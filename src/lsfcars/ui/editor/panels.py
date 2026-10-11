"""Panneaux du Vehicle Editor : outils de modélisation (3 modes), géométrie, ancrages, ateliers
(Bodywork Studio, Wheel Editor, Interior Studio), historique et compatibilité FiveM.

Chaque bouton appelle une opération réelle du contrôleur ou de ``VehicleEditor`` ; un outil
indisponible (biseau sans Blender) est désactivé avec son explication.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lsfcars.editor import compat, vehicle
from lsfcars.editor import edit_state as modes
from lsfcars.editor.blender_ops import bevel_available
from lsfcars.editor.vehicle import ANCHOR_CONSTRAINTS, ANCHOR_TYPES, AXIS_NAMES, VehicleAxes
from lsfcars.project import restore_points
from lsfcars.scene import editmesh, mathutils
from lsfcars.scene.graph import NodeKind
from lsfcars.scene.transform import decompose
from lsfcars.ui.design import icons
from lsfcars.ui.design.components import (
    LSBadge,
    LSButton,
    LSInput,
    LSPropertyField,
    LSSelect,
    eyebrow,
    label,
    tooltip,
)

ID_ROLE = Qt.ItemDataRole.UserRole
AXES = [(name, index) for index, name in enumerate(AXIS_NAMES)]


# --- Petits constructeurs ----------------------------------------------------------------


def scroll(widget: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setWidget(widget)
    return area


def spin(
    value: float, minimum: float, maximum: float, step: float, decimals: int = 3, suffix: str = ""
) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setSingleStep(step)
    box.setDecimals(decimals)
    box.setValue(value)
    if suffix:
        box.setSuffix(suffix)
    return box


def button(
    text: str, icon: str | None, slot: Callable[[], object], tip: str = "", variant: str = "secondary"
) -> LSButton:
    widget = LSButton(text, variant, icon, True)
    widget.clicked.connect(lambda: slot())
    if tip:
        tooltip(widget, tip)
    return widget


class Section(QWidget):
    """Bloc titré d'un panneau d'outils."""

    def __init__(self, title: str, hint: str = "") -> None:
        super().__init__()
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(0, 6, 0, 6)
        self.body.setSpacing(6)
        self.body.addWidget(eyebrow(title))
        if hint:
            self.body.addWidget(label(hint, "faint", wrap=True))

    def row(self, *widgets: QWidget, stretch: bool = False) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(6)
        for widget in widgets:
            layout.addWidget(widget)
        if stretch:
            layout.addStretch(1)
        self.body.addLayout(layout)
        return layout

    def add(self, widget: QWidget) -> QWidget:
        self.body.addWidget(widget)
        return widget


class Page(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(12, 8, 12, 12)
        self.layout_.setSpacing(4)

    def section(self, title: str, hint: str = "") -> Section:
        section = Section(title, hint)
        self.layout_.addWidget(section)
        return section

    def finish(self) -> None:
        self.layout_.addStretch(1)


# --- Outils de modélisation ----------------------------------------------------------------


class ModelingTools(QStackedWidget):
    """Outils contextuels du mode actif : Objet, Édition ou Composant."""

    def __init__(self, controller, viewport, open_replace: Callable[[], None]) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.controller = controller
        self.viewport = viewport
        self.open_replace = open_replace
        self.object_page = self._object_page()
        self.edit_page = self._edit_page()
        self.component_page = self._component_page()
        for page in (self.object_page, self.edit_page, self.component_page):
            self.addWidget(scroll(page))
        controller.edit_changed.connect(self.refresh)
        controller.selection_changed.connect(self.refresh)
        controller.session_changed.connect(self.refresh)
        controller.busy_changed.connect(self._on_busy)
        self.refresh()

    @property
    def editor(self):  # type: ignore[no-untyped-def]
        return self.controller.editor

    def _sel(self) -> list[str]:
        return self.controller.selected()

    # Mode Objet -------------------------------------------------------------------------
    def _object_page(self) -> Page:
        page = Page()
        ctl = self.controller
        edit = page.section("Objet", "Sélection, transformations (W / E / R), hiérarchie dans l'explorateur.")
        edit.row(
            button("Dupliquer", "copy-plus", ctl.duplicate_selected, "Ctrl+D"),
            button(
                "Miroir",
                "copy",
                self.mirror,
                "Duplication miroir par rapport au plan de symétrie du véhicule",
            ),
        )
        edit.row(
            button("Grouper", "group", ctl.group_selected, "Ctrl+G"),
            button("Dégrouper", "ungroup", ctl.ungroup_selected, "Ctrl+Maj+G"),
            button("", "trash-2", ctl.delete_selected, "Supprimer (Suppr)", "danger"),
        )
        edit.row(
            button("Masquer", "eye-off", lambda: ctl.set_visible(self._sel(), False)),
            button("Afficher", "eye", lambda: ctl.set_visible(self._sel(), True)),
            button("", "lock", lambda: ctl.set_locked(self._sel(), True), "Verrouiller"),
            button("", "lock-open", lambda: ctl.set_locked(self._sel(), False), "Déverrouiller"),
        )
        align = page.section("Alignement sur un plan", "Aligne les objets sélectionnés sur un même plan.")
        self.align_axis = LSSelect(AXES)
        self.align_axis.setCurrentIndex(1)
        align.row(
            self.align_axis,
            button("Min", None, lambda: self._align("min")),
            button("Centre", None, lambda: self._align("center")),
            button("Max", None, lambda: self._align("max")),
        )
        proportions = page.section("Proportions", "Échelle par axe autour du centre de la sélection.")
        self.proportions = LSPropertyField("Facteurs", minimum=0.01, maximum=100, step=0.05)
        self.proportions.set_value([1.0, 1.0, 1.0])
        proportions.add(self.proportions)
        proportions.row(button("Appliquer", "scale-3d", self._apply_proportions), stretch=True)
        axes = page.section(
            "Axes du véhicule", "Utilisés par la symétrie, les roues et le placement des pièces."
        )
        self.lateral = LSSelect(AXES)
        self.longitudinal = LSSelect(AXES)
        self.forward = LSSelect([("Avant vers −", -1), ("Avant vers +", 1)])
        self.mirror_origin = spin(0.0, -100, 100, 0.01, 3, " m")
        grid = QGridLayout()
        rows = (
            ("Latéral (symétrie)", self.lateral),
            ("Longitudinal", self.longitudinal),
            ("Sens", self.forward),
            ("Plan de symétrie", self.mirror_origin),
        )
        for row, (title, widget) in enumerate(rows):
            grid.addWidget(label(title, "muted"), row, 0)
            grid.addWidget(widget, row, 1)
        axes.body.addLayout(grid)
        axes.row(button("Appliquer les axes", "check", self._apply_axes), stretch=True)
        page.finish()
        return page

    def mirror(self) -> None:
        if self.editor is not None:
            self.controller.run("Duplication miroir", lambda: self.editor.mirror_duplicate(self._sel()))

    def _align(self, mode: str) -> None:
        axis = self.align_axis.currentData()
        self.controller.run("Alignement", lambda: self.editor.align_objects(self._sel(), axis, mode))

    def _apply_proportions(self) -> None:
        factors = self.proportions.value()
        self.controller.run("Proportions", lambda: self.editor.scale_proportions(self._sel(), factors))

    def _apply_axes(self) -> None:
        if self.editor is None:
            return
        axes = VehicleAxes(
            self.lateral.currentData(),
            self.longitudinal.currentData(),
            self.forward.currentData(),
            self.mirror_origin.value(),
        )
        if axes.lateral_axis == axes.longitudinal_axis:
            self.controller.notify.emit(
                "Axes du véhicule", "Les axes latéral et longitudinal doivent différer.", "warning"
            )
            return
        self.editor.set_axes(axes)
        self.controller.state_changed.emit()
        self.controller.notify.emit("Axes du véhicule", "Réglages enregistrés dans le projet.", "success")

    # Mode Édition ------------------------------------------------------------------------
    def _edit_page(self) -> Page:
        page = Page()
        self.edit_target = label("Aucun maillage en édition", "muted", wrap=True)
        page.layout_.addWidget(self.edit_target)
        select = page.section("Sélection", "Clic, Maj+clic (ajout), Ctrl+clic (bascule), A : tout.")
        self.element_group = QButtonGroup(self)
        self.element_buttons: dict[str, LSButton] = {}
        row = []
        for element in (editmesh.VERTEX, editmesh.EDGE, editmesh.FACE):
            widget = LSButton(editmesh.ELEMENT_LABELS[element], "ghost", None, True)
            widget.setCheckable(True)
            widget.setProperty("chip", True)
            widget.clicked.connect(
                lambda _=False, e=element: self.controller.edit.set_element(e, self.controller.edit_mesh())
            )
            self.element_group.addButton(widget)
            self.element_buttons[element] = widget
            row.append(widget)
        select.row(*row)
        self.xray = QCheckBox("Sélection à travers (rayons X)")
        self.xray.toggled.connect(self._set_xray)
        select.add(self.xray)
        select.row(
            button("Tout", None, lambda: self._select("all")),
            button("Aucun", None, lambda: self._select("none")),
            button("Inverser", None, lambda: self._select("invert")),
        )
        select.row(
            button("Étendre", None, lambda: self._select("grow"), "Ajoute les éléments voisins"),
            button("Liés", None, lambda: self._select("linked"), "Toute la partie connexe"),
            button(
                "Coplanaires", None, lambda: self._select("coplanar"), "Faces voisines de même orientation"
            ),
        )
        self.selection_info = label("", "faint")
        select.add(self.selection_info)
        transform = page.section("Transformation", "Ou glissez le gizmo (W / E / R) dans le viewport.")
        self.move = LSPropertyField("Déplacer", suffix=" m", step=0.01)
        self.rotate = LSPropertyField("Pivoter", minimum=-360, maximum=360, step=5, decimals=1, suffix="°")
        self.scale = LSPropertyField("Échelle", minimum=0.001, maximum=1000, step=0.05)
        self.scale.set_value([1.0, 1.0, 1.0])
        for field in (self.move, self.rotate, self.scale):
            transform.add(field)
        transform.row(
            button("Déplacer", "move", self._move),
            button("Pivoter", "rotate-3d", self._rotate),
            button("Échelle", "scale-3d", self._scale),
        )
        ops = page.section("Opérations")
        self.extrude_distance = spin(0.1, -10, 10, 0.01, 3, " m")
        ops.row(
            self.extrude_distance,
            button("Extruder", "plus", self._extrude, "Extrusion de région le long de la normale"),
        )
        self.inset_amount = spin(0.2, 0.01, 0.95, 0.05, 2)
        ops.row(
            self.inset_amount,
            button("Inset", "square-dashed", self._inset, "Réduction vers le centre avec bande de faces"),
        )
        self.bevel_width = spin(0.02, 0.001, 1.0, 0.005, 3, " m")
        self.bevel_segments = QSpinBox()
        self.bevel_segments.setRange(1, 8)
        self.bevel_segments.setValue(2)
        self.bevel_button = button("Biseau", "shapes", self._bevel)
        self.bevel_cancel = button(
            "", "x", self.controller.cancel_task, "Annuler le biseau en cours", "ghost"
        )
        self.bevel_cancel.setEnabled(False)
        ops.row(self.bevel_width, self.bevel_segments, self.bevel_button, self.bevel_cancel)
        self.merge_distance = spin(0.001, 0.0001, 1.0, 0.001, 4, " m")
        ops.row(
            button("Fusionner", "minus", self._merge, "Fusionne les sommets sélectionnés en leur centre"),
            self.merge_distance,
            button(
                "Par distance", None, self._merge_distance, "Soude les sommets proches dans tout le maillage"
            ),
        )
        ops.row(
            button(
                "Supprimer",
                "trash-2",
                self.controller.delete_selected,
                "Supprime les éléments sélectionnés",
                "danger",
            ),
            button(
                "Séparer",
                "copy",
                self.controller.separate_selection,
                "Sépare la sélection en un nouvel objet",
            ),
        )
        normals = page.section("Normales")
        normals.row(
            button(
                "Recalculer",
                "refresh-cw",
                lambda: self.controller.run_edit("Normales", editmesh.recalculate_normals),
            ),
            button("Inverser", None, self._flip),
            button(
                "Orienter",
                None,
                lambda: self.controller.run_edit(
                    "Orientation des normales", editmesh.make_normals_consistent
                ),
            ),
        )
        symmetry = page.section("Symétrie et alignement", "Prévisualisez, puis validez ou annulez.")
        self.sym_axis = LSSelect(AXES)
        self.sym_side = LSSelect([("Garder le côté +", True), ("Garder le côté −", False)])
        symmetry.row(self.sym_axis, self.sym_side)
        self.sym_preview = button("Prévisualiser", "eye", self._preview_symmetry)
        self.sym_apply = button("Valider", "check", self._confirm_preview, variant="primary")
        self.sym_cancel = button("Annuler", "x", self._cancel_preview, variant="ghost")
        symmetry.row(self.sym_preview, self.sym_apply, self.sym_cancel)
        self.flat_axis = LSSelect(AXES)
        symmetry.row(
            self.flat_axis,
            button("Aligner sur le plan", None, self._flatten, "Aplatit la sélection sur un plan"),
        )
        uv = page.section("UV", "À utiliser si une opération a invalidé les coordonnées de texture.")
        uv.row(button("Projection UV automatique", "image", self._box_uv), stretch=True)
        page.finish()
        self._sync_bevel()
        return page

    def _set_xray(self, value: bool) -> None:
        self.controller.edit.xray = bool(value)
        self.viewport._on_edit_state()

    def _sync_bevel(self) -> None:
        available, reason = bevel_available()
        self.bevel_button.setEnabled(available)
        tooltip(self.bevel_button, reason)

    def _on_busy(self, busy: bool, _text: str) -> None:
        self.bevel_cancel.setEnabled(busy)
        self.bevel_button.setEnabled(not busy and bevel_available()[0])

    def _select(self, how: str) -> None:
        state, mesh = self.controller.edit, self.controller.edit_mesh()
        if mesh is None:
            return
        element = state.element
        if how == "all":
            state.select(editmesh.all_elements(mesh, element))
        elif how == "none":
            state.select(set())
        elif how == "invert":
            state.select(editmesh.all_elements(mesh, element) - state.selection)
        elif how in ("grow", "linked"):
            vertices = editmesh.to_vertices(mesh, element, state.selection)
            grown = (
                editmesh.grow_vertices(mesh, vertices)
                if how == "grow"
                else editmesh.linked_vertices(mesh, vertices)
            )
            state.select(editmesh.convert_selection(mesh, editmesh.VERTEX, grown, element))
        elif how == "coplanar":
            faces = editmesh.convert_selection(mesh, element, state.selection, editmesh.FACE)
            if faces:
                region = editmesh.coplanar_faces(mesh, min(faces))
                state.set_element(editmesh.FACE)
                state.select(region)

    def _edit(self, title: str, operation) -> None:  # type: ignore[no-untyped-def]
        self.controller.run_edit(title, operation)

    def _move(self) -> None:
        state, offset = self.controller.edit, self.move.value()
        element, sel = state.element, set(state.selection)
        self._edit("Déplacement des sommets", lambda m: editmesh.translate_elements(m, element, sel, offset))

    def _rotate(self) -> None:
        state, angles = self.controller.edit, self.rotate.value()
        element, sel = state.element, set(state.selection)
        self._edit("Rotation des sommets", lambda m: editmesh.rotate_elements(m, element, sel, angles))

    def _scale(self) -> None:
        state, factors = self.controller.edit, self.scale.value()
        element, sel = state.element, set(state.selection)
        self._edit("Échelle des sommets", lambda m: editmesh.scale_elements(m, element, sel, factors))

    def _faces(self) -> set[int]:
        mesh, state = self.controller.edit_mesh(), self.controller.edit
        return (
            editmesh.convert_selection(mesh, state.element, state.selection, editmesh.FACE) if mesh else set()
        )

    def _extrude(self) -> None:
        faces, distance = self._faces(), self.extrude_distance.value()
        self._edit("Extrusion", lambda m: editmesh.extrude_faces(m, faces, distance))

    def _inset(self) -> None:
        faces, amount = self._faces(), self.inset_amount.value()
        self._edit("Inset", lambda m: editmesh.inset_faces(m, faces, amount))

    def _bevel(self) -> None:
        self.controller.bevel_async(self.bevel_width.value(), self.bevel_segments.value())

    def _merge(self) -> None:
        state = self.controller.edit
        element, sel = state.element, set(state.selection)
        self._edit("Fusion de sommets", lambda m: editmesh.merge_vertices(m, element, sel))

    def _merge_distance(self) -> None:
        distance = self.merge_distance.value()
        self._edit("Fusion par distance", lambda m: editmesh.merge_by_distance(m, distance))

    def _flip(self) -> None:
        faces = self._faces()
        self._edit("Inversion des normales", lambda m: editmesh.flip_faces(m, faces or None))

    def _flatten(self) -> None:
        state, axis = self.controller.edit, self.flat_axis.currentData()
        element, sel = state.element, set(state.selection)
        self._edit("Alignement sur un plan", lambda m: editmesh.flatten_elements(m, element, sel, axis))

    def _box_uv(self) -> None:
        self._edit("Projection UV automatique", editmesh.box_project_uv)

    def _preview_symmetry(self) -> None:
        ctl, editor = self.controller, self.editor
        mesh, target = ctl.edit_mesh(), ctl.edit.target
        if mesh is None or editor is None:
            return
        axis, keep = self.sym_axis.currentData(), self.sym_side.currentData()
        origin = editor.axes.mirror_origin if axis == editor.axes.lateral_axis else 0.0
        try:
            if editor.previewing:
                editor.cancel()
                mesh = ctl.edit_mesh()
            result = editmesh.symmetrize(mesh, axis, keep, origin)
            editor.preview(editor.geometry_command(target, result.mesh, "Symétrie du maillage"))
        except editmesh.EditError as exc:
            ctl.notify.emit("Symétrie", str(exc), "warning")
            return
        ctl.edit.set_result(ctl.edit.element, set())
        ctl.scene_changed.emit("geometry")
        for warning in result.warnings:
            ctl.notify.emit("Symétrie (aperçu)", warning, "info")

    def _confirm_preview(self) -> None:
        if self.editor is not None and self.editor.previewing:
            self.editor.confirm()

    def _cancel_preview(self) -> None:
        if self.editor is not None and self.editor.previewing:
            self.editor.cancel()
            self.controller.scene_changed.emit("geometry")

    # Mode Composant ----------------------------------------------------------------------
    def _component_page(self) -> Page:
        page = Page()
        self.component_info = label("Aucun composant sélectionné", "muted", wrap=True)
        page.layout_.addWidget(self.component_info)
        info = page.section("Composant", "Distinction visuel / mobile / technique FiveM.")
        self.role = LSSelect([(v, k) for k, v in vehicle.ROLE_LABELS.items()])
        self.role.activated.connect(self._set_role)
        info.add(self.role)
        actions = page.section("Actions")
        actions.row(
            button("Isoler", "scan", self._isolate, "N'affiche que ce composant (affichage seulement)"),
            button("Tout afficher", "eye", lambda: self.viewport.set_isolation(None)),
        )
        actions.row(
            button("Remplacer…", "refresh-cw", self.open_replace, "Replace Component"),
            button("Dupliquer", "copy-plus", self.controller.duplicate_selected),
        )
        variants = page.section("Variantes", "Une seule variante visible à la fois ; chacune est modifiable.")
        variants.row(button("Créer une variante", "copy", self._variant), stretch=True)
        self.variant_select = LSSelect()
        self.variant_select.activated.connect(self._activate_variant)
        variants.add(self.variant_select)
        pivot = page.section("Pivot", "Déplacer le pivot ne déplace pas la pièce.")
        self.pivot = LSPropertyField("Position", suffix=" m", step=0.01)
        pivot.add(self.pivot)
        pivot.row(
            button("Centrer", "frame", self._center_pivot), button("Placer", "move-3d", self._set_pivot)
        )
        parent = page.section(
            "Parent", "Associer le composant à un autre élément (position monde conservée)."
        )
        self.parent_select = LSSelect()
        parent.add(self.parent_select)
        parent.row(button("Associer", "layers", self._reparent), stretch=True)
        attach = page.section("Points d'attache")
        self.attach_type = LSSelect([(v, k) for k, v in ANCHOR_TYPES.items()])
        attach.row(self.attach_type, button("Ajouter", "plus", self._add_attach))
        page.finish()
        return page

    def _active(self):  # type: ignore[no-untyped-def]
        session = self.controller.session
        return session.scene.get(session.selection.active) if session else None

    def _set_role(self) -> None:
        node, role = self._active(), self.role.currentData()
        if node is not None:
            self.controller.run(
                "Rôle du composant", lambda: self.editor.set_component_info([node.id], role=role)
            )

    def _isolate(self) -> None:
        session = self.controller.session
        if session is not None and self._sel():
            self.viewport.set_isolation(vehicle.mesh_ids_under(session.scene, self._sel()))

    def _variant(self) -> None:
        node = self._active()
        if node is not None:
            self.controller.run("Variante", lambda: self.editor.create_variant(node.id))

    def _activate_variant(self) -> None:
        node, variant = self._active(), self.variant_select.currentData()
        if node is None or not variant:
            return
        parent = node.id if vehicle.is_variant_set(node) else node.parent_id
        self.controller.run("Variante active", lambda: self.editor.set_active_variant(parent, variant))

    def _center_pivot(self) -> None:
        node = self._active()
        if node is not None:
            self.controller.fivem_risk([node.id], "pivot")
            self.controller.run("Pivot", lambda: self.editor.center_pivot(node.id))

    def _set_pivot(self) -> None:
        node, point = self._active(), np.asarray(self.pivot.value())
        if node is not None:
            self.controller.fivem_risk([node.id], "pivot")
            self.controller.run("Pivot", lambda: self.editor.set_pivot(node.id, point))

    def _reparent(self) -> None:
        self.controller.reparent(self._sel(), self.parent_select.currentData() or None)

    def _add_attach(self) -> None:
        node, kind = self._active(), self.attach_type.currentData()
        name = f"Attache {ANCHOR_TYPES[kind].lower()}"
        self.controller.run(
            "Point d'attache", lambda: self.editor.add_anchor(node.id if node else None, name, kind)
        )

    # Rafraîchissement ---------------------------------------------------------------------
    def refresh(self) -> None:
        state = self.controller.edit
        index = {modes.OBJECT: 0, modes.EDIT: 1, modes.COMPONENT: 2}[state.mode]
        self.setCurrentIndex(index)
        session = self.controller.session
        if self.editor is not None:
            axes = self.editor.axes
            self.lateral.select_data(axes.lateral_axis)
            self.longitudinal.select_data(axes.longitudinal_axis)
            self.forward.select_data(axes.forward_sign)
            self.mirror_origin.setValue(axes.mirror_origin)
        if index == 1:
            self._refresh_edit(session, state)
        elif index == 2 and session is not None:
            self._refresh_component(session)

    def _refresh_edit(self, session, state) -> None:  # type: ignore[no-untyped-def]
        for element, widget in self.element_buttons.items():
            widget.setChecked(element == state.element)
        node = session.scene.get(state.target) if session and state.target else None
        mesh = self.controller.edit_mesh()
        if node is not None and mesh is not None:
            topo = editmesh.topology(mesh)
            self.edit_target.setText(
                f"<b>{node.name}</b> — {topo.vertex_count} sommets, {len(topo.edges)} arêtes, "
                f"{mesh.triangle_count} faces"
            )
        noun = editmesh.ELEMENT_LABELS[state.element].lower()
        self.selection_info.setText(f"{len(state.selection)} {noun} sélectionné(e)s")

    def _refresh_component(self, session) -> None:  # type: ignore[no-untyped-def]
        node = self._active()
        scene = session.scene
        self.component_info.setText(
            f"<b>{node.name}</b> — {vehicle.category(scene, node)}" if node else "Aucun composant"
        )
        if node is not None:
            self.role.select_data(vehicle.role(scene, node))
            self.pivot.set_value(scene.world_matrix(node.id)[:3, 3])
        self.variant_select.clear()
        set_node = node if vehicle.is_variant_set(node) else (scene.get(node.parent_id) if node else None)
        if vehicle.is_variant_set(set_node):
            for child in scene.children(set_node.id):
                self.variant_select.addItem(("● " if child.visible else "○ ") + child.name, child.id)
        else:
            self.variant_select.addItem("Aucun ensemble de variantes", "")
        self.parent_select.clear()
        self.parent_select.addItem("Racine de la scène", "")
        if node is None:
            return
        for candidate in scene.walk():
            if (
                candidate.kind is NodeKind.ANCHOR
                or candidate.id == node.id
                or scene.is_ancestor(node.id, candidate.id)
            ):
                continue
            self.parent_select.addItem(icons.icon("layers", size=14), scene.path(candidate.id), candidate.id)


# --- Géométrie -------------------------------------------------------------------------------


class GeometryPanel(Page):
    def __init__(self, controller) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.controller = controller
        info = self.section("Géométrie de la pièce")
        self.info = info.add(label("Aucune pièce sélectionnée", "muted", wrap=True))
        uv = self.section("Coordonnées de texture (UV)")
        self.uv_status = LSBadge("—")
        uv.row(self.uv_status, stretch=True)
        self.uv_messages = uv.add(label("", "faint", wrap=True))
        uv.row(button("Projection UV automatique", "image", self._box_uv), stretch=True)
        tools = self.section("Actions")
        tools.row(
            button("Mode Édition", "pencil", lambda: controller.set_mode(modes.EDIT), "Tab"),
            button("Recalculer les normales", "refresh-cw", self._normals),
        )
        memory = self.section("Mémoire", "Géométrie chargée et conservée par l'historique.")
        self.memory = memory.add(label("—", "faint", wrap=True))
        self.finish()
        for signal in (controller.selection_changed, controller.session_changed, controller.state_changed):
            signal.connect(self.refresh)
        self.refresh()

    def _mesh_node(self):  # type: ignore[no-untyped-def]
        session = self.controller.session
        if session is None:
            return None, None
        node = session.scene.get(session.selection.active)
        if node is None or node.kind is not NodeKind.MESH:
            return node, None
        return node, session.geometry_for(node)

    def _apply(self, title: str, operation) -> None:  # type: ignore[no-untyped-def]
        node, mesh = self._mesh_node()
        if node is not None and mesh is not None:
            self.controller.run(title, lambda: self.controller.editor.edit(node.id, operation, title))

    def _box_uv(self) -> None:
        self._apply("Projection UV automatique", editmesh.box_project_uv)

    def _normals(self) -> None:
        self._apply("Normales", editmesh.recalculate_normals)

    def refresh(self) -> None:
        session = self.controller.session
        node, mesh = self._mesh_node()
        if mesh is None:
            self.info.setText(
                "Sélectionnez un maillage pour voir sa géométrie." if session else "Aucun projet"
            )
            self.uv_status.setText("—")
            self.uv_messages.setText("")
        else:
            topo = editmesh.topology(mesh)
            if node.asset_id is None:
                source = "géométrie locale du projet (modifiée ou créée)"
            else:
                source = "fichier importé (non modifié)"
            dims = " × ".join(f"{v:.3f}".replace(".", ",") for v in mesh.bounds[1] - mesh.bounds[0])
            self.info.setText(
                f"<b>{node.name}</b><br>{topo.vertex_count} sommets logiques ({mesh.vertex_count} de rendu), "
                f"{len(topo.edges)} arêtes, {mesh.triangle_count} faces<br>Dimensions locales : {dims} m<br>"
                f"Source : {source}"
            )
            report = editmesh.uv_report(mesh)
            self.uv_status.setText(report.label)
            self.uv_messages.setText("\n".join(report.messages) or "Aucun problème détecté.")
        if session is not None:
            mb = {k: v / 1048576 for k, v in session.memory_report().items()}
            self.memory.setText(
                f"Fichiers importés : {mb['imported']:.1f} Mo · géométrie locale : {mb['local']:.1f} Mo · "
                f"historique : {mb['history']:.1f} Mo (limite {session.stack.memory_budget / 1048576:.0f} Mo)"
            )


# --- Points d'ancrage --------------------------------------------------------------------------


class AnchorsPanel(Page):
    def __init__(self, controller, viewport) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.controller = controller
        self.viewport = viewport
        self._updating = False
        create = self.section("Nouveau point d'ancrage", "Créé sur la pièce sélectionnée (ou à la racine).")
        self.name = LSInput("Nom (ex. Rampe de toit)")
        self.type = LSSelect([(v, k) for k, v in ANCHOR_TYPES.items()])
        self.constraints = LSSelect([(v, k) for k, v in ANCHOR_CONSTRAINTS.items()])
        create.add(self.name)
        create.row(self.type, self.constraints)
        create.row(button("Créer", "plus", self.create, variant="primary"), stretch=True)
        listing = self.section("Points d'ancrage du projet")
        self.show_axes = QCheckBox("Afficher les axes dans le viewport")
        self.show_axes.setChecked(True)
        self.show_axes.toggled.connect(self._toggle_axes)
        listing.add(self.show_axes)
        self.list = QListWidget()
        self.list.setMinimumHeight(140)
        self.list.itemClicked.connect(lambda item: self.controller.select([item.data(ID_ROLE)]))
        listing.add(self.list)
        details = self.section("Point sélectionné")
        self.detail_type = LSSelect([(v, k) for k, v in ANCHOR_TYPES.items()])
        self.detail_type.activated.connect(lambda: self._update(type=self.detail_type.currentData()))
        self.detail_constraints = LSSelect([(v, k) for k, v in ANCHOR_CONSTRAINTS.items()])
        self.detail_constraints.activated.connect(
            lambda: self._update(constraints=self.detail_constraints.currentData())
        )
        details.row(self.detail_type, self.detail_constraints)
        self.position = LSPropertyField("Position", suffix=" m", step=0.01)
        self.rotation = LSPropertyField("Rotation", minimum=-360, maximum=360, step=5, decimals=1, suffix="°")
        self.position.edit_finished.connect(lambda v: self._transform("translation", v))
        self.rotation.edit_finished.connect(lambda v: self._transform("rotation", v))
        details.add(self.position)
        details.add(self.rotation)
        details.add(label("Métadonnées (une ligne clé = valeur) :", "faint"))
        self.metadata = QPlainTextEdit()
        self.metadata.setMaximumHeight(80)
        details.add(self.metadata)
        self.component = LSSelect()
        details.add(self.component)
        details.row(
            button("Métadonnées", "save", self._save_metadata, "Enregistrer les métadonnées"),
            button("Associer", "layers", self._attach, "Associer au composant choisi"),
            button("", "trash-2", self._delete, "Supprimer le point d'ancrage", "danger"),
        )
        self.parent_info = details.add(label("", "faint", wrap=True))
        self.finish()
        for signal in (controller.session_changed, controller.selection_changed, controller.scene_changed):
            signal.connect(lambda *_: self.refresh())
        self.refresh()

    def _toggle_axes(self, value: bool) -> None:
        self.viewport.show_anchors = value
        self.viewport.update()

    def _anchor(self):  # type: ignore[no-untyped-def]
        session = self.controller.session
        node = session.scene.get(session.selection.active) if session else None
        return node if node is not None and node.kind is NodeKind.ANCHOR else None

    def create(self) -> str | None:
        session = self.controller.session
        if session is None or self.controller.editor is None:
            return None
        parent = session.selection.active
        node = session.scene.get(parent) if parent else None
        if node is not None and node.kind is NodeKind.ANCHOR:
            parent = node.parent_id
        position = (0.0, 0.0, 0.0)
        bounds = session.world_bounds([parent], only_visible=False) if parent else None
        if bounds is not None:  # au sommet de la pièce porteuse (repère local du parent)
            top = np.array(
                [(bounds[0][0] + bounds[1][0]) / 2, bounds[1][1], (bounds[0][2] + bounds[1][2]) / 2]
            )
            inverse = np.linalg.inv(session.scene.world_matrix(parent))
            position = tuple(float(v) for v in mathutils.transform_points(inverse, top[None, :])[0])
        kind, constraints = self.type.currentData(), self.constraints.currentData()
        name = self.name.text().strip() or f"Ancrage {ANCHOR_TYPES[kind].lower()}"
        return self.controller.run(
            "Point d'ancrage",
            lambda: self.controller.editor.add_anchor(parent, name, kind, position, constraints=constraints),
        )

    def _update(self, **fields) -> None:  # type: ignore[no-untyped-def]
        anchor = self._anchor()
        if anchor is not None and not self._updating:
            self.controller.run(
                "Point d'ancrage", lambda: self.controller.editor.update_anchor(anchor.id, **fields)
            )

    def _transform(self, field: str, values: list[float]) -> None:
        anchor = self._anchor()
        if anchor is None or self._updating:
            return
        transform = anchor.transform.copy()
        setattr(transform, field, [float(v) for v in values])
        self.controller.session.set_transforms({anchor.id: transform}, "Point d'ancrage")

    def _save_metadata(self) -> None:
        metadata = {}
        for line in self.metadata.toPlainText().splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip():
                metadata[key.strip()] = value.strip()
        self._update(metadata=metadata)

    def _attach(self) -> None:
        anchor, target = self._anchor(), self.component.currentData()
        if anchor is not None and target:
            self.controller.run(
                "Association", lambda: self.controller.editor.attach_anchor(anchor.id, target)
            )

    def _delete(self) -> None:
        anchor = self._anchor()
        if anchor is not None and self.controller.session is not None:
            self.controller.session.delete([anchor.id])

    def refresh(self) -> None:
        session = self.controller.session
        self._updating = True
        self.list.clear()
        self.component.clear()
        if session is not None:
            for node in session.scene.anchor_nodes():
                kind = vehicle.anchor_data(node)["type"]
                item = QListWidgetItem(
                    icons.icon("frame", size=14), f"{node.name} — {ANCHOR_TYPES.get(kind, kind)}"
                )
                item.setData(ID_ROLE, node.id)
                self.list.addItem(item)
                if node.id == session.selection.active:
                    self.list.setCurrentItem(item)
            for node in session.scene.walk():
                if node.kind is not NodeKind.ANCHOR:
                    self.component.addItem(session.scene.path(node.id), node.id)
        anchor = self._anchor()
        for widget in (
            self.detail_type,
            self.detail_constraints,
            self.position,
            self.rotation,
            self.metadata,
            self.component,
        ):
            widget.setEnabled(anchor is not None)
        if anchor is not None:
            data = vehicle.anchor_data(anchor)
            self.detail_type.select_data(data["type"])
            self.detail_constraints.select_data(data["constraints"])
            self.position.set_value(anchor.transform.translation)
            self.rotation.set_value(anchor.transform.rotation)
            self.metadata.setPlainText("\n".join(f"{k} = {v}" for k, v in data["metadata"].items()))
            parent = session.scene.get(anchor.parent_id)
            self.parent_info.setText(
                f"Parent : {parent.name if parent else 'racine'} · identifiant {data['anchor_id']}"
            )
        else:
            self.parent_info.setText("Sélectionnez un point d'ancrage (liste ou viewport).")
        self._updating = False


# --- Ateliers -------------------------------------------------------------------------------


class BodyworkPanel(Page):
    """Bodywork Studio : panneaux de carrosserie, proportions, création de pièces, symétrie."""

    CREATE = (
        ("Pare-chocs", "lsf-bumper", "front"),
        ("Aileron", "lsf-spoiler", "rear"),
        ("Calandre", "lsf-grille", "front"),
        ("Prise d'air", "lsf-air_intake", "hood"),
        ("Bas de caisse", "lsf-side_skirt", "side"),
        ("Lame avant", "lsf-splitter", "front"),
        ("Diffuseur", "lsf-diffuser", "rear"),
        ("Élargisseur", "lsf-fender_flare", "side"),
        ("Canard", "lsf-canard", "front"),
        ("Capot", "lsf-hood", "hood"),
    )

    def __init__(self, controller, library_panel, viewport) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.controller = controller
        self.library_panel = library_panel
        self.viewport = viewport
        panels = self.section(
            "Panneaux de carrosserie", "Classés d'après leurs noms (conventions GTA V ou noms explicites)."
        )
        self.panels = QListWidget()
        self.panels.setMaximumHeight(150)
        self.panels.itemClicked.connect(
            lambda item: item.data(ID_ROLE) and controller.select([item.data(ID_ROLE)])
        )
        panels.add(self.panels)
        panels.row(
            button("Isoler la carrosserie", "scan", self._isolate),
            button("Tout afficher", "eye", lambda: viewport.set_isolation(None)),
        )
        proportions = self.section(
            "Proportions de la sélection", "Largeur, hauteur, longueur en pourcentage."
        )
        self.width = spin(100, 10, 400, 1, 1, " %")
        self.height = spin(100, 10, 400, 1, 1, " %")
        self.length = spin(100, 10, 400, 1, 1, " %")
        proportions.row(
            label("L", "muted"),
            self.width,
            label("H", "muted"),
            self.height,
            label("Lo", "muted"),
            self.length,
        )
        proportions.row(button("Appliquer", "scale-3d", self._proportions), stretch=True)
        create = self.section(
            "Créer une pièce", "Formes originales placées d'après l'encombrement du véhicule."
        )
        grid = QGridLayout()
        for index, (text, component_id, placement) in enumerate(self.CREATE):
            widget = button(text, "plus", lambda c=component_id, p=placement: self.create(c, p))
            grid.addWidget(widget, index // 2, index % 2)
        create.body.addLayout(grid)
        symmetry = self.section(
            "Symétrie gauche / droite", "Plan de symétrie : réglages « Axes du véhicule »."
        )
        symmetry.row(
            button("Dupliquer en miroir", "copy", self._mirror),
            button(
                "Symétriser le maillage",
                "pencil",
                lambda: controller.set_mode(modes.EDIT),
                "Mode Édition, outil Symétrie",
            ),
        )
        self.section(
            "UV",
            "Les déplacements conservent les UV ; extrusion, inset et symétrie signalent leurs effets. "
            "Correction proposée : Projection UV automatique (onglet Géométrie).",
        )
        self.finish()
        for signal in (controller.session_changed, controller.scene_changed):
            signal.connect(lambda *_: self.refresh())
        self.refresh()

    def create(self, component_id: str, placement: str) -> str | None:
        session, editor = self.controller.session, self.controller.editor
        if session is None or editor is None:
            return None
        library = self.library_panel.library
        component = library.get(component_id)
        if component is None:
            self.controller.notify.emit(
                "Bodywork Studio", "Composant de départ absent de la bibliothèque.", "warning"
            )
            return None
        payload = library.payload(component, session.project)
        payload.snapshots[0]["transform"] = editor.placement_for(placement).to_dict()
        return editor.insert_payload(payload, None, None, f"Création : {component.name}")

    def _mirror(self) -> None:
        self.controller.run(
            "Miroir", lambda: self.controller.editor.mirror_duplicate(self.controller.selected())
        )

    def _isolate(self) -> None:
        session = self.controller.session
        if session is not None:
            ids = vehicle.mesh_ids_under(session.scene, [n.id for n in vehicle.body_panels(session.scene)])
            self.viewport.set_isolation(ids or None)

    def _proportions(self) -> None:
        editor = self.controller.editor
        if editor is None:
            return
        axes = editor.axes
        factors = [1.0, 1.0, 1.0]
        factors[axes.lateral_axis] = self.width.value() / 100
        factors[axes.up_axis] = self.height.value() / 100
        factors[axes.longitudinal_axis] = self.length.value() / 100
        selected = self.controller.selected()
        self.controller.fivem_risk(selected, "scale")
        self.controller.run("Proportions", lambda: editor.scale_proportions(selected, factors))

    def refresh(self) -> None:
        session = self.controller.session
        self.panels.clear()
        if session is not None:
            for node in vehicle.body_panels(session.scene):
                text = f"{node.name} — {vehicle.category(session.scene, node)}"
                item = QListWidgetItem(icons.icon("cuboid", size=14), text)
                item.setData(ID_ROLE, node.id)
                self.panels.addItem(item)
        if self.panels.count() == 0:
            self.panels.addItem("Aucun panneau identifié")


def axis_rotation(axis: np.ndarray, angle: float) -> np.ndarray:
    """Rotation 4x4 d'angle ``angle`` (radians) autour d'un axe passant par l'origine."""
    x, y, z = axis / np.linalg.norm(axis)
    c, s = math.cos(angle), math.sin(angle)
    matrix = np.eye(4)
    matrix[:3, :3] = [
        [c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
        [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
        [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)],
    ]
    return matrix


class WheelPanel(Page):
    """Wheel Editor : identification, positions, alignement, échelle, jantes, pivots, rotation."""

    COLUMNS = ("Roue", "Côté", "Essieu", "Rayon", "Largeur", "Pivot")

    def __init__(self, controller, viewport, open_replace: Callable[[str | None, str | None], None]) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.controller = controller
        self.viewport = viewport
        self.open_replace = open_replace
        self._angle = 0.0
        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(30)
        self._spin_timer.timeout.connect(self._spin_step)
        found = self.section("Roues identifiées", "Os wheel_* (GTA V) ou pièces nommées roue / wheel / pneu.")
        self.profile = found.add(label("", "muted", wrap=True))
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(150)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellClicked.connect(self._pick)
        found.add(self.table)
        self.messages = found.add(label("", "faint", wrap=True))
        position = self.section("Positionnement")
        self.track = spin(1.6, 0.1, 10, 0.01, 3, " m")
        self.wheelbase = spin(2.6, 0.1, 30, 0.01, 3, " m")
        position.row(label("Voie", "muted"), self.track, button("Appliquer", None, self._track))
        position.row(
            label("Empattement", "muted"), self.wheelbase, button("Appliquer", None, self._wheelbase)
        )
        position.row(
            button("Aligner les hauteurs", "frame", self._align),
            button("Symétrie", "copy", self._mirror, "Place la roue opposée en miroir de la roue choisie"),
        )
        size = self.section("Dimensions de la roue choisie")
        self.scale = spin(1.0, 0.1, 5, 0.01, 3, " ×")
        self.tire_width = spin(1.0, 0.1, 5, 0.01, 3, " ×")
        size.row(label("Diamètre", "muted"), self.scale, button("Appliquer", None, self._scale))
        size.row(label("Largeur", "muted"), self.tire_width, button("Appliquer", None, self._width))
        parts = self.section("Jantes, pneus et pivots")
        parts.row(
            button(
                "Remplacer la jante…", "refresh-cw", lambda: self.open_replace(self._wheel_id(), "lsf-rim5")
            ),
            button("Pneu…", "refresh-cw", lambda: self.open_replace(self._wheel_id(), "lsf-tire")),
        )
        parts.row(button("Centrer le pivot", "frame", self._center_pivot), stretch=True)
        preview = self.section(
            "Prévisualisation", "Rotation autour de l'axe latéral de chaque roue (affichage seulement)."
        )
        self.spin_button = button("Prévisualiser la rotation", "orbit", self.toggle_spin)
        self.spin_button.setCheckable(True)
        preview.row(self.spin_button, stretch=True)
        self.finish()
        for signal in (controller.session_changed, controller.scene_changed, controller.state_changed):
            signal.connect(lambda *_: self.refresh())
        self.refresh()

    @property
    def editor(self):  # type: ignore[no-untyped-def]
        return self.controller.editor

    def report(self):  # type: ignore[no-untyped-def]
        return self.editor.wheels() if self.editor is not None else None

    def _wheel_id(self) -> str | None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        return item.data(ID_ROLE) if item else None

    def _pick(self, row: int, _column: int) -> None:
        item = self.table.item(row, 0)
        if item is not None:
            self.controller.select([item.data(ID_ROLE)])

    def _track(self) -> None:
        value = self.track.value()
        self.controller.run("Voie", lambda: self.editor.set_track(value))

    def _wheelbase(self) -> None:
        value = self.wheelbase.value()
        self.controller.run("Empattement", lambda: self.editor.set_wheelbase(value))

    def _align(self) -> None:
        self.controller.run("Alignement des roues", self.editor.align_wheel_heights)

    def _mirror(self) -> None:
        report, wheel_id = self.report(), self._wheel_id()
        if report is None or wheel_id is None:
            return
        wheel = next((w for w in report.wheels if w.node_id == wheel_id), None)
        partner = vehicle.mirror_partner(report, wheel) if wheel else None
        if partner is None:
            self.controller.notify.emit("Symétrie des roues", "Aucune roue opposée trouvée.", "info")
            return
        self.controller.run(
            "Symétrie des roues", lambda: self.editor.mirror_wheel_position(wheel_id, partner.node_id)
        )

    def _scale(self) -> None:
        wheel_id, factor = self._wheel_id(), self.scale.value()
        if wheel_id:
            self.controller.run("Diamètre", lambda: self.editor.scale_wheels([wheel_id], factor))

    def _width(self) -> None:
        wheel_id, factor = self._wheel_id(), self.tire_width.value()
        if wheel_id:
            axis = self.editor.axes.lateral_axis
            self.controller.run("Largeur", lambda: self.editor.scale_wheels([wheel_id], factor, axis))

    def _center_pivot(self) -> None:
        wheel_id = self._wheel_id()
        if wheel_id:
            self.controller.fivem_risk([wheel_id], "pivot")
            self.controller.run("Pivot", lambda: self.editor.center_pivot(wheel_id))

    def toggle_spin(self) -> None:
        if self._spin_timer.isActive():
            self._spin_timer.stop()
            self.spin_button.setChecked(False)
            self.viewport.set_display_matrices({})
            self.refresh()
        else:
            self._spin_timer.start()
            self.spin_button.setChecked(True)

    def _spin_step(self) -> None:
        report = self.report()
        if report is None or not report.wheels:
            self.toggle_spin()
            return
        self._angle = (self._angle + 6.0) % 360.0
        axis = np.zeros(3)
        axis[report.axes.lateral_axis] = 1.0
        rotation = axis_rotation(axis, math.radians(self._angle))
        self.viewport.set_display_matrices(
            {
                w.node_id: mathutils.translation(w.center) @ rotation @ mathutils.translation(-w.center)
                for w in report.wheels
            }
        )

    def refresh(self) -> None:
        if self._spin_timer.isActive():
            return  # pendant l'aperçu : les roues affichées tournent, rien à recalculer
        report = self.report()
        self.table.setRowCount(0)
        if report is None:
            self.profile.setText("Aucun projet")
            self.messages.setText("")
            return
        expected = " ou ".join(str(n) for n in report.profile.expected) or "aucun nombre imposé"
        self.profile.setText(
            f"Profil {report.profile.label} : {expected} roue(s) attendue(s). {report.profile.note}"
        )
        for row, wheel in enumerate(report.wheels):
            self.table.insertRow(row)
            values = (
                wheel.name,
                wheel.side,
                wheel.axle,
                f"{wheel.radius:.3f}".replace(".", ","),
                f"{wheel.width:.3f}".replace(".", ","),
                f"{wheel.pivot_offset * 100:.1f} cm".replace(".", ","),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(ID_ROLE, wheel.node_id)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        if report.track:
            self.track.setValue(report.track)
        if report.wheelbase:
            self.wheelbase.setValue(report.wheelbase)
        self.messages.setText(
            "\n".join(report.messages) or "Aucune anomalie détectée (vérification indicative)."
        )


class InteriorPanel(Page):
    """Interior Studio : isolation de l'habitacle, caméra intérieure, sièges, configurations."""

    BODY = {"carrosserie", "vitres", "capot", "coffre", "portes"}

    def __init__(self, controller, viewport, library_panel) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.controller = controller
        self.viewport = viewport
        self.library_panel = library_panel
        view = self.section("Affichage")
        self.isolate = QCheckBox("Isoler l'habitacle")
        self.isolate.toggled.connect(self._isolate)
        self.hide_body = QCheckBox("Masquer temporairement la carrosserie")
        self.hide_body.toggled.connect(self._hide_body)
        view.add(self.isolate)
        view.add(self.hide_body)
        view.row(
            button("Caméra intérieure", "video", self.interior_camera, "Vue depuis la place du conducteur"),
            button("Vue extérieure", "orbit", self._exterior),
        )
        parts = self.section("Éléments de l'habitacle")
        self.list = QListWidget()
        self.list.setMaximumHeight(160)
        self.list.itemClicked.connect(
            lambda item: item.data(ID_ROLE) and controller.select([item.data(ID_ROLE)])
        )
        parts.add(self.list)
        add = self.section(
            "Ajouter", "Composants de la bibliothèque, placés dans l'habitacle (ou la configuration active)."
        )
        add.row(
            button("Siège", "plus", lambda: self._add("lsf-seat")),
            button("Tableau de bord", "plus", lambda: self._add("lsf-dashboard")),
            button("Volant", "plus", lambda: self._add("lsf-steering_wheel")),
        )
        add.row(button("Support médical", "plus", lambda: self._add("lsf-medical_bracket")), stretch=True)
        configs = self.section("Configurations", "Variantes d'habitacle : une seule active à la fois.")
        self.config_boxes: dict[str, QCheckBox] = {}
        for key, text in (
            ("civil", "Civil"),
            ("police", "Police"),
            ("ems", "EMS"),
            ("command", "Commandement"),
        ):
            box = QCheckBox(text)
            box.setChecked(key != "command")
            self.config_boxes[key] = box
        configs.row(*self.config_boxes.values(), stretch=True)
        configs.row(button("Créer les configurations", "layers", self._create_configs), stretch=True)
        self.active_config = LSSelect()
        self.active_config.activated.connect(self._activate)
        configs.add(self.active_config)
        configs.row(
            button("Déplacer la sélection dans la configuration", "layers", self._move_to_config),
            stretch=True,
        )
        self.finish()
        for signal in (controller.session_changed, controller.scene_changed):
            signal.connect(lambda *_: self.refresh())
        self.refresh()

    def _config_set(self):  # type: ignore[no-untyped-def]
        session = self.controller.session
        if session is None:
            return None
        return next(
            (n for n in session.scene.walk() if n.extra.get("variant_set", {}).get("kind") == "interior"),
            None,
        )

    def _isolate(self, value: bool) -> None:
        session = self.controller.session
        if session is None:
            return
        roots = [n.id for n in vehicle.interior_nodes(session.scene)]
        config = self._config_set()
        if config is not None:
            roots.append(config.id)
        ids = vehicle.mesh_ids_under(session.scene, roots)
        self.viewport.set_isolation(ids if value and ids else None)

    def _hide_body(self, value: bool) -> None:
        session = self.controller.session
        if session is not None:
            scene = session.scene
            panels = [n.id for n in vehicle.nodes_in_categories(scene, self.BODY)]
            cabin = [n.id for n in vehicle.interior_nodes(scene)]
            body = vehicle.mesh_ids_under(scene, panels) - vehicle.mesh_ids_under(scene, cabin)
            self.viewport.set_hidden(body if value else set())

    def driver_position(self) -> np.ndarray | None:
        session = self.controller.session
        if session is None:
            return None
        seats = vehicle.nodes_in_categories(session.scene, {"sieges"})
        preferred = [
            n for n in seats if any(k in n.name.lower() for k in ("dside", "conducteur", "driver", "gauche"))
        ]
        chosen = preferred or seats or vehicle.interior_nodes(session.scene)
        bounds = (
            session.world_bounds([chosen[0].id], only_visible=False) if chosen else session.world_bounds()
        )
        if bounds is None:
            return None
        up = self.controller.editor.axes.up_axis
        head = (bounds[0] + bounds[1]) / 2
        if chosen:  # au-dessus de l'assise
            head[up] = bounds[0][up] + 0.75 * max(bounds[1][up] - bounds[0][up], 0.9)
        else:  # aucun siège : 60 % de la hauteur du véhicule
            head[up] = bounds[0][up] + 0.6 * (bounds[1][up] - bounds[0][up])
        return head

    def interior_camera(self) -> bool:
        head = self.driver_position()
        if head is None:
            self.controller.notify.emit("Caméra intérieure", "Aucun habitacle ni véhicule à cadrer.", "info")
            return False
        camera = self.viewport.camera
        camera.mode = "free"
        camera.orthographic = False
        camera.distance = 0.3
        camera.yaw = 0.0 if self.controller.editor.axes.forward_sign < 0 else 180.0
        camera.pitch = -6.0
        camera.target = head - camera._offset() * camera.distance
        self.viewport._sync_buttons()
        self.viewport.view_changed.emit()
        self.viewport.update()
        return True

    def _exterior(self) -> None:
        self.viewport.camera.mode = "orbit"
        self.viewport._sync_buttons()
        session = self.controller.session
        self.viewport.frame_bounds(session.world_bounds() if session else None)

    def _add(self, component_id: str) -> None:
        library = self.library_panel.library
        component = library.get(component_id)
        session, editor = self.controller.session, self.controller.editor
        if component is None or session is None or editor is None:
            self.controller.notify.emit(
                "Interior Studio", "Composant indisponible dans la bibliothèque.", "warning"
            )
            return
        payload = library.payload(component, session.project)
        parent = self.active_config.currentData() or None
        world = editor.placement_for("interior").matrix()
        parent_world = session.scene.world_matrix(parent) if parent else np.eye(4)
        payload.snapshots[0]["transform"] = decompose(np.linalg.inv(parent_world) @ world).to_dict()
        editor.insert_payload(payload, parent, None, f"Ajout de {component.name}")

    def _create_configs(self) -> None:
        keys = [k for k, box in self.config_boxes.items() if box.isChecked()]
        self.controller.run(
            "Configurations", lambda: self.controller.editor.create_interior_configurations(keys)
        )

    def _activate(self) -> None:
        config, variant = self._config_set(), self.active_config.currentData()
        if config is not None and variant:
            self.controller.run(
                "Configuration active", lambda: self.controller.editor.set_active_variant(config.id, variant)
            )

    def _move_to_config(self) -> None:
        target = self.active_config.currentData()
        if target:
            self.controller.reparent(self.controller.selected(), target)

    def refresh(self) -> None:
        session = self.controller.session
        self.list.clear()
        self.active_config.clear()
        if session is None:
            return
        for node in vehicle.interior_nodes(session.scene):
            item = QListWidgetItem(
                icons.icon("cuboid", size=14), f"{node.name} — {vehicle.category(session.scene, node)}"
            )
            item.setData(ID_ROLE, node.id)
            self.list.addItem(item)
        if self.list.count() == 0:
            self.list.addItem("Aucun élément d'habitacle identifié")
        config = self._config_set()
        if config is None:
            self.active_config.addItem("Aucune configuration (créez-en ci-dessus)", "")
            return
        for child in session.scene.children(config.id):
            self.active_config.addItem(("● " if child.visible else "○ ") + child.name, child.id)
        active = vehicle.active_variant(session.scene, config.id)
        if active:
            self.active_config.select_data(active)


# --- Bas : historique et compatibilité ----------------------------------------------------


class HistoryPanel(QWidget):
    def __init__(self, controller) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.controller = controller
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        history = QVBoxLayout()
        history.addWidget(label("Historique (double-clic : revenir à cette étape)", "faint"))
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self._go_to)
        history.addWidget(self.list, 1)
        self.memory = label("", "faint")
        history.addWidget(self.memory)
        layout.addLayout(history, 3)
        points = QVBoxLayout()
        points.addWidget(label("Points de restauration", "faint"))
        row = QHBoxLayout()
        self.point_name = LSInput("Nom du point")
        row.addWidget(self.point_name, 1)
        row.addWidget(button("Créer", "save", self.create_point))
        points.addLayout(row)
        self.points = QListWidget()
        points.addWidget(self.points, 1)
        points.addWidget(
            button(
                "Restaurer", "history", self.restore_point, "Remplace la scène par ce point de restauration"
            )
        )
        layout.addLayout(points, 2)
        for signal in (controller.session_changed, controller.state_changed):
            signal.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        session = self.controller.session
        self.list.clear()
        self.points.clear()
        if session is None:
            return
        self.list.addItem("○ État initial")
        for text, done in session.stack.history():
            item = QListWidgetItem(("● " if done else "○ ") + text)
            if not done:
                item.setForeground(self.palette().placeholderText())
            self.list.addItem(item)
        self.list.setCurrentRow(session.stack.done_count())
        trimmed = (
            f" · {session.stack.trimmed} étape(s) ancienne(s) oubliée(s)" if session.stack.trimmed else ""
        )
        self.memory.setText(
            f"Mémoire de l'historique : {session.stack.memory_used() / 1048576:.1f} Mo{trimmed}"
        )
        if session.project.file_path is not None:
            for point in restore_points.list_points(session.project):
                item = QListWidgetItem(icons.icon("history", size=14), point.label)
                item.setData(ID_ROLE, str(point.path))
                self.points.addItem(item)

    def _go_to(self, item: QListWidgetItem) -> None:
        session = self.controller.session
        if session is not None:
            session.stack.go_to(self.list.row(item))

    def create_point(self) -> None:
        session = self.controller.session
        if session is None:
            return
        try:
            point = restore_points.create(
                session.project, self.point_name.text().strip() or "Point de restauration"
            )
        except Exception as exc:  # noqa: BLE001 (ProjectError, disque plein…)
            self.controller.notify.emit("Point de restauration", str(exc), "warning")
            return
        self.point_name.clear()
        self.refresh()
        self.controller.notify.emit("Point de restauration créé", point.name, "success")

    def restore_point(self, confirm: bool = True) -> None:
        session, item = self.controller.session, self.points.currentItem()
        if session is None or item is None:
            return
        points = restore_points.list_points(session.project)
        point = next((p for p in points if str(p.path) == item.data(ID_ROLE)), None)
        if point is None:
            return
        if confirm:
            answer = QMessageBox.question(
                self, "Restaurer", f"Remplacer la scène actuelle par « {point.label} » ?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.controller.restore_point(point)


class CompatPanel(QWidget):
    LEVEL_ICONS = {"error": "circle-x", "warning": "triangle-alert", "info": "info"}

    def __init__(self, controller) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.controller = controller
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        header = QHBoxLayout()
        self.summary = label("", "muted")
        header.addWidget(self.summary, 1)
        header.addWidget(button("Analyser", "refresh-cw", self.refresh, "Recalcule le rapport technique"))
        layout.addLayout(header)
        self.list = QListWidget()
        self.list.itemClicked.connect(self._pick)
        layout.addWidget(self.list, 1)
        controller.session_changed.connect(self.refresh)

    def refresh(self) -> None:
        session = self.controller.session
        self.list.clear()
        if session is None:
            self.summary.setText("Aucun projet")
            return
        issues = compat.compatibility_report(session)
        counts = compat.summary(issues)
        self.summary.setText(
            f"{counts['error']} erreur(s), {counts['warning']} avertissement(s), "
            f"{counts['info']} information(s)"
        )
        for issue in issues:
            item = QListWidgetItem(
                icons.icon(self.LEVEL_ICONS[issue.level], size=14), f"{issue.label} — {issue.message}"
            )
            item.setData(ID_ROLE, issue.node_id)
            self.list.addItem(item)

    def _pick(self, item: QListWidgetItem) -> None:
        node_id = item.data(ID_ROLE)
        if node_id:
            self.controller.select([node_id])
