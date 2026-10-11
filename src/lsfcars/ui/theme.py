"""Thème sombre à accents bleu électrique."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

COLORS = {
    "bg0": "#0b0f15",  # fond de fenêtre
    "bg1": "#11161f",  # panneaux
    "bg2": "#18202c",  # champs de saisie
    "bg3": "#212b3a",  # survol
    "border": "#263142",
    "text": "#e6edf3",
    "muted": "#8b98a9",
    "accent": "#1e90ff",
    "accent_hover": "#4aa8ff",
    "accent_dark": "#0b5fbf",
    "success": "#3ccf91",
    "warning": "#f0b429",
    "danger": "#ff5c6c",
}

LOG_LEVEL_COLORS = {
    "DEBUG": COLORS["muted"],
    "INFO": COLORS["text"],
    "WARNING": COLORS["warning"],
    "ERROR": COLORS["danger"],
    "CRITICAL": COLORS["danger"],
}

VIEWPORT_BACKGROUND = (0.075, 0.09, 0.115)

QSS = """
* {{ font-family: "Segoe UI", "Inter", sans-serif; font-size: 10pt; }}
QMainWindow, QDialog {{ background: {bg0}; }}
QWidget {{ color: {text}; }}
QToolTip {{ background: {bg2}; color: {text}; border: 1px solid {accent}; padding: 4px; }}

QMenuBar {{ background: {bg1}; border-bottom: 1px solid {border}; }}
QMenuBar::item {{ padding: 6px 10px; background: transparent; }}
QMenuBar::item:selected {{ background: {bg3}; border-radius: 4px; }}
QMenu {{ background: {bg1}; border: 1px solid {border}; padding: 4px; }}
QMenu::item {{ padding: 6px 24px 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {accent_dark}; }}
QMenu::item:disabled {{ color: {muted}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}

QStatusBar {{ background: {bg1}; border-top: 1px solid {border}; color: {muted}; }}
QStatusBar QLabel {{ color: {muted}; padding: 0 8px; }}

QDockWidget {{ color: {text}; }}
QDockWidget::title {{ background: {bg1}; padding: 7px 10px; border-bottom: 1px solid {border};
    font-weight: 600; }}
QMainWindow::separator {{ background: {border}; width: 1px; height: 1px; }}

QToolBar#NavToolBar {{ background: {bg1}; border: none; padding: 0; spacing: 0; }}
QFrame#NavRail {{ background: {bg1}; border-right: 1px solid {border}; }}
QFrame#ViewportToolbar {{ background: {bg1}; border-bottom: 1px solid {border}; }}
QPushButton#NavButton {{ background: transparent; border: none; border-left: 3px solid transparent;
    border-radius: 0; padding: 11px 16px; text-align: left; color: {muted}; font-weight: 600; }}
QPushButton#NavButton:hover {{ background: {bg3}; color: {text}; }}
QPushButton#NavButton:checked {{ color: {text}; background: {bg2}; border-left: 3px solid {accent}; }}
QLabel#NavTitle {{ color: {accent}; font-weight: 800; font-size: 11pt; padding: 14px 14px 2px 14px; }}
QLabel#NavVersion {{ color: {muted}; font-size: 8pt; padding: 0 14px 12px 14px; }}

QPushButton {{ background: {bg2}; border: 1px solid {border}; border-radius: 6px; padding: 7px 14px; }}
QPushButton:hover {{ background: {bg3}; border-color: {accent}; }}
QPushButton:pressed {{ background: {accent_dark}; }}
QPushButton:disabled {{ color: {muted}; border-color: {bg3}; }}
QPushButton[primary="true"] {{ background: {accent}; border-color: {accent}; color: white; font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: {accent_hover}; }}
QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 5px; padding: 4px 8px; }}
QToolButton:hover {{ background: {bg3}; border-color: {border}; }}

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {bg2}; border: 1px solid {border}; border-radius: 5px; padding: 5px 7px;
    selection-background-color: {accent_dark}; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {accent}; }}
QLineEdit:read-only {{ color: {muted}; }}
QAbstractSpinBox {{ padding-right: 2px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 12px; border: none; background: transparent; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{ background: {bg1}; border: 1px solid {border};
    selection-background-color: {accent_dark}; }}

QTreeWidget, QListWidget, QTreeView, QListView {{ background: {bg1}; border: none; outline: none; }}
QTreeWidget::item, QListWidget::item {{ padding: 5px 4px; border-radius: 4px; }}
QTreeWidget::item:hover, QListWidget::item:hover {{ background: {bg3}; }}
QTreeWidget::item:selected, QListWidget::item:selected {{ background: {accent_dark}; color: white; }}
QHeaderView::section {{ background: {bg1}; color: {muted}; border: none; padding: 5px; }}

QGroupBox {{ border: 1px solid {border}; border-radius: 8px; margin-top: 14px; padding: 10px 8px 8px 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {accent}; font-weight: 600; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {bg3}; border-radius: 5px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {accent_dark}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {bg3}; border-radius: 5px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid {border}; border-radius: 3px;
    background: {bg2}; }}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}

QLabel#H1 {{ font-size: 24pt; font-weight: 800; }}
QLabel#H2 {{ font-size: 14pt; font-weight: 700; }}
QLabel#Muted {{ color: {muted}; }}
QLabel#Accent {{ color: {accent}; font-weight: 600; }}
QLabel#Badge {{ background: {bg3}; color: {warning}; border: 1px solid {warning}; border-radius: 10px;
    padding: 3px 10px; font-weight: 600; }}
QLabel#Warning {{ color: {warning}; }}
QFrame#Card {{ background: {bg1}; border: 1px solid {border}; border-radius: 10px; }}
QLabel#ViewportHint {{ color: {muted}; background: rgba(11, 15, 21, 170); border-radius: 6px;
    padding: 5px 9px; font-size: 9pt; }}
QLabel#ViewportError {{ color: {danger}; background: rgba(11, 15, 21, 220); border: 1px solid {danger};
    border-radius: 8px; padding: 14px; }}
"""


def stylesheet() -> str:
    return QSS.format(**COLORS)


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: COLORS["bg0"],
        QPalette.ColorRole.WindowText: COLORS["text"],
        QPalette.ColorRole.Base: COLORS["bg2"],
        QPalette.ColorRole.AlternateBase: COLORS["bg1"],
        QPalette.ColorRole.Text: COLORS["text"],
        QPalette.ColorRole.Button: COLORS["bg2"],
        QPalette.ColorRole.ButtonText: COLORS["text"],
        QPalette.ColorRole.Highlight: COLORS["accent_dark"],
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.ToolTipBase: COLORS["bg2"],
        QPalette.ColorRole.ToolTipText: COLORS["text"],
        QPalette.ColorRole.PlaceholderText: COLORS["muted"],
        QPalette.ColorRole.Link: COLORS["accent"],
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(COLORS["muted"]))
    app.setPalette(palette)
    app.setStyleSheet(stylesheet())
