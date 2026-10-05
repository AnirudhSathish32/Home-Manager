"""The trace and provenance backbone (docs/ui.md "Redesign: calculation observability"; docs/open-work.md "UI redesign" 3):
who changed what and why, corrections of statements, account values and tax form boxes, typed tax values beside the
records', rule sets, provenance, verification, traces and manual transactions. Synthetic data only."""

from fastapi.testclient import TestClient
import pytest

from conftest import documents_by_name, inbox_scan
from home_manager.app.api import create_app
from home_manager.core import actor
from home_manager.core.trace import Recorder, build, verification_of
from home_manager.finance import rules
from home_manager.finance.investments import Investments
from home_manager.finance.ledger import Ledger
from home_manager.finance.provenance import page_of, provenance_for
from home_manager.finance.reconcile import Reconciler
from home_manager.finance.tax_tags import TaxTags
from home_manager.finance.tax_year import TaxYears, typed_changes
from home_manager.finance.tools import FinanceTools, PeriodInput
from home_manager.finance.traces import shown, trace
from home_manager.library.scanner import ScanLimits
from home_manager.library.storage import Store
from test_investments import statement as investment_statement
from test_reconcile_tools import add, receipt, source_of


@pytest.fixture
def books(tmp_path):
    store = Store(tmp_path / "managed")
    inbox_scan(store, {"export.csv": b"date,amount\n", "receipt.png": b"synthetic receipt bytes", "statement.png": b"synthetic statement",
                       "august.png": b"august statement", "form.png": b"synthetic 1099"})
    try:
        yield store, Ledger(store), documents_by_name(store)
    finally:
        store.close()


def bank_statement(closing_minor):
    return {"institution": "First Local Bank", "statement_type": "bank", "last_four": "4821", "currency": "USD", "period_start": "2026-09-01",
            "period_end": "2026-09-30", "due_date": None, "opening_balance_minor": 100000, "closing_balance_minor": closing_minor,
            "statement_balance_minor": None, "minimum_payment_minor": None, "summary": {}, "issues": [], "locator": {"line_ids": ["line-1"]}, "transactions": []}


def test_the_actor_is_one_of_the_profiles_people_or_nobody():
    assert actor.checked("", ["Sam"]) is None and actor.checked(None, ["Sam"]) is None
    assert actor.checked("  sam ", ["Sam", "Alex"]) == "Sam"  # As listed, whatever the case and spacing.
    with pytest.raises(ValueError, match="isn't one of this profile's people"):
        actor.checked("Mallory", ["Sam"])
    assert actor.current() is None
    with actor.acting_as("Sam"):
        assert actor.current() == "Sam"
    assert actor.current() is None


def test_corrections_keep_who_why_and_the_value_they_replaced(books):
    store, ledger, docs = books
    published = ledger.publish_statement(bank_statement(150000), source_of(docs["statement.png"], "extraction:statement"), "proposed")
    with actor.acting_as("Sam"):
        record = ledger.correct("statement", published["id"], {"closing_balance": "1,525.10"}, reason="The model read 1,500.00; the PDF says 1,525.10.")
    assert record["closing_balance_minor"] == 152510
    [correction] = record["corrections"]
    assert (correction["field"], correction["previous"], correction["value"], correction["actor"]) == ("closing_balance", "1500.00", "1525.10", "Sam")
    assert correction["reason"].startswith("The model read")
    # A new reading of the same statement keeps the person's value.
    ledger.publish_statement(bank_statement(150000), source_of(docs["statement.png"], "extraction:statement-again"), "proposed")
    assert ledger.record("statement", published["id"])["closing_balance_minor"] == 152510
    with pytest.raises(ValueError, match="500 characters"):
        ledger.correct("statement", published["id"], {"closing_balance": "1"}, reason="x" * 501)
    # Review decisions carry the person too.
    with actor.acting_as("Sam"):
        ledger.review("statement", published["id"], "verified")
    assert ledger.review_history("statement", published["id"])[-1]["actor"] == "Sam"


