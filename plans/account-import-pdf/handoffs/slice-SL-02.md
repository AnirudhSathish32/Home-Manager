```yaml
slice: SL-02
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: c0d3c0a
end_head: <the commit; see `git log -1`>
commit: <this commit>
changed_files:
  - src/home_manager/finance/pdf_import.py      # new, pure: analyze() and its parsing helpers
  - tests/test_pdf_imports.py                   # 48 analyzer tests (test_analyzer_*), appended; the P-check tests are untouched
  - tests/pdf_import_fixtures.py                # additive: summary_below_pages, second_heading_pages, synthetic_page/synthetic_result, imports
  - plans/account-import-pdf/handoffs/slice-SL-02.md
checks:
  - command: ".venv/bin/python -m pytest tests/test_pdf_imports.py -k \"analyzer or sc07 or sc24 or sc25 or sc16\" -q"
    exit_code: 0   # 57 passed, 26 deselected
  - command: ".venv/bin/python -m pytest tests/test_pdf_imports.py -k pcheck -q"
    exit_code: 0   # 35 passed
  - command: ".venv/bin/python -m pytest tests/test_pdf_imports.py tests/test_pdf.py tests/test_pdf_layout.py tests/test_tabular.py -q"
    exit_code: 0   # 132 passed
  - command: ".venv/bin/ruff check src/home_manager/finance/pdf_import.py tests/test_pdf_imports.py tests/pdf_import_fixtures.py"
    exit_code: 0
  - command: ".venv/bin/python -m mypy"
    exit_code: 1   # 8 errors, all in core/paths.py (Windows-only attributes), identical at START_HEAD; none in pdf_import.py
escalations: []
```

# SL-02 handoff: the pure analyzer

`finance/pdf_import.py` is new and pure (no DB, no store, no `models/` import). Spec, plan, `progress.yaml`, approvals, `reviews.md`,
the reader (`pdf_layout.py`, `pdf_reader.py`) and `tabular.py` are untouched. The index functions (`index_row`, `pending`, `backfill`,
`ANALYZER_VERSION`) are SL-06 and are not here. No expected value in the contract changed; none is computed by `pdf_import`.

## Interface as built

`analyze(result, *, tables=None, year=None, date_format="auto", sign=None, account_type=None, currency) -> Analysis`

- `currency` is required: the account's (or the request's) currency. `tables` are ids of selectable tables (None: all). Unknown id or an
  `other` table raises `PDFImportError`. `PDFImportError(ValueError)` is also raised over a limit: `MAX_ROWS` (20,000; module-level, a
  test can lower it; message "...exceeds N data rows...") and `MAX_CELL` (2,000; "...a cell exceeds the 2,000-character limit").
- Dataclasses `Analysis`, `ImportTable`, `ImportRow`, `ImportIssue` (all `dataclasses.asdict`-able).
  - `Analysis`: `tables`, `rows`, `issues` (blocking ones first, then by page, capped at `MAX_ISSUES = 200`), `counts` (`seen`, `parsed`,
    `rejected`, `left_out`, `pages_without_rows`; exact), `required` (subset of `["year","date_format","sign"]`, in that order), `mapping`
    (role to heading text of the first selected non-continuation table), `last_fours` (`{"4821": first page}`), `document_currency`,
    `sign_default`, `sign` (the choice, else the default), and the property `blocked` (message of the first issue coded
    `reading_without_layout` or `document_currency_mismatch`, else None).
  - `ImportTable`: `id`, `page`, `kind` (`transactions` | `rebuilt` | `continuation` | `other`), `linked_to`, `headings`, `columns`,
    `rows` (keys, only when selected), `row_count` (seen even when unselected), `selected`, `selectable`.
  - `ImportRow`: the plan's fields plus `continued_from` (page number or None, for the locator).
- Ids: native tables keep the reader's id (`page-1-layout-table-1`); rebuilt `page-N-import-table-K`; continuation `page-N-import-continuation`.
  Row key `"<table_id>:<row>"`. Native rows: the reader's row index (heading 0); below-table rows continue it (V: v3..v5 = 3..5); rebuilt and
  continuation rows count candidates on that page from 0 (k5 = `page-2-import-continuation:1`).
