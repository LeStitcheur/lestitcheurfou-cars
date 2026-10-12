"""Widgets d'AI Vehicle Creator : pont des tâches (threads → interface) et tableau de références.

``ReferenceBoard`` affiche une référence préparée avec ses annotations, son détourage et son
cadre de recadrage ; en mode « annoter » ou « recadrer », un glisser trace un rectangle
(coordonnées relatives à l'image). Le mode comparaison affiche deux références côte à côte.
"""

from __future__ import annotations

import numpy as np
from PIL import Image
from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from lsfcars.ui.design import tokens

C = tokens.ColorTokens
ANNOTATION_COLORS = {
    "logo": C.ERROR,
    "wheel": C.TEXT_SECONDARY,
    "light": C.WARNING,
    "glass": C.ELECTRIC,
    "grille": C.PRIMARY,
    "detail": C.SUCCESS,
    "note": C.TEXT,
}


class JobBridge(QObject):
    """Relaie les notifications de la file de tâches (fils de travail) vers le fil de l'interface."""

    updated = Signal(object)

    def __call__(self, job) -> None:  # type: ignore[no-untyped-def]
        self.updated.emit(job)


def to_qimage(image: Image.Image) -> QImage:
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimage = QImage(data, rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888)
    return qimage.copy()  # détache des octets Python


class _Release:
    """Événement minimal pour simuler la fin d'un glisser (tests, scripts)."""

    def __init__(self, point: QPointF) -> None:
        self._point = point

    def position(self) -> QPointF:
        return self._point


