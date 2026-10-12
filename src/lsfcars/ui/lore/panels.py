"""Panneaux du Lore Friendly Studio : source, marques, Design DNA, presets, analyse, studios de
transformation, propositions, propriétés, historique, progression, diagnostics, validation,
provenance. Toute action passe par ``LoreFriendlyEngine`` (historique annulable)."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lsfcars.lorefriendly import analyzer, concepts, originality
from lsfcars.lorefriendly import dna as dna_mod
from lsfcars.lorefriendly import operations as ops
from lsfcars.lorefriendly.brands import CATEGORIES
from lsfcars.lorefriendly.components import COMPONENT_LABELS
from lsfcars.lorefriendly.engine import SOURCE, SOURCE_KINDS
from lsfcars.ui.design import tokens
from lsfcars.ui.design.components import LSInput, LSProgress, LSSelect, label, tooltip
from lsfcars.ui.editor.panels import Page, button, spin
from lsfcars.ui.livery.panels import check, clear_items, form, int_spin

ID_ROLE = Qt.ItemDataRole.UserRole
C = tokens.ColorTokens
STATUS_COLORS = {
    "measured": C.SUCCESS,
    "recognized": C.ELECTRIC,
    "ai": C.WARNING,
    "unknown": C.TEXT_SECONDARY,
    "user": C.PRIMARY,
}
REVIEW_COLORS = {"changed": C.SUCCESS, "slight": C.WARNING, "unchanged": C.ERROR, "check": C.ELECTRIC}
LIGHT_COLORS = (
    ("Blanc froid", (0.85, 0.92, 1.0)),
    ("Blanc chaud", (1.0, 0.94, 0.82)),
    ("Ambre", (1.0, 0.62, 0.15)),
    ("Rouge", (1.0, 0.12, 0.08)),
    ("Bleu glacier", (0.55, 0.8, 1.0)),
)
OPERATION_KINDS = {
    "deform": "déformation du maillage",
    "add": "pièce ajoutée",
    "replace": "pièce remplacée (l'ancienne est masquée, pas supprimée)",
    "wheels": "roues déplacées + déformation des ailes",
    "material": "matériaux propres à la variante",
}


def wrap(text: str = "", role: str = "muted") -> QLabel:
    widget = label(text, role, wrap=True)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


def pixmap(data: bytes | None, width: int = 300) -> QPixmap:
    image = QPixmap()
    if data:
        image.loadFromData(data, "PNG")
    if image.isNull():
        return image
    return image.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)


def swatch(colors: list[str]) -> QPixmap:
    image = QPixmap(18 * max(len(colors), 1), 14)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    for index, value in enumerate(colors):
        painter.fillRect(index * 18, 0, 16, 14, QColor(value))
    painter.end()
    return image


def local_path_label(text: str) -> str:
    """Chemin local abrégé (dossier et fichier) : le chemin complet reste en info-bulle."""
    if ":" in text[:3] or text.startswith(("\\", "/")):
        return "/".join(text.replace("\\", "/").split("/")[-2:])
    return text


def list_widget(height: int = 150) -> QListWidget:
    widget = QListWidget()
    widget.setMinimumHeight(height)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    return widget


def current_data(widget: QListWidget):  # type: ignore[no-untyped-def]
    item = widget.currentItem()
    return item.data(ID_ROLE) if item is not None else None


# --- Gauche ---------------------------------------------------------------------------------------


class SourcePanel(Page):
    """Véhicule source, design actif, variantes, points de restauration."""

    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        source = self.section(
            "Véhicule source",
            "Modèle importé, véhicule FiveM, modèle généré par IA ou élément du projet. "
            "La source est verrouillée et n'est jamais modifiée.",
        )
        self.sources = list_widget(110)
        source.add(self.sources)
        source.row(
            button(
                "Créer un design",
                "plus",
                self.create_design,
                "Nouveau design depuis la source choisie",
                "primary",
            ),
            button("Importer…", "import", page.import_requested.emit, "Importer un modèle 3D dans le projet"),
        )
        design = self.section("Design")
        self.designs = LSSelect()
        self.designs.activated.connect(lambda _i: self.select_design())
        design.add(self.designs)
        self.design_info = wrap("Aucun design.")
        design.add(self.design_info)
        variants = self.section(
            "Original et variantes",
            "Les transformations s'appliquent aux variantes (copies non destructives).",
        )
        self.targets = list_widget(130)
        self.targets.itemDoubleClicked.connect(lambda _i: self.show_target())
        variants.add(self.targets)
        variants.row(
            button(
                "Afficher", "eye", self.show_target, "Afficher l'élément choisi (les autres sont masqués)"
            ),
            button(
                "Revenir à l'original", "undo-2", lambda: page.show(SOURCE), "Afficher le véhicule source"
            ),
        )
        variants.row(
            button("Nouvelle variante", "copy-plus", self.new_variant, "Copie de l'élément choisi"),
            button(
                "Point de restauration", "save", self.restore_point, "Copie figée de la variante affichée"
            ),
        )
        self.points = LSSelect()
        variants.row(
            self.points, button("Restaurer", "history", self.restore, "Nouvelle variante depuis le point")
        )
        self.finish()

    def refresh(self) -> None:
        engine = self.page.engine
        clear_items(self.sources)
        clear_items(self.targets)
        self.designs.clear()
        self.points.clear()
        if engine is None:
            self.design_info.setText("Créez ou ouvrez un projet.")
            return
        for node_id, name, kind in engine.candidate_sources():
            item = QListWidgetItem(f"{name}\n{SOURCE_KINDS.get(kind, kind)}")
            item.setData(ID_ROLE, node_id)
            self.sources.addItem(item)
        if self.sources.count():
            self.sources.setCurrentRow(0)
        for item in engine.designs():
            self.designs.addItem(item["name"], item["id"])
        design = self.page.design()
        if design is None:
            self.design_info.setText("Aucun design : choisissez un véhicule source puis « Créer un design ».")
            return
        self.designs.select_data(design["id"])
        brand = engine.brands.get(design.get("brand"))
        self.design_info.setText(
            f"Source : {design['source_name']} "
            f"({SOURCE_KINDS.get(design['source_kind'], '')}) — verrouillée\n"
            f"Marque : {brand.name if brand else 'à choisir'} · Catégorie : "
            f"{CATEGORIES.get(design.get('category'), design.get('category'))} · Niveau : "
            f"{concepts.LEVELS.get(design.get('level'), '')}\n"
            f"{len(design['variants'])} variante(s), {len(design['concepts'])} proposition(s)"
        )
        for target, name in engine.targets(design):
            item = QListWidgetItem(("● " if design.get("display") == target else "   ") + name)
            item.setData(ID_ROLE, target)
            self.targets.addItem(item)
            if target == self.page.target():
                self.targets.setCurrentItem(item)
        variant = next((v for v in design["variants"] if v["id"] == self.page.target()), None)
        for point in (variant or {}).get("restore_points", []):
            self.points.addItem(f"{point['name']} · {point['at'][:16].replace('T', ' ')} UTC", point["id"])

    def create_design(self) -> None:
        source = current_data(self.sources)
        if source is None:
            self.page.notify("Lore Friendly", "Choisissez un véhicule source dans la liste.", "info")
            return
        self.page.run("Nouveau design", lambda: self.page.engine.create_design(source))

    def select_design(self) -> None:
        design_id = self.designs.currentData()
        if design_id:
            self.page.run("Design", lambda: self.page.engine.set_active(design_id))

    def chosen_target(self) -> str | None:
        return current_data(self.targets)

    def show_target(self) -> None:
        target = self.chosen_target()
        if target:
            self.page.show(target)

    def new_variant(self) -> None:
        self.page.new_variant(self.chosen_target() or SOURCE)

    def restore_point(self) -> None:
        target = self.page.target()
        if target == SOURCE:
            self.page.notify("Restauration", "Affichez d'abord une variante.", "info")
            return
        self.page.run("Point de restauration", lambda: self.page.engine.restore_point(None, target))

    def restore(self) -> None:
        point = self.points.currentData()
        target = self.page.target()
        if point and target != SOURCE:
            self.page.run("Restauration", lambda: self.page.engine.restore(None, target, point))


class BrandsPanel(Page):
    """Fictional Brand Library : marques GTA V (références créatives) et marques originales."""

    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        library = self.section(
            "Fictional Brand Library",
            "Marques de l'univers GTA V citées comme références créatives (aucun logo fourni) "
            "et marques originales.",
        )
        self.search = LSInput("Rechercher une marque…", "search")
        self.search.textChanged.connect(lambda _t: self.refresh())
        library.add(self.search)
        self.category = LSSelect([("Toutes catégories", None), *((v, k) for k, v in CATEGORIES.items())])
        self.origin = LSSelect([("Toutes", None), ("Univers GTA V", "gta"), ("Personnalisées", "custom")])
        for widget in (self.category, self.origin):
            widget.currentIndexChanged.connect(lambda _i: self.refresh())
        library.row(self.category, self.origin)
        self.list = list_widget(170)
        self.list.currentItemChanged.connect(lambda *_: self.show_details())
        library.add(self.list)
        self.details = wrap("")
        library.add(self.details)
        self.palette = QLabel()
        library.add(self.palette)
        library.row(button("Choisir cette marque", "check", self.choose, "Marque du design actif", "primary"))
        create = self.section("Créer une marque originale", "Nom vérifié : aucune marque automobile réelle.")
        self.name = LSInput("Nom de la marque")
        create.add(self.name)
        self.description = LSInput("Description (facultatif)")
        create.add(self.description)
        self.new_category = LSSelect([(v, k) for k, v in CATEGORIES.items()])
        self.style = LSInput("Direction stylistique")
        create.row(self.new_category, self.style)
        self.to_user = check("Enregistrer aussi dans ma bibliothèque", False)
        create.add(self.to_user)
        create.row(
            button("Suggérer des noms", "sparkles", self.suggest, "Noms originaux générés (filtrés)"),
            button("Créer", "plus", self.create, "Créer la marque"),
        )
        self.suggestions = list_widget(70)
        self.suggestions.itemDoubleClicked.connect(lambda item: self.name.setText(item.text()))
        create.add(self.suggestions)
        self.finish()

    def refresh(self) -> None:
        engine = self.page.engine
        selected = current_data(self.list)
        clear_items(self.list)
        if engine is None:
            return
        design = self.page.design()
        current = design.get("brand") if design else None
        for brand in engine.brands.search(
            self.search.text(), self.category.currentData(), self.origin.currentData()
        ):
            origin = "GTA V" if brand.is_gta else "originale"
            item = QListWidgetItem(
                f"{'✓ ' if brand.key == current else ''}{brand.name} — {brand.style or origin}"
            )
            item.setData(ID_ROLE, brand.key)
            self.list.addItem(item)
            if brand.key == (selected or current):
                self.list.setCurrentItem(item)

    def select(self, key: str) -> None:
        for row in range(self.list.count()):
            if self.list.item(row).data(ID_ROLE) == key:
                self.list.setCurrentRow(row)

    def show_details(self) -> None:
        engine = self.page.engine
        brand = engine.brands.get(current_data(self.list)) if engine else None
        if brand is None:
            self.details.setText("")
            self.palette.clear()
            return
        cats = ", ".join(CATEGORIES.get(c, c) for c in brand.categories) or "—"
        self.details.setText(
            f"{brand.name}\n{brand.description}\nCatégories : {cats}\nDirection : {brand.style}\n"
            f"Caractéristiques : {', '.join(brand.traits) or '—'}\nIdentité visuelle : {brand.identity}\n"
            f"Provenance : {brand.provenance}\nLicence : {brand.license}"
        )
        self.palette.setPixmap(swatch(brand.palette))
        tooltip(self.palette, "Palette indicative")

    def choose(self) -> None:
        key = current_data(self.list)
        design = self.page.design()
        if key is None or design is None:
            self.page.notify("Marque", "Choisissez une marque et créez d'abord un design.", "info")
            return
        self.page.run("Marque", lambda: self.page.engine.choose_brand(design["id"], key))

    def suggest(self) -> None:
        engine = self.page.engine
        if engine is None:
            return
        clear_items(self.suggestions)
        for name in engine.brands.suggest_names(self.page.session.project.project_id + self.name.text()):
            self.suggestions.addItem(name)

    def create(self) -> None:
        engine = self.page.engine
        if engine is None:
            return
        brand = self.page.run(
            "Nouvelle marque",
            lambda: engine.create_brand(
                self.name.text(),
                save_to_user=self.to_user.isChecked(),
                description=self.description.text(),
                categories=[self.new_category.currentData()],
                style=self.style.text(),
            ),
        )
        if brand is not None:
            self.name.clear()
            self.page.notify("Marque", f"« {brand.name} » ajoutée à la bibliothèque du projet.", "success")


class StylesPanel(Page):
    """Design DNA Engine : dix paramètres réglables, profils enregistrables."""

    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        profiles = self.section(
            "Design DNA",
            "Les valeurs guident les propositions ; elles ne modifient pas la géométrie à elles seules.",
        )
        self.profile = LSSelect()
        profiles.row(
            self.profile, button("Appliquer", "check", self.apply_profile, "Charger ce profil dans le design")
        )
        self.profile_info = wrap("")
        profiles.add(self.profile_info)
        sliders = self.section("Paramètres")
        self.sliders: dict[str, QSlider] = {}
        layout = form()
        for key, text in dna_mod.PARAMETERS.items():
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            value = label("50", "muted")
            value.setMinimumWidth(28)
            slider.valueChanged.connect(lambda v, lab=value: lab.setText(str(v)))
            row = QHBoxLayout()
            row.addWidget(slider, 1)
            row.addWidget(value)
            layout.addRow(text, row)
            self.sliders[key] = slider
        sliders.body.addLayout(layout)
        sliders.row(
            button(
                "Enregistrer dans le design", "save", self.save_values, "Valeurs du design actif", "primary"
            )
        )
        save = self.section("Profil personnalisé")
        self.profile_name = LSInput("Nom du profil")
        save.add(self.profile_name)
        self.profile_user = check("Enregistrer aussi dans ma bibliothèque", False)
        save.add(self.profile_user)
        save.row(button("Enregistrer le profil", "plus", self.save_profile, "Profil réutilisable"))
        self.finish()

    def values(self) -> dict[str, int]:
        return {k: s.value() for k, s in self.sliders.items()}

    def set_values(self, values: dict) -> None:
        for key, value in dna_mod.normalize(values).items():
            self.sliders[key].setValue(value)

    def refresh(self) -> None:
        engine = self.page.engine
        self.profile.clear()
        if engine is None:
            return
        for profile in engine.dnas.all():
            suffix = " (personnalisé)" if profile.origin == "custom" else ""
            self.profile.addItem(profile.name + suffix, profile.key)
        design = self.page.design()
        if design:
            self.profile.select_data(design.get("dna_profile"))
            self.set_values(design.get("dna", {}))
        profile = engine.dnas.get(self.profile.currentData())
        guidance = "\n".join(f"• {g}" for g in profile.guidance) if profile else ""
        self.profile_info.setText(f"{profile.description}\n{guidance}" if profile else "")

    def apply_profile(self) -> None:
        design = self.page.design()
        key = self.profile.currentData()
        if design and key:
            self.page.run("Design DNA", lambda: self.page.engine.apply_dna_profile(design["id"], key))

    def save_values(self) -> None:
        design = self.page.design()
        if design:
            self.page.run(
                "Design DNA", lambda: self.page.engine.update_design(design["id"], dna=self.values())
            )

    def save_profile(self) -> None:
        engine = self.page.engine
        if engine is None:
            return
        profile = self.page.run(
            "Profil Design DNA",
            lambda: engine.save_dna_profile(
                self.profile_name.text(), self.values(), to_user=self.profile_user.isChecked()
            ),
        )
        if profile is not None:
            self.page.notify("Design DNA", f"Profil « {profile.name} » enregistré.", "success")


class PresetsPanel(Page):
    """Niveau de transformation, contraintes techniques et presets de transformation."""

    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        self._loading = False
        level = self.section("Niveau de transformation")
        self.level = LSSelect([(v, k) for k, v in concepts.LEVELS.items()])
        self.level.activated.connect(lambda _i: self.save_level())
        level.add(self.level)
        self.level_info = wrap("")
        level.add(self.level_info)
        constraints = self.section("Contraintes techniques conservées", "Respectées par les propositions.")
        self.constraints: dict[str, object] = {}
        for key, (text, _ops) in concepts.CONSTRAINTS.items():
            box = check(text, False)
            box.toggled.connect(lambda _v: self.save_constraints())
            constraints.add(box)
            self.constraints[key] = box
        presets = self.section(
            "Presets de transformation",
            "Plans prêts à l'emploi (opérations réelles), appliqués à la variante affichée "
            "après confirmation.",
        )
        for key, (title, description, _plan) in concepts.QUICK_PRESETS.items():
            presets.add(button(title, "sparkles", lambda k=key: page.apply_preset(k), description))
        self.finish()

    def refresh(self) -> None:
        design = self.page.design()
        self._loading = True
        if design:
            self.level.select_data(design.get("level", "balanced"))
            for key, box in self.constraints.items():
                box.setChecked(key in design.get("constraints", []))  # type: ignore[attr-defined]
        self.level_info.setText(concepts.LEVEL_DESCRIPTIONS.get(self.level.currentData(), ""))
        self._loading = False

    def save_level(self) -> None:
        design = self.page.design()
        if design and not self._loading:
            self.page.run(
                "Niveau", lambda: self.page.engine.update_design(design["id"], level=self.level.currentData())
            )

    def save_constraints(self) -> None:
        design = self.page.design()
        if design is None or self._loading:
            return
        chosen = [k for k, box in self.constraints.items() if box.isChecked()]  # type: ignore[attr-defined]
        self.page.run("Contraintes", lambda: self.page.engine.update_design(design["id"], constraints=chosen))


# --- Droite ---------------------------------------------------------------------------------------


class AnalysisPanel(Page):
    """Vehicle Design Analyzer : rapport éditable, statut de chaque information."""

    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        top = self.section("Vehicle Design Analyzer", "Analyse de la géométrie réelle du véhicule affiché.")
        top.row(
            button(
                "Analyser",
                "scan",
                page.analyze,
                "Analyser le véhicule (source ou variante affichée)",
                "primary",
            )
        )
        legend = " · ".join(
            f"{analyzer.STATUS_SHORT[k]} = {v.lower()}" for k, v in analyzer.STATUS_LABELS.items()
        )
        top.add(wrap(f"Statuts : {legend}. Double-clic : corriger une valeur.", "faint"))
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Élément", "Valeur", "Statut"])
        self.tree.setMinimumHeight(380)
        self.tree.setWordWrap(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tree.itemDoubleClicked.connect(self.edit)
        top.add(self.tree)
        self.warnings = wrap("", "faint")
        top.add(self.warnings)
        self.finish()

    def refresh(self) -> None:
        clear_items(self.tree)
        design = self.page.design()
        report = (design or {}).get("analysis")
        if not report:
            self.warnings.setText("Aucune analyse : cliquez sur « Analyser ».")
            return
        sections: dict[str, QTreeWidgetItem] = {}
        for entry in report["entries"]:
            parent = sections.get(entry["section"])
            if parent is None:
                parent = QTreeWidgetItem([analyzer.SECTIONS.get(entry["section"], entry["section"])])
                self.tree.addTopLevelItem(parent)
                parent.setExpanded(True)
                sections[entry["section"]] = parent
            item = QTreeWidgetItem(
                [entry["label"], str(entry["value"] or "—"), analyzer.STATUS_SHORT[entry["status"]]]
            )
            item.setToolTip(2, analyzer.STATUS_LABELS[entry["status"]])
            item.setData(0, ID_ROLE, entry["key"])
            item.setForeground(2, QColor(STATUS_COLORS.get(entry["status"], C.TEXT_SECONDARY)))
            item.setToolTip(
                1, f"Source : {entry['source']}" + (f"\n{entry['note']}" if entry.get("note") else "")
            )
            parent.addChild(item)
        target = report.get("target", SOURCE)
        what = "véhicule source" if target == SOURCE else "variante"
        warnings = "\n".join(report.get("warnings", []))
        self.warnings.setText(
            f"Analyse du {what} · {report.get('at', '')[:16].replace('T', ' ')} UTC\n{warnings}".strip()
        )

    def edit(self, item: QTreeWidgetItem, _column: int) -> None:
        key = item.data(0, ID_ROLE)
        design = self.page.design()
        if not key or design is None:
            return
        value, ok = QInputDialog.getText(
            self, "Corriger l'analyse", item.text(0), text=item.text(1).strip("— ")
        )
        if ok:
            self.page.run("Analyse", lambda: self.page.engine.set_analysis_value(design["id"], key, value))


class ParamForm(QWidget):
    """Formulaire des paramètres d'une opération du catalogue."""

    def __init__(self) -> None:
        super().__init__()
        self.layout_ = form()
        self.setLayout(self.layout_)
        self.widgets: dict[str, tuple[str, QWidget]] = {}

    def build(self, spec: ops.OperationSpec | None) -> None:
        while self.layout_.rowCount():
            self.layout_.removeRow(0)
        self.widgets = {}
        if spec is None:
            return
        for p in spec.params:
            widget: QWidget
            if p.kind == "float":
                widget = spin(
                    float(p.default), p.minimum, p.maximum, p.step, 3, f" {p.unit}" if p.unit else ""
                )  # type: ignore[arg-type]
            elif p.kind == "int":
                widget = int_spin(int(p.default), int(p.minimum), int(p.maximum))  # type: ignore[call-overload]
            elif p.kind == "choice":
                widget = LSSelect([(text, key) for key, text in p.choices])
                widget.select_data(p.default)
            elif p.kind == "color":
                widget = LSSelect(list(LIGHT_COLORS))
                default = tuple(p.default)  # type: ignore[arg-type]
                best = min(
                    LIGHT_COLORS, key=lambda c: sum(abs(a - b) for a, b in zip(c[1], default, strict=False))
                )
                widget.select_data(best[1])
            else:
                widget = check(p.label, bool(p.default))
            self.layout_.addRow(p.label, widget)
            self.widgets[p.key] = (p.kind, widget)

    def values(self) -> dict:
        result: dict = {}
        for key, (kind, widget) in self.widgets.items():
            if kind in ("float", "int"):
                result[key] = widget.value()  # type: ignore[attr-defined]
            elif kind in ("choice", "color"):
                result[key] = widget.currentData()  # type: ignore[attr-defined]
            else:
                result[key] = widget.isChecked()  # type: ignore[attr-defined]
        return result

    def set_value(self, key: str, value) -> None:  # type: ignore[no-untyped-def]
        kind, widget = self.widgets[key]
        if kind in ("float", "int"):
            widget.setValue(value)  # type: ignore[attr-defined]
        elif kind in ("choice", "color"):
            widget.select_data(value)  # type: ignore[attr-defined]


