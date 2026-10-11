"""ComponentStyles : feuille de style Qt générée exclusivement à partir des tokens.

Conventions : les variantes passent par des propriétés dynamiques
(``variant``, ``size``, ``role``, ``tint``) et des ``objectName`` préfixés ``LS``.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from lsfcars.ui.design import fonts
from lsfcars.ui.design import tokens as t
from lsfcars.ui.design.tokens import ColorTokens as C
from lsfcars.ui.design.tokens import rgba

_density: t.Density = t.NORMAL


def density() -> t.Density:
    return _density


def _badges() -> str:
    rules = []
    for name, value in t.TINT_TOKENS.items():
        rules.append(
            f'QLabel#LSBadge[tint="{name}"] {{ background: {value.background}; color: {value.foreground}; '
            f"border-color: {value.border}; }}"
        )
    return "\n".join(rules)


def stylesheet(d: t.Density = t.NORMAL) -> str:
    # Pas de règle « * » sur la police : elle écraserait les QFont posées en code
    # (titres, capitales espacées). La police de base est définie par app.setFont().
    return f"""
QWidget {{ color: {C.TEXT}; outline: none; }}
QMainWindow, QDialog {{ background: {C.BG_MAIN}; }}
QWidget#LSPage {{ background: {C.BG_MAIN}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QToolTip {{ background: {C.SURFACE}; color: {C.TEXT}; border: 1px solid {C.BORDER};
    border-radius: 6px; padding: 6px 9px; font-size: {d.small_font}px; }}

/* --- Barre supérieure ---------------------------------------------------- */
QWidget#LSTopbar {{ background: {C.BG_SECONDARY}; border-bottom: 1px solid {t.BORDER_SOFT}; }}
QLabel#LSAppTitle {{ color: {C.TEXT}; }}
QLabel#LSAppSubtitle {{ color: {t.TEXT_FAINT}; }}
QLabel#LSProjectTitle {{ color: {C.TEXT}; font-weight: 600; font-size: {d.small_font}px; }}
QLabel#LSSaveState {{ color: {t.TEXT_MUTED}; font-size: {d.tiny_font + 1}px; }}
QLabel#LSSaveState[state="dirty"] {{ color: {C.WARNING}; }}
QLabel#LSSaveState[state="saved"] {{ color: {C.SUCCESS}; }}
QLineEdit#LSSearch {{ background: {t.INPUT}; border: 1px solid {C.BORDER}; border-radius: 8px;
    padding: 5px 10px 5px 30px; color: {t.TEXT_3}; font-size: {d.small_font}px; min-width: 220px; }}
QLineEdit#LSSearch:focus {{ border-color: {C.ELECTRIC}; color: {C.TEXT}; }}
QToolButton#LSWindowButton {{ border: none; border-radius: 0; background: transparent;
    min-width: 44px; min-height: {t.TITLEBAR_HEIGHT - 1}px; }}
QToolButton#LSWindowButton:hover {{ background: {t.HOVER}; }}
QToolButton#LSWindowButton[role="close"]:hover {{ background: {C.ERROR}; }}
QToolButton#LSIconButton {{ border: 1px solid transparent; border-radius: 7px; background: transparent;
    min-width: 32px; min-height: 32px; }}
QToolButton#LSIconButton:hover {{ background: {t.SURFACE_HOVER}; }}
QToolButton#LSIconButton:checked {{ background: {t.PRIMARY_SOFT}; border-color: {t.PRIMARY_BORDER}; }}
QLabel#LSCounter {{ background: {C.PRIMARY}; color: {C.TEXT}; border-radius: 8px; padding: 1px 6px;
    font-size: {d.tiny_font + 1}px; font-weight: 700; }}

/* --- Navigation latérale ------------------------------------------------- */
QWidget#LSSidebar {{ background: {C.BG_SECONDARY}; border-right: 1px solid {t.BORDER_SOFT}; }}
QPushButton#LSNavItem {{ background: transparent; border: 1px solid transparent; border-radius: {d.radius_md}px;
    color: {t.TEXT_3}; text-align: left; padding: {d.nav_padding}px 12px; min-height: 0;
    font-size: {d.small_font}px; font-weight: 500; }}
