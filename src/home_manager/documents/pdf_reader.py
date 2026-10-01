"""Page-aware PDF evidence. Native decoding runs only in a bounded child."""
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from ..core.paths import write_atomic
from .receipt_schema import Issue, ReceiptResult, Region, StrictModel, TextLine

PDF_VERSION = "pdf-pages-v1"
# Several images read as one document's pages (documents/grouping.py), in the same page-aware shape as a PDF.
GROUP_VERSION = "receipt-images-v1"


class PDFPage(StrictModel):
    number: int = Field(ge=1, le=200)
    method: Literal["embedded_text", "vision_model"]
    lines: list[TextLine] = Field(max_length=5000)
    # A scanned page holding several receipts: each piece of paper read on its own (documents/regions.py).
    regions: list[Region] = Field(default_factory=list, max_length=12)


class PDFResult(StrictModel):
    parser_version: Literal["pdf-pages-v1", "receipt-images-v1"] = "pdf-pages-v1"
    input_hash: str
    # A combined document: each page's preserved image hash, in page order (input_hash is the first).
    page_hashes: list[str] = Field(default_factory=list, max_length=20)
    transcription_method: Literal["pdf_pages"] = "pdf_pages"
    pages: list[PDFPage] = Field(min_length=1, max_length=200)
    issues: list[Issue] = Field(default_factory=list)

    @model_validator(mode="after")
    def page_order(self):
        for number, page in enumerate(self.pages, 1):
            if page.number != number or any(line.id != f"page-{number}-line-{i}" for i, line in enumerate(page.lines, 1)):
                raise ValueError("PDF evidence has missing or misnumbered pages/lines.")
        return self

    @property
    def lines(self):
        return [line for page in self.pages for line in page.lines]

    @property
    def model_text(self):
        return "\n".join(line.text for line in self.lines)


def read_result(value):
    if value.get("transcription_method") == "pdf_pages":
        return PDFResult.model_validate({key: item for key, item in value.items() if key != "lines"})
    return ReceiptResult.model_validate(value)


def complete_pdf(folder, config, digest, work=None):
    """Embedded text where trustworthy; vision only for pages that need it. Pages are never omitted."""
    from ..models.vision import transcribe
    manifest = json.loads((folder / "pages.json").read_text(encoding="utf-8"))
    pages = []
    for entry in manifest:
        number = entry["number"]
        texts, regions = [entry["text"]], [Region.model_validate(region) for region in entry.get("regions", [])]
        if entry["method"] == "vision_model":
            texts = []
            for region in regions or [None]:
                if work:
                    work.check()
                texts.append(transcribe(config, folder / (f"page-{number}-region-{region.number}.png" if region else f"page-{number}.png"), work).full_text)
        lines = []
        for region, text in zip(regions or [None], texts):
            start = len(lines)
            lines += [TextLine(id=f"page-{number}-line-{start + index}", text=line, block_ids=[]) for index, line in enumerate(text.splitlines(), 1)]
            if region and len(lines) > start:
                region.first_line, region.last_line = lines[start].id, lines[-1].id
        pages.append(PDFPage(number=number, method=entry["method"], lines=lines, regions=regions))
    write_atomic(folder / "result.json", PDFResult(input_hash=digest, pages=pages).model_dump_json(), limit=4 * 1024**2)


def combine_pages(folder, digests, readings):
    """One page-aware result from the readings of a combined document's images (ReceiptResult each, in page order).
    Each image's lines become its page's lines, and its pieces of paper keep their line ranges."""
    pages = []
    for number, reading in enumerate(readings, 1):
        ids = {line.id: f"page-{number}-line-{index}" for index, line in enumerate(reading.lines, 1)}
        lines = [TextLine(id=ids[line.id], text=line.text, block_ids=[]) for line in reading.lines]
        regions = [region.model_copy(update={"first_line": ids.get(region.first_line or ""), "last_line": ids.get(region.last_line or "")})
                   for region in reading.regions]
        pages.append(PDFPage(number=number, method="vision_model", lines=lines, regions=regions))
    issues = list({issue.code: issue for reading in readings for issue in reading.issues if issue.code in ("unreadable_text", "unverified_vision")}.values())
    write_atomic(folder / "result.json", PDFResult(parser_version=GROUP_VERSION, input_hash=digests[0], page_hashes=list(digests), pages=pages,
                                                   issues=issues).model_dump_json(), limit=4 * 1024**2)


def worker(source, folder):
    import pypdfium2 as pdfium

    from .regions import find_regions
    pages = []
    with pdfium.PdfDocument(source) as pdf:
        if not 1 <= len(pdf) <= 200:
            raise ValueError("PDF must contain 1–200 pages. Split larger documents.")
        total = 0
        for index in range(len(pdf)):
            # pypdfium2 pages, text pages and bitmaps are closed explicitly (no context-manager support).
            page, regions = pdf[index], []
            try:
                textpage = page.get_textpage()
                try:
                    if textpage.count_chars() > 100000:
                        raise ValueError("PDF page exceeds the text limit.")
                    text = textpage.get_text_bounded()
                finally:
                    textpage.close()
                total += len(text.encode())
                if total > 2 * 1024**2:
                    raise ValueError("PDF exceeds the embedded-text limit.")
                # Near-empty or undecodable text layers are treated as scanned pages.
                fallback = len(''.join(text.split())) < 40 or '\ufffd' in text
                if fallback:
                    width, height = page.get_size()
                    if width <= 0 or height <= 0:
                        raise ValueError("Invalid PDF page size.")
                    bitmap = page.render(scale=min(2, 2400 / max(width, height)))
                    try:
                        image = bitmap.to_pil()
                        image.save(folder / f"page-{index+1}.png")
                        # A flatbed scan of several receipts saved as a PDF: each piece of paper is read on its own.
                        for number, bbox in enumerate(find_regions(image), 1):
                            image.crop(bbox).save(folder / f"page-{index+1}-region-{number}.png")
                            regions.append({"number": number, "bbox": list(bbox)})
                        image.close()
                    finally:
                        bitmap.close()
            finally:
                page.close()
            pages.append({"number": index+1, "method": "vision_model" if fallback else "embedded_text", "text": text, "regions": regions})
    write_atomic(folder / "pages.json", json.dumps(pages))


if __name__ == "__main__":
    import sys
    if sys.stdin.readline().strip() != "start":
        raise SystemExit(2)
    try:
        worker(sys.argv[1], Path(sys.argv[2]))
    except Exception:
        (Path(sys.argv[2]) / "error.json").write_text(json.dumps({"error": "PDF could not be read within the page, text, or resource limits. Check encryption or file damage."}), encoding="utf-8")
        raise SystemExit(1) from None
