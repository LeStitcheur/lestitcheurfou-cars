"""Primitives procédurales (gizmos) : cylindre, cône, tore, cube. Axe principal : +Y."""

from __future__ import annotations

import math

import numpy as np

from lsfcars.scene.mesh import MeshData


def _mesh(name: str, positions: list, indices: list) -> MeshData:
    return MeshData(name, np.asarray(positions, np.float32), np.asarray(indices, np.uint32))


def cylinder(radius: float, height: float, segments: int = 16, y0: float = 0.0) -> MeshData:
    positions, indices = [], []
    for i in range(segments):
        a = 2 * math.pi * i / segments
        x, z = math.cos(a) * radius, math.sin(a) * radius
        positions += [(x, y0, z), (x, y0 + height, z)]
    for i in range(segments):
        j = (i + 1) % segments
        a, b, c, d = 2 * i, 2 * i + 1, 2 * j, 2 * j + 1
        indices += [(a, c, b), (b, c, d)]
    return _mesh("cylindre", positions, indices)


def cone(radius: float, height: float, segments: int = 18, y0: float = 0.0) -> MeshData:
    positions = [(0.0, y0 + height, 0.0), (0.0, y0, 0.0)]
    for i in range(segments):
        a = 2 * math.pi * i / segments
        positions.append((math.cos(a) * radius, y0, math.sin(a) * radius))
    indices = []
    for i in range(segments):
        j = (i + 1) % segments
        indices += [(0, 2 + j, 2 + i), (1, 2 + i, 2 + j)]
    return _mesh("cone", positions, indices)


def torus(major: float, minor: float, segments: int = 64, sides: int = 8) -> MeshData:
    """Anneau dans le plan XZ (normal à +Y)."""
    positions, indices = [], []
    for i in range(segments):
        u = 2 * math.pi * i / segments
        for j in range(sides):
            v = 2 * math.pi * j / sides
            r = major + minor * math.cos(v)
            positions.append((r * math.cos(u), minor * math.sin(v), r * math.sin(u)))
    for i in range(segments):
        for j in range(sides):
            a = i * sides + j
            b = ((i + 1) % segments) * sides + j
            c = ((i + 1) % segments) * sides + (j + 1) % sides
            d = i * sides + (j + 1) % sides
            indices += [(a, b, c), (a, c, d)]
    return _mesh("tore", positions, indices)


def cube(size: float, center_y: float = 0.0) -> MeshData:
    h = size / 2
    corners = [(x, center_y + y, z) for x in (-h, h) for y in (-h, h) for z in (-h, h)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    positions, indices = [], []
    for quad in faces:  # sommets dupliqués : arêtes nettes
        base = len(positions)
        positions += [corners[k] for k in quad]
        indices += [(base, base + 1, base + 2), (base, base + 2, base + 3)]
    return _mesh("cube", positions, indices)


def merge(*meshes: MeshData) -> MeshData:
    positions, indices, offset = [], [], 0
    for mesh in meshes:
        positions.append(mesh.positions)
        indices.append(mesh.indices + offset)
        offset += mesh.vertex_count
    return MeshData("fusion", np.vstack(positions), np.vstack(indices))


TRANSLATE_HANDLE = merge(cylinder(0.018, 0.82, 12, 0.15), cone(0.07, 0.2, 18, 0.8))
SCALE_HANDLE = merge(cylinder(0.018, 0.82, 12, 0.15), cube(0.12, 0.92))
ROTATE_HANDLE = torus(0.85, 0.016, 72, 6)