class ReferenceBoard(QWidget):
    """Visionneuse de références : annotations, recadrage, détourage, comparaison."""

    rect_drawn = Signal(str, list)  # mode (« annotate », « crop »), [x0, y0, x1, y1] relatifs

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(240, 200)
        self.images: list[QImage] = []
        self.titles: list[str] = []
        self.annotations: list[dict] = []
        self.mask: QImage | None = None
        self.crop: list[float] | None = None
        self.mode = "view"
        self.show_mask = False
        self._drag: tuple[QPointF, QPointF] | None = None
        self.message = "Importez des images de référence (PNG, JPG, WEBP)."

    # --- Contenu ------------------------------------------------------------------------------
    def set_reference(
        self, image: Image.Image | None, title: str = "", annotations=None, mask=None, crop=None
    ) -> None:  # type: ignore[no-untyped-def]
        self.images = [to_qimage(image)] if image is not None else []
        self.titles = [title]
        self.annotations = list(annotations or [])
        self.crop = crop
        self.mask = None
        if mask is not None:
            overlay = np.zeros(mask.shape + (4,), np.uint8)
            color = QColor(C.ELECTRIC)
            overlay[mask] = (color.red(), color.green(), color.blue(), 70)
            self.mask = to_qimage(Image.fromarray(overlay, "RGBA"))
        self.update()

    def set_compare(self, first: Image.Image, second: Image.Image, titles: tuple[str, str]) -> None:
        self.images = [to_qimage(first), to_qimage(second)]
        self.titles = list(titles)
        self.annotations = []
        self.mask = None
        self.crop = None
        self.update()

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        cursor = Qt.CursorShape.CrossCursor if mode in ("annotate", "crop") else Qt.CursorShape.ArrowCursor
        self.setCursor(cursor)
        self.update()

    # --- Géométrie ----------------------------------------------------------------------------
    def image_rects(self) -> list[QRectF]:
        count = max(1, len(self.images))
        margin = 12.0
        cell_w = (self.width() - margin * (count + 1)) / count
        rects = []
        for index, image in enumerate(self.images):
            area = QRectF(
                margin + index * (cell_w + margin), margin + 18, cell_w, self.height() - 2 * margin - 18
            )
            scale = min(area.width() / max(image.width(), 1), area.height() / max(image.height(), 1))
            w, h = image.width() * scale, image.height() * scale
            rects.append(QRectF(area.center().x() - w / 2, area.center().y() - h / 2, w, h))
        return rects

    def to_relative(self, point: QPointF) -> tuple[float, float] | None:
        rects = self.image_rects()
        if not rects:
            return None
        rect = rects[0]
        return (
            min(1.0, max(0.0, (point.x() - rect.left()) / max(rect.width(), 1.0))),
            min(1.0, max(0.0, (point.y() - rect.top()) / max(rect.height(), 1.0))),
        )

    def _point(self, relative: tuple[float, float]) -> QPointF:
        rect = self.image_rects()[0]
        return QPointF(rect.left() + relative[0] * rect.width(), rect.top() + relative[1] * rect.height())

    # --- Interaction --------------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if self.mode in ("annotate", "crop") and self.images and event.button() == Qt.MouseButton.LeftButton:
            self._drag = (event.position(), event.position())
            self.update()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if self._drag is not None:
            self._drag = (self._drag[0], event.position())
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if self._drag is None:
            return
        start = self._drag[0]
        end = event.position()
        self._drag = None
        self.update()
        a, b = self.to_relative(start), self.to_relative(end)
        if a is None or b is None or abs(a[0] - b[0]) < 0.01 or abs(a[1] - b[1]) < 0.01:
            return
        self.rect_drawn.emit(self.mode, [min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])])

    def drag(self, start: tuple[float, float], end: tuple[float, float]) -> None:
        """Simule un glisser en coordonnées relatives (tests, scripts)."""
        if not self.images:
            return
        self._drag = (self._point(start), self._point(start))
        self.mouseReleaseEvent(_Release(self._point(end)))

    # --- Dessin -------------------------------------------------------------------------------
    def paintEvent(self, _event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor(C.BG_MAIN))
        if not self.images:
            painter.setPen(QColor(C.TEXT_SECONDARY))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message)
            return
        for index, (image, rect) in enumerate(zip(self.images, self.image_rects(), strict=False)):
            painter.setPen(QColor(C.TEXT_SECONDARY))
            if index < len(self.titles) and self.titles[index]:
                title_rect = QRectF(rect.left(), rect.top() - 20, rect.width(), 18)
                painter.drawText(
                    title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, self.titles[index]
                )
            painter.drawImage(rect, image)
            painter.setPen(QPen(QColor(C.BORDER), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            if index == 0:
                self._overlays(painter, rect)
        if self._drag is not None:
            start, end = self._drag
            color = QColor(C.WARNING if self.mode == "crop" else C.ELECTRIC)
            painter.setPen(QPen(color, 1.5, Qt.PenStyle.DashLine))
            fill = QColor(color)
            fill.setAlpha(40)
            painter.setBrush(fill)
            painter.drawRect(QRectF(start, end).normalized())

    def _relative_rect(self, rect: QRectF, box: list[float]) -> QRectF:
        x0, y0, x1, y1 = box
        return QRectF(
            rect.left() + x0 * rect.width(),
            rect.top() + y0 * rect.height(),
            (x1 - x0) * rect.width(),
            (y1 - y0) * rect.height(),
        )

    def _overlays(self, painter: QPainter, rect: QRectF) -> None:
        if self.show_mask and self.mask is not None:
            painter.drawImage(rect, self.mask)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for note in self.annotations:
            box = note.get("rect") or [0, 0, 0, 0]
            area = self._relative_rect(rect, box)
            color = QColor(ANNOTATION_COLORS.get(note.get("kind"), C.TEXT))
            painter.setPen(QPen(color, 2))
            painter.drawRect(area)
            text = note.get("text") or note.get("kind", "")
            painter.drawText(
                area.adjusted(4, 2, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, text
            )
        if self.mode == "crop" and self.crop and list(self.crop) != [0.0, 0.0, 1.0, 1.0]:
            painter.setPen(QPen(QColor(C.WARNING), 1.5, Qt.PenStyle.DashLine))
            painter.drawRect(self._relative_rect(rect, list(self.crop)))
