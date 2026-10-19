"""Pay stub forms (specs/document-forms): this period never takes a year-to-date or annual amount (FR-22 – FR-24)."""

from contextlib import contextmanager
import json

from document_forms_fixtures import (
    P_LINES,
    P_NET,
    P_TABLE_HEADING,
    at,
    cite,
    flat_label,
    number_of,
    p_flat,
    p_table,
    paystub_classification,
    paystub_summary,
    section_line,
    stored_identifiers,
    uncited,
    value,
)
from home_manager.documents.extraction import DETAILS_FAILED, EXTRACTION_VERSION, GUARD_RULES
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


def test_sc20_c_equal_to_year_to_date_mid_year(tmp_path, local_model):
    lines = p_flat()
    copied = ytd_value(lines, "GROSS PAY", "32,500.00")
    with read_stub(tmp_path, local_model, lines, correct_replies(lines, gross_pay=copied, gross_pay_ytd=copied)) as (_, _run, record):
        assert record["gross_pay_minor"] is None and record["review_status"] == "needs_review"
        [issue] = guard_issues(record)
        assert issue.startswith("Gross pay 32,500.00 USD equals its year to date 32,500.00 USD mid-year")


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


def test_sc21_a_a_mismatching_rate_goes_to_review(tmp_path, local_model):
    lines, tables = p_table(regular="Regular 80.00 h @ 31.00")
    with read_stub(tmp_path, local_model, lines, p_table_replies(lines, hours="80.00", rate="31.00", **p_details(lines)), tables) as (_, _run, record):
        assert record["review_status"] == "needs_review"
        [issue] = [issue for issue in record["issues"] if "hours ×" in issue]
        assert issue.startswith("This period: Regular 80.00 hours × 31.00 = 2,480.00 USD, not the printed 2,500.00 USD")


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
    lines = p_flat(period=None, frequency=None, ytd_equal=True)
    with read_stub(tmp_path, local_model, lines, correct_replies(lines)) as (_, _run, record):
        assert record["review_status"] == "needs_review" and record["gross_pay_minor"] == 250000  # Kept, with the reason.
        assert any(issue.startswith("Gross pay 2,500.00 USD equals its year to date 2,500.00 USD and the pay period isn't known")
                   for issue in record["issues"])


def test_version_changed_and_old_readings_are_not_reused(tmp_path, local_model):
    """SC-15 (FR-16)."""
    assert EXTRACTION_VERSION != "typed-extraction-v22-native-cells"
    lines = p_flat()
    manager, doc, parse_id = transcribe(tmp_path, local_model, lines)
    try:
        local_model["by_schema"] = correct_replies(lines)
        run = extract(manager, doc, parse_id)
        with manager.store.connection() as db:
            db.execute("UPDATE extraction_runs SET prompt_version='typed-extraction-v22-native-cells' WHERE id=?", (run["id"],))
        local_model["by_schema"] = correct_replies(lines)
        started = manager.start_extraction(doc["id"], parse_id)
        manager.future.result(timeout=30)
        assert started["reused"] is False and started["run_id"] != run["id"]
        assert manager.extractions.get(started["run_id"])["prompt_version"] == EXTRACTION_VERSION
    finally:
        manager.close()
