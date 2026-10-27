"""Independent text placements exercise native geometry without literal separators."""

import json
import random

from PIL import Image
import pytest

from home_manager.documents.layout_context import native_page, project_page
from home_manager.documents.pdf_layout import PDFLayout, point, visual_box
from home_manager.documents.pdf_reader import complete_pdf, read_result, worker
from home_manager.library.storage import digest_file
from test_pdf import make_pdf


def read_layout(tmp_path, items, type3_scale=None, **settings):
    source = tmp_path / "positioned.pdf"
    make_pdf(source, [{"items": items, **settings}], type3_scale=type3_scale)
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


STATEMENT_ROWS = [("08/25/2026", "REFUND BOOKSTORE", "", "19.99", "2,460.89"),
                  ("08/28/2026", "UTILITY CO", "82.40", "", "2,378.49"),
                  ("08/30/2026", "INTEREST PAID", "", "0.12", "2,378.61")]
STATEMENT_FOOTER = "FIRST LOCAL BANK statement page three of three, kept for your records"


def statement_items(rows, top=700):
    return [(x, top - 20 * row, text) for row, cells in enumerate(rows)
            for x, text in zip((40, 110, 300, 390, 480), cells) if text]


@pytest.mark.parametrize("rows", [
    STATEMENT_ROWS,  # A continued page: no heading, so no table.
    [("Date", "Description", "Withdrawals", "Deposits", "Balance"), *[(*row[:3], "", row[4]) for row in STATEMENT_ROWS]],  # No deposits on the page.
])
def test_a_statement_page_without_a_table_keeps_each_amount_on_its_row(tmp_path, rows):
    """A statement's amount columns are part of their rows even when no table is found: splitting at the gutter listed
    19.99 and 0.12 after the rows, and a model then paired them with the wrong rows (docs/documents.md "PDFs")."""
    layout = read_layout(tmp_path, [*statement_items(rows), (40, 700 - 20 * len(rows), STATEMENT_FOOTER)])
    assert not layout.tables and layout.issues == ["unresolved_columns"]
    assert layout.reading_text.splitlines() == [" ".join(cell for cell in row if cell) for row in rows] + [STATEMENT_FOOTER]


def test_an_amount_column_with_rows_of_its_own_is_still_read_apart(tmp_path):
    """Amounts printed where the left side has no row (a totals box beside a note) are a column of their own."""
    items = [(40, 700, "Thank you for banking with us"), (40, 680, "Questions? Call the branch"),
             (400, 700, "1,000.00"), (400, 680, "2,378.61"), (400, 660, "1,378.61")]
    layout = read_layout(tmp_path, items)
    assert layout.reading_text.splitlines() == ["Thank you for banking with us", "Questions? Call the branch", "1,000.00", "2,378.61", "1,378.61"]


def test_title_and_footer_do_not_become_table_rows(tmp_path):
    layout = read_layout(tmp_path, [(40, 720, "Payroll statement - October"), *payroll_items(), (40, 620, "Keep this for your records")])
    assert len(layout.tables) == 1
    assert layout.blocks[0].kind != "table" and layout.blocks[-1].kind != "table"
    assert grid(layout)[0] == ["Description", "YTD", "Current"]


def tight_payroll_items():
    """A payroll site's packed columns: right-aligned amounts and headings less than 1.5 font sizes apart."""
    def right(x, y, text):
        return (round(x - len(text) * 5.0, 1), y, text)
    items = [(40, 700, "Earnings"), (170, 700, "rate"), (230, 700, "hours"), (300, 700, "this period"), (358, 700, "year to date")]
    for row, (label, rate, hours, current, ytd) in enumerate([("Regular", "50.0000", "80.00", "4,000.00", "52,000.00"),
                                                              ("Relocation Bonus", "", "", "", "4,000.00"),
                                                              ("Gross Pay", "", "", "$4,000.00", "56,000.00")], 1):
        items.append((40, 700 - 14 * row, label))
        items += [right(x, 700 - 14 * row, value) for x, value in ((205, rate), (260, hours), (350, current), (400, ytd)) if value]
    return items


