"""Chargement des fichiers 3D (GLB, glTF, OBJ, STL, PLY) via trimesh."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from lsfcars.core.logging_setup import get_logger
from lsfcars.scene.mesh import DEFAULT_COLOR, MeshData

log = get_logger(__name__)

SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".glb": "glTF binaire",
    ".gltf": "glTF",
    ".obj": "Wavefront OBJ",
    ".stl": "STL",
    ".ply": "PLY",
}


class ModelLoadError(Exception):
    """Le fichier n'a pas pu être chargé comme modèle 3D."""


def file_dialog_filter() -> str:
    patterns = " ".join(f"*{ext}" for ext in SUPPORTED_EXTENSIONS)
    details = ";;".join(f"{name} (*{ext})" for ext, name in SUPPORTED_EXTENSIONS.items())
    return f"Modèles 3D ({patterns});;{details};;Tous les fichiers (*)"


def _material_color(visual) -> tuple[float, float, float, float]:  # type: ignore[no-untyped-def]
    """Couleur de base du matériau (les textures ne sont pas encore gérées)."""
    candidates = []
    material = getattr(visual, "material", None)
    if material is not None:
        for attr in ("baseColorFactor", "main_color"):
            try:
                candidates.append(getattr(material, attr, None))
            except Exception:  # certains matériaux calculent la couleur depuis la texture
                continue
    for color in candidates:
        if color is None:
            continue
        rgba = np.asarray(color, dtype=np.float64).reshape(-1)
        if rgba.size < 3:
            continue
        if rgba.max() > 1.0:  # couleurs 0-255
            rgba = rgba / 255.0
        alpha = float(rgba[3]) if rgba.size > 3 else 1.0
        return (float(rgba[0]), float(rgba[1]), float(rgba[2]), max(alpha, 0.05))
    return DEFAULT_COLOR


def _to_mesh_data(name: str, mesh) -> MeshData:  # type: ignore[no-untyped-def]
    """Convertit un ``trimesh.Trimesh`` en ``MeshData`` en conservant les couleurs."""
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    visual = getattr(mesh, "visual", None)
    kind = getattr(visual, "kind", None)

    if kind == "face":
        # Une couleur par face : on duplique les sommets (pas de dépendance à scipy).
        face_colors = np.asarray(visual.face_colors, dtype=np.uint8)
        positions = vertices[faces].reshape(-1, 3)
        colors = np.repeat(face_colors, 3, axis=0)
        indices = np.arange(len(positions)).reshape(-1, 3)
        return MeshData(
            name, positions, indices, colors=colors, color=tuple(colors.mean(axis=0) / 255.0)
        )
    if kind == "vertex":
        colors = np.asarray(visual.vertex_colors, dtype=np.uint8)
        if colors.shape == (len(vertices), 4):
            return MeshData(
                name, vertices, faces, colors=colors, color=tuple(colors.mean(axis=0) / 255.0)
            )
    return MeshData(name, vertices, faces, color=_material_color(visual))


def load_meshes(path: str | Path) -> list[MeshData]:
    """Charge un fichier 3D et retourne ses maillages triangulés, transformations appliquées."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ModelLoadError(f"Format non pris en charge : « {ext or path.name} ».")
    if not path.is_file():
        raise ModelLoadError(f"Fichier introuvable : {path}")

    import trimesh  # import différé : coûteux au démarrage

    start = time.perf_counter()
    try:
        scene = trimesh.load(str(path), force="scene", process=False)
    except Exception as exc:  # trimesh lève des types variés selon le format
        raise ModelLoadError(f"Lecture impossible de « {path.name} » : {exc}") from exc

    meshes: list[MeshData] = []
    for node_name in scene.graph.nodes_geometry:
        transform, geometry_name = scene.graph[node_name]
        geometry = scene.geometry.get(geometry_name)
        if not isinstance(geometry, trimesh.Trimesh) or len(geometry.faces) == 0:
            continue  # nuages de points, courbes…
        mesh = geometry.copy()
        mesh.vertices = trimesh.transformations.transform_points(mesh.vertices, transform)
        meshes.append(_to_mesh_data(str(node_name), mesh))

    if not meshes:
        raise ModelLoadError(f"Aucun maillage triangulé trouvé dans « {path.name} ».")

    triangles = sum(m.triangle_count for m in meshes)
    log.info(
        "Modèle chargé : %s (%d maillage(s), %d triangles) en %.0f ms",
        path.name,
        len(meshes),
        triangles,
        (time.perf_counter() - start) * 1000,
    )
    return meshes
