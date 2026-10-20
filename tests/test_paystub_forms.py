"""Pay stub forms (specs/document-forms): this period never takes a year-to-date or annual amount (FR-22 – FR-24)."""

from contextlib import contextmanager
from decimal import Decimal
import json

import pytest

from document_forms_fixtures import (
    P_EXTRAS,
    P_LINES,
    P_NET,
    P_TABLE_HEADING,
    at,
    cite,
    flat_label,
    number_of,
    p_flat,
    p_header,
    p_table,
    paystub_classification,
    paystub_summary,
    section_line,
    stored_identifiers,
    uncited,
    value,
)
from home_manager.documents.extraction import DETAILS_FAILED, EXTRACTION_VERSION, GUARD_RULES, line_amounts, printed_header
from home_manager.finance import traces
from test_extraction import extract, transcribe


@contextmanager
def read_stub(tmp_path, local_model, lines, replies, tables=None):
    """Transcribe lines, extract them with replies keyed by schema name, and yield (manager, run, record)."""
    manager, doc, parse_id = transcribe(tmp_path, local_model, lines, tables)
    try:
        local_model["by_schema"] = replies
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded", run["error"]
        record = manager.ledger.record("income_record", run["publication"]["id"]) if run["publication"] else None
        yield manager, run, record
    finally:
        manager.close()


def ytd_value(lines, name, amount):
    """A this-period value the faulty model copied from the YEAR TO DATE section's line."""
    number = section_line(lines, "YEAR TO DATE", name)
    return {"value": amount, "status": "proposed", "evidence": at(lines, number)}


def all_ytd_replies(lines):
    """20-e: every this-period value (gross, net and all six lines) copied from the YEAR TO DATE section. They add up."""
    rows = []
    for name, group, category, _, ytd in P_LINES:
        number = section_line(lines, "YEAR TO DATE", flat_label(name))
        rows.append({"description": name, "group": group, "category": category, "current": ytd, "ytd": ytd, "evidence": at(lines, number)})
    summary = paystub_summary(lines, gross_pay=ytd_value(lines, "GROSS PAY", "32,500.00"), gross_pay_ytd=ytd_value(lines, "GROSS PAY", "32,500.00"),
                              net_pay=ytd_value(lines, "NET PAY", P_NET[1]), net_pay_ytd=ytd_value(lines, "NET PAY", P_NET[1]))
    return {"Classification": [paystub_classification(lines)], "PaystubSummary": [summary], "PayLines": [{"lines": rows}]}


def period_value(lines, name, amount, section="THIS PERIOD"):
    number = section_line(lines, section, name)
    return {"value": amount, "status": "proposed", "evidence": at(lines, number)}


def correct_rows(lines, first=0):
    """P-flat's lines (from fixture P's line first: 20-b prints Regular apart) read correctly: this period from the THIS
    PERIOD section, year to date from YEAR TO DATE."""
    rows = []
    for name, group, category, _, _ in P_LINES[first:]:
        this, year = (section_line(lines, section, flat_label(name)) for section in ("THIS PERIOD", "YEAR TO DATE"))
        rows.append({"description": name, "group": group, "category": category, "current": lines[this - 1].split()[-1],
                     "ytd": lines[year - 1].split()[-1], "evidence": at(lines, this) + at(lines, year)})
    return rows


def correct_replies(lines, rows=None, **summary):
    """P-flat read correctly, with summary fields replaced by summary."""
    gross = (lines[section_line(lines, "THIS PERIOD", "GROSS PAY") - 1].split()[-1], lines[section_line(lines, "YEAR TO DATE", "GROSS PAY") - 1].split()[-1])
    net = (lines[section_line(lines, "THIS PERIOD", "NET PAY") - 1].split()[-1], lines[section_line(lines, "YEAR TO DATE", "NET PAY") - 1].split()[-1])
    fields = {"gross_pay": period_value(lines, "GROSS PAY", gross[0]), "gross_pay_ytd": period_value(lines, "GROSS PAY", gross[1], "YEAR TO DATE"),
              "net_pay": period_value(lines, "NET PAY", net[0]), "net_pay_ytd": period_value(lines, "NET PAY", net[1], "YEAR TO DATE")}
    return {"Classification": [paystub_classification(lines)], "PaystubSummary": [paystub_summary(lines, **{**fields, **summary})],
            "PayLines": [{"lines": correct_rows(lines) if rows is None else rows}]}


def guard_issues(record):
    return [issue for issue in record["issues"] if any(rule in issue for rule in GUARD_RULES.values()) or "equals its year to date" in issue]


def label(lines, text, line):
    return {"text": text, "evidence": cite(lines, line, text)}


def test_sc20_a_a_year_to_date_heading_is_never_this_period(tmp_path, local_model):
    lines = p_flat()
    gross = {**ytd_value(lines, "GROSS PAY", "32,500.00"), "column_heading": label(lines, "YEAR TO DATE", "YEAR TO DATE")}
    with read_stub(tmp_path, local_model, lines, correct_replies(lines, gross_pay=gross)) as (manager, _run, record):
        assert record["gross_pay_minor"] is None and record["review_status"] == "needs_review"
        [issue] = guard_issues(record)
        line = f"line-{section_line(lines, 'YEAR TO DATE', 'GROSS PAY')}"
        assert issue.startswith("Gross pay 32,500.00 USD reads as year to date or annual") and line in issue
        with manager.store.connection() as db:
            details = json.loads(db.execute("SELECT details_json FROM income_records").fetchone()[0])
        assert details["guards"]["gross_pay"]["rule"] == "a"
        heading = details["labels"]["gross_pay"]["column_heading"]
        assert heading["text"] == "YEAR TO DATE" and all(quote in lines[int(id.split("-")[1]) - 1] for id, quote in
                                                          zip(heading["locator"]["line_ids"], heading["locator"]["quotes"]))  # C-cite


def test_sc20_b_larger_than_year_to_date(tmp_path, local_model):
    lines = p_flat(regular_unlabelled=True)
    regular = number_of(lines, "REGULAR")
    swapped = {"description": "Regular", "group": "earnings", "category": "regular_pay", "current": "32,500.00", "ytd": "2,500.00",
               "evidence": at(lines, regular + 2) + at(lines, regular + 1)}
    with read_stub(tmp_path, local_model, lines, correct_replies(lines, rows=[swapped, *correct_rows(lines, 1)])) as (_, _run, record):
        assert record["lines"][0]["current_minor"] is None and record["review_status"] == "needs_review"
        [issue] = guard_issues(record)
        assert issue.startswith("This period: Regular 32,500.00 USD is larger than its year to date 2,500.00 USD")