QPushButton#LSNavItem:hover {{ background: {t.HOVER}; color: {C.TEXT}; }}
QPushButton#LSNavItem:checked {{ background: {rgba(C.PRIMARY, 0.16)};
    border: 1px solid {rgba(C.PRIMARY, 0.32)}; color: {C.TEXT}; }}
QPushButton#LSNavItem[upcoming="true"] {{ color: {t.TEXT_MUTED}; }}
QPushButton#LSNavItem[upcoming="true"]:checked {{ color: {C.TEXT_SECONDARY}; }}
QLabel#LSNavSection {{ color: {t.TEXT_FAINT}; }}
QLabel#LSNavBadge {{ background: {C.SURFACE}; color: {C.TEXT_SECONDARY}; border-radius: 5px; padding: 1px 6px;
    font-size: {d.tiny_font + 1}px; }}
QLabel#LSNavDot {{ background: {C.WARNING}; border-radius: 3px; }}
QFrame#LSWorkspaceCard {{ background: {C.PANEL}; border: 1px solid {t.BORDER_SOFT}; border-radius: 10px; }}
QLabel#LSWorkspaceName {{ color: {C.TEXT}; font-weight: 600; }}
QLabel#LSWorkspaceMeta {{ color: {t.TEXT_MUTED}; font-size: {d.tiny_font + 2}px; }}
QLabel#LSVersion {{ background: {C.SURFACE}; border: 1px solid {C.BORDER}; color: {C.TEXT_SECONDARY};
    border-radius: 5px; padding: 1px 6px; font-size: {d.tiny_font}px; }}

/* --- Typographie --------------------------------------------------------- */
QLabel[role="h1"] {{ color: {C.TEXT}; }}
QLabel[role="h2"] {{ color: {C.TEXT}; font-size: {t.TypographyTokens.H2}px; font-weight: 600; }}
QLabel[role="h3"] {{ color: {C.TEXT}; font-size: {t.TypographyTokens.H3}px; font-weight: 600; }}
QLabel[role="subtitle"] {{ color: {C.TEXT_SECONDARY}; font-size: {d.small_font}px; }}
QLabel[role="muted"] {{ color: {t.TEXT_MUTED}; font-size: {d.small_font}px; }}
QLabel[role="faint"] {{ color: {t.TEXT_FAINT}; font-size: {d.tiny_font + 1}px; }}
QLabel[role="eyebrow"] {{ color: {t.TEXT_FAINT}; }}
QLabel[role="breadcrumb"] {{ color: {t.TEXT_MUTED}; font-size: {d.small_font - 1}px; }}
QLabel[role="breadcrumb-current"] {{ color: {C.TEXT}; font-size: {d.small_font - 1}px; font-weight: 600; }}
QLabel[role="value"] {{ color: {C.TEXT}; }}
QLabel[role="info"] {{ color: {t.ELECTRIC_TEXT}; font-size: {d.small_font}px; }}
QLabel[role="success"] {{ color: {C.SUCCESS}; font-size: {d.small_font}px; }}
QLabel[role="warning"] {{ color: {C.WARNING}; font-size: {d.small_font}px; }}
QLabel[role="error"] {{ color: {C.ERROR}; font-size: {d.small_font}px; }}
QLabel[role="mono"] {{ color: {t.TEXT_3}; font-size: {d.small_font - 1}px; }}

/* --- Cartes -------------------------------------------------------------- */
QFrame#LSCard {{ background: {C.PANEL}; border: 1px solid {t.BORDER_SOFT}; border-radius: {d.radius_lg}px; }}
QFrame#LSCard[interactive="true"]:hover {{ border-color: {t.PRIMARY_BORDER}; }}
QFrame#LSCard[selected="true"] {{ border-color: {C.PRIMARY}; }}
QFrame#LSHero {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {C.PANEL}, stop:1 {C.BG_SECONDARY});
    border: 1px solid {t.BORDER_SOFT}; border-radius: 14px; }}
