"""GLB, glTF, OBJ, STL, PLY via trimesh : hiérarchie, matériaux PBR, textures, UV."""

from __future__ import annotations

import io
import time
from collections import deque
from pathlib import Path

import numpy as np

from lsfcars.core.logging_setup import get_logger
from lsfcars.importers.base import (
    ImportedMaterial,
    ImportedNode,
    ImportResult,
    ModelLoadError,
    Progress,
    no_progress,
)
from lsfcars.scene.mesh import MeshData
from lsfcars.scene.transform import decompose

log = get_logger(__name__)

VERTEX_COLOR_MATERIAL = "__couleurs_sommets__"


def _rgba(value: object, default: tuple[float, ...]) -> tuple[float, float, float, float]:
    if value is None:
        return default  # type: ignore[return-value]
    rgba = np.asarray(value, dtype=np.float64).reshape(-1)
    if rgba.size < 3:
        return default  # type: ignore[return-value]
    if rgba.max() > 1.0:
        rgba = rgba / 255.0
    alpha = float(rgba[3]) if rgba.size > 3 else 1.0
    return float(rgba[0]), float(rgba[1]), float(rgba[2]), alpha


def _png(image: object) -> bytes | None:
    """Réencode une image PIL en PNG (aucune modification du fichier d'origine)."""
    if image is None or not hasattr(image, "save"):
        return None
    try:
        buffer = io.BytesIO()
        image.convert("RGBA").save(buffer, format="PNG")  # type: ignore[attr-defined]
        return buffer.getvalue()
    except Exception as exc:  # image corrompue ou mode exotique
        log.warning("Texture ignorée : %s", exc)
        return None


def _convert_material(material: object, key: str, index: int) -> ImportedMaterial:
    name = getattr(material, "name", None) or f"Matériau {index}"
    result = ImportedMaterial(key=key, name=str(name))
    if type(material).__name__ == "PBRMaterial":
        result.base_color = _rgba(getattr(material, "baseColorFactor", None), result.base_color)
        metallic = getattr(material, "metallicFactor", None)
        roughness = getattr(material, "roughnessFactor", None)
        result.metallic = float(metallic) if metallic is not None else 1.0  # défaut glTF
        result.roughness = float(roughness) if roughness is not None else 1.0
        texture = getattr(material, "baseColorTexture", None)
    else:  # SimpleMaterial (OBJ/MTL)
        result.base_color = _rgba(getattr(material, "diffuse", None), result.base_color)
        glossiness = getattr(material, "glossiness", None)
        if glossiness is not None:
            result.roughness = float(np.clip(1.0 - float(glossiness) / 100.0, 0.05, 1.0))
        texture = getattr(material, "image", None)
    result.opacity = result.base_color[3]
    result.texture_png = _png(texture)
    if result.texture_png:
        result.texture_name = str(name)
    return result


def _mesh_data(name: str, mesh: object) -> tuple[MeshData, str]:
    """Convertit un Trimesh (repère local) ; retourne (MeshData, mode de couleur)."""
    vertices = np.asarray(mesh.vertices, dtype=np.float64)  # type: ignore[attr-defined]
    faces = np.asarray(mesh.faces, dtype=np.int64)  # type: ignore[attr-defined]
    visual = getattr(mesh, "visual", None)
    kind = getattr(visual, "kind", None)
    if kind == "face":
        face_colors = np.asarray(visual.face_colors, dtype=np.uint8)  # type: ignore[union-attr]
        positions = vertices[faces].reshape(-1, 3)
        indices = np.arange(len(positions)).reshape(-1, 3)
        colors = np.repeat(face_colors, 3, axis=0)
        return MeshData(name, positions, indices, colors=colors), "vertex"
    if kind == "vertex":
        colors = np.asarray(visual.vertex_colors, dtype=np.uint8)  # type: ignore[union-attr]
        if colors.shape == (len(vertices), 4):
            return MeshData(name, vertices, faces, colors=colors), "vertex"
    uvs = getattr(visual, "uv", None)
    uv_array = np.asarray(uvs, dtype=np.float32) if uvs is not None else None
    white = np.full((len(vertices), 4), 255, np.uint8)
    return MeshData(name, vertices, faces, colors=white, uvs=uv_array), "material"


