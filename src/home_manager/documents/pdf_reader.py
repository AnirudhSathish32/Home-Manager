"""Page-aware PDF evidence. Native decoding runs only in a bounded child."""
from io import BytesIO
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from ..core.paths import write_atomic
from .pdf_layout import MAX_DOCUMENT_CHARACTERS, PDF_EVIDENCE_BYTES, PDF_PREVIEW_BYTES, PDFLayout, capture_layout
from .receipt_schema import Issue, ReceiptResult, Region, StrictModel, TextLine, VisionTables
from .vision_tables import embedded_tables, restore_text_tables, validate_tables, verify_saved_tables

PDF_VERSION = "pdf-pages-v3-layout"
PDF_VERSIONS = ("pdf-pages-v1", "pdf-pages-v2-tables", PDF_VERSION)
# Several images read as one document's pages (documents/grouping.py), in the same page-aware shape as a PDF.
GROUP_VERSION = "receipt-images-v2-tables"


class PDFPage(StrictModel):
    number: int = Field(ge=1, le=200)
    method: Literal["embedded_text", "vision_model"]
    lines: list[TextLine] = Field(max_length=5000)
    vision_tables: VisionTables | None = None
    layout: PDFLayout | None = None
    # A scanned page holding several receipts: each piece of paper read on its own (documents/regions.py).
    regions: list[Region] = Field(default_factory=list, max_length=12)


class PDFResult(StrictModel):
    parser_version: Literal["pdf-pages-v1", "receipt-images-v1", "pdf-pages-v2-tables", "receipt-images-v2-tables", "pdf-pages-v3-layout"] = PDF_VERSION
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
            if page.vision_tables is not None:
                verify_saved_tables(page.vision_tables, page.lines)
            if page.layout is not None and (page.layout.source_hash != self.input_hash or page.layout.page_number != number):
                raise ValueError("PDF layout does not match its source hash/page.")
        return self

    @property
    def lines(self):
        return [line for page in self.pages for line in page.lines]

    @property
    def model_text(self):
        return "\n".join(line.text for line in self.lines)


def read_result(value):
    if value.get("transcription_method") == "pdf_pages":
        return restore_text_tables(PDFResult.model_validate({key: item for key, item in value.items() if key not in ("lines", "layout_context")}))
    return restore_text_tables(ReceiptResult.model_validate(value))


