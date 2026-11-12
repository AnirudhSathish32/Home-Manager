"""Record uses the bill engine (specs/pdf-table-engine-bills/test-contract.md), slice SL-03: SC-100 step 4, SC-101, SC-102 steps 2 - 9, SC-103 step 3, SC-104
step 2, SC-105, SC-106, SC-110 steps 1 - 6, SC-111 steps 1 - 2, SC-112, SC-113, SC-114, SC-115 (a), SC-116 and SC-122 (UTIL-STRAY), plus the scanned one-bill
regression of plan P7.1. Slice SL-04 adds the tests named `sl04` (SC-111 step 4, SC-117, SC-118, SC-122's R1 (c) case).

Every file goes through the real services as tests/test_paystub_engine_record.py does: `make_pdf` into the Inbox, `capture`, `ReceiptService` (no vision call
for text pages), then `ExtractionService` with the contract's doubles (`local_model` by schema). Expected values are the contract's literals in
tests/bill_engine_fixtures.py, never what the code produced. The model stubs classify the charge rows right and answer every amount wrong (STUB-UTIL-WRONG,
and so on), so a value that reaches the record from the model would be wrong everywhere. The summary question's amounts are wrong but printed: a summary
amount must be printed where it is cited, or the question fails its citation check before Record sees it.

The double answers each question with the entries whose cited line is in that question's lines (one question is a run of lines the engine covers with charge
rows, or a run it doesn't), so a fixture's chunking needs no hand-written order.
"""

from collections import Counter
import dataclasses
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

import bill_engine_fixtures as bf
from home_manager.core.jobs import Work
from home_manager.documents import extraction
from home_manager.documents.reasoning import ReasoningConfig
from home_manager.finance import bill_tables
from home_manager.finance.family_routing import FamilyRouting
from home_manager.finance.ledger import Ledger
import home_manager.library
from test_bills_ledger import WHO
from test_extraction import MISSING
from test_paystub_engine_record import Run, no_network, started  # noqa: F401  (no_network is autouse: C-net)
from test_pdf import pdf_store  # noqa: F401

ENGINE = bill_tables.read  # Kept here so a test that makes the engine fail still shapes the model double with the real one.
V39 = "typed-extraction-v39-receipt-printed-signs"
MONEY = {"status": "proposed"}
BILL_FAILED_NOTE_TEXT = extraction.BILL_FAILED_NOTE

# The summary fields BL-UTIL's stub answers right (printed in the cited line): value, the line it starts, the quote.
UTIL_FIELDS = {"provider": ("CITY POWER & WATER", "CITY POWER & WATER", "CITY POWER & WATER"), "account_reference": ("9012", "Account Number", "1234-5678-9012"),
               "issue_date": ("2026-09-20", "Statement Date", "09/20/2026"), "due_date": ("2026-10-15", "Due Date", "10/15/2026"),
               "period_start": ("2026-08-15", "Billing Period", "08/15/2026"), "period_end": ("2026-09-14", "Billing Period", "09/14/2026"),
               "currency": ("USD", "This bill is for", "US dollars")}
# Wrong but printed: the cited line prints the value (a summary amount is checked against its citation before Record sees it).
UTIL_WRONG_AMOUNTS = {"amount_due": ("82.10", "82.10", "82.10"), "new_charges": ("60.00", "60.00", "60.00")}
PHONE_FIELDS = {"provider": ("METRO WIRELESS", "METRO WIRELESS", "METRO WIRELESS"), "account_reference": ("7788", "Account Number", "555-0100-7788"),
                "due_date": ("2026-10-12", "Due Date", "10/12/2026"), "currency": ("USD", "This bill is for", "US dollars"),
                "amount_due": ("120.00", "120.00", "120.00"), "new_charges": ("24.99", "24.99", "24.99")}
RENT_FIELDS = {"provider": ("SYNTH PROPERTY MANAGEMENT", "SYNTH PROPERTY MANAGEMENT", "SYNTH PROPERTY MANAGEMENT"),
               "account_reference": ("4821", "Resident Account", "****4821"), "due_date": ("2026-10-01", "Due Date", "10/01/2026"),
               "currency": ("USD", "This bill is for", "US dollars"), "amount_due": ("1,450.00", "Rent", "$1,450.00")}
# Which printed line starts a row whose label differs from the line (a wrapped label).
ROW_LINES = {"International Pack (Canada and Mexico)": "International Pack"}
LINE_KEYS = ("description", "line_total_minor", "line_kind")


class BillRun(Run):
    """One fixture, read and then extracted through the real services, with the bill doubles."""

    def runs(self):
        """The runs of evidence lines the engine covers with charge rows, and the runs it doesn't, in file order: each is one model question."""
        covered = {line_id for table in ENGINE(self.evidence).adapted for line_id in [*(row.line_id for row in table.rows), *table.spans]}
        runs = []
        for line in self.lines:
            if not runs or (line.id in covered) != runs[-1][0]:
                runs.append([line.id in covered, []])
            runs[-1][1].append(line.id)
        return runs

    def field(self, value, label, quote):
        return {"value": value, "status": "proposed", "evidence": self.cite(label, quote)}

    def header(self, fields, **changes):
        """The summary answer: `fields` (a name to (value, the line it starts, the quote)); changes replace a field by a ready answer or MISSING."""
        names = ("provider", "account_reference", "issue_date", "due_date", "period_start", "period_end", "amount_due", "new_charges", "currency")
        answer = {name: MISSING for name in names}
        answer.update({name: self.field(*found) for name, found in fields.items()})
        return {**answer, **changes}

    def model_line(self, key, entry, rent=False):
        """A model line for a stub row: (description, line_kind, category, line_holder, amount, quantity, unit_price), citing its printed line."""
        description, kind, category, holder, amount, quantity, unit = entry
        line = self.line(ROW_LINES.get(key, key))
        row = {"description": description, "amount": amount, "quantity": quantity, "unit_price": unit, "category": category, "line_holder": holder,
               "evidence": [{"line_id": line.id, "quote": line.text}]}
        return {**row, "rent_type": kind, "period_start": None, "period_end": None, "usage": None} if rent else {**row, "line_kind": kind}

    def stub_bill(self, rows, fields, kind="general", extra=(), classify="CITY POWER & WATER", single_run=False, **changes):
        """The contract's `local_model` by schema: the classification of a bill citing its first line, the summary, and the lines of each run.
        rows: stub rows keyed by printed label; extra: ready model lines (a total, a line the print doesn't have); changes: replaced summary fields."""
        rent = kind == "rent"
        header = self.header(fields, **changes)
        entries = [self.model_line(key, entry, rent) for key, entry in rows.items()] + list(extra)
        runs = [[False, [line.id for line in self.lines]]] if single_run else self.runs()  # Read like flat text, the whole bill is one question.
        classification = {"document_type": "bill", "evidence": self.cite(classify), "issuer": header["provider"], "document_date": MISSING,
                          "bill_kind": kind, "bill_kind_evidence": self.cite("Rent and Leasing Charges") if rent else []}
        self.local_model["by_schema"] = {
            "Classification": [classification], "BillRentSummary" if rent else "BillSummary": [header],
            "RentBillLines" if rent else "BillLines": [{"line_items": [entry for entry in entries if entry["evidence"][0]["line_id"] in ids]} for _, ids in runs]}
        self.questions = 2 + len(runs)
        self.before = len(self.local_model["requests"])

    def requests(self, schema):
        """This run's requests for a schema, as the model saw them: the lines and the reported tables."""
        return [json.loads(request["messages"][1]["content"]) for request in self.local_model["requests"][self.before:]
                if request["response_format"]["json_schema"]["name"] == schema]

    def bill_row(self):
        with self.store.connection() as db:
            return dict(db.execute("SELECT * FROM receipts WHERE id=?", (self.run["publication"]["id"],)).fetchone())

    @property
    def record(self):
        return Ledger(self.store).record("receipt", self.run["publication"]["id"])

    @property
    def notes(self):
        """The bill's own notes (`details_json[bill_kind]["notes"]`), where C-note reads them."""
        return (self.record["details"] or {}).get("notes", [])


def bill_run(pdf_store, local_model, pages, rows, fields, kind="general", extra=(), extract=True, name="bill.pdf", **changes):
    """A fixture read, stubbed (rows, fields) and extracted."""
    run = started(pdf_store, local_model, pages, name=name)
    run.__class__ = BillRun
    run.stub_bill(rows, fields, kind, extra, **changes)
    if extract:
        run.extract()
    return run


def util(pdf_store, local_model, pages=None, rows=bf.STUB_UTIL_WRONG, **options):
    """BL-UTIL (or a variant) with the wrong-everywhere stub, extracted."""
    return bill_run(pdf_store, local_model, pages if pages is not None else bf.util_pages(), rows, {**UTIL_FIELDS, **UTIL_WRONG_AMOUNTS}, **options)


def phone(pdf_store, local_model, rows=bf.STUB_PHONE, pages=None, extra=(), **options):
    return bill_run(pdf_store, local_model, pages if pages is not None else bf.phone_pages(), rows, PHONE_FIELDS, classify="METRO WIRELESS", extra=extra, **options)


# --- Shared checks (the contract's "Shared checks") ---------------------------------------------------------------------------------

def lines_of(record):
    """C-lines: (description, line_total_minor, line_kind or line_type) by position."""
    return [(item["description"], item["line_total_minor"], item["line_type"] or item["line_kind"]) for item in record["items"]]


def auto(record):
    """C-auto."""
    assert record["review_status"] == "verified" and record["issues"] == [], record["issues"]


def reasons(record, *facts):
    """C-reason: exactly one issue holds every fact, and the bill waits in To check."""
    assert len([issue for issue in record["issues"] if all(fact in issue for fact in facts)]) == 1, (facts, record["issues"])
    assert record["review_status"] == "needs_review"


def no_feature_review(record):
    """C-no-feature-review: no issue about a column, a guess, an unplaced or unclassified line, a charge table, a printed total or a split."""
    words = ("column", "guess", "unplaced", "unclassified", "charge table", "printed total", "subtotal", "split", "native source", "native table row")
    assert [issue for issue in record["issues"] if "PDF layout needs review" not in issue and any(word in issue.lower() for word in words)] == []


def noted(run, *facts):
    """C-note: a note of the bill holds every fact, and no issue does."""
    assert [note for note in run.notes if all(fact in note for fact in facts)], (facts, run.notes)
    assert [issue for issue in run.record["issues"] if all(fact in issue for fact in facts)] == [], facts


