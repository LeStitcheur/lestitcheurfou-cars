"""Analyse d'un véhicule dans la scène : axes, composants, roues, habitacle, ancrages, variantes.

Règle : aucune invention. Un nœud n'est classé que si son nom ou ses métadonnées le permettent
(conventions GTA V via ``fivem.structure.classify``, puis motifs génériques français / anglais).
Les profils de roues décrivent ce qui est *attendu* pour un type de véhicule ; ils servent aux
diagnostics et ne garantissent aucune compatibilité GTA V.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from lsfcars.fivem.structure import UNCLASSIFIED, classify
from lsfcars.scene.graph import NodeKind, SceneGraph, SceneNode

# --- Réglages des axes du véhicule -------------------------------------------------------

AXIS_NAMES = ("X", "Y", "Z")
DEFAULT_SETTINGS = {
    "lateral_axis": 0,  # axe gauche / droite (plan de symétrie perpendiculaire)
    "longitudinal_axis": 2,  # axe avant / arrière
    "forward_sign": -1,  # avant du véhicule vers -Z (modèles GTA V importés)
    "mirror_origin": 0.0,  # position du plan de symétrie sur l'axe latéral
}


@dataclass
class VehicleAxes:
    lateral_axis: int = 0
    longitudinal_axis: int = 2
    forward_sign: int = -1
    mirror_origin: float = 0.0

    @property
    def up_axis(self) -> int:
        return ({0, 1, 2} - {self.lateral_axis, self.longitudinal_axis}).pop()

    @property
    def right_sign(self) -> float:
        """Signe de l'axe latéral pointant vers la droite du véhicule (droite = avant × haut)."""
        forward = np.zeros(3)
        forward[self.longitudinal_axis] = self.forward_sign
        up = np.zeros(3)
        up[self.up_axis] = 1.0
        return 1.0 if np.cross(forward, up)[self.lateral_axis] >= 0 else -1.0

    @classmethod
    def from_project(cls, editor: dict | None) -> VehicleAxes:
        data = {**DEFAULT_SETTINGS, **(editor or {})}
        lateral = int(data["lateral_axis"]) % 3
        longitudinal = int(data["longitudinal_axis"]) % 3
        if longitudinal == lateral:
            longitudinal = 2 if lateral != 2 else 0
        sign = -1 if int(data["forward_sign"]) < 0 else 1
        return cls(lateral, longitudinal, sign, float(data["mirror_origin"]))

    def to_dict(self) -> dict:
        return {
            "lateral_axis": self.lateral_axis,
            "longitudinal_axis": self.longitudinal_axis,
            "forward_sign": self.forward_sign,
            "mirror_origin": self.mirror_origin,
        }


# --- Catégories et rôles ------------------------------------------------------------------

ROLE_VISUAL, ROLE_MOBILE, ROLE_TECHNICAL = "visual", "mobile", "technical"
ROLE_LABELS = {
    ROLE_VISUAL: "Composant visuel",
    ROLE_MOBILE: "Composant mobile",
    ROLE_TECHNICAL: "Composant technique FiveM",
}
MOBILE_CATEGORIES = {"roues", "portes", "capot", "coffre"}
INTERIOR_CATEGORIES = {"habitacle", "sieges", "tableau_de_bord"}
BODY_CATEGORIES = {"carrosserie", "portes", "capot", "coffre"}

_GENERIC: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("vitres", (r"glass", r"window", r"vitre", r"pare.?brise")),
    ("roues", (r"wheel", r"\broues?\b", r"tire", r"tyre", r"pneu", r"\brim\b", r"jante")),
    ("sieges", (r"seat", r"si[eè]ge")),
    ("tableau_de_bord", (r"dash", r"tableau de bord", r"volant", r"steer")),
    ("habitacle", (r"interior", r"int[ée]rieur", r"cabin", r"habitacle", r"cockpit")),
    ("portes", (r"door", r"porti[eè]re", r"\bportes?\b")),
    ("capot", (r"\bhood\b", r"bonnet", r"capot")),
    ("coffre", (r"trunk", r"\bboot\b", r"coffre", r"hayon")),
    ("phares", (r"light", r"phare", r"\bfeux?\b", r"lamp", r"rampe")),
    (
        "carrosserie",
        (
            r"body",
            r"carross",
            r"bumper",
            r"pare.?chocs?",
            r"spoiler",
            r"aileron",
            r"fender",
            r"[ée]largisseur",
            r"skirt",
            r"bas de caisse",
            r"grille",
            r"calandre",
            r"roof",
            r"\btoit\b",
            r"\bailes?\b",
            r"splitter",
            r"\blame\b",
            r"diffuseur",
            r"prise d.air",
            r"canard",
        ),
    ),
    (
        "accessoires",
        (r"antenn", r"galerie", r"rack", r"pare.?buffle", r"push.?bar", r"support", r"mirror", r"r[ée]tro"),
    ),
)
_GENERIC_RE = [(key, [re.compile(p, re.IGNORECASE) for p in patterns]) for key, patterns in _GENERIC]
_TECHNICAL_RE = re.compile(r"(^|[_\s])(col|collision|lod\d?|dummy|helper|socket)([_\s]|$)", re.IGNORECASE)


