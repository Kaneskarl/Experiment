"""Run with: python tests/browser_smoke.py (requires Playwright and Chromium).

Starts an isolated server and uses synthetic fixtures; never touches real event data.
"""

import io
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw
from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[1]


def run():
    with tempfile.TemporaryDirectory(prefix="dmm-browser-") as temp:
        root = Path(temp)
        for name, color, size in [("landscape.jpg", "#b6cdbd", (1200,800)), ("portrait.jpg", "#adc8db", (800,1200))]:
            photo = Image.new("RGB", size, color)
            draw = ImageDraw.Draw(photo)
            draw.rectangle((size[0]//3,size[1]//5,2*size[0]//3,4*size[1]//5),fill="#657b61")
            photo.save(root/name)
        overlay = Image.new("RGBA", (940,788), (0,0,0,0))
        draw = ImageDraw.Draw(overlay)
        draw.rectangle((0,0,180,788),fill=(15,89,80,210))
        draw.text((25,35), "TEST OVERLAY", fill="white")
        overlay.save(root/"overlay.png")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1",0)); port = listener.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        log = (root/"server.log").open("w")
        server = subprocess.Popen([sys.executable,"-m","dmm","--no-browser","--port",str(port),"--data-dir",str(root/"events")],cwd=REPO,stdout=log,stderr=log)
        try:
            for _ in range(100):
                try:
                    with urllib.request.urlopen(url+"/api/health",timeout=1) as response:
                        assert response.status == 200
                    break
                except OSError:
                    if server.poll() is not None:
                        raise AssertionError((root/"server.log").read_text())
                    time.sleep(.1)
            else:
                raise AssertionError("Application did not become ready")
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=os.environ.get("DMM_BROWSER") or shutil.which("chromium"),headless=True,args=["--no-sandbox"])
                context = browser.new_context(viewport={"width":1440,"height":1050},accept_downloads=True)
                context.grant_permissions(["clipboard-read","clipboard-write"])
                page = context.new_page(); errors = []; external = []
                page.on("pageerror",lambda error: errors.append(str(error)))
                page.on("console",lambda message: errors.append(message.text) if message.type == "error" else None)
                page.on("request",lambda request: external.append(request.url) if not request.url.startswith(url) else None)
                page.goto(url)
                expect(page.get_by_role("heading",name="Your ministry. In focus.")).to_be_visible()
                page.screenshot(path="/tmp/dmm-library.png",full_page=True)
                page.get_by_role("button",name="Create your first event").click()
                page.locator('#event-form [name="name"]').fill("DMM Browser Test Event")
                page.locator('#event-form [name="date"]').fill("2026-10-19")
                page.locator('#event-form [name="venue"]').fill("Test venue")
                page.locator('#event-form [name="organizer"]').fill("Test Ministry")
                page.locator('#event-form [name="photographer"]').fill("Test Photographer")
                page.locator('#event-submit').click()
                expect(page.get_by_role("heading",name="DMM Browser Test Event")).to_be_visible()
                page.locator('#watermark-input').set_input_files(root/"overlay.png")
                expect(page.get_by_role("button",name="Change watermark")).to_be_visible()
                page.locator('#photo-input').set_input_files([root/"landscape.jpg",root/"portrait.jpg"])
                expect(page.locator('.photo-tile')).to_have_count(2)
                expect(page.get_by_role("button",name="Export 2 photos",exact=True)).to_be_enabled()
                page.locator('#preview-image').wait_for(state="visible")
                page.wait_for_function("() => document.querySelector('#preview-image').naturalWidth > 0")
                with page.expect_response(lambda r: '/photos/' in r.url and r.request.method == 'PATCH'):
                    page.locator('#slider-zoom').evaluate("el => { el.value='1.4'; el.dispatchEvent(new Event('input',{bubbles:true})); }")
                page.wait_for_function("() => document.querySelector('#preview-image').complete")
                page.screenshot(path="/tmp/dmm-workspace.png",full_page=True)
                page.locator('[data-favorite]').first.click()
                page.locator('[data-filter="favorites"]').click()
                expect(page.locator('.photo-tile')).to_have_count(1)
                page.locator('[data-filter="all"]').click()
                expect(page.locator('.photo-tile')).to_have_count(2)
                page.locator('[data-select]').last.click()
                expect(page.get_by_role("button",name="Export 1 photo",exact=True)).to_be_enabled()
                page.get_by_role("tab",name="Caption maker").click()
                page.locator('[name="activities"]').fill("Participants attended a leadership workshop.")
                page.locator('[name="purpose"]').fill("The workshop focused on Christian service.")
                # Unsaved fact fields survive switching tools.
                page.get_by_role("tab",name="Photos").click()
                page.get_by_role("tab",name="Caption maker").click()
                expect(page.locator('[name="activities"]')).to_have_value("Participants attended a leadership workshop.")
                page.get_by_role("button",name="Create draft",exact=True).click()
                expect(page.locator('#caption-text')).to_contain_text("#damdamagmisyonmontanyosa")
                caption = page.locator('#caption-text').input_value()
                assert "Participants attended a leadership workshop." in caption
                page.get_by_role("button",name="Copy text",exact=True).click()
                assert page.evaluate("navigator.clipboard.readText()") == caption
                page.get_by_role("button",name="Save caption",exact=True).click()
                expect(page.locator('#caption-save-state')).to_have_text("Saved to CAPTIONS")
                page.screenshot(path="/tmp/dmm-captions.png",full_page=True)
                page.get_by_role("tab",name="Photos").click()
                page.get_by_role("button",name="Export 1 photo",exact=True).click()
                expect(page.locator('#job-status')).to_contain_text("1 photo exported",timeout=15000)
                with page.expect_download() as info:
                    page.get_by_role("link",name="Download ZIP").click()
                info.value.save_as(root/"export.zip")
                with zipfile.ZipFile(root/"export.zip") as archive:
                    assert len(archive.namelist()) == 2
                    assert archive.read("CAPTIONS/caption.txt").decode() == caption
                page.locator('#library-nav').click()
                page.locator('.event-card').click()
                expect(page.locator('#slider-zoom')).to_have_value("1.4")
                page.get_by_role("tab",name="Caption maker").click()
                expect(page.locator('#caption-text')).to_have_value(caption)
                page.get_by_role("tab",name="Photos").click()
                page.set_viewport_size({"width":390,"height":844})
                page.screenshot(path="/tmp/dmm-mobile.png",full_page=True)
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "Mobile layout overflows"
                assert not errors, f"Browser errors: {errors}"
                assert not external, f"Unexpected network requests: {external}"
                browser.close()
                print("Browser workflow passed: create, import, overlay, crop, favorites, selection, caption, clipboard, export, ZIP, reopen, mobile; no browser errors or external requests.")
        finally:
            server.terminate()
            try: server.wait(timeout=10)
            except subprocess.TimeoutExpired: server.kill(); server.wait()
            log.close()


if __name__ == "__main__":
    run()
