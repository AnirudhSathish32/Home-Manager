"""The bill layout generator through the real reader, the bill engine and Record (specs/pdf-table-engine-bills/test-contract.md SC-123, SC-125; FR-123, FR-127).

Every one of the seeded files (`bill_engine_generator.CASES`, files of 1 to 4 bills) is written with `make_pdf`, read by the real PDF reader and recorded
through the real services with the contract's `local_model` stubs. The stubs are drawn from the case's own answers: the classification, the summary (the
printed dates, account and amounts, the right amount due) and each charge row's description, kind, category and holder citing its row; they give no line
amount, quantity or rate. Every expected value comes from the generator's inputs (`evals/bill_layouts.py`), never from the engine: each line's description,
amount, kind, printed quantity and rate (and the rate's text when it is not a whole number of cents), holder and the note a disagreeing model holder earns; the
amounts the bill prints, the new charges worked out or summed, the amount due FR-117 settles on; the guesses and notes; and where the file splits. A miss
prints the seed, the case index and the layout choices.

`generator_only` tests need no store and no model: they read each file and compare the engine's charge rows with the expected lines. The `diagnose` tests
run `scripts/statement_diagnose.py <pdf> bill` as a subprocess with `-I` (SC-125).
"""

from collections import Counter
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

import bill_engine_fixtures as bf
import bill_engine_generator as gen
from evals import bill_layouts as layouts
from home_manager.documents import bill_split
from home_manager.documents.extraction import BILL_SPLIT_NOTE, NO_BILL_TABLE
from home_manager.finance import bill_tables
import pdf_import_fixtures as fx
from test_bill_engine_record import finished, lines_of, no_network, started  # noqa: F401 - no_network is the autouse C-net fixture
from test_bill_split import Bills
from test_extraction import MISSING
from test_pdf import make_pdf, pdf_store  # noqa: F401

# Engine defects the generator found that need a source change outside this slice (the handoff lists them with their seed, index and choices). Each is a case
# the assertions below still judge in full: the entry only turns the failure into a strict expected failure, so it fails loudly once the engine is fixed.
LAST_YEAR = ("a last-year column with no heading in a file of several bills: the column roles are decided once for the whole table, and the sum rule compares "
             "the whole column's sum with each bill's new charges, never the sum of them (finance/bill_tables.py targets_of, decide)")
CARRIED_TITLE = ("the last section title of one bill (`Account Credits`) is still the section of the next bill's first rows when that bill prints no title of "
                 "its own, so they read as money off (finance/bill_tables.py: a row's section is the last title above it, whatever bill it belongs to)")
ESCALATED_RECORD = {
    **dict.fromkeys((29, 33, 64, 67), LAST_YEAR),
    **dict.fromkeys((56, 83), CARRIED_TITLE),
}
ESCALATED_ROWS = {index: LAST_YEAR for index in (29, 33, 64, 67)}


def escalated(index, table):
    return [pytest.mark.xfail(strict=True, reason=table[index])] if index in table else []


CASES = [pytest.param(index, marks=escalated(index, ESCALATED_RECORD), id=f"case{index}") for index in range(gen.CASES)]
ROW_CASES = [pytest.param(index, marks=escalated(index, ESCALATED_ROWS), id=f"case{index}") for index in range(gen.CASES)]


def context(case, index, seed=gen.SEED):
    return f"seed {seed} case {index}: layout {case.choices}"


def collapse(text):
    return " ".join(text.replace("|", " ").split())


def printed_minor(minor, case, bill):
    """A signed minor amount as the case prints it (money off in the case's credit style)."""
    return layouts.minor_text(minor, case.choices["credit"], bill["kind"] == "rent")


def label_of(line):
    return collapse(f"{line['label']} {line['wrap']}" if line["wrap"] else line["label"])


def read(case, folder):
    result = fx.read_pdf(folder, case.pages)
    assert [page.method for page in result.pages] == ["embedded_text"] * len(case.pages)
    return result


# --- generator_only: the engine's charge rows against the generator's lines ------------------------------------------------------------------

