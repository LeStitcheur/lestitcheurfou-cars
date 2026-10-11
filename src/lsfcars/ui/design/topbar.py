"""LSTopbar : barre de titre personnalisée (fenêtre sans cadre)."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QStringListModel, Qt, Signal
from PySide6.QtGui import QKeySequence, QMouseEvent, QShortcut
from PySide6.QtWidgets import (
    QCompleter,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from lsfcars import APP_NAME
from lsfcars.ui.design import fonts, icons
from lsfcars.ui.design import tokens as t
from lsfcars.ui.design.components import LSIconButton, LSInput, set_prop, tooltip

SAVE_STATE_TEXTS = {
    "saved": "Enregistré",
    "dirty": "Modifications non enregistrées",
    "autosaved": "Sauvegarde automatique effectuée",
}


class WindowButton(QToolButton):
    def __init__(self, icon: str, tip: str, role: str = "") -> None:
        super().__init__()
        self.setObjectName("LSWindowButton")
        if role:
            self.setProperty("role", role)
        self.setIcon(icons.icon(icon, t.TEXT_3, t.TEXT, size=14))
        self.setIconSize(icons.icon_size(14))
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tooltip(self, tip)


class LSTopbar(QWidget):
    toggle_sidebar = Signal()
    search_activated = Signal(str)
    notifications_requested = Signal()
    settings_requested = Signal()

    def __init__(self, window: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self.setObjectName("LSTopbar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(t.TITLEBAR_HEIGHT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(10)

        self.sidebar_button = LSIconButton("panel-left-close", "Réduire la barre latérale", shortcut="Ctrl+B")
        self.sidebar_button.clicked.connect(self.toggle_sidebar)
        layout.addWidget(self.sidebar_button)

        logo = QLabel()
        logo.setPixmap(icons.logo(26))
        layout.addWidget(logo)
        brand = QVBoxLayout()
        brand.setSpacing(0)
        title = QLabel(APP_NAME)
        title.setObjectName("LSAppTitle")
        title.setFont(fonts.font(12, 600))
        subtitle = QLabel("Vehicle creation studio")
        subtitle.setObjectName("LSAppSubtitle")
        subtitle.setFont(fonts.font(8, 600, 1.6, caps=True))
        brand.addStretch(1)
        brand.addWidget(title)
        brand.addWidget(subtitle)
        brand.addStretch(1)
        layout.addLayout(brand)
        layout.addStretch(1)

        center = QVBoxLayout()
        center.setSpacing(1)
        self.project_label = QLabel("Aucun projet")
        self.project_label.setObjectName("LSProjectTitle")
        self.project_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.save_state = QLabel("")
        self.save_state.setObjectName("LSSaveState")
        self.save_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center.addStretch(1)
        center.addWidget(self.project_label)
        center.addWidget(self.save_state)
        center.addStretch(1)
        layout.addLayout(center)
        layout.addStretch(1)

        self.search = LSInput("Rechercher…", "search")
        self.search.setObjectName("LSSearch")
        self.search.setStyleSheet("padding-left: 8px;")
        tooltip(self.search, "Rechercher une page, une commande ou un objet", "Ctrl+K")
        self._completer_model = QStringListModel(self)
        completer = QCompleter(self._completer_model, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.activated.connect(self._activate)
        self.search.setCompleter(completer)
        self.search.returnPressed.connect(lambda: self._activate(self.search.text()))
        layout.addWidget(self.search)
        QShortcut(QKeySequence("Ctrl+K"), window).activated.connect(self._focus_search)

        self.bell = LSIconButton("bell", "Notifications")
        self.bell.clicked.connect(self.notifications_requested)
        layout.addWidget(self.bell)
        self.counter = QLabel("")
        self.counter.setObjectName("LSCounter")
        self.counter.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        self.counter.hide()
        layout.addWidget(self.counter, 0, Qt.AlignmentFlag.AlignVCenter)
        self.settings_button = LSIconButton("settings", "Paramètres")
        self.settings_button.clicked.connect(self.settings_requested)
        layout.addWidget(self.settings_button)

        divider = QFrame()
        divider.setFixedSize(1, 22)
        divider.setStyleSheet(f"background: {t.BORDER_SOFT};")
        layout.addSpacing(4)
        layout.addWidget(divider)

        self.min_button = WindowButton("minus", "Réduire")
        self.max_button = WindowButton("square", "Agrandir")
        self.close_button = WindowButton("x", "Fermer", "close")
        self.min_button.clicked.connect(window.showMinimized)
        self.max_button.clicked.connect(self.toggle_maximized)
        self.close_button.clicked.connect(window.close)
        for button in (self.min_button, self.max_button, self.close_button):
            layout.addWidget(button)
        window.installEventFilter(self)

    # --- État -----------------------------------------------------------------
    def set_project(self, name: str | None, state: str = "") -> None:
        """``state`` : 'saved', 'dirty', 'autosaved' ou ''."""
        self.project_label.setText(name or "Aucun projet")
        default = "" if name else "Ouvrez ou créez un projet"
        self.save_state.setText(SAVE_STATE_TEXTS.get(state, default))
        style = "dirty" if state == "dirty" else ("saved" if state in SAVE_STATE_TEXTS else "")
        set_prop(self.save_state, "state", style)

    def set_unread(self, count: int) -> None:
        self.counter.setVisible(count > 0)
        self.counter.setText(str(count) if count < 100 else "99+")

    def set_sidebar_collapsed(self, collapsed: bool) -> None:
        name = "panel-left-open" if collapsed else "panel-left-close"
        self.sidebar_button.setIcon(icons.icon(name, t.TEXT_3, t.TEXT, size=17))
        text = "Déplier la barre latérale" if collapsed else "Réduire la barre latérale"
        tooltip(self.sidebar_button, text, "Ctrl+B")

    def set_search_entries(self, entries: list[str]) -> None:
        self._completer_model.setStringList(entries)

    # --- Fenêtre --------------------------------------------------------------
    def toggle_maximized(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def _focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def _activate(self, text: str) -> None:
        if text.strip():
            self.search_activated.emit(text.strip())
            self.search.clear()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None and not self._window.isFullScreen():
                handle.startSystemMove()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self._window and event.type() == QEvent.Type.WindowStateChange:
            maximized = self._window.isMaximized()
            name = "copy" if maximized else "square"
            self.max_button.setIcon(icons.icon(name, t.TEXT_3, t.TEXT, size=14))
            tooltip(self.max_button, "Restaurer" if maximized else "Agrandir")
        return False
