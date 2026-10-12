"""Reference Studio : images de référence, vues, préparation, détourage et cohérence.

Une référence est décrite par un dictionnaire JSON (document ``ai`` du projet) ; l'image
d'origine est conservée intacte dans ``SceneGraph.blobs`` (clé = empreinte SHA-256). Toutes les
retouches (rotation, miroir, recadrage, réglages) sont non destructives et recalculées.

Le détourage local est un algorithme simple : couche alpha de l'image si elle existe, sinon
fond uni estimé sur les bords puis propagation depuis les bords. Sur une photo avec décor, il
échoue et le signale (confiance faible) ; aucune silhouette n'est inventée.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np
from PIL import Image, ImageEnhance, ImageOps, UnidentifiedImageError

from lsfcars.ai.errors import AIError

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")
MAX_IMAGE_BYTES = 40 * 1024 * 1024
MAX_PIXELS = 8192 * 8192
SEGMENT_SIZE = 320  # côté de travail du détourage (pixels)

VIEWS: dict[str, str] = {
    "front": "Vue avant",
    "back": "Vue arrière",
    "left": "Profil gauche",
    "right": "Profil droit",
    "three_quarter": "Vue trois quarts",
    "top": "Vue du dessus",
    "interior": "Vue intérieure",
    "detail": "Détail",
}
SIDE_VIEWS = ("left", "right")
ANNOTATION_KINDS: dict[str, str] = {
    "logo": "Logo / marque réelle",
    "wheel": "Roue",
    "light": "Optique",
    "glass": "Vitrage",
    "grille": "Calandre",
    "detail": "Élément distinctif",
    "note": "Note",
}


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def blob_key(data: bytes) -> str:
    return "ref-" + hashlib.sha256(data).hexdigest()[:40]


def open_image(data: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise AIError(f"Image illisible : {exc}") from exc
    if image.width * image.height > MAX_PIXELS:
        raise AIError("Image trop grande (plus de 67 mégapixels).")
    return ImageOps.exif_transpose(image)


def new_reference(data: bytes, name: str, view: str = "three_quarter", source: str = "") -> dict:
    """Valide l'image et crée la description d'une référence (l'image va dans les blobs)."""
    if len(data) > MAX_IMAGE_BYTES:
        raise AIError("Image trop volumineuse (40 Mo au plus).")
    image = open_image(data)
    return {
        "id": uuid.uuid4().hex,
        "name": name,
        "blob": blob_key(data),
        "view": view if view in VIEWS else "three_quarter",
        "width": image.width,
        "height": image.height,
        "order": 0,
        "rotation": 0,
        "flip": False,
        "crop": [0.0, 0.0, 1.0, 1.0],
        "adjust": {"brightness": 1.0, "contrast": 1.0, "saturation": 1.0},
        "annotations": [],
        "front_left": None,  # profils : avant à gauche de l'image (None : convention de la vue)
        "source": source,
        "author": "",
        "license": "",
        "notes": "",
        "added_at": now_iso(),
    }


def guess_view(name: str) -> str:
    """Vue proposée d'après le nom du fichier (modifiable)."""
    lower = name.lower()
    rules = (
        (("arriere", "arrière", "rear", "back"), "back"),
        (("avant", "front", "face"), "front"),
        (("gauche", "left"), "left"),
        (("droit", "right"), "right"),
        (("dessus", "top"), "top"),
        (("interieur", "intérieur", "interior", "cockpit"), "interior"),
        (("detail", "détail"), "detail"),
        (("3-4", "3_4", "trois", "quarter"), "three_quarter"),
    )
    for words, view in rules:
        if any(w in lower for w in words):
            return view
    return "three_quarter"


def front_on_left(ref: dict) -> bool:
    """Profil gauche : l'avant pointe vers la gauche de l'image ; profil droit : vers la droite."""
    value = ref.get("front_left")
    if value is None:
        return ref.get("view") != "right"
    return bool(value)


def prepare(ref: dict, data: bytes, max_side: int | None = None) -> Image.Image:
    """Image retouchée (orientation, miroir, recadrage, réglages), RGBA."""
    image = open_image(data).convert("RGBA")
    rotation = int(ref.get("rotation", 0)) % 360
    if rotation:
        image = image.rotate(-rotation, expand=True)
    if ref.get("flip"):
        image = ImageOps.mirror(image)
    x0, y0, x1, y1 = (float(v) for v in ref.get("crop", (0, 0, 1, 1)))
    x0, x1 = sorted((max(0.0, min(1.0, x0)), max(0.0, min(1.0, x1))))
    y0, y1 = sorted((max(0.0, min(1.0, y0)), max(0.0, min(1.0, y1))))
    if (x1 - x0) > 0.02 and (y1 - y0) > 0.02 and (x0, y0, x1, y1) != (0.0, 0.0, 1.0, 1.0):
        w, h = image.size
        image = image.crop((round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h)))
    adjust = ref.get("adjust") or {}
    alpha = image.getchannel("A")
    rgb = image.convert("RGB")
    for key, enhancer in (
        ("brightness", ImageEnhance.Brightness),
        ("contrast", ImageEnhance.Contrast),
        ("saturation", ImageEnhance.Color),
    ):
        factor = float(adjust.get(key, 1.0))
        if abs(factor - 1.0) > 1e-3:
            rgb = enhancer(rgb).enhance(factor)
    image = rgb.convert("RGBA")
    image.putalpha(alpha)
    if max_side and max(image.size) > max_side:
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return image


