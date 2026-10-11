"""Session de travail : projet ouvert, maillages chargés et état « modifié »."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from lsfcars.core.logging_setup import get_logger
from lsfcars.project import store
from lsfcars.project.model import Project, SceneObject, Transform, VehicleRole, VehicleType
from lsfcars.scene import mathutils
from lsfcars.scene.loader import ModelLoadError, load_meshes
from lsfcars.scene.mesh import MeshData, combined_bounds

log = get_logger(__name__)


class ProjectSession:
    """Projet en cours d'édition. Indépendant de l'interface pour être testable."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self.meshes: dict[str, list[MeshData]] = {}
        self.missing: dict[str, str] = {}  # id -> raison
        self.dirty = False

    # --- Cycle de vie -------------------------------------------------------
    @classmethod
    def create(
        cls,
        parent_dir: str | Path,
        name: str,
        vehicle_type: VehicleType = VehicleType.CAR,
        role: VehicleRole = VehicleRole.CIVILIAN,
        description: str = "",
    ) -> ProjectSession:
        return cls(store.create_project(parent_dir, name, vehicle_type, role, description))

    @classmethod
    def open(cls, path: str | Path) -> ProjectSession:
        session = cls(store.load_project(path))
        for obj in session.project.objects:
            session._load_object_meshes(obj)
        return session

    def save(self) -> Path:
        path = store.save_project(self.project)
        self.dirty = False
        return path

    @property
    def file_path(self) -> Path:
        assert self.project.file_path is not None
        return self.project.file_path

    def mark_dirty(self) -> None:
        self.dirty = True

    # --- Objets -------------------------------------------------------------
    def _load_object_meshes(self, obj: SceneObject) -> None:
        path = self.project.project_dir / obj.asset_path
        try:
            self.meshes[obj.id] = load_meshes(path)
            self.missing.pop(obj.id, None)
        except ModelLoadError as exc:
            self.meshes[obj.id] = []
            self.missing[obj.id] = str(exc)
            log.warning("Objet « %s » non chargé : %s", obj.name, exc)

    def add_model(self, source: str | Path, name: str | None = None) -> SceneObject:
        """Importe un fichier 3D : validation, copie dans ``assets/`` puis ajout à la scène."""
        source = Path(source)
        meshes = load_meshes(source)  # lève ModelLoadError avant toute copie
        asset_path = store.import_asset(self.project, source)
        obj = SceneObject(name=name or source.stem, asset_path=asset_path)
        self.project.objects.append(obj)
        self.meshes[obj.id] = meshes
        self.mark_dirty()
        log.info("Objet ajouté : « %s » (%s)", obj.name, asset_path)
        return obj

    def remove_object(self, object_id: str) -> SceneObject | None:
        obj = self.project.find_object(object_id)
        if obj is None:
            return None
        self.project.objects.remove(obj)
        self.meshes.pop(object_id, None)
        self.missing.pop(object_id, None)
        self.mark_dirty()
        log.info("Objet retiré de la scène : « %s » (le fichier reste dans assets/)", obj.name)
        return obj

    def rename_object(self, object_id: str, name: str) -> None:
        obj = self.project.find_object(object_id)
        name = name.strip()
        if obj and name and obj.name != name:
            obj.name = name
            self.mark_dirty()

    def set_transform(self, object_id: str, transform: Transform) -> None:
        obj = self.project.find_object(object_id)
        if obj and obj.transform != transform:
            obj.transform = transform
            self.mark_dirty()

    def set_visible(self, object_id: str, visible: bool) -> None:
        obj = self.project.find_object(object_id)
        if obj and obj.visible != visible:
            obj.visible = visible
            self.mark_dirty()

    # --- Informations -------------------------------------------------------
    def stats(self, object_id: str | None = None) -> tuple[int, int]:
        """(triangles, sommets) d'un objet ou de toute la scène."""
        ids = [object_id] if object_id else list(self.meshes)
        meshes = [m for i in ids for m in self.meshes.get(i, [])]
        return sum(m.triangle_count for m in meshes), sum(m.vertex_count for m in meshes)

    def world_bounds(
        self, object_ids: list[str] | None = None, only_visible: bool = True
    ) -> tuple[np.ndarray, np.ndarray] | None:
        """Boîte englobante monde des objets donnés (tous par défaut)."""
        corners_all = []
        for obj in self.project.objects:
            if object_ids is not None and obj.id not in object_ids:
                continue
            if only_visible and not obj.visible:
                continue
            bounds = combined_bounds(self.meshes.get(obj.id, []))
            if bounds is None:
                continue
            bmin, bmax = bounds
            corners = np.array(
                [
                    [x, y, z]
                    for x in (bmin[0], bmax[0])
                    for y in (bmin[1], bmax[1])
                    for z in (bmin[2], bmax[2])
                ]
            )
            corners_all.append(mathutils.transform_points(obj.transform.matrix(), corners))
        if not corners_all:
            return None
        pts = np.vstack(corners_all)
        return pts.min(axis=0), pts.max(axis=0)
