"""Opérations de l'Emergency Vehicle Studio (sans Qt), toutes annulables.

Organisation dans la scène ::

    véhicule de base (pièces partagées par toutes les variantes)
    Variantes d'urgence            <- ensemble de variantes (une seule visible)
        SUV LSPD                   <- racine de variante : équipements propres à la variante
            Rampe lumineuse pleine
            Intérieur              <- équipements intérieurs
        SUV SAMD

Les données non géométriques (feux, groupes, motifs, sirène, livrée, métadonnées) vivent dans
le document ``emergency`` de la scène ; chaque opération combine les commandes de scène et la
mise à jour du document en **une seule étape d'historique**. Les modifications du véhicule de
base sont partagées par toutes les variantes sans écraser leurs personnalisations.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field

import numpy as np

from lsfcars.editor.library import LibraryComponent, LibraryError
from lsfcars.editor.operations import VehicleEditor
from lsfcars.emergency import model
from lsfcars.emergency.equipment import EquipmentLibrary
from lsfcars.emergency.model import (
    LightGroup,
    LightSource,
    LiveryData,
    Pattern,
    PatternFrame,
    SirenMode,
    SirenProfile,
    StudioState,
    Variant,
    Zone,
    build_pattern,
    new_id,
)
from lsfcars.scene import editmesh, mathutils
from lsfcars.scene.commands import (
    Command,
    CompositeCommand,
    InsertNodes,
    RemoveNodes,
    SetDocument,
    SetNodeExtra,
    SetNodeField,
    SetTransforms,
)
from lsfcars.scene.editmesh import EditError
from lsfcars.scene.graph import NodeKind, SceneNode, new_node_id
from lsfcars.scene.transform import Transform, decompose

DOC_KEY = "emergency"
MAX_PREVIEW_LIGHTS = 96  # lumières simultanées affichées par la prévisualisation
DEFAULT_GROUPS = ("main", "left", "right", "front", "rear", "secondary", "work")
INTERIOR_PRESETS: dict[str, tuple[tuple, ...]] = {
    "police": (
        ("lsf-pol-console", "console"),
        ("lsf-pol-mdt", "dash"),
        ("lsf-pol-radio", "console", (0.0, 0.33, -0.05)),  # posée sur la console
        ("lsf-pol-partition", "partition"),
        ("lsf-pol-storage", "cargo"),
    ),
    "ems": (
        ("lsf-ems-stretcher", "patient"),
        ("lsf-ems-bag", "cargo"),
        ("lsf-ems-bracket", "patient"),
        ("lsf-ems-storage", "cargo"),
        ("lsf-ems-firstaid", "rear_seat"),
        ("lsf-ems-radio", "console", (0.0, 0.05, 0.0)),
    ),
    "fire": (
        ("lsf-fire-storage", "cargo"),
        ("lsf-fire-rescue-kit", "cargo"),
        ("lsf-ems-firstaid", "rear_seat"),
    ),
}
INTERIOR_LABELS = {"police": "Police", "ems": "EMS / SAMD", "fire": "Fire / Rescue"}
CATEGORY_GROUP = {"rampe": "main", "gyro": "main", "lunette": "rear", "travail": "work"}


class EquipmentError(EditError):
    """Équipement ou opération invalide (géométrie absente, introuvable, incompatible…)."""


@dataclass
class Placement:
    transform: Transform  # transformation locale au parent
    world: np.ndarray
    zone: str | None
    warnings: list[str] = field(default_factory=list)


@dataclass
class AddResult:
    node_id: str
    light_ids: list[str]
    warnings: list[str]


def _unit(v) -> np.ndarray:  # type: ignore[no-untyped-def]
    v = np.asarray(v, np.float64)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else v


def orientation(up, forward) -> np.ndarray:  # type: ignore[no-untyped-def]
    """Rotation 3x3 dont l'axe local +Y suit ``up`` et l'axe local -Z suit ``forward``."""
    y = _unit(up)
    f = np.asarray(forward, np.float64)
    f = f - y * float(f @ y)
    if np.linalg.norm(f) < 1e-6:  # avant parallèle au haut : axe de repli
        f = np.cross(y, [1.0, 0.0, 0.0]) if abs(y[0]) < 0.9 else np.cross(y, [0.0, 0.0, 1.0])
    z = -_unit(f)
    x = _unit(np.cross(y, z))
    return np.column_stack([x, y, z])


def snap_value(value: float, step: float) -> float:
    return round(value / step) * step if step > 0 else value


class EmergencyStudio:
    def __init__(self, session, library: EquipmentLibrary | None = None) -> None:  # type: ignore[no-untyped-def]
        self.session = session
        self.editor = VehicleEditor(session)
        self._library = library

    # --- Accès -----------------------------------------------------------------------
    @property
    def library(self) -> EquipmentLibrary:
        if self._library is None:
            self._library = EquipmentLibrary()
            self._library.ensure_builtins()
        return self._library

    @property
    def scene(self):  # type: ignore[no-untyped-def]
        return self.session.scene

    def state(self) -> StudioState:
        return StudioState.from_dict(self.scene.documents.get(DOC_KEY))

    def variant(self, variant_id: str | None = None, state: StudioState | None = None) -> Variant:
        state = state or self.state()
        found = state.variant(variant_id) if variant_id else state.active_variant
        if found is None:
            raise EquipmentError("Aucune variante d'urgence : créez-en une d'abord.")
        return found

    def _doc(self, state: StudioState, label: str) -> SetDocument:
        before = copy.deepcopy(self.scene.documents.get(DOC_KEY))
        return SetDocument(DOC_KEY, before, state.to_dict(), label)

    def _push(self, commands: list[Command], state: StudioState, label: str) -> None:
        """Commandes de scène + document, en une seule étape d'historique."""
        self.session.stack.push(CompositeCommand([*commands, self._doc(state, label)], label))

    def _save(self, state: StudioState, label: str) -> None:
        self.session.stack.push(self._doc(state, label))

    def default_profile(self) -> str:
        return model.VEHICLE_TYPE_PROFILE.get(self.session.project.vehicle_type.value, "sedan")

    # --- Véhicule de base et surfaces ----------------------------------------------------
    def base_mesh_ids(self) -> list[str]:
        """Maillages du véhicule de base (hors variantes d'urgence)."""
        set_id = self.state().set_id
        return [
            n.id
            for n in self.scene.mesh_nodes()
            if not (set_id and set_id in self.scene and self.scene.is_ancestor(set_id, n.id))
        ]

    def vehicle_bounds(self) -> tuple[np.ndarray, np.ndarray]:
        bounds = self.session.world_bounds(self.base_mesh_ids(), only_visible=False)
        if bounds is None:
            raise EquipmentError("Aucun véhicule dans la scène : importez d'abord un véhicule.")
        return bounds

    def surface_hit(self, origin, direction, node_ids: Iterable[str] | None = None):  # type: ignore[no-untyped-def]
        """Premier point touché sur le véhicule de base : ``(point, normale)`` ou ``None``."""
        origin = np.asarray(origin, np.float64)
        direction = _unit(direction)
        best = None
        for node_id in node_ids if node_ids is not None else self.base_mesh_ids():
            node = self.scene.nodes.get(node_id)
            mesh = self.session.geometry_for(node) if node is not None else None
            if mesh is None or not self.scene.effective_visible(node_id):
                continue
            world = self.scene.world_matrix(node_id)
            inverse = np.linalg.inv(world)
            hit = editmesh.ray_triangle(
                inverse[:3, :3] @ origin + inverse[:3, 3], inverse[:3, :3] @ direction, mesh
            )
            if hit is None:
                continue
            face, _t = hit
            tri = mathutils.transform_points(world, mesh.positions[mesh.indices[face]].astype(np.float64))
            point_on = self._ray_plane(origin, direction, tri)
            if point_on is None:
                continue
            distance = float(np.dot(point_on - origin, direction))
            if best is None or distance < best[0]:
                normal = _unit(np.cross(tri[1] - tri[0], tri[2] - tri[0]))
                if float(normal @ direction) > 0:
                    normal = -normal
                best = (distance, point_on, normal)
        return None if best is None else (best[1], best[2])

    @staticmethod
    def _ray_plane(origin: np.ndarray, direction: np.ndarray, tri: np.ndarray) -> np.ndarray | None:
        normal = np.cross(tri[1] - tri[0], tri[2] - tri[0])
        denom = float(normal @ direction)
        if abs(denom) < 1e-12:
            return None
        t = float(normal @ (tri[0] - origin)) / denom
        return origin + direction * t if t > 0 else None

    def frame(self) -> dict:
        """Repère monde du véhicule : haut, avant, droite (d'après les axes du projet)."""
        axes = self.editor.axes
        up = np.zeros(3)
        up[axes.up_axis] = 1.0
        forward = np.zeros(3)
        forward[axes.longitudinal_axis] = axes.forward_sign
        return {"up": up, "forward": forward, "right": np.cross(forward, up), "axes": axes}

    def zone_point(self, zone: Zone) -> tuple[np.ndarray, np.ndarray]:
        """Point et normale d'une zone (projetés sur la carrosserie si la zone est extérieure)."""
        bmin, bmax = self.vehicle_bounds()
        frame = self.frame()
        axes = frame["axes"]
        center, half = (bmin + bmax) / 2, (bmax - bmin) / 2
        point = center.copy()
        lat, up, lon = axes.lateral_axis, axes.up_axis, axes.longitudinal_axis
        point[lat] = center[lat] + zone.lateral * half[lat] * axes.right_sign
        point[up] = bmin[up] + zone.up * (bmax[up] - bmin[up])
        point[lon] = center[lon] + zone.longitudinal * half[lon] * axes.forward_sign
        normals = {
            "up": frame["up"],
            "down": -frame["up"],
            "front": frame["forward"],
            "rear": -frame["forward"],
            "right": frame["right"],
            "left": -frame["right"],
        }
        normal = normals.get(zone.normal, frame["up"])
        if zone.interior:
            return point, normal
        reach = float(np.max(bmax - bmin))
        hit = self.surface_hit(point + normal * reach, -normal)
        return (hit[0], hit[1]) if hit is not None else (point, normal)

    def placement(
        self,
        component: LibraryComponent,
        parent_id: str | None,
        zone: Zone | None = None,
        point=None,  # type: ignore[no-untyped-def]
        normal=None,  # type: ignore[no-untyped-def]
        align_to_surface: bool = True,
        yaw: float = 0.0,
    ) -> Placement:
        """Transformation d'un équipement posé sur une zone ou sur un point de la carrosserie."""
        frame = self.frame()
        face = zone.normal if zone else "up"
        if point is None:
            if zone is None:  # au-dessus du centre du véhicule
                bmin, bmax = self.vehicle_bounds()
                point, normal = (bmin + bmax) / 2, frame["up"]
                point[frame["axes"].up_axis] = bmax[frame["axes"].up_axis]
            else:
                point, normal = self.zone_point(zone)
        point = np.asarray(point, np.float64)
        normal = _unit(normal if normal is not None else frame["up"])
        if face in ("up", "down"):
            up = normal if align_to_surface and float(normal @ frame["up"]) > 0.3 else frame["up"]
            forward = frame["forward"]
        else:
            up = frame["up"]
            forward = {
                "front": frame["forward"],
                "rear": -frame["forward"],
                "right": frame["right"],
                "left": -frame["right"],
            }[face]
        rotation = np.eye(4)
        rotation[:3, :3] = orientation(up, forward) @ mathutils.rotation_euler_xyz((0.0, yaw, 0.0))[:3, :3]
        bmin_local, bmax_local = self.library.preview_mesh(component).bounds
        if face in ("up", "down") or (zone is not None and zone.interior):
            contact = np.array([0.0, float(bmin_local[1]), 0.0])  # base posée sur la surface
        else:
            contact = np.array([0.0, 0.0, float(bmax_local[2])])  # face arrière contre la carrosserie
        world = mathutils.translation(point) @ rotation @ mathutils.translation(-contact)
        parent_world = self.scene.world_matrix(parent_id) if parent_id else np.eye(4)
        return Placement(decompose(np.linalg.inv(parent_world) @ world), world, zone.key if zone else None)

    # --- Variantes -------------------------------------------------------------------
    def _activation(self, state: StudioState, target_id: str | None) -> list[Command]:
        """Visibilité des racines et surcharges de matériaux pour activer ``target_id``."""
        commands: list[Command] = []
        visibility = {}
        for variant in state.variants:
            node = self.scene.get(variant.root_id)
            if node is not None and node.visible != (variant.id == target_id):
                visibility[node.id] = (node.visible, variant.id == target_id)
        if visibility:
            commands.append(SetNodeField("visible", visibility, "Variante active"))
        target = state.variant(target_id)
        desired: dict[str, str | None] = dict(state.base_materials)
        for node_id, material_id in (target.material_overrides if target else {}).items():
            if node_id in self.scene:
                state.base_materials.setdefault(node_id, self.scene.nodes[node_id].material_id)
                desired[node_id] = material_id
        materials = {
            node_id: (self.scene.nodes[node_id].material_id, material_id)
            for node_id, material_id in desired.items()
            if node_id in self.scene and self.scene.nodes[node_id].material_id != material_id
        }
        if materials:
            commands.append(SetNodeField("material_id", materials, "Matériaux de la variante"))
        state.active = target_id
        return commands

    def create_variant(self, name: str, service: str = "lspd", profile: str | None = None) -> str:
        """Crée une variante non destructive (groupes et motif par défaut) et l'active."""
        if not self.base_mesh_ids():
            raise EquipmentError("Importez d'abord un véhicule compatible.")
        state = self.state()
        commands: list[Command] = []
        if state.set_id is None or state.set_id not in self.scene:
            parent = next((n.id for n in self.scene.roots() if n.kind is NodeKind.MODEL), None)
            group = SceneNode(
                "Variantes d'urgence",
                NodeKind.GROUP,
                extra={"variant_set": {"kind": "emergency"}, "component": {"category": "accessoires"}},
            )
            commands.append(InsertNodes([group.snapshot()], [(group.id, parent, None)]))
            state.set_id = group.id
        variant_id = new_id("var-")
        root = SceneNode(
            self.scene.unique_name(name.strip() or "Variante"),
            NodeKind.GROUP,
            extra={"emergency_variant": variant_id, "component": {"category": "accessoires"}},
        )
        commands.append(InsertNodes([root.snapshot()], [(root.id, state.set_id, None)]))
        variant = Variant(variant_id, root.name, service, profile or self.default_profile(), root.id)
        variant.groups = [LightGroup(new_id("grp-"), model.GROUP_KINDS[k], k) for k in DEFAULT_GROUPS]
        kinds = {g.kind: g.id for g in variant.groups}
        pattern = build_pattern("alternate", [kinds["left"], kinds["right"]], 110)
        variant.patterns.append(pattern)
        variant.active_pattern = pattern.id
        variant.interior_preset = model.service(service).interior_preset
        variant.livery = LiveryData(unit_id=f"{model.service(service).unit_prefix}-01".strip("-"))
        state.variants.append(variant)
        commands += self._activation(state, variant_id)  # la nouvelle racine est visible à la création
        self._push(commands, state, f"Variante « {root.name} »")
        self.session.selection.set([root.id])
        return variant_id

    def activate_variant(self, variant_id: str | None) -> None:
        state = self.state()
        if variant_id is not None and state.variant(variant_id) is None:
            raise EquipmentError("Variante introuvable.")
        commands = self._activation(state, variant_id)
        self._push(commands, state, "Variante active")

    def rename_variant(self, variant_id: str, name: str) -> None:
        state = self.state()
        variant = self.variant(variant_id, state)
        name = name.strip()
        if not name:
            raise EquipmentError("Le nom de la variante est vide.")
        variant.name = name
        commands: list[Command] = []
        node = self.scene.get(variant.root_id)
        if node is not None and node.name != name:
            commands.append(SetNodeField("name", {node.id: (node.name, name)}))
        self._push(commands, state, "Renommage de la variante")

    def update_variant(self, variant_id: str, **fields) -> None:  # type: ignore[no-untyped-def]
        """Service, profil, intérieur, paramètres, métadonnées, livrée (dictionnaire)."""
        state = self.state()
        variant = self.variant(variant_id, state)
        for key in ("service", "profile", "interior_preset", "parameters", "metadata"):
            if key in fields and fields[key] is not None:
                setattr(variant, key, copy.deepcopy(fields[key]))
        if fields.get("livery") is not None:
            variant.livery = LiveryData(
                **{k: v for k, v in fields["livery"].items() if k in LiveryData.__dataclass_fields__}
            )
        self._save(state, "Propriétés de la variante")

    def duplicate_variant(self, variant_id: str, name: str | None = None) -> str:
        """Copie complète : équipements, feux, groupes, motifs, sirène, livrée, métadonnées."""
        state = self.state()
        source = self.variant(variant_id, state)
        subtree = self.scene.subtree(source.root_id)
        mapping = {n.id: new_node_id() for n in subtree}
        new_variant_id = new_id("var-")
        snapshots = []
        for position, node in enumerate(subtree):
            snap = node.snapshot()
            snap["id"] = mapping[node.id]
            snap["parent_id"] = state.set_id if position == 0 else mapping[node.parent_id]  # type: ignore[index]
            if position == 0:
                snap["name"] = self.scene.unique_name(name or f"{source.name} (copie)")
                snap["extra"] = {**snap["extra"], "emergency_variant": new_variant_id}
                snap["visible"] = False
            snapshots.append(snap)
        copy_variant = model.variant_from_dict(copy.deepcopy(asdict(source)))
        copy_variant.id = new_variant_id
        copy_variant.name = snapshots[0]["name"]
        copy_variant.root_id = mapping[source.root_id]
        copy_variant.created_at = model.utc_now_iso()
        light_ids = {light.id: new_id("lgt-") for light in copy_variant.lights}
        group_ids = {group.id: new_id("grp-") for group in copy_variant.groups}
        pattern_ids = {pattern.id: new_id("pat-") for pattern in copy_variant.patterns}
        for light in copy_variant.lights:
            light.id = light_ids[light.id]
            light.node_id = mapping.get(light.node_id, light.node_id) if light.node_id else None
        for group in copy_variant.groups:
            group.id = group_ids[group.id]
            group.light_ids = [light_ids[i] for i in group.light_ids if i in light_ids]
        for pattern in copy_variant.patterns:
            pattern.id = pattern_ids[pattern.id]
            for frame in pattern.frames:
                frame.groups = [group_ids[g] for g in frame.groups if g in group_ids]
        copy_variant.active_pattern = pattern_ids.get(source.active_pattern or "")
        for mode in copy_variant.siren.modes:
            mode.pattern_id = pattern_ids.get(mode.pattern_id or "")
        state.variants.append(copy_variant)
        insert = InsertNodes(
            snapshots, [(snapshots[0]["id"], state.set_id, None)], "Duplication de la variante"
        )
        self._push([insert], state, f"Duplication de « {source.name} »")
        return new_variant_id

    def delete_variant(self, variant_id: str) -> None:
        """Supprime une variante ; elle reste restaurable (corbeille) et annulable."""
        state = self.state()
        variant = self.variant(variant_id, state)
        snapshots = (
            [n.snapshot() for n in self.scene.subtree(variant.root_id)]
            if variant.root_id in self.scene
            else []
        )
        state.trash.append(
            {"variant": asdict(variant), "snapshots": snapshots, "deleted_at": model.utc_now_iso()}
        )
        state.variants = [v for v in state.variants if v.id != variant_id]
        commands: list[Command] = []
        if state.active == variant_id:
            commands += self._activation(state, state.variants[0].id if state.variants else None)
        if variant.root_id in self.scene:
            commands.append(RemoveNodes([variant.root_id]))
        self._push(commands, state, f"Suppression de « {variant.name} »")

    def restore_variant(self, index: int = -1) -> str:
        """Restaure une variante supprimée (la plus récente par défaut)."""
        state = self.state()
        if not state.trash:
            raise EquipmentError("Aucune variante supprimée à restaurer.")
        entry = state.trash.pop(index)
        variant = model.variant_from_dict(entry["variant"])
        commands: list[Command] = []
        snapshots = [dict(s) for s in entry.get("snapshots", [])]
        if snapshots and variant.root_id not in self.scene:
            parent = state.set_id if state.set_id in self.scene else None
            snapshots[0]["parent_id"] = parent
            commands.append(InsertNodes(snapshots, [(snapshots[0]["id"], parent, None)]))
        state.variants.append(variant)
        self._push(commands, state, f"Restauration de « {variant.name} »")
        self.activate_variant(variant.id)
        return variant.id

    def equipment_nodes(self, variant: Variant) -> list[SceneNode]:
        if variant.root_id not in self.scene:
            return []
        return [n for n in self.scene.walk(variant.root_id) if "emergency_equipment" in n.extra]

    def compare_variants(self, first_id: str, second_id: str) -> dict:
        """Différences entre deux variantes (équipements, feux, motifs, sirène, livrée…)."""
        state = self.state()
        a, b = self.variant(first_id, state), self.variant(second_id, state)
        names_a = sorted(n.name for n in self.equipment_nodes(a))
        names_b = sorted(n.name for n in self.equipment_nodes(b))
        livery_a, livery_b = asdict(a.livery), asdict(b.livery)
        return {
            "service": (a.service, b.service),
            "profile": (a.profile, b.profile),
            "equipment_only_first": sorted(set(names_a) - set(names_b)),
            "equipment_only_second": sorted(set(names_b) - set(names_a)),
            "equipment_common": sorted(set(names_a) & set(names_b)),
            "lights": (len(a.lights), len(b.lights)),
            "groups": ([g.name for g in a.groups if g.light_ids], [g.name for g in b.groups if g.light_ids]),
            "patterns": ([p.name for p in a.patterns], [p.name for p in b.patterns]),
            "siren": ([m.tone for m in a.siren.modes], [m.tone for m in b.siren.modes]),
            "materials": (len(a.material_overrides), len(b.material_overrides)),
            "livery": {k: (livery_a[k], livery_b[k]) for k in livery_a if livery_a[k] != livery_b[k]},
            "interior": (a.interior_preset, b.interior_preset),
        }

    def set_material_override(
        self, variant_id: str, node_ids: Iterable[str], material_id: str | None
    ) -> None:
        """Matériau propre à une variante sur des pièces du véhicule de base."""
        state = self.state()
        variant = self.variant(variant_id, state)
        base = set(self.base_mesh_ids())
        targets = [n.id for i in node_ids if i in self.scene for n in self.scene.subtree(i) if n.id in base]
        if not targets:
            raise EquipmentError("Sélectionnez des pièces du véhicule de base.")
        for node_id in targets:
            variant.material_overrides[node_id] = material_id  # type: ignore[assignment]
        commands = self._activation(state, state.active) if state.active == variant_id else []
        self._push(commands, state, "Matériau de la variante")

    # --- Équipements -----------------------------------------------------------------
    def component(self, component_id: str) -> LibraryComponent:
        component = self.library.get(component_id)
        if component is None:
            raise EquipmentError(f"Équipement introuvable dans la bibliothèque : {component_id}.")
        return component

    def check_equipment(
        self, component: LibraryComponent, variant: Variant, state: StudioState | None = None
    ) -> list[str]:
        """Avertissements de compatibilité ; lève ``EquipmentError`` si l'équipement est inutilisable."""
        try:
            meshes = self.library.load_meshes(component)
        except LibraryError as exc:
            raise EquipmentError(f"« {component.name} » est invalide : {exc}") from exc
        if not meshes or not any(m.triangle_count for m in meshes):
            raise EquipmentError(f"« {component.name} » ne contient aucune géométrie.")
        warnings = []
        profile = (state or self.state()).profile(variant.profile)
        if component.compatible_profiles and variant.profile not in component.compatible_profiles:
            warnings.append(
                f"« {component.name} » n'est pas prévu pour le profil {profile.label} : "
                "vérifiez son placement."
            )
        restricted = component.category in model.CATEGORY_ZONES and component.category != "urg_perso"
        if restricted and not profile.zones_for(component.category):
            warnings.append(
                f"Aucune zone du profil {profile.label} n'accueille cette catégorie d'équipement."
            )
        if not component.license or not component.provenance:
            warnings.append(f"Licence ou provenance manquante pour « {component.name} ».")
        return warnings

    def interior_root(self, variant: Variant, commands: list[Command]) -> str:
        """Groupe « Intérieur » de la variante (créé si besoin, ajouté à ``commands``)."""
        for child in self.scene.children(variant.root_id):
            if child.extra.get("emergency_interior"):
                return child.id
        node = SceneNode("Intérieur", NodeKind.GROUP, extra={"emergency_interior": True})
        commands.append(InsertNodes([node.snapshot()], [(node.id, variant.root_id, None)]))
        return node.id

    def _resolve_color(self, color: str, variant: Variant, side_swap: bool = False) -> str:
        colors = model.service(variant.service).light_colors or ("amber", "amber")
        if color.startswith("service_"):
            left, right = colors[0], colors[-1]
            if side_swap:
                left, right = right, left
            return left if color == "service_left" else right
        return color

    def add_equipment(
        self,
        component_id: str,
        zone_key: str | None = None,
        point=None,  # type: ignore[no-untyped-def]
        normal=None,  # type: ignore[no-untyped-def]
        variant_id: str | None = None,
        align_to_surface: bool = True,
        yaw: float = 0.0,
        offset: tuple[float, float, float] | None = None,
    ) -> AddResult:
        """Ajoute un équipement à la variante : placement sur zone ou point, feux et groupes.

        ``offset`` : décalage (latéral, haut, longitudinal) en mètres dans le repère du véhicule.
        """
        state = self.state()
        variant = self.variant(variant_id, state)
        if variant.root_id not in self.scene:
            raise EquipmentError("La racine de la variante est absente de la scène.")
        component = self.component(component_id)
        warnings = self.check_equipment(component, variant, state)
        profile = state.profile(variant.profile)
        zone = profile.zone(zone_key) if zone_key else None
        if zone is None and point is None:
            candidates = profile.zones_for(component.category)
            zone = candidates[0] if candidates else None
            if zone is None and component.category not in ("urg_perso",):
                warnings.append(
                    "Aucune zone adaptée : équipement posé au-dessus du véhicule, à placer manuellement."
                )
        commands: list[Command] = []
        parent = (
            self.interior_root(variant, commands) if zone is not None and zone.interior else variant.root_id
        )
        if commands:  # groupe « Intérieur » inséré avant le calcul de la transformation locale
            commands[0].redo(self.scene)
        try:
            place = self.placement(component, parent, zone, point, normal, align_to_surface, yaw)
        finally:
            if commands:
                commands[0].undo(self.scene)
        if offset is not None:
            frame = self.frame()
            shift = frame["right"] * offset[0] + frame["up"] * offset[1] + frame["forward"] * offset[2]
            # parent « Intérieur » encore absent : groupe à l'identité sous la racine de variante
            parent_world = self.scene.world_matrix(parent if parent in self.scene else variant.root_id)
            place.transform = decompose(
                np.linalg.inv(parent_world) @ mathutils.translation(shift) @ place.world
            )
        payload = self.library.payload(component, self.session.project)
        root = payload.snapshots[0]
        root["transform"] = place.transform.to_dict()
        root["name"] = self.scene.unique_name(component.name)
        root["extra"] = {
            **root["extra"],
            "emergency_equipment": {
                "component_id": component.id,
                "category": component.category,
                "zone": place.zone,
            },
        }
        commands.append(
            InsertNodes(
                payload.snapshots,
                [(payload.root_id, parent, None)],
                meshes=payload.meshes,
                materials=payload.materials,
            )
        )
        light_ids = self._lights_from_emitters(variant, component, payload.root_id, zone)
        self._push(commands, state, f"Ajout de {component.name}")
        self.session.selection.set([payload.root_id])
        return AddResult(payload.root_id, light_ids, warnings + place.warnings)

    def _lights_from_emitters(
        self, variant: Variant, component: LibraryComponent, node_id: str, zone: Zone | None
    ) -> list[str]:
        """Sources de prévisualisation créées depuis les projecteurs déclarés par l'équipement."""
        created = []
        kinds = {g.kind: g for g in variant.groups}
        category_suffix = component.category.split("_", 1)[-1]
        right_side = zone is not None and zone.lateral > 0.5  # équipement unique posé à droite
        swap = right_side and len(component.emitters) == 1
        for emitter in component.emitters:
            light = LightSource(
                new_id("lgt-"),
                f"{component.name} · {emitter.get('name', 'Feu')}",
                node_id,
                [float(v) for v in emitter.get("position", [0, 0, 0])],
                [float(v) for v in emitter.get("rotation", [0, 0, 0])],
                self._resolve_color(str(emitter.get("color", "white")), variant, side_swap=swap),
                intensity=1.0,
                range=float(emitter.get("range", 12.0)),
                angle=float(emitter.get("angle", 90.0)),
            )
            variant.lights.append(light)
            created.append(light.id)
            group_kind = str(emitter.get("group", "secondary"))
            if swap:
                group_kind = {"left": "right", "right": "left"}.get(group_kind, group_kind)
            targets = {group_kind}
            targets.add(CATEGORY_GROUP.get(category_suffix, "secondary"))
            if zone is not None and zone.normal in ("front", "rear"):
                targets.add(zone.normal)
            for kind in targets:
                if kind in kinds:
                    kinds[kind].light_ids.append(light.id)
        return created

    def add_equipment_pair(
        self, component_id: str, zone_key: str, variant_id: str | None = None
    ) -> list[AddResult]:
        """Pose un équipement sur une zone latérale puis sur la zone symétrique (gauche / droite)."""
        state = self.state()
        variant = self.variant(variant_id, state)
        profile = state.profile(variant.profile)
        zone = profile.zone(zone_key)
        if zone is None:
            raise EquipmentError("Zone inconnue pour ce profil.")
        twin_key = zone_key[:-1] + ("r" if zone_key.endswith("l") else "l") if zone.mirror else None
        self.session.stack.begin("Pose symétrique")
        try:
            results = [self.add_equipment(component_id, zone_key, variant_id=variant.id)]
            if twin_key and profile.zone(twin_key):
                results.append(self.add_equipment(component_id, twin_key, variant_id=variant.id))
        except EditError:
            self.session.stack.rollback()
            raise
        self.session.stack.commit()
        return results

    def place_on_surface(
        self, node_id: str, point, normal, align_to_surface: bool = True, yaw: float = 0.0
    ) -> None:  # type: ignore[no-untyped-def]
        """Déplace un équipement placé vers un point de la carrosserie (aligné sur la surface)."""
        node = self.scene.get(node_id)
        info = node.extra.get("emergency_equipment") if node else None
        if node is None or info is None:
            raise EquipmentError("Sélectionnez un équipement placé.")
        component = self.library.get(info.get("component_id", ""))
        if component is None:
            raise EquipmentError(
                "Équipement absent de la bibliothèque : placement par coordonnées seulement."
            )
        place = self.placement(component, node.parent_id, None, point, normal, align_to_surface, yaw)
        self.session.stack.push(
            SetTransforms({node_id: (node.transform.copy(), place.transform)}, "Placement")
        )

    def move_to_zone(self, node_id: str, zone_key: str) -> None:
        node = self.scene.get(node_id)
        info = node.extra.get("emergency_equipment") if node else None
        if node is None or info is None:
            raise EquipmentError("Sélectionnez un équipement placé.")
        variant = self.variant_of(node_id)
        zone = self.state().profile(variant.profile).zone(zone_key)
        component = self.library.get(info.get("component_id", ""))
        if zone is None or component is None:
            raise EquipmentError("Zone ou équipement introuvable.")
        place = self.placement(component, node.parent_id, zone)
        extra = {**node.extra, "emergency_equipment": {**info, "zone": zone.key}}
        self.session.stack.push(
            CompositeCommand(
                [
                    SetTransforms({node_id: (node.transform.copy(), place.transform)}),
                    SetNodeExtra({node_id: (dict(node.extra), extra)}),
                ],
                f"Placement : {zone.label}",
            )
        )

    def snap(self, node_id: str, step: float = 0.05, angle_step: float = 15.0) -> None:
        """Aimantation : position sur une grille, rotation par incréments."""
        node = self.scene.get(node_id)
        if node is None:
            raise EquipmentError("Élément introuvable.")
        snapped = Transform(
            [snap_value(v, step) for v in node.transform.translation],
            [snap_value(v, angle_step) for v in node.transform.rotation],
            list(node.transform.scale),
        )
        self.session.set_transforms({node_id: snapped}, "Aimantation")

    def rotate_step(self, node_id: str, degrees: float) -> None:
        """Rotation par incrément autour de l'axe vertical du véhicule (pivot de l'équipement)."""
        node = self.scene.get(node_id)
        if node is None:
            raise EquipmentError("Élément introuvable.")
        frame = self.frame()
        world = self.scene.world_matrix(node_id)
        pivot = world[:3, 3]
        rotation = np.eye(4)
        rotation[:3, :3] = _axis_angle(frame["up"], np.radians(degrees))
        new_world = mathutils.translation(pivot) @ rotation @ mathutils.translation(-pivot) @ world
        local = decompose(np.linalg.inv(self.scene.parent_world_matrix(node_id)) @ new_world)
        self.session.stack.push(
            SetTransforms({node_id: (node.transform.copy(), local)}, f"Rotation {degrees:+.0f}°")
        )

    def variant_of(self, node_id: str) -> Variant:
        state = self.state()
        for variant in state.variants:
            if node_id == variant.root_id or (
                variant.root_id in self.scene and self.scene.is_ancestor(variant.root_id, node_id)
            ):
                return variant
        raise EquipmentError("Cet élément n'appartient à aucune variante d'urgence.")

    def mirror_equipment(self, node_ids: Iterable[str]) -> list[str]:
        """Duplication miroir (plan de symétrie du véhicule), feux recopiés et côtés inversés."""
        ids = [i for i in node_ids if i in self.scene and "emergency_equipment" in self.scene.nodes[i].extra]
        if not ids:
            raise EquipmentError("Sélectionnez un équipement placé.")
        variant = self.variant_of(ids[0])
        self.session.stack.begin("Duplication miroir")
        try:
            created = self.editor.mirror_duplicate(ids)
            state = self.state()
            variant = self.variant(variant.id, state)
            kinds = {g.kind: g for g in variant.groups}
            swap = {"left": "right", "right": "left"}
            for source_id, copy_id in zip(ids, created, strict=True):
                for light in [x for x in variant.lights if x.node_id == source_id]:
                    mirrored = LightSource(**{**asdict(light), "id": new_id("lgt-"), "node_id": copy_id})
                    mirrored.position = [-light.position[0], light.position[1], light.position[2]]
                    mirrored.name = light.name + " (miroir)"
                    variant.lights.append(mirrored)
                    for group in list(variant.groups):
                        if light.id in group.light_ids:
                            target = kinds.get(swap.get(group.kind, group.kind), group)
                            target.light_ids.append(mirrored.id)
            self._save(state, "Feux recopiés en miroir")
        except EditError:
            self.session.stack.rollback()
            raise
        self.session.stack.commit()
        return created

    def remove_equipment(self, node_ids: Iterable[str]) -> int:
        ids = [i for i in node_ids if i in self.scene]
        if not ids:
            return 0
        state = self.state()
        removed = {n.id for i in ids for n in self.scene.subtree(i)}
        for variant in state.variants:
            gone = {light.id for light in variant.lights if light.node_id in removed}
            variant.lights = [light for light in variant.lights if light.id not in gone]
            for group in variant.groups:
                group.light_ids = [i for i in group.light_ids if i not in gone]
        self._push([RemoveNodes(ids)], state, "Suppression d'équipements")
        return len(ids)

    def collisions(self, variant_id: str | None = None, tolerance: float = 0.01) -> list[str]:
        """Contrôle géométrique **approximatif** (boîtes englobantes) des équipements."""
        variant = self.variant(variant_id)
        nodes = self.equipment_nodes(variant)
        boxes = []
        for node in nodes:
            bounds = self.session.world_bounds([node.id], only_visible=False)
            if bounds is not None:
                boxes.append((node, bounds))
        issues = []
        for i, (a, (amin, amax)) in enumerate(boxes):
            for b, (bmin, bmax) in boxes[i + 1 :]:
                overlap = np.minimum(amax, bmax) - np.maximum(amin, bmin)
                if np.all(overlap > tolerance):
                    issues.append(f"« {a.name} » et « {b.name} » se chevauchent (boîtes englobantes).")
        if boxes:
            vmin, vmax = self.vehicle_bounds()
            margin = 0.6
            for node, (bmin, bmax) in boxes:
                if np.any(bmin > vmax + margin) or np.any(bmax < vmin - margin):
                    issues.append(f"« {node.name} » est éloigné du véhicule (> {margin} m).")
        return issues

    # --- Intérieur ---------------------------------------------------------------------
    def apply_interior_preset(self, preset: str, variant_id: str | None = None) -> list[AddResult]:
        """Pose une configuration intérieure (Police, EMS, Fire) en une seule étape."""
        variant = self.variant(variant_id)
        items = INTERIOR_PRESETS.get(preset)
        custom = next((p for p in self.state().interior_presets if p.get("name") == preset), None)
        if items is None and custom is None:
            raise EquipmentError("Configuration intérieure inconnue.")
        profile = self.state().profile(variant.profile)
        results: list[AddResult] = []
        self.session.stack.begin(f"Intérieur {INTERIOR_LABELS.get(preset, preset)}")
        try:
            if custom is not None:
                for item in custom.get("items", []):
                    result = self.add_equipment(item["component_id"], item.get("zone"), variant_id=variant.id)
                    node = self.scene.nodes[result.node_id]
                    self.session.set_transforms(
                        {node.id: Transform.from_dict(item["transform"])}, "Intérieur"
                    )
                    results.append(result)
            else:
                for item in items or ():
                    component_id, zone_key = item[0], item[1]
                    if profile.zone(zone_key) is None:
                        continue  # zone absente de ce profil (ex. cellule sur une berline)
                    if self.library.get(component_id) is None:
                        continue
                    offset = item[2] if len(item) > 2 else None
                    results.append(
                        self.add_equipment(component_id, zone_key, variant_id=variant.id, offset=offset)
                    )
            state = self.state()
            self.variant(variant.id, state).interior_preset = preset
            self._save(state, "Configuration intérieure")
        except EditError:
            self.session.stack.rollback()
            raise
        self.session.stack.commit()
        return results

    def save_interior_preset(self, name: str, variant_id: str | None = None) -> dict:
        """Enregistre l'intérieur actuel de la variante comme preset réutilisable."""
        variant = self.variant(variant_id)
        interior = next(
            (c for c in self.scene.children(variant.root_id) if c.extra.get("emergency_interior")), None
        )
        if interior is None:
            raise EquipmentError("Cette variante n'a pas d'équipement intérieur.")
        items = [
            {
                "component_id": n.extra["emergency_equipment"].get("component_id"),
                "zone": n.extra["emergency_equipment"].get("zone"),
                "transform": n.transform.to_dict(),
            }
            for n in self.scene.children(interior.id)
            if "emergency_equipment" in n.extra
        ]
        preset = {"name": name.strip() or "Intérieur personnalisé", "items": items}
        state = self.state()
        state.interior_presets = [p for p in state.interior_presets if p.get("name") != preset["name"]] + [
            preset
        ]
        self._save(state, "Preset d'intérieur")
        return preset

    # --- Feux et groupes --------------------------------------------------------------
    def add_light(
        self,
        node_id: str | None,
        name: str = "Feu",
        position=(0.0, 0.0, 0.0),  # type: ignore[no-untyped-def]
        color: str = "red",
        group_kind: str | None = None,
        variant_id: str | None = None,
    ) -> str:
        state = self.state()
        variant = self.variant(variant_id, state)
        if node_id is not None and node_id not in self.scene:
            raise EquipmentError("Équipement porteur introuvable.")
        if color not in model.LIGHT_COLORS:
            raise EquipmentError(f"Couleur inconnue : {color}.")
        light = LightSource(new_id("lgt-"), name, node_id, [float(v) for v in position], color=color)
        variant.lights.append(light)
        group = next((g for g in variant.groups if g.kind == group_kind), None)
        if group is not None:
            group.light_ids.append(light.id)
        self._save(state, "Source lumineuse")
        return light.id

    def update_light(self, light_id: str, variant_id: str | None = None, **fields) -> None:  # type: ignore[no-untyped-def]
        state = self.state()
        variant = self.variant(variant_id, state)
        light = variant.light(light_id)
        if light is None:
            raise EquipmentError("Source lumineuse introuvable.")
        if "color" in fields and fields["color"] not in model.LIGHT_COLORS and fields["color"] != "custom":
            raise EquipmentError("Couleur inconnue.")
        for key, value in fields.items():
            if key in LightSource.__dataclass_fields__ and key != "id":
                setattr(light, key, copy.deepcopy(value))
        light.intensity = max(0.0, min(float(light.intensity), 10.0))
        light.range = max(0.1, float(light.range))
        light.angle = max(1.0, min(float(light.angle), 360.0))
        self._save(state, "Source lumineuse")

    def remove_light(self, light_id: str, variant_id: str | None = None) -> None:
        state = self.state()
        variant = self.variant(variant_id, state)
        variant.lights = [light for light in variant.lights if light.id != light_id]
        for group in variant.groups:
            group.light_ids = [i for i in group.light_ids if i != light_id]
        self._save(state, "Suppression d'une source lumineuse")

    def create_group(
        self, name: str, kind: str = "custom", light_ids: Iterable[str] = (), variant_id: str | None = None
    ) -> str:
        state = self.state()
        variant = self.variant(variant_id, state)
        known = {light.id for light in variant.lights}
        group = LightGroup(
            new_id("grp-"), name.strip() or "Groupe", kind if kind in model.GROUP_KINDS else "custom"
        )
        group.light_ids = [i for i in light_ids if i in known]
        variant.groups.append(group)
        self._save(state, "Groupe lumineux")
        return group.id

    def set_group_lights(
        self, group_id: str, light_ids: Iterable[str], variant_id: str | None = None
    ) -> None:
        state = self.state()
        variant = self.variant(variant_id, state)
        group = variant.group(group_id)
        if group is None:
            raise EquipmentError("Groupe introuvable.")
        known = {light.id for light in variant.lights}
        group.light_ids = list(dict.fromkeys(i for i in light_ids if i in known))
        self._save(state, "Groupe lumineux")

    def delete_group(self, group_id: str, variant_id: str | None = None) -> None:
        state = self.state()
        variant = self.variant(variant_id, state)
        variant.groups = [g for g in variant.groups if g.id != group_id]
        for pattern in variant.patterns:
            for frame in pattern.frames:
                frame.groups = [g for g in frame.groups if g != group_id]
        self._save(state, "Suppression d'un groupe")

    # --- Motifs ---------------------------------------------------------------------------
    def add_pattern(
        self,
        preset: str,
        group_ids: Iterable[str] | None = None,
        step_ms: int = 100,
        name: str | None = None,
        variant_id: str | None = None,
    ) -> str:
        state = self.state()
        variant = self.variant(variant_id, state)
        groups = list(group_ids) if group_ids else []
        if not groups:
            kinds = {g.kind: g.id for g in variant.groups}
            if preset == "progressive":
                groups = [g.id for g in variant.groups if g.light_ids] or [
                    kinds.get("left", ""),
                    kinds.get("right", ""),
                ]
            else:
                groups = [kinds.get("left", ""), kinds.get("right", "")]
        valid = {g.id for g in variant.groups}
        if not any(g in valid for g in groups):
            raise EquipmentError("Le motif doit utiliser au moins un groupe lumineux de la variante.")
        pattern = build_pattern(preset, [g for g in groups if g in valid], step_ms, name)
        variant.patterns.append(pattern)
        variant.active_pattern = pattern.id
        self._save(state, f"Motif « {pattern.name} »")
        return pattern.id

    def update_pattern(
        self,
        pattern_id: str,
        frames: list[PatternFrame] | None = None,
        name: str | None = None,
        variant_id: str | None = None,
    ) -> None:
        state = self.state()
        variant = self.variant(variant_id, state)
        pattern = variant.pattern(pattern_id)
        if pattern is None:
            raise EquipmentError("Motif introuvable.")
        if frames is not None:
            valid = {g.id for g in variant.groups}
            cleaned = [PatternFrame(int(f.duration_ms), [g for g in f.groups if g in valid]) for f in frames]
            if not cleaned or any(f.duration_ms <= 0 for f in cleaned):
                raise EquipmentError("Chaque étape du motif doit durer plus de 0 ms.")
            pattern.frames = cleaned
            pattern.preset = "custom" if pattern.preset not in model.PATTERN_PRESETS else pattern.preset
        if name:
            pattern.name = name.strip()
        self._save(state, "Motif lumineux")

    def duplicate_pattern(self, pattern_id: str, variant_id: str | None = None) -> str:
        state = self.state()
        variant = self.variant(variant_id, state)
        pattern = variant.pattern(pattern_id)
        if pattern is None:
            raise EquipmentError("Motif introuvable.")
        copy_pattern = Pattern(
            new_id("pat-"), f"{pattern.name} (copie)", copy.deepcopy(pattern.frames), pattern.preset
        )
        variant.patterns.append(copy_pattern)
        self._save(state, "Duplication du motif")
        return copy_pattern.id

    def delete_pattern(self, pattern_id: str, variant_id: str | None = None) -> None:
        state = self.state()
        variant = self.variant(variant_id, state)
        variant.patterns = [p for p in variant.patterns if p.id != pattern_id]
        if variant.active_pattern == pattern_id:
            variant.active_pattern = variant.patterns[0].id if variant.patterns else None
        for mode in variant.siren.modes:
            if mode.pattern_id == pattern_id:
                mode.pattern_id = None
        self._save(state, "Suppression du motif")

    def set_active_pattern(self, pattern_id: str | None, variant_id: str | None = None) -> None:
        state = self.state()
        variant = self.variant(variant_id, state)
        if pattern_id is not None and variant.pattern(pattern_id) is None:
            raise EquipmentError("Motif introuvable.")
        variant.active_pattern = pattern_id
        self._save(state, "Motif actif")

    def save_pattern_preset(self, pattern_id: str, variant_id: str | None = None) -> dict:
        """Preset réutilisable : les groupes sont mémorisés par **type** (gauche, droite…)."""
        state = self.state()
        variant = self.variant(variant_id, state)
        pattern = variant.pattern(pattern_id)
        if pattern is None:
            raise EquipmentError("Motif introuvable.")
        kinds = {g.id: g.kind for g in variant.groups}
        preset = {
            "name": pattern.name,
            "frames": [
                {"duration_ms": f.duration_ms, "kinds": [kinds.get(g, "custom") for g in f.groups]}
                for f in pattern.frames
            ],
        }
        state.pattern_presets = [p for p in state.pattern_presets if p["name"] != preset["name"]] + [preset]
        self._save(state, "Preset de motif")
        return preset

    def apply_pattern_preset(self, name: str, variant_id: str | None = None) -> str:
        state = self.state()
        variant = self.variant(variant_id, state)
        preset = next((p for p in state.pattern_presets if p["name"] == name), None)
        if preset is None:
            raise EquipmentError("Preset de motif introuvable.")
        by_kind = {g.kind: g.id for g in variant.groups}
        frames = [
            PatternFrame(int(f["duration_ms"]), [by_kind[k] for k in f.get("kinds", []) if k in by_kind])
            for f in preset["frames"]
        ]
        pattern = Pattern(new_id("pat-"), preset["name"], frames, "custom")
        variant.patterns.append(pattern)
        variant.active_pattern = pattern.id
        self._save(state, f"Motif « {pattern.name} »")
        return pattern.id

    # --- Prévisualisation -------------------------------------------------------------
    def lights_on(
        self, variant: Variant, t_ms: float, speed: float = 1.0, pattern_id: str | None = None
    ) -> set[str]:
        """Sources allumées à l'instant t (motif actif ou choisi) : déterministe."""
        pattern = variant.pattern(pattern_id or variant.active_pattern)
        if pattern is None:
            return set()
        groups = {g.id: g for g in variant.groups}
        on: set[str] = set()
        for group_id in pattern.groups_on(t_ms, speed):
            group = groups.get(group_id)
            if group is not None:
                on.update(group.light_ids)
        enabled = {light.id for light in variant.lights if light.enabled and light.visible}
        return on & enabled

    def light_world(self, light: LightSource) -> tuple[np.ndarray, np.ndarray] | None:
        """Position et direction monde d'une source (direction : -Z local de la source)."""
        if light.node_id is not None and light.node_id not in self.scene:
            return None
        base = self.scene.world_matrix(light.node_id) if light.node_id else np.eye(4)
        local = mathutils.trs(light.position, light.rotation, [1.0, 1.0, 1.0])
        world = base @ local
        direction = _unit(world[:3, :3] @ np.array([0.0, 0.0, -1.0]))
        return world[:3, 3], direction

    # --- Sirènes ------------------------------------------------------------------------
    def set_siren(self, profile: SirenProfile, variant_id: str | None = None) -> None:
        state = self.state()
        variant = self.variant(variant_id, state)
        patterns = {p.id for p in variant.patterns}
        for mode in profile.modes:
            if mode.pattern_id and mode.pattern_id not in patterns:
                raise EquipmentError(f"Le mode « {mode.label} » référence un motif inexistant.")
            if mode.tone not in model.SIREN_TONES and not mode.tone.startswith("custom:"):
                raise EquipmentError(f"Tonalité inconnue : {mode.tone}.")
        variant.siren = copy.deepcopy(profile)
        self._save(state, "Profil de sirène")

    def add_siren_mode(
        self, label: str, tone: str = "wail", pattern_id: str | None = None, variant_id: str | None = None
    ) -> None:
        variant = self.variant(variant_id)
        profile = copy.deepcopy(variant.siren)
        profile.modes.append(SirenMode(new_id("mode-"), label, tone, pattern_id))
        self.set_siren(profile, variant.id)

    # --- Profils personnalisés ---------------------------------------------------------
    def save_custom_profile(
        self, key: str, label: str, base_profile: str = "sedan", zones: list[dict] | None = None
    ) -> str:
        """Profil de véhicule personnalisé (zones copiées d'un profil existant puis modifiables)."""
        state = self.state()
        base = state.profile(base_profile)
        key = key.strip().lower().replace(" ", "_") or "profil"
        if key in model.PROFILES_BY_KEY:
            raise EquipmentError("Ce nom est réservé à un profil intégré.")
        data = {
            "key": key,
            "label": label.strip() or key,
            "notes": f"Créé à partir du profil {base.label}",
            "zones": zones if zones is not None else [asdict(z) for z in base.zones],
        }
        state.custom_profiles = [p for p in state.custom_profiles if p.get("key") != key] + [data]
        self._save(state, "Profil de véhicule")
        return key

    # --- Contrôles ---------------------------------------------------------------------
    def lore_report(self, variant_id: str | None = None) -> list[tuple[str, str]]:
        """Contrôle Lore Friendly et provenance (aide, sans valeur juridique)."""
        variant = self.variant(variant_id)
        issues: list[tuple[str, str]] = [("info", model.LORE_DISCLAIMER)]
        texts = [
            ("variante", variant.name),
            ("livrée", variant.livery.livery_name),
            ("indicatif", variant.livery.callsign),
        ]
        texts += [("marquage", m) for m in variant.livery.markings]
        for node in self.equipment_nodes(variant):
            info = node.extra.get("component", {})
            texts.append(("équipement", node.name))
            texts.append(("provenance", str(info.get("provenance", ""))))
            if not info.get("license"):
                issues.append(("warning", f"Licence non renseignée : « {node.name} »."))
            if not info.get("provenance"):
                issues.append(("warning", f"Provenance non renseignée : « {node.name} »."))
        for logo in variant.livery.logos:
            if not logo.get("license"):
                issues.append(("warning", f"Logo sans licence déclarée : « {logo.get('name', '?')} »."))
        for kind, text in texts:
            for brand in model.real_brand_hits(text or ""):
                issues.append(("warning", f"Marque réelle possible « {brand} » dans {kind} : « {text} »."))
        if len(issues) == 1:
            issues.append(("ok", "Aucun problème détecté par les contrôles automatiques."))
        return issues

    def diagnostics(self, variant_id: str | None = None) -> list[tuple[str, str]]:
        variant = self.variant(variant_id)
        grouped = {i for g in variant.groups for i in g.light_ids}
        active = variant.pattern(variant.active_pattern)
        active_name = active.name if active else "aucun"
        enabled = [light for light in variant.lights if light.enabled and light.visible]
        report = [
            (
                "info",
                f"{len(self.equipment_nodes(variant))} équipement(s), "
                f"{len(variant.lights)} source(s) lumineuse(s)",
            ),
            (
                "info",
                f"{len(variant.patterns)} motif(s) ; motif actif : {active_name}",
            ),
        ]
        orphan = [light.name for light in variant.lights if light.id not in grouped]
        if orphan:
            report.append(
                ("warning", f"{len(orphan)} source(s) hors de tout groupe (jamais allumées par un motif).")
            )
        missing = [
            light.name for light in variant.lights if light.node_id and light.node_id not in self.scene
        ]
        if missing:
            report.append(("warning", f"{len(missing)} source(s) rattachée(s) à un équipement supprimé."))
        if len(enabled) > MAX_PREVIEW_LIGHTS:
            report.append(
                ("warning", f"Prévisualisation limitée aux {MAX_PREVIEW_LIGHTS} premières sources.")
            )
        empty = [p.name for p in variant.patterns if not any(f.groups for f in p.frames)]
        if empty:
            report.append(("warning", f"Motif(s) sans aucun groupe allumé : {', '.join(empty)}."))
        report += [("warning", issue) for issue in self.collisions(variant.id)]
        return report


def _axis_angle(axis, angle: float) -> np.ndarray:  # type: ignore[no-untyped-def]
    x, y, z = _unit(axis)
    c, s = np.cos(angle), np.sin(angle)
    return np.array(
        [
            [c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
            [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
            [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)],
        ]
    )
