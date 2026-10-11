"""Feuille de style Qt générée à partir des tokens.

Conventions : les variantes passent par des propriétés dynamiques
(``variant``, ``size``, ``role``, ``tint``) et des ``objectName`` préfixés ``LS``.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from lsfcars.ui.design import fonts
from lsfcars.ui.design import tokens as t

_density: t.Density = t.NORMAL


def density() -> t.Density:
    return _density


def stylesheet(d: t.Density = t.NORMAL) -> str:
    red_bg, red_fg, red_border = t.tint("red")
    # Pas de règle « * » sur la police : elle écraserait les QFont posées en code
    # (titres, capitales espacées). La police de base est définie par app.setFont().
    return f"""
QWidget {{ color: {t.TEXT}; outline: none; }}
QMainWindow, QDialog {{ background: {t.BG}; }}
QWidget#LSPage {{
    background: qradialgradient(cx:0.92, cy:0, radius:0.75, fx:0.92, fy:0,
        stop:0 rgba(70, 22, 32, 0.38), stop:0.55 rgba(9, 11, 14, 0), stop:1 rgba(9, 11, 14, 0));
}}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QToolTip {{ background: {t.SURFACE}; color: {t.TEXT}; border: 1px solid {t.BORDER_STRONG};
    border-radius: 6px; padding: 6px 9px; font-size: {d.small_font}px; }}

/* --- Barre de titre ------------------------------------------------------ */
QWidget#LSTopbar {{ background: {t.TITLEBAR}; border-bottom: 1px solid {t.BORDER_SOFT}; }}
QLabel#LSAppTitle {{ color: #dfe6f1; }}
QLabel#LSAppSubtitle {{ color: {t.TEXT_FAINT}; }}
QLabel#LSProjectTitle {{ color: #cdd4df; font-weight: 600; font-size: {d.small_font}px; }}
QLabel#LSSaveState {{ color: {t.TEXT_MUTED}; font-size: {d.tiny_font + 1}px; }}
QLabel#LSSaveState[state="dirty"] {{ color: {t.WARNING}; }}
QLabel#LSSaveState[state="saved"] {{ color: {t.SUCCESS}; }}
QLineEdit#LSSearch {{ background: {t.INPUT}; border: 1px solid #272f39; border-radius: 8px;
    padding: 6px 10px 6px 30px; color: {t.TEXT_3}; font-size: {d.small_font}px; min-width: 220px; }}
QLineEdit#LSSearch:focus {{ border-color: {t.ACCENT_BORDER}; color: {t.TEXT}; }}
QToolButton#LSWindowButton {{ border: none; border-radius: 0; background: transparent;
    min-width: 44px; min-height: {t.TITLEBAR_HEIGHT - 1}px; }}
QToolButton#LSWindowButton:hover {{ background: {t.HOVER}; }}
QToolButton#LSWindowButton[role="close"]:hover {{ background: #c42b3d; }}
QToolButton#LSIconButton {{ border: 1px solid transparent; border-radius: 7px; background: transparent;
    min-width: 32px; min-height: 32px; }}
QToolButton#LSIconButton:hover {{ background: {t.SURFACE_HOVER}; }}
QToolButton#LSIconButton:checked {{ background: {t.ACCENT_DARK}; border-color: {t.ACCENT_BORDER}; }}
QLabel#LSCounter {{ background: {t.ACCENT}; color: white; border-radius: 8px; padding: 1px 6px;
    font-size: {d.tiny_font + 1}px; font-weight: 700; }}

/* --- Sidebar ------------------------------------------------------------- */
QWidget#LSSidebar {{ background: {t.SIDEBAR}; border-right: 1px solid {t.SIDEBAR_BORDER}; }}
QPushButton#LSNavItem {{ background: transparent; border: 1px solid transparent; border-radius: {d.radius_md}px;
    color: {t.TEXT_3}; text-align: left; padding: {d.nav_padding}px 12px; min-height: 0;
    font-size: {d.small_font}px; font-weight: 500; }}
QPushButton#LSNavItem:hover {{ background: {t.HOVER}; color: #f6f7f9; }}
QPushButton#LSNavItem:checked {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(255,65,87,0.11), stop:1 rgba(255,65,87,0.04));
    border: 1px solid rgba(255, 65, 87, 0.17); color: {t.ACCENT_TEXT}; }}
QPushButton#LSNavItem[upcoming="true"] {{ color: {t.TEXT_MUTED}; }}
QPushButton#LSNavItem[upcoming="true"]:checked {{ color: #c98794; }}
QLabel#LSNavSection {{ color: {t.TEXT_FAINT}; }}
QLabel#LSNavBadge {{ background: #242d38; color: #acb6c4; border-radius: 5px; padding: 1px 6px;
    font-size: {d.tiny_font + 1}px; }}
