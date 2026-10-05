"""A tax year's inputs (docs/taxes.md): gathering the return from pay stubs, interest, tags and forms, the tax engine's facts
filled from records, and your typed values over them. Synthetic data only."""

from datetime import date
from decimal import Decimal
import json
import shutil

from fastapi.testclient import TestClient
import pytest

from conftest import documents_by_name, inbox_scan
from home_manager.app.api import create_app
from home_manager.finance.engines import opentax, taxcalc
from home_manager.finance.ledger import HouseholdConfig, Ledger
from home_manager.finance.tax_tags import TaxTags
from home_manager.finance.tax_year import TaxYears, average_balance, balance_at, gather, hsa_coverage, likely_range, merge, paydays_left
from home_manager.household.tax_tables import TaxTables
from home_manager.library.scanner import ScanLimits
from home_manager.library.storage import Store
from test_plan_tracking import stub
from test_withholding import FEDERAL, confirmed

TODAY = date(2026, 9, 30)


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / "managed")
    try:
        yield value
    finally:
        value.close()


def test_paydays_left_in_the_year():
    assert paydays_left("2026-08-28", 26, 2026) == 8  # Every 14 days after Aug 28: Sep 11 … Dec 18.
    assert paydays_left("2026-09-25", 52, 2026) == 13
    assert paydays_left("2026-09-15", 24, 2026) == 7  # Sep 30, then the 15th and last day of Oct, Nov and Dec.
    assert paydays_left("2026-09-01", 12, 2026) == 3
    assert paydays_left(None, 26, 2026) == 0


def test_the_return_is_gathered_from_stubs_interest_and_tags(store):
    inbox_scan(store, {name: name.encode() for name in ("aug1.png", "aug2.png", "export.csv")})
    docs = documents_by_name(store)
    stub(store, docs["aug1.png"], "2026-08-14", 45000, 280000)
    stub(store, docs["aug2.png"], "2026-08-28", 47000, 278000)
    with store.connection() as db:
        db.execute("UPDATE income_records SET pay_frequency=26,work_state='GA'")
    ledger = Ledger(store)
    account = ledger.create_account("First Local Bank", "checking", "USD")
    source = {"document_id": docs["export.csv"]["id"], "blob_hash": docs["export.csv"]["current_hash"], "source_key": "import:test"}
    with store.connection() as db:
        [interest, gift] = ledger.insert_transactions(db, account, [{"posted_date": "2026-06-30", "description": "INTEREST PAYMENT", "amount_minor": 120000, "currency": "USD",
                                                                    "locator": {"rows": [1]}},
                                                                   {"posted_date": "2026-07-01", "description": "RED CROSS", "amount_minor": -25000, "currency": "USD",
                                                                    "locator": {"rows": [2]}}], "import", source)[0]
    TaxTags(store).tag("transaction", gift, "itemized", "charity_cash")
    household = HouseholdConfig(filing_status="single", birth_year=1990)
    gathered = gather(store, 2026, household, TODAY)
    [job] = gathered["jobs"]
    # No year-to-date figures printed: the two stubs added up, then 8 more paydays like the last. Two of them (Sep 11 and 25) are
    # already past on Sep 30 without a stub here: they count, but only the 6 ahead can change with a new W-4.
    assert (job["stubs"], job["paychecks_projected"], job["paychecks_left"], job["ytd_printed"]) == (2, 8, 6, False)
    assert job["paydays_without_stub"] == 2  # Shown on the Taxes page as is.
    assert job["values"]["wages"] == 10 * (400000 - 34000) and job["values"]["federal_withheld"] == 45000 + 47000 + 8 * 47000
    assert job["values"]["ss_wages"] == 10 * (400000 - 10000)  # Health lowers FICA wages; the 401(k) doesn't.
    # 1,200 of interest by September, projected at the same pace: 1,600.
    assert (gathered["values"]["interest"], gathered["values"]["charity"], gathered["state"]) == (160000, 25000, "GA")
    # Each value says what kind it is (§35): the projected interest and job, the tagged gift as recorded, the
    # qualified part of dividends still to enter.
    kinds = gathered["kinds"]
    assert (kinds["interest"], kinds["charity"], kinds["qualified_dividends"], job["kind"]) == ("projected", "record", "to_enter", "projected")
    typed = {"fields": {"qualified_dividends": "100", "qualifying_children": "1"}, "jobs": {job["key"]: {"federal_withheld": "5000"}},
             "extra_jobs": [{"name": "Spouse's job", "wages": "40000", "federal_withheld": "3000"}], "people": [{"name": "Ana", "birth_year": 1958}]}
    merged = merge(2026, "married_joint", household, gathered, typed)
    assert [(job.name, job.wages, job.federal_withheld) for job in merged.jobs] == [("Employer", 3660000, 500000), ("Spouse's job", 4000000, 300000)]
    assert (merged.qualified_dividends, merged.qualifying_children, merged.charity, [person.birth_year for person in merged.people]) == (10000, 1, 25000, [1990, 1958])
    TaxYears(store).save(2026, typed)
    assert TaxYears(store).inputs(2026) == typed
    with pytest.raises(ValueError, match="Unknown field"):
        TaxYears(store).save(2026, {"fields": {"nope": "1"}})