def not_anchoring(run):
    """SC-113 step 3: no anchoring note on an engine page."""
    for text in [*run.record["issues"], *run.notes]:
        assert "no unambiguous native source column" not in text and "native table row(s) were not accounted for" not in text, text


def no_grid(run):
    """C-no-grid: every table a request after the classification carried is the bill engine's, never the reader's printed grid."""
    for schema in ("BillSummary", "BillRentSummary", "BillLines", "RentBillLines"):
        for request in run.requests(schema):
            assert all("-layout-table-" not in table["table_id"] for table in request.get("reported_tables", [])), request["reported_tables"]


def planned_questions(run):
    """C-model-calls: the stubs were asked the classification, the summary and one question per run of lines; the engine asked nothing."""
    assert len(run.asked()) == run.questions
    assert Counter(run.asked())["Classification"] == 1


def money_is_integer(run):
    """C-money: the amounts and every line's amount and unit price are integers or null, in USD; the details' minor values are integers."""
    with run.store.connection() as db:
        row = db.execute("SELECT typeof(total_minor),typeof(amount_due_minor),currency,details_json,bill_kind FROM receipts WHERE id=?",
                         (run.run["publication"]["id"],)).fetchone()
        assert {row[0], row[1]} <= {"integer", "null"} and row[2] == "USD"
        assert {kind for (kind,) in db.execute("SELECT typeof(line_total_minor) FROM receipt_items WHERE receipt_id=?", (run.run["publication"]["id"],))} <= {"integer"}
        assert {kind for (kind,) in db.execute("SELECT typeof(unit_price_minor) FROM receipt_items WHERE receipt_id=?", (run.run["publication"]["id"],))} <= {"integer", "null"}
    for name, detail in json.loads(row[3])[row[4]].items():
        if isinstance(detail, dict) and "minor" in detail:
            assert isinstance(detail["minor"], int), name


def finished(run, before=None):
    """What every record test ends with: C-docs (the original and the reading folder are as they were), C-money, SC-113 step 3 and C-ledger."""
    from conftest import assert_ledger_healthy
    if before is not None:
        assert run.fingerprint() == before
    money_is_integer(run)
    not_anchoring(run)
    assert_ledger_healthy(run.store)


def expect_util(run, rates=bf.EXP_UTIL_RATE, totals=bf.EXP_UTIL):
    """EXP-UTIL: the four lines with their printed quantity and rate, the amounts, and both checks; C-rate on each rate."""
    record = run.record
    assert lines_of(record) == bf.EXP_UTIL_LINES
    assert [item["quantity"] for item in record["items"]] == [bf.EXP_UTIL_QUANTITY.get(item[0]) for item in bf.EXP_UTIL_LINES]
    for item in record["items"]:
        minor, text = rates.get(item["description"], (None, None))
        assert item["unit_price_minor"] == minor
        shown = (item["details"] or {}).get("unit_price")
        assert (shown["text"] if shown else None) == text, item["description"]
    assert [issue for issue in record["issues"] if "Amount has more precision" in issue or issue.startswith("Charge line")] == []
    assert (record["total_minor"], record["amount_due_minor"], record["due_date"], record["issue_date"]) == (
        totals["total_minor"], totals["amount_due_minor"], totals["due_date"], totals["issue_date"])
    assert (record["period_start"], record["period_end"]) == totals["period"]
    details = record["details"]
    assert (details["previous_balance"]["minor"], details["payments_received"]["minor"], details["new_charges"]["minor"]) == (
        totals["previous_balance"], totals["payments_received"], totals["new_charges"])
    checks = {check["name"]: check for check in record["checks"]}
    assert checks["lines"]["passes"] and checks["carried"]["passes"]
    auto(record)
    return record


# === SC-110: every amount from its printed cell ===========================================================================

def test_sc110_every_amount_quantity_and_rate_is_its_printed_cell_although_the_model_was_wrong_everywhere(pdf_store, local_model):
    run = started(pdf_store, local_model, bf.util_pages())
    run.__class__ = BillRun
    before = run.fingerprint()
    run.stub_bill(bf.STUB_UTIL_WRONG, {**UTIL_FIELDS, **UTIL_WRONG_AMOUNTS})
    run.extract()
    expect_util(run)
    assert run.run["prompt_version"] == extraction.EXTRACTION_VERSION == "typed-extraction-v48-bill-review-fixes" != V39
    no_grid(run)
    planned_questions(run)
    finished(run, before)


def test_sc110_a_blank_cell_stays_blank_and_the_model_cannot_fill_it(pdf_store, local_model):
    run = util(pdf_store, local_model)  # STUB-UTIL-WRONG gives Customer Charge quantity 1 and unit price 13.00.
    customer = next(item for item in run.record["items"] if item["description"] == "Customer Charge")
    assert (customer["quantity"], customer["unit_price_minor"], customer["line_total_minor"]) == (None, None, 1200)
    # The model's own wrong numbers reach no stored amount: 61.00, 21.02, 13.00, 6.53 and 98.55.
    stored = {record_value for item in run.record["items"] for record_value in (item["line_total_minor"], item["unit_price_minor"])}
    assert not stored & {6100, 2102, 1300, 653, 9855, 13, 15}


def test_sc110_the_line_question_carries_the_engines_cells_with_their_roles_and_no_printed_grid(pdf_store, local_model):
    run = util(pdf_store, local_model)
    tables = [table for request in run.requests("BillLines") for table in request.get("reported_tables", [])]
    assert tables and all(table["table_id"] == "page-1-charges-1" for table in tables)
    rows = {row["cells"][0]["text"]: [cell["text"] for cell in row["cells"]] for table in tables for row in table["rows"]}
    assert rows["Energy Tier 2"] == ["Energy Tier 2", "140 kWh", "0.1430", "20.02"]
    assert rows["Customer Charge"] == ["Customer Charge", "", "", "12.00"]
    assert {key: tables[0]["roles"][key] for key in ("1", "2", "3")} == {"1": "quantity", "2": "unit_price", "3": "charge"}
    no_grid(run)
    asked = [request for request in run.local_model["requests"][run.before:] if request["response_format"]["json_schema"]["name"] == "BillLines"]
    assert [("copies each amount, quantity and unit price" in request["messages"][0]["content"], "reported_tables" in request["messages"][1]["content"])
            for request in asked] == [(False, False), (True, True), (False, False)]  # Only the run the engine covers is told to copy its cells.


def test_sc110_a_rent_bill_and_the_same_file_read_as_general_copy_the_same_amounts(pdf_store, local_model):
    for kind in ("rent", "general"):
        run = started(pdf_store, local_model, bf.rent_pages(), name=f"{kind}.pdf")
        run.__class__ = BillRun
        rent = kind == "rent"
        rows = [{"description": "Rent", "amount": "1,540.00", "quantity": None, "unit_price": None, "category": "housing", "line_holder": None,
                 "evidence": run.cite("Rent 10/01/2026"), **({"rent_type": "rent", "period_start": "2026-10-01", "period_end": "2026-10-31", "usage": None}
                                                              if rent else {"line_kind": "service"})},
                {"description": "Water Usage", "amount": "83.42", "quantity": None, "unit_price": None, "category": "utilities", "line_holder": None,
                 "evidence": run.cite("Water Usage"), **({"rent_type": "utility", "period_start": "2026-08-15", "period_end": "2026-09-14", "usage": "3,200 GAL"}
                                                          if rent else {"line_kind": "usage"})}]
        run.stub_bill({}, RENT_FIELDS, kind=kind, extra=rows, classify="SYNTH PROPERTY")
        run.extract()
        record = run.record
        assert [(item["description"], item["line_total_minor"]) for item in record["items"]] == [("Rent", 145000), ("Water Usage", 3842)]
        assert (record["amount_due_minor"], record["total_minor"]) == (bf.EXP_RENT["amount_due_minor"], bf.EXP_RENT["total_minor"])
        if rent:  # EXP-RENT: the rent form's types, printed periods and usage.
            assert [(item["line_type"]) for item in record["items"]] == ["rent", "utility"]
            assert record["items"][1]["details"]["usage"]["text"] == bf.EXP_RENT["usage"]
            assert (record["items"][0]["details"]["period"]["start"], record["items"][0]["details"]["period"]["end"]) == bf.EXP_RENT["periods"][0]
        else:
            assert [item["line_kind"] for item in record["items"]] == ["service", "usage"]
        no_grid(run)
        not_anchoring(run)


def test_sc100_a_rent_text_pdf_records_its_printed_amounts_although_every_model_amount_was_wrong(pdf_store, local_model):
    run = started(pdf_store, local_model, bf.rent_pages())
    run.__class__ = BillRun
    before = run.fingerprint()
    rows = [{"description": "Rent", "amount": "1,540.00", "quantity": None, "unit_price": None, "category": "housing", "line_holder": None,
             "evidence": run.cite("Rent 10/01/2026"), "rent_type": "rent", "period_start": "2026-10-01", "period_end": "2026-10-31", "usage": None},
            {"description": "Water Usage", "amount": "83.42", "quantity": None, "unit_price": None, "category": "utilities", "line_holder": None,
             "evidence": run.cite("Water Usage"), "rent_type": "utility", "period_start": "2026-08-15", "period_end": "2026-09-14", "usage": "3,200 GAL"}]
    run.stub_bill({}, RENT_FIELDS, kind="rent", extra=rows, classify="SYNTH PROPERTY")
    run.extract()
    record = run.record
    assert lines_of(record) == bf.EXP_RENT_LINES
    assert (record["amount_due_minor"], record["total_minor"]) == (bf.EXP_RENT["amount_due_minor"], bf.EXP_RENT["total_minor"])
    assert [item["details"]["period"] for item in record["items"]] == [
        {"start": start, "end": end, "how": "printed", "locator": item["details"]["period"]["locator"]} for (start, end), item in zip(bf.EXP_RENT["periods"], record["items"])]
    assert record["items"][1]["details"]["usage"]["text"] == "3,200 GAL"
    assert record["bill_kind"] == "rent"
    no_grid(run)
    planned_questions(run)
    finished(run, before)


# === SC-101: headings are never required ======================================================================================

