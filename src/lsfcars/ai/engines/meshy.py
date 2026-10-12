"""Adaptateur cloud Meshy (API publique documentée : https://docs.meshy.ai).

Contrat utilisé (vérifié dans la documentation officielle le 2026-10-12) :
- ``POST /openapi/v1/image-to-3d`` (``image_url`` : URL publique ou URI ``data:`` base64) ;
- ``POST /openapi/v1/multi-image-to-3d`` (``image_urls`` : 1 à 4 images) ;
- ``GET  /openapi/v1/<type>/:id`` : ``status`` (PENDING, IN_PROGRESS, SUCCEEDED, FAILED,
  CANCELED), ``progress`` 0-100, ``model_urls``, ``texture_urls``, ``consumed_credits`` ;
- ``GET  /openapi/v1/balance`` : solde de crédits (test de connexion gratuit) ;
- authentification ``Authorization: Bearer <clé>``.

Les images ne partent qu'avec le consentement explicite de l'utilisateur (``allow_cloud``) et
l'opération facturée exige ``allow_paid``. L'estimation suit la grille de crédits publiée
(susceptible d'évoluer) ; le coût affiché après coup est celui renvoyé par Meshy.
**Vérification** : testé contre un serveur local reproduisant ce contrat, pas contre le
service réel (aucune clé disponible pendant le développement).
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image

from lsfcars.ai import http
from lsfcars.ai.engines.base import (
    PROFILE_LABELS,
    SIMULATED_ONLY,
    Availability,
    Capability,
    CostEstimate,
    EngineAdapter,
    EngineInfo,
    EngineOutput,
    GenerationRequest,
    JobContext,
    ProfileOption,
    Status,
)
from lsfcars.ai.errors import ConsentRequired, EngineUnavailable, InvalidOutput, ProviderError
from lsfcars.ai.hardware import HardwareInfo

DEFAULT_BASE_URL = "https://api.meshy.ai"
VIEW_PRIORITY = ("three_quarter", "left", "front", "right", "back", "top")
PROFILES = {
    "eco": {"ai_model": "meshy-6-lite", "should_texture": False, "credits": 5},
    "balanced": {"ai_model": "meshy-6", "should_texture": True, "texture_resolution": "2k", "credits": 30},
    "high": {
        "ai_model": "latest",
        "should_texture": True,
        "enable_pbr": True,
        "texture_resolution": "4k",
        "credits": 30,
    },
}


def data_uri(path: Path, max_side: int = 2048) -> str:
    image = Image.open(path)
    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    data = buffer.getvalue()
    if len(data) > 20 * 1024 * 1024:
        raise ProviderError("Image trop volumineuse pour Meshy (20 Mo au plus).")
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


class MeshyEngine(EngineAdapter):
    info = EngineInfo(
        id="meshy",
        name="Meshy (cloud)",
        version="API openapi/v1",
        kind="cloud",
        method="neural",
        capabilities=frozenset(
            {Capability.IMAGE_TO_3D, Capability.MULTIVIEW_3D, Capability.TEXTURE, Capability.PBR}
        ),
        input_formats=("PNG", "JPG", "WEBP"),
        output_formats=("GLB", "OBJ", "FBX"),
        resources="Service distant (aucune ressource locale)",
        auth="clé API (Bearer)",
        limits={"max_images": 4, "max_image_mb": 20},
        cost="facturé en crédits Meshy (5 à 35 crédits par génération selon la grille publiée)",
        license="Conditions d'utilisation Meshy (vérifiez les droits sur les modèles générés)",
        docs_url="https://docs.meshy.ai/en/api/image-to-3d",
        verification=SIMULATED_ONLY,
    )

    def __init__(self, config: dict | None = None, secrets=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(config)
        self.secrets = secrets

    @property
    def base_url(self) -> str:
        return str(self.config.get("base_url") or DEFAULT_BASE_URL).rstrip("/")

    def _key(self) -> str | None:
        return self.secrets.get("meshy") if self.secrets is not None else None

    def _headers(self) -> dict:
        key = self._key()
        if not key:
            raise EngineUnavailable("Meshy : aucune clé API configurée.")
        return {"Authorization": f"Bearer {key}"}

    def detect(self) -> Availability:
        if not self._key():
            return Availability(Status.UNCONFIGURED, "Clé API absente (Paramètres des moteurs).")
        return Availability(Status.AVAILABLE, "Clé configurée — connexion non testée.")

    def test_connection(self, ctx: JobContext | None = None) -> Availability:
        if not self._key():
            return self.detect()
        data = http.request_json(
            "GET", f"{self.base_url}/openapi/v1/balance", headers=self._headers(), ctx=ctx, provider="Meshy"
        )
        return Availability(
            Status.AVAILABLE, f"Connexion réussie — solde : {data.get('balance')} crédits.", "openapi/v1"
        )

    def profiles(self, hardware: HardwareInfo | None) -> list[ProfileOption]:
        labels = {
            "eco": "maillage sans texture (meshy-6-lite)",
            "balanced": "texture 2K (meshy-6)",
            "high": "texture 4K + PBR (dernier modèle)",
        }
        return [
            ProfileOption(key, f"{PROFILE_LABELS[key]} — {labels[key]}", dict(params))
            for key, params in PROFILES.items()
        ]

    def estimate(self, request: GenerationRequest) -> CostEstimate:
        params = PROFILES.get(request.profile, PROFILES["balanced"])
        return CostEstimate(
            float(params["credits"]),
            "crédits Meshy",
            "grille publiée, à confirmer par le solde après génération",
            paid=True,
        )

    def _choose(self, request: GenerationRequest) -> list:
        pool = sorted(
            request.references,
            key=lambda r: VIEW_PRIORITY.index(r.view) if r.view in VIEW_PRIORITY else len(VIEW_PRIORITY),
        )
        return pool[: self.info.max_images]

    def run(self, request: GenerationRequest, ctx: JobContext) -> EngineOutput:
        if not request.allow_cloud:
            raise ConsentRequired("Transfert vers Meshy non confirmé : aucune image n'a été envoyée.")
        if not request.allow_paid:
            raise ConsentRequired("Opération Meshy facturée non confirmée.")
        headers = self._headers()
        chosen = self._choose(request)
        if not chosen:
            raise EngineUnavailable("Aucune image de référence à envoyer.")
        params = {
            k: v for k, v in PROFILES.get(request.profile, PROFILES["balanced"]).items() if k != "credits"
        }
        params["target_formats"] = ["glb"]
        multi = len(chosen) > 1
        ctx.progress(0.02, f"Envoi de {len(chosen)} image(s) à Meshy")
        if multi:
            body = {"image_urls": [data_uri(r.path) for r in chosen], **params}
            kind = "multi-image-to-3d"
        else:
            body = {"image_url": data_uri(chosen[0].path), **params}
            kind = "image-to-3d"
        created = http.request_json(
            "POST",
            f"{self.base_url}/openapi/v1/{kind}",
            headers=headers,
            body=body,
            ctx=ctx,
            retries=1,
            backoff=float(self.config.get("backoff", 1.0)),
            provider="Meshy",
        )
        task_id = created.get("result")
        if not task_id:
            raise ProviderError("Meshy n'a pas renvoyé d'identifiant de tâche.")
        ctx.log(f"Tâche Meshy {task_id} créée ({kind}).")
        poll = float(self.config.get("poll_interval", 5.0))
        while True:
            task = http.request_json(
                "GET",
                f"{self.base_url}/openapi/v1/{kind}/{task_id}",
                headers=headers,
                ctx=ctx,
                backoff=float(self.config.get("backoff", 1.0)),
                provider="Meshy",
            )
            status = str(task.get("status"))
            progress = float(task.get("progress") or 0) / 100.0
            ctx.progress(0.05 + 0.85 * progress, f"Meshy : {status} ({int(progress * 100)} %)")
            if status == "SUCCEEDED":
                break
            if status in ("FAILED", "CANCELED"):
                message = (task.get("task_error") or {}).get("message") or status
                raise ProviderError(f"Meshy : génération {status.lower()} — {message}")
            ctx.sleep(poll)
        model_url = (task.get("model_urls") or {}).get("glb")
        if not model_url:
            raise InvalidOutput("Meshy n'a pas fourni de fichier GLB.")
        out_dir = Path(request.output_dir)
        files = {"model": http.download(model_url, out_dir / "meshy.glb", ctx=ctx, provider="Meshy")}
        textures = task.get("texture_urls") or []
        if textures and isinstance(textures[0], dict):
            for role in ("base_color", "normal", "roughness", "metallic"):
                url = textures[0].get(role)
                if url:
                    files[role] = http.download(url, out_dir / f"meshy_{role}.png", ctx=ctx, provider="Meshy")
        ctx.progress(1.0, "Modèle Meshy récupéré")
        credits = task.get("consumed_credits")
        return EngineOutput(
            files,
            "glb",
            reported_cost=f"{credits} crédits Meshy" if credits is not None else "",
            data={"task_id": task_id, "endpoint": kind, "status": status},
            used_views=[r.view for r in chosen],
            warnings=[] if multi else ["Une seule image envoyée (Image → 3D)."],
        )
