"""Identification des composants d'un véhicule et repère du véhicule (sans Qt).

Un composant n'est reconnu que par des données réelles : métadonnée explicite, nom du nœud
(conventions GTA V, motifs français / anglais) ou position mesurée (avant / arrière). Chaque
reconnaissance indique sa source ; rien n'est déduit d'une image ni inventé.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from lsfcars.editor.vehicle import VehicleAxes, is_wheel_name
from lsfcars.scene.graph import NodeKind, SceneNode

COMPONENT_LABELS: dict[str, str] = {
    "body": "Carrosserie",
    "hood": "Capot",
    "trunk": "Coffre / hayon",
    "roof": "Toit",
    "grille": "Calandre",
    "headlight": "Phare",
    "taillight": "Feu arrière",
    "signature": "Signature lumineuse",
    "front_bumper": "Pare-chocs avant",
    "rear_bumper": "Pare-chocs arrière",
    "fender": "Aile / passage de roue",
    "skirt": "Bas de caisse",
    "door": "Portière",
    "mirror": "Rétroviseur",
    "glass": "Vitrage",
    "wheel": "Roue",
    "exhaust": "Échappement",
    "spoiler": "Aileron / becquet",
    "diffuser": "Diffuseur",
    "intake": "Prise d'air",
    "splitter": "Lame avant",
    "protection": "Protection",
    "underbody": "Soubassement",
    "interior": "Habitacle",
    "emergency": "Équipement d'urgence (Emergency Studio)",
    "technical": "Technique (collision, LOD, os, ancrage)",
    "other": "Non classé",
}
FRONT_KINDS = {"grille", "headlight", "front_bumper", "hood", "intake", "splitter", "signature"}
REAR_KINDS = {"taillight", "rear_bumper", "trunk", "diffuser", "exhaust", "spoiler"}
RIGID_KINDS = {"headlight", "taillight", "signature", "mirror", "wheel", "exhaust", "emergency"}

_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("technical", (r"(^|[_\s])(col|collision|lod\d?|dummy|helper|socket|bone)([_\s]|$)",)),
    ("glass", (r"glass", r"window", r"vitre", r"vitrage", r"pare.?brise", r"windscreen")),
    ("wheel", (r"wheel", r"\broues?\b", r"tire", r"tyre", r"pneu", r"\brims?\b", r"jante")),
    ("interior", (r"seat", r"si[eè]ge", r"dash", r"volant", r"steer", r"interior", r"int[ée]rieur",
                  r"habitacle", r"cockpit", r"cabin")),
    ("signature", (r"\bdrl\b", r"signature", r"daytime")),
    ("taillight", (r"tail.?light", r"feux? arri[eè]re", r"\bfeu ar", r"brake.?light", r"stop.?light",
                   r"taillamp")),
    ("headlight", (r"head.?light", r"\bphares?\b", r"headlamp", r"optique")),
    ("grille", (r"grill", r"calandre")),
    ("front_bumper", (r"bumper.?f\b", r"front.?bumper", r"pare.?chocs?.?av", r"bouclier.?av")),
    ("rear_bumper", (r"bumper.?r\b", r"rear.?bumper", r"pare.?chocs?.?ar", r"bouclier.?ar")),
    ("hood", (r"\bhood\b", r"bonnet", r"capot")),
    ("trunk", (r"trunk", r"\bboot\b", r"coffre", r"hayon", r"tailgate", r"hatch")),
    ("roof", (r"\broof\b", r"\btoit\b", r"pavillon")),
    ("door", (r"door", r"porti[eè]re", r"\bportes?\b")),
    ("mirror", (r"mirror", r"r[ée]tro")),
    ("exhaust", (r"exhaust", r"[ée]chappement", r"muffler", r"silencieux")),
    ("spoiler", (r"spoiler", r"aileron", r"becquet", r"\bwing\b")),
    ("diffuser", (r"diffus",)),
    ("intake", (r"intake", r"prise d.air", r"scoop", r"[ée]cope")),
    ("splitter", (r"splitter", r"\blame\b", r"\blip\b")),
    ("fender", (r"fender", r"\bailes?\b", r"[ée]largisseur", r"flare", r"\barch")),
    ("skirt", (r"skirt", r"bas de caisse", r"\bsill")),
    ("protection", (r"push.?bar", r"pare.?buffle", r"skid", r"protection", r"bull.?bar")),
    ("underbody", (r"soubassement", r"underbody", r"ch[aâ]ssis", r"\bfloor\b")),
    ("body", (r"body", r"carross", r"\bcaisse\b", r"shell", r"coque")),
    ("headlight", (r"light", r"lamp", r"\bfeux?\b")),  # éclairage générique : avant / arrière par position
    ("front_bumper", (r"bumper", r"pare.?chocs?", r"bouclier")),  # idem
)  # fmt: skip
_COMPILED = [(k, [re.compile(p, re.IGNORECASE) for p in pats]) for k, pats in _PATTERNS]
_GENERIC_POSITIONAL = {"headlight": "taillight", "front_bumper": "rear_bumper"}


def name_kind(name: str) -> tuple[str, bool]:
    """(composant, positionnel) d'après le nom ; ``positionnel`` : avant / arrière à décider."""
    lowered = re.sub(r"[._-]+", " ", name.lower())
    for index, (key, patterns) in enumerate(_COMPILED):
        if any(p.search(lowered) or p.search(name.lower()) for p in patterns):
            return key, index >= len(_COMPILED) - 2
    return "other", False


