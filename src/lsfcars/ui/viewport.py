"""Viewport 3D : interaction (caméras, sélection, gizmos) au-dessus du ``Renderer``.

Le widget ne modifie pas la scène lui-même : il émet ``selection_requested``,
``transforms_edited`` et ``edit_transform`` (mode Édition), appliqués par le contrôleur via
l'historique. En mode Édition, la sélection de sommets / arêtes / faces est portée par
l'``EditState`` partagé ; l'aperçu d'un glisser est un maillage temporaire jamais enregistré.
"""

from __future__ import annotations

import itertools
import math

import numpy as np
from PySide6.QtCore import QBuffer, QIODevice, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QKeyEvent, QMouseEvent, QResizeEvent, QWheelEvent
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QWidget

from lsfcars.core import diagnostics
from lsfcars.core.logging_setup import get_logger
from lsfcars.editor import edit_state as modes
from lsfcars.render.renderer import DrawItem, FrameData, GizmoDraw, Overlay, Renderer, gl_rgb
from lsfcars.scene import editmesh, gizmo, mathutils, picking
from lsfcars.scene.camera import VIEW_LABELS, OrbitCamera
from lsfcars.scene.gizmo import GizmoMode
from lsfcars.scene.graph import NodeKind
from lsfcars.scene.transform import Transform, decompose
from lsfcars.ui.design import tokens
from lsfcars.ui.design.components import LSIconButton, tooltip

log = get_logger(__name__)

SHADING_LABELS = {"solid": "Solide", "wireframe": "Filaire", "material": "Matériaux"}
_drag_ids = itertools.count(1)
PICK_RADIUS = 10.0  # pixels
EDIT_SELECTED = (*gl_rgb(tokens.ColorTokens.ELECTRIC), 1.0)
EDIT_IDLE = (*gl_rgb(tokens.ColorTokens.TEXT_SECONDARY), 0.55)
EDIT_FACE = (*gl_rgb(tokens.ColorTokens.ELECTRIC), 0.45)
ANCHOR_SELECTED = (*gl_rgb(tokens.ColorTokens.ELECTRIC), 1.0)
ANCHOR_IDLE = (*gl_rgb(tokens.ColorTokens.WARNING), 1.0)
OVERLAY_EDGE_LIMIT = 400_000


def _colored(points: np.ndarray, color: tuple) -> np.ndarray:
    data = np.empty((len(points), 7), np.float32)
    data[:, :3] = points
    data[:, 3:] = color
    return data


class _Drag:
    def __init__(
        self,
        axis: int,
        mode: GizmoMode,
        start: QPoint,
        pivot: np.ndarray,
        axes: np.ndarray,
        nodes: dict,
    ) -> None:
        self.axis = axis
        self.mode = mode
        self.start = start
        self.pivot = pivot
        self.axes = axes
        self.nodes = nodes  # id -> (transform local, monde, monde du parent)
        self.key = ("drag", next(_drag_ids))