def test_packed_amount_columns_and_run_together_headings_stay_separate_columns(tmp_path):
    """Two amounts side by side are never one cell, and a heading that runs into the next is split where the amounts
    below it split (docs/documents.md "Native PDF layout")."""
    layout = read_layout(tmp_path, tight_payroll_items())
    assert grid(layout) == [["Earnings", "rate", "hours", "this period", "year to date"],
                            ["Regular", "50.0000", "80.00", "4,000.00", "52,000.00"],
                            ["Relocation Bonus", "", "", "", "4,000.00"],
                            ["Gross Pay", "", "", "$4,000.00", "56,000.00"]]


def payslip_items(pad=6):
    """A payslip's Earnings and Deductions side by side on the same rows, cells padded by pad points, labels wider than
    their headings, and the totals row after a blank stretch at the foot of both, as in ruled payslip templates."""
    def right(x, y, text):
        return (round(x - len(text) * 5.0, 1), y, text)
    second = 290 + pad
    items = [(40, 700, "Earnings"), (155, 700, "Current"), (262, 700, "YTD"), (second, 700, "Deductions"), (second + 115, 700, "Current"),
             (second + 222, 700, "YTD")]
    earnings = [("Regular Salary", "4,000.00", "52,000.00"), ("Relocation Bonus", "", "4,000.00"), ("Overtime", "300.00", "1,200.00")]
    deductions = [("Federal Income Tax", "500.00", "6,500.00"), ("Social Security", "248.00", "3,224.00"), ("Medicare", "58.00", "754.00"),
                  ("401K", "200.00", "2,600.00"), ("Dental", "12.00", "156.00")]
    rows = [(earnings[r] if r < len(earnings) else ("", "", ""), deductions[r], 700 - 16 * (r + 1)) for r in range(len(deductions))]
    rows.append((("Gross Pay", "4,300.00", "57,200.00"), ("Total Deductions", "1,018.00", "13,234.00"), 700 - 16 * (len(deductions) + 2)))
    for left, other, y in rows:
        for (label, current, ytd), (x, current_right, ytd_right) in ((left, (40, 200, 290)), (other, (second, second + 160, second + 250))):
            if label:
                items += [(x, y, label), *[right(edge, y, value) for edge, value in ((current_right, current), (ytd_right, ytd)) if value]]
    return items


@pytest.mark.parametrize("pad", [6, 20, 40])
def test_side_by_side_payslip_tables_are_read_as_two_tables_with_their_totals(tmp_path, pad):
    """Labels wider than their headings, an amount padded close to the next table's label, two tables sharing rows and
    a totals row after a blank stretch: two tables, each with its own Current and YTD (docs/documents.md "PDFs")."""
    layout = read_layout(tmp_path, payslip_items(pad))
    assert len(layout.tables) == 2
    assert grid(layout, 0) == [["Earnings", "Current", "YTD"], ["Regular Salary", "4,000.00", "52,000.00"], ["Relocation Bonus", "", "4,000.00"],
                               ["Overtime", "300.00", "1,200.00"], ["Gross Pay", "4,300.00", "57,200.00"]]
    assert grid(layout, 1) == [["Deductions", "Current", "YTD"], ["Federal Income Tax", "500.00", "6,500.00"], ["Social Security", "248.00", "3,224.00"],
                               ["Medicare", "58.00", "754.00"], ["401K", "200.00", "2,600.00"], ["Dental", "12.00", "156.00"],
                               ["Total Deductions", "1,018.00", "13,234.00"]]


