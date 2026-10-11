"""Édition de maillage (mode Édition) : topologie soudée, sélection et opérations géométriques.

Pur numpy, sans Qt. Les maillages ``MeshData`` sont triangulés et peuvent dupliquer un sommet
aux coutures (UV, arêtes vives) : la topologie « soudée » regroupe les sommets de rendu de même
position en **sommets logiques**, que l'utilisateur sélectionne. Les identifiants logiques sont
stables tant que l'opération ne change pas le nombre de sommets de rendu (ordre de première
apparition).

Chaque opération retourne un **nouveau** ``MeshData`` (les maillages sont immuables) ; l'original
n'est jamais modifié. Les opérations qui ne savent pas conserver les UV le signalent dans
``EditResult.warnings`` et ``uv_changed``.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

from lsfcars.scene import mathutils
from lsfcars.scene.mesh import MeshData, compute_vertex_normals

VERTEX, EDGE, FACE = "vertex", "edge", "face"
ELEMENT_LABELS = {VERTEX: "Sommets", EDGE: "Arêtes", FACE: "Faces"}
WELD_TOLERANCE = 1e-5  # mètres


class EditError(ValueError):
    """Opération impossible (sélection vide ou inadaptée, résultat dégénéré)."""


# --- Topologie --------------------------------------------------------------------


@dataclass
class Topology:
    vertex_of: np.ndarray  # (N,) sommet logique de chaque sommet de rendu
    positions: np.ndarray  # (V, 3) position des sommets logiques
    tri: np.ndarray  # (M, 3) sommets logiques de chaque triangle
    edges: np.ndarray  # (E, 2) arêtes logiques uniques (a < b)

    @property
    def vertex_count(self) -> int:
        return len(self.positions)


_TOPOLOGY_CACHE: dict[int, tuple[MeshData, Topology]] = {}


def topology(mesh: MeshData) -> Topology:
    """Topologie soudée (mise en cache tant que le maillage existe)."""
    cached = _TOPOLOGY_CACHE.get(id(mesh))
    if cached is not None and cached[0] is mesh:
        return cached[1]
    if len(_TOPOLOGY_CACHE) > 64:
        _TOPOLOGY_CACHE.clear()
    topo = _build_topology(mesh.positions, mesh.indices)
    _TOPOLOGY_CACHE[id(mesh)] = (mesh, topo)
    return topo


def _build_topology(positions: np.ndarray, indices: np.ndarray) -> Topology:
    if len(positions) == 0:
        empty = np.zeros((0, 3), np.int64)
        return Topology(
            np.zeros(0, np.int64), np.zeros((0, 3), np.float64), empty, np.zeros((0, 2), np.int64)
        )
    keys = np.round(positions.astype(np.float64) / WELD_TOLERANCE).astype(np.int64)
    _, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    order = np.argsort(first, kind="stable")  # groupes classés par première apparition
    rank = np.empty_like(order)
    rank[order] = np.arange(len(order))
    vertex_of = rank[inverse.reshape(-1)]
    logical = positions[first[order]].astype(np.float64)
    tri = vertex_of[indices.astype(np.int64)] if len(indices) else np.zeros((0, 3), np.int64)
    if len(tri):
        pairs = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]])
        pairs.sort(axis=1)
        pairs = pairs[pairs[:, 0] != pairs[:, 1]]
        edges = np.unique(pairs, axis=0) if len(pairs) else np.zeros((0, 2), np.int64)
    else:
        edges = np.zeros((0, 2), np.int64)
    return Topology(vertex_of, logical, tri, edges)


# --- Sélection ----------------------------------------------------------------------


def to_vertices(mesh: MeshData, element: str, items) -> np.ndarray:  # type: ignore[no-untyped-def]
    """Sommets logiques couverts par une sélection de sommets, d'arêtes ou de faces."""
    topo = topology(mesh)
    items = list(items)
    if not items:
        return np.zeros(0, np.int64)
    if element == VERTEX:
        values = np.asarray(items, np.int64)
        return np.unique(values[(values >= 0) & (values < topo.vertex_count)])
    if element == EDGE:
        return np.unique(np.asarray(items, np.int64).reshape(-1))
    faces = np.asarray(items, np.int64)
    faces = faces[(faces >= 0) & (faces < len(topo.tri))]
    return np.unique(topo.tri[faces].reshape(-1))


def faces_from_vertices(mesh: MeshData, vertices) -> np.ndarray:  # type: ignore[no-untyped-def]
    topo = topology(mesh)
    chosen = np.zeros(topo.vertex_count, bool)
    chosen[np.asarray(list(vertices), np.int64)] = True
    return np.flatnonzero(chosen[topo.tri].all(axis=1)) if len(topo.tri) else np.zeros(0, np.int64)


def edges_from_vertices(mesh: MeshData, vertices) -> list[tuple[int, int]]:  # type: ignore[no-untyped-def]
    topo = topology(mesh)
    chosen = np.zeros(topo.vertex_count, bool)
    chosen[np.asarray(list(vertices), np.int64)] = True
    keep = chosen[topo.edges].all(axis=1) if len(topo.edges) else np.zeros(0, bool)
    return [(int(a), int(b)) for a, b in topo.edges[keep]]


