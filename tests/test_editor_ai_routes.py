"""Exercise image edits and AI configuration through the local HTTP interface."""

import hashlib
import io
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from dmm.ai_captions import AICaptionError
from dmm.captions import FOOTER, HASHTAGS
from dmm.server import create_app


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    for name in ("DMM_AI_API_KEY", "OPENAI_API_KEY", "DMM_AI_MODEL"):
        monkeypatch.delenv(name, raising=False)
    apps = []
    with ExitStack() as stack:
        def factory(root=None):
            app = create_app(root or tmp_path / f"events-{len(apps)}")
            apps.append(app)
            return stack.enter_context(TestClient(app, base_url="http://127.0.0.1"))

        yield factory
    for app in apps:
        app.state.pool.shutdown(wait=True)


@pytest.fixture
def client(make_client):
    return make_client()


def create_event(client):
    response = client.post("/api/events", json={
        "name": "DMM Youth Gathering", "date": "2026-10-19", "venue": "Baguio",
        "organizer": "Youth Ministry", "photographer": "Event Photographer",
        "activities": "Participants attended a leadership workshop.",
        "purpose": "The workshop focused on service.",
    })
    assert response.status_code == 201, response.text
    return response.json()


def png_bytes(image):
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def add_photo(client, event):
    image = Image.new("RGB", (80, 40), (40, 40, 40))
    image.paste((120, 120, 120), (40, 0, 80, 40))
    response = client.post(f'/api/events/{event["id"]}/photos', files={
        "files": ("photo.png", png_bytes(image), "image/png"),
    })
    assert response.status_code == 200, response.text
    return response.json()["accepted"][0]


def add_watermark(client, event):
    image = Image.new("RGBA", (40, 80), (0, 0, 0, 0))
    image.paste((0, 255, 0, 255), (0, 0, 5, 80))
    response = client.post(f'/api/events/{event["id"]}/watermark', files={
        "file": ("watermark.png", png_bytes(image), "image/png"),
    })
    assert response.status_code == 200, response.text


def photo_url(event, photo):
    return f'/api/events/{event["id"]}/photos/{photo["id"]}'


def export(client, event):
    response = client.post(f'/api/events/{event["id"]}/export')
    assert response.status_code == 202, response.text
    job = response.json()
    deadline = time.monotonic() + 10
    while job["status"] == "running" and time.monotonic() < deadline:
        time.sleep(.01)
        response = client.get(f'/api/jobs/{job["id"]}')
        assert response.status_code == 200, response.text
        job = response.json()
    assert job["status"] == "completed", job
    return job


def test_partial_photo_updates_preserve_edits_framing_and_selection(client):
    event = create_event(client)
    photo = add_photo(client, event)
    url = photo_url(event, photo)
    changes = {"x": .2, "y": .8, "zoom": 1.5, "rotation": 90,
               "flip_horizontal": True, "flip_vertical": True, "brightness": 1.4,
               "contrast": .8, "saturation": .7, "sharpness": 1.6,
               "selected": False, "favorite": True}
    response = client.patch(url, json=changes)
    assert response.status_code == 200, response.text
    assert all(response.json()[key] == value for key, value in changes.items())
    response = client.patch(url, json={"favorite": False})
    assert response.status_code == 200, response.text
    changes["favorite"] = False
    assert all(response.json()[key] == value for key, value in changes.items())
    assert client.patch(url, json={}).json() == response.json()
    reopened = client.get(f'/api/events/{event["id"]}').json()["photos"][0]
    assert all(reopened[key] == value for key, value in changes.items())


@pytest.mark.parametrize("changes", [
    {"rotation": 45}, {"brightness": .1}, {"brightness": 2.1},
    {"contrast": .1}, {"contrast": 2.1}, {"saturation": -.1},
    {"saturation": 2.1}, {"sharpness": -.1}, {"sharpness": 3.1},
])
def test_invalid_edits_are_rejected_without_mutating_photo(client, changes):
    event = create_event(client)
    photo = add_photo(client, event)
    url = photo_url(event, photo)
    before = client.patch(url, json={"rotation": 90, "brightness": 1.3}).json()
    response = client.patch(url, json=changes)
    assert response.status_code == 422, response.text
    after = client.get(f'/api/events/{event["id"]}').json()["photos"][0]
    assert before == after


