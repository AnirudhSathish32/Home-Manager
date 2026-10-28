```yaml
slice: SL-03
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
resumed_from_attempt_1_diff: true     # attempt 1 (rate limit) left an uncommitted partial diff on a602cad; kept, debugged, committed in steps
start_head: a602cad
end_head: HEAD          # the handoff commit on top of code commit f7a09f2 (git log -1 on this file)
commit: f7a09f2                        # last code/test commit; the handoff file is committed on top of it
changed_files:
  - src/home_manager/finance/statement_dates.py       # new: Rebuild (+opening_minor, closing_minor, period), read_period, placed, duplicates, PERIOD_SLACK, NO_LAYOUT_NOTE
  - src/home_manager/finance/statement_rows.py        # imports and re-exports the moved names; nothing else changed
  - src/home_manager/finance/statement_tables.py      # new: the statement layer
  - src/home_manager/documents/table_engine.py        # period lines; read(..., amounts=True) option; finish() local-name fix
  - tests/test_table_engine.py                        # 54 new statement-level tests (stmt_*)
  - plans/pdf-table-engine/handoffs/slice-SL-03.md
checks:
  - command: ".venv/bin/python -m pytest tests/test_table_engine.py -q"
    exit_code: 0     # 243 passed (189 from SL-01/02 + 54 new)
  - command: ".venv/bin/python -m pytest tests/test_pdf_imports.py tests/test_statement_rebuild.py -q"
    exit_code: 0     # 218 passed, 2 warnings, 232 s; unchanged tests, run on the final src
  - command: ".venv/bin/ruff check src tests"
    exit_code: 0
skipped_checks: [mypy, browser tests, test_table_engine_record/generator (SL-04/05), anything else]
escalations: []
```

## What was built
Resumed from attempt 1's uncommitted diff (it was close: it imported and read most fixtures to the contract values). I kept it, fixed
what the tests showed, and wrote the tests (attempt 1 wrote none).

- **`finance/statement_dates.py`**: the moved helpers, unchanged except `Rebuild` gains `opening_minor`, `closing_minor`, `period`
  (default None). `NO_LAYOUT_NOTE` moved with them. Imports nothing from `pdf_import`, `statement_rows` or `statement_tables` (a test
  reads its source for that). `statement_rows` re-exports `Rebuild`, `read_period`, `placed`, `duplicates`, `PERIOD_SLACK`,
  `NO_LAYOUT_NOTE`; the old reader and its callers are untouched otherwise.
