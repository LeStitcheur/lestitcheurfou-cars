"""Adaptateur local ComfyUI : exécute un workflow fourni par l'utilisateur via l'API HTTP.

ComfyUI n'est pas livré avec l'application. L'utilisateur l'installe, y ajoute les nœuds et
modèles de son choix (en respectant leurs licences), puis exporte son workflow au format API
(« Save (API) »). L'adaptateur :

1. vérifie le serveur (``GET /system_stats`` : version, périphériques, VRAM) ;
2. vérifie que **tous** les nœuds du workflow existent (``GET /object_info``) ;
3. envoie les images (``POST /upload/image``) et les branche sur les nœuds ``LoadImage`` ;
4. met en file (``POST /prompt``), attend le résultat (``GET /history/<id>``) et récupère les
   fichiers produits (``GET /view``) : maillages (GLB, glTF, OBJ, PLY) ou images (texture) ;
5. ``POST /interrupt`` en cas d'annulation.

Les capacités dépendent du workflow : elles sont déduites des fichiers produits, jamais
supposées. **Vérification** : testé contre un serveur local simulant l'API ComfyUI ; aucun
ComfyUI réel n'était installé sur la machine de développement.
"""

from __future__ import annotations

import contextlib
import copy
import json
import urllib.parse
import uuid
from pathlib import Path

from lsfcars.ai import http
from lsfcars.ai.engines.base import (
    Availability,
    Capability,
    EngineAdapter,
    EngineInfo,
    EngineOutput,
    GenerationRequest,
    JobContext,
    Status,
)
from lsfcars.ai.errors import AIError, EngineUnavailable, InvalidOutput, ProviderError

DEFAULT_URL = "http://127.0.0.1:8188"
MESH_EXTENSIONS = (".glb", ".gltf", ".obj", ".ply")
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")