def test_account_values_and_tax_form_boxes_can_be_corrected_and_stay_corrected(books):
    store, _, docs = books
    investments = Investments(store)
    august = investments.publish_statement(*investment_statement(docs, "august.png", "2026-08-31", 100000))
    with actor.acting_as("Sam"):
        investments.correct_valuation(august["id"], "1,010.00", "Statement page 2 shows 1,010.00")
    assert investments.publish_statement(*investment_statement(docs, "august.png", "2026-08-31", 100000))["status"] == "published"
    with store.connection() as db:
        assert db.execute("SELECT value_minor FROM investment_valuations WHERE id=?", (august["id"],)).fetchone()[0] == 101000
        found = provenance_for(db, "investment_valuation", august["id"], "value")
    assert found["provenance"]["kind"] == "override" and found["provenance"]["override"]["original"] == "1000.00"
    assert found["provenance"]["override"]["actor"]["person"] == "Sam" and found["verification"] == "needs_review"
    record = {"institution": "Vanguard", "last_four": None, "tax_year": 2025, "currency": "USD", "issues": [],
              "boxes": [{"form": "1099-INT", "box": "1", "label": "Interest income", "amount_minor": 4200, "locator": {}}]}
    source = {"document_id": docs["form.png"]["id"], "blob_hash": docs["form.png"]["current_hash"], "run_id": "form"}
    form = investments.publish_tax_form(record, source)
    corrected = investments.correct_tax_form_box(form["id"], "1099-INT", "1", "42.50", "Box 1 is 42.50")
    assert corrected["boxes"][0]["amount_minor"] == 4250
    investments.publish_tax_form(record, source)  # Read again: the boxes are written again, the correction outlives it.
    assert investments.tax_form(form["id"])["boxes"][0]["amount_minor"] == 4250
    with pytest.raises(ValueError, match="isn't on this tax form"):
        investments.correct_tax_form_box(form["id"], "1099-DIV", "1a", "1", None)


def test_budget_history_and_child_row_timestamps(books):
    store, ledger, docs = books
    with actor.acting_as("Sam"):
        ledger.set_budget("Groceries", "USD", "400")
        ledger.set_budget("Groceries", "USD", "400")  # The same amount again is not a change.
        budget = ledger.set_budget("Groceries", "USD", "450")
    ledger.delete_budget(budget["id"])
    history = ledger.budget_history("groceries", "usd")
    assert [(row["previous"] and row["previous"]["display"], row["amount"] and row["amount"]["display"], row["actor"]) for row in history] == [
        ("450.00 USD", None, None), ("400.00 USD", "450.00 USD", "Sam"), (None, "400.00 USD", "Sam")]
    receipt_id = ledger.publish_receipt({"merchant": "Corner Market", "purchase_date": "2026-09-10", "subtotal_minor": None, "tax_minor": None, "tip_minor": None,
                                         "total_minor": 500, "currency": "USD", "issues": [], "locator": {"line_ids": ["line-1"]},
                                         "items": [{"description": "MILK", "product_code": None, "quantity": "1", "unit_price_minor": 500, "line_total_minor": 500,
                                                    "discount_minor": None, "locator": {"line_ids": ["line-2"]}}]},
                                        source_of(docs["receipt.png"], "extraction:receipt"), "proposed")["id"]
    with store.connection() as db:
        created, updated = db.execute("SELECT created_at,updated_at FROM receipt_items WHERE receipt_id=?", (receipt_id,)).fetchone()
    assert created and updated


def test_typed_tax_values_are_kept_beside_the_records_values(books):
    store, _, _ = books
    years = TaxYears(store)
    gathered = {"values": {"interest": 12000}, "jobs": [{"key": "employer-1", "values": {"wages": 9000000}}]}
    with actor.acting_as("Sam"):
        years.save(2026, {"fields": {"interest": "150"}, "jobs": {"employer-1": {"wages": "91000"}}, "reason": "The 1099 came in"}, gathered=gathered)
    years.save(2026, {"fields": {"interest": ""}, "jobs": {"employer-1": {"wages": "91000"}}}, gathered=gathered)
    assert "reason" not in years.inputs(2026)  # Kept with the change, not with the values.
    changes = years.changes(2026)
    assert [(row["key"], row["gathered"], row["previous"], row["typed"], row["actor"], row["reason"]) for row in changes] == [
        ("interest", 12000, "150", None, None, None),
        ("job:employer-1:wages", 9000000, None, "91000", "Sam", "The 1099 came in"), ("interest", 12000, None, "150", "Sam", "The 1099 came in")]
    assert typed_changes({"fields": {"interest": "1"}}, {"fields": {"interest": "1"}}) == []


