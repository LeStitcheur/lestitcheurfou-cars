"""Interface complète (pytest-qt) : navigation, sidebar, studio, sauvegarde, erreurs."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from lsfcars.project.model import VehicleRole, VehicleType
from lsfcars.ui.design import tokens
from lsfcars.ui.design.qss import stylesheet
from lsfcars.ui.dialogs.new_project import NewProjectRequest
from lsfcars.ui.main_window import MainWindow, nav_entries
from lsfcars.ui.pages.pages import UPCOMING


def new(win: MainWindow, folder, name: str = "Police Buffalo") -> None:  # noqa: ANN001
    assert win.new_project(NewProjectRequest(name, folder, VehicleType.CAR, VehicleRole.LSPD, ""))


def import_sample(win: MainWindow, qtbot, path) -> None:  # noqa: ANN001
    with qtbot.waitSignal(win.controller.import_finished, timeout=30000) as blocker:
        assert win.import_model(path)
    assert blocker.args[0], blocker.args[1]


def test_dark_premium_tokens():
    palette = tokens.ColorTokens
    assert palette.PALETTE == (
        "#0b0e14",
        "#111722",
        "#151b26",
        "#202a3b",
        "#2a3445",
        "#2563eb",
        "#38bdf8",
        "#f3f6fc",
        "#94a3b8",
        "#22c55e",
        "#f59e0b",
        "#ef4444",
    )
    assert tokens.ACCENT == palette.PRIMARY and tokens.SIDEBAR == palette.BG_SECONDARY
    css = stylesheet()
    assert palette.PRIMARY in css and palette.ELECTRIC in css and "LSNavItem" in css
    # L'ancienne identité rouge / rose a disparu de la feuille de style
    for legacy in ("#ff4157", "#ff5268", "#ff7384", "#35151f", "255,65,87", "255, 65, 87"):
        assert legacy not in css


def test_starts_on_dashboard_frameless(window):
    assert window.current_page() == "dashboard"
    assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert window.topbar.project_label.text() == "Aucun projet"
    assert window.dashboard.header.title.text().startswith("Bienvenue dans ton garage")


def test_navigation_reaches_every_page(window):
    for entry in nav_entries():
        window.sidebar.items[entry.key].click()
        assert window.current_page() == entry.key
        assert window.sidebar.current() == entry.key


def test_upcoming_entries_are_marked(window):
    upcoming = {u.key for u in UPCOMING}
    for key, item in window.sidebar.items.items():
        assert item.dot.isVisibleTo(window) == (key in upcoming)
    for key in upcoming:
        assert "Bientôt" in window.pages[key].badge.text()


def test_sidebar_collapse_frees_space(window, qtbot):
    width = window.sidebar.width()
    window.toggle_sidebar()
    qtbot.waitUntil(lambda: window.sidebar.width() <= tokens.SIDEBAR_COLLAPSED_WIDTH + 1)
    assert window.sidebar.width() < width and window.settings.sidebar_collapsed
    window.toggle_sidebar()
    qtbot.waitUntil(lambda: window.sidebar.width() >= tokens.SIDEBAR_WIDTH - 1)


def test_panels_are_resizable_and_layout_saved(window):
    window.navigate("studio")
    split = window.studio.h_split
    split.setSizes([400, 700, 400])
    sizes = split.sizes()
    window.studio.save_layout()
    split.setSizes([200, 1000, 300])
    window.studio.restore_layout()
    assert split.sizes() == sizes


def test_create_import_select_transform_material_save_reopen(window, qtbot, projects_dir, sample_glb):
    new(window, projects_dir)
    assert window.current_page() == "studio"
    import_sample(window, qtbot, sample_glb)
    session = window.controller.session
    assert session.stats()[0] == 720
    assert window.topbar.save_state.text().startswith("Modif")

    explorer = window.studio.explorer
    item = explorer.item_for(next(n.id for n in session.scene.walk() if n.name == "caisse"))
    explorer.tree.setCurrentItem(item)
    body = session.scene.get(session.selection.active)
    assert body.name == "caisse"
    assert window.studio.properties.title.text() == "caisse"

    window.studio.properties.position.spins[1].setValue(0.5)
    assert body.transform.translation[1] == pytest.approx(0.5)

    editor = window.studio.properties.material_editor
    assert editor.material().name == "Peinture rouge LS"
    editor.metallic.slider.setValue(10)
    assert editor.material().metallic == pytest.approx(0.1)
    assert any(abs(i.metallic - 0.1) < 1e-6 for i in window.studio.viewport.draw_items())

    window.controller.undo()
    assert editor.material().metallic == pytest.approx(0.55)
    window.controller.redo()
    assert window.save_project()
    path = session.file_path
    assert window.topbar.save_state.text() == "Enregistré"
    assert window.close_project()

    assert window.open_project(path)
    again = window.controller.session
    reopened = next(n for n in again.scene.walk() if n.name == "caisse")
    assert reopened.transform.translation[1] == pytest.approx(0.5)
    assert again.scene.material_for(reopened.id).metallic == pytest.approx(0.1)


def test_dashboard_lists_real_projects(window, projects_dir):
    new(window, projects_dir, "Garage A")
    window.save_project()
    window.close_project()
    window.dashboard.refresh()
    assert window.dashboard.stats.cells[0].value_label.text() == "1"
    assert len(window.dashboard.grid.cards) == 1


def test_delete_requires_confirmation(window, qtbot, projects_dir, sample_glb, dialogs):
    new(window, projects_dir)
    import_sample(window, qtbot, sample_glb)
    session = window.controller.session
    count = len(session.scene)
    dialogs.confirm_answer = False
    assert window.delete_selection() == 0 and len(session.scene) == count
    dialogs.confirm_answer = True
    assert window.delete_selection() == 1 and len(session.scene) < count


def test_import_error_is_readable(window, qtbot, projects_dir, tmp_path, dialogs):
    new(window, projects_dir)
    broken = tmp_path / "casse.glb"
    broken.write_bytes(b"pas un glb")
    with qtbot.waitSignal(window.controller.import_finished, timeout=30000) as blocker:
        window.import_model(broken)
    assert blocker.args[0] is False
    assert "error" in dialogs.kinds()


def test_unsaved_changes_prompt(window, qtbot, projects_dir, sample_glb, dialogs):
    new(window, projects_dir)
    import_sample(window, qtbot, sample_glb)
    dialogs.save_answer = "cancel"
    assert not window.close_project() and window.controller.session is not None
    dialogs.save_answer = "discard"
    assert window.close_project() and window.controller.session is None


def test_search_and_notifications(window, qtbot, projects_dir, sample_glb):
    new(window, projects_dir)
    import_sample(window, qtbot, sample_glb)
    window._search("Objet : jante_avant_gauche")
    session = window.controller.session
    assert session.scene.get(session.selection.active).name == "jante_avant_gauche"
    window._search("Diagnostics")
    assert window.current_page() == "diagnostics"
    assert window.notifications.history and window.topbar.counter.isVisible()


def test_import_page_lists_formats(window):
    badges = window.import_page.formats.status_badges
    assert badges[".glb"].text() == "Disponible"
    assert badges[".yft"].text() == "Disponible"
    assert badges[".ybn"].text() == "Partiel"
    assert badges[".rpf chiffrée"].text() == "Refusé"
