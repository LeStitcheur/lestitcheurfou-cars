"""Dictionnaires de textures (.ytd, et textures intégrées aux .yft / .ydr).

Disposition « gen8 » (vérifiée sur un fichier réel) :

- dictionnaire : liste de pointeurs vers les textures à ``+0x30`` (pointeur, nombre) ;
- texture : nom à ``+0x28``, largeur / hauteur / profondeur / pas / format à ``+0x50``,
  nombre de niveaux à ``+0x5D``, données (bloc graphique) à ``+0x70``.

Décodage : le niveau 0 est encapsulé dans un en-tête DDS et lu par Pillow (DXT1/3/5,
BC4/BC5, BC7) ou converti directement (formats non compressés). Un format inconnu n'est
jamais remplacé par une fausse image : ``TextureDecodeError`` explique la raison.
"""

from __future__ import annotations

import io
import struct
from dataclasses import dataclass

import numpy as np
from PIL import Image

from lsfcars.fivem.errors import FormatError
from lsfcars.fivem.rsc import Resource, View


class TextureDecodeError(Exception):
    """Texture lue mais non décodable : le message explique pourquoi."""


def _fourcc(text: str) -> int:
    return struct.unpack("<I", text.encode("ascii"))[0]


@dataclass(frozen=True)
class FormatInfo:
    name: str
    block_bytes: int  # octets par bloc 4x4 (compressé) ; 0 = non compressé
    bits_per_pixel: int  # non compressé
    alpha: bool
    dds_fourcc: bytes = b""
    dxgi: int = 0  # format DX10 (BC7)


FORMATS: dict[int, FormatInfo] = {
    _fourcc("DXT1"): FormatInfo("DXT1 (BC1)", 8, 0, False, b"DXT1"),
    _fourcc("DXT3"): FormatInfo("DXT3 (BC2)", 16, 0, True, b"DXT3"),
    _fourcc("DXT5"): FormatInfo("DXT5 (BC3)", 16, 0, True, b"DXT5"),
    _fourcc("ATI1"): FormatInfo("ATI1 (BC4)", 8, 0, False, b"ATI1"),
    _fourcc("ATI2"): FormatInfo("ATI2 (BC5)", 16, 0, False, b"ATI2"),
    _fourcc("BC7 "): FormatInfo("BC7", 16, 0, True, b"DX10", 98),
    21: FormatInfo("A8R8G8B8", 0, 32, True),
    22: FormatInfo("X8R8G8B8", 0, 32, False),
    25: FormatInfo("A1R5G5B5", 0, 16, True),
    28: FormatInfo("A8", 0, 8, True),
    32: FormatInfo("A8B8G8R8", 0, 32, True),
    50: FormatInfo("L8", 0, 8, False),
}


def format_name(code: int) -> str:
    info = FORMATS.get(code)
    if info is not None:
        return info.name
    raw = struct.pack("<I", code)
    if all(32 <= b < 127 for b in raw):
        return f"{raw.decode('ascii')} (non pris en charge)"
    return f"Format {code} (non pris en charge)"


def level_size(info: FormatInfo, width: int, height: int, stride: int, level: int) -> int:
    """Taille en octets du niveau ``level`` (le pas stocké ne vaut que pour le niveau 0)."""
    w, h = max(1, width >> level), max(1, height >> level)
    if info.block_bytes:
        return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * info.block_bytes
    pitch = stride if level == 0 and stride else (w * info.bits_per_pixel + 7) // 8
    return pitch * h


@dataclass
class Texture:
    name: str
    width: int
    height: int
    depth: int
    levels: int
    format_code: int
    stride: int
    data: bytes  # niveaux disponibles, à partir du niveau 0
    complete: bool = True  # False si les données sont tronquées ou absentes

    @property
    def format_name(self) -> str:
        return format_name(self.format_code)

    @property
    def info(self) -> FormatInfo | None:
        return FORMATS.get(self.format_code)

    @property
    def supported(self) -> bool:
        return self.info is not None

    @property
    def has_alpha_channel(self) -> bool:
        """Le format peut porter de la transparence (à confirmer par ``alpha_used``)."""
        info = self.info
        return bool(info and info.alpha)

    def chain_size(self, levels: int | None = None) -> int:
        info = self.info
        if info is None:
            return len(self.data)
        count = self.levels if levels is None else levels
        return sum(level_size(info, self.width, self.height, self.stride, i) for i in range(count))

    @property
    def memory_bytes(self) -> int:
        """Mémoire estimée de la chaîne de niveaux complète (telle que stockée)."""
        return self.chain_size()

    def level0(self) -> bytes:
        info = self.info
        if info is None:
            raise TextureDecodeError(
                f"Format {self.format_name} : décodage non pris en charge par cette version."
            )
        size = level_size(info, self.width, self.height, self.stride, 0)
        if len(self.data) < size:
            raise TextureDecodeError("Données de texture absentes ou tronquées (niveau 0 incomplet).")
        return self.data[:size]


# --- Lecture du dictionnaire -------------------------------------------------------


def read_texture(view: View) -> Texture:
    name = view.string(0x28) or "(sans nom)"
    width, height, depth, stride, code = struct.unpack("<HHHHI", view.raw(0x50, 12))
    levels = max(1, view.u8(0x5D))
    if not (0 < width <= 16384 and 0 < height <= 16384) or levels > 16:
        raise FormatError(f"Texture « {name} » : en-tête invalide ({width}×{height}, {levels} niveaux).")
    texture = Texture(name, width, height, max(1, depth), levels, code, stride, b"", False)
    data_view = view.ptr(0x70)
    if data_view is not None:
        wanted = texture.chain_size() if texture.info else stride * height
        available = len(data_view.block) - data_view.offset
        texture.data = data_view.block[data_view.offset : data_view.offset + min(wanted, available)]
        texture.complete = available >= wanted
    return texture


