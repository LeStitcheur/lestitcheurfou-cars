"""AI Mesh Assistant, AI Texture Creator, Lore Friendly AI Assistant (tests réels, sans Qt)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import trimesh
from PIL import Image

from lsfcars.ai import lore, mesh_assist
from lsfcars.ai import texture as tex
from lsfcars.ai.engines.silhouette import _mask_crop, surface_nets
from lsfcars.scene.editmesh import EditError
from lsfcars.scene.mesh import MeshData

REFERENCES = Path(__file__).resolve().parents[1] / "samples" / "references"


def mesh_from(tm: trimesh.Trimesh, name: str = "test") -> MeshData:
    colors = np.tile(np.array([200, 40, 40, 255], np.uint8), (len(tm.vertices), 1))
    return MeshData(name, tm.vertices, tm.faces, colors=colors)


def broken_mesh() -> MeshData:
    """Sphère trouée, une face retournée, une face dupliquée et une petite pièce isolée."""
    sphere = trimesh.creation.icosphere(subdivisions=3, radius=1.0)
    faces = np.delete(sphere.faces.copy(), [0, 1, 2], axis=0)  # trois trous (faces non voisines)
    faces[10] = faces[10][::-1]  # normale inversée
    faces = np.vstack([faces, faces[20:21]])  # face dupliquée
    small = trimesh.creation.box(extents=(0.05, 0.05, 0.05))
    small.apply_translation((3, 0, 0))
    vertices = np.vstack([sphere.vertices, small.vertices])
    faces = np.vstack([faces, small.faces + len(sphere.vertices)])
    return mesh_from(trimesh.Trimesh(vertices, faces, process=False))


# --- AI Mesh Assistant ----------------------------------------------------------------------------


def test_mesh_diagnostics_are_exact_and_categorised():
    report = mesh_assist.analyze(broken_mesh())
    assert report["boundary_edges"] == 9 and report["holes"] >= 2  # deux trous se touchent par un sommet
    assert report["components"] == 2 and report["small_components"] == 1
    assert report["duplicates"] == 1
    assert report["inconsistent_faces"] >= 1
    assert report["uv"] == "missing"
    categories = {issue["category"] for issue in report["issues"]}
    assert categories == {"diagnostic", "fix", "suggestion", "human"}
    assert any("FiveM" in i["text"] for i in report["issues"] if i["category"] == "human")


def test_deterministic_corrections():
    mesh = broken_mesh()
    fixed = mesh_assist.remove_degenerate(mesh).mesh
    assert mesh_assist.analyze(fixed)["duplicates"] == 0
    oriented = mesh_assist.fix_normals(fixed).mesh
    assert mesh_assist.analyze(oriented)["inconsistent_faces"] == 0
    closed = mesh_assist.fill_holes(oriented).mesh
    assert mesh_assist.analyze(closed)["holes"] == 0
    cleaned = mesh_assist.remove_small_parts(closed).mesh
    assert mesh_assist.analyze(cleaned)["components"] == 1
    assert (cleaned.colors[:, 0] == 200).all()  # couleurs conservées
    smoothed = mesh_assist.smooth(cleaned, 3).mesh
    assert smoothed.triangle_count == cleaned.triangle_count
    dense = mesh_from(trimesh.creation.icosphere(subdivisions=5))
    simplified = mesh_assist.decimate(dense, 2000).mesh
    assert 1000 < simplified.triangle_count < 2600
    with pytest.raises(EditError):
        mesh_assist.decimate(dense, 10)
    with pytest.raises(EditError):
        mesh_assist.operation("inconnue")


# --- AI Texture Creator ---------------------------------------------------------------------------


def silhouette_mesh() -> MeshData:
    field = np.zeros((24, 16, 40), np.float32)
    field[4:20, 2:13, 3:37] = 1.0
    vertices, faces = surface_nets(field)
    positions = (vertices - [12, 2, 20]) * np.array([0.09, 0.09, 0.11])
    return MeshData("caisse", positions, faces[:, ::-1])


def test_atlas_and_projection_with_sources():
    mesh = silhouette_mesh()
    atlas = tex.atlas_uv(mesh).mesh
    assert atlas.uvs.min() >= 0 and atlas.uvs.max() <= 1
    maps = tex.surface_maps(atlas, 256)
    assert maps.coverage.mean() > 0.05
    views = []
    for view, name in (("left", "demo_profil_gauche.png"), ("front", "demo_avant.png")):
        mask, rgb = _mask_crop(Image.open(REFERENCES / name), None)
        views.append(tex.ViewImage(view, rgb, mask))
    base, stats = tex.project_references(atlas, maps, views)
    assert base.shape == (256, 256, 4) and stats["projected_ratio"] > 0.2
    assert "right" in stats["mirrored_views"]  # un seul profil : l'autre flanc est supposé symétrique
    normal = tex.normal_from_height(base)
    assert normal[..., 2].mean() > 200  # normales majoritairement vers +Z (carte tangente)
    rough, metal = tex.rule_maps(base, "paint_metal")
    assert rough.shape[:2] == base.shape[:2] and metal.max() > 100
    variant = tex.variation(base, 0.5)
    assert variant.shape == base.shape and not np.array_equal(variant, base)
    assert set(tex.MAP_SOURCES) >= {"projection", "derived", "rules", "provider", "none"}


def test_logo_annotations_are_masked():
    rgb = np.full((100, 200, 3), 180, np.uint8)
    rgb[40:60, 80:120] = (255, 0, 0)  # « logo »
    masked, count = tex.mask_annotations(rgb, [{"kind": "logo", "rect": [0.4, 0.4, 0.6, 0.6]}])
    assert count == 1 and (masked[45:55, 85:115] == 180).all()
    untouched, none = tex.mask_annotations(rgb, [{"kind": "wheel", "rect": [0.4, 0.4, 0.6, 0.6]}])
    assert none == 0 and np.array_equal(untouched, rgb)


# --- Lore Friendly --------------------------------------------------------------------------------


def test_fictional_names_avoid_real_and_gta_brands():
    names = lore.brand_names("graine", 20)
    assert len(names) == 20 and len(set(names)) == 20
    assert not any(lore.is_forbidden(n) for n in names)
    assert (
        lore.is_forbidden("Vapid") and lore.is_forbidden("Ford Motors") and not lore.is_forbidden("Corvane")
    )
    assert lore.brand_names("graine", 5) == names[:5]  # déterministe


def test_three_proposals_and_cloud_filtering():
    report = {"fields": {"type": {"value": "suv"}, "body_color": {"value": "#204080"}}}
    proposals = lore.proposals(report, "projet")
    assert [p["level"] for p in proposals] == ["light", "balanced", "original"]
    assert all(p["adjustments"] for p in proposals)
    cloud = {
        "proposals": [
            {"level": "original", "brand": "Bravado", "model_name": "X"},
            {"level": "balanced", "brand": "Nervalis", "model_name": "Strata"},
        ]
    }
    merged = lore.merge_cloud(proposals, cloud)
    assert len(merged) == 4 and merged[-1]["source"] == "cloud"  # marque GTA filtrée
    assert "certification" in lore.DISCLAIMER


def test_geometric_adjustments():
    mesh = silhouette_mesh()
    longer = lore.deform(mesh, "hood_length", 0.1).mesh
    assert np.ptp(longer.positions[:, 2]) > np.ptp(mesh.positions[:, 2])
    lower = lore.deform(mesh, "roof_height", -0.1).mesh
    assert lower.positions[:, 1].max() < mesh.positions[:, 1].max()
    with pytest.raises(EditError):
        lore.deform(mesh, "hood_length", 0.5)
