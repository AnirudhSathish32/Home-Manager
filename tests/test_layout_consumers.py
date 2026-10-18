"""Native PDF evidence must reach consumers, not merely survive serialization."""

import json
import random
from types import SimpleNamespace

from home_manager.core.jobs import Work
from home_manager.documents.extraction import (
    EXTRACTION_VERSION,
    HEADER_MODELS,
    HEADERS,
    BillLine,
    ExtractionService,
    InvestmentLine,
    PayLine,
    Transaction,
    paystub_chunks,
    paystub_columns,
    paystub_table_context,
)
from home_manager.documents.layout_context import citation_lines, evidence_lines, evidence_tables, viewer_context
from home_manager.documents.native_values import anchor_rows, anchor_summary
from home_manager.documents.pdf_reader import complete_pdf, read_result
from home_manager.documents.reasoning import ReasoningConfig
from home_manager.documents.receipt_service import ReceiptService
from home_manager.finance.ledger import Ledger
from home_manager.library.storage import digest_file
from home_manager.library.text_index import document_lines, index_run, search
from test_extraction import MISSING
from test_pdf import capture, make_pdf, pdf_store  # noqa: F401
from test_pdf_layout import payroll_items, read_layout


def native_result(tmp_path, items):
    layout = read_layout(tmp_path, items)
    complete_pdf(tmp_path, None, digest_file(tmp_path / "positioned.pdf"))
    result = read_result(json.loads((tmp_path / "result.json").read_text(encoding="utf-8")))
    assert result.pages[0].layout == layout
    return result


def test_projection_preserves_rows_blanks_and_historical_ids(tmp_path):
    items = payroll_items()
    random.Random(42).shuffle(items)
    result = native_result(tmp_path, items)
    lines, tables = evidence_lines(result), evidence_tables(result)
    assert [line.text for line in lines] == ["Description | YTD | Current", "Regular pay | 52000.00 | 2000.00",
                                           "Bonus | 500.00 | ", "Adjustment | -10.00 | 0.00"]
    assert not {line.id for line in lines} & {line.id for line in result.lines}
    assert {line.id for line in result.lines} <= {line.id for line in citation_lines(result)}
    assert tables[0].rows[0].cells[2].word_ids
    assert viewer_context(result)["tables"][0]["source"] == "pdf_text"


def test_side_by_side_current_only_rows_keep_separate_identity(tmp_path):
    items = [(x+offset, y, text) for offset in (0, 300) for x, y, text in
             [(40, 700, "Description"), (180, 700, "Amount"), (40, 680, "Salary"), (180, 680, "2000.00"),
              (40, 660, "Bonus"), (180, 660, "500.00")]]
    tables = evidence_tables(native_result(tmp_path, items))
    assert len(tables) == 2
    assert tables[0].rows[0].line_id != tables[1].rows[0].line_id
    assert paystub_columns(tables[0]) == (1, None)


def test_native_invoice_and_statement_copy_amount_not_unit_price_or_balance(tmp_path):
    result = native_result(tmp_path, [(40+c*130, 700-r*20, value) for r, row in enumerate([
        ["Item", "Qty", "Unit price", "Total"], ["Widgets", "2", "12.50", "25.00"], ["Delivery", "1", "5.00", "5.00"]])
                                     for c, value in enumerate(row)])
    row = evidence_tables(result)[0].rows[0]
    item = BillLine(description="Widgets", amount="12.50", quantity="25", unit_price="2", category=None,
                    line_kind="other", line_holder=None, evidence=[{"line_id": row.line_id, "quote": "Widgets"}])
    notes = []
    rows, refs = anchor_rows("bill", [item], evidence_tables(result), notes)
    assert (rows[0].amount, rows[0].quantity, rows[0].unit_price) == ("25.00", "2", "12.50")
    assert refs[0]["amount"]["cell_id"] == row.cells[3].id and not notes
    other = tmp_path / "bank"; other.mkdir()
    result = native_result(other, [(40+c*130, 700-r*20, value) for r, row in enumerate([
        ["Description", "Debit", "Credit", "Balance"], ["Shop", "45.00", "", "955.00"], ["Deposit", "", "100.00", "1055.00"]])
                                  for c, value in enumerate(row) if value])
    table = evidence_tables(result)[0]
    transactions = [Transaction(posted_date=None, transaction_date=None, description=row.cells[0].quote,
                                amount=row.cells[3].quote, direction="credit", evidence=[{"line_id": row.line_id, "quote": row.cells[0].quote}])
                    for row in table.rows]
    rows, refs = anchor_rows("bank_statement", transactions, [table], [])
    assert [(row.amount, row.direction) for row in rows] == [("45.00", "debit"), ("100.00", "credit")]
    assert refs[0]["amount"]["word_ids"] == table.rows[0].cells[1].word_ids


