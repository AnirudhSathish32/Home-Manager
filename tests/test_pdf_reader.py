"""The PDF worker, run in-process here (the app runs it in a limited child process): each page keeps its embedded
text or is rendered for vision, pages are never omitted, and evidence numbering is checked. End-to-end PDF reading
is in test_pdf.py."""

import json

import pytest

from home_manager.documents.pdf_reader import PDFResult, complete_pdf, read_result, worker
from home_manager.documents.receipt_schema import TextLine
from test_pdf import STATEMENT, make_pdf


def test_text_pages_keep_their_text_and_image_pages_are_rendered_for_vision(tmp_path):
    source = tmp_path / "statement.pdf"
    make_pdf(source, [STATEMENT, None, "short"])
    worker(str(source), tmp_path)
    pages = json.loads((tmp_path / "pages.json").read_text(encoding="utf-8"))
    assert [(page["number"], page["method"]) for page in pages] == [(1, "embedded_text"), (2, "vision_model"), (3, "vision_model")]
    assert "Closing balance 1,250.00" in pages[0]["text"]
    assert not (tmp_path / "page-1.png").exists()
    assert (tmp_path / "page-2.png").is_file() and (tmp_path / "page-3.png").is_file()  # Too little text counts as a scan.


def test_the_page_limit(tmp_path):
    source = tmp_path / "long.pdf"
    make_pdf(source, [STATEMENT] * 201)
    with pytest.raises(ValueError, match="1–200 pages"):
        worker(str(source), tmp_path)
    assert not (tmp_path / "pages.json").exists()


def test_embedded_pages_are_assembled_without_a_model(tmp_path):
    source = tmp_path / "statement.pdf"
    make_pdf(source, [STATEMENT, STATEMENT.replace("FIRST", "SECOND")])
    worker(str(source), tmp_path)
    complete_pdf(tmp_path, config=None, digest="d" * 64)  # No vision pages, so no model is needed.
    result = read_result(json.loads((tmp_path / "result.json").read_text(encoding="utf-8")))
    assert isinstance(result, PDFResult) and len(result.pages) == 2
    assert result.lines[0].id == "page-1-line-1" and result.pages[1].lines[0].text.startswith("SECOND")
    assert result.model_text.splitlines()[0] == "FIRST LOCAL BANK"


def test_misnumbered_evidence_is_refused():
    line = lambda page, number: TextLine(id=f"page-{page}-line-{number}", text="x", block_ids=[])
    PDFResult(input_hash="d" * 64, pages=[{"number": 1, "method": "embedded_text", "lines": [line(1, 1), line(1, 2)]}])
    for pages in ([{"number": 2, "method": "embedded_text", "lines": [line(2, 1)]}],
                  [{"number": 1, "method": "embedded_text", "lines": [line(1, 2)]}],
                  [{"number": 1, "method": "embedded_text", "lines": [line(2, 1)]}]):
        with pytest.raises(ValueError, match="misnumbered"):
            PDFResult(input_hash="d" * 64, pages=pages)
