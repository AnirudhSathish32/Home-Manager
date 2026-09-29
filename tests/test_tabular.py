"""Transaction import refusals and edge cases: every row is either imported exactly or reported, never guessed.
The main import paths are in test_imports.py."""

import zipfile

import pytest

from home_manager.finance import tabular
from home_manager.finance.tabular import (
    ImportMapping,
    MappingError,
    TableError,
    date_order,
    parse_date,
    parse_transactions,
    preview,
    read_table,
    spreadsheet_amount,
)
from test_imports import MAIN, make_xlsx


def test_a_file_that_is_not_utf8_is_read_as_windows_1252_and_says_so():
    data = "Date,Description,Amount\n2026-08-03,CAFÉ,-4.50\n".encode("cp1252")
    rows, _, issues, _ = parse_transactions(data, ".csv", "EUR")
    assert rows[0]["description"] == "CAFÉ"
    assert any("read as Windows-1252" in issue for issue in issues)


def test_rows_with_both_a_debit_and_a_credit_or_no_date_are_reported():
    data = "Date,Description,Debit,Credit\n2026-08-03,BOTH,1.00,2.00\n2026-02-30,NO SUCH DAY,1.00,\n2026-08-05,,1.00,\n2026-08-06,GOOD,3.00,\n"
    rows, _, issues, counts = parse_transactions(data.encode(), ".csv", "USD")
    assert [(row["description"], row["amount_minor"]) for row in rows] == [("GOOD", -300)]
    assert counts["rejected"] == 3
    assert "Row 2 was not imported: it has both a debit and a credit." in issues
    assert issues.count("Row 3 was not imported: it has no valid date or description.") == 1
    assert "Row 4 was not imported: it has no valid date or description." in issues


def test_a_chosen_mapping_overrides_detection():
    data = "Date,Description,Amount,Out,In\n2026-08-03,SHOP,999.00,12.00,\n"
    rows, used, _, _ = parse_transactions(data.encode(), ".csv", "USD", ImportMapping(debit="Out", credit="In"))
    assert rows[0]["amount_minor"] == -1200 and "amount" not in used
    with pytest.raises(MappingError, match="'Missing' is not in this file") as needs:
        parse_transactions(data.encode(), ".csv", "USD", ImportMapping(description="Missing"))
    assert needs.value.columns == ["Date", "Description", "Amount", "Out", "In"]


def test_import_limits_are_enforced(monkeypatch):
    with pytest.raises(TableError, match="32 MiB"):
        read_table(b"x" * (tabular.MAX_BYTES + 1), ".csv")
    with pytest.raises(TableError, match="cell exceeds"):
        parse_transactions(("Date,Description,Amount\n2026-08-03," + "A" * (tabular.MAX_CELL + 1) + ",1.00\n").encode(), ".csv", "USD")
    with pytest.raises(TableError, match="columns"):
        parse_transactions(("," * tabular.MAX_COLUMNS + "\n").encode(), ".csv", "USD")
    monkeypatch.setattr(tabular, "MAX_ROWS", 3)
    with pytest.raises(TableError, match="rows"):
        parse_transactions(("Date,Description,Amount\n" + "2026-08-03,A,1.00\n" * 4).encode(), ".csv", "USD")


def test_dates_are_read_only_in_the_chosen_or_proven_order():
    assert date_order(["2026-08-03", "2026-09-01"], "auto") == "YYYY-MM-DD"
    assert date_order(["13/08/2026"], "auto") == "DD/MM/YYYY" and date_order(["08/13/2026"], "auto") == "MM/DD/YYYY"
    assert date_order(["03/08/2026"], "MM/DD/YYYY") == "MM/DD/YYYY"
    assert parse_date("2026/8/3", "YYYY-MM-DD") == "2026-08-03"
    assert parse_date("03/08/2026", "YYYY-MM-DD") is None  # An ISO file never reads a slashed date by guessing.
    assert parse_date("2026-02-30", "YYYY-MM-DD") is None and parse_date("31/04/2026", "DD/MM/YYYY") is None
    assert parse_date("yesterday", "MM/DD/YYYY") is None


