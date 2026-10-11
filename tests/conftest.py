"""Fixtures communes. Les données de l'application sont isolées dans un dossier temporaire."""

from __future__ import annotations

from pathlib import Path

import pytest

from lsfcars.core.logging_setup import setup_logging
from lsfcars.ui.design.components import LSModal
from lsfcars.ui.gl_setup import configure_opengl

# Avant toute création de QApplication par pytest-qt.
# LSFCARS_SOFTWARE_GL=1 force le rendu logiciel (utilisé en CI, sans GPU).
configure_opengl()
setup_logging(to_file=False)

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


@pytest.fixture(scope="session", autouse=True)
def demo_addon_sample() -> Path:
    """Addon de démonstration (contenu synthétique original) requis par le test de démarrage."""
    from lsfcars.fivem.synthetic import write_demo_addon

    folder = SAMPLES / "fivem" / "lsfdemo"
    if not (folder / "stream" / "lsfdemo.yft").is_file():
        write_demo_addon(folder)
    return folder


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "lsfcars-home"
    monkeypatch.setenv("LSFCARS_HOME", str(home))
    return home


@pytest.fixture
def sample_glb() -> Path:
    return SAMPLES / "vehicule_test.glb"


@pytest.fixture
def sample_obj() -> Path:
    return SAMPLES / "vehicule_test.obj"


@pytest.fixture
def projects_dir(tmp_path: Path) -> Path:
    path = tmp_path / "projets"
    path.mkdir()
    return path


# --- Fenêtre principale (tests d'interface) ------------------------------------


class Dialogs:
    """Remplace les fenêtres modales : réponses programmées, appels enregistrés."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.confirm_answer = True
        self.save_answer = "discard"

    def confirm(self, parent, title, message, *args, **kwargs):  # noqa: ANN001
        self.calls.append(("confirm", title))
        return self.confirm_answer

    def ask_save(self, parent, name):  # noqa: ANN001
        self.calls.append(("ask_save", name))
        return self.save_answer

    def error(self, parent, title, message):  # noqa: ANN001
        self.calls.append(("error", title))

    def info(self, parent, title, message):  # noqa: ANN001
        self.calls.append(("info", title))

    def kinds(self) -> list[str]:
        return [k for k, _ in self.calls]


@pytest.fixture
def dialogs(monkeypatch):
    fake = Dialogs()
    for name in ("confirm", "ask_save", "error", "info"):
        monkeypatch.setattr(LSModal, name, staticmethod(getattr(fake, name)))
    return fake


@pytest.fixture
def window(qtbot, dialogs, projects_dir):
    from lsfcars.ui.main_window import MainWindow

    win = MainWindow()
    win.settings.projects_dir = projects_dir
    qtbot.addWidget(win)
    win.resize(1600, 960)
    win.show()
    qtbot.waitExposed(win)
    yield win
    if win.controller.session is not None:
        win.controller.session.stack.mark_clean()
        win.controller.session._meta_dirty = False
