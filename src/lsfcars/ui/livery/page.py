"""Livery Studio Pro : page principale.

Disposition : outils, formes, logos, modèles | vue 3D et vue UV 2D (seule ou partagée) |
calques, propriétés, couleurs, matériaux, livrées, export — en bas : historique, progression,
diagnostics, UV. La peinture 3D modifie réellement les pixels de la texture : le viewport,
le canvas 2D et l'export partagent la même composition.
"""

from __future__ import annotations

import copy
import math

import numpy as np
from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from lsfcars.core.logging_setup import get_logger
from lsfcars.livery import export, render2d
from lsfcars.livery import templates as tpl
from lsfcars.livery.logos import LogoError, LogoLibrary
from lsfcars.livery.model import STANDARD_SIZES, rgba
from lsfcars.livery.studio import LiveryError, LiveryStudio
from lsfcars.render.renderer import Overlay
from lsfcars.scene.editmesh import EditError
from lsfcars.ui.design.components import LSBadge, LSButton, LSInput, LSSelect, LSTabs, label, tooltip
from lsfcars.ui.editor.panels import HistoryPanel, scroll
from lsfcars.ui.livery.canvas import TOOLS, Canvas2D
from lsfcars.ui.livery.colors import ColorPanel
from lsfcars.ui.livery.panels import (
    DiagnosticsPanel,
    ExportPanel,
    LayersPanel,
    LogosPanel,
    MarkingsPanel,
    MaterialsPanel,
    ProgressPanel,
    PropertiesPanel,
    TemplatesPanel,
    ToolsPanel,
    UVPanel,
    VariantsPanel,
)
from lsfcars.ui.viewport import Viewport3D

log = get_logger(__name__)
ID_ROLE = Qt.ItemDataRole.UserRole
EXPECTED = (LiveryError, LogoError, EditError, ValueError, KeyError, OSError)


