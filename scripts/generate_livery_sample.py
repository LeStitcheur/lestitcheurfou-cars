"""Génère ``samples/vehicule_livree.glb`` : véhicule d'essai original avec dépliage UV.

Sert au Livery Studio (tests, captures, démonstration). Géométrie et texture entièrement
générées ici (aucun asset tiers). Particularités volontaires :

- côté gauche et côté droit sur deux îlots UV distincts, le côté droit **tourné de 180°**
  (une symétrie par simple retournement horizontal serait fausse) ;
- rétroviseurs gauche et droit partageant la **même zone UV** (îlots superposés) ;
- plusieurs matériaux : carrosserie texturée, vitres, pneus, soubassement ;
- avant du véhicule vers -Z (axes par défaut du projet), haut = +Y, droite = +X.

Usage : ``python scripts/generate_livery_sample.py``
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "samples" / "vehicule_livree.glb"

HALF_W, Y0, Y1, Y2 = 0.9, 0.32, 0.92, 1.42
Z_FRONT, Z_REAR = -2.2, 2.2
CABIN_BOTTOM, CABIN_TOP = (-1.0, 1.4), (-0.55, 0.85)
TEX = 1024


def lerp(a, b, t):  # type: ignore[no-untyped-def]
    return a + (b - a) * t


def grid(corner, du, dv, nu, nv, uv_of):  # type: ignore[no-untyped-def]
    """Quadrillage plan : sommet = corner + s·du + t·dv ; ``uv_of(s, t)`` donne l'UV."""
    positions, uvs, faces = [], [], []
    for j in range(nv + 1):
        for i in range(nu + 1):
            s, t = i / nu, j / nv
            positions.append(
                np.asarray(corner, float) + s * np.asarray(du, float) + t * np.asarray(dv, float)
            )
            uvs.append(uv_of(s, t))
    for j in range(nv):
        for i in range(nu):
            a = j * (nu + 1) + i
            b, c, d = a + 1, a + nu + 2, a + nu + 1
            faces += [(a, b, c), (a, c, d)]
    return np.array(positions), np.array(uvs), np.array(faces)


def trapezoid(x, nu, nv, uv_of):  # type: ignore[no-untyped-def]
    """Flanc de l'habitacle (plan x = cste), trapèze entre Y1 et Y2."""
    positions, uvs, faces = [], [], []
    for j in range(nv + 1):
        t = j / nv
        z0 = lerp(CABIN_BOTTOM[0], CABIN_TOP[0], t)
        z1 = lerp(CABIN_BOTTOM[1], CABIN_TOP[1], t)
        y = lerp(Y1, Y2, t)
        for i in range(nu + 1):
            z = lerp(z0, z1, i / nu)
            positions.append((x, y, z))
            uvs.append(uv_of(z, y))
    for j in range(nv):
        for i in range(nu):
            a = j * (nu + 1) + i
            b, c, d = a + 1, a + nu + 2, a + nu + 1
            faces += [(a, b, c), (a, c, d)]
    return np.array(positions), np.array(uvs), np.array(faces)


def merge(parts, flip_mask):  # type: ignore[no-untyped-def]
    positions, uvs, faces, offset = [], [], [], 0
    for (p, uv, f), flip in zip(parts, flip_mask, strict=True):
        positions.append(p)
        uvs.append(uv)
        f = f[:, ::-1] if flip else f
        faces.append(f + offset)
        offset += len(p)
    return np.vstack(positions), np.vstack(uvs), np.vstack(faces)


def side_uv(left: bool):  # type: ignore[no-untyped-def]
    def uv(z, y):  # type: ignore[no-untyped-def]
        a = (z - Z_FRONT) / (Z_REAR - Z_FRONT)  # 0 avant → 1 arrière
        b = (y - Y0) / (Y2 - Y0)  # 0 bas → 1 haut
        if left:  # îlot gauche, orienté « vu de l'extérieur » : avant à gauche, haut en haut
            return (lerp(0.02, 0.88, a), lerp(0.765, 0.98, b))
        # îlot droit tourné de 180° : avant à gauche et haut en bas
        return (lerp(0.02, 0.88, a), lerp(0.745, 0.53, b))

    return uv


