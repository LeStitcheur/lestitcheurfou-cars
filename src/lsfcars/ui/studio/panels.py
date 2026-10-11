"""Panneaux du studio : explorateur de scène, propriétés, matériaux, panneau inférieur."""

from __future__ import annotations

import itertools
from datetime import datetime

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QDropEvent, QPainter, QPaintEvent, QRadialGradient
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QMenu,
    QPushButton,
    QScrollArea,
    QSlider,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lsfcars.scene.graph import NodeKind, SceneNode
from lsfcars.scene.materials import Material
from lsfcars.scene.transform import Transform
from lsfcars.ui.design import icons
from lsfcars.ui.design import tokens as t
from lsfcars.ui.design.components import (
    LSBadge,
    LSButton,
    LSEmptyState,
    LSIconBox,
    LSIconButton,
    LSInput,
    LSProgress,
    LSPropertyField,
    LSSelect,
    LSTabs,
    eyebrow,
    label,
    separator,
    tooltip,
)
from lsfcars.ui.panels.log_panel import LogPanel
from lsfcars.ui.studio.controller import StudioController

ID_ROLE = Qt.ItemDataRole.UserRole
KIND_ICONS = {NodeKind.MODEL: "car", NodeKind.GROUP: "layers", NodeKind.MESH: "cuboid"}
_serials = itertools.count(1)


