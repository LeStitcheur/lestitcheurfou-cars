"""Détection des capacités matérielles : GPU, VRAM, CUDA, RAM, CPU, disque, dépendances.

Les valeurs proviennent du système (``nvidia-smi``, WMI, registre, ``GlobalMemoryStatusEx``) ;
une valeur introuvable reste ``None`` et est affichée comme « inconnue », jamais inventée.
"""

from __future__ import annotations

import ctypes
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from importlib import metadata
from pathlib import Path

from lsfcars.core.logging_setup import get_logger

log = get_logger(__name__)

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class GPUInfo:
    name: str
    vendor: str = ""
    vram_mb: int | None = None  # mémoire dédiée (None : inconnue)
    free_mb: int | None = None
    driver: str = ""
    source: str = ""  # « nvidia-smi » ou « WMI » (VRAM WMI plafonnée à 4 Go : indicative)

    @property
    def cuda_capable(self) -> bool:
        return self.vendor == "NVIDIA"


@dataclass
class HardwareInfo:
    os: str = ""
    cpu: str = ""
    cores: int | None = None
    ram_mb: int | None = None
    ram_free_mb: int | None = None
    gpus: list[GPUInfo] = field(default_factory=list)
    cuda: str | None = None  # version CUDA maximale prise en charge par le pilote
    disk_free_mb: int | None = None
    dependencies: dict[str, str] = field(default_factory=dict)

    @property
    def best_gpu(self) -> GPUInfo | None:
        cuda = [g for g in self.gpus if g.cuda_capable]
        pool = cuda or [g for g in self.gpus if g.vram_mb]
        return max(pool, key=lambda g: g.vram_mb or 0, default=None)

    @property
    def vram_mb(self) -> int | None:
        gpu = self.best_gpu
        return gpu.vram_mb if gpu else None

    @property
    def has_cuda(self) -> bool:
        return self.cuda is not None and any(g.cuda_capable for g in self.gpus)

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> dict[str, str]:
        """Résumé lisible (panneau Matériel, diagnostics)."""

        def mb(value: int | None) -> str:
            return "inconnue" if value is None else f"{value / 1024:.1f} Go"

        gpu = self.best_gpu
        return {
            "Système": self.os or "inconnu",
            "Processeur": f"{self.cpu or 'inconnu'} ({self.cores or '?'} threads)",
            "Mémoire vive": f"{mb(self.ram_mb)} (libre : {mb(self.ram_free_mb)})",
            "GPU": gpu.name if gpu else "aucun GPU détecté",
            "VRAM": mb(gpu.vram_mb) if gpu else "—",
            "Accélération": f"CUDA {self.cuda}" if self.has_cuda else "aucune (CPU seulement)",
            "Disque libre (moteurs)": mb(self.disk_free_mb),
        }


def _run(command: list[str], timeout: float = 8.0) -> str | None:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def _nvidia() -> tuple[list[GPUInfo], str | None]:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return [], None
    query = _run(
        [
            executable,
            "--query-gpu=name,memory.total,memory.free,driver_version",
            "--format=csv,noheader,nounits",
        ]
    )
    gpus = []
    for line in (query or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        gpus.append(GPUInfo(parts[0], "NVIDIA", _int(parts[1]), _int(parts[2]), parts[3], "nvidia-smi"))
    header = _run([executable]) or ""
    match = re.search(r"CUDA (?:UMD )?Version:\s*([\d.]+)", header)
    return gpus, (match.group(1) if match and gpus else None)


def _wmi_gpus() -> list[GPUInfo]:
    if sys.platform != "win32":
        return []
    output = _run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_VideoController | ForEach-Object "
            '{ "$($_.Name)|$($_.AdapterRAM)|$($_.DriverVersion)" }',
        ],
        timeout=15,
    )
    gpus = []
    for line in (output or "").splitlines():
        parts = line.strip().split("|")
        if len(parts) != 3 or not parts[0] or "Remote Display" in parts[0] or "Basic" in parts[0]:
            continue
        name = parts[0]
        vendor = next((v for v in ("NVIDIA", "AMD", "Intel") if v.lower() in name.lower()), "")
        ram = _int(parts[1])
        gpus.append(GPUInfo(name, vendor, ram // (1024 * 1024) if ram else None, None, parts[2], "WMI"))
    return gpus


def _int(text: str) -> int | None:
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _memory() -> tuple[int | None, int | None]:
    if sys.platform != "win32":
        try:
            pages, size = os.sysconf("SC_PHYS_PAGES"), os.sysconf("SC_PAGE_SIZE")
            free = os.sysconf("SC_AVPHYS_PAGES")
            return pages * size // 2**20, free * size // 2**20
        except (ValueError, OSError, AttributeError):
            return None, None

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None, None
    return status.ullTotalPhys // 2**20, status.ullAvailPhys // 2**20


def _cpu_name() -> str:
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            ) as key:
                return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    return platform.processor() or ""


def dependency_versions() -> dict[str, str]:
    versions = {"Python": sys.version.split()[0]}
    for name in ("numpy", "trimesh", "Pillow", "PySide6-Essentials"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = "absent"
    from lsfcars.importers.fbx_blender import blender_version

    versions["Blender"] = blender_version() or "non détecté"
    return versions


def detect(engines_dir: Path | None = None, include_dependencies: bool = True) -> HardwareInfo:
    """Interroge le système (quelques secondes au plus : à lancer hors du fil de l'interface)."""
    gpus, cuda = _nvidia()
    if not gpus:
        gpus = _wmi_gpus()
    ram, ram_free = _memory()
    disk = None
    if engines_dir is not None:
        try:
            probe = engines_dir if engines_dir.exists() else Path(engines_dir.anchor or Path.home())
            disk = shutil.disk_usage(probe).free // 2**20
        except OSError:
            disk = None
    info = HardwareInfo(
        os=f"{platform.system()} {platform.release()}",
        cpu=_cpu_name(),
        cores=os.cpu_count(),
        ram_mb=ram,
        ram_free_mb=ram_free,
        gpus=gpus,
        cuda=cuda,
        disk_free_mb=disk,
        dependencies=dependency_versions() if include_dependencies else {},
    )
    log.info("Matériel : %s", info.summary())
    return info


def from_dict(data: dict) -> HardwareInfo:
    gpus = [GPUInfo(**g) for g in data.get("gpus", [])]
    fields = {k: v for k, v in data.items() if k in HardwareInfo.__dataclass_fields__ and k != "gpus"}
    return HardwareInfo(gpus=gpus, **fields)