@pytest.mark.parametrize("name", ["UTIL-2L", "UTIL-ODD", "UTIL-NOHEAD"])
def test_sc101_the_three_columns_are_found_whatever_their_headings(pdf_store, local_model, name):
    run = util(pdf_store, local_model, pages=bf.FIXTURES[name]())
    expect_util(run)
    assert [note for note in run.notes if "column" in note] == []  # The product rule decides: no guess.
    assert (run.record["details"] or {}).get("guesses") is None
    finished(run)


# === SC-102: sections, a wrapped label, holders from section titles =========================================================

def title_line(run, name):
    return run.line(name).id


def expect_phone(run, holders=bf.EXP_PHONE_HOLDERS, lines=bf.EXP_PHONE_LINES, total=bf.EXP_PHONE):
    """EXP-PHONE with EXP-PHONE-HOLDERS (SC-102 steps 2 and 3): the lines, whose holder each has and whether its evidence holds its section title."""
    record = run.record
    assert lines_of(record) == lines
    assert [item["line_holder"] for item in record["items"]] == holders
    titles = [title_line(run, "Alex 555-201-1111"), title_line(run, "Blair 555-202-2222")]
    for item, holder in zip(record["items"], holders):
        assert (titles[0] in item["line_ids"]) == (holder == "Alex 555-201-1111"), item["description"]
        assert (titles[1] in item["line_ids"]) == (holder == "Blair 555-202-2222"), item["description"]
        assert title_line(run, "Account Credits") not in item["line_ids"]
    assert (record["total_minor"], record["amount_due_minor"]) == (total["total_minor"], total["amount_due_minor"])
    assert (record["details"]["previous_balance"]["minor"], record["details"]["payments_received"]["minor"]) == (total["previous_balance"], total["payments_received"])
    assert all(item["member_id"] is None for item in record["items"])  # Before routing.
    return record


def route(run):
    """FAM-WHO: Alex and Blair's phone lines, applied after Extract (SC-102 step 4)."""
    routing = FamilyRouting(run.store)
    routing.refresh({}, WHO[:2])
    return Ledger(run.store).record("receipt", run.run["publication"]["id"]), routing


def members(record):
    return [(item["member_id"], item["member_source"]) for item in record["items"]]


MEMBERS = [("alex", "configured"), ("alex", "configured"), ("blair", "configured"), ("blair", "configured"), (None, None)]


def test_sc102_a_phone_bill_records_each_line_with_its_sections_holder_and_wrapped_label(pdf_store, local_model):
    run = phone(pdf_store, local_model)
    record = expect_phone(run)
    auto(record)
    international = record["items"][3]
    assert international["line_ids"][:2] == [run.line("International Pack").id, run.line("(Canada and Mexico)").id]  # Its own lines in order; the title follows.
    assert not [note for note in run.notes if note.startswith("Line ") and "differs from its section title" in note]
    assert "Total for" not in " ".join(item["description"] for item in record["items"])
    no_grid(run)
    routed, routing = route(run)
    assert members(routed) == MEMBERS
    [listed] = routing.list()
    assert listed["suggested"]["mode"] == "lines" and set(listed["suggested"]["members"]) == {"alex", "blair"} and listed["suggested"]["ask"] is None
    finished(run)


def test_sc102_b_the_title_alone_gives_the_holder_when_the_model_gave_none(pdf_store, local_model):
    run = phone(pdf_store, local_model, rows=bf.STUB_PHONE_NOHOLD)
    record = expect_phone(run)
    auto(record)
    assert not [note for note in run.notes if "differs from its section title" in note]
    assert members(route(run)[0]) == MEMBERS


def test_sc102_c_a_model_holder_that_disagrees_with_its_section_title_gives_way_with_a_note(pdf_store, local_model):
    run = phone(pdf_store, local_model, rows=bf.STUB_PHONE_DISAGREE)
    record = expect_phone(run)
    auto(record)
    notes = [note for note in run.notes if note.startswith("Line ") and "differs from its section title" in note]
    assert notes == ["Line 3: the holder Alex 555-201-1111 differs from its section title; the title's holder Blair 555-202-2222 was used."]
    assert members(route(run)[0]) == MEMBERS
    noted(run, notes[0])


def test_sc102_d_a_model_holder_in_another_format_agrees_with_its_title(pdf_store, local_model):
    run = phone(pdf_store, local_model, rows=bf.STUB_PHONE_AGREE)
    auto(expect_phone(run))
    assert not [note for note in run.notes if "differs from its section title" in note]
    assert members(route(run)[0]) == MEMBERS


def test_sc102_e_a_holder_the_credit_row_does_not_print_is_dropped_as_before(pdf_store, local_model):
    run = phone(pdf_store, local_model, rows=bf.STUB_PHONE_CREDITHOLD)
    record = expect_phone(run)
    auto(record)
    assert record["items"][4]["line_holder"] is None
    assert not [note for note in run.notes if "differs from its section title" in note]
    assert members(route(run)[0]) == MEMBERS


TITLE_FIELDS = {"provider": ("SYNTH TITLE CO", "SYNTH TITLE CO", "SYNTH TITLE CO"), "account_reference": ("9012", "Account Number", "1234-5678-9012"),
                "issue_date": ("2026-09-20", "Statement Date", "09/20/2026"), "due_date": ("2026-10-15", "Due Date", "10/15/2026"),
                "period_start": ("2026-08-15", "Billing Period", "08/15/2026"), "period_end": ("2026-09-14", "Billing Period", "09/14/2026"),
                "currency": ("USD", "This bill is for", "US dollars")}


def title_pages(title, **options):
    """bf.title_page with its new charges and amount due printed under the rows, so the bill's lines are cross-checked (10.00 + 5.00)."""
    pages = bf.title_page(title, **options)
    pages[0]["items"] += bf.amounts_at(600, "New Charges", (bf.CHARGE, "15.00")) + bf.amounts_at(584, "Amount Due", (bf.CHARGE, "15.00"))
    return pages


def titled(pdf_store, local_model, title, holders=(None, None), **options):
    """A one-section page whose title is `title`, with rows Plan and Device and the model's holders on them."""
    rows = {"Plan": ("Plan", "service", None, holders[0], "10.00", None, None), "Device": ("Device", "service", None, holders[1], "5.00", None, None)}
    run = bill_run(pdf_store, local_model, title_pages(title, encoding="cp1252" if "•" in title else None), rows,
                   {**TITLE_FIELDS, "amount_due": ("10.00", "Plan", "10.00")}, classify="SYNTH TITLE", **options)
    place = next(number for number, line in enumerate(run.lines) if line.text.startswith("Plan"))
    return run, [item["line_holder"] for item in run.record["items"]], run.lines[place - 1].id  # The title is the line just above the first row.


HOLDER_TITLES = [(title, text) for title, is_holder, text in bf.PHONE_TITLES if is_holder]
NOT_HOLDER_TITLES = [title for title, is_holder, _ in bf.PHONE_TITLES if not is_holder]


@pytest.mark.parametrize("title,printed", HOLDER_TITLES)
def test_sc102_a_phone_number_in_a_title_gives_its_rows_the_title_as_printed_with_no_model_holder(pdf_store, local_model, title, printed):
    run, holders, title_id = titled(pdf_store, local_model, title)
    assert holders == [printed, printed]
    assert all(title_id in item["line_ids"] for item in run.record["items"])
    auto(run.record)


@pytest.mark.parametrize("title", NOT_HOLDER_TITLES)
def test_sc102_a_title_with_no_phone_number_gives_no_holder_when_the_model_gave_none(pdf_store, local_model, title):
    run, holders, title_id = titled(pdf_store, local_model, title)
    assert holders == [None, None]
    assert all(title_id not in item["line_ids"] for item in run.record["items"])
    auto(run.record)


def test_sc102_a_title_with_a_year_is_no_holder_title_even_when_the_model_names_a_holder(pdf_store, local_model):
    run, holders, title_id = titled(pdf_store, local_model, "Charges 2026", ("Alex 555-201-1111", None))
    assert holders == [None, None]  # Not printed in the row's own line (today's rule), and no title is cited.
    assert all(title_id not in item["line_ids"] for item in run.record["items"])


def test_sc102_a_title_longer_than_eighty_characters_is_cut_to_eighty_as_the_holder(pdf_store, local_model):
    rows = {"Plan": ("Plan", "service", None, None, "10.00", None, None), "Device": ("Device", "service", None, None, "5.00", None, None)}
    run = bill_run(pdf_store, local_model, title_pages(bf.LONG_TITLE, size=7), rows, {**TITLE_FIELDS, "amount_due": ("10.00", "Plan", "10.00")}, classify="SYNTH TITLE")
    assert [item["line_holder"] for item in run.record["items"]] == [bf.LONG_TITLE[:80]] * 2
    assert len(run.record["items"][0]["line_holder"]) == 80


NAME_ONLY = [
    # (the model's holders on Plan and Device, a holder title?, the rows' holder, the note, the issues)
    (("Alex 555-201-1111", None), True, "Alex", None),
    (("Blair", "Blair"), False, None, None),
    ((None, None), False, None, None),
    (("Alex", "Blair 555-202-2222"), True, "Alex", "Line 2: the holder Blair 555-202-2222 differs from its section title; the title's holder Alex was used."),
]


@pytest.mark.parametrize("given,is_holder,holder,note", NAME_ONLY)
def test_sc102_a_name_only_title_counts_only_when_a_model_holder_of_the_section_has_a_word_in_it(pdf_store, local_model, given, is_holder, holder, note):
    run, holders, title_id = titled(pdf_store, local_model, "Alex", given)
    assert holders == [holder, holder]
    assert all((title_id in item["line_ids"]) == is_holder for item in run.record["items"])
    assert [n for n in run.notes if "differs from its section title" in n] == ([note] if note else [])
    auto(run.record)


# === SC-103: summary anchors wherever printed; late amounts are nothing ======================================================

@pytest.mark.parametrize("name", ["UTIL-LATE", "UTIL-LATE-COL"])
def test_sc103_a_late_payment_amount_is_never_recorded(pdf_store, local_model, name):
    run = util(pdf_store, local_model, pages=bf.FIXTURES[name]())
    record = expect_util(run)
    stored = [record["total_minor"], record["amount_due_minor"], *(item["line_total_minor"] for item in record["items"]),
              *(detail["minor"] for detail in record["details"].values() if isinstance(detail, dict) and "minor" in detail)]
    assert 10255 not in stored
    assert not [note for note in run.notes if "amount due is printed as" in note]  # No FR-117 guess: 97.55 is printed alike.
    finished(run)


# === SC-104: nothing dropped silently =====================================================================================

