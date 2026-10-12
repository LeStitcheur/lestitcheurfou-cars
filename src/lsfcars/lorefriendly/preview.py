"""Aperçus légers (rendu logiciel, sans OpenGL, exécutables dans un fil) et silhouettes mesurées.

Les aperçus des propositions sont des **rendus de la géométrie transformée** (``VehicleState``),
pas des images conceptuelles : rien n'est encore écrit dans le projet tant que l'utilisateur
n'applique pas la proposition.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

from lsfcars.ai import raster3d

RenderItem = tuple[object, np.ndarray, tuple]  # (MeshData, matrice monde, couleur RGBA)
SHEET_VIEWS = ("three_quarter", "left", "front", "back")


def to_render_meshes(items: list[RenderItem]) -> list[raster3d.RenderMesh]:
    result = []
    for mesh, world, color in items:
        positions = np.asarray(mesh.positions, float) @ world[:3, :3].T + world[:3, 3]  # type: ignore[attr-defined]
        indices = np.asarray(mesh.indices, np.int64)  # type: ignore[attr-defined]
        rgb = np.tile(np.asarray(color[:3], float), (len(indices), 1))
        result.append(raster3d.RenderMesh(positions, indices, rgb))
    return result


def common_fit(groups: list[list[RenderItem]], view: str) -> tuple[np.ndarray, float]:
    points = [m.positions for items in groups for m in to_render_meshes(items)]
    if not points:
        return np.zeros(2), 1.0
    return raster3d.screen_fit(np.vstack(points), view)


def render(
    items: list[RenderItem], view: str = "three_quarter", size: int = 256, fit=None, transparent=False
) -> Image.Image:  # type: ignore[no-untyped-def]
    return raster3d.render(to_render_meshes(items), view, size, fit=fit, transparent=transparent)


def silhouette(items: list[RenderItem], view: str, size: int, fit) -> np.ndarray:  # type: ignore[no-untyped-def]
    image = render(items, view, size, fit=fit, transparent=True)
    return np.asarray(image)[..., 3] > 0


def iou(a: np.ndarray, b: np.ndarray) -> float:
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / union) if union else 1.0


def contact_sheet(items: list[RenderItem], size: int = 180, views=SHEET_VIEWS) -> bytes:  # type: ignore[no-untyped-def]
    """Planche PNG : trois quarts, profil, face avant, face arrière."""
    sheet = Image.new("RGB", (size * len(views), size), (226, 229, 234))
    for index, view in enumerate(views):
        sheet.paste(render(items, view, size), (index * size, 0))
    return png(sheet)


def png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()
