"""Fixtures communes. Les données de l'application sont isolées dans un dossier temporaire."""

from __future__ import annotations

from pathlib import Path

import pytest

from lsfcars.core.logging_setup import setup_logging
from lsfcars.ui.gl_setup import configure_opengl

# Avant toute création de QApplication par pytest-qt.
# LSFCARS_SOFTWARE_GL=1 force le rendu logiciel (utilisé en CI, sans GPU).
configure_opengl()
setup_logging(to_file=False)

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


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
