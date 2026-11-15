"""The charged total and tip of a dining receipt (specs/dining-receipt-indent FR-01 – FR-07 (the link) and FR-09, SC-01 – SC-04, SC-06, SC-19, D19 – D31):
a later, larger total is what was charged, a tip not printed is worked out from the two printed lines, and a suggested-tip table is never the source of
either. Synthetic breakfast receipt (tests/dining_receipt_fixtures.py) and the local model stub only.

One category per dining receipt (FR-10 – FR-12, FR-14 (a, c), FR-27, D18, D20: SC-01 steps 6 – 8, SC-05, SC-07, SC-09 steps 1 – 5, SC-16, SC-18, X-D8,
X-Q1) is checked beside them, and a kind change with its Undo and the item-category backfill on a dining receipt (FR-13, FR-14 (b), D27: SC-08, SC-17).
Test functions of later slices are added to this file by those slices."""

from decimal import Decimal
import hashlib
import json
import sqlite3
from typing import get_origin

import pytest

from dining_receipt_fixtures import b8_stub, b11_stub, breakfast_stub, find, grocery_re_read_stub, image_id, insert_old_receipts, proposed
from home_manager.app.manager import Manager
from home_manager.core.categories import LEGACY_CATEGORIES
from home_manager.core.money import amount_text
from home_manager.documents import dining_total
from home_manager.documents.extraction import looks_like_several
from home_manager.documents.receipt_schema import TextLine
from home_manager.finance.family_routing import apply_delivery, record_payload
from home_manager.finance.item_categories import ItemCategorizer
from home_manager.finance.ledger import CATEGORY_REFUSED, normalize_name
from home_manager.finance.reconcile import Reconciler
from home_manager.library.scanner import ScanLimits
from home_manager.library.storage import Store
from test_dining_baseline_capture import start_reasoning
from test_migrations import MIGRATIONS
from test_receipt_kinds import app_session, check_named, inputs_by_key, trace_of
from test_receipt_side_lines import read

WORKED_OUT = "Tip $8.79 was worked out from Total $61.55 less Bill $52.76, not printed; check it."
TABLE_TOTAL = "The total the reading took from the suggested-tip table was not used."
TABLE_TIP = "The tip the reading took from the suggested-tip table was not used."


def breakfast(tmp_path, local_model, name="B0"):
    """The breakfast receipt read and recorded with stub `name`: (manager, run, requests). The several-receipts question is asked only when the
    lines hold more than one total line with a digit (looks_like_several), so a stub with fewer has no answer for it."""
    texts, indents, replies = breakfast_stub(name)
    if not looks_like_several(lines_of(*texts)):
        replies.pop("ReceiptStarts")
    return read(tmp_path, local_model, texts, indents, replies)


def read_again(manager, local_model, replies):
    """Extract again (force) from the document's one reading with replies, through the app's job path: the new extraction run."""
    [doc] = manager.store.documents()["items"]
    [parse] = manager.receipts.history(doc["id"])
    local_model["requests"].clear()
    local_model["by_schema"] = {name: list(reply) for name, reply in replies.items()}
    run_id = manager.start_extraction(doc["id"], parse["id"], True)["run_id"]
    manager.future.result(timeout=60)
    run = manager.extractions.get(run_id)
    assert run["status"] == "succeeded", run["error"]
    return run


def receipt_of(manager, run):
    """(the receipt's database row as a dict, its record payload)."""
    receipt_id = run["publication"]["id"]
    with manager.store.connection() as db:
        row = dict(db.execute("SELECT * FROM receipts WHERE id=?", (receipt_id,)).fetchone())
    return row, manager.ledger.record("receipt", receipt_id)


def cited(run, field):
    """The line ids the saved reading's header cites for field."""
    return [cite["line_id"] for cite in run["result"]["header"][field]["evidence"]]


def charge(manager, run, amount_minor, text="GACHAS BREAKFAST BAR"):
    """A card charge of the amount on the receipt's date (the ledger fixture K61 / K52): its transaction id."""
    receipt = manager.ledger.record("receipt", run["publication"]["id"])
    account = manager.ledger.create_account("Synth Bank", "credit_card", "USD", last_four="4242")
    source = {"document_id": receipt["document_id"], "blob_hash": receipt["blob_hash"], "source_key": f"import:{amount_minor}", "run_id": f"import:{amount_minor}"}
    with manager.store.connection() as db:
        [transaction_id], _ = manager.ledger.insert_transactions(
            db, account, [{"posted_date": "2026-11-12", "description": text, "amount_minor": -amount_minor, "currency": "USD", "locator": {"rows": [1]}}],
            "import", source, review_status="proposed")
    return transaction_id


def receipt_split(manager, receipt_id):
    """[(category, amount_minor, has an item)] of the receipt's own split, in row order."""
    with manager.store.connection() as db:
        return [(row[0], row[1], row[2] is not None) for row in db.execute(
            "SELECT category,amount_minor,receipt_item_id FROM category_splits WHERE receipt_id=? AND transaction_id IS NULL ORDER BY id", (receipt_id,))]


def assert_split(manager, receipt_id, total, category="dining"):
    """C-sum and C-cat on the receipt's own split: its rows add up to total and every row has the category. Returns the rows."""
    rows = receipt_split(manager, receipt_id)
    assert sum(amount for _, amount, _ in rows) == total and {name for name, _, _ in rows} == {category}
    return rows


def issues_of(manager, run):
    return manager.ledger.record("receipt", run["publication"]["id"])["issues"]


# SC-01 ------------------------------------------------------------------------------------------------------------------------------

def test_sc01_breakfast_counts_what_was_charged(tmp_path, local_model):
    manager, run, requests = breakfast(tmp_path, local_model)
    try:
        row, shown = receipt_of(manager, run)
        # 1. P-check: five items adding to the subtotal, tax 391.
        assert (row["subtotal_minor"], row["tax_minor"]) == (4885, 391)
        with manager.store.connection() as db:
            assert [tuple(item) for item in db.execute("SELECT line_total_minor FROM receipt_items WHERE receipt_id=? ORDER BY position", (row["id"],))] == [
                (395,), (395,), (1495,), (1870,), (730,)]
        # 2. The charged total, from the later, larger Total line.
        assert row["total_minor"] == 6155 and cited(run, "total") == ["line-23"]
        # 3. The tip worked out from the bill (line 22, the nearest pre-tip amount) and the total (line 23), marked as worked out.
        assert row["tip_minor"] == 879 and cited(run, "tip") == ["line-22", "line-23"]
        assert shown["tip_worked_out"] is True and json.loads(row["tip_worked_out_json"]) == {
            "total": {"label": "Total", "line_id": "line-23", "text": "Total: $61.55"},
            "bill": {"label": "Bill", "line_id": "line-22", "text": "Bill: $52.76"}, "total_minor": 6155, "bill_minor": 5276}
        # 4. The dining check passes and counts as a cross-check; its trace names both lines and says the tip was worked out.
        dining = check_named(shown, "dining")
        trace = trace_of(manager, dining["figure"]["trace"])
        assert (trace["result"]["decimal"], trace["compared_with"]["decimal"], trace["reconciles"]) == ("61.55", "61.55", True)
        tip = inputs_by_key(trace)["tip"]
        assert tip["label"] == "Tip (worked out)" and tip["provenance"]["kind"] == "extracted" and tip["provenance"]["line_ids"] == ["line-22", "line-23"]
        assert run["result"]["normalized"]["cross_checks"] >= 1 and not [issue for issue in shown["issues"] if "do not equal" in issue]
        # 5. Review: the worked-out tip alone, which starts with "Tip" so correcting the tip clears it (D4, D26).
        assert (row["review_status"], shown["issues"]) == ("needs_review", [WORKED_OUT])
        # 7. The page's Tip note.
        assert shown["tip_note"] == "Worked out: Total $61.55 − Bill $52.76"
        # The saved reading holds the decided values, the decision and the basis (P4).
        assert run["result"]["dining"]["tip_basis"]["bill"]["line_id"] == "line-22" and run["result"]["dining"]["issues"] == []
    finally:
        manager.close()


def test_sc01_step8_a_charge_of_the_total_links_exactly(tmp_path, local_model):
    manager, run, _ = breakfast(tmp_path, local_model)
    try:
        transaction_id = charge(manager, run, 6155)
        Reconciler(manager.store).run("extraction")
        with manager.store.connection() as db:
            links = [tuple(link) for link in db.execute("SELECT transaction_id,review_status,match_method FROM transaction_receipt_links WHERE receipt_id=?",
                                                          (run["publication"]["id"],))]
            questions = db.execute("SELECT count(*) FROM reconciliation_issues WHERE status='open' AND issue_type='ambiguous_receipt_match'").fetchone()[0]
            charge_rows = db.execute("SELECT amount_minor,category FROM category_splits WHERE transaction_id=?", (transaction_id,)).fetchall()
        charge_split, charge_categories = [row[0] for row in charge_rows], {row[1] for row in charge_rows}
        assert [(link[0], link[1]) for link in links] == [(transaction_id, "proposed")] and "amount" in links[0][2] and "near" not in links[0][2]
        assert questions == 0 and sum(charge_split) == 6155 and charge_categories == {"dining"}  # C-sum, C-cat
        assert_split(manager, run["publication"]["id"], 6155)
    finally:
        manager.close()


def test_sc01a_the_model_already_answering_the_charged_total_ends_the_same(tmp_path, local_model):
    manager, run, _ = breakfast(tmp_path, local_model, "B1")
    try:
        row, shown = receipt_of(manager, run)
        assert (row["total_minor"], row["tip_minor"], shown["tip_worked_out"]) == (6155, 879, True)
        assert cited(run, "total") == ["line-23"] and cited(run, "tip") == ["line-22", "line-23"] and shown["issues"] == [WORKED_OUT]
    finally:
        manager.close()


def test_sc01b_the_same_document_recorded_again_leaves_one_receipt(tmp_path, local_model):
    texts, indents, replies = breakfast_stub("B0")
    manager, run, _ = read(tmp_path, local_model, texts, indents, replies)
    try:
        again = read_again(manager, local_model, breakfast_stub("B0")[2])
        assert again["publication"]["id"] == run["publication"]["id"]
        with manager.store.connection() as db:
            assert db.execute("SELECT count(*) FROM receipts").fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM receipt_items").fetchone()[0] == 5
        row, shown = receipt_of(manager, again)
        assert (row["total_minor"], row["tip_minor"], shown["issues"]) == (6155, 879, [WORKED_OUT])
    finally:
        manager.close()


def test_sc01d_a_failed_reading_leaves_the_total_the_tip_and_the_marker(tmp_path, local_model):
    texts, indents, replies = breakfast_stub("B0")
    manager, run, _ = read(tmp_path, local_model, texts, indents, replies)
    try:
        before = receipt_of(manager, run)
        [doc] = manager.store.documents()["items"]
        [parse] = manager.receipts.history(doc["id"])
        local_model["requests"].clear()
        local_model["by_schema"] = {"Classification": breakfast_stub("B0")[2]["Classification"], "ReceiptDiningSummary": [{"bad": "shape"}, {"bad": "shape"}]}
        failed = manager.start_extraction(doc["id"], parse["id"], True)["run_id"]
        manager.future.result(timeout=60)
        assert manager.extractions.get(failed)["status"] == "failed"
        assert receipt_of(manager, run) == before
    finally:
        manager.close()


# SC-02 ------------------------------------------------------------------------------------------------------------------------------

def test_sc02_a_printed_tip_is_kept(tmp_path, local_model):
    manager, run, _ = breakfast(tmp_path, local_model, "B2")
    try:
        row, shown = receipt_of(manager, run)
        assert (row["tip_minor"], row["total_minor"]) == (879, 6155) and cited(run, "tip") == ["line-24"] and cited(run, "total") == ["line-23"]
        assert row["tip_worked_out_json"] is None and shown["tip_worked_out"] is False and shown["tip_note"] is None
        assert (row["review_status"], row["review_source"], shown["issues"]) == ("verified", "automatic", [])
        assert_split(manager, run["publication"]["id"], 6155)
    finally:
        manager.close()


def test_sc02a_a_printed_tip_that_does_not_make_the_total_is_an_issue(tmp_path, local_model):
    manager, run, _ = breakfast(tmp_path, local_model, "B3")
    try:
        row, shown = receipt_of(manager, run)
        assert (row["tip_minor"], row["total_minor"]) == (500, 6155) and row["tip_worked_out_json"] is None
        assert "Tip ($5.00) and the bill ($52.76) don't make the total ($61.55)." in shown["issues"]
        assert row["review_status"] == "needs_review" and not any(issue.startswith("Tip $") for issue in shown["issues"])
        assert_split(manager, run["publication"]["id"], 6155)
    finally:
        manager.close()


# SC-03 ------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name,total,line", [("B4", 5276, "line-20"), ("B4e", 5276, "line-20")])
def test_sc03_no_tip_is_invented(tmp_path, local_model, name, total, line):
    """B4: the customer copy (Tip and Total blank); B4e (a): the later Total equals the Bill."""
    manager, run, _ = breakfast(tmp_path, local_model, name)
    try:
        row, shown = receipt_of(manager, run)
        assert (row["total_minor"], row["tip_minor"]) == (total, None) and cited(run, "total") == [line]
        assert row["tip_worked_out_json"] is None and shown["tip_note"] is None and not any(issue.startswith("Tip") for issue in shown["issues"])
        assert_split(manager, run["publication"]["id"], 5276)
    finally:
        manager.close()


