"""Importe les ressources de marque partagées avec LeStitcheur Control.

Source : le dépôt local de LeStitcheur Control (même auteur), par défaut ``../lestitcheur``.
Produit dans ``src/lsfcars/resources`` :

- ``fonts/`` : DM Sans (texte) et Barlow Condensed (marque), convertis en TTF (OFL 1.1) ;
- ``icons/`` : icônes Lucide (ISC) en SVG ``stroke="currentColor"`` ;
- ``brand/emblem.svg`` : emblème LSF de la suite LeStitcheur ;
- les licences correspondantes.

Usage : ``python scripts/import_brand_assets.py [chemin/vers/lestitcheur]``
Nécessite ``fonttools`` et ``brotli`` (outils de développement uniquement).
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "src" / "lsfcars" / "resources"

FONTS = {
    "dm-sans": ("dm-sans-latin-{w}-normal.woff2", "DMSans-{w}.ttf", (400, 500, 600, 700)),
    "barlow-condensed": (
        "barlow-condensed-latin-{w}-normal.woff2",
        "BarlowCondensed-{w}.ttf",
        (600, 700),
    ),
}

ICONS = [
    "activity",
    "ambulance",
    "arrow-up-right",
    "bell",
    "blocks",
    "box",
    "camera",
    "car",
    "check",
    "chevron-down",
    "chevron-right",
    "circle-check",
    "circle-x",
    "clock",
    "copy",
    "copy-plus",
    "cuboid",
    "download",
    "eye",
    "eye-off",
    "file-box",
    "folder",
    "folder-open",
    "frame",
    "gauge",
    "grid-3x3",
    "group",
    "heart-pulse",
    "history",
    "home",
    "image",
    "import",
    "info",
    "layers",
    "layout-grid",
    "leaf",
    "loader-circle",
    "lock",
    "lock-open",
    "maximize-2",
    "minus",
    "mouse-pointer-2",
    "move",
    "move-3d",
    "orbit",
    "package",
    "paint-bucket",
    "palette",
    "panel-left-close",
    "panel-left-open",
    "pencil",
    "plus",
    "redo-2",
    "refresh-cw",
    "rotate-3d",
    "save",
    "scale-3d",
    "scan",
    "scroll-text",
    "search",
    "settings",
    "shapes",
    "shield",
    "siren",
    "sliders-horizontal",
    "sparkles",
    "square",
    "square-dashed",
    "sun",
    "trash-2",
    "triangle-alert",
    "undo-2",
    "ungroup",
    "upload",
    "video",
    "x",
]

ELEMENT = re.compile(r'\[\s*"(\w+)",\s*\{([^}]*)\}\s*\]')
ATTRIBUTE = re.compile(r'(\w+):\s*"([^"]*)"')
ALIAS = re.compile(r"export \{ default \} from '\./([\w-]+\.js)'")


def _kebab(name: str) -> str:
    return re.sub(r"([A-Z])", lambda m: "-" + m.group(1).lower(), name)


def convert_fonts(source: Path) -> None:
    from fontTools.ttLib import TTFont

    target = RESOURCES / "fonts"
    target.mkdir(parents=True, exist_ok=True)
    for package, (pattern, output, weights) in FONTS.items():
        package_dir = source / "node_modules" / "@fontsource" / package
        for weight in weights:
            font = TTFont(package_dir / "files" / pattern.format(w=weight))
            font.flavor = None
            font.save(target / output.format(w=weight))
        name = "".join(part.capitalize() for part in package.split("-"))
        shutil.copyfile(package_dir / "LICENSE", target / f"OFL-{name}.txt")
    print(f"Polices : {len(list(target.glob('*.ttf')))} fichiers TTF")


def lucide_svg(js_source: str) -> str:
    elements = []
    for tag, raw_attributes in ELEMENT.findall(js_source):
        attributes = " ".join(
            f'{_kebab(key)}="{value}"' for key, value in ATTRIBUTE.findall(raw_attributes) if key != "key"
        )
        elements.append(f"<{tag} {attributes}/>")
    if not elements:
        raise ValueError("aucun élément SVG trouvé")
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" '
        'stroke-linejoin="round">' + "".join(elements) + "</svg>\n"
    )


def extract_icons(source: Path) -> None:
    package = source / "node_modules" / "lucide-react"
    target = RESOURCES / "icons"
    target.mkdir(parents=True, exist_ok=True)
    icons_dir = package / "dist" / "esm" / "icons"
    for name in ICONS:
        js = (icons_dir / f"{name}.js").read_text(encoding="utf-8")
        alias = ALIAS.search(js)  # ex. home.js -> house.js
        if alias:
            js = (icons_dir / alias.group(1)).read_text(encoding="utf-8")
        (target / f"{name}.svg").write_text(lucide_svg(js), encoding="utf-8")
    shutil.copyfile(package / "LICENSE", target / "LICENSE-lucide.txt")
    print(f"Icônes : {len(ICONS)} SVG")


def copy_brand(source: Path) -> None:
    target = RESOURCES / "brand"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source / "public" / "emblem.svg", target / "emblem.svg")
    print("Emblème : brand/emblem.svg")


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "lestitcheur"
    if not (source / "package.json").is_file():
        raise SystemExit(f"Dépôt LeStitcheur Control introuvable : {source}")
    convert_fonts(source)
    extract_icons(source)
    copy_brand(source)


if __name__ == "__main__":
    main()
