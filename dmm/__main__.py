import argparse
import os
import threading
import webbrowser
from pathlib import Path

import uvicorn

from .server import create_app


def main():
    parser = argparse.ArgumentParser(description="DMM Photo Desk — local event photo workspace")
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get(
        "DMM_DATA_DIR", str(Path.home() / "Pictures" / "DMM Photo Desk"))),
        help="Folder where event projects will be saved")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a port between 1024 and 65535.")
    app = create_app(args.data_dir)
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}")).start()
    print(f"DMM Photo Desk\nEvent folder: {app.state.store.root}\nClose with Ctrl+C.")
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
