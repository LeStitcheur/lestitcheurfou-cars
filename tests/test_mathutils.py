import numpy as np
import pytest

from lsfcars.scene import mathutils


def test_trs_identity():
    m = mathutils.trs((0, 0, 0), (0, 0, 0), (1, 1, 1))
    assert np.allclose(m, np.eye(4))


def test_translation_moves_points():
    pts = mathutils.transform_points(mathutils.translation((1, 2, 3)), [[0, 0, 0], [1, 1, 1]])
    assert np.allclose(pts, [[1, 2, 3], [2, 3, 4]])


def test_rotation_y_90_maps_x_to_minus_z():
    m = mathutils.rotation_euler_xyz((0, 90, 0))
    assert np.allclose(mathutils.transform_points(m, [[1, 0, 0]]), [[0, 0, -1]], atol=1e-9)


def test_trs_applies_scale_then_rotation_then_translation():
    m = mathutils.trs((10, 0, 0), (0, 0, 90), (2, 2, 2))
    # (1,0,0) -> échelle (2,0,0) -> rotation Z 90° (0,2,0) -> translation (10,2,0)
    assert np.allclose(mathutils.transform_points(m, [[1, 0, 0]]), [[10, 2, 0]], atol=1e-9)


def test_normal_matrix_compensates_non_uniform_scale():
    model = mathutils.scaling((2, 1, 1))
    n = mathutils.normal_matrix(model) @ np.array([1.0, 1.0, 0.0])
    assert n[0] == pytest.approx(0.5)
    assert n[1] == pytest.approx(1.0)


def test_normal_matrix_handles_zero_scale():
    assert np.allclose(mathutils.normal_matrix(mathutils.scaling((0, 1, 1))), np.eye(3))


def test_perspective_maps_near_and_far_planes():
    near, far = 0.5, 100.0
    proj = mathutils.perspective(60, 1.5, near, far)
    for depth, expected in ((near, -1.0), (far, 1.0)):
        clip = proj @ np.array([0, 0, -depth, 1.0])
        assert clip[2] / clip[3] == pytest.approx(expected)


def test_look_at_places_target_on_negative_z():
    view = mathutils.look_at((3, 4, 5), (0, 1, 0))
    target_view = view @ np.array([0, 1, 0, 1.0])
    assert target_view[0] == pytest.approx(0, abs=1e-9)
    assert target_view[1] == pytest.approx(0, abs=1e-9)
    assert target_view[2] < 0


def test_look_at_straight_down_is_stable():
    view = mathutils.look_at((0, 10, 0), (0, 0, 0))
    assert np.all(np.isfinite(view))
