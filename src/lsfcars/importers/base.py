"""Structures communes aux importateurs (indépendantes de Qt, exécutables dans un thread)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from lsfcars.scene.mesh import MeshData
from lsfcars.scene.transform import Transform

Progress = Callable[[float, str], None]


def no_progress(_value: float, _text: str) -> None:
    return None


class ModelLoadError(Exception):
    """Le fichier n'a pas pu être chargé comme modèle 3D."""


class UnsupportedYetError(ModelLoadError):
    """Format reconnu, dont la prise en charge est prévue mais pas encore disponible."""


@dataclass
class ImportedMaterial:
    key: str
    name: str
    base_color: tuple[float, float, float, float] = (0.72, 0.74, 0.78, 1.0)
    roughness: float = 0.5
    metallic: float = 0.0
    opacity: float = 1.0
    texture_png: bytes | None = None  # texture de couleur réencodée en PNG
    texture_name: str = ""


@dataclass
class ImportedNode:
    key: str  # identifiant stable dans le fichier (nom de nœud)
    name: str
    parent_key: str | None
    transform: Transform
    mesh_key: str | None = None
    material_key: str | None = None


@dataclass
class ImportResult:
    source: Path
    format: str
    importer: str
    nodes: list[ImportedNode]  # parents avant enfants
    meshes: dict[str, MeshData]
    materials: dict[str, ImportedMaterial] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def triangle_count(self) -> int:
        return sum(m.triangle_count for m in self.meshes.values())


class Importer(Protocol):
    name: str
    extensions: dict[str, str]

    def available(self) -> tuple[bool, str]: ...

    def load(self, path: Path, progress: Progress = no_progress) -> ImportResult: ...
