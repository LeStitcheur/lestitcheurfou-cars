"""Explorateur d'objets : arborescence de la scène avec visibilité."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lsfcars.project.session import ProjectSession
from lsfcars.ui.theme import COLORS

ID_ROLE = Qt.ItemDataRole.UserRole


class ObjectExplorer(QWidget):
    selection_changed = Signal(object)  # str | None
    visibility_toggled = Signal(str, bool)
    delete_requested = Signal(str)
    frame_requested = Signal(str)
    import_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session: ProjectSession | None = None
        self._updating = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        buttons = QHBoxLayout()
        self.import_button = QPushButton("Importer…")
        self.import_button.setProperty("primary", True)
        self.import_button.setToolTip("Importer un fichier GLB, glTF, OBJ, STL ou PLY (Ctrl+I)")
        self.import_button.clicked.connect(self.import_requested)
        self.delete_button = QPushButton("Retirer")
        self.delete_button.setToolTip("Retirer l'objet sélectionné de la scène (Suppr)")
        self.delete_button.clicked.connect(self._request_delete)
        buttons.addWidget(self.import_button, 1)
        buttons.addWidget(self.delete_button)
        layout.addLayout(buttons)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.itemSelectionChanged.connect(self._on_selection)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.tree, 1)

        self.empty_label = QLabel("Aucun objet.\nImportez un modèle 3D pour commencer.")
        self.empty_label.setObjectName("Muted")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)
        self.set_session(None)

    # --- Remplissage --------------------------------------------------------
    def set_session(self, session: ProjectSession | None) -> None:
        self._session = session
        self.refresh()

    def refresh(self) -> None:
        selected = self.selected_id()
        self._updating = True
        self.tree.clear()
        session = self._session
        self.import_button.setEnabled(session is not None)
        if session is not None:
            for obj in session.project.objects:
                item = QTreeWidgetItem([obj.name])
                item.setData(0, ID_ROLE, obj.id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    0, Qt.CheckState.Checked if obj.visible else Qt.CheckState.Unchecked
                )
                triangles, _ = session.stats(obj.id)
                tooltip = f"{obj.asset_path}\n{triangles:,} triangles".replace(",", " ")
                if obj.id in session.missing:
                    item.setText(0, f"{obj.name}  (fichier manquant)")
                    item.setForeground(0, QBrush(QColor(COLORS["warning"])))
                    tooltip = session.missing[obj.id]
                item.setToolTip(0, tooltip)
                self.tree.addTopLevelItem(item)
        count = self.tree.topLevelItemCount()
        self.empty_label.setVisible(session is not None and count == 0)
        self.tree.setVisible(count > 0)
        self._updating = False
        self.select(selected, emit=False)

    # --- Sélection ----------------------------------------------------------
    def selected_id(self) -> str | None:
        items = self.tree.selectedItems()
        return items[0].data(0, ID_ROLE) if items else None

    def select(self, object_id: str | None, emit: bool = True) -> None:
        self._updating = not emit
        self.tree.clearSelection()
        if object_id is not None:
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                if item.data(0, ID_ROLE) == object_id:
                    item.setSelected(True)
                    self.tree.scrollToItem(item)
                    break
        self._updating = False
        self.delete_button.setEnabled(self.selected_id() is not None)

    def _on_selection(self) -> None:
        self.delete_button.setEnabled(self.selected_id() is not None)
        if not self._updating:
            self.selection_changed.emit(self.selected_id())

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating:
            return
        visible = item.checkState(0) == Qt.CheckState.Checked
        self.visibility_toggled.emit(item.data(0, ID_ROLE), visible)

    def _on_double_click(self, item: QTreeWidgetItem, column: int) -> None:
        self.frame_requested.emit(item.data(0, ID_ROLE))

    def _request_delete(self) -> None:
        object_id = self.selected_id()
        if object_id:
            self.delete_requested.emit(object_id)

    def _context_menu(self, pos: QPoint) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        object_id = item.data(0, ID_ROLE)
        visible = item.checkState(0) == Qt.CheckState.Checked
        menu = QMenu(self)
        menu.addAction("Cadrer dans la vue", lambda: self.frame_requested.emit(object_id))
        menu.addAction(
            "Masquer" if visible else "Afficher",
            lambda: self.visibility_toggled.emit(object_id, not visible),
        )
        menu.addSeparator()
        menu.addAction("Retirer de la scène", lambda: self.delete_requested.emit(object_id))
        menu.exec(self.tree.viewport().mapToGlobal(pos))