def test_rule_sets_are_versioned_and_their_values_are_pinned(books):
    store, _, _ = books
    for key, entry in rules.RULES.items():
        # A value changed without a new version fails here: bump the version and record the new digest.
        assert rules.digest(entry["values"]()) == entry["values_sha256"], key
    card = rules.rule("rmd_uniform_lifetime")
    assert (card["checked_on"], card["cpa_reviewed_on"], card["values"]["divisors"]["73"]) == ("2026-09-28", None, "26.5")
    found = {row["key"]: row for row in rules.sources(store)}
    assert set(found) == set(rules.RULES) and found["safe_harbor"]["version"] == "2026-1"


def test_verification_has_three_states_and_only_needs_review_flags_a_total():
    def inputs(*states):
        return [{"key": f"x:{n}", "value": {"minor": 100, "currency": "USD"}, "verification": state} for n, state in enumerate(states)]
    assert verification_of(inputs("confirmed", "checked_automatically"))["state"] == "verified"
    partial = verification_of(inputs("confirmed", "needs_review"))
    assert (partial["state"], partial["unverified_count"], partial["unverified_value"]["minor"], partial["first"]) == ("partial", 1, 100, "x:1")
    assert verification_of(inputs("needs_review"))["state"] == "unverified"
    assert page_of("page-3-line-12") == 3 and page_of("line-4") == 1


def test_net_spending_traces_to_the_lines_it_counted_and_says_when_they_changed(books):
    store, ledger, docs = books
    checking = ledger.create_account("First Local Bank", "checking", "USD", last_four="4821")
    add(store, ledger, checking, docs["export.csv"], [("2026-09-02", "GROCER", -5000), ("2026-09-03", "REFUND GROCER", 1000), ("2026-09-04", "BOOKSHOP", -2500)])
    with store.connection() as db:
        db.execute("UPDATE transactions SET transaction_type='refund' WHERE description_raw='REFUND GROCER'")
    receipt_id = receipt(ledger, docs["receipt.png"], "Corner Market", "2026-09-05", 1200)
    ledger.review("receipt", receipt_id, "verified")
    shown = FinanceTools(store).get_spending(PeriodInput(start="2026-09-01", end="2026-09-30"))["by_currency"][0]["net_spending"]
    found = trace(store, shown["trace"])
    # 50.00 + 25.00 of charges, plus a 12.00 receipt no charge replaced, less a 10.00 refund: 77.00, and the steps add up to it.
    assert found["result"] == {key: shown[key] for key in ("minor", "currency", "decimal", "display")} and found["result"]["minor"] == 7700
    assert found["reconciles"] and [(step["label"], step["op"], step["value"]["minor"]) for step in found["steps"]] == [
        ("Card and bank charges", "+", 7500), ("Receipts no card or bank charge has replaced", "+", 1200), ("Refunds", "−", 1000)]
    assert found["inputs_page"]["total"] == 4 and found["verification"]["state"] == "verified" and not found["stale"]
    kinds = {item["key"].split(":")[0]: item["provenance"]["kind"] for item in found["inputs"]}
    assert kinds == {"transaction": "imported", "receipt": "extracted"}
    add(store, ledger, checking, docs["export.csv"], [("2026-09-06", "CAFE", -400)])
    again = trace(store, shown["trace"])
    assert again["stale"] and again["result"]["minor"] == 8100 and again["reconciles"]
    with pytest.raises(ValueError, match="can't be traced yet"):
        trace(store, "forecast.month?month=2026-10")


def test_a_trace_that_does_not_add_up_says_so():
    recorder = Recorder()
    recorder.step("A", "+", 500, "USD")
    recorder.step("B", "−", 100, "USD")
    assert build("x", "X", 400, "USD", "", recorder)["reconciles"]
    assert not build("x", "X", 401, "USD", "", recorder)["reconciles"]
    recorder.round(1, "USD", note="A cent of rounding")
    assert build("x", "X", 401, "USD", "", recorder)["reconciles"]


