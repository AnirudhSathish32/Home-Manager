"""Bounded image preparation and barcode decoding; text extraction runs in the coordinator."""

import base64
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import sys
import warnings


MAX_PIXELS = 24_000_000
TILE = 1600
OVERLAP = 160


def positions(length: int):
    if length <= TILE:
        return [0]
    return list(range(0, length - TILE, TILE - OVERLAP)) + [length - TILE]


def bounds(polygon):
    xs, ys = zip(*polygon)
    return min(xs), min(ys), max(xs), max(ys)


def same_region(first, second):
    a, b = bounds(first), bounds(second)
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    area = min(max(1, (a[2]-a[0])*(a[3]-a[1])), max(1, (b[2]-b[0])*(b[3]-b[1])))
    return intersection / area > .65


def extract_receipt(source: Path, output: Path, rotation: int):
    # Imports intentionally occur after the coordinator attaches resource limits.
    from PIL import Image, ImageOps
    import zxingcpp

    from .paths import write_atomic
    from .receipt_schema import CodeEvidence, Issue, ReceiptResult, code_transcript

    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    with Image.open(source) as raw:
        if raw.format not in ("PNG", "JPEG"):
            raise ValueError("Only decoded PNG/JPEG receipt images are supported in this slice.")
        if raw.width * raw.height > MAX_PIXELS or max(raw.size) > 40000:
            raise ValueError("Image exceeds the 24-megapixel/40,000-pixel-side limit; use a smaller scan.")
        if getattr(raw, "n_frames", 1) != 1:
            raise ValueError("Multi-frame images require an explicit page reader; no frames were silently omitted.")
        original_width, original_height = raw.size
        image_format = raw.format
        orientation = raw.getexif().get(274)
        oriented = ImageOps.exif_transpose(raw)
        rgba = oriented.convert("RGBA")
        image = Image.new("RGB", rgba.size, "white")
        image.paste(rgba, mask=rgba.getchannel("A"))
        if rotation:
            image = image.rotate(-rotation, expand=True)
    with open(output / "preview.png", "wb") as stream:
        image.save(stream, format="PNG")
        stream.flush()
        os.fsync(stream.fileno())
    if (output / "preview.png").stat().st_size > 64 * 1024 * 1024:
        raise ValueError("Preview exceeds the output size limit; use a smaller scan.")

    codes, issues = [], []

    def collect_codes(region, x_offset=0, y_offset=0):
        for code in zxingcpp.read_barcodes(region, return_errors=True, text_mode=zxingcpp.TextMode.Plain):
            pos = code.position
            polygon = [(float(p.x + x_offset), float(p.y + y_offset)) for p in (pos.top_left, pos.top_right, pos.bottom_right, pos.bottom_left)]
            payload = bytes(code.bytes)
            encoded = base64.b64encode(payload).decode("ascii")
            if any(existing.bytes_base64 == encoded and same_region(existing.polygon, polygon) for existing in codes):
                continue
            codes.append(CodeEvidence(id=f"code-{len(codes)+1}", format=str(code.format),
                                      text=code.text, bytes_base64=encoded, valid=bool(code.valid),
                                      error=str(code.error) if code.error else None, polygon=polygon))
            if len(codes) > 100:
                raise ValueError("Too many barcode regions; split this image into individual receipts.")

    collect_codes(image)
    tiles = [(x, y) for y in positions(image.height) for x in positions(image.width)]
    for x, y in tiles:
        tile = image.crop((x, y, min(image.width, x + TILE), min(image.height, y + TILE)))
        if len(tiles) > 1:
            collect_codes(tile, x, y)
    if not codes:
        issues.append(Issue(code="no_code_decoded", message="No QR/barcode was decoded. A code may be absent, damaged or unreadable; its pixels remain preserved."))
    if any(not code.valid for code in codes):
        issues.append(Issue(code="code_decode_error", message="Some detected codes could not be decoded reliably; inspect their image regions."))
    result = ReceiptResult(input_hash=digest, image_format=image_format,
                           original_width=original_width, original_height=original_height,
                           width=image.width, height=image.height, exif_orientation=orientation,
                           clockwise_rotation=rotation,
                           engine={name: version(name) for name in ("pillow", "zxing-cpp")},
                           model_hashes={}, blocks=[], lines=[], ocr_text="",
                           codes=codes, extracted_text=code_transcript(codes), fields=None, issues=issues)
    write_atomic(output / "prepared.json", result.model_dump_json(indent=2), limit=4 * 1024**2)


def main():
    # Coordinator sends this only after the child is assigned to a Windows Job.
    if sys.stdin.buffer.readline().strip() != b"start":
        return
    output = Path(sys.argv[2])
    try:
        extract_receipt(Path(sys.argv[1]), output, int(sys.argv[3]))
    except Exception as exc:
        # No raw receipt text or exception paths in logs/results.
        message = str(exc) if isinstance(exc, ValueError) else "Local image preparation failed. Verify the image and installed image dependencies."
        (output / "error.json").write_text(json.dumps({"error": message[:1000]}), encoding="utf-8")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