def convert_selection(mesh: MeshData, element: str, items, target: str) -> set:  # type: ignore[no-untyped-def]
    """Change le type de sélection (sommets ↔ arêtes ↔ faces)."""
    vertices = to_vertices(mesh, element, items)
    if target == VERTEX:
        return {int(v) for v in vertices}
    if target == EDGE:
        return set(edges_from_vertices(mesh, vertices))
    return {int(f) for f in faces_from_vertices(mesh, vertices)}


def all_elements(mesh: MeshData, element: str) -> set:  # type: ignore[no-untyped-def]
    topo = topology(mesh)
    if element == VERTEX:
        return set(range(topo.vertex_count))
    if element == EDGE:
        return {(int(a), int(b)) for a, b in topo.edges}
    return set(range(len(topo.tri)))


def _vertex_neighbors(topo: Topology) -> list[list[int]]:
    neighbors: list[list[int]] = [[] for _ in range(topo.vertex_count)]
    for a, b in topo.edges.tolist():
        neighbors[a].append(b)
        neighbors[b].append(a)
    return neighbors


def grow_vertices(mesh: MeshData, vertices) -> set[int]:  # type: ignore[no-untyped-def]
    topo = topology(mesh)
    chosen = set(int(v) for v in vertices)
    if not chosen or not len(topo.edges):
        return chosen
    mask = np.zeros(topo.vertex_count, bool)
    mask[list(chosen)] = True
    touching = mask[topo.edges].any(axis=1)
    return chosen | {int(v) for v in topo.edges[touching].reshape(-1)}


def linked_vertices(mesh: MeshData, vertices) -> set[int]:  # type: ignore[no-untyped-def]
    """Sommets de toutes les parties connexes touchées par la sélection."""
    topo = topology(mesh)
    neighbors = _vertex_neighbors(topo)
    seen = set(int(v) for v in vertices)
    stack = list(seen)
    while stack:
        for nxt in neighbors[stack.pop()]:
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def face_normals(positions: np.ndarray, indices: np.ndarray) -> np.ndarray:
    if not len(indices):
        return np.zeros((0, 3))
    tri = positions[indices].astype(np.float64)
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    return np.divide(normals, lengths, out=np.zeros_like(normals), where=lengths > 1e-15)


def coplanar_faces(mesh: MeshData, seed: int, angle_deg: float = 5.0) -> set[int]:
    """Faces connectées à ``seed`` dont la normale s'écarte de moins de ``angle_deg``."""
    topo = topology(mesh)
    if not 0 <= seed < len(topo.tri):
        return set()
    normals = face_normals(topo.positions, topo.tri)
    reference = normals[seed]
    limit = math.cos(math.radians(angle_deg))
    by_edge: dict[tuple[int, int], list[int]] = defaultdict(list)
    for face, (a, b, c) in enumerate(topo.tri.tolist()):
        for u, v in ((a, b), (b, c), (c, a)):
            by_edge[(min(u, v), max(u, v))].append(face)
    region = {seed}
    stack = [seed]
    while stack:
        face = stack.pop()
        a, b, c = topo.tri[face].tolist()
        for u, v in ((a, b), (b, c), (c, a)):
            for other in by_edge[(min(u, v), max(u, v))]:
                if other not in region and float(normals[other] @ reference) >= limit:
                    region.add(other)
                    stack.append(other)
    return region


def selection_center(mesh: MeshData, element: str, items) -> np.ndarray | None:  # type: ignore[no-untyped-def]
    vertices = to_vertices(mesh, element, items)
    if not len(vertices):
        return None
    return topology(mesh).positions[vertices].mean(axis=0)


# --- Résultat et reconstruction ---------------------------------------------------------


@dataclass
class EditResult:
    mesh: MeshData
    element: str = FACE
    selection: set = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)
    uv_changed: bool = False
    extra: MeshData | None = None  # séparation : partie détachée


def _colors_or_default(mesh: MeshData) -> np.ndarray:
    return mesh.colors if mesh.colors is not None else np.full((mesh.vertex_count, 4), 255, np.uint8)


def _build(
    template: MeshData,
    positions: np.ndarray,
    indices: np.ndarray,
    normals: np.ndarray | None,
    colors: np.ndarray,
    uvs: np.ndarray | None,
) -> MeshData:
    return MeshData(
        template.name,
        np.asarray(positions, np.float32),
        np.asarray(indices, np.int64),
        None if normals is None else np.asarray(normals, np.float32),
        np.asarray(colors, np.uint8),
        template.color,
        None if uvs is None else np.asarray(uvs, np.float32),
    )


def _refresh_normals(positions: np.ndarray, indices: np.ndarray, old: np.ndarray, affected) -> np.ndarray:  # type: ignore[no-untyped-def]
    """Recalcule les normales des sommets de rendu touchés, conserve les autres (normales d'auteur)."""
    fresh = compute_vertex_normals(positions, indices)
    if old is None or len(old) != len(positions):
        return fresh
    result = old.copy()
    result[affected] = fresh[affected]
    return result


def _compact(
    positions: np.ndarray,
    indices: np.ndarray,
    normals: np.ndarray | None,
    colors: np.ndarray,
    uvs: np.ndarray | None,
):  # type: ignore[no-untyped-def]
    """Retire les sommets de rendu inutilisés."""
    used = np.zeros(len(positions), bool)
    if len(indices):
        used[indices.reshape(-1)] = True
    remap = np.full(len(positions), -1, np.int64)
    remap[used] = np.arange(int(used.sum()))
    return (
        positions[used],
        remap[indices] if len(indices) else np.zeros((0, 3), np.int64),
        None if normals is None else normals[used],
        colors[used],
        None if uvs is None else uvs[used],
    )


