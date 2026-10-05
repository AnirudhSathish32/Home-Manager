"""A trace for each calculation (docs/ui.md "Trace contract"; docs/open-work.md "UI redesign" 4): every traced figure's
trace re-runs the calculation that produced it, gives the same result as the figure shown, and its steps add up to it.
Synthetic data only."""

from datetime import date
import shutil
from urllib.parse import quote

from fastapi.testclient import TestClient
import pytest

from conftest import documents_by_name, inbox_scan
from home_manager.app.api import create_app
from home_manager.app.family_sync import FamilyFolder
from home_manager.app.manager import Manager
from home_manager.core.trace import Recorder
from home_manager.finance import tax_engine
from home_manager.finance.dashboard import dashboard
from home_manager.finance.engines import opentax
from home_manager.finance.fx import EcbRates
from home_manager.finance.investments import AccountInput as InvestmentAccountInput
from home_manager.finance.investments import HoldingInput, Investments, LotInput
from home_manager.finance.ledger import Ledger
from home_manager.finance.paycheck import calculate
from home_manager.finance.reconcile import Reconciler
from home_manager.finance.scenarios import ScenarioInput, Scenarios
from home_manager.finance.tax_lots import realized
from home_manager.finance.tax_tags import TaxTags
from home_manager.finance.tools import AccountInput, AsOfInput, BudgetInput, FinanceTools, PeriodInput
from home_manager.finance.traces import CONTEXT_TRACES, TRACES, shown_family_tax, trace
from home_manager.household.tax_tables import TaxTables
from home_manager.library.scanner import ScanLimits
from home_manager.library.storage import Store
from test_fx import FakeEcb
from test_investments import statement as investment_statement
from test_plan_tracking import PLAN, TOM, stub
from test_reconcile_tools import add
from test_spending_splits import costco_receipt, statement
from test_tax_family import paid
from test_tax_return import JOINT
from test_withholding import FEDERAL, confirmed

SEPTEMBER = PeriodInput(start="2026-09-01", end="2026-09-30")


@pytest.fixture
def books(tmp_path):
    store = Store(tmp_path / "managed")
    inbox_scan(store, {"export.csv": b"date,amount\n", "statement.pdf": b"synthetic statement", "costco.png": b"synthetic costco receipt",
                       "cafe.png": b"synthetic cafe receipt", "bank.pdf": b"synthetic bank statement"})
    try:
        yield store, Ledger(store), documents_by_name(store)
    finally:
        store.close()


def same(found, shown):
    """The trace is of exactly the figure shown, and its steps add up to it."""
    assert found["reconciles"], found["steps"]
    assert {key: found["result"][key] for key in ("minor", "currency")} == {key: shown[key] for key in ("minor", "currency")}
    assert shown["trace"] == found["ref"]
    return found


def test_category_spending_and_a_receipts_split_by_item_trace_to_their_shares(books):
    store, ledger, docs = books
    tools = FinanceTools(store)
    receipt_id = costco_receipt(ledger, docs["costco.png"])
    rows = {row["category"]: row["spending"] for row in tools.get_spending_by_category(SEPTEMBER)["categories"]}
    furniture = same(trace(store, rows["furniture & decor"]["trace"]), rows["furniture & decor"])
    assert furniture["result"]["minor"] == 53999 and [step["value"]["minor"] for step in furniture["steps"]] == [0, 53999]
    [line] = furniture["inputs"]
    assert (line["key"], line["value"]["minor"], line["trace"]) == (f"receipt:{receipt_id}", 53999, f"split.receipt?receipt_id={receipt_id}")
    split = trace(store, line["trace"])
    # 1.50 + 499.99 + 80.00 of items, with 40.12 of tax shared over the taxed two: rounded down, then the cents left over.
    assert split["reconciles"] and split["result"]["minor"] == 62161
    assert [(step["label"], step["value"]["minor"]) for step in split["steps"]] == [
        ("HOT DOG COMBO · dining", 162), ("QUEEN MATTRESS · furniture & decor", 53998), ("KS EGGS 24CT · groceries", 8000)]
    assert split["rounding"]["adjustment"]["minor"] == 1 and split["rounding"]["method"] == "largest_remainder"
    # Once a card charge takes the receipt over, the charge's own division is traced the same way.
    statement_id = statement(ledger, docs["statement.pdf"], [("2026-09-11", "COSTCO WHSE #1234", -62161)])
    Reconciler(store).reconcile_statement(statement_id)
    rows = {row["category"]: row["spending"] for row in tools.get_spending_by_category(SEPTEMBER)["categories"]}
    [charge] = same(trace(store, rows["dining"]["trace"]), rows["dining"])["inputs"]
    assert charge["trace"].startswith("split.charge?") and trace(store, charge["trace"])["result"]["minor"] == 62161