class TransformPanel(Page):
    """Front Design Studio, Rear Design Studio, Body Silhouette Studio, identité lumineuse."""

    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        top = self.section(
            "Studios de transformation", "Modifications réelles du maillage ou pièces ajoutées."
        )
        self.studio = LSSelect([(v, k) for k, v in ops.STUDIOS.items()])
        self.studio.currentIndexChanged.connect(lambda _i: self.fill_operations())
        top.add(self.studio)
        self.operations = list_widget(150)
        self.operations.currentItemChanged.connect(lambda *_: self.select_operation())
        top.add(self.operations)
        self.description = wrap("")
        top.add(self.description)
        params = self.section("Paramètres")
        self.params = ParamForm()
        params.add(self.params)
        self.impacts = wrap("", "faint")
        params.add(self.impacts)
        self.target = wrap("", "faint")
        params.add(self.target)
        params.row(
            button(
                "Prévisualiser", "eye", self.preview, "Rendu avant / après (rien n'est écrit dans le projet)"
            ),
            button(
                "Appliquer", "check", self.apply, "Appliquer à la variante affichée (annulable)", "primary"
            ),
        )
        self.preview_image = QLabel()
        self.preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        params.add(self.preview_image)
        self.preview_text = wrap("", "faint")
        params.add(self.preview_text)
        self.fill_operations()
        self.finish()

    def fill_operations(self) -> None:
        clear_items(self.operations)
        for spec in ops.by_studio(self.studio.currentData()):
            item = QListWidgetItem(spec.label)
            item.setData(ID_ROLE, spec.key)
            self.operations.addItem(item)
        self.operations.setCurrentRow(0)

    def chosen(self) -> ops.OperationSpec | None:
        key = current_data(self.operations)
        return ops.OPERATIONS.get(key) if key else None

    def select(self, key: str) -> None:
        self.studio.select_data(ops.OPERATIONS[key].studio)
        for row in range(self.operations.count()):
            if self.operations.item(row).data(ID_ROLE) == key:
                self.operations.setCurrentRow(row)

    def select_operation(self) -> None:
        spec = self.chosen()
        self.params.build(spec)
        self.preview_image.clear()
        self.preview_text.setText("")
        if spec is None:
            return
        self.description.setText(f"{spec.description}\nType : {OPERATION_KINDS.get(spec.kind, spec.kind)}.")
        self.impacts.setText(
            "Impacts possibles : " + "; ".join(ops.IMPACT_LABELS[i] for i in sorted(spec.impacts))
        )

    def refresh(self) -> None:
        design = self.page.design()
        target = self.page.target()
        if design is None:
            self.target.setText("Créez d'abord un design.")
        elif target == SOURCE:
            self.target.setText("Cible : une nouvelle variante sera créée (la source n'est jamais modifiée).")
        else:
            self.target.setText(f"Cible : {self.page.engine.label(design, target)}")

    def preview(self) -> None:
        spec = self.chosen()
        if spec is not None:
            self.page.preview_operation(spec.key, self.params.values())

    def show_preview(self, png: bytes, messages: list[str]) -> None:
        self.preview_image.setPixmap(pixmap(png, 320))
        self.preview_text.setText("Aperçu calculé (non appliqué) — " + " ".join(messages))

    def apply(self) -> None:
        spec = self.chosen()
        if spec is not None:
            self.page.apply_plan([{"op": spec.key, "params": self.params.values()}], spec.label)


