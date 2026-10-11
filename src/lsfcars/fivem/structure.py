"""Classification des composants d'un véhicule d'après les noms de la hiérarchie.

Règle : aucune invention. Un nœud n'est classé que si son nom (ou celui de son os) correspond
à une convention de nommage GTA V connue ; sinon il reste « non classée ».
"""

from __future__ import annotations

import re
from dataclasses import dataclass

UNCLASSIFIED = "non_classee"


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    patterns: tuple[str, ...]


# Ordre significatif : la première catégorie dont un motif correspond l'emporte.
CATEGORIES: tuple[Category, ...] = (
    Category("vitres", "Vitres", (r"^window", r"^windscreen", r"^glass", r"vehglass")),
    Category(
        "phares",
        "Phares et feux",
        (
            r"^headlight",
            r"^taillight",
            r"^indicator",
            r"^brakelight",
            r"^reversinglight",
            r"^extralight",
            r"^siren",
            r"^neon",
            r"lights?emissive",
        ),
    ),
    Category("portes", "Portes", (r"^door_",)),
    Category("capot", "Capot", (r"^bonnet",)),
    Category("coffre", "Coffre", (r"^boot", r"^trunk")),
    Category(
        "roues",
        "Roues",
        (r"^wheel", r"^hub_", r"^bikedisc", r"^tyre", r"^tire", r"vehicle_tire"),
    ),
    Category("sieges", "Sièges", (r"^seat_", r"^seat$")),
    Category(
        "tableau_de_bord",
        "Tableau de bord",
        (r"^dials", r"^steeringwheel", r"^steering_wheel", r"^dashglow"),
    ),
    Category("habitacle", "Habitacle", (r"^interior", r"^cabin", r"^cockpit", r"^dashboard")),
    Category(
        "chassis",
        "Châssis et mécanique",
        (
            r"^chassis",
            r"^suspension",
            r"^swingarm",
            r"^forks",
            r"^engine",
            r"^transmission",
            r"^axle",
            r"^petroltank",
            r"^exhaust",
            r"^overheat",
            r"^handlebars",
            r"^hbgrip",
        ),
    ),
    Category(
        "carrosserie",
        "Carrosserie",
        (r"^bodyshell", r"^bumper_", r"^panel_", r"^wing_", r"^spoiler", r"^roof", r"^skirt"),
    ),
    Category(
        "accessoires",
        "Accessoires",
        (r"^misc_", r"^extra_", r"^mod_col", r"^bobble", r"^platelight", r"^numberplate", r"^plate_"),
    ),
)
CATEGORY_LABELS = {c.key: c.label for c in CATEGORIES} | {UNCLASSIFIED: "Non classée"}
_COMPILED = [(c.key, [re.compile(p, re.IGNORECASE) for p in c.patterns]) for c in CATEGORIES]


def classify(*names: str) -> str:
    """Catégorie du premier nom reconnu (nom du nœud, de l'os…), sinon « non classée »."""
    for name in names:
        if not name:
            continue
        base = name.strip().lower()
        for key, patterns in _COMPILED:
            if any(p.search(base) for p in patterns):
                return key
    return UNCLASSIFIED


def label(category: str) -> str:
    return CATEGORY_LABELS.get(category, CATEGORY_LABELS[UNCLASSIFIED])


# --- Modes d'inspection -----------------------------------------------------------


@dataclass(frozen=True)
class InspectionMode:
    key: str
    label: str
    available: bool
    detail: str = ""


INSPECTION_MODES: tuple[InspectionMode, ...] = (
    InspectionMode("complet", "Complet", True, "Toutes les pièces visibles"),
    InspectionMode("isole", "Isolé", True, "Affiche uniquement la sélection"),
    InspectionMode("eclate", "Éclaté", True, "Écarte les pièces sans modifier le modèle"),
    InspectionMode("filaire", "Filaire", True, "Arêtes du maillage"),
    InspectionMode("materiaux", "Matériaux", True, "Couleurs et textures des matériaux"),
    InspectionMode("bones", "Os", True, "Hiérarchie des os et pivots d'origine"),
    InspectionMode("ancrage", "Ancrages", True, "Os sans géométrie (sièges, feux, roues…)"),
    InspectionMode("statistiques", "Statistiques", True, "Triangles, sommets, matériaux par pièce"),
    InspectionMode(
        "collisions",
        "Collisions",
        False,
        "Non implémenté : la géométrie de collision (.ybn) n'est pas encore décodée",
    ),
)
