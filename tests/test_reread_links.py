"""Which charge links a reading removes (specs/dining-receipt-indent FR-28 – FR-30, D34 – D41: SC-21, SC-22): when a reading rewrites a receipt and
changes its counted total, each live link the new total no longer supports is removed, on every receipt kind, with a note and a stay in Review. Synthetic
receipts, charges and rates only; every re-read goes through the app's extraction job, so the reconciliation after a reading runs as in the app (the foreign
receipt of SC-21 (d) is built through the ledger, as the contract says, and reconciled after each reading the way the job does)."""

import json

import pytest

from bill_kinds_fixtures import RENT, rent_replies, rent_row
from conftest import assert_ledger_healthy, documents_by_name, inbox_scan
from dining_receipt_fixtures import b11_stub, breakfast_stub, grocery_re_read_stub
from home_manager.finance.fx import EcbRates
from home_manager.finance.ledger import Ledger
from home_manager.finance.reconcile import Reconciler
from home_manager.library.storage import Store
from test_bill_kinds import pay_and_reconcile, read_bill
from test_dining_receipts import (
    breakfast,
    charge,
    charge_rows_of,
    charge_split,
    link_of,
    link_rows,
    links_of,
    note,
    old_manager,
    open_questions,
    read_again,
    read_again_of,
    receipt_of,
    receipt_split,
    reconcile,
    removal_notes,
    table_rows,
)
from test_extraction import extract
from test_fx import FakeEcb, ecb_zip
from test_receipt_side_lines import read


def grocery(tmp_path, local_model, variant="B11"):
    """The B11 receipt read and recorded: (manager, run, receipt id)."""
    texts, indents, replies = b11_stub(variant)
    manager, run, _ = read(tmp_path, local_model, texts, indents, replies)
    return manager, run, run["publication"]["id"]


def read_b11(manager, local_model, variant):
    """Extract again with a B11 variant (the same lines; the summary's total and its citation differ)."""
    return read_again(manager, local_model, b11_stub(variant)[2])


def total_of(manager, receipt_id):
    with manager.store.connection() as db:
        return db.execute("SELECT total_minor FROM receipts WHERE id=?", (receipt_id,)).fetchone()[0]


def question_of(manager, receipt_id):
    """(id, candidate transaction ids) of the receipt's open near-match question, or None."""
    with manager.store.connection() as db:
        row = db.execute("SELECT id,detail_json FROM reconciliation_issues WHERE issue_type='ambiguous_receipt_match' AND record_type='receipt' "
                         "AND record_id=? AND status='open'", (receipt_id,)).fetchone()
    return (row["id"], json.loads(row["detail_json"])["candidate_transaction_ids"]) if row else None


def grocery_note(charge_text, total_text, confirmed=False):
    return note(charge_text, f"this reading's total ({total_text}) no longer matches it.", confirmed)


# SC-21 ------------------------------------------------------------------------------------------------------------------------------

def sc21_to_step6(tmp_path, local_model):
    """SC-21 steps 1 – 6: B11 linked to K10 (proposed), read again at 9.00 (removed, a question), K10 chosen (verified), read again at 10.00 and 9.00 (kept):
    (manager, receipt id, K10)."""
    manager, run, receipt_id = grocery(tmp_path, local_model)
    k10 = charge(manager, run, 1000, "SYNTH MART")
    reconcile(manager)
    read_b11(manager, local_model, "B11b")
    assert question_of(manager, receipt_id)
    manager.reconciler.resolve_issue(question_of(manager, receipt_id)[0], k10)
    read_b11(manager, local_model, "B11")
    read_b11(manager, local_model, "B11b")
    assert links_of(manager, receipt_id) == [(k10, "verified")] and total_of(manager, receipt_id) == 900
    return manager, receipt_id, k10


