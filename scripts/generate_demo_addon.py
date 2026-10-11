"""Génère l'addon FiveM de démonstration ``samples/fivem/lsfdemo`` (contenu original, libre).

Petit véhicule synthétique (.yft), son dictionnaire de textures (.ytd), ses métadonnées
(vehicles, handling, carvariations, carcols) et son fxmanifest.lua. Aucune donnée GTA V ni
ressource tierce : il sert aux tests, au test de démarrage et à la découverte du
Vehicle Import Studio.

Usage : ``python scripts/generate_demo_addon.py``
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lsfcars.fivem.synthetic import write_demo_addon  # noqa: E402

TARGET = ROOT / "samples" / "fivem" / "lsfdemo"


def main() -> None:
    if TARGET.exists():
        shutil.rmtree(TARGET)
    write_demo_addon(TARGET)
    for path in sorted(TARGET.rglob("*")):
        if path.is_file():
            print(f"{path.relative_to(ROOT).as_posix()}  ({path.stat().st_size} octets)")


if __name__ == "__main__":
    main()