def test_mixed_chunks_never_use_classification_only_for_uncovered_lines(tmp_path):
    result = native_result(tmp_path, [(40, 740, "Health deduction 25.00"), *payroll_items()])
    tables, lines = evidence_tables(result), evidence_lines(result)
    covered = {row.line_id for table in tables for row in table.rows}
    chunks = list(paystub_chunks(lines, tables, split_covered=True))
    assert [line.id for chunk in chunks for line in chunk] == [line.id for line in lines]
    for chunk in chunks:
        context = paystub_table_context(tables, chunk)
        assert not context or all(line.id in covered for line in chunk)
    assert any("Health deduction" in line.text for chunk in chunks if not paystub_table_context(tables, chunk) for line in chunk)


def test_native_paystub_reaches_ledger_search_and_source_cells(pdf_store, local_model):
    inbox, store = pdf_store
    items = [(40, 760, "EXAMPLE WIDGETS LLC"), (40, 740, "Pay date 2026-09-20"), (40, 720, "Currency USD"),
             (40, 700, "Description"), (230, 700, "YTD"), (380, 700, "Current")]
    body = [["Regular pay", "52000.00", "2000.00"], ["Federal tax", "5200.00", "200.00"],
            ["Gross pay", "52000.00", "2000.00"], ["Net pay", "46800.00", "1800.00"]]
    items.extend((x, 680-r*20, text) for r, row in enumerate(body) for x, text in zip((40, 230, 380), row))
    random.Random(17).shuffle(items)
    make_pdf(inbox / "native-stub.pdf", [{"items": items}])
    doc = capture(inbox, store)
    service = ReceiptService(store)
    parse_id, _ = service.enqueue(doc["id"], vision=local_model["config"])
    service.run(parse_id, Work.detached())
    parsed = service.get(parse_id)
    assert parsed["status"] == "succeeded", parsed["error"]
    assert not local_model["requests"]
    result = read_result(parsed["result"])
    lines = evidence_lines(result)
    def cite(text):
        line = next(line for line in lines if text in line.text)
        return [{"line_id": line.id, "quote": line.text}]
    def value(text, line):
        return {"value": text, "status": "proposed", "evidence": cite(line)}
    summary = {name: MISSING for name in HEADERS["paystub"]}
    summary.update(payer_or_employer=value("EXAMPLE WIDGETS LLC", "EXAMPLE"), pay_date=value("2026-09-20", "Pay date"),
                   currency=value("USD", "Currency"), gross_pay=value("52000.00", "Gross pay"),
                   net_pay=value("46800.00", "Net pay"), gross_pay_ytd=value("2000.00", "Gross pay"),
                   net_pay_ytd=value("1800.00", "Net pay"))
    local_model["outputs"] = [{"document_type": "paystub", "evidence": cite("Regular pay"),
                               "issuer": summary["payer_or_employer"], "document_date": summary["pay_date"]}, summary,
                              {"lines": []}, {"lines": [
                                  {"description": "Regular pay", "group": "earnings", "category": "regular_pay", "evidence": cite("Regular pay")},
                                  {"description": "Federal tax", "group": "tax", "category": "federal_income_tax", "evidence": cite("Federal tax")}]}]
    extraction = ExtractionService(store, service)
    config = ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning")
    run_id, _ = extraction.enqueue(doc["id"], parse_id, config)
    extraction.run(run_id, Work.detached())
    run = extraction.get(run_id)
    assert run["status"] == "succeeded", run["error"]
    assert run["prompt_version"] == EXTRACTION_VERSION
    record = Ledger(store).record("income_record", run["publication"]["id"])
    assert record["gross_pay_minor"] == 200000 and record["net_pay_minor"] == 180000
    assert record["lines"][0]["cell_evidence"]["current"]["source"] == "pdf_text"
    from home_manager.finance.provenance import provenance_for
    with store.connection() as db:
        provenance = provenance_for(db, "income_record", record["id"], "net_pay")
    assert provenance["provenance"]["document"]["cells"][0]["quote"] == "1800.00"
    for request in (local_model["requests"][0], local_model["requests"][1], local_model["requests"][-1]):
        assert json.loads(request["messages"][1]["content"])["reported_tables"][0]["source"] == "pdf_text"
    with store.connection() as db:
        index_run(db, parse_id)
    found = search(store, "Regular pay")
    assert found["documents"]
    passage = found["documents"][0]["passages"][0]
    assert "Regular pay | 52000.00 | 2000.00" in passage["text"]
    row_id = next(line.id for line in lines if "Regular pay" in line.text)
    assert document_lines(store, doc["id"], row_id)["lines"]
    assert document_lines(store, doc["id"], result.lines[0].id)["lines"]


