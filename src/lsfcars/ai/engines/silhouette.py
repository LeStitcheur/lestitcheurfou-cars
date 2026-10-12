"""LSF Silhouette : reconstruction 3D par enveloppe visuelle (algorithme local, pas une IA).

Principe (« shape from silhouette ») : les vues orthographiques détourées (profil, avant /
arrière, dessus) sont extrudées dans une grille de voxels ; seuls les voxels présents dans
**toutes** les silhouettes disponibles sont conservés. La surface est extraite par *surface
nets* puis lissée, et chaque sommet reçoit la couleur de la vue qui lui fait face.

Limites, signalées dans le rapport : les concavités (passages de roues, vitrages en retrait)
ne sont pas reconstruites ; une vue absente est remplacée par une section **estimée** ; la
vue trois quarts n'est pas exploitable (perspective) ; l'habitacle n'est pas reconstruit.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from lsfcars.ai import references as refs_mod
from lsfcars.ai.engines.base import (
    PROFILE_LABELS,
    Availability,
    Capability,
    EngineAdapter,
    EngineInfo,
    EngineOutput,
    GenerationRequest,
    JobContext,
    ProfileOption,
    Status,
)
from lsfcars.ai.errors import EngineUnavailable, InvalidOutput
from lsfcars.ai.hardware import HardwareInfo

VERSION = "1.0"
RESOLUTIONS = {"eco": 72, "balanced": 128, "high": 200}  # voxels sur la longueur


def _mask_crop(image: Image.Image, mask_path: Path | None) -> tuple[np.ndarray, np.ndarray]:
    """(masque recadré bool, image RGB recadrée) d'une vue détourée."""
    if mask_path is not None and Path(mask_path).is_file():
        mask = np.asarray(Image.open(mask_path).convert("L")) >= 128
        box = refs_mod._bbox(mask)
    else:
        seg = refs_mod.segment(image)
        if not seg.ok:
            raise InvalidOutput(
                "Silhouette introuvable : " + " ".join(seg.warnings or ["détourage impossible."])
            )
        mask, box = seg.mask, seg.bbox
    if box is None:
        raise InvalidOutput("Silhouette vide.")
    x0, y0, x1, y1 = box
    rgb = np.asarray(image.convert("RGB"))[y0:y1, x0:x1]
    return mask[y0:y1, x0:x1], rgb


def _resample(mask: np.ndarray, width: int, height: int) -> np.ndarray:
    image = Image.fromarray(mask.astype(np.uint8) * 255).resize((width, height), Image.Resampling.BILINEAR)
    return np.asarray(image) >= 128


def _smoothstep(e0: float, e1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - e0) / (e1 - e0 if abs(e1 - e0) > 1e-6 else 1e-6), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _blur(field: np.ndarray, sigma: float) -> np.ndarray:
    radius = max(1, int(round(sigma * 2.5)))
    xs = np.arange(-radius, radius + 1)
    kernel = np.exp(-(xs**2) / (2 * sigma * sigma))
    kernel /= kernel.sum()
    out = field
    for axis in range(3):
        out = np.apply_along_axis(lambda line: np.convolve(line, kernel, mode="same"), axis, out)
    return out


_CORNERS = np.array([[i, j, k] for k in (0, 1) for j in (0, 1) for i in (0, 1)])
_EDGES = [(a, b) for a in range(8) for b in range(a + 1, 8) if np.abs(_CORNERS[a] - _CORNERS[b]).sum() == 1]


