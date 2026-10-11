"""Canvas 2D de la texture : zoom, panoramique, grille, règles, guides, UV, sélection, outils.

La texture affichée est la composition du Livery Studio (même tableau que celui envoyé au
viewport 3D et exporté). L'image Qt pointe directement sur ce tableau : aucune copie à chaque
coup de pinceau. Au fort dézoom, un aperçu réduit est utilisé (textures 4K fluides).
"""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from lsfcars.livery import render2d
from lsfcars.livery.studio import LiveryError, transform_params
from lsfcars.ui.design import tokens

RULER = 18
TOOLS = [
    # (clé, libellé, icône, raccourci)
    ("move", "Transformation / déplacement", "lsf-transform", "V"),
    ("brush", "Pinceau", "lsf-brush", "B"),
    ("eraser", "Gomme", "lsf-eraser", "E"),
    ("fill", "Remplissage", "paint-bucket", "G"),
    ("gradient", "Dégradé", "lsf-gradient", "Shift+G"),
    ("line", "Ligne", "lsf-line", "L"),
    ("rect", "Rectangle", "square", "U"),
    ("rounded_rect", "Rectangle arrondi", "lsf-rounded", "Shift+U"),
    ("circle", "Cercle", "lsf-circle", "O"),
    ("ellipse", "Ellipse", "lsf-ellipse", "Shift+O"),
    ("polygon", "Polygone (double-clic pour terminer)", "lsf-polygon", "P"),
    ("curve", "Courbe (double-clic pour terminer)", "lsf-curve", "Shift+P"),
    ("text", "Texte", "lsf-text", "T"),
    ("pipette", "Pipette", "lsf-pipette", "I"),
    ("select", "Sélection rectangulaire", "square-dashed", "M"),
    ("lasso", "Sélection libre (lasso)", "lsf-lasso", "Shift+M"),
    ("island", "Sélection d'îlot UV", "lsf-island", "W"),
]
TOOL_LABELS = {key: label for key, label, _icon, _shortcut in TOOLS}
SHAPE_TOOLS = {"line", "rect", "rounded_rect", "circle", "ellipse"}
POINT_TOOLS = {"polygon", "curve"}


def qcolor(token: str, alpha: float = 1.0) -> QColor:
    color = QColor(token)
    color.setAlphaF(max(0.0, min(1.0, alpha)))
    return color


