"""The layout generator through the real reader and the engine's statement path (specs/pdf-table-engine/test-contract.md SC-18, FR-33).

`generator_only` tests need no store and no model: each of the 200 seeded statements is written with `make_pdf`, read by the real PDF reader,
and run through `finance/statement_tables.read`. Every row must equal its expected row (date, signed amount, description) exactly, and the
statement must reconcile. A failure prints the seed, the case index and the layout choices. The expected rows come only from the generator's
inputs (`evals/statement_layouts.py`), never from the engine.
"""

from collections import Counter
from datetime import date

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
