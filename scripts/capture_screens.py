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
        QTimer.singleShot(400, lambda: (grab("metadonnees_filaire"), step_upcoming()))

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