def _drop_degenerate(indices: np.ndarray, vertex_of: np.ndarray) -> np.ndarray:
    logical = vertex_of[indices]
    keep = (
        (logical[:, 0] != logical[:, 1]) & (logical[:, 1] != logical[:, 2]) & (logical[:, 0] != logical[:, 2])
    )
    return indices[keep]


def _require(items, message: str) -> None:  # type: ignore[no-untyped-def]
    if items is None or len(items) == 0:
        raise EditError(message)


# --- Transformations de sommets -----------------------------------------------------------


def transform_elements(mesh: MeshData, element: str, items, matrix: np.ndarray) -> EditResult:  # type: ignore[no-untyped-def]
    """Applique une matrice 4x4 (repère local du maillage) aux sommets sélectionnés."""
    vertices = to_vertices(mesh, element, items)
    _require(vertices, "Aucun élément sélectionné.")
    topo = topology(mesh)
    moved = np.isin(topo.vertex_of, vertices)
    positions = mesh.positions.astype(np.float64).copy()
    positions[moved] = mathutils.transform_points(np.asarray(matrix, np.float64), positions[moved])
    tri_touched = moved[mesh.indices].any(axis=1)
    affected = np.zeros(len(positions), bool)
    affected[mesh.indices[tri_touched].reshape(-1)] = True
    normals = _refresh_normals(positions, mesh.indices, mesh.normals, affected)
    result = EditResult(
        _build(mesh, positions, mesh.indices, normals, _colors_or_default(mesh), mesh.uvs),
        element,
        set(items),
    )
    report = uv_stretch(mesh, result.mesh)
    if report > 0.5:
        result.warnings.append(
            f"Déformation importante des UV (étirement moyen {report:.0%}) : la texture peut paraître "
            "étirée. Correction possible : projection UV automatique."
        )
    return result


def translate_elements(mesh: MeshData, element: str, items, offset) -> EditResult:  # type: ignore[no-untyped-def]
    return transform_elements(mesh, element, items, mathutils.translation(offset))


def scale_elements(mesh: MeshData, element: str, items, factors, pivot=None) -> EditResult:  # type: ignore[no-untyped-def]
    center = selection_center(mesh, element, items) if pivot is None else np.asarray(pivot, np.float64)
    if center is None:
        raise EditError("Aucun élément sélectionné.")
    matrix = mathutils.translation(center) @ mathutils.scaling(factors) @ mathutils.translation(-center)
    return transform_elements(mesh, element, items, matrix)


def rotate_elements(mesh: MeshData, element: str, items, degrees, pivot=None) -> EditResult:  # type: ignore[no-untyped-def]
    center = selection_center(mesh, element, items) if pivot is None else np.asarray(pivot, np.float64)
    if center is None:
        raise EditError("Aucun élément sélectionné.")
    matrix = (
        mathutils.translation(center) @ mathutils.rotation_euler_xyz(degrees) @ mathutils.translation(-center)
    )
    return transform_elements(mesh, element, items, matrix)


def flatten_elements(
    mesh: MeshData, element: str, items, axis: int, value: float | None = None
) -> EditResult:  # type: ignore[no-untyped-def]
    """Aligne les sommets sélectionnés sur un plan perpendiculaire à ``axis`` (centre par défaut)."""
    vertices = to_vertices(mesh, element, items)
    _require(vertices, "Aucun élément sélectionné.")
    topo = topology(mesh)
    target = float(topo.positions[vertices, axis].mean()) if value is None else float(value)
    moved = np.isin(topo.vertex_of, vertices)
    positions = mesh.positions.astype(np.float64).copy()
    positions[moved, axis] = target
    affected = np.zeros(len(positions), bool)
    affected[mesh.indices[moved[mesh.indices].any(axis=1)].reshape(-1)] = True
    normals = _refresh_normals(positions, mesh.indices, mesh.normals, affected)
    return EditResult(
        _build(mesh, positions, mesh.indices, normals, _colors_or_default(mesh), mesh.uvs),
        element,
        set(items),
    )


# --- Extrusion et inset ---------------------------------------------------------------


def _islands(tri: np.ndarray, faces: np.ndarray) -> list[np.ndarray]:
    """Groupes de faces connexes (arêtes logiques partagées) — union-find."""
    parent = {int(f): int(f) for f in faces}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owner: dict[tuple[int, int], int] = {}
    for face in faces.tolist():
        a, b, c = tri[face].tolist()
        for u, v in ((a, b), (b, c), (c, a)):
            key = (min(u, v), max(u, v))
            if key in owner:
                ra, rb = find(owner[key]), find(face)
                if ra != rb:
                    parent[ra] = rb
            else:
                owner[key] = face
    groups: dict[int, list[int]] = defaultdict(list)
    for face in faces.tolist():
        groups[find(face)].append(face)
    return [np.asarray(g, np.int64) for g in groups.values()]


