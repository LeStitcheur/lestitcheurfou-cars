"""Vehicle Design Analyzer : analyse stylistique d'un véhicule à partir des données disponibles.

Chaque entrée du rapport porte un statut explicite :

- ``measured``   : mesure géométrique vérifiée (calculée sur les sommets du projet) ;
- ``recognized`` : reconnaissance automatique (nom des pièces, règles sur la silhouette) ;
- ``ai``         : hypothèse d'une IA (analyse cloud des références, si l'utilisateur l'a lancée) ;
- ``unknown``    : information non observable — rien n'est inventé ;
- ``user``       : valeur saisie ou corrigée par l'utilisateur.
"""

from __future__ import annotations

import numpy as np

from lsfcars.lorefriendly.components import COMPONENT_LABELS
from lsfcars.lorefriendly.geometry import VehicleState, height_profile

STATUS_LABELS = {
    "measured": "Mesure géométrique vérifiée",
    "recognized": "Reconnaissance automatique",
    "ai": "Hypothèse IA",
    "unknown": "Inconnu",
    "user": "Saisie utilisateur",
}
STATUS_SHORT = {
    "measured": "Mesure",
    "recognized": "Reconnu",
    "ai": "Hypothèse IA",
    "unknown": "Inconnu",
    "user": "Saisi",
}
SECTIONS = {
    "general": "Général",
    "proportions": "Proportions et silhouette",
    "front": "Face avant",
    "rear": "Arrière",
    "wheels": "Roues et passages",
    "details": "Éléments distinctifs",
    "materials": "Matériaux",
}


def _entry(key: str, section: str, label: str, value, status: str, source: str, note: str = "") -> dict:  # type: ignore[no-untyped-def]
    return {
        "key": key,
        "section": section,
        "label": label,
        "value": value,
        "status": status,
        "source": source,
        "note": note,
    }


def _m(value: float) -> str:
    return f"{value:.2f} m"


def mesh_volume(state: VehicleState) -> tuple[float | None, str]:
    """Volume des maillages de carrosserie fermés (théorème de la divergence) ; None si ouverts."""
    total = 0.0
    closed = 0
    for entry in state.body_entries():
        if entry.kind not in ("body", "hood", "trunk", "roof", "door"):
            continue
        indices = entry.mesh.indices.astype(np.int64)
        edges = np.sort(np.concatenate([indices[:, [0, 1]], indices[:, [1, 2]], indices[:, [2, 0]]]), axis=1)
        _, counts = np.unique(edges, axis=0, return_counts=True)
        if not len(counts) or counts.max() != 2 or counts.min() != 2:
            continue
        tri = state.world_points(entry)[indices]
        total += abs(float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum()) / 6.0)
        closed += 1
    if not closed:
        return None, "maillage de carrosserie ouvert (non fermé) : volume non mesurable"
    return total, f"{closed} maillage(s) fermé(s)"


def silhouette_type(profile_u: np.ndarray, profile_v: np.ndarray, lm) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    """Type de silhouette déduit du profil de hauteur mesuré (règles documentées)."""
    if not lm.has_cabin:
        return "monocorps / fourgon", "toit sur presque toute la longueur"
    rear_deck = lm.cabin_start
    front_hood = 1.0 - lm.cabin_end
    rear_drop = float(np.interp(max(lm.cabin_start - 0.05, 0.0), profile_u, profile_v))
    if rear_deck < 0.12:
        return "bicorps (hayon / break)", f"pavillon prolongé jusqu'à l'arrière (coffre {rear_deck:.0%})"
    if rear_drop > lm.deck_top + 0.15 * (1 - lm.deck_top) and rear_deck < 0.3:
        return "fastback / coupé", "lunette arrière en pente douce"
    if front_hood > 0.33 and rear_deck > 0.22:
        return "tricorps à capot long", f"capot {front_hood:.0%}, coffre {rear_deck:.0%} de la longueur"
    return "tricorps (berline)", f"capot {front_hood:.0%}, coffre {rear_deck:.0%} de la longueur"


def vehicle_type_guess(dims: dict, silhouette: str) -> tuple[str, str]:
    ratio = dims["height"] / max(dims["length"], 1e-6)
    clearance = dims.get("clearance", 0.0)
    if "fourgon" in silhouette and ratio > 0.4:
        return "van", f"monocorps, hauteur / longueur {ratio:.2f}"
    if clearance > 0.28 or ratio > 0.4:
        return "suv", f"garde au sol {clearance:.2f} m, hauteur / longueur {ratio:.2f}"
    if ratio < 0.27:
        return "sport", f"silhouette basse (hauteur / longueur {ratio:.2f})"
    if "fastback" in silhouette:
        return "coupe", "silhouette fastback"
    return "sedan", f"hauteur / longueur {ratio:.2f}, {silhouette}"


