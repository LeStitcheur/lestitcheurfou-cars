"""Bandes 3D et zones de carrosserie, calculées à partir de la position réelle de chaque texel.

Une bande « longitudinale à 0,55 m du sol » est définie dans l'espace du véhicule, pas dans
celui de la texture : elle suit la carrosserie quel que soit le dépliage UV, se raccorde aux
coutures et reste **symétrique par construction** (gauche et droite sont deux régions de la
même définition 3D). Zones : flancs, gauche, droite, capot, toit, coffre, avant, arrière.
Pur numpy ; le rendu se fait à la résolution des cartes de surface puis est mis à l'échelle.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image

from lsfcars.livery.model import rgba
from lsfcars.livery.surface import LiverySurface

ZONES = {
    "body": "Toute la carrosserie",
    "sides": "Flancs (gauche et droite)",
    "top": "Dessus (capot, toit, coffre)",
    "left": "Flanc gauche",
    "right": "Flanc droit",
    "hood": "Capot",
    "roof": "Toit",
    "trunk": "Coffre",
    "front": "Face avant",
    "rear": "Face arrière",
}
ORIENTATIONS = {
    "longitudinal": "Longitudinale (le long du véhicule)",
    "vertical": "Verticale (transversale)",
    "diagonal": "Diagonale",
}
PATTERNS = {
    "solid": "Unie",
    "stripes": "Rayures",
    "checker": "Damier (type Battenburg)",
    "chevron": "Chevrons",
    "dashed": "Tirets",
    "reflective": "Réfléchissante (simulée)",
}


def _cached_coords(surface: LiverySurface, resolution: int) -> dict:
    maps = surface.maps(resolution)
    key = ("coords", maps.resolution)
    if key not in surface.cache:
        surface.cache[key] = vehicle_coords(surface, maps.position)
    return surface.cache[key]


def vehicle_coords(surface: LiverySurface, position: np.ndarray) -> dict:
    """Coordonnées véhicule (m) : longitudinale (+ avant), hauteur (0 = point bas), latérale (+ droite)."""
    frame = surface.frame
    bmin, bmax = surface.bounds
    center = (bmin + bmax) / 2
    up = np.asarray(frame["up"], np.float64)
    forward = np.asarray(frame["forward"], np.float64)
    right = np.asarray(frame["right"], np.float64)
    corners = np.array(
        [[x, y, z] for x in (bmin[0], bmax[0]) for y in (bmin[1], bmax[1]) for z in (bmin[2], bmax[2])]
    )
    heights = (corners - center) @ up
    low = float(heights.min())
    rel = position.astype(np.float64) - center
    return {
        "lon": rel @ forward,
        "height": rel @ up - low,
        "lat": rel @ right,
        "total_height": float(heights.max() - low),
        "half_length": float(np.abs((corners - center) @ forward).max()),
        "half_width": float(np.abs((corners - center) @ right).max()),
    }


def zone_mask(surface: LiverySurface, zone: str, resolution: int = 1024) -> np.ndarray:
    """Masque booléen de la zone à la résolution des cartes de surface (en cache)."""
    maps = surface.maps(resolution)
    key = ("zone", zone, maps.resolution)
    if key in surface.cache:
        return surface.cache[key]
    surface.cache[key] = mask = _zone_mask(surface, zone, maps)
    return mask


def _zone_mask(surface: LiverySurface, zone: str, maps) -> np.ndarray:  # type: ignore[no-untyped-def]
    covered = maps.coverage
    if zone == "body":
        return covered
    n = maps.normal.astype(np.float64)
    frame = surface.frame
    n_up = n @ np.asarray(frame["up"], np.float64)
    n_fwd = n @ np.asarray(frame["forward"], np.float64)
    n_right = n @ np.asarray(frame["right"], np.float64)
    coords = _cached_coords(surface, maps.resolution[0])
    lon = coords["lon"] / max(coords["half_length"], 1e-6)
    height = coords["height"] / max(coords["total_height"], 1e-6)
    top = n_up > 0.55
    masks = {
        "sides": np.abs(n_right) > 0.55,
        "top": top,
        "left": n_right < -0.55,
        "right": n_right > 0.55,
        "hood": top & (lon > 0.25) & (height < 0.85),
        "roof": top & (height >= 0.85),
        "trunk": top & (lon < -0.25) & (height < 0.85),
        "front": n_fwd > 0.55,
        "rear": n_fwd < -0.55,
    }
    return covered & masks.get(zone, covered)


def zone_center(surface: LiverySurface, zone: str) -> tuple[np.ndarray, np.ndarray] | None:
    """Point 3D central et normale moyenne d'une zone (placement des marquages)."""
    maps = surface.maps(512)
    mask = zone_mask(surface, zone, 512)
    if not mask.any():
        return None
    points = maps.position[mask].astype(np.float64)
    normals = maps.normal[mask].astype(np.float64)
    normal = normals.mean(axis=0)
    normal /= max(np.linalg.norm(normal), 1e-9)
    nearest = points[np.argmin(np.linalg.norm(points - points.mean(axis=0), axis=1))]
    return nearest, normal


