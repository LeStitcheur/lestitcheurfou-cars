"""AI Engine Manager : moteurs, détection, configuration, routage, file de tâches, cache.

- **Registre** des adaptateurs (``ENGINE_CLASSES``) et des fournisseurs étudiés mais non
  intégrés (``NOT_INTEGRATED``, avec la raison).
- **Configuration** (``ai_engines.json`` dans les données de l'application) : mode (local /
  cloud / automatique), confirmation du transfert cloud, délai maximal, réglages par moteur.
  Les clés API vont dans le coffre (``secrets.SecretStore``), jamais ici.
- **Routage automatique** : chaque moteur est retenu ou écarté avec une raison explicite
  (indisponible, capacité absente, vue requise manquante, profil impossible sur ce matériel,
  mode, coût) puis classé ; l'utilisateur garde toujours le choix manuel.
- **File de tâches** : un thread par ressource (GPU local, processeur, réseau), progression,
  annulation, délai maximal, journal ; aucune dépendance à Qt.
- **Cache** des résultats (même moteur, mêmes paramètres, mêmes images) et nettoyage des
  fichiers temporaires.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from lsfcars.ai import hardware as hw
from lsfcars.ai.engines.anthropic import AnthropicEngine
from lsfcars.ai.engines.base import (
    Availability,
    Capability,
    CostEstimate,
    EngineAdapter,
    GenerationRequest,
    JobContext,
    Status,
)
from lsfcars.ai.engines.comfyui import ComfyUIEngine
from lsfcars.ai.engines.meshy import MeshyEngine
from lsfcars.ai.engines.silhouette import SilhouetteEngine
from lsfcars.ai.engines.triposr import TripoSREngine, default_engines_dir
from lsfcars.ai.errors import AIError, JobCancelled, JobTimeout
from lsfcars.ai.secrets import SecretStore
from lsfcars.core.logging_setup import get_logger

log = get_logger(__name__)

ENGINE_CLASSES: tuple[type[EngineAdapter], ...] = (
    SilhouetteEngine,
    TripoSREngine,
    ComfyUIEngine,
    MeshyEngine,
    AnthropicEngine,
)
NOT_INTEGRATED: tuple[dict, ...] = (
    {
        "name": "Stability AI — Stable Fast 3D / SPAR3D (cloud)",
        "reason": "Contrat d'API non vérifié : la documentation officielle n'a pas pu être consultée "
        "pendant le développement. Non intégré plutôt que supposé compatible.",
    },
    {
        "name": "Tripo (cloud)",
        "reason": "Contrat d'API non vérifié (documentation inaccessible pendant le développement).",
    },
    {
        "name": "Hunyuan3D-2 (local)",
        "reason": "Licence Tencent Hunyuan 3D Community : ne s'applique pas dans l'Union européenne, "
        "au Royaume-Uni ni en Corée du Sud. Non intégré.",
    },
    {
        "name": "TRELLIS (local)",
        "reason": "Dépendances compilées (CUDA) non validées sous Windows pendant le développement.",
    },
)
DEFAULT_CONFIG: dict = {
    "mode": "auto",  # « local », « cloud » ou « auto »
    "confirm_cloud": True,
    "default_profile": "balanced",
    "timeout_s": 1800,
    "max_credits": None,  # plafond de coût au-delà duquel un moteur est écarté
    "engines": {},
}
ORTHO_VIEWS = {"left", "right", "front", "back", "top"}
GENERATION_CAPABILITIES = (Capability.IMAGE_TO_3D, Capability.MULTIVIEW_3D)


# --- Routage ------------------------------------------------------------------------------------


@dataclass
class RoutingRequest:
    capability: Capability
    views: list[str] = field(default_factory=list)
    vehicle_type: str = ""
    quality: str = "balanced"
    output_format: str = "glb"
    mode: str = ""  # local, cloud, auto (vide : configuration)
    max_credits: float | None = None


@dataclass
class Candidate:
    engine_id: str
    name: str
    kind: str
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    excluded: str | None = None
    estimate: CostEstimate | None = None


@dataclass
class RoutingDecision:
    chosen: str | None
    candidates: list[Candidate]
    explanation: list[str]

    def candidate(self, engine_id: str | None) -> Candidate | None:
        return next((c for c in self.candidates if c.engine_id == engine_id), None)

    @property
    def needs_cloud_consent(self) -> bool:
        chosen = self.candidate(self.chosen)
        return bool(chosen and chosen.kind == "cloud")

    @property
    def needs_payment_consent(self) -> bool:
        chosen = self.candidate(self.chosen)
        return bool(chosen and chosen.estimate and chosen.estimate.paid)


# --- File de tâches -----------------------------------------------------------------------------

QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELLED, TIMEOUT = (
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "timeout",
)
STATUS_LABELS = {
    QUEUED: "En attente",
    RUNNING: "En cours",
    SUCCEEDED: "Terminée",
    FAILED: "Échec",
    CANCELLED: "Annulée",
    TIMEOUT: "Délai dépassé",
}


@dataclass
class Job:
    label: str
    function: Callable[[JobContext], object]
    resource: str = "local-cpu"
    timeout: float | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = QUEUED
    progress: float = 0.0
    message: str = ""
    result: object = None
    error: str = ""
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    logs: list[str] = field(default_factory=list)
    on_done: Callable[[Job], None] | None = None
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    _done: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def duration(self) -> float | None:
        if self.started is None:
            return None
        return (self.finished or time.time()) - self.started

    @property
    def active(self) -> bool:
        return self.status in (QUEUED, RUNNING)

    def cancel(self) -> None:
        self._cancel.set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._done.wait(timeout)


class JobQueue:
    """Une file et un thread par ressource : les tâches GPU passent une par une."""

    def __init__(self, on_update: Callable[[Job], None] | None = None) -> None:
        self.listeners: list[Callable[[Job], None]] = [on_update] if on_update else []
        self.jobs: list[Job] = []
        self._pending: dict[str, list[Job]] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        self._wake: dict[str, threading.Condition] = {}
        self._stopping = False

    def submit(
        self,
        label: str,
        function: Callable[[JobContext], object],
        resource: str = "local-cpu",
        timeout: float | None = None,
        on_done: Callable[[Job], None] | None = None,
    ) -> Job:
        job = Job(label, function, resource, timeout, on_done=on_done)
        with self._lock:
            self.jobs.append(job)
            self._pending.setdefault(resource, []).append(job)
            condition = self._wake.setdefault(resource, threading.Condition(self._lock))
            if resource not in self._threads:
                thread = threading.Thread(
                    target=self._loop, args=(resource,), name=f"lsf-ai-{resource}", daemon=True
                )
                self._threads[resource] = thread
                thread.start()
            condition.notify()
        self._notify(job)
        return job

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job is None or not job.active:
            return False
        job.cancel()
        removed = False
        with self._lock:
            pending = self._pending.get(job.resource, [])
            if job in pending:  # encore en attente : retirée immédiatement
                pending.remove(job)
                removed = True
        if removed:
            self._finish(job, CANCELLED, "Annulée avant le démarrage.")
        return True

    def get(self, job_id: str) -> Job | None:
        return next((j for j in self.jobs if j.id == job_id), None)

    def active(self) -> list[Job]:
        return [j for j in self.jobs if j.active]

    def clear_finished(self) -> None:
        with self._lock:
            self.jobs = [j for j in self.jobs if j.active]

    def shutdown(self) -> None:
        with self._lock:
            self._stopping = True
            for job in self.jobs:
                job.cancel()
            for condition in self._wake.values():
                condition.notify_all()

    def _notify(self, job: Job) -> None:
        for listener in list(self.listeners):
            try:
                listener(job)
            except Exception:  # noqa: BLE001 (un écouteur ne doit jamais tuer la file)
                log.exception("Écouteur de tâche en erreur")

    def _finish(self, job: Job, status: str, message: str) -> None:
        job.status = status
        job.message = message
        job.finished = time.time()
        if job.on_done is not None:
            try:
                job.on_done(job)
            except Exception:  # noqa: BLE001
                log.exception("Fin de tâche en erreur")
        job._done.set()
        self._notify(job)

    def _loop(self, resource: str) -> None:
        condition = self._wake[resource]
        while True:
            with self._lock:
                while not self._pending.get(resource) and not self._stopping:
                    condition.wait(timeout=1.0)
                if self._stopping:
                    return
                job = self._pending[resource].pop(0)
            if job._cancel.is_set():
                self._finish(job, CANCELLED, "Annulée avant le démarrage.")
                continue
            job.status = RUNNING
            job.started = time.time()
            self._notify(job)

            def progress(value: float, text: str, job: Job = job) -> None:
                job.progress = value
                if text:
                    job.message = text
                self._notify(job)

            def log_line(text: str, job: Job = job) -> None:
                job.logs.append(text)
                log.info("[%s] %s", job.label, text)

            ctx = JobContext(progress, job._cancel.is_set, job.timeout, log_line)
            try:
                job.result = job.function(ctx)
            except JobCancelled as exc:
                self._finish(job, CANCELLED, str(exc))
                continue
            except JobTimeout as exc:
                job.error = str(exc)
                self._finish(job, TIMEOUT, str(exc))
                continue
            except AIError as exc:
                job.error = str(exc)
                self._finish(job, CANCELLED if job._cancel.is_set() else FAILED, str(exc))
                continue
            except Exception as exc:  # noqa: BLE001 (jamais de plantage : erreur affichée)
                log.exception("Tâche « %s » en erreur", job.label)
                job.error = f"Erreur inattendue : {exc}"
                self._finish(job, FAILED, job.error)
                continue
            job.progress = 1.0
            self._finish(job, SUCCEEDED, job.message or "Terminée.")


# --- Gestionnaire -------------------------------------------------------------------------------


class AIEngineManager:
    def __init__(
        self,
        data_dir: Path,
        engines_dir: Path | None = None,
        secrets: SecretStore | None = None,
        engine_classes: tuple[type[EngineAdapter], ...] = ENGINE_CLASSES,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.engines_dir = Path(engines_dir) if engines_dir else default_engines_dir()
        self.secrets = secrets or SecretStore(self.data_dir / "ai_secrets.json")
        self.config_path = self.data_dir / "ai_engines.json"
        self.cache_dir = self.data_dir / "ai_cache"
        self.config = self._load_config()
        self.adapters: dict[str, EngineAdapter] = {}
        for cls in engine_classes:
            settings = dict(self.config["engines"].get(cls.info.id, {}))
            if cls is TripoSREngine:
                settings.setdefault("root", str(self.engines_dir / "triposr"))
            try:
                adapter = cls(settings, secrets=self.secrets)  # type: ignore[call-arg]
            except TypeError:
                adapter = cls(settings)
            self.adapters[cls.info.id] = adapter
        self.availability: dict[str, Availability] = {}
        self.hardware: hw.HardwareInfo | None = None
        self.queue = JobQueue()
        self._lock = threading.Lock()

    # --- Configuration ----------------------------------------------------------------------
    def _load_config(self) -> dict:
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        try:
            stored = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = {}
        if isinstance(stored, dict):
            config.update({k: v for k, v in stored.items() if k in DEFAULT_CONFIG})
        config["engines"] = dict(config.get("engines") or {})
        return config

    def save_config(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        temp = self.config_path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.config, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.config_path)

    def set_option(self, key: str, value) -> None:  # type: ignore[no-untyped-def]
        if key not in DEFAULT_CONFIG:
            raise KeyError(key)
        self.config[key] = value
        self.save_config()

    def configure_engine(self, engine_id: str, settings: dict) -> None:
        if any("key" in k.lower() or "secret" in k.lower() or "token" in k.lower() for k in settings):
            raise AIError("Les clés API vont dans le coffre sécurisé, pas dans la configuration.")
        stored = self.config["engines"].setdefault(engine_id, {})
        stored.update(settings)
        self.adapters[engine_id].configure(settings)
        self.availability.pop(engine_id, None)
        self.save_config()

    # --- Détection ----------------------------------------------------------------------------
    def detect_hardware(self) -> hw.HardwareInfo:
        self.hardware = hw.detect(self.engines_dir)
        return self.hardware

    def detect(self, engine_id: str) -> Availability:
        adapter = self.adapters[engine_id]
        try:
            availability = adapter.detect()
        except Exception as exc:  # noqa: BLE001 (un moteur défaillant ne bloque pas les autres)
            log.exception("Détection de %s", engine_id)
            availability = Availability(Status.ERROR, f"Détection impossible : {exc}")
        with self._lock:
            self.availability[engine_id] = availability
        return availability

    def detect_all(self, include_hardware: bool = True) -> dict[str, Availability]:
        if include_hardware:
            self.detect_hardware()
        for engine_id in self.adapters:
            self.detect(engine_id)
        return dict(self.availability)

    def test_connection(self, engine_id: str, ctx: JobContext | None = None) -> Availability:
        try:
            availability = self.adapters[engine_id].test_connection(ctx)
        except AIError as exc:
            availability = Availability(Status.ERROR, str(exc))
        with self._lock:
            self.availability[engine_id] = availability
        return availability

    def availability_of(self, engine_id: str) -> Availability:
        return self.availability.get(engine_id) or self.detect(engine_id)

    def engines_for(self, capability: Capability) -> list[EngineAdapter]:
        return [a for a in self.adapters.values() if a.info.supports(capability)]

    # --- Routage ----------------------------------------------------------------------------
    def route(self, request: RoutingRequest) -> RoutingDecision:
        candidates = []
        views = set(request.views)
        ortho = views & ORTHO_VIEWS
        mode = request.mode or self.config.get("mode", "auto")
        limit = request.max_credits if request.max_credits is not None else self.config.get("max_credits")
        for engine_id, adapter in self.adapters.items():
            info = adapter.info
            candidate = Candidate(engine_id, info.name, info.kind)
            candidates.append(candidate)
            single_image = (
                request.capability is Capability.MULTIVIEW_3D
                and not info.supports(Capability.MULTIVIEW_3D)
                and info.supports(Capability.IMAGE_TO_3D)
            )  # moteur image → 3D : reste candidat, une seule vue sera exploitée
            if not info.supports(request.capability) and not single_image:
                candidate.excluded = f"ne prend pas en charge : {request.capability.label}"
                continue
            availability = self.availability_of(engine_id)
            if not availability.ok:
                candidate.excluded = f"{availability.status.label} — {availability.message}"
                continue
            if mode == "local" and info.kind != "local":
                candidate.excluded = "mode « local uniquement »"
                continue
            if mode == "cloud" and info.kind != "cloud":
                candidate.excluded = "mode « cloud uniquement »"
                continue
            generating = request.capability in GENERATION_CAPABILITIES
            if generating and request.output_format.upper() not in (f.upper() for f in info.output_formats):
                candidate.excluded = f"format {request.output_format.upper()} non produit"
                continue
            if engine_id == "lsf-silhouette" and not views & {"left", "right"}:
                candidate.excluded = "exige un profil (gauche ou droit)"
                continue
            if not views and (generating or request.capability is Capability.VISION):
                candidate.excluded = "aucune image de référence"
                continue
            profiles = {p.key: p for p in adapter.profiles(self.hardware)}
            profile = profiles.get(request.quality)
            if profile is not None and not profile.available:
                candidate.excluded = f"profil « {profile.label} » impossible : {profile.reason}"
                continue
            candidate.estimate = adapter.estimate(
                GenerationRequest(request.capability, [], Path("."), request.quality)
            )
            estimate = candidate.estimate
            if (
                estimate.paid
                and estimate.amount is not None
                and limit is not None
                and estimate.amount > float(limit)
            ):
                candidate.excluded = f"coût estimé {estimate.describe()} supérieur au plafond ({limit})"
                continue
            score = 1.0
            reasons = []
            if info.kind == "local":
                score += 1.0
                reasons.append("local : gratuit, aucune image ne quitte le PC")
            else:
                reasons.append("cloud : transfert d'images et coût à confirmer")
            if generating:
                if len(ortho) >= 2 and info.supports(Capability.MULTIVIEW_3D):
                    score += (
                        2.5 if engine_id == "lsf-silhouette" and {"front", "back", "top"} & views else 2.0
                    )
                    reasons.append(f"exploite les {len(ortho)} vues orthogonales")
                elif len(views) >= 2:
                    reasons.append(f"une seule image exploitée sur {len(views)} (pas de multi-vues)")
                if "three_quarter" in views and info.method == "neural":
                    score += 1.5
                    reasons.append("vue trois quarts adaptée aux réseaux image → 3D")
                if info.method == "neural":
                    score += 0.8
                    reasons.append("forme complète estimée par un réseau de neurones")
                else:
                    reasons.append("algorithme déterministe : proportions fidèles, détails limités")
                if request.quality == "high" and info.kind == "cloud":
                    score += 0.6
            candidate.score = round(score, 2)
            candidate.reasons = reasons
        ranked = sorted((c for c in candidates if c.excluded is None), key=lambda c: -c.score)
        chosen = ranked[0].engine_id if ranked else None
        explanation = []
        if ranked:
            explanation.append(f"Moteur proposé : {ranked[0].name} (score {ranked[0].score}).")
            explanation.extend(f"• {r}" for r in ranked[0].reasons)
        else:
            explanation.append("Aucun moteur disponible pour cette opération.")
        explanation.extend(f"Écarté : {c.name} — {c.excluded}" for c in candidates if c.excluded)
        ordered = sorted(candidates, key=lambda c: (c.excluded is not None, -c.score))
        return RoutingDecision(chosen, ordered, explanation)

    # --- Tâches -------------------------------------------------------------------------------
    def resource_for(self, engine_id: str) -> str:
        info = self.adapters[engine_id].info
        if info.kind == "cloud":
            return "network"
        return "local-gpu" if info.method == "neural" else "local-cpu"

    def submit(
        self, label: str, engine_id: str, function: Callable[[JobContext], object], on_done=None
    ) -> Job:  # type: ignore[no-untyped-def]
        timeout = float(self.config.get("timeout_s") or 0) or None
        return self.queue.submit(label, function, self.resource_for(engine_id), timeout, on_done)

    # --- Cache et fichiers temporaires --------------------------------------------------------
    def job_dir(self, name: str | None = None) -> Path:
        folder = self.cache_dir / "jobs" / (name or uuid.uuid4().hex[:12])
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    @staticmethod
    def cache_key(engine_id: str, version: str, profile: str, params: dict, inputs: list[str]) -> str:
        payload = json.dumps(
            [engine_id, version, profile, params, sorted(inputs)], sort_keys=True, default=str
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]

    def _index_path(self) -> Path:
        return self.cache_dir / "index.json"

    def _read_index(self) -> dict:
        try:
            index = json.loads(self._index_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return index if isinstance(index, dict) else {}

    def cache_lookup(self, key: str) -> dict | None:
        entry = self._read_index().get(key)
        if not entry:
            return None
        files = {role: Path(p) for role, p in entry.get("files", {}).items()}
        if not files or not all(p.is_file() for p in files.values()):
            return None
        return {**entry, "files": files}

    def cache_store(self, key: str, files: dict[str, Path], data: dict) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            index = self._read_index()
            index[key] = {"files": {r: str(p) for r, p in files.items()}, "data": data, "at": time.time()}
            self._index_path().write_text(
                json.dumps(index, ensure_ascii=False, default=str), encoding="utf-8"
            )

    def cleanup(self, max_age_days: float = 7.0, keep: set[str] | None = None) -> int:
        """Supprime les dossiers de tâches plus anciens que ``max_age_days`` (hors ``keep``)."""
        root = self.cache_dir / "jobs"
        if not root.is_dir():
            return 0
        keep = set(keep or set())
        limit = time.time() - max_age_days * 86400
        removed = 0
        for folder in root.iterdir():
            if not folder.is_dir() or folder.name in keep:
                continue
            try:
                if folder.stat().st_mtime < limit:
                    shutil.rmtree(folder, ignore_errors=True)
                    removed += 1
            except OSError:
                continue
        if removed:
            with self._lock:
                index = {
                    k: v
                    for k, v in self._read_index().items()
                    if all(Path(p).is_file() for p in v["files"].values())
                }
                if self.cache_dir.is_dir():
                    self._index_path().write_text(
                        json.dumps(index, ensure_ascii=False, default=str), encoding="utf-8"
                    )
        return removed

    def cache_size(self) -> int:
        if not self.cache_dir.is_dir():
            return 0
        return sum(p.stat().st_size for p in self.cache_dir.rglob("*") if p.is_file())

    def shutdown(self) -> None:
        self.queue.shutdown()
