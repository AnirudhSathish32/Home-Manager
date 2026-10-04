"""A What If plan put to use (docs/planning.md "Following a plan"): its set spending as budgets, then planned pay and spending against
what happened. Synthetic tables, stubs and transactions only."""

from datetime import date

from fastapi.testclient import TestClient
import pytest

from conftest import documents_by_name, inbox_scan
from home_manager.app.api import create_app
from home_manager.finance.ledger import Ledger
from home_manager.finance.plan_tracking import adopt, budget_changes, plan_vs_actual, stop_tracking
from home_manager.finance.scenarios import ScenarioInput, Scenarios
from home_manager.finance.tools import FinanceTools
from home_manager.household.tax_tables import TaxTables
from home_manager.library.scanner import ScanLimits
from home_manager.library.storage import Store
from test_paycheck import TOM
from test_withholding import FEDERAL, GEORGIA, confirmed

TODAY = date(2026, 9, 28)
PLAN = {"name": "Tom's new job", "basis": "profile",
        "paychecks": [{"label": "Tom", "paycheck": TOM, "from_month": "2026-08"}],
        "forecast": {"category_amounts": [{"category": "Rent", "monthly_amount": "2100", "from_month": "2026-08"},
                                          {"category": "groceries", "monthly_amount": "400", "from_month": "2026-09"}]}}
# A stub's lines this period: (group, category, amount). Tom's plan also has dental and vision, which these stubs don't print.
STUB = [("pre_tax", "retirement_pretax", 24000), ("pre_tax", "health", 10000), ("tax", "state_income_tax", 15923),
        ("tax", "social_security", 24087), ("tax", "medicare", 5633), ("post_tax", "life_insurance", 250)]


@pytest.fixture
def books(tmp_path):
    store = Store(tmp_path / "managed")
    inbox_scan(store, {name: name.encode() for name in ("jul.png", "aug.png", "sep.png", "export.csv")})
    docs = documents_by_name(store)
    ledger = Ledger(store)
    tables = TaxTables(store)
    confirmed(tables, "US", FEDERAL)
    confirmed(tables, "GA", GEORGIA)
    try:
        yield store, ledger, docs, lambda year, codes, status: tables.for_year(year, codes, status)
    finally:
        store.close()


def stub(store, doc, pay_date, federal, net):
    with store.connection() as db:
        record = db.execute("INSERT INTO income_records(document_id,blob_hash,pay_date,gross_pay_minor,net_pay_minor,currency,review_status,created_at,updated_at) "
                            "VALUES(?,?,?,400000,?,'USD','verified','t','t')", (doc["id"], doc["current_hash"], pay_date, net)).lastrowid
        lines = [*STUB, ("tax", "federal_income_tax", federal)]
        db.executemany("INSERT INTO income_lines(income_record_id,position,description,line_group,category,current_minor,locator_json) VALUES(?,?,?,?,?,?,'{}')",
                       [(record, position, category, group, category, amount) for position, (group, category, amount) in enumerate(lines, 1)])


