"""Pièces paramétriques originales du Lore Friendly Engine (générées par le code, aucun asset tiers).

Repère des pièces (comme ``scene.shapes``) : X = largeur, Y = hauteur, Z = longueur, avant du
véhicule vers −Z. Les optiques sont des profils 2D extrudés (forme réelle de la pièce) ; leur
couleur émise est une prévisualisation viewport, pas un éclairage GTA V.
"""

from __future__ import annotations

import math

import numpy as np

from lsfcars.scene import shapes
from lsfcars.scene.mesh import MeshData

LENS = (0.86, 0.88, 0.92, 1.0)
TAIL = (0.62, 0.08, 0.1, 1.0)
DARK = shapes.DARK

HEADLIGHT_STYLES = {
    "rect": "Rectangulaire",
    "slim": "Lame fine",
    "trapezoid": "Trapèze incliné",
    "round": "Ronde",
    "dual_round": "Double ronde",
    "boomerang": "Boomerang (L)",
    "split": "Divisée (signature au-dessus)",
}
TAILLIGHT_STYLES = {
    "rect": "Rectangulaire",
    "bar": "Barre horizontale",
    "c_shape": "En C",
    "round_pair": "Doubles rondes",
    "vertical": "Verticale",
    "slim": "Lame fine",
}
GRILLE_STYLES = {
    "bars_h": "Barres horizontales",
    "bars_v": "Barres verticales",
    "mesh": "Maille",
    "closed": "Fermée (fente)",
    "split": "Divisée en deux",
}
EXHAUST_STYLES = {
    "single": "Simple",
    "dual": "Double (une sortie par côté)",
    "dual_left": "Double à gauche",
    "quad": "Quadruple",
    "center": "Centrale",
}
SIGNATURE_STYLES = {"bar": "Barre continue", "split": "Deux traits", "dots": "Points"}


def _shift(x: float, y: float, z: float = 0.0) -> np.ndarray:
    m = np.eye(4)
    m[:3, 3] = (x, y, z)
    return m


def _ry(degrees: float) -> np.ndarray:
    """Rotation autour de Y : l'axe X des cylindres de ``shapes`` devient l'axe Z (longitudinal)."""
    a = math.radians(degrees)
    m = np.eye(4)
    m[0, 0], m[0, 2], m[2, 0], m[2, 2] = math.cos(a), math.sin(a), -math.sin(a), math.cos(a)
    return m


def _circle(cx: float, cy: float, r: float, n: int = 20) -> list[tuple[float, float]]:
    return [
        (cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)
    ]


def _lens(profile, depth: float, name: str, color=LENS) -> MeshData:  # type: ignore[no-untyped-def]
    return shapes.extrude_profile(profile, depth, name, color, axis=2)


def headlight(style: str, width: float, height: float, depth: float = 0.08) -> MeshData:
    w, h = width / 2, height / 2
    if style == "slim":
        return _lens([(-w, -h * 0.35), (w, -h * 0.2), (w * 0.9, h * 0.35), (-w, h * 0.25)], depth, "Phare")
    if style == "trapezoid":
        return _lens([(-w, -h), (w, -h * 0.6), (w * 0.8, h), (-w * 0.7, h * 0.85)], depth, "Phare")
    if style == "round":
        return _lens(_circle(0, 0, min(w, h)), depth, "Phare")
    if style == "dual_round":
        r = min(w / 2, h) * 0.9
        lens = _lens(_circle(0, 0, r), depth, "optique")
        return shapes.combine("Phare", [(lens, _shift(-w / 2, 0)), (lens, _shift(w / 2, 0))], LENS)
    if style == "boomerang":
        t = h * 0.45
        return _lens([(-w, -h), (w, -h), (w, -h + t), (-w + t, -h + t), (-w + t, h), (-w, h)], depth, "Phare")
    if style == "split":
        top = _lens([(-w, h * 0.55), (w, h * 0.7), (w, h), (-w, h * 0.85)], depth, "signature")
        main = _lens(
            [(-w * 0.8, -h), (w * 0.8, -h), (w * 0.8, h * 0.2), (-w * 0.8, h * 0.2)], depth, "optique"
        )
        return shapes.combine("Phare", [(top, None), (main, None)], LENS)
    return _lens([(-w, -h), (w, -h), (w, h), (-w, h)], depth, "Phare")


