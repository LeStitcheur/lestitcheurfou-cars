"""Rendu logiciel minimal (numpy) : vues orthographiques et miniatures, sans OpenGL.

Sert aux miniatures de comparaison de l'historique (exécutables dans un thread) et à la
génération des références de démonstration. Repère du véhicule : X latéral (droite = +X),
Y vertical, Z longitudinal (avant vers -Z), comme les axes par défaut du Vehicle Editor.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

# vue → (direction de regard, vecteur haut de l'écran)
VIEW_CAMERAS: dict[str, tuple[tuple[float, float, float], tuple[float, float, float]]] = {
    "left": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
    "right": ((-1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
    "front": ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
    "back": ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    "top": ((0.0, -1.0, 0.0), (0.0, 0.0, -1.0)),
    "three_quarter": ((0.62, -0.38, 0.68), (0.0, 1.0, 0.0)),
}


@dataclass
class RenderMesh:
    positions: np.ndarray  # (N, 3)
    indices: np.ndarray  # (M, 3)
    face_colors: np.ndarray  # (M, 3) float 0..1


def camera_basis(view: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    look, up = (np.asarray(v, float) for v in VIEW_CAMERAS[view])
    look /= np.linalg.norm(look)
    right = np.cross(look, up)
    right /= np.linalg.norm(right)
    true_up = np.cross(right, look)
    return right, true_up, look


def render(
    meshes: list[RenderMesh],
    view: str = "three_quarter",
    size: int = 256,
    background: tuple[int, int, int] = (226, 229, 234),
    margin: float = 0.08,
    transparent: bool = False,
) -> Image.Image:
    """Projection orthographique, tampon de profondeur, éclairage Lambert + ambiant."""
    right, up, look = camera_basis(view)
    tris = [m.positions[m.indices.astype(np.int64)] for m in meshes if len(m.indices)]
    if not tris:
        return Image.new("RGBA" if transparent else "RGB", (size, size), (*background, 0))
    all_tri = np.concatenate(tris)
    colors = np.concatenate([m.face_colors for m in meshes if len(m.indices)])
    screen = np.stack([all_tri @ right, all_tri @ up, all_tri @ look], axis=-1)  # (M, 3, 3)
    lo = screen[..., :2].reshape(-1, 2).min(axis=0)
    hi = screen[..., :2].reshape(-1, 2).max(axis=0)
    extent = float((hi - lo).max()) or 1.0
    scale = size * (1 - 2 * margin) / extent
    center = (lo + hi) / 2
    px = (screen[..., 0] - center[0]) * scale + size / 2
    py = size / 2 - (screen[..., 1] - center[1]) * scale
    depth = screen[..., 2]
    normals = np.cross(all_tri[:, 1] - all_tri[:, 0], all_tri[:, 2] - all_tri[:, 0])
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = np.divide(normals, lengths, out=np.zeros_like(normals), where=lengths > 1e-12)
    light = -look + up * 0.6 + right * 0.3
    light /= np.linalg.norm(light)
    shade = 0.35 + 0.65 * np.abs(normals @ light)  # faces doubles (orientation inconnue)
    shaded = np.clip(colors * shade[:, None], 0, 1)
    zbuf = np.full((size, size), np.inf)
    image = np.zeros((size, size, 3))
    alpha = np.zeros((size, size), bool)
    for index in range(len(all_tri)):
        xs, ys, zs = px[index], py[index], depth[index]
        x0, x1 = int(max(0, np.floor(xs.min()))), int(min(size - 1, np.ceil(xs.max())))
        y0, y1 = int(max(0, np.floor(ys.min()))), int(min(size - 1, np.ceil(ys.max())))
        if x0 > x1 or y0 > y1:
            continue
        d = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
        if abs(d) < 1e-9:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        w0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / d
        w1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / d
        w2 = 1 - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not inside.any():
            continue
        z = w0 * zs[0] + w1 * zs[1] + w2 * zs[2]
        region = zbuf[y0 : y1 + 1, x0 : x1 + 1]
        closer = inside & (z < region)
        region[closer] = z[closer]
        image[y0 : y1 + 1, x0 : x1 + 1][closer] = shaded[index]
        alpha[y0 : y1 + 1, x0 : x1 + 1][closer] = True
    rgb = np.where(alpha[..., None], image * 255, np.asarray(background, float))
    out = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))
    if transparent:
        out.putalpha(Image.fromarray((alpha * 255).astype(np.uint8)))
    return out


def from_trimesh_scene(scene) -> list[RenderMesh]:  # type: ignore[no-untyped-def]
    """Maillages d'une scène trimesh (couleurs : texture échantillonnée, sommets ou matériau)."""
    import trimesh

    geometries = [scene] if isinstance(scene, trimesh.Trimesh) else scene.dump(concatenate=False)
    result = []
    for geom in geometries:
        if not isinstance(geom, trimesh.Trimesh) or not len(geom.faces):
            continue
        result.append(RenderMesh(np.asarray(geom.vertices, float), np.asarray(geom.faces), face_colors(geom)))
    return result


def face_colors(geom) -> np.ndarray:  # type: ignore[no-untyped-def]
    faces = np.asarray(geom.faces)
    visual = geom.visual
    try:
        if visual.kind == "texture" and getattr(visual, "uv", None) is not None:
            material = visual.material
            image = getattr(material, "baseColorTexture", None) or getattr(material, "image", None)
            factor = getattr(material, "baseColorFactor", None)
            factor = np.ones(3) if factor is None else np.asarray(factor, float)[:3]
            factor = factor / (255.0 if factor.max() > 1.0 else 1.0)
            if image is not None:
                pixels = np.asarray(image.convert("RGB"), float) / 255.0
                uv = np.asarray(visual.uv, float)[faces].mean(axis=1)
                h, w = pixels.shape[:2]
                xs = np.clip((uv[:, 0] % 1.0) * (w - 1), 0, w - 1).astype(int)
                ys = np.clip((1 - uv[:, 1] % 1.0) * (h - 1), 0, h - 1).astype(int)
                return pixels[ys, xs] * factor
            return np.tile(factor, (len(faces), 1))
        if visual.kind == "vertex":
            vc = np.asarray(visual.vertex_colors, float)[:, :3] / 255.0
            return vc[faces].mean(axis=1)
        fc = np.asarray(visual.face_colors, float)[:, :3] / 255.0
        if len(fc) == len(faces):
            return fc
    except (AttributeError, ValueError, TypeError, IndexError):
        pass
    return np.tile((0.72, 0.74, 0.78), (len(faces), 1))


def from_mesh_data(meshes: list[tuple[object, np.ndarray]]) -> list[RenderMesh]:
    """(MeshData, matrice monde 4×4) → maillages de rendu (couleurs de sommets)."""
    result = []
    for mesh, matrix in meshes:
        positions = np.asarray(mesh.positions, float)
        world = positions @ matrix[:3, :3].T + matrix[:3, 3]
        indices = np.asarray(mesh.indices, np.int64)
        colors = np.asarray(mesh.colors, float)[:, :3] / 255.0
        result.append(
            RenderMesh(world, indices, colors[indices].mean(axis=1) if len(indices) else colors[:0])
        )
    return result
