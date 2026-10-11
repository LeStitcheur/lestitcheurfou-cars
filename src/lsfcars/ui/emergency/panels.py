"""Panneaux de l'Emergency Vehicle Studio.

Chaque panneau lit l'état via ``page.studio`` et applique ses modifications par les opérations
annulables d'``EmergencyStudio`` (``page.run`` transforme les erreurs prévues en notifications).
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QMimeData, QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lsfcars.emergency import adapters, model, sirens
from lsfcars.emergency.model import PatternFrame, SirenMode
from lsfcars.emergency.studio import INTERIOR_LABELS
from lsfcars.scene.transform import decompose
from lsfcars.ui.design import icons
from lsfcars.ui.design.components import LSBadge, LSInput, LSPropertyField, LSSelect, label, tooltip
from lsfcars.ui.editor.library_panel import render_thumbnail
from lsfcars.ui.editor.panels import Page, button, spin

ID_ROLE = Qt.ItemDataRole.UserRole
MIME = "application/x-lsf-equipment"
LEVEL_ICONS = {"error": "circle-x", "warning": "triangle-alert", "info": "info", "ok": "circle-check"}


def _issue_item(level: str, text: str) -> QListWidgetItem:
    return QListWidgetItem(icons.icon(LEVEL_ICONS.get(level, "info"), size=14), text)


# --- Service et variantes ----------------------------------------------------------------------


class ServicePanel(Page):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        create = self.section(
            "Nouvelle variante", "Le véhicule de base reste intact : chaque variante a ses équipements."
        )
        self.service = LSSelect([(f"{s.label} — {s.full_name}", s.key) for s in model.SERVICES])
        self.profile = LSSelect()
        self.name = LSInput("Nom (ex. SUV LSPD)")
        create.add(self.service)
        create.add(self.profile)
        create.add(self.name)
        create.row(button("Créer la variante", "plus", self.create, variant="primary"), stretch=True)
        variants = self.section("Variantes du projet", "Une seule variante visible à la fois.")
        self.list = QListWidget()
        self.list.setMinimumHeight(150)
        self.list.itemClicked.connect(self._activate)
        variants.add(self.list)
        variants.row(
            button("Dupliquer", "copy-plus", self.duplicate),
            button("Renommer", "pencil", self.rename),
            button("", "trash-2", self.delete, "Supprimer (restaurable)", "danger"),
        )
        variants.row(
            button("Restaurer", "history", self.restore, "Restaurer la dernière variante supprimée"),
            button("Comparer", "layers", self.compare),
        )
        self.compare_with = LSSelect()
        variants.add(self.compare_with)
        self.comparison = variants.add(label("", "faint", wrap=True))
        current = self.section("Variante active")
        self.active_service = LSSelect([(s.label, s.key) for s in model.SERVICES])
        self.active_service.activated.connect(lambda: self._update(service=self.active_service.currentData()))
        self.active_profile = LSSelect()
        self.active_profile.activated.connect(lambda: self._update(profile=self.active_profile.currentData()))
        current.add(self.active_service)
        current.add(self.active_profile)
        current.row(button("Profil personnalisé…", "plus", self.custom_profile), stretch=True)
        self.profile_notes = current.add(label("", "faint", wrap=True))
        self.finish()

    def create(self) -> str | None:
        studio = self.page.studio
        if studio is None:
            return None
        service = model.service(self.service.currentData())
        name = self.name.text().strip() or f"{service.label} {len(studio.state().variants) + 1}"
        profile = self.profile.currentData()
        self.name.clear()
        return self.page.run("Variante", lambda: studio.create_variant(name, service.key, profile))

    def _activate(self, item: QListWidgetItem) -> None:
        studio = self.page.studio
        if studio is not None and item.data(ID_ROLE) != studio.state().active:
            self.page.run("Variante active", lambda: studio.activate_variant(item.data(ID_ROLE)))

    def _current(self) -> str | None:
        item = self.list.currentItem()
        if item is not None:
            return item.data(ID_ROLE)
        variant = self.page.active_variant()
        return variant.id if variant else None

    def duplicate(self) -> None:
        studio, variant_id = self.page.studio, self._current()
        if studio and variant_id:
            self.page.run("Duplication", lambda: studio.duplicate_variant(variant_id))

    def rename(self) -> None:
        studio, variant_id = self.page.studio, self._current()
        if not (studio and variant_id):
            return
        variant = studio.state().variant(variant_id)
        name, ok = QInputDialog.getText(
            self, "Renommer la variante", "Nom :", text=variant.name if variant else ""
        )
        if ok:
            self.page.run("Renommage", lambda: studio.rename_variant(variant_id, name))

    def delete(self) -> None:
        studio, variant_id = self.page.studio, self._current()
        if studio and variant_id:
            self.page.run("Suppression", lambda: studio.delete_variant(variant_id))

    def restore(self) -> None:
        studio = self.page.studio
        if studio is not None:
            self.page.run("Restauration", studio.restore_variant)

    def compare(self) -> None:
        studio, first, second = self.page.studio, self._current(), self.compare_with.currentData()
        if not (studio and first and second) or first == second:
            self.comparison.setText("Choisissez deux variantes différentes.")
            return
        diff = self.page.run("Comparaison", lambda: studio.compare_variants(first, second))
        if not diff:
            return
        self.comparison.setText(
            "\n".join(
                [
                    f"Service : {diff['service'][0]} / {diff['service'][1]} · "
                    f"profil : {diff['profile'][0]} / {diff['profile'][1]}",
                    f"Seulement dans la première : {', '.join(diff['equipment_only_first']) or '—'}",
                    f"Seulement dans la seconde : {', '.join(diff['equipment_only_second']) or '—'}",
                    f"Feux : {diff['lights'][0]} / {diff['lights'][1]} · "
                    f"motifs : {len(diff['patterns'][0])} / {len(diff['patterns'][1])}",
                    f"Livrée différente : {', '.join(diff['livery']) or 'non'}",
                ]
            )
        )

    def _update(self, **fields) -> None:  # type: ignore[no-untyped-def]
        studio, variant = self.page.studio, self.page.active_variant()
        if studio and variant:
            self.page.run("Variante", lambda: studio.update_variant(variant.id, **fields))

    def custom_profile(self) -> None:
        studio, variant = self.page.studio, self.page.active_variant()
        if studio is None:
            return
        name, ok = QInputDialog.getText(self, "Profil personnalisé", "Nom du profil :")
        if ok and name.strip():
            base = variant.profile if variant else "sedan"
            key = self.page.run("Profil", lambda: studio.save_custom_profile(name, name, base))
            if key and variant:
                self.page.run("Profil", lambda: studio.update_variant(variant.id, profile=key))

    def refresh(self) -> None:
        studio = self.page.studio
        state = studio.state() if studio else None
        profiles = state.all_profiles() if state else list(model.PROFILES)
        for select in (self.profile, self.active_profile):
            current = select.currentData()
            select.clear()
            for profile in profiles:
                select.addItem(profile.label + (" (personnalisé)" if profile.custom else ""), profile.key)
            if current:
                select.select_data(current)
        if studio is not None and self.profile.currentIndex() <= 0:
            self.profile.select_data(studio.default_profile())
        self.list.clear()
        self.compare_with.clear()
        for variant in state.variants if state else []:
            marker = "● " if variant.id == state.active else "○ "
            item = QListWidgetItem(
                icons.icon("siren", size=14),
                f"{marker}{variant.name} — {model.service(variant.service).label}",
            )
            item.setData(ID_ROLE, variant.id)
            self.list.addItem(item)
            self.compare_with.addItem(variant.name, variant.id)
            if variant.id == state.active:
                self.list.setCurrentItem(item)
        variant = state.active_variant if state else None
        for widget in (self.active_service, self.active_profile):
            widget.setEnabled(variant is not None)
        if variant is not None:
            self.active_service.select_data(variant.service)
            self.active_profile.select_data(variant.profile)
            profile = state.profile(variant.profile)
            self.profile_notes.setText(f"{profile.label} : {len(profile.zones)} zone(s). {profile.notes}")
        else:
            self.profile_notes.setText("Créez une variante pour commencer.")


# --- Bibliothèque d'équipements -----------------------------------------------------------------


class EquipmentList(QListWidget):
    """Liste d'équipements déplaçables vers le viewport (glisser-déposer)."""

    def __init__(self) -> None:
        super().__init__()
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setIconSize(QSize(52, 52))

    def mimeData(self, items) -> QMimeData:  # type: ignore[no-untyped-def]  # noqa: N802
        data = QMimeData()
        if items:
            data.setData(MIME, str(items[0].data(ID_ROLE)).encode("utf-8"))
        return data

    def mimeTypes(self) -> list[str]:  # noqa: N802
        return [MIME]


