"""Catalogue des transformations Lore Friendly (Front, Rear, Body Silhouette, identité lumineuse).

Chaque opération agit sur un ``VehicleState`` : déformation lisse du maillage, pièce
paramétrique ajoutée (ou remplaçant une pièce identifiée, masquée et non supprimée),
déplacement des roues, matériau. Aucune opération n'est un simple changement de texture.
Les impacts possibles (UV, collisions, LOD, os) sont déclarés pour chaque opération et
vérifiés sur le véhicule avant application (``impacts``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from lsfcars.lorefriendly import parts
from lsfcars.lorefriendly.geometry import (
    DEFORMATIONS,
    IncompatibleTransformation,
    VehicleState,
    new_part,
    part_world,
    surface_u,
)
from lsfcars.scene import shapes

STUDIOS = {
    "front": "Front Design Studio",
    "rear": "Rear Design Studio",
    "body": "Body Silhouette Studio",
    "lights": "Identité lumineuse",
}
IMPACT_LABELS = {
    "uv": "UV étirées par la déformation (texture à vérifier)",
    "collision": "Collisions non mises à jour (à régénérer pour FiveM)",
    "lod": "LOD non mis à jour (à régénérer)",
    "bones": "Pièces mobiles / os : pivots conservés, géométrie à vérifier autour des charnières",
    "new_uv": "Nouvelle pièce : UV paramétriques à intégrer à la livrée",
    "materials": "Nouveau matériau propre à la variante (le matériau source n'est pas modifié)",
}
MATERIALS = {
    "plastic": {
        "name": "Plastique Lore",
        "base_color": (0.07, 0.07, 0.08, 1.0),
        "roughness": 0.6,
        "metallic": 0.0,
    },
    "chrome": {
        "name": "Chrome Lore",
        "base_color": (0.86, 0.87, 0.9, 1.0),
        "roughness": 0.12,
        "metallic": 1.0,
    },
    "metal": {
        "name": "Métal Lore",
        "base_color": (0.45, 0.46, 0.48, 1.0),
        "roughness": 0.35,
        "metallic": 0.9,
    },
    "lens": {
        "name": "Optique Lore",
        "base_color": (0.86, 0.88, 0.92, 1.0),
        "roughness": 0.08,
        "metallic": 0.0,
        "emissive": (1.0, 0.97, 0.9),
        "emissive_strength": 0.9,
    },
    "tail": {
        "name": "Feu Lore",
        "base_color": (0.55, 0.05, 0.07, 1.0),
        "roughness": 0.1,
        "metallic": 0.0,
        "emissive": (1.0, 0.12, 0.08),
        "emissive_strength": 0.7,
    },
    "signature": {
        "name": "Signature Lore",
        "base_color": (0.9, 0.93, 1.0, 1.0),
        "roughness": 0.08,
        "metallic": 0.0,
        "emissive": (0.85, 0.92, 1.0),
        "emissive_strength": 1.4,
    },
}


@dataclass(frozen=True)
class Param:
    key: str
    label: str
    kind: str = "float"  # float / int / choice / bool / color
    default: object = 0.0
    minimum: float = 0.0
    maximum: float = 1.0
    step: float = 0.01
    unit: str = ""
    choices: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class OperationSpec:
    key: str
    studio: str
    label: str
    description: str
    kind: str  # deform / add / replace / wheels / material
    params: tuple[Param, ...] = ()
    impacts: frozenset[str] = field(default_factory=frozenset)
    components: tuple[str, ...] = ()  # composants remplacés ou modifiés

    def defaults(self) -> dict:
        return {p.key: p.default for p in self.params}

    def clean(self, params: dict | None) -> dict:
        values = self.defaults()
        for p in self.params:
            if params is None or p.key not in params:
                continue
            value = params[p.key]
            if p.kind == "float":
                values[p.key] = float(np.clip(float(value), p.minimum, p.maximum))  # type: ignore[arg-type]
            elif p.kind == "int":
                values[p.key] = int(np.clip(int(value), p.minimum, p.maximum))  # type: ignore[call-overload]
            elif p.kind == "choice":
                values[p.key] = value if value in dict(p.choices) else p.default
            elif p.kind == "bool":
                values[p.key] = bool(value)
            elif p.kind == "color":
                values[p.key] = tuple(float(np.clip(c, 0, 1)) for c in list(value)[:3])  # type: ignore[call-overload]
        return values


def _amount(key: str) -> Param:
    d = DEFORMATIONS[key]
    return Param(
        "amount", d.label, "float", d.default, d.minimum, d.maximum, 0.005, "m" if d.unit == "m" else ""
    )


def _deform(key: str, studio: str, impacts=("uv", "collision", "lod")) -> OperationSpec:  # type: ignore[no-untyped-def]
    d = DEFORMATIONS[key]
    extra = {"bones"} if key in ("hood_height", "ducktail", "nose_length", "tail_length") else set()
    return OperationSpec(
        key, studio, d.label, d.description, "deform", (_amount(key),), frozenset({*impacts, *extra})
    )


def _choices(table: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(table.items())


ADD_IMPACTS = frozenset({"new_uv", "collision", "lod"})
OPERATIONS: dict[str, OperationSpec] = {
    op.key: op
    for op in (
        # --- Front Design Studio ------------------------------------------------------
        OperationSpec(
            "grille",
            "front",
            "Calandre",
            "Nouvelle calandre (forme et style) ; l'ancienne est masquée.",
            "replace",
            (
                Param("style", "Style", "choice", "mesh", choices=_choices(parts.GRILLE_STYLES)),
                Param("width", "Largeur (part de la largeur)", "float", 0.5, 0.2, 0.9, 0.01),
                Param("height", "Hauteur", "float", 0.16, 0.06, 0.45, 0.01, "m"),
            ),
            ADD_IMPACTS,
            ("grille",),
        ),
        OperationSpec(
            "headlights",
            "front",
            "Phares",
            "Nouvelle forme d'optiques avant (paire symétrique).",
            "replace",
            (
                Param("style", "Forme", "choice", "slim", choices=_choices(parts.HEADLIGHT_STYLES)),
                Param("width", "Largeur", "float", 0.34, 0.12, 0.7, 0.01, "m"),
                Param("height", "Hauteur", "float", 0.1, 0.03, 0.3, 0.005, "m"),
            ),
            ADD_IMPACTS | {"materials"},
            ("headlight",),
        ),
        OperationSpec(
            "front_bumper",
            "front",
            "Pare-chocs avant",
            "Nouveau bouclier avant paramétrique.",
            "replace",
            (
                Param("height", "Hauteur", "float", 0.3, 0.12, 0.6, 0.01, "m"),
                Param("depth", "Avancée", "float", 0.12, 0.04, 0.35, 0.01, "m"),
                Param("curve", "Galbe", "float", 0.1, 0.0, 0.3, 0.01, "m"),
            ),
            ADD_IMPACTS,
            ("front_bumper",),
        ),
        OperationSpec(
            "intakes",
            "front",
            "Prises d'air de bouclier",
            "Deux prises d'air latérales maillées.",
            "add",
            (
                Param("width", "Largeur", "float", 0.22, 0.08, 0.45, 0.01, "m"),
                Param("height", "Hauteur", "float", 0.08, 0.03, 0.2, 0.005, "m"),
            ),
            ADD_IMPACTS,
        ),
        OperationSpec(
            "hood_scoop",
            "front",
            "Écope de capot",
            "Prise d'air posée sur le capot.",
            "add",
            (
                Param("width", "Largeur", "float", 0.45, 0.2, 0.9, 0.01, "m"),
                Param("height", "Hauteur", "float", 0.07, 0.03, 0.16, 0.005, "m"),
            ),
            ADD_IMPACTS,
        ),
        OperationSpec(
            "splitter",
            "front",
            "Lame avant",
            "Lame basse sous le bouclier avant.",
            "add",
            (Param("depth", "Avancée", "float", 0.12, 0.04, 0.3, 0.01, "m"),),
            ADD_IMPACTS,
        ),
        OperationSpec(
            "protection",
            "front",
            "Protection avant",
            "Pare-buffle ou plaque de protection inférieure.",
            "add",
            (
                Param(
                    "style",
                    "Type",
                    "choice",
                    "skid",
                    choices=(("skid", "Plaque inférieure"), ("push_bar", "Pare-buffle")),
                ),
            ),
            ADD_IMPACTS,
        ),
        OperationSpec(
            "canards",
            "front",
            "Canards",
            "Appendices aérodynamiques aux angles du bouclier.",
            "add",
            (Param("size", "Taille", "float", 1.0, 0.6, 1.8, 0.05),),
            ADD_IMPACTS,
        ),
        _deform("front_bumper_depth", "front"),
        _deform("nose_length", "front"),
        _deform("hood_height", "front"),
        _deform("front_taper", "front"),
        # --- Rear Design Studio -------------------------------------------------------
        OperationSpec(
            "taillights",
            "rear",
            "Feux arrière",
            "Nouvelle forme de feux arrière (paire symétrique).",
            "replace",
            (
                Param("style", "Forme", "choice", "bar", choices=_choices(parts.TAILLIGHT_STYLES)),
                Param("width", "Largeur", "float", 0.38, 0.12, 0.8, 0.01, "m"),
                Param("height", "Hauteur", "float", 0.1, 0.03, 0.3, 0.005, "m"),
            ),
            ADD_IMPACTS | {"materials"},
            ("taillight",),
        ),
        OperationSpec(
            "rear_bumper",
            "rear",
            "Pare-chocs arrière",
            "Nouveau bouclier arrière paramétrique.",
            "replace",
            (
                Param("height", "Hauteur", "float", 0.28, 0.12, 0.6, 0.01, "m"),
                Param("depth", "Saillie", "float", 0.1, 0.04, 0.3, 0.01, "m"),
            ),
            ADD_IMPACTS,
            ("rear_bumper",),
        ),
        OperationSpec(
            "diffuser",
            "rear",
            "Diffuseur",
            "Diffuseur à ailettes sous le bouclier arrière.",
            "add",
            (
                Param("fins", "Ailettes", "int", 5, 2, 9, 1),
                Param("width", "Largeur (part)", "float", 0.6, 0.3, 0.9, 0.01),
            ),
            ADD_IMPACTS,
        ),
        OperationSpec(
            "exhaust",
            "rear",
            "Sorties d'échappement",
            "Sorties d'échappement (configuration au choix).",
            "replace",
            (
                Param("style", "Configuration", "choice", "dual", choices=_choices(parts.EXHAUST_STYLES)),
                Param("radius", "Rayon", "float", 0.045, 0.025, 0.08, 0.005, "m"),
            ),
            ADD_IMPACTS,
            ("exhaust",),
        ),
        OperationSpec(
            "spoiler",
            "rear",
            "Aileron / becquet",
            "Aileron posé sur le coffre ou le hayon.",
            "replace",
            (
                Param("height", "Hauteur des supports", "float", 0.12, 0.0, 0.4, 0.01, "m"),
                Param("angle", "Incidence", "float", 8.0, 0.0, 20.0, 0.5, "°"),
                Param("width", "Largeur (part)", "float", 0.8, 0.4, 1.0, 0.01),
            ),
            ADD_IMPACTS,
            ("spoiler",),
        ),
        _deform("rear_bumper_depth", "rear"),
        _deform("tail_length", "rear"),
        _deform("ducktail", "rear"),
        _deform("rear_taper", "rear"),
        # --- Body Silhouette Studio -------------------------------------------------------
        _deform("roof_height", "body"),
        _deform("roof_slope", "body"),
        _deform("fender_width", "body"),
        _deform("shoulder", "body"),
        _deform("ride_height", "body", ("collision", "lod", "bones")),
        _deform("rake", "body", ("collision", "lod", "bones")),
        OperationSpec(
            "track",
            "body",
            "Voies (roues et ailes)",
            "Écarte les roues et élargit les ailes d'autant.",
            "wheels",
            (Param("amount", "Écart par côté", "float", 0.03, -0.03, 0.08, 0.005, "m"),),
            frozenset({"uv", "collision", "lod", "bones"}),
            ("wheel",),
        ),
        OperationSpec(
            "side_skirts",
            "body",
            "Bas de caisse",
            "Bas de caisse entre les passages de roues.",
            "add",
            (
                Param("height", "Hauteur", "float", 0.12, 0.05, 0.25, 0.01, "m"),
                Param("depth", "Saillie", "float", 0.06, 0.02, 0.15, 0.005, "m"),
            ),
            ADD_IMPACTS,
        ),
        OperationSpec(
            "fender_flares",
            "body",
            "Extensions d'ailes",
            "Élargisseurs autour de chaque passage de roue.",
            "add",
            (Param("width", "Largeur", "float", 0.06, 0.03, 0.15, 0.005, "m"),),
            ADD_IMPACTS,
        ),
        OperationSpec(
            "trim",
            "body",
            "Jonc latéral",
            "Jonc décoratif à hauteur de ceinture.",
            "add",
            (
                Param(
                    "finish",
                    "Finition",
                    "choice",
                    "chrome",
                    choices=(("chrome", "Chrome"), ("plastic", "Noir mat")),
                ),
            ),
            ADD_IMPACTS,
        ),
        # --- Identité lumineuse -------------------------------------------------------------
        OperationSpec(
            "signature",
            "lights",
            "Signature lumineuse avant",
            "Bande lumineuse de jour (DRL), matériau émissif (prévisualisation).",
            "add",
            (
                Param("style", "Forme", "choice", "bar", choices=_choices(parts.SIGNATURE_STYLES)),
                Param("width", "Largeur (part)", "float", 0.7, 0.3, 0.95, 0.01),
                Param("color", "Couleur", "color", (0.85, 0.92, 1.0)),
            ),
            ADD_IMPACTS | {"materials"},
        ),
        OperationSpec(
            "rear_signature",
            "lights",
            "Signature lumineuse arrière",
            "Bandeau lumineux arrière continu.",
            "add",
            (
                Param("width", "Largeur (part)", "float", 0.8, 0.3, 0.95, 0.01),
                Param("color", "Couleur", "color", (1.0, 0.12, 0.08)),
            ),
            ADD_IMPACTS | {"materials"},
        ),
        OperationSpec(
            "light_colors",
            "lights",
            "Couleurs des optiques",
            "Couleurs émises des phares, feux et "
            "signatures (prévisualisation viewport, pas un éclairage GTA V).",
            "material",
            (
                Param("front", "Avant", "color", (1.0, 0.97, 0.9)),
                Param("rear", "Arrière", "color", (1.0, 0.12, 0.08)),
                Param("strength", "Intensité", "float", 1.0, 0.0, 3.0, 0.05),
            ),
            frozenset({"materials"}),
            ("headlight", "taillight", "signature"),
        ),
    )
}


def by_studio(studio: str) -> list[OperationSpec]:
    return [op for op in OPERATIONS.values() if op.studio == studio]


# --- Repères de pose ---------------------------------------------------------------------


def _front_u(state: VehicleState, v_range, w_range, front: bool = True) -> float:  # type: ignore[no-untyped-def]
    points = state.body_points()
    u = surface_u(points, state.frame, v_range, w_range, front)
    if u is None:
        u = surface_u(points, state.frame, (0.0, 1.0), (-1.0, 1.0), front)
    if u is None:
        return 1.0 if front else 0.0
    return u


def _band_v(state: VehicleState, u_range, w_range, lowest: bool) -> float | None:  # type: ignore[no-untyped-def]
    """Hauteur normalisée (v) la plus basse ou la plus haute de la carrosserie dans une bande (u, w)."""
    points = state.body_points()
    if not len(points):
        return None
    u, v, w = state.frame.coords(points)
    mask = (u >= u_range[0]) & (u <= u_range[1]) & (w >= w_range[0]) & (w <= w_range[1])
    if not mask.any():
        return None
    return float(v[mask].min() if lowest else v[mask].max())


def _bottom(state: VehicleState, front: bool, default: float = 0.12) -> float:
    """Dessous de la carrosserie à l'avant ou à l'arrière (pose des lames, diffuseurs, échappements)."""
    value = _band_v(state, (0.86, 1.0) if front else (0.0, 0.14), (-0.7, 0.7), lowest=True)
    return default if value is None else value


def _face_top(state: VehicleState, front: bool, default: float) -> float:
    """Haut de la face avant (ou arrière) : les pièces de face ne flottent jamais au-dessus."""
    value = _band_v(state, (0.93, 1.0) if front else (0.0, 0.07), (-0.8, 0.8), lowest=False)
    return default if value is None else value


def _material(key: str, **overrides) -> dict:  # type: ignore[no-untyped-def]
    return {**MATERIALS[key], **overrides}


def _body_color(state: VehicleState) -> tuple:
    body = [e for e in state.body_entries() if e.kind == "body"] or state.body_entries()
    return tuple(body[0].color) if body else (0.72, 0.74, 0.78, 1.0)


def _existing(state: VehicleState, kind: str) -> list[tuple[np.ndarray, str]]:
    """Centres monde des pièces existantes d'un type (les nouvelles sont posées au même endroit)."""
    result = []
    for owner in state.owners_of(kind):
        bounds = state.owner_bounds(owner)
        if bounds is not None:
            result.append(((bounds[0] + bounds[1]) / 2, owner))
    for part in state.new_parts:  # pièce déjà ajoutée par une opération précédente du même plan
        if part.kind == kind and part.node_id not in state.hidden:
            result.append((part.world[:3, 3].copy(), part.node_id))
    return result


