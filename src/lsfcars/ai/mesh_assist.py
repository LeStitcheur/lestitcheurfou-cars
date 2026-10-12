"""AI Mesh Assistant : diagnostics, corrections déterministes, suggestions, validation humaine.

Quatre catégories distinctes, affichées séparément :

- **Diagnostics automatiques** (mesures exactes) : triangles, parties non connectées, trous
  (arêtes de bord), arêtes non manifold, faces dégénérées ou dupliquées, enroulement incohérent,
  normales inversées, état des UV.
- **Corrections déterministes** : algorithmes reproductibles (réorientation des normales,
  suppression des faces dégénérées / dupliquées, fusion des sommets, bouchage des petits trous,
  lissage, décimation par regroupement, suppression des petites pièces). Chacune retourne un
  nouveau maillage (``EditResult``) appliqué par l'historique : toujours annulable.
- **Suggestions** : règles heuristiques locales (pas de réseau de neurones), formulées comme des
  propositions.
- **Validation humaine** : opérations dont le résultat dépend d'un choix (symétrisation,
  suppression de pièces, bouchage des ouvertures) — jamais appliquées sans confirmation.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from lsfcars.scene import editmesh
from lsfcars.scene.editmesh import FACE, EditError, EditResult
from lsfcars.scene.mesh import MeshData, compute_vertex_normals

DIAGNOSTIC, FIX, SUGGESTION, HUMAN = "diagnostic", "fix", "suggestion", "human"
CATEGORY_LABELS = {
    DIAGNOSTIC: "Diagnostics automatiques",
    FIX: "Corrections déterministes",
    SUGGESTION: "Suggestions (heuristiques locales)",
    HUMAN: "Validation humaine requise",
}
FIXES: dict[str, str] = {
    "normals": "Réorienter les normales (enroulement cohérent, vers l'extérieur)",
    "degenerate": "Supprimer les faces dégénérées et dupliquées",
    "weld": "Fusionner les sommets proches",
    "holes": "Boucher les petits trous",
    "smooth": "Lisser (Taubin, sans rétrécissement)",
    "decimate": "Simplifier (regroupement de sommets)",
    "small_parts": "Supprimer les petites pièces isolées",
    "symmetrize": "Symétriser gauche / droite",
    "box_uv": "Projeter des UV (boîte)",
}
CONFIRM_FIXES = {"holes", "small_parts", "symmetrize", "decimate"}  # validation humaine obligatoire
GTA_TRIANGLE_HINT = 150_000  # ordre de grandeur indicatif d'un LOD haut de véhicule (non normatif)


def _thousands(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _components(tri: np.ndarray, vertex_count: int) -> np.ndarray:
    """Étiquette de composante connexe par face (union-find sur les sommets logiques)."""
    parent = list(range(vertex_count))

    def find(x: int) -> int:
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    for a, b, c in tri.tolist():
        ra = find(a)
        for other in (b, c):
            ro = find(other)
            if ro != ra:
                parent[ro] = ra
    if not len(tri):
        return np.zeros(0, np.int64)
    roots = np.array([find(int(v)) for v in tri[:, 0]])
    _, labels = np.unique(roots, return_inverse=True)
    return labels.reshape(-1)


def boundary_loops(tri: np.ndarray) -> list[list[int]]:
    """Boucles d'arêtes de bord (arêtes utilisées par une seule face), orientées par leur face.

    Le test se fait sur les arêtes non orientées : une face retournée ne crée pas de faux bord.
    """
    directed = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]])
    undirected = np.sort(directed, axis=1)
    _, inverse, counts = np.unique(undirected, axis=0, return_inverse=True, return_counts=True)
    single = counts[inverse.reshape(-1)] == 1
    nxt: dict[int, list[int]] = defaultdict(list)
    for a, b in directed[single].tolist():
        nxt[a].append(b)
    loops = []
    used: set[tuple[int, int]] = set()
    for start in list(nxt):
        for first in list(nxt[start]):
            if (start, first) in used:
                continue
            loop = [start]
            used.add((start, first))
            current = first
            guard = 0
            while current != start and guard < 200_000:
                loop.append(current)
                options = [n for n in nxt.get(current, []) if (current, n) not in used]
                if not options:
                    loop = []
                    break
                used.add((current, options[0]))
                current = options[0]
                guard += 1
            if len(loop) >= 3:
                loops.append(loop)
    return loops


def analyze(mesh: MeshData) -> dict:
    """Diagnostics exacts et liste classée des problèmes (catégorie, gravité, correction)."""
    topo = editmesh.topology(mesh)
    tri = topo.tri
    report: dict = {
        "triangles": int(mesh.triangle_count),
        "vertices": int(mesh.vertex_count),
        "logical_vertices": int(topo.vertex_count),
        "issues": [],
    }
    issues: list[dict] = report["issues"]

    def add(category: str, severity: str, text: str, fix: str | None = None) -> None:
        issues.append({"category": category, "severity": severity, "text": text, "fix": fix})

    if not len(tri):
        add(DIAGNOSTIC, "error", "Le maillage ne contient aucune face.")
        return report
    p = topo.positions[tri]
    areas = 0.5 * np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1)
    same = (tri[:, 0] == tri[:, 1]) | (tri[:, 1] == tri[:, 2]) | (tri[:, 0] == tri[:, 2])
    degenerate = int((same | (areas < 1e-12)).sum())
    duplicates = int(len(tri) - len(np.unique(np.sort(tri, axis=1), axis=0)))
    pairs = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]])
    pairs.sort(axis=1)
    _, counts = np.unique(pairs, axis=0, return_counts=True)
    boundary = int((counts == 1).sum())
    non_manifold = int((counts > 2).sum())
    labels = _components(tri, topo.vertex_count)
    sizes = np.bincount(labels)
    small = int((sizes < max(8, 0.01 * len(tri))).sum()) if len(sizes) > 1 else 0
    loops = boundary_loops(tri) if boundary else []
    inconsistent = len(editmesh.consistent_flips(topo.positions, tri)) if len(tri) <= 400_000 else -1
    volume = float(np.einsum("ij,ij->i", p[:, 0], np.cross(p[:, 1], p[:, 2])).sum() / 6.0)
    extent = topo.positions.max(axis=0) - topo.positions.min(axis=0)
    uv = editmesh.uv_report(mesh)
    report.update(
        {
            "components": int(len(sizes)),
            "small_components": small,
            "boundary_edges": boundary,
            "holes": len(loops),
            "largest_hole_edges": max((len(loop) for loop in loops), default=0),
            "non_manifold_edges": non_manifold,
            "degenerate": degenerate,
            "duplicates": duplicates,
            "inconsistent_faces": int(inconsistent),
            "signed_volume": round(volume, 4),
            "extent_m": [round(float(v), 3) for v in extent],
            "uv": uv.status,
        }
    )
    add(
        DIAGNOSTIC,
        "info",
        f"{_thousands(len(tri))} triangles, {_thousands(topo.vertex_count)} sommets soudés, "
        f"{len(sizes)} partie(s).",
    )
    if degenerate or duplicates:
        add(
            DIAGNOSTIC,
            "warning",
            f"{degenerate} face(s) dégénérée(s), {duplicates} face(s) dupliquée(s).",
            "degenerate",
        )
    if inconsistent > 0:
        add(
            DIAGNOSTIC,
            "warning",
            f"{inconsistent} face(s) à l'enroulement incohérent (normales inversées).",
            "normals",
        )
    elif volume < 0 and boundary == 0:
        add(DIAGNOSTIC, "warning", "Volume signé négatif : normales tournées vers l'intérieur.", "normals")
    if boundary:
        add(
            DIAGNOSTIC,
            "warning",
            f"{len(loops)} trou(s) ({boundary} arêtes de bord, "
            f"le plus grand : {report['largest_hole_edges']} arêtes).",
            "holes",
        )
    if non_manifold:
        add(
            DIAGNOSTIC, "warning", f"{non_manifold} arête(s) non manifold (partagées par plus de deux faces)."
        )
    if len(sizes) > 1:
        add(
            DIAGNOSTIC,
            "info",
            f"{len(sizes)} parties non connectées, dont {small} petite(s) pièce(s).",
            "small_parts" if small else None,
        )
    add(
        DIAGNOSTIC,
        "info" if uv.status == "ok" else "warning",
        f"UV : {uv.status}.",
        None if uv.status == "ok" else "box_uv",
    )

    for key in ("normals", "degenerate"):
        if any(i["fix"] == key for i in issues):
            add(FIX, "info", FIXES[key], key)
    if uv.status != "ok":
        add(FIX, "info", FIXES["box_uv"], "box_uv")
    add(FIX, "info", FIXES["weld"], "weld")
    add(FIX, "info", FIXES["smooth"], "smooth")

    if len(tri) > GTA_TRIANGLE_HINT:
        add(
            SUGGESTION,
            "info",
            f"Maillage dense ({_thousands(len(tri))} triangles) : une simplification vers "
            f"~{_thousands(GTA_TRIANGLE_HINT // 2)} triangles faciliterait l'édition (ordre de grandeur "
            "indicatif, non normatif).",
            "decimate",
        )
    if len(tri) > 20_000 and topo.vertex_count / len(tri) > 0.45:
        add(
            SUGGESTION,
            "info",
            "Surface régulière à facettes (maillage généré) : un lissage léger réduit les marches.",
            "smooth",
        )
    left = int((topo.positions[:, 0] < -1e-6).sum())
    right = int((topo.positions[:, 0] > 1e-6).sum())
    if left and right and abs(left - right) / max(left, right) > 0.15:
        asym = abs(left - right) / max(left, right)
        add(
            SUGGESTION,
            "info",
            f"Asymétrie gauche / droite marquée ({asym:.0%}) : la symétrisation peut aider.",
            "symmetrize",
        )
    add(
        SUGGESTION,
        "info",
        "Retopologie : un remaillage par Blender (voxel) produit une surface régulière à partir d'un "
        "maillage "
        "généré bruité (Vehicle Editor, si Blender est installé).",
    )

    add(
        HUMAN,
        "info",
        "Symétriser : choisir le côté à conserver (les détails asymétriques seront perdus).",
        "symmetrize",
    )
    if small:
        add(
            HUMAN,
            "info",
            f"Supprimer {small} petite(s) pièce(s) : vérifier qu'il ne s'agit pas de détails voulus.",
            "small_parts",
        )
    if loops:
        add(
            HUMAN,
            "info",
            "Boucher les trous : les ouvertures voulues (vitres, passages de roues) seraient fermées.",
            "holes",
        )
    if len(tri) > 2000:
        add(HUMAN, "info", "Simplifier : choisir le nombre de triangles visé (perte de détails).", "decimate")
    add(
        HUMAN,
        "info",
        "Préparation FiveM (hiérarchie, matériaux, collisions, LOD, export) : travail manuel dans le "
        "Vehicle Editor ; "
        "aucun maillage généré n'est utilisable en jeu sans ce travail.",
    )
    return report


# --- Corrections déterministes ------------------------------------------------------------------


def _result(mesh: MeshData, positions, indices, warnings: list[str], colors=None, uvs=None) -> EditResult:  # type: ignore[no-untyped-def]
    positions = np.asarray(positions, np.float64)
    indices = np.asarray(indices, np.int64).reshape(-1, 3)
    if colors is None:
        colors = mesh.colors
    if colors is None or len(colors) != len(positions):
        colors = np.full((len(positions), 4), 255, np.uint8)
    if uvs is not None and len(uvs) != len(positions):
        uvs = None
    used = np.zeros(len(positions), bool)
    used[indices.reshape(-1)] = True
    remap = np.full(len(positions), -1, np.int64)
    remap[used] = np.arange(int(used.sum()))
    positions, colors = positions[used], np.asarray(colors)[used]
    uvs = None if uvs is None else np.asarray(uvs)[used]
    indices = remap[indices]
    new = MeshData(
        mesh.name,
        positions.astype(np.float32),
        indices,
        compute_vertex_normals(positions, indices),
        colors.astype(np.uint8),
        mesh.color,
        None if uvs is None else uvs.astype(np.float32),
    )
    return EditResult(new, FACE, set(), warnings)


def _logical_colors(mesh: MeshData, topo) -> np.ndarray:  # type: ignore[no-untyped-def]
    source = mesh.colors if mesh.colors is not None else np.full((mesh.vertex_count, 4), 255, np.uint8)
    sums = np.zeros((topo.vertex_count, 4))
    np.add.at(sums, topo.vertex_of, source.astype(np.float64))
    return sums / np.maximum(np.bincount(topo.vertex_of, minlength=topo.vertex_count), 1)[:, None]


def fix_normals(mesh: MeshData) -> EditResult:
    return editmesh.make_normals_consistent(mesh)


def remove_degenerate(mesh: MeshData) -> EditResult:
    topo = editmesh.topology(mesh)
    tri = topo.tri
    p = topo.positions[tri]
    areas = 0.5 * np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1)
    same = (tri[:, 0] == tri[:, 1]) | (tri[:, 1] == tri[:, 2]) | (tri[:, 0] == tri[:, 2])
    keep = ~(same | (areas < 1e-12))
    _, first = np.unique(np.sort(tri, axis=1), axis=0, return_index=True)
    unique = np.zeros(len(tri), bool)
    unique[first] = True
    keep &= unique
    removed = int((~keep).sum())
    if not removed:
        return EditResult(mesh, FACE, set(), ["Aucune face dégénérée ou dupliquée."])
    if not keep.any():
        raise EditError("Toutes les faces seraient supprimées.")
    return _result(
        mesh,
        mesh.positions,
        mesh.indices.astype(np.int64)[keep],
        [f"{removed} face(s) supprimée(s)."],
        uvs=mesh.uvs,
    )


def weld(mesh: MeshData, threshold: float = 1e-4) -> EditResult:
    return editmesh.merge_by_distance(mesh, threshold)


def fill_holes(mesh: MeshData, max_edges: int = 64) -> EditResult:
    """Bouche les trous de ``max_edges`` arêtes au plus (éventail autour du barycentre)."""
    topo = editmesh.topology(mesh)
    loops = [loop for loop in boundary_loops(topo.tri) if len(loop) <= max_edges]
    if not loops:
        return EditResult(mesh, FACE, set(), [f"Aucun trou de {max_edges} arêtes ou moins."])
    colors = _logical_colors(mesh, topo)
    tri = topo.tri.tolist()
    points, point_colors = [], []
    for loop in loops:
        center = topo.vertex_count + len(points)
        points.append(topo.positions[loop].mean(axis=0))
        point_colors.append(colors[loop].mean(axis=0))
        for a, b in zip(loop, loop[1:] + loop[:1], strict=False):
            tri.append([b, a, center])  # sens inverse du bord : cohérent avec les faces voisines
    positions = np.vstack([topo.positions, np.asarray(points)])
    all_colors = np.vstack([colors, np.asarray(point_colors)]).round().astype(np.uint8)
    result = _result(
        mesh, positions, np.asarray(tri), [f"{len(loops)} trou(s) bouché(s)."], colors=all_colors
    )
    if mesh.uvs is not None:
        result.uv_changed = True
        result.warnings.append("Les UV ont été retirées (maillage ressoudé) : reprojetez-les si nécessaire.")
    return result


def remove_small_parts(mesh: MeshData, ratio: float = 0.01) -> EditResult:
    topo = editmesh.topology(mesh)
    labels = _components(topo.tri, topo.vertex_count)
    sizes = np.bincount(labels)
    if len(sizes) <= 1:
        return EditResult(mesh, FACE, set(), ["Une seule partie : rien à supprimer."])
    keep = sizes[labels] >= max(8, ratio * len(topo.tri))
    if not keep.any():
        raise EditError("Toutes les pièces sont petites : rien ne serait conservé.")
    removed = int(len(sizes) - len(np.unique(labels[keep])))
    if not removed:
        return EditResult(mesh, FACE, set(), ["Aucune petite pièce."])
    indices = mesh.indices.astype(np.int64)[keep]
    return _result(
        mesh, mesh.positions, indices, [f"{removed} petite(s) pièce(s) supprimée(s)."], uvs=mesh.uvs
    )


def smooth(mesh: MeshData, iterations: int = 4) -> EditResult:
    """Lissage de Taubin sur la topologie soudée (couleurs et UV conservées)."""
    from lsfcars.ai.engines.silhouette import taubin

    topo = editmesh.topology(mesh)
    positions = taubin(topo.positions, topo.tri, iterations)[topo.vertex_of]
    return _result(
        mesh, positions, mesh.indices.astype(np.int64), [f"Lissage ({iterations} itérations)."], uvs=mesh.uvs
    )


def _cluster(positions: np.ndarray, lo: np.ndarray, size: float) -> np.ndarray:
    keys = np.floor((positions - lo) / size).astype(np.int64)
    return np.unique(keys, axis=0, return_inverse=True)[1].reshape(-1)


def _clustered_faces(tri: np.ndarray, cluster: np.ndarray) -> np.ndarray:
    faces = cluster[tri]
    faces = faces[(faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2])]
    if not len(faces):
        return faces
    _, first = np.unique(np.sort(faces, axis=1), axis=0, return_index=True)
    return faces[np.sort(first)]


def decimate(mesh: MeshData, target_triangles: int) -> EditResult:
    """Simplification par regroupement de sommets (grille ajustée au nombre visé), déterministe."""
    topo = editmesh.topology(mesh)
    current = len(topo.tri)
    if target_triangles >= current:
        return EditResult(mesh, FACE, set(), ["Le maillage est déjà sous le nombre de triangles visé."])
    if target_triangles < 100:
        raise EditError("Nombre de triangles visé trop faible (100 au moins).")
    lo = topo.positions.min(axis=0)
    extent = float((topo.positions.max(axis=0) - lo).max()) or 1.0
    cells = max(4, int(np.sqrt(target_triangles / 2.0) * 1.2))
    best: tuple[np.ndarray, np.ndarray] | None = None
    for _ in range(16):  # recherche de la taille de cellule qui approche la cible
        cluster = _cluster(topo.positions, lo, extent / cells)
        faces = _clustered_faces(topo.tri, cluster)
        best = (cluster, faces)
        if len(faces) > target_triangles * 1.1:
            cells = max(4, int(cells / 1.2))
        elif len(faces) < target_triangles * 0.75:
            cells = int(cells * 1.15) + 1
        else:
            break
    assert best is not None
    cluster, faces = best
    if not len(faces):
        raise EditError("La simplification supprimerait toutes les faces.")
    k = int(cluster.max()) + 1
    weights = np.bincount(cluster, minlength=k)[:, None]
    positions = np.zeros((k, 3))
    np.add.at(positions, cluster, topo.positions)
    positions /= np.maximum(weights, 1)
    colors = np.zeros((k, 4))
    np.add.at(colors, cluster, _logical_colors(mesh, topo))
    colors = (colors / np.maximum(weights, 1)).round().astype(np.uint8)
    text = f"Simplification : {_thousands(current)} → {_thousands(len(faces))} triangles."
    result = _result(mesh, positions, faces, [text], colors=colors)
    if mesh.uvs is not None:
        result.uv_changed = True
        result.warnings.append("Les UV ont été retirées : reprojetez-les après simplification.")
    return result


def symmetrize(mesh: MeshData, keep_positive: bool = True, axis: int = 0, origin: float = 0.0) -> EditResult:
    return editmesh.symmetrize(mesh, axis, keep_positive, origin)


def box_uv(mesh: MeshData) -> EditResult:
    return editmesh.box_project_uv(mesh)


def operation(key: str, **options):  # type: ignore[no-untyped-def]
    """Fonction ``MeshData → EditResult`` d'une correction (pour ``VehicleEditor.edit``)."""
    table = {
        "normals": fix_normals,
        "degenerate": remove_degenerate,
        "weld": lambda m: weld(m, float(options.get("threshold", 1e-4))),
        "holes": lambda m: fill_holes(m, int(options.get("max_edges", 64))),
        "small_parts": lambda m: remove_small_parts(m, float(options.get("ratio", 0.01))),
        "smooth": lambda m: smooth(m, int(options.get("iterations", 4))),
        "decimate": lambda m: decimate(m, int(options.get("target", 50_000))),
        "symmetrize": lambda m: symmetrize(m, bool(options.get("keep_positive", True))),
        "box_uv": box_uv,
    }
    if key not in table:
        raise EditError(f"Correction inconnue : {key}")
    return table[key]
