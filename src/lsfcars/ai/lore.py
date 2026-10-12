"""Lore Friendly AI Assistant : véhicule original cohérent avec l'univers satirique de GTA V.

- **Marques et noms fictifs** générés localement (syllabes, déterministes pour un projet) et
  filtrés : jamais une marque automobile réelle connue, jamais une marque de l'univers GTA
  (propriété de Rockstar Games) — l'utilisateur reste libre de ses choix.
- **Trois propositions** (adaptation légère, équilibrée, originale) fondées sur le rapport
  d'analyse : calandre, optiques, carrosserie, détails distinctifs, direction artistique.
- **Ajustements géométriques applicables** (capot, toit, voies, garde au sol) : déformations
  paramétriques lisses, appliquées sur confirmation via l'historique (annulables).
- **Logos réels** : aucune reconnaissance automatique locale (aucun modèle de détection
  embarqué) ; les logos se marquent par annotation sur les références, ou sont listés par une
  analyse cloud si l'utilisateur l'active. Les zones annotées sont masquées dans les textures
  projetées (AI Texture Creator).

Remplacer un logo ne suffit pas à garantir le respect des droits de propriété intellectuelle,
et aucune vérification de l'application n'est une certification de conformité aux règles de
Rockstar Games ou de Cfx.re.
"""

from __future__ import annotations

import hashlib
import random

import numpy as np

from lsfcars.ai import vision
from lsfcars.scene.editmesh import FACE, EditError, EditResult
from lsfcars.scene.mesh import MeshData, compute_vertex_normals

DISCLAIMER = (
    "Remplacer un logo ou un nom ne suffit pas à garantir le respect des droits de propriété "
    "intellectuelle (formes, calandres et signatures lumineuses peuvent aussi être protégées). "
    "Les suggestions et vérifications de l'application ne constituent ni un avis juridique ni une "
    "certification de conformité aux règles de Rockstar Games ou de Cfx.re."
)
LEVELS = {
    "light": "Adaptation légère",
    "balanced": "Adaptation équilibrée",
    "original": "Adaptation originale",
}

# Marques automobiles réelles connues : filtrage des noms générés (liste non exhaustive).
REAL_BRANDS = {
    "abarth", "acura", "alfa", "alpine", "aston", "audi", "bentley", "bmw", "bugatti", "buick", "byd",
    "cadillac", "chevrolet", "chevy", "chrysler", "citroen", "cupra", "dacia", "daewoo", "daihatsu",
    "dodge", "ds", "ferrari", "fiat", "fisker", "ford", "geely", "genesis", "gmc", "honda", "hummer",
    "hyundai", "infiniti", "isuzu", "iveco", "jaguar", "jeep", "kia", "koenigsegg", "lada", "lamborghini",
    "lancia", "land", "lexus", "lincoln", "lotus", "lucid", "man", "maserati", "maybach", "mazda",
    "mclaren", "mercedes", "mini", "mitsubishi", "nissan", "opel", "pagani", "peugeot", "polestar",
    "pontiac", "porsche", "ram", "renault", "rimac", "rivian", "rover", "saab", "scania", "seat",
    "skoda", "smart", "subaru", "suzuki", "tata", "tesla", "toyota", "vauxhall", "volkswagen", "volvo",
    "yamaha", "ducati", "harley", "kawasaki", "triumph", "piaggio", "vespa", "aprilia", "ktm",
}  # fmt: skip
# Marques de l'univers GTA (Rockstar Games) : évitées pour ne pas reprendre l'existant.
GTA_BRANDS = {
    "albany", "annis", "benefactor", "bf", "bollokan", "bravado", "brute", "buckingham", "canis",
    "chariot", "cheval", "coil", "declasse", "dewbauchee", "dinka", "dundreary", "emperor", "enus",
    "fathom", "gallivanter", "grotti", "hijak", "hvy", "imponte", "invetero", "jacksheepe", "jobuilt",
    "karin", "lampadati", "maibatsu", "mammoth", "maxwell", "mtl", "nagasaki", "obey", "ocelot",
    "overflod", "pegassi", "pfister", "principe", "progen", "rune", "schyster", "shitzu", "speedophile",
    "stanley", "truffade", "ubermacht", "vapid", "vulcar", "vysser", "weeny", "western", "willard",
    "zirconium",
}  # fmt: skip

