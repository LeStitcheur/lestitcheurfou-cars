"""Archives RPF7 (GTA V) : lecture des archives non chiffrées uniquement.

Structure (vérifiée sur une archive d'addon réelle) :

- en-tête de 16 octets : ``"7FPR"``, nombre d'entrées, taille du bloc de noms, chiffrement ;
- table des entrées (16 octets chacune), puis bloc de noms (chaînes terminées par ``\\0``) ;
- entrée 0 = racine. Dossier : ``(nom, 0x7FFFFF00, premier index, nombre)`` ;
- fichier binaire : nom (16 bits), taille stockée (24 bits), position / 512 (24 bits),
  taille réelle, drapeau de chiffrement. Taille stockée non nulle = flux « deflate » brut ;
- fichier ressource (bit 31 du second mot) : nom, taille stockée, position / 512,
  drapeaux système et graphiques. Les données commencent par l'en-tête RSC7 complet.

Les archives officielles de GTA V sont chiffrées (AES ou « NG »). Elles sont détectées et
refusées avec une explication : aucun déchiffrement, aucun contournement.
"""

from __future__ import annotations

import mmap
import struct
import zlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from lsfcars.fivem.errors import EncryptedError, FormatError

MAGIC = b"7FPR"
ENC_NONE = 0
ENC_OPEN = 0x4E45504F  # « OPEN » : archive non chiffrée (addons, OpenIV)
ENC_AES = 0x0FFFFFF9
ENC_NG = 0x0FEFFFFF
DIRECTORY_IDENT = 0x7FFFFF00
BLOCK = 512
MAX_ENTRIES = 1_000_000
MAX_EXTRACT = 1 << 30  # 1 Gio par fichier extrait : garde-fou mémoire

ENCRYPTION_LABELS = {
    ENC_NONE: "aucun",
    ENC_OPEN: "OPEN (non chiffrée)",
    ENC_AES: "AES (archive officielle)",
    ENC_NG: "NG (archive officielle)",
}

ENCRYPTED_EXPLANATION = (
    "Cette archive RPF est chiffrée ({label}). C'est le cas des archives officielles de "
    "GTA V. LeStitcheurFou Cars ne déchiffre pas les archives et ne contourne aucune "
    "protection. Pour travailler sur ces fichiers, exportez-les depuis votre propre "
    "installation avec un outil de modding compatible, sous votre responsabilité, puis "
    "importez les fichiers obtenus (dossier, .yft, .ytd, .meta) ou une archive non chiffrée."
)


def encryption_label(value: int) -> str:
    return ENCRYPTION_LABELS.get(value, f"inconnu (0x{value:08X})")


@dataclass
class RpfEntry:
    name: str
    path: str  # chemin interne, séparateurs « / »

    @property
    def extension(self) -> str:
        dot = self.name.rfind(".")
        return self.name[dot:].lower() if dot > 0 else ""


@dataclass
class RpfDirectory(RpfEntry):
    entries: list[RpfEntry] = field(default_factory=list)


@dataclass
class RpfFile(RpfEntry):
    offset: int = 0  # position absolue dans la source
    stored_size: int = 0  # 0 = stocké tel quel (binaire)
    size: int = 0  # taille réelle (binaire) ou taille stockée (ressource)
    is_resource: bool = False
    encrypted: bool = False
    sys_flags: int = 0
    gfx_flags: int = 0

    @property
    def compressed(self) -> bool:
        return not self.is_resource and self.stored_size not in (0, self.size)


def _read_header(data: bytes | mmap.mmap, base: int) -> tuple[int, int, int]:
    if base + 16 > len(data):
        raise FormatError("Archive RPF tronquée : en-tête incomplet.")
    magic, count, names_length, encryption = struct.unpack_from("<4sIII", data, base)
    if magic != MAGIC:
        raise FormatError("Ce fichier n'est pas une archive RPF7 (signature absente).")
    return count, names_length, encryption


def probe(path: str | Path) -> tuple[int, int]:
    """Lit seulement l'en-tête : (nombre d'entrées, chiffrement). Ne lève que FormatError/OSError."""
    with open(path, "rb") as fh:
        head = fh.read(16)
    count, _names, encryption = _read_header(head, 0)
    return count, encryption


