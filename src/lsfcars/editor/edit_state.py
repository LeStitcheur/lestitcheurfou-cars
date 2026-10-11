"""État des modes d'édition (Objet, Édition, Composant) partagé par le viewport et les panneaux.

Pur Python (sans Qt) : les vues s'abonnent avec ``subscribe``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from lsfcars.scene import editmesh

OBJECT, EDIT, COMPONENT = "object", "edit", "component"
MODE_LABELS = {OBJECT: "Objet", EDIT: "Édition", COMPONENT: "Composant"}
MODE_HINTS = {
    OBJECT: "Sélection, déplacement, rotation, échelle, duplication, hiérarchie (Tab : mode Édition)",
    EDIT: "Modifier le maillage : sommets, arêtes, faces (Tab : retour au mode Objet)",
    COMPONENT: "Composants entiers : isolation, remplacement, variantes, pivots, points d'attache",
}


class EditState:
    def __init__(self) -> None:
        self.mode = OBJECT
        self.target: str | None = None  # maillage en cours d'édition
        self.element = editmesh.FACE
        self.selection: set = set()
        self.xray = False
        self._listeners: list[Callable[[], None]] = []

    def subscribe(self, listener: Callable[[], None]) -> None:
        self._listeners.append(listener)

    def _changed(self) -> None:
        for listener in list(self._listeners):
            listener()

    @property
    def editing(self) -> bool:
        return self.mode == EDIT and self.target is not None

    def set_mode(self, mode: str, target: str | None = None) -> None:
        if mode not in MODE_LABELS:
            raise ValueError(mode)
        if mode == EDIT and target is None:
            mode = OBJECT
        new_target = target if mode == EDIT else None
        changed = mode != self.mode or new_target != self.target
        if new_target != self.target:
            self.selection = set()
        self.mode, self.target = mode, new_target
        if changed:
            self._changed()

    def set_element(self, element: str, mesh=None) -> None:  # type: ignore[no-untyped-def]
        """Change le type d'élément ; la sélection est convertie si le maillage est fourni."""
        if element == self.element:
            return
        if mesh is not None and self.selection:
            self.selection = editmesh.convert_selection(mesh, self.element, self.selection, element)
        else:
            self.selection = set()
        self.element = element
        self._changed()

    def select(self, items: Iterable, mode: str = "replace") -> None:
        items = set(items)
        if mode == "add":
            new = self.selection | items
        elif mode == "toggle":
            new = self.selection ^ items
        else:
            new = items
        if new != self.selection:
            self.selection = new
            self._changed()

    def set_result(self, element: str, selection: set) -> None:
        """Après une opération : sélection retournée par ``editmesh`` (vide si non pertinente)."""
        self.element = element or self.element
        self.selection = set(selection)
        self._changed()

    def reset(self) -> None:
        self.mode, self.target, self.selection = OBJECT, None, set()
        self._changed()
