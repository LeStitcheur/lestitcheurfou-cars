"""Design DNA Engine : caractéristiques stylistiques réglables d'un véhicule ou d'une marque.

Un profil DNA est un ensemble de valeurs 0-100. Il **guide** le Lore Concept Generator
(choix et amplitude des transformations proposées) ; il ne promet aucune modification
géométrique : seules les opérations du catalogue (``operations.py``) modifient le maillage.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

PARAMETERS: dict[str, str] = {
    "sport": "Sportivité",
    "luxury": "Luxe",
    "robust": "Robustesse",
    "modern": "Modernité",
    "retro": "Style rétro",
    "aggressive": "Agressivité visuelle",
    "sobriety": "Sobriété",
    "aero": "Aérodynamisme",
    "utility": "Caractère utilitaire",
    "offroad": "Orientation tout-terrain",
}
NEUTRAL = 50


@dataclass
class DnaProfile:
    key: str
    name: str
    description: str
    values: dict[str, int]
    guidance: list[str] = field(default_factory=list)  # intentions de design (texte)
    origin: str = "builtin"  # builtin / custom

    def __post_init__(self) -> None:
        self.values = normalize(self.values)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> DnaProfile:
        return cls(
            str(data.get("key", "custom")),
            str(data.get("name", "Profil")),
            str(data.get("description", "")),
            dict(data.get("values", {})),
            list(data.get("guidance", [])),
            str(data.get("origin", "custom")),
        )


def normalize(values: dict | None) -> dict[str, int]:
    values = values or {}
    result = {}
    for key in PARAMETERS:
        try:
            result[key] = max(0, min(100, int(round(float(values.get(key, NEUTRAL))))))
        except (TypeError, ValueError):
            result[key] = NEUTRAL
    return result


PRESETS: tuple[DnaProfile, ...] = (
    DnaProfile(
        "sport_premium",
        "Sport Premium",
        "Silhouette dynamique, prises d'air discrètes, optiques affinées, surfaces tendues.",
        {"sport": 80, "luxury": 65, "modern": 75, "aggressive": 55, "sobriety": 55, "aero": 70,
         "robust": 35, "utility": 15, "offroad": 10, "retro": 20},
        ["Silhouette dynamique (toit abaissé, capot allongé)", "Prises d'air discrètes",
         "Optiques affinées", "Surfaces tendues"],
    ),
    DnaProfile(
        "offroad",
        "Offroad",
        "Garde au sol adaptée, passages de roues prononcés, protections, éléments robustes.",
        {"offroad": 90, "robust": 85, "utility": 60, "sport": 25, "luxury": 30, "aero": 15,
         "aggressive": 55, "sobriety": 45, "modern": 45, "retro": 35},
        ["Garde au sol rehaussée", "Passages de roues prononcés (extensions d'ailes)",
         "Protections avant / sous-caisse", "Éléments robustes"],
    ),
    DnaProfile(
        "utility",
        "Utility",
        "Carrosserie fonctionnelle, éléments simples, bonne lisibilité des volumes.",
        {"utility": 90, "robust": 70, "sobriety": 75, "sport": 15, "luxury": 15, "aero": 20,
         "aggressive": 20, "modern": 45, "offroad": 35, "retro": 30},
        ["Carrosserie fonctionnelle", "Éléments simples", "Lisibilité des volumes",
         "Accessoires compatibles (galerie, protections)"],
    ),
    DnaProfile(
        "luxury",
        "Grand luxe",
        "Proportions nobles, calandre imposante, signature lumineuse fine, sobriété.",
        {"luxury": 90, "sobriety": 75, "modern": 60, "sport": 40, "aggressive": 25, "aero": 45,
         "robust": 40, "utility": 10, "offroad": 15, "retro": 40},
        ["Capot long et calandre imposante", "Signature lumineuse fine", "Peu d'appendices"],
    ),
    DnaProfile(
        "retro",
        "Rétro",
        "Optiques rondes, chromes, lignes horizontales et porte-à-faux généreux.",
        {"retro": 90, "luxury": 50, "sobriety": 50, "sport": 40, "modern": 15, "aero": 25,
         "aggressive": 30, "robust": 45, "utility": 25, "offroad": 15},
        ["Optiques rondes", "Calandre à barres chromées", "Lignes horizontales"],
    ),
    DnaProfile(
        "muscle",
        "Muscle",
        "Capot long et bombé, face avant agressive, arrière ramassé.",
        {"sport": 70, "aggressive": 85, "robust": 60, "retro": 55, "luxury": 30, "aero": 35,
         "modern": 35, "sobriety": 25, "utility": 15, "offroad": 10},
        ["Capot bombé, prise d'air", "Face avant agressive", "Sorties d'échappement doubles"],
    ),
    DnaProfile(
        "urban",
        "Compacte urbaine",
        "Volumes courts, porte-à-faux réduits, optiques expressives.",
        {"modern": 75, "utility": 50, "sobriety": 60, "sport": 35, "luxury": 30, "aero": 50,
         "aggressive": 30, "robust": 35, "offroad": 10, "retro": 25},
        ["Porte-à-faux réduits", "Optiques expressives", "Signature lumineuse continue"],
    ),
    DnaProfile(
        "supercar",
        "Supercar",
        "Silhouette très basse, arêtes vives, aérodynamique active visible.",
        {"sport": 95, "aggressive": 90, "aero": 95, "modern": 85, "luxury": 60, "sobriety": 15,
         "robust": 20, "utility": 0, "offroad": 0, "retro": 10},
        ["Toit très bas", "Lame avant et diffuseur", "Aileron", "Optiques en lame"],
    ),
)  # fmt: skip


def preset(key: str) -> DnaProfile | None:
    return next((p for p in PRESETS if p.key == key), None)


def blend(first: dict | None, second: dict | None, weight: float = 0.5) -> dict[str, int]:
    """Moyenne pondérée de deux ADN (ex. marque × direction choisie)."""
    a, b = normalize(first), normalize(second)
    w = max(0.0, min(1.0, weight))
    return {k: int(round(a[k] * (1 - w) + b[k] * w)) for k in PARAMETERS}


def dominant(values: dict, count: int = 3) -> list[tuple[str, int]]:
    norm = normalize(values)
    return sorted(norm.items(), key=lambda kv: -kv[1])[:count]


def describe(values: dict) -> str:
    top = dominant(values)
    return " · ".join(f"{PARAMETERS[k]} {v}" for k, v in top)


def weight(values: dict, key: str) -> float:
    """Valeur centrée −1 … +1 (50 = neutre) utilisée pour orienter les amplitudes."""
    return (normalize(values)[key] - NEUTRAL) / NEUTRAL


class DnaLibrary:
    """Profils intégrés + profils enregistrés (projet et bibliothèque utilisateur)."""

    def __init__(self, user_file: Path | None = None) -> None:
        self.user_file = user_file
        self.user: list[DnaProfile] = []
        self.project: list[DnaProfile] = []
        if user_file is not None and user_file.is_file():
            try:
                data = json.loads(user_file.read_text(encoding="utf-8"))
                self.user = [DnaProfile.from_dict(p) for p in data.get("profiles", []) if isinstance(p, dict)]
            except (OSError, ValueError, TypeError):
                self.user = []

    def all(self) -> list[DnaProfile]:
        seen: set[str] = set()
        result = []
        for profile in [*self.project, *self.user, *PRESETS]:
            if profile.key not in seen:
                seen.add(profile.key)
                result.append(profile)
        return result

    def get(self, key: str | None) -> DnaProfile | None:
        return next((p for p in self.all() if p.key == key), None)

    def save(self, name: str, values: dict, description: str = "", to_user: bool = False) -> DnaProfile:
        cleaned = " ".join(name.split()) or "Profil personnalisé"
        key = "custom-" + "".join(c for c in cleaned.lower() if c.isalnum())[:40]
        profile = DnaProfile(key, cleaned, description.strip(), values, origin="custom")
        self.project = [p for p in self.project if p.key != key] + [profile]
        if to_user and self.user_file is not None:
            self.user = [p for p in self.user if p.key != key] + [profile]
            self.user_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {"format": 1, "profiles": [p.to_dict() for p in self.user]}
            self.user_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return profile