def test_spreadsheet_numbers_accept_binary_noise_but_not_real_fractions():
    assert spreadsheet_amount("-45.099999999999994", "USD") == -4510
    assert spreadsheet_amount("1E2", "USD") == 10000
    assert spreadsheet_amount("12", "JPY") == 12
    for value in ("-12.345", "0.001", "12.5", "abc"):
        currency = "JPY" if value == "12.5" else "USD"
        with pytest.raises(ValueError):
            spreadsheet_amount(value, currency)


def test_preview_totals_inflow_and_outflow_separately():
    rows = [{"posted_date": "2026-08-03", "description": "A", "amount_minor": amount, "currency": "USD", "locator": {}} for amount in (-450, 200000, -50)]
    shown = preview(rows, "USD", limit=2)
    assert len(shown["rows"]) == 2 and shown["rows"][0]["display_amount"] == "-4.50 USD"
    assert shown["totals"] == {"outflow": "-5.00 USD", "inflow": "2,000.00 USD"}


def workbook(path, sheet_xml, names=None):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", f'<workbook xmlns="{MAIN}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                                            '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                         '<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="worksheet"/></Relationships>')
        if sheet_xml is not None:
            archive.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{MAIN}"><sheetData>{sheet_xml}</sheetData></worksheet>')
        for name in names or []:
            archive.writestr(name, "")


def test_workbook_cells_of_every_kind(tmp_path):
    path = tmp_path / "export.xlsx"
    workbook(path, '<row r="1"><c r="A1" t="inlineStr"><is><t>Date</t></is></c><c r="B1" t="inlineStr"><is><t>Description</t></is></c>'
                   '<c r="C1" t="inlineStr"><is><t>Amount</t></is></c><c r="D1" t="inlineStr"><is><t>Flag</t></is></c></row>'
                   '<row r="2"><c r="A2" t="inlineStr"><is><t>2026-08-03</t></is></c><c r="B2" t="inlineStr"><is><t>SHOP</t></is></c>'
                   '<c r="C2"><v>-4.5</v></c><c r="D2" t="b"><v>1</v></c></row>'
                   '<row r="3"><c r="A3" t="inlineStr"><is><t>2026-08-04</t></is></c><c r="B3" t="inlineStr"><is><t>BROKEN</t></is></c>'
                   '<c r="C3" t="e"><v>#DIV/0!</v></c></row>')
    rows, _, issues, counts = parse_transactions(path.read_bytes(), ".xlsx", "USD")
    assert [(row["description"], row["amount_minor"]) for row in rows] == [("SHOP", -450)]
    assert counts["rejected"] == 1
    assert "Cell C3 contains a spreadsheet error value." in issues


def test_workbooks_with_missing_parts_or_sheets_are_refused(tmp_path):
    path = tmp_path / "export.xlsx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("docProps/app.xml", "")
    with pytest.raises(TableError, match="structure is not supported"):
        parse_transactions(path.read_bytes(), ".xlsx", "USD")
    workbook(path, None)
    with pytest.raises(TableError, match="worksheet part is missing"):
        parse_transactions(path.read_bytes(), ".xlsx", "USD")
    make_xlsx(path, [[("s", "Date"), ("s", "Description"), ("s", "Amount")]])
    with pytest.raises(TableError, match="requested worksheet was not found"):
        parse_transactions(path.read_bytes(), ".xlsx", "USD", sheet="Other")


def test_workbooks_wider_than_the_limit_are_refused(tmp_path):
    path = tmp_path / "export.xlsx"
    workbook(path, '<row r="1"><c r="ZZ1"><v>1</v></c></row>')
    with pytest.raises(TableError, match="exceeds 60 columns"):
        parse_transactions(path.read_bytes(), ".xlsx", "USD")
