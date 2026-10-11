"""Analyse de ressources, import dans un projet, inspection et adaptateur Blender / Sollumz."""

from __future__ import annotations

import sqlite3
import sys
import threading
import zipfile
from contextlib import closing
from pathlib import Path

import numpy as np
import pytest

from lsfcars.fivem import gta_install, sollumz
from lsfcars.fivem.errors import FormatError
from lsfcars.fivem.project_import import import_into_project, safe_relative
from lsfcars.fivem.resource import AnalysisCancelled, Status, analyze, stage_model
from lsfcars.fivem.rpf import ENC_AES
from lsfcars.fivem.synthetic import RpfItem, build_rpf, build_yft, demo_vehicle, write_demo_addon
from lsfcars.importers.yft_importer import YftImporter
from lsfcars.project import store
from lsfcars.project.session import ProjectSession
from lsfcars.scene.inspection import anchor_nodes, exploded_offsets, offset_bounds, part_statistics
from lsfcars.scene.transform import Transform


@pytest.fixture
def addon(tmp_path) -> Path:
    return write_demo_addon(tmp_path / "lsfdemo")


def statuses(analysis) -> dict[str, Status]:  # type: ignore[no-untyped-def]
    return {f.path: f.status for f in analysis.files}


def test_demo_addon_analysis(addon):
    analysis = analyze(addon)
    try:
        assert analysis.name == "lsfdemo" and analysis.source_kind == "dossier"
        assert analysis.overall is Status.COMPATIBLE
        assert set(statuses(analysis).values()) == {Status.COMPATIBLE}
        model = analysis.model("lsfdemo")
        assert model.is_vehicle and model.meta["handlingId"] == "LSFDEMO"
        assert [y.name for y in model.ytds] == ["lsfdemo.ytd"]
        assert model.yft.details["triangles"] == 168 and model.yft.details["bones"] == 15
        assert {t.name for t in analysis.textures} == {"lsfdemo_details", "lsfdemo_lights", "lsfdemo_sign_1"}
        assert all(t.decoded and t.preview_png for t in analysis.textures)
        assert any("HANDLING_FILE" in d for d in analysis.dependencies)
        # Textures partagées par le jeu : signalées, jamais inventées
        assert "vehicle_generic_tyrewallblack" in model.yft.details["missing_textures"]
    finally:
        analysis.close()


def test_zip_and_rpf_sources(addon, tmp_path):
    archive = tmp_path / "lsfdemo.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for path in addon.rglob("*"):
            if path.is_file():
                zf.write(path, f"lsfdemo/{path.relative_to(addon).as_posix()}")
    analysis = analyze(archive)
    assert analysis.source_kind == "zip" and analysis.overall is Status.COMPATIBLE
    analysis.close()
    inner = build_rpf(
        {
            "lsfdemo.yft": RpfItem((addon / "stream/lsfdemo.yft").read_bytes(), resource=True),
            "lsfdemo.ytd": RpfItem((addon / "stream/lsfdemo.ytd").read_bytes(), resource=True),
        }
    )
    rpf = tmp_path / "dlc.rpf"
    rpf.write_bytes(
        build_rpf(
            {
                "common/data/vehicles.meta": RpfItem(
                    (addon / "data/vehicles.meta").read_bytes(), compress=True
                ),
                "x64/vehicles.rpf": RpfItem(inner),
            }
        )
    )
    analysis = analyze(rpf)
    try:
        assert analysis.source_kind == "rpf"
        model = analysis.model("lsfdemo")
        assert model.yft.path == "x64/vehicles.rpf/lsfdemo.yft" and model.status is Status.COMPATIBLE
        staged = stage_model(analysis, model, tmp_path / "stage")
        assert staged.read_bytes() == (addon / "stream/lsfdemo.yft").read_bytes()
    finally:
        analysis.close()


def test_missing_texture_and_incomplete_resource(addon):
    (addon / "stream/lsfdemo.ytd").unlink()
    (addon / "data/handling.meta").unlink()
    analysis = analyze(addon)
    try:
        found = statuses(analysis)
        assert found["stream/lsfdemo.yft"] is Status.MISSING  # dictionnaire du véhicule absent
        assert found["fxmanifest.lua"] is Status.MISSING  # fichier déclaré introuvable
        assert analysis.overall is Status.MISSING
        assert any("handling.meta" in message for _level, message in analysis.issues)
    finally:
        analysis.close()


