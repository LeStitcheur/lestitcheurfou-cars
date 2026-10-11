"""Collecte d'informations de diagnostic (versions, système, OpenGL)."""

from __future__ import annotations

import platform
import sys
from importlib import metadata

from lsfcars import APP_NAME, __version__
from lsfcars.core import paths
from lsfcars.core.logging_setup import log_file_path

# Renseigné par le viewport après l'initialisation du contexte OpenGL.
_gl_info: dict[str, str] = {}


def set_gl_info(info: dict[str, str]) -> None:
    _gl_info.clear()
    _gl_info.update(info)


def gl_info() -> dict[str, str]:
    return dict(_gl_info)


def _package_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "inconnue"


def collect() -> dict[str, dict[str, str]]:
    """Retourne les diagnostics regroupés par section."""
    try:
        import PySide6
        from PySide6 import QtCore

        qt_version = QtCore.qVersion()
        pyside_version = PySide6.__version__
    except ImportError:
        qt_version = pyside_version = "indisponible"

    log_file = log_file_path()
    return {
        "Application": {
            "Nom": APP_NAME,
            "Version": __version__,
            "Exécutable": "oui" if paths.is_frozen() else "non (mode développement)",
        },
        "Système": {
            "OS": f"{platform.system()} {platform.release()} ({platform.version()})",
            "Architecture": platform.machine(),
            "Python": sys.version.split()[0],
        },
        "Bibliothèques": {
            "PySide6": pyside_version,
            "Qt": qt_version,
            "numpy": _package_version("numpy"),
            "trimesh": _package_version("trimesh"),
        },
        "OpenGL": gl_info() or {"État": "contexte non initialisé"},
        "Chemins": {
            "Données": str(paths.app_data_dir()),
            "Journal": str(log_file) if log_file else "désactivé",
            "Projets (défaut)": str(paths.default_projects_dir()),
        },
    }


def format_report(data: dict[str, dict[str, str]] | None = None) -> str:
    """Rapport texte, prêt à être copié dans un ticket."""
    data = data or collect()
    lines = [f"=== Diagnostics {APP_NAME} ==="]
    for section, values in data.items():
        lines.append("")
        lines.append(f"[{section}]")
        width = max((len(k) for k in values), default=0)
        for key, value in values.items():
            lines.append(f"  {key.ljust(width)} : {value}")
    return "\n".join(lines)