class ProposalsPanel(Page):
    """Lore Concept Generator : propositions, aperçus rendus, application."""

    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        top = self.section(
            "Lore Concept Generator",
            "Plans de transformation fondés sur la marque, le Design DNA, le niveau et les contraintes.",
        )
        self.engine_choice = LSSelect(
            [
                (concepts.LOCAL_ENGINE_LABEL, "local"),
                ("Claude (cloud) — plans validés contre le catalogue", "anthropic"),
            ]
        )
        top.add(self.engine_choice)
        self.count = int_spin(3, 1, 6)
        top.row(label("Nombre de propositions", "muted"), self.count, stretch=True)
        top.row(
            button("Générer", "sparkles", self.generate, "Nouvelles propositions", "primary"),
            button(
                "Aperçus",
                "image",
                page.compute_previews,
                "Rendu de la géométrie transformée (en arrière-plan)",
            ),
        )
        self.list = list_widget(220)
        self.list.setIconSize(QSize(120, 30))
        self.list.currentItemChanged.connect(lambda *_: self.show_details())
        top.add(self.list)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.add(self.preview)
        self.details = wrap("")
        top.add(self.details)
        top.row(
            button(
                "Appliquer",
                "check",
                self.apply,
                "Nouvelle variante transformée (après confirmation)",
                "primary",
            ),
            button(
                "Image conceptuelle…",
                "image",
                self.concept_image,
                "ComfyUI (workflow utilisateur) : image 2D seulement",
            ),
        )
        self.concept = QLabel()
        self.concept.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.add(self.concept)
        self.concept_note = wrap("", "faint")
        top.add(self.concept_note)
        self.finish()

    def refresh(self) -> None:
        selected = current_data(self.list)
        clear_items(self.list)
        design = self.page.design()
        if design is None:
            self.details.setText("")
            return
        blobs = self.page.session.scene.blobs
        for concept in reversed(design["concepts"]):
            level = concepts.LEVELS.get(concept["level"], "")
            item = QListWidgetItem(f"{concept['title']} · {level} · {len(concept['plan'])} opération(s)")
            item.setData(ID_ROLE, concept["id"])
            if concept.get("preview") in blobs:
                item.setIcon(QIcon(pixmap(blobs[concept["preview"]], 120)))
            item.setToolTip(concept["summary"])
            self.list.addItem(item)
            if concept["id"] == selected:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self.show_details()

    def chosen(self) -> dict | None:
        design = self.page.design()
        concept_id = current_data(self.list)
        if design is None or concept_id is None:
            return None
        return next((c for c in design["concepts"] if c["id"] == concept_id), None)

    def select_index(self, row: int) -> None:
        self.list.setCurrentRow(row)

    def show_details(self) -> None:
        concept = self.chosen()
        self.preview.clear()
        self.concept.clear()
        self.concept_note.setText("")
        if concept is None:
            self.details.setText("Aucune proposition : choisissez une marque puis « Générer ».")
            return
        blobs = self.page.session.scene.blobs
        if concept.get("preview") in blobs:
            self.preview.setPixmap(pixmap(blobs[concept["preview"]], 330))
        steps = "\n".join(
            f"• {ops.OPERATIONS[s['op']].label} — {s.get('why', '')}".rstrip(" —")
            for s in concept["plan"]
            if s["op"] in ops.OPERATIONS
        )
        skipped = (
            ("\nIgnorées (incompatibles) : " + "; ".join(concept["skipped"]))
            if concept.get("skipped")
            else ""
        )
        source = f"Moteur : {concept.get('engine_label', concept.get('engine'))}"
        if concept.get("reported_cost"):
            source += f" · coût communiqué : {concept['reported_cost']}"
        note = (
            "Aperçu : rendu de la géométrie transformée (non appliqué)."
            if concept.get("preview")
            else "Aperçu non calculé : bouton « Aperçus »."
        )
        self.details.setText(f"{concept['summary']}\n{steps}{skipped}\n{source}\n{note}")
        if concept.get("concept_image") in blobs:
            self.concept.setPixmap(pixmap(blobs[concept["concept_image"]], 330))
            self.concept_note.setText(
                "Image conceptuelle 2D (ComfyUI) : illustration, ce n'est pas un modèle 3D."
            )

    def generate(self) -> None:
        if self.engine_choice.currentData() == "local":
            self.page.generate_concepts(self.count.value())
        else:
            self.page.cloud_concepts(self.count.value())

    def apply(self) -> None:
        concept = self.chosen()
        if concept is not None:
            self.page.apply_concept(concept["id"])

    def concept_image(self) -> None:
        concept = self.chosen()
        if concept is not None:
            self.page.concept_image(concept["id"])


