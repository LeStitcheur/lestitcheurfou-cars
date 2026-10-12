"""Transformations géométriques réelles d'un véhicule (sans Qt) : champs de déformation lisses
exprimés dans le repère du véhicule, pièces ajoutées, déplacements rigides, matériaux.

``VehicleState`` est une copie de travail du véhicule (maillages locaux, matrices monde) sur
laquelle s'appliquent les opérations. Le même état sert à la **prévisualisation** (rendu des
propositions, rien n'est écrit dans le projet) et à **l'application** : ``engine.py`` convertit
ses différences en commandes annulables. Une transformation présentée comme appliquée
correspond donc toujours à une modification effective des données du projet.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from lsfcars.lorefriendly.components import RIGID_KINDS, VehicleComponents, VehicleFrame
from lsfcars.scene.editmesh import EditError
from lsfcars.scene.graph import new_node_id
from lsfcars.scene.mesh import MeshData, compute_vertex_normals

NON_DEFORMABLE = RIGID_KINDS | {"technical"}


class IncompatibleTransformation(EditError):
    """Transformation impossible sur ce véhicule (composant absent, géométrie insuffisante…)."""


def smoothstep(x, a: float, b: float) -> np.ndarray:  # type: ignore[no-untyped-def]
    if abs(b - a) < 1e-9:
        return (np.asarray(x) >= a).astype(np.float64)
    t = np.clip((np.asarray(x, np.float64) - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def bump(x, a: float, b: float, soft: float) -> np.ndarray:  # type: ignore[no-untyped-def]
    """1 sur [a, b], transitions lisses de largeur ``soft`` de part et d'autre."""
    return smoothstep(x, a - soft, a) * (1.0 - smoothstep(x, b, b + soft))


@dataclass
class Landmarks:
    """Repères mesurés sur la carrosserie (coordonnées normalisées u, v)."""

    front_axle: float
    rear_axle: float
    wheel_radius: float  # en u (rayon / longueur)
    beltline: float  # v de la ligne de caisse (haut du capot / du coffre)
    cabin_start: float  # u arrière de l'habitacle (lunette)
    cabin_end: float  # u avant de l'habitacle (pied de pare-brise)
    hood_top: float  # v du capot
    deck_top: float  # v du coffre
    has_cabin: bool
    measured_wheels: bool

    def to_dict(self) -> dict:
        return {k: round(float(v), 4) if isinstance(v, float) else v for k, v in self.__dict__.items()}


def height_profile(points: np.ndarray, frame: VehicleFrame, bins: int = 40) -> tuple[np.ndarray, np.ndarray]:
    """Hauteur maximale (v) par tranche longitudinale (u) : silhouette latérale mesurée."""
    u, v, _ = frame.coords(points)
    edges = np.linspace(0, 1, bins + 1)
    index = np.clip(np.digitize(u, edges) - 1, 0, bins - 1)
    top = np.full(bins, np.nan)
    np.fmax.at(top, index, v)
    centers = (edges[:-1] + edges[1:]) / 2
    valid = ~np.isnan(top)
    if valid.any() and not valid.all():
        top = np.interp(centers, centers[valid], top[valid])
    return centers, np.nan_to_num(top)


def landmarks(points: np.ndarray, frame: VehicleFrame, vc: VehicleComponents | None) -> Landmarks:
    centers, top = height_profile(points, frame)
    peak = float(top.max()) if len(top) else 1.0
    cabin = centers[top >= peak - 0.18 * max(peak, 1e-6)]
    front_axle = vc.axle_u("avant") if vc else None
    rear_axle = vc.axle_u("arrière") if vc else None
    radius = (vc.wheel_radius() or 0.0) / max(frame.length, 1e-9) if vc else 0.0
    measured = front_axle is not None and rear_axle is not None
    front_axle = 0.8 if front_axle is None else front_axle
    rear_axle = 0.2 if rear_axle is None else rear_axle
    radius = radius or 0.075
    if len(cabin):
        cabin_start, cabin_end = float(cabin.min()), float(cabin.max())
    else:
        cabin_start, cabin_end = 0.35, 0.65
    has_cabin = (cabin_end - cabin_start) < 0.85 and peak > 0
    hood = float(np.interp(min(front_axle + radius, 0.98), centers, top)) if len(top) else 0.5
    deck = float(np.interp(max(rear_axle - radius, 0.02), centers, top)) if len(top) else 0.5
    belt = min(max(min(hood, deck) if has_cabin else 0.6 * peak, 0.15), 0.9)
    return Landmarks(
        front_axle, rear_axle, radius, belt, cabin_start, cabin_end, hood, deck, has_cabin, measured
    )


