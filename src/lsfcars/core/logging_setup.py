"""Configuration de la journalisation : fichier tournant, console et tampon mémoire pour l'UI."""

from __future__ import annotations

import contextlib
import logging
import sys
import threading
from collections import deque
from collections.abc import Callable
from logging.handlers import RotatingFileHandler
from pathlib import Path

from lsfcars.core.paths import logs_dir

LOGGER_NAME = "lsfcars"
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

Listener = Callable[[logging.LogRecord, str], None]


class MemoryLogHandler(logging.Handler):
    """Conserve les derniers messages et notifie des abonnés (panneau Journal)."""

    def __init__(self, capacity: int = 2000) -> None:
        super().__init__()
        self.records: deque[tuple[logging.LogRecord, str]] = deque(maxlen=capacity)
        self._listeners: list[Listener] = []
        self._listeners_lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = self.format(record)
        except Exception:
            self.handleError(record)
            return
        self.records.append((record, text))
        with self._listeners_lock:
            listeners = list(self._listeners)
        for listener in listeners:
            # Un abonné défaillant ne doit pas casser la journalisation.
            with contextlib.suppress(Exception):
                listener(record, text)

    def subscribe(self, listener: Listener) -> None:
        with self._listeners_lock:
            self._listeners.append(listener)

    def unsubscribe(self, listener: Listener) -> None:
        with self._listeners_lock:
            if listener in self._listeners:
                self._listeners.remove(listener)


_memory_handler: MemoryLogHandler | None = None
_log_file: Path | None = None


def setup_logging(level: int = logging.INFO, to_file: bool = True) -> logging.Logger:
    """Configure le logger racine de l'application. Idempotent."""
    global _memory_handler, _log_file

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    if _memory_handler is None:
        _memory_handler = MemoryLogHandler()
        _memory_handler.setLevel(logging.DEBUG)
        _memory_handler.setFormatter(formatter)
        logger.addHandler(_memory_handler)

        if sys.stderr is not None:  # absent dans l'exécutable fenêtré
            reconfigure = getattr(sys.stderr, "reconfigure", None)
            if reconfigure is not None:
                with contextlib.suppress(OSError, ValueError):
                    reconfigure(encoding="utf-8", errors="replace")
            console = logging.StreamHandler(sys.stderr)
            console.setLevel(level)
            console.setFormatter(formatter)
            logger.addHandler(console)

    if to_file and _log_file is None:
        _log_file = logs_dir() / "lsfcars.log"
        file_handler = RotatingFileHandler(
            _log_file, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def memory_handler() -> MemoryLogHandler:
    """Tampon mémoire partagé (configure la journalisation si nécessaire)."""
    if _memory_handler is None:
        setup_logging(to_file=False)
    assert _memory_handler is not None
    return _memory_handler


def log_file_path() -> Path | None:
    return _log_file


def get_logger(name: str) -> logging.Logger:
    """Logger enfant de ``lsfcars`` (ex. ``get_logger(__name__)``)."""
    if not name.startswith(LOGGER_NAME):
        name = f"{LOGGER_NAME}.{name}"
    return logging.getLogger(name)


def install_excepthook() -> None:
    """Journalise les exceptions non interceptées au lieu de les perdre silencieusement."""
    logger = logging.getLogger(LOGGER_NAME)
    previous = sys.excepthook

    def hook(exc_type, exc, tb):  # type: ignore[no-untyped-def]
        if issubclass(exc_type, KeyboardInterrupt):
            previous(exc_type, exc, tb)
            return
        logger.critical("Exception non interceptée", exc_info=(exc_type, exc, tb))

    sys.excepthook = hook
