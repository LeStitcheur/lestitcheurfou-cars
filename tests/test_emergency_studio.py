"""Emergency Vehicle Studio (v0.5) : variantes, équipements, placement, feux, motifs, sirènes,
intérieurs, profils, adaptateurs, Lore Friendly, sauvegarde et annulation (sans interface).

Les 16 scénarios obligatoires du prompt 5 sont numérotés ; le véhicule de test est le modèle
d'exemple du dépôt (original) et les équipements sont les formes générées par le logiciel.
"""

from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from lsfcars.editor.vehicle import VehicleAxes
from lsfcars.emergency import adapters, model, sirens
from lsfcars.emergency.equipment import EquipmentLibrary
from lsfcars.emergency.model import PatternFrame, build_pattern
from lsfcars.emergency.studio import EmergencyStudio, EquipmentError
from lsfcars.project.session import ProjectSession
from lsfcars.scene.graph import NodeKind


@pytest.fixture(scope="module")
def library(tmp_path_factory):
    lib = EquipmentLibrary(tmp_path_factory.mktemp("equipment"))
    lib.ensure_builtins()
    return lib


@pytest.fixture
def studio(projects_dir, sample_glb, library):
    """1. Import d'un véhicule compatible (modèle d'exemple, avant vers +Z)."""
    session = ProjectSession.create(projects_dir, "Urgence")
    session.import_model(sample_glb)
    studio = EmergencyStudio(session, library)
    studio.editor.set_axes(VehicleAxes(forward_sign=1))
    session.stack.clear()
    session.stack.mark_clean()
    return studio


def center(session, node_id):
    bmin, bmax = session.world_bounds([node_id], only_visible=False)
    return (bmin + bmax) / 2, bmin, bmax


def test_library_contents_and_licenses(library):
    components = library.components()
    assert {"police", "ems", "fire"} <= {c.family for c in components} and len(components) >= 30
    assert all(c.license and c.provenance for c in components)
    lightbar = library.get("lsf-pol-lightbar")
    assert len(lightbar.emitters) == 8 and "moto_road" not in lightbar.compatible_profiles
    assert "sedan" not in library.get("lsf-ems-stretcher").compatible_profiles
    assert library.for_service("samd") and all(
        "lspd" not in c.services for c in library.for_service("samd") if c.services
    )


def test_lspd_variant_lightbar_roof_and_grille(studio):
    session = studio.session
    # 2. Variante LSPD
    variant_id = studio.create_variant("Berline LSPD", "lspd")
    variant = studio.variant(variant_id)
    assert variant.service == "lspd" and variant.profile == "sedan"
    assert session.scene.nodes[variant.root_id].extra["emergency_variant"] == variant_id
    # 3-4. Rampe lumineuse posée sur le toit
    bar = studio.add_equipment("lsf-pol-lightbar")
    assert not bar.warnings and len(bar.light_ids) == 8
    _vmin, vmax = studio.vehicle_bounds()
    _c, bmin, _bmax = center(session, bar.node_id)
    assert vmax[1] - 0.25 < bmin[1] < vmax[1] + 0.05  # repose sur le haut du véhicule
    assert studio.surface_hit([0, vmax[1] + 2, 0.0], [0, -1, 0]) is not None
    # 5. Feux secondaires (calandre) sur la face avant
    grille = studio.add_equipment("lsf-pol-grille")
    _c, _gmin, gmax = center(session, grille.node_id)
    assert gmax[2] == pytest.approx(vmax[2], abs=0.08)
    variant = studio.variant()
    kinds = {g.kind: g for g in variant.groups}
    assert set(grille.light_ids) <= set(kinds["front"].light_ids)
    assert {variant.light(i).color for i in grille.light_ids} == {"red", "blue"}  # couleurs LSPD