def generic_category(name: str) -> str:
    found = classify(name)
    if found != UNCLASSIFIED:
        return found
    lowered = re.sub(r"[._-]+", " ", name.lower())  # « roue_avant » : séparateurs = espaces
    for key, patterns in _GENERIC_RE:
        if any(p.search(lowered) for p in patterns):
            return key
    return UNCLASSIFIED


def category(scene: SceneGraph, node: SceneNode) -> str:
    """Catégorie d'un nœud : métadonnée explicite, convention GTA V, puis motif générique."""
    explicit = node.extra.get("component", {}).get("category") or node.extra.get("category")
    if explicit and explicit != UNCLASSIFIED:
        return str(explicit)
    found = generic_category(node.name)
    if found != UNCLASSIFIED:
        return found
    parent = scene.get(node.parent_id)
    if parent is not None and node.kind is NodeKind.MESH and parent.kind is not NodeKind.MODEL:
        return category(scene, parent)  # pièce d'un composant : catégorie du composant
    return UNCLASSIFIED


def role(scene: SceneGraph, node: SceneNode) -> str:
    """Rôle : visuel, mobile (roue, porte, capot, coffre) ou technique (ancrage, collision…)."""
    explicit = node.extra.get("component", {}).get("role")
    if explicit in ROLE_LABELS:
        return explicit
    gta = node.extra.get("gta", {})
    if node.kind is NodeKind.ANCHOR or gta.get("anchor") or _TECHNICAL_RE.search(node.name):
        return ROLE_TECHNICAL
    if category(scene, node) in MOBILE_CATEGORIES:
        return ROLE_MOBILE
    return ROLE_VISUAL


def component_root(scene: SceneGraph, node_id: str) -> str | None:
    """Composant auquel appartient un nœud (mode Composant).

    Ordre : ancêtre marqué ``component`` ; os GTA V porteur d'une géométrie ; sinon on remonte
    tant que le parent regroupe des pièces (et non des sous-ensembles) d'une même catégorie,
    sans dépasser le modèle importé ni un ensemble de variantes.
    """
    node = scene.get(node_id)
    if node is None:
        return None
    for item in [node, *scene.ancestors(node_id)]:
        if "component" in item.extra and item.kind is not NodeKind.MODEL:
            return item.id
    if node.extra.get("gta", {}).get("role") == "geometry" and node.parent_id:
        parent = scene.nodes[node.parent_id]
        if parent.extra.get("gta", {}).get("role") == "bone":
            return parent.id
    current = node
    while current.parent_id is not None:
        parent = scene.nodes[current.parent_id]
        if parent.kind is NodeKind.MODEL or is_variant_set(parent):
            break
        if any(c.kind in (NodeKind.GROUP, NodeKind.MODEL) for c in scene.children(parent.id)):
            break  # le parent est un ensemble de composants (ex. « roues »)
        own, above = generic_category(current.name), generic_category(parent.name)
        if UNCLASSIFIED not in (own, above) and own != above:
            break  # pièce d'une autre nature que son groupe (ex. phare dans « carrosserie »)
        current = parent
    return current.id


def is_gta_original(node: SceneNode) -> bool:
    return bool(node.extra.get("gta"))


def is_essential_bone(node: SceneNode) -> bool:
    """Os GTA V dont le pivot pilote une animation (roues, portes, capot, coffre, volant…)."""
    if node.extra.get("gta", {}).get("role") != "bone":
        return False
    return classify(node.name) in MOBILE_CATEGORIES | {"tableau_de_bord"} or node.name.lower() == "chassis"


# --- Variantes ----------------------------------------------------------------------------


def is_variant_set(node: SceneNode | None) -> bool:
    return node is not None and isinstance(node.extra.get("variant_set"), dict)


def active_variant(scene: SceneGraph, set_id: str) -> str | None:
    visible = [c.id for c in scene.children(set_id) if c.visible]
    return visible[0] if visible else None


# --- Roues --------------------------------------------------------------------------------


