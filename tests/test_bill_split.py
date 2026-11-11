"""Several bills in one file (specs/pdf-table-engine-bills/test-contract.md), slice SL-06: SC-126 (finding the bills), SC-127 (uncertain boundaries go to review),
SC-128 (one record per bill, and the library), SC-129 steps 1 and 3 - 6 (the API; the browser step is SL-08's), SC-130 (reading again and retired bills), SC-115 (b),
SC-121 (3) and SC-122's BL-MULTI case, plus the contract's retry, duplicate-capture, restart and concurrent variants. SC-131 (VOID and duplicate bills) is SL-07's.

Every file goes through the real services as tests/test_paystub_split.py does: `make_pdf` into the Inbox, `capture`, `ReceiptService`, then `ExtractionService`
with the contract's doubles (`local_model` by schema, one answer per part in file order). Expected values are the contract's literals in
tests/bill_engine_fixtures.py (`exp_mini`), never what the code produced.
"""

from collections import Counter
import dataclasses
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

import bill_engine_fixtures as bf
from conftest import assert_ledger_healthy
from home_manager.app.api import create_app
from home_manager.core.jobs import Work
from home_manager.documents import bill_split, extraction
from home_manager.documents.extraction import BILL_SPLIT_CHANGED, BILL_SPLIT_FAILED, BILL_SPLIT_NOTE, ExtractionService
from home_manager.documents.reasoning import ReasoningConfig
from home_manager.finance.ledger import Ledger
from home_manager.finance.reconcile import Reconciler
from home_manager.finance.tools import FinanceTools, PeriodInput
from home_manager.library.scanner import ScanLimits
from test_bill_engine_record import ENGINE, BillRun, auto, finished, lines_of, reasons  # noqa: F401
from test_extraction import MISSING
from test_paystub_engine_record import no_network, started  # noqa: F401  (no_network is autouse: C-net)
from test_pdf import make_pdf, pdf_store  # noqa: F401

CITY = "CITY POWER & WATER"
SPLIT_REASON_A = "Page 1 prints more than one due date (07/20/2026, 08/20/2026), so it may hold more than one bill; check it and split it on the document's page."
ROWS = {"Customer Charge": "service", "Energy Charge": "usage", "State Tax": "tax_fee"}
DUES = ["2026-07-20", "2026-08-20", "2026-09-20"]


def lines_from(*pages):
    """Hand-built lines (id and text) of pages given as lists of texts: the split rule reads nothing else."""
    return [SimpleNamespace(id=f"page-{page}-layout-line-{number}", text=text) for page, texts in enumerate(pages, 1) for number, text in enumerate(texts, 1)]


def mini_texts(k, account="1234-5678-9012", due=None):
    """MINI-BILL(k)'s transcription lines as the scanned forms print them, with another account or due date when asked."""
    texts = bf.mini_transcription(k)
    texts[1] = f"Account Number {account}"
    return [text.replace(bf.MINI[k][2], due) if due else text for text in texts]


# --- The doubles ------------------------------------------------------------------------------------------------------------------

class Bills(BillRun):
    """A file of bills, read by the real services and answered by the contract's `local_model` double with one answer per part in file order."""

    def blank_free(self):
        return [line for line in self.lines if line.text.strip()]

    def pages(self):
        """The lines of each page, as the test's own idea of the split by page (not the code under test's)."""
        lines = self.blank_free()
        return [[line for line in lines if bill_split.page_of(line) == page] for page in sorted({bill_split.page_of(line) for line in lines})]

    def covered(self):
        try:
            return {line_id for table in ENGINE(self.evidence).adapted for line_id in [*(row.line_id for row in table.rows), *table.spans]}
        except Exception:  # A scanned reading has no engine pages.
            return set()

    def answer(self, stubs, parts=None, fail_summary_at=None, kinds=None, invoice_at=None, whole_invoice=False, flat=False):
        """The bills' answers. stubs: k (MINI-BILL's number), (k, account last four) or (k, account, j) per part, where j is the MINI-BILL whose statement date, period
        and due date the part prints (BL-ACCT); parts: the lines of each part (default: one per page, one part for one stub). kinds: {part index: classification}
        (bill by default; `rent` reads the part with the rent form); invoice_at: the part whose summary reads an invoice number; whole_invoice: the file is
        read again as one document, so its summary is asked once more (twice for an invoice: D5)."""
        lines = self.blank_free()
        parts = parts or (self.pages() if len(stubs) > 1 else [lines])
        covered = set() if flat else self.covered()  # flat: the engine failed, so each part is one question
        replies = {"Classification": [], "BillSummary": [], "BillLines": [], "BillRentSummary": [], "RentBillLines": []}
        for number, (part, stub) in enumerate(zip(parts, stubs)):
            k, account, j = (stub, "9012", stub) if isinstance(stub, int) else (stub[0], stub[1], stub[2] if len(stub) > 2 else stub[0])
            s, b, d, p, r, e, t, n, a = bf.MINI[k]
            s, b, d = bf.MINI[j][:3]

            def find(text, part=part):
                return next(line for line in part if line.text.startswith(text))

            def field(value, label, quote, find=find):
                return {"value": value, "status": "proposed", "evidence": [{"line_id": find(label).id, "quote": quote}]}
            iso = lambda text: f"{text[6:]}-{text[:2]}-{text[3:5]}"  # noqa: E731
            printed = any(line.text.startswith("This bill is for") for line in part)  # A scan prints no currency: the account line stands in, as the scanned regression does.
            fields = {"provider": field(CITY, CITY, CITY), "account_reference": field(account, "Account Number", f"1234-5678-{account}"),
                      "issue_date": field(iso(s), "Statement Date", s), "due_date": field(iso(d), "Due Date", d),
                      "period_start": field(iso(b[:10]), "Billing Period", b[:10]), "period_end": field(iso(b[13:]), "Billing Period", b[13:]),
                      "amount_due": field(a, "Total Amount Due", a), "new_charges": field(n, "New Charges", n),
                      "currency": field("USD", "This bill is for", "US dollars") if printed else field("USD", "Account Number", "Account Number")}
            header = self.header({}, **fields)
            if invoice_at == number:
                header = {**header, "invoice_number": field("INV-2002", "Invoice Number", "INV-2002")}
            kind = (kinds or {}).get(number, "bill")
            rent = kind == "rent"
            replies["Classification"].append({"document_type": "bill" if rent else kind, "evidence": [{"line_id": find(CITY).id, "quote": CITY}],
                                              "issuer": header["provider"], "document_date": MISSING, "bill_kind": "rent" if rent else "general",
                                              "bill_kind_evidence": [{"line_id": find("Customer Charge").id, "quote": "Customer Charge"}] if rent else []})
            replies["BillRentSummary" if rent else "BillSummary"] += [header, header] if invoice_at == number else [header]  # An invoice is asked twice (D5).
            entries = []
            for line in part:
                label = next((label for label in ROWS if line.text.startswith(label)), None)
                if label:
                    row = {"description": label, "amount": line.text.split()[-1], "quantity": None, "unit_price": None, "category": "utilities", "line_holder": None,
                           "evidence": [{"line_id": line.id, "quote": line.text}]}
                    entries.append({**row, "rent_type": {"service": "fee", "usage": "utility", "tax_fee": "fee"}[ROWS[label]], "period_start": None, "period_end": None,
                                    "usage": None} if rent else {**row, "line_kind": ROWS[label]})
            runs = []
            for line in part:
                if not runs or (line.id in covered) != runs[-1][0]:
                    runs.append([line.id in covered, []])
                runs[-1][1].append(line.id)
            replies["RentBillLines" if rent else "BillLines"] += [{"line_items": [entry for entry in entries if entry["evidence"][0]["line_id"] in ids]} for _, ids in runs]
        if fail_summary_at is not None:
            replies["BillSummary"][fail_summary_at] = {"unexpected": "not a summary"}  # A model error: the run fails as runs fail today.
        if len(stubs) > 1:
            replies["Classification"].insert(0, replies["Classification"][0])  # The file's own classification comes first.
        if whole_invoice:  # The file read again as one document: its summary is asked twice (D5), and its lines once.
            replies["BillSummary"] += [replies["BillSummary"][invoice_at]] * 2
            replies["BillLines"].append({"line_items": []})
        replies = {name: replies[name] for name in replies if replies[name]}
        self.local_model["by_schema"] = replies
        self.before = len(self.local_model["requests"])
        self.questions = sum(len(replied) for replied in replies.values())
        return replies

    def blob(self):
        return self.service.get(self.parse_id)["blob_hash"]

    def bills(self):
        """The file's bills by segment: (segment, id, Ledger record)."""
        with self.store.connection() as db:
            found = [(row["segment"], row["id"]) for row in db.execute("SELECT segment,id FROM receipts WHERE blob_hash=? ORDER BY segment", (self.blob(),))]
        return [(segment, bill_id, Ledger(self.store).record("receipt", bill_id)) for segment, bill_id in found]

    def segments(self):
        with self.store.connection() as db:
            return [tuple(row) for row in db.execute("SELECT ordinal,first_line_id,last_line_id,status,source FROM document_segments WHERE document_id=? AND blob_hash=? "
                                                     "ORDER BY ordinal", (self.doc["id"], self.blob()))]

    def starts(self):
        return [first for _, first, _, _, _ in self.segments()]

    def config(self):
        return ReasoningConfig(base_url=self.local_model["config"].base_url, model="synthetic-reasoning")


