import hashlib
import io
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from dmm.captions import FOOTER, HASHTAGS, make_caption
from dmm.imaging import compose, load_photo
from dmm.server import create_app


def image_bytes(color="navy", size=(400, 300), fmt="JPEG", exif=None):
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, fmt, **({"exif": exif} if exif else {}))
    return stream.getvalue()


def overlay_bytes(size=(200, 200)):
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    image.paste((0, 255, 0, 255), (0, 0, 20, size[1]))
    stream = io.BytesIO(); image.save(stream, "PNG")
    return stream.getvalue()


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "events")
    with TestClient(app, base_url="http://127.0.0.1") as test:
        yield test
    app.state.pool.shutdown(wait=True)


def event(client, **details):
    response = client.post("/api/events", json={"name":"Youth / Ministry: Event", "date":"2026-10-19", **details})
    assert response.status_code == 201, response.text
    return response.json()


def upload(client, event_id, content=None, filename="photo.jpg"):
    return client.post(f"/api/events/{event_id}/photos", files=[("files", (filename, content or image_bytes(), "image/jpeg"))])


def watermark(client, event_id):
    result = client.post(f"/api/events/{event_id}/watermark", files={"file":("overlay.png", overlay_bytes(), "image/png")})
    assert result.status_code == 200, result.text
    return result.json()


def wait_export(client, event_id):
    response = client.post(f"/api/events/{event_id}/export")
    assert response.status_code == 202, response.text
    job = response.json()
    deadline = time.monotonic() + 10
    while job["status"] == "running" and time.monotonic() < deadline:
        time.sleep(.01)
        job = client.get(f'/api/jobs/{job["id"]}').json()
    assert job["status"] != "running", "Export did not complete"
    return job


def test_create_folders_and_reopen(client):
    item = event(client)
    folder = Path(item["folder"])
    assert all((folder / name).is_dir() for name in ("RAW", "EDITED", "CAPTIONS"))
    assert folder.parent == client.app.state.store.root
    assert ":" not in folder.name and "/" not in folder.name
    assert event(client)["folder"] != item["folder"]
    other_app = create_app(folder.parent)
    with TestClient(other_app, base_url="http://127.0.0.1") as reopened:
        assert reopened.get(f'/api/events/{item["id"]}').json()["name"] == item["name"]
    other_app.state.pool.shutdown(wait=True)


def test_import_preserves_originals_and_handles_duplicates_and_bad_files(client):
    item = event(client)
    content = image_bytes()
    results = [upload(client,item["id"],content).json() for _ in range(2)]
    names = [result["accepted"][0]["name"] for result in results]
    assert names == ["photo.jpg", "photo-2.jpg"]
    for name in names:
        assert hashlib.sha256((Path(item["folder"])/"RAW"/name).read_bytes()).digest() == hashlib.sha256(content).digest()
    failed = upload(client,item["id"],b"not an image","bad.jpg").json()
    assert not failed["accepted"] and len(failed["rejected"]) == 1
    assert len(list((Path(item["folder"])/"RAW").iterdir())) == 2
    safe = upload(client,item["id"],content,"../../CON.jpg").json()["accepted"][0]
    assert safe["name"].startswith("photo-")


def test_overlay_validation_and_inheritance(client):
    item = event(client)
    response = client.post(f'/api/events/{item["id"]}/watermark', files={"file":("opaque.png",image_bytes(fmt="PNG"),"image/png")})
    assert response.status_code == 400 and "transparency" in response.json()["detail"]
    assert not Path(item["folder"],"watermark.png").exists()
    watermark(client,item["id"])
    assert event(client)["has_watermark"]


def test_crop_positions_and_transparency(tmp_path):
    source = Image.new("RGB", (400,200),"red")
    source.paste("blue", (200,0,400,200))
    photo, mark = tmp_path/"photo.png", tmp_path/"mark.png"
    source.save(photo); mark.write_bytes(overlay_bytes())
    left = compose(photo,mark,{"x":0,"y":.5,"zoom":1})
    right = compose(photo,mark,{"x":1,"y":.5,"zoom":1})
    assert left.size == (200,200) and right.size == left.size
    assert left.getpixel((100,100)) == (255,0,0)
    assert right.getpixel((100,100)) == (0,0,255)
    assert left.getpixel((5,100)) == (0,255,0)
    faint = compose(photo,mark,{"x":0},opacity=.5)
    assert faint.getpixel((5,100)) == (127,128,0)
    assert compose(photo,mark,{"zoom":2},long_edge=2048).size == (100,100)


def test_exif_rotation_is_applied(tmp_path):
    exif = Image.Exif(); exif[274] = 6
    photo = tmp_path/"rotated.jpg"; photo.write_bytes(image_bytes(size=(300,200),exif=exif))
    assert load_photo(photo).size == (200,300)


