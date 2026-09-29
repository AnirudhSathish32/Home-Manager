"""Image preparation, run in-process here (the app runs it in a limited child process): tiling covers the whole image,
duplicate codes are recognized by region, and unsupported or oversized images are refused before any result is written."""

import json
import warnings

from PIL import Image
import pytest

from home_manager.documents import receipt_worker
from home_manager.documents.receipt_worker import OVERLAP, TILE, bounds, extract_receipt, positions, same_region


@pytest.mark.parametrize("length", [1, TILE - 1, TILE, TILE + 1, 2 * TILE, 3100, 10_000, 40_000])
def test_tiles_cover_the_whole_side_with_overlap(length):
    starts = positions(length)
    assert starts[0] == 0 and starts == sorted(set(starts))
    assert starts[-1] + TILE >= length  # The last tile reaches the far edge.
    for first, second in zip(starts, starts[1:]):
        assert second - first <= TILE - OVERLAP or second == length - TILE  # Neighbours overlap, so no code is cut in two.
        assert first + TILE > second


def test_regions_are_the_same_when_they_mostly_overlap():
    square = [(0, 0), (100, 0), (100, 100), (0, 100)]
    assert bounds(square) == (0, 0, 100, 100)
    shifted = [(x + 10, y + 10) for x, y in square]
    assert same_region(square, shifted)  # 81% overlap: the same code found again in a neighbouring tile.
    assert not same_region(square, [(x + 60, y) for x, y in square])  # 40%: a different code beside it.
    assert not same_region(square, [(x + 500, y) for x, y in square])
    point = [(5, 5), (5, 5), (5, 5), (5, 5)]  # Degenerate polygons never divide by zero.
    assert same_region(point, point) is False


@pytest.fixture
def isolated(monkeypatch):
    """extract_receipt changes Pillow's pixel limit and the warning filters, as the child process wants; keep them here."""
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", Image.MAX_IMAGE_PIXELS)
    with warnings.catch_warnings():
        yield


def test_a_plain_image_is_prepared_with_its_size_and_rotation(tmp_path, isolated):
    source = tmp_path / "receipt.png"
    Image.new("RGBA", (300, 120), (255, 255, 255, 0)).save(source)
    extract_receipt(source, tmp_path, 90)
    result = json.loads((tmp_path / "prepared.json").read_text(encoding="utf-8"))
    assert (result["original_width"], result["original_height"], result["width"], result["height"]) == (300, 120, 120, 300)
    assert result["image_format"] == "PNG" and result["clockwise_rotation"] == 90
    assert result["codes"] == [] and [issue["code"] for issue in result["issues"]] == ["no_code_decoded"]
    with Image.open(tmp_path / "preview.png") as preview:
        assert preview.size == (120, 300) and preview.mode == "RGB"  # Transparency is flattened onto white.


@pytest.mark.parametrize("save", [
    lambda path: Image.new("RGB", (10, 10)).save(path, format="GIF"),
    lambda path: Image.new("RGB", (10, 10)).save(path, format="BMP"),
])
def test_only_png_and_jpeg_are_read(tmp_path, isolated, save):
    source = tmp_path / "receipt.png"
    save(source)
    with pytest.raises(ValueError, match="PNG/JPEG"):
        extract_receipt(source, tmp_path, 0)
    assert not (tmp_path / "prepared.json").exists()


def test_oversized_images_are_refused(tmp_path, isolated, monkeypatch):
    monkeypatch.setattr(receipt_worker, "MAX_PIXELS", 10_000)
    source = tmp_path / "receipt.png"
    Image.new("RGB", (120, 100)).save(source)  # 12,000 pixels: over the limit, under Pillow's hard stop at twice it.
    with pytest.raises((ValueError, Image.DecompressionBombWarning)):
        extract_receipt(source, tmp_path, 0)
    assert not (tmp_path / "prepared.json").exists()
