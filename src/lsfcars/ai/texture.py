"""AI Texture Creator : textures et cartes PBR d'un modèle, avec l'origine de chaque carte.

Méthodes locales (déterministes, pas de réseau de neurones) :

- **Couleur de base** : projection des images de référence sur le modèle (vue la mieux
  orientée, test de visibilité par carte de profondeur), ou cuisson des couleurs par sommet
  d'un maillage généré. Les zones annotées « logo » sont masquées avant projection.
- **Normal map** : *dérivée* de la luminance de la couleur de base (approximation, pas une
  mesure du relief réel).
- **Roughness / Metallic** : cartes *par règles* (vitrages sombres brillants, carrosserie
  selon le préréglage choisi).
- **Ambient occlusion** : non générée localement.
- **Variations** : changement de teinte de la couleur dominante (carrosserie).

Les cartes fournies par un moteur (ex. Meshy avec PBR) sont conservées et étiquetées comme
telles : le rapport précise toujours l'origine de chaque carte.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from lsfcars.livery.raster import dilate_colors
from lsfcars.scene.editmesh import FACE, EditError, EditResult, face_normals
from lsfcars.scene.mesh import MeshData

PRESETS = {
    "paint_gloss": {"label": "Peinture brillante", "roughness": 0.25, "metallic": 0.0},
    "paint_metal": {"label": "Peinture métallisée", "roughness": 0.3, "metallic": 0.65},
    "matte": {"label": "Mat", "roughness": 0.8, "metallic": 0.0},
    "raw_metal": {"label": "Métal brut", "roughness": 0.45, "metallic": 1.0},
}
MAP_SOURCES = {
    "projection": "projetée depuis les références",
    "vertex": "cuite depuis les couleurs par sommet",
    "derived": "dérivée de la couleur (approximation)",
    "rules": "générée par règles (préréglage)",
    "provider": "fournie par le moteur",
    "none": "non générée",
}


# --- UV d'atlas -----------------------------------------------------------------------------------


def atlas_uv(mesh: MeshData, padding: float = 0.02) -> EditResult:
    """UV en atlas dans [0, 1] : six projections (±X, ±Y, ±Z) rangées dans une grille 3 × 2.

    Chaque face va dans la case de son axe dominant (avec signe) ; l'échelle est commune à toutes
    les cases (densité de texels uniforme). Des recouvrements restent possibles dans les creux
    (faces de même orientation à des profondeurs différentes) : le dépliage Blender est préférable
    quand il est disponible.
    """
    if not mesh.triangle_count:
        raise EditError("Le maillage ne contient aucune face.")
    normals = face_normals(mesh.positions, mesh.indices)
    axis = np.argmax(np.abs(normals), axis=1)
    positive = np.take_along_axis(normals, axis[:, None], axis=1)[:, 0] >= 0
    group = axis * 2 + (~positive).astype(int)  # 0:+X 1:-X 2:+Y 3:-Y 4:+Z 5:-Z
    corners = mesh.indices.reshape(-1).astype(np.int64)
    positions = mesh.positions[corners].astype(np.float64)
    face_group = np.repeat(group, 3)
    plane = {0: (2, 1), 1: (2, 1), 2: (0, 2), 3: (0, 2), 4: (0, 1), 5: (0, 1)}
    spans = [
        np.ptp(positions[face_group == g][:, [u, v]], axis=0)
        for g, (u, v) in plane.items()
        if (face_group == g).any()
    ]
    largest = max(float(np.max(spans)) if spans else 1.0, 1e-6)
    cell_w = (1.0 - 4 * padding) / 3.0
    cell_h = (1.0 - 3 * padding) / 2.0
    scale = min(cell_w, cell_h) / largest
    uv = np.zeros((len(corners), 2))
    for g, (u, v) in plane.items():
        rows = face_group == g
        if not rows.any():
            continue
        pts = positions[rows][:, [u, v]]
        local = (pts - pts.min(axis=0)) * scale
        if g in (1, 3, 5):  # faces opposées : miroir pour garder une lecture non inversée
            local[:, 0] = local[:, 0].max() - local[:, 0]
        col, row = g % 3, g // 3
        uv[rows] = np.array([padding + col * (cell_w + padding), padding + row * (cell_h + padding)]) + local
    colors = mesh.colors[corners] if mesh.colors is not None else np.full((len(corners), 4), 255, np.uint8)
    key = np.round(np.hstack([positions * 1e5, uv * 1e6])).astype(np.int64)
    _, first, inverse = np.unique(key, axis=0, return_index=True, return_inverse=True)
    result = MeshData(
        mesh.name,
        positions[first].astype(np.float32),
        inverse.reshape(-1, 3),
        mesh.normals[corners][first],
        colors[first],
        mesh.color,
        uv[first].astype(np.float32),
    )
    return EditResult(
        result,
        FACE,
        set(),
        ["UV d'atlas générées (6 projections) : des recouvrements restent possibles dans les creux."],
        uv_changed=True,
    )


# --- Rastérisation dans l'espace UV ---------------------------------------------------------------


def _lattice(steps: int) -> np.ndarray:
    points = [(i / steps, j / steps) for i in range(steps + 1) for j in range(steps + 1 - i)]
    return np.array([(a, b, 1.0 - a - b) for a, b in points])


# Triangles petits ou moyens : réseau d'échantillons barycentriques (pas ≤ 1 pixel), vectorisé
# par paquets ; les grands triangles sont rastérisés un par un.
LATTICES = ((2.0, _lattice(3)), (6.0, _lattice(8)))
LATTICE_SPAN = LATTICES[-1][0]
CHUNK = 20000


def _buckets(span: np.ndarray):  # type: ignore[no-untyped-def]
    """(indices des triangles, poids du réseau) par palier de taille, par paquets."""
    lower = -1.0
    for limit, weights in LATTICES:
        chosen = np.flatnonzero((span > lower) & (span <= limit))
        for start in range(0, len(chosen), CHUNK):
            yield chosen[start : start + CHUNK], weights
        lower = limit


@dataclass
class SurfaceMaps:
    size: int
    positions: np.ndarray  # (S, S, 3)
    normals: np.ndarray  # (S, S, 3)
    colors: np.ndarray  # (S, S, 4) couleurs par sommet interpolées
    coverage: np.ndarray  # (S, S) bool


def surface_maps(mesh: MeshData, size: int = 1024) -> SurfaceMaps:
    """Position, normale et couleur par texel (barycentriques) ; ligne 0 = v 1 (convention image)."""
    if mesh.uvs is None:
        raise EditError("Le modèle n'a pas d'UV : générez-les d'abord.")
    uv = mesh.uvs.astype(np.float64)
    px = np.stack([uv[:, 0] * size, (1.0 - uv[:, 1]) * size], axis=1)
    tri = mesh.indices.astype(np.int64)
    positions = np.zeros((size, size, 3), np.float32)
    normals = np.zeros((size, size, 3), np.float32)
    colors = np.zeros((size, size, 4), np.float32)
    coverage = np.zeros((size, size), bool)
    source_colors = mesh.colors if mesh.colors is not None else np.full((mesh.vertex_count, 4), 255, np.uint8)
    vcolors = source_colors.astype(np.float32)
    corners = px[tri]  # (M, 3, 2)
    lo = np.floor(corners.min(axis=1)).astype(int)
    hi = np.ceil(corners.max(axis=1)).astype(int)
    span = np.ptp(corners, axis=1).max(axis=1)
    small = span <= LATTICE_SPAN
    for chosen, weights in _buckets(span):
        t = tri[chosen]
        sample_px = np.einsum("kc,mcd->mkd", weights, corners[chosen]).reshape(-1, 2)
        cx = np.clip(sample_px[:, 0].astype(int), 0, size - 1)
        cy = np.clip(sample_px[:, 1].astype(int), 0, size - 1)
        positions[cy, cx] = np.einsum("kc,mcd->mkd", weights, mesh.positions[t]).reshape(-1, 3)
        normals[cy, cx] = np.einsum("kc,mcd->mkd", weights, mesh.normals[t]).reshape(-1, 3)
        colors[cy, cx] = np.einsum("kc,mcd->mkd", weights, vcolors[t]).reshape(-1, 4)
        coverage[cy, cx] = True
    for index in np.flatnonzero(~small):
        x0, y0 = np.clip(lo[index], 0, size - 1)
        x1, y1 = np.clip(hi[index], 0, size - 1)
        if x0 > x1 or y0 > y1:
            continue
        a, b, c = corners[index]
        d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(d) < 1e-12:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        w0 = ((b[1] - c[1]) * (gx - c[0]) + (c[0] - b[0]) * (gy - c[1])) / d
        w1 = ((c[1] - a[1]) * (gx - c[0]) + (a[0] - c[0]) * (gy - c[1])) / d
        w2 = 1 - w0 - w1
        inside = (w0 >= -1e-4) & (w1 >= -1e-4) & (w2 >= -1e-4)
        if not inside.any():
            continue
        weights = np.stack([w0[inside], w1[inside], w2[inside]], axis=1)
        ys, xs = np.nonzero(inside)
        ys, xs = ys + y0, xs + x0
        t = tri[index]
        positions[ys, xs] = weights @ mesh.positions[t]
        normals[ys, xs] = weights @ mesh.normals[t]
        colors[ys, xs] = weights @ vcolors[t]
        coverage[ys, xs] = True
    lengths = np.linalg.norm(normals, axis=-1, keepdims=True)
    normals = np.divide(normals, lengths, out=np.zeros_like(normals), where=lengths > 1e-9)
    return SurfaceMaps(size, positions, normals, colors, coverage)


def _finish(rgb: np.ndarray, coverage: np.ndarray, padding: int = 8) -> np.ndarray:
    alpha = np.full(rgb.shape[:2] + (1,), 255, np.uint8)
    rgba = np.concatenate([np.clip(rgb, 0, 255).astype(np.uint8), alpha], axis=-1)
    return dilate_colors(rgba, coverage, padding)


def bake_vertex_colors(maps: SurfaceMaps) -> np.ndarray:
    return _finish(maps.colors[..., :3], maps.coverage)


# --- Projection des références --------------------------------------------------------------------


@dataclass
class ViewImage:
    view: str  # left, right, front, back, top
    rgb: np.ndarray  # (h, w, 3) recadrée sur la silhouette
    mask: np.ndarray  # (h, w) bool
    front_left: bool = True  # profils : l'avant est à gauche de l'image


VIEW_DIRECTIONS = {  # direction de la caméra vers le véhicule (X droite, Y haut, avant vers -Z)
    "left": np.array([1.0, 0.0, 0.0]),
    "right": np.array([-1.0, 0.0, 0.0]),
    "front": np.array([0.0, 0.0, 1.0]),
    "back": np.array([0.0, 0.0, -1.0]),
    "top": np.array([0.0, -1.0, 0.0]),
}


def mask_annotations(rgb: np.ndarray, annotations: list[dict], kinds=("logo",)) -> tuple[np.ndarray, int]:  # type: ignore[no-untyped-def]
    """Remplit les rectangles annotés (coordonnées relatives) par la couleur médiane de leur pourtour."""
    out = rgb.copy()
    h, w = rgb.shape[:2]
    count = 0
    for note in annotations:
        if note.get("kind") not in kinds or len(note.get("rect", [])) != 4:
            continue
        x0, y0, x1, y1 = note["rect"]
        a, b = int(min(x0, x1) * w), int(max(x0, x1) * w)
        c, d = int(min(y0, y1) * h), int(max(y0, y1) * h)
        if b - a < 1 or d - c < 1:
            continue
        ring = max(2, int(0.15 * max(b - a, d - c)))
        outer = out[max(0, c - ring) : min(h, d + ring), max(0, a - ring) : min(w, b + ring)].reshape(-1, 3)
        out[c:d, a:b] = np.median(outer, axis=0)
        count += 1
    return out, count


def _project(view: str, positions: np.ndarray, lo: np.ndarray, hi: np.ndarray, front_left: bool):  # type: ignore[no-untyped-def]
    """Coordonnées (u, v) ∈ [0, 1] dans l'image recadrée d'une vue orthographique."""
    size = np.maximum(hi - lo, 1e-6)
    x = (positions[..., 0] - lo[0]) / size[0]  # 0 = gauche du véhicule
    y = (positions[..., 1] - lo[1]) / size[1]  # 0 = sol
    z = (positions[..., 2] - lo[2]) / size[2]  # 0 = avant
    if view in ("left", "right"):
        return (z if front_left else 1 - z), 1 - y
    if view == "front":
        return 1 - x, 1 - y
    if view == "back":
        return x, 1 - y
    return x, z  # dessus : avant en haut de l'image


def _depth_buffer(mesh: MeshData, view: str, lo, hi, shape, front_left: bool) -> np.ndarray:  # type: ignore[no-untyped-def]
    """Profondeur minimale par pixel de la vue (orthographique, même cadrage que la projection)."""
    h, w = shape
    direction = VIEW_DIRECTIONS[view]
    positions = mesh.positions.astype(np.float64)
    u, v = _project(view, positions, lo, hi, front_left)
    depth = positions @ direction
    buffer = np.full((h, w), np.inf)
    xs, ys = u * (w - 1), v * (h - 1)
    tri = mesh.indices.astype(np.int64)
    span = np.maximum(np.ptp(xs[tri], axis=1), np.ptp(ys[tri], axis=1))
    small = span <= LATTICE_SPAN
    for chosen, weights in _buckets(span):  # petits triangles : réseau d'échantillons vectorisé
        t = tri[chosen]
        cols = np.clip((xs[t] @ weights.T).round().astype(int), 0, w - 1).reshape(-1)
        rows = np.clip((ys[t] @ weights.T).round().astype(int), 0, h - 1).reshape(-1)
        np.minimum.at(buffer, (rows, cols), (depth[t] @ weights.T).reshape(-1))
    for t in tri[~small]:
        tx, ty, tz = xs[t], ys[t], depth[t]
        x0, x1 = int(max(0, np.floor(tx.min()))), int(min(w - 1, np.ceil(tx.max())))
        y0, y1 = int(max(0, np.floor(ty.min()))), int(min(h - 1, np.ceil(ty.max())))
        if x0 > x1 or y0 > y1:
            continue
        region = buffer[y0 : y1 + 1, x0 : x1 + 1]
        d = (ty[1] - ty[2]) * (tx[0] - tx[2]) + (tx[2] - tx[1]) * (ty[0] - ty[2])
        if abs(d) < 1e-12:
            np.minimum(region, tz.min(), out=region)
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        w0 = ((ty[1] - ty[2]) * (gx - tx[2]) + (tx[2] - tx[1]) * (gy - ty[2])) / d
        w1 = ((ty[2] - ty[0]) * (gx - tx[2]) + (tx[0] - tx[2]) * (gy - ty[2])) / d
        w2 = 1 - w0 - w1
        inside = (w0 >= -0.05) & (w1 >= -0.05) & (w2 >= -0.05)
        np.minimum(region, np.where(inside, w0 * tz[0] + w1 * tz[1] + w2 * tz[2], np.inf), out=region)
    return buffer


def project_references(
    mesh: MeshData, maps: SurfaceMaps, views: list[ViewImage], depth_size: int = 256
) -> tuple[np.ndarray, dict]:
    """Couleur de base projetée : pour chaque texel, la vue la mieux orientée et visible."""
    if not views:
        raise EditError("Aucune vue orthographique (profil, avant, arrière, dessus) à projeter.")
    lo = mesh.positions.min(axis=0).astype(np.float64)
    hi = mesh.positions.max(axis=0).astype(np.float64)
    extent = float((hi - lo).max())
    best = np.full(maps.coverage.shape, -np.inf)
    rgb = maps.colors[..., :3].copy()  # repli : couleurs par sommet
    available = {v.view: v for v in views}
    mirrored = []
    # un seul profil : l'autre flanc réutilise la même image (véhicule supposé symétrique)
    for side, other in (("left", "right"), ("right", "left")):
        if side in available and other not in available:
            available[other] = available[side]
            mirrored.append(other)
    used = []
    for name, view in available.items():
        direction = VIEW_DIRECTIONS[name]
        facing = -(maps.normals @ direction)
        u, v = _project(name, maps.positions, lo, hi, view.front_left)
        h, w = view.rgb.shape[:2]
        dh = max(8, int(depth_size * h / max(h, w)))
        dw = max(8, int(depth_size * w / max(h, w)))
        depth = _depth_buffer(mesh, name, lo, hi, (dh, dw), view.front_left)
        dx = np.clip((u * (dw - 1)).round().astype(int), 0, dw - 1)
        dy = np.clip((v * (dh - 1)).round().astype(int), 0, dh - 1)
        visible = (maps.positions @ direction) <= depth[dy, dx] + 0.03 * extent
        cx = np.clip((u * (w - 1)).round().astype(int), 0, w - 1)
        cy = np.clip((v * (h - 1)).round().astype(int), 0, h - 1)
        score = np.where(maps.coverage & visible & view.mask[cy, cx] & (facing > 0.15), facing, -np.inf)
        better = score > best
        rgb[better] = view.rgb[cy, cx][better]
        best[better] = score[better]
        if better.any():
            used.append(name)
    covered = maps.coverage & np.isfinite(best)
    stats = {
        "views": used,
        "mirrored_views": mirrored,
        "projected_ratio": round(float(covered.sum() / max(int(maps.coverage.sum()), 1)), 3),
    }
    return _finish(rgb, maps.coverage), stats


# --- Cartes dérivées ------------------------------------------------------------------------------


def normal_from_height(base: np.ndarray, strength: float = 2.0) -> np.ndarray:
    """Normal map tangente *approximative* dérivée de la luminance (relief non mesuré)."""
    luma = base[..., 0] * 0.299 + base[..., 1] * 0.587 + base[..., 2] * 0.114
    blurred = Image.fromarray(np.clip(luma, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.5))
    height = np.asarray(blurred, dtype=np.float32) / 255.0
    gx = np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)
    gy = np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)
    normal = np.stack([-gx * strength, gy * strength, np.ones_like(height)], axis=-1)
    normal /= np.linalg.norm(normal, axis=-1, keepdims=True)
    rgb = ((normal * 0.5 + 0.5) * 255).round().astype(np.uint8)
    return np.concatenate([rgb, np.full(rgb.shape[:2] + (1,), 255, np.uint8)], axis=-1)


def rule_maps(base: np.ndarray, preset: str = "paint_gloss") -> tuple[np.ndarray, np.ndarray]:
    """Roughness et metallic *par règles* : vitrages sombres brillants, reste selon le préréglage."""
    settings = PRESETS.get(preset, PRESETS["paint_gloss"])
    rgb = base[..., :3].astype(np.float32)
    luma = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
    saturation = rgb.max(axis=-1) - rgb.min(axis=-1)
    glass = (luma < 70) & (saturation < 50)
    rough = np.full(luma.shape, settings["roughness"], np.float32)
    metal = np.full(luma.shape, settings["metallic"], np.float32)
    rough[glass] = 0.05
    metal[glass] = 0.0

    def gray(values: np.ndarray) -> np.ndarray:
        return np.repeat((values * 255).round().astype(np.uint8)[..., None], 3, axis=-1)

    return gray(rough), gray(metal)


def dominant_mask(base: np.ndarray, tolerance: float = 48.0) -> tuple[np.ndarray, np.ndarray]:
    rgb = base[..., :3].reshape(-1, 3).astype(np.float32)
    sample = rgb[:: max(1, len(rgb) // 20000)]
    bright = sample[sample.max(axis=1) > 55]
    color = np.median(bright if len(bright) else sample, axis=0)
    distance = np.linalg.norm(base[..., :3].astype(np.float32) - color, axis=-1)
    return distance < tolerance, color


def _rgb_to_hsv(rgb: np.ndarray) -> np.ndarray:
    maxc, minc = rgb.max(axis=1), rgb.min(axis=1)
    delta = maxc - minc
    safe = np.maximum(delta, 1e-6)
    r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    hue = np.where(maxc == r, (g - b) / safe, np.where(maxc == g, 2.0 + (b - r) / safe, 4.0 + (r - g) / safe))
    hue = np.where(delta > 0, (hue / 6.0) % 1.0, 0.0)
    sat = np.where(maxc > 0, delta / np.maximum(maxc, 1e-6), 0.0)
    return np.stack([hue, sat, maxc], axis=1)


def _hsv_to_rgb(hsv: np.ndarray) -> np.ndarray:
    h, s, v = hsv[:, 0], hsv[:, 1], hsv[:, 2]
    i = np.floor(h * 6).astype(int) % 6
    f = h * 6 - np.floor(h * 6)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    choices = np.stack(
        [np.stack(c, axis=1) for c in ((v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q))],
        axis=0,
    )
    return choices[i, np.arange(len(i))]


def variation(base: np.ndarray, hue_shift: float, saturation: float = 1.0) -> np.ndarray:
    """Variante de teinte appliquée à la couleur dominante (carrosserie), le reste intact."""
    mask, _color = dominant_mask(base)
    out = base.copy()
    flat = base[..., :3][mask].astype(np.float32) / 255.0
    if len(flat):
        hsv = _rgb_to_hsv(flat)
        hsv[:, 0] = (hsv[:, 0] + hue_shift) % 1.0
        if hsv[:, 1].max() < 0.05:  # teinte neutre (gris, blanc) : saturation minimale pour colorer
            hsv[:, 1] = 0.5
        hsv[:, 1] = np.clip(hsv[:, 1] * saturation, 0, 1)
        out[..., :3][mask] = np.clip(_hsv_to_rgb(hsv) * 255 + 0.5, 0, 255).astype(np.uint8)
    return out


def save_png(array: np.ndarray, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(array).save(path, optimize=True)
    return path