- Issue codes: `scanned_page`, `no_table` ("Page N: no transactions table found"), `no_rows`, `second_heading`, `rejected_row`,
  `unassigned_column`, `pdf_layout_review` / `pdf_table_ambiguous` (the page's reader issue, when it flags rows), `reading_without_layout`,
  `document_currency_mismatch`.
- Public helpers also usable by SL-03: `PageView`, `NO_LAYOUT`, `MAX_ROWS`, `MAX_CELL`, `SIGN_DEFAULTS`, `LAST_FOUR`.

## Choices where the plan was silent (please confirm in verification)

1. **Continuation entries are not independently selectable** (`selectable=False`): they are selected exactly when the table they continue is.
   A continuation id inside `tables` is accepted and ignored. (The plan lists them as tables but only "selectable tables" get checkboxes.)
2. **Rows are only produced for selected tables**; `row_count` is computed for all so the preview can show what an unticked table holds.
3. **Rejection order of reasons** for one row: structural (straddling date or amount, two amounts / text in an amount column), then date, then
   blank description, then amount/currency. First reason wins; every rejection is also an issue `Page N row M: <reason>`.
4. **Sign unresolved** (single Amount column, no `sign`, account type without a default): rows are parsed, `amount_minor` is None and
   `required` has `sign`. **Year or date order unresolved**: `posted_date` is None, no rejection (an impossible month/day is still rejected, with
   a leap year assumed for `02/29` until the year is known).
5. **Document currency mismatch**: the blocking issue is added *and* every row whose amount prints another currency is also rejected
   individually (so SC-18 step 1 shows both).
6. **`pages_without_rows`** counts every page (native or scanned) that is the source of no row in the selected tables.
7. A rebuilt table with a heading and zero candidate rows is listed and adds `Page N: no rows found under the transactions heading.`
   (`no_rows`); a continuation page with no candidates is not listed as a table and is reported "no transactions table found".

## Observations (no change made, within the plan's text)

- A native `other` table on a **continuation** page is never absorbed (the plan absorbs only into rebuilt tables and below-table rows), so a
  wrong reader table that shares baselines with continuation rows would be listed as "not a transactions table" next to the rows.
- A second transactions heading on a **rebuilt** page (not native) is not specially handled: the plan reports it only below a native table.
- In the synthetic second-heading fixture the reader also builds a wrong 2-column `Date | Description` native table from the unread rows; it
  stays listed as `other` (it shares no baseline with a candidate row). The test asserts only the issue and that C2/C3 are not rows.

## Tests (`tests/test_pdf_imports.py`, all `test_analyzer_*`, on real readings)

K (rebuilt page 1, two continuations, labels, locators, totals), selection and determinism, K2/K0 and the 10 SC-05 patterns, R (year and sign
by account type, SC-02/SC-03), X and 7-a to 7-e, the two synthetic cases (Summary below a native table; second visual heading), F (unticked
rows, message, left out), Fn (8-a), M and 9-a (scanned page, via `local_model`, no extra requests), a layout-less reading (blocked),
Keur / 18-a, D-ny / D-bad / D-full / D-amb / D-2y, V (5 rows; v3..v5 below-table, rows 3..5, reasons), SC-16 (20,001 refused, 20,000 accepted
on an in-memory `PDFResult`, lowered `MAX_ROWS`, 2,001-character cell, 250 rejected rows give 200 issues), and a test that the analyzer's
`PageView` grouping equals the SL-01 fixture helpers and every native table. Import steps of SC-07/SC-24/SC-25 are SL-03 and are not here.

## For the next slice

- Preview/import code should call `analyze` with the resolved `currency` and `account_type`, then apply the user's `ticked`/`unticked` over
  `row.ticked` and recompute `left_out`; `counts` are the analyzer's defaults.
- `required` empty and `blocked` None are the preconditions for import; rows with `rejected` are never inserted; fingerprint over all
  `parsed` rows in `Analysis.rows` order (P3).
