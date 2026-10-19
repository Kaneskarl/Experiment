"""Caption generation through Ollama on this computer; no cloud route or key."""

import http.client
import json
import re

from .ai_captions import (AICaptionError, FACT_FIELDS, LENGTH_GUIDANCE,
                          MAX_RESPONSE_BYTES, SYSTEM_INSTRUCTIONS, _remove_decorations)
from .captions import FOOTER, HASHTAGS, make_caption

OLLAMA_HOST = "127.0.0.1"
OLLAMA_PORT = 11434
DEFAULT_MODEL = "qwen2.5:3b"


def _cloud_name(model: str) -> bool:
    return model.lower().endswith((":cloud", "-cloud"))


def _request(path: str, payload: dict | None = None, timeout: int = 5) -> dict:
    # A fixed loopback connection stays on the computer running Photo Desk.
    # No provider URL, redirect, proxy credential, or OpenAI key is accepted here.
    connection = http.client.HTTPConnection(OLLAMA_HOST, OLLAMA_PORT, timeout=timeout)
    try:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        connection.request("POST" if payload is not None else "GET", path, body=body,
                           headers={"Content-Type": "application/json", "Accept": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            if response.status == 404:
                raise AICaptionError("Ollama could not find the model or API. Update Ollama and download the selected model.", 503)
            raise AICaptionError("Ollama could not complete the request. Check that the selected model is installed and try again.", 502)
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise AICaptionError("The local model returned an oversized response. Try a shorter caption.")
        result = json.loads(raw)
        if not isinstance(result, dict) or result.get("error"):
            raise AICaptionError("Ollama returned an unreadable result. Check the local model and try again.")
        return result
    except (OSError, http.client.HTTPException):
        raise AICaptionError("Could not reach Ollama on this computer. Open Ollama, then try again. First-time model loading can take longer.", 503) from None
    except (ValueError, UnicodeDecodeError):
        raise AICaptionError("Ollama returned an unreadable result. Update Ollama and try again.") from None
    finally:
        connection.close()


def _local_models() -> list[str]:
    result = _request("/api/tags")
    if not isinstance(result.get("models"), list):
        raise AICaptionError("Could not read Ollama's installed models. Update Ollama and try again.")
    models = []
    for item in result["models"]:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("model")
        if (isinstance(name, str) and name and not _cloud_name(name)
                and not item.get("remote_host") and not item.get("remote_model")):
            models.append(name)
    return sorted(set(models))


def ollama_status(model: str = DEFAULT_MODEL) -> dict:
    try:
        models = _local_models()
    except AICaptionError as exc:
        return {"running": False, "model_installed": False, "models": [], "model": model, "detail": str(exc)}
    installed = model in models or (":" not in model and f"{model}:latest" in models)
    return {"running": True, "model_installed": installed, "models": models, "model": model,
            "detail": "Ollama is running and the local model is installed." if installed else
            f"Ollama is running. Download this model first: ollama pull {model}"}


def generate_local_caption(event: dict, *, model: str = DEFAULT_MODEL, style: str = "album",
                           photo_caption: str = "", include_footer: bool = True,
                           include_credit: bool = True, length: str = "standard", instructions: str = "") -> dict:
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}", model) or _cloud_name(model):
        raise AICaptionError("Choose a downloaded local Ollama model such as qwen2.5:3b.", 400)
    if style not in ("album", "photo") or length not in LENGTH_GUIDANCE:
        raise AICaptionError("Choose a supported caption style and length.", 400)
    if not isinstance(photo_caption, str) or not isinstance(instructions, str) or len(photo_caption) > 8000 or len(instructions) > 2000:
        raise AICaptionError("Shorten the photo description or writing preferences and try again.", 400)
    if not isinstance(event, dict):
        raise AICaptionError("Supply confirmed event facts before drafting.", 400)
    facts = {key: event.get(key, "") for key in FACT_FIELDS}
    if (any(not isinstance(value, str) for value in facts.values())
            or not facts["name"].strip() or sum(map(len, facts.values())) > 24000):
        raise AICaptionError("Supply an event name and keep event details under 24,000 characters.", 400)
    try:
        template = make_caption(facts, style=style, photo_caption=photo_caption,
                                include_footer=False, include_credit=False)
    except (KeyError, ValueError, TypeError):
        raise AICaptionError("Supply the event name and a valid date before drafting.", 400) from None
    status = ollama_status(model)
    if not status["running"] or not status["model_installed"]:
        raise AICaptionError(status["detail"], 503)
    payload = {"model": model, "stream": False, "keep_alive": "5m",
               "messages": [{"role": "system", "content": SYSTEM_INSTRUCTIONS},
                            {"role": "user", "content": json.dumps({
                                "event_facts": facts, "style": style,
                                "photo_description": photo_caption.strip() if style == "photo" else "",
                                "length_guidance": LENGTH_GUIDANCE[length],
                                "writing_preferences": instructions.strip()}, ensure_ascii=False)}],
               "format": {"type": "object", "properties": {"caption": {"type": "string"}},
                          "required": ["caption"], "additionalProperties": False},
               "options": {"temperature": .3, "num_ctx": 16384, "num_predict": 1200}}
    result = _request("/api/chat", payload, timeout=180)
    if result.get("done") is not True or result.get("done_reason") == "length":
        raise AICaptionError("The local caption was incomplete. Try a shorter caption or fewer event notes.")
    message = result.get("message")
    try:
        content = json.loads(message["content"]) if isinstance(message, dict) else None
        text = content.get("caption") if isinstance(content, dict) else None
    except (KeyError, ValueError, TypeError):
        text = None
    if not isinstance(text, str) or not text.strip():
        raise AICaptionError("The local model did not return a readable caption. Try generating again.")
    prose = _remove_decorations(text)
    if not prose:
        raise AICaptionError("The local model did not return caption prose. Try generating again.")
    parts = [prose]
    credit_value = event.get("photographer", "")
    credit = credit_value.strip() if isinstance(credit_value, str) else ""
    if include_credit and credit:
        parts.append(f"{'Photos' if style == 'album' else 'Photo'}: {credit}")
    if include_footer:
        parts.extend([FOOTER, HASHTAGS])
    return {"text": "\n\n".join(parts), "missing": template["missing"], "mode": "ai",
            "provider": "Ollama", "model": model,
            "notice": "Local AI draft. Confirm every name, date, number, and claim before posting."}
