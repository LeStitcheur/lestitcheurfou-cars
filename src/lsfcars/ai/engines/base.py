"""Interface commune des adaptateurs IA.

Chaque adaptateur déclare ce qu'il sait réellement faire (``EngineInfo``) : capacités, formats,
ressources, authentification, limites, coûts et **niveau de vérification** (génération réelle
exécutée, ou seulement testée contre un serveur simulé). Le gestionnaire ne suppose jamais
qu'un moteur prend en charge une fonction qu'il n'a pas déclarée.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path

from lsfcars.ai.errors import EngineUnavailable, JobCancelled, JobTimeout
from lsfcars.ai.hardware import HardwareInfo


class Capability(StrEnum):
    IMAGE_TO_3D = "image_to_3d"  # une image → maillage
    MULTIVIEW_3D = "multiview_3d"  # plusieurs vues exploitées ensemble
    VISION = "vision"  # analyse d'images (rapport)
    LORE_TEXT = "lore_text"  # suggestions textuelles (noms, directions artistiques)
    TEXTURE = "texture"  # texture couleur
    PBR = "pbr"  # cartes PBR (normal, roughness, metallic…)
    SEGMENTATION = "segmentation"  # détourage
    MESH_OPS = "mesh_ops"  # remaillage, décimation

    @property
    def label(self) -> str:
        return {
            "image_to_3d": "Image → 3D",
            "multiview_3d": "Multi-vues → 3D",
            "vision": "Analyse d'images",
            "lore_text": "Suggestions Lore Friendly",
            "texture": "Texture couleur",
            "pbr": "Cartes PBR",
            "segmentation": "Détourage",
            "mesh_ops": "Opérations de maillage",
        }[self.value]


class Status(StrEnum):
    AVAILABLE = "available"
    UNCONFIGURED = "unconfigured"  # installé mais à configurer (clé, adresse…)
    MISSING = "missing"  # non installé
    ERROR = "error"  # détecté mais inutilisable

    @property
    def label(self) -> str:
        return {
            "available": "Disponible",
            "unconfigured": "À configurer",
            "missing": "Non installé",
            "error": "Erreur",
        }[self.value]


@dataclass(frozen=True)
class EngineInfo:
    id: str
    name: str
    version: str
    kind: str  # « local » ou « cloud »
    method: str  # « neural » (réseau de neurones) ou « algorithmic » (algorithme déterministe)
    capabilities: frozenset[Capability]
    input_formats: tuple[str, ...]
    output_formats: tuple[str, ...]
    resources: str
    auth: str  # « aucune », « clé API »
    limits: dict = field(default_factory=dict)  # max_images, max_image_mb, max_resolution…
    cost: str = "gratuit (calcul local)"
    license: str = ""
    docs_url: str = ""
    verification: str = ""  # comment l'adaptateur a été vérifié (réel / simulé)
    min_vram_mb: int = 0
    min_ram_mb: int = 0

    def supports(self, capability: Capability) -> bool:
        return capability in self.capabilities

    @property
    def max_images(self) -> int:
        return int(self.limits.get("max_images", 1))

    @property
    def method_label(self) -> str:
        return "IA (réseau de neurones)" if self.method == "neural" else "Algorithme déterministe"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["capabilities"] = sorted(c.value for c in self.capabilities)
        return data


@dataclass
class Availability:
    status: Status
    message: str
    detected_version: str = ""

    @property
    def ok(self) -> bool:
        return self.status is Status.AVAILABLE


@dataclass
class ProfileOption:
    """Profil de qualité tel que ce moteur peut réellement le tenir sur ce matériel."""

    key: str  # « eco », « balanced », « high »
    label: str
    params: dict
    available: bool = True
    reason: str = ""


SIMULATED_ONLY = (
    "Testé contre un serveur local simulant le contrat documenté ; non testé avec le service réel."
)
PROFILE_LABELS = {"eco": "Économique", "balanced": "Équilibré", "high": "Haute qualité"}


@dataclass
class CostEstimate:
    amount: float | None  # None : coût non communiqué (jamais inventé)
    unit: str = ""  # « crédits », « USD »
    note: str = ""
    paid: bool = False  # opération facturée : confirmation obligatoire

    def describe(self) -> str:
        if self.amount is None:
            return self.note or "coût non communiqué par le fournisseur"
        if not self.paid:
            return self.note or "gratuit"
        return f"≈ {self.amount:g} {self.unit}" + (f" ({self.note})" if self.note else "")


@dataclass
class ReferenceInput:
    path: Path  # image préparée (recadrée, orientée)
    view: str  # front, back, left, right, three_quarter, top, interior, detail
    mask_path: Path | None = None  # détourage (PNG niveaux de gris), si disponible


@dataclass
class GenerationRequest:
    capability: Capability
    references: list[ReferenceInput]
    output_dir: Path
    profile: str = "balanced"
    params: dict = field(default_factory=dict)
    prompt: str = ""
    vehicle: dict = field(default_factory=dict)  # dimensions estimées, type… (indicatif)
    allow_cloud: bool = False  # consentement explicite au transfert
    allow_paid: bool = False  # consentement explicite à une opération facturée


@dataclass
class EngineOutput:
    files: dict[str, Path]  # rôle (model, base_color, normal, roughness, metallic…) → fichier
    format: str = ""
    reported_cost: str = ""  # coût communiqué par le fournisseur (vide : non communiqué)
    data: dict = field(default_factory=dict)  # résultat structuré (analyse, suggestions)
    warnings: list[str] = field(default_factory=list)
    used_views: list[str] = field(default_factory=list)  # vues réellement exploitées


class JobContext:
    """Progression, annulation, délai maximal et journal d'une tâche."""

    def __init__(
        self,
        progress: Callable[[float, str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
        timeout: float | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self._progress = progress or (lambda _v, _t: None)
        self._cancelled = cancelled or (lambda: False)
        self._log = log or (lambda _t: None)
        self.deadline = time.monotonic() + timeout if timeout else None

    def progress(self, value: float, text: str = "") -> None:
        self.check()
        self._progress(max(0.0, min(1.0, float(value))), text)

    def log(self, text: str) -> None:
        self._log(text)

    def cancelled(self) -> bool:
        return self._cancelled()

    def remaining(self) -> float | None:
        return None if self.deadline is None else self.deadline - time.monotonic()

    def check(self) -> None:
        if self._cancelled():
            raise JobCancelled("Tâche annulée.")
        if self.deadline is not None and time.monotonic() > self.deadline:
            raise JobTimeout("Délai maximal dépassé : la tâche a été interrompue.")

    def sleep(self, seconds: float) -> None:
        """Attente interruptible (annulation et délai vérifiés toutes les 0,1 s)."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.check()
            time.sleep(min(0.1, max(0.0, end - time.monotonic())))


class EngineAdapter(ABC):
    """Adaptateur d'un moteur IA. ``run`` s'exécute dans un thread de travail (jamais Qt)."""

    info: EngineInfo

    def __init__(self, config: dict | None = None) -> None:
        self.config: dict = dict(config or {})

    def configure(self, config: dict) -> None:
        self.config.update(config)

    @abstractmethod
    def detect(self) -> Availability:
        """Vérifie l'installation / la configuration (rapide, sans opération facturée)."""

    def test_connection(self, ctx: JobContext | None = None) -> Availability:
        """Test explicite (appel réseau gratuit pour le cloud) ; par défaut identique à ``detect``."""
        return self.detect()

    def profiles(self, hardware: HardwareInfo | None) -> list[ProfileOption]:
        return [ProfileOption("balanced", PROFILE_LABELS["balanced"], {})]

    def estimate(self, request: GenerationRequest) -> CostEstimate:
        return CostEstimate(0.0, "", "calcul local, gratuit")

    @abstractmethod
    def run(self, request: GenerationRequest, ctx: JobContext) -> EngineOutput:
        """Exécute la tâche ; lève une ``AIError`` explicite en cas d'échec."""

    # --- Aides -------------------------------------------------------------------------------
    def require(self, capability: Capability) -> None:
        if not self.info.supports(capability):
            raise EngineUnavailable(f"{self.info.name} ne prend pas en charge : {capability.label}.")

    def profile_params(self, request: GenerationRequest, hardware: HardwareInfo | None) -> dict:
        options = {p.key: p for p in self.profiles(hardware)}
        option = options.get(request.profile) or next(iter(options.values()))
        if not option.available:
            raise EngineUnavailable(f"Profil « {option.label} » indisponible : {option.reason}")
        return {**option.params, **request.params}
