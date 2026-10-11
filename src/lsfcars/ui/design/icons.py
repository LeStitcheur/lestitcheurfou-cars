"""Icônes Lucide (SVG à trait fin) colorées à la volée."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from lsfcars.core.paths import resources_dir
from lsfcars.ui.design import tokens


@lru_cache(maxsize=128)
def _svg_source(name: str) -> bytes:
    path = resources_dir() / "icons" / f"{name}.svg"
    if not path.is_file():
        raise FileNotFoundError(f"Icône inconnue : {name}")
    return path.read_bytes()


def _device_ratio() -> float:
    app = QGuiApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    return max(screen.devicePixelRatio(), 1.0) if screen is not None else 1.0


def _render(renderer: QSvgRenderer, size: int) -> QPixmap:
    ratio = _device_ratio()
    side = max(int(round(size * ratio)), 1)
    image = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, side, side))
    painter.end()
    result = QPixmap.fromImage(image)
    result.setDevicePixelRatio(ratio)
    return result


@lru_cache(maxsize=512)
def pixmap(name: str, color: str = tokens.TEXT_3, size: int = 18) -> QPixmap:
    svg = _svg_source(name).replace(b"currentColor", color.encode())
    return _render(QSvgRenderer(QByteArray(svg)), size)


@lru_cache(maxsize=256)
def icon(
    name: str,
    color: str = tokens.TEXT_3,
    active: str | None = None,
    disabled: str = tokens.TEXT_FAINT,
    size: int = 18,
) -> QIcon:
    """QIcon avec variantes normale, active (survol / coché) et désactivée."""
    hot = active or color
    result = QIcon()
    result.addPixmap(pixmap(name, color, size), QIcon.Mode.Normal, QIcon.State.Off)
    result.addPixmap(pixmap(name, hot, size), QIcon.Mode.Active, QIcon.State.Off)
    result.addPixmap(pixmap(name, hot, size), QIcon.Mode.Selected, QIcon.State.Off)
    result.addPixmap(pixmap(name, hot, size), QIcon.Mode.Normal, QIcon.State.On)
    result.addPixmap(pixmap(name, hot, size), QIcon.Mode.Active, QIcon.State.On)
    result.addPixmap(pixmap(name, disabled, size), QIcon.Mode.Disabled, QIcon.State.Off)
    return result


def clear_caches() -> None:
    """Libère les QPixmap / QIcon en cache avant l'arrêt de l'application (ordre de destruction Qt)."""
    for cached in (pixmap, icon, logo):
        cached.cache_clear()


@lru_cache(maxsize=16)
def logo(size: int) -> QPixmap:
    """Logo de l'application (icône LeStitcheurFou Cars)."""
    source = QPixmap(str(resources_dir() / "icon.png"))
    if source.isNull():
        return QPixmap()
    ratio = _device_ratio()
    side = max(int(round(size * ratio)), 1)
    result = source.scaled(
        side, side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )
    result.setDevicePixelRatio(ratio)
    return result


def icon_size(px: int) -> QSize:
    return QSize(px, px)
