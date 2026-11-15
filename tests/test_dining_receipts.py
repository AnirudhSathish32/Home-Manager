"""The charged total and tip of a dining receipt (specs/dining-receipt-indent FR-01 – FR-07 (the link) and FR-09, SC-01 – SC-04, SC-06, SC-19, D19 – D31):
a later, larger total is what was charged, a tip not printed is worked out from the two printed lines, and a suggested-tip table is never the source of
either. Synthetic breakfast receipt (tests/dining_receipt_fixtures.py) and the local model stub only.

Every "C-cat", "By category" and stored-item-category check of these scenarios needs one category per dining receipt (FR-10); SL-05 adds them where
the tests below carry a `# SL-05: C-cat` comment. Test functions of SL-05 and later slices are added to this file by those slices."""

from decimal import Decimal
import json
from typing import get_origin

import pytest

from dining_receipt_fixtures import breakfast_stub
from home_manager.core.money import amount_text
from home_manager.documents import dining_total
from home_manager.documents.extraction import looks_like_several
from home_manager.documents.receipt_schema import TextLine
from home_manager.finance.reconcile import Reconciler
from test_receipt_kinds import check_named, inputs_by_key, trace_of
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
        # 7. The page's Tip note, and nothing left over to show as "Not matched to an item" is SL-05's (FR-27).
        assert shown["tip_note"] == "Worked out: Total $61.55 − Bill $52.76"
        # The saved reading holds the decided values, the decision and the basis (P4).
        assert run["result"]["dining"]["tip_basis"]["bill"]["line_id"] == "line-22" and run["result"]["dining"]["issues"] == []
        # 6. One category (FR-10): SL-05: C-cat
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
            charge_split = [row[0] for row in db.execute("SELECT amount_minor FROM category_splits WHERE transaction_id=?", (transaction_id,))]
        assert [(link[0], link[1]) for link in links] == [(transaction_id, "proposed")] and "amount" in links[0][2] and "near" not in links[0][2]
        assert questions == 0 and sum(charge_split) == 6155  # C-sum; SL-05: C-cat
        assert sum(amount for _, amount, _ in receipt_split(manager, run["publication"]["id"])) == 6155
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
        assert sum(amount for _, amount, _ in receipt_split(manager, run["publication"]["id"])) == 6155  # SL-05: C-cat
    finally:
        manager.close()


def test_sc02a_a_printed_tip_that_does_not_make_the_total_is_an_issue(tmp_path, local_model):
    manager, run, _ = breakfast(tmp_path, local_model, "B3")
    try:
        row, shown = receipt_of(manager, run)
        assert (row["tip_minor"], row["total_minor"]) == (500, 6155) and row["tip_worked_out_json"] is None
        assert "Tip ($5.00) and the bill ($52.76) don't make the total ($61.55)." in shown["issues"]
        assert row["review_status"] == "needs_review" and not any(issue.startswith("Tip $") for issue in shown["issues"])
        assert sum(amount for _, amount, _ in receipt_split(manager, run["publication"]["id"])) == 6155
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
        assert sum(amount for _, amount, _ in receipt_split(manager, run["publication"]["id"])) == 5276  # SL-05: C-cat
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
        assert sum(amount for _, amount, _ in receipt_split(manager, run["publication"]["id"])) == 6155
        # SL-05: C-cat, the 879 difference as one no-item row, "Not matched to an item" 879
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
        assert sum(amount for _, amount, _ in receipt_split(manager, run["publication"]["id"])) == 6155
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
        assert sum(amount for _, amount, _ in receipt_split(manager, receipt_id)) == 6155  # SL-05: C-cat
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