def test_export_caption_zip_and_repeatability(client):
    item = event(client,venue="Baguio",organizer="Youth Ministry",photographer="Test Photographer",
                 activities="Participants attended a leadership workshop.",purpose="The workshop focused on service.")
    photo = upload(client,item["id"]).json()["accepted"][0]
    assert client.post(f'/api/events/{item["id"]}/export').status_code == 400
    watermark(client,item["id"])
    preview = client.get(f'/api/events/{item["id"]}/photos/{photo["id"]}/preview')
    assert preview.status_code == 200
    assert Image.open(io.BytesIO(preview.content)).size == (300,300)
    draft = client.post(f'/api/events/{item["id"]}/captions/generate',json={}).json()
    assert FOOTER in draft["text"] and HASHTAGS in draft["text"]
    assert "Photos: Test Photographer" in draft["text"]
    assert not draft["missing"]
    saved = client.put(f'/api/events/{item["id"]}/captions',json={"text":draft["text"]})
    assert saved.status_code == 200
    job = wait_export(client,item["id"])
    assert job["succeeded"] == 1 and job["done"] == 1 and job["errors"] == []
    edited = list(Path(item["folder"],"EDITED").iterdir())
    assert len(edited) == 1 and Image.open(edited[0]).size == (300,300)
    download = client.get(f'/api/events/{item["id"]}/download')
    assert download.status_code == 200
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        assert any(name.startswith("EDITED/") for name in archive.namelist())
        assert archive.read("CAPTIONS/caption.txt").decode() == draft["text"]
        assert not any(name.startswith("RAW/") for name in archive.namelist())
    wait_export(client,item["id"])
    assert len(list(Path(item["folder"],"EDITED").iterdir())) == 1
    assert not list(Path(item["folder"],".cache").glob("*.zip"))
    assert not list(Path(item["folder"],".cache").glob("*.export"))


def test_stale_exports_require_rerender_and_excluded_photos_stay_out(client):
    item = event(client); watermark(client,item["id"])
    photos = upload(client,item["id"]).json()["accepted"]
    second = upload(client,item["id"],filename="second.jpg").json()["accepted"][0]
    assert client.patch(f'/api/events/{item["id"]}/photos/{second["id"]}',json={"selected":False}).status_code == 200
    job = wait_export(client,item["id"])
    assert job["total"] == 1
    first = photos[0]
    client.patch(f'/api/events/{item["id"]}/photos/{first["id"]}',json={"x":.2,"zoom":1.5})
    assert client.get(f'/api/events/{item["id"]}/download').status_code == 400
    job = wait_export(client,item["id"])
    assert job["succeeded"] == 1
    client.put(f'/api/events/{item["id"]}/export-settings',json={"opacity":.8,"format":"png","long_edge":0})
    assert client.get(f'/api/events/{item["id"]}/download').status_code == 400
    wait_export(client,item["id"])
    download = client.get(f'/api/events/{item["id"]}/download')
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        assert len(archive.namelist()) == 1
        assert archive.namelist()[0].endswith(".png")


def test_failed_exports_are_reported(client):
    item = event(client); watermark(client,item["id"])
    photo = upload(client,item["id"]).json()["accepted"][0]
    (Path(item["folder"])/"RAW"/photo["name"]).unlink()
    job = wait_export(client,item["id"])
    assert job["status"] == "completed_with_errors" and job["succeeded"] == 0
    assert job["errors"][0]["name"] == photo["name"]


def test_caption_missing_facts_and_photo_description():
    details = {"name":"Confirmed Event","date":"2026-10-19"}
    result = make_caption(details,style="photo")
    assert "Organizer" in result["missing"]
    assert "A factual description of this photo" in result["missing"]
    assert result["text"].endswith(HASHTAGS)
    assert "successful" not in result["text"].lower()
    result = make_caption(details,style="photo",photo_caption="Members gather at the venue.",include_footer=False)
    assert "Members gather at the venue." in result["text"] and FOOTER not in result["text"]


def test_validation_and_local_origin_protection(client):
    assert client.post("/api/events",json={"name":" ","date":"2026-10-19"}).status_code == 422
    assert client.post("/api/events",json={"name":"Bad date","date":"2026-02-30"}).status_code == 422
    assert client.get("/api/events/not-an-id").status_code == 404
    assert client.get("/api/settings",headers={"Origin":"https://unrelated.example"}).status_code == 403
    assert client.get("/api/settings",headers={"Host":"unrelated.example"}).status_code == 400
    assert client.get("/").status_code == 200
    assert "Content-Security-Policy" in client.get("/").headers