def expected_rows(case):
    """Every line of every bill as the engine should read its cells: (label, charge, quantity, rate), the charge as printed."""
    return Counter((label_of(line), printed_minor(line["minor"], case, bill).lstrip("$"), line["quantity"], line["rate"])
                   for bill in case.bills for line in bill["lines"])


def engine_rows(reading):
    found = []
    for table in reading.adapted:
        for row in table.rows:
            if row.total:
                continue
            cells = {table.roles.get(number): cell.quote.strip() for number, cell in enumerate(row.cells) if number and cell.quote.strip()}
            found.append((collapse(row.cells[0].quote), (cells.get("charge") or "").lstrip("$"), cells.get("quantity"), cells.get("unit_price")))
    return Counter(found)


@pytest.mark.parametrize("index", ROW_CASES)
def test_generator_only_case_engine_rows_are_exact(index, tmp_path):
    case = gen.layout(index)
    where = context(case, index)
    reading = bill_tables.read(read(case, tmp_path))
    got, wanted = engine_rows(reading), expected_rows(case)
    assert got == wanted, f"{where}: missing {wanted - got}, extra {got - wanted}"
    assert not reading.reading.unplaced or case.choices["sentence"] == "anchor_prose", f"{where}: unplaced {reading.reading.unplaced}"
    assert [guess for guess in reading.guesses if guess.kind != bill_tables.AMOUNT_DUE] == [], where


# --- Record: every file through the real services ------------------------------------------------------------------------------------------------

UNPLACED_NOTE = re.compile(r"^Page \d+: a printed line wasn't placed in any column, so it wasn't recorded: \".*\b4\.00\"$")  # The sentence that holds an anchor phrase (G7, FR-104).
WORKED_OUT = "New charges aren't printed; worked out as amount due"
DUE_GUESS = re.compile(r"^The amount due is printed as .+; .+, the first on page \d+, was used\.$")


class Generated(Bills):
    """One generated file, read and then extracted through the real services; every answer of the model double is drawn from the case's answers."""

    def part(self, bill):
        pages = range(bill["first_page"] + 1, bill["first_page"] + bill["pages"] + 1)
        return [line for line in self.blank_free() if bill_split.page_of(line) in pages]

    def answer(self, case):
        """The contract's `local_model` by schema, one answer per bill in file order: the classification, the summary and each charge row's classification
        citing its printed line; the run structure (rows the engine covers, and the rest) is the file's."""
        covered = self.covered()
        rent = case.choices["kind"] == "rent"
        replies = {"Classification": [], "BillSummary": [], "BillLines": [], "BillRentSummary": [], "RentBillLines": []}
        for bill in case.bills:
            part = self.part(bill)

            def find(text, part=part):
                return next(line for line in part if line.text.startswith(text))

            def with_amount(text, part=part):
                """The line that prints the amount: the reader sets a printed column's values in lines of their own, so it starts with the amount."""
                return next((line for line in part if line.text.startswith(text)), None) or next(line for line in part if text in line.text)

            def field(value, line, quote):
                return {"value": value, "status": "proposed", "evidence": [{"line_id": line.id, "quote": quote}]}
            us = lambda day: f"{day[5:7]}/{day[8:]}/{day[:4]}"  # noqa: E731
            keys = bill["labels"]
            money = lambda minor: layouts.money(minor)  # noqa: E731
            fields = {name: MISSING for name in ("provider", "account_reference", "issue_date", "due_date", "period_start", "period_end", "amount_due", "new_charges",
                                                  "currency")}
            fields.update(provider=field(bill["provider"], find(bill["provider"]), bill["provider"]),
                          account_reference=field(bill["last_four"], find(keys["account"]), bill["account"]),
                          issue_date=field(bill["issue_date"], find(keys["statement"]), us(bill["issue_date"])),
                          due_date=field(bill["due_date"], find(keys["due"]), us(bill["due_date"])),
                          amount_due=field(money(bill["amount_due"]), with_amount(money(bill["amount_due"])), money(bill["amount_due"])),
                          currency=field("USD", find("This bill is for"), "US dollars"))
            if not rent:
                fields.update(period_start=field(bill["period"][0], find("Billing Period"), us(bill["period"][0])),
                              period_end=field(bill["period"][1], find("Billing Period"), us(bill["period"][1])))
            if bill["new_printed"]:
                fields["new_charges"] = field(money(bill["new_charges"]), with_amount(money(bill["new_charges"])), money(bill["new_charges"]))
            replies["Classification"].append({"document_type": "bill", "evidence": fields["provider"]["evidence"], "issuer": fields["provider"], "document_date": MISSING,
                                              "bill_kind": "rent" if rent else "general",
                                              "bill_kind_evidence": [{"line_id": find("Rent and Leasing Charges").id, "quote": "Rent and Leasing Charges"}] if rent else []})
            replies["BillRentSummary" if rent else "BillSummary"].append(fields)
            entries = []
            for line in bill["lines"]:
                cited = find(line["label"])
                row = {"description": line["description"], "amount": None, "quantity": None, "unit_price": None, "category": line["category"],
                       "line_holder": line["model_holder"], "evidence": [{"line_id": cited.id, "quote": cited.text}]}
                entries.append({**row, "rent_type": line["kind"], "period_start": line["period"][0] if line["period"] else None,
                                "period_end": line["period"][1] if line["period"] else None, "usage": line["usage"]} if rent else {**row, "line_kind": line["kind"]})
            runs = []
            for line in part:
                if not runs or (line.id in covered) != runs[-1][0]:
                    runs.append([line.id in covered, []])
                runs[-1][1].append(line.id)
            replies["RentBillLines" if rent else "BillLines"] += [{"line_items": [entry for entry in entries if entry["evidence"][0]["line_id"] in ids]} for _, ids in runs]
        if len(case.bills) > 1:
            replies["Classification"].insert(0, replies["Classification"][0])  # The file's own classification comes first.
        replies = {name: replies[name] for name in replies if replies[name]}
        self.local_model["by_schema"] = replies
        self.before = len(self.local_model["requests"])
        self.questions = sum(len(replied) for replied in replies.values())
        return replies


