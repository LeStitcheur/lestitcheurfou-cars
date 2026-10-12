"""Design Originality Review : repérer les éléments encore proches de la référence.

La revue s'appuie sur des **mesures techniques** (recouvrement de silhouettes, opérations
réellement appliquées, pièces remplacées, dimensions) et sur les confirmations de
l'utilisateur. Elle ne produit **aucun pourcentage de légalité**, aucune certification et
n'affirme jamais qu'une modification est juridiquement suffisante. Les seuils utilisés sont
des repères de l'application, indiqués avec chaque mesure.
"""

from __future__ import annotations

from lsfcars.lorefriendly import operations as ops

DISCLAIMER = (
    "Revue d'aide à la conception : elle signale des éléments peu ou pas modifiés par rapport à la "
    "référence à partir de mesures techniques. Ce n'est ni un avis juridique, ni une évaluation de "
    "la ressemblance perçue, ni une certification de conformité aux règles de Rockstar Games ou de "
    "Cfx.re. Aucune modification n'est présentée comme suffisante."
)
THRESHOLDS = {"changed": 0.93, "slight": 0.985}  # recouvrement de silhouettes (intersection / union)
STATUS_LABELS = {
    "unchanged": "Inchangé",
    "slight": "Peu modifié",
    "changed": "Modifié",
    "check": "À vérifier par vous",
}
ASPECTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "silhouette": ("Silhouette", ("roof_height", "roof_slope", "nose_length", "tail_length")),
    "front": ("Face avant", ("front_bumper", "nose_length", "front_taper", "hood_height", "intakes")),
    "lights": ("Optiques", ("headlights", "taillights", "signature", "rear_signature")),
    "grille": ("Calandre", ("grille",)),
    "rear": ("Face arrière", ("taillights", "rear_bumper", "ducktail", "diffuser", "exhaust")),
    "logos": ("Logos et inscriptions", ()),
    "distinctive": ("Éléments distinctifs", ("signature", "trim", "hood_scoop", "side_skirts", "spoiler")),
    "proportions": ("Proportions", ("nose_length", "tail_length", "fender_width", "ride_height", "track")),
}
FRONT_OPS = {
    "headlights",
    "grille",
    "front_bumper",
    "signature",
    "intakes",
    "splitter",
    "hood_height",
    "nose_length",
    "front_taper",
    "front_bumper_depth",
    "hood_scoop",
    "canards",
    "protection",
}
REAR_OPS = {
    "taillights",
    "rear_bumper",
    "rear_signature",
    "diffuser",
    "exhaust",
    "spoiler",
    "ducktail",
    "tail_length",
    "rear_taper",
    "rear_bumper_depth",
}
CHECKLIST = {
    "logos_removed": "Logos et inscriptions d'origine retirés",
    "names_checked": "Noms de marque et de modèle vérifiés",
    "livery_checked": "Textures et livrée sans identité réelle",
}
_ORDER = ["changed", "slight", "unchanged"]


def _iou_status(value: float | None) -> str:
    if value is None:
        return "check"
    if value < THRESHOLDS["changed"]:
        return "changed"
    if value < THRESHOLDS["slight"]:
        return "slight"
    return "unchanged"


def _most_changed(*statuses: str) -> str:
    present = [s for s in statuses if s in _ORDER]
    return min(present, key=_ORDER.index) if present else "check"


