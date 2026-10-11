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
    from lsfcars.ui.design import apply_design
    from lsfcars.ui.gl_setup import configure_opengl
    from lsfcars.ui.viewport import Viewport3D

    configure_opengl()
    app = QApplication([])
    apply_design(app)
    session = ProjectSession.create(tempfile.mkdtemp(), "Hero")
    session.import_model(ROOT / "samples" / "vehicule_test.glb")
    session.selection.clear()
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
        QTimer.singleShot(500, lambda: (grab("studio_3d"), step_material()))

    def step_material() -> None:
        session = window.controller.session
        body = next(n for n in session.scene.walk() if n.name == "caisse")
        window.controller.select([body.id])
        window.studio.viewport.set_tool("rotate")
        window.studio.properties.tabs.setCurrentIndex(2)
        QTimer.singleShot(500, lambda: (grab("materiaux"), step_import()))

    def step_import() -> None:
        window.navigate("import")
        QTimer.singleShot(300, lambda: (grab("import"), step_upcoming()))

    def step_upcoming() -> None:
        window.navigate("lspd")
        QTimer.singleShot(300, lambda: (grab("atelier_lspd"), finish()))

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
