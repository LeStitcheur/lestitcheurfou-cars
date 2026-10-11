"""Design system « Dark Premium — Automotive Creation Studio ».

Source unique des valeurs graphiques. Aucune couleur ne doit être écrite en dur ailleurs :
les modules d'interface lisent ``ColorTokens`` (ou les alias de compatibilité en bas de fichier).

La palette officielle compte douze couleurs ; les nuances intermédiaires (survols, fonds teintés,
bordures actives) sont *dérivées* de ces douze valeurs par mélange (``mix``) ou transparence
(``rgba``), jamais inventées. Les couleurs d'état (succès, avertissement, erreur) ne servent qu'à
communiquer un état.
"""

from __future__ import annotations

from dataclasses import dataclass


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def mix(a: str, b: str, amount: float) -> str:
    """Mélange ``a`` vers ``b`` (0 = a, 1 = b). Sert à dériver les nuances de la palette."""
    ra, ga, ba = _hex_to_rgb(a)
    rb, gb, bb = _hex_to_rgb(b)
    channels = (ra + (rb - ra) * amount, ga + (gb - ga) * amount, ba + (bb - ba) * amount)
    return "#" + "".join(f"{round(c):02x}" for c in channels)


def rgba(color: str, alpha: float) -> str:
    """Couleur de la palette avec transparence, au format QSS ``rgba(r, g, b, a)``."""
    r, g, b = _hex_to_rgb(color)
    return f"rgba({r}, {g}, {b}, {alpha:.2f})"


# --- Couleurs -----------------------------------------------------------------
class ColorTokens:
    """Les douze couleurs officielles."""

    BG_MAIN = "#0b0e14"
    BG_SECONDARY = "#111722"
    PANEL = "#151b26"
    SURFACE = "#202a3b"
    BORDER = "#2a3445"
    PRIMARY = "#2563eb"  # bleu principal : sélection, boutons principaux, éléments actifs
    ELECTRIC = "#38bdf8"  # bleu électrique : accents, focus, indicateurs actifs
    TEXT = "#f3f6fc"
    TEXT_SECONDARY = "#94a3b8"
    SUCCESS = "#22c55e"
    WARNING = "#f59e0b"
    ERROR = "#ef4444"

    PALETTE = (
        BG_MAIN,
        BG_SECONDARY,
        PANEL,
        SURFACE,
        BORDER,
        PRIMARY,
        ELECTRIC,
        TEXT,
        TEXT_SECONDARY,
        SUCCESS,
        WARNING,
        ERROR,
    )


C = ColorTokens

# Nuances dérivées (toutes calculées depuis la palette)
SURFACE_HOVER = mix(C.SURFACE, C.BORDER, 0.65)
INPUT = mix(C.BG_SECONDARY, C.PANEL, 0.5)
HOVER = mix(C.PANEL, C.SURFACE, 0.55)
BORDER_SOFT = mix(C.BORDER, C.PANEL, 0.45)
BORDER_STRONG = mix(C.BORDER, C.TEXT_SECONDARY, 0.18)
TEXT_STRONG = C.TEXT
TEXT_2 = C.TEXT_SECONDARY
TEXT_3 = mix(C.TEXT_SECONDARY, C.TEXT, 0.25)
TEXT_MUTED = mix(C.TEXT_SECONDARY, C.BG_MAIN, 0.3)
TEXT_FAINT = mix(C.TEXT_SECONDARY, C.BG_MAIN, 0.48)
TEXT_DISABLED = mix(C.TEXT_SECONDARY, C.BG_MAIN, 0.6)
PRIMARY_HOVER = mix(C.PRIMARY, C.ELECTRIC, 0.22)
PRIMARY_PRESSED = mix(C.PRIMARY, C.BG_MAIN, 0.18)
PRIMARY_SOFT = mix(C.PRIMARY, C.PANEL, 0.78)  # fond d'élément actif
PRIMARY_BORDER = mix(C.PRIMARY, C.PANEL, 0.45)
PRIMARY_DISABLED = mix(C.PRIMARY, C.PANEL, 0.7)
ELECTRIC_TEXT = mix(C.ELECTRIC, C.TEXT, 0.15)


@dataclass(frozen=True)
class Tint:
    background: str
    foreground: str
    border: str


def _tint(color: str, fg_amount: float = 0.25) -> Tint:
    return Tint(mix(color, C.PANEL, 0.82), mix(color, C.TEXT, fg_amount), mix(color, C.PANEL, 0.6))


