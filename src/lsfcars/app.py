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

    configure_opengl(software=args.software_gl)

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(ORG_NAME)
    icon_path = resources_dir() / "icon.png"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    from lsfcars.ui.main_window import MainWindow
    from lsfcars.ui.theme import apply_theme

    apply_theme(app)
    window = MainWindow()
    window.show()
    if args.project:
        window.open_project(args.project)

    if args.smoke_test is not None:
        return _run_smoke_test(app, window, args.smoke_test)
    return app.exec()


def _run_smoke_test(app: QApplication, window: MainWindow, delay_ms: int) -> int:
    """Vérification de démarrage (CI, exécutable) : rendu du véhicule d'exemple puis sortie.

    Code de retour 0 si le rendu OpenGL a fonctionné, ``EXIT_SMOKE_GL_FAILED`` sinon.
    """
    from PySide6.QtCore import QTimer

    from lsfcars.scene.loader import load_meshes
    from lsfcars.scene.mesh import combined_bounds
    from lsfcars.ui.main_window import MODE_3D

    log = get_logger("smoke")
    window.set_mode(MODE_3D)
    meshes = load_meshes(samples_dir() / "vehicule_test.glb")
    window.viewport.set_object("smoke-test", meshes)
    window.viewport.frame_bounds(combined_bounds(meshes))
    result = {"code": EXIT_SMOKE_GL_FAILED}

    def finish() -> None:
        image = window.viewport.grabFramebuffer()
        ok = window.viewport.gl_ready and not image.isNull()
        log.info(
            "Test de démarrage : OpenGL %s, image %dx%d",
            "OK" if window.viewport.gl_ready else "INDISPONIBLE",
            image.width(),
            image.height(),
        )
        log.info("\n%s", diagnostics.format_report())
        result["code"] = 0 if ok else EXIT_SMOKE_GL_FAILED
        window.viewport.remove_object("smoke-test")
        window.close()
        app.quit()

    QTimer.singleShot(max(delay_ms, 100), finish)
    app.exec()
    return result["code"]


if __name__ == "__main__":
    raise SystemExit(main())
