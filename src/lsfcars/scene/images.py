"""Images de projet (calques raster, masques) : tampons RGBA décodés à la demande.

Une image est conservée encodée (PNG) tant qu'elle n'est pas utilisée : un projet contenant de
nombreux calques 4K n'occupe en mémoire que les calques affichés. ``array`` décode au premier
accès ; ``release`` libère la version décodée (réencodée si elle a changé).
Pur numpy + Pillow : aucune dépendance Qt.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image


def encode_png(array: np.ndarray) -> bytes:
    array = np.ascontiguousarray(array)
    mode = "L" if array.ndim == 2 else "RGBA"
    buffer = io.BytesIO()
    Image.fromarray(array, mode).save(buffer, format="PNG", compress_level=3)
    return buffer.getvalue()


def decode_png(data: bytes, channels: int = 4) -> np.ndarray:
    with Image.open(io.BytesIO(data)) as image:
        converted = image.convert("L" if channels == 1 else "RGBA")
        return np.array(converted, dtype=np.uint8)


class ImageBuffer:
    """Tampon d'image (H, W, 4) ou masque (H, W) uint8, ligne 0 = haut de l'image (v = 1)."""

    def __init__(self, array: np.ndarray | None = None, png: bytes | None = None, channels: int = 4) -> None:
        if array is None and png is None:
            raise ValueError("image vide")
        self._array = None if array is None else np.ascontiguousarray(array, dtype=np.uint8)
        self._png = png
        self.channels = channels if array is None else (1 if array.ndim == 2 else 4)
        self.version = 0
        self._encoded_version = 0 if png is not None else -1
        if self._array is not None:
            self._shape = self._array.shape[:2]
        else:
            with Image.open(io.BytesIO(png)) as image:  # type: ignore[arg-type]
                self._shape = (image.height, image.width)

    @classmethod
    def blank(cls, width: int, height: int, color=(0, 0, 0, 0), channels: int = 4) -> ImageBuffer:  # type: ignore[no-untyped-def]
        if channels == 1:
            value = int(color[0]) if hasattr(color, "__len__") else int(color)
            return cls(np.full((height, width), value, np.uint8))
        array = np.empty((height, width, 4), np.uint8)
        array[:] = np.asarray(color, np.uint8)
        return cls(array)

    @property
    def width(self) -> int:
        return int(self._shape[1])

    @property
    def height(self) -> int:
        return int(self._shape[0])

    @property
    def decoded(self) -> bool:
        return self._array is not None

    @property
    def array(self) -> np.ndarray:
        if self._array is None:
            assert self._png is not None
            self._array = decode_png(self._png, self.channels)
        return self._array

    def touch(self) -> None:
        """Signale une modification en place du tableau décodé."""
        self.version += 1

    def png(self) -> bytes:
        if self._png is None or self._encoded_version != self.version:
            self._png = encode_png(self.array)
            self._encoded_version = self.version
        return self._png

    def release(self) -> bool:
        """Libère la version décodée (réencodée au besoin) : retourne True si libérée."""
        if self._array is None:
            return False
        self.png()
        self._array = None
        return True

    def copy(self) -> ImageBuffer:
        if self._array is None:
            return ImageBuffer(png=self._png, channels=self.channels)
        return ImageBuffer(self._array.copy())

    def nbytes(self) -> int:
        if self._array is not None:
            return int(self._array.nbytes)
        return len(self._png or b"")
