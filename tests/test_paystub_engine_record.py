"""Record uses the pay engine (specs/pdf-table-engine-paystubs/test-contract.md), slice SL-03: SC-50 to SC-55, SC-57 to SC-59, SC-63, SC-65, SC-66
(single stubs) and SC-69, plus the two extra tests the plan's SL-03 row names (PS-NH's reading carries `unresolved_columns` and its record has no
layout-review issue; a table-less page's swapped flat line is still nulled by `column_checks`). Slice SL-04 adds SC-56, SC-60, SC-61, SC-62 and SC-70
at Record level (the notes and guesses on the record, unclassified rows, the summary box), and a few tests of the rules the plan gives beyond the
contract's fixtures (a group guessed from the stub's totals or the line above, a totals line and the summary box disagreeing).

Every file goes through the real services as test_layout_consumers.py does: `make_pdf` into the Inbox, `capture`, `ReceiptService`, then
`ExtractionService` with the contract's doubles (`local_model` by schema). Expected values are the contract's literals in
tests/paystub_engine_fixtures.py, never what the code produced. The model stubs classify rows correctly and answer every amount swapped
(`STUB-PS-SWAPPED`), so a value that reaches the record from the model would be wrong everywhere.

The double answers each question with the entries whose cited line is in that question's lines (a question is one run of lines the engine covers
with rows, or one run it doesn't), so a fixture's chunking needs no hand-written order.

Not here (later slices): the viewer data (SC-71) and files of several stubs (SC-72 to SC-76).
"""

from collections import Counter
import hashlib
import json
import logging
import random
import re
import socket

import pytest

from conftest import inbox_scan
from home_manager.core.jobs import Work
from home_manager.documents import extraction
from home_manager.documents.extraction import HEADERS, ExtractionService
from home_manager.documents.layout_context import evidence_lines
from home_manager.documents.pdf_reader import read_result
from home_manager.documents.reasoning import ReasoningConfig
from home_manager.documents.receipt_service import ReceiptService
from home_manager.finance import paystub_tables
from home_manager.finance.ledger import Ledger
from home_manager.finance.provenance import provenance_for
import paystub_engine_fixtures as pf
from test_extraction import MISSING
from test_pdf import make_pdf, pdf_store  # noqa: F401

PREVIOUS_VERSION = "typed-extraction-v34-order-discounts"
ENGINE = paystub_tables.read  # Kept here so a test that makes the engine fail still shapes the model double with the real one.
FIXTURE_WORDS = ("Regular", "2,500.00", "Federal", "401K")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """C-net: nothing connects to a non-loopback address."""
    def loopback(address):
        host = address[0] if isinstance(address, tuple) else address
        return not isinstance(host, str) or host in ("localhost", "::1") or host.startswith("127.") or host.startswith("/")

    def guard(original):
        def connect(self, address, *args):
            if not loopback(address):
                raise OSError(f"C-net: a connection to {address} was blocked")
            return original(self, address, *args)
        return connect

    real_create = socket.create_connection

    def create(address, *args, **kwargs):
        if not loopback(address):
            raise OSError(f"C-net: a connection to {address} was blocked")
        return real_create(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guard(socket.socket.connect))
    monkeypatch.setattr(socket.socket, "connect_ex", guard(socket.socket.connect_ex))
    monkeypatch.setattr(socket, "create_connection", create)


# --- The doubles ---------------------------------------------------------------------------------------------------------

# The model stub's classes for PS: (description, group, category, the printed label that starts its row).
PS_CLASSES = [("Regular", "earnings", "regular_pay", "Regular"), ("Overtime", "earnings", "overtime", "Overtime"),
              ("Federal Income Tax", "tax", "federal_income_tax", "Federal Income Tax"), ("Social Security", "tax", "social_security", "Social Security"),
              ("Medicare", "tax", "medicare", "Medicare"), ("401K", "pre_tax", "retirement_pretax", "401K")]


def swapped(rows):
    """STUB-PS-SWAPPED's summary for a fixture's rows (label, hours, rate, current, ytd, kind): {field: (printed label of its line, the value given)},
    this period given the year-to-date value and back, so a value from the model would be wrong everywhere. Taxes and deductions are this period's
    only, so they are given the year-to-date value."""
    found = {kind: (label, current, ytd) for label, _, _, current, ytd, kind in rows if kind != "row"}
    gross, net, taxes, deductions = found["gross"], found["net"], found["taxes"], found["deductions"]
    return {"gross_pay": (gross[0], gross[2]), "gross_pay_ytd": (gross[0], gross[1]), "net_pay": (net[0], net[2]), "net_pay_ytd": (net[0], net[1]),
            "taxes": (taxes[0], taxes[2]), "deductions": (deductions[0], deductions[2])}


