"""Lecture des métadonnées FiveM / GTA V (.meta, .xml) : vehicles, handling, carvariations…

Lecture seule : le texte d'origine est conservé tel quel (``MetaDocument.text``) et aucune
donnée inconnue n'est supprimée — l'arbre XML complet reste disponible pour un futur éditeur.
Les erreurs XML sont rapportées avec leur ligne et leur colonne.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

# Racine XML → type de document
KINDS = {
    "CVehicleModelInfo__InitDataList": ("vehicles", "Véhicules (vehicles.meta)"),
    "CHandlingDataMgr": ("handling", "Comportement (handling.meta)"),
    "CVehicleModelInfoVariation": ("carvariations", "Variations (carvariations.meta)"),
    "CVehicleModelInfoVarGlobal": ("carcols", "Couleurs, kits et sirènes (carcols.meta)"),
    "CVehicleMetadataMgr": ("vehiclelayouts", "Dispositions (vehiclelayouts.meta)"),
    "CDataFileMgr__ContentsOfDataFileXml": ("content", "Contenu DLC (content.xml)"),
    "SSetupData": ("setup", "Configuration DLC (setup2.xml)"),
    "CExtraTextMetaFile": ("dlctext", "Textes DLC (dlctext.meta)"),
    "ShopVehicleDataArray": ("shop", "Boutique (shop_vehicle.meta)"),
    "CVehicleModColours": ("carmodcols", "Couleurs de modification (carmodcols.meta)"),
}


@dataclass
class MetaIssue:
    level: str  # « erreur », « avertissement », « info »
    message: str
    line: int | None = None


@dataclass
class MetaEntry:
    """Élément significatif d'un document (véhicule, handling, kit, sirène…)."""

    kind: str
    name: str
    fields: dict[str, str] = field(default_factory=dict)


