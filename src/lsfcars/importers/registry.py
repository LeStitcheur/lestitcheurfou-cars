"""Sélection de l'importateur selon l'extension ; formats GTA V / FiveM prévus."""

from __future__ import annotations

from pathlib import Path

from lsfcars.importers.base import (
    ImportResult,
    ModelLoadError,
    Progress,
    UnsupportedYetError,
    no_progress,
)
from lsfcars.importers.fbx_blender import FbxBlenderImporter
from lsfcars.importers.trimesh_importer import TrimeshImporter

IMPORTERS = (TrimeshImporter(), FbxBlenderImporter())

# Formats reconnus dont la prise en charge est prévue : aucun chargement n'est simulé.
PLANNED_FORMATS: dict[str, str] = {
    ".yft": "Modèle de véhicule GTA V (fragment)",
    ".ydr": "Modèle GTA V (drawable)",
    ".ytd": "Dictionnaire de textures GTA V",
    ".rpf": "Archive GTA V",
    ".meta": "Métadonnées de véhicule FiveM",
}


def supported_extensions() -> dict[str, str]:
    result: dict[str, str] = {}
    for importer in IMPORTERS:
        result.update(importer.extensions)
    return result


def importer_for(path: str | Path):  # type: ignore[no-untyped-def]
    ext = Path(path).suffix.lower()
    return next((i for i in IMPORTERS if ext in i.extensions), None)


def file_dialog_filter() -> str:
    formats = supported_extensions()
    patterns = " ".join(f"*{ext}" for ext in formats)
    details = ";;".join(f"{name} (*{ext})" for ext, name in formats.items())
    return f"Modèles 3D ({patterns});;{details};;Tous les fichiers (*)"


def load_model(path: str | Path, progress: Progress = no_progress) -> ImportResult:
    """Vérifie et charge un fichier 3D. Lève ModelLoadError avec un message lisible."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext in PLANNED_FORMATS:
        raise UnsupportedYetError(
            f"Le format {ext} ({PLANNED_FORMATS[ext]}) sera pris en charge dans une version "
            "future. Il n'est pas encore lisible par LeStitcheurFou Cars."
        )
    importer = importer_for(path)
    if importer is None:
        raise ModelLoadError(f"Format non pris en charge : « {ext or path.name} ».")
    if not path.is_file():
        raise ModelLoadError(f"Fichier introuvable : {path}")
    if path.stat().st_size == 0:
        raise ModelLoadError(f"Le fichier « {path.name} » est vide.")
    return importer.load(path, progress)