_ONSETS = ["Ar", "Bel", "Cor", "Dra", "Ev", "Fal", "Gar", "Hal", "Is", "Jur", "Kel", "Lor", "Mar", "Nov",
           "Or", "Pel", "Quor", "Ros", "Sal", "Tor", "Ul", "Var", "Wex", "Zan", "Bray", "Clov",
           "Strav"]  # fmt: skip
_CODAS = ["ane", "ard", "ell", "en", "ero", "ex", "ian", "ico", "is", "ont", "ora", "ova", "ux", "ys",
          "ette", "ano", "ik", "oro", "ar", "esk"]  # fmt: skip
_MODEL_WORDS = {
    "sedan": ["Meridian", "Corvane", "Solenne", "Ambrel", "Vestor", "Calder"],
    "coupe": ["Striva", "Zephro", "Velaro", "Kestrel GT", "Ardent", "Nerio"],
    "suv": ["Ridgeback", "Taluvo", "Cairnline", "Sentry X", "Granitor", "Vallis"],
    "offroad": ["Rockhound", "Dunecrest", "Traverso", "Basalt", "Outrun", "Gorge"],
    "pickup": ["Haulmaster", "Fieldline", "Brakon", "Tillar", "Cargon", "Mesa"],
    "truck": ["Ironhaul", "Freightor", "Titanus", "Roadbarge", "Colossa", "Atlasline"],
    "van": ["Transa", "Courier V", "Shuttlo", "Packet", "Cabover", "Convoy"],
    "ambulance": ["Medivan", "Lifeline", "Rescuer", "Vital", "Pulse", "Samaritan"],
    "motorcycle": ["Razzo", "Viper R", "Stilo", "Kinetta", "Fulmen", "Torque S"],
}
_GRILLES = {
    "light": ["grille de même taille, motif à barres horizontales au lieu du motif d'origine",
              "contour de calandre conservé, maillage en losanges fins"],
    "balanced": ["calandre élargie jusqu'aux optiques, barre centrale",
                 "calandre trapézoïdale inversée avec entrée d'air inférieure séparée"],
    "original": ["face avant sans calandre apparente, prise d'air basse pleine largeur",
                 "calandre verticale étroite type « bouclier », phares intégrés au bandeau"],
}  # fmt: skip
_LIGHTS = {
    "light": ["signature lumineuse modifiée (bande LED continue)", "phares au contour légèrement étiré"],
    "balanced": ["phares affinés en lame, feux arrière reliés par un bandeau",
                 "optiques doubles superposées"],
    "original": ["phares masqués derrière une lame", "feux arrière en forme de crochet"],
}  # fmt: skip
_BODY = {
    "light": ["nervure latérale déplacée", "rétroviseurs et poignées redessinés"],
    "balanced": ["capot rallongé, pare-chocs redessinés",
                 "toit légèrement abaissé, montants arrière épaissis"],
    "original": ["proportions revues (porte-à-faux, hauteur, voies)",
                 "ligne de caisse et vitrages redessinés"],
}  # fmt: skip
_DIRECTIONS = {
    "light": "Proche de la référence, distinguée par son identité (logo, nom, calandre, optiques).",
    "balanced": "Inspirée de la référence, avec une face avant et une signature lumineuse propres.",
    "original": "Création nouvelle : la référence ne sert que de base de gabarit et de proportions.",
}
_ADJUSTMENTS = {  # ajustements géométriques proposés par niveau (amplitudes relatives)
    "light": [("hood_length", 0.03)],
    "balanced": [("hood_length", 0.06), ("roof_height", -0.04)],
    "original": [("hood_length", 0.09), ("roof_height", -0.07), ("track_width", 0.04)],
}
ADJUSTMENT_LABELS = {
    "hood_length": "Longueur du capot",
    "roof_height": "Hauteur du toit",
    "track_width": "Largeur des voies",
    "ride_height": "Garde au sol",
}