@dataclass
class MetaDocument:
    path: str
    text: str
    kind: str = "inconnu"
    kind_label: str = "Métadonnées non reconnues"
    root_tag: str = ""
    root: ET.Element | None = None
    entries: list[MetaEntry] = field(default_factory=list)
    issues: list[MetaIssue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return self.root is not None

    def values(self, entry_kind: str, field_name: str) -> list[str]:
        return [
            e.fields[field_name] for e in self.entries if e.kind == entry_kind and e.fields.get(field_name)
        ]

    def search(self, needle: str, limit: int = 200) -> list[tuple[str, str]]:
        """Chemins d'éléments dont la balise, un attribut ou le texte contient ``needle``."""
        if self.root is None or not needle:
            return []
        needle = needle.lower()
        found: list[tuple[str, str]] = []
        stack: list[tuple[ET.Element, str]] = [(self.root, "")]
        while stack and len(found) < limit:
            element, path = stack.pop()
            here = f"{path}/{element.tag}"
            text = (element.text or "").strip()
            attributes = " ".join(f'{k}="{v}"' for k, v in element.attrib.items())
            if needle in element.tag.lower() or needle in text.lower() or needle in attributes.lower():
                found.append((here, text or attributes))
            stack.extend((child, here) for child in reversed(list(element)))
        return found


def _text(element: ET.Element | None, tag: str) -> str:
    if element is None:
        return ""
    child = element.find(tag)
    if child is None:
        return ""
    if child.text and child.text.strip():
        return child.text.strip()
    return child.attrib.get("value", "").strip()


def _decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


def parse_meta(data: bytes | str, path: str = "") -> MetaDocument:
    text = data if isinstance(data, str) else _decode(data)
    document = MetaDocument(path, text)
    if not text.strip():
        document.issues.append(MetaIssue("erreur", "Fichier vide."))
        return document
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        line, column = getattr(exc, "position", (None, None))
        document.issues.append(
            MetaIssue("erreur", f"XML invalide (ligne {line}, colonne {column}) : {exc.msg}", line)
        )
        return document
    document.root = root
    document.root_tag = root.tag
    document.kind, document.kind_label = KINDS.get(root.tag, ("inconnu", f"Métadonnées « {root.tag} »"))
    extractor = _EXTRACTORS.get(document.kind)
    if extractor is not None:
        extractor(root, document)
    if document.kind == "inconnu":
        document.issues.append(
            MetaIssue("info", f"Type « {root.tag} » non interprété : affiché tel quel, données conservées.")
        )
    return document


# --- Extraction par type ----------------------------------------------------------

_VEHICLE_FIELDS = (
    "modelName",
    "txdName",
    "handlingId",
    "gameName",
    "vehicleMakeName",
    "type",
    "vehicleClass",
    "layout",
    "audioNameHash",
    "plateType",
    "dashboardType",
)


def _vehicles(root: ET.Element, doc: MetaDocument) -> None:
    for item in root.iterfind("./InitDatas/Item"):
        fields = {tag: _text(item, tag) for tag in _VEHICLE_FIELDS}
        name = fields["modelName"] or "(sans modelName)"
        doc.entries.append(MetaEntry("vehicle", name, fields))
        if not fields["modelName"]:
            doc.issues.append(MetaIssue("erreur", "Véhicule sans modelName."))
        elif not _NAME_PATTERN.match(fields["modelName"]):
            doc.issues.append(
                MetaIssue(
                    "avertissement", f"modelName « {name} » : caractères inhabituels (espaces, accents)."
                )
            )
        if not fields["txdName"]:
            doc.issues.append(MetaIssue("avertissement", f"{name} : txdName absent."))
        if not fields["handlingId"]:
            doc.issues.append(MetaIssue("avertissement", f"{name} : handlingId absent."))
    for item in root.iterfind("./txdRelationships/Item"):
        relation = {"parent": _text(item, "parent"), "child": _text(item, "child")}
        doc.entries.append(MetaEntry("txd_relationship", relation["child"], relation))
    _duplicates(doc, "vehicle", "modelName")


def _handling(root: ET.Element, doc: MetaDocument) -> None:
    for item in root.iterfind("./HandlingData/Item"):
        fields = {"handlingName": _text(item, "handlingName"), "type": item.attrib.get("type", "")}
        for tag in (
            "fMass",
            "fInitialDriveForce",
            "fInitialDriveMaxFlatVel",
            "fBrakeForce",
            "nInitialDriveGears",
        ):
            fields[tag] = _text(item, tag)
        doc.entries.append(MetaEntry("handling", fields["handlingName"] or "(sans handlingName)", fields))
        if not fields["handlingName"]:
            doc.issues.append(MetaIssue("erreur", "Entrée de handling sans handlingName."))
    _duplicates(doc, "handling", "handlingName")


def _carvariations(root: ET.Element, doc: MetaDocument) -> None:
    for item in root.iterfind("./variationData/Item"):
        kits = [k.text.strip() for k in item.iterfind("./kits/Item") if k.text and k.text.strip()]
        fields = {
            "modelName": _text(item, "modelName"),
            "kits": ", ".join(kits),
            "lightSettings": _text(item, "lightSettings"),
            "sirenSettings": _text(item, "sirenSettings"),
            "colors": str(len(item.findall("./colors/Item"))),
        }
        doc.entries.append(MetaEntry("variation", fields["modelName"] or "(sans modelName)", fields))


def _carcols(root: ET.Element, doc: MetaDocument) -> None:
    for item in root.iterfind("./Kits/Item"):
        fields = {
            "kitName": _text(item, "kitName"),
            "id": _text(item, "id"),
            "mods": str(len(item.findall("./visibleMods/Item"))),
        }
        doc.entries.append(MetaEntry("kit", fields["kitName"] or "(kit sans nom)", fields))
    for item in root.iterfind("./Lights/Item"):
        doc.entries.append(MetaEntry("lights", _text(item, "id") or "?", {"id": _text(item, "id")}))
    for item in root.iterfind("./Sirens/Item"):
        fields = {"id": _text(item, "id"), "name": _text(item, "name")}
        doc.entries.append(MetaEntry("siren", fields["name"] or fields["id"] or "?", fields))


def _content(root: ET.Element, doc: MetaDocument) -> None:
    for item in root.iterfind("./dataFiles/Item"):
        fields = {"filename": _text(item, "filename"), "fileType": _text(item, "fileType")}
        doc.entries.append(MetaEntry("data_file", fields["filename"], fields))


def _duplicates(doc: MetaDocument, kind: str, field_name: str) -> None:
    seen: dict[str, int] = {}
    for value in doc.values(kind, field_name):
        seen[value.lower()] = seen.get(value.lower(), 0) + 1
    for key, count in seen.items():
        if count > 1:
            doc.issues.append(MetaIssue("avertissement", f"{field_name} « {key} » défini {count} fois."))


_EXTRACTORS = {
    "vehicles": _vehicles,
    "handling": _handling,
    "carvariations": _carvariations,
    "carcols": _carcols,
    "content": _content,
}


# --- Vérifications croisées -------------------------------------------------------


def cross_check(documents: list[MetaDocument], model_names: set[str], txd_names: set[str]) -> list[MetaIssue]:
    """Références entre fichiers : handlingId, kits, modèles et textures présents."""
    issues: list[MetaIssue] = []
    handlings = {v.lower() for d in documents for v in d.values("handling", "handlingName")}
    kits = {v.lower() for d in documents for v in d.values("kit", "kitName")}
    models = {m.lower() for m in model_names}
    txds = {t.lower() for t in txd_names}
    has_handling = any(d.kind == "handling" for d in documents)
    has_carcols = any(d.kind == "carcols" for d in documents)
    for document in documents:
        for entry in document.entries:
            if entry.kind == "vehicle":
                model = entry.fields.get("modelName", "").lower()
                handling = entry.fields.get("handlingId", "").lower()
                txd = entry.fields.get("txdName", "").lower()
                if model and model not in models:
                    issues.append(
                        MetaIssue("erreur", f"{entry.name} : aucun fichier {model}.yft dans la ressource.")
                    )
                if txd and txd not in txds:
                    issues.append(
                        MetaIssue("avertissement", f"{entry.name} : dictionnaire {txd}.ytd introuvable.")
                    )
                if handling and has_handling and handling not in handlings:
                    issues.append(
                        MetaIssue(
                            "erreur", f"{entry.name} : handlingId « {handling} » absent de handling.meta."
                        )
                    )
                if handling and not has_handling:
                    issues.append(
                        MetaIssue("avertissement", f"{entry.name} : aucun handling.meta pour « {handling} ».")
                    )
            elif entry.kind == "variation" and entry.fields.get("kits"):
                for kit in entry.fields["kits"].split(", "):
                    if has_carcols and kit.lower() not in kits and not kit.lower().endswith("_default_kit"):
                        issues.append(
                            MetaIssue(
                                "avertissement", f"{entry.name} : kit « {kit} » absent de carcols.meta."
                            )
                        )
    return issues