def _hide(state: VehicleState, owners: list[str]) -> None:
    state.new_parts = [p for p in state.new_parts if p.node_id not in owners]
    state.hide([o for o in owners if o in {e.owner_id for e in state.entries.values()}])


def _place_pair(
    state: VehicleState, kind: str, mesh, front: bool, v: float, w: float, material: dict, op: str, name: str
) -> int:  # type: ignore[no-untyped-def]
    existing = _existing(state, kind)
    frame = state.frame
    if existing:
        centers = [c for c, _ in existing]
        _hide(state, [o for _, o in existing])
    else:
        centers = []
        for side in (-1, 1):
            u = _front_u(state, (v - 0.12, v + 0.12), sorted((side * (w - 0.2), side * (w + 0.2))), front)
            centers.append(frame.point(u, v, side * w))
    replaced = [o for _, o in existing]
    for center in centers:
        _, _, cw = frame.coords(center[None])
        world = part_world(frame, center, mirror=bool(cw[0] < 0), yaw180=not front)
        state.add_part(new_part(name, kind, mesh, world, dict(material), op, replaced))
    return len(centers)


# --- Application -------------------------------------------------------------------------


def apply(state: VehicleState, key: str, params: dict | None = None) -> list[str]:
    """Applique une opération du catalogue à l'état ; retourne les messages (effets réels)."""
    spec = OPERATIONS.get(key)
    if spec is None:
        raise IncompatibleTransformation(f"Opération inconnue : {key}")
    values = spec.clean(params)
    if spec.kind == "deform":
        messages = state.deform(key, values["amount"])
    elif key == "track":
        messages = state.move_wheels(values["amount"])
        messages += state.deform("fender_width", float(np.clip(values["amount"], -0.03, 0.12)))
    elif key == "light_colors":
        messages = _light_colors(state, values)
    else:
        messages = _add(state, key, values)
    state.log.append({"op": key, "params": jsonable(values), "messages": messages})
    return messages