@dataclass(frozen=True)
class WheelProfile:
    key: str
    label: str
    expected: tuple[int, ...]  # nombres de roues plausibles (vide : aucun attendu)
    note: str = ""


WHEEL_PROFILES: dict[str, WheelProfile] = {
    "car": WheelProfile("car", "Voiture", (4,)),
    "suv": WheelProfile("suv", "SUV / 4x4", (4,)),
    "truck": WheelProfile("truck", "Camion / utilitaire", (4, 6, 8, 10), "Essieux multiples possibles"),
    "motorcycle": WheelProfile("motorcycle", "Moto", (2,), "Roues avant et arrière sur l'axe central"),
    "special": WheelProfile("special", "Véhicule spécial", (), "Aucun nombre attendu (trike, chenilles…)"),
}
VEHICLE_TYPE_PROFILE = {"car": "car", "suv": "suv", "truck": "truck", "motorcycle": "motorcycle"}
_GTA_WHEEL = re.compile(r"^wheel_(l|r)(f|r|m\d?)$", re.IGNORECASE)


@dataclass
class Wheel:
    node_id: str
    name: str
    center: np.ndarray  # monde
    radius: float
    width: float
    side: str = ""  # gauche / droite / centre
    axle: str = ""  # avant / arrière / milieu
    gta_bone: bool = False
    pivot_offset: float = 0.0  # écart pivot ↔ centre géométrique (m)


@dataclass
class WheelReport:
    wheels: list[Wheel]
    profile: WheelProfile
    axes: VehicleAxes
    messages: list[str] = field(default_factory=list)

    def _spread(self, axis: int) -> float | None:
        if len(self.wheels) < 2:
            return None
        values = np.array([w.center[axis] for w in self.wheels])
        return float(values.max() - values.min())

    @property
    def track(self) -> float | None:
        """Voie : écart maximal gauche / droite des centres de roues."""
        return self._spread(self.axes.lateral_axis)

    @property
    def wheelbase(self) -> float | None:
        """Empattement : écart maximal avant / arrière des centres de roues."""
        return self._spread(self.axes.longitudinal_axis)


def is_wheel_name(name: str) -> bool:
    return bool(_GTA_WHEEL.match(name)) or generic_category(name) == "roues"


def find_wheels(session, axes: VehicleAxes | None = None, vehicle_type: str = "car") -> WheelReport:  # type: ignore[no-untyped-def]
    """Identifie les roues : os GTA V ``wheel_*``, puis composants nommés roue / wheel / pneu.

    Un seul nœud par roue : le nœud le plus haut reconnu comme roue (un pneu et sa jante
    regroupés comptent pour une roue).
    """
    axes = axes or VehicleAxes()
    scene = session.scene
    chosen: set[str] = set()
    candidates: list[SceneNode] = []
    for node in scene.walk():
        if node.kind in (NodeKind.ANCHOR, NodeKind.MODEL) or not is_wheel_name(node.name):
            continue
        if any(a.id in chosen for a in scene.ancestors(node.id)):
            continue
        if node.extra.get("gta", {}).get("role") == "geometry":
            continue  # la géométrie d'un os de roue appartient à l'os
        if session.world_bounds([node.id], only_visible=False) is None:
            continue  # os d'ancrage sans géométrie
        if _is_wheel_container(session, node):
            continue  # groupe « roues » : chaque roue est cherchée parmi ses enfants
        candidates.append(node)
        chosen.add(node.id)
    lat, lon, up = axes.lateral_axis, axes.longitudinal_axis, axes.up_axis
    wheels: list[Wheel] = []
    for node in candidates:
        bmin, bmax = session.world_bounds([node.id], only_visible=False)
        size, center = bmax - bmin, (bmin + bmax) / 2
        pivot = scene.world_matrix(node.id)[:3, 3]
        wheels.append(
            Wheel(
                node.id,
                node.name,
                center,
                float(max(size[up], size[lon]) / 2),
                float(size[lat]),
                gta_bone=node.extra.get("gta", {}).get("role") == "bone",
                pivot_offset=float(np.linalg.norm(pivot - center)),
            )
        )
    if wheels:
        lat_values = np.array([w.center[lat] for w in wheels])
        lon_values = np.array([w.center[lon] * axes.forward_sign for w in wheels])
        tol = max(float(np.ptp(lat_values)) * 0.15, 0.05)
        lo, hi = float(lon_values.min()), float(lon_values.max())
        for wheel, x, z in zip(wheels, lat_values, lon_values, strict=True):
            offset = (x - axes.mirror_origin) * axes.right_sign
            wheel.side = "centre" if abs(offset) <= tol else ("droite" if offset > 0 else "gauche")
            if hi - lo < 0.2:
                wheel.axle = "milieu"
            else:
                rel = (z - lo) / (hi - lo)
                wheel.axle = "avant" if rel > 0.66 else ("arrière" if rel < 0.34 else "milieu")
    profile = WHEEL_PROFILES.get(VEHICLE_TYPE_PROFILE.get(vehicle_type, "special"), WHEEL_PROFILES["special"])
    report = WheelReport(wheels, profile, axes)
    if not wheels:
        report.messages.append("Aucune roue identifiée (os wheel_* ou pièce nommée roue / wheel / pneu).")
    elif profile.expected and len(wheels) not in profile.expected:
        expected = " ou ".join(str(n) for n in profile.expected)
        report.messages.append(
            f"Profil {profile.label} : {expected} roues attendues, {len(wheels)} trouvée(s)."
        )
    for wheel in wheels:
        if wheel.pivot_offset > max(wheel.radius * 0.1, 0.01):
            report.messages.append(
                f"{wheel.name} : pivot décalé de {wheel.pivot_offset * 100:.1f} cm du centre de la roue "
                "(la rotation se fait autour du pivot)."
            )
    return report


