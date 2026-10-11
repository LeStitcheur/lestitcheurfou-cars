"""Panneaux du Vehicle Import Studio : fichiers, hiérarchie, véhicule, métadonnées, textures."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path, PurePosixPath

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lsfcars.fivem import structure
from lsfcars.fivem.meta import MetaDocument
from lsfcars.fivem.resource import FORMAT_SUPPORT, ResourceAnalysis, ResourceFile, Status, TextureSummary
from lsfcars.fivem.ytd import TextureDecodeError, dds_bytes, decode, parse_ytd
from lsfcars.ui.design import fonts, icons
from lsfcars.ui.design import tokens as t
from lsfcars.ui.design.components import (
    LSBadge,
    LSButton,
    LSInput,
    LSSelect,
    LSTabs,
    label,
    separator,
    tooltip,
)

STATUS_TINTS = {
    Status.COMPATIBLE: "green",
    Status.PARTIAL: "amber",
    Status.MISSING: "amber",
    Status.ERROR: "red",
    Status.UNSUPPORTED: "neutral",
}
STATUS_COLORS = {
    Status.COMPATIBLE: t.SUCCESS,
    Status.PARTIAL: t.WARNING,
    Status.MISSING: t.WARNING,
    Status.ERROR: t.ERROR,
    Status.UNSUPPORTED: t.TEXT_MUTED,
}
LEVEL_COLORS = {"erreur": t.ERROR, "avertissement": t.WARNING, "info": t.TEXT_2}


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("o", "Ko", "Mo", "Go"):
        if value < 1024 or unit == "Go":
            return f"{value:.0f} {unit}" if unit == "o" else f"{value:.1f} {unit}".replace(".", ",")
        value /= 1024
    return f"{size} o"


def _scroll(widget: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(widget)
    return area


def _fmt(value: object) -> str:
    return f"{value:,}".replace(",", " ") if isinstance(value, int) else str(value)


class KeyValueGrid(QWidget):
    """Liste « libellé : valeur » sélectionnable."""

    def __init__(self) -> None:
        super().__init__()
        self.form = QFormLayout(self)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setHorizontalSpacing(14)
        self.form.setVerticalSpacing(7)
        self.values: dict[str, QLabel] = {}

    def set_rows(self, rows: list[tuple[str, str]]) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self.values.clear()
        for key, value in rows:
            value_label = label(value, wrap=True)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.form.addRow(label(key, "muted"), value_label)
            self.values[key] = value_label


def _add(parent: QTreeWidget | QTreeWidgetItem, item: QTreeWidgetItem) -> None:
    if isinstance(parent, QTreeWidget):
        parent.addTopLevelItem(item)
    else:
        parent.addChild(item)


# --- Explorateur de fichiers -----------------------------------------------------

FILE_FILTERS = [
    ("Tous les fichiers", "all"),
    ("Modèles (.yft, .ydr…)", "models"),
    ("Textures (.ytd)", "textures"),
    ("Métadonnées (.meta, .xml)", "meta"),
    ("Problèmes uniquement", "problems"),
]


class FileTree(QWidget):
    file_selected = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 6)
        layout.setSpacing(8)
        self.search = LSInput("Filtrer les fichiers…", "search")
        self.search.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search)
        self.filter = LSSelect(FILE_FILTERS)
        self.filter.currentIndexChanged.connect(self._apply_filter)
        layout.addWidget(self.filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Fichier", "Taille", "Statut"])
        self.tree.setUniformRowHeights(True)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemSelectionChanged.connect(self._selected)
        layout.addWidget(self.tree, 1)
        self.summary = label("", "faint", wrap=True)
        layout.addWidget(self.summary)
        self._items: dict[str, QTreeWidgetItem] = {}
        self._analysis: ResourceAnalysis | None = None

    def set_analysis(self, analysis: ResourceAnalysis | None) -> None:
        self._analysis = analysis
        self.tree.clear()
        self._items.clear()
        if analysis is None:
            self.summary.setText("")
            return
        folders: dict[str, QTreeWidgetItem] = {}
        for item in analysis.files:
            parts = PurePosixPath(item.path).parts
            parent: QTreeWidget | QTreeWidgetItem = self.tree
            for depth in range(len(parts) - 1):
                key = "/".join(parts[: depth + 1])
                if key not in folders:
                    folder = QTreeWidgetItem([parts[depth], "", ""])
                    archive = parts[depth].lower().endswith(".rpf")
                    folder.setIcon(0, icons.icon("package" if archive else "folder", t.TEXT_2, size=15))
                    _add(parent, folder)
                    folders[key] = folder
                parent = folders[key]
            node = QTreeWidgetItem([parts[-1], human_size(item.size), item.status.label])
            node.setData(0, Qt.ItemDataRole.UserRole, item.path)
            node.setForeground(2, QColor(STATUS_COLORS[item.status]))
            node.setToolTip(0, f"{item.path}\n{item.kind}\n{item.message}")
            node.setIcon(0, icons.icon(_file_icon(item), t.TEXT_2, size=15))
            _add(parent, node)
            self._items[item.path] = node
        self.tree.expandToDepth(3)
        counts = analysis.counts()
        self.summary.setText(
            f"{len(analysis.files)} fichiers · {human_size(analysis.total_size)} · "
            + " · ".join(f"{count} {status.label.lower()}" for status, count in counts.items() if count)
        )
        self._apply_filter()

    def _apply_filter(self) -> None:
        if self._analysis is None:
            return
        needle = self.search.text().strip().lower()
        mode = self.filter.currentData()
        for item in self._analysis.files:
            node = self._items.get(item.path)
            if node is not None:
                node.setHidden(not ((not needle or needle in item.path.lower()) and _matches(item, mode)))
        for index in range(self.tree.topLevelItemCount()):
            _hide_empty(self.tree.topLevelItem(index))

    def _selected(self) -> None:
        items = self.tree.selectedItems()
        path = items[0].data(0, Qt.ItemDataRole.UserRole) if items else None
        if path:
            self.file_selected.emit(path)

    def select_path(self, path: str) -> None:
        node = self._items.get(path)
        if node is not None:
            self.tree.setCurrentItem(node)
            self.tree.scrollToItem(node)


def _matches(item: ResourceFile, mode: str) -> bool:
    if mode == "models":
        return item.extension in (".yft", ".ydr", ".obj", ".glb", ".gltf", ".fbx")
    if mode == "textures":
        return item.extension in (".ytd", ".dds", ".png")
    if mode == "meta":
        return item.extension in (".meta", ".xml") or item.name.lower().endswith(".lua")
    if mode == "problems":
        return item.status in (Status.ERROR, Status.MISSING, Status.PARTIAL)
    return True


def _hide_empty(node: QTreeWidgetItem) -> bool:
    if node.data(0, Qt.ItemDataRole.UserRole):
        return not node.isHidden()
    any_visible = False
    for index in range(node.childCount()):
        any_visible |= _hide_empty(node.child(index))
    node.setHidden(not any_visible)
    return any_visible


def _file_icon(item: ResourceFile) -> str:
    return {
        ".yft": "car",
        ".ydr": "cuboid",
        ".ytd": "image",
        ".ybn": "shapes",
        ".meta": "scroll-text",
        ".xml": "scroll-text",
        ".lua": "file-box",
        ".dds": "image",
        ".png": "image",
    }.get(item.extension, "file-box")


# --- Hiérarchie du véhicule -------------------------------------------------------

HIERARCHY_MODES = [
    ("Par composant", "category"),
    ("Hiérarchie des os", "bones"),
    ("Points d'ancrage", "anchors"),
]


class HierarchyTree(QWidget):
    """Composants du modèle prévisualisé. Les cases à cocher règlent l'affichage (non destructif)."""

    nodes_selected = Signal(list)
    visibility_changed = Signal(set)

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 6)
        layout.setSpacing(8)
        self.mode = LSSelect(HIERARCHY_MODES)
        self.mode.currentIndexChanged.connect(self.rebuild)
        layout.addWidget(self.mode)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.itemSelectionChanged.connect(self._selected)
        self.tree.itemChanged.connect(self._changed)
        layout.addWidget(self.tree, 1)
        self.hint = label("Visualisez un modèle pour afficher ses composants.", "faint", wrap=True)
        layout.addWidget(self.hint)
        self.session = None
        self._updating = False

    def set_session(self, session) -> None:  # type: ignore[no-untyped-def]
        self.session = session
        self.rebuild()

    def set_mode(self, mode: str) -> None:
        self.mode.select_data(mode)

    def rebuild(self) -> None:
        self._updating = True
        self.tree.clear()
        session = self.session
        if session is None:
            self.hint.setText("Visualisez un modèle pour afficher ses composants.")
            self._updating = False
            return
        mode = self.mode.currentData()
        if mode == "category":
            self._build_categories(session)
        elif mode == "bones":
            self._build_bones(session)
        else:
            from lsfcars.scene.inspection import anchor_nodes

            anchors = anchor_nodes(session)
            for node in anchors:
                item = QTreeWidgetItem([node.name])
                item.setData(0, Qt.ItemDataRole.UserRole, node.id)
                item.setIcon(0, icons.icon("scan", t.TEXT_2, size=14))
                self.tree.addTopLevelItem(item)
            self.hint.setText(f"{len(anchors)} os sans géométrie (emplacements : sièges, feux, roues…).")
        self._updating = False

    def _build_categories(self, session) -> None:  # type: ignore[no-untyped-def]
        groups: dict[str, list] = defaultdict(list)
        for node in session.scene.mesh_nodes():
            groups[node.extra.get("category", structure.UNCLASSIFIED)].append(node)
        for key in [c.key for c in structure.CATEGORIES] + [structure.UNCLASSIFIED]:
            if key not in groups:
                continue
            parent = QTreeWidgetItem([f"{structure.label(key)}  ({len(groups[key])})"])
            parent.setFlags(parent.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
            parent.setCheckState(0, Qt.CheckState.Checked)
            parent.setFont(0, fonts.font(12, 600))
            self.tree.addTopLevelItem(parent)
            for node in sorted(groups[key], key=lambda n: n.name.lower()):
                child = QTreeWidgetItem([node.name])
                child.setData(0, Qt.ItemDataRole.UserRole, node.id)
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Checked)
                child.setIcon(0, icons.icon("cuboid", t.TEXT_2, size=14))
                parent.addChild(child)
        self.tree.expandAll()
        unclassified = len(groups.get(structure.UNCLASSIFIED, []))
        self.hint.setText(
            "Classement d'après les noms d'os GTA V. Décochez pour masquer (affichage seulement)."
            + (f" {unclassified} pièce(s) non classée(s) : nom non reconnu." if unclassified else "")
        )

    def _build_bones(self, session) -> None:  # type: ignore[no-untyped-def]
        items: dict[str, QTreeWidgetItem] = {}
        for node in session.scene.walk():
            if node.kind.value == "mesh":
                continue
            role = node.extra.get("gta", {}).get("role")
            item = QTreeWidgetItem([node.name])
            item.setData(0, Qt.ItemDataRole.UserRole, node.id)
            item.setIcon(0, icons.icon("move-3d" if role == "bone" else "layers", t.TEXT_2, size=14))
            parent = items.get(node.parent_id) if node.parent_id else None
            _add(parent if parent is not None else self.tree, item)
            items[node.id] = item
        self.tree.expandToDepth(2)
        self.hint.setText(
            "Os du squelette d'origine, pivots conservés. Affichage 3D des os : non implémenté "
            "(la sélection d'un os affiche son pivot dans le panneau Véhicule)."
        )

    def _selected(self) -> None:
        if self._updating:
            return
        ids = [i.data(0, Qt.ItemDataRole.UserRole) for i in self.tree.selectedItems()]
        self.nodes_selected.emit([i for i in ids if i])

    def _changed(self, _item: QTreeWidgetItem, _column: int) -> None:
        if not self._updating and self.mode.currentData() == "category":
            self.visibility_changed.emit(self.checked_ids())

    def checked_ids(self) -> set[str]:
        result: set[str] = set()
        for index in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(index)
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                if child.checkState(0) == Qt.CheckState.Checked:
                    result.add(child.data(0, Qt.ItemDataRole.UserRole))
        return result

    def set_all_checked(self) -> None:
        self._updating = True
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(0, Qt.CheckState.Checked)
        self._updating = False

    def select_ids(self, ids: list[str]) -> None:
        self._updating = True
        self.tree.clearSelection()
        wanted = set(ids)
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            if item.data(0, Qt.ItemDataRole.UserRole) in wanted:
                item.setSelected(True)
                self.tree.scrollToItem(item)
            stack.extend(item.child(i) for i in range(item.childCount()))
        self._updating = False


