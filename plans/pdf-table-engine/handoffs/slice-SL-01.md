```yaml
slice: SL-01
result: ready_for_verification_with_escalation   # all checks pass; one contract expectation (NB) is an xfail, see escalations
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 4131858
end_head: cfdb7e4
commit: cfdb7e4
changed_files:
  - src/home_manager/documents/table_engine.py        # new
  - src/home_manager/finance/pdf_import.py             # PageView removed, re-exported from the engine; two unused imports dropped
  - tests/table_engine_fixtures.py                     # new
  - tests/test_table_engine.py                         # new
checks:
  - command: ".venv/bin/python -m pytest tests/test_table_engine.py -k \"pcheck or sc21 or rows or sc14\" -q"
    exit_code: 0     # 112 passed, 1 xfailed (NB rows)
  - command: ".venv/bin/python -m pytest tests/test_pdf_imports.py tests/test_statement_rebuild.py -q"
    exit_code: 0     # 218 passed, unchanged tests
  - command: ".venv/bin/ruff check src tests"
    exit_code: 0
skipped_checks: [mypy, browser tests, anything outside the three commands above]
escalations:
  - id: NB-P4
    summary: "Plan P4's two-row rule can't produce the contract's NB expected values."
```

## What was built
- `documents/table_engine.py`: `PageView` (moved verbatim, `pdf_import.PageView is table_engine.PageView`); P2 dataclasses (`Token`, `Column`, `EngineRow`, `EngineTable`, `EngineReading`, plus `Anchor`, `Total`, `Unplaced` as unused stubs); tokens (P3); columns by alignment with zones, heading labels and the heading-line rule (P4); rows from P5 rules 1–4 and section titles. Public entry: `read(result: PDFResult) -> EngineReading`; `read_tokens(words)` tags a run without a page (SC-21). It imports `core.money.EXPONENTS` only (for ISO codes), nothing from `finance/`.
- `tests/table_engine_fixtures.py`: all contract fixtures plus WR-above, with hand-written expected tables and the `FIXTURES` registry. `tests/test_table_engine.py`: P-checks, SC-21, rows for WF, WF-bare, WF-flag, DM, WR, OD, ONE, CS, TD, TD-bare, FX, SC-14 on every fixture (with `local_model` running and C-net active).

## Escalation: NB (SC-07 variant, engine rows)
NB has columns A (n2, n3) and B (n1 only), no heading. P4/FR-04 needs ≥ 2 supporting rows, so B forms no column; n1's `1,500.00` fits no zone and n1 is not a row. The contract expects B and all three rows. `test_rows_nb_finds_two_amount_columns_without_headings` is `xfail(strict=True)`; `test_rows_nb_column_a_alone_…` records what the engine does. I did not change the expected values or the rule. Options for the orchestrator: add a second B row to the NB fixture in the contract, or amend P4 (for example, a single-row group forms a column when it lies between or beyond formed columns and its edge lines up with the heading-less page). The last option would also make UP's `35.00` a column, so it needs care. OD's Deposits column has the same one-row shape but forms through its heading.

## Deviations and notes for later slices
- `json.dumps(asdict(x), sort_keys=True)` fails on `Decimal`, so SC-14 uses `default=str`. P2 says Decimal; if later slices want plain `json.dumps`, change `Token.value`/`Anchor.value` to strings.
- Date years are as printed (`26` stays 26); SC-21's `1-Oct-26 → 2026-10-01` is asserted as `(1, 10, 26, "month_name")`. Dot- and dash-dates need a year (`10.25` is an amount). Month-name dates, `CR`/`DR` and ISO-code joins are in tokenize.
- Heading support: labels within three visual rows above the table's first row count as one row of support for any group (OD's Deposits, ONE). Ties between alignments go to the smaller spread, then right, left, centre.
- Not in SL-01, left for SL-02: one table per page; no table end at balance/total titles, no continuation across pages (K3 forms three tables; page 3's Withdrawals column has one row and `82.40` lands in the description), no anchors/totals (BL's balance, total, daily and fee lines become rows), no unplaced lines (UP's `35.00` line and K3's stray amount are just not recorded as such), rule 5 rejections beyond rule 3's two texts, "more than one amount" (basic version), and rule 6, rule 7 (WR-above reads wrongly: shown as a fixture only), `kind` "schedule".
- The plan puts row numbers 1-based including rejected rows; `carried_from` points to the dated source row `(page, row)` (OD: o2 → (1,1), o4/o5 → (1,3)).
- Contract fixture geometry notes: TD's `Trans Date` (x 40) is about 52 pt wide and overlaps `Post Date` (x 90), so the engine reads them as one run and their heading labels come out as one `Trans DatePost Date` label on the second date column (labels only; columns and rows are right). ND-prior prints the balance and period lines above (the contract's stub table lists a period and balances for it but its fixture text does not print them). WR-above puts all of a row's description lines (first line plus continuations) directly above its date line.
- P-check on layout issues: the contract states issues only for WF-flag; the real reader reports `unresolved_columns` on pages it builds no native table for, so the P-check allows exactly that and nothing else on other fixtures.

## Open issues
- NB (above). Decision needed before SL-03/SL-05 rely on NB.
- `pdf_import.py` lost `math` and `statistics.median` imports (no longer used there).
