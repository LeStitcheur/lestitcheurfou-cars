"""Lore Friendly Studio : transformation d'un véhicule de référence en création originale.

Organisation : gauche (source, marques, styles, presets), centre (viewport 3D, comparaison
avant / après), droite (analyse, transformation, propositions, propriétés), bas (historique,
progression, diagnostics, validation, provenance). Modes simplifié et avancé.

Les calculs longs (aperçus, appels cloud, images conceptuelles) passent par la file de tâches de
l'AI Engine Manager ; leurs résultats sont appliqués au projet par des commandes annulables.
Aucun transfert cloud ni opération payante sans confirmation explicite.
"""

from __future__ import annotations

import io

from PIL import Image
from PySide6.QtCore import QCoreApplication, QElapsedTimer, QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from lsfcars.ai.engines.base import Capability, GenerationRequest
from lsfcars.ai.errors import AIError
from lsfcars.ai.manager import AIEngineManager, Job
from lsfcars.core.logging_setup import get_logger
from lsfcars.core.paths import app_data_dir
from lsfcars.editor import compat
from lsfcars.lorefriendly import concepts, preview, provenance
from lsfcars.lorefriendly import operations as ops
from lsfcars.lorefriendly.engine import SOURCE, LoreError, LoreFriendlyEngine
from lsfcars.scene.commands import CompositeCommand, SetNodeExtra
from lsfcars.scene.editmesh import EditError
from lsfcars.scene.graph import NodeKind
from lsfcars.ui.ai.widgets import JobBridge
from lsfcars.ui.design.components import LSBadge, LSButton, LSModal, LSSelect, LSTabs, label, tooltip
from lsfcars.ui.editor.panels import scroll
from lsfcars.ui.lore.compare import ComparisonView
from lsfcars.ui.lore.panels import (
    AnalysisPanel,
    BrandsPanel,
    DiagnosticsPanel,
    HistoryPanel,
    JobsPanel,
    PresetsPanel,
    PropertiesPanel,
    ProposalsPanel,
    ProvenancePanel,
    SourcePanel,
    StylesPanel,
    TransformPanel,
    ValidationPanel,
)
from lsfcars.ui.viewport import Viewport3D

log = get_logger(__name__)
EXPECTED = (AIError, EditError, OSError, ValueError)
CPU_RESOURCE = "lsf-silhouette"  # file « calcul local » de l'AI Engine Manager