class TrimeshImporter:
    name = "trimesh"
    extensions = {
        ".glb": "glTF binaire",
        ".gltf": "glTF",
        ".obj": "Wavefront OBJ",
        ".stl": "STL",
        ".ply": "PLY",
    }

    def available(self) -> tuple[bool, str]:
        return True, "Intégré"

    def load(
        self, path: Path, progress: Progress = no_progress, fmt: str | None = None
    ) -> ImportResult:
        import trimesh  # import différé : coûteux au démarrage

        path = Path(path)
        start = time.perf_counter()
        progress(0.05, f"Lecture de {path.name}")
        try:
            scene = trimesh.load(str(path), force="scene", process=False)
        except Exception as exc:  # trimesh lève des types variés selon le format
            raise ModelLoadError(f"Lecture impossible de « {path.name} » : {exc}") from exc

        progress(0.45, "Analyse de la hiérarchie")
        graph = scene.graph
        base = graph.base_frame
        parents: dict[str, str] = dict(graph.transforms.parents)
        children: dict[str, list[str]] = {}
        for child, parent in parents.items():
            children.setdefault(parent, []).append(child)

        nodes: list[ImportedNode] = []
        meshes: dict[str, MeshData] = {}
        materials: dict[str, ImportedMaterial] = {}
        material_keys: dict[int, str] = {}
        queue = deque(sorted(children.get(base, [])))
        total = max(len(parents), 1)
        done = 0
        while queue:
            node_name = queue.popleft()
            done += 1
            if done % 20 == 0:
                progress(0.45 + 0.4 * done / total, "Conversion des maillages")
            parent = parents.get(node_name)
            edge = graph.transforms.edge_data.get((parent, node_name), {})
            matrix = np.asarray(edge.get("matrix", np.eye(4)), dtype=np.float64)
            geometry_name = edge.get("geometry")
            geometry = scene.geometry.get(geometry_name) if geometry_name else None
            imported = ImportedNode(
                key=str(node_name),
                name=str(node_name),
                parent_key=None if parent == base else str(parent),
                transform=decompose(matrix),
            )
            if isinstance(geometry, trimesh.Trimesh) and len(geometry.faces):
                mesh_key = str(node_name)
                data, color_mode = _mesh_data(mesh_key, geometry)
                meshes[mesh_key] = data
                imported.mesh_key = mesh_key
                if color_mode == "vertex":
                    if VERTEX_COLOR_MATERIAL not in materials:
                        materials[VERTEX_COLOR_MATERIAL] = ImportedMaterial(
                            VERTEX_COLOR_MATERIAL, "Couleurs de sommets", (1, 1, 1, 1), 0.6, 0.0
                        )
                    imported.material_key = VERTEX_COLOR_MATERIAL
                else:
                    material = getattr(geometry.visual, "material", None)
                    if material is not None:
                        key = material_keys.get(id(material))
                        if key is None:
                            key = f"m{len(material_keys)}"
                            material_keys[id(material)] = key
                            materials[key] = _convert_material(material, key, len(material_keys))
                        imported.material_key = key
            nodes.append(imported)
            queue.extend(sorted(children.get(node_name, [])))

        if not meshes:
            raise ModelLoadError(f"Aucun maillage triangulé trouvé dans « {path.name} ».")
        progress(0.9, "Finalisation")
        result = ImportResult(
            source=path,
            format=fmt or path.suffix.lower().lstrip("."),
            importer=f"trimesh {getattr(trimesh, '__version__', '?')}",
            nodes=nodes,
            meshes=meshes,
            materials=materials,
        )
        textures = sum(1 for m in materials.values() if m.texture_png)
        log.info(
            "Modèle lu : %s (%d nœuds, %d maillages, %d triangles, %d matériaux, %d textures)"
            " en %.0f ms",
            path.name,
            len(nodes),
            len(meshes),
            result.triangle_count,
            len(materials),
            textures,
            (time.perf_counter() - start) * 1000,
        )
        return result
