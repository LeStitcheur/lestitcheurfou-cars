"""Adaptateurs d'export des éclairages et sirènes (ELS / non-ELS / données intermédiaires).

Chaque adaptateur déclare ses fonctions prises en charge, ses limites, ses dépendances et les
validations qu'il effectue. Une configuration non exportable est refusée avec la liste précise
des raisons. Aucun fichier produit n'est garanti fonctionnel en jeu : il doit être intégré à une
ressource dont le modèle possède les os ou « extras » correspondants (LeStitcheurFou Cars
n'écrit pas encore de modèle GTA V), puis testé.

Sources des formats :

- ``carcols.meta`` (réglages de sirènes) : structure observée dans les fichiers de la communauté
  et ses outils (20 sirènes au maximum par réglage, ``sequencerBpm`` commun, séquenceurs de
  32 bits, couleurs AARRGGBB). Aucune documentation officielle de Rockstar.
- VCF MISS-ELS : documentation publique du projet MISS-ELS (``docs/vcf.md``) : ``vcfroot``,
  ``EOVERRIDE`` (``Extra01`` à ``Extra12``), ``STATIC``, ``SOUNDS``, ``PATTERN``
  (``PRIMARY``, ``SECONDARY``, ``REARREDS``) et ``Flash`` (``Duration``, ``Extras``).
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path

from lsfcars import __version__
from lsfcars.emergency import model
from lsfcars.emergency.model import Pattern, Variant

INTERMEDIATE_VERSION = 1
CARCOLS_MAX_SIRENS = 20
CARCOLS_STEPS = 32
ELS_MAX_EXTRAS = 12
ELS_COLORS = {"red", "green", "blue", "white", "amber"}


class AdapterError(Exception):
    """Export impossible : ``reasons`` explique précisément pourquoi."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__(" ; ".join(reasons))
        self.reasons = reasons


@dataclass
class ExportIssue:
    level: str  # error / warning / info
    message: str


@dataclass
class AdapterInfo:
    key: str
    name: str
    description: str
    supported: list[str]
    limits: list[str]
    dependencies: list[str]
    validations: list[str]
    available: bool = True
    unavailable_reason: str = ""


@dataclass
class ExportContext:
    studio: object  # EmergencyStudio
    variant: Variant
    resource_name: str = "lsf_vehicle"
    extra: dict = field(default_factory=dict)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "variante"


def _ordered_lights(variant: Variant) -> list[model.LightSource]:
    """Sources actives, rampe principale d'abord (ordre stable)."""
    rank: dict[str, int] = {}
    for group in sorted(variant.groups, key=lambda g: g.kind != "main"):
        for light_id in group.light_ids:
            rank.setdefault(light_id, len(rank))
    lights = [light for light in variant.lights if light.enabled]
    return sorted(lights, key=lambda light: rank.get(light.id, 10_000))


def _active_pattern(variant: Variant) -> Pattern | None:
    return variant.pattern(variant.active_pattern) or (variant.patterns[0] if variant.patterns else None)


def _values(parent: ET.Element, pairs: tuple[tuple[str, str], ...]) -> None:
    for tag, value in pairs:
        ET.SubElement(parent, tag, value=value)


class Adapter:
    info: AdapterInfo

    def validate(self, context: ExportContext) -> list[ExportIssue]:
        raise NotImplementedError

    def export(self, context: ExportContext, folder: str | Path) -> list[Path]:
        raise NotImplementedError

    def _ensure_exportable(self, context: ExportContext) -> list[ExportIssue]:
        if not self.info.available:
            raise AdapterError([self.info.unavailable_reason])
        issues = self.validate(context)
        errors = [i.message for i in issues if i.level == "error"]
        if errors:
            raise AdapterError(errors)
        return issues


# --- Données intermédiaires ------------------------------------------------------------------