def started_bills(pdf_store, local_model, pages, name="bills.pdf"):
    run = started(pdf_store, local_model, pages, name)
    run.__class__ = Bills
    return run


def multi(pdf_store, local_model, answers=(1, 2, 3), pages=None, **options):
    """BL-MULTI (or another file) read and answered, not yet extracted."""
    run = started_bills(pdf_store, local_model, pages if pages is not None else bf.mini_pages(1, 2, 3))
    run.answer(list(answers), **options)
    return run


def notes_of(record):
    return (record["details"] or {}).get("notes", [])


def noted(record, text):
    """C-note: the text is among the bill's notes and not among its issues."""
    assert text in notes_of(record) and text not in record["issues"], (text, notes_of(record), record["issues"])


def expect_mini(record, k, account=None):
    """EXP-MINI(k): lines, total, amount due, due date, previous balance and payments, both checks."""
    wanted = bf.exp_mini(k)
    assert lines_of(record) == wanted["lines"]
    assert (record["total_minor"], record["amount_due_minor"], record["due_date"]) == (wanted["total_minor"], wanted["amount_due_minor"], wanted["due_date"])
    assert (record["details"]["previous_balance"]["minor"], record["details"]["payments_received"]["minor"]) == (wanted["previous_balance"], wanted["payments_received"])
    checks = {check["name"]: check for check in record["checks"]}
    assert checks["lines"]["passes"] and checks["carried"]["passes"]
    if account:
        assert record["account_last_four"] == account


def segment_check(run, count):
    """C-segments(n): n `document_segments` rows with ordinals 0 … n−1 (none for a file read as one), the file's receipts rows are segments 0 … n−1, and every
    line of the reading is in exactly one segment's range."""
    segments = run.segments()
    assert [row[0] for row in segments] == (list(range(count)) if count > 1 else [])
    assert [segment for segment, _, _ in run.bills()] == list(range(count))
    if count > 1:
        ids = [line.id for line in run.blank_free()]
        spans = [(ids.index(first), ids.index(last)) for _, first, last, _, _ in segments]
        assert spans[0][0] == 0 and spans[-1][1] == len(ids) - 1 and all(spans[i][1] + 1 == spans[i + 1][0] for i in range(len(spans) - 1))


def spending(store, start, end):
    rows = FinanceTools(store).get_spending(PeriodInput(start=start, end=end))["by_currency"]
    return rows[0]["spending"]["minor"] if rows else 0


# === SC-126 step 7: key lines and the rule, on hand-built lines ===========================================================================

def key_of(text):
    key = bill_split.key_of(SimpleNamespace(id="page-1-layout-line-1", text=text))
    return None if key is None else (key.kind, key.value)


def test_sc126_an_account_masked_or_in_full_is_the_same_account():
    assert key_of("Account #: ****9012") == key_of("Account Number 1234-5678-9012") == ("account", "9012")
    assert key_of("Account no. ****3456") == ("account", "3456")


def test_sc126_a_payment_due_line_with_dot_leaders_is_a_due_date_key():
    assert key_of("Payment Due ........ 10/15/2026") == ("due_date", (10, 15, 2026))
    assert key_of("Due Date | 07/20/2026") == key_of("Due Date 07/20/2026") == ("due_date", (7, 20, 2026))
    assert key_of("Statement Date 2026-08-03") == ("statement_date", (8, 3, 2026))


@pytest.mark.parametrize("text", ["Your previous bill, due 09/15/2026, is past due", "Late fee if not paid by 10/15/2026", "Previous Statement Date 08/20/2026",
                                  "Rent and Leasing Charges Due 10/01/2026", "Billing Period 06/01/2026 - 06/30/2026", "Service Period 06/01/2026 - 06/30/2026",
                                  "Due Date", "Account Balance 100.00", "Due Date upon receipt 07/20/2026"])
def test_sc126_a_sentence_text_before_the_label_a_period_or_a_label_with_no_value_is_no_key_line(text):
    assert key_of(text) is None


def test_sc126_a_page_whose_only_differing_value_is_its_billing_period_continues_the_open_bill():
    first, second = mini_texts(1), mini_texts(1)
    second[3] = "Billing Period 07/01/2026 - 07/31/2026"
    assert bill_split.bill_parts(lines_from(first, second)).parts == [(0, 30)]


