"""Format .lsfc v2, session (import, édition, historique), récupération après interruption."""

import json
import shutil
import sqlite3
from contextlib import closing

import numpy as np
import pytest

from lsfcars.project import recovery, store
from lsfcars.project.model import VehicleRole, VehicleType
from lsfcars.project.session import ProjectSession
from lsfcars.project.store import ProjectError
from lsfcars.scene.graph import NodeKind
from lsfcars.scene.transform import Transform


@pytest.fixture
def session(projects_dir):
    return ProjectSession.create(projects_dir, "Essai", VehicleType.SUV, VehicleRole.EMS)


@pytest.fixture
def loaded(session, sample_glb):
    session.import_model(sample_glb)
    return session


def node(session, name):
    return next(n for n in session.scene.walk() if n.name == name)


def test_create_layout(projects_dir):
    project = store.create_project(projects_dir, "Police Buffalo")
    assert project.file_path == projects_dir / "Police Buffalo" / "Police Buffalo.lsfc"
    assert (projects_dir / "Police Buffalo" / "assets").is_dir()
    (projects_dir / "Police Buffalo" / "x.txt").write_text("x")
    with pytest.raises(ProjectError, match="n'est pas vide"):
        store.create_project(projects_dir, "Police Buffalo")


def test_import_preserves_hierarchy_materials_and_provenance(loaded, sample_glb):
    root = loaded.scene.roots()[0]
    assert root.kind is NodeKind.MODEL and root.name == "vehicule_test.glb"
    wheel = node(loaded, "roue_avant_gauche")
    assert sorted(c.name for c in loaded.scene.children(wheel.id)) == [
        "jante_avant_gauche",
        "pneu_avant_gauche",
    ]
    assert loaded.stats() == (720, 2160, 15)
    paint = loaded.scene.material_for(node(loaded, "caisse").id)
    assert paint.name == "Peinture rouge LS" and paint.metallic == pytest.approx(0.55)
    asset = next(iter(loaded.project.assets.values()))
    assert asset.sha256 == store.sha256_of(sample_glb)  # copie identique, original intact
    assert asset.format == "glb" and asset.source_path.endswith("vehicule_test.glb")
    assert (loaded.project.project_dir / asset.rel_path).is_file()
    assert loaded.dimensions()[2] == pytest.approx(4.6, abs=0.01)


def test_save_reopen_preserves_everything(loaded):
    wheel = node(loaded, "roue_avant_gauche")
    wanted = Transform([1.0, 0.5, 2.0], [0, 45, 0], [1.2, 1.2, 1.2])
    loaded.set_transforms({wheel.id: wanted})
    paint = loaded.scene.material_for(node(loaded, "caisse").id)
    loaded.set_material_properties(paint.id, {"roughness": 0.9, "base_color": (0, 0, 1, 1)})
    loaded.set_locked([wheel.id], True)
    loaded.project.camera = {"target": [0, 1, 0], "distance": 6.0, "yaw": 10.0, "pitch": 5.0}
    loaded.project.thumbnail = b"\x89PNG..."
    path = loaded.save()
    assert not loaded.dirty

    again = ProjectSession.open(path)
    reopened = node(again, "roue_avant_gauche")
    assert reopened.transform.is_close(wanted) and reopened.locked and reopened.id == wheel.id
    material = again.scene.materials[paint.id]
    assert material.roughness == pytest.approx(0.9) and material.base_color == (0, 0, 1, 1)
    assert again.project.vehicle_type is VehicleType.SUV and again.project.role is VehicleRole.EMS
    assert again.project.camera["distance"] == 6.0
    assert again.project.thumbnail == b"\x89PNG..."
    assert again.stats() == loaded.stats() and not again.dirty


def test_open_errors(tmp_path, session):
    with pytest.raises(ProjectError, match="introuvable"):
        store.load_project(tmp_path / "absent.lsfc")
    garbage = tmp_path / "faux.lsfc"
    garbage.write_bytes(b"pas une base" * 50)
    with pytest.raises(ProjectError, match="illisible"):
        store.load_project(garbage)
    with closing(sqlite3.connect(session.file_path)) as conn:
        conn.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
        conn.commit()
    with pytest.raises(ProjectError, match="plus récente"):
        store.load_project(session.file_path)


def test_load_never_modifies_file(loaded):
    path = loaded.save()
    before = path.read_bytes()
    ProjectSession.open(path)
    assert path.read_bytes() == before