QFrame#LSHeroCopy {{ background: transparent; border: none; }}
QLabel#LSHeroChip {{ color: {C.ELECTRIC}; }}
QFrame#LSStatsGrid {{ background: {C.PANEL}; border: 1px solid {t.BORDER_SOFT}; border-radius: 12px; }}
QFrame#LSStatCell {{ background: transparent; border: none; border-right: 1px solid {t.BORDER_SOFT}; }}
QFrame#LSStatCell[last="true"] {{ border-right: none; }}
QFrame#LSPanel {{ background: {C.PANEL}; border: 1px solid {t.BORDER_SOFT}; border-radius: 10px; }}
QFrame#LSThumb {{ background: {C.BG_SECONDARY}; border: 1px solid {t.BORDER_SOFT}; border-radius: 9px; }}
QFrame#LSSeparator {{ background: {t.BORDER_SOFT}; border: none; max-height: 1px; min-height: 1px; }}
QWidget#LSStudioPanel {{ background: {C.PANEL}; }}

/* --- Badges -------------------------------------------------------------- */
QLabel#LSBadge {{ border-radius: 6px; padding: 3px 7px; font-size: {d.tiny_font + 1}px; font-weight: 600;
    background: {C.SURFACE}; color: {C.TEXT_SECONDARY}; border: 1px solid {C.BORDER}; }}
{_badges()}

/* --- Boutons ------------------------------------------------------------- */
QPushButton {{ background: {C.SURFACE}; border: 1px solid {C.BORDER}; color: {C.TEXT};
    border-radius: {d.radius_md}px; padding: 0 14px; min-height: {d.control_height}px;
    font-size: {d.small_font}px; font-weight: 600; }}
QPushButton:hover {{ background: {t.SURFACE_HOVER}; border-color: {t.BORDER_STRONG}; }}
QPushButton:pressed {{ background: {C.PANEL}; }}
QPushButton:disabled {{ color: {t.TEXT_DISABLED}; border-color: {t.BORDER_SOFT}; background: {C.PANEL}; }}
QPushButton[variant="primary"] {{ background: {C.PRIMARY}; border-color: {C.PRIMARY}; color: {C.TEXT}; }}
QPushButton[variant="primary"]:hover {{ background: {t.PRIMARY_HOVER}; border-color: {t.PRIMARY_HOVER}; }}
QPushButton[variant="primary"]:pressed {{ background: {t.PRIMARY_PRESSED}; }}
QPushButton[variant="primary"]:disabled {{ background: {t.PRIMARY_DISABLED}; border-color: {t.PRIMARY_DISABLED};
    color: {C.TEXT_SECONDARY}; }}
QPushButton[variant="ghost"] {{ background: transparent; border-color: {C.BORDER}; color: {t.TEXT_3}; }}
QPushButton[variant="ghost"]:hover {{ background: {t.HOVER}; color: {C.TEXT}; }}
QPushButton[variant="danger"] {{ background: {t.TINT_TOKENS["red"].background}; color: {C.ERROR};
    border-color: {t.TINT_TOKENS["red"].border}; }}
QPushButton[variant="danger"]:hover {{ border-color: {C.ERROR}; color: {C.TEXT}; }}
QPushButton[size="small"] {{ min-height: {d.control_height - 8}px; padding: 0 11px; font-size: {d.small_font - 1}px; }}
QPushButton[chip="true"] {{ font-weight: 500; padding: 0 14px; }}
QPushButton[chip="true"]:checked {{ background: {rgba(C.PRIMARY, 0.18)}; border-color: {C.PRIMARY}; }}

QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 7px;
    padding: 4px 7px; color: {t.TEXT_3}; }}