- **`finance/statement_tables.py`**: `read(result, *, statement_type, currency, fallback_period, choices, prior_order)` →
  `StatementReading`; `.as_rebuild()`; `engine_pages(result)`; `decided_order(result)` (the order decision without OD-2, so it never
  recurses); `prior_order(db, last_four, document_id)` (newest first, ≤ 10, PDF readings only, other documents only).
  - *Roles* by enumeration (≤ 6 amount columns, ≤ 1 balance, one signed or in/out), tiers chain → summary → b′ (most holding links) →
    headings → type default, with per-row FR-12 signs (own marker, then section title, then default; both whole-column conventions
    also tried), tie rule "same money / fewest other / labels agree, else undecided". `other` columns and the balance column are never
    amounts; Decimal → `to_minor` only in money columns (the engine runs with `amounts=False`, so FX's rate is never parsed).
  - *Rejections needing roles*: both a debit and a credit; unreadable / too-precise amount only in a money column; the statement
    currency check (`The amount "4.00 EUR" is not in USD.`).
  - *Anchors inside tables* are re-classed per candidate (balance column → anchor, else a row); FR-17's two-chains issue; FR-15's
    first chain break; FR-13's reason; pending rows (R4) as `Unplaced(reason="pending")`; unplaced lines carried over from the engine;
    period line (P8), order (day over 12 → period fit → `prior_order` → user choice → undecided, one issue per page), year via
    `placed`, schedule kind (a whole table, or a run of ≥ 2 rows after a title/page top, every date outside period ± 7 days; none
    without a period), OD-1 carried dates and notes, the FR-19 `NO_TABLE` note, `duplicates`.
- **`documents/table_engine.py`** (small additions): `EngineReading.period_lines` is now filled (outside every table, exactly two
  four-digit-year dates, no amount); `read(result, currency=None, amounts=True)` – with `amounts=False` no row is rejected for
  its amounts, because the statement layer knows which columns are money.

## Fixes made on top of attempt 1's draft (all keep every contract value)
1. **Order decision with a whole-table "schedule"** (found with OD): under the wrong order every OD date falls outside the period,
   so the whole table counted as a schedule and "fit" trivially; both orders then fit and the order stayed undecided. A whole table
   outside the period is now no evidence for an order (only partial runs are left out of the fit test).
2. **FX roles**: the foreign amount column was chosen as `balance` (a tie on the money, fewest-`other` won), giving a bogus chain
   issue. A balance column nothing supports (no holding link, no heading saying balance) now loses ties to `other`
   (`Candidate.unsupported`).
3. **`finish()` shadowed its `amounts` flag** with the list of amount columns, so `amounts=False` did nothing; renamed the local.
4. `StatementReading.pages` came from the engine before schedules/pending rows were split out (BL reported pages {1, 2}); now it is
   computed from the settled tables (+ pending rows' pages). `engine_pages` runs the same reader so the two agree.
5. Cleaned the currency check (`problem()`), a junk `dropped` term, `AND p.result_json IS NOT NULL` in `prior_order`, ruff imports.

## Deviations and notes (none changes a contract value)
- **P7 tie rule extension**: the `unsupported`-balance preference above is an addition to P7.5's tie-break ("fewest other columns, then
  labels"). Needed for FX (SC-23). Please confirm or amend P7.5.
- **FR-13 reason also on undecided-but-labelled readings** uses a separate text (`ROLES_DIFFER`) when the strongest tier held
  candidates that disagree; P9 has no wording for that case (G11/G16 leave wording open). Roles wholly undecided with nothing to fall
  back on: `ROLES_UNKNOWN` ("…can't be told, so its rows weren't recorded."), rows not recorded, `dropped` counts them.
- **Not done / carried on**: (1) `as_analysis()` (PDF import adapter) is left for SL-06 as allowed. (2) P6's mid-page cut "at a
  different column set that starts a run of ≥ 2 rows": no fixture or contract value needs it (CC's second table is on its own page);
  not implemented — SL-04's generator should say if it is needed. (3) Record-only items (FR-07 note when the model's value differs,
  record-note routing, locator reuse) are SL-05.
- A statement-level `unreadable amount` in a table whose roles can't be decided is not listed as its own issue (the per-page
  "roles can't be told" issue covers the table); rows are counted in `dropped`.
- `prior_order`'s SQL was checked against `050_strict_tables.sql` (columns `statements.account_id/document_id/extraction_run_id/
  period_end`, `extraction_runs.parse_run_id`, `parse_runs.parser_version/status/result_json`, `accounts.account_last_four`) and is
  unit-tested on a loose-typed in-memory database with those columns; SL-05 should also run it on a real migrated library.

## Tests added (`tests/test_table_engine.py`, `stmt_*`; expected values are the fixtures' contract literals)
WF and WF-bare (roles by chain, balance on the locator), WF dated anchors, WF-flag, DM, BRK (row 14's issue text, tier b′), WR,
WR-above, WR-split, OD (three notes, period decides), ONE (FR-13 reason), CS (summary tier), CS-split (sections), NB with and without
its summary, K3, BL (anchors, totals, daily balance table, schedule kind, identity; and no schedule without a period), UP, PR note,
x1–x6 at statement level, both-debit-and-credit, precision only in money columns, CC (FR-17, no chain issue), ND (two order issues;
stub prior giving day-first; stub None; choice; the stub never called when the dates decide), `decided_order`, `prior_order` on a
tmp database (newest decides, own document and other last fours excluded, non-PDF/failed readings ignored), FX (roles other/other/
signed; unreadable rate does not reject), PD (pending), TD and TD-bare, FR-12 markers (CR, minus, parentheses), FR-14 fallback and
choice, `as_rebuild` shape and locator keys, no-layout reading, `engine_pages`, re-exports and the import-free `statement_dates`,
determinism for every fixture, and the engine's own tables unchanged by the statement layer.

## Open issues
- P7.5 tie extension and the ROLES_DIFFER / ROLES_UNKNOWN wording above need a nod (no contract value depends on them).
- `as_analysis()` for SL-06; the mid-page different-column-set cut is unimplemented (see above).