class EquipmentPanel(QWidget):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        self._icons: dict[str, QIcon] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        self.search = LSInput("Rechercher un équipement…", "search")
        self.search.textChanged.connect(self.refresh)
        families = [("Équipements du service", "service"), ("Tous les équipements", "")]
        self.family = LSSelect(families + [(v, k) for k, v in model.FAMILY_LABELS.items()])
        self.family.currentIndexChanged.connect(self.refresh)
        layout.addWidget(self.search)
        layout.addWidget(self.family)
        self.list = EquipmentList()
        self.list.currentItemChanged.connect(lambda *_: self._show())
        self.list.itemDoubleClicked.connect(lambda _i: self.add())
        layout.addWidget(self.list, 3)
        self.details = label("", "muted", wrap=True)
        layout.addWidget(self.details)
        self.zone = LSSelect()
        tooltip(self.zone, "Zone de placement proposée par le profil du véhicule")
        layout.addWidget(self.zone)
        row = QHBoxLayout()
        self.add_button = button(
            "Ajouter", "plus", self.add, "Pose l'équipement sur la zone choisie", "primary"
        )
        self.pair_button = button(
            "Paire", "copy", self.add_pair, "Pose sur la zone et sur la zone symétrique"
        )
        self.click_button = button(
            "Par clic", "mouse-pointer-2", self.toggle_click, "Cliquez sur la carrosserie pour poser"
        )
        self.click_button.setCheckable(True)
        for widget in (self.add_button, self.pair_button, self.click_button):
            row.addWidget(widget)
        layout.addLayout(row)
        layout.addWidget(button("Importer un composant personnel…", "import", self.import_component))
        layout.addWidget(
            label("Glissez un équipement sur le véhicule pour le poser à cet endroit.", "faint", wrap=True)
        )
        self.loading = label("", "faint", wrap=True)
        layout.addWidget(self.loading)

    def current_id(self) -> str | None:
        item = self.list.currentItem()
        return item.data(ID_ROLE) if item else None

    def select_component(self, component_id: str) -> bool:
        for row in range(self.list.count()):
            if self.list.item(row).data(ID_ROLE) == component_id:
                self.list.setCurrentRow(row)
                return True
        return False

    def refresh(self) -> None:
        library = self.page.library
        current = self.current_id()
        self.list.clear()
        if library is None:
            self.loading.setText("Chargement de la bibliothèque d'équipements…")
            return
        self.loading.setText("")
        variant = self.page.active_variant()
        family = self.family.currentData()
        if family == "service" and variant is not None:
            components = library.for_service(variant.service, self.search.text())
        else:
            components = [
                c
                for c in library.search(self.search.text())
                if family in ("", "service") or c.family == family
            ]
        for component in (c for c in components if c.family):
            if component.id not in self._icons:
                try:
                    self._icons[component.id] = QIcon(render_thumbnail(library.preview_mesh(component), 96))
                except Exception:  # noqa: BLE001 (aperçu impossible : icône vide)
                    self._icons[component.id] = QIcon()
            compatible = (
                variant is None
                or not component.compatible_profiles
                or variant.profile in component.compatible_profiles
            )
            text = f"{component.name}\n{component.category_label}" + (
                "" if compatible else "\nNon prévu pour ce profil"
            )
            item = QListWidgetItem(self._icons[component.id], text)
            item.setData(ID_ROLE, component.id)
            self.list.addItem(item)
            if component.id == current:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._show()

    def _show(self) -> None:
        library, studio = self.page.library, self.page.studio
        component = library.get(self.current_id()) if library and self.current_id() else None
        variant = self.page.active_variant()
        self.zone.clear()
        if component is None:
            self.details.setText("Aucun équipement.")
            return
        dims = " × ".join(f"{v:.2f}".replace(".", ",") for v in component.dimensions)
        names = [
            model.PROFILES_BY_KEY[p].label
            for p in component.compatible_profiles
            if p in model.PROFILES_BY_KEY
        ]
        self.details.setText(
            f"<b>{component.name}</b><br>{component.category_label} · {dims} m · "
            f"{len(component.emitters)} feu(x)<br>"
            f"Profils : {', '.join(names) or 'tous'}<br>Licence : {component.license or 'non précisée'}<br>"
            f"Provenance : {component.provenance or '—'}"
        )
        if studio is not None and variant is not None:
            profile = studio.state().profile(variant.profile)
            for zone in profile.zones_for(component.category) or profile.zones:
                self.zone.addItem(zone.label, zone.key)
        if self.click_button.isChecked():
            self.page.place_component = component.id

    def add(self):  # type: ignore[no-untyped-def]
        studio, component_id = self.page.studio, self.current_id()
        if not (studio and component_id):
            return None
        zone = self.zone.currentData()
        result = self.page.run("Équipement", lambda: studio.add_equipment(component_id, zone))
        self.page.report(result)
        return result

    def add_pair(self) -> None:
        studio, component_id, zone = self.page.studio, self.current_id(), self.zone.currentData()
        if studio and component_id and zone:
            for result in self.page.run("Paire", lambda: studio.add_equipment_pair(component_id, zone)) or []:
                self.page.report(result)

    def toggle_click(self) -> None:
        self.page.place_component = self.current_id() if self.click_button.isChecked() else None

    def import_component(self) -> None:
        library = self.page.library
        if library is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Importer un équipement", "", "Modèles 3D (*.glb *.gltf *.obj *.fbx *.stl *.ply)"
        )
        if not path:
            return
        license_text, ok = QInputDialog.getText(
            self, "Licence", "Licence de ce composant (obligatoire pour la diffusion) :"
        )
        if ok:
            imported = self.page.run(
                "Import",
                lambda: library.import_file(
                    path, license=license_text or "Non précisée", provenance=f"Import : {path}"
                ),
            )
            if imported:
                self.refresh()