def recorded(pdf_store, local_model, case, index):
    run = started(pdf_store, local_model, case.pages, name=f"generated-{index}.pdf")
    run.__class__ = Generated
    run.answer(case)
    run.extract()
    return run


def allowed_note(note, expected):
    return (note == BILL_SPLIT_NOTE or note in expected or note.startswith(WORKED_OUT) or bool(DUE_GUESS.match(note)) or bool(UNPLACED_NOTE.match(note))
            or any(note == NO_BILL_TABLE.format(page=page) for page in range(1, 9)))


def assert_bill(case, bill, record, where, count):
    """One bill's record: lines, quantities, rates, holders, totals, the amounts the print gives, the checks and the notes."""
    items = record["items"]
    assert lines_of(record) == [(line["description"], line["minor"], line["kind"]) for line in bill["lines"]], where
    assert [item["quantity"] for item in items] == [line["quantity"] for line in bill["lines"]], where
    assert [item["unit_price_minor"] for item in items] == [line["unit_minor"] for line in bill["lines"]], where
    assert [((item["details"] or {}).get("unit_price") or {}).get("text") for item in items] == [line["unit_text"] for line in bill["lines"]], where
    assert [item["line_holder"] for item in items] == [line["holder"] for line in bill["lines"]], where
    assert [issue for issue in record["issues"] if "Amount has more precision" in issue or issue.startswith("Charge line")] == [], where
    assert (record["total_minor"], record["amount_due_minor"], record["due_date"], record["issue_date"]) == (
        bill["new_charges"], bill["amount_due"], bill["due_date"], bill["issue_date"]), where
    assert (record["period_start"], record["period_end"]) == tuple(bill["period"]), where
    assert record["account_last_four"] == bill["last_four"], where
    details = record["details"]
    for name, printed in (("previous_balance", bill["previous"]), ("payments_received", bill["payments"])):
        assert (details[name]["minor"] if name in details else None) == printed, f"{where}: {name}"
    assert (details["new_charges"]["minor"] if "new_charges" in details else None) == (bill["new_charges"] if bill["new_printed"] or bill["worked_out"] else None), where
    if bill["worked_out"]:
        assert details["new_charges"]["worked_out"] == {"amount_due": bill["amount_due"], "previous_balance": bill["previous"], "payments": bill["payments"]}, where
    checks = {check["name"]: check for check in record["checks"]}
    assert checks["lines"]["passes"] and all(check["passes"] for check in checks.values()), f"{where}: {checks}"
    assert ("carried" in checks) == (bill["previous"] is not None and bill["new_printed"]), f"{where}: {sorted(checks)}"
    assert record["review_status"] == "verified" and record["issues"] == [], f"{where}: {record['review_status']} {record['issues']}"
    notes = details.get("notes", [])
    expected = bill["notes"]
    assert all(allowed_note(note, expected) for note in notes), f"{where}: unexpected notes {notes}"
    assert [note for note in notes if note in expected] == expected, f"{where}: holder notes {notes}"
    assert (BILL_SPLIT_NOTE in notes) == (count > 1), where
    assert any(note.startswith(WORKED_OUT) for note in notes) == bill["worked_out"], where
    assert any(DUE_GUESS.match(note) for note in notes) == bill["due_guess"], f"{where}: {notes}"
    assert {guess["kind"] for guess in details.get("guesses", [])} == ({bill_tables.AMOUNT_DUE} if bill["due_guess"] else set()), where


