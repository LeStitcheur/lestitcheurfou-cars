"""Historique annuler / rétablir (motif commande) sur le graphe de scène."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from lsfcars.scene.graph import SceneGraph, SceneNode
from lsfcars.scene.materials import Material
from lsfcars.scene.transform import Transform, decompose

# Catégories : indiquent à l'interface quoi rafraîchir.
STRUCTURE = "structure"
TRANSFORM = "transform"
PROPERTY = "property"
MATERIAL = "material"


class Command:
    label = "Modification"
    kind = PROPERTY

    def redo(self, scene: SceneGraph) -> None:
        raise NotImplementedError

    def undo(self, scene: SceneGraph) -> None:
        raise NotImplementedError

    def merge_key(self) -> object | None:
        """Deux commandes consécutives de même clé fusionnent (glisser continu)."""
        return None

    def merge(self, other: Command) -> bool:
        return False

    def node_ids(self) -> list[str]:
        return []


@dataclass
class SetTransforms(Command):
    changes: dict[str, tuple[Transform, Transform]]
    label: str = "Transformation"
    key: object | None = None
    kind: str = TRANSFORM

    def redo(self, scene: SceneGraph) -> None:
        for node_id, (_, after) in self.changes.items():
            scene.nodes[node_id].transform = after.copy()

    def undo(self, scene: SceneGraph) -> None:
        for node_id, (before, _) in self.changes.items():
            scene.nodes[node_id].transform = before.copy()

    def merge_key(self) -> object | None:
        return self.key

    def merge(self, other: Command) -> bool:
        if not isinstance(other, SetTransforms) or set(other.changes) != set(self.changes):
            return False
        self.changes = {i: (self.changes[i][0], other.changes[i][1]) for i in self.changes}
        return True

    def node_ids(self) -> list[str]:
        return list(self.changes)


@dataclass
class SetNodeField(Command):
    """Renommage, visibilité, verrouillage (un champ, plusieurs nœuds)."""

    field_name: str
    changes: dict[str, tuple[object, object]]
    label: str = "Modification"
    kind: str = PROPERTY

    def redo(self, scene: SceneGraph) -> None:
        for node_id, (_, after) in self.changes.items():
            setattr(scene.nodes[node_id], self.field_name, after)

    def undo(self, scene: SceneGraph) -> None:
        for node_id, (before, _) in self.changes.items():
            setattr(scene.nodes[node_id], self.field_name, before)

    def node_ids(self) -> list[str]:
        return list(self.changes)


@dataclass
class SetMaterialProperties(Command):
    material_id: str
    before: dict
    after: dict
    label: str = "Matériau"
    key: object | None = None
    kind: str = MATERIAL

    def redo(self, scene: SceneGraph) -> None:
        scene.materials[self.material_id].apply(self.after)

    def undo(self, scene: SceneGraph) -> None:
        scene.materials[self.material_id].apply(self.before)

    def merge_key(self) -> object | None:
        return self.key

    def merge(self, other: Command) -> bool:
        if not isinstance(other, SetMaterialProperties) or other.material_id != self.material_id:
            return False
        self.before = {**other.before, **self.before}
        self.after = {**self.after, **other.after}
        return True


@dataclass
class AddMaterial(Command):
    material: Material
    label: str = "Nouveau matériau"
    kind: str = MATERIAL

    def redo(self, scene: SceneGraph) -> None:
        scene.materials[self.material.id] = self.material

    def undo(self, scene: SceneGraph) -> None:
        scene.materials.pop(self.material.id, None)


@dataclass
class AssignMaterial(Command):
    targets: list[str]
    material_id: str | None
    label: str = "Affectation du matériau"
    kind: str = MATERIAL
    before: dict[str, str | None] = field(default_factory=dict)

    def redo(self, scene: SceneGraph) -> None:
        for node_id in self.targets:
            node = scene.nodes[node_id]
            self.before.setdefault(node_id, node.material_id)
            node.material_id = self.material_id

    def undo(self, scene: SceneGraph) -> None:
        for node_id, previous in self.before.items():
            scene.nodes[node_id].material_id = previous

    def node_ids(self) -> list[str]:
        return list(self.targets)


@dataclass
class InsertNodes(Command):
    """Ajoute des sous-arbres (import, duplication). ``snapshots`` : parents avant enfants."""

    snapshots: list[dict]
    roots: list[tuple[str, str | None, int | None]]  # (id, parent, rang) des racines insérées
    label: str = "Ajout"
    materials: list[Material] = field(default_factory=list)
    kind: str = STRUCTURE

    def redo(self, scene: SceneGraph) -> None:
        for material in self.materials:
            scene.materials.setdefault(material.id, material)
        positions = {node_id: (parent, index) for node_id, parent, index in self.roots}
        for snapshot in self.snapshots:
            node = SceneNode.from_snapshot(snapshot)
            if node.id in positions:
                parent, index = positions[node.id]
                scene.add(node, parent, index)
            else:
                scene.add(node, node.parent_id)

    def undo(self, scene: SceneGraph) -> None:
        for node_id, _, _ in reversed(self.roots):
            if node_id in scene:
                scene.remove(node_id)
        for material in self.materials:
            if not scene.material_users(material.id):
                scene.materials.pop(material.id, None)

    def node_ids(self) -> list[str]:
        return [node_id for node_id, _, _ in self.roots]


@dataclass
class RemoveNodes(Command):
    targets: list[str]
    label: str = "Suppression"
    kind: str = STRUCTURE
    saved: list[tuple[str | None, int, list[dict]]] = field(default_factory=list)

    def redo(self, scene: SceneGraph) -> None:
        self.saved = []
        for node_id in scene.top_level(self.targets):
            node = scene.nodes[node_id]
            snapshots = [n.snapshot() for n in scene.subtree(node_id)]
            self.saved.append((node.parent_id, scene.index_of(node_id), snapshots))
            scene.remove(node_id)

    def undo(self, scene: SceneGraph) -> None:
        for parent_id, index, snapshots in reversed(self.saved):
            for position, snapshot in enumerate(snapshots):
                node = SceneNode.from_snapshot(snapshot)
                scene.add(
                    node,
                    parent_id if position == 0 else node.parent_id,
                    index if position == 0 else None,
                )

    def node_ids(self) -> list[str]:
        return list(self.targets)


@dataclass
class MoveNodes(Command):
    """Change le parent en conservant la position dans le monde."""

    targets: list[str]
    new_parent_id: str | None
    label: str = "Déplacement dans la hiérarchie"
    kind: str = STRUCTURE
    before: list[tuple[str, str | None, int, Transform]] = field(default_factory=list)

    def redo(self, scene: SceneGraph) -> None:
        self.before = []
        parent = scene.world_matrix(self.new_parent_id) if self.new_parent_id else np.eye(4)
        inverse = np.linalg.inv(parent)
        for node_id in scene.top_level(self.targets):
            node = scene.nodes[node_id]
            world = scene.world_matrix(node_id)
            self.before.append(
                (node_id, node.parent_id, scene.index_of(node_id), node.transform.copy())
            )
            scene.move(node_id, self.new_parent_id)
            node.transform = decompose(inverse @ world)

    def undo(self, scene: SceneGraph) -> None:
        for node_id, parent_id, index, transform in reversed(self.before):
            scene.move(node_id, parent_id, index)
            scene.nodes[node_id].transform = transform.copy()

    def node_ids(self) -> list[str]:
        return list(self.targets)


@dataclass
class CompositeCommand(Command):
    commands: list[Command]
    label: str = "Modification"
    kind: str = STRUCTURE

    def redo(self, scene: SceneGraph) -> None:
        for command in self.commands:
            command.redo(scene)

    def undo(self, scene: SceneGraph) -> None:
        for command in reversed(self.commands):
            command.undo(scene)

    def node_ids(self) -> list[str]:
        return [i for c in self.commands for i in c.node_ids()]


Listener = Callable[[Command, str], None]


class UndoStack:
    """Pile d'historique avec point « enregistré » et fusion des modifications continues."""

    def __init__(self, scene: SceneGraph, limit: int = 200) -> None:
        self.scene = scene
        self.limit = limit
        self._done: list[Command] = []
        self._undone: list[Command] = []
        self._clean_depth: int | None = 0
        self._listeners: list[Listener] = []

    def subscribe(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def _notify(self, command: Command, action: str) -> None:
        for listener in list(self._listeners):
            listener(command, action)

    def push(self, command: Command, execute: bool = True) -> Command:
        if execute:
            command.redo(self.scene)
        if self._clean_depth is not None and self._clean_depth > len(self._done):
            self._clean_depth = None  # l'état enregistré était dans les commandes annulées
        last = self._done[-1] if self._done else None
        key = command.merge_key()
        mergeable = (
            key is not None
            and last is not None
            and last.merge_key() == key
            and len(self._done) != self._clean_depth  # ne pas fusionner avec l'état enregistré
        )
        if not (mergeable and last.merge(command)):
            self._done.append(command)
            if len(self._done) > self.limit:
                self._done.pop(0)
                if self._clean_depth is not None:
                    self._clean_depth = self._clean_depth - 1 if self._clean_depth > 0 else None
        self._undone.clear()
        self._notify(command, "do")
        return command

    def undo(self) -> Command | None:
        if not self._done:
            return None
        command = self._done.pop()
        command.undo(self.scene)
        self._undone.append(command)
        self._notify(command, "undo")
        return command

    def redo(self) -> Command | None:
        if not self._undone:
            return None
        command = self._undone.pop()
        command.redo(self.scene)
        self._done.append(command)
        self._notify(command, "redo")
        return command

    def can_undo(self) -> bool:
        return bool(self._done)

    def can_redo(self) -> bool:
        return bool(self._undone)

    def undo_label(self) -> str:
        return self._done[-1].label if self._done else ""

    def redo_label(self) -> str:
        return self._undone[-1].label if self._undone else ""

    def mark_clean(self) -> None:
        self._clean_depth = len(self._done)

    def is_clean(self) -> bool:
        return self._clean_depth == len(self._done)

    def clear(self) -> None:
        self._done.clear()
        self._undone.clear()
        self._clean_depth = 0
