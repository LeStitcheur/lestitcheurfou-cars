"""Presets de matériaux automobiles (valeurs originales, aucune texture tierce).

Chaque preset propose un shader GTA V **indicatif** pour préparer une future conversion :
la correspondance exacte n'est pas garantie (les shaders GTA V utilisent leurs propres
paramètres et textures, non générés par LeStitcheurFou Cars).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MaterialPreset:
    key: str
    label: str
    base_color: tuple[float, float, float, float]
    roughness: float
    metallic: float
    opacity: float = 1.0
    gta_shader: str = ""
    note: str = ""

    def properties(self) -> dict:
        return {
            "base_color": self.base_color,
            "roughness": self.roughness,
            "metallic": self.metallic,
            "opacity": self.opacity,
            "preset": self.key,
            "gta_shader": self.gta_shader,
        }


PRESETS: tuple[MaterialPreset, ...] = (
    MaterialPreset(
        "paint_gloss",
        "Peinture brillante",
        (0.08, 0.22, 0.62, 1.0),
        0.18,
        0.35,
        1.0,
        "vehicle_paint1",
        "Teinte de carrosserie (couleur primaire carcols)",
    ),
    MaterialPreset(
        "paint_matte",
        "Peinture mate",
        (0.14, 0.15, 0.17, 1.0),
        0.78,
        0.05,
        1.0,
        "vehicle_paint1",
        "Aspect mat obtenu par la spécularité, à vérifier en jeu",
    ),
    MaterialPreset("metal", "Métal brossé", (0.62, 0.63, 0.65, 1.0), 0.42, 1.0, 1.0, "vehicle_mesh"),
    MaterialPreset(
        "chrome",
        "Chrome",
        (0.92, 0.93, 0.95, 1.0),
        0.04,
        1.0,
        1.0,
        "vehicle_mesh",
        "Reflets chromés dépendant de la carte spéculaire en jeu",
    ),
    MaterialPreset("plastic", "Plastique", (0.07, 0.07, 0.08, 1.0), 0.55, 0.0, 1.0, "vehicle_mesh"),
    MaterialPreset("rubber", "Caoutchouc", (0.05, 0.05, 0.055, 1.0), 0.9, 0.0, 1.0, "vehicle_tire"),
    MaterialPreset("glass", "Verre", (0.55, 0.62, 0.68, 0.35), 0.03, 0.0, 0.35, "vehicle_vehglass"),
    MaterialPreset("fabric", "Tissu", (0.18, 0.19, 0.22, 1.0), 0.95, 0.0, 1.0, "vehicle_interior"),
    MaterialPreset("leather", "Cuir", (0.24, 0.13, 0.08, 1.0), 0.6, 0.0, 1.0, "vehicle_interior"),
)
PRESETS_BY_KEY = {p.key: p for p in PRESETS}
GTA_SHADER_DISCLAIMER = (
    "Shader GTA V suggéré à titre indicatif : la correspondance exacte n'est pas garantie et "
    "devra être validée lors d'un export réel."
)


def preset(key: str) -> MaterialPreset | None:
    return PRESETS_BY_KEY.get(key)