def _extrude_region(mesh: MeshData, faces, offset_fn) -> EditResult:  # type: ignore[no-untyped-def]
    """Détache les faces sélectionnées, les déplace (``offset_fn``) et crée les parois latérales.

    ``offset_fn(islands, region_positions, render_ids, uvs) -> (new_positions, new_uvs)``.
    """
    faces = np.unique(np.asarray(list(faces), np.int64))
    faces = faces[(faces >= 0) & (faces < mesh.triangle_count)]
    _require(faces, "Sélectionnez au moins une face.")
    topo = topology(mesh)
    positions = mesh.positions.astype(np.float64)
    normals = mesh.normals.astype(np.float64)
    colors = _colors_or_default(mesh)
    uvs = None if mesh.uvs is None else mesh.uvs.astype(np.float64)
    indices = mesh.indices.astype(np.int64).copy()

    # Sommets de rendu de la région : copiés (les faces voisines gardent les originaux)
    region_render = np.unique(indices[faces].reshape(-1))
    copy_of = {int(r): len(positions) + i for i, r in enumerate(region_render.tolist())}
    new_positions = positions[region_render].copy()
    new_uvs = None if uvs is None else uvs[region_render].copy()
    islands = _islands(topo.tri, faces)
    moved_positions, moved_uvs = offset_fn(islands, new_positions, region_render, new_uvs)

    remap = np.vectorize(copy_of.__getitem__, otypes=[np.int64])
    original_tris = indices[faces].copy()
    indices[faces] = remap(indices[faces])

    # Arêtes de bord de la région : utilisées par une seule face de la région
    count: dict[tuple[int, int], int] = defaultdict(int)
    for face in faces.tolist():
        a, b, c = topo.tri[face].tolist()
        for u, v in ((a, b), (b, c), (c, a)):
            count[(min(u, v), max(u, v))] += 1
    wall_pos: list[np.ndarray] = []
    wall_uv: list[np.ndarray] = []
    wall_colors: list[np.ndarray] = []
    wall_tris: list[tuple[int, int, int]] = []
    base = len(positions) + len(region_render)
    for row, face in enumerate(faces.tolist()):
        render = original_tris[row]
        logical = topo.tri[face]
        for k in range(3):
            a_l, b_l = int(logical[k]), int(logical[(k + 1) % 3])
            if count[(min(a_l, b_l), max(a_l, b_l))] != 1:
                continue
            a_r, b_r = int(render[k]), int(render[(k + 1) % 3])
            a_n = moved_positions[copy_of[a_r] - len(positions)]
            b_n = moved_positions[copy_of[b_r] - len(positions)]
            start = base + len(wall_pos)
            wall_pos.extend([positions[a_r], positions[b_r], b_n, a_n])
            wall_colors.extend([colors[a_r], colors[b_r], colors[b_r], colors[a_r]])
            if uvs is not None:
                ua, ub = uvs[a_r], uvs[b_r]
                edge_uv = ub - ua
                edge_len = float(np.linalg.norm(positions[b_r] - positions[a_r]))
                height = float(np.linalg.norm(a_n - positions[a_r]))
                perp = np.array([-edge_uv[1], edge_uv[0]])
                scale = height / edge_len if edge_len > 1e-12 else 0.0
                wall_uv.extend([ua, ub, ub + perp * scale, ua + perp * scale])
            wall_tris.append((start, start + 1, start + 2))
            wall_tris.append((start, start + 2, start + 3))

    all_positions = np.vstack([positions, moved_positions, np.asarray(wall_pos).reshape(-1, 3)])
    all_colors = np.vstack([colors, colors[region_render], np.asarray(wall_colors, np.uint8).reshape(-1, 4)])
    all_uvs = None
    if uvs is not None:
        all_uvs = np.vstack([uvs, moved_uvs, np.asarray(wall_uv).reshape(-1, 2)])
    all_indices = np.vstack([indices, np.asarray(wall_tris, np.int64).reshape(-1, 3)])
    old_normals = np.vstack([normals, normals[region_render], np.zeros((len(wall_pos), 3))])
    affected = np.zeros(len(all_positions), bool)
    affected[len(positions) :] = True
    all_normals = _refresh_normals(all_positions, all_indices, old_normals, affected)
    compacted = _compact(all_positions, all_indices, all_normals, all_colors, all_uvs)
    result = EditResult(_build(mesh, *compacted), FACE, uv_changed=uvs is not None and bool(wall_pos))
    result.selection = {int(f) for f in faces}  # les faces de la région gardent leur rang
    if wall_pos and uvs is not None:
        result.warnings.append(
            "Les UV des nouvelles parois sont générées par projection depuis le bord : vérifiez la "
            "texture (projection UV automatique disponible)."
        )
    elif uvs is None:
        result.warnings.append("Ce maillage n'a pas d'UV : aucune coordonnée de texture n'a été générée.")
    return result


def extrude_faces(mesh: MeshData, faces, distance: float) -> EditResult:  # type: ignore[no-untyped-def]
    """Extrusion de région : les faces sélectionnées avancent le long de leur normale moyenne."""
    if abs(distance) < 1e-9:
        raise EditError("La distance d'extrusion doit être non nulle.")

    def offset(islands, new_positions, region_render, new_uvs):  # type: ignore[no-untyped-def]
        topo = topology(mesh)
        normals = face_normals(mesh.positions, mesh.indices)
        moved = new_positions.copy()
        index_of = {int(r): i for i, r in enumerate(region_render.tolist())}
        for island in islands:
            direction = normals[island].mean(axis=0)
            length = np.linalg.norm(direction)
            render = np.unique(mesh.indices[island].reshape(-1))
            rows = np.asarray([index_of[int(r)] for r in render])
            if length > 0.3:  # région assez plane : direction commune
                moved[rows] += direction / length * distance
                continue
            logical_normals = np.zeros((topo.vertex_count, 3))  # région fermée ou très courbe
            for face in island.tolist():
                for v in topo.tri[face]:
                    logical_normals[v] += normals[face]
            for row, r in zip(rows, render, strict=True):
                n = logical_normals[topo.vertex_of[r]]
                norm = np.linalg.norm(n)
                if norm > 1e-12:
                    moved[row] += n / norm * distance
        return moved, new_uvs

    return _extrude_region(mesh, faces, offset)


