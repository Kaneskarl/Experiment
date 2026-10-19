import hashlib

import pytest
from PIL import Image, ImageEnhance

from dmm.imaging import apply_edits, compose, load_photo, render_photo


def patterned_photo():
    """Six distinct pixels expose direction and ordering without interpolation."""
    image = Image.new("RGB", (3, 2))
    image.putdata([
        (255, 0, 0), (0, 255, 0), (0, 0, 255),
        (255, 255, 0), (255, 0, 255), (0, 255, 255),
    ])
    return image


@pytest.mark.parametrize("rotation,expected", [
    (90, [(255, 255, 0), (255, 0, 0), (255, 0, 255),
          (0, 255, 0), (0, 255, 255), (0, 0, 255)]),
    (180, [(0, 255, 255), (255, 0, 255), (255, 255, 0),
           (0, 0, 255), (0, 255, 0), (255, 0, 0)]),
    (270, [(0, 0, 255), (0, 255, 255), (0, 255, 0),
           (255, 0, 255), (255, 0, 0), (255, 255, 0)]),
])
def test_quarter_turns_are_clockwise_and_keep_all_pixels(rotation, expected):
    edited = apply_edits(patterned_photo(), {"rotation": rotation})
    assert edited.size == ((3, 2) if rotation == 180 else (2, 3))
    assert [edited.getpixel((x, y)) for y in range(edited.height)
            for x in range(edited.width)] == expected


def test_horizontal_and_vertical_flips_use_visible_photo_axes():
    source = patterned_photo()
    horizontal = apply_edits(source, {"flip_horizontal": True})
    vertical = apply_edits(source, {"flip_vertical": True})
    assert horizontal.getpixel((0, 0)) == source.getpixel((2, 0))
    assert horizontal.getpixel((2, 1)) == source.getpixel((0, 1))
    assert vertical.getpixel((0, 0)) == source.getpixel((0, 1))
    assert vertical.getpixel((2, 1)) == source.getpixel((2, 0))
    rotated_then_flipped = apply_edits(source, {"rotation": 90, "flip_horizontal": True})
    assert rotated_then_flipped.size == (2, 3)
    assert rotated_then_flipped.getpixel((0, 0)) == source.getpixel((0, 0))
    assert rotated_then_flipped.getpixel((1, 2)) == source.getpixel((2, 1))


@pytest.mark.parametrize("settings", [
    {}, {"rotation": 0, "flip_horizontal": False, "flip_vertical": False,
         "brightness": 1, "contrast": 1, "saturation": 1, "sharpness": 1},
])
def test_default_edits_are_pixel_identical_and_return_independent_copy(settings):
    source = patterned_photo()
    original = source.tobytes()
    result = apply_edits(source, settings)
    assert result is not source
    assert result.size == source.size and result.tobytes() == original
    result.putpixel((0, 0), (0, 0, 0))
    assert source.tobytes() == original


def test_basic_adjustments_have_visible_effects():
    source = Image.new("RGB", (8, 8), (40, 80, 120))
    assert apply_edits(source, {"brightness": 1.5}).getpixel((4, 4)) == (60, 120, 180)
    gray = apply_edits(source, {"saturation": 0}).getpixel((4, 4))
    assert gray[0] == gray[1] == gray[2]
    source.paste((180, 140, 100), (4, 0, 8, 8))
    contrast = apply_edits(source, {"contrast": 1.5})
    assert contrast.tobytes() != source.tobytes()
    assert contrast.getpixel((1, 4))[0] < source.getpixel((1, 4))[0]
    assert contrast.getpixel((6, 4))[0] > source.getpixel((6, 4))[0]
    sharp = apply_edits(source, {"sharpness": 2})
    smooth = apply_edits(source, {"sharpness": 0})
    assert sharp.tobytes() != source.tobytes()
    assert smooth.tobytes() != source.tobytes()


@pytest.mark.parametrize("key,value,bounded,enhancer", [
    ("brightness", -4, .25, ImageEnhance.Brightness),
    ("brightness", 10, 2, ImageEnhance.Brightness),
    ("contrast", -4, .25, ImageEnhance.Contrast),
    ("contrast", 10, 2, ImageEnhance.Contrast),
    ("saturation", -4, 0, ImageEnhance.Color),
    ("saturation", 10, 2, ImageEnhance.Color),
    ("sharpness", -4, 0, ImageEnhance.Sharpness),
    ("sharpness", 10, 3, ImageEnhance.Sharpness),
])
def test_adjustments_are_bounded(key, value, bounded, enhancer):
    source = patterned_photo().resize((12, 8), Image.Resampling.NEAREST)
    assert apply_edits(source, {key: value}).tobytes() == enhancer(source).enhance(bounded).tobytes()


