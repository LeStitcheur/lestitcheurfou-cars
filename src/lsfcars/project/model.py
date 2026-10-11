"""Modèle de données d'un projet LeStitcheurFou Cars."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import numpy as np

from lsfcars.scene import mathutils


class VehicleType(StrEnum):
    """Catégories de véhicules prévues par l'architecture."""

    CAR = "car"
    SUV = "suv"
    MOTORCYCLE = "motorcycle"
    TRUCK = "truck"
    BOAT = "boat"
    HELICOPTER = "helicopter"
    PLANE = "plane"

    @property
    def label(self) -> str:
        return VEHICLE_TYPE_LABELS[self]


VEHICLE_TYPE_LABELS: dict[VehicleType, str] = {
    VehicleType.CAR: "Voiture",
    VehicleType.SUV: "SUV / 4x4",
    VehicleType.MOTORCYCLE: "Moto",
    VehicleType.TRUCK: "Camion / utilitaire",
    VehicleType.BOAT: "Bateau",
    VehicleType.HELICOPTER: "Hélicoptère",
    VehicleType.PLANE: "Avion / aéronef",
}


class VehicleRole(StrEnum):
    """Usage du véhicule (les configurations LSPD / EMS arriveront dans une version future)."""

    CIVILIAN = "civilian"
    LSPD = "lspd"
    EMS = "ems"

    @property
    def label(self) -> str:
        return VEHICLE_ROLE_LABELS[self]


VEHICLE_ROLE_LABELS: dict[VehicleRole, str] = {
    VehicleRole.CIVILIAN: "Civil",
    VehicleRole.LSPD: "LSPD (police)",
    VehicleRole.EMS: "EMS (secours)",
}


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class Transform:
    """Transformation d'un objet : translation (m), rotation d'Euler XYZ (°), échelle."""

    translation: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotation: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    scale: list[float] = field(default_factory=lambda: [1.0, 1.0, 1.0])

    def matrix(self) -> np.ndarray:
        return mathutils.trs(self.translation, self.rotation, self.scale)

    def to_dict(self) -> dict[str, list[float]]:
        return {
            "translation": [float(v) for v in self.translation],
            "rotation": [float(v) for v in self.rotation],
            "scale": [float(v) for v in self.scale],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Transform:
        def vec(key: str, default: float) -> list[float]:
            values = data.get(key, [default] * 3)
            if not isinstance(values, list) or len(values) != 3:
                return [default] * 3
            return [float(v) for v in values]

        return cls(vec("translation", 0.0), vec("rotation", 0.0), vec("scale", 1.0))


@dataclass
class SceneObject:
    """Objet de la scène, lié à un fichier du dossier ``assets/`` du projet."""

    name: str
    asset_path: str  # chemin relatif au dossier du projet, séparateurs « / »
    transform: Transform = field(default_factory=Transform)
    visible: bool = True
    id: str = field(default_factory=new_id)


@dataclass
class Project:
    name: str
    vehicle_type: VehicleType = VehicleType.CAR
    role: VehicleRole = VehicleRole.CIVILIAN
    description: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    objects: list[SceneObject] = field(default_factory=list)
    camera: dict | None = None
    file_path: Path | None = None

    @property
    def project_dir(self) -> Path:
        if self.file_path is None:
            raise ValueError("Le projet n'a pas encore d'emplacement sur le disque.")
        return self.file_path.parent

    @property
    def assets_dir(self) -> Path:
        return self.project_dir / "assets"

    def find_object(self, object_id: str) -> SceneObject | None:
        return next((o for o in self.objects if o.id == object_id), None)