def test_sc21_which_links_hold_after_a_reread(tmp_path, local_model):
    manager, run, receipt_id = grocery(tmp_path, local_model)
    try:
        k10 = charge(manager, run, 1000, "SYNTH MART")
        # 1. Record B11 and reconcile: total 1000, linked to K10 exactly (proposed). Remember the row.
        assert total_of(manager, receipt_id) == 1000
        reconcile(manager)
        assert links_of(manager, receipt_id) == [(k10, "proposed")]
        row = link_rows(manager, receipt_id)
        # 2. Extract again with the same total: nothing is tested (D39), the row is as it was, no note.
        read_b11(manager, local_model, "B11")
        assert link_rows(manager, receipt_id) == row and removal_notes(manager, receipt_id) == []
        # 3. Extract again at 9.00: the proposed link is removed, reconciliation never links a larger charge by itself (D35).
        run = read_b11(manager, local_model, "B11b")
        shown = manager.ledger.record("receipt", receipt_id)
        assert total_of(manager, receipt_id) == 900 and links_of(manager, receipt_id) == [] and charge_rows_of(manager, k10) == 0
        assert removal_notes(manager, receipt_id) == [grocery_note("$10.00", "$9.00")] and shown["review_status"] == "needs_review"
        # The reconciliation after the reading asks the near-match question, K10 the only candidate: the removed pair isn't rejected (D37).
        asked, candidates = question_of(manager, receipt_id)
        assert candidates == [k10]
        # 4. Answer with K10: a link you chose (verified); the charge counts 1000, the receipt 900.
        manager.reconciler.resolve_issue(asked, k10)
        assert links_of(manager, receipt_id) == [(k10, "verified")]
        [method] = [link[4] for link in link_rows(manager, receipt_id)]
        assert "near_amount" in method and "user_choice" in method
        assert sum(amount for _, amount in charge_split(manager, k10)) == 1000 and sum(amount for _, amount, _ in receipt_split(manager, receipt_id)) == 900
        chosen = link_rows(manager, receipt_id)
        # 5. Extract again at 10.00: the link you chose holds at the exact amount; unchanged, no note.
        read_b11(manager, local_model, "B11")
        assert link_rows(manager, receipt_id) == chosen and removal_notes(manager, receipt_id) == []
        # 6. Extract again at 9.00: it holds within the allowance (1000 × 100 <= 900 × 130); unchanged, no note, the charge still counts 1000.
        read_b11(manager, local_model, "B11b")
        assert link_rows(manager, receipt_id) == chosen and removal_notes(manager, receipt_id) == []
        assert sum(amount for _, amount in charge_split(manager, k10)) == 1000
        # 7. Extract again at 7.00: 1000 × 100 > 700 × 130, so it is removed with the "you confirmed" note, and no question follows (K10 is more than 30% larger).
        read_b11(manager, local_model, "B11c")
        assert total_of(manager, receipt_id) == 700 and links_of(manager, receipt_id) == [] and charge_rows_of(manager, k10) == 0
        assert removal_notes(manager, receipt_id) == [grocery_note("$10.00", "$7.00", confirmed=True)]
        assert manager.ledger.record("receipt", receipt_id)["review_status"] == "needs_review" and open_questions(manager) == 0
        with manager.store.connection() as db:
            assert db.execute("SELECT count(*) FROM transaction_receipt_links").fetchone()[0] == 0  # None is rejected.
    finally:
        manager.close()


def test_sc21a_the_allowance_boundary_is_exact_to_the_cent(tmp_path, local_model):
    manager, receipt_id, k10 = sc21_to_step6(tmp_path, local_model)
    try:
        chosen = link_rows(manager, receipt_id)
        read_b11(manager, local_model, "B11d")  # 7.70: 100000 <= 100100, holds.
        assert total_of(manager, receipt_id) == 770 and link_rows(manager, receipt_id) == chosen and removal_notes(manager, receipt_id) == []
        read_b11(manager, local_model, "B11e")  # 7.69: 100000 > 99970, removed.
        assert total_of(manager, receipt_id) == 769 and links_of(manager, receipt_id) == []
        assert removal_notes(manager, receipt_id) == [grocery_note("$10.00", "$7.69", confirmed=True)]
    finally:
        manager.close()


