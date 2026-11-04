```yaml
slice: SL-08
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 7d3813b
end_head: 3b7735a   # the code commit; this handoff is committed right after it
commit: 3b7735a
checks:
  - command: ".venv/bin/python -m pytest tests/test_paystub_engine_generator.py -q"
    exit_code: 0   # 363 passed in ~3.5 min (120 Record cases, 120 engine-only cases, 120 engine-only cases of seeds 1-3, byte-identical, coverage, rules)
  - command: ".venv/bin/python -m pytest tests/test_paystub_engine.py tests/test_paystub_engine_record.py tests/test_paystub_split.py tests/test_table_engine.py -q"
    exit_code: 0   # 571 passed before the last two engine edits; re-run below with a wider set
  - command: ".venv/bin/python -m pytest tests/test_paystub_engine.py tests/test_paystub_engine_record.py tests/test_paystub_split.py tests/test_table_engine.py tests/test_layout_consumers.py tests/test_paystub_forms.py tests/test_paycheck.py tests/test_extraction.py tests/test_table_engine_record.py tests/test_table_engine_generator.py tests/test_pdf_layout.py -q"
    exit_code: 0   # 1121 passed, on the final source (statements' phase 1 generator included)
  - command: "RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_paystub_engine_browser.py -q"
    exit_code: 0   # 3 passed (extra: the engine's tables feed the Tables tab)
  - command: ".venv/bin/ruff check src tests evals"
    exit_code: 1   # only the 2 errors present at START_HEAD (tests/test_document_v2_browser.py:410, tests/test_receipt_kinds.py:977); my files are clean
escalations: []   # none blocking; the engine changes below need the orchestrator's eye (E1 - E3 are decisions to review)
```

# SL-08 handoff: the seeded pay stub layout generator

## What was built
- **`evals/paystub_layouts.py` (new).** `make(seed, index, **choices) -> Layout(pages, answers, choices)`, positions and texts as `make_pdf` takes them (no PDF written). `answers` is one dict per stub in file order, from the generator's inputs only: employer, pay date, every pay line (full description, label, group, category, this-period / year-to-date minor units or `None` for a blank cell, hours and rate as printed), gross / net / taxes / deductions where the stub prints them (else `None`), the printed text that cites each, and the split (`start` line text, `above` heading lines). Every FR-70 dimension is a balanced draw: one table, stacked tables, side-by-side blocks; summary box with / without headings / shuffled; Hours/Rate, YTD hours, 4-decimal rates; four column orders; headings known / unknown / none, one or two lines; with and without YTD; YTD-only row; retro and negative lines; label digits (`401K`, `PRE-TAX 401K`, `SECTION 125`, `403(b)`); plain / parenthesised / minus deductions; totals all / gross and net / none (box only); employer-cost column; wrapped label; two pages; deposit and leave tables; 1-4 stubs, employer heading above or below the pay date, pay date alone or with a pay period line in either order (M4), one or two stubs on a page. `variations()` and `REQUIRED` list what a case shows. Rules (plan P10, plus what the engine needs to be decidable): totals present or headings known; every YTD is about the stub's own multiple of the amount (so net YTD >= net current and the arithmetic holds exactly); a gross figure is always printed (totals or box); a net pay line in every stub; dates before 2026-11-04.
- **`tests/paystub_engine_generator.py` (new, thin).** `SEED = 20261104`, `CASES = 120`, `layout()`, `build()` via `make_pdf`.
- **`tests/test_paystub_engine_generator.py` (new).** (a) `test_case_is_recorded_exactly_through_the_real_services[0-119]`: each file read by the real reader and recorded through `ExtractionService` with `local_model` stubs drawn from the case's answers (classification; summary with every printed total given the other column's printed value, so a model value would be wrong; pay line group and category citing the row, no amounts). Asserts per stub: every line (description, group, this period, YTD, hours, rate), gross / net / taxes / deductions / pay date exact, C-auto (`verified`, no issues), notes only the split note, the summary box's guess and a correct columns guess, guesses only of those kinds, the file's `document_segments` equal the expected first / last lines (none for one stub), one summary question per stub. (b) `generator_only` tests (no store, no model): engine rows against the expected lines for 120 cases of the fixed seed and 120 of seeds 1-3; regeneration is byte-identical; every FR-70 variation occurs in >= 3 cases (all in >= 8); the generator's own rules. A miss prints seed, index and the layout choices.

