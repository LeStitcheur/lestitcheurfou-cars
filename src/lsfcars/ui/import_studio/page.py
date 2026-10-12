"""Vehicle Import Studio : analyse d'une ressource, inspection du véhicule, import dans le projet.

Disposition : fichiers et hiérarchie à gauche, viewport et outils d'inspection au centre,
informations, métadonnées et textures à droite, diagnostics, journal et progression en bas.
Toutes les opérations longues tournent dans un thread et sont annulables.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from lsfcars.core.logging_setup import get_logger
from lsfcars.fivem import gta_install, structure
from lsfcars.fivem.project_import import import_into_project
from lsfcars.fivem.resource import ResourceAnalysis, Status, analyze, stage_model
from lsfcars.fivem.sollumz import SollumzStatus, import_with_sollumz, probe
from lsfcars.importers.yft_importer import YftImporter
from lsfcars.project.session import ProjectSession
from lsfcars.project.store import ProjectError
from lsfcars.scene.inspection import exploded_offsets, offset_bounds
from lsfcars.ui.design import fonts
from lsfcars.ui.design.components import LSBadge, LSButton, LSIconButton, LSProgress, LSTabs, label, tooltip
from lsfcars.ui.import_studio.panels import (
    STATUS_TINTS,
    DiagnosticsList,
    FileInfoPanel,
    FileTree,
    FormatsPanel,
    HierarchyTree,
    KeyValueGrid,
    MetadataPanel,
    StatsTable,
    TextureInspector,
    VehiclePanel,
    human_size,
)
from lsfcars.ui.import_studio.workers import TaskWorker
from lsfcars.ui.panels.log_panel import LogPanel
from lsfcars.ui.viewport import Viewport3D

log = get_logger(__name__)
_task_ids = itertools.count(1)

INSPECTION_ICONS = {
    "complet": "car",
    "isole": "scan",
    "eclate": "maximize-2",
    "filaire": "grid-3x3",
    "materiaux": "palette",
    "bones": "move-3d",
    "ancrage": "frame",
    "statistiques": "gauge",
    "collisions": "shapes",
}


class BlenderPanel(QWidget):
    probe_requested = Signal()
    sollumz_import_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addWidget(label("Blender et Sollumz", "h3"))
        self.summary = label("Non détecté pour l'instant : cliquez sur « Détecter ».", "subtitle", wrap=True)
        layout.addWidget(self.summary)
        self.info = KeyValueGrid()
        layout.addWidget(self.info)
        row = QHBoxLayout()
        self.detect = LSButton("Détecter", "secondary", "search", True)
        self.detect.clicked.connect(self.probe_requested)
        self.sollumz_import = LSButton("Importer via Sollumz", "ghost", "import", True)
        self.sollumz_import.clicked.connect(self.sollumz_import_requested)
        self.sollumz_import.setEnabled(False)
        tooltip(self.sollumz_import, "Expérimental : nécessite Sollumz et un opérateur d'import détecté")
        row.addWidget(self.detect)
        row.addWidget(self.sollumz_import)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addWidget(
            label(
                "Les formats .yft, .ydr et .ytd sont décodés nativement par LeStitcheurFou Cars. "
                "Sollumz n'est utilisé qu'en solution de repli, s'il est installé. Son API n'étant "
                "pas stable, seuls les opérateurs réellement détectés sont proposés et un échec est "
                "signalé comme opération manuelle. L'export vers FiveM n'est pas encore disponible.",
                "faint",
                wrap=True,
            )
        )
        layout.addStretch(1)
        self.status: SollumzStatus | None = None

    def set_status(self, status: SollumzStatus) -> None:
        self.status = status
        self.summary.setText(status.summary())
        sollumz = (
            f"{status.sollumz_name} {status.sollumz_version}".strip()
            if status.sollumz_installed
            else "non installé"
        )
        self.info.set_rows(
            [
                ("Blender", status.blender_version or "introuvable"),
                ("Chemin", status.blender_path or "—"),
                ("Sollumz", sollumz),
                ("Opérateurs détectés", ", ".join(status.operators) or "aucun"),
                ("Import", "disponible" if status.can_import else "indisponible"),
                ("Export", "disponible" if status.can_export else "indisponible"),
            ]
        )
        self.sollumz_import.setEnabled(status.can_import)


class RpfBrowser(QDialog):
    """Archives RPF d'une installation GTA V : lisibles (non chiffrées) ou refusées."""

    def __init__(
        self, folder: Path, archives: list[gta_install.RpfInfo], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Archives de l'installation GTA V")
        self.resize(760, 520)
        self.selected: Path | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(label(str(folder), "h3"))
        readable = sum(a.readable for a in archives)
        layout.addWidget(
            label(
                f"{len(archives)} archive(s), dont {readable} lisible(s). Les archives chiffrées "
                "(AES / NG) proviennent de l'installation officielle : elles ne sont jamais déchiffrées.",
                "subtitle",
                wrap=True,
            )
        )
        self.list = QListWidget()
        for info in archives:
            shown = info.path.relative_to(folder) if info.path.is_relative_to(folder) else info.path
            item = QListWidgetItem(f"{shown}\n{info.status} · {human_size(info.size)}")
            item.setData(Qt.ItemDataRole.UserRole, str(info.path))
            if not info.readable:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.list.addItem(item)
        self.list.itemDoubleClicked.connect(self._accept)
        layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        close = LSButton("Fermer", "ghost")
        close.clicked.connect(self.reject)
        open_button = LSButton("Analyser l'archive", "primary", "search")
        open_button.clicked.connect(lambda: self._accept(self.list.currentItem()))
        row.addWidget(close)
        row.addWidget(open_button)
        layout.addLayout(row)

    def _accept(self, item: QListWidgetItem | None) -> None:
        if item is not None and item.flags() & Qt.ItemFlag.ItemIsEnabled:
            self.selected = Path(item.data(Qt.ItemDataRole.UserRole))
            self.accept()


class VehicleImportStudio(QWidget):
    notify = Signal(str, str, str)  # titre, message, niveau
    error = Signal(str, str)
    imported = Signal(str)  # identifiant du nœud racine importé
    model_import_requested = Signal(str)  # chemin local d'un modèle 3D standard
    analysis_finished = Signal(bool)
    preview_finished = Signal(bool)
    busy_changed = Signal(bool)

    def __init__(self, controller, ensure_project: Callable[[], bool]) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.setObjectName("LSPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.controller = controller
        self.ensure_project = ensure_project
        self.analysis: ResourceAnalysis | None = None
        self.preview_session: ProjectSession | None = None
        self.preview_result = None
        self.preview_key: tuple[str, bool] | None = None
        self.mode = "complet"
        self._worker: TaskWorker | None = None
        self._import_after_preview = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())

        self.files = FileTree()
        self.hierarchy = HierarchyTree()
        self.left = LSTabs()
        self.left.addTab(self.files, "Fichiers")
        self.left.addTab(self.hierarchy, "Hiérarchie")

        self.viewport = Viewport3D()
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        center_layout.addWidget(self._build_inspection_bar())
        center_layout.addWidget(self.viewport, 1)

        self.vehicle = VehiclePanel()
        self.file_info = FileInfoPanel()
        self.metadata = MetadataPanel()
        self.textures = TextureInspector()
        self.stats = StatsTable()
        self.blender = BlenderPanel()
        self.formats = FormatsPanel()
        self.right = LSTabs()
        for widget, title, tip in (
            (self.vehicle, "Véhicule", "Modèle, statut, informations et sélection"),
            (self.file_info, "Fichier", "Détails du fichier sélectionné"),
            (self.metadata, "Méta", "Métadonnées : vehicles, handling, carvariations, carcols…"),
            (self.textures, "Textures", "Inspecteur de textures"),
            (self.stats, "Stats", "Statistiques par pièce"),
            (self.blender, "Blender", "Blender et Sollumz"),
            (self.formats, "Formats", "Formats reconnus et réellement pris en charge"),
        ):
            index = self.right.addTab(widget, title)
            self.right.setTabToolTip(index, tip)

        self.diagnostics = DiagnosticsList()
        self.log_panel = LogPanel()
        self.bottom = LSTabs()
        self.bottom.addTab(self.diagnostics, "Diagnostics")
        self.bottom.addTab(self.log_panel, "Journal")

        for panel in (self.left, self.right, self.bottom):
            panel.setObjectName("LSStudioPanel")
            panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        for tabs in (self.left, self.right):
            tabs.tabBar().setUsesScrollButtons(True)
            tabs.tabBar().setElideMode(Qt.TextElideMode.ElideNone)
        self.left.setMinimumWidth(240)
        self.right.setMinimumWidth(360)

        self.h_split = QSplitter(Qt.Orientation.Horizontal)
        self.h_split.addWidget(self.left)
        self.h_split.addWidget(center)
        self.h_split.addWidget(self.right)
        self.h_split.setStretchFactor(1, 1)
        self.h_split.setSizes([290, 880, 430])
        self.v_split = QSplitter(Qt.Orientation.Vertical)
        self.v_split.addWidget(self.h_split)
        self.v_split.addWidget(self.bottom)
        self.v_split.setStretchFactor(0, 1)
        self.v_split.setSizes([700, 190])
        outer.addWidget(self.v_split, 1)
        outer.addWidget(self._build_progress())
        self._connect()
        self._refresh_actions()

    # --- Construction --------------------------------------------------------
    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("LSTopbar")
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(header)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(8)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        title = label("Vehicle Import Studio")
        title.setFont(fonts.brand_font(18, 600))
        texts.addWidget(title)
        self.subtitle = label(
            "Addons FiveM, ZIP, archives RPF non chiffrées, .yft / .ytd / .ybn / .meta, OBJ, FBX, glTF.",
            "subtitle",
        )
        texts.addWidget(self.subtitle)
        row.addLayout(texts, 1)
        self.overall = LSBadge("Aucune ressource")
        row.addWidget(self.overall)
        self.open_folder = LSButton("Dossier", "primary", "folder-open")
        self.open_zip = LSButton("ZIP", "secondary", "package")
        self.open_rpf = LSButton("RPF", "secondary", "package")
        self.open_files = LSButton("Fichier", "secondary", "file-box")
        self.open_gta = LSButton("Installation GTA V", "ghost", "search")
        tooltip(self.open_folder, "Analyser un dossier de ressource FiveM (ou d'addon)")
        tooltip(self.open_zip, "Analyser une ressource compressée (.zip)")
        tooltip(self.open_rpf, "Analyser une archive RPF non chiffrée (dlc.rpf d'addon…)")
        tooltip(self.open_files, "Analyser un fichier isolé (.yft, .ytd, .ybn, .meta, .obj, .fbx, .glb…)")
        tooltip(self.open_gta, "Lister les archives RPF de votre installation GTA V (lisibles ou chiffrées)")
        for button in (self.open_folder, self.open_zip, self.open_rpf, self.open_files, self.open_gta):
            row.addWidget(button)
        return header

    def _build_inspection_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("LSStudioPanel")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        # Ligne 1 : modes d'affichage + éclatement ; ligne 2 : modes d'analyse + outils
        display = QHBoxLayout()
        display.setSpacing(4)
        analysis = QHBoxLayout()
        analysis.setSpacing(4)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_buttons: dict[str, QPushButton] = {}
        for mode in structure.INSPECTION_MODES:
            display_mode = mode.key in ("complet", "isole", "eclate", "filaire", "materiaux")
            text = mode.label if mode.available else f"{mode.label} (non implémenté)"
            icon = INSPECTION_ICONS.get(mode.key) if display_mode else None
            button = LSButton(text, "ghost", icon, True)
            button.setCheckable(True)
            button.setProperty("chip", True)
            tooltip(button, mode.detail)
            button.setEnabled(mode.available)
            self.mode_group.addButton(button)
            self.mode_buttons[mode.key] = button
            button.clicked.connect(lambda _=False, key=mode.key: self.set_mode(key))
            row = display if display_mode else analysis
            row.addWidget(button)
        layout.addLayout(display)
        layout.addLayout(analysis)
        tools = display
        tools.addSpacing(10)
        tools.addWidget(label("Éclatement", "muted"))
        self.explode = QSlider(Qt.Orientation.Horizontal)
        self.explode.setRange(0, 100)
        self.explode.setMinimumWidth(110)
        self.explode.setMaximumWidth(220)
        self.explode.valueChanged.connect(self._explode_changed)
        tooltip(self.explode, "Écarte les pièces (affichage seulement : le modèle n'est pas modifié)")
        tools.addWidget(self.explode, 1)
        self.explode_value = label("0 %", "faint")
        self.explode_value.setFixedWidth(40)
        tools.addWidget(self.explode_value)
        tools.addStretch(1)
        analysis.addStretch(1)
        self.isolate_button = LSIconButton("scan")
        self.isolate_button.clicked.connect(self.isolate_selection)
        tooltip(self.isolate_button, "Isoler : n'afficher que la sélection (affichage seulement)")
        self.show_all_button = LSIconButton("eye")
        self.show_all_button.clicked.connect(self.show_all)
        tooltip(self.show_all_button, "Tout afficher")
        self.focus_button = LSIconButton("frame")
        self.focus_button.clicked.connect(self.focus_selection)
        tooltip(self.focus_button, "Recentrer la caméra sur la sélection")
        self.reset_button = LSIconButton("refresh-cw")
        self.reset_button.clicked.connect(self.reset_view)
        tooltip(self.reset_button, "Réinitialiser : vue assemblée, toutes les pièces, caméra par défaut")
        for button in (self.isolate_button, self.show_all_button, self.focus_button, self.reset_button):
            analysis.addWidget(button)
        self.mode_buttons["complet"].setChecked(True)
        return bar

    def _build_progress(self) -> QWidget:
        holder = QFrame()
        holder.setObjectName("LSStudioPanel")
        holder.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(holder)
        row.setContentsMargins(14, 6, 14, 8)
        self.progress = LSProgress()
        self.progress.reset("Prêt — glissez un dossier, un ZIP ou une archive RPF ici.")
        row.addWidget(self.progress, 1)
        self.cancel_button = LSButton("Annuler", "danger", "x", True)
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.hide()
        row.addWidget(self.cancel_button)
        return holder

    def _connect(self) -> None:
        self.open_folder.clicked.connect(self._choose_folder)
        self.open_zip.clicked.connect(lambda: self._choose_file("Ressource ZIP (*.zip)"))
        self.open_rpf.clicked.connect(lambda: self._choose_file("Archive RPF (*.rpf)"))
        self.open_files.clicked.connect(
            lambda: self._choose_file(
                "Fichiers de véhicule (*.yft *.ydr *.ytd *.ybn *.meta *.xml *.obj *.fbx *.glb *.gltf);;"
                "Tous les fichiers (*)"
            )
        )
        self.open_gta.clicked.connect(self._choose_gta_install)
        self.files.file_selected.connect(self.show_file)
        self.diagnostics.file_requested.connect(self._reveal_file)
        self.vehicle.preview_requested.connect(self.preview_model)
        self.vehicle.import_requested.connect(self.import_to_project)
        self.vehicle.model_import_requested.connect(self.import_generic_model)
        self.hierarchy.nodes_selected.connect(self._select_nodes)
        self.hierarchy.visibility_changed.connect(self._visibility_changed)
        self.stats.node_requested.connect(lambda node_id: self._select_nodes([node_id]))
        self.viewport.selection_requested.connect(self._viewport_selection)
        self.viewport.frame_requested.connect(self.focus_selection)
        self.textures.exported.connect(lambda path: self.notify.emit("Copie exportée", path, "success"))
        self.textures.failed.connect(lambda message: self.error.emit("Export impossible", message))
        self.blender.probe_requested.connect(self.probe_blender)
        self.blender.sollumz_import_requested.connect(self.import_with_sollumz)
        self.controller.session_changed.connect(self._refresh_actions)

    # --- Glisser-déposer -------------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        urls = [u for u in event.mimeData().urls() if u.isLocalFile()]
        if urls:
            self.analyze(urls[0].toLocalFile())

    # --- Choix de la source ----------------------------------------------------
    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Dossier de ressource FiveM")
        if folder:
            self.analyze(folder)

    def _choose_file(self, filters: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Ressource à analyser", "", filters)
        if path:
            self.analyze(path)

    def _choose_gta_install(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Dossier d'installation de GTA V (votre copie)")
        if not folder:
            return
        root = Path(folder)
        if not gta_install.is_gta_install(root):
            self.notify.emit(
                "Dossier sans GTA5.exe",
                "Ce dossier ne ressemble pas à une installation GTA V : ses archives sont listées.",
                "warning",
            )
        self._run(
            "Inventaire des archives",
            lambda progress, cancelled: gta_install.scan(root, cancelled),
            lambda archives: self._show_rpf_browser(root, archives),
        )

    def _show_rpf_browser(self, root: Path, archives: list[gta_install.RpfInfo]) -> None:
        if not archives:
            self.notify.emit("Aucune archive", "Aucun fichier .rpf trouvé dans ce dossier.", "warning")
            return
        dialog = RpfBrowser(root, archives, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected is not None:
            self.analyze(dialog.selected)

    # --- Tâches -------------------------------------------------------------------
    def is_busy(self) -> bool:
        return self._worker is not None

    def _run(self, label_text: str, job, on_success, on_failure=None) -> TaskWorker | None:  # type: ignore[no-untyped-def]
        if self._worker is not None:
            self.notify.emit("Tâche en cours", "Patientez ou annulez la tâche actuelle.", "warning")
            return None
        worker = TaskWorker(label_text, job, self)
        worker.progress.connect(lambda value, text: self.progress.set_progress(value, text))
        worker.succeeded.connect(lambda result: self._finish(worker, True, on_success, result))
        worker.failed.connect(lambda message: self._finish(worker, False, on_failure, message))
        worker.cancelled.connect(lambda: self._finish(worker, None, on_failure, None))
        self._worker = worker
        self.progress.set_busy(label_text)
        self.cancel_button.show()
        self.busy_changed.emit(True)
        worker.start()
        return worker

    def _finish(self, worker: TaskWorker, ok: bool | None, callback, value) -> None:  # type: ignore[no-untyped-def]
        worker.wait(10000)
        worker.deleteLater()
        if self._worker is worker:
            self._worker = None
        self.cancel_button.hide()
        self.busy_changed.emit(False)
        if ok is None:
            self.progress.reset(f"{worker.label} : annulé.")
            self.notify.emit("Opération annulée", worker.label, "warning")
            if callback is not None:
                callback(None)
            return
        if ok:
            self.progress.set_progress(1.0, f"{worker.label} : terminé.")
        else:
            self.progress.reset(f"{worker.label} : échec.")
            log.error("%s : %s", worker.label, value)
        if callback is not None:
            callback(value)
        elif not ok:
            self.error.emit(worker.label, str(value))

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.progress.set_busy("Annulation…")

    # --- Analyse ------------------------------------------------------------------
    def analyze(self, path: str | Path) -> TaskWorker | None:
        source = Path(path)
        return self._run(
            f"Analyse de {source.name}",
            lambda progress, cancelled: analyze(source, progress, cancelled),
            self._analysis_ready,
            self._analysis_failed,
        )

    def _analysis_failed(self, message: str | None) -> None:
        if message is not None:
            self.error.emit("Analyse impossible", message)
        self.analysis_finished.emit(False)

    def _analysis_ready(self, analysis: ResourceAnalysis) -> None:
        self._clear_preview()
        if self.analysis is not None:
            self.analysis.close()
        self.analysis = analysis
        overall = analysis.overall
        self.overall.setText(overall.label)
        self.overall.set_tint(STATUS_TINTS[overall])
        self.subtitle.setText(
            f"{analysis.name} — {len(analysis.files)} fichiers, {human_size(analysis.total_size)}"
        )
        self.files.set_analysis(analysis)
        self.vehicle.set_analysis(analysis)
        self.metadata.set_analysis(analysis)
        self.textures.set_analysis(analysis)
        self.diagnostics.set_analysis(analysis)
        self.file_info.show_file(None)
        self.left.setCurrentWidget(self.files)
        self.right.setCurrentWidget(self.vehicle)
        level = {Status.COMPATIBLE: "success", Status.ERROR: "error"}.get(overall, "warning")
        self.notify.emit("Analyse terminée", f"{analysis.name} : {overall.label.lower()}", level)
        self.analysis_finished.emit(True)

    def show_file(self, path: str) -> None:
        item = self.analysis.find(path) if self.analysis else None
        self.file_info.show_file(item)
        if item is None:
            return
        self.right.setCurrentWidget(self.file_info)
        if item.extension in (".meta", ".xml"):
            self.metadata.select_path(path)
        if item.extension in (".yft", ".ydr"):
            base = item.stem[:-3] if item.stem.lower().endswith("_hi") else item.stem
            self.vehicle.select_model(base)

    def _reveal_file(self, path: str) -> None:
        self.left.setCurrentWidget(self.files)
        self.files.select_path(path)
        self.show_file(path)

    # --- Aperçu du modèle --------------------------------------------------------
    def preview_model(self, name: str, high: bool = False) -> TaskWorker | None:
        analysis = self.analysis
        model = analysis.model(name) if analysis else None
        if analysis is None or model is None:
            return None
        number = next(_task_ids)

        def job(progress, cancelled):  # type: ignore[no-untyped-def]
            folder = analysis.temp_dir() / f"apercu_{number}"
            path = stage_model(analysis, model, folder / "source", high)
            progress(0.1, f"Décodage de {path.name}")
            result = YftImporter().load(path, lambda v, text: progress(0.1 + v * 0.7, text))
            if cancelled():
                return None
            progress(0.85, "Préparation de l'aperçu")
            session = ProjectSession.create(folder, "Apercu")
            session.apply_import(result)
            session.selection.clear()
            return result, session

        return self._run(
            f"Décodage de {name}{' (_hi)' if high else ''}",
            job,
            lambda value: self._preview_ready(value, (name, high)),
            self._preview_failed,
        )

    def _preview_failed(self, message: str | None) -> None:
        self._import_after_preview = False
        if message is not None:
            self.error.emit("Visualisation impossible", message)
        self.preview_finished.emit(False)

    def _preview_ready(self, value, key: tuple[str, bool]) -> None:  # type: ignore[no-untyped-def]
        if value is None:
            self._preview_failed(None)
            return
        result, session = value
        self._clear_preview()
        self.preview_session, self.preview_result, self.preview_key = session, result, key
        self.viewport.set_tool("select")
        self.viewport.set_session(session)
        self.hierarchy.set_session(session)
        self.stats.set_session(session)
        self.left.setCurrentWidget(self.hierarchy)
        self.reset_view()
        dims = session.dimensions()
        triangles, _vertices, meshes = session.stats()
        message = f"{triangles:,} triangles, {meshes} pièces".replace(",", " ")
        if dims is not None:
            message += f", {dims[0]:.2f} × {dims[1]:.2f} × {dims[2]:.2f} m"
        for warning in result.warnings:
            log.warning("%s : %s", key[0], warning)
        self.notify.emit("Modèle prêt", message, "success")
        self.preview_finished.emit(True)
        if self._import_after_preview:
            self._import_after_preview = False
            self.import_to_project()

    def _clear_preview(self) -> None:
        self.viewport.set_session(None)
        self.viewport.set_isolation(None)
        self.viewport.set_display_offsets({})
        self.hierarchy.set_session(None)
        self.stats.set_session(None)
        self.vehicle.show_selection([])
        self.preview_session = None
        self.preview_result = None
        self.preview_key = None

    # --- Sélection et inspection ---------------------------------------------------
    def _viewport_selection(self, ids: list, mode: str) -> None:
        session = self.preview_session
        if session is None:
            return
        if mode == "toggle":
            for node_id in ids:
                session.selection.toggle(node_id)
        elif mode == "add":
            session.selection.add(ids)
        else:
            session.selection.set(ids)
        self.hierarchy.select_ids(session.selection.ids)
        self._selection_changed()

    def _select_nodes(self, ids: list) -> None:
        session = self.preview_session
        if session is None:
            return
        session.selection.set([i for i in ids if i in session.scene])
        self._selection_changed()

    def select_parts(self, names: list[str]) -> list[str]:
        """Sélectionne les nœuds de l'aperçu portant ces noms (raccourci de test et de recherche)."""
        session = self.preview_session
        if session is None:
            return []
        wanted = {n.lower() for n in names}
        ids = [n.id for n in session.scene.walk() if n.name.lower() in wanted]
        self._select_nodes(ids)
        self.hierarchy.select_ids(ids)
        return ids

    def _selection_changed(self) -> None:
        session = self.preview_session
        self.viewport.update()
        if session is None or not session.selection.ids:
            self.vehicle.show_selection([])
            return
        node = session.scene.get(session.selection.active or session.selection.ids[0])
        category = structure.label(node.extra.get("category", structure.UNCLASSIFIED))
        rows = [("Pièce", node.name), ("Catégorie", category)]
        gta = node.extra.get("gta", {})
        if gta.get("role") == "bone":
            rows.append(("Os", f"index {gta.get('bone_index')}, étiquette {gta.get('bone_tag')}"))
            rows.append(("Pivot (repère GTA)", ", ".join(f"{v:.3f}" for v in gta.get("translation", []))))
        elif gta.get("role") == "geometry":
            rows.append(("Shader", gta.get("shader", "—")))
        dims = session.dimensions(session.selection.ids)
        if dims is not None:
            rows.append(("Dimensions", f"{dims[0]:.3f} × {dims[1]:.3f} × {dims[2]:.3f} m"))
        triangles, vertices, meshes = session.stats(session.selection.ids)
        rows.append(
            (
                "Géométrie",
                f"{triangles:,} triangles, {vertices:,} sommets, {meshes} maillage(s)".replace(",", " "),
            )
        )
        material = session.scene.material_for(node.id)
        if material is not None:
            texture = f" (texture {Path(material.texture).name})" if material.texture else ""
            rows.append(("Matériau", material.name + texture))
        self.vehicle.show_selection(rows)

    def _mesh_ids(self, node_ids: list[str]) -> set[str]:
        session = self.preview_session
        result: set[str] = set()
        if session is None:
            return result
        for node_id in node_ids:
            if node_id in session.scene:
                result.update(n.id for n in session.scene.subtree(node_id) if n.kind.value == "mesh")
        return result

    def set_mode(self, key: str) -> None:
        mode = next((m for m in structure.INSPECTION_MODES if m.key == key), None)
        if mode is None or not mode.available:
            return
        self.mode = key
        self.mode_buttons[key].setChecked(True)
        if key == "complet":
            self.explode.setValue(0)
            self.show_all()
            self.viewport.set_shading("material")
        elif key == "isole":
            self.isolate_selection()
        elif key == "eclate":
            if self.explode.value() == 0:
                self.explode.setValue(50)
        elif key == "filaire":
            self.viewport.set_shading("wireframe")
        elif key == "materiaux":
            self.viewport.set_shading("material")
        elif key == "bones":
            self.left.setCurrentWidget(self.hierarchy)
            self.hierarchy.set_mode("bones")
        elif key == "ancrage":
            self.left.setCurrentWidget(self.hierarchy)
            self.hierarchy.set_mode("anchors")
        elif key == "statistiques":
            self.right.setCurrentWidget(self.stats)

    def isolate_selection(self) -> None:
        session = self.preview_session
        if session is None:
            return
        ids = self._mesh_ids(session.selection.ids)
        if not ids:
            self.notify.emit("Isolation", "Sélectionnez d'abord une ou plusieurs pièces.", "warning")
            return
        self.viewport.set_isolation(ids)
        self.focus_selection()

    def show_all(self) -> None:
        self.viewport.set_isolation(None)
        self.hierarchy.set_all_checked()

    def _visibility_changed(self, ids: set[str]) -> None:
        session = self.preview_session
        total = sum(1 for _ in session.scene.mesh_nodes()) if session else 0
        self.viewport.set_isolation(None if len(ids) == total else set(ids))

    def set_explode(self, percent: int) -> None:
        self.explode.setValue(percent)

    def _explode_changed(self, value: int) -> None:
        self.explode_value.setText(f"{value} %")
        session = self.preview_session
        offsets = exploded_offsets(session, value / 100.0) if session is not None else {}
        self.viewport.set_display_offsets(offsets)
        if value > 0 and self.mode != "eclate":
            self.mode = "eclate"
            self.mode_buttons["eclate"].setChecked(True)

    def focus_selection(self) -> None:
        session = self.preview_session
        if session is None:
            return
        if session.selection.ids:
            targets = list(session.selection.ids)
        elif self.viewport.isolated is not None:
            targets = list(self.viewport.isolated)
        else:
            targets = [n.id for n in session.scene.children(None)]
        self.viewport.frame_bounds(offset_bounds(session, targets, self.viewport.display_offsets))

    def reset_view(self) -> None:
        self.explode.blockSignals(True)
        self.explode.setValue(0)
        self.explode.blockSignals(False)
        self.explode_value.setText("0 %")
        self.viewport.set_display_offsets({})
        self.viewport.set_isolation(None)
        self.viewport.set_shading("material")
        self.hierarchy.set_all_checked()
        self.mode = "complet"
        self.mode_buttons["complet"].setChecked(True)
        session = self.preview_session
        if session is not None:
            self.viewport.camera.set_view(-35, 12)
            self.viewport.frame_bounds(session.world_bounds())

    # --- Import dans le projet -----------------------------------------------------
    def _refresh_actions(self) -> None:
        session = self.controller.session
        self.textures.set_project_dir(session.project.project_dir if session is not None else None)

    def import_to_project(self) -> bool:
        """Importe le modèle courant (aperçu décodé d'abord si nécessaire)."""
        analysis = self.analysis
        model = self.vehicle.current_model()
        if analysis is None or model is None:
            return False
        if self.preview_result is None or self.preview_key != (model.name, False):
            self._import_after_preview = True
            self.preview_model(model.name, False)
            return False
        if not self.ensure_project():
            return False
        try:
            root_id, resource = import_into_project(
                self.controller.session, analysis, model, self.preview_result
            )
        except ProjectError as exc:
            self.error.emit("Import impossible", str(exc))
            return False
        self.controller.state_changed.emit()
        self._refresh_actions()
        copies = sum(1 for f in resource.manifest.get("files", []) if f.get("copy"))
        self.notify.emit(
            "Véhicule importé",
            f"{model.name} : {copies} fichier(s) copiés dans le projet, originaux intacts.",
            "success",
        )
        self.imported.emit(root_id)
        return True

    def import_generic_model(self, path: str) -> bool:
        """Modèle 3D standard (GLB, glTF, OBJ, FBX) : confié à l'import 3D de l'application."""
        item = self.analysis.find(path) if self.analysis is not None and path else None
        if item is None:
            return False
        try:
            local = self.analysis.local_model_path(item)
        except OSError as exc:
            self.error.emit("Import impossible", f"Extraction de {item.name} impossible : {exc}")
            return False
        self.model_import_requested.emit(str(local))
        return True

    # --- Blender / Sollumz -------------------------------------------------------
    def probe_blender(self) -> TaskWorker | None:
        return self._run(
            "Détection de Blender et Sollumz",
            lambda progress, cancelled: probe(lambda line: log.debug("Blender : %s", line)),
            self.blender.set_status,
        )

    def import_with_sollumz(self) -> TaskWorker | None:
        status = self.blender.status
        model = self.vehicle.current_model()
        analysis = self.analysis
        if status is None or not status.can_import or model is None or analysis is None:
            self.notify.emit("Sollumz indisponible", "Lancez d'abord la détection.", "warning")
            return None
        holder: dict = {}

        def job(progress, cancelled):  # type: ignore[no-untyped-def]
            folder = analysis.temp_dir() / f"sollumz_{next(_task_ids)}"
            source = stage_model(analysis, model, folder / "source")
            target = folder / f"{model.name}.glb"
            progress(0.2, "Import via Sollumz (Blender en arrière-plan)")
            import_with_sollumz(status, source, target, lambda task: holder.setdefault("task", task))
            return target

        worker = self._run(
            "Import via Sollumz",
            job,
            lambda path: self.notify.emit("Sollumz", f"Conversion réussie : {path}", "success"),
        )
        if worker is not None:
            worker.on_cancel = lambda: holder["task"].cancel() if "task" in holder else None
        return worker

    # --- Fermeture -------------------------------------------------------------------
    def shutdown(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._worker.wait(10000)
        self._clear_preview()
        if self.analysis is not None:
            self.analysis.close()
            self.analysis = None
        self.log_panel.detach()
