# DMM Photo Desk

A local photo workspace for **Damdamag Misyon Montanyosa**. Organize event coverage, rotate and edit photos, apply your original transparent DMM overlay, and draft captions with AI.

Photo editing and watermarking run on the computer hosting the app, and originals stay untouched. **Local AI captions use Ollama with no API key or per-caption charge.** OpenAI remains an optional paid provider. The offline caption template also works without an AI model.

## Start on your PC

1. Install **Python 3.12 or newer** from the official Python website. On Windows, include the Python launcher during installation.
2. Download or clone this repository and extract it into a regular folder.
3. On **Windows**, double-click **`start.bat`**. On **macOS or Linux**, run `bash start.sh` from a terminal.
4. The first launch installs dependencies; subsequent launches can edit photos offline. Keep the terminal window open while using the app. Close the app with **Ctrl+C** in that window.

Your browser opens automatically. This is a local browser interface, not a standalone Windows installer. The application has been tested on Linux with Chromium; the Windows launcher and native folder-opening integration still need a Windows PC check.

By default, events are stored under **Pictures / DMM Photo Desk** in your home folder. To choose another location, launch from a terminal:

```bat
start.bat --data-dir "D:\DMM Events"
```

```sh
bash start.sh --data-dir "/your/event/folder"
```

Use **Storage & help** inside the app to see the actual storage location. **Open folder** opens an event's directory when a desktop file manager is available.

Running the app in a cloud workspace saves files in that workspace. To create folders on your own PC, run it on that PC.

## Your first event

1. **Create an event.** Enter its confirmed name, date, location, organizer, theme, and photographer as available.
2. **Load your watermark.** Choose the original transparent PNG of your DMM design. The app preserves that artwork and its proportions; it does not recreate your logos or wording. The image shown in chat is not bundled with this repository, so load the original file on first use.
3. **Add photos.** Select multiple JPG, PNG, or WebP files, or drop them into the empty photo area. Original bytes are copied into `RAW`; source files are not moved or changed.
4. **Edit and frame.** Select a photo, rotate or flip it, adjust brightness, contrast, color, and sharpness, and set zoom and horizontal/vertical placement. Photos fill the overlay's shape without stretching. Settings save automatically. Mark favorites and exclude pictures you do not want to publish.
5. **Prepare a caption.** Open Caption maker, enter verified activities, purpose, and outcomes. Choose Local AI with Ollama or connect an OpenAI API key to generate an album or single-photo caption. Offline template remains available too. Edit the result, copy it, and explicitly save it to `CAPTIONS/caption.txt`.
6. **Export.** Choose JPG or PNG and full crop resolution, 2048 px, or 3200 px. The image size is a maximum long edge: small photos are not enlarged. Exported copies go into `EDITED`.
7. **Download ZIP** if useful. The ZIP includes the current selected exports and your saved caption, without duplicating the originals.

Changing an image edit, crop, watermark, opacity, or output setting marks affected exports as needing a new export. Re-export before downloading the current ZIP. Re-exporting to the same format replaces that photo's generated copy; previously exported files in other formats remain in `EDITED`. The ZIP includes only the current selected versions.

## Photo editing

- **Rotate left / right:** exact 90-degree steps, applied after automatic camera-orientation correction.
- **Flip horizontal / vertical:** mirror the photo along either axis, after rotation.
- **Brightness and contrast:** adjust between 25% and 200%; 100% preserves the original setting.
- **Color:** adjust saturation between 0% (grayscale) and 200%.
- **Sharpness:** adjust between 0% (softer) and 300%; 100% preserves the original setting.
- **Compare original:** view the unedited, correctly oriented source without the watermark. Choose Show edited to return to the publication preview.
- **Reset edits:** restore rotation, flips, and basic adjustments. **Reset** under Photo framing separately restores crop placement and zoom.

Adjustments apply only to the photo. The watermark is composited afterward, preserving its typography, logos, and colors. Basic adjustments work before loading a watermark; crop framing and publication exports use the watermark's proportions. Edits are saved as settings, and full-resolution output is rendered from the original each time, avoiding repeated JPEG editing. Gallery thumbnails show the imported originals.

## Event folders and persistence

```text
Pictures/DMM Photo Desk/
├── .branding/default.png
├── .ai-settings.json         Provider and model names only; no API key
└── Event-Date_Event-Name_unique-id/
    ├── RAW/                  Untouched imported copies
    ├── EDITED/               Watermarked publication copies
    ├── CAPTIONS/caption.txt  Your saved caption
    ├── .cache/               Generated thumbnails and temporary exports
    ├── watermark.png         This event's overlay
    └── event.json            Event details, photo selections, and framing
```

New events inherit your last uploaded watermark. Existing events retain their own copy. Event folders receive a unique suffix to avoid collisions; changing event details does not rename a folder. Imported duplicate filenames receive a numbered suffix instead of overwriting files.

Back up the **whole storage folder** to preserve events, originals, branding, framing, and captions. Only run one instance of the app against a given storage folder at a time. There is no event deletion feature in this version.

`RAW` is the originals folder name; this version does **not** decode camera RAW, HEIC, animated images, or video. Individual images are limited to 60 MB and 50 megapixels. Output copies are flattened RGB images with source EXIF/GPS metadata omitted; originals retain their metadata. Advanced color-profile conversion is not implemented.

## AI-powered DMM captions

