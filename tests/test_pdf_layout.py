"""Independent text placements exercise native geometry without literal separators."""

import json
import random

from PIL import Image
import pytest

from home_manager.documents.pdf_layout import PDFLayout, point, visual_box
from home_manager.documents.pdf_reader import complete_pdf, read_result, worker
from home_manager.library.storage import digest_file
from test_pdf import make_pdf


def read_layout(tmp_path, items, **settings):
    source = tmp_path / "positioned.pdf"
    make_pdf(source, [{"items": items, **settings}])
    worker(str(source), tmp_path)
    return PDFLayout.model_validate(json.loads((tmp_path / "pages.json").read_text(encoding="utf-8"))[0]["layout"])


def payroll_items():
    return [(40, 700, "Description"), (210, 700, "YTD"), (330, 700, "Current"),
            (40, 680, "Regular pay"), (205, 680, "52000.00"), (335, 680, "2000.00"),
            (40, 660, "Bonus"), (215, 660, "500.00"),
            (40, 640, "Adjustment"), (220, 640, "-10.00"), (350, 640, "0.00")]


def grid(layout, index=0):
    table = layout.tables[index]
    return [[next(cell.text for cell in table.cells if cell.row == r and cell.column == c)
             for c in range(table.columns)] for r in range(table.rows)]


def test_shuffled_stream_retains_current_ytd_blanks_zeros_and_character_membership(tmp_path):
    items = payroll_items()
    random.Random(42).shuffle(items)
    layout = read_layout(tmp_path, items)
    assert len(layout.tables) == 1
    assert grid(layout) == [["Description", "YTD", "Current"], ["Regular pay", "52000.00", "2000.00"],
                            ["Bonus", "500.00", ""], ["Adjustment", "-10.00", "0.00"]]
    assert not layout.issues
    words = {word.id: word for word in layout.words}
    current = layout.tables[0].cells[5]
    assert "".join(layout.characters[index].text for id in current.word_ids for index in words[id].character_indexes) == "2000.00"
    assert all(char.bbox is None for char in layout.characters if char.generated)
    complete_pdf(tmp_path, config=None, digest=digest_file(tmp_path / "positioned.pdf"))
    result = read_result(json.loads((tmp_path / "result.json").read_text(encoding="utf-8")))
    assert result.pages[0].layout == layout
    assert "Bonus | 500.00 | " in layout.reading_text
    # Historical text is retained separately, rather than assigning its line IDs to new visual rows.
    assert result.pages[0].layout.raw_text.splitlines() == [line.text for line in result.lines]


@pytest.mark.parametrize("headers,body", [
    (["Item", "Qty", "Unit", "Total"], [["Widgets", "2", "12.50", "25.00"], ["Shipping", "1", "5.00", "5.00"]]),
    (["Description", "Debit", "Credit", "Balance"], [["Shop", "45.00", "", "955.00"], ["Deposit", "", "100.00", "1055.00"]]),
    (["Earnings", "Hours", "Rate", "Amount"], [["Regular", "80", "25.00", "2000.00"], ["Overtime", "5", "37.50", "187.50"]]),
])
def test_shared_tables_do_not_depend_on_document_type(tmp_path, headers, body):
    rows = [headers, *body]
    items = [(40+column*140, 700-row*20, text) for row, cells in enumerate(rows) for column, text in enumerate(cells) if text]
    layout = read_layout(tmp_path, items)
    assert grid(layout) == rows
    assert all(block.source == "pdf_text" for block in layout.blocks)


def test_side_by_side_tables_have_distinct_rows_and_ids(tmp_path):
    items = [(x, y, text) for offset in (0, 300) for x, y, text in
             [(40+offset, 700, "Description"), (180+offset, 700, "Amount"),
              (40+offset, 680, "Salary"), (180+offset, 680, "2000.00"),
              (40+offset, 660, "Bonus"), (180+offset, 660, "500.00")]]
    layout = read_layout(tmp_path, items)
    assert len(layout.tables) == 2
    assert grid(layout, 0) == grid(layout, 1)
    assert set(layout.blocks[0].line_ids).isdisjoint(layout.blocks[1].line_ids)


def test_two_column_letter_and_address_are_read_by_column_not_as_a_table(tmp_path):
    items = [(40, 700, "Dear neighbor"), (40, 680, "Please keep this letter"), (40, 660, "for your records."),
             (350, 700, "Mailing address"), (350, 680, "10 Example Street"), (350, 660, "Example City NY")]
    layout = read_layout(tmp_path, items)
    assert not layout.tables
    assert layout.reading_text.splitlines() == [text for _, _, text in items]