class ComponentsPanel(QWidget):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(label("Équipements de la variante active", "faint"))
        self.list = QListWidget()
        self.list.itemClicked.connect(lambda item: self.page.controller.select([item.data(ID_ROLE)]))
        layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(button("Masquer", "eye-off", lambda: self._visible(False)))
        row.addWidget(button("Afficher", "eye", lambda: self._visible(True)))
        row.addWidget(button("Grouper", "group", self.page.controller.group_selected))
        row.addWidget(button("", "trash-2", self.remove, "Supprimer l'équipement et ses feux", "danger"))
        layout.addLayout(row)

    def _visible(self, value: bool) -> None:
        self.page.controller.set_visible(self.page.controller.selected(), value)

    def remove(self) -> None:
        studio = self.page.studio
        if studio is not None:
            self.page.run("Suppression", lambda: studio.remove_equipment(self.page.controller.selected()))

    def refresh(self) -> None:
        studio, variant = self.page.studio, self.page.active_variant()
        self.list.clear()
        if studio is None or variant is None:
            return
        selected = set(self.page.controller.selected())
        for node in studio.equipment_nodes(variant):
            zone = node.extra["emergency_equipment"].get("zone") or "placement libre"
            text = f"{node.name} — {zone}" + ("" if node.visible else " (masqué)")
            item = QListWidgetItem(icons.icon("cuboid", size=14), text)
            item.setData(ID_ROLE, node.id)
            self.list.addItem(item)
            item.setSelected(node.id in selected)


# --- Propriétés de l'équipement -------------------------------------------------------------------


