"""Peinture raster : pinceau, gomme, remplissage, dégradé, flou, débordement des îlots.

Un coup de pinceau accumule un **masque de trait** (maximum des empreintes) et recompose les
pixels à partir de l'état d'origine : l'opacité du trait est donc respectée sans surcharge
aux croisements, comme dans les éditeurs professionnels. Seules les tuiles touchées sont
copiées ; à la fin du trait, elles deviennent des commandes ``PatchImage`` (historique léger).
Pur numpy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from lsfcars.scene.commands import PatchImage
from lsfcars.scene.images import ImageBuffer

TILE = 128


@dataclass
class BrushSettings:
    size: float = 24.0  # diamètre en pixels de texture
    opacity: float = 1.0
    hardness: float = 0.8
    spacing: float = 0.15  # fraction du diamètre entre deux empreintes
    pressure_size: bool = True
    pressure_opacity: bool = False
    eraser: bool = False


def dab_mask(cx: float, cy: float, radius: float, hardness: float) -> tuple[int, int, np.ndarray]:
    """Empreinte circulaire antialiasée : (x0, y0, alpha float32)."""
    radius = max(float(radius), 0.5)
    x0, y0 = math.floor(cx - radius - 1), math.floor(cy - radius - 1)
    x1, y1 = math.ceil(cx + radius + 1), math.ceil(cy + radius + 1)
    ys, xs = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    d = np.sqrt((xs + 0.5 - cx) ** 2 + (ys + 0.5 - cy) ** 2)
    hard = max(0.0, min(1.0, float(hardness))) * radius
    soft = np.clip((radius - d) / max(radius - hard, 1.0), 0.0, 1.0)
    alpha = soft * soft * (3.0 - 2.0 * soft)  # lissage
    return x0, y0, alpha.astype(np.float32)


class StrokeEngine:
    """Trait en cours sur une image RGBA ou un masque (niveaux de gris)."""

    def __init__(
        self,
        image: ImageBuffer,
        key: str,
        color: tuple[int, int, int, int],
        settings: BrushSettings,
        selection: np.ndarray | None = None,
        lock_alpha: bool = False,
    ) -> None:
        self.image = image
        self.key = key
        self.target = image.array
        self.mono = self.target.ndim == 2
        self.color = np.asarray(color, np.float32)
        self.settings = settings
        self.selection = selection
        self.lock_alpha = lock_alpha
        self.height, self.width = self.target.shape[:2]
        self._orig: dict[tuple[int, int], np.ndarray] = {}
        self._mask: dict[tuple[int, int], np.ndarray] = {}
        self._last: tuple[float, float] | None = None
        self._carry = 0.0
        self.dirty: tuple[int, int, int, int] | None = None
        self.dabs = 0

    # --- Empreintes ----------------------------------------------------------------------
    def apply(self, x0: int, y0: int, alpha: np.ndarray) -> None:
        """Ajoute une empreinte (masque [0, 1]) au trait, coin haut-gauche en (x0, y0)."""
        h, w = alpha.shape
        cx0, cy0 = max(x0, 0), max(y0, 0)
        cx1, cy1 = min(x0 + w, self.width), min(y0 + h, self.height)
        if cx0 >= cx1 or cy0 >= cy1:
            return
        for ty in range(cy0 // TILE, (cy1 - 1) // TILE + 1):
            for tx in range(cx0 // TILE, (cx1 - 1) // TILE + 1):
                key = (tx, ty)
                bx0, by0 = tx * TILE, ty * TILE
                bx1, by1 = min(bx0 + TILE, self.width), min(by0 + TILE, self.height)
                if key not in self._orig:
                    self._orig[key] = self.target[by0:by1, bx0:bx1].copy()
                    self._mask[key] = np.zeros((by1 - by0, bx1 - bx0), np.float32)
                sx0, sy0 = max(cx0, bx0), max(cy0, by0)
                sx1, sy1 = min(cx1, bx1), min(cy1, by1)
                if sx0 >= sx1 or sy0 >= sy1:
                    continue
                tile_mask = self._mask[key]
                region = tile_mask[sy0 - by0 : sy1 - by0, sx0 - bx0 : sx1 - bx0]
                np.maximum(region, alpha[sy0 - y0 : sy1 - y0, sx0 - x0 : sx1 - x0], out=region)
                self._recompose(key, sx0, sy0, sx1, sy1)
        self._grow_dirty(cx0, cy0, cx1, cy1)
        self.image.touch()
        self.dabs += 1

    def _recompose(self, key: tuple[int, int], x0: int, y0: int, x1: int, y1: int) -> None:
        bx0, by0 = key[0] * TILE, key[1] * TILE
        local = (slice(y0 - by0, y1 - by0), slice(x0 - bx0, x1 - bx0))
        orig = self._orig[key][local].astype(np.float32)
        m = self._mask[key][local] * float(self.settings.opacity)
        if self.selection is not None:
            m = m * (self.selection[y0:y1, x0:x1].astype(np.float32) / 255.0)
        out = self.target[y0:y1, x0:x1]
        if self.mono:
            value = (
                255.0 if self.settings.eraser else float(self.color[:3] @ np.array([0.2126, 0.7152, 0.0722]))
            )
            out[...] = np.clip(orig * (1 - m) + value * m + 0.5, 0, 255).astype(np.uint8)
            return
        m = m * (self.color[3] / 255.0)
        o_a = orig[..., 3] / 255.0
        if self.settings.eraser:
            out[..., :3] = orig[..., :3].astype(np.uint8)
            out[..., 3] = np.clip(orig[..., 3] * (1 - m) + 0.5, 0, 255).astype(np.uint8)
            return
        if self.lock_alpha:
            rgb = orig[..., :3] * (1 - m[..., None]) + self.color[:3] * m[..., None]
            out[..., :3] = np.clip(rgb + 0.5, 0, 255).astype(np.uint8)
            out[..., 3] = orig[..., 3].astype(np.uint8)
            return
        a_out = m + o_a * (1 - m)
        rgb = orig[..., :3] * (o_a * (1 - m))[..., None] + self.color[:3] * m[..., None]
        rgb = np.where(a_out[..., None] > 1e-6, rgb / np.maximum(a_out, 1e-6)[..., None], 0.0)
        out[..., :3] = np.clip(rgb + 0.5, 0, 255).astype(np.uint8)
        out[..., 3] = np.clip(a_out * 255.0 + 0.5, 0, 255).astype(np.uint8)

    def _grow_dirty(self, x0: int, y0: int, x1: int, y1: int) -> None:
        if self.dirty is None:
            self.dirty = (x0, y0, x1, y1)
        else:
            a = self.dirty
            self.dirty = (min(a[0], x0), min(a[1], y0), max(a[2], x1), max(a[3], y1))

    def take_dirty(self) -> tuple[int, int, int, int] | None:
        dirty, self.dirty = self.dirty, None
        return dirty

    # --- Trait 2D ---------------------------------------------------------------------------
    def _radius(self, pressure: float) -> float:
        scale = pressure if self.settings.pressure_size else 1.0
        return max(0.5, self.settings.size * 0.5 * max(scale, 0.05))

    def dab(self, x: float, y: float, pressure: float = 1.0) -> None:
        x0, y0, alpha = dab_mask(x, y, self._radius(pressure), self.settings.hardness)
        if self.settings.pressure_opacity:
            alpha = alpha * max(0.0, min(1.0, pressure))
        self.apply(x0, y0, alpha)

    def stroke_to(self, x: float, y: float, pressure: float = 1.0) -> None:
        """Prolonge le trait jusqu'à (x, y) avec un espacement régulier des empreintes."""
        if self._last is None:
            self._last = (x, y)
            self.dab(x, y, pressure)
            return
        lx, ly = self._last
        distance = math.hypot(x - lx, y - ly)
        step = max(1.0, self.settings.spacing * self._radius(pressure) * 2.0)
        travelled = step - self._carry
        while travelled <= distance:
            t = travelled / distance
            self.dab(lx + (x - lx) * t, ly + (y - ly) * t, pressure)
            travelled += step
        self._carry = distance - (travelled - step)
        self._last = (x, y)

    # --- Fin -----------------------------------------------------------------------------
    def commands(self, label: str = "Peinture") -> list[PatchImage]:
        """Tuiles modifiées → commandes (déjà appliquées : à empiler sans réexécution)."""
        result = []
        for (tx, ty), orig in self._orig.items():
            x0, y0 = tx * TILE, ty * TILE
            h, w = orig.shape[:2]
            after = self.target[y0 : y0 + h, x0 : x0 + w].copy()
            if not np.array_equal(after, orig):
                result.append(PatchImage(self.key, x0, y0, orig, after, label))
        return result

    def cancel(self) -> None:
        for (tx, ty), orig in self._orig.items():
            h, w = orig.shape[:2]
            self.target[ty * TILE : ty * TILE + h, tx * TILE : tx * TILE + w] = orig
        self._orig.clear()
        self._mask.clear()
        self.image.touch()


