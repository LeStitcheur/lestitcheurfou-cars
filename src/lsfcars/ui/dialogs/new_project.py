"""Boîte de dialogue « Nouveau projet »."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lsfcars.core.paths import default_projects_dir
from lsfcars.project.model import VehicleRole, VehicleType
from lsfcars.project.store import ProjectError, safe_folder_name


@dataclass
class NewProjectRequest:
    name: str
    parent_dir: Path
    vehicle_type: VehicleType
    role: VehicleRole
    description: str


class NewProjectDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Nouveau projet")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit("Nouveau véhicule")
        self.name_edit.selectAll()
        self.name_edit.textChanged.connect(self._validate)
        self.type_combo = QComboBox()
        for vt in VehicleType:
            self.type_combo.addItem(vt.label, vt.value)
        self.role_combo = QComboBox()
        for role in VehicleRole:
            self.role_combo.addItem(role.label, role.value)
        location_row = QHBoxLayout()
        self.location_edit = QLineEdit(str(default_projects_dir()))
        self.location_edit.textChanged.connect(self._validate)
        browse = QPushButton("Parcourir…")
        browse.clicked.connect(self._browse)
        location_row.addWidget(self.location_edit, 1)
        location_row.addWidget(browse)
        self.description_edit = QPlainTextEdit()
        self.description_edit.setPlaceholderText("Facultatif")
        self.description_edit.setFixedHeight(70)
        form.addRow("Nom du projet", self.name_edit)
        form.addRow("Type de véhicule", self.type_combo)
        form.addRow("Usage", self.role_combo)
        form.addRow("Emplacement", location_row)
        form.addRow("Description", self.description_edit)
        layout.addLayout(form)

        self.preview = QLabel()
        self.preview.setObjectName("Muted")
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Créer le projet")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuler")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._validate()

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choisir l'emplacement du projet", self.location_edit.text()
        )
        if folder:
            self.location_edit.setText(folder)

    def _validate(self) -> None:
        ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        location = self.location_edit.text().strip()
        if not location:
            self.preview.setText("Choisissez un emplacement.")
            ok_button.setEnabled(False)
            return
        try:
            folder = Path(location) / safe_folder_name(self.name_edit.text())
        except ProjectError as exc:
            self.preview.setText(str(exc))
            ok_button.setEnabled(False)
            return
        if folder.exists() and any(folder.iterdir()):
            self.preview.setText(f"⚠ Le dossier existe déjà et n'est pas vide : {folder}")
            ok_button.setEnabled(False)
        else:
            self.preview.setText(f"Le projet sera créé dans : {folder}")
            ok_button.setEnabled(True)

    def request(self) -> NewProjectRequest:
        return NewProjectRequest(
            name=self.name_edit.text().strip(),
            parent_dir=Path(self.location_edit.text().strip()),
            vehicle_type=VehicleType(self.type_combo.currentData()),
            role=VehicleRole(self.role_combo.currentData()),
            description=self.description_edit.toPlainText().strip(),
        )
