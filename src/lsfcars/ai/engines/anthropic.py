"""Adaptateur cloud Anthropic (Claude) : analyse d'images et suggestions Lore Friendly.

API publique documentée (https://docs.anthropic.com) : ``POST /v1/messages`` avec blocs
``image`` (base64) et ``text`` ; ``GET /v1/models`` sert de test de connexion (gratuit).
En-têtes ``x-api-key`` et ``anthropic-version: 2023-06-01``.

Le modèle répond en JSON ; la réponse est validée puis rangée dans la section « cloud » du
rapport, toujours distinguée de l'analyse locale. Aucune génération 3D par cet adaptateur.
Le coût dépend de la tarification Anthropic : il n'est pas estimé à l'avance ; les jetons
consommés (``usage``) sont affichés après l'appel. **Vérification** : testé contre un serveur
local simulant ce contrat ; non testé avec le service réel (aucune clé pendant le
développement).
"""

from __future__ import annotations

import base64
import io
import json
import re
from pathlib import Path

from PIL import Image

from lsfcars.ai import http
from lsfcars.ai.engines.base import (
    SIMULATED_ONLY,
    Availability,
    Capability,
    CostEstimate,
    EngineAdapter,
    EngineInfo,
    EngineOutput,
    GenerationRequest,
    JobContext,
    Status,
)
from lsfcars.ai.errors import ConsentRequired, EngineUnavailable, InvalidOutput
from lsfcars.ai.references import VIEWS

DEFAULT_BASE_URL = "https://api.anthropic.com"
DEFAULT_MODEL = "claude-opus-5-5"
API_VERSION = "2023-06-01"

VISION_PROMPT = """Tu analyses des images de référence d'un véhicule pour un logiciel de modélisation 3D.
Vues fournies : {views}.
Réponds UNIQUEMENT par un objet JSON valide, en français, avec les clés :
"type" (une valeur parmi : {types}),
"type_confidence" (0 à 1),
"proportions" (texte court),
"silhouette" (texte court),
"wheels" (texte court : nombre visible, taille relative),
"body" (texte court : carrosserie, lignes),
"lights" (texte court : optiques avant / arrière),
"glazing" (texte court : vitrages),
"colors" (liste de couleurs hexadécimales),
"distinctive" (liste d'éléments distinctifs),
"real_brands" (liste des marques, logos ou noms réels visibles ; liste vide si aucun),
"inconsistencies" (liste d'incohérences entre les images),
"invisible_zones" (liste des zones non visibles qui devront être estimées).
N'invente pas de détails invisibles sur les images."""

LORE_PROMPT = """Tu aides à concevoir un véhicule ORIGINAL cohérent avec l'univers satirique de GTA V,
à partir des références fournies. Résumé de l'analyse : {summary}
Réponds UNIQUEMENT par un objet JSON valide, en français, avec la clé "proposals" : une liste de trois
objets (niveaux "light", "balanced", "original"), chacun avec :
"level", "brand" (marque fictive inventée, pas une marque réelle), "model_name" (nom fictif),
"grille" (variation de calandre), "lights" (modification des optiques), "body" (modifications de
carrosserie), "details" (liste de détails distinctifs à modifier), "direction" (direction artistique).
N'utilise aucune marque, aucun logo ni nom de modèle réel."""

DESIGN_PROMPT = """Tu aides à transformer un véhicule de référence en un véhicule ORIGINAL cohérent avec
l'univers satirique de GTA V. Analyse mesurée du véhicule : {summary}
Tu ne modifies rien toi-même : tu proposes des opérations choisies UNIQUEMENT dans ce catalogue
(clé, paramètres et bornes) : {catalogue}
Réponds UNIQUEMENT par un objet JSON valide, en français, avec la clé "proposals" : une liste de
{count} objets avec "title" (nom fictif, aucune marque ni modèle réel), "summary" (texte court),
"plan" (liste d'objets {{"op": clé du catalogue, "params": {{...}}, "why": "raison"}}).
N'invente aucune opération hors catalogue."""


def _image_block(path: Path, max_side: int = 1568) -> dict:
    image = Image.open(path).convert("RGB")
    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=90)
    data = base64.b64encode(buffer.getvalue()).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