def _fmt(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return iso or "—"


# --- Explorateur de scène ---------------------------------------------------------


class _SceneTree(QTreeWidget):
    """Arbre dont le glisser-déposer change le parent via l'historique (pas Qt)."""

    def __init__(self, explorer: SceneExplorer) -> None:
        super().__init__()
        self._explorer = explorer

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        target = self.itemAt(event.position().toPoint())
        indicator = self.dropIndicatorPosition()
        if target is None:
            parent_id = None
        elif indicator == QAbstractItemView.DropIndicatorPosition.OnItem:
            parent_id = target.data(0, ID_ROLE)
        else:
            parent = target.parent()
            parent_id = parent.data(0, ID_ROLE) if parent else None
        event.setDropAction(Qt.DropAction.IgnoreAction)
        event.accept()
        self._explorer.reparent_selection(parent_id)


class SceneExplorer(QWidget):
    def __init__(self, controller: StudioController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._updating = False
        self._collapsed: set[str] = set()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 8)
        layout.setSpacing(8)
        header = QHBoxLayout()
        header.addWidget(eyebrow("Scène"))
        header.addStretch(1)
        self.group_button = LSIconButton(
            "group", "Grouper la sélection", size=15, shortcut="Ctrl+G"
        )
        self.group_button.clicked.connect(controller.group_selected)
        self.dup_button = LSIconButton("copy-plus", "Dupliquer", size=15, shortcut="Ctrl+D")
        self.dup_button.clicked.connect(controller.duplicate_selected)
        self.del_button = LSIconButton("trash-2", "Supprimer", size=15, shortcut="Suppr")
        self.del_button.clicked.connect(lambda: self.window().delete_selection())
        for button in (self.group_button, self.dup_button, self.del_button):
            header.addWidget(button)
        layout.addLayout(header)
        self.search = LSInput("Rechercher dans la scène…", "search")
        self.search.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search)

        self.tree = _SceneTree(self)
        self.tree.setColumnCount(3)
        self.tree.setHeaderHidden(True)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2):
            self.tree.header().setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.tree.setColumnWidth(column, 26)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tree.setEditTriggers(
            QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.DoubleClicked
        )
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.itemSelectionChanged.connect(self._on_selection)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemCollapsed.connect(lambda i: self._collapsed.add(i.data(0, ID_ROLE)))
        self.tree.itemExpanded.connect(lambda i: self._collapsed.discard(i.data(0, ID_ROLE)))
        layout.addWidget(self.tree, 1)
        self.empty = LSEmptyState("cuboid", "Scène vide", "Importez un modèle 3D pour commencer.")
        layout.addWidget(self.empty)
        self.footer = label("", "faint")
        layout.addWidget(self.footer)

        controller.session_changed.connect(self.rebuild)
        controller.scene_changed.connect(
            lambda kind: self.rebuild() if kind in ("structure", "property") else None
        )
        controller.selection_changed.connect(self.sync_selection)
        self.rebuild()

    def _make_item(self, node: SceneNode) -> QTreeWidgetItem:
        scene = self.controller.session.scene
        item = QTreeWidgetItem([node.name, "", ""])
        item.setData(0, ID_ROLE, node.id)
        item.setFlags(
            item.flags()
            | Qt.ItemFlag.ItemIsEditable
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemIsDropEnabled
        )
        dim = not scene.effective_visible(node.id)
        item.setIcon(
            0, icons.icon(KIND_ICONS[node.kind], t.TEXT_FAINT if dim else "#9aa8ba", size=15)
        )
        item.setIcon(
            1,
            icons.icon(
                "eye" if node.visible else "eye-off",
                "#7e8da0" if node.visible else t.TEXT_FAINT,
                size=14,
            ),
        )
        item.setIcon(
            2,
            icons.icon(
                "lock" if node.locked else "lock-open",
                t.WARNING if node.locked else "#3a4552",
                size=14,
            ),
        )
        item.setToolTip(0, f"{node.kind.label} — {scene.path(node.id)}")
        item.setToolTip(1, "Masquer / afficher")
        item.setToolTip(2, "Verrouiller / déverrouiller")
        if dim:
            item.setForeground(0, QBrush(QColor(t.TEXT_FAINT)))
        return item

    def rebuild(self) -> None:
        session = self.controller.session
        self._updating = True
        self.tree.clear()
        has_nodes = session is not None and len(session.scene) > 0
        if session is not None:

            def add(parent_item: QTreeWidgetItem | None, parent_id: str | None) -> None:
                for node in session.scene.children(parent_id):
                    item = self._make_item(node)
                    if parent_item is None:
                        self.tree.addTopLevelItem(item)
                    else:
                        parent_item.addChild(item)
                    add(item, node.id)
                    item.setExpanded(
                        node.id not in self._collapsed and node.kind is not NodeKind.MESH
                    )

            add(None, None)
            triangles, _v, meshes = session.stats()
            self.footer.setText(
                f"{len(session.scene)} nœuds · {meshes} maillages · {_fmt(triangles)} triangles"
            )
        else:
            self.footer.setText("Aucun projet ouvert")
        self.tree.setVisible(has_nodes)
        self.empty.setVisible(not has_nodes)
        self._updating = False
        self.sync_selection()
        self._apply_filter()

    def items(self) -> list[QTreeWidgetItem]:
        result = []
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            result.append(item)
            stack.extend(item.child(i) for i in range(item.childCount()))
        return result

    def item_for(self, node_id: str) -> QTreeWidgetItem | None:
        return next((i for i in self.items() if i.data(0, ID_ROLE) == node_id), None)

    def sync_selection(self) -> None:
        session = self.controller.session
        if session is None:
            return
        selected = set(session.selection.ids)
        self._updating = True
        for item in self.items():
            item.setSelected(item.data(0, ID_ROLE) in selected)
            if item.data(0, ID_ROLE) == session.selection.active:
                self.tree.scrollToItem(item)
        self._updating = False
        for button in (self.group_button, self.dup_button, self.del_button):
            button.setEnabled(bool(selected))

    def _apply_filter(self) -> None:
        text = self.search.text().strip().lower()

        def visit(item: QTreeWidgetItem) -> bool:
            child_match = any([visit(item.child(i)) for i in range(item.childCount())])
            match = not text or text in item.text(0).lower() or child_match
            item.setHidden(not match)
            if text and child_match:
                item.setExpanded(True)
            return match

        for i in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(i))

    def _on_selection(self) -> None:
        if self._updating:
            return
        ids = [item.data(0, ID_ROLE) for item in self.tree.selectedItems()]
        current = self.tree.currentItem()
        if current is not None and current.data(0, ID_ROLE) in ids:  # l'actif en dernier
            ids.remove(current.data(0, ID_ROLE))
            ids.append(current.data(0, ID_ROLE))
        self.controller.select(ids)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if not self._updating and column == 0:
            self.controller.rename(item.data(0, ID_ROLE), item.text(0))

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        session = self.controller.session
        node = session.scene.get(item.data(0, ID_ROLE)) if session else None
        if node is None:
            return
        if column == 1:
            self.controller.set_visible([node.id], not node.visible)
        elif column == 2:
            self.controller.set_locked([node.id], not node.locked)

    def reparent_selection(self, parent_id: str | None) -> None:
        self.controller.reparent(self.controller.selected(), parent_id)

    def _context_menu(self, pos: QPoint) -> None:
        item = self.tree.itemAt(pos)
        session = self.controller.session
        node = session.scene.get(item.data(0, ID_ROLE)) if item and session else None
        if node is None:
            return
        if node.id not in self.controller.selected():
            self.controller.select([node.id])
        ids = self.controller.selected()
        window = self.window()
        ctl = self.controller
        menu = QMenu(self)
        menu.addAction(icons.icon("pencil"), "Renommer\tF2", lambda: self.tree.editItem(item, 0))
        menu.addAction(icons.icon("scan"), "Centrer la vue\tF", window.frame_selection)
        menu.addSeparator()
        menu.addAction(icons.icon("copy-plus"), "Dupliquer\tCtrl+D", ctl.duplicate_selected)
        menu.addAction(icons.icon("group"), "Grouper\tCtrl+G", ctl.group_selected)
        if node.kind is not NodeKind.MESH and session.scene.children(node.id):
            menu.addAction(icons.icon("ungroup"), "Dégrouper\tCtrl+Maj+G", ctl.ungroup_selected)
        if node.parent_id:
            menu.addAction(
                icons.icon("layers"), "Sortir du groupe", lambda: ctl.reparent(ids, None)
            )
        menu.addSeparator()
        menu.addAction(
            icons.icon("eye-off" if node.visible else "eye"),
            "Masquer" if node.visible else "Afficher",
            lambda: ctl.set_visible(ids, not node.visible),
        )
        menu.addAction(
            icons.icon("lock-open" if node.locked else "lock"),
            "Déverrouiller" if node.locked else "Verrouiller",
            lambda: ctl.set_locked(ids, not node.locked),
        )
        menu.addSeparator()
        menu.addAction(icons.icon("trash-2", t.ERROR), "Supprimer\tSuppr", window.delete_selection)
        menu.exec(self.tree.viewport().mapToGlobal(pos))