class EquipmentProperties(Page):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        self._updating = False
        head = self.section("Équipement sélectionné")
        self.title = head.add(label("Aucun équipement sélectionné", "muted", wrap=True))
        place = self.section(
            "Placement", "Coordonnées locales, zone du profil, aimantation, rotation par incréments."
        )
        self.zone = LSSelect()
        place.row(self.zone, button("Placer", "frame", self.move_to_zone))
        self.position = LSPropertyField("Position", suffix=" m", step=0.01)
        self.rotation = LSPropertyField(
            "Rotation", minimum=-360, maximum=360, step=15, decimals=1, suffix="°"
        )
        self.scale = LSPropertyField("Échelle", minimum=0.01, maximum=100, step=0.05)
        for name, field in (
            ("translation", self.position),
            ("rotation", self.rotation),
            ("scale", self.scale),
        ):
            field.edit_finished.connect(lambda v, n=name: self._transform(n, v))
            place.add(field)
        place.row(
            button("−15°", None, lambda: self._rotate(-15)),
            button("+15°", None, lambda: self._rotate(15)),
            button("Aimanter", "grid-3x3", self._snap, "Position sur une grille de 5 cm, rotation par 15°"),
            button("Miroir", "copy", self._mirror, "Duplication miroir (feux recopiés, côtés inversés)"),
        )
        anchor = self.section("Point d'ancrage", "Aligne l'équipement sur un point d'ancrage du véhicule.")
        self.anchor = LSSelect()
        anchor.row(self.anchor, button("Associer", "layers", self._attach))
        self.finish()

    def _node(self):  # type: ignore[no-untyped-def]
        session = self.page.controller.session
        node = session.scene.get(session.selection.active) if session else None
        return node if node is not None and "emergency_equipment" in node.extra else None

    def move_to_zone(self) -> None:
        node, studio, zone = self._node(), self.page.studio, self.zone.currentData()
        if node and studio and zone:
            self.page.run("Placement", lambda: studio.move_to_zone(node.id, zone))

    def _transform(self, name: str, values: list[float]) -> None:
        node = self._node()
        if node is None or self._updating:
            return
        transform = node.transform.copy()
        setattr(transform, name, [float(v) for v in values])
        self.page.controller.session.set_transforms({node.id: transform}, "Placement par coordonnées")

    def _rotate(self, degrees: float) -> None:
        node, studio = self._node(), self.page.studio
        if node and studio:
            self.page.run("Rotation", lambda: studio.rotate_step(node.id, degrees))

    def _snap(self) -> None:
        node, studio = self._node(), self.page.studio
        if node and studio:
            self.page.run("Aimantation", lambda: studio.snap(node.id))

    def _mirror(self) -> None:
        node, studio = self._node(), self.page.studio
        if node and studio:
            self.page.run("Miroir", lambda: studio.mirror_equipment([node.id]))

    def _attach(self) -> None:
        node, anchor_id = self._node(), self.anchor.currentData()
        session = self.page.controller.session
        if node is None or not anchor_id or session is None:
            return
        world = session.scene.world_matrix(anchor_id)
        local = decompose(np.linalg.inv(session.scene.parent_world_matrix(node.id)) @ world)
        local.scale = list(node.transform.scale)
        session.set_transforms({node.id: local}, "Association au point d'ancrage")

    def refresh(self) -> None:
        node, studio = self._node(), self.page.studio
        self._updating = True
        for widget in (self.zone, self.position, self.rotation, self.scale, self.anchor):
            widget.setEnabled(node is not None)
        self.zone.clear()
        self.anchor.clear()
        if node is None or studio is None:
            self.title.setText("Sélectionnez un équipement (viewport ou onglet Composants).")
            self._updating = False
            return
        info = node.extra["emergency_equipment"]
        self.title.setText(f"<b>{node.name}</b> — {model.EQUIPMENT_CATEGORIES.get(info.get('category'), '')}")
        variant = next(
            (v for v in studio.state().variants if studio.scene.is_ancestor(v.root_id, node.id)), None
        )
        if variant is not None:
            for zone in studio.state().profile(variant.profile).zones:
                self.zone.addItem(zone.label, zone.key)
            self.zone.select_data(info.get("zone"))
        for anchor_node in self.page.controller.session.scene.anchor_nodes():
            self.anchor.addItem(anchor_node.name, anchor_node.id)
        self.position.set_value(node.transform.translation)
        self.rotation.set_value(node.transform.rotation)
        self.scale.set_value(node.transform.scale)
        self._updating = False


# --- Éclairage ---------------------------------------------------------------------------------


