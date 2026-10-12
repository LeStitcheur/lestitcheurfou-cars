"""Génère le visuel de bannière et les captures d'écran de l'interface.

Usage :
    python scripts/capture_screens.py hero
        -> src/lsfcars/resources/brand/hero_vehicle.png (rendu du véhicule de test)
    python scripts/capture_screens.py screens LARGEUR HAUTEUR ECHELLE
        -> docs/screenshots/<largeur>x<hauteur>@<échelle>_<page>.png

Les captures utilisent un dossier de données temporaire (LSFCARS_HOME) : aucune donnée de
l'utilisateur n'est lue ni modifiée.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def hero() -> None:
    from PySide6.QtWidgets import QApplication

    from lsfcars.project.session import ProjectSession
    from lsfcars.render.renderer import gl_rgb
    from lsfcars.ui.design import apply_design, tokens
    from lsfcars.ui.gl_setup import configure_opengl
    from lsfcars.ui.viewport import Viewport3D

    configure_opengl()
    app = QApplication([])
    apply_design(app)
    session = ProjectSession.create(tempfile.mkdtemp(), "Hero")
    session.import_model(ROOT / "samples" / "vehicule_test.glb")
    session.selection.clear()
    # Visuel de la bannière : carrosserie au bleu principal du design system
    # (le modèle de test lui-même reste inchangé).
    for material in session.scene.materials.values():
        if material.name == "Peinture rouge LS":
            material.base_color = (*gl_rgb(tokens.ColorTokens.PRIMARY), 1.0)
    viewport = Viewport3D()
    viewport.toolbar.hide()
    viewport.stats_label.hide()
    viewport.resize(1400, 760)
    viewport.show()
    viewport.set_session(session)
    app.processEvents()
    viewport.camera.set_view(-38, 9)
    viewport.frame_bounds(session.world_bounds())
    viewport.camera.distance *= 0.78
    viewport.camera.target[1] += 0.15
    app.processEvents()
    target = ROOT / "src" / "lsfcars" / "resources" / "brand" / "hero_vehicle.png"
    viewport.grabFramebuffer().save(str(target))
    print(target.relative_to(ROOT))


def screens(width: int, height: int, scale: str) -> None:
    os.environ["QT_SCALE_FACTOR"] = scale
    os.environ["LSFCARS_HOME"] = tempfile.mkdtemp(prefix="lsfcars-captures-")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from lsfcars.ui.design import apply_design
    from lsfcars.ui.gl_setup import configure_opengl
    from lsfcars.ui.main_window import MainWindow

    configure_opengl()
    app = QApplication([])
    apply_design(app)
    factor = float(scale)
    window = MainWindow()
    window.resize(int(width / factor), int(height / factor))
    window.show()
    out = ROOT / "docs" / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    prefix = f"{width}x{height}@{scale}"
    shots = []

    def grab(name: str) -> None:
        for toast in window.notifications.active_toasts():
            toast.hide()
        path = out / f"{prefix}_{name}.png"
        window.grab().save(str(path))
        shots.append(path.name)

    def step_dashboard() -> None:
        window.open_sample_project()
        window.close_project()
        window.navigate("dashboard")
        window.dashboard.refresh()
        QTimer.singleShot(400, lambda: (grab("tableau_de_bord"), step_studio()))

    def step_studio() -> None:
        window.open_project(window.dashboard.grid.cards[0].summary.path)
        session = window.controller.session
        wheel = next(n for n in session.scene.walk() if n.name == "roue_avant_gauche")
        window.controller.select([wheel.id])
        window.studio.viewport.set_tool("translate")
        window.studio.properties.tabs.setCurrentIndex(1)
        QTimer.singleShot(500, lambda: (grab("vehicle_editor"), step_material()))

    def step_material() -> None:
        session = window.controller.session
        body = next(n for n in session.scene.walk() if n.name == "caisse")
        window.controller.select([body.id])
        window.studio.viewport.set_tool("rotate")
        window.studio.properties.tabs.setCurrentIndex(2)
        QTimer.singleShot(500, lambda: (grab("materiaux"), step_edit_mode()))

    def step_edit_mode() -> None:
        from lsfcars.editor import edit_state as modes
        from lsfcars.editor.vehicle import VehicleAxes
        from lsfcars.scene import editmesh

        ctl, studio = window.controller, window.studio
        ctl.editor.set_axes(VehicleAxes(forward_sign=1))  # modèle d'exemple : avant vers +Z
        session = ctl.session
        body = next(n for n in session.scene.walk() if n.name == "caisse")
        ctl.select([body.id])
        studio.viewport.set_tool("translate")
        studio.set_mode(modes.EDIT)
        mesh = ctl.edit_mesh()
        top = int(editmesh.face_normals(mesh.positions, mesh.indices)[:, 1].argmax())
        ctl.edit.set_element(editmesh.FACE, mesh)
        ctl.edit.select(editmesh.coplanar_faces(mesh, top, 20.0))
        studio.right.setCurrentWidget(studio.right.widget(1))
        QTimer.singleShot(500, lambda: (grab("mode_edition"), step_bodywork()))

    def step_bodywork() -> None:
        from lsfcars.editor import edit_state as modes

        ctl, studio = window.controller, window.studio
        studio.set_mode(modes.OBJECT)
        studio.set_workspace("bodywork")
        spoiler = studio.bodywork.create("lsf-spoiler", "rear")
        ctl.select([spoiler])
        studio.left.setCurrentWidget(studio.library)
        studio.library.category.select_data("spoilers")
        QTimer.singleShot(600, lambda: (grab("bodywork_bibliotheque"), step_wheels()))

    def step_wheels() -> None:
        studio = window.studio
        studio.set_workspace("wheels")
        studio.wheels.table.selectRow(2)
        studio.wheels._pick(2, 0)
        studio.left.setCurrentWidget(studio.explorer)
        studio.bottom.setCurrentWidget(studio.compat)
        studio.compat.refresh()
        QTimer.singleShot(500, lambda: (grab("wheel_editor"), step_interior()))

    def step_interior() -> None:
        ctl, studio = window.controller, window.studio
        session = ctl.session
        body = next(n for n in session.scene.walk() if n.name == "caisse")
        ctl.select([body.id])
        studio.anchors.name.setText("Rampe de toit")
        studio.anchors.type.select_data("roof")
        studio.anchors.create()
        studio.set_workspace("interior")
        studio.interior._create_configs()
        studio.interior.hide_body.setChecked(True)
        studio.bottom.setCurrentWidget(studio.history)
        studio.history.refresh()
        QTimer.singleShot(500, lambda: (grab("interior_ancrages"), step_emergency()))

    def step_emergency() -> None:
        from lsfcars.emergency.equipment import EquipmentLibrary

        studio_page = window.studio
        studio_page.interior.hide_body.setChecked(False)
        studio_page.set_workspace("editor")
        page = window.emergency
        library = EquipmentLibrary()
        library.ensure_builtins()
        page.set_library(library)
        window.navigate("emergency")
        studio = page.studio
        studio.create_variant("Berline LSPD", "lspd")
        studio.add_equipment("lsf-pol-lightbar", "roof")
        studio.add_equipment("lsf-pol-grille", "grille")
        studio.add_equipment_pair("lsf-pol-mirror", "mirror_l")
        studio.add_equipment("lsf-pol-bumper", "bumper_rear")
        studio.apply_interior_preset("police")
        page.refresh()
        page.left.setCurrentWidget(page.equipment_panel)
        page.equipment_panel.select_component("lsf-pol-lightbar")
        page.bottom.setCurrentWidget(page.timeline)
        page.set_playing(True)
        page._timer.stop()
        page.time_ms = 0
        page.advance(150)
        QTimer.singleShot(600, lambda: (grab("emergency_studio"), step_emergency_lighting()))

    def step_emergency_lighting() -> None:
        page = window.emergency
        studio = page.studio
        studio.create_variant("Berline EMS", "ems")
        studio.add_equipment("lsf-ems-lightbar", "roof")
        studio.add_equipment("lsf-ems-flasher-pair", "grille")
        page.refresh()
        page.right.setCurrentIndex(1)
        page.lighting.list.item(0).setSelected(True)
        page.left.setCurrentIndex(0)
        page.advance(420)
        QTimer.singleShot(600, lambda: (grab("emergency_eclairage"), step_emergency_config()))

    def step_emergency_config() -> None:
        page = window.emergency
        page.set_playing(False)
        page.right.setCurrentIndex(2)
        page.bottom.setCurrentWidget(page.diagnostics)
        page.diagnostics.refresh()
        page.configuration.refresh_lore()
        QTimer.singleShot(500, lambda: (grab("emergency_configurations"), step_import()))

    def step_import() -> None:
        window.navigate("import")
        page = window.import_page
        page.analysis_finished.connect(lambda _ok: QTimer.singleShot(300, step_import_preview))
        page.analyze(ROOT / "samples" / "fivem" / "lsfdemo")

    def step_import_preview() -> None:
        page = window.import_page
        page.show_file("stream/lsfdemo.yft")
        page.preview_finished.connect(lambda _ok: QTimer.singleShot(500, step_import_views))
        page.preview_model("lsfdemo")

    def step_import_views() -> None:
        page = window.import_page
        page.select_parts(["door_dside_f"])
        page.right.setCurrentWidget(page.vehicle)
        QTimer.singleShot(400, lambda: (grab("import_studio"), step_exploded()))

    def step_exploded() -> None:
        page = window.import_page
        page.select_parts([])
        page.set_explode(65)
        page.right.setCurrentWidget(page.textures)
        page.textures.list.setCurrentRow(2)
        QTimer.singleShot(400, lambda: (grab("vue_eclatee_textures"), step_metadata()))

    def step_metadata() -> None:
        page = window.import_page
        page.reset_view()
        page.set_mode("filaire")
        page.right.setCurrentWidget(page.metadata)
        page.metadata.select_path("data/handling.meta")
        page.bottom.setCurrentIndex(0)
        QTimer.singleShot(400, lambda: (grab("metadonnees_filaire"), step_livery()))

    def step_livery() -> None:
        from lsfcars.livery.raster import BrushSettings
        from lsfcars.project.session import ProjectSession

        session = ProjectSession.create(tempfile.mkdtemp(prefix="lsfcars-livree-"), "Démo - Livrée")
        session.import_model(ROOT / "samples" / "vehicule_livree.glb")
        session.selection.clear()
        window.controller.set_session(session)
        page = window.livery
        page.ensure_logos()
        window.navigate("liveries")
        page.create_document(size=1024, template="lspd", unit="1-ADAM-12", name="LSPD Patrol")
        studio = page.studio
        paint = studio.require().active_variant.layers[0].id
        studio.begin_stroke(paint, "#38BDF8", BrushSettings(size=16, hardness=0.9), symmetry=True, mode="3d")
        for z in [1.9 - i * 0.12 for i in range(26)]:  # filet bleu électrique peint en 3D, symétrique
            studio.stroke_3d([-3.0, 0.38 + 0.02 * abs(z), z], [1.0, 0.0, 0.0])
        studio.end_stroke()
        page.set_view_mode("split")
        page.views.setSizes([620, 380])
        page.viewport.camera.set_view(-32, 14)
        page.viewport.frame_bounds(session.world_bounds())
        page.viewport.camera.distance *= 0.8
        page.refresh()
        page.right.setCurrentIndex(0)
        page.left.setCurrentIndex(0)
        page.set_tool("brush")
        QTimer.singleShot(600, lambda: (page.canvas.fit(), QTimer.singleShot(300, step_livery_capture)))

    def step_livery_capture() -> None:
        grab("livery_studio")
        step_livery_paint()

    def step_livery_paint() -> None:
        page = window.livery
        page.set_view_mode("3d")
        page.right.setCurrentIndex(2)
        viewport = page.viewport
        surface = page.studio.surface()
        w, h = viewport.width(), viewport.height()
        spots = [(x * w / 10, y * h / 10) for y in range(3, 8) for x in range(3, 8)]
        hit = next((p for p in spots if surface.raycast(*viewport.screen_ray(*p)) is not None), None)
        if hit is not None:
            page.tools.size.setValue(60)
            page.hover(*hit)
        QTimer.singleShot(500, lambda: (grab("livery_peinture_3d"), step_livery_uv()))

    def step_livery_uv() -> None:
        page = window.livery
        page._hover = None
        page.set_view_mode("uv")
        page.canvas.show_seams = True
        page.uv_panel.show_seams.setChecked(True)
        studio = page.studio
        text = next(layer for layer in studio.require().active_variant.walk() if layer.kind == "text")
        page.select_layer(text.id)
        page.set_tool("move")
        page.right.setCurrentIndex(1)
        page.left.setCurrentIndex(2)
        page.bottom.setCurrentWidget(page.uv_panel)
        page.uv_panel.refresh()
        QTimer.singleShot(400, lambda: (page.canvas.fit(), QTimer.singleShot(300, step_livery_uv_capture)))

    def step_livery_uv_capture() -> None:
        grab("livery_uv_calques")
        step_livery_variants()

    def step_livery_variants() -> None:
        page = window.livery
        studio = page.studio
        patrol = studio.require().active
        studio.create_variant("EMS Rescue", "ems", "M-7")
        page.set_view_mode("split")
        page.canvas.show_seams = False
        page.refresh()
        page.right.setCurrentIndex(4)
        page.variants.compare_with.select_data(patrol)
        page.variants.compare()
        page.left.setCurrentIndex(3)
        page.bottom.setCurrentWidget(page.diagnostics)
        page.diagnostics.refresh()
        QTimer.singleShot(
            600, lambda: (page.canvas.fit(), QTimer.singleShot(300, step_livery_variants_capture))
        )

    def step_livery_variants_capture() -> None:
        grab("livery_variantes")
        step_ai()

    def step_ai() -> None:
        from lsfcars.ai.engines.base import JobContext

        window.navigate("ai")
        page = window.ai
        page.wait_idle(120000)
        page.manager.detect_all()  # résultat réel de la machine de capture
        page.after_detection()
        page.import_references(sorted((ROOT / "samples" / "references").glob("demo_*.png")))
        creator = page.creator
        creator.analyze(known_length=4.4)
        outcome = creator.generation_job("lsf-silhouette", "balanced")(JobContext())
        record_id = creator.apply_generation(outcome)
        root = creator.record(record_id)["root_id"]
        session = window.controller.session
        for other in [n.id for n in session.scene.roots() if n.id != root]:
            session.set_visible([other], False)
        page.last_root = root
        node = creator.mesh_nodes([root])[0]
        textures = creator.texture_job(node.id, "projection", 1024)(JobContext())
        creator.apply_textures(textures)
        page.texture_outcome = textures
        page.textures.show_outcome(textures)
        page.generation.result.setText(
            f"Modèle généré par LSF Silhouette en {outcome.duration_s:.1f} s "
            f"({outcome.import_result.triangle_count} triangles)."
        )
        page.set_view_mode("split")
        page.left.setCurrentIndex(0)
        page.right.setCurrentIndex(0)
        page.refresh()
        page.references.list.setCurrentRow(3)
        session.selection.clear()  # texture lisible (pas de teinte de sélection)
        page.viewport.camera.set_view(-35, 14)
        page.frame_model()
        QTimer.singleShot(700, step_ai_capture)

    def step_ai_capture() -> None:
        grab("ai_creator")
        page = window.ai
        page.right.setCurrentIndex(1)
        page.mesh.analyze()
        page.left.setCurrentIndex(1)
        page.analysis.refresh()
        page.bottom.setCurrentWidget(page.jobs_panel)
        QTimer.singleShot(500, lambda: (grab("ai_maillage"), step_ai_engines()))

    def step_ai_engines() -> None:
        page = window.ai
        page.creator.generate_proposals()
        page.creator.select_proposal(1)
        page.left.setCurrentIndex(2)
        page.right.setCurrentIndex(3)
        page.bottom.setCurrentWidget(page.hardware)
        page.v_split.setSizes([620, 330])
        page.refresh()
        page.history.list.setCurrentRow(0)
        QTimer.singleShot(500, lambda: (grab("ai_moteurs"), finish()))

    def finish() -> None:
        session = window.controller.session
        if session is not None:
            session.stack.mark_clean()
            session._meta_dirty = False
        print("\n".join(shots))
        window.close()
        app.quit()

    QTimer.singleShot(600, step_dashboard)
    app.exec()


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "hero":
        hero()
    elif len(sys.argv) == 5 and sys.argv[1] == "screens":
        screens(int(sys.argv[2]), int(sys.argv[3]), sys.argv[4])
    else:
        raise SystemExit(__doc__)
