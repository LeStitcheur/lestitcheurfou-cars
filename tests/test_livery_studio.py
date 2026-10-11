"""Livery Studio Pro (logique) : les 20 scénarios obligatoires et les cas difficiles.

Véhicule d'essai : ``samples/vehicule_livree.glb`` (original) — côté droit sur un îlot UV
tourné de 180°, rétroviseurs sur la même zone UV, plusieurs matériaux, texture d'origine.
"""

from __future__ import annotations

import struct
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from lsfcars.livery import export, raster
from lsfcars.livery.blend import composite as blend_composite
from lsfcars.livery.logos import LogoLibrary
from lsfcars.livery.model import DOC_KEY, LiveryDocument
from lsfcars.livery.studio import LiveryError, LiveryStudio, LiveTexture
from lsfcars.livery.surface import LiverySurface
from lsfcars.livery.templates import BUILTIN_TEMPLATES
from lsfcars.project.session import ProjectSession


@pytest.fixture
def logos(tmp_path):
    library = LogoLibrary(tmp_path / "logos")
    library.ensure_builtins()
    return library


@pytest.fixture
def session(projects_dir, livery_glb, qapp):
    session = ProjectSession.create(projects_dir, "Livrée test")
    session.import_model(livery_glb)
    return session


@pytest.fixture
def studio(session, logos):
    studio = LiveryStudio(session, logos)
    studio.create_document(size=512)
    return studio


def body(session):
    return next(m.id for m in session.scene.materials.values() if m.name == "Carrosserie")


def paint_layer(studio):
    return studio.require().active_variant.layers[0].id


def changed(a: np.ndarray, b: np.ndarray, threshold: int = 4) -> np.ndarray:
    return np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=-1) > threshold


def _hit(surface, x, y, z):  # type: ignore[no-untyped-def]
    hit = surface.raycast([x, y, z], [-np.sign(x), 0.0, 0.0])
    return hit.tri, hit.bary


# --- 1 à 3 : véhicule, texture, UV ------------------------------------------------------------


def test_vehicle_with_uv_texture_and_uv_display(session, logos):
    studio = LiveryStudio(session, logos)
    candidates = studio.candidate_materials()
    assert candidates[0]["name"] == "Carrosserie" and candidates[0]["with_uv"] == 3  # 1. véhicule avec UV
    doc = studio.create_document(size=512)
    assert doc.targets == [body(session)] and doc.base_texture and doc.mode == "texture"
    base = (
        Image.open(session.project.project_dir / doc.base_texture)
        .convert("RGBA")
        .resize((512, 512), Image.LANCZOS)
    )
    composite = studio.composite()  # 2. texture chargée : la composition reproduit la texture d'origine
    assert np.abs(composite.astype(int) - np.array(base).astype(int)).max() <= 2
    surface = studio.surface()  # 3. affichage des UV
    report = surface.uv_report()
    assert len(surface.uv_segments()) > 100 and len(surface.seam_segments()) > 0
    assert report.islands >= 8 and report.coverage_ratio > 0.3
    assert session.live_textures[body(session)] is studio.live  # texture publiée aux viewports


def test_uv_inspection_overlaps_and_missing_texture(studio, session):
    report = studio.uv_report()
    assert report.overlapping_islands, "les rétroviseurs partagent la même zone UV"
    assert any("superposés" in w for w in report.warnings())
    material = session.scene.materials[body(session)]
    material.texture = "assets/textures/absente.png"  # texture manquante
    doc = studio.require()
    doc.base_texture = material.texture
    session.scene.documents[DOC_KEY] = doc.to_dict()
    studio.compositor.reset()
    studio.refresh()  # pas de plantage : fond blanc et avertissement
    messages = " ".join(text for _level, text in studio.diagnostics())
    assert "absente.png" in messages


# --- 4 à 6 : calque, peinture 2D, peinture 3D --------------------------------------------------


def test_layers_2d_paint_and_undo(studio, session):
    layer_id = studio.add_layer("raster", "Retouches")  # 4. création d'un calque
    assert studio.layer(layer_id).kind == "raster"
    before = studio.composite()
    studio.begin_stroke(layer_id, "#FF0000", raster.BrushSettings(size=20, hardness=1.0))
    for x in range(100, 220, 6):  # 5. peinture 2D
        studio.stroke_2d(x, 150)
    assert studio.end_stroke() > 0
    after = studio.composite()
    assert changed(before, after)[150, 100:220].all()
    assert tuple(after[150, 160, :3]) == (255, 0, 0)
    assert not changed(before, after)[300, 300]  # seule la zone peinte change
    session.stack.undo()
    assert not changed(before, studio.composite()).any()
    session.stack.redo()
    assert np.array_equal(studio.composite(), after)