class IntermediateAdapter(Adapter):
    info = AdapterInfo(
        "lsf-json",
        "Données intermédiaires LeStitcheurFou Cars (JSON)",
        "Toutes les données de la variante, positions monde des feux résolues : base des futurs exports.",
        [
            "Équipements et transformations",
            "Feux, groupes, motifs",
            "Sirène",
            "Livrée (données)",
            "Provenance",
        ],
        ["Format propre à LeStitcheurFou Cars : non lu par GTA V ni par FiveM"],
        ["Aucune"],
        ["Variante présente"],
    )

    def validate(self, context: ExportContext) -> list[ExportIssue]:
        return [ExportIssue("info", "Export complet, sans perte.")]

    def build(self, context: ExportContext) -> dict:
        studio, variant = context.studio, context.variant
        lights = []
        for light in variant.lights:
            world = studio.light_world(light)  # type: ignore[attr-defined]
            entry = asdict(light)
            entry["rgb"] = list(light.rgb)
            entry["world_position"] = [float(v) for v in world[0]] if world else None
            entry["world_direction"] = [float(v) for v in world[1]] if world else None
            lights.append(entry)
        equipment = []
        for node in studio.equipment_nodes(variant):  # type: ignore[attr-defined]
            info = node.extra.get("component", {})
            placed = node.extra.get("emergency_equipment", {})
            equipment.append(
                {
                    "name": node.name,
                    "node_id": node.id,
                    "component_id": placed.get("component_id"),
                    "zone": placed.get("zone"),
                    "transform": node.transform.to_dict(),
                    "license": info.get("license", ""),
                    "provenance": info.get("provenance", ""),
                }
            )
        data = asdict(variant)
        data["lights"] = lights
        return {
            "format": "lsfcars-emergency",
            "version": INTERMEDIATE_VERSION,
            "app_version": __version__,
            "variant": data,
            "service": asdict(model.service(variant.service)),
            "equipment": equipment,
            "disclaimer": "Données intermédiaires : aucune compatibilité en jeu n'est garantie.",
        }

    def export(self, context: ExportContext, folder: str | Path) -> list[Path]:
        self._ensure_exportable(context)
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{_slug(context.variant.name)}.lsf-emergency.json"
        path.write_text(json.dumps(self.build(context), ensure_ascii=False, indent=2), encoding="utf-8")
        return [path]


# --- carcols.meta (non-ELS) ------------------------------------------------------------------------


def argb(rgb: tuple[float, float, float]) -> str:
    r, g, b = (max(0, min(255, round(c * 255))) for c in rgb)
    return f"0xFF{r:02X}{g:02X}{b:02X}"


def sequencer_bits(states: list[bool]) -> int:
    """Masque de 32 bits. **Hypothèse** : le premier pas correspond au bit de poids fort."""
    value = 0
    for state in states[:CARCOLS_STEPS]:
        value = (value << 1) | int(bool(state))
    return value