# --- Remplissage -------------------------------------------------------------------------------


def similar_mask(rgba: np.ndarray, x: int, y: int, tolerance: int) -> np.ndarray:
    target = rgba[y, x].astype(np.int16)
    return np.abs(rgba.astype(np.int16) - target).max(axis=-1) <= int(tolerance)


def connected_region(mask: np.ndarray, x: int, y: int) -> np.ndarray:
    """Composante 4-connexe de ``mask`` contenant (x, y), par segments de lignes."""
    h, w = mask.shape
    result = np.zeros_like(mask, dtype=bool)
    if not (0 <= x < w and 0 <= y < h) or not mask[y, x]:
        return result
    runs_cache: dict[int, list[tuple[int, int]]] = {}

    def runs(row: int) -> list[tuple[int, int]]:
        if row not in runs_cache:
            line = np.concatenate([[False], mask[row], [False]]).astype(np.int8)
            edges = np.flatnonzero(np.diff(line))
            runs_cache[row] = list(zip(edges[0::2], edges[1::2], strict=True))
        return runs_cache[row]

    seen: set[tuple[int, int]] = set()
    start = next((r for r in runs(y) if r[0] <= x < r[1]), None)
    stack = [(y, start)] if start else []
    while stack:
        row, (a, b) = stack.pop()
        if (row, a) in seen:
            continue
        seen.add((row, a))
        result[row, a:b] = True
        for nr in (row - 1, row + 1):
            if 0 <= nr < h:
                for c, d in runs(nr):
                    if c < b and d > a and (nr, c) not in seen:
                        stack.append((nr, (c, d)))
    return result