def test_sc20_c_one_amount_equal_to_year_to_date_mid_year_is_kept(tmp_path, local_model):
    """FR-22 (c), amended 2026-10-19: one amount equal to its year to date mid-year is kept (a benefit can start then);
    only every amount equal is year to date copied into this period (test_sc20_e_all_year_to_date...)."""
    lines = p_flat()
    copied = ytd_value(lines, "GROSS PAY", "32,500.00")
    with read_stub(tmp_path, local_model, lines, correct_replies(lines, gross_pay=copied, gross_pay_ytd=copied)) as (_, _run, record):
        assert record["gross_pay_minor"] == 3250000 and guard_issues(record) == []


def test_fr22_c_mid_year_clears_equal_amounts_only_when_every_amount_equals_its_year_to_date():
    """Benefits starting with this paycheck equal their year to date while pay doesn't: kept. Every amount equal (year
    to date copied throughout, D14): each is left out, with rule (c)."""
    from home_manager.documents.extraction import this_period_guards
    record = {"currency": "USD", "period_start": "2026-09-19", "pay_date": "2026-10-09", "pay_frequency": 26}

    def slots(*pairs):
        return [{"key": f"line:{index}", "label": f"This period: line {index}", "value": value, "ytd": ytd, "words": [], "line_ids": ["line-1"],
                 "clear": lambda: None} for index, (value, ytd) in enumerate(pairs)]
    issues = []
    assert this_period_guards(record, slots((400000, 840000), (600, 600), (1200, 1200)), issues) == {} and issues == []
    fired = this_period_guards(record, slots((840000, 840000), (600, 600)), issues)
    assert [result["rule"] for result in fired.values()] == ["c", "c"] and all("mid-year" in issue for issue in issues)


def test_sc20_d_an_annual_salary_is_never_gross_pay(tmp_path, local_model):
    lines = p_flat(extra=["ANNUAL SALARY 65,000.00"])
    salary = {**value(lines, "65,000.00", "ANNUAL SALARY 65,000.00", "65,000.00"), "row_label": label(lines, "ANNUAL SALARY", "ANNUAL SALARY 65,000.00")}
    with read_stub(tmp_path, local_model, lines, correct_replies(lines, gross_pay=salary)) as (_, _run, record):
        assert record["gross_pay_minor"] is None and record["review_status"] == "needs_review"
        [issue] = guard_issues(record)
        assert issue.startswith("Gross pay 65,000.00 USD reads as year to date or annual") and "annual" in issue


def test_sc20_e_all_year_to_date_never_counts_as_this_paycheck(tmp_path, local_model):
    """The reported defect (D14), reproduced through the public extraction entry point. The stub uses only the fields
    that existed before document forms, so the same test runs on the pre-change code, where it fails: the stub is
    verified with gross pay 32,500.00."""
    lines = p_flat()
    with read_stub(tmp_path, local_model, lines, all_ytd_replies(lines)) as (manager, run, record):
        print("characterization:", record["review_status"], record["gross_pay_minor"], record["issues"])
        assert record["review_status"] == "needs_review"
        assert record["gross_pay_minor"] is None
        # Every this-period value is null and ambiguous with its reason; the year-to-date checks still pass.
        assert record["net_pay_minor"] is None and all(line["current_minor"] is None for line in record["lines"])
        assert len(guard_issues(record)) == 8 and all("mid-year" in issue for issue in guard_issues(record))
        assert record["gross_pay_ytd_minor"] == 3250000 and run["result"]["normalized"]["cross_checks"] == 2
        with manager.store.connection() as db:
            statuses = [json.loads(row[0])["current_status"] for row in db.execute("SELECT details_json FROM income_lines ORDER BY position")]
        assert statuses == ["ambiguous"] * 6


def test_sc20_e_corrections_clear_their_reasons_and_outlive_reading_again(tmp_path, local_model):
    """FR-23 follow-on: correcting gross and net clears their reasons and leaves the lines'; reading again with the same
    faulty stub keeps the corrections and raises the lines' reasons again. A line correction clears its own, and undo
    puts it back."""
    lines = p_flat()
    manager, doc, parse_id = transcribe(tmp_path, local_model, lines)
    try:
        local_model["by_schema"] = all_ytd_replies(lines)
        run = extract(manager, doc, parse_id)
        income_id = run["publication"]["id"]
        record = manager.ledger.correct("income_record", income_id, {"gross_pay": "2500.00", "net_pay": "1912.34"})
        assert not any(issue.startswith(("Gross pay", "Net pay")) for issue in record["issues"])
        assert len([issue for issue in record["issues"] if issue.startswith("This period:")]) == 6
        assert record["review_status"] == "needs_review"
        local_model["by_schema"] = all_ytd_replies(lines)
        again = extract(manager, doc, parse_id, force=True)
        assert again["id"] != run["id"] and again["publication"]["id"] == income_id
        record = manager.ledger.record("income_record", income_id)
        assert (record["gross_pay_minor"], record["net_pay_minor"]) == (250000, 191234)
        assert not any(issue.startswith(("Gross pay", "Net pay")) for issue in record["issues"])
        assert len([issue for issue in record["issues"] if issue.startswith("This period:")]) == 6
        corrected = manager.ledger.correct_income_line(income_id, 1, {"current": "2500.00"})
        assert not any(issue.startswith("This period: Regular") for issue in corrected["issues"])
        assert corrected["lines"][0]["current_minor"] == 250000
        undone = manager.ledger.undo_corrections("income_record", income_id, corrected["correction_ids"])
        assert any(issue.startswith("This period: Regular") for issue in undone["issues"]) and undone["lines"][0]["current_minor"] is None
    finally:
        manager.close()


def p_table_replies(lines, gross=None, hours=None, rate=None, **details):
    """P-table read correctly: the summary's money cited from its table rows, lines classified by their rows (Regular
    with hours and rate when given), and the summary's details."""
    def row(text):
        return number_of(lines, text)
    summary = {"gross_pay": gross or {"value": "2,500.00", "status": "proposed", "evidence": at(lines, row("Gross pay |"), "2,500.00")},
               "gross_pay_ytd": {"value": "32,500.00", "status": "proposed", "evidence": at(lines, row("Gross pay |"), "32,500.00")},
               "net_pay": {"value": "1,912.34", "status": "proposed", "evidence": at(lines, row("Net pay |"), "1,912.34")},
               "net_pay_ytd": {"value": "24,860.42", "status": "proposed", "evidence": at(lines, row("Net pay |"), "24,860.42")}}
    classes = [{"description": name, "group": group, "category": category, "evidence": at(lines, row(f"{name} " if name == "Regular" else f"{name} |")),
                **({"hours": hours, "rate": rate} if name == "Regular" else {})}
               for name, group, category, _, _ in P_LINES]
    return {"Classification": [paystub_classification(lines)], "PaystubSummary": [paystub_summary(lines, **summary, **details)],
            "PayRowClasses": [{"lines": classes}], "PayLines": [{"lines": []}] * 3}


