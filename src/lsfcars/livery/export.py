"""Export des textures de livrée : PNG, TIFF, WEBP (sans perte), DDS (DXT1, DXT5, non compressé)
avec mipmaps, débordement des îlots, vérification relue et rapport de compatibilité.

La préparation « YTD » écrit un dossier de textures DDS et un manifeste destinés aux outils de
conversion GTA V (CodeWalker, OpenIV, Sollumz…). **Aucun fichier .ytd n'est produit** : le
logiciel ne dispose pas d'un convertisseur YTD vérifié.
"""

from __future__ import annotations

import io
import json
import math
import struct
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from lsfcars import __version__
from lsfcars.livery import raster
from lsfcars.livery.model import now_iso

FORMATS = {
    "png": ("PNG (sans perte, transparence)", ".png"),
    "tiff": ("TIFF (sans perte, LZW)", ".tif"),
    "webp": ("WEBP sans perte", ".webp"),
    "dds-dxt5": ("DDS DXT5 / BC3 (alpha) + mipmaps", ".dds"),
    "dds-dxt1": ("DDS DXT1 / BC1 (sans alpha) + mipmaps", ".dds"),
    "dds-rgba": ("DDS non compressé A8R8G8B8 + mipmaps", ".dds"),
}
LOSSLESS = {"png", "tiff", "webp", "dds-rgba"}


@dataclass
class ExportOptions:
    fmt: str = "png"
    width: int | None = None  # None : taille du document
    height: int | None = None
    alpha: bool = True
    mipmaps: bool = True
    padding: int = 8  # débordement des îlots UV (pixels de la texture exportée)


@dataclass
class ExportReport:
    path: str
    fmt: str
    width: int
    height: int
    has_alpha: bool
    size_bytes: int
    mip_levels: int
    verified: bool
    max_difference: int
    psnr: float
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        quality = "identique" if self.max_difference == 0 else f"PSNR {self.psnr:.1f} dB"
        return (
            f"{Path(self.path).name} — {self.width}×{self.height}, {self.mip_levels} niveau(x), "
            f"{self.size_bytes / 1024:.0f} Kio, relu : {quality}"
        )


def is_power_of_two(value: int) -> bool:
    return value > 0 and (value & (value - 1)) == 0


def compatibility(width: int, height: int, fmt: str, has_alpha: bool) -> list[str]:
    warnings = []
    if not (is_power_of_two(width) and is_power_of_two(height)):
        warnings.append(
            "Dimensions non puissances de deux : les mipmaps et la compression GTA V les supposent."
        )
    if max(width, height) > 4096:
        warnings.append(
            "Texture > 4096 px : mémoire vidéo importante en jeu, 2048 est généralement suffisant."
        )
    if fmt == "dds-dxt1" and has_alpha:
        warnings.append("DXT1 ne conserve pas la transparence : utilisez DXT5 pour une livrée transparente.")
    if fmt.startswith("dds") and (width % 4 or height % 4):
        warnings.append("Les formats compressés DXT exigent des dimensions multiples de 4.")
    return warnings


def prepare(array: np.ndarray, options: ExportOptions, coverage: np.ndarray | None = None) -> np.ndarray:
    """Redimensionne, ajoute le débordement des îlots et retire l'alpha si demandé."""
    image = array
    width = options.width or array.shape[1]
    height = options.height or array.shape[0]
    if coverage is not None and options.padding > 0:
        cover = coverage
        if cover.shape != array.shape[:2]:
            resized = Image.fromarray(cover.astype(np.uint8) * 255).resize(
                (array.shape[1], array.shape[0]), Image.NEAREST
            )
            cover = np.array(resized) > 0
        scale = array.shape[1] / max(width, 1)
        image = raster.dilate_colors(array, cover, int(math.ceil(options.padding * max(scale, 1.0))))
    if (width, height) != (array.shape[1], array.shape[0]):
        image = np.array(Image.fromarray(image, "RGBA").resize((width, height), Image.LANCZOS))
    if not options.alpha:
        image = image.copy()
        image[..., 3] = 255
    return np.ascontiguousarray(image)