# --- Fiche véhicule ---------------------------------------------------------------


class VehiclePanel(QWidget):
    preview_requested = Signal(str, bool)  # nom du modèle, variante _hi
    import_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        head = QHBoxLayout()
        self.title = label("Aucune ressource", "h2")
        self.status = LSBadge("—")
        head.addWidget(self.title, 1)
        head.addWidget(self.status)
        layout.addLayout(head)
        self.source = label("", "subtitle", wrap=True)
        layout.addWidget(self.source)
        layout.addWidget(separator())
        layout.addWidget(label("Modèle", "h3"))
        self.models = LSSelect()
        self.models.currentIndexChanged.connect(self._model_changed)
        layout.addWidget(self.models)
        actions = QHBoxLayout()
        self.preview = LSButton("Visualiser", "secondary", "eye")
        self.preview.clicked.connect(lambda: self._preview(False))
        self.preview_hi = LSButton("Version _hi", "ghost", "eye")
        self.preview_hi.clicked.connect(lambda: self._preview(True))
        tooltip(self.preview_hi, "Visualiser la variante haute définition (_hi)")
        actions.addWidget(self.preview)
        actions.addWidget(self.preview_hi)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.import_button = LSButton("Importer dans le projet", "primary", "import")
        self.import_button.clicked.connect(self.import_requested)
        tooltip(self.import_button, "Copie le modèle, ses textures et ses métadonnées dans le projet ouvert")
        layout.addWidget(self.import_button)
        self.info = KeyValueGrid()
        layout.addWidget(self.info)
        self.warnings = label("", "warning", wrap=True)
        layout.addWidget(self.warnings)
        layout.addWidget(separator())
        layout.addWidget(label("Sélection", "h3"))
        self.selection = KeyValueGrid()
        layout.addWidget(self.selection)
        layout.addStretch(1)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(_scroll(content))
        self.analysis: ResourceAnalysis | None = None
        self.set_analysis(None)

    def set_analysis(self, analysis: ResourceAnalysis | None) -> None:
        self.analysis = analysis
        self.models.blockSignals(True)
        self.models.clear()
        if analysis is None:
            self.title.setText("Aucune ressource")
            self.status.setText("—")
            self.status.set_tint("neutral")
            self.source.setText("Ouvrez un dossier, un ZIP, une archive RPF ou des fichiers.")
        else:
            self.title.setText(analysis.name)
            overall = analysis.overall
            self.status.setText(overall.label)
            self.status.set_tint(STATUS_TINTS[overall])
            self.source.setText(f"{analysis.source_kind.capitalize()} : {analysis.source}")
            for model in analysis.models:
                prefix = "Véhicule" if model.is_vehicle else "Modèle"
                self.models.addItem(f"{prefix} · {model.name}  ({model.status.label.lower()})", model.name)
        self.models.blockSignals(False)
        self._model_changed()
        self.show_selection([])

    def current_model(self):  # type: ignore[no-untyped-def]
        name = self.models.currentData()
        return self.analysis.model(name) if self.analysis is not None and name else None

    def select_model(self, name: str) -> None:
        self.models.select_data(name)

    def _preview(self, high: bool) -> None:
        model = self.current_model()
        if model is not None:
            self.preview_requested.emit(model.name, high)

    def _model_changed(self) -> None:
        model = self.current_model()
        usable = (
            model is not None
            and model.yft is not None
            and model.yft.status in (Status.COMPATIBLE, Status.MISSING)
        )
        self.preview.setEnabled(usable)
        self.preview_hi.setEnabled(
            usable and model.yft_hi is not None and model.yft_hi.status is Status.COMPATIBLE
        )
        self.import_button.setEnabled(usable)
        if model is None:
            self.info.set_rows([])
            self.warnings.setText("")
            return
        details = model.yft.details if model.yft else {}
        rows = [
            ("Déclaré dans vehicles.meta", "oui" if model.is_vehicle else "non"),
            ("Statut", model.status.label + (f" — {model.yft.message}" if model.yft else "")),
            ("Variante haute définition", model.yft_hi.name if model.yft_hi else "absente"),
            ("Textures", ", ".join(y.name for y in model.ytds) or "aucun .ytd associé"),
            ("Triangles", _fmt(details.get("triangles", 0))),
            ("Os", _fmt(details.get("bones", 0))),
            ("Niveaux de détail", ", ".join(details.get("lods", [])) or "—"),
            ("Shaders", _fmt(len(details.get("shaders", [])))),
        ]
        for key in ("gameName", "vehicleMakeName", "handlingId", "type", "vehicleClass", "layout"):
            if model.meta.get(key):
                rows.append((key, model.meta[key]))
        self.info.set_rows(rows)
        warnings = list(details.get("warnings", []))
        missing = details.get("missing_textures", [])
        if missing:
            warnings.append(
                "Textures manquantes : " + ", ".join(missing[:10]) + (" …" if len(missing) > 10 else "")
            )
        self.warnings.setText("\n".join(warnings))

    def show_selection(self, rows: list[tuple[str, str]]) -> None:
        self.selection.set_rows(rows or [("—", "Aucune pièce sélectionnée")])