def test_rotation_and_brightness_reach_unwatermarked_preview_and_png_export(client):
    event = create_event(client)
    photo = add_photo(client, event)
    original = Path(event["folder"]) / "RAW" / photo["name"]
    original_hash = hashlib.sha256(original.read_bytes()).digest()
    url = photo_url(event, photo)
    assert client.patch(url, json={"rotation": 90, "brightness": 1.5}).status_code == 200
    response = client.get(f"{url}/preview")
    assert response.status_code == 200, response.text
    preview = Image.open(io.BytesIO(response.content))
    assert preview.size == (40, 80)
    assert all(abs(value - 60) <= 2 for value in preview.getpixel((25, 20)))
    assert all(abs(value - 180) <= 2 for value in preview.getpixel((25, 60)))

    add_watermark(client, event)
    assert client.put(f'/api/events/{event["id"]}/export-settings', json={
        "format": "png", "long_edge": 0, "opacity": 1,
    }).status_code == 200
    assert export(client, event)["succeeded"] == 1
    output = list((Path(event["folder"]) / "EDITED").glob("*.png"))
    assert len(output) == 1
    with Image.open(output[0]) as edited:
        assert edited.size == (40, 80)
        assert edited.getpixel((25, 20)) == (60, 60, 60)
        assert edited.getpixel((25, 60)) == (180, 180, 180)
        assert edited.getpixel((2, 40)) == (0, 255, 0)
    assert hashlib.sha256(original.read_bytes()).digest() == original_hash


@pytest.mark.parametrize("changes", [
    {"rotation": 90}, {"flip_horizontal": True}, {"flip_vertical": True},
    {"brightness": 1.5}, {"contrast": 1.5}, {"saturation": 0}, {"sharpness": 2},
])
def test_each_image_edit_requires_fresh_export(client, changes):
    event = create_event(client)
    photo = add_photo(client, event)
    add_watermark(client, event)
    export(client, event)
    assert client.get(f'/api/events/{event["id"]}/download').status_code == 200
    response = client.patch(photo_url(event, photo), json=changes)
    assert response.status_code == 200, response.text
    assert "exported_at" not in response.json()
    assert client.get(f'/api/events/{event["id"]}/download').status_code == 400


def test_favorite_change_and_noop_edit_keep_valid_export(client):
    event = create_event(client)
    photo = add_photo(client, event)
    add_watermark(client, event)
    assert client.patch(photo_url(event, photo), json={"brightness": 1.5}).status_code == 200
    export(client, event)
    response = client.patch(photo_url(event, photo), json={"favorite": True, "brightness": 1.5})
    assert response.status_code == 200, response.text
    assert response.json()["exported_at"]
    assert client.get(f'/api/events/{event["id"]}/download').status_code == 200


def test_ai_defaults_expose_configuration_status_without_a_key(client):
    response = client.get("/api/ai/settings")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "configured": False, "model": "gpt-4.1-mini", "provider": "OpenAI", "source": "none",
    }
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("contents", ["[]", "null", '"wrong shape"', "not json", '{"model": []}'])
def test_malformed_optional_ai_settings_do_not_block_photo_workspace(tmp_path, make_client, contents):
    root = tmp_path / "malformed-settings"
    root.mkdir()
    (root / ".ai-settings.json").write_text(contents, encoding="utf-8")
    reopened = make_client(root)
    assert reopened.get("/api/health").json()["status"] == "ok"
    assert reopened.get("/api/ai/settings").json()["model"] == "gpt-4.1-mini"