def test_3d_paint_modifies_texture_across_seams_with_symmetry(studio):
    surface = studio.surface()
    before = studio.composite()
    studio.begin_stroke(
        paint_layer(studio), "#2563EB", raster.BrushSettings(size=24, hardness=0.6), symmetry=True, mode="3d"
    )
    hit = studio.stroke_3d([-3.0, 0.6, 0.2], [1.0, 0.0, 0.0])  # 6. peinture 3D sur le flanc gauche
    assert hit is not None and hit.point[0] < 0
    for z in np.linspace(0.2, -0.9, 12):
        studio.stroke_3d([-3.0, 0.6, z], [1.0, 0.0, 0.0])
    studio.end_stroke()
    diff = changed(before, studio.composite())
    islands = surface.islands()
    maps = surface.maps()
    touched = set(islands[maps.triangle[diff & (maps.triangle >= 0)]])
    left = surface.raycast([-3, 0.6, 0.2], [1, 0, 0])
    right = surface.raycast([3, 0.6, 0.2], [-1, 0, 0])
    assert islands[left.tri] in touched and islands[right.tri] in touched  # symétrie 3D (îlot tourné)
    x, y = surface.pixel_of(right.tri, right.bary)
    assert diff[int(y), int(x)]  # pixel symétrique réellement peint sur l'îlot droit
    # coutures : un coup de pinceau au bord du capot touche aussi le flanc (deux îlots)
    studio.begin_stroke(paint_layer(studio), "#22C55E", raster.BrushSettings(size=40), mode="3d")
    mark = studio.composite()
    assert studio.stroke_3d([-0.55, 3.0, -1.6], [-0.15, -1.0, 0.0]) is not None
    studio.end_stroke()
    seam = changed(mark, studio.composite())
    assert len(set(islands[maps.triangle[seam & (maps.triangle >= 0)]])) >= 2


# --- 7 à 11 : logo, texte, bande, symétrie, opacité -------------------------------------------


def test_logo_text_band_and_uv_aware_symmetry(studio):
    before = studio.composite()
    logo_ids = studio.add_logo_on_zone("lsf-star6-badge", "sides", 0.3, 0.75, 0.6)  # 7. logo
    assert len(logo_ids) == 2
    doc = studio.require()
    assert doc.provenance[0]["license"] and doc.provenance[0]["author"]
    left, right = (studio.layer(i) for i in logo_ids)
    assert abs(left.params["rotation"]) < 1e-6 and abs(abs(right.params["rotation"]) - 180) < 1e-6
    assert not left.params["flip_v"] and not right.params["flip_v"]  # îlot tourné, pas retourné
    text_id = studio.add_text("POLICE", 256, 400, 48, "#11151C", bold=True)  # 8. texte éditable
    with_text = studio.composite()
    assert changed(before, with_text)[380:420, 200:310].any()
    studio.update_params(text_id, text="EMS")
    assert not np.array_equal(with_text, studio.composite())
    band_id = studio.add_band(
        "Filet", zone="sides", center_height=0.45, width=0.05, color="#2563EB"
    )  # 9. bande
    surface = studio.surface()
    composite = studio.composite()
    for z in (-1.5, 0.0, 1.5):  # bande symétrique par construction (gauche / droite)
        lx, ly = surface.pixel_of(*_hit(surface, -3, 0.77, z))
        rx, ry = surface.pixel_of(*_hit(surface, 3, 0.77, z))
        assert (
            tuple(composite[int(ly), int(lx), :3]) == tuple(composite[int(ry), int(rx), :3]) == (37, 99, 235)
        )
    marking = studio.add_text_on_zone("SHERIFF", "left", 0.12, 0.1, 0.7, mirror_sides=False)[
        0
    ]  # 10. symétrie
    mirrored = studio.layer(studio.mirror_layer(marking))
    assert mirrored.params["anchor"]["side"] == "right" and "symétrie" in mirrored.name
    assert abs(abs(mirrored.params["rotation"]) - 180) < 1e-6 and not mirrored.params["flip_v"]
    roof = studio.layer(studio.add_text_on_zone("12", "roof", 0.4, mirror_sides=False)[0])
    assert roof.params["flip_v"]  # toit déplié en miroir : le texte est retourné pour se lire à l'endroit
    studio.set_layer(band_id, opacity=0.5)  # 11. opacité
    half = studio.composite()
    lx, ly = surface.pixel_of(*_hit(surface, -3, 0.77, 0.0))
    pixel = half[int(ly), int(lx), :3].astype(int)
    assert 37 < pixel[0] < 205 and 99 < pixel[1] < 210  # mélange 50 % bande / fond


