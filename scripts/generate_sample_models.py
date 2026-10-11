"""Génère le véhicule de test libre de droits ``samples/vehicule_test.(glb|obj)``.

Coupé low-poly créé de zéro (silhouette extrudée, roues, optiques) : aucune donnée GTA V
ni modèle tiers. Le GLB conserve une hiérarchie (carrosserie, roues > pneu / jante) et des
matériaux PBR pour exercer l'explorateur de scène et l'éditeur de matériaux.

Repère : +Y vers le haut, +Z vers l'avant, X la largeur. Unités : mètres.
Usage : ``python scripts/generate_sample_models.py``
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial

SAMPLES = Path(__file__).resolve().parents[1] / "samples"

MATERIALS = {
    "peinture": PBRMaterial(
        name="Peinture rouge LS",
        baseColorFactor=[214, 32, 52, 255],
        metallicFactor=0.55,
        roughnessFactor=0.32,
    ),
    "vitres": PBRMaterial(
        name="Vitres teintées",
        baseColorFactor=[22, 27, 36, 255],
        metallicFactor=0.3,
        roughnessFactor=0.08,
    ),
    "pneus": PBRMaterial(
        name="Caoutchouc",
        baseColorFactor=[20, 20, 22, 255],
        metallicFactor=0.0,
        roughnessFactor=0.92,
    ),
    "jantes": PBRMaterial(
        name="Aluminium brossé",
        baseColorFactor=[196, 201, 210, 255],
        metallicFactor=1.0,
        roughnessFactor=0.28,
    ),
    "phares": PBRMaterial(
        name="Optiques avant",
        baseColorFactor=[255, 246, 222, 255],
        metallicFactor=0.0,
        roughnessFactor=0.15,
    ),
    "feux": PBRMaterial(
        name="Feux arrière",
        baseColorFactor=[190, 16, 30, 255],
        metallicFactor=0.0,
        roughnessFactor=0.2,
    ),
    "chassis": PBRMaterial(
        name="Soubassement",
        baseColorFactor=[28, 30, 34, 255],
        metallicFactor=0.2,
        roughnessFactor=0.8,
    ),
}

# Silhouettes latérales (z, y), sens antihoraire vues depuis +X.
BODY_PROFILE = [
    (-2.22, 0.30),
    (2.18, 0.30),
    (2.30, 0.48),
    (2.24, 0.62),
    (2.00, 0.72),
    (1.10, 0.84),
    (0.80, 0.88),
    (-1.62, 0.95),
    (-2.12, 0.92),
    (-2.28, 0.74),
    (-2.30, 0.46),
]
CABIN_PROFILE = [
    (-1.66, 0.90),
    (0.86, 0.86),
    (0.10, 1.27),
    (-0.82, 1.26),
]


def _signed_area(polygon: np.ndarray) -> float:
    x, y = polygon[:, 0], polygon[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _cross(u: np.ndarray, v: np.ndarray) -> float:
    return float(u[0] * v[1] - u[1] * v[0])


def triangulate(polygon: list[tuple[float, float]]) -> list[tuple[int, int, int]]:
    """Triangulation par oreilles d'un polygone simple (antihoraire)."""
    points = np.asarray(polygon, dtype=float)
    indices = list(range(len(points)))
    if _signed_area(points) < 0:
        indices.reverse()
    triangles = []

    def is_ear(i_prev: int, i: int, i_next: int) -> bool:
        a, b, c = points[i_prev], points[i], points[i_next]
        if _cross(b - a, c - b) <= 1e-12:  # sommet réflexe
            return False
        for j in indices:
            if j in (i_prev, i, i_next):
                continue
            p = points[j]
            d1, d2, d3 = _cross(b - a, p - a), _cross(c - b, p - b), _cross(a - c, p - c)
            if d1 >= 0 and d2 >= 0 and d3 >= 0:
                return False
        return True

    guard = 0
    while len(indices) > 3 and guard < 10_000:
        guard += 1
        for k in range(len(indices)):
            i_prev, i, i_next = indices[k - 1], indices[k], indices[(k + 1) % len(indices)]
            if is_ear(i_prev, i, i_next):
                triangles.append((i_prev, i, i_next))
                indices.pop(k)
                break
    triangles.append(tuple(indices))
    return triangles


