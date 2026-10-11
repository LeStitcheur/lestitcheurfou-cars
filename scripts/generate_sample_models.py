"""Génère les modèles de test libres de droits ``samples/vehicule_test.(glb|obj)``.

Véhicule volontairement simplifié (boîtes + cylindres), créé de zéro : aucune
donnée GTA V ni modèle tiers. Usage : ``python scripts/generate_sample_models.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh

SAMPLES = Path(__file__).resolve().parents[1] / "samples"

BLEU = (30, 144, 255, 255)
VITRE = (35, 45, 58, 255)
PNEU = (22, 22, 24, 255)
JANTE = (190, 195, 205, 255)
PHARE = (255, 244, 214, 255)


def _part(mesh: trimesh.Trimesh, color: tuple[int, int, int, int], offset) -> trimesh.Trimesh:
    mesh.apply_translation(offset)
    mesh.unmerge_vertices()  # ombrage à facettes nettes
    mesh.visual.vertex_colors = np.tile(color, (len(mesh.vertices), 1))
    return mesh


def build_scene() -> trimesh.Scene:
    scene = trimesh.Scene()
    # Axe avant du véhicule : +Z ; hauteur : +Y ; longueur ≈ 4,4 m.
    scene.add_geometry(
        _part(trimesh.creation.box((1.8, 0.6, 4.4)), BLEU, (0, 0.6, 0)), node_name="carrosserie"
    )
    scene.add_geometry(
        _part(trimesh.creation.box((1.6, 0.5, 2.1)), VITRE, (0, 1.15, -0.25)),
        node_name="habitacle",
    )
    for side, x in (("gauche", 0.86), ("droite", -0.86)):
        scene.add_geometry(
            _part(trimesh.creation.box((0.35, 0.14, 0.05)), PHARE, (x * 0.75, 0.7, 2.2)),
            node_name=f"phare_{side}",
        )
    rotation = trimesh.transformations.rotation_matrix(np.pi / 2, (0, 1, 0))
    for label, z in (("avant", 1.4), ("arriere", -1.4)):
        for side, x in (("gauche", 0.86), ("droite", -0.86)):
            pneu = trimesh.creation.cylinder(radius=0.36, height=0.26, sections=24)
            pneu.apply_transform(rotation)
            scene.add_geometry(_part(pneu, PNEU, (x, 0.36, z)), node_name=f"roue_{label}_{side}")
            jante = trimesh.creation.cylinder(radius=0.22, height=0.28, sections=16)
            jante.apply_transform(rotation)
            scene.add_geometry(_part(jante, JANTE, (x, 0.36, z)), node_name=f"jante_{label}_{side}")
    return scene


def main() -> None:
    SAMPLES.mkdir(exist_ok=True)
    scene = build_scene()
    glb = SAMPLES / "vehicule_test.glb"
    obj = SAMPLES / "vehicule_test.obj"
    scene.export(glb)
    scene.export(obj, include_color=True, include_normals=True)
    for path in (glb, obj):
        print(f"{path.relative_to(SAMPLES.parent)} : {path.stat().st_size} octets")


if __name__ == "__main__":
    main()