QToolButton:hover {{ background: {t.SURFACE_HOVER}; color: {C.TEXT}; }}
QToolButton:checked {{ background: {rgba(C.PRIMARY, 0.2)}; border-color: {t.PRIMARY_BORDER}; color: {C.TEXT}; }}
QToolButton:disabled {{ color: {t.TEXT_DISABLED}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

/* --- Champs -------------------------------------------------------------- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {t.INPUT}; border: 1px solid {C.BORDER}; border-radius: 7px; padding: 4px 9px;
    color: {C.TEXT}; selection-background-color: {C.PRIMARY}; min-height: {d.control_height - 14}px; }}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {t.BORDER_STRONG}; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {C.ELECTRIC}; }}
QLineEdit:read-only {{ color: {t.TEXT_3}; }}
QLineEdit:disabled, QComboBox:disabled, QDoubleSpinBox:disabled {{ color: {t.TEXT_DISABLED}; }}
QAbstractSpinBox {{ padding-right: 2px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 12px; border: none; background: transparent; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {C.PANEL}; border: 1px solid {C.BORDER}; border-radius: 8px;
    selection-background-color: {rgba(C.PRIMARY, 0.25)}; selection-color: {C.TEXT}; padding: 4px; }}
QDoubleSpinBox[axis="x"] {{ border-left: 2px solid {t.AXIS_X}; }}
QDoubleSpinBox[axis="y"] {{ border-left: 2px solid {t.AXIS_Y}; }}
QDoubleSpinBox[axis="z"] {{ border-left: 2px solid {t.AXIS_Z}; }}
QCheckBox {{ spacing: 8px; color: {C.TEXT}; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid {t.BORDER_STRONG}; border-radius: 4px;
    background: {t.INPUT}; }}
QCheckBox::indicator:checked {{ background: {C.PRIMARY}; border-color: {C.PRIMARY}; }}
QSlider::groove:horizontal {{ height: 4px; background: {C.SURFACE}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {C.PRIMARY}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {C.TEXT}; width: 12px; height: 12px; margin: -5px 0; border-radius: 6px; }}
QSlider::handle:horizontal:hover {{ background: {C.ELECTRIC}; }}
QProgressBar {{ background: {C.SURFACE}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px;
    text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {C.PRIMARY}, stop:1 {C.ELECTRIC});
    border-radius: 3px; }}

/* --- Onglets ------------------------------------------------------------- */
QTabWidget::pane {{ border: none; }}
QTabBar {{ background: transparent; qproperty-drawBase: 0; }}
QTabBar::tab {{ background: transparent; color: {t.TEXT_MUTED}; border: none; border-bottom: 2px solid transparent;
    padding: 6px 2px 9px 2px; margin-right: 16px; font-size: {d.small_font - 1}px; font-weight: 600; }}
QTabBar::tab:hover {{ color: {C.TEXT}; }}
QTabBar::tab:selected {{ color: {C.TEXT}; border-bottom-color: {C.ELECTRIC}; }}

/* --- Listes, arbres, tableaux -------------------------------------------- */
QTreeView, QListView, QTreeWidget, QListWidget, QTableView, QTableWidget {{ background: transparent; border: none;
    alternate-background-color: transparent; gridline-color: {t.BORDER_SOFT}; }}
QTreeView::item, QListView::item {{ padding: 4px 2px; border-radius: 6px; color: {C.TEXT}; }}
QTreeView::item:hover, QListView::item:hover {{ background: {t.HOVER}; }}
QTreeView::item:selected, QListView::item:selected, QTableView::item:selected {{
    background: {rgba(C.PRIMARY, 0.28)}; color: {C.TEXT}; }}
QTreeView {{ show-decoration-selected: 0; }}
QTreeView::branch, QTreeView::branch:selected {{ background: transparent; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: transparent; color: {t.TEXT_FAINT}; border: none;
    border-bottom: 1px solid {t.BORDER_SOFT}; padding: 4px 6px; font-weight: 600; }}

/* --- Séparateurs redimensionnables --------------------------------------- */
QMainWindow::separator {{ background: {t.BORDER_SOFT}; width: 1px; height: 1px; }}
QMainWindow::separator:hover {{ background: {C.PRIMARY}; }}
QSplitter::handle {{ background: {t.BORDER_SOFT}; }}
QSplitter::handle:hover {{ background: {C.PRIMARY}; }}

/* --- Menus --------------------------------------------------------------- */
QMenu {{ background: {C.PANEL}; border: 1px solid {C.BORDER}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 6px; color: {C.TEXT}; }}
QMenu::item:selected {{ background: {rgba(C.PRIMARY, 0.25)}; color: {C.TEXT}; }}
QMenu::item:disabled {{ color: {t.TEXT_DISABLED}; }}
QMenu::separator {{ height: 1px; background: {t.BORDER_SOFT}; margin: 5px 8px; }}
QMenu::icon {{ padding-left: 8px; }}

/* --- Barres de défilement discrètes -------------------------------------- */
QScrollBar:vertical {{ background: transparent; width: 6px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {C.BORDER}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {t.BORDER_STRONG}; }}
QScrollBar:horizontal {{ background: transparent; height: 6px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {C.BORDER}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

/* --- Notifications et fenêtres modales ----------------------------------- */
QFrame#LSToast {{ background: {C.PANEL}; border: 1px solid {C.BORDER}; border-radius: 10px; }}
QFrame#LSToast[level="success"] {{ border-color: {t.TINT_TOKENS["green"].border}; }}
QFrame#LSToast[level="warning"] {{ border-color: {t.TINT_TOKENS["amber"].border}; }}
QFrame#LSToast[level="error"] {{ border-color: {t.TINT_TOKENS["red"].border}; }}
QDialog#LSModal {{ background: {C.PANEL}; }}
QFrame#LSModalHeader {{ background: {C.BG_SECONDARY}; border-bottom: 1px solid {t.BORDER_SOFT}; }}
QFrame#LSModalActions {{ border-top: 1px solid {t.BORDER_SOFT}; }}

/* --- Viewport ------------------------------------------------------------ */
QFrame#LSViewportToolbar {{ background: {rgba(C.BG_SECONDARY, 0.92)}; border: 1px solid {t.BORDER_SOFT};
    border-radius: 9px; }}
QLabel#LSViewportHint {{ color: {t.TEXT_MUTED}; background: {rgba(C.BG_MAIN, 0.75)}; border-radius: 6px;
    padding: 4px 9px; font-size: {d.tiny_font + 1}px; }}