def sectioned_payslip_items():
    """A ruled payslip template: a details box right above one heading row for Earnings and Deductions side by side,
    Statutory and Voluntary section labels (the second after a blank row), and the totals at the foot of a mostly
    empty box. Amounts are invented; one is printed without cents."""
    def right(x, y, text):
        return (round(x - len(text) * 5.0, 1), y, text)
    items = [(30, 660, "Pay Date"), (130, 660, "10/09/2026"), (276, 660, "Federal Allowances"),
             (30, 645, "Period Beginning"), (130, 645, "09/19/2026"), (276, 645, "Federal Additional Withholding"),
             (30, 630, "Period Ending"), (130, 630, "10/02/2026"), (276, 630, "Federal Standard Withholding Table"),
             (30, 615, "Earnings"), (142, 615, "Rate"), (175, 615, "Hours"), (212, 615, "This Period"), (276, 615, "Year To Date"),
             (340, 615, "Deductions"), (463, 615, "This Period"), (520, 615, "Year To Date")]
    earnings = {600: ("Regular Salary", ["50.00", "80", "4,000.00", "84,000.00"]), 585: ("Relocation Bonus", ["", "", "", "4,000"])}
    deductions = {600: ("Statutory", []), 585: ("Federal Tax", ["500.00", "10,500.00"]), 570: ("Social Security Tax", ["248.00", "5,208.00"]),
                  555: ("Medicare Tax", ["58.00", "1,218.00"]), 540: ("GA State Tax", ["190.00", "3,990.00"]), 510: ("Voluntary", []),
                  495: ("Medical HDP", ["90.00", "1,890.00"]), 480: ("Vision Insurance", ["6.00", "6.00"]), 465: ("Dental PPO", ["12.00", "252.00"]),
                  450: ("HSA Additional", ["50.00", "1,050.00"]), 435: ("401K Plan", ["200.00", "4,200.00"])}
    for y, (label, values) in earnings.items():
        items += [(30, y, label), *[right(edge, y, value) for edge, value in zip((170, 203, 268, 334), values) if value]]
    for y, (label, values) in deductions.items():
        items += [(340, y, label), *[right(edge, y, value) for edge, value in zip((516, 578), values)]]
    items += [(30, 120, "Total Earnings (A)"), right(268, 120, "4,000.00"), right(334, 120, "88,000.00"),
              (340, 120, "Total Deductions (B)"), right(516, 120, "1,354.00"), right(578, 120, "28,434.00"),
              (30, 105, "Net Payment (A-B)"), right(268, 105, "2,646.00"), right(334, 105, "59,566.00")]
    return items


def test_sectioned_payslip_keeps_section_labels_blank_rows_and_foot_totals_in_its_tables(tmp_path):
    """Statutory and Voluntary label rows, a blank row before Voluntary and the totals at the foot of the box stay in
    their tables; the details box above isn't part of them (docs/documents.md "PDFs")."""
    layout = read_layout(tmp_path, sectioned_payslip_items())
    assert len(layout.tables) == 2
    assert grid(layout, 0) == [["Earnings", "Rate", "Hours", "This Period", "Year To Date"],
                               ["Regular Salary", "50.00", "80", "4,000.00", "84,000.00"], ["Relocation Bonus", "", "", "", "4,000"],
                               ["Total Earnings (A)", "", "", "4,000.00", "88,000.00"], ["Net Payment (A-B)", "", "", "2,646.00", "59,566.00"]]
    assert grid(layout, 1) == [["Deductions", "This Period", "Year To Date"], ["Statutory", "", ""], ["Federal Tax", "500.00", "10,500.00"],
                               ["Social Security Tax", "248.00", "5,208.00"], ["Medicare Tax", "58.00", "1,218.00"], ["GA State Tax", "190.00", "3,990.00"],
                               ["Voluntary", "", ""], ["Medical HDP", "90.00", "1,890.00"], ["Vision Insurance", "6.00", "6.00"],
                               ["Dental PPO", "12.00", "252.00"], ["HSA Additional", "50.00", "1,050.00"], ["401K Plan", "200.00", "4,200.00"],
                               ["Total Deductions (B)", "1,354.00", "28,434.00"]]


def test_a_one_row_table_with_two_amount_columns_is_a_table(tmp_path):
    """Other Benefit And Information | This Period | Year to Date over one Co Match 401K row is still a table."""
    layout = read_layout(tmp_path, [(60, 400, "Other Benefit And Information"), (250, 400, "This Period"), (320, 400, "Year to Date"),
                                    (60, 385, "Co Match 401K"), (265, 385, "160.00"), (330, 385, "3,360.00")])
    assert grid(layout) == [["Other Benefit And Information", "This Period", "Year to Date"], ["Co Match 401K", "160.00", "3,360.00"]]


