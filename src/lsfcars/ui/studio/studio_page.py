"""Page Studio 3D : explorateur | viewport | propriétés, panneau inférieur redimensionnable."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from lsfcars.ui.settings import AppSettings
from lsfcars.ui.studio.controller import StudioController
from lsfcars.ui.studio.panels import BottomPanel, PropertiesPanel, SceneExplorer
from lsfcars.ui.viewport import Viewport3D


class StudioPage(QWidget):
    def __init__(
        self, controller: StudioController, settings: AppSettings, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.settings = settings
        self.viewport = Viewport3D()
        self.explorer = SceneExplorer(controller)
        self.properties = PropertiesPanel(controller)
        self.bottom = BottomPanel(controller, self.viewport)
        for panel in (self.explorer, self.properties, self.bottom):
            panel.setObjectName("LSStudioPanel")
            panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            panel.setStyleSheet("QWidget#LSStudioPanel { background: #11151a; }")
        self.explorer.setMinimumWidth(220)
        self.properties.setMinimumWidth(360)

        self.h_split = QSplitter(Qt.Orientation.Horizontal)
        self.h_split.setHandleWidth(1)
        self.h_split.addWidget(self.explorer)
        self.h_split.addWidget(self.viewport)
        self.h_split.addWidget(self.properties)
        self.h_split.setStretchFactor(1, 1)
        self.h_split.setSizes([270, 900, 350])
        self.v_split = QSplitter(Qt.Orientation.Vertical)
        self.v_split.setHandleWidth(1)
        self.v_split.addWidget(self.h_split)
        self.v_split.addWidget(self.bottom)
        self.v_split.setStretchFactor(0, 1)
        self.v_split.setSizes([700, 190])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.v_split)
        self.restore_layout()

        self.viewport.selection_requested.connect(controller.select)
        self.viewport.transforms_edited.connect(controller.apply_transforms)
        self.viewport.frame_requested.connect(self.frame_selection)
        controller.session_changed.connect(self._on_session)
        controller.scene_changed.connect(lambda _k: self.viewport.refresh())
        controller.selection_changed.connect(self.viewport.refresh)

    def _on_session(self) -> None:
        session = self.controller.session
        self.viewport.set_session(session)
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

    def save_layout(self) -> None:
        self.settings.set_value("layout/studio_h", self.h_split.saveState())
        self.settings.set_value("layout/studio_v", self.v_split.saveState())

    def restore_layout(self) -> None:
        for key, splitter in (("layout/studio_h", self.h_split), ("layout/studio_v", self.v_split)):
            state = self.settings.value(key)
            if state is not None:
                splitter.restoreState(state)

    def reset_layout(self) -> None:
        self.h_split.setSizes([270, max(self.width() - 640, 400), 350])
        self.v_split.setSizes([max(self.height() - 200, 300), 190])
