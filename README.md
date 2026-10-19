# DMM Photo Desk

A local photo workspace for **Damdamag Misyon Montanyosa**. Organize event coverage, apply your original transparent DMM overlay, frame photos, and prepare factual captions.

Photos and captions stay on the computer running the app. No account, cloud upload, AI subscription, or API key is required. Internet is needed only to install dependencies the first time.

## Start on your PC

1. Install **Python 3.12 or newer** from the official Python website. On Windows, include the Python launcher during installation.
2. Download or clone this repository and extract it into a regular folder.
3. On **Windows**, double-click **`start.bat`**. On **macOS or Linux**, run `bash start.sh` from a terminal.
4. The first launch installs dependencies; subsequent launches work offline. Keep the terminal window open while using the app. Close the app with **Ctrl+C** in that window.

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
4. **Review framing.** Select a photo and adjust zoom and horizontal/vertical placement. Photos fill the overlay's shape without stretching. Settings save automatically. Mark favorites and exclude pictures you do not want to publish.
5. **Prepare a caption.** Open Caption maker, enter verified activities, purpose, and outcomes, then create an album or single-photo template draft. Edit it, copy it, and explicitly save it to `CAPTIONS/caption.txt`.
6. **Export.** Choose JPG or PNG and full crop resolution, 2048 px, or 3200 px. The image size is a maximum long edge: small photos are not enlarged. Exported copies go into `EDITED`.
7. **Download ZIP** if useful. The ZIP includes the current selected exports and your saved caption, without duplicating the originals.

Changing a crop, watermark, opacity, or output setting marks affected exports as needing a new export. Re-export before downloading the current ZIP. Re-exporting to the same format replaces that photo's generated copy; previously exported files in other formats remain in `EDITED`. The ZIP includes only the current selected versions.

## Event folders and persistence

```text
Pictures/DMM Photo Desk/
├── .branding/default.png
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

## DMM captions

The caption maker is an **offline template tool**, not generative AI. It arranges the facts you supply and identifies missing core details. It does not verify claims, invent quotations, attendance, names, or spiritual outcomes, and it never publishes automatically.

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

The browser check covers event creation, original import, transparent overlay, framing, favorites, selection, captions, clipboard, export, ZIP contents, reopening, and a narrow screen layout. It also checks for browser errors and unexpected external requests.