class RpfArchive:
    """Archive RPF7 ouverte en lecture seule (fichier projeté en mémoire ou octets)."""

    def __init__(self, data: bytes | mmap.mmap, base: int = 0, name: str = "archive.rpf") -> None:
        self._data = data
        self._base = base
        self._mmap: mmap.mmap | None = None
        self._file = None
        self.name = name
        count, names_length, encryption = _read_header(data, base)
        self.encryption = encryption
        self.entry_count = count
        if encryption not in (ENC_NONE, ENC_OPEN):
            raise EncryptedError(ENCRYPTED_EXPLANATION.format(label=encryption_label(encryption)))
        if not 0 < count <= MAX_ENTRIES:
            raise FormatError(f"Archive RPF invalide : {count} entrées annoncées.")
        toc = base + 16
        names_at = toc + count * 16
        if names_at + names_length > len(data):
            raise FormatError("Archive RPF tronquée : table des entrées incomplète.")
        self._names = bytes(data[names_at : names_at + names_length])
        self._raw = [bytes(data[toc + i * 16 : toc + i * 16 + 16]) for i in range(count)]
        self.root = self._build(0, "")
        if not isinstance(self.root, RpfDirectory):
            raise FormatError("Archive RPF invalide : la racine n'est pas un dossier.")

    # --- Ouverture -------------------------------------------------------------
    @classmethod
    def open(cls, path: str | Path) -> RpfArchive:
        path = Path(path)
        fh = open(path, "rb")  # noqa: SIM115 (fermé par close())
        try:
            if path.stat().st_size < 16:
                raise FormatError("Archive RPF tronquée : fichier trop petit.")
            mapped = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
        except Exception:
            fh.close()
            raise
        try:
            archive = cls(mapped, 0, path.name)
        except Exception:
            mapped.close()
            fh.close()
            raise
        archive._mmap, archive._file = mapped, fh
        return archive

    @classmethod
    def from_bytes(cls, data: bytes, name: str = "archive.rpf") -> RpfArchive:
        return cls(data, 0, name)

    def close(self) -> None:
        if self._mmap is not None:
            self._mmap.close()
            self._mmap = None
        if self._file is not None:
            self._file.close()
            self._file = None

    def __enter__(self) -> RpfArchive:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # --- Table des entrées -----------------------------------------------------
    def _name(self, offset: int) -> str:
        if offset >= len(self._names):
            raise FormatError("Archive RPF invalide : nom d'entrée hors limites.")
        end = self._names.find(b"\0", offset)
        raw = self._names[offset : end if end >= 0 else len(self._names)]
        return raw.decode("utf-8", errors="replace")

    def _build(self, index: int, parent_path: str, depth: int = 0) -> RpfEntry:
        if depth > 64:
            raise FormatError("Archive RPF invalide : arborescence trop profonde (boucle ?).")
        raw = self._raw[index]
        _x, y = struct.unpack_from("<II", raw)
        if y == DIRECTORY_IDENT:
            name_offset, _ident, first, count = struct.unpack_from("<IIII", raw)
            name = "" if index == 0 else self._name(name_offset)
            path = f"{parent_path}/{name}".strip("/") if name else parent_path
            directory = RpfDirectory(name, path)
            if first + count > len(self._raw) or (count and first <= index):
                raise FormatError("Archive RPF invalide : dossier hors limites.")
            for child in range(first, first + count):
                directory.entries.append(self._build(child, path, depth + 1))
            return directory
        if y & 0x80000000 == 0:
            (packed,) = struct.unpack_from("<Q", raw)
            stored = (packed >> 16) & 0xFFFFFF
            offset = ((packed >> 40) & 0xFFFFFF) * BLOCK
            size, encrypted = struct.unpack_from("<II", raw, 8)
            name = self._name(packed & 0xFFFF)
            return RpfFile(
                name,
                f"{parent_path}/{name}".strip("/"),
                offset=self._base + offset,
                stored_size=stored,
                size=size,
                encrypted=encrypted != 0,
            )
        (name_offset,) = struct.unpack_from("<H", raw)
        stored = int.from_bytes(raw[2:5], "little")
        offset = (int.from_bytes(raw[5:8], "little") & 0x7FFFFF) * BLOCK
        sys_flags, gfx_flags = struct.unpack_from("<II", raw, 8)
        name = self._name(name_offset)
        absolute = self._base + offset
        if stored == 0xFFFFFF:  # grande ressource : taille réelle dans l'en-tête RSC7
            head = bytes(self._data[absolute : absolute + 16])
            if len(head) == 16:
                stored = head[7] | (head[14] << 8) | (head[5] << 16) | (head[2] << 24)
        return RpfFile(
            name,
            f"{parent_path}/{name}".strip("/"),
            offset=absolute,
            stored_size=stored,
            size=stored,
            is_resource=True,
            sys_flags=sys_flags,
            gfx_flags=gfx_flags,
        )

    # --- Parcours --------------------------------------------------------------
    def files(self) -> Iterator[RpfFile]:
        stack: list[RpfEntry] = [self.root]
        while stack:
            entry = stack.pop()
            if isinstance(entry, RpfDirectory):
                stack.extend(reversed(entry.entries))
            elif isinstance(entry, RpfFile):
                yield entry

    def find(self, path: str) -> RpfFile | None:
        wanted = path.replace("\\", "/").strip("/").lower()
        return next((f for f in self.files() if f.path.lower() == wanted), None)

    # --- Lecture -----------------------------------------------------------------
    def _slice(self, offset: int, length: int) -> bytes:
        if length < 0 or offset + length > len(self._data):
            raise FormatError("Archive RPF tronquée : données d'un fichier hors limites.")
        return bytes(self._data[offset : offset + length])

    def read(self, entry: RpfFile) -> bytes:
        """Octets du fichier. Binaire : décompressé. Ressource : en-tête RSC7 + données."""
        if entry.encrypted:
            raise EncryptedError(f"« {entry.name} » est chiffré dans l'archive : il n'est pas déchiffré.")
        if entry.is_resource:
            if entry.stored_size > MAX_EXTRACT:
                raise FormatError(f"« {entry.name} » dépasse la taille maximale autorisée.")
            return self._slice(entry.offset, entry.stored_size)
        if entry.size > MAX_EXTRACT:
            raise FormatError(f"« {entry.name} » dépasse la taille maximale autorisée.")
        if entry.stored_size == 0:
            return self._slice(entry.offset, entry.size)
        raw = self._slice(entry.offset, entry.stored_size)
        try:
            inflater = zlib.decompressobj(-15)
            data = inflater.decompress(raw, entry.size)
        except zlib.error as exc:
            raise FormatError(f"« {entry.name} » : décompression impossible ({exc}).") from exc
        if len(data) != entry.size:
            raise FormatError(f"« {entry.name} » : taille décompressée inattendue.")
        return data

    def open_nested(self, entry: RpfFile) -> RpfArchive:
        """Archive RPF imbriquée (stockée sans compression dans l'archive parente)."""
        if entry.is_resource or entry.compressed or entry.encrypted:
            raise FormatError(f"« {entry.name} » n'est pas une archive imbriquée lisible.")
        if entry.offset + entry.size > len(self._data):
            raise FormatError(f"« {entry.name} » : archive imbriquée tronquée.")
        return RpfArchive(self._data, entry.offset, entry.name)

    def walk(self, prefix: str = "") -> Iterator[tuple[RpfArchive, RpfFile, str]]:
        """Tous les fichiers, archives imbriquées comprises : (archive, entrée, chemin affiché).

        Une archive imbriquée illisible (chiffrée, corrompue) est renvoyée comme un fichier
        ordinaire : l'appelant peut ainsi la signaler sans interrompre le parcours.
        """
        for entry in self.files():
            display = f"{prefix}{entry.path}"
            if entry.extension == ".rpf" and not entry.is_resource:
                try:
                    nested = self.open_nested(entry)
                except FormatError:
                    yield self, entry, display
                    continue
                yield from nested.walk(f"{display}/")
            else:
                yield self, entry, display
