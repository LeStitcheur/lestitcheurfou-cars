"""Lore Concept Generator : propositions de design fondées sur la marque, le Design DNA et le niveau.

Une proposition est un **plan** : une liste d'opérations du catalogue (``operations.py``) avec
leurs paramètres et leur justification. Le moteur local (« règles Design DNA ») est déterministe
pour une graine donnée ; un moteur cloud (capacité ``design_plan``) peut proposer des plans,
qui sont validés contre le catalogue (opérations inconnues rejetées, paramètres bornés).
L'aperçu d'une proposition est un rendu de la géométrie transformée, jamais une image
présentée comme un modèle 3D.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass

from lsfcars.ai import lore as ai_lore
from lsfcars.lorefriendly import dna as dna_mod
from lsfcars.lorefriendly import operations as ops
from lsfcars.lorefriendly.geometry import IncompatibleTransformation, VehicleState

LEVELS = {"light": "Léger", "balanced": "Équilibré", "original": "Original"}
LEVEL_DESCRIPTIONS = {
    "light": "Ajustements limités, structure conservée, modifications visuelles ciblées.",
    "balanced": "Nouvelle identité avant / arrière, plusieurs panneaux modifiés, signature distincte.",
    "original": "Refonte stylistique importante, modifications structurelles, contraintes techniques "
    "respectées.",
}
LEVEL_SCALE = {"light": 0.45, "balanced": 0.75, "original": 1.0}
LEVEL_COUNT = {"light": (3, 4), "balanced": (6, 8), "original": (9, 12)}
CONSTRAINTS: dict[str, tuple[str, set[str]]] = {
    "keep_roof": ("Conserver la hauteur de toit", {"roof_height", "roof_slope"}),
    "keep_length": (
        "Conserver la longueur",
        {"nose_length", "tail_length", "front_bumper_depth", "rear_bumper_depth"},
    ),
    "keep_track": ("Conserver les voies et les roues", {"track", "fender_width"}),
    "keep_ride": ("Conserver la garde au sol et l'assiette", {"ride_height", "rake"}),
    "no_additions": ("Aucune pièce ajoutée", set()),
}
ADDITIONS = {k for k, op in ops.OPERATIONS.items() if op.kind in ("add", "replace")}
LOCAL_ENGINE = "lsf-dna-rules"
LOCAL_ENGINE_LABEL = "Règles Design DNA (local, déterministe)"
QUICK_PRESETS: dict[str, tuple[str, str, list[dict]]] = {
    "front_identity": (
        "Nouvelle identité avant",
        "Phares, calandre et signature lumineuse redessinés.",
        [
            {"op": "headlights", "params": {"style": "slim"}},
            {"op": "grille", "params": {"style": "mesh"}},
            {"op": "signature", "params": {}},
        ],
    ),
    "rear_identity": (
        "Nouvelle identité arrière",
        "Feux, bandeau lumineux et diffuseur.",
        [
            {"op": "taillights", "params": {"style": "bar"}},
            {"op": "rear_signature", "params": {}},
            {"op": "diffuser", "params": {}},
        ],
    ),
    "coupe": (
        "Silhouette coupé",
        "Pavillon abaissé, chute de toit, assiette dynamique.",
        [
            {"op": "roof_height", "params": {"amount": -0.06}},
            {"op": "roof_slope", "params": {"amount": 0.15}},
            {"op": "rake", "params": {"amount": 0.02}},
        ],
    ),
    "sport_pack": (
        "Pack sport",
        "Bouclier avancé, lame, bas de caisse, diffuseur, aileron, quatre sorties.",
        [
            {"op": "front_bumper_depth", "params": {"amount": 0.05}},
            {"op": "splitter", "params": {}},
            {"op": "side_skirts", "params": {}},
            {"op": "diffuser", "params": {}},
            {"op": "spoiler", "params": {}},
            {"op": "exhaust", "params": {"style": "quad"}},
        ],
    ),
    "offroad_pack": (
        "Pack tout-terrain",
        "Garde au sol rehaussée, extensions d'ailes, protection inférieure.",
        [
            {"op": "ride_height", "params": {"amount": 0.1}},
            {"op": "fender_flares", "params": {}},
            {"op": "protection", "params": {"style": "skid"}},
        ],
    ),
    "luxury_pack": (
        "Pack prestige",
        "Capot allongé, calandre verticale, joncs chromés, signature fine.",
        [
            {"op": "nose_length", "params": {"amount": 0.12}},
            {"op": "grille", "params": {"style": "bars_v", "height": 0.24}},
            {"op": "trim", "params": {"finish": "chrome"}},
            {"op": "signature", "params": {"style": "bar"}},
        ],
    ),
}
FRONT_IDENTITY = {"headlights", "grille", "signature"}
REAR_IDENTITY = {"taillights", "rear_signature", "diffuser", "exhaust"}
STRUCTURAL = {"roof_height", "roof_slope", "nose_length", "tail_length", "fender_width", "hood_height"}


@dataclass
class ConceptRequest:
    brand_key: str
    brand_name: str
    category: str
    dna: dict
    level: str = "balanced"
    count: int = 3
    seed: str = ""
    constraints: tuple[str, ...] = ()
    brand_dna: dict | None = None


def _seed(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12], 16)


def _choose(rng: random.Random, scores: dict[str, float], spread: int) -> str:
    ranked = sorted(scores, key=lambda k: -scores[k])
    return ranked[min(rng.randrange(max(1, spread)), len(ranked) - 1)]


def _candidates(d: dict, rng: random.Random, scale: float, spread: int) -> list[tuple[float, str, dict, str]]:
    """(score, opération, paramètres, raison) pour toutes les opérations pertinentes."""
    w = {k: dna_mod.weight(d, k) for k in dna_mod.PARAMETERS}
    sport, aero, aggressive, luxury = w["sport"], w["aero"], w["aggressive"], w["luxury"]
    retro, robust, utility, offroad, modern = w["retro"], w["robust"], w["utility"], w["offroad"], w["modern"]

    def jitter() -> float:
        return rng.uniform(0.85, 1.15)

    head = _choose(
        rng,
        {
            "slim": sport + modern + aero,
            "boomerang": aggressive + sport,
            "trapezoid": aggressive + 0.5 * robust,
            "round": 1.5 * retro + 0.5 * offroad,
            "dual_round": retro + 0.4 * sport,
            "rect": utility + w["sobriety"] + 0.5 * robust,
            "split": modern + luxury,
        },
        spread,
    )
    tail = _choose(
        rng,
        {
            "bar": modern + luxury,
            "slim": sport + aero,
            "c_shape": aggressive + 0.5 * modern,
            "round_pair": 1.5 * retro + 0.4 * sport,
            "vertical": utility + offroad,
            "rect": w["sobriety"] + 0.5 * robust,
        },
        spread,
    )
    grille = _choose(
        rng,
        {
            "mesh": sport + aggressive,
            "bars_v": 1.4 * luxury + 0.3 * retro,
            "bars_h": retro + utility + 0.5 * robust,
            "closed": modern + aero - 0.5 * aggressive,
            "split": aggressive + 0.5 * luxury,
        },
        spread,
    )
    exhaust = "quad" if sport > 0.5 else "dual" if sport > 0 or aggressive > 0.3 else "single"
    candidates = [
        (
            2.0,
            "headlights",
            {
                "style": head,
                "width": 0.3 + 0.08 * (sport + modern) * jitter(),
                "height": max(0.06, 0.12 - 0.04 * (sport + aero)),
            },
            "Nouvelle forme d'optiques avant : identité de face distincte",
        ),
        (
            1.9,
            "grille",
            {
                "style": grille,
                "width": 0.45 + 0.15 * (luxury + robust) * jitter(),
                "height": 0.14 + 0.08 * (luxury + robust),
            },
            "Calandre redessinée selon la direction choisie",
        ),
        (
            1.8,
            "taillights",
            {"style": tail, "width": 0.34 + 0.1 * (modern + luxury) * jitter(), "height": 0.1},
            "Nouvelle signature arrière",
        ),
        (
            1.0 + modern,
            "signature",
            {"style": "split" if aggressive > 0.3 else "bar", "width": 0.6 + 0.2 * modern},
            "Signature lumineuse de jour propre à la marque",
        ),
        (0.6 + modern + luxury, "rear_signature", {"width": 0.85}, "Bandeau lumineux arrière continu"),
        (
            1.2 + 0.5 * abs(sport - utility),
            "front_bumper_depth",
            {"amount": 0.06 * scale * (sport + aggressive - utility) * jitter()},
            "Bouclier avant plus ou moins avancé",
        ),
        (0.8 + aggressive + sport, "splitter", {"depth": 0.08 + 0.08 * max(sport, 0)}, "Lame avant sportive"),
        (
            0.7 + aero + sport,
            "diffuser",
            {"fins": 5 + int(3 * max(aero, 0)), "width": 0.6},
            "Diffuseur arrière",
        ),
        (
            0.6 + sport + 0.5 * aggressive,
            "exhaust",
            {"style": exhaust, "radius": 0.04 + 0.015 * max(sport, 0)},
            "Sorties d'échappement redessinées",
        ),
        (
            0.4 + 1.2 * sport + 0.5 * aggressive,
            "spoiler",
            {"height": 0.08 + 0.12 * max(aero, 0), "angle": 6 + 8 * max(aero, 0)},
            "Aileron arrière",
        ),
        (0.5 + aero + sport, "side_skirts", {"height": 0.1, "depth": 0.05}, "Bas de caisse"),
        (
            0.4 + 1.5 * offroad + 0.5 * robust,
            "fender_flares",
            {"width": 0.05 + 0.04 * max(offroad, 0)},
            "Extensions d'ailes robustes",
        ),
        (
            0.4 + offroad + robust,
            "protection",
            {"style": "push_bar" if utility > 0.3 else "skid"},
            "Protection avant",
        ),
        (
            0.3 + 1.2 * aggressive + 0.5 * retro,
            "hood_scoop",
            {"width": 0.4, "height": 0.06 + 0.03 * max(aggressive, 0)},
            "Écope de capot",
        ),
        (0.3 + aggressive, "intakes", {"width": 0.2, "height": 0.07}, "Prises d'air de bouclier"),
        (0.2 + 1.2 * aggressive, "canards", {"size": 1.0}, "Canards aérodynamiques"),
        (
            0.3 + luxury + retro,
            "trim",
            {"finish": "chrome" if luxury + retro > 0 else "plastic"},
            "Jonc latéral",
        ),
        (
            1.1 + sport + aero,
            "roof_height",
            {"amount": (-0.045 * (sport + aero) + 0.06 * max(utility, 0)) * scale * jitter()},
            "Hauteur de pavillon",
        ),
        (
            0.6 + aero + sport,
            "roof_slope",
            {"amount": 0.15 * max(aero, sport, 0) * scale * jitter()},
            "Chute de pavillon",
        ),
        (
            1.0 + abs(luxury - modern),
            "nose_length",
            {"amount": 0.15 * (luxury + 0.5 * retro - 0.5 * modern) * scale * jitter()},
            "Porte-à-faux avant (proportions)",
        ),
        (
            0.8 + abs(luxury - sport),
            "tail_length",
            {"amount": 0.12 * (luxury - 0.5 * sport) * scale * jitter()},
            "Porte-à-faux arrière",
        ),
        (
            0.9 + abs(robust - aero),
            "hood_height",
            {"amount": 0.05 * (robust + 0.5 * aggressive - aero) * scale * jitter()},
            "Hauteur de capot",
        ),
        (0.7 + aero, "front_taper", {"amount": 0.12 * max(aero, 0) * scale}, "Effilement de la face avant"),
        (0.5 + aero, "rear_taper", {"amount": 0.08 * max(aero, 0) * scale}, "Effilement de l'arrière"),
        (
            1.0 + sport + offroad + aggressive,
            "fender_width",
            {"amount": 0.06 * max(sport, offroad, aggressive, 0) * scale * jitter()},
            "Ailes élargies",
        ),
        (0.5 + sport + luxury, "shoulder", {"amount": 0.015 * (sport + luxury) * scale}, "Ligne d'épaule"),
        (
            0.6 + abs(offroad - sport),
            "ride_height",
            {"amount": (0.12 * max(offroad, 0) - 0.05 * max(sport, 0)) * scale},
            "Garde au sol",
        ),
        (0.3 + sport, "rake", {"amount": 0.03 * max(sport, 0) * scale}, "Assiette dynamique"),
        (
            0.4 + retro + sport,
            "ducktail",
            {"amount": 0.05 * max(retro, sport, 0) * scale},
            "Relevé de coffre",
        ),
        (0.5 + sport + offroad, "track", {"amount": 0.03 * max(sport, offroad, 0) * scale}, "Voies élargies"),
    ]
    return [(score * rng.uniform(0.9, 1.1), op, params, why) for score, op, params, why in candidates]


def build_plan(request: ConceptRequest, index: int, available: set[str]) -> dict:
    """Plan d'une proposition (déterministe pour une graine et un rang)."""
    rng = random.Random(
        _seed(request.seed, request.brand_key, request.level, str(index), json.dumps(request.dna))
    )
    values = (
        dna_mod.blend(request.brand_dna, request.dna, 0.65)
        if request.brand_dna
        else dna_mod.normalize(request.dna)
    )
    scale = LEVEL_SCALE.get(request.level, 0.75)
    excluded: set[str] = set()
    for key in request.constraints:
        excluded |= CONSTRAINTS.get(key, ("", set()))[1]
    if "no_additions" in request.constraints:
        excluded |= ADDITIONS
    candidates = [
        c for c in _candidates(values, rng, scale, 1 + index) if c[1] not in excluded and c[1] in available
    ]
    ranked = sorted(candidates, key=lambda c: -c[0])
    lo, hi = LEVEL_COUNT.get(request.level, (6, 8))
    target = rng.randint(lo, hi)
    chosen: list[tuple[float, str, dict, str]] = []

    def take(group: set[str], minimum: int) -> None:
        for cand in ranked:
            if sum(1 for c in chosen if c[1] in group) >= minimum:
                return
            if cand[1] in group and cand not in chosen:
                chosen.append(cand)

    take(FRONT_IDENTITY, 1 if request.level == "light" else 2)
    take(REAR_IDENTITY, 1)
    take(STRUCTURAL, {"original": 3, "balanced": 1}.get(request.level, 0))
    for cand in ranked:
        if len(chosen) >= target:
            break
        light_structural = request.level == "light" and cand[1] in STRUCTURAL - {"hood_height"}
        if cand not in chosen and not light_structural:
            chosen.append(cand)
    order = list(ops.OPERATIONS)
    chosen.sort(key=lambda c: (ops.OPERATIONS[c[1]].kind != "deform", order.index(c[1])))
    plan = [
        {"op": op, "params": ops.jsonable(ops.OPERATIONS[op].clean(params)), "why": why}
        for _, op, params, why in chosen
    ]
    names = ai_lore.model_names(request.category or "sedan", request.seed, 6)  # noms distincts par rang
    model = names[index % len(names)] if names else f"Concept {index + 1}"
    return {
        "title": f"{request.brand_name} {model}".strip(),
        "level": request.level,
        "plan": plan,
        "summary": describe(plan),
        "dna": values,
        "engine": LOCAL_ENGINE,
        "engine_label": LOCAL_ENGINE_LABEL,
        "source": "local",
    }