def p_details(lines, splits=(("1234", "1,500.00", "DIRECT DEPOSIT CHECKING"), ("9876", "412.34", "SAVINGS ****9876"))):
    """Fixture P's printed details: the PTO balance with its label, and the deposit splits."""
    pto = "PTO BALANCE 56.00 HRS"
    return {"pto_balance": {**value(lines, "56.00 HRS", pto, "56.00 HRS"), "row_label": {"text": "PTO BALANCE", "evidence": cite(lines, pto, "PTO BALANCE")}},
            "deposit_splits": [{"last_four": four, "amount": amount, "evidence": cite(lines, line)} for four, amount, line in splits]}


def test_sc21_pay_stub_fields_and_checks(tmp_path, local_model):
    lines, tables = p_table()
    replies = p_table_replies(lines, hours="80.00", rate="31.25", **p_details(lines))
    with read_stub(tmp_path, local_model, lines, replies, tables) as (manager, run, record):
        assert record["review_status"] == "verified", record["issues"]
        assert run["result"]["normalized"]["cross_checks"] == 6  # Earnings and net, both columns, plus hours × rate and the splits.
        with manager.store.connection() as db:
            details = json.loads(db.execute("SELECT details_json FROM income_records").fetchone()[0])
            lines_details = [(row[0], row[1], json.loads(row[2])) for row in db.execute(
                "SELECT current_minor,ytd_minor,details_json FROM income_lines ORDER BY position")]
            assert tuple(db.execute("SELECT json_type(details_json,'$.deposit_splits[0].minor'),json_type(details_json,'$.pto_balance.text') "
                                    "FROM income_records").fetchone()) == ("integer", "text")  # C-money
            assert stored_identifiers(db, ("445566", "XXX-XX-1234")) == []  # C-ids
        current, ytd, regular = lines_details[0]
        assert (current, ytd, regular["hours"]["text"], regular["rate"]["text"]) == (250000, 3250000, "80.00", "31.25")
        assert (details["pto_balance"]["text"], details["pto_balance"]["unit"], details["pto_balance"]["label"]["text"]) == ("56.00", "hrs", "PTO BALANCE")
        assert [(split["last_four"], split["minor"]) for split in details["deposit_splits"]] == [("1234", 150000), ("9876", 41234)]
        # Every amount's printed row label and column heading, each a substring of its own line (C-cite).
        assert set(details["labels"]) == {"gross_pay", "gross_pay_ytd", "net_pay", "net_pay_ytd"}
        found = [label for pair in details["labels"].values() for label in pair.values()]
        found += [line[2][key] for line in lines_details for key in ("current_row_label", "current_column_heading", "ytd_row_label", "ytd_column_heading")]
        assert len(found) == 8 + 6 * 4 and all(uncited(label, lines) == [] for label in found)
        assert [details["labels"]["net_pay_ytd"][key]["text"] for key in ("row_label", "column_heading")] == ["Net pay", "Year to date"]
        assert all(uncited(item, lines) == [] for item in [details["pto_balance"], *details["deposit_splits"], regular["hours"]])


def test_sc21_the_hours_and_deposit_traces(tmp_path, local_model):
    """Checkpoint 4: hours × rate gives 2,500.00 and the deposits 1,912.34, each reconciling, inputs extracted from their
    lines; each trace's result is the record's check figure."""
    lines, tables = p_table()
    with read_stub(tmp_path, local_model, lines, p_table_replies(lines, hours="80.00", rate="31.25", **p_details(lines)), tables) as (manager, _, record):
        shown = {check["name"]: check for check in record["checks"]}
        hours = traces.trace(manager.store, shown["hours:1"]["figure"]["trace"], manager)
        assert (hours["result"]["decimal"], hours["compared_with"]["decimal"], hours["reconciles"]) == ("2500.00", "2500.00", True)
        regular = number_of(lines, "Regular 80.00")
        assert all(item["provenance"]["kind"] == "extracted" and item["provenance"]["line_ids"] == [f"line-{regular}"] for item in hours["inputs"])
        deposits = traces.trace(manager.store, shown["deposits"]["figure"]["trace"], manager)
        assert (deposits["result"]["decimal"], deposits["reconciles"]) == ("1912.34", True)
        assert [item["value"]["decimal"] for item in deposits["inputs"]] == ["1500.00", "412.34", "1912.34"]
        assert all(trace["result"]["minor"] == shown[name]["figure"]["minor"] for name, trace in (("hours:1", hours), ("deposits", deposits)))


def test_sc21_a_a_mismatching_rate_goes_to_review(tmp_path, local_model):
    lines, tables = p_table(regular="Regular 80.00 h @ 31.00")
    with read_stub(tmp_path, local_model, lines, p_table_replies(lines, hours="80.00", rate="31.00", **p_details(lines)), tables) as (manager, _run, record):
        assert record["review_status"] == "needs_review"
        [issue] = [issue for issue in record["issues"] if "hours ×" in issue]
        assert issue.startswith("This period: Regular 80.00 hours × 31.00 = 2,480.00 USD, not the printed 2,500.00 USD")
        trace = traces.trace(manager.store, next(check for check in record["checks"] if check["name"] == "hours:1")["figure"]["trace"], manager)
        assert (trace["result"]["decimal"], trace["reconciles"]) == ("2480.00", False)


def test_sc21_b_a_salaried_line_has_no_hours_check(tmp_path, local_model):
    lines, tables = p_table(regular="Regular")
    with read_stub(tmp_path, local_model, lines, p_table_replies(lines, **p_details(lines)), tables) as (_, run, record):
        assert record["review_status"] == "verified", record["issues"]
        assert run["result"]["normalized"]["cross_checks"] == 5 and "hours" not in run["result"]["normalized"]["lines"][0]["details"]


def test_sc21_c_a_split_without_an_amount_skips_the_split_check(tmp_path, local_model):
    lines, tables = p_table(extras=["PTO BALANCE 56.00 HRS", "DIRECT DEPOSIT CHECKING ****1234 1,500.00", "SAVINGS ****9876"])
    replies = p_table_replies(lines, hours="80.00", rate="31.25", **p_details(lines, splits=(("1234", "1,500.00", "DIRECT DEPOSIT CHECKING"),
                                                                                            ("9876", None, "SAVINGS ****9876"))))
    with read_stub(tmp_path, local_model, lines, replies, tables) as (_, run, record):
        assert record["review_status"] == "verified", record["issues"]
        assert run["result"]["normalized"]["cross_checks"] == 5 and not any("Deposit splits" in issue for issue in record["issues"])