def band_rgba(surface: LiverySurface, params: dict, resolution: int = 2048) -> np.ndarray:
    """Bande 3D rendue à la taille de la texture (H, W, 4) uint8."""
    maps = surface.maps(resolution)
    w, h = maps.resolution
    mask = zone_mask(surface, params.get("zone", "sides"), resolution)
    coords = _cached_coords(surface, resolution)
    n_up = maps.normal.astype(np.float64) @ np.asarray(surface.frame["up"], np.float64)
    width = max(float(params.get("width", 0.15)), 1e-3)
    orientation = params.get("orientation", "longitudinal")
    if orientation == "vertical":
        d = coords["lon"] - float(params.get("center_lon", 0.0))
        along = coords["height"]
    elif orientation == "diagonal":
        angle = math.radians(float(params.get("angle", 30.0)))
        d = (coords["lon"] - float(params.get("center_lon", 0.0))) * math.cos(angle) + (
            coords["height"] - float(params.get("center_height", 0.6))
        ) * math.sin(angle)
        along = coords["lon"] * -math.sin(angle) + coords["height"] * math.cos(angle)
    else:  # longitudinale : hauteur sur les flancs, décalage latéral sur les surfaces du dessus
        side_d = coords["height"] - float(params.get("center_height", 0.6))
        top_d = coords["lat"] - float(params.get("lateral_offset", 0.0))
        d = np.where(n_up > 0.55, top_d, side_d)
        along = coords["lon"]
    density = max(surface.texel_density() * w / max(surface.width, 1), 1e-3)  # pixels par mètre
    alpha = np.clip((width / 2 - np.abs(d)) * density + 0.5, 0.0, 1.0) * mask
    side = params.get("side", "both")
    if side in ("left", "right"):
        lat = coords["lat"]
        alpha *= (lat < 0) if side == "left" else (lat > 0)
    c1 = np.asarray(rgba(params.get("color", "#2563EB")), np.float32)
    c2 = np.asarray(rgba(params.get("color2", "#F3F6FC")), np.float32)
    period = max(float(params.get("period", 0.3)), 0.01)
    pattern = params.get("pattern", "solid")
    if pattern == "stripes":
        second = (np.floor(along / period) % 2) == 1
    elif pattern == "checker":
        rows = np.floor((d + width / 2) / max(width / 2, 1e-6))
        second = ((np.floor(along / period) + rows) % 2) == 1
    elif pattern == "chevron":
        second = (np.floor((along + np.abs(coords["lat"]) + np.abs(d)) / period) % 2) == 1
    elif pattern == "dashed":
        second = np.zeros_like(alpha, bool)
        alpha = alpha * ((np.floor(along / period) % 2) == 0)
    else:
        second = np.zeros_like(alpha, bool)
    color = np.where(second[..., None], c2, c1)
    if pattern == "reflective":  # micro-hachures claires : rendu visuel seulement (aucune rétroréflexion)
        sheen = ((np.floor((along + d) / 0.025) % 3) == 0)[..., None]
        color = np.where(sheen, np.minimum(color * 1.25 + 20, 255), color)
    out = np.zeros((h, w, 4), np.float32)
    out[..., :3] = color[..., :3]
    out[..., 3] = alpha * color[..., 3]
    out = np.clip(out + 0.5, 0, 255).astype(np.uint8)
    if (w, h) != (surface.width, surface.height):
        out = np.array(Image.fromarray(out, "RGBA").resize((surface.width, surface.height), Image.BILINEAR))
    return out
