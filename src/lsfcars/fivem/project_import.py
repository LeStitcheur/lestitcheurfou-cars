"""Import d'un modèle de ressource FiveM dans un projet : copies, provenance, manifeste.

Les fichiers d'origine ne sont jamais modifiés : le modèle et ses dictionnaires de textures
sont copiés dans ``assets/`` (via l'import standard), les métadonnées et fichiers associés dans
``assets/fivem/<ressource>/``, et le manifeste versionné est enregistré dans le projet.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from lsfcars.core.logging_setup import get_logger
from lsfcars.fivem.resource import ResourceAnalysis, ResourceFile, VehicleModel, build_manifest
from lsfcars.importers.base import ImportResult
from lsfcars.project.model import ImportedResource
from lsfcars.project.store import ProjectError

log = get_logger(__name__)

_UNSAFE = re.compile(r'[<>:"\\|?*\x00-\x1f]')


def safe_relative(path: str) -> Path:
    """Chemin relatif sûr (aucune remontée « .. », caractères Windows interdits remplacés)."""
    parts = [
        _UNSAFE.sub("_", part).strip(" .") or "_"
        for part in PurePosixPath(path.replace("\\", "/")).parts
        if part not in ("", ".", "..", "/")
    ]
    return Path(*parts) if parts else Path("fichier")


def files_to_copy(analysis: ResourceAnalysis, model: VehicleModel) -> list[ResourceFile]:
    model_files = {id(f) for f in (model.yft, model.yft_hi, *model.ytds) if f is not None}
    return [
        item
        for item in analysis.files
        if id(item) in model_files
        or item.extension in (".meta", ".xml")
        or item.name.lower() in ("fxmanifest.lua", "__resource.lua")
    ]


def import_into_project(session, analysis: ResourceAnalysis, model: VehicleModel, result: ImportResult):  # type: ignore[no-untyped-def]
    """Ajoute le modèle à la scène et enregistre la ressource. Retourne (racine, ressource)."""
    root_id = session.apply_import(result)
    asset_id = session.scene.nodes[root_id].asset_id or ""
    base = session.project.assets_dir / "fivem" / safe_relative(analysis.name or "ressource").name
    copies: dict[str, str] = {}
    for item in files_to_copy(analysis, model):
        target = base / safe_relative(item.path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(item.read())
        except OSError as exc:
            raise ProjectError(f"Copie de « {item.name} » impossible : {exc}") from exc
        copies[item.path] = target.relative_to(session.project.project_dir).as_posix()
    manifest = build_manifest(analysis, model, copies, asset_id)
    resource = ImportedResource(
        analysis.name, str(analysis.source), analysis.source_kind, manifest, analysis.overall.value
    )
    session.project.resources[resource.id] = resource
    session.mark_meta_dirty()
    log.info("Ressource « %s » importée (%d copies)", analysis.name, len(copies))
    return root_id, resource
