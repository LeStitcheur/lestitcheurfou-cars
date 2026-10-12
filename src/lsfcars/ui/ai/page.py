"""AI Vehicle Creator : page principale.

Disposition : références, analyse, Lore Friendly | vue 3D et tableau des références (seul ou
partagé) | génération, maillage, textures, historique — en bas : tâches, journal, matériel.

Les opérations longues (détection, analyse, génération, textures, appels cloud) passent par la
file de tâches du gestionnaire : l'interface reste utilisable, chaque tâche est annulable et
son résultat est appliqué au projet dans le fil principal (historique annulable). Aucun
transfert cloud ni opération facturée sans confirmation explicite.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QElapsedTimer, QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QSplitter, QVBoxLayout, QWidget

from lsfcars.ai import http as ai_http
from lsfcars.ai import mesh_assist
from lsfcars.ai.creator import AIVehicleCreator
from lsfcars.ai.engines.base import Capability, GenerationRequest
from lsfcars.ai.errors import AIError
from lsfcars.ai.manager import AIEngineManager, Job
from lsfcars.core.logging_setup import get_logger
from lsfcars.core.paths import app_data_dir
from lsfcars.scene.editmesh import EditError
from lsfcars.ui.ai.engines_dialog import EnginesDialog
from lsfcars.ui.ai.panels import (
    AnalysisPanel,
    GenerationPanel,
    GenerationsPanel,
    HardwarePanel,
    JobsPanel,
    LogPanel,
    LorePanel,
    MeshPanel,
    ReferencesPanel,
    TexturePanel,
)
from lsfcars.ui.ai.widgets import JobBridge, ReferenceBoard
from lsfcars.ui.design.components import LSBadge, LSButton, LSModal, LSTabs, label, tooltip
from lsfcars.ui.editor.panels import scroll
from lsfcars.ui.viewport import Viewport3D

log = get_logger(__name__)
EXPECTED = (AIError, EditError, OSError, ValueError)


class AIVehicleCreatorPage(QWidget):
    editor_requested = Signal()
    livery_requested = Signal()

    def __init__(
        self, controller, settings, manager: AIEngineManager | None = None, parent: QWidget | None = None
    ) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.controller = controller
        self.settings = settings
        self.manager = manager or AIEngineManager(app_data_dir())
        self.creator: AIVehicleCreator | None = None
        self.texture_outcome = None
        self.generation_job: Job | None = None
        self.last_root: str | None = None
        self.detected = False
        self.view_mode = "split"
        self._callbacks: dict[str, tuple] = {}
        self.bridge = JobBridge(self)
        self.bridge.updated.connect(self._on_job)
        self.manager.queue.listeners.append(self.bridge)
        self.log_bridge = JobBridge(self)
        self.log_bridge.updated.connect(lambda entry: self.log_panel.append(self._format_request(entry)))
        ai_http.REQUEST_LOG.listeners.append(self._request_listener)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.refresh)
        self._jobs_timer = QTimer(self)
        self._jobs_timer.setSingleShot(True)
        self._jobs_timer.setInterval(120)
        self._jobs_timer.timeout.connect(lambda: self.jobs_panel.refresh())

        self.viewport = Viewport3D()
        self.viewport.frame_requested.connect(self.frame_model)
        self.board = ReferenceBoard()
        self.references = ReferencesPanel(self)
        self.board.rect_drawn.connect(self.references.rect_drawn)
        self.analysis = AnalysisPanel(self)
        self.lore = LorePanel(self)
        self.left = LSTabs()
        self.left.addTab(scroll(self.references), "Références")
        self.left.addTab(scroll(self.analysis), "Analyse")
        self.left.addTab(scroll(self.lore), "Lore Friendly")
        self.generation = GenerationPanel(self)
        self.mesh = MeshPanel(self)
        self.textures = TexturePanel(self)
        self.history = GenerationsPanel(self)
        self.right = LSTabs()
        self.right.addTab(scroll(self.generation), "Génération")
        self.right.addTab(scroll(self.mesh), "Maillage")
        self.right.addTab(scroll(self.textures), "Textures")
        self.right.addTab(scroll(self.history), "Historique")
        self.jobs_panel = JobsPanel(self)
        self.log_panel = LogPanel()
        self.hardware = HardwarePanel(self)
        self.bottom = LSTabs()
        self.bottom.addTab(self.jobs_panel, "Tâches")
        self.bottom.addTab(self.log_panel, "Journal")
        self.bottom.addTab(self.hardware, "Matériel et moteurs")
        for panel in (self.left, self.right, self.bottom):
            panel.setObjectName("LSStudioPanel")
            panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.left.setMinimumWidth(320)
        self.right.setMinimumWidth(350)

        self.views = QSplitter(Qt.Orientation.Horizontal)
        self.views.setHandleWidth(2)
        self.views.addWidget(self.viewport)
        self.views.addWidget(self.board)
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
        self.h_split.setSizes([350, 880, 380])
        self.v_split = QSplitter(Qt.Orientation.Vertical)
        self.v_split.setHandleWidth(1)
        self.v_split.addWidget(self.h_split)
        self.v_split.addWidget(self.bottom)
        self.v_split.setStretchFactor(0, 1)
        self.v_split.setSizes([720, 180])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.v_split)
        self.set_view_mode("split")
        controller.session_changed.connect(self._on_session)
        for signal in (controller.scene_changed, controller.state_changed):
            signal.connect(lambda *_: self.schedule_refresh())
        controller.selection_changed.connect(lambda *_: self.mesh.refresh())
        self._on_session()

    # --- En-tête ------------------------------------------------------------------------------
    def _header(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("LSStudioPanel")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(6)
        self.badge = LSBadge("Moteurs : détection…", "neutral")
        row.addWidget(self.badge)
        self.status = label("", "faint")
        self.status.setMinimumWidth(40)
        row.addWidget(self.status, 1)
        self.view_group = QButtonGroup(self)
        self.view_buttons: dict[str, LSButton] = {}
        for key, text, icon_name, tip in (
            ("3d", "3D", "cuboid", "Vue 3D seule"),
            ("refs", "Références", "image", "Tableau des références seul"),
            ("split", "3D + Références", "lsf-split", "Vue partagée"),
        ):
            widget = LSButton(text, "ghost", icon_name, True)
            widget.setCheckable(True)
            widget.setProperty("chip", True)
            widget.clicked.connect(lambda _c=False, k=key: self.set_view_mode(k))
            tooltip(widget, tip)
            self.view_group.addButton(widget)
            self.view_buttons[key] = widget
            row.addWidget(widget)
        engines = LSButton("Moteurs", "ghost", "lsf-chip", True)
        engines.clicked.connect(self.open_engines)
        tooltip(engines, "Moteurs locaux et cloud, clés API, cache")
        row.addWidget(engines)
        editor = LSButton("Vehicle Editor", "primary", "cuboid", True)
        editor.clicked.connect(self.transfer_to_editor)
        tooltip(editor, "Transférer le modèle sélectionné vers le Vehicle Editor (même projet)")
        row.addWidget(editor)
        self._compact_texts = {widget: widget.text() for widget in (*self.view_buttons.values(), engines)}
        self._compact = False
        self._header_bar = bar
        bar.installEventFilter(self)
        return bar

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (API Qt)
        if watched is getattr(self, "_header_bar", None) and event.type() == QEvent.Type.Resize:
            self._apply_compact(watched.width() < 900)
        return super().eventFilter(watched, event)

    def _apply_compact(self, compact: bool) -> None:
        """En-tête étroit (mise à l'échelle 125 % et plus) : boutons réduits à leur icône."""
        if compact == self._compact:
            return
        self._compact = compact
        for widget, text in self._compact_texts.items():
            widget.setText("" if compact else text)
        self._update_badge()

    def set_view_mode(self, mode: str) -> None:
        self.viewport.setVisible(mode in ("3d", "split"))
        self.board.setVisible(mode in ("refs", "split"))
        if mode in self.view_buttons:
            self.view_buttons[mode].setChecked(True)
        self.view_mode = mode

    def set_board_mode(self, mode: str) -> None:
        if mode != "view" and self.view_mode == "3d":
            self.set_view_mode("split")
        self.board.set_mode(mode)
        self.references.show_current()
        hints = {
            "crop": "Tracez le cadre de recadrage sur l'image.",
            "annotate": "Tracez un rectangle autour de l'élément à annoter.",
        }
        self.status.setText(hints.get(mode, ""))

    # --- Session ------------------------------------------------------------------------------
    @property
    def session(self):  # type: ignore[no-untyped-def]
        return self.controller.session

    def _on_session(self) -> None:
        session = self.controller.session
        self.viewport.set_session(session)
        self.creator = AIVehicleCreator(session, self.manager) if session is not None else None
        self.texture_outcome = None
        self.textures.show_outcome(None)
        self.last_root = None
        self.board.set_mode("view")
        self.refresh()

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        super().showEvent(event)
        if not self.detected:
            self.detect_engines()
        self.schedule_refresh()

    def schedule_refresh(self) -> None:
        self._refresh_timer.start(0)

    def refresh(self) -> None:
        for panel in (self.references, self.analysis, self.lore, self.generation, self.mesh, self.history):
            panel.refresh()
        self.jobs_panel.refresh()
        self.hardware.refresh()
        self.viewport.refresh()
        if self.creator is None:
            self.status.setText("Créez ou ouvrez un projet pour utiliser AI Vehicle Creator.")
        elif self.status.text().startswith("Créez"):
            self.status.setText("")

    def notify(self, title: str, message: str, level: str = "info") -> None:
        self.controller.notify.emit(title, message, level)

    def run(self, title: str, action):  # type: ignore[no-untyped-def]
        """Exécute une opération ; les erreurs prévues deviennent des notifications."""
        if self.creator is None:
            self.notify(title, "Aucun projet ouvert.", "warning")
            return None
        try:
            result = action()
        except EXPECTED as exc:
            log.warning("%s : %s", title, exc)
            self.notify(title, str(exc), "warning")
            return None
        self.schedule_refresh()
        return result

    # --- File de tâches -----------------------------------------------------------------------
    def submit(self, label_text: str, engine_id: str, function, on_success, on_failure=None) -> Job:  # type: ignore[no-untyped-def]
        job = self.manager.submit(label_text, engine_id, function)
        self._callbacks[job.id] = (on_success, on_failure)
        self.bottom.setCurrentWidget(self.jobs_panel)
        self.jobs_panel.refresh()
        return job

    def _on_job(self, job: Job) -> None:
        self._jobs_timer.start()
        if self.generation_job is not None and job is self.generation_job:
            self.generation.progress.set_progress(job.progress, job.message)
        while job.logs:
            self.log_panel.append(f"[{job.label}] {job.logs.pop(0)}")
        if job.active or job.id not in self._callbacks:
            return
        on_success, on_failure = self._callbacks.pop(job.id)
        self.log_panel.append(f"[{job.label}] {job.status} — {job.message}")
        if job.status == "succeeded":
            try:
                on_success(job.result)
            except EXPECTED as exc:
                log.warning("%s : %s", job.label, exc)
                self.notify(job.label, str(exc), "warning")
        else:
            if on_failure is not None:
                on_failure(job)
            if job.status == "cancelled":
                self.notify(job.label, "Tâche annulée.", "info")
            else:
                self.notify(job.label, job.error or job.message, "warning")
        self.schedule_refresh()

    def _request_listener(self, entry: dict) -> None:
        try:
            self.log_bridge.updated.emit(entry)
        except RuntimeError:  # page détruite : l'écouteur se retire
            if self._request_listener in ai_http.REQUEST_LOG.listeners:
                ai_http.REQUEST_LOG.listeners.remove(self._request_listener)

    @staticmethod
    def _format_request(entry: dict) -> str:
        return (
            f"[réseau] {entry.get('at')} {entry.get('provider')} {entry.get('method')} {entry.get('url')} → "
            f"{entry.get('status') or 'échec'} ({entry.get('duration_s')} s, "
            f"tentative {entry.get('attempt')})"
        )

    def wait_idle(self, timeout_ms: int = 60000) -> bool:
        """Attend la fin des tâches en traitant les événements (tests, scripts)."""
        timer = QElapsedTimer()
        timer.start()
        while (self.manager.queue.active() or self._callbacks) and timer.elapsed() < timeout_ms:
            QCoreApplication.processEvents()
        QCoreApplication.processEvents()
        return not self.manager.queue.active() and not self._callbacks

    # --- Moteurs ------------------------------------------------------------------------------
    def _update_badge(self) -> None:
        counts = getattr(self, "_badge_counts", None)
        if counts is None:
            return
        available, local = counts
        if self._compact:
            self.badge.setText(f"{available} moteur(s) · {local} local")
        else:
            self.badge.setText(f"{available} moteur(s) disponible(s) · {local} local(aux)")
        tooltip(self.badge, f"{available} moteur(s) disponible(s), dont {local} local(aux)")

    def detect_engines(self) -> Job:
        self.detected = True
        self.badge.setText("Moteurs : détection…")
        return self.submit(
            "Détection du matériel et des moteurs",
            "lsf-silhouette",
            lambda ctx: self.manager.detect_all(),
            lambda _result: self.after_detection(),
        )

    def after_detection(self) -> None:
        availability = self.manager.availability
        available = [e for e, a in availability.items() if a.ok]
        local = [e for e in available if self.manager.adapters[e].info.kind == "local"]
        self._badge_counts = (len(available), len(local))
        self._update_badge()
        self.badge.set_tint("green" if available else "amber")
        self.generation.refresh()
        self.hardware.refresh()

    def open_engines(self) -> EnginesDialog:
        dialog = EnginesDialog(self, self)
        dialog.open()
        self.engines_dialog = dialog
        return dialog

    # --- Références et analyse ----------------------------------------------------------------
    def import_references(self, paths) -> list[str]:  # type: ignore[no-untyped-def]
        if self.creator is None:
            self.notify("Références", "Créez ou ouvrez d'abord un projet.", "warning")
            return []
        added: list[str] = []
        stack = self.session.stack
        stack.begin("Import de références")
        try:
            for path in paths:
                try:
                    added.append(self.creator.add_reference(Path(path)))
                except AIError as exc:
                    self.notify("Référence", f"{Path(path).name} : {exc}", "warning")
        finally:
            stack.commit()
        if added:
            self.notify("Références", f"{len(added)} image(s) importée(s).", "success")
            if self.view_mode == "3d":
                self.set_view_mode("split")
        self.schedule_refresh()
        return added

    def analyze(self) -> Job | None:
        if self.creator is None:
            return None
        try:
            function = self.creator.analysis_job(self.analysis.known())
        except AIError as exc:
            self.notify("Analyse", str(exc), "warning")
            return None
        creator = self.creator
        return self.submit(
            "Analyse du véhicule",
            "lsf-silhouette",
            function,
            lambda report: self.run("Analyse", lambda: creator.set_analysis(report)),
        )

    def _cloud_request(self, capability: Capability, prompt: str = "") -> tuple | None:
        adapter = self.manager.adapters.get("anthropic")
        if adapter is None or self.creator is None:
            return None
        availability = self.manager.availability_of("anthropic")
        if not availability.ok:
            self.notify("Cloud", f"Anthropic indisponible : {availability.message}", "warning")
            return None
        refs = [r for r in self.creator.references() if r["view"] != "interior"]
        if not refs:
            self.notify("Cloud", "Aucune référence à envoyer.", "warning")
            return None
        cost = adapter.estimate(GenerationRequest(capability, [], Path("."))).describe()
        message = (
            f"Envoyer {len(refs)} image(s) de référence à {adapter.info.name} ?\n\n"
            f"Coût : {cost}.\nLes logos annotés sont masqués avant l'envoi. Les images quittent votre PC."
        )
        if not LSModal.confirm(self, "Transfert cloud", message, "Envoyer"):
            return None
        folder = self.manager.job_dir()
        inputs = self.creator.reference_inputs(folder / "inputs")
        request = GenerationRequest(
            capability, inputs, folder, prompt=prompt, allow_cloud=True, allow_paid=True
        )
        return adapter, request

    def cloud_analysis(self) -> Job | None:
        prepared = self._cloud_request(Capability.VISION)
        if prepared is None:
            return None
        adapter, request = prepared
        creator = self.creator
        return self.submit(
            "Analyse cloud",
            "anthropic",
            lambda ctx: adapter.run(request, ctx),
            lambda output: self.run(
                "Analyse cloud", lambda: creator.merge_cloud_analysis(output, adapter.info.name)
            ),
        )

    def lore_proposals(self) -> list | None:
        return self.run("Lore Friendly", lambda: self.creator.generate_proposals())

    def cloud_lore(self) -> Job | None:
        report = self.creator.document().get("analysis") if self.creator else None
        summary = ""
        if report:
            fields = report.get("fields", {})
            summary = ", ".join(
                f"{k}={fields[k].get('value')}" for k in ("type", "length_m", "body_color") if k in fields
            )
        prepared = self._cloud_request(Capability.LORE_TEXT, summary)
        if prepared is None:
            return None
        adapter, request = prepared
        creator = self.creator
        return self.submit(
            "Suggestions Lore Friendly (cloud)",
            "anthropic",
            lambda ctx: adapter.run(request, ctx),
            lambda output: self.run("Lore Friendly", lambda: creator.merge_cloud_proposals(output)),
        )

    # --- Génération ---------------------------------------------------------------------------
    def generate(self, engine_id: str | None = None, profile: str | None = None) -> Job | None:
        creator = self.creator
        if creator is None:
            self.notify("Génération", "Créez ou ouvrez d'abord un projet.", "warning")
            return None
        if self.generation_job is not None and self.generation_job.active:
            self.notify("Génération", "Une génération est déjà en cours.", "info")
            return None
        self.generation.update_routing()
        engine_id = engine_id or self.generation.chosen_engine()
        profile = profile or self.generation.profile.currentData()
        if engine_id is None:
            self.notify(
                "Génération",
                "Aucun moteur disponible : voir « Moteurs » et l'explication du routage.",
                "warning",
            )
            return None
        adapter = self.manager.adapters[engine_id]
        length = self.generation.length.value()
        prompt = self.generation.prompt.text().strip()
        changes: dict = {"engine": engine_id, "profile": profile, "prompt": prompt}
        if length > 0:
            changes["length_m"] = length
        creator.set_settings(**changes)
        estimate = adapter.estimate(GenerationRequest(Capability.IMAGE_TO_3D, [], Path("."), profile))
        allow_cloud = allow_paid = False
        if adapter.info.kind == "cloud":
            if not self.generation.allow_cloud.isChecked() or self.manager.config.get("confirm_cloud", True):
                text = (
                    f"Envoyer les images de référence à {adapter.info.name} ?\n"
                    "Les logos annotés sont masqués avant l'envoi. Les images quittent votre PC."
                )
                if not LSModal.confirm(self, "Transfert cloud", text, "Envoyer"):
                    return None
            allow_cloud = True
        if estimate.paid:
            text = (
                f"Cette génération est facturée par {adapter.info.name} : {estimate.describe()}.\nContinuer ?"
            )
            accepted = self.generation.allow_paid.isChecked()
            if not accepted and not LSModal.confirm(self, "Opération payante", text, "Accepter le coût"):
                return None
            allow_paid = True
        try:
            function = creator.generation_job(engine_id, profile, {}, prompt, allow_cloud, allow_paid)
        except AIError as exc:
            self.notify("Génération", str(exc), "warning")
            return None
        estimated = estimate.describe()

        def succeeded(outcome) -> None:  # type: ignore[no-untyped-def]
            record_id = creator.apply_generation(outcome)
            self.last_root = creator.record(record_id)["root_id"]
            warnings = "\n".join(f"⚠ {w}" for w in outcome.output.warnings)
            cached = " — résultat du cache" if outcome.cached else ""
            self.generation.result.setText(
                f"Modèle généré par {adapter.info.name} en {outcome.duration_s:.1f} s "
                f"({outcome.import_result.triangle_count} triangles){cached}.\n{warnings}"
            )
            self.frame_model()
            self.notify("Génération", f"Modèle importé ({adapter.info.name}).", "success")

        def failed(job: Job) -> None:
            message = job.error or job.message
            self.run(
                "Historique",
                lambda: creator.record_failure(
                    engine_id, profile, job.status, message, job.duration, prompt, estimated
                ),
            )
            self.generation.result.setText(message)

        self.generation.progress.reset("En file d'attente…")
        self.generation_job = self.submit(
            f"Génération — {adapter.info.name}", engine_id, function, succeeded, failed
        )
        return self.generation_job

    def cancel_generation(self) -> None:
        if self.generation_job is not None and self.generation_job.active:
            self.manager.queue.cancel(self.generation_job.id)

    def apply_settings(self, settings: dict) -> None:
        self.generation.engine.select_data(settings.get("engine", "auto"))
        self.generation.profile.select_data(settings.get("profile", "balanced"))
        self.generation.prompt.setText(settings.get("prompt", ""))
        self.right.setCurrentIndex(0)
        self.generation.update_routing()

    # --- Modèle -------------------------------------------------------------------------------
    def target_root(self) -> str | None:
        session = self.session
        if session is None:
            return None
        for node_id in session.selection.ids:
            if node_id in session.scene:
                top = node_id
                for ancestor in session.scene.ancestors(node_id):
                    top = ancestor.id
                return top
        if self.last_root in session.scene:
            return self.last_root
        for record in reversed(self.creator.records() if self.creator else []):
            if record.get("root_id") in session.scene:
                return record["root_id"]
        return None

    def target_mesh(self):  # type: ignore[no-untyped-def]
        session = self.session
        if session is None or self.creator is None:
            return None
        nodes = self.creator.mesh_nodes()
        if not nodes:
            root = self.target_root()
            nodes = self.creator.mesh_nodes([root]) if root else []
        if not nodes:
            return None
        return max(nodes, key=lambda n: session.geometry_for(n).triangle_count)

    def frame_model(self) -> None:
        session = self.session
        self.viewport.frame_bounds(session.world_bounds() if session else None)

    def transfer_to_editor(self) -> None:
        root = self.target_root()
        if root is not None:
            self.session.selection.set([root])
        self.editor_requested.emit()

    def apply_fix(self, key: str) -> list[str] | None:
        node = self.target_mesh()
        if node is None:
            self.notify("Maillage", "Sélectionnez un maillage (ou générez un modèle).", "info")
            return None
        if key in mesh_assist.CONFIRM_FIXES:
            text = f"{mesh_assist.FIXES[key]} sur « {node.name} » ?\nL'opération est annulable (Ctrl+Z)."
            if not LSModal.confirm(self, "Validation requise", text, "Appliquer"):
                return None
        options = self.mesh.options(key)
        warnings = self.run("Assistant maillage", lambda: self.creator.apply_fix(node.id, key, **options))
        if warnings is not None:
            self.notify("Assistant maillage", " ".join(warnings) or "Correction appliquée.", "success")
            report = self.run("Analyse du maillage", lambda: self.creator.analyze_mesh(node.id))
            if report:
                self.mesh.show_report(report)
        return warnings

    def turn_model(self, degrees: float) -> None:
        root = self.target_root()
        if root is None:
            self.notify("Placement", "Aucun modèle.", "info")
            return
        self.run("Placement", lambda: self.creator.turn_model(root, degrees))

    def fit_to_analysis(self) -> list[str] | None:
        root = self.target_root()
        if root is None:
            self.notify("Placement", "Aucun modèle.", "info")
            return None
        result = self.run("Recalage", lambda: self.creator.fit_to_analysis(root))
        if result is not None:
            self.notify("Recalage", ", ".join(result) or "Déjà aux proportions mesurées.", "success")
        return result

    def apply_adjustment(self, kind: str, amount: float) -> list[str] | None:
        node = self.target_mesh()
        if node is None:
            self.notify("Lore Friendly", "Sélectionnez un maillage.", "info")
            return None
        text = f"Appliquer l'ajustement ({amount:+.0%}) à « {node.name} » ? Annulable (Ctrl+Z)."
        if not LSModal.confirm(self, "Ajustement géométrique", text, "Appliquer"):
            return None
        return self.run("Lore Friendly", lambda: self.creator.apply_adjustment(node.id, kind, amount))

    # --- Textures -----------------------------------------------------------------------------
    def generate_textures(self) -> Job | None:
        node = self.target_mesh()
        if node is None or self.creator is None:
            self.notify("Textures", "Sélectionnez un maillage (ou générez un modèle).", "info")
            return None
        try:
            function = self.creator.texture_job(
                node.id, self.textures.method.currentData(), self.textures.size.currentData(),
                self.textures.preset.currentData(),
            )  # fmt: skip
        except AIError as exc:
            self.notify("Textures", str(exc), "warning")
            return None

        def succeeded(outcome) -> None:  # type: ignore[no-untyped-def]
            self.texture_outcome = outcome
            self.textures.show_outcome(outcome)
            self.notify("Textures", "Cartes prêtes : vérifiez-les puis « Appliquer au modèle ».", "success")

        return self.submit("Textures IA", "lsf-silhouette", function, succeeded)

    def apply_textures(self) -> str | None:
        if self.texture_outcome is None:
            self.notify("Textures", "Générez d'abord les textures.", "info")
            return None
        outcome = self.texture_outcome
        material = self.run("Textures", lambda: self.creator.apply_textures(outcome))
        if material:
            self.notify("Textures", "Matériau créé et affecté au modèle.", "success")
        return material

    def texture_variant(self) -> str | None:
        node = self.target_mesh()
        if node is None or not node.material_id:
            self.notify("Variante", "Le modèle n'a pas encore de texture IA.", "info")
            return None
        hue = self.textures.hue.value()
        return self.run("Variante", lambda: self.creator.texture_variant(node.material_id, hue))

    def open_livery(self) -> None:
        node = self.target_mesh()
        if node is None or not node.material_id:
            self.notify("Livery Studio", "Appliquez d'abord une texture au modèle.", "info")
            return
        self.session.selection.set([node.id])
        self.livery_requested.emit()