def surface_nets(field: np.ndarray, iso: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
    """Surface nets naïfs vectorisés : (sommets en coordonnées de grille, triangles)."""
    nx, ny, nz = field.shape
    corners = np.stack(
        [field[i : nx - 1 + i, j : ny - 1 + j, k : nz - 1 + k] for i, j, k in _CORNERS], axis=-1
    )  # (cx, cy, cz, 8)
    inside = corners > iso
    active = inside.any(-1) & ~inside.all(-1)
    cells = np.argwhere(active)
    if not len(cells):
        return np.zeros((0, 3)), np.zeros((0, 3), np.int64)
    values = corners[active]
    accum = np.zeros((len(cells), 3))
    count = np.zeros(len(cells))
    for a, b in _EDGES:
        va, vb = values[:, a], values[:, b]
        crossing = (va > iso) != (vb > iso)
        t = np.where(crossing, (iso - va) / np.where(crossing, vb - va, 1.0), 0.0)
        point = _CORNERS[a] + t[:, None] * (_CORNERS[b] - _CORNERS[a])
        accum += np.where(crossing[:, None], point, 0.0)
        count += crossing
    vertices = cells + accum / np.maximum(count, 1)[:, None]
    index = -np.ones(active.shape, np.int64)
    index[tuple(cells.T)] = np.arange(len(cells))
    quads = []
    solid = field > iso
    for axis in range(3):
        a1, a2 = [a for a in range(3) if a != axis]
        lo = [slice(None)] * 3
        hi = [slice(None)] * 3
        lo[axis] = slice(0, -1)
        hi[axis] = slice(1, None)
        change = solid[tuple(lo)] != solid[tuple(hi)]
        edges = np.argwhere(change)
        edges = edges[(edges[:, a1] >= 1) & (edges[:, a2] >= 1)]
        edges = edges[(edges[:, a1] < field.shape[a1] - 1) & (edges[:, a2] < field.shape[a2] - 1)]
        if not len(edges):
            continue
        offsets = []
        for d1, d2 in ((-1, -1), (0, -1), (0, 0), (-1, 0)):
            cell = edges.copy()
            cell[:, a1] += d1
            cell[:, a2] += d2
            offsets.append(index[tuple(cell.T)])
        quad = np.stack(offsets, axis=1)
        flip = solid[tuple(edges.T)]  # intérieur du côté bas de l'arête : orientation inversée
        quad[flip] = quad[flip][:, ::-1]
        if axis == 1:
            quad = quad[:, ::-1]
        quads.append(quad[(quad >= 0).all(axis=1)])
    if not quads:
        return vertices, np.zeros((0, 3), np.int64)
    quads_all = np.concatenate(quads)
    tris = np.concatenate([quads_all[:, [0, 1, 2]], quads_all[:, [0, 2, 3]]])
    return vertices, tris


def taubin(vertices: np.ndarray, faces: np.ndarray, iterations: int = 6) -> np.ndarray:
    """Lissage de Taubin (λ / μ) : atténue les marches de voxels sans rétrécir la forme."""
    if not len(faces):
        return vertices
    n = len(vertices)
    edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    edges = np.concatenate([edges, edges[:, ::-1]])
    degree = np.bincount(edges[:, 0], minlength=n).astype(float)
    points = vertices.astype(float).copy()
    for _ in range(iterations):
        for factor in (0.5, -0.53):
            neighbour = np.zeros_like(points)
            np.add.at(neighbour, edges[:, 0], points[edges[:, 1]])
            mean = neighbour / np.maximum(degree, 1)[:, None]
            points += factor * (mean - points)
    return points


def vertex_normals(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    normals = np.zeros_like(vertices)
    tri = vertices[faces]
    face_n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    for corner in range(3):
        np.add.at(normals, faces[:, corner], face_n)
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    return np.divide(normals, lengths, out=np.zeros_like(normals), where=lengths > 1e-12)


class SilhouetteEngine(EngineAdapter):
    info = EngineInfo(
        id="lsf-silhouette",
        name="LSF Silhouette",
        version=VERSION,
        kind="local",
        method="algorithmic",
        capabilities=frozenset({Capability.IMAGE_TO_3D, Capability.MULTIVIEW_3D, Capability.TEXTURE}),
        input_formats=("PNG", "JPG", "WEBP"),
        output_formats=("GLB",),
        resources="CPU seulement, < 1 Go de RAM",
        auth="aucune",
        limits={
            "max_images": 5,
            "views": ["left", "right", "front", "back", "top"],
            "required": "un profil (gauche ou droit) détouré",
        },
        cost="gratuit (calcul local)",
        license="Code LeStitcheurFou Cars",
        verification="Génération réelle exécutée par les tests automatisés (références de démonstration).",
    )

    def detect(self) -> Availability:
        return Availability(Status.AVAILABLE, "Intégré à l'application (aucune installation).", VERSION)

    def profiles(self, hardware: HardwareInfo | None) -> list[ProfileOption]:
        return [
            ProfileOption(key, PROFILE_LABELS[key], {"resolution": value, "smooth": 4 if key == "eco" else 6})
            for key, value in RESOLUTIONS.items()
        ]

    def run(self, request: GenerationRequest, ctx: JobContext) -> EngineOutput:
        params = self.profile_params(request, None)
        by_view: dict = {}
        for ref in request.references:
            by_view.setdefault(ref.view, ref)
        side_ref = by_view.get("left") or by_view.get("right")
        if side_ref is None:
            raise EngineUnavailable(
                "LSF Silhouette exige un profil (gauche ou droit). Une vue trois quarts seule n'est pas "
                "exploitable par cet algorithme : utilisez un moteur image → 3D (TripoSR, cloud)."
            )
        ctx.progress(0.05, "Détourage des vues")
        warnings: list[str] = []
        estimated: list[str] = []
        used: list[str] = []
        side_mask, side_rgb = _mask_crop(Image.open(side_ref.path), side_ref.mask_path)
        front_left = request.params.get("front_left", {}).get(side_ref.view, side_ref.view != "right")
        if not front_left:
            side_mask, side_rgb = side_mask[:, ::-1], side_rgb[:, ::-1]
        used.append(side_ref.view)
        length = float(request.vehicle.get("length_m") or 4.6)
        height = length * side_mask.shape[0] / side_mask.shape[1]
        end_ref = by_view.get("front") or by_view.get("back")
        end_mask = end_rgb = None
        if end_ref is not None:
            ctx.check()
            end_mask, end_rgb = _mask_crop(Image.open(end_ref.path), end_ref.mask_path)
            if end_ref.view == "front":  # écran : la gauche du véhicule apparaît à droite
                end_mask, end_rgb = end_mask[:, ::-1], end_rgb[:, ::-1]
            width = height * end_mask.shape[1] / end_mask.shape[0]
            used.append(end_ref.view)
        else:
            width = float(request.vehicle.get("width_m") or length * 0.4)
            estimated.append("Section transversale (aucune vue avant / arrière) : largeur et galbe estimés")
        top_ref = by_view.get("top")
        top_mask = top_rgb = None
        if top_ref is not None:
            ctx.check()
            top_mask, top_rgb = _mask_crop(Image.open(top_ref.path), top_ref.mask_path)
            used.append("top")
        else:
            estimated.append("Vue en plan (aucune vue du dessus) : contour arrondi estimé")
        if len(used) == 1:
            warnings.append(
                "Une seule vue exploitée (profil) : la forme 3D repose en partie sur des estimations."
            )

        resolution = int(params.get("resolution", 128))
        nz = resolution
        voxel = length / nz
        ny = max(8, int(round(height / voxel)))
        nx = max(8, int(round(width / voxel)))
        ctx.progress(0.2, f"Grille de voxels {nx}×{ny}×{nz}")
        side = _resample(side_mask, nz, ny)[::-1]  # (y du bas vers le haut, z de l'avant vers l'arrière)
        occupancy = np.broadcast_to(side[None, :, :], (nx, ny, nz)).copy()
        ys = (np.arange(ny) + 0.5) / ny
        xs = (np.arange(nx) + 0.5) / nx * 2 - 1  # -1 (gauche) → 1 (droite)
        if end_mask is not None:
            end = _resample(end_mask, nx, ny)[::-1].T  # (x, y)
            occupancy &= end[:, :, None]
        else:
            hood = side[:, : max(1, nz // 5)].any(axis=1)
            belt = float(np.flatnonzero(hood)[-1] + 1) / ny if hood.any() else 0.55
            half = 1.0 - 0.24 * _smoothstep(belt, 1.0, ys)  # rentrée de caisse au-dessus de la ceinture
            half *= 1.0 - 0.10 * _smoothstep(0.12, 0.0, ys)  # bas de caisse légèrement galbé
            section = np.abs(xs)[:, None] <= half[None, :]
            occupancy &= section[:, :, None]
        if top_mask is not None:
            top = _resample(top_mask, nx, nz)  # (z de l'avant vers l'arrière, x de gauche à droite)
            occupancy &= top.T[:, None, :]
        else:
            zs = (np.arange(nz) + 0.5) / nz
            taper = 1.0 - 0.10 * (_smoothstep(0.12, 0.0, zs) + _smoothstep(0.88, 1.0, zs))
            ends = np.minimum(zs, 1 - zs)
            round_corner = np.sqrt(np.clip(1 - np.clip((0.06 - ends) / 0.06, 0, 1) ** 2, 0, 1))
            plan = np.abs(xs)[:, None] <= (taper * (0.82 + 0.18 * round_corner))[None, :]
            occupancy &= plan[:, None, :]
        if not occupancy.any():
            raise InvalidOutput(
                "Les silhouettes ne se recoupent pas : vérifiez les vues et leur orientation."
            )
        ctx.progress(0.45, "Extraction de la surface")
        field = _blur(np.pad(occupancy.astype(np.float32), 2), 0.9)
        grid_vertices, faces = surface_nets(field, 0.5)
        if len(faces) < 12:
            raise InvalidOutput("Surface trop petite : silhouette insuffisante.")
        ctx.progress(0.65, "Lissage")
        grid_vertices = taubin(grid_vertices, faces, int(params.get("smooth", 6)))
        positions = np.empty_like(grid_vertices)
        positions[:, 0] = (grid_vertices[:, 0] - 2 + 0.5 - nx / 2) * voxel
        positions[:, 1] = (grid_vertices[:, 1] - 2 + 0.5) * voxel
        positions[:, 2] = (grid_vertices[:, 2] - 2 + 0.5) * voxel - length / 2
        positions[:, 1] -= positions[:, 1].min()
        tri = positions[faces]
        volume = float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6)
        if volume < 0:
            faces = faces[:, ::-1]
        ctx.progress(0.8, "Projection des couleurs des références")
        normals = vertex_normals(positions, faces)
        colors = _project_colors(
            positions, normals, (length, height, width), side_rgb, end_rgb, top_rgb, end_ref
        )
        out_dir = Path(request.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        model_path = out_dir / "silhouette.glb"
        import trimesh

        trimesh.Trimesh(positions, faces, vertex_colors=colors, process=False).export(model_path)
        estimated.extend(
            [
                "Concavités (passages de roues, vitrages en retrait) non reconstruites",
                "Habitacle et soubassement non reconstruits",
            ]
        )
        report = {
            "engine": self.info.id,
            "views_used": used,
            "estimated": estimated,
            "dimensions_m": {
                "length": round(length, 3),
                "height": round(height, 3),
                "width": round(width, 3),
            },
            "voxels": [nx, ny, nz],
            "triangles": int(len(faces)),
        }
        report_path = out_dir / "report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        ctx.progress(1.0, "Modèle reconstruit")
        return EngineOutput(
            {"model": model_path, "report": report_path},
            "glb",
            data=report,
            warnings=warnings + [f"Zone estimée : {z}" for z in estimated],
            used_views=used,
        )


def _project_colors(positions, normals, dims, side_rgb, end_rgb, top_rgb, end_ref) -> np.ndarray:  # type: ignore[no-untyped-def]
    """Couleur de chaque sommet : vue la mieux orientée (profil, avant / arrière, dessus)."""
    length, height, width = dims

    def sample(rgb: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        h, w = rgb.shape[:2]
        cols = np.clip((u * (w - 1)).round().astype(int), 0, w - 1)
        rows = np.clip((v * (h - 1)).round().astype(int), 0, h - 1)
        return rgb[rows, cols].astype(float)

    u_len = np.clip((positions[:, 2] + length / 2) / length, 0, 1)  # 0 = avant
    v_h = np.clip(1 - positions[:, 1] / max(height, 1e-6), 0, 1)  # 0 = toit
    u_w = np.clip(positions[:, 0] / max(width, 1e-6) + 0.5, 0, 1)  # 0 = gauche
    colors = sample(side_rgb, u_len, v_h)
    weights = np.abs(normals[:, 0])
    if end_rgb is not None:
        facing = -normals[:, 2] if end_ref.view == "front" else normals[:, 2]
        use = facing > weights
        colors[use] = sample(end_rgb, u_w[use], v_h[use])
        weights = np.maximum(weights, facing)
    if top_rgb is not None:
        use = normals[:, 1] > np.maximum(weights, 0.35)
        colors[use] = sample(top_rgb, u_w[use], u_len[use])
    colors[normals[:, 1] < -0.6] = (34, 36, 40)  # soubassement (jamais visible)
    rgba = np.concatenate([colors, np.full((len(colors), 1), 255.0)], axis=1)
    return np.clip(rgba, 0, 255).astype(np.uint8)
