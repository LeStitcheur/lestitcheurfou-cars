"""Propriétés contextuelles : projet (rien de sélectionné) ou objet sélectionné."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from lsfcars.project.model import Transform, VehicleRole, VehicleType
from lsfcars.project.session import ProjectSession


def _format_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return iso


def _fmt_int(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _wrappable_path(path: object) -> str:
    """Ajoute des points de coupure invisibles après les séparateurs de chemin."""
    return str(path).replace("\\", "\\​").replace("/", "/​")


class Vec3Editor(QWidget):
    """Trois champs X / Y / Z."""

    value_changed = Signal()

    def __init__(
        self, minimum: float, maximum: float, step: float, decimals: int, suffix: str = ""
    ) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.spins: list[QDoubleSpinBox] = []
        for axis in "XYZ":
            spin = QDoubleSpinBox()
            spin.setRange(minimum, maximum)
            spin.setSingleStep(step)
            spin.setDecimals(decimals)
            spin.setSuffix(suffix)
            spin.setPrefix(f"{axis} ")
            spin.setKeyboardTracking(False)
            # Ne pas utiliser NoButtons : avec la feuille de style, Qt 6.12 n'affiche alors
            # plus la valeur. Les flèches sont affinées dans theme.py.
            # La taille suggérée par Qt dépend de la plage (±10 000) : on laisse le champ
            # se partager la largeur disponible.
            spin.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            spin.setMinimumWidth(64)
            spin.valueChanged.connect(self.value_changed)
            layout.addWidget(spin)
            self.spins.append(spin)

    def value(self) -> list[float]:
        return [s.value() for s in self.spins]

    def set_value(self, values: list[float]) -> None:
        for spin, v in zip(self.spins, values, strict=True):
            spin.blockSignals(True)
            spin.setValue(v)
            spin.blockSignals(False)


class PropertiesPanel(QWidget):
    project_edited = Signal()
    object_edited = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session: ProjectSession | None = None
        self._object_id: str | None = None
        self._updating = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.stack)
        outer.addWidget(scroll)

        self.empty_page = QLabel("Aucun projet ouvert.")
        self.empty_page.setObjectName("Muted")
        self.empty_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.empty_page)
        self.stack.addWidget(self._build_project_page())
        self.stack.addWidget(self._build_object_page())
        self.stack.currentChanged.connect(self._fit_current_page)
        self.set_session(None)

    def _fit_current_page(self, index: int) -> None:
        """Seule la page visible compte dans la taille minimale du panneau."""
        for i in range(self.stack.count()):
            policy = QSizePolicy.Policy.Preferred if i == index else QSizePolicy.Policy.Ignored
            self.stack.widget(i).setSizePolicy(policy, policy)
        self.stack.adjustSize()

    # --- Construction -------------------------------------------------------
    def _build_project_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        group = QGroupBox("Projet")
        form = QFormLayout(group)
        self.project_name = QLineEdit()
        self.project_name.editingFinished.connect(self._apply_project)
        self.vehicle_type = QComboBox()
        for vt in VehicleType:
            self.vehicle_type.addItem(vt.label, vt.value)
        self.vehicle_type.currentIndexChanged.connect(self._apply_project)
        self.vehicle_role = QComboBox()
        for role in VehicleRole:
            self.vehicle_role.addItem(role.label, role.value)
        self.vehicle_role.setToolTip(
            "Information de projet. Les configurations LSPD / EMS (équipements, gyrophares…) "
            "arriveront avec l'atelier dédié."
        )
        self.vehicle_role.currentIndexChanged.connect(self._apply_project)
        self.project_description = QPlainTextEdit()
        self.project_description.setPlaceholderText("Notes, inspiration, cahier des charges…")
        self.project_description.setFixedHeight(90)
        self.project_description.textChanged.connect(self._apply_description)
        form.addRow("Nom", self.project_name)
        form.addRow("Type de véhicule", self.vehicle_type)
        form.addRow("Usage", self.vehicle_role)
        form.addRow("Description", self.project_description)
        layout.addWidget(group)

        info = QGroupBox("Informations")
        info_form = QFormLayout(info)
        self.project_path = QLabel()
        self.project_path.setWordWrap(True)
        self.project_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.project_dates = QLabel()
        self.project_stats = QLabel()
        self.project_stats.setWordWrap(True)
        info_form.addRow("Fichier", self.project_path)
        info_form.addRow("Dates", self.project_dates)
        info_form.addRow("Scène", self.project_stats)
        layout.addWidget(info)
        hint = QLabel(
            "Sélectionnez un objet pour modifier sa position, sa rotation ou son échelle."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _build_object_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        group = QGroupBox("Objet")
        form = QFormLayout(group)
        self.object_name = QLineEdit()
        self.object_name.editingFinished.connect(self._apply_object_name)
        self.object_visible = QCheckBox("Visible dans le viewport")
        self.object_visible.toggled.connect(self._apply_object_transform)
        self.object_source = QLabel()
        self.object_source.setWordWrap(True)
        self.object_source.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.object_stats = QLabel()
        self.object_stats.setWordWrap(True)
        self.object_warning = QLabel()
        self.object_warning.setObjectName("Warning")
        self.object_warning.setWordWrap(True)
        form.addRow("Nom", self.object_name)
        form.addRow("", self.object_visible)
        form.addRow("Fichier", self.object_source)
        form.addRow("Géométrie", self.object_stats)
        form.addRow(self.object_warning)
        layout.addWidget(group)

        tgroup = QGroupBox("Transformation")
        tform = QFormLayout(tgroup)
        self.translation = Vec3Editor(-10000, 10000, 0.1, 3, " m")
        self.rotation = Vec3Editor(-360, 360, 5, 1, "°")
        self.scale = Vec3Editor(0.001, 1000, 0.1, 3)
        self.uniform_scale = QCheckBox("Échelle uniforme")
        self.uniform_scale.setChecked(True)
        for editor in (self.translation, self.rotation):
            editor.value_changed.connect(self._apply_object_transform)
        self.scale.value_changed.connect(self._on_scale_changed)
        reset = QPushButton("Réinitialiser la transformation")
        reset.clicked.connect(self._reset_transform)
        tform.addRow("Position", self.translation)
        tform.addRow("Rotation", self.rotation)
        tform.addRow("Échelle", self.scale)
        tform.addRow("", self.uniform_scale)
        tform.addRow(reset)
        layout.addWidget(tgroup)
        layout.addStretch(1)
        return page

    # --- Affichage ----------------------------------------------------------
    def set_session(self, session: ProjectSession | None) -> None:
        self._session = session
        self.show_object(None)

    def current_object_id(self) -> str | None:
        return self._object_id

    def show_object(self, object_id: str | None) -> None:
        self._object_id = object_id
        session = self._session
        if session is None:
            self.stack.setCurrentIndex(0)
            return
        obj = session.project.find_object(object_id) if object_id else None
        self._updating = True
        if obj is None:
            self._object_id = None
            self._fill_project(session)
            self.stack.setCurrentIndex(1)
        else:
            self.object_name.setText(obj.name)
            self.object_visible.setChecked(obj.visible)
            self.object_source.setText(_wrappable_path(obj.asset_path))
            triangles, vertices = session.stats(obj.id)
            meshes = len(session.meshes.get(obj.id, []))
            self.object_stats.setText(
                f"{_fmt_int(triangles)} triangles · {_fmt_int(vertices)} sommets · "
                f"{meshes} maillage(s)"
            )
            missing = session.missing.get(obj.id)
            self.object_warning.setText(f"⚠ {missing}" if missing else "")
            self.object_warning.setVisible(bool(missing))
            self.translation.set_value(obj.transform.translation)
            self.rotation.set_value(obj.transform.rotation)
            self.scale.set_value(obj.transform.scale)
            self.stack.setCurrentIndex(2)
        self._updating = False

    def _fill_project(self, session: ProjectSession) -> None:
        project = session.project
        self.project_name.setText(project.name)
        self.vehicle_type.setCurrentIndex(self.vehicle_type.findData(project.vehicle_type.value))
        self.vehicle_role.setCurrentIndex(self.vehicle_role.findData(project.role.value))
        if self.project_description.toPlainText() != project.description:
            self.project_description.setPlainText(project.description)
        self.project_path.setText(_wrappable_path(project.file_path))
        self.project_dates.setText(
            f"Créé le {_format_date(project.created_at)}\n"
            f"Modifié le {_format_date(project.updated_at)}"
        )
        triangles, _ = session.stats()
        self.project_stats.setText(
            f"{len(project.objects)} objet(s) · {_fmt_int(triangles)} triangles"
        )

    def refresh(self) -> None:
        self.show_object(self._object_id)

    # --- Application des modifications ------------------------------------
    def _apply_project(self) -> None:
        session = self._session
        if self._updating or session is None:
            return
        project = session.project
        name = self.project_name.text().strip()
        vehicle_type = VehicleType(self.vehicle_type.currentData())
        role = VehicleRole(self.vehicle_role.currentData())
        changed = False
        if name and name != project.name:
            project.name, changed = name, True
        if vehicle_type != project.vehicle_type:
            project.vehicle_type, changed = vehicle_type, True
        if role != project.role:
            project.role, changed = role, True
        if changed:
            session.mark_dirty()
            self.project_edited.emit()

    def _apply_description(self) -> None:
        session = self._session
        if self._updating or session is None:
            return
        text = self.project_description.toPlainText()
        if text != session.project.description:
            session.project.description = text
            session.mark_dirty()
            self.project_edited.emit()

    def _apply_object_name(self) -> None:
        session, object_id = self._session, self._object_id
        if self._updating or session is None or object_id is None:
            return
        obj = session.project.find_object(object_id)
        name = self.object_name.text().strip()
        if obj and name and name != obj.name:
            session.rename_object(object_id, name)
            self.object_edited.emit(object_id)

    def _on_scale_changed(self) -> None:
        if self._updating:
            return
        session, object_id = self._session, self._object_id
        if self.uniform_scale.isChecked() and session and object_id:
            obj = session.project.find_object(object_id)
            if obj:
                new, old = self.scale.value(), obj.transform.scale
                changed = [i for i in range(3) if abs(new[i] - old[i]) > 1e-9]
                if changed:
                    self.scale.set_value([new[changed[0]]] * 3)
        self._apply_object_transform()

    def _apply_object_transform(self) -> None:
        session, object_id = self._session, self._object_id
        if self._updating or session is None or object_id is None:
            return
        transform = Transform(self.translation.value(), self.rotation.value(), self.scale.value())
        session.set_transform(object_id, transform)
        session.set_visible(object_id, self.object_visible.isChecked())
        self.object_edited.emit(object_id)

    def _reset_transform(self) -> None:
        session, object_id = self._session, self._object_id
        if session is None or object_id is None:
            return
        session.set_transform(object_id, Transform())
        self.show_object(object_id)
        self.object_edited.emit(object_id)
