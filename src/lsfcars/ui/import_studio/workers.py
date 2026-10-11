"""Tâches longues en arrière-plan (analyse, décodage, Blender) avec progression et annulation."""

from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, Signal

from lsfcars.core.logging_setup import get_logger
from lsfcars.fivem.errors import FormatError
from lsfcars.fivem.resource import AnalysisCancelled
from lsfcars.fivem.sollumz import TaskCancelled
from lsfcars.importers.base import ModelLoadError

log = get_logger(__name__)

Job = Callable[[Callable[[float, str], None], Callable[[], bool]], object]
EXPECTED = (FormatError, ModelLoadError, OSError, RuntimeError, TimeoutError)


class TaskWorker(QThread):
    """Exécute ``job(progress, cancelled)`` dans un thread. Ne touche jamais à l'interface."""

    progress = Signal(float, str)
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, label: str, job: Job, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.label = label
        self._job = job
        self._cancel = threading.Event()
        self.on_cancel: Callable[[], None] | None = None  # ex. arrêt d'un processus Blender

    def cancel(self) -> None:
        self._cancel.set()
        if self.on_cancel is not None:
            self.on_cancel()

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def run(self) -> None:
        try:
            result = self._job(lambda v, t: self.progress.emit(v, t), self._cancel.is_set)
        except (AnalysisCancelled, TaskCancelled):
            self.cancelled.emit()
            return
        except EXPECTED as exc:
            if self._cancel.is_set():
                self.cancelled.emit()
            else:
                self.failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 (jamais de plantage sur une ressource invalide)
            log.exception("Tâche « %s » interrompue", self.label)
            self.failed.emit(f"Erreur inattendue : {exc}")
            return
        if self._cancel.is_set():
            self.cancelled.emit()
        else:
            self.succeeded.emit(result)