def _levels(image: np.ndarray, mipmaps: bool, minimum: int = 4) -> list[Image.Image]:
    base = Image.fromarray(image, "RGBA")
    levels = [base]
    if not mipmaps:
        return levels
    w, h = base.size
    while min(w, h) // 2 >= minimum:
        w, h = max(w // 2, 1), max(h // 2, 1)
        levels.append(base.resize((w, h), Image.LANCZOS))
    return levels


def dds_bytes(image: np.ndarray, fmt: str, mipmaps: bool) -> tuple[bytes, int]:
    """Fichier DDS (en-tête classique) avec chaîne de mipmaps ; encodage DXT par Pillow."""
    pixel_format = {"dds-dxt5": "DXT5", "dds-dxt1": "DXT1"}.get(fmt)
    chunks: list[bytes] = []
    header = bytearray()
    levels = _levels(image, mipmaps)
    for index, level in enumerate(levels):
        buffer = io.BytesIO()
        if pixel_format:
            level.save(buffer, "DDS", pixel_format=pixel_format)
        else:
            level.save(buffer, "DDS")
        data = buffer.getvalue()
        if data[:4] != b"DDS " or data[84:88] == b"DX10":
            raise ValueError("En-tête DDS inattendu (DX10) : export impossible dans ce format.")
        if index == 0:
            header = bytearray(data[:128])
        chunks.append(data[128:])
    if len(levels) > 1:
        struct.pack_into("<I", header, 8, struct.unpack_from("<I", header, 8)[0] | 0x20000)  # MIPMAPCOUNT
        struct.pack_into("<I", header, 28, len(levels))
        caps = (
            struct.unpack_from("<I", header, 108)[0] | 0x8 | 0x400000 | 0x1000
        )  # COMPLEX | MIPMAP | TEXTURE
        struct.pack_into("<I", header, 108, caps)
    return bytes(header) + b"".join(chunks), len(levels)


def write(image: np.ndarray, path: Path, fmt: str, mipmaps: bool = True) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    pil = Image.fromarray(image, "RGBA")
    if fmt == "png":
        pil.save(path, "PNG")
        return 1
    if fmt == "tiff":
        pil.save(path, "TIFF", compression="tiff_lzw")
        return 1
    if fmt == "webp":
        pil.save(path, "WEBP", lossless=True, exact=True, quality=100)
        return 1
    if fmt.startswith("dds"):
        data, levels = dds_bytes(image, fmt, mipmaps)
        path.write_bytes(data)
        return levels
    raise ValueError(f"Format d'export inconnu : {fmt}")


def verify(path: Path, expected: np.ndarray) -> tuple[int, float]:
    """Relit le fichier écrit et le compare à l'image attendue : (écart maximal, PSNR en dB)."""
    with Image.open(path) as image:
        read = np.array(image.convert("RGBA"), np.uint8)
    if read.shape != expected.shape:
        return 255, 0.0
    diff = read.astype(np.int16) - expected.astype(np.int16)
    mse = float(np.mean(diff.astype(np.float64) ** 2))
    psnr = float("inf") if mse == 0 else 10 * math.log10(255**2 / mse)
    return int(np.abs(diff).max()), psnr


def export_texture(
    array: np.ndarray, path: str | Path, options: ExportOptions, coverage: np.ndarray | None = None
) -> ExportReport:
    path = Path(path)
    if options.fmt not in FORMATS:
        raise ValueError(f"Format d'export inconnu : {options.fmt}")
    suffix = FORMATS[options.fmt][1]
    known = {ext for _label, ext in FORMATS.values()} | {".tiff", ".jpg"}
    stem = path.stem if path.suffix.lower() in known else path.name
    path = path.with_name(stem + suffix)
    image = prepare(array, options, coverage)
    expected = image.copy()
    if options.fmt == "dds-dxt1":
        expected[..., 3] = 255
    levels = write(image, path, options.fmt, options.mipmaps)
    max_diff, psnr = verify(path, expected)
    has_alpha = bool(options.alpha and (image[..., 3] < 255).any())
    lossless = options.fmt in LOSSLESS
    report = ExportReport(
        str(path),
        options.fmt,
        image.shape[1],
        image.shape[0],
        has_alpha,
        path.stat().st_size,
        levels,
        verified=(max_diff == 0) if lossless else psnr >= 30.0,
        max_difference=max_diff,
        psnr=psnr,
        warnings=compatibility(image.shape[1], image.shape[0], options.fmt, has_alpha),
    )
    if lossless and max_diff:
        report.warnings.append("La relecture diffère de l'image composée : fichier à vérifier.")
    if not lossless:
        report.notes.append("Compression DXT avec perte : écart attendu, vérifié par PSNR (≥ 30 dB).")
    return report


def prepare_ytd(
    folder: str | Path,
    dictionary: str,
    textures: dict[str, np.ndarray],
    options: ExportOptions,
    coverage: np.ndarray | None = None,
) -> tuple[Path, list[ExportReport]]:
    """Dossier prêt pour un outil de conversion YTD : DDS + manifeste + mode d'emploi."""
    target = Path(folder) / f"{dictionary}_ytd"
    target.mkdir(parents=True, exist_ok=True)
    dds_options = ExportOptions(
        fmt=options.fmt if options.fmt.startswith("dds") else "dds-dxt5",
        width=options.width,
        height=options.height,
        alpha=options.alpha,
        mipmaps=True,
        padding=options.padding,
    )
    reports = [
        export_texture(array, target / name, dds_options, coverage) for name, array in textures.items()
    ]
    manifest = {
        "format": "lsf-ytd-preparation",
        "version": 1,
        "generator": f"LeStitcheurFou Cars {__version__}",
        "created_at": now_iso(),
        "dictionary": dictionary,
        "textures": [asdict(r) | {"name": Path(r.path).stem} for r in reports],
        "ytd_written": False,
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (target / "LISEZMOI.txt").write_text(
        "Préparation de dictionnaire de textures (YTD) — LeStitcheurFou Cars\n\n"
        f"Dictionnaire visé : {dictionary}.ytd\n"
        "Ce dossier contient des textures DDS avec mipmaps. AUCUN fichier .ytd n'a été produit :\n"
        "créez le dictionnaire avec un outil dédié (CodeWalker, OpenIV, Sollumz pour Blender…) en y\n"
        "ajoutant ces fichiers sous le même nom. Vérifiez en jeu l'affichage de la livrée : aucune\n"
        "compatibilité n'est garantie.\n",
        encoding="utf-8",
    )
    return target, reports
