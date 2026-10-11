"""LSSidebar : navigation verticale de la suite LeStitcheur (rétractable)."""

from __future__ import annotations

import getpass
from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRect, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from lsfcars import __version__
from lsfcars.ui.design import fonts, icons
from lsfcars.ui.design import tokens as t
from lsfcars.ui.design.components import set_prop, tooltip
from lsfcars.ui.design.qss import density


@dataclass(frozen=True)
class NavEntry:
    key: str
    label: str
    icon: str
    section: str
    upcoming: bool = False
    tooltip: str = ""


class NavItem(QPushButton):
    """Entrée de navigation ; l'entrée active reçoit un liseré rouge à gauche."""

    def __init__(self, entry: NavEntry) -> None:
        super().__init__(entry.label)
        self.entry = entry
        self.setObjectName("LSNavItem")
        self.setCheckable(True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setIcon(icons.icon(entry.icon, "#687587", "#ff677a", size=18))
        self.setIconSize(icons.icon_size(18))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if entry.upcoming:
            self.setProperty("upcoming", True)
        tip = entry.tooltip or entry.label
        if entry.upcoming:
            tip += " — fonctionnalité à venir"
        tooltip(self, tip)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 10, 0)
        row.addStretch(1)
        self.badge = QLabel()
        self.badge.setObjectName("LSNavBadge")
        self.badge.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        self.badge.hide()
        row.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignVCenter)
        # Point discret « à venir » (même vocabulaire que les indicateurs de LeStitcheur Control)
        self.dot = QLabel()
        self.dot.setObjectName("LSNavDot")
        self.dot.setFixedSize(6, 6)
        self.dot.setVisible(entry.upcoming)
        row.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_badge(self, text: str | None, tint: str = "") -> None:
        if not text:
            self.badge.setText("")
            self.badge.hide()
            return
        self.badge.setText(text)
        set_prop(self.badge, "tint", tint)
        self.badge.show()

    def set_collapsed(self, collapsed: bool) -> None:
        self.setText("" if collapsed else self.entry.label)
        self.badge.setVisible(not collapsed and bool(self.badge.text()))
        self.dot.setVisible(not collapsed and self.entry.upcoming)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        super().paintEvent(event)
        if self.isChecked():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(t.ACCENT_2))
            painter.drawRoundedRect(QRect(0, 11, 2, max(self.height() - 22, 4)), 1, 1)


class ProfileCard(QFrame):
    """Carte profil : utilisateur Windows local (aucune donnée inventée)."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("LSProfileCard")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(11)
        avatar = QLabel()
        avatar.setPixmap(icons.emblem(40))
        avatar.setFixedSize(40, 40)
        layout.addWidget(avatar)
        try:
            user = getpass.getuser()
        except (KeyError, OSError):
            user = "Utilisateur"
        self.name = QLabel(user)
        self.name.setObjectName("LSProfileName")
        self.name.setFont(fonts.font(15, 700))
        self.meta = QLabel("Espace local")
        self.meta.setObjectName("LSProfileMeta")
        self.texts = QWidget()
        texts = QVBoxLayout(self.texts)
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(2)
        texts.addWidget(self.name)
        texts.addWidget(self.meta)
        layout.addWidget(self.texts, 1)

    def set_collapsed(self, collapsed: bool) -> None:
        self.texts.setVisible(not collapsed)
        margin = 0 if collapsed else 12
        self.layout().setContentsMargins(margin, margin, margin, margin)


class LSSidebar(QWidget):
    navigate = Signal(str)
    collapsed_changed = Signal(bool)

    def __init__(self, entries: Sequence[NavEntry], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LSSidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._collapsed = False
        self.items: dict[str, NavItem] = {}
        self._sections: list[QLabel] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 16, 12, 12)
        outer.setSpacing(0)
        self.profile = ProfileCard()
        outer.addWidget(self.profile)
        outer.addSpacing(20)

        self.workspace_row = QWidget()
        workspace = QHBoxLayout(self.workspace_row)
        workspace.setContentsMargins(10, 0, 6, 0)
        self.workspace_label = QLabel("Espace personnel")
        self.workspace_label.setObjectName("LSNavSection")
        self.workspace_label.setFont(fonts.font(density().tiny_font, 700, 1.4, caps=True))
        self.version = QLabel(".".join(__version__.split(".")[:2]))
        self.version.setObjectName("LSVersion")
        workspace.addWidget(self.workspace_label)
        workspace.addStretch(1)
        workspace.addWidget(self.version)
        outer.addWidget(self.workspace_row)
        outer.addSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        nav = QVBoxLayout(content)
        nav.setContentsMargins(0, 0, 4, 0)
        nav.setSpacing(density().nav_spacing)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        current_section = None
        for entry in entries:
            if entry.section != current_section:
                current_section = entry.section
                section = QLabel(entry.section)
                section.setObjectName("LSNavSection")
                section.setFont(fonts.font(density().tiny_font, 700, 1.4, caps=True))
                section.setContentsMargins(12, 16 if self._sections else 4, 0, 6)
                nav.addWidget(section)
                self._sections.append(section)
            item = NavItem(entry)
            item.clicked.connect(lambda _=False, key=entry.key: self.navigate.emit(key))
            self._group.addButton(item)
            nav.addWidget(item)
            self.items[entry.key] = item
        nav.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        self.setFixedWidth(t.SIDEBAR_WIDTH)
        self._animation = QPropertyAnimation(self, b"minimumWidth", self)
        self._animation.setDuration(170)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(lambda value: self.setMaximumWidth(int(value)))

    # --- API -----------------------------------------------------------------
    def current(self) -> str | None:
        checked = self._group.checkedButton()
        return checked.entry.key if isinstance(checked, NavItem) else None

    def set_current(self, key: str) -> None:
        item = self.items.get(key)
        if item is not None:
            item.setChecked(True)

    def set_badge(self, key: str, text: str | None, tint: str = "") -> None:
        if key in self.items:
            self.items[key].set_badge(text, tint)
            self.items[key].set_collapsed(self._collapsed)

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool, animate: bool = True) -> None:
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        for item in self.items.values():
            item.set_collapsed(collapsed)
        for section in self._sections:
            section.setVisible(not collapsed)
        self.workspace_row.setVisible(not collapsed)
        self.profile.set_collapsed(collapsed)
        target = t.SIDEBAR_COLLAPSED_WIDTH if collapsed else t.SIDEBAR_WIDTH
        self._animation.stop()
        if animate and self.isVisible():
            self.setMinimumWidth(self.width())
            self._animation.setStartValue(self.width())
            self._animation.setEndValue(target)
            self._animation.start()
        else:
            self.setFixedWidth(target)
        self.collapsed_changed.emit(collapsed)

    def toggle(self) -> None:
        self.set_collapsed(not self._collapsed)
