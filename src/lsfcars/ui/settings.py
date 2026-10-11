"""Paramètres de l'application (``settings.ini`` dans le dossier de données)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from lsfcars.core.paths import app_data_dir, default_projects_dir


class AppSettings:
    def __init__(self) -> None:
        self._qs = QSettings(str(app_data_dir() / "settings.ini"), QSettings.Format.IniFormat)

    def _bool(self, key: str, default: bool) -> bool:
        value = self._qs.value(key, default)
        return value if isinstance(value, bool) else value in ("true", "1", 1)

    def value(self, key: str, default: object = None) -> object:
        return self._qs.value(key, default)

    def set_value(self, key: str, value: object) -> None:
        self._qs.setValue(key, value)
        self._qs.sync()

    @property
    def compact(self) -> bool:
        return self._bool("ui/compact", False)

    @compact.setter
    def compact(self, value: bool) -> None:
        self.set_value("ui/compact", bool(value))

    @property
    def sidebar_collapsed(self) -> bool:
        return self._bool("ui/sidebar_collapsed", False)

    @sidebar_collapsed.setter
    def sidebar_collapsed(self, value: bool) -> None:
        self.set_value("ui/sidebar_collapsed", bool(value))

    @property
    def autosave_minutes(self) -> int:
        try:
            return max(0, int(self._qs.value("projects/autosave_minutes", 3)))
        except (TypeError, ValueError):
            return 3

    @autosave_minutes.setter
    def autosave_minutes(self, value: int) -> None:
        self.set_value("projects/autosave_minutes", int(value))

    @property
    def projects_dir(self) -> Path:
        value = self._qs.value("projects/default_dir", "")
        return Path(value) if value else default_projects_dir()

    @projects_dir.setter
    def projects_dir(self, value: Path | str) -> None:
        self.set_value("projects/default_dir", str(value))

    @property
    def blender_path(self) -> str:
        return str(self._qs.value("tools/blender_path", "") or "")

    @blender_path.setter
    def blender_path(self, value: str) -> None:
        self.set_value("tools/blender_path", value or "")

    @property
    def software_gl(self) -> bool:
        return self._bool("render/software_gl", False)

    @software_gl.setter
    def software_gl(self, value: bool) -> None:
        self.set_value("render/software_gl", bool(value))
