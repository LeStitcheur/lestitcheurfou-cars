"""Modèle de données de l'Emergency Vehicle Studio : services, profils de véhicules, sources
lumineuses, groupes, motifs (timeline), sirènes, livrées (structure), variantes, registre
Lore Friendly. Pur Python, sérialisable en JSON.

Les motifs sont **déterministes** : l'état d'un groupe à l'instant t ne dépend que du motif et de
t (aucun hasard, aucune horloge interne). La prévisualisation est une simulation ; la conversion
vers un système de jeu passe par un adaptateur (``emergency.adapters``) qui déclare ses limites.
"""

from __future__ import annotations

import copy
import re
import uuid
from dataclasses import asdict, dataclass, field

from lsfcars.project.model import utc_now_iso


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


# --- Services --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Service:
    key: str
    label: str
    full_name: str  # nom fictif (univers GTA V / Lore Friendly)
    family: str  # police / ems / fire / civil / custom
    light_colors: tuple[str, ...]  # couleurs par défaut des feux (gauche, droite)
    interior_preset: str  # configuration intérieure proposée
    unit_prefix: str


SERVICES: tuple[Service, ...] = (
    Service("lspd", "LSPD", "Los Santos Police Department", "police", ("red", "blue"), "police", "LSPD"),
    Service(
        "bcso",
        "BCSO / Sheriff",
        "Blaine County Sheriff's Office",
        "police",
        ("red", "blue"),
        "police",
        "BCSO",
    ),
    Service(
        "sahp",
        "State Police / Highway Patrol",
        "San Andreas Highway Patrol",
        "police",
        ("red", "blue"),
        "police",
        "SAHP",
    ),
    Service("ems", "EMS", "Emergency Medical Services", "ems", ("red", "white"), "ems", "EMS"),
    Service("samd", "SAMD", "San Andreas Medical Department", "ems", ("red", "white"), "ems", "SAMD"),
    Service(
        "lsfd", "Fire Department", "Los Santos Fire Department", "fire", ("red", "white"), "fire", "LSFD"
    ),
    Service("rescue", "Rescue", "San Andreas Rescue Service", "fire", ("amber", "white"), "fire", "RSQ"),
    Service("civil", "Civil", "Véhicule civil (sans équipement)", "civil", (), "", ""),
    Service(
        "custom",
        "Service personnalisé",
        "Service d'urgence personnalisé",
        "custom",
        ("amber", "amber"),
        "",
        "SRV",
    ),
)
SERVICES_BY_KEY = {s.key: s for s in SERVICES}


def service(key: str) -> Service:
    return SERVICES_BY_KEY.get(key, SERVICES_BY_KEY["custom"])


# --- Couleurs des feux (simulation) ----------------------------------------------------------

LIGHT_COLORS: dict[str, tuple[str, tuple[float, float, float]]] = {
    "red": ("Rouge", (1.0, 0.08, 0.08)),
    "blue": ("Bleu", (0.12, 0.32, 1.0)),
    "white": ("Blanc", (1.0, 1.0, 1.0)),
    "amber": ("Ambre", (1.0, 0.62, 0.05)),
    "green": ("Vert", (0.1, 0.9, 0.2)),
}


def color_rgb(name: str, custom: list[float] | None = None) -> tuple[float, float, float]:
    if name in LIGHT_COLORS:
        return LIGHT_COLORS[name][1]
    if custom and len(custom) == 3:
        return tuple(max(0.0, min(1.0, float(c))) for c in custom)  # type: ignore[return-value]
    return LIGHT_COLORS["white"][1]


# --- Catégories d'équipements -------------------------------------------------------------------

