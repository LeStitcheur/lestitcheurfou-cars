"""Composition des calques en une texture (H, W, 4), avec mises à jour partielles.

- Chaque calque non raster (vecteur, texte, image, bande 3D) est rendu une fois puis mis en
  cache tant que ses paramètres ne changent pas.
- Seule la région touchée est recomposée : rectangle d'un coup de pinceau, ancien et nouveau
  rectangle d'un élément déplacé… La texture complète n'est recalculée qu'au premier rendu ou
  après un changement global (taille, mode, texture d'origine).
- Le résultat est exactement celui envoyé au viewport et exporté : ce que l'on voit est ce que
  l'on exporte.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
from PIL import Image

from lsfcars.core.logging_setup import get_logger
from lsfcars.livery import bands, blend, render2d
from lsfcars.livery.model import Layer, LiveryDocument, LiveryVariant

log = get_logger(__name__)

Rect = tuple[int, int, int, int]


def union(a: Rect | None, b: Rect | None) -> Rect | None:
    if a is None:
        return b
    if b is None:
        return a
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def clip(rect: Rect | None, width: int, height: int) -> Rect | None:
    if rect is None:
        return None
    x0, y0 = max(int(rect[0]), 0), max(int(rect[1]), 0)
    x1, y1 = min(int(rect[2]), width), min(int(rect[3]), height)
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def _flatten(layers: list[Layer], depth: int = 0):  # type: ignore[no-untyped-def]
    """(calque, profondeur) dans l'ordre de composition, groupes développés."""
    for layer in layers:
        yield layer, depth
        if layer.children:
            yield from _flatten(layer.children, depth + 1)