@pytest.mark.parametrize("value", [None, "invalid", float("nan"), float("inf")])
def test_unusable_saved_adjustment_values_fall_back_to_default(value):
    source = patterned_photo()
    assert apply_edits(source, {"brightness": value}).tobytes() == source.tobytes()


@pytest.mark.parametrize("settings", [
    {"rotation": 90}, {"flip_horizontal": True}, {"flip_vertical": True},
    {"brightness": 1.5}, {"contrast": 1.5}, {"saturation": 0}, {"sharpness": 2},
])
def test_edits_apply_to_photo_but_never_to_watermark(tmp_path, settings):
    photo, mark = tmp_path / "photo.png", tmp_path / "mark.png"
    source = Image.new("RGB", (40, 40), (40, 70, 100))
    source.paste((130, 90, 50), (20, 0, 40, 40))
    source.paste((70, 100, 130), (0, 20, 20, 40))
    source.save(photo)
    overlay = Image.new("RGBA", source.size, (0, 0, 0, 0))
    overlay.paste((35, 190, 75, 255), (0, 0, 8, 40))
    overlay.save(mark)
    result = compose(photo, mark, settings)
    expected_photo = apply_edits(source, settings)
    assert result.getpixel((3, 15)) == (35, 190, 75)
    assert result.getpixel((3, 25)) == (35, 190, 75)
    assert result.crop((8, 0, 40, 40)).tobytes() == expected_photo.crop((8, 0, 40, 40)).tobytes()


def test_render_photo_and_composite_preserve_original_files(tmp_path):
    photo, mark = tmp_path / "photo.png", tmp_path / "mark.png"
    source = patterned_photo().resize((60, 40), Image.Resampling.NEAREST)
    source.save(photo)
    overlay = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    overlay.paste((255, 255, 255, 255), (0, 0, 5, 40))
    overlay.save(mark)
    before = {path: hashlib.sha256(path.read_bytes()).digest() for path in (photo, mark)}
    settings = {"rotation": 90, "brightness": 1.5, "flip_vertical": True}
    preview = render_photo(photo, settings)
    assert preview.size == (40, 60)
    assert preview.tobytes() == apply_edits(source, settings).tobytes()
    assert render_photo(photo, settings, long_edge=30).size == (20, 30)
    assert render_photo(photo, settings, long_edge=300).size == (40, 60)
    assert compose(photo, mark, settings).size == (40, 40)
    assert before == {path: hashlib.sha256(path.read_bytes()).digest() for path in (photo, mark)}


def test_exif_orientation_precedes_manual_rotation(tmp_path):
    photo = tmp_path / "oriented.jpg"
    source = Image.new("RGB", (60, 40), (60, 90, 120))
    source.paste((180, 90, 40), (30, 0, 60, 40))
    exif = Image.Exif()
    exif[274] = 6
    source.save(photo, exif=exif)
    oriented = load_photo(photo)
    assert oriented.size == (40, 60)
    result = render_photo(photo, {"rotation": 90})
    assert result.size == (60, 40)
    assert result.tobytes() == oriented.transpose(Image.Transpose.ROTATE_270).tobytes()


def test_existing_project_framing_keeps_original_composition(tmp_path):
    photo, mark = tmp_path / "photo.png", tmp_path / "mark.png"
    source = Image.new("RGB", (60, 40), "red")
    source.paste("blue", (30, 0, 60, 40))
    source.save(photo)
    overlay = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    overlay.paste((0, 255, 0, 255), (0, 0, 4, 40))
    overlay.save(mark)
    old_framing = {"x": 1, "y": .5, "zoom": 1}
    result = compose(photo, mark, old_framing)
    expected = Image.alpha_composite(source.crop((20, 0, 60, 40)).convert("RGBA"), overlay).convert("RGB")
    assert result.size == expected.size and result.tobytes() == expected.tobytes()
    defaults = {"rotation": 0, "flip_horizontal": False, "flip_vertical": False,
                "brightness": 1, "contrast": 1, "saturation": 1, "sharpness": 1}
    assert compose(photo, mark, {**old_framing, **defaults}).tobytes() == result.tobytes()