class Canvas2D(QWidget):
    color_picked = Signal(str)
    status = Signal(str)
    layer_selected = Signal(str)

    def __init__(self, page, parent: QWidget | None = None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.page = page
        self.zoom = 0.5
        self.offset = QPointF(RULER + 20, RULER + 20)
        self.show_grid = False
        self.show_uv = True
        self.show_seams = False
        self.show_rulers = True
        self.guides: list[tuple[str, float]] = []  # ("h" | "v", position en pixels de texture)
        self._image: QImage | None = None
        self._image_key: tuple | None = None
        self._array_ref = None
        self._preview: tuple[int, QImage] | None = None  # (facteur, image réduite)
        self._uv_paths: tuple[int, QPainterPath, QPainterPath] | None = None
        self._selection_image: tuple[int, QImage] | None = None
        self._mouse: QPointF | None = None
        self._mode: str | None = None
        self._select_op = "replace"
        self._start = (0.0, 0.0)
        self._current = (0.0, 0.0)
        self._points: list[tuple[float, float]] = []
        self._drag_layer: str | None = None
        self._drag_params: dict | None = None
        self._drag_rect = QRectF()
        self._handle: str | None = None
        self._pan_last = QPointF()
        self._space = False
        self._pressure = 1.0
        self._tablet = False
        self._fitted = False
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(150)
        self._preview_timer.timeout.connect(self._rebuild_preview)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(260, 200)
        self.setCursor(Qt.CursorShape.CrossCursor)

    # --- Données ---------------------------------------------------------------------------------
    @property
    def studio(self):  # type: ignore[no-untyped-def]
        return self.page.studio

    def texture_size(self) -> tuple[int, int]:
        studio = self.studio
        doc = studio.document() if studio is not None else None
        return (doc.width, doc.height) if doc is not None else (0, 0)

    def _current_image(self) -> QImage | None:
        studio = self.studio
        array = studio.compositor.result if studio is not None else None
        if array is None:
            self._image = None
            return None
        key = (id(array), array.shape)
        if self._image is None or self._image_key != key:
            h, w = array.shape[:2]
            self._image = QImage(array.data, w, h, w * 4, QImage.Format.Format_RGBA8888)  # sans copie
            self._image_key = key
            self._array_ref = array
            self._preview = None
        return self._image

    def texture_changed(self) -> None:
        """La composition a changé : redessiner (aperçu réduit recalculé avec un léger délai)."""
        if self.zoom < 0.5:
            self._preview_timer.start()
        self.update()

    def selection_updated(self) -> None:
        self._selection_image = None
        self.update()

    def surface_changed(self) -> None:
        self._uv_paths = None
        self.update()

    def _rebuild_preview(self) -> None:
        image = self._current_image()
        if image is None:
            return
        factor = 2 if self.zoom >= 0.25 else 4
        scaled = image.scaled(
            max(image.width() // factor, 1),
            max(image.height() // factor, 1),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._preview = (factor, scaled)
        self.update()

    # --- Coordonnées ------------------------------------------------------------------------------
    def to_tex(self, pos: QPointF) -> tuple[float, float]:
        return ((pos.x() - self.offset.x()) / self.zoom, (pos.y() - self.offset.y()) / self.zoom)

    def to_view(self, x: float, y: float) -> QPointF:
        return QPointF(self.offset.x() + x * self.zoom, self.offset.y() + y * self.zoom)

    def fit(self) -> None:
        w, h = self.texture_size()
        if not w or not h:
            return
        area_w = max(self.width() - RULER - 20, 50)
        area_h = max(self.height() - RULER - 20, 50)
        self.zoom = max(min(area_w / w, area_h / h) * 0.96, 0.02)
        self.offset = QPointF(
            RULER + (self.width() - RULER - w * self.zoom) / 2,
            RULER + (self.height() - RULER - h * self.zoom) / 2,
        )
        self._fitted = True
        self._preview_timer.start()
        self.update()

    def set_zoom(self, zoom: float, anchor: QPointF | None = None) -> None:
        anchor = anchor or QPointF(self.width() / 2, self.height() / 2)
        x, y = self.to_tex(anchor)
        self.zoom = max(0.02, min(32.0, zoom))
        self.offset = QPointF(anchor.x() - x * self.zoom, anchor.y() - y * self.zoom)
        if self.zoom < 0.5:
            self._preview_timer.start()
        self.status.emit(f"Zoom {self.zoom * 100:.0f} %")
        self.update()

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        super().resizeEvent(event)
        if not self._fitted:
            self.fit()

    # --- Dessin -----------------------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), qcolor(tokens.ColorTokens.BG_MAIN))
        w, h = self.texture_size()
        image = self._current_image()
        if not w or image is None:
            painter.setPen(qcolor(tokens.ColorTokens.TEXT_SECONDARY))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Aucun document de livrée")
            painter.end()
            return
        target = QRectF(self.offset.x(), self.offset.y(), w * self.zoom, h * self.zoom)
        self._draw_checker(painter, target)
        visible = target.intersected(QRectF(self.rect()))
        if not visible.isEmpty():
            src = QRectF(
                (visible.left() - self.offset.x()) / self.zoom,
                (visible.top() - self.offset.y()) / self.zoom,
                visible.width() / self.zoom,
                visible.height() / self.zoom,
            )
            source_image = image
            if self.zoom < 0.5 and self._preview is not None:
                factor, small = self._preview
                source_image = small
                src = QRectF(
                    src.left() / factor, src.top() / factor, src.width() / factor, src.height() / factor
                )
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.zoom < 1.0)
            painter.drawImage(visible, source_image, src)
        painter.save()
        painter.translate(self.offset)
        painter.scale(self.zoom, self.zoom)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.show_grid:
            self._draw_grid(painter, w, h)
        if self.show_uv or self.show_seams:
            self._draw_uv(painter)
        self._draw_selection(painter, w, h)
        self._draw_element_bounds(painter)
        self._draw_tool_preview(painter)
        painter.restore()
        self._draw_guides(painter)
        self._draw_brush_cursor(painter)
        if self.show_rulers:
            self._draw_rulers(painter, w, h)
        painter.end()

    def _draw_checker(self, painter: QPainter, target: QRectF) -> None:
        painter.save()
        clip = target.intersected(QRectF(self.rect()))
        painter.setClipRect(clip)
        painter.fillRect(clip, qcolor(tokens.ColorTokens.SURFACE))
        cell = 12
        dark = qcolor(tokens.ColorTokens.PANEL)
        x0 = int(clip.left() // cell * cell)
        y0 = int(clip.top() // cell * cell)
        for y in range(y0, int(clip.bottom()) + cell, cell):
            for x in range(x0 + ((y // cell) % 2) * cell, int(clip.right()) + cell, cell * 2):
                painter.fillRect(x, y, cell, cell, dark)
        painter.restore()

    def _cosmetic(self, color: QColor, width: float = 1.0, dash: bool = False) -> QPen:
        pen = QPen(color, width)
        pen.setCosmetic(True)
        if dash:
            pen.setStyle(Qt.PenStyle.DashLine)
        return pen

    def _draw_grid(self, painter: QPainter, w: int, h: int) -> None:
        step = next((s for s in (8, 16, 32, 64, 128, 256, 512, 1024) if s * self.zoom >= 22), 1024)
        painter.setPen(self._cosmetic(qcolor(tokens.ColorTokens.TEXT_SECONDARY, 0.16)))
        for x in range(0, w + 1, step):
            painter.drawLine(QPointF(x, 0), QPointF(x, h))
        for y in range(0, h + 1, step):
            painter.drawLine(QPointF(0, y), QPointF(w, y))

    def _draw_uv(self, painter: QPainter) -> None:
        studio = self.studio
        try:
            surface = studio.surface() if studio is not None else None
        except LiveryError:
            surface = None
        if surface is None:
            return
        if self._uv_paths is None or self._uv_paths[0] != id(surface):
            uv, seams = QPainterPath(), QPainterPath()
            for (x0, y0), (x1, y1) in surface.uv_segments():
                uv.moveTo(x0, y0)
                uv.lineTo(x1, y1)
            for (x0, y0), (x1, y1) in surface.seam_segments():
                seams.moveTo(x0, y0)
                seams.lineTo(x1, y1)
            self._uv_paths = (id(surface), uv, seams)
        _key, uv, seams = self._uv_paths
        if self.show_uv:
            painter.setPen(self._cosmetic(qcolor(tokens.ColorTokens.ELECTRIC, 0.22)))
            painter.drawPath(uv)
        if self.show_seams:
            painter.setPen(self._cosmetic(qcolor(tokens.ColorTokens.WARNING, 0.9), 1.6))
            painter.drawPath(seams)

    def _draw_selection(self, painter: QPainter, w: int, h: int) -> None:
        studio = self.studio
        if studio is None or studio.selection is None:
            return
        selection = studio.selection
        key = id(selection)
        if self._selection_image is None or self._selection_image[0] != key:
            tint = np.zeros((*selection.shape, 4), np.uint8)
            color = QColor(tokens.ColorTokens.PRIMARY)
            tint[..., 0], tint[..., 1], tint[..., 2] = color.red(), color.green(), color.blue()
            tint[..., 3] = (selection.astype(np.uint16) * 70 // 255).astype(np.uint8)
            self._selection_image = (key, render2d.qimage_from_rgba(tint))
        painter.drawImage(QRectF(0, 0, w, h), self._selection_image[1])
        bounds = studio.selection_bounds()
        if bounds is not None:
            painter.setPen(self._cosmetic(qcolor(tokens.ColorTokens.ELECTRIC), 1.2, dash=True))
            painter.drawRect(QRectF(bounds[0], bounds[1], bounds[2] - bounds[0], bounds[3] - bounds[1]))

    def selected_element(self):  # type: ignore[no-untyped-def]
        layer = self.page.current_layer()
        return layer if layer is not None and layer.kind in ("text", "image", "vector") else None

    def _element_rect(self, layer) -> QRectF:  # type: ignore[no-untyped-def]
        return render2d.element_bounds(layer, self.studio.scene.blobs if self.studio else None)

    def _handles(self, rect: QRectF) -> dict[str, QPointF]:
        return {
            "nw": rect.topLeft(),
            "ne": rect.topRight(),
            "sw": rect.bottomLeft(),
            "se": rect.bottomRight(),
            "rotate": QPointF(rect.center().x(), rect.top() - 28 / self.zoom),
        }

    def _draw_element_bounds(self, painter: QPainter) -> None:
        if self.page.tool != "move":
            return
        layer = self.selected_element()
        if layer is None:
            return
        rect = self._element_rect(layer)
        if rect.isEmpty():
            return
        painter.setPen(self._cosmetic(qcolor(tokens.ColorTokens.ELECTRIC), 1.2, dash=True))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)
        size = 7 / self.zoom
        handles = self._handles(rect)
        painter.drawLine(QPointF(rect.center().x(), rect.top()), handles["rotate"])
        painter.setPen(self._cosmetic(qcolor(tokens.ColorTokens.BG_MAIN)))
        painter.setBrush(qcolor(tokens.ColorTokens.ELECTRIC))
        for name, point in handles.items():
            if name == "rotate":
                painter.drawEllipse(point, size * 0.7, size * 0.7)
            else:
                painter.drawRect(QRectF(point.x() - size / 2, point.y() - size / 2, size, size))

    def _draw_tool_preview(self, painter: QPainter) -> None:
        painter.setPen(self._cosmetic(qcolor(tokens.ColorTokens.ELECTRIC), 1.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        (x0, y0), (x1, y1) = self._start, self._current
        if self._mode == "shape":
            tool = self.page.tool
            rect = QRectF(QPointF(x0, y0), QPointF(x1, y1)).normalized()
            if tool == "line":
                painter.drawLine(QPointF(x0, y0), QPointF(x1, y1))
            elif tool == "circle":
                r = math.hypot(x1 - x0, y1 - y0)
                painter.drawEllipse(QPointF(x0, y0), r, r)
            elif tool == "ellipse":
                painter.drawEllipse(rect)
            elif tool == "rounded_rect":
                radius = float(self.page.tool_settings.get("radius", 24.0))
                painter.drawRoundedRect(rect, radius, radius)
            else:
                painter.drawRect(rect)
        elif self._mode == "select":
            painter.setPen(self._cosmetic(qcolor(tokens.ColorTokens.ELECTRIC), 1.2, dash=True))
            painter.drawRect(QRectF(QPointF(x0, y0), QPointF(x1, y1)).normalized())
        elif self._mode == "gradient":
            painter.drawLine(QPointF(x0, y0), QPointF(x1, y1))
            painter.drawEllipse(QPointF(x0, y0), 4 / self.zoom, 4 / self.zoom)
        if self._points and self._mode in ("points", "lasso"):
            polygon = QPolygonF([QPointF(x, y) for x, y in self._points] + [QPointF(*self._current)])
            painter.setPen(
                self._cosmetic(qcolor(tokens.ColorTokens.ELECTRIC), 1.2, dash=self._mode == "lasso")
            )
            painter.drawPolyline(polygon)

    def _draw_guides(self, painter: QPainter) -> None:
        if not self.guides:
            return
        painter.setPen(self._cosmetic(qcolor(tokens.ColorTokens.ELECTRIC, 0.85), 1.0, dash=True))
        for orientation, value in self.guides:
            if orientation == "h":
                y = self.to_view(0, value).y()
                painter.drawLine(QPointF(RULER, y), QPointF(self.width(), y))
            else:
                x = self.to_view(value, 0).x()
                painter.drawLine(QPointF(x, RULER), QPointF(x, self.height()))

    def _draw_brush_cursor(self, painter: QPainter) -> None:
        if self._mouse is None or self.page.tool not in ("brush", "eraser"):
            return
        radius = self.page.brush_settings().size * 0.5 * self.zoom
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(self._cosmetic(qcolor(tokens.ColorTokens.BG_MAIN, 0.8), 2.0))
        painter.drawEllipse(self._mouse, radius, radius)
        painter.setPen(self._cosmetic(qcolor(tokens.ColorTokens.TEXT), 1.0))
        painter.drawEllipse(self._mouse, radius, radius)

    def _draw_rulers(self, painter: QPainter, w: int, h: int) -> None:
        panel = qcolor(tokens.ColorTokens.BG_SECONDARY)
        painter.fillRect(QRectF(0, 0, self.width(), RULER), panel)
        painter.fillRect(QRectF(0, 0, RULER, self.height()), panel)
        painter.setPen(qcolor(tokens.ColorTokens.TEXT_SECONDARY, 0.8))
        font = painter.font()
        font.setPixelSize(9)
        painter.setFont(font)
        step = next((s for s in (16, 32, 64, 128, 256, 512, 1024, 2048) if s * self.zoom >= 56), 2048)
        start = max(0, int(-self.offset.x() / self.zoom) // step * step)
        for x in range(start, w + 1, step):
            vx = self.to_view(x, 0).x()
            if vx > self.width():
                break
            painter.drawLine(QPointF(vx, RULER - 6), QPointF(vx, RULER))
            painter.drawText(QPointF(vx + 2, 10), str(x))
        start = max(0, int(-self.offset.y() / self.zoom) // step * step)
        for y in range(start, h + 1, step):
            vy = self.to_view(0, y).y()
            if vy > self.height():
                break
            painter.drawLine(QPointF(RULER - 6, vy), QPointF(RULER, vy))
            painter.save()
            painter.translate(10, vy + 2)
            painter.rotate(90)
            painter.drawText(QPointF(0, 0), str(y))
            painter.restore()
        painter.fillRect(QRectF(0, 0, RULER, RULER), panel)

    # --- Interaction ------------------------------------------------------------------------------
    def tabletEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        self._pressure = max(0.0, min(1.0, float(event.pressure())))
        self._tablet = True
        event.ignore()

    def _snap(self, x: float, y: float) -> tuple[float, float]:
        """Magnétisme des guides (8 px écran)."""
        tolerance = 8 / self.zoom
        for orientation, value in self.guides:
            if orientation == "v" and abs(x - value) < tolerance:
                x = value
            if orientation == "h" and abs(y - value) < tolerance:
                y = value
        return x, y

    def press(self, x: float, y: float, modifiers=Qt.KeyboardModifier.NoModifier) -> None:  # type: ignore[no-untyped-def]
        """Début d'une action d'outil aux coordonnées de texture (souris ou tests)."""
        self._start = self._current = (x, y)
        pressure = self._pressure if self._tablet else 1.0
        tool = self.page.tool
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            op = "add"
        elif modifiers & Qt.KeyboardModifier.AltModifier:
            op = "subtract"
        else:
            op = "replace"
        if tool in ("brush", "eraser"):
            if self.page.begin_stroke(x, y, pressure, mode="2d"):
                self._mode = "stroke"
        elif tool == "fill":
            self.page.fill_at(x, y)
        elif tool == "pipette":
            color = self.page.run("Pipette", lambda: self.studio.pick_color(x, y))
            if color:
                self.color_picked.emit(color)
        elif tool == "text":
            self.page.create_text_at(x, y)
        elif tool in SHAPE_TOOLS:
            self._mode = "shape"
        elif tool in POINT_TOOLS:
            self._mode = "points"
            self._points.append((x, y))
        elif tool in ("select", "lasso"):
            self._mode = tool
            self._select_op = op
            self._points = [(x, y)] if tool == "lasso" else []
        elif tool == "island":
            self.page.run("Sélection d'îlot", lambda: self.studio.select_island(x, y, op))
            self.page.selection_changed()
        elif tool == "gradient":
            self._mode = "gradient"
        elif tool == "move":
            self._begin_move(x, y)
        self.update()

    def drag(self, x: float, y: float, modifiers=Qt.KeyboardModifier.NoModifier) -> None:  # type: ignore[no-untyped-def]
        self._current = (x, y)
        if self._mode == "stroke":
            self.page.continue_stroke(x, y, self._pressure if self._tablet else 1.0, mode="2d")
        elif self._mode == "lasso":
            self._points.append((x, y))
        elif self._mode == "move":
            self._update_move(x, y, modifiers)
        self.update()

    def release(self) -> None:
        mode, self._mode = self._mode, None
        studio = self.studio
        if studio is None:
            return
        (x0, y0), (x1, y1) = self._start, self._current
        self._tablet = False
        if mode == "stroke":
            self.page.end_stroke()
        elif mode == "shape":
            if math.hypot(x1 - x0, y1 - y0) >= 2:
                self.page.create_shape(self.page.tool, [(x0, y0), (x1, y1)])
        elif mode == "select":
            if math.hypot(x1 - x0, y1 - y0) < 2:
                studio.clear_selection()
            else:
                studio.select_rect(x0, y0, x1, y1, self._select_op)
            self.page.selection_changed()
        elif mode == "lasso":
            if len(self._points) >= 3:
                studio.select_polygon(self._points, self._select_op)
            self._points = []
            self.page.selection_changed()
        elif mode == "gradient":
            if math.hypot(x1 - x0, y1 - y0) >= 2:
                self.page.gradient_between((x0, y0), (x1, y1))
        elif mode == "move":
            labels = {"rotate": "Rotation", None: "Déplacement"}
            studio.commit_edit(labels.get(self._handle, "Mise à l'échelle"))
            self._drag_layer = self._drag_params = None
            self.page.schedule_refresh()
        elif mode == "points":
            self._mode = "points"  # la saisie continue jusqu'au double-clic ou Entrée
        self.update()

    def _begin_move(self, x: float, y: float) -> None:
        layer = self.selected_element()
        handle = None
        if layer is not None:
            rect = self._element_rect(layer)
            tolerance = 9 / self.zoom
            for name, spot in self._handles(rect).items():
                if abs(spot.x() - x) <= tolerance and abs(spot.y() - y) <= tolerance:
                    handle = name
                    break
            if handle is None and not rect.contains(QPointF(x, y)):
                layer = None
        if layer is None:
            layer = self.page.element_at(x, y)
            if layer is not None:
                self.layer_selected.emit(layer.id)
        if layer is None or layer.locked:
            return
        self._mode = "move"
        self._handle = handle
        self._drag_layer = layer.id
        self._drag_params = dict(layer.params)
        self._drag_rect = self._element_rect(layer)

    def _update_move(self, x: float, y: float, modifiers) -> None:  # type: ignore[no-untyped-def]
        studio, layer_id, start = self.studio, self._drag_layer, self._drag_params
        if studio is None or layer_id is None or start is None:
            return
        center = self._drag_rect.center()
        sx, sy = self._start
        dx = dy = rotation = 0.0
        scale = 1.0
        if self._handle == "rotate":
            a0 = math.atan2(sy - center.y(), sx - center.x())
            a1 = math.atan2(y - center.y(), x - center.x())
            rotation = math.degrees(a1 - a0)
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                rotation = round(rotation / 15.0) * 15.0
        elif self._handle:
            d0 = math.hypot(sx - center.x(), sy - center.y())
            scale = max(0.05, math.hypot(x - center.x(), y - center.y()) / max(d0, 1e-6))
        else:
            dx, dy = x - sx, y - sy

        def mutate(doc) -> None:  # type: ignore[no-untyped-def]
            found = doc.find(layer_id)
            if found is None:
                return
            layer = found[0]
            layer.params = dict(start)
            transform_params(layer, dx, dy, rotation, scale)
            if dx or dy:
                layer.params.pop("anchor", None)

        studio.preview(mutate)
        self.texture_changed()

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        self.setFocus()
        pos = event.position()
        middle = event.button() == Qt.MouseButton.MiddleButton
        if middle or (event.button() == Qt.MouseButton.LeftButton and self._space):
            self._mode = "pan"
            self._pan_last = pos
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if (
            event.button() != Qt.MouseButton.LeftButton
            or self.studio is None
            or self.studio.document() is None
        ):
            return
        if self.show_rulers and (pos.x() < RULER or pos.y() < RULER):  # nouveau guide tiré d'une règle
            self._mode = "guide"
            self.guides.append(("h" if pos.y() < RULER else "v", 0.0))
            return
        self.press(*self._snap(*self.to_tex(pos)), event.modifiers())

    def mouseMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        pos = event.position()
        self._mouse = pos
        if self._mode == "pan":
            self.offset += pos - self._pan_last
            self._pan_last = pos
            self.update()
            return
        x, y = self.to_tex(pos)
        if self._mode == "guide" and self.guides:
            orientation, _value = self.guides[-1]
            self.guides[-1] = (orientation, y if orientation == "h" else x)
            self.update()
            return
        x, y = self._snap(x, y)
        w, h = self.texture_size()
        if w and 0 <= x < w and 0 <= y < h:
            self.status.emit(f"x {x:.0f} · y {y:.0f} px · zoom {self.zoom * 100:.0f} %")
        if self._mode is not None:
            self.drag(x, y, event.modifiers())
        else:
            self._current = (x, y)
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if self._mode == "pan":
            self._mode = None
            self.setCursor(Qt.CursorShape.CrossCursor)
            return
        if self._mode == "guide":
            self._mode = None
            orientation, value = self.guides[-1]
            w, h = self.texture_size()
            if value <= 0 or value >= (h if orientation == "h" else w):
                self.guides.pop()  # relâché hors de la texture : guide supprimé
            self.update()
            return
        self.release()

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if self.page.tool in POINT_TOOLS:
            self.finish_points()

    def finish_points(self) -> None:
        points, self._points = self._points, []
        self._mode = None
        unique = [p for i, p in enumerate(points) if i == 0 or math.dist(p, points[i - 1]) > 1.0]
        if len(unique) >= 2:
            self.page.create_shape(self.page.tool, unique)
        self.update()

    def cancel(self) -> None:
        if self._mode == "move" and self.studio is not None:
            self.studio.cancel_edit()
        if self._mode == "stroke" and self.studio is not None:
            self.studio.cancel_stroke()
        self._mode = None
        self._points = []
        self.update()

    def wheelEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.set_zoom(self.zoom * (1.18**steps), event.position())

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.finish_points()
        elif key == Qt.Key.Key_Escape:
            self.cancel()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space = False
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            super().keyReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        self._mouse = None
        self.update()
        super().leaveEvent(event)
