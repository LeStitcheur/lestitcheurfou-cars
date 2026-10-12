"""AI Vehicle Creator : service du projet (références, analyse, Lore, génération, historique,
maillage, textures), sans Qt.

Tout l'état vit dans ``SceneGraph.documents["ai"]`` (JSON, format 1) et n'est modifié que par
des commandes annulables (``SetDocument`` dans une ``CompositeCommand``). Les images de
référence et les miniatures sont des blobs du projet (table ``blobs`` du ``.lsfc``) ; les
modèles générés sont importés comme des fichiers du projet (``assets/``) avec leur provenance ;
les fichiers annexes (textures, rapports) vont dans ``assets/ai/<génération>/``. Aucune clé API
n'est jamais écrite dans le document.

Les opérations longues (analyse, génération, textures) sont des fonctions ``job(ctx)``
exécutées par la file du gestionnaire ; leur résultat est appliqué ensuite dans le fil
principal (``apply_*``).
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from lsfcars.ai import lore, mesh_assist, raster3d, vision
from lsfcars.ai import references as refs_mod
from lsfcars.ai import texture as tex
from lsfcars.ai.engines.base import Capability, EngineOutput, GenerationRequest, JobContext, ReferenceInput
from lsfcars.ai.errors import AIError, EngineUnavailable, InvalidOutput
from lsfcars.ai.manager import AIEngineManager
from lsfcars.core.logging_setup import get_logger
from lsfcars.importers.base import ImportResult, ModelLoadError
from lsfcars.scene import mathutils
from lsfcars.scene.commands import AddBlob, AddMaterial, AssignMaterial, CompositeCommand, SetDocument
from lsfcars.scene.editmesh import EditError
from lsfcars.scene.graph import NodeKind
from lsfcars.scene.materials import Material
from lsfcars.scene.transform import Transform, euler_xyz_from_rotation

log = get_logger(__name__)

DOC_KEY = "ai"
DOC_VERSION = 1
METRIC_ENGINES = {"lsf-silhouette"}  # sorties déjà à l'échelle (mètres, repère du véhicule)
# Rotation (degrés XYZ) ramenant la sortie d'un moteur à « Y vertical » (TripoSR : Z vertical).
ENGINE_ORIENTATION: dict[str, tuple[float, float, float]] = {"triposr": (-90.0, 0.0, 0.0)}


def principal_alignment(points: np.ndarray) -> np.ndarray:
    """Rotation alignant un nuage sur le repère du véhicule (X latéral, Y vertical, Z longueur).

    Analyse en composantes principales : l'axe vertical est le vecteur propre le plus proche de
    +Y (la sortie a déjà été redressée grossièrement), la longueur le plus grand des deux autres.
    Corrige l'inclinaison due à l'élévation de la caméra de référence. Le sens avant / arrière
    reste ambigu : l'utilisateur peut retourner le modèle de 180°.
    """
    centered = points - points.mean(axis=0)
    _, vectors = np.linalg.eigh(np.cov(centered.T))
    up_index = int(np.argmax(np.abs(vectors[1])))
    up = vectors[:, up_index] * (1.0 if vectors[1, up_index] >= 0 else -1.0)
    others = [i for i in range(3) if i != up_index]
    spreads = [float(np.var(centered @ vectors[:, i])) for i in others]
    length = vectors[:, others[int(np.argmax(spreads))]]
    length = length - up * float(length @ up)
    length /= np.linalg.norm(length)
    if length[2] < 0:  # garde le sens d'origine autant que possible
        length = -length
    lateral = np.cross(up, length)
    rotation = np.stack([lateral, up, length])  # lignes : nouveaux axes exprimés dans l'ancien repère
    return ground_refinement(centered @ rotation.T) @ rotation


def _align(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Rotation minimale amenant le vecteur unitaire ``source`` sur ``target`` (Rodrigues)."""
    axis = np.cross(source, target)
    sin, cos = float(np.linalg.norm(axis)), float(source @ target)
    if sin < 1e-9:
        return np.eye(3)
    k = axis / sin
    skew = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + sin * skew + (1 - cos) * skew @ skew


def ground_refinement(points: np.ndarray, iterations: int = 3, max_tilt: float = 25.0) -> np.ndarray:
    """Redresse le tangage et le roulis : plan d'appui ajusté sur les points les plus bas (pneus)."""
    rotation = np.eye(3)
    for _ in range(iterations):
        p = points @ rotation.T
        height = float(np.ptp(p[:, 1])) or 1.0
        low = p[p[:, 1] < p[:, 1].min() + 0.04 * height]
        if (
            len(low) < 8
            or np.ptp(low[:, 0]) < 0.2 * np.ptp(p[:, 0])
            or np.ptp(low[:, 2]) < 0.3 * np.ptp(p[:, 2])
        ):
            break  # appuis trop concentrés : plan non fiable
        design = np.column_stack([low[:, 0], low[:, 2], np.ones(len(low))])
        (a, b, _c), *_ = np.linalg.lstsq(design, low[:, 1], rcond=None)
        normal = np.array([-a, 1.0, -b])
        normal /= np.linalg.norm(normal)
        tilt = np.degrees(np.arccos(np.clip(normal[1], -1, 1)))
        if tilt < 0.2 or tilt > max_tilt:
            break
        rotation = _align(normal, np.array([0.0, 1.0, 0.0])) @ rotation
    return rotation


def empty_document() -> dict:
    return {
        "version": DOC_VERSION,
        "references": [],
        "analysis": None,
        "lore": {"proposals": [], "selected": None},
        "settings": {
            "engine": "auto",
            "profile": "balanced",
            "mode": "",
            "length_m": None,
            "prompt": "",
            "texture_preset": "paint_gloss",
            "texture_size": 1024,
        },
        "generations": [],
        "textures": [],
    }


