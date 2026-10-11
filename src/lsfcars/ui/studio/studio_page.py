"""Vehicle Editor : page principale d'édition de véhicule (v0.4).

Disposition : outils (scène, bibliothèque, outils de modélisation) | viewport | propriétés,
géométrie, ancrages, atelier — en bas : statistiques, historique, compatibilité FiveM, journal.
Tous les panneaux sont redimensionnables, rétractables, et leur disposition est mémorisée.

Espaces de travail : Vehicle Editor, Bodywork Studio, Wheel Editor, Interior Studio.
Modes : Objet, Édition (sommets / arêtes / faces), Composant.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from lsfcars.editor import edit_state as modes
from lsfcars.ui.design.components import LSButton, LSIconButton, LSTabs, tooltip
from lsfcars.ui.editor.library_panel import LibraryPanel, ReplaceDialog
from lsfcars.ui.editor.panels import (
    AnchorsPanel,
    BodyworkPanel,
    CompatPanel,
    GeometryPanel,
    HistoryPanel,
    InteriorPanel,
    ModelingTools,
    WheelPanel,
    scroll,
)
from lsfcars.ui.settings import AppSettings
from lsfcars.ui.studio.controller import StudioController
from lsfcars.ui.studio.panels import BottomPanel, PropertiesPanel, SceneExplorer
from lsfcars.ui.viewport import Viewport3D

WORKSPACES = (
    ("editor", "Vehicle Editor", "car", "Modélisation générale : objets, maillages, composants"),
    ("bodywork", "Bodywork Studio", "shapes", "Carrosserie : panneaux, proportions, pièces, symétrie"),
    ("wheels", "Wheel Editor", "orbit", "Roues : positions, alignement, jantes, pivots"),
    ("interior", "Interior Studio", "layers", "Habitacle : isolation, caméra intérieure, configurations"),
)
WORKSHOP_TABS = {"bodywork": (0, "Carrosserie"), "wheels": (1, "Roues"), "interior": (2, "Habitacle")}
MODE_ICONS = {modes.OBJECT: "mouse-pointer-2", modes.EDIT: "pencil", modes.COMPONENT: "blocks"}
SHORT_TITLES = {"editor": "Éditeur", "bodywork": "Carrosserie", "wheels": "Roues", "interior": "Habitacle"}


class _HeaderBar(QFrame):
    """Barre d'en-tête qui signale sa largeur pour adapter ses libellés."""

    def __init__(self, on_resize) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self._on_resize = on_resize

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        super().resizeEvent(event)
        self._on_resize(self.width())


