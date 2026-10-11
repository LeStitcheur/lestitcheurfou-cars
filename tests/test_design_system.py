"""Design system Dark Premium : palette officielle centralisée, aucune couleur dispersée."""

from __future__ import annotations

import re
from pathlib import Path

from lsfcars.ui.design import tokens
from lsfcars.ui.design.qss import ComponentStyles, stylesheet

UI = Path(__file__).resolve().parents[1] / "src" / "lsfcars" / "ui"
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")


def test_palette_is_the_official_one():
    c = tokens.ColorTokens
    assert (c.BG_MAIN, c.BG_SECONDARY, c.PANEL, c.SURFACE, c.BORDER) == (
        "#0b0e14",
        "#111722",
        "#151b26",
        "#202a3b",
        "#2a3445",
    )
    assert (c.PRIMARY, c.ELECTRIC, c.TEXT, c.TEXT_SECONDARY) == ("#2563eb", "#38bdf8", "#f3f6fc", "#94a3b8")
    assert (c.SUCCESS, c.WARNING, c.ERROR) == ("#22c55e", "#f59e0b", "#ef4444")
    assert tokens.THEME.name == "Dark Premium"


def test_no_color_literal_outside_tokens():
    offenders = []
    for path in UI.rglob("*.py"):
        if path.name == "tokens.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if HEX.search(line) or re.search(r"rgba?\(\s*\d", line):
                offenders.append(f"{path.relative_to(UI)}:{number}: {line.strip()}")
    assert not offenders, "\n".join(offenders)


def test_stylesheet_uses_blue_for_active_states():
    css = stylesheet()
    assert 'QPushButton[variant="primary"] { background: #2563eb' in css
    assert "border-bottom-color: #38bdf8" in css  # onglet actif
    assert ComponentStyles.palette().highlight().color().name() == "#2563eb"