def _seed(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12], 16)


def is_forbidden(name: str) -> bool:
    words = {w.strip(".-'&").lower() for w in name.replace("-", " ").split()}
    return bool(words & (REAL_BRANDS | GTA_BRANDS))


def brand_names(seed: str, count: int = 6) -> list[str]:
    """Marques fictives originales (déterministes pour une graine)."""
    rng = random.Random(_seed("brand", seed))
    names: list[str] = []
    attempts = 0
    while len(names) < count and attempts < 500:
        attempts += 1
        name = rng.choice(_ONSETS) + rng.choice(_CODAS)
        if rng.random() < 0.25:
            name += rng.choice([" Motors", " Automotive", " & Fils"])
        if name not in names and not is_forbidden(name):
            names.append(name)
    return names


def model_names(vehicle_type: str, seed: str, count: int = 6) -> list[str]:
    rng = random.Random(_seed("model", vehicle_type, seed))
    pool = list(_MODEL_WORDS.get(vehicle_type, _MODEL_WORDS["sedan"]))
    rng.shuffle(pool)
    return [n for n in pool if not is_forbidden(n)][:count]


def proposals(report: dict | None, seed: str) -> list[dict]:
    """Trois directions (légère, équilibrée, originale) fondées sur l'analyse."""
    vehicle_type = vision.value(report, "type", "sedan") or "sedan"
    brands = brand_names(seed, 6)
    models = model_names(vehicle_type, seed, 6)
    rng = random.Random(_seed("proposals", seed))
    profile = vision.value(report, "roof_profile", {}) or {}
    color = vision.value(report, "body_color", None)
    result = []
    for index, level in enumerate(LEVELS):
        details = [rng.choice(_BODY[level])]
        if profile.get("flat_roof", 0) > 0.5:
            details.append(
                "toit plat conservé (gabarit utilitaire) : se distinguer par les montants et galeries"
            )
        if color:
            details.append(f"teinte d'origine {color} conservable ; la livrée se crée dans Livery Studio")
        details.append("logos et inscriptions réels retirés et remplacés par des éléments originaux")
        result.append(
            {
                "level": level,
                "label": LEVELS[level],
                "brand": brands[index % len(brands)],
                "model_name": models[index % len(models)] if models else "Modèle",
                "grille": rng.choice(_GRILLES[level]),
                "lights": rng.choice(_LIGHTS[level]),
                "body": rng.choice(_BODY[level]),
                "details": details,
                "direction": _DIRECTIONS[level],
                "adjustments": [{"kind": k, "amount": a} for k, a in _ADJUSTMENTS[level]],
                "source": "local (règles et générateur de noms)",
            }
        )
    return result


def merge_cloud(local: list[dict], cloud: dict) -> list[dict]:
    """Ajoute les propositions d'un fournisseur cloud, filtrées et identifiées comme telles."""
    merged = list(local)
    items = cloud.get("proposals", []) if isinstance(cloud, dict) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        brand = str(item.get("brand", "")).strip()
        model = str(item.get("model_name", "")).strip()
        if not brand or is_forbidden(brand) or is_forbidden(model):
            continue
        level = item.get("level") if item.get("level") in LEVELS else "balanced"
        merged.append(
            {
                "level": level,
                "label": LEVELS[level] + " (cloud)",
                "brand": brand,
                "model_name": model,
                "grille": str(item.get("grille", "")),
                "lights": str(item.get("lights", "")),
                "body": str(item.get("body", "")),
                "details": [str(d) for d in item.get("details", []) if isinstance(d, str)][:8],
                "direction": str(item.get("direction", "")),
                "adjustments": [{"kind": k, "amount": a} for k, a in _ADJUSTMENTS[level]],
                "source": "cloud",
            }
        )
    return merged