### Local AI on your PC: no API key

For a **16 GB RAM PC with an AMD Radeon RX 6600**, start with the small `qwen2.5:3b` model:

1. Install [Ollama](https://ollama.com/download) and open it.
2. Open a terminal (PowerShell on Windows) and download the model once:

   ```sh
   ollama pull qwen2.5:3b
   ```

   The model download is approximately 2 GB. Internet is needed for installation and this download, then generation can work offline.
3. Start DMM Photo Desk on your PC. Open **AI connection** and select **Local AI · Ollama · No API key**.
4. Leave the model as **`qwen2.5:3b`**, click **Check local model**, then **Save connection**.
5. Open an event → **Caption maker** → **AI writer**. Enter the facts, choose a length, and click **Generate AI caption**. Keep Ollama running.

The model uses your existing DMM instructions and supplied facts; no training job or paid API account is needed. The first caption may take longer while the model loads. Start with short captions to assess speed and quality on your PC.

Your 16 GB RAM can support this small model on the CPU. **RX 6600 acceleration depends on your operating system, Ollama version, and drivers; it is not guaranteed.** CPU generation is available when GPU acceleration is unavailable. This app does not install GPU drivers or enable experimental GPU overrides. Actual speed and GPU use must be checked on your PC.

Local mode talks only to Ollama on the same computer, at its default port 11434. It uses downloaded models; cloud-tagged models and model entries marked as remote are excluded. It never sends an OpenAI key or silently switches to a cloud provider. If Ollama or the selected model is unavailable, the app explains how to start or download it while preserving your existing draft. Local AI selection and each provider's model choice survive app restarts.

If Photo Desk runs in a cloud workspace, local means that cloud machine. **Run Photo Desk on your own PC to use your PC's RAM and GPU.** Ollama and the model are not bundled into the app download.

### Optional OpenAI provider

Open **AI connection**, select **OpenAI**, and enter an API key and model available to that account. The default is `gpt-4.1-mini`, which uses the Responses API and structured output. Saving a key configures it; actual access is checked when generating a caption.

OpenAI uses your API account's usage billing. A ChatGPT subscription does not include API usage. Keys entered in the app stay in server memory for the current app session; closing and restarting the app clears them. Only the provider and model names are saved. **Forget session key** removes an in-app key; a key supplied by the launch environment remains available until removed there. Keys are never returned by the API, put in browser storage, or saved in event files.

For a key supplied at launch, set `DMM_AI_API_KEY` in the app process environment. An existing `OPENAI_API_KEY` is also accepted. `DMM_AI_MODEL` can set the initial model. No `.env` file is automatically read. In the managed cloud environment, supply `DMM_AI_API_KEY` securely through environment settings and allow `api.openai.com`; restart the app after the binding is applied. Do not paste keys into chat or commit them to Git.

### DMM voice and final review

Both AI providers follow DMM's **“News first, faith naturally”** instructions: use supplied facts, omit missing information, and avoid fabricated names, statistics, quotations, and outcomes. Neither can see or describe photos unless you supply a factual description. The app flags missing core details. **AI can still make mistakes: review every factual claim before posting.**

The selected AI receives only the event's name, date, venue, organizer, theme, activities, purpose, outcomes, optional photo description, and writing preferences. Local mode keeps these on your computer. OpenAI mode sends this text to OpenAI with response storage disabled (`store: false`). Photo files, local paths, and photographer credits are not sent to either model. Official footer, hashtags, and photographer credit are appended by the app afterward. Provider errors do not replace your existing draft or silently substitute an offline template.

Choose **Offline template** whenever you want a local draft without AI or internet. Neither mode verifies facts or publishes automatically.

The default draft includes photographer credit when supplied and this exact footer:

> Damdamag Misyon Montanyosa is the Official Online News Portal of the Mountain Provinces Mission of the Seventh-day Adventists.

```text
#damdamagmisyonmontanyosa #adventistmontanyosa #mpmlocalnewsprogram
```

The footer and credit can be turned off for alternate formats. One editable caption is saved per event; choosing another draft style does not create a separate caption file. Review all facts and obtain any needed publication permissions before posting.

## Development and validation

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
node --test tests/editor_state.test.cjs
.venv/bin/python -m dmm --no-browser --data-dir /workspace/.dmm-data
```

On Windows use `.venv\Scripts\python.exe`. Runtime and test dependencies are pinned. The server binds only to loopback and rejects foreign browser origins. Do not expose it as a public or shared network service.

The optional browser check starts an isolated application and exercises the real interface using synthetic fixtures:

```sh
.venv/bin/python -m pip install -r requirements-browser.txt
# Use an installed Chromium, set DMM_BROWSER to a browser executable,
# or install the browser with: python -m playwright install chromium
.venv/bin/python tests/browser_smoke.py
```

The browser check covers event creation, photo edits, original comparison, selection, offline captions, both AI provider settings, local model status, mocked AI results, controls locked during generation, clipboard, export, ZIP contents, reopening, and a narrow screen layout. It checks for browser errors and unexpected external browser requests. Node's dependency-free tests cover overlapping edits and settings writes. API tests mock OpenAI transport and exercise the Ollama protocol against an isolated local HTTP fixture, including privacy boundaries, local-only model selection, and errors. These tests do **not** run a real downloaded language model or establish GPU acceleration. Real model output must be validated on your PC; live OpenAI access requires a working API key.