def test_cash_flow_budgets_recurring_bills_and_balances_trace(books):
    store, ledger, docs = books
    tools = FinanceTools(store)
    checking = ledger.create_account("First Local Bank", "checking", "USD", last_four="4821")
    add(store, ledger, checking, docs["export.csv"], [
        ("2026-09-01", "PAYROLL ACME", 300000), ("2026-09-02", "GROCER", -5000), ("2026-06-05", "CITY WATER", -4000),
        ("2026-07-05", "CITY WATER", -4000), ("2026-08-05", "CITY WATER", -4000), ("2026-09-05", "CITY WATER", -4301)])
    Reconciler(store).run()
    Reconciler(store).run()  # The bill found from the steady payments is brought up to date with the September one.
    flow = tools.calculate_cashflow(SEPTEMBER)["by_currency"][0]
    found = same(trace(store, flow["net"]["trace"]), flow["net"])
    assert [(step["op"], step["value"]["minor"], step["trace"]) for step in found["steps"]] == [
        ("+", 300000, None), ("−", 9301, flow["outflow"]["trace"])]
    assert found["inputs_page"]["total"] == 1

    with store.connection() as db:
        db.execute("UPDATE transactions SET category='groceries',category_source='user' WHERE description_raw='GROCER'")
    ledger.set_budget("Groceries", "USD", "400")
    [budget] = tools.get_budgets(BudgetInput(month="2026-09", as_of="2026-09-15"))["budgets"]
    remaining = same(trace(store, budget["remaining"]["trace"]), budget["remaining"])
    assert [(step["op"], step["value"]["minor"]) for step in remaining["steps"]] == [("+", 40000), ("−", 5000)]
    assert remaining["steps"][1]["trace"] == budget["spent"]["trace"]
    same(trace(store, budget["projected"]["trace"]), budget["projected"])
    same(trace(store, budget["spent"]["trace"]), budget["spent"])

    [water] = [row for row in tools.get_recurring_obligations()["obligations"] if row["merchant"].startswith("CITY WATER")]
    Reconciler(store).review_obligation(water["id"], "verified")
    [total] = tools.get_recurring_obligations()["totals"]
    monthly = same(trace(store, total["monthly"]["trace"]), total["monthly"])
    yearly = same(trace(store, total["yearly"]["trace"]), total["yearly"])
    assert monthly["steps"][0]["trace"] == f"bill.expected?obligation_id={water['id']}" and yearly["result"]["minor"] == total["yearly"]["minor"]
    [bill] = tools.get_upcoming_bills(AsOfInput(as_of="2026-09-01", days=60))["bills"]
    expected = same(trace(store, bill["amount_due"]["trace"]), bill["amount_due"])
    # (40.00 + 40.00 + 43.01) / 3 = 41.0033…: each third rounded down, then the rounding of the average.
    assert expected["result"]["minor"] == 4100 and [step["value"]["minor"] for step in expected["steps"]] == [1333, 1333, 1433]
    assert expected["rounding"]["adjustment"]["minor"] == 1 and expected["inputs_page"]["total"] == 3

    ledger.publish_statement({"institution": "First Local Bank", "statement_type": "bank", "last_four": "4821", "currency": "USD", "period_start": "2026-09-01",
                              "period_end": "2026-09-30", "due_date": None, "opening_balance_minor": 0, "closing_balance_minor": 295000,
                              "statement_balance_minor": None, "minimum_payment_minor": None, "summary": {}, "issues": [], "locator": {"line_ids": ["line-1"]},
                              "transactions": []},
                             {"document_id": docs["bank.pdf"]["id"], "blob_hash": docs["bank.pdf"]["current_hash"], "source_key": "extraction:bank", "run_id": "bank"},
                             "proposed")
    balance = tools.get_account_balance(AccountInput(account_id=checking["id"]))["balance"]
    found = same(trace(store, balance["trace"]), balance)
    assert found["verification"]["state"] == "unverified"  # Read by a model, and not reviewed yet.