EQUIPMENT_CATEGORIES: dict[str, str] = {
    "pol_rampe": "Police · Rampes lumineuses",
    "pol_gyro": "Police · Gyrophares",
    "pol_calandre": "Police · Feux de calandre",
    "pol_parechoc": "Police · Feux de pare-chocs",
    "pol_retro": "Police · Feux de rétroviseurs",
    "pol_lunette": "Police · Feux de lunette arrière",
    "pol_antenne": "Police · Antennes",
    "pol_radio": "Police · Radios",
    "pol_console": "Police · Consoles",
    "pol_ordi": "Police · Ordinateurs embarqués",
    "pol_grille": "Police · Grilles de séparation",
    "pol_rangement": "Police · Rangements",
    "pol_support": "Police · Supports d'équipements",
    "ems_rampe": "EMS · Rampes lumineuses",
    "ems_feux": "EMS · Feux d'urgence",
    "ems_antenne": "EMS · Antennes",
    "ems_radio": "EMS · Radios",
    "ems_sac": "EMS · Sacs médicaux",
    "ems_brancard": "EMS · Brancards",
    "ems_support": "EMS · Supports médicaux",
    "ems_rangement": "EMS · Rangements",
    "ems_armoire": "EMS · Armoires",
    "ems_secours": "EMS · Premiers secours",
    "ems_reanimation": "EMS · Réanimation (décoratif)",
    "fire_feux": "Fire / Rescue · Feux d'urgence",
    "fire_travail": "Fire / Rescue · Éclairage de travail",
    "fire_rangement": "Fire / Rescue · Rangements",
    "fire_outils": "Fire / Rescue · Supports d'outils",
    "fire_sauvetage": "Fire / Rescue · Équipements de sauvetage",
    "fire_exterieur": "Fire / Rescue · Accessoires extérieurs",
    "urg_perso": "Composants personnels",
}
FAMILY_LABELS = {"police": "Police", "ems": "EMS", "fire": "Fire / Rescue", "custom": "Personnels"}


def category_family(category: str) -> str:
    prefix = category.split("_", 1)[0]
    return {"pol": "police", "ems": "ems", "fire": "fire"}.get(prefix, "custom")


# Types de zone accueillant chaque catégorie (premier type = choix par défaut)
CATEGORY_ZONES: dict[str, tuple[str, ...]] = {
    "pol_rampe": ("roof",),
    "pol_gyro": ("roof", "mast"),
    "pol_calandre": ("grille",),
    "pol_parechoc": ("bumper_front", "bumper_rear"),
    "pol_retro": ("mirror",),
    "pol_lunette": ("rear_window",),
    "pol_antenne": ("roof", "rear_deck"),
    "pol_radio": ("console",),
    "pol_console": ("console",),
    "pol_ordi": ("dash",),
    "pol_grille": ("partition",),
    "pol_rangement": ("cargo",),
    "pol_support": ("cargo", "console"),
    "ems_rampe": ("roof",),
    "ems_feux": ("grille", "bumper_front", "bumper_rear", "side"),
    "ems_antenne": ("roof",),
    "ems_radio": ("console",),
    "ems_sac": ("cargo", "rear_seat", "patient"),
    "ems_brancard": ("patient", "cargo"),
    "ems_support": ("patient", "cargo"),
    "ems_rangement": ("cargo", "patient"),
    "ems_armoire": ("patient",),
    "ems_secours": ("cargo", "patient", "rear_seat"),
    "ems_reanimation": ("patient", "cargo"),
    "fire_feux": ("roof", "grille", "side"),
    "fire_travail": ("roof", "side", "mast"),
    "fire_rangement": ("cargo",),
    "fire_outils": ("cargo", "side"),
    "fire_sauvetage": ("cargo",),
    "fire_exterieur": ("roof", "side"),
    "urg_perso": (),
}


# --- Profils de véhicules ----------------------------------------------------------------------


@dataclass
class Zone:
    """Zone de placement en coordonnées normalisées du véhicule.

    ``lateral`` : -1 (gauche) … +1 (droite) ; ``up`` : 0 (bas) … 1 (haut) ;
    ``longitudinal`` : -1 (arrière) … +1 (avant). ``normal`` : face d'appui (up, front, rear,
    left, right, down). ``interior`` : zone de l'habitacle ou d'un compartiment.
    """

    key: str
    label: str
    kind: str  # type de zone (roof, grille, console…)
    lateral: float
    up: float
    longitudinal: float
    normal: str = "up"
    interior: bool = False
    mirror: bool = False  # zone latérale proposée en paire (gauche / droite)


