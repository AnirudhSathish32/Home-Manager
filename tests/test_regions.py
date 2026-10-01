"""Separating pieces of paper in one image (documents/regions.py), on synthetic scans."""

import random

from PIL import Image, ImageDraw

from home_manager.documents.regions import find_regions


def receipt(draw, left, top, width, height, paper="white", lines=24, gaps=()):
    """A receipt: paper with rows of dark 'text', optionally with blank bands (gaps) between sections."""
    draw.rectangle((left, top, left + width, top + height), fill=paper)
    step = height / (lines + 2)
    for index in range(lines):
        if index in gaps:
            continue
        y = top + step * (index + 1)
        draw.rectangle((left + width * .08, y, left + width * (.5 if index % 3 else .9), y + step * .45), fill="black")
        draw.rectangle((left + width * .72, y, left + width * .9, y + step * .45), fill="black")


def test_three_receipts_on_a_dark_flatbed():
    image = Image.new("RGB", (2400, 1800), (35, 35, 40))
    draw = ImageDraw.Draw(image)
    for left in (100, 900, 1700):
        receipt(draw, left, 150 + left // 10, 600, 1400)
    regions = find_regions(image)
    assert len(regions) == 3
    assert [region[0] < 1000 for region in regions] == [True, True, False]  # Left to right.
    for (left, top, right, bottom), expected in zip(regions, (100, 900, 1700)):
        assert left <= expected and right >= expected + 600 and bottom - top >= 1300


def test_grid_of_four_reads_row_by_row():
    image = Image.new("RGB", (2000, 2000), (20, 20, 20))
    draw = ImageDraw.Draw(image)
    for top in (100, 1100):
        for left in (100, 1100):
            receipt(draw, left, top, 700, 800)
    regions = find_regions(image)
    assert [(region[0] // 1000, region[1] // 1000) for region in regions] == [(0, 0), (1, 0), (0, 1), (1, 1)]


def test_stacked_strip_on_a_dark_table():
    image = Image.new("RGB", (900, 3000), (60, 45, 30))
    draw = ImageDraw.Draw(image)
    for top in (80, 1080, 2080):
        receipt(draw, 150, top, 600, 820)
    assert len(find_regions(image)) == 3


def test_side_by_side_on_a_white_lid():
    image = Image.new("RGB", (2400, 1600), "white")
    draw = ImageDraw.Draw(image)
    receipt(draw, 100, 100, 900, 1400)
    receipt(draw, 1350, 150, 900, 1300)
    regions = find_regions(image)
    assert len(regions) == 2 and regions[0][2] <= 1350 and regions[1][0] >= 1000


def test_one_receipt_is_never_split():
    # Filling the frame, with blank bands between its sections.
    image = Image.new("RGB", (900, 2400), "white")
    receipt(ImageDraw.Draw(image), 0, 0, 900, 2400, lines=40, gaps=(5, 6, 7, 8, 20, 21, 22, 23, 24))
    assert find_regions(image) == []
    # On a dark table, with a fold shadow across it.
    image = Image.new("RGB", (1600, 2000), (30, 30, 30))
    draw = ImageDraw.Draw(image)
    receipt(draw, 400, 100, 800, 1800, gaps=(10, 11))
    draw.rectangle((400, 990, 1200, 1000), fill=(120, 120, 120))
    assert find_regions(image) == []


def test_noise_and_specks_make_no_regions():
    rng = random.Random(7)
    image = Image.new("RGB", (1600, 1600), (30, 30, 30))
    draw = ImageDraw.Draw(image)
    receipt(draw, 300, 200, 900, 1200)
    for _ in range(200):  # Dust and crumbs on the scanner glass.
        x, y = rng.randrange(1600), rng.randrange(1600)
        draw.rectangle((x, y, x + 6, y + 6), fill="white")
    assert find_regions(image) == []
    assert find_regions(Image.new("RGB", (40, 40), "white")) == []  # Too small to judge.


def test_each_piece_of_paper_is_transcribed_on_its_own(tmp_path, monkeypatch):
    from home_manager.documents import receipt_worker
    from home_manager.documents.receipt_schema import ReceiptResult
    from home_manager.models import vision
    image = Image.new("RGB", (2400, 1800), (35, 35, 40))
    draw = ImageDraw.Draw(image)
    for left in (100, 900, 1700):
        receipt(draw, left, 200, 600, 1400)
    image.save(tmp_path / "scan.png")
    out = tmp_path / "out"
    out.mkdir()
    receipt_worker.extract_receipt(tmp_path / "scan.png", out, 0)
    seen = []

    def transcribe(config, path, work=None):
        seen.append(path.name)
        return type("Text", (), {"full_text": f"{path.stem.upper()}\nTotal 1.00"})()
    monkeypatch.setattr(vision, "transcribe", transcribe)
    vision.transcribe_preview(out, vision.VisionConfig(model="synthetic-vision"), None)
    result = ReceiptResult.model_validate_json((out / "result.json").read_bytes())
    assert seen == ["region-1.png", "region-2.png", "region-3.png"]
    assert [line.id for line in result.lines] == [f"line-{number}" for number in range(1, 7)]
    assert [(region.first_line, region.last_line) for region in result.regions] == [("line-1", "line-2"), ("line-3", "line-4"), ("line-5", "line-6")]
    assert result.lines[2].text == "REGION-2"