def test_sc25_pay_stub_identifiers_are_never_stored(tmp_path, local_model):
    """The stub returns more than four digits for a split and quotes the SSN and employee ID in free-text details."""
    lines, tables = p_table()
    details = p_details(lines, splits=(("000000001234", "1,500.00", "DIRECT DEPOSIT CHECKING"), ("9876", "412.34", "SAVINGS ****9876")))
    details["pto_balance"]["row_label"] = {"text": "EMPLOYEE ID 445566", "evidence": cite(lines, "EMPLOYEE ID 445566")}
    details["sick_balance"] = {**value(lines, "1234", "SSN XXX-XX-1234", "SSN XXX-XX-1234"),
                               "row_label": {"text": "SSN XXX-XX-1234", "evidence": cite(lines, "SSN XXX-XX-1234")}}
    with read_stub(tmp_path, local_model, lines, p_table_replies(lines, hours="80.00", rate="31.25", **details), tables) as (manager, _run, record):
        with manager.store.connection() as db:
            assert stored_identifiers(db) == []
            stored = json.loads(db.execute("SELECT details_json FROM income_records").fetchone()[0])
        assert [split["last_four"] for split in stored["deposit_splits"]] == ["1234", "9876"]
        assert stored["pto_balance"]["label"]["text"] == "EMPLOYEE ID **5566"
        assert "Digits of an identifier were dropped from Deposit split 1 account." in record["issues"]
        assert "Digits of an identifier were dropped from Paid time off balance label." in record["issues"]


def test_fallback_pay_stub_details_that_fail_twice_are_left_out(tmp_path, local_model):
    """FR-14: the summary's new fields fail twice (a split cites a quote that isn't in its line); the stub is published
    with its usual fields, no new field of any kind (none partially stored), and the reason."""
    lines, tables = p_table()
    details = p_details(lines)
    details["deposit_splits"][0]["evidence"] = [{"line_id": details["deposit_splits"][0]["evidence"][0]["line_id"], "quote": "CHECKING 9999 1,500.00"}]
    replies = p_table_replies(lines, hours="80.00", rate="31.25", **details)
    replies["PaystubSummary"] *= 2
    with read_stub(tmp_path, local_model, lines, replies, tables) as (manager, run, record):
        assert record["review_status"] == "needs_review" and DETAILS_FAILED in record["issues"]
        assert (record["gross_pay_minor"], record["net_pay_minor"], len(record["lines"])) == (250000, 191234, 6)
        with manager.store.connection() as db:
            assert db.execute("SELECT details_json FROM income_records").fetchone()[0] is None
            assert {row[0] for row in db.execute("SELECT details_json FROM income_lines")} == {None}
        assert len([request for request in local_model["requests"] if request["response_format"]["json_schema"]["name"] == "PaystubSummary"]) == 2


def test_fallback_a_shared_field_that_fails_twice_still_fails_the_stub(tmp_path, local_model):
    """Variant 8a for pay stubs: the base fields fail twice, so nothing is published, as today."""
    lines, tables = p_table()
    invented = {"value": "2,600.00", "status": "proposed", "evidence": at(lines, number_of(lines, "Gross pay |"))}
    replies = p_table_replies(lines, gross=invented)
    replies["PaystubSummary"] *= 2
    manager, doc, parse_id = transcribe(tmp_path, local_model, lines, tables)
    try:
        local_model["by_schema"] = replies
        run = extract(manager, doc, parse_id)
        assert run["status"] == "failed" and run["publication"] is None
        with manager.store.connection() as db:
            assert db.execute("SELECT count(*) FROM income_records").fetchone()[0] == 0
    finally:
        manager.close()


def test_sc20_f_table_cells_are_copied_from_this_period(tmp_path, local_model):
    lines, tables = p_table()
    ytd_cell = {"value": "32,500.00", "status": "proposed", "evidence": at(lines, number_of(lines, "Gross pay |"), "32,500.00")}
    with read_stub(tmp_path, local_model, lines, p_table_replies(lines, gross=ytd_cell), tables) as (_, run, record):
        assert record["gross_pay_minor"] == 250000 and guard_issues(record) == []
        assert record["review_status"] == "verified", record["issues"]
        labels = run["result"]["normalized"]["details"]["labels"]["gross_pay"]
        assert (labels["row_label"]["text"], labels["column_heading"]["text"]) == ("Gross pay", "This period")
        assert labels["column_heading"]["locator"]["line_ids"] == [f"line-{number_of(lines, P_TABLE_HEADING)}"]


def test_sc20_g_the_first_paycheck_of_the_year_equals_its_year_to_date(tmp_path, local_model):
    lines = p_flat(period=("2026-01-01", "2026-01-14"), pay_date="2026-01-16", ytd_equal=True)
    with read_stub(tmp_path, local_model, lines, correct_replies(lines)) as (_, _run, record):
        assert guard_issues(record) == [] and record["review_status"] == "verified", record["issues"]
        assert record["gross_pay_minor"] == 250000


def test_sc20_h_equality_with_no_period_goes_to_review(tmp_path, local_model):
    """Every amount equal, each printed once (its year-to-date line), with the period unknown: kept, with the reason.
    Equal amounts the stub prints in both sections need no reason (test_sc20_g_a_new_jobs_first_paycheck...)."""
    lines = p_flat(period=None, frequency=None)
    with read_stub(tmp_path, local_model, lines, all_ytd_replies(lines)) as (_, _run, record):
        assert record["review_status"] == "needs_review" and record["gross_pay_minor"] == 3250000  # Kept, with the reason.
        assert any(issue.startswith("Gross pay 32,500.00 USD equals its year to date 32,500.00 USD and the pay period isn't known")
                   for issue in record["issues"])


def test_sc20_h_equality_printed_in_both_sections_with_no_period_counts(tmp_path, local_model):
    lines = p_flat(period=None, frequency=None, ytd_equal=True)
    with read_stub(tmp_path, local_model, lines, correct_replies(lines)) as (_, _run, record):
        assert guard_issues(record) == [] and record["review_status"] == "verified", record["issues"]


def test_sc20_g_a_new_jobs_first_paycheck_mid_year_keeps_this_period(tmp_path, local_model):
    """The user's report (2026-10-19): a new job's first paycheck mid-year prints every year-to-date amount equal to this
    period's. The stub prints each amount in both sections, so it isn't year to date copied (FR-22 c): all kept."""
    lines = p_flat(ytd_equal=True)
    with read_stub(tmp_path, local_model, lines, correct_replies(lines)) as (_, _run, record):
        assert guard_issues(record) == [] and record["review_status"] == "verified", record["issues"]
        assert (record["gross_pay_minor"], record["gross_pay_ytd_minor"], record["net_pay_minor"]) == (250000, 250000, 191234)
        assert all(line["current_minor"] is not None and line["current_minor"] == line["ytd_minor"] for line in record["lines"])


SIDE_FIRST = ["SYNTH WORKS", "EARNINGS STATEMENT", "PAY DATE 2026-07-03", "PAY PERIOD 2026-06-15 TO 2026-06-28", "CURRENCY USD",
              "DESCRIPTION CURRENT YTD", "REGULAR 2,500.00 2,500.00", "FEDERAL INCOME TAX 250.00 250.00",
              "GROSS PAY 2,500.00 2,500.00", "NET PAY 2,250.00 2,250.00"]