def test_homes_category_groups_and_usd_total_trace(books):
    store, ledger, docs = books
    checking = ledger.create_account("First Local Bank", "checking", "USD", last_four="4821")
    names = ["groceries", "dining", "fuel", "health", "travel", "gifts", "education"]
    ids = add(store, ledger, checking, docs["export.csv"], [(f"2026-09-{day:02d}", name.upper(), -1000 * day) for day, name in enumerate(names, 1)])
    with store.connection() as db:
        for transaction_id, name in zip(ids, names):
            db.execute("UPDATE transactions SET category=?,category_source='user' WHERE id=?", (name, transaction_id))
    found = dashboard(store, "2026-09", today=date(2026, 9, 30))
    other = next(row for row in found["categories"] if row["category"] == "Other")
    other_trace = same(trace(store, other["spending"]["trace"]), other["spending"])
    assert [(step["label"], step["value"]["minor"]) for step in other_trace["steps"]] == [("Dining", 2000), ("Groceries", 1000)]
    gross = same(trace(store, found["gross"]["trace"]), found["gross"])
    assert len(gross["steps"]) == 7 and all(step["trace"].startswith("spending.category?") for step in gross["steps"])
    same(trace(store, found["cashflow"]["net"]["trace"]), found["cashflow"]["net"])

    EcbRates(store, FakeEcb()).refresh()
    tools = FinanceTools(store)
    with store.connection() as db:
        db.execute("UPDATE transactions SET posted_date='2025-03-14' WHERE id=?", (ids[0],))
    ledger.publish_receipt({"merchant": "OXXO", "purchase_date": "2025-03-15", "subtotal_minor": None, "tax_minor": None, "tip_minor": None,
                            "total_minor": 100_000, "currency": "MXN", "issues": [], "items": [], "locator": {"line_ids": ["line-1"]}},
                           {"document_id": docs["cafe.png"]["id"], "blob_hash": docs["cafe.png"]["current_hash"], "source_key": "extraction:oxxo", "run_id": "r"},
                           "verified")
    usd = tools.get_spending(PeriodInput(start="2025-03-01", end="2025-03-31"))["usd_total"]["net"]
    found = same(trace(store, usd["trace"]), usd)
    # 1,000.00 MXN at 1.09 USD / 21.80 MXN per euro is 50.00 USD.
    assert [step["value"]["minor"] for step in found["steps"]] == [1000, 5000] and "ECB, 2025-03-14" in found["steps"][1]["label"]


