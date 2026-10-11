import os

import pytest

from lsfcars import app


def test_parse_args_defaults():
    args = app.parse_args([])
    assert args.project is None
    assert not args.software_gl
    assert args.smoke_test is None


def test_parse_args_ignores_qt_arguments():
    args = app.parse_args(["projet.lsfc", "--software-gl", "-platform", "windows"])
    assert args.project == "projet.lsfc"
    assert args.software_gl


def test_smoke_test_runs_application(isolated_home):
    """Démarrage réel dans un processus séparé (comme l'exécutable)."""
    import subprocess
    import sys

    env = {**os.environ, "LSFCARS_HOME": str(isolated_home)}
    completed = subprocess.run(
        [sys.executable, "-m", "lsfcars", "--smoke-test", "800"], env=env, capture_output=True, timeout=120
    )
    if completed.returncode == app.EXIT_SMOKE_GL_FAILED and os.environ.get("LSFCARS_REQUIRE_GL") != "1":
        pytest.skip("OpenGL indisponible sur cette machine")
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")[-2000:]
