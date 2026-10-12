"""Point d'entrée de l'application LeStitcheurFou Cars."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING

from lsfcars import APP_ID, APP_NAME, ORG_NAME, __version__
from lsfcars.core import diagnostics
from lsfcars.core.logging_setup import get_logger, install_excepthook, setup_logging
from lsfcars.core.paths import resources_dir, samples_dir

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

    from lsfcars.ui.main_window import MainWindow

EXIT_SMOKE_GL_FAILED = 3
EXIT_SMOKE_FIVEM_FAILED = 4
EXIT_SMOKE_EDITOR_FAILED = 5
EXIT_SMOKE_EMERGENCY_FAILED = 6
EXIT_SMOKE_LIVERY_FAILED = 7
EXIT_SMOKE_AI_FAILED = 8
EXIT_SMOKE_LORE_FAILED = 9


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=APP_ID, description=APP_NAME)
    parser.add_argument("project", nargs="?", help="Projet .lsfc à ouvrir au démarrage")
    parser.add_argument(
        "--software-gl",
        action="store_true",
        help="Forcer le rendu OpenGL logiciel (pilote graphique défaillant)",
    )
    parser.add_argument("--debug", action="store_true", help="Journalisation détaillée")
    parser.add_argument(
        "--smoke-test",
        type=int,
        metavar="MS",
        default=None,
        help="Démarre, rend le véhicule d'exemple puis quitte après MS millisecondes",
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    args, _unknown = parser.parse_known_args(argv)  # ignore les arguments propres à Qt
    return args


def release_qt_caches() -> None:
    """Objets Qt en cache (icônes, polices, logos) libérés avant la destruction de l'application."""
    from lsfcars.livery import render2d
    from lsfcars.ui.design import fonts, icons

    icons.clear_caches()
    fonts.clear_caches()
    render2d.clear_caches()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(logging.DEBUG if args.debug else logging.INFO)
    install_excepthook()
    log = get_logger("app")
    log.info("Démarrage de %s %s (Python %s)", APP_NAME, __version__, sys.version.split()[0])

    from lsfcars.ui.gl_setup import configure_opengl
    from lsfcars.ui.settings import AppSettings

    settings = AppSettings()
    configure_opengl(software=args.software_gl or settings.software_gl)
    if settings.blender_path:
        from lsfcars.importers.fbx_blender import set_blender_path

        set_blender_path(settings.blender_path)

    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.aboutToQuit.connect(release_qt_caches)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(ORG_NAME)
    icon_path = resources_dir() / "icon.png"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    from lsfcars.ui.design import apply_design
    from lsfcars.ui.main_window import MainWindow

    apply_design(app, compact=settings.compact)
    window = MainWindow(settings)
    window.show()
    if args.project:
        window.open_project(args.project)
    elif args.smoke_test is None:
        QTimer.singleShot(400, window.check_recovery)

    if args.smoke_test is not None:
        return _run_smoke_test(app, window, args.smoke_test)
    return app.exec()


def _run_smoke_test(app: QApplication, window: MainWindow, delay_ms: int) -> int:
    """Vérification de démarrage (CI, exécutable) : rendu du véhicule d'exemple puis sortie.

    Code de retour 0 si le rendu OpenGL a fonctionné, ``EXIT_SMOKE_GL_FAILED`` sinon,
    ``EXIT_SMOKE_FIVEM_FAILED`` si l'addon de démonstration n'a pas pu être analysé et décodé,
    ``EXIT_SMOKE_EDITOR_FAILED`` si le Vehicle Editor (édition, bibliothèque, sauvegarde) échoue,
    ``EXIT_SMOKE_EMERGENCY_FAILED`` si l'Emergency Studio (variante, équipements, motif) échoue,
    ``EXIT_SMOKE_LIVERY_FAILED`` si le Livery Studio (peinture 3D, calques, export) échoue,
    ``EXIT_SMOKE_AI_FAILED`` si AI Vehicle Creator (analyse, génération locale, textures) échoue,
    ``EXIT_SMOKE_LORE_FAILED`` si le Lore Friendly Engine (analyse, propositions, variante) échoue.
    Le rendu inclut les superpositions du mode Édition et d'un point d'ancrage.
    """
    import tempfile

    from PySide6.QtCore import QTimer

    from lsfcars.project.session import ProjectSession

    log = get_logger("smoke")
    session = ProjectSession.create(tempfile.mkdtemp(prefix="lsfcars-smoke-"), "Test")
    session.import_model(samples_dir() / "vehicule_test.glb")
    window.controller.set_session(session)
    window.navigate("studio")
    viewport = window.studio.viewport
    result = {"code": EXIT_SMOKE_GL_FAILED}
    editor_ok = _smoke_editor(window, session, log)
    emergency_ok = _smoke_emergency(log)
    livery_ok = _smoke_livery(log)
    ai_ok = _smoke_ai(log)
    lore_ok = _smoke_lore(log)

    def finish() -> None:
        image = viewport.grabFramebuffer()
        ok = viewport.gl_ready and not image.isNull()
        log.info(
            "Test de démarrage : OpenGL %s, image %dx%d, %d nœuds",
            "OK" if viewport.gl_ready else "INDISPONIBLE",
            image.width(),
            image.height(),
            len(session.scene),
        )
        log.info("\n%s", diagnostics.format_report())
        fivem_ok = _smoke_fivem(log)
        if not ok:
            result["code"] = EXIT_SMOKE_GL_FAILED
        elif not fivem_ok:
            result["code"] = EXIT_SMOKE_FIVEM_FAILED
        elif not editor_ok:
            result["code"] = EXIT_SMOKE_EDITOR_FAILED
        elif not emergency_ok:
            result["code"] = EXIT_SMOKE_EMERGENCY_FAILED
        elif not livery_ok:
            result["code"] = EXIT_SMOKE_LIVERY_FAILED
        elif not ai_ok:
            result["code"] = EXIT_SMOKE_AI_FAILED
        else:
            result["code"] = 0 if lore_ok else EXIT_SMOKE_LORE_FAILED
        session.stack.mark_clean()
        window.close()
        app.quit()

    QTimer.singleShot(max(delay_ms, 100), finish)
    app.exec()
    return result["code"]