def inset_faces(mesh: MeshData, faces, amount: float) -> EditResult:  # type: ignore[no-untyped-def]
    """Inset : chaque région est réduite vers son centre (``amount`` entre 0 et 1) et entourée
    d'une bande de faces. Les UV de la région sont réduites de la même façon."""
    if not 0.0 < amount < 1.0:
        raise EditError("L'épaisseur d'inset doit être comprise entre 0 et 100 %.")

    def offset(islands, new_positions, region_render, new_uvs):  # type: ignore[no-untyped-def]
        moved = new_positions.copy()
        uvs = None if new_uvs is None else new_uvs.copy()
        index_of = {int(r): i for i, r in enumerate(region_render.tolist())}
        for island in islands:
            render = np.unique(mesh.indices[island].reshape(-1))
            rows = np.asarray([index_of[int(r)] for r in render])
            center = moved[rows].mean(axis=0)
            moved[rows] = center + (moved[rows] - center) * (1.0 - amount)
            if uvs is not None:
                uv_center = uvs[rows].mean(axis=0)
                uvs[rows] = uv_center + (uvs[rows] - uv_center) * (1.0 - amount)
        return moved, uvs

    result = _extrude_region(mesh, faces, offset)
    result.warnings = [w for w in result.warnings if "parois" not in w]
    if mesh.uvs is not None:
        result.uv_changed = True
        result.warnings.append("Les UV de la région ont été réduites avec la géométrie (inset).")
    return result


# --- Suppression, séparation, fusion ----------------------------------------------------


def delete_faces(mesh: MeshData, faces) -> EditResult:  # type: ignore[no-untyped-def]
    faces = np.unique(np.asarray(list(faces), np.int64))
    faces = faces[(faces >= 0) & (faces < mesh.triangle_count)]
    _require(faces, "Sélectionnez au moins une face.")
    keep = np.ones(mesh.triangle_count, bool)
    keep[faces] = False
    if not keep.any():
        raise EditError("Supprimer toutes les faces viderait la pièce : supprimez plutôt l'objet.")
    compacted = _compact(mesh.positions, mesh.indices[keep], mesh.normals, _colors_or_default(mesh), mesh.uvs)
    return EditResult(_build(mesh, *compacted), FACE, set())


def delete_vertices(mesh: MeshData, vertices) -> EditResult:  # type: ignore[no-untyped-def]
    """Supprime les sommets et toutes les faces qui les utilisent."""
    vertices = to_vertices(mesh, VERTEX, vertices)
    _require(vertices, "Aucun sommet sélectionné.")
    topo = topology(mesh)
    mask = np.zeros(topo.vertex_count, bool)
    mask[vertices] = True
    return delete_faces(mesh, np.flatnonzero(mask[topo.tri].any(axis=1)))


def separate_faces(mesh: MeshData, faces) -> EditResult:  # type: ignore[no-untyped-def]
    """Sépare les faces sélectionnées : ``mesh`` = le reste, ``extra`` = la partie détachée."""
    faces = np.unique(np.asarray(list(faces), np.int64))
    faces = faces[(faces >= 0) & (faces < mesh.triangle_count)]
    _require(faces, "Sélectionnez au moins une face.")
    if len(faces) == mesh.triangle_count:
        raise EditError("Toutes les faces sont sélectionnées : dupliquez plutôt l'objet.")
    part = _compact(mesh.positions, mesh.indices[faces], mesh.normals, _colors_or_default(mesh), mesh.uvs)
    rest = delete_faces(mesh, faces)
    detached = _build(mesh, *part)
    detached.name = f"{mesh.name} (séparé)"
    rest.extra = detached
    return rest


def merge_vertices(mesh: MeshData, element: str, items) -> EditResult:  # type: ignore[no-untyped-def]
    """Fusionne les sommets sélectionnés en leur centre ; les faces dégénérées disparaissent."""
    vertices = to_vertices(mesh, element, items)
    if len(vertices) < 2:
        raise EditError("Sélectionnez au moins deux sommets à fusionner.")
    topo = topology(mesh)
    center = topo.positions[vertices].mean(axis=0)
    moved = np.isin(topo.vertex_of, vertices)
    positions = mesh.positions.astype(np.float64).copy()
    positions[moved] = center
    vertex_of = topo.vertex_of.copy()
    vertex_of[moved] = int(vertices[0])
    indices = _drop_degenerate(mesh.indices.astype(np.int64), vertex_of)
    if not len(indices):
        raise EditError("La fusion supprimerait toutes les faces.")
    affected = np.zeros(len(positions), bool)
    affected[moved] = True
    normals = _refresh_normals(positions, indices, mesh.normals, affected)
    result = _build(mesh, *_compact(positions, indices, normals, _colors_or_default(mesh), mesh.uvs))
    keys = np.round(topology(result).positions / WELD_TOLERANCE)
    merged = np.flatnonzero((keys == np.round(center / WELD_TOLERANCE)).all(axis=1))
    return EditResult(result, VERTEX, {int(v) for v in merged})


