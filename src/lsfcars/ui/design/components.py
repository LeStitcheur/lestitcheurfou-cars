"""Composants réutilisables du design system Dark Premium."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPropertyAnimation,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QCursor, QMouseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from lsfcars.ui.design import fonts, icons
from lsfcars.ui.design import tokens as t
from lsfcars.ui.design.qss import density

# --- Utilitaires ---------------------------------------------------------------


def repolish(widget: QWidget) -> None:
    """Réapplique la feuille de style après changement d'une propriété dynamique."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def set_prop(widget: QWidget, name: str, value: object) -> None:
    widget.setProperty(name, value)
    repolish(widget)


def tooltip(widget: QWidget, text: str, shortcut: str | None = None) -> None:
    """LSTooltip : infobulle française, avec raccourci clavier éventuel."""
    if shortcut:
        text = f"{text}&nbsp;&nbsp;<span style='color:{t.TEXT_MUTED}'>{shortcut}</span>"
    widget.setToolTip(text)


def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if role:
        widget.setProperty("role", role)
    widget.setWordWrap(wrap)
    return widget


def eyebrow(text: str, color: str | None = None) -> QLabel:
    """Petit label en capitales espacées (« WORKSPACE / LESTITCHEUR »)."""
    widget = label(text, "eyebrow")
    widget.setFont(fonts.font(density().tiny_font, 700, 1.6, caps=True))
    if color:
        widget.setStyleSheet(f"color: {color};")
    return widget


def heading(text: str, size: int = 29, dot: bool = True, accent_words: str | None = None) -> QLabel:
    """Titre fort ; ``dot`` ajoute un point final bleu électrique, ``accent_words`` colore une partie."""
    html = text
    if accent_words and accent_words in text:
        html = text.replace(accent_words, f"<span style='color:{t.ACCENT_2}'>{accent_words}</span>")
    if dot:
        html = html.rstrip(".") + f"<span style='color:{t.ACCENT_2}'>.</span>"
    widget = label(html, "h1")
    widget.setTextFormat(Qt.TextFormat.RichText)
    widget.setFont(fonts.font(size, 650, -0.04 * size))
    return widget


def separator() -> QFrame:
    line = QFrame()
    line.setObjectName("LSSeparator")
    line.setFrameShape(QFrame.Shape.NoFrame)
    return line


# --- Boutons -----------------------------------------------------------------

_ICON_COLORS = {
    "primary": t.TEXT,
    "secondary": t.TEXT_3,
    "ghost": t.TEXT_3,
    "danger": t.ERROR,
}