@dataclass
class GenerationOutcome:
    """Résultat d'une tâche de génération, prêt à être appliqué au projet (fil principal)."""

    engine_id: str
    profile: str
    params: dict
    prompt: str
    references: list[str]
    output: EngineOutput
    import_result: ImportResult
    thumbnail: bytes
    duration_s: float
    estimated_cost: str
    cached: bool = False


@dataclass
class TextureOutcome:
    node_id: str
    method: str
    maps: dict[str, np.ndarray]  # rôle → image
    sources: dict[str, str]  # rôle → origine (clé de ``texture.MAP_SOURCES``)
    mesh: object | None  # nouveau MeshData si des UV ont été créées
    stats: dict = field(default_factory=dict)


class AIVehicleCreator:
    def __init__(self, session, manager: AIEngineManager) -> None:  # type: ignore[no-untyped-def]
        self.session = session
        self.manager = manager
        self._prepared: dict[tuple, Image.Image] = {}
        self._segments: dict[tuple, refs_mod.Segmentation] = {}

    # --- Document -----------------------------------------------------------------------------
    @property
    def scene(self):  # type: ignore[no-untyped-def]
        return self.session.scene

    def document(self) -> dict:
        doc = self.scene.documents.get(DOC_KEY)
        merged = empty_document()
        if doc is None:
            return merged
        settings = {**merged["settings"], **doc.get("settings", {})}
        merged.update(copy.deepcopy(doc))
        merged["settings"] = settings
        return merged

    def _push(self, label: str, mutate, extra: list | None = None) -> dict:  # type: ignore[no-untyped-def]
        before = copy.deepcopy(self.scene.documents.get(DOC_KEY))
        after = self.document()
        mutate(after)
        steps = list(extra or []) + [SetDocument(DOC_KEY, before, after, label)]
        self.session.stack.push(CompositeCommand(steps, label))
        return after

    def set_settings(self, **changes) -> None:  # type: ignore[no-untyped-def]
        current = self.document()["settings"]
        if all(current.get(k) == v for k, v in changes.items()):
            return
        self._push("Réglages IA", lambda doc: doc["settings"].update(changes))

    # --- Références ---------------------------------------------------------------------------
    def references(self) -> list[dict]:
        return refs_mod.ordered(self.document()["references"])

    def reference(self, ref_id: str) -> dict:
        ref = next((r for r in self.document()["references"] if r["id"] == ref_id), None)
        if ref is None:
            raise AIError("Référence introuvable.")
        return ref

    def add_reference(
        self,
        source: str | Path | bytes,
        name: str | None = None,
        view: str | None = None,
        origin: str = "",
        license_text: str = "",
    ) -> str:
        if isinstance(source, bytes):
            data, name = source, name or "reference.png"
        else:
            path = Path(source)
            if path.suffix.lower() not in refs_mod.IMAGE_EXTENSIONS:
                raise AIError(
                    f"Format non pris en charge : {path.suffix or 'sans extension'} (PNG, JPG, WEBP…)."
                )
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise AIError(f"Lecture impossible : {exc}") from exc
            name = name or path.name
            origin = origin or str(path)
        ref = refs_mod.new_reference(data, name, view or refs_mod.guess_view(name), origin)
        ref["license"] = license_text
        existing = self.document()["references"]
        ref["order"] = max((int(r.get("order", 0)) for r in existing), default=-1) + 1
        self._push(
            f"Référence « {name} »", lambda doc: doc["references"].append(ref), [AddBlob(ref["blob"], data)]
        )
        return ref["id"]

    def update_reference(self, ref_id: str, **changes) -> None:  # type: ignore[no-untyped-def]
        allowed = {
            "name", "view", "rotation", "flip", "crop", "adjust", "front_left", "source", "author", "license",
            "notes", "annotations",
        }  # fmt: skip
        unknown = set(changes) - allowed
        if unknown:
            raise AIError(f"Champs inconnus : {', '.join(sorted(unknown))}")
        if "view" in changes and changes["view"] not in refs_mod.VIEWS:
            raise AIError("Vue inconnue.")
        self.reference(ref_id)

        def mutate(doc: dict) -> None:
            for ref in doc["references"]:
                if ref["id"] == ref_id:
                    ref.update(copy.deepcopy(changes))

        self._push("Référence modifiée", mutate)

    def rotate_reference(self, ref_id: str, degrees: int = 90) -> None:
        ref = self.reference(ref_id)
        self.update_reference(ref_id, rotation=(int(ref.get("rotation", 0)) + degrees) % 360)

    def remove_reference(self, ref_id: str) -> None:
        self.reference(ref_id)

        def mutate(doc: dict) -> None:
            doc["references"] = [r for r in doc["references"] if r["id"] != ref_id]

        self._push("Référence supprimée", mutate)

    def move_reference(self, ref_id: str, offset: int) -> None:
        ids = [r["id"] for r in self.references()]
        index = ids.index(ref_id)
        target = max(0, min(len(ids) - 1, index + offset))
        if target == index:
            return
        ids.insert(target, ids.pop(index))

        def mutate(doc: dict) -> None:
            for ref in doc["references"]:
                ref["order"] = ids.index(ref["id"])

        self._push("Ordre des références", mutate)

    def add_annotation(self, ref_id: str, kind: str, rect: list[float], text: str = "") -> str:
        if kind not in refs_mod.ANNOTATION_KINDS:
            raise AIError("Type d'annotation inconnu.")
        note = {"id": uuid.uuid4().hex[:10], "kind": kind, "rect": [float(v) for v in rect], "text": text}
        self.update_reference(
            ref_id, annotations=list(self.reference(ref_id).get("annotations", [])) + [note]
        )
        return note["id"]

    def remove_annotation(self, ref_id: str, note_id: str) -> None:
        annotations = [n for n in self.reference(ref_id).get("annotations", []) if n.get("id") != note_id]
        self.update_reference(ref_id, annotations=annotations)

    def reference_bytes(self, ref: dict) -> bytes:
        data = self.scene.blobs.get(ref["blob"])
        if data is None:
            raise AIError(f"Image de « {ref.get('name')} » absente du projet.")
        return data

    @staticmethod
    def _ref_key(ref: dict, max_side: int | None) -> tuple:
        params = {k: ref.get(k) for k in ("rotation", "flip", "crop", "adjust")}
        return ref["blob"], json.dumps(params, sort_keys=True), max_side

    def prepared(self, ref: dict | str, max_side: int | None = 1024) -> Image.Image:
        ref = self.reference(ref) if isinstance(ref, str) else ref
        key = self._ref_key(ref, max_side)
        image = self._prepared.get(key)
        if image is None:
            if len(self._prepared) > 48:
                self._prepared.clear()
            image = refs_mod.prepare(ref, self.reference_bytes(ref), max_side)
            self._prepared[key] = image
        return image

    def segmentation(self, ref: dict | str) -> refs_mod.Segmentation:
        ref = self.reference(ref) if isinstance(ref, str) else ref
        key = self._ref_key(ref, 1024)
        seg = self._segments.get(key)
        if seg is None:
            if len(self._segments) > 48:
                self._segments.clear()
            seg = refs_mod.segment(self.prepared(ref, 1024))
            self._segments[key] = seg
        return seg

    def coverage(self) -> refs_mod.CoverageReport:
        return refs_mod.coverage(self.references())

    # --- Analyse ------------------------------------------------------------------------------
    def analysis_job(self, known_length: float | None = None):  # type: ignore[no-untyped-def]
        refs = self.references()
        if not refs:
            raise AIError("Importez au moins une image de référence.")
        images = {r["id"]: self.prepared(r, 1024) for r in refs}

        def job(ctx: JobContext) -> dict:
            ctx.progress(0.1, "Détourage et mesures")
            report = vision.build_report(refs, images, known_length)
            ctx.progress(1.0, "Analyse terminée")
            return report

        return job

    def analyze(self, known_length: float | None = None) -> dict:
        report = self.analysis_job(known_length)(JobContext())
        self.set_analysis(report)
        return report

    def set_analysis(self, report: dict, label: str = "Analyse du véhicule") -> None:
        previous = self.document().get("analysis")
        if previous and previous.get("cloud") and not report.get("cloud"):
            report = {**report, "cloud": previous["cloud"]}
        self._push(label, lambda doc: doc.__setitem__("analysis", report))

    def set_analysis_field(self, key: str, value) -> None:  # type: ignore[no-untyped-def]
        report = self.document().get("analysis")
        if not report:
            raise AIError("Lancez d'abord l'analyse.")
        vision.set_value(report, key, value)
        self._push("Rapport corrigé", lambda doc: doc.__setitem__("analysis", report))

    def merge_cloud_analysis(self, output: EngineOutput, engine_name: str) -> None:
        report = self.document().get("analysis") or {"version": 1, "fields": {}, "warnings": [], "colors": []}
        report["cloud"] = {
            "engine": engine_name,
            "model": output.data.get("model"),
            "at": refs_mod.now_iso(),
            "cost": output.reported_cost,
            "result": output.data.get("result", {}),
        }
        self._push("Analyse cloud", lambda doc: doc.__setitem__("analysis", report))

    def vehicle_hints(self) -> dict:
        doc = self.document()
        report = doc.get("analysis")
        length = doc["settings"].get("length_m") or vision.value(report, "length_m")
        hints: dict = {"length_m": float(length) if length else None, "type": vision.value(report, "type")}
        width = vision.value(report, "width_m")
        if width and not any(r.get("view") in ("front", "back") for r in doc["references"]):
            hints["width_m"] = float(width)
        return hints

    # --- Lore Friendly ------------------------------------------------------------------------
    def lore_seed(self) -> str:
        return self.session.project.project_id + "".join(r["blob"] for r in self.references())

    def generate_proposals(self) -> list[dict]:
        proposals = lore.proposals(self.document().get("analysis"), self.lore_seed())
        self._push("Propositions Lore Friendly", lambda doc: doc["lore"].__setitem__("proposals", proposals))
        return proposals

    def merge_cloud_proposals(self, output: EngineOutput) -> list[dict]:
        doc = self.document()
        local = [p for p in doc["lore"].get("proposals", []) if p.get("source") != "cloud"]
        local = local or lore.proposals(doc.get("analysis"), self.lore_seed())
        merged = lore.merge_cloud(local, output.data.get("result", {}))
        self._push("Propositions Lore Friendly (cloud)", lambda d: d["lore"].__setitem__("proposals", merged))
        return merged

    def select_proposal(self, index: int | None, overrides: dict | None = None) -> None:
        proposals = self.document()["lore"].get("proposals", [])
        if index is not None and not 0 <= index < len(proposals):
            raise AIError("Proposition introuvable.")
        selected = None if index is None else {**proposals[index], **(overrides or {})}
        if selected and (
            lore.is_forbidden(selected.get("brand", "")) or lore.is_forbidden(selected.get("model_name", ""))
        ):
            raise AIError(
                "Ce nom correspond à une marque réelle ou de l'univers GTA : choisissez un nom original."
            )
        self._push("Choix Lore Friendly", lambda doc: doc["lore"].__setitem__("selected", selected))

    def apply_adjustment(self, node_id: str, kind: str, amount: float) -> list[str]:
        from lsfcars.editor.operations import VehicleEditor
        from lsfcars.editor.vehicle import VehicleAxes

        axes = VehicleAxes.from_project(self.session.project.editor)
        order = (axes.lateral_axis, axes.up_axis, axes.longitudinal_axis)
        try:
            result = VehicleEditor(self.session).edit(
                node_id,
                lambda mesh: lore.deform(mesh, kind, amount, order, axes.forward_sign),
                f"Lore Friendly : {lore.ADJUSTMENT_LABELS.get(kind, kind)}",
            )
        except EditError as exc:
            raise AIError(str(exc)) from exc
        return result.warnings

    def provenance(self) -> dict:
        doc = self.document()
        return lore.provenance(doc["references"], doc["generations"], doc["lore"].get("selected"))

    # --- Génération ---------------------------------------------------------------------------
    def reference_inputs(self, folder: Path) -> list[ReferenceInput]:
        """Écrit les références préparées (logos annotés masqués) et leur détourage."""
        inputs = []
        folder.mkdir(parents=True, exist_ok=True)
        for index, ref in enumerate(self.references()):
            if ref.get("view") in ("interior", "detail"):
                continue
            image = self.prepared(ref, 2048).convert("RGB")
            logos = [n for n in ref.get("annotations", []) if n.get("kind") == "logo"]
            if logos:  # logos réels marqués : masqués avant tout traitement ou envoi
                rgb, _count = tex.mask_annotations(np.asarray(image), logos)
                image = Image.fromarray(rgb)
            path = folder / f"ref_{index:02d}_{ref['view']}.png"
            image.save(path)
            seg = refs_mod.segment(image)
            mask_path = None
            if seg.ok:
                mask_path = folder / f"ref_{index:02d}_{ref['view']}_mask.png"
                Image.fromarray(seg.mask.astype(np.uint8) * 255).save(mask_path)
            inputs.append(ReferenceInput(path, ref["view"], mask_path))
        return inputs

    def generation_job(
        self,
        engine_id: str,
        profile: str = "balanced",
        params: dict | None = None,
        prompt: str = "",
        allow_cloud: bool = False,
        allow_paid: bool = False,
        use_cache: bool = True,
    ):  # type: ignore[no-untyped-def]
        """Prépare une génération (fil principal) ; la fonction retournée s'exécute en arrière-plan."""
        adapter = self.manager.adapters.get(engine_id)
        if adapter is None:
            raise EngineUnavailable(f"Moteur inconnu : {engine_id}")
        refs = self.references()
        if not refs:
            raise AIError("Importez au moins une image de référence.")
        ortho = {r["view"] for r in refs} & {"left", "right", "front", "back", "top"}
        multi = len(ortho) >= 2 and adapter.info.supports(Capability.MULTIVIEW_3D)
        capability = Capability.MULTIVIEW_3D if multi else Capability.IMAGE_TO_3D
        adapter.require(capability)
        if adapter.info.kind == "cloud" and not allow_cloud:
            raise AIError("Transfert cloud non confirmé : aucune image n'a été envoyée.")
        hints = self.vehicle_hints()
        params = dict(params or {})
        params["front_left"] = {
            r["view"]: refs_mod.front_on_left(r) for r in refs if r["view"] in ("left", "right")
        }
        folder = self.manager.job_dir()
        inputs = self.reference_inputs(folder / "inputs")
        request = GenerationRequest(
            capability,
            inputs,
            folder / "output",
            profile,
            params,
            prompt,
            {**hints, "_hardware": self.manager.hardware},
            allow_cloud,
            allow_paid,
        )
        estimate = adapter.estimate(request).describe()
        retouches = ("rotation", "flip", "crop", "adjust", "annotations", "view")
        fingerprint = [r["blob"] + json.dumps({k: r.get(k) for k in retouches}, sort_keys=True) for r in refs]
        cache_key = self.manager.cache_key(
            engine_id, adapter.info.version, profile, params, fingerprint + [str(hints.get("length_m"))]
        )
        blobs = [r["blob"] for r in refs]
        public_params = {k: v for k, v in params.items() if k != "front_left"}

        def job(ctx: JobContext) -> GenerationOutcome:
            start = time.monotonic()
            cached = (
                self.manager.cache_lookup(cache_key) if use_cache and adapter.info.kind == "local" else None
            )
            if cached:
                ctx.progress(0.5, "Résultat identique retrouvé dans le cache")
                stored = cached.get("data", {})
                output = EngineOutput(
                    cached["files"],
                    "glb",
                    data=stored.get("data", {}),
                    warnings=stored.get("warnings", []),
                    used_views=stored.get("used_views", []),
                )
            else:
                output = adapter.run(request, ctx)
            model = output.files.get("model")
            if model is None or not Path(model).is_file():
                raise InvalidOutput("Le moteur n'a produit aucun fichier de modèle.")
            ctx.progress(0.97, "Validation du fichier produit")
            from lsfcars.importers import load_model

            try:
                result = load_model(model)
            except ModelLoadError as exc:
                raise InvalidOutput(f"Fichier produit invalide : {exc}") from exc
            if result.triangle_count == 0:
                raise InvalidOutput("Le modèle produit ne contient aucun triangle.")
            if any(not np.isfinite(mesh.positions).all() for mesh in result.meshes.values()):
                raise InvalidOutput("Le modèle produit contient des coordonnées invalides.")
            if not cached and adapter.info.kind == "local":
                payload = {"data": output.data, "warnings": output.warnings, "used_views": output.used_views}
                self.manager.cache_store(cache_key, output.files, payload)
            thumbnail = render_thumbnail(result, engine_id)
            return GenerationOutcome(
                engine_id,
                profile,
                public_params,
                prompt,
                blobs,
                output,
                result,
                thumbnail,
                round(time.monotonic() - start, 2),
                estimate,
                bool(cached),
            )

        return job

    def apply_generation(self, outcome: GenerationOutcome) -> str:
        """Importe le modèle généré (fichier du projet), le recale et l'historise. Annulable."""
        adapter = self.manager.adapters[outcome.engine_id]
        record_id = uuid.uuid4().hex[:12]
        files = self._store_files(record_id, outcome.output.files)
        stack = self.session.stack
        stack.begin(f"Génération {adapter.info.name}")
        try:
            root_id = self.session.apply_import(outcome.import_result)
            asset_id = self.scene.nodes[root_id].asset_id
            asset = self.session.project.assets.get(asset_id)
            if asset is not None:
                asset.importer = f"AI Vehicle Creator — {adapter.info.name}"
                asset.notes = [
                    f"Généré par {adapter.info.name} ({adapter.info.method_label}), {refs_mod.now_iso()}.",
                    "Modèle généré : ce n'est pas un véhicule GTA V / FiveM fonctionnel.",
                ]
            transform = self.normalized_transform(root_id, outcome.engine_id)
            if transform is not None:
                self.session.set_transforms({root_id: transform}, "Recalage du modèle généré")
            thumb_key = "thumb-" + hashlib.sha256(outcome.thumbnail).hexdigest()[:32]
            record = {
                "id": record_id,
                "created_at": refs_mod.now_iso(),
                "engine": outcome.engine_id,
                "engine_name": adapter.info.name,
                "engine_version": adapter.info.version,
                "engine_license": adapter.info.license,
                "method": adapter.info.method,
                "kind": adapter.info.kind,
                "profile": outcome.profile,
                "params": _jsonable(outcome.params),
                "prompt": outcome.prompt,
                "references": outcome.references,
                "views_used": outcome.output.used_views,
                "status": "succeeded",
                "error": "",
                "duration_s": outcome.duration_s,
                "estimated_cost": outcome.estimated_cost,
                "reported_cost": outcome.output.reported_cost,
                "cached": outcome.cached,
                "files": files,
                "asset_id": asset_id,
                "root_id": root_id,
                "thumbnail": thumb_key,
                "warnings": list(outcome.output.warnings),
                "report": _jsonable(outcome.output.data),
                "triangles": int(outcome.import_result.triangle_count),
            }
            self._push(
                "Historique des générations",
                lambda doc: doc["generations"].append(record),
                [AddBlob(thumb_key, outcome.thumbnail)],
            )
        except Exception:
            stack.rollback()
            raise
        stack.commit()
        self.session.selection.set([root_id])
        return record_id

    def record_failure(
        self,
        engine_id: str,
        profile: str,
        status: str,
        error: str,
        duration: float | None,
        prompt: str = "",
        estimated_cost: str = "",
    ) -> str:
        adapter = self.manager.adapters.get(engine_id)
        record = {
            "id": uuid.uuid4().hex[:12],
            "created_at": refs_mod.now_iso(),
            "engine": engine_id,
            "engine_name": adapter.info.name if adapter else engine_id,
            "engine_version": adapter.info.version if adapter else "",
            "engine_license": adapter.info.license if adapter else "",
            "method": adapter.info.method if adapter else "",
            "kind": adapter.info.kind if adapter else "",
            "profile": profile,
            "params": {},
            "prompt": prompt,
            "references": [r["blob"] for r in self.references()],
            "views_used": [],
            "status": status,
            "error": error,
            "duration_s": round(duration, 2) if duration else None,
            "estimated_cost": estimated_cost,
            "reported_cost": "",
            "files": {},
            "asset_id": None,
            "root_id": None,
            "thumbnail": None,
            "warnings": [],
            "report": {},
        }
        self._push("Historique des générations", lambda doc: doc["generations"].append(record))
        return record["id"]

    def _store_files(self, record_id: str, files: dict[str, Path]) -> dict[str, str]:
        """Copie les fichiers annexes (hors modèle) dans ``assets/ai/<id>/`` ; chemins relatifs."""
        project_dir = self.session.project.project_dir
        folder = project_dir / "assets" / "ai" / record_id
        stored = {}
        for role, source in files.items():
            if role == "model" or not Path(source).is_file():
                continue
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / f"{role}{Path(source).suffix.lower()}"
            shutil.copy2(source, target)
            stored[role] = target.relative_to(project_dir).as_posix()
        return stored

    def normalized_transform(self, root_id: str, engine_id: str) -> Transform | None:
        """Orientation (Y vertical, longueur selon Z), pose au sol, centrage et échelle estimée."""
        root_world = self.scene.world_matrix(root_id)
        inverse = np.linalg.inv(root_world)
        points = []
        for node in self.scene.subtree(root_id):
            mesh = self.session.geometry_for(node)
            if mesh is not None and mesh.vertex_count:
                relative = inverse @ self.scene.world_matrix(node.id)
                points.append(mathutils.transform_points(relative, mesh.positions.astype(np.float64)))
        if not points:
            return None
        cloud = np.vstack(points)
        euler = ENGINE_ORIENTATION.get(engine_id, (0.0, 0.0, 0.0))
        rotation = mathutils.trs([0, 0, 0], list(euler), [1, 1, 1])[:3, :3]
        if engine_id not in METRIC_ENGINES and len(cloud) >= 16:
            rotation = principal_alignment(cloud @ rotation.T) @ rotation
        rotated = cloud @ rotation.T
        extent = rotated.max(axis=0) - rotated.min(axis=0)
        scale = 1.0
        length = self.vehicle_hints().get("length_m")
        if engine_id not in METRIC_ENGINES and length and extent[2] > 1e-6:
            scale = float(length) / float(extent[2])
        lo, hi = rotated.min(axis=0), rotated.max(axis=0)
        center = (lo + hi) / 2
        offset = np.array([-center[0], -lo[1], -center[2]]) * scale
        if np.allclose(rotation, np.eye(3)) and abs(scale - 1.0) < 1e-9 and np.abs(offset).max() < 1e-4:
            return None
        current = self.scene.nodes[root_id].transform
        return Transform(
            [float(current.translation[i] + offset[i]) for i in range(3)],
            [round(a, 6) for a in euler_xyz_from_rotation(rotation)],
            [scale, scale, scale],
        )

    def turn_model(self, root_id: str, degrees: float = 180.0) -> None:
        """Tourne un modèle autour de l'axe vertical passant par son centre (sens avant / arrière)."""
        if root_id not in self.scene:
            raise AIError("Modèle introuvable.")
        bounds = self.session.world_bounds([root_id], only_visible=False)
        node = self.scene.nodes[root_id]
        center = np.zeros(3) if bounds is None else (bounds[0] + bounds[1]) / 2
        turn = mathutils.trs([0, 0, 0], [0.0, float(degrees), 0.0], [1, 1, 1])
        to_center = mathutils.trs(list(-center), [0, 0, 0], [1, 1, 1])
        back = mathutils.trs(list(center), [0, 0, 0], [1, 1, 1])
        world = back @ turn @ to_center @ self.scene.world_matrix(root_id)
        local = np.linalg.inv(self.scene.parent_world_matrix(root_id)) @ world
        transform = Transform.from_matrix(local)
        transform.scale = list(node.transform.scale)  # échelle uniforme conservée exactement
        self.session.set_transforms({root_id: transform}, f"Rotation de {degrees:g}°")

    def fit_to_analysis(self, root_id: str) -> list[str]:
        """Recale largeur, hauteur et longueur sur les mesures de l'analyse (échelle non uniforme).

        L'échelle s'applique dans le repère du véhicule (X latéral, Y vertical, Z longueur) : la
        géométrie des maillages est réécrite (une étape d'historique, annulable).
        """
        from lsfcars.editor.operations import VehicleEditor
        from lsfcars.scene.mesh import MeshData, compute_vertex_normals

        report = self.document().get("analysis")
        targets = {
            0: vision.value(report, "width_m"),
            1: vision.value(report, "height_m"),
            2: self.document()["settings"].get("length_m") or vision.value(report, "length_m"),
        }
        if not targets[0] or not targets[1]:
            raise AIError("L'analyse ne fournit ni largeur ni hauteur : lancez l'analyse avec un profil.")
        nodes = [n for n in self.scene.subtree(root_id) if self.session.geometry_for(n) is not None]
        if not nodes:
            raise AIError("Aucun maillage sous ce modèle.")
        world_points = []
        for node in nodes:
            matrix = self.scene.world_matrix(node.id)
            world_points.append(
                mathutils.transform_points(
                    matrix, self.session.geometry_for(node).positions.astype(np.float64)
                )
            )
        cloud = np.vstack(world_points)
        lo, hi = cloud.min(axis=0), cloud.max(axis=0)
        extent = np.maximum(hi - lo, 1e-6)
        factors = np.array([float(targets[i]) / extent[i] if targets[i] else 1.0 for i in range(3)])
        anchor = np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
        scale = np.eye(4)
        scale[:3, :3] = np.diag(factors)
        scale[:3, 3] = anchor - factors * anchor
        editor = VehicleEditor(self.session)
        stack = self.session.stack
        stack.begin("Recalage sur les proportions mesurées")
        try:
            for node in nodes:
                mesh = self.session.geometry_for(node)
                matrix = self.scene.world_matrix(node.id)
                local = np.linalg.inv(matrix) @ scale @ matrix
                positions = mathutils.transform_points(local, mesh.positions.astype(np.float64))
                new = MeshData(
                    mesh.name,
                    positions.astype(np.float32),
                    mesh.indices,
                    compute_vertex_normals(positions, mesh.indices),
                    mesh.colors,
                    mesh.color,
                    mesh.uvs,
                )
                stack.push(editor.geometry_command(node.id, new, "Recalage sur les proportions mesurées"))
        except Exception:
            stack.rollback()
            raise
        stack.commit()
        labels = ("largeur", "hauteur", "longueur")
        return [f"{labels[i]} × {factors[i]:.2f}" for i in range(3) if abs(factors[i] - 1) > 1e-3]

    def records(self) -> list[dict]:
        return list(self.document()["generations"])

    def record(self, record_id: str) -> dict:
        record = next((g for g in self.document()["generations"] if g["id"] == record_id), None)
        if record is None:
            raise AIError("Génération introuvable dans l'historique.")
        return record

    def reopen(self, record_id: str) -> str:
        """Sélectionne le résultat dans la scène, ou le réimporte depuis le fichier du projet."""
        record = self.record(record_id)
        if record.get("root_id") in self.scene:
            self.session.selection.set([record["root_id"]])
            return record["root_id"]
        asset = self.session.project.assets.get(record.get("asset_id") or "")
        if asset is None:
            raise AIError("Le fichier de ce résultat n'est plus dans le projet.")
        from lsfcars.importers import load_model

        try:
            result = load_model(self.session.project.project_dir / asset.rel_path)
        except ModelLoadError as exc:
            raise AIError(f"Réouverture impossible : {exc}") from exc
        stack = self.session.stack
        stack.begin("Réouverture d'une génération")
        try:
            root_id = self.session.apply_import(result)
            transform = self.normalized_transform(root_id, record["engine"])
            if transform is not None:
                self.session.set_transforms({root_id: transform}, "Recalage du modèle généré")
            asset_id = self.scene.nodes[root_id].asset_id
            self._push(
                "Historique des générations",
                lambda doc: _update_record(doc, record_id, root_id=root_id, asset_id=asset_id),
            )
        except Exception:
            stack.rollback()
            raise
        stack.commit()
        self.session.selection.set([root_id])
        return root_id

    def duplicate(self, record_id: str) -> str:
        record = self.record(record_id)
        root_id = record.get("root_id")
        if root_id not in self.scene:
            root_id = self.reopen(record_id)
        return self.session.duplicate([root_id])[0]

    def delete_record(self, record_id: str, remove_model: bool = False) -> None:
        record = self.record(record_id)
        stack = self.session.stack
        stack.begin("Suppression d'une génération")
        if remove_model and record.get("root_id") in self.scene:
            self.session.delete([record["root_id"]])

        def mutate(doc: dict) -> None:
            doc["generations"] = [g for g in doc["generations"] if g["id"] != record_id]

        self._push("Historique des générations", mutate)
        stack.commit()

    def reuse_parameters(self, record_id: str) -> dict:
        record = self.record(record_id)
        settings = {
            "engine": record["engine"],
            "profile": record.get("profile", "balanced"),
            "prompt": record.get("prompt", ""),
        }
        self.set_settings(**settings)
        return settings

    def compare(self, first: str, second: str) -> list[tuple[str, str, str]]:
        a, b = self.record(first), self.record(second)

        def dims(record: dict) -> str:
            size = (record.get("report") or {}).get("dimensions_m")
            if not size:
                return "—"
            return " × ".join(f"{size[k]:.2f}" for k in ("length", "width", "height")) + " m"

        return [
            ("Moteur", a["engine_name"], b["engine_name"]),
            ("Méthode", _method(a), _method(b)),
            ("Profil", a.get("profile", "—"), b.get("profile", "—")),
            ("Date", a.get("created_at", "—"), b.get("created_at", "—")),
            ("Statut", a.get("status", "—"), b.get("status", "—")),
            ("Durée", _seconds(a.get("duration_s")), _seconds(b.get("duration_s"))),
            ("Triangles", str(a.get("triangles", "—")), str(b.get("triangles", "—"))),
            (
                "Vues exploitées",
                ", ".join(a.get("views_used", [])) or "—",
                ", ".join(b.get("views_used", [])) or "—",
            ),
            ("Dimensions", dims(a), dims(b)),
            (
                "Coût communiqué",
                a.get("reported_cost") or "non communiqué",
                b.get("reported_cost") or "non communiqué",
            ),
        ]

    def thumbnail(self, record: dict) -> bytes | None:
        key = record.get("thumbnail")
        return self.scene.blobs.get(key) if key else None

    # --- Assistant maillage -------------------------------------------------------------------
    def mesh_nodes(self, node_ids: list[str] | None = None) -> list:
        ids = node_ids if node_ids is not None else self.session.selection.ids
        found: dict = {}
        for node_id in ids:
            if node_id in self.scene:
                for node in self.scene.subtree(node_id):
                    if node.kind is NodeKind.MESH and self.session.geometry_for(node) is not None:
                        found[node.id] = node
        return list(found.values())

    def analyze_mesh(self, node_id: str) -> dict:
        node = self.scene.nodes.get(node_id)
        mesh = self.session.geometry_for(node) if node else None
        if mesh is None:
            raise AIError("Sélectionnez un maillage.")
        report = mesh_assist.analyze(mesh)
        report["node"] = node.name
        return report

    def apply_fix(self, node_id: str, key: str, **options) -> list[str]:  # type: ignore[no-untyped-def]
        from lsfcars.editor.operations import VehicleEditor

        label = f"Assistant maillage : {mesh_assist.FIXES.get(key, key)}"
        try:
            result = VehicleEditor(self.session).edit(node_id, mesh_assist.operation(key, **options), label)
        except EditError as exc:
            raise AIError(str(exc)) from exc
        return result.warnings

    # --- Textures -----------------------------------------------------------------------------
    def projection_views(self) -> list[tex.ViewImage]:
        views: list[tex.ViewImage] = []
        for ref in self.references():
            if ref.get("view") not in tex.VIEW_DIRECTIONS or any(v.view == ref["view"] for v in views):
                continue
            seg = self.segmentation(ref)
            if not seg.ok:
                continue
            image = np.asarray(self.prepared(ref, 1024).convert("RGB"))
            logos = [n for n in ref.get("annotations", []) if n.get("kind") == "logo"]
            image, _masked = tex.mask_annotations(image, logos)
            x0, y0, x1, y1 = seg.bbox
            views.append(
                tex.ViewImage(
                    ref["view"], image[y0:y1, x0:x1], seg.mask[y0:y1, x0:x1], refs_mod.front_on_left(ref)
                )
            )
        return views

    def texture_job(
        self, node_id: str, method: str = "projection", size: int = 1024, preset: str = "paint_gloss"
    ):  # type: ignore[no-untyped-def]
        node = self.scene.nodes.get(node_id)
        mesh = self.session.geometry_for(node) if node else None
        if mesh is None:
            raise AIError("Sélectionnez un maillage.")
        views = self.projection_views() if method == "projection" else []
        if method == "projection" and not views:
            raise AIError(
                "Aucune référence orthographique détourée (profil, avant, arrière, dessus) à projeter."
            )
        world = self.scene.world_matrix(node_id)

        def job(ctx: JobContext) -> TextureOutcome:
            work = mesh
            new_mesh = None
            if work.uvs is None or float(work.uvs.min()) < -1e-3 or float(work.uvs.max()) > 1.001:
                ctx.progress(0.05, "Création des UV (atlas)")
                work = tex.atlas_uv(work).mesh
                new_mesh = work
            ctx.progress(0.15, "Rastérisation dans l'espace UV")
            maps = tex.surface_maps(work, size)
            stats: dict = {}
            if method == "projection":
                world_positions = maps.positions.reshape(-1, 3) @ world[:3, :3].T + world[:3, 3]
                world_maps = tex.SurfaceMaps(
                    size,
                    world_positions.reshape(maps.positions.shape).astype(np.float32),
                    _rotate_normals(maps.normals, world),
                    maps.colors,
                    maps.coverage,
                )
                ctx.progress(0.4, "Projection des références")
                base, stats = tex.project_references(_world_mesh(work, world), world_maps, views)
                base_source = "projection"
            else:
                base = tex.bake_vertex_colors(maps)
                base_source = "vertex"
            ctx.progress(0.8, "Cartes dérivées")
            rough, metal = tex.rule_maps(base, preset)
            result_maps = {
                "base_color": base,
                "normal": tex.normal_from_height(base),
                "roughness": rough,
                "metallic": metal,
            }
            sources = {
                "base_color": base_source,
                "normal": "derived",
                "roughness": "rules",
                "metallic": "rules",
                "ao": "none",
            }
            ctx.progress(1.0, "Textures prêtes")
            return TextureOutcome(
                node_id, method, result_maps, sources, new_mesh, {**stats, "size": size, "preset": preset}
            )

        return job

    def apply_textures(self, outcome: TextureOutcome, label: str = "Textures IA") -> str:
        """Écrit les cartes dans le projet, crée et affecte le matériau. Annulable."""
        from lsfcars.editor.operations import VehicleEditor
        from lsfcars.project import store

        node = self.scene.nodes.get(outcome.node_id)
        if node is None:
            raise AIError("Le maillage n'existe plus.")
        project = self.session.project
        paths = {}
        for role, array in outcome.maps.items():
            buffer = io.BytesIO()
            Image.fromarray(array).save(buffer, "PNG", optimize=True)
            paths[role] = store.store_texture(project, buffer.getvalue(), f"ia_{node.name}_{role}")
        preset = tex.PRESETS.get(outcome.stats.get("preset", "paint_gloss"), tex.PRESETS["paint_gloss"])
        material = Material(
            f"IA — {node.name}", (1.0, 1.0, 1.0, 1.0), preset["roughness"], preset["metallic"]
        )
        material.texture = paths["base_color"]
        material.normal_texture = paths.get("normal")
        material.normal_strength = 0.5
        entry = {
            "id": uuid.uuid4().hex[:10],
            "created_at": refs_mod.now_iso(),
            "node": outcome.node_id,
            "material": material.id,
            "method": outcome.method,
            "files": paths,
            "sources": {role: tex.MAP_SOURCES[src] for role, src in outcome.sources.items()},
            "stats": _jsonable(outcome.stats),
        }
        stack = self.session.stack
        stack.begin(label)
        try:
            if outcome.mesh is not None:
                stack.push(
                    VehicleEditor(self.session).geometry_command(outcome.node_id, outcome.mesh, "UV d'atlas")
                )
            stack.push(AddMaterial(material))
            stack.push(AssignMaterial([outcome.node_id], material.id))
            self._push(label, lambda doc: doc["textures"].append(entry))
        except Exception:
            stack.rollback()
            raise
        stack.commit()
        return material.id

    def texture_variant(self, material_id: str, hue_shift: float) -> str:
        """Nouvelle texture (teinte de carrosserie décalée) sur une copie du matériau. Annulable."""
        from lsfcars.project import store

        material = self.scene.materials.get(material_id)
        if material is None or not material.texture:
            raise AIError("Matériau sans texture.")
        try:
            base = np.asarray(Image.open(self.session.project.project_dir / material.texture).convert("RGBA"))
        except OSError as exc:
            raise AIError(f"Texture illisible : {exc}") from exc
        buffer = io.BytesIO()
        Image.fromarray(tex.variation(base, hue_shift)).save(buffer, "PNG", optimize=True)
        rel = store.store_texture(
            self.session.project, buffer.getvalue(), f"{Path(material.texture).stem}_variante"
        )
        variant = material.copy()
        variant.name = f"{material.name} (variante)"
        variant.texture = rel
        users = [n.id for n in self.scene.material_users(material_id)]
        stack = self.session.stack
        stack.begin("Variante de texture")
        stack.push(AddMaterial(variant))
        if users:
            stack.push(AssignMaterial(users, variant.id))
        stack.commit()
        return variant.id


