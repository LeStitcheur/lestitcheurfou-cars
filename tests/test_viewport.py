"""Rendu OpenGL réel. Ignoré sans OpenGL, sauf si LSFCARS_REQUIRE_GL=1 (CI)."""

from __future__ import annotations

import os

import numpy as np
import pytest
from PySide6.QtGui import QImage

from lsfcars.scene.loader import load_meshes
from lsfcars.scene.mesh import combined_bounds
from lsfcars.ui.theme import VIEWPORT_BACKGROUND
from lsfcars.ui.viewport import Viewport3D, _glsl_header, build_grid

BACKGROUND_RGB = tuple(round(c * 255) for c in VIEWPORT_BACKGROUND)


def test_build_grid_shape():
    grid = build_grid(half_size=2)
    assert grid.shape == (5 * 4, 6)
    assert grid.dtype == np.float32


def test_glsl_header_depends_on_context():
    assert _glsl_header(3, 3).startswith("#version 330 core")
    assert _glsl_header(4, 6).startswith("#version 330 core")
    assert _glsl_header(3, 0).startswith("#version 130")


@pytest.fixture
def viewport(qtbot):
    vp = Viewport3D()
    vp.resize(640, 480)
    qtbot.addWidget(vp)
    vp.show()
    qtbot.waitExposed(vp)
    qtbot.waitUntil(lambda: vp.gl_ready or vp.gl_error is not None, timeout=10000)
    if not vp.gl_ready:
        message = f"OpenGL indisponible : {vp.gl_error}"
        if os.environ.get("LSFCARS_REQUIRE_GL") == "1":
            pytest.fail(message)
        pytest.skip(message)
    return vp


def _pixels(image: QImage) -> np.ndarray:
    image = image.convertToFormat(QImage.Format.Format_RGB888)
    width, height = image.width(), image.height()
    data = np.frombuffer(image.constBits(), dtype=np.uint8, count=image.sizeInBytes())
    return data.reshape(height, image.bytesPerLine())[:, : width * 3].reshape(height, width, 3)


def _is_background(pixel: np.ndarray) -> bool:
    return bool(np.all(np.abs(pixel.astype(int) - BACKGROUND_RGB) <= 3))


def _show_car(viewport: Viewport3D, path) -> None:  # noqa: ANN001
    meshes = load_meshes(path)
    viewport.set_object("car", meshes)
    viewport.frame_bounds(combined_bounds(meshes))


def test_empty_scene_shows_background(viewport):
    viewport.set_grid_visible(False)
    pixels = _pixels(viewport.grabFramebuffer())
    assert _is_background(pixels[pixels.shape[0] // 2, pixels.shape[1] // 2])


def test_renders_sample_vehicle(viewport, sample_glb):
    viewport.set_grid_visible(False)
    _show_car(viewport, sample_glb)
    pixels = _pixels(viewport.grabFramebuffer())
    h, w, _ = pixels.shape
    assert not _is_background(pixels[h // 2, w // 2])  # le véhicule couvre le centre
    covered = np.mean([not _is_background(p) for p in pixels[::8, ::8].reshape(-1, 3)])
    assert covered > 0.05
    # la carrosserie bleue est visible (canal bleu dominant)
    blueish = (pixels[..., 2].astype(int) - pixels[..., 0].astype(int)) > 80
    assert blueish.mean() > 0.02


def test_hidden_object_is_not_drawn(viewport, sample_glb):
    viewport.set_grid_visible(False)
    _show_car(viewport, sample_glb)
    viewport.set_object_state("car", np.eye(4), visible=False)
    pixels = _pixels(viewport.grabFramebuffer())
    assert _is_background(pixels[pixels.shape[0] // 2, pixels.shape[1] // 2])


def test_selection_highlight_changes_render(viewport, sample_glb):
    _show_car(viewport, sample_glb)
    normal = _pixels(viewport.grabFramebuffer()).astype(int)
    viewport.set_selected("car")
    selected = _pixels(viewport.grabFramebuffer()).astype(int)
    assert np.abs(selected - normal).sum() > 0


def test_pick_center_after_framing(viewport, sample_glb):
    _show_car(viewport, sample_glb)
    assert viewport.pick(viewport.width() / 2, viewport.height() / 2) == "car"
    assert viewport.pick(2, 2) is None


def test_replace_and_remove_geometry(viewport, sample_glb, sample_obj):
    viewport.set_object("car", load_meshes(sample_glb))
    viewport.grabFramebuffer()  # envoi GPU
    viewport.set_object("car", load_meshes(sample_obj))
    viewport.grabFramebuffer()
    viewport.remove_object("car")
    viewport.clear()
    assert viewport.object_ids() == []
    viewport.grabFramebuffer()  # libération différée sans erreur
