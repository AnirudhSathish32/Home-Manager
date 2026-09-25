"""Page-aware PDF evidence. Native decoding runs only in a bounded child."""
import json
from pathlib import Path
from typing import Literal
from pydantic import Field, model_validator
from .paths import write_atomic
from .receipt_schema import StrictModel, TextLine, Issue, ReceiptResult

PDF_VERSION = "pdf-pages-v1"


class PDFPage(StrictModel):
    number: int = Field(ge=1, le=200)
    method: Literal["embedded_text", "vision_model"]
    lines: list[TextLine] = Field(max_length=5000)


class PDFResult(StrictModel):
    parser_version: Literal["pdf-pages-v1"] = PDF_VERSION
    input_hash: str
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
    from .vision import transcribe
    manifest = json.loads((folder / "pages.json").read_text(encoding="utf-8"))
    pages = []
    for entry in manifest:
        number = entry["number"]
        text = entry["text"]
        if entry["method"] == "vision_model":
            if work:
                work.check()
            text = transcribe(config, folder / f"page-{number}.png", work).full_text
        lines = [TextLine(id=f"page-{number}-line-{i}", text=line, block_ids=[]) for i, line in enumerate(text.splitlines(), 1)]
        pages.append(PDFPage(number=number, method=entry["method"], lines=lines))
    write_atomic(folder / "result.json", PDFResult(input_hash=digest, pages=pages).model_dump_json(), limit=4 * 1024**2)


def worker(source, folder):
    import pypdfium2 as pdfium
    pages = []
    with pdfium.PdfDocument(source) as pdf:
        if not 1 <= len(pdf) <= 200:
            raise ValueError("PDF must contain 1–200 pages. Split larger documents.")
        total = 0
        for index in range(len(pdf)):
            # pypdfium2 pages, text pages and bitmaps are closed explicitly (no context-manager support).
            page = pdf[index]
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
                        image.close()
                    finally:
                        bitmap.close()
            finally:
                page.close()
            pages.append({"number": index+1, "method": "vision_model" if fallback else "embedded_text", "text": text})
    write_atomic(folder / "pages.json", json.dumps(pages))


if __name__ == "__main__":
    import sys
    if sys.stdin.readline().strip() != "start":
        raise SystemExit(2)
    try:
        worker(sys.argv[1], Path(sys.argv[2]))
    except Exception:
        (Path(sys.argv[2]) / "error.json").write_text(json.dumps({"error": "PDF could not be read within the page, text, or resource limits. Check encryption or file damage."}), encoding="utf-8")
        raise SystemExit(1)