# Badges et conteneurs d'icônes : bleu et neutre pour l'information, vert/ambre/rouge pour l'état.
TINT_TOKENS: dict[str, Tint] = {
    "blue": _tint(C.PRIMARY, 0.45),
    "electric": _tint(C.ELECTRIC, 0.2),
    "green": _tint(C.SUCCESS),
    "amber": _tint(C.WARNING),
    "red": _tint(C.ERROR),
    "neutral": Tint(C.SURFACE, C.TEXT_SECONDARY, C.BORDER),
}

# Repères techniques des axes X/Y/Z : convention universelle des outils 3D,
# exprimée avec les couleurs de la palette.
AXIS_X = C.ERROR
AXIS_Y = C.SUCCESS
AXIS_Z = mix(C.PRIMARY, C.ELECTRIC, 0.35)


# --- Typographie --------------------------------------------------------------
class TypographyTokens:
    """Polices système Windows : sobres, lisibles, sans fichier tiers embarqué."""

    TEXT_FAMILIES = ("Segoe UI Variable Text", "Segoe UI", "Arial")
    DISPLAY_FAMILIES = ("Segoe UI Variable Display", "Segoe UI Semibold", "Segoe UI", "Arial")
    MONO_FAMILIES = ("Cascadia Mono", "Consolas", "Courier New")
    H1 = 26
    H2 = 17
    H3 = 14
    EYEBROW_SPACING = 1.3


# --- Espacements et densité ---------------------------------------------------
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
    radius_sm: int = 6
    radius_md: int = 8
    radius_lg: int = 12


class SpacingTokens:
    XS = 4
    SM = 8
    MD = 12
    LG = 16
    XL = 24
    XXL = 32
    NORMAL = Density("normal", 13, 12, 9, 36, 9, 3, 20, 28)
    COMPACT = Density("compact", 12, 11, 8, 30, 6, 2, 14, 18)
    SIDEBAR_WIDTH = 224
    SIDEBAR_COLLAPSED_WIDTH = 60
    TITLEBAR_HEIGHT = 44


# --- Animations ---------------------------------------------------------------
class AnimationTokens:
    FAST_MS = 120
    NORMAL_MS = 170
    SLOW_MS = 260
    TOAST_MS = 4200
    EASING = "OutCubic"


@dataclass(frozen=True)
class AppTheme:
    """Thème actif : regroupe les familles de tokens et la densité choisie."""

    name: str = "Dark Premium"
    colors: type[ColorTokens] = ColorTokens
    typography: type[TypographyTokens] = TypographyTokens
    spacing: type[SpacingTokens] = SpacingTokens
    animation: type[AnimationTokens] = AnimationTokens
    density: Density = SpacingTokens.NORMAL


THEME = AppTheme()


def tint(name: str) -> tuple[str, str, str]:
    value = TINT_TOKENS.get(name, TINT_TOKENS["neutral"])
    return value.background, value.foreground, value.border


# --- Alias de compatibilité (noms historiques utilisés dans l'interface) -------
BG = C.BG_MAIN
BG_RAISED = C.BG_SECONDARY
TITLEBAR = C.BG_SECONDARY
SIDEBAR = C.BG_SECONDARY
SIDEBAR_BORDER = BORDER_SOFT
PANEL = C.PANEL
CARD = C.PANEL
SURFACE = C.SURFACE
BORDER = C.BORDER
DIVIDER = BORDER_SOFT
TEXT = C.TEXT
ACCENT = C.PRIMARY
ACCENT_2 = C.ELECTRIC
ACCENT_HOVER = PRIMARY_HOVER
ACCENT_TEXT = ELECTRIC_TEXT
ACCENT_DARK = PRIMARY_SOFT
ACCENT_BORDER = PRIMARY_BORDER
TEXT_INFO = ELECTRIC_TEXT
SUCCESS = C.SUCCESS
WARNING = C.WARNING
ERROR = C.ERROR

NORMAL = SpacingTokens.NORMAL
COMPACT = SpacingTokens.COMPACT
SIDEBAR_WIDTH = SpacingTokens.SIDEBAR_WIDTH
SIDEBAR_COLLAPSED_WIDTH = SpacingTokens.SIDEBAR_COLLAPSED_WIDTH
TITLEBAR_HEIGHT = SpacingTokens.TITLEBAR_HEIGHT
