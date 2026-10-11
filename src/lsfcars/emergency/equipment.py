"""Bibliothèque d'équipements d'urgence (Police, EMS, Fire / Rescue).

Tous les équipements de départ sont des formes **originales générées par le code** ; aucun asset
tiers n'est distribué. Chaque équipement déclare ses projecteurs lumineux (sources de
prévisualisation), ses profils de véhicules compatibles et ses services. L'utilisateur peut
importer ses propres composants (licence et provenance à renseigner).

Repère des équipements : X = largeur, Y = hauteur, Z = longueur, avant vers -Z (comme les
véhicules GTA V importés). Couleurs d'émetteur ``service_left`` / ``service_right`` : couleurs
du service de la variante (ex. rouge / bleu pour la police).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from lsfcars.editor.library import ComponentLibrary, register_categories
from lsfcars.emergency.model import EQUIPMENT_CATEGORIES, category_family
from lsfcars.scene import mathutils, shapes
from lsfcars.scene.mesh import MeshData

register_categories(EQUIPMENT_CATEGORIES)

CARS = ("sedan", "suv", "4x4", "pickup")
BOXES = ("van", "ambulance", "truck")
ROAD = CARS + BOXES
BIKES = ("moto_road", "moto_tt")
POLICE = ("lspd", "bcso", "sahp")
MEDICAL = ("ems", "samd")
FIRE = ("lsfd", "rescue")

LENS = (0.92, 0.94, 0.97, 1.0)
BLACK = (0.08, 0.08, 0.09, 1.0)
METAL = (0.62, 0.64, 0.67, 1.0)
WHITE_BODY = (0.88, 0.89, 0.91, 1.0)
ORANGE = (0.9, 0.42, 0.08, 1.0)
GREEN = (0.1, 0.55, 0.3, 1.0)
RED_BODY = (0.75, 0.1, 0.08, 1.0)

Built = MeshData | tuple[MeshData, list[dict]]


def _t(x: float = 0.0, y: float = 0.0, z: float = 0.0) -> np.ndarray:
    return mathutils.translation((x, y, z))


def _r(x: float = 0.0, y: float = 0.0, z: float = 0.0) -> np.ndarray:
    return mathutils.rotation_euler_xyz((x, y, z))


def emitter(
    name: str,
    position: tuple[float, float, float],
    color: str,
    group: str,
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    angle: float = 90.0,
    light_range: float = 12.0,
) -> dict:
    """Projecteur déclaré par un équipement (repère local de l'équipement)."""
    return {
        "name": name,
        "position": [float(v) for v in position],
        "rotation": [float(v) for v in rotation],
        "color": color,
        "group": group,
        "angle": float(angle),
        "range": float(light_range),
    }


# --- Formes ------------------------------------------------------------------------------------


def lightbar(width: float = 1.2, modules: int = 8, name: str = "Rampe lumineuse") -> Built:
    """Rampe : socle, pieds et modules de lentilles ; un projecteur par module."""
    parts: list = [(shapes.box((width, 0.035, 0.28)), None)]
    for x in (-width * 0.38, width * 0.38):
        parts.append((shapes.box((0.05, 0.05, 0.3), color=BLACK), _t(x, -0.035, 0)))
    step = width / modules
    emitters = []
    for k in range(modules):
        x = -width / 2 + step * (k + 0.5)
        parts.append((shapes.box((step * 0.9, 0.065, 0.24), color=LENS), _t(x, 0.05, 0)))
        side = "left" if x < 0 else "right"
        emitters.append(emitter(f"Module {k + 1}", (x, 0.05, 0), f"service_{side}", side, angle=180.0))
    return shapes.combine(name, parts, LENS), emitters


def beacon() -> Built:
    base = shapes.cylinder(0.08, 0.03, 24, color=BLACK)
    dome = shapes.cylinder(0.065, 0.11, 24, color=LENS)
    mesh = shapes.combine("Gyrophare", [(base, _r(z=90)), (dome, _t(0, 0.07, 0) @ _r(z=90))], LENS)
    return mesh, [emitter("Gyrophare", (0, 0.08, 0), "service_right", "main", angle=360.0)]


def led_pair(spacing: float = 0.5, name: str = "Feux (paire)") -> Built:
    """Deux têtes LED orientées vers l'avant (-Z) : gauche et droite."""
    head = shapes.box((0.12, 0.04, 0.03), color=BLACK)
    lens = shapes.box((0.1, 0.03, 0.006), color=LENS)
    parts: list = []
    emitters = []
    for side, x in (("left", -spacing / 2), ("right", spacing / 2)):
        parts += [(head, _t(x, 0, 0)), (lens, _t(x, 0, -0.018))]
        label = "gauche" if side == "left" else "droit"
        emitters.append(emitter(f"Feu {label}", (x, 0, -0.02), f"service_{side}", side, angle=120.0))
    return shapes.combine(name, parts, LENS), emitters


def single_led(name: str, color: str, group: str) -> Built:
    head = shapes.box((0.1, 0.035, 0.03), color=BLACK)
    lens = shapes.box((0.085, 0.025, 0.006), color=LENS)
    mesh = shapes.combine(name, [(head, None), (lens, _t(0, 0, -0.018))], LENS)
    return mesh, [emitter(name, (0, 0, -0.02), color, group, angle=120.0)]


def rear_window_bar(width: float = 0.8) -> Built:
    """Rampe de lunette arrière (intérieure), lentilles orientées vers l'arrière (+Z)."""
    parts: list = [(shapes.box((width, 0.05, 0.05), color=BLACK), None)]
    emitters = []
    for k in range(4):
        x = -width / 2 + width / 4 * (k + 0.5)
        parts.append((shapes.box((width / 4 * 0.85, 0.035, 0.006), color=LENS), _t(x, 0, 0.028)))
        side = "left" if x < 0 else "right"
        emitters.append(
            emitter(f"Lunette {k + 1}", (x, 0, 0.03), f"service_{side}", "rear", (0, 180, 0), 110.0)
        )
    return shapes.combine("Rampe de lunette arrière", parts, BLACK), emitters


def radio() -> MeshData:
    knob = shapes.cylinder(0.012, 0.015, 12, color=METAL)
    return shapes.combine(
        "Radio de bord",
        [
            (shapes.box((0.18, 0.05, 0.15), color=BLACK), None),
            (shapes.box((0.08, 0.025, 0.004), color=(0.2, 0.4, 0.5, 1.0)), _t(-0.02, 0, -0.077)),
            (knob, _t(0.06, 0, -0.08) @ _r(y=90)),
            (knob, _t(0.035, 0, -0.08) @ _r(y=90)),
        ],
        BLACK,
    )


def console() -> MeshData:
    tower = shapes.box((0.24, 0.32, 0.45), color=BLACK)
    face = shapes.box((0.2, 0.24, 0.01), color=(0.16, 0.17, 0.2, 1.0))
    return shapes.combine(
        "Console centrale", [(tower, _t(0, 0.16, 0)), (face, _t(0, 0.22, -0.2) @ _r(x=-25))], BLACK
    )


def mdt() -> MeshData:
    return shapes.combine(
        "Ordinateur embarqué",
        [
            (shapes.box((0.12, 0.02, 0.12), color=BLACK), None),
            (shapes.cylinder(0.018, 0.35, 12, color=METAL), _t(0, 0.18, 0) @ _r(z=90)),
            (shapes.box((0.34, 0.02, 0.22), color=(0.2, 0.2, 0.22, 1.0)), _t(0, 0.36, 0)),
            (shapes.box((0.34, 0.24, 0.025), color=BLACK), _t(0, 0.48, 0.1) @ _r(x=-15)),
        ],
        BLACK,
    )


def partition(width: float = 1.3, height: float = 0.75) -> MeshData:
    bar = 0.022
    parts: list = [
        (shapes.box((width, bar, bar), color=BLACK), _t(0, height, 0)),
        (shapes.box((width, bar, bar), color=BLACK), None),
        (shapes.box((bar, height, bar), color=BLACK), _t(-width / 2, height / 2, 0)),
        (shapes.box((bar, height, bar), color=BLACK), _t(width / 2, height / 2, 0)),
    ]
    for k in range(1, 10):
        parts.append(
            (shapes.box((0.008, height, 0.008), color=METAL), _t(-width / 2 + width * k / 10, height / 2, 0))
        )
    return shapes.combine("Grille de séparation", parts, BLACK)


def storage_box(
    size: tuple[float, float, float] = (0.9, 0.35, 0.5), name: str = "Coffre de rangement", color=BLACK
) -> MeshData:  # type: ignore[no-untyped-def]
    w, h, d = size
    lid = shapes.box((w * 1.02, 0.03, d * 1.02), color=METAL)
    return shapes.combine(
        name, [(shapes.box((w, h, d), color=color), _t(0, h / 2, 0)), (lid, _t(0, h, 0))], color
    )


def mount() -> MeshData:
    return shapes.combine(
        "Support d'équipement",
        [
            (shapes.box((0.3, 0.012, 0.2), color=METAL), None),
            (shapes.box((0.04, 0.18, 0.04), color=METAL), _t(0, 0.09, 0)),
            (shapes.box((0.2, 0.02, 0.15), color=BLACK), _t(0, 0.19, 0)),
        ],
        METAL,
    )


def _cross(height: float) -> list:
    return [
        (shapes.box((0.12, 0.004, 0.035), color=WHITE_BODY), _t(0, height, 0)),
        (shapes.box((0.035, 0.004, 0.12), color=WHITE_BODY), _t(0, height, 0)),
    ]


def medical_bag() -> MeshData:
    body = shapes.extrude_profile(
        [(-0.18, 0), (0.18, 0), (0.16, 0.22), (-0.16, 0.22)], 0.5, "sac", ORANGE, axis=0
    )
    handle = shapes.box((0.25, 0.02, 0.03), color=BLACK)
    return shapes.combine("Sac médical", [(body, _r(y=90)), (handle, _t(0, 0.24, 0)), *_cross(0.222)], ORANGE)


def stretcher(length: float = 1.95, width: float = 0.56) -> MeshData:
    leg = shapes.box((0.04, 0.45, 0.04), color=METAL)
    wheel = shapes.cylinder(0.05, 0.04, 16, color=BLACK)
    parts: list = [
        (shapes.box((width, 0.04, length), color=METAL), _t(0, 0.5, 0)),
        (shapes.box((width * 0.92, 0.08, length * 0.95), color=(0.15, 0.25, 0.45, 1.0)), _t(0, 0.56, 0)),
    ]
    for x in (-width / 2 + 0.05, width / 2 - 0.05):
        for z in (-length / 2 + 0.15, length / 2 - 0.15):
            parts += [(leg, _t(x, 0.27, z)), (wheel, _t(x, 0.05, z))]
    return shapes.combine("Brancard", parts, METAL)


def cabinet() -> MeshData:
    parts: list = [(shapes.box((0.6, 1.4, 0.45), color=WHITE_BODY), _t(0, 0.7, 0))]
    for k in range(5):
        parts.append((shapes.box((0.56, 0.008, 0.005), color=METAL), _t(0, 0.25 + k * 0.25, -0.227)))
    return shapes.combine("Armoire sanitaire", parts, WHITE_BODY)


def first_aid() -> MeshData:
    return shapes.combine(
        "Trousse de premiers secours",
        [(shapes.box((0.32, 0.12, 0.22), color=GREEN), _t(0, 0.06, 0)), *_cross(0.122)],
        GREEN,
    )


def defibrillator() -> MeshData:
    return shapes.combine(
        "Défibrillateur (décoratif)",
        [
            (shapes.box((0.26, 0.09, 0.22), color=(0.85, 0.75, 0.1, 1.0)), _t(0, 0.045, 0)),
            (shapes.box((0.14, 0.004, 0.09), color=BLACK), _t(0, 0.092, 0)),
            (shapes.box((0.16, 0.025, 0.025), color=BLACK), _t(0, 0.11, 0.08)),
        ],
    )


def worklight() -> Built:
    mesh = shapes.combine(
        "Projecteur de travail",
        [
            (shapes.box((0.26, 0.02, 0.04), color=METAL), None),
            (shapes.box((0.22, 0.16, 0.08), color=BLACK), _t(0, 0.1, 0)),
            (shapes.box((0.19, 0.13, 0.006), color=LENS), _t(0, 0.1, -0.043)),
        ],
        BLACK,
    )
    return mesh, [emitter("Projecteur", (0, 0.1, -0.045), "white", "work", angle=70.0, light_range=25.0)]


def light_mast() -> Built:
    lamp = worklight()[0]
    pole = shapes.cylinder(0.03, 1.0, 12, color=METAL)
    mesh = shapes.combine(
        "Mât d'éclairage",
        [(pole, _t(0, 0.5, 0) @ _r(z=90)), (lamp, _t(-0.15, 1.0, 0)), (lamp, _t(0.15, 1.0, 0))],
        METAL,
    )
    return mesh, [
        emitter("Mât gauche", (-0.15, 1.1, -0.045), "white", "work", angle=70.0, light_range=30.0),
        emitter("Mât droit", (0.15, 1.1, -0.045), "white", "work", angle=70.0, light_range=30.0),
    ]


def tool_rack() -> MeshData:
    parts: list = [(shapes.box((0.9, 0.5, 0.02), color=METAL), _t(0, 0.25, 0))]
    parts += [(shapes.box((0.03, 0.03, 0.12), color=BLACK), _t(x, 0.38, -0.06)) for x in (-0.3, 0.0, 0.3)]
    return shapes.combine("Support d'outils", parts, METAL)


def ladder(length: float = 2.4) -> MeshData:
    rail = shapes.box((0.03, 0.04, length), color=METAL)
    rung = shapes.cylinder(0.012, 0.44, 8, color=METAL)
    parts: list = [(rail, _t(-0.22, 0, 0)), (rail, _t(0.22, 0, 0))]
    parts += [(rung, _t(0, 0, -length / 2 + length * (k + 0.5) / 10)) for k in range(10)]
    return shapes.combine("Échelle de toit", parts, METAL)


# --- Composants de départ ---------------------------------------------------------------------


@dataclass(frozen=True)
class EquipmentSpec:
    """Composant de départ de la bibliothèque d'équipements."""

    key: str
    name: str
    category: str
    factory: Callable[[], Built]
    preset: str = ""
    profiles: tuple[str, ...] = ()
    services: tuple[str, ...] = ()
    description: str = ""
    attach: tuple = ()

    def _built(self) -> tuple[MeshData, list[dict]]:
        result = self.factory()
        return result if isinstance(result, tuple) else (result, [])

    def extras(self) -> dict:
        """Champs supplémentaires transmis à ``ComponentLibrary.add`` (bibliothèque générique)."""
        return {
            "family": category_family(self.category),
            "services": list(self.services),
            "compatible_profiles": list(self.profiles),
            "emitters": self._built()[1],
        }

    def mesh(self) -> MeshData:
        return self._built()[0]


def _spec(
    key, name, category, factory, preset="plastic", profiles=(), services=(), description=""
) -> EquipmentSpec:  # type: ignore[no-untyped-def]
    return EquipmentSpec(key, name, category, factory, preset, tuple(profiles), tuple(services), description)


EQUIPMENT_BUILTINS: tuple[EquipmentSpec, ...] = (
    # Police
    _spec(
        "pol-lightbar",
        "Rampe lumineuse pleine",
        "pol_rampe",
        lambda: lightbar(1.2, 8),
        profiles=ROAD,
        services=POLICE,
        description="Socle bas, 8 modules (couleurs du service)",
    ),
    _spec(
        "pol-minibar",
        "Mini-rampe",
        "pol_rampe",
        lambda: lightbar(0.62, 4, "Mini-rampe"),
        profiles=ROAD,
        services=POLICE,
    ),
    _spec(
        "pol-beacon",
        "Gyrophare magnétique",
        "pol_gyro",
        beacon,
        profiles=(*ROAD, *BIKES, "boat"),
        services=POLICE,
    ),
    _spec(
        "pol-grille",
        "Feux de calandre (paire)",
        "pol_calandre",
        lambda: led_pair(0.5, "Feux de calandre"),
        profiles=(*ROAD, *BIKES),
        services=POLICE,
    ),
    _spec(
        "pol-bumper",
        "Feux de pare-chocs (paire)",
        "pol_parechoc",
        lambda: led_pair(0.9, "Feux de pare-chocs"),
        profiles=ROAD,
        services=POLICE,
    ),
    _spec(
        "pol-mirror",
        "Feu de rétroviseur",
        "pol_retro",
        lambda: single_led("Feu de rétroviseur", "service_left", "left"),
        profiles=(*ROAD, *BIKES),
        services=POLICE,
    ),
    _spec(
        "pol-rear-window",
        "Rampe de lunette arrière",
        "pol_lunette",
        rear_window_bar,
        profiles=(*CARS, "van"),
        services=POLICE,
    ),
    _spec("pol-antenna", "Antenne radio", "pol_antenne", shapes.antenna, services=POLICE),
    _spec("pol-radio", "Radio de bord", "pol_radio", radio, services=POLICE),
    _spec("pol-console", "Console centrale", "pol_console", console, profiles=ROAD, services=POLICE),
    _spec("pol-mdt", "Ordinateur embarqué", "pol_ordi", mdt, profiles=ROAD, services=POLICE),
    _spec("pol-partition", "Grille de séparation", "pol_grille", partition, "metal", CARS, POLICE),
    _spec("pol-storage", "Coffre de rangement", "pol_rangement", storage_box, profiles=ROAD, services=POLICE),
    _spec("pol-mount", "Support d'équipement", "pol_support", mount, "metal", services=POLICE),
    # EMS
    _spec(
        "ems-lightbar",
        "Rampe lumineuse EMS",
        "ems_rampe",
        lambda: lightbar(1.2, 8, "Rampe EMS"),
        profiles=ROAD,
        services=MEDICAL,
    ),
    _spec(
        "ems-flasher",
        "Feu d'urgence encastré",
        "ems_feux",
        lambda: single_led("Feu d'urgence", "service_left", "front"),
        profiles=(*ROAD, *BIKES),
        services=MEDICAL,
    ),
    _spec(
        "ems-flasher-pair",
        "Feux d'urgence (paire)",
        "ems_feux",
        lambda: led_pair(0.5, "Feux d'urgence"),
        profiles=(*ROAD, *BIKES),
        services=MEDICAL,
    ),
    _spec("ems-antenna", "Antenne EMS", "ems_antenne", shapes.antenna, services=MEDICAL),
    _spec("ems-radio", "Radio EMS", "ems_radio", radio, services=MEDICAL),
    _spec("ems-bag", "Sac médical", "ems_sac", medical_bag, "fabric", services=MEDICAL),
    _spec(
        "ems-stretcher",
        "Brancard",
        "ems_brancard",
        stretcher,
        "metal",
        ("ambulance", "van", "truck", "helicopter"),
        MEDICAL,
        "Nécessite une cellule arrière (ambulance, van, camion, hélicoptère)",
    ),
    _spec("ems-bracket", "Support médical", "ems_support", shapes.medical_bracket, "metal", services=MEDICAL),
    _spec(
        "ems-storage",
        "Rangement médical",
        "ems_rangement",
        lambda: storage_box((0.7, 0.3, 0.4), "Rangement médical", WHITE_BODY),
        services=MEDICAL,
    ),
    _spec(
        "ems-cabinet",
        "Armoire sanitaire",
        "ems_armoire",
        cabinet,
        profiles=("ambulance", "van", "truck"),
        services=MEDICAL,
    ),
    _spec(
        "ems-firstaid", "Trousse de premiers secours", "ems_secours", first_aid, services=(*MEDICAL, *FIRE)
    ),
    _spec(
        "ems-defib",
        "Défibrillateur (décoratif)",
        "ems_reanimation",
        defibrillator,
        services=MEDICAL,
        description="Élément décoratif, sans fonction médicale",
    ),
    # Fire / Rescue
    _spec(
        "fire-lightbar",
        "Rampe Fire / Rescue",
        "fire_feux",
        lambda: lightbar(1.4, 10, "Rampe Fire / Rescue"),
        profiles=ROAD,
        services=FIRE,
    ),
    _spec(
        "fire-worklight", "Projecteur de travail", "fire_travail", worklight, "metal", (*ROAD, "boat"), FIRE
    ),
    _spec(
        "fire-mast", "Mât d'éclairage", "fire_travail", light_mast, "metal", ("pickup", *BOXES, "boat"), FIRE
    ),
    _spec(
        "fire-storage",
        "Coffre à outils",
        "fire_rangement",
        lambda: storage_box((1.0, 0.4, 0.5), "Coffre à outils", ORANGE),
        profiles=("pickup", *BOXES),
        services=FIRE,
    ),
    _spec("fire-toolrack", "Support d'outils", "fire_outils", tool_rack, "metal", services=FIRE),
    _spec(
        "fire-rescue-kit",
        "Coffret de sauvetage",
        "fire_sauvetage",
        lambda: storage_box((0.6, 0.25, 0.4), "Coffret de sauvetage", RED_BODY),
        services=FIRE,
    ),
    _spec("fire-ladder", "Échelle de toit", "fire_exterieur", ladder, "metal", ("pickup", *BOXES), FIRE),
)


class _BuiltinAdapter:
    """Présente un ``EquipmentSpec`` à ``ComponentLibrary.ensure_builtins`` (maillage seul)."""

    def __init__(self, spec: EquipmentSpec) -> None:
        self.spec = spec
        self.key = spec.key
        self.name = spec.name
        self.category = spec.category
        self.preset = spec.preset
        self.attach = spec.attach
        self.description = spec.description
        self.factory = spec.mesh

    def extras(self) -> dict:
        return self.spec.extras()


class EquipmentLibrary(ComponentLibrary):
    """Bibliothèque locale d'équipements (``<données>/equipment``) : mêmes fonctions que la
    bibliothèque de composants (import personnel, recherche, duplication, suppression)."""

    categories = EQUIPMENT_CATEGORIES
    builtin_specs = tuple(_BuiltinAdapter(s) for s in EQUIPMENT_BUILTINS)
    default_category = "urg_perso"
    folder_name = "equipment"

    def import_file(  # type: ignore[override]
        self,
        path,  # type: ignore[no-untyped-def]
        name: str | None = None,
        category: str = "urg_perso",
        author: str = "",
        license: str = "",
        provenance: str = "",
    ):
        component = super().import_file(path, name, category, author, license, provenance)
        component.family = category_family(component.category)
        self._save()
        return component

    def for_service(self, service_key: str, text: str = "") -> list:
        """Équipements proposés pour un service (et composants personnels)."""
        return [
            c
            for c in self.search(text)
            if not c.services
            or service_key in c.services
            or c.category == "urg_perso"
            or service_key == "custom"
        ]