def test_sc104_a_line_placed_in_no_column_is_a_note_not_a_review_reason(pdf_store, local_model):
    run = util(pdf_store, local_model, pages=bf.util_stray_pages())
    record = expect_util(run)
    noted(run, "Page 1", "Paperless billing saves paper")
    no_feature_review(record)
    finished(run)


# === SC-105: which column is the charge ===================================================================================

@pytest.mark.parametrize("pages", [bf.util_shuf_items, lambda: bf.util_shuf_items(False)], ids=["UTIL-SHUF", "BL-HEADLESS"])
def test_sc105_the_charge_column_is_found_by_the_numbers_wherever_it_is_printed(pdf_store, local_model, pages):
    run = util(pdf_store, local_model, pages=[bf.page_of(pages())])
    expect_util(run)
    assert not [note for note in run.notes if "column" in note]
    assert (run.record["details"] or {}).get("guesses") is None
    finished(run)


UTIL_LASTYEAR_STUB = {"Energy Charge": ("Energy Charge", "usage", "utilities", None, "81.02", None, None),
                      "Customer Charge": ("Customer Charge", "service", "utilities", None, "13.00", None, None),
                      "State Tax": ("State Tax", "tax_fee", "utilities", None, "6.53", None, None)}


@pytest.mark.parametrize("head", [True, False], ids=["UTIL-LASTYEAR", "UTIL-LASTYEAR-C2"])
def test_sc105_this_bills_column_is_the_charge_because_it_adds_up_to_the_new_charges(pdf_store, local_model, head):
    run = bill_run(pdf_store, local_model, [bf.page_of(bf.util_lastyear_items(head))], UTIL_LASTYEAR_STUB,
                   {**UTIL_FIELDS, "amount_due": ("82.10", "82.10", "82.10"), "new_charges": ("80.02", "80.02", "80.02")})
    record = run.record
    assert [(item["description"], item["line_total_minor"]) for item in record["items"]] == [("Energy Charge", 8002), ("Customer Charge", 1200), ("State Tax", 553)]
    assert record["total_minor"] == 9755
    stored = {record["total_minor"], record["amount_due_minor"], *(item["line_total_minor"] for item in record["items"])}
    assert not stored & {7215, 498, 8913}
    auto(record)
    assert not [note for note in run.notes if "column" in note]  # Decided by the numbers: no guess.
    finished(run)


# === SC-106: money off ====================================================================================================

DISCOUNT_PAGES = {"signed": lambda: bf.phone_pages(), "unsigned": lambda: bf.phone_pages("5.00"), "parentheses": lambda: bf.phone_pages("(5.00)"),
                  "credit": lambda: bf.phone_pages("5.00 CR")}


def discount_stub(kind):
    return {**bf.STUB_PHONE, "Autopay Discount": ("Autopay Discount", kind, "utilities", None, "5.00", None, None)}


@pytest.mark.parametrize("printed,answer,noted_kind", [
    ("signed", "service", True),  # (1) printed -5.00, the model said service.
    ("unsigned", "credit", False),  # (2) unsigned under Account Credits, the model said credit: no note.
    ("unsigned", "service", None),  # (3) unsigned under Account Credits, the model said service: money off by the section (G8: a note isn't asserted).
    ("parentheses", "service", True), ("credit", "service", True)])  # (4) and (5).
def test_sc106_a_row_printed_as_money_off_is_a_credit(pdf_store, local_model, printed, answer, noted_kind):
    run = phone(pdf_store, local_model, rows=discount_stub(answer), pages=DISCOUNT_PAGES[printed]())
    record = run.record
    assert lines_of(record) == bf.EXP_PHONE_LINES
    assert sum(item["line_total_minor"] for item in record["items"]) == 11850
    money_off = [note for note in run.notes if "Autopay Discount" in note and "money off" in note]
    if noted_kind is not None:
        assert bool(money_off) is noted_kind, run.notes
    auto(record)
    finished(run)


@pytest.mark.parametrize("title", ["Account Credits", "Discounts", "Adjustments"])
def test_sl11_f2_a_plus_five_under_a_money_off_section_is_stored_as_a_charge_of_five(pdf_store, local_model, title):
    """FR-106 applies the section only to an UNSIGNED amount: `+5.00` is a charge even under `Account Credits`, the model's `service` stays."""
    run = phone(pdf_store, local_model, rows=discount_stub("service"), pages=bf.phone_pages("+5.00", credits=title))
    [item] = [item for item in run.record["items"] if item["description"] == "Autopay Discount"]
    assert item["line_total_minor"] == 500 and (item["line_type"] or item["line_kind"]) != "credit"
    assert sum(item["line_total_minor"] for item in run.record["items"]) == 12850
    finished(run)


# === SC-110 steps 5 and 6: the product on the printed rate; the half-up boundary =============================================

def test_sc110_the_product_checks_run_on_the_printed_quantity_and_rate_never_on_the_rounded_cents(pdf_store, local_model):
    from home_manager.finance import traces
    run = util(pdf_store, local_model)
    record = run.record
    checks = {check["name"]: check for check in record["checks"]}
    assert checks["product:1"]["passes"] and checks["product:2"]["passes"] and "product:3" not in checks and "product:4" not in checks
    assert (checks["product:1"]["figure"]["minor"], checks["product:2"]["figure"]["minor"]) == (6000, 2002)  # 140 × 0.1430, not 140 × 0.14 = 1960.
    receipt_id = run.run["publication"]["id"]
    trace = traces.trace(run.store, f"bill.product?receipt_id={receipt_id}&position=2", None)
    assert trace["reconciles"] is True
    inputs = {entry["label"]: entry for entry in trace["inputs"]}
    assert (inputs["Quantity"]["value"], inputs["Unit price"]["value"]) == ("140 kWh", "0.1430") or (
        "140 kWh" in json.dumps(trace) and "0.1430" in json.dumps(trace))
    assert "1960" not in json.dumps(trace) and "19.60" not in json.dumps(trace)


HALF = [("UTIL-HALF", bf.util_half_pages, {"Energy Tier 2": ("Energy Tier 2", "usage", "utilities", None, "21.30", "150 kWh", "0.1500")}, 15, "0.1450", 2030, 9783),
        ("UTIL-15", bf.util_15_pages, {"Energy Tier 2": ("Energy Tier 2", "usage", "utilities", None, "22.00", "150 kWh", "0.1600")}, 15, None, 2100, 9853),
        ("UTIL-125", bf.util_125_pages, {"Energy Tier 2": ("Energy Tier 2", "usage", "utilities", None, "18.50", "150 kWh", "0.1300")}, 13, "0.125", 1750, 9503)]


@pytest.mark.parametrize("name,pages,tier2,minor,text,line,total", HALF, ids=[entry[0] for entry in HALF])
def test_sc110_a_rate_is_rounded_half_up_and_kept_as_printed_only_when_it_is_not_whole_cents(pdf_store, local_model, name, pages, tier2, minor, text, line, total):
    run = util(pdf_store, local_model, pages=pages(), rows={**bf.STUB_UTIL_WRONG, **tier2})
    record = run.record
    second = record["items"][1]
    assert (second["unit_price_minor"], second["line_total_minor"]) == (minor, line)
    assert ((second["details"] or {}).get("unit_price") or {}).get("text") == text
    assert (record["total_minor"], record["amount_due_minor"]) == (total, total)
    assert [issue for issue in record["issues"] if "Amount has more precision" in issue or issue.startswith("Charge line")] == []
    checks = {check["name"]: check for check in record["checks"]}
    assert checks["product:2"]["passes"]
    auto(record)
    finished(run)


def test_sc110_a_rate_printed_with_more_decimals_shows_as_printed_from_the_server_until_you_correct_it(pdf_store, local_model):
    run = util(pdf_store, local_model)
    record = run.record
    assert record["items"][1]["display"]["unit_price_minor"] == "0.1430"  # The text the page shows (it does no money arithmetic).
    assert record["items"][0]["display"]["unit_price_minor"] == "0.12 USD"  # A whole number of cents is today's display.
    receipt_id = run.run["publication"]["id"]
    Ledger(run.store).correct_item_fields(receipt_id, 2, {"unit_price": "0.15"})
    assert run.record["items"][1]["display"]["unit_price_minor"] == "0.15 USD"  # Your correction shows as today, not 0.1430.


# === SC-111: summary amounts from the print, on a general bill =============================================================

def test_sc111_a_general_bill_keeps_its_previous_balance_and_payments_from_the_box_lines(pdf_store, local_model):
    run = util(pdf_store, local_model)
    record = run.record
    details = run.record["details"]
    assert (details["previous_balance"]["minor"], details["payments_received"]["minor"], details["new_charges"]["minor"]) == (8210, 8210, 9755)
    assert record["amount_due_minor"] == 9755
    assert {check["name"]: check["passes"] for check in record["checks"]}["carried"] is True
    # Each cites the printed amount's own line (the box's), with the amount word as its quote.
    assert details["previous_balance"]["locator"] == {"line_ids": [run.line("82.10").id], "quotes": ["82.10"]}
    assert details["payments_received"]["locator"]["quotes"] == ["-82.10"]
    carried = record["bill_summary"]["carried"]
    assert [(entry["label"], entry["display"]) for entry in carried] == [("Previous balance", "82.10 USD"), ("Payment received", "-82.10 USD")]
    assert record["bill_summary"]["earlier_balance"] is None and record["bill_summary"]["gap"] is None
    assert record["bill_summary"]["amount_due"]["display"] == "97.55 USD"
    assert run.run["result"]["summary_cell_evidence"]["amount_due"]["quote"] == "97.55"  # The cell Find lights.
    auto(record)
    finished(run)


# --- SC-111 step 4: a kind printed twice with different values (FR-111; slice SL-04) ---------------------------------------------------

def previous_twice(first, second):
    """BL-UTIL printing `Previous Balance` twice: `first` in the box and `second` on its own line at y 476, below the charge table."""
    summary = [("Previous Balance", first), *bf.UTIL_SUMMARY[1:]]
    return [bf.page_of(bf.util_items(summary=summary, extra=bf.amounts_at(476, "Previous Balance", (bf.CHARGE, second))))]


