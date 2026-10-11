"""Modèle de données d'un projet LeStitcheurFou Cars."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from lsfcars.scene.graph import SceneGraph
from lsfcars.scene.transform import Transform

__all__ = [
    "Asset",
    "Project",
    "Transform",
    "VehicleRole",
    "VehicleType",
    "new_id",
    "utc_now_iso",
]


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
    """Usage du véhicule (les ateliers LSPD / EMS arriveront dans une version future)."""

    CIVILIAN = "civilian"
    LSPD = "lspd"
    EMS = "ems"

    @property
    def label(self) -> str:
        return VEHICLE_ROLE_LABELS[self]


VEHICLE_ROLE_LABELS: dict[VehicleRole, str] = {
    VehicleRole.CIVILIAN: "Civil",
    VehicleRole.LSPD: "LSPD (police)",
    VehicleRole.EMS: "EMS / SAMD (secours)",
}


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class Asset:
    """Fichier importé copié dans ``assets/`` avec sa provenance."""

    rel_path: str  # relatif au dossier du projet, séparateurs « / »
    original_name: str
    source_path: str = ""
    sha256: str = ""
    format: str = ""
    size: int = 0
    imported_at: str = field(default_factory=utc_now_iso)
    importer: str = ""
    notes: list[str] = field(default_factory=list)
    id: str = field(default_factory=new_id)

    def to_row(self) -> tuple:
        return (
            self.id,
            self.rel_path,
            self.original_name,
            self.source_path,
            self.sha256,
            self.format,
            self.size,
            self.imported_at,
            self.importer,
            json.dumps(self.notes),
        )

    @classmethod
    def from_row(cls, row: tuple) -> Asset:
        (
            asset_id,
            rel_path,
            original_name,
            source_path,
            sha256,
            fmt,
            size,
            imported_at,
            importer,
            notes,
        ) = row
        try:
            note_list = json.loads(notes) if notes else []
        except json.JSONDecodeError:
            note_list = []
        return cls(
            rel_path,
            original_name,
            source_path or "",
            sha256 or "",
            fmt or "",
            int(size or 0),
            imported_at or "",
            importer or "",
            note_list,
            asset_id,
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ImportedResource:
    """Ressource FiveM / GTA V importée : provenance et manifeste versionné.

    Le manifeste décrit la ressource d'origine (fichiers, empreintes, modèles, textures,
    métadonnées, os, état de compatibilité). Les fichiers originaux ne sont jamais modifiés ;
    des copies sont rangées dans ``assets/fivem/<ressource>/``.
    """

    name: str
    source_path: str
    source_kind: str  # « dossier », « zip », « rpf », « fichier »
    manifest: dict = field(default_factory=dict)
    status: str = ""
    imported_at: str = field(default_factory=utc_now_iso)
    id: str = field(default_factory=new_id)


@dataclass
class Project:
    name: str
    vehicle_type: VehicleType = VehicleType.CAR
    role: VehicleRole = VehicleRole.CIVILIAN
    description: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    scene: SceneGraph = field(default_factory=SceneGraph)
    assets: dict[str, Asset] = field(default_factory=dict)
    camera: dict | None = None
    file_path: Path | None = None
    project_id: str = field(default_factory=new_id)
    thumbnail: bytes | None = None
    resources: dict[str, ImportedResource] = field(default_factory=dict)

    @property
    def project_dir(self) -> Path:
        if self.file_path is None:
            raise ValueError("Le projet n'a pas encore d'emplacement sur le disque.")
        return self.file_path.parent

    @property
    def assets_dir(self) -> Path:
        return self.project_dir / "assets"

    @property
    def textures_dir(self) -> Path:
        return self.assets_dir / "textures"
