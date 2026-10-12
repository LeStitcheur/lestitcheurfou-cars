"""AI Vehicle Creator (interface) : parcours d'acceptation du prompt 7 dans la vraie fenêtre.

Génération **réelle** avec le moteur local intégré (LSF Silhouette, algorithme déterministe) :
aucun moteur n'est simulé ici. Les moteurs installés sur la machine (TripoSR…) sont isolés
(``LSFCARS_ENGINES`` vide) pour que le test soit reproductible.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lsfcars.project.model import VehicleRole, VehicleType
from lsfcars.ui.dialogs.new_project import NewProjectRequest

REFERENCES = Path(__file__).resolve().parents[1] / "samples" / "references"


@pytest.fixture
def ai_window(window, qtbot, projects_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("LSFCARS_ENGINES", str(tmp_path / "engines"))
    window.ai.manager.adapters["triposr"].configure({"root": str(tmp_path / "engines" / "triposr")})
    request = NewProjectRequest("IA UI", projects_dir, VehicleType.CAR, VehicleRole.CIVILIAN, "")
    assert window.new_project(request)
    window.navigate("ai")
    assert window.ai.wait_idle(60000)  # détection du matériel et des moteurs
    return window


def test_ai_acceptance_flow(ai_window, qtbot, dialogs):
    window = ai_window
    page = window.ai
    assert window.current_page() == "ai"  # 1-2. AI Vehicle Creator ouvert
    assert [page.left.tabText(i) for i in range(3)] == ["Références", "Analyse", "Lore Friendly"]
    assert [page.right.tabText(i) for i in range(4)] == ["Génération", "Maillage", "Textures", "Historique"]
    assert page.manager.availability["lsf-silhouette"].ok
    assert not page.manager.availability["triposr"].ok  # isolé : non installé dans ce test
    assert page.manager.hardware is not None and page.manager.hardware.cpu
    assert "disponible" in page.badge.toolTip()  # texte complet (badge abrégé si étroit)

    # 3. Plusieurs images de référence
    added = page.import_references(sorted(REFERENCES.glob("demo_*.png")))
    assert len(added) == 5
    qtbot.wait(50)
    assert page.references.list.count() == 5
    views = {r["view"] for r in page.creator.references()}
    assert {"left", "front", "back", "top", "three_quarter"} <= views
    # annotation (zone de logo) tracée sur le tableau des références
    page.references.list.setCurrentRow(0)
    page.references.note_kind.select_data("logo")
    page.set_board_mode("annotate")
    page.board.drag((0.4, 0.4), (0.6, 0.55))
    qtbot.wait(20)
    ref = page.creator.reference(page.references.current_id())
    assert [n["kind"] for n in ref["annotations"]] == ["logo"]
    page.set_board_mode("view")

    # 4. Analyse (tâche en arrière-plan)
    page.analyze()
    assert page.wait_idle()
    assert page.creator.document()["analysis"]["fields"]["type"]["value"] == "sedan"
    page.analysis.refresh()
    assert page.analysis.tree.topLevelItemCount() > 5

    # 5-6. Moteur et mode : le routage automatique choisit un moteur local disponible
    page.generation.mode.select_data("local")
    page.generation.refresh()
    assert page.generation.chosen_engine() == "lsf-silhouette"
    assert "Écarté" in page.generation.routing.text()  # moteurs indisponibles expliqués

    # 7-10. Génération réelle, progression, récupération, affichage dans le viewport
    progress: list[float] = []
    page.manager.queue.listeners.append(lambda job: progress.append(job.progress))
    job = page.generate()
    assert job is not None
    assert page.wait_idle(120000)
    assert job.status == "succeeded", job.error
    assert progress and max(progress) == pytest.approx(1.0)
    record = page.creator.records()[-1]
    assert record["status"] == "succeeded" and record["engine"] == "lsf-silhouette"
    assert set(record["views_used"]) >= {"left", "front", "top"}
    session = window.controller.session
    assert record["root_id"] in session.scene
    meshes = [session.geometry_for(n) for n in session.scene.subtree(record["root_id"])]
    assert any(any(item.mesh is m for m in meshes if m is not None) for item in page.viewport.draw_items())

    # 11-12. Analyse des défauts et correction annulable
    report = page.mesh.analyze()
    assert report is not None and report["triangles"] > 1000
    assert page.mesh.tree.topLevelItemCount() == 4  # diagnostics / corrections / suggestions / validation
    before = len(session.stack.history())
    assert page.apply_fix("smooth") is not None
    assert len(session.stack.history()) == before + 1

    # Textures (projection des références) appliquées au modèle
    page.textures.size.select_data(512)
    page.generate_textures()
    assert page.wait_idle(120000)
    assert page.texture_outcome is not None
    material_id = page.apply_textures()
    assert material_id and session.scene.materials[material_id].texture

    # Lore Friendly : propositions et choix
    page.lore_proposals()
    page.lore.refresh()
    assert page.lore.list.count() == 3
    page.lore.list.setCurrentRow(2)
    page.lore.select()
    assert page.creator.document()["lore"]["selected"]["level"] == "original"

    # 13-14. Sauvegarde, fermeture, réouverture sans perte
    assert window.save_project()
    path = session.file_path
    assert window.close_project()
    assert window.open_project(path)
    window.navigate("ai")
    qtbot.wait(50)
    doc = page.creator.document()
    assert len(doc["references"]) == 5 and len(doc["generations"]) == 1
    assert doc["generations"][0]["thumbnail"] in window.controller.session.scene.blobs
    assert doc["lore"]["selected"]["level"] == "original"
    page.history.refresh()
    assert page.history.list.count() == 1
    root = page.creator.reopen(doc["generations"][0]["id"])
    assert root in window.controller.session.scene

    # 15. Transfert vers le Vehicle Editor
    page.transfer_to_editor()
    assert window.current_page() == "studio"
    assert window.controller.session.selection.ids == [root]


def test_engine_failure_is_recorded(ai_window, qtbot):
    page = ai_window.ai
    page.import_references([REFERENCES / "demo_trois_quarts.png"])  # aucune vue de profil
    page.generation.mode.select_data("local")
    page.generation.refresh()
    assert page.generation.chosen_engine() is None  # LSF Silhouette écarté (profil requis)
    assert page.generate() is None
    job = page.generate("lsf-silhouette")  # choix manuel : erreur explicite, enregistrée
    assert page.wait_idle()
    assert job.status == "failed" and "profil" in job.error
    record = page.creator.records()[-1]
    assert record["status"] == "failed" and record["error"]


def test_lore_navigation_and_engines_dialog(ai_window, qtbot):
    window = ai_window
    window.navigate("lore")  # v0.8 : Lore Friendly Studio (page dédiée)
    assert window.current_page() == "lore" and window.stack.currentWidget() is window.lore_studio
    window.navigate("ai")
    window.ai.lore_requested.emit()  # lien depuis l'onglet Lore Friendly d'AI Vehicle Creator
    assert window.current_page() == "lore"
    dialog = window.ai.open_engines()
    assert dialog.tabs.count() == 1 + len(window.ai.manager.adapters)
    dialog.close()