def test_table_evaluation_separates_text_coverage_and_wrong_column_values():
    from copy import deepcopy

    from evals.tasks.transcription import grade, report_lines, table_cases
    case = table_cases()[0]
    perfect = {"text": case["expected"]["text"], "tables": case["expected"]["tables"]}
    assert grade(case, perfect)["passed"]
    missing = grade(case, {"text": perfect["text"]})
    assert missing["checks"]["accuracy"] == 1 and not missing["passed"]
    wrong = deepcopy(perfect)
    wrong["tables"][0]["rows"][0]["cells"][1:] = ["52000.00", "2000.00"]
    wrong["text"] = wrong["text"].replace("2000.00 | 52000.00", "52000.00 | 2000.00")
    graded = grade(case, wrong)
    assert not graded["passed"] and graded["checks"]["wrong_column_values"] == 2
    assert "2" in "\n".join(report_lines({"synthetic": [{"grades": graded}]}))


def test_missing_native_rows_are_reviewed_and_blank_current_is_not_ytd(tmp_path):
    result = native_result(tmp_path, payroll_items())
    tables = evidence_tables(result)
    bonus = tables[0].rows[1]
    row = PayLine(description="Bonus", group="earnings", category="bonus", current="500.00", ytd="500.00",
                  evidence=[{"line_id": bonus.line_id, "quote": "Bonus"}])
    header = HEADER_MODELS["paystub"](**{name: MISSING for name in HEADERS["paystub"]})
    classification = SimpleNamespace(document_type="paystub")
    fake = SimpleNamespace(extract=lambda *args: (classification, header, [row], None))
    reading = ExtractionService.read(fake, None, Work.detached(), "run", result, evidence_lines(result), None, [])
    assert reading["rows"][0].current is None and reading["rows"][0].ytd == "500.00"
    assert any("2 native table row(s)" in note for note in reading["notes"])


def test_invoice_summary_and_holdings_keep_distinct_native_columns(tmp_path):
    result = native_result(tmp_path, [(40+c*145, 700-r*20, value) for r, row in enumerate([
        ["Invoice", "Invoice total", "Payments", "Balance due"], ["Order A", "100.00", "80.00", "20.00"],
        ["Order B", "200.00", "200.00", "0.00"]]) for c, value in enumerate(row)])
    table = evidence_tables(result)[0]
    header = HEADER_MODELS["bill"](**{name: MISSING for name in HEADERS["bill"]})
    from home_manager.documents.extraction import Value
    wrong = Value(value="20.00", status="proposed", evidence=[{"line_id": table.rows[0].line_id, "quote": "20.00"}])
    fixed, refs = anchor_summary(header.model_copy(update={"invoice_total": wrong}), [table], [])
    assert fixed.invoice_total.value == "100.00" and refs["invoice_total"]["cell_id"] == table.rows[0].cells[1].id
    folder = tmp_path / "holdings"; folder.mkdir()
    result = native_result(folder, [(40+c*140, 700-r*20, value) for r, row in enumerate([
        ["Holding", "Quantity", "Price", "Market value"], ["ABC Fund", "10", "25.00", "250.00"],
        ["DEF Fund", "20", "50.00", "1000.00"]]) for c, value in enumerate(row)])
    table = evidence_tables(result)[0]
    item = InvestmentLine(row_type="holding", description="ABC Fund", identifier=None, instrument_class=None,
                          activity_type=None, contribution_source=None, date=None, quantity="250.00", price="10", amount="25.00",
                          cost_basis=None, rate=None, maturity_date=None,
                          evidence=[{"line_id": table.rows[0].line_id, "quote": "ABC Fund"}])
    rows, _ = anchor_rows("investment_statement", [item], [table], [])
    assert (rows[0].quantity, rows[0].price, rows[0].amount) == ("10", "25.00", "250.00")


def test_paystub_total_cannot_become_an_earning_line(tmp_path):
    from home_manager.documents.extraction import anchor_paystub
    result = native_result(tmp_path, [(x, y, "Gross pay" if text == "Regular pay" else text) for x, y, text in payroll_items()])
    table = evidence_tables(result)[0]
    row = PayLine(description="Gross pay", group="earnings", category="regular_pay", current="2000.00", ytd="52000.00",
                  evidence=[{"line_id": table.rows[0].line_id, "quote": "Gross pay"}])
    header = HEADER_MODELS["paystub"](**{name: MISSING for name in HEADERS["paystub"]})
    notes = []
    _, rows, refs = anchor_paystub(header, [row], [table], notes)
    assert rows == refs == [] and "excluded" in notes[0]