def test_sc21b_no_total_removes_every_link_with_the_note_that_says_so(tmp_path, local_model):
    manager, receipt_id, k10 = sc21_to_step6(tmp_path, local_model)
    try:
        read_b11(manager, local_model, "B11n")
        assert total_of(manager, receipt_id) is None and links_of(manager, receipt_id) == [] and charge_rows_of(manager, k10) == 0
        assert removal_notes(manager, receipt_id) == [note("$10.00", "this reading has no total.", confirmed=True)]
    finally:
        manager.close()


def test_sc21c_a_gift_card_receipts_removal_note_names_the_amount_paid_and_no_amount_paid_note_follows(tmp_path, local_model):
    manager, run, receipt_id = grocery(tmp_path, local_model, "B11g")
    try:
        k9 = charge(manager, run, 900, "SYNTH MART")
        assert total_of(manager, receipt_id) == 900  # Printed 10.00, paid 9.00.
        reconcile(manager)
        assert links_of(manager, receipt_id) == [(k9, "proposed")]
        read_b11(manager, local_model, "B11g'")  # Printed 9.00, paid 8.00.
        assert total_of(manager, receipt_id) == 800 and links_of(manager, receipt_id) == [] and charge_rows_of(manager, k9) == 0
        issues = manager.ledger.record("receipt", receipt_id)["issues"]
        assert removal_notes(manager, receipt_id) == [grocery_note("$9.00", "$8.00")] and not [issue for issue in issues if issue.startswith("Amount paid (")]
        # The reconciliation after the reading asks the near-match question: 900 is at most 30% above 800.
        assert question_of(manager, receipt_id)[1] == [k9]
    finally:
        manager.close()


def test_a_link_that_still_holds_keeps_its_gift_card_note(tmp_path, local_model):
    """D40's other half: the "Amount paid (" note stays for a link that holds (today's rule, unchanged)."""
    manager, run, receipt_id = grocery(tmp_path, local_model, "B11g")
    try:
        k10 = charge(manager, run, 1000, "SYNTH MART")
        manager.reconciler.run("extraction")
        assert links_of(manager, receipt_id) == []  # 900 paid; 1000 is a near match only.
        with manager.store.connection() as db:
            db.execute("INSERT INTO transaction_receipt_links(transaction_id,receipt_id,match_score,match_method,review_status,created_at,updated_at) "
                       "VALUES(?,?,60,'near_amount+user_choice','verified','t','t')", (k10, receipt_id))
            manager.ledger.refresh_paid(db, receipt_id)
        assert [issue for issue in manager.ledger.record("receipt", receipt_id)["issues"] if issue.startswith("Amount paid (")] == [
            "Amount paid (9.00) no longer equals the linked charge (10.00)."]
    finally:
        manager.close()


# SC-21 (d): a foreign receipt, built through the ledger as tests/test_fx.py builds one ----------------------------------------------------

def history(*rows):
    return "Date,USD,\n" + "".join(f"{day},{rate},\n" for day, rate in rows)


