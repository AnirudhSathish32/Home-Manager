"""What If scenarios (docs/what-if.md): planned paychecks and set spending in the forecast, saved plans, the three bases and
the comparison. Synthetic tables and records only."""

from decimal import Decimal

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from home_manager.app.api import create_app
from home_manager.finance.forecast import AssetInput, Assets, CategoryAmount, ForecastInput, PayPlan, RetirementPlan, project
from home_manager.finance.scenarios import ScenarioInput, Scenarios, compare, empty_baseline, family_baseline, paycheck_plans, run
from home_manager.household.tax_tables import TaxTables
from home_manager.library.scanner import ScanLimits
from home_manager.library.storage import Store
from test_forecast import TODAY, base
from test_paycheck import TOM
from test_withholding import FEDERAL, GEORGIA, confirmed

FLAT = {"inflation_percent": "0", "years": 1}


def month(result, name):
    return next(row for row in result["months"] if row["month"] == name)


def pay_plan(**changes):
    return PayPlan.model_validate({"label": "Tom", "from_month": "2026-12", "mode": "replace_pay", "monthly_net": "4000", **changes})


def test_a_planned_paycheck_replaces_the_stubs_pay_while_it_runs():
    result = project(base(monthly_pay=Decimal(250000)), ForecastInput(**FLAT, pay_plans=[pay_plan(to_month="2027-02")]), TODAY)
    # Recorded income 3,000 a month includes 2,500 of stub pay; from December the plan's 4,000 takes its place.
    assert [month(result, name)["income"] for name in ("2026-11", "2026-12", "2027-02", "2027-03")] == [300000, 450000, 450000, 300000]
    assert any("Tom: 4,000.00 USD a month of take-home pay from 2026-12 to 2027-02, replacing" in note for note in result["notes"])
    assert result["assumptions"]["pay_plans"][0]["label"] == "Tom"


def test_an_added_earner_and_retirement_stopping_planned_pay():
    plan = pay_plan(mode="add", monthly_net="1000")
    retire = RetirementPlan(start_month="2027-03", mode="fixed", monthly_amount="0.01")
    result = project(base(monthly_pay=Decimal(250000)), ForecastInput(**FLAT, pay_plans=[plan], retirement=retire), TODAY)
    assert [month(result, name)["income"] for name in ("2026-11", "2026-12", "2027-03")] == [300000, 400000, 50000]
    # Without stubs there is nothing to replace; the note says the recorded income keeps its pay.
    alone = project(base(), ForecastInput(**FLAT, pay_plans=[pay_plan()]), TODAY)
    assert month(alone, "2026-12")["income"] == 700000 and any("no confirmed pay stubs to replace" in note for note in alone["notes"])


def test_set_category_amounts_replace_averages_and_bills():
    bill = {"name": "Old rent", "category": "rent", "amount_minor": 180000, "frequency": "monthly", "next_due": "2026-10-01"}
    amounts = [CategoryAmount(category="rent", monthly_amount="2100", from_month="2026-11"),
               CategoryAmount(category="groceries", monthly_amount="1500", from_month="2027-01")]
    result = project(base(bills=[bill]), ForecastInput(**FLAT, category_amounts=amounts), TODAY)
    # October: 2,000 groceries + 1,800 old rent; November: the new rent replaces the bill; January: groceries set too.
    assert [month(result, name)["spending"] for name in ("2026-10", "2026-11", "2027-01")] == [380000, 410000, 360000]
    # Set amounts are in today's money and rise with inflation like any spending.
    inflated = project(base(), ForecastInput(years=1, category_amounts=amounts[:1]), TODAY)
    assert month(inflated, "2026-11")["spending"] > 200000 + 210000


def investment(account_id, payroll, name="401(k)", tax="tax_deferred"):
    return {"name": name, "kind": "401k", "kind_label": "401(k)", "value_minor": 1000000, "annual_rate_bp": 0, "monthly_payment_minor": None,
            "value": {}, "annual_rate_percent": "0", "monthly_payment": None, "currency": "USD", "source": "investment", "terms": [],
            "tax_treatment": tax, "payroll_monthly_minor": payroll, "personal_monthly_minor": 0, "account_id": account_id}