def _update_record(doc: dict, record_id: str, **changes) -> None:  # type: ignore[no-untyped-def]
    for record in doc["generations"]:
        if record["id"] == record_id:
            record.update(changes)


def _method(record: dict) -> str:
    return "IA (réseau de neurones)" if record.get("method") == "neural" else "Algorithme déterministe"


def _seconds(value) -> str:  # type: ignore[no-untyped-def]
    return "—" if value is None else f"{float(value):.1f} s"


def _jsonable(data):  # type: ignore[no-untyped-def]
    return json.loads(json.dumps(data, default=str))


def _rotate_normals(normals: np.ndarray, world: np.ndarray) -> np.ndarray:
    rotated = normals.reshape(-1, 3) @ np.linalg.inv(world[:3, :3])
    lengths = np.linalg.norm(rotated, axis=1, keepdims=True)
    rotated = np.divide(rotated, lengths, out=np.zeros_like(rotated), where=lengths > 1e-9)
    return rotated.reshape(normals.shape).astype(np.float32)


def _world_mesh(mesh, world: np.ndarray):  # type: ignore[no-untyped-def]
    from lsfcars.scene.mesh import MeshData

    positions = mesh.positions.astype(np.float64) @ world[:3, :3].T + world[:3, 3]
    return MeshData(
        mesh.name, positions.astype(np.float32), mesh.indices, None, mesh.colors, mesh.color, mesh.uvs
    )


