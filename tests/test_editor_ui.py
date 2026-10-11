"""Vehicle Editor (interface) : parcours d'acceptation du prompt 4 dans la vraie fenêtre.

Ouvrir → charger un véhicule → sélectionner une pièce → modifier sa géométrie (mode Édition) →
ajouter une pièce → remplacer un composant → matériaux → roues → ancrages → enregistrer →
fermer → rouvrir sans perte.
"""

from __future__ import annotations

import numpy as np
import pytest

from lsfcars.editor import edit_state as modes
from lsfcars.editor.library import ComponentLibrary
from lsfcars.editor.vehicle import VehicleAxes
from lsfcars.project.model import VehicleRole, VehicleType
from lsfcars.scene import editmesh, gizmo, mathutils
from lsfcars.scene.graph import NodeKind
from lsfcars.ui.dialogs.new_project import NewProjectRequest


@pytest.fixture
def editor_window(window, qtbot, projects_dir, sample_glb, tmp_path):
    request = NewProjectRequest("Atelier UI", projects_dir, VehicleType.CAR, VehicleRole.CIVILIAN, "")
    assert window.new_project(request)
    with qtbot.waitSignal(window.controller.import_finished, timeout=30000) as blocker:
        assert window.import_model(sample_glb)
    assert blocker.args[0]
    library = ComponentLibrary(tmp_path / "bibliotheque")
    library.ensure_builtins()
    window.studio.library._library = library
    window.studio.library.refresh()
    window.controller.editor.set_axes(VehicleAxes(forward_sign=1))  # modèle d'exemple : avant vers +Z
    return window


def node_named(session, name):
    return next(n for n in session.scene.walk() if n.name == name)


def test_vehicle_editor_layout_and_modes(editor_window):
    window = editor_window
    studio, session = window.studio, window.controller.session
    assert window.current_page() == "studio"
    assert [studio.left.tabText(i) for i in range(studio.left.count())] == ["Scène", "Bibliothèque", "Outils"]
    right = [studio.right.tabText(i) for i in range(studio.right.count())]
    assert right[:3] == ["Propriétés", "Géométrie", "Ancrages"]
    bottom = {studio.bottom.tabText(i) for i in range(studio.bottom.count())}
    assert {"Statistiques", "Historique", "Compatibilité FiveM"} <= bottom
    for key, page in (("bodywork", "Carrosserie"), ("wheels", "Roues"), ("interior", "Habitacle")):
        studio.set_workspace(key)
        assert studio.right.tabText(studio.right.currentIndex()) == page
    studio.set_workspace("editor")
    assert studio.right.indexOf(studio.workshop) < 0
    studio.set_panel_visible("left", False)
    studio.save_layout()
    studio.set_panel_visible("left", True)
    studio.restore_layout()
    assert studio.left.isHidden()  # disposition mémorisée
    studio.set_panel_visible("left", True)
    tire = node_named(session, "pneu_avant_gauche").id
    studio.set_mode(modes.COMPONENT)
    window.controller.select([tire])
    assert session.selection.active == node_named(session, "roue_avant_gauche").id  # composant entier
    studio.set_mode(modes.OBJECT)


