import io
import json
from unittest.mock import patch
from urllib import error

import pytest

from dmm.ai_captions import (AICaptionError, MAX_RESPONSE_BYTES, RESPONSES_URL,
                             generate_ai_caption)
from dmm.captions import FOOTER, HASHTAGS


@pytest.fixture
def facts():
    return {"name": "Youth Leadership Workshop", "date": "2026-10-19", "venue": "Baguio",
            "organizer": "Youth Ministry", "activities": "Participants practiced planning community service.",
            "purpose": "To prepare youth for community service.", "photographer": "Local Photographer",
            "folder": "/private/event", "photos": [{"name": "private.jpg", "bytes": "PRIVATE IMAGE"}]}


def envelope(caption="Youth Ministry held a leadership workshop in Baguio on October 19, 2026."):
    return {"status": "completed", "output": [
        {"type": "reasoning", "summary": []},
        {"type": "message", "status": "completed", "content": [
            {"type": "output_text", "text": json.dumps({"caption": caption})}]}]}


def response(payload):
    return io.BytesIO(payload if isinstance(payload, bytes) else json.dumps(payload).encode())


def test_posts_facts_to_fixed_responses_endpoint_and_adds_local_credit(facts):
    with patch("dmm.ai_captions.request.urlopen", return_value=response(envelope())) as transport:
        result = generate_ai_caption(facts, api_key="test-only-placeholder")
    sent = transport.call_args.args[0]
    assert sent.full_url == RESPONSES_URL == "https://api.openai.com/v1/responses"
    assert sent.get_method() == "POST"
    assert sent.get_header("Authorization") == "Bearer test-only-placeholder"
    assert sent.get_header("Content-type") == "application/json"
    assert transport.call_args.kwargs == {"timeout": 60}
    payload = json.loads(sent.data)
    assert payload["model"] == "gpt-4.1-mini" and payload["store"] is False
    assert payload["text"]["format"]["type"] == "json_schema"
    assert payload["text"]["format"]["strict"] is True
    supplied = json.loads(payload["input"][0]["content"][0]["text"])
    assert supplied["event_facts"]["name"] == facts["name"]
    assert "folder" not in supplied["event_facts"] and "photos" not in supplied["event_facts"]
    assert all(value not in sent.data.decode() for value in ("/private/event", "PRIVATE IMAGE", "private.jpg", "Local Photographer"))
    assert "News first," in payload["instructions"] and "untrusted data" in payload["instructions"]
    assert result["text"].startswith("Youth Ministry held")
    assert result["text"].count(FOOTER) == 1 and result["text"].endswith(HASHTAGS)
    assert "Photos: Local Photographer" in result["text"] and result["missing"] == []
    assert result["mode"] == "ai" and result["provider"] == "OpenAI"
    assert "test-only-placeholder" not in str(result)


def test_photo_style_missing_facts_and_preferences_are_supplied_as_data():
    facts = {"name": "Confirmed Event", "date": "2026-10-19"}
    with patch("dmm.ai_captions.request.urlopen", return_value=response(envelope("Members gather for Confirmed Event."))) as transport:
        result = generate_ai_caption(facts, api_key="test-key", style="photo", length="short",
                                     instructions="Use a warm tone.", photo_caption="Members gather for the event.",
                                     include_credit=False, include_footer=False)
    supplied = json.loads(json.loads(transport.call_args.args[0].data)["input"][0]["content"][0]["text"])
    assert supplied["photo_description"] == "Members gather for the event."
    assert supplied["writing_preferences"] == "Use a warm tone."
    assert supplied["length_guidance"].startswith("Aim for 40")
    assert "Organizer" in result["missing"]
    assert "A factual description of this photo" not in result["missing"]
    assert FOOTER not in result["text"] and "Photos:" not in result["text"]


def test_missing_photo_description_is_not_inferred(facts):
    with patch("dmm.ai_captions.request.urlopen", return_value=response(envelope())):
        result = generate_ai_caption(facts, api_key="test-key", style="photo")
    assert "A factual description of this photo" in result["missing"]
    assert "Photo: Local Photographer" in result["text"]