def merge_by_distance(mesh: MeshData, threshold: float) -> EditResult:
    """Soude les sommets logiques plus proches que ``threshold`` (regroupement glouton par grille)."""
    if threshold <= 0:
        raise EditError("La distance de fusion doit être positive.")
    topo = topology(mesh)
    cells: dict[tuple[int, ...], list[int]] = defaultdict(list)
    target = np.arange(topo.vertex_count)
    offsets = [(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)]
    for index, point in enumerate(topo.positions):
        cell = tuple(np.floor(point / threshold).astype(int).tolist())
        found = next(
            (
                other
                for dx, dy, dz in offsets
                for other in cells.get((cell[0] + dx, cell[1] + dy, cell[2] + dz), ())
                if np.linalg.norm(topo.positions[other] - point) <= threshold
            ),
            None,
        )
        if found is None:
            cells[cell].append(index)
        else:
            target[index] = found
    merged = int((target != np.arange(topo.vertex_count)).sum())
    if merged == 0:
        return EditResult(
            mesh, VERTEX, set(), [f"Aucun sommet à moins de {threshold:g} m : rien à fusionner."]
        )
    render_target = target[topo.vertex_of]
    positions = topo.positions[render_target]
    indices = _drop_degenerate(mesh.indices.astype(np.int64), render_target)
    if not len(indices):
        raise EditError("La fusion supprimerait toutes les faces.")
    normals = compute_vertex_normals(positions, indices)
    compacted = _compact(positions, indices, normals, _colors_or_default(mesh), mesh.uvs)
    return EditResult(_build(mesh, *compacted), VERTEX, set(), [f"{merged} sommet(s) fusionné(s)."])


# --- Normales -------------------------------------------------------------------------


def recalculate_normals(mesh: MeshData) -> EditResult:
    """Normales lissées recalculées (les coutures existantes restent des arêtes vives)."""
    normals = compute_vertex_normals(mesh.positions, mesh.indices)
    return EditResult(
        _build(mesh, mesh.positions, mesh.indices, normals, _colors_or_default(mesh), mesh.uvs), FACE, set()
    )


def flip_faces(mesh: MeshData, faces=None) -> EditResult:  # type: ignore[no-untyped-def]
    indices = mesh.indices.astype(np.int64).copy()
    chosen = np.arange(len(indices)) if faces is None else np.asarray(sorted(faces), np.int64)
    _require(chosen, "Sélectionnez au moins une face.")
    indices[chosen] = indices[chosen][:, [0, 2, 1]]
    affected = np.zeros(mesh.vertex_count, bool)
    affected[indices[chosen].reshape(-1)] = True
    normals = _refresh_normals(mesh.positions, indices, mesh.normals, affected)
    return EditResult(
        _build(mesh, mesh.positions, indices, normals, _colors_or_default(mesh), mesh.uvs),
        FACE,
        {int(f) for f in chosen},
    )


def consistent_flips(positions: np.ndarray, tri: np.ndarray) -> np.ndarray:
    """Faces à retourner pour un enroulement cohérent, orienté vers l'extérieur.

    Parcours en largeur des faces voisines : deux faces cohérentes parcourent leur arête commune
    en sens opposés. Chaque partie connexe est ensuite orientée pour que son volume signé soit
    positif (normales sortantes pour une pièce fermée).
    """
    by_edge: dict[tuple[int, int], list[int]] = defaultdict(list)
    rows = tri.tolist()
    for face, (a, b, c) in enumerate(rows):
        for u, v in ((a, b), (b, c), (c, a)):
            by_edge[(min(u, v), max(u, v))].append(face)
    flip = np.zeros(len(rows), bool)
    seen = np.zeros(len(rows), bool)

    def forward(face: int, u: int, v: int) -> bool:
        a, b, c = rows[face]
        along = (a, b) == (u, v) or (b, c) == (u, v) or (c, a) == (u, v)
        return along != bool(flip[face])

    for start in range(len(rows)):
        if seen[start]:
            continue
        seen[start] = True
        component, queue = [start], [start]
        while queue:
            face = queue.pop()
            a, b, c = rows[face]
            for u, v in ((a, b), (b, c), (c, a)):
                shared = by_edge[(min(u, v), max(u, v))]
                if len(shared) != 2:  # arête non manifold ou bord : pas de propagation
                    continue
                for other in shared:
                    if seen[other]:
                        continue
                    seen[other] = True
                    if forward(face, u, v) == forward(other, u, v):  # même sens : incohérent
                        flip[other] = True
                    component.append(other)
                    queue.append(other)
        members = np.asarray(component)
        oriented = tri[members].copy()
        oriented[flip[members]] = oriented[flip[members]][:, [0, 2, 1]]
        p = positions[oriented]
        if float(np.einsum("ij,ij->i", p[:, 0], np.cross(p[:, 1], p[:, 2])).sum()) < 0:
            flip[members] = ~flip[members]
    return np.flatnonzero(flip)