@dataclass(frozen=True)
class Deformation:
    key: str
    label: str
    unit: str  # m / ratio
    minimum: float
    maximum: float
    default: float
    description: str
    needs_cabin: bool = False


DEFORMATIONS: dict[str, Deformation] = {
    d.key: d
    for d in (
        Deformation("nose_length", "Longueur du porte-à-faux avant", "m", -0.25, 0.35, 0.12,
                    "Allonge ou raccourcit la face avant au-delà de l'essieu (empattement conservé)."),
        Deformation("tail_length", "Longueur du porte-à-faux arrière", "m", -0.25, 0.35, 0.1,
                    "Allonge ou raccourcit l'arrière au-delà de l'essieu."),
        Deformation("hood_height", "Hauteur du capot", "m", -0.12, 0.12, 0.04,
                    "Relève ou abaisse le capot (face avant plus massive ou plus effilée).", True),
        Deformation("roof_height", "Hauteur du pavillon", "m", -0.18, 0.12, -0.06,
                    "Abaisse (toit « chopé ») ou relève le pavillon ; vitrages étirés.", True),
        Deformation("roof_slope", "Chute de pavillon (fastback)", "m", -0.05, 0.3, 0.12,
                    "Abaisse progressivement l'arrière du pavillon (silhouette coupé).", True),
        Deformation("front_taper", "Effilement de la face avant", "ratio", -0.1, 0.25, 0.08,
                    "Resserre les angles avant (vue de dessus)."),
        Deformation("rear_taper", "Effilement de l'arrière", "ratio", -0.1, 0.25, 0.06,
                    "Resserre les angles arrière (vue de dessus)."),
        Deformation("fender_width", "Élargissement des ailes", "m", -0.03, 0.12, 0.05,
                    "Bombe les ailes au droit des roues (passages de roues marqués)."),
        Deformation("shoulder", "Épaules de caisse", "m", -0.04, 0.08, 0.03,
                    "Accentue la ligne d'épaule à hauteur de ceinture.", True),
        Deformation("ride_height", "Garde au sol", "m", -0.1, 0.2, 0.06,
                    "Rehausse ou abaisse la caisse ; les roues restent en place."),
        Deformation("rake", "Assiette (avant plongeant)", "m", -0.06, 0.08, 0.03,
                    "Abaisse l'avant et relève l'arrière (assiette dynamique)."),
        Deformation("front_bumper_depth", "Avancée du bouclier avant", "m", -0.08, 0.15, 0.05,
                    "Avance ou recule la partie basse de la face avant."),
        Deformation("rear_bumper_depth", "Avancée du bouclier arrière", "m", -0.08, 0.15, 0.05,
                    "Recule ou avance la partie basse de l'arrière."),
        Deformation("ducktail", "Relevé du coffre (ducktail)", "m", -0.06, 0.12, 0.05,
                    "Relève le bord arrière du coffre ou du hayon."),
    )
}  # fmt: skip