class Foreign:
    """A EUR receipt of 100.00 on 2026-11-12, a cached EUR to USD rate, and a USD charge of 112.00 chosen in the cross-currency question (verified,
    its rate id stored). reread(total) records a new reading of the receipt and reconciles after it, the way the extraction job does."""

    def __init__(self, tmp_path, rows=(("2026-11-12", "1.1000"),)):
        """rows: the cached rates (day, USD per EUR); none means no rates at all, and the link is then a fixture row with no stored rate."""
        self.store = Store(tmp_path / "managed")
        inbox_scan(self.store, {"card.csv": b"date,amount\n", "cafe.png": b"synthetic eur receipt"})
        self.docs = documents_by_name(self.store)
        self.ledger, self.reconciler = Ledger(self.store), Reconciler(self.store)
        if rows:
            EcbRates(self.store, FakeEcb(ecb_zip(history(*rows)))).refresh()
        card = self.ledger.create_account("Travel Card", "credit_card", "USD")
        with self.store.connection() as db:
            [self.charge], _ = self.ledger.insert_transactions(
                db, card, [{"posted_date": "2026-11-12", "description": "SYNTH CAFE PARIS", "amount_minor": -11200, "currency": "USD", "locator": {"rows": [1]}}],
                "import", {"document_id": self.docs["card.csv"]["id"], "blob_hash": self.docs["card.csv"]["current_hash"], "source_key": "import:card"})
        self.receipt = self.record(10000)
        if rows:
            self.reconciler.run("extraction")
            [issue] = self.open_questions()
            self.reconciler.resolve_issue(issue["id"], self.charge)
        else:
            with self.store.connection() as db:
                db.execute("INSERT INTO transaction_receipt_links(transaction_id,receipt_id,match_score,match_method,review_status,created_at,updated_at) "
                           "VALUES(?,?,60,'cross_currency+user_choice','verified','t','t')", (self.charge, self.receipt))

    def record(self, total):
        doc = self.docs["cafe.png"]
        return self.ledger.publish_receipt(
            {"merchant": "SYNTH CAFE", "purchase_date": "2026-11-12", "subtotal_minor": None, "tax_minor": None, "tip_minor": None, "total_minor": total,
             "currency": "EUR", "issues": [], "items": [], "locator": {"line_ids": ["line-1"]}},
            {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": "extraction:cafe", "run_id": "r"}, "proposed")["id"]

    def open_questions(self):
        with self.store.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM reconciliation_issues WHERE status='open'")]

    def reread(self, total):
        self.record(total)
        self.reconciler.run("extraction")

    def links(self):
        with self.store.connection() as db:
            return [tuple(row) for row in db.execute("SELECT id,transaction_id,review_status,match_method,estimate_rate_id,estimate_minor "
                                                      "FROM transaction_receipt_links WHERE receipt_id=? ORDER BY id", (self.receipt,))]

    def notes(self):
        with self.store.connection() as db:
            return [issue for issue in json.loads(db.execute("SELECT validation_json FROM receipts WHERE id=?", (self.receipt,)).fetchone()[0])
                    if issue.startswith("The match")]


@pytest.fixture
def foreign(tmp_path):
    made = Foreign(tmp_path)
    try:
        yield made
    finally:
        made.store.close()


def test_sc21d_a_foreign_receipts_link_holds_within_the_estimate_and_is_removed_outside_it(foreign):
    [link] = foreign.links()
    assert link[1:3] == (foreign.charge, "verified") and link[3].startswith("cross_currency") and link[3].endswith("user_choice")
    assert (link[4], link[5]) == ("ecb:2026-11-12:EUR", 11000)
    foreign.reread(10200)  # Estimate 112.20; 112.00 is 99.8% of it: holds.
    assert foreign.links() == [link] and foreign.notes() == []
    foreign.reread(9000)  # Estimate 99.00; 112.00 is 113% of it: removed, with the note naming the charge and the euro total.
    assert foreign.links() == []
    assert foreign.notes() == ["The match you confirmed to the $112.00 charge on 2026-11-12 was removed: this reading's total (€90.00) no longer matches it."]
    with foreign.store.connection() as db:
        assert db.execute("SELECT count(*) FROM category_splits WHERE transaction_id=?", (foreign.charge,)).fetchone()[0] == 0
        assert db.execute("SELECT review_status FROM receipts WHERE id=?", (foreign.receipt,)).fetchone()[0] == "needs_review"


def test_sc21d_the_rate_stored_on_the_link_decides_not_the_one_a_lookup_would_find_now(tmp_path):
    made = Foreign(tmp_path, rows=(("2026-11-11", "1.1000"),))  # The link is made at the 11 Nov rate, 1.10.
    try:
        [link] = made.links()
        assert link[4] == "ecb:2026-11-11:EUR"
        EcbRates(made.store, FakeEcb(ecb_zip(history(("2026-11-11", "1.1000"), ("2026-11-12", "1.2000"))))).refresh()  # A lookup now would find 1.20.
        made.reread(10200)  # At 1.10 the estimate is 112.20 and 112.00 holds; at 1.20 (122.40) it would not.
        assert made.links() == [link] and made.notes() == []
    finally:
        made.store.close()


def test_sc21d_a_stored_rate_id_that_names_no_cached_rate_means_no_rate_and_the_link_goes(foreign):
    """Cached rates are immutable (a trigger refuses any change), so a stored id always resolves in practice; the guard is for an id that never did."""
    with foreign.store.connection() as db:
        db.execute("UPDATE transaction_receipt_links SET estimate_rate_id='ecb:2026-01-01:EUR'")
    foreign.reread(10200)
    assert foreign.links() == [] and len(foreign.notes()) == 1


def test_sc21d_a_link_with_no_stored_rate_follows_the_rate_found_now(tmp_path):
    made = Foreign(tmp_path)
    try:
        with made.store.connection() as db:
            db.execute("UPDATE transaction_receipt_links SET estimate_rate_id=NULL,estimate_minor=NULL")
        made.reread(10200)  # The rate found now (1.10) decides: 112.20 holds the 112.00 charge.
        assert len(made.links()) == 1 and made.notes() == []
        made.reread(9000)  # And outside the range it goes.
        assert made.links() == [] and len(made.notes()) == 1
    finally:
        made.store.close()


def test_sc21d_a_link_with_no_stored_rate_and_no_cached_rate_is_removed_on_any_change_of_total(tmp_path):
    made = Foreign(tmp_path, rows=())
    try:
        assert len(made.links()) == 1
        made.reread(10200)
        assert made.links() == [] and len(made.notes()) == 1
    finally:
        made.store.close()


# SC-22 ------------------------------------------------------------------------------------------------------------------------------

def unchanged(manager, receipt_id, links, issues=None):
    """The link rows are exactly as they were (same id, status, score, method), no removal note stands, and (when given) the issues are the same."""
    assert link_rows(manager, receipt_id) == links and removal_notes(manager, receipt_id) == []
    if issues is not None:
        assert manager.ledger.record("receipt", receipt_id)["issues"] == issues


def case_a(tmp_path, local_model):
    """An approved receipt (B) linked to K52, read again with B0: nothing of it changes."""
    manager, ids = old_manager(tmp_path, local_model, ["B"])
    k52 = charge(manager, {"publication": {"id": ids["B"]}}, 5276)
    reconcile(manager)
    assert link_of(manager, ids["B"])[1:] == (k52, "proposed")
    before, links = table_rows(manager, ids["B"]), link_rows(manager, ids["B"])
    read_again_of(manager, local_model, ids["B"], breakfast_stub("B0")[2])
    assert table_rows(manager, ids["B"]) == before
    unchanged(manager, ids["B"], links)
    return manager


def case_b(tmp_path, local_model):
    """SC-09 after step 3, then a Try again whose summary fails validation twice: the run fails and the link, the issues and the receipt are as they were."""
    manager, ids = old_manager(tmp_path, local_model, ["C"])
    receipt_id = ids["C"]
    k52 = charge(manager, {"publication": {"id": receipt_id}}, 5276)
    reconcile(manager)
    assert link_of(manager, receipt_id)[1:] == (k52, "proposed")
    links, before = link_rows(manager, receipt_id), table_rows(manager, receipt_id)
    issues = manager.ledger.record("receipt", receipt_id)["issues"]
    with manager.store.connection() as db:
        document = db.execute("SELECT document_id FROM receipts WHERE id=?", (receipt_id,)).fetchone()[0]
    [parse] = manager.receipts.history(document)
    local_model["requests"].clear()
    local_model["by_schema"] = {"Classification": breakfast_stub("B0")[2]["Classification"], "ReceiptDiningSummary": [{"bad": "shape"}, {"bad": "shape"}]}
    failed = manager.start_extraction(document, parse["id"], True)["run_id"]
    manager.future.result(timeout=60)
    assert manager.extractions.get(failed)["status"] == "failed"
    assert table_rows(manager, receipt_id) == before
    unchanged(manager, receipt_id, links, issues)
    return manager


def case_c(tmp_path, local_model):
    """A bill linked to its payment, read again with a different total: the link is unchanged and no note is added (a bill's payment link is a later change)."""
    manager = None
    with read_bill(tmp_path, local_model, RENT, rent_replies()) as (manager, run, _record, row):
        payment = pay_and_reconcile(manager.store, manager.ledger, manager.store.documents()["items"][0])
        links = link_rows(manager, row["id"])
        assert [link[1:3] for link in links] == [(payment, "proposed")] and row["total_minor"] == 148842
        [doc] = manager.store.documents()["items"]
        parse_id = manager.receipts.history(doc["id"])[0]["id"]
        local_model["by_schema"] = rent_replies(rows=[rent_row()])  # Only the rent line: the bill's total is its lines, 1,450.00.
        again = extract(manager, doc, parse_id, True)
        assert again["status"] == "succeeded", again["error"]
        assert total_of(manager, row["id"]) == 145000  # The bill's total changed.
        unchanged(manager, row["id"], links)
        assert [issue for issue in manager.ledger.record("receipt", row["id"])["issues"] if issue.startswith("The match")] == []


def case_d(tmp_path, local_model):
    """SC-01 after step 8 (linked to K61), approved, then the kind changed to grocery with B7: the amounts stay and so does the link."""
    from test_dining_receipts import kind_change

    manager, run, _ = breakfast(tmp_path, local_model)
    receipt_id = run["publication"]["id"]
    k61 = charge(manager, run, 6155)
    reconcile(manager)
    assert link_of(manager, receipt_id)[1:] == (k61, "proposed")
    manager.ledger.review("receipt", receipt_id, "verified", "Checked.")
    links, before = link_rows(manager, receipt_id), table_rows(manager, receipt_id)
    kind_change(manager, local_model, receipt_id, "grocery", grocery_re_read_stub()[2])
    row = receipt_of(manager, run)[0]
    assert row["receipt_kind"] == "grocery" and (row["total_minor"], row["tip_minor"]) == (6155, 879)
    assert table_rows(manager, receipt_id)[0][0]["total_minor"] == before[0][0]["total_minor"]
    unchanged(manager, receipt_id, links)
    return manager


def case_e(tmp_path, local_model):
    """SC-01 after step 8, then Correct Total to 60.00: your own change, the link stays as today."""
    manager, run, _ = breakfast(tmp_path, local_model)
    receipt_id = run["publication"]["id"]
    k61 = charge(manager, run, 6155)
    reconcile(manager)
    assert link_of(manager, receipt_id)[1:] == (k61, "proposed")
    links = link_rows(manager, receipt_id)
    manager.correct_record("receipt", receipt_id, {"total": "60.00"})
    assert total_of(manager, receipt_id) == 6000
    unchanged(manager, receipt_id, links)
    return manager


def case_f(tmp_path, local_model):
    """B11 recorded (unlinked), then a fixture link to K8 that wouldn't pass D35 (8.00 is below the total), verified; Extract again with the same total."""
    manager, run, receipt_id = grocery(tmp_path, local_model)
    k8 = charge(manager, run, 800, "SYNTH MART")
    with manager.store.connection() as db:
        db.execute("INSERT INTO transaction_receipt_links(transaction_id,receipt_id,match_score,match_method,review_status,created_at,updated_at) "
                   "VALUES(?,?,60,'fixture','verified','t','t')", (k8, receipt_id))
    links = link_rows(manager, receipt_id)
    read_b11(manager, local_model, "B11")
    assert total_of(manager, receipt_id) == 1000
    unchanged(manager, receipt_id, links)
    return manager


@pytest.mark.parametrize("case", [case_a, case_b, case_c, case_d, case_e, case_f], ids=["a_approved", "b_failed", "c_bill", "d_kind_change", "e_correct_total", "f_unchanged"])
def test_sc22_what_the_rule_leaves_alone(tmp_path, local_model, case):
    manager = case(tmp_path, local_model)
    if manager is not None:  # case_c's context manager closes its own.
        try:
            assert_ledger_healthy(manager.store)
        finally:
            manager.close()