def _light_colors(state: VehicleState, values: dict) -> list[str]:
    strength = values["strength"]
    count = 0
    for kind, color, base in (
        ("headlight", values["front"], "lens"),
        ("signature", values["front"], "signature"),
        ("taillight", values["rear"], "tail"),
    ):
        for owner in state.owners_of(kind):
            state.set_material(owner, _material(base, emissive=color, emissive_strength=strength))
            count += 1
        for part in state.new_parts:
            if part.kind == kind:
                part.material = {**part.material, "emissive": color, "emissive_strength": strength}
                count += 1
    if not count:
        raise IncompatibleTransformation(
            "Aucune optique identifiée : créez d'abord des phares, feux ou une signature."
        )
    return [f"Couleurs d'optiques appliquées à {count} pièce(s) (matériaux propres à la variante)."]


def _add(state: VehicleState, key: str, values: dict) -> list[str]:  # noqa: C901, PLR0911, PLR0912, PLR0915 (aiguillage)
    frame = state.frame
    lm = state.landmarks()
    W, H = frame.width, frame.height  # noqa: N806
    hood_v = max(lm.hood_top, 0.3)
    metre = 1.0 / max(H, 1e-6)  # 1 m en coordonnée normalisée v
    front_top = _face_top(state, True, hood_v)
    rear_top = _face_top(state, False, max(lm.deck_top, 0.3))
    paint = _material("plastic", base_color=_body_color(state), name="Carrosserie Lore", roughness=0.3)
    if key == "grille":
        width = values["width"] * W
        mesh = parts.grille(values["style"], width, values["height"])
        existing = _existing(state, "grille")
        if existing:
            center = existing[0][0]
            _hide(state, [o for _, o in existing])
        else:
            v = hood_v * 0.62
            u = _front_u(state, (v - 0.08, v + 0.08), (-0.3, 0.3))
            center = frame.point(u, v, 0.0) - frame.forward * 0.02
        part = new_part(
            "Calandre Lore",
            "grille",
            mesh,
            part_world(frame, center),
            MATERIALS["plastic"],
            key,
            [o for _, o in existing],
        )
        state.add_part(part)
        return [
            f"Calandre « {parts.GRILLE_STYLES[values['style']]} » ({width:.2f} × {values['height']:.2f} m)."
        ]
    if key == "headlights":
        mesh = parts.headlight(values["style"], values["width"], values["height"])
        v = min(hood_v * 0.82, front_top - (values["height"] / 2 + 0.03) * metre)
        n = _place_pair(state, "headlight", mesh, True, v, 0.68, MATERIALS["lens"], key, "Phare Lore")
        return [f"Phares « {parts.HEADLIGHT_STYLES[values['style']]} » : {n} optique(s)."]
    if key == "taillights":
        mesh = parts.taillight(values["style"], values["width"], values["height"])
        v = min(max(lm.deck_top, 0.3) * 0.85, rear_top - (values["height"] / 2 + 0.03) * metre)
        n = _place_pair(state, "taillight", mesh, False, v, 0.7, MATERIALS["tail"], key, "Feu Lore")
        return [f"Feux arrière « {parts.TAILLIGHT_STYLES[values['style']]} » : {n} feu(x)."]
    if key in ("front_bumper", "rear_bumper"):
        front = key == "front_bumper"
        mesh = shapes.bumper(W * 0.96, values["height"], values["depth"], values.get("curve", 0.08))
        existing = _existing(state, key)
        _hide(state, [o for _, o in existing])
        v = values["height"] / 2 / max(H, 1e-6) + 0.06
        u = _front_u(state, (v - 0.05, v + 0.05), (-0.6, 0.6), front)
        world = part_world(frame, frame.point(u, v, 0.0), yaw180=not front)
        state.add_part(new_part("Pare-chocs Lore", key, mesh, world, paint, key, [o for _, o in existing]))
        return [
            f"{'Bouclier avant' if front else 'Bouclier arrière'} paramétrique ({values['height']:.2f} m)."
        ]
    if key == "intakes":
        mesh = parts.grille("mesh", values["width"], values["height"], 0.04)
        v = min(_bottom(state, True) + (values["height"] / 2 + 0.06) * metre, front_top * 0.6)
        for side in (-1, 1):
            u = _front_u(state, (v - 0.08, v + 0.08), sorted((side * 0.4, side * 0.85)))
            world = part_world(frame, frame.point(u, v, side * 0.62) - frame.forward * 0.015)
            state.add_part(new_part("Prise d'air Lore", "intake", mesh, world, MATERIALS["plastic"], key))
        return ["Deux prises d'air latérales ajoutées."]
    if key == "hood_scoop":
        u_mid = (lm.cabin_end + 1.0) / 2
        uu, vv, ww = frame.coords(state.body_points())
        band = (np.abs(uu - u_mid) < 0.05) & (np.abs(ww) < 0.3)
        v_top = float(vv[band].max()) if band.any() else hood_v
        mesh = shapes.air_intake(values["width"], 0.5, values["height"])
        state.add_part(
            new_part(
                "Écope Lore", "intake", mesh, part_world(frame, frame.point(u_mid, v_top, 0.0)), paint, key
            )
        )
        return ["Écope posée sur le capot."]
    if key == "splitter":
        v = _bottom(state, True) - 0.01 * metre
        u = _front_u(state, (v, v + 0.12), (-0.6, 0.6))
        mesh = shapes.splitter(W * 0.9, values["depth"])
        state.add_part(
            new_part(
                "Lame Lore",
                "splitter",
                mesh,
                part_world(frame, frame.point(u, v, 0.0)),
                MATERIALS["plastic"],
                key,
            )
        )
        return ["Lame avant ajoutée."]
    if key == "protection":
        if values["style"] == "push_bar":
            mesh = shapes.push_bar(W * 0.5, H * 0.4)
            u = _front_u(state, (0.2, 0.5), (-0.4, 0.4))
            world = part_world(frame, frame.point(u, 0.38, 0.0) + frame.forward * 0.08)
            name = "Pare-buffle Lore"
        else:
            mesh = parts.skid_plate(W * 0.7)
            v = _bottom(state, True) - 0.02 * metre
            u = _front_u(state, (v, v + 0.15), (-0.5, 0.5))
            world = part_world(frame, frame.point(u, v, 0.0) - frame.forward * 0.12)
            name = "Protection Lore"
        state.add_part(new_part(name, "protection", mesh, world, MATERIALS["metal"], key))
        return [f"{name.replace(' Lore', '')} : pièce ajoutée."]
    if key == "canards":
        mesh = shapes.canard(0.18 * values["size"], 0.06 * values["size"])
        for side in (-1, 1):
            v = min(_bottom(state, True) + 0.1 * metre, front_top * 0.6)
            u = _front_u(state, (v - 0.1, v + 0.1), sorted((side * 0.7, side * 1.0)))
            world = part_world(frame, frame.point(u, v, side * 0.9), mirror=side < 0)
            state.add_part(new_part("Canard Lore", "splitter", mesh, world, MATERIALS["plastic"], key))
        return ["Deux canards ajoutés."]
    if key == "diffuser":
        mesh = shapes.diffuser(W * values["width"], 0.35, values["fins"])
        v = _bottom(state, False)
        u = _front_u(state, (v, v + 0.15), (-0.5, 0.5), front=False)
        world = part_world(frame, frame.point(u, v, 0.0) + frame.forward * 0.16, yaw180=True)
        state.add_part(new_part("Diffuseur Lore", "diffuser", mesh, world, MATERIALS["plastic"], key))
        return [f"Diffuseur à {values['fins']} ailettes ajouté."]
    if key == "exhaust":
        existing = _existing(state, "exhaust")
        _hide(state, [o for _, o in existing])
        mesh = parts.exhaust_tip(values["radius"])
        offsets = parts.exhaust_offsets(values["style"], W / 2)
        v = _bottom(state, False) + (values["radius"] + 0.02) * metre
        for lateral in offsets:
            w = lateral / max(W / 2, 1e-6)
            u = _front_u(state, (v - 0.12, v + 0.12), sorted((w - 0.15, w + 0.15)), front=False)
            world = part_world(frame, frame.point(u, v, w) - frame.forward * 0.03, yaw180=True)
            state.add_part(
                new_part(
                    "Échappement Lore",
                    "exhaust",
                    mesh,
                    world,
                    MATERIALS["chrome"],
                    key,
                    [o for _, o in existing],
                )
            )
        return [f"{len(offsets)} sortie(s) d'échappement « {parts.EXHAUST_STYLES[values['style']]} »."]
    if key == "spoiler":
        existing = _existing(state, "spoiler")
        _hide(state, [o for _, o in existing])
        u = max(lm.rear_axle - lm.wheel_radius * 1.2, 0.04)
        uu, vv, ww = frame.coords(state.body_points())
        band = (np.abs(uu - u) < 0.04) & (np.abs(ww) < 0.5)
        v_top = float(vv[band].max()) if band.any() else lm.deck_top
        mesh = shapes.spoiler(W * values["width"], 0.26, max(values["height"], 0.005), values["angle"])
        world = part_world(frame, frame.point(u, v_top, 0.0))
        state.add_part(new_part("Aileron Lore", "spoiler", mesh, world, paint, key, [o for _, o in existing]))
        return ["Aileron posé sur le coffre."]
    if key == "side_skirts":
        if lm.measured_wheels:
            length = (lm.front_axle - lm.rear_axle - 2.2 * lm.wheel_radius) * frame.length
            center_u = (lm.front_axle + lm.rear_axle) / 2
        else:
            length, center_u = 0.45 * frame.length, 0.5
        if length <= 0.2:
            raise IncompatibleTransformation(
                "Bas de caisse : espace insuffisant entre les passages de roues."
            )
        mesh = shapes.side_skirt(length, values["height"], values["depth"])
        half = length / 2 / max(frame.length, 1e-6)
        sill = _band_v(state, (center_u - half, center_u + half), (-1.0, -0.55), lowest=True)
        sill = sill if sill is not None else 0.2
        v = sill - values["height"] * 0.55 * metre  # le bas de caisse recouvre le bas de la carrosserie
        for side in (-1, 1):
            world = part_world(frame, frame.point(center_u, v, side * 0.97), mirror=side < 0)
            state.add_part(new_part("Bas de caisse Lore", "skirt", mesh, world, paint, key))
        return [f"Bas de caisse ({length:.2f} m) ajoutés des deux côtés."]
    if key == "fender_flares":
        wheels = state.components.wheels
        if not wheels:
            raise IncompatibleTransformation("Extensions d'ailes : aucune roue identifiée.")
        sa = frame.axes.lateral_axis
        for group in wheels:
            sign = 1.0 if group.side == "droite" else -1.0
            center = group.center + state.owner_move(group.node_ids[0])
            center[sa] = frame.center[sa] + sign * frame.axes.right_sign * (
                frame.width / 2 - values["width"] * 0.6
            )
            mesh = shapes.fender_flare(group.radius * 1.12, values["width"])
            world = part_world(frame, center, mirror=sign < 0)
            state.add_part(
                new_part("Extension d'aile Lore", "fender", mesh, world, MATERIALS["plastic"], key)
            )
        return [f"{len(wheels)} extension(s) d'aile ajoutée(s)."]
    if key == "trim":
        mesh = shapes.box((0.012, 0.018, frame.length * 0.62), "Jonc")
        for side in (-1, 1):
            world = part_world(frame, frame.point(0.5, lm.beltline * 0.92, side * 1.0))
            state.add_part(new_part("Jonc Lore", "other", mesh, world, MATERIALS[values["finish"]], key))
        return ["Joncs latéraux ajoutés."]
    if key == "signature":
        width = W * values["width"]
        mesh = parts.signature(values["style"], width)
        v = min(hood_v * 0.95, front_top - 0.03 * metre)
        u = _front_u(state, (v - 0.06, v + 0.06), (-0.5, 0.5))
        world = part_world(frame, frame.point(u, v, 0.0) + frame.forward * 0.005)
        material = _material("signature", emissive=values["color"])
        state.add_part(new_part("Signature lumineuse Lore", "signature", mesh, world, material, key))
        return [f"Signature lumineuse avant « {parts.SIGNATURE_STYLES[values['style']]} » ({width:.2f} m)."]
    if key == "rear_signature":
        width = W * values["width"]
        mesh = parts.signature("bar", width, 0.022)
        v = min(max(lm.deck_top, 0.3) * 0.9, rear_top - 0.03 * metre)
        u = _front_u(state, (v - 0.06, v + 0.06), (-0.5, 0.5), front=False)
        world = part_world(frame, frame.point(u, v, 0.0) - frame.forward * 0.005, yaw180=True)
        material = _material("tail", emissive=values["color"], emissive_strength=1.0)
        state.add_part(new_part("Bandeau arrière Lore", "taillight", mesh, world, material, key))
        return [f"Bandeau lumineux arrière ({width:.2f} m)."]
    raise IncompatibleTransformation(f"Opération non prise en charge : {key}")


def impacts(state: VehicleState, key: str) -> list[str]:
    """Impacts réellement présents sur ce véhicule pour une opération (UV, collisions, LOD, os)."""
    spec = OPERATIONS[key]
    comps = state.components.components
    found = []
    for impact in sorted(spec.impacts):
        if impact == "collision" and not any(c.kind == "technical" for c in comps):
            continue
        if impact == "lod" and not any("lod" in c.name.lower() for c in comps):
            continue
        if impact == "bones" and not any(c.kind in ("hood", "trunk", "door", "wheel") for c in comps):
            continue
        if impact == "uv" and not any(e.original.uvs is not None for e in state.body_entries()):
            continue
        found.append(IMPACT_LABELS[impact])
    return found


def jsonable(values: dict) -> dict:
    return {k: list(v) if isinstance(v, tuple) else v for k, v in values.items()}
