"""Asset Provenance Registry : origine, licence et modifications de chaque ressource du projet.

Les informations détectées automatiquement (fichiers importés, ressources FiveM, générations
IA, références, pièces Lore Friendly, marques) sont complétées par l'utilisateur. Règles :

- aucune licence n'est inventée : une licence inconnue reste « Non renseignée » ;
- les mentions obligatoires ne peuvent pas être supprimées (seulement ajoutées) ;
- le registre ne lit aucun contenu protégé et ne contourne aucune protection de fichier.

Document ``provenance`` (format 1) : ``{"format": 1, "entries": {id: {champs saisis}}}``.
"""

from __future__ import annotations

import copy

DOC_KEY = "provenance"
FORMAT = 1
UNKNOWN_LICENSE = "Non renseignée"
EDITABLE = ("author", "source", "license", "restrictions", "notes", "references")
KIND_LABELS = {
    "import": "Fichier 3D importé",
    "fivem": "Ressource FiveM / GTA V",
    "ai_generation": "Modèle généré par IA",
    "reference": "Image de référence",
    "lore_part": "Pièces Lore Friendly (générées)",
    "brand": "Marque",
}
LICENSE_HINTS = ("license", "licence", "readme", "credits", "terms", "eula")


class ProvenanceError(ValueError):
    """Modification refusée (mention obligatoire, champ inconnu)."""


def empty() -> dict:
    return {"format": FORMAT, "entries": {}}


def migrate(doc: dict | None) -> dict:
    """Document courant (format 1) ; les formats futurs ajouteront leurs étapes ici."""
    if not isinstance(doc, dict):
        return empty()
    result = copy.deepcopy(doc)
    if not isinstance(result.get("entries"), dict):
        result["entries"] = {}
    result["format"] = FORMAT
    return result


def _entry(entry_id: str, kind: str, name: str, **fields) -> dict:  # type: ignore[no-untyped-def]
    return {
        "id": entry_id,
        "kind": kind,
        "kind_label": KIND_LABELS.get(kind, kind),
        "name": name,
        "author": fields.get("author", ""),
        "source": fields.get("source", ""),
        "license": fields.get("license", "") or UNKNOWN_LICENSE,
        "imported_at": fields.get("imported_at", ""),
        "modifications": list(fields.get("modifications", [])),
        "restrictions": fields.get("restrictions", ""),
        "references": list(fields.get("references", [])),
        "mentions": list(fields.get("mentions", [])),
        "notes": fields.get("notes", ""),
        "detected": sorted(k for k, v in fields.items() if v),
    }