class LightingPanel(Page):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        self._updating = False
        lights = self.section(
            "Sources lumineuses (prévisualisation)",
            "Simulation du viewport : ce ne sont pas des données de jeu.",
        )
        self.only_selected = QCheckBox("Seulement l'équipement sélectionné")
        self.only_selected.toggled.connect(self.refresh)
        lights.add(self.only_selected)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setMinimumHeight(150)
        self.list.itemSelectionChanged.connect(self._selection)
        lights.add(self.list)
        lights.row(
            button("Ajouter un feu", "plus", self.add_light),
            button("", "trash-2", self.remove_light, "Supprimer", "danger"),
        )
        props = self.section("Propriétés du feu")
        self.name = QLineEdit()
        self.name.editingFinished.connect(lambda: self._update(name=self.name.text().strip()))
        self.color = LSSelect([(v[0], k) for k, v in model.LIGHT_COLORS.items()])
        self.color.activated.connect(lambda: self._update(color=self.color.currentData()))
        self.intensity = spin(1.0, 0.0, 10.0, 0.1, 2)
        self.range = spin(12.0, 0.1, 200.0, 0.5, 1, " m")
        self.angle = spin(90.0, 1.0, 360.0, 5.0, 0, "°")
        for widget, key in ((self.intensity, "intensity"), (self.range, "range"), (self.angle, "angle")):
            widget.editingFinished.connect(lambda k=key, w=widget: self._update(**{k: w.value()}))
        self.visible = QCheckBox("Visible")
        self.visible.toggled.connect(lambda v: self._update(visible=v))
        self.enabled = QCheckBox("Activé")
        self.enabled.toggled.connect(lambda v: self._update(enabled=v))
        self.position = LSPropertyField("Position", suffix=" m", step=0.01)
        self.position.edit_finished.connect(lambda v: self._update(position=[float(x) for x in v]))
        grid = QGridLayout()
        rows = (
            ("Nom", self.name),
            ("Couleur", self.color),
            ("Intensité", self.intensity),
            ("Portée", self.range),
            ("Angle", self.angle),
        )
        for row, (title, widget) in enumerate(rows):
            grid.addWidget(label(title, "muted"), row, 0)
            grid.addWidget(widget, row, 1)
        props.body.addLayout(grid)
        props.row(self.visible, self.enabled, stretch=True)
        props.add(self.position)
        groups = self.section(
            "Groupes", "Avant, arrière, gauche, droite, rampe principale, secondaires, travail."
        )
        self.groups = QListWidget()
        self.groups.setMaximumHeight(170)
        groups.add(self.groups)
        groups.row(
            button(
                "Ajouter la sélection",
                "plus",
                self.add_to_group,
                "Ajoute les feux sélectionnés au groupe choisi",
            ),
            button("Retirer", "minus", self.remove_from_group),
        )
        groups.row(
            button("Nouveau groupe…", "layers", self.new_group),
            button("", "trash-2", self.delete_group, "", "danger"),
        )
        self.finish()

    def _selected_ids(self) -> list[str]:
        return [item.data(ID_ROLE) for item in self.list.selectedItems()]

    def _selection(self) -> None:
        self.page.selected_lights = set(self._selected_ids())
        self._fill()
        self.page.viewport.update()

    def _fill(self) -> None:
        variant, ids = self.page.active_variant(), self._selected_ids()
        light = variant.light(ids[0]) if variant and ids else None
        self._updating = True
        for widget in (
            self.name,
            self.color,
            self.intensity,
            self.range,
            self.angle,
            self.visible,
            self.enabled,
            self.position,
        ):
            widget.setEnabled(light is not None)
        if light is not None:
            self.name.setText(light.name)
            self.color.select_data(light.color)
            self.intensity.setValue(light.intensity)
            self.range.setValue(light.range)
            self.angle.setValue(light.angle)
            self.visible.setChecked(light.visible)
            self.enabled.setChecked(light.enabled)
            self.position.set_value(light.position)
        self._updating = False

    def _update(self, **fields) -> None:  # type: ignore[no-untyped-def]
        studio, ids = self.page.studio, self._selected_ids()
        if self._updating or studio is None or not ids:
            return

        def apply() -> None:  # plusieurs feux sélectionnés : même réglage
            studio.session.stack.begin("Feux")
            for light_id in ids:
                studio.update_light(light_id, **fields)
            studio.session.stack.commit()

        self.page.run("Feu", apply)

    def add_light(self) -> None:
        studio, session = self.page.studio, self.page.controller.session
        if studio is None or session is None:
            return
        node_id = session.selection.active
        if node_id is not None and "emergency_equipment" not in session.scene.nodes[node_id].extra:
            node_id = None
        self.page.run(
            "Feu", lambda: studio.add_light(node_id, "Feu personnalisé", (0.0, 0.1, 0.0), "red", "secondary")
        )

    def remove_light(self) -> None:
        studio, ids = self.page.studio, self._selected_ids()
        if not (studio and ids):
            return

        def apply() -> None:
            studio.session.stack.begin("Suppression de feux")
            for light_id in ids:
                studio.remove_light(light_id)
            studio.session.stack.commit()

        self.page.run("Suppression", apply)

    def _group_id(self) -> str | None:
        item = self.groups.currentItem()
        return item.data(ID_ROLE) if item else None

    def add_to_group(self) -> None:
        studio, variant, group_id = self.page.studio, self.page.active_variant(), self._group_id()
        if studio and variant and group_id:
            ids = list(dict.fromkeys([*variant.group(group_id).light_ids, *self._selected_ids()]))
            self.page.run("Groupe", lambda: studio.set_group_lights(group_id, ids))

    def remove_from_group(self) -> None:
        studio, variant, group_id = self.page.studio, self.page.active_variant(), self._group_id()
        if studio and variant and group_id:
            selected = set(self._selected_ids())
            ids = [i for i in variant.group(group_id).light_ids if i not in selected]
            self.page.run("Groupe", lambda: studio.set_group_lights(group_id, ids))

    def new_group(self) -> None:
        studio = self.page.studio
        if studio is None:
            return
        name, ok = QInputDialog.getText(self, "Nouveau groupe", "Nom du groupe :")
        if ok:
            self.page.run("Groupe", lambda: studio.create_group(name, "custom", self._selected_ids()))

    def delete_group(self) -> None:
        studio, group_id = self.page.studio, self._group_id()
        if studio and group_id:
            self.page.run("Groupe", lambda: studio.delete_group(group_id))

    def refresh(self) -> None:
        variant = self.page.active_variant()
        selected = set(self.page.selected_lights)
        session = self.page.controller.session
        active = session.selection.active if session else None
        self.list.blockSignals(True)
        self.list.clear()
        names: dict[str, list[str]] = {}
        if variant is not None:
            for group in variant.groups:
                for light_id in group.light_ids:
                    names.setdefault(light_id, []).append(group.name)
            for light in variant.lights:
                if self.only_selected.isChecked() and light.node_id != active:
                    continue
                state = "" if light.enabled else " (désactivé)"
                color = model.LIGHT_COLORS.get(light.color, ("personnalisée",))[0]
                item = QListWidgetItem(icons.icon("sun", size=14), f"{light.name} — {color}{state}")
                item.setToolTip("Groupes : " + (", ".join(names.get(light.id, [])) or "aucun"))
                item.setData(ID_ROLE, light.id)
                self.list.addItem(item)
                item.setSelected(light.id in selected)
        self.list.blockSignals(False)
        current = self._group_id()
        self.groups.clear()
        for group in variant.groups if variant else []:
            item = QListWidgetItem(
                icons.icon("layers", size=14), f"{group.name} — {len(group.light_ids)} feu(x)"
            )
            item.setData(ID_ROLE, group.id)
            self.groups.addItem(item)
            if group.id == current:
                self.groups.setCurrentItem(item)
        self._fill()


# --- Configurations : intérieur, sirènes, livrée, Lore Friendly -----------------------------------