class StudioPage(QWidget):
    """Page « Vehicle Editor » (nom historique de la classe conservé pour la compatibilité)."""

    def __init__(
        self, controller: StudioController, settings: AppSettings, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.settings = settings
        self.workspace = "editor"
        self.replace_dialog: ReplaceDialog | None = None
        self.viewport = Viewport3D()
        self.viewport.set_edit_state(controller.edit)

        # Gauche : scène, bibliothèque, outils
        self.explorer = SceneExplorer(controller)
        self.library = LibraryPanel(controller)
        self.tools = ModelingTools(controller, self.viewport, lambda: self.open_replace())
        self.left = LSTabs()
        self.left.addTab(self.explorer, "Scène")
        self.left.addTab(self.library, "Bibliothèque")
        self.left.addTab(self.tools, "Outils")

        # Droite : propriétés, géométrie, ancrages, atelier de l'espace de travail
        self.properties = PropertiesPanel(controller)
        self.geometry = GeometryPanel(controller)
        self.anchors = AnchorsPanel(controller, self.viewport)
        self.bodywork = BodyworkPanel(controller, self.library, self.viewport)
        self.wheels = WheelPanel(controller, self.viewport, self.open_replace)
        self.interior = InteriorPanel(controller, self.viewport, self.library)
        self.workshop = QStackedWidget()
        for panel in (self.bodywork, self.wheels, self.interior):
            self.workshop.addWidget(scroll(panel))
        self.right = LSTabs()
        self.right.addTab(self.properties, "Propriétés")
        self.right.addTab(scroll(self.geometry), "Géométrie")
        self.right.addTab(scroll(self.anchors), "Ancrages")

        # Bas : statistiques, historique, compatibilité FiveM, progression, journal
        self.bottom = BottomPanel(controller, self.viewport)
        self.history = HistoryPanel(controller)
        self.compat = CompatPanel(controller)
        self.bottom.insertTab(1, self.history, "Historique")
        self.bottom.insertTab(2, self.compat, "Compatibilité FiveM")

        for panel in (self.left, self.right, self.bottom):
            panel.setObjectName("LSStudioPanel")
            panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.left.setMinimumWidth(330)
        self.right.setMinimumWidth(360)

        self.h_split = QSplitter(Qt.Orientation.Horizontal)
        self.h_split.setHandleWidth(1)
        self.h_split.addWidget(self.left)
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        center_layout.addWidget(self._header())
        center_layout.addWidget(self.viewport, 1)
        self.h_split.addWidget(center)
        self.h_split.addWidget(self.right)
        self.h_split.setStretchFactor(1, 1)
        self.h_split.setSizes([360, 840, 390])
        self.v_split = QSplitter(Qt.Orientation.Vertical)
        self.v_split.setHandleWidth(1)
        self.v_split.addWidget(self.h_split)
        self.v_split.addWidget(self.bottom)
        self.v_split.setStretchFactor(0, 1)
        self.v_split.setSizes([700, 200])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.v_split)
        self.restore_layout()

        self.viewport.selection_requested.connect(controller.select)
        self.viewport.transforms_edited.connect(controller.apply_transforms)
        self.viewport.edit_transform.connect(controller.apply_edit_transform)
        self.viewport.edit_mode_toggled.connect(controller.toggle_edit_mode)
        self.viewport.frame_requested.connect(self.frame_selection)
        self.library.replace_requested.connect(lambda component_id: self.open_replace(None, component_id))
        controller.session_changed.connect(self._on_session)
        controller.scene_changed.connect(lambda _k: self.viewport.refresh())
        controller.selection_changed.connect(self.viewport.refresh)
        controller.edit_changed.connect(self._sync_mode)
        self._sync_mode()

    # --- Barre d'en-tête : espaces de travail, modes, panneaux --------------------------------
    def _header(self) -> QFrame:
        bar = _HeaderBar(self._adapt_header)
        bar.setObjectName("LSStudioPanel")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(4)
        self.workspace_group = QButtonGroup(self)
        self.workspace_buttons: dict[str, LSButton] = {}
        for key, title, icon, tip in WORKSPACES:
            widget = LSButton(title, "ghost", icon, True)
            widget.setCheckable(True)
            widget.setProperty("chip", True)
            tooltip(widget, tip)
            widget.clicked.connect(lambda _=False, k=key: self.set_workspace(k))
            self.workspace_group.addButton(widget)
            self.workspace_buttons[key] = widget
            row.addWidget(widget)
        row.addSpacing(14)
        self.mode_group = QButtonGroup(self)
        self.mode_buttons: dict[str, LSButton] = {}
        for mode, title in modes.MODE_LABELS.items():
            widget = LSButton(title, "ghost", MODE_ICONS[mode], True)
            widget.setCheckable(True)
            widget.setProperty("chip", True)
            tooltip(widget, modes.MODE_HINTS[mode], "Tab" if mode == modes.EDIT else None)
            widget.clicked.connect(lambda _=False, m=mode: self.set_mode(m))
            self.mode_group.addButton(widget)
            self.mode_buttons[mode] = widget
            row.addWidget(widget)
        row.addStretch(1)
        self.panel_buttons: dict[str, LSIconButton] = {}
        for key, icon, tip in (
            ("left", "panel-left-close", "Afficher / masquer les outils (gauche)"),
            ("bottom", "layout-grid", "Afficher / masquer le panneau inférieur"),
            ("right", "sliders-horizontal", "Afficher / masquer les propriétés (droite)"),
        ):
            widget = LSIconButton(icon, tip, checkable=True, size=15)
            widget.setChecked(True)
            widget.toggled.connect(lambda visible, k=key: self.set_panel_visible(k, visible))
            self.panel_buttons[key] = widget
            row.addWidget(widget)
        self.workspace_buttons["editor"].setChecked(True)
        return bar

    def _adapt_header(self, width: int) -> None:
        """En-tête adaptatif : libellés complets, courts, puis icônes seules (infobulles conservées)."""
        level = "full" if width >= 1180 else ("short" if width >= 900 else "icons")
        if getattr(self, "_header_level", None) == level:
            return
        self._header_level = level
        for key, title, *_ in WORKSPACES:
            text = {"full": title, "short": SHORT_TITLES[key], "icons": ""}[level]
            self.workspace_buttons[key].setText(text)
        for mode, title in modes.MODE_LABELS.items():
            self.mode_buttons[mode].setText("" if level == "icons" and width < 640 else title)

    def set_workspace(self, key: str) -> None:
        """Change d'espace de travail : l'onglet d'atelier montre l'outil dédié."""
        self.workspace = key
        self.workspace_buttons[key].setChecked(True)
        index = self.right.indexOf(self.workshop)
        if key not in WORKSHOP_TABS:
            if index >= 0:
                self.right.removeTab(index)
            return
        page, title = WORKSHOP_TABS[key]
        self.workshop.setCurrentIndex(page)
        if index < 0:
            index = self.right.insertTab(0, self.workshop, title)
        else:
            self.right.setTabText(index, title)
        self.right.setCurrentIndex(index)
        (self.bodywork, self.wheels, self.interior)[page].refresh()

    def set_mode(self, mode: str) -> None:
        self.controller.set_mode(mode)
        if self.controller.edit.mode != modes.OBJECT:
            self.left.setCurrentWidget(self.tools)
        self._sync_mode()

    def _sync_mode(self) -> None:
        state = self.controller.edit
        self.mode_buttons[state.mode].setChecked(True)
        self.viewport.refresh()

    def set_panel_visible(self, key: str, visible: bool) -> None:
        widget = {"left": self.left, "right": self.right, "bottom": self.bottom}[key]
        widget.setVisible(visible)
        if self.panel_buttons[key].isChecked() != visible:
            self.panel_buttons[key].setChecked(visible)

    # --- Remplacement -----------------------------------------------------------------
    def open_replace(
        self, target_id: str | None = None, component_id: str | None = None, modal: bool = True
    ) -> bool:
        session = self.controller.session
        if session is None:
            return False
        target_id = target_id or session.selection.active
        if target_id is None or target_id not in session.scene:
            self.controller.notify.emit(
                "Remplacer un composant", "Sélectionnez d'abord la pièce à remplacer.", "info"
            )
            return False
        self.replace_dialog = ReplaceDialog(
            self.controller, self.library.library, target_id, component_id, self
        )
        if not modal:
            self.replace_dialog.show()
            return True
        return bool(self.replace_dialog.exec())

    # --- Session et caméra -------------------------------------------------------------------
    def _on_session(self) -> None:
        session = self.controller.session
        self.viewport.set_session(session)
        self.viewport.set_isolation(None)
        self.viewport.set_hidden(set())
        self.viewport.set_display_matrices({})
        if session is None:
            return
        if session.project.camera:
            self.viewport.camera.apply_state(session.project.camera)
            self.viewport._sync_buttons()
        else:
            self.viewport.frame_bounds(session.world_bounds())

    def frame_selection(self) -> None:
        session = self.controller.session
        if session is None:
            self.viewport.frame_bounds(None)
            return
        ids = session.selection.ids
        bounds = session.world_bounds(ids, only_visible=False) if ids else None
        self.viewport.frame_bounds(bounds or session.world_bounds())

    # --- Disposition ----------------------------------------------------------------------
    def save_layout(self) -> None:
        self.settings.set_value("layout/studio_h", self.h_split.saveState())
        self.settings.set_value("layout/studio_v", self.v_split.saveState())
        panels = (("left", self.left), ("right", self.right), ("bottom", self.bottom))
        self.settings.set_value("layout/editor_hidden", ",".join(k for k, w in panels if w.isHidden()))
        self.settings.set_value("layout/editor_workspace", self.workspace)

    def restore_layout(self) -> None:
        for key, splitter in (("layout/studio_h", self.h_split), ("layout/studio_v", self.v_split)):
            state = self.settings.value(key)
            if state is not None:
                splitter.restoreState(state)
        hidden = str(self.settings.value("layout/editor_hidden") or "").split(",")
        for key in ("left", "right", "bottom"):
            self.set_panel_visible(key, key not in hidden)
        workspace = str(self.settings.value("layout/editor_workspace") or "editor")
        if workspace in {k for k, *_ in WORKSPACES}:
            self.set_workspace(workspace)

    def reset_layout(self) -> None:
        for key in ("left", "right", "bottom"):
            self.set_panel_visible(key, True)
        self.h_split.setSizes([360, max(self.width() - 750, 400), 390])
        self.v_split.setSizes([max(self.height() - 210, 300), 200])


VehicleEditorPage = StudioPage