# --- Fiche fichier ----------------------------------------------------------------


class FileInfoPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        head = QHBoxLayout()
        self.title = label("Sélectionnez un fichier", "h3")
        self.title.setWordWrap(True)
        self.status = LSBadge("—")
        head.addWidget(self.title, 1)
        head.addWidget(self.status)
        layout.addLayout(head)
        self.message = label("", "subtitle", wrap=True)
        layout.addWidget(self.message)
        self.preview = QLabel()
        self.preview.setObjectName("LSTexturePreview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedHeight(200)
        self.preview.hide()
        layout.addWidget(self.preview)
        self.info = KeyValueGrid()
        layout.addWidget(self.info)
        layout.addStretch(1)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(_scroll(content))

    def show_file(self, item: ResourceFile | None) -> None:
        if item is None:
            self.title.setText("Sélectionnez un fichier")
            self.status.setText("—")
            self.status.set_tint("neutral")
            self.message.setText("")
            self.info.set_rows([])
            self.preview.hide()
            return
        self.title.setText(item.name)
        self.status.setText(item.status.label)
        self.status.set_tint(STATUS_TINTS[item.status])
        self.message.setText(item.message)
        support = FORMAT_SUPPORT.get(item.extension)
        rows = [
            ("Chemin", item.path),
            ("Type", item.kind or "—"),
            ("Taille", human_size(item.size)),
            ("Provenance", {"rpf": "archive RPF", "zip": "archive ZIP"}.get(item.origin, "dossier")),
            ("Prise en charge", support[1] if support else "Non exploité par le studio"),
        ]
        details = item.details
        for key, title in (
            ("model_name", "Nom interne"),
            ("triangles", "Triangles"),
            ("vertices", "Sommets"),
            ("bones", "Os"),
            ("children", "Enfants physiques (roues…)"),
        ):
            if key in details:
                rows.append((title, _fmt(details[key])))
        if details.get("lods"):
            rows.append(("Niveaux de détail", ", ".join(details["lods"])))
        if details.get("shaders"):
            rows.append(("Shaders", ", ".join(sorted(set(details["shaders"])))))
        if details.get("textures"):
            rows.append(("Textures", f"{len(details['textures'])} : " + ", ".join(details["textures"][:20])))
        if details.get("texture_refs"):
            rows.append(("Textures référencées", ", ".join(details["texture_refs"][:24])))
        if details.get("missing_textures"):
            rows.append(("Textures absentes", ", ".join(details["missing_textures"])))
        if details.get("data_files"):
            rows.append(("data_file", "\n".join(f"{k} → {p}" for k, p in details["data_files"])))
        for warning in details.get("warnings", []):
            rows.append(("Avertissement", warning))
        self.info.set_rows(rows)
        preview = details.get("preview_png")
        if preview:
            pixmap = QPixmap()
            pixmap.loadFromData(preview)
            self.preview.setPixmap(
                pixmap.scaled(
                    QSize(260, 190),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.preview.show()
        else:
            self.preview.hide()


# --- Métadonnées ------------------------------------------------------------------


class MetadataPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self.documents = LSSelect()
        self.documents.currentIndexChanged.connect(self._show)
        layout.addWidget(self.documents)
        self.search = LSInput("Rechercher (balise, valeur, attribut)…", "search")
        self.search.textChanged.connect(self._search)
        layout.addWidget(self.search)
        self.tabs = LSTabs()
        self.entries = QTableWidget(0, 3)
        self.entries.setHorizontalHeaderLabels(["Type", "Nom", "Champs"])
        self.entries.horizontalHeader().setStretchLastSection(True)
        self.entries.verticalHeader().hide()
        self.entries.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Élément", "Valeur"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.issues = QListWidget()
        self.raw = QPlainTextEdit()
        self.raw.setObjectName("LSCode")
        self.raw.setReadOnly(True)
        self.raw.setFont(fonts.mono_font(12))
        self.results = QListWidget()
        self.tabs.addTab(self.entries, "Entrées")
        self.tabs.addTab(self.tree, "Structure XML")
        self.tabs.addTab(self.issues, "Vérifications")
        self.tabs.addTab(self.raw, "Texte d'origine")
        self.tabs.addTab(self.results, "Recherche")
        layout.addWidget(self.tabs, 1)
        layout.addWidget(
            label("Lecture seule : les fichiers d'origine ne sont jamais modifiés.", "faint", wrap=True)
        )
        self.docs: list[MetaDocument] = []

    def set_analysis(self, analysis: ResourceAnalysis | None) -> None:
        self.docs = list(analysis.metadata) if analysis else []
        self.documents.blockSignals(True)
        self.documents.clear()
        for document in self.docs:
            self.documents.addItem(
                f"{PurePosixPath(document.path).name} — {document.kind_label}", document.path
            )
        self.documents.blockSignals(False)
        self._show()

    def select_path(self, path: str) -> None:
        index = self.documents.findData(path)
        if index >= 0:
            self.documents.setCurrentIndex(index)

    def current(self) -> MetaDocument | None:
        index = self.documents.currentIndex()
        return self.docs[index] if 0 <= index < len(self.docs) else None

    def _show(self) -> None:
        document = self.current()
        self.entries.setRowCount(0)
        self.tree.clear()
        self.issues.clear()
        self.raw.setPlainText(document.text if document else "")
        if document is None:
            return
        for entry in document.entries:
            row = self.entries.rowCount()
            self.entries.insertRow(row)
            fields = ", ".join(f"{k}={v}" for k, v in entry.fields.items() if v)
            for column, value in enumerate((entry.kind, entry.name, fields)):
                self.entries.setItem(row, column, QTableWidgetItem(value))
        self.entries.resizeColumnsToContents()
        if document.root is not None:
            self._fill(self.tree, document.root, 0)
            self.tree.expandToDepth(1)
        for issue in document.issues:
            item = QListWidgetItem(f"{issue.level.capitalize()} — {issue.message}")
            item.setForeground(QColor(LEVEL_COLORS.get(issue.level, t.TEXT_2)))
            self.issues.addItem(item)
        if not document.issues:
            self.issues.addItem("Aucun problème détecté.")
        self._search()

    def _fill(self, parent: QTreeWidget | QTreeWidgetItem, element, depth: int) -> None:  # type: ignore[no-untyped-def]
        if depth > 40:
            return
        text = (element.text or "").strip()
        attributes = " ".join(f'{k}="{v}"' for k, v in element.attrib.items())
        item = QTreeWidgetItem([element.tag, text or attributes])
        _add(parent, item)
        for index, child in enumerate(element):
            if index >= 2000:
                item.addChild(QTreeWidgetItem(["…", "affichage limité à 2000 éléments"]))
                break
            self._fill(item, child, depth + 1)

    def _search(self) -> None:
        self.results.clear()
        document = self.current()
        needle = self.search.text().strip()
        if document is None or not needle:
            return
        found = document.search(needle)
        for path, value in found:
            self.results.addItem(f"{path}  =  {value}")
        if not found:
            self.results.addItem("Aucun résultat.")
        self.tabs.setCurrentWidget(self.results)


# --- Inspecteur de textures --------------------------------------------------------


class TextureInspector(QWidget):
    exported = Signal(str)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(_scroll(content))
        self.search = LSInput("Filtrer les textures…", "search")
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        self.list = QListWidget()
        self.list.setIconSize(QSize(40, 40))
        self.list.setFixedHeight(170)
        self.list.currentRowChanged.connect(self._show)
        layout.addWidget(self.list)
        self.preview = QLabel("Aucune texture sélectionnée")
        self.preview.setObjectName("LSTexturePreview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedHeight(190)
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)
        self.info = KeyValueGrid()
        layout.addWidget(self.info)
        actions = QHBoxLayout()
        self.export_png = LSButton("PNG", "secondary", "download", True)
        self.export_png.clicked.connect(lambda: self.export("png"))
        tooltip(self.export_png, "Exporter une copie PNG (niveau 0 décodé)")
        self.export_dds = LSButton("DDS", "secondary", "download", True)
        self.export_dds.clicked.connect(lambda: self.export("dds"))
        tooltip(self.export_dds, "Exporter une copie DDS (format d'origine, tous les niveaux)")
        self.livery = LSButton("Livrées", "ghost", "paint-bucket", True)
        self.livery.clicked.connect(lambda: self.export("livery"))
        tooltip(self.livery, "Copie la texture en PNG dans « assets/livrees » du projet ouvert")
        for button in (self.export_png, self.export_dds, self.livery):
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.missing = label("", "warning", wrap=True)
        layout.addWidget(self.missing)
        layout.addStretch(1)
        self.analysis: ResourceAnalysis | None = None
        self.summaries: list[TextureSummary] = []
        self.project_dir: Path | None = None
        self._update_buttons()

    def set_analysis(self, analysis: ResourceAnalysis | None) -> None:
        self.analysis = analysis
        self.summaries = list(analysis.textures) if analysis else []
        self.list.clear()
        for summary in self.summaries:
            item = QListWidgetItem(f"{summary.name}\n{summary.width}×{summary.height} · {summary.format}")
            if summary.preview_png:
                pixmap = QPixmap()
                pixmap.loadFromData(summary.preview_png)
                item.setIcon(QIcon(pixmap))
            else:
                item.setIcon(icons.icon("triangle-alert", t.WARNING, size=20))
            self.list.addItem(item)
        models = analysis.models if analysis else []
        missing = sorted(
            {m for model in models if model.yft for m in model.yft.details.get("missing_textures", [])}
        )
        self.missing.setText(
            f"{len(missing)} texture(s) référencée(s) absente(s) de la ressource : "
            + ", ".join(missing[:14])
            + (" …" if len(missing) > 14 else "")
            if missing
            else ""
        )
        if self.summaries:
            self.list.setCurrentRow(0)
        else:
            self._show(-1)

    def _filter(self) -> None:
        needle = self.search.text().strip().lower()
        for row, summary in enumerate(self.summaries):
            self.list.item(row).setHidden(bool(needle) and needle not in summary.name.lower())

    def current(self) -> TextureSummary | None:
        row = self.list.currentRow()
        return self.summaries[row] if 0 <= row < len(self.summaries) else None

    def _users(self, name: str) -> list[str]:
        models = self.analysis.models if self.analysis else []
        return [
            m.name
            for m in models
            if m.yft and name.lower() in {r.lower() for r in m.yft.details.get("texture_refs", [])}
        ]

    def _show(self, _row: int) -> None:
        summary = self.current()
        self._update_buttons()
        if summary is None:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("Aucune texture sélectionnée")
            self.info.set_rows([])
            return
        if summary.decoded and summary.preview_png:
            pixmap = QPixmap()
            pixmap.loadFromData(summary.preview_png)
            self.preview.setPixmap(
                pixmap.scaled(
                    QSize(320, 180),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            self.preview.setPixmap(QPixmap())
            self.preview.setText(f"Aperçu indisponible :\n{summary.reason}")
        if summary.alpha:
            transparency = "utilisée"
        else:
            transparency = "non utilisée" if summary.decoded else "inconnue (non décodée)"
        self.info.set_rows(
            [
                ("Nom", summary.name),
                ("Dimensions", f"{summary.width} × {summary.height}"),
                ("Format", summary.format),
                ("Niveaux (mipmaps)", str(summary.levels)),
                ("Transparence", transparency),
                ("Mémoire estimée", human_size(summary.memory)),
                ("Fichier", summary.source),
                ("Utilisée par", ", ".join(self._users(summary.name)) or "aucun modèle de la ressource"),
                ("Décodage", "réussi" if summary.decoded else f"impossible — {summary.reason}"),
            ]
        )

    def _update_buttons(self) -> None:
        summary = self.current()
        decoded = summary is not None and summary.decoded
        self.export_png.setEnabled(decoded)
        self.export_dds.setEnabled(decoded)
        self.livery.setEnabled(decoded and self.project_dir is not None)

    def set_project_dir(self, folder: Path | None) -> None:
        self.project_dir = folder
        self._update_buttons()

    def _texture(self, summary: TextureSummary):  # type: ignore[no-untyped-def]
        item = self.analysis.find(summary.source) if self.analysis else None
        if item is None:
            raise TextureDecodeError("Dictionnaire d'origine introuvable.")
        for texture in parse_ytd(item.read()):
            if texture.name == summary.name:
                return texture
        raise TextureDecodeError("Texture introuvable dans son dictionnaire.")

    def export(self, kind: str, path: str | None = None) -> str | None:
        """Exporte une copie (PNG, DDS) ou prépare la texture pour l'atelier de livrées."""
        summary = self.current()
        if summary is None:
            return None
        try:
            texture = self._texture(summary)
            if kind == "livery":
                if self.project_dir is None:
                    raise TextureDecodeError("Aucun projet ouvert.")
                folder = self.project_dir / "assets" / "livrees"
                folder.mkdir(parents=True, exist_ok=True)
                target = folder / f"{summary.name}.png"
                decode(texture).save(target, "PNG")
                self.exported.emit(str(target))
                return str(target)
            suffix = ".png" if kind == "png" else ".dds"
            if path is None:
                path, _ = QFileDialog.getSaveFileName(
                    self, "Exporter une copie", f"{summary.name}{suffix}", f"*{suffix}"
                )
            if not path:
                return None
            if kind == "png":
                decode(texture).save(path, "PNG")
            else:
                Path(path).write_bytes(dds_bytes(texture, all_levels=True))
            self.exported.emit(path)
            return path
        except Exception as exc:  # noqa: BLE001 (décodage / écriture : message lisible)
            self.failed.emit(str(exc))
            return None


# --- Formats pris en charge -------------------------------------------------------


def format_rows() -> list[tuple[str, str, str, str, str]]:
    """(extension, nom, statut, teinte, détail) : ce qui est réellement fait de chaque format."""
    from lsfcars.importers.fbx_blender import blender_version

    states = {
        ".ydr": ("Expérimental", "amber"),
        ".ybn": ("Partiel", "amber"),
        ".lua": ("Partiel", "amber"),
        ".fxap": ("Refusé", "red"),
        ".dds": ("Aperçu", "blue"),
        ".png": ("Aperçu", "blue"),
    }
    rows = []
    for ext, (name, detail) in FORMAT_SUPPORT.items():
        status, tint = states.get(ext, ("Disponible", "green"))
        if ext == ".fbx" and blender_version() is None:
            status, tint, detail = (
                "Blender requis",
                "amber",
                "Blender introuvable : installez-le pour convertir les FBX",
            )
        rows.append((ext, name, status, tint, detail))
    rows.append(
        (".awc / .rel", "Audio GTA V", "Non pris en charge", "neutral", "Reconnu, ignoré par le studio")
    )
    rows.append((".rpf chiffrée", "Archive officielle (AES / NG)", "Refusé", "red", "Jamais déchiffrée"))
    return rows


class FormatsPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        layout.addWidget(
            label("Reconnaître un format ne signifie pas pouvoir le convertir.", "subtitle", wrap=True)
        )
        self.status_badges: dict[str, LSBadge] = {}
        for ext, name, status, tint, detail in format_rows():
            row = QHBoxLayout()
            ext_label = label(ext.upper().lstrip("."), "h3")
            ext_label.setFixedWidth(84)
            row.addWidget(ext_label)
            texts = QVBoxLayout()
            texts.setSpacing(1)
            texts.addWidget(label(name))
            texts.addWidget(label(detail, "faint", wrap=True))
            row.addLayout(texts, 1)
            badge = LSBadge(status, tint)
            self.status_badges[ext] = badge
            row.addWidget(badge)
            layout.addLayout(row)
            layout.addWidget(separator())
        layout.addStretch(1)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(_scroll(content))


# --- Diagnostics et statistiques --------------------------------------------------


class DiagnosticsList(QTreeWidget):
    file_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setHeaderLabels(["Niveau", "Message"])
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.setRootIsDecorated(False)
        self.itemDoubleClicked.connect(self._open)

    def set_analysis(self, analysis: ResourceAnalysis | None) -> None:
        self.clear()
        if analysis is None:
            return
        rows: list[tuple[str, str, str]] = [(level, message, "") for level, message in analysis.issues]
        for item in analysis.files:
            if item.status in (Status.ERROR, Status.MISSING, Status.PARTIAL):
                level = "erreur" if item.status is Status.ERROR else "avertissement"
                rows.append((level, f"{item.path} — {item.status.label} : {item.message}", item.path))
        order = {"erreur": 0, "avertissement": 1, "info": 2}
        for level, message, path in sorted(rows, key=lambda r: order.get(r[0], 3)):
            node = QTreeWidgetItem([level.capitalize(), message])
            node.setForeground(0, QColor(LEVEL_COLORS.get(level, t.TEXT_2)))
            node.setData(0, Qt.ItemDataRole.UserRole, path)
            node.setToolTip(1, message)
            self.addTopLevelItem(node)
        if not rows:
            self.addTopLevelItem(QTreeWidgetItem(["Info", "Aucun problème détecté."]))

    def _open(self, item: QTreeWidgetItem) -> None:
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path:
            self.file_requested.emit(path)


class StatsTable(QTableWidget):
    node_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__(0, 5)
        self.setHorizontalHeaderLabels(["Pièce", "Catégorie", "Triangles", "Sommets", "Matériau"])
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.verticalHeader().hide()
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.cellClicked.connect(self._clicked)

    def _clicked(self, row: int, _column: int) -> None:
        cell = self.item(row, 0)
        if cell is not None:
            self.node_requested.emit(cell.data(Qt.ItemDataRole.UserRole))

    def set_session(self, session) -> None:  # type: ignore[no-untyped-def]
        from lsfcars.scene.inspection import part_statistics

        self.setRowCount(0)
        if session is None:
            return
        for stats in part_statistics(session):
            row = self.rowCount()
            self.insertRow(row)
            values = (
                stats.name,
                structure.label(stats.category),
                stats.triangles,
                stats.vertices,
                stats.material,
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(_fmt(value))
                if column == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, stats.node_id)
                self.setItem(row, column, cell)