class Run:
    """One fixture, read and then extracted through the real services."""

    def __init__(self, store, service, local_model, parse_id, doc):
        self.store, self.service, self.local_model, self.parse_id, self.doc = store, service, local_model, parse_id, doc
        self.evidence = read_result(service.get(parse_id)["result"])
        self.lines = evidence_lines(self.evidence)
        self.extraction = ExtractionService(store, service)
        self.run = None

    def line(self, text):
        """The evidence line starting with the text, else the first holding it."""
        return next((line for line in self.lines if line.text.startswith(text)), None) or next(line for line in self.lines if text in line.text)

    def cite(self, text, quote=None):
        line = self.line(text)
        return [{"line_id": line.id, "quote": quote or line.text}]

    def value(self, text, label):
        return {"value": text, "status": "proposed", "evidence": self.cite(label, text)}

    def runs(self):
        """The runs of evidence lines the engine covers with rows, and the runs it doesn't, in file order: each is one model question."""
        covered = {line_id for table in ENGINE(self.evidence).adapted for line_id in [*(row.line_id for row in table.rows), *table.spans]}
        runs = []
        for line in self.lines:
            if not runs or (line.id in covered) != runs[-1][0]:
                runs.append([line.id in covered, []])
            runs[-1][1].append(line.id)
        return runs

    def stub(self, classes=PS_CLASSES, summary=None, extra_lines=(), employer="SYNTH PAYROLL CO", details=None):
        """The contract's `local_model` by schema: the classification citing the employer line, the summary with the given swapped amounts, the
        classes of each covered run, and the model's own pay lines (extra_lines, full PayLines entries) of each other run."""
        fields = {name: MISSING for name in HEADERS["paystub"]}
        fields.update(payer_or_employer=self.value(employer, employer), pay_date=self.value("2026-07-03", "Pay date"), currency=self.value("USD", "Currency"))
        fields.update({name: self.value(text, label) for name, (label, text) in (summary if summary is not None else swapped(pf.PS_ROWS)).items()})
        fields.update(details or {})
        rows = [{"description": description, "group": group, "category": category, "evidence": self.cite(label)} for description, group, category, label in classes]
        runs = self.runs()
        in_run = lambda entries, ids: [entry for entry in entries if entry["evidence"][0]["line_id"] in ids]  # noqa: E731
        self.local_model["by_schema"] = {
            "Classification": [{"document_type": "paystub", "evidence": self.cite(employer), "issuer": fields["payer_or_employer"],
                                "document_date": fields["pay_date"]}],
            "PaystubSummary": [fields],
            "PayRowClasses": [{"lines": in_run(rows, ids)} for covered, ids in runs if covered],
            "PayLines": [{"lines": in_run(list(extra_lines), ids)} for covered, ids in runs if not covered]}
        self.questions = 2 + len(runs)
        self.before = len(self.local_model["requests"])

    def extract(self, config=None, force=False):
        config = config or ReasoningConfig(base_url=self.local_model["config"].base_url, model="synthetic-reasoning")
        run_id, _ = self.extraction.enqueue(self.doc["id"], self.parse_id, config, force=force)
        self.extraction.run(run_id, Work.detached())
        self.run = self.extraction.get(run_id)
        assert self.run["status"] == "succeeded", self.run["error"]
        return self.run

    def asked(self):
        """The schemas of the questions this run's stubs were asked, in order."""
        return [request["response_format"]["json_schema"]["name"] for request in self.local_model["requests"][self.before:]]

    @property
    def record(self):
        return Ledger(self.store).record("income_record", self.run["publication"]["id"])

    @property
    def notes(self):
        return self.run["result"]["normalized"].get("notes", [])

    def fingerprint(self):
        """C-docs: the preserved original and every file of the reading folder, by sha256."""
        folder = self.service.folder(self.parse_id)
        files = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(folder.iterdir()) if path.is_file()}
        blob = self.store.blob_path(self.service.get(self.parse_id)["blob_hash"])
        return hashlib.sha256(blob.read_bytes()).hexdigest(), files


def started(pdf_store, local_model, pages, name="stub.pdf", shuffle=None):
    """The fixture captured and read by the real reader: no model call, every page embedded text (P-check)."""
    inbox, store = pdf_store
    if shuffle is not None:
        pages = [{"items": random.Random(shuffle).sample(page["items"], len(page["items"]))} if isinstance(page, dict) else page for page in pages]
    make_pdf(inbox / name, pages)
    inbox_scan(store)
    doc = next(item for item in store.documents()["items"] if item["relative_path"].endswith(name))
    service = ReceiptService(store)
    asked = len(local_model["requests"])
    parse_id, _ = service.enqueue(doc["id"], vision=local_model["config"])
    service.run(parse_id, Work.detached())
    parsed = service.get(parse_id)
    assert parsed["status"] == "succeeded", parsed["error"]
    assert len(local_model["requests"]) == asked
    assert [page["method"] for page in parsed["result"]["pages"]] == ["embedded_text"] * len(pages)
    return Run(store, service, local_model, parse_id, doc)


def lines_of(record):
    return [(line["description"], line["line_group"], line["current_minor"], line["ytd_minor"]) for line in record["lines"]]


def printed_details(record):
    return [((line["details"] or {}).get("hours", {}).get("text"), (line["details"] or {}).get("rate", {}).get("text")) for line in record["lines"]]


def expect(record, lines=pf.EXP_PS_LINES, totals=pf.EXP_PS):
    """C-lines(expected), the expected totals and C-money."""
    assert lines_of(record) == [line[:4] for line in lines]
    if len(lines[0]) > 4:
        assert printed_details(record) == [(line[4], line[5]) for line in lines]
    for name, minor in totals.items():
        assert record[name] == minor, name
    assert record["currency"] == "USD"
    for name in ("gross_pay_minor", "net_pay_minor", "taxes_minor", "deductions_minor", "gross_pay_ytd_minor", "net_pay_ytd_minor"):
        assert record[name] is None or isinstance(record[name], int)
    for line in record["lines"]:
        assert line["current_minor"] is None or isinstance(line["current_minor"], int)
        assert line["ytd_minor"] is None or isinstance(line["ytd_minor"], int)


def auto(record):
    """C-auto."""
    assert record["review_status"] == "verified" and record["issues"] == [], record["issues"]


def no_feature_review(record):
    """C-no-feature-review: no issue of this feature's kind. The reader's own "Page N PDF layout needs review: …" issues are not this feature's."""
    feature = [issue for issue in record["issues"] if "PDF layout needs review" not in issue
               and any(word in issue.lower() for word in ("column", "guess", "unplaced", "unclassified", "pay table", "split"))]
    assert feature == [], feature


def only_the_planned_questions(run):
    """C-model-calls: the stubs were asked exactly the classification, the summary and one question per run of lines; the engine asked nothing."""
    assert len(run.asked()) == run.questions
    assert Counter(run.asked())["Classification"] == 1 and Counter(run.asked())["PaystubSummary"] == 1


def read_by_engine(run):
    """Every question about rows showed the model the pay engine's cells (tables `page-N-pay-K`), and none a printed table's `…layout-table-K` (FR-60)."""
    shown = [json.loads(request["messages"][1]["content"]).get("reported_tables", []) for request in run.local_model["requests"][run.before:]
             if request["response_format"]["json_schema"]["name"] == "PayRowClasses"]
    assert shown and all(re.fullmatch(r"page-\d+-pay-\d+", table["table_id"]) for tables in shown for table in tables)


def swapped_stub_run(pdf_store, local_model, pages, classes=PS_CLASSES, summary=None, **options):
    run = started(pdf_store, local_model, pages, **options)
    run.stub(classes, summary)
    run.extract()
    read_by_engine(run)
    return run


