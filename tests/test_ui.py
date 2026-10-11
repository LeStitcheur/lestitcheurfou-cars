"""Tests de l'interface (pytest-qt). Les boîtes de message sont remplacées par un double."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from lsfcars import APP_NAME, __version__
from lsfcars.core.logging_setup import get_logger
from lsfcars.project import recent
from lsfcars.project.model import VehicleRole, VehicleType
from lsfcars.ui import main_window as main_window_module
from lsfcars.ui.dialogs.diagnostics import DiagnosticsDialog
from lsfcars.ui.dialogs.new_project import NewProjectDialog, NewProjectRequest
from lsfcars.ui.main_window import MODE_3D, MODE_HOME, MainWindow
from lsfcars.ui.workshop_page import PLANNED_BADGE


class FakeMessageBox:
    """Remplace QMessageBox : enregistre les appels et renvoie une réponse programmée."""

    StandardButton = QMessageBox.StandardButton
    answer = QMessageBox.StandardButton.Yes
    calls: list[tuple[str, str]] = []

    @classmethod
    def question(cls, parent, title, *args, **kwargs):  # noqa: ANN001
        cls.calls.append(("question", title))
        return cls.answer

    @classmethod
    def critical(cls, parent, title, *args, **kwargs):  # noqa: ANN001
        cls.calls.append(("critical", title))

    @classmethod
    def warning(cls, parent, title, *args, **kwargs):  # noqa: ANN001
        cls.calls.append(("warning", title))

    @classmethod
    def about(cls, parent, title, *args, **kwargs):  # noqa: ANN001
        cls.calls.append(("about", title))

    @classmethod
    def kinds(cls) -> list[str]:
        return [kind for kind, _ in cls.calls]


@pytest.fixture
def message_box(monkeypatch):
    FakeMessageBox.calls = []
    FakeMessageBox.answer = QMessageBox.StandardButton.Yes
    monkeypatch.setattr(main_window_module, "QMessageBox", FakeMessageBox)
    return FakeMessageBox


@pytest.fixture
def window(qtbot, message_box):
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    yield win
    if win.session is not None:
        win.session.dirty = False


def _new(win: MainWindow, folder, name: str = "Projet test") -> None:
    request = NewProjectRequest(name, folder, VehicleType.CAR, VehicleRole.LSPD, "")
    assert win.new_project(request)


def test_starts_on_home_page(window):
    assert window.current_mode() == MODE_HOME
    assert window.windowTitle() == APP_NAME
    assert not window.act_save.isEnabled()
    assert not window.explorer_dock.isVisible()


def test_new_project_opens_3d_workshop(window, projects_dir):
    _new(window, projects_dir)
    assert window.current_mode() == MODE_3D
    assert window.explorer_dock.isVisible() and window.properties_dock.isVisible()
    assert window.session.project.role is VehicleRole.LSPD
    assert window.explorer.empty_label.isVisible()
    assert window.session.file_path.resolve() in recent.list_recent()
    assert window.act_save.isEnabled()


def test_import_updates_scene_and_panels(window, projects_dir, sample_glb):
    _new(window, projects_dir)
    obj = window.import_model(sample_glb)
    assert obj is not None
    assert window.explorer.tree.topLevelItemCount() == 1
    assert window.explorer.selected_id() == obj.id
    assert window.properties.current_object_id() == obj.id
    assert window.viewport.object_ids() == [obj.id]
    assert window.viewport.selected() == obj.id
    assert "688" in window.status_scene.text()
    assert window.windowTitle().startswith("Projet test *")


def test_edit_transform_from_properties(window, projects_dir, sample_glb):
    _new(window, projects_dir)
    obj = window.import_model(sample_glb)
    before_min, _ = window.session.world_bounds()
    window.properties.translation.spins[0].setValue(2.5)
    assert obj.transform.translation[0] == pytest.approx(2.5)
    after_min, _ = window.session.world_bounds()
    assert after_min[0] - before_min[0] == pytest.approx(2.5, abs=1e-4)
    assert window.session.dirty


def test_uniform_scale(window, projects_dir, sample_glb):
    _new(window, projects_dir)
    obj = window.import_model(sample_glb)
    window.properties.scale.spins[1].setValue(2.0)
    assert obj.transform.scale == [2.0, 2.0, 2.0]
    window.properties.uniform_scale.setChecked(False)
    window.properties.scale.spins[0].setValue(3.0)
    assert obj.transform.scale == [3.0, 2.0, 2.0]


def test_visibility_from_explorer(window, projects_dir, sample_glb):
    _new(window, projects_dir)
    obj = window.import_model(sample_glb)
    item = window.explorer.tree.topLevelItem(0)
    item.setCheckState(0, Qt.CheckState.Unchecked)
    assert obj.visible is False
    assert window.properties.object_visible.isChecked() is False


def test_viewport_click_selects_object(window, projects_dir, sample_glb):
    _new(window, projects_dir)
    obj = window.import_model(sample_glb)
    window.viewport.object_clicked.emit(None)
    assert window.explorer.selected_id() is None
    assert window.properties.current_object_id() is None
    window.viewport.object_clicked.emit(obj.id)
    assert window.explorer.selected_id() == obj.id


def test_save_close_and_reopen(window, projects_dir, sample_glb):
    _new(window, projects_dir, "Persistance")
    obj = window.import_model(sample_glb)
    window.properties.rotation.spins[1].setValue(90)
    window.viewport.camera.orbit(30, 10)
    camera_state = window.viewport.camera.to_state()
    assert window.save_project()
    assert not window.session.dirty
    assert "*" not in window.windowTitle()
    path = window.session.file_path

    assert window.close_project()
    assert window.session is None
    assert window.current_mode() == MODE_HOME
    assert window.viewport.object_ids() == []

    assert window.open_project(path)
    reopened = window.session.project.objects
    assert [o.id for o in reopened] == [obj.id]
    assert reopened[0].transform.rotation[1] == pytest.approx(90)
    restored = window.viewport.camera.to_state()
    assert restored["yaw"] == pytest.approx(camera_state["yaw"])
    assert restored["pitch"] == pytest.approx(camera_state["pitch"])
    assert window.explorer.tree.topLevelItemCount() == 1


def test_unsaved_changes_cancel_keeps_project(window, projects_dir, sample_glb, message_box):
    _new(window, projects_dir)
    window.import_model(sample_glb)
    message_box.answer = QMessageBox.StandardButton.Cancel
    assert not window.close_project()
    assert window.session is not None


def test_unsaved_changes_discard(window, projects_dir, sample_glb, message_box):
    _new(window, projects_dir)
    window.import_model(sample_glb)
    message_box.answer = QMessageBox.StandardButton.Discard
    assert window.close_project()
    assert window.session is None


def test_open_invalid_project_shows_error(window, tmp_path, message_box):
    bad = tmp_path / "faux.lsfc"
    bad.write_bytes(b"x" * 200)
    assert not window.open_project(bad)
    assert "critical" in message_box.kinds()
    assert window.session is None


def test_import_invalid_file_shows_error(window, projects_dir, tmp_path, message_box):
    _new(window, projects_dir)
    bad = tmp_path / "casse.obj"
    bad.write_text("pas un modèle", encoding="utf-8")
    assert window.import_model(bad) is None
    assert "critical" in message_box.kinds()
    assert window.session.project.objects == []


def test_import_without_project_can_be_declined(window, sample_glb, message_box):
    message_box.answer = QMessageBox.StandardButton.No
    assert window.import_model(sample_glb) is None
    assert window.session is None
    assert message_box.kinds() == ["question"]


def test_remove_object(window, projects_dir, sample_glb):
    _new(window, projects_dir)
    obj = window.import_model(sample_glb)
    window.remove_object(obj.id, confirm=False)
    assert window.explorer.tree.topLevelItemCount() == 0
    assert window.viewport.object_ids() == []
    assert window.properties.current_object_id() is None


def test_sample_project(window):
    assert window.open_sample_project()
    assert len(window.session.project.objects) == 1
    assert not window.session.dirty
    assert window.current_mode() == MODE_3D


def test_workshop_pages_are_marked_planned(window):
    for key, page in window.workshop_pages.items():
        assert page.badge.text() == PLANNED_BADGE
        window.set_mode(key)
        assert window.current_mode() == key
        assert not window.explorer_dock.isVisible()


def test_log_panel_receives_messages(window, qtbot):
    get_logger("ui-test").warning("alerte visible dans le journal")
    qtbot.waitUntil(lambda: "alerte visible dans le journal" in window.log_panel.text())
    window.log_panel.level_combo.setCurrentIndex(3)  # erreurs uniquement
    assert "alerte visible dans le journal" not in window.log_panel.text()


def test_new_project_dialog_validation(qtbot, projects_dir):
    dialog = NewProjectDialog()
    qtbot.addWidget(dialog)
    ok = dialog.buttons.button(dialog.buttons.StandardButton.Ok)
    dialog.location_edit.setText(str(projects_dir))
    dialog.name_edit.setText("   ")
    assert not ok.isEnabled()
    dialog.name_edit.setText("Valide")
    assert ok.isEnabled()
    (projects_dir / "Valide").mkdir()
    (projects_dir / "Valide" / "x.txt").write_text("x")
    dialog.name_edit.setText("Valide ")
    assert not ok.isEnabled()
    dialog.name_edit.setText("Autre")
    dialog.type_combo.setCurrentIndex(dialog.type_combo.findData(VehicleType.BOAT.value))
    request = dialog.request()
    assert (request.name, request.parent_dir, request.vehicle_type) == (
        "Autre",
        projects_dir,
        VehicleType.BOAT,
    )


def test_diagnostics_dialog(qtbot):
    dialog = DiagnosticsDialog()
    qtbot.addWidget(dialog)
    assert __version__ in dialog.report.toPlainText()