def test_sc126_a_part_with_no_amount_due_anchor_joins_the_part_before_and_the_first_joins_the_next():
    late = ["CITY POWER & WATER", "Account Number 1234-5678-9012", "Due Date 08/20/2026", "Late fee if paid after 08/25/2026, pay 90.00"]
    lines = lines_from(mini_texts(1), late)
    split = bill_split.bill_parts(lines)
    assert split.parts == [(0, 19)] and len(split.reasons[0]) == 1  # A late-payment line is no amount due: the part joins the bill before it.
    first = lines_from(["CITY POWER & WATER", "Due Date 07/20/2026"], mini_texts(2))
    split = bill_split.bill_parts(first)
    assert split.parts == [(0, 17)] and split.reasons[0][0].endswith("so it was read with the bill after it; check how the file was split.")


def test_sc126_two_hundred_and_one_one_page_bills_are_two_hundred_and_one_parts_and_the_run_reads_them_as_one(pdf_store, local_model, monkeypatch, caplog):
    pages = [["Account Number 1234-5678-9012", f"Due Date {1 + page // 28:02d}/{1 + page % 28:02d}/2026", "Total Amount Due 10.00"] for page in range(201)]
    assert len(bill_split.bill_parts(lines_from(*pages)).parts) == 201
    run = multi(pdf_store, local_model, (1,), pages=bf.mini_pages(1))
    monkeypatch.setattr(bill_split, "bill_parts", lambda lines: bill_split.BillSplit([(0, 1)] * 201))
    run.extract()
    [(_, _, record)] = run.bills()
    reasons(record, BILL_SPLIT_FAILED)
    assert [entry for entry in caplog.records if "bill split" in entry.getMessage()]
    assert not [entry for entry in caplog.records if CITY in entry.getMessage() or "81.42" in entry.getMessage()]


# === SC-126 steps 1 - 4 and SC-128 step 1: BL-MULTI and the files that are one bill or two ================================================

def test_sc126_bl_multi_is_three_bills_with_their_due_dates_and_sc128_each_is_read_on_its_own_lines(pdf_store, local_model):
    run = multi(pdf_store, local_model)
    before = run.fingerprint()
    run.extract()
    bills = run.bills()
    segment_check(run, 3)
    assert [record["due_date"] for _, _, record in bills] == DUES
    for (_, _, record), k in zip(bills, (1, 2, 3)):
        expect_mini(record, k, "9012")
        noted(record, BILL_SPLIT_NOTE)
        auto(record)
    assert [(record["total_minor"], record["amount_due_minor"]) for _, _, record in bills] == [(8142, 8142), (8726, 8726), (7472, 11198)]
    assert [record["details"]["previous_balance"]["minor"] for _, _, record in bills] == [8000, 8142, 8726]
    assert [record["details"]["payments_received"]["minor"] for _, _, record in bills] == [8000, 8142, 5000]
    assert [record["review_status"] for _, _, record in bills] == ["verified"] * 3
    assert Counter(run.asked())["Classification"] == 4 and run.asked()[:4] == ["Classification"] * 4  # The file's, then one per part before any part is read.
    assert len(run.asked()) == run.questions
    assert all(row for row in run.run["publication"]["segments"]) and [row["status"] for row in run.run["publication"]["segments"]] == ["published"] * 3
    assert run.fingerprint() == before
    assert_ledger_healthy(run.store)


def test_sc126_bl_remit_a_remittance_stub_and_a_repeated_header_are_one_bill_with_no_split_note(pdf_store, local_model):
    from test_bill_engine_record import expect_util, util
    run = util(pdf_store, local_model, pages=bf.remit_pages(), rows=bf.STUB_UTIL)
    record = expect_util(run)
    run.__class__ = Bills
    assert BILL_SPLIT_NOTE not in notes_of(record) and not run.segments() and "segments" not in run.run["publication"]
    segment_check(run, 1)


def test_sc126_bl_acct_the_same_dates_for_another_account_are_two_bills(pdf_store, local_model):
    run = multi(pdf_store, local_model, ((1, "9012"), (2, "3456", 1)), pages=bf.acct_pages())
    run.extract()
    segment_check(run, 2)
    first, second = [record for _, _, record in run.bills()]
    assert (first["account_last_four"], second["account_last_four"]) == ("9012", "3456")
    expect_mini(first, 1)
    assert lines_of(second) == [("Customer Charge", 1200, "service"), ("Energy Charge", 7020, "usage"), ("State Tax", 506, "tax_fee")]
    assert (second["total_minor"], second["amount_due_minor"], second["due_date"]) == (8726, 8726, "2026-07-20")
    for record in (first, second):
        noted(record, BILL_SPLIT_NOTE)
        auto(record)


def test_sc126_bl_util_is_one_bill_and_no_segment_row(pdf_store, local_model):
    from test_bill_engine_record import expect_util, util
    run = util(pdf_store, local_model, rows=bf.STUB_UTIL)
    expect_util(run)
    run.__class__ = Bills
    segment_check(run, 1)
    assert BILL_SPLIT_NOTE not in run.notes


def started_scan(pdf_store, local_model, transcriptions, name="scan.pdf"):
    """A scanned PDF (image-only pages) whose vision stub transcribes each page in turn: no text page, so the bill engine never runs (MULTI-SCAN)."""
    from conftest import inbox_scan
    from home_manager.documents.receipt_service import ReceiptService
    inbox, store = pdf_store
    make_pdf(inbox / name, [None] * len(transcriptions))
    inbox_scan(store)
    doc = next(item for item in store.documents()["items"] if item["relative_path"].endswith(name))
    local_model["outputs"] = [{"full_text": "\n".join(texts)} for texts in transcriptions]
    service = ReceiptService(store)
    parse_id, _ = service.enqueue(doc["id"], vision=local_model["config"])
    service.run(parse_id, Work.detached())
    assert service.get(parse_id)["status"] == "succeeded", service.get(parse_id)["error"]
    assert [page["method"] for page in service.get(parse_id)["result"]["pages"]] == ["vision_model"] * len(transcriptions)
    return Bills(store, service, local_model, parse_id, doc)


def no_engine(run):
    """SC-126 step 5: the lines' evidence cites transcription lines (no engine cell), the line questions carry no engine table or direction, and no FR-110 note."""
    for question in run.requests("BillLines"):
        assert "reported_tables" not in question
    assert all("copies each amount" not in request["messages"][0]["content"] for request in run.local_model["requests"][run.before:])
    for _, _, record in run.bills():
        assert not [note for note in notes_of(record) if note.startswith("Page ") or "charge lines couldn't be read" in note]
        assert not any((item.get("cell_evidence") or (item.get("details") or {}).get("unit_price")) for item in record["items"])
        assert (record["details"] or {}).get("guesses") is None


def expect_read(record, k):
    """EXP-MINI(k) for a bill read like a photographed one: lines, total, amount due and due date (no engine anchors, so no previous balance or payments)."""
    wanted = bf.exp_mini(k)
    assert lines_of(record) == wanted["lines"]
    assert (record["total_minor"], record["amount_due_minor"], record["due_date"]) == (wanted["total_minor"], wanted["amount_due_minor"], wanted["due_date"])