@dataclass
class VehicleProfile:
    key: str
    label: str
    zones: list[Zone]
    notes: str = ""
    custom: bool = False

    def zone(self, key: str) -> Zone | None:
        return next((z for z in self.zones if z.key == key), None)

    def zones_for(self, category: str) -> list[Zone]:
        """Zones adaptées à une catégorie ; liste vide = catégorie non prévue sur ce profil."""
        kinds = CATEGORY_ZONES.get(category, ())
        if not kinds:
            return list(self.zones)
        return [z for kind in kinds for z in self.zones if z.kind == kind]

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "notes": self.notes,
            "zones": [asdict(z) for z in self.zones],
        }

    @classmethod
    def from_dict(cls, data: dict) -> VehicleProfile:
        zones = [
            Zone(**{k: v for k, v in z.items() if k in Zone.__dataclass_fields__})
            for z in data.get("zones", [])
        ]
        return cls(
            str(data["key"]), str(data.get("label", data["key"])), zones, str(data.get("notes", "")), True
        )


def _car_zones(cargo_open: bool = False) -> list[Zone]:
    return [
        Zone("roof", "Toit", "roof", 0.0, 1.0, 0.05),
        Zone("grille", "Calandre", "grille", 0.0, 0.48, 1.0, "front"),
        Zone("bumper_front", "Pare-chocs avant", "bumper_front", 0.0, 0.25, 1.0, "front"),
        Zone("bumper_rear", "Pare-chocs arrière", "bumper_rear", 0.0, 0.3, -1.0, "rear"),
        Zone("mirror_l", "Rétroviseur gauche", "mirror", -1.0, 0.62, 0.42, "left", mirror=True),
        Zone("mirror_r", "Rétroviseur droit", "mirror", 1.0, 0.62, 0.42, "right", mirror=True),
        Zone("rear_window", "Lunette arrière (intérieur)", "rear_window", 0.0, 0.8, -0.5, "rear", True),
        Zone("rear_deck", "Plage arrière / coffre", "rear_deck", 0.0, 0.72, -0.8),
        Zone("side_l", "Flanc gauche", "side", -1.0, 0.5, 0.0, "left", mirror=True),
        Zone("side_r", "Flanc droit", "side", 1.0, 0.5, 0.0, "right", mirror=True),
        Zone("console", "Console centrale", "console", 0.0, 0.38, 0.15, "up", True),
        Zone("dash", "Tableau de bord", "dash", 0.25, 0.55, 0.45, "up", True),
        Zone("partition", "Séparation avant / arrière", "partition", 0.0, 0.5, -0.05, "rear", True),
        Zone("rear_seat", "Banquette arrière", "rear_seat", 0.0, 0.35, -0.3, "up", True),
        Zone("cargo", "Benne" if cargo_open else "Coffre", "cargo", 0.0, 0.4, -0.78, "up", not cargo_open),
    ]


def _box_zones() -> list[Zone]:
    """Fourgon, ambulance, camion : cabine, feux d'angle, cellule arrière."""
    return [
        Zone("roof", "Toit avant (cabine)", "roof", 0.0, 1.0, 0.65),
        Zone("roof_rear_l", "Angle arrière gauche", "roof", -0.9, 1.0, -0.95, "up", mirror=True),
        Zone("roof_rear_r", "Angle arrière droit", "roof", 0.9, 1.0, -0.95, "up", mirror=True),
        Zone("grille", "Calandre", "grille", 0.0, 0.45, 1.0, "front"),
        Zone("bumper_front", "Pare-chocs avant", "bumper_front", 0.0, 0.2, 1.0, "front"),
        Zone("bumper_rear", "Pare-chocs arrière", "bumper_rear", 0.0, 0.2, -1.0, "rear"),
        Zone("mirror_l", "Rétroviseur gauche", "mirror", -1.0, 0.62, 0.6, "left", mirror=True),
        Zone("mirror_r", "Rétroviseur droit", "mirror", 1.0, 0.62, 0.6, "right", mirror=True),
        Zone("side_l", "Flanc gauche", "side", -1.0, 0.75, -0.2, "left", mirror=True),
        Zone("side_r", "Flanc droit", "side", 1.0, 0.75, -0.2, "right", mirror=True),
        Zone("console", "Console centrale", "console", 0.0, 0.4, 0.55, "up", True),
        Zone("dash", "Tableau de bord", "dash", 0.25, 0.55, 0.75, "up", True),
        Zone("partition", "Cloison cabine / cellule", "partition", 0.0, 0.55, 0.35, "rear", True),
        Zone("patient", "Cellule arrière", "patient", 0.0, 0.25, -0.35, "up", True),
        Zone("cargo", "Rangements arrière", "cargo", -0.6, 0.35, -0.7, "up", True),
    ]