def _is_wheel_container(session, node: SceneNode) -> bool:  # type: ignore[no-untyped-def]
    """Vrai pour un groupe qui contient plusieurs roues éloignées (et non une jante + un pneu)."""
    centers, radii = [], []
    for child in session.scene.children(node.id):
        if not is_wheel_name(child.name):
            continue
        bounds = session.world_bounds([child.id], only_visible=False)
        if bounds is not None:
            centers.append((bounds[0] + bounds[1]) / 2)
            radii.append(float(np.max(bounds[1] - bounds[0])) / 2)
    if len(centers) < 2:
        return False
    points = np.asarray(centers)
    spread = float(np.max(np.linalg.norm(points[:, None] - points[None, :], axis=2)))
    return spread > max(radii)


def mirror_partner(report: WheelReport, wheel: Wheel) -> Wheel | None:
    """Roue symétrique : côté opposé, la plus proche de la position miroir."""
    lat = report.axes.lateral_axis
    target = wheel.center.copy()
    target[lat] = 2 * report.axes.mirror_origin - target[lat]
    others = [w for w in report.wheels if w.node_id != wheel.node_id and w.side != wheel.side]
    if not others:
        return None
    return min(others, key=lambda w: float(np.linalg.norm(w.center - target)))


# --- Habitacle et carrosserie --------------------------------------------------------------


def nodes_in_categories(scene: SceneGraph, categories: set[str]) -> list[SceneNode]:
    """Composants (les plus hauts) dont la catégorie est dans ``categories``."""
    found: list[SceneNode] = []
    chosen: set[str] = set()
    for node in scene.walk():
        if node.kind in (NodeKind.ANCHOR, NodeKind.MODEL):
            continue
        if any(a.id in chosen for a in scene.ancestors(node.id)):
            continue
        if category(scene, node) in categories:
            found.append(node)
            chosen.add(node.id)
    return found


def interior_nodes(scene: SceneGraph) -> list[SceneNode]:
    return nodes_in_categories(scene, INTERIOR_CATEGORIES)


def body_panels(scene: SceneGraph) -> list[SceneNode]:
    return nodes_in_categories(scene, BODY_CATEGORIES)


def mesh_ids_under(scene: SceneGraph, node_ids) -> set[str]:  # type: ignore[no-untyped-def]
    return {n.id for i in node_ids if i in scene for n in scene.subtree(i) if n.kind is NodeKind.MESH}


# --- Points d'ancrage ----------------------------------------------------------------------

ANCHOR_TYPES = {
    "roof": "Toit",
    "grille": "Calandre",
    "bumper": "Pare-chocs",
    "dashboard": "Tableau de bord",
    "trunk": "Coffre",
    "door": "Portière",
    "medical": "Support médical",
    "light": "Éclairage",
    "generic": "Générique",
}
ANCHOR_CONSTRAINTS = {
    "fixed": "Fixe",
    "slide_longitudinal": "Glissière avant / arrière",
    "rotate_up": "Rotation autour de la verticale",
    "free": "Libre",
}


def anchor_data(node: SceneNode) -> dict:
    data = node.extra.get("anchor", {})
    return {
        "anchor_id": data.get("anchor_id", ""),
        "type": data.get("type", "generic"),
        "constraints": data.get("constraints", "fixed"),
        "metadata": dict(data.get("metadata", {})),
        "component_id": data.get("component_id"),
    }
