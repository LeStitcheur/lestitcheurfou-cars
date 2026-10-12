"""Lore Friendly Engine (logique) — tests unitaires et d'intégration RÉELS.

Véhicule d'essai original : ``samples/vehicule_lore.glb`` (généré par
``scripts/generate_lore_sample.py``, aucun asset tiers). Les transformations sont vérifiées sur
les sommets du projet : aucune n'est simulée.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from lsfcars.lorefriendly import (
    analyzer,
    brands,
    components,
    concepts,
    dna,
    operations,
    originality,
    provenance,
)
from lsfcars.lorefriendly.engine import SOURCE, LoreFriendlyEngine, migrate
from lsfcars.lorefriendly.geometry import IncompatibleTransformation, VehicleState
from lsfcars.project.session import ProjectSession
from lsfcars.scene import shapes
from lsfcars.scene.graph import NodeKind, SceneNode

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
LORE_GLB = SAMPLES / "vehicule_lore.glb"
REQUIRED_BRANDS = {
    "Vapid",
    "Bravado",
    "Declasse",
    "Albany",
    "Benefactor",
    "Obey",
    "Übermacht",
    "Karin",
    "Dinka",
    "Annis",
    "Pfister",
    "Grotti",
    "Pegassi",
    "Ocelot",
    "Enus",
    "Gallivanter",
    "Canis",
    "Dundreary",
    "Emperor",
    "Maibatsu",
}


class Ctx:
    """Contexte de tâche minimal (exécution directe, sans file)."""

    def check(self) -> None:
        return

    def progress(self, *_args) -> None:  # type: ignore[no-untyped-def]
        return


@pytest.fixture
def lore(tmp_path):
    session = ProjectSession.create(tmp_path / "projets", "Lore")
    root = session.import_model(LORE_GLB)
    return session, root, LoreFriendlyEngine(session, None, tmp_path / "data")


def geometry(session, root) -> dict[str, np.ndarray]:  # type: ignore[no-untyped-def]
    return {
        n.id: session.geometry_for(n).positions.copy()
        for n in session.scene.subtree(root)
        if n.kind is NodeKind.MESH
    }


def fresh_state(session, root) -> VehicleState:  # type: ignore[no-untyped-def]
    return VehicleState.from_session(session, components.identify(session, root))


# --- Bibliothèques -------------------------------------------------------------------------------


def test_brand_library_rules(tmp_path):
    library = brands.BrandLibrary(tmp_path / "brands.json")
    assert {b.name for b in library.all() if b.is_gta} >= REQUIRED_BRANDS
    for brand in library.all():
        assert brand.provenance and brand.resources == []  # aucun logo ni fichier fourni
        assert "Rockstar" in brand.license
    with pytest.raises(brands.BrandError, match="réelle"):
        library.create("Ferrari Motors")
    created = library.create("Velmora", categories=["sedan", "inconnue"], save_to_user=True)
    assert created.categories == ["sedan"] and created.license == "Non renseignée"  # licence jamais inventée
    with pytest.raises(brands.BrandError, match="existe déjà"):
        library.create("velmora")
    assert brands.BrandLibrary(tmp_path / "brands.json").get("custom-velmora") is not None
    taken = {b.name.lower() for b in library.all()}
    names = library.suggest_names("graine")
    assert names and not any(n.lower() in taken for n in names)


def test_dna_profiles(tmp_path):
    assert {"sport_premium", "offroad", "utility"} <= {p.key for p in dna.PRESETS}
    assert len(dna.PARAMETERS) == 10 and all(set(p.values) == set(dna.PARAMETERS) for p in dna.PRESETS)
    library = dna.DnaLibrary(tmp_path / "dna.json")
    saved = library.save("Mon style", {"sport": 120, "luxury": "40"}, to_user=True)
    assert saved.values["sport"] == 100 and saved.values["luxury"] == 40  # bornes 0-100
    assert dna.DnaLibrary(tmp_path / "dna.json").get(saved.key).name == "Mon style"


# --- Analyse ---------------------------------------------------------------------------------


def test_components_and_design_analysis(lore):
    session, root, engine = lore
    vc = components.identify(session, root)
    kinds = [c.kind for c in vc.components]
    expected = (
        ("headlight", 2),
        ("taillight", 2),
        ("grille", 1),
        ("front_bumper", 1),
        ("rear_bumper", 1),
        ("mirror", 2),
        ("exhaust", 1),
        ("body", 1),
    )
    for kind, count in expected:
        assert kinds.count(kind) == count, kind
    assert len(vc.wheels) == 4 and vc.wheelbase == pytest.approx(2.74, abs=0.02)
    design_id = engine.create_design(root)
    report = engine.analyze(design_id)
    statuses = {e["key"]: e["status"] for e in report["entries"]}
    assert statuses["wheelbase"] == "measured" and statuses["length"] == "measured"
    assert statuses["silhouette"] == "recognized" and statuses["headlights"] == "recognized"
    assert statuses["signature"] == "unknown" and statuses["rims"] == "unknown"  # rien d'inventé
    assert statuses["volume"] == "measured"  # carrosserie fermée
    engine.set_analysis_value(design_id, "type", "coupé")
    entry = next(e for e in engine.design(design_id)["analysis"]["entries"] if e["key"] == "type")
    assert entry["status"] == "user" and entry["original"]["status"] == "recognized"


# --- Transformations réelles ------------------------------------------------------------------------


def test_deformations_change_vertices(lore):
    session, root, _engine = lore
    height = fresh_state(session, root).frame.height
    state = fresh_state(session, root)
    operations.apply(state, "nose_length", {"amount": 0.2})
    body = next(e for e in state.entries.values() if e.kind == "body")
    moved = np.linalg.norm(body.mesh.positions - body.original.positions, axis=1)
    assert body.edited and moved.max() == pytest.approx(0.2, abs=0.01)
    state = fresh_state(session, root)
    operations.apply(state, "roof_height", {"amount": -0.08})
    top = max(state.world_points(e)[:, 1].max() for e in state.body_entries())
    assert top == pytest.approx(height - 0.08, abs=0.01)
    lights = state.owners_of("headlight")
    operations.apply(state, "hood_height", {"amount": 0.05})
    assert any(np.linalg.norm(state.owner_move(o)) > 0 for o in lights)  # les optiques suivent la carrosserie
    for key in operations.DEFORMATIONS:
        state = fresh_state(session, root)
        operations.apply(state, key, {})
        assert any(e.edited for e in state.entries.values()), key


def test_catalogue_operations_have_real_effects(lore):
    session, root, _engine = lore
    for key, spec in operations.OPERATIONS.items():
        state = fresh_state(session, root)
        messages = operations.apply(state, key, {})
        changed = (
            state.new_parts
            or state.hidden
            or state.materials
            or any(e.edited for e in state.entries.values())
        )
        assert changed and messages, key
        if spec.kind == "replace" and spec.components[0] in ("headlight", "taillight", "grille"):
            assert state.hidden, key  # pièce d'origine masquée, jamais supprimée
    state = fresh_state(session, root)
    operations.apply(state, "headlights", {"style": "round", "width": 9.0})  # paramètre borné
    assert len([p for p in state.new_parts if p.kind == "headlight"]) == 2


def test_incompatible_transformations(tmp_path):
    session = ProjectSession.create(tmp_path / "projets", "Boîte")
    group = SceneNode("Bloc", NodeKind.GROUP)
    session.scene.add(group)
    session.scene.meshes["k"] = shapes.box((1.8, 1.2, 4.0), "caisse")
    session.scene.add(SceneNode("caisse", NodeKind.MESH, mesh_key="k"), group.id)
    engine = LoreFriendlyEngine(session, None, tmp_path / "data")
    design_id = engine.create_design(group.id)
    available = engine.available_operations(engine.design(design_id))
    assert "track" not in available and "roof_height" not in available  # ni roues ni habitacle mesurable
    variant = engine.create_variant(design_id)
    with pytest.raises(IncompatibleTransformation, match="roues"):
        engine.apply_operation(design_id, variant, "track", {})
    with pytest.raises(IncompatibleTransformation, match="habitacle"):
        engine.apply_operation(design_id, variant, "roof_height", {})


def test_concepts_are_deterministic_and_respect_constraints(lore):
    _session, root, engine = lore
    design_id = engine.create_design(root)
    engine.choose_brand(design_id, "canis")
    engine.apply_dna_profile(design_id, "offroad")
    design = engine.design(design_id)
    request = engine.concept_request(design, 3)
    available = engine.available_operations(design)
    first, second = concepts.generate(request, available), concepts.generate(request, available)
    assert [p["plan"] for p in first] == [p["plan"] for p in second] and len(first) == 3
    assert all(p["title"].startswith("Canis") for p in first)
    request.constraints = ("keep_roof", "no_additions")
    for proposal in concepts.generate(request, available):
        used = {s["op"] for s in proposal["plan"]}
        assert not used & {"roof_height", "roof_slope"} and not used & concepts.ADDITIONS
    request.constraints = ()
    request.level = "original"
    assert all(len(p["plan"]) >= 6 for p in concepts.generate(request, available))


# --- Moteur : variantes, historique, sauvegarde ------------------------------------------------------


def test_variant_workflow_keeps_source_and_undo(lore, tmp_path):
    session, root, engine = lore
    before = geometry(session, root)
    design_id = engine.create_design(root)
    assert session.scene.nodes[root].locked
    engine.choose_brand(design_id, "pegassi")
    engine.apply_dna_profile(design_id, "supercar")
    proposals = engine.generate_concepts(design_id, 2)
    engine.apply_previews(design_id, engine.preview_job(design_id)(Ctx()))
    assert all(c["preview"] in session.scene.blobs for c in engine.design(design_id)["concepts"])
    variant = engine.apply_concept(design_id, proposals[0]["id"])
    design = engine.design(design_id)
    root_v = design["variants"][0]["root_id"]
    assert design["display"] == variant
    assert session.scene.nodes[root_v].visible and not session.scene.nodes[root].visible
    assert any(n.extra.get("edited_geometry") for n in session.scene.subtree(root_v))
    after = geometry(session, root)
    assert all(np.array_equal(before[k], after[k]) for k in before)  # source jamais modifiée
    steps = len(session.stack.history())
    engine.apply_operation(design_id, variant, "spoiler", {"height": 0.2})

    def has_spoiler() -> bool:
        return any(n.extra.get("lore", {}).get("part") == "spoiler" for n in session.scene.subtree(root_v))

    assert has_spoiler()
    session.stack.undo()
    assert not has_spoiler()
    session.stack.redo()
    assert has_spoiler() and len(session.stack.history()) == steps + 1
    point = engine.restore_point(design_id, variant, "Étape 1")
    restored = engine.restore(design_id, variant, point)
    assert restored != variant and len(engine.design(design_id)["variants"]) == 2
    comparison = engine.compare(design_id, SOURCE, variant)
    assert comparison["silhouettes"]["left"] < 0.999 and comparison["deformed"] > 0
    review = engine.review(design_id, variant)
    assert {a["status_label"] for a in review["aspects"]} <= set(originality.STATUS_LABELS.values())
    assert "ni un avis juridique" in review["disclaimer"]
    path = session.save()
    reopened = ProjectSession.open(path)
    engine2 = LoreFriendlyEngine(reopened, None, tmp_path / "data")
    design2 = engine2.design()
    assert len(design2["variants"]) == 2 and len(design2["concepts"]) == 2
    assert all(c["preview"] in reopened.scene.blobs for c in design2["concepts"])
    root2 = design2["variants"][0]["root_id"]
    materials = [reopened.scene.material_for(n.id) for n in reopened.scene.subtree(root2)]
    assert any(m is not None and m.is_emissive for m in materials)  # émission conservée dans le .lsfc
    assert engine2.compare(None, SOURCE, design2["variants"][0]["id"])["deformed"] > 0


def test_emergency_equipment_and_materials_preserved(lore):
    session, root, engine = lore
    session.scene.meshes["eq"] = shapes.lightbar()
    equipment = SceneNode(
        "Rampe", NodeKind.MESH, mesh_key="eq", extra={"emergency_equipment": {"component_id": "x"}}
    )
    session.scene.add(equipment, root)
    design_id = engine.create_design(root)
    variant = engine.create_variant(design_id)
    root_v = engine.design(design_id)["variants"][0]["root_id"]
    copies = [n for n in session.scene.subtree(root_v) if "emergency_equipment" in n.extra]
    assert len(copies) == 1  # l'équipement d'urgence suit la variante
    engine.apply_operation(design_id, variant, "light_colors", {"strength": 1.5})
    assert session.scene.material_for(copies[0].id) is None  # feux d'urgence ≠ optiques civiles
    assert session.scene.nodes[equipment.id].visible  # équipement de la source intact


def test_provenance_registry_rules(lore):
    _session, root, engine = lore
    design_id = engine.create_design(root)
    engine.choose_brand(design_id, "obey")
    variant = engine.create_variant(design_id)
    engine.apply_operation(design_id, variant, "grille", {})
    entries = engine.provenance()
    imported = next(e for e in entries if e["kind"] == "import")
    assert imported["license"] == provenance.UNKNOWN_LICENSE  # jamais inventée
    brand = next(e for e in entries if e["kind"] == "brand")
    assert brand["mentions"] and "Rockstar" in brand["license"]
    assert any(e["kind"] == "lore_part" for e in entries)
    engine.update_provenance(imported["id"], license="CC BY 4.0", author="Moi")
    engine.add_mention(imported["id"], "Modèle d'essai généré par script")
    updated = next(e for e in engine.provenance() if e["id"] == imported["id"])
    assert updated["license"] == "CC BY 4.0" and "Modèle d'essai généré par script" in updated["mentions"]
    with pytest.raises(provenance.ProvenanceError):
        provenance.remove_mention(engine.scene.documents.get("provenance"), imported["id"], "x")


def test_document_migration_from_v07():
    ai_doc = {"lore": {"selected": {"brand": "Corvane", "direction": "sobre", "details": ["calandre"]}}}
    doc = migrate(None, ai_doc)
    assert doc["format"] == 1 and doc["brands"][0]["name"] == "Corvane" and doc["migrated_from"]
    assert migrate({"designs": [{"id": "d"}]})["designs"][0]["variants"] == []


def test_analyzer_summary_excludes_unknown():
    report = {
        "entries": [
            {"label": "A", "value": "1 m", "status": "measured"},
            {"label": "B", "value": "", "status": "unknown"},
        ]
    }
    assert analyzer.summary(report) == "A : 1 m"
