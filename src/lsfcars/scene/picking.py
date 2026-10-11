"""Sélection d'objets par lancer de rayon (clic dans le viewport)."""

from __future__ import annotations

import math
from collections.abc import Iterable

import numpy as np

from lsfcars.scene.camera import OrbitCamera
from lsfcars.scene.mesh import MeshData


def ray_from_screen(
    camera: OrbitCamera, x: float, y: float, width: int, height: int
) -> tuple[np.ndarray, np.ndarray]:
    """Rayon monde (origine, direction normalisée) passant par le pixel (x, y)."""
    width, height = max(width, 1), max(height, 1)
    ndc_x = 2.0 * x / width - 1.0
    ndc_y = 1.0 - 2.0 * y / height
    right, up, forward = camera.basis()
    if getattr(camera, "orthographic", False):
        half_h = camera.half_height()
        offset = right * ndc_x * half_h * (width / height) + up * ndc_y * half_h
        origin = camera.eye() + offset - forward * camera.distance * 50.0
        return origin, forward / np.linalg.norm(forward)
    tan_half = math.tan(math.radians(camera.fov_y) / 2.0)
    direction = forward + right * ndc_x * tan_half * (width / height) + up * ndc_y * tan_half
    return camera.eye(), direction / np.linalg.norm(direction)


def _ray_hits_box(origin: np.ndarray, direction: np.ndarray, bmin, bmax) -> bool:
    with np.errstate(divide="ignore", invalid="ignore"):
        inv = 1.0 / direction
        t1 = (bmin - origin) * inv
        t2 = (bmax - origin) * inv
    t1 = np.nan_to_num(t1, nan=-np.inf)
    t2 = np.nan_to_num(t2, nan=np.inf)
    t_near = np.max(np.minimum(t1, t2))
    t_far = np.min(np.maximum(t1, t2))
    return bool(t_far >= max(t_near, 0.0))


def ray_mesh_distance(origin: np.ndarray, direction: np.ndarray, mesh: MeshData) -> float | None:
    """Distance paramétrique du premier triangle touché (Möller–Trumbore vectorisé)."""
    if mesh.triangle_count == 0:
        return None
    bmin, bmax = mesh.bounds
    if not _ray_hits_box(origin, direction, bmin.astype(float), bmax.astype(float)):
        return None
    tri = mesh.positions[mesh.indices].astype(np.float64)
    v0, e1, e2 = tri[:, 0], tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
    p = np.cross(direction, e2)
    det = np.einsum("ij,ij->i", e1, p)
    valid = np.abs(det) > 1e-12
    inv_det = np.zeros_like(det)
    inv_det[valid] = 1.0 / det[valid]
    s = origin - v0
    u = np.einsum("ij,ij->i", s, p) * inv_det
    q = np.cross(s, e1)
    v = (q @ direction) * inv_det
    t = np.einsum("ij,ij->i", e2, q) * inv_det
    hit = valid & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-9)
    if not np.any(hit):
        return None
    return float(t[hit].min())


def pick(
    origin: np.ndarray,
    direction: np.ndarray,
    candidates: Iterable[tuple[str, np.ndarray, list[MeshData]]],
) -> str | None:
    """Identifiant de l'objet le plus proche touché par le rayon.

    ``candidates`` : (identifiant, matrice modèle 4x4, maillages locaux).
    """
    best_id, best_t = None, math.inf
    for obj_id, model, meshes in candidates:
        try:
            inv = np.linalg.inv(model)
        except np.linalg.LinAlgError:
            continue
        local_origin = inv[:3, :3] @ origin + inv[:3, 3]
        local_dir = inv[:3, :3] @ direction  # non normalisé : t reste comparable en monde
        for mesh in meshes:
            t = ray_mesh_distance(local_origin, local_dir, mesh)
            if t is not None and t < best_t:
                best_id, best_t = obj_id, t
    return best_id
