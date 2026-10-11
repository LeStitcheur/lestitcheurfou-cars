"""Fenêtre principale sans cadre : barre de titre, sidebar, pages et studio 3D."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QAction, QCloseEvent, QCursor, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMenu,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from lsfcars import APP_NAME
from lsfcars.core.logging_setup import get_logger
from lsfcars.core.paths import samples_dir
from lsfcars.importers import file_dialog_filter
from lsfcars.project import recent, recovery
from lsfcars.project.model import VehicleRole, VehicleType
from lsfcars.project.session import ProjectSession
from lsfcars.project.store import PROJECT_EXTENSION, ProjectError
from lsfcars.ui.design import apply_design, icons
from lsfcars.ui.design import tokens as t
from lsfcars.ui.design.components import LSModal, NotificationCenter, tooltip
from lsfcars.ui.design.sidebar import LSSidebar, NavEntry
from lsfcars.ui.design.topbar import LSTopbar
from lsfcars.ui.dialogs.new_project import NewProjectDialog, NewProjectRequest
from lsfcars.ui.import_studio.page import VehicleImportStudio
from lsfcars.ui.pages.dashboard import DashboardPage
from lsfcars.ui.pages.pages import (
    UPCOMING,
    DiagnosticsPage,
    MaterialsPage,
    ProjectsPage,
    SettingsPage,
    UpcomingPage,
)
from lsfcars.ui.settings import AppSettings
from lsfcars.ui.studio.controller import StudioController
from lsfcars.ui.studio.studio_page import StudioPage

log = get_logger(__name__)

SAMPLE_MODEL = "vehicule_test.glb"
SAMPLE_PROJECT_NAME = "Démo - Véhicule de test"
PROJECT_FILTER = f"Projets {APP_NAME} (*{PROJECT_EXTENSION})"
RESIZE_MARGIN = 6
UPCOMING_ICONS = {
    "liveries": "paint-bucket",
    "lspd": "shield",
    "ems": "ambulance",
    "configs": "sliders-horizontal",
    "ai": "sparkles",
    "lore": "scroll-text",
    "optimize": "gauge",
    "export": "package",
}


def nav_entries() -> list[NavEntry]:
    upcoming = {u.key: u for u in UPCOMING}

    def soon(key: str) -> NavEntry:
        info = upcoming[key]
        return NavEntry(key, info.title, UPCOMING_ICONS[key], info.section, True, info.summary)

    return [
        NavEntry("dashboard", "Vue d'ensemble", "layout-grid", "Accueil"),
        NavEntry("projects", "Mes projets", "folder", "Accueil"),
        NavEntry("recent", "Projets récents", "history", "Accueil"),
        NavEntry(
            "studio",
            "Vehicle Editor",
            "cuboid",
            "Création",
            tooltip="Modifier le véhicule : géométrie, carrosserie, roues, habitacle, ancrages",
        ),
        NavEntry(
            "import",
            "Vehicle Import Studio",
            "import",
            "Création",
            tooltip="Importer et inspecter un véhicule FiveM / GTA V",
        ),
        NavEntry(
            "library",
            "Bibliothèque",
            "blocks",
            "Création",
            tooltip="Composants 3D réutilisables (dans le Vehicle Editor)",
        ),
        NavEntry("materials", "Matériaux", "palette", "Création"),
        soon("liveries"),
        soon("lspd"),
        soon("ems"),
        soon("configs"),
        soon("ai"),
        soon("lore"),
        soon("optimize"),
        soon("export"),
        NavEntry("settings", "Paramètres", "settings", "Système"),
        NavEntry("diagnostics", "Diagnostics", "activity", "Système"),
    ]


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings | None = None) -> None:
        super().__init__()
        self.settings = settings or AppSettings()
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowTitle(APP_NAME)
        self.resize(1520, 920)
        self.setMinimumSize(1100, 680)
        self.controller = StudioController(self)
        self.controller.set_autosave_interval(self.settings.autosave_minutes)

        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.topbar = LSTopbar(self)
        outer.addWidget(self.topbar)
        body = QHBoxLayout()
        body.setSpacing(0)
        self.sidebar = LSSidebar(nav_entries())
        body.addWidget(self.sidebar)
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        outer.addLayout(body, 1)
        self.setCentralWidget(root)
        self.notifications = NotificationCenter(self)

        projects_dir = lambda: self.settings.projects_dir  # noqa: E731
        self.dashboard = DashboardPage(projects_dir)
        self.projects_page = ProjectsPage(projects_dir)
        self.recent_page = ProjectsPage(projects_dir, recent_only=True)
        self.studio = StudioPage(self.controller, self.settings)
        self.import_page = VehicleImportStudio(self.controller, self.ensure_project)
        self.materials_page = MaterialsPage(self.controller)
        self.settings_page = SettingsPage(self.settings)
        self.diagnostics_page = DiagnosticsPage()
        self.pages: dict[str, QWidget] = {
            "dashboard": self.dashboard,
            "projects": self.projects_page,
            "recent": self.recent_page,
            "studio": self.studio,
            "import": self.import_page,
            "materials": self.materials_page,
            "settings": self.settings_page,
            "diagnostics": self.diagnostics_page,
        }
        for info in UPCOMING:
            self.pages[info.key] = UpcomingPage(info)
        for page in self.pages.values():
            self.stack.addWidget(page)

        self._build_actions()
        self._connect()
        self.sidebar.set_collapsed(self.settings.sidebar_collapsed, animate=False)
        self.topbar.set_sidebar_collapsed(self.settings.sidebar_collapsed)
        geometry = self.settings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        self.navigate("dashboard")
        self._update_state()
        QApplication.instance().installEventFilter(self)
        log.info("Fenêtre principale prête")

    # --- Actions et raccourcis ------------------------------------------------
    def _action(
        self,
        text: str,
        slot,
        shortcut: str | QKeySequence.StandardKey | None = None,  # type: ignore[no-untyped-def]
        icon: str | None = None,
    ) -> QAction:
        action = QAction(text, self)
        if icon:
            action.setIcon(icons.icon(icon))
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        action.triggered.connect(lambda _=False: slot())
        self.addAction(action)
        return action

    def _build_actions(self) -> None:
        a = self._action
        ctl = self.controller
        self.act_new = a("Nouveau véhicule…", self.new_project, QKeySequence.StandardKey.New, "plus")
        self.act_open = a(
            "Ouvrir un projet…", self.open_project, QKeySequence.StandardKey.Open, "folder-open"
        )
        self.act_save = a("Enregistrer", self.save_project, QKeySequence.StandardKey.Save, "save")
        self.act_save_as = a("Enregistrer sous…", self.save_project_as, "Ctrl+Shift+S")
        self.act_import = a("Importer un modèle 3D…", self.import_model, "Ctrl+I", "import")
        self.act_close = a("Fermer le projet", self.close_project, "Ctrl+W")
        self.act_quit = a("Quitter", self.close, "Ctrl+Q")
        self.act_undo = a("Annuler", ctl.undo, QKeySequence.StandardKey.Undo, "undo-2")
        self.act_redo = a("Rétablir", ctl.redo, "Ctrl+Y", "redo-2")
        self.act_redo_alt = a("Rétablir", ctl.redo, "Ctrl+Shift+Z")
        self.act_duplicate = a("Dupliquer", ctl.duplicate_selected, "Ctrl+D", "copy-plus")
        self.act_delete = a("Supprimer", self.delete_selection, QKeySequence.StandardKey.Delete, "trash-2")
        self.act_group = a("Grouper", ctl.group_selected, "Ctrl+G", "group")
        self.act_ungroup = a("Dégrouper", ctl.ungroup_selected, "Ctrl+Shift+G", "ungroup")
        self.act_rename = a("Renommer", self._rename_active, "F2", "pencil")
        self.act_select_none = a("Désélectionner", lambda: ctl.select([]), "Escape")
        self.act_sidebar = a("Barre latérale", self.toggle_sidebar, "Ctrl+B")
        for action in (self.act_delete, self.act_rename, self.act_select_none):
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self.studio.addAction(action)
            self.removeAction(action)

        self.file_button = QToolButton()
        self.file_button.setText("Fichier")
        self.file_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        tooltip(self.file_button, "Projet, import et édition")
        menu = QMenu(self.file_button)
        for item in (
            self.act_new,
            self.act_open,
            None,
            self.act_save,
            self.act_save_as,
            None,
            self.act_import,
            None,
            self.act_undo,
            self.act_redo,
            self.act_duplicate,
            self.act_group,
            self.act_ungroup,
            self.act_delete,
            None,
            self.act_close,
            self.act_quit,
        ):
            menu.addSeparator() if item is None else menu.addAction(item)
        self.file_button.setMenu(menu)
        self.topbar.layout().insertWidget(4, self.file_button)

    def _connect(self) -> None:
        ctl = self.controller
        self.sidebar.navigate.connect(self.navigate)
        self.topbar.toggle_sidebar.connect(self.toggle_sidebar)
        self.topbar.settings_requested.connect(lambda: self.navigate("settings"))
        self.topbar.notifications_requested.connect(self._show_notifications)
        self.topbar.search_activated.connect(self._search)
        self.notifications.changed.connect(lambda: self.topbar.set_unread(self.notifications.unread))
        ctl.notify.connect(lambda title, msg, level: self.notify(title, msg, level, 1800))
        ctl.state_changed.connect(self._update_state)
        ctl.session_changed.connect(self._update_search)
        ctl.scene_changed.connect(lambda kind: self._update_search() if kind == "structure" else None)
        ctl.import_finished.connect(self._on_import_finished)
        for page in (self.dashboard, self.projects_page, self.recent_page):
            page.open_requested.connect(self.open_project)
            page.new_requested.connect(self.new_project)
        self.dashboard.import_requested.connect(self.import_model)
        self.dashboard.addon_requested.connect(lambda: self.navigate("import"))
        self.dashboard.studio_requested.connect(lambda: self.navigate("studio"))
        self.dashboard.projects_requested.connect(lambda: self.navigate("projects"))
        self.import_page.notify.connect(lambda title, msg, level: self.notify(title, msg, level))
        self.import_page.error.connect(self.error)
        self.import_page.imported.connect(self._on_resource_imported)
        self.settings_page.settings_changed.connect(self._on_setting)

    # --- Navigation ---------------------------------------------------------
    def current_page(self) -> str:
        widget = self.stack.currentWidget()
        if getattr(self, "_library_shown", False) and widget is self.studio:
            return "library"
        return next((k for k, p in self.pages.items() if p is widget), "dashboard")

    def navigate(self, key: str) -> None:
        if key == "library":  # la bibliothèque vit dans le Vehicle Editor (onglet de gauche)
            self.navigate("studio")
            self.studio.set_panel_visible("left", True)
            self.studio.left.setCurrentWidget(self.studio.library)
            self.sidebar.set_current("library")
            self._library_shown = True
            return
        self._library_shown = False
        page = self.pages.get(key)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        self.sidebar.set_current(key)
        refresh = getattr(page, "refresh", None)
        if callable(refresh) and key != "studio":
            refresh()

    def toggle_sidebar(self) -> None:
        self.sidebar.toggle()
        collapsed = self.sidebar.is_collapsed()
        self.settings.sidebar_collapsed = collapsed
        self.topbar.set_sidebar_collapsed(collapsed)

    def notify(self, title: str, message: str = "", level: str = "info", duration_ms: int = 4200) -> None:
        self.notifications.notify(title, message, level, duration_ms)

    def _show_notifications(self) -> None:
        menu = QMenu(self)
        if not self.notifications.history:
            menu.addAction("Aucune notification").setEnabled(False)
        for item in self.notifications.history[:12]:
            menu.addAction(
                f"{item.time.strftime('%H:%M')}  {item.title}"
                + (f" — {item.message[:60]}" if item.message else "")
            )
        menu.exec(self.topbar.bell.mapToGlobal(QPoint(0, self.topbar.bell.height())))
        self.notifications.mark_read()

    # --- Recherche ----------------------------------------------------------
    def _search_entries(self) -> dict[str, tuple[str, str]]:
        entries = {e.label: ("page", e.key) for e in nav_entries()}
        session = self.controller.session
        if session is not None:
            for node in session.scene.walk():
                entries.setdefault(f"Objet : {node.name}", ("node", node.id))
        return entries

    def _update_search(self) -> None:
        self.topbar.set_search_entries(sorted(self._search_entries()))

    def _search(self, text: str) -> None:
        entries = self._search_entries()
        match = entries.get(text) or next((v for k, v in entries.items() if text.lower() in k.lower()), None)
        if match is None:
            self.notify("Aucun résultat", f"Rien ne correspond à « {text} ».", "warning")
            return
        kind, value = match
        if kind == "page":
            self.navigate(value)
        else:
            self.navigate("studio")
            self.controller.select([value])
            self.frame_selection()

    # --- Projets ------------------------------------------------------------
    def maybe_save(self) -> bool:
        session = self.controller.session
        if session is None or not session.dirty:
            return True
        choice = LSModal.ask_save(self, session.project.name)
        if choice == "save":
            return self.save_project()
        return choice == "discard"

    def error(self, title: str, message: str) -> None:
        log.error("%s : %s", title, message)
        LSModal.error(self, title, message)

    def _set_session(self, session: ProjectSession | None) -> None:
        self.controller.set_session(session)
        if session is not None:
            recent.add_recent(session.file_path)
            self.navigate("studio")
        else:
            self.navigate("dashboard")
        self._update_state()

    def new_project(self, request: NewProjectRequest | None = None) -> bool:
        if not self.maybe_save():
            return False
        if request is None:
            dialog = NewProjectDialog(self.settings.projects_dir, self)
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
            self.error("Création du projet impossible", str(exc))
            return False
        self._set_session(session)
        self.notify("Projet créé", session.project.name, "success")
        return True

    def open_project(self, path: str | Path | None = None) -> bool:
        if not self.maybe_save():
            return False
        if path is None:
            start = self.settings.projects_dir
            selected, _ = QFileDialog.getOpenFileName(
                self, "Ouvrir un projet", str(start) if start.exists() else "", PROJECT_FILTER
            )
            if not selected:
                return False
            path = selected
        path = Path(path)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            session = ProjectSession.open(path)
        except ProjectError as exc:
            QApplication.restoreOverrideCursor()
            self.error("Ouverture du projet impossible", str(exc))
            if not path.is_file():
                recent.remove_recent(path)
            return False
        QApplication.restoreOverrideCursor()
        self._set_session(session)
        if session.missing_assets:
            self.notify(
                "Fichiers manquants",
                f"{len(session.missing_assets)} modèle(s) introuvable(s), voir le journal.",
                "warning",
                7000,
            )
        else:
            self.notify("Projet ouvert", session.project.name, "success")
        return True

    def _capture_thumbnail(self) -> None:
        session = self.controller.session
        viewport = self.studio.viewport
        if session is not None and viewport.gl_ready and viewport.isVisible():
            thumbnail = viewport.grab_thumbnail()
            if thumbnail:
                session.project.thumbnail = thumbnail

    def save_project(self) -> bool:
        session = self.controller.session
        if session is None:
            return False
        session.project.camera = self.studio.viewport.camera.to_state()
        self._capture_thumbnail()
        try:
            path = session.save()
        except ProjectError as exc:
            self.error("Enregistrement impossible", str(exc))
            return False
        recent.add_recent(path)
        self.controller.state_changed.emit()
        self.notify("Projet enregistré", path.name, "success", 2500)
        return True

    def save_project_as(self, parent_dir: str | Path | None = None, name: str | None = None) -> bool:
        session = self.controller.session
        if session is None:
            return False
        if parent_dir is None:
            folder = QFileDialog.getExistingDirectory(
                self, "Enregistrer sous : dossier parent", str(self.settings.projects_dir)
            )
            if not folder:
                return False
            parent_dir, name = folder, name or f"{session.project.name} (copie)"
        session.project.camera = self.studio.viewport.camera.to_state()
        self._capture_thumbnail()
        try:
            path = session.save_as(parent_dir, name or session.project.name)
        except ProjectError as exc:
            self.error("Enregistrement impossible", str(exc))
            return False
        recent.add_recent(path)
        self.controller.state_changed.emit()
        self.notify("Projet enregistré sous", str(path), "success")
        return True

    def close_project(self) -> bool:
        if self.controller.session is None:
            return True
        if not self.maybe_save():
            return False
        self._set_session(None)
        return True

    def open_sample_project(self) -> bool:
        sample = samples_dir() / SAMPLE_MODEL
        if not sample.is_file():
            self.error("Exemple introuvable", f"Le modèle d'exemple est absent : {sample}")
            return False
        parent = self.settings.projects_dir
        name, counter = SAMPLE_PROJECT_NAME, 2
        while (parent / name).exists():
            name, counter = f"{SAMPLE_PROJECT_NAME} ({counter})", counter + 1
        request = NewProjectRequest(
            name,
            parent,
            VehicleType.CAR,
            VehicleRole.CIVILIAN,
            "Projet de démonstration (véhicule de test libre de droits).",
        )
        if not self.new_project(request):
            return False
        self.controller.session.import_model(sample)
        self.frame_selection()
        return self.save_project()

    def check_recovery(self) -> bool:
        """Propose de restaurer une session interrompue (instantané de sauvegarde automatique)."""
        pending = recovery.pending()
        if not pending:
            return False
        info = pending[0]
        if not LSModal.confirm(
            self,
            "Récupération après interruption",
            f"Le projet « {info.name} » n'a pas été fermé correctement. "
            f"Restaurer la sauvegarde automatique du {info.saved_at_local} ?",
            "Restaurer",
        ):
            for item in pending:
                recovery.clear(item.project_id)
            return False
        try:
            session = ProjectSession.from_project(recovery.restore(info))
        except ProjectError as exc:
            self.error("Restauration impossible", str(exc))
            return False
        session.mark_dirty()
        self._set_session(session)
        self.notify("Projet restauré", "Pensez à l'enregistrer.", "warning", 6000)
        return True

    # --- Import -------------------------------------------------------------
    def import_model(self, path: str | Path | None = None) -> bool:
        if self.controller.session is None:
            if not LSModal.confirm(
                self,
                "Aucun projet ouvert",
                "Un projet est nécessaire pour importer un modèle. Créer un nouveau véhicule ?",
                "Créer",
            ):
                return False
            if not self.new_project():
                return False
        if path is None:
            selected, _ = QFileDialog.getOpenFileName(self, "Importer un modèle 3D", "", file_dialog_filter())
            if not selected:
                return False
            path = selected
        if self.controller.import_model_async(path) is None:
            self.notify("Import en cours", "Patientez jusqu'à la fin de l'import actuel.", "warning")
            return False
        self.navigate("studio")
        self.studio.bottom.setCurrentIndex(1)
        return True

    def _on_import_finished(self, ok: bool, message: str) -> None:
        if ok:
            self.notify("Modèle importé", message, "success")
            self.frame_selection()
        else:
            self.error("Import impossible", message)

    def ensure_project(self) -> bool:
        """Projet ouvert, ou création proposée (import depuis le Vehicle Import Studio)."""
        if self.controller.session is not None:
            return True
        if not LSModal.confirm(
            self,
            "Aucun projet ouvert",
            "Un projet est nécessaire pour importer ce véhicule. Créer un nouveau véhicule ?",
            "Créer",
        ):
            return False
        return self.new_project()

    def _on_resource_imported(self, root_id: str) -> None:
        self.navigate("studio")
        self.controller.select([root_id])
        self.frame_selection()

    # --- Édition --------------------------------------------------------------
    def delete_selection(self, confirm: bool = True) -> int:
        ids = self.controller.selected()
        if not ids:
            return 0
        if confirm and not LSModal.confirm(
            self,
            "Supprimer la sélection",
            f"Supprimer {len(ids)} élément(s) de la scène ? "
            "Les fichiers importés restent dans le projet, et "
            "l'action peut être annulée (Ctrl+Z).",
            "Supprimer",
            danger=True,
        ):
            return 0
        return self.controller.delete_selected()

    def frame_selection(self) -> None:
        self.studio.frame_selection()

    def _rename_active(self) -> None:
        session = self.controller.session
        if session and session.selection.active:
            item = self.studio.explorer.item_for(session.selection.active)
            if item is not None:
                self.studio.explorer.tree.editItem(item, 0)

    # --- État -----------------------------------------------------------------
    def _update_state(self) -> None:
        session = self.controller.session
        has = session is not None
        for action in (self.act_save, self.act_save_as, self.act_close):
            action.setEnabled(has)
        self.act_undo.setEnabled(has and session.stack.can_undo())
        self.act_redo.setEnabled(has and session.stack.can_redo())
        if session is None:
            self.topbar.set_project(None)
            self.setWindowTitle(APP_NAME)
            return
        state = "dirty" if session.dirty else "saved"
        if session.dirty and self.controller.last_autosave:
            state = "autosaved"
        self.topbar.set_project(session.project.name, state)
        self.setWindowTitle(f"{session.project.name}{' *' if session.dirty else ''} — {APP_NAME}")
        undo = session.stack.undo_label()
        self.act_undo.setText(f"Annuler {undo.lower()}" if undo else "Annuler")

    def _on_setting(self, key: str) -> None:
        if key == "compact":
            apply_design(QApplication.instance(), self.settings.compact)
            self.notify("Mode compact", "Certains espacements s'appliqueront au prochain démarrage.", "info")
        elif key == "autosave":
            self.controller.set_autosave_interval(self.settings.autosave_minutes)
        elif key == "layout_reset":
            self.studio.reset_layout()
            self.notify("Agencement réinitialisé", level="success")

    # --- Fenêtre sans cadre : redimensionnement par les bords -------------------
    def _edges(self, global_pos: QPoint) -> Qt.Edge:
        if self.isMaximized() or self.isFullScreen():
            return Qt.Edge(0)
        rect = self.frameGeometry()
        edges = Qt.Edge(0)
        if global_pos.x() - rect.left() <= RESIZE_MARGIN:
            edges |= Qt.Edge.LeftEdge
        if rect.right() - global_pos.x() <= RESIZE_MARGIN:
            edges |= Qt.Edge.RightEdge
        if global_pos.y() - rect.top() <= RESIZE_MARGIN:
            edges |= Qt.Edge.TopEdge
        if rect.bottom() - global_pos.y() <= RESIZE_MARGIN:
            edges |= Qt.Edge.BottomEdge
        return edges

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        etype = event.type()
        if (
            etype in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress)
            and isinstance(watched, QWidget)
            and watched.window() is self
        ):
            pos = QCursor.pos()
            edges = self._edges(pos)
            if etype == QEvent.Type.MouseMove and not event.buttons():
                shapes = {
                    Qt.Edge.LeftEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeFDiagCursor,
                    Qt.Edge.RightEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeFDiagCursor,
                    Qt.Edge.RightEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeBDiagCursor,
                    Qt.Edge.LeftEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeBDiagCursor,
                }
                if edges in shapes:
                    shape = shapes[edges]
                elif edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge):
                    shape = Qt.CursorShape.SizeHorCursor
                elif edges:
                    shape = Qt.CursorShape.SizeVerCursor
                else:
                    shape = None
                if shape is not None:
                    self.setCursor(shape)
                else:
                    self.unsetCursor()
            elif (
                etype == QEvent.Type.MouseButtonPress
                and edges
                and event.button() == Qt.MouseButton.LeftButton
            ):
                handle = self.windowHandle()
                if handle is not None and handle.startSystemResize(edges):
                    return True
        return super().eventFilter(watched, event)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if not self.maybe_save():
            event.ignore()
            return
        if self.controller.session is not None:
            self.controller.session.close()
        self.settings.set_value("window/geometry", self.saveGeometry())
        self.studio.save_layout()
        self.studio.bottom.log_panel.detach()
        self.import_page.shutdown()
        QApplication.instance().removeEventFilter(self)
        log.info("Fermeture de l'application")
        event.accept()


__all__ = ["MainWindow", "nav_entries", "t"]
