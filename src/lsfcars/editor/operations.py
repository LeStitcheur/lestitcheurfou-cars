"""Opérations du Vehicle Editor (géométrie, composants, roues, habitacle, ancrages, matériaux).

Toutes les modifications passent par l'historique de la ``ProjectSession`` (annulables) ;
une opération composée forme une seule étape. Rien ici ne dépend de Qt.

Prévisualisation : ``preview(command)`` applique une commande à la scène sans l'inscrire dans
l'historique ; ``confirm()`` l'y inscrit, ``cancel()`` la défait.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

import numpy as np

from lsfcars.editor import vehicle
from lsfcars.editor.vehicle import VehicleAxes
from lsfcars.scene import editmesh, mathutils
from lsfcars.scene.commands import (
    AddMaterial,
    AssignMaterial,
    Command,
    CompositeCommand,
    InsertNodes,
    MoveNodes,
    RemoveNodes,
    SetGeometry,
    SetMaterialProperties,
    SetNodeExtra,
    SetNodeField,
    SetTransforms,
)
from lsfcars.scene.editmesh import EditError, EditResult
from lsfcars.scene.graph import NodeKind, SceneNode, new_node_id
from lsfcars.scene.material_presets import preset as material_preset
from lsfcars.scene.materials import Material
from lsfcars.scene.mesh import MeshData
from lsfcars.scene.transform import Transform, decompose


def new_mesh_key() -> str:
    return f"local-{uuid.uuid4().hex}"


@dataclass
class Payload:
    """Sous-arbre prêt à insérer (bibliothèque, duplication, remplacement)."""

    snapshots: list[dict]  # parents avant enfants ; la racine en premier
    meshes: dict[str, MeshData] = field(default_factory=dict)
    materials: list[Material] = field(default_factory=list)

    @property
    def root_id(self) -> str:
        return self.snapshots[0]["id"]


@dataclass
class ReplaceOptions:
    keep_transform: bool = True
    align_pivot: bool = True
    fit_dimensions: bool = False
    keep_materials: bool = True
    keep_parent: bool = True
    keep_anchors: bool = True
    allow_bone_change: bool = False  # ne jamais modifier les os GTA V sans validation


@dataclass
class ReplaceReport:
    target_name: str
    source_name: str
    target_size: np.ndarray | None = None
    source_size: np.ndarray | None = None
    scale: float = 1.0
    materials: str = ""
    anchors_moved: int = 0
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class VehicleEditor:
    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        self.session = session
        self._preview: Command | None = None

    # --- Accès -------------------------------------------------------------------
    @property
    def scene(self):  # type: ignore[no-untyped-def]
        return self.session.scene

    @property
    def stack(self):  # type: ignore[no-untyped-def]
        return self.session.stack

    @property
    def axes(self) -> VehicleAxes:
        return VehicleAxes.from_project(self.session.project.editor)

    def set_axes(self, axes: VehicleAxes) -> None:
        self.session.project.editor = {**self.session.project.editor, **axes.to_dict()}
        self.session.mark_meta_dirty()

    def _node(self, node_id: str) -> SceneNode:
        node = self.scene.get(node_id)
        if node is None:
            raise EditError("Élément introuvable dans la scène.")
        return node

    def _check_editable(self, node_id: str) -> SceneNode:
        node = self._node(node_id)
        if self.scene.effective_locked(node_id):
            raise EditError(f"« {node.name} » est verrouillé.")
        return node

    def mesh_of(self, node_id: str) -> MeshData | None:
        node = self.scene.get(node_id)
        return self.session.geometry_for(node) if node else None

    # --- Prévisualisation ------------------------------------------------------------
    def preview(self, command: Command) -> None:
        self.cancel()
        command.redo(self.scene)
        self._preview = command

    def confirm(self) -> Command | None:
        command, self._preview = self._preview, None
        if command is not None:
            self.stack.push(command, execute=False)
        return command

    def cancel(self) -> None:
        command, self._preview = self._preview, None
        if command is not None:
            command.undo(self.scene)

    @property
    def previewing(self) -> bool:
        return self._preview is not None

    # --- Géométrie ----------------------------------------------------------------------
    def geometry_command(self, node_id: str, mesh: MeshData, label: str) -> SetGeometry:
        node = self._check_editable(node_id)
        if node.kind is not NodeKind.MESH:
            raise EditError("Seul un maillage peut être modifié en mode Édition.")
        key = new_mesh_key()
        extra_after = {**node.extra, "edited_geometry": True, "uv_status": editmesh.uv_report(mesh).status}
        meshes = {key: mesh}
        if node.asset_id is None and node.mesh_key in self.scene.meshes:  # l'annulation en aura besoin
            meshes[node.mesh_key] = self.scene.meshes[node.mesh_key]
        return SetGeometry(
            node_id,
            (node.asset_id, node.mesh_key),
            (None, key),
            meshes,
            label,
            extra_before=dict(node.extra),
            extra_after=extra_after,
        )

    def edit(self, node_id: str, operation: Callable[[MeshData], EditResult], label: str) -> EditResult:
        """Applique une opération ``editmesh`` à un maillage et l'inscrit dans l'historique."""
        self._check_editable(node_id)
        mesh = self.mesh_of(node_id)
        if mesh is None:
            raise EditError("Géométrie indisponible pour cet élément.")
        result = operation(mesh)
        if result.mesh is mesh:
            return result  # rien à faire (avertissement seulement)
        if result.mesh.triangle_count == 0:
            raise EditError("L'opération ne laisserait aucune face.")
        before = editmesh.uv_report(mesh).status
        if editmesh.uv_report(result.mesh).status == "invalid" and before != "invalid":
            result.warnings.append(
                "Les UV sont devenues invalides : utilisez « Projection UV automatique » pour corriger."
            )
        self.stack.push(self.geometry_command(node_id, result.mesh, label))
        return result

    def separate(self, node_id: str, faces: Iterable[int]) -> str:
        """Sépare des faces en un nouvel objet (même parent, transformation et matériau)."""
        node = self._check_editable(node_id)
        mesh = self.mesh_of(node_id)
        if mesh is None:
            raise EditError("Géométrie indisponible pour cet élément.")
        result = editmesh.separate_faces(mesh, faces)
        assert result.extra is not None
        key = new_mesh_key()
        extra = {k: v for k, v in node.extra.items() if k not in ("gta", "edited_geometry")}
        extra["separated_from"] = node.id
        part = SceneNode(
            self.scene.unique_name(f"{node.name} (séparé)"),
            NodeKind.MESH,
            node.transform.copy(),
            mesh_key=key,
            material_id=node.material_id,
            extra=extra,
        )
        index = self.scene.index_of(node_id) + 1
        command = CompositeCommand(
            [
                self.geometry_command(node_id, result.mesh, "Séparation"),
                InsertNodes(
                    [part.snapshot()], [(part.id, node.parent_id, index)], meshes={key: result.extra}
                ),
            ],
            "Séparer la sélection",
        )
        self.stack.push(command)
        self.session.selection.set([part.id])
        return part.id

    # --- Création ----------------------------------------------------------------------
    def insert_payload(self, payload: Payload, parent_id: str | None, index: int | None, label: str) -> str:
        roots = [(payload.root_id, parent_id, index)]
        self.stack.push(
            InsertNodes(payload.snapshots, roots, label, payload.materials, meshes=payload.meshes)
        )
        self.session.selection.set([payload.root_id])
        return payload.root_id

    def add_mesh(
        self,
        mesh: MeshData,
        name: str,
        parent_id: str | None = None,
        transform: Transform | None = None,
        material: Material | None = None,
        extra: dict | None = None,
        label: str | None = None,
    ) -> str:
        """Ajoute une nouvelle pièce (géométrie locale enregistrée dans le projet)."""
        key = new_mesh_key()
        node = SceneNode(
            self.scene.unique_name(name),
            NodeKind.MESH,
            transform.copy() if transform else Transform(),
            mesh_key=key,
            material_id=material.id if material else None,
            extra=dict(extra or {}),
        )
        payload = Payload([node.snapshot()], {key: mesh}, [material] if material else [])
        return self.insert_payload(payload, parent_id, None, label or f"Ajout de {node.name}")

    def placement_for(self, kind: str) -> Transform:
        """Position proposée d'une nouvelle pièce d'après l'encombrement du véhicule."""
        bounds = self.session.world_bounds()
        if bounds is None:
            return Transform()
        axes = self.axes
        bmin, bmax = bounds
        center = (bmin + bmax) / 2
        lat, lon, up = axes.lateral_axis, axes.longitudinal_axis, axes.up_axis
        front = bmin[lon] if axes.forward_sign < 0 else bmax[lon]
        rear = bmax[lon] if axes.forward_sign < 0 else bmin[lon]
        height = bmax[up] - bmin[up]
        position = center.copy()
        if kind == "front":
            position[lon], position[up] = front, bmin[up] + height * 0.25
        elif kind == "rear":
            position[lon], position[up] = rear, bmin[up] + height * 0.6
        elif kind == "roof":
            position[up] = bmax[up]
        elif kind == "side":
            position[lat], position[up] = bmax[lat], bmin[up] + 0.05
        elif kind == "hood":
            position[lon], position[up] = (front + center[lon]) / 2, bmin[up] + height * 0.7
        elif kind == "interior":
            position[up] = bmin[up] + height * 0.35
        return Transform(translation=[float(v) for v in position])

    # --- Transformations d'objets -------------------------------------------------------
    def _world_move_changes(self, deltas: dict[str, np.ndarray]) -> dict[str, tuple[Transform, Transform]]:
        changes = {}
        for node_id, delta in deltas.items():
            node = self.scene.nodes[node_id]
            parent = self.scene.parent_world_matrix(node_id)
            moved = node.transform.copy()
            offset = np.linalg.inv(parent[:3, :3]) @ np.asarray(delta, np.float64)
            moved.translation = [
                a + float(b) for a, b in zip(node.transform.translation, offset, strict=True)
            ]
            if not moved.is_close(node.transform):
                changes[node_id] = (node.transform.copy(), moved)
        return changes

    def move_world(self, deltas: dict[str, np.ndarray], label: str = "Déplacement") -> None:
        editable = set(self.session.editable(deltas))
        changes = self._world_move_changes({i: d for i, d in deltas.items() if i in editable})
        if changes:
            self.stack.push(SetTransforms(changes, label))

    def align_objects(self, node_ids: Iterable[str], axis: int, mode: str = "min") -> None:
        """Aligne les objets sur un plan (minimum, centre ou maximum de la sélection)."""
        ids = self.scene.top_level(self.session.editable(node_ids))
        boxes = {i: self.session.world_bounds([i], only_visible=False) for i in ids}
        boxes = {i: b for i, b in boxes.items() if b is not None}
        if len(boxes) < 2:
            raise EditError("Sélectionnez au moins deux objets avec géométrie.")

        def value(box) -> float:  # type: ignore[no-untyped-def]
            if mode == "min":
                return float(box[0][axis])
            if mode == "max":
                return float(box[1][axis])
            return float((box[0][axis] + box[1][axis]) / 2)

        values = [value(b) for b in boxes.values()]
        target = min(values) if mode == "min" else max(values) if mode == "max" else float(np.mean(values))
        deltas = {}
        for node_id, box in boxes.items():
            delta = np.zeros(3)
            delta[axis] = target - value(box)
            deltas[node_id] = delta
        self.move_world(deltas, f"Alignement sur {vehicle.AXIS_NAMES[axis]}")

    def scale_proportions(self, node_ids: Iterable[str], factors) -> None:  # type: ignore[no-untyped-def]
        """Ajuste les proportions (échelle par axe) autour du centre de la sélection."""
        ids = self.scene.top_level(self.session.editable(node_ids))
        bounds = self.session.world_bounds(ids, only_visible=False)
        if not ids or bounds is None:
            raise EditError("Sélectionnez au moins un objet avec géométrie.")
        center = (bounds[0] + bounds[1]) / 2
        world_scale = (
            mathutils.translation(center) @ mathutils.scaling(factors) @ mathutils.translation(-center)
        )
        changes = {}
        for node_id in ids:
            node = self.scene.nodes[node_id]
            parent = self.scene.parent_world_matrix(node_id)
            new = decompose(np.linalg.inv(parent) @ world_scale @ self.scene.world_matrix(node_id))
            if not new.is_close(node.transform):
                changes[node_id] = (node.transform.copy(), new)
        if changes:
            self.stack.push(SetTransforms(changes, "Proportions"))

    # --- Symétrie d'objets ------------------------------------------------------------
    def mirror_duplicate(self, node_ids: Iterable[str], axis: int | None = None) -> list[str]:
        """Duplique en miroir par rapport au plan de symétrie du véhicule.

        La géométrie est recalculée en miroir (enroulement inversé) : aucune échelle négative,
        ce qui garde des normales correctes et des transformations exportables.
        """
        axes = self.axes
        axis = axes.lateral_axis if axis is None else axis
        origin = axes.mirror_origin if axis == axes.lateral_axis else 0.0
        reflect = np.eye(4)
        reflect[axis, axis] = -1.0
        reflect[axis, 3] = 2.0 * origin
        flip = np.diag([-1.0, 1.0, 1.0, 1.0])  # miroir local sur X, compensé par la géométrie
        snapshots: list[dict] = []
        roots: list[tuple[str, str | None, int | None]] = []
        meshes: dict[str, MeshData] = {}
        created: list[str] = []
        for node_id in self.scene.top_level(list(node_ids)):
            subtree = self.scene.subtree(node_id)
            mapping = {n.id: new_node_id() for n in subtree}
            for position, node in enumerate(subtree):
                snap = node.snapshot()
                snap["id"] = mapping[node.id]
                if position == 0:
                    parent = self.scene.parent_world_matrix(node_id)
                    world = reflect @ self.scene.world_matrix(node_id) @ flip
                    snap["transform"] = decompose(np.linalg.inv(parent) @ world).to_dict()
                    snap["name"] = self.scene.unique_name(mirror_name(node.name))
                    snap["parent_id"] = node.parent_id
                else:
                    snap["transform"] = decompose(flip @ node.transform.matrix() @ flip).to_dict()
                    snap["parent_id"] = mapping[node.parent_id]  # type: ignore[index]
                    snap["name"] = mirror_name(node.name)
                extra = {k: v for k, v in snap["extra"].items() if k != "gta"}  # copie, plus d'origine GTA
                extra["mirror_of"] = node.id
                snap["extra"] = extra
                mesh = self.session.geometry_for(node)
                if mesh is not None:
                    key = new_mesh_key()
                    meshes[key] = editmesh.mirrored(mesh, 0)
                    snap["asset_id"], snap["mesh_key"] = None, key
                snapshots.append(snap)
            roots.append((mapping[node_id], self.scene.nodes[node_id].parent_id, None))
            created.append(mapping[node_id])
        if not snapshots:
            raise EditError("Aucun élément à dupliquer.")
        self.stack.push(InsertNodes(snapshots, roots, "Duplication miroir", meshes=meshes))
        self.session.selection.set(created)
        return created

    # --- Pivot ------------------------------------------------------------------------
    def set_pivot(self, node_id: str, world_point) -> None:  # type: ignore[no-untyped-def]
        """Déplace le pivot sans déplacer la pièce (géométrie ou enfants compensés)."""
        node = self._check_editable(node_id)
        world = self.scene.world_matrix(node_id)
        local_point = (np.linalg.inv(world) @ np.append(np.asarray(world_point, np.float64), 1.0))[:3]
        if np.linalg.norm(local_point) < 1e-9:
            return
        new_transform = decompose(node.transform.matrix() @ mathutils.translation(local_point))
        commands: list[Command] = [SetTransforms({node_id: (node.transform.copy(), new_transform)}, "Pivot")]
        mesh = self.mesh_of(node_id) if node.kind is NodeKind.MESH else None
        if mesh is not None:
            everything = range(editmesh.topology(mesh).vertex_count)
            moved = editmesh.translate_elements(mesh, editmesh.VERTEX, everything, -local_point)
            commands.append(self.geometry_command(node_id, moved.mesh, "Pivot"))
        shift = mathutils.translation(-local_point)
        children = {
            c.id: (c.transform.copy(), decompose(shift @ c.transform.matrix()))
            for c in self.scene.children(node_id)
        }
        if children:
            commands.append(SetTransforms(children, "Pivot"))
        self.stack.push(CompositeCommand(commands, f"Pivot de {node.name}"))

    def center_pivot(self, node_id: str) -> None:
        bounds = self.session.world_bounds([node_id], only_visible=False)
        if bounds is None:
            raise EditError("Aucune géométrie pour calculer le centre.")
        self.set_pivot(node_id, (bounds[0] + bounds[1]) / 2)

    # --- Composants ------------------------------------------------------------------
    def set_component_info(self, node_ids: Iterable[str], **fields) -> None:  # type: ignore[no-untyped-def]
        changes = {}
        for node_id in node_ids:
            node = self.scene.get(node_id)
            if node is None:
                continue
            values = {k: v for k, v in fields.items() if v is not None}
            after = {**node.extra, "component": {**node.extra.get("component", {}), **values}}
            if after != node.extra:
                changes[node_id] = (dict(node.extra), after)
        if changes:
            self.stack.push(SetNodeExtra(changes, "Propriétés du composant"))

    def create_variant(self, component_id: str, name: str | None = None) -> tuple[str, str]:
        """Crée une variante d'un composant dans un ensemble de variantes (une seule visible).

        La première fois, le composant d'origine est rangé dans un nouvel ensemble ; la variante
        est une copie masquée, modifiable indépendamment.
        """
        node = self._check_editable(component_id)
        parent = self.scene.get(node.parent_id)
        commands: list[Command] = []
        if vehicle.is_variant_set(parent):
            set_id = parent.id  # type: ignore[union-attr]
            count = len(self.scene.children(set_id))
        else:
            group = SceneNode(
                self.scene.unique_name(f"Variantes · {node.name}"),
                NodeKind.GROUP,
                extra={
                    "variant_set": {"kind": "component"},
                    "component": {"category": vehicle.category(self.scene, node)},
                },
            )
            set_id = group.id
            count = 1
            commands += [
                InsertNodes(
                    [group.snapshot()], [(group.id, node.parent_id, self.scene.index_of(component_id))]
                ),
                MoveNodes([component_id], group.id),
            ]
        subtree = self.scene.subtree(component_id)
        mapping = {n.id: new_node_id() for n in subtree}
        snapshots = []
        for position, item in enumerate(subtree):
            snap = item.snapshot()
            snap["id"] = mapping[item.id]
            snap["parent_id"] = set_id if position == 0 else mapping[item.parent_id]  # type: ignore[index]
            if position == 0:
                snap["name"] = name or f"{node.name} · variante {chr(ord('A') + count)}"
                snap["visible"] = False
            snapshots.append(snap)
        variant_id = mapping[component_id]
        commands.append(InsertNodes(snapshots, [(variant_id, set_id, None)]))
        # l'ensemble est créé à l'identité sous le même parent : transformations locales identiques
        self.stack.push(CompositeCommand(commands, f"Variante de {node.name}"))
        return set_id, variant_id

    def set_active_variant(self, set_id: str, variant_id: str) -> None:
        group = self._node(set_id)
        if not vehicle.is_variant_set(group):
            raise EditError("Ce groupe n'est pas un ensemble de variantes.")
        changes = {
            c.id: (c.visible, c.id == variant_id)
            for c in self.scene.children(set_id)
            if c.visible != (c.id == variant_id)
        }
        if changes:
            self.stack.push(SetNodeField("visible", changes, "Variante active"))

    # --- Remplacement ----------------------------------------------------------------
    def duplicate_payload(self, node_id: str) -> Payload:
        """Copie d'un sous-arbre existant, utilisable comme pièce de remplacement."""
        subtree = self.scene.subtree(node_id)
        mapping = {n.id: new_node_id() for n in subtree}
        snapshots = []
        for position, node in enumerate(subtree):
            snap = node.snapshot()
            snap["id"] = mapping[node.id]
            snap["parent_id"] = None if position == 0 else mapping[node.parent_id]  # type: ignore[index]
            snap["extra"] = {k: v for k, v in node.extra.items() if k != "gta"}
            snapshots.append(snap)
        return Payload(snapshots)

    def build_replacement(
        self, target_id: str, source: Payload, options: ReplaceOptions | None = None
    ) -> tuple[Command, ReplaceReport]:
        """Prépare le remplacement d'une pièce : commande (non exécutée) et rapport de vérification."""
        options = options or ReplaceOptions()
        target = self._check_editable(target_id)
        scene = self.scene
        report = ReplaceReport(target.name, source.snapshots[0]["name"])
        is_bone = target.extra.get("gta", {}).get("role") == "bone"
        inside_bone = is_bone and not options.allow_bone_change
        if vehicle.role(scene, target) == vehicle.ROLE_MOBILE:
            report.warnings.append(
                "Pièce mobile remplacée : vérifiez le pivot et l'axe de rotation (roue, porte, capot…)."
            )
        if inside_bone:
            report.notes.append(
                "Os GTA V conservé : seule la géométrie rattachée à l'os est remplacée "
                "(modification des os non autorisée sans validation)."
            )
        elif is_bone:
            report.warnings.append(
                "L'os GTA V d'origine sera supprimé : la pièce ne sera plus animée en jeu."
            )

        target_bounds = self.session.world_bounds([target_id], only_visible=False)
        parent_id = target_id if inside_bone else (target.parent_id if options.keep_parent else None)
        parent_world = scene.world_matrix(parent_id) if parent_id else np.eye(4)
        snapshots = [dict(s) for s in source.snapshots]
        root = snapshots[0]
        root["name"] = scene.unique_name(root["name"])
        if inside_bone:
            local = Transform()
        elif options.keep_transform:
            local = (
                target.transform.copy() if options.keep_parent else decompose(scene.world_matrix(target_id))
            )
        else:
            local = Transform()
            if target_bounds is not None:
                center = (target_bounds[0] + target_bounds[1]) / 2
                local.translation = [
                    float(v) for v in (np.linalg.inv(parent_world) @ np.append(center, 1.0))[:3]
                ]
        root["transform"] = local.to_dict()

        def insert() -> InsertNodes:
            return InsertNodes(
                snapshots, [(root["id"], parent_id, None)], meshes=source.meshes, materials=source.materials
            )

        probe = insert()  # mesure de la nouvelle pièce en place, défaite aussitôt
        probe.redo(scene)
        try:
            source_bounds = self.session.world_bounds([root["id"]], only_visible=False)
        finally:
            probe.undo(scene)
        if target_bounds is not None and source_bounds is not None:
            report.target_size = target_bounds[1] - target_bounds[0]
            report.source_size = source_bounds[1] - source_bounds[0]
            world = parent_world @ local.matrix()
            source_center = (source_bounds[0] + source_bounds[1]) / 2
            if options.fit_dimensions:
                ratios = [
                    t / s
                    for t, s in zip(report.target_size, report.source_size, strict=True)
                    if s > 1e-6 and t > 1e-6
                ]
                if ratios:
                    report.scale = float(min(ratios))
                    world = (
                        mathutils.translation(source_center)
                        @ mathutils.scaling([report.scale] * 3)
                        @ mathutils.translation(-source_center)
                        @ world
                    )
            if options.align_pivot:
                delta = (target_bounds[0] + target_bounds[1]) / 2 - source_center
                world = mathutils.translation(delta) @ world
            root["transform"] = decompose(np.linalg.inv(parent_world) @ world).to_dict()
        commands: list[Command] = [insert()]

        new_meshes = [s["id"] for s in snapshots if s["kind"] == NodeKind.MESH.value]
        used = {n.material_id for n in scene.subtree(target_id) if n.kind is NodeKind.MESH and n.material_id}
        if options.keep_materials and len(used) == 1 and new_meshes:
            commands.append(AssignMaterial(new_meshes, used.pop(), "Matériau conservé"))
            report.materials = "Matériau d'origine conservé"
        elif options.keep_materials and used:
            report.materials = f"{len(used)} matériaux d'origine : matériaux de la nouvelle pièce conservés"
        else:
            report.materials = "Matériaux de la nouvelle pièce"

        if inside_bone:
            removed = [c.id for c in scene.children(target_id) if c.kind is NodeKind.MESH]
        else:
            removed = [target_id]
            anchors = scene.top_level([n.id for n in scene.walk(target_id) if n.kind is NodeKind.ANCHOR])
            if options.keep_anchors and anchors:
                commands.append(MoveNodes(anchors, root["id"]))
                report.anchors_moved = len(anchors)
            elif anchors:
                report.warnings.append(f"{len(anchors)} point(s) d'ancrage seront supprimés avec la pièce.")
        if removed:
            commands.append(RemoveNodes(removed))
        return CompositeCommand(commands, f"Remplacement de {target.name}"), report

    def replace(
        self, target_id: str, source: Payload, options: ReplaceOptions | None = None
    ) -> ReplaceReport:
        command, report = self.build_replacement(target_id, source, options)
        self.stack.push(command)
        self.session.selection.set([source.root_id])
        return report

    # --- Points d'ancrage ----------------------------------------------------------------
    def add_anchor(
        self,
        parent_id: str | None,
        name: str = "Point d'ancrage",
        anchor_type: str = "generic",
        position=(0.0, 0.0, 0.0),  # type: ignore[no-untyped-def]
        rotation=(0.0, 0.0, 0.0),  # type: ignore[no-untyped-def]
        constraints: str = "fixed",
        metadata: dict | None = None,
    ) -> str:
        """Crée un point d'ancrage (position et rotation locales au parent)."""
        if parent_id is not None:
            self._node(parent_id)
        node = SceneNode(
            self.scene.unique_name(name),
            NodeKind.ANCHOR,
            Transform([float(v) for v in position], [float(v) for v in rotation]),
            extra={
                "anchor": {
                    "anchor_id": uuid.uuid4().hex[:12],
                    "type": anchor_type if anchor_type in vehicle.ANCHOR_TYPES else "generic",
                    "constraints": constraints if constraints in vehicle.ANCHOR_CONSTRAINTS else "fixed",
                    "metadata": dict(metadata or {}),
                    "component_id": parent_id,
                }
            },
        )
        self.stack.push(
            InsertNodes([node.snapshot()], [(node.id, parent_id, None)], f"Ancrage « {node.name} »")
        )
        self.session.selection.set([node.id])
        return node.id

    def update_anchor(self, anchor_id: str, **fields) -> None:  # type: ignore[no-untyped-def]
        node = self._node(anchor_id)
        if node.kind is not NodeKind.ANCHOR:
            raise EditError("Ce nœud n'est pas un point d'ancrage.")
        data = dict(node.extra.get("anchor", {}))
        for key in ("type", "constraints", "metadata", "component_id"):
            if fields.get(key) is not None:
                data[key] = fields[key]
        after = {**node.extra, "anchor": data}
        if after != node.extra:
            self.stack.push(SetNodeExtra({anchor_id: (dict(node.extra), after)}, "Point d'ancrage"))

    def attach_anchor(self, anchor_id: str, component_id: str) -> None:
        """Associe un ancrage à un composant : il en devient l'enfant (position monde conservée)."""
        node = self._node(anchor_id)
        self._node(component_id)
        after = {**node.extra, "anchor": {**node.extra.get("anchor", {}), "component_id": component_id}}
        commands: list[Command] = [SetNodeExtra({anchor_id: (dict(node.extra), after)})]
        if node.parent_id != component_id:
            commands.insert(0, MoveNodes([anchor_id], component_id))
        self.stack.push(CompositeCommand(commands, "Association de l'ancrage"))

    # --- Roues --------------------------------------------------------------------------
    def wheels(self) -> vehicle.WheelReport:
        return vehicle.find_wheels(self.session, self.axes, self.session.project.vehicle_type.value)

    def set_track(self, track: float, wheel_ids: Iterable[str] | None = None) -> None:
        """Règle la voie : roues gauches et droites placées symétriquement à ``track / 2``."""
        if track <= 0:
            raise EditError("La voie doit être positive.")
        chosen = set(wheel_ids) if wheel_ids is not None else None
        wheels = [
            w
            for w in self.wheels().wheels
            if w.side in ("gauche", "droite") and (chosen is None or w.node_id in chosen)
        ]
        if not wheels:
            raise EditError("Aucune roue gauche / droite identifiée.")
        lat, origin = self.axes.lateral_axis, self.axes.mirror_origin
        deltas = {}
        for wheel in wheels:
            delta = np.zeros(3)
            sign = (1.0 if wheel.side == "droite" else -1.0) * self.axes.right_sign
            delta[lat] = origin + sign * track / 2 - wheel.center[lat]
            deltas[wheel.node_id] = delta
        self.move_world(deltas, "Voie des roues")

    def set_wheelbase(self, wheelbase: float) -> None:
        """Règle l'empattement : essieux avant et arrière déplacés symétriquement."""
        if wheelbase <= 0:
            raise EditError("L'empattement doit être positif.")
        report = self.wheels()
        front = [w for w in report.wheels if w.axle == "avant"]
        rear = [w for w in report.wheels if w.axle == "arrière"]
        if not front or not rear:
            raise EditError("Essieux avant et arrière non identifiés.")
        lon = self.axes.longitudinal_axis
        front_pos = float(np.mean([w.center[lon] for w in front]))
        rear_pos = float(np.mean([w.center[lon] for w in rear]))
        middle = (front_pos + rear_pos) / 2
        direction = 1.0 if front_pos >= rear_pos else -1.0
        deltas = {}
        for group, target in (
            (front, middle + direction * wheelbase / 2),
            (rear, middle - direction * wheelbase / 2),
        ):
            current = float(np.mean([w.center[lon] for w in group]))
            for wheel in group:
                delta = np.zeros(3)
                delta[lon] = target - current
                deltas[wheel.node_id] = delta
        self.move_world(deltas, "Empattement")

    def align_wheel_heights(self) -> None:
        report = self.wheels()
        if len(report.wheels) < 2:
            raise EditError("Au moins deux roues sont nécessaires.")
        up = self.axes.up_axis
        target = float(np.mean([w.center[up] for w in report.wheels]))
        deltas = {}
        for wheel in report.wheels:
            delta = np.zeros(3)
            delta[up] = target - wheel.center[up]
            deltas[wheel.node_id] = delta
        self.move_world(deltas, "Alignement des roues")

    def scale_wheels(self, wheel_ids: Iterable[str], factor: float, axis: int | None = None) -> None:
        """Échelle d'une roue autour de son centre (uniforme, ou sur un axe : largeur du pneu)."""
        if factor <= 0:
            raise EditError("Le facteur d'échelle doit être positif.")
        changes = {}
        for node_id in self.session.editable(wheel_ids):
            bounds = self.session.world_bounds([node_id], only_visible=False)
            if bounds is None:
                continue
            center = (bounds[0] + bounds[1]) / 2
            factors = [factor] * 3 if axis is None else [factor if i == axis else 1.0 for i in range(3)]
            world_scale = (
                mathutils.translation(center) @ mathutils.scaling(factors) @ mathutils.translation(-center)
            )
            node = self.scene.nodes[node_id]
            parent = self.scene.parent_world_matrix(node_id)
            changes[node_id] = (
                node.transform.copy(),
                decompose(np.linalg.inv(parent) @ world_scale @ self.scene.world_matrix(node_id)),
            )
        if changes:
            self.stack.push(SetTransforms(changes, "Échelle des roues"))

    def mirror_wheel_position(self, source_id: str, target_id: str) -> None:
        """Place la roue ``target`` en position miroir de ``source`` (plan de symétrie du véhicule)."""
        by_id = {w.node_id: w for w in self.wheels().wheels}
        if source_id not in by_id or target_id not in by_id:
            raise EditError("Roues non identifiées.")
        lat = self.axes.lateral_axis
        mirrored = by_id[source_id].center.copy()
        mirrored[lat] = 2 * self.axes.mirror_origin - mirrored[lat]
        self.move_world({target_id: mirrored - by_id[target_id].center}, "Symétrie des roues")

    # --- Habitacle ------------------------------------------------------------------------
    INTERIOR_PRESETS = {
        "civil": "Habitacle civil",
        "police": "Habitacle police",
        "ems": "Habitacle EMS",
        "command": "Véhicule de commandement",
    }

    def create_interior_configurations(self, keys: Iterable[str] = ("civil", "police", "ems")) -> str:
        """Crée un ensemble de configurations d'habitacle (une seule active à la fois)."""
        keys = [k for k in keys if k in self.INTERIOR_PRESETS]
        if not keys:
            raise EditError("Aucune configuration choisie.")
        group = SceneNode(
            self.scene.unique_name("Configurations d'habitacle"),
            NodeKind.GROUP,
            extra={"variant_set": {"kind": "interior"}, "component": {"category": "habitacle"}},
        )
        snapshots = [group.snapshot()]
        for position, key in enumerate(keys):
            child = SceneNode(
                self.INTERIOR_PRESETS[key],
                NodeKind.GROUP,
                visible=position == 0,
                extra={"interior_configuration": key, "component": {"category": "habitacle"}},
            )
            snapshots.append({**child.snapshot(), "parent_id": group.id})
        parent = next((n.id for n in self.scene.roots() if n.kind is NodeKind.MODEL), None)
        self.stack.push(InsertNodes(snapshots, [(group.id, parent, None)], "Configurations d'habitacle"))
        self.session.selection.set([group.id])
        return group.id

    # --- Matériaux ------------------------------------------------------------------------
    def apply_material_preset(self, node_ids: Iterable[str], key: str, material_id: str | None = None) -> str:
        """Applique un preset automobile : modifie ``material_id`` ou crée un matériau et l'affecte."""
        found = material_preset(key)
        if found is None:
            raise EditError("Preset de matériau inconnu.")
        if material_id is not None and material_id in self.scene.materials:
            material = self.scene.materials[material_id]
            properties = found.properties()
            before = {k: material.properties()[k] for k in properties}
            self.stack.push(SetMaterialProperties(material_id, before, properties, f"Preset {found.label}"))
            return material_id
        targets = [
            n.id
            for i in self.session.editable(node_ids)
            for n in self.scene.subtree(i)
            if n.kind is NodeKind.MESH
        ]
        if not targets:
            raise EditError("Sélectionnez au moins une pièce.")
        material = Material(found.label)
        material.apply(found.properties())
        commands: list[Command] = [AddMaterial(material), AssignMaterial(targets, material.id)]
        self.stack.push(CompositeCommand(commands, f"Matériau {found.label}"))
        return material.id


def mirror_name(name: str) -> str:
    """Nom de la copie miroir : gauche ↔ droite si le nom l'indique, sinon suffixe « (miroir) »."""
    for a, b in (("gauche", "droite"), ("droite", "gauche"), ("left", "right"), ("right", "left")):
        if a in name.lower():
            index = name.lower().index(a)
            return name[:index] + b + name[index + len(a) :]
    for a, b in (("_l", "_r"), ("_r", "_l"), (" G", " D"), (" D", " G")):
        if name.endswith(a):
            return name[: -len(a)] + b
    return f"{name} (miroir)"
