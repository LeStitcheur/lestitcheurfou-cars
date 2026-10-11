"""Outils d'inspection non destructifs : vue éclatée, statistiques par pièce, points d'ancrage.

Rien ici ne modifie la scène : les décalages calculés sont appliqués à l'affichage seulement
(``Viewport3D.set_display_offsets``) et disparaissent à la réinitialisation.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from lsfcars.scene import mathutils
from lsfcars.scene.graph import NodeKind

MAX_SPREAD = 1.6  # intensité 1 : chaque pièce s'éloigne de 1,6 fois sa distance au centre


def _box(mesh) -> np.ndarray:  # type: ignore[no-untyped-def]
    bmin, bmax = mesh.bounds
    return np.array(
        [[x, y, z] for x in (bmin[0], bmax[0]) for y in (bmin[1], bmax[1]) for z in (bmin[2], bmax[2])]
    )


def _center(session, node) -> np.ndarray | None:  # type: ignore[no-untyped-def]
    mesh = session.geometry_for(node)
    if mesh is None or mesh.vertex_count == 0:
        return None
    points = mathutils.transform_points(session.scene.world_matrix(node.id), _box(mesh))
    return points.mean(axis=0)


def _mesh_nodes(session, node_ids) -> list:  # type: ignore[no-untyped-def]
    if node_ids is None:
        return list(session.scene.mesh_nodes())
    seen = {}
    for node_id in node_ids:
        if node_id in session.scene:
            for node in session.scene.subtree(node_id):
                if node.kind is NodeKind.MESH:
                    seen[node.id] = node
    return list(seen.values())


def exploded_offsets(session, intensity: float, node_ids=None) -> dict[str, np.ndarray]:  # type: ignore[no-untyped-def]
    """Décalage monde de chaque maillage, proportionnel à la distance de sa pièce au centre.

    ``intensity`` : 0 (assemblé) à 1 (écartement maximal). Les maillages d'un même parent
    (ex. une roue : jante et pneu) se déplacent ensemble pour rester lisibles.
    """
    intensity = float(np.clip(intensity, 0.0, 1.0))
    bounds = session.world_bounds(node_ids, only_visible=False)
    if bounds is None or intensity == 0.0:
        return {}
    center = (bounds[0] + bounds[1]) / 2.0
    groups: dict[str | None, list] = defaultdict(list)
    for node in _mesh_nodes(session, node_ids):
        groups[node.parent_id].append(node)
    offsets: dict[str, np.ndarray] = {}
    for members in groups.values():
        centers = [c for c in (_center(session, n) for n in members) if c is not None]
        if not centers:
            continue
        offset = (np.mean(centers, axis=0) - center) * MAX_SPREAD * intensity
        for node in members:
            offsets[node.id] = offset
    return offsets


def offset_bounds(session, node_ids, offsets: dict[str, np.ndarray]):  # type: ignore[no-untyped-def]
    """Boîte englobante telle qu'affichée (décalages de la vue éclatée compris)."""
    corners = []
    for node in _mesh_nodes(session, node_ids):
        mesh = session.geometry_for(node)
        if mesh is None:
            continue
        points = mathutils.transform_points(session.scene.world_matrix(node.id), _box(mesh))
        corners.append(points + offsets.get(node.id, 0.0))
    if not corners:
        return None
    stacked = np.vstack(corners)
    return stacked.min(axis=0), stacked.max(axis=0)


@dataclass
class PartStats:
    node_id: str
    name: str
    category: str
    triangles: int
    vertices: int
    material: str


def part_statistics(session) -> list[PartStats]:  # type: ignore[no-untyped-def]
    rows = []
    for node in session.scene.mesh_nodes():
        mesh = session.geometry_for(node)
        if mesh is None:
            continue
        material = session.scene.material_for(node.id)
        rows.append(
            PartStats(
                node.id,
                node.name,
                node.extra.get("category", "non_classee"),
                mesh.triangle_count,
                mesh.vertex_count,
                material.name if material else "—",
            )
        )
    return sorted(rows, key=lambda r: -r.triangles)


def anchor_nodes(session) -> list:  # type: ignore[no-untyped-def]
    """Os sans géométrie (emplacements de sièges, feux, roues…) issus d'un import GTA V."""
    return [
        n
        for n in session.scene.walk()
        if n.extra.get("gta", {}).get("role") == "bone" and n.extra["gta"].get("anchor")
    ]
