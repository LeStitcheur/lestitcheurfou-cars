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
    ``EXIT_SMOKE_FIVEM_FAILED`` si l'addon de démonstration n'a pas pu être analysé et décodé.
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
        result["code"] = (0 if fivem_ok else EXIT_SMOKE_FIVEM_FAILED) if ok else EXIT_SMOKE_GL_FAILED
        session.stack.mark_clean()
        window.close()
        app.quit()

    QTimer.singleShot(max(delay_ms, 100), finish)
    app.exec()
    return result["code"]


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