def test_sc03b_one_printed_total_is_read_as_today(tmp_path, local_model):
    texts, indents, replies = breakfast_stub("B0")
    keep = 20  # Lines 1 – 20 only: the model's answer cites line 20 and nothing after it is printed.
    replies.pop("ReceiptStarts")  # One total line: nothing asks where a receipt starts.
    manager, run, _ = read(tmp_path, local_model, texts[:keep], indents[:keep], replies)
    try:
        row, _ = receipt_of(manager, run)
        assert (row["total_minor"], row["tip_minor"], row["tip_worked_out_json"]) == (5276, None, None) and cited(run, "total") == ["line-20"]
    finally:
        manager.close()


def test_sc03c_no_tip_line_still_gives_the_charged_total(tmp_path, local_model):
    manager, run, _ = breakfast(tmp_path, local_model, "B10")
    try:
        row, shown = receipt_of(manager, run)
        assert (row["total_minor"], row["tip_minor"], row["tip_worked_out_json"]) == (6155, None, None) and cited(run, "total") == ["line-23"]
        assert shown["tip_note"] is None and not any(issue.startswith("Tip") for issue in shown["issues"])
        # The dining check fails as today (4885 + 391 = 5276 is not 6155), so the receipt waits in Review.
        assert any("do not equal the total" in issue for issue in shown["issues"]) and row["review_status"] == "needs_review"
        # The receipt's split by rule 5 on a dining receipt: the items and tax, and the 879 difference as one row no item carries (FR-27: no tip row to leave out).
        rows = assert_split(manager, run["publication"]["id"], 6155)
        assert sorted(amount for _, amount, item in rows if not item) == [879] and sum(amount for _, amount, item in rows if item) == 5276
        assert shown["unmatched_minor"] == 879
    finally:
        manager.close()


def test_sc03d_pre_tip_amounts_that_disagree_work_out_no_tip(tmp_path, local_model):
    manager, run, _ = breakfast(tmp_path, local_model, "B9")
    try:
        row, shown = receipt_of(manager, run)
        assert (row["total_minor"], row["tip_minor"], row["tip_worked_out_json"]) == (6155, None, None) and cited(run, "total") == ["line-23"]
        # Earlier amount first (line 20 before line 22); the card terminal's "Amount: $52.76" (line 6) takes no part (D29, D30).
        assert "The receipt prints different amounts before the tip ($52.76 and $50.00), so the tip wasn't worked out." in shown["issues"]
        assert not any(issue.startswith("Tip $") for issue in shown["issues"]) and any("do not equal the total" in issue for issue in shown["issues"])
        rows = assert_split(manager, run["publication"]["id"], 6155)
        assert sorted(amount for _, amount, item in rows if not item) == [879] and shown["unmatched_minor"] == 879
    finally:
        manager.close()


# SC-04 ------------------------------------------------------------------------------------------------------------------------------

def summary_requests(requests):
    return [request for request in requests if request["response_format"]["json_schema"]["name"] == "ReceiptDiningSummary"]


def table_lines(run):
    """The ids of the lines of B0's suggested-tip table (its heading and three offers), as the stored reading numbers them."""
    return {cite["line_id"] for field in ("total", "tip") for cite in run["result"]["header"][field]["evidence"]}


def test_sc04_step1_the_table_is_not_the_source_of_the_total(tmp_path, local_model):
    texts, indents, replies = breakfast_stub("B0")
    replies["ReceiptDiningSummary"][0]["total"] = {"value": "61.55", "status": "proposed", "evidence": [{"line_id": "line-26", "quote": texts[25]}]}
    manager, run, _ = read(tmp_path, local_model, texts, indents, replies)
    try:
        row, shown = receipt_of(manager, run)
        assert (row["total_minor"], row["tip_minor"]) == (6155, 879) and cited(run, "total") == ["line-23"] and cited(run, "tip") == ["line-22", "line-23"]
        assert TABLE_TOTAL in shown["issues"]
        assert not table_lines(run) & {"line-25", "line-26", "line-27", "line-28"}
    finally:
        manager.close()


def test_sc04_step2_without_a_post_tip_total_the_bill_before_the_table_is_the_total(tmp_path, local_model):
    manager, run, requests = breakfast(tmp_path, local_model, "B5")
    try:
        row, shown = receipt_of(manager, run)
        assert (row["total_minor"], row["tip_minor"], row["tip_worked_out_json"]) == (5276, None, None) and cited(run, "total") == ["line-22"]
        assert len(summary_requests(requests)) == 1 and TABLE_TOTAL in shown["issues"]  # The model is not asked again (D22).
        assert not table_lines(run) & {"line-24", "line-25", "line-26", "line-27"}
        assert row["review_status"] == "needs_review"
    finally:
        manager.close()


def test_sc04a_a_tip_from_the_table_is_dropped_and_worked_out(tmp_path, local_model):
    texts, indents, replies = breakfast_stub("B0")
    replies["ReceiptDiningSummary"][0]["tip"] = {"value": "8.79", "status": "proposed", "evidence": [{"line_id": "line-26", "quote": texts[25]}]}
    manager, run, _ = read(tmp_path, local_model, texts, indents, replies)
    try:
        row, shown = receipt_of(manager, run)
        assert (row["tip_minor"], row["total_minor"]) == (879, 6155) and cited(run, "tip") == ["line-22", "line-23"]
        assert TABLE_TIP in shown["issues"] and WORKED_OUT in shown["issues"]
    finally:
        manager.close()


def test_sc04b_a_table_without_its_heading_is_the_same(tmp_path, local_model):
    texts, indents, replies = breakfast_stub("B0")
    assert texts.pop(24) == "Suggested Tip" and indents.pop(24) == 0
    summary = replies["ReceiptDiningSummary"][0]
    summary["total"] = {"value": "61.55", "status": "proposed", "evidence": [{"line_id": "line-25", "quote": texts[24]}]}
    manager, run, _ = read(tmp_path, local_model, texts, indents, replies)
    try:
        row, shown = receipt_of(manager, run)
        assert (row["total_minor"], row["tip_minor"]) == (6155, 879) and TABLE_TOTAL in shown["issues"]
        assert cited(run, "total") == ["line-23"] and cited(run, "tip") == ["line-22", "line-23"]
    finally:
        manager.close()


@pytest.mark.parametrize("name", ["B5n", "B5a"])
def test_sc04cd_no_pre_tip_amount_before_the_table_leaves_the_total_missing(tmp_path, local_model, name):
    """B5n: no pre-tip amount before the table; B5a: only the card terminal's "Amount: $52.76" (D30)."""
    manager, run, requests = breakfast(tmp_path, local_model, name)
    try:
        row, shown = receipt_of(manager, run)
        assert (row["total_minor"], row["tip_minor"]) == (None, None) and run["result"]["header"]["total"]["status"] == "missing"
        assert not any(cite == "line-6" for field in ("total", "tip") for cite in cited(run, field))
        assert len(summary_requests(requests)) == 1 and TABLE_TOTAL in shown["issues"]
    finally:
        manager.close()


# SC-06 ------------------------------------------------------------------------------------------------------------------------------

def test_sc06_your_tip_correction_wins(tmp_path, local_model):
    manager, run, _ = breakfast(tmp_path, local_model)
    try:
        receipt_id = run["publication"]["id"]
        shown = manager.ledger.correct("receipt", receipt_id, {"tip": "9.00"})
        row, shown = receipt_of(manager, run)
        # 1 – 4. The tip is yours and no longer worked out; the Tip reason is resolved, no check is re-run, and the footer warns as today.
        assert row["tip_minor"] == 900 and shown["tip_worked_out"] is False and shown["tip_note"] is None
        assert shown["issues"] == [] and shown["totals_mismatch"] is True
        assert (row["review_status"], row["review_source"]) == ("verified", "automatic")
        assert_split(manager, receipt_id, 6155)
        # 6. Reading again keeps the correction.
        again = read_again(manager, local_model, breakfast_stub("B0")[2])
        row, shown = receipt_of(manager, again)
        assert (row["tip_minor"], row["total_minor"], shown["tip_worked_out"]) == (900, 6155, False)
    finally:
        manager.close()


def test_sc06a_undoing_the_tip_correction_brings_the_marker_back(tmp_path, local_model):
    manager, run, _ = breakfast(tmp_path, local_model)
    try:
        receipt_id = run["publication"]["id"]
        ids = manager.ledger.correct("receipt", receipt_id, {"tip": "9.00"})["correction_ids"]
        manager.ledger.undo_corrections("receipt", receipt_id, ids)
        row, shown = receipt_of(manager, run)
        assert row["tip_minor"] == 879 and shown["tip_worked_out"] is True and shown["tip_note"] == "Worked out: Total $61.55 − Bill $52.76"
    finally:
        manager.close()


def test_sc06b_a_printed_tip_corrected_the_same_way(tmp_path, local_model):
    manager, run, _ = breakfast(tmp_path, local_model, "B2")
    try:
        receipt_id = run["publication"]["id"]
        manager.ledger.correct("receipt", receipt_id, {"tip": "9.00"})
        row, shown = receipt_of(manager, run)
        assert row["tip_minor"] == 900 and shown["tip_worked_out"] is False and row["tip_worked_out_json"] is None and shown["totals_mismatch"] is True
    finally:
        manager.close()


# SC-19 ------------------------------------------------------------------------------------------------------------------------------

def test_sc19_several_total_lines_are_one_receipt(tmp_path, local_model):
    """Characterization (D14): five total lines make the file look like several receipts, so the starts question is asked once, and its answer
    (one receipt) keeps the breakfast receipt whole."""
    manager, run, requests = breakfast(tmp_path, local_model)
    try:
        assert [request["response_format"]["json_schema"]["name"] for request in requests].count("ReceiptStarts") == 1
        with manager.store.connection() as db:
            assert db.execute("SELECT count(*) FROM receipts").fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM document_segments").fetchone()[0] == 0
        assert receipt_of(manager, run)[0]["total_minor"] == 6155
    finally:
        manager.close()


# dining_total.decide ----------------------------------------------------------------------------------------------------------------

def lines_of(*texts):
    return [TextLine(id=f"line-{number}", text=text, block_ids=[]) for number, text in enumerate(texts, 1)]


def header_of(total=None, tip=None):
    """A ReceiptDiningSummary header whose total and tip are the model's answers (text, line numbers) or missing."""
    from home_manager.documents.extraction import RECEIPT_FORMS
    missing = {"value": None, "status": "missing", "evidence": []}

    def value(answer):
        if answer is None:
            return missing
        text, numbers, quotes = answer
        return {"value": text, "status": "proposed", "evidence": [{"line_id": f"line-{number}", "quote": quote} for number, quote in zip(numbers, quotes)]}
    form = RECEIPT_FORMS["dining"]
    fields = {name: [] if get_origin(info.annotation) is list else missing for name, info in form.model_fields.items()}
    return form.model_validate({**fields, "total": value(total), "tip": value(tip)})


def decided(texts, total=None, tip=None):
    lines = lines_of(*texts)
    return dining_total.decide(header_of(total, tip), lines)


def amount_of(value):
    return value.value if value.status == "proposed" else None


def test_decide_a_larger_total_after_the_bill_is_the_charged_total_and_the_tip_is_the_difference():
    texts = ["Subtotal: $48.85", "Total Tax: $3.91", "Bill: $52.76", "Total: $61.55", "Tip: $"]
    decision = decided(texts, total=("52.76", [3], ["$52.76"]))
    assert amount_of(decision.header.total) == "61.55" and [cite.line_id for cite in decision.header.total.evidence] == ["line-4"]
    assert amount_of(decision.header.tip) == "8.79" and [cite.line_id for cite in decision.header.tip.evidence] == ["line-3", "line-4"]
    assert decision.tip_basis == {"total": {"label": "Total", "line_id": "line-4", "text": "Total: $61.55"},
                                  "bill": {"label": "Bill", "line_id": "line-3", "text": "Bill: $52.76"}}
    assert decision.issues == [] and decision.total_changed and decision.tip_changed


@pytest.mark.parametrize("label,printed", [("Total", "Total: $20.00"), ("Grand Total", "Grand Total $20.00"), ("Bill", "Bill $20.00"),
                                           ("Amount due", "Amount due: $20.00"), ("Balance due", "Balance Due 20.00")])
def test_decide_every_pre_tip_label_the_spec_names_makes_a_pre_tip_amount(label, printed):
    decision = decided([printed, "Tip: $", "Grand Total: $24.00"], total=("20.00", [1], [printed]))
    assert amount_of(decision.header.total) == "24.00" and amount_of(decision.header.tip) == "4.00"
    assert decision.tip_basis["bill"]["label"] == label and decision.tip_basis["total"]["label"] == "Grand Total"


@pytest.mark.parametrize("text", ["Subtotal: $20.00", "Sub Total $20.00", "Total Tax: $20.00", "Total Item Count: 20", "Total Savings $20.00",
                                  "Total Discounts: $20.00", "Amount: $20.00", "Paid With: VISA 20.00", "Items total $20.00"])
def test_decide_other_labels_are_never_a_pre_tip_amount(text):
    decision = decided([text, "Tip: $", "Total: $24.00"])
    assert decision.tip_basis is None and amount_of(decision.header.tip) is None
    assert decision.header.total.status == "missing"  # No pre-tip amount to be larger than: not a post-tip total either.


def test_decide_a_total_line_with_no_amount_is_not_a_candidate():
    decision = decided(["Bill: $20.00", "Tip: $", "Total: $"])
    assert decision.tip_basis is None and decision.header.total.status == "missing"


