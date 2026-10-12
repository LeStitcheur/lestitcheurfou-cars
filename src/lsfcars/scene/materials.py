"""Matériaux PBR simplifiés : couleur, rugosité, métallicité, opacité, textures, UV, preset,
émission (v0.8 : optiques et signatures lumineuses, prévisualisation viewport uniquement)."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field

DEFAULT_BASE_COLOR = (0.72, 0.74, 0.78, 1.0)
EDITABLE_FIELDS = (
    "name",
    "base_color",
    "roughness",
    "metallic",
    "opacity",
    "texture",
    "double_sided",
    "normal_texture",
    "normal_strength",
    "uv_scale",
    "uv_offset",
    "preset",
    "gta_shader",
    "emissive",
    "emissive_strength",
)
EXTRA_FIELDS = (
    "normal_texture",
    "normal_strength",
    "uv_scale",
    "uv_offset",
    "preset",
    "gta_shader",
    "emissive",
    "emissive_strength",
)


def new_material_id() -> str:
    return uuid.uuid4().hex


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _pair(value, default: float) -> tuple[float, float]:  # type: ignore[no-untyped-def]
    try:
        a, b = (float(v) for v in value)
    except (TypeError, ValueError):
        return (default, default)
    return (a, b)


@dataclass
class Material:
    name: str
    base_color: tuple[float, float, float, float] = DEFAULT_BASE_COLOR
    roughness: float = 0.5
    metallic: float = 0.0
    opacity: float = 1.0
    texture: str | None = None  # chemin relatif au dossier du projet (assets/textures/…)
    double_sided: bool = True
    id: str = field(default_factory=new_material_id)
    normal_texture: str | None = None  # carte de normales (espace tangent), relative au projet
    normal_strength: float = 1.0
    uv_scale: tuple[float, float] = (1.0, 1.0)
    uv_offset: tuple[float, float] = (0.0, 0.0)
    preset: str = ""  # preset automobile d'origine (peinture brillante, chrome…)
    gta_shader: str = ""  # shader GTA V suggéré (indicatif, correspondance non garantie)
    emissive: tuple[float, float, float] = (0.0, 0.0, 0.0)  # couleur émise (viewport)
    emissive_strength: float = 0.0  # 0 = aucune émission

    def __post_init__(self) -> None:
        rgba = [*self.base_color, 1.0, 1.0, 1.0, 1.0][:4]
        self.base_color = tuple(_clamp01(c) for c in rgba)  # type: ignore[assignment]
        self.roughness = _clamp01(self.roughness)
        self.metallic = _clamp01(self.metallic)
        self.opacity = _clamp01(self.opacity)
        self.normal_strength = max(0.0, min(4.0, float(self.normal_strength)))
        self.uv_scale = _pair(self.uv_scale, 1.0)
        self.uv_offset = _pair(self.uv_offset, 0.0)
        self.preset = str(self.preset or "")
        self.gta_shader = str(self.gta_shader or "")
        rgb = [*self.emissive, 0.0, 0.0, 0.0][:3] if self.emissive is not None else [0.0, 0.0, 0.0]
        self.emissive = tuple(_clamp01(c) for c in rgb)  # type: ignore[assignment]
        self.emissive_strength = max(0.0, min(8.0, float(self.emissive_strength or 0.0)))

    @property
    def is_transparent(self) -> bool:
        return self.opacity < 0.999 or self.base_color[3] < 0.999

    def properties(self) -> dict:
        """Propriétés modifiables (pour l'historique d'annulation)."""
        return {key: getattr(self, key) for key in EDITABLE_FIELDS}

    def apply(self, properties: dict) -> None:
        for key, value in properties.items():
            if key in EDITABLE_FIELDS:
                setattr(self, key, value)
        self.__post_init__()

    def copy(self, keep_id: bool = False) -> Material:
        clone = Material(**self.properties())
        if keep_id:
            clone.id = self.id
        return clone

    def to_dict(self) -> dict:
        data = asdict(self)
        data["base_color"] = list(self.base_color)
        data["uv_scale"] = list(self.uv_scale)
        data["uv_offset"] = list(self.uv_offset)
        data["emissive"] = list(self.emissive)
        return data

    def extra_dict(self) -> dict:
        """Champs ajoutés en v0.4 (colonne ``materials.extra`` du ``.lsfc``)."""
        data = {key: getattr(self, key) for key in EXTRA_FIELDS}
        data["uv_scale"] = list(self.uv_scale)
        data["uv_offset"] = list(self.uv_offset)
        data["emissive"] = list(self.emissive)
        return data

    @property
    def is_emissive(self) -> bool:
        return self.emissive_strength > 0 and max(self.emissive) > 0

    @classmethod
    def from_dict(cls, data: dict) -> Material:
        known = {key: data[key] for key in (*EDITABLE_FIELDS, "id") if key in data}
        if "base_color" in known:
            known["base_color"] = tuple(known["base_color"])
        return cls(**known)
