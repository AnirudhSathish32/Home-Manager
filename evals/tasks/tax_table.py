"""Tax table lookup (docs/evals.md, task 14, household/tax_tables.py): one jurisdiction's income tax brackets and standard
deduction for a year, quoted from recorded pages. The figures are made up, not any year's real ones.

Graded on the proposed table: the standard deduction and every bracket exactly, plus the FICA figures for federal.
Each case's web also holds the year before with different figures; a year whose figures are not published must
give no proposal.
"""

from home_manager.household.tax_tables import TAX_TABLE_VERSION, TaxTables, TaxTableService

from .common import make_case, result
from .web import html, lookup, scratch_store

NAME, ROLE, VERSION, PROMPT_VERSION, MULTI_STEP = "tax_table", "reasoning", "tax-table-v1", TAX_TABLE_VERSION, True
YEAR = 2026
# (code, state name, filing status, standard deduction, [(from, rate)], prior year's deduction, publishes YEAR)
STATES = [
    ("GA", "Georgia", "single", "15,000", [("0", "5.19%")], "12,000", True),
    ("CO", "Colorado", "single", "15,750", [("0", "4.25%")], "14,600", True),
    ("NC", "North Carolina", "single", "12,750", [("0", "3.99%")], "12,750", True),
    ("UT", "Utah", "married_joint", "31,500", [("0", "4.50%")], "29,200", True),
    ("VA", "Virginia", "single", "8,750", [("0", "2%"), ("3,000", "3%"), ("5,000", "5%"), ("17,000", "5.75%")], "8,500", True),
    ("MO", "Missouri", "head_of_household", "23,625", [("0", "2%"), ("1,313", "3%"), ("2,626", "4%"), ("8,000", "4.7%")], "22,500", True),
    ("NM", "New Mexico", "single", "15,750", [("0", "1.5%"), ("5,500", "3.2%"), ("16,500", "4.3%"), ("33,500", "4.7%"), ("66,500", "4.9%")], "14,600", True),
    ("ID", "Idaho", "single", "15,750", [("0", "5.3%")], "14,600", False),
]
FEDERAL = [("single", "15,750", [("0", "10%"), ("11,925", "12%"), ("48,475", "22%"), ("103,350", "24%")], "200,000"),
           ("married_joint", "31,500", [("0", "10%"), ("23,850", "12%"), ("96,950", "22%"), ("206,700", "24%")], "250,000")]
WORDS = {"single": "single filers", "married_joint": "married couples filing jointly", "head_of_household": "heads of household"}


def table_text(year, status, deduction, brackets):
    rates = "; ".join(f"{rate} on taxable income over ${start}" if start != "0" else f"{rate} on taxable income from $0" for start, rate in brackets)
    return [f"For tax year {year}, the standard deduction for {WORDS[status]} is ${deduction}.", f"Tax rates for {year} ({WORDS[status]}): {rates}."]


def money(text):
    return int(text.replace(",", "")) * 100


def bp(rate):
    return round(float(rate.rstrip("%")) * 100)


def cases():
    out = []
    for code, name, status, deduction, brackets, prior, published in STATES:
        slug = name.lower().replace(" ", "")
        current = (f"{name} {YEAR} individual income tax rates", f"https://tax.{slug}.example/{YEAR}-rates", f"{YEAR} rates and standard deduction")
        older = (f"{name} {YEAR - 1} individual income tax rates", f"https://tax.{slug}.example/{YEAR - 1}-rates", f"{YEAR - 1} rates")
        pages = {older[1]: html(older[0], f"{name} Department of Revenue", *table_text(YEAR - 1, status, prior, brackets[:1] if len(brackets) == 1 else brackets[:-1]))}
        results = [older]
        if published:
            pages[current[1]] = html(current[0], f"{name} Department of Revenue", *table_text(YEAR, status, deduction, brackets))
            results.insert(0, current)
        expected = {"standard_deduction_minor": money(deduction), "brackets": [{"from_minor": money(start), "rate_bp": bp(rate)} for start, rate in brackets]}
        out.append(make_case(NAME, {"jurisdiction": code, "year": YEAR, "filing_status": status,
                                    "web": {"results": [{"title": title, "url": url, "description": snippet} for title, url, snippet in results], "pages": pages}},
                             {"table": expected if published else None}, ["state", *([] if published else ["not_published"])]))
    for status, deduction, brackets, threshold in FEDERAL:
        url = f"https://www.irs.example/newsroom/{YEAR}-adjustments-{status}"
        fica = f"https://www.ssa.example/oact/cola/{YEAR}"
        pages = {url: html(f"IRS provides tax inflation adjustments for tax year {YEAR}", *table_text(YEAR, status, deduction, brackets)),
                 fica: html(f"{YEAR} Social Security and Medicare", f"For {YEAR}, the Social Security tax rate for employees is 6.2% on earnings up to $184,500.",
                            "The Medicare tax rate for employees is 1.45% on all earnings.",
                            f"An Additional Medicare Tax of 0.9% applies to wages above ${threshold} for {WORDS[status]}.")}
        results = [{"title": f"IRS tax inflation adjustments for tax year {YEAR}", "url": url, "description": "Standard deduction and brackets"},
                   {"title": f"{YEAR} Social Security wage base and Medicare rates", "url": fica, "description": "Contribution and benefit base"}]
        expected = {"standard_deduction_minor": money(deduction), "brackets": [{"from_minor": money(start), "rate_bp": bp(rate)} for start, rate in brackets],
                    "ss_rate_bp": 620, "ss_wage_base_minor": money("184,500"), "medicare_rate_bp": 145, "additional_medicare_rate_bp": 90,
                    "additional_medicare_threshold_minor": money(threshold)}
        out.append(make_case(NAME, {"jurisdiction": "US", "year": YEAR, "filing_status": status, "web": {"results": results, "pages": pages}},
                             {"table": expected}, ["federal"]))
    return out


def run(case, config, work):
    given = case["input"]
    with scratch_store() as store:
        service = TaxTableService(store, lookup(store, given["web"]))
        outcome = service.agent(given["jurisdiction"], given["year"], given["filing_status"], config, work, "eval")
        table = TaxTables(store).get(outcome["tax_table_id"]) if outcome.get("tax_table_id") else None
    keys = ("standard_deduction_minor", "ss_rate_bp", "ss_wage_base_minor", "medicare_rate_bp", "additional_medicare_rate_bp",
            "additional_medicare_threshold_minor")
    return {"table": {**{key: table[key] for key in keys}, "brackets": [{"from_minor": item["from_minor"], "rate_bp": item["rate_bp"]}
                                                                        for item in table["brackets"]]} if table else None,
            "note": outcome.get("note"), "tool_calls": outcome.get("tool_calls")}


def grade(case, output):
    want, got = case["expected"]["table"], output["table"]
    if want is None:
        return result({"no_proposal": got is None}, ["no_proposal"])
    if got is None:
        return result({"proposed": False}, ["proposed"])
    fields = [key for key in want if key != "brackets"]
    wrong = [key for key in fields if got.get(key) != want[key]]
    checks = {"proposed": True, "brackets": got["brackets"] == want["brackets"], "figures": not wrong,
              "fields_right": round((len(fields) - len(wrong) + (got["brackets"] == want["brackets"])) / (len(fields) + 1), 4),
              "money_errors": len(wrong) + (got["brackets"] != want["brackets"])}
    return result(checks, ["brackets", "figures"], ["fields_right"])
