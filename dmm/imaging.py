"""Image transformations shared by previews and final exports."""

import math
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 50_000_000
SUPPORTED = {"JPEG", "PNG", "WEBP"}


def load_photo(path: Path) -> Image.Image:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as source:
                if source.format not in SUPPORTED:
                    raise ValueError("Please use a JPG, PNG, or WebP photo.")
                if getattr(source, "n_frames", 1) != 1:
                    raise ValueError("Animated images are not supported.")
                source.load()
                image = ImageOps.exif_transpose(source).convert("RGBA")
                # Transparent source photos are flattened onto white, not black.
                background = Image.new("RGBA", image.size, "white")
                return Image.alpha_composite(background, image).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ValueError("This photo is unreadable or exceeds the 50-megapixel limit.") from exc


def load_overlay(path: Path) -> Image.Image:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as source:
                if source.format != "PNG" or getattr(source, "n_frames", 1) != 1:
                    raise ValueError("Use your original transparent PNG watermark.")
                image = source.convert("RGBA")
                if min(image.size) < 16:
                    raise ValueError("The watermark must be at least 16 pixels on each side.")
                if image.getchannel("A").getextrema()[0] == 255:
                    raise ValueError("This PNG has no transparency. Choose the original overlay so photos can show through.")
                if image.getchannel("A").getextrema()[1] == 0:
                    raise ValueError("This watermark is completely transparent.")
                return image
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ValueError("This watermark is unreadable or exceeds the 50-megapixel limit.") from exc


def compose(photo: Path, overlay: Path, framing: dict, *, opacity: float = 1,
            long_edge: int = 0) -> Image.Image:
    """Cover the overlay's canvas, without stretching either layer or upscaling photos."""
    image = load_photo(photo)
    mark = load_overlay(overlay)
    ratio = mark.width / mark.height
    zoom = max(1.0, min(3.0, float(framing.get("zoom", 1))))
    x = max(0.0, min(1.0, float(framing.get("x", 0.5))))
    y = max(0.0, min(1.0, float(framing.get("y", 0.5))))
    crop_w = min(image.width, image.height * ratio) / zoom
    crop_h = crop_w / ratio
    left, top = (image.width - crop_w) * x, (image.height - crop_h) * y
    scale = min(1.0, long_edge / max(crop_w, crop_h)) if long_edge else 1.0
    width, height = max(1, math.floor(crop_w * scale)), max(1, math.floor(crop_h * scale))
    result = image.resize((width, height), Image.Resampling.LANCZOS,
                          box=(left, top, left + crop_w, top + crop_h)).convert("RGBA")
    mark = mark.resize(result.size, Image.Resampling.LANCZOS)
    if opacity != 1:
        mark.putalpha(mark.getchannel("A").point(lambda a: round(a * opacity)))
    return Image.alpha_composite(result, mark).convert("RGB")


def thumbnail(photo: Path, destination: Path) -> None:
    image = load_photo(photo)
    image.thumbnail((440, 320), Image.Resampling.LANCZOS)
    image.save(destination, "JPEG", quality=85)