def test_groups_patterns_and_deterministic_preview(studio):
    studio.create_variant("LSPD", "lspd")
    bar = studio.add_equipment("lsf-pol-lightbar")
    variant = studio.variant()
    # 6. Groupe lumineux
    group_id = studio.create_group("Rampe gauche", "custom", bar.light_ids[:4])
    assert studio.variant().group(group_id).light_ids == bar.light_ids[:4]
    # 7. Motif
    kinds = {g.kind: g.id for g in variant.groups}
    pattern_id = studio.add_pattern("triple", [kinds["left"], kinds["right"]], 90)
    pattern = studio.variant().pattern(pattern_id)
    assert pattern.cycle_ms > 0 and studio.variant().active_pattern == pattern_id
    # 8. Prévisualisation déterministe
    variant = studio.variant()
    first = [studio.lights_on(variant, t) for t in range(0, pattern.cycle_ms, 15)]
    second = [studio.lights_on(variant, t) for t in range(0, pattern.cycle_ms, 15)]
    assert first == second and any(first) and not all(first)
    assert studio.lights_on(variant, 37) == studio.lights_on(variant, 37 + pattern.cycle_ms)
    assert studio.lights_on(variant, 100, speed=2.0) == studio.lights_on(variant, 200)
    frames = [PatternFrame(100, [kinds["left"]]), PatternFrame(100, []), PatternFrame(200, [kinds["right"]])]
    studio.update_pattern(pattern_id, frames, "Mon motif")
    assert studio.variant().pattern(pattern_id).cycle_ms == 400
    copy_id = studio.duplicate_pattern(pattern_id)
    preset = studio.save_pattern_preset(copy_id)
    assert preset["frames"][0]["kinds"] == ["left"]
    applied = studio.apply_pattern_preset(preset["name"])
    assert studio.variant().pattern(applied).frames[0].groups == [kinds["left"]]
    for preset_key in model.PATTERN_PRESETS:
        assert build_pattern(preset_key, ["a", "b", "c"], 80).cycle_ms > 0
    with pytest.raises(EquipmentError):
        studio.update_pattern(pattern_id, [PatternFrame(0, [])])
    _position, direction = studio.light_world(studio.variant().light(bar.light_ids[0]))
    assert np.linalg.norm(direction) == pytest.approx(1.0)


def test_interior_ems_variant_save_reopen_and_undo(studio):
    session = studio.session
    lspd = studio.create_variant("Berline LSPD", "lspd")
    studio.add_equipment("lsf-pol-lightbar")
    studio.add_equipment("lsf-pol-grille")
    # 9. Équipements intérieurs (configuration police)
    interior = studio.apply_interior_preset("police")
    assert len(interior) >= 4
    variant = studio.variant(lspd)
    inner = next(c for c in session.scene.children(variant.root_id) if c.extra.get("emergency_interior"))
    assert len(session.scene.children(inner.id)) == len(interior)
    assert studio.save_interior_preset("Ma console")["items"]
    # 10. Variante EMS
    ems = studio.create_variant("Berline EMS", "ems")
    studio.add_equipment("lsf-ems-lightbar")
    studio.add_siren_mode("Mode urgent", "priority", studio.variant(ems).active_pattern)
    studio.update_variant(
        ems, livery={"livery_name": "EMS blanc", "unit_id": "EMS-12", "callsign": "Medic 12"}
    )
    studio.update_variant(ems, metadata={"auteur": "test"})
    assert session.scene.nodes[studio.variant(lspd).root_id].visible is False  # une seule visible
    comparison = studio.compare_variants(lspd, ems)
    assert comparison["service"] == ("lspd", "ems") and comparison["equipment_only_first"]
    # 11-14. Sauvegarde, fermeture, réouverture, conservation des configurations
    snapshot = studio.state().to_dict()
    lspd_equipment = len(studio.equipment_nodes(studio.variant(lspd)))
    session.save()
    session.close()
    reopened = ProjectSession.open(session.file_path)
    again = EmergencyStudio(reopened, studio.library)
    assert again.state().to_dict() == snapshot
    ems_variant = again.variant(ems)
    assert ems_variant.livery.callsign == "Medic 12" and ems_variant.metadata == {"auteur": "test"}
    assert any(m.tone == "priority" for m in ems_variant.siren.modes)
    assert len(again.equipment_nodes(again.variant(lspd))) == lspd_equipment
    meshes = [n for n in reopened.scene.walk(again.variant(lspd).root_id) if n.kind is NodeKind.MESH]
    assert meshes and all(reopened.geometry_for(n) is not None for n in meshes)
    # 15. Annuler / rétablir
    count = len(studio.state().variants)
    for _ in range(5):  # métadonnées, livrée, mode de sirène, rampe EMS, création de la variante
        session.stack.undo()
    assert len(studio.state().variants) == count - 1
    assert session.scene.nodes[studio.variant(lspd).root_id].visible is True
    session.stack.redo()
    assert len(studio.state().variants) == count