def test_blend_modes_masks_groups_merge(studio):
    rgb = np.full((1, 1, 3), 0.5, np.float32)
    alpha = np.ones((1, 1), np.float32)
    src, src_a = np.full((1, 1, 3), 0.5, np.float32), np.ones((1, 1), np.float32)
    expected = {"normal": 0.5, "multiply": 0.25, "screen": 0.75, "overlay": 0.5, "add": 1.0}
    for mode, value in expected.items():
        dst = rgb.copy()
        blend_composite(dst, alpha.copy(), src, src_a, mode)
        assert abs(float(dst[0, 0, 0]) - value) < 1e-6, mode
    base = studio.composite()
    a = studio.add_shape("rect", [(10, 10), (110, 110)], "#FF0000")
    b = studio.add_shape("ellipse", [(60, 60), (160, 160)], "#0000FF")
    studio.set_layer(b, blend="multiply")
    assert tuple(studio.composite()[80, 80, :3]) == (0, 0, 0)  # rouge × bleu
    group = studio.group_layers([a, b], "Formes")
    assert studio.layer(group).children[1].id == b
    studio.add_mask(group)
    mask = studio.scene.images[studio.layer(group).mask]
    mask.array[:, :] = 0  # masque noir : groupe invisible
    mask.touch()
    studio.refresh([(0, 0, 512, 512)])
    assert np.array_equal(studio.composite()[80, 80], base[80, 80])
    studio.delete_mask(group)
    studio.ungroup(group)
    merged = studio.merge_down(b)
    assert studio.layer(merged).kind == "raster"
    assert tuple(studio.composite()[80, 80, :3]) == (0, 0, 0)  # résultat identique après fusion


def test_selection_fill_gradient_copy_paste(studio):
    layer = paint_layer(studio)
    studio.select_rect(50, 50, 150, 100)
    studio.fill(layer, 60, 60, "#22C55E", mode="selection")
    pixels = studio.scene.images[studio.layer(layer).image].array
    assert pixels[75, 100, 3] == 255 and pixels[120, 100, 3] == 0
    studio.begin_stroke(layer, "#EF4444", raster.BrushSettings(size=60))  # peinture limitée à la sélection
    studio.stroke_2d(100, 140)
    studio.end_stroke()
    assert pixels[140, 100, 3] == 0
    studio.clear_selection()
    studio.gradient(layer, (0, 300), (512, 300), "#000000", "#FFFFFF")
    assert pixels[300, 10, 0] < pixels[300, 500, 0]
    surface = studio.surface()
    island = surface.island_mask(*surface.pixel_of(*_hit(surface, -3, 0.6, 0)))
    assert island is not None and island.sum() > 1000
    studio.select_rect(50, 50, 150, 100)
    studio.copy(layer)
    pasted = studio.paste()
    assert studio.layer(pasted).kind == "image" and studio.scene.blobs[studio.layer(pasted).params["blob"]]


# --- 12 : annuler / rétablir ---------------------------------------------------------------------


def test_undo_redo_restores_identical_textures(studio, session):
    states = [studio.composite()]
    studio.add_band("Bande", zone="sides", center_height=0.5, width=0.1, color="#F59E0B")
    states.append(studio.composite())
    studio.add_text("27", 300, 450, 60, "#FFFFFF")
    states.append(studio.composite())
    studio.begin_stroke(paint_layer(studio), "#000000", raster.BrushSettings(size=30), mode="3d")
    studio.stroke_3d([-3, 0.5, 0.0], [1, 0, 0])
    studio.end_stroke()
    states.append(studio.composite())
    for expected in reversed(states[:-1]):
        session.stack.undo()
        assert np.array_equal(studio.composite(), expected)
    for expected in states[1:]:
        session.stack.redo()
        assert np.array_equal(studio.composite(), expected)


# --- 13 : variantes ---------------------------------------------------------------------------


