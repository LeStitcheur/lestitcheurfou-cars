"""Vehicle Editor (v0.4) : géométrie, composants, roues, ancrages, matériaux, historique, sauvegarde.

Les 17 scénarios obligatoires du prompt 4 sont couverts ici (logique sans interface) ; les
interactions Qt sont testées dans ``test_editor_ui.py``.
"""

from __future__ import annotations

import numpy as np
import pytest

from lsfcars.editor import compat, vehicle
from lsfcars.editor.blender_ops import bevel_available, bevel_edges
from lsfcars.editor.library import ComponentLibrary
from lsfcars.editor.operations import ReplaceOptions, VehicleEditor
from lsfcars.project import restore_points
from lsfcars.project.model import VehicleType
from lsfcars.project.session import ProjectSession
from lsfcars.scene import editmesh, shapes
from lsfcars.scene.editmesh import EditError
from lsfcars.scene.graph import NodeKind
from lsfcars.scene.transform import Transform

WHEELS = {
    "Roue avant gauche": (-0.8, 0.34, -1.3),
    "Roue avant droite": (0.8, 0.34, -1.3),
    "Roue arrière gauche": (-0.8, 0.34, 1.3),
    "Roue arrière droite": (0.8, 0.34, 1.3),
}


@pytest.fixture
def car(projects_dir):
    """Véhicule synthétique : caisse et quatre roues (formes originales)."""
    session = ProjectSession.create(projects_dir, "Atelier")
    editor = VehicleEditor(session)
    body = editor.add_mesh(
        shapes.box((1.8, 1.0, 4.2), "Carrosserie"), "Carrosserie", transform=Transform([0, 0.9, 0])
    )
    wheels = {
        name: editor.add_mesh(shapes.wheel(), name, transform=Transform(list(p)))
        for name, p in WHEELS.items()
    }
    session.stack.clear()
    session.stack.mark_clean()
    return session, editor, body, wheels


def world_center(session, node_id):
    bmin, bmax = session.world_bounds([node_id], only_visible=False)
    return (bmin + bmax) / 2


# 1. Importation d'un modèle ------------------------------------------------------------


def test_import_model_then_edit_geometry(projects_dir, sample_glb):
    session = ProjectSession.create(projects_dir, "Import")
    root = session.import_model(sample_glb)
    meshes = [n for n in session.scene.walk(root) if n.kind is NodeKind.MESH]
    assert meshes
    original = session.geometry_for(meshes[0])
    editor = VehicleEditor(session)
    editor.edit(meshes[0].id, lambda m: editmesh.translate_elements(m, "vertex", [0], (0, 0.1, 0)), "Sommet")
    node = session.scene.nodes[meshes[0].id]
    assert node.asset_id is None and node.extra["edited_geometry"]  # géométrie locale du projet
    assert session.geometry_for(node) is not original
    asset = next(iter(session.project.assets.values()))
    assert (session.project.project_dir / asset.rel_path).stat().st_size > 0  # copie intacte
    session.stack.undo()
    assert session.geometry_for(session.scene.nodes[meshes[0].id]) is original


# 2-5. Sélection d'un composant, déplacement, rotation, échelle ---------------------------


def test_component_selection_and_transforms(car):
    session, editor, body, wheels = car
    wheel = wheels["Roue avant gauche"]
    assert vehicle.component_root(session.scene, wheel) == wheel
    assert vehicle.role(session.scene, session.scene.nodes[wheel]) == vehicle.ROLE_MOBILE
    assert vehicle.category(session.scene, session.scene.nodes[body]) == "carrosserie"
    before = world_center(session, wheel)
    editor.move_world({wheel: np.array([0.0, 0.0, -0.2])})
    assert np.allclose(world_center(session, wheel), before + [0, 0, -0.2], atol=1e-5)
    rotated = session.scene.nodes[wheel].transform.copy()
    rotated.rotation = [0.0, 30.0, 0.0]
    session.set_transforms({wheel: rotated}, "Rotation")
    assert session.scene.nodes[wheel].transform.rotation[1] == pytest.approx(30.0)
    editor.scale_wheels([wheel], 1.2)
    assert session.scene.nodes[wheel].transform.scale[0] == pytest.approx(1.2)
    assert np.allclose(world_center(session, wheel), before + [0, 0, -0.2], atol=1e-4)  # centre conservé