def assert_records_exactly(case, where, run):
    bills = run.bills()
    assert [segment for segment, _, _ in bills] == list(range(len(case.bills))), f"{where}: {len(bills)} records for {len(case.bills)} bills"
    for bill, (_, _, record) in zip(case.bills, bills):
        assert_bill(case, bill, record, f"{where} bill {bill['number']}", len(case.bills))
    lines = run.blank_free()
    segments = run.segments()
    if len(case.bills) == 1:
        assert segments == [], where
    else:  # Every line of the file is in exactly one segment: each bill's pages, from its first line to its last.
        ids = [line.id for line in lines]
        spans = [(ids.index(first), ids.index(last)) for _, first, last, _, _ in segments]
        starts = [next(number for number, line in enumerate(lines) if bill_split.page_of(line) == bill["first_page"] + 1) for bill in case.bills]
        assert [first for first, _ in spans] == starts and [last for _, last in spans] == [*(start - 1 for start in starts[1:]), len(lines) - 1], where
    assert Counter(run.asked())["Classification"] == (1 if len(case.bills) == 1 else len(case.bills) + 1), where
    assert Counter(run.asked())["BillSummary" if case.choices["kind"] != "rent" else "BillRentSummary"] == len(case.bills), where


@pytest.mark.parametrize("index", CASES)
def test_case_is_recorded_exactly_through_the_real_services(index, pdf_store, local_model):
    case = gen.layout(index)
    run = recorded(pdf_store, local_model, case, index)
    assert_records_exactly(case, context(case, index), run)
    finished(run)


ONE_BILL = [pytest.param(index, id=f"case{index}") for index in sorted(ESCALATED_RECORD)]


@pytest.mark.parametrize("index", ONE_BILL)
def test_escalated_layout_as_a_single_bill_is_recorded_exactly(index, pdf_store, local_model):
    """The escalated files' layouts, with one bill each, so everything but the escalated defect (a file of several bills) is still judged in full."""
    case = gen.layout(index, bills=1)
    run = recorded(pdf_store, local_model, case, index)
    assert_records_exactly(case, context(case, index), run)
    finished(run)


# --- SC-125: the redacted probe ---------------------------------------------------------------------------------------------------------------

