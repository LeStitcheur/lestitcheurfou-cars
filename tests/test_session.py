import numpy as np
import pytest

from lsfcars.project.model import Transform, VehicleType
from lsfcars.project.session import ProjectSession
from lsfcars.scene.loader import ModelLoadError


@pytest.fixture
def session(projects_dir):
    return ProjectSession.create(projects_dir, "Session test", VehicleType.SUV)


def test_new_session_is_clean(session):
    assert not session.dirty
    assert session.project.objects == []
    assert session.world_bounds() is None


def test_add_model_copies_asset_and_marks_dirty(session, sample_glb):
    obj = session.add_model(sample_glb)
    assert session.dirty
    assert obj.name == "vehicule_test"
    assert (session.project.project_dir / obj.asset_path).is_file()
    assert session.stats(obj.id) == (688, 2064)


def test_add_invalid_model_copies_nothing(session, tmp_path):
    bad = tmp_path / "casse.glb"
    bad.write_bytes(b"x")
    with pytest.raises(ModelLoadError):
        session.add_model(bad)
    assert not any(session.project.assets_dir.iterdir())
    assert not session.dirty


def test_save_then_reopen(session, sample_glb, sample_obj):
    glb = session.add_model(sample_glb)
    session.add_model(sample_obj, name="Version OBJ")
    session.set_transform(glb.id, Transform([1, 0, 0], [0, 45, 0], [1, 1, 1]))
    session.set_visible(glb.id, False)
    path = session.save()
    assert not session.dirty

    reopened = ProjectSession.open(path)
    assert [o.name for o in reopened.project.objects] == ["vehicule_test", "Version OBJ"]
    first = reopened.project.objects[0]
    assert first.transform.rotation == [0, 45, 0]
    assert first.visible is False
    assert reopened.stats() == session.stats()
    assert reopened.missing == {}
    assert not reopened.dirty


def test_missing_asset_is_reported(session, sample_glb):
    obj = session.add_model(sample_glb)
    session.save()
    (session.project.project_dir / obj.asset_path).unlink()
    reopened = ProjectSession.open(session.file_path)
    assert obj.id in reopened.missing
    assert reopened.meshes[obj.id] == []


def test_edits_mark_dirty_only_when_changed(session, sample_glb):
    obj = session.add_model(sample_glb)
    session.save()
    session.set_transform(obj.id, Transform())
    session.set_visible(obj.id, True)
    session.rename_object(obj.id, "vehicule_test")
    assert not session.dirty
    session.rename_object(obj.id, "Nouveau nom")
    assert session.dirty


def test_remove_object(session, sample_glb):
    obj = session.add_model(sample_glb)
    session.save()
    removed = session.remove_object(obj.id)
    assert removed is obj
    assert session.project.objects == []
    assert session.dirty
    assert session.remove_object("inconnu") is None


def test_world_bounds_follow_transform(session, sample_glb):
    obj = session.add_model(sample_glb)
    bmin, bmax = session.world_bounds()
    session.set_transform(obj.id, Transform([10, 0, 0], [0, 0, 0], [1, 1, 1]))
    moved_min, moved_max = session.world_bounds()
    assert np.allclose(moved_min - bmin, [10, 0, 0], atol=1e-5)
    assert np.allclose(moved_max - bmax, [10, 0, 0], atol=1e-5)
    session.set_visible(obj.id, False)
    assert session.world_bounds() is None
    assert session.world_bounds(only_visible=False) is not None
