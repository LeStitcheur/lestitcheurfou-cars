"""Caméra orbitale du viewport (axe vertical : +Y)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from lsfcars.scene import mathutils

MIN_DISTANCE = 0.05
MAX_DISTANCE = 5000.0
PITCH_LIMIT = 89.0


@dataclass
class OrbitCamera:
    """Caméra qui tourne autour d'un point cible.

    ``yaw`` : rotation horizontale en degrés (0 = caméra sur l'axe +Z, regard vers -Z).
    ``pitch`` : élévation en degrés (positif = au-dessus de la cible).
    """

    target: np.ndarray = field(default_factory=lambda: np.zeros(3))
    distance: float = 8.0
    yaw: float = 35.0
    pitch: float = 20.0
    fov_y: float = 45.0

    def __post_init__(self) -> None:
        self.target = np.asarray(self.target, dtype=np.float64).copy()

    # --- Position et repère -------------------------------------------------
    def eye(self) -> np.ndarray:
        yaw, pitch = math.radians(self.yaw), math.radians(self.pitch)
        offset = np.array(
            [
                math.cos(pitch) * math.sin(yaw),
                math.sin(pitch),
                math.cos(pitch) * math.cos(yaw),
            ]
        )
        return self.target + offset * self.distance

    def basis(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Vecteurs (droite, haut, avant) de la caméra en coordonnées monde."""
        view = self.view_matrix()
        right, up, back = view[0, :3], view[1, :3], view[2, :3]
        return right, up, -back

    # --- Matrices -----------------------------------------------------------
    def view_matrix(self) -> np.ndarray:
        return mathutils.look_at(self.eye(), self.target)

    def clip_planes(self) -> tuple[float, float]:
        near = max(self.distance * 0.01, 0.01)
        far = max(self.distance * 100.0, 100.0)
        return near, far

    def projection_matrix(self, aspect: float) -> np.ndarray:
        near, far = self.clip_planes()
        return mathutils.perspective(self.fov_y, aspect, near, far)

    # --- Navigation ---------------------------------------------------------
    def orbit(self, d_yaw: float, d_pitch: float) -> None:
        self.yaw = (self.yaw + d_yaw) % 360.0
        self.pitch = float(np.clip(self.pitch + d_pitch, -PITCH_LIMIT, PITCH_LIMIT))

    def pan(self, dx_px: float, dy_px: float, viewport_height: int) -> None:
        """Déplace la vue pour que la scène suive le curseur (déplacement en pixels)."""
        height = max(viewport_height, 1)
        world_per_px = 2.0 * self.distance * math.tan(math.radians(self.fov_y) / 2.0) / height
        right, up, _ = self.basis()
        self.target = self.target - right * dx_px * world_per_px + up * dy_px * world_per_px

    def zoom(self, steps: float) -> None:
        """Rapproche (steps > 0) ou éloigne (steps < 0) la caméra."""
        self.distance = float(np.clip(self.distance * (0.85**steps), MIN_DISTANCE, MAX_DISTANCE))

    def frame(self, bounds_min: np.ndarray, bounds_max: np.ndarray, margin: float = 1.15) -> None:
        """Cadre la boîte englobante donnée sans changer l'orientation."""
        bmin, bmax = np.asarray(bounds_min, float), np.asarray(bounds_max, float)
        self.target = (bmin + bmax) / 2.0
        radius = max(float(np.linalg.norm(bmax - bmin)) / 2.0, 0.1)
        distance = radius * margin / math.sin(math.radians(self.fov_y) / 2.0)
        self.distance = float(np.clip(distance, MIN_DISTANCE, MAX_DISTANCE))

    def set_view(self, yaw: float, pitch: float) -> None:
        self.yaw = yaw % 360.0
        self.pitch = float(np.clip(pitch, -PITCH_LIMIT, PITCH_LIMIT))

    def reset(self) -> None:
        defaults = OrbitCamera()
        self.target, self.distance = defaults.target, defaults.distance
        self.yaw, self.pitch = defaults.yaw, defaults.pitch

    # --- Persistance --------------------------------------------------------
    def to_state(self) -> dict[str, float | list[float]]:
        return {
            "target": [float(v) for v in self.target],
            "distance": self.distance,
            "yaw": self.yaw,
            "pitch": self.pitch,
        }

    def apply_state(self, state: dict) -> None:
        try:
            self.target = np.asarray(state["target"], dtype=np.float64).reshape(3)
            self.distance = float(np.clip(float(state["distance"]), MIN_DISTANCE, MAX_DISTANCE))
            self.set_view(float(state["yaw"]), float(state["pitch"]))
        except (KeyError, TypeError, ValueError):
            self.reset()
