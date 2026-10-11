"""Formes paramétriques originales (pièces de carrosserie, roues, habitacle, accessoires).

Toutes les formes sont générées par le code (aucun asset tiers) et possèdent des UV. Repère des
pièces : X = largeur (axe latéral), Y = hauteur, Z = longueur ; origine au centre de la pièce,
avant du véhicule vers -Z (convention des modèles GTA V importés).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from lsfcars.scene import mathutils
from lsfcars.scene.mesh import MeshData

Color = tuple[float, float, float, float]
NEUTRAL: Color = (0.72, 0.74, 0.78, 1.0)
DARK: Color = (0.1, 0.1, 0.11, 1.0)


def _mesh(name: str, positions, indices, uvs, color: Color = NEUTRAL, normals=None) -> MeshData:  # type: ignore[no-untyped-def]
    return MeshData(
        name,
        np.asarray(positions, np.float32),
        np.asarray(indices, np.int64).reshape(-1, 3),
        None if normals is None else np.asarray(normals, np.float32),
        color=color,
        uvs=np.asarray(uvs, np.float32),
    )


def combine(
    name: str, parts: Sequence[tuple[MeshData, np.ndarray | None]], color: Color = NEUTRAL
) -> MeshData:
    """Fusionne des maillages (chacun avec une matrice 4x4 optionnelle) en un seul."""
    positions, normals, indices, uvs = [], [], [], []
    offset = 0
    for mesh, matrix in parts:
        m = np.eye(4) if matrix is None else np.asarray(matrix, np.float64)
        positions.append(mathutils.transform_points(m, mesh.positions.astype(np.float64)))
        normals.append(mesh.normals.astype(np.float64) @ mathutils.normal_matrix(m).T)
        indices.append(mesh.indices.astype(np.int64) + offset)
        uvs.append(mesh.uvs if mesh.uvs is not None else np.zeros((mesh.vertex_count, 2), np.float32))
        offset += mesh.vertex_count
    n = np.vstack(normals)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    return _mesh(name, np.vstack(positions), np.vstack(indices), np.vstack(uvs), color, n)


def _flipped(mesh: MeshData) -> MeshData:
    return MeshData(mesh.name, mesh.positions, mesh.indices[:, [0, 2, 1]], None, None, mesh.color, mesh.uvs)


def _outward(mesh: MeshData) -> MeshData:
    """Inverse l'enroulement si le volume signé est négatif (normales vers l'intérieur)."""
    tri = mesh.positions[mesh.indices].astype(np.float64)
    volume = float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum())
    return _flipped(mesh) if volume < 0 else mesh


def box(size=(1.0, 1.0, 1.0), name: str = "Boîte", color: Color = NEUTRAL) -> MeshData:  # type: ignore[no-untyped-def]
    """Pavé centré (24 sommets, faces à arêtes vives, UV par face)."""
    half = np.array([float(s) / 2.0 for s in size])
    faces = [  # (normale, axe u, axe v) ; u x v = normale
        ((1, 0, 0), (0, 0, -1), (0, 1, 0)),
        ((-1, 0, 0), (0, 0, 1), (0, 1, 0)),
        ((0, 1, 0), (1, 0, 0), (0, 0, -1)),
        ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
        ((0, 0, 1), (1, 0, 0), (0, 1, 0)),
        ((0, 0, -1), (-1, 0, 0), (0, 1, 0)),
    ]
    positions, normals, uvs, indices = [], [], [], []
    for normal, u, v in faces:
        n, du, dv = (np.array(x, float) for x in (normal, u, v))
        for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            positions.append((n + du * su + dv * sv) * half)
            normals.append(n)
            uvs.append(((su + 1) / 2, (sv + 1) / 2))
        base = len(positions) - 4
        indices += [(base, base + 1, base + 2), (base, base + 2, base + 3)]
    return _mesh(name, positions, indices, uvs, color, normals)


def plane(width: float = 1.0, depth: float = 1.0, name: str = "Plan", color: Color = NEUTRAL) -> MeshData:
    hw, hd = width / 2, depth / 2
    positions = [(-hw, 0, hd), (hw, 0, hd), (hw, 0, -hd), (-hw, 0, -hd)]
    return _mesh(name, positions, [(0, 1, 2), (0, 2, 3)], [(0, 0), (1, 0), (1, 1), (0, 1)], color)


def cylinder(
    radius: float = 0.5,
    length: float = 1.0,
    segments: int = 24,
    name: str = "Cylindre",
    color: Color = NEUTRAL,
    caps: bool = True,
) -> MeshData:
    """Cylindre d'axe X (axe d'une roue), centré."""
    segments = max(int(segments), 3)
    hl = length / 2
    angles = np.linspace(0, 2 * math.pi, segments + 1)
    positions, normals, uvs, indices = [], [], [], []
    for i, a in enumerate(angles):  # paroi (couture dédoublée pour les UV)
        y, z = math.cos(a), math.sin(a)
        for side in (-1, 1):
            positions.append((side * hl, y * radius, z * radius))
            normals.append((0, y, z))
            uvs.append((i / segments, (side + 1) / 2))
    for i in range(segments):
        a, b, c, d = 2 * i, 2 * i + 1, 2 * i + 3, 2 * i + 2
        indices += [(a, c, b), (a, d, c)]
    if caps:
        for side in (-1, 1):
            center = len(positions)
            positions.append((side * hl, 0, 0))
            normals.append((side, 0, 0))
            uvs.append((0.5, 0.5))
            for a in angles[:-1]:
                y, z = math.cos(a), math.sin(a)
                positions.append((side * hl, y * radius, z * radius))
                normals.append((side, 0, 0))
                uvs.append((0.5 + y / 2, 0.5 + z / 2))
            for i in range(segments):
                p, q = center + 1 + i, center + 1 + (i + 1) % segments
                indices.append((center, p, q) if side > 0 else (center, q, p))
    return _mesh(name, positions, indices, uvs, color, normals)


def torus(
    major: float = 0.35,
    minor: float = 0.1,
    segments: int = 32,
    rings: int = 12,
    name: str = "Tore",
    color: Color = NEUTRAL,
    section_scale: tuple[float, float] = (1.0, 1.0),
) -> MeshData:
    """Tore d'axe X (pneu). ``section_scale`` : (largeur, hauteur) relatives de la section."""
    sx, sr = section_scale
    positions, normals, uvs, indices = [], [], [], []
    for i in range(segments + 1):
        a = 2 * math.pi * i / segments
        ca, sa = math.cos(a), math.sin(a)
        for j in range(rings + 1):
            b = 2 * math.pi * j / rings
            cb, sb = math.cos(b), math.sin(b)
            r = major + minor * sr * cb
            positions.append((minor * sx * sb, r * ca, r * sa))
            n = np.array([sb / max(sx, 1e-6), cb * ca / max(sr, 1e-6), cb * sa / max(sr, 1e-6)])
            normals.append(n / np.linalg.norm(n))
            uvs.append((i / segments, j / rings))
    stride = rings + 1
    for i in range(segments):
        for j in range(rings):
            a, b = i * stride + j, (i + 1) * stride + j
            indices += [(a, b, b + 1), (a, b + 1, a + 1)]
    mesh = _mesh(name, positions, indices, uvs, color, normals)
    tri = mesh.positions[mesh.indices].astype(np.float64)
    face_n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    if float(np.einsum("ij,ij->i", face_n, mesh.normals[mesh.indices[:, 0]]).sum()) < 0:
        mesh = MeshData(name, mesh.positions, mesh.indices[:, [0, 2, 1]], mesh.normals, None, color, mesh.uvs)
    return mesh


