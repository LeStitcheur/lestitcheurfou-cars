"""Graphe de scène hiérarchique (pur Python, sans dépendance au rendu ni à l'interface)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np

from lsfcars.scene.materials import Material
from lsfcars.scene.transform import Transform


class NodeKind(StrEnum):
    GROUP = "group"  # regroupement sans géométrie
    MODEL = "model"  # racine d'un fichier importé
    MESH = "mesh"  # maillage affichable

    @property
    def label(self) -> str:
        return {"group": "Groupe", "model": "Modèle importé", "mesh": "Maillage"}[self.value]


def new_node_id() -> str:
    return uuid.uuid4().hex


@dataclass
class SceneNode:
    name: str
    kind: NodeKind = NodeKind.GROUP
    transform: Transform = field(default_factory=Transform)
    visible: bool = True
    locked: bool = False
    asset_id: str | None = None  # fichier importé d'origine
    mesh_key: str | None = None  # identifiant du maillage dans ce fichier
    material_id: str | None = None
    parent_id: str | None = None
    id: str = field(default_factory=new_node_id)

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind.value,
            "transform": self.transform.to_dict(),
            "visible": self.visible,
            "locked": self.locked,
            "asset_id": self.asset_id,
            "mesh_key": self.mesh_key,
            "material_id": self.material_id,
            "parent_id": self.parent_id,
        }

    @classmethod
    def from_snapshot(cls, data: dict) -> SceneNode:
        return cls(
            name=data["name"],
            kind=NodeKind(data.get("kind", "group")),
            transform=Transform.from_dict(data.get("transform", {})),
            visible=bool(data.get("visible", True)),
            locked=bool(data.get("locked", False)),
            asset_id=data.get("asset_id"),
            mesh_key=data.get("mesh_key"),
            material_id=data.get("material_id"),
            parent_id=data.get("parent_id"),
            id=data.get("id") or new_node_id(),
        )


class SceneError(Exception):
    pass


class SceneGraph:
    """Nœuds ordonnés par parent, matériaux partagés."""

    def __init__(self) -> None:
        self.nodes: dict[str, SceneNode] = {}
        self._children: dict[str | None, list[str]] = {None: []}
        self.materials: dict[str, Material] = {}

    # --- Lecture ------------------------------------------------------------
    def __contains__(self, node_id: object) -> bool:
        return node_id in self.nodes

    def __len__(self) -> int:
        return len(self.nodes)

    def get(self, node_id: str | None) -> SceneNode | None:
        return self.nodes.get(node_id) if node_id else None

    def roots(self) -> list[SceneNode]:
        return [self.nodes[i] for i in self._children[None]]

    def children(self, node_id: str | None) -> list[SceneNode]:
        return [self.nodes[i] for i in self._children.get(node_id, [])]

    def index_of(self, node_id: str) -> int:
        return self._children[self.nodes[node_id].parent_id].index(node_id)

    def walk(self, node_id: str | None = None) -> Iterator[SceneNode]:
        """Parcours en profondeur (ordre d'affichage) sous ``node_id`` (exclu)."""
        for child_id in list(self._children.get(node_id, [])):
            yield self.nodes[child_id]
            yield from self.walk(child_id)

    def subtree(self, node_id: str) -> list[SceneNode]:
        return [self.nodes[node_id], *self.walk(node_id)]

    def ancestors(self, node_id: str) -> Iterator[SceneNode]:
        node = self.nodes.get(node_id)
        while node is not None and node.parent_id is not None:
            node = self.nodes[node.parent_id]
            yield node

    def is_ancestor(self, ancestor_id: str, node_id: str) -> bool:
        return any(a.id == ancestor_id for a in self.ancestors(node_id))

    def path(self, node_id: str) -> str:
        names = [a.name for a in self.ancestors(node_id)][::-1]
        return " / ".join([*names, self.nodes[node_id].name])

    def mesh_nodes(self) -> Iterator[SceneNode]:
        return (n for n in self.walk() if n.kind is NodeKind.MESH)

    def effective_visible(self, node_id: str) -> bool:
        return self.nodes[node_id].visible and all(a.visible for a in self.ancestors(node_id))

    def effective_locked(self, node_id: str) -> bool:
        return self.nodes[node_id].locked or any(a.locked for a in self.ancestors(node_id))

    def world_matrix(self, node_id: str) -> np.ndarray:
        matrix = self.nodes[node_id].transform.matrix()
        for ancestor in self.ancestors(node_id):
            matrix = ancestor.transform.matrix() @ matrix
        return matrix

    def parent_world_matrix(self, node_id: str) -> np.ndarray:
        parent_id = self.nodes[node_id].parent_id
        return self.world_matrix(parent_id) if parent_id else np.eye(4)

    def top_level(self, node_ids: list[str]) -> list[str]:
        """Retire les nœuds dont un ancêtre figure aussi dans la liste."""
        chosen = set(node_ids)
        return [
            i
            for i in node_ids
            if i in self.nodes and not any(a.id in chosen for a in self.ancestors(i))
        ]

    def unique_name(self, base: str) -> str:
        names = {n.name for n in self.nodes.values()}
        if base not in names:
            return base
        index = 1
        while f"{base}.{index:03d}" in names:
            index += 1
        return f"{base}.{index:03d}"

    def material_for(self, node_id: str) -> Material | None:
        node = self.nodes.get(node_id)
        return self.materials.get(node.material_id) if node and node.material_id else None

    def material_users(self, material_id: str) -> list[SceneNode]:
        return [n for n in self.nodes.values() if n.material_id == material_id]

    # --- Écriture -----------------------------------------------------------
    def add(self, node: SceneNode, parent_id: str | None = None, index: int | None = None) -> None:
        if node.id in self.nodes:
            raise SceneError(f"Nœud déjà présent : {node.id}")
        if parent_id is not None and parent_id not in self.nodes:
            raise SceneError(f"Parent inconnu : {parent_id}")
        node.parent_id = parent_id
        self.nodes[node.id] = node
        self._children.setdefault(node.id, [])
        siblings = self._children.setdefault(parent_id, [])
        siblings.insert(len(siblings) if index is None else index, node.id)

    def remove(self, node_id: str) -> list[SceneNode]:
        """Retire un nœud et ses descendants ; retourne les nœuds retirés (ordre de parcours)."""
        removed = self.subtree(node_id)
        self._children[self.nodes[node_id].parent_id].remove(node_id)
        for item in removed:
            self.nodes.pop(item.id, None)
            self._children.pop(item.id, None)
        return removed

    def move(self, node_id: str, new_parent_id: str | None, index: int | None = None) -> None:
        if new_parent_id is not None and (
            new_parent_id == node_id or self.is_ancestor(node_id, new_parent_id)
        ):
            raise SceneError("Impossible de placer un nœud dans sa propre descendance.")
        node = self.nodes[node_id]
        self._children[node.parent_id].remove(node_id)
        node.parent_id = new_parent_id
        siblings = self._children.setdefault(new_parent_id, [])
        siblings.insert(len(siblings) if index is None else min(index, len(siblings)), node_id)

    def clear(self) -> None:
        self.nodes.clear()
        self._children = {None: []}
        self.materials.clear()

    def add_material(self, material: Material) -> Material:
        self.materials[material.id] = material
        return material

    def ordered_nodes(self) -> list[tuple[SceneNode, int]]:
        """Tous les nœuds avec leur rang parmi leurs frères (persistance, parents d'abord)."""
        return [(node, self.index_of(node.id)) for node in self.walk()]