## Engine / Record repairs the generator found (each listed, existing tests all green)
All in `documents/pay_tables.py` unless stated; each is pinned by generator cases (no new unit test of its own; see "Open").
1. **Summary box above side-by-side blocks** was cut in two by the block split and never found. Boxes are now found on the whole page first (`taken`), then blocks are read.
2. **Repeated stub heading on a later page ended the open table.** A start line that prints only dates already printed by the stub being read (`stub`, per block) now continues the table (FR-55, FR-80); a different date still ends it (STUBCUT unchanged); a net pay still resets.
3. **A start line ends the table of an empty block too** (`starts` found on the whole line): two side-by-side stubs on one page no longer share a right-hand table.
4. **A second table with the same heading words was ignored as a repeated heading.** A heading repeats the open table's only when the row after it prints in the table's columns (`repeats`).
5. **Side-by-side partner with more tables on the page** (a deposit or leave table under the left block): the right table now pairs with the left table it shares lines with (was only paired when exactly two tables), so it is a pay table (FR-56).
6. **Heading phrases printed close together read as one run** (`This Period` `Year to Date`) are split between the column zones they lie over.
7. **A text-only line of several runs is not a wrapped label** (the leave table's heading, cut by a block, was joined to the row above): requires one run on the whole page line.
8. **Continuation mapping** (`offset_of`) compares a group with a column at every alignment, since the same column can be right-aligned on one page and left- or centre-aligned on another (equal-width amounts); this had put page 2's amounts into the Hours / Rate columns. `Group.boxes` / `edge_at`, `Builder.frame` is now `{key: {alignment: edge}}`.
9. **`documents/paystub_split.py`**: a line holding only the net pay label counts as the stub's net pay (the reader prints a column of labels beside a column of amounts on pages with no table it recognises, so "Net Pay" and its amount were separate lines and a file of several headless stubs never split). Docstring updated.
10. **`documents/extraction.py`** (one line): a pay stub's summary `taxes` and `deductions` are magnitudes however printed (`(501.23)` / `-501.23`), as its lines already were; before, a stub printing deductions in parentheses recorded `taxes_minor` negative.

## Decisions to review
- **E1 (9 and 10 touch behaviour beyond the engine).** Both are small and judged defects against FR-61 / FR-80 as written ("value copied exactly"; "net pay line"). If you disagree, 9 can be undone by giving those cases a heading the reader recognises; 10 by dropping the minus / parentheses variation for taxes totals.
- **E2 (generator avoids, not an engine change):** (i) a table of rows that are all printed negative with year to date left of this period and no heading cannot be told apart by the numbers (FR-57 c says negative rows don't vote), so such a stub is drawn with this period left; (ii) a stacked layout's page break is placed before the third table, never at the top of the second (a table that starts a page within 80 pt of the open table's columns is read as its continuation); (iii) a headless stub prints hours on two rows (FR-04: a column needs two rows); (iv) a one-column table has no two-line heading (its upper word is a single run, not heading-like); (v) hours are never equal to the stub's year-to-date multiple (hours x current would then equal year to date, a product the numbers can't tell from hours x rate); (vi) leave-table columns are moved off any amount already printed, by left, centre or right edge, within the tolerance (the engine's alignment groups merge columns of different tables that line up). None changes a spec rule; (ii), (v) and (vi) are real engine ambiguities a user's stub could hit (they fall back to guesses or wrong columns, never to an invented number); worth a look in R-A.
- **E3 runtime.** The module takes ~3.5 min (Record cases ~1.4 s each x 120; the rest ~35 s). Phase 1's test samples 10 files through Record; the contract and task ask for all.

## Open / not done
- No separate engine unit tests for repairs 1-8; the 360 generated cases are their tests (any of them fails a case if reverted; not each individually verified by reverting).
- Documentation of the generator (docs/evals.md) and the probe test (`-k probe`) are SL-09.
- `progress.yaml` untouched and uncommitted.
