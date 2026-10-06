"""How a pay stub's taxes are figured, and looking up tax tables (docs/taxes.md "Jobs and pay stubs"). The tables here are
synthetic, not any year's real figures."""

import json

import pytest

from home_manager.core.jobs import Work
from home_manager.documents.reasoning import ReasoningConfig
from home_manager.finance.charts import tax_buckets_svg
from home_manager.finance.paystub import explain
from home_manager.household.tax_tables import TaxTables, TaxTableService, TaxTableTools
from home_manager.library.storage import Store
from home_manager.models.web_lookup import BRAVE_SEARCH, WebLookup

FEDERAL = {"standard_deduction_minor": 1500000, "brackets": [{"from_minor": 0, "rate_bp": 1000}, {"from_minor": 1192500, "rate_bp": 1200},
                                                             {"from_minor": 4847500, "rate_bp": 2200}, {"from_minor": 10335000, "rate_bp": 2400}],
           "ss_rate_bp": 620, "ss_wage_base_minor": 17610000, "medicare_rate_bp": 145, "additional_medicare_rate_bp": 90,
           "additional_medicare_threshold_minor": 20000000}
GEORGIA = {"standard_deduction_minor": 1500000, "brackets": [{"from_minor": 0, "rate_bp": 519}]}


def line(group, category, current, ytd=None):
    return {"line_group": group, "category": category, "current_minor": current, "ytd_minor": ytd, "description": category}


LINES = [line("earnings", "regular_pay", 400000, 7200000), line("pre_tax", "retirement_pretax", 24000, 432000), line("pre_tax", "health", 10000, 180000),
         line("pre_tax", "dental", 1000, 18000), line("pre_tax", "vision", 500, 9000), line("tax", "federal_income_tax", 38000),
         line("tax", "state_income_tax", 17000), line("tax", "social_security", 24087), line("tax", "medicare", 5633),
         line("employer_paid", "other", 16000)]
RECORD = {"pay_date": "2026-09-15", "pay_frequency": 26, "work_state": "GA", "currency": "USD"}


@pytest.fixture
def tables(tmp_path):
    store = Store(tmp_path / "managed")
    try:
        yield store, TaxTables(store)
    finally:
        store.close()


def confirmed(tables, code, values):
    source = [{"url": "https://example.gov/rates", "title": "Rates", "quote": "synthetic"}]
    table = tables.propose(code, 2026, "single", values, source)
    return tables.review(table["id"], "verified")


def test_federal_and_state_buckets_estimate_and_fica(tables):
    store, service = tables
    confirmed(service, "US", FEDERAL)
    confirmed(service, "GA", GEORGIA)
    result = explain(RECORD, LINES, service.for_year(2026, ["US", "GA"], "single"), "single")
    federal, georgia = result["jurisdictions"]
    # Income-tax wages: 4,000 less 401(k), health, dental and vision = 3,645 a paycheck, 94,770 a year.
    assert (federal["period_wages_minor"], federal["annual_wages_minor"], federal["taxable_minor"]) == (364500, 9477000, 7977000)
    assert [(bucket["label"], bucket["income_minor"], bucket["tax_minor"]) for bucket in federal["buckets"]] == [
        ("Standard deduction", 1500000, 0), ("10%", 1192500, 119250), ("12%", 3655000, 438600), ("22%", 3129500, 688490), ("24%", 0, 0)]
    # 12,463.40 a year over 26 paychecks = 479.36, against 380.00 withheld.
    assert (federal["annual_tax_minor"], federal["estimate_minor"], federal["difference_minor"]) == (1246340, 47936, -9936)
    assert federal["standard_deduction_per_paycheck_minor"] == 57692 and federal["top_rate_bp"] == 2200
    assert federal["display"]["estimate_minor"] == "479.36 USD"
    # Georgia: one flat bucket above its deduction.
    assert (georgia["name"], georgia["estimate_minor"], georgia["actual_minor"], georgia["difference_minor"]) == ("Georgia", 15923, 17000, 1077)
    # FICA wages keep the 401(k): 4,000 less health, dental and vision = 3,885.
    assert [(row["name"], row["wages_minor"], row["estimate_minor"], row["difference_minor"]) for row in result["fica"]] == [
        ("Social Security", 388500, 24087, 0), ("Medicare", 388500, 5633, 0)]
    svg = tax_buckets_svg("Federal income tax buckets, 2026", federal["buckets"], "USD", 26)
    assert svg == tax_buckets_svg("Federal income tax buckets, 2026", federal["buckets"], "USD", 26)  # Deterministic.
    assert ">0%</text>" in svg and ">deduction</text>" in svg and ">22%</text>" in svg and "<script" not in svg


def test_social_security_stops_at_the_wage_base(tables):
    store, service = tables
    confirmed(service, "US", {**FEDERAL, "ss_wage_base_minor": 6800000})
    result = explain(RECORD, LINES, service.for_year(2026, ["US"], "single"), "single")
    social = result["fica"][0]
    # Year-to-date FICA wages 69,930 include this paycheck's 3,885: only 68,000 - 66,045 = 1,955 is still under the base.
    assert (social["wages_minor"], social["estimate_minor"]) == (195500, 12121)