def test_ai_session_key_is_never_echoed_or_saved_and_model_survives_reopen(client, make_client):
    key = "sk-test-session-private-credential"
    response = client.put("/api/ai/settings", json={"api_key": key, "model": "gpt-4.1"})
    assert response.status_code == 200, response.text
    for result in (response, client.get("/api/ai/settings")):
        assert key not in result.text
        assert result.json() == {
            "configured": True, "model": "gpt-4.1", "provider": "OpenAI", "source": "session",
        }
    root = client.app.state.store.root
    files = [path for path in root.rglob("*") if path.is_file()]
    assert all(key.encode() not in path.read_bytes() for path in files)
    reopened = make_client(root)
    result = reopened.get("/api/ai/settings").json()
    assert result == {
        "configured": False, "model": "gpt-4.1", "provider": "OpenAI", "source": "none",
    }
    response = client.delete("/api/ai/session")
    assert response.status_code == 200, response.text
    assert client.get("/api/ai/settings").json()["configured"] is False
    assert key not in response.text


@pytest.mark.parametrize("env_names", [("OPENAI_API_KEY",), ("DMM_AI_API_KEY", "OPENAI_API_KEY")])
def test_ai_environment_credentials_and_session_override_priority(make_client, monkeypatch, env_names):
    keys = {name: f"sk-test-{name.lower()}-secret" for name in env_names}
    for name, key in keys.items():
        monkeypatch.setenv(name, key)
    monkeypatch.setenv("DMM_AI_MODEL", "gpt-4.1")
    client = make_client()
    event = create_event(client)
    route = f'/api/events/{event["id"]}/captions/generate'
    generated = {"text": "AI draft.", "missing": [], "notice": "Review this draft."}
    model = Mock(return_value=generated)
    monkeypatch.setattr("dmm.server.generate_ai_caption", model)
    settings = client.get("/api/ai/settings")
    assert settings.json()["source"] == "environment"
    assert settings.json()["model"] == "gpt-4.1"
    assert all(key not in settings.text for key in keys.values())
    assert client.post(route, json={"mode": "ai"}).status_code == 200
    expected_key = keys.get("DMM_AI_API_KEY", keys.get("OPENAI_API_KEY"))
    assert model.call_args.kwargs["api_key"] == expected_key
    session_key = "sk-test-session-override"
    assert client.put("/api/ai/settings", json={"api_key": session_key}).status_code == 200
    assert client.get("/api/ai/settings").json()["source"] == "session"
    assert client.post(route, json={"mode": "ai"}).status_code == 200
    assert model.call_args.kwargs["api_key"] == session_key
    assert client.delete("/api/ai/session").status_code == 200
    assert client.get("/api/ai/settings").json()["source"] == "environment"
    assert client.post(route, json={"mode": "ai"}).status_code == 200
    assert model.call_args.kwargs["api_key"] == expected_key


def test_missing_ai_key_reports_unavailable_instead_of_a_template(client, monkeypatch):
    event = create_event(client)
    model = Mock(side_effect=AssertionError("A keyless request must not reach the AI provider."))
    monkeypatch.setattr("dmm.server.generate_ai_caption", model)
    for body in ({}, {"mode": "ai"}):
        response = client.post(f'/api/events/{event["id"]}/captions/generate', json=body)
        assert response.status_code == 503, response.text
        assert "key" in response.json()["detail"].lower()
        assert "text" not in response.json()
    model.assert_not_called()


def test_explicit_template_mode_works_without_ai_credentials(client, monkeypatch):
    event = create_event(client)
    model = Mock(side_effect=AssertionError("Template mode must remain offline."))
    monkeypatch.setattr("dmm.server.generate_ai_caption", model)
    response = client.post(f'/api/events/{event["id"]}/captions/generate', json={
        "mode": "template", "style": "photo", "photo_caption": "Youth attend a workshop.",
        "include_credit": False, "length": "short", "instructions": "Write plainly.",
    })
    assert response.status_code == 200, response.text
    assert "Youth attend a workshop." in response.json()["text"]
    assert FOOTER in response.json()["text"] and HASHTAGS in response.json()["text"]
    assert "Event Photographer" not in response.json()["text"]
    model.assert_not_called()