def body_mesh():  # type: ignore[no-untyped-def]
    parts, flips = [], []
    for x, left in ((-HALF_W, True), (HALF_W, False)):  # -X = gauche, +X = droite
        uv = side_uv(left)
        lower = grid(
            (x, Y0, Z_FRONT),
            (0, 0, Z_REAR - Z_FRONT),
            (0, Y1 - Y0, 0),
            22,
            4,
            lambda s, t, uv=uv: uv(lerp(Z_FRONT, Z_REAR, s), lerp(Y0, Y1, t)),
        )
        parts += [lower, trapezoid(x, 12, 4, uv)]
        flips += [not left, not left]

    def top(z0, z1, y, u0, u1, v0, v1, nu):  # type: ignore[no-untyped-def]
        """Capot, toit, coffre (faces vers +Y)."""
        return grid(
            (HALF_W, y, z0),
            (-2 * HALF_W, 0, 0),
            (0, 0, z1 - z0),
            8,
            nu,
            lambda s, t: (lerp(u0, u1, s), lerp(v1, v0, t)),
        )

    parts += [
        top(Z_FRONT, CABIN_BOTTOM[0], Y1, 0.02, 0.372, 0.27, 0.504, 6),
        top(CABIN_TOP[0], CABIN_TOP[1], Y2, 0.39, 0.742, 0.231, 0.504, 6),
        top(CABIN_BOTTOM[1], Z_REAR, Y1, 0.02, 0.372, 0.10, 0.256, 4),
    ]
    flips += [False, False, False]
    parts.append(  # face avant (vers -Z)
        grid(
            (-HALF_W, Y0, Z_FRONT),
            (2 * HALF_W, 0, 0),
            (0, Y1 - Y0, 0),
            8,
            3,
            lambda s, t: (lerp(0.39, 0.742, 1 - s), lerp(0.10, 0.217, t)),
        )
    )
    parts.append(  # face arrière (vers +Z)
        grid(
            (-HALF_W, Y0, Z_REAR),
            (2 * HALF_W, 0, 0),
            (0, Y1 - Y0, 0),
            8,
            3,
            lambda s, t: (lerp(0.39, 0.742, s), lerp(0.005, 0.09, t)),
        )
    )
    flips += [True, False]
    return merge(parts, flips)


def quad(p0, p1, p2, p3, uv_box=(0, 0, 1, 1)):  # type: ignore[no-untyped-def]
    u0, v0, u1, v1 = uv_box
    positions = np.array([p0, p1, p2, p3], float)
    uvs = np.array([(u0, v0), (u1, v0), (u1, v1), (u0, v1)], float)
    return positions, uvs, np.array([(0, 1, 2), (0, 2, 3)])


def glass_mesh():  # type: ignore[no-untyped-def]
    eps = 0.004
    windshield = quad(
        (-HALF_W, Y1, CABIN_BOTTOM[0]),
        (HALF_W, Y1, CABIN_BOTTOM[0]),
        (HALF_W, Y2, CABIN_TOP[0]),
        (-HALF_W, Y2, CABIN_TOP[0]),
    )
    rear = quad(
        (HALF_W, Y1, CABIN_BOTTOM[1]),
        (-HALF_W, Y1, CABIN_BOTTOM[1]),
        (-HALF_W, Y2, CABIN_TOP[1]),
        (HALF_W, Y2, CABIN_TOP[1]),
    )
    sides = []
    for x in (HALF_W + eps, -HALF_W - eps):
        y_a, y_b = Y1 + 0.06, Y2 - 0.06
        za0 = lerp(CABIN_BOTTOM[0], CABIN_TOP[0], 0.12) + 0.1
        za1 = lerp(CABIN_BOTTOM[1], CABIN_TOP[1], 0.12) - 0.1
        zb0 = lerp(CABIN_BOTTOM[0], CABIN_TOP[0], 0.88) + 0.1
        zb1 = lerp(CABIN_BOTTOM[1], CABIN_TOP[1], 0.88) - 0.1
        sides.append(quad((x, y_a, za0), (x, y_a, za1), (x, y_b, zb1), (x, y_b, zb0)))
    return merge([windshield, rear, *sides], [True, True, True, False])


def mirror_mesh(x_sign: float):  # type: ignore[no-untyped-def]
    box = trimesh.creation.box(extents=(0.16, 0.1, 0.12))
    box.apply_translation((x_sign * (HALF_W + 0.08), Y1 + 0.08, CABIN_BOTTOM[0] + 0.1))
    # les deux rétroviseurs utilisent la même zone UV (îlots superposés, volontaire)
    local = box.vertices - box.vertices.min(axis=0)
    span = np.maximum(local.max(axis=0), 1e-9)
    uvs = np.stack([lerp(0.76, 0.98, local[:, 2] / span[2]), lerp(0.10, 0.16, local[:, 1] / span[1])], axis=1)
    return box.vertices, uvs, box.faces