def test_sc111_sl04_a_previous_balance_printed_twice_takes_the_first_on_page_one_with_a_note_and_the_check_judges_it(pdf_store, local_model):
    run = util(pdf_store, local_model, previous_twice("82.10", "90.00"))
    record = run.record
    assert record["details"]["previous_balance"]["minor"] == 8210
    assert record["details"]["previous_balance"]["locator"]["quotes"] == ["82.10"]
    noted(run, "The previous balance is printed as 82.10 and 90.00;", "82.10, the first on page 1, was used.")
    assert {check["name"]: check["passes"] for check in record["checks"]}["carried"] is True  # The carried check runs on 82.10 and holds.
    auto(record)
    finished(run)


def test_sc111_sl04_a_misprint_listed_first_is_used_and_the_carried_check_fails_for_it(pdf_store, local_model):
    run = util(pdf_store, local_model, previous_twice("90.00", "82.10"))
    record = run.record
    assert record["details"]["previous_balance"]["minor"] == 9000
    assert [note for note in run.notes if "The previous balance is printed as 90.00 and 82.10; 90.00, the first on page 1, was used." in note]
    assert {check["name"]: check["passes"] for check in record["checks"]}["carried"] is False  # No check chooses among the values.
    reasons(record, "Amount due: previous balance 90.00 USD", "97.55 USD")
    finished(run)


def test_sc111_sl04_a_value_printed_alike_twice_is_one_value_and_gets_no_note(pdf_store, local_model):
    run = util(pdf_store, local_model, previous_twice("82.10", "82.10"))
    assert run.record["details"]["previous_balance"]["minor"] == 8210
    assert [note for note in run.notes if "is printed as" in note] == []
    auto(run.record)
    finished(run)


# === SC-117: amount due printed several times (FR-117; slice SL-04) ========================================================

def r1_run(pdf_store, local_model, variant, due="50.00", pages=None):
    """BL-UTIL-R1 (a), (b) or (c) with the stub answering the amount due 50.00 (printed in the page's past-due banner, so it passes its citation check)."""
    fields = {**UTIL_FIELDS, "amount_due": (due, due, due), "new_charges": ("60.00", "60.00", "60.00")}
    changes = {"new_charges": MISSING} if variant == "b" else {}  # (b) prints no new charges and the model gives none: the lines' sum counts.
    return bill_run(pdf_store, local_model, pages if pages is not None else bf.util_r1_pages(variant), bf.STUB_UTIL_WRONG, fields, **changes)


def guesses_of(run):
    return (run.record["details"] or {}).get("guesses", [])


def test_sc117_a_the_carried_check_picks_147_55_over_a_first_printed_50_00(pdf_store, local_model):
    run = r1_run(pdf_store, local_model, "a")
    record = run.record
    assert record["amount_due_minor"] == 14755 and record["total_minor"] == 9755
    assert [note for note in run.notes if "The amount due is printed as" in note] == [] and guesses_of(run) == []
    checks = {check["name"]: check["passes"] for check in record["checks"]}
    assert checks["carried"] is True and checks["lines"] is True
    auto(record)
    finished(run)


def test_sc117_b_the_lines_check_picks_97_55_when_no_new_charges_are_printed(pdf_store, local_model):
    run = r1_run(pdf_store, local_model, "b")
    record = run.record
    assert record["amount_due_minor"] == 9755 and record["total_minor"] == 9755  # The lines' sum counts: no new charges are printed.
    assert [note for note in run.notes if "The amount due is printed as" in note] == [] and guesses_of(run) == []
    assert {check["name"]: check["passes"] for check in record["checks"]} == {"lines": True, "product:1": True, "product:2": True}  # Against the amount due.
    auto(record)
    finished(run)


def test_sc117_c_nothing_decides_so_the_first_on_page_one_is_used_with_a_guess_note(pdf_store, local_model):
    run = r1_run(pdf_store, local_model, "c")
    record = run.record
    assert record["amount_due_minor"] == 5000 and record["total_minor"] == 9755
    noted(run, "The amount due is printed as 50.00 and 147.55; 50.00, the first on page 1, was used.")
    assert [(guess["kind"], guess["page"]) for guess in guesses_of(run)] == [("amount_due", 1)]
    assert [check["name"] for check in record["checks"] if check["name"] == "carried"] == []  # No check involves the amount due.
    auto(record)
    finished(run)


def test_sc117_a_late_payment_amount_is_never_the_amount_due(pdf_store, local_model):
    late = [*bf.left(216, "If paid after 10/15/2026, pay"), *bf.heading(216, (bf.CHARGE, "102.55"))]
    first = bf.amounts_at(720, "Balance Due", (bf.CHARGE, "50.00"))
    page = bf.page_of(bf.util_items(summary=[bf.UTIL_SUMMARY[2], ("Total Amount Due", "147.55")], stub_amount="147.55", above=first, extra=late))
    run = r1_run(pdf_store, local_model, "c", pages=[page])
    assert run.record["amount_due_minor"] == 5000
    assert not [text for text in [*run.notes, *run.record["issues"], *(guess["text"] for guess in guesses_of(run))] if "102.55" in text]
    finished(run)


# === SC-118: new charges worked out (FR-118; slice SL-04) ===================================================================

def r2_run(pdf_store, local_model, variant, **changes):
    """BL-UTIL-R2 or a variant, the stub answering the amount due and the new charges wrong but printed (150.00 and 100.00)."""
    wrong = ("12.00", "12.00", "12.00") if variant == "noprev" else None  # R2-NOPREV prints neither 150.00 nor 100.00.
    fields = {**UTIL_FIELDS, "amount_due": wrong or ("150.00", "150.00", "150.00"), "new_charges": wrong or ("100.00", "100.00", "100.00")}
    return bill_run(pdf_store, local_model, bf.util_r2_pages(variant), bf.STUB_UTIL_WRONG, fields, **changes)


def counted(run, minor):
    """Spending on the bill's due date (2026-10-15), from the same tool the page uses."""
    from home_manager.finance.tools import FinanceTools, PeriodInput
    rows = FinanceTools(run.store).get_spending(PeriodInput(start="2026-10-01", end="2026-10-31"))["by_currency"]
    assert rows and rows[0]["spending"]["minor"] == minor


def test_sc118_new_charges_not_printed_are_worked_out_and_that_is_what_counts_with_no_carried_check(pdf_store, local_model):
    from home_manager.finance import traces
    run = r2_run(pdf_store, local_model, "r2")
    record = run.record
    assert (record["total_minor"], record["amount_due_minor"]) == (9755, 14755)
    details = record["details"]
    assert (details["previous_balance"]["minor"], details["payments_received"]["minor"], details["new_charges"]["minor"]) == (15000, 10000, 9755)
    assert details["new_charges"]["worked_out"] == {"amount_due": 14755, "previous_balance": 15000, "payments": 10000}  # The model's 100.00 is not used.
    noted(run, "New charges aren't printed; worked out as amount due 147.55", "previous balance 150.00", "payments 100.00", "= 97.55.")
    checks = {check["name"]: check for check in record["checks"]}
    assert checks["lines"]["passes"] is True and "carried" not in checks
    assert checks["lines"]["compared_with"]["minor"] == 9755
    trace = traces.trace(run.store, checks["lines"]["figure"]["trace"])
    assert {item["key"]: item["value"]["decimal"] for item in trace["inputs"] if item["key"] in ("amount_due", "previous_balance", "payments_received")} == {
        "amount_due": "147.55", "previous_balance": "150.00", "payments_received": "100.00"}
    assert "147.55 \u2212 previous balance 150.00 + payments 100.00 = 97.55" in trace["formula"]
    assert trace["reconciles"] is True
    auto(record)
    counted(run, 9755)
    finished(run)


def test_sc118_a_misprinted_amount_due_works_out_a_wrong_new_charges_the_lines_check_catches(pdf_store, local_model):
    run = r2_run(pdf_store, local_model, "bad")
    record = run.record
    assert (record["total_minor"], record["amount_due_minor"]) == (10055, 15055)  # The worked-out value counts until corrected.
    noted(run, "New charges aren't printed; worked out as amount due 150.55", "payments 100.00", "= 100.55.")
    reasons(record, "the lines add up to 97.55 USD", "100.55 USD")
    assert "carried" not in {check["name"] for check in record["checks"]}
    Ledger(run.store).review("receipt", record["id"], "verified")  # The bill waits in To check; once you keep it, it counts the worked-out 100.55.
    counted(run, 10055)
    finished(run)


def test_sc118_without_a_previous_balance_and_payments_todays_rule_stands(pdf_store, local_model):
    run = r2_run(pdf_store, local_model, "noprev", new_charges=MISSING)
    record = run.record
    assert (record["total_minor"], record["amount_due_minor"]) == (9755, 14755)
    reasons(record, "Amount due: the lines add up to 97.55 USD, but the amount due is 147.55 USD")
    assert [note for note in run.notes if "worked out" in note] == []
    assert "worked_out" not in ((record["details"] or {}).get("new_charges") or {})
    finished(run)


# === SC-121: version and existing records (slice SL-04: cases (1) and (2)) ===============================================

def read_as_v39(run, rows_of, fields, monkeypatch):
    """The reading the previous version left: the engine fault double (the model's lines are used) with the version patched, left in To check by SQL."""
    def fault(evidence, firsts=None):
        raise RuntimeError("injected engine fault")
    run.stub_bill({}, fields, extra=rows_of, single_run=True)
    with monkeypatch.context() as patch:
        patch.setattr(extraction, "EXTRACTION_VERSION", V39)
        patch.setattr(bill_tables, "read", fault)
        run.extract()
    assert run.run["status"] == "succeeded"
    with run.store.connection() as db:
        assert db.execute("SELECT prompt_version FROM extraction_runs WHERE id=?", (run.run["id"],)).fetchone()[0] == V39


def model_rows(run):
    return [{**run.model_line(key, bf.STUB_UTIL[key]), "evidence": [{"line_id": run.line(text).id, "quote": run.line(text).text} for text in cites]}
            for key, cites in UTIL_CITES.items()]