class ConfigurationPanel(Page):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        self.player = sirens.SirenPlayer()
        interior = self.section(
            "Configuration intérieure", "Équipements posés dans l'habitacle selon le profil du véhicule."
        )
        interior.row(
            *[
                button(text, "layers", lambda k=key: self.apply_interior(k))
                for key, text in INTERIOR_LABELS.items()
            ]
        )
        self.custom_interiors = LSSelect()
        interior.row(
            self.custom_interiors,
            button("Appliquer", None, lambda: self.apply_interior(self.custom_interiors.currentData())),
        )
        interior.row(
            button("Enregistrer l'intérieur comme preset…", "save", self.save_interior), stretch=True
        )
        siren = self.section(
            "Sirènes",
            "Tonalités originales synthétisées ; un son joué ici n'est pas utilisable tel quel en jeu.",
        )
        self.modes = QTableWidget(0, 4)
        self.modes.setHorizontalHeaderLabels(["Mode", "Tonalité", "Motif lumineux", "AudioString (export)"])
        self.modes.verticalHeader().setVisible(False)
        self.modes.horizontalHeader().setStretchLastSection(True)
        self.modes.setMinimumHeight(150)
        siren.add(self.modes)
        available, reason = sirens.playback_available()
        play = button("Écouter", "video", self.play, reason)
        play.setEnabled(available)
        siren.row(play, button("Arrêter", "x", self.player.stop))
        siren.row(
            button("Ajouter un mode", "plus", self.add_mode), button("Enregistrer", "save", self.save_siren)
        )
        livery = self.section(
            "Livrée (données préparatoires)",
            "Livery Studio prévu : seules les données sont enregistrées ici.",
        )
        self.livery_fields: dict[str, QLineEdit] = {}
        grid = QGridLayout()
        fields = (
            ("livery_name", "Nom de livrée"),
            ("primary_color", "Couleur principale"),
            ("secondary_color", "Couleur secondaire"),
            ("unit_id", "Identifiant d'unité"),
            ("callsign", "Indicatif"),
        )
        for row, (key, title) in enumerate(fields):
            field = QLineEdit()
            self.livery_fields[key] = field
            grid.addWidget(label(title, "muted"), row, 0)
            grid.addWidget(field, row, 1)
        livery.body.addLayout(grid)
        livery.add(label("Marquages (un par ligne) :", "faint"))
        self.markings = QPlainTextEdit()
        self.markings.setMaximumHeight(70)
        livery.add(self.markings)
        livery.row(button("Enregistrer la livrée", "save", self.save_livery), stretch=True)
        lore = self.section("Lore Friendly et provenance", model.LORE_DISCLAIMER)
        lore.add(
            label(
                "Marques fictives proposées : " + ", ".join(model.FICTIONAL_BRANDS[:8]) + "…",
                "faint",
                wrap=True,
            )
        )
        self.lore = QListWidget()
        self.lore.setMinimumHeight(110)
        lore.add(self.lore)
        lore.row(button("Vérifier", "refresh-cw", self.refresh_lore), stretch=True)
        self.finish()

    def apply_interior(self, key: str | None) -> None:
        studio = self.page.studio
        if studio is not None and key:
            for result in self.page.run("Intérieur", lambda: studio.apply_interior_preset(key)) or []:
                self.page.report(result)

    def save_interior(self) -> None:
        studio = self.page.studio
        if studio is None:
            return
        name, ok = QInputDialog.getText(self, "Preset d'intérieur", "Nom :")
        if ok:
            self.page.run("Intérieur", lambda: studio.save_interior_preset(name))

    def _modes(self) -> list[SirenMode]:
        variant = self.page.active_variant()
        modes = []
        for row in range(self.modes.rowCount()):
            original = (
                variant.siren.modes[row]
                if variant and row < len(variant.siren.modes)
                else SirenMode(f"mode{row}", "Mode")
            )
            name_item = self.modes.item(row, 0)
            tone = self.modes.cellWidget(row, 1).currentData()
            pattern = self.modes.cellWidget(row, 2).currentData() or None
            modes.append(
                SirenMode(original.key, name_item.text() if name_item else original.label, tone, pattern)
            )
        return modes

    def save_siren(self) -> None:
        studio, variant = self.page.studio, self.page.active_variant()
        if studio is None or variant is None:
            return
        profile = variant.siren
        profile.modes = self._modes()
        profile.audio_strings = {}
        for row, mode in enumerate(profile.modes):
            item = self.modes.item(row, 3)
            if item is not None and item.text().strip():
                profile.audio_strings[mode.key] = item.text().strip()
        self.page.run("Sirène", lambda: studio.set_siren(profile))

    def add_mode(self) -> None:
        studio = self.page.studio
        if studio is not None:
            self.page.run("Sirène", lambda: studio.add_siren_mode("Nouveau mode", "hilo"))

    def play(self) -> None:
        row = max(self.modes.currentRow(), 0)
        if row < self.modes.rowCount():
            tone = self.modes.cellWidget(row, 1).currentData()
            self.page.run("Aperçu sonore", lambda: self.player.play(tone, loop=True))

    def save_livery(self) -> None:
        studio, variant = self.page.studio, self.page.active_variant()
        if studio is None or variant is None:
            return
        data = {key: field.text().strip() for key, field in self.livery_fields.items()}
        data["markings"] = [line.strip() for line in self.markings.toPlainText().splitlines() if line.strip()]
        data["logos"] = list(variant.livery.logos)
        data["notes"] = variant.livery.notes
        self.page.run("Livrée", lambda: studio.update_variant(variant.id, livery=data))

    def refresh_lore(self) -> None:
        studio = self.page.studio
        self.lore.clear()
        if studio is None or self.page.active_variant() is None:
            return
        for level, message in self.page.run("Lore Friendly", studio.lore_report) or []:
            self.lore.addItem(_issue_item(level, message))

    def refresh(self) -> None:
        studio, variant = self.page.studio, self.page.active_variant()
        self.custom_interiors.clear()
        for preset in studio.state().interior_presets if studio else []:
            self.custom_interiors.addItem(preset["name"], preset["name"])
        self.modes.setRowCount(0)
        if variant is None:
            return
        for row, mode in enumerate(variant.siren.modes):
            self.modes.insertRow(row)
            self.modes.setItem(row, 0, QTableWidgetItem(mode.label))
            tone = LSSelect([(v, k) for k, v in model.SIREN_TONES.items()])
            tone.select_data(mode.tone)
            self.modes.setCellWidget(row, 1, tone)
            pattern = LSSelect([("Aucun", "")] + [(p.name, p.id) for p in variant.patterns])
            pattern.select_data(mode.pattern_id or "")
            self.modes.setCellWidget(row, 2, pattern)
            self.modes.setItem(row, 3, QTableWidgetItem(variant.siren.audio_strings.get(mode.key, "")))
        for key, field in self.livery_fields.items():
            field.setText(str(getattr(variant.livery, key, "")))
        self.markings.setPlainText("\n".join(variant.livery.markings))


