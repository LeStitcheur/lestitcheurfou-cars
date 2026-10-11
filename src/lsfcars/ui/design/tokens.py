"""Tokens graphiques : couleurs, typographie, espacements, rayons.

Valeurs relevées dans LeStitcheur Control 2.10 (``src/design.css``, couche « workspace 2 »),
qui prime sur la palette indicative du cahier des charges lorsqu'elles diffèrent.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Couleurs ---------------------------------------------------------------
BG = "#090b0e"  # fond de l'application
BG_RAISED = "#0e1117"  # zone de contenu
TITLEBAR = "#0d1014"
SIDEBAR = "#0d1014"
SIDEBAR_BORDER = "#20252c"
PANEL = "#11151a"
CARD = "#12171d"
CARD_ALT = "#141316"  # bannière
SURFACE = "#1b222b"  # boutons secondaires, champs actifs
SURFACE_HOVER = "#242e3a"
INPUT = "#141920"
HOVER = "#191f26"
BORDER = "#29313b"
BORDER_SOFT = "#20252c"
BORDER_STRONG = "#303b48"
DIVIDER = "#262f39"

ACCENT = "#ff4157"  # couleur de marque
ACCENT_2 = "#ff5268"
ACCENT_HOVER = "#ff647f"
ACCENT_TEXT = "#ff7384"
ACCENT_DARK = "#35151f"
ACCENT_BORDER = "#5f2a38"

TEXT = "#f4f6f9"
TEXT_STRONG = "#ffffff"
TEXT_2 = "#94a8c3"  # sous-titres bleu gris
TEXT_3 = "#8e98a6"  # navigation, labels
TEXT_MUTED = "#687587"
TEXT_FAINT = "#596675"  # catégories en petites capitales
TEXT_INFO = "#8db9eb"

SUCCESS = "#2cc58a"
WARNING = "#f4b54a"
ERROR = "#ff526e"

# Conteneurs d'icônes et badges (fond, texte, bordure)
TINTS: dict[str, tuple[str, str, str]] = {
    "red": ("#3c1c29", "#f97b91", "#66313f"),
    "blue": ("#192c3d", "#75c0ed", "#2b4a66"),
    "violet": ("#28223b", "#b49eee", "#463b5e"),
    "amber": ("#362d1d", "#e1b875", "#5b4527"),
    "green": ("#12372a", "#7fe1b1", "#24523e"),
    "neutral": ("#222a33", "#a7b2c0", "#35404d"),
}

# Repères techniques des axes (volontairement hors palette de marque)
AXIS_X = "#ff5b5b"
AXIS_Y = "#7bd88f"
AXIS_Z = "#4f9dff"

# --- Typographie ------------------------------------------------------------
FONT_TEXT_FALLBACK = "Segoe UI"
FONT_BRAND_FALLBACK = "Bahnschrift SemiCondensed"


@dataclass(frozen=True)
class Density:
    """Échelle d'espacement : normale ou compacte (paramètre utilisateur)."""

    name: str
    base_font: int  # px
    small_font: int
    tiny_font: int  # catégories, labels en capitales
    control_height: int
    nav_padding: int
    nav_spacing: int
    card_padding: int
    page_padding: int
    radius_sm: int = 7
    radius_md: int = 9
    radius_lg: int = 15


NORMAL = Density("normal", 13, 12, 9, 38, 11, 4, 22, 32)
COMPACT = Density("compact", 12, 11, 8, 30, 7, 2, 14, 20)

SIDEBAR_WIDTH = 236
SIDEBAR_COLLAPSED_WIDTH = 64
TITLEBAR_HEIGHT = 46


def tint(name: str) -> tuple[str, str, str]:
    return TINTS.get(name, TINTS["neutral"])