class PropertiesPanel(Page):
    """Propriétés : composant sélectionné (type corrigible), variante affichée et son journal."""

    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        selection = self.section("Composant sélectionné", "Cliquez une pièce dans le viewport.")
        self.component = wrap("Aucune sélection.")
        selection.add(self.component)
        self.kind = LSSelect(
            [(v, k) for k, v in COMPONENT_LABELS.items() if k not in ("technical", "emergency")]
        )
        selection.row(
            self.kind,
            button("Définir le type", "pencil", self.set_kind, "Corrige la reconnaissance (annulable)"),
        )
        variant = self.section("Variante affichée")
        self.variant = wrap("")
        variant.add(self.variant)
        self.log = list_widget(160)
        variant.add(self.log)
        self.finish()

    def refresh(self) -> None:
        clear_items(self.log)
        info = self.page.selected_component()
        if info is None:
            self.component.setText("Aucune sélection.")
        else:
            node, comp = info
            if comp is None:
                self.component.setText(f"{node.name} (hors du véhicule affiché)")
            else:
                size = comp.size
                self.component.setText(
                    f"{node.name}\nType : {comp.label} (reconnu par : {comp.source})\n"
                    f"Zone : {comp.zone} · côté : {comp.side}\n"
                    f"Encombrement : {size[0]:.2f} × {size[1]:.2f} × {size[2]:.2f} m"
                )
                self.kind.select_data(comp.kind)
        design = self.page.design()
        target = self.page.target()
        if design is None or target == SOURCE:
            self.variant.setText("Original affiché (verrouillé, jamais modifié)." if design else "")
            return
        variant = next(v for v in design["variants"] if v["id"] == target)
        self.variant.setText(
            f"{variant['name']} · créée le {variant['created_at'][:16].replace('T', ' ')} UTC"
        )
        for entry in variant["operations"]:
            self.log.addItem(f"{entry['label']} · {entry['at'][11:16]} UTC")

    def set_kind(self) -> None:
        self.page.set_component_kind(self.kind.currentData())


