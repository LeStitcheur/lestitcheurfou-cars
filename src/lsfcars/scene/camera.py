"""Caméra du viewport (axe vertical +Y) : orbite, vol libre, perspective ou orthographique."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from lsfcars.scene import mathutils

MIN_DISTANCE = 0.05
MAX_DISTANCE = 5000.0
PITCH_LIMIT = 89.0

STANDARD_VIEWS: dict[str, tuple[float, float]] = {
    "front": (0.0, 0.0),
    "back": (180.0, 0.0),
    "right": (90.0, 0.0),
    "left": (270.0, 0.0),
    "top": (0.0, 89.0),
    "bottom": (0.0, -89.0),
    "perspective": (35.0, 20.0),
}

VIEW_LABELS = {
    "front": "Avant",
    "back": "Arrière",
    "right": "Droite",
    "left": "Gauche",
    "top": "Dessus",
    "bottom": "Dessous",
    "perspective": "Perspective",
}


@dataclass
class OrbitCamera:
    """Caméra définie par une cible, une distance et deux angles.

    ``yaw`` : rotation horizontale (0 = caméra sur +Z regardant vers -Z).
    ``pitch`` : élévation (positif = au-dessus de la cible).
    En mode libre, l'œil reste fixe quand on regarde autour et la cible le suit.
    """

    target: np.ndarray = field(default_factory=lambda: np.zeros(3))
    distance: float = 8.0
    yaw: float = 35.0
    pitch: float = 20.0
    fov_y: float = 45.0
    orthographic: bool = False
    mode: str = "orbit"  # « orbit » ou « free »

    def __post_init__(self) -> None:
        self.target = np.asarray(self.target, dtype=np.float64).copy()

    # --- Position et repère -------------------------------------------------
    def _offset(self) -> np.ndarray:
        yaw, pitch = math.radians(self.yaw), math.radians(self.pitch)
        return np.array([math.cos(pitch) * math.sin(yaw), math.sin(pitch), math.cos(pitch) * math.cos(yaw)])

    def eye(self) -> np.ndarray:
        return self.target + self._offset() * self.distance

    def basis(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Vecteurs (droite, haut, avant) de la caméra en coordonnées monde."""
        view = self.view_matrix()
        return view[0, :3], view[1, :3], -view[2, :3]

    def half_height(self) -> float:
        """Demi-hauteur visible au niveau de la cible (sert à l'orthographique)."""
        return self.distance * math.tan(math.radians(self.fov_y) / 2.0)

    # --- Matrices -----------------------------------------------------------
    def view_matrix(self) -> np.ndarray:
        return mathutils.look_at(self.eye(), self.target)

    def clip_planes(self) -> tuple[float, float]:
        if self.orthographic:
            return -max(self.distance * 50.0, 500.0), max(self.distance * 50.0, 500.0)
        return max(self.distance * 0.01, 0.01), max(self.distance * 100.0, 100.0)

    def projection_matrix(self, aspect: float) -> np.ndarray:
        near, far = self.clip_planes()
        if not self.orthographic:
            return mathutils.perspective(self.fov_y, aspect, near, far)
        top = self.half_height()
        right = top * max(aspect, 1e-6)
        m = np.eye(4)
        m[0, 0] = 1.0 / right
        m[1, 1] = 1.0 / top
        m[2, 2] = -2.0 / (far - near)
        m[2, 3] = -(far + near) / (far - near)
        return m

    # --- Navigation ---------------------------------------------------------
    def orbit(self, d_yaw: float, d_pitch: float) -> None:
        if self.mode == "free":
            self.look(d_yaw, d_pitch)
            return
        self.yaw = (self.yaw + d_yaw) % 360.0
        self.pitch = float(np.clip(self.pitch + d_pitch, -PITCH_LIMIT, PITCH_LIMIT))

    def look(self, d_yaw: float, d_pitch: float) -> None:
        """Regarder autour en gardant l'œil immobile (caméra libre)."""
        eye = self.eye()
        self.yaw = (self.yaw + d_yaw) % 360.0
        self.pitch = float(np.clip(self.pitch + d_pitch, -PITCH_LIMIT, PITCH_LIMIT))
        self.target = eye - self._offset() * self.distance

    def fly(self, forward: float, right: float, up: float) -> None:
        """Déplacement libre (mètres) dans le repère de la caméra."""
        r, _u, f = self.basis()
        self.target = self.target + f * forward + r * right + np.array([0.0, 1.0, 0.0]) * up

    def pan(self, dx_px: float, dy_px: float, viewport_height: int) -> None:
        """Déplace la vue pour que la scène suive le curseur (déplacement en pixels)."""
        world_per_px = 2.0 * self.half_height() / max(viewport_height, 1)
        right, up, _ = self.basis()
        self.target = self.target - right * dx_px * world_per_px + up * dy_px * world_per_px

    def zoom(self, steps: float) -> None:
        """Rapproche (steps > 0) ou éloigne (steps < 0) la caméra."""
        if self.mode == "free":
            self.fly(steps * max(self.distance * 0.15, 0.2), 0.0, 0.0)
            return
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

    def set_standard_view(self, name: str) -> None:
        self.set_view(*STANDARD_VIEWS[name])

    def reset(self) -> None:
        defaults = OrbitCamera()
        self.target, self.distance = defaults.target, defaults.distance
        self.yaw, self.pitch = defaults.yaw, defaults.pitch

    # --- Persistance --------------------------------------------------------
    def to_state(self) -> dict:
        return {
            "target": [float(v) for v in self.target],
            "distance": self.distance,
            "yaw": self.yaw,
            "pitch": self.pitch,
            "orthographic": self.orthographic,
            "mode": self.mode,
        }

    def apply_state(self, state: dict) -> None:
        try:
            self.target = np.asarray(state["target"], dtype=np.float64).reshape(3)
            self.distance = float(np.clip(float(state["distance"]), MIN_DISTANCE, MAX_DISTANCE))
            self.set_view(float(state["yaw"]), float(state["pitch"]))
            self.orthographic = bool(state.get("orthographic", False))
            self.mode = "free" if state.get("mode") == "free" else "orbit"
        except (KeyError, TypeError, ValueError):
            self.reset()