# 6-7. Modification de géométrie, extrusion ------------------------------------------------


def test_vertex_edit_and_extrusion(car):
    session, editor, body, _ = car
    mesh = editor.mesh_of(body)
    up = int(np.argmax(editmesh.face_normals(mesh.positions, mesh.indices)[:, 1]))
    top = editmesh.coplanar_faces(mesh, up)
    assert len(top) == 2
    result = editor.edit(body, lambda m: editmesh.extrude_faces(m, top, 0.3), "Extrusion")
    extruded = editor.mesh_of(body)
    assert extruded.triangle_count == mesh.triangle_count + 8
    assert extruded.bounds[1][1] == pytest.approx(mesh.bounds[1][1] + 0.3, abs=1e-5)
    assert result.selection == top
    editor.edit(body, lambda m: editmesh.scale_elements(m, "face", top, (0.5, 1, 0.5)), "Échelle des faces")
    editor.edit(body, lambda m: editmesh.inset_faces(m, [0, 1], 0.2), "Inset")
    assert editor.mesh_of(body).triangle_count > extruded.triangle_count
    assert editmesh.uv_report(editor.mesh_of(body)).status in ("ok", "warning")


def test_merge_delete_separate_normals(car):
    session, editor, body, _ = car
    mesh = editor.mesh_of(body)
    editor.edit(body, lambda m: editmesh.merge_vertices(m, "vertex", [0, 1]), "Fusion")
    assert editor.mesh_of(body).triangle_count < mesh.triangle_count
    part = editor.separate(body, [0, 1])
    assert session.scene.nodes[part].kind is NodeKind.MESH and editor.mesh_of(part).triangle_count == 2
    editor.edit(body, lambda m: editmesh.delete_faces(m, [0]), "Suppression de faces")
    assert editmesh.make_normals_consistent(editmesh.flip_faces(shapes.box(), [0]).mesh).warnings
    editor.edit(body, editmesh.recalculate_normals, "Normales")


# 8. Symétrie ------------------------------------------------------------------------------


def test_symmetry_mesh_and_mirror_duplicate(car):
    session, editor, _, _ = car
    spoiler = editor.add_mesh(shapes.spoiler(), "Aileron gauche", transform=Transform([-0.5, 1.5, 1.8]))
    copies = editor.mirror_duplicate([spoiler])
    copy = session.scene.nodes[copies[0]]
    assert copy.name == "Aileron droite"
    assert all(v > 0 for v in copy.transform.scale)  # pas d'échelle négative
    assert np.allclose(
        world_center(session, copies[0]), world_center(session, spoiler) * [-1, 1, 1], atol=1e-4
    )
    skewed = editmesh.translate_elements(shapes.box(), "vertex", [0], (0.4, 0, 0)).mesh
    lo, hi = editmesh.symmetrize(skewed, 0).mesh.bounds
    assert lo[0] == pytest.approx(-hi[0], abs=1e-5)
    session.stack.undo()
    assert copies[0] not in session.scene


# 9. Remplacement de pièce -------------------------------------------------------------------


def test_replace_component_keeps_old_in_history(car, tmp_path):
    session, editor, _, wheels = car
    library = ComponentLibrary(tmp_path / "lib")
    library.ensure_builtins()
    rim = library.get("lsf-rim7")
    target = wheels["Roue avant droite"]
    anchor = editor.add_anchor(target, "Capteur", "generic", (0.1, 0, 0))
    target_center = world_center(session, target)
    command, report = editor.build_replacement(
        target, library.payload(rim), ReplaceOptions(fit_dimensions=True)
    )
    assert report.warnings and "mobile" in report.warnings[0]
    editor.preview(command)  # prévisualisation sans historique
    assert target not in session.scene
    editor.cancel()
    assert target in session.scene
    report = editor.replace(target, library.payload(rim), ReplaceOptions(fit_dimensions=True))
    new_id = session.selection.active
    assert target not in session.scene and report.anchors_moved == 1
    assert session.scene.nodes[anchor].parent_id == new_id
    assert np.allclose(world_center(session, new_id), target_center, atol=1e-3)  # pivots alignés
    session.stack.undo()
    assert target in session.scene and new_id not in session.scene  # ancienne pièce restaurée


# 10. Ajout d'un accessoire ---------------------------------------------------------------