QLabel#LSViewportError {{ color: {C.ERROR}; background: {rgba(C.BG_MAIN, 0.92)};
    border: 1px solid {t.TINT_TOKENS["red"].border}; border-radius: 10px; padding: 16px; }}
QPlainTextEdit#LSLog, QPlainTextEdit#LSCode {{ background: {C.BG_MAIN}; border: none; border-radius: 0;
    font-size: {d.small_font - 1}px; }}
QLabel#LSTexturePreview {{ background: {C.BG_MAIN}; border: 1px solid {t.BORDER_SOFT}; border-radius: 8px; }}
"""


class ComponentStyles:
    """Point d'accès au style des composants (feuille QSS + palette Qt)."""

    stylesheet = staticmethod(stylesheet)

    @staticmethod
    def palette() -> QPalette:
        palette = QPalette()
        roles = {
            QPalette.ColorRole.Window: C.BG_MAIN,
            QPalette.ColorRole.WindowText: C.TEXT,
            QPalette.ColorRole.Base: t.INPUT,
            QPalette.ColorRole.AlternateBase: C.PANEL,
            QPalette.ColorRole.Text: C.TEXT,
            QPalette.ColorRole.Button: C.SURFACE,
            QPalette.ColorRole.ButtonText: C.TEXT,
            QPalette.ColorRole.Highlight: C.PRIMARY,
            QPalette.ColorRole.HighlightedText: C.TEXT,
            QPalette.ColorRole.ToolTipBase: C.SURFACE,
            QPalette.ColorRole.ToolTipText: C.TEXT,
            QPalette.ColorRole.PlaceholderText: t.TEXT_MUTED,
            QPalette.ColorRole.Link: C.ELECTRIC,
        }
        for role, color in roles.items():
            palette.setColor(role, QColor(color))
        for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
            palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(t.TEXT_DISABLED))
        return palette


def apply_design(app: QApplication, compact: bool = False) -> None:
    """Applique polices, palette et feuille de style à toute l'application."""
    global _density
    _density = t.COMPACT if compact else t.NORMAL
    fonts.load_fonts()
    app.setStyle("Fusion")
    app.setFont(fonts.font(_density.base_font))
    app.setPalette(ComponentStyles.palette())
    app.setStyleSheet(stylesheet(_density))
