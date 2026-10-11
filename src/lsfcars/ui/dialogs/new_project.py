"""Boîte de dialogue « Nouveau véhicule » (LSModal)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QFormLayout, QHBoxLayout, QPlainTextEdit, QWidget

from lsfcars.project.model import VehicleRole, VehicleType
from lsfcars.project.store import ProjectError, safe_folder_name
from lsfcars.ui.design.components import LSButton, LSInput, LSModal, LSSelect, label


@dataclass
class NewProjectRequest:
    name: str
    parent_dir: Path
    vehicle_type: VehicleType
    role: VehicleRole
    description: str


class NewProjectDialog(LSModal):
    def __init__(self, default_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(
            "Nouveau véhicule",
            "Un dossier de projet sera créé avec ses assets.",
            "car",
            "red",
            parent,
        )
        self.setMinimumWidth(560)
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.name_edit = LSInput()
        self.name_edit.setText("Nouveau véhicule")
        self.name_edit.selectAll()
        self.name_edit.textChanged.connect(self._validate)
        self.type_combo = LSSelect([(vt.label, vt.value) for vt in VehicleType])
        self.role_combo = LSSelect([(r.label, r.value) for r in VehicleRole])
        location = QHBoxLayout()
        self.location_edit = LSInput()
        self.location_edit.setText(str(default_dir))
        self.location_edit.textChanged.connect(self._validate)
        browse = LSButton("Parcourir…", "secondary", small=True)
        browse.clicked.connect(self._browse)
        location.addWidget(self.location_edit, 1)
        location.addWidget(browse)
        self.description_edit = QPlainTextEdit()
        self.description_edit.setPlaceholderText("Facultatif : inspiration, usage prévu…")
        self.description_edit.setFixedHeight(70)
        for title, widget in (
            ("Nom", self.name_edit),
            ("Type", self.type_combo),
            ("Usage", self.role_combo),
        ):
            form.addRow(label(title, "muted"), widget)
        form.addRow(label("Emplacement", "muted"), location)
        form.addRow(label("Description", "muted"), self.description_edit)
        self.body.addLayout(form)
        self.preview = label("", "faint", wrap=True)
        self.body.addWidget(self.preview)
        self.add_button("Annuler")
        self.create_button = self.add_button("Créer le projet", "primary", "ok", "plus", accept=True)
        self._validate()

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Emplacement du projet", self.location_edit.text())
        if folder:
            self.location_edit.setText(folder)

    def _validate(self) -> None:
        location = self.location_edit.text().strip()
        try:
            folder = Path(location) / safe_folder_name(self.name_edit.text())
        except ProjectError as exc:
            self.preview.setText(str(exc))
            self.create_button.setEnabled(False)
            return
        if not location:
            message, ok = "Choisissez un emplacement.", False
        elif folder.exists() and any(folder.iterdir()):
            message, ok = f"⚠ Le dossier existe déjà et n'est pas vide : {folder}", False
        else:
            message, ok = f"Le projet sera créé dans : {folder}", True
        self.preview.setText(message)
        self.create_button.setEnabled(ok)

    def request(self) -> NewProjectRequest:
        return NewProjectRequest(
            name=self.name_edit.text().strip(),
            parent_dir=Path(self.location_edit.text().strip()),
            vehicle_type=VehicleType(self.type_combo.currentData()),
            role=VehicleRole(self.role_combo.currentData()),
            description=self.description_edit.toPlainText().strip(),
        )
