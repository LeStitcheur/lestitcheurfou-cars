"""Squelette commun : page défilante, fil d'Ariane, en-tête et grille de projets."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from lsfcars.project import recent, store
from lsfcars.project.store import ProjectSummary
from lsfcars.ui.design import icons
from lsfcars.ui.design import tokens as t
from lsfcars.ui.design.components import Breadcrumb, LSCard, LSSectionHeader, label
from lsfcars.ui.design.qss import density


class Page(QScrollArea):
    """Page défilante du studio (fond principal Dark Premium)."""

    def __init__(
        self,
        crumbs: Sequence[str],
        title: str,
        subtitle: str = "",
        eyebrow: str = "LeStitcheurFou Cars / Studio",
    ) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("LSPage")
        content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        pad = density().page_padding
        self.body = QVBoxLayout(content)
        self.body.setContentsMargins(pad, 22, pad, pad)
        self.body.setSpacing(22)
        self.breadcrumb = Breadcrumb(crumbs)
        self.body.addWidget(self.breadcrumb)
        self.header = LSSectionHeader(title, subtitle, eyebrow)
        self.body.addWidget(self.header)
        self.setWidget(content)

    def finish(self) -> None:
        self.body.addStretch(1)


def relative_date(iso: str) -> str:
    try:
        moment = datetime.fromisoformat(iso)
    except ValueError:
        return "—"
    days = (datetime.now(UTC).date() - moment.astimezone(UTC).date()).days
    if days <= 0:
        return f"Aujourd'hui, {moment.astimezone().strftime('%H:%M')}"
    if days == 1:
        return "Hier"
    if days < 7:
        return f"Il y a {days} jours"
    return moment.astimezone().strftime("%d/%m/%Y")


def known_projects(projects_dir: Path) -> list[ProjectSummary]:
    """Projets réellement présents : récents + dossier de projets (sans doublon)."""
    paths: dict[str, Path] = {}
    for path in recent.list_recent():
        if path.is_file():
            paths[str(path.resolve()).lower()] = path
    if projects_dir.is_dir():
        for path in list(projects_dir.glob("*/*.lsfc"))[:200]:
            paths.setdefault(str(path.resolve()).lower(), path)
    summaries = [s for s in (store.read_summary(p) for p in paths.values()) if s is not None]
    return sorted(summaries, key=lambda s: s.updated_at, reverse=True)


class ProjectCard(LSCard):
    """Carte projet avec miniature (capture du viewport à l'enregistrement)."""

    def __init__(self, summary: ProjectSummary, on_open: Callable[[Path], None]) -> None:
        super().__init__(padding=12, interactive=True)
        self.summary = summary
        self.setFixedWidth(250)
        thumb = QLabel()
        thumb.setFixedSize(226, 127)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setObjectName("LSThumb")
        pixmap = QPixmap()
        if summary.thumbnail and pixmap.loadFromData(summary.thumbnail):
            thumb.setPixmap(
                pixmap.scaled(
                    226,
                    127,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            thumb.setPixmap(icons.pixmap("car", t.BORDER_STRONG, 40))
        self.body.addWidget(thumb)
        name = label(summary.name, "h3", wrap=True)
        self.body.addWidget(name)
        self.body.addWidget(
            label(
                f"{summary.vehicle_type.label} · {summary.asset_count} "
                f"modèle(s) · {summary.node_count} nœuds",
                "muted",
            )
        )
        self.body.addWidget(label(relative_date(summary.updated_at), "faint"))
        self.setToolTip(str(summary.path))
        self.clicked.connect(lambda: on_open(summary.path))


class ProjectGrid(QWidget):
    def __init__(self, columns: int = 4) -> None:
        super().__init__()
        self.columns = columns
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(16)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.cards: list[ProjectCard] = []

    def set_projects(
        self,
        summaries: Sequence[ProjectSummary],
        on_open: Callable[[Path], None],
        empty: QWidget | None = None,
    ) -> int:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.cards = [ProjectCard(s, on_open) for s in summaries]
        if not summaries and empty is not None:
            self.grid.addWidget(empty, 0, 0)
        for index, card in enumerate(self.cards):
            self.grid.addWidget(card, index // self.columns, index % self.columns)
        return len(self.cards)


def section_title(title: str, action: QWidget | None = None) -> QWidget:
    widget = QWidget()
    row = QHBoxLayout(widget)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(label(title, "h2"))
    row.addStretch(1)
    if action is not None:
        row.addWidget(action)
    return widget


__all__ = [
    "Page",
    "ProjectCard",
    "ProjectGrid",
    "QVBoxLayout",
    "known_projects",
    "relative_date",
    "section_title",
]
