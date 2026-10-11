"""Bibliothèque locale de logos : emblèmes originaux intégrés et logos importés (PNG, SVG, JPG, WEBP).

Chaque logo enregistre auteur, source, licence et catégorie. Les emblèmes intégrés sont des
formes géométriques **générées par le logiciel** (aucun logo protégé, aucune marque réelle).
Un logo importé sans licence renseignée reste utilisable mais est signalé dans le registre de
provenance du document ; aucune vérification n'a valeur de garantie juridique.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from lsfcars.core.logging_setup import get_logger
from lsfcars.livery.model import now_iso

log = get_logger(__name__)

CATEGORIES = {
    "police": "Police",
    "ems": "Secours médicaux",
    "fire": "Pompiers",
    "racing": "Course",
    "generic": "Générique",
    "personal": "Personnel",
}
IMPORT_FORMATS = {".png": "png", ".svg": "svg", ".jpg": "jpg", ".jpeg": "jpg", ".webp": "webp"}
BUILTIN_LICENSE = "Original LeStitcheurFou Cars — libre d'utilisation dans vos créations"
BUILTIN_AUTHOR = "LeStitcheurFou Cars"


class LogoError(Exception):
    pass


@dataclass
class LogoEntry:
    id: str
    name: str
    category: str
    author: str
    source: str
    license: str
    file: str
    format: str
    builtin: bool = False
    created_at: str = field(default_factory=now_iso)

    def provenance(self) -> dict:
        return {
            "logo_id": self.id,
            "name": self.name,
            "author": self.author,
            "source": self.source,
            "license": self.license,
            "category": self.category,
            "builtin": self.builtin,
        }


def default_root() -> Path:
    from lsfcars.core.paths import app_data_dir

    return app_data_dir() / "logos"


def blob_key(data: bytes) -> str:
    return "blob-" + hashlib.sha256(data).hexdigest()[:24]


# --- Emblèmes originaux (SVG générés) -------------------------------------------------------

WHITE, BLUE, DARK = "#F3F6FC", "#2563EB", "#0B0E14"


def _svg(body: str, size: int = 256) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 256 256">'
        f"{body}</svg>"
    )


def _star(cx: float, cy: float, outer: float, inner: float, points: int, rotation: float = -90) -> str:
    coords = []
    for i in range(points * 2):
        r = outer if i % 2 == 0 else inner
        a = math.radians(rotation + i * 180 / points)
        coords.append(f"{cx + r * math.cos(a):.1f},{cy + r * math.sin(a):.1f}")
    return " ".join(coords)


def _star6_badge() -> str:
    tips = "".join(
        f'<circle cx="{128 + 112 * math.cos(math.radians(-90 + i * 60)):.1f}" '
        f'cy="{128 + 112 * math.sin(math.radians(-90 + i * 60)):.1f}" r="10" fill="{WHITE}" '
        f'stroke="{DARK}" stroke-width="4"/>'
        for i in range(6)
    )
    return _svg(
        f'<polygon points="{_star(128, 128, 112, 60, 6)}" fill="{WHITE}" stroke="{DARK}" stroke-width="6"/>'
        f'<circle cx="128" cy="128" r="44" fill="{BLUE}" stroke="{DARK}" stroke-width="5"/>{tips}'
    )


def _wings() -> str:
    feathers = "".join(
        f'<path d="M{128 + s * 40} {108 + i * 18} L{128 + s * (120 - i * 14)} {96 + i * 22} '
        f'L{128 + s * (112 - i * 14)} {112 + i * 22} L{128 + s * 40} {120 + i * 18} Z" fill="{WHITE}"/>'
        for s in (-1, 1)
        for i in range(3)
    )
    return _svg(
        f'<circle cx="128" cy="128" r="34" fill="{BLUE}" stroke="{WHITE}" stroke-width="8"/>{feathers}'
    )


def _chevrons() -> str:
    return _svg(
        "".join(
            f'<path d="M24 {200 - i * 60} L128 {120 - i * 60} L232 {200 - i * 60} L232 {236 - i * 60} '
            f'L128 {156 - i * 60} L24 {236 - i * 60} Z" fill="{WHITE}"/>'
            for i in range(3)
        )
    )


def _checker_flag() -> str:
    cells = "".join(
        f'<rect x="{32 + c * 34}" y="{28 + r * 34}" width="34" height="34" '
        f'fill="{WHITE if (r + c) % 2 == 0 else DARK}"/>'
        for r in range(4)
        for c in range(6)
    )
    return _svg(f'<rect x="20" y="20" width="12" height="220" fill="{WHITE}"/>{cells}')


def _builtin_svgs() -> list[tuple[str, str, str, str]]:
    """(identifiant, nom, catégorie, SVG) des emblèmes intégrés."""
    return [
        ("lsf-star6-badge", "Insigne étoile à six branches", "police", _star6_badge()),
        (
            "lsf-star5-ring",
            "Étoile à cinq branches cerclée",
            "police",
            _svg(
                f'<circle cx="128" cy="128" r="118" fill="{DARK}" stroke="{WHITE}" stroke-width="10"/>'
                f'<polygon points="{_star(128, 132, 92, 38, 5)}" fill="{WHITE}"/>'
            ),
        ),
        (
            "lsf-shield",
            "Bouclier à chevron",
            "police",
            _svg(
                f'<path d="M128 10 L232 44 L222 150 Q206 214 128 246 Q50 214 34 150 L24 44 Z" fill="{BLUE}" '
                f'stroke="{WHITE}" stroke-width="10"/>'
                f'<path d="M60 150 L128 96 L196 150 L196 178 L128 124 L60 178 Z" fill="{WHITE}"/>'
            ),
        ),
        (
            "lsf-medical-cross",
            "Croix de secours (bleue)",
            "ems",
            _svg(
                f'<rect x="88" y="16" width="80" height="224" rx="18" fill="{BLUE}" '
                f'stroke="{WHITE}" stroke-width="10"/>'
                f'<rect x="16" y="88" width="224" height="80" rx="18" fill="{BLUE}" '
                f'stroke="{WHITE}" stroke-width="10"/>'
                f'<rect x="93" y="93" width="70" height="70" fill="{BLUE}"/>'
            ),
        ),
        (
            "lsf-flame",
            "Flamme stylisée",
            "fire",
            _svg(
                '<path d="M128 8 C150 60 210 90 204 160 C200 214 166 246 128 248 C90 246 56 214 52 164 '
                'C48 120 78 96 92 64 C100 96 112 108 124 112 C118 70 112 40 128 8 Z" fill="#F59E0B"/>'
                '<path d="M128 112 C140 140 172 156 168 196 C166 224 148 240 128 240 C108 240 90 224 88 198 '
                'C86 172 104 160 112 140 C118 156 124 162 130 164 C126 146 122 130 128 112 Z" '
                'fill="#FDE68A"/>'
            ),
        ),
        ("lsf-wings", "Ailes d'intervention", "generic", _wings()),
        ("lsf-chevrons", "Triple chevron", "generic", _chevrons()),
        ("lsf-checker-flag", "Drapeau à damier", "racing", _checker_flag()),
        (
            "lsf-unit-ring",
            "Cercle d'unité",
            "generic",
            _svg(
                f'<circle cx="128" cy="128" r="112" fill="none" stroke="{WHITE}" stroke-width="18"/>'
                f'<circle cx="128" cy="128" r="80" fill="none" stroke="{BLUE}" stroke-width="10"/>'
            ),
        ),
        (
            "lsf-bolt",
            "Éclair",
            "racing",
            _svg(
                f'<path d="M150 8 L52 148 L118 148 L96 248 L204 100 L136 100 Z" fill="#38BDF8" '
                f'stroke="{DARK}" stroke-width="6"/>'
            ),
        ),
    ]


class LogoLibrary:
    """Index JSON + fichiers dans le dossier de données de l'utilisateur."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self._index = self.root / "index.json"
        self._entries: dict[str, LogoEntry] = {}
        self._load()

    def _load(self) -> None:
        if not self._index.is_file():
            return
        try:
            raw = json.loads(self._index.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Index des logos illisible : %s", exc)
            return
        for item in raw.get("logos", []):
            try:
                entry = LogoEntry(**item)
            except TypeError:
                continue
            self._entries[entry.id] = entry

    def _save(self) -> None:
        payload = {"version": 1, "logos": [asdict(e) for e in self._entries.values()]}
        tmp = self._index.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self._index)

    def ensure_builtins(self) -> int:
        created = 0
        for logo_id, name, category, svg in _builtin_svgs():
            path = self.root / f"{logo_id}.svg"
            if logo_id in self._entries and path.is_file():
                continue
            path.write_text(svg, encoding="utf-8")
            self._entries[logo_id] = LogoEntry(
                logo_id,
                name,
                category,
                BUILTIN_AUTHOR,
                "Généré par LeStitcheurFou Cars",
                BUILTIN_LICENSE,
                path.name,
                "svg",
                True,
            )
            created += 1
        if created:
            self._save()
        return created

    def entries(self, category: str | None = None, text: str = "") -> list[LogoEntry]:
        text = text.strip().lower()
        result = [
            e
            for e in self._entries.values()
            if (category in (None, "", e.category)) and (not text or text in e.name.lower())
        ]
        return sorted(result, key=lambda e: (not e.builtin, e.category, e.name.lower()))

    def get(self, logo_id: str) -> LogoEntry | None:
        return self._entries.get(logo_id)

    def data(self, logo_id: str) -> bytes:
        entry = self._entries.get(logo_id)
        if entry is None:
            raise LogoError(f"Logo inconnu : {logo_id}")
        try:
            return (self.root / entry.file).read_bytes()
        except OSError as exc:
            raise LogoError(f"Fichier du logo « {entry.name} » illisible : {exc}") from exc

    def import_file(
        self,
        source: str | Path,
        name: str = "",
        category: str = "personal",
        author: str = "",
        origin: str = "",
        license_text: str = "",
    ) -> LogoEntry:
        """Copie un logo dans la bibliothèque (le fichier d'origine n'est pas modifié)."""
        from lsfcars.livery.render2d import is_svg, source_size

        source = Path(source)
        fmt = IMPORT_FORMATS.get(source.suffix.lower())
        if fmt is None:
            raise LogoError(
                f"Format non pris en charge : {source.suffix or 'sans extension'} (PNG, SVG, JPG, WEBP)."
            )
        try:
            data = source.read_bytes()
        except OSError as exc:
            raise LogoError(f"Lecture impossible : {exc}") from exc
        if fmt == "svg":
            if not is_svg(data):
                raise LogoError("Le fichier SVG n'est pas valide.")
        else:
            from PySide6.QtCore import QByteArray
            from PySide6.QtGui import QImage

            if QImage.fromData(QByteArray(data)).isNull():
                raise LogoError("Image illisible ou format corrompu.")
        source_size(data)
        logo_id = "user-" + hashlib.sha256(data).hexdigest()[:16]
        target = self.root / f"{logo_id}{source.suffix.lower()}"
        shutil.copyfile(source, target)
        entry = LogoEntry(
            logo_id,
            name.strip() or source.stem,
            category if category in CATEGORIES else "personal",
            author.strip(),
            origin.strip() or str(source.name),
            license_text.strip(),
            target.name,
            fmt,
        )
        self._entries[logo_id] = entry
        self._save()
        return entry

    def remove(self, logo_id: str) -> bool:
        entry = self._entries.get(logo_id)
        if entry is None or entry.builtin:
            return False
        (self.root / entry.file).unlink(missing_ok=True)
        del self._entries[logo_id]
        self._save()
        return True
