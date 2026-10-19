"""Local event folders and atomic manifests; original photo bytes are never edited."""

import json
import os
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_name(value: str, fallback: str = "event") -> str:
    name = re.sub(r'[^\w .-]', "", value, flags=re.UNICODE).strip(" .")[:90]
    # Also avoid Windows device names, including names such as CON.jpg.
    if not name or name.split(".")[0].upper() in {
        "CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)],
        *[f"LPT{i}" for i in range(1, 10)]
    }:
        return fallback
    return name


def atomic_json(path: Path, data: dict) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)


class Store:
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.template = self.root / ".branding" / "default.png"

    def event_path(self, event_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", event_id):
            raise KeyError("Event not found.")
        for path in self.root.glob(f"*_{event_id[:8]}"):
            manifest = path / "event.json"
            if path.is_dir() and not path.is_symlink() and manifest.is_file():
                if json.loads(manifest.read_text(encoding="utf-8")).get("id") == event_id:
                    return path
        raise KeyError("Event not found.")

    def read(self, event_id: str) -> dict:
        return json.loads((self.event_path(event_id) / "event.json").read_text(encoding="utf-8"))

    def save(self, event: dict) -> None:
        event["updated_at"] = now()
        atomic_json(self.event_path(event["id"]) / "event.json", event)

    def list_events(self) -> list:
        events = []
        for path in self.root.glob("*/event.json"):
            if path.parent.is_symlink():
                continue
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                if not re.fullmatch(r"[a-f0-9]{32}", item.get("id", "")):
                    continue
                events.append(self.public(item))
            except (ValueError, OSError, KeyError):
                continue
        return sorted(events, key=lambda e: e["created_at"], reverse=True)

    def create(self, details: dict) -> dict:
        event_id = uuid.uuid4().hex
        folder = self.root / f'{details["date"]}_{safe_name(details["name"])}_{event_id[:8]}'
        folder.mkdir()
        for name in ("RAW", "EDITED", "CAPTIONS", ".cache"):
            (folder / name).mkdir()
        if self.template.exists():
            shutil.copyfile(self.template, folder / "watermark.png")
        event = {**details, "id": event_id, "created_at": now(), "updated_at": now(),
                 "photos": [], "opacity": 1.0, "long_edge": 2048, "format": "jpeg"}
        atomic_json(folder / "event.json", event)
        return self.public(event)

    def public(self, event: dict) -> dict:
        folder = self.event_path(event["id"])
        return {**event, "folder": str(folder), "has_watermark": (folder / "watermark.png").exists(),
                "caption_saved": (folder / "CAPTIONS" / "caption.txt").exists()}

    def photo(self, event_id: str, photo_id: str) -> tuple[dict, dict, Path]:
        event = self.read(event_id)
        for photo in event["photos"]:
            if photo["id"] == photo_id:
                return event, photo, self.event_path(event_id)
        raise KeyError("Photo not found.")

    @staticmethod
    def invalidate(event: dict) -> None:
        for photo in event["photos"]:
            photo.pop("exported_at", None)
