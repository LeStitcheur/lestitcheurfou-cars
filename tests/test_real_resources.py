"""Validation sur une vraie ressource FiveM / GTA V présente localement (facultatif).

Aucun fichier tiers n'est versionné : indiquez le chemin d'une ressource que vous avez le droit
d'utiliser dans la variable ``LSFCARS_REAL_RESOURCE`` (dossier, ZIP ou RPF). Sans elle, ces tests
sont ignorés et ne prétendent rien valider.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from lsfcars.fivem.resource import Status, analyze, stage_model
from lsfcars.importers.yft_importer import YftImporter

REAL = os.environ.get("LSFCARS_REAL_RESOURCE", "")
pytestmark = pytest.mark.skipif(
    not REAL or not Path(REAL).exists(), reason="LSFCARS_REAL_RESOURCE non défini : aucune ressource réelle"
)


def test_real_resource_is_analyzed_and_imported(tmp_path):
    analysis = analyze(REAL)
    try:
        assert analysis.overall in (Status.COMPATIBLE, Status.PARTIAL, Status.MISSING)
        vehicles = [m for m in analysis.models if m.is_vehicle and m.status is Status.COMPATIBLE]
        assert vehicles, "aucun véhicule compatible trouvé"
        assert any(t.decoded for t in analysis.textures)
        assert all(t.decoded or t.reason for t in analysis.textures)  # jamais d'échec silencieux
        result = YftImporter().load(stage_model(analysis, vehicles[0], tmp_path / "stage"))
        assert result.triangle_count > 1000
        assert any(n.extra.get("category") == "roues" for n in result.nodes)
    finally:
        analysis.close()
