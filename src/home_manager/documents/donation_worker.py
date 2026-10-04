"""Bounded child for donation checks: page images to check and redact, and the redacted copy (library/donations.py).

Run like the other readers (documents/receipt_service.ReceiptService.child), so a document is decoded only in a
resource-limited process. argv: source, folder, mode.
- pages-pdf, pages-image: render the source (a PDF, or a reading's preview PNG) to folder/page-N.png, at most 20 pages.
- redact: black out folder/boxes.json on folder/page-N.png and write folder/redacted.png (one page) or redacted.pdf.
"""

import json
from pathlib import Path
import sys
import warnings

MAX_PAGES = 20
MAX_PIXELS = 24_000_000


def render_pages(source: Path, folder: Path, pdf: bool):
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    if pdf:
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(source) as pdf:
            if not 1 <= len(pdf) <= MAX_PAGES:
                raise ValueError(f"Only documents of 1 to {MAX_PAGES} pages can be donated.")
            for index in range(len(pdf)):
                page = pdf[index]
                try:
                    width, height = page.get_size()
                    if width <= 0 or height <= 0:
                        raise ValueError("Invalid PDF page size.")
                    bitmap = page.render(scale=min(2, 2400 / max(width, height)))
                    try:
                        image = bitmap.to_pil()
                        image.convert("RGB").save(folder / f"page-{index + 1}.png", format="PNG")
                        image.close()
                    finally:
                        bitmap.close()
                finally:
                    page.close()
        return
    with Image.open(source) as image:
        if image.format != "PNG" or image.width * image.height > MAX_PIXELS:
            raise ValueError("The page image could not be prepared.")
        image.convert("RGB").save(folder / "page-1.png", format="PNG")


def redact(folder: Path):
    from PIL import Image, ImageDraw

    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    boxes = json.loads((folder / "boxes.json").read_text(encoding="utf-8"))
    pages = sorted(folder.glob("page-*.png"), key=lambda path: int(path.stem.split("-")[1]))
    if not 1 <= len(pages) <= MAX_PAGES:
        raise ValueError("The page images are missing; open the check again.")
    images = []
    for number, path in enumerate(pages, 1):
        image = Image.open(path).convert("RGB")
        draw = ImageDraw.Draw(image)
        for box in boxes:
            if box["page"] == number:
                left, top = box["x"] * image.width, box["y"] * image.height
                draw.rectangle([left, top, left + box["w"] * image.width, top + box["h"] * image.height], fill="black")
        images.append(image)
    if len(images) == 1:
        images[0].save(folder / "redacted.png", format="PNG")
    else:
        images[0].save(folder / "redacted.pdf", format="PDF", save_all=True, append_images=images[1:], resolution=150)


def main():
    if sys.stdin.buffer.readline().strip() != b"start":
        return
    source, folder, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    try:
        if mode in ("pages-pdf", "pages-image"):
            render_pages(source, folder, mode == "pages-pdf")
        elif mode == "redact":
            redact(folder)
        else:
            raise ValueError("Unknown donation step.")
    except Exception as exc:
        message = str(exc) if isinstance(exc, ValueError) else "The document's pages could not be prepared."
        (folder / "error.json").write_text(json.dumps({"error": message[:500]}), encoding="utf-8")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
