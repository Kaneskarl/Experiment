"""Run with: python tests/browser_smoke.py (requires Playwright and Chromium).

Starts an isolated server and uses synthetic fixtures; never touches real event data.
"""

import io
import os
import re
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
                with page.expect_response(lambda r: '/photos/' in r.url and r.request.method == 'PATCH'):
                    page.get_by_role('button',name='Rotate right',exact=True).click()
                expect(page.locator('.rotation-value')).to_have_text('90°')
                with page.expect_response(lambda r: '/photos/' in r.url and r.request.method == 'PATCH'):
                    page.get_by_role('button',name='Flip horizontal',exact=True).click()
                expect(page.get_by_role('button',name='Flip horizontal',exact=True)).to_have_attribute('aria-pressed','true')
                with page.expect_response(lambda r: '/photos/' in r.url and r.request.method == 'PATCH'):
                    page.locator('#slider-brightness').evaluate("el => { el.value='0.75'; el.dispatchEvent(new Event('input',{bubbles:true})); }")
                page.get_by_role('button',name='Compare original',exact=True).click()
                expect(page.locator('#preview-image')).to_have_attribute('src',re.compile('/before'))
                page.get_by_role('button',name='Show edited',exact=True).click()
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
                expect(page.get_by_role('button',name='Generate AI caption',exact=True)).to_be_disabled()
                page.locator('[name="activities"]').fill("Participants attended a leadership workshop.")
                page.locator('[name="purpose"]').fill("The workshop focused on Christian service.")
                # Unsaved fact fields survive switching tools.
                page.get_by_role("tab",name="Photos").click()
                page.get_by_role("tab",name="Caption maker").click()
                expect(page.locator('[name="activities"]')).to_have_value("Participants attended a leadership workshop.")
                page.get_by_role('button',name='Offline template',exact=True).click()
                page.get_by_role("button",name="Create draft",exact=True).click()
                expect(page.locator('#caption-text')).to_contain_text("#damdamagmisyonmontanyosa")
                caption = page.locator('#caption-text').input_value()
                assert "Participants attended a leadership workshop." in caption
                page.get_by_role("button",name="Copy text",exact=True).click()
                assert page.evaluate("navigator.clipboard.readText()") == caption
                page.get_by_role("button",name="Save caption",exact=True).click()
                expect(page.locator('#caption-save-state')).to_have_text("Saved to CAPTIONS")
                # Exercise the real connection settings UI with a synthetic key.
                # Only the AI result is mocked here; transport is covered by API tests.
                page.get_by_role('button',name='AI writer',exact=True).click()
                page.get_by_role('button',name='Connect',exact=True).click()
                page.locator('#ai-key').fill('browser-test-key-not-a-real-credential')
                page.locator('#ai-submit').click()
                expect(page.locator('#ai-dialog')).not_to_be_visible()
                expect(page.get_by_role('button',name='Generate AI caption',exact=True)).to_be_enabled()
                assert 'browser-test-key' not in ''.join(path.read_text() for path in (root/'events').rglob('*.json'))
                assert page.locator('#ai-key').input_value() == ''
                generated = caption.replace('DMM Browser Test Event','DMM Browser Test Event — A Focus on Service',1)
                ai_payloads, ai_requests, fact_requests = [], [], []
                def ai_result(route):
                    ai_payloads.append(route.request.post_data_json)
                    ai_requests.append(route)
                def hold_fact_save(route):
                    if route.request.method == 'PUT':
                        fact_requests.append(route)
                    else:
                        route.continue_()
                page.route('**/api/events/*/captions/generate',ai_result)
                page.route('**/api/events/*',hold_fact_save)
                page.locator('#caption-length').select_option('short')
                page.locator('#caption-instructions').fill('Keep the language warm and concise.')
                page.once('dialog',lambda dialog: dialog.accept())
                page.get_by_role('button',name='Generate AI caption',exact=True).click()
                expect(page.locator('#caption-text')).to_be_disabled()
                expect(page.get_by_role('tab',name='Photos')).to_be_disabled()
                expect(page.locator('#library-nav')).to_be_disabled()
                # Lock before saving facts as well as during the paid AI call.
                assert len(fact_requests) == 1
                assert not ai_requests
                fact_requests[0].fulfill(response=fact_requests[0].fetch())
                page.unroute('**/api/events/*',hold_fact_save)
                expect(page.get_by_role('button',name='Writing your caption…',exact=True)).to_be_disabled()
                page.wait_for_function('() => document.querySelector("#caption-text").matches(":disabled")')
                # Wait for the AI request without substituting a live provider.
                deadline = time.monotonic() + 10
                while not ai_requests and time.monotonic() < deadline:
                    page.wait_for_timeout(50)
                assert len(ai_requests) == 1
                ai_requests[0].fulfill(status=200,json={'text':generated,'missing':[],'mode':'ai','provider':'OpenAI','model':'gpt-4.1-mini'})
                expect(page.locator('#caption-text')).to_have_value(generated)
                assert ai_payloads[0]['mode'] == 'ai' and ai_payloads[0]['length'] == 'short'
                assert ai_payloads[0]['instructions'] == 'Keep the language warm and concise.'
                page.unroute('**/api/events/*/captions/generate',ai_result)
                caption = generated
                page.get_by_role('button',name='Save caption',exact=True).click()
                expect(page.locator('#caption-save-state')).to_have_text('Saved to CAPTIONS')
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
                expect(page.locator('#slider-brightness')).to_have_value('0.75')
                expect(page.locator('.rotation-value')).to_have_text('90°')
                expect(page.get_by_role('button',name='Flip horizontal',exact=True)).to_have_attribute('aria-pressed','true')
                page.get_by_role("tab",name="Caption maker").click()
                expect(page.locator('#caption-text')).to_have_value(caption)
                page.get_by_role("tab",name="Photos").click()
                page.set_viewport_size({"width":390,"height":844})
                page.screenshot(path="/tmp/dmm-mobile.png",full_page=True)
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "Mobile layout overflows"
                assert not errors, f"Browser errors: {errors}"
                assert not external, f"Unexpected network requests: {external}"
                browser.close()
                print("Browser workflow passed: import, overlay, rotate, flip, adjust, compare, favorites, selection, offline caption, AI key settings, mocked AI caption, clipboard, export, ZIP, reopen, mobile. No browser errors or external requests. Live AI requires a real key.")
        finally:
            server.terminate()
            try: server.wait(timeout=10)
            except subprocess.TimeoutExpired: server.kill(); server.wait()
            log.close()


if __name__ == "__main__":
    run()