def _smoke_editor(window: MainWindow, session, log) -> bool:  # type: ignore[no-untyped-def]
    """Vehicle Editor : extrusion en mode Édition, bibliothèque, ancrage, sauvegarde, réouverture."""
    import tempfile

    import numpy as np

    from lsfcars.editor import edit_state as modes
    from lsfcars.editor.library import ComponentLibrary
    from lsfcars.project.session import ProjectSession
    from lsfcars.scene import editmesh

    try:
        controller = window.controller
        body = next(n for n in session.scene.walk() if n.name == "caisse")
        controller.select([body.id])
        controller.set_mode(modes.EDIT)
        mesh = controller.edit_mesh()
        top = int(np.argmax(editmesh.face_normals(mesh.positions, mesh.indices)[:, 1]))
        controller.edit.set_element(editmesh.FACE, mesh)
        controller.edit.select(editmesh.coplanar_faces(mesh, top, 20.0))
        faces = set(controller.edit.selection)
        controller.run_edit("Extrusion", lambda m: editmesh.extrude_faces(m, faces, 0.03))
        library = ComponentLibrary(tempfile.mkdtemp(prefix="lsfcars-smoke-lib-"))
        created = library.ensure_builtins()
        editor = controller.editor
        spoiler = editor.insert_payload(library.payload(library.get("lsf-spoiler")), None, None, "Aileron")
        editor.add_anchor(body.id, "Toit", "roof", (0.0, 0.4, 0.0))
        triangles = session.geometry_for(session.scene.nodes[body.id]).triangle_count
        session.save()
        reopened = ProjectSession.open(session.file_path)
        ok = (
            triangles > mesh.triangle_count
            and spoiler in reopened.scene
            and reopened.geometry_for(reopened.scene.nodes[body.id]).triangle_count == triangles
            and any(True for _ in reopened.scene.anchor_nodes())
        )
        log.info(
            "Test de démarrage : Vehicle Editor %s (%d → %d triangles, %d composants de départ)",
            "OK" if ok else "ÉCHEC",
            mesh.triangle_count,
            triangles,
            created,
        )
        controller.select([body.id])  # rendu final : mode Édition et ancrage visibles
        return ok
    except Exception:  # noqa: BLE001 (un échec du test doit se traduire par un code de retour)
        log.exception("Test de démarrage : Vehicle Editor en échec")
        return False


