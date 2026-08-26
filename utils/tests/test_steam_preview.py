"""Unit tests for deriving a Workshop-legal preview image.

Steam rejects a preview above 1 MB outright, and every logo in this family is a
1024² PNG with a soft golden glow — the one thing PNG compresses badly. The
ladder therefore matters more than any single size: it must come down in
resolution before it gives up colour depth, because the Workshop renders
previews at roughly 268² while banding in a gradient stays visible at any size.
"""

import pytest
import steam_preview
from PIL import Image


def _logo(tmp_path, side=1024, noisy=True):
    """A stand-in for a mod logo: a gradient, so it compresses like the real ones."""
    img = Image.new("RGBA", (side, side))
    px = img.load()
    for y in range(side):
        for x in range(side):
            px[x, y] = (
                ((x * 7) % 256, (y * 11) % 256, ((x + y) * 13) % 256, 255)
                if noisy
                else (10, 80, 90, 255)
            )
    path = tmp_path / "logo.png"
    img.save(path)
    return path


def test_a_small_image_is_taken_at_full_resolution(tmp_path):
    src = _logo(tmp_path, side=64, noisy=False)
    dest = tmp_path / "preview.png"

    size, how = steam_preview.derive_preview(src, dest)

    assert dest.is_file()
    assert "1024" not in how  # not upscaled
    assert size < 1_048_576


def test_it_steps_down_until_the_result_fits(tmp_path):
    src = _logo(tmp_path)
    dest = tmp_path / "preview.png"

    size, how = steam_preview.derive_preview(src, dest, limit=200_000)

    assert size <= 200_000
    assert "lossless" in how


def test_transparency_survives(tmp_path):
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (64, 64), (255, 200, 0, 255)), (96, 96))
    src = tmp_path / "logo.png"
    img.save(src)
    dest = tmp_path / "preview.png"

    steam_preview.derive_preview(src, dest)

    assert Image.open(dest).convert("RGBA").getpixel((0, 0))[3] == 0


def test_quantisation_is_the_last_resort_not_the_first(tmp_path):
    src = _logo(tmp_path)
    dest = tmp_path / "preview.png"

    _, how = steam_preview.derive_preview(src, dest, limit=400_000)

    assert "quantised" not in how, "a lossless smaller size must be preferred"


def test_an_impossible_limit_is_reported_rather_than_silently_shipped(tmp_path):
    src = _logo(tmp_path)
    dest = tmp_path / "preview.png"

    with pytest.raises(ValueError, match="1 MB|fit|limit"):
        steam_preview.derive_preview(src, dest, limit=200)
