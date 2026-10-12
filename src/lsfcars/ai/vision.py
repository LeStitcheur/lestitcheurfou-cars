"""Vehicle Vision Analyzer : analyse locale des références (silhouette, proportions, roues…).

Analyse **algorithmique** (pas un réseau de neurones) fondée sur le détourage : rapport
longueur / hauteur, profil de toit, garde au sol, position et taille des roues, couleurs
dominantes, vitrages et optiques probables, incohérences entre vues. Le type de véhicule est
une proposition classée par score, modifiable. Toute mesure est **approximative** ; une
analyse cloud (si l'utilisateur l'active) peut compléter le rapport et reste identifiée comme
telle.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from lsfcars.ai import references as refs_mod
from lsfcars.ai.references import Segmentation

VEHICLE_TYPES: dict[str, str] = {
    "sedan": "Berline",
    "coupe": "Coupé",
    "suv": "SUV",
    "offroad": "4x4",
    "pickup": "Pick-up",
    "truck": "Camion",
    "van": "Van",
    "ambulance": "Ambulance",
    "motorcycle": "Moto",
    "helicopter": "Hélicoptère",
    "boat": "Bateau",
    "plane": "Aéronef",
    "special": "Véhicule spécialisé",
}
# Dimensions typiques (m) : base des mesures estimées quand aucune cote n'est fournie.
TYPICAL_LENGTH = {
    "sedan": 4.8,
    "coupe": 4.5,
    "suv": 4.8,
    "offroad": 4.6,
    "pickup": 5.5,
    "truck": 8.0,
    "van": 5.3,
    "ambulance": 6.0,
    "motorcycle": 2.1,
    "helicopter": 12.0,
    "boat": 7.0,
    "plane": 12.0,
    "special": 6.0,
}
TYPICAL_WIDTH_RATIO = {  # largeur / longueur
    "sedan": 0.39,
    "coupe": 0.42,
    "suv": 0.41,
    "offroad": 0.41,
    "pickup": 0.37,
    "truck": 0.31,
    "van": 0.38,
    "ambulance": 0.36,
    "motorcycle": 0.38,
}
LOCAL_TYPES = ("sedan", "coupe", "suv", "offroad", "pickup", "truck", "van", "ambulance", "motorcycle")


@dataclass
class ViewAnalysis:
    ref_id: str
    view: str
    segmentation: Segmentation
    aspect: float | None = None  # largeur / hauteur de la silhouette
    profile: np.ndarray | None = None  # hauteur relative du toit par colonne (avant → arrière)
    wheels: list[dict] = field(default_factory=list)  # {x, diameter} relatifs à la longueur
    clearance: float | None = None  # garde au sol / hauteur
    colors: list[dict] = field(default_factory=list)
    glass_ratio: float | None = None
    lights: int | None = None
    warnings: list[str] = field(default_factory=list)


def _field(value, source: str = "local", approx: bool = True, confidence: float = 0.5) -> dict:  # type: ignore[no-untyped-def]
    return {"value": value, "source": source, "approx": approx, "confidence": round(float(confidence), 2)}


def _hex(rgb: np.ndarray) -> str:
    r, g, b = (int(round(float(c))) for c in rgb[:3])
    return f"#{r:02X}{g:02X}{b:02X}"


def dominant_colors(pixels: np.ndarray, k: int = 5, seed: int = 7) -> list[dict]:
    """k-moyennes sur les pixels du véhicule ; parts décroissantes."""
    if len(pixels) == 0:
        return []
    rng = np.random.default_rng(seed)
    sample = pixels[rng.choice(len(pixels), size=min(len(pixels), 12000), replace=False)].astype(np.float32)
    k = min(k, len(sample))
    centers = sample[np.linspace(0, len(sample) - 1, k).astype(int)].copy()
    labels = np.zeros(len(sample), int)
    for _ in range(12):
        labels = np.argmin(((sample[:, None, :] - centers[None]) ** 2).sum(-1), axis=1)
        for index in range(k):
            members = sample[labels == index]
            if len(members):
                centers[index] = members.mean(axis=0)
    counts = np.bincount(labels, minlength=k)
    order = np.argsort(-counts)
    return [
        {"hex": _hex(centers[i]), "share": round(float(counts[i] / counts.sum()), 3)}
        for i in order
        if counts[i] > 0
    ]


def _luma(rgb: np.ndarray) -> np.ndarray:
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def _runs(flags: np.ndarray) -> list[tuple[int, int]]:
    """Plages contiguës de valeurs vraies : [(début, fin exclue)]."""
    padded = np.concatenate([[False], flags, [False]])
    changes = np.flatnonzero(padded[1:] != padded[:-1])
    return [(int(a), int(b)) for a, b in zip(changes[::2], changes[1::2], strict=False)]


def analyse_side(ref: dict, image: Image.Image, seg: Segmentation) -> ViewAnalysis:
    result = ViewAnalysis(ref["id"], ref["view"], seg, warnings=list(seg.warnings))
    if not seg.ok:
        result.warnings.append("Silhouette non exploitable : proportions non mesurées.")
        return result
    x0, y0, x1, y1 = seg.bbox
    mask = seg.mask[y0:y1, x0:x1]
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)[y0:y1, x0:x1]
    if not refs_mod.front_on_left(ref):  # toujours de l'avant vers l'arrière
        mask, rgb = mask[:, ::-1], rgb[:, ::-1]
    h, w = mask.shape
    result.aspect = w / max(h, 1)
    filled = mask.any(axis=0)
    top = np.where(filled, mask.argmax(axis=0), h)
    bottom = np.where(filled, h - 1 - mask[::-1].argmax(axis=0), 0)
    result.profile = np.clip(1.0 - top / max(h, 1), 0.0, 1.0)
    # Roues : colonnes où la silhouette touche le sol (pneus), séparées par la garde au sol
    ground = bottom >= h - 1 - max(2, int(h * 0.03))
    runs = [(a, b) for a, b in _runs(ground) if (b - a) >= max(2, int(w * 0.03))]
    luma = _luma(rgb)
    dark = luma < np.percentile(luma[mask], 30) if mask.any() else np.zeros_like(mask)
    lower = int(h * 0.5)
    wheels = []
    for a, b in runs:
        center = (a + b) / 2
        band = dark[lower:, max(0, a - int(w * 0.04)) : min(w, b + int(w * 0.04))]
        rows = np.flatnonzero(band.any(axis=1))
        diameter = (h - (lower + rows[0])) if len(rows) else (b - a) * 1.6
        wheels.append({"x": round(center / w, 3), "diameter": round(min(diameter, h * 0.6) / w, 3)})
    result.wheels = wheels
    if len(wheels) >= 2:
        start, end = int(wheels[0]["x"] * w), int(wheels[-1]["x"] * w)
        between = bottom[start:end]
        between = between[between > 0]
        if len(between):
            result.clearance = round(float((h - 1 - np.median(between)) / h), 3)
    else:
        result.warnings.append("Roues non localisées sur le profil (moins de deux contacts au sol).")
    result.colors = dominant_colors(rgb[mask])
    # Vitrages probables : pixels sombres et peu saturés dans la moitié haute de la silhouette
    upper = mask.copy()
    upper[int(h * 0.55) :] = False
    if upper.any():
        sat = rgb.max(axis=-1) - rgb.min(axis=-1)
        glass = upper & (luma < 90) & (sat < 60)
        result.glass_ratio = round(float(glass.sum() / upper.sum()), 3)
    return result


def analyse_end(ref: dict, image: Image.Image, seg: Segmentation) -> ViewAnalysis:
    """Vue avant / arrière : largeur / hauteur, optiques (zones très claires ou rouges)."""
    result = ViewAnalysis(ref["id"], ref["view"], seg, warnings=list(seg.warnings))
    if not seg.ok:
        result.warnings.append("Silhouette non exploitable.")
        return result
    x0, y0, x1, y1 = seg.bbox
    mask = seg.mask[y0:y1, x0:x1]
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)[y0:y1, x0:x1]
    h, w = mask.shape
    result.aspect = w / max(h, 1)
    result.colors = dominant_colors(rgb[mask])
    band = mask.copy()
    band[: int(h * 0.3)] = False
    band[int(h * 0.8) :] = False
    luma = _luma(rgb)
    red = (rgb[..., 0] > 150) & (rgb[..., 1] < 90) & (rgb[..., 2] < 90)
    bright = band & ((luma > np.percentile(luma[mask], 95)) | red)
    columns = bright.any(axis=0)
    result.lights = len([r for r in _runs(columns) if (r[1] - r[0]) >= max(2, int(w * 0.03))])
    return result


def analyse_view(ref: dict, image: Image.Image) -> ViewAnalysis:
    seg = refs_mod.segment(image)
    if ref.get("view") in refs_mod.SIDE_VIEWS:
        return analyse_side(ref, image, seg)
    if ref.get("view") in ("front", "back"):
        return analyse_end(ref, image, seg)
    result = ViewAnalysis(ref["id"], ref.get("view", ""), seg, warnings=list(seg.warnings))
    if seg.ok:
        x0, y0, x1, y1 = seg.bbox
        result.aspect = (x1 - x0) / max(y1 - y0, 1)
        rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
        result.colors = dominant_colors(rgb[seg.mask])
    return result


def classify(
    side: ViewAnalysis | None, end: ViewAnalysis | None, body_hex: str | None
) -> list[tuple[str, float]]:
    """Scores des types de véhicules routiers (règles sur les proportions), décroissants."""
    scores = dict.fromkeys(LOCAL_TYPES, 0.1)
    if side is None or side.aspect is None or side.profile is None:
        return sorted(scores.items(), key=lambda kv: -kv[1])
    aspect = side.aspect
    profile = side.profile
    n = len(profile)
    front = float(profile[: max(1, n // 5)].mean())
    rear = float(profile[-max(1, n // 5) :].mean())
    middle = float(profile[n // 3 : 2 * n // 3].mean())
    plateau = float((profile > 0.9).mean())
    tall = np.flatnonzero(profile > 0.85)
    hood_len = tall[0] / n if len(tall) else 0.0  # longueur basse à l'avant (capot)
    tail_len = (n - 1 - tall[-1]) / n if len(tall) else 0.0  # longueur basse à l'arrière (coffre, benne)
    clearance = side.clearance or 0.0
    narrow = end is not None and end.aspect is not None and end.aspect < 0.7

    def bump(key: str, amount: float) -> None:
        scores[key] += amount

    if narrow or (aspect < 1.9 and len(side.wheels) == 2 and middle < 0.8 and plateau < 0.15):
        bump("motorcycle", 1.4 if narrow else 0.6)
    if plateau > 0.55 and rear > 0.8:
        bump("van", 1.0)
        bump("truck", 0.6 if aspect > 2.7 else 0.0)
        if body_hex and _is_light(body_hex):
            bump("ambulance", 0.8)
    if tail_len > 0.33 and rear / max(middle, 1e-3) < 0.75 and plateau < 0.4:
        bump("pickup", 1.0 if aspect > 2.6 else 0.5)
    if 2.0 <= aspect <= 2.7 and rear > 0.7 and clearance > 0.12:
        bump("suv", 0.9)
        bump("offroad", 0.6 if clearance > 0.17 else 0.2)
    if aspect >= 2.4 and 0.1 <= tail_len <= 0.33 and 0.15 <= hood_len <= 0.42 and rear < 0.8:
        bump("sedan", 1.0)
    if aspect >= 2.6 and plateau <= 0.2 and middle > 0.8 and rear < 0.65 and front < 0.6:
        bump("coupe", 0.9)
    if aspect > 3.4:
        bump("truck", 0.7)
    return sorted(scores.items(), key=lambda kv: -kv[1])


def _rgb(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _is_light(hex_color: str) -> bool:
    return min(_rgb(hex_color)) > 175


def _color_distance(a: str, b: str) -> float:
    return float(np.linalg.norm(np.array(_rgb(a), float) - np.array(_rgb(b), float)))


def body_color(colors: list[dict]) -> str | None:
    """Couleur de carrosserie probable : couleur dominante ni très sombre (pneus, vitres)."""
    for color in colors:
        if max(_rgb(color["hex"])) > 55:
            return color["hex"]
    return colors[0]["hex"] if colors else None


def build_report(references: list[dict], images: dict, known_length: float | None = None) -> dict:
    """Rapport éditable : champs {value, source, approx, confidence}, avertissements, vues."""
    analyses = {ref["id"]: analyse_view(ref, images[ref["id"]]) for ref in references if ref["id"] in images}
    sides = [a for a in analyses.values() if a.view in refs_mod.SIDE_VIEWS and a.aspect]
    ends = [a for a in analyses.values() if a.view in ("front", "back") and a.aspect]
    side = sides[0] if sides else None
    end = next((a for a in ends if a.view == "front"), ends[0] if ends else None)
    main = side or end or next(iter(analyses.values()), None)
    colors = main.colors if main else []
    body = body_color(colors)
    ranking = classify(side, end, body)
    best, best_score = ranking[0]
    total = sum(s for _k, s in ranking)
    confidence = best_score / total if total else 0.0
    if side is None:
        confidence = min(confidence, 0.2)
    warnings: list[str] = []
    for analysis in analyses.values():
        warnings.extend(
            f"{refs_mod.VIEWS.get(analysis.view, analysis.view)} : {w}" for w in analysis.warnings
        )
    if len(sides) >= 2 and abs(sides[0].aspect - sides[1].aspect) / sides[0].aspect > 0.08:
        warnings.append(
            f"Profils gauche et droit incohérents (rapport L/H {sides[0].aspect:.2f} contre "
            f"{sides[1].aspect:.2f}) : perspective ou véhicules différents ?"
        )
    view_colors = [c for c in (body_color(a.colors) for a in analyses.values() if a.colors) if c]
    if len(view_colors) >= 2 and max(_color_distance(view_colors[0], c) for c in view_colors[1:]) > 110:
        warnings.append("Couleurs de carrosserie différentes selon les vues : vérifiez les références.")
    if any(r.get("view") == "three_quarter" for r in references) and not sides:
        warnings.append("Vue trois quarts seule : proportions mesurées avec la perspective (peu fiables).")

    fields: dict[str, dict] = {
        "type": _field(best, approx=False, confidence=confidence),
        "type_candidates": _field([{"type": k, "score": round(s, 2)} for k, s in ranking[:3]], approx=False),
    }
    length = known_length or TYPICAL_LENGTH.get(best, 4.8)
    fields["length_m"] = _field(
        round(length, 2),
        source="utilisateur" if known_length else "local",
        approx=not known_length,
        confidence=0.4,
    )
    if side is not None and side.aspect:
        height = length / side.aspect
        fields["aspect_lh"] = _field(round(side.aspect, 3), confidence=0.7)
        fields["height_m"] = _field(round(height, 2), confidence=0.4)
        if end is not None and end.aspect:
            fields["width_m"] = _field(round(height * end.aspect, 2), confidence=0.4)
        else:
            fields["width_m"] = _field(round(length * TYPICAL_WIDTH_RATIO.get(best, 0.4), 2), confidence=0.2)
        if len(side.wheels) >= 2:
            wheelbase = (side.wheels[-1]["x"] - side.wheels[0]["x"]) * length
            fields["wheelbase_m"] = _field(round(wheelbase, 2), confidence=0.45)
            diameter = float(np.mean([wh["diameter"] for wh in side.wheels])) * length
            fields["wheel_diameter_m"] = _field(round(diameter, 2), confidence=0.35)
        fields["wheels_visible"] = _field(len(side.wheels), confidence=0.6)
        if side.clearance is not None:
            fields["ground_clearance_m"] = _field(round(side.clearance * height, 2), confidence=0.3)
        profile = side.profile
        n = len(profile)
        fields["roof_profile"] = _field(
            {
                "hood": round(float(profile[: max(1, n // 5)].mean()), 2),
                "middle": round(float(profile[n // 3 : 2 * n // 3].mean()), 2),
                "rear": round(float(profile[-max(1, n // 5) :].mean()), 2),
                "flat_roof": round(float((profile > 0.9).mean()), 2),
            },
            confidence=0.6,
        )
        if side.glass_ratio is not None:
            fields["glass_ratio"] = _field(side.glass_ratio, confidence=0.3)
    if end is not None and end.lights is not None:
        fields["lights_" + end.view] = _field(end.lights, confidence=0.3)
    if body:
        fields["body_color"] = _field(body, approx=False, confidence=0.6)
    distinctive = []
    for ref in references:
        for note in ref.get("annotations", []):
            if note.get("kind") in ("detail", "grille", "light", "logo"):
                kind = refs_mod.ANNOTATION_KINDS.get(note["kind"], note["kind"])
                distinctive.append(f"{kind} : {note.get('text') or 'sans description'}")
    fields["distinctive"] = _field(distinctive, source="utilisateur", approx=False, confidence=1.0)
    real_logos = [n for r in references for n in r.get("annotations", []) if n.get("kind") == "logo"]
    return {
        "version": 1,
        "created_at": refs_mod.now_iso(),
        "method": "Analyse algorithmique locale (détourage, proportions, couleurs) — mesures approximatives",
        "fields": fields,
        "colors": colors,
        "wheels": side.wheels if side else [],
        "views": {
            a.ref_id: {
                "view": a.view,
                "segmentation": a.segmentation.method,
                "confidence": round(a.segmentation.confidence, 2),
            }
            for a in analyses.values()
        },
        "real_logos_marked": len(real_logos),
        "warnings": warnings,
        "cloud": None,
    }


def value(report: dict | None, key: str, default=None):  # type: ignore[no-untyped-def]
    if not report:
        return default
    entry = report.get("fields", {}).get(key)
    return entry.get("value", default) if isinstance(entry, dict) else default


def set_value(report: dict, key: str, new_value) -> None:  # type: ignore[no-untyped-def]
    """Correction de l'utilisateur : la valeur devient exacte (non approximative) et sourcée."""
    report.setdefault("fields", {})[key] = _field(
        new_value, source="utilisateur", approx=False, confidence=1.0
    )