def test_a_new_jobs_first_paycheck_side_by_side_keeps_this_period(tmp_path, local_model):
    """The same first paycheck photographed with both columns on each line: every amount is printed twice, so kept."""
    lines = SIDE_FIRST
    rows = [{"description": name, "group": group, "category": category, "current": amount, "ytd": amount, "evidence": at(lines, number_of(lines, text))}
            for name, group, category, text, amount in (("Regular", "earnings", "regular_pay", "REGULAR", "2,500.00"),
                                                         ("Federal income tax", "tax", "federal_income_tax", "FEDERAL", "250.00"))]
    summary = {name: side_amount(lines, text, amount) for name, text, amount in (
        ("gross_pay", "GROSS PAY", "2,500.00"), ("gross_pay_ytd", "GROSS PAY", "2,500.00"),
        ("net_pay", "NET PAY", "2,250.00"), ("net_pay_ytd", "NET PAY", "2,250.00"))}
    replies = {"Classification": [paystub_classification(lines)], "PaystubSummary": [paystub_summary(lines, **summary)], "PayLines": [{"lines": rows}]}
    with read_stub(tmp_path, local_model, lines, replies) as (_, _run, record):
        assert guard_issues(record) == [] and column_notes(record) == [], record["issues"]
        assert (record["gross_pay_minor"], record["net_pay_minor"]) == (250000, 225000)
        assert stored_lines(record) == [("Regular", 250000, 250000), ("Federal income tax", 25000, 25000)]


SIDE_BY_SIDE = ["SYNTH WORKS","EARNINGS STATEMENT", "PAY DATE 2026-07-03", "PAY PERIOD 2026-06-15 TO 2026-06-28", "CURRENCY USD",
                "DESCRIPTION CURRENT YTD", "REGULAR 2,500.00 32,500.00", "RELOCATION BONUS 5,000.00", "FEDERAL INCOME TAX 250.00 3,250.00",
                "GROSS PAY 2,500.00 37,500.00", "NET PAY 2,250.00 34,250.00"]


SIDE_ROWS = (("Regular", "earnings", "regular_pay", "REGULAR", "2,500.00", "32,500.00"),
             ("Relocation bonus", "earnings", "bonus", "RELOCATION", None, "5,000.00"),
             ("Federal income tax", "tax", "federal_income_tax", "FEDERAL", "250.00", "3,250.00"))
MULTIPLE = "multiple amounts without a validated source"
COLUMN_NOTE = "doesn't match the printed columns"


def side_amount(lines, text, figure):
    return {"value": figure, "status": "proposed", "evidence": at(lines, number_of(lines, text), figure)}


def side_replies(lines, rows=None, changes=None, **summary):
    """SIDE_BY_SIDE read correctly, citing each row's whole line; changes: {description: {key: value}} per pay line,
    summary: summary fields replaced."""
    found = {"gross_pay": side_amount(lines, "GROSS PAY", "2,500.00"), "gross_pay_ytd": side_amount(lines, "GROSS PAY", "37,500.00"),
             "net_pay": side_amount(lines, "NET PAY", "2,250.00"), "net_pay_ytd": side_amount(lines, "NET PAY", "34,250.00")}
    rows = [{"description": name, "group": group, "category": category, "current": current, "ytd": ytd,
             "evidence": at(lines, number_of(lines, text)), **(changes or {}).get(name, {})}
            for name, group, category, text, current, ytd in (rows or SIDE_ROWS)]
    return {"Classification": [paystub_classification(lines)], "PaystubSummary": [paystub_summary(lines, **{**found, **summary})],
            "PayLines": [{"lines": rows}]}


def stored_lines(record):
    return [(line["description"], line["current_minor"], line["ytd_minor"]) for line in record["lines"]]


def column_notes(record):
    return [issue for issue in record["issues"] if COLUMN_NOTE in issue or "prints one amount" in issue]


@pytest.mark.parametrize("text, count", [("PRE-TAX 401K 184.98 2,404.74", 2), ("403(b) 10.00 20.00", 2), ("401(k) 10.00", 1), ("W2 5.00", 1),
                                          ("SECTION 125 150.00 1,800.00", 3), ("SECTION 125 150.00", 2), ("(50.00)", 1), ("50.00CR", 0),
                                          ("REGULAR2,500.00", 0), ("DESCRIPTION CURRENT YTD", 0)])
def test_line_amounts_skip_label_digits(text, count):
    """FR-34 and plan P3: standalone whole numbers count, digits joined to letters don't."""
    assert len(line_amounts(text)) == count


def test_line_amounts_are_absolute_and_in_order():
    assert line_amounts("401K 184.98 2,404.74") == [Decimal("184.98"), Decimal("2404.74")]
    assert line_amounts("ADJUSTMENT (50.00) -3.00") == [Decimal("50.00"), Decimal("3.00")]


@pytest.mark.parametrize("texts, found", [
    (["DESCRIPTION CURRENT YTD"], (["current", "ytd"], True)),
    (["DESCRIPTION HOURS RATE THIS PERIOD YEAR TO DATE"], (["hours", "rate", "current", "ytd"], True)),
    (["DESCRIPTION CURRENT YTD", "YTD CURRENT"], (None, True)),
    (["EARNINGS CURRENT YTD DEDUCTIONS CURRENT YTD"], (None, True)),
    (["CURRENT YTD 2,500.00"], (None, False)),
    (["PAY PERIOD 2026-06-15 TO 2026-06-28", "REGULAR 2,500.00"], (None, False)),
    (["CURRENT ONLY"], (None, False))])
def test_printed_header(texts, found):
    assert printed_header(texts) == found


def test_a_photo_stub_keeps_this_period_beside_year_to_date(tmp_path, local_model):
    """SC-28 (FR-31, FR-32). The user's report (2026-10-19), on synthetic lines: a photographed stub prints each row's
    this-period and year-to-date amounts side by side, and a relocation bonus paid in an earlier period only in year to
    date. The vision model reports no table. The model answers every value correctly, citing each row's line."""
    lines = SIDE_BY_SIDE
    with read_stub(tmp_path, local_model, lines, side_replies(lines)) as (_, _run, record):
        assert (record["gross_pay_minor"], record["net_pay_minor"]) == (250000, 225000)
        assert stored_lines(record) == [("Regular", 250000, 3250000), ("Relocation bonus", None, 500000), ("Federal income tax", 25000, 325000)]
        assert not any(MULTIPLE in issue for issue in record["issues"]) and column_notes(record) == []


def test_sc32_a_label_digits_are_not_amounts_on_a_photo(tmp_path, local_model):
    lines = [*SIDE_BY_SIDE[:9], "401K 184.98 2,404.74", *SIDE_BY_SIDE[9:]]
    rows = (*SIDE_ROWS, ("401k", "pre_tax", "retirement_pretax", "401K", "184.98", "2,404.74"))
    with read_stub(tmp_path, local_model, lines, side_replies(lines, rows)) as (_, _run, record):
        assert stored_lines(record)[-1] == ("401k", 18498, 240474)
        assert not any(MULTIPLE in issue for issue in record["issues"]) and column_notes(record) == []