def review(
    comparison: dict, applied_ops: list[str], checklist: dict | None = None, logo_annotations: int = 0
) -> dict:
    """Revue d'originalité d'une variante comparée à sa source (``compare.compare(source, variante)``)."""
    checklist = checklist or {}
    applied = {op for op in applied_ops if op in ops.OPERATIONS}
    sil = comparison.get("silhouettes", {})
    dims = comparison.get("dimensions", {})
    delta, base = dims.get("delta", {}), dims.get("a", {})
    added = comparison.get("added", [])
    components = comparison.get("components", [])
    replaced = {c["kind"] for c in components if c["status"] == "remplacé ou masqué"}
    deformed = {c["kind"] for c in components if c["status"] == "déformé"}
    aspects: list[dict] = []

    def label_of(op: str) -> str:
        return ops.OPERATIONS[op].label

    def add(key: str, status: str, measures: list[str], changes: list[str]) -> None:
        label, alternatives = ASPECTS[key]
        suggestions = [
            {"op": op, "label": label_of(op), "studio": ops.STUDIOS[ops.OPERATIONS[op].studio]}
            for op in alternatives
            if op not in applied
        ]
        aspects.append(
            {
                "key": key,
                "label": label,
                "status": status,
                "status_label": STATUS_LABELS[status],
                "measures": measures,
                "changes": changes,
                "suggestions": suggestions[:4] if status != "changed" else [],
            }
        )

    def iou_text(view: str, label: str) -> list[str]:
        value = sil.get(view)
        return (
            [f"Recouvrement de silhouette {label} : {value:.3f} (mesure technique)"]
            if value is not None
            else []
        )

    status = _most_changed(_iou_status(sil.get("left")), _iou_status(sil.get("top")))
    add(
        "silhouette",
        status,
        iou_text("left", "de profil") + iou_text("top", "de dessus"),
        [label_of(o) for o in sorted(applied & set(ASPECTS["silhouette"][1]))],
    )

    for key, view, label, group in (
        ("front", "front", "de face", FRONT_OPS),
        ("rear", "back", "arrière", REAR_OPS),
    ):
        done = applied & group
        status = _iou_status(sil.get(view))
        if len(done) >= 3:
            status = "changed"
        elif done and status in ("unchanged", "check"):
            status = "slight"
        add(key, status, iou_text(view, label), [label_of(o) for o in sorted(done)])

    head = "headlights" in applied or "headlight" in replaced
    tail = "taillights" in applied or "taillight" in replaced
    signature = bool(applied & {"signature", "rear_signature"})
    status = "changed" if head and tail else "slight" if head or tail or signature else "unchanged"
    add(
        "lights",
        status,
        [
            f"Phares remplacés : {'oui' if head else 'non'}",
            f"Feux arrière remplacés : {'oui' if tail else 'non'}",
            f"Signature lumineuse ajoutée : {'oui' if signature else 'non'}",
        ],
        [],
    )

    grille = "grille" in applied or "grille" in replaced
    add(
        "grille",
        "changed" if grille else "unchanged",
        [f"Calandre remplacée : {'oui' if grille else 'non'}"],
        [],
    )

    confirmed = bool(checklist.get("logos_removed"))
    measures = ["Aucune détection automatique de logos (aucun modèle de reconnaissance embarqué)."]
    if logo_annotations:
        measures.append(
            f"{logo_annotations} zone(s) de logo annotée(s) sur les références (AI Vehicle Creator)."
        )
    add(
        "logos",
        "changed" if confirmed else "check",
        measures,
        ["Confirmé par l'utilisateur"] if confirmed else [],
    )

    new_parts = [a for a in added if a.get("kind") not in replaced]
    status = "changed" if len(new_parts) >= 4 else "slight" if new_parts else "unchanged"
    add(
        "distinctive",
        status,
        [f"{len(added)} pièce(s) ajoutée(s), {len(replaced)} type(s) de pièce remplacé(s)"],
        sorted({a["label"] for a in added}),
    )

    measures = []
    relative = 0.0
    for key, label in (
        ("length", "Longueur"),
        ("height", "Hauteur"),
        ("width", "Largeur"),
        ("wheelbase", "Empattement"),
    ):
        if key in delta and base.get(key):
            change = delta[key] / base[key]
            relative = max(relative, abs(change))
            measures.append(f"{label} : {delta[key]:+.3f} m ({change:+.1%})")
    status = "changed" if relative > 0.03 else "slight" if relative > 0.008 or deformed else "unchanged"
    add("proportions", status, measures, [])

    return {
        "aspects": aspects,
        "rework": [a["label"] for a in aspects if a["status"] != "changed"],
        "checklist": {k: bool(checklist.get(k)) for k in CHECKLIST},
        "thresholds": dict(THRESHOLDS),
        "limits": comparison.get("limits", ""),
        "disclaimer": DISCLAIMER,
    }