def test_decide_a_later_equal_total_changes_nothing():
    header = header_of(total=("52.76", [1], ["Total: $52.76"]))
    decision = dining_total.decide(header, lines_of("Total: $52.76", "Tip: $", "Total: $52.76"))
    assert decision.header is header and decision.tip_basis is None and not (decision.total_changed or decision.tip_changed)


def test_decide_no_tip_line_gives_the_total_and_no_tip():
    decision = decided(["Bill: $52.76", "Total: $61.55"], total=("52.76", [1], ["Bill: $52.76"]))
    assert amount_of(decision.header.total) == "61.55" and decision.header.tip.status == "missing" and decision.tip_basis is None


def test_decide_the_latest_post_tip_total_counts_and_the_total_line_before_it_is_its_pre_tip_amount():
    """Total $55.00 is larger than the Bill before it, and Total $56.00 larger than that one: the latest counts (D23), its nearest pre-tip amount is
    the $55.00 line, so the Bill differs from it and no tip is worked out; a printed tip of $5.00 is checked against the nearest one."""
    decision = decided(["Bill: $50.00", "Total: $55.00", "Tip: $5.00", "Total: $56.00"], tip=("5.00", [3], ["Tip: $5.00"]))
    assert amount_of(decision.header.total) == "56.00" and [cite.line_id for cite in decision.header.total.evidence] == ["line-4"]
    assert [(issue.template, issue.amounts) for issue in decision.issues] == [
        (dining_total.DIFFERENT, (Decimal("50.00"), Decimal("55.00"))), (dining_total.TIP_AND_BILL, (Decimal("5.00"), Decimal("55.00"), Decimal("56.00")))]


def test_decide_a_printed_tip_is_kept_when_it_makes_the_total():
    header = header_of(tip=("8.79", [4], ["Tip: $8.79"]))
    decision = dining_total.decide(header, lines_of("Bill: $52.76", "Total: $61.55", "x", "Tip: $8.79"))
    assert decision.header.tip == header.tip and decision.issues == [] and decision.tip_basis is None and amount_of(decision.header.total) == "61.55"


def test_decide_a_printed_tip_that_does_not_make_the_total_adds_the_issue_with_its_amounts():
    decision = decided(["Bill: $52.76", "Tip: $5.00", "Total: $61.55"], tip=("5.00", [2], ["Tip: $5.00"]))
    [issue] = decision.issues
    assert issue.template == dining_total.TIP_AND_BILL and issue.amounts == (Decimal("5.00"), Decimal("52.76"), Decimal("61.55"))
    assert amount_text(500, "USD") == "$5.00" and decision.tip_basis is None


def test_decide_pre_tip_amounts_that_disagree_name_the_earliest_differing_and_the_nearest():
    decision = decided(["Total: $52.76", "Total: $51.00", "Bill: $50.00", "Tip: $", "Total: $61.55"])
    [issue] = decision.issues
    assert issue.template == dining_total.DIFFERENT and issue.amounts == (Decimal("52.76"), Decimal("50.00"))
    assert amount_of(decision.header.total) == "61.55" and amount_of(decision.header.tip) is None and decision.tip_basis is None


def test_decide_a_table_without_a_heading_is_still_a_table():
    texts = ["Bill: $52.76", "Tip: $", "18.00% of sale: $8.79 Total $61.55", "20.00% of sale: $9.77 Total $62.53"]
    decision = decided(texts, total=("61.55", [3], [texts[2]]))
    assert amount_of(decision.header.total) == "52.76" and [cite.line_id for cite in decision.header.total.evidence] == ["line-1"]
    assert [issue.template for issue in decision.issues] == [dining_total.TABLE_NOTE.format(what="total")]
    assert decision.tip_basis is None  # No post-tip total outside the table.


def test_decide_a_heading_line_joins_the_table_and_is_not_a_tip_line():
    texts = ["Total: $20.00", "Tip Guide", "15% $3.00 Total $23.00", "18% $3.60 Total $23.60"]
    decision = decided(texts)
    assert decision.tip_basis is None and decision.header.tip.status == "missing"
    assert dining_total.table_ids(lines_of(*texts)) == {"line-2", "line-3", "line-4"}


def test_decide_a_tax_rate_line_is_not_a_table():
    assert dining_total.table_ids(lines_of("Tax 8.25% $3.91", "Total: $52.76")) == set()


def test_decide_a_total_cited_to_part_of_the_table_and_a_real_line_is_kept():
    texts = ["Total: $20.00", "15% $3.00 Total $23.00", "18% $3.60 Total $23.60"]
    header = header_of(total=("20.00", [1, 2], [texts[0], texts[1]]))
    assert dining_total.decide(header, lines_of(*texts)).header is header


def test_decide_the_decision_is_deterministic_and_leaves_its_input_alone():
    header = header_of(total=("52.76", [3], ["Bill: $52.76"]))
    snapshot = header.model_dump()
    lines = lines_of("Subtotal: $48.85", "Total Tax: $3.91", "Bill: $52.76", "Total: $61.55", "Tip: $")
    first, second = dining_total.decide(header, lines), dining_total.decide(header, lines)
    assert first.header == second.header and first.dump() == second.dump() and header.model_dump() == snapshot


def test_amount_text_writes_the_magnitude_with_the_currencys_symbol():
    assert [amount_text(minor, code) for minor, code in ((6155, "USD"), (-6155, "USD"), (123456, "USD"), (5, "EUR"), (12000, "GBP"), (6155, "CAD"), (500, "JPY"))] == [
        "$61.55", "$61.55", "$1,234.56", "€0.05", "£120.00", "61.55 CAD", "500 JPY"]


# One category (FR-10 – FR-12, FR-14 (a, c), FR-27, D18, D20) ------------------------------------------------------------------------------

REFUSED = "Every item on a dining receipt counts as the receipt's category; change it with Edit details."
COFFEE_MEMORY = [(normalize_name("Gacha's Breakfast Bar"), normalize_name("Coffee"), "groceries")]


def reopen(tmp_path, local_model, manager):
    """A restart: close the manager and open the same library again."""
    manager.close()
    manager = Manager(tmp_path / "control", ScanLimits(stability_seconds=0))
    start_reasoning(manager, local_model)
    return manager


def old_manager(tmp_path, local_model, names, memory=False):
    """A library as the code before this feature left it (contract "Old library"): the old receipts called names, plain SQL on a database at the
    last schema version below migration 081, opened with the changed code. Returns (manager, {name: receipt id}). The dining receipts have a seller."""
    managed = tmp_path / "managed"
    managed.mkdir(parents=True)
    (managed / ".home-manager-store").write_text("home-manager-store-v1\n", encoding="utf-8")
    db = sqlite3.connect(managed / "inventory.sqlite3")
    db.row_factory = sqlite3.Row
    for number, script in MIGRATIONS:
        if number < 81:
            db.executescript(script.read_text())
    ids = insert_old_receipts(db, names, memory=memory)
    db.commit()
    db.close()
    manager = Manager(tmp_path / "control", ScanLimits(stability_seconds=0))
    manager.configure(str(managed))
    start_reasoning(manager, local_model)
    with manager.store.connection() as db:
        merchant = manager.ledger.merchant(db, "Gacha's Breakfast Bar")
        db.execute("UPDATE receipts SET merchant_id=? WHERE receipt_kind='dining' AND id<>?", (merchant, ids["H"] if "H" in ids else 0))
        if "H" in ids:
            db.execute("UPDATE receipts SET merchant_id=? WHERE id=?", (manager.ledger.merchant(db, "Synth Diner"), ids["H"]))
    return manager, ids


def read_again_of(manager, local_model, receipt_id, replies):
    """Extract again (force) from the receipt's document's one reading with replies, through the app's job path: the new extraction run."""
    with manager.store.connection() as db:
        document = db.execute("SELECT document_id FROM receipts WHERE id=?", (receipt_id,)).fetchone()[0]
    [parse] = manager.receipts.history(document)
    local_model["requests"].clear()
    local_model["by_schema"] = {name: list(reply) for name, reply in replies.items()}
    run_id = manager.start_extraction(document, parse["id"], True)["run_id"]
    manager.future.result(timeout=60)
    run = manager.extractions.get(run_id)
    assert run["status"] == "succeeded", run["error"]
    return run


def splits_of(manager):
    """Every category_splits row but its id, sorted: a rebuild keeps the rows and hands out new ids."""
    with manager.store.connection() as db:
        return sorted(tuple(row) for row in db.execute(
            "SELECT receipt_id,coalesce(transaction_id,0),coalesce(receipt_item_id,0),category,amount_minor FROM category_splits"))


def charge_split(manager, transaction_id):
    """[(category, amount_minor)] of a charge's split, item rows first as stored."""
    with manager.store.connection() as db:
        return [(row[0], row[1]) for row in db.execute("SELECT category,amount_minor FROM category_splits WHERE transaction_id=? ORDER BY id", (transaction_id,))]


def stored_categories(manager, receipt_id):
    """[(category, category_source)] of the receipt's items in order."""
    with manager.store.connection() as db:
        return [tuple(row) for row in db.execute("SELECT category,category_source FROM receipt_items WHERE receipt_id=? ORDER BY position", (receipt_id,))]


def memory_rows(manager):
    with manager.store.connection() as db:
        return [tuple(row) for row in db.execute("SELECT merchant_key,item_key,category FROM item_category_memory ORDER BY rowid")]


def table_rows(manager, receipt_id):
    """The receipt's, its items' and its own split's rows, as a test compares them before and after (a rebuild only renumbers split rows)."""
    with manager.store.connection() as db:
        return ([dict(row) for row in db.execute("SELECT * FROM receipts WHERE id=?", (receipt_id,))],
                [dict(row) for row in db.execute("SELECT * FROM receipt_items WHERE receipt_id=? ORDER BY position", (receipt_id,))],
                sorted(tuple(row) for row in db.execute("SELECT coalesce(receipt_item_id,0),category,amount_minor FROM category_splits "
                                                        "WHERE receipt_id=? AND transaction_id IS NULL", (receipt_id,))))


def reconcile(manager):
    return manager.reconciler.run("extraction")


def link_of(manager, receipt_id):
    """(link id, transaction id, review_status) of the receipt's one live link, or None."""
    with manager.store.connection() as db:
        rows = db.execute("SELECT id,transaction_id,review_status FROM transaction_receipt_links WHERE receipt_id=? AND review_status<>'rejected'", (receipt_id,)).fetchall()
    assert len(rows) <= 1
    return tuple(rows[0]) if rows else None


def by_category(shown):
    """The page's "By category" lines: [(category, amount_minor)]."""
    return [(line["category"], line["amount_minor"]) for line in shown["splits"]]


def item_rows(rows):
    return [(category, amount) for category, amount, has_item in rows if has_item]


def no_item_rows(rows):
    return [(category, amount) for category, amount, has_item in rows if not has_item]


def test_sc01_step6_and_7_every_item_the_tip_and_the_by_category_line_are_dining(tmp_path, local_model):
    manager, run, _ = breakfast(tmp_path, local_model)
    try:
        receipt_id = run["publication"]["id"]
        row, shown = receipt_of(manager, run)
        # 6. Receipt split C-sum(6155), C-cat(dining): five item rows (5276) and the tip row (879), although the stub said groceries for items 1 and 2.
        rows = assert_split(manager, receipt_id, 6155)
        assert sum(amount for _, amount in item_rows(rows)) == 5276 and len(item_rows(rows)) == 5 and no_item_rows(rows) == [("dining", 879)]
        assert by_category(shown) == [("dining", 6155)] and row["category"] == "dining"
        # D20: all five items model-categorised, so all store dining with source receipt. C-mem(0).
        assert stored_categories(manager, receipt_id) == [("dining", "receipt")] * 5 and memory_rows(manager) == []
        # 7. C-col(hidden), and nothing is left over to show as "Not matched to an item" once the tip's own row is left out (FR-27: 879 − 879).
        assert shown["category_column"] is False and shown["unmatched_minor"] == 0 and row["one_category"] == 1
    finally:
        manager.close()


def test_sc01_step8_the_charge_split_and_the_receipt_split_follow_the_one_category(tmp_path, local_model):
    manager, run, _ = breakfast(tmp_path, local_model)
    try:
        receipt_id = run["publication"]["id"]
        transaction_id = charge(manager, run, 6155)
        before = receipt_split(manager, receipt_id)
        reconcile(manager)
        assert link_of(manager, receipt_id)[1:] == (transaction_id, "proposed")
        assert {category for category, _ in charge_split(manager, transaction_id)} == {"dining"} and sum(amount for _, amount in charge_split(manager, transaction_id)) == 6155
        assert receipt_split(manager, receipt_id) == before and sum(amount for _, amount, _ in before) == 6155
    finally:
        manager.close()


def test_sc01c_a_restart_and_a_reconciliation_keep_the_applied_state(tmp_path, local_model):
    manager, run, _ = breakfast(tmp_path, local_model)
    try:
        charge(manager, run, 6155)
        reconcile(manager)
        after_step8 = splits_of(manager)
        manager = reopen(tmp_path, local_model, manager)
        reconcile(manager)
        assert splits_of(manager) == after_step8  # C-snap (D8: the applied state survives).
    finally:
        manager.close()


def test_sc01b_the_same_document_recorded_again_leaves_one_split(tmp_path, local_model):
    manager, run, _ = breakfast(tmp_path, local_model)
    try:
        before = splits_of(manager)
        again = read_again(manager, local_model, breakfast_stub("B0")[2])
        assert splits_of(manager) == before and len(receipt_split(manager, again["publication"]["id"])) == 6
    finally:
        manager.close()


