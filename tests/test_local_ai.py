"""Exercise the Ollama protocol over a real loopback HTTP fixture, without a model download."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from dmm import local_ai
from dmm.ai_captions import AICaptionError
from dmm.captions import FOOTER, HASHTAGS
from dmm.server import create_app

FACTS = {"name": "DMM Youth Gathering", "date": "2026-10-19", "venue": "Baguio",
         "organizer": "Youth Ministry", "activities": "Participants attended a workshop.",
         "purpose": "The workshop focused on service.", "photographer": "Test Photographer",
         "folder": "/private/location", "photos": [{"name": "private.jpg"}]}


@pytest.fixture
def ollama(monkeypatch):
    state = {"models": [{"name": "qwen2.5:3b"}], "status": 200,
             "result": {"done": True, "done_reason": "stop", "message": {
                 "role": "assistant", "content": json.dumps({"caption": "Young people attended a workshop in Baguio focused on service."})}},
             "calls": []}

    class Handler(BaseHTTPRequestHandler):
        def respond(self, data, code=200):
            raw = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers(); self.wfile.write(raw)

        def do_GET(self):
            state["calls"].append((self.path, dict(self.headers), None))
            self.respond({"models": state["models"]})

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["calls"].append((self.path, dict(self.headers), payload))
            self.respond(state["result"], state["status"])

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    monkeypatch.setattr(local_ai, "OLLAMA_PORT", server.server_address[1])
    yield state
    server.shutdown(); server.server_close(); thread.join()


@pytest.fixture
def client(tmp_path, monkeypatch):
    for name in ["DMM_AI_API_KEY", "OPENAI_API_KEY", "DMM_AI_MODEL"]:
        monkeypatch.delenv(name, raising=False)
    app = create_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1") as result:
        yield result
    app.state.pool.shutdown(wait=True)


def test_local_chat_protocol_and_factual_privacy_boundary(ollama):
    result = local_ai.generate_local_caption(FACTS, length="short", instructions="Use warm language.")
    assert result["provider"] == "Ollama" and result["mode"] == "ai"
    assert result["text"].endswith(HASHTAGS) and result["text"].count(FOOTER) == 1
    assert "Photos: Test Photographer" in result["text"]
    path, headers, payload = ollama["calls"][-1]
    assert path == "/api/chat" and "Authorization" not in headers
    assert payload["model"] == "qwen2.5:3b" and payload["stream"] is False
    assert payload["format"]["required"] == ["caption"]
    facts = json.loads(payload["messages"][1]["content"])
    assert facts["event_facts"]["name"] == FACTS["name"]
    assert "News first" in payload["messages"][0]["content"]
    assert "40–80" in facts["length_guidance"]
    sent = json.dumps(payload)
    assert "private.jpg" not in sent and "/private/location" not in sent
    assert "Test Photographer" not in sent


def test_local_model_status_excludes_cloud_and_remote_models(ollama):
    ollama["models"] += [{"name": "gpt-oss:120b-cloud"}, {"name": "remote:cloud"},
                         {"name": "alias:latest", "remote_host": "https://example.com"},
                         {"name": "remote-alias", "remote_model": "remote"}]
    status = local_ai.ollama_status()
    assert status["running"] and status["model_installed"]
    assert status["models"] == ["qwen2.5:3b"]


def test_missing_model_is_reported_without_generation(ollama):
    ollama["models"] = []
    with pytest.raises(AICaptionError, match="ollama pull qwen2.5:3b"):
        local_ai.generate_local_caption(FACTS)
    assert all(call[0] != "/api/chat" for call in ollama["calls"])


@pytest.mark.parametrize("result", [
    {"done": False}, {"done": True, "done_reason": "length"},
    {"done": True, "message": {"content": "not json"}},
    {"done": True, "message": {"content": '{"caption":""}'}},
    {"done": True, "message": None},
])
def test_invalid_or_incomplete_model_results_are_not_presented_as_captions(ollama, result):
    ollama["result"] = result
    with pytest.raises(AICaptionError):
        local_ai.generate_local_caption(FACTS)


def test_local_footer_and_credit_flags_are_enforced(ollama):
    ollama["result"]["message"]["content"] = json.dumps({"caption": "Confirmed event prose.\nPhotos: Invented Name\n"+FOOTER+"\n"+HASHTAGS})
    result = local_ai.generate_local_caption(FACTS, include_footer=False, include_credit=False)
    assert result["text"] == "Confirmed event prose."


def test_provider_selection_persists_without_key_and_remembers_each_model(client, ollama):
    client.put("/api/ai/settings", json={"model": "gpt-4.1", "api_key": "test-session-key"})
    result = client.put("/api/ai/settings", json={"provider": "ollama", "model": "qwen2.5:3b"})
    assert result.status_code == 200
    assert result.json() == {"provider": "Ollama", "model": "qwen2.5:3b", "configured": True, "source": "local"}
    assert client.get("/api/settings").json()["ai_requires_internet"] is False
    assert client.get("/api/ai/settings?provider=openai").json()["model"] == "gpt-4.1"
    assert client.get("/api/ai/local-status").json()["model_installed"]
    root = client.app.state.store.root
    saved = json.loads((root / ".ai-settings.json").read_text())
    assert saved["provider"] == "ollama" and "test-session-key" not in json.dumps(saved)
    reopened = create_app(root)
    with TestClient(reopened, base_url="http://127.0.0.1") as other:
        assert other.get("/api/ai/settings").json()["provider"] == "Ollama"
    reopened.state.pool.shutdown(wait=True)
    assert client.put("/api/ai/settings", json={"provider": "openai"}).json()["model"] == "gpt-4.1"


def test_local_route_never_calls_openai_even_when_a_key_exists(client, ollama, monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Local AI must never fall back to OpenAI")
    monkeypatch.setattr("dmm.server.generate_ai_caption", forbidden)
    monkeypatch.setenv("DMM_AI_API_KEY", "test-key-must-not-leave-this-process")
    event = client.post("/api/events", json={key:value for key,value in FACTS.items() if key not in ("folder", "photos")}).json()
    client.put("/api/ai/settings", json={"provider": "ollama", "model": "qwen2.5:3b"})
    route = f'/api/events/{event["id"]}/captions/generate'
    response = client.post(route, json={"mode": "ai"})
    assert response.status_code == 200 and response.json()["provider"] == "Ollama"
    assert all("Authorization" not in headers for _path, headers, _payload in ollama["calls"])
    ollama["models"] = []
    response = client.post(route, json={"mode": "ai"})
    assert response.status_code == 503 and "ollama pull" in response.json()["detail"]


@pytest.mark.parametrize("model", ["remote:cloud", "gpt-oss:120b-cloud"])
def test_cloud_tag_is_rejected_in_local_mode(client, model):
    response = client.put("/api/ai/settings", json={"provider": "ollama", "model": model})
    assert response.status_code == 400
    assert client.get("/api/ai/settings").json()["provider"] == "OpenAI"