def fill_region(
    rgba: np.ndarray, region: np.ndarray, color: tuple[int, int, int, int], opacity: float = 1.0
) -> tuple[int, int, int, int] | None:
    """Peint ``color`` sur la région (booléen ou [0, 255]) ; retourne le rectangle modifié."""
    ys, xs = np.nonzero(region)
    if not len(xs):
        return None
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
    sub = rgba[y0:y1, x0:x1]
    m = region[y0:y1, x0:x1].astype(np.float32)
    if region.dtype != bool:
        m /= 255.0
    m *= float(opacity) * color[3] / 255.0
    paint_over(sub, np.asarray(color[:3], np.float32), m)
    return (x0, y0, x1, y1)


def paint_over(sub: np.ndarray, rgb: np.ndarray, m: np.ndarray) -> None:
    """« Normal » en alpha non prémultiplié : couleur unie (ou image) ``rgb`` avec couverture ``m``."""
    orig = sub.astype(np.float32)
    o_a = orig[..., 3] / 255.0
    a_out = m + o_a * (1 - m)
    color = rgb if rgb.ndim == 3 else rgb[None, None, :]
    out = orig[..., :3] * (o_a * (1 - m))[..., None] + color * m[..., None]
    out = np.where(a_out[..., None] > 1e-6, out / np.maximum(a_out, 1e-6)[..., None], 0.0)
    sub[..., :3] = np.clip(out + 0.5, 0, 255).astype(np.uint8)
    sub[..., 3] = np.clip(a_out * 255.0 + 0.5, 0, 255).astype(np.uint8)


def gradient(
    width: int,
    height: int,
    p0: tuple[float, float],
    p1: tuple[float, float],
    c0: tuple[int, int, int, int],
    c1: tuple[int, int, int, int],
    kind: str = "linear",
    box: tuple[int, int, int, int] | None = None,
) -> np.ndarray:
    """Dégradé RGBA (H, W, 4) uint8 ; ``box`` limite le calcul à un rectangle (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = box or (0, 0, width, height)
    ys, xs = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    length2 = max(dx * dx + dy * dy, 1e-6)
    if kind == "radial":
        t = np.sqrt((xs + 0.5 - p0[0]) ** 2 + (ys + 0.5 - p0[1]) ** 2) / math.sqrt(length2)
    else:
        t = ((xs + 0.5 - p0[0]) * dx + (ys + 0.5 - p0[1]) * dy) / length2
    t = np.clip(t, 0.0, 1.0)[..., None]
    a, b = np.asarray(c0, np.float32), np.asarray(c1, np.float32)
    return np.clip(a + (b - a) * t + 0.5, 0, 255).astype(np.uint8)


def box_blur(alpha: np.ndarray, radius: int) -> np.ndarray:
    """Flou séparable (3 passes ≈ gaussien) d'un canal float32."""
    radius = int(radius)
    if radius <= 0:
        return alpha
    out = alpha.astype(np.float32)
    size = 2 * radius + 1
    for _ in range(3):
        for axis in (0, 1):
            pad = [(0, 0), (0, 0)]
            pad[axis] = (radius + 1, radius)
            cumulative = np.cumsum(np.pad(out, pad, mode="edge"), axis=axis, dtype=np.float64)
            if axis == 0:
                out = ((cumulative[size:] - cumulative[:-size]) / size).astype(np.float32)
            else:
                out = ((cumulative[:, size:] - cumulative[:, :-size]) / size).astype(np.float32)
    return out


def dilate_colors(rgba: np.ndarray, coverage: np.ndarray, iterations: int) -> np.ndarray:
    """Débordement des îlots UV : les couleurs couvertes s'étendent sur ``iterations`` pixels.

    Évite les liserés aux coutures quand la texture est filtrée ou réduite (mipmaps).
    L'alpha n'est pas modifié.
    """
    out = rgba.copy()
    filled = coverage.copy()
    rgb = out[..., :3].astype(np.float32)
    for _ in range(int(iterations)):
        if filled.all():
            break
        acc = np.zeros_like(rgb)
        count = np.zeros(filled.shape, np.float32)
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            shifted = np.roll(filled, (dy, dx), axis=(0, 1))
            acc += np.roll(rgb, (dy, dx), axis=(0, 1)) * shifted[..., None]
            count += shifted
        grow = (~filled) & (count > 0)
        rgb[grow] = acc[grow] / count[grow][:, None]
        filled |= grow
    out[..., :3] = np.clip(rgb + 0.5, 0, 255).astype(np.uint8)
    return out