def test_sc05_old_receipts_stay_until_read_again(tmp_path, local_model):
    manager, ids = old_manager(tmp_path, local_model, ["A", "B", "G"])
    try:
        run = {"publication": {"id": ids["A"]}}
        k52 = charge(manager, run, 5276)
        # 1 – 2. The upgrade: the library opened with the changed code, then once more. Nothing is rewritten, no job is queued, no model is asked.
        before = {name: table_rows(manager, receipt_id) for name, receipt_id in ids.items()}
        all_before = splits_of(manager)
        manager = reopen(tmp_path, local_model, manager)
        assert {name: table_rows(manager, receipt_id) for name, receipt_id in ids.items()} == before and splits_of(manager) == all_before
        assert local_model["requests"] == []
        # 3. One of A and B links to K52 (exact, proposed); no receipt split changes, and the charge split has the item rows' categories.
        reconcile(manager)
        holder = "A" if link_of(manager, ids["A"]) else "B"
        assert link_of(manager, ids[holder])[1:] == (k52, "proposed") and link_of(manager, ids["B" if holder == "A" else "A"]) is None
        assert {name: table_rows(manager, receipt_id)[2] for name, receipt_id in ids.items()} == {name: before[name][2] for name in ids}
        assert charge_split(manager, k52)[:2] == [("groceries", 395), ("groceries", 395)] and sum(amount for _, amount in charge_split(manager, k52)) == 5276
        # 4. Extract again on B, which you approved: a new v57 run, and nothing of B changes.
        with manager.store.connection() as db:
            parse_before = [tuple(row) for row in db.execute("SELECT id,parser_version,result_json FROM parse_runs ORDER BY id")]
        read_again_of(manager, local_model, ids["B"], breakfast_stub("B0")[2])
        assert table_rows(manager, ids["B"]) == before["B"]
        # 5. Extract again on A: the current version, the charged total and the worked-out tip, one category.
        run_a = read_again_of(manager, local_model, ids["A"], breakfast_stub("B0")[2])
        with manager.store.connection() as db:
            versions = [row[0] for row in db.execute("SELECT prompt_version FROM extraction_runs WHERE prompt_version LIKE 'typed-extraction-v57%'")]
            assert len(versions) == 2 and db.execute("SELECT count(*) FROM extraction_runs WHERE prompt_version='typed-extraction-v56-money-sign-rule'").fetchone()[0] == 3
        row, shown = receipt_of(manager, run_a)
        assert (row["total_minor"], row["tip_minor"], shown["tip_worked_out"]) == (6155, 879, True) and cited(run_a, "tip") == ["line-22", "line-23"]
        assert_split(manager, ids["A"], 6155)
        assert stored_categories(manager, ids["A"]) == [("dining", "receipt")] * 5 and WORKED_OUT in shown["issues"] and row["review_status"] == "needs_review"
        if holder == "B":  # A held no link: its reasons are the FR-06 reason alone; B's link is unchanged (a reading never rewrites what you approved, D39).
            assert link_of(manager, ids["A"]) is None and shown["issues"] == [WORKED_OUT] and link_of(manager, ids["B"])[1:] == (k52, "proposed")
        else:  # A held the link (proposed; 6155 is not 5276, FR-28): removed with the note, and the reconciliation after the reading links K52 to B (FR-29).
            assert links_of(manager, ids["A"]) == [] and shown["issues"] == [WORKED_OUT, REMOVED_52] and row["review_status"] == "needs_review"
            assert charge_rows_of(manager, k52, ids["A"]) == 0 and link_of(manager, ids["B"])[1:] == (k52, "proposed")
            assert charge_split(manager, k52)[:2] == [("groceries", 395), ("groceries", 395)] and sum(amount for _, amount in charge_split(manager, k52)) == 5276
        # (a) A second Extract again on A with the same stub: the same state, nothing doubled.
        after = table_rows(manager, ids["A"])[2]
        read_again_of(manager, local_model, ids["A"], breakfast_stub("B0")[2])
        assert table_rows(manager, ids["A"])[2] == after and len(stored_categories(manager, ids["A"])) == 5
        # 6. A reconciliation run: A stays all dining (FR-14: once applied, kept); B and G are as they were, and nothing is rejected.
        reconcile(manager)
        assert_split(manager, ids["A"], 6155)
        assert table_rows(manager, ids["B"])[2] == before["B"][2] and table_rows(manager, ids["G"]) == before["G"]
        with manager.store.connection() as db:
            assert db.execute("SELECT count(*) FROM transaction_receipt_links WHERE review_status='rejected'").fetchone()[0] == 0
            assert [tuple(row) for row in db.execute("SELECT id,parser_version,result_json FROM parse_runs ORDER BY id")] == parse_before
        assert memory_rows(manager) == []
    finally:
        manager.close()


# SC-07 ------------------------------------------------------------------------------------------------------------------------------

def test_sc07_one_category_on_a_dining_receipt(tmp_path, local_model):
    manager, run, _ = breakfast(tmp_path, local_model)
    try:
        receipt_id = run["publication"]["id"]
        # 1. The payload says the Category column is hidden.
        assert receipt_of(manager, run)[1]["category_column"] is False
        # 2. Changing one item's category is refused, with nothing written.
        stored, split = stored_categories(manager, receipt_id), splits_of(manager)
        with pytest.raises(ValueError) as refused:
            manager.ledger.set_item_category(receipt_id, 1, "groceries")
        assert str(refused.value) == REFUSED == CATEGORY_REFUSED
        assert memory_rows(manager) == [] and stored_categories(manager, receipt_id) == stored and splits_of(manager) == split
        # 3. Edit details → Categories → Travel: the receipt's category, the five items, the tip row (D18), all travel.
        manager.ledger.correct("receipt", receipt_id, {"category": "travel"})
        row, shown = receipt_of(manager, run)
        rows = assert_split(manager, receipt_id, 6155, "travel")
        assert sum(amount for _, amount in item_rows(rows)) == 5276 and no_item_rows(rows) == [("travel", 879)]
        assert by_category(shown) == [("travel", 6155)] and row["category"] == "travel"
        assert stored_categories(manager, receipt_id) == [("travel", "receipt")] * 5 and shown["unmatched_minor"] == 0 and shown["category_column"] is False
        # 4. Still refused.
        with pytest.raises(ValueError, match="Every item on a dining receipt"):
            manager.ledger.set_item_category(receipt_id, 1, "groceries")
        assert memory_rows(manager) == []
        # 5. Reconcile with K61: the charge splits as travel, and a further run keeps both splits all travel.
        transaction_id = charge(manager, run, 6155)
        reconcile(manager)
        assert {category for category, _ in charge_split(manager, transaction_id)} == {"travel"} and sum(amount for _, amount in charge_split(manager, transaction_id)) == 6155
        reconcile(manager)
        assert {category for category, _ in charge_split(manager, transaction_id)} == {"travel"}
        assert_split(manager, receipt_id, 6155, "travel")
        assert memory_rows(manager) == []
        # (c) Q1's counterpart: the same category again changes no split.
        before = splits_of(manager)
        manager.ledger.correct("receipt", receipt_id, {"category": "travel"})
        assert splits_of(manager) == before
    finally:
        manager.close()


def test_sc07_the_item_dropdown_answers_400_through_the_api(tmp_path, local_model):
    manager, run, _ = breakfast(tmp_path, local_model)
    receipt_id = run["publication"]["id"]
    manager.close()
    with app_session(tmp_path, local_model) as (client, restarted, _doc, _parse):
        refused = client.put(f"/api/receipts/{receipt_id}/items/1/category", json={"category": "groceries"})
        assert (refused.status_code, refused.json()["detail"]) == (400, REFUSED)
        assert memory_rows(restarted) == []
        shown = client.get(f"/api/finance/records/receipt/{receipt_id}").json()
        assert shown["category_column"] is False and shown["unmatched_minor"] == 0


def test_sc07a_a_grocery_receipt_keeps_its_column_and_its_dropdown(tmp_path, local_model):
    texts, indents, replies = b11_stub()
    manager, run, _ = read(tmp_path, local_model, texts, indents, replies)
    try:
        receipt_id = run["publication"]["id"]
        assert receipt_of(manager, run)[1]["category_column"] is True
        assert manager.ledger.set_item_category(receipt_id, 1, "dining")["category_source"] == "user"
        assert memory_rows(manager) == [(normalize_name("SYNTH MART"), normalize_name("Milk"), "dining")]
    finally:
        manager.close()


def test_sc07b_a_dining_receipt_with_no_total_still_hides_the_column(tmp_path, local_model):
    manager, run, _ = breakfast(tmp_path, local_model, "B5n")
    try:
        row, shown = receipt_of(manager, run)
        assert row["total_minor"] is None and receipt_split(manager, run["publication"]["id"]) == [] and shown["category_column"] is False
    finally:
        manager.close()


def test_a_dining_receipt_never_reads_the_category_memory(tmp_path, local_model):
    """FR-12 (memory is never read for a dining receipt) and FR-10: a remembered "Coffee" → groceries doesn't change the dining receipt's items."""
    manager, run, _ = breakfast(tmp_path, local_model)
    try:
        receipt_id = run["publication"]["id"]
        with manager.store.connection() as db:
            db.execute("INSERT INTO item_category_memory(merchant_key,item_key,category,updated_at) VALUES(?,?,'groceries','t')", COFFEE_MEMORY[0][:2])
        again = read_again(manager, local_model, breakfast_stub("B0")[2])
        assert stored_categories(manager, receipt_id) == [("dining", "receipt")] * 5 and assert_split(manager, again["publication"]["id"], 6155)
    finally:
        manager.close()


# SC-09 steps 1 – 5 ------------------------------------------------------------------------------------------------------------------

def test_sc09_an_old_dining_receipt_keeps_its_categories_until_it_is_read_again(tmp_path, local_model):
    manager, ids = old_manager(tmp_path, local_model, ["C"])
    receipt_id = ids["C"]
    try:
        k52 = charge(manager, {"publication": {"id": receipt_id}}, 5276)
        # 1. The upgrade changes nothing. 2. The page shows the Category column.
        before = table_rows(manager, receipt_id)
        manager = reopen(tmp_path, local_model, manager)
        assert table_rows(manager, receipt_id) == before
        assert manager.ledger.record("receipt", receipt_id)["category_column"] is True and manager.ledger.record("receipt", receipt_id)["unmatched_minor"] == 391
        # 3. C links to K52 exactly; both splits keep items 1 and 2 under groceries.
        snapshot = charge_state(manager, k52)
        reconcile(manager)
        assert link_of(manager, receipt_id)[1:] == (k52, "proposed")
        expected = [("groceries", 395), ("groceries", 395), ("dining", 1495), ("dining", 1870), ("dining", 730), ("dining", 391)]
        assert [(category, amount) for category, amount, _ in receipt_split(manager, receipt_id)] == expected and charge_split(manager, k52) == expected
        # 4. One item's category: allowed while the column shows, with its memory.
        assert manager.ledger.set_item_category(receipt_id, 3, "groceries")["category_source"] == "user"
        assert memory_rows(manager) == COFFEE_MEMORY
        expected[2] = ("groceries", 1495)
        assert [(category, amount) for category, amount, _ in receipt_split(manager, receipt_id)] == expected and charge_split(manager, k52) == expected
        # 5. Extract again from the v6 reading with B0: the charged total, the worked-out tip, every item counted as dining (your choices stay stored).
        run = read_again_of(manager, local_model, receipt_id, breakfast_stub("B0")[2])
        row, shown = receipt_of(manager, run)
        assert (row["total_minor"], row["tip_minor"], row["review_status"]) == (6155, 879, "needs_review") and WORKED_OUT in shown["issues"]
        assert_split(manager, receipt_id, 6155)
        assert shown["category_column"] is False
        assert stored_categories(manager, receipt_id) == [("groceries", "user"), ("dining", "receipt"), ("groceries", "user"), ("dining", "receipt"), ("dining", "receipt")]
        assert memory_rows(manager) == COFFEE_MEMORY
        # 6. The link to K52 was proposed and 5276 is not the new total: removed, not rejected (FR-28, FR-29, D37), with the note (FR-30). The reconciliation
        #    after the reading links nothing and asks nothing: K52 is smaller than the total.
        assert_unlinked_after_reread(manager, receipt_id, k52, REMOVED_52, snapshot=snapshot)
        # 7. A further reconciliation changes nothing: still dining, still unlinked, the note still there.
        reconcile(manager)
        assert_split(manager, receipt_id, 6155)
        assert_unlinked_after_reread(manager, receipt_id, k52, REMOVED_52, snapshot=snapshot)
        with manager.store.connection() as db:
            assert db.execute("SELECT count(*) FROM transaction_receipt_links").fetchone()[0] == 0
    finally:
        manager.close()


# SC-16, X-Q1 --------------------------------------------------------------------------------------------------------------------------

