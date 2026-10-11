"""Component Library (panneau) et Replace Component (dialogue de remplacement)."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from lsfcars.core.logging_setup import get_logger
from lsfcars.editor import vehicle
from lsfcars.editor.library import CATEGORIES, ComponentLibrary, LibraryComponent, LibraryError
from lsfcars.editor.operations import ReplaceOptions
from lsfcars.importers import ModelLoadError
from lsfcars.scene import mathutils
from lsfcars.scene.editmesh import EditError
from lsfcars.scene.mesh import MeshData
from lsfcars.ui.design import tokens as t
from lsfcars.ui.design.components import LSButton, LSInput, LSSelect, eyebrow, label, tooltip

log = get_logger(__name__)
ID_ROLE = Qt.ItemDataRole.UserRole
PLACEMENT = {
    "spoilers": "rear",
    "pare_chocs": "front",
    "calandres": "front",
    "feux": "rear",
    "phares": "front",
    "urgence": "roof",
    "accessoires": "roof",
    "sieges": "interior",
    "tableaux_de_bord": "interior",
}


def render_thumbnail(mesh: MeshData, size: int = 96) -> QPixmap:
    """Aperçu léger sans OpenGL : projection isométrique et ombrage plat (algorithme du peintre)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(t.PANEL))
    if not mesh.triangle_count:
        return pixmap
    rotation = mathutils.rotation_euler_xyz((-28.0, 38.0, 0.0))[:3, :3]
    points = mesh.positions.astype(np.float64) @ rotation.T
    tris = points[mesh.indices]
    if len(tris) > 6000:  # aperçu : sous-échantillonnage des très gros maillages
        tris = tris[:: len(tris) // 6000 + 1]
    lo, hi = points.min(axis=0), points.max(axis=0)
    scale = (size * 0.82) / max(float(np.max(hi[:2] - lo[:2])), 1e-6)
    center = (lo + hi) / 2
    normals = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    normals = normals / np.where(lengths[:, None] > 1e-12, lengths[:, None], 1.0)
    light = np.array([0.35, 0.7, 0.62]) / np.linalg.norm([0.35, 0.7, 0.62])
    shade = 0.35 + 0.65 * np.abs(normals @ light)
    base = np.asarray(mesh.color[:3])
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    for index in np.argsort(tris[:, :, 2].mean(axis=1)):  # du plus loin au plus proche
        polygon = QPolygonF(
            [
                QPointF(size / 2 + (p[0] - center[0]) * scale, size / 2 - (p[1] - center[1]) * scale)
                for p in tris[index]
            ]
        )
        r, g, b = np.clip(base * shade[index], 0.0, 1.0)
        painter.setBrush(QColor.fromRgbF(float(r), float(g), float(b)))
        painter.drawPolygon(polygon)
    painter.end()
    return pixmap


class LibraryPanel(QWidget):
    """Bibliothèque locale : recherche, filtres, aperçu, ajout au véhicule, presets."""

    replace_requested = Signal(str)  # identifiant du composant de remplacement

    def __init__(
        self, controller, library: ComponentLibrary | None = None, parent: QWidget | None = None
    ) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.controller = controller
        self._library = library
        self._thumbs: dict[str, QIcon] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        self.search = LSInput("Rechercher un composant…", "search")
        self.search.textChanged.connect(self.refresh)
        self.category = LSSelect([("Toutes les catégories", "")] + [(v, k) for k, v in CATEGORIES.items()])
        self.category.currentIndexChanged.connect(self.refresh)
        layout.addWidget(self.search)
        layout.addWidget(self.category)
        self.list = QListWidget()
        self.list.setIconSize(QSize(56, 56))
        self.list.currentItemChanged.connect(lambda *_: self._show())
        self.list.itemDoubleClicked.connect(lambda _i: self.add_selected())
        layout.addWidget(self.list, 3)
        self.details = label("", "muted", wrap=True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.details)
        row = QHBoxLayout()
        self.add_button = LSButton("Ajouter au véhicule", "primary", "plus", True)
        self.add_button.clicked.connect(self.add_selected)
        self.replace_button = LSButton("Remplacer…", "secondary", "refresh-cw", True)
        tooltip(self.replace_button, "Remplacer la pièce sélectionnée par ce composant")
        self.replace_button.clicked.connect(self._replace)
        row.addWidget(self.add_button, 1)
        row.addWidget(self.replace_button)
        layout.addLayout(row)
        manage = QHBoxLayout()
        for text, icon, slot, tip in (
            ("Importer", "import", self.import_component, "Importer un modèle 3D comme composant"),
            ("Preset", "save", self.save_selection, "Enregistrer la sélection comme preset de bibliothèque"),
            ("", "copy-plus", self.duplicate_selected, "Dupliquer le composant"),
            (
                "",
                "trash-2",
                self.delete_selected,
                "Retirer de la bibliothèque (les projets gardent leur copie)",
            ),
        ):
            button = LSButton(text, "ghost", icon, True)
            tooltip(button, tip)
            button.clicked.connect(slot)
            manage.addWidget(button)
        manage.addStretch(1)
        layout.addLayout(manage)
        layout.addWidget(
            label("Composants de départ générés localement ; aucun asset propriétaire.", "faint", wrap=True)
        )
        controller.session_changed.connect(self._sync_buttons)
        controller.selection_changed.connect(self._sync_buttons)

    @property
    def library(self) -> ComponentLibrary:
        if self._library is None:
            self._library = ComponentLibrary()
            try:
                self._library.ensure_builtins()
            except (OSError, LibraryError) as exc:
                log.warning("Composants de départ non générés : %s", exc)
        return self._library

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        super().showEvent(event)
        if self.list.count() == 0:
            self.refresh()

    def refresh(self) -> None:
        current = self.current_id()
        self.list.clear()
        for component in self.library.search(self.search.text(), self.category.currentData() or None):
            item = QListWidgetItem(self._icon(component), f"{component.name}\n{component.category_label}")
            item.setData(ID_ROLE, component.id)
            item.setToolTip(component.description or component.name)
            self.list.addItem(item)
            if component.id == current:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._show()

    def _icon(self, component: LibraryComponent) -> QIcon:
        if component.id not in self._thumbs:
            try:
                self._thumbs[component.id] = QIcon(
                    render_thumbnail(self.library.preview_mesh(component), 112)
                )
            except (LibraryError, OSError, ValueError) as exc:
                log.warning("Aperçu impossible pour %s : %s", component.name, exc)
                self._thumbs[component.id] = QIcon()
        return self._thumbs[component.id]

    def current_id(self) -> str | None:
        item = self.list.currentItem()
        return item.data(ID_ROLE) if item else None

    def current(self) -> LibraryComponent | None:
        component_id = self.current_id()
        return self.library.get(component_id) if component_id else None

    def _show(self) -> None:
        component = self.current()
        if component is None:
            self.details.setText("Aucun composant.")
        else:
            dims = " × ".join(f"{v:.2f}".replace(".", ",") for v in component.dimensions)
            attach = ", ".join(a.get("name", "") for a in component.attach_points) or "aucun"
            triangles = f"{component.triangles:,}".replace(",", " ")
            self.details.setText(
                f"<b>{component.name}</b> — {component.category_label}<br>"
                f"Dimensions : {dims} m · {triangles} triangles<br>"
                f"Points d'attache : {attach}<br>"
                f"Auteur : {component.author or '—'} · Licence : {component.license or 'non précisée'}<br>"
                f"Provenance : {component.provenance or '—'}<br>"
                f"Compatibilité : {component.compatibility or '—'}"
            )
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        ready = self.controller.session is not None and self.current() is not None
        self.add_button.setEnabled(ready)
        self.replace_button.setEnabled(ready and bool(self.controller.selected()))

    # --- Actions ---------------------------------------------------------------------
    def add_selected(self, parent_id: str | None = None) -> str | None:
        component, session, editor = self.current(), self.controller.session, self.controller.editor
        if component is None or session is None or editor is None:
            return None
        try:
            payload = self.library.payload(component, session.project)
        except LibraryError as exc:
            self.controller.notify.emit("Bibliothèque", str(exc), "warning")
            return None
        if parent_id is None:
            payload.snapshots[0]["transform"] = editor.placement_for(
                PLACEMENT.get(component.category, "center")
            ).to_dict()
        node_id = editor.insert_payload(payload, parent_id, None, f"Ajout de {component.name}")
        self.controller.notify.emit("Composant ajouté", component.name, "success")
        return node_id

    def _replace(self) -> None:
        component_id = self.current_id()
        if component_id:
            self.replace_requested.emit(component_id)

    def import_component(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Importer un composant", "", "Modèles 3D (*.glb *.gltf *.obj *.fbx *.stl *.ply *.yft *.ydr)"
        )
        if not path:
            return
        try:
            component = self.library.import_file(
                path, category=self.category.currentData() or "personnalises"
            )
        except (LibraryError, ModelLoadError, OSError) as exc:
            self.controller.notify.emit("Import de composant", str(exc), "warning")
            return
        self.refresh()
        self._select(component.id)
        self.controller.notify.emit("Composant importé", component.name, "success")

    def save_selection(self) -> None:
        session = self.controller.session
        active = session.selection.active if session else None
        if active is None:
            self.controller.notify.emit("Preset", "Sélectionnez la pièce à enregistrer.", "info")
            return
        name, ok = QInputDialog.getText(
            self, "Enregistrer comme preset", "Nom du composant :", text=session.scene.nodes[active].name
        )
        if not ok or not name.strip():
            return
        try:
            component = self.library.save_from_scene(
                session, active, name.strip(), self.category.currentData() or "personnalises"
            )
        except LibraryError as exc:
            self.controller.notify.emit("Preset", str(exc), "warning")
            return
        self.refresh()
        self._select(component.id)
        self.controller.notify.emit("Preset enregistré", component.name, "success")

    def duplicate_selected(self) -> None:
        component = self.current()
        if component is not None:
            copy = self.library.duplicate(component.id)
            self.refresh()
            self._select(copy.id)

    def delete_selected(self) -> None:
        component = self.current()
        if component is None:
            return
        answer = QMessageBox.question(
            self,
            "Retirer de la bibliothèque",
            f"Retirer « {component.name} » de la bibliothèque ?\n"
            "Les projets qui l'utilisent conservent leur copie.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.library.delete(component.id)
            self._thumbs.pop(component.id, None)
            self.refresh()

    def _select(self, component_id: str) -> None:
        for row in range(self.list.count()):
            if self.list.item(row).data(ID_ROLE) == component_id:
                self.list.setCurrentRow(row)
                return


class ReplaceDialog(QDialog):
    """Replace Component : choix, prévisualisation, vérifications, confirmation (réversible)."""

    OPTIONS = (
        (
            "keep_transform",
            "Conserver les transformations",
            "Position, rotation et échelle de l'ancienne pièce",
        ),
        ("align_pivot", "Aligner les pivots", "Centre de la nouvelle pièce sur celui de l'ancienne"),
        (
            "fit_dimensions",
            "Ajuster les dimensions",
            "Mise à l'échelle uniforme aux dimensions de l'ancienne",
        ),
        (
            "keep_materials",
            "Conserver les matériaux (si compatibles)",
            "Un seul matériau d'origine : réutilisé",
        ),
        ("keep_parent", "Conserver le parent", "La nouvelle pièce garde sa place dans la hiérarchie"),
        (
            "keep_anchors",
            "Conserver les points d'ancrage",
            "Les ancrages de l'ancienne pièce sont transférés",
        ),
        (
            "allow_bone_change",
            "Autoriser la suppression de l'os GTA V",
            "Désactivé : l'os d'origine est conservé",
        ),
    )

    def __init__(
        self,
        controller,
        library: ComponentLibrary,
        target_id: str,
        component_id: str | None = None,
        parent=None,
    ) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.controller = controller
        self.library = library
        self.target_id = target_id
        self.setWindowTitle("Remplacer un composant")
        self.setObjectName("LSModal")
        self.setMinimumSize(660, 560)
        session = controller.session
        target = session.scene.nodes[target_id]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        layout.addWidget(eyebrow("Replace Component"))
        layout.addWidget(label(f"Pièce à remplacer : {target.name}", "h3"))
        role = vehicle.ROLE_LABELS[vehicle.role(session.scene, target)]
        layout.addWidget(label(f"{role} · catégorie : {vehicle.category(session.scene, target)}", "muted"))
        body = QHBoxLayout()
        self.list = QListWidget()
        for component in library.components():
            item = QListWidgetItem(f"{component.name}\n{component.category_label}")
            item.setData(ID_ROLE, component.id)
            self.list.addItem(item)
            if component.id == component_id:
                self.list.setCurrentItem(item)
        self.list.currentItemChanged.connect(lambda *_: self._invalidate())
        body.addWidget(self.list, 1)
        options = QFormLayout()
        self.options: dict[str, QCheckBox] = {}
        defaults = ReplaceOptions()
        for key, text, tip in self.OPTIONS:
            box = QCheckBox(text)
            box.setChecked(getattr(defaults, key))
            tooltip(box, tip)
            box.toggled.connect(self._invalidate)
            options.addRow(box)
            self.options[key] = box
        side = QWidget()
        side.setLayout(options)
        body.addWidget(side, 1)
        layout.addLayout(body, 1)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setPlaceholderText(
            "« Prévisualiser » : dimensions, matériaux et ancrages sont vérifiés ici."
        )
        self.report.setMaximumHeight(150)
        layout.addWidget(self.report)
        actions = QHBoxLayout()
        actions.addStretch(1)
        self.preview_button = LSButton("Prévisualiser", "secondary", "eye")
        self.preview_button.clicked.connect(self.preview)
        cancel = LSButton("Annuler", "ghost")
        cancel.clicked.connect(self.reject)
        self.confirm_button = LSButton("Confirmer le remplacement", "primary", "check")
        self.confirm_button.clicked.connect(self.confirm)
        for button in (self.preview_button, cancel, self.confirm_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)

    def selected_options(self) -> ReplaceOptions:
        return ReplaceOptions(**{key: box.isChecked() for key, box in self.options.items()})

    def _invalidate(self) -> None:
        editor = self.controller.editor
        if editor is not None and editor.previewing:
            editor.cancel()
            self.controller.scene_changed.emit("structure")
        self.report.clear()

    def preview(self) -> bool:
        editor = self.controller.editor
        item = self.list.currentItem()
        if item is None:
            self.report.setPlainText("Choisissez un composant de remplacement.")
            return False
        try:
            payload = self.library.payload(
                self.library.get(item.data(ID_ROLE)), self.controller.session.project
            )
            command, report = editor.build_replacement(self.target_id, payload, self.selected_options())
        except (EditError, LibraryError) as exc:
            self.report.setPlainText(str(exc))
            return False
        editor.preview(command)
        self.controller.scene_changed.emit("structure")
        lines = []
        if report.target_size is not None and report.source_size is not None:

            def fmt(values) -> str:  # type: ignore[no-untyped-def]
                return " × ".join(f"{x:.2f}".replace(".", ",") for x in values)

            lines.append(
                f"Dimensions : ancienne {fmt(report.target_size)} m, nouvelle {fmt(report.source_size)} m"
            )
        if report.scale != 1.0:
            lines.append(f"Échelle appliquée : {report.scale:.3f}".replace(".", ","))
        lines.append(f"Matériaux : {report.materials}")
        lines.append(f"Points d'ancrage transférés : {report.anchors_moved}")
        lines += [f"Note : {n}" for n in report.notes]
        lines += [f"Attention : {w}" for w in report.warnings]
        lines.append("L'ancienne pièce reste disponible dans l'historique (Ctrl+Z).")
        self.report.setPlainText("\n".join(lines))
        return True

    def confirm(self) -> None:
        editor = self.controller.editor
        if not editor.previewing and not self.preview():
            return
        self.controller.fivem_risk([self.target_id], "replace")
        editor.confirm()
        self.accept()

    def reject(self) -> None:
        editor = self.controller.editor
        if editor is not None and editor.previewing:
            editor.cancel()
            self.controller.scene_changed.emit("structure")
        super().reject()
