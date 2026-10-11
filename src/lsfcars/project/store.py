"""Persistance des projets dans un fichier SQLite ``.lsfc`` (format version 2).

Structure sur disque ::

    MonProjet/
        MonProjet.lsfc        <- base SQLite (métadonnées, scène, matériaux, provenance)
        assets/               <- copies des modèles importés (les originaux ne sont jamais modifiés)
        assets/textures/      <- textures extraites ou choisies
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from lsfcars import APP_ID, __version__
from lsfcars.core.logging_setup import get_logger
from lsfcars.project.model import (
    Asset,
    Project,
    VehicleRole,
    VehicleType,
    new_id,
    utc_now_iso,
)
from lsfcars.scene.graph import NodeKind, SceneGraph, SceneNode
from lsfcars.scene.materials import Material
from lsfcars.scene.transform import Transform

log = get_logger(__name__)

PROJECT_EXTENSION = ".lsfc"
FORMAT_ID = APP_ID
SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE assets (
    id TEXT PRIMARY KEY, rel_path TEXT NOT NULL, original_name TEXT NOT NULL,
    source_path TEXT, sha256 TEXT, format TEXT, size INTEGER, imported_at TEXT,
    importer TEXT, notes TEXT
);
CREATE TABLE materials (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, base_color TEXT NOT NULL, roughness REAL NOT NULL,
    metallic REAL NOT NULL, opacity REAL NOT NULL, texture TEXT, double_sided INTEGER NOT NULL
);
CREATE TABLE nodes (
    id TEXT PRIMARY KEY, parent_id TEXT, position INTEGER NOT NULL, name TEXT NOT NULL,
    kind TEXT NOT NULL, transform TEXT NOT NULL, visible INTEGER NOT NULL,
    locked INTEGER NOT NULL, asset_id TEXT, mesh_key TEXT, material_id TEXT
);
CREATE TABLE thumbnail (id INTEGER PRIMARY KEY CHECK (id = 1), png BLOB NOT NULL);
"""


class ProjectError(Exception):
    """Erreur de création, d'ouverture ou d'enregistrement d'un projet."""


_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_folder_name(name: str) -> str:
    """Nom de dossier/fichier valide sous Windows dérivé du nom du projet."""
    cleaned = _INVALID_CHARS.sub("_", name).strip().strip(".")
    if not cleaned:
        raise ProjectError("Le nom du projet est vide ou invalide.")
    return cleaned[:80]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --- Création -------------------------------------------------------------------


def _prepare_folder(parent_dir: str | Path, name: str) -> Path:
    folder = Path(parent_dir) / safe_folder_name(name.strip())
    if folder.exists() and any(folder.iterdir()):
        raise ProjectError(f"Le dossier « {folder} » existe déjà et n'est pas vide.")
    try:
        (folder / "assets").mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ProjectError(f"Impossible de créer le dossier du projet : {exc}") from exc
    return folder


def create_project(
    parent_dir: str | Path,
    name: str,
    vehicle_type: VehicleType = VehicleType.CAR,
    role: VehicleRole = VehicleRole.CIVILIAN,
    description: str = "",
) -> Project:
    """Crée le dossier du projet, son dossier ``assets`` et le fichier ``.lsfc``."""
    folder = _prepare_folder(parent_dir, name)
    project = Project(
        name=name.strip(), vehicle_type=vehicle_type, role=role, description=description
    )
    project.file_path = folder / f"{folder.name}{PROJECT_EXTENSION}"
    save_project(project)
    log.info("Projet créé : %s", project.file_path)
    return project


def save_as(project: Project, parent_dir: str | Path, name: str) -> Path:
    """Copie le projet (fichier + assets) dans un nouveau dossier et bascule dessus."""
    old_dir = project.project_dir if project.file_path else None
    folder = _prepare_folder(parent_dir, name)
    if old_dir is not None and (old_dir / "assets").is_dir():
        shutil.copytree(old_dir / "assets", folder / "assets", dirs_exist_ok=True)
    project.name = name.strip()
    project.project_id = new_id()
    project.file_path = folder / f"{folder.name}{PROJECT_EXTENSION}"
    path = save_project(project)
    log.info("Projet enregistré sous : %s", path)
    return path


# --- Enregistrement ----------------------------------------------------------------