def test_planned_contributions_go_to_the_linked_account_or_a_new_planned_one():
    plan = pay_plan(monthly_retirement="800", monthly_hsa="200", retirement_account_id=7)
    result = project(base(monthly_pay=Decimal(250000), assets=[investment(7, 50000)]), ForecastInput(**FLAT, pay_plans=[plan]), TODAY)
    # Before the plan the stubs pay in 500 a month; while it runs the plan's 800 replaces them, and 200 starts a planned HSA.
    assert [month(result, name)["contributions"] for name in ("2026-11", "2026-12")] == [50000, 100000]
    assert month(result, "2026-12")["assets"] == 1000000 + 50000 * 2 + 80000 + 20000
    # An added earner's contributions add to the stubs'.
    added = project(base(assets=[investment(7, 50000)]), ForecastInput(**FLAT, pay_plans=[pay_plan(mode="add", monthly_retirement="800", retirement_account_id=7)]), TODAY)
    assert month(added, "2026-12")["contributions"] == 130000


@pytest.fixture
def tables(tmp_path):
    store = Store(tmp_path / "managed")
    try:
        service = TaxTables(store)
        confirmed(service, "US", FEDERAL)
        confirmed(service, "GA", GEORGIA)
        yield store, lambda year, codes, status: service.for_year(year, codes, status)
    finally:
        store.close()


def tom_scenario(**changes):
    value = {"name": "Tom moves", "basis": "blank", "starting_cash": "5000",
             "paychecks": [{"label": "Tom", "paycheck": TOM, "from_month": "2026-10"}],
             "forecast": {**FLAT, "category_amounts": [{"category": "rent", "monthly_amount": "2100", "from_month": "2026-10"}]}}
    return ScenarioInput.model_validate({**value, **changes})


def test_paychecks_are_worked_out_into_monthly_pay_and_contributions(tables):
    _, tables_for = tables
    [plan], [summary] = paycheck_plans(tom_scenario(), tables_for)
    # 2,706.71 × 26 = 70,374.46 a year = 5,864.54 a month; 400.00 a paycheck to the 401(k) (6% + the match) = 866.67 a month.
    assert (plan.monthly_net, plan.monthly_retirement, plan.monthly_hsa) == ("5864.54", "866.67", "0.00")
    assert summary["net_per_check"]["display"] == "2,706.71 USD" and summary["complete"]


def test_a_blank_slate_runs_on_the_plan_alone(tables):
    _, tables_for = tables
    value = tom_scenario()
    result = run(value, empty_baseline("USD", 6, 500000, TODAY), tables_for, TODAY)
    first = result["months"][0]
    assert (first["income"], first["spending"], first["contributions"]) == (586454, 210000, 86667)
    assert first["cash"] == 500000 + 586454 - 210000
    assert result["paychecks"][0]["label"] == "Tom" and any("A blank slate" in note for note in result["notes"])
    # A missing state table is named: Colorado has none here.
    moved = tom_scenario(paychecks=[{"label": "Tom in Denver", "paycheck": {**TOM, "work_state": "CO"}, "from_month": "2026-10"}])
    assert any("Tom in Denver: some tax tables are missing" in note for note in run(moved, empty_baseline("USD", 6), tables_for, TODAY)["notes"])


def test_a_planned_bonus_is_paid_in_its_month_each_year(tables):
    _, tables_for = tables
    paycheck = {**TOM, "bonuses": [{"label": "Year-end", "amount": "10000", "month": 12}], "state_supplemental_percent": "5.19"}
    value = tom_scenario(paychecks=[{"label": "Tom", "paycheck": paycheck, "from_month": "2026-10"}], forecast={**FLAT, "years": 2})
    [plan], _ = paycheck_plans(value, tables_for)
    assert plan.monthly_net == "5864.54" and plan.yearly_bonuses[0].model_dump() == {"month_of_year": 12, "net": "6079.14", "retirement": "1000.00", "hsa": "0.00"}
    result = run(value, empty_baseline("USD", 6, 0, TODAY), tables_for, TODAY)
    # Every December: the regular 5,864.54 plus the bonus's 6,079.14, and its 1,000.00 into the planned 401(k).
    assert [month(result, name)["income"] for name in ("2026-11", "2026-12", "2027-12")] == [586454, 586454 + 607914, 586454 + 607914]
    assert month(result, "2026-12")["contributions"] == 86667 + 100000


def test_a_plans_retirement_stops_its_paychecks_and_draws_on_its_accounts(tables):
    _, tables_for = tables
    retire = {"start_month": "2027-04", "mode": "fixed", "monthly_amount": "1000", "tax_percent": "10"}
    value = tom_scenario(forecast={**FLAT, "years": 2, "retirement": retire})
    result = run(value, empty_baseline("USD", 6, 0, TODAY), tables_for, TODAY)
    # Tom's pay stops in April; his planned 401(k) (866.67 a month since October) pays 1,000 a month after 10% tax.
    march, april = month(result, "2027-03"), month(result, "2027-04")
    assert (march["income"], april["income"], april["contributions"]) == (586454, 0, 0)
    assert (april["withdrawals"], april["withdrawal_tax"]) == (100000, 11111)
    saved = ScenarioInput.model_validate(value.model_dump())
    assert saved.forecast.retirement.start_month == "2027-04"  # Kept with the plan.


