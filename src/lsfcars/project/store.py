"""Persistance des projets dans un fichier SQLite ``.lsfc``.

Structure sur disque ::

    MonProjet/
        MonProjet.lsfc   <- base SQLite (métadonnées + scène)
        assets/          <- copies des modèles importés
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from lsfcars import APP_ID, __version__
from lsfcars.core.logging_setup import get_logger
from lsfcars.project.model import (
    Project,
    SceneObject,
    Transform,
    VehicleRole,
    VehicleType,
    utc_now_iso,
)

log = get_logger(__name__)

PROJECT_EXTENSION = ".lsfc"
FORMAT_ID = APP_ID
SCHEMA_VERSION = 1

_SCHEMA_V1 = """
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE scene_objects (
    id         TEXT PRIMARY KEY,
    position   INTEGER NOT NULL,
    name       TEXT NOT NULL,
    asset_path TEXT NOT NULL,
    transform  TEXT NOT NULL,
    visible    INTEGER NOT NULL DEFAULT 1
);
"""

# Migrations : version de départ -> script SQL amenant à la version suivante.
_MIGRATIONS: dict[int, str] = {}


class ProjectError(Exception):
    """Erreur de création, d'ouverture ou d'enregistrement d'un projet."""


_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_folder_name(name: str) -> str:
    """Nom de dossier/fichier valide sous Windows dérivé du nom du projet."""
    cleaned = _INVALID_CHARS.sub("_", name).strip().strip(".")
    if not cleaned:
        raise ProjectError("Le nom du projet est vide ou invalide.")
    return cleaned[:80]


def create_project(
    parent_dir: str | Path,
    name: str,
    vehicle_type: VehicleType = VehicleType.CAR,
    role: VehicleRole = VehicleRole.CIVILIAN,
    description: str = "",
) -> Project:
    """Crée le dossier du projet, son dossier ``assets`` et le fichier ``.lsfc``."""
    name = name.strip()
    folder = Path(parent_dir) / safe_folder_name(name)
    if folder.exists() and any(folder.iterdir()):
        raise ProjectError(f"Le dossier « {folder} » existe déjà et n'est pas vide.")
    try:
        (folder / "assets").mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ProjectError(f"Impossible de créer le dossier du projet : {exc}") from exc

    project = Project(name=name, vehicle_type=vehicle_type, role=role, description=description)
    project.file_path = folder / f"{folder.name}{PROJECT_EXTENSION}"
    save_project(project)
    log.info("Projet créé : %s", project.file_path)
    return project


def save_project(project: Project) -> Path:
    """Enregistre le projet de façon atomique (fichier temporaire puis remplacement)."""
    if project.file_path is None:
        raise ProjectError("Aucun emplacement défini pour le projet.")
    target = Path(project.file_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.unlink(missing_ok=True)

    project.updated_at = utc_now_iso()
    meta = {
        "format": FORMAT_ID,
        "schema_version": str(SCHEMA_VERSION),
        "app_version": __version__,
        "name": project.name,
        "vehicle_type": project.vehicle_type.value,
        "role": project.role.value,
        "description": project.description,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "camera": json.dumps(project.camera) if project.camera else "",
    }
    rows = [
        (o.id, i, o.name, o.asset_path, json.dumps(o.transform.to_dict()), int(o.visible))
        for i, o in enumerate(project.objects)
    ]
    try:
        with closing(sqlite3.connect(tmp)) as conn:
            conn.executescript(_SCHEMA_V1)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.executemany("INSERT INTO meta(key, value) VALUES (?, ?)", meta.items())
            conn.executemany(
                "INSERT INTO scene_objects(id, position, name, asset_path, transform, visible)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()
        os.replace(tmp, target)
    except (sqlite3.Error, OSError) as exc:
        tmp.unlink(missing_ok=True)
        raise ProjectError(f"Échec de l'enregistrement de « {target.name} » : {exc}") from exc
    log.info("Projet enregistré : %s (%d objet(s))", target, len(project.objects))
    return target


_SELECT_OBJECTS = (
    "SELECT id, name, asset_path, transform, visible FROM scene_objects ORDER BY position"
)


def _migrate(conn: sqlite3.Connection, version: int) -> int:
    while version < SCHEMA_VERSION:
        script = _MIGRATIONS.get(version)
        if script is None:
            raise ProjectError(f"Aucune migration disponible depuis la version {version}.")
        conn.executescript(script)
        version += 1
        conn.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(version),))
    return version