def render_thumbnail(result: ImportResult, engine_id: str = "", size: int = 192) -> bytes:
    """Miniature trois quarts (rendu logiciel) d'un résultat d'import, orienté comme dans la scène."""
    by_key = {n.key: n for n in result.nodes}

    def matrix(node) -> np.ndarray:  # type: ignore[no-untyped-def]
        m = node.transform.matrix()
        parent = by_key.get(node.parent_key)
        while parent is not None:
            m = parent.transform.matrix() @ m
            parent = by_key.get(parent.parent_key)
        return m

    pairs = [(result.meshes[n.mesh_key], matrix(n)) for n in result.nodes if n.mesh_key in result.meshes]
    meshes = raster3d.from_mesh_data(pairs)
    euler = ENGINE_ORIENTATION.get(engine_id, (0.0, 0.0, 0.0))
    rotation = mathutils.trs([0, 0, 0], list(euler), [1, 1, 1])[:3, :3]
    if engine_id not in METRIC_ENGINES and meshes:
        cloud = np.vstack([m.positions for m in meshes]) @ rotation.T
        if len(cloud) >= 16:
            rotation = principal_alignment(cloud) @ rotation
    for item in meshes:
        item.positions = item.positions @ rotation.T
    image = raster3d.render(meshes, "three_quarter", size)
    buffer = io.BytesIO()
    image.save(buffer, "PNG", optimize=True)
    return buffer.getvalue()
