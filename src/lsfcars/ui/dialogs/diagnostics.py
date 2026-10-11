"""Boîte de dialogue « Diagnostics » : rapport système copiable."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lsfcars.core import diagnostics
from lsfcars.core.paths import logs_dir


class DiagnosticsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Diagnostics")
        self.resize(720, 520)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Joignez ce rapport à vos signalements de bug. Il ne contient ni clé ni donnée "
            "personnelle, uniquement des informations techniques."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.report = QPlainTextEdit(diagnostics.format_report())
        self.report.setReadOnly(True)
        font = QFont("Cascadia Mono")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.report.setFont(font)
        layout.addWidget(self.report, 1)

        buttons = QHBoxLayout()
        copy = QPushButton("Copier le rapport")
        copy.setProperty("primary", True)
        copy.clicked.connect(self._copy)
        logs = QPushButton("Ouvrir le dossier des logs")
        logs.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(logs_dir()))))
        close = QPushButton("Fermer")
        close.clicked.connect(self.accept)
        buttons.addWidget(copy)
        buttons.addWidget(logs)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.report.toPlainText())