def load_project(path: str | Path) -> Project:
    """Ouvre un fichier ``.lsfc`` et retourne le projet (le fichier n'est jamais modifié)."""
    path = Path(path)
    if not path.is_file():
        raise ProjectError(f"Fichier projet introuvable : {path}")
    try:
        with closing(sqlite3.connect(":memory:")) as conn:
            uri = f"{path.resolve().as_uri()}?mode=ro"
            with closing(sqlite3.connect(uri, uri=True)) as src:
                src.backup(conn)
            meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
            if meta.get("format") != FORMAT_ID:
                raise ProjectError(f"« {path.name} » n'est pas un projet LeStitcheurFou Cars.")
            version = int(meta.get("schema_version", "0"))
            if version > SCHEMA_VERSION:
                raise ProjectError(
                    f"« {path.name} » a été créé avec une version plus récente du logiciel "
                    f"(schéma {version}, pris en charge : {SCHEMA_VERSION})."
                )
            if version < SCHEMA_VERSION:
                _migrate(conn, version)
                log.info(
                    "Projet migré du schéma %d vers %d : %s", version, SCHEMA_VERSION, path.name
                )
            rows = conn.execute(_SELECT_OBJECTS).fetchall()
    except (sqlite3.DatabaseError, ValueError) as exc:
        raise ProjectError(f"« {path.name} » est illisible ou corrompu : {exc}") from exc
    return _build_project(path, meta, rows)


def _build_project(path: Path, meta: dict[str, str], rows: list[tuple]) -> Project:
    try:
        vehicle_type = VehicleType(meta.get("vehicle_type", VehicleType.CAR.value))
    except ValueError:
        vehicle_type = VehicleType.CAR
    try:
        role = VehicleRole(meta.get("role", VehicleRole.CIVILIAN.value))
    except ValueError:
        role = VehicleRole.CIVILIAN
    camera = None
    if meta.get("camera"):
        try:
            camera = json.loads(meta["camera"])
        except json.JSONDecodeError:
            log.warning("État de caméra illisible dans %s, ignoré", path.name)

    objects = []
    for obj_id, name, asset_path, transform_json, visible in rows:
        try:
            transform = Transform.from_dict(json.loads(transform_json))
        except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
            log.warning("Transformation illisible pour « %s », réinitialisée", name)
            transform = Transform()
        objects.append(SceneObject(name, asset_path, transform, bool(visible), obj_id))

    project = Project(
        name=meta.get("name", path.stem),
        vehicle_type=vehicle_type,
        role=role,
        description=meta.get("description", ""),
        created_at=meta.get("created_at", utc_now_iso()),
        updated_at=meta.get("updated_at", utc_now_iso()),
        objects=objects,
        camera=camera,
        file_path=path,
    )
    log.info("Projet ouvert : %s (%d objet(s))", path, len(objects))
    return project


def _unique_destination(folder: Path, filename: str) -> Path:
    candidate = folder / filename
    stem, suffix = candidate.stem, candidate.suffix
    counter = 2
    while candidate.exists():
        candidate = folder / f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def _companion_files(source: Path) -> list[str]:
    """Fichiers externes référencés par un .gltf (buffers, textures) ou un .obj (mtllib)."""
    names: list[str] = []
    try:
        if source.suffix.lower() == ".gltf":
            data = json.loads(source.read_text(encoding="utf-8"))
            for key in ("buffers", "images"):
                for item in data.get(key, []):
                    uri = item.get("uri", "")
                    if uri and not uri.startswith("data:"):
                        names.append(uri)
        elif source.suffix.lower() == ".obj":
            with source.open(encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    if line.startswith("mtllib "):
                        names.append(line.split(maxsplit=1)[1].strip())
    except (OSError, json.JSONDecodeError, AttributeError):
        log.warning("Dépendances non analysables pour %s", source.name)
    return names


def import_asset(project: Project, source: str | Path) -> str:
    """Copie un fichier modèle dans ``assets/`` et retourne son chemin relatif au projet.

    Un modèle avec fichiers externes (.gltf + .bin, .obj + .mtl) est copié dans un
    sous-dossier dédié afin de conserver les références relatives.
    """
    source = Path(source)
    assets = project.assets_dir
    assets.mkdir(parents=True, exist_ok=True)
    companions = _companion_files(source)
    try:
        if companions:
            folder = _unique_destination(assets, source.stem)
            folder.mkdir(parents=True)
            destination = folder / source.name
            shutil.copy2(source, destination)
            base = source.parent.resolve()
            for rel in companions:
                src = (source.parent / rel).resolve()
                if src.is_file() and src.is_relative_to(base):
                    dst = folder / src.relative_to(base)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                else:
                    log.warning("Fichier référencé introuvable ou hors dossier : %s", rel)
        else:
            destination = _unique_destination(assets, source.name)
            shutil.copy2(source, destination)
    except OSError as exc:
        raise ProjectError(f"Copie du modèle impossible : {exc}") from exc
    return destination.relative_to(project.project_dir).as_posix()
