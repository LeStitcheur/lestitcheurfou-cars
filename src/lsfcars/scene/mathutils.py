"""Matrices 4x4 (convention mathématique : vecteurs colonnes, ``M @ v``).

Les matrices sont envoyées à OpenGL avec ``transpose=GL_TRUE``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

Vec3 = Sequence[float]


def identity() -> np.ndarray:
    return np.eye(4, dtype=np.float64)


def translation(t: Vec3) -> np.ndarray:
    m = identity()
    m[:3, 3] = t
    return m


def scaling(s: Vec3) -> np.ndarray:
    return np.diag([s[0], s[1], s[2], 1.0]).astype(np.float64)


def rotation_euler_xyz(degrees: Vec3) -> np.ndarray:
    """Rotation d'Euler appliquée dans l'ordre X puis Y puis Z (``Rz @ Ry @ Rx``)."""
    rx, ry, rz = (math.radians(a) for a in degrees)
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    mx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    my = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    mz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    m = identity()
    m[:3, :3] = mz @ my @ mx
    return m


def trs(t: Vec3, r_deg: Vec3, s: Vec3) -> np.ndarray:
    """Matrice modèle : échelle, puis rotation, puis translation."""
    return translation(t) @ rotation_euler_xyz(r_deg) @ scaling(s)


def perspective(fov_y_deg: float, aspect: float, near: float, far: float) -> np.ndarray:
    f = 1.0 / math.tan(math.radians(fov_y_deg) / 2.0)
    aspect = max(aspect, 1e-6)
    m = np.zeros((4, 4), dtype=np.float64)
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = (2.0 * far * near) / (near - far)
    m[3, 2] = -1.0
    return m


def look_at(eye: Vec3, target: Vec3, up: Vec3 = (0.0, 1.0, 0.0)) -> np.ndarray:
    eye_v = np.asarray(eye, dtype=np.float64)
    forward = np.asarray(target, dtype=np.float64) - eye_v
    forward /= np.linalg.norm(forward)
    side = np.cross(forward, np.asarray(up, dtype=np.float64))
    if np.linalg.norm(side) < 1e-9:  # regard parallèle à « up »
        side = np.cross(forward, np.array([0.0, 0.0, 1.0]))
    side /= np.linalg.norm(side)
    true_up = np.cross(side, forward)
    m = identity()
    m[0, :3] = side
    m[1, :3] = true_up
    m[2, :3] = -forward
    m[:3, 3] = -m[:3, :3] @ eye_v
    return m


def normal_matrix(model: np.ndarray) -> np.ndarray:
    """Matrice 3x3 pour transformer les normales (inverse transposée)."""
    upper = model[:3, :3]
    try:
        return np.linalg.inv(upper).T
    except np.linalg.LinAlgError:  # échelle nulle
        return np.eye(3)


def transform_points(m: np.ndarray, points: np.ndarray) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    return pts @ m[:3, :3].T + m[:3, 3]