# --- Export ----------------------------------------------------------------------------------------


class ExportPanel(Page):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        intro = self.section(
            "Adaptateurs d'export", "Aucun fichier exporté n'est garanti fonctionnel en jeu sans validation."
        )
        self.adapter = LSSelect([(a.info.name, a.info.key) for a in adapters.ADAPTERS])
        self.adapter.currentIndexChanged.connect(self.refresh)
        intro.add(self.adapter)
        self.info = intro.add(label("", "muted", wrap=True))
        self.resource = LSInput("Nom de la ressource (ex. police_suv)")
        intro.add(self.resource)
        intro.row(
            button("Valider", "circle-check", self.validate),
            button("Exporter…", "download", self.export, variant="primary"),
        )
        self.issues = QListWidget()
        self.issues.setMinimumHeight(140)
        intro.add(self.issues)
        self.finish()

    def _adapter(self) -> adapters.Adapter:
        return adapters.ADAPTERS_BY_KEY[self.adapter.currentData()]

    def _context(self) -> adapters.ExportContext | None:
        studio, variant = self.page.studio, self.page.active_variant()
        if studio is None or variant is None:
            return None
        return adapters.ExportContext(studio, variant, self.resource.text().strip() or "lsf_vehicle")

    def validate(self) -> list:
        context = self._context()
        self.issues.clear()
        if context is None:
            self.issues.addItem(_issue_item("error", "Aucune variante active."))
            return []
        issues = self._adapter().validate(context)
        for issue in issues:
            self.issues.addItem(_issue_item(issue.level, issue.message))
        return issues

    def export(self, folder: str | None = None) -> list:
        context = self._context()
        if context is None:
            return []
        if not folder:
            folder = QFileDialog.getExistingDirectory(self, "Dossier d'export")
            if not folder:
                return []
        self.issues.clear()
        try:
            files = self._adapter().export(context, folder)
        except adapters.AdapterError as exc:
            for reason in exc.reasons:
                self.issues.addItem(_issue_item("error", reason))
            self.page.controller.notify.emit("Export impossible", exc.reasons[0], "warning")
            return []
        for path in files:
            self.issues.addItem(_issue_item("ok", f"Fichier écrit : {path}"))
        self.page.controller.notify.emit("Export terminé", f"{len(files)} fichier(s)", "success")
        return files

    def refresh(self) -> None:
        info = self._adapter().info
        status = "Disponible" if info.available else f"Non disponible : {info.unavailable_reason}"
        self.info.setText(
            f"<b>{info.name}</b><br>{info.description}<br><i>{status}</i><br><br>"
            f"<b>Fonctions</b> : {'; '.join(info.supported) or '—'}<br>"
            f"<b>Limites</b> : {'; '.join(info.limits)}<br>"
            f"<b>Dépendances</b> : {'; '.join(info.dependencies)}<br>"
            f"<b>Validations</b> : {'; '.join(info.validations) or '—'}"
        )


# --- Timeline des motifs ----------------------------------------------------------------------------