def test_sc126_a_scanned_pdf_of_three_bills_is_three_bills_each_read_like_a_photographed_one(pdf_store, local_model):
    run = started_scan(pdf_store, local_model, [bf.mini_transcription(k) for k in (1, 2, 3)])
    run.answer([1, 2, 3])
    run.extract()
    segment_check(run, 3)
    bills = run.bills()
    assert [record["due_date"] for _, _, record in bills] == DUES
    for (_, _, record), k in zip(bills, (1, 2, 3)):
        expect_read(record, k)
        noted(record, BILL_SPLIT_NOTE)
    no_engine(run)


def combined_images(tmp_path, local_model, transcriptions):
    """Three PNGs combined into one document (MULTI-IMAGES): the manager, the lead's document and its reading."""
    from home_manager.app.manager import Manager
    from test_document_groups import images
    manager = Manager(tmp_path / "control", ScanLimits(stability_seconds=0))
    manager.configure(str(tmp_path / "managed"))
    images(manager.store.library.inbox, [f"bill_p{number}.png" for number in range(1, len(transcriptions) + 1)])
    manager.start_inbox()
    manager.future.result(timeout=30)
    [group] = manager.suggested_groups()
    manager.configure_vision(local_model["config"])
    local_model["outputs"] = [{"full_text": "\n".join(texts)} for texts in transcriptions]
    manager.change_group(group["id"], "confirmed")
    manager.future.result(timeout=60)
    lead = group["pages"][0]["document_id"]
    doc = next(item for item in manager.store.documents()["items"] if item["id"] == lead)
    parse_id = next(row["id"] for row in manager.receipts.history(lead) if row["parser_version"] == "receipt-images-v2-tables")
    assert manager.receipts.get(parse_id)["status"] == "succeeded"
    return manager, Bills(manager.store, manager.receipts, local_model, parse_id, doc)


def test_sc126_three_images_combined_into_one_document_are_three_bills_each_read_like_a_photographed_one(tmp_path, local_model):
    manager, run = combined_images(tmp_path, local_model, [bf.mini_transcription(k) for k in (1, 2, 3)])
    try:
        run.answer([1, 2, 3])
        run.extract()
        segment_check(run, 3)
        assert [record["due_date"] for _, _, record in run.bills()] == DUES
        for (_, _, record), k in zip(run.bills(), (1, 2, 3)):
            expect_read(record, k)
        no_engine(run)
    finally:
        manager.close()


def test_sc126_a_single_photographed_bill_is_one_bill_with_no_segment_row(tmp_path, local_model):
    from test_extraction import transcribe
    manager, doc, parse_id = transcribe(tmp_path, local_model, bf.mini_transcription(1))
    try:
        run = Bills(manager.store, manager.receipts, local_model, parse_id, doc)
        run.answer([1])
        run.extract()
        segment_check(run, 1)
        expect_read(run.bills()[0][2], 1)
        assert BILL_SPLIT_NOTE not in notes_of(run.bills()[0][2])
    finally:
        manager.close()


# === SC-127: uncertain boundaries go to review =============================================================================================

def amounts_of(record):
    return [amount for _, amount, _ in lines_of(record)]


def test_sc127_bl_join_a_part_with_no_amount_due_of_its_own_is_read_with_the_bill_before_it(pdf_store, local_model):
    run = started_bills(pdf_store, local_model, bf.join_pages())
    pages = run.pages()
    run.answer([1, 3], parts=[pages[0] + pages[1], pages[2]])
    run.extract()
    segment_check(run, 2)
    first, second = [record for _, _, record in run.bills()]
    reasons(first, "Page 2 prints its own due date (08/20/2026) but no amount due, so it was read with the bill before it; check how the file was split.")
    assert amounts_of(first) == [1200, 6480, 462, 1200, 7020, 506] and sum(amounts_of(first)) == 16868
    reasons(first, "New charges: the lines add up to 168.68 USD", "81.42 USD")
    assert first["total_minor"] == 8142 and first["amount_due_minor"] == 8142
    assert first["details"]["previous_balance"]["minor"] == 8000 and first["details"]["payments_received"]["minor"] == 8000
    assert {check["name"]: check["passes"] for check in first["checks"]}["carried"]
    for fact in ("new charges", "previous balance", "payment received"):
        assert [note for note in notes_of(first) if fact in note.lower() and "81.42" in note], fact
    assert [note for note in notes_of(first) if "new charges" in note.lower() and "87.26" in note]
    expect_mini(second, 3)
    noted(second, BILL_SPLIT_NOTE)
    auto(second)


@pytest.mark.parametrize("pages_of,reason,lines_reason", [
    (bf.two_on_page_pages, SPLIT_REASON_A, ("New charges: the lines add up to 168.68 USD", "81.42 USD")),
    (bf.nokey_pages, "This bill prints new charges of 81.42 and 87.26 on different pages, so the file may hold more than one bill; check it and split it on the document's "
                     "page.", ("New charges: the lines add up to 168.68 USD", "81.42 USD"))], ids=["BL-TWOONPAGE", "BL-NOKEY"])
def test_sc127_a_file_that_may_hold_two_bills_but_cannot_be_split_between_pages_is_one_bill_in_review(pdf_store, local_model, pages_of, reason, lines_reason):
    run = multi(pdf_store, local_model, (1,), pages=pages_of())
    run.extract()
    segment_check(run, 1)
    [(_, _, record)] = run.bills()
    reasons(record, reason)
    reasons(record, *lines_reason)
    assert record["amount_due_minor"] == 8142
    assert not [note for note in notes_of(record) if "amount due is printed as" in note]  # The carried check picks 81.42: no guess note.
    assert BILL_SPLIT_NOTE not in notes_of(record)


@pytest.mark.parametrize("fault", ["raises", "201 parts"])
def test_sc127_a_split_rule_that_fails_reads_the_file_as_one_bill_with_reason_d_and_logs_no_text(pdf_store, local_model, monkeypatch, caplog, fault):
    def broken(lines):
        if fault == "raises":
            raise RuntimeError("injected split fault")
        return bill_split.BillSplit([(0, 1)] * 201)

    monkeypatch.setattr(bill_split, "bill_parts", broken)
    run = multi(pdf_store, local_model, (1,))
    run.answer([1], parts=[run.blank_free()])
    run.extract()
    segment_check(run, 1)
    [(_, _, record)] = run.bills()
    reasons(record, "Where each bill starts couldn't be read, so the file was read as one; check whether it holds more than one bill.")
    failures = [entry for entry in caplog.records if "bill split" in entry.getMessage()]
    assert len(failures) == 1 and "Error" in failures[0].getMessage()
    assert not [entry for entry in caplog.records if CITY in entry.getMessage() or "81.42" in entry.getMessage()]
    assert run.run["publication"]["segments"][0]["one"] is True  # FR-131: Split here is offered for it.


