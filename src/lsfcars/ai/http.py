"""Client HTTP des adaptateurs (bibliothèque standard) : délais, reprises contrôlées, annulation.

- Reprises (``retries``) uniquement pour les erreurs transitoires : réseau, 429, 5xx, avec
  attente exponentielle interruptible et respect de ``Retry-After`` (plafonné).
- Erreurs classées : ``AuthError`` (401 / 403), ``QuotaError`` (402, 429 persistant),
  ``NetworkError`` (connexion, délai), ``ProviderError`` (autres réponses d'erreur).
- Historique des requêtes : méthode, adresse **sans paramètres**, statut, durée ; jamais
  d'en-têtes ni de corps (les clés API n'y figurent donc pas).
"""

from __future__ import annotations

import contextlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from lsfcars.ai.engines.base import JobContext
from lsfcars.ai.errors import AIError, AuthError, NetworkError, ProviderError, QuotaError
from lsfcars.ai.references import now_iso

USER_AGENT = "LeStitcheurFouCars-AI"
MAX_RETRY_AFTER = 30.0


@dataclass
class RequestLog:
    entries: list[dict] = field(default_factory=list)
    limit: int = 500
    listeners: list[Callable[[dict], None]] = field(default_factory=list)

    def add(self, entry: dict) -> None:
        self.entries.append(entry)
        del self.entries[: -self.limit]
        for listener in list(self.listeners):
            listener(entry)


REQUEST_LOG = RequestLog()


def public_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _message(raw: bytes) -> str:
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return raw.decode("utf-8", "replace")[:300]
    if isinstance(data, dict):
        for key in ("message", "error", "detail"):
            value = data.get(key)
            if isinstance(value, dict):
                value = value.get("message") or json.dumps(value)[:300]
            if value:
                return str(value)[:300]
    return json.dumps(data)[:300]


def request(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    body: dict | bytes | None = None,
    content_type: str | None = None,
    timeout: float = 30.0,
    retries: int = 2,
    backoff: float = 1.0,
    ctx: JobContext | None = None,
    provider: str = "",
) -> tuple[int, bytes, dict]:
    """Requête avec reprises ; retourne (statut, corps, en-têtes). Lève une ``AIError`` classée."""
    ctx = ctx or JobContext()
    data = None
    final_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    if isinstance(body, dict):
        data = json.dumps(body).encode("utf-8")
        final_headers.setdefault("Content-Type", "application/json")
    elif body is not None:
        data = body
        if content_type:
            final_headers["Content-Type"] = content_type
    name = provider or "Fournisseur"
    attempt = 0
    while True:
        ctx.check()
        attempt += 1
        start = time.monotonic()
        status = 0
        retry_after = None
        error: AIError
        try:
            remaining = ctx.remaining()
            effective = timeout if remaining is None else max(1.0, min(timeout, remaining))
            req = urllib.request.Request(url, data=data, headers=final_headers, method=method)
            with urllib.request.urlopen(req, timeout=effective) as response:  # noqa: S310 (adresses configurées)
                status = response.status
                payload = response.read()
                result_headers = dict(response.headers.items())
            _log(method, url, status, start, attempt, provider)
            return status, payload, result_headers
        except urllib.error.HTTPError as exc:
            status = exc.code
            payload = exc.read() if exc.fp else b""
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            message = _message(payload) or str(exc.reason)
            if status in (401, 403):
                error = AuthError(f"{name} : authentification refusée ({status}) — {message}")
            elif status == 402:
                error = QuotaError(f"{name} : crédits insuffisants (402) — {message}")
            elif status == 429:
                error = QuotaError(f"{name} : limite de requêtes atteinte (429) — {message}")
            else:
                error = ProviderError(f"{name} : erreur {status} — {message}")
            transient = status == 429 or status >= 500
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            error = NetworkError(f"{provider or 'Réseau'} : connexion impossible ({reason}).")
            transient = True
        _log(method, url, status, start, attempt, provider)
        if not transient or attempt > retries:
            raise error
        delay = backoff * (2 ** (attempt - 1))
        if retry_after:
            with contextlib.suppress(ValueError):  # Retry-After au format date : ignoré
                delay = max(delay, min(float(retry_after), MAX_RETRY_AFTER))
        ctx.log(f"Nouvelle tentative dans {delay:.0f} s ({error}).")
        ctx.sleep(delay)


def _log(method: str, url: str, status: int, start: float, attempt: int, provider: str) -> None:
    REQUEST_LOG.add(
        {
            "at": now_iso(),
            "provider": provider,
            "method": method,
            "url": public_url(url),
            "status": status,
            "duration_s": round(time.monotonic() - start, 3),
            "attempt": attempt,
        }
    )


def request_json(method: str, url: str, **kwargs) -> dict:  # type: ignore[no-untyped-def]
    _status, payload, _headers = request(method, url, **kwargs)
    try:
        data = json.loads(payload.decode("utf-8")) if payload else {}
    except ValueError as exc:
        raise ProviderError(f"Réponse non JSON de {public_url(url)}.") from exc
    return data if isinstance(data, dict) else {"items": data}


def download(
    url: str,
    target: Path,
    *,
    headers: dict | None = None,
    ctx: JobContext | None = None,
    max_bytes: int = 1024 * 1024 * 1024,
    timeout: float = 120.0,
    retries: int = 2,
    backoff: float = 1.0,
    provider: str = "",
) -> Path:
    """Téléchargement vers un fichier (taille plafonnée), avec reprises."""
    _status, payload, _headers = request(
        "GET",
        url,
        headers=headers,
        ctx=ctx,
        timeout=timeout,
        retries=retries,
        backoff=backoff,
        provider=provider,
    )
    if len(payload) > max_bytes:
        raise ProviderError("Fichier téléchargé trop volumineux.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return target


def multipart(fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]) -> tuple[bytes, str]:
    """Corps multipart/form-data : (données, type de contenu)."""
    boundary = "----lsf" + uuid.uuid4().hex
    lines: list[bytes] = []
    for name, value in fields.items():
        lines += [
            f"--{boundary}".encode(),
            f'Content-Disposition: form-data; name="{name}"'.encode(),
            b"",
            value.encode(),
        ]
    for name, (filename, data, mime) in files.items():
        lines += [
            f"--{boundary}".encode(),
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"'.encode(),
            f"Content-Type: {mime}".encode(),
            b"",
            data,
        ]
    lines += [f"--{boundary}--".encode(), b""]
    return b"\r\n".join(lines), f"multipart/form-data; boundary={boundary}"