def test_corrupted_invalid_and_unsupported_files(addon, tmp_path):
    (addon / "stream/casse.yft").write_bytes(b"RSC7" + b"\xff" * 64)
    (addon / "stream/chiffre.ytd").write_bytes(b"\x9a\x12" * 200)
    (addon / "stream/collision.ybn").write_bytes(b"RSC7" + (43).to_bytes(4, "little") + b"\0" * 24)
    (addon / "data/broken.meta").write_text("<CHandlingDataMgr><Item>", encoding="utf-8")
    (addon / "audio.awc").write_bytes(b"\0" * 32)
    (addon / "official.rpf").write_bytes(build_rpf({"a.meta": RpfItem(b"x")}, encryption=ENC_AES))
    (addon / "random.bin").write_bytes(np.random.default_rng(3).bytes(4096))
    analysis = analyze(addon)
    try:
        found = statuses(analysis)
        assert found["stream/casse.yft"] is Status.ERROR
        assert found["stream/chiffre.ytd"] is Status.ERROR
        assert "chiffré" in analysis.find("stream/chiffre.ytd").message
        assert found["stream/collision.ybn"] is Status.PARTIAL
        assert found["data/broken.meta"] is Status.ERROR
        assert found["audio.awc"] is Status.UNSUPPORTED
        assert found["official.rpf"] is Status.ERROR
        assert "ne déchiffre pas" in analysis.find("official.rpf").message
        assert found["random.bin"] is Status.UNSUPPORTED
        assert found["stream/lsfdemo.yft"] is Status.COMPATIBLE  # le reste reste exploitable
    finally:
        analysis.close()
    bad_zip = tmp_path / "faux.zip"
    bad_zip.write_bytes(b"ceci n'est pas un zip")
    with pytest.raises(FormatError, match="ZIP invalide"):
        analyze(bad_zip)


def test_asset_escrow_resource_is_refused(addon):
    (addon / "escrow.fxap").write_bytes(b"\0" * 16)
    analysis = analyze(addon)
    try:
        assert analysis.protected and analysis.overall is Status.ERROR
        assert "Asset Escrow" in analysis.issues[0][1]
    finally:
        analysis.close()


def test_analysis_can_be_cancelled(addon):
    with pytest.raises(AnalysisCancelled):
        analyze(addon, cancel=lambda: True)


def test_import_into_project_save_reopen(addon, projects_dir):
    analysis = analyze(addon)
    model = analysis.model("lsfdemo")
    staged = stage_model(analysis, model, analysis.temp_dir() / "stage")
    result = YftImporter().load(staged)
    session = ProjectSession.create(projects_dir, "Démo FiveM")
    root_id, resource = import_into_project(session, analysis, model, result)
    analysis.close()
    assert resource.manifest["manifest_version"] == 1
    assert resource.manifest["model"]["triangles"] == 168
    copies = {f["path"]: f["copy"] for f in resource.manifest["files"] if f["copy"]}
    assert "data/handling.meta" in copies and "stream/lsfdemo.ytd" in copies
    for rel in copies.values():
        assert (session.project.project_dir / rel).is_file()
    assert (addon / "stream/lsfdemo.yft").read_bytes() == build_yft(
        demo_vehicle("lsfdemo")
    )  # original intact

    door = next(n for n in session.scene.walk() if n.name == "door_dside_f")
    assert door.extra["gta"]["role"] == "bone" and door.extra["category"] == "portes"
    session.set_transforms({door.id: Transform(list(door.transform.translation), [0.0, 0.0, 35.0])})
    session.save()
    reopened = ProjectSession.open(session.file_path)
    assert not reopened.missing_assets
    assert reopened.stats()[0] == 168
    door2 = next(n for n in reopened.scene.walk() if n.name == "door_dside_f")
    assert door2.transform.rotation[2] == pytest.approx(35.0)
    assert door2.extra["gta"]["bone_tag"] == door.extra["gta"]["bone_tag"]
    (saved,) = reopened.project.resources.values()
    assert saved.name == "lsfdemo" and saved.manifest["resource"]["overall_status"] == "compatible"
    root = reopened.scene.get(root_id)
    assert root is not None and reopened.project.assets[root.asset_id].format == "yft"


def test_v2_project_migrates_to_v3(projects_dir):
    session = ProjectSession.create(projects_dir, "Ancien")
    path = session.file_path
    with closing(sqlite3.connect(path)) as conn:  # simulation d'un fichier au format 2
        conn.execute("DROP TABLE resources")
        conn.execute("ALTER TABLE nodes DROP COLUMN extra")
        conn.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")
        conn.commit()
    project = store.load_project(path)
    assert project.resources == {}
    store.save_project(project)
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == "3"


def test_safe_relative_blocks_traversal():
    assert safe_relative("../../evil.meta") == Path("evil.meta")
    assert safe_relative("a/b:c/d.meta") == Path("a/b_c/d.meta")


