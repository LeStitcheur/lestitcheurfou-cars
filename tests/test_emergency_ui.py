"""Emergency Studio (interface) : parcours d'acceptation du prompt 5 dans la vraie fenêtre.

Ouvrir → importer un véhicule civil → Emergency Studio → variante LSPD → rampe → feux de
calandre → motif → aperçu → intérieur → variante EMS → sauvegarder → fermer → rouvrir.
"""

from __future__ import annotations

import pytest

from lsfcars.editor.vehicle import VehicleAxes
from lsfcars.emergency.equipment import EquipmentLibrary
from lsfcars.project.model import VehicleRole, VehicleType
from lsfcars.ui.dialogs.new_project import NewProjectRequest


@pytest.fixture
def emergency_window(window, qtbot, projects_dir, sample_glb, tmp_path):
    library = EquipmentLibrary(tmp_path / "equipment")
    library.ensure_builtins()
    window.emergency.set_library(library)
    request = NewProjectRequest("Urgence UI", projects_dir, VehicleType.CAR, VehicleRole.LSPD, "")
    assert window.new_project(request)
    with qtbot.waitSignal(window.controller.import_finished, timeout=30000) as blocker:
        assert window.import_model(sample_glb)
    assert blocker.args[0]
    window.controller.editor.set_axes(VehicleAxes(forward_sign=1))
    window.navigate("emergency")
    return window


def lit(page) -> int:
    return sum(len(o.points) for o in page.light_overlays() if o.point_size == 14.0 and o.points is not None)


def test_acceptance_flow(emergency_window, tmp_path):
    window = emergency_window
    page = window.emergency
    assert window.current_page() == "emergency"
    assert [page.left.tabText(i) for i in range(page.left.count())] == [
        "Service",
        "Équipements",
        "Composants",
    ]
    assert page.bottom.tabText(0) == "Timeline lumineuse"
    # 4. Variante LSPD
    service = page.service_panel
    service.service.select_data("lspd")
    service.name.setText("Berline LSPD")
    lspd = service.create()
    page.refresh()
    assert page.active_variant().id == lspd and "LSPD" in page.variant_badge.text()
    # 5. Rampe lumineuse (zone toit)
    equipment = page.equipment_panel
    assert equipment.select_component("lsf-pol-lightbar")
    equipment.zone.select_data("roof")
    bar = equipment.add()
    assert bar is not None and len(bar.light_ids) == 8
    # 6. Feux de calandre
    assert equipment.select_component("lsf-pol-grille")
    equipment.zone.select_data("grille")
    assert equipment.add() is not None
    # Placement sur la carrosserie visée (clic / glisser-déposer) au centre du viewport
    page.viewport.frame_bounds(window.controller.session.world_bounds())
    assert page.place_at("lsf-pol-beacon", page.viewport.width() / 2, page.viewport.height() / 2) is not None
    page.refresh()
    assert page.components_panel.list.count() == 3
    # 7. Motif : preset triple flash puis édition dans la timeline
    timeline = page.timeline
    timeline.preset.select_data("triple")
    timeline.create()
    page.refresh()
    assert timeline.table.columnCount() > 0
    timeline.toggle_cell(1, 0)
    timeline.commit()
    page.refresh()
    # 8. Prévisualisation des éclairages (simulation)
    page.set_playing(True)
    counts = set()
    for _ in range(16):
        page.advance(37)
        counts.add(lit(page))
    page.set_playing(False)
    assert max(counts) > 0 and len(counts) > 1  # les feux clignotent
    # 9. Équipements intérieurs
    page.configuration.apply_interior("police")
    page.refresh()
    assert page.components_panel.list.count() >= 7
    # Éclairage : réglage d'un feu sélectionné
    page.lighting.list.item(0).setSelected(True)
    page.lighting._update(color="white")
    assert page.studio.state().active_variant.lights[0].color == "white"
    # 10. Variante EMS
    service.service.select_data("ems")
    service.name.setText("Berline EMS")
    ems = service.create()
    page.refresh()
    assert equipment.select_component("lsf-ems-lightbar")
    equipment.zone.select_data("roof")
    assert equipment.add() is not None
    # Export (données intermédiaires) depuis le panneau
    page.export_panel.adapter.select_data("lsf-json")
    assert page.export_panel.export(str(tmp_path))
    # Passage au Vehicle Editor et retour : rien n'est perdu
    window.navigate("studio")
    window.navigate("emergency")
    page.refresh()
    assert len(page.studio.state().variants) == 2
    # 11-13. Sauvegarder, fermer, rouvrir
    assert window.save_project()
    path = window.controller.session.file_path
    assert window.close_project()
    assert window.open_project(path)
    window.navigate("emergency")
    page.refresh()
    state = page.studio.state()
    assert [v.id for v in state.variants] == [lspd, ems]
    lspd_variant = state.variant(lspd)
    assert len(page.studio.equipment_nodes(lspd_variant)) >= 7
    assert lspd_variant.lights[0].color == "white"
    assert len(lspd_variant.patterns) >= 2
    # Annuler / rétablir depuis la fenêtre
    page.run("Variante", lambda: page.studio.activate_variant(lspd))
    window.controller.undo()
    assert page.studio.state().active == ems
    window.controller.redo()
    assert page.studio.state().active == lspd


def test_invalid_equipment_and_unavailable_export(emergency_window, tmp_path):
    page = emergency_window.emergency
    assert (
        page.run("Équipement", lambda: page.studio.add_equipment("lsf-pol-lightbar")) is None
    )  # sans variante
    page.service_panel.create()
    page.refresh()
    assert page.run("Équipement", lambda: page.studio.add_equipment("inexistant")) is None
    page.export_panel.adapter.select_data("els-classic")
    assert page.export_panel.export(str(tmp_path)) == []
    assert "spécification" in page.export_panel.issues.item(0).text()