def test_invalid_equipment_is_rejected(studio, tmp_path):
    # 16. Équipement invalide
    with pytest.raises(EquipmentError):
        studio.add_equipment("lsf-pol-lightbar")  # aucune variante
    studio.create_variant("LSPD", "lspd")
    with pytest.raises(EquipmentError):
        studio.add_equipment("composant-inexistant")
    broken_lib = EquipmentLibrary(tmp_path / "lib")
    broken_lib.ensure_builtins()
    shutil.rmtree(broken_lib.root / "meshes" / "lsf-pol-radio")  # géométrie disparue
    with pytest.raises(EquipmentError):
        EmergencyStudio(studio.session, broken_lib).add_equipment("lsf-pol-radio")
    stretcher = studio.add_equipment("lsf-ems-stretcher")  # brancard sur une berline : avertissement
    assert any("profil" in w for w in stretcher.warnings)
    with pytest.raises(EquipmentError):
        studio.add_light(None, "Feu", color="violet")
    assert studio.session.stack.done_count() == 2  # seules les opérations valides sont enregistrées


def test_variant_management_duplicate_delete_restore_materials(studio):
    session = studio.session
    lspd = studio.create_variant("SUV LSPD", "lspd", "suv")
    bar = studio.add_equipment("lsf-pol-lightbar")
    sheriff = studio.duplicate_variant(lspd, "SUV Sheriff")
    copy, original = studio.variant(sheriff), studio.variant(lspd)
    assert len(copy.lights) == len(original.lights) and copy.root_id != original.root_id
    assert not {x.id for x in copy.lights} & {x.id for x in original.lights}
    assert all(light.node_id in session.scene for light in copy.lights)
    studio.rename_variant(sheriff, "SUV BCSO")
    assert session.scene.nodes[copy.root_id].name == "SUV BCSO"
    body = next(n for n in session.scene.walk() if n.name == "caisse")
    base_material = body.material_id
    paint = session.create_material("Peinture BCSO")
    studio.activate_variant(sheriff)
    studio.set_material_override(sheriff, [body.id], paint.id)
    assert session.scene.nodes[body.id].material_id == paint.id  # matériau propre à la variante
    studio.activate_variant(lspd)
    assert session.scene.nodes[body.id].material_id == base_material  # base partagée intacte
    studio.delete_variant(sheriff)
    assert studio.state().variant(sheriff) is None and copy.root_id not in session.scene
    assert studio.restore_variant() == sheriff and copy.root_id in session.scene
    assert studio.state().active == sheriff and session.scene.nodes[body.id].material_id == paint.id
    studio.activate_variant(lspd)
    mirrored = studio.mirror_equipment([bar.node_id])
    assert mirrored and len(studio.variant(lspd).lights) == 16


def test_profiles_zones_pairs_snap_and_collisions(studio):
    session = studio.session
    studio.create_variant("LSPD", "lspd")
    pair = studio.add_equipment_pair("lsf-pol-mirror", "mirror_l")
    assert len(pair) == 2
    left, right = (center(session, r.node_id)[0] for r in pair)
    assert left[0] == pytest.approx(-right[0], abs=0.05)
    variant = studio.variant()
    assert {variant.light(pair[0].light_ids[0]).color, variant.light(pair[1].light_ids[0]).color} == {
        "red",
        "blue",
    }
    beacon = studio.add_equipment("lsf-pol-beacon", "roof")
    studio.rotate_step(beacon.node_id, 15)
    studio.snap(beacon.node_id, 0.05, 15)
    rotation = session.scene.nodes[beacon.node_id].transform.rotation
    assert all(abs(v / 15 - round(v / 15)) < 1e-6 for v in rotation)
    studio.move_to_zone(beacon.node_id, "rear_deck")
    assert center(session, beacon.node_id)[0][2] < 0  # arrière du véhicule (avant vers +Z)
    studio.add_equipment("lsf-pol-beacon", "rear_deck")
    assert any("chevauchent" in issue for issue in studio.collisions())
    point, normal = studio.zone_point(studio.state().profile("sedan").zone("roof"))
    studio.place_on_surface(beacon.node_id, point, normal)
    moto = model.PROFILES_BY_KEY["moto_road"]
    assert not moto.zones_for("pol_rampe") and moto.zones_for("pol_gyro")  # pas de rampe sur une moto
    key = studio.save_custom_profile("Quad", "Quad de patrouille", "moto_tt")
    assert studio.state().profile(key).label == "Quad de patrouille"
    assert all(profile.zones for profile in model.PROFILES)


