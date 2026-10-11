"""Page d'accueil : gestionnaire de projets (création, ouverture, projets récents)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from lsfcars import APP_NAME, __version__
from lsfcars.project import recent
from lsfcars.ui.theme import COLORS

PATH_ROLE = Qt.ItemDataRole.UserRole

ROADMAP = [
    ("✅", "Projets, viewport 3D, import GLB / OBJ, logs", "v0.1"),
    ("🕓", "Édition 3D avancée, matériaux et textures", "prévu"),
    ("🕓", "Import de véhicules GTA V / FiveM existants", "prévu"),
    ("🕓", "Atelier de livrées", "prévu"),
    ("🕓", "Atelier LSPD / EMS (équipements, gyrophares)", "prévu"),
    ("🕓", "Génération 3D par IA depuis des images", "prévu"),
    ("🕓", "Optimisation et export de ressource FiveM", "prévu"),
]


def _card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(10)
    return frame, layout


class HomePage(QWidget):
    new_requested = Signal()
    open_requested = Signal(object)  # Path | None (None = boîte de dialogue)
    sample_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 32, 40, 32)
        root.setSpacing(20)

        title = QLabel(APP_NAME)
        title.setObjectName("H1")
        subtitle = QLabel(
            "Créez, adaptez et préparez vos véhicules Lore Friendly pour FiveM — "
            f"version {__version__}"
        )
        subtitle.setObjectName("Muted")
        root.addWidget(title)
        root.addWidget(subtitle)

        columns = QHBoxLayout()
        columns.setSpacing(20)
        root.addLayout(columns, 1)

        # Colonne gauche : démarrer + récents
        left = QVBoxLayout()
        left.setSpacing(20)
        start_card, start = _card()
        start_title = QLabel("Démarrer")
        start_title.setObjectName("H2")
        start.addWidget(start_title)
        self.new_button = QPushButton("Nouveau projet…")
        self.new_button.setProperty("primary", True)
        self.new_button.clicked.connect(self.new_requested)
        self.open_button = QPushButton("Ouvrir un projet…")
        self.open_button.clicked.connect(lambda: self.open_requested.emit(None))
        self.sample_button = QPushButton("Découvrir avec le véhicule d'exemple")
        self.sample_button.setToolTip(
            "Crée un projet de démonstration contenant un véhicule de test libre de droits."
        )
        self.sample_button.clicked.connect(self.sample_requested)
        buttons = QHBoxLayout()
        for button in (self.new_button, self.open_button, self.sample_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        start.addLayout(buttons)
        left.addWidget(start_card)

        recent_card, recent_layout = _card()
        recent_title = QLabel("Projets récents")
        recent_title.setObjectName("H2")
        recent_layout.addWidget(recent_title)
        self.recent_list = QListWidget()
        self.recent_list.itemActivated.connect(self._open_item)
        self.recent_list.itemSelectionChanged.connect(self._update_buttons)
        recent_layout.addWidget(self.recent_list, 1)
        self.recent_empty = QLabel(
            "Aucun projet récent. Créez un projet ou essayez le véhicule d'exemple."
        )
        self.recent_empty.setObjectName("Muted")
        recent_layout.addWidget(self.recent_empty)
        self._recent_spacer = QWidget()
        self._recent_spacer.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        recent_layout.addWidget(self._recent_spacer)
        recent_buttons = QHBoxLayout()
        self.open_recent_button = QPushButton("Ouvrir")
        self.open_recent_button.clicked.connect(self._open_selected)
        self.remove_recent_button = QPushButton("Retirer de la liste")
        self.remove_recent_button.clicked.connect(self._remove_selected)
        recent_buttons.addWidget(self.open_recent_button)
        recent_buttons.addWidget(self.remove_recent_button)
        recent_buttons.addStretch(1)
        recent_layout.addLayout(recent_buttons)
        left.addWidget(recent_card, 1)
        columns.addLayout(left, 3)

        # Colonne droite : feuille de route (honnête sur l'état réel)
        roadmap_card, roadmap = _card()
        roadmap_title = QLabel("Feuille de route")
        roadmap_title.setObjectName("H2")
        roadmap.addWidget(roadmap_title)
        for icon, label, status in ROADMAP:
            row = QLabel(
                f"{icon}  {label}  <span style='color:{COLORS['muted']}'>· {status}</span>"
            )
            row.setWordWrap(True)
            roadmap.addWidget(row)
        roadmap.addStretch(1)
        tips = QLabel(
            "Astuce : dans le viewport, clic gauche pour tourner autour du véhicule, "
            "clic droit pour déplacer la vue, molette pour zoomer, F pour cadrer."
        )
        tips.setObjectName("Muted")
        tips.setWordWrap(True)
        roadmap.addWidget(tips)
        columns.addWidget(roadmap_card, 2)

        self.refresh_recent()

    def refresh_recent(self) -> None:
        self.recent_list.clear()
        for path in recent.list_recent():
            item = QListWidgetItem(f"{path.stem}\n{path}")
            item.setData(PATH_ROLE, str(path))
            if not path.is_file():
                item.setText(f"{path.stem}  (introuvable)\n{path}")
                item.setForeground(QBrush(QColor(COLORS["muted"])))
            self.recent_list.addItem(item)
        has_items = self.recent_list.count() > 0
        self.recent_list.setVisible(has_items)
        self.recent_empty.setVisible(not has_items)
        self._recent_spacer.setVisible(not has_items)
        self._update_buttons()

    def _selected_path(self) -> Path | None:
        items = self.recent_list.selectedItems()
        return Path(items[0].data(PATH_ROLE)) if items else None

    def _update_buttons(self) -> None:
        selected = self._selected_path() is not None
        self.open_recent_button.setEnabled(selected)
        self.remove_recent_button.setEnabled(selected)

    def _open_item(self, item: QListWidgetItem) -> None:
        self.open_requested.emit(Path(item.data(PATH_ROLE)))

    def _open_selected(self) -> None:
        path = self._selected_path()
        if path is not None:
            self.open_requested.emit(path)

    def _remove_selected(self) -> None:
        path = self._selected_path()
        if path is not None:
            recent.remove_recent(path)
            self.refresh_recent()