def save_project(project: Project, path: str | Path | None = None) -> Path:
    """Enregistre de façon atomique (fichier temporaire puis remplacement).

    ``path`` permet d'écrire ailleurs (sauvegarde automatique) sans changer ``file_path``.
    """
    if path is None and project.file_path is None:
        raise ProjectError("Aucun emplacement défini pour le projet.")
    target = Path(path) if path is not None else Path(project.file_path)  # type: ignore[arg-type]
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.unlink(missing_ok=True)

    if path is None:
        project.updated_at = utc_now_iso()
    meta = {
        "format": FORMAT_ID,
        "schema_version": str(SCHEMA_VERSION),
        "app_version": __version__,
        "project_id": project.project_id,
        "name": project.name,
        "vehicle_type": project.vehicle_type.value,
        "role": project.role.value,
        "description": project.description,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "camera": json.dumps(project.camera) if project.camera else "",
    }
    scene = project.scene
    node_rows = [
        (
            n.id,
            n.parent_id,
            position,
            n.name,
            n.kind.value,
            json.dumps(n.transform.to_dict()),
            int(n.visible),
            int(n.locked),
            n.asset_id,
            n.mesh_key,
            n.material_id,
        )
        for n, position in scene.ordered_nodes()
    ]
    material_rows = [
        (
            m.id,
            m.name,
            json.dumps(list(m.base_color)),
            m.roughness,
            m.metallic,
            m.opacity,
            m.texture,
            int(m.double_sided),
        )
        for m in scene.materials.values()
    ]
    try:
        with closing(sqlite3.connect(tmp)) as conn:
            conn.executescript(_SCHEMA)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.executemany("INSERT INTO meta VALUES (?, ?)", meta.items())
            conn.executemany(
                "INSERT INTO assets VALUES (?,?,?,?,?,?,?,?,?,?)",
                [a.to_row() for a in project.assets.values()],
            )
            conn.executemany("INSERT INTO materials VALUES (?,?,?,?,?,?,?,?)", material_rows)
            conn.executemany("INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?,?,?)", node_rows)
            if project.thumbnail:
                conn.execute("INSERT INTO thumbnail VALUES (1, ?)", (project.thumbnail,))
            conn.commit()
        os.replace(tmp, target)
    except (sqlite3.Error, OSError) as exc:
        tmp.unlink(missing_ok=True)
        raise ProjectError(f"Échec de l'enregistrement de « {target.name} » : {exc}") from exc
    log.info(
        "Projet enregistré : %s (%d nœuds, %d assets)", target, len(scene), len(project.assets)
    )
    return target


# --- Ouverture ----------------------------------------------------------------------


def _migrate_v1(conn: sqlite3.Connection) -> None:
    """v0.1 → v2 : chaque objet devient un asset + un nœud « modèle » (développé à l'ouverture)."""
    rows = conn.execute(
        "SELECT id, name, asset_path, transform, visible FROM scene_objects ORDER BY position"
    ).fetchall()
    new_tables = [
        s
        for s in _SCHEMA.split(";")
        if s.strip() and not s.strip().startswith("CREATE TABLE meta ")
    ]
    conn.executescript(";".join(new_tables) + ";")
    for position, (obj_id, name, asset_path, transform, visible) in enumerate(rows):
        asset = Asset(
            asset_path,
            Path(asset_path).name,
            importer="migré depuis la v0.1",
            format=Path(asset_path).suffix.lstrip("."),
        )
        conn.execute("INSERT INTO assets VALUES (?,?,?,?,?,?,?,?,?,?)", asset.to_row())
        conn.execute(
            "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                obj_id,
                None,
                position,
                name,
                NodeKind.MODEL.value,
                transform,
                visible,
                0,
                asset.id,
                None,
                None,
            ),
        )
    conn.execute("DROP TABLE scene_objects")
    conn.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")


_MIGRATIONS = {1: _migrate_v1}


def load_project(path: str | Path) -> Project:
    """Ouvre un fichier ``.lsfc`` (le fichier n'est jamais modifié à l'ouverture)."""
    path = Path(path)
    if not path.is_file():
        raise ProjectError(f"Fichier projet introuvable : {path}")
    try:
        with closing(sqlite3.connect(":memory:")) as conn:
            with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as src:
                src.backup(conn)
            meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
            if meta.get("format") != FORMAT_ID:
                raise ProjectError(f"« {path.name} » n'est pas un projet LeStitcheurFou Cars.")
            version = int(meta.get("schema_version", "0"))
            if version > SCHEMA_VERSION:
                raise ProjectError(
                    f"« {path.name} » a été créé avec une version plus récente du logiciel "
                    f"(format {version}, pris en charge : {SCHEMA_VERSION})."
                )
            while version < SCHEMA_VERSION:
                migration = _MIGRATIONS.get(version)
                if migration is None:
                    raise ProjectError(f"Aucune migration disponible depuis le format {version}.")
                migration(conn)
                log.info("Projet migré du format %d vers %d : %s", version, version + 1, path.name)
                version += 1
            assets = [Asset.from_row(r) for r in conn.execute("SELECT * FROM assets")]
            materials = conn.execute("SELECT * FROM materials").fetchall()
            nodes = conn.execute("SELECT * FROM nodes ORDER BY position").fetchall()
            thumb = conn.execute("SELECT png FROM thumbnail WHERE id = 1").fetchone()
    except (sqlite3.DatabaseError, ValueError) as exc:
        raise ProjectError(f"« {path.name} » est illisible ou corrompu : {exc}") from exc
    return _build_project(path, meta, assets, materials, nodes, thumb[0] if thumb else None)


def _enum(enum_cls, value, default):  # type: ignore[no-untyped-def]
    try:
        return enum_cls(value)
    except ValueError:
        return default