def test_sc127_a_split_you_confirm_raises_none_of_these_reasons(pdf_store, local_model):
    run = started_bills(pdf_store, local_model, bf.join_pages())
    pages = run.pages()
    run.answer([1, 3], parts=[pages[0] + pages[1], pages[2]])
    run.extract()
    first = run.bills()[0][2]
    assert len([issue for issue in first["issues"] if "Page 2 prints its own due date" in issue]) == 1
    assert run.extraction.confirm_split(run.doc["id"])["confirmed"] is True
    first, second = [record for _, _, record in run.bills()]
    assert [issue for issue in first["issues"] if "Page 2 prints its own due date" in issue] == []
    assert [issue for issue in first["issues"] if issue.startswith("New charges: the lines add up to")] and first["review_status"] == "needs_review"
    assert BILL_SPLIT_NOTE not in notes_of(second) and BILL_SPLIT_NOTE not in notes_of(first)
    run.answer([1, 3], parts=[pages[0] + pages[1], pages[2]])
    run.extract(force=True)  # Read again, the confirmed split raises none of FR-129's reasons and carries no note.
    first = run.bills()[0][2]
    assert [issue for issue in first["issues"] if "Page 2 prints its own due date" in issue] == [] and BILL_SPLIT_NOTE not in notes_of(first)


# === The app: the library row, the split API and the actions a user takes ===============================================================