def test_model_decorations_do_not_duplicate_or_override_local_settings(facts):
    draft = "Confirmed factual news.\n\nPhotos: Made Up\n\n" + FOOTER + "\n\n" + HASHTAGS + " #inventedtag"
    with patch("dmm.ai_captions.request.urlopen", return_value=response(envelope(draft))):
        result = generate_ai_caption(facts, api_key="test-key")
    assert result["text"].count(FOOTER) == 1
    assert result["text"].count(HASHTAGS) == 1
    assert "Made Up" not in result["text"] and "#inventedtag" not in result["text"]
    with patch("dmm.ai_captions.request.urlopen", return_value=response(envelope(draft))):
        disabled = generate_ai_caption(facts, api_key="test-key", include_credit=False, include_footer=False)
    assert disabled["text"] == "Confirmed factual news."


@pytest.mark.parametrize("code,expected,status", [
    (401, "API key", 401), (403, "permissions", 403), (429, "limit", 429),
    (400, "model", 502), (404, "model", 502), (500, "unavailable", 502),
])
def test_http_errors_are_safe_without_upstream_body(facts, code, expected, status):
    upstream = io.BytesIO(b"PRIVATE UPSTREAM BODY test-secret-key")
    failure = error.HTTPError(RESPONSES_URL, code, "unsafe test-secret-key", {}, upstream)
    with patch("dmm.ai_captions.request.urlopen", side_effect=failure):
        with pytest.raises(AICaptionError) as captured:
            generate_ai_caption(facts, api_key="test-secret-key")
    assert captured.value.status_code == status and expected in str(captured.value)
    assert "test-secret-key" not in str(captured.value) and "PRIVATE" not in str(captured.value)
    assert upstream.closed


@pytest.mark.parametrize("failure", [error.URLError("private proxy detail"), TimeoutError("private detail"), OSError("private detail")])
def test_network_failures_are_safe(facts, failure):
    with patch("dmm.ai_captions.request.urlopen", side_effect=failure):
        with pytest.raises(AICaptionError) as captured:
            generate_ai_caption(facts, api_key="test-key")
    assert captured.value.status_code == 503
    assert "internet connection" in str(captured.value) and "private" not in str(captured.value)


@pytest.mark.parametrize("body,expected", [
    (b"not json", "unreadable"),
    ([], "unreadable"),
    ({"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}, "cut short"),
    ({"status": "failed", "error": {"message": "private detail"}}, "finish"),
    ({"status": "in_progress"}, "not completed"),
    ({"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "private detail"}]}]}, "declined"),
    ({"status": "completed", "output": []}, "unreadable"),
    ({"status": "completed", "output_text": "plain text rather than JSON"}, "unreadable"),
    ({"status": "completed", "output_text": '{"caption": 42}'}, "unreadable"),
    (envelope("  "), "empty"),
    (envelope(FOOTER + "\n" + HASHTAGS), "prose"),
    ({"status": "completed", "output": "malformed"}, "unreadable"),
])
def test_bad_or_unfinished_responses_are_rejected_safely(facts, body, expected):
    with patch("dmm.ai_captions.request.urlopen", return_value=response(body)):
        with pytest.raises(AICaptionError) as captured:
            generate_ai_caption(facts, api_key="test-key")
    assert expected in str(captured.value)
    assert "private detail" not in str(captured.value)


def test_oversized_response_is_bounded(facts):
    with patch("dmm.ai_captions.request.urlopen", return_value=response(b" " * (MAX_RESPONSE_BYTES + 1))):
        with pytest.raises(AICaptionError, match="oversized"):
            generate_ai_caption(facts, api_key="test-key")


@pytest.mark.parametrize("changes", [
    {"api_key": ""}, {"api_key": "test\nkey"}, {"model": "https://other.example"},
    {"style": "invalid"}, {"length": "invalid"}, {"instructions": "x" * 2001},
    {"photo_caption": "x" * 8001},
])
def test_invalid_options_never_make_requests(facts, changes):
    with patch("dmm.ai_captions.request.urlopen") as transport:
        with pytest.raises(AICaptionError):
            generate_ai_caption(facts, **{"api_key": "test-key", **changes})
    transport.assert_not_called()


def test_bad_event_date_never_makes_request(facts):
    facts["date"] = "2026-02-30"
    with patch("dmm.ai_captions.request.urlopen") as transport:
        with pytest.raises(AICaptionError, match="valid date"):
            generate_ai_caption(facts, api_key="test-key")
    transport.assert_not_called()