def test_the_likely_range_moves_only_what_is_projected():
    from home_manager.finance.tax_return import Job, ReturnInput
    gathered = {"projected": {"interest": 40000}, "jobs": [{"key": "e1", "spread_bp": 500, "projected": {"wages": 1000000, "federal_withheld": 100000}}]}
    merged = ReturnInput(year=2026, filing_status="single", jobs=[Job(wages=5000000, federal_withheld=500000)], interest=160000)
    lower, higher, confidence = likely_range(merged, gathered, {})
    # Pay still to come moves by 5% (10,000 × 5%), with its withholding; interest still to come by 25%.
    assert (lower.jobs[0].wages, lower.jobs[0].federal_withheld, lower.interest) == (4950000, 495000, 150000)
    assert (higher.jobs[0].wages, higher.interest) == (5050000, 170000)
    assert confidence == "medium"  # 10,400 of 51,600 is projected: 20%.
    # Typed values stay put.
    typed_lower, _, _ = likely_range(merged, gathered, {"fields": {"interest": "1600"}, "jobs": {"e1": {"wages": "50000"}}})
    assert (typed_lower.interest, typed_lower.jobs[0].wages, typed_lower.jobs[0].federal_withheld) == (160000, 5000000, 495000)


def test_ibond_interest_is_marked_state_exempt_and_529_earnings_are_income(store):
    from home_manager.finance.investments import AccountInput, EventInput, Investments
    from home_manager.finance.tax_return import ReturnInput, state_return
    investments = Investments(store, TODAY)
    bonds = investments.add(AccountInput(name="TreasuryDirect", kind="i_bond", currency="USD", value="10000", as_of="2026-01-01"))
    investments.add_event(bonds["id"], EventInput(event_type="interest", event_date="2026-06-01", amount="300"))
    plan = investments.add(AccountInput(name="529", kind="education_529", currency="USD", value="10000", as_of="2026-01-01"))
    investments.add_event(plan["id"], EventInput(event_type="nonqualified_withdrawal", event_date="2026-06-01", amount="1000"))
    gathered = gather(store, 2025 + 1, HouseholdConfig(), date(2026, 12, 31))
    assert gathered["values"]["interest"] == gathered["values"]["us_obligation_interest"] == 30000
    assert "exempt from state tax" in gathered["sources"]["us_obligation_interest"]
    assert "other_income" not in gathered["values"]  # No 1099-Q yet, so the earnings share is unknown.
    table = {"status": "verified", "standard_deduction_minor": 0, "brackets_json": '[{"from_minor": 0, "rate_bp": 500}]'}
    taxed = state_return(ReturnInput(year=2026, filing_status="single", state="GA", interest=30000, us_obligation_interest=30000), 100000, table)
    assert taxed["taxable_minor"] == 70000  # The state leaves the I bond interest out.


def form(store, doc, boxes, name="1098"):
    """A confirmed tax form for 2026 with these boxes: [(box, cents)]."""
    with store.connection() as db:
        form_id = db.execute("INSERT INTO tax_forms(institution,tax_year,currency,document_id,blob_hash,review_status,created_at,updated_at) "
                             "VALUES('First Home Lending',2026,'USD',?,?,'verified','t','t')", (doc["id"], doc["current_hash"])).lastrowid
        db.executemany("INSERT INTO tax_form_boxes(form_id,form,box,label,amount_minor) VALUES(?,?,?,?,?)",
                       [(form_id, name, box, f"Box {box}", amount) for box, amount in boxes])


