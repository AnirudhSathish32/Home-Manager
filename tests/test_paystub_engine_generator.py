"""The pay stub layout generator through the real reader, the pay engine and Record (specs/pdf-table-engine-paystubs/test-contract.md SC-67, FR-70).

Every one of the seeded files (`paystub_engine_generator.CASES`, files of 1 to 4 pay stubs) is written with `make_pdf`, read by the real PDF reader
and recorded through the real services with the contract's `local_model` stubs. The stubs are drawn from the case's own answers: the classification,
the summary (every printed total given the other column's value, so a value taken from the model would be wrong) and each pay line's group and
category citing its row; they give no pay line amount. Every expected value comes from the generator's inputs (`evals/paystub_layouts.py`), never
from the engine: each pay line's this-period, year-to-date, hours and rate; gross, net, taxes and deductions where printed; the pay date; and where
the file splits. A miss prints the seed, the case index and the layout choices.

`generator_only` tests need no store and no model: they read each file and compare the pay engine's rows with the expected lines.
"""

from collections import Counter
from decimal import Decimal
import re

import pytest

from conftest import documents_by_name  # noqa: F401  (the Inbox helpers the Record tests share)
from evals import paystub_layouts as layouts
from home_manager.core.jobs import Work  # noqa: F401
from home_manager.documents.extraction import HEADERS, PAY_SPLIT_NOTE
from home_manager.finance import paystub_tables
from home_manager.finance.ledger import Ledger
import paystub_engine_generator as gen
import pdf_import_fixtures as fx
from test_extraction import MISSING
from test_paystub_engine_record import Run, lines_of, no_network, printed_details, started  # noqa: F401 - no_network is the autouse C-net fixture
from test_paystub_split import segments_of
from test_pdf import pdf_store  # noqa: F401

COLLAPSE = re.compile(r"\s+")


def context(case, index, seed=gen.SEED):
    return f"seed {seed} case {index}: layout {case.choices}"


def collapse(text):
    return COLLAPSE.sub(" ", text.replace("|", " ")).strip()


def minor_of(text):
    """A printed amount in minor units, signed as printed: `(75.00)` and `-75.00` are negative."""
    negative = text.startswith("(") or text.startswith("-")
    value = int(Decimal(text.strip("()-").replace(",", "")) * 100)
    return -value if negative else value


def expected_rows(case):
    """The pay lines of every stub, as the engine should read their cells: (label, this period, year to date, hours, rate). Taxes and deductions
    are magnitudes (the printed sign is style only), as Record keeps them."""
    return Counter((collapse(line["description"]), line["current"], line["ytd"], line["hours"], line["rate"])
                   for stub in case.answers for line in stub["lines"])


def engine_rows(reading):
    """The engine's pay rows (not totals), as (label, this period, year to date, hours, rate) from the cells in their roles. A tax or deduction
    row is counted by magnitude (the printed sign is style)."""
    found = []
    for table in reading.adapted:
        roles = {index: role for index, role in table.roles.items()}
        for row in table.rows:
            if row.total:
                continue
            cells = {role: cell.quote.strip() for index, role in roles.items() if index < len(row.cells) for cell in [row.cells[index]]
                     if cell.quote.strip() and role in ("current", "ytd", "hours", "rate")}
            label = collapse(row.cells[0].quote)
            found.append((label, cells.get("current"), cells.get("ytd"), cells.get("hours"), cells.get("rate")))
    return found


def read(case, folder):
    result = fx.read_pdf(folder, case.pages)
    assert [page.method for page in result.pages] == ["embedded_text"] * len(case.pages)
    return result


def shown_rows(case, found):
    """The engine's rows in minor units, a tax or deduction row by magnitude, matched to the expected lines' groups by label."""
    groups = {collapse(line["description"]): line["group"] for stub in case.answers for line in stub["lines"]}
    rows = []
    for label, current, ytd, hours, rate in found:
        group = groups.get(label)
        convert = lambda text, group=group: None if text is None else (abs(minor_of(text)) if group in ("tax", "pre_tax") else minor_of(text))  # noqa: E731
        rows.append((label, convert(current), convert(ytd), hours, rate))
    return rows