# --- Détourage ----------------------------------------------------------------------------------


@dataclass
class Segmentation:
    mask: np.ndarray  # (H, W) bool, à la taille de l'image préparée
    method: str  # « alpha », « fond uni », « échec »
    confidence: float  # 0..1
    bbox: tuple[int, int, int, int] | None  # x0, y0, x1, y1 (pixels, x1/y1 exclus)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.bbox is not None and self.confidence >= 0.35


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    rows, cols = np.flatnonzero(mask.any(axis=1)), np.flatnonzero(mask.any(axis=0))
    if not len(rows) or not len(cols):
        return None
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def _grow(seed: np.ndarray, allowed: np.ndarray, limit: int = 2000) -> np.ndarray:
    """Propagation 4-connexe de ``seed`` dans ``allowed`` (reconstruction géodésique)."""
    region = seed & allowed
    for _ in range(limit):
        grown = region.copy()
        grown[1:] |= region[:-1]
        grown[:-1] |= region[1:]
        grown[:, 1:] |= region[:, :-1]
        grown[:, :-1] |= region[:, 1:]
        grown &= allowed
        if np.array_equal(grown, region):
            break
        region = grown
    return region


def _fill_holes(mask: np.ndarray) -> np.ndarray:
    outside = np.zeros_like(mask)
    outside[0, :] = outside[-1, :] = True
    outside[:, 0] = outside[:, -1] = True
    return ~_grow(outside & ~mask, ~mask)


