"""Phase 6: deterministic CSV/XLSX transaction import with explicit mapping and de-duplication."""

from conftest import inbox_scan
from datetime import date
import zipfile

from fastapi.testclient import TestClient
import pytest

from home_manager.api import create_app
from home_manager.scanner import Scanner, ScanLimits
from home_manager.storage import Store
from home_manager.finance import Ledger
from home_manager.tabular import ImportMapping, MappingError, TableError, parse_transactions

EXPORT = """Account: FIRST LOCAL BANK CHECKING ****4821
Export date: 09/24/2026

Posted Date,Description,Amount,Balance
08/03/2026,COFFEE SHOP,-4.50,995.50
08/03/2026,COFFEE SHOP,-4.50,991.00
08/15/2026,PAYROLL ACME,"2,000.00",2991.00
08/20/2026,ONLINE TRANSFER TO SAVINGS,(500.00),2491.00
08/21/2026,MONTHLY SERVICE FEE,$-5.00,2486.00
08/22/2026,BAD ROW,12.345,2486.00
,,,
"""
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def make_xlsx(path, rows, doctype=False):
    """rows: lists of ("s", text) | ("n", number text) | ("d", date) | ("f", formula, cached or None)."""
    strings, sheet = [], []
    for number, row in enumerate(rows, 1):
        cells = []
        for column, cell in enumerate(row):
            ref = f"{chr(65 + column)}{number}"
            if cell[0] == "s":
                strings.append(cell[1])
                cells.append(f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>')
            elif cell[0] == "d":
                cells.append(f'<c r="{ref}" s="1"><v>{(cell[1] - date(1899, 12, 30)).days}</v></c>')
            elif cell[0] == "f":
                cells.append(f'<c r="{ref}"><f>{cell[1]}</f>' + (f"<v>{cell[2]}</v>" if cell[2] is not None else "") + "</c>")
            else:
                cells.append(f'<c r="{ref}"><v>{cell[1]}</v></c>')
        sheet.append(f'<row r="{number}">{"".join(cells)}</row>')
    prolog = '<!DOCTYPE x [<!ENTITY a "aaaa">]>' if doctype else ""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", f'{prolog}<workbook xmlns="{MAIN}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                                            '<sheets><sheet name="Transactions" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                         '<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="worksheet"/></Relationships>')
        archive.writestr("xl/styles.xml", f'<styleSheet xmlns="{MAIN}"><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>')
        archive.writestr("xl/sharedStrings.xml", f'<sst xmlns="{MAIN}">' + "".join(f"<si><t>{text}</t></si>" for text in strings) + "</sst>")
        archive.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{MAIN}"><sheetData>{"".join(sheet)}</sheetData></worksheet>')


def test_csv_export_with_preamble_signs_and_explicit_rejections():
    rows, mapping, issues, counts = parse_transactions(EXPORT.encode(), ".csv", "USD")
    assert mapping == {"date": "Posted Date", "description": "Description", "amount": "Amount", "date_format": "MM/DD/YYYY", "sign": "negative_is_outflow"}
    assert [(row["posted_date"], row["amount_minor"]) for row in rows] == [
        ("2026-08-03", -450), ("2026-08-03", -450), ("2026-08-15", 200000), ("2026-08-20", -50000), ("2026-08-21", -500)]
    assert counts == {"parsed": 5, "rejected": 1, "blank": 1, "columns": ["Posted Date", "Description", "Amount", "Balance"]}
    assert "Row 10 was not imported: Amount has more precision than USD allows." in issues and "1 blank rows were skipped." in issues
    assert rows[0]["locator"] == {"rows": [5]}


def test_debit_credit_columns_and_date_order_are_never_guessed():
    debit_credit = "Date,Details,Money out,Money in\n03/08/2026,GROCERY,45.10,\n25/08/2026,REFUND,,5.00\n"
    rows, mapping, _, _ = parse_transactions(debit_credit.encode(), ".csv", "EUR")
    assert mapping["date_format"] == "DD/MM/YYYY" and [row["amount_minor"] for row in rows] == [-4510, 500]
    assert rows[0]["posted_date"] == "2026-08-03"
    ambiguous = "Date,Description,Amount\n03/08/2026,A,1.00\n04/09/2026,B,2.00\n"
    with pytest.raises(TableError, match="ambiguous"):
        parse_transactions(ambiguous.encode(), ".csv", "USD")
    rows, *_ = parse_transactions(ambiguous.encode(), ".csv", "USD", ImportMapping(date_format="DD/MM/YYYY"))
    assert [row["posted_date"] for row in rows] == ["2026-08-03", "2026-09-04"]
    card = "Transaction Date,Description,Amount\n2026-08-03,BOOKSTORE,19.99\n"
    rows, *_ = parse_transactions(card.encode(), ".csv", "USD", ImportMapping(sign="positive_is_outflow"))
    assert rows[0]["amount_minor"] == -1999
    foreign = "Date,Description,Amount,Currency\n2026-08-03,HOTEL,100.00,EUR\n"
    rows, _, issues, counts = parse_transactions(foreign.encode(), ".csv", "USD")
    assert not rows and counts["rejected"] == 1 and "currency differs" in issues[0]
    with pytest.raises(MappingError, match="description column") as needs_choice:
        parse_transactions(b"date,amount\n2026-09-01,1.00\n", ".csv", "USD")
    assert needs_choice.value.columns == ["date", "amount"] and needs_choice.value.mapping == {"date": "date", "amount": "amount"}
    with pytest.raises(TableError, match="header row"):
        parse_transactions(b"just,some,text\n1,2,3\n", ".csv", "USD")
    with pytest.raises(ValueError, match="not both"):
        ImportMapping(amount="Amount", debit="Debit")


def test_xlsx_reads_cached_values_dates_and_binary_noise_without_evaluating_formulas(tmp_path):
    path = tmp_path / "export.xlsx"
    make_xlsx(path, [
        [("s", "Date"), ("s", "Description"), ("s", "Amount")],
        [("d", date(2026, 8, 3)), ("s", "COFFEE"), ("n", "-4.5")],
        [("d", date(2026, 8, 4)), ("s", "PAYROLL"), ("n", "2000")],
        [("d", date(2026, 8, 5)), ("s", "GROCERY"), ("f", "B2*10", "-45.099999999999994")],
        [("d", date(2026, 8, 6)), ("s", "BOOKS"), ("f", "B3*2", None)],
        [("d", date(2026, 8, 7)), ("s", "ODD"), ("n", "-12.345")],
    ])
    rows, mapping, issues, counts = parse_transactions(path.read_bytes(), ".xlsx", "USD")
    assert [(row["posted_date"], row["description"], row["amount_minor"]) for row in rows] == [
        ("2026-08-03", "COFFEE", -450), ("2026-08-04", "PAYROLL", 200000), ("2026-08-05", "GROCERY", -4510)]
    assert counts["rejected"] == 2
    assert any("C5 has a formula without a saved value" in issue for issue in issues)
    assert any("formula cells were read from their saved values" in issue for issue in issues)
    make_xlsx(path, [[("s", "Date"), ("s", "Amount")]], doctype=True)
    with pytest.raises(TableError, match="XML declarations"):
        parse_transactions(path.read_bytes(), ".xlsx", "USD")
    path.write_bytes(b"PK not a workbook")
    with pytest.raises(TableError, match="not a valid XLSX"):
        parse_transactions(path.read_bytes(), ".xlsx", "USD")


def test_import_api_is_idempotent_and_statement_rows_do_not_double_count(tmp_path):
    app = create_app(tmp_path / "control", "import-token", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.get("/api/finance/accounts").status_code == 401
        client.headers.update({"Authorization": "Bearer import-token"})
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        month = app.state.manager.store.library.inbox
        (month / "checking.csv").write_text(EXPORT)
        app.state.manager.start_inbox()
        app.state.manager.future.result(timeout=30)
        doc = client.get("/api/documents").json()["items"][0]
        preview = client.post(f"/api/documents/{doc['id']}/transaction-import/preview", json={"expected_hash": doc["current_hash"], "currency": "USD"}).json()
        assert preview["counts"]["parsed"] == 5 and preview["totals"] == {"outflow": "-514.00 USD", "inflow": "2,000.00 USD"}
        assert preview["rows"][0]["display_amount"] == "-4.50 USD"
        assert client.post("/api/finance/accounts", json={"institution": "First Local Bank", "account_type": "checking", "currency": "USD", "last_four": "123456"}).status_code == 422
        account = client.post("/api/finance/accounts", json={"institution": "First Local Bank", "account_type": "checking", "currency": "USD", "last_four": "4821"}).json()
        body = {"expected_hash": doc["current_hash"], "account_id": account["id"]}
        assert client.post(f"/api/documents/{doc['id']}/transaction-imports", json={"expected_hash": doc["current_hash"]}).status_code == 400
        first = client.post(f"/api/documents/{doc['id']}/transaction-imports", json=body).json()
        assert (first["inserted"], first["duplicates"], first["rejected"]) == (5, 0, 1)
        again = client.post(f"/api/documents/{doc['id']}/transaction-imports", json=body).json()
        assert (again["inserted"], again["duplicates"]) == (0, 5)
        manager = app.state.manager
        with manager.store.connection() as db:
            kinds = [row[0] for row in db.execute("SELECT transaction_type FROM transactions ORDER BY posted_date, id")]
        assert kinds == ["purchase", "purchase", "deposit", "transfer", "fee"]
        # A statement covering the same period re-describes the same rows: recognised, not added.
        statement = {"statement_type": "bank", "institution": "First Local Bank", "last_four": "4821", "currency": "USD",
                     "period_start": "2026-08-01", "period_end": "2026-08-31", "opening_balance_minor": 100000, "closing_balance_minor": 248600,
                     "summary": {}, "issues": [], "locator": {"line_ids": ["page-1-line-1"]},
                     "transactions": [{"posted_date": "2026-08-03", "description": "COFFEE SHOP #12", "amount_minor": -450, "currency": "USD", "locator": {"line_ids": ["page-1-line-4"]}},
                                      {"posted_date": "2026-08-15", "description": "ACME PAYROLL DIRECT DEP", "amount_minor": 200000, "currency": "USD", "locator": {"line_ids": ["page-1-line-5"]}}]}
        published = manager.ledger.publish_statement(statement, {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": "extraction:test", "run_id": "test"}, "proposed")
        assert (published["inserted"], published["duplicates"]) == (0, 2)
        with manager.store.connection() as db:
            assert db.execute("SELECT count(*) FROM transactions").fetchone()[0] == 5
        assert client.get("/api/finance/accounts").json()[0]["account_last_four"] == "4821"


def test_imports_read_preserved_bytes_not_the_inbox_file(tmp_path):
    store = Store(tmp_path / "managed")
    path = store.library.inbox / "export.csv"
    path.write_text(EXPORT)
    try:
        inbox_scan(store)
        doc = store.documents()["items"][0]
        path.write_text("Date,Description,Amount\n2026-08-01,CHANGED AFTER CAPTURE,-999.00\n")
        ledger = Ledger(store)
        account = ledger.create_account("First Local Bank", "checking", "USD")
        assert ledger.import_transactions(doc["id"], account["id"])["inserted"] == 5
        store.blob_path(doc["current_hash"]).write_bytes(b"corrupt")
        with pytest.raises(ValueError, match="integrity"):
            ledger.import_transactions(doc["id"], account["id"])
    finally:
        store.close()
