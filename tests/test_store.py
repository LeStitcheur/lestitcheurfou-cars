import json
import sqlite3
from contextlib import closing

import pytest

from lsfcars.project import store
from lsfcars.project.model import Project, SceneObject, Transform, VehicleRole, VehicleType
from lsfcars.project.store import ProjectError


def test_create_project_layout(projects_dir):
    project = store.create_project(projects_dir, "Police Buffalo", VehicleType.CAR)
    folder = projects_dir / "Police Buffalo"
    assert project.file_path == folder / "Police Buffalo.lsfc"
    assert project.file_path.is_file()
    assert (folder / "assets").is_dir()


def test_create_project_in_non_empty_folder_fails(projects_dir):
    folder = projects_dir / "Existant"
    folder.mkdir()
    (folder / "autre.txt").write_text("x")
    with pytest.raises(ProjectError, match="n'est pas vide"):
        store.create_project(projects_dir, "Existant")


@pytest.mark.parametrize(
    ("name", "expected"),
    [("  Mon véhicule  ", "Mon véhicule"), ('a<b>c:"d"', "a_b_c__d_"), ("..nom..", "nom")],
)
def test_safe_folder_name(name, expected):
    assert store.safe_folder_name(name) == expected


def test_safe_folder_name_rejects_empty():
    with pytest.raises(ProjectError):
        store.safe_folder_name("  ...  ")


def test_save_and_load_roundtrip(projects_dir):
    project = store.create_project(
        projects_dir, "Ambulance", VehicleType.TRUCK, VehicleRole.EMS, "Notes"
    )
    project.objects = [
        SceneObject("caisse", "assets/caisse.glb", Transform([1, 2, 3], [0, 90, 0], [2, 2, 2])),
        SceneObject("gyro", "assets/gyro.obj", visible=False),
    ]
    project.camera = {"target": [0, 1, 0], "distance": 5.0, "yaw": 10.0, "pitch": 5.0}
    store.save_project(project)

    loaded = store.load_project(project.file_path)
    assert loaded.name == "Ambulance"
    assert loaded.vehicle_type is VehicleType.TRUCK
    assert loaded.role is VehicleRole.EMS
    assert loaded.description == "Notes"
    assert loaded.camera == project.camera
    assert [o.name for o in loaded.objects] == ["caisse", "gyro"]
    assert loaded.objects[0].transform == Transform([1, 2, 3], [0, 90, 0], [2, 2, 2])
    assert loaded.objects[0].id == project.objects[0].id
    assert loaded.objects[1].visible is False
    assert loaded.created_at == project.created_at


def test_save_is_atomic_and_leaves_no_temp_file(projects_dir):
    project = store.create_project(projects_dir, "Atomique")
    store.save_project(project)
    assert not list(project.project_dir.glob("*.tmp"))


def test_load_does_not_modify_file(projects_dir):
    project = store.create_project(projects_dir, "Lecture seule")
    before = project.file_path.read_bytes()
    store.load_project(project.file_path)
    assert project.file_path.read_bytes() == before


def test_load_missing_file(tmp_path):
    with pytest.raises(ProjectError, match="introuvable"):
        store.load_project(tmp_path / "absent.lsfc")


def test_load_garbage_file(tmp_path):
    path = tmp_path / "faux.lsfc"
    path.write_bytes(b"pas une base sqlite" * 100)
    with pytest.raises(ProjectError, match="illisible"):
        store.load_project(path)


def test_load_foreign_sqlite(tmp_path):
    path = tmp_path / "autre.lsfc"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE meta (key TEXT, value TEXT)")
        conn.execute("INSERT INTO meta VALUES ('format', 'AutreLogiciel')")
        conn.commit()
    with pytest.raises(ProjectError, match="n'est pas un projet"):
        store.load_project(path)


def test_load_newer_schema_is_refused(projects_dir):
    project = store.create_project(projects_dir, "Futur")
    with closing(sqlite3.connect(project.file_path)) as conn:
        conn.execute("UPDATE meta SET value = '999' WHERE key = 'schema_version'")
        conn.commit()
    with pytest.raises(ProjectError, match="version plus récente"):
        store.load_project(project.file_path)


def test_corrupted_transform_is_reset(projects_dir):
    project = store.create_project(projects_dir, "Transfo")
    project.objects = [SceneObject("o", "assets/o.glb")]
    store.save_project(project)
    with closing(sqlite3.connect(project.file_path)) as conn:
        conn.execute("UPDATE scene_objects SET transform = '{casse'")
        conn.commit()
    loaded = store.load_project(project.file_path)
    assert loaded.objects[0].transform == Transform()


def test_save_without_path_fails():
    with pytest.raises(ProjectError):
        store.save_project(Project(name="Sans chemin"))


def test_import_asset_copies_with_unique_names(projects_dir, sample_glb):
    project = store.create_project(projects_dir, "Imports")
    first = store.import_asset(project, sample_glb)
    second = store.import_asset(project, sample_glb)
    assert first == "assets/vehicule_test.glb"
    assert second == "assets/vehicule_test_2.glb"
    assert (project.project_dir / second).read_bytes() == sample_glb.read_bytes()


def test_import_gltf_copies_external_buffers(projects_dir, tmp_path):
    source_dir = tmp_path / "source"
    (source_dir / "textures").mkdir(parents=True)
    (source_dir / "modele.bin").write_bytes(b"\x00" * 8)
    (source_dir / "textures" / "peinture.png").write_bytes(b"png")
    gltf = source_dir / "modele.gltf"
    gltf.write_text(
        json.dumps(
            {
                "asset": {"version": "2.0"},
                "buffers": [{"uri": "modele.bin", "byteLength": 8}],
                "images": [{"uri": "textures/peinture.png"}, {"uri": "data:image/png;base64,AA"}],
            }
        ),
        encoding="utf-8",
    )
    project = store.create_project(projects_dir, "Gltf")
    rel = store.import_asset(project, gltf)
    assert rel == "assets/modele/modele.gltf"
    folder = project.assets_dir / "modele"
    assert (folder / "modele.bin").is_file()
    assert (folder / "textures" / "peinture.png").is_file()
