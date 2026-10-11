"""Rendu OpenGL réel du viewport. Ignoré sans OpenGL, sauf si LSFCARS_REQUIRE_GL=1 (CI)."""

from __future__ import annotations

import os

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QMouseEvent

from lsfcars.project.session import ProjectSession
from lsfcars.render.renderer import BACKGROUND_BOTTOM, build_grid, glsl_header
from lsfcars.scene import gizmo
from lsfcars.ui.viewport import Viewport3D


def test_grid_and_glsl_header():
    assert build_grid(half_size=2).shape == (5 * 4, 7)
    assert glsl_header(3, 3).startswith("#version 330 core")
    assert glsl_header(3, 0).startswith("#version 130")


@pytest.fixture
def scene(projects_dir, sample_glb):
    session = ProjectSession.create(projects_dir, "Rendu")
    session.import_model(sample_glb)
    session.selection.clear()
    return session


@pytest.fixture
def viewport(qtbot, scene):
    vp = Viewport3D()
    vp.resize(640, 480)
    qtbot.addWidget(vp)
    vp.show()
    qtbot.waitExposed(vp)
    qtbot.waitUntil(lambda: vp.gl_ready or vp.gl_error is not None, timeout=10000)
    if not vp.gl_ready:
        if os.environ.get("LSFCARS_REQUIRE_GL") == "1":
            pytest.fail(f"OpenGL indisponible : {vp.gl_error}")
        pytest.skip(f"OpenGL indisponible : {vp.gl_error}")
    vp.set_session(scene)
    vp.frame_bounds(scene.world_bounds())
    return vp


def pixels(vp: Viewport3D) -> np.ndarray:
    image = vp.grabFramebuffer().convertToFormat(QImage.Format.Format_RGB888)
    w, h = image.width(), image.height()
    data = np.frombuffer(image.constBits(), np.uint8, count=image.sizeInBytes())
    return data.reshape(h, image.bytesPerLine())[:, : w * 3].reshape(h, w, 3).astype(int)


def test_vehicle_rendered_with_brand_red_paint(viewport):
    viewport.set_grid_visible(False)
    px = pixels(viewport)
    red = (px[..., 0] - px[..., 2] > 70) & (px[..., 0] > 110)
    assert red.mean() > 0.03  # la carrosserie rouge occupe l'écran
    corner = px[5, 5]
    assert np.all(np.abs(corner - np.array(BACKGROUND_BOTTOM) * 255) < 40)


def test_shading_modes_render_differently(viewport):
    images = {}
    for mode in ("material", "solid", "wireframe"):
        viewport.set_shading(mode)
        images[mode] = pixels(viewport)
    assert np.abs(images["material"] - images["solid"]).sum() > 0
    assert np.abs(images["solid"] - images["wireframe"]).sum() > 0


def test_orthographic_and_views(viewport):
    before = pixels(viewport)
    viewport.toggle_orthographic()
    viewport.set_standard_view("left")
    assert viewport.camera.orthographic
    assert np.abs(pixels(viewport) - before).sum() > 0


def test_click_selects_component(viewport, scene, qtbot):
    viewport.set_standard_view("front")
    viewport.frame_bounds(scene.world_bounds())
    with qtbot.waitSignal(viewport.selection_requested) as blocker:
        center = QPoint(viewport.width() // 2, viewport.height() // 2)
        qtbot.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=center)
    ids, mode = blocker.args
    assert mode == "replace" and len(ids) == 1
    assert scene.scene.nodes[ids[0]].kind.value == "mesh"


def test_gizmo_drag_emits_transforms(viewport, scene, qtbot):
    wheel = next(n for n in scene.scene.walk() if n.name == "roue_avant_gauche")
    scene.selection.set([wheel.id])
    viewport.set_tool("translate")
    pivot, axes = viewport._gizmo_frame()
    size = gizmo.world_size(viewport.camera, pivot, viewport.height())
    start = gizmo.project(viewport.camera, pivot + axes[0] * size * 0.7, viewport.width(), viewport.height())[
        0
    ]
    end = gizmo.project(
        viewport.camera, pivot + axes[0] * (size * 0.7 + 0.5), viewport.width(), viewport.height()
    )[0]
    received = []
    viewport.transforms_edited.connect(lambda changes, key: received.append(changes))

    def send(kind, point, buttons):  # type: ignore[no-untyped-def]
        event = QMouseEvent(
            kind,
            QPointF(*point),
            QPointF(*point),
            Qt.MouseButton.LeftButton,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        )
        getattr(
            viewport,
            {
                QMouseEvent.Type.MouseButtonPress: "mousePressEvent",
                QMouseEvent.Type.MouseMove: "mouseMoveEvent",
            }.get(kind, "mouseReleaseEvent"),
        )(event)

    send(QMouseEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton)
    send(QMouseEvent.Type.MouseMove, end, Qt.MouseButton.LeftButton)
    send(QMouseEvent.Type.MouseButtonRelease, end, Qt.MouseButton.NoButton)
    assert received, "le glissement du gizmo doit produire une transformation"
    moved = received[-1][wheel.id].translation
    assert moved[0] - wheel.transform.translation[0] == pytest.approx(0.5, abs=0.02)


def test_free_camera_flies(viewport, qtbot):
    viewport.toggle_free_camera()
    eye = viewport.camera.eye().copy()
    viewport.camera.fly(1.0, 0.0, 0.0)
    assert np.linalg.norm(viewport.camera.eye() - eye) == pytest.approx(1.0)