QLabel#LSNavDot {{ background: {t.WARNING}; border-radius: 3px; }}
QFrame#LSProfileCard {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2a1a2a, stop:1 #1a1424);
    border: 1px solid #4a2a44; border-radius: 12px; }}
QLabel#LSProfileName {{ color: #f6dce6; font-weight: 700; }}
QLabel#LSProfileMeta {{ color: #b9a1b4; font-size: {d.tiny_font + 2}px; }}
QLabel#LSVersion {{ background: #1a1f27; border: 1px solid #303843; color: #9fa7b5; border-radius: 5px;
    padding: 1px 6px; font-size: {d.tiny_font}px; }}

/* --- Typographie --------------------------------------------------------- */
QLabel[role="h1"] {{ color: {t.TEXT}; }}
QLabel[role="h2"] {{ color: {t.TEXT}; font-size: 17px; font-weight: 600; }}
QLabel[role="h3"] {{ color: {t.TEXT}; font-size: 14px; font-weight: 600; }}
QLabel[role="subtitle"] {{ color: {t.TEXT_2}; font-size: {d.small_font}px; }}
QLabel[role="muted"] {{ color: {t.TEXT_MUTED}; font-size: {d.small_font}px; }}
QLabel[role="faint"] {{ color: {t.TEXT_FAINT}; font-size: {d.tiny_font + 1}px; }}
QLabel[role="eyebrow"] {{ color: #626f7e; }}
QLabel[role="breadcrumb"] {{ color: #6e7b8b; font-size: {d.small_font - 1}px; }}
QLabel[role="breadcrumb-current"] {{ color: #cdd4df; font-size: {d.small_font - 1}px; font-weight: 600; }}
QLabel[role="value"] {{ color: {t.TEXT}; }}
QLabel[role="info"] {{ color: {t.TEXT_INFO}; font-size: {d.small_font}px; }}
QLabel[role="warning"] {{ color: {t.WARNING}; font-size: {d.small_font}px; }}
QLabel[role="error"] {{ color: {t.ERROR}; font-size: {d.small_font}px; }}

/* --- Cartes -------------------------------------------------------------- */
QFrame#LSCard {{ background: {t.CARD}; border: 1px solid {t.BORDER}; border-radius: {d.radius_lg}px; }}
QFrame#LSCard[interactive="true"]:hover {{ border-color: {t.ACCENT_BORDER}; }}
QFrame#LSHero {{ background: {t.CARD_ALT}; border: 1px solid #593039; border-radius: 18px; }}
QFrame#LSHeroCopy {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0.4, stop:0 #1c151a, stop:1 #131519);
    border: none; border-top-left-radius: 17px; border-bottom-left-radius: 17px; }}
QLabel#LSHeroChip {{ color: #c0a2ac; }}
QFrame#LSStatsGrid {{ background: {t.CARD}; border: 1px solid {t.DIVIDER}; border-radius: 14px; }}
QFrame#LSStatCell {{ background: transparent; border: none; border-right: 1px solid {t.DIVIDER}; }}
QFrame#LSStatCell[last="true"] {{ border-right: none; }}
QFrame#LSPanel {{ background: {t.PANEL}; border: 1px solid {t.BORDER_SOFT}; border-radius: 12px; }}
QFrame#LSThumb {{ background: #0d1116; border: 1px solid {t.BORDER_SOFT}; border-radius: 10px; }}
QFrame#LSSeparator {{ background: {t.DIVIDER}; border: none; max-height: 1px; min-height: 1px; }}

/* --- Badges -------------------------------------------------------------- */
QLabel#LSBadge {{ border-radius: 6px; padding: 3px 7px; font-size: {d.tiny_font + 1}px; font-weight: 600;
    background: #222a33; color: #a7b2c0; border: 1px solid #35404d; }}
QLabel#LSBadge[tint="red"] {{ background: {red_bg}; color: {red_fg}; border-color: {red_border}; }}
QLabel#LSBadge[tint="green"] {{ background: #12372a; color: #7fe1b1; border-color: #24523e; }}
QLabel#LSBadge[tint="amber"] {{ background: #392e1b; color: #ebc581; border-color: #5b4527; }}
QLabel#LSBadge[tint="blue"] {{ background: #192c3d; color: #75c0ed; border-color: #2b4a66; }}

/* --- Boutons ------------------------------------------------------------- */
QPushButton {{ background: {t.SURFACE}; border: 1px solid {t.BORDER_STRONG}; color: #c9d2dd;
    border-radius: {d.radius_md}px; padding: 0 15px; min-height: {d.control_height}px;
    font-size: {d.small_font}px; font-weight: 600; }}
QPushButton:hover {{ background: {t.SURFACE_HOVER}; border-color: #46576a; color: white; }}
QPushButton:pressed {{ background: #1a212a; }}
QPushButton:disabled {{ color: #4f5a67; border-color: #232a33; background: #151a20; }}
QPushButton[variant="primary"] {{ background: {t.ACCENT}; border-color: #ff5266; color: white; }}
QPushButton[variant="primary"]:hover {{ background: {t.ACCENT_2}; border-color: #ff7b89; }}
QPushButton[variant="primary"]:pressed {{ background: #e5354b; }}
QPushButton[variant="primary"]:disabled {{ background: #4a1f29; border-color: #5a2632; color: #b07985; }}
QPushButton[variant="ghost"] {{ background: transparent; border-color: rgba(255,255,255,0.09); color: #b9c3d0; }}
QPushButton[variant="ghost"]:hover {{ background: rgba(255,255,255,0.03); color: white; }}
QPushButton[variant="danger"] {{ background: #4b1d28; color: #ff9daf; border-color: #783044; }}
QPushButton[variant="danger"]:hover {{ background: #5c2230; color: #ffc2cd; }}
QPushButton[size="small"] {{ min-height: {d.control_height - 8}px; padding: 0 11px; font-size: {d.small_font - 1}px; }}
QPushButton[chip="true"] {{ font-weight: 500; color: #dfe5ee; padding: 0 14px; }}

QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 7px;
    padding: 4px 7px; color: {t.TEXT_3}; }}
QToolButton:hover {{ background: {t.SURFACE_HOVER}; color: white; }}
QToolButton:checked {{ background: {t.ACCENT_DARK}; border-color: {t.ACCENT_BORDER}; color: {t.ACCENT_TEXT}; }}
QToolButton:disabled {{ color: #4f5a67; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

/* --- Champs -------------------------------------------------------------- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {t.INPUT}; border: 1px solid #272f39; border-radius: 8px; padding: 4px 9px;
    color: {t.TEXT}; selection-background-color: #ab263f; min-height: {d.control_height - 14}px; }}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: #36414e; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {t.ACCENT_BORDER}; }}
QLineEdit:read-only {{ color: {t.TEXT_3}; }}
QLineEdit:disabled, QComboBox:disabled, QDoubleSpinBox:disabled {{ color: #4f5a67; }}
QAbstractSpinBox {{ padding-right: 2px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 12px; border: none; background: transparent; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {t.PANEL}; border: 1px solid {t.BORDER}; border-radius: 8px;
    selection-background-color: {t.ACCENT_DARK}; selection-color: {t.ACCENT_TEXT}; padding: 4px; }}
QDoubleSpinBox[axis="x"] {{ border-left: 2px solid {t.AXIS_X}; }}
QDoubleSpinBox[axis="y"] {{ border-left: 2px solid {t.AXIS_Y}; }}
QDoubleSpinBox[axis="z"] {{ border-left: 2px solid {t.AXIS_Z}; }}
QCheckBox {{ spacing: 8px; color: #c9d2dd; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid {t.BORDER_STRONG}; border-radius: 4px;
    background: {t.INPUT}; }}
QCheckBox::indicator:checked {{ background: {t.ACCENT}; border-color: {t.ACCENT}; }}
QSlider::groove:horizontal {{ height: 4px; background: {t.SURFACE}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {t.ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: #f4f6f9; width: 12px; height: 12px; margin: -5px 0; border-radius: 6px; }}
QProgressBar {{ background: {t.SURFACE}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px;
    text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {t.ACCENT}, stop:1 #ff7b8e);
    border-radius: 3px; }}

/* --- Onglets ------------------------------------------------------------- */
QTabWidget::pane {{ border: none; }}
QTabBar {{ background: transparent; qproperty-drawBase: 0; }}
QTabBar::tab {{ background: transparent; color: #7e8da0; border: none; border-bottom: 2px solid transparent;
    padding: 6px 2px 9px 2px; margin-right: 18px; font-size: {d.small_font - 1}px; font-weight: 600; }}
QTabBar::tab:hover {{ color: #c9d2dd; }}
QTabBar::tab:selected {{ color: #ff7d90; border-bottom-color: #ff526c; }}

/* --- Listes et arbres ---------------------------------------------------- */
QTreeView, QListView, QTreeWidget, QListWidget, QTableView {{ background: transparent; border: none;
    alternate-background-color: transparent; }}
QTreeView::item, QListView::item {{ padding: 4px 2px; border-radius: 6px; color: #c9d2dd; }}
QTreeView::item:hover, QListView::item:hover {{ background: {t.HOVER}; }}
QTreeView::item:selected, QListView::item:selected {{ background: rgba(255,65,87,0.14); color: {t.ACCENT_TEXT}; }}
QTreeView::branch {{ background: transparent; }}
QHeaderView::section {{ background: transparent; color: {t.TEXT_FAINT}; border: none; padding: 4px; }}

/* --- Panneaux ancrables -------------------------------------------------- */
QDockWidget {{ color: {t.TEXT_3}; font-size: {d.tiny_font + 1}px; font-weight: 700; }}
QDockWidget::title {{ background: {t.PANEL}; padding: 8px 12px; border-bottom: 1px solid {t.BORDER_SOFT};
    text-align: left; }}
QDockWidget > QWidget {{ background: {t.PANEL}; }}
QMainWindow::separator {{ background: {t.BORDER_SOFT}; width: 1px; height: 1px; }}
QMainWindow::separator:hover {{ background: {t.ACCENT_BORDER}; }}
QSplitter::handle {{ background: {t.BORDER_SOFT}; }}
QSplitter::handle:hover {{ background: {t.ACCENT_BORDER}; }}

/* --- Menus --------------------------------------------------------------- */
QMenu {{ background: {t.PANEL}; border: 1px solid {t.BORDER}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 6px; color: #c9d2dd; }}
QMenu::item:selected {{ background: {t.ACCENT_DARK}; color: {t.ACCENT_TEXT}; }}
QMenu::item:disabled {{ color: #4f5a67; }}
QMenu::separator {{ height: 1px; background: {t.BORDER_SOFT}; margin: 5px 8px; }}
QMenu::icon {{ padding-left: 8px; }}

/* --- Barres de défilement discrètes -------------------------------------- */
QScrollBar:vertical {{ background: transparent; width: 6px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #35353e; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #4a4a56; }}
QScrollBar:horizontal {{ background: transparent; height: 6px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #35353e; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

/* --- Notifications et fenêtres modales ----------------------------------- */
QFrame#LSToast {{ background: #161b22; border: 1px solid {t.BORDER_STRONG}; border-radius: 12px; }}
QFrame#LSToast[level="success"] {{ border-color: #24523e; }}
QFrame#LSToast[level="warning"] {{ border-color: #5b4527; }}
QFrame#LSToast[level="error"] {{ background: #2a1820; border-color: #6d3854; }}
QDialog#LSModal {{ background: {t.PANEL}; }}
QFrame#LSModalHeader {{ background: {t.CARD}; border-bottom: 1px solid {t.BORDER_SOFT}; }}
QFrame#LSModalActions {{ border-top: 1px solid {t.BORDER_SOFT}; }}

/* --- Viewport ------------------------------------------------------------ */
QFrame#LSViewportToolbar {{ background: rgba(13,16,20,0.92); border: 1px solid {t.BORDER_SOFT}; border-radius: 10px; }}
QLabel#LSViewportHint {{ color: {t.TEXT_MUTED}; background: rgba(9,11,14,0.75); border-radius: 6px;
    padding: 4px 9px; font-size: {d.tiny_font + 1}px; }}
QLabel#LSViewportError {{ color: {t.ERROR}; background: rgba(9,11,14,0.92); border: 1px solid #6d3854;
    border-radius: 10px; padding: 16px; }}
QPlainTextEdit#LSLog {{ background: #0b0e12; border: none; border-radius: 0; font-size: {d.small_font - 1}px; }}
"""


def apply_design(app: QApplication, compact: bool = False) -> None:
    """Applique polices, palette et feuille de style à toute l'application."""
    global _density
    _density = t.COMPACT if compact else t.NORMAL
    fonts.load_fonts()
    app.setStyle("Fusion")
    app.setFont(fonts.font(_density.base_font))

    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: t.BG,
        QPalette.ColorRole.WindowText: t.TEXT,
        QPalette.ColorRole.Base: t.INPUT,
        QPalette.ColorRole.AlternateBase: t.PANEL,
        QPalette.ColorRole.Text: t.TEXT,
        QPalette.ColorRole.Button: t.SURFACE,
        QPalette.ColorRole.ButtonText: "#c9d2dd",
        QPalette.ColorRole.Highlight: "#ab263f",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.ToolTipBase: t.SURFACE,
        QPalette.ColorRole.ToolTipText: t.TEXT,
        QPalette.ColorRole.PlaceholderText: t.TEXT_MUTED,
        QPalette.ColorRole.Link: t.ACCENT_TEXT,
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#4f5a67"))
    app.setPalette(palette)
    app.setStyleSheet(stylesheet(_density))