class NewDocumentDialog(QDialog):
    """Nouveau document : matériaux ciblés, résolution, modèle, numéro d'unité."""

    def __init__(self, studio: LiveryStudio, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Nouveau document de livrée")
        layout = QVBoxLayout(self)
        layout.addWidget(
            label(
                "Matériaux recevant la livrée (ils doivent partager le même dépliage UV) :",
                "muted",
                wrap=True,
            )
        )
        self.materials = QListWidget()
        for index, candidate in enumerate(studio.candidate_materials()):
            uv = "UV" if candidate["with_uv"] else "sans UV"
            item = QListWidgetItem(f"{candidate['name']} — {candidate['meshes']} maillage(s), {uv}")
            item.setData(ID_ROLE, candidate["id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if index == 0 else Qt.CheckState.Unchecked)
            self.materials.addItem(item)
        layout.addWidget(self.materials)
        self.size = LSSelect(
            [("Selon la texture d'origine", 0)] + [(f"{s} × {s}", s) for s in STANDARD_SIZES]
        )
        self.template = LSSelect(
            [("Vierge", "")] + [(tpl.CATEGORIES[t.key], t.key) for t in tpl.BUILTIN_TEMPLATES]
        )
        self.unit = LSInput("Numéro d'unité (optionnel)")
        self.name = LSInput("Nom de la première livrée")
        self.name.setText("Livrée 1")
        for text, widget in (
            ("Résolution", self.size),
            ("Modèle", self.template),
            ("Unité", self.unit),
            ("Nom", self.name),
        ):
            row = QHBoxLayout()
            row.addWidget(label(text, "muted"))
            row.addWidget(widget, 1)
            layout.addLayout(row)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def targets(self) -> list[str]:
        return [
            self.materials.item(i).data(ID_ROLE)
            for i in range(self.materials.count())
            if self.materials.item(i).checkState() == Qt.CheckState.Checked
        ]


class LiveryPage(QWidget):
    changed = Signal()
    editor_requested = Signal()

    def __init__(self, controller, settings, parent: QWidget | None = None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.controller = controller
        self.settings = settings
        self.studio: LiveryStudio | None = None
        self.logos: LogoLibrary | None = None
        self.emergency_page = None  # EmergencyPage : aperçu des éclairages
        self.tool = "brush"
        self.view_mode = "split"
        self.current_layer_id: str | None = None
        self.refreshing = False
        self.tool_settings: dict = {}
        self._commit_label = "Modification"
        self._hover = None
        self._worker = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.refresh)
        self._commit_timer = QTimer(self)
        self._commit_timer.setSingleShot(True)
        self._commit_timer.setInterval(450)
        self._commit_timer.timeout.connect(lambda: self.commit_edit())
        self._light_timer = QTimer(self)
        self._light_timer.setInterval(33)
        self._light_timer.timeout.connect(lambda: self.viewport.update())

        self.viewport = Viewport3D()
        self.viewport.stroke_handler = self
        self.viewport.show_selection = False  # la livrée doit rester lisible
        self.viewport.overlay_providers.append(self._brush_overlay)
        self.viewport.overlay_providers.append(self._light_overlays)
        self.viewport.frame_requested.connect(self.frame_vehicle)
        self.canvas = Canvas2D(self)
        self.canvas.color_picked.connect(lambda c: self.colors.set_color(c, record=True))
        self.canvas.status.connect(lambda text: self.status.setText(text))
        self.canvas.layer_selected.connect(self.select_layer)

        self.tools = ToolsPanel(self)
        self.markings = MarkingsPanel(self)
        self.logos_panel = LogosPanel(self)
        self.templates = TemplatesPanel(self)
        self.left = LSTabs()
        self.left.addTab(scroll(self.tools), "Outils")
        self.left.addTab(scroll(self.markings), "Formes")
        self.left.addTab(scroll(self.logos_panel), "Logos")
        self.left.addTab(scroll(self.templates), "Modèles")
        self.layers = LayersPanel(self)
        self.properties = PropertiesPanel(self)
        self.colors = ColorPanel(self)
        self.colors.pipette_requested.connect(lambda: self.set_tool("pipette"))
        self.materials = MaterialsPanel(self)
        self.variants = VariantsPanel(self)
        self.export_panel = ExportPanel(self)
        self.right = LSTabs()
        self.right.addTab(self.layers, "Calques")
        self.right.addTab(scroll(self.properties), "Propriétés")
        self.right.addTab(scroll(self.colors), "Couleurs")
        self.right.addTab(scroll(self.materials), "Matériaux")
        self.right.addTab(scroll(self.variants), "Livrées")
        self.right.addTab(scroll(self.export_panel), "Export")
        self.history = HistoryPanel(controller)
        self.progress = ProgressPanel()
        self.diagnostics = DiagnosticsPanel(self)
        self.uv_panel = UVPanel(self)
        self.bottom = LSTabs()
        self.bottom.addTab(self.history, "Historique")
        self.bottom.addTab(self.progress, "Progression")
        self.bottom.addTab(self.diagnostics, "Diagnostics")
        self.bottom.addTab(self.uv_panel, "UV")
        self.bottom.currentChanged.connect(lambda _i: self._refresh_bottom())
        for panel in (self.left, self.right, self.bottom):
            panel.setObjectName("LSStudioPanel")
            panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.left.setMinimumWidth(300)
        self.right.setMinimumWidth(340)

        self.views = QSplitter(Qt.Orientation.Horizontal)
        self.views.setHandleWidth(2)
        self.views.addWidget(self.viewport)
        self.views.addWidget(self.canvas)
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        center_layout.addWidget(self._header())
        center_layout.addWidget(self.views, 1)
        self.h_split = QSplitter(Qt.Orientation.Horizontal)
        self.h_split.setHandleWidth(1)
        for widget in (self.left, center, self.right):
            self.h_split.addWidget(widget)
        self.h_split.setStretchFactor(1, 1)
        self.h_split.setSizes([330, 900, 370])
        self.v_split = QSplitter(Qt.Orientation.Vertical)
        self.v_split.setHandleWidth(1)
        self.v_split.addWidget(self.h_split)
        self.v_split.addWidget(self.bottom)
        self.v_split.setStretchFactor(0, 1)
        self.v_split.setSizes([720, 190])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.v_split)
        for combo in self.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
        self._shortcuts()
        self.set_tool("brush")
        self.set_view_mode("split")
        self.restore_layout()
        controller.session_changed.connect(self._on_session)
        for signal in (controller.scene_changed, controller.state_changed):
            signal.connect(lambda *_: self.schedule_refresh())
        self._on_session()

    # --- En-tête ------------------------------------------------------------------------------
    def _header(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("LSStudioPanel")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(6)
        self.badge = LSBadge("Aucun document", "neutral")
        row.addWidget(self.badge)
        self.status = label("", "faint")
        self.status.setMinimumWidth(40)
        row.addWidget(self.status, 1)
        self.view_group = QButtonGroup(self)
        self.view_buttons: dict[str, LSButton] = {}
        for key, text, icon_name, tip in (
            ("3d", "3D", "cuboid", "Vue 3D seule (1)"),
            ("uv", "UV 2D", "lsf-island", "Vue UV 2D seule (2)"),
            ("split", "2D + 3D", "lsf-split", "Vue partagée (3)"),
        ):
            widget = LSButton(text, "ghost", icon_name, True)
            widget.setCheckable(True)
            widget.setProperty("chip", True)
            widget.clicked.connect(lambda _c=False, k=key: self.set_view_mode(k))
            tooltip(widget, tip)
            self.view_group.addButton(widget)
            self.view_buttons[key] = widget
            row.addWidget(widget)
        self.lights_button = LSButton("Éclairages", "ghost", "siren", True)
        self.lights_button.setCheckable(True)
        self.lights_button.setProperty("chip", True)
        self.lights_button.clicked.connect(self.set_lights)
        tooltip(self.lights_button, "Aperçu simulé des feux de la variante d'urgence (Emergency Studio)")
        row.addWidget(self.lights_button)
        self.new_button = LSButton("Nouveau document", "primary", "plus", True)
        self.new_button.clicked.connect(self.create_document_dialog)
        row.addWidget(self.new_button)
        editor = LSButton("Vehicle Editor", "ghost", "cuboid", True)
        editor.clicked.connect(self.editor_requested)
        tooltip(editor, "Revenir au Vehicle Editor (même projet, rien n'est perdu)")
        row.addWidget(editor)
        return bar

    def set_view_mode(self, mode: str) -> None:
        self.viewport.setVisible(mode in ("3d", "split"))
        self.canvas.setVisible(mode in ("uv", "split"))
        if mode in self.view_buttons:
            self.view_buttons[mode].setChecked(True)
        self.view_mode = mode
        if mode != "3d":
            QTimer.singleShot(0, self.canvas.fit)

    def set_lights(self, enabled: bool) -> None:
        page = self.emergency_page
        available = page is not None and page.active_variant() is not None
        enabled = bool(enabled) and available
        self.lights_button.setChecked(enabled)
        if page is not None and available:
            page.set_playing(enabled)
        if enabled:
            self._light_timer.start()
        else:
            self._light_timer.stop()
            if not available:
                self.controller.notify.emit("Éclairages", "Aucune variante d'urgence avec des feux.", "info")
        self.viewport.update()

    def _light_overlays(self) -> list[Overlay]:
        if self.lights_button.isChecked() and self.emergency_page is not None:
            return self.emergency_page.light_overlays()
        return []

    # --- Raccourcis ---------------------------------------------------------------------------
    def _shortcuts(self) -> None:
        def bind(sequence: str, slot) -> None:  # type: ignore[no-untyped-def]
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)

        for key, _text, _icon, sequence in TOOLS:
            bind(sequence, lambda k=key: self.set_tool(k))
        bind("[", lambda: self.tools.size.setValue(max(1, self.tools.size.value() / 1.25)))
        bind("]", lambda: self.tools.size.setValue(min(1024, self.tools.size.value() * 1.25)))
        bind("X", self.colors.swap)
        bind("Delete", self.remove_layer)
        bind("Ctrl+J", self.duplicate_layer)
        bind("Ctrl+E", self.merge_down)
        bind("Ctrl+G", self.group_selected)
        bind("Ctrl+A", self.select_all)
        bind("Ctrl+D", self.clear_selection)
        bind("Ctrl+C", self.copy)
        bind("Ctrl+X", self.cut)
        bind("Ctrl+V", self.paste)
        bind("1", lambda: self.set_view_mode("3d"))
        bind("2", lambda: self.set_view_mode("uv"))
        bind("3", lambda: self.set_view_mode("split"))
        bind("F", self.canvas.fit)

    # --- Session ------------------------------------------------------------------------------
    def set_logos(self, library: LogoLibrary) -> None:
        self.logos = library
        if self.studio is not None:
            self.studio.logos = library
        self.logos_panel.refresh()

    def ensure_logos(self) -> None:
        if self.logos is None:
            library = LogoLibrary()
            library.ensure_builtins()
            self.set_logos(library)

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        super().showEvent(event)
        self.ensure_logos()
        if self.studio is not None:
            emergency = self.studio.active_emergency_variant()
            if emergency and self.studio.document() is not None:
                self.run("Livrée associée", lambda: self.studio.follow_emergency(emergency))
        self.schedule_refresh()

    def _on_session(self) -> None:
        session = self.controller.session
        self.viewport.set_session(session)
        self.current_layer_id = None
        self.studio = LiveryStudio(session, self.logos) if session is not None else None
        if session is not None:
            self.frame_vehicle()
        self.refresh()

    def frame_vehicle(self) -> None:
        session = self.controller.session
        self.viewport.frame_bounds(session.world_bounds() if session else None)

    # --- Exécution ----------------------------------------------------------------------------
    def run(self, title: str, action):  # type: ignore[no-untyped-def]
        """Exécute une opération ; les erreurs prévues deviennent des notifications."""
        self.commit_edit()
        try:
            result = action()
        except EXPECTED as exc:
            log.warning("%s : %s", title, exc)
            self.controller.notify.emit(title, str(exc), "warning")
            return None
        self.schedule_refresh()
        return result

    def schedule_refresh(self) -> None:
        self._refresh_timer.start(0)

    def texture_changed(self) -> None:
        self.canvas.texture_changed()
        self.viewport.update()

    def refresh(self) -> None:
        self.refreshing = True
        try:
            studio = self.studio
            doc = studio.document() if studio is not None else None
            if studio is not None:
                try:
                    studio.refresh()
                except EXPECTED as exc:
                    self.controller.notify.emit("Livrée", str(exc), "warning")
            variant = doc.active_variant if doc else None
            if doc is not None and self.current_layer() is None:
                self.current_layer_id = variant.layers[-1].id if variant and variant.layers else None
            if doc is None:
                self.badge.setText("Aucun document")
                self.status.setText("Créez un document de livrée (bouton « Nouveau document »).")
            else:
                self.badge.setText(f"{variant.name if variant else '—'} · {doc.width}×{doc.height}")
                if self.status.text().startswith("Créez"):
                    self.status.setText("Clic gauche sur la carrosserie : peindre · Alt + glisser : orbite")
            self.new_button.setVisible(doc is None)
            for panel in (
                self.layers,
                self.colors,
                self.materials,
                self.variants,
                self.export_panel,
                self.templates,
            ):
                panel.refresh()
            self.properties.refresh()
            self.canvas.texture_changed()
            self.canvas.surface_changed()
            self.canvas.selection_updated()
            self._refresh_bottom()
            self.viewport.refresh()
        finally:
            self.refreshing = False
        self.changed.emit()

    def _refresh_bottom(self) -> None:
        widget = self.bottom.currentWidget()
        if widget is self.diagnostics:
            self.diagnostics.refresh()
        elif widget is self.uv_panel:
            self.uv_panel.refresh()

    # --- Édition interactive des paramètres ----------------------------------------------------
    def edit_param(self, key: str, value, label_text: str, now: bool = False) -> None:  # type: ignore[no-untyped-def]
        self.edit_params({key: value}, label_text, now)

    def edit_params(self, params: dict, label_text: str, now: bool = False) -> None:
        layer, studio = self.current_layer(), self.studio
        if layer is None or studio is None:
            return
        if layer.locked:
            self.controller.notify.emit("Calque", f"« {layer.name} » est verrouillé.", "info")
            return
        layer_id = layer.id

        def mutate(doc) -> None:  # type: ignore[no-untyped-def]
            found = doc.find(layer_id)
            if found is not None:
                found[0].params.update(copy.deepcopy(params))

        studio.preview(mutate)
        self._commit_label = label_text
        self.texture_changed()
        if now:
            self.commit_edit(label_text)
        else:
            self._commit_timer.start()

    def schedule_commit(self, label_text: str) -> None:
        self._commit_label = label_text
        self._commit_timer.start()

    def commit_edit(self, label_text: str | None = None) -> None:
        self._commit_timer.stop()
        if self.studio is not None and self.studio.editing:
            self.studio.commit_edit(label_text or self._commit_label)
            self.schedule_refresh()

    # --- Calques et outils ----------------------------------------------------------------------
    def set_tool(self, key: str) -> None:
        self.tool = key
        self.tools.set_tool(key)
        self.canvas.update()
        if key not in ("brush", "eraser") and self._hover is not None:
            self._hover = None
        self.viewport.update()

    def brush_settings(self):  # type: ignore[no-untyped-def]
        return self.tools.brush_settings(self.tool == "eraser")

    def layer_by_id(self, layer_id: str | None):  # type: ignore[no-untyped-def]
        doc = self.studio.document() if self.studio and layer_id else None
        found = doc.find(layer_id) if doc else None
        return found[0] if found else None

    def current_layer(self):  # type: ignore[no-untyped-def]
        return self.layer_by_id(self.current_layer_id)

    def select_layer(self, layer_id: str) -> None:
        self.current_layer_id = layer_id
        self.layers.select_layer(layer_id)
        self.properties.refresh()
        self.canvas.update()

    def _after_create(self, layer_id) -> None:  # type: ignore[no-untyped-def]
        if isinstance(layer_id, list):
            layer_id = layer_id[-1] if layer_id else None
        if isinstance(layer_id, str):
            self.current_layer_id = layer_id
            self.schedule_refresh()

    def add_layer(self, kind: str) -> str | None:
        if self.studio is None:
            return None
        current = self.current_layer()
        parent = current.id if current is not None and current.kind == "group" and kind != "group" else None
        layer_id = self.run("Calque", lambda: self.studio.add_layer(kind, parent=parent))
        self._after_create(layer_id)
        return layer_id

    def remove_layer(self) -> None:
        layer = self.current_layer()
        if layer is not None:
            self.run("Calque", lambda: self.studio.remove_layer(layer.id))
            self.current_layer_id = None

    def duplicate_layer(self) -> str | None:
        layer = self.current_layer()
        if layer is None:
            return None
        layer_id = self.run("Calque", lambda: self.studio.duplicate_layer(layer.id))
        self._after_create(layer_id)
        return layer_id

    def move_layer(self, offset: int) -> None:
        layer = self.current_layer()
        if layer is not None:
            self.run("Calque", lambda: self.studio.move_layer(layer.id, offset))

    def group_selected(self) -> str | None:
        ids = self.layers.selected_ids() or ([self.current_layer_id] if self.current_layer_id else [])
        if not ids or self.studio is None:
            return None
        group_id = self.run("Groupe", lambda: self.studio.group_layers(ids))
        self._after_create(group_id)
        return group_id

    def ungroup(self) -> None:
        layer = self.current_layer()
        if layer is not None and layer.kind == "group":
            self.run("Groupe", lambda: self.studio.ungroup(layer.id))
            self.current_layer_id = None

    def merge_down(self) -> None:
        layer = self.current_layer()
        if layer is not None:
            self._after_create(self.run("Fusion", lambda: self.studio.merge_down(layer.id)))

    def rasterize_layer(self) -> None:
        layer = self.current_layer()
        if layer is not None:
            self.run("Pixellisation", lambda: self.studio.rasterize_layer(layer.id))

    def add_mask(self) -> None:
        layer = self.current_layer()
        if layer is not None:
            self.run("Masque", lambda: self.studio.add_mask(layer.id))

    def mask_from_selection(self) -> None:
        layer = self.current_layer()
        if layer is not None:
            self.run("Masque", lambda: self.studio.add_mask(layer.id, from_selection=True))

    def invert_mask(self) -> None:
        layer = self.current_layer()
        if layer is not None:
            self.run("Masque", lambda: self.studio.invert_mask(layer.id))

    def apply_mask(self) -> None:
        layer = self.current_layer()
        if layer is not None:
            self.run("Masque", lambda: self.studio.apply_mask(layer.id))

    def delete_mask(self) -> None:
        layer = self.current_layer()
        if layer is not None:
            self.run("Masque", lambda: self.studio.delete_mask(layer.id))

    def set_shared(self, shared: bool) -> None:
        layer = self.current_layer()
        if layer is not None:
            self.run("Élément commun", lambda: self.studio.set_shared(layer.id, shared))

    def apply_structure(self, structure: list) -> None:
        if self.studio is not None:
            self.run("Ordre des calques", lambda: self.studio.restructure(structure))

    def mirror_layer(self) -> str | None:
        layer = self.current_layer()
        if layer is None:
            return None
        layer_id = self.run("Symétrie", lambda: self.studio.mirror_layer(layer.id))
        self._after_create(layer_id)
        return layer_id

    def align(self, mode: str, reference: str) -> None:
        layer = self.current_layer()
        if layer is not None:
            ids = self.layers.selected_ids() or [layer.id]
            self.run("Alignement", lambda: self.studio.align_layers(ids, mode, reference))

    def transform_current(self, rotation: float = 0.0, scale: float = 1.0) -> None:
        layer = self.current_layer()
        if layer is not None:
            self.run(
                "Transformation",
                lambda: self.studio.transform_layer(layer.id, rotation=rotation, scale=scale),
            )

    def element_at(self, x: float, y: float):  # type: ignore[no-untyped-def]
        """Élément (texte, logo, forme) visible le plus haut sous le point (x, y)."""
        doc = self.studio.document() if self.studio else None
        variant = doc.active_variant if doc else None
        if variant is None:
            return None

        def walk(layers):  # type: ignore[no-untyped-def]
            for layer in reversed(layers):
                if not layer.visible:
                    continue
                if layer.children:
                    found = walk(layer.children)
                    if found is not None:
                        return found
                bounds = render2d.element_bounds(layer, self.studio.scene.blobs)
                if layer.kind in ("text", "image", "vector") and bounds.contains(QPointF(x, y)):
                    return layer
            return None

        return walk(variant.layers)

    # --- Sélection et presse-papiers -------------------------------------------------------------
    def selection_changed(self) -> None:
        self.canvas.selection_updated()

    def select_all(self) -> None:
        if self.studio is not None and self.studio.document() is not None:
            self.studio.select_all()
            self.selection_changed()

    def clear_selection(self) -> None:
        if self.studio is not None:
            self.studio.clear_selection()
            self.selection_changed()

    def copy(self) -> None:
        if self.studio is not None:
            self.run("Copier", lambda: self.studio.copy(self.current_layer_id))

    def cut(self) -> None:
        layer = self.current_layer()
        if layer is not None:
            self.run("Couper", lambda: self.studio.cut(layer.id))

    def paste(self) -> None:
        if self.studio is not None:
            self._after_create(self.run("Coller", self.studio.paste))

    # --- Peinture --------------------------------------------------------------------------------
    def _paint_layer(self) -> str | None:
        """Calque raster cible : le calque actif, sinon le raster le plus haut (créé au besoin)."""
        layer = self.current_layer()
        target = self.tools.target.currentData()
        if layer is not None and (layer.kind == "raster" or (target == "mask" and layer.mask)):
            return layer.id
        doc = self.studio.document()
        variant = doc.active_variant if doc else None
        if variant is None:
            return None
        raster = next((item for item in reversed(list(variant.walk())) if item.kind == "raster"), None)
        layer_id = self.studio.add_layer("raster", "Peinture") if raster is None else raster.id
        self.current_layer_id = layer_id
        if layer is not None:
            name = self.layer_by_id(layer_id).name
            self.controller.notify.emit("Peinture", f"Peinture sur le calque raster « {name} ».", "info")
        return layer_id

    def begin_stroke(self, x: float | None, y: float | None, pressure: float, mode: str = "2d") -> bool:
        studio = self.studio
        if studio is None or studio.document() is None:
            return False
        self.commit_edit()
        try:
            layer_id = self._paint_layer()
            if layer_id is None:
                return False
            studio.begin_stroke(
                layer_id,
                self.colors.color(),
                self.brush_settings(),
                self.tools.target.currentData(),
                self.tools.symmetry.isChecked(),
                mode,
                self.tools.lock_alpha.isChecked(),
            )
            if mode == "2d" and x is not None and y is not None:
                studio.stroke_2d(x, y, pressure)
        except EXPECTED as exc:
            self.controller.notify.emit("Peinture", str(exc), "warning")
            return False
        self.texture_changed()
        return True

    def continue_stroke(self, x: float, y: float, pressure: float, mode: str = "2d") -> None:
        if self.studio is not None and self.studio.stroking:
            self.studio.stroke_2d(x, y, pressure)
            self.texture_changed()

    def end_stroke(self) -> None:
        if self.studio is not None and self.studio.stroking:
            self.studio.end_stroke()
            if self.tool == "brush":
                self.studio.record_color(self.colors.color())
            self.schedule_refresh()

    def fill_at(self, x: float, y: float) -> None:
        if self.studio is None:
            return
        layer_id = self.run("Remplissage", self._paint_layer)
        if layer_id is None:
            return
        tools = self.tools
        color, tolerance, mode = self.colors.color(), tools.tolerance.value(), tools.fill_mode.currentData()
        opacity, target = tools.fill_opacity.value() / 100, tools.target.currentData()
        self.run(
            "Remplissage", lambda: self.studio.fill(layer_id, x, y, color, tolerance, mode, opacity, target)
        )

    def gradient_between(self, p0: tuple[float, float], p1: tuple[float, float]) -> None:
        if self.studio is None:
            return
        layer_id = self.run("Dégradé", self._paint_layer)
        if layer_id is None:
            return
        c0, c1 = self.colors.color(), self.colors.secondary()
        kind, opacity = self.tools.gradient_kind.currentData(), self.tools.gradient_opacity.value() / 100
        self.run("Dégradé", lambda: self.studio.gradient(layer_id, p0, p1, c0, c1, kind, opacity))

    def create_text_at(self, x: float, y: float) -> str | None:
        if self.studio is None:
            return None
        tools = self.tools
        size, color = tools.text_size.value(), self.colors.color()
        bold, family = tools.text_bold.isChecked(), tools.font.currentFont().family()
        layer_id = self.run(
            "Texte", lambda: self.studio.add_text("TEXTE", x, y, size, color, bold=bold, font_family=family)
        )
        if layer_id:
            self._after_create(layer_id)
            self.right.setCurrentIndex(1)
            self.set_tool("move")
        return layer_id

    def create_shape(self, tool: str, points: list[tuple[float, float]]) -> str | None:
        if self.studio is None:
            return None
        tools = self.tools
        fill = self.colors.color() if tools.shape_fill.isChecked() else None
        stroke = self.colors.secondary() if tools.shape_stroke.isChecked() else None
        extra: dict = {}
        if tool == "rounded_rect":
            extra["radius"] = tools.radius.value()
        if tool == "line" or (tool == "curve" and not tools.shape_closed.isChecked()):
            fill, stroke = None, self.colors.color()
        if tool == "curve":
            extra["closed"] = tools.shape_closed.isChecked()
        width = tools.stroke_width.value() if stroke else 0.0
        layer_id = self.run(
            "Forme", lambda: self.studio.add_shape(tool, points, fill, stroke, width, **extra)
        )
        self._after_create(layer_id)
        return layer_id

    def insert_preset(self, key: str) -> str | None:
        studio = self.studio
        doc = studio.document() if studio else None
        if doc is None:
            return None
        cx, cy = self.view_center()
        r = min(doc.width, doc.height) * 0.06

        def star(i: int) -> tuple[float, float]:
            radius = r if i % 2 == 0 else r * 0.42
            angle = math.radians(-90 + i * 36)
            return (cx + radius * math.cos(angle), cy + radius * math.sin(angle))

        shapes = {
            "rect": ("rect", [(cx - r * 1.5, cy - r), (cx + r * 1.5, cy + r)]),
            "rounded_rect": ("rounded_rect", [(cx - r * 1.5, cy - r), (cx + r * 1.5, cy + r)]),
            "circle": ("circle", [(cx, cy), (cx + r, cy)]),
            "ellipse": ("ellipse", [(cx - r * 1.6, cy - r), (cx + r * 1.6, cy + r)]),
            "chevron": (
                "polygon",
                [
                    (cx - r, cy - r),
                    (cx, cy),
                    (cx - r, cy + r),
                    (cx - r * 0.4, cy + r),
                    (cx + r * 0.6, cy),
                    (cx - r * 0.4, cy - r),
                ],
            ),
            "star": ("polygon", [star(i) for i in range(10)]),
            "arrow": (
                "polygon",
                [
                    (cx - r * 1.5, cy - r * 0.3),
                    (cx + r * 0.3, cy - r * 0.3),
                    (cx + r * 0.3, cy - r * 0.8),
                    (cx + r * 1.5, cy),
                    (cx + r * 0.3, cy + r * 0.8),
                    (cx + r * 0.3, cy + r * 0.3),
                    (cx - r * 1.5, cy + r * 0.3),
                ],
            ),
            "triangle": ("polygon", [(cx, cy - r), (cx + r, cy + r * 0.8), (cx - r, cy + r * 0.8)]),
            "banner": ("rounded_rect", [(cx - r * 3, cy - r * 0.35), (cx + r * 3, cy + r * 0.35)]),
        }
        shape, points = shapes[key]
        extra = {"radius": r * 0.35} if shape == "rounded_rect" else {}
        color = self.colors.color()
        layer_id = self.run("Forme", lambda: studio.add_shape(shape, points, color, **extra))
        self._after_create(layer_id)
        return layer_id

    def view_center(self) -> tuple[float, float]:
        doc = self.studio.document() if self.studio else None
        if doc is None:
            return (0.0, 0.0)
        if self.canvas.isVisible() and self.canvas.width() > 0:
            x, y = self.canvas.to_tex(QPointF(self.canvas.width() / 2, self.canvas.height() / 2))
            if 0 <= x < doc.width and 0 <= y < doc.height:
                return (x, y)
        return (doc.width / 2, doc.height / 2)

    def apply_paint_color(self, color: str) -> None:
        """Peinture de carrosserie = couleur du matériau ciblé (distincte de la texture de livrée)."""
        session = self.controller.session
        doc = self.studio.document() if self.studio else None
        if session is None or doc is None:
            return
        r, g, b, _a = rgba(color)

        def action() -> None:
            session.stack.begin("Peinture de carrosserie")
            for material_id in doc.targets:
                session.set_material_properties(material_id, {"base_color": (r / 255, g / 255, b / 255, 1.0)})
            session.stack.commit()

        self.run("Peinture de carrosserie", action)

    # --- Peinture 3D (gestionnaire du viewport) -------------------------------------------------
    def begin(self, x: float, y: float, pressure: float) -> bool:
        studio = self.studio
        if studio is None or studio.document() is None or self.tool == "move":
            return False
        origin, direction = self.viewport.screen_ray(x, y)
        try:
            surface = studio.surface()
        except EXPECTED:
            return False
        hit = surface.raycast(origin, direction)
        if hit is None:
            return False  # hors carrosserie : orbite habituelle
        if self.tool in ("brush", "eraser"):
            if not self.begin_stroke(None, None, pressure, mode="3d"):
                return False
            studio.stroke_3d(origin, direction, pressure)
            self.texture_changed()
            return True
        px, py = surface.pixel_of(hit.tri, hit.bary)
        if self.tool == "pipette":
            color = self.run("Pipette", lambda: studio.pick_color(px, py))
            if color:
                self.colors.set_color(color, record=True)
            return True
        if self.tool == "fill":
            self.fill_at(px, py)
            return True
        if self.tool == "text":
            placement = surface.placement(hit.point, hit.normal)
            layer_id = self.create_text_at(px, py)
            if layer_id and placement is not None:
                self.run(
                    "Texte",
                    lambda: studio.update_params(
                        layer_id,
                        "Orientation",
                        rotation=placement.rotation,
                        flip_v=placement.flip,
                        scale_y=placement.stretch,
                    ),
                )
            return True
        return False

    def move(self, x: float, y: float, pressure: float) -> None:
        if self.studio is not None and self.studio.stroking:
            origin, direction = self.viewport.screen_ray(x, y)
            self.studio.stroke_3d(origin, direction, pressure)
            self.canvas.texture_changed()

    def end(self) -> None:
        self.end_stroke()

    def hover(self, x: float, y: float) -> None:
        if self.tool not in ("brush", "eraser") or self.studio is None or self.studio.document() is None:
            if self._hover is not None:
                self._hover = None
                self.viewport.update()
            return
        try:
            surface = self.studio.surface()
        except EXPECTED:
            return
        origin, direction = self.viewport.screen_ray(x, y)
        hit = surface.raycast(origin, direction)
        radius = self.studio.brush_radius_m(self.tools.size.value())
        self._hover = None if hit is None else (hit.point, hit.normal, radius)
        self.viewport.update()

    def _brush_overlay(self) -> list[Overlay]:
        """Cercle du pinceau 3D sur la carrosserie (orienté selon la normale)."""
        if self._hover is None:
            return []
        point, normal, radius = self._hover
        helper = np.array([0.0, 1.0, 0.0]) if abs(normal[1]) < 0.9 else np.array([1.0, 0.0, 0.0])
        u = np.cross(normal, helper)
        u /= max(np.linalg.norm(u), 1e-9)
        v = np.cross(normal, u)
        angles = np.linspace(0, 2 * math.pi, 49)
        ring = point + normal * 0.003 + (np.outer(np.cos(angles), u) + np.outer(np.sin(angles), v)) * radius
        lines = []
        for a, b in zip(ring[:-1], ring[1:], strict=True):
            lines += [(*a, 0.95, 0.96, 0.99, 0.95), (*b, 0.95, 0.96, 0.99, 0.95)]
        return [Overlay(lines=np.asarray(lines, np.float32))]

    # --- Document ----------------------------------------------------------------------------------
    def create_document_dialog(self) -> None:
        if self.studio is None:
            self.controller.notify.emit("Livrée", "Ouvrez d'abord un projet avec un véhicule.", "info")
            return
        dialog = NewDocumentDialog(self.studio, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        targets = dialog.targets()
        if self.studio.nodes_without_uv(targets) and not self.project_uvs(True, targets):
            return
        self.create_document(
            targets,
            dialog.size.currentData() or None,
            dialog.template.currentData() or None,
            dialog.unit.text().strip(),
            dialog.name.text().strip() or "Livrée 1",
        )

    def create_document(
        self,
        targets: list[str] | None = None,
        size: int | None = None,
        template: str | None = None,
        unit: str = "",
        name: str = "Livrée 1",
    ):  # type: ignore[no-untyped-def]
        if self.studio is None:
            return None
        self.ensure_logos()
        doc = self.run(
            "Nouveau document", lambda: self.studio.create_document(targets, size, None, name, template, unit)
        )
        if doc is not None:
            self.current_layer_id = None
            self.refresh()
            QTimer.singleShot(0, self.canvas.fit)
        return doc

    def project_uvs(self, confirm: bool = True, materials: list[str] | None = None) -> bool:
        studio = self.studio
        if studio is None:
            return False
        nodes = studio.nodes_without_uv(materials)
        if not nodes:
            self.controller.notify.emit("UV", "Aucun maillage ciblé sans UV.", "info")
            return False
        if confirm:
            answer = QMessageBox.question(
                self,
                "Projection UV",
                f"{len(nodes)} maillage(s) n'ont pas d'UV. Créer un dépliage par projection « boîte » ?\n"
                "Les UV existantes des autres maillages ne sont pas modifiées ; l'opération est annulable.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        return bool(self.run("Projection UV", lambda: studio.project_missing_uvs(nodes)))

    def unwrap_with_blender(self, confirm: bool = True) -> bool:
        """Nouveau dépliage des maillages ciblés par Blender (sur confirmation, en arrière-plan)."""
        from lsfcars.editor.blender_ops import smart_unwrap
        from lsfcars.editor.operations import VehicleEditor

        studio, session = self.studio, self.controller.session
        doc = studio.document() if studio else None
        if studio is None or session is None:
            return False
        targets = set(doc.targets) if doc else {c["id"] for c in studio.candidate_materials()[:1]}
        nodes = [n for n in session.scene.mesh_nodes() if n.material_id in targets]
        if not nodes:
            return False
        if confirm:
            answer = QMessageBox.question(
                self,
                "Dépliage Blender",
                f"Remplacer les UV de {len(nodes)} maillage(s) par un dépliage automatique Blender ?\n"
                "Les calques peints suivent les anciennes UV : à faire avant de peindre. Annulable.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        meshes = {n.id: session.geometry_for(n) for n in nodes}

        def job(progress, cancelled):  # type: ignore[no-untyped-def]
            results = {}
            for index, (node_id, mesh) in enumerate(meshes.items()):
                if cancelled():
                    break
                progress(index / max(len(meshes), 1), f"Dépliage {index + 1}/{len(meshes)}")
                results[node_id] = smart_unwrap(mesh)
            return results

        def done(results) -> None:  # type: ignore[no-untyped-def]
            editor = VehicleEditor(session)
            session.stack.begin("Dépliage UV (Blender)")
            for node_id, result in results.items():
                session.stack.push(editor.geometry_command(node_id, result.mesh, "Dépliage UV (Blender)"))
            session.stack.commit()
            self.progress.finish(f"{len(results)} maillage(s) dépliés par Blender.")
            self.schedule_refresh()

        self._start_worker("Dépliage UV (Blender)", job, done)
        return True

    def _start_worker(self, title: str, job, done) -> None:  # type: ignore[no-untyped-def]
        from lsfcars.ui.import_studio.workers import TaskWorker

        worker = TaskWorker(title, job, self)
        worker.progress.connect(self.progress.update_progress)
        worker.succeeded.connect(done)

        def failed(message: str) -> None:
            self.progress.finish(message)
            self.controller.notify.emit(title, message, "warning")

        worker.failed.connect(failed)
        worker.cancelled.connect(lambda: self.progress.finish("Annulé."))
        self.progress.start(title, worker.cancel)
        self.bottom.setCurrentWidget(self.progress)
        self._worker = worker
        worker.start()

    # --- Export -------------------------------------------------------------------------------------
    def export_now(self, folder: str, options: export.ExportOptions, scope: str = "active") -> list:
        """Export synchrone (tests, scripts) : même résultat que l'export asynchrone."""
        studio = self.studio
        if studio is None:
            return []
        if scope == "ytd":
            result = self.run("Préparation YTD", lambda: studio.prepare_ytd(folder, options))
            reports = result[1] if result else []
        elif scope == "all":
            reports = self.run("Export", lambda: studio.export_all(folder, options)) or []
        else:
            doc = studio.document()
            report = self.run("Export", lambda: studio.export(f"{folder}/{doc.texture_name}", options))
            reports = [report] if report else []
        self.export_panel.show_reports(reports)
        return reports

    def export_async(self, folder: str, options: export.ExportOptions, scope: str = "active") -> None:
        """Compositions calculées ici ; encodage et écriture (DDS, mipmaps) en arrière-plan."""
        studio = self.studio
        doc = studio.document() if studio else None
        if doc is None:
            return
        variants = doc.variants if scope in ("all", "ytd") else [doc.active_variant]
        try:
            arrays = {v.id: studio.composite(v.id) for v in variants}
            coverage = (
                studio.surface(doc).maps().coverage if options.padding and doc.mode == "texture" else None
            )
        except EXPECTED as exc:
            self.controller.notify.emit("Export", str(exc), "warning")
            return
        project = self.controller.session.project.name if self.controller.session else "livree"
        dictionary = "".join(c if c.isalnum() else "_" for c in project.lower()).strip("_") or "livree"

        def job(progress, cancelled):  # type: ignore[no-untyped-def]
            if scope == "ytd":
                base = doc.texture_name.rsplit("_sign_", 1)[0]
                textures = {f"{base}_sign_{i}": arrays[v.id] for i, v in enumerate(variants, start=1)}
                return export.prepare_ytd(folder, dictionary, textures, options, coverage)[1]
            reports = []
            for index, variant in enumerate(variants):
                if cancelled():
                    break
                progress(index / max(len(variants), 1), f"Export de « {variant.name} »")
                name = f"{doc.texture_name}_{variant.name}" if scope == "all" else doc.texture_name
                safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in name)
                reports.append(
                    export.export_texture(arrays[variant.id], f"{folder}/{safe}", options, coverage)
                )
            return reports

        def done(reports) -> None:  # type: ignore[no-untyped-def]
            for report in reports:
                studio.check_provenance(doc, report)
            self.export_panel.show_reports(reports)
            message = f"{len(reports)} texture(s) exportée(s) dans {folder}"
            self.progress.finish(message)
            self.controller.notify.emit(
                "Export", message, "success" if all(r.verified for r in reports) else "warning"
            )

        self._start_worker("Export des textures", job, done)

    # --- Disposition -------------------------------------------------------------------------------
    def save_layout(self) -> None:
        self.settings.set_value("layout/livery_h", self.h_split.saveState())
        self.settings.set_value("layout/livery_v", self.v_split.saveState())
        self.settings.set_value("layout/livery_views", self.views.saveState())

    def restore_layout(self) -> None:
        for key, splitter in (
            ("layout/livery_h", self.h_split),
            ("layout/livery_v", self.v_split),
            ("layout/livery_views", self.views),
        ):
            state = self.settings.value(key)
            if state is not None:
                splitter.restoreState(state)