def loan(store, name, owed, rate_bp, payment):
    with store.connection() as db:
        db.execute("INSERT INTO assets(name,kind,value_minor,currency,as_of,annual_rate_bp,monthly_payment_minor,source,review_status,created_at,updated_at) "
                   "VALUES(?,'loan',?,'USD','2026-09-30',?,?,'manual','verified','t','t')", (name, owed, rate_bp, payment))


def test_a_1098_and_the_mortgage_fill_the_average_balance(store):
    inbox_scan(store, {"1098.pdf": b"1098"})
    form(store, documents_by_name(store)["1098.pdf"], [("1", 1200000), ("2", 30000000), ("10", 400000)])
    loan(store, "Home Mortgage", 29000000, 0, 100000)
    loan(store, "Car loan", 1500000, 600, 40000)  # Not the mortgage: its name doesn't say so.
    gathered = gather(store, 2026, HouseholdConfig(), TODAY)
    values, sources = gathered["values"], gathered["sources"]
    assert (values["mortgage_interest"], values["property_tax"], sources["mortgage_interest"]) == (1200000, 400000, "1098 box 1")
    # Pub 936: the average of 300,000 on Jan 1 (box 2) and 287,000 on Dec 31 (290,000 on Sep 30, three payments of 1,000 at 0%).
    assert values["mortgage_average_balance"] == 29350000 and "1098 box 2" in sources["mortgage_average_balance"]
    assert (gathered["kinds"]["mortgage_interest"], gathered["kinds"]["mortgage_average_balance"]) == ("record", "worked_out")
    assert merge(2026, "single", HouseholdConfig(), gathered, {"fields": {"mortgage_average_balance": "250000"}}).mortgage_average_balance == 25000000


def test_the_average_balance_methods_and_balances_over_time():
    mortgage = {"name": "Home Mortgage", "value_minor": 29000000, "as_of": "2026-09-30", "annual_rate_bp": 400, "monthly_payment_minor": 180000}
    # 4% a year is 1/300 a month: 290,000 → 289,166.67 → 288,330.56 → 287,491.66 by Dec 31.
    assert balance_at(mortgage, date(2026, 12, 31)) == 28749166 and balance_at(mortgage, date(2026, 9, 1)) == 29000000
    assert balance_at({**mortgage, "monthly_payment_minor": None}, date(2026, 12, 31)) is None
    # Back in time too: last Dec 31's balance, paid down again, comes back to Sep 30's within a cent.
    back = balance_at(mortgage, date(2025, 12, 31))
    assert abs(balance_at({**mortgage, "value_minor": back, "as_of": "2025-12-31"}, date(2026, 9, 30)) - 29000000) <= 1
    # The forecast pays the same loan down with the same monthly step (forecast.loan_month): its December balance agrees.
    from home_manager.finance.forecast import ForecastInput, project
    base = {"currency": "USD", "cash": 0, "balances": [], "monthly_income": Decimal(0), "monthly_pay": Decimal(0), "monthly_spending": {}, "bills": [], "notes": [],
            "history": {"start": "2026-03-01", "end": "2026-08-31", "months": 6, "months_with_data": 6},
            "assets": [{"name": "Home Mortgage", "kind": "loan", "value_minor": 29000000, "value": None, "annual_rate_bp": 400, "annual_rate_percent": "4",
                        "monthly_payment_minor": 180000, "monthly_payment": None, "terms": []}]}
    december = next(row for row in project(base, ForecastInput(years=1, inflation_percent="0"), today=date(2026, 9, 30))["months"] if row["month"] == "2026-12")
    assert december["loans"] == balance_at(mortgage, date(2026, 12, 31))
    # No box 2: the year's interest ÷ the yearly rate (12,000 ÷ 4%); box 2 alone: the Jan 1 principal, an upper bound.
    assert average_balance(1200000, None, [mortgage], 2026)[0] == 30000000
    assert average_balance(1200000, 31000000, [], 2026)[0] == 31000000
    assert average_balance(1200000, None, [], 2026) is None and average_balance(1200000, None, [mortgage, mortgage], 2026) is None