@pytest.mark.skipif(shutil.which("node") is None or date.today().year not in opentax.YEARS, reason="Node.js isn't installed, or Engine 1 isn't pinned for this year")
def test_the_return_and_tax_zen_trace_to_the_engines_lines_and_the_records(tmp_path):
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        manager, year = app.state.manager, date.today().year
        store = manager.store
        confirmed(TaxTables(store), "US", FEDERAL)
        manager.configure_household(manager.household.model_copy(update={"birth_year": 1985, "tax_engine_compare": False}))
        inbox_scan(store, {"stub1.png": b"synthetic stub one", "stub2.png": b"synthetic stub two", "export.csv": b"date,amount\n"})
        docs = documents_by_name(store)
        stub(store, docs["stub1.png"], f"{year}-01-09", 45000, 280000)
        stub(store, docs["stub2.png"], f"{year}-01-23", 47000, 278000)
        with store.connection() as db:
            db.execute("UPDATE income_records SET pay_frequency=26")
        ledger = Ledger(store)
        account = ledger.create_account("First Local Bank", "checking", "USD")
        [gift] = add(store, ledger, account, docs["export.csv"], [(f"{year}-01-05", "RED CROSS", -25000)])
        TaxTags(store).tag("transaction", gift, "itemized", "charity_cash")
        view = client.get(f"/api/tax/year/{year}").json()
        estimate = view["return"]
        assert estimate["result_minor"] is not None, estimate["notes"]
        trace_of = lambda text: client.get(f"/api/traces/{quote(text, safe='')}").json()
        result = same(trace_of(estimate["result_figure"]["trace"]), estimate["result_figure"])
        assert [step["trace"] for step in result["steps"]] == [f"tax.line?key=total_payments&year={year}", f"tax.line?key=total_tax&year={year}"]
        assert view["return"]["result_figure"]["stale"] is False
        lines = {line["key"]: line for line in estimate["lines"]}
        agi = trace_of(lines["agi"]["trace"])
        assert agi["reconciles"] and agi["steps"][0]["trace"].endswith("key=total_income&year=" + str(year))
        assert agi["result"]["minor"] == lines["agi"]["amount_minor"]
        for key in ("total_income", "taxable_income", "total_tax", "total_payments", "wages"):
            found = trace_of(lines[key]["trace"])
            assert found["reconciles"] and found["result"]["minor"] == lines[key]["amount_minor"], key
        # Wages trace to the job, and the job to its pay stubs: two stubs, then the paydays left at the latest paycheck.
        [job] = view["gathered"]["jobs"]
        wages = trace_of(job["traces"]["wages"])
        assert wages["reconciles"] and wages["result"]["minor"] == job["values"]["wages"] and wages["inputs_page"]["total"] == 2
        withheld = trace_of(job["traces"]["federal_withheld"])
        assert withheld["result"]["minor"] == job["values"]["federal_withheld"] and withheld["reconciles"]
        # The gift: a return input, from its tax tag line.
        charity = trace_of(view["gathered"]["traces"]["charity"])
        assert charity["result"]["minor"] == 25000 and charity["steps"][0]["trace"].startswith("tax.tags?")
        tags = trace_of(charity["steps"][0]["trace"])
        assert tags["reconciles"] and tags["inputs"][0]["key"] == f"transaction:{gift}"
        zen = view["zen"]
        harbor = trace_of(zen["safe_harbor"]["trace"])
        assert harbor["reconciles"] and harbor["result"]["minor"] == zen["safe_harbor"]["required_minor"] and harbor["rule"]["name"] == "Estimated tax safe harbor"
        if zen.get("advance"):
            assert trace_of(zen["advance"]["trace"])["result"]["minor"] == zen["advance"]["needed_minor"]
        if (zen.get("job") or {}).get("extra"):
            extra = trace_of(zen["job"]["extra"]["trace"])
            assert extra["reconciles"] and extra["result"]["minor"] == zen["job"]["extra"]["per_check_minor"]
        # A pay stub's estimated federal income tax, bucket by bucket.
        with store.connection() as db:
            income_id = db.execute("SELECT id FROM income_records ORDER BY id DESC LIMIT 1").fetchone()[0]
            db.execute("INSERT INTO income_lines(income_record_id,position,description,line_group,category,current_minor,locator_json) "
                       "VALUES(?,99,'Regular','earnings','regular_pay',400000,'{}')", (income_id,))
        record = manager.paystub(income_id)
        federal = next(part for part in record["withholding"]["jurisdictions"] if part["jurisdiction"] == "US")
        found = trace_of(federal["trace"])
        assert found["reconciles"] and found["result"]["minor"] == federal["estimate_minor"] and found["rule"]["name"] == "Federal tax table"
        for part in record["withholding"]["fica"]:
            found = trace_of(part["trace"])
            assert found["reconciles"] and found["result"]["minor"] == part["estimate_minor"]
        assert client.get("/api/traces/" + quote("tax.line?year=1999&key=agi", safe="")).status_code == 400
        # A saved plan's paycheck: take-home pay, line by line.
        scenario = Scenarios(store).create(ScenarioInput.model_validate(PLAN))
        paycheck = calculate(Scenarios(store).input(scenario["id"]).paychecks[0].paycheck, manager.scenario_tables()(2026, ["US", "GA"], "single"))
        found = trace_of(f"paycheck.net?index=0&scenario_id={scenario['id']}")
        assert found["reconciles"] and found["result"]["minor"] == paycheck["net"]["per_check_minor"] and found["steps"][0]["op"] == "+"

        # A 1099-INT: the interest input traces to the form's box, and every figure on the Taxes page traces and adds up,
        # Tax Zen's likely range, cushion, state advice and W-4 answers included.
        investments = Investments(store)
        inbox_scan(store, {"int.png": b"synthetic 1099-INT"})
        source = {"document_id": documents_by_name(store)["int.png"]["id"], "blob_hash": documents_by_name(store)["int.png"]["current_hash"], "run_id": "f"}
        form = investments.publish_tax_form({"institution": "Ally", "last_four": None, "tax_year": year, "currency": "USD", "issues": [],
                                             "boxes": [{"form": "1099-INT", "box": "1", "label": "Interest income", "amount_minor": 4200, "locator": {}}]}, source)
        investments.review_tax_form(form["id"], "verified")
        view = client.get(f"/api/tax/year/{year}").json()
        interest = trace_of(view["gathered"]["traces"]["interest"])
        assert interest["reconciles"] and interest["steps"][0]["label"] == "Ally 1099-INT box 1" and interest["steps"][0]["value"]["minor"] == 4200
        names = check_every_ref(trace_of, view)
        assert {"tax.result", "tax.line", "tax.field", "tax.job", "tax.safe_harbor", "taxzen.w4", "taxzen.w4_year_end"} <= names

        # The paycheck planner, What If's plans and plan against actual: every figure traces.
        planned = client.post("/api/paycheck", json=TOM).json()
        assert {"paycheck.net", "paycheck.line"} <= check_every_ref(trace_of, planned)
        compared = client.post("/api/scenarios/compare", json={"scenarios": [scenario["id"]], "include_now": True, "years": 2}).json()
        assert {"forecast.cash", "forecast.net_worth", "paycheck.net"} <= check_every_ref(trace_of, compared)
        client.post(f"/api/scenarios/{scenario['id']}/adopt", json={"month": f"{year}-08"})
        actual = client.get(f"/api/scenarios/{scenario['id']}/actual").json()
        assert "plan.actual" in check_every_ref(trace_of, actual)