def wheel_mesh(x, z):  # type: ignore[no-untyped-def]
    wheel = trimesh.creation.cylinder(radius=0.34, height=0.24, sections=24)
    wheel.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (0, 1, 0)))
    wheel.apply_translation((x, 0.34, z))
    angle = np.arctan2(wheel.vertices[:, 1] - 0.34, wheel.vertices[:, 2] - z)
    uvs = np.stack([(angle + np.pi) / (2 * np.pi), (wheel.vertices[:, 0] - x) / 0.24 + 0.5], axis=1)
    return wheel.vertices, uvs, wheel.faces


def base_texture() -> Image.Image:
    """Texture d'origine : gris clair, joints de portes, capot et coffre (graphisme original)."""
    image = Image.new("RGBA", (TEX, TEX), (205, 210, 218, 255))
    draw = ImageDraw.Draw(image)

    def px(u, v):  # type: ignore[no-untyped-def]
        return (u * TEX, (1 - v) * TEX)

    line = (120, 126, 136, 255)
    for left in (True, False):
        uv = side_uv(left)
        for z in (-0.95, 0.25, 1.35):  # joints de portes
            draw.line([px(*uv(z, Y0 + 0.05)), px(*uv(z, Y1 + 0.02))], fill=line, width=3)
        draw.line([px(*uv(Z_FRONT + 0.05, Y1 - 0.02)), px(*uv(Z_REAR - 0.05, Y1 - 0.02))], fill=line, width=2)
    for u0, u1, v0, v1 in ((0.02, 0.372, 0.27, 0.504), (0.02, 0.372, 0.10, 0.256)):
        draw.rectangle([px(u0 + 0.01, v1 - 0.01), px(u1 - 0.01, v0 + 0.01)], outline=line, width=3)
    return image


def build() -> trimesh.Scene:
    texture = base_texture()
    body_material = trimesh.visual.material.PBRMaterial(
        name="Carrosserie",
        baseColorTexture=texture,
        baseColorFactor=(255, 255, 255, 255),
        metallicFactor=0.3,
        roughnessFactor=0.35,
    )
    glass = trimesh.visual.material.PBRMaterial(
        name="Vitres",
        baseColorFactor=(40, 52, 70, 200),
        metallicFactor=0.0,
        roughnessFactor=0.1,
        alphaMode="BLEND",
    )
    tyre = trimesh.visual.material.PBRMaterial(
        name="Pneus", baseColorFactor=(28, 28, 30, 255), roughnessFactor=0.9
    )
    under = trimesh.visual.material.PBRMaterial(
        name="Soubassement", baseColorFactor=(45, 48, 54, 255), roughnessFactor=0.8
    )
    scene = trimesh.Scene()

    def add(name, data, material):  # type: ignore[no-untyped-def]
        positions, uvs, faces = data
        mesh = trimesh.Trimesh(positions, faces, process=False)
        mesh.visual = trimesh.visual.TextureVisuals(uv=uvs, material=material)
        scene.add_geometry(mesh, node_name=name, geom_name=f"{name}_geo")

    add("caisse", body_mesh(), body_material)
    add("vitres", glass_mesh(), glass)
    add("retroviseur_gauche", mirror_mesh(-1.0), body_material)
    add("retroviseur_droit", mirror_mesh(1.0), body_material)
    under_quad = quad(
        (HALF_W, Y0, Z_FRONT), (-HALF_W, Y0, Z_FRONT), (-HALF_W, Y0, Z_REAR), (HALF_W, Y0, Z_REAR)
    )
    add("soubassement", under_quad, under)
    for name, x, z in (
        ("roue_avant_gauche", -0.8, -1.4),
        ("roue_avant_droite", 0.8, -1.4),
        ("roue_arriere_gauche", -0.8, 1.4),
        ("roue_arriere_droite", 0.8, 1.4),
    ):
        add(name, wheel_mesh(x, z), tyre)
    return scene


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    build().export(OUTPUT)
    print(f"Écrit : {OUTPUT} ({OUTPUT.stat().st_size // 1024} Kio)")


if __name__ == "__main__":
    main()