@pytest.mark.parametrize("explicit_mode", [True, False])
def test_ai_caption_route_passes_confirmed_facts_and_caption_options(client, monkeypatch, explicit_mode):
    event = create_event(client)
    key = "sk-test-caption-route-secret"
    assert client.put("/api/ai/settings", json={"api_key": key, "model": "gpt-4.1"}).status_code == 200
    result = {"text": "AI-generated draft for review.", "missing": ["Verified outcome"],
              "notice": "Confirm all facts before publication."}
    model = Mock(return_value=result)
    monkeypatch.setattr("dmm.server.generate_ai_caption", model)
    options = {"style": "photo", "photo_caption": "Participants take part in a workshop.",
               "include_footer": False, "include_credit": True, "length": "short",
               "instructions": "Use a clear, warm tone."}
    body = {"mode": "ai", **options} if explicit_mode else options
    response = client.post(f'/api/events/{event["id"]}/captions/generate', json=body)
    assert response.status_code == 200, response.text
    assert response.json() == result
    model.assert_called_once()
    args, kwargs = model.call_args
    assert len(args) == 1
    assert args[0]["id"] == event["id"]
    assert args[0]["activities"] == event["activities"]
    assert kwargs == {"api_key": key, "model": "gpt-4.1", **options}
    assert key not in response.text
    assert not (Path(event["folder"]) / "CAPTIONS" / "caption.txt").exists()


@pytest.mark.parametrize("status_code", [401, 403, 429, 502, 503])
def test_ai_error_keeps_actionable_message_and_does_not_replace_saved_caption(client, monkeypatch, status_code):
    event = create_event(client)
    key = "sk-test-provider-error-secret"
    assert client.put("/api/ai/settings", json={"api_key": key}).status_code == 200
    assert client.put(f'/api/events/{event["id"]}/captions', json={
        "text": "Previously reviewed caption.",
    }).status_code == 200
    message = "OpenAI could not create this draft. Check your connection and retry."
    monkeypatch.setattr("dmm.server.generate_ai_caption", Mock(side_effect=AICaptionError(message, status_code)))
    response = client.post(f'/api/events/{event["id"]}/captions/generate', json={"mode": "ai"})
    assert response.status_code == status_code, response.text
    assert response.json() == {"detail": message}
    assert key not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert client.get(f'/api/events/{event["id"]}/captions').json()["text"] == "Previously reviewed caption."


@pytest.mark.parametrize("options", [
    {"mode": "invalid"}, {"length": "invalid"}, {"instructions": "x" * 1501},
])
def test_invalid_caption_options_do_not_call_ai(client, monkeypatch, options):
    event = create_event(client)
    model = Mock(side_effect=AssertionError("Invalid input must not reach AI."))
    monkeypatch.setattr("dmm.server.generate_ai_caption", model)
    response = client.post(f'/api/events/{event["id"]}/captions/generate', json=options)
    assert response.status_code == 422, response.text
    model.assert_not_called()


def test_invalid_ai_configuration_does_not_echo_key_or_replace_session(client, monkeypatch):
    original = "sk-test-valid-session-secret"
    attempted = "sk-test-invalid-request-secret"
    assert client.put("/api/ai/settings", json={"api_key": original}).status_code == 200
    response = client.put("/api/ai/settings", json={"api_key": attempted, "model": " "})
    assert response.status_code in (400, 422), response.text
    assert original not in response.text and attempted not in response.text
    assert client.get("/api/ai/settings").json()["configured"] is True
    event = create_event(client)
    model = Mock(return_value={"text": "Draft.", "missing": [], "notice": "Review."})
    monkeypatch.setattr("dmm.server.generate_ai_caption", model)
    assert client.post(f'/api/events/{event["id"]}/captions/generate', json={"mode": "ai"}).status_code == 200
    assert model.call_args.kwargs["api_key"] == original
    for path in client.app.state.store.root.rglob("*"):
        if path.is_file():
            assert original.encode() not in path.read_bytes()
            assert attempted.encode() not in path.read_bytes()
