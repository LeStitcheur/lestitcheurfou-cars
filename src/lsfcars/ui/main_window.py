"""Fenêtre principale : navigation par ateliers, viewport central et panneaux ancrables."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from lsfcars import APP_NAME, REPO_URL, __version__
from lsfcars.core.logging_setup import get_logger
from lsfcars.core.paths import app_data_dir, default_projects_dir, logs_dir, samples_dir
from lsfcars.project import recent
from lsfcars.project.model import SceneObject, VehicleRole, VehicleType
from lsfcars.project.session import ProjectSession
from lsfcars.project.store import PROJECT_EXTENSION, ProjectError
from lsfcars.scene.loader import ModelLoadError, file_dialog_filter
from lsfcars.ui.dialogs.diagnostics import DiagnosticsDialog
from lsfcars.ui.dialogs.new_project import NewProjectDialog, NewProjectRequest
from lsfcars.ui.home_page import HomePage
from lsfcars.ui.panels.log_panel import LogPanel
from lsfcars.ui.panels.object_explorer import ObjectExplorer
from lsfcars.ui.panels.properties import PropertiesPanel
from lsfcars.ui.viewport import Viewport3D
from lsfcars.ui.workshop_page import WORKSHOPS, WorkshopPage

log = get_logger(__name__)

MODE_HOME = "home"
MODE_3D = "workshop3d"
NAV_LABELS = {
    MODE_HOME: "Accueil",
    MODE_3D: "Atelier 3D",
    "liveries": "Livrées",
    "emergency": "LSPD / EMS",
    "ai": "Génération IA",
    "export": "Export FiveM",
}
SAMPLE_MODEL = "vehicule_test.glb"
SAMPLE_PROJECT_NAME = "Démo - Véhicule de test"
PROJECT_FILTER = f"Projets {APP_NAME} (*{PROJECT_EXTENSION})"
USER_GUIDE_URL = f"{REPO_URL}/blob/main/docs/GUIDE_UTILISATEUR.md"


class _BusyCursor:
    """Curseur d'attente pendant une opération bloquante."""

    def __enter__(self) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

    def __exit__(self, *exc: object) -> None:
        QApplication.restoreOverrideCursor()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.session: ProjectSession | None = None
        self.setWindowTitle(APP_NAME)
        self.resize(1440, 900)
        self.setMinimumSize(1000, 640)

        self.viewport = Viewport3D()
        self.home_page = HomePage()
        self.workshop_pages = {info.key: WorkshopPage(info) for info in WORKSHOPS}
        self.explorer = ObjectExplorer()
        self.properties = PropertiesPanel()
        self.log_panel = LogPanel()

        self._build_central()
        self._build_docks()
        self._build_actions()
        self._build_menus()
        self._build_status_bar()
        self._connect()
        self._restore_settings()
        self._update_state()
        self.set_mode(MODE_HOME)
        log.info("Fenêtre principale prête")

    # --- Construction -------------------------------------------------------
    def _build_central(self) -> None:
        # Le rail de navigation vit dans une barre d'outils fixe pour rester à l'extérieur
        # des zones de panneaux ancrables.
        rail = QFrame()
        rail.setObjectName("NavRail")
        rail.setFixedWidth(176)
        rail.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(0, 0, 0, 0)
        rail_layout.setSpacing(0)
        title = QLabel("LSF CARS")
        title.setObjectName("NavTitle")
        version = QLabel(f"v{__version__}")
        version.setObjectName("NavVersion")
        rail_layout.addWidget(title)
        rail_layout.addWidget(version)

        self.stack = QStackedWidget()
        self._pages: dict[str, QWidget] = {}
        self._nav_buttons: dict[str, QPushButton] = {}
        self._nav_group = QButtonGroup(self)

        pages: list[tuple[str, QWidget, str]] = [
            (MODE_HOME, self.home_page, "Projets et démarrage"),
            (MODE_3D, self._build_viewport_page(), "Viewport et scène du projet"),
        ]
        pages += [(key, page, page.info.summary) for key, page in self.workshop_pages.items()]
        for key, page, tooltip in pages:
            button = QPushButton(NAV_LABELS[key])
            button.setObjectName("NavButton")
            button.setToolTip(tooltip)
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, k=key: self.set_mode(k))
            self._nav_group.addButton(button)
            rail_layout.addWidget(button)
            self._nav_buttons[key] = button
            self.stack.addWidget(page)
            self._pages[key] = page
            if key == MODE_3D:
                upcoming = QLabel("ATELIERS À VENIR")
                upcoming.setObjectName("NavVersion")
                upcoming.setContentsMargins(0, 16, 0, 0)
                rail_layout.addWidget(upcoming)
        rail_layout.addStretch(1)

        nav_bar = QToolBar("Navigation", self)
        nav_bar.setObjectName("NavToolBar")
        nav_bar.setMovable(False)
        nav_bar.setFloatable(False)
        nav_bar.toggleViewAction().setVisible(False)
        nav_bar.addWidget(rail)
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, nav_bar)
        self.setCentralWidget(self.stack)

    def _build_viewport_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        toolbar = QFrame()
        toolbar.setObjectName("ViewportToolbar")
        bar = QHBoxLayout(toolbar)
        bar.setContentsMargins(8, 4, 8, 4)
        bar.setSpacing(4)

        def tool(text: str, tip: str, slot: Callable[[], None]) -> QToolButton:
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            bar.addWidget(button)
            return button

        tool("Cadrer", "Cadrer la sélection ou toute la scène (F)", self.frame_view)
        bar.addSpacing(8)
        for label, view, key in (
            ("Avant", "front", "1"),
            ("Droite", "right", "3"),
            ("Dessus", "top", "7"),
            ("Perspective", "perspective", "5"),
        ):
            tool(
                label,
                f"Vue {label.lower()} ({key})",
                lambda v=view: self.viewport.set_standard_view(v),
            )
        bar.addSpacing(8)
        self.grid_button = tool("Grille", "Afficher / masquer la grille au sol", self._toggle_grid)
        self.grid_button.setCheckable(True)
        self.grid_button.setChecked(True)
        bar.addStretch(1)
        layout.addWidget(toolbar)
        layout.addWidget(self.viewport, 1)
        return page

    def _build_docks(self) -> None:
        self.explorer_dock = self._dock(
            "Explorateur d'objets",
            "ExplorerDock",
            self.explorer,
            Qt.DockWidgetArea.LeftDockWidgetArea,
        )
        self.properties_dock = self._dock(
            "Propriétés", "PropertiesDock", self.properties, Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.log_dock = self._dock(
            "Journal", "LogDock", self.log_panel, Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.explorer.setMinimumWidth(240)
        self.properties.setMinimumWidth(340)
        self.resizeDocks(
            [self.explorer_dock, self.properties_dock], [270, 340], Qt.Orientation.Horizontal
        )
        self.resizeDocks([self.log_dock], [170], Qt.Orientation.Vertical)

    def _dock(self, title: str, name: str, widget: QWidget, area: Qt.DockWidgetArea) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(name)
        dock.setWidget(widget)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.addDockWidget(area, dock)
        return dock

    def _action(
        self,
        text: str,
        slot: Callable[[], object],
        shortcut: QKeySequence | QKeySequence.StandardKey | str | None = None,
    ) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(lambda _=False: slot())
        return action

    def _build_actions(self) -> None:
        self.act_new = self._action(
            "&Nouveau projet…", self.new_project, QKeySequence.StandardKey.New
        )
        self.act_open = self._action(
            "&Ouvrir un projet…", self.open_project, QKeySequence.StandardKey.Open
        )
        self.act_save = self._action(
            "&Enregistrer", self.save_project, QKeySequence.StandardKey.Save
        )
        self.act_close = self._action("&Fermer le projet", self.close_project)
        self.act_import = self._action("&Importer un modèle 3D…", self.import_model, "Ctrl+I")
        self.act_sample = self._action("Projet d'e&xemple", self.open_sample_project)
        self.act_quit = self._action("&Quitter", self.close, QKeySequence.StandardKey.Quit)
        self.act_remove = self._action(
            "&Retirer l'objet sélectionné", self.remove_selected, QKeySequence.StandardKey.Delete
        )
        self.act_deselect = self._action(
            "&Désélectionner", lambda: self.select_object(None), "Escape"
        )
        self.act_frame = self._action("&Cadrer la sélection", self.frame_view, "F")
        self.act_reset_view = self._action("&Réinitialiser la vue", self._reset_view, "Home")
        self.act_grid = self._action("Afficher la &grille", self._toggle_grid)
        self.act_grid.setCheckable(True)
        self.act_grid.setChecked(True)
        self.act_guide = self._action("&Guide utilisateur", self._open_guide, "F1")
        self.act_diagnostics = self._action("&Diagnostics…", self.show_diagnostics)
        self.act_logs = self._action("Ouvrir le dossier des &logs", self._open_logs)
        self.act_about = self._action("À &propos", self._about)

    def _build_menus(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("&Fichier")
        file_menu.addActions([self.act_new, self.act_open])
        self.recent_menu = QMenu("Projets &récents", self)
        self.recent_menu.aboutToShow.connect(self._fill_recent_menu)
        file_menu.addMenu(self.recent_menu)
        file_menu.addAction(self.act_sample)
        file_menu.addSeparator()
        file_menu.addActions([self.act_save, self.act_close])
        file_menu.addSeparator()
        file_menu.addAction(self.act_import)
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)

        edit_menu = bar.addMenu("É&dition")
        edit_menu.addActions([self.act_remove, self.act_deselect])

        view_menu = bar.addMenu("&Affichage")
        view_menu.addActions([self.act_frame, self.act_reset_view, self.act_grid])
        view_menu.addSeparator()
        for dock in (self.explorer_dock, self.properties_dock, self.log_dock):
            view_menu.addAction(dock.toggleViewAction())

        help_menu = bar.addMenu("&Aide")
        help_menu.addActions([self.act_guide, self.act_diagnostics, self.act_logs])
        help_menu.addSeparator()
        help_menu.addAction(self.act_about)

    def _build_status_bar(self) -> None:
        self.status_project = QLabel("Aucun projet")
        self.status_scene = QLabel("")
        self.status_gl = QLabel("OpenGL : en attente")
        status = self.statusBar()
        status.addWidget(self.status_project)
        status.addWidget(self.status_scene)
        status.addPermanentWidget(self.status_gl)

    def _connect(self) -> None:
        self.home_page.new_requested.connect(self.new_project)
        self.home_page.open_requested.connect(self.open_project)
        self.home_page.sample_requested.connect(self.open_sample_project)
        self.explorer.selection_changed.connect(self.select_object)
        self.explorer.visibility_toggled.connect(self._set_visibility)
        self.explorer.delete_requested.connect(self.remove_object)
        self.explorer.frame_requested.connect(self._frame_object)
        self.explorer.import_requested.connect(self.import_model)
        self.properties.object_edited.connect(self._on_object_edited)
        self.properties.project_edited.connect(self._update_state)
        self.viewport.object_clicked.connect(self.select_object)
        self.viewport.frame_requested.connect(self.frame_view)
        self.viewport.gl_initialized.connect(self._on_gl_initialized)

    # --- Paramètres ---------------------------------------------------------
    def _settings(self) -> QSettings:
        return QSettings(str(app_data_dir() / "settings.ini"), QSettings.Format.IniFormat)

    def _restore_settings(self) -> None:
        settings = self._settings()
        geometry = settings.value("window/geometry")
        state = settings.value("window/state")
        if geometry is not None:
            self.restoreGeometry(geometry)
        if state is not None:
            self.restoreState(state)

    def _save_settings(self) -> None:
        settings = self._settings()
        settings.setValue("window/geometry", self.saveGeometry())
        settings.setValue("window/state", self.saveState())

    # --- Navigation ---------------------------------------------------------
    def current_mode(self) -> str:
        page = self.stack.currentWidget()
        return next((k for k, p in self._pages.items() if p is page), MODE_HOME)

    def set_mode(self, key: str) -> None:
        self.stack.setCurrentWidget(self._pages[key])
        self._nav_buttons[key].setChecked(True)
        in_3d = key == MODE_3D
        self.explorer_dock.setVisible(in_3d)
        self.properties_dock.setVisible(in_3d)
        if key == MODE_HOME:
            self.home_page.refresh_recent()

    # --- Projets ------------------------------------------------------------
    def maybe_save(self) -> bool:
        """Propose d'enregistrer les modifications. Retourne False si l'utilisateur annule."""
        if self.session is None or not self.session.dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Modifications non enregistrées",
            f"Le projet « {self.session.project.name} » a été modifié.\n"
            "Voulez-vous enregistrer les modifications ?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        return answer == QMessageBox.StandardButton.Discard

    def new_project(self, request: NewProjectRequest | None = None) -> bool:
        if not self.maybe_save():
            return False
        if request is None:
            dialog = NewProjectDialog(self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return False
            request = dialog.request()
        try:
            session = ProjectSession.create(
                request.parent_dir,
                request.name,
                request.vehicle_type,
                request.role,
                request.description,
            )
        except ProjectError as exc:
            self._error("Création du projet impossible", str(exc))
            return False
        self._set_session(session)
        return True

    def open_project(self, path: str | Path | None = None) -> bool:
        if not self.maybe_save():
            return False
        if path is None:
            start = default_projects_dir()
            selected, _ = QFileDialog.getOpenFileName(
                self, "Ouvrir un projet", str(start) if start.exists() else "", PROJECT_FILTER
            )
            if not selected:
                return False
            path = selected
        path = Path(path)
        try:
            with _BusyCursor():
                session = ProjectSession.open(path)
        except ProjectError as exc:
            self._error("Ouverture du projet impossible", str(exc))
            if not path.is_file():
                recent.remove_recent(path)
                self.home_page.refresh_recent()
            return False
        self._set_session(session)
        if session.missing:
            QMessageBox.warning(
                self,
                "Fichiers manquants",
                f"{len(session.missing)} objet(s) n'ont pas pu être chargés. "
                "Consultez le journal pour le détail.",
            )
        return True

    def save_project(self) -> bool:
        if self.session is None:
            return False
        self.session.project.camera = self.viewport.camera.to_state()
        try:
            path = self.session.save()
        except ProjectError as exc:
            self._error("Enregistrement impossible", str(exc))
            return False
        recent.add_recent(path)
        self.statusBar().showMessage(f"Projet enregistré : {path}", 5000)
        self.properties.refresh()
        self._update_state()
        return True

    def close_project(self) -> bool:
        if self.session is None:
            return True
        if not self.maybe_save():
            return False
        log.info("Projet fermé : %s", self.session.project.name)
        self._set_session(None)
        self.set_mode(MODE_HOME)
        return True

    def open_sample_project(self) -> bool:
        """Crée un projet de démonstration contenant le véhicule d'exemple."""
        sample = samples_dir() / SAMPLE_MODEL
        if not sample.is_file():
            self._error("Exemple introuvable", f"Le modèle d'exemple est absent : {sample}")
            return False
        parent = default_projects_dir()
        name, counter = SAMPLE_PROJECT_NAME, 2
        while (parent / name).exists():
            name = f"{SAMPLE_PROJECT_NAME} ({counter})"
            counter += 1
        request = NewProjectRequest(
            name,
            parent,
            VehicleType.CAR,
            VehicleRole.CIVILIAN,
            "Projet de démonstration créé avec le véhicule de test libre de droits.",
        )
        if not self.new_project(request):
            return False
        return self.import_model(sample) is not None and self.save_project()

    def _set_session(self, session: ProjectSession | None) -> None:
        self.session = session
        self.viewport.clear()
        self.viewport.camera.reset()
        if session is not None:
            for obj in session.project.objects:
                self.viewport.set_object(obj.id, session.meshes.get(obj.id, []))
                self._sync_object(obj.id)
            if session.project.camera:
                self.viewport.camera.apply_state(session.project.camera)
            else:
                self.viewport.frame_bounds(session.world_bounds())
            recent.add_recent(session.file_path)
            self.set_mode(MODE_3D)
        self.explorer.set_session(session)
        self.properties.set_session(session)
        self.home_page.refresh_recent()
        self._update_state()

    # --- Objets -------------------------------------------------------------
    def import_model(self, path: str | Path | None = None) -> SceneObject | None:
        if self.session is None:
            answer = QMessageBox.question(
                self,
                "Aucun projet ouvert",
                "Un projet est nécessaire pour importer un modèle.\nCréer un nouveau projet ?",
            )
            if answer != QMessageBox.StandardButton.Yes or not self.new_project():
                return None
        session = self.session
        assert session is not None
        if path is None:
            selected, _ = QFileDialog.getOpenFileName(
                self, "Importer un modèle 3D", "", file_dialog_filter()
            )
            if not selected:
                return None
            path = selected
        try:
            with _BusyCursor():
                obj = session.add_model(path)
        except (ModelLoadError, ProjectError) as exc:
            self._error("Import impossible", str(exc))
            return None
        self.viewport.set_object(obj.id, session.meshes[obj.id])
        self._sync_object(obj.id)
        self.explorer.refresh()
        self.select_object(obj.id)
        if len(session.project.objects) == 1:
            self.viewport.frame_bounds(session.world_bounds())
        self.set_mode(MODE_3D)
        self._update_state()
        return obj

    def remove_selected(self) -> None:
        object_id = self.explorer.selected_id()
        if object_id:
            self.remove_object(object_id)

    def remove_object(self, object_id: str, confirm: bool = True) -> None:
        if self.session is None:
            return
        obj = self.session.project.find_object(object_id)
        if obj is None:
            return
        if confirm:
            answer = QMessageBox.question(
                self,
                "Retirer l'objet",
                f"Retirer « {obj.name} » de la scène ?\n"
                "Le fichier reste dans le dossier assets du projet.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.session.remove_object(object_id)
        self.viewport.remove_object(object_id)
        self.explorer.refresh()
        self.select_object(None)
        self._update_state()

    def select_object(self, object_id: str | None) -> None:
        if object_id is not None and (
            self.session is None or self.session.project.find_object(object_id) is None
        ):
            object_id = None
        self.viewport.set_selected(object_id)
        self.explorer.select(object_id, emit=False)
        self.properties.show_object(object_id)

    def _sync_object(self, object_id: str) -> None:
        if self.session is None:
            return
        obj = self.session.project.find_object(object_id)
        if obj is not None:
            self.viewport.set_object_state(obj.id, obj.transform.matrix(), obj.visible)

    def _set_visibility(self, object_id: str, visible: bool) -> None:
        if self.session is None:
            return
        self.session.set_visible(object_id, visible)
        self._sync_object(object_id)
        self.explorer.refresh()
        if self.properties.current_object_id() == object_id:
            self.properties.refresh()
        self._update_state()

    def _on_object_edited(self, object_id: str) -> None:
        self._sync_object(object_id)
        self.explorer.refresh()
        self._update_state()

    # --- Vue ----------------------------------------------------------------
    def frame_view(self) -> None:
        if self.session is None:
            self.viewport.frame_bounds(None)
            return
        selected = self.explorer.selected_id()
        bounds = self.session.world_bounds([selected]) if selected else None
        self.viewport.frame_bounds(bounds or self.session.world_bounds())

    def _frame_object(self, object_id: str) -> None:
        if self.session is not None:
            self.select_object(object_id)
            self.viewport.frame_bounds(self.session.world_bounds([object_id], only_visible=False))

    def _reset_view(self) -> None:
        self.viewport.set_standard_view("perspective")
        self.frame_view()

    def _toggle_grid(self) -> None:
        visible = not self.viewport.grid_visible()
        self.viewport.set_grid_visible(visible)
        self.act_grid.setChecked(visible)
        self.grid_button.setChecked(visible)

    def _on_gl_initialized(self, ok: bool, detail: str) -> None:
        self.status_gl.setText(f"OpenGL : {detail}" if ok else "OpenGL : indisponible")
        self.status_gl.setToolTip(detail)

    # --- État ---------------------------------------------------------------
    def _update_state(self) -> None:
        session = self.session
        for action in (self.act_save, self.act_close):
            action.setEnabled(session is not None)
        self.act_remove.setEnabled(session is not None and bool(session.project.objects))
        if session is None:
            self.setWindowTitle(APP_NAME)
            self.status_project.setText("Aucun projet")
            self.status_scene.setText("")
            return
        marker = " *" if session.dirty else ""
        self.setWindowTitle(f"{session.project.name}{marker} — {APP_NAME}")
        self.status_project.setText(
            f"{session.project.name} · {session.project.vehicle_type.label}{marker}"
        )
        triangles, _ = session.stats()
        self.status_scene.setText(
            f"{len(session.project.objects)} objet(s) · {triangles:,} triangles".replace(",", " ")
        )

    def _fill_recent_menu(self) -> None:
        self.recent_menu.clear()
        paths = recent.list_recent()
        if not paths:
            self.recent_menu.addAction("(aucun)").setEnabled(False)
            return
        for path in paths:
            action = self.recent_menu.addAction(f"{path.stem}  —  {path}")
            action.setEnabled(path.is_file())
            action.triggered.connect(lambda _=False, p=path: self.open_project(p))
        self.recent_menu.addSeparator()
        self.recent_menu.addAction("Vider la liste").triggered.connect(self._clear_recent)

    def _clear_recent(self) -> None:
        recent.clear_recent()
        self.home_page.refresh_recent()

    # --- Aide ---------------------------------------------------------------
    def show_diagnostics(self) -> None:
        DiagnosticsDialog(self).exec()

    def _open_guide(self) -> None:
        QDesktopServices.openUrl(QUrl(USER_GUIDE_URL))

    def _open_logs(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(logs_dir())))

    def _about(self) -> None:
        QMessageBox.about(
            self,
            f"À propos de {APP_NAME}",
            f"<h3>{APP_NAME} {__version__}</h3>"
            "<p>Atelier de création et d'adaptation de véhicules Lore Friendly pour FiveM.</p>"
            f"<p><a href='{REPO_URL}'>{REPO_URL}</a></p>"
            "<p>Projet non affilié à Rockstar Games ni à Take-Two Interactive.</p>",
        )

    def _error(self, title: str, message: str) -> None:
        log.error("%s : %s", title, message)
        QMessageBox.critical(self, title, message)

    # --- Fermeture ----------------------------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if not self.maybe_save():
            event.ignore()
            return
        self._save_settings()
        self.log_panel.detach()
        log.info("Fermeture de l'application")
        event.accept()