def test_title_and_footer_do_not_become_table_rows(tmp_path):
    layout = read_layout(tmp_path, [(40, 720, "Payroll statement - October"), *payroll_items(), (40, 620, "Keep this for your records")])
    assert len(layout.tables) == 1
    assert layout.blocks[0].kind != "table" and layout.blocks[-1].kind != "table"
    assert grid(layout)[0] == ["Description", "YTD", "Current"]


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_crop_rotation_transform_matches_pdfium_rendered_ink(tmp_path, rotation):
    layout = read_layout(tmp_path, payroll_items(), rotation=rotation, crop="20 30 580 760")
    assert layout.bounds == (20, 30, 580, 760)
    assert layout.rotation == rotation
    with Image.open(tmp_path / "page-1.png") as preview:
        assert preview.size == (layout.preview_width, layout.preview_height)
        for word in layout.words:
            box = visual_box(layout.page_to_preview, word.bbox)
            assert -1 <= box[0] < box[2] <= preview.width+1
            assert -1 <= box[1] < box[3] <= preview.height+1
            crop = preview.crop((int(box[0]), int(box[1]), int(box[2])+1, int(box[3])+1)).convert("L")
            assert crop.getextrema()[0] < 100
            crop.close()
    # The saved transform also agrees with the engine's coordinate converter.
    import pypdfium2 as pdfium
    with pdfium.PdfDocument(tmp_path / "positioned.pdf") as pdf:
        page = pdf[0]
        bitmap = page.render(scale=2)
        try:
            converter = bitmap.get_posconv(page)
            for x, y in [(20, 30), (580, 760), (300, 400)]:
                assert point(layout.page_to_preview, x, y) == pytest.approx(converter.to_bitmap(x, y), abs=1)
        finally:
            bitmap.close()
            page.close()


def test_overlapping_layer_is_preserved_but_not_promoted_to_a_table(tmp_path):
    items = payroll_items()
    layout = read_layout(tmp_path, items + items)
    assert layout.coverage == "needs_review" and "overlapping_text" in layout.issues
    assert not layout.tables
    assert len(layout.characters) > 100


@pytest.mark.parametrize("corruption", ["word", "reference", "cell", "duplicate", "coverage", "bounds", "column_swap", "row_swap"])
def test_saved_layout_rejects_invented_or_ambiguous_evidence(tmp_path, corruption):
    value = read_layout(tmp_path, payroll_items()).model_dump()
    if corruption == "word":
        value["words"][0]["text"] = "Invented"
    elif corruption == "reference":
        value["words"][0]["character_indexes"][0] = 99999
    elif corruption == "cell":
        value["tables"][0]["cells"][0]["text"] = "Wrong heading"
    elif corruption == "duplicate":
        value["tables"][0]["cells"][1]["column"] = 0
    elif corruption == "coverage":
        value["blocks"].clear()
    elif corruption == "column_swap":
        a, b = value["tables"][0]["cells"][4:6]
        a["column"], b["column"] = b["column"], a["column"]
    elif corruption == "row_swap":
        for cell in value["tables"][0]["cells"]:
            if cell["row"] in (1, 2):
                cell["row"] = 3-cell["row"]
    else:
        value["characters"][0]["bbox"] = (0, 0, 0, 0)
    with pytest.raises(ValueError):
        PDFLayout.model_validate(value)


def test_native_header_with_raster_body_requires_review(tmp_path):
    import pypdfium2 as pdfium

    source = tmp_path / "mixed.pdf"
    make_pdf(source, ["An embedded header with more than forty readable characters.\nThe body below is a scanned image."])
    with pdfium.PdfDocument(source) as pdf:
        page = pdf[0]
        raster = pdfium.PdfImage.new(pdf)
        with Image.new("RGB", (400, 300), "white") as pixels:
            raster.set_bitmap(pdfium.PdfBitmap.from_pil(pixels))
        raster.set_matrix(pdfium.PdfMatrix(400, 0, 0, 300, 50, 100))
        page.insert_obj(raster)
        page.gen_content()
        pdf.save(tmp_path / "mixed-body.pdf")
        page.close()
    worker(str(tmp_path / "mixed-body.pdf"), tmp_path)
    complete_pdf(tmp_path, config=None, digest=digest_file(tmp_path / "mixed-body.pdf"))
    result = read_result(json.loads((tmp_path / "result.json").read_text(encoding="utf-8")))
    assert result.pages[0].method == "embedded_text"
    assert result.pages[0].layout.coverage == "needs_review"
    assert "possible_image_content" in result.pages[0].layout.issues
    assert result.issues[0].code == "pdf_layout_review"


@pytest.mark.parametrize("limit", ["MAX_DOCUMENT_CHARACTERS", "PDF_EVIDENCE_BYTES", "PDF_PREVIEW_BYTES"])
def test_resource_limits_fail_without_publishing_a_truncated_manifest(tmp_path, monkeypatch, limit):
    from home_manager.documents import pdf_reader

    source = tmp_path / "limited.pdf"
    make_pdf(source, [{"items": payroll_items()}])
    monkeypatch.setattr(pdf_reader, limit, 10)
    with pytest.raises(ValueError, match="limit"):
        worker(str(source), tmp_path)
    assert not (tmp_path / "pages.json").exists()
    assert not (tmp_path / "result.json").exists()


def test_unicode_scalar_and_ligature_are_read_by_engine_index(tmp_path):
    source = tmp_path / "unicode.pdf"
    make_pdf(source, ["Native Unicode text including \x80 and ligature \x81 preserved in the source."],
             unicode_map={0x80: "\U0001f600", 0x81: "\ufb01"})
    worker(str(source), tmp_path)
    layout = PDFLayout.model_validate(json.loads((tmp_path / "pages.json").read_text(encoding="utf-8"))[0]["layout"])
    assert "\U0001f600" in [char.text for char in layout.characters]
    # PDFium expands the ligature into f/i engine entries; retain those exact
    # entries and their shared glyph box rather than zipping the flat string.
    assert "\U0001f600" in layout.reading_text and "fi" in layout.reading_text
    lead = next(char for char in layout.characters if char.text == "\U0001f600")
    assert layout.characters[lead.index+1].continuation_of == lead.index
    assert not any(char.unicode_error for char in layout.characters)