# --- generator_only: the pay engine's rows against the generator's lines ------------------------------------------------------------------

@pytest.mark.parametrize("index", range(gen.CASES))
def test_generator_only_case_engine_rows_are_exact(index, tmp_path):
    case = gen.layout(index)
    where = context(case, index)
    reading = paystub_tables.read(read(case, tmp_path))
    assert reading.pages_without_tables == [] and not reading.unplaced, f"{where}: {reading.pages_without_tables} {reading.unplaced}"
    got = Counter(shown_rows(case, engine_rows(reading)))
    assert got == expected_rows(case), f"{where}: missing {expected_rows(case) - got}, extra {got - expected_rows(case)}"


# --- Record: every file through the real services ------------------------------------------------------------------------------------------

FIELDS = (("gross", "gross_pay", "gross_pay_ytd"), ("net", "net_pay", "net_pay_ytd"), ("taxes", "taxes", None), ("deductions", "deductions", None))
COLUMN_GUESS = re.compile(r"^Page \d+: the (?:left|right) column was taken as this period; the printed amounts didn't tell the two columns apart\.$")
BOX_GUESS = re.compile(r"^Page \d+: in the summary box, the left of the two columns was taken as taxes and the other as deductions, because no heading named them\.$")


class Generated(Run):
    """One generated file, read and then extracted through the real services; every answer of the model double is drawn from the case's answers."""

    def printed_lines(self):
        return [line for line in self.lines if line.text.strip()]

    def spans(self, case):
        """Each stub's (first, last) index among the printed lines, from the generator's own idea of the split: the line it starts at (the first line
        printing that text, after the previous stub's) less the heading lines printed above it, to the line before the next stub's first."""
        lines, firsts, search = self.printed_lines(), [], 0
        for stub in case.answers:
            at = next(number for number in range(search, len(lines)) if collapse(lines[number].text) == stub["start"])
            firsts.append(at - stub["above"])
            search = at + 1
        return list(zip(firsts, [*(first - 1 for first in firsts[1:]), len(lines) - 1]))

    def answer(self, case):
        """The contract's `local_model` by schema, one answer per stub in file order: the classification, the summary (each printed total given the
        other column's printed value) and each pay line's group and category citing its row; no pay line amount."""
        lines, spans = self.printed_lines(), self.spans(case)
        covered = {line_id for table in paystub_tables.read(self.evidence).adapted for line_id in [*(row.line_id for row in table.rows), *table.spans]}
        replies = {"Classification": [], "PaystubSummary": [], "PayRowClasses": [], "PayLines": []}
        for stub, (first, last) in zip(case.answers, spans):
            part = lines[first:last + 1]

            def find(needle, fallback=None, part=part):
                """The line printing the needle (a label and its first amount); else, where the reader cut a side-by-side row into several lines, the
                first line holding the fallback (the label, or the value's text)."""
                found = next((line for line in part if needle in collapse(line.text)), None)
                return found or next(line for line in part if fallback and fallback in collapse(line.text))

            def cite(needle, quote=None, fallback=None, find=find):
                line = find(needle, fallback)
                return [{"line_id": line.id, "quote": quote or line.text}]

            def value(text, needle, cite=cite):
                return {"value": text, "status": "proposed", "evidence": cite(needle, text, text)}
            fields = {name: MISSING for name in HEADERS["paystub"]}
            fields.update(payer_or_employer=value(stub["employer"], stub["employer"]), pay_date=value(stub["pay_date"], stub["date_line"]),
                          currency=value("USD", stub["currency_line"]))
            for kind, current_name, ytd_name in FIELDS:
                printed = stub["printed"].get(kind)
                if not printed:
                    continue
                current, ytd = printed["current"], printed["ytd"]
                given = ytd or current  # (needle, text): the other column's printed value when there is one
                fields[current_name] = value(given[1], given[0])
                if ytd_name and ytd:
                    fields[ytd_name] = value(current[1], current[0])
            replies["Classification"].append({"document_type": "paystub", "evidence": cite(stub["employer"]), "issuer": fields["payer_or_employer"],
                                              "document_date": fields["pay_date"]})
            replies["PaystubSummary"].append(fields)
            rows = [{"description": line["description"], "group": line["group"], "category": line["category"], "evidence": cite(line["cite"], fallback=line["label"])}
                    for line in stub["lines"]]
            runs = []  # The part's runs of lines the engine covers with rows, and the runs it doesn't: each is one question.
            for line in part:
                if not runs or (line.id in covered) != runs[-1][0]:
                    runs.append([line.id in covered, []])
                runs[-1][1].append(line.id)
            for engine, ids in runs:
                if engine:
                    replies["PayRowClasses"].append({"lines": [row for row in rows if row["evidence"][0]["line_id"] in ids]})
                else:
                    replies["PayLines"].append({"lines": []})
        replies["Classification"].insert(0, replies["Classification"][0])  # The file's own classification comes first.
        self.local_model["by_schema"] = replies
        self.before = len(self.local_model["requests"])
        return spans

    def records(self):
        """The income records of the file, by segment."""
        with self.store.connection() as db:
            found = [row["id"] for row in db.execute("SELECT id FROM income_records WHERE blob_hash=? ORDER BY segment", (self.service.get(self.parse_id)["blob_hash"],))]
        return [Ledger(self.store).record("income_record", income_id) for income_id in found]