def test_scenarios_are_saved_duplicated_and_deleted(tables):
    store, _ = tables
    saved = Scenarios(store)
    first = saved.create(tom_scenario())
    assert first["basis_name"] == "A blank slate" and first["inputs"]["paychecks"][0]["paycheck"]["annual_salary"] == "104000"
    copy = saved.duplicate(first["id"])
    assert copy["name"] == "Tom moves (copy)"
    saved.update(copy["id"], tom_scenario(name="Tom stays"))
    assert [row["name"] for row in saved.list()] == ["Tom moves", "Tom stays"]
    assert saved.input(first["id"]) == tom_scenario()
    saved.delete(first["id"])
    with pytest.raises(ValueError, match="not found"):
        saved.get(first["id"])
    with pytest.raises(ValidationError, match="as paychecks"):
        tom_scenario(forecast={"pay_plans": [pay_plan().model_dump()]})


def test_the_family_base_adds_its_members_up(tmp_path):
    stores = [Store(tmp_path / name) for name in ("ana", "tom")]
    try:
        for store, value in zip(stores, ("20000", "5000")):
            Assets(store).add(AssetInput(name="Car", kind="vehicle", value=value, currency="USD", as_of="2026-09-01"))
        combined = family_baseline([({"name": "Ana"}, stores[0]), ({"name": "Tom"}, stores[1])], 6, "USD", TODAY)
    finally:
        for store in stores:
            store.close()
    assert [asset["name"] for asset in combined["assets"]] == ["Ana · Car", "Tom · Car"]
    assert sum(asset["value_minor"] for asset in combined["assets"]) == 2500000 and combined["cash"] == 0
    assert all(asset["account_id"] is None for asset in combined["assets"])


def test_compare_draws_one_line_per_plan():
    runs = [(name, project(base(cash=cash), ForecastInput(years=3), TODAY)) for name, cash in (("Now", 0), ("Tom moves", 100000))]
    result = compare(runs)
    assert [run["name"] for run in result["runs"]] == ["Now", "Tom moves"] and result["chart"].startswith("<svg")
    assert "Tom moves" in result["chart"] and len(result["runs"][0]["years"]) == 3
    with pytest.raises(ValueError, match="at most 3"):
        compare(runs * 2)


def test_scenario_endpoints(tmp_path):
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        tables = TaxTables(app.state.manager.store)
        confirmed(tables, "US", FEDERAL)
        confirmed(tables, "GA", GEORGIA)
        draft = tom_scenario().model_dump()
        created = client.post("/api/scenarios", json=draft)
        assert created.status_code == 201
        view = client.get("/api/scenarios").json()
        assert [row["name"] for row in view["scenarios"]] == ["Tom moves"] and view["bases"] == ["profile", "blank"] and not view["family"]
        result = client.post("/api/scenarios/compare", json={"scenarios": [created.json()["id"]], "draft": {**draft, "name": "Tom, bigger 401(k)"}, "years": 2}).json()
        assert [run["name"] for run in result["runs"]] == ["Now", "Tom moves", "Tom, bigger 401(k)"] and all(len(run["years"]) == 2 for run in result["runs"])
        assert result["runs"][1]["paychecks"][0]["net_monthly"]["display"] == "5,864.54 USD"
        # Tax Zen in this year: Now from the records (no pay stubs, so no job to change), each plan at its full-year pay.
        assert result["runs"][0]["tax_zen"]["ready"] and result["runs"][1]["tax_zen"]["job"] == "Tom" and result["runs"][1]["tax_zen"]["w4"]["field"]
        assert client.post("/api/paycheck", json=TOM).json()["tax_time"]["ready"]
        assert client.post("/api/scenarios/compare", json={"scenarios": [1, 1, 1]}).status_code == 400
        assert client.post("/api/scenarios", json={**draft, "basis": "family"}).status_code == 201
        assert client.post("/api/scenarios/compare", json={"scenarios": [2], "include_now": False}).status_code == 400
        assert client.post(f"/api/scenarios/{created.json()['id']}/duplicate").status_code == 201
        assert client.delete(f"/api/scenarios/{created.json()['id']}").json()["deleted"]
        assert client.put("/api/scenarios/99", json=draft).status_code == 400