def test_variants_create_duplicate_compare_delete(studio):
    first = studio.require().active
    patrol = studio.create_variant("LSPD Patrol", "lspd", "1-ADAM-12")
    doc = studio.require()
    assert doc.active == patrol and any(g.name == "Marquages" for g in doc.active_variant.layers)
    supervisor = studio.duplicate_variant(patrol, "LSPD Supervisor")
    assert studio.require().variant(supervisor).name == "LSPD Supervisor"
    studio.rename_variant(supervisor, "Supervisor")
    comparison = studio.compare_variants(patrol, first)
    assert comparison["changed_ratio"] > 0.01 and comparison["only_a"]
    assert studio.compare_variants(patrol, supervisor)["changed_ratio"] == 0.0
    studio.delete_variant(supervisor)
    assert [v.name for v in studio.require().variants] == ["Livrée 1", "LSPD Patrol"]
    first_before = studio.composite(first)
    shared = studio.add_text("COMMUN", 256, 300, 40, "#FFFFFF")  # élément commun aux livrées
    studio.set_shared(shared, True)
    assert any(layer.id == shared for layer in studio.require().shared_layers)
    assert changed(first_before, studio.composite(first))[280:320, 200:310].any()


def test_all_templates_apply(studio):
    for template in BUILTIN_TEMPLATES:
        variant = studio.create_variant(template.key, template.key, "42")
        layers = list(studio.require().variant(variant).walk())
        assert template.key == "custom" or len(layers) > 2, template.key
    texts = [
        layer.params.get("text")
        for v in studio.require().variants
        for layer in v.walk()
        if layer.kind == "text"
    ]
    assert texts and all("{unit}" not in (t or "") for t in texts)


# --- 14 à 17 : sauvegarde, fermeture, réouverture, calques conservés -------------------------------


def test_save_close_reopen_keeps_layers_editable(studio, session, logos):
    studio.create_variant("EMS Rescue", "ems", "M-7")
    studio.begin_stroke(paint_layer(studio), "#FFFFFF", raster.BrushSettings(size=50), mode="3d")
    studio.stroke_3d([-3, 0.5, -0.5], [1, 0, 0])
    studio.end_stroke()
    text_id = studio.add_text("RESCUE", 250, 470, 40, "#DC2626")
    expected_doc = studio.require().to_dict()
    expected = {v.id: studio.composite(v.id) for v in studio.require().variants}
    keys = studio.require().image_keys()
    session.save()  # 14. sauvegarde
    path = session.file_path
    session.close()  # 15. fermeture
    reopened = ProjectSession.open(path)  # 16. réouverture
    assert all(not reopened.scene.images[k].decoded for k in keys)  # décodage différé des calques
    again = LiveryStudio(reopened, logos)
    assert again.require().to_dict() == expected_doc  # 17. calques conservés, rien de fusionné
    for variant_id, array in expected.items():
        assert np.array_equal(again.composite(variant_id), array)
    again.update_params(text_id, text="SAMD")  # toujours éditable
    assert again.layer(text_id).params["text"] == "SAMD"


# --- 18 et 19 : export et vérification ------------------------------------------------------------


def test_export_png_and_verify_matches_viewport(studio, tmp_path):
    studio.apply_template("fire", unit="E-1")
    viewport_texture = studio.composite()
    assert np.array_equal(viewport_texture, studio.live.array)
    report = studio.export(tmp_path / "out", export.ExportOptions("png", padding=0))  # 18. export PNG
    exported = np.array(Image.open(report.path).convert("RGBA"))  # 19. vérification
    assert report.verified and report.max_difference == 0
    assert np.array_equal(exported, viewport_texture)  # identique à la texture du viewport
    big = studio.export(tmp_path / "big", export.ExportOptions("webp", 1024, 1024))
    assert big.verified and Image.open(big.path).size == (1024, 1024)
    dds = studio.export(tmp_path / "tex", export.ExportOptions("dds-dxt5", 256, 256))
    data = Path(dds.path).read_bytes()
    assert data[:4] == b"DDS " and data[84:88] == b"DXT5"
    assert struct.unpack_from("<I", data, 28)[0] == dds.mip_levels == 7 and dds.psnr > 30
    folder, reports = studio.prepare_ytd(tmp_path, export.ExportOptions("dds-dxt5", 256, 256))
    assert (folder / "manifest.json").is_file() and (folder / "LISEZMOI.txt").is_file()
    assert not list(folder.glob("*.ytd")) and reports[0].verified


# --- 20 : modèle sans UV -------------------------------------------------------------------------


def test_model_without_uv(projects_dir, sample_glb, logos, qapp):
    session = ProjectSession.create(projects_dir, "Sans UV")
    session.import_model(sample_glb)
    studio = LiveryStudio(session, logos)
    with pytest.raises(LiveryError, match="UV absentes"):
        studio.create_document()
    missing = studio.nodes_without_uv()
    assert missing and studio.document() is None
    assert studio.project_missing_uvs(missing) == len(missing)  # projection, après confirmation (interface)
    doc = studio.create_document(size=256)
    assert studio.surface(doc).triangle_count > 0
    session.stack.undo()  # document
    session.stack.undo()  # projection UV : annulable
    assert studio.nodes_without_uv(doc.targets)


