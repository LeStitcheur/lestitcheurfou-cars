"""Contrôleur du studio : relie la session (modèle) aux vues Qt et à l'historique."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from lsfcars.core.logging_setup import get_logger
from lsfcars.editor import compat, vehicle
from lsfcars.editor import edit_state as modes
from lsfcars.editor.edit_state import EditState
from lsfcars.editor.operations import VehicleEditor
from lsfcars.importers import ImportResult
from lsfcars.project.session import ProjectSession
from lsfcars.project.store import ProjectError
from lsfcars.scene import editmesh
from lsfcars.scene.commands import Command
from lsfcars.scene.editmesh import EditError, EditResult
from lsfcars.scene.graph import NodeKind
from lsfcars.scene.transform import Transform
from lsfcars.ui.studio.import_worker import ImportWorker

log = get_logger(__name__)

# Opérations susceptibles de rendre un modèle GTA V incompatible avec FiveM (voir editor.compat)
FIVEM_RISKS = compat.ACTION_RISKS


class StudioController(QObject):
    session_changed = Signal()
    scene_changed = Signal(str)  # catégorie : structure / transform / property / material
    selection_changed = Signal()
    state_changed = Signal()  # état modifié, historique, sauvegarde automatique
    import_progress = Signal(float, str)
    import_finished = Signal(bool, str)  # succès, message
    notify = Signal(str, str, str)  # titre, message, niveau
    edit_changed = Signal()  # mode, maillage édité, type d'élément ou sélection d'éléments
    busy_changed = Signal(bool, str)  # tâche d'édition en arrière-plan (biseau Blender…)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.session: ProjectSession | None = None
        self.last_autosave = False
        self._warned: set[str] = set()
        self._worker: ImportWorker | None = None
        self._autosave = QTimer(self)
        self._autosave.timeout.connect(self.autosave_now)
        self.edit = EditState()
        self.edit.subscribe(self.edit_changed.emit)
        self.editor: VehicleEditor | None = None
        self._task = None

    # --- Session ------------------------------------------------------------
    def set_session(self, session: ProjectSession | None) -> None:
        if self.session is not None and session is not self.session:
            self.session.close()
        self.session = session
        self.last_autosave = False
        self._warned.clear()
        self.editor = VehicleEditor(session) if session is not None else None
        self.edit.reset()
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
        if self.edit.target and (self.session is None or self.edit.target not in self.session.scene):
            self.edit.reset()  # maillage édité supprimé (annulation, suppression)
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
        """Avertit (une fois par risque et par projet) si l'action menace la compatibilité FiveM."""
        if self.session is None:
            return False
        risks = compat.action_risks(self.session, action, node_ids)
        for risk in risks:
            log.warning("Compatibilité FiveM (%s) : %s", action, risk)
            if risk not in self._warned:
                self._warned.add(risk)
                self.notify.emit("Compatibilité FiveM", risk, "warning")
        return bool(risks)

    # --- Modes d'édition -------------------------------------------------------
    def set_mode(self, mode: str) -> bool:
        if self.session is None:
            return False
        if mode == modes.EDIT:
            target = self.edit_target_candidate()
            if target is None:
                self.notify.emit("Mode Édition", "Sélectionnez d'abord un maillage à modifier.", "info")
                self.edit_changed.emit()
                return False
            self.fivem_risk([target], "geometry")
            self.edit.set_mode(modes.EDIT, target)
            return True
        self.edit.set_mode(mode)
        if mode == modes.COMPONENT:
            self.select(self.selected())
        return True

    def toggle_edit_mode(self) -> None:
        self.set_mode(modes.OBJECT if self.edit.mode == modes.EDIT else modes.EDIT)

    def edit_target_candidate(self) -> str | None:
        session = self.session
        if session is None:
            return None
        for node_id in reversed(session.selection.ids):
            node = session.scene.get(node_id)
            if node is not None and node.kind is NodeKind.MESH and session.geometry_for(node) is not None:
                return node_id
            if node is not None:  # composant : premier maillage
                mesh = next((n for n in session.scene.walk(node_id) if n.kind is NodeKind.MESH), None)
                if mesh is not None:
                    return mesh.id
        return None

    def edit_mesh(self):  # type: ignore[no-untyped-def]
        if self.session is None or not self.edit.target or self.edit.target not in self.session.scene:
            return None
        return self.session.geometry_for(self.session.scene.nodes[self.edit.target])

    def _report(self, title: str, result: EditResult | None) -> None:
        if result is None:
            return
        for warning in result.warnings:
            level = "warning" if ("UV" in warning or "invalide" in warning) else "info"
            self.notify.emit(title, warning, level)
        if self.session and self.edit.target:
            node = self.session.scene.get(self.edit.target)
            if node is not None and node.extra.get("uv_status") == "invalid":
                self.fivem_risk([node.id], "uv")

    def run_edit(self, label: str, operation: Callable[[object], EditResult]) -> EditResult | None:
        """Opération sur le maillage édité (mode Édition), annulable, sans jamais planter."""
        if self.editor is None or not self.edit.target:
            self.notify.emit(label, "Passez en mode Édition sur un maillage.", "info")
            return None
        try:
            result = self.editor.edit(self.edit.target, operation, label)
        except EditError as exc:
            self.notify.emit(label, str(exc), "warning")
            return None
        self.edit.set_result(result.element, result.selection)
        self._report(label, result)
        return result

    def run(self, label: str, action: Callable[[], object]) -> object | None:
        """Opération de l'éditeur de véhicule ; les erreurs prévues deviennent des notifications."""
        if self.editor is None:
            return None
        try:
            return action()
        except EditError as exc:
            self.notify.emit(label, str(exc), "warning")
        except (ValueError, KeyError) as exc:
            log.warning("%s : %s", label, exc)
            self.notify.emit(label, f"Opération impossible : {exc}", "warning")
        return None

    def apply_edit_transform(self, node_id: str, matrix) -> None:  # type: ignore[no-untyped-def]
        if node_id != self.edit.target:
            return
        element, selection = self.edit.element, set(self.edit.selection)
        self.run_edit(
            "Transformation des sommets", lambda m: editmesh.transform_elements(m, element, selection, matrix)
        )

    def separate_selection(self) -> str | None:
        mesh = self.edit_mesh()
        if mesh is None or self.editor is None:
            return None
        faces = editmesh.convert_selection(mesh, self.edit.element, self.edit.selection, editmesh.FACE)
        target = self.edit.target
        new_id = self.run("Séparer", lambda: self.editor.separate(target, faces))
        if new_id:
            self.edit.set_result(editmesh.FACE, set())
        return new_id  # type: ignore[return-value]

    def bevel_async(self, width: float, segments: int) -> bool:
        """Biseau Blender en arrière-plan ; le résultat n'est appliqué que si le maillage n'a pas changé."""
        from lsfcars.editor.blender_ops import bevel_edges
        from lsfcars.ui.import_studio.workers import TaskWorker

        mesh = self.edit_mesh()
        if mesh is None or self._task is not None:
            return False
        edges = editmesh.convert_selection(mesh, self.edit.element, self.edit.selection, editmesh.EDGE)
        if not edges:
            self.notify.emit("Biseau", "Sélectionnez des arêtes (ou des faces) à biseauter.", "info")
            return False
        target = self.edit.target
        holder: dict = {}

        def job(progress, cancelled):  # type: ignore[no-untyped-def]
            progress(0.1, "Calcul du biseau par Blender")
            return bevel_edges(mesh, edges, width, segments, on_task=lambda t: holder.setdefault("task", t))

        worker = TaskWorker("Biseau", job, self)
        worker.on_cancel = lambda: holder.get("task") and holder["task"].cancel()
        self._task = worker
        self.busy_changed.emit(True, "Biseau en cours (Blender)…")

        def done(result) -> None:  # type: ignore[no-untyped-def]
            self._finish_task()
            if self.edit.target != target or self.edit_mesh() is not mesh:
                self.notify.emit(
                    "Biseau", "Le maillage a changé pendant le calcul : résultat ignoré.", "warning"
                )
                return
            self.run_edit("Biseau", lambda _m: result)

        worker.succeeded.connect(done)
        worker.failed.connect(
            lambda message: (self._finish_task(), self.notify.emit("Biseau", message, "warning"))
        )
        worker.cancelled.connect(
            lambda: (self._finish_task(), self.notify.emit("Biseau", "Biseau annulé.", "info"))
        )
        worker.start()
        return True

    def restore_point(self, point) -> bool:  # type: ignore[no-untyped-def]
        """Remplace la scène par un point de restauration (à enregistrer pour le rendre définitif)."""
        from lsfcars.project import restore_points

        if self.session is None:
            return False
        try:
            restored = restore_points.load(point, self.session.project)
        except ProjectError as exc:
            self.notify.emit("Point de restauration", str(exc), "warning")
            return False
        session = ProjectSession.from_project(restored)
        session.mark_dirty()
        self.set_session(session)
        self.notify.emit("Point de restauration", f"Scène restaurée : {point.name}", "success")
        return True

    def cancel_task(self) -> None:
        if self._task is not None:
            self._task.cancel()

    def _finish_task(self) -> None:
        worker, self._task = self._task, None
        if worker is not None:
            worker.wait(2000)
            worker.deleteLater()
        self.busy_changed.emit(False, "")

    # --- Commandes d'édition --------------------------------------------------
    def selected(self) -> list[str]:
        return self.session.selection.ids if self.session else []

    def select(self, node_ids: list[str], mode: str = "replace") -> None:
        if self.session is None:
            return
        selection = self.session.selection
        if self.edit.mode == modes.COMPONENT:  # mode Composant : on sélectionne le composant entier
            roots = [vehicle.component_root(self.session.scene, i) for i in node_ids]
            node_ids = list(dict.fromkeys(r for r in roots if r))
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
        if self.edit.editing:  # mode Édition : suppression des éléments sélectionnés
            element, selection = self.edit.element, set(self.edit.selection)
            if element == editmesh.VERTEX:
                self.run_edit("Suppression de sommets", lambda m: editmesh.delete_vertices(m, selection))
            else:
                faces_of = editmesh.convert_selection
                self.run_edit(
                    "Suppression de faces",
                    lambda m: editmesh.delete_faces(m, faces_of(m, element, selection, editmesh.FACE)),
                )
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