def test_a_manual_transaction_counts_at_once_until_its_statement_line_replaces_it(books):
    store, ledger, docs = books
    checking = ledger.create_account("First Local Bank", "checking", "USD", last_four="4821")
    with actor.acting_as("Sam"):
        manual = ledger.add_manual_transaction(checking["id"], "2026-09-10", "Farmers market", "23.40", "out", "groceries")
    assert (manual["origin"], manual["amount_minor"], manual["review_status"], manual["actor"]) == ("manual", -2340, "verified", "Sam")
    spending = lambda: FinanceTools(store).get_spending(PeriodInput(start="2026-09-01", end="2026-09-30"))["by_currency"][0]["net_spending"]["minor"]
    assert spending() == 2340
    with store.connection() as db:
        assert provenance_for(db, "transaction", manual["id"])["provenance"]["actor"]["person"] == "Sam"
    reconciler = Reconciler(store)
    [line] = add(store, ledger, checking, docs["export.csv"], [("2026-09-12", "FARMERS MKT 0912", -2340)])
    assert reconciler.run()["manual_replaced"] == 1
    assert spending() == 2340  # Counted once: the statement line now, not both.
    replaced = ledger.record("transaction", manual["id"])
    assert (replaced["review_status"], replaced["replaced_by"]) == ("rejected", line)
    assert ledger.record("transaction", line)["category"] == "groceries"  # The person's category moved across.
    # Two lines that could be the same payment: nothing is replaced by a guess.
    second = ledger.add_manual_transaction(checking["id"], "2026-09-20", "Hardware", "10", "out")
    add(store, ledger, checking, docs["export.csv"], [("2026-09-20", "HARDWARE A", -1000), ("2026-09-21", "HARDWARE B", -1000)])
    assert reconciler.run()["manual_replaced"] == 0 and ledger.record("transaction", second["id"])["review_status"] == "verified"
    with pytest.raises(ValueError, match="above zero"):
        ledger.add_manual_transaction(checking["id"], "2026-09-20", "Hardware", "-5", "out")


def test_a_manual_transactions_tax_tag_moves_to_the_line_that_replaces_it(books):
    store, ledger, docs = books
    checking = ledger.create_account("First Local Bank", "checking", "USD", last_four="4821")
    manual = ledger.add_manual_transaction(checking["id"], "2026-09-10", "Food bank gift", "50", "out")
    tag = TaxTags(store).tag("transaction", manual["id"], "itemized", "charity_cash")
    [line] = add(store, ledger, checking, docs["export.csv"], [("2026-09-11", "FOOD BANK", -5000)])
    assert Reconciler(store).run()["manual_replaced"] == 1
    moved = TaxTags(store).get(tag["id"])
    assert (moved["transaction_id"], moved["tax_date"]) == (line, "2026-09-11")


def test_transactions_can_be_corrected_and_the_correction_outlives_a_new_reading(books):
    store, ledger, docs = books
    statement = {**bank_statement(150000), "transactions": [
        {"posted_date": "2026-09-04", "description": "BOOKSHOP", "amount_minor": -2500, "currency": "USD", "locator": {"line_ids": ["line-4"]}}]}
    published = ledger.publish_statement(statement, source_of(docs["statement.png"], "extraction:statement"), "proposed")
    [row] = ledger.record("statement", published["id"])["transactions"]
    with actor.acting_as("Sam"):
        record = ledger.correct_transaction(row["id"], {"amount": "25.50", "merchant": "Corner Books", "transaction_type": "fee"}, reason="Printed 25.50")
    assert (record["amount_minor"], record["merchant"], record["transaction_type"]) == (-2550, "Corner Books", "fee")
    assert {(item["field"], item["previous"], item["value"], item["actor"]) for item in record["corrections"]} == {
        ("amount", "25.00", "25.50", "Sam"), ("merchant", "BOOKSHOP", "Corner Books", "Sam"), ("transaction_type", "purchase", "fee", "Sam")}
    ledger.publish_statement(statement, source_of(docs["statement.png"], "extraction:statement-again"), "proposed")
    again = ledger.record("transaction", row["id"])
    assert (again["amount_minor"], again["transaction_type"]) == (-2550, "fee")
    ledger.correct_transaction(row["id"], {"direction": "in"})
    assert ledger.record("transaction", row["id"])["amount_minor"] == 2550
    ledger.set_category(row["id"], "Books")  # A category the person sets is kept as a correction too.
    with store.connection() as db:
        found = provenance_for(db, "transaction", row["id"], "category")
    assert (found["provenance"]["kind"], found["provenance"]["override"]["value"]) == ("override", "books")
    with pytest.raises(ValueError, match="positive"):
        ledger.correct_transaction(row["id"], {"amount": "-3"})
    with pytest.raises(ValueError, match="Choose fields"):
        ledger.correct_transaction(row["id"], {"account": "x"})