def test_library_add_accessory_and_delete_keeps_project(car, tmp_path):
    session, editor, _, _ = car
    library = ComponentLibrary(tmp_path / "lib")
    assert library.ensure_builtins() >= 20
    assert {c.category for c in library.components()} >= {"spoilers", "jantes", "urgence", "sieges"}
    lightbar = library.search("rampe", "urgence")[0]
    assert lightbar.license and lightbar.author and lightbar.attach_points
    root = editor.insert_payload(library.payload(lightbar, session.project), None, None, "Ajout rampe")
    assert any(n.kind is NodeKind.ANCHOR for n in session.scene.subtree(root))
    preset = library.save_from_scene(session, root, "Ma rampe", "urgence", author="Moi")
    copy = library.duplicate(preset.id)
    library.delete(preset.id)
    library.delete("lsf-lightbar")
    assert library.get(preset.id) is None and library.get(copy.id) is not None
    assert ComponentLibrary(tmp_path / "lib").ensure_builtins() == 0  # supprimé : pas recréé
    session.save()
    reopened = ProjectSession.open(session.file_path)  # le projet garde sa copie
    meshes = [n for n in reopened.scene.subtree(root) if n.kind is NodeKind.MESH]
    assert meshes and all(reopened.geometry_for(n) is not None for n in meshes)


def test_library_import_file(tmp_path, sample_obj):
    library = ComponentLibrary(tmp_path / "lib")
    component = library.import_file(sample_obj, "Pièce importée", "carrosserie", author="Test", license="CC0")
    assert component.triangles > 0 and component.dimensions[0] > 0
    assert library.preview_mesh(component).triangle_count == component.triangles


# 11. Modification de matériau ----------------------------------------------------------


def test_material_presets_and_extended_fields(car):
    session, editor, body, _ = car
    material_id = editor.apply_material_preset([body], "chrome")
    material = session.scene.materials[material_id]
    assert material.metallic == 1.0 and material.gta_shader == "vehicle_mesh" and material.preset == "chrome"
    editor.apply_material_preset([body], "paint_matte", material_id)
    assert material.roughness == pytest.approx(0.78)
    session.set_material_properties(material_id, {"uv_scale": (2.0, 2.0), "normal_strength": 0.5})
    assert material.uv_scale == (2.0, 2.0)
    session.stack.undo()
    assert material.uv_scale == (1.0, 1.0)


# 12. Points d'ancrage --------------------------------------------------------------------


def test_anchor_points(car):
    session, editor, body, _ = car
    anchor = editor.add_anchor(
        body, "Toit", "roof", (0, 0.5, 0), constraints="slide_longitudinal", metadata={"charge": 20}
    )
    node = session.scene.nodes[anchor]
    data = vehicle.anchor_data(node)
    assert node.kind is NodeKind.ANCHOR and data["type"] == "roof" and data["metadata"] == {"charge": 20}
    editor.update_anchor(anchor, type="light")
    session.rename(anchor, "Rampe")
    support = editor.add_mesh(shapes.box(), "Support")
    editor.attach_anchor(anchor, support)
    assert session.scene.nodes[anchor].parent_id == support
    assert vehicle.anchor_data(session.scene.nodes[anchor])["component_id"] == support
    assert vehicle.anchor_data(session.scene.nodes[anchor])["type"] == "light"


# 13. Undo / Redo, transactions, budget mémoire ------------------------------------------------


def test_undo_redo_transactions_and_memory_budget(car):
    session, editor, body, _ = car
    stack = session.stack
    stack.begin("Plusieurs opérations")
    editor.edit(body, lambda m: editmesh.translate_elements(m, "vertex", [0], (0, 0.2, 0)), "A")
    editor.edit(body, lambda m: editmesh.translate_elements(m, "vertex", [1], (0, 0.2, 0)), "B")
    stack.commit()
    assert stack.history()[-1] == ("Plusieurs opérations", True)
    stack.undo()
    assert session.scene.nodes[body].mesh_key in session.scene.meshes
    stack.redo()
    stack.memory_budget = 1  # au-delà du budget : les étapes anciennes sont oubliées
    editor.edit(body, lambda m: editmesh.translate_elements(m, "vertex", [2], (0, 0.2, 0)), "C")
    assert stack.done_count() == 1 and stack.trimmed >= 1
    session.prune_geometry()
    assert len(session.scene.meshes) <= 7  # 5 pièces + avant / après de la dernière étape
    stack.go_to(0)
    assert stack.done_count() == 0


