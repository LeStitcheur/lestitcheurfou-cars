"""Génère l'icône de l'application (PNG pour Qt, ICO pour l'exécutable Windows).

Usage : ``python scripts/generate_icon.py``
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)

ROOT = Path(__file__).resolve().parents[1]
PNG_PATH = ROOT / "src" / "lsfcars" / "resources" / "icon.png"
ICO_PATH = ROOT / "packaging" / "icon.ico"

ACCENT = QColor("#1e90ff")
DARK = QColor("#0b0f15")
PANEL = QColor("#18202c")
TEXT = QColor("#e6edf3")

CAR_BODY = (
    (34, 186),
    (34, 158),
    (66, 146),
    (98, 116),
    (160, 116),
    (192, 146),
    (222, 154),
    (222, 186),
)
CAR_WINDOW = ((104, 124), (154, 124), (178, 146), (80, 146))


def _polygon(points: tuple[tuple[int, int], ...]) -> QPolygonF:
    return QPolygonF([QPointF(x, y) for x, y in points])


def render(size: int = 256) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 256, size / 256)

    gradient = QLinearGradient(0, 0, 0, 256)
    gradient.setColorAt(0, PANEL)
    gradient.setColorAt(1, DARK)
    p.setPen(QPen(ACCENT, 8))
    p.setBrush(QBrush(gradient))
    p.drawRoundedRect(QRectF(8, 8, 240, 240), 48, 48)

    font = QFont("Segoe UI", 44)
    font.setWeight(QFont.Weight.Black)
    p.setFont(font)
    p.setPen(TEXT)
    p.drawText(QRectF(0, 30, 256, 70), Qt.AlignmentFlag.AlignCenter, "LSF")

    body = QPainterPath()
    body.addPolygon(_polygon(CAR_BODY))
    body.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(ACCENT)
    p.drawPath(body)
    p.setBrush(DARK)
    p.drawPolygon(_polygon(CAR_WINDOW))
    p.setPen(QPen(ACCENT, 7))
    for cx in (80, 178):
        p.drawEllipse(QPointF(cx, 188), 19, 19)
    p.end()
    return image


def main() -> None:
    _app = QGuiApplication.instance() or QGuiApplication([])  # nécessaire pour les polices
    PNG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ICO_PATH.parent.mkdir(parents=True, exist_ok=True)
    image = render(256)
    if not image.save(str(PNG_PATH)) or not image.save(str(ICO_PATH)):
        raise SystemExit("Échec de l'écriture de l'icône")
    print(f"{PNG_PATH.relative_to(ROOT)}\n{ICO_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
