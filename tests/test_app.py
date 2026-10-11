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


def test_smoke_test_runs_application(qapp):
    code = app.main(["--smoke-test", "300"])
    if code == app.EXIT_SMOKE_GL_FAILED and os.environ.get("LSFCARS_REQUIRE_GL") != "1":
        pytest.skip("OpenGL indisponible sur cette machine")
    assert code == 0