def _bike_zones(offroad: bool = False) -> list[Zone]:
    zones = [
        Zone("fork", "Fourche / feux avant", "grille", 0.0, 0.55, 0.95, "front"),
        Zone("mirror_l", "Rétroviseur gauche", "mirror", -1.0, 0.85, 0.55, "left", mirror=True),
        Zone("mirror_r", "Rétroviseur droit", "mirror", 1.0, 0.85, 0.55, "right", mirror=True),
        Zone("rear_rack", "Porte-bagages arrière", "rear_deck", 0.0, 0.65, -0.75),
        Zone("mast", "Mât arrière", "mast", 0.0, 0.85, -0.85),
        Zone("bag_l", "Sacoche gauche", "cargo", -0.9, 0.45, -0.55, "left", mirror=True),
        Zone("bag_r", "Sacoche droite", "cargo", 0.9, 0.45, -0.55, "right", mirror=True),
        Zone("dash", "Tableau de bord", "dash", 0.0, 0.8, 0.55),
    ]
    return [z for z in zones if not (offroad and z.key in ("bag_l", "bag_r"))]


PROFILES: tuple[VehicleProfile, ...] = (
    VehicleProfile("sedan", "Berline", _car_zones()),
    VehicleProfile("suv", "SUV", _car_zones()),
    VehicleProfile("4x4", "4x4", _car_zones()),
    VehicleProfile("pickup", "Pick-up", _car_zones(cargo_open=True), "Benne ouverte : rangements extérieurs"),
    VehicleProfile("van", "Van", _box_zones(), "Rampe sur cabine, feux d'angle arrière"),
    VehicleProfile("ambulance", "Ambulance", _box_zones(), "Cellule sanitaire pour brancard et supports"),
    VehicleProfile("truck", "Camion", _box_zones(), "Rangements, éclairages de travail"),
    VehicleProfile(
        "moto_road", "Moto routière", _bike_zones(), "Pas de toit : feux sur fourche, mât et sacoches"
    ),
    VehicleProfile("moto_tt", "Moto tout-terrain", _bike_zones(offroad=True), "Équipement minimal"),
    VehicleProfile(
        "helicopter",
        "Hélicoptère",
        [
            Zone("belly", "Ventre (projecteur)", "mast", 0.0, 0.0, 0.3, "down"),
            Zone("nose", "Nez", "grille", 0.0, 0.4, 1.0, "front"),
            Zone("tail", "Poutre de queue", "rear_deck", 0.0, 0.6, -1.0),
            Zone("cabin", "Cabine", "console", 0.0, 0.35, 0.4, "up", True),
            Zone("cargo", "Soute", "cargo", 0.0, 0.3, -0.1, "up", True),
        ],
        "Rampe automobile non adaptée : feux de position et projecteur",
    ),
    VehicleProfile(
        "boat",
        "Bateau",
        [
            Zone("mast", "Mât", "mast", 0.0, 1.0, 0.1),
            Zone("cabin_roof", "Toit de cabine", "roof", 0.0, 0.85, 0.15),
            Zone("bow", "Proue", "grille", 0.0, 0.5, 1.0, "front"),
            Zone("stern", "Poupe", "bumper_rear", 0.0, 0.45, -1.0, "rear"),
            Zone("cockpit", "Poste de pilotage", "console", 0.0, 0.5, 0.2, "up", True),
            Zone("deck", "Pont arrière", "cargo", 0.0, 0.4, -0.6),
        ],
    ),
    VehicleProfile(
        "aircraft",
        "Aéronef",
        [
            Zone("wing_l", "Saumon d'aile gauche", "side", -1.0, 0.5, 0.0, "left", mirror=True),
            Zone("wing_r", "Saumon d'aile droit", "side", 1.0, 0.5, 0.0, "right", mirror=True),
            Zone("belly", "Ventre", "mast", 0.0, 0.0, 0.2, "down"),
            Zone("tail", "Dérive", "rear_deck", 0.0, 1.0, -1.0),
            Zone("cockpit", "Cockpit", "console", 0.0, 0.5, 0.7, "up", True),
        ],
    ),
)
PROFILES_BY_KEY = {p.key: p for p in PROFILES}
VEHICLE_TYPE_PROFILE = {
    "car": "sedan",
    "suv": "suv",
    "truck": "truck",
    "motorcycle": "moto_road",
    "boat": "boat",
    "helicopter": "helicopter",
    "plane": "aircraft",
}


