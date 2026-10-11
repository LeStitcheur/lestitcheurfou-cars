"""Adaptateur Blender / Sollumz : détection, sondage des capacités, tâches annulables.

Sollumz (module complémentaire Blender pour les formats GTA V) n'a pas d'API publique stable :
l'adaptateur ne suppose aucun nom d'opérateur. Il interroge Blender au moment de l'exécution
(modules installés, version, opérateurs ``bpy.ops.sollumz.*`` réellement présents) et ne propose
une opération que si l'opérateur correspondant existe. Tout s'exécute dans un processus séparé,
avec journal capturé, délai maximal et annulation.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from lsfcars.core.logging_setup import get_logger
from lsfcars.importers.fbx_blender import NO_WINDOW, blender_version, find_blender

log = get_logger(__name__)

MARKER = "LSFCARS_JSON:"
PROBE_TIMEOUT_S = 90

# Exécuté sans --factory-startup : on lit la configuration réelle de l'utilisateur
# (modules complémentaires installés et activés).
PROBE_SCRIPT = r"""
import json
import addon_utils, bpy
info = {"blender": bpy.app.version_string, "sollumz": None, "operators": []}
for module in addon_utils.modules():
    name = module.__name__
    meta = getattr(module, "bl_info", {}) or {}
    label = str(meta.get("name", name))
    if "sollumz" in name.lower() or "sollumz" in label.lower():
        _loaded, enabled = addon_utils.check(name)
        info["sollumz"] = {
            "module": name,
            "name": label,
            "version": ".".join(str(v) for v in meta.get("version", ())),
            "enabled": bool(enabled),
        }
        if not enabled:
            try:
                addon_utils.enable(name, default_set=False)
            except Exception as exc:
                info["sollumz"]["enable_error"] = str(exc)
        break
if hasattr(bpy.ops, "sollumz"):
    info["operators"] = sorted(op for op in dir(bpy.ops.sollumz) if not op.startswith("_"))
