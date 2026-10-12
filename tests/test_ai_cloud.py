"""Adaptateurs cloud et ComfyUI — tests SIMULÉS.

Un serveur HTTP local reproduit les contrats publiés (Meshy openapi/v1, Anthropic Messages API,
API HTTP de ComfyUI). Ces tests vérifient le protocole, le consentement, les reprises et la
gestion des erreurs ; ils ne prouvent PAS le fonctionnement des services réels (aucune clé
n'était disponible). Les clés utilisées sont factices.
"""

from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from lsfcars.ai import http as ai_http
from lsfcars.ai.engines.anthropic import AnthropicEngine
from lsfcars.ai.engines.base import Capability, GenerationRequest, JobContext, ReferenceInput, Status
from lsfcars.ai.engines.comfyui import ComfyUIEngine
from lsfcars.ai.engines.meshy import MeshyEngine, data_uri
from lsfcars.ai.errors import AuthError, ConsentRequired, NetworkError, ProviderError, QuotaError
from lsfcars.ai.secrets import SecretStore

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
GLB = (SAMPLES / "vehicule_livree.glb").read_bytes()
FAKE_KEY = "cle-de-test-factice-0000"


class Fake:
    """État partagé du serveur simulé (scénarios d'erreurs, requêtes reçues)."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict]] = []
        self.fail_next: list[int] = []  # statuts HTTP renvoyés aux prochaines requêtes
        self.polls = 0
        self.task_status = "SUCCEEDED"
        self.url = ""


def _meshy(handler, fake: Fake, method: str, path: str, raw: bytes, headers, host: str) -> None:  # type: ignore[no-untyped-def]
    if headers.get("Authorization") != f"Bearer {FAKE_KEY}":
        handler.send_json(401, {"message": "Invalid API key"})
    elif path == "/openapi/v1/balance":
        handler.send_json(200, {"balance": 120, "monthly_credits": 100, "permanent_credits": 20})
    elif method == "POST" and path in ("/openapi/v1/image-to-3d", "/openapi/v1/multi-image-to-3d"):
        data = json.loads(raw)
        images = data.get("image_urls") or [data.get("image_url")]
        assert all(i.startswith("data:image/png;base64,") for i in images)
        handler.send_json(200, {"result": "task-123"})
    elif path.endswith("/task-123"):
        fake.polls += 1
        if fake.polls < 2:
            handler.send_json(200, {"id": "task-123", "status": "IN_PROGRESS", "progress": 50})
        elif fake.task_status == "FAILED":
            handler.send_json(
                200, {"status": "FAILED", "progress": 0, "task_error": {"message": "image refusée"}}
            )
        else:
            handler.send_json(
                200,
                {
                    "id": "task-123",
                    "status": "SUCCEEDED",
                    "progress": 100,
                    "consumed_credits": 30,
                    "model_urls": {"glb": f"{host}/files/model.glb"},
                    "texture_urls": [{"base_color": f"{host}/files/base.png"}],
                },
            )
    else:
        handler.send_json(404, {"message": "inconnu"})


def _anthropic(handler, path: str, raw: bytes, headers) -> None:  # type: ignore[no-untyped-def]
    if headers.get("x-api-key") != FAKE_KEY:
        handler.send_json(401, {"error": {"message": "invalid x-api-key"}})
    elif path == "/v1/models":
        handler.send_json(200, {"data": [{"id": "claude-opus-5-5"}]})
    else:
        data = json.loads(raw)
        assert headers.get("anthropic-version") == "2023-06-01"
        assert any(block["type"] == "image" for block in data["messages"][0]["content"])
        text = json.dumps({"type": "sedan", "real_brands": [], "distinctive": ["toit plat"]})
        handler.send_json(
            200,
            {
                "content": [{"type": "text", "text": f"```json\n{text}\n```"}],
                "usage": {"input_tokens": 1200, "output_tokens": 80},
            },
        )


def _comfyui(handler, fake: Fake, path: str, full_path: str, raw: bytes) -> None:  # type: ignore[no-untyped-def]
    if path == "/system_stats":
        devices = [{"name": "cuda:0", "vram_total": 8 * 2**30}]
        handler.send_json(200, {"system": {"comfyui_version": "0.3.test"}, "devices": devices})
    elif path == "/object_info":
        handler.send_json(200, {"LoadImage": {}, "FakeImageTo3D": {}, "SaveGLB": {}})
    elif path == "/upload/image":
        assert b'name="image"' in raw
        handler.send_json(200, {"name": "lsf_upload.png", "subfolder": "", "type": "input"})
    elif path == "/prompt":
        assert json.loads(raw)["prompt"]["1"]["inputs"]["image"] == "lsf_upload.png"
        handler.send_json(200, {"prompt_id": "p-1", "number": 1, "node_errors": {}})
    elif path == "/history/p-1":
        fake.polls += 1
        if fake.polls < 2:
            handler.send_json(200, {})
        else:
            output = {"meshes": [{"filename": "car.glb", "subfolder": "3d", "type": "output"}]}
            entry = {"status": {"status_str": "success", "completed": True}, "outputs": {"3": output}}
            handler.send_json(200, {"p-1": entry})
    elif path == "/view":
        assert "filename=car.glb" in full_path
        handler.send_bytes(200, GLB, "model/gltf-binary")
    elif path == "/interrupt":
        handler.send_json(200, {})
    else:
        handler.send_json(404, {"message": "inconnu"})


def make_handler(fake: Fake):  # type: ignore[no-untyped-def]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:  # type: ignore[no-untyped-def]
            return

        def send_bytes(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, code: int, payload: dict) -> None:
            self.send_bytes(code, json.dumps(payload).encode(), "application/json")

        def _route(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            headers = self.headers  # insensible à la casse (urllib normalise les noms d'en-têtes)
            fake.requests.append((method, self.path, dict(headers.items())))
            if fake.fail_next:
                code = fake.fail_next.pop(0)
                self.send_json(code, {"message": f"erreur simulée {code}"})
                return
            host = f"http://127.0.0.1:{self.server.server_address[1]}"
            path = self.path.split("?")[0]
            if path.startswith("/openapi/"):
                _meshy(self, fake, method, path, raw, headers, host)
            elif path == "/files/model.glb":
                self.send_bytes(200, GLB, "model/gltf-binary")
            elif path == "/files/base.png":
                self.send_bytes(200, (SAMPLES / "references" / "demo_avant.png").read_bytes(), "image/png")
            elif path.startswith("/v1/"):
                _anthropic(self, path, raw, headers)
            else:
                _comfyui(self, fake, path, self.path, raw)

        def do_GET(self) -> None:  # noqa: N802
            self._route("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._route("POST")

    return Handler


@pytest.fixture
def server():
    fake = Fake()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(fake))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    fake.url = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield fake
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def secrets(tmp_path):
    store = SecretStore(tmp_path / "ai_secrets.json")
    store.set("meshy", FAKE_KEY)
    store.set("anthropic", FAKE_KEY)
    return store


def references() -> list[ReferenceInput]:
    folder = SAMPLES / "references"
    return [
        ReferenceInput(folder / "demo_trois_quarts.png", "three_quarter"),
        ReferenceInput(folder / "demo_profil_gauche.png", "left"),
    ]


def meshy(server, secrets) -> MeshyEngine:  # type: ignore[no-untyped-def]
    return MeshyEngine({"base_url": server.url, "poll_interval": 0.01, "backoff": 0.01}, secrets=secrets)


def test_secret_store_never_writes_clear_keys(tmp_path, monkeypatch):
    store = SecretStore(tmp_path / "s.json")
    store.set("meshy", FAKE_KEY)
    assert FAKE_KEY not in (tmp_path / "s.json").read_text(encoding="utf-8")  # chiffré (DPAPI)
    assert store.get("meshy") == FAKE_KEY and store.source("meshy") == "coffre Windows (DPAPI)"
    monkeypatch.setenv("LSFCARS_MESHY_API_KEY", "autre-cle-factice-99")
    assert store.get("meshy") == "autre-cle-factice-99"
    assert store.source("meshy") == "variable d'environnement"
    monkeypatch.delenv("LSFCARS_MESHY_API_KEY")
    assert store.delete("meshy") and store.get("meshy") is None


def test_meshy_unconfigured_and_connection(server, secrets, tmp_path):
    empty = MeshyEngine({"base_url": server.url}, secrets=SecretStore(tmp_path / "vide.json"))
    assert empty.detect().status is Status.UNCONFIGURED
    engine = meshy(server, secrets)
    result = engine.test_connection()
    assert result.ok and "120 crédits" in result.message
    assert engine.estimate(GenerationRequest(Capability.IMAGE_TO_3D, [], tmp_path, "high")).paid


def test_meshy_generation_requires_consent_then_downloads(server, secrets, tmp_path):
    engine = meshy(server, secrets)
    request = GenerationRequest(Capability.MULTIVIEW_3D, references(), tmp_path / "out", "balanced")
    with pytest.raises(ConsentRequired):
        engine.run(request, JobContext())
    assert not any(path.startswith("/openapi/v1/multi") for _m, path, _h in server.requests)  # rien envoyé
    request.allow_cloud = True
    with pytest.raises(ConsentRequired):  # coût non accepté
        engine.run(request, JobContext())
    request.allow_paid = True
    progress: list[float] = []
    output = engine.run(request, JobContext(progress=lambda v, t: progress.append(v)))
    assert output.files["model"].read_bytes() == GLB
    assert output.files["base_color"].is_file()
    assert output.reported_cost == "30 crédits Meshy"  # coût communiqué par le fournisseur
    assert output.used_views == ["three_quarter", "left"]
    assert progress[-1] == pytest.approx(1.0)


def test_network_errors_are_retried_then_reported(server, secrets, tmp_path):
    engine = meshy(server, secrets)
    engine.configure({"backoff": 0.01})
    server.fail_next = [503, 502]  # deux erreurs transitoires puis succès
    result = ai_http.request_json(
        "GET", f"{server.url}/openapi/v1/balance", headers={"Authorization": f"Bearer {FAKE_KEY}"},
        retries=2, backoff=0.01, provider="Meshy",
    )  # fmt: skip
    assert result["balance"] == 120
    assert [e["status"] for e in ai_http.REQUEST_LOG.entries[-3:]] == [503, 502, 200]
    assert FAKE_KEY not in json.dumps(ai_http.REQUEST_LOG.entries)  # jamais de clé dans le journal
    with pytest.raises(NetworkError):  # serveur injoignable
        ai_http.request("GET", "http://127.0.0.1:9/indisponible", retries=1, backoff=0.01, timeout=1)
    server.fail_next = [402]
    with pytest.raises(QuotaError):
        engine.test_connection()
    store = SecretStore(tmp_path / "x.json")
    store.set("meshy", "mauvaise-cle-factice-1")
    with pytest.raises(AuthError):
        MeshyEngine({"base_url": server.url}, secrets=store).test_connection()


def test_meshy_failed_task_is_explained(server, secrets, tmp_path):
    server.task_status = "FAILED"
    request = GenerationRequest(
        Capability.IMAGE_TO_3D, references()[:1], tmp_path, allow_cloud=True, allow_paid=True
    )
    with pytest.raises(ProviderError, match="image refusée"):
        meshy(server, secrets).run(request, JobContext())


def test_anthropic_vision_is_parsed_and_labelled(server, secrets, tmp_path):
    engine = AnthropicEngine({"base_url": server.url, "backoff": 0.01}, secrets=secrets)
    assert "disponible" in engine.test_connection().message
    request = GenerationRequest(Capability.VISION, references(), tmp_path, allow_cloud=True, allow_paid=True)
    output = engine.run(request, JobContext())
    assert output.data["result"]["type"] == "sedan"
    assert "1200 jetons" in output.reported_cost
    assert engine.estimate(request).amount is None  # coût non inventé


def test_comfyui_workflow_roundtrip(server, tmp_path):
    workflow = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "placeholder.png"}},
        "2": {"class_type": "FakeImageTo3D", "inputs": {"image": ["1", 0]}},
        "3": {"class_type": "SaveGLB", "inputs": {"mesh": ["2", 0]}},
    }
    path = tmp_path / "workflow_api.json"
    path.write_text(json.dumps(workflow), encoding="utf-8")
    engine = ComfyUIEngine({"url": server.url, "poll_interval": 0.01})
    assert engine.detect().status is Status.UNCONFIGURED  # serveur présent, workflow absent
    engine.configure({"workflow": str(path)})
    assert engine.detect().ok
    output = engine.run(
        GenerationRequest(Capability.IMAGE_TO_3D, references()[:1], tmp_path / "out"), JobContext()
    )
    assert output.files["model"].read_bytes() == GLB
    workflow["2"]["class_type"] = "NoeudAbsent"
    path.write_text(json.dumps(workflow), encoding="utf-8")
    availability = engine.detect()
    assert availability.status is Status.ERROR and "NoeudAbsent" in availability.message


def test_comfyui_absent_server():
    assert ComfyUIEngine({"url": "http://127.0.0.1:9"}).detect().status is Status.MISSING


def test_data_uri_encoding():
    uri = data_uri(SAMPLES / "references" / "demo_avant.png")
    assert base64.b64decode(uri.split(",", 1)[1])[:8] == b"\x89PNG\r\n\x1a\n"