# --- Bas ------------------------------------------------------------------------------------------


class HistoryPanel(QWidget):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        row = QHBoxLayout()
        row.addWidget(button("Annuler", "undo-2", page.controller.undo, "Ctrl+Z"))
        row.addWidget(button("Rétablir", "redo-2", page.controller.redo, "Ctrl+Y"))
        row.addStretch(1)
        layout.addLayout(row)
        self.list = QListWidget()
        layout.addWidget(self.list, 1)

    def refresh(self) -> None:
        clear_items(self.list)
        design = self.page.design()
        for event in reversed((design or {}).get("history", [])):
            self.list.addItem(f"{event['at'][:16].replace('T', ' ')} UTC · {event['event']}")


class JobsPanel(QWidget):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        self.progress = LSProgress()
        layout.addWidget(self.progress)
        self.list = QListWidget()
        layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(button("Annuler la tâche", "x", page.cancel_job, "Interrompre la tâche en cours"))
        row.addStretch(1)
        layout.addLayout(row)

    def refresh(self) -> None:
        clear_items(self.list)
        for job in reversed(self.page.jobs[-30:]):
            self.list.addItem(f"{job.label} — {job.status} ({int(job.progress * 100)} %) {job.message}")
        active = next((j for j in reversed(self.page.jobs) if j.active), None)
        if active is not None:
            self.progress.set_progress(active.progress, f"{active.label} : {active.message}")
        elif self.page.jobs:
            last = self.page.jobs[-1]
            self.progress.set_progress(
                1.0 if last.status == "succeeded" else last.progress, f"{last.label} : {last.status}"
            )