def p_table_with(row):
    """P-table with one more table row (its cells) after Net pay."""
    lines, tables = p_table()
    at_line = number_of(lines, "Net pay |")
    lines.insert(at_line, " | ".join(row))
    tables[0]["rows"].append({"line_index": at_line, "cells": list(row)})
    return lines, tables


def scrambled_totals(gross_ytd):
    """The user's text PDF (2026-10-19, amounts swapped for P's): the earnings table has no totals rows, and the totals
    box's text comes out scrambled, gross pay's two columns beside Total Deductions on one line."""
    lines, tables = p_table()
    for text in ("Gross pay |", "Net pay |"):
        lines.remove(lines[number_of(lines, text) - 1])
    del tables[0]["rows"][-2:]
    lines += ["Total Earnings (A)", "Net Payment (A-B)", "2,500.00", "1,912.34", f"2,500.00 {gross_ytd} Total Deductions (B) $587.66"]
    shared = number_of(lines, "Total Deductions")
    summary = {"gross_pay": {"value": "2,500.00", "status": "proposed", "evidence": at(lines, shared, "2,500.00")},
               "gross_pay_ytd": {"value": gross_ytd, "status": "proposed", "evidence": at(lines, shared, gross_ytd)}}
    classes = [{"description": name, "group": group, "category": category, "evidence": at(lines, number_of(lines, f"{name} " if name == "Regular" else f"{name} |"))}
               for name, group, category, _, _ in P_LINES]
    replies = {"Classification": [paystub_classification(lines)], "PaystubSummary": [paystub_summary(lines, **summary)],
               "PayRowClasses": [{"lines": classes}], "PayLines": [{"lines": []}] * 3}
    return lines, tables, replies


def test_a_first_paychecks_gross_pay_printed_twice_on_a_crowded_line_is_kept(tmp_path, local_model):
    """This period and year to date are the same amount, printed twice on a line with several amounts: either column
    gives the right value, so neither is left out as several amounts."""
    lines, tables, replies = scrambled_totals("2,500.00")
    with read_stub(tmp_path, local_model, lines, replies, tables) as (_, _run, record):
        assert (record["gross_pay_minor"], record["gross_pay_ytd_minor"]) == (250000, 250000)
        assert not any(MULTIPLE in issue for issue in record["issues"]), record["issues"]


def totals_box(gross_ytd="5,500.00"):
    """The user's text PDF layout (2026-10-19, synthetic amounts): earnings and deductions tables with every year to date
    equal to this period, then a totals box whose text comes out scrambled; gross pay's year to date shares a line
    with Total Deductions. The model cites only that crowded line for both gross pay amounts."""
    lines = p_header()
    earnings, deductions = len(lines), len(lines) + 3
    lines += ["Earnings | Rate | Hours | This Period | Year To Date", "Regular Salary | 31.25 | 80 | 2,500.00 | 2,500.00",
              "Relocation Bonus |  |  | 3,000.00 | 3,000.00", "Deductions | This Period | Year To Date", "Statutory |  | ",
              "Federal Tax | 500.00 | 500.00", "Medicare Tax | 79.75 | 79.75", "Total Earnings (A)", "Net Payment (A-B)", "$5,500.00", "$4,920.25",
              "$5,500.00 Total Deductions (B) $579.75 $579.75", "$4,920.25"]
    tables = [{"header_rows": [{"line_index": earnings, "cells": ["Earnings", "Rate", "Hours", "This Period", "Year To Date"]}],
               "rows": [{"line_index": earnings + 1, "cells": ["Regular Salary", "31.25", "80", "2,500.00", "2,500.00"]},
                        {"line_index": earnings + 2, "cells": ["Relocation Bonus", "", "", "3,000.00", "3,000.00"]}]},
              {"header_rows": [{"line_index": deductions, "cells": ["Deductions", "This Period", "Year To Date"]}],
               "rows": [{"line_index": deductions + 1, "cells": ["Statutory", "", ""]},
                        {"line_index": deductions + 2, "cells": ["Federal Tax", "500.00", "500.00"]},
                        {"line_index": deductions + 3, "cells": ["Medicare Tax", "79.75", "79.75"]}]}]
    crowded, net_lines = number_of(lines, "Total Deductions"), [index + 1 for index, line in enumerate(lines) if line == "$4,920.25"]
    summary = {"gross_pay": {"value": "5,500.00", "status": "proposed", "evidence": at(lines, crowded, "5,500.00")},
               "gross_pay_ytd": {"value": gross_ytd, "status": "proposed", "evidence": at(lines, crowded, gross_ytd)},
               "net_pay": {"value": "4,920.25", "status": "proposed", "evidence": at(lines, net_lines[0])},
               "net_pay_ytd": {"value": "4,920.25", "status": "proposed", "evidence": at(lines, net_lines[1])}}
    classes = [{"description": name, "group": group, "category": category, "evidence": at(lines, number_of(lines, f"{name} |"))}
               for name, group, category in (("Regular Salary", "earnings", "regular_pay"), ("Relocation Bonus", "earnings", "bonus"),
                                             ("Statutory", "tax", "other"), ("Federal Tax", "tax", "federal_income_tax"), ("Medicare Tax", "tax", "medicare"))]
    # The model also lists the totals outside the tables as pay lines (docs/bugs.md "Gross pay and Net pay read as earnings lines").
    totals = [{"description": name, "group": "earnings", "category": "other_earnings", "current": amount, "ytd": amount, "evidence": at(lines, number)}
              for name, amount, number in (("Gross Pay", "5,500.00", crowded), ("Net Payment (A-B)", "4,920.25", net_lines[0]))]
    replies = {"Classification": [paystub_classification(lines)], "PaystubSummary": [paystub_summary(lines, **summary)],
               "PayRowClasses": [{"lines": classes[:2]}, {"lines": classes[2:]}], "PayLines": [{"lines": []}, {"lines": []}, {"lines": totals}, *[{"lines": []}] * 4]}  # The third call holds the totals lines.
    return lines, tables, replies


def test_a_first_paychecks_totals_on_a_scrambled_line_add_up_from_the_table(tmp_path, local_model):
    """Gross pay on a line printing several amounts is kept when the table's earnings cells add up to it, in its own
    column: whichever column the model read it from, it is right. Every total and line keeps both columns."""
    lines, tables, replies = totals_box()
    with read_stub(tmp_path, local_model, lines, replies, tables) as (_, run, record):
        assert (record["gross_pay_minor"], record["gross_pay_ytd_minor"]) == (550000, 550000), record["issues"]
        assert (record["net_pay_minor"], record["net_pay_ytd_minor"]) == (492025, 492025), record["issues"]
        assert stored_lines(record) == [("Regular Salary", 250000, 250000), ("Relocation Bonus", 300000, 300000),
                                        ("Federal Tax", 50000, 50000), ("Medicare Tax", 7975, 7975)]
        assert not any(MULTIPLE in issue for issue in record["issues"]) and guard_issues(record) == []
        # The Statutory heading row is no pay line, so taxes add up: shown from the lines, beside the stored record.
        assert (record["display"]["taxes_minor"], record["display"]["total_deductions_minor"]) == ("579.75 USD", "579.75 USD")
        assert sum("pay summary total was returned as an individual pay line" in note for note in run["result"]["notes"]) == 2


