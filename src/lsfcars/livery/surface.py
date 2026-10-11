"""Surface peinte : correspondance entre la carrosserie 3D et l'espace de la texture (UV).

- **Lancer de rayon** sur les maillages ciblés (triangle, barycentriques, point, normale).
- **Pinceau 3D** : les texels peints sont ceux dont la *position 3D* tombe dans la sphère du
  pinceau. Chaque triangle proche est rastérisé dans l'espace UV ; un trait traverse donc les
  coutures UV et touche tous les îlots concernés, sans projection écran.
- **Cartes de surface** (position, normale, triangle par texel) pour les bandes 3D, les zones
  (portières, capot, toit…), le remplissage d'îlot et la conversion UV → 3D.
- **Analyse UV** : îlots, UV absentes, hors limites, triangles dégénérés, chevauchements,
  coutures.
- **Placement orienté** : position, rotation, retournement et échelle d'un texte ou d'un logo
  déduits du jacobien UV local ; la symétrie gauche / droite passe par la géométrie 3D (plan
  de symétrie du véhicule) et non par un retournement de l'image.

Pur numpy (aucune dépendance Qt).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from lsfcars.scene import mathutils


@dataclass
class Hit:
    tri: int
    bary: np.ndarray  # (3,)
    point: np.ndarray  # monde
    normal: np.ndarray  # normale du triangle, tournée vers l'observateur (monde)
    distance: float
    node_id: str


@dataclass
class Placement:
    """Placement d'un élément 2D pour qu'il apparaisse droit et lisible sur la carrosserie."""

    x: float
    y: float
    rotation: float  # degrés (repère image, y vers le bas)
    flip: bool  # îlot UV « miroir » : l'élément doit être retourné pour se lire à l'endroit
    px_per_m: float
    stretch: float  # rapport d'échelle vertical / horizontal du dépliage (1 = isotrope)
    tri: int = -1  # triangle d'appui


@dataclass
class SurfaceMaps:
    resolution: tuple[int, int]  # (largeur, hauteur)
    position: np.ndarray  # (h, w, 3) float32
    normal: np.ndarray  # (h, w, 3) float32
    triangle: np.ndarray  # (h, w) int32, -1 : texel non couvert

    @property
    def coverage(self) -> np.ndarray:
        return self.triangle >= 0


@dataclass
class UVReport:
    parts_without_uv: list[str] = field(default_factory=list)
    triangles: int = 0
    islands: int = 0
    out_of_bounds: int = 0  # triangles débordant de [0, 1]
    degenerate: int = 0  # triangles d'aire UV nulle
    overlapping_islands: list[tuple[int, int]] = field(default_factory=list)
    overlap_ratio: float = 0.0  # part de la surface UV couverte plusieurs fois
    seam_edges: int = 0
    coverage_ratio: float = 0.0  # part de la texture utilisée
    texel_density: float = 0.0  # pixels par mètre (moyenne)
    density_spread: float = 0.0  # écart relatif de densité entre îlots (étirement)

    def warnings(self) -> list[str]:
        messages = []
        if self.parts_without_uv:
            messages.append(
                "UV absentes : "
                + ", ".join(self.parts_without_uv)
                + " (projection proposée, sur confirmation)."
            )
        if self.out_of_bounds:
            messages.append(f"{self.out_of_bounds} triangle(s) hors de l'espace UV [0, 1] (texture répétée).")
        if self.degenerate:
            messages.append(f"{self.degenerate} triangle(s) d'aire UV nulle : non peignables.")
        if self.overlapping_islands:
            messages.append(
                f"{len(self.overlapping_islands)} paire(s) d'îlots superposés "
                f"({self.overlap_ratio:.0%} de la "
                "surface) : peindre l'un modifie aussi l'autre."
            )
        if self.density_spread > 0.5:
            messages.append(
                f"Densité de texels irrégulière (écart {self.density_spread:.0%}) : étirements visibles."
            )
        return messages


class LiverySurface:
    """Triangles ciblés en coordonnées monde et pixels de la texture."""

    def __init__(
        self,
        tri_world: np.ndarray,
        tri_uv: np.ndarray,
        tri_node: np.ndarray,
        node_ids: list[str],
        node_names: list[str],
        width: int,
        height: int,
        frame: dict | None = None,
        parts_without_uv: list[str] | None = None,
    ) -> None:
        self.tri_world = np.asarray(tri_world, np.float64).reshape(-1, 3, 3)
        uv = np.asarray(tri_uv, np.float64).reshape(-1, 3, 2)
        self.raw_uv = uv
        # chaque triangle est ramené dans [0, 1] d'après son centre (texture répétée)
        self.tri_uv = uv - np.floor(uv.mean(axis=1, keepdims=True)) if len(uv) else uv
        self.tri_node = np.asarray(tri_node, np.int32)
        self.node_ids = node_ids
        self.node_names = node_names
        self.parts_without_uv = parts_without_uv or []
        self.frame = frame or {
            "up": np.array([0.0, 1.0, 0.0]),
            "forward": np.array([0.0, 0.0, -1.0]),
            "right": np.array([1.0, 0.0, 0.0]),
            "lateral_axis": 0,
            "mirror_origin": 0.0,
        }
        self._maps: dict[tuple[int, int], SurfaceMaps] = {}
        self._report: UVReport | None = None
        self._islands: np.ndarray | None = None
        e1 = self.tri_world[:, 1] - self.tri_world[:, 0]
        e2 = self.tri_world[:, 2] - self.tri_world[:, 0]
        cross = np.cross(e1, e2)
        area2 = np.linalg.norm(cross, axis=1)
        self.normals = np.divide(
            cross, area2[:, None], out=np.zeros_like(cross), where=area2[:, None] > 1e-12
        )
        self.world_area = area2 * 0.5
        self.centroids = self.tri_world.mean(axis=1)
        self.radii = (
            np.linalg.norm(self.tri_world - self.centroids[:, None], axis=2).max(axis=1)
            if len(self.tri_world)
            else np.zeros(0)
        )
        if len(self.tri_world):
            flat = self.tri_world.reshape(-1, 3)
            self.bounds = (flat.min(axis=0), flat.max(axis=0))
        else:
            self.bounds = (np.zeros(3), np.zeros(3))
        self.resize(width, height)

    def resize(self, width: int, height: int) -> None:
        self.width, self.height = int(width), int(height)
        self.tri_px = np.empty_like(self.tri_uv)
        if len(self.tri_uv):
            self.tri_px[..., 0] = self.tri_uv[..., 0] * self.width
            self.tri_px[..., 1] = (1.0 - self.tri_uv[..., 1]) * self.height
        self._maps.clear()
        self._report = None
        self.cache: dict = {}  # calculs dérivés des cartes (coordonnées véhicule, zones, îlots)

    # --- Construction ---------------------------------------------------------------------
    @classmethod
    def from_session(
        cls, session, material_ids: list[str], width: int, height: int, frame: dict | None = None
    ) -> LiverySurface:  # type: ignore[no-untyped-def]
        """Triangles des maillages utilisant les matériaux ciblés (transformations monde appliquées)."""
        scene = session.scene
        worlds, uvs, nodes, ids, names, missing = [], [], [], [], [], []
        wanted = set(material_ids)
        for node in scene.mesh_nodes():
            if node.material_id not in wanted or not scene.effective_visible(node.id):
                continue
            mesh = session.geometry_for(node)
            if mesh is None or not mesh.triangle_count:
                continue
            if mesh.uvs is None:
                missing.append(node.name)
                continue
            material = scene.materials.get(node.material_id)
            world = scene.world_matrix(node.id)
            positions = mathutils.transform_points(world, mesh.positions.astype(np.float64))
            uv = mesh.uvs.astype(np.float64)
            if material is not None:  # même transformation UV que le rendu
                uv = uv * np.asarray(material.uv_scale) + np.asarray(material.uv_offset)
            worlds.append(positions[mesh.indices])
            uvs.append(uv[mesh.indices])
            nodes.append(np.full(mesh.triangle_count, len(ids), np.int32))
            ids.append(node.id)
            names.append(node.name)
        if worlds:
            tri_world, tri_uv, tri_node = np.vstack(worlds), np.vstack(uvs), np.concatenate(nodes)
        else:
            tri_world, tri_uv, tri_node = np.zeros((0, 3, 3)), np.zeros((0, 3, 2)), np.zeros(0, np.int32)
        return cls(tri_world, tri_uv, tri_node, ids, names, width, height, frame, missing)

    @property
    def triangle_count(self) -> int:
        return len(self.tri_world)

    def texel_density(self) -> float:
        """Pixels de texture par mètre de carrosserie (moyenne pondérée par l'aire)."""
        world = self.world_area.sum()
        return float(math.sqrt(self._px_areas().sum() / world)) if world > 1e-12 else 0.0

    def _px_areas(self) -> np.ndarray:
        a = self.tri_px[:, 1] - self.tri_px[:, 0]
        b = self.tri_px[:, 2] - self.tri_px[:, 0]
        return np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]) * 0.5

    # --- Lancer de rayon ----------------------------------------------------------------------
    def raycast(self, origin, direction) -> Hit | None:  # type: ignore[no-untyped-def]
        if not self.triangle_count:
            return None
        origin = np.asarray(origin, np.float64)
        direction = np.asarray(direction, np.float64)
        direction = direction / max(np.linalg.norm(direction), 1e-12)
        v0 = self.tri_world[:, 0]
        e1 = self.tri_world[:, 1] - v0
        e2 = self.tri_world[:, 2] - v0
        p = np.cross(direction, e2)
        det = np.einsum("ij,ij->i", e1, p)
        valid = np.abs(det) > 1e-12
        inv = np.where(valid, 1.0 / np.where(valid, det, 1.0), 0.0)
        s = origin - v0
        u = np.einsum("ij,ij->i", s, p) * inv
        q = np.cross(s, e1)
        v = (q @ direction) * inv
        t = np.einsum("ij,ij->i", e2, q) * inv
        hit = valid & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) & (t > 1e-7)
        if not hit.any():
            return None
        candidates = np.flatnonzero(hit)
        best = int(candidates[np.argmin(t[candidates])])
        bary = np.array([1.0 - u[best] - v[best], u[best], v[best]])
        point = bary @ self.tri_world[best]
        normal = self.normals[best]
        if np.dot(normal, direction) > 0:  # face vue de dos (maillage double face)
            normal = -normal
        return Hit(best, bary, point, normal, float(t[best]), self.node_ids[self.tri_node[best]])

    def pixel_of(self, tri: int, bary: np.ndarray) -> tuple[float, float]:
        x, y = np.asarray(bary) @ self.tri_px[tri]
        return float(x), float(y)

    # --- Rastérisation ------------------------------------------------------------------------
    def _raster(self, tri: int, scale: tuple[float, float] = (1.0, 1.0), margin: float = 0.75):  # type: ignore[no-untyped-def]
        """Pixels d'un triangle (marge conservative en pixels) : (xs, ys, barycentriques)."""
        pts = self.tri_px[tri] * np.asarray(scale)
        w = int(round(self.width * scale[0]))
        h = int(round(self.height * scale[1]))
        x0, y0 = np.floor(pts.min(axis=0) - 1).astype(int)
        x1, y1 = np.ceil(pts.max(axis=0) + 1).astype(int)
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
        if x0 >= x1 or y0 >= y1:
            return None
        ys, xs = np.mgrid[y0:y1, x0:x1]
        px = xs + 0.5
        py = ys + 0.5
        (ax, ay), (bx, by), (cx, cy) = pts
        det = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(det) < 1e-12:
            return None
        l0 = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / det
        l1 = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / det
        l2 = 1.0 - l0 - l1
        if margin > 0:
            edges = np.array(
                [np.hypot(bx - cx, by - cy), np.hypot(cx - ax, cy - ay), np.hypot(ax - bx, ay - by)]
            )
            tol = margin / (abs(det) / np.maximum(edges, 1e-9))  # λi = distance au côté i / hauteur i
            inside = (l0 >= -tol[0]) & (l1 >= -tol[1]) & (l2 >= -tol[2])
        else:
            inside = (l0 > 1e-6) & (l1 > 1e-6) & (l2 > 1e-6)
        if not inside.any():
            return None
        lam = np.clip(np.stack([l0[inside], l1[inside], l2[inside]], axis=1), 0.0, None)
        lam /= np.maximum(lam.sum(axis=1, keepdims=True), 1e-12)
        return xs[inside], ys[inside], lam

    def brush_patches(
        self, point, radius: float, hardness: float, normal=None, facing: float = -0.25
    ) -> list[tuple[int, int, np.ndarray]]:  # type: ignore[no-untyped-def]
        """Empreintes du pinceau 3D : texels dont la position 3D est dans la sphère du pinceau.

        ``normal`` (normale au point touché) exclut les faces orientées à l'opposé (face
        intérieure d'une tôle fine, autre côté du véhicule).
        """
        if not self.triangle_count:
            return []
        point = np.asarray(point, np.float64)
        near = np.linalg.norm(self.centroids - point, axis=1) <= radius + self.radii
        if normal is not None:
            near &= (self.normals @ np.asarray(normal, np.float64)) > facing
        patches = []
        hard = max(0.0, min(1.0, hardness)) * radius
        for tri in np.flatnonzero(near):
            raster = self._raster(int(tri))
            if raster is None:
                continue
            xs, ys, lam = raster
            d = np.linalg.norm(lam @ self.tri_world[tri] - point, axis=1)
            soft = np.clip((radius - d) / max(radius - hard, 1e-6), 0.0, 1.0)
            alpha = soft * soft * (3.0 - 2.0 * soft)
            keep = alpha > 0
            if not keep.any():
                continue
            xs, ys, alpha = xs[keep], ys[keep], alpha[keep]
            x0, y0 = int(xs.min()), int(ys.min())
            patch = np.zeros((int(ys.max()) - y0 + 1, int(xs.max()) - x0 + 1), np.float32)
            np.maximum.at(patch, (ys - y0, xs - x0), alpha.astype(np.float32))
            patches.append((x0, y0, patch))
        return patches

    # --- Cartes de surface -----------------------------------------------------------------
    def maps(self, max_resolution: int = 2048) -> SurfaceMaps:
        scale = min(1.0, max_resolution / max(self.width, self.height))
        w, h = max(1, int(round(self.width * scale))), max(1, int(round(self.height * scale)))
        key = (w, h)
        if key not in self._maps:
            position = np.zeros((h, w, 3), np.float32)
            normal = np.zeros((h, w, 3), np.float32)
            triangle = np.full((h, w), -1, np.int32)
            sx, sy = w / self.width, h / self.height
            for tri in np.argsort(-self._px_areas()):  # petits triangles en dernier (détails prioritaires)
                raster = self._raster(int(tri), (sx, sy))
                if raster is None:
                    continue
                xs, ys, lam = raster
                position[ys, xs] = lam @ self.tri_world[tri]
                normal[ys, xs] = self.normals[tri]
                triangle[ys, xs] = tri
            self._maps[key] = SurfaceMaps((w, h), position, normal, triangle)
        return self._maps[key]

    def surface_at(self, x: float, y: float, search: int = 6) -> tuple[np.ndarray, np.ndarray, int] | None:
        """Point 3D, normale et triangle sous le pixel (x, y) de la texture (texel voisin au besoin)."""
        maps = self.maps()
        w, h = maps.resolution
        mx, my = int(x * w / self.width), int(y * h / self.height)
        for radius in range(search + 1):
            y0, y1 = max(my - radius, 0), min(my + radius + 1, h)
            x0, x1 = max(mx - radius, 0), min(mx + radius + 1, w)
            window = maps.triangle[y0:y1, x0:x1]
            found = np.argwhere(window >= 0)
            if len(found):
                cy, cx = found[np.argmin(np.abs(found - [my - y0, mx - x0]).sum(axis=1))]
                tri = int(window[cy, cx])
                return self._bary_px(tri, x, y) @ self.tri_world[tri], self.normals[tri], tri
        return None

    def _bary_px(self, tri: int, x: float, y: float) -> np.ndarray:
        (ax, ay), (bx, by), (cx, cy) = self.tri_px[tri]
        det = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(det) < 1e-12:
            return np.array([1 / 3, 1 / 3, 1 / 3])
        l0 = ((by - cy) * (x - cx) + (cx - bx) * (y - cy)) / det
        l1 = ((cy - ay) * (x - cx) + (ax - cx) * (y - cy)) / det
        lam = np.clip(np.array([l0, l1, 1 - l0 - l1]), 0, None)
        return lam / max(lam.sum(), 1e-12)

    # --- Point le plus proche, jacobien, placement -------------------------------------------
    def closest(self, point, normal=None, candidates: int = 96) -> tuple[int, np.ndarray, np.ndarray] | None:  # type: ignore[no-untyped-def]
        """Triangle, barycentriques et point de la surface les plus proches de ``point``."""
        if not self.triangle_count:
            return None
        point = np.asarray(point, np.float64)
        order = np.argsort(np.linalg.norm(self.centroids - point, axis=1))[:candidates]
        if normal is not None:  # même orientation (évite la face opposée d'une tôle)
            facing = order[(self.normals[order] @ np.asarray(normal, np.float64)) > 0.2]
            order = facing if len(facing) else order
        best = None
        for tri in order:
            a, b, c = self.tri_world[tri]
            n = self.normals[tri]
            v0, v1 = b - a, c - a
            v2 = (point - np.dot(point - a, n) * n) - a
            d00, d01, d11 = v0 @ v0, v0 @ v1, v1 @ v1
            d20, d21 = v2 @ v0, v2 @ v1
            denom = d00 * d11 - d01 * d01
            if abs(denom) < 1e-18:
                continue
            v = (d11 * d20 - d01 * d21) / denom
            w = (d00 * d21 - d01 * d20) / denom
            lam = np.clip(np.array([1 - v - w, v, w]), 0.0, None)
            lam /= max(lam.sum(), 1e-12)
            on = lam @ self.tri_world[tri]
            distance = float(np.linalg.norm(on - point))
            if best is None or distance < best[0]:
                best = (distance, int(tri), lam, on)
        if best is None:
            return None
        return best[1], best[2], best[3]

    def jacobian(self, tri: int) -> np.ndarray:
        """Matrice 2x3 : déplacement 3D (dans le plan du triangle) → déplacement en pixels."""
        world = self.tri_world[tri]
        px = self.tri_px[tri]
        e = np.stack([world[1] - world[0], world[2] - world[0]], axis=1)  # 3x2
        f = np.stack([px[1] - px[0], px[2] - px[0]], axis=1)  # 2x2
        gram = e.T @ e
        if abs(np.linalg.det(gram)) < 1e-18:
            return np.zeros((2, 3))
        return f @ np.linalg.inv(gram) @ e.T

    def placement(self, point, normal=None) -> Placement | None:  # type: ignore[no-untyped-def]
        """Placement lisible en ``point`` : l'axe de lecture suit la carrosserie, le haut reste en haut."""
        found = self.closest(point, normal)
        if found is None:
            return None
        tri, lam, _on = found
        n = self.normals[tri].copy()
        if normal is not None and np.dot(n, normal) < 0:
            n = -n
        up = np.asarray(self.frame["up"], np.float64)
        reading = np.cross(up, n)  # droite d'un observateur placé face à la surface
        if np.linalg.norm(reading) < 0.3:  # surface horizontale (toit, capot) : lecture vers la droite
            reading = np.asarray(self.frame["right"], np.float64)
            reading = reading - np.dot(reading, n) * n
        reading /= max(np.linalg.norm(reading), 1e-12)
        top = np.cross(n, reading)
        top /= max(np.linalg.norm(top), 1e-12)
        jac = self.jacobian(tri)
        a = jac @ reading  # direction de lecture en pixels
        b = jac @ top  # direction « haut » en pixels (axe y de l'image vers le bas)
        if np.linalg.norm(a) < 1e-9:
            return None
        angle = math.degrees(math.atan2(a[1], a[0]))
        flip = float(a[0] * b[1] - a[1] * b[0]) > 0  # orientation inversée : îlot miroir
        x, y = self.pixel_of(tri, lam)
        stretch = float(np.linalg.norm(b) / np.linalg.norm(a))
        return Placement(x, y, angle, flip, float(np.linalg.norm(a)), stretch, tri)

    def mirror_point(self, point) -> np.ndarray:  # type: ignore[no-untyped-def]
        """Symétrique par rapport au plan de symétrie gauche / droite du véhicule."""
        point = np.array(point, np.float64)
        axis = int(self.frame.get("lateral_axis", 0))
        point[axis] = 2 * float(self.frame.get("mirror_origin", 0.0)) - point[axis]
        return point

    def mirror_vector(self, vector) -> np.ndarray:  # type: ignore[no-untyped-def]
        vector = np.array(vector, np.float64)
        vector[int(self.frame.get("lateral_axis", 0))] *= -1
        return vector

    def mirror_pixel(self, x: float, y: float) -> tuple[Placement, np.ndarray] | None:
        """Placement symétrique (côté opposé du véhicule) d'un pixel de texture."""
        found = self.surface_at(x, y)
        if found is None:
            return None
        point, normal, _tri = found
        target = self.mirror_point(point)
        placement = self.placement(target, self.mirror_vector(normal))
        return (placement, target) if placement is not None else None

    # --- Analyse UV --------------------------------------------------------------------------
    def uv_report(self) -> UVReport:
        if self._report is not None:
            return self._report
        report = UVReport(parts_without_uv=list(self.parts_without_uv), triangles=self.triangle_count)
        if not self.triangle_count:
            self._report = report
            return report
        raw = self.raw_uv
        report.out_of_bounds = int(((raw < -1e-4) | (raw > 1 + 1e-4)).any(axis=(1, 2)).sum())
        px_area = self._px_areas()
        report.degenerate = int((px_area < 1e-9 * self.width * self.height).sum())
        islands = self.islands()
        report.islands = int(islands.max()) + 1 if len(islands) else 0
        report.seam_edges = len(self.seam_segments())
        report.texel_density = self.texel_density()
        density = []
        total = max(float(self.world_area.sum()), 1e-12)
        for island in range(report.islands):
            sel = islands == island
            world = self.world_area[sel].sum()
            if world > 0.02 * total:  # les petits îlots (rétroviseurs, détails) ne comptent pas
                density.append(math.sqrt(px_area[sel].sum() / world))
        if density:
            report.density_spread = float(
                (max(density) - min(density)) / max(float(np.median(density)), 1e-9)
            )
        maps = self.maps(512)
        w, h = maps.resolution
        report.coverage_ratio = float(maps.coverage.mean())
        counts = np.zeros((h, w), np.int16)
        owner = np.full((h, w), -1, np.int32)
        pairs: set[tuple[int, int]] = set()
        sx, sy = w / self.width, h / self.height
        for island in range(report.islands):
            stamp = np.zeros((h, w), bool)
            for tri in np.flatnonzero(islands == island):
                raster = self._raster(int(tri), (sx, sy), margin=0.0)
                if raster is not None:
                    stamp[raster[1], raster[0]] = True
            clash = stamp & (owner >= 0)
            if clash.any():
                others, counts_per = np.unique(owner[clash], return_counts=True)
                for other, count in zip(others, counts_per, strict=True):
                    if count >= 4:  # plus que quelques texels de bord
                        pairs.add((int(other), island))
            counts += stamp
            owner[stamp] = island
        report.overlapping_islands = sorted(pairs)
        report.overlap_ratio = float((counts > 1).sum() / max(int((counts > 0).sum()), 1))
        self._report = report
        return report

    def _corner_keys(self) -> tuple[np.ndarray, np.ndarray]:
        pos = np.round(self.tri_world.reshape(-1, 3) * 1e4).astype(np.int64)
        uv = np.round(self.tri_uv.reshape(-1, 2) * 1e5).astype(np.int64)
        node = np.repeat(self.tri_node, 3)[:, None].astype(np.int64)
        _, pos_id = np.unique(np.hstack([node, pos]), axis=0, return_inverse=True)
        _, full_id = np.unique(np.hstack([node, pos, uv]), axis=0, return_inverse=True)
        return pos_id.reshape(-1, 3), full_id.reshape(-1, 3)

    def islands(self) -> np.ndarray:
        """Numéro d'îlot UV de chaque triangle (triangles reliés par une arête UV commune)."""
        if self._islands is not None:
            return self._islands
        if not self.triangle_count:
            return np.zeros(0, np.int32)
        _pos, full = self._corner_keys()
        parent = list(range(self.triangle_count))

        def root(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        edges: dict[tuple[int, int], int] = {}
        for tri, corners in enumerate(full.tolist()):
            for a, b in ((0, 1), (1, 2), (2, 0)):
                key = (min(corners[a], corners[b]), max(corners[a], corners[b]))
                other = edges.setdefault(key, tri)
                if other != tri:
                    ra, rb = root(tri), root(other)
                    if ra != rb:
                        parent[ra] = rb
        roots = np.array([root(i) for i in range(self.triangle_count)])
        _, labels = np.unique(roots, return_inverse=True)
        self._islands = labels.astype(np.int32)
        return self._islands

    def seam_segments(self) -> np.ndarray:
        """Coutures : arêtes 3D partagées dont les UV diffèrent de part et d'autre (N, 2, 2) en pixels."""
        if not self.triangle_count:
            return np.zeros((0, 2, 2))
        pos, full = self._corner_keys()
        seen: dict[tuple[int, int], tuple[int, int]] = {}
        segments = []
        pos_l, full_l = pos.tolist(), full.tolist()
        for tri in range(self.triangle_count):
            for a, b in ((0, 1), (1, 2), (2, 0)):
                key = (min(pos_l[tri][a], pos_l[tri][b]), max(pos_l[tri][a], pos_l[tri][b]))
                uv_key = (min(full_l[tri][a], full_l[tri][b]), max(full_l[tri][a], full_l[tri][b]))
                if key in seen:
                    if seen[key] != uv_key:
                        segments.append(self.tri_px[tri, [a, b]])
                else:
                    seen[key] = uv_key
        return np.array(segments) if segments else np.zeros((0, 2, 2))

    def uv_segments(self) -> np.ndarray:
        """Arêtes du dépliage (N, 2, 2) en pixels, sans doublons (affichage des UV)."""
        if not self.triangle_count:
            return np.zeros((0, 2, 2))
        _pos, full = self._corner_keys()
        pairs = np.concatenate([full[:, [0, 1]], full[:, [1, 2]], full[:, [2, 0]]])
        coords = np.concatenate([self.tri_px[:, [0, 1]], self.tri_px[:, [1, 2]], self.tri_px[:, [2, 0]]])
        pairs.sort(axis=1)
        _, first = np.unique(pairs, axis=0, return_index=True)
        return coords[np.sort(first)]

    def island_bounds(self, tri: int) -> tuple[float, float, float, float]:
        """Rectangle (pixels) de l'îlot UV contenant le triangle ``tri``."""
        labels = self.islands()
        key = ("island_bounds", int(labels[tri]))
        if key not in self.cache:
            pts = self.tri_px[labels == labels[tri]].reshape(-1, 2)
            x0, y0 = pts.min(axis=0)
            x1, y1 = pts.max(axis=0)
            self.cache[key] = (float(x0), float(y0), float(x1), float(y1))
        return self.cache[key]

    def island_mask(self, x: float, y: float) -> np.ndarray | None:
        """Masque (pleine résolution) de l'îlot UV sous le pixel (x, y)."""
        found = self.surface_at(x, y, search=2)
        if found is None:
            return None
        labels = self.islands()
        mask = np.zeros((self.height, self.width), bool)
        for tri in np.flatnonzero(labels == labels[found[2]]):
            raster = self._raster(int(tri))
            if raster is not None:
                mask[raster[1], raster[0]] = True
        return mask
