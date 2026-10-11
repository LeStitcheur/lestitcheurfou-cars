"""Emergency Vehicle Studio : page principale.

Disposition : service, équipements, composants | viewport (placement, aperçu lumineux) |
propriétés, éclairage, configurations, export — en bas : timeline lumineuse, diagnostics,
historique. La session est partagée avec le Vehicle Editor : passer d'une page à l'autre ne perd
rien. L'aperçu lumineux est une **simulation** dessinée par-dessus la scène.
"""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QSplitter, QVBoxLayout, QWidget

from lsfcars.core.logging_setup import get_logger
from lsfcars.editor.library import LibraryError
from lsfcars.emergency import model
from lsfcars.emergency.adapters import AdapterError
from lsfcars.emergency.equipment import EquipmentLibrary
from lsfcars.emergency.studio import MAX_PREVIEW_LIGHTS, AddResult, EmergencyStudio
from lsfcars.render.renderer import Overlay
from lsfcars.scene.editmesh import EditError
from lsfcars.ui.design.components import LSBadge, LSButton, LSTabs, label, tooltip
from lsfcars.ui.editor.panels import HistoryPanel, scroll
from lsfcars.ui.emergency.panels import (
    ComponentsPanel,
    ConfigurationPanel,
    DiagnosticsPanel,
    EquipmentPanel,
    EquipmentProperties,
    ExportPanel,
    LightingPanel,
    ServicePanel,
    TimelinePanel,
)
from lsfcars.ui.viewport import Viewport3D

log = get_logger(__name__)
FRAME_MS = 33