def test_a_total_the_table_doesnt_add_up_to_is_still_left_out(tmp_path, local_model):
    lines, tables, replies = totals_box(gross_ytd="579.75")
    with read_stub(tmp_path, local_model, lines, replies, tables) as (_, _run, record):
        assert record["gross_pay_ytd_minor"] is None
        assert any(issue.startswith("Gross pay ytd has multiple amounts") for issue in record["issues"])


@pytest.mark.parametrize("printed", ["TOTAL DEDUCTIONS (B) 587.66", "DEDUCTIONS 587.66"])
def test_a_total_of_taxes_and_deductions_is_never_pre_tax_deductions(tmp_path, local_model, printed):
    """The user's second paycheck (2026-10-19): the model reads Total Deductions (taxes 537.66 + 401(k) 50.00) as the
    pre-tax deductions field. Left empty, by its label or because it is every tax and deduction added up; the page then
    shows the pre-tax lines' 50.00, and the total beside it."""
    lines, tables = p_table(extras=[*P_EXTRAS, printed])
    replies = p_table_replies(lines, deductions={"value": "587.66", "status": "proposed", "evidence": at(lines, number_of(lines, printed), "587.66")})
    with read_stub(tmp_path, local_model, lines, replies, tables) as (manager, run, _record):
        record = manager.paystub(run["publication"]["id"])
        assert record["deductions_minor"] is None and "deductions_minor" in record["worked_out"]
        assert (record["display"]["deductions_minor"], record["display"]["total_deductions_minor"]) == ("50.00 USD", "587.66 USD")


def test_a_printed_pre_tax_total_is_kept(tmp_path, local_model):
    lines, tables = p_table(extras=[*P_EXTRAS, "PRE-TAX DEDUCTIONS 50.00"])
    replies = p_table_replies(lines, deductions={"value": "50.00", "status": "proposed", "evidence": at(lines, len(lines), "50.00")})
    with read_stub(tmp_path, local_model, lines, replies, tables) as (manager, run, _record):
        assert manager.paystub(run["publication"]["id"])["deductions_minor"] == 5000


def test_sc32_b_a_validated_401k_row_keeps_its_cell(tmp_path, local_model):
    """SC-32 b; fixture P-table already prints "401(k) | 50.00 | 650.00", so the added row is named apart."""
    lines, tables = p_table_with(("Roth 401(k)", "184.98", "2,404.74"))
    replies = p_table_replies(lines)
    replies["PayRowClasses"][0]["lines"].append({"description": "Roth 401(k)", "group": "post_tax", "category": "retirement_roth",
                                                 "evidence": at(lines, number_of(lines, "Roth 401(k) |"))})
    with read_stub(tmp_path, local_model, lines, replies, tables) as (_, run, record):
        assert stored_lines(record)[-1] == ("Roth 401(k)", 18498, 240474)
        assert stored_lines(record)[-2] == ("401(k)", 5000, 65000)
        assert run["result"]["rows"][-1]["cell_evidence"]["current"]["quote"] == "184.98"


def test_a_401k_line_outside_the_table_is_one_amount(tmp_path, local_model):
    """FR-34 in anchor_paystub: a pay line citing "401K 184.98" outside the validated table has one amount, so it keeps
    the model's value instead of being nulled as several amounts."""
    lines, tables = p_table()
    lines.append("401K 184.98")
    replies = p_table_replies(lines)
    # Lines outside the table are read in two chunks: the header lines, then the extras ending with the 401K line.
    replies["PayLines"] = [{"lines": []}, {"lines": [{"description": "401k", "group": "pre_tax", "category": "retirement_pretax", "current": "184.98",
                                                      "ytd": None, "evidence": at(lines, len(lines))}]}]
    with read_stub(tmp_path, local_model, lines, replies, tables) as (_, _run, record):
        assert ("401k", 18498, None) in stored_lines(record)
        assert not any(MULTIPLE in issue for issue in record["issues"])


def test_sc29_a_swapped_line_is_left_out_and_its_correction_outlives_reading_again(tmp_path, local_model):
    """SC-29 (FR-33, FR-36)."""
    lines = SIDE_BY_SIDE
    regular = f"line-{number_of(lines, 'REGULAR')}"
    swapped = {"Regular": {"current": "32,500.00", "ytd": "2,500.00"}}
    manager, doc, parse_id = transcribe(tmp_path, local_model, lines)
    try:
        local_model["by_schema"] = side_replies(lines, changes=swapped)
        run = extract(manager, doc, parse_id)
        income_id = run["publication"]["id"]
        record = manager.ledger.record("income_record", income_id)
        assert stored_lines(record)[0] == ("Regular", None, None) and record["review_status"] == "needs_review"
        assert column_notes(record) == [
            f"This period: Regular 32,500.00 USD doesn't match the printed columns (pay line 1, {regular}): it is printed under YTD; "
            "it was left out. Enter this paycheck's amount with Edit details.",
            f"Year to date: Regular 2,500.00 USD doesn't match the printed columns (pay line 1, {regular}); it was left out. "
            "Enter the year-to-date amount with Edit details."]
        assert any(issue.startswith("This period: Regular 32,500.00 USD is larger than its year to date") for issue in record["issues"])
        with manager.store.connection() as db:
            details = json.loads(db.execute("SELECT details_json FROM income_lines ORDER BY position").fetchone()[0])
        assert (details["current_status"], details["ytd_status"], details["column"]["rule"]) == ("ambiguous", "ambiguous", "position")
        assert (details["column"]["value_minor"], details["column"]["ytd_minor"]) == (3250000, 250000)
        others = [issue for issue in record["issues"] if not issue.startswith(("This period: Regular", "Year to date: Regular"))]
        corrected = manager.ledger.correct_income_line(income_id, 1, {"current": "2500.00", "ytd": "32500.00"})
        assert column_notes(corrected) == [] and stored_lines(corrected)[0] == ("Regular", 250000, 3250000)
        assert [issue for issue in corrected["issues"] if issue in others] == others
        with manager.store.connection() as db:
            resolved = [json.loads(row[0]) for row in db.execute("SELECT resolved_issues_json FROM record_corrections ORDER BY id")]
        assert any(COLUMN_NOTE in issue for issue in resolved[0]) and any(COLUMN_NOTE in issue for issue in resolved[1])
        local_model["by_schema"] = side_replies(lines, changes=swapped)
        again = extract(manager, doc, parse_id, force=True)
        assert again["publication"]["id"] == income_id
        record = manager.ledger.record("income_record", income_id)
        assert stored_lines(record)[0] == ("Regular", 250000, 3250000) and column_notes(record) == []
    finally:
        manager.close()