class DiagnosticsPanel(QWidget):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        self.list = QListWidget()
        self.list.setWordWrap(True)
        layout.addWidget(self.list, 1)

    def refresh(self) -> None:
        clear_items(self.list)
        for level, text in self.page.diagnostics():
            item = QListWidgetItem(text)
            item.setForeground(QColor({"warning": C.WARNING, "error": C.ERROR}.get(level, C.TEXT_SECONDARY)))
            self.list.addItem(item)


class ValidationPanel(QWidget):
    """Workflow de validation humaine, revue d'originalité, vérifications de l'utilisateur."""

    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        left = QVBoxLayout()
        left.addWidget(label("Workflow", "muted"))
        self.steps = QListWidget()
        self.steps.setMaximumWidth(240)
        left.addWidget(self.steps, 1)
        layout.addLayout(left)
        middle = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(
            button(
                "Revue d'originalité",
                "shield",
                page.review,
                "Mesures techniques sur la variante affichée",
                "primary",
            )
        )
        row.addWidget(
            button(
                "Rapport de préparation FiveM",
                "file-box",
                page.fivem_report,
                "Vérifications avant le pipeline FiveM",
            )
        )
        row.addStretch(1)
        middle.addLayout(row)
        self.review = QTreeWidget()
        self.review.setHeaderLabels(["Aspect", "État", "Mesures et pistes"])
        self.review.setWordWrap(True)
        self.review.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        middle.addWidget(self.review, 1)
        middle.addWidget(wrap(originality.DISCLAIMER, "faint"))
        layout.addLayout(middle, 1)
        right = QVBoxLayout()
        right.addWidget(label("Vérifications par vous", "muted"))
        self.checks: dict[str, object] = {}
        for key, text in originality.CHECKLIST.items():
            box = check(text, False)
            box.toggled.connect(lambda value, k=key: page.set_checklist(k, value))
            right.addWidget(box)
            self.checks[key] = box
        right.addStretch(1)
        frame = QFrame()
        frame.setLayout(right)
        frame.setMaximumWidth(320)
        layout.addWidget(frame)

    def refresh(self) -> None:
        clear_items(self.steps)
        clear_items(self.review)
        engine = self.page.engine
        if engine is None:
            return
        for _key, text, done in engine.workflow():
            item = QListWidgetItem(f"{'✓' if done else '○'}  {text}")
            item.setForeground(QColor(C.SUCCESS if done else C.TEXT_SECONDARY))
            self.steps.addItem(item)
        design = self.page.design()
        if design is None:
            return
        for key, box in self.checks.items():
            box.blockSignals(True)  # type: ignore[attr-defined]
            box.setChecked(bool(design.get("checklist", {}).get(key)))  # type: ignore[attr-defined]
            box.blockSignals(False)  # type: ignore[attr-defined]
        review = design.get("originality", {}).get(self.page.target())
        for aspect in (review or {}).get("aspects", []):
            lines = aspect["measures"] + [f"Modifié : {c}" for c in aspect["changes"]]
            lines += [f"Piste : {s['label']} ({s['studio']})" for s in aspect["suggestions"]]
            item = QTreeWidgetItem([aspect["label"], aspect["status_label"], "\n".join(lines)])
            item.setForeground(1, QColor(REVIEW_COLORS.get(aspect["status"], C.TEXT_SECONDARY)))
            self.review.addTopLevelItem(item)


