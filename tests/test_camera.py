import math

import numpy as np
import pytest

from lsfcars.scene.camera import MAX_DISTANCE, MIN_DISTANCE, PITCH_LIMIT, OrbitCamera


def test_eye_is_at_distance_from_target():
    cam = OrbitCamera(target=np.array([1.0, 2.0, 3.0]), distance=7.0)
    assert np.linalg.norm(cam.eye() - cam.target) == pytest.approx(7.0)


def test_orbit_wraps_yaw_and_clamps_pitch():
    cam = OrbitCamera(yaw=350, pitch=80)
    cam.orbit(20, 50)
    assert cam.yaw == pytest.approx(10)
    assert cam.pitch == PITCH_LIMIT
    cam.orbit(0, -500)
    assert cam.pitch == -PITCH_LIMIT


def test_zoom_in_and_out_with_limits():
    cam = OrbitCamera(distance=10)
    cam.zoom(1)
    assert cam.distance < 10
    cam.zoom(-1000)
    assert cam.distance == MAX_DISTANCE
    cam.zoom(1000)
    assert cam.distance == MIN_DISTANCE


def test_frame_centers_and_fits_box():
    cam = OrbitCamera()
    bmin, bmax = np.array([-1.0, 0.0, -2.0]), np.array([1.0, 1.5, 2.0])
    cam.frame(bmin, bmax)
    assert np.allclose(cam.target, (bmin + bmax) / 2)
    radius = np.linalg.norm(bmax - bmin) / 2
    # la sphère englobante tient dans le champ de vision vertical
    assert radius / cam.distance <= math.sin(math.radians(cam.fov_y) / 2) + 1e-9


def test_pan_moves_target_perpendicular_to_view():
    cam = OrbitCamera()
    _, _, forward = cam.basis()
    before = cam.target.copy()
    cam.pan(50, -30, 600)
    delta = cam.target - before
    assert np.linalg.norm(delta) > 0
    assert abs(np.dot(delta, forward)) < 1e-9


def test_basis_is_orthonormal():
    right, up, forward = OrbitCamera(yaw=123, pitch=-37).basis()
    for v in (right, up, forward):
        assert np.linalg.norm(v) == pytest.approx(1.0)
    assert np.dot(right, up) == pytest.approx(0, abs=1e-9)
    assert np.dot(right, forward) == pytest.approx(0, abs=1e-9)


def test_state_roundtrip():
    cam = OrbitCamera(target=np.array([1.0, 2.0, 3.0]), distance=12, yaw=45, pitch=-10)
    other = OrbitCamera()
    other.apply_state(cam.to_state())
    assert np.allclose(other.target, cam.target)
    assert (other.distance, other.yaw, other.pitch) == (12, 45, -10)


def test_invalid_state_resets_camera():
    cam = OrbitCamera(distance=99)
    cam.apply_state({"target": "n'importe quoi"})
    assert cam.distance == OrbitCamera().distance


def test_projection_matrix_is_finite():
    assert np.all(np.isfinite(OrbitCamera().projection_matrix(16 / 9)))