# === SC-50: every value from its printed cell ===============================================================================

def test_sc50_every_value_is_its_printed_cell_although_the_model_swapped_every_amount(pdf_store, local_model):
    run = started(pdf_store, local_model, pf.ps_pages())
    before = run.fingerprint()
    run.stub()
    run.extract()
    record = run.record
    expect(record)
    auto(record)
    assert len(record["lines"]) == 6
    assert run.run["prompt_version"] == extraction.EXTRACTION_VERSION
    assert [line["cell_evidence"]["current"]["source"] for line in record["lines"]] == ["pdf_text"] * 6  # Each value cites its printed cell's words.
    assert run.notes == []
    read_by_engine(run)
    only_the_planned_questions(run)
    assert run.fingerprint() == before  # C-docs


def test_sc50_a_shuffled_content_stream_gives_the_same_record(pdf_store, local_model):
    run = started(pdf_store, local_model, pf.ps_pages(), shuffle=11)
    run.stub()
    run.extract()
    expect(run.record)
    auto(run.record)


# === SC-51: two-line headings and totals lines ===============================================================================

def test_sc51_two_line_headings_and_totals_lines_give_the_same_values(pdf_store, local_model):
    run = swapped_stub_run(pdf_store, local_model, pf.ps_2l_pages())
    record = run.record
    expect(record)
    auto(record)
    # The Current column is headed "This" over "Period": the heading cited for each value is both lines' words (FR-66).
    labels = {line["details"]["current_column_heading"]["text"] for line in record["lines"]}
    assert labels == {"This Period"}
    assert {line["details"]["ytd_column_heading"]["text"] for line in record["lines"]} == {"Year to Date"}


# === SC-52: side-by-side blocks ================================================================================================

def test_sc52_side_by_side_blocks_record_every_line_from_its_own_block(pdf_store, local_model):
    run = swapped_stub_run(pdf_store, local_model, pf.sbs_pages())
    # SBS expected: EXP-PS with no hours or rate on any line.
    expect(run.record, [line[:4] + (None, None) for line in pf.EXP_PS_LINES])
    auto(run.record)


# === SC-53: stacked tables and section titles ================================================================================

def test_sc53_stacked_tables_record_one_line_per_row_and_no_line_for_a_title(pdf_store, local_model):
    run = swapped_stub_run(pdf_store, local_model, pf.stk_pages())
    expect(run.record)
    auto(run.record)
    assert "Statutory" not in [line["description"] for line in run.record["lines"]]


# === SC-54: a wrapped label and its evidence =================================================================================

def test_sc54_a_wrapped_label_is_one_line_citing_both_printed_lines(pdf_store, local_model):
    run = started(pdf_store, local_model, pf.ps_wrap_pages())
    classes = [("Federal Income Tax Withholding", *rest) if description == "Federal Income Tax" else (description, *rest)
               for description, *rest in [(c[0], c[1], c[2], "Federal Income" if c[0] == "Federal Income Tax" else c[3]) for c in PS_CLASSES]]
    run.stub(classes)
    run.extract()
    read_by_engine(run)
    record = run.record
    expected = [("Federal Income Tax Withholding", *line[1:]) if line[0] == "Federal Income Tax" else line for line in pf.EXP_PS_LINES]
    expect(record, expected)
    # Step 2: the Federal line's locator lists the `Federal Income` line and then the `Tax Withholding` line.
    federal = record["lines"][2]
    assert federal["line_ids"] == [run.line("Federal Income").id, run.line("Tax Withholding").id]
    # Step 3: net pay cites the Net Pay line's 2,051.89 word, the Federal line's this-period value cites the word 295.63.
    words = {word.id: word.text for word in run.evidence.pages[0].layout.words}
    with run.store.connection() as db:
        provenance = provenance_for(db, "income_record", record["id"], "net_pay")["provenance"]["document"]
    assert [cell["quote"] for cell in provenance["cells"]] == ["2,051.89"]
    assert [words[word_id] for word_id in provenance["cells"][0]["word_ids"]] == ["2,051.89"]
    assert [words[word_id] for word_id in federal["cell_evidence"]["current"]["word_ids"]] == ["295.63"]
    assert [words[word_id] for word_id in federal["cell_evidence"]["ytd"]["word_ids"]] == ["3,698.75"]


# === SC-55: no headings, columns reversed ====================================================================================

def test_sc55_no_headings_and_reversed_columns_give_the_same_values_and_no_note_about_columns(pdf_store, local_model):
    run = swapped_stub_run(pdf_store, local_model, pf.ps_nh_pages())
    expect(run.record)
    auto(run.record)
    assert not [note for note in run.notes if "column" in note.lower()]


def test_sc55_ps_nh_reading_carries_unresolved_columns_and_its_record_has_no_layout_review_issue(pdf_store, local_model):
    """Plan P7.1a: table_grid raises `unresolved_columns` exactly when it can't build a headerless table; the pay engine read the table, so the
    reader's layout-review message is not a review reason."""
    run = started(pdf_store, local_model, pf.ps_nh_pages())
    assert set(run.evidence.pages[0].layout.issues) == {"unresolved_columns"}  # P-check: the reading carries it ...
    assert [issue.code for issue in run.evidence.issues] == ["pdf_layout_review"]  # ... and the reader raised its review message.
    run.stub()
    run.extract()
    record = run.record
    assert not [issue for issue in record["issues"] if "layout" in issue.lower()]
    auto(record)
    assert not [note for note in run.run["result"]["notes"] if "layout" in note.lower()]


# === SC-57: YTD hours and an employer column are other =======================================================================

def test_sc57a_ytd_hours_are_not_the_hours_of_the_line(pdf_store, local_model):
    run = swapped_stub_run(pdf_store, local_model, pf.ps_ytdh_pages())
    expect(run.record)  # Regular's hours are 80.00, not 1,040.00.
    auto(run.record)


def test_sc57b_an_employer_column_is_never_money(pdf_store, local_model):
    run = swapped_stub_run(pdf_store, local_model, pf.ps_emp_pages())
    record = run.record
    expect(record)
    auto(record)
    assert 8063 not in [value for line in record["lines"] for value in (line["current_minor"], line["ytd_minor"])]
    assert 8063 not in [record[name] for name in ("gross_pay_minor", "net_pay_minor", "taxes_minor", "deductions_minor")]


