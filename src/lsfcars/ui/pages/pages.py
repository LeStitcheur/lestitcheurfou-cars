"""Pages secondaires : projets, import, matériaux, ateliers à venir, paramètres, diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSpinBox,
)

from lsfcars.core import diagnostics
from lsfcars.core.paths import logs_dir
from lsfcars.importers.registry import IMPORTERS
from lsfcars.project import recent
from lsfcars.ui.design.components import (
    LSBadge,
    LSButton,
    LSCard,
    LSEmptyState,
    LSInput,
    label,
)
from lsfcars.ui.pages.base import Page, ProjectGrid, known_projects
from lsfcars.ui.settings import AppSettings
from lsfcars.ui.studio.controller import StudioController
from lsfcars.ui.studio.panels import MaterialEditor


class ProjectsPage(Page):
    """« Mes projets » (dossier de projets) ou « Projets récents » (historique)."""

    open_requested = Signal(object)
    new_requested = Signal()

    def __init__(self, projects_dir: Callable[[], Path], recent_only: bool = False) -> None:
        title = "Projets récents" if recent_only else "Mes projets"
        subtitle = (
            "Les derniers projets ouverts sur ce poste."
            if recent_only
            else "Tous les projets de ton dossier de travail."
        )
        super().__init__(["Espace personnel", title], title, subtitle)
        self._projects_dir = projects_dir
        self.recent_only = recent_only
        open_button = LSButton("Ouvrir…", "secondary", "folder-open")
        open_button.clicked.connect(lambda: self.open_requested.emit(None))
        new = LSButton("Nouveau véhicule", "primary", "plus")
        new.clicked.connect(self.new_requested)
        self.header.actions.addWidget(open_button)
        self.header.actions.addWidget(new)
        self.location = label("", "faint")
        self.body.addWidget(self.location)
        if recent_only:
            self.list = QListWidget()
            self.list.setMinimumHeight(320)
            self.list.itemActivated.connect(lambda item: self.open_requested.emit(Path(item.toolTip())))
            card = LSCard("Historique", "history")
            card.body.addWidget(self.list)
            clear = LSButton("Vider l'historique", "ghost", "trash-2", True)
            clear.clicked.connect(self._clear)
            card.header_actions.addWidget(clear)
            self.body.addWidget(card)
        else:
            self.grid = ProjectGrid()
            self.body.addWidget(self.grid)
        self.finish()
        self.refresh()

    def _clear(self) -> None:
        recent.clear_recent()
        self.refresh()

    def refresh(self) -> None:
        if self.recent_only:
            self.list.clear()
            for path in recent.list_recent():
                exists = path.is_file()
                item = QListWidgetItem(f"{path.stem}{'' if exists else '  (introuvable)'}\n{path.parent}")
                item.setToolTip(str(path))
                if not exists:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                self.list.addItem(item)
            self.location.setText(f"{self.list.count()} projet(s) dans l'historique")
            return
        folder = self._projects_dir()
        empty = LSEmptyState(
            "folder",
            "Aucun projet trouvé",
            f"Les nouveaux projets sont créés dans {folder}.",
            ("Nouveau véhicule", self.new_requested.emit),
        )
        self.grid.set_projects(known_projects(folder), lambda p: self.open_requested.emit(Path(p)), empty)
        self.location.setText(f"Dossier : {folder}")


class MaterialsPage(Page):
    def __init__(self, controller: StudioController) -> None:
        super().__init__(
            ["Création", "Matériaux"],
            "Matériaux",
            "Couleur, rugosité, métallicité, opacité et textures du projet ouvert.",
        )
        card = LSCard("Éditeur de matériaux", "palette")
        self.editor = MaterialEditor(controller)
        card.body.addWidget(self.editor)
        self.body.addWidget(card)
        self.body.addWidget(
            label(
                "Astuce : sélectionne des pièces dans le Studio 3D puis "
                "« Affecter à la sélection ». L'aperçu en direct est visible "
                "dans le viewport en mode Matériaux.",
                "faint",
                wrap=True,
            )
        )
        self.finish()
        for signal in (controller.session_changed, controller.selection_changed):
            signal.connect(self.editor.refresh)
        controller.scene_changed.connect(lambda _k: self.editor.refresh())
        self.editor.refresh()


@dataclass(frozen=True)
class Upcoming:
    key: str
    section: str
    title: str
    summary: str
    planned: tuple[str, ...]


UPCOMING: tuple[Upcoming, ...] = (
    Upcoming(
        "liveries",
        "Création",
        "Livrées",
        "Création et personnalisation des livrées appliquées sur la carrosserie.",
        (
            "Calques de couleurs, logos, textes et motifs",
            "Gabarits UV par véhicule",
            "Aperçu en direct et export des textures FiveM",
        ),
    ),
    Upcoming(
        "configs",
        "Personnalisation",
        "Configurations",
        "Variantes d'un même véhicule (civil, service, extras).",
        ("Extras et modkits", "Variantes de couleurs", "Gestion des déclinaisons"),
    ),
    Upcoming(
        "ai",
        "Outils",
        "Intelligence artificielle",
        "Propositions 3D générées à partir d'images de référence.",
        (
            "Adaptateurs IA locale et cloud interchangeables",
            "Clés API hors du dépôt (coffre Windows)",
            "File de génération et historique",
        ),
    ),
    Upcoming(
        "lore",
        "Outils",
        "Lore Friendly",
        "Adaptation des véhicules à l'univers de Los Santos.",
        ("Retrait des marques réelles", "Noms et badges fictifs", "Contrôle de conformité"),
    ),
    Upcoming(
        "optimize",
        "Outils",
        "Optimisation",
        "Allègement des modèles pour un usage en jeu.",
        ("Décimation et LOD", "Fusion des matériaux", "Rapport de polygones"),
    ),
    Upcoming(
        "export",
        "Outils",
        "Export FiveM",
        "Préparation d'une ressource FiveM prête à l'emploi.",
        ("fxmanifest.lua et métadonnées", "Conversion via Blender", "Contrôles avant publication"),
    ),
)


class UpcomingPage(Page):
    def __init__(self, info: Upcoming) -> None:
        super().__init__([info.section, info.title], info.title, info.summary)
        self.info = info
        self.badge = LSBadge("Bientôt — non disponible dans la v0.2.0", "amber")
        self.header.actions.addWidget(self.badge)
        card = LSCard("Fonctions prévues", "sparkles")
        for feature in info.planned:
            card.body.addWidget(label(f"•  {feature}"))
        self.body.addWidget(card)
        self.body.addWidget(
            label(
                "Cet espace n'est pas encore implémenté : aucune action n'est "
                "disponible ici. Suis l'avancement dans le CHANGELOG.",
                "faint",
                wrap=True,
            )
        )
        self.finish()


class SettingsPage(Page):
    settings_changed = Signal(str)  # clé modifiée

    def __init__(self, settings: AppSettings) -> None:
        super().__init__(
            ["Système", "Paramètres"], "Paramètres", "Interface, projets, outils externes et rendu."
        )
        self.settings = settings
        ui_card = LSCard("Interface", "layout-grid")
        self.compact = QCheckBox("Mode interface compacte (espacements réduits)")
        self.compact.setChecked(settings.compact)
        self.compact.toggled.connect(self._compact)
        reset = LSButton("Réinitialiser l'agencement des panneaux", "ghost", "refresh-cw", True)
        reset.clicked.connect(lambda: self.settings_changed.emit("layout_reset"))
        ui_card.body.addWidget(self.compact)
        ui_card.body.addWidget(reset)
        self.body.addWidget(ui_card)

        projects = LSCard("Projets", "folder")
        form = QFormLayout()
        self.autosave = QSpinBox()
        self.autosave.setRange(0, 60)
        self.autosave.setSuffix(" min")
        self.autosave.setSpecialValueText("Désactivée")
        self.autosave.setValue(settings.autosave_minutes)
        self.autosave.valueChanged.connect(self._autosave)
        folder_row = QHBoxLayout()
        self.folder = LSInput()
        self.folder.setReadOnly(True)
        self.folder.setText(str(settings.projects_dir))
        browse = LSButton("Parcourir…", "secondary", small=True)
        browse.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse)
        form.addRow(label("Sauvegarde automatique", "muted"), self.autosave)
        form.addRow(label("Dossier des projets", "muted"), folder_row)
        projects.body.addLayout(form)
        self.body.addWidget(projects)

        tools = LSCard("Outils externes", "settings")
        blender_row = QHBoxLayout()
        self.blender = LSInput("Détection automatique")
        self.blender.setText(settings.blender_path)
        self.blender.editingFinished.connect(self._blender)
        choose = LSButton("Choisir…", "secondary", small=True)
        choose.clicked.connect(self._browse_blender)
        blender_row.addWidget(self.blender, 1)
        blender_row.addWidget(choose)
        tools.body.addWidget(label("Blender (import FBX)", "muted"))
        tools.body.addLayout(blender_row)
        self.blender_status = label("", "faint", wrap=True)
        tools.body.addWidget(self.blender_status)
        self.body.addWidget(tools)

        render = LSCard("Rendu 3D", "cuboid")
        self.software = QCheckBox("Forcer le rendu OpenGL logiciel (après redémarrage)")
        self.software.setChecked(settings.software_gl)
        self.software.toggled.connect(lambda v: setattr(self.settings, "software_gl", v))
        render.body.addWidget(self.software)
        render.body.addWidget(label("À activer uniquement si le pilote graphique pose problème.", "faint"))
        self.body.addWidget(render)
        self.finish()
        self._update_blender_status()

    def _compact(self, value: bool) -> None:
        self.settings.compact = value
        self.settings_changed.emit("compact")

    def _autosave(self, value: int) -> None:
        self.settings.autosave_minutes = value
        self.settings_changed.emit("autosave")

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Dossier des projets", self.folder.text())
        if folder:
            self.settings.projects_dir = folder
            self.folder.setText(folder)
            self.settings_changed.emit("projects_dir")

    def _browse_blender(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Emplacement de blender.exe", "", "Blender (blender.exe)")
        if path:
            self.blender.setText(path)
            self._blender()

    def _blender(self) -> None:
        from lsfcars.importers.fbx_blender import set_blender_path

        self.settings.blender_path = self.blender.text().strip()
        set_blender_path(self.settings.blender_path)
        self._update_blender_status()
        self.settings_changed.emit("blender")

    def _update_blender_status(self) -> None:
        from lsfcars.importers.fbx_blender import FbxBlenderImporter

        ok, reason = FbxBlenderImporter().available()
        self.blender_status.setText(("✓ " if ok else "✗ ") + reason)


class DiagnosticsPage(Page):
    def __init__(self) -> None:
        super().__init__(
            ["Système", "Diagnostics"],
            "Diagnostics",
            "Informations techniques à joindre aux signalements de bug.",
        )
        copy = LSButton("Copier le rapport", "primary", "copy")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.report.toPlainText()))
        logs = LSButton("Dossier des logs", "secondary", "folder-open")
        logs.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(logs_dir()))))
        refresh = LSButton("Actualiser", "secondary", "refresh-cw")
        refresh.clicked.connect(self.refresh)
        for button in (refresh, logs, copy):
            self.header.actions.addWidget(button)
        card = LSCard("Rapport", "activity")
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setMinimumHeight(420)
        font = QFont("Cascadia Mono")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.report.setFont(font)
        card.body.addWidget(self.report)
        self.body.addWidget(card)
        self.finish()
        self.refresh()

    def refresh(self) -> None:
        lines = []
        for importer in IMPORTERS:
            ok, reason = importer.available()
            state = "disponible" if ok else "indisponible"
            lines.append(f"  {', '.join(importer.extensions)} : {state} ({reason})")
        self.report.setPlainText(diagnostics.format_report() + "\n\n[Importateurs]\n" + "\n".join(lines))