def test_hsa_coverage_from_what_went_in(store):
    # Within the 2026 self-only limit (4,400) the coverage doesn't change the deduction; above it, it's family coverage.
    assert hsa_coverage(440000, 2026, 1990)[0] == "self" and hsa_coverage(440001, 2026, 1990)[0] == "family"
    assert hsa_coverage(540000, 2026, 1970)[0] == "self"  # 55 or older: 1,000 more.
    assert "more than the family limit" in hsa_coverage(900000, 2026, 1990)[1]
    assert hsa_coverage(0, 2026, 1990) is None and hsa_coverage(100000, 2031, 1990) is None
    # Payroll HSA lines (yours and the employer's) projected to Dec 31: 2 stubs and 8 more paydays at 150 each.
    inbox_scan(store, {name: name.encode() for name in ("aug1.png", "aug2.png", "5498.pdf")})
    docs = documents_by_name(store)
    stub(store, docs["aug1.png"], "2026-08-14", 45000, 280000)
    stub(store, docs["aug2.png"], "2026-08-28", 47000, 278000)
    with store.connection() as db:
        db.execute("UPDATE income_records SET pay_frequency=26")
        for record in [row[0] for row in db.execute("SELECT id FROM income_records")]:
            db.executemany("INSERT INTO income_lines(income_record_id,position,description,line_group,category,current_minor,locator_json) VALUES(?,?,?,?,?,?,'{}')",
                           [(record, 20, "HSA", "pre_tax", "hsa", 10000), (record, 21, "Employer HSA", "employer_paid", "hsa", 5000)])
    gathered = gather(store, 2026, HouseholdConfig(birth_year=1990), TODAY)
    assert gathered["jobs"][0]["hsa_minor"] == 150000 and gathered["values"]["hsa_coverage"] == "self"
    # The 5498-SA's box 2 is every contribution for the year: once it's here, it decides.
    form(store, docs["5498.pdf"], [("2", 600000)], "5498-SA")
    assert gather(store, 2026, HouseholdConfig(birth_year=1990), TODAY)["values"]["hsa_coverage"] == "family"
    assert merge(2026, "single", HouseholdConfig(), gather(store, 2026, HouseholdConfig(), TODAY), {"fields": {"hsa_coverage": "self"}}).hsa_coverage == "self"


