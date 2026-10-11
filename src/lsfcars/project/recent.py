"""Liste des projets récemment ouverts (``recent.json`` dans le dossier de données)."""

from __future__ import annotations

import json
from pathlib import Path

from lsfcars.core.logging_setup import get_logger
from lsfcars.core.paths import app_data_dir

log = get_logger(__name__)

MAX_RECENT = 10


def _store_path() -> Path:
    return app_data_dir() / "recent.json"


def list_recent() -> list[Path]:
    try:
        data = json.loads(_store_path().read_text(encoding="utf-8"))
        return [Path(p) for p in data.get("projects", []) if isinstance(p, str)]
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        log.warning("Liste des projets récents illisible (%s), réinitialisée", exc)
        return []


def _write(paths: list[Path]) -> None:
    data = {"projects": [str(p) for p in paths[:MAX_RECENT]]}
    try:
        _store_path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        log.warning("Impossible d'enregistrer les projets récents : %s", exc)


def _same(a: Path, b: Path) -> bool:
    return str(a.resolve()).lower() == str(b.resolve()).lower()


def add_recent(path: str | Path) -> None:
    path = Path(path).resolve()
    paths = [p for p in list_recent() if not _same(p, path)]
    _write([path, *paths])


def remove_recent(path: str | Path) -> None:
    path = Path(path)
    _write([p for p in list_recent() if not _same(p, path)])


def clear_recent() -> None:
    _write([])
