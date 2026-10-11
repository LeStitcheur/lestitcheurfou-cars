"""Sauvegarde automatique et récupération après plantage.

Les instantanés sont écrits dans ``<données>/recovery/<project_id>.lsfc`` sans toucher au
fichier du projet. Ils sont supprimés après un enregistrement ou une fermeture normale ;
ceux qui restent au démarrage signalent une session interrompue.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from lsfcars.core.logging_setup import get_logger
from lsfcars.core.paths import app_data_dir
from lsfcars.project import store
from lsfcars.project.model import Project

log = get_logger(__name__)


def recovery_dir() -> Path:
    path = app_data_dir() / "recovery"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class RecoveryInfo:
    project_id: str
    project_path: Path
    name: str
    saved_at: str
    snapshot: Path

    @property
    def saved_at_local(self) -> str:
        try:
            return datetime.fromisoformat(self.saved_at).astimezone().strftime("%d/%m/%Y %H:%M")
        except ValueError:
            return self.saved_at


def autosave(project: Project) -> Path:
    """Écrit un instantané de récupération ; le projet lui-même n'est pas modifié."""
    snapshot = recovery_dir() / f"{project.project_id}.lsfc"
    store.save_project(project, path=snapshot)
    sidecar = snapshot.with_suffix(".json")
    sidecar.write_text(
        json.dumps(
            {
                "project_path": str(project.file_path),
                "name": project.name,
                "saved_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    log.info("Sauvegarde automatique : %s", project.name)
    return snapshot


def clear(project_id: str) -> None:
    for suffix in (".lsfc", ".json"):
        (recovery_dir() / f"{project_id}{suffix}").unlink(missing_ok=True)


def pending() -> list[RecoveryInfo]:
    """Instantanés restants (session interrompue), du plus récent au plus ancien."""
    infos: list[RecoveryInfo] = []
    for sidecar in recovery_dir().glob("*.json"):
        snapshot = sidecar.with_suffix(".lsfc")
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        if not data or not snapshot.is_file():
            sidecar.unlink(missing_ok=True)
            snapshot.unlink(missing_ok=True)
            continue
        infos.append(
            RecoveryInfo(
                sidecar.stem,
                Path(data.get("project_path", "")),
                data.get("name", sidecar.stem),
                data.get("saved_at", ""),
                snapshot,
            )
        )
    return sorted(infos, key=lambda i: i.saved_at, reverse=True)


def restore(info: RecoveryInfo) -> Project:
    """Charge l'instantané en le rattachant à l'emplacement d'origine du projet."""
    project = store.load_project(info.snapshot)
    project.file_path = info.project_path
    return project