# --- Éditeur de matériaux --------------------------------------------------------


class MaterialPreview(QWidget):
    """Aperçu immédiat : sphère éclairée selon couleur, rugosité et métallicité."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(84, 84)
        self.material: Material | None = None

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#0d1116"))
        painter.drawRoundedRect(self.rect(), 12, 12)
        material = self.material
        if material is None:
            return
        r, g, b, a = material.base_color
        base = QColor.fromRgbF(r, g, b, max(a * material.opacity, 0.15))
        highlight = 0.35 + 0.65 * (1 - material.roughness)
        spot = QColor.fromRgbF(
            min(1.0, r * material.metallic + highlight),
            min(1.0, g * material.metallic + highlight),
            min(1.0, b * material.metallic + highlight),
            base.alphaF(),
        )
        gradient = QRadialGradient(QPointF(30, 30), 52)
        gradient.setColorAt(0.0, spot)
        gradient.setColorAt(0.12 + 0.35 * material.roughness, base)
        gradient.setColorAt(1.0, base.darker(260 if material.metallic > 0.5 else 200))
        painter.setBrush(gradient)
        painter.drawEllipse(QRectF(12, 12, 60, 60))


class _Slider(QWidget):
    def __init__(self, title: str) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.value_label = label("0,00", "faint")
        self.value_label.setFixedWidth(34)
        self.slider.valueChanged.connect(
            lambda v: self.value_label.setText(f"{v / 100:.2f}".replace(".", ","))
        )
        tooltip(self.slider, title)
        row.addWidget(self.slider, 1)
        row.addWidget(self.value_label)

    def value(self) -> float:
        return self.slider.value() / 100.0

    def set_value(self, value: float) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(round(value * 100))
        self.slider.blockSignals(False)
        self.value_label.setText(f"{value:.2f}".replace(".", ","))


class MaterialEditor(QWidget):
    def __init__(self, controller: StudioController) -> None:
        super().__init__()
        self.controller = controller
        self._updating = False
        self._serial = next(_serials)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(10)
        top = QHBoxLayout()
        self.preview = MaterialPreview()
        top.addWidget(self.preview)
        info = QVBoxLayout()
        self.select = LSSelect()
        self.select.currentIndexChanged.connect(self._on_choose)
        info.addWidget(self.select)
        buttons = QHBoxLayout()
        self.new_button = LSIconButton("plus", "Nouveau matériau", size=15)
        self.new_button.clicked.connect(self._new_material)
        self.copy_button = LSIconButton("copy-plus", "Dupliquer le matériau", size=15)
        self.copy_button.clicked.connect(lambda: self._new_material(copy=True))
        self.assign_button = LSButton("Affecter à la sélection", "secondary", "paint-bucket", True)
        self.assign_button.clicked.connect(self.assign)
        buttons.addWidget(self.new_button)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.assign_button, 1)
        info.addLayout(buttons)
        self.users = label("", "faint")
        info.addWidget(self.users)
        top.addLayout(info, 1)
        layout.addLayout(top)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(9)
        self.name = LSInput()
        self.name.editingFinished.connect(
            lambda: self.set_properties({"name": self.name.text().strip()})
        )
        self.color_button = QPushButton()
        self.color_button.setFixedHeight(28)
        self.color_button.clicked.connect(self._pick_color)
        tooltip(self.color_button, "Choisir la couleur de base")
        self.roughness = _Slider("Rugosité : 0 = brillant, 1 = mat")
        self.metallic = _Slider("Métallicité : 0 = diélectrique, 1 = métal")
        self.opacity = _Slider("Opacité : 1 = opaque")
        for field_name, slider in (
            ("roughness", self.roughness),
            ("metallic", self.metallic),
            ("opacity", self.opacity),
        ):
            slider.slider.valueChanged.connect(
                lambda _v, f=field_name, s=slider: self.set_properties({f: s.value()}, live=True)
            )
            slider.slider.sliderReleased.connect(self._next_serial)
        texture_row = QHBoxLayout()
        self.texture_label = label("Aucune", "muted", wrap=True)
        choose = LSButton("Choisir…", "secondary", "image", True)
        choose.clicked.connect(self._choose_texture)
        self.clear_texture = LSIconButton("x", "Retirer la texture", size=14)
        self.clear_texture.clicked.connect(lambda: self.set_properties({"texture": None}))
        texture_row.addWidget(self.texture_label, 1)
        texture_row.addWidget(choose)
        texture_row.addWidget(self.clear_texture)
        for title, widget in (
            ("Nom", self.name),
            ("Couleur", self.color_button),
            ("Rugosité", self.roughness),
            ("Métallicité", self.metallic),
            ("Opacité", self.opacity),
        ):
            form.addRow(label(title, "muted"), widget)
        form.addRow(label("Texture", "muted"), texture_row)
        self.form_widget = QWidget()
        self.form_widget.setLayout(form)
        layout.addWidget(self.form_widget)
        layout.addWidget(
            label(
                "Les modifications s'affichent immédiatement dans le viewport "
                "(mode Matériaux) et sont annulables (Ctrl+Z).",
                "faint",
                wrap=True,
            )
        )
        layout.addStretch(1)

    def material(self) -> Material | None:
        session = self.controller.session
        material_id = self.select.currentData()
        return session.scene.materials.get(material_id) if session and material_id else None

    def refresh(self) -> None:
        session = self.controller.session
        previous = self.select.currentData()
        self._updating = True
        self.select.clear()
        if session is not None:
            for material in sorted(session.scene.materials.values(), key=lambda m: m.name.lower()):
                self.select.addItem(icons.icon("palette", size=14), material.name, material.id)
            current = previous
            node_id = session.selection.active
            if node_id in session.scene:
                current = next(
                    (n.material_id for n in session.scene.subtree(node_id) if n.material_id),
                    current,
                )
            if current:
                self.select.select_data(current)
        self._updating = False
        has_materials = session is not None and bool(session.scene.materials)
        self.form_widget.setEnabled(has_materials)
        self.copy_button.setEnabled(has_materials)
        self.assign_button.setEnabled(has_materials and bool(self.controller.selected()))
        self.new_button.setEnabled(session is not None)
        self._fill()

    def _fill(self) -> None:
        material, session = self.material(), self.controller.session
        self.preview.material = material
        self.preview.update()
        if material is None:
            self.users.setText("Aucun matériau")
            return
        self._updating = True
        self.name.setText(material.name)
        color = QColor.fromRgbF(*material.base_color)
        self.color_button.setStyleSheet(
            f"background: {color.name()}; border: 1px solid {t.BORDER_STRONG}; border-radius: 7px;"
        )
        self.color_button.setText(color.name().upper())
        self.roughness.set_value(material.roughness)
        self.metallic.set_value(material.metallic)
        self.opacity.set_value(material.opacity)
        self.texture_label.setText(
            material.texture.split("/")[-1] if material.texture else "Aucune"
        )
        self.clear_texture.setEnabled(bool(material.texture))
        users = len(session.scene.material_users(material.id)) if session else 0
        self.users.setText(f"Utilisé par {users} maillage(s)")
        self._updating = False

    def _on_choose(self) -> None:
        if not self._updating:
            self._fill()

    def _next_serial(self) -> None:
        self._serial = next(_serials)

    def set_properties(self, properties: dict, live: bool = False) -> None:
        material, session = self.material(), self.controller.session
        if self._updating or material is None or session is None:
            return
        key = ("mat", material.id, tuple(sorted(properties)), self._serial) if live else None
        session.set_material_properties(material.id, properties, merge_key=key)
        if not live:
            self._next_serial()

    def _pick_color(self) -> None:
        material = self.material()
        if material is None:
            return
        color = QColorDialog.getColor(
            QColor.fromRgbF(*material.base_color), self, "Couleur de base"
        )
        if color.isValid():
            self.set_properties(
                {
                    "base_color": (
                        color.redF(),
                        color.greenF(),
                        color.blueF(),
                        material.base_color[3],
                    )
                }
            )

    def _choose_texture(self) -> None:
        material, session = self.material(), self.controller.session
        if material is None or session is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Choisir une texture", "", "Images (*.png *.jpg *.jpeg *.bmp *.tga)"
        )
        if path:
            session.set_texture(material.id, path)

    def _new_material(self, copy: bool = False) -> None:
        session = self.controller.session
        if session is None:
            return
        base = self.material() if copy else None
        material = session.create_material(
            f"{base.name} (copie)" if base else "Nouveau matériau", base
        )
        self.refresh()
        self.select.select_data(material.id)

    def assign(self) -> None:
        session, material = self.controller.session, self.material()
        if session and material:
            session.assign_material(self.controller.selected(), material.id)


# --- Propriétés ----------------------------------------------------------------


class PropertiesPanel(QWidget):
    def __init__(self, controller: StudioController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._updating = False
        self._serial = next(_serials)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 8)
        layout.setSpacing(8)
        header = QHBoxLayout()
        self.kind_icon = LSIconBox("cuboid", "red", 30)
        self.title = label("Aucune sélection", "h3")
        self.kind_badge = LSBadge("—")
        header.addWidget(self.kind_icon)
        header.addWidget(self.title, 1)
        header.addWidget(self.kind_badge)
        layout.addLayout(header)
        self.tabs = LSTabs()
        layout.addWidget(self.tabs, 1)

        object_tab = QWidget()
        form = QFormLayout(object_tab)
        form.setContentsMargins(0, 10, 0, 0)
        form.setVerticalSpacing(9)
        self.name = LSInput()
        self.name.editingFinished.connect(self._rename)
        self.visible = QCheckBox("Visible")
        self.visible.toggled.connect(lambda v: self._apply_flag("visible", v))
        self.locked = QCheckBox("Verrouillé")
        self.locked.toggled.connect(lambda v: self._apply_flag("locked", v))
        flags = QHBoxLayout()
        flags.addWidget(self.visible)
        flags.addWidget(self.locked)
        flags.addStretch(1)
        self.path = label("", "faint", wrap=True)
        self.geometry = label("", "muted", wrap=True)
        self.dimensions = label("", "muted", wrap=True)
        self.provenance = label("", "faint", wrap=True)
        self.provenance.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow(label("Nom", "muted"), self.name)
        form.addRow("", flags)
        form.addRow(label("Chemin", "muted"), self.path)
        form.addRow(label("Géométrie", "muted"), self.geometry)
        form.addRow(label("Dimensions", "muted"), self.dimensions)
        form.addRow(label("Provenance", "muted"), self.provenance)
        self.tabs.addTab(self._scroll(object_tab), "Objet")

        transform_tab = QWidget()
        tl = QVBoxLayout(transform_tab)
        tl.setContentsMargins(0, 10, 0, 0)
        tl.setSpacing(9)
        self.active_info = label("", "faint", wrap=True)
        tl.addWidget(self.active_info)
        self.position = LSPropertyField("Position", suffix=" m", step=0.05)
        self.rotation = LSPropertyField(
            "Rotation", minimum=-360, maximum=360, step=5, decimals=1, suffix="°"
        )
        self.scale = LSPropertyField("Échelle", minimum=0.001, maximum=1000, step=0.05)
        for name, field in (
            ("translation", self.position),
            ("rotation", self.rotation),
            ("scale", self.scale),
        ):
            field.value_changed.connect(lambda v, n=name: self._transform_changed(n, v))
            field.edit_finished.connect(lambda _v: self._next_serial())
            tl.addWidget(field)
        self.uniform = QCheckBox("Échelle uniforme")
        self.uniform.setChecked(True)
        tl.addWidget(self.uniform)
        self.dims_transform = label("", "muted", wrap=True)
        tl.addWidget(self.dims_transform)
        reset = LSButton("Réinitialiser la transformation", "ghost", "refresh-cw", True)
        reset.clicked.connect(self._reset)
        tl.addWidget(reset)
        tl.addWidget(
            label(
                "Astuce : glissez horizontalement sur X / Y / Z pour ajuster, "
                "Maj pour un réglage fin.",
                "faint",
                wrap=True,
            )
        )
        tl.addStretch(1)
        self.tabs.addTab(self._scroll(transform_tab), "Transformations")

        self.material_editor = MaterialEditor(controller)
        self.tabs.addTab(self._scroll(self.material_editor), "Matériau")

        controller.session_changed.connect(self.refresh)
        controller.selection_changed.connect(self.refresh)
        controller.scene_changed.connect(lambda _k: self.refresh())
        self.refresh()

    @staticmethod
    def _scroll(widget: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(widget)
        return area

    def active(self) -> SceneNode | None:
        session = self.controller.session
        return session.scene.get(session.selection.active) if session else None

    def refresh(self) -> None:
        session, node = self.controller.session, self.active()
        self._updating = True
        for widget in (
            self.name,
            self.visible,
            self.locked,
            self.position,
            self.rotation,
            self.scale,
        ):
            widget.setEnabled(node is not None)
        if node is None:
            self.title.setText("Aucune sélection" if session else "Aucun projet")
            self.kind_badge.setText("—")
            for widget in (
                self.path,
                self.geometry,
                self.dimensions,
                self.provenance,
                self.active_info,
                self.dims_transform,
            ):
                widget.setText("")
            self.name.clear()
        else:
            scene = session.scene
            self.title.setText(node.name)
            self.kind_badge.setText(node.kind.label)
            self.kind_icon.setPixmap(icons.pixmap(KIND_ICONS[node.kind], "#f97b91", 15))
            self.name.setText(node.name)
            self.visible.setChecked(node.visible)
            self.locked.setChecked(node.locked)
            self.path.setText(scene.path(node.id))
            triangles, vertices, meshes = session.stats([node.id])
            self.geometry.setText(
                f"{_fmt(triangles)} triangles · {_fmt(vertices)} sommets · {meshes} maillage(s)"
            )
            dims = session.dimensions([node.id])
            text = (
                "—"
                if dims is None
                else " × ".join(f"{v:.2f}".replace(".", ",") for v in dims) + " m (X × Y × Z)"
            )
            self.dimensions.setText(text)
            self.dims_transform.setText(f"Dimensions monde : {text}")
            self.provenance.setText(self._provenance(node))
            count = len(session.selection)
            locked = scene.effective_locked(node.id)
            self.active_info.setText(
                f"Élément actif : {node.name}"
                + (f" (+{count - 1} autre(s) sélectionné(s))" if count > 1 else "")
                + (" — verrouillé" if locked else "")
            )
            for field in (self.position, self.rotation, self.scale):
                field.set_fields_enabled(not locked)
            self.position.set_value(node.transform.translation)
            self.rotation.set_value(node.transform.rotation)
            self.scale.set_value(node.transform.scale)
        self._updating = False
        self.material_editor.refresh()

    def _provenance(self, node: SceneNode) -> str:
        session = self.controller.session
        asset_id = node.asset_id or next(
            (a.asset_id for a in session.scene.ancestors(node.id) if a.asset_id), None
        )
        asset = session.project.assets.get(asset_id) if asset_id else None
        if asset is None:
            return "Créé dans LeStitcheurFou Cars"
        lines = [
            f"{asset.original_name} ({asset.format.upper()}, {asset.size / 1024:.0f} Ko)",
            f"Importé le {_date(asset.imported_at)} — {asset.importer}",
            f"Copie : {asset.rel_path}",
        ]
        if asset.sha256:
            lines.append(f"SHA-256 : {asset.sha256[:16]}…")
        lines += asset.notes
        if asset_id in session.missing_assets:
            lines.append("⚠ Fichier manquant ou illisible")
        return "\n".join(lines)

    def _next_serial(self) -> None:
        self._serial = next(_serials)

    def _transform_changed(self, field_name: str, values: list[float]) -> None:
        node = self.active()
        if self._updating or node is None:
            return
        transform = node.transform.copy()
        if field_name == "scale" and self.uniform.isChecked():
            changed = [i for i in range(3) if abs(values[i] - transform.scale[i]) > 1e-9]
            if changed:
                values = [values[changed[0]]] * 3
                self.scale.set_value(values)
        setattr(transform, field_name, list(values))
        self.controller.apply_transforms(
            {node.id: transform}, ("panel", field_name, node.id, self._serial)
        )

    def _rename(self) -> None:
        node = self.active()
        if node is not None and not self._updating:
            self.controller.rename(node.id, self.name.text())

    def _apply_flag(self, name: str, value: bool) -> None:
        if self._updating or self.active() is None:
            return
        ids = self.controller.selected()
        if name == "visible":
            self.controller.set_visible(ids, value)
        else:
            self.controller.set_locked(ids, value)

    def _reset(self) -> None:
        node = self.active()
        if node is not None:
            self.controller.apply_transforms({node.id: Transform()})


# --- Panneau inférieur ----------------------------------------------------------


class BottomPanel(LSTabs):
    STAT_NAMES = (
        "Nœuds",
        "Maillages",
        "Triangles",
        "Sommets",
        "Matériaux",
        "Textures",
        "Sélection",
        "Image (ms)",
        "Caméra",
        "Affichage",
    )

    def __init__(
        self,
        controller: StudioController,
        viewport,
        parent: QWidget | None = None,  # type: ignore[no-untyped-def]
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.viewport = viewport
        stats = QWidget()
        grid = QGridLayout(stats)
        grid.setContentsMargins(14, 10, 14, 10)
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(6)
        self.values: dict[str, QLabel] = {}
        for index, name in enumerate(self.STAT_NAMES):
            row, column = index % 5, (index // 5) * 2
            grid.addWidget(label(name, "faint"), row, column)
            value = label("—")
            value.setStyleSheet("color: #dfe5ee; font-weight: 600;")
            grid.addWidget(value, row, column + 1)
            self.values[name] = value
        grid.setColumnStretch(4, 1)
        self.addTab(stats, "Statistiques")

        progress_tab = QWidget()
        pl = QVBoxLayout(progress_tab)
        pl.setContentsMargins(14, 10, 14, 10)
        self.progress = LSProgress()
        self.progress.reset("Aucune tâche en cours")
        pl.addWidget(self.progress)
        pl.addWidget(separator())
        self.history = QListWidget()
        pl.addWidget(self.history, 1)
        self.addTab(progress_tab, "Progression")

        self.log_panel = LogPanel()
        self.addTab(self.log_panel, "Journal")

        controller.import_progress.connect(self._on_progress)
        controller.import_finished.connect(self._on_finished)
        for signal in (
            controller.session_changed,
            controller.selection_changed,
            controller.state_changed,
        ):
            signal.connect(self.refresh)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_view)
        self._timer.start(1000)
        self.refresh()

    def refresh(self) -> None:
        session = self.controller.session
        if session is None:
            for value in self.values.values():
                value.setText("—")
            return
        triangles, vertices, meshes = session.stats()
        materials = list(session.scene.materials.values())
        self.values["Nœuds"].setText(_fmt(len(session.scene)))
        self.values["Maillages"].setText(_fmt(meshes))
        self.values["Triangles"].setText(_fmt(triangles))
        self.values["Sommets"].setText(_fmt(vertices))
        self.values["Matériaux"].setText(_fmt(len(materials)))
        self.values["Textures"].setText(_fmt(sum(1 for m in materials if m.texture)))
        self.values["Sélection"].setText(_fmt(len(session.selection)))
        self._refresh_view()

    def _refresh_view(self) -> None:
        from lsfcars.ui.viewport import SHADING_LABELS, describe_view

        ms = self.viewport.renderer.last_frame_ms
        self.values["Image (ms)"].setText(f"{ms:.1f}".replace(".", ",") if ms else "—")
        self.values["Caméra"].setText(describe_view(self.viewport.camera))
        self.values["Affichage"].setText(SHADING_LABELS[self.viewport.shading])

    def _on_progress(self, value: float, text: str) -> None:
        self.progress.set_progress(value, text)

    def _on_finished(self, ok: bool, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        first_line = message.splitlines()[0] if message else ""
        self.history.insertItem(0, f"{stamp} — {'✓' if ok else '✗'} {first_line}")
        if not ok:
            self.progress.reset("Échec de l'import")