def complete_pdf(folder, config, digest, work=None):
    """Embedded text where trustworthy; vision only for pages that need it. Pages are never omitted."""
    from ..models.vision import transcribe
    manifest_path = folder / "pages.json"
    if manifest_path.stat().st_size > PDF_EVIDENCE_BYTES:
        raise ValueError("PDF manifest exceeds the evidence storage limit.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pages, issues = [], []
    for entry in manifest:
        number = entry["number"]
        layout = PDFLayout.model_validate(entry["layout"]) if entry.get("layout") else None
        if layout and layout.issues and entry["method"] == "embedded_text":
            issues.append(Issue(code="pdf_layout_review", message=f"Page {number} PDF layout needs review: {', '.join(layout.issues)}.",
                                evidence_ids=[block.id for block in layout.blocks if block.status == "needs_review"]))
        texts, regions = [entry["text"]], [Region.model_validate(region) for region in entry.get("regions", [])]
        if entry["method"] == "vision_model":
            texts = []
            for region in regions or [None]:
                if work:
                    work.check()
                texts.append(transcribe(config, folder / (f"page-{number}-region-{region.number}.png" if region else f"page-{number}.png"), work))
                if texts[-1].table_issue:
                    issues.append(Issue(code="vision_table_invalid", message=f"Page {number} table structure could not be validated; review table values against the source page."))
        lines = []
        tables = []
        for region, reading in zip(regions or [None], texts):
            start = len(lines)
            text = reading.full_text if entry["method"] == "vision_model" else reading
            parts = text.split("\n") if entry["method"] == "vision_model" else text.splitlines()
            lines += [TextLine(id=f"page-{number}-line-{start + index}", text=line, block_ids=[]) for index, line in enumerate(parts, 1)]
            if entry["method"] == "vision_model" and reading.tables:
                tables.extend(validate_tables(reading.tables, lines, prefix=f"page-{number}-", index_offset=start,
                                              table_start=len(tables) + 1).tables)
            if region and len(lines) > start:
                region.first_line, region.last_line = lines[start].id, lines[-1].id
        if entry["method"] == "embedded_text":
            try:
                tables = embedded_tables(lines, prefix=f"page-{number}-").tables
            except ValueError:
                tables = []
                issues.append(Issue(code="pdf_table_ambiguous", message=f"Page {number} table rows could not be reconstructed from embedded text; review their columns."))
        pages.append(PDFPage(number=number, method=entry["method"], lines=lines, regions=regions,
                             vision_tables=VisionTables(tables=tables), layout=layout))
    write_atomic(folder / "result.json", PDFResult(input_hash=digest, pages=pages, issues=issues).model_dump_json(), limit=PDF_EVIDENCE_BYTES)


def combine_pages(folder, digests, readings):
    """One page-aware result from the readings of a combined document's images (ReceiptResult each, in page order).
    Each image's lines become its page's lines, and its pieces of paper keep their line ranges."""
    pages = []
    for number, reading in enumerate(readings, 1):
        ids = {line.id: f"page-{number}-line-{index}" for index, line in enumerate(reading.lines, 1)}
        lines = [TextLine(id=ids[line.id], text=line.text, block_ids=[]) for line in reading.lines]
        regions = [region.model_copy(update={"first_line": ids.get(region.first_line or ""), "last_line": ids.get(region.last_line or "")})
                   for region in reading.regions]
        tables = []
        if reading.vision_tables:
            raw = [{"header_rows": [{"line_index": next(i for i, line in enumerate(reading.lines) if line.id == row.line_id),
                                      "cells": [cell.quote for cell in row.cells]} for row in table.header_rows],
                    "rows": [{"line_index": next(i for i, line in enumerate(reading.lines) if line.id == row.line_id),
                              "cells": [cell.quote for cell in row.cells]} for row in table.rows]}
                   for table in reading.vision_tables.tables]
            tables = validate_tables(raw, lines, prefix=f"page-{number}-").tables
        pages.append(PDFPage(number=number, method="vision_model", lines=lines, regions=regions,
                             vision_tables=VisionTables(tables=tables)))
    issues = list({issue.code: issue for reading in readings for issue in reading.issues
                   if issue.code in ("unreadable_text", "unverified_vision", "vision_table_invalid")}.values())
    write_atomic(folder / "result.json", PDFResult(parser_version=GROUP_VERSION, input_hash=digests[0], page_hashes=list(digests), pages=pages,
                                                   issues=issues).model_dump_json(), limit=4 * 1024**2)


def save_preview(image, path, remaining):
    with BytesIO() as output:
        image.save(output, format="PNG")
        payload = output.getvalue()
    if len(payload) > remaining:
        raise ValueError("PDF page previews exceed the storage limit.")
    write_atomic(path, payload, limit=remaining)
    return len(payload)


def worker(source, folder):
    import pypdfium2 as pdfium

    from ..library.storage import digest_file
    from .regions import find_regions
    digest = digest_file(Path(source))
    pages = []
    with pdfium.PdfDocument(source) as pdf:
        if not 1 <= len(pdf) <= 200:
            raise ValueError("PDF must contain 1–200 pages. Split larger documents.")
        total = characters = preview_bytes = manifest_bytes = 0
        for index in range(len(pdf)):
            # pypdfium2 pages, text pages and bitmaps are closed explicitly (no context-manager support).
            page, regions = pdf[index], []
            try:
                textpage = page.get_textpage()
                try:
                    if textpage.count_chars() > 100000:
                        raise ValueError("PDF page exceeds the text limit.")
                    text = textpage.get_text_bounded()
                    characters += textpage.count_chars()
                    if characters > MAX_DOCUMENT_CHARACTERS:
                        raise ValueError("PDF exceeds the document character limit.")
                    width, height = page.get_size()
                    if not 0 < width < 1_000_000 or not 0 < height < 1_000_000:
                        raise ValueError("Invalid PDF page size.")
                    bitmap = page.render(scale=min(2, 2400 / max(width, height)))
                    try:
                        layout = capture_layout(page, textpage, bitmap, index+1, digest, text)
                        image = bitmap.to_pil()
                        try:
                            preview_bytes += save_preview(image, folder / f"page-{index+1}.png", PDF_PREVIEW_BYTES-preview_bytes)
                            fallback = len(''.join(text.split())) < 40 or '\ufffd' in text or not layout.words
                            if fallback:
                                for number, bbox in enumerate(find_regions(image), 1):
                                    crop = image.crop(bbox)
                                    try:
                                        preview_bytes += save_preview(crop, folder / f"page-{index+1}-region-{number}.png", PDF_PREVIEW_BYTES-preview_bytes)
                                    finally:
                                        crop.close()
                                    regions.append({"number": number, "bbox": list(bbox)})
                        finally:
                            image.close()
                    finally:
                        bitmap.close()
                finally:
                    textpage.close()
                total += len(text.encode())
                if total > 2 * 1024**2:
                    raise ValueError("PDF exceeds the embedded-text limit.")
            finally:
                page.close()
            entry = {"number": index+1, "method": "vision_model" if fallback else "embedded_text", "text": text,
                     "regions": regions, "layout": layout.model_dump()}
            manifest_bytes += len(json.dumps(entry, ensure_ascii=False).encode("utf-8")) + 2
            if manifest_bytes > PDF_EVIDENCE_BYTES:
                raise ValueError("PDF layout exceeds the evidence storage limit.")
            pages.append(entry)
    write_atomic(folder / "pages.json", json.dumps(pages, ensure_ascii=False), limit=PDF_EVIDENCE_BYTES)


if __name__ == "__main__":
    import sys
    if sys.stdin.readline().strip() != "start":
        raise SystemExit(2)
    try:
        worker(sys.argv[1], Path(sys.argv[2]))
    except Exception:
        (Path(sys.argv[2]) / "error.json").write_text(json.dumps({"error": "PDF could not be read within the page, text, or resource limits. Check encryption or file damage."}), encoding="utf-8")
        raise SystemExit(1) from None