class EmergencyPage(QWidget):
    changed = Signal()
    editor_requested = Signal()  # retour au Vehicle Editor (même session)

    def __init__(self, controller, settings, parent: QWidget | None = None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.controller = controller
        self.settings = settings
        self.library: EquipmentLibrary | None = None
        self.studio: EmergencyStudio | None = None
        self._state = None
        self._loader = None
        self.place_component: str | None = None
        self.selected_lights: set[str] = set()
        self.time_ms = 0.0
        self.speed = 1.0
        self.playing = False
        self._last_tick = time.perf_counter()
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.refresh)

        self.viewport = Viewport3D()
        self.viewport.setAcceptDrops(True)
        self.viewport.overlay_providers.append(self.light_overlays)
        self.viewport.click_handler = self._click
        self.viewport.drop_handler = self._drop
        self.viewport.selection_requested.connect(controller.select)
        self.viewport.transforms_edited.connect(controller.apply_transforms)
        self.viewport.frame_requested.connect(self.frame_vehicle)

        self.service_panel = ServicePanel(self)
        self.equipment_panel = EquipmentPanel(self)
        self.components_panel = ComponentsPanel(self)
        self.left = LSTabs()
        self.left.addTab(scroll(self.service_panel), "Service")
        self.left.addTab(self.equipment_panel, "Équipements")
        self.left.addTab(self.components_panel, "Composants")
        self.properties = EquipmentProperties(self)
        self.lighting = LightingPanel(self)
        self.configuration = ConfigurationPanel(self)
        self.export_panel = ExportPanel(self)
        self.right = LSTabs()
        self.right.addTab(scroll(self.properties), "Propriétés")
        self.right.addTab(scroll(self.lighting), "Éclairage")
        self.right.addTab(scroll(self.configuration), "Configurations")
        self.right.addTab(scroll(self.export_panel), "Export")
        self.timeline = TimelinePanel(self)
        self.diagnostics = DiagnosticsPanel(self)
        self.history = HistoryPanel(controller)
        self.bottom = LSTabs()
        self.bottom.addTab(self.timeline, "Timeline lumineuse")
        self.bottom.addTab(self.diagnostics, "Diagnostics")
        self.bottom.addTab(self.history, "Historique")
        for panel in (self.left, self.right, self.bottom):
            panel.setObjectName("LSStudioPanel")
            panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.left.setMinimumWidth(320)
        self.right.setMinimumWidth(360)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        center_layout.addWidget(self._header())
        center_layout.addWidget(self.viewport, 1)
        self.h_split = QSplitter(Qt.Orientation.Horizontal)
        self.h_split.setHandleWidth(1)
        for widget in (self.left, center, self.right):
            self.h_split.addWidget(widget)
        self.h_split.setStretchFactor(1, 1)
        self.h_split.setSizes([350, 850, 390])
        self.v_split = QSplitter(Qt.Orientation.Vertical)
        self.v_split.setHandleWidth(1)
        self.v_split.addWidget(self.h_split)
        self.v_split.addWidget(self.bottom)
        self.v_split.setStretchFactor(0, 1)
        self.v_split.setSizes([620, 300])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.v_split)
        for combo in self.findChildren(QComboBox):  # les libellés longs ne doivent pas élargir les panneaux
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
        self.restore_layout()

        controller.session_changed.connect(self._on_session)
        for signal in (controller.scene_changed, controller.selection_changed, controller.state_changed):
            signal.connect(lambda *_: self.schedule_refresh())
        self._on_session()

    # --- En-tête ------------------------------------------------------------------------
    def _header(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("LSStudioPanel")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(6)
        self.variant_badge = LSBadge("Aucune variante", "neutral")
        row.addWidget(self.variant_badge)
        self.hint = label("", "faint")
        self.hint.setMinimumWidth(40)
        row.addWidget(self.hint, 1)
        self.preview_button = LSButton("Aperçu lumineux", "ghost", "siren", True)
        self.preview_button.setCheckable(True)
        self.preview_button.setProperty("chip", True)
        self.preview_button.clicked.connect(lambda checked: self.set_playing(checked))
        tooltip(self.preview_button, "Simulation des feux dans le viewport (pas un rendu de jeu)")
        row.addWidget(self.preview_button)
        collisions = LSButton("Collisions", "ghost", "scan", True)
        collisions.clicked.connect(self.check_collisions)
        tooltip(collisions, "Contrôle géométrique approximatif (boîtes englobantes)")
        row.addWidget(collisions)
        editor = LSButton("Vehicle Editor", "ghost", "cuboid", True)
        editor.clicked.connect(self.editor_requested)
        tooltip(editor, "Revenir au Vehicle Editor (même projet, rien n'est perdu)")
        row.addWidget(editor)
        return bar

    # --- Session et bibliothèque ---------------------------------------------------------
    def set_library(self, library: EquipmentLibrary) -> None:
        self.library = library
        self._rebuild_studio()

    def ensure_library(self) -> None:
        """Chargement asynchrone : génération des équipements de départ en arrière-plan."""
        if self.library is not None or self._loader is not None:
            return
        library = EquipmentLibrary()
        if len(library.components()) >= len(library.builtin_specs) or library._removed_builtins:
            self.set_library(library)
            return
        from lsfcars.ui.import_studio.workers import TaskWorker

        def job(progress, cancelled):  # type: ignore[no-untyped-def]
            progress(0.1, "Génération des équipements de départ")
            library.ensure_builtins()
            return library

        worker = TaskWorker("Bibliothèque d'équipements", job, self)
        worker.succeeded.connect(self._library_ready)
        worker.failed.connect(
            lambda message: self.controller.notify.emit("Bibliothèque d'équipements", message, "warning")
        )
        self._loader = worker
        self.equipment_panel.refresh()
        worker.start()

    def _library_ready(self, library: EquipmentLibrary) -> None:
        worker, self._loader = self._loader, None
        if worker is not None:
            worker.wait(2000)
            worker.deleteLater()
        self.set_library(library)

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        super().showEvent(event)
        self.ensure_library()
        self.schedule_refresh()

    def _rebuild_studio(self) -> None:
        session = self.controller.session
        self.studio = (
            EmergencyStudio(session, self.library)
            if session is not None and self.library is not None
            else None
        )
        self.refresh()

    def _on_session(self) -> None:
        session = self.controller.session
        self.viewport.set_session(session)
        self.selected_lights = set()
        if session is not None:
            self.frame_vehicle()
        self._rebuild_studio()

    def frame_vehicle(self) -> None:
        session = self.controller.session
        self.viewport.frame_bounds(session.world_bounds() if session else None)

    def active_variant(self):  # type: ignore[no-untyped-def]
        return self._state.active_variant if self._state is not None else None

    # --- Opérations ---------------------------------------------------------------------
    def run(self, title: str, action):  # type: ignore[no-untyped-def]
        """Exécute une opération ; les erreurs prévues deviennent des notifications."""
        try:
            result = action()
        except (EditError, LibraryError, AdapterError, ValueError, KeyError) as exc:
            log.warning("%s : %s", title, exc)
            self.controller.notify.emit(title, str(exc), "warning")
            return None
        self.schedule_refresh()
        return result

    def report(self, result: AddResult | None) -> None:
        for warning in result.warnings if result is not None else []:
            self.controller.notify.emit("Équipement", warning, "warning")

    def _surface(self, x: float, y: float):  # type: ignore[no-untyped-def]
        if self.studio is None:
            return None
        origin, direction = self.viewport.screen_ray(x, y)
        return self.studio.surface_hit(origin, direction)

    def place_at(self, component_id: str, x: float, y: float) -> AddResult | None:
        """Pose un équipement à l'endroit visé sur la carrosserie (clic ou dépôt)."""
        hit = self._surface(x, y)
        if hit is None:
            self.controller.notify.emit("Placement", "Visez la carrosserie du véhicule.", "info")
            return None
        result = self.run(
            "Placement", lambda: self.studio.add_equipment(component_id, point=hit[0], normal=hit[1])
        )
        self.report(result)
        return result

    def _click(self, x: float, y: float) -> bool:
        if self.place_component is None or self.studio is None:
            return False
        self.place_at(self.place_component, x, y)
        return True

    def _drop(self, component_id: str, x: float, y: float) -> bool:
        return self.studio is not None and self.place_at(component_id, x, y) is not None

    def check_collisions(self) -> list[str]:
        if self.studio is None or self.active_variant() is None:
            return []
        issues = self.run("Collisions", self.studio.collisions) or []
        message = "\n".join(issues) if issues else "Aucun chevauchement détecté (contrôle approximatif)."
        self.controller.notify.emit("Collisions", message, "warning" if issues else "success")
        return issues

    # --- Aperçu lumineux ------------------------------------------------------------------
    def set_playing(self, playing: bool) -> None:
        self.playing = bool(playing)
        self.preview_button.setChecked(self.playing)
        self.timeline.play_button.setChecked(self.playing)
        self._last_tick = time.perf_counter()
        if self.playing:
            self._timer.start()
        else:
            self._timer.stop()
        self.viewport.update()

    def advance(self, delta_ms: float) -> None:
        """Avance l'horloge de prévisualisation (lecture, tests)."""
        self.time_ms += delta_ms * self.speed
        variant = self.active_variant()
        pattern = variant.pattern(variant.active_pattern) if variant else None
        if pattern is not None:
            self.timeline.mark(pattern.frame_index_at(self.time_ms))
        self.viewport.update()

    def _tick(self) -> None:
        now = time.perf_counter()
        self.advance((now - self._last_tick) * 1000.0)
        self._last_tick = now

    def light_overlays(self) -> list[Overlay]:
        """Feux de la variante active : allumés selon le motif (lecture) ou en veille."""
        studio, variant = self.studio, self.active_variant()
        if studio is None or variant is None or not variant.lights:
            return []
        on = studio.lights_on(variant, self.time_ms) if self.playing else set()
        lit, glow, idle, cones = [], [], [], []
        for light in [x for x in variant.lights if x.visible][:MAX_PREVIEW_LIGHTS]:
            world = studio.light_world(light)
            if world is None:
                continue
            position, direction = world
            r, g, b = light.rgb
            if light.id in on:
                lit.append((*position, r, g, b, 1.0))
                glow.append((*position, r, g, b, 0.28 * min(light.intensity, 3.0)))
            else:
                idle.append((*position, r * 0.6, g * 0.6, b * 0.6, 0.55 if light.enabled else 0.2))
            if light.id in self.selected_lights:  # cône d'éclairage simulé
                length = min(light.range * 0.06, 1.5)
                half = np.radians(min(light.angle, 170.0) / 2)
                side = np.cross(direction, [0.0, 1.0, 0.0])
                norm = np.linalg.norm(side)
                side = side / norm if norm > 1e-6 else np.array([1.0, 0.0, 0.0])
                for sign in (-1.0, 1.0):
                    edge = direction * np.cos(half) + side * np.sin(half) * sign
                    cones += [(*position, r, g, b, 0.9), (*(position + edge * length), r, g, b, 0.0)]
                cones += [(*position, r, g, b, 1.0), (*(position + direction * length), r, g, b, 0.3)]
        overlays = []
        if idle:
            overlays.append(Overlay(points=np.asarray(idle, np.float32), point_size=6.0, xray=True))
        if glow:
            overlays.append(
                Overlay(points=np.asarray(glow, np.float32), point_size=38.0, xray=True, point_style="glow")
            )
        if lit:
            overlays.append(Overlay(points=np.asarray(lit, np.float32), point_size=14.0, xray=True))
        if cones:
            overlays.append(Overlay(lines=np.asarray(cones, np.float32), xray=True))
        return overlays

    # --- Rafraîchissement ------------------------------------------------------------------
    def schedule_refresh(self) -> None:
        self._refresh_timer.start(0)

    def refresh(self) -> None:
        self._state = self.studio.state() if self.studio is not None else None
        variant = self.active_variant()
        if variant is None:
            self.variant_badge.setText("Aucune variante")
            self.hint.setText("Onglet Service : créez une variante (le véhicule de base n'est pas modifié).")
        else:
            self.variant_badge.setText(f"{variant.name} · {model.service(variant.service).label}")
            profile = self._state.profile(variant.profile)
            placing = " · clic sur la carrosserie : pose" if self.place_component else ""
            self.hint.setText(f"Profil {profile.label} · {len(variant.lights)} feu(x){placing}")
        for panel in (
            self.service_panel,
            self.equipment_panel,
            self.components_panel,
            self.properties,
            self.lighting,
            self.configuration,
            self.timeline,
            self.export_panel,
        ):
            panel.refresh()
        self.viewport.refresh()
        self.changed.emit()

    # --- Disposition ------------------------------------------------------------------------
    def save_layout(self) -> None:
        self.settings.set_value("layout/emergency_h", self.h_split.saveState())
        self.settings.set_value("layout/emergency_v", self.v_split.saveState())

    def restore_layout(self) -> None:
        for key, splitter in (("layout/emergency_h", self.h_split), ("layout/emergency_v", self.v_split)):
            state = self.settings.value(key)
            if state is not None:
                splitter.restoreState(state)
