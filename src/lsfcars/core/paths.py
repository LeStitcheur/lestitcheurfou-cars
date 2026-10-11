"""Emplacements des données de l'application.

La variable d'environnement ``LSFCARS_HOME`` permet de rediriger toutes les données
(utile pour les tests et les installations portables).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from lsfcars import APP_ID, APP_NAME


def app_data_dir() -> Path:
    """Dossier des données de l'application (logs, paramètres, projets récents)."""
    override = os.environ.get("LSFCARS_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "win32" and os.environ.get("APPDATA"):
        base = Path(os.environ["APPDATA"]) / APP_ID
    else:
        base = Path.home() / f".{APP_ID.lower()}"
    base.mkdir(parents=True, exist_ok=True)
    return base


def logs_dir() -> Path:
    path = app_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_projects_dir() -> Path:
    """Dossier proposé par défaut pour créer de nouveaux projets (non créé ici)."""
    override = os.environ.get("LSFCARS_HOME")
    if override:
        return Path(override) / "Projets"
    return Path.home() / "Documents" / APP_NAME / "Projets"


def is_frozen() -> bool:
    """Vrai lorsque l'application tourne depuis l'exécutable PyInstaller."""
    return bool(getattr(sys, "frozen", False))


def _bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))


def resources_dir() -> Path:
    """Dossier des ressources embarquées (icônes…), en développement comme en exécutable."""
    if is_frozen():
        return _bundle_root() / "lsfcars" / "resources"
    return Path(__file__).resolve().parent.parent / "resources"


def samples_dir() -> Path:
    """Dossier des modèles d'exemple livrés avec l'application."""
    if is_frozen():
        return _bundle_root() / "samples"
    return Path(__file__).resolve().parents[3] / "samples"
