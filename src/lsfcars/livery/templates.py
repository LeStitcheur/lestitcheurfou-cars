"""Modèles de livrées (LSPD, Sheriff, State Police, Highway Patrol, EMS, SAMD, Fire, Rescue,
Civil, Racing, Custom) et modèles personnels.

Graphismes **originaux** : bandes 3D, textes et emblèmes générés par le logiciel. Les positions
sont exprimées dans l'espace du véhicule (zone, distance longitudinale, hauteur) puis placées
sur la texture d'après le dépliage réel ; les marquages des flancs sont créés des deux côtés
par symétrie 3D. Les hauteurs sont des **fractions de la hauteur de carrosserie** (0 = point bas,
1 = toit) : un même modèle s'adapte à une berline, un SUV ou un fourgon. Le texte ``{unit}`` est
remplacé par le numéro d'unité de la variante.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path

CATEGORIES = {
    "lspd": "LSPD",
    "sheriff": "Sheriff",
    "state": "State Police",
    "highway": "Highway Patrol",
    "ems": "EMS",
    "samd": "SAMD",
    "fire": "Fire Department",
    "rescue": "Rescue",
    "civil": "Civil",
    "racing": "Racing",
    "custom": "Custom",
}
# service d'Emergency Studio → modèle proposé
SERVICE_TEMPLATE = {
    "lspd": "lspd",
    "bcso": "sheriff",
    "sahp": "highway",
    "ems": "ems",
    "samd": "samd",
    "lsfd": "fire",
    "rescue": "rescue",
    "civil": "civil",
    "custom": "custom",
}


@dataclass
class Template:
    key: str
    name: str
    description: str
    palette: list[str]
    paint: str  # couleur de peinture de carrosserie suggérée (matériau, distincte de la texture)
    elements: list[dict] = field(default_factory=list)
    zones: list[str] = field(default_factory=list)  # zones graphiques utilisées


def _band(name: str, **params) -> dict:  # type: ignore[no-untyped-def]
    """Bande 3D ; ``center_frac`` = hauteur du centre en fraction de la hauteur de carrosserie."""
    return {"type": "band", "name": name, "params": params}


def _text(name: str, text: str, zone: str, size_m: float, lon: float, height: float, **style) -> dict:  # type: ignore[no-untyped-def]
    return {
        "type": "text",
        "name": name,
        "text": text,
        "zone": zone,
        "size_m": size_m,
        "lon": lon,
        "height": height,
        "style": style,
    }


def _logo(
    name: str, logo: str, zone: str, size_m: float, lon: float, height: float, tint: str | None = None
) -> dict:
    return {
        "type": "logo",
        "name": name,
        "logo": logo,
        "zone": zone,
        "size_m": size_m,
        "lon": lon,
        "height": height,
        "tint": tint,
    }


BLACK, WHITE, BLUE, GOLD = "#11151C", "#F3F6FC", "#2563EB", "#E0B83A"
GREEN, YELLOW, RED = "#15803D", "#FACC15", "#DC2626"

BUILTIN_TEMPLATES = [
    Template(
        "lspd",
        "LSPD — Noir et blanc",
        "Portières blanches, filet bleu, numéro d'unité sur le toit.",
        [BLACK, WHITE, BLUE, "#94A3B8"],
        BLACK,
        [
            _band(
                "Portières blanches",
                zone="sides",
                orientation="vertical",
                center_lon=0.15,
                width=1.9,
                color=WHITE,
            ),
            _band(
                "Filet bleu",
                zone="sides",
                orientation="longitudinal",
                center_frac=0.3,
                width=0.035,
                color=BLUE,
            ),
            _text("POLICE", "POLICE", "sides", 0.15, 0.15, 0.46, color=BLACK, bold=True, letter_spacing=4),
            _text("LOS SANTOS", "LOS SANTOS", "sides", 0.07, 0.15, 0.56, color=BLACK, bold=True),
            _text("Unité (toit)", "{unit}", "roof", 0.5, 0.0, 0.0, color=BLACK, bold=True),
            _text("Unité (coffre)", "{unit}", "trunk", 0.18, 0.0, 0.0, color=WHITE, bold=True),
            _logo("Insigne", "lsf-star6-badge", "sides", 0.3, 0.75, 0.4),
        ],
        ["sides", "roof", "trunk"],
    ),
    Template(
        "sheriff",
        "Sheriff — Vert et blanc",
        "Bas de caisse blanc, liseré or, étoile cerclée.",
        ["#14532D", WHITE, GOLD, BLACK],
        "#14532D",
        [
            _band(
                "Bas de caisse blanc",
                zone="sides",
                orientation="longitudinal",
                center_frac=0.18,
                width=0.36,
                color=WHITE,
            ),
            _band(
                "Liseré or",
                zone="sides",
                orientation="longitudinal",
                center_frac=0.4,
                width=0.03,
                color=GOLD,
            ),
            _text(
                "SHERIFF",
                "SHERIFF",
                "sides",
                0.14,
                0.1,
                0.5,
                color=GOLD,
                bold=True,
                outline_width=2,
                outline_color=BLACK,
            ),
            _text("Unité (toit)", "{unit}", "roof", 0.5, 0.0, 0.0, color=WHITE, bold=True),
            _logo("Étoile", "lsf-star5-ring", "sides", 0.32, 0.8, 0.4),
        ],
        ["sides", "roof"],
    ),
    Template(
        "state",
        "State Police — Bleu et or",
        "Double filet or, bouclier sur les portières avant.",
        ["#1E3A8A", GOLD, WHITE, BLACK],
        "#1E3A8A",
        [
            _band(
                "Filet or haut",
                zone="sides",
                orientation="longitudinal",
                center_frac=0.46,
                width=0.04,
                color=GOLD,
            ),
            _band(
                "Filet or bas",
                zone="sides",
                orientation="longitudinal",
                center_frac=0.4,
                width=0.02,
                color=GOLD,
            ),
            _text("STATE POLICE", "STATE POLICE", "sides", 0.12, 0.05, 0.52, color=GOLD, bold=True),
            _logo("Bouclier", "lsf-shield", "sides", 0.34, 0.85, 0.38),
            _text("Unité (toit)", "{unit}", "roof", 0.45, 0.0, 0.0, color=GOLD, bold=True),
        ],
        ["sides", "roof"],
    ),
    Template(
        "highway",
        "Highway Patrol — Bicolore, ailes",
        "Partie basse noire, carrosserie blanche, ailes d'intervention.",
        [BLACK, WHITE, GOLD, BLUE],
        WHITE,
        [
            _band(
                "Partie basse noire",
                zone="sides",
                orientation="longitudinal",
                center_frac=0.16,
                width=0.5,
                color=BLACK,
            ),
            _text("HIGHWAY PATROL", "HIGHWAY PATROL", "sides", 0.11, 0.1, 0.5, color=BLACK, bold=True),
            _logo("Ailes", "lsf-wings", "sides", 0.4, 0.8, 0.4, tint=GOLD),
            _text("Unité (toit)", "{unit}", "roof", 0.5, 0.0, 0.0, color=BLACK, bold=True),
        ],
        ["sides", "roof"],
    ),
    Template(
        "ems",
        "EMS — Damier haute visibilité",
        "Damier jaune et vert, inscription inversée sur le capot (lecture au rétroviseur).",
        [YELLOW, GREEN, WHITE, BLUE],
        WHITE,
        [
            _band(
                "Damier",
                zone="sides",
                orientation="longitudinal",
                center_frac=0.38,
                width=0.22,
                pattern="checker",
                color=YELLOW,
                color2=GREEN,
                period=0.22,
            ),
            _band(
                "Damier arrière",
                zone="rear",
                orientation="longitudinal",
                center_frac=0.38,
                width=0.22,
                pattern="checker",
                color=YELLOW,
                color2=GREEN,
                period=0.15,
            ),
            _text("AMBULANCE", "AMBULANCE", "sides", 0.13, 0.1, 0.52, color=GREEN, bold=True),
            _text(
                "AMBULANCE (capot)",
                "AMBULANCE",
                "hood",
                0.16,
                0.0,
                0.0,
                color=GREEN,
                bold=True,
                mirrored=True,
            ),
            _logo("Croix de secours", "lsf-medical-cross", "sides", 0.3, 0.85, 0.4),
        ],
        ["sides", "rear", "hood"],
    ),
    Template(
        "samd",
        "SAMD — Blanc et rouge",
        "Bande rouge (réfléchissante simulée), croix de secours.",
        [WHITE, RED, BLUE, BLACK],
        WHITE,
        [
            _band(
                "Bande rouge",
                zone="sides",
                orientation="longitudinal",
                center_frac=0.38,
                width=0.14,
                pattern="reflective",
                color=RED,
            ),
            _text(
                "SAN ANDREAS MEDICAL", "SAN ANDREAS\nMEDICAL", "sides", 0.09, 0.1, 0.52, color=RED, bold=True
            ),
            _logo("Croix de secours", "lsf-medical-cross", "sides", 0.28, 0.85, 0.4),
            _text("Unité (toit)", "{unit}", "roof", 0.45, 0.0, 0.0, color=RED, bold=True),
        ],
        ["sides", "roof"],
    ),
    Template(
        "fire",
        "Fire Department — Rouge",
        "Bande blanche (réfléchissante simulée), flamme, inscription dorée.",
        ["#B91C1C", WHITE, GOLD, BLACK],
        "#B91C1C",
        [
            _band(
                "Bande blanche",
                zone="sides",
                orientation="longitudinal",
                center_frac=0.34,
                width=0.12,
                pattern="reflective",
                color=WHITE,
            ),
            _text(
                "FIRE DEPT",
                "FIRE DEPT",
                "sides",
                0.13,
                0.1,
                0.48,
                color=GOLD,
                bold=True,
                outline_width=2,
                outline_color=BLACK,
            ),
            _logo("Flamme", "lsf-flame", "sides", 0.3, 0.85, 0.42),
        ],
        ["sides"],
    ),
    Template(
        "rescue",
        "Rescue — Chevrons",
        "Chevrons arrière rouge et jaune, bande orange.",
        ["#F97316", YELLOW, RED, WHITE],
        WHITE,
        [
            _band(
                "Chevrons arrière",
                zone="rear",
                orientation="longitudinal",
                center_frac=0.4,
                width=0.6,
                pattern="chevron",
                color=RED,
                color2=YELLOW,
                period=0.12,
            ),
            _band(
                "Bande orange",
                zone="sides",
                orientation="longitudinal",
                center_frac=0.38,
                width=0.16,
                color="#F97316",
            ),
            _text("RESCUE", "RESCUE", "sides", 0.15, 0.1, 0.52, color=RED, bold=True),
        ],
        ["rear", "sides"],
    ),
    Template(
        "civil",
        "Civil — Filet discret",
        "Filet fin le long des flancs.",
        ["#94A3B8", WHITE, BLUE, BLACK],
        "#2A3445",
        [
            _band(
                "Filet",
                zone="sides",
                orientation="longitudinal",
                center_frac=0.48,
                width=0.02,
                color="#94A3B8",
            )
        ],
        ["sides"],
    ),
    Template(
        "racing",
        "Racing — Doubles bandes",
        "Doubles bandes sur le dessus (capot, toit, coffre), numéro de course.",
        [WHITE, BLUE, "#38BDF8", BLACK],
        "#0B0E14",
        [
            _band(
                "Bande gauche",
                zone="top",
                orientation="longitudinal",
                lateral_offset=-0.2,
                width=0.22,
                color=WHITE,
            ),
            _band(
                "Bande droite",
                zone="top",
                orientation="longitudinal",
                lateral_offset=0.2,
                width=0.22,
                color=WHITE,
            ),
            _logo("Disque de course", "lsf-unit-ring", "sides", 0.45, 0.1, 0.4),
            _text("Numéro", "{unit}", "sides", 0.24, 0.1, 0.4, color=WHITE, bold=True),
            _logo("Damier", "lsf-checker-flag", "sides", 0.22, -1.2, 0.4),
        ],
        ["top", "sides"],
    ),
    Template(
        "custom",
        "Custom — Vierge",
        "Document vide avec une palette de départ.",
        [BLUE, WHITE, BLACK, GOLD],
        "#2A3445",
        [],
        [],
    ),
]
TEMPLATES_BY_KEY = {t.key: t for t in BUILTIN_TEMPLATES}


# --- Modèles personnels --------------------------------------------------------------------


def user_templates_dir() -> Path:
    from lsfcars.core.paths import app_data_dir

    folder = app_data_dir() / "livery_templates"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def save_user_template(
    path: Path, name: str, layers: list[dict], images: dict[str, bytes], palette: list[str]
) -> Path:
    """Modèle personnel portable : calques éditables + images PNG encodées (base64)."""
    payload = {
        "format": "lsf-livery-template",
        "version": 1,
        "name": name,
        "palette": palette,
        "layers": layers,
        "images": {k: base64.b64encode(v).decode("ascii") for k, v in images.items()},
    }
    Path(path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return Path(path)


def load_user_template(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("format") != "lsf-livery-template":
        raise ValueError("Ce fichier n'est pas un modèle de livrée LeStitcheurFou Cars.")
    data["images"] = {k: base64.b64decode(v) for k, v in (data.get("images") or {}).items()}
    return data


def list_user_templates() -> list[Path]:
    return sorted(user_templates_dir().glob("*.json"))