# --- Profils extrudés --------------------------------------------------------------------


def _signed_area(points: np.ndarray) -> float:
    x, y = points[:, 0], points[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))


def triangulate_polygon(points: Sequence[Sequence[float]]) -> list[tuple[int, int, int]]:
    """Triangulation d'un polygone simple par oreilles (triangles antihoraires)."""
    pts = np.asarray(points, np.float64)
    order = list(range(len(pts)))
    if _signed_area(pts) < 0:
        order.reverse()

    def inside(p, a, b, c) -> bool:  # type: ignore[no-untyped-def]
        d1 = (p[0] - b[0]) * (a[1] - b[1]) - (a[0] - b[0]) * (p[1] - b[1])
        d2 = (p[0] - c[0]) * (b[1] - c[1]) - (b[0] - c[0]) * (p[1] - c[1])
        d3 = (p[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (p[1] - a[1])
        return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))

    triangles: list[tuple[int, int, int]] = []
    while len(order) > 3:
        for k in range(len(order)):
            i0, i1, i2 = order[k - 1], order[k], order[(k + 1) % len(order)]
            a, b, c = pts[i0], pts[i1], pts[i2]
            if (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) <= 1e-12:
                continue
            if any(inside(pts[j], a, b, c) for j in order if j not in (i0, i1, i2)):
                continue
            triangles.append((i0, i1, i2))
            order.pop(k)
            break
        else:  # polygone dégénéré : éventail de repli
            triangles += [(order[0], order[k], order[k + 1]) for k in range(1, len(order) - 1)]
            return triangles
    triangles.append((order[0], order[1], order[2]))
    return triangles