class LSButton(QPushButton):
    def __init__(
        self,
        text: str = "",
        variant: str = "secondary",
        icon: str | None = None,
        small: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self.setProperty("variant", variant)
        if small:
            self.setProperty("size", "small")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        if icon:
            color = _ICON_COLORS.get(variant, t.TEXT_3)
            self.setIcon(icons.icon(icon, color, t.TEXT, size=16))
            self.setIconSize(icons.icon_size(15 if small else 16))


class LSIconButton(QToolButton):
    def __init__(
        self,
        icon: str,
        tip: str = "",
        checkable: bool = False,
        size: int = 17,
        shortcut: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("LSIconButton")
        active = t.ACCENT_TEXT if checkable else t.TEXT
        self.setIcon(icons.icon(icon, t.TEXT_3, active, size=size))
        self.setIconSize(icons.icon_size(size))
        self.setCheckable(checkable)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setAutoRaise(True)
        if tip:
            tooltip(self, tip, shortcut)


# --- Badges, icônes ------------------------------------------------------------


class LSBadge(QLabel):
    def __init__(self, text: str, tint: str = "neutral", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("LSBadge")
        self.setProperty("tint", tint)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def set_tint(self, tint: str) -> None:
        set_prop(self, "tint", tint)


class LSIconBox(QLabel):
    """Petite icône dans un conteneur coloré arrondi (cartes statistiques, en-têtes)."""

    def __init__(self, icon: str, tint: str = "blue", size: int = 34, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        background, foreground, _ = t.tint(tint)
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setPixmap(icons.pixmap(icon, foreground, int(size * 0.5)))
        self.setStyleSheet(f"background: {background}; border-radius: {int(size * 0.3)}px;")


# --- Cartes ------------------------------------------------------------------


class LSCard(QFrame):
    """Carte (couleur « panneau » des tokens) à coins arrondis, avec en-tête optionnel."""

    clicked = Signal()

    def __init__(
        self,
        title: str | None = None,
        icon: str | None = None,
        padding: int | None = None,
        interactive: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("LSCard")
        if interactive:
            self.setProperty("interactive", True)
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        pad = density().card_padding if padding is None else padding
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(pad, pad, pad, pad)
        self._layout.setSpacing(12)
        self.header_actions = QHBoxLayout()
        self.header_actions.setSpacing(6)
        if title:
            header = QHBoxLayout()
            header.setSpacing(9)
            if icon:
                header_icon = QLabel()
                header_icon.setPixmap(icons.pixmap(icon, t.TEXT_2, 16))
                header.addWidget(header_icon)
            header.addWidget(label(title, "h3"))
            header.addStretch(1)
            header.addLayout(self.header_actions)
            self._layout.addLayout(header)
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        self._layout.addLayout(self.body, 1)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.property("interactive") and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class LSSectionHeader(QWidget):
    """Petit label + titre fort + sous-titre + actions alignées à droite."""

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        eyebrow_text: str = "",
        size: int = 29,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        texts = QVBoxLayout()
        texts.setSpacing(6)
        if eyebrow_text:
            texts.addWidget(eyebrow(eyebrow_text))
        self.title = heading(title, size)
        texts.addWidget(self.title)
        self.subtitle = label(subtitle, "subtitle", wrap=True)
        if subtitle:
            texts.addWidget(self.subtitle)
        layout.addLayout(texts, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(10)
        layout.addLayout(self.actions)
        layout.setAlignment(self.actions, Qt.AlignmentFlag.AlignTop)


class Breadcrumb(QWidget):
    def __init__(self, parts: Sequence[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(10)
        self.set_parts(parts)

    def set_parts(self, parts: Sequence[str]) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for index, part in enumerate(parts):
            last = index == len(parts) - 1
            self._layout.addWidget(label(part, "breadcrumb-current" if last else "breadcrumb"))
            if not last:
                chevron = QLabel()
                chevron.setPixmap(icons.pixmap("chevron-right", t.TEXT_FAINT, 12))
                self._layout.addWidget(chevron)
        self._layout.addStretch(1)


# --- Statistiques -------------------------------------------------------------


@dataclass
class StatSpec:
    title: str
    icon: str
    tint: str
    value: str = "—"
    unit: str = ""
    detail: str = ""


class LSStatCell(QFrame):
    def __init__(self, spec: StatSpec, last: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LSStatCell")
        if last:
            self.setProperty("last", True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(13)
        layout.addWidget(LSIconBox(spec.icon, spec.tint, 34), 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(4)
        self.title_label = label(spec.title)
        self.title_label.setStyleSheet(f"color: {t.TEXT_2}; font-size: 11px;")
        value_row = QHBoxLayout()
        value_row.setSpacing(5)
        self.value_label = label(spec.value, "value")
        self.value_label.setFont(fonts.font(27, 700, -0.5))
        self.unit_label = label(spec.unit)
        self.unit_label.setStyleSheet(f"color: {t.TEXT_MUTED}; font-size: 11px;")
        value_row.addWidget(self.value_label)
        value_row.addWidget(self.unit_label, 0, Qt.AlignmentFlag.AlignBottom)
        value_row.addStretch(1)
        self.detail_label = label(spec.detail)
        self.detail_label.setStyleSheet(f"color: {t.TEXT_MUTED}; font-size: 10px;")
        texts.addWidget(self.title_label)
        texts.addLayout(value_row)
        texts.addWidget(self.detail_label)
        layout.addLayout(texts, 1)

    def set_value(self, value: str, unit: str = "", detail: str | None = None) -> None:
        self.value_label.setText(value)
        self.unit_label.setText(unit)
        if detail is not None:
            self.detail_label.setText(detail)


class LSStatsGrid(QFrame):
    def __init__(self, specs: Sequence[StatSpec], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LSStatsGrid")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.cells = [LSStatCell(spec, i == len(specs) - 1) for i, spec in enumerate(specs)]
        for cell in self.cells:
            layout.addWidget(cell, 1)


# --- Champs -------------------------------------------------------------------


class LSInput(QLineEdit):
    def __init__(self, placeholder: str = "", icon: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        if icon:
            self.addAction(icons.icon(icon, t.TEXT_MUTED, size=15), QLineEdit.ActionPosition.LeadingPosition)


class LSSelect(QComboBox):
    def __init__(self, items: Sequence[tuple[str, object]] = (), parent: QWidget | None = None) -> None:
        super().__init__(parent)
        for text, data in items:
            self.addItem(text, data)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def select_data(self, data: object) -> None:
        index = self.findData(data)
        if index >= 0:
            self.setCurrentIndex(index)


class LSTabs(QTabWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDocumentMode(True)
        self.tabBar().setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.tabBar().setExpanding(False)


class LSProgress(QWidget):
    """Barre fine + libellé + pourcentage. ``set_busy`` pour une durée inconnue."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        row = QHBoxLayout()
        self.label = label("", "muted")
        self.percent = label("", "faint")
        row.addWidget(self.label, 1)
        row.addWidget(self.percent)
        layout.addLayout(row)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        layout.addWidget(self.bar)

    def set_progress(self, value: float, text: str = "") -> None:
        value = max(0.0, min(1.0, value))
        self.bar.setRange(0, 100)
        self.bar.setValue(int(value * 100))
        self.percent.setText(f"{int(value * 100)} %")
        if text:
            self.label.setText(text)

    def set_busy(self, text: str) -> None:
        self.bar.setRange(0, 0)
        self.percent.setText("")
        self.label.setText(text)

    def reset(self, text: str = "") -> None:
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.percent.setText("")
        self.label.setText(text)


# --- Champs numériques à glisser ---------------------------------------------


class ScrubSpinBox(QDoubleSpinBox):
    """Champ numérique compact. ``editing_done`` signale la fin d'une modification."""

    editing_done = Signal()

    def __init__(
        self,
        minimum: float,
        maximum: float,
        step: float,
        decimals: int,
        suffix: str = "",
        axis: str | None = None,
    ) -> None:
        super().__init__()
        self.setRange(minimum, maximum)
        self.setSingleStep(step)
        self.setDecimals(decimals)
        self.setSuffix(suffix)
        self.setKeyboardTracking(False)
        self.setAccelerated(True)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(58)
        if axis:
            self.setProperty("axis", axis)
        self.editingFinished.connect(self.editing_done)


class ScrubLabel(QLabel):
    """Libellé d'axe : glisser horizontalement modifie la valeur (comme dans les DCC 3D)."""

    def __init__(self, text: str, spin: ScrubSpinBox, color: str) -> None:
        super().__init__(text)
        self._spin = spin
        self._origin: QPoint | None = None
        self._start = 0.0
        self.setCursor(QCursor(Qt.CursorShape.SizeHorCursor))
        self.setStyleSheet(f"color: {color}; font-weight: 700; font-size: 10px;")
        self.setFixedWidth(12)
        tooltip(self, "Glisser horizontalement pour ajuster (Maj : réglage fin)")

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._origin = event.globalPosition().toPoint()
        self._start = self._spin.value()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._origin is None:
            return
        dx = event.globalPosition().toPoint().x() - self._origin.x()
        factor = 0.1 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1.0
        self._spin.setValue(self._start + dx * self._spin.singleStep() * 0.25 * factor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._origin is not None:
            self._origin = None
            self._spin.editing_done.emit()


_AXES = (("X", "x", t.AXIS_X), ("Y", "y", t.AXIS_Y), ("Z", "z", t.AXIS_Z))


class LSPropertyField(QWidget):
    """Ligne de propriété : libellé + 1 à 3 champs numériques (X/Y/Z colorés).

    ``value_changed`` : chaque changement (aperçu en direct).
    ``edit_finished`` : fin de l'interaction (validation, utile pour l'historique).
    """

    value_changed = Signal(list)
    edit_finished = Signal(list)

    def __init__(
        self,
        title: str,
        components: int = 3,
        minimum: float = -1e5,
        maximum: float = 1e5,
        step: float = 0.1,
        decimals: int = 3,
        suffix: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.title = label(title, "muted")
        self.title.setFixedWidth(70)
        layout.addWidget(self.title)
        self.spins: list[ScrubSpinBox] = []
        for index in range(components):
            text, axis, color = _AXES[index] if components > 1 else ("", None, t.TEXT_3)
            spin = ScrubSpinBox(minimum, maximum, step, decimals, suffix, axis)
            if text:
                layout.addWidget(ScrubLabel(text, spin, color))
            spin.valueChanged.connect(self._changed)
            spin.editing_done.connect(lambda: self.edit_finished.emit(self.value()))
            layout.addWidget(spin, 1)
            self.spins.append(spin)

    def value(self) -> list[float]:
        return [s.value() for s in self.spins]

    def set_value(self, values: Sequence[float]) -> None:
        for spin, value in zip(self.spins, values, strict=False):
            spin.blockSignals(True)
            spin.setValue(float(value))
            spin.blockSignals(False)

    def set_fields_enabled(self, enabled: bool) -> None:
        for spin in self.spins:
            spin.setEnabled(enabled)

    def _changed(self) -> None:
        self.value_changed.emit(self.value())


# --- Fenêtres modales ---------------------------------------------------------


class LSModal(QDialog):
    """Fenêtre modale : en-tête (icône, titre, sous-titre), corps, barre d'actions."""

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        icon: str = "info",
        tint: str = "blue",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("LSModal")
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self.result_value: str | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header = QFrame()
        header.setObjectName("LSModalHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(22, 18, 22, 18)
        header_layout.setSpacing(13)
        header_layout.addWidget(LSIconBox(icon, tint, 38))
        texts = QVBoxLayout()
        texts.setSpacing(3)
        texts.addWidget(label(title, "h3"))
        if subtitle:
            texts.addWidget(label(subtitle, "subtitle", wrap=True))
        header_layout.addLayout(texts, 1)
        outer.addWidget(header)
        body_widget = QWidget()
        self.body = QVBoxLayout(body_widget)
        self.body.setContentsMargins(22, 20, 22, 16)
        self.body.setSpacing(12)
        outer.addWidget(body_widget, 1)
        actions = QFrame()
        actions.setObjectName("LSModalActions")
        self.actions = QHBoxLayout(actions)
        self.actions.setContentsMargins(22, 14, 22, 16)
        self.actions.setSpacing(10)
        self.actions.addStretch(1)
        outer.addWidget(actions)

    def add_button(
        self,
        text: str,
        variant: str = "secondary",
        value: str = "cancel",
        icon: str | None = None,
        accept: bool = False,
    ) -> LSButton:
        """Ajoute un bouton ; un clic mémorise ``value`` dans ``result_value`` et ferme."""
        button = LSButton(text, variant, icon)

        def choose() -> None:
            self.result_value = value
            if accept:
                self.accept()
            else:
                self.reject()

        button.clicked.connect(choose)
        if accept:
            button.setDefault(True)
        self.actions.addWidget(button)
        return button

    # --- Raccourcis (remplaçables dans les tests) -------------------------
    @staticmethod
    def confirm(
        parent: QWidget | None,
        title: str,
        message: str,
        confirm_text: str = "Confirmer",
        danger: bool = False,
    ) -> bool:
        modal = LSModal(
            title,
            icon="triangle-alert" if danger else "info",
            tint="red" if danger else "blue",
            parent=parent,
        )
        modal.body.addWidget(label(message, "subtitle", wrap=True))
        modal.add_button("Annuler")
        modal.add_button(confirm_text, "danger" if danger else "primary", "ok", accept=True)
        return modal.exec() == QDialog.DialogCode.Accepted

    @staticmethod
    def ask_save(parent: QWidget | None, project_name: str) -> str:
        """Retourne 'save', 'discard' ou 'cancel'."""
        modal = LSModal(
            "Modifications non enregistrées",
            f"Le projet « {project_name} » a été modifié.",
            "save",
            "amber",
            parent,
        )
        modal.body.addWidget(label("Voulez-vous enregistrer avant de continuer ?", "subtitle"))
        modal.add_button("Annuler", value="cancel")
        modal.add_button("Ne pas enregistrer", "ghost", "discard", accept=True)
        modal.add_button("Enregistrer", "primary", "save", "save", accept=True)
        modal.exec()
        return modal.result_value or "cancel"

    @staticmethod
    def error(parent: QWidget | None, title: str, message: str) -> None:
        modal = LSModal(title, icon="circle-x", tint="red", parent=parent)
        text = label(message, "subtitle", wrap=True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        modal.body.addWidget(text)
        modal.add_button("Fermer", "primary", "ok", accept=True)
        modal.exec()

    @staticmethod
    def info(parent: QWidget | None, title: str, message: str) -> None:
        modal = LSModal(title, icon="info", tint="blue", parent=parent)
        modal.body.addWidget(label(message, "subtitle", wrap=True))
        modal.add_button("Fermer", "primary", "ok", accept=True)
        modal.exec()


# --- Notifications ------------------------------------------------------------

LEVEL_STYLE = {
    "info": ("info", "blue"),
    "success": ("circle-check", "green"),
    "warning": ("triangle-alert", "amber"),
    "error": ("circle-x", "red"),
}


@dataclass
class Notification:
    title: str
    message: str = ""
    level: str = "info"
    time: datetime = field(default_factory=datetime.now)


class LSNotification(QFrame):
    """Toast : apparition / disparition courtes (160 ms), fermeture automatique."""

    closed = Signal()

    def __init__(
        self, notification: Notification, parent: QWidget, duration_ms: int = t.AnimationTokens.TOAST_MS
    ) -> None:
        super().__init__(parent)
        self.setObjectName("LSToast")
        self.setProperty("level", notification.level)
        self.setFixedWidth(340)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 10, 12)
        layout.setSpacing(12)
        icon_name, tint = LEVEL_STYLE.get(notification.level, LEVEL_STYLE["info"])
        layout.addWidget(LSIconBox(icon_name, tint, 30), 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(3)
        title = label(notification.title, wrap=True)
        title.setStyleSheet(f"font-weight: 600; color: {t.TEXT};")
        texts.addWidget(title)
        if notification.message:
            texts.addWidget(label(notification.message, "muted", wrap=True))
        layout.addLayout(texts, 1)
        close = LSIconButton("x", "Fermer", size=14)
        close.clicked.connect(self.dismiss)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(t.AnimationTokens.NORMAL_MS)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._closing = False
        self.adjustSize()
        self.show()
        self._animate(1.0)
        if duration_ms > 0:
            QTimer.singleShot(duration_ms, self.dismiss)

    def _animate(self, target: float) -> None:
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(target)
        self._fade.start()

    def dismiss(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._fade.finished.connect(self._finish)
        self._animate(0.0)

    def _finish(self) -> None:
        self.hide()
        self.closed.emit()
        self.deleteLater()


class NotificationCenter(QObject):
    """Empile les toasts en haut à droite de la fenêtre et garde l'historique (cloche)."""

    changed = Signal()

    def __init__(self, host: QWidget, top_offset: int = t.TITLEBAR_HEIGHT + 12) -> None:
        super().__init__(host)
        self._host = host
        self._top = top_offset
        self.history: list[Notification] = []
        self.unread = 0
        self._toasts: list[LSNotification] = []
        host.installEventFilter(self)

    def notify(
        self,
        title: str,
        message: str = "",
        level: str = "info",
        duration_ms: int = t.AnimationTokens.TOAST_MS,
    ) -> Notification:
        notification = Notification(title, message, level)
        self.history.insert(0, notification)
        del self.history[50:]
        self.unread += 1
        toast = LSNotification(notification, self._host, duration_ms)
        toast.closed.connect(lambda: self._remove(toast))
        self._toasts.append(toast)
        self._layout_toasts()
        self.changed.emit()
        return notification

    def mark_read(self) -> None:
        self.unread = 0
        self.changed.emit()

    def active_toasts(self) -> list[LSNotification]:
        return list(self._toasts)

    def _remove(self, toast: LSNotification) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        self._layout_toasts()

    def _layout_toasts(self) -> None:
        y = self._top
        for toast in reversed(self._toasts[-4:]):
            toast.move(self._host.width() - toast.width() - 18, y)
            toast.raise_()
            y += toast.height() + 10

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self._host and event.type() == QEvent.Type.Resize:
            self._layout_toasts()
        return False


# --- États vides --------------------------------------------------------------


class LSEmptyState(QWidget):
    def __init__(
        self,
        icon: str,
        title: str,
        text: str = "",
        action: tuple[str, Callable[[], object]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 26, 20, 26)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(LSIconBox(icon, "blue", 44), 0, Qt.AlignmentFlag.AlignHCenter)
        title_label = label(title, "h3")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        if text:
            body = label(text, "muted", wrap=True)
            body.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(body)
        if action:
            button = LSButton(action[0], "secondary", small=True)
            button.clicked.connect(lambda: action[1]())
            layout.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)
