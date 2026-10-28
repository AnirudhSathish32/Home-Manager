"""The layout generator through the real reader and the engine's statement path (specs/pdf-table-engine/test-contract.md SC-18, FR-33).

`generator_only` tests need no store and no model: each of the 200 seeded statements is written with `make_pdf`, read by the real PDF reader,
and run through `finance/statement_tables.read`. Every row must equal its expected row (date, signed amount, description) exactly, and the
statement must reconcile. A failure prints the seed, the case index and the layout choices. The expected rows come only from the generator's
inputs (`evals/statement_layouts.py`), never from the engine.
"""

from collections import Counter
from datetime import date
from pathlib import Path
import re
import subprocess
import sys

import pytest

from evals import statement_layouts as layouts
from home_manager.finance import statement_tables as stt
import pdf_import_fixtures as fx
import table_engine_generator as gen
from test_table_engine import no_network  # noqa: F401  C-net: autouse, so no test here connects to a non-loopback address.


def context(case, index):
    return f"seed {gen.SEED} case {index}: layout {case.choices}"


def read(case, folder):
    result = fx.read_pdf(folder, case.pages)
    assert [page.method for page in result.pages] == ["embedded_text"] * len(case.pages)
    return result


@pytest.mark.parametrize("index", range(gen.CASES))
def test_generator_only_case_reads_exactly(index, tmp_path):
    """Every row of the statement, with its exact date, signed amount and description; no issue; the printed summary and period."""
    case = gen.layout(index)
    answers = case.answers
    reading = stt.read(read(case, tmp_path), statement_type="credit_card" if answers["kind"] == "card" else "bank")
    where = context(case, index)
    got = [(row["posted_date"], row["amount_minor"], " ".join(row["description"].split())) for row in reading.rows]
    expected = [(day, amount, " ".join(text.split())) for day, amount, text in answers["rows"]]
    assert got == expected, where
    assert reading.issues == [] and reading.dropped == 0 and not reading.unplaced, f"{where}: {reading.issues}"
    assert reading.period == (tuple(answers["period"]) if answers["period"] else None), where
    assert (reading.opening_minor, reading.closing_minor) == (answers["opening"], answers["closing"]), where
    if answers["opening"] is not None:  # Reconciles: the opening and the rows give the closing (a card's balance is what is owed).
        net = sum(row["amount_minor"] for row in reading.rows)
        assert reading.closing_minor == reading.opening_minor + (-net if answers["kind"] == "card" else net), where


def test_generator_only_twice_gives_byte_identical_pdfs(tmp_path):
    for index in range(gen.CASES):
        first, second = gen.layout(index), gen.layout(index)
        assert first == second, context(first, index)
        assert gen.build(tmp_path / "a.pdf", first).read_bytes() == gen.build(tmp_path / "b.pdf", second).read_bytes(), context(first, index)
    assert gen.layout(0, seed=gen.SEED + 1) != gen.layout(0)  # Another seed gives other statements.


def test_generator_only_every_fr33_variation_occurs_in_five_cases():
    seen = Counter()
    for index in range(gen.CASES):
        seen.update(layouts.variations(gen.layout(index)))
    missing = {tag: seen[tag] for tag in layouts.REQUIRED if seen[tag] < 5}
    assert not missing, f"seed {gen.SEED}: variations in fewer than 5 cases: {missing}"


def test_generator_only_follows_its_own_rules():
    """The rules that keep each case decidable (SC-18): a running balance or a summary; a printed period for year-less dates; a period that
    decides the order when every numeric date has a day of 12 or less."""
    for index in range(gen.CASES):
        case = gen.layout(index)
        choices, answers = case.choices, case.answers
        where = context(case, index)
        assert choices["balance"] or choices["summary"], where
        assert (answers["opening"] is not None) == choices["summary"], where
        if choices["dates"] in layouts.NEEDS_PERIOD:
            assert answers["period"], where
        numeric = choices["dates"] in layouts.NUMERIC
        days = [date.fromisoformat(day) for day, _, _ in answers["rows"]]
        if numeric and all(day.day <= 12 for day in days):
            start, end = (date.fromisoformat(day) for day in answers["period"])
            assert layouts.decides_order(days, choices["dates"], start, end), where
        assert all(isinstance(amount, int) for _, amount, _ in answers["rows"]), where  # Money is in minor units.


PROBE = Path(__file__).resolve().parents[1] / "scripts" / "statement_diagnose.py"
MONEY = re.compile(r"\d[\d,]*\.\d{2}\b")


@pytest.mark.parametrize("index", [4, 5, 20, 25])
def test_generator_only_probe_prints_no_document_text_or_amounts(index, tmp_path):
    """OD-6: the redacted probe (scripts/statement_diagnose.py) runs on a generated PDF and its output holds no word, date or amount the document
    prints. Words the probe prints by design (column kinds and roles, `page`, `rows`) are the only ones the document may share with it."""
    case = gen.layout(index)
    pdf = gen.build(tmp_path / "statement.pdf", case)
    card = case.answers["kind"] == "card"
    done = subprocess.run([sys.executable, "-I", str(PROBE), str(pdf), "2026", *(["card"] if card else [])], capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, f"{context(case, index)}: {done.stderr[-300:]}"
    output = done.stdout
    printed = [text for page in case.pages for _, _, text, *_ in page["items"]]
    # The document's own words are the capitalised ones (names, descriptions, headings); the probe's prose is lower case, apart from its
    # section names (`Page`, `Table`) and the column names it prints as kinds, which a heading may share.
    allowed = {"Date", "Description", "Details", "Amount", "Balance", "Posted", "Transaction", "Net", "Page", "Table"}
    words = {word for text in printed for word in re.findall(r"[A-Z][A-Za-z]{2,}", text)} - allowed
    leaked = sorted(word for word in words if re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", output))
    assert not leaked, f"{context(case, index)}: the probe printed document words {leaked}"
    amounts = {money for text in printed for money in MONEY.findall(text)}
    assert not amounts & set(MONEY.findall(output)) and not MONEY.search(output), f"{context(case, index)}: the probe printed an amount"
    dates = {day for day, _, _ in case.answers["rows"]}
    assert not any(day in output or day[2:] in output for day in dates), context(case, index)
    for text in printed:
        if re.fullmatch(r"[\d./-]{5,10}|\d{2}/\d{2}(/\d{2,4})?", text):
            assert text not in output, f"{context(case, index)}: the probe printed the date {text}"
    assert "=== Table engine" in output and "first chain-break row:" in output and "roles decided by" in output, output[-400:]