def make_normals_consistent(mesh: MeshData) -> EditResult:
    """Oriente toutes les faces de façon cohérente, vers l'extérieur."""
    topo = topology(mesh)
    if not len(topo.tri):
        raise EditError("Le maillage ne contient aucune face.")
    flipped = consistent_flips(topo.positions, topo.tri)
    if not len(flipped):
        return EditResult(mesh, FACE, set(), ["Les normales sont déjà orientées de façon cohérente."])
    result = flip_faces(mesh, flipped)
    result.warnings.append(f"{len(flipped)} face(s) réorientée(s).")
    return result


# --- Symétrie -----------------------------------------------------------------------------


def mirrored(mesh: MeshData, axis: int, origin: float = 0.0) -> MeshData:
    """Copie miroir de la géométrie (enroulement inversé pour garder les normales vers l'extérieur)."""
    positions = mesh.positions.astype(np.float64).copy()
    positions[:, axis] = 2.0 * origin - positions[:, axis]
    normals = mesh.normals.astype(np.float64).copy()
    normals[:, axis] *= -1.0
    indices = mesh.indices.astype(np.int64)[:, [0, 2, 1]]
    return _build(mesh, positions, indices, normals, _colors_or_default(mesh), mesh.uvs)


def symmetrize(mesh: MeshData, axis: int, keep_positive: bool = True, origin: float = 0.0) -> EditResult:
    """Coupe le maillage par le plan de symétrie, garde un côté et le recopie en miroir.

    La découpe (``trimesh.intersections.slice_faces_plane``) interpole les UV des sommets créés ;
    la moitié recopiée réutilise les mêmes UV (miroir de texture).
    """
    from trimesh.intersections import slice_faces_plane

    normal = np.zeros(3)
    normal[axis] = 1.0 if keep_positive else -1.0
    plane_origin = np.zeros(3)
    plane_origin[axis] = origin
    vertices, faces, uvs = slice_faces_plane(
        mesh.positions.astype(np.float64),
        mesh.indices.astype(np.int64),
        normal,
        plane_origin,
        uv=None if mesh.uvs is None else mesh.uvs.astype(np.float64),
    )
    if faces is None or not len(faces):
        raise EditError("Aucune face de ce côté du plan de symétrie.")
    vertices = np.asarray(vertices, np.float64)
    faces = np.asarray(faces, np.int64)
    mirror_vertices = vertices.copy()
    mirror_vertices[:, axis] = 2.0 * origin - mirror_vertices[:, axis]
    on_plane = np.abs(vertices[:, axis] - origin) < WELD_TOLERANCE * 10
    # sommets sur le plan : la copie réutilise le sommet d'origine (pas de couture d'éclairage)
    mirror_index = np.where(on_plane, np.arange(len(vertices)), np.arange(len(vertices)) + len(vertices))
    mirror_faces = mirror_index[faces][:, [0, 2, 1]]
    positions = np.vstack([vertices, mirror_vertices])
    positions[: len(vertices)][on_plane, axis] = origin
    indices = np.vstack([faces, mirror_faces])
    source_colors = _colors_or_default(mesh)
    uniform = source_colors.mean(axis=0).round().astype(np.uint8)
    colors = np.tile(uniform, (len(positions), 1))
    all_uvs = None if uvs is None else np.vstack([uvs, uvs])
    normals = compute_vertex_normals(positions, indices)
    result = EditResult(_build(mesh, *_compact(positions, indices, normals, colors, all_uvs)), FACE, set())
    if mesh.uvs is not None:
        result.uv_changed = True
        result.warnings.append(
            "La moitié recopiée réutilise les UV du côté conservé (texture en miroir) : textes et "
            "logos apparaîtront inversés de ce côté."
        )
    if len(np.unique(source_colors, axis=0)) > 1:
        result.warnings.append("Les couleurs par sommet ont été uniformisées.")
    return result


# --- UV ---------------------------------------------------------------------------------


def _uv_areas(mesh: MeshData) -> np.ndarray:
    if mesh.uvs is None or not mesh.triangle_count:
        return np.zeros(0)
    uv = mesh.uvs[mesh.indices].astype(np.float64)
    e1, e2 = uv[:, 1] - uv[:, 0], uv[:, 2] - uv[:, 0]
    return 0.5 * (e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])


def _areas(mesh: MeshData) -> np.ndarray:
    if not mesh.triangle_count:
        return np.zeros(0)
    tri = mesh.positions[mesh.indices].astype(np.float64)
    return 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)


def uv_stretch(before: MeshData, after: MeshData) -> float:
    """Variation moyenne (log) du rapport aire UV / aire 3D entre deux maillages de même topologie."""
    if before.uvs is None or after.uvs is None or before.triangle_count != after.triangle_count:
        return 0.0
    a0, a1 = _areas(before), _areas(after)
    u0, u1 = np.abs(_uv_areas(before)), np.abs(_uv_areas(after))
    valid = (a0 > 1e-12) & (a1 > 1e-12) & (u0 > 1e-14)
    if not valid.any():
        return 0.0
    ratio = (u1[valid] / a1[valid]) / (u0[valid] / a0[valid])
    return float(np.mean(np.abs(np.log(np.clip(ratio, 1e-6, 1e6)))))


@dataclass
class UVReport:
    status: str  # ok / warning / invalid / missing
    messages: list[str]
    degenerate: int = 0
    flipped: int = 0

    @property
    def label(self) -> str:
        return {
            "ok": "UV valides",
            "warning": "UV à vérifier",
            "invalid": "UV invalides",
            "missing": "Sans UV",
        }[self.status]


