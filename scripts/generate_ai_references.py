"""Génère les images de référence de démonstration d'AI Vehicle Creator.

Rendus orthographiques (profil gauche, avant, arrière, dessus) et trois quarts du véhicule
d'essai original ``samples/vehicule_livree.glb`` (aucun véhicule réel, aucune marque), sur fond
uni. Usage : python scripts/generate_ai_references.py
"""

from __future__ import annotations

from pathlib import Path

import trimesh

from lsfcars.ai import raster3d

ROOT = Path(__file__).resolve().parents[1]
VIEWS = {
    "left": "demo_profil_gauche.png",
    "front": "demo_avant.png",
    "back": "demo_arriere.png",
    "top": "demo_dessus.png",
    "three_quarter": "demo_trois_quarts.png",
}


def main() -> None:
    meshes = raster3d.from_trimesh_scene(trimesh.load(ROOT / "samples" / "vehicule_livree.glb"))
    folder = ROOT / "samples" / "references"
    folder.mkdir(parents=True, exist_ok=True)
    for view, name in VIEWS.items():
        image = raster3d.render(meshes, view, 768, background=(232, 234, 238))
        image.save(folder / name, optimize=True)
        print(folder / name)


if __name__ == "__main__":
    main()