def test_holdings_can_be_corrected_and_stay_corrected(books):
    store, _, docs = books
    investments = Investments(store)
    holding = {"instrument_class": "cd", "name": "12-month CD", "identifier": None, "rate_bp": 450, "maturity_date": "2027-08-31", "value_minor": 50000}
    investments.publish_statement(*investment_statement(docs, "august.png", "2026-08-31", 50000, holdings=[holding]))
    with store.connection() as db:
        holding_id = db.execute("SELECT id FROM holdings").fetchone()[0]
    with actor.acting_as("Sam"):
        investments.correct_holding(holding_id, "rate", "4.75", reason="The CD letter says 4.75%")
        investments.correct_holding(holding_id, "value", "505.00", as_of="2026-08-31")
    investments.publish_statement(*investment_statement(docs, "august.png", "2026-08-31", 50000, holdings=[holding]))  # Read again.
    with store.connection() as db:
        assert db.execute("SELECT rate_bp FROM holdings WHERE id=?", (holding_id,)).fetchone()[0] == 475
        assert db.execute("SELECT value_minor FROM investment_valuations WHERE holding_id=?", (holding_id,)).fetchone()[0] == 50500
        found = provenance_for(db, "holding", holding_id, "rate")
    assert (found["provenance"]["kind"], found["provenance"]["override"]["original"], found["provenance"]["override"]["actor"]["person"]) == ("override", "4.5", "Sam")
    with pytest.raises(ValueError, match="No statement value"):
        investments.correct_holding(holding_id, "value", "1", as_of="2026-07-31")


def test_the_spouse_on_the_return_is_one_of_the_people(tmp_path):
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        manager = app.state.manager
        manager.configure(str(tmp_path / "mine"))  # Sets up the first profile.
        assert len(manager.people()) == 1
        TaxYears(manager.store).save(2026, {"people": [{"name": " Alex  Rivera ", "birth_year": 1990}]})
        assert manager.people()[1:] == ["Alex Rivera"]
        assert client.get("/api/settings", headers={"X-HM-Actor": "Alex Rivera"}).status_code == 200


def test_home_remembers_the_figures_it_shows(books):
    store, ledger, docs = books
    checking = ledger.create_account("First Local Bank", "checking", "USD", last_four="4821")
    add(store, ledger, checking, docs["export.csv"], [("2026-09-02", "GROCER", -5000)])
    first = shown(store, [FinanceTools(store).get_spending(PeriodInput(start="2026-09-01", end="2026-09-30"))["by_currency"][0]["net_spending"]])
    assert first[0]["stale"] is False
    add(store, ledger, checking, docs["export.csv"], [("2026-09-03", "CAFE", -400)])
    # Changed since it was last shown, without anyone opening its breakdown in between.
    assert trace(store, first[0]["trace"])["stale"]


def test_the_api_checks_who_is_here_and_serves_traces_provenance_and_rules(tmp_path):
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        people = client.get("/api/settings").json()["people"]
        assert client.get("/api/settings", headers={"X-HM-Actor": "Mallory"}).status_code == 400
        manager = app.state.manager
        account = manager.ledger.create_account("First Local Bank", "checking", "USD")
        # One person (or none yet) needs no choice: the server records them without the header.
        added = client.post("/api/finance/transactions", json={"account_id": account["id"], "date": "2026-09-10", "description": "Cash at the fair",
                                                              "amount": "12.00"})
        assert added.status_code == 201 and added.json()["record"]["actor"] == (people[0] if len(people) == 1 else None)
        spending = client.post("/api/finance/tools/get_spending", json={"start": "2026-09-01", "end": "2026-09-30"}).json()
        ref = spending["by_currency"][0]["net_spending"]["trace"]
        from urllib.parse import quote
        found = client.get(f"/api/traces/{quote(ref, safe='')}").json()
        assert found["result"]["minor"] == 1200 and found["reconciles"]
        provenance = client.get(f"/api/provenance/transaction/{added.json()['record']['id']}").json()
        assert provenance["provenance"]["kind"] == "manual" and provenance["verification"] == "confirmed"
        assert {row["key"] for row in client.get("/api/rule-sources").json()} == set(rules.RULES)
        assert client.get("/api/finance/budgets/history", params={"category": "groceries", "currency": "USD"}).json() == []
