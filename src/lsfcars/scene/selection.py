"""Sélection multiple ordonnée ; le dernier élément sélectionné est l'élément « actif »."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from lsfcars.scene.graph import SceneGraph


class Selection:
    def __init__(self) -> None:
        self._ids: list[str] = []
        self._listeners: list[Callable[[], None]] = []

    def subscribe(self, listener: Callable[[], None]) -> None:
        self._listeners.append(listener)

    def _changed(self) -> None:
        for listener in list(self._listeners):
            listener()

    @property
    def ids(self) -> list[str]:
        return list(self._ids)

    @property
    def active(self) -> str | None:
        return self._ids[-1] if self._ids else None

    def __contains__(self, node_id: object) -> bool:
        return node_id in self._ids

    def __len__(self) -> int:
        return len(self._ids)

    def set(self, node_ids: Iterable[str]) -> None:
        new = list(dict.fromkeys(node_ids))
        if new != self._ids:
            self._ids = new
            self._changed()

    def clear(self) -> None:
        self.set([])

    def toggle(self, node_id: str) -> None:
        if node_id in self._ids:
            self.set([i for i in self._ids if i != node_id])
        else:
            self.set([*self._ids, node_id])

    def add(self, node_ids: Iterable[str]) -> None:
        self.set([*self._ids, *node_ids])

    def prune(self, scene: SceneGraph) -> None:
        """Retire les nœuds qui n'existent plus (après suppression ou annulation)."""
        self.set([i for i in self._ids if i in scene])