def test_sc16_an_approved_old_receipt_then_categories(tmp_path, local_model):
    manager, ids = old_manager(tmp_path, local_model, ["D"])
    receipt_id = ids["D"]
    try:
        # 1. Extract again with B0: the approved receipt is not rewritten, and the column shows.
        before = table_rows(manager, receipt_id)
        read_again_of(manager, local_model, receipt_id, breakfast_stub("B0")[2])
        assert table_rows(manager, receipt_id) == before and manager.ledger.record("receipt", receipt_id)["category_column"] is True
        # 2. Edit details → Categories → Travel: item 1 keeps groceries stored; the split counts every item, and the 391 difference, as travel (D18).
        manager.ledger.correct("receipt", receipt_id, {"category": "travel"})
        shown = manager.ledger.record("receipt", receipt_id)
        assert stored_categories(manager, receipt_id) == [("groceries", "user")] + [("travel", "receipt")] * 4
        rows = assert_split(manager, receipt_id, 5276, "travel")
        assert item_rows(rows) == [("travel", 395), ("travel", 395), ("travel", 1495), ("travel", 1870), ("travel", 730)] and no_item_rows(rows) == [("travel", 391)]
        assert shown["unmatched_minor"] == 391 and shown["category_column"] is False
        # 3. The dropdown is refused. 4. A reconciliation run keeps the split.
        with pytest.raises(ValueError, match="Every item on a dining receipt"):
            manager.ledger.set_item_category(receipt_id, 2, "groceries")
        assert memory_rows(manager) == []
        reconcile(manager)
        assert_split(manager, receipt_id, 5276, "travel")
    finally:
        manager.close()


def test_xq1_edit_details_with_the_same_category_does_not_apply_one_category(tmp_path, local_model):
    manager, ids = old_manager(tmp_path, local_model, ["D"])
    receipt_id = ids["D"]
    try:
        before = receipt_split(manager, receipt_id)
        manager.ledger.correct("receipt", receipt_id, {"category": "dining"})
        assert receipt_split(manager, receipt_id) == before and before[0][:2] == ("groceries", 395)
        shown = manager.ledger.record("receipt", receipt_id)
        assert shown["category_column"] is True
        with manager.store.connection() as db:
            assert db.execute("SELECT one_category FROM receipts WHERE id=?", (receipt_id,)).fetchone()[0] == 0
        assert manager.ledger.set_item_category(receipt_id, 1, "dining")["category"] == "dining"  # The dropdown still works (D7).
    finally:
        manager.close()


# SC-18 ------------------------------------------------------------------------------------------------------------------------------

def test_sc18_not_matched_to_an_item_leaves_out_the_tip(tmp_path, local_model):
    manager, run, _ = breakfast(tmp_path, local_model)
    try:
        # 1. The breakfast receipt: nothing is left over, Tip $8.79, "Dining $61.55", item rows 5276 and the tip row 879.
        before = splits_of(manager)
        row, shown = receipt_of(manager, run)
        assert (row["tip_minor"], shown["unmatched_minor"], by_category(shown)) == (879, 0, [("dining", 6155)])
        rows = receipt_split(manager, run["publication"]["id"])
        assert sum(amount for _, amount in item_rows(rows)) == 5276 and no_item_rows(rows) == [("dining", 879)]
        assert splits_of(manager) == before  # 4. Display only.
    finally:
        manager.close()
    # 2. B8: a printed tip of $3.00 and $2.00 left over.
    texts, indents, replies = b8_stub()
    replies.pop("ReceiptStarts")  # One total line: nothing asks where a receipt starts.
    manager, run, _ = read(tmp_path / "b8", local_model, texts, indents, replies)
    try:
        before = splits_of(manager)
        row, shown = receipt_of(manager, run)
        rows = assert_split(manager, run["publication"]["id"], 2600)
        assert item_rows(rows) == [("dining", 2100)] and sorted(no_item_rows(rows)) == [("dining", 200), ("dining", 300)]
        assert (row["tip_minor"], shown["unmatched_minor"]) == (300, 200)
        assert splits_of(manager) == before
    finally:
        manager.close()
    # 3. E: an old dining receipt with its tax missed keeps "Not matched to an item $3.91" as today.
    manager, ids = old_manager(tmp_path / "old", local_model, ["E"])
    try:
        before = splits_of(manager)
        shown = manager.ledger.record("receipt", ids["E"])
        assert shown["unmatched_minor"] == 391 and shown["category_column"] is False and splits_of(manager) == before
    finally:
        manager.close()


def test_sc18a_a_gift_card_resizes_the_tip_row_and_the_footer_follows_it(tmp_path, local_model):
    manager, run, _ = breakfast(tmp_path, local_model)
    try:
        receipt_id = run["publication"]["id"]
        with manager.store.connection() as db:
            details = json.dumps({"dining": {"tenders": [{"tender_type": "gift_card", "minor": 1000, "last_four": None, "locator": {"line_ids": ["line-23"]}}]}})
            db.execute("UPDATE receipts SET details_json=? WHERE id=?", (details, receipt_id))
            manager.ledger.refresh_paid(db, receipt_id)
        row, shown = receipt_of(manager, run)
        assert (row["printed_total_minor"], row["total_minor"]) == (6155, 5155)
        rows = assert_split(manager, receipt_id, 5155)
        [(_, tip_row)] = no_item_rows(rows)
        assert 0 < tip_row < 879 and shown["unmatched_minor"] == 0  # The tip's resized row is left out; nothing else carries no item.
    finally:
        manager.close()


# FR-10: the split rules (unit) ------------------------------------------------------------------------------------------------------

def one_item_split(**kwargs):
    from home_manager.finance import splits
    items = [{"line_total_minor": 2000, "category": "groceries"}, {"line_total_minor": 1000, "category": None}]
    return splits.allocate(items, 3000, 300, 400, 4000, **kwargs)


def test_allocate_without_the_flag_is_todays_rules():
    rows = one_item_split(fallback="dining")
    assert [(index, category) for index, category, _ in rows] == [(0, "groceries"), (1, "dining"), (None, "dining"), (None, "dining")]
    rows = one_item_split(fallback="travel")  # Rule 4: the tip is dining; rule 5: the difference is spread over the items.
    assert [(index, category) for index, category, _ in rows] == [(0, "groceries"), (1, "travel"), (None, "dining")] and sum(amount for *_, amount in rows) == 4000


def test_allocate_with_one_category_puts_everything_under_the_receipts_category():
    rows = one_item_split(fallback="travel", one_category=True)
    assert [(index, category) for index, category, _ in rows] == [(0, "travel"), (1, "travel"), (None, "travel"), (None, "travel")]
    assert sum(amount for *_, amount in rows) == 4000 and rows[2][2] == 400 and rows[3][2] == 300  # The tip, then the 300 difference as its own row.


def test_allocate_with_one_category_and_no_category_counts_the_tip_as_dining():
    rows = one_item_split(fallback=None, one_category=True)
    assert [category for _, category, _ in rows][2] == "dining"


def test_allocate_marks_only_the_tip_row():
    rows = one_item_split(fallback="travel", one_category=True, tip_category="MARK")
    assert [category for _, category, _ in rows] == ["travel", "travel", "MARK", "travel"]
    assert [category for _, category, _ in one_item_split(fallback="dining", tip_category="MARK")][2:] == ["MARK", "dining"]


# X-D8 -------------------------------------------------------------------------------------------------------------------------------

