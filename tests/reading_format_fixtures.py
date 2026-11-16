"""Synthetic fixtures for specs/receipt-layout-eval: the committed inputs and the paths of the v7 baseline captures.

tests/reading_format_data/ holds what today's code (receipt-vision-v7-indent, pdf-pages-v4-indent, receipt-images-v3-indent)
read and sent for three synthetic inputs, before any application change of this feature (plans/receipt-layout-eval SL-01):

  inputs/receipt.png                  white paper with grey bars, one region (an image reading)
  inputs/page1.png, inputs/page2.png  the two pages of a combined document
  inputs/scan.pdf                     one image-only page (a scanned PDF)
  v7_<kind>_requests.json             every vision request body, each image URL replaced by sha256:<hex of the image bytes>
  v7_<kind>_result.json               the stored parse_runs.result_json
  v7_<kind>_options.json              the stored parse_runs.options_json
  v7_vision_settings.json             the settings file configure_vision wrote

with <kind> image, pdf or group. They were written by
`CAPTURE_READING_BASELINE=1 .venv/bin/python -m pytest tests/test_reading_format_capture.py -q`. Never regenerate them with
changed code: a later test compares the new code's output with these files. Nothing here is drawn with a font, so the input
bytes are the same on every computer; tests/reading_format_data/** is `-text` in .gitattributes so a checkout never rewrites them.
"""

import hashlib
import json
from pathlib import Path
import re

from PIL import Image, ImageDraw

DATA = Path(__file__).parent / "reading_format_data"
INPUTS = DATA / "inputs"
KINDS = ("image", "pdf", "group")
CAPTURES = {kind: {part: DATA / f"v7_{kind}_{part}.json" for part in ("requests", "result", "options")} for kind in KINDS}
SETTINGS = DATA / "v7_vision_settings.json"
INPUT_FILES = {name: INPUTS / name for name in ("receipt.png", "page1.png", "page2.png", "scan.pdf")}
# sha256 of each committed input, checked before anything is captured and by the self-test.
INPUT_HASHES = {
    "receipt.png": "34b86805dd7fa74e134729bd63a708c99cfbcd40c13ef0fccb2ef021aa96969a",
    "page1.png": "a0446c714fef3c7db5de457a5c76c11a42546cc0faa4070060d3c66bc8a55f83",
    "page2.png": "f012abd85ebe4d6a8f39c42ff75e79ea4ceb8162c10d7a2b36fcb9cb86e37648",
    "scan.pdf": "7674a7f5321db265e3307412a87a0bf3a7f8d5105e4a6eaf33ce0ebcf22ac471",
}
GROUP_SPLIT = 20  # The breakfast lines 1 – GROUP_SPLIT are page 1's answer, the rest page 2's.


def sha256_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def draw_bars(path, bars):
    """White paper (900 x 1100) with grey bars drawn as plain rectangles: no font, so the same bytes on every computer.
    bars: (left, top, right) per bar; each is 24 pixels tall."""
    image = Image.new("RGB", (900, 1100), "white")
    draw = ImageDraw.Draw(image)
    for left, top, right in bars:
        draw.rectangle((left, top, right, top + 23), fill=(90, 90, 90))
    image.save(path, optimize=False, compress_level=9)


RECEIPT_BARS = [(40 + (60 if row in (7, 8, 9, 13) else 0), 30 + row * 48, 300 + (row * 37) % 420) for row in range(20)]
PAGE_BARS = ([(40, 30 + row * 48, 260 + (row * 53) % 380) for row in range(12)],
             [(40 + (60 if row in (3, 4) else 0), 30 + row * 48, 240 + (row * 41) % 400) for row in range(10)])


def write_inputs():
    """Draw the four committed inputs (run once, by the author of the fixtures; the files are the source of truth)."""
    from test_pdf import make_pdf
    INPUTS.mkdir(parents=True, exist_ok=True)
    draw_bars(INPUT_FILES["receipt.png"], RECEIPT_BARS)
    draw_bars(INPUT_FILES["page1.png"], PAGE_BARS[0])
    draw_bars(INPUT_FILES["page2.png"], PAGE_BARS[1])
    make_pdf(INPUT_FILES["scan.pdf"], [None])


PORT = re.compile(r"127\.0\.0\.1:\d+")
IMAGE_URL = re.compile(r"^data:image/png;base64,")


def mask_port(text):
    """Each 127.0.0.1:<port> becomes 127.0.0.1:PORT, applied identically when writing and when comparing, so no fixed port is
    needed and two test runs can't collide."""
    return PORT.sub("127.0.0.1:PORT", text)


def _hash_images(node):
    import base64
    if isinstance(node, dict):
        return {key: (f"sha256:{hashlib.sha256(base64.b64decode(IMAGE_URL.sub('', value))).hexdigest()}"
                      if key == "url" and isinstance(value, str) and IMAGE_URL.match(value) else _hash_images(value))
                for key, value in node.items()}
    if isinstance(node, list):
        return [_hash_images(child) for child in node]
    return node


def dump_vision_requests(requests):
    """The text a v7_<kind>_requests.json capture holds for a list of request bodies (JSON, indent 2, each image URL replaced by
    the sha256 of the image bytes), before mask_port; the one way to write or compare them."""
    return json.dumps(_hash_images(requests), indent=2, ensure_ascii=False) + "\n"


def v7_answer(texts, indents=None):
    """A v7 vision answer, {"lines": [{"text", "indent"}]}: what today's code is fed for the captures. indents: one per line
    (default 0 on every line)."""
    indents = [0] * len(texts) if indents is None else indents
    return {"lines": [{"text": text, "indent": indent} for text, indent in zip(texts, indents)]}
