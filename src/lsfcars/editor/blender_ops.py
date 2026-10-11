"""Opérations géométriques déléguées à Blender (processus auxiliaire) : biseau d'arêtes.

Le biseau utilise ``bmesh.ops.bevel`` de Blender, un algorithme éprouvé, plutôt qu'une
réimplémentation partielle. L'outil n'est proposé que si Blender est détecté ; la tâche
s'exécute dans un processus séparé, avec délai maximal et annulation. Les UV sont interpolées
par Blender.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path

import numpy as np

from lsfcars.core.logging_setup import get_logger
from lsfcars.importers.fbx_blender import find_blender
from lsfcars.scene import editmesh
from lsfcars.scene.editmesh import EditError, EditResult
from lsfcars.scene.mesh import MeshData, compute_vertex_normals

log = get_logger(__name__)

BEVEL_SCRIPT = r"""
import sys
import bmesh
import numpy as np

args = sys.argv[sys.argv.index("--") + 1:]
source, target, width, segments = args[0], args[1], float(args[2]), int(args[3])
data = np.load(source)
positions, faces, edges = data["positions"], data["tri"], data["edges"]
corner_uv = data["corner_uv"] if "corner_uv" in data.files else None
bm = bmesh.new()
verts = [bm.verts.new((float(p[0]), float(p[1]), float(p[2]))) for p in positions]
bm.verts.ensure_lookup_table()
uv_layer = bm.loops.layers.uv.new("UV") if corner_uv is not None else None
for index, face in enumerate(faces):
    try:
        created = bm.faces.new([verts[int(i)] for i in face])
    except ValueError:
        continue  # face dupliquée ou dégénérée
    if uv_layer is not None:
        for corner, loop in enumerate(created.loops):
            loop[uv_layer].uv = (float(corner_uv[index, corner, 0]), float(corner_uv[index, corner, 1]))
bm.verts.index_update()
bm.edges.ensure_lookup_table()
wanted = {(int(a), int(b)) for a, b in edges}
geom = [e for e in bm.edges if tuple(sorted((e.verts[0].index, e.verts[1].index))) in wanted]
if not geom:
    print("LSF_ERROR aucune arête retrouvée")
    sys.exit(3)
bmesh.ops.bevel(
    bm, geom=geom, offset=width, segments=segments, affect="EDGES", profile=0.5, clamp_overlap=True
)
bmesh.ops.triangulate(bm, faces=bm.faces[:])
out_pos, out_uv = [], []
for face in bm.faces:
    for loop in face.loops:
        out_pos.append(tuple(loop.vert.co))
        out_uv.append(tuple(loop[uv_layer].uv) if uv_layer is not None else (0.0, 0.0))
np.savez(target, positions=np.array(out_pos, dtype=np.float64), uvs=np.array(out_uv, dtype=np.float64),
         has_uv=np.array([uv_layer is not None]))
print("LSF_OK", len(bm.faces))
"""


def bevel_available() -> tuple[bool, str]:
    executable = find_blender()
    if executable is None:
        return (
            False,
            "Nécessite Blender (non détecté) : installez Blender ou indiquez son chemin dans les paramètres.",
        )
    return True, f"Biseau calculé par Blender ({executable.parent.name})"


def bevel_edges(
    mesh: MeshData,
    edges: Iterable[tuple[int, int]],
    width: float,
    segments: int = 2,
    timeout_s: float = 180,
    on_task: Callable[[object], None] | None = None,
) -> EditResult:
    """Biseaute les arêtes logiques ``edges`` (paires de sommets logiques) avec Blender."""
    from lsfcars.fivem.sollumz import BlenderTask

    edges = [tuple(sorted((int(a), int(b)))) for a, b in edges]
    if not edges:
        raise EditError("Sélectionnez au moins une arête à biseauter.")
    if width <= 0:
        raise EditError("La largeur du biseau doit être positive.")
    available, reason = bevel_available()
    if not available:
        raise EditError(reason)
    topo = editmesh.topology(mesh)
    with tempfile.TemporaryDirectory(prefix="lsf_bevel_") as tmp:
        folder = Path(tmp)
        arrays = {"positions": topo.positions, "tri": topo.tri, "edges": np.asarray(edges, np.int64)}
        if mesh.uvs is not None:
            arrays["corner_uv"] = mesh.uvs[mesh.indices].astype(np.float64)
        np.savez(folder / "in.npz", **arrays)
        (folder / "bevel.py").write_text(BEVEL_SCRIPT, encoding="utf-8")
        task = BlenderTask(
            [
                "--background",
                "--factory-startup",
                "--python",
                str(folder / "bevel.py"),
                "--",
                str(folder / "in.npz"),
                str(folder / "out.npz"),
                str(width),
                str(max(int(segments), 1)),
            ],
            timeout_s,
        )
        if on_task is not None:
            on_task(task)
        code = task.run()
        if task.cancelled:
            raise EditError("Biseau annulé.")
        output = folder / "out.npz"
        if code != 0 or not output.is_file():
            detail = next((line for line in task.lines if "LSF_ERROR" in line or "Error" in line), "")
            raise EditError(f"Blender n'a pas pu calculer le biseau. {detail}".strip())
        with np.load(output) as data:
            corners = data["positions"].astype(np.float64)
            corner_uvs = data["uvs"].astype(np.float64)
            has_uv = bool(data["has_uv"][0])
    if not len(corners):
        raise EditError("Le biseau n'a produit aucune face.")
    keys = np.round(corners / editmesh.WELD_TOLERANCE).astype(np.int64)
    if has_uv:
        keys = np.hstack([keys, np.round(corner_uvs * 1e5).astype(np.int64)])
    _, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    positions = corners[first]
    indices = inverse.reshape(-1, 3)
    colors = None
    if mesh.colors is not None:
        colors = np.tile(mesh.colors.mean(axis=0).round().astype(np.uint8), (len(positions), 1))
    result = MeshData(
        mesh.name,
        positions.astype(np.float32),
        indices,
        compute_vertex_normals(positions, indices),
        colors,
        mesh.color,
        corner_uvs[first].astype(np.float32) if has_uv else None,
    )
    warnings = [f"Biseau calculé par Blender ({len(edges)} arête(s), {segments} segment(s))."]
    if has_uv:
        warnings.append("UV interpolées par Blender sur les faces du biseau.")
    log.info("Biseau Blender : %d → %d triangles", mesh.triangle_count, result.triangle_count)
    return EditResult(result, editmesh.FACE, set(), warnings, uv_changed=has_uv)