def extrude_profile(
    profile: Sequence[Sequence[float]],
    length: float,
    name: str = "Profil",
    color: Color = NEUTRAL,
    axis: int = 0,
    bend: float = 0.0,
    segments: int = 1,
) -> MeshData:
    """Extrude un profil 2D fermé le long de ``axis`` (centré), avec bouchons.

    Profil (u, v) : pour l'axe X, u → Z et v → Y ; pour l'axe Z, u → X et v → Y.
    ``bend`` cintre la pièce (décalage parabolique selon u, maximal aux extrémités).
    """
    pts = np.asarray(profile, np.float64)
    if _signed_area(pts) < 0:
        pts = pts[::-1]
    n = len(pts)
    segments = max(int(segments), 1)
    stations = np.linspace(-length / 2, length / 2, segments + 1)
    perimeter = np.concatenate([[0], np.cumsum(np.linalg.norm(np.roll(pts, -1, 0) - pts, axis=1))])

    def place(u: float, v: float, w: float) -> tuple[float, float, float]:
        offset = bend * (2 * w / length) ** 2 if length else 0.0
        return (w, v, u + offset) if axis == 0 else (u + offset, v, w)

    positions, uvs, indices = [], [], []
    for k in range(n):  # parois : chaque arête du profil a ses propres sommets (arêtes vives)
        a, b = pts[k], pts[(k + 1) % n]
        base = len(positions)
        for s, w in enumerate(stations):
            for p, along in ((a, perimeter[k]), (b, perimeter[k + 1])):
                positions.append(place(p[0], p[1], w))
                uvs.append((along / max(perimeter[-1], 1e-9), s / segments))
        for s in range(segments):
            i0, i1 = base + 2 * s, base + 2 * s + 1
            indices += [(i0, i1, i1 + 2), (i0, i1 + 2, i0 + 2)]
    span = np.ptp(pts, axis=0)
    span[span < 1e-9] = 1.0
    for w, flip in ((stations[0], True), (stations[-1], False)):
        base = len(positions)
        for p in pts:
            positions.append(place(p[0], p[1], w))
            uvs.append(tuple((p - pts.min(axis=0)) / span))
        for t in triangulate_polygon(pts):
            indices.append((base + t[0], base + t[2], base + t[1]) if flip else tuple(base + i for i in t))
    return _outward(_mesh(name, positions, indices, uvs, color))


def _t(x: float = 0.0, y: float = 0.0, z: float = 0.0) -> np.ndarray:
    return mathutils.translation((x, y, z))


def _r(x: float = 0.0, y: float = 0.0, z: float = 0.0) -> np.ndarray:
    return mathutils.rotation_euler_xyz((x, y, z))


# --- Carrosserie ----------------------------------------------------------------------


def spoiler(width: float = 1.4, chord: float = 0.28, height: float = 0.22, angle: float = 8.0) -> MeshData:
    """Aileron : profil d'aile incliné, deux supports et deux dérives."""
    profile = [(-chord / 2, 0.0), (-chord / 4, 0.025), (chord / 3, 0.02), (chord / 2, 0.0), (0.0, -0.012)]
    wing = extrude_profile(profile, width, "aile", axis=0)
    support = box((0.03, height, chord * 0.45))
    plate = box((0.012, 0.1, chord * 1.05))
    hw = width / 2
    return combine(
        "Aileron",
        [
            (wing, _t(0, height, 0) @ _r(x=-angle)),
            (support, _t(-hw * 0.6, height / 2, 0)),
            (support, _t(hw * 0.6, height / 2, 0)),
            (plate, _t(-hw, height + 0.02, 0)),
            (plate, _t(hw, height + 0.02, 0)),
        ],
    )


