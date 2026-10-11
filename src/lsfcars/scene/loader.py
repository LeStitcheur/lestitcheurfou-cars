"""Façade de compatibilité : charge un fichier 3D en maillages exprimés dans le repère monde.

Le studio utilise ``lsfcars.importers`` (hiérarchie, matériaux) ; cette fonction sert aux
usages simples (test de démarrage, rendu de la bannière).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from lsfcars.importers import ModelLoadError, file_dialog_filter, load_model, supported_extensions
from lsfcars.scene.mesh import MeshData

SUPPORTED_EXTENSIONS = supported_extensions()

__all__ = ["SUPPORTED_EXTENSIONS", "ModelLoadError", "file_dialog_filter", "load_meshes"]


def load_meshes(path: str | Path) -> list[MeshData]:
    result = load_model(path)
    parents = {n.key: n.parent_key for n in result.nodes}
    locals_ = {n.key: n.transform.matrix() for n in result.nodes}
    meshes = []
    for node in result.nodes:
        if not node.mesh_key:
            continue
        world = locals_[node.key]
        parent = parents[node.key]
        while parent is not None:
            world = locals_[parent] @ world
            parent = parents[parent]
        source = result.meshes[node.mesh_key]
        material = result.materials.get(node.material_key or "")
        color = material.base_color if material else (0.72, 0.74, 0.78, 1.0)
        colors = source.colors
        if material is not None and node.material_key != "__couleurs_sommets__":
            rgba = np.clip(np.asarray(color) * 255, 0, 255).astype(np.uint8)
            colors = np.tile(rgba, (source.vertex_count, 1))
        positions = source.positions @ world[:3, :3].T + world[:3, 3]
        meshes.append(MeshData(node.name, positions, source.indices, colors=colors, color=color))
    return meshes