def parse_json(text: str) -> dict:
    """Premier objet JSON de la réponse (tolère un bloc ```json)."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise InvalidOutput("Réponse du modèle sans objet JSON.")
    try:
        data = json.loads(match.group(0))
    except ValueError as exc:
        raise InvalidOutput(f"JSON invalide dans la réponse du modèle : {exc}") from exc
    if not isinstance(data, dict):
        raise InvalidOutput("Réponse JSON inattendue.")
    return data


class AnthropicEngine(EngineAdapter):
    info = EngineInfo(
        id="anthropic",
        name="Claude (Anthropic, cloud)",
        version=f"Messages API {API_VERSION}",
        kind="cloud",
        method="neural",
        capabilities=frozenset({Capability.VISION, Capability.LORE_TEXT, Capability.DESIGN_PLAN}),
        input_formats=("PNG", "JPG", "WEBP"),
        output_formats=("JSON",),
        resources="Service distant",
        auth="clé API (x-api-key)",
        limits={"max_images": 8, "max_side_px": 1568},
        cost="facturé au jeton selon la tarification Anthropic (non estimé à l'avance)",
        license="Conditions d'utilisation de l'API Anthropic",
        docs_url="https://docs.anthropic.com/en/api/messages",
        verification=SIMULATED_ONLY,
    )

    def __init__(self, config: dict | None = None, secrets=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(config)
        self.secrets = secrets

    @property
    def base_url(self) -> str:
        return str(self.config.get("base_url") or DEFAULT_BASE_URL).rstrip("/")

    @property
    def model(self) -> str:
        return str(self.config.get("model") or DEFAULT_MODEL)

    def _key(self) -> str | None:
        return self.secrets.get("anthropic") if self.secrets is not None else None

    def _headers(self) -> dict:
        key = self._key()
        if not key:
            raise EngineUnavailable("Anthropic : aucune clé API configurée.")
        return {"x-api-key": key, "anthropic-version": API_VERSION}

    def detect(self) -> Availability:
        if not self._key():
            return Availability(Status.UNCONFIGURED, "Clé API absente (Paramètres des moteurs).")
        return Availability(Status.AVAILABLE, f"Clé configurée ({self.model}) — connexion non testée.")

    def test_connection(self, ctx: JobContext | None = None) -> Availability:
        if not self._key():
            return self.detect()
        data = http.request_json(
            "GET", f"{self.base_url}/v1/models", headers=self._headers(), ctx=ctx, provider="Anthropic"
        )
        models = [m.get("id") for m in data.get("data", []) if isinstance(m, dict)]
        found = "disponible" if self.model in models else "absent de la liste renvoyée"
        return Availability(
            Status.AVAILABLE, f"Connexion réussie — modèle {self.model} {found}.", API_VERSION
        )

    def estimate(self, request: GenerationRequest) -> CostEstimate:
        return CostEstimate(None, "", "facturé au jeton (tarification Anthropic) : non estimé", paid=True)

    def run(self, request: GenerationRequest, ctx: JobContext) -> EngineOutput:
        if not request.allow_cloud:
            raise ConsentRequired("Transfert vers Anthropic non confirmé : aucune image n'a été envoyée.")
        if not request.allow_paid:
            raise ConsentRequired("Appel Anthropic facturé non confirmé.")
        self.require(request.capability)
        headers = self._headers()
        refs = request.references[: self.info.max_images]
        views = ", ".join(VIEWS.get(r.view, r.view) for r in refs) or "aucune"
        if request.capability is Capability.VISION:
            from lsfcars.ai.vision import VEHICLE_TYPES

            prompt = VISION_PROMPT.format(views=views, types=", ".join(VEHICLE_TYPES))
        elif request.capability is Capability.DESIGN_PLAN:
            prompt = DESIGN_PROMPT.format(
                summary=request.prompt or "non fourni",
                catalogue=request.params.get("catalogue", "[]"),
                count=int(request.params.get("count", 3)),
            )
        else:
            prompt = LORE_PROMPT.format(summary=request.prompt or "non fourni")
        ctx.progress(0.1, f"Envoi à Anthropic ({len(refs)} image(s))")
        content = [_image_block(r.path) for r in refs] + [{"type": "text", "text": prompt}]
        body = {
            "model": self.model,
            "max_tokens": int(self.config.get("max_tokens", 2000)),
            "messages": [{"role": "user", "content": content}],
        }
        response = http.request_json(
            "POST",
            f"{self.base_url}/v1/messages",
            headers=headers,
            body=body,
            ctx=ctx,
            timeout=120,
            retries=1,
            backoff=float(self.config.get("backoff", 1.0)),
            provider="Anthropic",
        )
        text = "".join(b.get("text", "") for b in response.get("content", []) if b.get("type") == "text")
        data = parse_json(text)
        usage = response.get("usage") or {}
        cost = ""
        if usage:
            tokens_in, tokens_out = usage.get("input_tokens", "?"), usage.get("output_tokens", "?")
            cost = f"{tokens_in} jetons en entrée, {tokens_out} en sortie"
        ctx.progress(1.0, "Réponse reçue")
        return EngineOutput(
            {},
            "json",
            reported_cost=cost,
            data={"model": self.model, "result": data},
            used_views=[r.view for r in refs],
        )
