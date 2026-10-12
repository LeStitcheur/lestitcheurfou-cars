"""Clés API des fournisseurs cloud : coffre chiffré par Windows (DPAPI), jamais dans un projet.

Ordre de lecture : variable d'environnement ``LSFCARS_<FOURNISSEUR>_API_KEY`` puis coffre de
l'utilisateur (``ai_secrets.json`` dans les données de l'application, chiffré par
``CryptProtectData`` : seul le même compte Windows peut le relire). Aucune clé n'est écrite
dans un ``.lsfc``, dans un journal ou dans l'historique ; l'interface n'affiche qu'un masque.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import sys
from ctypes import wintypes
from pathlib import Path

from lsfcars.ai.errors import AIError
from lsfcars.core.logging_setup import get_logger

log = get_logger(__name__)

_ENTROPY = b"LeStitcheurFouCars/ai-secrets/v1"


def env_name(provider: str) -> str:
    return f"LSFCARS_{provider.upper().replace('-', '_')}_API_KEY"


def masked(secret: str) -> str:
    """Affichage sûr : quatre derniers caractères seulement."""
    secret = secret or ""
    return "•" * 6 + secret[-4:] if len(secret) > 8 else "•" * len(secret)


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, protect: bool) -> bytes:
    if sys.platform != "win32":
        raise AIError("Coffre sécurisé indisponible hors Windows : utilisez une variable d'environnement.")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    source_buffer = ctypes.create_string_buffer(data, len(data))
    entropy_buffer = ctypes.create_string_buffer(_ENTROPY, len(_ENTROPY))
    source = _Blob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_char)))
    entropy = _Blob(len(_ENTROPY), ctypes.cast(entropy_buffer, ctypes.POINTER(ctypes.c_char)))
    out = _Blob()
    function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = function(
        ctypes.byref(source), None, ctypes.byref(entropy), None, None, 0x01, ctypes.byref(out)
    )  # 0x01 : CRYPTPROTECT_UI_FORBIDDEN
    if not ok:
        raise AIError("Le coffre Windows a refusé l'opération (clé illisible pour ce compte ?).")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


class SecretStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _read(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(temp, self.path)

    def get(self, provider: str) -> str | None:
        env = os.environ.get(env_name(provider), "").strip()
        if env:
            return env
        stored = self._read().get(provider)
        if not stored:
            return None
        try:
            return _dpapi(base64.b64decode(stored), protect=False).decode("utf-8")
        except (AIError, ValueError) as exc:
            log.warning("Clé « %s » illisible : %s", provider, exc)
            return None

    def source(self, provider: str) -> str | None:
        if os.environ.get(env_name(provider), "").strip():
            return "variable d'environnement"
        if self._read().get(provider):
            return "coffre Windows (DPAPI)"
        return None

    def set(self, provider: str, secret: str) -> None:
        secret = secret.strip()
        if not secret:
            raise AIError("Clé vide.")
        data = self._read()
        data[provider] = base64.b64encode(_dpapi(secret.encode("utf-8"), protect=True)).decode("ascii")
        self._write(data)
        log.info("Clé API enregistrée pour « %s » (coffre Windows).", provider)

    def delete(self, provider: str) -> bool:
        data = self._read()
        if provider not in data:
            return False
        del data[provider]
        self._write(data)
        log.info("Clé API supprimée pour « %s ».", provider)
        return True