def _build_project(
    path: Path,
    meta: dict[str, str],
    assets: list[Asset],
    material_rows: list,
    node_rows: list,
    thumbnail: bytes | None,
) -> Project:
    camera = None
    if meta.get("camera"):
        try:
            camera = json.loads(meta["camera"])
        except json.JSONDecodeError:
            log.warning("État de caméra illisible dans %s, ignoré", path.name)
    scene = SceneGraph()
    for mid, name, base_color, roughness, metallic, opacity, texture, double_sided in material_rows:
        try:
            color = tuple(json.loads(base_color))
        except (json.JSONDecodeError, TypeError):
            color = (0.72, 0.74, 0.78, 1.0)
        scene.add_material(
            Material(name, color, roughness, metallic, opacity, texture, bool(double_sided), mid)
        )
    # Parents avant enfants : on insère par vagues (les lignes sont triées par rang).
    pending = list(node_rows)
    while pending:
        progressed = False
        remaining = []
        for row in pending:
            (
                node_id,
                parent_id,
                _pos,
                name,
                kind,
                transform,
                visible,
                locked,
                asset_id,
                mesh_key,
                material_id,
            ) = row
            if parent_id is not None and parent_id not in scene:
                remaining.append(row)
                continue
            try:
                parsed = Transform.from_dict(json.loads(transform))
            except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
                log.warning("Transformation illisible pour « %s », réinitialisée", name)
                parsed = Transform()
            node = SceneNode(
                name,
                _enum(NodeKind, kind, NodeKind.GROUP),
                parsed,
                bool(visible),
                bool(locked),
                asset_id,
                mesh_key,
                material_id,
                None,
                node_id,
            )
            scene.add(node, parent_id)
            progressed = True
        if not progressed:
            log.warning("%d nœud(s) orphelin(s) rattaché(s) à la racine", len(remaining))
            for row in remaining:
                row = (row[0], None, *row[2:])
                remaining_node = SceneNode(
                    row[3],
                    _enum(NodeKind, row[4], NodeKind.GROUP),
                    Transform(),
                    bool(row[6]),
                    bool(row[7]),
                    row[8],
                    row[9],
                    row[10],
                    None,
                    row[0],
                )
                scene.add(remaining_node, None)
            break
        pending = remaining

    project = Project(
        name=meta.get("name", path.stem),
        vehicle_type=_enum(VehicleType, meta.get("vehicle_type"), VehicleType.CAR),
        role=_enum(VehicleRole, meta.get("role"), VehicleRole.CIVILIAN),
        description=meta.get("description", ""),
        created_at=meta.get("created_at", utc_now_iso()),
        updated_at=meta.get("updated_at", utc_now_iso()),
        scene=scene,
        assets={a.id: a for a in assets},
        camera=camera,
        file_path=path,
        project_id=meta.get("project_id") or new_id(),
        thumbnail=thumbnail,
    )
    log.info("Projet ouvert : %s (%d nœuds, %d assets)", path, len(scene), len(assets))
    return project


# --- Résumés (tableau de bord) ------------------------------------------------------


@dataclass
class ProjectSummary:
    path: Path
    name: str
    vehicle_type: VehicleType
    updated_at: str
    asset_count: int
    node_count: int
    thumbnail: bytes | None


def read_summary(path: str | Path) -> ProjectSummary | None:
    """Lecture rapide des métadonnées d'un projet (None si illisible)."""
    path = Path(path)
    try:
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as conn:
            meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
            if meta.get("format") != FORMAT_ID:
                return None
            tables = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "assets" in tables:
                assets = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
                nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
                row = conn.execute("SELECT png FROM thumbnail WHERE id = 1").fetchone()
                thumbnail = row[0] if row else None
            else:  # format v0.1
                assets = nodes = conn.execute("SELECT COUNT(*) FROM scene_objects").fetchone()[0]
                thumbnail = None
    except (sqlite3.Error, OSError):
        return None
    return ProjectSummary(
        path,
        meta.get("name", path.stem),
        _enum(VehicleType, meta.get("vehicle_type"), VehicleType.CAR),
        meta.get("updated_at", ""),
        int(assets),
        int(nodes),
        thumbnail,
    )


# --- Fichiers du projet -------------------------------------------------------------


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
    sous-dossier dédié afin de conserver les références relatives. L'original n'est pas modifié.
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


def store_texture(project: Project, data: bytes, name: str) -> str:
    """Enregistre une texture PNG dans ``assets/textures`` ; retourne son chemin relatif."""
    folder = project.textures_dir
    folder.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^\w\-]+", "_", name).strip("_") or "texture"
    destination = _unique_destination(folder, f"{stem[:60]}.png")
    destination.write_bytes(data)
    return destination.relative_to(project.project_dir).as_posix()


def copy_texture(project: Project, source: str | Path) -> str:
    """Copie une image choisie par l'utilisateur dans ``assets/textures`` (original intact)."""
    source = Path(source)
    folder = project.textures_dir
    folder.mkdir(parents=True, exist_ok=True)
    destination = _unique_destination(folder, source.name)
    try:
        shutil.copy2(source, destination)
    except OSError as exc:
        raise ProjectError(f"Copie de la texture impossible : {exc}") from exc
    return destination.relative_to(project.project_dir).as_posix()