@pytest.mark.skipif(shutil.which("node") is None or date.today().year not in opentax.YEARS, reason="Node.js isn't installed, or Engine 1 isn't pinned for this year")
def test_a_worse_tax_zen_is_put_on_home_until_the_taxes_page_is_opened(tmp_path):
    # Home looks at this year's return, so this runs in the years Engine 1 is pinned for.
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        manager, year = app.state.manager, date.today().year
        confirmed(TaxTables(manager.store), "US", FEDERAL)
        manager.configure_household(manager.household.model_copy(update={"birth_year": 1985, "tax_engine_compare": False}))
        # On the Taxes page: about 442 back, close enough to watch.
        client.put(f"/api/tax/year/{year}", json={"extra_jobs": [{"name": "Job", "wages": "94770", "federal_withheld": "12463.36"}]})
        month = f"/api/dashboard?month={date.today().isoformat()[:7]}&months=6"
        assert client.get(month).json()["attention"]["tax"] is None
        # Withholding typed lower elsewhere (not on the Taxes page): Home works the return out again and says so.
        TaxYears(manager.store).save(year, {"extra_jobs": [{"name": "Job", "wages": "94770", "federal_withheld": "9000"}]})
        found = manager.tax_attention(wait=True)
        assert found["status"] == "ACTION_RECOMMENDED" and "The jobs you typed in changed" in found["trigger"]
        assert client.get(month).json()["attention"]["tax"]["status"] == "ACTION_RECOMMENDED"
        client.get(f"/api/tax/year/{year}")  # The Taxes page shows it.
        assert client.get(month).json()["attention"]["tax"] is None


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js isn't installed")
def test_tax_year_endpoints(tmp_path):
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        empty = client.get("/api/tax/year/2026")
        # No income and no birth year: the earned income credit turns on age, so the engine asks rather than guesses.
        assert empty.json()["return"]["needs"] == ["isAtLeastAge25"] and empty.json()["tables"]["US"] == "missing"
        assert empty.json()["return"]["engine"]["label"] == "Engine 1" and "OpenTax" not in empty.text  # The page names the slot, never the engine.
        confirmed(TaxTables(app.state.manager.store), "US", FEDERAL)
        # Last year's return worked out here fills this year's safe harbor until the filed figures are typed.
        client.put("/api/tax/year/2025", json={"extra_jobs": [{"name": "Job", "wages": "50000", "federal_withheld": "5000"}]})
        saved = client.put("/api/tax/year/2026", json={"extra_jobs": [{"name": "Job", "wages": "94770", "federal_withheld": "12463.36"}]}).json()
        # 2026 law: 94,770 less 16,100; 78,670 is in the 78,650–78,700 row of the Tax Table: 12,021. 12,463.36 withheld.
        assert abs(saved["return"]["result_minor"] - 44236) <= 100 and saved["inputs"]["extra_jobs"][0]["name"] == "Job"
        assert "worked out here" in saved["prior_year"]["source"] and saved["prior_year"]["tax_minor"] > 0
        typed = client.put("/api/tax/year/2026", json={**saved["inputs"], "prior_year_tax": {"tax": "4000", "agi": "60000"}}).json()
        assert typed["prior_year"] == {"tax_minor": 400000, "agi_minor": 6000000}
        assert client.get("/api/tax/year/1800").status_code == 400
        # The page's return is kept in tax_calculations, once per engine and profile, with the implementation behind the slot.
        from home_manager.finance.tax_engine import TaxCalculations
        manager = app.state.manager
        kept = TaxCalculations(manager.store).list(2026)
        engine_1 = [row for row in kept if row["engine"] == "opentax"]
        assert engine_1 and abs(engine_1[0]["result_minor"] - 44236) <= 100
        if taxcalc.installed() == taxcalc.PINNED:  # Engine 2 checks it (on by default) and agrees: its answer is kept too.
            assert {row["engine"] for row in kept} == {"opentax", "taxcalc"} and saved["return"]["comparison"]["agree"]
            shown = json.dumps(saved).lower()
            assert saved["return"]["comparison"]["engine"]["label"] == "Engine 2" and "taxcalc" not in shown and "tax-calculator" not in shown
            assert abs(next(row for row in kept if row["engine"] == "taxcalc")["result_minor"] - 44236) <= 100
        # The assistant's Tax Zen tool: the deterministic status, small, for the model to explain.
        from home_manager.finance.tools import TOOLS, TaxYearInput, call_tool
        status = call_tool(manager.tools, "get_tax_zen_status", {"year": 2026})
        assert "get_tax_zen_status" in TOOLS and TaxYearInput().year is None
        # About 442 back: more than a dollar from $0, so not Tax Zen, but within the 500 watch band and safe: watch it.
        assert status["status"] == "WATCH" and (status["engine"]["slot"], status["engine"]["label"]) == ("engine_1", "Engine 1")
        assert "refund" in status["year_end"] and status["safe_harbor"]["satisfied"] and status["aim"]["strategy"] == "precision"
        # A saved aim changes it: with a 1,000 refund as the aim, about 558 away, past the 500 watch band.
        client.put("/api/tax/year/2026", json={**typed["inputs"], "zen_policy": {"strategy": "small_refund", "refund": "1000"}})
        aimed = call_tool(manager.tools, "get_tax_zen_status", {"year": 2026})
        assert aimed["aim"] == {"strategy": "small_refund", "year_end": "1,000.00 USD", "refund": True} and aimed["status"] == "ACTION_RECOMMENDED"
        # Settings say whether Engine 1 can run here.
        assert client.get("/api/settings").json()["tax_engine"]["ready"]


@pytest.mark.skipif(taxcalc.installed() != taxcalc.PINNED, reason="Engine 2 isn't installed")
def test_a_return_engine_1_doesnt_cover_is_worked_out_by_engine_2(tmp_path):
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        manager = app.state.manager
        household = HouseholdConfig(filing_status="married_joint", birth_year=1980)
        # Both spouses self-employed: Engine 1 has no Schedule SE for each, Engine 2 does.
        gathered = {"values": {}, "sources": {}, "jobs": [], "state": None, "notes": [], "estimated_payments": {"federal_estimated": [], "state_estimated": []},
                    "businesses": [{"key": "a", "name": "Design", "owner": "", "income": 3000000, "expenses": 0},
                                   {"key": "b", "name": "Tutoring", "owner": "spouse", "income": 1000000, "expenses": 0}]}
        view = manager.tax_view(2026, "married_joint", household, gathered, {"people": [{"name": "Sam", "birth_year": 1982}]},
                                lambda codes: {}, today=date(2026, 6, 1))
        result = view["return"]
        assert result["engine"]["label"] == "Engine 2" and result["result_minor"] is not None
        assert result["notes"][0] == "Engine 1 doesn't cover this return, so Engine 2 worked it out."
        # Each spouse's own self-employment tax: 92.35% × 15.3% of 30,000 and of 10,000.
        lines = {line["key"]: line["amount_minor"] for line in result["lines"]}
        assert abs(lines["other_se"] - (423883 + 141294)) <= 100
