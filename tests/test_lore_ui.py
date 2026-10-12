"""Lore Friendly Studio (interface) — parcours d'acceptation du prompt 8 dans la vraie fenêtre.

Test d'intégration RÉEL : véhicule d'essai original importé, transformations réelles du
maillage, propositions du moteur local déterministe (aucun moteur simulé). Les moteurs cloud
sont isolés (aucune clé) : leur indisponibilité est vérifiée.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from lsfcars.lorefriendly.engine import SOURCE
from lsfcars.project.model import VehicleRole, VehicleType
from lsfcars.scene.graph import NodeKind
from lsfcars.ui.dialogs.new_project import NewProjectRequest

LORE_GLB = Path(__file__).resolve().parents[1] / "samples" / "vehicule_lore.glb"


@pytest.fixture
def lore_window(window, qtbot, projects_dir, monkeypatch, tmp_path):
    monkeypatch.setenv("LSFCARS_ENGINES", str(tmp_path / "engines"))
    monkeypatch.delenv("LSFCARS_ANTHROPIC_API_KEY", raising=False)
    request = NewProjectRequest("Lore UI", projects_dir, VehicleType.CAR, VehicleRole.CIVILIAN, "")
    assert window.new_project(request)
    with qtbot.waitSignal(window.controller.import_finished, timeout=30000) as blocker:
        assert window.import_model(LORE_GLB)
    assert blocker.args[0]
    window.navigate("lore")
    qtbot.wait(50)
    return window


def notifications(window) -> list[tuple[str, str, str]]:  # type: ignore[no-untyped-def]
    received: list[tuple[str, str, str]] = []
    window.controller.notify.connect(lambda title, message, level: received.append((title, message, level)))
    return received


def mesh_positions(session, root) -> dict:  # type: ignore[no-untyped-def]
    return {
        n.id: session.geometry_for(n).positions.copy()
        for n in session.scene.subtree(root)
        if n.kind is NodeKind.MESH
    }


def test_lore_acceptance_flow(lore_window, qtbot, dialogs):
    window = lore_window
    page = window.lore_studio
    session = window.controller.session
    assert window.current_page() == "lore"  # 1-3. application ouverte, véhicule chargé, studio ouvert
    assert [page.left.tabText(i) for i in range(4)] == ["Source", "Marques", "Styles", "Presets"]
    assert [page.right.tabText(i) for i in range(4)] == [
        "Analyse",
        "Transformation",
        "Propositions",
        "Propriétés",
    ]
    tabs = [page.bottom.tabText(i) for i in range(5)]
    assert tabs == ["Historique", "Progression", "Diagnostics", "Validation", "Provenance"]

    page.source.sources.setCurrentRow(0)
    page.source.create_design()
    source_root = page.design()["source_id"]
    assert session.scene.nodes[source_root].locked
    before = mesh_positions(session, source_root)

    # 4. Analyse du design
    page.analyze()
    page.analysis.refresh()
    assert page.analysis.tree.topLevelItemCount() >= 5
    assert {"measured", "recognized", "unknown"} <= {
        e["status"] for e in page.design()["analysis"]["entries"]
    }

    # 5. Marque fictive
    page.brands.search.setText("Pegassi")
    page.brands.list.setCurrentRow(0)
    page.brands.choose()
    assert page.design()["brand"] == "pegassi"

    # 6. Direction stylistique (Design DNA)
    page.styles.profile.select_data("supercar")
    page.styles.apply_profile()
    assert page.design()["dna_profile"] == "supercar"

    # 7. Plusieurs propositions (rendus de la géométrie transformée, calculés en arrière-plan)
    page.proposals.count.setValue(3)
    page.proposals.generate()
    assert page.wait_idle(120000)
    concepts = page.design()["concepts"]
    assert len(concepts) == 3 and all(c["preview"] in session.scene.blobs for c in concepts)
    page.proposals.refresh()
    assert page.proposals.list.count() == 3 and not page.proposals.preview.pixmap().isNull()

    # 8 / 10. Comparer les propositions puis appliquer : variante originale (confirmation, une étape)
    page.proposals.list.setCurrentRow(1)
    history = len(session.stack.history())
    page.proposals.apply()
    assert ("confirm", "Confirmer la transformation") in dialogs.calls
    assert len(session.stack.history()) == history + 1
    assert page.target() != SOURCE and len(page.design()["variants"]) == 1

    # 9. Modifier une pièce (Front Design Studio : forme des phares) puis annuler / rétablir
    page.right.setCurrentIndex(1)
    page.transform.select("headlights")
    page.transform.params.set_value("style", "round")
    root_v = page.design()["variants"][0]["root_id"]
    existing = {n.id for n in session.scene.subtree(root_v)}
    page.transform.apply()
    created = [n.id for n in session.scene.subtree(root_v) if n.id not in existing]
    assert any(session.scene.nodes[i].extra.get("lore", {}).get("part") == "headlights" for i in created)
    window.controller.undo()
    assert not any(i in session.scene for i in created)
    window.controller.redo()
    assert all(i in session.scene for i in created)

    # 11. Vérifier les changements : comparaison réelle, modes, déplacements, revue d'originalité
    page.set_view("compare")
    result = page.comparison.measure()
    assert result is not None and result["deformed"] > 0 and result["silhouettes"]["left"] < 0.999
    for mode in ("split", "overlay", "wire", "materials", "side"):
        page.comparison.mode.select_data(mode)
        page.comparison.apply()
    page.comparison.toggle_displacements()
    assert page.comparison._overlay_points is not None and len(page.comparison._overlay_points) > 0
    page.set_view("3d")
    review = page.review()
    assert review is not None and len(review["aspects"]) == 8
    page.validation.refresh()
    assert page.validation.review.topLevelItemCount() == 8

    after = mesh_positions(session, source_root)
    assert all(np.array_equal(before[k], after[k]) for k in before)  # la source n'a jamais changé

    # Point de restauration et restauration non destructive (nouvelle variante)
    page.source.restore_point()
    point = page.design()["variants"][0]["restore_points"][0]["id"]
    page.source.refresh()
    page.source.points.select_data(point)
    page.source.restore()
    assert len(page.design()["variants"]) == 2

    # 12-14. Sauvegarde, fermeture, réouverture sans perte
    assert window.save_project()
    path = session.file_path
    assert window.close_project()
    assert window.open_project(path)
    window.navigate("lore")
    qtbot.wait(50)
    design = page.design()
    assert len(design["variants"]) == 2 and len(design["concepts"]) == 3
    assert design["brand"] == "pegassi" and design["analysis"] and design["originality"]
    assert all(c["preview"] in window.controller.session.scene.blobs for c in design["concepts"])
    page.provenance_panel.refresh()
    assert page.provenance_panel.table.rowCount() >= 3

    # 15. Transfert vers le Vehicle Editor et Livery Studio
    page.show(design["variants"][0]["id"])
    page.transfer_to_editor()
    assert window.current_page() == "studio"
    assert window.controller.session.selection.ids == [design["variants"][0]["root_id"]]
    window.navigate("lore")
    page.transfer_to_livery()
    assert window.current_page() == "liveries"


def test_unavailable_ai_and_simple_mode(lore_window, qtbot, dialogs):
    window = lore_window
    page = window.lore_studio
    received = notifications(window)
    page.source.sources.setCurrentRow(0)
    page.source.create_design()
    page.brands.search.setText("Karin")
    page.brands.list.setCurrentRow(0)
    page.brands.choose()
    page.proposals.engine_choice.select_data("anthropic")
    page.proposals.generate()  # 16. IA cloud indisponible : refus expliqué, aucun envoi
    assert any(title == "Propositions cloud" and level == "warning" for title, _m, level in received)
    assert ("confirm", "Transfert cloud") not in dialogs.calls
    assert not page.design()["concepts"]
    page.set_simple(True)
    assert not page.right.isTabVisible(1) and not page.left.isTabVisible(2)
    page.set_simple(False)
    assert page.right.isTabVisible(1)


def test_incompatible_transformation_is_refused(lore_window, qtbot, dialogs):
    window = lore_window
    page = window.lore_studio
    received = notifications(window)
    page.source.sources.setCurrentRow(0)
    page.source.create_design()
    page.new_variant()
    session = window.controller.session
    root_v = page.design()["variants"][0]["root_id"]
    for node in session.scene.subtree(root_v):  # 17. roues non identifiables : « voies » incompatible
        node.name = node.name.replace("pneu", "piece").replace("jante", "piece")
    count = len(session.stack.history())
    assert page.apply_plan([{"op": "track", "params": {"amount": 0.04}}], "Voies") is None
    assert len(session.stack.history()) == count
    assert any("incompatible" in message for _t, message, _l in received)
