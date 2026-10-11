"""Graphe de scène, transformations, historique, importateurs et gizmos (sans GPU)."""

import math
import subprocess

import numpy as np
import pytest

from lsfcars.importers import ModelLoadError, UnsupportedYetError, load_model
from lsfcars.importers.fbx_blender import FbxBlenderImporter, find_blender
from lsfcars.scene import gizmo
from lsfcars.scene.camera import OrbitCamera
from lsfcars.scene.commands import SetTransforms, UndoStack
from lsfcars.scene.graph import NodeKind, SceneError, SceneGraph, SceneNode
from lsfcars.scene.picking import ray_from_screen
from lsfcars.scene.transform import Transform, decompose


def test_decompose_roundtrip():
    original = Transform([1, -2, 3], [10, 35, -70], [1.5, 0.5, 2.0])
    assert decompose(original.matrix()).is_close(original, tol=1e-6)


def test_graph_hierarchy_and_world_matrix():
    scene = SceneGraph()
    parent = SceneNode("parent", transform=Transform([1, 0, 0]))
    child = SceneNode("enfant", NodeKind.MESH, transform=Transform([0, 2, 0]))
    scene.add(parent)
    scene.add(child, parent.id)
    assert np.allclose(scene.world_matrix(child.id)[:3, 3], [1, 2, 0])
    assert scene.path(child.id) == "parent / enfant"
    with pytest.raises(SceneError):
        scene.move(parent.id, child.id)
    parent.visible = False
    assert not scene.effective_visible(child.id)
    assert scene.unique_name("parent") == "parent.001"


def test_undo_stack_merges_and_tracks_clean_state():
    scene = SceneGraph()
    item = SceneNode("objet")
    scene.add(item)
    stack = UndoStack(scene)
    for x in (1.0, 2.0, 3.0):
        stack.push(SetTransforms({item.id: (item.transform.copy(), Transform([x, 0, 0]))}, key="glisser"))
    assert item.transform.translation[0] == 3.0
    stack.undo()
    assert item.transform.translation[0] == 0.0 and stack.is_clean()
    stack.redo()
    stack.mark_clean()
    stack.push(
        SetTransforms({item.id: (item.transform.copy(), Transform([9, 0, 0]))}, key="glisser")
    )  # ne fusionne pas avec l'état enregistré
    stack.undo()
    assert item.transform.translation[0] == 3.0 and stack.is_clean()


def test_import_glb_hierarchy(sample_glb):
    result = load_model(sample_glb)
    by_key = {n.key: n for n in result.nodes}
    assert by_key["pneu_avant_gauche"].parent_key == "roue_avant_gauche"
    assert by_key["roue_avant_gauche"].transform.translation == pytest.approx([0.86, 0.34, 1.42])
    assert {m.name for m in result.materials.values()} >= {"Peinture rouge LS", "Caoutchouc"}
    assert result.triangle_count == 720


def test_import_errors(tmp_path):
    with pytest.raises(UnsupportedYetError, match="version future"):
        load_model(tmp_path / "vehicule.yft")
    empty = tmp_path / "vide.glb"
    empty.write_bytes(b"")
    with pytest.raises(ModelLoadError, match="vide"):
        load_model(empty)


@pytest.mark.skipif(find_blender() is None, reason="Blender non installé")
def test_fbx_roundtrip_through_blender(sample_glb, tmp_path):
    fbx = tmp_path / "vehicule.fbx"
    script = (
        "import bpy,sys; a=sys.argv[sys.argv.index('--')+1:]; "
        "bpy.ops.wm.read_factory_settings(use_empty=True); "
        "bpy.ops.import_scene.gltf(filepath=a[0]); bpy.ops.export_scene.fbx(filepath=a[1])"
    )
    subprocess.run(
        [
            str(find_blender()),
            "-b",
            "--factory-startup",
            "--python-expr",
            script,
            "--",
            str(sample_glb),
            str(fbx),
        ],
        check=True,
        capture_output=True,
        timeout=300,
    )
    assert FbxBlenderImporter().available()[0]
    result = load_model(fbx)
    assert result.format == "fbx" and result.triangle_count > 0
    assert any("Blender" in note for note in result.notes)


def test_gizmo_translate_hit_and_drag():
    camera = OrbitCamera(distance=10, yaw=30, pitch=25)
    pivot = np.zeros(3)
    size = gizmo.world_size(camera, pivot, 600)
    tip = gizmo.project(camera, np.array([[size * 0.8, 0, 0]]), 800, 600)[0]
    assert gizmo.hit_test(gizmo.GizmoMode.TRANSLATE, camera, pivot, np.eye(3), tuple(tip), 800, 600) == 0
    target = gizmo.project(camera, np.array([[size * 0.8 + 1.5, 0, 0]]), 800, 600)[0]
    delta = gizmo.drag_translation(camera, pivot, np.array([1.0, 0, 0]), tuple(tip), tuple(target), 800, 600)
    assert delta == pytest.approx([1.5, 0, 0], abs=1e-6)


def test_gizmo_rotation_and_scale():
    camera = OrbitCamera(distance=10, yaw=0, pitch=60)
    pivot = np.zeros(3)
    a = tuple(gizmo.project(camera, np.array([[1.0, 0, 0]]), 800, 600)[0])
    b = tuple(gizmo.project(camera, np.array([[0, 0, -1.0]]), 800, 600)[0])
    angle = gizmo.drag_rotation(camera, pivot, np.array([0, 1.0, 0]), a, b, 800, 600)
    assert angle == pytest.approx(math.pi / 2, abs=1e-6)
    c = tuple(gizmo.project(camera, np.array([[2.0, 0, 0]]), 800, 600)[0])
    assert gizmo.drag_scale(camera, pivot, np.array([1.0, 0, 0]), a, c, 800, 600) == pytest.approx(
        2.0, abs=1e-6
    )
    rotation = gizmo.rotation_about(np.array([0, 1.0, 0]), math.pi / 2, np.array([1.0, 0, 0]))
    moved = rotation[:3, :3] @ np.array([2.0, 0, 0]) + rotation[:3, 3]
    assert moved == pytest.approx([1, 0, -1], abs=1e-9)


def test_orthographic_rays_and_free_look():
    camera = OrbitCamera(distance=5, yaw=0, pitch=0, orthographic=True)
    _, d1 = ray_from_screen(camera, 10, 10, 800, 600)
    _, d2 = ray_from_screen(camera, 700, 500, 800, 600)
    assert np.allclose(d1, d2)
    camera.mode = "free"
    eye = camera.eye().copy()
    camera.look(20, 0)
    assert np.allclose(camera.eye(), eye)