def test_sc121_the_version_moved_and_an_undecided_v39_bill_is_read_again_from_its_printed_columns(pdf_store, local_model, monkeypatch):
    assert extraction.EXTRACTION_VERSION != V39
    run = started(pdf_store, local_model, bf.util_pages())
    run.__class__ = BillRun
    read_as_v39(run, model_rows(run), {**UTIL_FIELDS, "amount_due": ("97.55", "97.55", "97.55"), "new_charges": ("97.55", "97.55", "97.55")}, monkeypatch)
    receipt_id = run.run["publication"]["id"]
    with run.store.connection() as db:
        db.execute("UPDATE receipts SET review_status='needs_review' WHERE id=?", (receipt_id,))
    run.stub_bill(bf.STUB_UTIL_WRONG, {**UTIL_FIELDS, **UTIL_WRONG_AMOUNTS})
    config = ReasoningConfig(base_url=run.local_model["config"].base_url, model="synthetic-reasoning")
    run_id, reused = run.extraction.enqueue(run.doc["id"], run.parse_id, config)
    assert reused is True  # `reused` False in the contract: enqueue made a new run, since the previous version's run is not reused.
    run.extraction.run(run_id, Work.detached())
    run.run = run.extraction.get(run_id)
    assert run.run["status"] == "succeeded" and run.run["publication"]["id"] == receipt_id
    expect_util(run)
    finished(run)


def test_sc121_a_decided_bill_keeps_its_receipt_and_item_rows_byte_for_byte(pdf_store, local_model, monkeypatch):
    run = started(pdf_store, local_model, bf.util_r1_pages("a"))
    run.__class__ = BillRun
    read_as_v39(run, model_rows(run), {**UTIL_FIELDS, "amount_due": ("147.55", "147.55", "147.55"), "new_charges": ("97.55", "97.55", "97.55")}, monkeypatch)
    receipt_id = run.run["publication"]["id"]
    Ledger(run.store).review("receipt", receipt_id, "verified")

    def rows():
        with run.store.connection() as db:
            return ([tuple(row) for row in db.execute("SELECT * FROM receipts WHERE id=?", (receipt_id,))],
                    [tuple(row) for row in db.execute("SELECT * FROM receipt_items WHERE receipt_id=? ORDER BY position", (receipt_id,))])
    before = rows()
    run.stub_bill(bf.STUB_UTIL_WRONG, {**UTIL_FIELDS, "amount_due": ("50.00", "50.00", "50.00"), "new_charges": ("60.00", "60.00", "60.00")})
    config = ReasoningConfig(base_url=run.local_model["config"].base_url, model="synthetic-reasoning")
    run_id, reused = run.extraction.enqueue(run.doc["id"], run.parse_id, config)
    assert reused is True
    run.extraction.run(run_id, Work.detached())
    assert run.extraction.get(run_id)["status"] == "succeeded"
    assert rows() == before
    finished(run)


def test_sc121_no_migration_is_added_by_this_feature():
    """The `library/migrations/` listing is START_HEAD's: 001 to 080, with 080_split_merged_documents the last: this feature adds none."""
    names = sorted(path.name for path in (Path(home_manager.library.__file__).parent / "migrations").iterdir() if path.suffix == ".sql")
    assert len(names) == 80 and names[0].startswith("001_") and names[-1] == "080_split_merged_documents.sql"
    assert [int(name[:3]) for name in names] == list(range(1, 81))


# === SC-112: matching model lines to engine rows ============================================================================

def total_line(run, text="Total for Alex", amount="79.99", **changes):
    return {"description": text, "amount": amount, "quantity": None, "unit_price": None, "category": None, "line_kind": "other", "line_holder": None,
            "evidence": run.cite(text), **changes}


def phone_without_device(pdf_store, local_model, extra):
    rows = {label: row for label, row in bf.STUB_PHONE.items() if label != "Device Payment"}
    run = started(pdf_store, local_model, bf.phone_pages())
    run.__class__ = BillRun
    run.stub_bill(rows, PHONE_FIELDS, classify="METRO WIRELESS", extra=list(extra(run)))
    run.extract()
    return run


def test_sc112_a_printed_row_no_model_line_took_is_added_as_other_and_a_printed_total_is_left_out(pdf_store, local_model):
    run = phone_without_device(pdf_store, local_model, lambda run: [total_line(run)])
    record = run.record
    expected = [(label, minor, "other" if label == "Device Payment" else kind) for label, minor, kind in bf.EXP_PHONE_LINES]
    assert lines_of(record) == expected
    device = record["items"][1]
    assert (device["description"], device["category"], device["line_holder"]) == ("Device Payment", None, "Alex 555-201-1111")
    assert run.line("Alex 555-201-1111").id in device["line_ids"]
    noted(run, "Total for Alex", "printed total")
    noted(run, "Device Payment")
    assert sum(item["line_total_minor"] for item in record["items"]) == 11850
    auto(record)
    no_feature_review(record)
    guesses = run.record["details"]["guesses"]
    assert [guess["kind"] for guess in guesses] == ["unclassified_row"] and "Device Payment" in guesses[0]["text"]
    finished(run)


def test_sc112_b_two_model_lines_on_one_printed_row_keep_the_first(pdf_store, local_model):
    run = started(pdf_store, local_model, bf.phone_pages())
    run.__class__ = BillRun
    again = run.model_line("Basic Plan", bf.STUB_PHONE["Basic Plan"])
    run.stub_bill(bf.STUB_PHONE, PHONE_FIELDS, classify="METRO WIRELESS", extra=[{**again, "description": "Basic Plan again"}])
    run.extract()
    record = run.record
    assert lines_of(record) == bf.EXP_PHONE_LINES
    noted(run, "Basic Plan")
    assert [note for note in run.notes if "Two lines were read" in note]
    auto(record)


def test_sc112_c_a_model_line_citing_no_printed_row_keeps_nothing_the_print_does_not_hold(pdf_store, local_model):
    run = started(pdf_store, local_model, bf.phone_pages())
    run.__class__ = BillRun
    waived = {"description": "Late fee waived", "amount": "3.00", "quantity": None, "unit_price": None, "category": None, "line_kind": "other",
              "line_holder": None, "evidence": run.cite("Account Credits")}
    run.stub_bill(bf.STUB_PHONE, PHONE_FIELDS, classify="METRO WIRELESS", extra=[waived])
    run.extract()
    assert lines_of(run.record) == bf.EXP_PHONE_LINES
    noted(run, "Late fee waived")
    auto(run.record)


# === SC-113: checks keep today's effect ====================================================================================

def test_sc113_a_printed_subtotal_that_is_not_its_lines_is_a_note_and_the_bill_still_counts(pdf_store, local_model):
    pages = bf.phone_pages()
    pages[0]["items"] = [(x, y, "44.51" if text == "43.51" else text) for x, y, text in pages[0]["items"]]
    run = phone(pdf_store, local_model, pages=pages)
    record = run.record
    assert lines_of(record) == bf.EXP_PHONE_LINES
    noted(run, "Page 1", "44.51")
    auto(record)


def test_sc113_new_charges_that_are_not_the_lines_are_a_review_reason_as_before(pdf_store, local_model):
    run = bill_run(pdf_store, local_model, bf.util_misnc_pages(), bf.STUB_UTIL, {**UTIL_FIELDS, **UTIL_WRONG_AMOUNTS})
    record = run.record
    assert lines_of(record) == bf.EXP_UTIL_LINES
    assert record["total_minor"] == 9955
    assert len(record["issues"]) == 2
    reasons(record, "New charges: the lines add up to 97.55 USD", "99.55 USD")
    reasons(record, "Amount due: previous balance 82.10 USD less payments 82.10 USD plus new charges 99.55 USD is 99.55 USD, but the amount due is 97.55 USD")
    no_feature_review(record)
    not_anchoring(run)


# === SC-114: a page with no charge table ===================================================================================

def test_sc114_a_page_with_no_charge_table_keeps_the_models_line_and_says_so(pdf_store, local_model):
    run = started(pdf_store, local_model, bf.util_2p_pages())
    run.__class__ = BillRun
    fee = {"description": "Paper Bill Fee", "amount": "2.00", "quantity": None, "unit_price": None, "category": None, "line_kind": "tax_fee",
           "line_holder": None, "evidence": run.cite("Your paper bill fee")}
    fields = {**UTIL_FIELDS, "amount_due": ("99.55", "Amount Due", "99.55"), "new_charges": ("99.55", "99.55", "99.55")}
    run.stub_bill(bf.STUB_UTIL_WRONG, fields, extra=[fee])
    run.extract()
    record = run.record
    assert lines_of(record) == [*bf.EXP_UTIL_LINES, ("Paper Bill Fee", 200, "tax_fee")]
    assert (record["total_minor"], record["amount_due_minor"]) == (9955, 9955)
    noted(run, "Page 2: no charge table was found in the printed columns, so its amounts are the reading's; check them.")
    assert {check["name"]: check["passes"] for check in record["checks"]}["lines"] and {check["name"]: check["passes"] for check in record["checks"]}["carried"]
    # The reader's `unresolved_columns` note on page 2 is waived (FR-114: its printed grids are dropped), so the bill is C-auto.
    assert run.evidence.pages[1].layout.issues == ["unresolved_columns"]  # P-check: the reading does carry it.
    auto(record)
    no_feature_review(record)
    finished(run)


def test_sc114_a_text_page_with_no_charge_table_and_another_layout_issue_still_needs_review(pdf_store, local_model, monkeypatch):
    run = started(pdf_store, local_model, bf.util_2p_pages())
    run.__class__ = BillRun
    note = "Page 2 PDF layout needs review: unresolved_columns, glyph_outside_page."
    original = extraction.read_result

    def with_issue(value):
        result = original(value)
        result.pages[1].layout.issues = ["unresolved_columns", "glyph_outside_page"]
        [issue] = [issue for issue in result.issues if issue.message.startswith("Page 2 ")]
        issue.message = note
        return result
    monkeypatch.setattr(extraction, "read_result", with_issue)
    fee = {"description": "Paper Bill Fee", "amount": "2.00", "quantity": None, "unit_price": None, "category": None, "line_kind": "tax_fee",
           "line_holder": None, "evidence": run.cite("Your paper bill fee")}
    run.stub_bill(bf.STUB_UTIL_WRONG, {**UTIL_FIELDS, "amount_due": ("99.55", "Amount Due", "99.55"), "new_charges": ("99.55", "99.55", "99.55")}, extra=[fee])
    run.extract()
    reasons(run.record, note)
    assert not [issue for issue in run.record["issues"] if "Page 1" in issue]