def _smoke_emergency(log) -> bool:  # type: ignore[no-untyped-def]
    """Emergency Studio : variante LSPD, rampe, intérieur, motif déterministe, sauvegarde, réouverture."""
    import tempfile

    from lsfcars.editor.vehicle import VehicleAxes
    from lsfcars.emergency.equipment import EquipmentLibrary
    from lsfcars.emergency.studio import EmergencyStudio
    from lsfcars.project.session import ProjectSession

    try:
        session = ProjectSession.create(tempfile.mkdtemp(prefix="lsfcars-smoke-urg-"), "Urgence")
        session.import_model(samples_dir() / "vehicule_test.glb")
        library = EquipmentLibrary(tempfile.mkdtemp(prefix="lsfcars-smoke-equip-"))
        created = library.ensure_builtins()
        studio = EmergencyStudio(session, library)
        studio.editor.set_axes(VehicleAxes(forward_sign=1))
        variant_id = studio.create_variant("LSPD", "lspd")
        bar = studio.add_equipment("lsf-pol-lightbar", "roof")
        studio.apply_interior_preset("police")
        variant = studio.state().variant(variant_id)
        frames = [studio.lights_on(variant, t) for t in range(0, 1400, 70)]
        session.save()
        reopened = EmergencyStudio(ProjectSession.open(session.file_path), library)
        restored = reopened.state().variant(variant_id)
        ok = (
            len(bar.light_ids) > 0
            and len({frozenset(f) for f in frames}) > 1
            and frames == [studio.lights_on(variant, t) for t in range(0, 1400, 70)]
            and restored is not None
            and len(reopened.equipment_nodes(restored)) == len(studio.equipment_nodes(variant))
        )
        log.info(
            "Test de démarrage : Emergency Studio %s (%d équipements de départ, %d posés, %d feux)",
            "OK" if ok else "ÉCHEC",
            created,
            len(studio.equipment_nodes(variant)),
            len(variant.lights),
        )
        return ok
    except Exception:  # noqa: BLE001 (un échec du test doit se traduire par un code de retour)
        log.exception("Test de démarrage : Emergency Studio en échec")
        return False


def _smoke_livery(log) -> bool:  # type: ignore[no-untyped-def]
    """Livery Studio : document, modèle, peinture 3D, texte, sauvegarde, réouverture, export PNG vérifié."""
    import tempfile

    import numpy as np

    from lsfcars.livery.export import ExportOptions
    from lsfcars.livery.logos import LogoLibrary
    from lsfcars.livery.raster import BrushSettings
    from lsfcars.livery.studio import LiveryStudio
    from lsfcars.project.session import ProjectSession

    try:
        folder = tempfile.mkdtemp(prefix="lsfcars-smoke-livree-")
        session = ProjectSession.create(folder, "Livrée")
        session.import_model(samples_dir() / "vehicule_livree.glb")
        logos = LogoLibrary(f"{folder}/logos")
        logos.ensure_builtins()
        studio = LiveryStudio(session, logos)
        doc = studio.create_document(size=512, template="lspd", unit="27")
        paint = doc.active_variant.layers[0].id
        before = studio.composite()
        studio.begin_stroke(paint, "#38BDF8", BrushSettings(size=24), symmetry=True, mode="3d")
        hit = studio.stroke_3d([-3.0, 0.6, 0.2], [1.0, 0.0, 0.0])
        studio.end_stroke()
        studio.add_text("SMOKE", 256, 470, 40, "#FFFFFF")
        painted = int((np.abs(studio.composite().astype(int) - before.astype(int)).max(axis=-1) > 4).sum())
        expected = studio.composite()
        session.save()
        reopened = LiveryStudio(ProjectSession.open(session.file_path), logos)
        report = reopened.export(f"{folder}/export", ExportOptions("png", padding=0))
        webp = reopened.export(f"{folder}/export", ExportOptions("webp", 256, 256))
        dds = reopened.export(f"{folder}/export", ExportOptions("dds-dxt5", 256, 256))
        ok = (
            hit is not None
            and painted > 100
            and np.array_equal(reopened.composite(), expected)
            and report.verified
            and webp.verified
            and dds.verified
            and dds.mip_levels > 1
            and sum(1 for _ in reopened.require().active_variant.walk()) >= 10
        )
        log.info(
            "Test de démarrage : Livery Studio %s (%d pixels peints en 3D, export %s)",
            "OK" if ok else "ÉCHEC",
            painted,
            "vérifié" if report.verified else "non vérifié",
        )
        return ok
    except Exception:  # noqa: BLE001 (un échec du test doit se traduire par un code de retour)
        log.exception("Test de démarrage : Livery Studio en échec")
        return False