def test_a_run_together_heading_splits_at_its_widest_gap_between_the_columns_below(tmp_path):
    """"This Period" and "Year to Date" run together over two narrow amount columns, and "Year" sits over neither
    column's amounts: the heading splits at the widest gap between the words over each column, not by distance."""
    layout = read_layout(tmp_path, [(60, 400, "Other Benefit And Information"), (250, 400, "This Period"), (304, 400, "Year to Date"),
                                    (60, 385, "Co Match 401K"), (270, 385, "160.00"), (339, 385, "336.00")])
    assert grid(layout) == [["Other Benefit And Information", "This Period", "Year to Date"], ["Co Match 401K", "160.00", "336.00"]]


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


SCALED = 10 / 0.24  # A bank's statement sets its font at 0.24 pt and draws it about 10 pt tall.
SCALED_ROWS = [("Date", "Description", "Amount", "Balance"), ("09/18", "SYNTH ACCTVERIFY", "0.36", "0.36"),
               ("09/18", "SYNTH ACCTVERIFY", "0.02", "0.38"), ("09/18", "SYNTH ACCTVERIFY", "-0.38", "0.00")]
SCALED_FOOTER = "Synthetic savings statement page one of one, kept for your records"


def scaled_items(margin=(600, 300), matrix=(SCALED, 0, 0, SCALED)):
    """SCALED_ROWS at 0.24 pt, scaled up by the text `matrix` (or by a Type 3 font when it is the identity), and a reference
    number printed up the page at `margin` (the right margin by default), drawn the same way."""
    turned = (0, matrix[0], -matrix[3], 0)
    items = [(x, 700 - 20 * row, text, 0.24, matrix) for row, cells in enumerate(SCALED_ROWS)
             for x, text in zip((40, 110, 380, 470), cells)]
    items.append((40, 600, SCALED_FOOTER, 0.24, matrix))
    items.append((*margin, "10000000000123456789", 0.24, turned))
    return items


SCALINGS = {  # How the PDF scales 0.24 pt text up, the read settings, and the size each glyph is then measured at.
    "text matrix": ({}, {}, 10.0),
    # The user's statement: PDFium reports 0.24 pt and a matrix scale of 1; the font's loose box (1 em here) shows the size.
    "Type 3 font": ({"matrix": (1, 0, 0, 1)}, {"type3_scale": SCALED}, 10.0),
}


@pytest.mark.parametrize("scaling", SCALINGS)
def test_scaled_text_is_measured_at_its_drawn_size_and_a_turned_margin_number_leaves_the_table(tmp_path, scaling):
    """The user's bank statement: PDFium reported 0.24 pt for most glyphs, so every gap counted as a word break, kerning
    counted as overlapping text, and a vertical number in the margin refused every table on the page."""
    items, settings, size = SCALINGS[scaling]
    layout = read_layout(tmp_path, scaled_items(**items), **settings)
    assert {round(char.font_size, 1) for char in layout.characters if char.bbox} == {size}
    assert layout.issues == ["unsupported_text_rotation"] and layout.coverage == "needs_review"
    assert len(layout.tables) == 1 and grid(layout) == [list(row) for row in SCALED_ROWS]
    # The number is one line of its own, after the page's other text, and needs review.
    assert layout.lines[-1].text == "10000000000123456789"
    assert layout.blocks[-1].kind == "paragraph" and layout.blocks[-1].status == "needs_review"
    complete_pdf(tmp_path, config=None, digest=digest_file(tmp_path / "positioned.pdf"))
    page = read_result(json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))).pages[0]
    assert native_page(page) and project_page(page)[1][0].page == 1  # The viewer's Tables tab and the model get the table.


def test_turned_text_across_a_table_still_refuses_it(tmp_path):
    layout = read_layout(tmp_path, scaled_items(margin=(420, 610)))
    assert "unsupported_text_rotation" in layout.issues and not layout.tables


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