def test_sc114_a_pay_stub_page_without_an_engine_table_keeps_its_layout_note():
    """The widening is the bill's: a pay stub (no text_pages) waives `unresolved_columns` only on a page its engine read a table on."""
    page = SimpleNamespace(number=1, layout=SimpleNamespace(issues=["unresolved_columns"]))
    evidence = SimpleNamespace(pages=[page], issues=[SimpleNamespace(code="pdf_layout_review", message="Page 1 PDF layout needs review: unresolved_columns.")])
    lines = [SimpleNamespace(id="page-1-layout-line-1")]
    pay = SimpleNamespace(engine_pages=set(), line_pages={1})
    assert extraction.pay_layout_notes(evidence, pay, lines) == ["Page 1 PDF layout needs review: unresolved_columns."]
    assert extraction.pay_layout_notes(evidence, SimpleNamespace(engine_pages={1}, line_pages={1}), lines) == []
    assert extraction.pay_layout_notes(evidence, pay, lines, {1}) == []  # a bill's text page


def test_sc114_a_reading_saved_without_layout_is_read_like_a_photographed_bill(pdf_store, local_model, monkeypatch):
    run = started(pdf_store, local_model, bf.util_pages())
    run.__class__ = BillRun
    original = extraction.read_result

    def without_layout(value):
        result = original(value)
        for page in result.pages:
            page.layout = None
        return result
    monkeypatch.setattr(extraction, "read_result", without_layout)
    run.evidence = without_layout(run.service.get(run.parse_id)["result"])
    run.lines = [line for line in extraction.evidence_lines(run.evidence)]
    keys = ("Energy Tier 1", "Energy Tier 2", "Customer Charge", "State Tax")
    rows = {key: run.model_line(key, bf.STUB_UTIL[key]) for key in keys}
    for key, row in rows.items():  # The plain transcription holds the whole row in one line, so the model's amounts are printed where it cites.
        assert row["amount"] in row["evidence"][0]["quote"], key
    run.stub_bill({}, {**UTIL_FIELDS, "amount_due": ("97.55", "Total Amount Due", "97.55"), "new_charges": ("97.55", "New Charges", "97.55")}, extra=list(rows.values()))
    run.local_model["by_schema"]["BillLines"] = [{"line_items": list(rows.values())}]
    run.extract()
    assert [(item["description"], item["line_total_minor"]) for item in run.record["items"]] == [(label, minor) for label, minor, _ in bf.EXP_UTIL_LINES]
    assert not [note for note in run.notes if note.startswith("Page ")]  # No page note: the reading has no layout to read.
    no_grid(run)


# === SC-115: engine failure ===================================================================================================

UTIL_CITES = {"Energy Tier 1": ("Energy Tier 1", "500 kWh 0.1200", "60.00"), "Energy Tier 2": ("Energy Tier 2", "140 kWh 0.1430", "20.02"),
              "Customer Charge": ("Customer Charge", "12.00"), "State Tax": ("State Tax", "5.53")}


def test_sc115_when_the_engine_fails_the_bill_is_read_from_the_models_lines_with_a_note_and_one_log_record(pdf_store, local_model, monkeypatch, caplog):
    run = started(pdf_store, local_model, bf.util_pages())
    run.__class__ = BillRun
    # The model's lines cite each row's label, quantity and rate, and amount lines, so each amount is printed where it is cited.
    rows = [{**run.model_line(key, bf.STUB_UTIL[key]), "evidence": [{"line_id": run.line(text).id, "quote": run.line(text).text} for text in cites]}
            for key, cites in UTIL_CITES.items()]
    run.stub_bill({}, {**UTIL_FIELDS, "amount_due": ("97.55", "97.55", "97.55"), "new_charges": ("97.55", "97.55", "97.55")}, extra=rows, single_run=True)

    def fault(evidence, firsts=None):
        raise RuntimeError("injected engine fault")
    monkeypatch.setattr(bill_tables, "read", fault)
    with caplog.at_level(logging.ERROR):
        run.extract()
    record = run.record
    assert [(item["description"], item["line_total_minor"]) for item in record["items"]] == [(label, minor) for label, minor, _ in bf.EXP_UTIL_LINES]
    noted(run, extraction.BILL_FAILED_NOTE)
    no_grid(run)
    failures = [entry for entry in caplog.records if "bill table read" in entry.getMessage()]
    assert len(failures) == 1 and "RuntimeError" in failures[0].getMessage()
    assert not [entry for entry in caplog.records if any(word in entry.getMessage() for word in ("CITY", "Energy", "97.55"))]
    assert run.run["status"] == "succeeded"


# === SC-116: evidence lights the printed words ===============================================================================

def test_sc116_a_line_cites_all_its_printed_lines_in_order_and_its_amount_lights_its_printed_word(pdf_store, local_model):
    run = phone(pdf_store, local_model)
    international = run.record["items"][3]
    assert international["line_ids"][:2] == [run.line("International Pack").id, run.line("(Canada and Mexico)").id]
    assert international["cell_evidence"]["amount"]["quote"] == "8.51" and international["cell_evidence"]["amount"]["word_ids"]


def test_sc116_the_amount_due_cites_the_first_amount_due_word_and_the_quantity_and_rate_cite_their_own_words(pdf_store, local_model):
    from home_manager.finance.provenance import provenance_for
    run = util(pdf_store, local_model)
    record = run.record
    with run.store.connection() as db:
        found = provenance_for(db, "receipt", record["id"], "amount_due")["provenance"]["document"]
    box = [line for line in run.lines if line.text == "97.55"][1]  # The box prints 82.10, -82.10, then the new charges and the amount due, both 97.55.
    assert found["lines"] == [box.id] and found["quote"] == "97.55"
    assert found["cells"][0]["word_ids"] and found["cells"][0]["quote"] == "97.55"
    cells = record["items"][0]["cell_evidence"]
    assert cells["quantity"]["quote"].startswith("500") and cells["unit_price"]["quote"] == "0.1200" and cells["amount"]["quote"] == "60.00"
    assert cells["quantity"]["word_ids"] and cells["unit_price"]["word_ids"]


# === SC-122: determinism ======================================================================================================

SNAPSHOT = {"receipts": "SELECT * FROM receipts ORDER BY id", "receipt_items": "SELECT * FROM receipt_items ORDER BY receipt_id,position",
            "record_corrections": "SELECT * FROM record_corrections ORDER BY id",
            "financial_evidence_links": "SELECT record_type,record_id,document_id,blob_hash,locator_json FROM financial_evidence_links ORDER BY record_type,record_id,id",
            "document_segments": "SELECT ordinal,first_line_id,last_line_id,status,source FROM document_segments ORDER BY ordinal"}


def snapshot(run):
    """The rows a reading wrote, without the clock and without the run's own id (a reading again replaces its links)."""
    with run.store.connection() as db:
        found = {name: [dict(row) for row in db.execute(sql)] for name, sql in SNAPSHOT.items()}
    for rows in found.values():
        for row in rows:
            for key in ("updated_at", "created_at", "extraction_run_id", "parse_run_id", "source_key"):
                row.pop(key, None)
    return found


def test_sc122_a_second_reading_of_a_bill_with_an_unplaced_line_changes_nothing(pdf_store, local_model):
    run = started(pdf_store, local_model, bf.util_stray_pages())
    run.__class__ = BillRun
    fields = {**UTIL_FIELDS, **UTIL_WRONG_AMOUNTS}
    run.stub_bill(bf.STUB_UTIL_WRONG, fields)
    first_run = run.extract()
    first = snapshot(run)
    first_notes, first_questions = run.notes, run.asked()
    first_engine = json.dumps(dataclasses.asdict(ENGINE(run.evidence).reading), sort_keys=True, default=str)
    assert first_engine == json.dumps(dataclasses.asdict(ENGINE(run.evidence).reading), sort_keys=True, default=str)  # Engine reads are equal.
    run.stub_bill(bf.STUB_UTIL_WRONG, fields)
    second_run = run.extract(force=True)
    assert second_run["id"] != first_run["id"]
    assert snapshot(run) == first
    assert run.notes == first_notes and run.asked() == first_questions  # The same schemas, in the same count (C-model-calls).
    finished(run)


def test_sc122_sl04_a_second_reading_of_a_bill_with_an_amount_due_guess_changes_nothing(pdf_store, local_model):
    run = started(pdf_store, local_model, bf.util_r1_pages("c"))
    run.__class__ = BillRun
    fields = {**UTIL_FIELDS, "amount_due": ("50.00", "50.00", "50.00"), "new_charges": ("60.00", "60.00", "60.00")}
    run.stub_bill(bf.STUB_UTIL_WRONG, fields)
    first_run = run.extract()
    first = snapshot(run)
    first_notes, first_questions, first_guesses = run.notes, run.asked(), guesses_of(run)
    assert [guess["kind"] for guess in first_guesses] == ["amount_due"]
    run.stub_bill(bf.STUB_UTIL_WRONG, fields)
    second_run = run.extract(force=True)
    assert second_run["id"] != first_run["id"]
    assert snapshot(run) == first
    assert (run.notes, run.asked(), guesses_of(run)) == (first_notes, first_questions, first_guesses)
    finished(run)


# === The scanned one-bill regression (plan P7.1) =============================================================================

def started_scanned(pdf_store, local_model, transcription):
    """A one-page scanned PDF (image only) whose vision stub transcribes `transcription`: no text page, so the bill engine never runs."""
    from conftest import inbox_scan
    from home_manager.core.jobs import Work
    from home_manager.documents.receipt_service import ReceiptService
    from test_pdf import make_pdf
    inbox, store = pdf_store
    make_pdf(inbox / "scan.pdf", [None])
    inbox_scan(store)
    doc = next(item for item in store.documents()["items"] if item["relative_path"].endswith("scan.pdf"))
    local_model["output"] = {"full_text": "\n".join(transcription)}
    service = ReceiptService(store)
    parse_id, _ = service.enqueue(doc["id"], vision=local_model["config"])
    service.run(parse_id, Work.detached())
    assert service.get(parse_id)["status"] == "succeeded", service.get(parse_id)["error"]
    assert [page["method"] for page in service.get(parse_id)["result"]["pages"]] == ["vision_model"]
    run = BillRun(store, service, local_model, parse_id, doc)
    return run


