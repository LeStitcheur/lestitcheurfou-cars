"""Lore Friendly Engine : orchestration des designs, variantes et transformations (sans Qt).

Principes :

- **le véhicule source n'est jamais modifié** : il est verrouillé à la création du design ; les
  transformations portent sur des **variantes** (copies du sous-arbre rangées dans un ensemble
  de variantes ``lore``), dont la géométrie importée reste partagée tant qu'elle n'est pas modifiée ;
- toute modification passe par l'historique (``CompositeCommand`` : commandes de scène +
  ``SetDocument``) : annuler / rétablir, points de restauration, variantes non destructives ;
- les équipements Emergency Studio et les matériaux de livrée de la source sont copiés avec la
  variante (jamais supprimés) ; une pièce remplacée est masquée, pas supprimée.

Document ``lore`` (format 1) : marques et profils DNA du projet, designs (source, marque,
direction, analyse, propositions, variantes, comparaisons, revues, historique).
"""

from __future__ import annotations

import copy
import uuid
from pathlib import Path

import numpy as np

from lsfcars.ai.engines.base import Capability, GenerationRequest, ReferenceInput
from lsfcars.editor.operations import VehicleEditor, new_mesh_key
from lsfcars.lorefriendly import analyzer, components, concepts, originality, preview, provenance
from lsfcars.lorefriendly import compare as compare_mod
from lsfcars.lorefriendly import dna as dna_mod
from lsfcars.lorefriendly import operations as ops
from lsfcars.lorefriendly.brands import Brand, BrandLibrary
from lsfcars.lorefriendly.geometry import IncompatibleTransformation, VehicleState
from lsfcars.project.model import utc_now_iso
from lsfcars.scene.commands import (
    AddBlob,
    AddMaterial,
    AssignMaterial,
    Command,
    CompositeCommand,
    InsertNodes,
    SetDocument,
    SetNodeField,
    SetTransforms,
)
from lsfcars.scene.editmesh import EditError
from lsfcars.scene.graph import NodeKind, SceneNode, new_node_id
from lsfcars.scene.materials import Material
from lsfcars.scene.transform import Transform

DOC_KEY = "lore"
FORMAT = 1
HISTORY_LIMIT = 200
COMPARISON_LIMIT = 12
SOURCE = "source"
SOURCE_KINDS = {
    "import": "Modèle 3D importé",
    "fivem": "Véhicule FiveM importé",
    "ai": "Modèle généré par IA",
    "project": "Élément du projet",
}
WORKFLOW = (
    ("analyzed", "Analyser"),
    ("proposed", "Proposer"),
    ("previewed", "Prévisualiser"),
    ("compared", "Comparer"),
    ("checked", "Vérifier les contraintes"),
    ("confirmed", "Confirmer"),
    ("applied", "Appliquer"),
    ("saved", "Sauvegarder"),
)
DESIGN_DEFAULTS = {
    "concepts": [],
    "variants": [],
    "comparisons": [],
    "originality": {},
    "checklist": {},
    "history": [],
    "workflow": {},
    "constraints": [],
    "display": "source",
    "set_id": None,
}


class LoreError(EditError):
    """Action Lore Friendly impossible (design introuvable, source absente…)."""


def empty_document() -> dict:
    return {"format": FORMAT, "brands": [], "dna_profiles": [], "designs": [], "active_design": None}


def migrate(doc: dict | None, ai_doc: dict | None = None) -> dict:
    """Document courant. Sans document : reprise du choix Lore Friendly de la v0.7 (AI Vehicle Creator)."""
    if isinstance(doc, dict):
        result = copy.deepcopy(doc)
        for key, default in empty_document().items():
            result.setdefault(key, copy.deepcopy(default))
        for design in result["designs"]:
            for key, default in DESIGN_DEFAULTS.items():
                design.setdefault(key, copy.deepcopy(default))
        result["format"] = FORMAT
        return result
    result = empty_document()
    selected = ((ai_doc or {}).get("lore") or {}).get("selected")
    if isinstance(selected, dict) and selected.get("brand"):
        name = str(selected["brand"])
        brand = Brand(
            f"custom-v07-{uuid.uuid5(uuid.NAMESPACE_OID, name).hex[:8]}",
            name,
            "Marque issue de l'assistant Lore Friendly (AI Vehicle Creator 0.7).",
            [],
            str(selected.get("direction", "")),
            [str(d) for d in selected.get("details", [])][:6],
            [],
            "Identité visuelle originale créée par l'utilisateur.",
            origin="custom",
            provenance="Nom généré par l'assistant Lore Friendly 0.7 et choisi par l'utilisateur.",
        )
        result["brands"].append(brand.to_dict())
        result["migrated_from"] = ["ai.lore (0.7)"]
    return result


