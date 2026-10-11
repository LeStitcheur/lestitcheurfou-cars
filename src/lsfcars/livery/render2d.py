"""Rendu des calques vectoriels, texte et image (QtGui : ``QPainter`` sur ``QImage``).

Chaque calque est rendu dans son seul rectangle englobant (``(x0, y0, rgba)``) : les petits
éléments (logos, textes, formes) ne coûtent pas une image pleine résolution. Les paramètres
restent éditables ; le rendu est recalculé seulement quand ils changent (cache du
compositeur). Fonctionne sans fenêtre (une ``QGuiApplication`` suffit pour les polices).
"""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontDatabase,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPolygonF,
    QRadialGradient,
    QTransform,
)
from PySide6.QtSvg import QSvgRenderer

from lsfcars.livery import raster
from lsfcars.livery.model import Layer, rgba

FALLBACK_FAMILIES = ("Bahnschrift", "Segoe UI", "Arial", "DejaVu Sans", "Liberation Sans")
_font_families: dict[str, str] = {}  # blob → famille enregistrée
_source_cache: dict[tuple[str, int, int], QImage] = {}


# --- Conversions -------------------------------------------------------------------------------


def qimage_from_rgba(array: np.ndarray) -> QImage:
    """Copie (H, W, 4) uint8 non prémultiplié → QImage RGBA8888."""
    array = np.ascontiguousarray(array, dtype=np.uint8)
    h, w = array.shape[:2]
    image = QImage(array.data, w, h, w * 4, QImage.Format.Format_RGBA8888)
    return image.copy()


def rgba_from_qimage(image: QImage) -> np.ndarray:
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = converted.width(), converted.height()
    data = np.frombuffer(converted.constBits(), np.uint8, count=converted.sizeInBytes())
    return data.reshape(h, converted.bytesPerLine())[:, : w * 4].reshape(h, w, 4).copy()


def qcolor(value: str, alpha: float = 1.0) -> QColor:
    r, g, b, a = rgba(value)
    return QColor(r, g, b, int(round(a * max(0.0, min(1.0, alpha)))))


def default_family() -> str:
    families = set(QFontDatabase.families())
    fallback = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family()
    return next((f for f in FALLBACK_FAMILIES if f in families), fallback)


def register_font(key: str, data: bytes) -> str | None:
    """Enregistre une police importée (blob du projet) ; retourne sa famille."""
    if key in _font_families:
        return _font_families[key]
    font_id = QFontDatabase.addApplicationFontFromData(QByteArray(data))
    if font_id < 0:
        return None
    families = QFontDatabase.applicationFontFamilies(font_id)
    if not families:
        return None
    _font_families[key] = families[0]
    return families[0]