# --- Ajustements géométriques ------------------------------------------------------------------


def _smooth01(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def deform(mesh: MeshData, kind: str, amount: float, axes=(0, 1, 2), forward_sign: int = -1) -> EditResult:  # type: ignore[no-untyped-def]
    """Déformation lisse dans le repère du véhicule (axes latéral, vertical, longitudinal).

    - ``hood_length`` : étire l'avant (environ le tiers avant) le long de l'axe longitudinal ;
    - ``roof_height`` : abaisse / relève la partie haute (au-dessus de la ceinture) ;
    - ``track_width`` : élargit le bas de caisse (voies) ;
    - ``ride_height`` : remonte / abaisse la caisse au-dessus du sol.
    """
    if kind not in ADJUSTMENT_LABELS:
        raise EditError(f"Ajustement inconnu : {kind}")
    if abs(amount) > 0.3:
        raise EditError("Amplitude limitée à ±30 %.")
    lateral, up, longitudinal = axes
    p = mesh.positions.astype(np.float64).copy()
    lo, hi = p.min(axis=0), p.max(axis=0)
    size = np.maximum(hi - lo, 1e-6)
    t_long = (p[:, longitudinal] - lo[longitudinal]) / size[longitudinal]
    front = 1 - t_long if forward_sign < 0 else t_long  # 1 à l'avant
    t_up = (p[:, up] - lo[up]) / size[up]
    if kind == "hood_length":
        weight = _smooth01((front - 0.6) / 0.25)
        p[:, longitudinal] += forward_sign * weight * amount * size[longitudinal]
    elif kind == "roof_height":
        weight = _smooth01((t_up - 0.55) / 0.3)
        p[:, up] += weight * amount * size[up]
    elif kind == "track_width":
        weight = _smooth01((0.5 - t_up) / 0.3)
        center = (lo[lateral] + hi[lateral]) / 2
        p[:, lateral] = center + (p[:, lateral] - center) * (1 + weight * amount)
    else:  # ride_height
        p[:, up] += _smooth01((t_up - 0.05) / 0.15) * amount * size[up]
    new = MeshData(
        mesh.name,
        p.astype(np.float32),
        mesh.indices,
        compute_vertex_normals(p, mesh.indices),
        mesh.colors,
        mesh.color,
        mesh.uvs,
    )
    sign = "+" if amount >= 0 else "−"
    return EditResult(new, FACE, set(), [f"{ADJUSTMENT_LABELS[kind]} : {sign}{abs(amount):.0%}."])


def provenance(references: list[dict], generations: list[dict], selected: dict | None) -> dict:
    """Registre de provenance et de licences (références, moteurs, choix Lore Friendly)."""
    return {
        "references": [
            {
                "name": r.get("name"),
                "view": r.get("view"),
                "sha": r.get("blob"),
                "source": r.get("source") or "non renseignée",
                "author": r.get("author") or "non renseigné",
                "license": r.get("license") or "non renseignée",
                "real_logos_marked": sum(1 for n in r.get("annotations", []) if n.get("kind") == "logo"),
            }
            for r in references
        ],
        "generations": [
            {
                "id": g.get("id"),
                "engine": g.get("engine_name"),
                "method": g.get("method"),
                "kind": g.get("kind"),
                "license": g.get("engine_license"),
                "date": g.get("created_at"),
            }
            for g in generations
            if g.get("status") == "succeeded"
        ],
        "lore": selected,
        "missing_licenses": [r.get("name") for r in references if not r.get("license")],
        "disclaimer": DISCLAIMER,
    }