# 14-16. Sauvegarde, réouverture, hiérarchie -----------------------------------------------


def test_save_reopen_preserves_everything(car):
    session, editor, body, wheels = car
    group = session.group(list(wheels.values()), "Roues")
    editor.edit(body, lambda m: editmesh.extrude_faces(m, [4, 5], 0.2), "Extrusion")
    anchor = editor.add_anchor(body, "Toit", "roof", (0, 0.5, 0))
    set_id, variant = editor.create_variant(wheels["Roue avant gauche"])
    editor.set_active_variant(set_id, variant)
    material = editor.apply_material_preset([body], "leather")
    axes = editor.axes
    axes.mirror_origin = 0.01
    editor.set_axes(axes)
    triangles = editor.mesh_of(body).triangle_count
    session.save()
    reopened = ProjectSession.open(session.file_path)
    scene = reopened.scene
    assert reopened.geometry_for(scene.nodes[body]).triangle_count == triangles
    assert scene.nodes[anchor].kind is NodeKind.ANCHOR and scene.nodes[anchor].parent_id == body
    assert vehicle.is_variant_set(scene.nodes[set_id]) and vehicle.active_variant(scene, set_id) == variant
    assert scene.nodes[wheels["Roue avant gauche"]].parent_id == set_id
    assert scene.nodes[set_id].parent_id == group
    assert scene.materials[material].preset == "leather"
    assert reopened.project.editor["mirror_origin"] == pytest.approx(0.01)
    assert not reopened.dirty


# 17. Opérations invalides ----------------------------------------------------------------


def test_invalid_operations_are_rejected_without_change(car):
    session, editor, body, wheels = car
    mesh = editor.mesh_of(body)
    with pytest.raises(EditError):
        editor.edit(body, lambda m: editmesh.extrude_faces(m, [], 0.1), "Rien")
    with pytest.raises(EditError):
        editor.edit(body, lambda m: editmesh.delete_faces(m, range(m.triangle_count)), "Tout")
    with pytest.raises(EditError):
        editmesh.inset_faces(mesh, [0], 1.5)
    with pytest.raises(EditError):
        editor.set_track(-1)
    session.set_locked([body], True)
    with pytest.raises(EditError):
        editor.edit(body, editmesh.recalculate_normals, "Verrouillé")
    with pytest.raises(EditError):
        editor.set_active_variant(body, wheels["Roue avant gauche"])
    assert editor.mesh_of(body) is mesh and session.stack.done_count() == 1  # seul le verrouillage


# Roues, habitacle, pivot, compatibilité ----------------------------------------------------


def test_wheel_editor(car):
    session, editor, _, wheels = car
    report = editor.wheels()
    assert len(report.wheels) == 4 and not report.messages
    sides = {w.name: (w.side, w.axle) for w in report.wheels}
    assert sides["Roue avant gauche"] == ("gauche", "avant")
    assert sides["Roue arrière droite"] == ("droite", "arrière")
    assert report.track == pytest.approx(1.6, abs=1e-4)
    editor.set_track(1.8)
    centers = [w.center[0] for w in editor.wheels().wheels]
    assert max(centers) == pytest.approx(0.9, abs=1e-4) and min(centers) == pytest.approx(-0.9, abs=1e-4)
    editor.set_wheelbase(3.0)
    assert editor.wheels().wheelbase == pytest.approx(3.0, abs=1e-4)
    editor.move_world({wheels["Roue avant droite"]: np.array([0, 0.1, 0])})
    editor.align_wheel_heights()
    assert np.ptp([w.center[1] for w in editor.wheels().wheels]) < 1e-5
    editor.mirror_wheel_position(wheels["Roue avant gauche"], wheels["Roue avant droite"])
    session.project.vehicle_type = VehicleType.MOTORCYCLE  # profil moto : 2 roues attendues
    assert any("Moto" in m for m in editor.wheels().messages)


