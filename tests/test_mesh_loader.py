import numpy as np
import pytest

from lsfcars.scene.loader import (
    SUPPORTED_EXTENSIONS,
    ModelLoadError,
    file_dialog_filter,
    load_meshes,
)
from lsfcars.scene.mesh import MeshData, combined_bounds, compute_vertex_normals

TRIANGLE = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)


def test_normals_computed_from_winding():
    normals = compute_vertex_normals(TRIANGLE, [[0, 1, 2]])
    assert np.allclose(normals, [[0, 0, 1]] * 3)


def test_degenerate_triangle_gets_default_normal():
    normals = compute_vertex_normals(np.zeros((3, 3)), [[0, 1, 2]])
    assert np.allclose(normals, [[0, 1, 0]] * 3)


def test_mesh_fills_colors_from_color():
    mesh = MeshData("t", TRIANGLE, [[0, 1, 2]], color=(1.0, 0.0, 0.0, 1.0))
    assert mesh.colors.shape == (3, 4)
    assert mesh.colors.dtype == np.uint8
    assert tuple(mesh.colors[0]) == (255, 0, 0, 255)
    assert mesh.triangle_count == 1 and mesh.vertex_count == 3


def test_mesh_rejects_out_of_range_indices():
    with pytest.raises(ValueError):
        MeshData("t", TRIANGLE, [[0, 1, 5]])


def test_bounds_and_combined_bounds():
    a = MeshData("a", TRIANGLE, [[0, 1, 2]])
    b = MeshData("b", TRIANGLE + 5, [[0, 1, 2]])
    bmin, bmax = combined_bounds([a, b])
    assert np.allclose(bmin, [0, 0, 0]) and np.allclose(bmax, [6, 6, 5])
    assert combined_bounds([]) is None


def test_load_sample_glb(sample_glb):
    meshes = load_meshes(sample_glb)
    assert len(meshes) == 12
    assert sum(m.triangle_count for m in meshes) == 688
    assert "carrosserie" in {m.name for m in meshes}
    body = next(m for m in meshes if m.name == "carrosserie")
    assert tuple(body.colors[0][:3]) == (30, 144, 255)  # bleu électrique conservé
    bmin, bmax = body.bounds
    assert bmax[2] - bmin[2] == pytest.approx(4.4, abs=1e-3)  # longueur de la carrosserie


def test_load_sample_obj_keeps_vertex_colors(sample_obj):
    meshes = load_meshes(sample_obj)
    assert sum(m.triangle_count for m in meshes) == 688
    unique_colors = {tuple(c) for m in meshes for c in m.colors}
    assert len(unique_colors) >= 4


def test_unsupported_extension(tmp_path):
    path = tmp_path / "modele.fbx"
    path.write_bytes(b"x")
    with pytest.raises(ModelLoadError, match="non pris en charge"):
        load_meshes(path)


def test_missing_file(tmp_path):
    with pytest.raises(ModelLoadError, match="introuvable"):
        load_meshes(tmp_path / "absent.glb")


def test_corrupt_file(tmp_path):
    path = tmp_path / "casse.glb"
    path.write_bytes(b"ceci n'est pas un glb")
    with pytest.raises(ModelLoadError):
        load_meshes(path)


def test_file_without_triangles(tmp_path):
    path = tmp_path / "vide.obj"
    path.write_text("v 0 0 0\nv 1 0 0\n", encoding="utf-8")
    with pytest.raises(ModelLoadError):
        load_meshes(path)


def test_file_dialog_filter_lists_formats():
    flt = file_dialog_filter()
    for ext in SUPPORTED_EXTENSIONS:
        assert f"*{ext}" in flt