def taillight(style: str, width: float, height: float, depth: float = 0.05) -> MeshData:
    w, h = width / 2, height / 2
    if style == "bar":
        return _lens([(-w, -h * 0.3), (w, -h * 0.3), (w, h * 0.3), (-w, h * 0.3)], depth, "Feu arrière", TAIL)
    if style == "c_shape":
        t = min(w, h) * 0.45
        outline = [
            (-w, -h),
            (w, -h),
            (w, -h + t),
            (-w + t, -h + t),
            (-w + t, h - t),
            (w, h - t),
            (w, h),
            (-w, h),
        ]
        return _lens(outline, depth, "Feu arrière", TAIL)
    if style == "round_pair":
        r = min(w / 2, h) * 0.9
        lens = _lens(_circle(0, 0, r), depth, "feu", TAIL)
        return shapes.combine("Feu arrière", [(lens, _shift(-w / 2, 0)), (lens, _shift(w / 2, 0))], TAIL)
    if style == "vertical":
        outline = [(-w * 0.35, -h * 1.4), (w * 0.35, -h * 1.4), (w * 0.35, h * 1.4), (-w * 0.35, h * 1.4)]
        return _lens(outline, depth, "Feu arrière", TAIL)
    if style == "slim":
        return _lens(
            [(-w, -h * 0.18), (w, -h * 0.1), (w, h * 0.18), (-w, h * 0.12)], depth, "Feu arrière", TAIL
        )
    return _lens([(-w, -h), (w, -h), (w, h), (-w, h)], depth, "Feu arrière", TAIL)


def grille(style: str, width: float, height: float, depth: float = 0.05) -> MeshData:
    t = 0.03
    rows = max(2, int(height / 0.06))
    if style == "bars_h":
        return shapes.grille(width, height, rows, depth)
    parts: list[tuple[MeshData, np.ndarray | None]] = [
        (shapes.box((width, t, depth)), _shift(0, height / 2 - t / 2)),
        (shapes.box((width, t, depth)), _shift(0, -height / 2 + t / 2)),
        (shapes.box((t, height, depth)), _shift(-width / 2 + t / 2, 0)),
        (shapes.box((t, height, depth)), _shift(width / 2 - t / 2, 0)),
    ]
    if style == "bars_v":
        count = max(3, int(width / 0.07))
        for k in range(1, count):
            parts.append(
                (
                    shapes.box((t * 0.5, height - 2 * t, depth * 0.7)),
                    _shift(-width / 2 + k * width / count, 0),
                )
            )
    elif style == "mesh":
        cols, grid_rows = max(4, int(width / 0.08)), max(2, int(height / 0.07))
        for k in range(1, cols):
            parts.append(
                (
                    shapes.box((t * 0.35, height - 2 * t, depth * 0.6)),
                    _shift(-width / 2 + k * width / cols, 0),
                )
            )
        for k in range(1, grid_rows):
            y = -height / 2 + k * height / grid_rows
            parts.append((shapes.box((width - 2 * t, t * 0.35, depth * 0.6)), _shift(0, y)))
    elif style == "closed":
        parts = [
            (shapes.box((width, height * 0.42, depth)), _shift(0, height * 0.29)),
            (shapes.box((width, height * 0.42, depth)), _shift(0, -height * 0.29)),
        ]
    elif style == "split":
        parts.append((shapes.box((t * 2.2, height, depth * 1.1)), None))
        for k in range(1, rows + 1):
            parts.append(
                (
                    shapes.box((width - 2 * t, t * 0.45, depth * 0.7)),
                    _shift(0, -height / 2 + k * height / (rows + 1)),
                )
            )
    return shapes.combine("Calandre", parts, DARK)


def signature(style: str, width: float, height: float = 0.018, depth: float = 0.02) -> MeshData:
    """Bande de signature lumineuse (DRL) : forme réelle, émission en prévisualisation."""
    w = width / 2
    if style == "split":
        bar = shapes.box((w * 0.8, height, depth))
        return shapes.combine(
            "Signature lumineuse", [(bar, _shift(-w * 0.55, 0)), (bar, _shift(w * 0.55, 0))], LENS
        )
    if style == "dots":
        dot = shapes.cylinder(height * 0.9, depth, 12)
        count = 4
        parts = [(dot, _shift(-w + (k + 0.5) * width / count, 0) @ _ry(90)) for k in range(count)]
        return shapes.combine("Signature lumineuse", parts, LENS)
    return shapes.combine("Signature lumineuse", [(shapes.box((width, height, depth)), None)], LENS)


def exhaust_tip(radius: float = 0.045, length: float = 0.14) -> MeshData:
    tip = shapes.cylinder(radius, length, 20, "sortie")
    return shapes.combine("Sortie d'échappement", [(tip, _ry(90))], (0.55, 0.56, 0.58, 1.0))


def exhaust_offsets(style: str, half_width: float) -> list[float]:
    """Positions latérales (m) des sorties selon la configuration."""
    lateral = half_width * 0.62
    return {
        "single": [-lateral],
        "dual": [-lateral, lateral],
        "dual_left": [-lateral - 0.06, -lateral + 0.06],
        "quad": [-lateral - 0.06, -lateral + 0.06, lateral - 0.06, lateral + 0.06],
        "center": [-0.05, 0.05],
    }.get(style, [-lateral, lateral])


def skid_plate(width: float, depth: float = 0.35, thickness: float = 0.02) -> MeshData:
    profile = [(-depth / 2, 0), (depth / 2, -0.06), (depth / 2, -0.06 + thickness), (-depth / 2, thickness)]
    return shapes.extrude_profile(profile, width, "Protection inférieure", (0.35, 0.36, 0.38, 1.0), axis=0)