def test_migration_from_v01(projects_dir, sample_glb):
    folder = projects_dir / "Ancien"
    (folder / "assets").mkdir(parents=True)
    shutil.copy(sample_glb, folder / "assets" / "v.glb")
    with closing(sqlite3.connect(folder / "Ancien.lsfc")) as conn:
        conn.executescript(
            "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);"
            "CREATE TABLE scene_objects(id TEXT PRIMARY KEY, position INTEGER, name TEXT,"
            " asset_path TEXT, transform TEXT, visible INTEGER);"
        )
        conn.executemany(
            "INSERT INTO meta VALUES (?,?)",
            [("format", "LeStitcheurFouCars"), ("schema_version", "1"), ("name", "Ancien")],
        )
        conn.execute(
            "INSERT INTO scene_objects VALUES ('o1',0,'voiture','assets/v.glb',?,1)",
            (json.dumps({"translation": [2, 0, 0], "rotation": [0, 0, 0], "scale": [1, 1, 1]}),),
        )
        conn.commit()
    migrated = ProjectSession.open(folder / "Ancien.lsfc")
    assert migrated.stats()[0] == 720
    assert migrated.scene.nodes["o1"].transform.translation == [2.0, 0.0, 0.0]
    assert migrated.dirty  # structure développée : à enregistrer
    migrated.save()
    assert store.read_summary(folder / "Ancien.lsfc").asset_count == 1


def test_edit_operations_and_undo(loaded):
    wheels = node(loaded, "roues")
    count = len(loaded.scene)
    copies = loaded.duplicate([wheels.id])
    assert loaded.scene.nodes[copies[0]].name == "roues.001"
    assert len(loaded.scene) == count + len(loaded.scene.subtree(wheels.id))
    group = loaded.group([wheels.id, copies[0]])
    assert {c.id for c in loaded.scene.children(group)} == {wheels.id, copies[0]}
    loaded.ungroup(group)
    assert group not in loaded.scene
    assert loaded.delete([copies[0]]) == 1
    for _ in range(4):
        loaded.stack.undo()
    assert len(loaded.scene) == count
    loaded.stack.redo()
    assert len(loaded.scene) > count


def test_dirty_follows_saved_point(loaded):
    loaded.save()
    loaded.rename(node(loaded, "caisse").id, "carrosserie principale")
    assert loaded.dirty
    loaded.stack.undo()
    assert not loaded.dirty  # retour exact à l'état enregistré


def test_locked_nodes_are_protected(loaded):
    wheel = node(loaded, "roue_avant_gauche")
    loaded.set_locked([wheel.id], True)
    assert loaded.delete([wheel.id]) == 0
    assert loaded.editable([wheel.id, node(loaded, "pneu_avant_gauche").id]) == []


def test_reparent_keeps_world_position(loaded):
    tyre = node(loaded, "pneu_avant_gauche")
    before = loaded.scene.world_matrix(tyre.id)
    loaded.reparent([tyre.id], None)
    assert tyre.parent_id is None
    assert np.allclose(loaded.scene.world_matrix(tyre.id), before, atol=1e-6)


def test_material_merge_and_assignment(loaded):
    paint = loaded.scene.material_for(node(loaded, "caisse").id)
    for value in (0.2, 0.4, 0.6):
        loaded.set_material_properties(paint.id, {"roughness": value}, merge_key="glisser")
    assert paint.roughness == pytest.approx(0.6)
    loaded.stack.undo()  # une seule entrée d'historique pour tout le glissement
    assert paint.roughness == pytest.approx(0.32)
    chrome = loaded.create_material("Chrome")
    loaded.assign_material([node(loaded, "roues").id], chrome.id)
    assert len(loaded.scene.material_users(chrome.id)) == 8


def test_texture_is_copied_not_moved(loaded, tmp_path):
    from PySide6.QtGui import QColor, QImage

    image = QImage(4, 4, QImage.Format.Format_RGBA8888)
    image.fill(QColor("red"))
    source = tmp_path / "livree.png"
    image.save(str(source))
    paint = loaded.scene.material_for(node(loaded, "caisse").id)
    loaded.set_texture(paint.id, source)
    assert source.is_file() and paint.texture.startswith("assets/textures/")
    assert (loaded.project.project_dir / paint.texture).is_file()


def test_missing_asset_is_reported(loaded):
    path = loaded.save()
    asset = next(iter(loaded.project.assets.values()))
    (loaded.project.project_dir / asset.rel_path).unlink()
    again = ProjectSession.open(path)
    assert asset.id in again.missing_assets and again.stats()[0] == 0


def test_save_as_copies_project(loaded, tmp_path):
    loaded.save()
    old_dir = loaded.project.project_dir
    path = loaded.save_as(tmp_path / "ailleurs", "Copie")
    assert path.parent != old_dir and (path.parent / "assets").is_dir()
    assert ProjectSession.open(path).stats() == loaded.stats()
    assert (old_dir / f"{old_dir.name}.lsfc").is_file()


def test_autosave_and_recovery(loaded):
    loaded.save()
    loaded.rename(node(loaded, "caisse").id, "renommé avant plantage")
    snapshot = loaded.autosave()
    assert snapshot is not None and snapshot.parent == recovery.recovery_dir()
    pending = recovery.pending()
    assert [p.name for p in pending] == ["Essai"]
    restored = ProjectSession.from_project(recovery.restore(pending[0]))
    assert restored.project.file_path == loaded.file_path
    assert any(n.name == "renommé avant plantage" for n in restored.scene.walk())
    loaded.save()  # un enregistrement normal supprime l'instantané
    assert recovery.pending() == []