def bumper(width: float = 1.8, height: float = 0.38, depth: float = 0.22, curve: float = 0.12) -> MeshData:
    """Pare-chocs avant : profil arrondi extrudé sur la largeur, cintré vers l'arrière aux angles."""
    h, d = height, depth
    profile = [
        (0, -h / 2),
        (-d * 0.75, -h / 2),
        (-d, -h * 0.25),
        (-d, h * 0.3),
        (-d * 0.7, h / 2),
        (0, h / 2),
    ]
    return extrude_profile(profile, width, "Pare-chocs", axis=0, bend=curve, segments=12)


def grille(width: float = 0.9, height: float = 0.32, bars: int = 6, depth: float = 0.05) -> MeshData:
    """Calandre : cadre et barres horizontales."""
    t = 0.035
    parts: list[tuple[MeshData, np.ndarray | None]] = [
        (box((width, t, depth)), _t(0, height / 2 - t / 2, 0)),
        (box((width, t, depth)), _t(0, -height / 2 + t / 2, 0)),
        (box((t, height, depth)), _t(-width / 2 + t / 2, 0, 0)),
        (box((t, height, depth)), _t(width / 2 - t / 2, 0, 0)),
    ]
    for k in range(1, max(int(bars), 0) + 1):
        y = -height / 2 + k * height / (bars + 1)
        parts.append((box((width - 2 * t, t * 0.45, depth * 0.7)), _t(0, y, 0)))
    return combine("Calandre", parts, DARK)


def air_intake(width: float = 0.45, length: float = 0.55, height: float = 0.09) -> MeshData:
    """Prise d'air (écope de capot) : coque en coin ouverte vers l'avant (-Z) et deux joues."""
    t = 0.012
    shell = [
        (-length / 2, height - t),
        (-length / 2 + 0.05, height),
        (length / 2, t),
        (length / 2, 0),
        (length / 2 - 0.02, 0),
        (-length / 2 + 0.03, height - t * 2),
    ]
    side = [(-length / 2, 0.0), (length / 2, 0.0), (length / 2, t), (-length / 2 + 0.05, height)]
    top = extrude_profile(shell, width, "écope", axis=0)
    cheek = extrude_profile(side, t, "joue", axis=0)
    return combine("Prise d'air", [(top, None), (cheek, _t(-width / 2, 0, 0)), (cheek, _t(width / 2, 0, 0))])


def side_skirt(length: float = 2.4, height: float = 0.14, depth: float = 0.09) -> MeshData:
    """Bas de caisse : profil extrudé dans la longueur (axe Z)."""
    profile = [(0, 0), (depth, 0.02), (depth, height * 0.6), (depth * 0.4, height), (0, height)]
    return extrude_profile(profile, length, "Bas de caisse", axis=2, segments=4)


def splitter(width: float = 1.7, depth: float = 0.16, thickness: float = 0.02) -> MeshData:
    """Lame avant : plaque à bord biseauté."""
    profile = [(0, 0), (-depth, 0), (-depth - 0.02, thickness / 2), (-depth, thickness), (0, thickness)]
    return extrude_profile(profile, width, "Lame avant", DARK, axis=0, bend=0.05, segments=10)


def diffuser(width: float = 1.2, depth: float = 0.35, fins: int = 5) -> MeshData:
    """Diffuseur arrière : plaque inclinée et ailettes verticales."""
    parts: list[tuple[MeshData, np.ndarray | None]] = [(box((width, 0.015, depth)), _r(x=12))]
    for k in range(max(int(fins), 0)):
        x = -width / 2 + (k + 0.5) * width / fins
        parts.append((box((0.012, 0.09, depth * 0.95)), _t(x, 0.04, 0) @ _r(x=12)))
    return combine("Diffuseur", parts, DARK)


