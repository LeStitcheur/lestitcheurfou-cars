"""Design Comparison Studio (calculs) : différences géométriques réelles entre deux véhicules.

Les mesures portent sur les données du projet (sommets, pièces, dimensions, silhouettes
rendues avec un cadrage commun). Ce sont des **mesures techniques** : elles décrivent l'ampleur
des changements, pas leur suffisance juridique.
"""

from __future__ import annotations

import numpy as np

from lsfcars.lorefriendly import preview
from lsfcars.lorefriendly.components import COMPONENT_LABELS
from lsfcars.lorefriendly.geometry import MeshEntry, VehicleState

COMPARE_VIEWS = ("left", "front", "back", "top")
LIMITS = (
    "Mesures techniques calculées sur la géométrie : recouvrement de silhouettes (rapport "
    "intersection / union des contours rendus, cadrage commun, résolution limitée) et "
    "déplacements de sommets. Elles ne mesurent ni la ressemblance perçue, ni les détails de "
    "texture, et ne constituent pas une évaluation juridique."
)
DIMENSION_LABELS = {
    "length": "Longueur",
    "width": "Largeur",
    "height": "Hauteur",
    "wheelbase": "Empattement",
    "track": "Voies",
    "ground_clearance": "Garde au sol (caisse)",
}


def visual_points(state: VehicleState) -> np.ndarray:
    pts = [state.world_points(e) for e in state.active_entries() if e.kind != "technical"]
    for part in state.new_parts:
        p = part.mesh.positions.astype(np.float64)
        pts.append(p @ part.world[:3, :3].T + part.world[:3, 3])
    return np.vstack(pts) if pts else np.zeros((0, 3))


def dimensions(state: VehicleState) -> dict:
    pts = visual_points(state)
    axes = state.frame.axes
    if not len(pts):
        return {}
    size = pts.max(axis=0) - pts.min(axis=0)
    result = {
        "length": float(size[axes.longitudinal_axis]),
        "width": float(size[axes.lateral_axis]),
        "height": float(size[axes.up_axis]),
    }
    centers = [w.center + state.owner_move(w.node_ids[0]) for w in state.components.wheels]
    if len(centers) >= 2:
        lateral = [c[axes.lateral_axis] for c in centers]
        along = [c[axes.longitudinal_axis] for c in centers]
        result["track"] = float(max(lateral) - min(lateral))
        result["wheelbase"] = float(max(along) - min(along))
    body = state.body_points()
    if len(body):
        result["ground_clearance"] = float(body[:, axes.up_axis].min() - pts[:, axes.up_axis].min())
    return result


def _keyed(state: VehicleState, origin: dict[str, str]) -> dict[str, MeshEntry]:
    return {origin.get(e.node_id, e.node_id): e for e in state.active_entries() if e.kind != "technical"}


def compare(
    a: VehicleState,
    b: VehicleState,
    a_origin: dict[str, str] | None = None,
    b_origin: dict[str, str] | None = None,
    size: int = 160,
) -> dict:
    """Compare ``b`` à ``a``. ``*_origin`` : nœud → nœud source d'origine (copies de variantes)."""
    entries_a, entries_b = _keyed(a, a_origin or {}), _keyed(b, b_origin or {})
    components: list[dict] = []
    for key, entry_a in entries_a.items():
        label = COMPONENT_LABELS.get(entry_a.kind, entry_a.kind)
        entry_b = entries_b.get(key)
        maximum: float | None = None
        mean: float | None = None
        if entry_b is None:
            status = "remplacé ou masqué"
        else:
            pa, pb = a.world_points(entry_a), b.world_points(entry_b)
            if len(pa) == len(pb) and len(pa):
                dist = np.linalg.norm(pb - pa, axis=1)
                maximum, mean = float(dist.max()), float(dist.mean())
                status = "identique" if maximum < 1e-4 else "déformé" if maximum > 1e-3 else "quasi identique"
            else:
                status = "géométrie différente"
        components.append(
            {"kind": entry_a.kind, "label": label, "name": entry_a.mesh.name, "status": status,
             "max": maximum, "mean": mean}
        )  # fmt: skip
    added = [
        {
            "kind": e.kind,
            "label": COMPONENT_LABELS.get(e.kind, e.kind),
            "name": e.mesh.name,
            "status": "ajouté",
        }
        for key, e in entries_b.items()
        if key not in entries_a
    ]
    added += [
        {"kind": p.kind, "label": COMPONENT_LABELS.get(p.kind, p.kind), "name": p.name, "status": "ajouté"}
        for p in b.new_parts
    ]
    dims_a, dims_b = dimensions(a), dimensions(b)
    items_a, items_b = a.render_list(), b.render_list()
    silhouettes = {}
    for view in COMPARE_VIEWS:
        fit = preview.common_fit([items_a, items_b], view)
        mask_a = preview.silhouette(items_a, view, size, fit)
        mask_b = preview.silhouette(items_b, view, size, fit)
        silhouettes[view] = preview.iou(mask_a, mask_b)
    return {
        "dimensions": {
            "a": dims_a,
            "b": dims_b,
            "delta": {k: dims_b[k] - dims_a[k] for k in dims_a if k in dims_b},
        },
        "silhouettes": silhouettes,
        "components": components,
        "added": added,
        "deformed": sum(1 for c in components if c["status"] == "déformé"),
        "replaced": sum(1 for c in components if c["status"] == "remplacé ou masqué"),
        "limits": LIMITS,
    }


def displacement_overlay(a: VehicleState, b: VehicleState, b_origin: dict[str, str]) -> np.ndarray:
    """Points colorés (N, 7) des sommets déplacés de ``b`` (position + couleur), pour le viewport."""
    rows = []
    entries_a = {e.node_id: e for e in a.active_entries()}
    for entry in b.active_entries():
        source = entries_a.get(b_origin.get(entry.node_id, entry.node_id))
        if source is None or source.mesh.vertex_count != entry.mesh.vertex_count:
            continue
        pa, pb = a.world_points(source), b.world_points(entry)
        dist = np.linalg.norm(pb - pa, axis=1)
        moved = dist > 2e-3
        if not moved.any():
            continue
        t = np.clip(dist[moved] / max(float(dist.max()), 1e-6), 0, 1)
        colors = np.column_stack([0.2 + 0.8 * t, 0.75 - 0.35 * t, 1.0 - 0.8 * t, np.full_like(t, 0.9)])
        rows.append(np.hstack([pb[moved], colors]))
    return np.vstack(rows).astype(np.float32) if rows else np.zeros((0, 7), np.float32)