class Viewport3D(QOpenGLWidget):
    selection_requested = Signal(list, str)  # ids, « replace » / « toggle » / « add »
    transforms_edited = Signal(dict, object)  # {id: Transform}, clé de fusion
    edit_transform = Signal(str, object)  # maillage, matrice locale 4x4 (fin d'un glisser en mode Édition)
    edit_mode_toggled = Signal()  # touche Tab
    frame_requested = Signal()
    gl_initialized = Signal(bool, str)
    tool_changed = Signal(str)
    view_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.camera = OrbitCamera()
        self.renderer = Renderer()
        self.session = None  # ProjectSession (lecture seule ici)
        self.tool = GizmoMode.SELECT
        self.shading = "material"
        self.grid_visible = True
        # Affichage non destructif (inspection) : isolation et vue éclatée n'altèrent pas la scène
        self.isolated: set[str] | None = None
        self.display_offsets: dict[str, np.ndarray] = {}
        # Transformations d'affichage (monde, héritées par les enfants) : aperçu de rotation des roues
        self.display_matrices: dict[str, np.ndarray] = {}
        self.hidden: set[str] = set()  # masquage temporaire (habitacle : carrosserie masquée)
        self.edit_state: modes.EditState | None = None
        self.edit_preview: tuple[str, object] | None = None  # (maillage, MeshData) pendant un glisser
        self.show_anchors = True
        self._overlay_cache: tuple[tuple, list[Overlay]] | None = None
        # Points d'extension (Emergency Studio) : superpositions, clic de placement, dépôt
        self.overlay_providers: list = []  # fonctions () -> list[Overlay]
        self.click_handler = None  # fonction (x, y) -> bool (True : clic consommé)
        self.drop_handler = None  # fonction (texte, x, y) -> bool
        self.drop_mime = "application/x-lsf-equipment"
        self._gl_error: str | None = None
        self._press: QPoint | None = None
        self._last = QPoint()
        self._button = Qt.MouseButton.NoButton
        self._moved = False
        self._drag: _Drag | None = None
        self._hover_axis: int | None = None
        self._keys: set[int] = set()
        self._fly_timer = QTimer(self)
        self._fly_timer.setInterval(16)
        self._fly_timer.timeout.connect(self._fly_step)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(320, 240)
        self._build_overlay()

    # --- Superpositions ------------------------------------------------------
    def _build_overlay(self) -> None:
        self.toolbar = QFrame(self)
        self.toolbar.setObjectName("LSViewportToolbar")
        bar = QHBoxLayout(self.toolbar)
        bar.setContentsMargins(6, 4, 6, 4)
        bar.setSpacing(2)
        self.tool_buttons: dict[GizmoMode, LSIconButton] = {}
        for mode, icon, key in (
            (GizmoMode.SELECT, "mouse-pointer-2", "Q"),
            (GizmoMode.TRANSLATE, "move", "W"),
            (GizmoMode.ROTATE, "rotate-3d", "E"),
            (GizmoMode.SCALE, "scale-3d", "R"),
        ):
            button = LSIconButton(icon, mode.label, checkable=True, size=16, shortcut=key)
            button.clicked.connect(lambda _=False, m=mode: self.set_tool(m))
            bar.addWidget(button)
            self.tool_buttons[mode] = button
        bar.addWidget(self._divider())
        self.shading_buttons: dict[str, LSIconButton] = {}
        for shading, icon in (("solid", "square"), ("wireframe", "frame"), ("material", "palette")):
            button = LSIconButton(
                icon,
                f"Mode {SHADING_LABELS[shading].lower()}",
                checkable=True,
                size=16,
                shortcut="Z",
            )
            button.clicked.connect(lambda _=False, s=shading: self.set_shading(s))
            bar.addWidget(button)
            self.shading_buttons[shading] = button
        bar.addWidget(self._divider())
        self.ortho_button = LSIconButton("square-dashed", "Vue orthographique", True, 16, "Pavé 5")
        self.ortho_button.clicked.connect(self.toggle_orthographic)
        self.free_button = LSIconButton("video", "Caméra libre (ZQSD/WASD + clic droit)", True, 16)
        self.free_button.clicked.connect(self.toggle_free_camera)
        self.views_button = LSIconButton("camera", "Vues prédéfinies", size=16)
        menu = QMenu(self.views_button)
        for name, shortcut in (
            ("front", "Pavé 1"),
            ("back", "Ctrl+Pavé 1"),
            ("right", "Pavé 3"),
            ("left", "Ctrl+Pavé 3"),
            ("top", "Pavé 7"),
            ("bottom", "Ctrl+Pavé 7"),
            ("perspective", ""),
        ):
            action = menu.addAction(f"{VIEW_LABELS[name]}\t{shortcut}")
            action.triggered.connect(lambda _=False, n=name: self.set_standard_view(n))
        self.views_button.setMenu(menu)
        self.views_button.setPopupMode(self.views_button.ToolButtonPopupMode.InstantPopup)
        self.frame_button = LSIconButton("scan", "Centrer sur la sélection", size=16, shortcut="F")
        self.frame_button.clicked.connect(self.frame_requested)
        self.grid_button = LSIconButton("grid-3x3", "Afficher la grille", True, 16)
        self.grid_button.setChecked(True)
        self.grid_button.clicked.connect(self.set_grid_visible)
        for button in (
            self.ortho_button,
            self.free_button,
            self.views_button,
            self.frame_button,
            self.grid_button,
        ):
            bar.addWidget(button)
        self.toolbar.adjustSize()

        self.stats_label = QLabel(self)
        self.stats_label.setObjectName("LSViewportHint")
        self.empty_label = QLabel("Importez un modèle 3D pour commencer\n(GLB, glTF, OBJ, FBX…)", self)
        self.empty_label.setObjectName("LSViewportHint")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_label = QLabel(self)
        self.error_label.setObjectName("LSViewportError")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        self._sync_buttons()

    def _divider(self) -> QFrame:
        line = QFrame()
        line.setFixedSize(1, 18)
        line.setStyleSheet(f"background: {tokens.BORDER};")
        return line

    def _layout_overlay(self) -> None:
        self.toolbar.adjustSize()
        self.toolbar.move(max((self.width() - self.toolbar.width()) // 2, 8), 10)
        self.stats_label.adjustSize()
        self.stats_label.move(
            self.width() - self.stats_label.width() - 12,
            self.height() - self.stats_label.height() - 12,
        )
        self.empty_label.adjustSize()
        self.empty_label.move(
            (self.width() - self.empty_label.width()) // 2,
            (self.height() - self.empty_label.height()) // 2,
        )
        if self.error_label.isVisible():
            self.error_label.setFixedWidth(max(min(560, self.width() - 40), 200))
            self.error_label.adjustSize()
            self.error_label.move(
                (self.width() - self.error_label.width()) // 2,
                (self.height() - self.error_label.height()) // 2,
            )

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._layout_overlay()

    def _sync_buttons(self) -> None:
        for mode, button in self.tool_buttons.items():
            button.setChecked(mode is self.tool)
        for shading, button in self.shading_buttons.items():
            button.setChecked(shading == self.shading)
        self.ortho_button.setChecked(self.camera.orthographic)
        self.free_button.setChecked(self.camera.mode == "free")
        self.grid_button.setChecked(self.grid_visible)

    # --- API ------------------------------------------------------------------
    @property
    def gl_ready(self) -> bool:
        return self.renderer.ready

    @property
    def gl_error(self) -> str | None:
        return self._gl_error

    def set_session(self, session) -> None:  # type: ignore[no-untyped-def]
        self.session = session
        self._drag = None
        self.refresh()

    def refresh(self) -> None:
        self._update_stats()
        self.update()

    def set_tool(self, mode: GizmoMode | str) -> None:
        self.tool = GizmoMode(mode)
        self._sync_buttons()
        self.tool_changed.emit(self.tool.value)
        self.update()

    def set_shading(self, shading: str) -> None:
        self.shading = shading
        self._sync_buttons()
        self.update()

    def cycle_shading(self) -> None:
        order = ["material", "solid", "wireframe"]
        self.set_shading(order[(order.index(self.shading) + 1) % len(order)])

    def set_grid_visible(self, visible: bool) -> None:
        self.grid_visible = bool(visible)
        self._sync_buttons()
        self.update()

    def toggle_orthographic(self) -> None:
        self.camera.orthographic = not self.camera.orthographic
        self._sync_buttons()
        self.view_changed.emit()
        self.update()

    def toggle_free_camera(self) -> None:
        self.camera.mode = "orbit" if self.camera.mode == "free" else "free"
        self._sync_buttons()
        self.view_changed.emit()
        self.update()

    def set_standard_view(self, name: str) -> None:
        self.camera.set_standard_view(name)
        self.view_changed.emit()
        self.update()

    def set_isolation(self, node_ids: set[str] | None) -> None:
        """Affiche uniquement ces maillages (None : tout). Ne modifie pas la scène."""
        self.isolated = set(node_ids) if node_ids is not None else None
        self.update()

    def set_display_offsets(self, offsets: dict[str, np.ndarray]) -> None:
        """Décalages d'affichage par maillage (vue éclatée). Ne modifie pas la scène."""
        self.display_offsets = {k: np.asarray(v, dtype=np.float64) for k, v in offsets.items()}
        self.update()

    def _display_matrix(self, node_id: str, world: np.ndarray) -> np.ndarray:
        offset = self.display_offsets.get(node_id)
        if offset is None:
            return world
        moved = world.copy()
        moved[:3, 3] += offset
        return moved

    def _displayed(self, node_id: str) -> bool:
        if node_id in self.hidden:
            return False
        return self.isolated is None or node_id in self.isolated

    def set_hidden(self, node_ids: set[str]) -> None:
        """Masquage temporaire d'affichage (ne modifie pas la visibilité enregistrée)."""
        self.hidden = set(node_ids)
        self.update()

    def set_display_matrices(self, matrices: dict[str, np.ndarray]) -> None:
        """Transformations monde d'affichage par nœud, héritées par les enfants (aperçu)."""
        self.display_matrices = {k: np.asarray(v, np.float64) for k, v in matrices.items()}
        self.update()

    def set_edit_state(self, state: modes.EditState) -> None:
        self.edit_state = state
        state.subscribe(self._on_edit_state)

    def _on_edit_state(self) -> None:
        self.edit_preview = None
        self._overlay_cache = None
        self.update()

    @property
    def editing(self) -> bool:
        state = self.edit_state
        return bool(state and state.editing and self.session and state.target in self.session.scene)

    def _world_of(self, node_id: str) -> np.ndarray:
        """Matrice monde affichée (transformations d'affichage et décalages compris)."""
        scene = self.session.scene
        chain = [node_id, *[a.id for a in scene.ancestors(node_id)]][::-1]
        world = np.eye(4)
        for item in chain:
            world = world @ scene.nodes[item].transform.matrix()
            if item in self.display_matrices:
                world = self.display_matrices[item] @ world
        return self._display_matrix(node_id, world)

    def _edit_mesh(self):  # type: ignore[no-untyped-def]
        if not self.editing:
            return None
        if self.edit_preview is not None and self.edit_preview[0] == self.edit_state.target:
            return self.edit_preview[1]
        return self.session.geometry_for(self.session.scene.nodes[self.edit_state.target])

    def frame_bounds(self, bounds: tuple[np.ndarray, np.ndarray] | None) -> None:
        if bounds is None:
            self.camera.reset()
        else:
            self.camera.frame(*bounds)
        self.view_changed.emit()
        self.update()

    def grab_thumbnail(self, width: int = 480, height: int = 270) -> bytes | None:
        if not self.gl_ready:
            return None
        image = self.grabFramebuffer().scaled(
            width,
            height,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        return bytes(buffer.data())

    # --- Données de la scène ----------------------------------------------------
    def _selected_subtree(self) -> set[str]:
        if self.session is None:
            return set()
        scene = self.session.scene
        result: set[str] = set()
        for node_id in self.session.selection.ids:
            if node_id in scene:
                result.update(n.id for n in scene.subtree(node_id))
        return result

    def draw_items(self) -> list[DrawItem]:
        session = self.session
        if session is None:
            return []
        scene = session.scene
        selected = self._selected_subtree()
        items: list[DrawItem] = []
        worlds: dict[str | None, np.ndarray] = {None: np.eye(4)}
        visible: dict[str | None, bool] = {None: True}
        for node in scene.walk():  # parents avant enfants : matrices cumulées une seule fois
            worlds[node.id] = worlds[node.parent_id] @ node.transform.matrix()
            if node.id in self.display_matrices:
                worlds[node.id] = self.display_matrices[node.id] @ worlds[node.id]
            visible[node.id] = visible[node.parent_id] and node.visible
            if node.kind is not NodeKind.MESH or not visible[node.id] or not self._displayed(node.id):
                continue
            mesh = session.geometry_for(node)
            if self.edit_preview is not None and self.edit_preview[0] == node.id:
                mesh = self.edit_preview[1]
            if mesh is None:
                continue
            material = scene.material_for(node.id)
            world = self._display_matrix(node.id, worlds[node.id])
            editing_this = self.editing and node.id == self.edit_state.target
            item = DrawItem(mesh, world, selected=node.id in selected and not editing_this)
            if material is not None:
                item.base_color = material.base_color
                item.roughness, item.metallic = material.roughness, material.metallic
                item.opacity = material.opacity
                if material.texture:
                    path = session.project.project_dir / material.texture
                    item.texture = path if path.is_file() else None
                if material.normal_texture:
                    path = session.project.project_dir / material.normal_texture
                    item.normal_texture = path if path.is_file() else None
                item.normal_strength = material.normal_strength
                item.uv_scale, item.uv_offset = material.uv_scale, material.uv_offset
            items.append(item)
        return items

    # --- Superpositions (mode Édition, ancrages) ------------------------------------
    def overlays(self) -> list[Overlay]:
        result: list[Overlay] = []
        if self.session is None:
            return result
        if self.show_anchors:
            anchors = self._anchor_overlay()
            if anchors is not None:
                result.append(anchors)
        if self.editing:
            result.extend(self._edit_overlays())
        for provider in self.overlay_providers:
            try:
                result.extend(provider())
            except Exception as exc:  # noqa: BLE001 (une superposition défaillante ne bloque pas le rendu)
                log.warning("Superposition ignorée : %s", exc)
        return result

    # --- Glisser-déposer (équipements) ------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self.drop_handler is not None and event.mimeData().hasFormat(self.drop_mime):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if self.drop_handler is not None and event.mimeData().hasFormat(self.drop_mime):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        if self.drop_handler is None or not event.mimeData().hasFormat(self.drop_mime):
            event.ignore()
            return
        text = bytes(event.mimeData().data(self.drop_mime)).decode("utf-8")
        position = event.position()
        if self.drop_handler(text, position.x(), position.y()):
            event.acceptProposedAction()

    def screen_ray(self, x: float, y: float) -> tuple[np.ndarray, np.ndarray]:
        """Rayon monde passant par le pixel (x, y)."""
        return picking.ray_from_screen(self.camera, x, y, self.width(), self.height())

    def _anchor_overlay(self) -> Overlay | None:
        scene = self.session.scene
        selected = set(self.session.selection.ids)
        lines, points = [], []
        for node in scene.anchor_nodes():
            if not scene.effective_visible(node.id) or node.id in self.hidden:
                continue
            world = self._world_of(node.id)
            origin = world[:3, 3]
            size = gizmo.world_size(self.camera, origin, self.height()) * 40.0 / gizmo.GIZMO_PIXELS  # ~40 px
            for axis in range(3):
                direction = world[:3, axis]
                norm = np.linalg.norm(direction)
                tip = origin + direction / (norm if norm > 1e-9 else 1.0) * size
                color = (*gl_rgb((tokens.AXIS_X, tokens.AXIS_Y, tokens.AXIS_Z)[axis]), 1.0)
                lines += [(*origin, *color), (*tip, *color)]
            points.append((*origin, *(ANCHOR_SELECTED if node.id in selected else ANCHOR_IDLE)))
        if not points:
            return None
        return Overlay(np.asarray(points, np.float32), np.asarray(lines, np.float32), None, 9.0, xray=True)

    def _edit_overlays(self) -> list[Overlay]:
        state = self.edit_state
        mesh = self._edit_mesh()
        if mesh is None:
            return []
        world = self._world_of(state.target)
        key = (id(mesh), state.element, hash(frozenset(state.selection)), world.tobytes(), state.xray)
        if self._overlay_cache is not None and self._overlay_cache[0] == key:
            return self._overlay_cache[1]
        topo = editmesh.topology(mesh)
        positions = mathutils.transform_points(world, topo.positions).astype(np.float32)
        selected_vertices = editmesh.to_vertices(mesh, state.element, state.selection)
        overlays: list[Overlay] = []
        if state.element == editmesh.FACE and state.selection:
            faces = np.asarray(sorted(f for f in state.selection if 0 <= f < len(topo.tri)), np.int64)
            if len(faces):
                overlays.append(
                    Overlay(
                        triangles=_colored(positions[topo.tri[faces]].reshape(-1, 3), EDIT_FACE),
                        xray=state.xray,
                    )
                )
        if len(topo.edges) <= OVERLAY_EDGE_LIMIT:
            mask = np.zeros(topo.vertex_count, bool)
            mask[selected_vertices] = True
            chosen = (
                mask[topo.edges].all(axis=1)
                if state.element != editmesh.VERTEX
                else mask[topo.edges].any(axis=1)
            )
            if state.element == editmesh.EDGE:
                wanted = {tuple(e) for e in state.selection}
                chosen = np.array([tuple(e) in wanted for e in topo.edges.tolist()], bool)
            idle = positions[topo.edges[~chosen]].reshape(-1, 3)
            hot = positions[topo.edges[chosen]].reshape(-1, 3)
            lines = np.vstack([_colored(idle, EDIT_IDLE), _colored(hot, EDIT_SELECTED)])
            overlays.append(Overlay(lines=lines, xray=state.xray))
        if state.element == editmesh.VERTEX:
            mask = np.zeros(topo.vertex_count, bool)
            mask[selected_vertices] = True
            overlays.append(
                Overlay(points=_colored(positions[~mask], EDIT_IDLE), point_size=5.0, xray=state.xray)
            )
            overlays.append(
                Overlay(points=_colored(positions[mask], EDIT_SELECTED), point_size=8.0, xray=True)
            )
        self._overlay_cache = (key, overlays)
        return overlays

    def _update_stats(self) -> None:
        session = self.session
        if session is None:
            self.stats_label.setText("")
            self.empty_label.show()
        else:
            triangles, _vertices, meshes = session.stats()
            count = len(session.selection)
            text = f"{triangles:,} triangles · {meshes} maillages".replace(",", " ")
            if count:
                text += f" · {count} sélectionné(s)"
            if self.renderer.last_frame_ms:
                text += f" · {self.renderer.last_frame_ms:.1f} ms"
            self.stats_label.setText(text)
            self.empty_label.setVisible(meshes == 0)
        self._layout_overlay()

    # --- OpenGL ------------------------------------------------------------
    def initializeGL(self) -> None:  # noqa: N802
        try:
            info = self.renderer.initialize(self.context())
            diagnostics.set_gl_info(info)
            log.info("OpenGL : %s — %s", info["Moteur de rendu"], info["Version"])
            self.context().aboutToBeDestroyed.connect(self._release_gl)
            self.gl_initialized.emit(True, info["Moteur de rendu"])
        except Exception as exc:  # pilote absent, contexte trop ancien, shaders refusés…
            self._gl_error = (
                f"Le rendu 3D n'a pas pu démarrer.\n{exc}\n\nMettez à jour le "
                "pilote graphique ou lancez l'application avec --software-gl."
            )
            diagnostics.set_gl_info({"État": "échec d'initialisation", "Erreur": str(exc)})
            log.error("Échec de l'initialisation OpenGL : %s", exc)
            self.error_label.setText(self._gl_error)
            self.error_label.show()
            self._layout_overlay()
            self.gl_initialized.emit(False, str(exc))

    def _release_gl(self) -> None:
        if self.renderer.ready:
            self.makeCurrent()
            self.renderer.release()
            self.doneCurrent()

    def paintGL(self) -> None:  # noqa: N802
        if not self.renderer.ready:
            return
        items = self.draw_items()
        aspect = self.width() / max(self.height(), 1)
        view = self.camera.view_matrix()
        frame = FrameData(
            view=view,
            proj=self.camera.projection_matrix(aspect),
            view_rotation=view[:3, :3],
            width=self.width(),
            height=self.height(),
            ratio=self.devicePixelRatioF(),
            items=items,
            shading=self.shading,
            grid=self.grid_visible,
            grid_center=self.camera.target,
            grid_radius=max(self.camera.distance * 4.0, 30.0),
            gizmo=self._gizmo_draw(),
            overlays=self.overlays(),
        )
        self.renderer.render(frame)
        self.renderer.collect_garbage({id(i.mesh) for i in items})

    # --- Gizmo ----------------------------------------------------------------
    def _gizmo_targets(self) -> list[str]:
        if self.session is None or self.tool is GizmoMode.SELECT or self.editing:
            return []
        scene = self.session.scene
        return scene.top_level(self.session.editable(self.session.selection.ids))

    def _edit_gizmo_frame(self) -> tuple[np.ndarray, np.ndarray] | None:
        state = self.edit_state
        if self.tool is GizmoMode.SELECT or not state.selection:
            return None
        mesh = self._edit_mesh()
        center = editmesh.selection_center(mesh, state.element, state.selection) if mesh is not None else None
        if center is None:
            return None
        world = self._world_of(state.target)
        pivot = mathutils.transform_points(world, center[None, :])[0]
        axes = np.eye(3)
        if self.tool is GizmoMode.SCALE:
            basis = world[:3, :3]
            norms = np.linalg.norm(basis, axis=0)
            axes = (basis / np.where(norms < 1e-9, 1, norms)).T
        return pivot, axes

    def _gizmo_frame(self) -> tuple[np.ndarray, np.ndarray] | None:
        if self.editing:
            return self._edit_gizmo_frame()
        targets = self._gizmo_targets()
        if not targets:
            return None
        scene = self.session.scene
        bounds = self.session.world_bounds(targets, only_visible=False)
        pivot = (bounds[0] + bounds[1]) / 2 if bounds is not None else scene.world_matrix(targets[-1])[:3, 3]
        axes = np.eye(3)
        if self.tool is GizmoMode.SCALE:  # axes locaux de l'élément actif
            basis = scene.world_matrix(targets[-1])[:3, :3]
            norms = np.linalg.norm(basis, axis=0)
            axes = (basis / np.where(norms < 1e-9, 1, norms)).T
        return pivot, axes

    def _gizmo_draw(self) -> GizmoDraw | None:
        frame = self._gizmo_frame()
        if frame is None:
            return None
        pivot, axes = frame
        size = gizmo.world_size(self.camera, pivot, self.height())
        hover = self._drag.axis if self._drag else self._hover_axis
        return GizmoDraw(self.tool.value, pivot, axes, size, hover)

    def _begin_drag(self, pos: QPoint) -> bool:
        frame = self._gizmo_frame()
        if frame is None:
            return False
        pivot, axes = frame
        axis = gizmo.hit_test(
            self.tool, self.camera, pivot, axes, (pos.x(), pos.y()), self.width(), self.height()
        )
        if axis is None:
            return False
        scene = self.session.scene
        if self.editing:  # glisser sur la sélection de sommets : maillage d'origine mémorisé
            mesh = self.session.geometry_for(scene.nodes[self.edit_state.target])
            nodes = {"__edit__": (mesh, self._world_of(self.edit_state.target), None)}
            self._drag = _Drag(axis, self.tool, pos, pivot, axes, nodes)
            return True
        nodes = {
            node_id: (
                scene.nodes[node_id].transform.copy(),
                scene.world_matrix(node_id),
                scene.parent_world_matrix(node_id),
            )
            for node_id in self._gizmo_targets()
        }
        self._drag = _Drag(axis, self.tool, pos, pivot, axes, nodes)
        return True

    def _edit_drag_matrix(self, drag: _Drag, pos: QPoint, snap: bool) -> np.ndarray:
        """Matrice monde du glisser en cours (translation, rotation ou échelle autour du pivot)."""
        args = (
            self.camera,
            drag.pivot,
            drag.axes[drag.axis],
            (drag.start.x(), drag.start.y()),
            (pos.x(), pos.y()),
            self.width(),
            self.height(),
        )
        if drag.mode is GizmoMode.TRANSLATE:
            delta = gizmo.drag_translation(*args)
            if snap:
                delta = np.round(delta / 0.01) * 0.01
            return mathutils.translation(delta)
        if drag.mode is GizmoMode.ROTATE:
            angle = gizmo.drag_rotation(*args)
            if snap:
                angle = math.radians(round(math.degrees(angle) / 15.0) * 15.0)
            return gizmo.rotation_about(drag.axes[drag.axis], angle, drag.pivot)
        factor = gizmo.drag_scale(*args)
        if snap:
            factor = max(round(factor / 0.1) * 0.1, 0.1)
        axis = drag.axes[drag.axis]
        stretch = np.eye(3) + (factor - 1.0) * np.outer(axis, axis)
        matrix = np.eye(4)
        matrix[:3, :3] = stretch
        return mathutils.translation(drag.pivot) @ matrix @ mathutils.translation(-drag.pivot)

    def _update_edit_drag(self, pos: QPoint, snap: bool) -> None:
        drag = self._drag
        mesh, world, _ = drag.nodes["__edit__"]
        local = np.linalg.inv(world) @ self._edit_drag_matrix(drag, pos, snap) @ world
        drag.local = local  # type: ignore[attr-defined]
        try:
            preview = editmesh.transform_elements(
                mesh, self.edit_state.element, self.edit_state.selection, local
            )
        except editmesh.EditError:
            return
        self.edit_preview = (self.edit_state.target, preview.mesh)
        self._overlay_cache = None
        self.update()

    def _update_drag(self, pos: QPoint, snap: bool) -> None:
        drag = self._drag
        assert drag is not None
        if "__edit__" in drag.nodes:
            self._update_edit_drag(pos, snap)
            return
        args = (
            self.camera,
            drag.pivot,
            drag.axes[drag.axis],
            (drag.start.x(), drag.start.y()),
            (pos.x(), pos.y()),
            self.width(),
            self.height(),
        )
        changes: dict[str, Transform] = {}
        if drag.mode is GizmoMode.TRANSLATE:
            delta = gizmo.drag_translation(*args)
            if snap:
                delta = np.round(delta / 0.1) * 0.1
            for node_id, (local, _world, parent) in drag.nodes.items():
                moved = local.copy()
                offset = np.linalg.inv(parent[:3, :3]) @ delta
                moved.translation = [a + b for a, b in zip(local.translation, offset, strict=True)]
                changes[node_id] = moved
        elif drag.mode is GizmoMode.ROTATE:
            angle = gizmo.drag_rotation(*args)
            if snap:
                angle = math.radians(round(math.degrees(angle) / 15.0) * 15.0)
            rotation = gizmo.rotation_about(drag.axes[drag.axis], angle, drag.pivot)
            for node_id, (local, world, parent) in drag.nodes.items():
                rotated = decompose(np.linalg.inv(parent) @ rotation @ world)
                rotated.scale = list(local.scale)
                changes[node_id] = rotated
        else:
            factor = gizmo.drag_scale(*args)
            if snap:
                factor = max(round(factor / 0.1) * 0.1, 0.1)
            for node_id, (local, _world, _parent) in drag.nodes.items():
                scaled = local.copy()
                scaled.scale[drag.axis] = local.scale[drag.axis] * factor
                changes[node_id] = scaled
        self.transforms_edited.emit(changes, drag.key)

    # --- Interaction ----------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.setFocus()
        pos = event.position().toPoint()
        self._press, self._last, self._button, self._moved = pos, pos, event.button(), False
        if event.button() == Qt.MouseButton.LeftButton and self._begin_drag(pos):
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position().toPoint()
        if self._press is None:  # survol : surbrillance de la poignée
            frame = self._gizmo_frame()
            axis = None
            if frame is not None:
                axis = gizmo.hit_test(
                    self.tool,
                    self.camera,
                    frame[0],
                    frame[1],
                    (pos.x(), pos.y()),
                    self.width(),
                    self.height(),
                )
            if axis != self._hover_axis:
                self._hover_axis = axis
                self.update()
            return
        delta = pos - self._last
        self._last = pos
        if (pos - self._press).manhattanLength() > 3:
            self._moved = True
        if self._drag is not None:
            snap = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            self._update_drag(pos, snap)
            return
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        left = self._button == Qt.MouseButton.LeftButton
        free = self.camera.mode == "free"
        if free and self._button in (Qt.MouseButton.RightButton, Qt.MouseButton.LeftButton):
            self.camera.look(-delta.x() * 0.25, -delta.y() * 0.25)
        elif left and not shift:
            self.camera.orbit(-delta.x() * 0.4, delta.y() * 0.4)
        elif (left and shift) or self._button in (
            Qt.MouseButton.RightButton,
            Qt.MouseButton.MiddleButton,
        ):
            self.camera.pan(delta.x(), delta.y(), self.height())
        self.view_changed.emit()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag is not None:
            drag, self._drag = self._drag, None
            local = getattr(drag, "local", None)
            if "__edit__" in drag.nodes and local is not None and self.edit_state.target:
                self.edit_transform.emit(self.edit_state.target, local)
            self.edit_preview = None
            self._overlay_cache = None
        elif self._button == Qt.MouseButton.LeftButton and not self._moved:
            pos = event.position()
            mods = event.modifiers()
            if mods & Qt.KeyboardModifier.ControlModifier:
                mode = "toggle"
            elif mods & Qt.KeyboardModifier.ShiftModifier:
                mode = "add"
            else:
                mode = "replace"
            if self.click_handler is not None and self.click_handler(pos.x(), pos.y()):
                pass  # clic consommé (placement d'équipement)
            elif self.editing:
                picked_element = self.pick_element(pos.x(), pos.y())
                self.edit_state.select([picked_element] if picked_element is not None else [], mode)
            else:
                picked = self.pick(pos.x(), pos.y())
                self.selection_requested.emit([picked] if picked else [], mode)
        self._press = None
        self._button = Qt.MouseButton.NoButton
        self.update()

    def pick_element(self, x: float, y: float):  # type: ignore[no-untyped-def]
        """Sommet, arête ou face du maillage édité sous le pixel (x, y), ou None."""
        mesh = self._edit_mesh()
        if mesh is None:
            return None
        state = self.edit_state
        world = self._world_of(state.target)
        topo = editmesh.topology(mesh)
        if state.element == editmesh.FACE:
            origin, direction = picking.ray_from_screen(self.camera, x, y, self.width(), self.height())
            inverse = np.linalg.inv(world)
            hit = editmesh.ray_triangle(
                inverse[:3, :3] @ origin + inverse[:3, 3], inverse[:3, :3] @ direction, mesh
            )
            return hit[0] if hit else None
        positions = mathutils.transform_points(world, topo.positions)
        screen = gizmo.project(self.camera, positions, self.width(), self.height())
        if state.element == editmesh.VERTEX:
            distances = np.linalg.norm(screen - (x, y), axis=1)
            distances[~np.isfinite(distances)] = np.inf
            near = np.flatnonzero(distances <= PICK_RADIUS)
            if not len(near):
                return None
            eye = self.camera.eye()  # le plus proche de la caméra parmi les candidats
            depth = np.linalg.norm(positions[near] - eye, axis=1)
            return int(near[np.argmin(depth)])
        index = editmesh.nearest_screen_segment(
            screen[topo.edges[:, 0]], screen[topo.edges[:, 1]], (x, y), PICK_RADIUS
        )
        return None if index is None else (int(topo.edges[index, 0]), int(topo.edges[index, 1]))

    def pick_anchor(self, x: float, y: float) -> str | None:
        if self.session is None or not self.show_anchors:
            return None
        scene = self.session.scene
        anchors = [
            n
            for n in scene.anchor_nodes()
            if scene.effective_visible(n.id) and not scene.effective_locked(n.id)
        ]
        if not anchors:
            return None
        origins = np.array([self._world_of(n.id)[:3, 3] for n in anchors])
        index = editmesh.nearest_screen_point(
            gizmo.project(self.camera, origins, self.width(), self.height()), (x, y), PICK_RADIUS
        )
        return None if index is None else anchors[index].id

    def pick(self, x: float, y: float) -> str | None:
        """Point d'ancrage, sinon maillage visible et non verrouillé sous le pixel (x, y)."""
        if self.session is None:
            return None
        anchor = self.pick_anchor(x, y)
        if anchor is not None:
            return anchor
        scene = self.session.scene
        origin, direction = picking.ray_from_screen(self.camera, x, y, self.width(), self.height())
        candidates = []
        for node in scene.mesh_nodes():
            if not scene.effective_visible(node.id) or scene.effective_locked(node.id):
                continue
            if not self._displayed(node.id):
                continue
            mesh = self.session.geometry_for(node)
            if mesh is not None:
                candidates.append((node.id, self._world_of(node.id), [mesh]))
        return picking.pick(origin, direction, candidates)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.camera.zoom(steps)
            self.view_changed.emit()
            self.update()

    _FLY_KEYS = {
        Qt.Key.Key_W,
        Qt.Key.Key_Z,
        Qt.Key.Key_S,
        Qt.Key.Key_A,
        Qt.Key.Key_Q,
        Qt.Key.Key_D,
        Qt.Key.Key_E,
        Qt.Key.Key_Space,
        Qt.Key.Key_C,
    }

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if self.camera.mode == "free" and key in self._FLY_KEYS and not ctrl:
            if not event.isAutoRepeat():
                self._keys.add(key)
                self._fly_timer.start()
            return
        views = {
            Qt.Key.Key_1: ("back" if ctrl else "front"),
            Qt.Key.Key_3: ("left" if ctrl else "right"),
            Qt.Key.Key_7: ("bottom" if ctrl else "top"),
        }
        tools = {
            Qt.Key.Key_Q: GizmoMode.SELECT,
            Qt.Key.Key_W: GizmoMode.TRANSLATE,
            Qt.Key.Key_E: GizmoMode.ROTATE,
            Qt.Key.Key_R: GizmoMode.SCALE,
        }
        if key == Qt.Key.Key_Tab:
            self.edit_mode_toggled.emit()
        elif key == Qt.Key.Key_A and not ctrl and self.editing:
            mesh = self._edit_mesh()
            if mesh is not None:
                everything = editmesh.all_elements(mesh, self.edit_state.element)
                self.edit_state.select(set() if self.edit_state.selection == everything else everything)
        elif key == Qt.Key.Key_F and not ctrl:
            self.frame_requested.emit()
        elif key in views:
            self.set_standard_view(views[key])
        elif key == Qt.Key.Key_5:
            self.toggle_orthographic()
        elif key == Qt.Key.Key_Z and not ctrl:
            self.cycle_shading()
        elif key in tools and not ctrl:
            self.set_tool(tools[key])
        else:
            super().keyPressEvent(event)

    def focusNextPrevChild(self, next: bool) -> bool:  # noqa: N802, A002
        return False  # Tab bascule le mode Édition au lieu de déplacer le focus

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if not event.isAutoRepeat():
            self._keys.discard(event.key())
            if not self._keys:
                self._fly_timer.stop()
        super().keyReleaseEvent(event)

    def _fly_step(self) -> None:
        if not self._keys or self.camera.mode != "free":
            self._fly_timer.stop()
            return
        speed = max(self.camera.distance * 0.9, 2.0) * self._fly_timer.interval() / 1000.0
        keys = self._keys
        forward = (Qt.Key.Key_W in keys or Qt.Key.Key_Z in keys) - (Qt.Key.Key_S in keys)
        right = (Qt.Key.Key_D in keys) - (Qt.Key.Key_A in keys or Qt.Key.Key_Q in keys)
        up = (Qt.Key.Key_E in keys or Qt.Key.Key_Space in keys) - (Qt.Key.Key_C in keys)
        self.camera.fly(forward * speed, right * speed, up * speed)
        self.view_changed.emit()
        self.update()


def describe_view(camera: OrbitCamera) -> str:
    projection = "orthographique" if camera.orthographic else "perspective"
    mode = "libre" if camera.mode == "free" else "orbitale"
    return f"Caméra {mode}, {projection}"


__all__ = ["SHADING_LABELS", "Viewport3D", "describe_view", "tooltip"]
