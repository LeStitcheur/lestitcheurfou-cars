"""Session de travail : projet ouvert, géométrie chargée, historique et opérations d'édition.

Indépendante de Qt : toutes les modifications de scène passent par l'``UndoStack``.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import numpy as np

from lsfcars.core.logging_setup import get_logger
from lsfcars.importers import ImportResult, ModelLoadError, load_model
from lsfcars.importers.base import Progress, no_progress
from lsfcars.project import recovery, store
from lsfcars.project.model import Asset, Project, VehicleRole, VehicleType
from lsfcars.scene import mathutils
from lsfcars.scene.commands import (
    AddMaterial,
    AssignMaterial,
    CompositeCommand,
    InsertNodes,
    MoveNodes,
    RemoveNodes,
    SetMaterialProperties,
    SetNodeField,
    SetTransforms,
    UndoStack,
)
from lsfcars.scene.graph import NodeKind, SceneNode, new_node_id
from lsfcars.scene.materials import Material
from lsfcars.scene.mesh import MeshData
from lsfcars.scene.selection import Selection
from lsfcars.scene.transform import Transform

log = get_logger(__name__)

GeometryKey = tuple[str, str]  # (asset_id, mesh_key)


class ProjectSession:
    def __init__(self, project: Project) -> None:
        self.project = project
        self.geometry: dict[GeometryKey, MeshData] = {}
        self.missing_assets: dict[str, str] = {}  # asset_id -> raison
        self.stack = UndoStack(project.scene)
        self.selection = Selection()
        self._meta_dirty = False
        self.stack.subscribe(lambda _c, _a: self.selection.prune(self.scene))

    # --- Cycle de vie -------------------------------------------------------
    @classmethod
    def create(
        cls,
        parent_dir: str | Path,
        name: str,
        vehicle_type: VehicleType = VehicleType.CAR,
        role: VehicleRole = VehicleRole.CIVILIAN,
        description: str = "",
    ) -> ProjectSession:
        return cls(store.create_project(parent_dir, name, vehicle_type, role, description))

    @classmethod
    def open(cls, path: str | Path) -> ProjectSession:
        return cls.from_project(store.load_project(path))

    @classmethod
    def from_project(cls, project: Project) -> ProjectSession:
        session = cls(project)
        session.load_geometry()
        return session

    @property
    def scene(self):  # type: ignore[no-untyped-def]
        return self.project.scene

    @property
    def file_path(self) -> Path:
        assert self.project.file_path is not None
        return self.project.file_path

    @property
    def dirty(self) -> bool:
        return self._meta_dirty or not self.stack.is_clean()

    def mark_meta_dirty(self) -> None:
        self._meta_dirty = True

    def mark_dirty(self) -> None:
        """Force l'état « modifié » (projet restauré, migré…)."""
        self._meta_dirty = True

    def save(self) -> Path:
        path = store.save_project(self.project)
        self._saved()
        return path

    def save_as(self, parent_dir: str | Path, name: str) -> Path:
        old_id = self.project.project_id
        path = store.save_as(self.project, parent_dir, name)
        recovery.clear(old_id)
        self._saved()
        return path

    def _saved(self) -> None:
        self.stack.mark_clean()
        self._meta_dirty = False
        recovery.clear(self.project.project_id)

    def autosave(self) -> Path | None:
        if not self.dirty or self.project.file_path is None:
            return None
        return recovery.autosave(self.project)

    def close(self) -> None:
        recovery.clear(self.project.project_id)

    # --- Géométrie ----------------------------------------------------------
    def load_geometry(self) -> None:
        """Charge chaque asset une fois ; développe les modèles migrés depuis la v0.1."""
        for asset in self.project.assets.values():
            try:
                result = load_model(self.project.project_dir / asset.rel_path)
            except ModelLoadError as exc:
                self.missing_assets[asset.id] = str(exc)
                log.warning("Asset « %s » non chargé : %s", asset.original_name, exc)
                continue
            for key, mesh in result.meshes.items():
                self.geometry[(asset.id, key)] = mesh
            for model in [
                n
                for n in self.scene.walk()
                if n.kind is NodeKind.MODEL and n.asset_id == asset.id and not self.scene.children(n.id)
            ]:
                self._expand_model(model, result)

    def _expand_model(self, model: SceneNode, result: ImportResult) -> None:
        snapshots, materials = self._snapshots_from_import(result, model.id)
        for material in materials:
            self.scene.add_material(material)
        for snapshot in snapshots:
            node = SceneNode.from_snapshot(snapshot)
            self.scene.add(node, node.parent_id)
        self._meta_dirty = True  # structure développée : à enregistrer
        log.info("Modèle v0.1 développé : %s (%d nœuds)", model.name, len(snapshots))

    def geometry_for(self, node: SceneNode) -> MeshData | None:
        if node.kind is not NodeKind.MESH or not node.asset_id or not node.mesh_key:
            return None
        return self.geometry.get((node.asset_id, node.mesh_key))

    # --- Import -------------------------------------------------------------
    @staticmethod
    def read_model(source: str | Path, progress: Progress = no_progress) -> ImportResult:
        """Lecture seule, sans effet sur la session (peut s'exécuter dans un thread)."""
        return load_model(source, progress)

    def import_model(self, source: str | Path, progress: Progress = no_progress) -> str:
        return self.apply_import(self.read_model(source, progress))

    def apply_import(self, result: ImportResult) -> str:
        """Copie le fichier dans le projet, enregistre la provenance et ajoute la scène."""
        source = Path(result.source)
        rel_path = store.import_asset(self.project, source)
        copied = self.project.project_dir / rel_path
        asset = Asset(
            rel_path=rel_path,
            original_name=source.name,
            source_path=str(source.resolve()),
            sha256=store.sha256_of(copied),
            format=result.format,
            size=copied.stat().st_size,
            importer=result.importer,
            notes=list(result.notes),
        )
        self.project.assets[asset.id] = asset
        for key, mesh in result.meshes.items():
            self.geometry[(asset.id, key)] = mesh

        root = SceneNode(self.scene.unique_name(source.name), NodeKind.MODEL, asset_id=asset.id)
        snapshots, materials = self._snapshots_from_import(result, root.id, asset.id)
        command = InsertNodes(
            [root.snapshot(), *snapshots],
            [(root.id, None, None)],
            f"Import de {source.name}",
            materials,
        )
        self.stack.push(command)
        self.selection.set([root.id])
        log.info("Modèle importé : %s (%d triangles)", source.name, result.triangle_count)
        return root.id

    def _snapshots_from_import(
        self, result: ImportResult, root_id: str, asset_id: str | None = None
    ) -> tuple[list[dict], list[Material]]:
        asset_id = asset_id or self.scene.nodes[root_id].asset_id
        materials: dict[str, Material] = {}
        for key, imported in result.materials.items():
            texture = None
            if imported.texture_png:
                texture = store.store_texture(
                    self.project, imported.texture_png, imported.texture_name or imported.name
                )
            materials[key] = Material(
                imported.name,
                imported.base_color,
                imported.roughness,
                imported.metallic,
                imported.opacity,
                texture,
            )
        ids = {node.key: new_node_id() for node in result.nodes}
        snapshots = []
        for node in result.nodes:
            snapshot = SceneNode(
                name=node.name,
                kind=NodeKind.MESH if node.mesh_key else NodeKind.GROUP,
                transform=node.transform.copy(),
                asset_id=asset_id if node.mesh_key else None,
                mesh_key=node.mesh_key,
                material_id=materials[node.material_key].id if node.material_key in materials else None,
                parent_id=ids.get(node.parent_key, root_id),
                id=ids[node.key],
                extra=dict(node.extra),
            ).snapshot()
            snapshots.append(snapshot)
        return snapshots, list(materials.values())

    # --- Informations -------------------------------------------------------
    def _mesh_nodes_under(self, node_ids: Iterable[str] | None, only_visible: bool):  # type: ignore[no-untyped-def]
        if node_ids is None:
            candidates = list(self.scene.mesh_nodes())
        else:
            seen: dict[str, SceneNode] = {}
            for node_id in node_ids:
                if node_id in self.scene:
                    for node in self.scene.subtree(node_id):
                        if node.kind is NodeKind.MESH:
                            seen[node.id] = node
            candidates = list(seen.values())
        for node in candidates:
            if only_visible and not self.scene.effective_visible(node.id):
                continue
            mesh = self.geometry_for(node)
            if mesh is not None:
                yield node, mesh

    def stats(self, node_ids: Iterable[str] | None = None) -> tuple[int, int, int]:
        """(triangles, sommets, maillages)."""
        triangles = vertices = count = 0
        for _node, mesh in self._mesh_nodes_under(node_ids, only_visible=False):
            triangles += mesh.triangle_count
            vertices += mesh.vertex_count
            count += 1
        return triangles, vertices, count

    def world_bounds(
        self, node_ids: Iterable[str] | None = None, only_visible: bool = True
    ) -> tuple[np.ndarray, np.ndarray] | None:
        corners = []
        for node, mesh in self._mesh_nodes_under(node_ids, only_visible):
            bmin, bmax = mesh.bounds
            box = np.array(
                [
                    [x, y, z]
                    for x in (bmin[0], bmax[0])
                    for y in (bmin[1], bmax[1])
                    for z in (bmin[2], bmax[2])
                ]
            )
            corners.append(mathutils.transform_points(self.scene.world_matrix(node.id), box))
        if not corners:
            return None
        points = np.vstack(corners)
        return points.min(axis=0), points.max(axis=0)

    def dimensions(self, node_ids: Iterable[str] | None = None) -> np.ndarray | None:
        bounds = self.world_bounds(node_ids, only_visible=False)
        return None if bounds is None else bounds[1] - bounds[0]

    # --- Édition (toutes annulables) ----------------------------------------
    def editable(self, node_ids: Iterable[str]) -> list[str]:
        return [i for i in node_ids if i in self.scene and not self.scene.effective_locked(i)]

    def set_transforms(
        self,
        changes: dict[str, Transform],
        label: str = "Transformation",
        merge_key: object | None = None,
    ) -> None:
        pairs = {
            node_id: (self.scene.nodes[node_id].transform.copy(), transform.copy())
            for node_id, transform in changes.items()
            if node_id in self.scene and not self.scene.nodes[node_id].transform.is_close(transform)
        }
        if pairs:
            self.stack.push(SetTransforms(pairs, label, merge_key))

    def rename(self, node_id: str, name: str) -> None:
        name = name.strip()
        node = self.scene.get(node_id)
        if node and name and name != node.name:
            self.stack.push(SetNodeField("name", {node_id: (node.name, name)}, "Renommage"))

    def set_visible(self, node_ids: Iterable[str], visible: bool) -> None:
        changes = {
            i: (self.scene.nodes[i].visible, visible)
            for i in node_ids
            if i in self.scene and self.scene.nodes[i].visible != visible
        }
        if changes:
            label = "Afficher" if visible else "Masquer"
            self.stack.push(SetNodeField("visible", changes, label))

    def set_locked(self, node_ids: Iterable[str], locked: bool) -> None:
        changes = {
            i: (self.scene.nodes[i].locked, locked)
            for i in node_ids
            if i in self.scene and self.scene.nodes[i].locked != locked
        }
        if changes:
            label = "Verrouiller" if locked else "Déverrouiller"
            self.stack.push(SetNodeField("locked", changes, label))

    def delete(self, node_ids: Iterable[str]) -> int:
        targets = self.scene.top_level(self.editable(node_ids))
        if not targets:
            return 0
        self.stack.push(RemoveNodes(targets, "Suppression"))
        return len(targets)

    def duplicate(self, node_ids: Iterable[str]) -> list[str]:
        """Duplique les sous-arbres (géométrie et matériaux partagés), juste après l'original."""
        new_roots: list[str] = []
        snapshots: list[dict] = []
        roots: list[tuple[str, str | None, int | None]] = []
        for node_id in self.scene.top_level(list(node_ids)):
            mapping: dict[str, str] = {}
            subtree = self.scene.subtree(node_id)
            for node in subtree:
                mapping[node.id] = new_node_id()
            for position, node in enumerate(subtree):
                snapshot = node.snapshot()
                snapshot["id"] = mapping[node.id]
                if position == 0:
                    snapshot["name"] = self.scene.unique_name(node.name)
                    snapshot["parent_id"] = node.parent_id
                else:
                    snapshot["parent_id"] = mapping[node.parent_id]  # type: ignore[index]
                snapshots.append(snapshot)
            original = self.scene.nodes[node_id]
            roots.append(
                (
                    mapping[node_id],
                    original.parent_id,
                    self.scene.index_of(node_id) + 1 + len(new_roots),
                )
            )
            new_roots.append(mapping[node_id])
        if snapshots:
            self.stack.push(InsertNodes(snapshots, roots, "Duplication"))
            self.selection.set(new_roots)
        return new_roots

    def group(self, node_ids: Iterable[str], name: str = "Groupe") -> str | None:
        targets = self.scene.top_level(self.editable(node_ids))
        if not targets:
            return None
        first = self.scene.nodes[targets[0]]
        parent_id = first.parent_id
        index = self.scene.index_of(first.id)
        group = SceneNode(self.scene.unique_name(name), NodeKind.GROUP)
        command = CompositeCommand(
            [
                InsertNodes([group.snapshot()], [(group.id, parent_id, index)]),
                MoveNodes(targets, group.id),
            ],
            "Regroupement",
        )
        self.stack.push(command)
        self.selection.set([group.id])
        return group.id

    def ungroup(self, group_id: str) -> list[str]:
        group = self.scene.get(group_id)
        if group is None or group.kind is NodeKind.MESH or self.scene.effective_locked(group_id):
            return []
        children = [c.id for c in self.scene.children(group_id)]
        command = CompositeCommand(
            [MoveNodes(children, group.parent_id), RemoveNodes([group_id])], "Dégroupement"
        )
        self.stack.push(command)
        self.selection.set(children)
        return children

    def reparent(self, node_ids: Iterable[str], parent_id: str | None) -> None:
        targets = [
            i
            for i in self.scene.top_level(self.editable(node_ids))
            if i != parent_id and not (parent_id and self.scene.is_ancestor(i, parent_id))
        ]
        if targets:
            self.stack.push(MoveNodes(targets, parent_id))

    # --- Matériaux ----------------------------------------------------------
    def create_material(self, name: str = "Nouveau matériau", based_on: Material | None = None) -> Material:
        material = based_on.copy() if based_on else Material(name)
        material.name = name
        self.stack.push(AddMaterial(material))
        return material

    def set_material_properties(
        self, material_id: str, properties: dict, merge_key: object | None = None
    ) -> None:
        material = self.scene.materials.get(material_id)
        if material is None:
            return
        before = {k: material.properties()[k] for k in properties}
        if before == properties:
            return
        self.stack.push(SetMaterialProperties(material_id, before, dict(properties), "Matériau", merge_key))

    def assign_material(self, node_ids: Iterable[str], material_id: str | None) -> None:
        targets = [
            n.id
            for i in self.editable(node_ids)
            for n in self.scene.subtree(i)
            if n.kind is NodeKind.MESH and n.material_id != material_id
        ]
        if targets:
            self.stack.push(AssignMaterial(targets, material_id))

    def set_texture(self, material_id: str, image_path: str | Path | None) -> None:
        texture = store.copy_texture(self.project, image_path) if image_path else None
        self.set_material_properties(material_id, {"texture": texture})