def test_exploded_view_is_non_destructive(addon, projects_dir):
    session = ProjectSession.create(projects_dir, "Inspection")
    session.import_model(addon / "stream/lsfdemo.yft")
    before = {n.id: n.transform.matrix().copy() for n in session.scene.walk()}
    offsets = exploded_offsets(session, 1.0)
    assert offsets and any(np.linalg.norm(v) > 0.1 for v in offsets.values())
    wheel = next(n for n in session.scene.mesh_nodes() if n.name == "wheel_lf")
    assert offsets[wheel.id][0] < 0  # la roue avant gauche s'écarte vers la gauche
    assert offset_bounds(session, [n.id for n in session.scene.children(None)], offsets) is not None
    assert all(np.allclose(n.transform.matrix(), before[n.id]) for n in session.scene.walk())
    assert exploded_offsets(session, 0.0) == {}
    assert sum(s.triangles for s in part_statistics(session)) == 168
    assert "seat_dside_f" in {n.name for n in anchor_nodes(session)}


def test_fbx_without_blender_is_a_missing_dependency(addon, monkeypatch):
    from lsfcars.importers import fbx_blender

    monkeypatch.setattr(fbx_blender, "blender_version", lambda: None)
    (addon / "extra.fbx").write_bytes(b"Kaydara FBX Binary  \0")
    analysis = analyze(addon)
    try:
        item = analysis.find("extra.fbx")
        assert item.status is Status.MISSING and "Blender" in item.message
    finally:
        analysis.close()


def test_sollumz_status_without_blender(monkeypatch):
    monkeypatch.setattr(sollumz, "find_blender", lambda: None)
    status = sollumz.probe()
    assert status.blender_version is None and not status.can_import
    assert "introuvable" in status.summary()


def test_sollumz_unavailable_is_reported(monkeypatch, tmp_path):
    monkeypatch.setattr(sollumz, "find_blender", lambda: tmp_path / "blender.exe")
    monkeypatch.setattr(sollumz, "blender_version", lambda: "Blender 9.9")

    def fake_run(self):  # type: ignore[no-untyped-def]
        self.lines = ['LSFCARS_JSON:{"blender": "9.9", "sollumz": null, "operators": []}']
        return 0

    monkeypatch.setattr(sollumz.BlenderTask, "run", fake_run)
    status = sollumz.probe()
    assert status.blender_version == "Blender 9.9" and not status.sollumz_installed
    assert not status.can_import and "pas installé" in status.summary()
    with pytest.raises(RuntimeError, match="pas disponible"):
        sollumz.import_with_sollumz(status, tmp_path / "a.yft", tmp_path / "a.glb")


def test_sollumz_operators_are_probed_not_assumed(monkeypatch, tmp_path):
    monkeypatch.setattr(sollumz, "find_blender", lambda: tmp_path / "blender.exe")
    monkeypatch.setattr(sollumz, "blender_version", lambda: "Blender 4.2.0")

    def fake_run(self):  # type: ignore[no-untyped-def]
        self.lines = [
            'LSFCARS_JSON:{"blender": "4.2.0", "sollumz": {"module": "SollumzPlugin", "name": "Sollumz",'
            ' "version": "2.4.0", "enabled": true}, "operators": ["import_assets", "other"]}'
        ]
        return 0

    monkeypatch.setattr(sollumz.BlenderTask, "run", fake_run)
    status = sollumz.probe()
    assert status.sollumz_installed and status.import_operator == "import_assets"
    assert status.can_import and not status.can_export


def test_blender_task_cancellation(monkeypatch):
    monkeypatch.setattr(sollumz, "find_blender", lambda: Path(sys.executable))
    task = sollumz.BlenderTask(
        ["-c", "import time; print('début', flush=True); time.sleep(30)"], timeout_s=20
    )
    threading.Timer(0.8, task.cancel).start()
    with pytest.raises(sollumz.TaskCancelled):
        task.run()


def test_gta_install_scan_lists_encryption(tmp_path):
    (tmp_path / "mods").mkdir()
    (tmp_path / "GTA5.exe").write_bytes(b"")
    (tmp_path / "x64a.rpf").write_bytes(build_rpf({"a.meta": RpfItem(b"x")}, encryption=ENC_AES))
    (tmp_path / "mods" / "addon.rpf").write_bytes(build_rpf({"a.meta": RpfItem(b"x")}))
    (tmp_path / "broken.rpf").write_bytes(b"xx")
    found = gta_install.scan(tmp_path)
    assert gta_install.is_gta_install(tmp_path)
    assert found[0].path.name == "addon.rpf" and found[0].readable
    by_name = {info.path.name: info for info in found}
    assert not by_name["x64a.rpf"].readable and "Chiffrée" in by_name["x64a.rpf"].status
    assert by_name["broken.rpf"].error
