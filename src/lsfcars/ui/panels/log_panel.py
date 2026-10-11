"""Panneau Journal : messages de l'application en direct, filtrables."""

from __future__ import annotations

import html
import logging

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lsfcars.core.logging_setup import memory_handler
from lsfcars.core.paths import logs_dir
from lsfcars.ui.design import tokens

LOG_LEVEL_COLORS = {
    "DEBUG": tokens.TEXT_MUTED,
    "INFO": tokens.TEXT_3,
    "WARNING": tokens.WARNING,
    "ERROR": tokens.ERROR,
    "CRITICAL": tokens.ERROR,
}

LEVEL_FILTERS = [
    ("Tous les messages", logging.DEBUG),
    ("Informations", logging.INFO),
    ("Avertissements", logging.WARNING),
    ("Erreurs", logging.ERROR),
]
MAX_ENTRIES = 5000


class _LogBridge(QObject):
    """Transmet les messages vers le thread de l'interface (connexion en file d'attente)."""

    message = Signal(int, str, str)


class LogPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._min_level = logging.INFO
        self._entries: list[tuple[int, str, str]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.setSpacing(4)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Afficher :"))
        self.level_combo = QComboBox()
        for label, level in LEVEL_FILTERS:
            self.level_combo.addItem(label, level)
        self.level_combo.setCurrentIndex(1)
        self.level_combo.currentIndexChanged.connect(self._on_filter)
        toolbar.addWidget(self.level_combo)
        toolbar.addStretch(1)
        clear = QPushButton("Effacer")
        clear.clicked.connect(self.clear)
        open_folder = QPushButton("Ouvrir le dossier des logs")
        open_folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(logs_dir()))))
        toolbar.addWidget(clear)
        toolbar.addWidget(open_folder)
        layout.addLayout(toolbar)

        self.view = QPlainTextEdit()
        self.view.setObjectName("LSLog")
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(MAX_ENTRIES)
        font = QFont("Cascadia Mono")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(9)
        self.view.setFont(font)
        layout.addWidget(self.view)

        self._bridge = _LogBridge(self)
        self._bridge.message.connect(self._append)
        self._handler = memory_handler()
        for record, text in list(self._handler.records):
            self._append(record.levelno, record.levelname, text)
        self._handler.subscribe(self._on_record)

    def _on_record(self, record: logging.LogRecord, text: str) -> None:
        # Peut être appelé depuis n'importe quel thread.
        self._bridge.message.emit(record.levelno, record.levelname, text)

    def _append(self, levelno: int, levelname: str, text: str) -> None:
        self._entries.append((levelno, levelname, text))
        if len(self._entries) > MAX_ENTRIES:
            del self._entries[: len(self._entries) - MAX_ENTRIES]
        if levelno >= self._min_level:
            self._write(levelname, text)

    def _write(self, levelname: str, text: str) -> None:
        color = LOG_LEVEL_COLORS.get(levelname, LOG_LEVEL_COLORS["INFO"])
        escaped = html.escape(text).replace("\n", "<br>")
        self.view.appendHtml(f'<span style="color:{color}">{escaped}</span>')

    def _on_filter(self) -> None:
        self._min_level = int(self.level_combo.currentData())
        self.view.clear()
        for levelno, levelname, text in self._entries:
            if levelno >= self._min_level:
                self._write(levelname, text)

    def clear(self) -> None:
        self._entries.clear()
        self.view.clear()

    def text(self) -> str:
        return self.view.toPlainText()

    def detach(self) -> None:
        """Se désabonne du journal (à la fermeture de la fenêtre)."""
        self._handler.unsubscribe(self._on_record)
