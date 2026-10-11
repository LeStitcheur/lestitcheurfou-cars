"""Représentation CPU d'un maillage prêt à être envoyé au GPU."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

DEFAULT_COLOR = (0.72, 0.74, 0.78, 1.0)


def compute_vertex_normals(positions: np.ndarray, indices: np.ndarray) -> np.ndarray:
    """Normales par sommet pondérées par l'aire des triangles adjacents."""
    positions = np.asarray(positions, dtype=np.float64).reshape(-1, 3)
    indices = np.asarray(indices, dtype=np.int64).reshape(-1, 3)
    normals = np.zeros_like(positions)
    if len(indices):
        tri = positions[indices]
        face_normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])  # norme = 2 x aire
        for corner in range(3):
            np.add.at(normals, indices[:, corner], face_normals)
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = np.divide(normals, lengths, out=np.zeros_like(normals), where=lengths > 1e-12)
    normals[lengths[:, 0] <= 1e-12] = (0.0, 1.0, 0.0)
    return normals.astype(np.float32)


@dataclass
class MeshData:
    """Maillage triangulé : positions, normales et couleurs par sommet, indices par triangle."""

    name: str
    positions: np.ndarray  # (N, 3) float32
    indices: np.ndarray  # (M, 3) uint32
    normals: np.ndarray | None = None  # (N, 3) float32, calculées si absentes
    colors: np.ndarray | None = None  # (N, 4) uint8, déduites de ``color`` si absentes
    color: tuple[float, float, float, float] = DEFAULT_COLOR  # couleur représentative
    _bounds: tuple[np.ndarray, np.ndarray] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.positions = np.ascontiguousarray(self.positions, dtype=np.float32).reshape(-1, 3)
        self.indices = np.ascontiguousarray(self.indices, dtype=np.uint32).reshape(-1, 3)
        if self.indices.size and int(self.indices.max()) >= len(self.positions):
            raise ValueError("indice de sommet hors limites")
        if self.normals is None:
            self.normals = compute_vertex_normals(self.positions, self.indices)
        self.normals = np.ascontiguousarray(self.normals, dtype=np.float32).reshape(-1, 3)
        if self.normals.shape != self.positions.shape:
            raise ValueError("positions et normales doivent avoir la même forme")
        if self.colors is None:
            rgba = np.clip(np.asarray(self.color, dtype=np.float64) * 255.0, 0, 255)
            self.colors = np.tile(rgba.astype(np.uint8), (len(self.positions), 1))
        self.colors = np.ascontiguousarray(self.colors, dtype=np.uint8).reshape(-1, 4)
        if len(self.colors) != len(self.positions):
            raise ValueError("une couleur par sommet est attendue")

    @property
    def vertex_count(self) -> int:
        return len(self.positions)

    @property
    def triangle_count(self) -> int:
        return len(self.indices)

    @property
    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        """Boîte englobante alignée (min, max) en coordonnées locales."""
        if self._bounds is None:
            if self.vertex_count:
                self._bounds = (self.positions.min(axis=0), self.positions.max(axis=0))
            else:
                self._bounds = (np.zeros(3, np.float32), np.zeros(3, np.float32))
        return self._bounds


def combined_bounds(meshes: list[MeshData]) -> tuple[np.ndarray, np.ndarray] | None:
    if not meshes:
        return None
    mins = np.min([m.bounds[0] for m in meshes], axis=0)
    maxs = np.max([m.bounds[1] for m in meshes], axis=0)
    return mins, maxs