def displacement(
    key: str, amount: float, frame: VehicleFrame, lm: Landmarks, points: np.ndarray
) -> np.ndarray:
    """Déplacement monde (N, 3) d'un champ de déformation appliqué à des points monde."""
    u, v, w = frame.coords(points)
    ru = lm.wheel_radius
    along = np.zeros_like(u)
    vertical = np.zeros_like(u)
    lateral = np.zeros_like(u)
    half_width = frame.width / 2
    if key == "nose_length":
        start = min(lm.front_axle + ru, 0.93)
        along = amount * smoothstep(u, start, start + 0.08)
    elif key == "tail_length":
        end = max(lm.rear_axle - ru, 0.07)
        along = -amount * (1.0 - smoothstep(u, end - 0.08, end))
    elif key == "hood_height":
        vertical = (
            amount
            * smoothstep(u, lm.cabin_end - 0.02, lm.cabin_end + 0.06)
            * smoothstep(v, 0.45 * lm.hood_top, lm.hood_top)
        )
    elif key == "roof_height":
        vertical = (
            amount
            * bump(u, lm.cabin_start, lm.cabin_end, 0.06)
            * smoothstep(v, lm.beltline, lm.beltline + 0.6 * (1 - lm.beltline))
        )
    elif key == "roof_slope":
        middle = (lm.cabin_start + lm.cabin_end) / 2
        rising = smoothstep(u, lm.cabin_start - 0.15, lm.cabin_start)
        weight_u = np.where(u < lm.cabin_start, rising, 1.0 - smoothstep(u, lm.cabin_start, middle))
        vertical = -amount * weight_u * smoothstep(v, lm.beltline, lm.beltline + 0.5 * (1 - lm.beltline))
    elif key == "front_taper":
        lateral = -amount * w * half_width * smoothstep(u, 0.72, 1.0) * smoothstep(np.abs(w), 0.2, 1.0)
    elif key == "rear_taper":
        lateral = (
            -amount * w * half_width * (1.0 - smoothstep(u, 0.0, 0.28)) * smoothstep(np.abs(w), 0.2, 1.0)
        )
    elif key == "fender_width":
        sigma = max(1.8 * ru, 0.04)
        arches = np.exp(-(((u - lm.front_axle) / sigma) ** 2)) + np.exp(-(((u - lm.rear_axle) / sigma) ** 2))
        lateral = (
            np.sign(w)
            * amount
            * np.minimum(arches, 1.0)
            * smoothstep(np.abs(w), 0.5, 0.92)
            * (1.0 - smoothstep(v, lm.beltline, lm.beltline + 0.12))
        )
    elif key == "shoulder":
        lateral = (
            np.sign(w)
            * amount
            * smoothstep(np.abs(w), 0.6, 0.95)
            * bump(v, lm.beltline - 0.12, lm.beltline + 0.02, 0.1)
        )
    elif key == "ride_height":
        vertical = np.full_like(u, amount)
    elif key == "rake":
        vertical = amount * (0.5 - u) * 2.0
    elif key == "front_bumper_depth":
        along = (
            amount * smoothstep(u, 0.86, 0.97) * (1.0 - smoothstep(v, 0.3 * lm.hood_top, 0.6 * lm.hood_top))
        )
    elif key == "rear_bumper_depth":
        along = (
            -amount
            * (1.0 - smoothstep(u, 0.03, 0.14))
            * (1.0 - smoothstep(v, 0.3 * lm.deck_top, 0.6 * lm.deck_top))
        )
    elif key == "ducktail":
        vertical = amount * (1.0 - smoothstep(u, 0.02, 0.16)) * smoothstep(v, 0.6 * lm.deck_top, lm.deck_top)
    else:
        raise IncompatibleTransformation(f"Déformation inconnue : {key}")
    return along[:, None] * frame.forward + vertical[:, None] * frame.up + lateral[:, None] * frame.right


# --- État de travail -------------------------------------------------------------------------


@dataclass
class MeshEntry:
    node_id: str
    owner_id: str
    kind: str
    original: MeshData
    mesh: MeshData
    world: np.ndarray  # matrice monde d'origine (sans déplacement rigide)
    color: tuple
    visible: bool = True

    @property
    def edited(self) -> bool:
        return self.mesh is not self.original


@dataclass
class NewPart:
    node_id: str
    name: str
    kind: str
    mesh: MeshData  # repère local de la pièce
    world: np.ndarray
    material: (
        dict  # {"name", "preset", "base_color", "roughness", "metallic", "emissive", "emissive_strength"}
    )
    operation: str
    replaces: list[str] = field(default_factory=list)