def scanned_stub(run, amount="12.00"):
    """The model's answers for MULTI-SCAN's page 1 alone: the lines and the summary with the printed amounts."""
    fields = {"provider": ("CITY POWER & WATER", "CITY POWER & WATER", "CITY POWER & WATER"), "account_reference": ("9012", "Account Number", "1234-5678-9012"),
              "issue_date": ("2026-07-02", "Statement Date", "07/02/2026"), "due_date": ("2026-07-20", "Due Date", "07/20/2026"),
              "period_start": ("2026-06-01", "Billing Period", "06/01/2026"), "period_end": ("2026-06-30", "Billing Period", "06/30/2026"),
              "amount_due": ("81.42", "Total Amount Due", "81.42"), "new_charges": ("81.42", "New Charges", "81.42"), "currency": ("USD", "Account Number", "9012")}
    rows = [{"description": label, "amount": value, "quantity": None, "unit_price": None, "category": "utilities", "line_kind": kind, "line_holder": None,
             "evidence": run.cite(label)}
            for label, value, kind in (("Customer Charge", amount, "service"), ("Energy Charge", "64.80", "usage"), ("State Tax", "4.62", "tax_fee"))]
    header = run.header(fields)
    run.local_model["by_schema"] = {"Classification": [{"document_type": "bill", "evidence": run.cite("CITY POWER"), "issuer": header["provider"],
                                                        "document_date": MISSING, "bill_kind": "general", "bill_kind_evidence": []}],
                                    "BillSummary": [header], "BillLines": [{"line_items": rows}]}
    run.before = len(run.local_model["requests"])


def test_scanned_one_bill_pdf_is_read_exactly_as_before_with_no_engine_and_its_amounts_checked_against_their_lines(pdf_store, local_model):
    run = started_scanned(pdf_store, local_model, bf.mini_transcription(1))
    scanned_stub(run)
    run.extract()
    record = run.record
    expected = bf.exp_mini(1)
    assert [(item["description"], item["line_total_minor"]) for item in record["items"]] == [(label, minor) for label, minor, _ in expected["lines"]]
    assert (record["total_minor"], record["amount_due_minor"], record["due_date"]) == (expected["total_minor"], expected["amount_due_minor"], expected["due_date"])
    questions = run.requests("BillLines")
    assert questions and all("reported_tables" not in question for question in questions)  # No charge table: the engine never ran.
    assert all("copies each amount" not in request["messages"][0]["content"] for request in run.local_model["requests"][run.before:])
    assert not [note for note in run.notes if note.startswith("Page ") or "charge lines couldn't be read" in note]
    assert (record["details"] or {}).get("guesses") is None


def test_scanned_one_bill_pdf_still_checks_a_models_amount_against_its_cited_line(pdf_store, local_model):
    from home_manager.core.jobs import Work
    run = started_scanned(pdf_store, local_model, bf.mini_transcription(1))
    scanned_stub(run, amount="13.00")  # Customer Charge 13.00 is not printed in the line it cites ("Customer Charge 12.00").
    run.local_model["by_schema"]["BillLines"] *= 2  # The correction asks again and is answered with the same wrong amount.
    from home_manager.documents.reasoning import ReasoningConfig
    config = ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning")
    run_id, _ = run.extraction.enqueue(run.doc["id"], run.parse_id, config)
    run.extraction.run(run_id, Work.detached())
    failed = run.extraction.get(run_id)
    assert failed["status"] == "failed" and "amount is not printed" in failed["error"]


# === A text-PDF invoice stays on today's path (D5, FR-120) ===================================================================

def test_invoice_a_text_pdf_invoice_is_read_again_on_todays_path_without_the_engine(pdf_store, local_model):
    run = started(pdf_store, local_model, bf.util_pages())
    run.__class__ = BillRun
    rows = {key: run.model_line(key, entry) for key, entry in bf.STUB_UTIL.items()}
    cites = {"Energy Tier 1": ("Energy Tier 1", "500 kWh 0.1200", "60.00"), "Energy Tier 2": ("Energy Tier 2", "140 kWh 0.1430", "20.02"),
             "Customer Charge": ("Customer Charge", "12.00"), "State Tax": ("State Tax", "5.53")}
    for key, row in rows.items():
        row["evidence"] = [{"line_id": run.line(text).id, "quote": run.line(text).text} for text in cites[key]]
        row["unit_price"] = row["quantity"] = None
    invoice = {"invoice_number": {"value": "INV-77", "status": "proposed", "evidence": run.cite("Account Number", "1234-5678-9012")}}
    # The invoice marker must be printed where it is cited: cite the digits of the account line as the "invoice number".
    invoice["invoice_number"]["value"] = "1234-5678-9012"
    header = run.header({**UTIL_FIELDS, "amount_due": ("97.55", "97.55", "97.55"), "new_charges": ("97.55", "97.55", "97.55")})
    run.local_model["by_schema"] = {"Classification": [{"document_type": "bill", "evidence": run.cite("CITY POWER"), "issuer": header["provider"],
                                                        "document_date": MISSING, "bill_kind": "general", "bill_kind_evidence": []}],
                                    "BillSummary": [{**header, **invoice}, {**header, **invoice}], "BillLines": [{"line_items": list(rows.values())}]}
    run.before = len(run.local_model["requests"])
    run.extract()
    assert run.asked().count("BillSummary") == 2  # One extra summary question, for the text-PDF invoice only (R-E).
    assert not [table for request in run.requests("BillLines") for table in request.get("reported_tables", []) if table["table_id"] == "page-1-charges-1"]
    assert run.record["bill_kind"] == "general" and run.record["invoice"] is not None


# === Review round 1, finding 3 (SL-11): an invoice with no engine charge table still takes the old path =====================

def invoice_items(*, table=True):
    """A text invoice whose Item / Qty / Unit price / Total table prints whole numbers only (100 and 200, no decimals): the bill engine finds no charge
    table in it, while the reader's printed table (the old path's native columns) holds the cells. A printed invoice number makes it an invoice."""
    items = [(40, 780 - 12 * number, text) for number, text in enumerate(("ACME SUPPLY CO", "Invoice Number INV-1001", "Due Date 10/15/2026", "Currency USD"))]
    if table:
        items += bf.heading(700, (330, "Qty"), (420, "Unit price"), (520, "Total")) + bf.left(700, "Item")
        items += bf.amounts_at(684, "Widget", (330, "1"), (420, "100"), (520, "100"))
        items += bf.amounts_at(668, "Gadget", (330, "1"), (420, "200"), (520, "200"))
    items += bf.amounts_at(640, "Total Due", (520, "300"))
    return items


def invoice_run(pdf_store, local_model):
    """The invoice read through the real services; the model answers each line's amount with its printed quantity (1), wrong on purpose."""
    run = started(pdf_store, local_model, [bf.page_of(invoice_items())], name="invoice.pdf")
    run.__class__ = BillRun
    header = run.header({"provider": ("ACME SUPPLY CO", "ACME SUPPLY CO", "ACME SUPPLY CO"), "due_date": ("2026-10-15", "Due Date", "10/15/2026"),
                         "currency": ("USD", "Currency", "USD")})
    header["invoice_number"] = {"value": "INV-1001", "status": "proposed", "evidence": run.cite("Invoice Number", "INV-1001")}
    entries = []
    for label in ("Widget", "Gadget"):
        line = run.line(label)
        entries.append({"description": label, "amount": "1", "quantity": "1", "unit_price": None, "category": "other", "line_holder": None, "line_kind": "other",
                        "evidence": [{"line_id": line.id, "quote": line.text}]})
    run.local_model["by_schema"] = {"Classification": [{"document_type": "bill", "evidence": run.cite("ACME SUPPLY CO"), "issuer": header["provider"],
                                                        "document_date": MISSING, "bill_kind": "general", "bill_kind_evidence": []}],
                                    "BillSummary": [header, header], "BillLines": [{"line_items": entries}, {"line_items": entries}]}
    run.before = len(run.local_model["requests"])
    return run


def invoice_amounts(run):
    return [(item["description"], item["line_total_minor"], item) for item in run.record["items"]]


def test_sl11_f3_an_invoice_with_no_engine_charge_table_is_read_again_on_todays_native_path(pdf_store, local_model):
    run = invoice_run(pdf_store, local_model)
    assert bill_tables.read(run.evidence).adapted == []  # The engine finds no charge table in whole numbers.
    run.extract()
    assert run.asked().count("BillSummary") == 2  # The engine path's question, then the invoice path's.
    assert run.record["invoice"] is not None
    amounts = invoice_amounts(run)
    assert [(name, minor) for name, minor, _ in amounts] == [("Widget", 10000), ("Gadget", 20000)]
    assert [item["cell_evidence"]["amount"]["quote"] for _, _, item in amounts] == ["100", "200"]  # Each amount is its printed cell, from the reader's table.
    assert all(item["cell_evidence"]["amount"]["source"] == "pdf_text" for _, _, item in amounts)
    assert BILL_FAILED_NOTE_TEXT not in [*run.notes, *(run.record.get("notes") or [])]


def test_sl11_f3_an_invoice_read_after_the_engine_failed_is_read_again_on_todays_native_path(pdf_store, local_model, monkeypatch):
    run = invoice_run(pdf_store, local_model)
    monkeypatch.setattr(extraction.bill_tables, "read", lambda evidence, firsts=None: (_ for _ in ()).throw(RuntimeError("synthetic engine failure")))
    run.extract()
    assert run.asked().count("BillSummary") == 2
    amounts = invoice_amounts(run)
    assert [(name, minor) for name, minor, _ in amounts] == [("Widget", 10000), ("Gadget", 20000)]
    assert [item["cell_evidence"]["amount"]["quote"] for _, _, item in amounts] == ["100", "200"]
    assert BILL_FAILED_NOTE_TEXT not in [*run.notes, *(run.record.get("notes") or [])]


# === Review round 1, finding 5 (SL-11): a bill's summary on another page decides the charge column ==========================

def test_sl11_f5_a_two_page_headless_table_with_a_comparison_column_stores_the_charge_column_when_the_summary_is_on_page_two(pdf_store, local_model):
    from test_bill_engine import other_page_summary_pages
    fields = {"provider": UTIL_FIELDS["provider"], "due_date": ("2026-07-20", "Due Date", "07/20/2026"), "currency": UTIL_FIELDS["currency"],
              "amount_due": ("30.00", "Amount Due", "30.00"), "new_charges": ("30.00", "New Charges", "30.00")}
    rows = {"Service": ("Service", "service", "utilities", None, "999.00", None, None), "Fee": ("Fee", "tax_fee", "utilities", None, "999.00", None, None)}
    run = bill_run(pdf_store, local_model, other_page_summary_pages(), rows, fields)
    assert [(item["description"], item["line_total_minor"]) for item in run.record["items"]] == [("Service", 1000), ("Fee", 2000)]  # Not 10000 / 20000.
    assert not [note for note in run.notes if "right-most" in note or "told apart" in note]
    assert (run.record["total_minor"], run.record["amount_due_minor"]) == (3000, 3000)
    finished(run)
