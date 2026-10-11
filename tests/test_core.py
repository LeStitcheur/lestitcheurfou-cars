"""Projets récents, journalisation et diagnostics."""

import logging

from lsfcars import __version__
from lsfcars.core import diagnostics
from lsfcars.core.logging_setup import MemoryLogHandler, get_logger, memory_handler
from lsfcars.core.paths import app_data_dir
from lsfcars.project import recent


def test_app_data_dir_uses_override(isolated_home):
    assert app_data_dir() == isolated_home
    assert isolated_home.is_dir()


def test_recent_projects_order_and_dedup(tmp_path):
    a, b = tmp_path / "a.lsfc", tmp_path / "b.lsfc"
    recent.add_recent(a)
    recent.add_recent(b)
    recent.add_recent(a)
    assert recent.list_recent() == [a.resolve(), b.resolve()]


def test_recent_projects_limit(tmp_path):
    for i in range(recent.MAX_RECENT + 5):
        recent.add_recent(tmp_path / f"p{i}.lsfc")
    paths = recent.list_recent()
    assert len(paths) == recent.MAX_RECENT
    assert paths[0].name == f"p{recent.MAX_RECENT + 4}.lsfc"


def test_recent_remove_and_clear(tmp_path):
    a = tmp_path / "a.lsfc"
    recent.add_recent(a)
    recent.remove_recent(a)
    assert recent.list_recent() == []
    recent.add_recent(a)
    recent.clear_recent()
    assert recent.list_recent() == []


def test_recent_corrupted_file_is_ignored(isolated_home):
    app_data_dir()
    (isolated_home / "recent.json").write_text("{pas du json", encoding="utf-8")
    assert recent.list_recent() == []


def test_memory_handler_notifies_listeners():
    handler = MemoryLogHandler(capacity=3)
    handler.setFormatter(logging.Formatter("%(message)s"))
    received = []
    handler.subscribe(lambda record, text: received.append(text))
    handler.subscribe(lambda record, text: 1 / 0)  # un abonné défaillant est toléré
    logger = logging.getLogger("lsfcars.test.memory")
    logger.addHandler(handler)
    try:
        for i in range(5):
            logger.warning("message %d", i)
    finally:
        logger.removeHandler(handler)
    assert received == [f"message {i}" for i in range(5)]
    assert [text for _, text in handler.records] == ["message 2", "message 3", "message 4"]


def test_shared_memory_handler_captures_app_logs():
    get_logger("test").info("trace de test")
    assert any("trace de test" in text for _, text in memory_handler().records)


def test_diagnostics_report_sections():
    diagnostics.set_gl_info({"Moteur de rendu": "Test GPU"})
    report = diagnostics.format_report()
    for section in ("[Application]", "[Système]", "[Bibliothèques]", "[OpenGL]", "[Chemins]"):
        assert section in report
    assert __version__ in report
    assert "Test GPU" in report