PROBE = Path(__file__).resolve().parents[1] / "scripts" / "statement_diagnose.py"
MONEY = re.compile(r"\d[\d,]*\.\d{2}\b")
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b")
FORBIDDEN = ("CITY", "POWER", "WATER", "Energy", "Tier", "Customer", "Electric", "State Tax", "kWh", "Usage History", "97.55", "82.10", "60.00", "20.02", "12.00",
             "5.53", "0.1200", "0.1430", "81.42", "87.26", "74.72", "111.98", "64.80", "70.20", "58.50", "4.62", "5.06", "4.22", "80.00", "50.00",
             "9755", "8210", "6000", "2002", "1200", "553", "8142", "8726", "7472", "11198", "6480", "7020", "5850", "462", "506", "422", "8000", "5000",
             "1234", "5678", "9012", "07/02/2026", "2026-07-02", "07/20/2026", "2026-07-20", "08/20/2026", "09/20/2026", "10/15/2026", "09/20/2026")


def probe(path, tmp_path):
    """The `bill` mode as a subprocess with `-I`; its temporary folders go to a folder of the test's own, so what it leaves behind can be counted."""
    scratch = tmp_path / "scratch"
    scratch.mkdir(exist_ok=True)
    done = subprocess.run([sys.executable, "-I", str(PROBE), str(path), "bill"], capture_output=True, text=True, timeout=180, check=False,
                          env={**os.environ, "TMPDIR": str(scratch), "TEMP": str(scratch), "TMP": str(scratch)})
    assert list(scratch.iterdir()) == [], f"the probe left {list(scratch.iterdir())} behind"
    return done


def written(tmp_path, name, pages):
    path = tmp_path / name
    make_pdf(path, pages)
    return path


def test_diagnose_bl_multi_and_bl_util_print_counts_and_splits_and_none_of_the_bills_words(tmp_path):
    """SC-125: the counts, roles and splits are printed; no fixture word, amount (as printed or in minor units), date or account digit is."""
    multi = probe(written(tmp_path, "multi.pdf", bf.FIXTURES["BL-MULTI"]()), tmp_path)
    util = probe(written(tmp_path, "util.pdf", bf.FIXTURES["BL-UTIL"]()), tmp_path)
    assert multi.returncode == 0 and util.returncode == 0, (multi.stderr[-300:], util.stderr[-300:])
    assert "3 bills: pages 1, 2, 3" in multi.stdout
    assert [line.strip() for line in multi.stdout.splitlines() if line.strip().startswith("page ") and "keys" in line] == [
        "page 1: keys account opens, statement date opens, due date opens",
        "page 2: keys account equal, statement date differs, due date differs   (a bill starts here)",
        "page 3: keys account equal, statement date differs, due date differs   (a bill starts here)"]
    assert "FR-129 reasons that fired: none" in multi.stdout
    assert multi.stdout.count("=== Page ") == 3 and multi.stdout.count("charge tables: 1   rows: 3   totals: 0   section titles: 0") == 3
    assert "1 bill" in util.stdout and "3 bills" not in util.stdout and "roles decided by: product" in util.stdout
    assert [line.split("role ")[1].split()[0] for line in util.stdout.splitlines() if "role " in line] == ["quantity", "rate", "charge"]
    assert "section titles: 2" in util.stdout and "other tables: 1 (12 rows)" in util.stdout
    for name, output in (("BL-MULTI", multi.stdout), ("BL-UTIL", util.stdout)):
        assert [text for text in FORBIDDEN if text in output] == [], name
        assert not DATE.search(output) and not MONEY.search(output), name


def probed_cases():
    """Generated files for the probe: a one-bill file of each kind, files of 2 to 4 bills the engine splits, and a file with wrapped labels and two pages."""
    found = {}
    for index in range(gen.CASES):
        case = gen.layout(index)
        choices = case.choices
        if index in ESCALATED_RECORD:
            continue
        found.setdefault(f"one-{choices['kind']}" if choices["bills"] == 1 else f"many-{choices['bills']}", index)
        if choices["wrapped"] and choices["pages"] == 2:
            found.setdefault("wrapped-two-pages", index)
    return sorted(set(found.values()))


