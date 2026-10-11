"""Chargement des polices de marque (DM Sans, Barlow Condensed — OFL 1.1)."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtGui import QFont, QFontDatabase

from lsfcars.core.logging_setup import get_logger
from lsfcars.core.paths import resources_dir
from lsfcars.ui.design import tokens

log = get_logger(__name__)

_families: dict[str, str] = {}


def load_fonts() -> dict[str, str]:
    """Enregistre les polices embarquées. Retourne {'text': famille, 'brand': famille}."""
    if _families:
        return dict(_families)
    folder = resources_dir() / "fonts"
    for path in sorted(folder.glob("*.ttf")):
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            log.warning("Police non chargée : %s", path.name)
            continue
        family = QFontDatabase.applicationFontFamilies(font_id)[0]
        if path.name.startswith("DMSans"):
            _families.setdefault("text", family)
        elif path.name.startswith("BarlowCondensed"):
            _families.setdefault("brand", family)
    _families.setdefault("text", tokens.FONT_TEXT_FALLBACK)
    _families.setdefault("brand", tokens.FONT_BRAND_FALLBACK)
    log.debug("Polices : %s", _families)
    return dict(_families)


def text_family() -> str:
    return load_fonts()["text"]


def brand_family() -> str:
    return load_fonts()["brand"]


@lru_cache(maxsize=64)
def _font(family: str, px: int, weight: int, spacing: float, caps: bool) -> QFont:
    font = QFont(family)
    font.setPixelSize(px)
    font.setWeight(QFont.Weight(weight))
    if spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    if caps:
        font.setCapitalization(QFont.Capitalization.AllUppercase)
    return font


def font(px: int, weight: int = 400, spacing: float = 0.0, caps: bool = False) -> QFont:
    """Police de texte (DM Sans). Le QSS ne gère pas l'espacement des lettres : d'où cette API."""
    return QFont(_font(text_family(), px, weight, spacing, caps))


def brand_font(px: int, weight: int = 700, spacing: float = 1.0) -> QFont:
    return QFont(_font(brand_family(), px, weight, spacing, False))
