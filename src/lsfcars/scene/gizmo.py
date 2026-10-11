"""Mathématiques des gizmos de transformation (sans GPU, testables).

Les poignées sont testées en espace écran ; les glissements sont convertis en grandeurs
monde par intersection du rayon souris avec l'axe (translation, échelle) ou le plan de
rotation.
"""

from __future__ import annotations

import math
from enum import StrEnum

import numpy as np

from lsfcars.scene.camera import OrbitCamera
from lsfcars.scene.picking import ray_from_screen

GIZMO_PIXELS = 110.0  # taille apparente du gizmo
HIT_TOLERANCE_PX = 9.0
RING_SAMPLES = 72


class GizmoMode(StrEnum):
    SELECT = "select"
    TRANSLATE = "translate"
    ROTATE = "rotate"
    SCALE = "scale"

    @property
    def label(self) -> str:
        return {
            "select": "Sélection",
            "translate": "Déplacer",
            "rotate": "Pivoter",
            "scale": "Mettre à l'échelle",
        }[self.value]


def world_size(camera: OrbitCamera, pivot: np.ndarray, viewport_height: int) -> float:
    """Taille monde donnant une hauteur apparente constante de ``GIZMO_PIXELS``."""
    height = max(viewport_height, 1)
    if camera.orthographic:
        per_px = 2.0 * camera.half_height() / height
    else:
        _, _, forward = camera.basis()
        depth = max(float(np.dot(np.asarray(pivot) - camera.eye(), forward)), 0.05)
        per_px = 2.0 * depth * math.tan(math.radians(camera.fov_y) / 2.0) / height
    return GIZMO_PIXELS * per_px


def project(camera: OrbitCamera, points: np.ndarray, width: int, height: int) -> np.ndarray:
    """Points monde -> pixels écran (x vers la droite, y vers le bas). NaN si derrière."""
    pts = np.atleast_2d(np.asarray(points, dtype=np.float64))
    view_proj = camera.projection_matrix(width / max(height, 1)) @ camera.view_matrix()
    clip = np.hstack([pts, np.ones((len(pts), 1))]) @ view_proj.T
    w = clip[:, 3:4]
    with np.errstate(divide="ignore", invalid="ignore"):
        ndc = clip[:, :2] / w
    screen = np.column_stack([(ndc[:, 0] + 1) * 0.5 * width, (1 - ndc[:, 1]) * 0.5 * height])
    screen[w[:, 0] <= 1e-6] = np.nan
    return screen