def read_dictionary(view: View) -> list[Texture]:
    """Dictionnaire de textures à la position ``view`` (racine d'un .ytd ou intégré)."""
    return [read_texture(item) for item in view.pointer_list(0x30, limit=4096)]


def parse_ytd(data: bytes) -> list[Texture]:
    resource = Resource.from_bytes(data)
    if resource.header.version != 13:
        raise FormatError(
            f"Ce fichier n'est pas un dictionnaire de textures (version RSC7 "
            f"{resource.header.version}, attendu 13)."
        )
    return read_dictionary(resource.root())


# --- Export et décodage --------------------------------------------------------------


def _uncompressed_pixel_format(code: int) -> bytes:
    rgb, alpha, luminance = 0x40, 0x1, 0x20000
    layouts = {
        21: (rgb | alpha, 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000),
        22: (rgb, 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0),
        32: (rgb | alpha, 32, 0x000000FF, 0x0000FF00, 0x00FF0000, 0xFF000000),
        25: (rgb | alpha, 16, 0x7C00, 0x03E0, 0x001F, 0x8000),
        28: (0x2, 8, 0, 0, 0, 0xFF),
        50: (luminance, 8, 0xFF, 0, 0, 0),
    }
    flags, bits, r, g, b, a = layouts[code]
    return struct.pack("<IIIIIIII", 32, flags, 0, bits, r, g, b, a)


def dds_bytes(texture: Texture, all_levels: bool = False) -> bytes:
    """Copie DDS (niveau 0 ou chaîne complète). Seuls les formats pris en charge sont exportés."""
    info = texture.info
    if info is None:
        raise TextureDecodeError(f"Format {texture.format_name} : export DDS impossible.")
    levels = texture.levels if all_levels and texture.complete else 1
    payload = texture.data[: texture.chain_size(levels)] if levels > 1 else texture.level0()
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | (0x20000 if levels > 1 else 0)
    if info.block_bytes:
        flags |= 0x80000
        pitch = level_size(info, texture.width, texture.height, texture.stride, 0)
        pixel_format = struct.pack("<II4sIIIII", 32, 0x4, info.dds_fourcc, 0, 0, 0, 0, 0)
    else:
        flags |= 0x8
        pitch = texture.stride or (texture.width * info.bits_per_pixel + 7) // 8
        pixel_format = _uncompressed_pixel_format(texture.format_code)
    caps = 0x1000 | (0x400008 if levels > 1 else 0)
    header = struct.pack(
        "<4sIIIIIII44x", b"DDS ", 124, flags, texture.height, texture.width, pitch, 0, levels
    )
    header += pixel_format + struct.pack("<IIII4x", caps, 0, 0, 0)
    if info.dxgi:
        header += struct.pack("<IIIII", info.dxgi, 3, 0, 1, 0)
    return header + payload


def decode(texture: Texture) -> Image.Image:
    """Image RGBA du niveau 0. Lève TextureDecodeError avec une explication sinon."""
    info = texture.info
    if info is None:
        raise TextureDecodeError(
            f"Format {texture.format_name} : décodage non pris en charge. La texture est listée "
            "mais aucun aperçu n'est généré (pas d'image de remplacement)."
        )
    if texture.depth > 1:
        raise TextureDecodeError("Texture volumique (3D) : aperçu non pris en charge.")
    raw = texture.level0()
    w, h = texture.width, texture.height
    if info.block_bytes:
        try:
            with Image.open(io.BytesIO(dds_bytes(texture))) as image:
                image.load()
                return image.convert("RGBA")
        except (OSError, ValueError, NotImplementedError) as exc:
            raise TextureDecodeError(f"Décodage {info.name} impossible : {exc}") from exc
    pitch = texture.stride or (w * info.bits_per_pixel + 7) // 8
    if pitch * h > len(raw):
        raise TextureDecodeError("Données de texture tronquées.")
    rows = np.frombuffer(raw, np.uint8)[: pitch * h].reshape(h, pitch)
    if texture.format_code in (21, 22, 32):
        pixels = rows[:, : w * 4].reshape(h, w, 4)
        rgba = pixels.copy() if texture.format_code == 32 else pixels[..., [2, 1, 0, 3]].copy()
        if texture.format_code == 22:
            rgba[..., 3] = 255
    elif texture.format_code == 25:
        value = np.ascontiguousarray(rows[:, : w * 2]).view("<u2").reshape(h, w).astype(np.uint32)
        rgba = np.empty((h, w, 4), np.uint8)
        rgba[..., 0] = ((value >> 10) & 0x1F) * 255 // 31
        rgba[..., 1] = ((value >> 5) & 0x1F) * 255 // 31
        rgba[..., 2] = (value & 0x1F) * 255 // 31
        rgba[..., 3] = np.where(value & 0x8000, 255, 0)
    elif texture.format_code == 28:
        rgba = np.zeros((h, w, 4), np.uint8)
        rgba[..., :3] = 255
        rgba[..., 3] = rows[:, :w]
    else:  # L8
        rgba = np.empty((h, w, 4), np.uint8)
        rgba[..., :3] = rows[:, :w, None]
        rgba[..., 3] = 255
    return Image.fromarray(rgba, "RGBA")


def alpha_used(image: Image.Image) -> bool:
    """La transparence est-elle réellement utilisée (au moins un pixel non opaque) ?"""
    if image.mode != "RGBA":
        return False
    low, _high = image.getchannel("A").getextrema()
    return low < 255


def png_bytes(image: Image.Image, max_side: int | None = None) -> bytes:
    if max_side and max(image.size) > max_side:
        image = image.copy()
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()