def collect(session, ai_doc: dict | None, lore_doc: dict | None, brand_lookup=None) -> list[dict]:  # type: ignore[no-untyped-def]
    """Entrées détectées dans le projet (sans les saisies de l'utilisateur)."""
    project = session.project
    entries: list[dict] = []
    edited: dict[str, int] = {}
    for node in session.scene.walk():
        if node.asset_id and node.extra.get("edited_geometry"):
            edited[node.asset_id] = edited.get(node.asset_id, 0) + 1
    generated = {r.get("asset_id"): r for r in (ai_doc or {}).get("generations", []) if r.get("asset_id")}
    for asset in project.assets.values():
        if asset.id in generated:
            continue
        mods = []
        if asset.id in edited:
            mods.append(f"{edited[asset.id]} pièce(s) modifiée(s) dans le projet (fichier d'origine intact)")
        entries.append(
            _entry(
                asset.id,
                "import",
                asset.original_name,
                source=asset.source_path,
                imported_at=asset.imported_at,
                modifications=mods,
                notes="; ".join(asset.notes)[:300],
            )
        )
    for resource in project.resources.values():
        files = [f.get("path", "") for f in resource.manifest.get("files", []) if isinstance(f, dict)]
        hints = [f for f in files if any(h in f.lower() for h in LICENSE_HINTS)]
        notes = ""
        if hints:
            listed = ", ".join(hints[:5])
            notes = f"Fichier(s) de licence ou de crédits dans la ressource : {listed} (à consulter)."
        entries.append(
            _entry(
                resource.id,
                "fivem",
                resource.name,
                source=resource.source_path,
                imported_at=resource.imported_at,
                notes=notes,
                restrictions="Ressource tierce : vérifiez les droits de modification et de redistribution.",
            )
        )
    for record in (ai_doc or {}).get("generations", []):
        if record.get("status") != "succeeded":
            continue
        engine_license = record.get("engine_license", "")
        entries.append(
            _entry(
                record["id"],
                "ai_generation",
                f"{record.get('engine_name', '')} · {record['id'][:8]}",
                author=f"Moteur {record.get('engine_name', '')}",
                source="AI Vehicle Creator",
                imported_at=record.get("created_at", ""),
                references=list(record.get("references", [])),
                notes=f"Licence du moteur : {engine_license}. La licence du résultat dépend des "
                "conditions du "
                "moteur et de vos références : à renseigner."
                if engine_license
                else "",
            )
        )
    for ref in (ai_doc or {}).get("references", []):
        entries.append(
            _entry(
                ref["id"],
                "reference",
                ref.get("name", ""),
                source=ref.get("source", ""),
                license=ref.get("license", ""),
                imported_at=ref.get("added_at", ""),
                author=ref.get("author", ""),
            )
        )
    brands_used: set[str] = set()
    for design in (lore_doc or {}).get("designs", []):
        if design.get("brand"):
            brands_used.add(design["brand"])
        for variant in design.get("variants", []):
            operations = variant.get("operations", [])
            if not any(o.get("parts") for o in operations):
                continue
            entries.append(
                _entry(
                    f"lore-parts-{variant['id']}",
                    "lore_part",
                    f"Pièces de « {variant.get('name', '')} »",
                    author="LeStitcheurFou Cars (pièces paramétriques générées)",
                    source="Lore Friendly Engine",
                    license="Créées dans ce projet",
                    imported_at=variant.get("created_at", ""),
                    modifications=[o.get("label", o.get("op", "")) for o in operations][-12:],
                    references=[design.get("source_name", "")],
                )
            )
    for key in sorted(brands_used):
        brand = brand_lookup(key) if brand_lookup else None
        if brand is None:
            continue
        restrictions = (
            "Nom utilisé comme référence créative ; aucun logo officiel fourni." if brand.is_gta else ""
        )
        entries.append(
            _entry(
                f"brand-{key}",
                "brand",
                brand.name,
                author=brand.author,
                source=brand.provenance,
                license=brand.license,
                restrictions=restrictions,
                mentions=[brand.provenance] if brand.is_gta else [],
            )
        )
    return entries


def merged(detected: list[dict], doc: dict | None) -> list[dict]:
    """Entrées détectées complétées par les saisies (la licence n'est jamais inventée)."""
    user = migrate(doc)["entries"]
    result = []
    for entry in detected:
        item = copy.deepcopy(entry)
        saved = user.get(entry["id"], {})
        item["edited"] = []
        for key in EDITABLE:
            if saved.get(key):
                item[key] = saved[key]
                item["edited"].append(key)
        item["mentions"] = list(dict.fromkeys([*entry.get("mentions", []), *saved.get("mentions", [])]))
        if not item.get("license"):
            item["license"] = UNKNOWN_LICENSE
        result.append(item)
    return result


def update(doc: dict | None, entry_id: str, **fields) -> dict:  # type: ignore[no-untyped-def]
    result = migrate(doc)
    entry = result["entries"].setdefault(entry_id, {})
    for key, value in fields.items():
        if key not in EDITABLE:
            raise ProvenanceError(f"Champ non modifiable : {key}")
        entry[key] = value.strip() if isinstance(value, str) else value
    return result


def add_mention(doc: dict | None, entry_id: str, text: str) -> dict:
    cleaned = " ".join(text.split())
    if not cleaned:
        raise ProvenanceError("La mention est vide.")
    result = migrate(doc)
    mentions = result["entries"].setdefault(entry_id, {}).setdefault("mentions", [])
    if cleaned not in mentions:
        mentions.append(cleaned)
    return result


def remove_mention(doc: dict | None, entry_id: str, text: str) -> dict:
    """Toujours refusé : une mention obligatoire ne se supprime pas."""
    raise ProvenanceError(
        f"La mention « {text[:60]} » ({entry_id}) est obligatoire : suppression impossible."
    )


def incomplete(entries: list[dict]) -> list[dict]:
    """Entrées sans licence ou sans source renseignée (à compléter par l'utilisateur)."""
    return [e for e in entries if e["license"] == UNKNOWN_LICENSE or not e.get("source")]