def recorded(pdf_store, local_model, case, index):
    run = started(pdf_store, local_model, case.pages, name=f"generated-{index}.pdf")
    run.__class__ = Generated
    spans = run.answer(case)
    run.extract()
    return run, spans


def assert_records_exactly(case, where, run, spans):
    """Every stub: its pay lines (description, group, this period, year to date, hours, rate), the totals it prints, its pay date; its checks hold
    (counted automatically); the only notes are the split, the summary box's guess and a correct columns guess; the file split into its stubs."""
    records = run.records()
    assert len(records) == len(case.answers), f"{where}: {len(records)} records for {len(case.answers)} stubs"
    for number, (stub, record) in enumerate(zip(case.answers, records)):
        here = f"{where} stub {number}"
        assert record["pay_date"] == stub["pay_date"] and record["currency"] == "USD", here
        assert lines_of(record) == [(" ".join(line["description"].split()), line["group"], line["current"], line["ytd"]) for line in stub["lines"]], here
        assert printed_details(record) == [(line["hours"], line["rate"]) for line in stub["lines"]], here
        for name, expected in (("gross_pay_minor", stub["gross"]["current"]), ("gross_pay_ytd_minor", stub["gross"]["ytd"]), ("net_pay_minor", stub["net"]["current"]),
                               ("net_pay_ytd_minor", stub["net"]["ytd"]), ("taxes_minor", stub["taxes"]), ("deductions_minor", stub["deductions"])):
            assert record[name] == expected, f"{here}: {name}"
        assert record["review_status"] == "verified" and record["issues"] == [], f"{here}: {record['review_status']} {record['issues']}"
        notes = (record["details"] or {}).get("notes", [])
        allowed = [note for note in notes if note == PAY_SPLIT_NOTE or COLUMN_GUESS.match(note) or (stub["box_guess"] and BOX_GUESS.match(note))]
        assert allowed == notes, f"{here}: unexpected notes {notes}"
        assert (PAY_SPLIT_NOTE in notes) == (len(case.answers) > 1), here
        assert {guess["kind"] for guess in (record["details"] or {}).get("guesses", [])} <= {paystub_tables.COLUMNS_GUESSED, paystub_tables.BOX_COLUMNS_GUESSED}, here
    segments = segments_of(run.store, run.doc["id"])
    lines = run.printed_lines()
    if len(case.answers) == 1:
        assert segments == [], where
    else:  # Every line of the file is in exactly one segment: the stubs' own first and last lines.
        assert [(first, last) for _, first, last, _, _ in segments] == [(lines[a].id, lines[b].id) for a, b in spans], where
    assert Counter(run.asked())["PaystubSummary"] == len(case.answers), where  # The engine and the split rule asked nothing.


