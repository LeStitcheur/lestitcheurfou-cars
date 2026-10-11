"""Panneau couleur : carré teinte / saturation / valeur, RGB, HSV, HEX, opacité, palettes, historique.

Les couleurs de dessin sont des valeurs sRGB 8 bits intégrées à la texture de livrée. Elles ne
se confondent pas avec la couleur de peinture de carrosserie (matériau), réglée dans l'onglet
Matériaux. La valeur linéaire est affichée pour information (shaders, outils de rendu).
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QSpinBox, QWidget

from lsfcars.livery.blend import srgb_to_linear
from lsfcars.livery.model import DEFAULT_PRIMARY, DEFAULT_SECONDARY, hex_color, rgba, to_hex
from lsfcars.ui.design import tokens
from lsfcars.ui.design.components import LSInput, LSSelect, label, tooltip
from lsfcars.ui.editor.panels import Page, button


def _qcolor(value: str) -> QColor:
    r, g, b, a = rgba(value)
    return QColor(r, g, b, a)


class Swatch(QWidget):
    clicked = Signal(str)

    def __init__(self, color: str = "", size: int = 22) -> None:
        super().__init__()
        self.color = color
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_color(self, color: str) -> None:
        self.color = color
        tooltip(self, color)
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        painter.setPen(QPen(QColor(tokens.ColorTokens.BORDER), 1))
        painter.setBrush(QColor(tokens.ColorTokens.SURFACE))
        painter.drawRoundedRect(rect, 4, 4)
        if self.color:
            painter.setBrush(_qcolor(self.color))
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 3, 3)
        painter.end()

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if self.color:
            self.clicked.emit(self.color)


class SVSquare(QWidget):
    """Saturation (horizontale) et valeur (verticale) pour la teinte courante."""

    changed = Signal(float, float)

    def __init__(self) -> None:
        super().__init__()
        self.hue, self.sat, self.val = 0.6, 0.8, 0.9
        self.setMinimumHeight(130)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        painter = QPainter(self)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        horizontal = QLinearGradient(rect.topLeft(), rect.topRight())
        horizontal.setColorAt(0, QColor.fromHsvF(self.hue, 0, 1))
        horizontal.setColorAt(1, QColor.fromHsvF(self.hue, 1, 1))
        painter.fillRect(rect, horizontal)
        vertical = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        vertical.setColorAt(0, QColor.fromRgbF(0, 0, 0, 0))
        vertical.setColorAt(1, QColor.fromRgbF(0, 0, 0, 1))
        painter.fillRect(rect, vertical)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(rect.left() + self.sat * rect.width(), rect.top() + (1 - self.val) * rect.height())
        painter.setPen(QPen(QColor(tokens.ColorTokens.TEXT), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, 6, 6)
        painter.end()

    def _pick(self, pos) -> None:  # type: ignore[no-untyped-def]
        self.sat = min(max(pos.x() / max(self.width(), 1), 0.0), 1.0)
        self.val = 1.0 - min(max(pos.y() / max(self.height(), 1), 0.0), 1.0)
        self.update()
        self.changed.emit(self.sat, self.val)

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        self._pick(event.position())

    def mouseMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._pick(event.position())


class HueBar(QWidget):
    changed = Signal(float)

    def __init__(self) -> None:
        super().__init__()
        self.hue = 0.6
        self.setFixedHeight(16)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        painter = QPainter(self)
        rect = QRectF(self.rect())
        gradient = QLinearGradient(rect.topLeft(), rect.topRight())
        for i in range(7):
            gradient.setColorAt(i / 6, QColor.fromHsvF((i / 6) % 1.0, 1, 1))
        painter.fillRect(rect, gradient)
        x = rect.left() + self.hue * rect.width()
        painter.setPen(QPen(QColor(tokens.ColorTokens.TEXT), 2))
        painter.drawLine(QPointF(x, 0), QPointF(x, rect.height()))
        painter.end()

    def _pick(self, pos) -> None:  # type: ignore[no-untyped-def]
        self.hue = min(max(pos.x() / max(self.width(), 1), 0.0), 0.9999)
        self.update()
        self.changed.emit(self.hue)

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        self._pick(event.position())

    def mouseMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._pick(event.position())


def _spin(maximum: int) -> QSpinBox:
    box = QSpinBox()
    box.setRange(0, maximum)
    return box


class ColorPanel(Page):
    color_changed = Signal(str)
    pipette_requested = Signal()

    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        self._primary = DEFAULT_PRIMARY
        self._secondary = DEFAULT_SECONDARY
        self._updating = False
        current = self.section("Couleur de dessin", "Couleur intégrée à la texture (sRGB 8 bits).")
        swatches = QHBoxLayout()
        self.primary_swatch = Swatch(self._primary, 34)
        self.secondary_swatch = Swatch(self._secondary, 26)
        self.secondary_swatch.clicked.connect(lambda _c: self.swap())
        tooltip(self.secondary_swatch, "Couleur secondaire (dégradés) — clic : permuter", "X")
        swatches.addWidget(self.primary_swatch)
        swatches.addWidget(self.secondary_swatch)
        swatches.addWidget(
            button("Permuter", None, self.swap, "Permuter couleur principale et secondaire (X)")
        )
        swatches.addWidget(
            button("Pipette", "lsf-pipette", self.pipette_requested.emit, "Prélever une couleur (I)")
        )
        swatches.addStretch(1)
        current.body.addLayout(swatches)
        self.square = SVSquare()
        self.square.changed.connect(lambda s, v: self._from_hsv(self.hue_bar.hue, s, v))
        current.add(self.square)
        self.hue_bar = HueBar()
        self.hue_bar.changed.connect(lambda h: self._from_hsv(h, self.square.sat, self.square.val))
        current.add(self.hue_bar)
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        self.r, self.g, self.b, self.a = (_spin(255) for _ in range(4))
        self.h, self.s, self.v = _spin(359), _spin(100), _spin(100)
        for col, (name, box) in enumerate((("R", self.r), ("G", self.g), ("B", self.b), ("A", self.a))):
            grid.addWidget(label(name, "faint"), 0, col)
            grid.addWidget(box, 1, col)
            box.valueChanged.connect(self._from_rgb)
        for col, (name, box) in enumerate((("T°", self.h), ("S %", self.s), ("V %", self.v))):
            grid.addWidget(label(name, "faint"), 2, col)
            grid.addWidget(box, 3, col)
            box.valueChanged.connect(self._from_hsv_boxes)
        current.body.addLayout(grid)
        self.hex = LSInput("#RRGGBB ou #RRGGBBAA")
        self.hex.editingFinished.connect(lambda: self.set_color(self.hex.text(), record=True))
        current.row(label("HEX", "muted"), self.hex)
        self.linear = current.add(label("", "faint", wrap=True))
        current.add(
            label(
                "La couleur de peinture de la carrosserie (matériau) se règle dans l'onglet Matériaux : "
                "elle n'est pas intégrée à la texture.",
                "faint",
                wrap=True,
            )
        )
        history = self.section("Historique")
        self.history_grid = QGridLayout()
        self.history_grid.setSpacing(4)
        history.body.addLayout(self.history_grid)
        palettes = self.section("Palettes enregistrées", "Palettes du document et des modèles appliqués.")
        self.palette_select = LSSelect()
        self.palette_select.activated.connect(lambda: self._show_palette())
        palettes.add(self.palette_select)
        self.palette_grid = QGridLayout()
        self.palette_grid.setSpacing(4)
        palettes.body.addLayout(self.palette_grid)
        self.palette_name = LSInput("Nom de la palette")
        palettes.add(self.palette_name)
        palettes.row(
            button("Enregistrer l'historique", "save", self.save_palette, "Palette = couleurs récentes"),
            button("", "trash-2", self.delete_palette, "Supprimer la palette", "danger"),
        )
        self.finish()
        self.set_color(self._primary)

    # --- Couleurs --------------------------------------------------------------------------------
    def color(self) -> str:
        return self._primary

    def secondary(self) -> str:
        return self._secondary

    def swap(self) -> None:
        self._primary, self._secondary = self._secondary, self._primary
        self.secondary_swatch.set_color(self._secondary)
        self.set_color(self._primary)

    def set_secondary(self, color: str) -> None:
        self._secondary = hex_color(color)
        self.secondary_swatch.set_color(self._secondary)

    def set_color(self, color: str, record: bool = False) -> None:
        color = hex_color(color, self._primary)
        self._primary = color
        r, g, b, a = rgba(color)
        qc = QColor(r, g, b)
        h, s, v = qc.hsvHueF(), qc.hsvSaturationF(), qc.valueF()
        self._updating = True
        for box, value in ((self.r, r), (self.g, g), (self.b, b), (self.a, a)):
            box.setValue(value)
        self.h.setValue(int(round(h * 359)) if h >= 0 else 0)
        self.s.setValue(int(round(s * 100)))
        self.v.setValue(int(round(v * 100)))
        self._updating = False
        if h >= 0:
            self.hue_bar.hue = h
        self.square.hue, self.square.sat, self.square.val = self.hue_bar.hue, s, v
        self.hue_bar.update()
        self.square.update()
        self.hex.setText(color)
        self.primary_swatch.set_color(color)
        lin = srgb_to_linear(np.array([r, g, b], np.float32) / 255.0)
        self.linear.setText(
            f"Linéaire (lumière) : {lin[0]:.3f} · {lin[1]:.3f} · {lin[2]:.3f} — opacité {a / 255:.0%}"
        )
        if record and self.page.studio is not None:
            self.page.studio.record_color(color)
            self.refresh()
        self.color_changed.emit(color)

    def _from_hsv(self, h: float, s: float, v: float) -> None:
        qc = QColor.fromHsvF(min(max(h, 0.0), 0.9999), min(max(s, 0.0), 1.0), min(max(v, 0.0), 1.0))
        self.set_color(to_hex(qc.red(), qc.green(), qc.blue(), self.a.value()))

    def _from_rgb(self) -> None:
        if not self._updating:
            self.set_color(to_hex(self.r.value(), self.g.value(), self.b.value(), self.a.value()))

    def _from_hsv_boxes(self) -> None:
        if not self._updating:
            self._from_hsv(self.h.value() / 359, self.s.value() / 100, self.v.value() / 100)

    # --- Historique et palettes --------------------------------------------------------------
    def _fill(self, grid: QGridLayout, colors: list[str]) -> None:
        while grid.count():
            item = grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for index, color in enumerate(colors):
            swatch = Swatch(color)
            swatch.set_color(color)
            swatch.clicked.connect(lambda c: self.set_color(c, record=True))
            grid.addWidget(swatch, index // 9, index % 9)

    def refresh(self) -> None:
        studio = self.page.studio
        doc = studio.document() if studio is not None else None
        self._fill(self.history_grid, doc.color_history[:18] if doc else [])
        current = self.palette_select.currentText()
        self.palette_select.clear()
        for name in doc.palettes if doc else {}:
            self.palette_select.addItem(name, name)
        if current:
            index = self.palette_select.findText(current)
            if index >= 0:
                self.palette_select.setCurrentIndex(index)
        self._show_palette()

    def _show_palette(self) -> None:
        studio = self.page.studio
        doc = studio.document() if studio is not None else None
        name = self.palette_select.currentData()
        self._fill(self.palette_grid, doc.palettes.get(name, []) if doc and name else [])

    def save_palette(self) -> None:
        studio = self.page.studio
        doc = studio.document() if studio is not None else None
        if doc is None:
            return
        colors = doc.color_history[:12] or [self._primary, self._secondary]
        self.page.run("Palette", lambda: studio.save_palette(self.palette_name.text() or "Palette", colors))

    def delete_palette(self) -> None:
        studio = self.page.studio
        name = self.palette_select.currentData()
        if studio is not None and name:
            self.page.run("Palette", lambda: studio.delete_palette(name))