# === SC-58: label digits ===================================================================================================

def test_sc58_label_digits_stay_in_the_label_and_each_row_has_two_amounts(pdf_store, local_model):
    rows = list(pf.PS_ROWS)
    rows[7:9] = [("PRE-TAX 401K", "", "", "134.38", "1,681.25", "row"), ("SECTION 125", "", "", "85.00", "1,105.00", "row"),
                 ("Total Pre-Tax Deductions", "", "", "219.38", "2,786.25", "deductions")]
    rows[-1] = ("Net Pay", "", "", "1,966.89", "24,567.69", "net")
    classes = [*PS_CLASSES[:5], ("PRE-TAX 401K", "pre_tax", "retirement_pretax", "PRE-TAX 401K"), ("SECTION 125", "pre_tax", "other", "SECTION 125")]
    run = swapped_stub_run(pdf_store, local_model, pf.ps_digits_pages(), classes, swapped(rows))
    expect(run.record, pf.EXP_DIGITS_LINES, {**pf.EXP_PS, **pf.EXP_DIGITS})
    auto(run.record)


# === SC-59: a page with no pay table ======================================================================================

def test_sc59_a_page_with_no_pay_table_keeps_the_models_value_and_adds_the_note(pdf_store, local_model):
    run = started(pdf_store, local_model, pf.prose_pages())
    assert paystub_tables.read(run.evidence).unplaced == []  # The page 2 line is not an unplaced line.
    prose = "Your employer HSA contribution"
    hsa = {"description": "Employer HSA", "group": "employer_paid", "category": "hsa", "current": "50.00", "ytd": None, "evidence": run.cite(prose)}
    run.stub(extra_lines=[hsa])
    run.extract()
    record = run.record
    expect(record, [*pf.EXP_PS_LINES, ("Employer HSA", "employer_paid", 5000, None, None, None)])
    note = "Page 2: no pay table was found in the printed columns, so its amounts are the reading's; check them."
    assert note in run.notes and note not in record["issues"]
    assert [note for note in run.notes if "Page 1" in note] == []
    no_feature_review(record)
    # The reader's own layout-review message for page 2 (it holds no pay table) is still a review reason.
    assert any(issue.startswith("Page 2 PDF layout needs review") for issue in record["issues"])


def test_sc59_a_table_less_pages_swapped_flat_line_is_still_nulled_by_the_column_checks(pdf_store, local_model):
    """M6 / FR-64: page 2 prints its own header and a line the pay engine reads no table from; the model swapped its two amounts, so both are
    nulled by `column_checks`. Page 1's values come from the engine's cells and are not judged by it."""
    flat = "DESCRIPTION CURRENT YTD\nBONUS 500.00 5,000.00"
    run = started(pdf_store, local_model, [*pf.ps_pages(), flat])
    bonus = {"description": "Bonus", "group": "earnings", "category": "bonus", "current": "5,000.00", "ytd": "500.00", "evidence": run.cite("BONUS")}
    run.stub(extra_lines=[bonus])
    run.extract()
    record = run.record
    assert lines_of(record)[:6] == [line[:4] for line in pf.EXP_PS_LINES]
    assert lines_of(record)[6] == ("Bonus", "earnings", None, None)
    assert record["lines"][6]["details"]["current_status"] == "ambiguous"
    assert any("Bonus" in issue and "doesn't match the printed columns" in issue for issue in record["issues"])
    assert "Page 2: no pay table was found in the printed columns, so its amounts are the reading's; check them." in run.notes
    assert not [issue for issue in record["issues"] if "Page 1" in issue or "Regular" in issue]


# === SC-63: engine failure =================================================================================================

def test_sc63_an_engine_fault_takes_todays_path_with_the_note_and_logs_only_the_class(pdf_store, local_model, monkeypatch, caplog):
    def boom(evidence):
        raise RuntimeError("injected engine fault")
    monkeypatch.setattr(paystub_tables, "read", boom)
    run = started(pdf_store, local_model, pf.ps_pages())
    run.stub()
    with caplog.at_level(logging.ERROR):
        run.extract()
    record = run.record
    note = "The pay table couldn't be read from the printed columns, so the reading's amounts were used; check them."
    assert note in run.notes and note not in record["issues"]
    assert record["lines"][0]["cell_evidence"]["current"]["source"] == "pdf_text"  # Today's path: the printed table's native cells.
    failures = [entry for entry in caplog.records if "pay table read failed" in entry.getMessage()]
    assert len(failures) == 1 and "RuntimeError" in failures[0].getMessage()
    assert not [entry for entry in caplog.records if any(word in entry.getMessage() for word in FIXTURE_WORDS)]
    assert failures[0].getMessage().splitlines()[0].startswith("pay table read failed: RuntimeError")  # By class and run id; the message is left out.


# === SC-65: version and existing records ====================================================================================

