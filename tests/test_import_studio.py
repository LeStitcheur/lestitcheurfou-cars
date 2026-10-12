"""Vehicle Import Studio (pytest-qt) : analyse, aperçu, inspection, import, sauvegarde, réouverture."""

from __future__ import annotations

import numpy as np
import pytest

from lsfcars.fivem.synthetic import write_demo_addon
from lsfcars.project.model import VehicleRole, VehicleType
from lsfcars.ui.design import tokens
from lsfcars.ui.dialogs.new_project import NewProjectRequest


@pytest.fixture
def addon(tmp_path):
    return write_demo_addon(tmp_path / "lsfdemo")


def analyze(page, qtbot, path) -> None:  # noqa: ANN001
    with qtbot.waitSignal(page.analysis_finished, timeout=60000) as blocker:
        assert page.analyze(path) is not None
    assert blocker.args[0]


def preview(page, qtbot, name: str) -> None:  # noqa: ANN001
    with qtbot.waitSignal(page.preview_finished, timeout=60000) as blocker:
        assert page.preview_model(name) is not None
    assert blocker.args[0]


def test_import_studio_full_flow(window, qtbot, addon, projects_dir, tmp_path):
    page = window.import_page
    window.navigate("import")
    assert window.current_page() == "import"
    analyze(page, qtbot, addon)
    assert page.overall.text() == "Compatible"
    assert "lsfdemo" in page.subtitle.text()
    assert page.vehicle.current_model().name == "lsfdemo"

    # Fichiers cliquables : fiche détaillée et métadonnées structurées
    page.show_file("data/handling.meta")
    assert page.file_info.title.text() == "handling.meta"
    assert page.metadata.current().kind == "handling"
    page.metadata.search.setText("fMass")
    assert page.metadata.results.count() >= 1
    page.show_file("stream/lsfdemo.yft")
    assert "168 triangles" in page.file_info.message.text()

    # Inspecteur de textures : aperçu réel, export d'une copie
    assert page.textures.list.count() == 3
    page.textures.list.setCurrentRow(2)
    assert page.textures.preview.pixmap() is not None and not page.textures.preview.pixmap().isNull()
    exported = page.textures.export("png", str(tmp_path / "copie.png"))
    assert exported and (tmp_path / "copie.png").stat().st_size > 0
    assert "vehicle_generic_tyrewallblack" in page.textures.missing.text()

    # Aperçu 3D, sélection, isolation, vue éclatée (non destructive)
    preview(page, qtbot, "lsfdemo")
    session = page.preview_session
    assert session.stats()[0] == 168 and len(page.viewport.draw_items()) == 14
    ids = page.select_parts(["door_dside_f"])
    assert ids and "Portes" in page.vehicle.selection.values["Catégorie"].text()
    page.isolate_selection()
    assert len(page.viewport.draw_items()) == 1
    page.show_all()
    before = {n.id: n.transform.matrix().copy() for n in session.scene.walk()}
    page.set_explode(70)
    assert page.mode == "eclate" and page.viewport.display_offsets
    assert len(page.viewport.draw_items()) == 14
    assert all(np.allclose(n.transform.matrix(), before[n.id]) for n in session.scene.walk())
    page.reset_view()
    assert page.viewport.display_offsets == {} and page.mode == "complet"
    page.set_mode("filaire")
    assert page.viewport.shading == "wireframe"
    page.set_mode("statistiques")
    assert page.right.currentWidget() is page.stats and page.stats.rowCount() == 14
    assert not page.mode_buttons["collisions"].isEnabled()
    assert "non implémenté" in page.mode_buttons["collisions"].text()

    # Import dans un projet, sauvegarde, fermeture, réouverture
    request = NewProjectRequest("Police démo", projects_dir, VehicleType.CAR, VehicleRole.LSPD, "")
    assert window.new_project(request)
    window.navigate("import")
    assert page.import_to_project()
    assert window.current_page() == "studio"
    project_session = window.controller.session
    assert len(project_session.project.resources) == 1
    door = next(n for n in project_session.scene.walk() if n.name == "door_dside_f")
    window.controller.rename(door.id, "porte_avant_gauche")
    assert any(n.title == "Compatibilité FiveM" for n in window.notifications.history)
    assert window.save_project()
    path = project_session.file_path
    assert window.close_project()
    assert window.open_project(path)
    reopened = window.controller.session
    assert reopened.stats()[0] == 168
    assert any(n.name == "porte_avant_gauche" for n in reopened.scene.walk())
    (resource,) = reopened.project.resources.values()
    assert resource.manifest["model"]["name"] == "lsfdemo"


def test_import_studio_reports_invalid_sources(window, qtbot, tmp_path, dialogs):
    page = window.import_page
    bad = tmp_path / "faux.zip"
    bad.write_bytes(b"pas un zip")
    with qtbot.waitSignal(page.analysis_finished, timeout=30000) as blocker:
        page.analyze(bad)
    assert blocker.args[0] is False
    assert "error" in dialogs.kinds()
    assert page.analysis is None


def test_import_studio_cancel(window, qtbot, addon):
    page = window.import_page
    with qtbot.waitSignal(page.analysis_finished, timeout=30000) as blocker:
        worker = page.analyze(addon)
        worker.cancel()
    # Annulée avant la fin ou terminée trop vite : jamais d'état incohérent
    assert blocker.args[0] in (True, False)
    assert not page.is_busy()


def test_dark_premium_palette_only():
    palette = set(tokens.ColorTokens.PALETTE)
    assert len(palette) == 12
    assert tokens.ACCENT == "#2563eb" and tokens.ACCENT_2 == "#38bdf8"


def test_import_studio_imports_standard_models(window, qtbot, projects_dir, tmp_path):
    """Un GLB ouvert dans le Vehicle Import Studio (dossier ou ZIP) s'importe comme modèle 3D."""
    import zipfile

    import trimesh

    folder = tmp_path / "prototype"
    folder.mkdir()
    parts = [trimesh.creation.box((1, 0.4, 0.3)), trimesh.creation.cylinder(0.3, 0.15)]
    trimesh.Scene(parts).export(folder / "moto.glb")
    (folder / "README.md").write_text("notes", encoding="utf-8")
    page = window.import_page
    window.navigate("import")
    analyze(page, qtbot, folder)
    assert page.overall.text() != "Compatible"  # un GLB n'est jamais déclaré compatible FiveM
    assert page.vehicle.current_model() is None and not page.vehicle.import_button.isEnabled()
    assert page.vehicle.generic.isVisibleTo(page.vehicle)
    assert page.vehicle.generic_models.currentData() == "moto.glb"
    request = NewProjectRequest("Moto", projects_dir, VehicleType.MOTORCYCLE, VehicleRole.EMS, "")
    assert window.new_project(request)
    window.navigate("import")
    with qtbot.waitSignal(window.controller.import_finished, timeout=60000) as blocker:
        page.vehicle.generic_import.click()
    assert blocker.args[0], blocker.args[1]
    assert window.current_page() == "studio"
    session = window.controller.session
    assert session.stats()[0] == sum(len(p.faces) for p in parts)
    assert (folder / "moto.glb").is_file()  # original intact

    archive = tmp_path / "prototype.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(folder / "moto.glb", "modeles/moto.glb")
    analyze(page, qtbot, archive)
    local = page.analysis.local_model_path(page.analysis.find("modeles/moto.glb"))
    assert local.is_file() and local.read_bytes() == (folder / "moto.glb").read_bytes()