def _shape_of(size: np.ndarray, axes) -> tuple[str, float]:  # type: ignore[no-untyped-def]
    aspect = float(size[axes.lateral_axis]) / (float(size[axes.up_axis]) or 1e-6)
    if aspect > 3.2:
        return "lame fine", aspect
    if aspect > 1.6:
        return "rectangulaire allongée", aspect
    if aspect > 0.8:
        return "compacte (ronde ou carrée)", aspect
    return "verticale", aspect


def analyze(  # noqa: C901, PLR0912, PLR0915 (rapport complet, section par section)
    state: VehicleState,
    vehicle_type: str = "",
    ai_analysis: dict | None = None,
    materials=None,  # type: ignore[no-untyped-def]
) -> dict:
    """Rapport stylistique éditable (sections, entrées, statut et source de chaque information)."""
    vc = state.components
    frame = state.frame
    axes = frame.axes
    entries: list[dict] = []
    body = state.body_points()
    lm = state.landmarks() if len(body) else None
    dims = {"length": frame.length, "width": frame.width, "height": frame.height}
    if len(body):
        dims["clearance"] = float(body[:, axes.up_axis].min() - frame.ground)

    # --- Général -----------------------------------------------------------------------
    silhouette, why = "", ""
    if lm is not None:
        profile_u, profile_v = height_profile(body, frame)
        silhouette, why = silhouette_type(profile_u, profile_v, lm)
        guess, guess_why = vehicle_type_guess(dims, silhouette)
        entries.append(
            _entry(
                "type",
                "general",
                "Type de véhicule",
                guess,
                "recognized",
                "règles sur la silhouette mesurée",
                guess_why,
            )
        )
    else:
        entries.append(
            _entry("type", "general", "Type de véhicule", "", "unknown", "aucune carrosserie identifiée")
        )
    if vehicle_type:
        entries.append(
            _entry("project_type", "general", "Type déclaré du projet", vehicle_type, "user", "projet")
        )
    if ai_analysis and ai_analysis.get("type"):
        entries.append(
            _entry(
                "ai_type",
                "general",
                "Type (analyse cloud des références)",
                str(ai_analysis["type"]),
                "ai",
                "analyse cloud",
                "hypothèse fondée sur les images",
            )
        )

    # --- Proportions -----------------------------------------------------------------------
    ratio = dims["height"] / max(dims["length"], 1e-6)
    entries += [
        _entry(
            "length",
            "proportions",
            "Longueur",
            _m(dims["length"]),
            "measured",
            "boîte englobante des pièces visibles",
        ),
        _entry("width", "proportions", "Largeur", _m(dims["width"]), "measured", "boîte englobante"),
        _entry("height", "proportions", "Hauteur", _m(dims["height"]), "measured", "boîte englobante"),
        _entry(
            "ratio", "proportions", "Rapport hauteur / longueur", f"{ratio:.3f}", "measured", "dimensions"
        ),
    ]
    if lm is not None:
        entries.append(
            _entry(
                "silhouette",
                "proportions",
                "Silhouette",
                silhouette,
                "recognized",
                "profil de hauteur mesuré",
                why,
            )
        )
        entries.append(
            _entry(
                "roofline",
                "proportions",
                "Ligne de toit",
                f"habitacle de {lm.cabin_start:.0%} à {lm.cabin_end:.0%} de la longueur",
                "measured",
                "profil de hauteur",
            )
        )
    if vc.wheelbase:
        entries.append(
            _entry(
                "wheelbase",
                "proportions",
                "Empattement",
                _m(vc.wheelbase),
                "measured",
                "centres des roues identifiées",
            )
        )
    elif ai_analysis and ai_analysis.get("wheelbase"):
        entries.append(
            _entry(
                "wheelbase",
                "proportions",
                "Empattement",
                str(ai_analysis["wheelbase"]),
                "ai",
                "analyse cloud",
            )
        )
    else:
        entries.append(
            _entry("wheelbase", "proportions", "Empattement", "", "unknown", "aucune roue identifiée par nom")
        )
    volume, volume_note = mesh_volume(state)
    if volume is not None:
        entries.append(
            _entry(
                "volume",
                "proportions",
                "Volume de carrosserie",
                f"{volume:.2f} m³",
                "measured",
                "intégrale sur maillages fermés",
                volume_note,
            )
        )
    else:
        entries.append(_entry("volume", "proportions", "Volume de carrosserie", "", "unknown", volume_note))
    if "clearance" in dims:
        entries.append(
            _entry(
                "clearance",
                "proportions",
                "Garde au sol (caisse)",
                _m(dims["clearance"]),
                "measured",
                "point le plus bas de la carrosserie",
            )
        )

    # --- Face avant ------------------------------------------------------------------------
    if lm is not None:
        status = "measured" if lm.measured_wheels else "recognized"
        overhang = max((1.0 - lm.front_axle - lm.wheel_radius) * frame.length, 0.0)
        entries.append(
            _entry(
                "front_overhang",
                "front",
                "Porte-à-faux avant",
                _m(overhang),
                status,
                "essieu avant → extrémité" if lm.measured_wheels else "essieu estimé (aucune roue)",
            )
        )
        hood_length = (1.0 - lm.cabin_end) * frame.length
        entries.append(
            _entry(
                "hood",
                "front",
                "Capot (longueur / hauteur)",
                f"{_m(hood_length)} / {_m(lm.hood_top * frame.height)}",
                "measured",
                "profil de hauteur",
            )
        )
        u, v, w = frame.coords(body)
        front = u > 0.93
        if front.any():
            face_width = float(np.ptp(w[front])) * frame.width / 2
            face = f"{_m(face_width)} × {_m(float(np.ptp(v[front])) * frame.height)}"
            entries.append(
                _entry(
                    "front_face",
                    "front",
                    "Face avant (largeur × hauteur)",
                    face,
                    "measured",
                    "sommets des 7 % avant de la carrosserie",
                )
            )
    for kind, key, label in (
        ("headlight", "headlights", "Optiques avant"),
        ("taillight", "taillights", "Feux arrière"),
    ):
        comps = vc.of_kind(kind)
        section = "front" if kind == "headlight" else "rear"
        if comps:
            shape, aspect = _shape_of(comps[0].size, axes)
            entries.append(
                _entry(
                    key,
                    section,
                    label,
                    f"{len(comps)} pièce(s), forme {shape}",
                    "recognized",
                    "nom des pièces + proportions mesurées",
                    f"largeur / hauteur {aspect:.1f}",
                )
            )
        else:
            entries.append(_entry(key, section, label, "", "unknown", "aucune pièce nommée comme telle"))
    signature = vc.of_kind("signature")
    emissive = [m for m in (materials or []) if getattr(m, "is_emissive", False)]
    if signature or emissive:
        entries.append(
            _entry(
                "signature",
                "front",
                "Signature lumineuse",
                f"{len(signature)} pièce(s) dédiée(s), {len(emissive)} matériau(x) émissif(s)",
                "recognized",
                "nom des pièces et matériaux",
            )
        )
    else:
        entries.append(
            _entry(
                "signature",
                "front",
                "Signature lumineuse",
                "",
                "unknown",
                "aucune pièce ni matériau lumineux dédié identifié",
            )
        )
    for kind, key, label, section in (
        ("grille", "grille", "Calandre", "front"),
        ("front_bumper", "front_bumper", "Pare-chocs avant", "front"),
        ("rear_bumper", "rear_bumper", "Pare-chocs arrière", "rear"),
    ):
        comps = vc.of_kind(kind)
        if comps:
            size = comps[0].size
            dims_text = f"{_m(float(size[axes.lateral_axis]))} × {_m(float(size[axes.up_axis]))}"
            entries.append(
                _entry(
                    key,
                    section,
                    label,
                    dims_text,
                    "measured",
                    f"pièce « {comps[0].name} » ({comps[0].source})",
                )
            )
        else:
            entries.append(
                _entry(
                    key,
                    section,
                    label,
                    "",
                    "unknown",
                    "aucune pièce identifiée (peut faire partie de la caisse)",
                )
            )

    # --- Arrière ----------------------------------------------------------------------------
    if lm is not None:
        overhang = max((lm.rear_axle - lm.wheel_radius) * frame.length, 0.0)
        entries.append(
            _entry(
                "rear_overhang",
                "rear",
                "Porte-à-faux arrière",
                _m(overhang),
                "measured" if lm.measured_wheels else "recognized",
                "essieu arrière → extrémité",
            )
        )
        entries.append(
            _entry(
                "deck",
                "rear",
                "Coffre / hayon (hauteur)",
                _m(lm.deck_top * frame.height),
                "measured",
                "profil de hauteur",
            )
        )

    # --- Roues ------------------------------------------------------------------------------
    if vc.wheels:
        radius = vc.wheel_radius() or 0.0
        entries.append(
            _entry(
                "wheels",
                "wheels",
                "Roues",
                f"{len(vc.wheels)} roue(s), Ø {2 * radius:.2f} m",
                "measured",
                "pièces nommées (pneu, jante, wheel)",
            )
        )
        if vc.track:
            entries.append(_entry("track", "wheels", "Voies", _m(vc.track), "measured", "centres des roues"))
        entries.append(
            _entry(
                "rims",
                "wheels",
                "Dessin des jantes",
                "",
                "unknown",
                "non mesurable automatiquement (nombre de branches, style)",
            )
        )
        if lm is not None:
            u, v, _w = frame.coords(body)
            near = (np.abs(u - lm.front_axle) < lm.wheel_radius * 0.5) | (
                np.abs(u - lm.rear_axle) < lm.wheel_radius * 0.5
            )
            if near.any():
                gap = float(v[near].min() * frame.height) - 2 * radius
                entries.append(
                    _entry(
                        "arches",
                        "wheels",
                        "Dégagement au-dessus des roues",
                        _m(max(gap, 0.0)),
                        "measured",
                        "bas de caisse au droit des essieux − diamètre",
                    )
                )
    else:
        entries.append(_entry("wheels", "wheels", "Roues", "", "unknown", "aucune roue identifiée par nom"))

    # --- Éléments distinctifs ---------------------------------------------------------------------
    aero = sorted(
        {
            COMPONENT_LABELS[c.kind]
            for c in vc.components
            if c.kind in ("spoiler", "diffuser", "splitter", "intake")
        }
    )
    entries.append(
        _entry(
            "aero",
            "details",
            "Éléments aérodynamiques",
            ", ".join(aero) or "aucun identifié",
            "recognized",
            "nom des pièces",
        )
    )
    others = sorted(
        {
            COMPONENT_LABELS[c.kind]
            for c in vc.components
            if c.kind in ("mirror", "exhaust", "protection", "fender", "skirt")
        }
    )
    if others:
        entries.append(
            _entry(
                "distinctive", "details", "Autres éléments", ", ".join(others), "recognized", "nom des pièces"
            )
        )
    unclassified = [c.name for c in vc.components if c.kind == "other"]
    if unclassified:
        entries.append(
            _entry(
                "unclassified",
                "details",
                "Pièces non classées",
                ", ".join(unclassified[:8]),
                "unknown",
                "nom non reconnu : renommez la pièce ou indiquez son type",
            )
        )
    if ai_analysis and ai_analysis.get("distinctive"):
        entries.append(
            _entry(
                "ai_distinctive",
                "details",
                "Éléments distinctifs (analyse cloud)",
                ", ".join(map(str, ai_analysis["distinctive"]))[:300],
                "ai",
                "analyse cloud",
            )
        )

    # --- Matériaux --------------------------------------------------------------------------------
    if materials:
        names = ", ".join(sorted({m.name for m in materials}))[:300]
        entries.append(
            _entry("materials", "materials", "Matériaux", names, "measured", "matériaux du projet")
        )
    else:
        entries.append(
            _entry(
                "materials",
                "materials",
                "Matériaux",
                "couleurs de sommets uniquement",
                "measured",
                "aucun matériau affecté",
            )
        )

    return {
        "entries": entries,
        "landmarks": lm.to_dict() if lm else {},
        "dimensions": {k: round(float(v), 4) for k, v in dims.items()},
        "components": [
            {
                "id": c.node_id,
                "name": c.name,
                "kind": c.kind,
                "label": c.label,
                "source": c.source,
                "zone": c.zone,
                "side": c.side,
            }
            for c in vc.components
        ],
        "warnings": list(vc.warnings),
    }


def set_value(report: dict, key: str, value: str) -> dict:
    """Correction utilisateur : la valeur devient « user », l'origine est conservée."""
    for entry in report.get("entries", []):
        if entry["key"] == key:
            if entry["status"] != "user":
                entry["original"] = {
                    "value": entry["value"],
                    "status": entry["status"],
                    "source": entry["source"],
                }
            entry["value"], entry["status"], entry["source"] = value, "user", "saisie utilisateur"
            return report
    report.setdefault("entries", []).append(_entry(key, "general", key, value, "user", "saisie utilisateur"))
    return report


def value(report: dict | None, key: str, default: str = "") -> str:
    for entry in (report or {}).get("entries", []):
        if entry["key"] == key:
            return str(entry["value"])
    return default


def summary(report: dict | None) -> str:
    """Résumé texte (envoyé à un moteur cloud uniquement sur confirmation de l'utilisateur)."""
    parts = [
        f"{e['label']} : {e['value']}"
        for e in (report or {}).get("entries", [])
        if e["status"] != "unknown" and e["value"]
    ]
    return " ; ".join(parts)[:1500]
