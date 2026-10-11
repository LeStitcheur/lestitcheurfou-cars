"""Modes de fusion et composition alpha (formules séparables du W3C *Compositing and Blending*).

Couleurs en flottants [0, 1], alpha non prémultiplié. La composition peut se faire dans
l'espace sRGB (comportement des éditeurs d'images courants) ou en lumière linéaire.
"""

from __future__ import annotations

import numpy as np


def srgb_to_linear(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4).astype(np.float32)


def linear_to_srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055).astype(np.float32)


def _overlay(cb: np.ndarray, cs: np.ndarray) -> np.ndarray:
    return np.where(cb <= 0.5, 2.0 * cb * cs, 1.0 - 2.0 * (1.0 - cb) * (1.0 - cs))


BLEND_FUNCTIONS = {
    "normal": lambda cb, cs: cs,
    "multiply": lambda cb, cs: cb * cs,
    "screen": lambda cb, cs: cb + cs - cb * cs,
    "overlay": _overlay,
    "add": lambda cb, cs: np.minimum(cb + cs, 1.0),
    "darken": np.minimum,
    "lighten": np.maximum,
}


def composite(
    dst_rgb: np.ndarray,
    dst_a: np.ndarray,
    src_rgb: np.ndarray,
    src_a: np.ndarray,
    mode: str = "normal",
) -> None:
    """Compose ``src`` sur ``dst`` en place. rgb : (H, W, 3), alpha : (H, W) ; flottants [0, 1]."""
    blend = BLEND_FUNCTIONS.get(mode, BLEND_FUNCTIONS["normal"])
    a_s = src_a[..., None]
    a_b = dst_a[..., None]
    a_o = a_s + a_b * (1.0 - a_s)
    mixed = blend(dst_rgb, src_rgb)
    premult = a_s * (1.0 - a_b) * src_rgb + a_s * a_b * mixed + (1.0 - a_s) * a_b * dst_rgb
    safe = np.where(a_o > 1e-6, a_o, 1.0)
    dst_rgb[...] = np.where(a_o > 1e-6, premult / safe, 0.0)
    dst_a[...] = a_o[..., 0]


def to_float(rgba: np.ndarray, linear: bool = False) -> tuple[np.ndarray, np.ndarray]:
    data = rgba.astype(np.float32) / 255.0
    rgb = data[..., :3]
    return (srgb_to_linear(rgb) if linear else rgb.copy()), data[..., 3].copy()


def to_uint8(rgb: np.ndarray, alpha: np.ndarray, linear: bool = False) -> np.ndarray:
    if linear:
        rgb = linear_to_srgb(rgb)
    out = np.empty((*alpha.shape, 4), np.uint8)
    out[..., :3] = np.clip(rgb * 255.0 + 0.5, 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(alpha * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return out
