"""Contrôleur du studio : relie la session (modèle) aux vues Qt et à l'historique."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from lsfcars.core.logging_setup import get_logger
from lsfcars.importers import ImportResult
from lsfcars.project.session import ProjectSession
from lsfcars.project.store import ProjectError
from lsfcars.scene.commands import Command
from lsfcars.scene.transform import Transform
from lsfcars.ui.studio.import_worker import ImportWorker

log = get_logger(__name__)

# Opérations susceptibles de rendre un modèle GTA V incompatible avec FiveM à la réexportation
FIVEM_RISKS = {
    "rename": "Les noms d'os sont utilisés par le jeu (portes, roues, feux…) : un os renommé peut "
    "ne plus fonctionner dans FiveM.",
    "delete": "Supprimer un os ou une pièce d'origine peut casser l'animation des portes, des roues "
    "ou des feux dans FiveM.",
    "reparent": "Modifier la hiérarchie des os d'origine peut rendre le modèle incompatible avec FiveM.",
    "group": "Regrouper des éléments d'origine modifie la hiérarchie attendue par FiveM.",
    "scale": "Une mise à l'échelle non uniforme d'une pièce d'origine peut déformer les collisions et "
    "les points d'ancrage dans FiveM.",
}


class StudioController(QObject):
    session_changed = Signal()
    scene_changed = Signal(str)  # catégorie : structure / transform / property / material
    selection_changed = Signal()
    state_changed = Signal()  # état modifié, historique, sauvegarde automatique
    import_progress = Signal(float, str)
    import_finished = Signal(bool, str)  # succès, message
    notify = Signal(str, str, str)  # titre, message, niveau

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.session: ProjectSession | None = None
        self.last_autosave = False
        self._warned: set[str] = set()
        self._worker: ImportWorker | None = None
        self._autosave = QTimer(self)
        self._autosave.timeout.connect(self.autosave_now)

    # --- Session ------------------------------------------------------------
    def set_session(self, session: ProjectSession | None) -> None:
        if self.session is not None and session is not self.session:
            self.session.close()
        self.session = session
        self.last_autosave = False
        self._warned.clear()
        if session is not None:
            session.stack.subscribe(self._on_command)
            session.selection.subscribe(self.selection_changed.emit)
        self.session_changed.emit()
        self.state_changed.emit()

    def set_autosave_interval(self, minutes: int) -> None:
        if minutes > 0:
            self._autosave.start(minutes * 60_000)
        else:
            self._autosave.stop()

    def autosave_now(self) -> bool:
        if self.session is None:
            return False
        try:
            saved = self.session.autosave() is not None
        except ProjectError as exc:
            log.warning("Sauvegarde automatique impossible : %s", exc)
            return False
        if saved:
            self.last_autosave = True
            self.state_changed.emit()
        return saved

    def _on_command(self, command: Command, _action: str) -> None:
        self.last_autosave = False
        self.scene_changed.emit(command.kind)
        self.state_changed.emit()

    # --- Import asynchrone --------------------------------------------------
    def is_importing(self) -> bool:
        return self._worker is not None

    def import_model_async(self, path: str | Path) -> ImportWorker | None:
        if self.session is None or self.is_importing():
            return None
        worker = ImportWorker(path, self)
        worker.progress.connect(self.import_progress)
        worker.succeeded.connect(self._import_succeeded)
        worker.failed.connect(lambda message: self._import_done(False, message))
        self._worker = worker
        self.import_progress.emit(0.0, f"Lecture de {Path(path).name}")
        worker.start()
        return worker

    def _import_succeeded(self, result: ImportResult) -> None:
        if self.session is None:
            self._import_done(False, "Le projet a été fermé pendant l'import.")
            return
        try:
            self.import_progress.emit(0.95, "Copie dans le projet")
            self.session.apply_import(result)
        except ProjectError as exc:
            self._import_done(False, str(exc))
            return
        message = (
            f"{result.source.name} : {result.triangle_count:,} triangles, "
            f"{len(result.meshes)} maillages, {len(result.materials)} matériaux"
        ).replace(",", " ")
        self._import_done(True, message)

    def _import_done(self, ok: bool, message: str) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.wait(5000)
            worker.deleteLater()
        self.import_progress.emit(1.0 if ok else 0.0, "Import terminé" if ok else "Échec")
        self.import_finished.emit(ok, message)

    # --- Compatibilité FiveM ---------------------------------------------------
    def fivem_risk(self, node_ids: list[str], action: str) -> bool:
        """Avertit (une fois par action et par projet) si des éléments GTA V d'origine sont touchés."""
        if self.session is None or action not in FIVEM_RISKS:
            return False
        scene = self.session.scene
        touched = [
            node
            for node_id in node_ids
            if node_id in scene
            for node in scene.subtree(node_id)
            if node.extra.get("gta")
        ]
        if not touched:
            return False
        log.warning("Compatibilité FiveM (%s) : %s", action, ", ".join(n.name for n in touched[:5]))
        if action not in self._warned:
            self._warned.add(action)
            self.notify.emit("Compatibilité FiveM", FIVEM_RISKS[action], "warning")
        return True

    # --- Commandes d'édition --------------------------------------------------
    def selected(self) -> list[str]:
        return self.session.selection.ids if self.session else []

    def select(self, node_ids: list[str], mode: str = "replace") -> None:
        if self.session is None:
            return
        selection = self.session.selection
        if mode == "toggle":
            for node_id in node_ids:
                selection.toggle(node_id)
        elif mode == "add":
            selection.add(node_ids)
        else:
            selection.set(node_ids)

    def undo(self) -> None:
        if self.session and self.session.stack.can_undo():
            label = self.session.stack.undo_label()
            self.session.stack.undo()
            self.notify.emit("Annulé", label, "info")

    def redo(self) -> None:
        if self.session and self.session.stack.can_redo():
            label = self.session.stack.redo_label()
            self.session.stack.redo()
            self.notify.emit("Rétabli", label, "info")

    def apply_transforms(self, changes: dict[str, Transform], merge_key: object = None) -> None:
        if self.session:
            scaled = [i for i, t in changes.items() if len({round(v, 6) for v in t.scale}) > 1]
            if scaled:
                self.fivem_risk(scaled, "scale")
            self.session.set_transforms(changes, merge_key=merge_key)

    def delete_selected(self) -> int:
        if not self.session:
            return 0
        self.fivem_risk(self.selected(), "delete")
        count = self.session.delete(self.selected())
        if count == 0 and self.selected():
            self.notify.emit(
                "Suppression impossible", "Les éléments sélectionnés sont verrouillés.", "warning"
            )
        return count

    def duplicate_selected(self) -> list[str]:
        return self.session.duplicate(self.selected()) if self.session else []

    def group_selected(self) -> str | None:
        if not self.session:
            return None
        self.fivem_risk(self.selected(), "group")
        return self.session.group(self.selected())

    def ungroup_selected(self) -> None:
        if self.session and self.session.selection.active:
            self.session.ungroup(self.session.selection.active)

    def set_visible(self, node_ids: list[str], visible: bool) -> None:
        if self.session:
            self.session.set_visible(node_ids, visible)

    def set_locked(self, node_ids: list[str], locked: bool) -> None:
        if self.session:
            self.session.set_locked(node_ids, locked)

    def rename(self, node_id: str, name: str) -> None:
        if self.session:
            node = self.session.scene.get(node_id)
            if node is not None and node.extra.get("gta", {}).get("role") == "bone" and name != node.name:
                self.fivem_risk([node_id], "rename")
            self.session.rename(node_id, name)

    def reparent(self, node_ids: list[str], parent_id: str | None) -> None:
        if self.session:
            self.fivem_risk(node_ids, "reparent")
            self.session.reparent(node_ids, parent_id)
