"""Génère ``samples/vehicule_lore.glb`` : berline d'essai originale, pièces nommées (calandre,
phares, feux, boucliers, rétroviseurs, roues, échappement) et carrosserie lissée par sections
(assez de sommets pour des déformations douces). Aucun asset tiers : tout est calculé ici.

Usage : python scripts/generate_lore_sample.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lsfcars.scene import shapes  # noqa: E402
from lsfcars.scene.mesh import MeshData  # noqa: E402

LENGTH, WIDTH = 4.5, 1.8
FRONT_AXLE, REAR_AXLE = -1.38, 1.36  # z (avant vers −Z)
WHEEL_R = 0.34
PAINT = (0.16, 0.3, 0.55, 1.0)


def _smooth(x: float, a: float, b: float) -> float:
    t = min(max((x - a) / (b - a), 0.0), 1.0)
    return t * t * (3 - 2 * t)


def body_section(z: float) -> tuple[float, float, float, float, float]:
    """(bas, ceinture, toit, demi-largeur bas, demi-largeur toit) à la station z."""
    u = (LENGTH / 2 - z) / LENGTH  # 0 = arrière, 1 = avant
    belt = 0.62 + 0.3 * _smooth(u, 0.02, 0.16) - 0.2 * _smooth(u, 0.82, 1.0) + 0.03 * _smooth(u, 0.2, 0.7)
    roof = belt + (1.42 - belt) * _smooth(u, 0.24, 0.36) * (1 - _smooth(u, 0.6, 0.72))
    bottom = 0.26
    for axle in (FRONT_AXLE, REAR_AXLE):  # passages de roues
        dz = abs(z - axle)
        if dz < WHEEL_R + 0.06:
            bottom = max(bottom, 0.34 + math.sqrt(max((WHEEL_R + 0.06) ** 2 - dz**2, 0.0)) * 0.95)
    end = min(_smooth(u, 0.0, 0.05), 1 - _smooth(u, 0.95, 1.0))  # extrémités arrondies (vue de dessus)
    half = WIDTH / 2 * (0.86 + 0.14 * math.sqrt(max(end, 0.0)))
    return bottom, belt, roof, half, half * 0.78


def body_mesh(stations: int = 64) -> MeshData:
    zs = np.linspace(-LENGTH / 2, LENGTH / 2, stations)
    rings = []
    for z in zs:
        bottom, belt, roof, half, top_half = body_section(float(z))
        profile = [
            (0.0, bottom),
            (half * 0.7, bottom),
            (half, bottom + 0.06),
            (half, belt - 0.12),
            (half * 0.98, belt),
            (top_half + (half * 0.98 - top_half) * 0.15, belt + (roof - belt) * 0.15),
            (top_half, roof - 0.04),
            (top_half * 0.7, roof),
            (0.0, roof),
        ]
        full = profile + [(-x, y) for x, y in reversed(profile[1:-1])]
        rings.append([(x, y, z) for x, y in full])
    ring = len(rings[0])
    positions = np.array([p for r in rings for p in r], np.float64)
    indices = []
    for s in range(stations - 1):
        for k in range(ring):
            a, b = s * ring + k, s * ring + (k + 1) % ring
            c, d = (s + 1) * ring + (k + 1) % ring, (s + 1) * ring + k
            indices += [(a, d, c), (a, c, b)]
    for s, flip in ((0, False), (stations - 1, True)):  # bouchons
        center = len(positions)
        positions = np.vstack([positions, positions[s * ring : (s + 1) * ring].mean(axis=0)])
        for k in range(ring):
            a, b = s * ring + k, s * ring + (k + 1) % ring
            indices.append((center, b, a) if not flip else (center, a, b))
    faces = np.array(indices)
    tri = positions[faces]
    if (
        np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() < 0
    ):  # normales vers l'extérieur
        faces = faces[:, [0, 2, 1]]
    uvs = np.column_stack([(positions[:, 2] + LENGTH / 2) / LENGTH, positions[:, 1] / 1.5])
    return MeshData("carrosserie", positions, faces, color=PAINT, uvs=uvs)


def to_trimesh(mesh: MeshData, color) -> trimesh.Trimesh:  # type: ignore[no-untyped-def]
    tm = trimesh.Trimesh(mesh.positions, mesh.indices, process=False)
    rgba = (np.asarray(color) * 255).astype(np.uint8)
    tm.visual = trimesh.visual.ColorVisuals(tm, vertex_colors=np.tile(rgba, (len(tm.vertices), 1)))
    return tm


def translate(x: float, y: float, z: float, rot_y: float = 0.0) -> np.ndarray:
    m = trimesh.transformations.rotation_matrix(math.radians(rot_y), (0, 1, 0))
    m[:3, 3] = (x, y, z)
    return m


def build() -> trimesh.Scene:
    scene = trimesh.Scene()
    scene.add_geometry(to_trimesh(body_mesh(), PAINT), node_name="carrosserie", geom_name="carrosserie")
    front_z, rear_z = -LENGTH / 2, LENGTH / 2
    _, belt_f, _, _, _ = body_section(front_z + 0.12)
    _, belt_r, _, _, _ = body_section(rear_z - 0.12)
    parts = [
        ("calandre", shapes.grille(0.78, 0.2, 5), shapes.DARK, (0.0, belt_f - 0.2, front_z + 0.015), 0),
        (
            "phare_gauche",
            shapes.headlight(0.34, 0.12),
            (0.9, 0.9, 0.92, 1.0),
            (-0.56, belt_f - 0.1, front_z + 0.045),
            0,
        ),
        (
            "phare_droit",
            shapes.headlight(0.34, 0.12),
            (0.9, 0.9, 0.92, 1.0),
            (0.56, belt_f - 0.1, front_z + 0.045),
            0,
        ),
        (
            "feu_arriere_gauche",
            shapes.taillight(0.36, 0.12),
            (0.7, 0.1, 0.1, 1.0),
            (-0.62, belt_r - 0.12, rear_z - 0.04),
            0,
        ),
        (
            "feu_arriere_droit",
            shapes.taillight(0.36, 0.12),
            (0.7, 0.1, 0.1, 1.0),
            (0.62, belt_r - 0.12, rear_z - 0.04),
            0,
        ),
        (
            "pare_chocs_avant",
            shapes.bumper(1.7, 0.26, 0.14, 0.08),
            shapes.DARK,
            (0.0, 0.36, front_z + 0.1),
            0,
        ),
        (
            "pare_chocs_arriere",
            shapes.bumper(1.7, 0.24, 0.12, 0.08),
            shapes.DARK,
            (0.0, 0.36, rear_z - 0.1),
            180,
        ),
        ("retroviseur_gauche", shapes.mirror(), PAINT, (-0.74, 0.98, -0.62), 180),
        ("retroviseur_droit", shapes.mirror(), PAINT, (0.74, 0.98, -0.62), 0),
        (
            "echappement",
            shapes.cylinder(0.04, 0.16, 16),
            (0.55, 0.55, 0.57, 1.0),
            (-0.55, 0.22, rear_z - 0.02),
            90,
        ),
    ]
    for name, mesh, color, (x, y, z), rot in parts:
        scene.add_geometry(
            to_trimesh(mesh, color), node_name=name, geom_name=name, transform=translate(x, y, z, rot)
        )
    for side, x in (("gauche", -0.8), ("droite", 0.8)):
        for axle, z in (("avant", FRONT_AXLE), ("arriere", REAR_AXLE)):
            pieces = (
                ("pneu", shapes.tire(WHEEL_R, 0.24), (0.08, 0.08, 0.09, 1.0)),
                ("jante", shapes.rim(0.22, 0.22), (0.7, 0.72, 0.75, 1.0)),
            )
            for kind, mesh, color in pieces:
                name = f"{kind}_{axle}_{side}"
                scene.add_geometry(
                    to_trimesh(mesh, color),
                    node_name=name,
                    geom_name=name,
                    transform=translate(x, WHEEL_R, z),
                )
    return scene


def main() -> None:
    out = ROOT / "samples" / "vehicule_lore.glb"
    build().export(out)
    print(f"{out.relative_to(ROOT)} : {out.stat().st_size // 1024} Ko")


if __name__ == "__main__":
    main()
