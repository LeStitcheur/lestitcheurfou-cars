"""Bibliothèque locale de composants 3D (Component Library).

Stockage : ``<données de l'application>/library/`` ::

    library.json                 <- index versionné (métadonnées de chaque composant)
    meshes/<id>/<n>.npz          <- géométrie des pièces (npz compressé)
    textures/<id>/<n>.png        <- textures éventuelles des matériaux

Un composant ajouté à un véhicule est **copié** dans le projet (géométrie locale du ``.lsfc``,
textures dans ``assets/textures``) : supprimer un composant de la bibliothèque n'affecte jamais
les projets existants.

Les composants de départ sont des formes paramétriques originales (``scene.shapes``), générées
localement : aucun asset propriétaire n'est distribué.
"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from lsfcars.core.logging_setup import get_logger
from lsfcars.editor.operations import Payload, new_mesh_key
from lsfcars.project.model import utc_now_iso
from lsfcars.scene import mathutils, shapes
from lsfcars.scene.graph import NodeKind, SceneNode
from lsfcars.scene.materials import Material
from lsfcars.scene.mesh import MeshData
from lsfcars.scene.transform import Transform, decompose

log = get_logger(__name__)

LIBRARY_VERSION = 1
CATEGORIES: dict[str, str] = {
    "carrosserie": "Carrosserie",
    "pare_chocs": "Pare-chocs",
    "spoilers": "Spoilers",
    "calandres": "Calandres",
    "phares": "Phares",
    "feux": "Feux arrière",
    "retroviseurs": "Rétroviseurs",
    "jantes": "Jantes",
    "pneus": "Pneus",
    "sieges": "Sièges",
    "tableaux_de_bord": "Tableaux de bord",
    "accessoires": "Accessoires",
    "urgence": "Équipements d'urgence",
    "personnalises": "Composants personnalisés",
}
# catégorie de bibliothèque → catégorie de véhicule (``editor.vehicle``)
VEHICLE_CATEGORY = {
    "carrosserie": "carrosserie",
    "pare_chocs": "carrosserie",
    "spoilers": "carrosserie",
    "calandres": "carrosserie",
    "phares": "phares",
    "feux": "phares",
    "retroviseurs": "accessoires",
    "jantes": "roues",
    "pneus": "roues",
    "sieges": "sieges",
    "tableaux_de_bord": "tableau_de_bord",
    "accessoires": "accessoires",
    "urgence": "accessoires",
    "personnalises": "non_classee",
}
BUILTIN_AUTHOR = "LeStitcheurFou Cars"
BUILTIN_LICENSE = "Original, généré par LeStitcheurFou Cars : libre d'utilisation dans vos projets"
BUILTIN_PROVENANCE = "Forme paramétrique intégrée (aucun asset tiers)"
BUILTIN_COMPATIBILITY = "Géométrie simple non validée en jeu : export et validation FiveM à faire"


class LibraryError(Exception):
    pass


@dataclass
class LibraryComponent:
    id: str
    name: str
    category: str
    parts: list[dict] = field(default_factory=list)  # {name, mesh, transform, material}
    materials: list[dict] = field(default_factory=list)  # Material.to_dict() (+ texture_file)
    attach_points: list[dict] = field(default_factory=list)  # {name, type, position, rotation}
    pivot: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    dimensions: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    author: str = ""
    provenance: str = ""
    license: str = ""
    compatibility: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    builtin: bool = False
    created_at: str = field(default_factory=utc_now_iso)
    triangles: int = 0

    @property
    def category_label(self) -> str:
        return CATEGORIES.get(self.category, CATEGORIES["personnalises"])

    @classmethod
    def from_dict(cls, data: dict) -> LibraryComponent:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


Attach = tuple[tuple[str, str, tuple[float, float, float]], ...]


@dataclass(frozen=True)
class BuiltinSpec:
    key: str
    name: str
    category: str
    factory: Callable[[], MeshData]
    preset: str = ""
    attach: Attach = ()
    description: str = ""


BUILTINS: tuple[BuiltinSpec, ...] = (
    BuiltinSpec(
        "spoiler",
        "Aileron GT",
        "spoilers",
        shapes.spoiler,
        "paint_gloss",
        (("Fixation gauche", "trunk", (-0.42, 0.0, 0.0)), ("Fixation droite", "trunk", (0.42, 0.0, 0.0))),
        "Aile à profil incliné sur deux supports",
    ),
    BuiltinSpec("bumper", "Pare-chocs avant sport", "pare_chocs", shapes.bumper, "paint_gloss"),
    BuiltinSpec("grille", "Calandre à barres", "calandres", shapes.grille, "plastic"),
    BuiltinSpec("air_intake", "Prise d'air de capot", "carrosserie", shapes.air_intake, "paint_gloss"),
    BuiltinSpec("side_skirt", "Bas de caisse", "carrosserie", shapes.side_skirt, "paint_gloss"),
    BuiltinSpec("splitter", "Lame avant", "carrosserie", shapes.splitter, "plastic"),
    BuiltinSpec("diffuser", "Diffuseur arrière", "carrosserie", shapes.diffuser, "plastic"),
    BuiltinSpec("fender_flare", "Élargisseur d'aile", "carrosserie", shapes.fender_flare, "plastic"),
    BuiltinSpec("canard", "Canard aérodynamique", "carrosserie", shapes.canard, "plastic"),
    BuiltinSpec("hood", "Capot bombé", "carrosserie", shapes.hood, "paint_gloss"),
    BuiltinSpec("headlight", "Phare double optique", "phares", shapes.headlight, "chrome"),
    BuiltinSpec("taillight", "Feu arrière", "feux", shapes.taillight, "glass"),
    BuiltinSpec("mirror", "Rétroviseur", "retroviseurs", shapes.mirror, "paint_gloss"),
    BuiltinSpec("rim5", "Jante 5 branches", "jantes", shapes.rim, "chrome"),
    BuiltinSpec("rim7", "Jante 7 branches", "jantes", lambda: shapes.rim(spokes=7), "metal"),
    BuiltinSpec("tire", "Pneu", "pneus", shapes.tire, "rubber"),
    BuiltinSpec("wheel", "Roue complète", "jantes", shapes.wheel, "rubber"),
    BuiltinSpec(
        "seat",
        "Siège baquet",
        "sieges",
        shapes.seat,
        "fabric",
        (("Fixation siège", "generic", (0.0, 0.0, 0.0)),),
    ),
    BuiltinSpec(
        "dashboard",
        "Tableau de bord",
        "tableaux_de_bord",
        shapes.dashboard,
        "plastic",
        (("Support tableau de bord", "dashboard", (0.0, 0.3, 0.2)),),
    ),
    BuiltinSpec("steering_wheel", "Volant", "tableaux_de_bord", shapes.steering_wheel, "leather"),
    BuiltinSpec(
        "lightbar",
        "Rampe lumineuse",
        "urgence",
        shapes.lightbar,
        "plastic",
        (("Fixation toit", "roof", (0.0, 0.0, 0.0)),),
        "Équipement d'urgence (Emergency Studio à venir)",
    ),
    BuiltinSpec(
        "push_bar",
        "Pare-buffle",
        "urgence",
        shapes.push_bar,
        "plastic",
        (("Fixation pare-chocs", "bumper", (0.0, 0.0, 0.0)),),
    ),
    BuiltinSpec(
        "medical_bracket",
        "Support médical",
        "urgence",
        shapes.medical_bracket,
        "metal",
        (("Support médical", "medical", (0.0, 0.0, 0.03)),),
    ),
    BuiltinSpec("antenna", "Antenne", "accessoires", shapes.antenna, "plastic"),
    BuiltinSpec(
        "roof_rack",
        "Galerie de toit",
        "accessoires",
        shapes.roof_rack,
        "metal",
        (("Charge de toit", "roof", (0.0, 0.03, 0.0)),),
    ),
)


def default_root() -> Path:
    from lsfcars.core.paths import app_data_dir

    return app_data_dir() / "library"


def _write_mesh(mesh: MeshData, path: Path) -> None:
    from lsfcars.project.store import mesh_to_bytes

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(mesh_to_bytes(mesh))


def _read_mesh(name: str, path: Path) -> MeshData:
    from lsfcars.project.store import mesh_from_bytes

    return mesh_from_bytes(name, path.read_bytes())


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "composant"


def _box_corners(bmin: np.ndarray, bmax: np.ndarray) -> np.ndarray:
    return np.array(
        [[x, y, z] for x in (bmin[0], bmax[0]) for y in (bmin[1], bmax[1]) for z in (bmin[2], bmax[2])]
    )


class ComponentLibrary:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_root()
        self._components: dict[str, LibraryComponent] = {}
        self._removed_builtins: set[str] = set()
        self._load()

    # --- Index -----------------------------------------------------------------
    @property
    def index_path(self) -> Path:
        return self.root / "library.json"

    def _load(self) -> None:
        if not self.index_path.is_file():
            return
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Index de bibliothèque illisible (%s) : bibliothèque vide", exc)
            return
        if int(data.get("version", 0)) > LIBRARY_VERSION:
            raise LibraryError("Bibliothèque créée par une version plus récente du logiciel.")
        for item in data.get("components", []):
            try:
                component = LibraryComponent.from_dict(item)
            except TypeError:
                continue
            self._components[component.id] = component
        self._removed_builtins = set(data.get("removed_builtins", []))

    def _save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        data = {
            "version": LIBRARY_VERSION,
            "components": [asdict(c) for c in self._components.values()],
            "removed_builtins": sorted(self._removed_builtins),
        }
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.index_path)

    # --- Lecture -------------------------------------------------------------------
    def components(self) -> list[LibraryComponent]:
        return sorted(self._components.values(), key=lambda c: (c.category_label, c.name.lower()))

    def get(self, component_id: str) -> LibraryComponent | None:
        return self._components.get(component_id)

    def search(self, text: str = "", category: str | None = None) -> list[LibraryComponent]:
        words = [w for w in text.lower().split() if w]
        found = []
        for component in self.components():
            if category and component.category != category:
                continue
            fields = [component.name, component.category_label, component.description, component.author]
            haystack = " ".join([*fields, *component.tags]).lower()
            if all(w in haystack for w in words):
                found.append(component)
        return found

    def load_meshes(self, component: LibraryComponent) -> list[MeshData]:
        folder = self.root / "meshes" / component.id
        meshes = []
        for part in component.parts:
            path = folder / part["mesh"]
            if not path.is_file():
                raise LibraryError(f"Géométrie manquante pour « {component.name} » ({part['mesh']}).")
            meshes.append(_read_mesh(part["name"], path))
        return meshes

    def preview_mesh(self, component: LibraryComponent) -> MeshData:
        """Toutes les pièces fusionnées dans le repère du composant (aperçu léger)."""
        meshes = self.load_meshes(component)
        parts = [
            (mesh, Transform.from_dict(part.get("transform", {})).matrix())
            for mesh, part in zip(meshes, component.parts, strict=True)
        ]
        return shapes.combine(component.name, parts)

    # --- Écriture --------------------------------------------------------------------
    def add(
        self,
        name: str,
        category: str,
        parts: list[tuple[MeshData, Transform | None, Material | None]],
        *,
        author: str = "",
        provenance: str = "",
        license: str = "",
        compatibility: str = "",
        description: str = "",
        attach_points: list[dict] | None = None,
        builtin: bool = False,
        component_id: str | None = None,
        textures: dict[int, bytes] | None = None,
    ) -> LibraryComponent:
        """Ajoute un composant (pièces = maillage, transformation, matériau)."""
        if not parts:
            raise LibraryError("Un composant doit contenir au moins une pièce.")
        category = category if category in CATEGORIES else "personnalises"
        component_id = component_id or f"{_slug(name)}-{uuid.uuid4().hex[:8]}"
        folder = self.root / "meshes" / component_id
        materials: list[dict] = []
        material_index: dict[str, int] = {}
        stored_parts = []
        corners = []
        triangles = 0
        for number, (mesh, transform, material) in enumerate(parts):
            filename = f"{number}.npz"
            _write_mesh(mesh, folder / filename)
            index = None
            if material is not None:
                if material.id not in material_index:
                    material_index[material.id] = len(materials)
                    data = material.to_dict()
                    data["texture"] = None
                    data["normal_texture"] = None
                    materials.append(data)
                index = material_index[material.id]
            transform = transform or Transform()
            stored_parts.append(
                {"name": mesh.name, "mesh": filename, "transform": transform.to_dict(), "material": index}
            )
            corners.append(mathutils.transform_points(transform.matrix(), _box_corners(*mesh.bounds)))
            triangles += mesh.triangle_count
        for index, png in (textures or {}).items():
            if 0 <= index < len(materials):
                path = self.root / "textures" / component_id / f"{index}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(png)
                materials[index]["texture_file"] = path.name
        points = np.vstack(corners)
        component = LibraryComponent(
            component_id,
            name.strip() or "Composant",
            category,
            stored_parts,
            materials,
            list(attach_points or []),
            [0.0, 0.0, 0.0],
            [float(v) for v in points.max(axis=0) - points.min(axis=0)],
            author,
            provenance,
            license,
            compatibility,
            description,
            builtin=builtin,
            triangles=triangles,
        )
        self._components[component_id] = component
        self._save()
        return component

    def ensure_builtins(self) -> int:
        """Génère les composants de départ absents (sauf ceux supprimés par l'utilisateur)."""
        from lsfcars.scene.material_presets import preset

        created = 0
        for spec in BUILTINS:
            component_id = f"lsf-{spec.key}"
            if component_id in self._components or component_id in self._removed_builtins:
                continue
            material = None
            found = preset(spec.preset) if spec.preset else None
            if found is not None:
                material = Material(found.label)
                material.apply(found.properties())
            attach = [
                {"name": n, "type": t, "position": list(p), "rotation": [0.0, 0.0, 0.0]}
                for n, t, p in spec.attach
            ]
            self.add(
                spec.name,
                spec.category,
                [(spec.factory(), None, material)],
                author=BUILTIN_AUTHOR,
                provenance=BUILTIN_PROVENANCE,
                license=BUILTIN_LICENSE,
                compatibility=BUILTIN_COMPATIBILITY,
                description=spec.description,
                attach_points=attach,
                builtin=True,
                component_id=component_id,
            )
            created += 1
        return created

    def import_file(
        self,
        path: str | Path,
        name: str | None = None,
        category: str = "personnalises",
        author: str = "",
        license: str = "",
        provenance: str = "",
    ) -> LibraryComponent:
        """Importe un modèle 3D (OBJ, glTF, GLB, FBX via Blender, .yft…) comme composant."""
        from lsfcars.importers import load_model

        path = Path(path)
        result = load_model(path)
        worlds: dict[str | None, np.ndarray] = {None: np.eye(4)}
        materials: dict[str, Material] = {}
        textures: dict[str, bytes] = {}
        for key, imported in result.materials.items():
            materials[key] = Material(
                imported.name, imported.base_color, imported.roughness, imported.metallic, imported.opacity
            )
            if imported.texture_png:
                textures[key] = imported.texture_png
        parts: list[tuple[MeshData, Transform | None, Material | None]] = []
        for node in result.nodes:
            worlds[node.key] = worlds.get(node.parent_key, np.eye(4)) @ node.transform.matrix()
            if node.mesh_key and node.mesh_key in result.meshes:
                mesh = result.meshes[node.mesh_key]
                mesh.name = node.name
                parts.append((mesh, decompose(worlds[node.key]), materials.get(node.material_key or "")))
        if not parts:
            raise LibraryError(f"« {path.name} » ne contient aucun maillage.")
        ordered = list(dict.fromkeys(m.id for _, _, m in parts if m is not None))
        texture_by_index = {
            ordered.index(materials[key].id): png
            for key, png in textures.items()
            if materials[key].id in ordered
        }
        return self.add(
            name or path.stem,
            category,
            parts,
            author=author,
            provenance=provenance or f"Fichier importé : {path.name}",
            license=license or "Non précisée : vérifiez vos droits avant diffusion",
            compatibility="Importé, non validé pour FiveM",
            textures=texture_by_index,
        )

    def save_from_scene(
        self,
        session,  # type: ignore[no-untyped-def]
        node_id: str,
        name: str = "",
        category: str = "personnalises",
        author: str = "",
        license: str = "",
    ) -> LibraryComponent:
        """Enregistre une pièce du projet (et ses enfants) comme preset de bibliothèque."""
        scene = session.scene
        root = scene.get(node_id)
        if root is None:
            raise LibraryError("Élément introuvable.")
        inverse = np.linalg.inv(scene.world_matrix(node_id))
        parts: list[tuple[MeshData, Transform | None, Material | None]] = []
        attach_points = []
        for node in scene.subtree(node_id):
            relative = decompose(inverse @ scene.world_matrix(node.id))
            if node.kind is NodeKind.ANCHOR:
                attach_points.append(
                    {
                        "name": node.name,
                        "type": node.extra.get("anchor", {}).get("type", "generic"),
                        "position": relative.translation,
                        "rotation": relative.rotation,
                    }
                )
                continue
            mesh = session.geometry_for(node)
            if mesh is not None:
                parts.append((mesh, relative, scene.material_for(node.id)))
        if not parts:
            raise LibraryError("La sélection ne contient aucune géométrie.")
        textures: dict[int, bytes] = {}
        ordered = list(dict.fromkeys(m.id for _, _, m in parts if m is not None))
        for index, material_id in enumerate(ordered):
            texture = scene.materials[material_id].texture
            if texture and (session.project.project_dir / texture).is_file():
                textures[index] = (session.project.project_dir / texture).read_bytes()
        return self.add(
            name or root.name,
            category,
            parts,
            author=author,
            provenance=f"Projet « {session.project.name} »",
            license=license or "Non précisée",
            compatibility="Créé dans LeStitcheurFou Cars, non validé pour FiveM",
            attach_points=attach_points,
            textures=textures,
        )

    def duplicate(self, component_id: str, name: str | None = None) -> LibraryComponent:
        source = self.get(component_id)
        if source is None:
            raise LibraryError("Composant introuvable.")
        meshes = self.load_meshes(source)
        materials = [
            Material.from_dict({k: v for k, v in m.items() if k not in ("id", "texture_file")})
            for m in source.materials
        ]
        parts: list[tuple[MeshData, Transform | None, Material | None]] = []
        for mesh, part in zip(meshes, source.parts, strict=True):
            material = materials[part["material"]] if part["material"] is not None else None
            parts.append((mesh, Transform.from_dict(part["transform"]), material))
        textures = {}
        for index, data in enumerate(source.materials):
            path = self.root / "textures" / source.id / str(data.get("texture_file") or "")
            if data.get("texture_file") and path.is_file():
                textures[index] = path.read_bytes()
        return self.add(
            name or f"{source.name} (copie)",
            source.category,
            parts,
            author=source.author,
            provenance=source.provenance,
            license=source.license,
            compatibility=source.compatibility,
            description=source.description,
            attach_points=[dict(a) for a in source.attach_points],
            textures=textures,
        )

    def update(self, component_id: str, **fields) -> LibraryComponent:  # type: ignore[no-untyped-def]
        component = self.get(component_id)
        if component is None:
            raise LibraryError("Composant introuvable.")
        for key in (
            "name",
            "category",
            "author",
            "provenance",
            "license",
            "compatibility",
            "description",
            "tags",
        ):
            if fields.get(key) is not None:
                setattr(component, key, fields[key])
        self._save()
        return component

    def delete(self, component_id: str) -> None:
        """Retire un composant de la bibliothèque (les projets qui l'utilisent gardent leur copie)."""
        component = self._components.pop(component_id, None)
        if component is None:
            return
        if component.builtin:
            self._removed_builtins.add(component_id)
        for folder in (self.root / "meshes" / component_id, self.root / "textures" / component_id):
            shutil.rmtree(folder, ignore_errors=True)
        self._save()

    def restore_builtins(self) -> int:
        self._removed_builtins.clear()
        return self.ensure_builtins()

    # --- Insertion dans un projet -------------------------------------------------------
    def payload(self, component: LibraryComponent, project=None) -> Payload:  # type: ignore[no-untyped-def]
        """Sous-arbre prêt à insérer : géométrie et matériaux **copiés** (nouveaux identifiants)."""
        meshes = self.load_meshes(component)
        materials: list[Material] = []
        for index, data in enumerate(component.materials):
            material = Material.from_dict({k: v for k, v in data.items() if k not in ("id", "texture_file")})
            texture = self.root / "textures" / component.id / str(data.get("texture_file") or "")
            if data.get("texture_file") and texture.is_file() and project is not None and project.file_path:
                from lsfcars.project.store import store_texture

                material.texture = store_texture(project, texture.read_bytes(), f"{component.name}_{index}")
            materials.append(material)
        info = {
            "library_id": component.id,
            "category": VEHICLE_CATEGORY.get(component.category, "non_classee"),
            "library_category": component.category,
            "author": component.author,
            "provenance": component.provenance,
            "license": component.license,
        }
        mesh_payload: dict[str, MeshData] = {}
        single = len(meshes) == 1 and not component.attach_points
        root = SceneNode(
            component.name, NodeKind.MESH if single else NodeKind.GROUP, extra={"component": info}
        )
        if single:
            key = new_mesh_key()
            mesh_payload[key] = meshes[0]
            root.mesh_key = key
            root.transform = Transform.from_dict(component.parts[0]["transform"])
            index = component.parts[0]["material"]
            root.material_id = materials[index].id if index is not None else None
            return Payload([root.snapshot()], mesh_payload, materials)
        snapshots = [root.snapshot()]
        for mesh, part in zip(meshes, component.parts, strict=True):
            key = new_mesh_key()
            mesh_payload[key] = mesh
            index = part["material"]
            child = SceneNode(
                part["name"],
                NodeKind.MESH,
                Transform.from_dict(part["transform"]),
                mesh_key=key,
                material_id=materials[index].id if index is not None else None,
            )
            snapshots.append({**child.snapshot(), "parent_id": root.id})
        for point in component.attach_points:
            position = [float(v) for v in point.get("position", [0, 0, 0])]
            rotation = [float(v) for v in point.get("rotation", [0, 0, 0])]
            anchor = SceneNode(
                point.get("name", "Point d'attache"),
                NodeKind.ANCHOR,
                Transform(position, rotation),
                extra={
                    "anchor": {
                        "anchor_id": uuid.uuid4().hex[:12],
                        "type": point.get("type", "generic"),
                        "constraints": "fixed",
                        "metadata": {"source": "bibliothèque"},
                        "component_id": root.id,
                    }
                },
            )
            snapshots.append({**anchor.snapshot(), "parent_id": root.id})
        return Payload(snapshots, mesh_payload, materials)