@pytest.mark.skipif(shutil.which("node") is None or date.today().year not in opentax.YEARS, reason="Node.js isn't installed, or Engine 1 isn't pinned for this year")
def test_the_engines_own_steps_trace_down_to_the_return_inputs_and_the_law(tmp_path, monkeypatch):
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        manager, year = app.state.manager, date.today().year
        confirmed(TaxTables(manager.store), "US", FEDERAL)
        manager.configure_household(manager.household.model_copy(update={"birth_year": 1985, "tax_engine_compare": False}))
        view = client.put(f"/api/tax/year/{year}", json={"extra_jobs": [{"name": "Job", "wages": "94770", "federal_withheld": "12463.36"}],
                                                         "fields": {"interest": "1200"}}).json()
        trace_of = lambda text: client.get(f"/api/traces/{quote(text, safe='')}").json()
        lines = {line["key"]: line for line in view["return"]["lines"]}
        # The tax line is the engine's own step (the Tax Table), and every step below it adds up, down to the return's inputs.
        tax = trace_of(lines["tax"]["trace"])
        assert tax["reconciles"] and tax["result"]["minor"] == lines["tax"]["amount_minor"] and tax["node"]["reconciles"]
        names, cards = walk(trace_of, tax)
        assert "tax.node" in names and {"tax.field", "tax.job"} & names
        # The standard deduction is taken away: one step, the engine's rule, which rests on the law for the year.
        deduction = trace_of(lines["deduction"]["trace"])
        assert deduction["reconciles"] and deduction["steps"][0]["op"] == "−" and deduction["steps"][0]["trace"].startswith("tax.node?")
        names, cards = walk(trace_of, trace_of(deduction["steps"][0]["trace"]))
        assert any(card["tax_year"] == year and "U.S.C." in card["source"] for card in cards)
        # A step the worksheet doesn't have says so.
        assert client.get("/api/traces/" + quote(f"tax.node?key=nothing&year={year}", safe="")).status_code == 400
        # A changed engine marks the figures shown with the old one stale.
        monkeypatch.setattr(tax_engine, "pin_of", lambda slot: "another build")
        assert trace_of(lines["tax"]["trace"])["stale"] is True