@dataclass
class VehicleState:
    frame: VehicleFrame
    components: VehicleComponents
    entries: dict[str, MeshEntry]
    moves: dict[str, np.ndarray] = field(default_factory=dict)  # nœud → translation monde
    hidden: set[str] = field(default_factory=set)  # composants masqués (remplacés)
    new_parts: list[NewPart] = field(default_factory=list)
    materials: dict[str, dict] = field(default_factory=dict)  # composant → nouveau matériau
    log: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # --- Construction ------------------------------------------------------------------
    @classmethod
    def from_session(cls, session, vc: VehicleComponents) -> VehicleState:  # type: ignore[no-untyped-def]
        scene = session.scene
        entries: dict[str, MeshEntry] = {}

        def visible_in_vehicle(node_id: str) -> bool:
            """Visibilité à l'intérieur du véhicule (la racine peut être masquée : source affichée ou non)."""
            current = scene.nodes[node_id]
            while current.id != vc.root_id:
                if not current.visible:
                    return False
                if current.parent_id is None:
                    break
                current = scene.nodes[current.parent_id]
            return True

        for comp in vc.components:
            for mesh_id in comp.mesh_ids:
                node = scene.nodes[mesh_id]
                mesh = session.geometry_for(node)
                if mesh is None:
                    continue
                material = scene.material_for(mesh_id)
                vertex = (
                    mesh.colors.astype(np.float64).mean(axis=0) / 255.0 if mesh.vertex_count else np.ones(4)
                )
                base = np.asarray(material.base_color if material else (1.0, 1.0, 1.0, 1.0), np.float64)
                color = tuple(
                    float(c) for c in base * vertex
                )  # même produit que le viewport (matériau × sommets)
                entries[mesh_id] = MeshEntry(
                    mesh_id,
                    comp.node_id,
                    comp.kind,
                    mesh,
                    mesh,
                    scene.world_matrix(mesh_id),
                    color,
                    visible_in_vehicle(mesh_id),
                )
        return cls(vc.frame, vc, entries)

    # --- Accès -------------------------------------------------------------------------
    def owner_move(self, owner_id: str) -> np.ndarray:
        return self.moves.get(owner_id, np.zeros(3))

    def world_of(self, entry: MeshEntry) -> np.ndarray:
        world = entry.world.copy()
        world[:3, 3] += self.owner_move(entry.owner_id)
        if entry.node_id != entry.owner_id:
            world[:3, 3] += self.owner_move(entry.node_id)
        return world

    def world_points(self, entry: MeshEntry) -> np.ndarray:
        world = self.world_of(entry)
        return entry.mesh.positions.astype(np.float64) @ world[:3, :3].T + world[:3, 3]

    def active_entries(self, kinds: set[str] | None = None) -> list[MeshEntry]:
        return [
            e
            for e in self.entries.values()
            if e.visible and e.owner_id not in self.hidden and (kinds is None or e.kind in kinds)
        ]

    def body_entries(self) -> list[MeshEntry]:
        return [e for e in self.active_entries() if e.kind not in NON_DEFORMABLE]

    def body_points(self) -> np.ndarray:
        pts = [self.world_points(e) for e in self.body_entries()]
        return np.vstack(pts) if pts else np.zeros((0, 3))

    def landmarks(self) -> Landmarks:
        points = self.body_points()
        if not len(points):
            raise IncompatibleTransformation("Aucune carrosserie déformable identifiée dans ce véhicule.")
        return landmarks(points, self.frame, self.components)

    def kinds(self) -> set[str]:
        return {e.kind for e in self.active_entries()} | {p.kind for p in self.new_parts}

    def owners_of(self, *kinds: str) -> list[str]:
        owners: list[str] = []
        for entry in self.active_entries(set(kinds)):
            if entry.owner_id not in owners:
                owners.append(entry.owner_id)
        return owners

    def owner_bounds(self, owner_id: str) -> tuple[np.ndarray, np.ndarray] | None:
        pts = [self.world_points(e) for e in self.entries.values() if e.owner_id == owner_id]
        if not pts:
            return None
        stacked = np.vstack(pts)
        return stacked.min(axis=0), stacked.max(axis=0)

    # --- Opérations élémentaires ---------------------------------------------------------
    def deform(self, key: str, amount: float) -> list[str]:
        spec = DEFORMATIONS[key]
        amount = float(np.clip(amount, spec.minimum, spec.maximum))
        lm = self.landmarks()
        if spec.needs_cabin and not lm.has_cabin:
            raise IncompatibleTransformation(
                f"{spec.label} : aucun habitacle distinct n'est mesurable sur la silhouette de ce véhicule."
            )
        moved = 0
        coarse = False
        for entry in self.body_entries():
            world = self.world_of(entry)
            points = entry.mesh.positions.astype(np.float64) @ world[:3, :3].T + world[:3, 3]
            delta = displacement(key, amount, self.frame, lm, points)
            if not np.any(np.abs(delta) > 1e-7):
                continue
            inverse = np.linalg.inv(world)
            local = (points + delta) @ inverse[:3, :3].T + inverse[:3, 3]
            entry.mesh = with_positions(entry.mesh, local)
            moved += 1
            coarse = coarse or (entry.kind == "body" and entry.mesh.vertex_count < 60)
        if not moved:
            raise IncompatibleTransformation(f"{spec.label} : aucune géométrie concernée sur ce véhicule.")
        for owner in self.owners_of(*(RIGID_KINDS - {"wheel"})):
            bounds = self.owner_bounds(owner)
            if bounds is not None:
                center = (bounds[0] + bounds[1]) / 2
                self.moves[owner] = (
                    self.owner_move(owner) + displacement(key, amount, self.frame, lm, center[None])[0]
                )
        for part in self.new_parts:
            part.world = part.world.copy()
            part.world[:3, 3] += displacement(key, amount, self.frame, lm, part.world[:3, 3][None])[0]
        unit = " m" if spec.unit == "m" else ""
        messages = [f"{spec.label} : {amount:+.3f}{unit}"]
        if coarse:
            messages.append("Carrosserie très simple (moins de 60 sommets) : la déformation reste anguleuse.")
        return messages

    def move_wheels(self, lateral: float) -> list[str]:
        wheels = self.components.wheels
        if len(wheels) < 2:
            raise IncompatibleTransformation("Voies : au moins deux roues identifiées sont nécessaires.")
        for group in wheels:
            sign = 1.0 if group.side == "droite" else -1.0
            for node_id in group.node_ids:
                self.moves[node_id] = self.owner_move(node_id) + self.frame.right * lateral * sign
        return [f"Voies : {lateral:+.3f} m par côté"]

    def add_part(self, part: NewPart) -> None:
        self.new_parts.append(part)

    def hide(self, owner_ids: list[str]) -> None:
        self.hidden.update(owner_ids)

    def set_material(self, owner_id: str, material: dict) -> None:
        self.materials[owner_id] = dict(material)

    # --- Prévisualisation -----------------------------------------------------------------
    def render_list(self) -> list[tuple[MeshData, np.ndarray, tuple]]:
        result = []
        for entry in self.active_entries():
            if entry.kind == "technical":
                continue
            spec = self.materials.get(entry.owner_id)
            color = tuple(spec.get("base_color", entry.color)) if spec else entry.color
            result.append((entry.mesh, self.world_of(entry), preview_color(color, spec)))
        for part in self.new_parts:
            result.append(
                (part.mesh, part.world, preview_color(part.material.get("base_color"), part.material))
            )
        return result


