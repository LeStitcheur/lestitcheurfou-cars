"""AI Vehicle Creator — service du projet, historique et sauvegarde ``.lsfc`` (tests réels, sans Qt)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from lsfcars.ai.creator import DOC_KEY, AIVehicleCreator, principal_alignment
from lsfcars.ai.engines.base import JobContext
from lsfcars.ai.errors import AIError
from lsfcars.ai.manager import AIEngineManager
from lsfcars.project.session import ProjectSession

REFERENCES = Path(__file__).resolve().parents[1] / "samples" / "references"


@pytest.fixture
def setup(tmp_path):
    session = ProjectSession.create(tmp_path / "projets", "IA projet")
    manager = AIEngineManager(tmp_path / "data", tmp_path / "engines")
    manager.detect_all(include_hardware=False)
    creator = AIVehicleCreator(session, manager)
    yield session, manager, creator
    manager.shutdown()


def generate(creator: AIVehicleCreator, profile: str = "eco") -> str:
    outcome = creator.generation_job("lsf-silhouette", profile)(JobContext())
    return creator.apply_generation(outcome)


def test_references_are_editable_and_undoable(setup):
    session, _manager, creator = setup
    ids = [creator.add_reference(p) for p in sorted(REFERENCES.glob("demo_*.png"))]
    assert len(creator.references()) == 5
    assert all(r["blob"] in session.scene.blobs for r in creator.references())
    first = ids[0]
    creator.update_reference(first, view="right", front_left=False, license="CC0", source="test")
    creator.rotate_reference(first, 90)
    note = creator.add_annotation(first, "logo", [0.1, 0.1, 0.3, 0.2], "logo fictif")
    creator.move_reference(first, 2)
    ref = creator.reference(first)
    assert ref["view"] == "right" and ref["rotation"] == 90 and ref["annotations"][0]["id"] == note
    assert creator.references()[2]["id"] == first
    with pytest.raises(AIError):
        creator.update_reference(first, unknown=1)
    with pytest.raises(AIError):
        creator.add_reference(REFERENCES.parent / "vehicule_test.obj")
    creator.remove_reference(first)
    assert len(creator.references()) == 4
    session.stack.undo()
    assert len(creator.references()) == 5
    for _ in range(4):
        session.stack.undo()
    assert creator.reference(first)["view"] == "back"  # vue d'origine (nom « demo_arriere »)


def test_generation_history_save_and_reopen(setup):
    session, manager, creator = setup
    for path in sorted(REFERENCES.glob("demo_*.png")):
        creator.add_reference(path, license_text="Rendu original LeStitcheurFou Cars")
    creator.analyze()
    record_id = generate(creator)
    record = creator.record(record_id)
    assert record["status"] == "succeeded" and record["method"] == "algorithmic"
    assert record["reported_cost"] == "" and "gratuit" in record["estimated_cost"]
    assert record["files"]["report"].startswith("assets/ai/")
    assert (session.project.project_dir / record["files"]["report"]).is_file()
    asset = session.project.assets[record["asset_id"]]
    assert "pas un véhicule GTA V" in " ".join(asset.notes)
    second = creator.record(generate(creator))  # essai identique : résultat du cache
    assert second["cached"]
    failure = creator.record_failure("triposr", "balanced", "failed", "moteur absent", 0.5)
    assert creator.record(failure)["status"] == "failed"
    rows = {r[0]: r[1:] for r in creator.compare(record_id, second["id"])}
    assert rows["Moteur"] == ("LSF Silhouette", "LSF Silhouette")
    assert rows["Coût communiqué"] == ("non communiqué", "non communiqué")
    assert creator.reuse_parameters(record_id)["engine"] == "lsf-silhouette"
    creator.generate_proposals()
    creator.select_proposal(0)
    session.save()
    # contenu du .lsfc : document « ai » et blobs cités, aucune clé API
    with sqlite3.connect(session.file_path) as conn:
        doc = json.loads(conn.execute("SELECT data FROM documents WHERE key = ?", (DOC_KEY,)).fetchone()[0])
        blob_keys = {row[0] for row in conn.execute("SELECT key FROM blobs")}
    assert len(doc["generations"]) == 3 and len(doc["references"]) == 5
    assert {r["blob"] for r in doc["references"]} | {record["thumbnail"]} <= blob_keys
    assert "api_key" not in json.dumps(doc).lower()
    reopened = ProjectSession.open(session.file_path)
    again = AIVehicleCreator(reopened, manager)
    assert again.document()["lore"]["selected"]["level"] == "light"
    assert again.provenance()["references"][0]["license"] == "Rendu original LeStitcheurFou Cars"
    assert again.prepared(again.references()[0]).size[0] > 0
    root = again.reopen(record_id)
    assert root in reopened.scene and reopened.selection.ids == [root]
    reopened.delete([root])
    new_root = again.reopen(record_id)  # réimporté depuis le fichier du projet
    assert new_root != root and new_root in reopened.scene
    duplicate = again.duplicate(record_id)
    assert duplicate in reopened.scene and duplicate != new_root
    again.delete_record(failure)
    assert len(again.records()) == 2
    again.delete_record(record_id, remove_model=True)
    assert new_root not in reopened.scene


def test_projects_without_ai_document_still_open(setup, sample_glb):
    session, manager, _creator = setup
    session.import_model(sample_glb)
    session.save()
    reopened = ProjectSession.open(session.file_path)
    creator = AIVehicleCreator(reopened, manager)
    assert creator.references() == [] and creator.records() == []
    assert DOC_KEY not in reopened.scene.documents  # rien n'est créé tant que l'IA n'est pas utilisée


def test_placement_tools(setup):
    session, _manager, creator = setup
    for name in ("demo_profil_gauche.png", "demo_avant.png"):
        creator.add_reference(REFERENCES / name)
    creator.analyze(known_length=4.4)
    root = creator.record(generate(creator, "balanced"))["root_id"]
    creator.set_analysis_field("width_m", 1.8)
    factors = creator.fit_to_analysis(root)
    assert "largeur" in " ".join(factors)
    bounds = session.world_bounds([root], only_visible=False)
    assert bounds[1][0] - bounds[0][0] == pytest.approx(1.8, abs=0.03)
    before = session.world_bounds([root], only_visible=False)
    creator.turn_model(root, 180)
    after = session.world_bounds([root], only_visible=False)
    assert np.allclose(before[1] - before[0], after[1] - after[0], atol=1e-3)
    session.stack.undo()
    session.stack.undo()
    restored = session.world_bounds([root], only_visible=False)
    assert restored[1][0] - restored[0][0] > 1.9  # largeur d'origine retrouvée


def test_principal_alignment_recovers_upright_pose():
    rng = np.random.default_rng(3)
    body = rng.uniform([-1.0, 0.0, -2.3], [1.0, 1.4, 2.3], size=(4000, 3))
    wheels = np.array([[-0.9, 0.0, -1.5], [0.9, 0.0, -1.5], [-0.9, 0.0, 1.5], [0.9, 0.0, 1.5]] * 20)
    cloud = np.vstack([body, wheels])
    angle = np.radians(25)
    tilt = np.array([[1, 0, 0], [0, np.cos(angle), -np.sin(angle)], [0, np.sin(angle), np.cos(angle)]])
    rotated = cloud @ tilt.T
    aligned = rotated @ principal_alignment(rotated).T
    extent = np.ptp(aligned, axis=0)
    assert extent[2] == pytest.approx(4.6, abs=0.15) and extent[1] == pytest.approx(1.4, abs=0.15)