def extrude_profile(profile: list[tuple[float, float]], half_width: float) -> trimesh.Trimesh:
    """Extrude une silhouette (z, y) sur la largeur X ∈ [-half_width, half_width]."""
    if _signed_area(np.asarray(profile, dtype=float)) < 0:
        profile = profile[::-1]  # caps et flancs doivent partager la même orientation
    n = len(profile)
    zy = np.asarray(profile, dtype=float)
    right = np.column_stack([np.full(n, half_width), zy[:, 1], zy[:, 0]])
    left = np.column_stack([np.full(n, -half_width), zy[:, 1], zy[:, 0]])
    vertices = np.vstack([right, left])
    faces = []
    for a, b, c in triangulate(profile):
        faces.append((a, b, c))  # face droite (+X)
        faces.append((n + c, n + b, n + a))  # face gauche (-X)
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, n + i, n + j))
        faces.append((i, n + j, j))
    mesh = trimesh.Trimesh(vertices, faces, process=False)
    if mesh.volume < 0:  # normales vers l'extérieur (sans scipy, contrairement à fix_normals)
        mesh.invert()
    return mesh


def _finish(mesh: trimesh.Trimesh, material: str) -> trimesh.Trimesh:
    mesh.unmerge_vertices()  # arêtes nettes
    mesh.visual = trimesh.visual.TextureVisuals(material=MATERIALS[material])
    return mesh


def _wheel_parts() -> tuple[trimesh.Trimesh, trimesh.Trimesh]:
    rotation = trimesh.transformations.rotation_matrix(np.pi / 2, (0, 1, 0))
    tyre = trimesh.creation.cylinder(radius=0.34, height=0.25, sections=28)
    tyre.apply_transform(rotation)
    rim = trimesh.creation.cylinder(radius=0.22, height=0.27, sections=10)
    rim.apply_transform(rotation)
    return _finish(tyre, "pneus"), _finish(rim, "jantes")


def build_scene() -> trimesh.Scene:
    scene = trimesh.Scene()
    world = scene.graph.base_frame
    identity = np.eye(4)

    def group(name: str, parent: str, translation=(0.0, 0.0, 0.0)) -> str:
        matrix = trimesh.transformations.translation_matrix(translation)
        scene.graph.update(frame_from=parent, frame_to=name, matrix=matrix)
        return name

    def part(name: str, mesh: trimesh.Trimesh, parent: str, matrix=identity) -> None:
        scene.add_geometry(
            mesh, node_name=name, geom_name=f"{name}_geo", parent_node_name=parent, transform=matrix
        )

    root = group("vehicule_test", world)
    body = group("carrosserie", root)
    part("caisse", _finish(extrude_profile(BODY_PROFILE, 0.92), "peinture"), body)
    part("habitacle", _finish(extrude_profile(CABIN_PROFILE, 0.80), "vitres"), body)
    part(
        "soubassement",
        _finish(trimesh.creation.box((1.70, 0.08, 4.10)), "chassis"),
        body,
        trimesh.transformations.translation_matrix((0, 0.30, 0)),
    )
    for side, x in (("gauche", 0.62), ("droite", -0.62)):
        part(
            f"phare_{side}",
            _finish(trimesh.creation.box((0.42, 0.09, 0.06)), "phares"),
            body,
            trimesh.transformations.translation_matrix((x, 0.64, 2.22)),
        )
        part(
            f"feu_{side}",
            _finish(trimesh.creation.box((0.46, 0.08, 0.05)), "feux"),
            body,
            trimesh.transformations.translation_matrix((x, 0.80, -2.27)),
        )

    wheels = group("roues", root)
    for axle, z in (("avant", 1.42), ("arriere", -1.38)):
        for side, x in (("gauche", 0.86), ("droite", -0.86)):
            wheel = group(f"roue_{axle}_{side}", wheels, (x, 0.34, z))
            tyre, rim = _wheel_parts()
            part(f"pneu_{axle}_{side}", tyre, wheel)
            part(f"jante_{axle}_{side}", rim, wheel)
    return scene


def main() -> None:
    SAMPLES.mkdir(exist_ok=True)
    scene = build_scene()
    glb = SAMPLES / "vehicule_test.glb"
    obj = SAMPLES / "vehicule_test.obj"
    scene.export(glb)
    # OBJ : pas de hiérarchie ni de PBR (format plus pauvre), couleurs conservées via le MTL.
    scene.export(obj, include_normals=False)  # normales recalculées au chargement
    for path in sorted(SAMPLES.glob("vehicule_test*")):
        print(f"{path.relative_to(SAMPLES.parent)} : {path.stat().st_size} octets")


if __name__ == "__main__":
    main()
