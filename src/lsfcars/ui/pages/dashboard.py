"""Tableau de bord « Bienvenue dans ton garage »."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPaintEvent, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from lsfcars.core.paths import resources_dir
from lsfcars.ui.design import fonts
from lsfcars.ui.design import tokens as t
from lsfcars.ui.design.components import (
    LSButton,
    LSEmptyState,
    LSStatsGrid,
    StatSpec,
    heading,
    label,
)
from lsfcars.ui.pages.base import Page, ProjectGrid, known_projects, relative_date, section_title

FRENCH_MONTHS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


class HeroVisual(QWidget):
    """Visuel automobile de la bannière : rendu du véhicule de test (aucune image tierce)."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(260)
        path = resources_dir() / "brand" / "hero_vehicle.png"
        self.pixmap = QPixmap(str(path)) if path.is_file() else QPixmap()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(rect.adjusted(-20, 1, -1, -1), 13, 13)
        painter.setClipPath(clip)
        painter.fillRect(rect, QColor(t.BG_RAISED))
        if not self.pixmap.isNull():
            scaled = self.pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(
                (self.width() - scaled.width()) // 2, (self.height() - scaled.height()) // 2, scaled
            )
        edge = QColor(t.PANEL)
        left = QLinearGradient(0, 0, self.width() * 0.35, 0)
        left.setColorAt(0, edge)
        edge.setAlpha(0)
        left.setColorAt(1, edge)
        painter.fillRect(rect, left)
        bottom = QLinearGradient(0, self.height(), 0, self.height() * 0.45)
        shade = QColor(t.BG)
        shade.setAlpha(235)
        bottom.setColorAt(0, shade)
        shade.setAlpha(0)
        bottom.setColorAt(1, shade)
        painter.fillRect(rect, bottom)
        painter.setPen(QColor(t.TEXT))
        painter.setFont(fonts.brand_font(26, 600, 0.5))
        painter.drawText(
            QRectF(28, self.height() - 62, self.width() - 56, 36),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "LeStitcheurFou Cars",
        )
        painter.setPen(QColor(t.ACCENT_2))
        painter.setFont(fonts.font(9, 600, 1.4, caps=True))
        painter.drawText(
            QRectF(28, self.height() - 34, self.width() - 56, 18),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "Built for FiveM",
        )


class HeroCard(QFrame):
    create_requested = Signal()
    studio_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("LSHero")
        self.setMinimumHeight(290)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        copy = QFrame()
        copy.setObjectName("LSHeroCopy")
        text = QVBoxLayout(copy)
        text.setContentsMargins(32, 30, 28, 30)
        text.setSpacing(14)
        chip = QLabel("Automotive creation studio")
        chip.setObjectName("LSHeroChip")
        chip.setFont(fonts.font(9, 600, 1.3, caps=True))
        text.addWidget(chip)
        title = heading(
            "Prêt pour ton prochain véhicule ?",
            size=36,
            dot=False,
            accent_words="prochain véhicule ?",
        )
        title.setWordWrap(True)
        text.addWidget(title)
        body = label(
            "Importe un modèle, ajuste-le dans le studio 3D et prépare-le pour "
            "tes serveurs FiveM, dans le style Lore Friendly.",
            wrap=True,
        )
        body.setProperty("role", "subtitle")
        text.addWidget(body)
        text.addStretch(1)
        actions = QHBoxLayout()
        create = LSButton("Créer un véhicule", "primary", "plus")
        create.clicked.connect(self.create_requested)
        studio = LSButton("Studio 3D", "ghost", "arrow-up-right")
        studio.clicked.connect(self.studio_requested)
        actions.addWidget(create)
        actions.addWidget(studio)
        actions.addStretch(1)
        text.addLayout(actions)
        layout.addWidget(copy, 1)
        layout.addWidget(HeroVisual(), 1)


class DashboardPage(Page):
    new_requested = Signal()
    import_requested = Signal()
    addon_requested = Signal()
    open_requested = Signal(object)  # Path | None
    studio_requested = Signal()
    projects_requested = Signal()

    def __init__(self, projects_dir: Callable[[], Path]) -> None:
        super().__init__(
            ["Espace personnel", "LeStitcheurFou Cars"],
            "Bienvenue dans ton garage",
            "Crée, personnalise et prépare tes véhicules pour FiveM.",
        )
        self._projects_dir = projects_dir
        today = datetime.now()
        self.date_label = label(f"{today.day} {FRENCH_MONTHS[today.month - 1]} {today.year}", "faint")
        refresh = LSButton("Actualiser", "secondary", "refresh-cw")
        refresh.clicked.connect(self.refresh)
        self.header.actions.addWidget(self.date_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.header.actions.addWidget(refresh)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.action_buttons: dict[str, LSButton] = {}
        for key, text, variant, icon in (
            ("new", "Nouveau véhicule", "primary", "plus"),
            ("import", "Importer un modèle 3D", "secondary", "import"),
            ("addon", "Importer un addon FiveM", "secondary", "package"),
            ("open", "Ouvrir un projet", "secondary", "folder-open"),
        ):
            button = LSButton(text, variant, icon)
            actions.addWidget(button)
            self.action_buttons[key] = button
        self.action_buttons["new"].clicked.connect(self.new_requested)
        self.action_buttons["import"].clicked.connect(self.import_requested)
        self.action_buttons["addon"].clicked.connect(self.addon_requested)
        self.action_buttons["open"].clicked.connect(lambda: self.open_requested.emit(None))
        actions.addStretch(1)
        self.body.addLayout(actions)

        self.hero = HeroCard()
        self.hero.create_requested.connect(self.new_requested)
        self.hero.studio_requested.connect(self.studio_requested)
        self.body.addWidget(self.hero)

        self.stats = LSStatsGrid(
            [
                StatSpec("Projets créés", "folder", "blue"),
                StatSpec("Véhicules importés", "car", "blue"),
                StatSpec(
                    "Livrées disponibles",
                    "paint-bucket",
                    "electric",
                    "—",
                    "",
                    "Atelier de livrées à venir",
                ),
                StatSpec("Dernière activité", "clock", "amber"),
            ]
        )
        self.body.addWidget(self.stats)
        see_all = LSButton("Voir tous les projets", "ghost", "arrow-up-right", True)
        see_all.clicked.connect(self.projects_requested)
        self.body.addWidget(section_title("Projets récents", see_all))
        self.grid = ProjectGrid()
        self.body.addWidget(self.grid)
        self.finish()
        self.refresh()

    def refresh(self) -> None:
        summaries = known_projects(self._projects_dir())
        count, total = len(summaries), sum(s.asset_count for s in summaries)
        self.stats.cells[0].set_value(
            str(count), "projets" if count > 1 else "projet", "Dossier de projets et récents"
        )
        self.stats.cells[1].set_value(
            str(total), "modèles" if total > 1 else "modèle", "Fichiers 3D importés"
        )
        if summaries:
            self.stats.cells[3].set_value(
                relative_date(summaries[0].updated_at).split(",")[0], "", summaries[0].name
            )
        else:
            self.stats.cells[3].set_value("—", "", "Aucune activité")
        empty = LSEmptyState(
            "car",
            "Aucun projet pour l'instant",
            "Crée un véhicule ou importe un modèle 3D pour remplir ton garage.",
            ("Nouveau véhicule", self.new_requested.emit),
        )
        self.grid.set_projects(summaries[:8], lambda p: self.open_requested.emit(Path(p)), empty)