def uv_report(mesh: MeshData) -> UVReport:
    """Diagnostic des coordonnées de texture d'un maillage."""
    if mesh.uvs is None:
        return UVReport("missing", ["Aucune coordonnée de texture : les textures ne peuvent pas s'afficher."])
    if not np.isfinite(mesh.uvs).all():
        return UVReport("invalid", ["Coordonnées de texture non numériques (NaN / infini)."])
    if not mesh.triangle_count:
        return UVReport("ok", [])
    areas = _areas(mesh)
    uv_areas = _uv_areas(mesh)
    real = areas > 1e-10
    degenerate = int((real & (np.abs(uv_areas) < 1e-12)).sum())
    signs = np.sign(uv_areas[real & (np.abs(uv_areas) >= 1e-12)])
    flipped = int(min((signs > 0).sum(), (signs < 0).sum())) if len(signs) else 0
    messages = []
    status = "ok"
    share = degenerate / max(int(real.sum()), 1)
    if degenerate:
        messages.append(f"{degenerate} triangle(s) sans surface UV ({share:.0%}) : texture étirée.")
        status = "invalid" if share > 0.25 else "warning"
    if flipped and flipped / max(len(signs), 1) > 0.02:  # information : UV en miroir légitimes
        messages.append(f"{flipped} triangle(s) aux UV en miroir (courant après une symétrie).")
    return UVReport(status, messages, degenerate, flipped)


def box_project_uv(mesh: MeshData, scale: float = 1.0) -> EditResult:
    """Projection UV automatique « boîte » : chaque face projetée sur le plan de son axe dominant.

    Correction proposée quand une opération a invalidé les UV. Les sommets sont dédoublés aux
    changements de projection ; les normales existantes sont conservées.
    """
    if not mesh.triangle_count:
        raise EditError("Le maillage ne contient aucune face.")
    dominant = np.argmax(np.abs(face_normals(mesh.positions, mesh.indices)), axis=1)
    corners = mesh.indices.reshape(-1)
    positions = mesh.positions[corners].astype(np.float64)
    vertex_normals = mesh.normals[corners]
    colors = _colors_or_default(mesh)[corners]
    uvs = np.zeros((len(corners), 2))
    face_axis = np.repeat(dominant, 3)
    for axis, (u, v) in {0: (2, 1), 1: (0, 2), 2: (0, 1)}.items():
        rows = face_axis == axis
        uvs[rows, 0] = positions[rows, u] * scale
        uvs[rows, 1] = positions[rows, v] * scale
    # dédoublonnage des coins identiques (position, normale, UV)
    key = np.round(np.hstack([positions / WELD_TOLERANCE, vertex_normals * 1e4, uvs * 1e5])).astype(np.int64)
    _, first, inverse = np.unique(key, axis=0, return_index=True, return_inverse=True)
    indices = inverse.reshape(-1).reshape(-1, 3)
    result = _build(mesh, positions[first], indices, vertex_normals[first], colors[first], uvs[first])
    return EditResult(result, FACE, set(), ["UV régénérées par projection boîte."], uv_changed=True)


# --- Lancer de rayon et sélection écran ---------------------------------------------------


def ray_triangle(origin: np.ndarray, direction: np.ndarray, mesh: MeshData) -> tuple[int, float] | None:
    """Triangle touché en premier (indice, distance paramétrique), repère local du maillage."""
    if not mesh.triangle_count:
        return None
    tri = mesh.positions[mesh.indices].astype(np.float64)
    v0, e1, e2 = tri[:, 0], tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
    p = np.cross(direction, e2)
    det = np.einsum("ij,ij->i", e1, p)
    valid = np.abs(det) > 1e-12
    inv_det = np.zeros_like(det)
    inv_det[valid] = 1.0 / det[valid]
    s = origin - v0
    u = np.einsum("ij,ij->i", s, p) * inv_det
    q = np.cross(s, e1)
    v = (q @ direction) * inv_det
    t = np.einsum("ij,ij->i", e2, q) * inv_det
    hit = valid & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-9)
    if not hit.any():
        return None
    candidates = np.flatnonzero(hit)
    best = candidates[np.argmin(t[candidates])]
    return int(best), float(t[best])


def nearest_screen_point(points: np.ndarray, click: tuple[float, float], radius: float) -> int | None:
    """Indice du point écran (N, 2) le plus proche du clic, dans ``radius`` pixels."""
    if not len(points):
        return None
    distances = np.linalg.norm(points - np.asarray(click, np.float64), axis=1)
    distances[~np.isfinite(distances)] = np.inf
    best = int(np.argmin(distances))
    return best if distances[best] <= radius else None


def nearest_screen_segment(starts: np.ndarray, ends: np.ndarray, click, radius: float) -> int | None:  # type: ignore[no-untyped-def]
    """Indice du segment écran le plus proche du clic, dans ``radius`` pixels."""
    if not len(starts):
        return None
    p = np.asarray(click, np.float64)
    seg = ends - starts
    length2 = np.einsum("ij,ij->i", seg, seg)
    t = np.clip(np.einsum("ij,ij->i", p - starts, seg) / np.where(length2 > 1e-12, length2, 1.0), 0.0, 1.0)
    distances = np.linalg.norm(starts + seg * t[:, None] - p, axis=1)
    distances[~np.isfinite(distances)] = np.inf
    best = int(np.argmin(distances))
    return best if distances[best] <= radius else None