@dataclass
class VehicleFrame:
    """Repère aligné sur les axes du Vehicle Editor, dimensions mesurées en monde."""

    axes: VehicleAxes
    lo: np.ndarray
    hi: np.ndarray

    @property
    def size(self) -> np.ndarray:
        return self.hi - self.lo

    @property
    def length(self) -> float:
        return float(self.size[self.axes.longitudinal_axis])

    @property
    def width(self) -> float:
        return float(self.size[self.axes.lateral_axis])

    @property
    def height(self) -> float:
        return float(self.size[self.axes.up_axis])

    @property
    def ground(self) -> float:
        return float(self.lo[self.axes.up_axis])

    @property
    def center(self) -> np.ndarray:
        return (self.lo + self.hi) / 2

    @staticmethod
    def vector(axis: int, sign: float = 1.0) -> np.ndarray:
        v = np.zeros(3)
        v[axis] = sign
        return v

    @property
    def forward(self) -> np.ndarray:
        return self.vector(self.axes.longitudinal_axis, self.axes.forward_sign)

    @property
    def up(self) -> np.ndarray:
        return self.vector(self.axes.up_axis)

    @property
    def right(self) -> np.ndarray:
        return self.vector(self.axes.lateral_axis, self.axes.right_sign)

    def coords(self, points: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(u, v, w) : u 0 = arrière → 1 = avant ; v 0 = bas → 1 = haut ; w −1 gauche → +1 droite."""
        pts = np.asarray(points, np.float64).reshape(-1, 3)
        la, ua, sa = self.axes.longitudinal_axis, self.axes.up_axis, self.axes.lateral_axis
        along = (pts[:, la] - self.lo[la]) / max(self.length, 1e-9)
        u = along if self.axes.forward_sign > 0 else 1.0 - along
        v = (pts[:, ua] - self.lo[ua]) / max(self.height, 1e-9)
        w = (pts[:, sa] - self.center[sa]) / max(self.width / 2, 1e-9) * self.axes.right_sign
        return u, v, w

    def rotation(self) -> np.ndarray:
        """Repère des pièces paramétriques (X largeur, Y haut, avant vers −Z) → monde."""
        return np.column_stack([self.right, self.up, -self.forward])

    def point(self, u: float, v: float, w: float) -> np.ndarray:
        """Point monde depuis des coordonnées normalisées du véhicule."""
        la, ua, sa = self.axes.longitudinal_axis, self.axes.up_axis, self.axes.lateral_axis
        p = self.center.copy()
        along = u if self.axes.forward_sign > 0 else 1.0 - u
        p[la] = self.lo[la] + along * self.length
        p[ua] = self.lo[ua] + v * self.height
        p[sa] = self.center[sa] + w * self.width / 2 * self.axes.right_sign
        return p

    def to_dict(self) -> dict:
        return {"lo": self.lo.tolist(), "hi": self.hi.tolist(), "axes": self.axes.to_dict()}


@dataclass
class Component:
    node_id: str
    name: str
    kind: str
    source: str  # « métadonnée », « nom », « nom + position », « volume »
    lo: np.ndarray
    hi: np.ndarray
    mesh_ids: list[str]
    zone: str = ""  # avant / centre / arrière
    side: str = ""  # gauche / centre / droite

    @property
    def label(self) -> str:
        return COMPONENT_LABELS.get(self.kind, self.kind)

    @property
    def center(self) -> np.ndarray:
        return (self.lo + self.hi) / 2

    @property
    def size(self) -> np.ndarray:
        return self.hi - self.lo


@dataclass
class WheelGroup:
    node_ids: list[str]
    center: np.ndarray
    radius: float
    width: float
    axle: str  # avant / arrière
    side: str


@dataclass
class VehicleComponents:
    root_id: str
    frame: VehicleFrame
    components: list[Component]
    wheels: list[WheelGroup] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def of_kind(self, *kinds: str) -> list[Component]:
        return [c for c in self.components if c.kind in kinds]

    def kinds(self) -> set[str]:
        return {c.kind for c in self.components}

    def mesh_kind(self) -> dict[str, str]:
        return {m: c.kind for c in self.components for m in c.mesh_ids}

    def component_of(self, node_id: str) -> Component | None:
        return next((c for c in self.components if c.node_id == node_id or node_id in c.mesh_ids), None)

    @property
    def wheelbase(self) -> float | None:
        front = [w for w in self.wheels if w.axle == "avant"]
        rear = [w for w in self.wheels if w.axle == "arrière"]
        if not front or not rear:
            return None
        la = self.frame.axes.longitudinal_axis
        return float(abs(np.mean([w.center[la] for w in front]) - np.mean([w.center[la] for w in rear])))

    @property
    def track(self) -> float | None:
        if len(self.wheels) < 2:
            return None
        sa = self.frame.axes.lateral_axis
        values = [w.center[sa] for w in self.wheels]
        return float(max(values) - min(values)) or None

    def axle_u(self, axle: str) -> float | None:
        group = [w for w in self.wheels if w.axle == axle]
        if not group:
            return None
        u, _, _ = self.frame.coords(np.array([w.center for w in group]))
        return float(u.mean())

    def wheel_radius(self) -> float | None:
        return float(np.mean([w.radius for w in self.wheels])) if self.wheels else None


def is_emergency(node: SceneNode) -> bool:
    return any(k.startswith("emergency") for k in node.extra)


def is_technical(node: SceneNode) -> bool:
    gta = node.extra.get("gta", {})
    if node.kind is NodeKind.ANCHOR or gta.get("anchor") or gta.get("role") == "collision":
        return True
    return name_kind(node.name)[0] == "technical"


def mesh_world_points(session, node: SceneNode) -> np.ndarray | None:  # type: ignore[no-untyped-def]
    mesh = session.geometry_for(node)
    if mesh is None or mesh.vertex_count == 0:
        return None
    world = session.scene.world_matrix(node.id)
    pts = mesh.positions.astype(np.float64)
    return pts @ world[:3, :3].T + world[:3, 3]


def identify(session, root_id: str, axes: VehicleAxes | None = None) -> VehicleComponents:  # type: ignore[no-untyped-def]
    """Composants d'un véhicule (sous-arbre ``root_id``), repère et roues mesurés."""
    scene = session.scene
    axes = axes or VehicleAxes.from_project(session.project.editor)
    points: dict[str, np.ndarray] = {}
    for node in scene.subtree(root_id):
        if node.kind is NodeKind.MESH:
            pts = mesh_world_points(session, node)
            if pts is not None:
                points[node.id] = pts

    def owner(node: SceneNode) -> SceneNode:
        """Nœud qui nomme la pièce : le maillage, sinon un parent nommé (« Phare » → « geometry_0 »)."""
        current = node
        while True:
            kind, _ = name_kind(current.name)
            if kind != "other" or current.extra.get("component", {}).get("lore_kind"):
                return current
            if current.parent_id is None or current.id == root_id:
                return node
            parent = scene.nodes[current.parent_id]
            if parent.id == root_id or parent.kind is NodeKind.MODEL:
                return node
            current = parent

    visual = [
        p
        for nid, p in points.items()
        if not is_technical(scene.nodes[nid]) and not is_emergency(scene.nodes[nid])
    ]
    visual = visual or list(points.values())
    if not visual:
        frame = VehicleFrame(axes, np.zeros(3), np.ones(3))
        return VehicleComponents(root_id, frame, [], warnings=["Aucune géométrie dans ce véhicule."])
    stacked = np.vstack(visual)
    frame = VehicleFrame(axes, stacked.min(axis=0), stacked.max(axis=0))

    grouped: dict[str, list[str]] = {}
    for nid in points:
        grouped.setdefault(owner(scene.nodes[nid]).id, []).append(nid)

    components: list[Component] = []
    for owner_id, mesh_ids in grouped.items():
        node = scene.nodes[owner_id]
        pts = np.vstack([points[m] for m in mesh_ids])
        lo, hi = pts.min(axis=0), pts.max(axis=0)
        u, _, w = frame.coords(np.array([(lo + hi) / 2]))
        zone = "avant" if u[0] > 0.62 else "arrière" if u[0] < 0.38 else "centre"
        side = "droite" if w[0] > 0.25 else "gauche" if w[0] < -0.25 else "centre"
        explicit = node.extra.get("component", {}).get("lore_kind")
        if is_emergency(node) or any(is_emergency(scene.nodes[m]) for m in mesh_ids):
            kind, source = "emergency", "métadonnée"
        elif explicit in COMPONENT_LABELS:
            kind, source = explicit, "métadonnée"
        elif is_technical(node):
            kind, source = "technical", "métadonnée" if node.extra.get("gta") else "nom"
        else:
            kind, positional = name_kind(node.name)
            source = "nom"
            if positional or kind in _GENERIC_POSITIONAL:
                if zone == "arrière":
                    kind = _GENERIC_POSITIONAL.get(kind, kind)
                    source = "nom + position"
                elif positional:
                    source = "nom + position"
        components.append(Component(owner_id, node.name, kind, source, lo, hi, mesh_ids, zone, side))

    wheels = _wheel_groups(components, frame)
    result = VehicleComponents(root_id, frame, components, wheels)
    if not result.of_kind("body"):
        largest = max(
            (c for c in components if c.kind == "other"),
            key=lambda c: float(np.prod(np.maximum(c.size, 1e-3))),
            default=None,
        )
        if largest is not None:
            largest.kind, largest.source = "body", "volume (plus grande pièce non classée)"
    if not wheels:
        result.warnings.append("Aucune roue identifiée par son nom : empattement et voies inconnus.")
    return result


def _wheel_groups(components: list[Component], frame: VehicleFrame) -> list[WheelGroup]:
    """Regroupe pneu + jante d'une même roue (centres proches)."""
    wheels = [c for c in components if c.kind == "wheel" or (c.kind == "other" and is_wheel_name(c.name))]
    groups: list[list[Component]] = []
    for comp in wheels:
        comp.kind = "wheel"
        for group in groups:
            if np.linalg.norm(group[0].center - comp.center) < max(0.15, float(group[0].size.max()) * 0.4):
                group.append(comp)
                break
        else:
            groups.append([comp])
    la, ua, sa = frame.axes.longitudinal_axis, frame.axes.up_axis, frame.axes.lateral_axis
    result = []
    for group in groups:
        lo = np.min([c.lo for c in group], axis=0)
        hi = np.max([c.hi for c in group], axis=0)
        center = (lo + hi) / 2
        size = hi - lo
        u, _, w = frame.coords(np.array([center]))
        result.append(
            WheelGroup(
                [c.node_id for c in group],
                center,
                float(max(size[la], size[ua]) / 2),
                float(size[sa]),
                "avant" if u[0] >= 0.5 else "arrière",
                "droite" if w[0] > 0 else "gauche",
            )
        )
    return result