def test_acceptance_flow_save_close_reopen(editor_window):
    window = editor_window
    studio, ctl = window.studio, window.controller
    session = ctl.session
    body = node_named(session, "caisse")

    # 3-4. Sélection d'une pièce et modification de sa géométrie en mode Édition
    ctl.select([body.id])
    studio.set_mode(modes.EDIT)
    assert ctl.edit.editing and ctl.edit.target == body.id
    assert studio.tools.currentIndex() == 1
    mesh = ctl.edit_mesh()
    top = int(np.argmax(editmesh.face_normals(mesh.positions, mesh.indices)[:, 1]))
    ctl.edit.set_element(editmesh.FACE, mesh)
    ctl.edit.select({top})
    studio.tools.extrude_distance.setValue(0.05)
    studio.tools._extrude()
    assert ctl.edit_mesh().triangle_count > mesh.triangle_count
    assert studio.viewport.overlays()  # superposition du mode Édition
    studio.tools._select("linked")
    studio.tools.move.set_value([0.0, 0.02, 0.0])
    studio.tools._move()
    studio.set_mode(modes.OBJECT)
    triangles = session.geometry_for(session.scene.nodes[body.id]).triangle_count

    # 5. Ajout d'une pièce (bibliothèque)
    library = studio.library
    library.search.setText("aileron")
    spoiler_id = library.add_selected()
    assert spoiler_id in session.scene and session.scene.nodes[spoiler_id].name == "Aileron GT"

    # 6. Remplacement d'un composant (prévisualisation puis confirmation)
    target = node_named(session, "phare_gauche").id
    ctl.select([target])
    assert studio.open_replace(target, "lsf-headlight", modal=False)
    dialog = studio.replace_dialog
    assert dialog.preview() and "Matériaux" in dialog.report.toPlainText()
    dialog.confirm()
    assert target not in session.scene

    # 7. Matériaux (preset automobile)
    ctl.select([spoiler_id])
    material_editor = studio.properties.material_editor
    material_editor.refresh()
    material_editor.preset.setCurrentIndex(material_editor.preset.findData("chrome"))
    material_editor._apply_preset()
    spoiler_mesh = next(n for n in session.scene.subtree(spoiler_id) if n.kind is NodeKind.MESH)
    assert session.scene.material_for(spoiler_mesh.id).preset == "chrome"

    # 8. Roues
    wheels = studio.wheels
    studio.set_workspace("wheels")
    assert wheels.table.rowCount() == 4
    wheels.track.setValue(1.9)
    wheels._track()
    assert ctl.editor.wheels().track == pytest.approx(1.9, abs=1e-4)
    wheels.toggle_spin()
    wheels._spin_step()
    assert studio.viewport.display_matrices
    wheels.toggle_spin()
    assert not studio.viewport.display_matrices

    # 9. Points d'ancrage
    ctl.select([body.id])
    studio.anchors.name.setText("Rampe de toit")
    studio.anchors.type.select_data("roof")
    anchor_id = studio.anchors.create()
    assert session.scene.nodes[anchor_id].kind is NodeKind.ANCHOR
    assert any(o.xray for o in studio.viewport.overlays())  # axes de l'ancrage
    studio.history.refresh()
    assert studio.history.list.count() > 5
    studio.compat.refresh()
    assert studio.compat.list.count() >= 1

    # 10-12. Enregistrer, fermer, rouvrir sans perte
    assert window.save_project()
    path = session.file_path
    assert window.close_project()
    assert window.open_project(path)
    again = window.controller.session
    assert again.geometry_for(again.scene.nodes[body.id]).triangle_count == triangles
    assert again.scene.nodes[anchor_id].kind is NodeKind.ANCHOR
    assert again.scene.material_for(spoiler_mesh.id).preset == "chrome"
    assert target not in again.scene
    assert again.project.editor["forward_sign"] == 1
    assert window.controller.editor.wheels().track == pytest.approx(1.9, abs=1e-4)


def test_interior_and_bodywork_studios(editor_window):
    window = editor_window
    studio, ctl = window.studio, window.controller
    session = ctl.session
    studio.set_workspace("interior")
    assert studio.interior.list.count() >= 1  # « habitacle » du modèle d'exemple
    studio.interior.isolate.setChecked(True)
    assert studio.viewport.isolated
    studio.interior.isolate.setChecked(False)
    studio.interior.hide_body.setChecked(True)
    assert studio.viewport.hidden
    studio.interior.hide_body.setChecked(False)
    assert studio.interior.interior_camera() and studio.viewport.camera.mode == "free"
    studio.interior._create_configs()
    assert studio.interior.active_config.count() == 3
    studio.interior._add("lsf-seat")
    studio.set_workspace("bodywork")
    assert studio.bodywork.panels.count() >= 1
    created = studio.bodywork.create("lsf-bumper", "front")
    assert created in session.scene
    ctl.select([created])
    studio.bodywork._mirror()
    assert session.selection.active != created


def test_edit_mode_viewport_picking(editor_window):
    window = editor_window
    studio, ctl = window.studio, window.controller
    session = ctl.session
    body = node_named(session, "caisse")
    ctl.select([body.id])
    viewport = studio.viewport
    viewport.frame_bounds(session.world_bounds([body.id]))
    studio.set_mode(modes.EDIT)
    mesh = ctl.edit_mesh()
    ctl.edit.set_element(editmesh.FACE, mesh)
    assert viewport.pick_element(viewport.width() / 2, viewport.height() / 2) is not None
    ctl.edit.set_element(editmesh.VERTEX, mesh)
    topo = editmesh.topology(mesh)
    world = viewport._world_of(body.id)
    points = mathutils.transform_points(world, topo.positions)
    screen = gizmo.project(viewport.camera, points, viewport.width(), viewport.height())
    width, height = viewport.width(), viewport.height()
    inside = [p for p in screen if np.isfinite(p).all() and 0 < p[0] < width and 0 < p[1] < height]
    assert inside
    assert viewport.pick_element(float(inside[0][0]), float(inside[0][1])) is not None
    ctl.toggle_edit_mode()
    assert ctl.edit.mode == modes.OBJECT