def test_lights_sirens_lore_and_diagnostics(studio):
    studio.create_variant("SAMD", "samd")
    bar = studio.add_equipment("lsf-ems-lightbar")
    light_id = bar.light_ids[0]
    studio.update_light(light_id, color="white", intensity=2.5, range=20.0, angle=45.0, enabled=False)
    light = studio.variant().light(light_id)
    assert (light.color, light.intensity, light.angle, light.enabled) == ("white", 2.5, 45.0, False)
    assert light_id not in studio.lights_on(studio.variant(), 0)
    extra = studio.add_light(bar.node_id, "Feu ajouté", (0.1, 0.1, 0), "amber", "work")
    assert extra in {g.kind: g for g in studio.variant().groups}["work"].light_ids
    studio.remove_light(extra)
    assert studio.variant().light(extra) is None
    for tone in model.SIREN_TONES:
        assert sirens.tone_wav(tone, 0.5)[:4] == b"RIFF"
    assert np.array_equal(sirens.tone_samples("yelp", 0.3), sirens.tone_samples("yelp", 0.3))
    studio.update_variant(studio.variant().id, livery={"livery_name": "Ford Police Interceptor"})
    report = studio.lore_report()
    assert report[0][0] == "info" and any("ford" in message.lower() for _level, message in report)
    assert model.real_brand_hits("Vapid Stanier LSPD") == []
    assert studio.diagnostics()[0][1].startswith("1 équipement")


def test_export_adapters(studio, tmp_path):
    studio.create_variant("Berline LSPD", "lspd")
    studio.add_equipment("lsf-pol-lightbar")
    studio.add_equipment("lsf-pol-grille")
    context = adapters.ExportContext(studio, studio.variant(), "police_berline")
    for adapter in adapters.ADAPTERS:
        assert adapter.info.limits and (adapter.info.supported or not adapter.info.available)
    files = adapters.ADAPTERS_BY_KEY["lsf-json"].export(context, tmp_path)
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["format"] == "lsfcars-emergency" and len(data["variant"]["lights"]) == 10
    assert all(light["world_position"] for light in data["variant"]["lights"])
    carcols = adapters.ADAPTERS_BY_KEY["carcols"]
    xml_path, report = carcols.export(context, tmp_path)
    root = ET.fromstring(xml_path.read_text(encoding="utf-8").split("-->", 1)[1])
    items = root.find("sirens").findall("Item")
    assert len(items) == 10 and root.find("sequencerBpm").get("value") != "0"
    bits = int(items[0].find("flashiness/sequencer").get("value"))
    assert 0 < bits < 2**32 and items[0].find("color").get("value").startswith("0xFF")
    assert "siren1" in report.read_text(encoding="utf-8")
    assert adapters.sequencer_bits([True, False] * 16) == 0xAAAAAAAA
    vcf, _extras = adapters.ADAPTERS_BY_KEY["miss-els"].export(context, tmp_path)
    vcf_root = ET.fromstring(vcf.read_text(encoding="utf-8").split("-->", 1)[1])
    assert vcf_root.tag == "vcfroot" and vcf_root.find("EOVERRIDE/Extra01") is not None
    flashes = vcf_root.findall("PATTERN/PRIMARY/Flash")
    assert flashes and all(int(f.get("Duration")) > 0 for f in flashes)
    with pytest.raises(adapters.AdapterError) as error:
        adapters.ADAPTERS_BY_KEY["els-classic"].export(context, tmp_path)
    assert "spécification" in error.value.reasons[0]
    civil = studio.create_variant("Civil", "civil")
    with pytest.raises(adapters.AdapterError):
        carcols.export(adapters.ExportContext(studio, studio.variant(civil)), tmp_path)