class LoreFriendlyEngine:
    def __init__(self, session, manager=None, data_dir: Path | None = None) -> None:  # type: ignore[no-untyped-def]
        self.session = session
        self.manager = manager
        folder = (data_dir / "lore") if data_dir else None
        self.brands = BrandLibrary(folder / "brands.json" if folder else None)
        self.dnas = dna_mod.DnaLibrary(folder / "dna_profiles.json" if folder else None)
        self.sync_libraries()

    # --- Document -----------------------------------------------------------------------------
    @property
    def scene(self):  # type: ignore[no-untyped-def]
        return self.session.scene

    def document(self) -> dict:
        return migrate(self.scene.documents.get(DOC_KEY), self.scene.documents.get("ai"))

    def sync_libraries(self) -> None:
        doc = self.document()
        self.brands.project = [Brand.from_dict(b) for b in doc.get("brands", [])]
        self.dnas.project = [dna_mod.DnaProfile.from_dict(p) for p in doc.get("dna_profiles", [])]

    def _push(
        self,
        label: str,
        mutate,
        extra: list[Command] | None = None,
        history: str | None = None,  # type: ignore[no-untyped-def]
        design_id: str | None = None,
    ) -> dict:
        before = self.scene.documents.get(DOC_KEY)
        after = self.document()
        mutate(after)
        if history and design_id:
            design = _find(after, design_id)
            design["history"] = (design["history"] + [{"at": utc_now_iso(), "event": history}])[
                -HISTORY_LIMIT:
            ]
        steps = [*(extra or []), SetDocument(DOC_KEY, copy.deepcopy(before), after, label)]
        self.session.stack.push(CompositeCommand(steps, label))
        self.sync_libraries()
        return after

    def designs(self) -> list[dict]:
        return self.document()["designs"]

    def design(self, design_id: str | None = None) -> dict:
        doc = self.document()
        design_id = design_id or doc.get("active_design")
        if not design_id and doc["designs"]:
            design_id = doc["designs"][-1]["id"]
        if not design_id:
            raise LoreError("Aucun design Lore Friendly : choisissez d'abord un véhicule source.")
        return _find(doc, design_id)

    def has_design(self) -> bool:
        return bool(self.designs())

    # --- Sources --------------------------------------------------------------------------------
    def candidate_sources(self) -> list[tuple[str, str, str]]:
        """(nœud, nom, type) des véhicules utilisables comme source (racines contenant de la géométrie)."""
        ai = self.scene.documents.get("ai") or {}
        generated = {r.get("root_id") for r in ai.get("generations", [])}
        result = []
        for node in self.scene.roots():
            if node.extra.get("lore") or node.extra.get("variant_set", {}).get("kind") == "lore":
                continue
            subtree = self.scene.subtree(node.id)
            if not any(n.kind is NodeKind.MESH for n in subtree):
                continue
            if node.id in generated:
                kind = "ai"
            elif any(n.extra.get("gta") for n in subtree):
                kind = "fivem"
            elif node.kind is NodeKind.MODEL:
                kind = "import"
            else:
                kind = "project"
            result.append((node.id, node.name, kind))
        return result

    def create_design(self, source_id: str, name: str | None = None, brand: str | None = None) -> str:
        node = self.scene.get(source_id)
        if node is None:
            raise LoreError("Véhicule source introuvable.")
        kinds = {nid: kind for nid, _, kind in self.candidate_sources()}
        design_id = uuid.uuid4().hex[:12]
        profile = dna_mod.preset("sport_premium")
        design = {
            "id": design_id,
            "name": (name or f"Design · {node.name}").strip(),
            "created_at": utc_now_iso(),
            "source_id": source_id,
            "source_name": node.name,
            "source_kind": kinds.get(source_id, "project"),
            "brand": brand,
            "category": "sedan",
            "dna_profile": profile.key if profile else "",
            "dna": dict(profile.values) if profile else dna_mod.normalize({}),
            "level": "balanced",
            "analysis": None,
            **copy.deepcopy(DESIGN_DEFAULTS),
        }
        lock = []
        if not node.locked:  # la source est protégée (verrou d'édition, réversible par l'utilisateur)
            lock = [SetNodeField("locked", {source_id: (False, True)}, "Verrouiller la source")]

        def mutate(doc: dict) -> None:
            doc["designs"].append(design)
            doc["active_design"] = design_id

        self._push(
            "Nouveau design Lore Friendly", mutate, lock, "Design créé ; source verrouillée", design_id
        )
        return design_id

    def set_active(self, design_id: str) -> None:
        self._push("Design actif", lambda doc: doc.__setitem__("active_design", _find(doc, design_id)["id"]))

    def update_design(self, design_id: str, **fields) -> None:  # type: ignore[no-untyped-def]
        allowed = {"name", "brand", "category", "dna", "dna_profile", "level", "constraints"}
        unknown = set(fields) - allowed
        if unknown:
            raise LoreError(f"Champ non modifiable : {', '.join(sorted(unknown))}")
        if "dna" in fields:
            fields["dna"] = dna_mod.normalize(fields["dna"])
        if "constraints" in fields:
            fields["constraints"] = [c for c in fields["constraints"] if c in concepts.CONSTRAINTS]
        if "level" in fields and fields["level"] not in concepts.LEVELS:
            raise LoreError("Niveau de transformation inconnu.")

        def mutate(doc: dict) -> None:
            _find(doc, design_id).update(fields)

        detail = ", ".join(sorted(fields))
        self._push(
            "Paramètres du design", mutate, history=f"Paramètres modifiés : {detail}", design_id=design_id
        )

    def choose_brand(self, design_id: str, brand_key: str) -> Brand:
        brand = self.brands.get(brand_key)
        if brand is None:
            raise LoreError("Marque inconnue.")
        design = self.design(design_id)
        fields: dict = {"brand": brand.key}
        if brand.categories and design.get("category") not in brand.categories:
            fields["category"] = brand.categories[0]
        self.update_design(design_id, **fields)
        return brand

    def apply_dna_profile(self, design_id: str, key: str) -> None:
        profile = self.dnas.get(key)
        if profile is None:
            raise LoreError("Profil Design DNA inconnu.")
        self.update_design(design_id, dna=profile.values, dna_profile=profile.key)

    def create_brand(self, name: str, save_to_user: bool = False, **fields) -> Brand:  # type: ignore[no-untyped-def]
        brand = self.brands.create(name, save_to_user=save_to_user, **fields)
        self._push("Nouvelle marque fictive", lambda doc: doc["brands"].append(brand.to_dict()))
        return brand

    def save_dna_profile(
        self, name: str, values: dict, description: str = "", to_user: bool = False
    ) -> dna_mod.DnaProfile:
        profile = self.dnas.save(name, values, description, to_user)

        def mutate(doc: dict) -> None:
            doc["dna_profiles"] = [p for p in doc["dna_profiles"] if p.get("key") != profile.key] + [
                profile.to_dict()
            ]

        self._push("Profil Design DNA enregistré", mutate)
        return profile

    # --- États de travail -----------------------------------------------------------------------
    def root_of(self, design: dict, target: str) -> str:
        root = design["source_id"] if target == SOURCE else _variant(design, target)["root_id"]
        if root not in self.scene:
            raise LoreError("Ce véhicule n'existe plus dans la scène (supprimé ?).")
        return root

    def state(self, design: dict, target: str = SOURCE) -> VehicleState:
        vc = components.identify(self.session, self.root_of(design, target))
        return VehicleState.from_session(self.session, vc)

    def origin_map(self, design: dict, target: str) -> dict[str, str]:
        if target == SOURCE:
            return {}
        root = self.root_of(design, target)
        return {
            n.id: n.extra["lore"]["copy_of"]
            for n in self.scene.subtree(root)
            if n.extra.get("lore", {}).get("copy_of")
        }

    # --- Analyse -------------------------------------------------------------------------------
    def analyze(self, design_id: str | None = None, target: str = SOURCE) -> dict:
        design = self.design(design_id)
        state = self.state(design, target)
        ai_doc = self.scene.documents.get("ai") or {}
        cloud = ((ai_doc.get("analysis") or {}).get("cloud") or {}).get("result")
        materials = {}
        for entry in state.entries.values():
            material = self.scene.material_for(entry.node_id)
            if material is not None:
                materials[material.id] = material
        vehicle_type = self.session.project.vehicle_type
        report = analyzer.analyze(
            state,
            vehicle_type.value if vehicle_type else "",
            cloud if isinstance(cloud, dict) else None,
            list(materials.values()),
        )
        report["at"] = utc_now_iso()
        report["target"] = target

        def mutate(doc: dict) -> None:
            item = _find(doc, design["id"])
            item["analysis"] = report
            item["workflow"]["analyzed"] = True

        self._push("Analyse stylistique", mutate, history="Analyse stylistique", design_id=design["id"])
        return report

    def set_analysis_value(self, design_id: str, key: str, value: str) -> None:
        def mutate(doc: dict) -> None:
            item = _find(doc, design_id)
            if not item.get("analysis"):
                raise LoreError("Analysez d'abord le véhicule.")
            analyzer.set_value(item["analysis"], key, value)

        self._push(
            "Correction de l'analyse", mutate, history=f"Analyse corrigée : {key}", design_id=design_id
        )

    # --- Propositions ----------------------------------------------------------------------------
    def concept_request(self, design: dict, count: int = 3) -> concepts.ConceptRequest:
        brand = self.brands.get(design.get("brand"))
        return concepts.ConceptRequest(
            brand_key=brand.key if brand else "",
            brand_name=brand.name if brand else "",
            category=design.get("category") or "sedan",
            dna=design.get("dna") or {},
            level=design.get("level", "balanced"),
            count=count,
            seed=f"{self.session.project.project_id}|{design['id']}|{len(design.get('concepts', []))}",
            constraints=tuple(design.get("constraints", [])),
            brand_dna=brand.dna if brand and brand.dna else None,
        )

    def available_operations(self, design: dict, target: str = SOURCE) -> set[str]:
        """Opérations compatibles avec le véhicule (les autres sont écartées et signalées)."""
        state = self.state(design, target)
        kinds = state.components.kinds()
        available = set(ops.OPERATIONS)
        if not state.body_entries():
            available = {k for k, op in ops.OPERATIONS.items() if op.kind in ("add", "replace", "material")}
        if len(state.components.wheels) < 2:
            available -= {"track", "fender_flares"}
        try:
            if not state.landmarks().has_cabin:
                available -= {k for k, d in ops.DEFORMATIONS.items() if d.needs_cabin}
        except IncompatibleTransformation:
            available -= set(ops.DEFORMATIONS) | {"track"}
        if not kinds & {"headlight", "taillight", "signature"}:
            available.discard("light_colors")
        return available

    def generate_concepts(self, design_id: str | None = None, count: int = 3) -> list[dict]:
        design = self.design(design_id)
        if not design.get("brand"):
            raise LoreError("Choisissez d'abord une marque fictive.")
        proposals = concepts.generate(self.concept_request(design, count), self.available_operations(design))
        return self._store_concepts(design["id"], proposals, "Propositions générées (règles Design DNA)")

    def _store_concepts(self, design_id: str, proposals: list[dict], event: str) -> list[dict]:
        stamped = [
            {
                **p,
                "id": uuid.uuid4().hex[:10],
                "created_at": utc_now_iso(),
                "preview": None,
                "messages": [],
                "skipped": [],
                "concept_image": None,
            }
            for p in proposals
        ]

        def mutate(doc: dict) -> None:
            item = _find(doc, design_id)
            item["concepts"].extend(stamped)
            item["workflow"]["proposed"] = True

        self._push(
            "Propositions Lore Friendly", mutate, history=f"{event} : {len(stamped)}", design_id=design_id
        )
        return stamped

    def preview_job(
        self, design_id: str | None = None, concept_ids: list[str] | None = None, size: int = 170
    ):  # type: ignore[no-untyped-def]
        """Tâche (fil secondaire) : rendus des propositions sur la géométrie transformée."""
        design = self.design(design_id)
        targets = [c for c in design["concepts"] if concept_ids is None or c["id"] in concept_ids]
        states = {c["id"]: self.state(design) for c in targets}  # copies de travail préparées ici
        plans = {c["id"]: c["plan"] for c in targets}

        def job(ctx) -> dict:  # type: ignore[no-untyped-def]
            results = {}
            for index, (concept_id, state) in enumerate(states.items()):
                ctx.check()
                messages, skipped = concepts.apply_plan(state, plans[concept_id])
                results[concept_id] = {
                    "png": preview.contact_sheet(state.render_list(), size),
                    "messages": messages,
                    "skipped": skipped,
                    "dimensions": compare_mod.dimensions(state),
                }
                ctx.progress((index + 1) / max(len(states), 1), f"Aperçu {index + 1} / {len(states)}")
            return results

        return job

    def apply_previews(self, design_id: str, results: dict) -> None:
        blobs: list[Command] = []
        keys = {}
        for concept_id, result in results.items():
            key = f"lore-preview-{concept_id}"
            if key not in self.scene.blobs:
                blobs.append(AddBlob(key, result["png"]))
            keys[concept_id] = key

        def mutate(doc: dict) -> None:
            item = _find(doc, design_id)
            for concept in item["concepts"]:
                if concept["id"] in results:
                    result = results[concept["id"]]
                    concept["preview"] = keys[concept["id"]]
                    concept["messages"] = result["messages"]
                    concept["skipped"] = result["skipped"]
                    concept["dimensions"] = result["dimensions"]
            item["workflow"]["previewed"] = True

        self._push("Aperçus des propositions", mutate, blobs, f"Aperçus calculés : {len(results)}", design_id)

    def cloud_request(
        self,
        design_id: str | None,
        folder: Path,
        count: int = 3,
        allow_cloud: bool = False,
        allow_paid: bool = False,
    ) -> GenerationRequest:
        """Requête « plan de transformation » : seul le résumé texte de l'analyse est transmis."""
        design = self.design(design_id)
        brand = self.brands.get(design.get("brand"))
        constraints = ", ".join(concepts.CONSTRAINTS[c][0] for c in design.get("constraints", [])) or "aucune"
        intent = (
            f"Marque fictive : {brand.name if brand else 'à définir'} ({brand.style if brand else ''}). "
            f"Catégorie : {design.get('category')}. "
            f"Niveau : {concepts.LEVELS.get(design.get('level', ''), '')}. "
            f"Design DNA : {dna_mod.describe(design.get('dna') or {})}. Contraintes : {constraints}."
        )
        return GenerationRequest(
            Capability.DESIGN_PLAN,
            [],
            folder,
            params={"catalogue": concepts.catalogue_json(), "count": count},
            prompt=f"{analyzer.summary(design.get('analysis'))}. {intent}",
            allow_cloud=allow_cloud,
            allow_paid=allow_paid,
        )

    def merge_cloud_concepts(
        self, design_id: str | None, output, engine_id: str, engine_name: str
    ) -> tuple[list[dict], list[str]]:  # type: ignore[no-untyped-def]
        design = self.design(design_id)
        proposals, rejected = concepts.from_cloud(
            output.data.get("result", {}), self.concept_request(design), engine_id, engine_name
        )
        available = self.available_operations(design)
        for proposal in proposals:
            rejected += [s["op"] for s in proposal["plan"] if s["op"] not in available]
            proposal["plan"] = [s for s in proposal["plan"] if s["op"] in available]
            proposal["reported_cost"] = output.reported_cost
        proposals = [p for p in proposals if p["plan"]]
        stored = (
            self._store_concepts(design["id"], proposals, f"Propositions {engine_name}") if proposals else []
        )
        return stored, rejected

    def concept_image_request(
        self, design_id: str | None, concept_id: str, folder: Path
    ) -> GenerationRequest:
        """Image conceptuelle 2D (ComfyUI) à partir de l'aperçu rendu de la proposition."""
        design = self.design(design_id)
        concept = _concept(design, concept_id)
        if not concept.get("preview") or concept["preview"] not in self.scene.blobs:
            raise LoreError("Calculez d'abord l'aperçu de la proposition.")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"apercu_{concept_id}.png"
        path.write_bytes(self.scene.blobs[concept["preview"]])
        brand = self.brands.get(design.get("brand"))
        prompt = (
            f"Concept automobile original, marque fictive {brand.name if brand else ''}, {concept['title']}, "
            f"{concept['summary']}. Aucun logo ni marque réelle."
        )
        return GenerationRequest(
            Capability.CONCEPT_IMAGE, [ReferenceInput(path, "three_quarter")], folder, prompt=prompt
        )

    def attach_concept_image(self, design_id: str | None, concept_id: str, output) -> str:  # type: ignore[no-untyped-def]
        path = output.files.get("concept")
        if path is None:
            raise LoreError("Le moteur n'a produit aucune image.")
        key = f"lore-concept-{concept_id}"
        design = self.design(design_id)

        def mutate(doc: dict) -> None:
            _concept(_find(doc, design["id"]), concept_id)["concept_image"] = key

        event = "Image conceptuelle 2D ajoutée (image seulement, aucune géométrie)"
        self._push(
            "Image conceptuelle 2D", mutate, [AddBlob(key, Path(path).read_bytes())], event, design["id"]
        )
        return key

    # --- Variantes --------------------------------------------------------------------------------
    def _lore_set(self, design: dict) -> tuple[str, list[Command]]:
        set_id = design.get("set_id")
        if set_id and set_id in self.scene:
            return set_id, []
        source = self.scene.nodes[design["source_id"]]
        group = SceneNode(
            self.scene.unique_name(f"Lore Friendly · {design['name']}"),
            NodeKind.GROUP,
            extra={
                "variant_set": {"kind": "lore", "design": design["id"]},
                "lore": {"design": design["id"], "set": True},
            },
        )
        index = self.scene.index_of(source.id) + 1
        return group.id, [
            InsertNodes([group.snapshot()], [(group.id, source.parent_id, index)], "Ensemble Lore")
        ]

    def _duplicate(
        self,
        root_id: str,
        set_id: str,
        design_id: str,
        variant_id: str,
        name: str,
        visible: bool,
        extra_root: dict | None = None,
    ) -> tuple[str, InsertNodes]:
        subtree = self.scene.subtree(root_id)
        mapping = {n.id: new_node_id() for n in subtree}
        snapshots = []
        for position, node in enumerate(subtree):
            snap = node.snapshot()
            snap["id"] = mapping[node.id]
            snap["parent_id"] = set_id if position == 0 else mapping[node.parent_id]  # type: ignore[index]
            lore = {
                **node.extra.get("lore", {}),
                "design": design_id,
                "variant": variant_id,
                "copy_of": node.extra.get("lore", {}).get("copy_of", node.id),
            }
            lore.pop("restore_point", None)
            snap["extra"] = {**node.extra, "lore": lore}
            if position == 0:
                snap["name"] = self.scene.unique_name(name)
                snap["visible"] = visible
                snap["locked"] = False
                lore.update(extra_root or {})
            snapshots.append(snap)
        new_root = mapping[root_id]
        return new_root, InsertNodes(snapshots, [(new_root, set_id, None)], "Copie du véhicule")

    def _display_changes(self, design: dict, target: str) -> dict[str, tuple]:
        changes: dict[str, tuple] = {}
        source = self.scene.nodes[design["source_id"]]
        if source.visible != (target == SOURCE):
            changes[source.id] = (source.visible, target == SOURCE)
        for variant in design["variants"]:
            node = self.scene.get(variant["root_id"])
            if node is not None and node.visible != (variant["id"] == target):
                changes[node.id] = (node.visible, variant["id"] == target)
        return changes

    def create_variant(
        self,
        design_id: str | None = None,
        name: str | None = None,
        from_target: str = SOURCE,
        concept_id: str | None = None,
    ) -> str:
        design = self.design(design_id)
        root = self.root_of(design, from_target)
        set_id, steps = self._lore_set(design)
        variant_id = uuid.uuid4().hex[:10]
        label = name or f"Variante {chr(ord('A') + len(design['variants']) % 26)}"
        new_root, insert = self._duplicate(root, set_id, design["id"], variant_id, label, True)
        steps.append(insert)
        hide = self._display_changes(design, "__aucune__")  # la nouvelle variante seule reste visible
        if hide:
            steps.append(SetNodeField("visible", hide, "Affichage"))
        record = {
            "id": variant_id,
            "name": label,
            "root_id": new_root,
            "concept_id": concept_id,
            "from": from_target,
            "created_at": utc_now_iso(),
            "operations": [],
            "restore_points": [],
        }

        def mutate(doc: dict) -> None:
            item = _find(doc, design["id"])
            item["set_id"] = set_id
            item["variants"].append(record)
            item["display"] = variant_id

        self._push(f"Variante « {label} »", mutate, steps, f"Variante créée : {label}", design["id"])
        return variant_id

    def show(self, design_id: str | None, target: str) -> None:
        """Affiche la source (« Revenir à l'original ») ou une variante (les autres sont masquées)."""
        design = self.design(design_id)
        if target != SOURCE:
            _variant(design, target)
        changes = self._display_changes(design, target)
        steps: list[Command] = [SetNodeField("visible", changes, "Affichage")] if changes else []
        self._push(
            "Affichage Lore Friendly",
            lambda doc: _find(doc, design["id"]).__setitem__("display", target),
            steps,
        )

    def restore_point(self, design_id: str | None, variant_id: str, name: str = "") -> str:
        design = self.design(design_id)
        variant = _variant(design, variant_id)
        point_id = uuid.uuid4().hex[:10]
        label = name.strip() or f"Point {len(variant['restore_points']) + 1}"
        root, insert = self._duplicate(
            variant["root_id"],
            design["set_id"],
            design["id"],
            variant_id,
            f"{variant['name']} · {label}",
            False,
            {"restore_point": point_id},
        )

        def mutate(doc: dict) -> None:
            item = _variant(_find(doc, design["id"]), variant_id)
            item["restore_points"].append(
                {"id": point_id, "name": label, "root_id": root, "at": utc_now_iso()}
            )

        self._push(
            "Point de restauration", mutate, [insert], f"Point de restauration « {label} »", design["id"]
        )
        return point_id

    def restore(self, design_id: str | None, variant_id: str, point_id: str) -> str:
        """Restaure un point en créant une nouvelle variante (rien n'est écrasé)."""
        design = self.design(design_id)
        variant = _variant(design, variant_id)
        point = next((p for p in variant["restore_points"] if p["id"] == point_id), None)
        if point is None or point["root_id"] not in self.scene:
            raise LoreError("Point de restauration introuvable.")
        new_id = uuid.uuid4().hex[:10]
        label = f"{variant['name']} (restauré : {point['name']})"
        root, insert = self._duplicate(point["root_id"], design["set_id"], design["id"], new_id, label, True)
        hide = self._display_changes(design, "__aucune__")
        steps: list[Command] = [insert] + ([SetNodeField("visible", hide, "Affichage")] if hide else [])
        record = {
            "id": new_id,
            "name": label,
            "root_id": root,
            "concept_id": variant.get("concept_id"),
            "from": variant_id,
            "created_at": utc_now_iso(),
            "operations": copy.deepcopy(variant["operations"]),
            "restore_points": [],
        }

        def mutate(doc: dict) -> None:
            item = _find(doc, design["id"])
            item["variants"].append(record)
            item["display"] = new_id

        self._push("Restauration", mutate, steps, f"Restauration de « {point['name']} »", design["id"])
        return new_id

    # --- Application ----------------------------------------------------------------------------
    def preview_operation(
        self, design_id: str | None, variant_id: str, op: str, params: dict | None
    ) -> tuple[VehicleState, list[str]]:
        """Prévisualisation (aucune écriture) : état transformé et messages."""
        design = self.design(design_id)
        state = self.state(design, variant_id)
        return state, ops.apply(state, op, params)

    def check(self, design_id: str | None, variant_id: str, plan: list[dict]) -> dict:
        """Vérification des contraintes avant confirmation : impacts et opérations incompatibles."""
        design = self.design(design_id)
        state = self.state(design, variant_id)
        impacts: list[str] = []
        for step in plan:
            if step["op"] in ops.OPERATIONS:
                impacts += [i for i in ops.impacts(state, step["op"]) if i not in impacts]
        messages, skipped = concepts.apply_plan(state, plan)
        return {"impacts": impacts, "messages": messages, "skipped": skipped, "locked": self._locked(state)}

    def _locked(self, state: VehicleState) -> list[str]:
        return [
            self.scene.nodes[e.node_id].name
            for e in state.entries.values()
            if self.scene.effective_locked(e.node_id)
        ]

    def apply_operation(
        self, design_id: str | None, variant_id: str, op: str, params: dict | None = None
    ) -> dict:
        if op not in ops.OPERATIONS:
            raise IncompatibleTransformation(f"Opération inconnue : {op}")
        return self.apply_plan(
            design_id, variant_id, [{"op": op, "params": params or {}}], ops.OPERATIONS[op].label
        )

    def apply_plan(
        self, design_id: str | None, variant_id: str, plan: list[dict], label: str = "Transformation"
    ) -> dict:
        design = self.design(design_id)
        variant = _variant(design, variant_id)
        state = self.state(design, variant_id)
        locked = self._locked(state)
        if locked:
            raise LoreError(f"Pièces verrouillées dans la variante : {', '.join(locked[:4])}.")
        impacts: list[str] = []
        for step in plan:
            if step["op"] in ops.OPERATIONS:
                impacts += [i for i in ops.impacts(state, step["op"]) if i not in impacts]
        messages, skipped = concepts.apply_plan(state, plan)
        if len(skipped) == len(plan):
            raise IncompatibleTransformation(
                "Transformation incompatible avec ce véhicule : " + " ; ".join(skipped)
            )
        steps = self._state_commands(state, variant["root_id"], design["id"], variant_id)
        skipped_labels = {s.split(" : ", 1)[0] for s in skipped}
        entries = [
            {
                "op": s["op"],
                "label": ops.OPERATIONS[s["op"]].label,
                "params": s.get("params", {}),
                "parts": ops.OPERATIONS[s["op"]].kind in ("add", "replace"),
                "at": utc_now_iso(),
            }
            for s in plan
            if s["op"] in ops.OPERATIONS and ops.OPERATIONS[s["op"]].label not in skipped_labels
        ]
        if entries:
            entries[-1]["messages"] = messages
            entries[-1]["impacts"] = impacts

        def mutate(doc: dict) -> None:
            item = _find(doc, design["id"])
            _variant(item, variant_id)["operations"].extend(entries)
            item["workflow"]["confirmed"] = True
            item["workflow"]["applied"] = True

        self._push(label, mutate, steps, f"{label} → {variant['name']}", design["id"])
        return {"messages": messages, "skipped": skipped, "impacts": impacts}

    def apply_concept(self, design_id: str | None, concept_id: str, variant_id: str | None = None) -> str:
        """Applique une proposition (nouvelle variante ou variante donnée) en une étape d'historique."""
        design = self.design(design_id)
        concept = _concept(design, concept_id)
        stack = self.session.stack
        label = f"Proposition « {concept['title']} »"
        stack.begin(label)
        try:
            target = variant_id or self.create_variant(design["id"], concept["title"], concept_id=concept_id)
            self.apply_plan(design["id"], target, concept["plan"], label)
        except Exception:
            stack.rollback()
            self.sync_libraries()
            raise
        stack.commit()
        return target

    def _state_commands(
        self, state: VehicleState, variant_root: str, design_id: str, variant_id: str
    ) -> list[Command]:
        scene = self.scene
        editor = VehicleEditor(self.session)
        steps: list[Command] = [
            editor.geometry_command(e.node_id, e.mesh, "Déformation Lore Friendly")
            for e in state.entries.values()
            if e.edited
        ]
        moves = {}
        for owner, delta in state.moves.items():
            if owner not in scene or float(np.abs(delta).max()) < 1e-9:
                continue
            world = scene.world_matrix(owner)
            world[:3, 3] += delta
            local = np.linalg.inv(scene.parent_world_matrix(owner)) @ world
            moves[owner] = (scene.nodes[owner].transform.copy(), Transform.from_matrix(local))
        if moves:
            steps.append(SetTransforms(moves, "Déplacement des pièces"))
        hidden = {o: (True, False) for o in state.hidden if o in scene and scene.nodes[o].visible}
        if hidden:
            steps.append(SetNodeField("visible", hidden, "Pièces remplacées (masquées)"))
        for owner, spec in state.materials.items():
            material = _material(spec)
            targets = [e.node_id for e in state.entries.values() if e.owner_id == owner]
            steps += [AddMaterial(material), AssignMaterial(targets, material.id, "Matériau Lore")]
        if not state.new_parts:
            return steps
        group_id = next(
            (c.id for c in scene.children(variant_root) if c.extra.get("lore", {}).get("parts_group")), None
        )
        snapshots: list[dict] = []
        roots: list[tuple[str, str | None, int | None]] = []
        new_group = group_id is None
        if new_group:
            group = SceneNode(
                "Pièces Lore Friendly",
                NodeKind.GROUP,
                extra={"lore": {"design": design_id, "variant": variant_id, "parts_group": True}},
            )
            snapshots.append(group.snapshot())
            roots.append((group.id, variant_root, None))
            group_id = group.id
            parent_world = scene.world_matrix(variant_root)
        else:
            parent_world = scene.world_matrix(group_id)
        inverse = np.linalg.inv(parent_world)
        meshes, materials = {}, []
        for part in state.new_parts:
            key = new_mesh_key()
            material = _material(part.material)
            node = SceneNode(
                scene.unique_name(part.name),
                NodeKind.MESH,
                Transform.from_matrix(inverse @ part.world),
                mesh_key=key,
                material_id=material.id,
                parent_id=group_id,
                extra={
                    "lore": {"design": design_id, "variant": variant_id, "part": part.operation},
                    "component": {"lore_kind": part.kind},
                },
            )
            snapshots.append(node.snapshot())
            if not new_group:
                roots.append((node.id, group_id, None))
            meshes[key] = part.mesh
            materials.append(material)
        steps.append(InsertNodes(snapshots, roots, "Pièces Lore Friendly", materials, meshes=meshes))
        return steps

    # --- Comparaison et revue ------------------------------------------------------------------
    def compare(self, design_id: str | None, a: str, b: str) -> dict:
        design = self.design(design_id)
        result = compare_mod.compare(
            self.state(design, a),
            self.state(design, b),
            self.origin_map(design, a),
            self.origin_map(design, b),
        )
        record = {"a": a, "b": b, "at": utc_now_iso(), "result": result}

        def mutate(doc: dict) -> None:
            item = _find(doc, design["id"])
            item["comparisons"] = (item["comparisons"] + [record])[-COMPARISON_LIMIT:]
            item["workflow"]["compared"] = True

        event = f"Comparaison {self.label(design, a)} / {self.label(design, b)}"
        self._push("Comparaison", mutate, history=event, design_id=design["id"])
        return result

    def overlay(self, design_id: str | None, a: str, b: str) -> np.ndarray:
        design = self.design(design_id)
        return compare_mod.displacement_overlay(
            self.state(design, a), self.state(design, b), self.origin_map(design, b)
        )

    def review(self, design_id: str | None, variant_id: str) -> dict:
        design = self.design(design_id)
        variant = _variant(design, variant_id)
        comparison = compare_mod.compare(
            self.state(design), self.state(design, variant_id), {}, self.origin_map(design, variant_id)
        )
        ai_doc = self.scene.documents.get("ai") or {}
        logos = sum(
            1
            for r in ai_doc.get("references", [])
            for n in r.get("annotations", [])
            if n.get("kind") == "logo"
        )
        result = originality.review(
            comparison, [o["op"] for o in variant["operations"]], design.get("checklist"), logos
        )
        result["at"] = utc_now_iso()

        def mutate(doc: dict) -> None:
            item = _find(doc, design["id"])
            item["originality"][variant_id] = result
            item["workflow"]["checked"] = True

        self._push(
            "Revue d'originalité",
            mutate,
            history=f"Revue d'originalité : {variant['name']}",
            design_id=design["id"],
        )
        return result

    def set_checklist(self, design_id: str | None, key: str, value: bool) -> None:
        if key not in originality.CHECKLIST:
            raise LoreError("Point de contrôle inconnu.")
        design = self.design(design_id)
        self._push(
            "Vérification", lambda doc: _find(doc, design["id"])["checklist"].__setitem__(key, bool(value))
        )

    # --- Provenance -------------------------------------------------------------------------------
    def provenance(self) -> list[dict]:
        detected = provenance.collect(
            self.session, self.scene.documents.get("ai"), self.document(), self.brands.get
        )
        return provenance.merged(detected, self.scene.documents.get(provenance.DOC_KEY))

    def _push_provenance(self, label: str, after: dict) -> None:
        before = self.scene.documents.get(provenance.DOC_KEY)
        command = SetDocument(provenance.DOC_KEY, copy.deepcopy(before), after, label)
        self.session.stack.push(CompositeCommand([command], label))

    def update_provenance(self, entry_id: str, **fields) -> None:  # type: ignore[no-untyped-def]
        doc = self.scene.documents.get(provenance.DOC_KEY)
        self._push_provenance("Provenance", provenance.update(doc, entry_id, **fields))

    def add_mention(self, entry_id: str, text: str) -> None:
        doc = self.scene.documents.get(provenance.DOC_KEY)
        self._push_provenance("Mention obligatoire", provenance.add_mention(doc, entry_id, text))

    # --- Workflow et utilitaires -----------------------------------------------------------------
    def workflow(self, design_id: str | None = None) -> list[tuple[str, str, bool]]:
        try:
            design = self.design(design_id)
        except LoreError:
            return [(k, label, False) for k, label in WORKFLOW]
        flags = dict(design.get("workflow", {}))
        flags["saved"] = bool(design["variants"]) and not self.session.dirty
        return [(k, label, bool(flags.get(k))) for k, label in WORKFLOW]

    def label(self, design: dict, target: str) -> str:
        if target == SOURCE:
            return f"Original ({design['source_name']})"
        return _variant(design, target)["name"]

    def targets(self, design: dict) -> list[tuple[str, str]]:
        return [(SOURCE, self.label(design, SOURCE))] + [(v["id"], v["name"]) for v in design["variants"]]


def _find(doc: dict, design_id: str) -> dict:
    for design in doc["designs"]:
        if design["id"] == design_id:
            return design
    raise LoreError("Design introuvable.")


def _variant(design: dict, variant_id: str) -> dict:
    for variant in design["variants"]:
        if variant["id"] == variant_id:
            return variant
    raise LoreError("Variante introuvable.")


def _concept(design: dict, concept_id: str) -> dict:
    for concept in design["concepts"]:
        if concept["id"] == concept_id:
            return concept
    raise LoreError("Proposition introuvable.")


def _material(spec: dict) -> Material:
    return Material(
        spec.get("name", "Matériau Lore"),
        tuple(spec.get("base_color", (0.72, 0.74, 0.78, 1.0))),
        float(spec.get("roughness", 0.5)),
        float(spec.get("metallic", 0.0)),
        emissive=tuple(spec.get("emissive", (0.0, 0.0, 0.0))),
        emissive_strength=float(spec.get("emissive_strength", 0.0)),
    )
