"""Inventaire des archives RPF d'une installation GTA V appartenant à l'utilisateur.

Seul l'en-tête de chaque archive est lu : on indique si elle est lisible (non chiffrée) ou
chiffrée. Les archives officielles sont chiffrées et ne sont jamais déchiffrées ici.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lsfcars.fivem.errors import FormatError
from lsfcars.fivem.rpf import ENC_NONE, ENC_OPEN, encryption_label, probe

MAX_ARCHIVES = 2000
MAX_DEPTH = 6


@dataclass
class RpfInfo:
    path: Path
    size: int
    entries: int
    encryption: int
    error: str = ""

    @property
    def readable(self) -> bool:
        return not self.error and self.encryption in (ENC_NONE, ENC_OPEN)

    @property
    def status(self) -> str:
        if self.error:
            return f"Illisible : {self.error}"
        if self.readable:
            return "Lisible (non chiffrée)"
        return f"Chiffrée — {encryption_label(self.encryption)} : non lue"


def is_gta_install(folder: Path) -> bool:
    return (folder / "GTA5.exe").is_file() or (folder / "GTA5_Enhanced.exe").is_file()


def scan(folder: str | Path, cancel: Callable[[], bool] | None = None) -> list[RpfInfo]:
    """Archives .rpf du dossier (profondeur limitée), triées : lisibles d'abord."""
    root = Path(folder)
    found: list[RpfInfo] = []
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack and len(found) < MAX_ARCHIVES:
        if cancel is not None and cancel():
            break
        current, depth = stack.pop()
        try:
            children = sorted(current.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir() and depth < MAX_DEPTH and not child.name.startswith("."):
                stack.append((child, depth + 1))
            elif child.is_file() and child.suffix.lower() == ".rpf":
                try:
                    entries, encryption = probe(child)
                    found.append(RpfInfo(child, child.stat().st_size, entries, encryption))
                except (FormatError, OSError) as exc:
                    found.append(RpfInfo(child, 0, 0, -1, str(exc)))
    return sorted(found, key=lambda info: (not info.readable, str(info.path).lower()))
