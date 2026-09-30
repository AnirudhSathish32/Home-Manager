"""A tax year's figures and inputs (docs/taxes.md): the figures lookup's checks, typed figures, gathering the return from
pay stubs, interest and tags, and your typed values over them. Synthetic data only."""

from datetime import date

from fastapi.testclient import TestClient
import pytest

from conftest import documents_by_name, inbox_scan
from home_manager.app.api import create_app
from home_manager.finance.ledger import HouseholdConfig, Ledger
from home_manager.finance.tax_tags import TaxTags
from home_manager.finance.tax_year import TaxYears, gather, merge, paydays_left
from home_manager.household.tax_figures import FigureTools, ProposeInput, TaxFigures
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


def test_typed_figures_count_at_once_and_replace_looked_up_ones(store):
    figures = TaxFigures(store)
    looked_up = figures.propose(2026, "single", {"cg_zero_max": 4835000, "ctc_per_child": 220000}, [{"url": "https://www.irs.gov/x", "quote": "q"}])
    assert figures.effective(2026, "single")["values"] == {} and figures.effective(2026, "single")["waiting"]
    figures.review(looked_up["id"], "verified")
    typed = figures.type_in(2026, "single", {"ctc_per_child": "2,300", "dc_rate_high": "50%"})
    assert typed["values"] == {"cg_zero_max": 4835000, "ctc_per_child": 230000, "dc_rate_high": 5000}
    assert (typed["sources"]["ctc_per_child"], typed["sources"]["cg_zero_max"], typed["display"]["dc_rate_high"]) == ("typed", "lookup", "50%")
    assert "salt_cap" in typed["missing"]
    assert figures.type_in(2026, "single", {"ctc_per_child": None})["values"]["ctc_per_child"] == 220000  # Back to the looked-up one.
    with pytest.raises(ValueError, match="an amount such as"):
        figures.type_in(2026, "single", {"salt_cap": "lots"})
    with pytest.raises(ValueError, match="Unknown figure"):
        figures.type_in(2026, "single", {"nope": "1"})


def test_a_looked_up_figure_must_be_quoted_from_an_opened_page(store):
    tools = FigureTools(TaxFigures(store), web=None, year=2026, filing_status="single")
    tools.pages = {"r1": {"url": "https://www.irs.gov/rp", "title": "Rev. Proc.", "text": "The maximum zero rate amount is $48,350 for single filers."}}
    quote = {"result_id": "r1", "text": "The maximum zero rate amount is $48,350 for single filers."}
    with pytest.raises(ValueError, match="not printed in your quotes"):
        tools.propose_tax_figures(ProposeInput.model_validate({"quotes": [quote], "figures": [{"key": "cg_zero_max", "value": "49,000"}]}))
    with pytest.raises(ValueError, match="not an exact passage"):
        tools.propose_tax_figures(ProposeInput.model_validate({"quotes": [{"result_id": "r1", "text": "The maximum zero rate is $48,350 always."}],
                                                               "figures": [{"key": "cg_zero_max", "value": "48,350"}]}))
    result = tools.propose_tax_figures(ProposeInput.model_validate({"quotes": [quote], "figures": [{"key": "cg_zero_max", "value": "48,350"}]}))
    assert TaxFigures(store).get(result["tax_figures_id"])["figures"]["cg_zero_max"]["value"] == 4835000


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
    assert job["values"]["wages"] == 10 * (400000 - 34000) and job["values"]["federal_withheld"] == 45000 + 47000 + 8 * 47000
    assert job["values"]["ss_wages"] == 10 * (400000 - 10000)  # Health lowers FICA wages; the 401(k) doesn't.
    # 1,200 of interest by September, projected at the same pace: 1,600.
    assert (gathered["values"]["interest"], gathered["values"]["charity"], gathered["state"]) == (160000, 25000, "GA")
    typed = {"fields": {"qualified_dividends": "100", "qualifying_children": "1"}, "jobs": {job["key"]: {"federal_withheld": "5000"}},
             "extra_jobs": [{"name": "Spouse's job", "wages": "40000", "federal_withheld": "3000"}], "people": [{"name": "Ana", "birth_year": 1958}]}
    merged = merge(2026, "married_joint", household, gathered, typed)
    assert [(job.name, job.wages, job.federal_withheld) for job in merged.jobs] == [("Employer", 3660000, 500000), ("Spouse's job", 4000000, 300000)]
    assert (merged.qualified_dividends, merged.qualifying_children, merged.charity, [person.birth_year for person in merged.people]) == (10000, 1, 25000, [1990, 1958])
    TaxYears(store).save(2026, typed)
    assert TaxYears(store).inputs(2026) == typed
    with pytest.raises(ValueError, match="Unknown field"):
        TaxYears(store).save(2026, {"fields": {"nope": "1"}})


def test_tax_year_endpoints(tmp_path):
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        empty = client.get("/api/tax/year/2026").json()
        assert empty["return"]["missing"] == ["federal_table"] and empty["tables"]["US"] == "missing"
        confirmed(TaxTables(app.state.manager.store), "US", FEDERAL)
        saved = client.put("/api/tax/year/2026", json={"extra_jobs": [{"name": "Job", "wages": "94770", "federal_withheld": "12463.36"}]}).json()
        assert saved["return"]["result_minor"] == -164 and saved["inputs"]["extra_jobs"][0]["name"] == "Job"
        figures = client.put("/api/tax/figures/2026", json={"figures": {"cg_zero_max": "48,350"}}).json()
        assert figures["values"] == {"cg_zero_max": 4835000}
        assert client.post("/api/tax/figures/2026/lookup", json={}).status_code == 400  # No reasoning model set up here.
        assert client.get("/api/tax/figure-sets", params={"status": "proposed"}).json() == {"sets": []}
        assert client.get("/api/tax/year/1800").status_code == 400