def test_sc65_the_version_changed_and_extract_again_rereads_the_undecided_stub_and_keeps_the_confirmed_one(pdf_store, local_model, monkeypatch):
    """Two stubs recorded under the previous version (the engine made to fail, so they were read by today's path); one is left undecided, one is
    confirmed with Ledger.review, which is what the review API calls."""
    assert extraction.EXTRACTION_VERSION != PREVIOUS_VERSION
    with monkeypatch.context() as past:
        past.setattr(extraction, "EXTRACTION_VERSION", PREVIOUS_VERSION)
        past.setattr(paystub_tables, "read", lambda evidence: (_ for _ in ()).throw(RuntimeError("injected engine fault")))
        undecided = started(pdf_store, local_model, pf.ps_pages(), name="undecided.pdf")
        undecided.stub()
        undecided.extract()
        confirmed = started(pdf_store, local_model, pf.ps_2l_pages(), name="confirmed.pdf")
        confirmed.stub()
        confirmed.extract()
        assert undecided.run["prompt_version"] == PREVIOUS_VERSION
        Ledger(confirmed.store).review("income_record", confirmed.run["publication"]["id"], "verified")
    failed = "The pay table couldn't be read from the printed columns, so the reading's amounts were used; check them."
    assert failed in undecided.notes
    store = confirmed.store

    def rows():
        with store.connection() as db:
            return ([tuple(row) for row in db.execute("SELECT * FROM income_records WHERE id=?", (confirmed.run["publication"]["id"],))],
                    [tuple(row) for row in db.execute("SELECT * FROM income_lines WHERE income_record_id=? ORDER BY id", (confirmed.run["publication"]["id"],))])
    frozen = rows()
    for run in (undecided, confirmed):
        run.stub()
        run_id, created = run.extraction.enqueue(run.doc["id"], run.parse_id, ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning"))
        assert created  # A new run: the version is part of the reuse key.
        run.extraction.run(run_id, Work.detached())
        run.run = run.extraction.get(run_id)
        assert run.run["status"] == "succeeded" and run.run["prompt_version"] == extraction.EXTRACTION_VERSION
    expect(undecided.record)
    assert failed not in undecided.notes  # Read by the engine now.
    assert rows() == frozen  # The confirmed record is byte-identical in income_records and income_lines.
    assert confirmed.record["review_status"] == "verified" and confirmed.record["review_source"] == "user"


# === SC-66: determinism (single stubs) ======================================================================================

def snapshot(run):
    """Every income record, line, evidence link and segment, without what names the run or the clock."""
    drop = {"created_at", "updated_at", "extraction_run_id", "source_key", "run_id"}
    with run.store.connection() as db:
        found = {table: [{key: value for key, value in dict(row).items() if key not in drop} for row in db.execute(f"SELECT * FROM {table} ORDER BY id")]
                 for table in ("income_records", "income_lines", "document_segments")}
        # Extract again links the record to its new run as well: the links are the same set of citations, once each run.
        found["evidence"] = sorted({(row["record_type"], row["record_id"], row["document_id"], row["locator_json"])
                                    for row in db.execute("SELECT * FROM financial_evidence_links")})
    return found


def test_sc66_extract_again_on_an_unchanged_reading_changes_nothing(pdf_store, local_model):
    run = started(pdf_store, local_model, pf.ps_sec_pages(memo=True))
    run.stub()
    run.extract()
    first, record, notes = snapshot(run), run.record, run.notes
    only_the_planned_questions(run)
    engine = [json.dumps(paystub_tables.read(run.evidence), default=str, sort_keys=True) for _ in range(2)]
    assert engine[0] == engine[1]
    run.stub()
    run.extract(force=True)
    assert snapshot(run) == first
    assert run.notes == notes and run.record["issues"] == record["issues"] and run.record["details"] == record["details"]
    only_the_planned_questions(run)


# === SC-69: a row printed only under YTD ====================================================================================

def test_sc69_a_row_printed_only_under_ytd_keeps_this_period_blank(pdf_store, local_model):
    rows = list(pf.PS_ROWS)
    rows.insert(2, ("Relocation Bonus", "", "", "", "5,000.00", "row"))
    rows[3] = ("Gross Pay", "", "", "2,687.50", "38,625.00", "gross")
    rows[-1] = ("Net Pay", "", "", "2,051.89", "30,672.69", "net")
    classes = [*PS_CLASSES[:2], ("Relocation Bonus", "earnings", "bonus", "Relocation Bonus"), *PS_CLASSES[2:]]
    run = swapped_stub_run(pdf_store, local_model, pf.ps_bonus_pages(), classes, swapped(rows))
    lines = [*pf.EXP_PS_LINES[:2], ("Relocation Bonus", "earnings", None, 500000, None, None), *pf.EXP_PS_LINES[2:]]
    expect(run.record, lines, {**pf.EXP_PS, "gross_pay_ytd_minor": 3862500, "net_pay_ytd_minor": 3067269})
    auto(run.record)
    assert not [note for note in run.notes if "Bonus" in note or "bonus" in note]


# === The engine on the existing payslip fixtures ============================================================================
# test_layout_consumers.py's side-by-side and sectioned payslips (FR-72: they pass unchanged) showed three things the contract's fixtures don't:
# a second label printed less than 1.5 font sizes after the first group's last amount, an amount under a column whose first amount chose another
# alignment, and a table whose columns all end other. Expected values are those tests' printed literals.

def engine_of(tmp_path, items, extra=()):
    import pdf_import_fixtures as fx
    return paystub_tables.read(fx.read_pdf(tmp_path, [{"items": items}, *extra]))


def test_a_tightly_padded_side_by_side_payslip_is_two_tables_with_every_amount_placed(tmp_path):
    from test_pdf_layout import payslip_items
    found = engine_of(tmp_path, [(40, 760, "SYNTH WIDGETS LLC"), (40, 745, "Pay Date 2026-07-03"), (40, 730, "Currency USD"), *payslip_items()])
    left, right = found.tables
    texts = lambda table: [(row.label, [token.text for token in row.amounts.values()], row.stray) for row in table.rows]  # noqa: E731
    assert texts(left) == [("Regular Salary", ["4,000.00", "52,000.00"], []), ("Relocation Bonus", ["4,000.00"], []), ("Overtime", ["300.00", "1,200.00"], [])]
    assert [total.label for total in left.totals] == ["Gross Pay"]
    assert texts(right) == [("Federal Income Tax", ["500.00", "6,500.00"], []), ("Social Security", ["248.00", "3,224.00"], []),
                            ("Medicare", ["58.00", "754.00"], []), ("401K", ["200.00", "2,600.00"], []), ("Dental", ["12.00", "156.00"], [])]
    assert [total.label for total in right.totals] == ["Total Deductions"]
    assert [roles.roles for roles in found.roles] == [{column.id: role for column, role in zip(table.columns, ("current", "ytd"))} for table in found.tables]


def test_a_table_whose_columns_all_end_other_is_not_trusted_on_its_page(tmp_path):
    from test_pdf_layout import sectioned_payslip_items
    benefits = {"items": [(60, 700, "Other Benefit And Information"), (250, 700, "This Period"), (320, 700, "Year to Date"),
                          (60, 685, "Co Match 401K"), (265, 685, "160.00"), (330, 685, "3,360.00")]}
    found = engine_of(tmp_path, [(30, 760, "SYNTH CONSULTING LTD"), (30, 745, "Currency USD"), *sectioned_payslip_items()], [benefits])
    assert found.fallback_pages == {1}  # Page 1's right block decided no column: its printed tables stay.
    assert found.engine_pages == {2} and [table.id for table in found.adapted] == ["page-2-pay-1"]
    assert found.pages_without_tables == [] and paystub_tables.for_lines(found, set(found.lines_of.values())).pages_without_tables == [1]


# === SL-04: notes and guesses on the record, unclassified rows, the summary box =============================================

def guesses_of(record, kind=None):
    found = (record["details"] or {}).get("guesses", [])
    return [guess for guess in found if kind is None or guess["kind"] == kind]


def note_among(run, *words, absent=()):
    """C-note: one record note holds every word, and it is not among the record's issues."""
    found = [note for note in run.notes if all(word in note for word in words) and not any(word in note for word in absent)]
    assert found, (words, run.notes)
    assert not [issue for issue in run.record["issues"] if issue in found]
    return found[0]


def cited_cells(run, field):
    """The quotes of the cells a summary field's provenance cites (FR-66)."""
    with run.store.connection() as db:
        return [cell["quote"] for cell in provenance_for(db, "income_record", run.record["id"], field)["provenance"]["document"]["cells"]]


def bad_rows(**totals):
    """PS's rows with a total's printed amounts replaced: {label: (current, ytd)}."""
    return [(label, hours, rate, *totals.get(label, (current, ytd)), kind) for label, hours, rate, current, ytd, kind in pf.PS_ROWS]


# --- SC-56: deposit and leave tables are set aside ---------------------------------------------------------------------------

def test_sc56_deposit_and_leave_tables_give_no_pay_lines_and_no_notes(pdf_store, local_model):
    run = started(pdf_store, local_model, pf.ps_other_pages())
    found = paystub_tables.read(run.evidence)  # Engine level: two other tables (deposit, leave), no unplaced line.
    assert len(found.other_tables) == 2 and found.unplaced == []
    other_rows = {row.label for table in found.other_tables for row in table.rows}
    assert other_rows == {"Checking 1234", "Savings 5678", "Vacation", "Sick"}
    assert not other_rows & {row.label for table in found.tables for row in table.rows}
    splits = [{"last_four": four, "amount": amount, "evidence": run.cite(label)} for four, amount, label in (("1234", "1,551.89", "Checking 1234"),
                                                                                                           ("5678", "500.00", "Savings 5678"))]
    run.stub(details={"deposit_splits": splits})
    run.extract()
    record = run.record
    expect(record)  # Six lines, none from those tables.
    auto(record)
    assert [(split["last_four"], split["minor"]) for split in record["details"]["deposit_splits"]] == [("1234", 155189), ("5678", 50000)]
    assert not [note for note in run.notes if "placed" in note or "classified" in note or "native table" in note]
    assert not [issue for issue in record["issues"] if "native table" in issue]
    assert guesses_of(record) == []


# --- SC-60: an unplaced line and an unclassified row ---------------------------------------------------------------------------

def test_sc60_an_unplaced_line_and_an_unclassified_row_are_notes_and_the_row_is_recorded_in_its_sections_group(pdf_store, local_model):
    run = started(pdf_store, local_model, pf.ps_sec_pages(memo=True))
    found = paystub_tables.read(run.evidence)
    assert [(line.page, "Bonus advance memo" in line.text) for line in found.unplaced] == [(1, True)]  # Step 1.
    run.stub([entry for entry in PS_CLASSES if entry[0] != "Medicare"])
    run.extract()
    record = run.record
    expect(record)  # Medicare is recorded as (Medicare, tax, 3897, 48756), its group guessed from the Taxes title.
    auto(record)
    assert len(record["lines"]) == 6
    medicare = note_among(run, "Medicare", "Page 1")
    assert "Taxes" in medicare  # Its group came from the section title.
    note_among(run, "Page 1", "Bonus advance memo")
    assert not [issue for issue in record["issues"] if "Medicare" in issue or "Bonus advance memo" in issue]
    assert not [text for text in [*run.notes, *record["issues"]] if "native table row" in text]  # The count note is gone.
    assert [(guess["kind"], guess["page"]) for guess in guesses_of(record)] == [("group_guessed", 1)]
    assert "Medicare" in guesses_of(record)[0]["text"] and guesses_of(record)[0]["text"] in run.notes
    assert record["lines"][4]["cell_evidence"]["current"]["source"] == "pdf_text"  # The guessed line's amounts are its printed cells' too.


def test_sc60_a_row_without_a_section_title_takes_the_group_under_which_the_totals_hold(pdf_store, local_model):
    run = swapped_stub_run(pdf_store, local_model, pf.ps_pages(), [entry for entry in PS_CLASSES if entry[0] != "Medicare"])
    record = run.record
    expect(record)  # Tax is tried before pre-tax and post-tax, and earnings first: only tax and the two deduction groups hold the net check.
    auto(record)
    note = note_among(run, "Medicare", "Page 1")
    assert "totals add up" in note and "a tax" in note
    assert [guess["kind"] for guess in guesses_of(record)] == ["group_guessed"]


def test_sc60_a_row_the_totals_cant_place_takes_the_group_of_the_line_above(pdf_store, local_model):
    """A stub with no totals and no summary: nothing the totals can settle, so the unclassified Overtime row takes Regular's group."""
    rows = [row for row in pf.PS_ROWS if row[0] in ("Regular", "Overtime")]
    run = started(pdf_store, local_model, [pf.ps_page(rows)])
    run.stub(PS_CLASSES[:1], {})
    run.extract()
    assert lines_of(run.record) == [line[:4] for line in pf.EXP_PS_LINES[:2]]
    assert "next to it" in note_among(run, "Overtime", "Page 1")
    assert [guess["kind"] for guess in guesses_of(run.record)] == ["group_guessed"]


# --- SC-61: guesses about the columns --------------------------------------------------------------------------------------

def test_sc61a_headings_that_contradict_the_numbers_lose_and_say_so(pdf_store, local_model):
    run = swapped_stub_run(pdf_store, local_model, pf.ps_swaphead_pages())
    record = run.record
    expect(record)  # The numbers win.
    auto(record)
    note_among(run, "Page 1", "YTD", "Current")
    assert [guess["kind"] for guess in guesses_of(record)] == ["headings_overruled"]
    assert guesses_of(record)[0]["text"] in run.notes


B1_SUMMARY = {"gross_pay": ("Gross Pay", "5,000.00"), "gross_pay_ytd": ("Gross Pay", "2,500.00"),
              "net_pay": ("Net Pay", "5,000.00"), "net_pay_ytd": ("Net Pay", "2,500.00")}
B2_SUMMARY = {"gross_pay": ("Gross Pay", "2,550.00"), "gross_pay_ytd": ("Gross Pay", "1,350.00"),
              "net_pay": ("Net Pay", "2,550.00"), "net_pay_ytd": ("Net Pay", "1,350.00")}


def test_sc61b1_columns_no_row_tells_apart_are_guessed_left_is_this_period(pdf_store, local_model):
    classes = [("Regular", "earnings", "regular_pay", "Regular"), ("Relocation Bonus", "earnings", "bonus", "Relocation Bonus")]
    run = swapped_stub_run(pdf_store, local_model, pf.b1_pages(), classes, B1_SUMMARY)
    record = run.record
    expect(record, pf.EXP_B1_LINES, {"gross_pay_minor": 250000, "gross_pay_ytd_minor": 500000, "net_pay_minor": 250000, "net_pay_ytd_minor": 500000})
    note_among(run, "Page 1", "left column")
    no_feature_review(record)
    assert [guess["kind"] for guess in guesses_of(record)] == ["columns_guessed"]
    assert guesses_of(record)[0]["text"] in run.notes


def test_sc61b2_rows_that_disagree_are_guessed_and_only_the_larger_this_period_row_needs_review(pdf_store, local_model):
    classes = [("Regular", "earnings", "regular_pay", "Regular"), ("Shift Premium", "earnings", "other_earnings", "Shift Premium"),
               ("Bonus", "earnings", "bonus", "Bonus")]
    run = swapped_stub_run(pdf_store, local_model, pf.b2_pages(), classes, B2_SUMMARY)
    record = run.record
    # B2 expected lists Shift Premium as (30000, 15000) and also says FR-22 (b) fires for it, which "is null and ambiguous" (today's check, unchanged):
    # the engine copies 30000 and the check then nulls it, so the record holds None (specs/.../test-contract.md SC-61, B2; the handoff escalates the wording).
    copied = [(*line[:2], None, line[3]) if line[0] == "Shift Premium" else line for line in pf.EXP_B2_LINES]
    expect(record, copied, {"gross_pay_minor": 135000, "gross_pay_ytd_minor": 255000, "net_pay_minor": 135000, "net_pay_ytd_minor": 255000})
    note_among(run, "Page 1", "left column")
    assert [guess["kind"] for guess in guesses_of(record)] == ["columns_guessed"]
    assert record["review_status"] == "needs_review"
    reasons = [issue for issue in record["issues"] if "PDF layout needs review" not in issue]  # The reader's own message is not this feature's.
    assert reasons and all("Shift Premium" in issue for issue in reasons), reasons  # FR-22 (b) for that line only, and no issue about the columns.
    assert not [issue for issue in reasons if "column" in issue.lower() and "Shift Premium" not in issue]
    assert record["lines"][1]["current_minor"] is None and record["lines"][1]["details"]["current_status"] == "ambiguous"


# --- SC-62: misprinted totals ---------------------------------------------------------------------------------------------

def test_sc62a_a_misprinted_taxes_total_is_a_note_not_a_review_reason(pdf_store, local_model):
    run = swapped_stub_run(pdf_store, local_model, pf.ps_badtotal_pages(), summary=swapped(bad_rows(**{"Total Taxes": ("510.23", "6,271.06")})))
    record = run.record
    expect(record, totals={**pf.EXP_PS, "taxes_minor": 51023})  # The printed total (FR-61), the lines as printed.
    auto(record)
    note = note_among(run, "Page 1", "510.23")
    assert "Total Taxes" in note and "501.23" in note  # It names the total and what the lines above it add up to.
    assert [note for note in run.notes if "doesn't match the lines above it" in note] == [note]


def test_sc62b_a_net_pay_the_lines_dont_give_is_todays_review_reason(pdf_store, local_model):
    run = swapped_stub_run(pdf_store, local_model, pf.ps_badnet_pages(), summary=swapped(bad_rows(**{"Net Pay": ("2,061.89", "25,672.69")})))
    record = run.record
    expect(record, totals={**pf.EXP_PS, "net_pay_minor": 206189})
    assert record["review_status"] == "needs_review"
    net = [issue for issue in record["issues"] if issue.startswith("Gross pay less deductions and taxes") and "is not net pay" in issue]
    assert len(net) == 1
    assert not [note for note in run.notes if "doesn't match the lines above it" in note]  # Net pay is no section total (FR-57 b).


# --- SC-70: the summary box ----------------------------------------------------------------------------------------------

BOX_SUMMARY = {"gross_pay": ("YTD", "33,625.00"), "gross_pay_ytd": ("Current", "2,687.50"), "net_pay": ("YTD", "25,672.69"),
               "net_pay_ytd": ("Current", "2,051.89"), "taxes": ("YTD", "6,271.06"), "deductions": ("YTD", "1,681.25")}


@pytest.mark.parametrize("pages", [pf.sb_pages, pf.sb_shuf_pages], ids=["sb", "sb-shuf"])
def test_sc70_summary_box_gives_gross_net_taxes_and_deductions_with_no_note(pdf_store, local_model, pages):
    run = swapped_stub_run(pdf_store, local_model, pages(), summary=BOX_SUMMARY)
    record = run.record
    expect(record)  # SB expected: EXP-PS lines and totals (YTD taxes and deductions are not record fields).
    auto(record)
    assert run.notes == [] and guesses_of(record) == []
    assert [cited_cells(run, name) for name in ("gross_pay", "gross_pay_ytd", "net_pay", "net_pay_ytd", "taxes", "deductions")] == [
        ["2,687.50"], ["33,625.00"], ["2,051.89"], ["25,672.69"], ["501.23"], ["134.38"]]  # Each cites its box cell's words.


def test_sc70_a_box_with_no_heading_takes_the_left_column_as_taxes_and_says_so(pdf_store, local_model):
    run = swapped_stub_run(pdf_store, local_model, pf.sb_nohead_pages(), summary=BOX_SUMMARY)
    record = run.record
    expect(record)
    auto(record)
    note_among(run, "left", "taxes")
    assert [guess["kind"] for guess in guesses_of(record)] == ["box_columns_guessed"]
    assert guesses_of(record)[0]["text"] in run.notes


def test_a_totals_line_and_the_summary_box_that_disagree_keep_the_one_the_lines_add_up_to(pdf_store, local_model):
    """FR-61: the box prints taxes 501.23 and the totals line 510.23; the tax lines add up to 501.23, so the box is kept, with a note. FR-63's note
    for the misprinted total is there too."""
    items = [*pf.row_items(712, [(edge, pf.BOX_HEADING[column], True) for column, edge in enumerate(pf.BOX_EDGES)])]
    for y, label, values in ((696, "Current", pf.BOX_CURRENT), (680, "YTD", pf.BOX_YTD)):
        items += pf.row_items(y, [(40, label), *[(edge, text, True) for edge, text in zip(pf.BOX_EDGES, values)]])
    rows = bad_rows(**{"Total Taxes": ("510.23", "6,271.06")})
    pages = [pf.page_of([*items, *pf.head(650, pf.PS_HEADING, pf.PS_EDGES), *pf.lay(630, pf.ps_specs(rows), pf.PS_EDGES)])]
    run = swapped_stub_run(pdf_store, local_model, pages, summary=BOX_SUMMARY)  # The box heading starts with "Gross Pay", so the stub cites the box rows.
    record = run.record
    expect(record)  # taxes_minor 50123, the box's.
    disagree = note_among(run, "Page 1", "summary box")
    assert "510.23" in disagree and "501.23" in disagree and "box was used" in disagree
    note_among(run, "Page 1", "510.23", "add up", absent=("summary box",))
    assert cited_cells(run, "taxes") == ["501.23"]
    assert not [issue for issue in record["issues"] if "summary box" in issue or "doesn't match" in issue]


def test_determinism_of_the_new_notes_and_guesses(pdf_store, local_model):
    """FR-69: Extract again on an unchanged reading gives the same notes and guesses."""
    run = started(pdf_store, local_model, pf.ps_sec_pages(memo=True))
    classes = [entry for entry in PS_CLASSES if entry[0] != "Medicare"]
    run.stub(classes)
    run.extract()
    first, notes, guesses = snapshot(run), run.notes, guesses_of(run.record)
    run.stub(classes)
    run.extract(force=True)
    assert snapshot(run) == first and run.notes == notes and guesses_of(run.record) == guesses


# --- FR-76: the run result's pay_tables (what the document page's Tables tab shows) ---------------------------------------------

def test_pay_tables_of_the_run_result_hold_the_engines_cells_and_roles(pdf_store, local_model):
    """SL-05 (plan P7.10): PS's run result carries one file-wide pay table: its roles by cell index, a header row, ten rows (totals flagged) whose
    cells hold the printed text and word ids, no guess; cell values are the contract's PS table, written out here."""
    run = swapped_stub_run(pdf_store, local_model, pf.ps_pages())
    [table] = run.run["result"]["pay_tables"]
    words = {word.id: word.text for word in run.evidence.pages[0].layout.words}
    assert table["page"] == 1 and re.fullmatch(r"page-1-pay-\d+", table["id"])
    assert table["roles"] == {"1": "hours", "2": "rate", "3": "current", "4": "ytd"}
    [heading] = table["header_rows"]
    assert [cell["quote"] for cell in heading["cells"]] == ["", "Hours", "Rate", "Current", "YTD"]
    assert [row["total"] for row in table["rows"]] == [kind != "row" for *_, kind in pf.PS_ROWS]
    for row, (label, hours, rate, current, ytd, _) in zip(table["rows"], pf.PS_ROWS):
        assert [cell["quote"] for cell in row["cells"]] == [label, hours, rate, current, ytd]
        assert row["line_id"] == row["cells"][0]["line_id"] and row["id"].startswith(table["id"])
        for cell in row["cells"]:
            assert {key for key in cell} == {"id", "quote", "word_ids", "line_id"}
            assert [words[word_id] for word_id in cell["word_ids"]] == (cell["quote"].split() if cell["quote"] else [])  # Blank cells hold no words.
    assert table["guesses"] == []
    assert [entry["id"] for entry in run.run["result"]["pay_tables"]] == [table["id"]]  # No summary box on PS.
    json.dumps(run.run["result"]["pay_tables"])


def test_pay_tables_list_the_guess_beside_the_table_it_concerns(pdf_store, local_model):
    """B1's columns guess (SC-61 b1) is the one guess text of its table, the same words as the record's note."""
    classes = [("Regular", "earnings", "regular_pay", "Regular"), ("Relocation Bonus", "earnings", "bonus", "Relocation Bonus")]
    run = swapped_stub_run(pdf_store, local_model, pf.b1_pages(), classes, B1_SUMMARY)
    [table] = run.run["result"]["pay_tables"]
    [guess] = guesses_of(run.record, "columns_guessed")
    assert table["guesses"] == [guess["text"]] and "left column" in table["guesses"][0]


def test_pay_tables_hold_the_summary_box_in_the_same_shape(pdf_store, local_model):
    run = swapped_stub_run(pdf_store, local_model, pf.sb_pages(), summary=BOX_SUMMARY)
    tables = run.run["result"]["pay_tables"]
    [box] = [table for table in tables if len(table["rows"]) == 2]  # The pay table has the six rows; the box its two.
    assert [cell["quote"] for cell in box["header_rows"][0]["cells"]][1:] == ["Gross Pay", "Taxes", "Deductions", "Net Pay"]
    assert [cell["quote"] for cell in box["rows"][0]["cells"]][1:] == ["2,687.50", "501.23", "134.38", "2,051.89"]
    assert [cell["quote"] for cell in box["rows"][1]["cells"]][1:] == ["33,625.00", "6,271.06", "1,681.25", "25,672.69"]
    assert set(box["roles"].values()) == {"gross", "taxes", "deductions", "net"}
