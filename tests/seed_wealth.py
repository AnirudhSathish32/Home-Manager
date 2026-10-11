"""Synthetic Wealth & plans data for the redesigned screens' browser tests, the parity harness and ui_shots.py
(design-system/home-manager/phase2-wealth-plan.md "Seeding"). Synthetic data only."""
from datetime import date, timedelta

from conftest import inbox_scan
from home_manager.finance.investments import AccountInput, EventInput, HoldingInput, Investments, LotInput, PensionInput
from home_manager.finance.scenarios import ScenarioInput, Scenarios
from test_investments import statement


def next_month(today=None):
    today = today or date.today()
    return (today.replace(day=1) + timedelta(days=32)).strftime("%Y-%m")


def seed_plans(manager):
    """Two saved What If plans: Tom's move (a paycheck, set rent and a one-off) and a raise from January 2027. Returns their
    ids as {plan} (the move) and {raise_plan} for ui_shots.py's --routes."""
    saved, today = Scenarios(manager.store), date.today()
    month = next_month(today)
    move = saved.create(ScenarioInput.model_validate({
        "name": "Tom moves to Denver",
        "paychecks": [{"label": "Tom", "from_month": month,
                       "paycheck": {"year": today.year, "filing_status": "single", "work_state": "GA", "pay_frequency": 26, "annual_salary": "85000"}}],
        "forecast": {"category_amounts": [{"category": "rent", "monthly_amount": "2100", "from_month": month}],
                     "one_offs": [{"month": month, "amount": "-3000.00", "label": "Movers"}]}}))
    raise_plan = saved.create(ScenarioInput.model_validate({
        "name": "Raise in 2027", "forecast": {"income_changes": [{"month": "2027-01", "monthly_amount": "500"}]}}))
    return {"plan": move["id"], "raise_plan": raise_plan["id"]}


def seed_investments(manager, full=True):
    """Investment accounts as tests/test_investments.py's browser test has them, less its RMD person (the seed's birth
    year belongs to Taxes). full=False adds only a 401(k) and a CD account with its CD (the parity harness). Returns the
    accounts' ids by name."""
    store, investments, today = manager.store, Investments(manager.store), date.today()
    iso = lambda days: (today + timedelta(days=days)).isoformat()  # noqa: E731
    ids = {}
    ids["work"] = investments.add(AccountInput(name="Work 401(k)", kind="401k", institution="Fidelity", currency="USD", value="60000", as_of=iso(-41)))["id"]
    ids["cd"] = investments.add(AccountInput(name="12-month CD", kind="cd", institution="Ally", currency="USD", value="10000", as_of=iso(-40),
                                             annual_rate_percent="4.1"))["id"]
    # A CD coming due within the page's 90 days, whatever day it runs.
    investments.add_holding(ids["cd"], HoldingInput(name="Ally 12-month CD", instrument_class="cd", principal="10000", annual_rate_percent="4.10",
                                                    issue_date=iso(-335), maturity_date=iso(30)))
    if not full:
        return ids
    inbox_scan(store, {"ira-statement.png": b"synthetic ira statement", "brokerage-statement.png": b"synthetic brokerage statement",
                       "chase-1099-int.png": b"synthetic tax form"})
    docs = {doc["relative_path"].rsplit("/", 1)[-1]: doc for doc in store.documents()["items"]}
    # The Rollover IRA's statement: a fund with a gain and a CD, and a contribution; it waits in To check.
    record, source = statement(docs, "ira-statement.png", iso(-11), 1500000, investment_kind="ira", account_name="Rollover IRA", institution="Schwab", last_four="4321")
    record["holdings"] = [{"name": "Total Stock Market Index Admiral", "identifier": "VTSAX", "instrument_class": "mutual_fund", "quantity": "80.000",
                           "value_minor": 1000000, "price_minor": 12500, "cost_basis_minor": 800000},
                          {"name": "Schwab 18-month CD", "instrument_class": "cd", "value_minor": 500000, "rate_bp": 410, "maturity_date": iso(170)}]
    record["activity"] = [{"name": "Contribution", "event_date": iso(-26), "event_type": "contribution", "contribution_source": "personal", "amount_minor": 50000}]
    ids["ira"] = investments.publish_statement(record, source)["account_id"]
    # I bonds over the yearly limit, a pension's terms, and a 529 with a withdrawal not yet marked.
    ids["ibonds"] = investments.add(AccountInput(name="TreasuryDirect", kind="i_bond", currency="USD", value="0", as_of="2024-01-01"))["id"]
    for name, principal, issued in (("I bond Jan 2024", "10000", "2024-01-20"), ("I bond Mar 2024", "500", "2024-03-01")):
        investments.add_holding(ids["ibonds"], HoldingInput(name=name, instrument_class="i_bond", principal=principal, issue_date=issued))
    ids["pension"] = investments.add(AccountInput(name="State pension", kind="pension", currency="USD"))["id"]
    investments.set_pension(ids["pension"], PensionInput(monthly_benefit="2400", start_date="2040-06-01", cola_percent="2", survivor_percent=50, lump_sum="350000"))
    ids["education"] = investments.add(AccountInput(name="Maya 529", kind="education_529", currency="USD", value="40000", as_of=f"{today.year}-01-01",
                                                    beneficiary="Maya", plan_state="UT"))["id"]
    investments.add_event(ids["education"], EventInput(event_type="withdrawal", event_date=f"{today.year - 1}-09-10", amount="2000"))
    # A brokerage account: one confirmed VTI holding with one tax lot, so its gain by lot cost shows.
    record, source = statement(docs, "brokerage-statement.png", iso(-12), 1200000, account_name="Brokerage", last_four="2222")
    record["holdings"] = [{"name": "Vanguard Total Stock Market ETF", "identifier": "VTI", "instrument_class": "etf", "quantity": "40.000",
                           "value_minor": 1200000, "price_minor": 30000, "cost_basis_minor": 1000000}]
    published = investments.publish_statement(record, source)
    investments.review(published["id"], "verified")
    ids["brokerage"] = published["account_id"]
    holding = investments.get(ids["brokerage"])["holdings"][0]
    investments.add_lot(holding["id"], LotInput(acquired_date=f"{today.year - 3}-03-15", quantity="40", cost="10000"))
    # A confirmed 1099-INT for last year from a bank with no account here.
    form = investments.publish_tax_form({"institution": "Chase", "last_four": "9999", "tax_year": today.year - 1, "currency": "USD", "issues": [],
                                         "boxes": [{"form": "1099-INT", "box": "1", "label": "Interest income", "amount_minor": 1200, "locator": {}}]},
                                        {"document_id": docs["chase-1099-int.png"]["id"], "blob_hash": docs["chase-1099-int.png"]["current_hash"], "run_id": "chase"})
    investments.review_tax_form(form["id"], "verified")
    return ids