# --- Cas difficiles -----------------------------------------------------------------------------


def test_multiple_materials_targets_and_shared_material(studio, session):
    tyres = next(m.id for m in session.scene.materials.values() if m.name == "Pneus")
    studio.set_document(targets=[body(session), tyres])
    surface = studio.surface()
    assert {"caisse", "roue_avant_gauche"} <= set(surface.node_names)
    messages = " ".join(text for _level, text in studio.diagnostics())
    assert "partagé" in messages  # carrosserie et rétroviseurs partagent le matériau
    studio.refresh()
    assert body(session) in session.live_textures and tyres in session.live_textures


def test_complex_geometry_paint_performance(qapp):
    import trimesh

    sphere = trimesh.creation.icosphere(subdivisions=4, radius=1.0)
    v = sphere.vertices
    uv = np.stack(
        [np.arctan2(v[:, 2], v[:, 0]) / (2 * np.pi) + 0.5, np.arccos(np.clip(v[:, 1], -1, 1)) / np.pi], axis=1
    )
    surface = LiverySurface(
        v[sphere.faces],
        uv[sphere.faces],
        np.zeros(len(sphere.faces), np.int32),
        ["s"],
        ["sphère"],
        1024,
        1024,
    )
    started = time.perf_counter()
    hit = surface.raycast([0, 0, -3], [0, 0, 1])
    patches = surface.brush_patches(hit.point, 0.15, 0.5, hit.normal)
    assert hit is not None and patches and time.perf_counter() - started < 2.0
    assert surface.triangle_count == 5120 and surface.uv_report().islands >= 1


def test_live_texture_partial_updates():
    live = LiveTexture(np.zeros((8, 8, 4), np.uint8))
    live.publish(None)
    version = live.version
    live.publish((0, 0, 2, 2))
    live.publish((4, 4, 6, 8))
    assert live.changes_since(version) == (0, 0, 6, 8)
    assert live.changes_since(live.version) is False
    assert live.changes_since(0) is True


def test_emergency_link_preserves_equipment(studio, session, tmp_path):
    from lsfcars.editor.vehicle import VehicleAxes
    from lsfcars.emergency.equipment import EquipmentLibrary
    from lsfcars.emergency.studio import EmergencyStudio

    library = EquipmentLibrary(tmp_path / "equipment")
    library.ensure_builtins()
    emergency = EmergencyStudio(session, library)
    emergency.editor.set_axes(VehicleAxes())
    variant_id = emergency.create_variant("LSPD", "lspd")
    emergency.add_equipment("lsf-pol-lightbar", "roof")
    equipment = len(emergency.equipment_nodes(emergency.state().variant(variant_id)))
    livery = studio.create_variant("LSPD Patrol", "lspd", "1-ADAM-12")
    studio.link_emergency(livery, variant_id)
    studio.add_text("UNIT", 200, 200, 40, "#FFFFFF")  # modification graphique
    state = emergency.state()
    assert len(emergency.equipment_nodes(state.variant(variant_id))) == equipment  # équipements intacts
    assert state.variant(variant_id).livery.livery_name == "LSPD Patrol"
    assert state.variant(variant_id).livery.unit_id == "1-ADAM-12"
    other = studio.create_variant("Civil")
    studio.activate_variant(other)
    assert studio.follow_emergency(variant_id) == livery and studio.require().active == livery


def test_user_template_logo_import_and_font_license(studio, logos, tmp_path):
    studio.add_text("MODÈLE", 256, 256, 50, "#FFFFFF")
    studio.add_logo("lsf-shield", 100, 100, 64)
    path = studio.save_template(tmp_path / "perso.json", "Perso")
    target = studio.create_variant("Copie")
    created = studio.apply_user_template(path, target)
    assert len(created) == len(studio.require().variants[0].layers)
    image = tmp_path / "logo.png"
    Image.new("RGBA", (32, 32), (255, 0, 0, 255)).save(image)
    entry = logos.import_file(image, "Mon logo", "personal", "Moi", "création", "")
    assert entry.license == "" and logos.get(entry.id) is not None
    studio.add_logo(entry.id, 200, 200, 64)
    report = studio.export(tmp_path / "check", export.ExportOptions("png", padding=0))
    assert any("licence" in w for w in report.warnings)  # licence manquante signalée
    with pytest.raises(LiveryError, match="licence"):
        studio.import_font(tmp_path / "police.ttf", "")
    assert LiveryDocument.from_dict(studio.require().to_dict()).version == 1