def test_interior_configurations_and_pivot(car):
    session, editor, _, wheels = car
    seat = editor.add_mesh(shapes.seat(), "Siège conducteur")
    assert [n.id for n in vehicle.interior_nodes(session.scene)] == [seat]
    config = editor.create_interior_configurations(("civil", "police", "ems", "command"))
    children = session.scene.children(config)
    assert [c.extra["interior_configuration"] for c in children] == ["civil", "police", "ems", "command"]
    assert vehicle.active_variant(session.scene, config) == children[0].id
    editor.set_active_variant(config, children[1].id)
    assert vehicle.active_variant(session.scene, config) == children[1].id
    wheel = wheels["Roue arrière gauche"]
    before = world_center(session, wheel)
    editor.set_pivot(wheel, before + [0.1, 0, 0])
    assert np.allclose(session.scene.world_matrix(wheel)[:3, 3], before + [0.1, 0, 0], atol=1e-5)
    assert np.allclose(world_center(session, wheel), before, atol=1e-5)  # la pièce n'a pas bougé
    editor.center_pivot(wheel)
    assert np.allclose(session.scene.world_matrix(wheel)[:3, 3], before, atol=1e-5)


def test_fivem_compatibility_warnings(car, demo_addon_sample):
    from lsfcars.fivem.project_import import import_into_project
    from lsfcars.fivem.resource import analyze, stage_model
    from lsfcars.importers.yft_importer import YftImporter

    session, editor, _, wheels = car
    assert compat.action_risks(session, "delete", [wheels["Roue avant gauche"]])
    analysis = analyze(demo_addon_sample)
    model = analysis.model("lsfdemo")
    result = YftImporter().load(stage_model(analysis, model, analysis.temp_dir() / "stage"))
    root_id, _resource = import_into_project(session, analysis, model, result)
    analysis.close()
    bones = [n for n in session.scene.walk(root_id) if n.extra.get("gta", {}).get("role") == "bone"]
    wheel_bone = next(b for b in bones if b.name.startswith("wheel_"))
    assert compat.action_risks(session, "pivot", [wheel_bone.id])
    assert compat.action_risks(session, "hierarchy", [wheel_bone.id])
    before = compat.summary(compat.compatibility_report(session))
    editor.set_pivot(wheel_bone.id, session.scene.world_matrix(wheel_bone.id)[:3, 3] + [0, 0.1, 0])
    issues = compat.compatibility_report(session)
    assert issues[0].code == "disclaimer" and any(i.code == "pivot_moved" for i in issues)
    assert compat.summary(issues)["error"] > before["error"]


def test_restore_points(car):
    session, editor, body, _ = car
    session.save()
    point = restore_points.create(session.project, "Avant extrusion")
    editor.edit(body, lambda m: editmesh.extrude_faces(m, [4, 5], 0.5), "Extrusion")
    assert restore_points.list_points(session.project)[0].name == "Avant extrusion"
    restored = restore_points.load(point, session.project)
    other = ProjectSession.from_project(restored)
    assert other.geometry_for(other.scene.nodes[body]).triangle_count == 12
    assert restored.file_path == session.file_path


@pytest.mark.skipif(not bevel_available()[0], reason="Blender absent : biseau non testable")
def test_bevel_with_blender(car):
    _session, editor, body, _ = car
    mesh = editor.mesh_of(body)
    edge = sorted(editmesh.all_elements(mesh, "edge"))[0]
    result = editor.edit(body, lambda m: bevel_edges(m, [edge], 0.05, 2), "Biseau")
    assert editor.mesh_of(body).triangle_count > mesh.triangle_count and result.warnings


def test_compat_ignores_original_bone_scale(projects_dir):
    """Une échelle non uniforme présente dans les données GTA V d'origine n'est pas une alerte."""
    from lsfcars.scene.graph import SceneNode

    session = ProjectSession.create(projects_dir, "Os")
    root = SceneNode("modele", NodeKind.MODEL, extra={"gta": {"role": "root"}})
    bone = SceneNode(
        "chassis",
        NodeKind.GROUP,
        Transform(scale=[1.0, 2.0, 1.0]),
        extra={"gta": {"role": "bone", "bone_index": 0, "parent_index": -1, "scale": [1.0, 2.0, 1.0]}},
    )
    session.scene.add(root)
    session.scene.add(bone, root.id)
    assert not [i for i in compat.compatibility_report(session) if i.code == "scale"]
    bone.transform.scale = [1.0, 3.0, 1.0]
    assert [i for i in compat.compatibility_report(session) if i.code == "scale"]