class LoreFriendlyStudioPage(QWidget):
    editor_requested = Signal()
    livery_requested = Signal()
    emergency_requested = Signal()
    import_requested = Signal()

    def __init__(
        self, controller, settings, manager: AIEngineManager | None = None, parent: QWidget | None = None
    ) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.controller = controller
        self.settings = settings
        self.manager = manager or AIEngineManager(app_data_dir())
        self.engine: LoreFriendlyEngine | None = None
        self.jobs: list[Job] = []
        self.simple = False
        self.view_mode = "3d"
        self.last_check: dict | None = None
        self.last_report: list[tuple[str, str]] = []
        self._callbacks: dict[str, tuple] = {}
        self.bridge = JobBridge(self)
        self.bridge.updated.connect(self._on_job)
        self.manager.queue.listeners.append(self.bridge)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.refresh)

        self.viewport = Viewport3D()
        self.viewport.frame_requested.connect(self.frame_model)
        self.comparison = ComparisonView(self)
        self.source = SourcePanel(self)
        self.brands = BrandsPanel(self)
        self.styles = StylesPanel(self)
        self.presets = PresetsPanel(self)
        self.left = LSTabs()
        for panel, text in (
            (self.source, "Source"),
            (self.brands, "Marques"),
            (self.styles, "Styles"),
            (self.presets, "Presets"),
        ):
            self.left.addTab(scroll(panel), text)
        self.analysis = AnalysisPanel(self)
        self.transform = TransformPanel(self)
        self.proposals = ProposalsPanel(self)
        self.properties = PropertiesPanel(self)
        self.right = LSTabs()
        for panel, text in (
            (self.analysis, "Analyse"),
            (self.transform, "Transformation"),
            (self.proposals, "Propositions"),
            (self.properties, "Propriétés"),
        ):
            self.right.addTab(scroll(panel), text)
        self.history = HistoryPanel(self)
        self.jobs_panel = JobsPanel(self)
        self.diagnostics_panel = DiagnosticsPanel(self)
        self.validation = ValidationPanel(self)
        self.provenance_panel = ProvenancePanel(self)
        self.bottom = LSTabs()
        for panel, text in (
            (self.history, "Historique"),
            (self.jobs_panel, "Progression"),
            (self.diagnostics_panel, "Diagnostics"),
            (self.validation, "Validation"),
            (self.provenance_panel, "Provenance"),
        ):
            self.bottom.addTab(panel, text)
        self.bottom.currentChanged.connect(lambda _i: self._bottom_changed())
        for panel in (self.left, self.right, self.bottom):
            panel.setObjectName("LSStudioPanel")
            panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.left.setMinimumWidth(330)
        self.right.setMinimumWidth(360)

        self.center_stack = QStackedWidget()
        self.center_stack.addWidget(self.viewport)
        self.center_stack.addWidget(self.comparison)
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        center_layout.addWidget(self._header())
        center_layout.addWidget(self.center_stack, 1)
        self.h_split = QSplitter(Qt.Orientation.Horizontal)
        self.h_split.setHandleWidth(1)
        for widget in (self.left, center, self.right):
            self.h_split.addWidget(widget)
        self.h_split.setStretchFactor(1, 1)
        self.h_split.setSizes([350, 880, 390])
        self.v_split = QSplitter(Qt.Orientation.Vertical)
        self.v_split.setHandleWidth(1)
        self.v_split.addWidget(self.h_split)
        self.v_split.addWidget(self.bottom)
        self.v_split.setStretchFactor(0, 1)
        self.v_split.setSizes([720, 200])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.v_split)
        controller.session_changed.connect(self._on_session)
        for signal in (controller.scene_changed, controller.state_changed):
            signal.connect(lambda *_: self.schedule_refresh())
        controller.selection_changed.connect(lambda *_: self.properties.refresh())
        self.set_view("3d")
        self._on_session()

    # --- En-tête ------------------------------------------------------------------------------
    def _header(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("LSStudioPanel")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(6)
        self.badge = LSBadge("Aucun design", "neutral")
        self.badge.setMaximumWidth(420)
        row.addWidget(self.badge)
        self.status = label("", "faint")
        self.status.setMinimumWidth(40)
        row.addWidget(self.status, 1)
        self.mode_select = LSSelect([("Simplifié", True), ("Avancé", False)])
        self.mode_select.select_data(False)
        self.mode_select.activated.connect(lambda _i: self.set_simple(bool(self.mode_select.currentData())))
        tooltip(self.mode_select, "Simplifié : parcours guidé ; avancé : tous les studios et réglages")
        row.addWidget(self.mode_select)
        self._compact_texts: dict = {}
        self._compact = False
        self.view_group = QButtonGroup(self)
        self.view_buttons: dict[str, LSButton] = {}
        for key, text, icon_name, tip in (
            ("3d", "3D", "cuboid", "Viewport 3D (élément affiché)"),
            ("compare", "Comparaison", "lsf-split", "Design Comparison Studio : avant / après"),
        ):
            widget = LSButton(text, "ghost", icon_name, True)
            widget.setCheckable(True)
            widget.setProperty("chip", True)
            widget.clicked.connect(lambda _c=False, k=key: self.set_view(k))
            tooltip(widget, tip)
            self.view_group.addButton(widget)
            self.view_buttons[key] = widget
            self._compact_texts[widget] = text
            row.addWidget(widget)
        for text, icon_name, slot, tip, variant in (
            (
                "Vehicle Editor",
                "cuboid",
                self.transfer_to_editor,
                "Ouvrir l'élément affiché dans le Vehicle Editor",
                "primary",
            ),
            (
                "Livery",
                "lsf-brush",
                self.transfer_to_livery,
                "Livrée, logos et palettes de la variante (Livery Studio)",
                "ghost",
            ),
            (
                "Emergency",
                "siren",
                self.transfer_to_emergency,
                "Variantes de service (Emergency Studio)",
                "ghost",
            ),
        ):
            widget = LSButton(text, variant, icon_name, True)
            widget.clicked.connect(slot)
            tooltip(widget, tip)
            self._compact_texts[widget] = text
            row.addWidget(widget)
        self._header_bar = bar
        bar.installEventFilter(self)
        return bar

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (API Qt)
        if watched is getattr(self, "_header_bar", None) and event.type() == QEvent.Type.Resize:
            compact = watched.width() < 1000  # mise à l'échelle 125 % et plus : icônes seules
            if compact != self._compact:
                self._compact = compact
                for widget, text in self._compact_texts.items():
                    widget.setText("" if compact else text)
                self.badge.setMaximumWidth(220 if compact else 420)
        return super().eventFilter(watched, event)

    def set_view(self, mode: str) -> None:
        self.view_mode = mode
        self.center_stack.setCurrentWidget(self.comparison if mode == "compare" else self.viewport)
        self.view_buttons[mode].setChecked(True)
        if mode == "compare":
            self.comparison.refresh()

    def set_simple(self, simple: bool) -> None:
        """Mode simplifié : source, marques, presets, analyse, propositions, validation."""
        self.simple = simple
        self.mode_select.select_data(simple)
        self.left.setTabVisible(2, not simple)
        self.right.setTabVisible(1, not simple)
        self.right.setTabVisible(3, not simple)
        self.bottom.setTabVisible(2, not simple)
        self.bottom.setTabVisible(4, not simple)

    def _bottom_changed(self) -> None:
        if self.bottom.currentWidget() is self.provenance_panel:
            self.provenance_panel.refresh()

    # --- Session et rafraîchissement ---------------------------------------------------------
    @property
    def session(self):  # type: ignore[no-untyped-def]
        return self.controller.session

    def _on_session(self) -> None:
        session = self.session
        self.viewport.set_session(session)
        self.comparison.set_session(session)
        self.engine = (
            LoreFriendlyEngine(session, self.manager, app_data_dir()) if session is not None else None
        )
        self.last_check = None
        self.last_report = []
        self.refresh()

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        super().showEvent(event)
        self.schedule_refresh()

    def schedule_refresh(self) -> None:
        self._refresh_timer.start(0)

    def refresh(self) -> None:
        if self.engine is not None:
            self.engine.sync_libraries()
        for panel in (
            self.source,
            self.brands,
            self.styles,
            self.presets,
            self.analysis,
            self.transform,
            self.proposals,
            self.properties,
            self.history,
            self.jobs_panel,
            self.diagnostics_panel,
            self.validation,
        ):
            panel.refresh()
        if self.bottom.currentWidget() is self.provenance_panel:
            self.provenance_panel.refresh()
        if self.view_mode == "compare":
            self.comparison.refresh()
        self.viewport.refresh()
        design = self.design()
        if self.engine is None:
            self.badge.setText("Aucun projet")
            self.status.setText("Créez ou ouvrez un projet pour utiliser Lore Friendly Studio.")
        elif design is None:
            self.badge.setText("Aucun design")
            self.badge.set_tint("neutral")
            self.status.setText("Choisissez un véhicule source (onglet Source).")
        else:
            self.badge.setText(f"{design['name']} · {self.engine.label(design, self.target())}")
            self.badge.set_tint("blue" if self.target() != SOURCE else "neutral")
            self.status.setText("")

    def design(self) -> dict | None:
        if self.engine is None or not self.engine.has_design():
            return None
        try:
            return self.engine.design()
        except LoreError:
            return None

    def target(self) -> str:
        design = self.design()
        if design is None:
            return SOURCE
        target = design.get("display", SOURCE)
        return target if target == SOURCE or any(v["id"] == target for v in design["variants"]) else SOURCE

    def notify(self, title: str, message: str, level: str = "info") -> None:
        self.controller.notify.emit(title, message, level)

    def run(self, title: str, action):  # type: ignore[no-untyped-def]
        """Exécute une opération ; les erreurs prévues deviennent des notifications."""
        if self.engine is None:
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

    def frame_model(self) -> None:
        session = self.session
        if session is None:
            return
        design = self.design()
        bounds = None
        if design is not None:
            try:
                bounds = session.world_bounds(
                    [self.engine.root_of(design, self.target())], only_visible=False
                )  # type: ignore[union-attr]
            except LoreError:
                bounds = None
        self.viewport.frame_bounds(bounds or session.world_bounds())

    # --- File de tâches -------------------------------------------------------------------------
    def submit(self, label_text: str, resource: str, function, on_success, on_failure=None) -> Job:  # type: ignore[no-untyped-def]
        job = self.manager.submit(label_text, resource, function)
        self._callbacks[job.id] = (on_success, on_failure)
        self.jobs.append(job)
        self.bottom.setCurrentWidget(self.jobs_panel)
        self.jobs_panel.refresh()
        return job

    def _on_job(self, job: Job) -> None:
        if job.id not in self._callbacks and not any(j.id == job.id for j in self.jobs):
            return
        self.jobs_panel.refresh()
        if job.active or job.id not in self._callbacks:
            return
        on_success, on_failure = self._callbacks.pop(job.id)
        if job.status == "succeeded":
            try:
                on_success(job.result)
            except EXPECTED as exc:
                log.warning("%s : %s", job.label, exc)
                self.notify(job.label, str(exc), "warning")
        else:
            if on_failure is not None:
                on_failure(job)
            cancelled = job.status == "cancelled"
            self.notify(
                job.label,
                "Tâche annulée." if cancelled else (job.error or job.message),
                "info" if cancelled else "warning",
            )
        self.schedule_refresh()

    def cancel_job(self) -> None:
        active = next((j for j in reversed(self.jobs) if j.active), None)
        if active is not None:
            self.manager.queue.cancel(active.id)

    def wait_idle(self, timeout_ms: int = 60000) -> bool:
        timer = QElapsedTimer()
        timer.start()
        while (any(j.active for j in self.jobs) or self._callbacks) and timer.elapsed() < timeout_ms:
            QCoreApplication.processEvents()
        QCoreApplication.processEvents()
        return not any(j.active for j in self.jobs) and not self._callbacks

    # --- Actions du parcours ---------------------------------------------------------------------
    def show(self, target: str) -> None:
        self.run("Affichage", lambda: self.engine.show(None, target))  # type: ignore[union-attr]
        self.frame_model()

    def new_variant(self, from_target: str = SOURCE) -> str | None:
        return self.run(
            "Nouvelle variante", lambda: self.engine.create_variant(None, from_target=from_target)
        )  # type: ignore[union-attr]

    def analyze(self) -> dict | None:
        report = self.run("Analyse stylistique", lambda: self.engine.analyze(None, self.target()))  # type: ignore[union-attr]
        if report is not None:
            self.right.setCurrentIndex(0)
        return report

    def _confirm_plan(self, plan: list[dict], label_text: str) -> bool:
        design = self.design()
        if design is None:
            self.notify(label_text, "Créez d'abord un design (onglet Source).", "warning")
            return False
        check = self.run("Vérification", lambda: self.engine.check(None, self.target(), plan))  # type: ignore[union-attr]
        if check is None:
            return False
        self.last_check = check
        if len(check["skipped"]) == len(plan):
            self.notify(
                label_text, "Transformation incompatible : " + " ; ".join(check["skipped"]), "warning"
            )
            self.diagnostics_panel.refresh()
            return False
        where = (
            "une nouvelle variante (la source reste intacte)"
            if self.target() == SOURCE
            else f"la variante « {self.engine.label(design, self.target())} »"  # type: ignore[union-attr]
        )
        lines = [f"Appliquer « {label_text} » à {where} ?", "", *check["messages"][:10]]
        if check["skipped"]:
            lines += ["", "Ignoré (incompatible) :", *check["skipped"]]
        if check["impacts"]:
            lines += ["", "À vérifier ensuite :", *check["impacts"]]
        lines += [
            "",
            "Annulable (Ctrl+Z). Aucune garantie de compatibilité FiveM ni de conformité juridique.",
        ]
        return LSModal.confirm(self, "Confirmer la transformation", "\n".join(lines), "Appliquer")

    def apply_plan(self, plan: list[dict], label_text: str) -> dict | None:
        if not self._confirm_plan(plan, label_text):
            return None
        engine = self.engine
        target = self.target()

        def action() -> dict:
            if target != SOURCE:
                return engine.apply_plan(None, target, plan, label_text)  # type: ignore[union-attr]
            stack = self.session.stack
            stack.begin(label_text)  # nouvelle variante + transformation : une seule étape d'historique
            try:
                variant = engine.create_variant(None, label_text)  # type: ignore[union-attr]
                result = engine.apply_plan(None, variant, plan, label_text)  # type: ignore[union-attr]
            except Exception:
                stack.rollback()
                raise
            stack.commit()
            return result

        result = self.run(label_text, action)
        if result is not None:
            self.last_check = result
            self.notify(
                label_text, " ".join(result["messages"][:3]) or "Transformation appliquée.", "success"
            )
        return result

    def apply_preset(self, key: str) -> dict | None:
        title, _description, plan = concepts.QUICK_PRESETS[key]
        return self.apply_plan(plan, title)

    def preview_operation(self, op: str, params: dict) -> Job | None:
        design = self.design()
        if design is None or self.engine is None:
            self.notify("Aperçu", "Créez d'abord un design.", "info")
            return None
        try:
            before = self.engine.state(design, self.target())
            after = self.engine.state(design, self.target())
        except EXPECTED as exc:
            self.notify("Aperçu", str(exc), "warning")
            return None

        def job(ctx) -> tuple[bytes, list[str]]:  # type: ignore[no-untyped-def]
            messages = ops.apply(after, op, params)
            ctx.progress(0.5, "Rendu")
            sheet = Image.new("RGB", (320, 320), (226, 229, 234))
            for column, view in enumerate(("three_quarter", "left")):
                fit = preview.common_fit([before.render_list(), after.render_list()], view)
                sheet.paste(preview.render(before.render_list(), view, 160, fit=fit), (column * 160, 0))
                sheet.paste(preview.render(after.render_list(), view, 160, fit=fit), (column * 160, 160))
            buffer = io.BytesIO()
            sheet.save(buffer, "PNG")
            return buffer.getvalue(), messages

        def done(result) -> None:  # type: ignore[no-untyped-def]
            png, messages = result
            self.transform.show_preview(png, ["Haut : avant · bas : après."] + messages)

        def failed(job_failed: Job) -> None:
            self.transform.preview_text.setText(job_failed.error or job_failed.message)

        return self.submit(f"Aperçu : {ops.OPERATIONS[op].label}", CPU_RESOURCE, job, done, failed)

    def generate_concepts(self, count: int = 3) -> list | None:
        result = self.run("Propositions", lambda: self.engine.generate_concepts(None, count))  # type: ignore[union-attr]
        if result:
            self.right.setCurrentIndex(2)
            self.compute_previews([c["id"] for c in result])
        return result

    def compute_previews(self, concept_ids: list[str] | None = None) -> Job | None:
        design = self.design()
        if design is None or not design["concepts"]:
            self.notify("Aperçus", "Aucune proposition.", "info")
            return None
        missing = concept_ids or [c["id"] for c in design["concepts"] if not c.get("preview")]
        if not missing:
            self.notify("Aperçus", "Tous les aperçus sont déjà calculés.", "info")
            return None
        try:
            job = self.engine.preview_job(design["id"], missing)  # type: ignore[union-attr]
        except EXPECTED as exc:
            self.notify("Aperçus", str(exc), "warning")
            return None
        design_id = design["id"]
        return self.submit(
            "Aperçus des propositions",
            CPU_RESOURCE,
            job,
            lambda results: self.run("Aperçus", lambda: self.engine.apply_previews(design_id, results)),  # type: ignore[union-attr]
        )

    def cloud_concepts(self, count: int = 3) -> Job | None:
        design = self.design()
        adapter = self.manager.adapters.get("anthropic")
        if design is None or adapter is None:
            return None
        if not design.get("brand"):
            self.notify("Propositions cloud", "Choisissez d'abord une marque fictive.", "info")
            return None
        availability = self.manager.availability_of("anthropic")
        if not availability.ok:
            self.notify(
                "Propositions cloud", f"{adapter.info.name} indisponible : {availability.message}", "warning"
            )
            return None
        cost = adapter.estimate(
            GenerationRequest(Capability.DESIGN_PLAN, [], self.manager.job_dir())
        ).describe()
        message = (
            f"Envoyer à {adapter.info.name} un résumé texte de l'analyse (dimensions, composants, marque, "
            f"Design DNA) ?\n\nAucune image ni aucun modèle 3D n'est envoyé.\nCoût : {cost}.\n"
            "Les plans reçus sont vérifiés contre le catalogue local avant d'être proposés."
        )
        if not LSModal.confirm(self, "Transfert cloud", message, "Envoyer"):
            return None
        folder = self.manager.job_dir()
        request = self.run(
            "Propositions cloud",
            lambda: self.engine.cloud_request(None, folder, count, allow_cloud=True, allow_paid=True),  # type: ignore[union-attr]
        )
        if request is None:
            return None
        design_id = design["id"]

        def merged(output) -> None:  # type: ignore[no-untyped-def]
            result = self.run(
                "Propositions cloud",
                lambda: self.engine.merge_cloud_concepts(
                    design_id, output, adapter.info.id, adapter.info.name
                ),  # type: ignore[union-attr]
            )
            if result is None:
                return
            stored, rejected = result
            if rejected:
                ignored = ", ".join(rejected[:6])
                self.notify(
                    "Propositions cloud",
                    f"Opérations écartées (hors catalogue ou incompatibles) : {ignored}",
                    "info",
                )
            if stored:
                self.compute_previews([c["id"] for c in stored])

        return self.submit("Propositions cloud", "anthropic", lambda ctx: adapter.run(request, ctx), merged)

    def apply_concept(self, concept_id: str) -> str | None:
        design = self.design()
        if design is None:
            return None
        concept = next(c for c in design["concepts"] if c["id"] == concept_id)
        if not self._confirm_plan(concept["plan"], f"Proposition « {concept['title']} »"):
            return None
        variant = self.run("Proposition", lambda: self.engine.apply_concept(None, concept_id))  # type: ignore[union-attr]
        if variant is not None:
            self.notify("Proposition", f"Variante « {concept['title']} » créée et transformée.", "success")
            self.frame_model()
        return variant

    def concept_image(self, concept_id: str) -> Job | None:
        adapter = self.manager.adapters.get("comfyui")
        if adapter is None:
            return None
        availability = self.manager.availability_of("comfyui")
        if not availability.ok:
            self.notify("Image conceptuelle", f"ComfyUI indisponible : {availability.message}", "warning")
            return None
        message = (
            f"Envoyer l'aperçu rendu de la proposition au serveur ComfyUI local ({adapter.base_url}) pour "
            "produire une image conceptuelle 2D ?\n\nLe résultat est une illustration : il ne modifie "
            "aucune géométrie et n'est jamais présenté comme un modèle 3D."
        )
        if not LSModal.confirm(self, "Image conceptuelle 2D", message, "Envoyer"):
            return None
        folder = self.manager.job_dir()
        request = self.run(
            "Image conceptuelle", lambda: self.engine.concept_image_request(None, concept_id, folder)
        )  # type: ignore[union-attr]
        if request is None:
            return None
        return self.submit(
            "Image conceptuelle 2D",
            "comfyui",
            lambda ctx: adapter.run(request, ctx),
            lambda output: self.run(
                "Image conceptuelle", lambda: self.engine.attach_concept_image(None, concept_id, output)
            ),  # type: ignore[union-attr]
        )

    # --- Propriétés et validation -----------------------------------------------------------------
    def selected_component(self):  # type: ignore[no-untyped-def]
        session = self.session
        if session is None or not session.selection.ids:
            return None
        node = session.scene.get(session.selection.active or session.selection.ids[-1])
        if node is None:
            return None
        design = self.design()
        if design is None:
            return node, None
        try:
            state = self.engine.state(design, self.target())  # type: ignore[union-attr]
        except EXPECTED:
            return node, None
        return node, state.components.component_of(node.id)

    def set_component_kind(self, kind: str) -> None:
        info = self.selected_component()
        if info is None or info[1] is None:
            self.notify("Type de pièce", "Sélectionnez une pièce du véhicule affiché.", "info")
            return
        if self.target() == SOURCE:
            self.notify(
                "Type de pièce", "La source est verrouillée : corrigez le type dans une variante.", "info"
            )
            return
        owner = self.session.scene.nodes[info[1].node_id]
        after = {**owner.extra, "component": {**owner.extra.get("component", {}), "lore_kind": kind}}
        command = SetNodeExtra({owner.id: (dict(owner.extra), after)}, "Type de pièce")
        self.run(
            "Type de pièce", lambda: self.session.stack.push(CompositeCommand([command], "Type de pièce"))
        )

    def review(self) -> dict | None:
        if self.target() == SOURCE:
            self.notify(
                "Revue d'originalité", "Affichez une variante : la revue la compare à l'original.", "info"
            )
            return None
        result = self.run("Revue d'originalité", lambda: self.engine.review(None, self.target()))  # type: ignore[union-attr]
        if result is not None:
            self.bottom.setCurrentWidget(self.validation)
        return result

    def set_checklist(self, key: str, value: bool) -> None:
        if self.design() is not None:
            self.run("Vérification", lambda: self.engine.set_checklist(None, key, value))  # type: ignore[union-attr]

    def fivem_report(self) -> list[tuple[str, str]]:
        """Préparation au pipeline FiveM : rapport technique indicatif (aucune compatibilité garantie)."""
        session = self.session
        design = self.design()
        if session is None or design is None:
            return []
        try:
            root = self.engine.root_of(design, self.target())  # type: ignore[union-attr]
        except LoreError as exc:
            self.notify("Préparation FiveM", str(exc), "warning")
            return []
        nodes = session.scene.subtree(root)
        subtree = {n.id for n in nodes}
        issues = [
            i for i in compat.compatibility_report(session) if i.node_id is None or i.node_id in subtree
        ]
        report = [(i.level, f"FiveM — {i.message}") for i in issues if i.code != "wheels"]
        added = [n for n in nodes if n.extra.get("lore", {}).get("part")]
        if added:
            report.append(
                (
                    "warning",
                    f"FiveM — {len(added)} pièce(s) Lore ajoutée(s) hors hiérarchie d'os d'origine : "
                    "à rattacher à un os (chassis, bumper_f…) lors de l'export.",
                )
            )
        if any((m := session.scene.material_for(n.id)) is not None and m.is_emissive for n in nodes):
            report.append(
                (
                    "info",
                    "FiveM — matériaux émissifs : aperçu viewport uniquement ; l'éclairage en jeu "
                    "(shaders, carcols) reste à configurer.",
                )
            )
        triangles = sum(
            session.geometry_for(n).triangle_count
            for n in nodes
            if n.kind is NodeKind.MESH and session.geometry_for(n) is not None
        )
        report.append(
            ("info", f"FiveM — {triangles} triangles dans ce véhicule (LOD haut ; LOD inférieurs à créer).")
        )
        report.append(
            (
                "info",
                "Rapport indicatif : ni compatibilité FiveM ni jouabilité garanties ; "
                "export et essai en jeu indispensables.",
            )
        )
        self.last_report = report
        self.bottom.setCurrentWidget(self.diagnostics_panel)
        self.diagnostics_panel.refresh()
        return report

    def diagnostics(self) -> list[tuple[str, str]]:
        design = self.design()
        if self.engine is None or design is None:
            return []
        items: list[tuple[str, str]] = []
        try:
            state = self.engine.state(design, self.target())
            items += [("warning", w) for w in state.components.warnings]
            unclassified = [c.name for c in state.components.components if c.kind == "other"]
            if unclassified:
                items.append(
                    (
                        "info",
                        "Pièces non classées (renommez-les ou définissez leur type) : "
                        + ", ".join(unclassified[:8]),
                    )
                )
            emergency = state.components.of_kind("emergency")
            if emergency:
                items.append(
                    ("info", f"{len(emergency)} équipement(s) Emergency Studio conservé(s) dans ce véhicule.")
                )
            if state.components.of_kind("technical"):
                items.append(
                    (
                        "warning",
                        "Pièces techniques (collisions, LOD, os) non déformées : à régénérer pour FiveM.",
                    )
                )
        except EXPECTED as exc:
            items.append(("error", str(exc)))
        check = self.last_check or {}
        items += [("warning", f"Ignoré : {s}") for s in check.get("skipped", [])]
        items += [("warning", f"À vérifier : {i}") for i in check.get("impacts", [])]
        missing = provenance.incomplete(self.engine.provenance())
        if missing:
            items.append(
                ("info", f"Provenance : {len(missing)} ressource(s) sans licence ou sans source renseignée.")
            )
        return items + self.last_report

    # --- Transferts vers les autres studios ----------------------------------------------------------
    def _select_displayed(self, body_only: bool = False) -> bool:
        design = self.design()
        if design is None or self.session is None:
            self.notify("Transfert", "Créez d'abord un design.", "info")
            return False
        node_id = self.engine.root_of(design, self.target())  # type: ignore[union-attr]
        if body_only:
            body = self.engine.state(design, self.target()).components.of_kind("body")  # type: ignore[union-attr]
            if body:
                node_id = body[0].mesh_ids[0]
        self.session.selection.set([node_id])
        return True

    def transfer_to_editor(self) -> None:
        if self._select_displayed():
            self.editor_requested.emit()

    def transfer_to_livery(self) -> None:
        if self._select_displayed(body_only=True):
            self.livery_requested.emit()

    def transfer_to_emergency(self) -> None:
        if self._select_displayed():
            self.emergency_requested.emit()