# --- Éclairage ---------------------------------------------------------------------------------

GROUP_KINDS = {
    "front": "Groupe avant",
    "rear": "Groupe arrière",
    "left": "Groupe gauche",
    "right": "Groupe droit",
    "main": "Rampe principale",
    "secondary": "Feux secondaires",
    "work": "Éclairage de travail",
    "custom": "Groupe personnalisé",
}


@dataclass
class LightSource:
    """Source lumineuse de **prévisualisation**, rattachée à un équipement (repère local)."""

    id: str
    name: str
    node_id: str | None  # équipement porteur (None : repère du véhicule)
    position: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotation: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    color: str = "red"
    custom_color: list[float] | None = None
    intensity: float = 1.0
    range: float = 12.0  # portée simulée (m)
    angle: float = 90.0  # ouverture (°)
    visible: bool = True
    enabled: bool = True

    @property
    def rgb(self) -> tuple[float, float, float]:
        return color_rgb(self.color, self.custom_color)


@dataclass
class LightGroup:
    id: str
    name: str
    kind: str = "custom"
    light_ids: list[str] = field(default_factory=list)


# --- Motifs (timeline) -------------------------------------------------------------------------


@dataclass
class PatternFrame:
    duration_ms: int
    groups: list[str] = field(default_factory=list)  # groupes allumés pendant cette étape


@dataclass
class Pattern:
    id: str
    name: str
    frames: list[PatternFrame] = field(default_factory=list)
    preset: str = "custom"

    @property
    def cycle_ms(self) -> int:
        return sum(max(int(f.duration_ms), 0) for f in self.frames)

    def frame_index_at(self, t_ms: float, speed: float = 1.0) -> int | None:
        """Étape active à l'instant ``t_ms`` (``speed`` : multiplicateur). Déterministe."""
        cycle = self.cycle_ms
        if cycle <= 0 or speed <= 0:
            return None
        local = int(t_ms * speed) % cycle
        elapsed = 0
        for index, frame in enumerate(self.frames):
            elapsed += max(int(frame.duration_ms), 0)
            if local < elapsed:
                return index
        return len(self.frames) - 1

    def groups_on(self, t_ms: float, speed: float = 1.0) -> set[str]:
        index = self.frame_index_at(t_ms, speed)
        return set(self.frames[index].groups) if index is not None else set()

    def group_ids(self) -> list[str]:
        return list(dict.fromkeys(g for f in self.frames for g in f.groups))

    def sample(self, steps: int) -> list[set[str]]:
        """Échantillonne un cycle en ``steps`` pas égaux (milieu de chaque pas)."""
        cycle = self.cycle_ms
        if cycle <= 0:
            return [set() for _ in range(steps)]
        return [self.groups_on((i + 0.5) * cycle / steps) for i in range(steps)]


PATTERN_PRESETS = {
    "alternate": "Alternance gauche / droite",
    "double": "Double flash",
    "triple": "Triple flash",
    "simultaneous": "Flash simultané",
    "progressive": "Séquence progressive",
    "custom": "Motif personnalisé",
}