def spend(store, ledger, doc, rows):
    account = ledger.create_account("First Local Bank", "checking", "USD")
    ledger.add_rule("landlord", "rent")
    ledger.add_rule("grocer", "groceries")
    source = {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": "import:test"}
    with store.connection() as db:
        ledger.insert_transactions(db, account, [{"posted_date": day, "description": text, "amount_minor": amount, "currency": "USD", "locator": {"rows": [index]}}
                                                 for index, (day, text, amount) in enumerate(rows, 1)], "import", source)


def test_a_plans_set_spending_becomes_budgets(books):
    store, ledger, _, _ = books
    scenario = Scenarios(store).create(ScenarioInput.model_validate(PLAN))
    ledger.set_budget("groceries", "USD", "500")
    ledger.set_budget("dining", "USD", "100")
    changes = budget_changes(Scenarios(store).input(scenario["id"]), "2026-09", "USD", ledger.budgets())
    # Categories compare the way budgets do: "Rent" is rent.
    assert [(row["category"], row["planned"]["display"], row["current"]["display"] if row["current"] else None, row["change"]) for row in changes["rows"]] == [
        ("groceries", "400.00 USD", "500.00 USD", "changed"), ("rent", "2,100.00 USD", None, "new")]
    assert [row["category"] for row in changes["untouched"]] == ["dining"]
    # In August only rent was set.
    assert [row["category"] for row in budget_changes(Scenarios(store).input(scenario["id"]), "2026-08", "USD", [])["rows"]] == ["rent"]
    result = adopt(store, ledger, scenario["id"], "2026-09", "USD")
    assert result["applied"] == 2 and result["scenario"]["adopted_month"] == "2026-09" and result["scenario"]["adopted_at"]
    assert {budget["category"]: budget["amount"]["display"] for budget in ledger.budgets()} == {
        "dining": "100.00 USD", "groceries": "400.00 USD", "rent": "2,100.00 USD"}
    assert adopt(store, ledger, scenario["id"], "2026-09", "USD")["applied"] == 0  # Nothing left to change.
    stopped = stop_tracking(store, scenario["id"])
    assert stopped["adopted_at"] is None and len(ledger.budgets()) == 3  # Its budgets stay.


def test_planned_pay_line_by_line_against_the_stubs(books):
    store, ledger, docs, tables_for = books
    scenario = Scenarios(store).create(ScenarioInput.model_validate(PLAN))
    stub(store, docs["jul.png"], "2026-07-31", 99999, 1)  # Before the plan: not compared.
    stub(store, docs["aug.png"], "2026-08-14", 45000, 280000)
    stub(store, docs["sep.png"], "2026-09-11", 47000, 278000)
    result = plan_vs_actual(store, FinanceTools(store), Scenarios(store).get(scenario["id"]), tables_for, "USD", TODAY)
    [pay] = result["pay"]
    assert [stub["pay_date"] for stub in pay["stubs"]] == ["2026-09-11", "2026-08-14"]
    rows = {row["label"]: row for row in pay["rows"]}
    view = lambda label: tuple(rows[label][key]["display"] if rows[label][key] else None for key in ("planned", "latest", "average", "difference"))
    # Federal: planned 479.36; the stubs withheld 470.00 and 450.00, 460.00 on average, 19.36 less than planned.
    assert view("Federal income tax") == ("479.36 USD", "470.00 USD", "460.00 USD", "-19.36 USD")
    assert view("Gross pay") == ("4,000.00 USD", "4,000.00 USD", "4,000.00 USD", "0.00 USD")
    assert view("Dental insurance") == ("10.00 USD", "0.00 USD", "0.00 USD", "-10.00 USD")  # Planned, not on the stubs.
    assert view("Net pay") == ("2,706.71 USD", "2,780.00 USD", "2,790.00 USD", "83.29 USD")
    assert pay["rows"][0]["label"] == "Gross pay" and pay["rows"][-1]["label"] == "Net pay"


def test_set_spending_against_counted_spending_by_month(books):
    store, ledger, docs, tables_for = books
    scenario = Scenarios(store).create(ScenarioInput.model_validate(PLAN))
    spend(store, ledger, docs["export.csv"], [("2026-08-01", "LANDLORD", -200000), ("2026-09-01", "LANDLORD", -210000),
                                              ("2026-09-05", "GROCER", -30000), ("2026-09-20", "GROCER", -15000)])
    result = plan_vs_actual(store, FinanceTools(store), Scenarios(store).get(scenario["id"]), tables_for, "USD", TODAY)
    # Not adopted: from the first set spending month. Newest month first; this month is so far.
    assert [(month["month"], month["partial"]) for month in result["spending"]] == [("2026-09", True), ("2026-08", False)]
    september = {row["category"]: row for row in result["spending"][0]["rows"]}
    assert (september["groceries"]["actual"]["display"], september["groceries"]["difference"]["display"], september["groceries"]["status"]) == (
        "450.00 USD", "50.00 USD", "over")
    assert (september["rent"]["status"], result["spending"][1]["rows"][0]["actual"]["display"]) == ("within", "2,000.00 USD")
    assert result["pay"][0]["message"].startswith("No confirmed pay stubs paid from 2026-08")
    # Adopted in September: August is no longer compared.
    adopt(store, ledger, scenario["id"], "2026-09", "USD")
    later = plan_vs_actual(store, FinanceTools(store), Scenarios(store).get(scenario["id"]), tables_for, "USD", TODAY)
    assert [month["month"] for month in later["spending"]] == ["2026-09"]


def test_plan_tracking_endpoints(tmp_path):
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        created = client.post("/api/scenarios", json=PLAN).json()
        preview = client.get(f"/api/scenarios/{created['id']}/budgets", params={"month": "2026-09"}).json()
        assert [row["change"] for row in preview["rows"]] == ["new", "new"]
        assert client.get(f"/api/scenarios/{created['id']}/budgets", params={"month": "2026-13"}).status_code == 422
        adopted = client.post(f"/api/scenarios/{created['id']}/adopt", json={"month": "2026-09"}).json()
        assert adopted["applied"] == 2 and adopted["scenario"]["adopted_month"] == "2026-09"
        assert client.get(f"/api/scenarios/{created['id']}/actual").json()["adopted_month"] == "2026-09"
        assert client.post(f"/api/scenarios/{created['id']}/stop").json()["adopted_month"] is None
        assert client.post("/api/scenarios/99/adopt", json={"month": "2026-09"}).status_code == 400
