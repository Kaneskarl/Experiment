"""Loopback-only web application. No photo or caption is sent to a remote service."""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.background import BackgroundTask
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .captions import make_caption
from .imaging import compose, load_overlay, load_photo, thumbnail
from .storage import Store, now, safe_name

MAX_UPLOAD = 60 * 1024 * 1024


class EventDetails(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    date: str
    venue: str = Field(default="", max_length=300)
    organizer: str = Field(default="", max_length=300)
    theme: str = Field(default="", max_length=500)
    photographer: str = Field(default="", max_length=200)
    activities: str = Field(default="", max_length=8000)
    purpose: str = Field(default="", max_length=4000)
    outcomes: str = Field(default="", max_length=4000)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("Please enter an event name.")
        return value.strip()

    @field_validator("date")
    @classmethod
    def check_date(cls, value):
        return date.fromisoformat(value).isoformat()


class PhotoSettings(BaseModel):
    x: float = Field(default=.5, ge=0, le=1)
    y: float = Field(default=.5, ge=0, le=1)
    zoom: float = Field(default=1, ge=1, le=3)
    selected: bool = True
    favorite: bool = False


class ExportSettings(BaseModel):
    opacity: float = Field(default=1, ge=.1, le=1)
    long_edge: Literal[0, 2048, 3200] = 2048
    format: Literal["jpeg", "png"] = "jpeg"


class CaptionRequest(BaseModel):
    style: Literal["album", "photo"] = "album"
    photo_caption: str = Field(default="", max_length=8000)
    include_footer: bool = True
    include_credit: bool = True


class SaveCaption(BaseModel):
    text: str = Field(min_length=1, max_length=30000)


def receive(file: UploadFile, destination: Path) -> None:
    """Copy with a bounded size; remove incomplete copies on all failure paths."""
    try:
        total = 0
        with destination.open("wb") as stream:
            while chunk := file.file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD:
                    raise ValueError("Each file must be under 60 MB.")
                stream.write(chunk)
        if total == 0:
            raise ValueError("This file is empty.")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def create_app(data_dir: Path) -> FastAPI:
    store = Store(data_dir)
    app = FastAPI(title="DMM Photo Desk", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.state.jobs = {}
    pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dmm-export")
    app.state.pool = pool
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.url.path.startswith("/api/"):
            expected = f"{request.url.scheme}://{request.headers.get('host')}"
            if (origin and origin != expected) or request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Open Photo Desk directly to use the local app."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(KeyError)
    async def missing(_request, exc):
        return JSONResponse({"detail": str(exc.args[0])}, status_code=404)

    @app.exception_handler(ValueError)
    async def bad_input(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    def writable(event_id):
        if any(job["event_id"] == event_id and job["status"] == "running"
               for job in app.state.jobs.values()):
            raise HTTPException(409, "Please wait for this event's export to finish.")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "app": "DMM Photo Desk"}

    @app.get("/api/settings")
    def settings():
        return {"data_dir": str(store.root), "has_watermark": store.template.exists(),
                "version": "0.1.0", "offline": True}

    @app.get("/api/events")
    def events():
        with store.lock:
            return store.list_events()

    @app.post("/api/events", status_code=201)
    def create(details: EventDetails):
        with store.lock:
            return store.create(details.model_dump())

    @app.get("/api/events/{event_id}")
    def read_event(event_id: str):
        with store.lock:
            return store.public(store.read(event_id))

    @app.put("/api/events/{event_id}")
    def update_event(event_id: str, details: EventDetails):
        with store.lock:
            writable(event_id)
            event = store.read(event_id)
            event.update(details.model_dump())
            store.save(event)
            return store.public(event)

    @app.post("/api/events/{event_id}/photos")
    def import_photos(event_id: str, files: list[UploadFile] = File(...)):
        if len(files) > 500:
            raise ValueError("Import up to 500 photos at a time.")
        accepted, rejected = [], []
        with store.lock:
            writable(event_id)
            event = store.read(event_id)
            folder = store.event_path(event_id)
            for file in files:
                photo_id = uuid.uuid4().hex
                temp = folder / ".cache" / f"{photo_id}.upload"
                original_name = (file.filename or "photo").replace("\\", "/").split("/")[-1]
                name = safe_name(original_name, f"photo-{photo_id[:8]}")
                destination = folder / "RAW" / name
                counter = 2
                while destination.exists():
                    destination = folder / "RAW" / f"{Path(name).stem}-{counter}{Path(name).suffix}"
                    counter += 1
                try:
                    receive(file, temp)
                    image = load_photo(temp)
                    width, height = image.size
                    thumbnail(temp, folder / ".cache" / f"{photo_id}.jpg")
                    os.replace(temp, destination)
                    photo = {"id": photo_id, "name": destination.name, "width": width,
                             "height": height, "x": .5, "y": .5, "zoom": 1,
                             "selected": True, "favorite": False}
                    event["photos"].append(photo)
                    accepted.append(photo)
                except ValueError as exc:
                    rejected.append({"name": original_name, "reason": str(exc)})
                finally:
                    temp.unlink(missing_ok=True)
                    file.file.close()
            store.save(event)
        return {"accepted": accepted, "rejected": rejected, "event": store.public(event)}

    @app.patch("/api/events/{event_id}/photos/{photo_id}")
    def update_photo(event_id: str, photo_id: str, settings: PhotoSettings):
        with store.lock:
            writable(event_id)
            event, photo, _ = store.photo(event_id, photo_id)
            new = settings.model_dump()
            if any(photo.get(key) != new[key] for key in ("x", "y", "zoom")):
                photo.pop("exported_at", None)
            photo.update(new)
            store.save(event)
            return photo

    @app.get("/api/events/{event_id}/photos/{photo_id}/{kind}")
    def photo_file(event_id: str, photo_id: str, kind: str):
        with store.lock:
            event, photo, folder = store.photo(event_id, photo_id)
        if kind == "thumbnail":
            return FileResponse(folder / ".cache" / f"{photo_id}.jpg", media_type="image/jpeg")
        if kind == "original":
            return FileResponse(folder / "RAW" / photo["name"], filename=photo["name"])
        if kind != "preview":
            raise KeyError("Image not found.")
        mark = folder / "watermark.png"
        if mark.exists():
            image = compose(folder / "RAW" / photo["name"], mark, photo,
                            opacity=event["opacity"], long_edge=1100)
        else:
            image = load_photo(folder / "RAW" / photo["name"])
            image.thumbnail((1100, 1100))
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=90)
        return Response(buffer.getvalue(), media_type="image/jpeg")

    @app.post("/api/events/{event_id}/watermark")
    def upload_watermark(event_id: str, file: UploadFile = File(...)):
        with store.lock:
            writable(event_id)
            event = store.read(event_id)
            folder = store.event_path(event_id)
            temp = folder / ".cache" / "watermark-upload.png"
            try:
                receive(file, temp)
                image = load_overlay(temp)
                # Preserve the original PNG, including its transparency and exact design.
                os.replace(temp, folder / "watermark.png")
                store.template.parent.mkdir(exist_ok=True)
                shutil.copyfile(folder / "watermark.png", store.template)
                store.invalidate(event)
                store.save(event)
                return {"width": image.width, "height": image.height,
                        "event": store.public(event)}
            finally:
                temp.unlink(missing_ok=True)
                file.file.close()

    @app.put("/api/events/{event_id}/export-settings")
    def export_settings(event_id: str, settings: ExportSettings):
        with store.lock:
            writable(event_id)
            event = store.read(event_id)
            new = settings.model_dump()
            if any(event[key] != new[key] for key in new):
                store.invalidate(event)
            event.update(new)
            store.save(event)
            return store.public(event)

    def export_job(job_id: str, event: dict):
        job = app.state.jobs[job_id]
        folder = store.event_path(event["id"])
        extension = ".jpg" if event["format"] == "jpeg" else ".png"
        try:
            for photo in (p for p in event["photos"] if p["selected"]):
                temp = None
                try:
                    image = compose(folder / "RAW" / photo["name"], folder / "watermark.png",
                                    photo, opacity=event["opacity"], long_edge=event["long_edge"])
                    filename = f'{Path(photo["name"]).stem}_{photo["id"][:6]}_DMM{extension}'
                    temp = folder / ".cache" / f"{photo['id']}.export"
                    image.save(temp, "JPEG" if extension == ".jpg" else "PNG", **(
                        {"quality": 95, "subsampling": 0} if extension == ".jpg" else {}))
                    os.replace(temp, folder / "EDITED" / filename)
                    with store.lock:
                        latest, stored_photo, _ = store.photo(event["id"], photo["id"])
                        stored_photo.update({"exported_at": now(), "edited_name": filename})
                        store.save(latest)
                    job["succeeded"] += 1
                except Exception as exc:
                    job["errors"].append({"name": photo["name"], "reason": str(exc)})
                finally:
                    if temp:
                        temp.unlink(missing_ok=True)
                    job["done"] += 1
        finally:
            job["status"] = "completed" if not job["errors"] else "completed_with_errors"

    @app.post("/api/events/{event_id}/export", status_code=202)
    def start_export(event_id: str):
        with store.lock:
            writable(event_id)
            event = store.read(event_id)
            if not (store.event_path(event_id) / "watermark.png").exists():
                raise ValueError("Load your transparent DMM watermark before exporting.")
            count = sum(bool(p["selected"]) for p in event["photos"])
            if not count:
                raise ValueError("Select at least one photo to export.")
            # Keep completed job history bounded for long-lived desktop sessions.
            for key in list(app.state.jobs):
                if len(app.state.jobs) < 100:
                    break
                if app.state.jobs[key]["status"] != "running":
                    del app.state.jobs[key]
            job = {"id": uuid.uuid4().hex, "event_id": event_id, "status": "running",
                   "total": count, "done": 0, "succeeded": 0, "errors": []}
            app.state.jobs[job["id"]] = job
            pool.submit(export_job, job["id"], event)
            return dict(job)

    @app.get("/api/jobs/{job_id}")
    def read_job(job_id: str):
        if job_id not in app.state.jobs:
            raise KeyError("Export job not found.")
        return dict(app.state.jobs[job_id])

    @app.post("/api/events/{event_id}/captions/generate")
    def generate_caption(event_id: str, settings: CaptionRequest):
        return make_caption(store.read(event_id), **settings.model_dump())

    @app.get("/api/events/{event_id}/captions")
    def read_caption(event_id: str):
        file = store.event_path(event_id) / "CAPTIONS" / "caption.txt"
        return {"text": file.read_text(encoding="utf-8") if file.exists() else ""}

    @app.put("/api/events/{event_id}/captions")
    def save_caption(event_id: str, caption: SaveCaption):
        path = store.event_path(event_id) / "CAPTIONS" / "caption.txt"
        temp = path.with_suffix(".tmp")
        with store.lock:
            temp.write_text(caption.text, encoding="utf-8")
            os.replace(temp, path)
        return {"saved": True, "path": str(path)}

    @app.get("/api/events/{event_id}/download")
    def download(event_id: str):
        with store.lock:
            writable(event_id)
            event = store.read(event_id)
            folder = store.event_path(event_id)
            photos = [p for p in event["photos"] if p["selected"]]
            if not photos or any(not p.get("exported_at") for p in photos):
                raise ValueError("Export all currently selected photos before downloading the ZIP.")
            handle, temp = tempfile.mkstemp(suffix=".zip", dir=folder / ".cache")
            os.close(handle)
            try:
                with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_STORED) as archive:
                    for photo in photos:
                        file = folder / "EDITED" / photo["edited_name"]
                        archive.write(file, f"EDITED/{file.name}")
                    caption = folder / "CAPTIONS" / "caption.txt"
                    if caption.exists():
                        archive.write(caption, "CAPTIONS/caption.txt")
            except BaseException:
                Path(temp).unlink(missing_ok=True)
                raise
        return FileResponse(temp, media_type="application/zip",
                            filename=f'{safe_name(event["name"])}_DMM.zip',
                            background=BackgroundTask(Path(temp).unlink, missing_ok=True))

    @app.post("/api/events/{event_id}/open-folder")
    def open_folder(event_id: str):
        path = store.event_path(event_id)
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
                    return {"opened": False, "path": str(path)}
                subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return {"opened": False, "path": str(path)}
        return {"opened": True, "path": str(path)}

    static = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=static, html=True), name="frontend")
    return app
