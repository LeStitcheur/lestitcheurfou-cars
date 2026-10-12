"""Adaptateur local TripoSR (Stability AI & Tripo AI, licence MIT) : une image → maillage 3D.

TripoSR est un réseau de neurones de reconstruction 3D **à partir d'une seule image**. Il
n'est pas livré avec l'application : il s'installe séparément (environnement Python dédié,
PyTorch, code et poids) dans ``<moteurs>/triposr`` — voir ``scripts/install_triposr.ps1``.
L'inférence s'exécute dans un processus séparé (``workers/triposr_worker.py``) : annulation
immédiate (arrêt du processus), délai maximal, aucun blocage de l'interface.

Disposition attendue :
    <moteurs>/triposr/env/Scripts/python.exe   environnement Python 3.12 (PyTorch, PyMCubes…)
    <moteurs>/triposr/src/tsr/                 code TripoSR (github.com/VAST-AI-Research/TripoSR)
    <moteurs>/triposr/weights/config.yaml      poids (huggingface.co/stabilityai/TripoSR)
    <moteurs>/triposr/weights/model.ckpt
    <moteurs>/triposr/hf/                      cache Hugging Face (configuration DINO)
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
from PIL import Image

from lsfcars.ai import references as refs_mod
from lsfcars.ai.engines.base import (
    PROFILE_LABELS,
    Availability,
    Capability,
    EngineAdapter,
    EngineInfo,
    EngineOutput,
    GenerationRequest,
    JobContext,
    ProfileOption,
    Status,
)
from lsfcars.ai.errors import EngineUnavailable, InvalidOutput, JobCancelled, JobTimeout, ProviderError
from lsfcars.ai.hardware import HardwareInfo
from lsfcars.core.logging_setup import get_logger

log = get_logger(__name__)

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
VIEW_PRIORITY = ("three_quarter", "left", "right", "front", "back", "top")
MIN_VRAM_MB = 6000  # indication des auteurs : environ 6 Go pour une image (réglages par défaut)


def default_engines_dir() -> Path:
    override = os.environ.get("LSFCARS_ENGINES")
    return Path(override) if override else Path.home() / ".lestitcheurfoucars" / "engines"


def worker_script() -> Path:
    if getattr(sys, "frozen", False):
        bundle = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return bundle / "lsfcars" / "ai" / "workers" / "triposr_worker.py"
    return Path(__file__).resolve().parents[1] / "workers" / "triposr_worker.py"


class TripoSREngine(EngineAdapter):
    info = EngineInfo(
        id="triposr",
        name="TripoSR (local)",
        version="TripoSR (Stability AI / Tripo AI)",
        kind="local",
        method="neural",
        capabilities=frozenset({Capability.IMAGE_TO_3D, Capability.TEXTURE}),
        input_formats=("PNG", "JPG", "WEBP"),
        output_formats=("GLB",),
        resources="GPU NVIDIA CUDA ≥ 6 Go recommandé (processeur possible, très lent), ~6 Go de disque",
        auth="aucune",
        limits={"max_images": 1, "note": "une seule image : les autres vues ne sont pas exploitées"},
        cost="gratuit (calcul local)",
        license="MIT (code et poids) — données d'entraînement Objaverse (CC-BY)",
        docs_url="https://github.com/VAST-AI-Research/TripoSR",
        verification="Génération réelle exécutée sur RTX 3060 Ti (voir docs/AI_VEHICLE_CREATOR.md).",
        min_vram_mb=MIN_VRAM_MB,
    )

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self._probe: dict | None = None
        self._probe_error = ""

    # --- Emplacements -------------------------------------------------------------------------
    @property
    def root(self) -> Path:
        return Path(self.config.get("root") or default_engines_dir() / "triposr")

    @property
    def python(self) -> Path:
        return self.root / "env" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

    @property
    def src(self) -> Path:
        return self.root / "src"

    @property
    def weights(self) -> Path:
        return self.root / "weights"

    def missing(self) -> list[str]:
        problems = []
        if not self.python.is_file():
            problems.append(f"environnement Python absent ({self.python})")
        if not (self.src / "tsr" / "system.py").is_file():
            problems.append(f"code TripoSR absent ({self.src})")
        for name in ("config.yaml", "model.ckpt"):
            if not (self.weights / name).is_file():
                problems.append(f"poids absents ({self.weights / name})")
        if not worker_script().is_file():
            problems.append("script auxiliaire introuvable")
        return problems

    def _env(self) -> dict:
        env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
        env.update(
            {
                "HF_HOME": str(self.root / "hf"),
                "HF_HUB_OFFLINE": "1",  # aucun téléchargement implicite pendant une génération
                "PYTHONIOENCODING": "utf-8",
                "PYTHONNOUSERSITE": "1",
            }
        )
        return env

    def probe(self, timeout: float = 120.0) -> dict | None:
        """Lance le Python du moteur : versions de PyTorch / CUDA (quelques secondes)."""
        code = (
            "import json,torch,mcubes,omegaconf,einops,transformers;"
            "print(json.dumps({'torch':torch.__version__,'cuda':torch.cuda.is_available(),"
            "'cuda_version':torch.version.cuda,"
            "'gpu':torch.cuda.get_device_name(0) if torch.cuda.is_available() else '',"
            "'transformers':transformers.__version__}))"
        )
        try:
            result = subprocess.run(
                [str(self.python), "-c", code],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=self._env(),
                creationflags=NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self._probe, self._probe_error = None, str(exc)
            return None
        if result.returncode != 0:
            self._probe, self._probe_error = None, (result.stderr.strip().splitlines() or ["erreur"])[-1]
            return None
        try:
            self._probe = json.loads(result.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            self._probe, self._probe_error = None, "réponse illisible"
        return self._probe

    def detect(self) -> Availability:
        problems = self.missing()
        if problems:
            return Availability(Status.MISSING, "Non installé : " + " ; ".join(problems) + ".")
        probe = self._probe or self.probe()
        if probe is None:
            return Availability(Status.ERROR, f"Environnement du moteur inutilisable : {self._probe_error}")
        if probe.get("cuda"):
            device = f"CUDA {probe.get('cuda_version')} — {probe.get('gpu')}"
        else:
            device = "processeur seulement"
        return Availability(
            Status.AVAILABLE, f"PyTorch {probe.get('torch')}, {device}.", str(probe.get("torch"))
        )

    def profiles(self, hardware: HardwareInfo | None) -> list[ProfileOption]:
        cuda = bool(self._probe.get("cuda")) if self._probe else bool(hardware and hardware.has_cuda)
        vram = hardware.vram_mb if hardware else None
        base = {"device": "cuda" if cuda else "cpu"}
        if not cuda:
            reason = "aucun GPU CUDA : seul le profil économique est proposé (calcul sur le processeur)"
            return [
                ProfileOption(
                    "eco", PROFILE_LABELS["eco"], {**base, "mc_resolution": 128, "chunk_size": 4096}
                ),
                ProfileOption("balanced", PROFILE_LABELS["balanced"], {}, False, reason),
                ProfileOption("high", PROFILE_LABELS["high"], {}, False, reason),
            ]
        enough = vram is None or vram >= MIN_VRAM_MB
        chunk = 8192 if enough else 2048
        high_reason = "" if enough else f"VRAM insuffisante ({vram} Mo < {MIN_VRAM_MB} Mo)"
        return [
            ProfileOption(
                "eco",
                f"{PROFILE_LABELS['eco']} — maillage 128³",
                {**base, "mc_resolution": 128, "chunk_size": chunk},
            ),
            ProfileOption(
                "balanced",
                f"{PROFILE_LABELS['balanced']} — maillage 256³",
                {**base, "mc_resolution": 256, "chunk_size": chunk},
            ),
            ProfileOption(
                "high",
                f"{PROFILE_LABELS['high']} — maillage 384³ (plus dense, détail limité par le modèle)",
                {**base, "mc_resolution": 384, "chunk_size": chunk},
                enough,
                high_reason,
            ),
        ]

    # --- Génération ---------------------------------------------------------------------------
    def choose_reference(self, request: GenerationRequest):  # type: ignore[no-untyped-def]
        pool = [r for r in request.references if r.view in VIEW_PRIORITY]
        if not pool:
            return None
        return min(pool, key=lambda r: VIEW_PRIORITY.index(r.view))

    def run(self, request: GenerationRequest, ctx: JobContext) -> EngineOutput:
        problems = self.missing()
        if problems:
            raise EngineUnavailable("TripoSR non installé : " + " ; ".join(problems) + ".")
        params = self.profile_params(request, request.vehicle.get("_hardware"))
        ref = self.choose_reference(request)
        if ref is None:
            raise EngineUnavailable("Aucune image exploitable (vues extérieures uniquement).")
        out_dir = Path(request.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        ctx.progress(0.01, "Préparation de l'image (détourage)")
        image = Image.open(ref.path).convert("RGBA")
        if ref.mask_path and Path(ref.mask_path).is_file():
            mask = Image.open(ref.mask_path).convert("L").resize(image.size)
        else:
            seg = refs_mod.segment(image)
            if not seg.ok:
                raise InvalidOutput("Détourage impossible : " + " ".join(seg.warnings))
            mask = Image.fromarray(seg.mask.astype(np.uint8) * 255)
        image.putalpha(mask)
        source = out_dir / "triposr_input.png"
        image.save(source)
        target = out_dir / "triposr.glb"
        command = [
            str(self.python),
            "-I",
            str(worker_script()),
            "--src", str(self.src),
            "--weights", str(self.weights),
            "--input", str(source),
            "--output", str(target),
            "--mc-resolution", str(int(params.get("mc_resolution", 256))),
            "--chunk-size", str(int(params.get("chunk_size", 8192))),
            "--device", str(params.get("device", "cuda")),
        ]  # fmt: skip
        log.info("TripoSR : lancement (%s, résolution %s)", params.get("device"), params.get("mc_resolution"))
        stderr_path = out_dir / "triposr_stderr.log"
        started = time.monotonic()
        done: dict | None = None
        error = ""
        with stderr_path.open("w", encoding="utf-8", errors="replace") as stderr:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=stderr,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=self._env(),
                cwd=str(out_dir),
                creationflags=NO_WINDOW,
            )
            lines: queue.Queue[str | None] = queue.Queue()

            def reader() -> None:
                assert process.stdout is not None
                for line in process.stdout:
                    lines.put(line)
                lines.put(None)

            threading.Thread(target=reader, daemon=True).start()
            try:
                while True:
                    try:
                        ctx.check()
                    except (JobCancelled, JobTimeout):
                        process.kill()
                        raise
                    try:
                        line = lines.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if line is None:
                        break
                    try:
                        message = json.loads(line)
                    except ValueError:
                        continue
                    if "progress" in message:
                        ctx.progress(0.02 + 0.96 * float(message["progress"]), str(message.get("text", "")))
                    elif "done" in message:
                        done = message
                    elif "error" in message:
                        error = str(message["error"])
                        log.warning("TripoSR : %s\n%s", error, message.get("trace", ""))
            finally:
                if process.poll() is None:
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        process.kill()
        if done is None or not target.is_file():
            tail = stderr_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-3:]
            raise ProviderError(f"TripoSR a échoué : {error or ' '.join(tail) or 'aucune sortie'}")
        stats = dict(done.get("stats") or {})
        stats["wall_seconds"] = round(time.monotonic() - started, 2)
        return EngineOutput(
            {"model": target, "input": source},
            "glb",
            data={"stats": stats, "reference": ref.view, "params": params},
            used_views=[ref.view],
            warnings=[
                f"TripoSR n'exploite qu'une image ({refs_mod.VIEWS.get(ref.view, ref.view)}) : "
                "les faces cachées sont estimées par le modèle."
            ],
        )