def segment(image: Image.Image) -> Segmentation:
    """Détourage local : alpha si présent, sinon fond uni des bords."""
    full_w, full_h = image.size
    rgba = image.convert("RGBA")
    alpha = np.asarray(rgba.getchannel("A"))
    if alpha.min() < 250 and (alpha < 128).mean() > 0.02:
        mask = alpha >= 128
        box = _bbox(mask)
        return Segmentation(mask, "alpha", 1.0 if box else 0.0, box)
    small = rgba.convert("RGB").copy()
    small.thumbnail((SEGMENT_SIZE, SEGMENT_SIZE), Image.Resampling.BILINEAR)
    pixels = np.asarray(small, dtype=np.float32)
    h, w = pixels.shape[:2]
    border = np.concatenate([pixels[0], pixels[-1], pixels[:, 0], pixels[:, -1]])
    background = np.median(border, axis=0)
    spread = float(np.percentile(np.linalg.norm(border - background, axis=1), 90))
    warnings = []
    if spread > 40:
        warnings.append(
            "Fond non uniforme : le détourage local est peu fiable. Utilisez une image détourée "
            "(PNG transparent) ou un fond uni."
        )
    distance = np.linalg.norm(pixels - background, axis=2)
    threshold = max(18.0, spread * 1.6 + 8.0)
    allowed = distance < threshold
    seed = np.zeros((h, w), bool)
    seed[0, :] = seed[-1, :] = True
    seed[:, 0] = seed[:, -1] = True
    background_region = _grow(seed, allowed)
    mask = _fill_holes(~background_region)
    # retire le bruit isolé par une ouverture simple
    eroded = mask.copy()
    eroded[1:-1, 1:-1] = (
        mask[1:-1, 1:-1] & mask[:-2, 1:-1] & mask[2:, 1:-1] & mask[1:-1, :-2] & mask[1:-1, 2:]
    )
    opened = _grow(eroded, mask, limit=3)
    coverage_ratio = float(opened.mean())
    box = _bbox(opened)
    confidence = max(0.0, 1.0 - spread / 80.0)
    if box is None or coverage_ratio < 0.01:
        warnings.append("Aucun véhicule distinct du fond n'a été trouvé.")
        confidence = 0.0
    elif coverage_ratio > 0.92:
        warnings.append("Le sujet occupe presque toute l'image : le fond n'a pas pu être séparé.")
        confidence = min(confidence, 0.2)
    elif box[0] == 0 or box[1] == 0 or box[2] == w or box[3] == h:
        warnings.append("Le véhicule touche le bord de l'image : il est peut-être coupé.")
        confidence = min(confidence, 0.6)
    full = np.asarray(
        Image.fromarray(opened.astype(np.uint8) * 255).resize((full_w, full_h), Image.Resampling.BILINEAR)
    )
    mask_full = full >= 128
    method = "fond uni" if confidence >= 0.35 else "échec"
    return Segmentation(mask_full, method, confidence, _bbox(mask_full), warnings)


# --- Cohérence ----------------------------------------------------------------------------------


@dataclass
class CoverageReport:
    views: dict[str, int]  # vue → nombre d'images
    estimated_zones: list[str]  # zones à reconstruire par estimation
    warnings: list[str]

    @property
    def can_multiview(self) -> bool:
        return sum(1 for v in ("front", "back", "left", "right", "top") if self.views.get(v)) >= 2


def coverage(refs: list[dict]) -> CoverageReport:
    views = dict.fromkeys(VIEWS, 0)
    for ref in refs:
        view = ref.get("view", "three_quarter")
        views[view] = views.get(view, 0) + 1
    zones = []
    sides = [v for v in SIDE_VIEWS if views[v]]
    if not sides and not views["three_quarter"]:
        zones.append("Profil complet (aucune vue de côté)")
    elif len(sides) == 1:
        other = "droit" if sides[0] == "left" else "gauche"
        zones.append(f"Flanc {other} (supposé symétrique)")
    if not views["front"]:
        zones.append("Face avant (largeur, calandre, optiques)")
    if not views["back"]:
        zones.append("Face arrière (feux, hayon / coffre)")
    if not views["top"]:
        zones.append("Toit, capot et vue en plan (largeur estimée)")
    if not views["interior"]:
        zones.append("Habitacle (non reconstruit)")
    zones.append("Soubassement (jamais visible : estimé)")
    warnings = []
    for key, count in views.items():
        if count > 1 and key not in ("detail", "interior"):
            warnings.append(
                f"{count} images pour « {VIEWS[key]} » : seule la première sert à la reconstruction."
            )
    for ref in refs:
        if min(int(ref.get("width", 0)), int(ref.get("height", 0))) < 384:
            warnings.append(
                f"« {ref.get('name')} » : résolution faible ({ref.get('width')}×{ref.get('height')})."
            )
    return CoverageReport(views, zones, warnings)


def first_of(refs: list[dict], view: str) -> dict | None:
    return next((r for r in refs if r.get("view") == view), None)


def ordered(refs: list[dict]) -> list[dict]:
    return sorted(refs, key=lambda r: int(r.get("order", 0)))