def event(manager, name, receipt_id, transaction_id):
    """Do one rebuild that isn't about categories (contract "X-D8"): the entry point each uses."""
    if name == "upgrade":
        return None
    if name == "reconcile":
        reconcile(manager)
    elif name in ("link_review", "unlink"):
        reconcile(manager)
        manager.reconciler.review_link("receipt", link_of(manager, receipt_id)[0], "verified" if name == "link_review" else "rejected")
    elif name == "delete_item":
        manager.ledger.delete_item(receipt_id, 5)
    elif name == "correct_amount":
        manager.ledger.correct("receipt", receipt_id, {"tax": "3.91"})
    elif name == "correct_item":
        manager.ledger.correct_item_fields(receipt_id, 4, {"quantity": "1"})
    elif name == "other_details":
        manager.ledger.correct("receipt", receipt_id, {"order_number": "179580"})
    elif name == "family_share":
        with manager.store.connection() as db:
            total = db.execute("SELECT total_minor FROM receipts WHERE id=?", (receipt_id,)).fetchone()[0]
            db.execute("INSERT INTO record_shares(record_type,record_id,share_minor,total_minor,people_json,family_record_key,created_at) "
                       "VALUES('receipt',?,?,?,'[]','k','t')", (receipt_id, total // 2, total))
            manager.ledger.refresh_splits(db, receipt_id)
    else:
        raise AssertionError(name)


EVENTS = ["upgrade", "reconcile", "link_review", "unlink", "delete_item", "correct_amount", "correct_item", "other_details", "family_share"]


def split_target(manager, receipt_id):
    """What the receipt's own split must add up to: the total, or this person's part of a shared receipt."""
    with manager.store.connection() as db:
        total = db.execute("SELECT total_minor FROM receipts WHERE id=?", (receipt_id,)).fetchone()[0]
        share = db.execute("SELECT share_minor,total_minor FROM record_shares WHERE record_type='receipt' AND record_id=?", (receipt_id,)).fetchone()
    return share[0] if share else total


@pytest.mark.parametrize("name", EVENTS)
def test_xd8_a_rebuild_that_is_not_about_categories_leaves_an_old_receipts_items_under_their_categories(tmp_path, local_model, name):
    manager, ids = old_manager(tmp_path, local_model, ["C"])
    receipt_id = ids["C"]
    try:
        k52 = charge(manager, {"publication": {"id": receipt_id}}, 5276)
        if name == "upgrade":
            manager = reopen(tmp_path, local_model, manager)
        else:
            event(manager, name, receipt_id, k52)
        rows = receipt_split(manager, receipt_id)
        assert [category for category, _, has_item in rows if has_item][:2] == ["groceries", "groceries"]
        assert sum(amount for _, amount, _ in rows) == split_target(manager, receipt_id)
        if link_of(manager, receipt_id):
            assert [category for category, _ in charge_split(manager, k52)][:2] == ["groceries", "groceries"] and sum(amount for _, amount in charge_split(manager, k52)) == 5276
        assert manager.ledger.record("receipt", receipt_id)["category_column"] is True and memory_rows(manager) == []
        with manager.store.connection() as db:
            assert db.execute("SELECT one_category FROM receipts WHERE id=?", (receipt_id,)).fetchone()[0] == 0
    finally:
        manager.close()


@pytest.mark.parametrize("category", ["dining", "travel"])
@pytest.mark.parametrize("name", EVENTS)
def test_xd8_mirror_once_applied_a_rebuild_keeps_every_row_in_the_receipts_category(tmp_path, local_model, name, category):
    """After SC-01 step 7 (dining), and after SC-07 step 3 (travel): every row stays in the category, the tip row included (D18)."""
    manager, run, _ = breakfast(tmp_path, local_model)
    try:
        receipt_id = run["publication"]["id"]
        if category == "travel":
            manager.ledger.correct("receipt", receipt_id, {"category": "travel"})
        transaction_id = charge(manager, run, 6155)
        if name == "upgrade":
            manager = reopen(tmp_path, local_model, manager)
        else:
            event(manager, name, receipt_id, transaction_id)
        target = split_target(manager, receipt_id)
        assert_split(manager, receipt_id, target, category)
        if link_of(manager, receipt_id):
            assert {name for name, _ in charge_split(manager, transaction_id)} == {category} and sum(amount for _, amount in charge_split(manager, transaction_id)) == 6155
        assert manager.ledger.record("receipt", receipt_id)["category_column"] is False and memory_rows(manager) == []
    finally:
        manager.close()


H_EVENTS = [name for name in EVENTS if name not in ("delete_item", "family_share")]


@pytest.mark.parametrize("name", H_EVENTS)
def test_xd8_old_rules_keep_the_tip_dining_and_the_difference_spread_on_a_receipt_fr10_has_not_applied_to(tmp_path, local_model, name):
    manager, ids = old_manager(tmp_path, local_model, ["H"])
    receipt_id = ids["H"]
    try:
        with manager.store.connection() as db:  # A charge of −26.00 on the receipt's date, whose seller text is the receipt's.
            account = manager.ledger.create_account("Synth Bank", "credit_card", "USD", last_four="4242")
            document, blob = db.execute("SELECT document_id,blob_hash FROM receipts WHERE id=?", (receipt_id,)).fetchone()
            [transaction_id], _ = manager.ledger.insert_transactions(
                db, account, [{"posted_date": "2026-11-10", "description": "SYNTH DINER", "amount_minor": -2600, "currency": "USD", "locator": {"rows": [1]}}],
                "import", {"document_id": document, "blob_hash": blob, "source_key": "import:h", "run_id": "import:h"}, review_status="proposed")
        if name == "upgrade":
            manager = reopen(tmp_path, local_model, manager)
        elif name == "correct_amount":
            manager.ledger.correct("receipt", receipt_id, {"tax": "1.50"})  # Total and tip are unchanged: the item row is still 2600 − 300.
        elif name == "correct_item":
            manager.ledger.correct_item_fields(receipt_id, 1, {"quantity": "1"})
        else:
            event(manager, name, receipt_id, transaction_id)
        rows = receipt_split(manager, receipt_id)
        assert sorted(rows) == [("dining", 300, False), ("travel", 2300, True)]  # C-sum(2600)
        if link_of(manager, receipt_id):
            assert sorted(charge_split(manager, transaction_id)) == [("dining", 300), ("travel", 2300)]
    finally:
        manager.close()


def test_xd8_contrast_edit_details_categories_applies_one_category_to_h(tmp_path, local_model):
    manager, ids = old_manager(tmp_path, local_model, ["H"])
    receipt_id = ids["H"]
    try:
        manager.ledger.correct("receipt", receipt_id, {"category": "groceries"})
        rows = assert_split(manager, receipt_id, 2600, "groceries")
        assert item_rows(rows) == [("groceries", 2100)] and sorted(no_item_rows(rows)) == [("groceries", 200), ("groceries", 300)]
        assert manager.ledger.record("receipt", receipt_id)["unmatched_minor"] == 200
    finally:
        manager.close()


# D18: the split trace's server-made text -----------------------------------------------------------------------------------------------

def split_note(manager, receipt_id):
    from home_manager.core.trace import ref
    trace = trace_of(manager, ref("split.receipt", receipt_id=receipt_id))
    return trace["formula"] if "formula" in trace else json.dumps(trace)


def test_the_split_trace_says_where_the_tip_counts(tmp_path, local_model):
    manager, ids = old_manager(tmp_path, local_model, ["H"])
    try:
        before = split_note(manager, ids["H"])
        assert "a tip as dining, and any difference from what was charged shared the same way" in before
        manager.ledger.correct("receipt", ids["H"], {"category": "groceries"})
        after = split_note(manager, ids["H"])
        assert "a tip and any difference under the receipt's category" in after and "a tip as dining" not in after
    finally:
        manager.close()


def test_a_dining_receipt_is_recorded_under_dining_whatever_the_description_model_says(tmp_path, local_model):
    texts, indents, replies = breakfast_stub("B0")
    replies["PurchaseDescription"][0]["category"] = "groceries"
    manager, run, _ = read(tmp_path, local_model, texts, indents, replies)
    try:
        row, shown = receipt_of(manager, run)
        assert row["category"] == "dining" and row["one_category"] == 1
        assert_split(manager, run["publication"]["id"], 6155) and by_category(shown) == [("dining", 6155)]
    finally:
        manager.close()


def test_a_category_you_corrected_wins_when_the_receipt_is_read_again(tmp_path, local_model):
    manager, run, _ = breakfast(tmp_path, local_model)
    try:
        receipt_id = run["publication"]["id"]
        manager.ledger.correct("receipt", receipt_id, {"category": "travel"})
        again = read_again(manager, local_model, breakfast_stub("B0")[2])
        row, shown = receipt_of(manager, again)
        assert row["category"] == "travel" and row["one_category"] == 1 and by_category(shown) == [("travel", 6155)]
        assert_split(manager, receipt_id, 6155, "travel")
        assert stored_categories(manager, receipt_id) == [("travel", "receipt")] * 5
    finally:
        manager.close()


# SC-08, FR-13: the kind changes away from dining and back --------------------------------------------------------------------------

def kind_change(manager, local_model, receipt_id, kind, replies):
    """PATCH the kind as the app does (Manager.change_kind) and wait for the reading it starts."""
    local_model["requests"].clear()
    local_model["by_schema"] = {name: list(reply) for name, reply in replies.items()}
    local_model.pop("outputs", None)
    assert manager.change_kind(receipt_id, kind)["run_id"]
    manager.future.result(timeout=60)


def kind_corrections(manager, receipt_id):
    """The receipt's kind corrections as (id, value, previous, snapshot or None), oldest first."""
    with manager.store.connection() as db:
        return [(row["id"], row["value"], row["previous"], json.loads(row["item_categories_json"]) if row["item_categories_json"] else None)
                for row in db.execute("SELECT * FROM record_corrections WHERE record_type='receipt' AND record_id=? AND field='receipt_kind' ORDER BY id", (receipt_id,))]


def undo_kind(manager, receipt_id):
    """Undo the latest kind correction, the way the page's Undo does."""
    return manager.ledger.undo_corrections("receipt", receipt_id, [kind_corrections(manager, receipt_id)[-1][0]])


def one_category_flag(manager, receipt_id):
    with manager.store.connection() as db:
        return db.execute("SELECT one_category FROM receipts WHERE id=?", (receipt_id,)).fetchone()[0]


def test_sc08_kind_change_and_undo(tmp_path, local_model):
    manager, run, _ = breakfast(tmp_path, local_model)
    try:
        receipt_id = run["publication"]["id"]
        manager.ledger.review("receipt", receipt_id, "verified", "Checked.")
        with manager.store.connection() as db:
            db.execute("INSERT INTO item_category_memory(merchant_key,item_key,category,updated_at) VALUES(?,?,'groceries','t')", COFFEE_MEMORY[0][:2])
        # 1. The receipt split S0: all dining, 6155.
        s0 = splits_of(manager)
        assert_split(manager, receipt_id, 6155)
        # 2. To grocery: the items take memory or the model's category, the tip row stays dining, the split adds up, the Category column shows.
        kind_change(manager, local_model, receipt_id, "grocery", grocery_re_read_stub()[2])
        row, shown = receipt_of(manager, run)
        assert (row["receipt_kind"], row["total_minor"], row["tip_minor"], row["review_status"], row["review_source"]) == ("grocery", 6155, 879, "verified", "user")
        assert stored_categories(manager, receipt_id) == [("groceries", "model"), ("groceries", "model"), ("groceries", "memory"), ("dining", "model"), ("dining", "model")]
        rows = receipt_split(manager, receipt_id)
        assert sum(amount for _, amount, _ in rows) == 6155 and [category for category, _ in item_rows(rows)] == ["groceries"] * 3 + ["dining"] * 2
        assert no_item_rows(rows) == [("dining", 879)] and one_category_flag(manager, receipt_id) == 0 and shown["category_column"] is True
        after_change = splits_of(manager)
        # 3. Undo: dining again and the split is S0 (the snapshot taken before the change).
        undone = undo_kind(manager, receipt_id)
        assert undone["receipt_kind"] == "dining" and undone["review_status"] == "verified"
        assert splits_of(manager) == s0 and stored_categories(manager, receipt_id) == [("dining", "receipt")] * 5 and one_category_flag(manager, receipt_id) == 1
        assert receipt_of(manager, run)[1]["category_column"] is False
        # Undoing the Undo is exact too: the grocery split comes back.
        undo_kind(manager, receipt_id)
        assert receipt_of(manager, run)[0]["receipt_kind"] == "grocery" and splits_of(manager) == after_change and one_category_flag(manager, receipt_id) == 0
        undo_kind(manager, receipt_id)
        assert splits_of(manager) == s0
        # 4. To grocery and back to dining: the approved receipt counts wholly under dining at once (FR-13).
        kind_change(manager, local_model, receipt_id, "grocery", grocery_re_read_stub()[2])
        assert splits_of(manager) == after_change
        kind_change(manager, local_model, receipt_id, "dining", breakfast_stub("B0")[2])
        row, shown = receipt_of(manager, run)
        assert (row["receipt_kind"], row["review_status"], row["one_category"]) == ("dining", "verified", 1)
        assert_split(manager, receipt_id, 6155) and shown["category_column"] is False
        assert stored_categories(manager, receipt_id) == [("dining", "receipt")] * 5
        assert memory_rows(manager) == COFFEE_MEMORY  # A kind change writes no memory.
    finally:
        manager.close()


def grocery_receipt(tmp_path, local_model):
    """The breakfast file read, changed to grocery (B7; nobody had decided it, so the reading is written) and then approved: (manager, run, receipt id)."""
    manager, run, _ = breakfast(tmp_path, local_model)
    receipt_id = run["publication"]["id"]
    kind_change(manager, local_model, receipt_id, "grocery", grocery_re_read_stub()[2])
    manager.ledger.review("receipt", receipt_id, "verified", "Checked.")
    return manager, run, receipt_id


def test_sc08a_a_verified_grocery_receipt_changed_to_dining_counts_under_its_category_at_once(tmp_path, local_model):
    manager, run, receipt_id = grocery_receipt(tmp_path, local_model)
    try:
        row = receipt_of(manager, run)[0]
        assert (row["receipt_kind"], row["category"], row["one_category"], row["review_status"]) == ("grocery", "groceries", 0, "verified")
        before_split, before_items, total = splits_of(manager), stored_categories(manager, receipt_id), row["total_minor"]
        kind_change(manager, local_model, receipt_id, "dining", breakfast_stub("B0")[2])
        row, shown = receipt_of(manager, run)
        assert (row["receipt_kind"], row["review_status"], row["one_category"], row["total_minor"]) == ("dining", "verified", 1, total)
        assert_split(manager, receipt_id, total, "groceries") and shown["category_column"] is False
        assert stored_categories(manager, receipt_id) == [("groceries", "receipt")] * 5
        # The snapshot taken before the change (C-snap): Undo gives back that receipt split, those categories and an unset flag.
        assert kind_corrections(manager, receipt_id)[-1][3]["one_category"] == 0
        undo_kind(manager, receipt_id)
        assert splits_of(manager) == before_split and stored_categories(manager, receipt_id) == before_items and one_category_flag(manager, receipt_id) == 0
        assert receipt_of(manager, run)[0]["receipt_kind"] == "grocery"
    finally:
        manager.close()


def test_sc08b_a_kind_change_while_a_reading_runs_is_refused_and_changes_nothing(tmp_path, local_model):
    manager, run, _ = breakfast(tmp_path, local_model)
    try:
        receipt_id = run["publication"]["id"]
        manager.ledger.review("receipt", receipt_id, "verified", "Checked.")
        before, corrections = table_rows(manager, receipt_id), kind_corrections(manager, receipt_id)
        with manager.store.connection() as db:
            [parse] = [row[0] for row in db.execute("SELECT parse_run_id FROM extraction_runs WHERE id=?", (run["id"],))]
            db.execute("INSERT INTO extraction_runs(id,document_id,parse_run_id,config_json,prompt_version,status,created_at,updated_at) "
                       "SELECT 'busy',document_id,parse_run_id,'{}','x','running','t','t' FROM extraction_runs WHERE id=?", (run["id"],))
        with pytest.raises(RuntimeError, match="A reading is in progress"):
            manager.change_kind(receipt_id, "grocery")
        assert table_rows(manager, receipt_id) == before and kind_corrections(manager, receipt_id) == corrections
    finally:
        manager.close()


def test_a_kind_change_that_rewrites_the_receipt_stores_the_snapshot_and_undo_puts_the_flag_and_categories_back(tmp_path, local_model):
    """The written branch (a receipt nobody has decided): the snapshot is taken before the reading changes anything, and the flag follows the kind."""
    manager, run, _ = breakfast(tmp_path, local_model)
    try:
        receipt_id = run["publication"]["id"]
        kind_change(manager, local_model, receipt_id, "grocery", grocery_re_read_stub()[2])
        [(_, value, previous, snapshot)] = kind_corrections(manager, receipt_id)
        assert (value, previous) == ("grocery", "dining") and snapshot["one_category"] == 1 and [item[1:] for item in snapshot["items"]] == [["dining", "receipt"]] * 5
        assert one_category_flag(manager, receipt_id) == 0 and receipt_of(manager, run)[1]["category_column"] is True
        undo_kind(manager, receipt_id)
        assert one_category_flag(manager, receipt_id) == 1 and stored_categories(manager, receipt_id) == [("dining", "receipt")] * 5
    finally:
        manager.close()


def same_amounts_grocery_stub():
    """B7 with the summary's total and tip the dining reading's own (61.55 and 8.79, from the table line), so the two readings differ in kind and category only."""
    texts, indents, replies = grocery_re_read_stub()
    table = find(texts, "18.00% of sale: $8.79 Total $61.55")
    summary = replies["ReceiptGrocerySummary"][0]
    summary["total"], summary["tip"] = proposed(texts, table, image_id, "61.55", "$61.55"), proposed(texts, table, image_id, "8.79", "$8.79")
    return replies


def category_of(manager, receipt_id):
    with manager.store.connection() as db:
        return db.execute("SELECT category FROM receipts WHERE id=?", (receipt_id,)).fetchone()[0]


def test_undo_of_a_kind_change_on_an_unreviewed_receipt_gives_back_the_whole_split_both_ways(tmp_path, local_model):
    """The reading a kind change starts rewrites the receipt's category (dining for a dining reading, the model's otherwise); Undo puts it back
    with the flag and the item categories, so the splits are what they were: dining to grocery and back, then grocery to dining and back."""
    manager, run, _ = breakfast(tmp_path, local_model)
    try:
        receipt_id = run["publication"]["id"]
        before_split, before_items = splits_of(manager), stored_categories(manager, receipt_id)
        assert (category_of(manager, receipt_id), one_category_flag(manager, receipt_id)) == ("dining", 1)
        kind_change(manager, local_model, receipt_id, "grocery", same_amounts_grocery_stub())
        assert (category_of(manager, receipt_id), one_category_flag(manager, receipt_id)) == ("groceries", 0)
        undo_kind(manager, receipt_id)
        assert (category_of(manager, receipt_id), one_category_flag(manager, receipt_id)) == ("dining", 1)
        assert splits_of(manager) == before_split and stored_categories(manager, receipt_id) == before_items
        assert_split(manager, receipt_id, 6155)
        # The other way: the grocery reading, then dining, then Undo.
        kind_change(manager, local_model, receipt_id, "grocery", same_amounts_grocery_stub())
        grocery_split, grocery_items = splits_of(manager), stored_categories(manager, receipt_id)
        kind_change(manager, local_model, receipt_id, "dining", breakfast_stub("B0")[2])
        assert (category_of(manager, receipt_id), one_category_flag(manager, receipt_id)) == ("dining", 1)
        undo_kind(manager, receipt_id)
        assert (category_of(manager, receipt_id), one_category_flag(manager, receipt_id)) == ("groceries", 0)
        assert splits_of(manager) == grocery_split and stored_categories(manager, receipt_id) == grocery_items
    finally:
        manager.close()


def test_undo_of_a_kind_change_keeps_a_category_you_corrected_since_and_a_snapshot_without_one_leaves_it(tmp_path, local_model):
    manager, run, _ = breakfast(tmp_path, local_model)
    try:
        receipt_id = run["publication"]["id"]
        kind_change(manager, local_model, receipt_id, "grocery", same_amounts_grocery_stub())
        manager.ledger.correct("receipt", receipt_id, {"category": "travel"})
        undo_kind(manager, receipt_id)
        assert (category_of(manager, receipt_id), one_category_flag(manager, receipt_id)) == ("travel", 1)
        assert_split(manager, receipt_id, 6155, "travel")
        # A snapshot taken before it held the category (key absent) leaves the category as the reading set it.
        undo_kind(manager, receipt_id)  # The Undo undone: grocery again, with the category you chose.
        kind_change(manager, local_model, receipt_id, "dining", breakfast_stub("B0")[2])
        with manager.store.connection() as db:
            db.execute("UPDATE record_corrections SET item_categories_json=json_remove(item_categories_json,'$.category') "
                       "WHERE id=(SELECT max(id) FROM record_corrections WHERE field='receipt_kind')")
            db.execute("UPDATE receipts SET category='lodging' WHERE id=?", (receipt_id,))
        undo_kind(manager, receipt_id)
        assert category_of(manager, receipt_id) == "lodging"
    finally:
        manager.close()


def test_undo_of_a_kind_change_on_an_old_dining_receipt_gives_back_its_own_categories_and_an_unset_flag(tmp_path, local_model):
    """Receipt D (approved, FR-10 never applied, one item the user's choice): away from dining and Undo, nothing is applied by the Undo."""
    manager, ids = old_manager(tmp_path, local_model, ["D"])
    try:
        receipt_id = ids["D"]
        before_split, before_items = splits_of(manager), stored_categories(manager, receipt_id)
        kind_change(manager, local_model, receipt_id, "grocery", grocery_re_read_stub()[2])
        assert stored_categories(manager, receipt_id)[0] == ("groceries", "user") and one_category_flag(manager, receipt_id) == 0
        undo_kind(manager, receipt_id)
        assert splits_of(manager) == before_split and stored_categories(manager, receipt_id) == before_items and one_category_flag(manager, receipt_id) == 0
        assert manager.ledger.record("receipt", receipt_id)["category_column"] is True
    finally:
        manager.close()


def test_undo_of_a_kind_change_made_before_snapshots_applies_the_kind_put_back(tmp_path, local_model):
    """A kind correction with no snapshot (recorded before migration 081): back to dining applies FR-10; back to another kind re-sorts the items
    from the latest reading, and a category you chose stays."""
    manager, run, _ = breakfast(tmp_path, local_model)
    try:
        receipt_id = run["publication"]["id"]
        manager.ledger.review("receipt", receipt_id, "verified", "Checked.")
        kind_change(manager, local_model, receipt_id, "grocery", grocery_re_read_stub()[2])
        with manager.store.connection() as db:
            db.execute("UPDATE record_corrections SET item_categories_json=NULL WHERE field='receipt_kind'")
            db.execute("UPDATE receipt_items SET category='travel',category_source='receipt' WHERE position=1")  # Something the snapshot would have undone.
        undo_kind(manager, receipt_id)
        assert one_category_flag(manager, receipt_id) == 1 and stored_categories(manager, receipt_id) == [("dining", "receipt")] * 5
        assert_split(manager, receipt_id, 6155)
        # The Undo's own correction has a snapshot; the earlier one is dropped to model a second old correction, then Undo away from dining.
        with manager.store.connection() as db:
            db.execute("UPDATE record_corrections SET item_categories_json=NULL WHERE field='receipt_kind'")
            db.execute("UPDATE receipt_items SET category='travel',category_source='user' WHERE position=2")
        undo_kind(manager, receipt_id)  # The Undo itself undone: the kind put back is grocery, from the latest reading (B7's categories).
        row = receipt_of(manager, run)[0]
        assert row["receipt_kind"] == "grocery" and row["one_category"] == 0
        assert stored_categories(manager, receipt_id) == [("groceries", "model"), ("travel", "user"), ("dining", "model"), ("dining", "model"), ("dining", "model")]
        assert sum(amount for _, amount, _ in receipt_split(manager, receipt_id)) == 6155
    finally:
        manager.close()


# SC-17, FR-14 (b backfill), D27: the item-category backfill on a dining receipt ------------------------------------------------------------

def backfill(manager, local_model, categories, category="groceries"):
    """Run the item-category backfill with a description stub answering every item with `categories`: its result."""
    local_model["outputs"] = [{"description": "Meal", "category": category, "recurrence": None, "item_categories": categories}]
    return ItemCategorizer(manager.store).run(manager.reasoning_config)


def test_sc17_the_backfill_gives_a_dining_receipts_items_its_category(tmp_path, local_model):
    manager, ids = old_manager(tmp_path, local_model, ["E"], memory=True)
    try:
        receipt_id = ids["E"]
        before = splits_of(manager)
        assert ItemCategorizer(manager.store).pending() == [receipt_id]
        # 2. Every item, Coffee too (memory says groceries, the model says groceries), takes dining with source receipt.
        assert backfill(manager, local_model, ["groceries"] * 5) == {"receipts": 1, "items": 5}
        assert stored_categories(manager, receipt_id) == [("dining", "receipt")] * 5
        # 3. The split is unchanged; the column is hidden; the backfill isn't an FR-14 event.
        assert splits_of(manager) == before and one_category_flag(manager, receipt_id) == 0
        assert manager.ledger.record("receipt", receipt_id)["category_column"] is False
        # 4. Again: nothing is pending and nothing changes.
        assert ItemCategorizer(manager.store).pending() == [] and backfill(manager, local_model, ["groceries"] * 5) == {"receipts": 0, "items": 0}
        assert splits_of(manager) == before
    finally:
        manager.close()


def test_sc17a_an_item_under_a_retired_category_moves_to_the_receipts_category_with_its_split(tmp_path, local_model):
    manager, ids = old_manager(tmp_path, local_model, ["E"], memory=True)
    try:
        receipt_id, retired = ids["E"], LEGACY_CATEGORIES[0]
        with manager.store.connection() as db:
            db.execute("UPDATE receipt_items SET category=?,category_source='legacy' WHERE receipt_id=? AND position=1", (retired, receipt_id))
            db.execute("UPDATE category_splits SET category=? WHERE receipt_id=? AND receipt_item_id=(SELECT id FROM receipt_items WHERE receipt_id=? AND position=1)",
                       (retired, receipt_id, receipt_id))
        before = splits_of(manager)
        assert ItemCategorizer(manager.store).pending() == [receipt_id]
        assert backfill(manager, local_model, ["groceries"] * 5) == {"receipts": 1, "items": 1}
        assert stored_categories(manager, receipt_id) == [("dining", "receipt")] + [(None, None)] * 4
        moved = [tuple(row if row[3] != retired else (*row[:3], "dining", row[4])) for row in before]
        assert splits_of(manager) == sorted(moved) and sum(amount for *_, amount in splits_of(manager)) == 5276
        assert sum(amount for category, amount, _ in receipt_split(manager, receipt_id) if category == "dining") == 5276
        assert one_category_flag(manager, receipt_id) == 0
    finally:
        manager.close()


def test_sc17b_a_grocery_receipt_is_categorised_as_today_by_memory_then_the_model(tmp_path, local_model):
    manager, ids = old_manager(tmp_path, local_model, ["G"])
    try:
        receipt_id = ids["G"]
        with manager.store.connection() as db:
            merchant = manager.ledger.merchant(db, "Synth Mart")
            db.execute("UPDATE receipts SET merchant_id=? WHERE id=?", (merchant, receipt_id))
            db.execute("UPDATE receipt_items SET category=NULL,category_source=NULL WHERE receipt_id=?", (receipt_id,))
            db.execute("INSERT INTO item_category_memory(merchant_key,item_key,category,updated_at) VALUES(?,?,'household supplies','t')",
                       (normalize_name("Synth Mart"), normalize_name("Milk")))
        assert backfill(manager, local_model, ["dining", "entertainment"], "groceries") == {"receipts": 1, "items": 2}
        assert stored_categories(manager, receipt_id) == [("household supplies", "memory"), ("entertainment", "model")]
    finally:
        manager.close()


def test_sc17c_the_backfill_leaves_the_tip_and_the_difference_under_todays_rules(tmp_path, local_model):
    manager, ids = old_manager(tmp_path, local_model, ["H"])
    try:
        receipt_id = ids["H"]
        with manager.store.connection() as db:
            db.execute("UPDATE receipt_items SET category=NULL,category_source=NULL WHERE receipt_id=?", (receipt_id,))
        before = splits_of(manager)
        assert backfill(manager, local_model, ["groceries"]) == {"receipts": 1, "items": 1}
        assert stored_categories(manager, receipt_id) == [("travel", "receipt")]
        assert splits_of(manager) == before and one_category_flag(manager, receipt_id) == 0
        assert ("dining", 300, False) in receipt_split(manager, receipt_id)  # The tip row stays dining.
    finally:
        manager.close()


# SL-07: a reading that changes the total removes the charge links it no longer supports (FR-28 – FR-30, D34 – D41) --------------------------------------

def note(charge_text, total_text, confirmed=False):
    """FR-30's note as the contract writes it."""
    return f"The match{' you confirmed' if confirmed else ''} to the {charge_text} charge on 2026-11-12 was removed: {total_text}"


REMOVED_52 = note("$52.76", "this reading's total ($61.55) no longer matches it.")
CONFIRMED_52 = note("$52.76", "this reading's total ($61.55) no longer matches it.", confirmed=True)


def links_of(manager, receipt_id):
    """[(transaction id, review_status)] of every link row of the receipt, of every status (C-links)."""
    with manager.store.connection() as db:
        return [tuple(row) for row in db.execute("SELECT transaction_id,review_status FROM transaction_receipt_links WHERE receipt_id=? ORDER BY id", (receipt_id,))]


def link_rows(manager, receipt_id):
    """The receipt's link rows with every column but the timestamps, to compare "unchanged" (same id, status, score and method)."""
    with manager.store.connection() as db:
        return [tuple(row) for row in db.execute("SELECT id,transaction_id,review_status,match_score,match_method,estimate_rate_id,estimate_minor "
                                                 "FROM transaction_receipt_links WHERE receipt_id=? ORDER BY id", (receipt_id,))]


def charge_rows_of(manager, transaction_id, receipt_id=None):
    """How many category_splits rows a charge has (for one receipt when given): C-nosplit needs 0."""
    with manager.store.connection() as db:
        return db.execute("SELECT count(*) FROM category_splits WHERE transaction_id=?" + (" AND receipt_id=?" if receipt_id else ""),
                          (transaction_id, receipt_id) if receipt_id else (transaction_id,)).fetchone()[0]


def charge_state(manager, transaction_id):
    """(category, merchant_id) of a charge: what its own rules give it, and the merchant a link may have given it."""
    with manager.store.connection() as db:
        return tuple(db.execute("SELECT category,merchant_id FROM transactions WHERE id=?", (transaction_id,)).fetchone())


def removal_notes(manager, receipt_id):
    """C-note: the receipt's issues that start "The match"."""
    return [issue for issue in manager.ledger.record("receipt", receipt_id)["issues"] if issue.startswith("The match")]


def open_questions(manager):
    with manager.store.connection() as db:
        return db.execute("SELECT count(*) FROM reconciliation_issues WHERE status='open'").fetchone()[0]


def assert_unlinked_after_reread(manager, receipt_id, transaction_id, text, snapshot=None):
    """C-links(receipt, []), C-nosplit(charge), C-note(receipt, text), C-review(needs_review, [FR-06 reason, text]) and no question: SC-09 step 6."""
    assert links_of(manager, receipt_id) == [] and charge_rows_of(manager, transaction_id) == 0
    shown = manager.ledger.record("receipt", receipt_id)
    assert removal_notes(manager, receipt_id) == [text] and shown["issues"] == [WORKED_OUT, text] and shown["review_status"] == "needs_review"
    assert not [issue for issue in shown["issues"] if issue.startswith("Amount paid (")] and open_questions(manager) == 0
    if snapshot:  # The charge decides its category and merchant again, as before the link (FR-29).
        assert charge_state(manager, transaction_id) == snapshot


def sc09_through_step5(tmp_path, local_model, approve=False):
    """SC-09 steps 1 – 5 on the old receipt C and K52 (with the link approved after step 3 when approve): (manager, receipt id, K52, K52's state before step 3)."""
    manager, ids = old_manager(tmp_path, local_model, ["C"])
    receipt_id = ids["C"]
    k52 = charge(manager, {"publication": {"id": receipt_id}}, 5276)
    snapshot = charge_state(manager, k52)
    reconcile(manager)
    assert link_of(manager, receipt_id)[1:] == (k52, "proposed")
    if approve:
        manager.reconciler.review_link("receipt", link_of(manager, receipt_id)[0], "verified")
        assert links_of(manager, receipt_id) == [(k52, "verified")]
    read_again_of(manager, local_model, receipt_id, breakfast_stub("B0")[2])
    return manager, receipt_id, k52, snapshot


def test_sc09a_a_restart_between_the_reading_and_the_next_reconciliation_changes_nothing(tmp_path, local_model):
    manager, receipt_id, k52, snapshot = sc09_through_step5(tmp_path, local_model)
    try:
        manager = reopen(tmp_path, local_model, manager)
        assert_unlinked_after_reread(manager, receipt_id, k52, REMOVED_52, snapshot=snapshot)
        reconcile(manager)
        assert_split(manager, receipt_id, 6155)
        assert_unlinked_after_reread(manager, receipt_id, k52, REMOVED_52, snapshot=snapshot)
    finally:
        manager.close()


def test_sc09b_a_link_review_and_an_unlink_and_relink_keep_the_groceries_rows_and_the_sums(tmp_path, local_model):
    manager, ids = old_manager(tmp_path, local_model, ["C"])
    receipt_id = ids["C"]
    try:
        k52 = charge(manager, {"publication": {"id": receipt_id}}, 5276)
        reconcile(manager)
        [(link_id, _, _)] = [link_of(manager, receipt_id)]

        def check(linked):
            rows = receipt_split(manager, receipt_id)
            assert [category for category, _, has_item in rows if has_item][:2] == ["groceries", "groceries"] and sum(amount for _, amount, _ in rows) == 5276
            if linked:
                assert [category for category, _ in charge_split(manager, k52)][:2] == ["groceries", "groceries"]
                assert sum(amount for _, amount in charge_split(manager, k52)) == 5276
            else:
                assert charge_split(manager, k52) == []
        manager.reconciler.review_link("receipt", link_id, "verified")
        check(True)
        manager.reconciler.review_link("receipt", link_id, "rejected")  # Unlink,
        check(False)
        manager.reconciler.review_link("receipt", link_id, "verified")  # and link it again in place.
        check(True)
    finally:
        manager.close()


def test_sc09c_a_link_you_approved_is_removed_with_the_note_that_says_so(tmp_path, local_model):
    manager, receipt_id, k52, snapshot = sc09_through_step5(tmp_path, local_model, approve=True)
    try:
        assert_unlinked_after_reread(manager, receipt_id, k52, CONFIRMED_52, snapshot=snapshot)
        with manager.store.connection() as db:
            assert db.execute("SELECT count(*) FROM transaction_receipt_links").fetchone()[0] == 0
    finally:
        manager.close()


# SC-20 ------------------------------------------------------------------------------------------------------------------------------

def reject_link(manager, receipt_id, transaction_id):
    """The fixture K60 has: a rejected link row to the receipt (method near_amount, score 30). Returns the row."""
    with manager.store.connection() as db:
        db.execute("INSERT INTO transaction_receipt_links(transaction_id,receipt_id,match_score,match_method,review_status,created_at,updated_at) "
                   "VALUES(?,?,30,'near_amount','rejected','t','t')", (transaction_id, receipt_id))
    return link_rows(manager, receipt_id)[-1]


def sc20_library(tmp_path, local_model, k61=True):
    """Old receipt C with K52, K60 (a rejected link to C) and (k61) K61: (manager, receipt id, {name: transaction id}, K60's link row)."""
    manager, ids = old_manager(tmp_path, local_model, ["C"])
    receipt_id = ids["C"]
    run = {"publication": {"id": receipt_id}}
    found = {"K52": charge(manager, run, 5276)}
    if k61:
        found["K61"] = charge(manager, run, 6155)
    found["K60"] = charge(manager, run, 6000)
    return manager, receipt_id, found, reject_link(manager, receipt_id, found["K60"])


def test_sc20_a_link_you_confirmed_is_removed_and_the_matching_charge_links(tmp_path, local_model):
    manager, receipt_id, charges, k60_row = sc20_library(tmp_path, local_model)
    k52, k61, k60 = charges["K52"], charges["K61"], charges["K60"]
    try:
        # 1. Upgrade changes nothing: K60's row as the fixture left it.
        before = table_rows(manager, receipt_id)
        manager = reopen(tmp_path, local_model, manager)
        assert table_rows(manager, receipt_id) == before and link_rows(manager, receipt_id) == [k60_row]
        # 2. Reconcile: K52 exactly (K61 isn't considered while an exact charge exists), K60 stays rejected.
        reconcile(manager)
        assert links_of(manager, receipt_id) == [(k60, "rejected"), (k52, "proposed")] and link_rows(manager, receipt_id)[0] == k60_row
        # 3. Approve that link: verified; the charge split sums to 5276.
        manager.reconciler.review_link("receipt", link_of(manager, receipt_id)[0], "verified")
        assert links_of(manager, receipt_id) == [(k60, "rejected"), (k52, "verified")] and sum(amount for _, amount in charge_split(manager, k52)) == 5276
        # 4. Extract again from the v6 reading with B0: the confirmed link is removed (not rejected), with the note; the reconciliation after the
        #    reading links K61 exactly, all dining; K60's row is as it was and no question is open.
        run = read_again_of(manager, local_model, receipt_id, breakfast_stub("B0")[2])
        row, shown = receipt_of(manager, run)
        assert (row["total_minor"], row["tip_minor"]) == (6155, 879)
        assert links_of(manager, receipt_id) == [(k60, "rejected"), (k61, "proposed")] and link_rows(manager, receipt_id)[0] == k60_row
        assert charge_rows_of(manager, k52) == 0 and charge_state(manager, k52)[1] is None
        assert shown["issues"] == [WORKED_OUT, CONFIRMED_52] and row["review_status"] == "needs_review" and removal_notes(manager, receipt_id) == [CONFIRMED_52]
        assert "amount" in link_rows(manager, receipt_id)[1][4]
        assert {category for category, _ in charge_split(manager, k61)} == {"dining"} and sum(amount for _, amount in charge_split(manager, k61)) == 6155
        assert open_questions(manager) == 0 and memory_rows(manager) == []
        # 5. A further reconciliation changes nothing.
        after = (links_of(manager, receipt_id), charge_split(manager, k61), receipt_split(manager, receipt_id))
        reconcile(manager)
        assert (links_of(manager, receipt_id), charge_split(manager, k61), receipt_split(manager, receipt_id)) == after
        # (b) A restart between steps 4 and 5 ends the same.
        manager = reopen(tmp_path, local_model, manager)
        assert (links_of(manager, receipt_id), charge_split(manager, k61), receipt_split(manager, receipt_id)) == after
        reconcile(manager)
        assert (links_of(manager, receipt_id), charge_split(manager, k61), receipt_split(manager, receipt_id)) == after
    finally:
        manager.close()


def test_sc20a_a_removed_link_is_not_a_rejection_so_the_pair_links_again_when_it_matches_again(tmp_path, local_model):
    manager, receipt_id, charges, k60_row = sc20_library(tmp_path, local_model, k61=False)
    k52, k60 = charges["K52"], charges["K60"]
    try:
        reconcile(manager)
        manager.reconciler.review_link("receipt", link_of(manager, receipt_id)[0], "verified")
        read_again_of(manager, local_model, receipt_id, breakfast_stub("B0")[2])
        # No K61: after the reading the receipt is linked to nothing (K52 is smaller than 6155), the only row is K60's rejected one, and no question exists.
        assert links_of(manager, receipt_id) == [(k60, "rejected")] and link_rows(manager, receipt_id) == [k60_row] and open_questions(manager) == 0
        assert charge_rows_of(manager, k52) == 0
        # Correct Total to 52.76 (which reconciles after it): K52 links again, exactly, proposed. The removal note stays: it doesn't start with "Total".
        manager.correct_record("receipt", receipt_id, {"total": "52.76"})
        assert links_of(manager, receipt_id) == [(k60, "rejected"), (k52, "proposed")] and link_rows(manager, receipt_id)[0] == k60_row
        assert removal_notes(manager, receipt_id) == [CONFIRMED_52]
    finally:
        manager.close()


def test_sc20c_the_documents_of_a_removed_link_no_longer_show_each_other_as_the_same_purchase(tmp_path, local_model):
    manager, ids = old_manager(tmp_path, local_model, ["C"])
    receipt_id = ids["C"]
    try:
        # K52 was read from another document (a statement or CSV), so it has evidence and a verified link joins the two documents.
        with manager.store.connection() as db:
            own = db.execute("SELECT document_id FROM receipts WHERE id=?", (receipt_id,)).fetchone()[0]
            other = db.execute("INSERT INTO occurrences(source_root,path_key,relative_path,current_hash,first_seen,last_seen,last_job) "
                               "SELECT source_root,'export.csv','export.csv',current_hash,'t','t',last_job FROM occurrences WHERE id=?", (own,)).lastrowid
        k52 = charge(manager, {"publication": {"id": receipt_id}}, 5276)
        with manager.store.connection() as db:
            db.execute("UPDATE financial_evidence_links SET document_id=? WHERE record_type='transaction' AND record_id=?", (other, k52))
        reconcile(manager)
        manager.reconciler.review_link("receipt", link_of(manager, receipt_id)[0], "verified")
        assert [(link["reason"], link["status"], link["document_id"]) for link in manager.store.linked_documents(own)] == [("same_record", "verified", other)]
        read_again_of(manager, local_model, receipt_id, breakfast_stub("B0")[2])
        assert manager.store.linked_documents(own) == []
        with manager.store.connection() as db:
            assert db.execute("SELECT count(*) FROM occurrence_links WHERE status='rejected'").fetchone()[0] == 0
    finally:
        manager.close()


def test_a_dining_receipt_delivered_by_the_family_counts_wholly_under_its_category(tmp_path, local_model):
    """FR-14 (a) lists a family-sent receipt: the copy in a person's library is a dining receipt, so FR-10 applies there whatever its items
    carried in the family's library and whatever that person's own item memory says."""
    manager, run, _ = breakfast(tmp_path, local_model)
    person = Store(tmp_path / "person")
    try:
        receipt_id = run["publication"]["id"]
        with manager.store.connection() as db:
            db.execute("UPDATE receipts SET category='travel' WHERE id=?", (receipt_id,))
            db.execute("UPDATE receipt_items SET category='groceries',category_source='model' WHERE receipt_id=? AND position=1", (receipt_id,))
        record, row = record_payload(manager.store, "receipt", receipt_id)
        assert (record["receipt_kind"], record["category"]) == ("dining", "travel") and record["tip_minor"] == 879
        document = manager.store.blob_path(row["blob_hash"]).read_bytes()
        with person.connection() as db:
            db.execute("INSERT INTO item_category_memory(merchant_key,item_key,category,updated_at) VALUES(?,?,'groceries','t')", COFFEE_MEMORY[0][:2])
        delivery = {"key": "family-dining-1", "action": "record", "record_type": "receipt", "record": record, "name": "breakfast.png",
                    "blob_hash": hashlib.sha256(document).hexdigest(), "share": 3000, "people": ["dad", "mom"]}
        [kind, copy_id] = apply_delivery(person, delivery, document)["record"]
        with person.connection() as db:
            copy = dict(db.execute("SELECT * FROM receipts WHERE id=?", (copy_id,)).fetchone())
            items = [tuple(item) for item in db.execute("SELECT category,category_source FROM receipt_items WHERE receipt_id=? ORDER BY position", (copy_id,))]
            split = [(item[0], item[1]) for item in db.execute("SELECT category,amount_minor FROM category_splits WHERE receipt_id=? AND transaction_id IS NULL", (copy_id,))]
        assert (copy["receipt_kind"], copy["one_category"], copy["total_minor"], copy["tip_minor"]) == ("dining", 1, 6155, 879)
        assert items == [("travel", "receipt")] * 5
        # Items, the tip and the difference all count under the receipt's category, and the person's part of the total is all of it.
        assert {category for category, _ in split} == {"travel"} and sum(amount for _, amount in split) == 3000
    finally:
        person.close()
        manager.close()


def test_sc20c_a_second_receipt_of_the_document_still_joined_keeps_the_documents_shown_as_the_same_purchase(tmp_path, local_model):
    """A file of two receipts (segments 0 and 1): a reread of the first removes its stale link, but the second receipt's link still joins a charge read
    from the same other document, so the two documents keep showing each other."""
    manager, ids = old_manager(tmp_path, local_model, ["C"])
    first = ids["C"]
    try:
        with manager.store.connection() as db:
            own = db.execute("SELECT document_id FROM receipts WHERE id=?", (first,)).fetchone()[0]
            other = db.execute("INSERT INTO occurrences(source_root,path_key,relative_path,current_hash,first_seen,last_seen,last_job) "
                               "SELECT source_root,'export.csv','export.csv',current_hash,'t','t',last_job FROM occurrences WHERE id=?", (own,)).lastrowid
            second = db.execute("INSERT INTO receipts(blob_hash,segment,document_id,merchant_id,purchase_date,total_minor,currency,review_status,validation_json,"
                                "created_at,updated_at) SELECT blob_hash,1,document_id,merchant_id,purchase_date,3000,currency,'proposed','[]',created_at,updated_at "
                                "FROM receipts WHERE id=?", (first,)).lastrowid
        k52, k30 = charge(manager, {"publication": {"id": first}}, 5276), charge(manager, {"publication": {"id": first}}, 3000, "GACHAS BREAKFAST BAR 2")
        with manager.store.connection() as db:
            db.execute("UPDATE financial_evidence_links SET document_id=? WHERE record_type='transaction' AND record_id IN (?,?)", (other, k52, k30))
        reconcile(manager)
        assert link_of(manager, first)[1] == k52 and link_of(manager, second)[1] == k30
        manager.reconciler.review_link("receipt", link_of(manager, first)[0], "verified")
        assert [(link["reason"], link["document_id"]) for link in manager.store.linked_documents(own)] == [("same_record", other)]
        read_again_of(manager, local_model, first, breakfast_stub("B0")[2])
        assert link_of(manager, first) is None and link_of(manager, second)[1] == k30  # The first's link went; the second's holds.
        assert [(link["reason"], link["document_id"]) for link in manager.store.linked_documents(own)] == [("same_record", other)]
    finally:
        manager.close()