def test_additional_medicare_is_withheld_above_200000_whatever_the_filing_status(tables):
    # The joint return's threshold is $250,000 (Form 8959), but payroll withholds the extra 0.9% on wages above $200,000
    # (IRC §3102(f)(1)): this $10,000 paycheck brings the year to $210,000, all of it above.
    store, service = tables
    table = service.propose("US", 2026, "married_joint", {**FEDERAL, "additional_medicare_threshold_minor": 25000000}, [])
    service.review(table["id"], "verified")
    lines = [line("earnings", "regular_pay", 1000000, 21000000), line("tax", "medicare", 23500)]
    medicare = explain(RECORD, lines, service.for_year(2026, ["US"], "married_joint"), "married_joint")["fica"][1]
    assert (medicare["additional_wages_minor"], medicare["limit_minor"], medicare["estimate_minor"], medicare["difference_minor"]) == (1000000, 20000000, 23500, 0)


def test_a_missing_or_unconfirmed_table_is_said_so(tables):
    store, service = tables
    service.propose("GA", 2026, "single", GEORGIA, [])
    result = explain(RECORD, LINES, service.for_year(2026, ["US", "GA"], "single"), "single")
    assert [(part["status"], part["message"]) for part in result["jurisdictions"]] == [
        ("missing", "The 2026 Federal tax table hasn't been looked up yet."),
        ("proposed", "The 2026 Georgia tax table waits for your confirmation in Review.")]
    assert result["fica"] == []
    assert service.needed(2026, "GA", "single") == ["US"] and service.needed(2026, "TX", "single") == ["US"]


PAGE = ("<html><head><title>Georgia Department of Revenue</title></head><body><h1>2026 Individual Income Tax</h1>"
        "<p>For tax year 2026 the flat income tax rate is 5.19% and the standard deduction for a single filer is $15,000.</p></body></html>")


class FakeWeb:
    def __call__(self, url, headers=None):
        if url.startswith(BRAVE_SEARCH):
            body = {"web": {"results": [{"title": "Georgia income tax", "url": "https://dor.georgia.gov/rates", "description": "Rates"}]}}
            return 200, "application/json", json.dumps(body).encode(), url
        return 200, "text/html; charset=utf-8", PAGE.encode(), url


def test_a_looked_up_table_must_quote_every_number_and_waits_in_review(tables, local_model):
    store, service = tables
    lookup = TaxTableService(store, WebLookup(store, FakeWeb(), key="k"))
    config = ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning")
    step = lambda tool, arguments: {"action": "call_tool", "tool": tool, "arguments_json": json.dumps(arguments), "note": None}  # noqa: E731
    quote = [{"result_id": "r1", "text": "the flat income tax rate is 5.19% and the standard deduction for a single filer is $15,000"}]
    wrong = {"quotes": quote, "standard_deduction": "12,000", "brackets": [{"starts_at": "0", "rate": "5.19%"}]}
    right = {"quotes": quote, "standard_deduction": "15,000", "brackets": [{"starts_at": "0", "rate": "5.19%"}]}
    local_model["outputs"] = [step("web_search", {"query": "Georgia 2026 income tax rate standard deduction"}), step("open_result", {"result_id": "r1"}),
                              step("propose_tax_table", wrong), step("propose_tax_table", right)]
    run_id = lookup.enqueue("GA", 2026, "single", config)
    lookup.run(run_id, config, Work("inference", "tax_table_lookup", "Looking up a tax table", sink=store.record_model_run))
    run = lookup.get(run_id)
    assert run["status"] == "succeeded" and run["result"]["tool_calls"] == 4
    refused = json.loads(local_model["requests"][-1]["messages"][-1]["content"].split("\n", 1)[1])
    assert "The standard deduction (12,000) is not printed in your quotes." in refused["error"]
    [table] = service.list("proposed")
    assert (table["jurisdiction"], table["standard_deduction_minor"], table["brackets"], table["sources"][0]["url"]) == (
        "GA", 1500000, [{"from_minor": 0, "rate_bp": 519, "display": {"from": "0.00 USD", "rate": "5.19%"}}], "https://dor.georgia.gov/rates")
    with pytest.raises(ValueError, match="already waiting"):
        lookup.enqueue("GA", 2026, "single", config)
    service.review(table["id"], "rejected")
    assert service.needed(2026, "GA", "single") == ["US", "GA"]  # A rejected table can be looked up again.
    with pytest.raises(ValueError, match="web search"):
        TaxTableService(store, WebLookup(store, FakeWeb(), key="")).enqueue("GA", 2026, "single", config)


def test_bracket_order_and_first_bracket_are_checked(tables):
    store, service = tables
    tools = TaxTableTools(service, None, "US", 2026, "single")
    tools.pages["r1"] = {"url": "https://irs.example", "title": "IRS", "text": "10% 0 12% 11,925 standard deduction 15,000"}
    from home_manager.household.tax_tables import ProposeInput
    quote = [{"result_id": "r1", "text": "10% 0 12% 11,925 standard deduction 15,000"}]
    with pytest.raises(ValueError, match="lowest first"):
        tools.propose_tax_table(ProposeInput.model_validate({"quotes": quote, "standard_deduction": "15,000",
                                                             "brackets": [{"starts_at": "0", "rate": "12%"}, {"starts_at": "0", "rate": "10%"}]}))
    with pytest.raises(ValueError, match="start at 0"):
        tools.propose_tax_table(ProposeInput.model_validate({"quotes": quote, "standard_deduction": "15,000",
                                                             "brackets": [{"starts_at": "11,925", "rate": "12%"}]}))