def fender_flare(
    radius: float = 0.42, width: float = 0.07, thickness: float = 0.03, sweep: float = 170.0
) -> MeshData:
    """Élargisseur d'aile : arc autour du passage de roue (axe X), section profilée."""
    steps = 24
    start = math.radians(90 - sweep / 2)
    section = [(0, 0), (width, 0), (width, thickness * 0.6), (width * 0.3, thickness), (0, thickness)]
    positions, uvs, indices = [], [], []
    for i in range(steps + 1):
        a = start + math.radians(sweep) * i / steps
        ca, sa = math.cos(a), math.sin(a)
        for j, (sx, sr) in enumerate(section):
            r = radius + sr
            positions.append((sx, r * sa, -r * ca))
            uvs.append((i / steps, j / (len(section) - 1)))
    m = len(section)
    for i in range(steps):
        for j in range(m):  # section fermée
            k = (j + 1) % m
            a, b, c, d = i * m + j, (i + 1) * m + j, (i + 1) * m + k, i * m + k
            indices += [(a, b, c), (a, c, d)]
    mesh = _mesh("Élargisseur d'aile", positions, indices, uvs, DARK)
    return _outward(mesh)


def canard(length: float = 0.18, height: float = 0.06, thickness: float = 0.008) -> MeshData:
    """Canard (appendice aérodynamique de pare-chocs)."""
    return extrude_profile([(0, 0), (length, 0), (length * 0.2, height)], thickness, "Canard", DARK, axis=0)


def hood(width: float = 1.4, length: float = 1.1, crown: float = 0.05, thickness: float = 0.02) -> MeshData:
    """Capot simple : panneau bombé."""
    half = length / 2
    profile = [(-half, 0), (half, 0), (half, thickness), (0, thickness + crown), (-half, thickness)]
    return extrude_profile(profile, width, "Capot", axis=0, bend=-crown, segments=8)


# --- Roues ------------------------------------------------------------------------------


def tire(radius: float = 0.34, width: float = 0.24, profile_ratio: float = 0.45) -> MeshData:
    """Pneu : tore à section aplatie (axe X)."""
    section = radius * profile_ratio / 2
    scale = (width / (2 * section), 1.0)
    return torus(radius - section, section, 40, 14, "Pneu", (0.08, 0.08, 0.09, 1.0), scale)


def rim(radius: float = 0.22, width: float = 0.22, spokes: int = 5) -> MeshData:
    """Jante : fût, moyeu et branches."""
    barrel = cylinder(radius, width * 0.9, 36, "fût", caps=False)
    hub = cylinder(radius * 0.22, width * 0.5, 20, "moyeu")
    parts: list[tuple[MeshData, np.ndarray | None]] = [(barrel, None), (hub, _t(width * 0.15, 0, 0))]
    for k in range(max(int(spokes), 0)):
        spoke = box((0.03, radius * 0.82, 0.045))
        parts.append((spoke, _t(width * 0.3, 0, 0) @ _r(x=360.0 * k / spokes) @ _t(0, radius * 0.5, 0)))
    return combine("Jante", parts, (0.78, 0.8, 0.84, 1.0))


def wheel(radius: float = 0.34, width: float = 0.24, spokes: int = 5) -> MeshData:
    return combine("Roue", [(tire(radius, width), None), (rim(radius * 0.66, width * 0.92, spokes), None)])


# --- Habitacle ------------------------------------------------------------------------------


def seat(width: float = 0.5, depth: float = 0.5, height: float = 0.95) -> MeshData:
    cushion = box((width, 0.12, depth))
    back = box((width, height * 0.62, 0.11))
    head = box((width * 0.55, 0.16, 0.09))
    return combine(
        "Siège",
        [
            (cushion, _t(0, 0.06, 0)),
            (back, _t(0, 0.12 + height * 0.31, depth / 2) @ _r(x=-12)),
            (head, _t(0, 0.12 + height * 0.62 + 0.1, depth / 2 + 0.06) @ _r(x=-12)),
        ],
        (0.16, 0.17, 0.2, 1.0),
    )


def dashboard(width: float = 1.4, depth: float = 0.45, height: float = 0.3) -> MeshData:
    profile = [(0, 0), (depth, 0), (depth, height * 0.4), (depth * 0.45, height), (0, height * 0.85)]
    return extrude_profile(profile, width, "Tableau de bord", DARK, axis=0, bend=-0.03, segments=8)


