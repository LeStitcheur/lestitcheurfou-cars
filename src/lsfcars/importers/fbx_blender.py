"""FBX via Blender en processus auxiliaire : conversion FBX → GLB, puis import glTF.

L'adaptateur est « vérifié » : il n'est proposé que si Blender est trouvé, la conversion est
contrôlée (code de retour, fichier produit) et la provenance mentionne la conversion.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from lsfcars.core.logging_setup import get_logger
from lsfcars.importers.base import ImportResult, ModelLoadError, Progress, no_progress
from lsfcars.importers.trimesh_importer import TrimeshImporter

log = get_logger(__name__)

CONVERT_SCRIPT = """
import sys, bpy
args = sys.argv[sys.argv.index("--") + 1:]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=args[0])
bpy.ops.export_scene.gltf(filepath=args[1], export_format="GLB", export_yup=True)
"""

TIMEOUT_S = 300
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_override: str | None = None


def set_blender_path(path: str | None) -> None:
    """Chemin choisi dans les paramètres (prioritaire sur la détection automatique)."""
    global _override
    _override = path or None
    find_blender.cache_clear()
    blender_version.cache_clear()


@lru_cache(maxsize=1)
def find_blender() -> Path | None:
    candidates: list[Path] = []
    if _override:
        candidates.append(Path(_override))
    if os.environ.get("LSFCARS_BLENDER"):
        candidates.append(Path(os.environ["LSFCARS_BLENDER"]))
    for root in (
        os.environ.get("ProgramFiles", r"C:\Program Files"),  # noqa: SIM112 (casse Windows)
        os.environ.get("ProgramFiles(x86)", ""),  # noqa: SIM112
    ):
        foundation = Path(root) / "Blender Foundation" if root else None
        if foundation and foundation.is_dir():
            candidates.extend(sorted(foundation.glob("Blender*/blender.exe"), reverse=True))
    which = shutil.which("blender")
    if which:
        candidates.append(Path(which))
    return next((c for c in candidates if c.is_file()), None)


@lru_cache(maxsize=1)
def blender_version() -> str | None:
    executable = find_blender()
    if executable is None:
        return None
    try:
        output = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=NO_WINDOW,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("Blender introuvable ou défaillant : %s", exc)
        return None
    match = re.search(r"Blender\s+([\d.]+)", output or "")
    return f"Blender {match.group(1)}" if match else None


class FbxBlenderImporter:
    name = "Blender (FBX → glTF)"
    extensions = {".fbx": "Autodesk FBX (via Blender)"}

    def available(self) -> tuple[bool, str]:
        version = blender_version()
        if version is None:
            return False, (
                "Blender n'est pas installé ou n'a pas été trouvé. Installez Blender "
                "ou indiquez son chemin dans les paramètres."
            )
        return True, f"{version} détecté"

    def load(self, path: Path, progress: Progress = no_progress) -> ImportResult:
        path = Path(path)
        ok, reason = self.available()
        if not ok:
            raise ModelLoadError(f"Import FBX indisponible : {reason}")
        executable = find_blender()
        assert executable is not None
        progress(0.05, f"Conversion FBX via {blender_version()}")
        with tempfile.TemporaryDirectory(prefix="lsfcars-fbx-") as tmp:
            target = Path(tmp) / f"{path.stem}.glb"
            command = [
                str(executable),
                "--background",
                "--factory-startup",
                "--python-expr",
                CONVERT_SCRIPT,
                "--",
                str(path),
                str(target),
            ]
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=TIMEOUT_S,
                    creationflags=NO_WINDOW,
                )
            except subprocess.TimeoutExpired as exc:
                raise ModelLoadError(f"Conversion FBX trop longue (> {TIMEOUT_S} s).") from exc
            except OSError as exc:
                raise ModelLoadError(f"Impossible de lancer Blender : {exc}") from exc
            if completed.returncode != 0 or not target.is_file():
                output = (completed.stderr or completed.stdout or "").strip().splitlines()
                tail = "\n".join(output[-6:])
                raise ModelLoadError(f"Blender n'a pas pu convertir « {path.name} ».\n{tail}")
            progress(0.4, "Lecture du résultat converti")
            result = TrimeshImporter().load(target, lambda v, t: progress(0.4 + v * 0.6, t), fmt="fbx")
        result.source = path
        result.importer = f"{self.name} — {blender_version()}"
        result.notes.append(f"Converti en glTF par {blender_version()} (fichier d'origine intact)")
        return result