def _smoke_ai(log) -> bool:  # type: ignore[no-untyped-def]
    """AI Vehicle Creator : références livrées, analyse, génération locale réelle, textures, réouverture."""
    import tempfile
    from pathlib import Path

    from lsfcars.ai.creator import AIVehicleCreator
    from lsfcars.ai.engines.base import JobContext
    from lsfcars.ai.engines.triposr import worker_script
    from lsfcars.ai.manager import AIEngineManager
    from lsfcars.project.session import ProjectSession
    from lsfcars.ui.ai.engines_dialog import install_script

    try:
        folder = Path(tempfile.mkdtemp(prefix="lsfcars-smoke-ia-"))
        session = ProjectSession.create(folder, "IA")
        manager = AIEngineManager(folder / "data", folder / "engines")
        manager.detect_all(include_hardware=False)
        creator = AIVehicleCreator(session, manager)
        for path in sorted((samples_dir() / "references").glob("demo_*.png")):
            creator.add_reference(path)
        report = creator.analyze()
        outcome = creator.generation_job("lsf-silhouette", "eco")(JobContext())
        record = creator.record(creator.apply_generation(outcome))
        node = creator.mesh_nodes([record["root_id"]])[0]
        textures = creator.texture_job(node.id, "projection", 256)(JobContext())
        creator.apply_textures(textures)
        session.save()
        reopened = AIVehicleCreator(ProjectSession.open(session.file_path), manager)
        ok = (
            len(reopened.references()) == 5
            and report["fields"]["type"]["value"] == "sedan"
            and reopened.records()[0]["status"] == "succeeded"
            and outcome.import_result.triangle_count > 1000
            and textures.stats.get("projected_ratio", 0) > 0.3
            and worker_script().is_file()
            and install_script() is not None
        )
        manager.shutdown()
        log.info(
            "Test de démarrage : AI Vehicle Creator %s (%d triangles générés, moteurs : %s)",
            "OK" if ok else "ÉCHEC",
            outcome.import_result.triangle_count,
            ", ".join(f"{k}={v.status.value}" for k, v in manager.availability.items()),
        )
        return ok
    except Exception:  # noqa: BLE001 (un échec du test doit se traduire par un code de retour)
        log.exception("Test de démarrage : AI Vehicle Creator en échec")
        return False


def _smoke_lore(log) -> bool:  # type: ignore[no-untyped-def]
    """Lore Friendly Engine : analyse, propositions, aperçus, variante transformée, source intacte."""
    import tempfile
    from pathlib import Path

    import numpy as np

    from lsfcars.ai.engines.base import JobContext
    from lsfcars.lorefriendly.engine import SOURCE, LoreFriendlyEngine
    from lsfcars.project.session import ProjectSession

    try:
        folder = Path(tempfile.mkdtemp(prefix="lsfcars-smoke-lore-"))
        session = ProjectSession.create(folder, "Lore")
        root = session.import_model(samples_dir() / "vehicule_lore.glb")
        source = {
            n.id: session.geometry_for(n).positions.copy() for n in session.scene.subtree(root) if n.mesh_key
        }
        engine = LoreFriendlyEngine(session, None, folder / "data")
        design = engine.create_design(root)
        report = engine.analyze(design)
        engine.choose_brand(design, "pegassi")
        proposals = engine.generate_concepts(design, 2)
        engine.apply_previews(design, engine.preview_job(design)(JobContext()))
        variant = engine.apply_concept(design, proposals[0]["id"])
        comparison = engine.compare(design, SOURCE, variant)
        session.save()
        reopened = LoreFriendlyEngine(ProjectSession.open(session.file_path), None, folder / "data")
        intact = all(
            np.array_equal(source[k], session.geometry_for(session.scene.nodes[k]).positions) for k in source
        )
        ok = (
            intact
            and len(report["entries"]) > 20
            and comparison["deformed"] > 0
            and len(reopened.design()["variants"]) == 1
        )
        log.info(
            "Test de démarrage : Lore Friendly Engine %s (%d opérations, silhouette de profil %.3f, "
            "source intacte : %s)",
            "OK" if ok else "ÉCHEC",
            len(proposals[0]["plan"]),
            comparison["silhouettes"]["left"],
            "oui" if intact else "NON",
        )
        return ok
    except Exception:  # noqa: BLE001 (un échec du test doit se traduire par un code de retour)
        log.exception("Test de démarrage : Lore Friendly Engine en échec")
        return False


def _smoke_fivem(log) -> bool:  # type: ignore[no-untyped-def]
    """Analyse et décode l'addon de démonstration embarqué (lecteurs RSC7, YTD, YFT, META)."""
    from lsfcars.fivem.resource import Status, analyze, stage_model
    from lsfcars.importers.yft_importer import YftImporter

    folder = samples_dir() / "fivem" / "lsfdemo"
    if not folder.is_dir():
        log.error("Addon de démonstration absent : %s", folder)
        return False
    analysis = analyze(folder)
    try:
        model = analysis.model("lsfdemo")
        if analysis.overall is not Status.COMPATIBLE or model is None:
            log.error("Addon de démonstration : statut %s", analysis.overall.label)
            return False
        result = YftImporter().load(stage_model(analysis, model, analysis.temp_dir() / "smoke"))
    finally:
        analysis.close()
    log.info(
        "Test de démarrage : import FiveM OK (%d fichiers, %d triangles, %d textures)",
        len(analysis.files),
        result.triangle_count,
        len(analysis.textures),
    )
    return result.triangle_count > 0


if __name__ == "__main__":
    raise SystemExit(main())