def walk(trace_of, start, most=120):
    """Every trace below one, breadth first: each must add up. The ref names seen and the rule cards met."""
    names, cards, queue, seen = set(), [], [start], set()
    while queue and len(seen) < most:
        found = queue.pop(0)
        assert found["reconciles"], (found["ref"], found["steps"])
        if found.get("rule"):
            cards.append(found["rule"])
        for text in [step["trace"] for step in found["steps"]] + [item["trace"] for item in found["inputs"]]:
            if text and text not in seen:
                seen.add(text)
                names.add(text.partition("?")[0])
                queue.append(trace_of(text))
    return names, cards


def every_ref(value):
    """(ref, the figure's minor units or None) for every trace ref in a response."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "trace" and isinstance(item, str):
                yield item, value.get("minor")
            elif key == "traces" and isinstance(item, dict):
                yield from ((text, None) for text in item.values() if isinstance(text, str))
            else:
                yield from every_ref(item)
    elif isinstance(value, list):
        for item in value:
            yield from every_ref(item)


def check_every_ref(trace_of, response, most=400):
    """Every ref in a response traces, its steps add up, and its result is the figure shown; the ref names seen."""
    names, seen = set(), set()
    for text, minor in every_ref(response):
        if text in seen or len(seen) >= most:
            continue
        seen.add(text)
        found = trace_of(text)
        assert "reconciles" in found, (text, found)
        assert found["reconciles"], (text, found["steps"], found.get("rounding"))
        assert minor is None or found["result"]["minor"] == minor, (text, minor, found["result"])
        names.add(text.partition("?")[0])
    return names


def test_investments_rmds_and_the_forecast_trace(tmp_path):
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        manager, today = app.state.manager, date.today()
        store = manager.store
        manager.configure_household(manager.household.model_copy(update={"birth_year": today.year - 80}))
        investments = Investments(store)
        trace_of = lambda text: client.get(f"/api/traces/{quote(text, safe='')}").json()
        # A CD worked out from its terms: the account's value is the CD's, and the CD's is what was paid plus its interest.
        cds = investments.add(InvestmentAccountInput(name="12-month CD", kind="cd", institution="Ally", currency="USD", value="10000", as_of="2025-01-01"))
        investments.add_holding(cds["id"], HoldingInput(name="Ally 12-month CD", instrument_class="cd", principal="10000", annual_rate_percent="4.10",
                                                        issue_date=date.fromordinal(today.toordinal() - 200).isoformat(),
                                                        maturity_date=date.fromordinal(today.toordinal() + 165).isoformat()))
        account = investments.get(cds["id"])
        found = same(trace_of(account["current"]["value"]["trace"]), account["current"]["value"])
        [cd] = found["steps"]
        holding = same(trace_of(cd["trace"]), account["holdings"][0]["value"])
        assert [step["value"]["minor"] for step in holding["steps"]][0] == 1000000 and holding["steps"][1]["label"].startswith("200 days at 4.1% a year")
        # An I bond, a published rate period at a time.
        bonds = investments.add(InvestmentAccountInput(name="TreasuryDirect", kind="i_bond", currency="USD", value="0", as_of="2024-01-01"))
        investments.add_holding(bonds["id"], HoldingInput(name="I bond Jan 2024", instrument_class="i_bond", principal="10000", issue_date="2024-01-20"))
        [bond] = investments.get(bonds["id"])["holdings"]
        ibond = same(trace_of(bond["value"]["trace"]), bond["value"])
        assert ibond["steps"][0]["value"]["minor"] == 1000000 and "at 5.27% a year" in ibond["steps"][1]["label"]
        # The total of every account in a currency.
        [total] = investments.summary()["totals"]
        assert len(same(trace_of(total["total"]["trace"]), total["total"])["steps"]) == 2
        # A traditional IRA: this year's required distribution, and what's left of it.
        investments.add(InvestmentAccountInput(name="Traditional IRA", kind="ira", institution="Schwab", currency="USD", value="50000", as_of=f"{today.year - 1}-12-31"))
        [ira] = client.get("/api/investments/rmd").json()["accounts"]
        required = same(trace_of(ira["required"]["trace"]), ira["required"])
        assert required["rule"]["name"] == "Required minimum distributions" and "÷ 20.2 (age 80)" in required["steps"][0]["label"]
        same(trace_of(ira["left"]["trace"]), ira["left"])
        # A holding with its open tax lot: its value less what the lot cost.
        inbox_scan(store, {"brokerage.png": b"synthetic brokerage statement"})
        record, source = investment_statement(documents_by_name(store), "brokerage.png", f"{today.year}-01-31", 1000000)
        record["holdings"] = [{"name": "Total Stock Market Index Admiral", "identifier": "VTSAX", "instrument_class": "mutual_fund", "quantity": "80.000",
                               "value_minor": 1000000, "price_minor": 12500}]
        published = investments.publish_statement(record, source)
        with store.connection() as db:
            db.execute("UPDATE investment_valuations SET review_status='verified' WHERE account_id=?", (published["account_id"],))
            holding_id = db.execute("SELECT id FROM holdings WHERE account_id=?", (published["account_id"],)).fetchone()[0]
        investments.add_lot(holding_id, LotInput(acquired_date="2020-03-02", quantity="80", cost="6000"))
        [fund] = investments.get(published["account_id"])["holdings"]
        gain = same(trace_of(fund["lot_gain"]["trace"]), fund["lot_gain"])
        assert [step["value"]["minor"] for step in gain["steps"]] == [1000000, 600000]
        # A sale: its gain, lot by lot, as the return's long-term gain counts it.
        with store.connection() as db:
            db.execute("INSERT INTO investment_events(account_id,holding_id,event_date,event_type,amount_minor,quantity,note,review_status,created_at) "
                       "VALUES(?,?,?,'sell',300000,'20',' ','verified','t')", (published["account_id"], holding_id, f"{today.year}-02-10"))
            recorder = Recorder()
            sold = realized(db, [published["account_id"]], today.year, recorder, "long")
        assert sold["long_minor"] == 300000 - 150000 and [step["minor"] for step in recorder.steps] == [150000]
        # Today's net worth, as the family view adds it up, traces to cash, assets and loans.
        worth = trace_of("worth.today?currency=USD&figure=net_worth&history_months=3")
        assert worth["reconciles"] and [step["trace"].split("figure=")[1][:4] for step in worth["steps"]] == ["cash", "asse", "loan"]
        # The forecast's years: each year's ending cash and net worth.
        years = client.post("/api/forecast", json={"years": 2}).json()["years"]
        cash = trace_of(years[0]["traces"]["end_cash"])
        assert cash["reconciles"] and cash["result"]["minor"] == years[0]["end_cash"]
        assert cash["steps"][0]["trace"].startswith("forecast.cash?")
        worth = trace_of(years[1]["traces"]["end_net_worth"])
        assert worth["reconciles"] and worth["result"]["minor"] == years[1]["end_net_worth"]


@pytest.mark.skipif(shutil.which("node") is None or date.today().year not in opentax.YEARS, reason="Node.js isn't installed, or Engine 1 isn't pinned for this year")
def test_family_figures_trace_to_each_members_own(tmp_path):
    year = date.today().year
    manager = Manager(tmp_path / "control", ScanLimits(stability_seconds=0))
    try:
        manager.configure(str(tmp_path / "mom"))
        manager.rename_profile(manager.profile["id"], "Mom")
        mom = manager.profile["id"]
        paid(manager, "mom", 30000)
        checking = manager.ledger.create_account("First Local Bank", "checking", "USD")
        inbox_scan(manager.store, {"export.csv": b"date,amount\n"})
        add(manager.store, manager.ledger, checking, documents_by_name(manager.store)["export.csv"],
            [(f"{year}-01-03", "GROCER", -5000), (f"{year}-01-04", "PAYROLL", 200000)])
        manager.configure_household(manager.household.model_copy(update={"birth_year": 1980}))
        tables = TaxTables(manager.store)
        tables.review(tables.propose("US", year, "married_joint", JOINT, [])["id"], "verified")
        dad = manager.create_profile("Dad", str(tmp_path / "dad"))
        manager.switch_profile(dad["id"])
        paid(manager, "dad", 20000)
        manager.configure_household(manager.household.model_copy(update={"birth_year": 1955}))
        manager.switch_profile(mom)
        family = manager.create_family("The Smiths", str(tmp_path / "family"), str(tmp_path), ["Dad"], my_profile=mom)
        folder = FamilyFolder(tmp_path / "family")
        members = {member["name"]: member["member_id"] for member in folder.data["members"]}
        folder.close()
        manager.set_up_local_member(family["id"], members["Dad"], dad["id"], None)
        manager.switch_profile(family["id"])
        manager.future.result(timeout=30)
        manager.add_tax_unit("", [members["Mom"], members["Dad"]], "married_joint")
        trace_of = lambda text: trace(manager.store, text, manager)
        returns = shown_family_tax(manager.store, manager.family_tax(year))
        names = check_every_ref(trace_of, returns)
        assert {"tax.result", "tax.line", "tax.field", "tax.job", "taxzen.w4"} <= names
        [joint] = returns["returns"]
        wages = trace_of(joint["view"]["gathered"]["jobs"][0]["traces"]["wages"])
        assert wages["inputs_page"]["total"] == 1  # Worked out on that member's own copy, from their pay stub.
        home = manager.family_dashboard(f"{year}-01", 6, "USD")
        names = check_every_ref(trace_of, home)
        assert {"family.spending.net", "family.cashflow.net", "spending.net"} <= names
        spending = trace_of(home["totals"]["net_spending"]["trace"])
        assert sorted(step["label"] for step in spending["steps"]) == ["Dad", "Mom"] and "member=" in spending["steps"][0]["trace"]
        assert "family.worth.today" in check_every_ref(trace_of, manager.family_net_worth("USD"))
    finally:
        manager.close()


def test_every_traced_name_is_registered():
    assert {"spending.net", "cashflow.net", "spending.category", "spending.other", "spending.gross", "spending.usd", "split.receipt", "split.charge",
            "budget.remaining", "budget.projected", "recurring.total", "bill.expected", "account.balance", "tax.tags", "investments.value",
            "investments.total", "investments.holding", "investments.lot_gain"} <= set(TRACES)
    assert {"tax.result", "tax.line", "tax.node", "tax.field", "tax.job", "tax.safe_harbor", "taxzen.advance", "taxzen.extra", "paystub.tax",
            "paycheck.net", "investments.rmd", "investments.rmd_left", "forecast.cash", "forecast.net_worth", "taxzen.range", "taxzen.cushion",
            "taxzen.state", "taxzen.w4", "taxzen.w4_year_end", "paycheck.line", "taxzen.paycheck", "taxzen.plan", "plan.actual",
            "family.spending.net", "family.cashflow.net", "family.spending.category", "family.spending.other", "family.spending.gross",
            "family.worth.today"} <= set(CONTEXT_TRACES)
    assert "worth.today" in TRACES
    with pytest.raises(ValueError, match="only in the app"):
        trace(None, "tax.result?year=2026")