def _canvas(rect: QRectF, width: int, height: int) -> tuple[int, int, QImage] | None:
    x0 = max(int(math.floor(rect.left())), 0)
    y0 = max(int(math.floor(rect.top())), 0)
    x1 = min(int(math.ceil(rect.right())), width)
    y1 = min(int(math.ceil(rect.bottom())), height)
    if x1 <= x0 or y1 <= y0:
        return None
    image = QImage(x1 - x0, y1 - y0, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    return x0, y0, image


def _painter(image: QImage, x0: int, y0: int) -> QPainter:
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.translate(-x0, -y0)
    return painter


# --- Formes vectorielles ------------------------------------------------------------------------


def _catmull_rom(points: list[QPointF], closed: bool) -> QPainterPath:
    path = QPainterPath(points[0])
    n = len(points)
    count = n if closed else n - 1
    for i in range(count):
        p0 = points[(i - 1) % n] if (closed or i > 0) else points[i]
        p1, p2 = points[i], points[(i + 1) % n]
        p3 = points[(i + 2) % n] if (closed or i + 2 < n) else p2
        c1 = p1 + (p2 - p0) / 6.0
        c2 = p2 - (p3 - p1) / 6.0
        path.cubicTo(c1, c2, p2)
    if closed:
        path.closeSubpath()
    return path


def shape_path(params: dict) -> QPainterPath:
    """Chemin de la forme (coordonnées de la texture) avant rotation."""
    shape = params.get("shape", "rect")
    pts = [QPointF(float(x), float(y)) for x, y in params.get("points") or []]
    path = QPainterPath()
    if len(pts) < 2:
        return path
    p0, p1 = pts[0], pts[1]
    box = QRectF(p0, p1).normalized()
    if shape == "line":
        path.moveTo(p0)
        for p in pts[1:]:
            path.lineTo(p)
    elif shape == "rect":
        path.addRect(box)
    elif shape == "rounded_rect":
        radius = float(params.get("radius", 16.0))
        path.addRoundedRect(box, radius, radius)
    elif shape == "ellipse":
        path.addEllipse(box)
    elif shape == "circle":
        r = math.hypot(p1.x() - p0.x(), p1.y() - p0.y())
        path.addEllipse(p0, r, r)
    elif shape == "polygon":
        path.addPolygon(QPolygonF(pts))
        path.closeSubpath()
    elif shape == "curve":
        path = _catmull_rom(pts, bool(params.get("closed", False)))
    return path


def _rotation(params: dict, rect: QRectF) -> QTransform:
    angle = float(params.get("rotation", 0.0))
    transform = QTransform()
    if angle:
        c = rect.center()
        transform.translate(c.x(), c.y())
        transform.rotate(angle)
        transform.translate(-c.x(), -c.y())
    return transform


def _is_line(params: dict) -> bool:
    return params.get("shape") == "line" or (params.get("shape") == "curve" and not params.get("closed"))


def render_vector(layer: Layer, width: int, height: int) -> tuple[int, int, np.ndarray] | None:
    params = layer.params
    path = shape_path(params)
    if path.isEmpty():
        return None
    path = _rotation(params, path.boundingRect()).map(path)
    line = _is_line(params)
    stroke_width = float(params.get("stroke_width", 0.0)) if (params.get("stroke") or line) else 0.0
    if line and stroke_width <= 0:
        stroke_width = 4.0
    margin = stroke_width / 2 + 2
    canvas = _canvas(path.boundingRect().adjusted(-margin, -margin, margin, margin), width, height)
    if canvas is None:
        return None
    x0, y0, image = canvas
    painter = _painter(image, x0, y0)
    if not line:
        gradient = params.get("gradient")
        if gradient:
            a = QPointF(*gradient.get("p0", (0, 0)))
            b = QPointF(*gradient.get("p1", (100, 0)))
            if gradient.get("kind") == "radial":
                grad = QRadialGradient(a, max(math.hypot(b.x() - a.x(), b.y() - a.y()), 1.0))
            else:
                grad = QLinearGradient(a, b)
            grad.setColorAt(0.0, qcolor(gradient.get("c0", "#FFFFFF")))
            grad.setColorAt(1.0, qcolor(gradient.get("c1", "#000000")))
            painter.fillPath(path, QBrush(grad))
        elif params.get("fill"):
            painter.fillPath(path, qcolor(params["fill"]))
    if stroke_width > 0:
        pen = QPen(qcolor(params.get("stroke") or params.get("fill") or "#FFFFFF"), stroke_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.strokePath(path, pen)
    painter.end()
    return x0, y0, rgba_from_qimage(image)


# --- Texte ---------------------------------------------------------------------------------------


def text_font(params: dict, blobs: dict[str, bytes] | None = None) -> QFont:
    family = params.get("font_family") or default_family()
    blob = params.get("font_blob")
    if blob and blobs and blob in blobs:
        family = register_font(blob, blobs[blob]) or family
    font = QFont(family)
    font.setPixelSize(max(1, int(round(float(params.get("size", 64.0))))))
    font.setBold(bool(params.get("bold", False)))
    font.setItalic(bool(params.get("italic", False)))
    spacing = float(params.get("letter_spacing", 0.0))
    if spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return font


def text_path(params: dict, blobs: dict[str, bytes] | None = None) -> QPainterPath:
    """Chemin du texte centré sur l'origine (lignes alignées), avant transformation."""
    font = text_font(params, blobs)
    lines = str(params.get("text", "")).split("\n") or [""]
    size = float(params.get("size", 64.0))
    line_height = size * 1.2 * float(params.get("line_spacing", 1.0))
    paths = []
    for line in lines:
        path = QPainterPath()
        path.addText(0, 0, font, line)
        paths.append(path)
    widths = [p.boundingRect().right() if not p.isEmpty() else 0.0 for p in paths]
    block = max(widths) if widths else 0.0
    align = params.get("align", "center")
    result = QPainterPath()
    for index, (path, w) in enumerate(zip(paths, widths, strict=True)):
        dx = {"left": 0.0, "right": block - w}.get(align, (block - w) / 2)
        result.addPath(QTransform.fromTranslate(dx, index * line_height).map(path))
    rect = result.boundingRect()
    return QTransform.fromTranslate(-block / 2, -(rect.top() + rect.bottom()) / 2).map(result)


def placement_transform(params: dict) -> QTransform:
    transform = QTransform()
    transform.translate(float(params.get("x", 0.0)), float(params.get("y", 0.0)))
    transform.rotate(float(params.get("rotation", 0.0)))
    sx = float(params.get("scale_x", 1.0)) * (-1.0 if params.get("flip_h") else 1.0)
    sy = float(params.get("scale_y", 1.0)) * (-1.0 if params.get("flip_v") else 1.0)
    transform.scale(sx, sy)
    return transform


def render_text(layer: Layer, width: int, height: int, blobs: dict[str, bytes] | None = None):  # type: ignore[no-untyped-def]
    params = layer.params
    if not str(params.get("text", "")).strip():
        return None
    path = placement_transform(params).map(text_path(params, blobs))
    outline = float(params.get("outline_width", 0.0))
    shadow = params.get("shadow") or {}
    shadow_on = bool(shadow.get("enabled"))
    dx, dy = float(shadow.get("dx", 6.0)), float(shadow.get("dy", 6.0))
    blur = int(shadow.get("blur", 4)) if shadow_on else 0
    margin = outline + 3 + blur * 3 + (max(abs(dx), abs(dy)) if shadow_on else 0)
    canvas = _canvas(path.boundingRect().adjusted(-margin, -margin, margin, margin), width, height)
    if canvas is None:
        return None
    x0, y0, image = canvas
    outline_path = None
    if outline > 0:
        stroker = QPainterPathStroker()
        stroker.setWidth(outline * 2)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        outline_path = stroker.createStroke(path).united(path)
    if shadow_on:
        mask = QImage(image.size(), QImage.Format.Format_ARGB32_Premultiplied)
        mask.fill(Qt.GlobalColor.transparent)
        painter = _painter(mask, x0, y0)
        painter.translate(dx, dy)
        painter.fillPath(outline_path if outline_path is not None else path, QColor(255, 255, 255))
        painter.end()
        alpha = rgba_from_qimage(mask)[..., 3].astype(np.float32) / 255.0
        alpha = raster.box_blur(alpha, blur) * float(shadow.get("opacity", 0.6))
        r, g, b, _a = rgba(shadow.get("color", "#000000"))
        shadow_rgba = np.zeros((*alpha.shape, 4), np.uint8)
        shadow_rgba[..., 0], shadow_rgba[..., 1], shadow_rgba[..., 2] = r, g, b
        shadow_rgba[..., 3] = np.clip(alpha * 255 + 0.5, 0, 255).astype(np.uint8)
        image = qimage_from_rgba(shadow_rgba).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    painter = _painter(image, x0, y0)
    if outline_path is not None:
        painter.fillPath(outline_path, qcolor(params.get("outline_color", "#000000")))
    painter.fillPath(path, qcolor(params.get("color", "#FFFFFF")))
    painter.end()
    return x0, y0, rgba_from_qimage(image)


# --- Images (logos) -----------------------------------------------------------------------------


def clear_caches() -> None:
    """Libère les images sources en cache (à appeler avant l'arrêt de l'application)."""
    _source_cache.clear()


def is_svg(data: bytes) -> bool:
    head = data[:512].lstrip().lower()
    return head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in data[:2048].lower())


def source_size(data: bytes) -> tuple[int, int]:
    if is_svg(data):
        size = QSvgRenderer(QByteArray(data)).defaultSize()
        return max(size.width(), 1), max(size.height(), 1)
    image = QImage.fromData(QByteArray(data))
    return max(image.width(), 1), max(image.height(), 1)


def source_image(key: str, data: bytes, width: int, height: int) -> QImage | None:
    """Image source à la taille d'affichage (SVG rendu à cette taille : net à toute échelle)."""
    width, height = max(1, int(width)), max(1, int(height))
    cache_key = (key, width, height)
    if cache_key in _source_cache:
        return _source_cache[cache_key]
    if is_svg(data):
        renderer = QSvgRenderer(QByteArray(data))
        if not renderer.isValid():
            return None
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter, QRectF(0, 0, width, height))
        painter.end()
    else:
        loaded = QImage.fromData(QByteArray(data))
        if loaded.isNull():
            return None
        image = loaded.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied).scaled(
            width, height, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
    if len(_source_cache) > 64:
        _source_cache.clear()
    _source_cache[cache_key] = image
    return image


def render_image(layer: Layer, width: int, height: int, blobs: dict[str, bytes]):  # type: ignore[no-untyped-def]
    params = layer.params
    blob = params.get("blob")
    if not blob or blob not in blobs:
        return None
    w, h = float(params.get("width", 256.0)), float(params.get("height", 256.0))
    if w < 1 or h < 1:
        return None
    source = source_image(blob, blobs[blob], int(round(w)), int(round(h)))
    if source is None:
        return None
    if params.get("tint_enabled") and params.get("tint"):
        pixels = rgba_from_qimage(source)
        r, g, b, _a = rgba(params["tint"])
        pixels[..., 0], pixels[..., 1], pixels[..., 2] = r, g, b  # recoloration (alpha conservé)
        source = qimage_from_rgba(pixels)
    transform = placement_transform(params)
    local = QRectF(-w / 2, -h / 2, w, h)
    canvas = _canvas(transform.mapRect(local).adjusted(-2, -2, 2, 2), width, height)
    if canvas is None:
        return None
    x0, y0, image = canvas
    painter = _painter(image, x0, y0)
    painter.setTransform(transform * QTransform.fromTranslate(-x0, -y0))
    painter.drawImage(local, source)
    painter.end()
    return x0, y0, rgba_from_qimage(image)


def element_bounds(layer: Layer, blobs: dict[str, bytes] | None = None) -> QRectF:
    """Rectangle englobant d'un élément (sélection, poignées de transformation)."""
    params = layer.params
    if layer.kind == "vector":
        path = shape_path(params)
        return _rotation(params, path.boundingRect()).map(path).boundingRect()
    if layer.kind == "text":
        return placement_transform(params).map(text_path(params, blobs)).boundingRect()
    if layer.kind == "image":
        w, h = float(params.get("width", 256.0)), float(params.get("height", 256.0))
        return placement_transform(params).mapRect(QRectF(-w / 2, -h / 2, w, h))
    return QRectF()