def steering_wheel(radius: float = 0.19) -> MeshData:
    parts: list[tuple[MeshData, np.ndarray | None]] = [
        (torus(radius, 0.017, 36, 10, "jante"), None),
        (cylinder(0.05, 0.05, 16), None),
    ]
    for angle in (90.0, 210.0, 330.0):
        parts.append((box((0.02, radius, 0.025)), _r(x=angle) @ _t(0, radius / 2, 0)))
    return combine("Volant", parts, DARK)


# --- Éclairage et accessoires ------------------------------------------------------------


def headlight(width: float = 0.32, height: float = 0.14, depth: float = 0.12) -> MeshData:
    lens = cylinder(height * 0.42, 0.02, 24, "optique")
    return combine(
        "Phare",
        [
            (box((width, height, depth), "boîtier"), None),
            (lens, _t(-width / 4, 0, -depth / 2) @ _r(y=90)),
            (lens, _t(width / 4, 0, -depth / 2) @ _r(y=90)),
        ],
        (0.85, 0.87, 0.9, 1.0),
    )


def taillight(width: float = 0.36, height: float = 0.12, depth: float = 0.06) -> MeshData:
    return combine("Feu arrière", [(box((width, height, depth)), None)], (0.75, 0.12, 0.12, 1.0))


def mirror(arm: float = 0.12) -> MeshData:
    shell = extrude_profile([(0, 0), (0.1, 0), (0.12, 0.05), (0.1, 0.1), (0, 0.1)], 0.2, "coque", axis=0)
    return combine(
        "Rétroviseur", [(shell, _t(arm + 0.1, 0, 0)), (box((arm, 0.025, 0.04)), _t(arm / 2, 0.05, 0.03))]
    )


def lightbar(width: float = 1.1, modules: int = 6) -> MeshData:
    """Rampe lumineuse (équipement d'urgence) : socle et modules de lentilles."""
    parts: list[tuple[MeshData, np.ndarray | None]] = [(box((width, 0.04, 0.26)), None)]
    step = width / max(int(modules), 1)
    for k in range(max(int(modules), 1)):
        parts.append((box((step * 0.92, 0.07, 0.22)), _t(-width / 2 + step * (k + 0.5), 0.055, 0)))
    return combine("Rampe lumineuse", parts, (0.9, 0.92, 0.95, 1.0))


def push_bar(width: float = 0.9, height: float = 0.55) -> MeshData:
    """Pare-buffle : deux montants et deux traverses tubulaires."""
    upright = cylinder(0.025, height, 16)
    cross = cylinder(0.025, width, 16)
    return combine(
        "Pare-buffle",
        [
            (upright, _t(-width * 0.35, 0, 0) @ _r(z=90)),
            (upright, _t(width * 0.35, 0, 0) @ _r(z=90)),
            (cross, _t(0, height * 0.45, 0)),
            (cross, _t(0, -height * 0.1, 0)),
        ],
        DARK,
    )


def roof_rack(width: float = 1.1, length: float = 1.3) -> MeshData:
    rail = cylinder(0.018, length, 12)
    bar = box((width, 0.025, 0.05))
    return combine(
        "Galerie de toit",
        [
            (rail, _t(-width / 2, 0, 0) @ _r(y=90)),
            (rail, _t(width / 2, 0, 0) @ _r(y=90)),
            (bar, _t(0, 0.01, -length / 3)),
            (bar, _t(0, 0.01, length / 3)),
        ],
        DARK,
    )


def antenna(height: float = 0.45) -> MeshData:
    return combine(
        "Antenne",
        [
            (cylinder(0.025, 0.03, 12), _r(z=90)),
            (cylinder(0.004, height, 8), _t(0, height / 2, 0) @ _r(z=90)),
        ],
        DARK,
    )


def medical_bracket(width: float = 0.4, height: float = 0.5) -> MeshData:
    """Support médical (équipement EMS) : plaque murale et deux sangles."""
    return combine(
        "Support médical",
        [
            (box((width, height, 0.02)), None),
            (box((width * 1.05, 0.04, 0.05)), _t(0, height * 0.25, 0.03)),
            (box((width * 1.05, 0.04, 0.05)), _t(0, -height * 0.25, 0.03)),
        ],
    )
