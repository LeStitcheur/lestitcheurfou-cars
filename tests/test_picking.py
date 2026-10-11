import numpy as np

from lsfcars.scene import mathutils, picking
from lsfcars.scene.camera import OrbitCamera
from lsfcars.scene.mesh import MeshData

# Carré unitaire dans le plan XY, centré sur l'origine.
QUAD = MeshData(
    "quad",
    np.array([[-0.5, -0.5, 0], [0.5, -0.5, 0], [0.5, 0.5, 0], [-0.5, 0.5, 0]]),
    [[0, 1, 2], [0, 2, 3]],
)


def test_ray_from_screen_center_points_at_target():
    cam = OrbitCamera(yaw=0, pitch=0, distance=5)
    origin, direction = picking.ray_from_screen(cam, 400, 300, 800, 600)
    assert np.allclose(origin, [0, 0, 5])
    assert np.allclose(direction, [0, 0, -1])


def test_ray_hits_quad_and_misses_outside():
    origin = np.array([0.0, 0.0, 5.0])
    down = np.array([0, 0, -1.0])
    assert picking.ray_mesh_distance(origin, down, QUAD) == 5.0
    assert picking.ray_mesh_distance(origin + [2, 0, 0], down, QUAD) is None


def test_pick_returns_nearest_object():
    origin, direction = np.array([0.0, 0.0, 10.0]), np.array([0.0, 0.0, -1.0])
    candidates = [
        ("loin", mathutils.translation((0, 0, -3)), [QUAD]),
        ("proche", mathutils.translation((0, 0, 2)), [QUAD]),
    ]
    assert picking.pick(origin, direction, candidates) == "proche"


def test_pick_respects_object_transform():
    direction = np.array([0.0, 0.0, -1.0])
    moved = [("a", mathutils.trs((3, 0, 0), (0, 0, 0), (1, 1, 1)), [QUAD])]
    assert picking.pick(np.array([3.0, 0.0, 10.0]), direction, moved) == "a"
    assert picking.pick(np.array([0.0, 0.0, 10.0]), direction, moved) is None


def test_pick_ignores_degenerate_matrix():
    zero = np.zeros((4, 4))
    assert picking.pick(np.zeros(3), np.array([0, 0, -1.0]), [("x", zero, [QUAD])]) is None