def load_workflow(path: str | Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EngineUnavailable(f"Workflow ComfyUI illisible : {exc}") from exc
    if (
        not isinstance(data, dict)
        or not data
        or not all(isinstance(v, dict) and "class_type" in v for v in data.values())
    ):
        raise EngineUnavailable(
            "Ce fichier n'est pas un workflow au format API (exportez-le avec « Save (API) » dans ComfyUI)."
        )
    return data


class ComfyUIEngine(EngineAdapter):
    info = EngineInfo(
        id="comfyui",
        name="ComfyUI (local)",
        version="API HTTP",
        kind="local",
        method="neural",
        capabilities=frozenset({Capability.IMAGE_TO_3D, Capability.TEXTURE, Capability.CONCEPT_IMAGE}),
        input_formats=("PNG", "JPG", "WEBP"),
        output_formats=("GLB", "glTF", "OBJ", "PLY", "PNG"),
        resources="Selon le workflow et les modèles installés dans ComfyUI (GPU recommandé)",
        auth="aucune (serveur local)",
        limits={"max_images": 4, "note": "capacités réelles déduites du workflow"},
        cost="gratuit (calcul local)",
        license="ComfyUI (GPL-3.0) et licences des modèles choisis par l'utilisateur",
        docs_url="https://docs.comfy.org",
        verification="Testé contre un serveur local simulant l'API ComfyUI ; non testé avec un ComfyUI réel.",
    )

    @property
    def base_url(self) -> str:
        return str(self.config.get("url") or DEFAULT_URL).rstrip("/")

    def _get(self, path: str, ctx: JobContext | None = None, timeout: float = 5.0) -> dict:
        return http.request_json(
            "GET", f"{self.base_url}{path}", ctx=ctx, timeout=timeout, retries=0, provider="ComfyUI"
        )

    def detect(self) -> Availability:
        try:
            stats = self._get("/system_stats", timeout=2.0)
        except AIError:
            return Availability(Status.MISSING, f"Aucun serveur ComfyUI sur {self.base_url}.")
        system = stats.get("system", {})
        version = str(system.get("comfyui_version") or "version inconnue")
        devices = stats.get("devices") or []
        vram = ""
        if devices:
            total = devices[0].get("vram_total")
            vram = f", {devices[0].get('name', 'GPU')}" + (f" ({total / 2**30:.1f} Go)" if total else "")
        configured = [
            (role, self.config.get(key))
            for role, key in (("3D", "workflow"), ("image conceptuelle", "concept_workflow"))
            if self.config.get(key)
        ]
        if not configured:
            return Availability(
                Status.UNCONFIGURED, f"ComfyUI {version} détecté{vram} — aucun workflow choisi.", version
            )
        for role, workflow_path in configured:
            try:
                workflow = load_workflow(workflow_path)
                missing = self.missing_nodes(workflow)
            except AIError as exc:
                return Availability(Status.ERROR, str(exc), version)
            if missing:
                return Availability(
                    Status.ERROR, f"Nœuds absents dans ComfyUI : {', '.join(sorted(missing))}.", version
                )
            if not any(n["class_type"] == "LoadImage" for n in workflow.values()):
                return Availability(Status.ERROR, f"Workflow {role} : aucun nœud LoadImage.", version)
        roles = " et ".join(role for role, _ in configured)
        return Availability(Status.AVAILABLE, f"ComfyUI {version}{vram} — workflow {roles} prêt.", version)

    def missing_nodes(self, workflow: dict) -> set[str]:
        available = set(self._get("/object_info", timeout=10.0).keys())
        return {node["class_type"] for node in workflow.values()} - available

    def run(self, request: GenerationRequest, ctx: JobContext) -> EngineOutput:
        concept = request.capability is Capability.CONCEPT_IMAGE
        workflow_path = self.config.get("concept_workflow" if concept else "workflow")
        if not workflow_path:
            kind = "d'image conceptuelle" if concept else "(format API)"
            raise EngineUnavailable(f"ComfyUI : choisissez un workflow {kind} dans les paramètres.")
        workflow = copy.deepcopy(load_workflow(workflow_path))
        missing = self.missing_nodes(workflow)
        if missing:
            raise EngineUnavailable(f"Nœuds absents dans ComfyUI : {', '.join(sorted(missing))}.")
        loaders = [key for key, node in workflow.items() if node["class_type"] == "LoadImage"]
        if not loaders:
            raise EngineUnavailable("Le workflow ne contient aucun nœud LoadImage.")
        refs = request.references[: len(loaders)]
        if not refs:
            raise EngineUnavailable("Aucune image de référence.")
        ctx.progress(0.05, f"Envoi de {len(refs)} image(s) à ComfyUI")
        for key, ref in zip(loaders, refs, strict=False):
            body, content_type = http.multipart(
                {"overwrite": "true"},
                {"image": (f"lsf_{uuid.uuid4().hex[:8]}.png", Path(ref.path).read_bytes(), "image/png")},
            )
            uploaded = http.request_json(
                "POST",
                f"{self.base_url}/upload/image",
                body=body,
                content_type=content_type,
                ctx=ctx,
                retries=0,
                provider="ComfyUI",
            )
            name = str(uploaded.get("name"))
            if uploaded.get("subfolder"):
                name = f"{uploaded['subfolder']}/{name}"
            workflow[key]["inputs"]["image"] = name
        if request.prompt:
            for node in workflow.values():
                inputs = node.get("inputs", {})
                if isinstance(inputs.get("text"), str) and "{{prompt}}" in inputs["text"]:
                    inputs["text"] = inputs["text"].replace("{{prompt}}", request.prompt)
        queued = http.request_json(
            "POST",
            f"{self.base_url}/prompt",
            body={"prompt": workflow, "client_id": uuid.uuid4().hex},
            ctx=ctx,
            retries=0,
            provider="ComfyUI",
        )
        if queued.get("node_errors"):
            raise ProviderError(f"ComfyUI a refusé le workflow : {json.dumps(queued['node_errors'])[:300]}")
        prompt_id = queued.get("prompt_id")
        if not prompt_id:
            raise ProviderError("ComfyUI n'a pas renvoyé d'identifiant.")
        poll = float(self.config.get("poll_interval", 1.0))
        waited = 0.0
        try:
            while True:
                entry = self._get(f"/history/{prompt_id}", ctx, timeout=10.0).get(prompt_id)
                if entry:
                    status = entry.get("status", {})
                    if status.get("status_str") == "error":
                        messages = json.dumps(status.get("messages", []))[:300]
                        raise ProviderError(f"ComfyUI : exécution en erreur — {messages}")
                    if status.get("completed", True):
                        break
                waited += poll
                # ComfyUI ne publie la progression détaillée que par websocket : progression indicative
                ctx.progress(min(0.85, 0.1 + waited / 600.0), f"Exécution dans ComfyUI ({int(waited)} s)")
                ctx.sleep(poll)
        except AIError:
            if ctx.cancelled():
                with contextlib.suppress(AIError):  # serveur déjà arrêté : rien à interrompre
                    http.request("POST", f"{self.base_url}/interrupt", body={}, retries=0, provider="ComfyUI")
            raise
        produced = [
            item
            for node_output in entry.get("outputs", {}).values()
            for items in node_output.values()
            if isinstance(items, list)
            for item in items
            if isinstance(item, dict) and "filename" in item
        ]
        files: dict[str, Path] = {}
        out_dir = Path(request.output_dir)
        for item in produced:
            filename = str(item["filename"])
            extension = Path(filename).suffix.lower()
            if concept:
                if extension not in IMAGE_EXTENSIONS or "concept" in files or item.get("type") != "output":
                    continue
                role = "concept"  # image 2D uniquement : jamais présentée comme un modèle 3D
            elif extension in MESH_EXTENSIONS and "model" not in files:
                role = "model"
            elif extension in IMAGE_EXTENSIONS and "base_color" not in files and item.get("type") == "output":
                role = "base_color"
            else:
                continue
            query = urllib.parse.urlencode(
                {
                    "filename": filename,
                    "subfolder": item.get("subfolder", ""),
                    "type": item.get("type", "output"),
                }
            )
            files[role] = http.download(
                f"{self.base_url}/view?{query}",
                out_dir / f"comfyui_{Path(filename).name}",
                ctx=ctx,
                provider="ComfyUI",
            )
        if request.capability in (Capability.IMAGE_TO_3D, Capability.MULTIVIEW_3D) and "model" not in files:
            raise InvalidOutput("Le workflow n'a produit aucun maillage (GLB, glTF, OBJ ou PLY).")
        if not files:
            raise InvalidOutput("Le workflow n'a produit aucun fichier exploitable.")
        ctx.progress(1.0, "Résultat ComfyUI récupéré")
        main = files.get("model") or next(iter(files.values()))
        return EngineOutput(
            files,
            main.suffix.lstrip("."),
            data={"prompt_id": prompt_id},
            used_views=[r.view for r in refs],
            warnings=["Une seule image utilisée par le workflow."] if len(refs) == 1 else [],
        )