@pytest.fixture
def app(tmp_path, local_model):
    """The real app on a managed library: (client, manager); the reasoning model is the contract's `local_model` and home currency USD."""
    from home_manager.finance.ledger import HouseholdConfig
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        manager = app.state.manager
        manager.configure_reasoning(ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning"))
        manager.configure_household(HouseholdConfig(home_currency="USD", auto_identify_items=False))
        yield client, manager


def started_in(manager, local_model, pages, name="bills.pdf"):
    """A fixture captured into the app's Inbox and read by the real reader, as `started` does for a bare library."""
    from conftest import inbox_scan
    make_pdf(manager.store.library.inbox / name, pages)
    inbox_scan(manager.store)
    doc = next(item for item in manager.store.documents()["items"] if item["relative_path"].endswith(name))
    parse_id, _ = manager.receipts.enqueue(doc["id"], vision=local_model["config"])
    manager.receipts.run(parse_id, Work.detached())
    assert manager.receipts.get(parse_id)["status"] == "succeeded"
    run = Bills(manager.store, manager.receipts, local_model, parse_id, doc)
    return run


def extract_through_app(manager, run):
    """Extract as the app does (the reading, then filing), waiting for it."""
    started_run = manager.start_extraction(run.doc["id"], run.parse_id, force=True)
    manager.future.result(timeout=60)
    run.run = run.extraction.get(started_run["run_id"])
    assert run.run["status"] == "succeeded", run.run["error"]
    return run.run


def bill_ids(run):
    return [bill_id for _, bill_id, _ in run.bills()]


def library_row(client, run):
    return client.get(f"/api/documents/{run.doc['id']}").json()


def test_sc128_the_library_shows_no_single_amount_for_three_bills_and_the_first_non_rejected_bills_dates(app, local_model):
    client, manager = app
    run = started_in(manager, local_model, bf.mini_pages(1, 2, 3))
    run.answer([1, 2, 3])
    extract_through_app(manager, run)
    shown = library_row(client, run)
    assert (shown["ledger_amount_minor"], shown["ledger_currency"]) == (None, None)
    assert (shown["document_date"], shown["merchant"], shown["due_date"]) == ("2026-07-20", CITY, "2026-07-20")
    assert (shown["bill_period_start"], shown["bill_period_end"]) == ("2026-06-01", "2026-06-30")
    with manager.store.connection() as db:
        [filed] = [row["relative_path"] for row in db.execute("SELECT relative_path FROM managed_files")]
    assert filed.startswith("Bills/2026/") and "CITY_POWER_WATER" in filed  # Filed under the first bill's provider, as a one-bill file is.
    ids = bill_ids(run)
    manager.ledger.review("receipt", ids[0], "rejected")  # After the user rejects bill 1 the first non-rejected bill is bill 2.
    shown = library_row(client, run)
    assert (shown["document_date"], shown["due_date"], shown["bill_period_start"], shown["bill_period_end"], shown["ledger_amount_minor"]) == (
        "2026-08-20", "2026-08-20", "2026-07-01", "2026-07-31", None)
    manager.ledger.review("receipt", ids[1], "rejected")  # One non-rejected bill left: as for any single bill.
    shown = library_row(client, run)
    assert (shown["ledger_amount_minor"], shown["ledger_currency"], shown["due_date"], shown["document_date"]) == (7472, "USD", "2026-09-20", "2026-09-20")


def test_sc128_the_library_row_takes_its_due_date_and_period_from_the_first_non_rejected_bill_by_segment_not_by_insertion(app):
    from conftest import documents_by_name, inbox_scan
    from test_reconcile_tools import source_of
    client, manager = app
    inbox_scan(manager.store, {"two.pdf": b"synthetic file holding two bills"})
    doc = documents_by_name(manager.store)["two.pdf"]

    def bill(provider, due, total):
        return {"provider": provider, "due_date": due, "issue_date": None, "period_start": f"{due[:8]}01", "period_end": due, "currency": "USD", "total_minor": total,
                "amount_due_minor": total, "issues": [], "locator": {}, "items": []}
    manager.ledger.publish_bill(bill("SECOND CO", "2026-09-20", 100), {**source_of(doc, "extraction:two"), "segment": 1}, "verified")  # Published first.
    manager.ledger.publish_bill(bill("FIRST CO", "2026-08-20", 200), {**source_of(doc, "extraction:two"), "segment": 0}, "verified")
    shown = client.get(f"/api/documents/{doc['id']}").json()
    assert (shown["merchant"], shown["due_date"], shown["bill_period_start"], shown["bill_period_end"], shown["document_date"]) == (
        "FIRST CO", "2026-08-20", "2026-08-01", "2026-08-20", "2026-08-20")
    assert shown["ledger_amount_minor"] is None


def filed_paths(manager):
    with manager.store.connection() as db:
        return [row["relative_path"] for row in db.execute("SELECT relative_path FROM managed_files")]


def test_sc128_the_file_is_filed_under_the_first_bills_due_date(app, local_model):
    client, manager = app
    run = started_in(manager, local_model, bf.mini_pages(1, 2, 3))
    run.answer([1, 2, 3])
    extract_through_app(manager, run)
    [filed] = filed_paths(manager)
    assert filed.startswith("Bills/2026/07/2026-07-20__CITY_POWER_WATER")


def test_fr120_a_file_of_one_bill_is_filed_under_its_statement_date_as_before(app, local_model):
    client, manager = app
    run = started_in(manager, local_model, bf.mini_pages(1))
    run.answer([1])
    extract_through_app(manager, run)
    [filed] = filed_paths(manager)
    assert filed.startswith("Bills/2026/07/2026-07-02__CITY_POWER_WATER")  # MINI-BILL(1) is dated 07/02/2026 and due 07/20/2026.


def test_fr135_filing_follows_the_first_non_rejected_bill_whenever_the_file_is_filed_again(app, local_model):
    client, manager = app
    run = started_in(manager, local_model, bf.mini_pages(1, 2, 3))
    run.answer([1, 2, 3])
    extract_through_app(manager, run)
    [before] = filed_paths(manager)
    assert "2026-07-20__" in before
    manager.ledger.review("receipt", bill_ids(run)[0], "rejected")
    assert filed_paths(manager) == [before]  # Rejecting a bill renames nothing: filing is only refreshed when the file is extracted or filed again.
    manager.file_extraction(run.doc["id"], run.run["id"])  # Extract on an unchanged file files again from the first bill still counting.
    [after] = filed_paths(manager)
    assert after.startswith("Bills/2026/08/2026-08-20__CITY_POWER_WATER")


def test_sc128_spending_counts_each_bill_on_its_own_due_date(pdf_store, local_model):
    run = multi(pdf_store, local_model)
    run.extract()
    assert [spending(run.store, day, day) for day in DUES] == [8142, 8726, 7472]
    assert spending(run.store, "2026-07-01", "2026-09-30") == 24340


def test_sc128_a_payment_to_the_provider_is_proposed_as_bill_1s_match_only(pdf_store, local_model):
    from test_reconcile_tools import add
    run = multi(pdf_store, local_model)
    run.extract()
    checking = Ledger(run.store).create_account("First Local Bank", "checking", "USD")
    [payment] = add(run.store, Ledger(run.store), checking, run.doc, [("2026-07-18", CITY, -8142)])
    Reconciler(run.store).run()
    with run.store.connection() as db:
        links = {bill_id: [tuple(row) for row in db.execute("SELECT transaction_id,review_status FROM transaction_receipt_links WHERE receipt_id=?", (bill_id,))]
                 for bill_id in bill_ids(run)}
    first, second, third = bill_ids(run)
    assert links == {first: [(payment, "proposed")], second: [], third: []}


def test_sc128_a_part_classified_as_rent_is_read_with_the_rent_form_and_the_others_as_general(pdf_store, local_model):
    run = multi(pdf_store, local_model, kinds={1: "rent"})
    run.extract()
    with run.store.connection() as db:
        kinds = [row["bill_kind"] for row in db.execute("SELECT bill_kind FROM receipts WHERE blob_hash=? ORDER BY segment", (run.blob(),))]
    assert kinds == ["general", "rent", "general"]
    assert run.asked().count("BillRentSummary") == 1 and run.asked().count("BillSummary") == 2 and run.asked().count("RentBillLines") >= 1
    segment_check(run, 3)


def test_sc128_a_part_that_is_not_a_bill_makes_the_file_one_document(pdf_store, local_model):
    run = started_bills(pdf_store, local_model, bf.mini_pages(1, 2, 3))
    three, one = run.answer([1, 2, 3]), run.answer([1])  # The three parts are classified (the second is a receipt); then the whole file is read as one.
    run.local_model["by_schema"] = {"Classification": [*three["Classification"][:2], {**three["Classification"][2], "document_type": "receipt"}],
                                    "BillSummary": one["BillSummary"], "BillLines": one["BillLines"]}
    run.extract()
    assert run.run["result"]["split_notes"] == ["A part of this file is not a bill, so the file was read as one document."]
    segment_check(run, 1)
    assert "segments" not in run.run["publication"]


def test_sc128_a_part_that_reads_as_an_invoice_makes_the_file_one_document_on_todays_path(pdf_store, local_model):
    run = multi(pdf_store, local_model, pages=bf.multi_inv_pages(), invoice_at=1, whole_invoice=True)
    run.extract()
    segment_check(run, 1)
    [(_, _, record)] = run.bills()
    assert run.run["result"]["split_notes"] == ["A part of this file is an invoice, so the file was read as one document."]
    assert record["invoice"] is not None and BILL_SPLIT_NOTE not in notes_of(record)
    for question in run.requests("BillLines")[-1:]:  # The whole file is read on the anchor_rows path: no engine table.
        assert not [table for table in question.get("reported_tables", []) if "charges" in table["table_id"]]


def test_sc128_a_split_inside_a_table_gives_each_part_its_own_rows_and_every_line_one_segment(app, local_model):
    client, manager = app
    run = started_in(manager, local_model, bf.mini_pages(1, 2, 3))
    run.answer([1, 2, 3])
    extract_through_app(manager, run)
    lines = run.blank_free()
    energy = next(line for line in lines if line.text.startswith("Energy Charge"))
    firsts = [next(line for line in lines if bill_split.page_of(line) == page) for page in (1, 2, 3)]
    starts = [firsts[0].id, energy.id, firsts[1].id, firsts[2].id]
    answer = client.put(f"/api/documents/{run.doc['id']}/segments", json={"starts": starts})
    assert answer.status_code == 202
    manager.future.result(timeout=60)
    ids = [line.id for line in lines]
    shown = client.get(f"/api/documents/{run.doc['id']}/segments").json()
    spans = [(ids.index(row["first_line_id"]), ids.index(row["last_line_id"])) for row in shown["segments"]]
    assert len(spans) == 4 and spans[0][0] == 0 and spans[-1][1] == len(ids) - 1 and all(spans[i][1] + 1 == spans[i + 1][0] for i in range(3))
    reading = bill_tables_read(run)
    from home_manager.finance import bill_tables
    inside = lambda span: {line.id for line in lines[span[0]:span[1] + 1]}  # noqa: E731
    before, after = (bill_tables.for_lines(reading, inside(span)) for span in spans[:2])
    labels = lambda part: [row.label for table in part.reading.tables for row in table.rows]  # noqa: E731
    assert labels(before) == ["Customer Charge"] and labels(after) == ["Energy Charge", "State Tax"]


def bill_tables_read(run):
    from home_manager.finance import bill_tables
    return bill_tables.read(run.evidence)


# === SC-129: no review for a certain split; the user can change it (API steps 1 and 3 - 6) =================================================

def test_sc129_the_split_api_lists_three_bills_none_in_review_for_the_split_and_the_users_change_wins(app, local_model):
    client, manager = app
    run = started_in(manager, local_model, bf.mini_pages(1, 2, 3))
    before = run.fingerprint()
    run.answer([1, 2, 3])
    run.extract()
    # Step 1: each bill carries the split note, none waits for the split, and the segments endpoint names each bill.
    for _, _, record in run.bills():
        noted(record, BILL_SPLIT_NOTE)
        auto(record)
    shown = client.get(f"/api/documents/{run.doc['id']}/segments").json()
    assert shown["confirmed"] is False and len(shown["segments"]) == 3 and "one" not in shown
    assert [(row["kind"], row["merchant"], row["due_date"], row["display"]) for row in shown["segments"]] == [
        ("bill", CITY, due, {"amount_due": f"{amount} USD"}) for due, amount in zip(DUES, ("81.42", "87.26", "111.98"))]
    assert [row["status"] for row in shown["segments"]] == ["proposed"] * 3
    starts = run.starts()
    # Step 3: Merge with next on bill 2 (starts of bills 1 and 2 only): the file is read again with the user's split.
    pages = run.pages()
    run.answer([1, 2], parts=[pages[0], pages[1] + pages[2]])
    assert client.put(f"/api/documents/{run.doc['id']}/segments", json={"starts": starts[:2]}).status_code == 202
    manager.future.result(timeout=60)
    assert len(run.segments()) == 2 and [row[3] for row in run.segments()] == ["confirmed"] * 2
    bills = run.bills()
    assert [segment for segment, _, _ in bills] == [0, 1, 2]
    expect_mini(bills[0][2], 1)
    retired = bills[2][2]
    assert (retired["review_status"], retired["review_source"]) == ("rejected", "automatic")
    assert "The latest reading of this file no longer finds this bill; check how the file was split." in retired["issues"]
    for _, _, record in bills[:2]:
        noted(record, BILL_SPLIT_CHANGED)
        assert [guess["kind"] for guess in record["details"]["guesses"]].count("split_changed") == 1
        assert BILL_SPLIT_NOTE not in notes_of(record)
    # Step 4: Extract again still has two segments: the user's split wins.
    run.answer([1, 2], parts=[pages[0], pages[1] + pages[2]])
    run.extract(force=True)
    assert [row[0] for row in run.segments()] == [0, 1] and len(run.run["publication"]["segments"]) == 2
    # Step 5: Confirm split: the file is confirmed; the merged bill keeps its lines reason (G9), and bill 1 is judged by its own checks.
    confirmed = client.post(f"/api/documents/{run.doc['id']}/segments/confirm").json()
    assert confirmed["confirmed"] is True
    first, merged = [record for _, _, record in run.bills()[:2]]
    assert BILL_SPLIT_NOTE not in notes_of(first) and BILL_SPLIT_NOTE not in notes_of(merged)
    assert first["review_status"] == "verified" and merged["review_status"] == "needs_review"
    assert [issue for issue in merged["issues"] if issue.startswith("New charges: the lines add up to")]
    assert run.fingerprint() == before


def test_sc129_a_bill_read_as_one_with_reason_a_is_offered_split_here_and_splitting_it_makes_two_verified_bills(app, local_model):
    client, manager = app
    run = started_in(manager, local_model, bf.two_on_page_pages())
    run.answer([1])
    run.extract()
    [(_, _, record)] = run.bills()
    reasons(record, SPLIT_REASON_A)
    # Step 6: the panel offers Split here although the file is one bill.
    shown = client.get(f"/api/documents/{run.doc['id']}/segments").json()
    lines = run.blank_free()
    assert shown["one"] is True and shown["confirmed"] is False and len(shown["segments"]) == 1
    [one] = shown["segments"]
    assert (one["kind"], one["ordinal"], one["first_line_id"], one["last_line_id"]) == ("bill", 0, lines[0].id, lines[-1].id)
    assert (one["merchant"], one["due_date"], one["display"]) == (CITY, "2026-07-20", {"amount_due": "81.42 USD"})
    assert run.run["publication"]["segments"][0]["one"] is True and run.run["publication"]["split_confirmed"] is False
    assert run.segments() == []  # Nothing is saved for the offer.
    second = [index for index, line in enumerate(lines) if line.text == CITY][1]  # MINI-BILL(2)'s first line.
    run.answer([1, 2], parts=[lines[:second], lines[second:]])
    assert client.put(f"/api/documents/{run.doc['id']}/segments", json={"starts": [lines[0].id, lines[second].id]}).status_code == 202
    manager.future.result(timeout=60)
    segment_check(run, 2)
    first, second_bill = [record for _, _, record in run.bills()]
    expect_mini(first, 1)
    expect_mini(second_bill, 2)
    for record in (first, second_bill):
        assert [issue for issue in record["issues"] if "more than one due date" in issue] == []
        assert record["review_status"] == "verified"


def test_sc129_confirm_split_is_refused_for_a_file_that_is_one_bill(pdf_store, local_model):
    run = multi(pdf_store, local_model, (1,), pages=bf.two_on_page_pages())
    run.extract()
    with pytest.raises(ValueError, match="not split"):
        run.extraction.confirm_split(run.doc["id"])


# === SC-130: reading again and retired bills ===============================================================================

def rows_of(run):
    """The rows a reading wrote (test_bill_engine_record.SNAPSHOT), without the clock or the run's own id; the evidence links without their source key."""
    from test_bill_engine_record import snapshot
    return snapshot(run)


def test_sc130_extract_again_twice_gives_the_same_three_bills_segments_lines_notes_and_split(pdf_store, local_model):
    run = multi(pdf_store, local_model)
    run.extract()
    first, ids = rows_of(run), bill_ids(run)
    notes_first = [notes_of(record) for _, _, record in run.bills()]
    for _ in range(2):
        run.answer([1, 2, 3])
        run.extract(force=True)
        assert bill_ids(run) == ids and rows_of(run) == first
        assert [notes_of(record) for _, _, record in run.bills()] == notes_first


def merge_bill_two(run):
    """Merge with next on bill 2: the user's split has the starts of bills 1 and 2 only; the file is read again."""
    pages = run.pages()
    starts = run.starts()
    run.extraction.set_split(run.doc["id"], starts[:2])
    run.answer([1, 2], parts=[pages[0], pages[1] + pages[2]])
    run.extract(force=True)


RETIRED = "The latest reading of this file no longer finds this bill; check how the file was split."


def test_sc130_a_bill_the_new_split_no_longer_finds_stops_counting_and_comes_back_when_found_again(pdf_store, local_model):
    run = multi(pdf_store, local_model)
    run.extract()
    ids = bill_ids(run)
    starts = run.starts()
    merge_bill_two(run)
    third = run.bills()[2][2]
    assert (third["review_status"], third["review_source"]) == ("rejected", "automatic") and RETIRED in third["issues"]
    assert spending(run.store, "2026-09-20", "2026-09-20") == 0
    # Splitting back: the automatically rejected bill is found again and restored, not a new id.
    run.extraction.set_split(run.doc["id"], starts)
    run.answer([1, 2, 3])
    run.extract(force=True)
    assert bill_ids(run) == ids
    third = run.bills()[2][2]
    assert third["review_status"] == "verified" and third["review_source"] == "automatic" and RETIRED not in third["issues"]
    assert spending(run.store, "2026-09-20", "2026-09-20") == 7472


def test_sc130_a_bill_you_decided_keeps_your_decision_and_gets_the_note(app, local_model):
    client, manager = app
    run = started_in(manager, local_model, bf.mini_pages(1, 2, 3))
    run.answer([1, 2, 3])
    run.extract()
    third_id = bill_ids(run)[2]
    manager.ledger.review("receipt", third_id, "verified")  # The user decides bill 3 first.
    merge_bill_two(run)
    third = run.bills()[2][2]
    assert (third["review_status"], third["review_source"]) == ("verified", "user") and RETIRED in third["issues"]
    assert spending(run.store, "2026-09-20", "2026-09-20") == 7472


# === SC-115 (b), SC-121 (3) and SC-122 for BL-MULTI ========================================================================================

def test_sc115_b_when_the_engine_fails_every_bill_of_the_file_is_read_like_a_photographed_one_with_one_log_record(pdf_store, local_model, monkeypatch, caplog):
    from home_manager.finance import bill_tables

    def broken(evidence):
        raise RuntimeError("injected engine fault")

    run = started_bills(pdf_store, local_model, bf.mini_pages(1, 2, 3))
    monkeypatch.setattr(bill_tables, "read", broken)
    run.answer([1, 2, 3], flat=True)
    run.extract()
    segment_check(run, 3)
    for (_, _, record), k in zip(run.bills(), (1, 2, 3)):
        expect_read(record, k)
        noted(record, extraction.BILL_FAILED_NOTE)
        noted(record, BILL_SPLIT_NOTE)
    failures = [entry for entry in caplog.records if "bill table read" in entry.getMessage()]
    assert len(failures) == 1 and "RuntimeError" in failures[0].getMessage()
    assert not [entry for entry in caplog.records if CITY in entry.getMessage() or "81.42" in entry.getMessage()]
    no_grid_in_questions(run)


def no_grid_in_questions(run):
    """C-no-grid: no request after the classifications carries the reader's printed grid."""
    for schema in ("BillSummary", "BillLines"):
        for request in run.requests(schema):
            assert all("-layout-table-" not in table["table_id"] for table in request.get("reported_tables", []))


V39 = "typed-extraction-v39-receipt-printed-signs"


def test_sc121_3_a_file_recorded_as_one_undecided_bill_before_the_split_becomes_three_and_keeps_its_first_id(pdf_store, local_model, monkeypatch):
    run = started_bills(pdf_store, local_model, bf.mini_pages(1, 2, 3))
    with monkeypatch.context() as patch:  # As v39 recorded it: one bill, from the whole file.
        patch.setattr(extraction, "EXTRACTION_VERSION", V39)
        patch.setattr(bill_split, "bill_parts", lambda lines: bill_split.BillSplit([(0, len(lines))]))
        run.answer([1])
        run.extract()
    [(_, original, _)] = run.bills()
    assert run.run["prompt_version"] == V39 and run.segments() == []
    assert extraction.EXTRACTION_VERSION != V39
    run.answer([1, 2, 3])
    again = run.extract()
    assert again["prompt_version"] == extraction.EXTRACTION_VERSION
    segment_check(run, 3)
    bills = run.bills()
    assert bills[0][1] == original and len(set(bill_ids(run))) == 3  # Segment 0 keeps the old id; segments 1 and 2 are new.
    for (_, _, record), k in zip(bills, (1, 2, 3)):
        expect_mini(record, k)


def test_sc122_bl_multi_read_again_changes_nothing_and_asks_the_same_questions(pdf_store, local_model):
    run = multi(pdf_store, local_model)
    run.extract()
    first, first_questions = rows_of(run), run.asked()
    engine = json.dumps(dataclasses.asdict(ENGINE(run.evidence).reading), sort_keys=True, default=str)
    assert engine == json.dumps(dataclasses.asdict(ENGINE(run.evidence).reading), sort_keys=True, default=str)  # Engine reads are equal.
    split = [bill_split.bill_parts(run.blank_free()) for _ in range(2)]
    assert split[0] == split[1]
    run.answer([1, 2, 3])
    run.extract(force=True)
    assert rows_of(run) == first and run.asked() == first_questions
    assert_ledger_healthy(run.store)


# === The contract's failure, retry, duplicate-capture, restart and concurrent variants ======================================================

def test_a_failed_run_publishes_nothing_and_extract_again_gives_exactly_the_three_bills(pdf_store, local_model):
    run = multi(pdf_store, local_model, fail_summary_at=1)
    run_id, _ = run.extraction.enqueue(run.doc["id"], run.parse_id, run.config())
    run.extraction.run(run_id, Work.detached())
    assert run.extraction.get(run_id)["status"] == "failed"
    assert run.bills() == [] and run.segments() == []
    run.answer([1, 2, 3])
    run.extract()
    segment_check(run, 3)
    with run.store.connection() as db:
        assert db.execute("SELECT count(*) FROM receipts").fetchone()[0] == 3
    for (_, _, record), k in zip(run.bills(), (1, 2, 3)):
        expect_mini(record, k)
        auto(record)


def test_the_file_dropped_twice_is_one_file_with_the_same_three_bills(pdf_store, local_model):
    inbox, store = pdf_store
    from conftest import inbox_scan
    run = multi(pdf_store, local_model)
    run.extract()
    first = [(segment, bill_id) for segment, bill_id, _ in run.bills()]
    (inbox / "again.pdf").write_bytes(store.blob_path(run.blob()).read_bytes())
    inbox_scan(store)
    names = {item["relative_path"]: item for item in store.documents()["items"]}
    assert set(names) == {"bills.pdf", "again.pdf"} and names["again.pdf"]["current_hash"] == names["bills.pdf"]["current_hash"]
    assert [link["relative_path"] for link in store.linked_documents(names["again.pdf"]["id"])] == ["bills.pdf"]
    with store.connection() as db:
        assert len(db.execute("SELECT DISTINCT blob_hash FROM receipts").fetchall()) == 1
    run.answer([1, 2, 3])
    run.extract()
    assert [(segment, bill_id) for segment, bill_id, _ in run.bills()] == first
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM receipts").fetchone()[0] == 3


def test_a_run_stopped_after_reading_and_before_publishing_is_recovered_and_read_again(pdf_store, local_model, monkeypatch):
    run = multi(pdf_store, local_model)
    run_id, _ = run.extraction.enqueue(run.doc["id"], run.parse_id, run.config())

    def stopped(*args, **kwargs):
        raise KeyboardInterrupt  # The process stops: nothing catches it, so the run stays "running".

    with monkeypatch.context() as patch:
        patch.setattr(ExtractionService, "record", stopped)
        with pytest.raises(KeyboardInterrupt):
            run.extraction.run(run_id, Work.detached())
    assert run.extraction.get(run_id)["status"] == "running" and run.bills() == []
    run.extraction.recover()  # On restart.
    assert run.extraction.get(run_id)["status"] == "interrupted"
    run.answer([1, 2, 3])
    run.extract()
    segment_check(run, 3)
    for (_, _, record), k in zip(run.bills(), (1, 2, 3)):
        expect_mini(record, k)
        noted(record, BILL_SPLIT_NOTE)
        auto(record)


def test_two_extract_requests_in_a_row_are_one_run_and_three_bills(pdf_store, local_model):
    run = multi(pdf_store, local_model)
    first, created_first = run.extraction.enqueue(run.doc["id"], run.parse_id, run.config())
    second, created_second = run.extraction.enqueue(run.doc["id"], run.parse_id, run.config())
    assert (created_first, created_second) == (True, False) and first == second  # The existing queue's dedupe.
    run.extraction.run(first, Work.detached())
    run.run = run.extraction.get(first)
    assert run.run["status"] == "succeeded"
    segment_check(run, 3)
    assert len(run.bills()) == 3