def test_sc30_hours_and_rate_count_by_position(tmp_path, local_model):
    lines = [*SIDE_BY_SIDE[:5], "DESCRIPTION HOURS RATE CURRENT YTD", "REGULAR 80.00 31.25 2,500.00 32,500.00", *SIDE_BY_SIDE[7:]]
    replies = side_replies(lines, changes={"Regular": {"hours": "80.00", "rate": "31.25"}})
    with read_stub(tmp_path, local_model, lines, replies) as (_, run, record):
        assert stored_lines(record)[0] == ("Regular", 250000, 3250000) and column_notes(record) == []
        assert run["result"]["normalized"]["lines"][0]["details"]["hours"]["text"] == "80.00"
        assert any(check["name"] == "hours:1" for check in record["checks"])
        assert not any("hours ×" in issue for issue in record["issues"])


def test_sc31_a_one_amount_line_answered_as_this_period_is_left_out(tmp_path, local_model):
    lines = SIDE_BY_SIDE
    replies = side_replies(lines, changes={"Relocation bonus": {"current": "5,000.00", "ytd": None}})
    with read_stub(tmp_path, local_model, lines, replies) as (manager, _run, record):
        assert stored_lines(record)[1] == ("Relocation bonus", None, None) and record["review_status"] == "needs_review"
        assert column_notes(record) == [
            f"This period: Relocation bonus 5,000.00 USD: pay line 2 prints one amount; check whether it is this period or year to date "
            f"(line-{number_of(lines, 'RELOCATION')}). It was left out; enter it with Edit details."]
        with manager.store.connection() as db:
            details = json.loads(db.execute("SELECT details_json FROM income_lines WHERE position=2").fetchone()[0])
        assert (details["current_status"], details["column"]["rule"]) == ("ambiguous", "one_amount")


def test_sc34_every_this_period_copied_from_year_to_date(tmp_path, local_model):
    lines = SIDE_BY_SIDE
    changes = {"Regular": {"current": "32,500.00"}, "Relocation bonus": {"current": "5,000.00"}, "Federal income tax": {"current": "3,250.00"}}
    replies = side_replies(lines, changes=changes, gross_pay=side_amount(lines, "GROSS PAY", "37,500.00"),
                           net_pay=side_amount(lines, "NET PAY", "34,250.00"))
    with read_stub(tmp_path, local_model, lines, replies) as (_, _run, record):
        assert record["review_status"] == "needs_review"
        assert stored_lines(record) == [("Regular", None, None), ("Relocation bonus", None, 500000), ("Federal income tax", None, None)]
        assert all(record[name] is None for name in ("gross_pay_minor", "gross_pay_ytd_minor", "net_pay_minor", "net_pay_ytd_minor"))
        notes = column_notes(record)
        for label in ("This period: Regular", "Year to date: Regular", "This period: Federal income tax", "Year to date: Federal income tax",
                      "Gross pay 37,500.00", "Gross pay year to date", "Net pay 34,250.00", "Net pay year to date"):
            assert any(note.startswith(label) and COLUMN_NOTE in note for note in notes), label
        assert any(note.startswith("This period: Relocation bonus") and "prints one amount" in note for note in notes)
        # FR-22 judges the model's values first: the 14-day printed period gives a frequency, so equality is rule (c).
        assert len([issue for issue in guard_issues(record) if "mid-year" in issue]) == 5


def test_an_ambiguous_header_skips_the_position_check(tmp_path, local_model):
    lines = [*SIDE_BY_SIDE[:6], "YTD CURRENT", *SIDE_BY_SIDE[6:]]
    replies = side_replies(lines, changes={"Regular": {"current": "32,500.00", "ytd": "2,500.00"}})
    with read_stub(tmp_path, local_model, lines, replies) as (_, _run, record):
        assert not any(COLUMN_NOTE in issue for issue in record["issues"])
        assert any(issue.startswith("This period: Regular 32,500.00 USD is larger than its year to date") for issue in record["issues"])


def test_with_no_header_a_one_amount_line_keeps_the_models_choice(tmp_path, local_model):
    lines = [line for line in SIDE_BY_SIDE if line != "DESCRIPTION CURRENT YTD"]
    replies = side_replies(lines, changes={"Relocation bonus": {"current": "5,000.00", "ytd": None}})
    with read_stub(tmp_path, local_model, lines, replies) as (_, _run, record):
        assert stored_lines(record)[1] == ("Relocation bonus", 500000, None) and column_notes(record) == []


def test_a_swapped_gross_pay_pair_is_left_out_and_one_correction_clears_both(tmp_path, local_model):
    """FR-33 on summary amounts; P8: correcting gross pay alone clears both of the pair's notes."""
    lines = SIDE_BY_SIDE
    replies = side_replies(lines, gross_pay=side_amount(lines, "GROSS PAY", "37,500.00"), gross_pay_ytd=side_amount(lines, "GROSS PAY", "2,500.00"))
    manager, doc, parse_id = transcribe(tmp_path, local_model, lines)
    try:
        local_model["by_schema"] = replies
        run = extract(manager, doc, parse_id)
        income_id = run["publication"]["id"]
        record = manager.ledger.record("income_record", income_id)
        assert (record["gross_pay_minor"], record["gross_pay_ytd_minor"]) == (None, None) and record["review_status"] == "needs_review"
        notes = column_notes(record)
        assert len(notes) == 2 and notes[0].startswith("Gross pay 37,500.00 USD") and notes[1].startswith("Gross pay year to date 2,500.00 USD")
        with manager.store.connection() as db:
            details = json.loads(db.execute("SELECT details_json FROM income_records").fetchone()[0])
        assert set(details["columns"]) == {"gross_pay", "gross_pay_ytd"}
        corrected = manager.ledger.correct("income_record", income_id, {"gross_pay": "2500.00"})
        assert column_notes(corrected) == [] and corrected["gross_pay_ytd_minor"] is None
    finally:
        manager.close()


def test_version_changed_and_old_readings_are_not_reused(tmp_path, local_model):
    """SC-15 (FR-16), SC-35 (FR-37)."""
    assert EXTRACTION_VERSION != "typed-extraction-v22-native-cells"
    assert EXTRACTION_VERSION != "typed-extraction-v23-document-forms"
    lines = p_flat()
    manager, doc, parse_id = transcribe(tmp_path, local_model, lines)
    try:
        local_model["by_schema"] = correct_replies(lines)
        run = extract(manager, doc, parse_id)
        with manager.store.connection() as db:
            db.execute("UPDATE extraction_runs SET prompt_version='typed-extraction-v23-document-forms' WHERE id=?", (run["id"],))
        local_model["by_schema"] = correct_replies(lines)
        started = manager.start_extraction(doc["id"], parse_id)
        manager.future.result(timeout=30)
        assert started["reused"] is False and started["run_id"] != run["id"]
        assert manager.extractions.get(started["run_id"])["prompt_version"] == EXTRACTION_VERSION
    finally:
        manager.close()