def build_pattern(preset: str, groups: list[str], step_ms: int = 100, name: str | None = None) -> Pattern:
    """Motif prédéfini appliqué aux groupes donnés (deux groupes pour les motifs alternés)."""
    groups = [g for g in groups if g]
    a = groups[0] if groups else ""
    b = groups[1] if len(groups) > 1 else a
    step = max(int(step_ms), 10)
    frames: list[PatternFrame] = []
    if preset == "alternate":
        frames = [PatternFrame(step * 3, [a]), PatternFrame(step * 3, [b])]
    elif preset in ("double", "triple"):
        count = 2 if preset == "double" else 3
        for group in dict.fromkeys((a, b)):
            for _ in range(count):
                frames += [PatternFrame(step // 2 + 20, [group]), PatternFrame(step // 2 + 20, [])]
            frames.append(PatternFrame(step, []))
    elif preset == "progressive":
        frames = [PatternFrame(step, [g]) for g in groups] + [PatternFrame(step, [])]
    else:  # simultané et personnalisé (point de départ modifiable dans la timeline)
        frames = [PatternFrame(step * 2, list(dict.fromkeys(groups))), PatternFrame(step * 2, [])]
        preset = preset if preset == "simultaneous" else "custom"
    frames = [PatternFrame(f.duration_ms, [g for g in f.groups if g]) for f in frames if f.duration_ms > 0]
    return Pattern(new_id("pat-"), name or PATTERN_PRESETS.get(preset, "Motif"), frames, preset)


# --- Sirènes --------------------------------------------------------------------------------

SIREN_TONES = {
    "wail": "Wail (montée lente)",
    "yelp": "Yelp (rapide)",
    "hilo": "Deux tons (hi-lo)",
    "priority": "Priorité (alternance rapide)",
    "horn": "Avertisseur",
    "none": "Aucun son",
}


@dataclass
class SirenMode:
    key: str
    label: str
    tone: str = "wail"  # tonalité intégrée (synthétisée) ou ``custom:<index>``
    pattern_id: str | None = None  # motif lumineux associé à ce mode


@dataclass
class SirenProfile:
    name: str = "Profil de sirène"
    modes: list[SirenMode] = field(default_factory=list)
    custom_tones: list[dict] = field(default_factory=list)  # {name, file, license}
    audio_strings: dict[str, str] = field(default_factory=dict)  # métadonnées d'export (FiveM)


def default_siren_profile() -> SirenProfile:
    return SirenProfile(
        "Profil standard",
        [
            SirenMode("stage1", "Mode 1 : feux seuls", "none"),
            SirenMode("stage2", "Mode 2 : feux + wail", "wail"),
            SirenMode("stage3", "Mode 3 : feux + yelp", "yelp"),
            SirenMode("horn", "Avertisseur", "horn"),
        ],
    )


# --- Livrée (structure seulement : Livery Studio prévu) ---------------------------------------


@dataclass
class LiveryData:
    livery_name: str = ""
    primary_color: str = ""
    secondary_color: str = ""
    logos: list[dict] = field(default_factory=list)  # {name, file, license, provenance}
    markings: list[str] = field(default_factory=list)
    unit_id: str = ""
    callsign: str = ""
    notes: str = ""


# --- Variantes ---------------------------------------------------------------------------------


@dataclass
class Variant:
    id: str
    name: str
    service: str
    profile: str
    root_id: str  # groupe de scène portant les équipements de la variante
    lights: list[LightSource] = field(default_factory=list)
    groups: list[LightGroup] = field(default_factory=list)
    patterns: list[Pattern] = field(default_factory=list)
    active_pattern: str | None = None
    siren: SirenProfile = field(default_factory=default_siren_profile)
    interior_preset: str = ""
    livery: LiveryData = field(default_factory=LiveryData)
    material_overrides: dict[str, str] = field(default_factory=dict)  # nœud de base → matériau
    parameters: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)

    def light(self, light_id: str) -> LightSource | None:
        return next((light for light in self.lights if light.id == light_id), None)

    def group(self, group_id: str | None) -> LightGroup | None:
        return next((g for g in self.groups if g.id == group_id), None)

    def pattern(self, pattern_id: str | None) -> Pattern | None:
        return next((p for p in self.patterns if p.id == pattern_id), None)


@dataclass
class StudioState:
    """Document ``emergency`` : variantes, variante active, corbeille, profils personnalisés."""

    version: int = 1
    set_id: str | None = None  # ensemble de variantes dans la scène
    variants: list[Variant] = field(default_factory=list)
    active: str | None = None
    base_materials: dict[str, str | None] = field(default_factory=dict)  # matériaux d'origine
    trash: list[dict] = field(default_factory=list)  # variantes supprimées (restaurables)
    custom_profiles: list[dict] = field(default_factory=list)
    pattern_presets: list[dict] = field(default_factory=list)  # motifs enregistrés comme presets
    interior_presets: list[dict] = field(default_factory=list)  # {name, items: [{component_id, transform}]}

    def variant(self, variant_id: str | None) -> Variant | None:
        return next((v for v in self.variants if v.id == variant_id), None)

    @property
    def active_variant(self) -> Variant | None:
        return self.variant(self.active)

    def profile(self, key: str) -> VehicleProfile:
        for data in self.custom_profiles:
            if data.get("key") == key:
                return VehicleProfile.from_dict(data)
        return PROFILES_BY_KEY.get(key, PROFILES_BY_KEY["sedan"])

    def all_profiles(self) -> list[VehicleProfile]:
        return [*PROFILES, *(VehicleProfile.from_dict(d) for d in self.custom_profiles)]

    def to_dict(self) -> dict:
        return copy.deepcopy(asdict(self))

    @classmethod
    def from_dict(cls, data: dict | None) -> StudioState:
        if not data:
            return cls()
        return cls(
            int(data.get("version", 1)),
            data.get("set_id"),
            [variant_from_dict(v) for v in data.get("variants", [])],
            data.get("active"),
            dict(data.get("base_materials", {})),
            list(data.get("trash", [])),
            list(data.get("custom_profiles", [])),
            list(data.get("pattern_presets", [])),
            list(data.get("interior_presets", [])),
        )


def _fields(cls, data: dict) -> dict:  # type: ignore[no-untyped-def]
    return {k: v for k, v in data.items() if k in cls.__dataclass_fields__}


def pattern_from_dict(data: dict) -> Pattern:
    frames = [
        PatternFrame(int(f.get("duration_ms", 100)), list(f.get("groups", [])))
        for f in data.get("frames", [])
    ]
    return Pattern(data["id"], data.get("name", "Motif"), frames, data.get("preset", "custom"))


def variant_from_dict(data: dict) -> Variant:
    nested = ("lights", "groups", "patterns", "siren", "livery")
    variant = Variant(**_fields(Variant, {k: v for k, v in data.items() if k not in nested}))
    variant.lights = [LightSource(**_fields(LightSource, light)) for light in data.get("lights", [])]
    variant.groups = [LightGroup(**_fields(LightGroup, g)) for g in data.get("groups", [])]
    variant.patterns = [pattern_from_dict(p) for p in data.get("patterns", [])]
    siren = data.get("siren")
    if siren:
        variant.siren = SirenProfile(
            siren.get("name", "Profil de sirène"),
            [SirenMode(**_fields(SirenMode, m)) for m in siren.get("modes", [])],
            list(siren.get("custom_tones", [])),
            dict(siren.get("audio_strings", {})),
        )
    variant.livery = LiveryData(**_fields(LiveryData, data.get("livery") or {}))
    return variant


# --- Lore Friendly et provenance -------------------------------------------------------------

LORE_DISCLAIMER = (
    "Aide à la vérification seulement : ce contrôle ne constitue ni une garantie juridique ni une "
    "certification de Rockstar Games ou de Cfx.re. Vérifiez vous-même les droits de chaque élément."
)
# Marques fictives de l'univers GTA V (propriété de leurs ayants droit), proposées pour nommer.
FICTIONAL_BRANDS = (
    "Vapid",
    "Declasse",
    "Bravado",
    "Albany",
    "Karin",
    "Annis",
    "Dinka",
    "Ubermacht",
    "Benefactor",
    "Obey",
    "Canis",
    "Brute",
    "Maibatsu",
    "Pegassi",
    "Western",
    "Shitzu",
)
# Exemples de marques réelles (automobile, équipements d'urgence) ; liste non exhaustive : leur
# présence dans un nom ou une provenance déclenche un avertissement.
REAL_BRANDS = (
    "ford",
    "chevrolet",
    "chevy",
    "dodge",
    "toyota",
    "bmw",
    "mercedes",
    "audi",
    "volkswagen",
    "renault",
    "peugeot",
    "citroen",
    "tesla",
    "jeep",
    "gmc",
    "cadillac",
    "lamborghini",
    "ferrari",
    "porsche",
    "whelen",
    "federal signal",
    "code 3",
    "code3",
    "soundoff",
    "feniex",
    "motorola",
    "panasonic",
    "toughbook",
    "stryker",
    "ferno",
    "zoll",
    "setina",
    "havis",
)


def real_brand_hits(text: str) -> list[str]:
    """Marques réelles connues citées dans un texte (détection par mots entiers)."""
    lowered = text.lower()
    return [b for b in REAL_BRANDS if re.search(rf"(?<![a-z0-9]){re.escape(b)}(?![a-z0-9])", lowered)]
