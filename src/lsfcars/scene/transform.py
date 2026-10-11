"""Transformation d'un nœud (translation, rotation d'Euler XYZ en degrés, échelle)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from lsfcars.scene import mathutils


@dataclass
class Transform:
    translation: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotation: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    scale: list[float] = field(default_factory=lambda: [1.0, 1.0, 1.0])

    def matrix(self) -> np.ndarray:
        return mathutils.trs(self.translation, self.rotation, self.scale)

    def copy(self) -> Transform:
        return Transform(list(self.translation), list(self.rotation), list(self.scale))

    def to_dict(self) -> dict[str, list[float]]:
        return {
            "translation": [float(v) for v in self.translation],
            "rotation": [float(v) for v in self.rotation],
            "scale": [float(v) for v in self.scale],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Transform:
        def vec(key: str, default: float) -> list[float]:
            values = data.get(key, [default] * 3)
            if not isinstance(values, list) or len(values) != 3:
                return [default] * 3
            return [float(v) for v in values]

        return cls(vec("translation", 0.0), vec("rotation", 0.0), vec("scale", 1.0))

    @classmethod
    def from_matrix(cls, matrix: np.ndarray) -> Transform:
        return decompose(matrix)

    def is_close(self, other: Transform, tol: float = 1e-6) -> bool:
        return all(
            np.allclose(a, b, atol=tol)
            for a, b in (
                (self.translation, other.translation),
                (self.rotation, other.rotation),
                (self.scale, other.scale),
            )
        )


def euler_xyz_from_rotation(r: np.ndarray) -> list[float]:
    """Angles (degrés) tels que ``R = Rz @ Ry @ Rx`` (inverse de ``mathutils.rotation_euler_xyz``)."""
    sy = max(-1.0, min(1.0, -float(r[2, 0])))
    ry = math.asin(sy)
    if abs(math.cos(ry)) > 1e-6:
        rx = math.atan2(float(r[2, 1]), float(r[2, 2]))
        rz = math.atan2(float(r[1, 0]), float(r[0, 0]))
    else:  # blocage de cardan : rz arbitraire
        rx = math.atan2(-float(r[1, 2]), float(r[1, 1]))
        rz = 0.0
    return [math.degrees(rx), math.degrees(ry), math.degrees(rz)]


def decompose(matrix: np.ndarray) -> Transform:
    """Décompose une matrice 4x4 en TRS (le cisaillement éventuel est ignoré)."""
    m = np.asarray(matrix, dtype=np.float64)
    translation = m[:3, 3].tolist()
    basis = m[:3, :3].copy()
    scale = np.linalg.norm(basis, axis=0)
    scale[scale < 1e-12] = 1e-12
    if np.linalg.det(basis) < 0:  # miroir : porté par l'axe X
        scale[0] = -scale[0]
    rotation = basis / scale
    u, _, vt = np.linalg.svd(rotation)  # ré-orthonormalisation (bruit, léger cisaillement)
    rotation = u @ vt
    angles = euler_xyz_from_rotation(rotation)
    return Transform(
        [float(v) for v in translation],
        [round(a, 9) for a in angles],
        [float(v) for v in scale],
    )
