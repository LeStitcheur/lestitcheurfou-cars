"""Panneaux d'AI Vehicle Creator.

Chaque panneau lit l'état dans ``page.creator`` / ``page.manager`` et agit par ``page.run`` (les
erreurs prévues deviennent des notifications). Les opérations longues passent par la file de
tâches du gestionnaire. Aucune couleur littérale (design system).
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lsfcars.ai import lore, mesh_assist, vision
from lsfcars.ai import references as refs_mod
from lsfcars.ai import texture as tex
from lsfcars.ai.engines.base import PROFILE_LABELS, Capability, GenerationRequest
from lsfcars.ai.manager import NOT_INTEGRATED, STATUS_LABELS, RoutingRequest
from lsfcars.ui.design import tokens
from lsfcars.ui.design.components import LSInput, LSProgress, LSSelect, label, tooltip
from lsfcars.ui.design.icons import icon
from lsfcars.ui.editor.panels import Page, button, spin
from lsfcars.ui.livery.panels import check, clear_items, form, int_spin

ID_ROLE = Qt.ItemDataRole.UserRole
C = tokens.ColorTokens


def pixmap_from_png(data: bytes | None, size: int = 72) -> QPixmap:
    pixmap = QPixmap()
    if data:
        pixmap.loadFromData(data, "PNG")
    if pixmap.isNull():
        return pixmap
    return pixmap.scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )


def pixmap_from_image(image, size: int = 72) -> QPixmap:  # type: ignore[no-untyped-def]
    buffer = io.BytesIO()
    copy = image.copy()
    copy.thumbnail((size * 2, size * 2))
    copy.save(buffer, "PNG")
    return pixmap_from_png(buffer.getvalue(), size)


def wrap_label(text: str = "", role: str = "muted") -> QLabel:
    widget = label(text, role, wrap=True)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


# --- Références -----------------------------------------------------------------------------------


class ReferencesPanel(Page):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        self._loading = False
        top = self.section(
            "Images de référence", "Avant, arrière, profils, trois quarts, dessus, intérieur, détails."
        )
        top.row(
            button("Importer…", "import", self.import_dialog, "PNG, JPG, WEBP, BMP, TIFF", "primary"),
            button("Supprimer", "trash-2", self.remove, "Retirer la référence (annulable)"),
        )
        self.list = QListWidget()
        self.list.setIconSize(QSize(56, 56))
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setMinimumHeight(170)
        self.list.currentItemChanged.connect(lambda *_: self.show_current())
        top.body.addWidget(self.list)
        top.row(
            button("Monter", "chevron-right", lambda: self.move(-1), "Réorganiser"),
            button("Descendre", "chevron-down", lambda: self.move(1), "Réorganiser"),
            button("Comparer", "lsf-split", self.compare, "Deux références côte à côte (Ctrl + clic)"),
        )

        props = self.section("Référence sélectionnée")
        layout = form()
        self.name = LSInput("Nom")
        self.name.editingFinished.connect(lambda: self.update_field("name", self.name.text().strip()))
        layout.addRow("Nom", self.name)
        self.view = LSSelect([(text, key) for key, text in refs_mod.VIEWS.items()])
        self.view.currentIndexChanged.connect(lambda _i: self.update_field("view", self.view.currentData()))
        layout.addRow("Vue", self.view)
        self.front_left = check(
            "Avant du véhicule à gauche de l'image", True, "Profils : orientation de l'image"
        )
        self.front_left.toggled.connect(lambda value: self.update_field("front_left", bool(value)))
        layout.addRow("", self.front_left)
        props.body.addLayout(layout)
        props.row(
            button("↺ 90°", "rotate-3d", lambda: self.rotate(-90), "Rotation de l'image"),
            button("↻ 90°", "rotate-3d", lambda: self.rotate(90), "Rotation de l'image"),
            button("Miroir", "lsf-mirror", self.flip, "Retournement horizontal"),
        )
        adjust = form()
        self.brightness = spin(1.0, 0.2, 3.0, 0.05, 2)
        self.contrast = spin(1.0, 0.2, 3.0, 0.05, 2)
        self.saturation = spin(1.0, 0.0, 3.0, 0.05, 2)
        for name, widget in (
            ("Luminosité", self.brightness),
            ("Contraste", self.contrast),
            ("Saturation", self.saturation),
        ):
            widget.editingFinished.connect(self.apply_adjust)
            adjust.addRow(name, widget)
        props.body.addLayout(adjust)
        props.row(
            button(
                "Recadrer (tracer)",
                "frame",
                lambda: self.page.set_board_mode("crop"),
                "Tracez le cadre sur l'image",
            ),
            button("Sans recadrage", "x", self.reset_crop),
        )
        self.mask_check = check("Afficher le détourage", False, "Silhouette détectée (algorithme local)")
        self.mask_check.toggled.connect(lambda _v: self.show_current())
        props.body.addWidget(self.mask_check)
        self.segment_info = wrap_label("", "faint")
        props.body.addWidget(self.segment_info)

        notes = self.section(
            "Annotations",
            "Marquez les logos réels (masqués avant génération et projection), roues, optiques…",
        )
        self.note_kind = LSSelect([(text, key) for key, text in refs_mod.ANNOTATION_KINDS.items()])
        self.note_text = LSInput("Description (facultatif)")
        notes.body.addWidget(self.note_kind)
        notes.body.addWidget(self.note_text)
        notes.row(
            button(
                "Annoter (tracer)",
                "square-dashed",
                lambda: self.page.set_board_mode("annotate"),
                "Tracez un rectangle",
            ),
            button("Supprimer", "trash-2", self.remove_note),
        )
        self.notes = QListWidget()
        self.notes.setMaximumHeight(110)
        notes.body.addWidget(self.notes)

        provenance = self.section(
            "Provenance et licence", "Conservées dans le projet et reprises dans le rapport."
        )
        prov = form()
        self.source = LSInput("Source (URL, photographe…)")
        self.author = LSInput("Auteur")
        self.license = LSInput("Licence / droits")
        for name, widget, key in (
            ("Source", self.source, "source"),
            ("Auteur", self.author, "author"),
            ("Licence", self.license, "license"),
        ):
            widget.editingFinished.connect(lambda w=widget, k=key: self.update_field(k, w.text().strip()))
            prov.addRow(name, widget)
        provenance.body.addLayout(prov)

        coverage = self.section("Couverture et cohérence")
        self.coverage = wrap_label("", "muted")
        coverage.body.addWidget(self.coverage)
        self.finish()

    # --- Lecture ------------------------------------------------------------------------------
    def current_id(self) -> str | None:
        item = self.list.currentItem()
        return item.data(ID_ROLE) if item else None

    def selected_ids(self) -> list[str]:
        return [item.data(ID_ROLE) for item in self.list.selectedItems()]

    def refresh(self) -> None:
        creator = self.page.creator
        current = self.current_id()
        self.list.blockSignals(True)
        clear_items(self.list)
        if creator is not None:
            for ref in creator.references():
                item = QListWidgetItem(f"{ref['name']}\n{refs_mod.VIEWS.get(ref['view'], ref['view'])}")
                item.setData(ID_ROLE, ref["id"])
                try:
                    item.setIcon(QIcon(pixmap_from_image(creator.prepared(ref, 256), 56)))
                except Exception:  # noqa: BLE001 (image illisible : la liste reste utilisable)
                    item.setIcon(icon("image"))
                self.list.addItem(item)
                if ref["id"] == current:
                    self.list.setCurrentItem(item)
            if self.list.currentItem() is None and self.list.count():
                self.list.setCurrentRow(0)
        self.list.blockSignals(False)
        self.show_current()
        self._refresh_coverage()

    def _refresh_coverage(self) -> None:
        creator = self.page.creator
        if creator is None or not creator.references():
            self.coverage.setText("Aucune référence.")
            return
        report = creator.coverage()
        views = ", ".join(f"{refs_mod.VIEWS[k]} ×{n}" for k, n in report.views.items() if n)
        lines = [f"Vues : {views}.", "", "Zones qui seront estimées (non visibles) :"]
        lines += [f"• {zone}" for zone in report.estimated_zones]
        lines += [f"⚠ {w}" for w in report.warnings]
        if not report.can_multiview:
            lines.append("Une seule vue orthogonale : reconstruction multi-vues impossible.")
        self.coverage.setText("\n".join(lines))

    def show_current(self) -> None:
        creator = self.page.creator
        ref_id = self.current_id()
        self._loading = True
        try:
            if creator is None or ref_id is None:
                self.page.board.set_reference(None)
                clear_items(self.notes)
                self.segment_info.setText("")
                return
            ref = creator.reference(ref_id)
            self.name.setText(ref["name"])
            self.view.select_data(ref["view"])
            self.front_left.setEnabled(ref["view"] in refs_mod.SIDE_VIEWS)
            self.front_left.setChecked(refs_mod.front_on_left(ref))
            adjust = ref.get("adjust", {})
            self.brightness.setValue(float(adjust.get("brightness", 1.0)))
            self.contrast.setValue(float(adjust.get("contrast", 1.0)))
            self.saturation.setValue(float(adjust.get("saturation", 1.0)))
            self.source.setText(ref.get("source", ""))
            self.author.setText(ref.get("author", ""))
            self.license.setText(ref.get("license", ""))
            clear_items(self.notes)
            for note in ref.get("annotations", []):
                kind = refs_mod.ANNOTATION_KINDS.get(note["kind"], note["kind"])
                item = QListWidgetItem(f"{kind} — {note.get('text') or '…'}")
                item.setData(ID_ROLE, note["id"])
                self.notes.addItem(item)
            seg = creator.segmentation(ref)
            if self.page.board.mode == "crop":
                image = creator.prepared({**ref, "crop": [0.0, 0.0, 1.0, 1.0]}, 1024)
                self.page.board.set_reference(image, ref["name"], [], None, ref.get("crop"))
            else:
                self.page.board.show_mask = self.mask_check.isChecked()
                mask = seg.mask if self.mask_check.isChecked() else None
                self.page.board.set_reference(
                    creator.prepared(ref, 1024), ref["name"], ref.get("annotations", []), mask
                )
            text = f"Détourage : {seg.method} (confiance {seg.confidence:.0%})."
            if seg.warnings:
                text += " " + " ".join(seg.warnings)
            self.segment_info.setText(text)
        finally:
            self._loading = False

    # --- Actions ------------------------------------------------------------------------------
    def import_dialog(self) -> None:
        patterns = " ".join(f"*{e}" for e in refs_mod.IMAGE_EXTENSIONS)
        paths, _ = QFileDialog.getOpenFileNames(self, "Importer des références", "", f"Images ({patterns})")
        if paths:
            self.page.import_references(paths)

    def update_field(self, key: str, value) -> None:  # type: ignore[no-untyped-def]
        ref_id = self.current_id()
        if self._loading or ref_id is None or self.page.creator is None:
            return
        if self.page.creator.reference(ref_id).get(key) == value:
            return
        self.page.run("Référence", lambda: self.page.creator.update_reference(ref_id, **{key: value}))

    def apply_adjust(self) -> None:
        values = {
            "brightness": self.brightness.value(),
            "contrast": self.contrast.value(),
            "saturation": self.saturation.value(),
        }
        self.update_field("adjust", {k: round(v, 3) for k, v in values.items()})

    def rotate(self, degrees: int) -> None:
        ref_id = self.current_id()
        if ref_id:
            self.page.run("Rotation", lambda: self.page.creator.rotate_reference(ref_id, degrees))

    def flip(self) -> None:
        ref_id = self.current_id()
        if ref_id:
            self.update_field("flip", not self.page.creator.reference(ref_id).get("flip", False))

    def reset_crop(self) -> None:
        self.page.set_board_mode("view")
        self.update_field("crop", [0.0, 0.0, 1.0, 1.0])

    def remove(self) -> None:
        ids = self.selected_ids() or ([self.current_id()] if self.current_id() else [])
        if not ids:
            return

        def action() -> None:
            stack = self.page.session.stack
            stack.begin("Références supprimées")
            try:
                for ref_id in ids:
                    self.page.creator.remove_reference(ref_id)
            finally:
                stack.commit()

        self.page.run("Suppression", action)

    def move(self, offset: int) -> None:
        ref_id = self.current_id()
        if ref_id:
            self.page.run("Ordre", lambda: self.page.creator.move_reference(ref_id, offset))

    def remove_note(self) -> None:
        ref_id, item = self.current_id(), self.notes.currentItem()
        if ref_id and item:
            note_id = item.data(ID_ROLE)
            self.page.run("Annotation", lambda: self.page.creator.remove_annotation(ref_id, note_id))

    def rect_drawn(self, mode: str, rect: list[float]) -> None:
        ref_id = self.current_id()
        if ref_id is None:
            return
        if mode == "crop":  # tracé relatif à l'image non recadrée (affichée en mode recadrage)
            self.page.set_board_mode("view")
            self.update_field("crop", [round(v, 4) for v in rect])
            return
        kind, text = self.note_kind.currentData(), self.note_text.text().strip()
        self.page.run("Annotation", lambda: self.page.creator.add_annotation(ref_id, kind, rect, text))

    def compare(self) -> None:
        ids = self.selected_ids()
        creator = self.page.creator
        if creator is None or len(ids) != 2:
            self.page.notify("Comparaison", "Sélectionnez exactement deux références (Ctrl + clic).", "info")
            return
        a, b = (creator.reference(i) for i in ids)
        self.page.set_view_mode("refs")
        self.page.board.set_compare(
            creator.prepared(a, 1024), creator.prepared(b, 1024), (a["name"], b["name"])
        )


# --- Analyse --------------------------------------------------------------------------------------

FIELD_LABELS = {
    "type": "Type de véhicule",
    "length_m": "Longueur (m)",
    "height_m": "Hauteur (m)",
    "width_m": "Largeur (m)",
    "wheelbase_m": "Empattement (m)",
    "wheel_diameter_m": "Diamètre des roues (m)",
    "wheels_visible": "Roues visibles (profil)",
    "ground_clearance_m": "Garde au sol (m)",
    "aspect_lh": "Rapport longueur / hauteur",
    "roof_profile": "Profil (capot / milieu / arrière / toit plat)",
    "glass_ratio": "Part vitrée (haut de caisse)",
    "lights_front": "Optiques avant détectées",
    "lights_back": "Feux arrière détectés",
    "body_color": "Couleur de carrosserie",
    "distinctive": "Éléments distinctifs (annotations)",
}
EDITABLE_NUMBERS = {
    "length_m",
    "height_m",
    "width_m",
    "wheelbase_m",
    "wheel_diameter_m",
    "ground_clearance_m",
}


def format_value(key: str, entry: dict, report: dict) -> str:
    value = entry.get("value")
    if key == "type":
        text = vision.VEHICLE_TYPES.get(value, str(value))
        others = (vision.value(report, "type_candidates", []) or [])[1:]
        if others:
            text += (
                "  (puis " + ", ".join(vision.VEHICLE_TYPES.get(c["type"], c["type"]) for c in others) + ")"
            )
    elif isinstance(value, dict):
        text = " / ".join(str(v) for v in value.values())
    elif isinstance(value, list):
        text = "; ".join(str(v) for v in value) or "—"
    elif isinstance(value, float):
        text = f"{value:g}"
    else:
        text = str(value)
    return ("≈ " + text) if entry.get("approx") else text


class AnalysisPanel(Page):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        run = self.section(
            "Vehicle Vision Analyzer", "Analyse algorithmique locale : mesures approximatives, modifiables."
        )
        layout = form()
        self.known_length = spin(0.0, 0.0, 30.0, 0.05, 2, " m")
        self.known_length.setSpecialValueText("inconnue")
        tooltip(
            self.known_length,
            "Cote connue : les autres mesures en sont déduites (sinon longueur typique du type)",
        )
        layout.addRow("Longueur connue", self.known_length)
        run.body.addLayout(layout)
        run.row(
            button(
                "Analyser",
                "scan",
                self.page.analyze,
                "Détourage, proportions, roues, couleurs, cohérence",
                "primary",
            ),
            button(
                "Analyse cloud…",
                "lsf-cloud",
                self.page.cloud_analysis,
                "Claude (Anthropic), après confirmation",
            ),
        )
        self.method = wrap_label("", "faint")
        run.body.addWidget(self.method)
        report = self.section(
            "Rapport", "≈ : valeur estimée. Double-clic : corriger (la valeur devient « utilisateur »)."
        )
        self.type_select = LSSelect([(text, key) for key, text in vision.VEHICLE_TYPES.items()])
        self.type_select.activated.connect(lambda _i: self.set_type())
        report.row(label("Type", "muted"), self.type_select, stretch=True)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Mesure", "Valeur", "Source"])
        self.tree.setRootIsDecorated(False)
        self.tree.setMinimumHeight(260)
        self.tree.itemDoubleClicked.connect(self.edit_item)
        report.body.addWidget(self.tree)
        self.colors = QHBoxLayout()
        report.body.addLayout(self.colors)
        warnings = self.section("Incohérences et avertissements")
        self.warnings = wrap_label("", "muted")
        warnings.body.addWidget(self.warnings)
        cloud = self.section("Analyse cloud", "Résultat distinct de l'analyse locale.")
        self.cloud = wrap_label("Aucune analyse cloud.", "faint")
        cloud.body.addWidget(self.cloud)
        self.finish()

    def known(self) -> float | None:
        value = self.known_length.value()
        return value if value > 0 else None

    def refresh(self) -> None:
        creator = self.page.creator
        report = creator.document().get("analysis") if creator else None
        clear_items(self.tree)
        while self.colors.count():
            item = self.colors.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not report:
            self.method.setText("Aucune analyse : importez des références puis cliquez sur « Analyser ».")
            self.warnings.setText("")
            self.cloud.setText("Aucune analyse cloud.")
            return
        self.method.setText(report.get("method", ""))
        self.type_select.blockSignals(True)
        self.type_select.select_data(vision.value(report, "type"))
        self.type_select.blockSignals(False)
        for key, entry in report.get("fields", {}).items():
            if key == "type_candidates":
                continue
            item = QTreeWidgetItem(
                [FIELD_LABELS.get(key, key), format_value(key, entry, report), entry.get("source", "")]
            )
            item.setData(0, ID_ROLE, key)
            item.setToolTip(1, f"Confiance : {entry.get('confidence', 0):.0%}")
            self.tree.addTopLevelItem(item)
        for column in range(3):
            self.tree.resizeColumnToContents(column)
        for color in report.get("colors", [])[:5]:
            swatch = QLabel()
            swatch.setFixedSize(26, 18)
            swatch.setStyleSheet(
                f"background: {color['hex']}; border-radius: 4px;"
            )  # couleur mesurée (donnée)
            tooltip(swatch, f"{color['hex']} — {color['share']:.0%}")
            self.colors.addWidget(swatch)
        self.colors.addStretch(1)
        warnings = report.get("warnings", [])
        self.warnings.setText(
            "\n".join(f"⚠ {w}" for w in warnings) or "Aucune incohérence détectée entre les vues."
        )
        cloud = report.get("cloud")
        if cloud:
            lines = [
                f"{cloud.get('engine')} ({cloud.get('model')}), {cloud.get('at')} — "
                f"coût communiqué : {cloud.get('cost') or 'non communiqué'}"
            ]
            for key, value in cloud.get("result", {}).items():
                shown = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
                lines.append(f"• {key} : {shown}")
            self.cloud.setText("\n".join(lines))
        else:
            self.cloud.setText("Aucune analyse cloud.")

    def set_type(self) -> None:
        value = self.type_select.currentData()
        self.page.run("Rapport", lambda: self.page.creator.set_analysis_field("type", value))

    def edit_item(self, item: QTreeWidgetItem) -> None:
        key = item.data(0, ID_ROLE)
        creator = self.page.creator
        if creator is None or key not in EDITABLE_NUMBERS:
            return
        current = vision.value(creator.document().get("analysis"), key, 0.0) or 0.0
        value, ok = QInputDialog.getDouble(
            self, "Corriger la mesure", FIELD_LABELS.get(key, key), float(current), 0.0, 50.0, 2
        )
        if ok:
            self.page.run("Rapport", lambda: creator.set_analysis_field(key, round(value, 3)))


# --- Lore Friendly --------------------------------------------------------------------------------


class LorePanel(Page):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        intro = self.section(
            "Lore Friendly AI Assistant", "Concevoir un véhicule original cohérent avec l'univers de GTA V."
        )
        intro.row(
            button(
                "Proposer",
                "sparkles",
                self.page.lore_proposals,
                "Trois directions : légère, équilibrée, originale",
                "primary",
            ),
            button(
                "Suggestions cloud…",
                "lsf-cloud",
                self.page.cloud_lore,
                "Claude (Anthropic), après confirmation",
            ),
        )
        intro.body.addWidget(wrap_label(lore.DISCLAIMER, "faint"))
        logos = self.section(
            "Logos réels", "Aucune reconnaissance automatique locale : marquez-les par annotation."
        )
        self.logos = wrap_label("", "muted")
        logos.body.addWidget(self.logos)
        proposals = self.section("Propositions")
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.setMinimumHeight(180)
        self.list.currentRowChanged.connect(lambda _r: self.show_proposal())
        proposals.body.addWidget(self.list)
        self.details = wrap_label("", "muted")
        proposals.body.addWidget(self.details)
        choice = form()
        self.brand = LSInput("Marque fictive")
        self.model_name = LSInput("Nom du modèle")
        choice.addRow("Marque", self.brand)
        choice.addRow("Modèle", self.model_name)
        proposals.body.addLayout(choice)
        proposals.row(button("Retenir cette proposition", "check", self.select, "Enregistrée dans le projet"))
        self.selected = wrap_label("", "faint")
        proposals.body.addWidget(self.selected)
        adjust = self.section(
            "Ajustements géométriques", "Appliqués au maillage sélectionné, sur confirmation (annulables)."
        )
        self.adjust_kind = LSSelect([(text, key) for key, text in lore.ADJUSTMENT_LABELS.items()])
        self.adjust_amount = spin(0.05, -0.3, 0.3, 0.01, 2)
        adjust.row(self.adjust_kind, self.adjust_amount)
        adjust.row(button("Appliquer à la sélection", "move-3d", self.apply_adjustment))
        provenance = self.section("Provenance et licences")
        self.provenance = wrap_label("", "faint")
        provenance.body.addWidget(self.provenance)
        provenance.row(button("Copier le rapport", "copy", self.copy_provenance))
        self.finish()

    def proposals(self) -> list[dict]:
        creator = self.page.creator
        return creator.document()["lore"].get("proposals", []) if creator else []

    def refresh(self) -> None:
        creator = self.page.creator
        row = self.list.currentRow()
        self.list.blockSignals(True)
        clear_items(self.list)
        for proposal in self.proposals():
            text = (
                f"{proposal['label']} — {proposal['brand']} {proposal['model_name']}\n{proposal['direction']}"
            )
            self.list.addItem(QListWidgetItem(text))
        self.list.blockSignals(False)
        if self.list.count():
            self.list.setCurrentRow(max(0, min(row, self.list.count() - 1)))
        self.show_proposal()
        if creator is None:
            self.logos.setText("")
            self.provenance.setText("")
            self.selected.setText("")
            return
        doc = creator.document()
        marked = sum(
            1 for r in doc["references"] for n in r.get("annotations", []) if n.get("kind") == "logo"
        )
        cloud = ((doc.get("analysis") or {}).get("cloud") or {}).get("result", {}).get("real_brands") or []
        text = f"{marked} logo(s) marqué(s) sur les références (masqués avant génération et projection)."
        if cloud:
            text += f"\nMarques signalées par l'analyse cloud : {', '.join(map(str, cloud))}."
        self.logos.setText(text)
        selected = doc["lore"].get("selected")
        self.selected.setText(
            f"Retenu : {selected['brand']} {selected['model_name']} ({selected['label']})"
            if selected
            else "Aucune proposition retenue."
        )
        prov = creator.provenance()
        lines = [
            f"• {r['name']} — source : {r['source']} ; licence : {r['license']}" for r in prov["references"]
        ]
        if prov["missing_licenses"]:
            lines.append(f"⚠ Licence non renseignée : {', '.join(prov['missing_licenses'])}")
        lines += [f"• Génération : {g['engine']} ({g['date']})" for g in prov["generations"]]
        self.provenance.setText("\n".join(lines) or "Aucune référence.")

    def show_proposal(self) -> None:
        proposals = self.proposals()
        row = self.list.currentRow()
        if not 0 <= row < len(proposals):
            self.details.setText("")
            return
        p = proposals[row]
        self.brand.setText(p["brand"])
        self.model_name.setText(p["model_name"])
        adjustments = ", ".join(
            f"{lore.ADJUSTMENT_LABELS[a['kind']]} {a['amount']:+.0%}" for a in p.get("adjustments", [])
        )
        self.details.setText(
            f"Calandre : {p['grille']}\nOptiques : {p['lights']}\nCarrosserie : {p['body']}\n"
            + "\n".join(f"• {d}" for d in p.get("details", []))
            + f"\nAjustements proposés : {adjustments or '—'}\nSource : {p.get('source', '')}"
        )
        if p.get("adjustments"):
            self.adjust_kind.select_data(p["adjustments"][0]["kind"])
            self.adjust_amount.setValue(p["adjustments"][0]["amount"])

    def select(self) -> None:
        row = self.list.currentRow()
        if row < 0:
            return
        overrides = {"brand": self.brand.text().strip(), "model_name": self.model_name.text().strip()}
        self.page.run("Lore Friendly", lambda: self.page.creator.select_proposal(row, overrides))

    def apply_adjustment(self) -> None:
        self.page.apply_adjustment(self.adjust_kind.currentData(), self.adjust_amount.value())

    def copy_provenance(self) -> None:
        if self.page.creator is not None:
            QApplication.clipboard().setText(
                json.dumps(self.page.creator.provenance(), ensure_ascii=False, indent=2)
            )
            self.page.notify("Provenance", "Rapport copié dans le presse-papiers.", "success")


# --- Génération -----------------------------------------------------------------------------------

MODES = (("Automatique", "auto"), ("Local uniquement", "local"), ("Cloud uniquement", "cloud"))


class GenerationPanel(Page):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        self.decision = None
        engine = self.section(
            "Moteur", "Auto AI Routing : proposition fondée sur les moteurs disponibles, le PC et les vues."
        )
        layout = form()
        self.mode = LSSelect(MODES)
        self.mode.currentIndexChanged.connect(lambda _i: self.update_routing())
        layout.addRow("Mode", self.mode)
        self.engine = LSSelect([("Automatique (recommandé)", "auto")])
        self.engine.currentIndexChanged.connect(lambda _i: self.update_routing())
        layout.addRow("Moteur", self.engine)
        self.profile = LSSelect([(text, key) for key, text in PROFILE_LABELS.items()])
        self.profile.select_data("balanced")
        self.profile.currentIndexChanged.connect(lambda _i: self.update_routing())
        layout.addRow("Profil", self.profile)
        self.length = spin(0.0, 0.0, 30.0, 0.05, 2, " m")
        self.length.setSpecialValueText("selon l'analyse")
        tooltip(self.length, "Longueur visée du modèle (mise à l'échelle des moteurs non métriques)")
        layout.addRow("Longueur", self.length)
        self.prompt = LSInput("Consigne (ComfyUI, cloud)")
        layout.addRow("Consigne", self.prompt)
        engine.body.addLayout(layout)
        engine.row(
            button("Détecter les moteurs", "refresh-cw", self.page.detect_engines),
            button("Moteurs…", "settings", self.page.open_engines),
        )
        self.routing = wrap_label("", "muted")
        engine.body.addWidget(self.routing)
        self.cost = wrap_label("", "faint")
        engine.body.addWidget(self.cost)
        consent = self.section("Confirmation", "Aucune image ne quitte le PC sans votre accord explicite.")
        self.allow_cloud = check("J'autorise l'envoi des images au fournisseur choisi")
        self.allow_paid = check("J'accepte le coût estimé de l'opération")
        consent.body.addWidget(self.allow_cloud)
        consent.body.addWidget(self.allow_paid)
        run = self.section("Génération", "Images → Analyse → Reconstruction → Modèle 3D → Inspection")
        self.generate_button = button(
            "Générer", "sparkles", self.page.generate, "Lancer la génération (file de tâches)", "primary"
        )
        run.row(self.generate_button, button("Annuler", "x", self.page.cancel_generation))
        self.progress = LSProgress()
        run.body.addWidget(self.progress)
        self.result = wrap_label("", "muted")
        run.body.addWidget(self.result)
        run.body.addWidget(
            wrap_label(
                "Un maillage généré n'est pas un véhicule GTA V / FiveM fonctionnel : hiérarchie, matériaux, "
                "collisions, LOD et export restent à préparer.",
                "faint",
            )
        )
        self.finish()

    def refresh(self) -> None:
        manager = self.page.manager
        current = self.engine.currentData()
        self.engine.blockSignals(True)
        self.engine.clear()
        self.engine.addItem("Automatique (recommandé)", "auto")
        for engine_id, adapter in manager.adapters.items():
            if adapter.info.supports(Capability.IMAGE_TO_3D) or adapter.info.supports(
                Capability.MULTIVIEW_3D
            ):
                status = manager.availability.get(engine_id)
                suffix = f" — {status.status.label}" if status else ""
                self.engine.addItem(f"{adapter.info.name}{suffix}", engine_id)
        self.engine.select_data(current or "auto")
        self.engine.blockSignals(False)
        self.update_routing()

    def views(self) -> list[str]:
        creator = self.page.creator
        return [r["view"] for r in creator.references()] if creator else []

    def capability(self) -> Capability:
        ortho = set(self.views()) & {"left", "right", "front", "back", "top"}
        return Capability.MULTIVIEW_3D if len(ortho) >= 2 else Capability.IMAGE_TO_3D

    def chosen_engine(self) -> str | None:
        data = self.engine.currentData()
        if data and data != "auto":
            return data
        return self.decision.chosen if self.decision else None

    def update_routing(self) -> None:
        views, quality, mode = self.views(), self.profile.currentData(), self.mode.currentData()
        decision = self.page.manager.route(
            RoutingRequest(self.capability(), views, quality=quality, mode=mode)
        )
        if decision.chosen is None and self.capability() is Capability.MULTIVIEW_3D:
            decision = self.page.manager.route(
                RoutingRequest(Capability.IMAGE_TO_3D, views, quality=quality, mode=mode)
            )
        self.decision = decision
        chosen = self.chosen_engine()
        lines = list(decision.explanation)
        if self.engine.currentData() not in (None, "auto") and chosen:
            lines.insert(0, f"Choix manuel : {self.page.manager.adapters[chosen].info.name}.")
        self.routing.setText("\n".join(lines))
        if chosen:
            adapter = self.page.manager.adapters[chosen]
            estimate = adapter.estimate(GenerationRequest(self.capability(), [], Path("."), quality))
            self.cost.setText(
                f"{adapter.info.method_label} · {adapter.info.kind} · coût : {estimate.describe()}\n"
                f"Vérification : {adapter.info.verification}"
            )
            self.allow_cloud.setEnabled(adapter.info.kind == "cloud")
            self.allow_paid.setEnabled(estimate.paid)
        else:
            self.cost.setText("")
            self.allow_cloud.setEnabled(False)
            self.allow_paid.setEnabled(False)


# --- Assistant maillage ---------------------------------------------------------------------------


class MeshPanel(Page):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        self.report: dict | None = None
        target = self.section(
            "AI Mesh Assistant", "Maillage ciblé : sélection du viewport (ou dernier modèle généré)."
        )
        self.target = label("Aucun maillage.", "muted")
        target.body.addWidget(self.target)
        target.row(button("Analyser", "scan", self.analyze, "Diagnostics automatiques", "primary"))
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumHeight(240)
        self.tree.setWordWrap(True)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        target.body.addWidget(self.tree)
        fixes = self.section("Corrections", "Déterministes et annulables ; « ⚠ » : confirmation demandée.")
        for key, text in mesh_assist.FIXES.items():
            short = text.split(" (")[0]  # libellé complet en info-bulle (panneau étroit)
            caption = ("⚠ " if key in mesh_assist.CONFIRM_FIXES else "") + short
            fixes.body.addWidget(button(caption, "lsf-mesh", lambda k=key: self.page.apply_fix(k), text))
        options = form()
        self.target_tris = int_spin(50000, 500, 2_000_000)
        self.target_tris.setSingleStep(5000)
        options.addRow("Simplifier vers", self.target_tris)
        self.iterations = int_spin(4, 1, 30)
        options.addRow("Lissage (itérations)", self.iterations)
        self.keep_positive = check("Symétrie : garder le côté droit (+X)", True)
        options.addRow("", self.keep_positive)
        fixes.body.addLayout(options)
        place = self.section("Placement du modèle", "Orientation et échelle (transformations annulables).")
        place.row(
            button(
                "Retourner 180°", "rotate-3d", lambda: self.page.turn_model(180), "Inverser avant / arrière"
            ),
            button("Quart de tour", "rotate-3d", lambda: self.page.turn_model(90)),
        )
        place.row(
            button(
                "Recaler sur les proportions mesurées",
                "scale-3d",
                self.page.fit_to_analysis,
                "Largeur et hauteur de l'analyse (échelle non uniforme)",
            )
        )
        self.finish()

    def options(self, key: str) -> dict:
        if key not in ("decimate", "smooth", "symmetrize"):
            return {}
        return {
            "target": self.target_tris.value(),
            "iterations": self.iterations.value(),
            "keep_positive": self.keep_positive.isChecked(),
        }

    def refresh(self) -> None:
        node = self.page.target_mesh()
        if node is None:
            self.target.setText("Aucun maillage sélectionné.")
            return
        mesh = self.page.session.geometry_for(node)
        self.target.setText(f"{node.name} ({mesh.triangle_count} triangles)")

    def analyze(self) -> dict | None:
        node = self.page.target_mesh()
        if node is None:
            self.page.notify("Maillage", "Sélectionnez un maillage (ou générez un modèle).", "info")
            return None
        report = self.page.run("Analyse du maillage", lambda: self.page.creator.analyze_mesh(node.id))
        if report:
            self.show_report(report)
        return report

    def show_report(self, report: dict) -> None:
        self.report = report
        clear_items(self.tree)
        severity_icons = {"info": "info", "warning": "triangle-alert", "error": "circle-x"}
        for category, title in mesh_assist.CATEGORY_LABELS.items():
            parent = QTreeWidgetItem([title])
            parent.setIcon(0, icon("layers", C.ELECTRIC))
            for issue in (i for i in report.get("issues", []) if i["category"] == category):
                child = QTreeWidgetItem([issue["text"]])
                child.setIcon(0, icon(severity_icons.get(issue["severity"], "info"), C.TEXT_SECONDARY))
                child.setData(0, ID_ROLE, issue.get("fix"))
                child.setToolTip(0, issue["text"])
                parent.addChild(child)
            self.tree.addTopLevelItem(parent)
            parent.setExpanded(True)


# --- Textures -------------------------------------------------------------------------------------

MAP_NAMES = {
    "base_color": "Couleur de base",
    "normal": "Normal map",
    "roughness": "Roughness",
    "metallic": "Metallic",
}


class TexturePanel(Page):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        params = self.section(
            "AI Texture Creator", "Méthodes locales ; l'origine de chaque carte est indiquée."
        )
        layout = form()
        self.method = LSSelect(
            [("Projection des références", "projection"), ("Couleurs du maillage", "vertex")]
        )
        self.size = LSSelect([("512 px", 512), ("1024 px", 1024), ("2048 px", 2048)])
        self.size.select_data(1024)
        self.preset = LSSelect([(p["label"], k) for k, p in tex.PRESETS.items()])
        layout.addRow("Couleur de base", self.method)
        layout.addRow("Résolution", self.size)
        layout.addRow("Matériau", self.preset)
        params.body.addLayout(layout)
        params.row(
            button(
                "Générer les textures",
                "palette",
                self.page.generate_textures,
                "Tâche en arrière-plan",
                "primary",
            )
        )
        self.maps = QGridLayout()
        params.body.addLayout(self.maps)
        self.sources = wrap_label("", "faint")
        params.body.addWidget(self.sources)
        params.row(
            button(
                "Appliquer au modèle",
                "check",
                self.page.apply_textures,
                "Matériau créé et affecté (annulable)",
            ),
            button(
                "Livery Studio",
                "paint-bucket",
                self.page.open_livery,
                "Utiliser la texture comme base de livrée",
            ),
        )
        variants = self.section("Variations", "Teinte de la couleur dominante (carrosserie).")
        self.hue = spin(0.5, 0.0, 1.0, 0.05, 2)
        variants.row(label("Décalage de teinte", "muted"), self.hue)
        variants.row(button("Créer une variante", "copy-plus", self.page.texture_variant))
        self.finish()

    def show_outcome(self, outcome) -> None:  # type: ignore[no-untyped-def]
        from PIL import Image

        while self.maps.count():
            item = self.maps.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if outcome is None:
            self.sources.setText("")
            return
        for index, (role, array) in enumerate(outcome.maps.items()):
            holder = QWidget()
            cell = QVBoxLayout(holder)
            cell.setContentsMargins(0, 0, 0, 0)
            picture = QLabel()
            picture.setPixmap(pixmap_from_image(Image.fromarray(array), 92))
            cell.addWidget(picture)
            cell.addWidget(label(MAP_NAMES.get(role, role), "faint"))
            self.maps.addWidget(holder, index // 2, index % 2)
        lines = [
            f"• {MAP_NAMES[r]} : {tex.MAP_SOURCES[s]}" for r, s in outcome.sources.items() if r in MAP_NAMES
        ]
        lines.append(f"• Ambient occlusion : {tex.MAP_SOURCES[outcome.sources.get('ao', 'none')]}")
        stats = outcome.stats
        if "projected_ratio" in stats:
            lines.append(
                f"Texels projetés : {stats['projected_ratio']:.0%} "
                f"(vues : {', '.join(stats.get('views', []))})"
            )
        self.sources.setText("\n".join(lines))


# --- Historique des générations -------------------------------------------------------------------

STATUS_TEXT = {"succeeded": "Réussie", "failed": "Échec", "cancelled": "Annulée", "timeout": "Délai dépassé"}


class GenerationsPanel(Page):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        history = self.section(
            "Historique des générations", "Coûts : uniquement ceux communiqués par le fournisseur."
        )
        self.list = QListWidget()
        self.list.setIconSize(QSize(72, 72))
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setMinimumHeight(260)
        self.list.currentItemChanged.connect(lambda *_: self.show_details())
        history.body.addWidget(self.list)
        history.row(
            button("Réouvrir", "folder-open", self.reopen, "Sélectionner ou réimporter le résultat"),
            button("Dupliquer", "copy", self.duplicate),
        )
        history.row(
            button("Réutiliser les paramètres", "refresh-cw", self.reuse),
            button("Comparer", "lsf-split", self.compare, "Deux générations (Ctrl + clic)"),
        )
        history.row(button("Supprimer", "trash-2", self.delete))
        self.details = wrap_label("", "muted")
        history.body.addWidget(self.details)
        self.finish()

    def selected_ids(self) -> list[str]:
        return [item.data(ID_ROLE) for item in self.list.selectedItems()]

    def current_id(self) -> str | None:
        item = self.list.currentItem()
        return item.data(ID_ROLE) if item else None

    def refresh(self) -> None:
        creator = self.page.creator
        current = self.current_id()
        self.list.blockSignals(True)
        clear_items(self.list)
        for record in reversed(creator.records() if creator else []):
            status = STATUS_TEXT.get(record["status"], record["status"])
            duration = f"{record['duration_s']:.1f} s" if record.get("duration_s") else "—"
            when = str(record.get("created_at", ""))[:16].replace("T", " ")
            item = QListWidgetItem(f"{record['engine_name']} · {status}\n{when} UTC · {duration}")
            item.setData(ID_ROLE, record["id"])
            pixmap = pixmap_from_png(creator.thumbnail(record), 72)
            item.setIcon(QIcon(pixmap) if not pixmap.isNull() else icon("triangle-alert", C.WARNING))
            self.list.addItem(item)
            if record["id"] == current:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        self.show_details()

    def show_details(self) -> None:
        creator, record_id = self.page.creator, self.current_id()
        if creator is None or record_id is None:
            self.details.setText("Aucune génération.")
            return
        r = creator.record(record_id)
        method = "IA (réseau de neurones)" if r.get("method") == "neural" else "algorithme déterministe"
        views = ", ".join(refs_mod.VIEWS.get(v, v) for v in r.get("views_used", [])) or "—"
        lines = [
            f"Moteur : {r['engine_name']} ({r.get('engine_version', '')}) — {method}",
            f"Profil : {PROFILE_LABELS.get(r.get('profile'), r.get('profile'))} · "
            f"statut : {STATUS_TEXT.get(r['status'], r['status'])}",
            f"Vues exploitées : {views}",
            f"Coût estimé : {r.get('estimated_cost') or '—'} · "
            f"communiqué : {r.get('reported_cost') or 'non communiqué'}",
        ]
        if r.get("triangles"):
            lines.append(
                f"Triangles : {r['triangles']}" + (" (résultat du cache)" if r.get("cached") else "")
            )
        if r.get("prompt"):
            lines.append(f"Consigne : {r['prompt']}")
        if r.get("error"):
            lines.append(f"Erreur : {r['error']}")
        lines += [f"⚠ {w}" for w in r.get("warnings", [])]
        self.details.setText("\n".join(lines))

    def reopen(self) -> None:
        record_id = self.current_id()
        if record_id and self.page.run("Réouverture", lambda: self.page.creator.reopen(record_id)):
            self.page.frame_model()

    def duplicate(self) -> None:
        record_id = self.current_id()
        if record_id:
            self.page.run("Duplication", lambda: self.page.creator.duplicate(record_id))

    def reuse(self) -> None:
        record_id = self.current_id()
        if record_id:
            settings = self.page.run("Paramètres", lambda: self.page.creator.reuse_parameters(record_id))
            if settings:
                self.page.apply_settings(settings)

    def delete(self) -> None:
        record_id = self.current_id()
        if record_id is None:
            return
        answer = QMessageBox.question(
            self,
            "Supprimer la génération",
            "Retirer cette génération de l'historique ?\n"
            "Oui : retirer aussi le modèle de la scène · Non : garder le modèle",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return
        remove = answer == QMessageBox.StandardButton.Yes
        self.page.run("Historique", lambda: self.page.creator.delete_record(record_id, remove))

    def compare(self) -> QDialog | None:
        ids = self.selected_ids()
        if len(ids) != 2 or self.page.creator is None:
            self.page.notify("Comparaison", "Sélectionnez exactement deux générations (Ctrl + clic).", "info")
            return None
        dialog = CompareDialog(self.page.creator, ids, self.page.creator.compare(*ids), self)
        dialog.open()
        return dialog


class CompareDialog(QDialog):
    def __init__(self, creator, ids, rows, parent=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.setWindowTitle("Comparer deux générations")
        layout = QVBoxLayout(self)
        pictures = QHBoxLayout()
        for record_id in ids:
            picture = QLabel()
            picture.setPixmap(pixmap_from_png(creator.thumbnail(creator.record(record_id)), 180))
            pictures.addWidget(picture)
        layout.addLayout(pictures)
        self.table = QTableWidget(len(rows), 3)
        self.table.setHorizontalHeaderLabels(["", "A", "B"])
        self.table.verticalHeader().setVisible(False)
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(640, 520)


# --- Bas de page : tâches, journal, matériel ------------------------------------------------------


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
        row.addWidget(button("Annuler la tâche", "x", self.cancel))
        row.addWidget(button("Effacer les tâches terminées", "trash-2", self.clear))
        row.addStretch(1)
        layout.addLayout(row)

    def refresh(self) -> None:
        item = self.list.currentItem()
        current = item.data(ID_ROLE) if item else None
        clear_items(self.list)
        active = None
        jobs = list(self.page.manager.queue.jobs)
        for job in reversed(jobs):
            duration = f" · {job.duration:.1f} s" if job.duration else ""
            status = STATUS_LABELS.get(job.status, job.status)
            text = f"{job.label} — {status} ({int(job.progress * 100)} %){duration}"
            entry = QListWidgetItem(f"{text}\n{job.message}")
            entry.setData(ID_ROLE, job.id)
            self.list.addItem(entry)
            if job.id == current:
                self.list.setCurrentItem(entry)
            if job.active and active is None:
                active = job
        if active is not None:
            self.progress.set_progress(active.progress, f"{active.label} : {active.message}")
        elif jobs:
            last = jobs[-1]
            self.progress.set_progress(
                1.0 if last.status == "succeeded" else last.progress, f"{last.label} : {last.message}"
            )
        else:
            self.progress.reset("Aucune tâche.")

    def cancel(self) -> None:
        item = self.list.currentItem()
        job_id = item.data(ID_ROLE) if item else None
        if job_id is None:
            active = self.page.manager.queue.active()
            job_id = active[0].id if active else None
        if job_id:
            self.page.manager.queue.cancel(job_id)

    def clear(self) -> None:
        self.page.manager.queue.clear_finished()
        self.refresh()


class LogPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.addWidget(label("Journal des tâches et des requêtes réseau (sans clés ni contenus).", "faint"))
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(2000)
        layout.addWidget(self.text, 1)

    def append(self, line: str) -> None:
        self.text.appendPlainText(line)


class HardwarePanel(QWidget):
    def __init__(self, page) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.page = page
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        left = QVBoxLayout()
        left.addWidget(label("Matériel détecté", "muted"))
        self.summary = wrap_label("Détection en cours…", "faint")
        left.addWidget(self.summary)
        left.addStretch(1)
        layout.addLayout(left, 2)
        right = QVBoxLayout()
        right.addWidget(label("Moteurs IA", "muted"))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Moteur", "Type", "Méthode", "Statut", "Vérification"])
        self.table.verticalHeader().setVisible(False)
        right.addWidget(self.table, 1)
        self.not_integrated = wrap_label("", "faint")
        right.addWidget(self.not_integrated)
        layout.addLayout(right, 5)

    def refresh(self) -> None:
        manager = self.page.manager
        if manager.hardware is not None:
            lines = [f"{k} : {v}" for k, v in manager.hardware.summary().items()]
            deps = manager.hardware.dependencies
            if deps:
                lines.append("Dépendances : " + ", ".join(f"{k} {v}" for k, v in deps.items()))
            self.summary.setText("\n".join(lines))
        self.table.setRowCount(len(manager.adapters))
        for row, (engine_id, adapter) in enumerate(manager.adapters.items()):
            availability = manager.availability.get(engine_id)
            status = (
                f"{availability.status.label} — {availability.message}" if availability else "non détecté"
            )
            values = [
                adapter.info.name,
                adapter.info.kind,
                adapter.info.method_label,
                status,
                adapter.info.verification,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        self.table.resizeRowsToContents()
        self.not_integrated.setText(
            "Étudiés, non intégrés : " + " · ".join(f"{n['name']} — {n['reason']}" for n in NOT_INTEGRATED)
        )
