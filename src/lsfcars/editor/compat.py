"""Préservation de la compatibilité FiveM : avertissements d'action et rapport technique.

Le rapport décrit ce qui a été modifié par rapport aux données GTA V d'origine (os, pivots,
hiérarchie, géométrie, UV…). Il ne valide **pas** la jouabilité : aucun export GTA V n'existe
encore dans LeStitcheurFou Cars, et un véhicule modifié doit être exporté puis testé en jeu.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from lsfcars.editor import vehicle
from lsfcars.scene.graph import NodeKind, SceneNode

DISCLAIMER = (
    "Ce rapport compare le projet aux données GTA V importées. Il ne garantit pas qu'un véhicule "
    "modifié sera jouable : un export et une validation en jeu restent indispensables."
)

ACTION_RISKS = {
    "delete_wheel": "Suppression d'une roue : le véhicule ne pourra plus rouler correctement dans FiveM.",
    "delete": "Supprimer un os ou une pièce d'origine peut casser l'animation des portes, des roues ou "
    "des feux dans FiveM.",
    "pivot": "Le pivot d'un os animé (roue, porte, capot, coffre, volant) détermine sa rotation en jeu : "
    "le modifier peut rendre l'animation incorrecte.",
    "hierarchy": "Modifier la hiérarchie des os d'origine peut rendre le modèle incompatible avec FiveM.",
    "replace_mobile": "Remplacer une pièce mobile impose de vérifier son pivot et son axe de rotation.",
    "collision": "Ce composant semble technique (collision, LOD, aide) : le modifier peut fausser la "
    "physique en jeu.",
    "uv": "Des UV invalides empêchent l'affichage correct des textures (correction : projection UV).",
    "rename": "Les noms d'os sont utilisés par le jeu (portes, roues, feux…) : un os renommé peut ne "
    "plus fonctionner dans FiveM.",
    "scale": "Une mise à l'échelle non uniforme d'une pièce d'origine peut déformer les collisions et "
    "les points d'ancrage dans FiveM.",
    "geometry": "La géométrie d'une pièce d'origine a été modifiée : un réexport sera nécessaire.",
}


@dataclass
class CompatIssue:
    level: str  # info / warning / error
    code: str
    message: str
    node_id: str | None = None

    @property
    def label(self) -> str:
        return {"info": "Information", "warning": "Avertissement", "error": "Erreur"}[self.level]


def _subtree(scene, node_ids: Iterable[str]) -> list[SceneNode]:  # type: ignore[no-untyped-def]
    seen: dict[str, SceneNode] = {}
    for node_id in node_ids:
        if node_id in scene:
            for node in scene.subtree(node_id):
                seen[node.id] = node
    return list(seen.values())


def action_risks(session, action: str, node_ids: Iterable[str]) -> list[str]:  # type: ignore[no-untyped-def]
    """Avertissements à afficher pour une action sur ces nœuds (liste vide : aucun risque connu)."""
    scene = session.scene
    node_ids = list(node_ids)
    nodes = _subtree(scene, node_ids)
    direct = [scene.nodes[i] for i in node_ids if i in scene]
    risks: list[str] = []
    if action == "delete":
        if any(vehicle.is_wheel_name(n.name) and n.kind is not NodeKind.ANCHOR for n in nodes):
            risks.append(ACTION_RISKS["delete_wheel"])
        if any(vehicle.is_gta_original(n) for n in nodes):
            risks.append(ACTION_RISKS["delete"])
    elif action == "pivot":
        if any(vehicle.is_essential_bone(n) for n in direct):
            risks.append(ACTION_RISKS["pivot"])
    elif action in ("reparent", "group", "ungroup", "hierarchy"):
        if any(n.extra.get("gta", {}).get("role") == "bone" for n in nodes):
            risks.append(ACTION_RISKS["hierarchy"])
    elif action == "replace":
        if any(vehicle.role(scene, n) == vehicle.ROLE_MOBILE for n in direct):
            risks.append(ACTION_RISKS["replace_mobile"])
        if any(vehicle.is_gta_original(n) for n in direct):
            risks.append(ACTION_RISKS["delete"])
    elif action == "geometry":
        if any(vehicle.role(scene, n) == vehicle.ROLE_TECHNICAL for n in direct):
            risks.append(ACTION_RISKS["collision"])
        if any(vehicle.is_gta_original(n) for n in direct):
            risks.append(ACTION_RISKS["geometry"])
    elif action == "rename":
        if any(n.extra.get("gta", {}).get("role") == "bone" for n in direct):
            risks.append(ACTION_RISKS["rename"])
    elif action == "scale":
        if any(vehicle.is_gta_original(n) for n in nodes):
            risks.append(ACTION_RISKS["scale"])
    elif action == "uv":
        risks.append(ACTION_RISKS["uv"])
    return risks


def _bone_issues(scene, root: SceneNode) -> list[CompatIssue]:  # type: ignore[no-untyped-def]
    issues: list[CompatIssue] = []
    bones = [n for n in scene.walk(root.id) if n.extra.get("gta", {}).get("role") == "bone"]
    indices = sorted(i for i in (b.extra["gta"].get("bone_index") for b in bones) if isinstance(i, int))
    if indices:
        missing = sorted(set(range(indices[-1] + 1)) - set(indices))
        if missing:
            listed = ", ".join(map(str, missing[:8]))
            issues.append(
                CompatIssue(
                    "error",
                    "bones_deleted",
                    f"{root.name} : os d'origine supprimé(s) (indices {listed}).",
                    root.id,
                )
            )
    if not any(vehicle.is_wheel_name(b.name) for b in bones):
        issues.append(
            CompatIssue("warning", "no_wheel_bones", f"{root.name} : aucun os de roue (wheel_*).", root.id)
        )
    for bone in bones:
        gta = bone.extra["gta"]
        original = gta.get("translation")
        if original is not None and not np.allclose(bone.transform.translation, original, atol=1e-3):
            level = "error" if vehicle.is_essential_bone(bone) else "warning"
            issues.append(
                CompatIssue(level, "pivot_moved", f"Pivot de l'os « {bone.name} » déplacé.", bone.id)
            )
        parent = scene.get(bone.parent_id)
        parent_gta = parent.extra.get("gta", {}) if parent else {}
        parent_index = -1 if parent_gta.get("role") == "root" else parent_gta.get("bone_index")
        if parent_index != gta.get("parent_index", -1):
            issues.append(
                CompatIssue("error", "hierarchy", f"Hiérarchie modifiée : os « {bone.name} ».", bone.id)
            )
    for node in scene.walk(root.id):
        if node.kind is NodeKind.MESH and not vehicle.is_gta_original(node):
            issues.append(
                CompatIssue(
                    "info",
                    "added_part",
                    f"Pièce ajoutée « {node.name} » : à rattacher à un os lors d'un futur export.",
                    node.id,
                )
            )
    return issues


def compatibility_report(session, vehicle_type: str | None = None) -> list[CompatIssue]:  # type: ignore[no-untyped-def]
    """Rapport technique de compatibilité FiveM du projet."""
    scene = session.scene
    issues: list[CompatIssue] = [CompatIssue("info", "disclaimer", DISCLAIMER)]
    roots = [n for n in scene.walk() if n.extra.get("gta", {}).get("role") == "root"]
    if not roots:
        issues.append(
            CompatIssue(
                "info",
                "no_gta",
                "Aucun modèle GTA V importé : seules les vérifications génériques s'appliquent.",
            )
        )
    for root in roots:
        issues += _bone_issues(scene, root)
    for node in scene.walk():
        gta = node.extra.get("gta", {})
        if node.extra.get("edited_geometry") and gta:
            issues.append(
                CompatIssue(
                    "warning", "geometry", f"Géométrie d'origine modifiée : « {node.name} ».", node.id
                )
            )
        if node.extra.get("uv_status") == "invalid":
            issues.append(CompatIssue("error", "uv", f"UV invalides : « {node.name} ».", node.id))
        scale = node.transform.scale
        original = gta.get("scale") if gta.get("role") == "bone" else [1.0, 1.0, 1.0]
        changed = original is None or not np.allclose(scale, original, atol=1e-4)
        if gta and changed and len({round(v, 5) for v in scale}) > 1:  # échelle d'origine : pas d'alerte
            issues.append(
                CompatIssue("warning", "scale", f"Échelle non uniforme : « {node.name} ».", node.id)
            )
        if gta and any(v < 0 for v in scale):
            issues.append(
                CompatIssue("error", "mirror_scale", f"Échelle négative : « {node.name} ».", node.id)
            )
    if roots:
        issues.append(
            CompatIssue(
                "info", "collisions", "Collisions (.ybn) non décodées : modifications non vérifiables."
            )
        )
        issues.append(
            CompatIssue(
                "info", "lod", "Seul le niveau de détail haut est importé : LOD à régénérer à l'export."
            )
        )
    axes = vehicle.VehicleAxes.from_project(session.project.editor)
    report = vehicle.find_wheels(session, axes, vehicle_type or session.project.vehicle_type.value)
    issues += [CompatIssue("warning", "wheels", message) for message in report.messages]
    return issues


def summary(issues: list[CompatIssue]) -> dict[str, int]:
    return {level: sum(1 for i in issues if i.level == level) for level in ("error", "warning", "info")}