def preview_color(color, spec: dict | None) -> tuple:  # type: ignore[no-untyped-def]
    rgba = tuple(color or (0.72, 0.74, 0.78, 1.0))
    if spec and float(spec.get("emissive_strength", 0)) > 0:
        glow = spec.get("emissive", (1, 1, 1))
        rgba = (*(min(1.0, 0.35 * c + 0.75 * g) for c, g in zip(rgba[:3], glow, strict=False)), 1.0)
    return rgba


def with_positions(mesh: MeshData, positions: np.ndarray) -> MeshData:
    positions = positions.astype(np.float32)
    return MeshData(
        mesh.name,
        positions,
        mesh.indices,
        compute_vertex_normals(positions, mesh.indices),
        mesh.colors,
        mesh.color,
        mesh.uvs,
    )


def part_world(
    frame: VehicleFrame, position: np.ndarray, mirror: bool = False, yaw180: bool = False
) -> np.ndarray:
    """Matrice monde d'une pièce paramétrique posée en ``position`` (repère du véhicule)."""
    rotation = frame.rotation()
    if yaw180:
        rotation = rotation @ np.diag([-1.0, 1.0, -1.0])
    if mirror:
        rotation = rotation @ np.diag([-1.0, 1.0, 1.0])
    world = np.eye(4)
    world[:3, :3] = rotation
    world[:3, 3] = position
    return world


def new_part(
    name: str, kind: str, mesh: MeshData, world: np.ndarray, material: dict, operation: str, replaces=None
) -> NewPart:  # type: ignore[no-untyped-def]
    white = (1.0, 1.0, 1.0, 1.0)  # couleur portée par le matériau (viewport : matériau × sommets)
    mesh = MeshData(mesh.name, mesh.positions, mesh.indices, mesh.normals, None, white, mesh.uvs)
    if np.linalg.det(world[:3, :3]) < 0:
        # Pièce symétrique : le miroir est intégré à la géométrie (enroulement inversé pour garder
        # les normales vers l'extérieur) et la transformation reste une rotation pure (TRS valide).
        flip = np.diag([-1.0, 1.0, 1.0])
        positions = mesh.positions.astype(np.float64) @ flip
        mesh = MeshData(
            mesh.name, positions, mesh.indices[:, [0, 2, 1]], None, mesh.colors, mesh.color, mesh.uvs
        )
        world = world.copy()
        world[:3, :3] = world[:3, :3] @ flip
    return NewPart(new_node_id(), name, kind, mesh, world, material, operation, list(replaces or []))


def surface_u(points: np.ndarray, frame: VehicleFrame, v_range, w_range, front: bool = True) -> float | None:  # type: ignore[no-untyped-def]
    """Position longitudinale (u) de la surface avant / arrière dans une bande (v, w)."""
    if not len(points):
        return None
    u, v, w = frame.coords(points)
    mask = (v >= v_range[0]) & (v <= v_range[1]) & (w >= w_range[0]) & (w <= w_range[1])
    if not mask.any():
        return None
    return float(u[mask].max() if front else u[mask].min())
