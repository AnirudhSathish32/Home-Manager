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
from test_pdf_layout import payroll_items, payslip_items, read_layout, sectioned_payslip_items, tight_payroll_items


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


def test_a_text_pdf_stub_with_no_rebuilt_table_is_read_like_flat_text(pdf_store, local_model):
    """paystub-columns plan P6: an embedded-text stub printing both columns on each line, without separators, rebuilds no
    table, so it is read like flat text: correct answers are kept, with no "multiple amounts" note (FR-31, FR-32)."""
    inbox, store = pdf_store
    printed = ["SYNTH WORKS", "EARNINGS STATEMENT", "PAY DATE 2026-07-03", "CURRENCY USD", "DESCRIPTION CURRENT YTD",
               "REGULAR 2,500.00 32,500.00", "FEDERAL INCOME TAX 250.00 3,250.00", "GROSS PAY 2,500.00 32,500.00", "NET PAY 2,250.00 29,250.00"]
    make_pdf(inbox / "text-stub.pdf", ["\n".join(printed)])
    doc = capture(inbox, store)
    service = ReceiptService(store)
    parse_id, _ = service.enqueue(doc["id"], vision=local_model["config"])
    service.run(parse_id, Work.detached())
    parsed = service.get(parse_id)
    assert parsed["status"] == "succeeded", parsed["error"]
    result = read_result(parsed["result"])
    assert evidence_tables(result) == []  # The no-table path is really taken.
    lines = evidence_lines(result)

    def cite(text, quote=None):
        line = next(line for line in lines if line.text.startswith(text))
        return [{"line_id": line.id, "quote": quote or line.text}]

    def value(text, line):
        return {"value": text, "status": "proposed", "evidence": cite(line, text)}
    summary = {name: MISSING for name in HEADERS["paystub"]}
    summary.update(payer_or_employer=value("SYNTH WORKS", "SYNTH"), pay_date=value("2026-07-03", "PAY DATE"), currency=value("USD", "CURRENCY"),
                   gross_pay=value("2,500.00", "GROSS PAY"), gross_pay_ytd=value("32,500.00", "GROSS PAY"),
                   net_pay=value("2,250.00", "NET PAY"), net_pay_ytd=value("29,250.00", "NET PAY"))
    rows = [{"description": "Regular", "group": "earnings", "category": "regular_pay", "current": "2,500.00", "ytd": "32,500.00", "evidence": cite("REGULAR")},
            {"description": "Federal income tax", "group": "tax", "category": "federal_income_tax", "current": "250.00", "ytd": "3,250.00",
             "evidence": cite("FEDERAL")}]
    local_model["by_schema"] = {"Classification": [{"document_type": "paystub", "evidence": cite("EARNINGS"), "issuer": summary["payer_or_employer"],
                                                    "document_date": summary["pay_date"]}],
                                "PaystubSummary": [summary], "PayLines": [{"lines": rows}]}
    extraction = ExtractionService(store, service)
    run_id, _ = extraction.enqueue(doc["id"], parse_id, ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning"))
    extraction.run(run_id, Work.detached())
    run = extraction.get(run_id)
    assert run["status"] == "succeeded", run["error"]
    record = Ledger(store).record("income_record", run["publication"]["id"])
    assert (record["gross_pay_minor"], record["net_pay_minor"], record["gross_pay_ytd_minor"]) == (250000, 225000, 3250000)
    assert [(line["current_minor"], line["ytd_minor"]) for line in record["lines"]] == [(250000, 3250000), (25000, 325000)]
    assert not any("multiple amounts" in issue or "printed columns" in issue for issue in record["issues"])


def test_a_payroll_site_stub_with_packed_columns_keeps_this_period_and_ytd(pdf_store, local_model):
    """A payroll site's text PDF prints This period and YTD less than 1.5 font sizes apart. Both columns are read as
    their own cells, so every amount is copied: none is left out, and a bonus printed only as YTD stays YTD."""
    inbox, store = pdf_store
    make_pdf(inbox / "packed-stub.pdf", [{"items": [(40, 760, "SYNTH WIDGETS LLC"), (40, 745, "Pay Date 2026-07-03"),
                                                     (40, 730, "Currency USD"), *tight_payroll_items()]}])
    doc = capture(inbox, store)
    service = ReceiptService(store)
    parse_id, _ = service.enqueue(doc["id"], vision=local_model["config"])
    service.run(parse_id, Work.detached())
    lines = evidence_lines(read_result(service.get(parse_id)["result"]))

    def cite(text, quote=None):
        line = next(line for line in lines if line.text.startswith(text))
        return [{"line_id": line.id, "quote": quote or line.text}]

    def value(text, line):
        return {"value": text, "status": "proposed", "evidence": cite(line, text)}
    summary = {name: MISSING for name in HEADERS["paystub"]}
    summary.update(payer_or_employer=value("SYNTH WIDGETS LLC", "SYNTH"), pay_date=value("2026-07-03", "Pay Date"), currency=value("USD", "Currency"),
                   gross_pay=value("$4,000.00", "Gross Pay"), gross_pay_ytd=value("56,000.00", "Gross Pay"))
    rows = [{"description": "Regular", "group": "earnings", "category": "regular_pay", "evidence": cite("Regular")},
            {"description": "Relocation Bonus", "group": "earnings", "category": "bonus", "evidence": cite("Relocation Bonus")}]
    local_model["by_schema"] = {"Classification": [{"document_type": "paystub", "evidence": cite("Earnings"), "issuer": summary["payer_or_employer"],
                                                    "document_date": summary["pay_date"]}],
                                "PaystubSummary": [summary], "PayRowClasses": [{"lines": rows}], "PayLines": [{"lines": []}] * 3}
    extraction = ExtractionService(store, service)
    run_id, _ = extraction.enqueue(doc["id"], parse_id, ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning"))
    extraction.run(run_id, Work.detached())
    run = extraction.get(run_id)
    assert run["status"] == "succeeded", run["error"]
    record = Ledger(store).record("income_record", run["publication"]["id"])
    assert (record["gross_pay_minor"], record["gross_pay_ytd_minor"]) == (400000, 5600000)
    assert [(line["current_minor"], line["ytd_minor"]) for line in record["lines"]] == [(400000, 5200000), (None, 400000)]
    assert sorted(record["lines"][0]["cell_evidence"]) == ["current", "ytd"] and sorted(record["lines"][1]["cell_evidence"]) == ["ytd"]
    assert not any("column headings" in issue or "source cell" in issue for issue in record["issues"])


def test_a_side_by_side_payslip_copies_every_line_and_total(pdf_store, local_model):
    """A payslip printing Earnings beside Deductions, totals at the foot of both: every pay line and the gross pay
    totals are copied from their own table's Current and YTD cells, with no note. "Regular Salary" is this paycheck's
    pay, not an annual figure (FR-22 a, amended 2026-10-19)."""
    inbox, store = pdf_store
    make_pdf(inbox / "payslip.pdf", [{"items": [(40, 760, "SYNTH WIDGETS LLC"), (40, 745, "Pay Date 2026-07-03"),
                                                 (40, 730, "Currency USD"), *payslip_items()]}])
    doc = capture(inbox, store)
    service = ReceiptService(store)
    parse_id, _ = service.enqueue(doc["id"], vision=local_model["config"])
    service.run(parse_id, Work.detached())
    lines = evidence_lines(read_result(service.get(parse_id)["result"]))

    def cite(text, quote=None):
        line = next(line for line in lines if line.text.startswith(text))
        return [{"line_id": line.id, "quote": quote or line.text}]

    def value(text, line):
        return {"value": text, "status": "proposed", "evidence": cite(line, text)}
    summary = {name: MISSING for name in HEADERS["paystub"]}
    summary.update(payer_or_employer=value("SYNTH WIDGETS LLC", "SYNTH"), pay_date=value("2026-07-03", "Pay Date"), currency=value("USD", "Currency"),
                   gross_pay=value("4,300.00", "Gross Pay"), gross_pay_ytd=value("57,200.00", "Gross Pay"))

    def classes(*rows):
        return {"lines": [{"description": label, "group": group, "category": category, "evidence": cite(label)} for label, group, category in rows]}
    local_model["by_schema"] = {"Classification": [{"document_type": "paystub", "evidence": cite("Earnings"), "issuer": summary["payer_or_employer"],
                                                    "document_date": summary["pay_date"]}],
                                "PaystubSummary": [summary],
                                "PayRowClasses": [classes(("Regular Salary", "earnings", "regular_pay"), ("Relocation Bonus", "earnings", "bonus"),
                                                          ("Overtime", "earnings", "overtime")),
                                                  classes(("Federal Income Tax", "tax", "federal_income_tax"), ("Social Security", "tax", "social_security"),
                                                          ("Medicare", "tax", "medicare"), ("401K", "pre_tax", "retirement_pretax"), ("Dental", "pre_tax", "dental"))],
                                "PayLines": [{"lines": []}] * 3}
    extraction = ExtractionService(store, service)
    run_id, _ = extraction.enqueue(doc["id"], parse_id, ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning"))
    extraction.run(run_id, Work.detached())
    run = extraction.get(run_id)
    assert run["status"] == "succeeded", run["error"]
    record = Ledger(store).record("income_record", run["publication"]["id"])
    assert (record["gross_pay_minor"], record["gross_pay_ytd_minor"]) == (430000, 5720000)
    assert [(line["description"], line["current_minor"], line["ytd_minor"]) for line in record["lines"]] == [
        ("Regular Salary", 400000, 5200000), ("Relocation Bonus", None, 400000), ("Overtime", 30000, 120000), ("Federal Income Tax", 50000, 650000),
        ("Social Security", 24800, 322400), ("Medicare", 5800, 75400), ("401K", 20000, 260000), ("Dental", 1200, 15600)]
    assert not any("column headings" in issue or "source cell" in issue or "multiple amounts" in issue for issue in record["issues"])


def test_a_sectioned_payslip_copies_every_line_total_and_benefit(pdf_store, local_model):
    """A ruled payslip template (sections, a blank row, totals at the foot of the box, a one-row benefits table on page
    two): every pay line and total is copied from its own table's cells, with no note."""
    inbox, store = pdf_store
    benefits = [(60, 700, "Other Benefit And Information"), (250, 700, "This Period"), (320, 700, "Year to Date"),
                (60, 685, "Co Match 401K"), (265, 685, "160.00"), (330, 685, "3,360.00")]
    make_pdf(inbox / "sectioned.pdf", [{"items": [(30, 760, "SYNTH CONSULTING LTD"), (30, 745, "Currency USD"), *sectioned_payslip_items()]},
                                       {"items": benefits}])
    doc = capture(inbox, store)
    service = ReceiptService(store)
    parse_id, _ = service.enqueue(doc["id"], vision=local_model["config"])
    service.run(parse_id, Work.detached())
    lines = evidence_lines(read_result(service.get(parse_id)["result"]))

    def cite(text, quote=None):
        line = next(line for line in lines if line.text.startswith(text))
        return [{"line_id": line.id, "quote": quote or line.text}]

    def value(text, line):
        return {"value": text, "status": "proposed", "evidence": cite(line, text)}
    summary = {name: MISSING for name in HEADERS["paystub"]}
    summary.update(payer_or_employer=value("SYNTH CONSULTING LTD", "SYNTH"), pay_date=value("10/09/2026", "Pay Date"), currency=value("USD", "Currency"),
                   # Cited from Regular Salary, as gpt-oss did: its this period is the total's too, its year to date isn't.
                   gross_pay=value("4,000.00", "Regular Salary"), gross_pay_ytd=value("84,000.00", "Regular Salary"),
                   net_pay=value("2,646.00", "Net Payment"), net_pay_ytd=value("59,566.00", "Net Payment"), deductions=value("1,354.00", "Total Deductions"))
    rows = [("Regular Salary", "earnings", "regular_pay"), ("Relocation Bonus", "earnings", "bonus"), ("Federal Tax", "tax", "federal_income_tax"),
            ("Social Security Tax", "tax", "social_security"), ("Medicare Tax", "tax", "medicare"), ("GA State Tax", "tax", "state_income_tax"),
            ("Medical HDP", "pre_tax", "health"), ("Vision Insurance", "pre_tax", "vision"), ("Dental PPO", "pre_tax", "dental"),
            ("HSA Additional", "pre_tax", "hsa"), ("401K Plan", "pre_tax", "retirement_pretax"), ("Co Match 401K", "employer_paid", "other")]
    local_model["by_schema"] = {"Classification": [{"document_type": "paystub", "evidence": cite("Earnings"), "issuer": summary["payer_or_employer"],
                                                    "document_date": summary["pay_date"]}],
                                "PaystubSummary": [summary],
                                "PayRowClasses": [{"lines": [{"description": label, "group": group, "category": category, "evidence": cite(label)}
                                                             for label, group, category in table]} for table in (rows[:2], rows[2:-1], rows[-1:])],
                                "PayLines": [{"lines": []}] * 3}
    extraction = ExtractionService(store, service)
    run_id, _ = extraction.enqueue(doc["id"], parse_id, ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning"))
    extraction.run(run_id, Work.detached())
    run = extraction.get(run_id)
    assert run["status"] == "succeeded", run["error"]
    record = Ledger(store).record("income_record", run["publication"]["id"])
    # Total Deductions (taxes and deductions together) is never the pre-tax deductions field: worked out from the
    # pre-tax lines instead (90.00 + 6.00 + 12.00 + 50.00 + 200.00), the total shown beside it.
    assert (record["gross_pay_minor"], record["gross_pay_ytd_minor"], record["net_pay_minor"], record["net_pay_ytd_minor"], record["deductions_minor"]) == (
        400000, 8800000, 264600, 5956600, None)
    assert (record["display"]["deductions_minor"], record["display"]["total_deductions_minor"]) == ("358.00 USD", "1,354.00 USD")
    assert [(line["description"], line["current_minor"], line["ytd_minor"]) for line in record["lines"]] == [
        ("Regular Salary", 400000, 8400000), ("Relocation Bonus", None, 400000), ("Federal Tax", 50000, 1050000), ("Social Security Tax", 24800, 520800),
        ("Medicare Tax", 5800, 121800), ("GA State Tax", 19000, 399000), ("Medical HDP", 9000, 189000), ("Vision Insurance", 600, 600),
        ("Dental PPO", 1200, 25200), ("HSA Additional", 5000, 105000), ("401K Plan", 20000, 420000), ("Co Match 401K", 16000, 336000)]
    # Hours and rate copied from their own columns, a whole number of hours included.
    assert (record["lines"][0]["details"]["hours"]["text"], record["lines"][0]["details"]["rate"]["text"]) == ("80", "50.00")
    assert not any(words in issue for issue in record["issues"]
                   for words in ("column headings", "source cell", "multiple amounts", "not accounted for", "left out", "add up"))


def test_a_table_row_cited_without_its_separators_or_by_a_cell_id_is_repaired_to_its_exact_line():
    """A model quoting a reported table row without its " | " separators or doubled spaces, or citing a cell id as the
    line, gets the row's exact text and line; a quote printed nowhere, or in two places, is left to fail."""
    from home_manager.documents.extraction import PayRowClasses, problems_in, repair_quotes
    lines = {"t-row-1": "Regular Salary | 50.00 | 80.00 | 4,000.00 | 84,000.00", "t-row-2": "Relocation Bonus |  |  |  | 4,000",
             "t-row-3": "Dental PPO | 12.00 | 12.00"}

    def answer(*cites):
        return PayRowClasses.model_validate({"lines": [{"description": "Row", "group": "earnings", "category": "other",
                                                        "evidence": [{"line_id": line_id, "quote": quote}]} for line_id, quote in cites]})
    fixed = repair_quotes(answer(("t-row-1", "Regular Salary 50.00 80.00 4,000.00 84,000.00"), ("t-row-2", "Relocation Bonus | | | | 4,000"),
                                 ("t-row-2-cell-1", "Relocation Bonus")), lines, {"t-row-2-cell-1": "t-row-2"})
    assert [(row.evidence[0].line_id, row.evidence[0].quote) for row in fixed.lines] == [
        ("t-row-1", lines["t-row-1"]), ("t-row-2", lines["t-row-2"]), ("t-row-2", "Relocation Bonus")]
    assert not problems_in(fixed, lines)
    unfixed = repair_quotes(answer(("t-row-1", "Regular Salary 55.00"), ("t-row-3", "12.00"), ("t-row-9", "Dental PPO")), lines, {})
    assert [message for _, message in problems_in(unfixed, lines)] == [
        "a citation is not an exact quote of an existing line", "a citation names a line id that isn't in these lines"]
    assert unfixed.lines[1].evidence[0].quote == "12.00"  # Exact already: two places is fine when the quote is exact.


def test_a_sectioned_payslip_records_when_the_model_quotes_rows_without_separators(pdf_store, local_model):
    """The same payslip when the model quotes each table row with plain spaces: it records, every amount copied."""
    inbox, store = pdf_store
    make_pdf(inbox / "sectioned.pdf", [{"items": [(30, 760, "SYNTH CONSULTING LTD"), (30, 745, "Currency USD"), *sectioned_payslip_items()]}])
    doc = capture(inbox, store)
    service = ReceiptService(store)
    parse_id, _ = service.enqueue(doc["id"], vision=local_model["config"])
    service.run(parse_id, Work.detached())
    lines = evidence_lines(read_result(service.get(parse_id)["result"]))

    def cite(text):
        line = next(line for line in lines if line.text.startswith(text))
        return [{"line_id": line.id, "quote": " ".join(line.text.replace("|", " ").split())}]

    def value(text, line):
        return {"value": text, "status": "proposed", "evidence": [{"line_id": cite(line)[0]["line_id"], "quote": text}]}
    summary = {name: MISSING for name in HEADERS["paystub"]}
    summary.update(payer_or_employer=value("SYNTH CONSULTING LTD", "SYNTH"), pay_date=value("10/09/2026", "Pay Date"), currency=value("USD", "Currency"),
                   gross_pay=value("4,000.00", "Total Earnings"), gross_pay_ytd=value("88,000.00", "Total Earnings"))
    tables = ([("Regular Salary", "earnings", "regular_pay"), ("Relocation Bonus", "earnings", "bonus")],
              [("Federal Tax", "tax", "federal_income_tax"), ("Medical HDP", "pre_tax", "health")])
    local_model["by_schema"] = {"Classification": [{"document_type": "paystub", "evidence": cite("Earnings"), "issuer": summary["payer_or_employer"],
                                                    "document_date": summary["pay_date"]}],
                                "PaystubSummary": [summary],
                                "PayRowClasses": [{"lines": [{"description": label, "group": group, "category": category, "evidence": cite(label)}
                                                             for label, group, category in table]} for table in tables],
                                "PayLines": [{"lines": []}] * 3}
    extraction = ExtractionService(store, service)
    run_id, _ = extraction.enqueue(doc["id"], parse_id, ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning"))
    extraction.run(run_id, Work.detached())
    run = extraction.get(run_id)
    assert run["status"] == "succeeded", run["error"]
    record = Ledger(store).record("income_record", run["publication"]["id"])
    assert [(line["description"], line["current_minor"], line["ytd_minor"]) for line in record["lines"]] == [
        ("Regular Salary", 400000, 8400000), ("Relocation Bonus", None, 400000), ("Federal Tax", 50000, 1050000), ("Medical HDP", 9000, 189000)]


def test_a_pay_row_listed_again_is_one_pay_line(pdf_store, local_model):
    """The model lists Regular Salary twice for its own row, and again (with Relocation Bonus) in the part of the text
    holding the table's heading row, citing the heading: each printed row is one pay line, with no note."""
    inbox, store = pdf_store
    make_pdf(inbox / "sectioned.pdf", [{"items": [(30, 760, "SYNTH CONSULTING LTD"), (30, 745, "Currency USD"), *sectioned_payslip_items()]}])
    doc = capture(inbox, store)
    service = ReceiptService(store)
    parse_id, _ = service.enqueue(doc["id"], vision=local_model["config"])
    service.run(parse_id, Work.detached())
    lines = evidence_lines(read_result(service.get(parse_id)["result"]))

    def cite(text, quote=None):
        line = next(line for line in lines if line.text.startswith(text))
        return [{"line_id": line.id, "quote": quote or line.text}]

    def value(text, line):
        return {"value": text, "status": "proposed", "evidence": cite(line, text)}

    def row(label, group, category, evidence=None, current=None, ytd=None):
        return {"description": label, "group": group, "category": category, "evidence": evidence or cite(label), "current": current, "ytd": ytd}
    summary = {name: MISSING for name in HEADERS["paystub"]}
    summary.update(payer_or_employer=value("SYNTH CONSULTING LTD", "SYNTH"), pay_date=value("10/09/2026", "Pay Date"), currency=value("USD", "Currency"),
                   gross_pay=value("4,000.00", "Total Earnings"), gross_pay_ytd=value("88,000.00", "Total Earnings"))
    heading = cite("Earnings", "Earnings")
    relisted = {"lines": [row("Regular Salary", "earnings", "regular_pay", heading), row("Relocation Bonus", "earnings", "bonus", heading)]}
    classes = [{key: value for key, value in item.items() if key not in ("current", "ytd")} for item in (
        row("Regular Salary", "earnings", "regular_pay"), row("Regular Salary", "earnings", "regular_pay"), row("Relocation Bonus", "earnings", "bonus"))]
    local_model["by_schema"] = {"Classification": [{"document_type": "paystub", "evidence": cite("Earnings"), "issuer": summary["payer_or_employer"],
                                                    "document_date": summary["pay_date"]}],
                                "PaystubSummary": [summary], "PayRowClasses": [{"lines": classes}, {"lines": []}],
                                "PayLines": [relisted, {"lines": []}]}
    extraction = ExtractionService(store, service)
    run_id, _ = extraction.enqueue(doc["id"], parse_id, ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning"))
    extraction.run(run_id, Work.detached())
    run = extraction.get(run_id)
    assert run["status"] == "succeeded", run["error"]
    record = Ledger(store).record("income_record", run["publication"]["id"])
    assert [(line["description"], line["current_minor"], line["ytd_minor"]) for line in record["lines"]] == [
        ("Regular Salary", 400000, 8400000), ("Relocation Bonus", None, 400000)]
    assert not any("printed row" in issue or "same native table row" in issue for issue in record["issues"])


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
    fake = SimpleNamespace(extract=lambda *args: (classification, header, [row], None, None))
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
