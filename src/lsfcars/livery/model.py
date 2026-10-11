"""Document de livrée versionné : calques, variantes, palettes, presets, provenance.

Le document est un dictionnaire JSON rangé dans ``SceneGraph.documents["livery"]`` et modifié
uniquement par ``SetDocument`` (annulable). Les pixels des calques raster, masques et images
sont des ``ImageBuffer`` de ``SceneGraph.images`` (clés citées par le document) ; les logos et
polices importés sont des ``SceneGraph.blobs``. Rien n'est fusionné à l'enregistrement : le
projet rouvert reste entièrement éditable.

Ordre des calques : liste du **bas vers le haut** (indice 0 = calque du dessous).
Coordonnées : pixels de la texture, origine en haut à gauche (ligne 0 = v = 1).
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

DOC_KEY = "livery"
DOC_VERSION = 1
DEFAULT_SIZE = 2048
MAX_SIZE = 8192
STANDARD_SIZES = (1024, 2048, 4096)
DEFAULT_PRIMARY = "#2563EB"  # couleurs de dessin initiales (bleu principal, blanc)
DEFAULT_SECONDARY = "#F3F6FC"

BLEND_MODES = {
    "normal": "Normal",
    "multiply": "Produit (Multiply)",
    "screen": "Superposition claire (Screen)",
    "overlay": "Incrustation (Overlay)",
    "add": "Addition (Add)",
    "darken": "Obscurcir",
    "lighten": "Éclaircir",
}
LAYER_KINDS = {
    "raster": "Calque raster",
    "vector": "Calque vectoriel",
    "text": "Calque texte",
    "image": "Calque image",
    "band": "Bande 3D",
    "group": "Groupe",
}
VECTOR_SHAPES = {
    "line": "Ligne",
    "rect": "Rectangle",
    "rounded_rect": "Rectangle arrondi",
    "circle": "Cercle",
    "ellipse": "Ellipse",
    "polygon": "Polygone",
    "curve": "Courbe",
}
MODES = {
    "texture": "Texture complète (remplace la texture du matériau)",
    "decal": "Livrée transparente sur la couleur de peinture (style GTA V « sign »)",
}
BLEND_SPACES = {
    "srgb": "sRGB (comme les éditeurs d'images courants)",
    "linear": "Linéaire (lumière physique)",
}


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def hex_color(value: str | None, default: str = "#FFFFFF") -> str:
    """Normalise une couleur « #RRGGBB » ou « #RRGGBBAA »."""
    text = str(value or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    if len(text) not in (6, 8):
        return default
    try:
        int(text, 16)
    except ValueError:
        return default
    return "#" + text.upper()


def rgba(value: str) -> tuple[int, int, int, int]:
    text = hex_color(value).lstrip("#")
    r, g, b = (int(text[i : i + 2], 16) for i in (0, 2, 4))
    a = int(text[6:8], 16) if len(text) == 8 else 255
    return r, g, b, a


def to_hex(r: float, g: float, b: float, a: float | None = None) -> str:
    values = [r, g, b] + ([a] if a is not None and a < 255 else [])
    return "#" + "".join(f"{max(0, min(255, round(v))):02X}" for v in values)


# --- Calques -------------------------------------------------------------------------------


@dataclass
class Layer:
    kind: str
    name: str
    id: str = field(default_factory=lambda: new_id("L"))
    visible: bool = True
    locked: bool = False
    opacity: float = 1.0
    blend: str = "normal"
    image: str | None = None  # pixels (raster) ou image placée (image) : clé de SceneGraph.images
    mask: str | None = None  # masque (niveaux de gris, blanc = visible) : clé de SceneGraph.images
    mask_enabled: bool = True
    params: dict = field(default_factory=dict)
    children: list[Layer] = field(default_factory=list)  # groupe : du bas vers le haut

    def __post_init__(self) -> None:
        if self.kind not in LAYER_KINDS:
            raise ValueError(f"type de calque inconnu : {self.kind}")
        self.opacity = max(0.0, min(1.0, float(self.opacity)))
        if self.blend not in BLEND_MODES:
            self.blend = "normal"

    @property
    def label(self) -> str:
        return LAYER_KINDS[self.kind]

    def walk(self) -> Iterator[Layer]:
        yield self
        for child in self.children:
            yield from child.walk()

    def image_keys(self) -> set[str]:
        keys = set()
        for layer in self.walk():
            keys |= {k for k in (layer.image, layer.mask) if k}
        return keys

    def to_dict(self) -> dict:
        data = {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "visible": self.visible,
            "locked": self.locked,
            "opacity": round(self.opacity, 4),
            "blend": self.blend,
            "image": self.image,
            "mask": self.mask,
            "mask_enabled": self.mask_enabled,
            "params": copy.deepcopy(self.params),
        }
        if self.kind == "group":
            data["children"] = [c.to_dict() for c in self.children]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> Layer:
        return cls(
            kind=str(data.get("kind", "raster")),
            name=str(data.get("name", "Calque")),
            id=str(data.get("id") or new_id("L")),
            visible=bool(data.get("visible", True)),
            locked=bool(data.get("locked", False)),
            opacity=float(data.get("opacity", 1.0)),
            blend=str(data.get("blend", "normal")),
            image=data.get("image"),
            mask=data.get("mask"),
            mask_enabled=bool(data.get("mask_enabled", True)),
            params=dict(data.get("params") or {}),
            children=[cls.from_dict(c) for c in data.get("children") or []],
        )


# --- Variantes et document ------------------------------------------------------------------


@dataclass
class LiveryVariant:
    name: str
    id: str = field(default_factory=lambda: new_id("V"))
    layers: list[Layer] = field(default_factory=list)
    emergency_variant: str | None = None  # variante d'Emergency Studio associée
    template: str = ""
    base_visible: bool = True  # texture d'origine sous les calques
    use_shared: bool = True  # éléments communs du document
    metadata: dict = field(default_factory=dict)  # service, numéro d'unité, indicatif…
    created_at: str = field(default_factory=now_iso)

    def walk(self) -> Iterator[Layer]:
        for layer in self.layers:
            yield from layer.walk()

    def image_keys(self) -> set[str]:
        return {k for layer in self.layers for k in layer.image_keys()}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "layers": [layer.to_dict() for layer in self.layers],
            "emergency_variant": self.emergency_variant,
            "template": self.template,
            "base_visible": self.base_visible,
            "use_shared": self.use_shared,
            "metadata": copy.deepcopy(self.metadata),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> LiveryVariant:
        return cls(
            name=str(data.get("name", "Livrée")),
            id=str(data.get("id") or new_id("V")),
            layers=[Layer.from_dict(d) for d in data.get("layers") or []],
            emergency_variant=data.get("emergency_variant"),
            template=str(data.get("template", "")),
            base_visible=bool(data.get("base_visible", True)),
            use_shared=bool(data.get("use_shared", True)),
            metadata=dict(data.get("metadata") or {}),
            created_at=str(data.get("created_at") or now_iso()),
        )


@dataclass
class LiveryDocument:
    width: int = DEFAULT_SIZE
    height: int = DEFAULT_SIZE
    targets: list[str] = field(default_factory=list)  # matériaux recevant la texture de livrée
    mode: str = "texture"
    base_texture: str | None = None  # texture d'origine (chemin relatif au projet), jamais modifiée
    texture_name: str = "livree"
    blend_space: str = "srgb"
    variants: list[LiveryVariant] = field(default_factory=list)
    active: str | None = None
    shared_layers: list[Layer] = field(default_factory=list)  # communs aux variantes (sous leurs calques)
    palettes: dict[str, list[str]] = field(default_factory=dict)
    color_history: list[str] = field(default_factory=list)
    user_templates: list[dict] = field(default_factory=list)
    fonts: list[dict] = field(default_factory=list)  # polices importées : famille, blob, licence…
    provenance: list[dict] = field(default_factory=list)  # logos et images : auteur, source, licence
    version: int = DOC_VERSION

    def __post_init__(self) -> None:
        self.width = max(16, min(MAX_SIZE, int(self.width)))
        self.height = max(16, min(MAX_SIZE, int(self.height)))
        if self.mode not in MODES:
            self.mode = "texture"
        if self.blend_space not in BLEND_SPACES:
            self.blend_space = "srgb"

    # --- Lecture --------------------------------------------------------------------------
    def variant(self, variant_id: str | None = None) -> LiveryVariant | None:
        wanted = variant_id or self.active
        return next((v for v in self.variants if v.id == wanted), None)

    @property
    def active_variant(self) -> LiveryVariant | None:
        return self.variant()

    def find(self, layer_id: str, variant: LiveryVariant | None = None) -> tuple[Layer, list[Layer]] | None:
        """Calque et liste qui le contient (variante active, puis éléments communs)."""
        variant = variant or self.active_variant
        stacks = ([variant.layers] if variant is not None else []) + [self.shared_layers]
        for stack in stacks:
            found = _find(stack, layer_id)
            if found is not None:
                return found
        return None

    def image_keys(self) -> set[str]:
        keys = {k for v in self.variants for k in v.image_keys()}
        return keys | {k for layer in self.shared_layers for k in layer.image_keys()}

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "width": self.width,
            "height": self.height,
            "targets": list(self.targets),
            "mode": self.mode,
            "base_texture": self.base_texture,
            "texture_name": self.texture_name,
            "blend_space": self.blend_space,
            "variants": [v.to_dict() for v in self.variants],
            "active": self.active,
            "shared_layers": [layer.to_dict() for layer in self.shared_layers],
            "palettes": copy.deepcopy(self.palettes),
            "color_history": list(self.color_history),
            "user_templates": copy.deepcopy(self.user_templates),
            "fonts": copy.deepcopy(self.fonts),
            "provenance": copy.deepcopy(self.provenance),
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> LiveryDocument | None:
        if not data:
            return None
        version = int(data.get("version", 1))
        if version > DOC_VERSION:
            raise ValueError(
                f"Document de livrée au format {version} : logiciel trop ancien (format {DOC_VERSION})."
            )
        return cls(
            width=int(data.get("width", DEFAULT_SIZE)),
            height=int(data.get("height", DEFAULT_SIZE)),
            targets=[str(t) for t in data.get("targets") or []],
            mode=str(data.get("mode", "texture")),
            base_texture=data.get("base_texture"),
            texture_name=str(data.get("texture_name") or "livree"),
            blend_space=str(data.get("blend_space", "srgb")),
            variants=[LiveryVariant.from_dict(v) for v in data.get("variants") or []],
            active=data.get("active"),
            shared_layers=[Layer.from_dict(d) for d in data.get("shared_layers") or []],
            palettes={str(k): [hex_color(c) for c in v] for k, v in (data.get("palettes") or {}).items()},
            color_history=[hex_color(c) for c in data.get("color_history") or []],
            user_templates=list(data.get("user_templates") or []),
            fonts=list(data.get("fonts") or []),
            provenance=list(data.get("provenance") or []),
            version=DOC_VERSION,
        )


def _find(stack: list[Layer], layer_id: str) -> tuple[Layer, list[Layer]] | None:
    for layer in stack:
        if layer.id == layer_id:
            return layer, stack
        if layer.children:
            found = _find(layer.children, layer_id)
            if found is not None:
                return found
    return None


def clone_layer(layer: Layer, image_map: dict[str, str]) -> Layer:
    """Copie profonde avec de nouveaux identifiants ; ``image_map`` reçoit ancienne → nouvelle clé."""
    data = layer.to_dict()

    def renew(item: dict) -> None:
        item["id"] = new_id("L")
        for slot in ("image", "mask"):
            key = item.get(slot)
            if key:
                image_map.setdefault(key, new_id("img-"))
                item[slot] = image_map[key]
        for child in item.get("children") or []:
            renew(child)

    renew(data)
    return Layer.from_dict(data)