def describe(plan: list[dict]) -> str:
    return " · ".join(ops.OPERATIONS[s["op"]].label for s in plan if s["op"] in ops.OPERATIONS)


def generate(request: ConceptRequest, available: set[str]) -> list[dict]:
    count = max(1, min(int(request.count), 6))
    proposals: list[dict] = []
    seen: set[str] = set()
    for index in range(count * 3):
        proposal = build_plan(request, index, available)
        signature = json.dumps([[s["op"], s["params"]] for s in proposal["plan"]], sort_keys=True)
        if signature in seen:
            continue
        seen.add(signature)
        proposals.append(proposal)
        if len(proposals) == count:
            break
    return proposals


def catalogue_json() -> str:
    """Catalogue transmis au moteur cloud (clés, paramètres et bornes uniquement)."""
    data = []
    for op in ops.OPERATIONS.values():
        params: dict[str, object] = {}
        for p in op.params:
            if p.kind == "choice":
                params[p.key] = [c for c, _ in p.choices]
            elif p.kind in ("float", "int"):
                params[p.key] = [p.minimum, p.maximum]
            elif p.kind == "color":
                params[p.key] = "rgb 0-1"
        data.append({"op": op.key, "label": op.label, "params": params})
    return json.dumps(data, ensure_ascii=False)