@pytest.mark.parametrize("index", probed_cases())
def test_diagnose_generated_bill_prints_no_document_text_amounts_or_dates(index, tmp_path):
    """FR-127: the probe runs on a generated PDF; its output holds no word, amount, date or account digit the document prints, only shapes and counts, and it
    reports the file's bills and their pages as the generator printed them."""
    case = gen.layout(index)
    pdf = gen.build(tmp_path / "bill.pdf", case)
    done = probe(pdf, tmp_path)
    where = context(case, index)
    assert done.returncode == 0, f"{where}: {done.stderr[-300:]}"
    output = done.stdout
    printed = [text for page in case.pages for _, _, text, *_ in page["items"]]
    words = {word for text in printed for word in re.findall(r"[A-Z][A-Za-z]{2,}", text)} - {"Page", "Account", "Charge"}
    leaked = sorted(word for word in words if re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", output))
    assert not leaked, f"{where}: the probe printed document words {leaked}"
    assert not DATE.search(output), f"{where}: the probe printed a date"
    amounts = {money for text in printed for money in MONEY.findall(text)}
    assert not any(re.search(rf"(?<![\d.]){re.escape(amount)}(?!\d)", output) or amount.replace(",", "").replace(".", "") in output for amount in amounts), where
    assert not any(digits in output for bill in case.bills for digits in (bill["account"], bill["last_four"], bill["due_date"], bill["issue_date"])), where
    spans = [f"{bill['first_page'] + 1}" if bill["pages"] == 1 else f"{bill['first_page'] + 1}-{bill['first_page'] + bill['pages']}" for bill in case.bills]
    assert (f"{len(spans)} bills: pages {', '.join(spans)}" if len(spans) > 1 else f"1 bill: pages {spans[0]}") in output, f"{where}: {output[-400:]}"
    assert f"=== Page {len(case.pages)} ===" in output and f"=== Page {len(case.pages) + 1} ===" not in output, where


def test_diagnose_runs_without_a_model_and_names_no_file(tmp_path):
    """No model is configured for the probe (it needs none), and a file that is no bill still gives counts, not an error."""
    path = written(tmp_path, "plain.pdf", [{"items": [(40, 700, "Just a note"), (40, 40, bf.FOOTER)]}])
    done = probe(path, tmp_path)
    assert done.returncode == 0 and "1 bill: pages 1" in done.stdout and "Just" not in done.stdout and "note" not in done.stdout, (done.stdout[-300:], done.stderr[-300:])


# --- generator_only: the generator's own rules and its coverage ---------------------------------------------------------------------------------

def test_generator_only_twice_gives_byte_identical_pdfs(tmp_path):
    for index in range(gen.CASES):
        first, second = gen.layout(index), gen.layout(index)
        assert first == second, context(first, index)
        assert gen.build(tmp_path / "a.pdf", first).read_bytes() == gen.build(tmp_path / "b.pdf", second).read_bytes(), context(first, index)
    assert gen.layout(0, seed=gen.SEED + 1) != gen.layout(0)  # Another seed gives other bills.


# Every FR-123 variation, SC-123's rate kinds, holder forms and holder stubs, by the tag `layouts.variations` gives a case.
REQUIRED = {
    *(f"kind:{kind}" for kind in ("utility", "phone", "rent")), *(f"sections:{style}" for style in ("sections", "one")), *(f"heading:{style}" for style in layouts.HEADINGS),
    *(f"columns:{style}" for style in layouts.COLUMNS), *(f"credit:{style}" for style in layouts.CREDITS), *(f"summary:{style}" for style in layouts.SUMMARIES),
    "prev:printed", "prev:not", "new:printed", "new:not", "due:alike", "due:different", "stub:on_page", "stub:own_page", "repeat", "late:run", "late:col", "late:dateless",
    "late:fee_after", "late_row", "sentence:due_prose", "sentence:late_prose", "sentence:statement_prose", "sentence:anchor_prose", "wrapped", "history", "dots",
    "cut:tail", "cut:mid", "acct_same_dates", "bills:1", "bills:2", "bills:3", "bills:4", "pages_per_bill:1", "pages_per_bill:2", "worked_out", "new_charges:summed",
    "decision:check", "decision:lines", "decision:guess",
    *(f"rate:{kind}" for kind in layouts.RATE_KINDS), *(f"holder_form:{form}" for form in layouts.PHONE_FORMS), *(f"holder_mode:{mode}" for mode in layouts.HOLDER_MODES),
}


def test_generator_only_every_fr123_variation_occurs():
    seen = Counter()
    for index in range(gen.CASES):
        seen.update(layouts.variations(gen.layout(index)))
    missing = sorted(tag for tag in REQUIRED if not seen[tag])
    assert not missing, f"seed {gen.SEED}: variations that no case of {gen.CASES} has: {missing}"


def test_generator_only_every_variation_is_also_read_by_a_case_that_passes_through_the_record():
    """The escalated files (strict expected failures above) never take a variation out of the Record test: each is covered by a case that is not escalated."""
    seen = Counter()
    for index in range(gen.CASES):
        if index not in ESCALATED_RECORD:
            seen.update(layouts.variations(gen.layout(index)))
    assert not sorted(tag for tag in REQUIRED if not seen[tag])


def test_generator_only_prints_rates_exactly_half_a_cent_past_at_three_and_four_decimals():
    """SC-123's rates: at least one exactly half a cent past a whole cent at each precision (0.125 and 0.1450 style), and whole-cent rates that print 2 and 4 decimals."""
    seen = set()
    for index in range(gen.CASES):
        for bill in gen.layout(index).bills:
            for line in bill["lines"]:
                if line.get("rate_kind"):
                    tenths = round(float(line["rate"]) * 10000)
                    places = len(line["rate"].split(".")[1])
                    seen.add((line["rate_kind"], places, tenths % 100 == 50 or tenths % 100 == 0))
                    if tenths % 100 == 50:
                        seen.add(("half", places))
    assert {("half", 3), ("half", 4)} <= seen, seen
    assert {("whole_2dp", 2, True), ("whole_4dp", 4, True)} <= seen, seen


def test_generator_only_follows_its_own_rules():
    """The rules that keep each bill decidable: money is integer minor units and the arithmetic holds exactly (new charges are the lines' signed sum, the amount
    due is previous balance − payments + new charges), a charge that is quantity × rate is the product rounded half up, a rate is stored rounded half up with its
    text kept only when its value is not a whole number of cents, a file holds 1 to 4 bills of at most two pages each, and every date is before 2026-11-08."""
    for index in range(gen.CASES):
        case = gen.layout(index)
        choices, where = case.choices, context(case, index)
        assert 1 <= len(case.bills) <= 4 and len(case.bills) == choices["bills"], where
        assert sum(bill["pages"] for bill in case.bills) == len(case.pages) and max(bill["pages"] for bill in case.bills) <= 2, where
        dues = [bill["due_date"] for bill in case.bills]
        assert max(dues) < "2026-11-08", where
        for bill in case.bills:
            assert bill["new_charges"] == sum(line["minor"] for line in bill["lines"]), where
            assert bill["amount_due"] == bill["new_charges"] + (0 if bill["previous"] is None else bill["previous"] - bill["payments"]), where
            assert bill["wrong_due"] is None or bill["wrong_due"] != bill["amount_due"], where
            for line in bill["lines"]:
                assert isinstance(line["minor"], int), where
                if line["quantity"]:
                    value = line["quantity_value"] * round(float(line["rate"]) * 10000)
                    assert line["minor"] == (value + 50) // 100, f"{where}: {line}"
                    whole = round(float(line["rate"]) * 10000) % 100 == 0
                    assert line["unit_minor"] == (round(float(line["rate"]) * 10000) + 50) // 100, where
                    assert (line["unit_text"] is None) == whole, where
                else:
                    assert line["unit_minor"] is None and line["unit_text"] is None, where
            assert all(line["holder"] is None for line in bill["lines"] if line.get("owner") is None), where
        if choices["kind"] == "phone":
            assert len(choices["holder_forms"]) == 2 and all(bill["notes"] == [] or "differs from its section title" in bill["notes"][0] for bill in case.bills), where
        if choices["columns"] == "lastyear":
            assert choices["new_printed"], where
