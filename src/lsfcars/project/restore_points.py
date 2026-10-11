"""Points de restauration : instantanés nommés d'un projet, enregistrés à côté du ``.lsfc``.

``MonProjet/restore_points/AAAAMMJJ-HHMMSS_<nom>.lsfc`` : copie complète de la base (scène,
géométrie locale, matériaux, ancrages). Les fichiers de ``assets/`` sont partagés (ils ne sont
jamais modifiés par l'éditeur). Restaurer remplace la scène de la session ; le projet doit
ensuite être enregistré pour rendre la restauration définitive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from lsfcars.core.logging_setup import get_logger
from lsfcars.project import store
from lsfcars.project.model import Project

log = get_logger(__name__)

FOLDER = "restore_points"
MAX_POINTS = 20
_NAME = re.compile(r"^(\d{8}-\d{6})_(.*)\.lsfc$")


@dataclass
class RestorePoint:
    path: Path
    name: str
    created: datetime

    @property
    def label(self) -> str:
        return f"{self.name} — {self.created:%d/%m/%Y %H:%M:%S}"


def folder(project: Project) -> Path:
    return project.project_dir / FOLDER


def create(project: Project, name: str = "Point de restauration") -> RestorePoint:
    stamp = datetime.now()
    clean = re.sub(r"[^\w\- ]+", "_", name).strip()[:40] or "point"
    path = folder(project) / f"{stamp:%Y%m%d-%H%M%S}_{clean}.lsfc"
    counter = 2
    while path.exists():
        path = path.with_name(f"{stamp:%Y%m%d-%H%M%S}_{clean}_{counter}.lsfc")
        counter += 1
    store.save_project(project, path)
    for old in list_points(project)[MAX_POINTS:]:
        old.path.unlink(missing_ok=True)
    log.info("Point de restauration créé : %s", path.name)
    return RestorePoint(path, name, stamp)


def list_points(project: Project) -> list[RestorePoint]:
    """Points du plus récent au plus ancien."""
    if project.file_path is None or not folder(project).is_dir():
        return []
    points = []
    for path in folder(project).glob("*.lsfc"):
        match = _NAME.match(path.name)
        if not match:
            continue
        try:
            created = datetime.strptime(match.group(1), "%Y%m%d-%H%M%S")
        except ValueError:
            continue
        points.append(RestorePoint(path, match.group(2).replace("_", " "), created))
    return sorted(points, key=lambda p: (p.created, p.path.name), reverse=True)


def load(point: RestorePoint, project: Project) -> Project:
    """Projet restauré, rattaché au fichier et à l'identifiant du projet courant."""
    restored = store.load_project(point.path)
    restored.file_path = project.file_path
    restored.project_id = project.project_id
    return restored


def delete(point: RestorePoint) -> None:
    point.path.unlink(missing_ok=True)
