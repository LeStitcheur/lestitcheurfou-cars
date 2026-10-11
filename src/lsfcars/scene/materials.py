"""Matériaux PBR simplifiés (couleur, rugosité, métallicité, opacité, texture de couleur)."""

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
)


def new_material_id() -> str:
    return uuid.uuid4().hex


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


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

    def __post_init__(self) -> None:
        rgba = [*self.base_color, 1.0, 1.0, 1.0, 1.0][:4]
        self.base_color = tuple(_clamp01(c) for c in rgba)  # type: ignore[assignment]
        self.roughness = _clamp01(self.roughness)
        self.metallic = _clamp01(self.metallic)
        self.opacity = _clamp01(self.opacity)

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
        return data

    @classmethod
    def from_dict(cls, data: dict) -> Material:
        known = {key: data[key] for key in (*EDITABLE_FIELDS, "id") if key in data}
        if "base_color" in known:
            known["base_color"] = tuple(known["base_color"])
        return cls(**known)