class CarcolsAdapter(Adapter):
    info = AdapterInfo(
        "carcols",
        "Sirènes non-ELS : fragment carcols.meta",
        "Réglage de sirènes (feux et séquences) au format XML de carcols.meta, à intégrer à une ressource.",
        [
            "Jusqu'à 20 feux (sirènes 1 à 20)",
            "Couleur par feu (AARRGGBB)",
            "Séquence clignotante de 32 pas dérivée du motif actif (sequencerBpm)",
        ],
        [
            "20 feux au maximum par réglage (limite du moteur) : les suivants sont ignorés",
            "Motif échantillonné sur 32 pas égaux : les durées non multiples sont arrondies",
            "Ordre des bits du séquenceur supposé (premier pas = bit de poids fort), à vérifier en jeu",
            "Rotation des gyrophares non exportée (feux clignotants seulement)",
            "Positions non exportées : le modèle doit contenir les os siren1 à sirenN au bon endroit",
        ],
        [
            "Modèle .yft avec os siren1…sirenN (non produit par LeStitcheurFou Cars)",
            "Identifiant de réglage unique dans la ressource, "
            "référencé par carvariations.meta (sirenSettings)",
        ],
        ["Nombre de feux", "Motif actif non vide", "Erreur de quantification du motif", "Couleurs"],
    )

    def plan(self, variant: Variant) -> tuple[list[model.LightSource], Pattern | None, int]:
        lights = _ordered_lights(variant)[:CARCOLS_MAX_SIRENS]
        pattern = _active_pattern(variant)
        bpm = round(60000 * CARCOLS_STEPS / pattern.cycle_ms) if pattern and pattern.cycle_ms > 0 else 0
        return lights, pattern, bpm

    def validate(self, context: ExportContext) -> list[ExportIssue]:
        variant = context.variant
        issues: list[ExportIssue] = []
        enabled = [light for light in variant.lights if light.enabled]
        if not enabled:
            issues.append(ExportIssue("error", "Aucune source lumineuse active à exporter."))
        if len(enabled) > CARCOLS_MAX_SIRENS:
            message = f"{len(enabled)} feux : seuls les {CARCOLS_MAX_SIRENS} premiers seront exportés."
            issues.append(ExportIssue("warning", message))
        pattern = _active_pattern(variant)
        if pattern is None or pattern.cycle_ms <= 0:
            issues.append(ExportIssue("error", "Aucun motif actif à convertir en séquence."))
        else:
            step = pattern.cycle_ms / CARCOLS_STEPS
            elapsed, worst = 0, 0.0
            for frame in pattern.frames:
                elapsed += frame.duration_ms
                worst = max(worst, abs(elapsed / step - round(elapsed / step)) * step)
            if worst > 1.0:
                message = f"Motif arrondi sur 32 pas de {step:.1f} ms (écart maximal {worst:.0f} ms)."
                issues.append(ExportIssue("warning", message))
        issues.append(
            ExportIssue("info", "Fragment non validé en jeu : nécessite les os siren1…sirenN dans le modèle.")
        )
        return issues

    def build_xml(self, context: ExportContext, setting_id: int = 1) -> str:
        variant = context.variant
        lights, pattern, bpm = self.plan(variant)
        groups_of = {light.id: {g.id for g in variant.groups if light.id in g.light_ids} for light in lights}
        samples = pattern.sample(CARCOLS_STEPS) if pattern else [set() for _ in range(CARCOLS_STEPS)]
        root = ET.Element("Item")
        ET.SubElement(root, "id", value=str(setting_id))
        ET.SubElement(root, "name").text = _slug(variant.name)
        _values(
            root,
            (
                ("timeMultiplier", "1.0"),
                ("lightFalloffMax", "40.0"),
                ("lightFalloffExponent", "50.0"),
                ("lightInnerConeAngle", "2.0"),
                ("lightOuterConeAngle", "70.0"),
                ("lightOffset", "0.0"),
            ),
        )
        ET.SubElement(root, "textureName").text = "VehicleLight_sirenlight"
        ET.SubElement(root, "sequencerBpm", value=str(bpm))
        for light_tag in ("leftHeadLight", "rightHeadLight", "leftTailLight", "rightTailLight"):
            ET.SubElement(ET.SubElement(root, light_tag), "sequencer", value="0")
            ET.SubElement(root, f"{light_tag}Multiples", value="1")
        ET.SubElement(root, "useRealLights", value="true")
        sirens = ET.SubElement(root, "sirens")
        for light in lights:
            states = [bool(groups_of[light.id] & sample) for sample in samples]
            item = ET.SubElement(sirens, "Item")
            motion = (("delta", "0.0"), ("start", "0.0"), ("speed", "0.0"))
            tail = (("multiples", "1"), ("direction", "false"), ("syncToBpm", "true"))
            _values(ET.SubElement(item, "rotation"), (*motion, ("sequencer", "0"), *tail))
            _values(
                ET.SubElement(item, "flashiness"),
                (*motion, ("sequencer", str(sequencer_bits(states))), *tail),
            )
            _values(
                ET.SubElement(item, "corona"),
                (
                    ("intensity", f"{50 * light.intensity:.1f}"),
                    ("size", "0.8"),
                    ("pull", "0.15"),
                    ("faceCamera", "false"),
                ),
            )
            ET.SubElement(item, "color", value=argb(light.rgb))
            ET.SubElement(item, "intensity", value=f"{light.intensity:.2f}")
            ET.SubElement(item, "lightGroup", value="0")
            _values(
                item,
                (
                    ("rotate", "false"),
                    ("scale", "true"),
                    ("scaleFactor", "2"),
                    ("flash", "true"),
                    ("light", "true"),
                    ("spotLight", "true"),
                    ("castShadows", "false"),
                ),
            )
        ET.indent(root)
        return ET.tostring(root, encoding="unicode")

    def export(self, context: ExportContext, folder: str | Path) -> list[Path]:
        issues = self._ensure_exportable(context)
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        slug = _slug(context.variant.name)
        setting_id = int(context.extra.get("setting_id", 1))
        header = (
            "<!-- Fragment carcols.meta généré par LeStitcheurFou Cars : à insérer dans <Sirens>. "
            "Non validé en jeu ; nécessite les os siren1..sirenN dans le modèle. -->\n"
        )
        xml_path = folder / f"carcols_sirens_{slug}.xml"
        xml_path.write_text(header + self.build_xml(context, setting_id) + "\n", encoding="utf-8")
        lights, pattern, bpm = self.plan(context.variant)
        lines = [
            f"Réglage de sirènes : {context.variant.name} (identifiant {setting_id}, à rendre unique)",
            f"Motif : {pattern.name if pattern else '—'} — {CARCOLS_STEPS} pas, sequencerBpm = {bpm}",
            "",
            "Correspondance feux → os du modèle (positions dans le repère de la scène, en mètres) :",
        ]
        for index, light in enumerate(lights, start=1):
            world = context.studio.light_world(light)  # type: ignore[attr-defined]
            position = ", ".join(f"{v:.3f}" for v in world[0]) if world else "inconnue"
            lines.append(f"  siren{index}: {light.name} — couleur {light.color} — position ({position})")
        lines += ["", "Avertissements :", *[f"  - {i.message}" for i in issues if i.level != "info"]]
        report = folder / f"carcols_sirens_{slug}.txt"
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return [xml_path, report]