@pytest.mark.parametrize("index", range(gen.CASES))
def test_case_is_recorded_exactly_through_the_real_services(index, pdf_store, local_model):
    case = gen.layout(index)
    run, spans = recorded(pdf_store, local_model, case, index)
    assert_records_exactly(case, context(case, index), run, spans)


# --- generator_only: the other seeds, the generator's own rules and its coverage -----------------------------------------------------------------

SWEEP = tuple((seed, index) for seed in (1, 2, 3) for index in range(40))


@pytest.mark.parametrize(("seed", "index"), SWEEP)
def test_generator_only_other_seeds_engine_rows_are_exact(seed, index, tmp_path):
    case = gen.layout(index, seed=seed)
    where = context(case, index, seed)
    reading = paystub_tables.read(read(case, tmp_path))
    assert reading.pages_without_tables == [] and not reading.unplaced, f"{where}: {reading.pages_without_tables} {reading.unplaced}"
    got = Counter(shown_rows(case, engine_rows(reading)))
    assert got == expected_rows(case), f"{where}: missing {expected_rows(case) - got}, extra {got - expected_rows(case)}"


def test_generator_only_twice_gives_byte_identical_pdfs(tmp_path):
    for index in range(gen.CASES):
        first, second = gen.layout(index), gen.layout(index)
        assert first == second, context(first, index)
        assert gen.build(tmp_path / "a.pdf", first).read_bytes() == gen.build(tmp_path / "b.pdf", second).read_bytes(), context(first, index)
    assert gen.layout(0, seed=gen.SEED + 1) != gen.layout(0)  # Another seed gives other stubs.


def test_generator_only_every_fr70_variation_occurs_in_three_cases():
    seen = Counter()
    for index in range(gen.CASES):
        seen.update(layouts.variations(gen.layout(index)))
    missing = {tag: seen[tag] for tag in layouts.REQUIRED if seen[tag] < 3}
    assert not missing, f"seed {gen.SEED}: variations in fewer than 3 cases: {missing}"


def test_generator_only_follows_its_own_rules():
    """The rules that keep each stub decidable (plan P10): every stub prints section totals or headings naming its columns, and a gross figure to check
    against; this period is at most the year to date except on a negative row; all money is integer minor units and the arithmetic holds exactly;
    a file holds 1 to 4 stubs with their own pay dates, all before 2026-11-04."""
    for index in range(gen.CASES):
        case = gen.layout(index)
        choices, where = case.choices, context(case, index)
        assert choices["totals"] == "all" or choices["heading"].startswith("known"), where
        assert 1 <= len(case.answers) <= 4 and len(case.answers) == choices["stubs"], where
        dates = [stub["pay_date"] for stub in case.answers]
        assert dates == sorted(set(dates)) and dates[-1] < "2026-11-04", where
        for stub in case.answers:
            assert stub["gross"]["current"] is not None, where
            lines = stub["lines"]
            for line in lines:
                assert all(value is None or isinstance(value, int) for value in (line["current"], line["ytd"])), where
                negative = (line["current"] or 0) < 0 or (line["ytd"] or 0) < 0
                if line["current"] is not None and line["ytd"] is not None and not negative:
                    assert line["current"] <= line["ytd"], f"{where}: {line}"
            earnings = sum(line["current"] or 0 for line in lines if line["group"] == "earnings")
            taken = sum(line["current"] for line in lines if line["group"] != "earnings")
            assert stub["gross"]["current"] == earnings, where
            assert stub["net"]["current"] is None or stub["net"]["current"] == earnings - taken, where
            if stub["gross"]["ytd"] is not None:
                ytd = sum(line["ytd"] or 0 for line in lines if line["group"] == "earnings")
                assert stub["gross"]["ytd"] == ytd, where
                if stub["net"]["ytd"] is not None:
                    assert stub["net"]["ytd"] == ytd - sum(line["ytd"] for line in lines if line["group"] != "earnings"), where