class ProvenancePanel(QWidget):
    """Asset Provenance Registry : consultation et saisie (licence jamais inventée)."""

    EDITABLE_COLUMNS = {2: "author", 3: "source", 4: "license", 5: "restrictions"}

    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        row = QHBoxLayout()
        self.summary = label("", "muted")
        row.addWidget(self.summary, 1)
        row.addWidget(
            button(
                "Ajouter une mention",
                "plus",
                self.add_mention,
                "Mention obligatoire (ne peut pas être retirée)",
            )
        )
        layout.addLayout(row)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            [
                "Ressource",
                "Type",
                "Auteur",
                "Source",
                "Licence",
                "Restrictions",
                "Importée le",
                "Mentions, modifications",
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self.changed)
        layout.addWidget(self.table, 1)

    def refresh(self) -> None:
        engine = self.page.engine
        self._loading = True
        self.table.setRowCount(0)
        if engine is None:
            self._loading = False
            return
        entries = engine.provenance()
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            extras = entry["mentions"] + entry["modifications"] + ([entry["notes"]] if entry["notes"] else [])
            source = local_path_label(entry["source"])
            values = [
                entry["name"],
                entry["kind_label"],
                entry["author"],
                source,
                entry["license"],
                entry["restrictions"],
                entry["imported_at"][:16].replace("T", " "),
                " · ".join(extras),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column not in self.EDITABLE_COLUMNS:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setData(ID_ROLE, entry["id"])
                if column == 4 and entry["license"] == "Non renseignée":
                    item.setForeground(QColor(C.WARNING))
                if column == 3:
                    item.setToolTip(entry["source"])
                self.table.setItem(row, column, item)
        missing = sum(1 for e in entries if e["license"] == "Non renseignée")
        self.summary.setText(
            f"{len(entries)} ressource(s) · {missing} licence(s) non renseignée(s) — "
            "double-clic pour compléter"
        )
        self.table.resizeRowsToContents()
        self._loading = False

    def changed(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() not in self.EDITABLE_COLUMNS:
            return
        field = self.EDITABLE_COLUMNS[item.column()]
        entry_id = item.data(ID_ROLE)
        self.page.run(
            "Provenance", lambda: self.page.engine.update_provenance(entry_id, **{field: item.text()})
        )

    def add_mention(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            self.page.notify("Provenance", "Choisissez une ressource dans le tableau.", "info")
            return
        entry_id = self.table.item(row, 0).data(ID_ROLE)
        text, ok = QInputDialog.getText(self, "Mention obligatoire", "Texte de la mention :")
        if ok and text.strip():
            self.page.run("Provenance", lambda: self.page.engine.add_mention(entry_id, text))