def from_cloud(
    data: dict, request: ConceptRequest, engine_id: str, engine_name: str
) -> tuple[list[dict], list[str]]:
    """Plans proposés par un moteur cloud, validés contre le catalogue (rien d'autre n'est accepté)."""
    proposals: list[dict] = []
    rejected: list[str] = []
    for item in (data or {}).get("proposals", [])[:6]:
        if not isinstance(item, dict):
            continue
        plan = []
        for step in item.get("plan", []):
            op = step.get("op") if isinstance(step, dict) else None
            if op not in ops.OPERATIONS:
                rejected.append(str(op if op is not None else step))
                continue
            raw = step.get("params") if isinstance(step.get("params"), dict) else {}
            try:
                params = ops.jsonable(ops.OPERATIONS[op].clean(raw))
            except (TypeError, ValueError):
                rejected.append(str(op))
                continue
            plan.append({"op": op, "params": params, "why": str(step.get("why", ""))[:200]})
        if not plan:
            continue
        title = str(item.get("title", "")).strip()[:60]
        words = {w.strip(".-'&").lower() for w in title.replace("-", " ").split()}
        if (
            not title or words & ai_lore.REAL_BRANDS
        ):  # jamais de marque réelle ; la marque choisie reste admise
            title = f"{request.brand_name} — proposition {len(proposals) + 1}".strip()
        proposals.append(
            {
                "title": title,
                "level": request.level,
                "plan": plan,
                "summary": str(item.get("summary", ""))[:300] or describe(plan),
                "dna": dna_mod.normalize(request.dna),
                "engine": engine_id,
                "engine_label": engine_name,
                "source": "cloud",
            }
        )
    return proposals, rejected


def apply_plan(state: VehicleState, plan: list[dict]) -> tuple[list[str], list[str]]:
    """Applique un plan à un état de travail : (messages, opérations incompatibles ignorées)."""
    messages: list[str] = []
    skipped: list[str] = []
    for step in plan:
        spec = ops.OPERATIONS.get(step.get("op", ""))
        label = spec.label if spec else str(step.get("op"))
        try:
            messages += ops.apply(state, step["op"], step.get("params"))
        except IncompatibleTransformation as exc:
            skipped.append(f"{label} : {exc}")
    return messages, skipped