def _segment_distance(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    if np.any(np.isnan(a)) or np.any(np.isnan(b)):
        return math.inf
    ab = b - a
    length2 = float(np.dot(ab, ab))
    t = 0.0 if length2 < 1e-9 else float(np.clip(np.dot(p - a, ab) / length2, 0.0, 1.0))
    return float(np.linalg.norm(p - (a + ab * t)))


def ring_points(
    pivot: np.ndarray, axis: np.ndarray, radius: float, samples: int = RING_SAMPLES
) -> np.ndarray:
    axis = axis / np.linalg.norm(axis)
    helper = np.array([0.0, 1.0, 0.0]) if abs(axis[1]) < 0.9 else np.array([1.0, 0.0, 0.0])
    u = np.cross(axis, helper)
    u /= np.linalg.norm(u)
    v = np.cross(axis, u)
    angles = np.linspace(0, 2 * math.pi, samples, endpoint=False)
    return pivot + radius * (np.outer(np.cos(angles), u) + np.outer(np.sin(angles), v))


def hit_test(
    mode: GizmoMode,
    camera: OrbitCamera,
    pivot: np.ndarray,
    axes: np.ndarray,
    mouse: tuple[float, float],
    width: int,
    height: int,
) -> int | None:
    """Index de l'axe (0 = X, 1 = Y, 2 = Z) sous le curseur, ou ``None``."""
    if mode is GizmoMode.SELECT:
        return None
    size = world_size(camera, pivot, height)
    p = np.asarray(mouse, dtype=np.float64)
    best, best_distance = None, HIT_TOLERANCE_PX
    for index in range(3):
        axis = axes[index] / np.linalg.norm(axes[index])
        if mode is GizmoMode.ROTATE:
            screen = project(camera, ring_points(pivot, axis, size * 0.85), width, height)
            distance = min(
                _segment_distance(p, screen[i], screen[(i + 1) % len(screen)])
                for i in range(len(screen))
            )
        else:
            ends = np.array([pivot + axis * size * 0.15, pivot + axis * size])
            a, b = project(camera, ends, width, height)
            distance = _segment_distance(p, a, b)
        if distance < best_distance:
            best, best_distance = index, distance
    return best


def _axis_parameter(
    camera: OrbitCamera,
    pivot: np.ndarray,
    axis: np.ndarray,
    mouse: tuple[float, float],
    width: int,
    height: int,
) -> float | None:
    """Paramètre t du point de l'axe le plus proche du rayon souris (pivot + t·axe)."""
    origin, direction = ray_from_screen(camera, mouse[0], mouse[1], width, height)
    axis = axis / np.linalg.norm(axis)
    w0 = pivot - origin
    b = float(np.dot(axis, direction))
    denom = 1.0 - b * b
    if denom < 1e-6:  # axe aligné avec le regard
        return None
    d, e = float(np.dot(axis, w0)), float(np.dot(direction, w0))
    return (b * e - d) / denom


def drag_translation(
    camera: OrbitCamera,
    pivot: np.ndarray,
    axis: np.ndarray,
    start: tuple[float, float],
    current: tuple[float, float],
    width: int,
    height: int,
) -> np.ndarray:
    """Déplacement monde le long de ``axis`` correspondant au glissement souris."""
    t0 = _axis_parameter(camera, pivot, axis, start, width, height)
    t1 = _axis_parameter(camera, pivot, axis, current, width, height)
    if t0 is None or t1 is None:
        return np.zeros(3)
    return (axis / np.linalg.norm(axis)) * (t1 - t0)


def drag_scale(
    camera: OrbitCamera,
    pivot: np.ndarray,
    axis: np.ndarray,
    start: tuple[float, float],
    current: tuple[float, float],
    width: int,
    height: int,
) -> float:
    t0 = _axis_parameter(camera, pivot, axis, start, width, height)
    t1 = _axis_parameter(camera, pivot, axis, current, width, height)
    if t0 is None or t1 is None or abs(t0) < 1e-6:
        return 1.0
    return float(max(t1 / t0, 0.01))


def _plane_point(
    camera: OrbitCamera,
    pivot: np.ndarray,
    normal: np.ndarray,
    mouse: tuple[float, float],
    width: int,
    height: int,
) -> np.ndarray | None:
    origin, direction = ray_from_screen(camera, mouse[0], mouse[1], width, height)
    denom = float(np.dot(normal, direction))
    if abs(denom) < 1e-4:
        return None
    return origin + direction * (float(np.dot(pivot - origin, normal)) / denom)


def drag_rotation(
    camera: OrbitCamera,
    pivot: np.ndarray,
    axis: np.ndarray,
    start: tuple[float, float],
    current: tuple[float, float],
    width: int,
    height: int,
) -> float:
    """Angle (radians, sens trigonométrique autour de ``axis``) du glissement."""
    axis = axis / np.linalg.norm(axis)
    a = _plane_point(camera, pivot, axis, start, width, height)
    b = _plane_point(camera, pivot, axis, current, width, height)
    if a is not None and b is not None:
        va, vb = a - pivot, b - pivot
        if np.linalg.norm(va) > 1e-6 and np.linalg.norm(vb) > 1e-6:
            return float(math.atan2(np.dot(np.cross(va, vb), axis), np.dot(va, vb)))
    # plan vu par la tranche : angle mesuré autour du pivot à l'écran
    center = project(camera, pivot, width, height)[0]
    sa, sb = np.asarray(start) - center, np.asarray(current) - center
    angle = math.atan2(sa[0] * sb[1] - sa[1] * sb[0], float(np.dot(sa, sb)))
    _, _, forward = camera.basis()
    return -angle if np.dot(forward, axis) > 0 else angle


def rotation_about(axis: np.ndarray, angle: float, pivot: np.ndarray) -> np.ndarray:
    """Matrice 4x4 de rotation de ``angle`` autour d'un axe passant par ``pivot``."""
    axis = axis / np.linalg.norm(axis)
    x, y, z = axis
    c, s = math.cos(angle), math.sin(angle)
    r = np.array(
        [
            [c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
            [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
            [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)],
        ]
    )
    m = np.eye(4)
    m[:3, :3] = r
    m[:3, 3] = pivot - r @ pivot
    return m
