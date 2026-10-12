"""Lore Friendly Engine × moteurs IA — tests SIMULÉS.

Un serveur HTTP local reproduit le contrat de l'API Messages d'Anthropic (plan de
transformation) et l'API HTTP de ComfyUI (image conceptuelle 2D). Ces tests vérifient le
protocole, le consentement, la validation des plans contre le catalogue et l'étiquetage des
images ; ils ne prouvent PAS le fonctionnement des services réels (aucune clé disponible).
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from lsfcars.ai.engines.anthropic import AnthropicEngine
from lsfcars.ai.engines.base import Capability, JobContext, Status
from lsfcars.ai.engines.comfyui import ComfyUIEngine
from lsfcars.ai.errors import ConsentRequired
from lsfcars.ai.secrets import SecretStore
from lsfcars.lorefriendly.engine import LoreFriendlyEngine
from lsfcars.project.session import ProjectSession

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
FAKE_KEY = "cle-de-test-factice-0000"
PNG = (SAMPLES / "references" / "demo_avant.png").read_bytes()
PLAN = {
    "proposals": [
        {
            "title": "Pegassi Ventura",
            "summary": "Silhouette abaissée et nouvelle face avant",
            "plan": [
                {"op": "roof_height", "params": {"amount": -5}, "why": "silhouette basse"},
                {"op": "headlights", "params": {"style": "slim"}, "why": "regard affûté"},
                {"op": "teleport", "params": {}, "why": "hors catalogue"},
            ],
        }
    ]
}


class State:
    def __init__(self) -> None:
        self.bodies: list[dict] = []
        self.url = ""


def handler_for(state: State):  # type: ignore[no-untyped-def]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:  # type: ignore[no-untyped-def]
            return

        def send(self, code: int, body: bytes, kind: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def reply(self, payload: dict, code: int = 200) -> None:
            self.send(code, json.dumps(payload).encode())

        def route(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            path = self.path.split("?")[0]
            if path == "/v1/messages":
                if self.headers.get("x-api-key") != FAKE_KEY:
                    self.reply({"error": {"message": "invalid x-api-key"}}, 401)
                    return
                state.bodies.append(json.loads(raw))
                usage = {"input_tokens": 900, "output_tokens": 120}
                self.reply({"content": [{"type": "text", "text": json.dumps(PLAN)}], "usage": usage})
            elif path == "/system_stats":
                self.reply({"system": {"comfyui_version": "0.3.test"}, "devices": []})
            elif path == "/object_info":
                self.reply({"LoadImage": {}, "FakeImg2Img": {}, "SaveImage": {}})
            elif path == "/upload/image":
                self.reply({"name": "lsf_apercu.png", "subfolder": "", "type": "input"})
            elif path == "/prompt":
                prompt = json.loads(raw)["prompt"]
                assert prompt["1"]["inputs"]["image"] == "lsf_apercu.png"
                assert "Aucun logo" in prompt["2"]["inputs"]["text"]
                self.reply({"prompt_id": "c-1", "number": 1, "node_errors": {}})
            elif path == "/history/c-1":
                images = {"images": [{"filename": "concept.png", "subfolder": "", "type": "output"}]}
                entry = {"status": {"status_str": "success", "completed": True}, "outputs": {"3": images}}
                self.reply({"c-1": entry})
            elif path == "/view":
                self.send(200, PNG, "image/png")
            else:
                self.reply({"message": "inconnu"}, 404)

        def do_GET(self) -> None:  # noqa: N802
            self.route()

        def do_POST(self) -> None:  # noqa: N802
            self.route()

    return Handler


@pytest.fixture
def server():
    state = State()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    state.url = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield state
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def design(tmp_path):
    session = ProjectSession.create(tmp_path / "projets", "Lore cloud")
    root = session.import_model(SAMPLES / "vehicule_lore.glb")
    engine = LoreFriendlyEngine(session, None, tmp_path / "data")
    design_id = engine.create_design(root)
    engine.choose_brand(design_id, "pegassi")
    engine.analyze(design_id)
    return engine, design_id


def test_cloud_design_plan_is_validated_against_catalogue(server, design, tmp_path):
    engine, design_id = design
    secrets = SecretStore(tmp_path / "secrets.json")
    secrets.set("anthropic", FAKE_KEY)
    adapter = AnthropicEngine({"base_url": server.url, "backoff": 0.01}, secrets=secrets)
    assert Capability.DESIGN_PLAN in adapter.info.capabilities
    with pytest.raises(ConsentRequired):
        adapter.run(
            engine.cloud_request(design_id, tmp_path / "job"), JobContext()
        )  # aucun envoi sans accord
    assert not server.bodies
    request = engine.cloud_request(design_id, tmp_path / "job", allow_cloud=True, allow_paid=True)
    output = adapter.run(request, JobContext())
    content = server.bodies[0]["messages"][0]["content"]
    assert all(block["type"] == "text" for block in content)  # aucune image ni aucun modèle transmis
    assert "Empattement" in content[0]["text"] and "headlights" in content[0]["text"]
    stored, rejected = engine.merge_cloud_concepts(design_id, output, adapter.info.id, adapter.info.name)
    assert rejected == ["teleport"]  # opération hors catalogue écartée
    plan = stored[0]["plan"]
    assert [s["op"] for s in plan] == ["roof_height", "headlights"]
    assert plan[0]["params"]["amount"] == pytest.approx(-0.18)  # paramètre borné au catalogue
    assert stored[0]["source"] == "cloud" and "900 jetons" in stored[0]["reported_cost"]


def test_comfyui_concept_image_is_labelled_2d(server, design, tmp_path):
    engine, design_id = design
    engine.generate_concepts(design_id, 1)
    engine.apply_previews(design_id, engine.preview_job(design_id)(JobContext()))
    workflow = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "x.png"}},
        "2": {"class_type": "FakeImg2Img", "inputs": {"image": ["1", 0], "text": "{{prompt}}"}},
        "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0]}},
    }
    path = tmp_path / "concept_api.json"
    path.write_text(json.dumps(workflow), encoding="utf-8")
    adapter = ComfyUIEngine({"url": server.url, "poll_interval": 0.01})
    assert adapter.detect().status is Status.UNCONFIGURED
    adapter.configure({"concept_workflow": str(path)})
    availability = adapter.detect()
    assert availability.ok and "image conceptuelle" in availability.message
    concept = engine.design(design_id)["concepts"][0]
    request = engine.concept_image_request(design_id, concept["id"], tmp_path / "job")
    output = adapter.run(request, JobContext())
    assert set(output.files) == {"concept"}  # une image, jamais un « model »
    key = engine.attach_concept_image(design_id, concept["id"], output)
    assert engine.scene.blobs[key] == PNG
    assert "aucune géométrie" in engine.design(design_id)["history"][-1]["event"]
