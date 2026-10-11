"""Ressources RSC7 (.yft, .ytd, .ydr, .ybn…) : en-tête, décompression, pointeurs.

Un fichier ressource commence par 16 octets : ``"RSC7"``, version, drapeaux du bloc système,
drapeaux du bloc graphique. Le reste est un flux « deflate » brut contenant le bloc système
suivi du bloc graphique. Les pointeurs internes ``0x5xxxxxxx`` visent le bloc système,
``0x6xxxxxxx`` le bloc graphique.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from lsfcars.fivem.errors import FormatError, ProtectedResourceError

MAGIC = b"RSC7"
MAX_RESOURCE = 768 << 20  # 768 Mio décompressés : garde-fou mémoire

KNOWN_VERSIONS = {
    13: "Dictionnaire de textures (.ytd)",
    43: "Collision (.ybn)",
    162: "Fragment / modèle de véhicule (.yft)",
    165: "Drawable (.ydr)",
    2: "Archétypes (.ytyp)",
}


def block_size(flags: int) -> int:
    """Taille d'un bloc d'après ses drapeaux (pages de tailles multiples de la page de base)."""
    counts = (
        ((flags >> 27) & 0x1) << 0,
        ((flags >> 26) & 0x1) << 1,
        ((flags >> 25) & 0x1) << 2,
        ((flags >> 24) & 0x1) << 3,
        ((flags >> 17) & 0x7F) << 4,
        ((flags >> 11) & 0x3F) << 5,
        ((flags >> 7) & 0xF) << 6,
        ((flags >> 5) & 0x3) << 7,
        ((flags >> 4) & 0x1) << 8,
    )
    return (0x200 << (flags & 0xF)) * sum(counts)


@dataclass(frozen=True)
class ResourceHeader:
    version: int
    sys_flags: int
    gfx_flags: int

    @property
    def sys_size(self) -> int:
        return block_size(self.sys_flags)

    @property
    def gfx_size(self) -> int:
        return block_size(self.gfx_flags)

    @property
    def kind(self) -> str:
        return KNOWN_VERSIONS.get(self.version, f"Ressource inconnue (version {self.version})")


def read_header(data: bytes) -> ResourceHeader:
    if len(data) < 16:
        raise FormatError("Ressource tronquée : en-tête RSC7 incomplet.")
    if data[:4] == b"RSC8":
        raise FormatError("Ressource RSC8 (format « gen9 » des éditions récentes) : non prise en charge.")
    if data[:4] != MAGIC:
        raise ProtectedResourceError(
            "En-tête RSC7 absent. Le fichier est soit corrompu, soit chiffré (par exemple "
            "par FiveM Asset Escrow). Un fichier chiffré n'est jamais déchiffré : utilisez la "
            "version non protégée fournie par l'auteur."
        )
    version, sys_flags, gfx_flags = struct.unpack_from("<III", data, 4)
    return ResourceHeader(version, sys_flags, gfx_flags)


class View:
    """Position dans un bloc de ressource, avec accès typés relatifs."""

    __slots__ = ("block", "offset", "resource")

    def __init__(self, resource: Resource, block: bytes, offset: int) -> None:
        self.resource = resource
        self.block = block
        self.offset = offset

    def _check(self, rel: int, size: int) -> int:
        at = self.offset + rel
        if at < 0 or at + size > len(self.block):
            raise FormatError("Ressource corrompue : lecture hors limites.")
        return at

    def u8(self, rel: int) -> int:
        return self.block[self._check(rel, 1)]

    def u16(self, rel: int) -> int:
        return struct.unpack_from("<H", self.block, self._check(rel, 2))[0]

    def i16(self, rel: int) -> int:
        return struct.unpack_from("<h", self.block, self._check(rel, 2))[0]

    def u32(self, rel: int) -> int:
        return struct.unpack_from("<I", self.block, self._check(rel, 4))[0]

    def u64(self, rel: int) -> int:
        return struct.unpack_from("<Q", self.block, self._check(rel, 8))[0]

    def floats(self, rel: int, count: int) -> tuple[float, ...]:
        return struct.unpack_from(f"<{count}f", self.block, self._check(rel, 4 * count))

    def raw(self, rel: int, size: int) -> bytes:
        at = self._check(rel, size)
        return self.block[at : at + size]

    def ptr(self, rel: int) -> View | None:
        """Suit le pointeur 64 bits situé à ``rel`` ; None s'il est nul."""
        return self.resource.resolve(self.u64(rel))

    def string(self, rel: int) -> str:
        """Chaîne visée par le pointeur situé à ``rel`` (vide si pointeur nul)."""
        target = self.ptr(rel)
        return target.cstring() if target is not None else ""

    def cstring(self, limit: int = 512) -> str:
        end = self.block.find(b"\0", self.offset, self.offset + limit)
        if end < 0:
            raise FormatError("Ressource corrompue : chaîne non terminée.")
        return self.block[self.offset : end].decode("utf-8", errors="replace")

    def pointer_list(self, rel: int, limit: int = 100_000) -> list[View]:
        """Liste ``(pointeur, nombre:u16)`` de pointeurs 64 bits vers des structures."""
        array = self.ptr(rel)
        count = self.u16(rel + 8)
        if array is None or count == 0:
            return []
        if count > limit:
            raise FormatError("Ressource corrompue : liste trop longue.")
        result = []
        for index in range(count):
            target = array.ptr(index * 8)
            if target is not None:
                result.append(target)
        return result


class Resource:
    """Ressource RSC7 décompressée : blocs système et graphique."""

    def __init__(self, header: ResourceHeader, system: bytes, graphics: bytes) -> None:
        self.header = header
        self.system = system
        self.graphics = graphics

    @classmethod
    def from_bytes(cls, data: bytes) -> Resource:
        header = read_header(data)
        sys_size, gfx_size = header.sys_size, header.gfx_size
        expected = sys_size + gfx_size
        if expected <= 0:
            raise FormatError("Ressource invalide : blocs vides.")
        if expected > MAX_RESOURCE:
            raise FormatError("Ressource trop volumineuse pour être analysée en sécurité.")
        try:
            inflater = zlib.decompressobj(-15)
            payload = inflater.decompress(data[16:], expected)
        except zlib.error as exc:
            raise FormatError(f"Ressource corrompue : décompression impossible ({exc}).") from exc
        if len(payload) < sys_size:
            raise FormatError("Ressource tronquée : bloc système incomplet.")
        return cls(header, payload[:sys_size], payload[sys_size:expected])

    def resolve(self, pointer: int) -> View | None:
        if pointer == 0:
            return None
        segment, offset = pointer >> 28, pointer & 0x0FFFFFFF
        if segment == 5:
            block = self.system
        elif segment == 6:
            block = self.graphics
        else:
            raise FormatError(f"Ressource corrompue : pointeur invalide 0x{pointer:X}.")
        if offset >= len(block):
            raise FormatError("Ressource corrompue : pointeur hors limites.")
        return View(self, block, offset)

    def root(self) -> View:
        return View(self, self.system, 0)


def joaat(text: str) -> int:
    """Hachage « Jenkins one-at-a-time » utilisé par GTA V pour les noms."""
    value = 0
    for byte in text.lower().encode("utf-8"):
        value = (value + byte) & 0xFFFFFFFF
        value = (value + (value << 10)) & 0xFFFFFFFF
        value ^= value >> 6
    value = (value + (value << 3)) & 0xFFFFFFFF
    value ^= value >> 11
    return (value + (value << 15)) & 0xFFFFFFFF
