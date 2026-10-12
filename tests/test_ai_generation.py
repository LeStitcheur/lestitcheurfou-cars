"""AI Engine Manager, références, analyse et génération — tests RÉELS (moteurs locaux).

LSF Silhouette (intégré) produit réellement un maillage à chaque exécution. Le test TripoSR
lance une vraie inférence neuronale ; il est ignoré si le moteur n'est pas installé sur la
machine (``scripts/install_triposr.ps1``).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np
import pytest

from lsfcars.ai import references as refs_mod
from lsfcars.ai import vision
from lsfcars.ai.engines.base import Capability, GenerationRequest, JobContext, ReferenceInput, Status
from lsfcars.ai.engines.silhouette import SilhouetteEngine
from lsfcars.ai.engines.triposr import TripoSREngine
from lsfcars.ai.errors import AIError, EngineUnavailable, JobCancelled
from lsfcars.ai.manager import (
    CANCELLED,
    FAILED,
    SUCCEEDED,
    TIMEOUT,
    AIEngineManager,
    JobQueue,
    RoutingRequest,
)
from lsfcars.importers import load_model

REFERENCES = Path(__file__).resolve().parents[1] / "samples" / "references"
VIEWS = {
    "left": "demo_profil_gauche.png",
    "front": "demo_avant.png",
    "back": "demo_arriere.png",
    "top": "demo_dessus.png",
    "three_quarter": "demo_trois_quarts.png",
}
# Installation réelle de l'utilisateur (hors dossier isolé des tests)
INSTALLED_TRIPOSR = Path(
    os.environ.get("LSFCARS_REAL_ENGINES", Path.home() / ".lestitcheurfoucars" / "engines")
)


@pytest.fixture
def manager(tmp_path):
    manager = AIEngineManager(tmp_path / "data", tmp_path / "engines")
    yield manager
    manager.shutdown()


def inputs(*views: str) -> list[ReferenceInput]:
    return [ReferenceInput(REFERENCES / VIEWS[v], v) for v in views]


# --- 1-3. Matériel, moteurs, configuration --------------------------------------------------------


def test_hardware_detection_is_real(tmp_path):
    from lsfcars.ai import hardware

    info = hardware.detect(tmp_path, include_dependencies=True)
    assert info.cpu and info.cores and info.cores >= 1
    assert info.ram_mb is None or info.ram_mb > 512
    assert info.disk_free_mb is not None
    assert info.dependencies["numpy"] != "absent"
    assert set(info.summary()) >= {"Processeur", "Mémoire vive", "GPU", "VRAM", "Accélération"}
    roundtrip = hardware.from_dict(info.to_dict())
    assert roundtrip.cpu == info.cpu and len(roundtrip.gpus) == len(info.gpus)


def test_engine_detection(manager):
    availability = manager.detect_all(include_hardware=False)
    assert availability["lsf-silhouette"].ok
    assert availability["triposr"].status is Status.MISSING  # dossier de moteurs vide
    assert availability["comfyui"].status in (Status.MISSING, Status.UNCONFIGURED, Status.ERROR)
    assert availability["meshy"].status is Status.UNCONFIGURED  # aucune clé
    assert availability["anthropic"].status is Status.UNCONFIGURED
    for adapter in manager.adapters.values():
        info = adapter.info
        assert info.name and info.version and info.capabilities and info.input_formats and info.output_formats
        assert info.resources and info.auth and info.cost and info.verification


def test_local_configuration_is_persisted_without_secrets(manager, tmp_path):
    manager.configure_engine(
        "comfyui", {"url": "http://127.0.0.1:8190", "workflow": str(tmp_path / "wf.json")}
    )
    manager.set_option("mode", "local")
    with pytest.raises(AIError):
        manager.configure_engine("meshy", {"api_key": "interdit"})
    reloaded = AIEngineManager(tmp_path / "data", tmp_path / "engines")
    assert reloaded.config["mode"] == "local"
    assert reloaded.adapters["comfyui"].base_url == "http://127.0.0.1:8190"
    assert "key" not in json.dumps(reloaded.config).lower()


def test_profiles_follow_hardware():
    from lsfcars.ai.hardware import GPUInfo, HardwareInfo

    engine = TripoSREngine({"root": "absent"})
    weak = HardwareInfo(gpus=[GPUInfo("GPU 4 Go", "NVIDIA", 4096)], cuda="12.0")
    profiles = {p.key: p for p in engine.profiles(weak)}
    assert not profiles["high"].available and "VRAM" in profiles["high"].reason
    cpu_only = {p.key: p for p in engine.profiles(HardwareInfo())}
    assert cpu_only["eco"].available and not cpu_only["balanced"].available


# --- 5-7. Références, analyse, routage ------------------------------------------------------------


def test_reference_preparation_and_segmentation():
    data = (REFERENCES / VIEWS["left"]).read_bytes()
    ref = refs_mod.new_reference(data, "profil.png", "left")
    image = refs_mod.prepare(ref, data)
    seg = refs_mod.segment(image)
    assert seg.ok and seg.method == "fond uni"
    rotated = refs_mod.prepare({**ref, "rotation": 90}, data)
    assert rotated.size == (image.height, image.width)
    cropped = refs_mod.prepare({**ref, "crop": [0.1, 0.2, 0.6, 0.9]}, data)
    assert cropped.width == pytest.approx(image.width * 0.5, abs=2)
    with pytest.raises(AIError):
        refs_mod.new_reference(b"pas une image", "x.png")
    report = refs_mod.coverage([ref])
    assert any("droit" in zone for zone in report.estimated_zones) and not report.can_multiview


def test_vision_report_measures_and_flags_estimates():
    refs, images = [], {}
    for view, name in VIEWS.items():
        data = (REFERENCES / name).read_bytes()
        ref = refs_mod.new_reference(data, name, view)
        refs.append(ref)
        images[ref["id"]] = refs_mod.prepare(ref, data)
    report = vision.build_report(refs, images, known_length=4.4)
    fields = report["fields"]
    assert fields["type"]["value"] == "sedan"
    assert fields["length_m"]["source"] == "utilisateur" and not fields["length_m"]["approx"]
    assert fields["height_m"]["approx"] and 1.2 < fields["height_m"]["value"] < 1.7  # modèle : 1,42 m
    assert fields["wheels_visible"]["value"] == 2
    assert report["colors"] and report["warnings"] == []
    vision.set_value(report, "height_m", 1.42)
    assert report["fields"]["height_m"] == {
        "value": 1.42,
        "source": "utilisateur",
        "approx": False,
        "confidence": 1.0,
    }


def test_auto_routing(manager):
    manager.detect_all(include_hardware=False)
    decision = manager.route(RoutingRequest(Capability.MULTIVIEW_3D, ["left", "front", "top"]))
    assert decision.chosen == "lsf-silhouette" and not decision.needs_cloud_consent
    only_photo = manager.route(RoutingRequest(Capability.IMAGE_TO_3D, ["three_quarter"]))
    assert only_photo.chosen is None
    reasons = {c.engine_id: c.excluded for c in only_photo.candidates}
    assert "profil" in reasons["lsf-silhouette"] and "Non installé" in reasons["triposr"]
    cloud_only = manager.route(RoutingRequest(Capability.IMAGE_TO_3D, ["left"], mode="cloud"))
    assert cloud_only.chosen is None  # aucun fournisseur configuré : rien n'est supposé compatible


# --- 8-9. Génération réelle et récupération -------------------------------------------------------


def test_silhouette_generation_is_real_and_metric(tmp_path):
    engine = SilhouetteEngine()
    request = GenerationRequest(
        Capability.MULTIVIEW_3D,
        inputs("left", "front", "top"),
        tmp_path,
        "balanced",
        vehicle={"length_m": 4.4},
    )  # profil économique : voxels de 6 cm, les rétroviseurs (fins) disparaissent
    output = engine.run(request, JobContext())
    result = load_model(output.files["model"])
    mesh = next(iter(result.meshes.values()))
    size = mesh.positions.max(axis=0) - mesh.positions.min(axis=0)
    assert np.allclose(size, [2.12, 1.42, 4.4], atol=0.12)  # dimensions du véhicule d'origine
    assert output.used_views == ["left", "front", "top"]
    assert any("estimée" in w.lower() for w in output.warnings)
    single = engine.run(
        GenerationRequest(Capability.IMAGE_TO_3D, inputs("left"), tmp_path / "one", "eco"), JobContext()
    )
    assert any("Une seule vue" in w for w in single.warnings)


def test_unavailable_engine_and_missing_view(tmp_path):
    request = GenerationRequest(Capability.IMAGE_TO_3D, inputs("three_quarter"), tmp_path)
    with pytest.raises(EngineUnavailable, match="profil"):
        SilhouetteEngine().run(request, JobContext())
    with pytest.raises(EngineUnavailable, match="non installé"):
        TripoSREngine({"root": str(tmp_path / "absent")}).run(request, JobContext())


# --- 18. Interruption, délai, file de tâches, cache -----------------------------------------------


def test_job_queue_cancel_timeout_and_errors():
    queue = JobQueue()

    def slow(ctx):  # type: ignore[no-untyped-def]
        for _ in range(200):
            ctx.sleep(0.02)
        return "fini"

    def broken(ctx):  # type: ignore[no-untyped-def]
        raise AIError("panne simulée")

    running = queue.submit("longue", slow)
    waiting = queue.submit("en attente", slow)
    time.sleep(0.1)
    assert queue.cancel(waiting.id) and waiting.status == CANCELLED  # retirée avant démarrage
    assert queue.cancel(running.id)
    assert running.wait(5) and running.status == CANCELLED
    timed = queue.submit("délai", slow, timeout=0.2)
    assert timed.wait(5) and timed.status == TIMEOUT
    failing = queue.submit("erreur", broken)
    assert failing.wait(5) and failing.status == FAILED and failing.error == "panne simulée"
    done = queue.submit("ok", lambda ctx: 42)
    assert done.wait(5) and done.status == SUCCEEDED and done.result == 42
    queue.shutdown()


def test_real_generation_can_be_interrupted(tmp_path):
    state = {"cancel": False}

    def progress(value: float, _text: str) -> None:
        if value >= 0.2:
            state["cancel"] = True

    ctx = JobContext(progress, lambda: state["cancel"])
    request = GenerationRequest(Capability.MULTIVIEW_3D, inputs("left", "front"), tmp_path, "high")
    with pytest.raises(JobCancelled):
        SilhouetteEngine().run(request, ctx)
    assert not (tmp_path / "silhouette.glb").exists()


def test_result_cache_and_cleanup(manager, tmp_path):
    files = {"model": tmp_path / "m.glb"}
    files["model"].write_bytes(b"glb")
    key = manager.cache_key("lsf-silhouette", "1.0", "eco", {"a": 1}, ["ref-1"])
    assert manager.cache_lookup(key) is None
    manager.cache_store(key, files, {"data": {}})
    assert manager.cache_lookup(key)["files"]["model"] == files["model"]
    assert manager.cache_key("lsf-silhouette", "1.0", "eco", {"a": 2}, ["ref-1"]) != key
    old = manager.job_dir("ancienne")
    os.utime(old, (time.time() - 10 * 86400, time.time() - 10 * 86400))
    manager.job_dir("recente")
    assert manager.cleanup(7) == 1
    assert (manager.cache_dir / "jobs" / "recente").is_dir()


# --- TripoSR réel (facultatif) --------------------------------------------------------------------

TRIPOSR = TripoSREngine({"root": str(INSTALLED_TRIPOSR / "triposr")})


@pytest.mark.skipif(bool(TRIPOSR.missing()), reason="TripoSR non installé (scripts/install_triposr.ps1)")
def test_triposr_real_generation(tmp_path):
    from lsfcars.ai import hardware

    availability = TRIPOSR.detect()
    assert availability.ok, availability.message
    request = GenerationRequest(
        Capability.IMAGE_TO_3D,
        inputs("three_quarter", "left"),
        tmp_path,
        "eco",
        vehicle={"_hardware": hardware.detect(include_dependencies=False)},
    )
    output = TRIPOSR.run(request, JobContext(timeout=900))
    result = load_model(output.files["model"])
    assert result.triangle_count > 10000
    assert output.used_views == ["three_quarter"]  # une seule image exploitée, signalé
    assert output.data["stats"]["faces"] == result.triangle_count


def cluttered_photo(path: Path) -> Path:
    """Véhicule de démonstration posé sur un décor non uniforme (ciel en dégradé, route bruitée)."""
    from PIL import Image

    car = Image.open(REFERENCES / "demo_trois_quarts.png").convert("RGB")
    w, h = car.size
    rng = np.random.default_rng(3)
    y = np.linspace(0, 1, h)[:, None, None]
    sky = np.array([90, 140, 200]) * (1 - y) + np.array([60, 60, 65]) * y
    background = np.clip(sky + rng.normal(0, 28, (h, w, 3)), 0, 255)
    pixels = np.asarray(car).astype(np.int16)
    car_mask = np.abs(pixels - pixels[0, 0]).sum(axis=2) > 30
    composed = np.where(car_mask[..., None], pixels, background).astype(np.uint8)
    Image.fromarray(composed).save(path)
    return path


def test_matting_choice_and_explicit_failure(tmp_path):
    from PIL import Image

    from lsfcars.ai.errors import InvalidOutput

    photo = cluttered_photo(tmp_path / "photo.png")
    assert not refs_mod.segment(Image.open(photo)).ok  # le détourage local échoue sur ce décor
    engine = TripoSREngine({"root": str(tmp_path / "triposr")})
    with pytest.raises(InvalidOutput, match="U²-Net"):
        engine.prepare_input(ReferenceInput(photo, "three_quarter"), tmp_path)
    (tmp_path / "triposr" / "models").mkdir(parents=True)
    (tmp_path / "triposr" / "models" / "u2net.onnx").write_bytes(b"onnx")
    (tmp_path / "triposr" / "env" / "Lib" / "site-packages" / "onnxruntime").mkdir(parents=True)
    source, method = engine.prepare_input(ReferenceInput(photo, "three_quarter"), tmp_path)
    assert method == "u2net" and source.is_file()  # détourage confié au réseau (processus du moteur)
    transparent = tmp_path / "detoure.png"
    image = Image.open(REFERENCES / "demo_trois_quarts.png").convert("RGBA")
    image.putalpha(Image.fromarray((np.asarray(image.convert("L")) < 200).astype(np.uint8) * 255))
    image.save(transparent)
    assert engine.prepare_input(ReferenceInput(transparent, "three_quarter"), tmp_path)[1] == "transparence"


@pytest.mark.skipif(
    bool(TRIPOSR.missing()) or not TRIPOSR.matting_available(),
    reason="TripoSR ou le détourage U²-Net non installé (scripts/install_triposr.ps1)",
)
def test_triposr_real_generation_on_cluttered_photo(tmp_path):
    from PIL import Image

    from lsfcars.ai import hardware

    photo = cluttered_photo(tmp_path / "photo.png")
    request = GenerationRequest(
        Capability.IMAGE_TO_3D,
        [ReferenceInput(photo, "three_quarter")],
        tmp_path / "job",
        "eco",
        vehicle={"_hardware": hardware.detect(include_dependencies=False)},
    )
    output = TRIPOSR.run(request, JobContext(timeout=900))
    assert output.data["matting"] == "u2net"
    assert load_model(output.files["model"]).triangle_count > 10000
    cut = Image.open(tmp_path / "job" / "triposr_input_u2net.png")
    coverage = (np.asarray(cut.getchannel("A")) >= 128).mean()
    assert 0.05 < coverage < 0.8  # véhicule séparé du décor
