"""Design Comparison Studio : comparaison avant / après dans de vrais viewports 3D.

Modes : côte à côte (caméras synchronisées), séparateur interactif (découpe GL en temps réel),
superposition avec opacité, filaire, matériaux. A et B : original ou n'importe quelle variante.
Les mesures (« Mesurer ») sont calculées sur la géométrie (``lorefriendly.compare``).
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QSlider,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lsfcars.lorefriendly.compare import DIMENSION_LABELS
from lsfcars.lorefriendly.components import COMPONENT_LABELS
from lsfcars.lorefriendly.engine import SOURCE
from lsfcars.render.renderer import Overlay
from lsfcars.scene.graph import NodeKind
from lsfcars.ui.design import tokens
from lsfcars.ui.design.components import LSSelect, label
from lsfcars.ui.editor.panels import button
from lsfcars.ui.livery.panels import check, clear_items
from lsfcars.ui.viewport import Viewport3D

C = tokens.ColorTokens
MODES = (
    ("Côte à côte", "side"),
    ("Séparateur interactif", "split"),
    ("Superposition", "overlay"),
    ("Filaire", "wire"),
    ("Matériaux", "materials"),
)
STATUS_COLORS = {"déformé": C.ELECTRIC, "remplacé ou masqué": C.WARNING, "ajouté": C.SUCCESS}
VIEW_NAMES = {"left": "Profil", "front": "Face avant", "back": "Face arrière", "top": "Dessus"}


class ComparisonView(QWidget):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        self._syncing = False
        self.result: dict | None = None
        self.show_displacements = False
        self._overlay_points: np.ndarray | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        bar = QHBoxLayout()
        bar.setContentsMargins(10, 6, 10, 0)
        self.a = LSSelect()
        self.b = LSSelect()
        self.mode = LSSelect(list(MODES))
        self.isolate = LSSelect([("Tous les composants", None)])
        for widget in (self.a, self.b, self.mode, self.isolate):
            widget.activated.connect(lambda _i: self.apply())
        self.sync = check("Caméras synchronisées", True)
        for widget, stretch in (
            (label("A", "muted"), 0),
            (self.a, 1),
            (label("B", "muted"), 0),
            (self.b, 1),
            (self.mode, 0),
            (self.isolate, 0),
            (self.sync, 0),
        ):
            bar.addWidget(widget, stretch)
        layout.addLayout(bar)
        actions = QHBoxLayout()
        actions.setContentsMargins(10, 0, 10, 0)
        actions.addWidget(
            button("Mesurer les différences", "scan", self.measure, "Mesures géométriques réelles", "primary")
        )
        actions.addWidget(
            button(
                "Déplacements", "orbit", self.toggle_displacements, "Sommets déplacés (couleur = amplitude)"
            )
        )
        actions.addWidget(button("Recadrer", "maximize-2", self.frame, "Cadrer les deux véhicules"))
        actions.addWidget(
            button("Revenir à l'original", "undo-2", lambda: page.show(SOURCE), "Afficher le véhicule source")
        )
        actions.addStretch(1)
        layout.addLayout(actions)

        self.view_a = Viewport3D()
        self.view_b = Viewport3D()
        self.view_single = Viewport3D()
        for view in (self.view_a, self.view_b, self.view_single):
            view.show_selection = False
            view.show_anchors = False
            view.view_changed.connect(lambda v=view: self._sync_from(v))
        self.view_b.overlay_providers.append(self._displacement_overlay)
        self.view_single.overlay_providers.append(self._displacement_overlay)
        side = QSplitter(Qt.Orientation.Horizontal)
        side.setHandleWidth(2)
        side.addWidget(self.view_a)
        side.addWidget(self.view_b)
        single = QWidget()
        single_layout = QVBoxLayout(single)
        single_layout.setContentsMargins(0, 0, 0, 0)
        single_layout.addWidget(self.view_single, 1)
        self.divider = QFrame(self.view_single)  # trait du séparateur (A à gauche, B à droite)
        self.divider.setFixedWidth(2)
        self.divider.setStyleSheet(f"background: {C.ELECTRIC};")
        self.divider.hide()
        self.view_single.installEventFilter(self)
        slider_row = QHBoxLayout()
        slider_row.setContentsMargins(10, 0, 10, 4)
        self.slider_label = label("Séparateur", "faint")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(50)
        self.slider.valueChanged.connect(lambda _v: self.apply())
        slider_row.addWidget(self.slider_label)
        slider_row.addWidget(self.slider, 1)
        single_layout.addLayout(slider_row)
        self.stack = QStackedWidget()
        self.stack.addWidget(side)
        self.stack.addWidget(single)
        layout.addWidget(self.stack, 1)
        self.results = QTreeWidget()
        self.results.setHeaderLabels(["Mesure", "A", "B", "Écart / état"])
        self.results.setMaximumHeight(190)
        self.results.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.results)
        self.limits = label("", "faint", wrap=True)
        layout.addWidget(self.limits)

    # --- Données -------------------------------------------------------------------------
    def set_session(self, session) -> None:  # type: ignore[no-untyped-def]
        self.result = None
        self._overlay_points = None
        for view in (self.view_a, self.view_b, self.view_single):
            view.set_session(session)

    def refresh(self) -> None:
        engine = self.page.engine
        design = self.page.design()
        current_a, current_b = self.a.currentData(), self.b.currentData()
        self.a.clear()
        self.b.clear()
        if engine is None or design is None:
            clear_items(self.results)
            return
        for target, name in engine.targets(design):
            self.a.addItem(name, target)
            self.b.addItem(name, target)
        displayed = self.page.target()
        fallback = (
            displayed
            if displayed != SOURCE
            else (design["variants"][-1]["id"] if design["variants"] else SOURCE)
        )
        self.a.select_data(current_a if self.a.findData(current_a) >= 0 else SOURCE)
        self.b.select_data(current_b if self.b.findData(current_b) >= 0 and current_b != SOURCE else fallback)
        chosen = self.isolate.currentData()
        self.isolate.clear()
        self.isolate.addItem("Tous les composants", None)
        for kind in sorted({c.kind for c in self._components(self.b.currentData())}):
            self.isolate.addItem(COMPONENT_LABELS.get(kind, kind), kind)
        self.isolate.select_data(chosen)
        self.apply()

    def _components(self, target):  # type: ignore[no-untyped-def]
        design = self.page.design()
        if design is None or target is None:
            return []
        try:
            return self.page.engine.state(design, target).components.components
        except Exception:  # noqa: BLE001 (cible disparue : liste vide)
            return []

    def _mesh_ids(self, target: str | None) -> tuple[set[str], str | None]:
        design = self.page.design()
        if design is None or target is None:
            return set(), None
        try:
            root = self.page.engine.root_of(design, target)
        except Exception:  # noqa: BLE001
            return set(), None
        ids = {n.id for n in self.page.session.scene.subtree(root) if n.kind is NodeKind.MESH}
        kind = self.isolate.currentData()
        if kind:
            ids &= {m for c in self._components(target) if c.kind == kind for m in c.mesh_ids}
        return ids, root

    # --- Affichage ---------------------------------------------------------------------------
    def apply(self) -> None:
        mode = self.mode.currentData()
        ids_a, root_a = self._mesh_ids(self.a.currentData())
        ids_b, root_b = self._mesh_ids(self.b.currentData())
        roots = {r for r in (root_a, root_b) if r}
        for view in (self.view_a, self.view_b, self.view_single):
            view.force_visible = set(roots)
            view.ghost_ids = set()
            view.split = None
            view.set_shading("wireframe" if mode == "wire" else "material")
        self.view_a.set_isolation(ids_a)
        self.view_b.set_isolation(ids_b)
        self.stack.setCurrentIndex(1 if mode in ("split", "overlay") else 0)
        self.slider_label.setText("Séparateur" if mode == "split" else "Opacité de A")
        self.divider.setVisible(mode == "split")
        if mode == "split":
            self.view_single.split = (ids_a, ids_b, self.slider.value() / 100.0)
            self.view_single.set_isolation(ids_a | ids_b)
            self._place_divider()
        elif mode == "overlay":
            self.view_single.ghost_ids = ids_a - ids_b
            self.view_single.ghost_opacity = max(0.05, self.slider.value() / 100.0)
            self.view_single.set_isolation(ids_a | ids_b)
        if mode == "materials":
            self._material_rows()
        elif self.result is not None:
            self.show_result(self.result)
        for view in (self.view_a, self.view_b, self.view_single):
            view.update()

    def _place_divider(self) -> None:
        x = int(self.view_single.width() * self.slider.value() / 100.0)
        self.divider.setGeometry(x - 1, 0, 2, self.view_single.height())
        self.divider.raise_()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (API Qt)
        if watched is self.view_single and event.type() == QEvent.Type.Resize and self.divider.isVisible():
            self._place_divider()
        return super().eventFilter(watched, event)

    def frame(self) -> None:
        session = self.page.session
        if session is None:
            return
        ids = set(self.view_a.isolated or set()) | set(self.view_b.isolated or set())
        bounds = session.world_bounds(list(ids), only_visible=False) if ids else None
        for view in (self.view_a, self.view_b, self.view_single):
            view.frame_bounds(bounds)

    def _sync_from(self, source: Viewport3D) -> None:
        if self._syncing or not self.sync.isChecked():
            return
        self._syncing = True
        try:
            state = source.camera.to_state()
            for view in (self.view_a, self.view_b, self.view_single):
                if view is not source:
                    view.camera.apply_state(state)
                    view.update()
        finally:
            self._syncing = False

    # --- Mesures ---------------------------------------------------------------------------------
    def measure(self) -> dict | None:
        a, b = self.a.currentData(), self.b.currentData()
        if a is None or b is None:
            return None
        result = self.page.run("Comparaison", lambda: self.page.engine.compare(None, a, b))
        if result is not None:
            self.result = result
            self.show_result(result)
        return result

    def show_result(self, result: dict) -> None:
        clear_items(self.results)
        dims = result["dimensions"]
        group = QTreeWidgetItem(["Dimensions (mesures)"])
        self.results.addTopLevelItem(group)
        for key, text in DIMENSION_LABELS.items():
            if key in dims["a"] and key in dims["b"]:
                delta = dims["delta"].get(key, 0.0)
                group.addChild(
                    QTreeWidgetItem(
                        [text, f"{dims['a'][key]:.3f} m", f"{dims['b'][key]:.3f} m", f"{delta:+.3f} m"]
                    )
                )
        sil = QTreeWidgetItem(["Recouvrement des silhouettes (mesure technique, 1 = identiques)"])
        self.results.addTopLevelItem(sil)
        for view, value in result["silhouettes"].items():
            sil.addChild(QTreeWidgetItem([VIEW_NAMES.get(view, view), "", "", f"{value:.3f}"]))
        summary = (
            f"Composants : {result['deformed']} déformé(s), {result['replaced']} remplacé(s), "
            f"{len(result['added'])} ajouté(s)"
        )
        comps = QTreeWidgetItem([summary])
        self.results.addTopLevelItem(comps)
        for comp in [c for c in result["components"] if c["status"] != "identique"] + result["added"]:
            detail = comp["status"]
            if comp.get("max") is not None and comp["status"] == "déformé":
                detail += f" (jusqu'à {comp['max'] * 100:.1f} cm)"
            item = QTreeWidgetItem([f"{comp['label']} — {comp['name']}", "", "", detail])
            item.setForeground(3, QColor(STATUS_COLORS.get(comp["status"], C.TEXT_SECONDARY)))
            comps.addChild(item)
        for top in (group, sil, comps):
            top.setExpanded(True)
        self.limits.setText(result["limits"])

    def _material_rows(self) -> None:
        clear_items(self.results)
        scene = self.page.session.scene
        group = QTreeWidgetItem(["Matériaux (A → B)"])
        self.results.addTopLevelItem(group)
        rows: dict[str, list] = {}
        for target, column in ((self.a.currentData(), 0), (self.b.currentData(), 1)):
            ids, _root = self._mesh_ids(target)
            for node_id in ids:
                node = scene.nodes[node_id]
                key = node.extra.get("lore", {}).get("copy_of", node_id)
                rows.setdefault(key, [None, None, node.name])[column] = scene.material_for(node_id)
        for material_a, material_b, name in sorted(rows.values(), key=lambda r: r[2]):
            if material_a is material_b:
                continue
            state = "nouvelle pièce" if material_a is None else "matériau changé"
            if material_b is not None and material_b.is_emissive:
                state += " · émissif (aperçu viewport)"
            group.addChild(
                QTreeWidgetItem(
                    [
                        name,
                        material_a.name if material_a else "—",
                        material_b.name if material_b else "—",
                        state,
                    ]
                )
            )
        if not group.childCount():
            group.addChild(QTreeWidgetItem(["Aucune différence de matériau", "", "", ""]))
        group.setExpanded(True)

    def toggle_displacements(self) -> None:
        self.show_displacements = not self.show_displacements
        self._overlay_points = None
        if self.show_displacements:
            a, b = self.a.currentData(), self.b.currentData()
            self._overlay_points = self.page.run("Déplacements", lambda: self.page.engine.overlay(None, a, b))
        for view in (self.view_b, self.view_single):
            view.update()

    def _displacement_overlay(self) -> list[Overlay]:
        points = self._overlay_points
        if not self.show_displacements or points is None or not len(points):
            return []
        return [Overlay(points=points, point_size=4.0, xray=True, point_style="round")]
