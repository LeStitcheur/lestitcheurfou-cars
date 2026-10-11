"""Polices système (Segoe UI Variable / Segoe UI) : aucune police tierce embarquée."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtGui import QFont, QFontDatabase

from lsfcars.core.logging_setup import get_logger
from lsfcars.ui.design.tokens import TypographyTokens

log = get_logger(__name__)

_families: dict[str, str] = {}


def _first_available(candidates: tuple[str, ...]) -> str:
    available = set(QFontDatabase.families())
    return next((name for name in candidates if name in available), candidates[-1])


def load_fonts() -> dict[str, str]:
    """Choisit les familles disponibles. Retourne {'text', 'brand', 'mono'}."""
    if _families:
        return dict(_families)
    _families["text"] = _first_available(TypographyTokens.TEXT_FAMILIES)
    _families["brand"] = _first_available(TypographyTokens.DISPLAY_FAMILIES)
    _families["mono"] = _first_available(TypographyTokens.MONO_FAMILIES)
    log.debug("Polices : %s", _families)
    return dict(_families)


def text_family() -> str:
    return load_fonts()["text"]


def brand_family() -> str:
    return load_fonts()["brand"]


def clear_caches() -> None:
    _font.cache_clear()


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
    """Police de texte. Le QSS ne gère pas l'espacement des lettres : d'où cette API."""
    return QFont(_font(text_family(), px, weight, spacing, caps))


def brand_font(px: int, weight: int = 600, spacing: float = 0.0) -> QFont:
    """Police d'affichage (titres)."""
    return QFont(_font(brand_family(), px, weight, spacing, False))


def mono_font(px: int) -> QFont:
    return QFont(_font(load_fonts()["mono"], px, 400, 0.0, False))