class TimelinePanel(QWidget):
    """Éditeur de motifs : lignes = groupes, colonnes = étapes (clic = allumé / éteint)."""

    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        self._frames: list[PatternFrame] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        top = QHBoxLayout()
        self.pattern = LSSelect()
        self.pattern.activated.connect(self._choose)
        top.addWidget(self.pattern, 2)
        self.preset = LSSelect([(v, k) for k, v in model.PATTERN_PRESETS.items()])
        top.addWidget(self.preset, 2)
        top.addWidget(button("Créer", "plus", self.create, "Nouveau motif depuis le preset"))
        top.addWidget(button("Dupliquer", "copy-plus", self.duplicate))
        top.addWidget(button("Preset", "save", self.save_preset, "Enregistrer comme preset réutilisable"))
        self.user_presets = LSSelect()
        top.addWidget(self.user_presets, 1)
        top.addWidget(button("Appliquer", None, self.apply_preset))
        top.addWidget(button("", "trash-2", self.delete, "Supprimer le motif", "danger"))
        layout.addLayout(top)
        controls = QHBoxLayout()
        self.play_button = button(
            "Lecture", "video", self.toggle_play, "Lecture / pause de la prévisualisation"
        )
        self.play_button.setCheckable(True)
        controls.addWidget(self.play_button)
        controls.addWidget(label("Vitesse", "muted"))
        self.speed = QSlider(Qt.Orientation.Horizontal)
        self.speed.setRange(25, 300)
        self.speed.setValue(100)
        self.speed.setMaximumWidth(160)
        self.speed.valueChanged.connect(lambda v: setattr(self.page, "speed", v / 100.0))
        controls.addWidget(self.speed)
        self.time_label = label("", "faint")
        controls.addWidget(self.time_label)
        controls.addStretch(1)
        controls.addWidget(button("+ étape", None, self.add_frame))
        controls.addWidget(button("− étape", None, self.remove_frame))
        controls.addWidget(button("Appliquer les modifications", "check", self.commit, variant="primary"))
        layout.addLayout(controls)
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.cellClicked.connect(self.toggle_cell)
        layout.addWidget(self.table, 1)

    def current_pattern(self):  # type: ignore[no-untyped-def]
        variant = self.page.active_variant()
        return variant.pattern(self.pattern.currentData()) if variant else None

    def _choose(self) -> None:
        studio, pattern_id = self.page.studio, self.pattern.currentData()
        if studio and pattern_id:
            self.page.run("Motif actif", lambda: studio.set_active_pattern(pattern_id))

    def create(self) -> None:
        studio = self.page.studio
        if studio is not None:
            self.page.run("Motif", lambda: studio.add_pattern(self.preset.currentData()))

    def duplicate(self) -> None:
        studio, pattern = self.page.studio, self.current_pattern()
        if studio and pattern:
            self.page.run("Motif", lambda: studio.duplicate_pattern(pattern.id))

    def delete(self) -> None:
        studio, pattern = self.page.studio, self.current_pattern()
        if studio and pattern:
            self.page.run("Motif", lambda: studio.delete_pattern(pattern.id))

    def save_preset(self) -> None:
        studio, pattern = self.page.studio, self.current_pattern()
        if studio and pattern:
            self.page.run("Preset", lambda: studio.save_pattern_preset(pattern.id))

    def apply_preset(self) -> None:
        studio, name = self.page.studio, self.user_presets.currentData()
        if studio and name:
            self.page.run("Preset", lambda: studio.apply_pattern_preset(name))

    def toggle_play(self) -> None:
        self.page.set_playing(self.play_button.isChecked())

    def groups(self) -> list:
        variant = self.page.active_variant()
        return [g for g in variant.groups if g.light_ids] if variant else []

    def toggle_cell(self, row: int, column: int) -> None:
        groups = self.groups()
        if row == 0 or not 0 <= column < len(self._frames) or row - 1 >= len(groups):
            return
        group_id = groups[row - 1].id
        frame = self._frames[column]
        frame.groups = (
            [g for g in frame.groups if g != group_id]
            if group_id in frame.groups
            else [*frame.groups, group_id]
        )
        self._paint()

    def add_frame(self) -> None:
        self._frames.append(PatternFrame(100, []))
        self._paint()

    def remove_frame(self) -> None:
        if len(self._frames) > 1:
            self._frames.pop()
            self._paint()

    def commit(self) -> None:
        studio, pattern = self.page.studio, self.current_pattern()
        if studio is None or pattern is None:
            return
        for column, frame in enumerate(self._frames):
            widget = self.table.cellWidget(0, column)
            if isinstance(widget, QSpinBox):
                frame.duration_ms = widget.value()
        frames = [PatternFrame(f.duration_ms, list(f.groups)) for f in self._frames]
        self.page.run("Motif", lambda: studio.update_pattern(pattern.id, frames))

    def _paint(self) -> None:
        groups = self.groups()
        self.table.clear()
        self.table.setRowCount(len(groups) + 1)
        self.table.setColumnCount(len(self._frames))
        self.table.setVerticalHeaderLabels(["Durée (ms)", *[g.name for g in groups]])
        self.table.setHorizontalHeaderLabels([str(i + 1) for i in range(len(self._frames))])
        for column, frame in enumerate(self._frames):
            duration = QSpinBox()
            duration.setRange(10, 5000)
            duration.setSingleStep(10)
            duration.setValue(int(frame.duration_ms))
            self.table.setCellWidget(0, column, duration)
            for row, group in enumerate(groups, start=1):
                on = group.id in frame.groups
                item = QTableWidgetItem("●" if on else "")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setToolTip("Allumé" if on else "Éteint")
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        self.mark(None)

    def mark(self, frame_index: int | None) -> None:
        """Repère de lecture sur l'en-tête de l'étape active."""
        for column in range(self.table.columnCount()):
            item = self.table.horizontalHeaderItem(column)
            if item is not None:
                item.setText(("▶ " if column == frame_index else "") + str(column + 1))
        pattern = self.current_pattern()
        self.time_label.setText(f"Cycle : {pattern.cycle_ms} ms" if pattern else "")

    def refresh(self) -> None:
        studio, variant = self.page.studio, self.page.active_variant()
        self.pattern.clear()
        self.user_presets.clear()
        for preset in studio.state().pattern_presets if studio else []:
            self.user_presets.addItem(preset["name"], preset["name"])
        if variant is not None:
            for pattern in variant.patterns:
                self.pattern.addItem(pattern.name, pattern.id)
            self.pattern.select_data(variant.active_pattern)
        pattern = self.current_pattern()
        self._frames = (
            [PatternFrame(f.duration_ms, list(f.groups)) for f in pattern.frames] if pattern else []
        )
        self._paint()


class DiagnosticsPanel(QWidget):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        top = QHBoxLayout()
        self.summary = LSBadge("—")
        top.addWidget(self.summary)
        top.addStretch(1)
        top.addWidget(
            button("Analyser", "refresh-cw", self.refresh, "Diagnostics, collisions approximatives, mémoire")
        )
        layout.addLayout(top)
        self.list = QListWidget()
        layout.addWidget(self.list, 1)

    def refresh(self) -> None:
        studio, variant = self.page.studio, self.page.active_variant()
        self.list.clear()
        if studio is None or variant is None:
            self.summary.setText("Aucune variante")
            return
        report = self.page.run("Diagnostics", studio.diagnostics) or []
        for level, message in report:
            self.list.addItem(_issue_item(level, message))
        memory = self.page.controller.session.memory_report()
        local, history = memory["local"] / 1048576, memory["history"] / 1048576
        text = f"Géométrie locale : {local:.1f} Mo · historique : {history:.1f} Mo"
        self.list.addItem(_issue_item("info", text))
        self.summary.setText(f"{sum(1 for level, _ in report if level == 'warning')} avertissement(s)")