# --- VCF MISS-ELS -----------------------------------------------------------------------------


class MissElsAdapter(Adapter):
    info = AdapterInfo(
        "miss-els",
        "ELS FiveM : VCF MISS-ELS",
        "Fichier VCF au format documenté par MISS-ELS : un groupe lumineux = un « extra » du modèle.",
        [
            "Jusqu'à 12 extras (Extra01 à Extra12) avec couleur et éclairage d'environnement",
            "Motifs PRIMARY, SECONDARY et REARREDS (Flash : durée en ms, extras allumés)",
            "Tonalités SrnTone1 à SrnTone4 si un AudioString est renseigné",
        ],
        [
            "12 extras au maximum ; les « miscs » ne sont pas exportés "
            "(non documentés dans la page consultée)",
            "Une couleur par extra : un groupe aux couleurs mélangées prend la couleur majoritaire",
            "Le modèle doit posséder les extras correspondants (non produits par LeStitcheurFou Cars)",
            "Compatible MISS-ELS uniquement : les VCF d'autres ressources ELS diffèrent",
        ],
        [
            "Ressource MISS-ELS installée sur le serveur",
            "Modèle avec extras 1 à N",
            "Banques audio pour les sirènes",
        ],
        ["Groupes non vides", "Nombre d'extras", "Couleurs", "Durées des étapes", "Tonalités renseignées"],
    )

    def extras(self, variant: Variant) -> list[tuple[int, model.LightGroup, str]]:
        mapping = []
        for index, group in enumerate([g for g in variant.groups if g.light_ids][:ELS_MAX_EXTRAS], start=1):
            colors = [light.color for light in variant.lights if light.id in group.light_ids]
            color = max(set(colors), key=colors.count) if colors else "red"
            mapping.append((index, group, color if color in ELS_COLORS else "white"))
        return mapping

    def validate(self, context: ExportContext) -> list[ExportIssue]:
        variant = context.variant
        issues: list[ExportIssue] = []
        groups = [g for g in variant.groups if g.light_ids]
        if not groups:
            issues.append(
                ExportIssue("error", "Aucun groupe lumineux non vide : rien à associer à des extras.")
            )
        if len(groups) > ELS_MAX_EXTRAS:
            message = f"{len(groups)} groupes : seuls les {ELS_MAX_EXTRAS} premiers deviennent des extras."
            issues.append(ExportIssue("warning", message))
        for group in groups:
            colors = {light.color for light in variant.lights if light.id in group.light_ids}
            if len(colors) > 1:
                message = f"Groupe « {group.name} » : couleurs mélangées ({', '.join(sorted(colors))})."
                issues.append(ExportIssue("warning", message))
            if colors - ELS_COLORS:
                issues.append(
                    ExportIssue("warning", f"Groupe « {group.name} » : couleur non prise en charge (blanc).")
                )
        if _active_pattern(variant) is None:
            issues.append(ExportIssue("error", "Aucun motif à exporter dans PRIMARY."))
        tones = [m for m in variant.siren.modes if m.tone not in ("none", "horn")]
        if tones and not variant.siren.audio_strings:
            issues.append(
                ExportIssue(
                    "warning", "Sirènes sans AudioString : SrnTone exportés désactivés (AllowUse=false)."
                )
            )
        issues.append(
            ExportIssue(
                "info", "Nécessite un modèle avec les extras correspondants ; à tester sur un serveur."
            )
        )
        return issues

    @staticmethod
    def _flashes(pattern: Pattern | None, extra_of: dict[str, int], parent: ET.Element) -> None:
        if pattern is None:
            return
        for frame in pattern.frames:
            extras = sorted({extra_of[g] for g in frame.groups if g in extra_of})
            attributes = {"Duration": str(int(frame.duration_ms))}
            if extras:
                attributes["Extras"] = ",".join(str(e) for e in extras)
            ET.SubElement(parent, "Flash", attributes)
        ET.SubElement(parent, "Flash", {"Duration": "50"})  # étape vide finale (boucle plus fluide)

    def build_xml(self, context: ExportContext) -> str:
        variant = context.variant
        mapping = self.extras(variant)
        extra_of = {group.id: index for index, group, _ in mapping}
        root = ET.Element(
            "vcfroot", {"Description": variant.name, "Author": "LeStitcheurFou Cars", "Version": __version__}
        )
        override = ET.SubElement(root, "EOVERRIDE")
        for index, _group, color in mapping:
            ET.SubElement(
                override,
                f"Extra{index:02d}",
                {"IsElsControlled": "true", "AllowEnvLight": "true", "Color": color},
            )
        ET.SubElement(root, "STATIC")
        sounds = ET.SubElement(root, "SOUNDS")
        ET.SubElement(sounds, "MainHorn", {"AllowUse": "false"})
        ET.SubElement(sounds, "NineMode", {"AllowUse": "false"})
        tone_modes = [m for m in variant.siren.modes if m.tone not in ("none", "horn")][:4]
        for number in range(1, 5):
            mode = tone_modes[number - 1] if number <= len(tone_modes) else None
            audio = variant.siren.audio_strings.get(mode.key, "") if mode else ""
            attributes = {"AllowUse": "true" if audio else "false"}
            if audio:
                attributes["AudioString"] = audio
            ET.SubElement(sounds, f"SrnTone{number}", attributes)
        pattern_root = ET.SubElement(root, "PATTERN")
        primary = _active_pattern(variant)
        secondary = next((p for p in variant.patterns if p is not primary), None)
        rear_group = next((g for g in variant.groups if g.kind == "rear" and g.id in extra_of), None)
        rear = None
        if rear_group is not None:
            rear = Pattern(
                "rear", "Arrière", [model.PatternFrame(250, [rear_group.id]), model.PatternFrame(250, [])]
            )
        for tag, pattern in (("PRIMARY", primary), ("SECONDARY", secondary), ("REARREDS", rear)):
            stage = ET.SubElement(pattern_root, tag, {"IsEmergency": "true" if tag == "PRIMARY" else "false"})
            self._flashes(pattern, extra_of, stage)
        ET.indent(root)
        return ET.tostring(root, encoding="unicode")

    def export(self, context: ExportContext, folder: str | Path) -> list[Path]:
        self._ensure_exportable(context)
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        slug = _slug(context.resource_name)
        path = folder / f"{slug}.xml"
        header = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            "<!-- VCF MISS-ELS généré par LeStitcheurFou Cars : à tester -->\n"
        )
        path.write_text(header + self.build_xml(context) + "\n", encoding="utf-8")
        lines = [f"Extras attendus dans le modèle « {context.resource_name} » :"]
        for index, group, color in self.extras(context.variant):
            lines.append(
                f"  Extra{index:02d} ← groupe « {group.name} » ({len(group.light_ids)} feu(x), {color})"
            )
        report = folder / f"{slug}_extras.txt"
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return [path, report]


