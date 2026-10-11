"""Lecture d'un modèle 3D dans un thread (l'interface et le viewport restent fluides)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from lsfcars.importers import ImportResult, ModelLoadError, load_model


class ImportWorker(QThread):
    progress = Signal(float, str)
    succeeded = Signal(object)  # ImportResult
    failed = Signal(str)

    def __init__(self, path: str | Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.path = Path(path)
        self.result: ImportResult | None = None
        self.error: str | None = None

    def run(self) -> None:  # thread secondaire : aucune modification de la session ici
        try:
            self.result = load_model(self.path, lambda v, t: self.progress.emit(v, t))
        except ModelLoadError as exc:
            self.error = str(exc)
        except Exception as exc:  # erreur inattendue d'une bibliothèque tierce
            self.error = f"Erreur inattendue pendant la lecture : {exc}"
        if self.error:
            self.failed.emit(self.error)
        else:
            self.succeeded.emit(self.result)