print("LSFCARS_JSON:" + json.dumps(info))
"""

# Opérateurs Sollumz connus selon les versions : seuls ceux réellement présents sont utilisés.
IMPORT_OPERATORS = ("import_assets", "import")
EXPORT_OPERATORS = ("export_assets", "export")


@dataclass
class SollumzStatus:
    blender_path: str | None = None
    blender_version: str | None = None
    sollumz_installed: bool = False
    sollumz_module: str = ""
    sollumz_name: str = ""
    sollumz_version: str = ""
    sollumz_enabled: bool = False
    operators: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def import_operator(self) -> str | None:
        return next((op for op in IMPORT_OPERATORS if op in self.operators), None)

    @property
    def export_operator(self) -> str | None:
        return next((op for op in EXPORT_OPERATORS if op in self.operators), None)

    @property
    def can_import(self) -> bool:
        return self.sollumz_installed and self.import_operator is not None

    @property
    def can_export(self) -> bool:
        return self.sollumz_installed and self.export_operator is not None

    def summary(self) -> str:
        if self.blender_version is None:
            return "Blender introuvable : installez Blender ou indiquez son chemin dans les paramètres."
        if self.error:
            return f"{self.blender_version} détecté, sondage impossible : {self.error}"
        if not self.sollumz_installed:
            return f"{self.blender_version} détecté ; Sollumz n'est pas installé dans ce Blender."
        parts = [self.blender_version, f"{self.sollumz_name} {self.sollumz_version}".strip()]
        parts.append("import disponible" if self.can_import else "import indisponible")
        parts.append("export disponible" if self.can_export else "export indisponible")
        return " · ".join(parts)


class TaskCancelled(Exception):
    pass


class BlenderTask:
    """Processus Blender en arrière-plan : journal ligne par ligne, délai maximal, annulation."""

    def __init__(
        self,
        arguments: list[str],
        timeout_s: float = 600,
        on_line: Callable[[str], None] | None = None,
    ) -> None:
        self.arguments = arguments
        self.timeout_s = timeout_s
        self.on_line = on_line
        self.lines: list[str] = []
        self.returncode: int | None = None
        self._process: subprocess.Popen[str] | None = None
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def run(self) -> int:
        executable = find_blender()
        if executable is None:
            raise FileNotFoundError("Blender introuvable.")
        log.info("Tâche Blender lancée (%s)", executable.name)
        self._process = subprocess.Popen(
            [str(executable), *self.arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=NO_WINDOW,
        )
        reader = threading.Thread(target=self._read, daemon=True)
        reader.start()
        started = time.monotonic()
        while self._process.poll() is None:
            if self._cancelled.is_set():
                self._kill()
                raise TaskCancelled("Tâche Blender annulée.")
            if time.monotonic() - started > self.timeout_s:
                self._kill()
                raise TimeoutError(f"Tâche Blender trop longue (> {self.timeout_s:.0f} s).")
            time.sleep(0.05)
        reader.join(timeout=2)
        self.returncode = self._process.returncode
        return self.returncode

    def _read(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        for raw in self._process.stdout:
            line = raw.rstrip()
            self.lines.append(line)
            if self.on_line is not None:
                self.on_line(line)

    def _kill(self) -> None:
        process = self._process
        if process is None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

    def json_payload(self) -> dict | None:
        for line in reversed(self.lines):
            if line.startswith(MARKER):
                try:
                    return json.loads(line[len(MARKER) :])
                except json.JSONDecodeError:
                    return None
        return None


def probe(on_line: Callable[[str], None] | None = None) -> SollumzStatus:
    """Détecte Blender et Sollumz (version, état, opérateurs réellement disponibles)."""
    status = SollumzStatus()
    executable = find_blender()
    if executable is None:
        return status
    status.blender_path = str(executable)
    status.blender_version = blender_version()
    if status.blender_version is None:
        status.error = "Blender ne répond pas à « --version »."
        return status
    task = BlenderTask(["--background", "--python-expr", PROBE_SCRIPT], PROBE_TIMEOUT_S, on_line)
    try:
        task.run()
    except (OSError, TimeoutError, TaskCancelled) as exc:
        status.error = str(exc)
        return status
    payload = task.json_payload()
    if payload is None:
        status.error = "Réponse de Blender illisible."
        return status
    sollumz = payload.get("sollumz")
    if sollumz:
        status.sollumz_installed = True
        status.sollumz_module = sollumz.get("module", "")
        status.sollumz_name = sollumz.get("name", "Sollumz")
        status.sollumz_version = sollumz.get("version", "")
        status.sollumz_enabled = bool(sollumz.get("enabled"))
        status.operators = list(payload.get("operators", []))
    return status


IMPORT_SCRIPT = r"""
import json, os, sys
import addon_utils, bpy
source, target, module, operator = sys.argv[sys.argv.index("--") + 1:]
bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable(module, default_set=False)
op = getattr(bpy.ops.sollumz, operator)
result = op(directory=os.path.dirname(source), files=[{"name": os.path.basename(source)}])
bpy.ops.export_scene.gltf(filepath=target, export_format="GLB", export_yup=True)
print("LSFCARS_JSON:" + json.dumps({"import": list(result), "exported": os.path.isfile(target)}))
"""


def import_with_sollumz(
    status: SollumzStatus,
    source: Path,
    target: Path,
    task_ready: Callable[[BlenderTask], None] | None = None,
) -> list[str]:
    """Import expérimental via Sollumz puis export glTF. Retourne le journal.

    Les paramètres de l'opérateur varient selon les versions de Sollumz : en cas d'échec,
    le journal est renvoyé dans l'erreur et l'opération est signalée comme manuelle.
    """
    if not status.can_import:
        raise RuntimeError("Sollumz n'est pas disponible : import automatique impossible.")
    task = BlenderTask(
        [
            "--background",
            "--python-expr",
            IMPORT_SCRIPT,
            "--",
            str(source),
            str(target),
            status.sollumz_module,
            str(status.import_operator),
        ],
        600,
    )
    if task_ready is not None:
        task_ready(task)
    code = task.run()
    payload = task.json_payload() or {}
    if code != 0 or not payload.get("exported") or not target.is_file():
        tail = "\n".join(task.lines[-12:])
        raise RuntimeError(
            f"L'import via Sollumz a échoué : opération à réaliser manuellement dans Blender.\n{tail}"
        )
    return task.lines