# --- ELS solo (non exportable) --------------------------------------------------------------------


class ClassicElsAdapter(Adapter):
    info = AdapterInfo(
        "els-classic",
        "ELS solo (LCPDFR)",
        "Emergency Lighting System pour GTA V solo.",
        [],
        ["12 extras au maximum, motifs prédéfinis du mod"],
        ["Mod ELS installé (solo, non compatible multijoueur)"],
        [],
        available=False,
        unavailable_reason=(
            "Export non proposé : aucune spécification publique et vérifiable du VCF de l'ELS solo n'a été "
            "trouvée (les motifs y sont des préréglages numérotés du mod). Utilisez l'export MISS-ELS "
            "(documenté) ou les données intermédiaires."
        ),
    )

    def validate(self, context: ExportContext) -> list[ExportIssue]:
        return [ExportIssue("error", self.info.unavailable_reason)]

    def export(self, context: ExportContext, folder: str | Path) -> list[Path]:
        raise AdapterError([self.info.unavailable_reason])


ADAPTERS: tuple[Adapter, ...] = (
    IntermediateAdapter(),
    CarcolsAdapter(),
    MissElsAdapter(),
    ClassicElsAdapter(),
)
ADAPTERS_BY_KEY = {a.info.key: a for a in ADAPTERS}