class Compositor:
    def __init__(self, scene, project_dir: Path | None = None) -> None:  # type: ignore[no-untyped-def]
        self.scene = scene
        self.project_dir = project_dir
        self.surface = None  # LiverySurface : nécessaire aux bandes 3D
        self.result: np.ndarray | None = None
        self.last_ms = 0.0
        self.last_region: Rect | None = None
        self.warnings: list[str] = []
        self._crops: dict[str, tuple[str, tuple[int, int, np.ndarray] | None]] = {}
        self._previous: dict[str, tuple[str, Rect | None]] = {}
        self._versions: dict[str, int] = {}
        self._global = ""
        self._base: tuple[tuple, np.ndarray | None] | None = None

    def reset(self) -> None:
        self.result = None
        self._previous.clear()

    def forget(self, layer_id: str | None = None) -> None:
        """Vide le cache de rendu (d'un calque ou de tous, ex. surface 3D modifiée)."""
        if layer_id is None:
            self._crops.clear()
            self.reset()
        else:
            self._crops.pop(layer_id, None)

    # --- Sources ----------------------------------------------------------------------------
    def base(self, doc: LiveryDocument) -> np.ndarray | None:
        """Texture d'origine à la taille du document (jamais modifiée)."""
        if not doc.base_texture or self.project_dir is None:
            return None
        path = self.project_dir / doc.base_texture
        try:
            stamp = path.stat().st_mtime
        except OSError:
            self.warnings.append(f"Texture d'origine introuvable : {doc.base_texture}")
            return None
        key = (str(path), stamp, doc.width, doc.height)
        if self._base is None or self._base[0] != key:
            try:
                with Image.open(path) as image:
                    converted = image.convert("RGBA")
                    if converted.size != (doc.width, doc.height):
                        converted = converted.resize((doc.width, doc.height), Image.LANCZOS)
                    self._base = (key, np.array(converted, np.uint8))
            except OSError as exc:
                log.warning("Texture d'origine illisible : %s", exc)
                self._base = (key, None)
        return self._base[1]

    def crop(self, layer: Layer, doc: LiveryDocument) -> tuple[int, int, np.ndarray] | None:
        """Rendu (en cache) d'un calque vectoriel, texte, image ou bande."""
        signature = self._content_signature(layer, doc)
        cached = self._crops.get(layer.id)
        if cached is not None and cached[0] == signature:
            return cached[1]
        result = None
        try:
            if layer.kind == "vector":
                result = render2d.render_vector(layer, doc.width, doc.height)
            elif layer.kind == "text":
                result = render2d.render_text(layer, doc.width, doc.height, self.scene.blobs)
            elif layer.kind == "image":
                result = render2d.render_image(layer, doc.width, doc.height, self.scene.blobs)
            elif layer.kind == "band" and self.surface is not None and self.surface.triangle_count:
                result = (0, 0, bands.band_rgba(self.surface, layer.params))
        except Exception as exc:  # noqa: BLE001 (un calque défectueux ne bloque pas la composition)
            log.warning("Rendu du calque « %s » impossible : %s", layer.name, exc)
        self._crops[layer.id] = (signature, result)
        return result

    def _content_signature(self, layer: Layer, doc: LiveryDocument) -> str:
        extra = [doc.width, doc.height]
        if layer.kind == "band" and self.surface is not None:
            extra.append(id(self.surface))
        return json.dumps([layer.kind, layer.params, extra], sort_keys=True, default=str)

    def _bounds(self, layer: Layer, doc: LiveryDocument) -> Rect | None:
        if layer.kind in ("raster", "band"):
            return (0, 0, doc.width, doc.height)
        if layer.kind == "group":
            rect = None
            for child in layer.children:
                rect = union(rect, self._bounds(child, doc))
            return rect
        crop = self.crop(layer, doc)
        if crop is None:
            return None
        x0, y0, data = crop
        return (x0, y0, x0 + data.shape[1], y0 + data.shape[0])

    # --- Mise à jour ---------------------------------------------------------------------------
    def stack(self, doc: LiveryDocument, variant: LiveryVariant | None) -> list[Layer]:
        if variant is None:
            return []
        return (list(doc.shared_layers) if variant.use_shared else []) + list(variant.layers)

    def update(
        self, doc: LiveryDocument, variant: LiveryVariant | None, rects: list[Rect] | None = None
    ) -> Rect | None:
        """Met à jour la texture ; retourne la région recomposée (None : rien à faire).

        ``rects`` : régions de pixels modifiées connues (coups de pinceau, annulations).
        """
        started = time.perf_counter()
        self.warnings = []
        width, height = doc.width, doc.height
        global_sig = json.dumps(
            [
                width,
                height,
                doc.mode,
                doc.base_texture,
                doc.blend_space,
                variant.id if variant else None,
                variant.base_visible if variant else True,
                variant.use_shared if variant else True,
            ]
        )
        full = self.result is None or self.result.shape[:2] != (height, width) or global_sig != self._global
        layers = self.stack(doc, variant)
        current: dict[str, tuple[str, Rect | None]] = {}
        region: Rect | None = None
        for index, (layer, depth) in enumerate(_flatten(layers)):
            sig = json.dumps(
                [
                    index,
                    depth,
                    layer.kind,
                    layer.visible,
                    layer.opacity,
                    layer.blend,
                    layer.image,
                    layer.mask,
                    layer.mask_enabled,
                    layer.params,
                    [c.id for c in layer.children],
                ],
                sort_keys=True,
                default=str,
            )
            previous = self._previous.get(layer.id)
            changed = previous is None or previous[0] != sig
            bounds = self._bounds(layer, doc) if (changed or full) else previous[1]
            current[layer.id] = (sig, bounds)
            if not full and changed:
                region = union(region, union(previous[1] if previous else None, bounds))
            for key in (layer.image, layer.mask):
                if key and key in self.scene.images:
                    version = self.scene.images[key].version
                    if self._versions.get(key) != version:
                        self._versions[key] = version
                        if not full and not rects:  # pixels modifiés sans région connue
                            region = union(region, bounds)
        for removed in set(self._previous) - set(current):
            region = union(region, self._previous[removed][1])
        self._previous = current
        self._global = global_sig
        if full:
            self.result = np.zeros((height, width, 4), np.uint8)
            region = (0, 0, width, height)
        else:
            for rect in rects or []:
                region = union(region, rect)
        region = clip(region, width, height)
        if region is None:
            return None
        self._compose(doc, variant, layers, region)
        self.last_region = region
        self.last_ms = (time.perf_counter() - started) * 1000
        return region

    def render_full(self, doc: LiveryDocument, variant: LiveryVariant | None) -> np.ndarray:
        """Composition complète indépendante (export, comparaison de variantes)."""
        out = np.zeros((doc.height, doc.width, 4), np.uint8)
        saved, self.result = self.result, out
        try:
            self._compose(doc, variant, self.stack(doc, variant), (0, 0, doc.width, doc.height))
        finally:
            self.result = saved
        return out

    # --- Composition ---------------------------------------------------------------------------
    def _compose(self, doc: LiveryDocument, variant, layers: list[Layer], region: Rect) -> None:  # type: ignore[no-untyped-def]
        x0, y0, x1, y1 = region
        linear = doc.blend_space == "linear"
        h, w = y1 - y0, x1 - x0
        base = self.base(doc) if (variant is None or variant.base_visible) else None
        if base is not None:
            rgb, alpha = blend.to_float(base[y0:y1, x0:x1], linear)
        elif doc.mode == "texture":
            rgb, alpha = np.ones((h, w, 3), np.float32), np.ones((h, w), np.float32)
        else:
            rgb, alpha = np.zeros((h, w, 3), np.float32), np.zeros((h, w), np.float32)
        for layer in layers:
            self._draw(layer, doc, region, rgb, alpha, linear)
        assert self.result is not None
        self.result[y0:y1, x0:x1] = blend.to_uint8(rgb, alpha, linear)

    def _source(self, layer: Layer, doc: LiveryDocument, region: Rect):  # type: ignore[no-untyped-def]
        """(sous-rectangle relatif à la région, rgba) du contenu du calque, ou None."""
        x0, y0, x1, y1 = region
        if layer.kind == "raster":
            image = self.scene.images.get(layer.image or "")
            if image is None:
                self.warnings.append(f"Pixels du calque « {layer.name} » absents.")
                return None
            return (0, 0, x1 - x0, y1 - y0), image.array[y0:y1, x0:x1]
        crop = self.crop(layer, doc)
        if crop is None:
            if layer.kind == "band" and (self.surface is None or not self.surface.triangle_count):
                self.warnings.append(f"Bande « {layer.name} » : aucune surface UV ciblée.")
            return None
        cx, cy, data = crop
        ox0, oy0 = max(x0, cx), max(y0, cy)
        ox1, oy1 = min(x1, cx + data.shape[1]), min(y1, cy + data.shape[0])
        if ox0 >= ox1 or oy0 >= oy1:
            return None
        return (ox0 - x0, oy0 - y0, ox1 - x0, oy1 - y0), data[oy0 - cy : oy1 - cy, ox0 - cx : ox1 - cx]

    def _draw(self, layer: Layer, doc: LiveryDocument, region: Rect, rgb, alpha, linear: bool) -> None:  # type: ignore[no-untyped-def]
        if not layer.visible or layer.opacity <= 0:
            return
        if layer.kind == "group":
            g_rgb = np.zeros_like(rgb)
            g_alpha = np.zeros_like(alpha)
            for child in layer.children:
                self._draw(child, doc, region, g_rgb, g_alpha, linear)
            sub, src_rgb, src_a = (0, 0, rgb.shape[1], rgb.shape[0]), g_rgb, g_alpha
        else:
            found = self._source(layer, doc, region)
            if found is None:
                return
            sub, data = found
            src_rgb, src_a = blend.to_float(data, linear)
        sx0, sy0, sx1, sy1 = sub
        src_a = src_a * float(layer.opacity)
        if layer.mask and layer.mask_enabled:
            mask = self.scene.images.get(layer.mask)
            if mask is not None:
                x0, y0 = region[0], region[1]
                m = mask.array[y0 + sy0 : y0 + sy1, x0 + sx0 : x0 + sx1].astype(np.float32) / 255.0
                src_a = src_a * m
        blend.composite(rgb[sy0:sy1, sx0:sx1], alpha[sy0:sy1, sx0:sx1], src_rgb, src_a, layer.blend)
