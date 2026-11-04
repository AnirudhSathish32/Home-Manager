```yaml
slice: SL-01
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 44f40b0
end_head: a2468c8   # the code commit; one later commit only corrects this file's hashes
commit: a2468c8
checks:
  - command: ".venv/bin/python -m pytest tests/test_paystub_engine.py -k \"pcheck or rows or blocks or sections or totals or other_tables or unplaced or continuation\" -q"
    exit_code: 0   # 156 passed (the whole module is these 156 tests)
  - command: ".venv/bin/python -m pytest tests/test_table_engine.py -q"
    exit_code: 0   # 280 passed; table_engine.py and test_table_engine.py have no diff
  - command: ".venv/bin/ruff check src tests"
    exit_code: 1   # 2 errors in files this slice did not touch (tests/test_document_v2_browser.py:410, tests/test_receipt_kinds.py:977); the slice's three files are clean
escalations: []
```

# SL-01 handoff: pay table engine (resume)

A previous worker left `pay_tables.py`, `paystub_engine_fixtures.py` and `test_paystub_engine.py` uncommitted. I read all three against the spec, test contract and plan P3, kept them, and fixed the six failing tests. No fixture expected value was changed.

## What was wrong and how it was fixed
- **P-check helper, PS-OTHER leave table (the failure the orchestrator saw):** the helper picked words by text only, so `24.00` in the Sick row's Accrued *and* Balance columns both matched. The helper's fault. It now also requires the word's right edge to be within 3 pt of the column's stated edge, so a misaligned fixture still fails on the count.
- **P-check STK:** the row window started one visual row too late (it skipped `Federal Income Tax`). The window is now `(10, 99)`.
- **P-check SBS labels at x 300:** `F` has a 0.86 pt left side bearing, so the saved box starts at 300.86. Tolerance for label lefts is 1.5 pt, with a comment. The 0.5 pt rule still applies to amount right edges.
- **Engine, `Total Tax`:** the regex `taxes?` didn't match `tax`. Now `tax(?:es)?`.
- **Engine, section title over a headerless first table (B1, PS-BONUS):** the `Currency USD` header line directly above the first row became the rows' `section`. FR-54 says a section title belongs to a table. A title now counts only when a table is open, a heading is pending above it, or a table was already opened in the block (STK's `Statutory` and `Voluntary`, PS-SEC's titles). The contract's B1 expectation (no section) now holds.
- **SBS test:** compared layout line ids, but the reader gives the left and right groups of one printed line separate layout lines. It now compares visual rows (`PageView.row_of`), which is what the contract means by "the same lines". (This matters for SL-03's line-id mapping: a side-by-side row maps to its own layout line, not a shared one.)
- **Added** the contract's `MINI-C` fixture (one amount column, no YTD) with its expected facts and a test (`test_rows_a_stub_with_no_year_to_date_column…`). Without it, the fixtures section was incomplete.
- `ruff --fix` sorted one import block in the test module.

## Behaviour of `documents/pay_tables.py` (for SL-02/03)
`read(result: PDFResult) -> PayReading(tables, boxes, other_tables=[], unplaced, pages_without_tables)`. `other_tables` stays empty: classifying pay vs other tables is SL-02. `PayReading.tables` holds every table found, including PS-OTHER's deposit and leave tables (they are separate tables, ended by net pay / a new heading line).
- Beyond P2: `PayRow.stray` (amounts of a row that sit in no column, kept on the row and not unplaced), `PayTotal.row`/`table_id`, `PayTable.lead` (title line above the heading, e.g. `Direct Deposit`; for the SBS left table it is `Currency USD`, which is harmless but not meaningful), `SummaryBox.id`. `PayTotal.kind` can also be `employer` (total employer contributions).
- `PayRow.row` numbers rows and totals together in printed order (1-based); the adapter's `<table>-row-<r>` in P4 can use it.
- `PayColumn.id` is `<table id>-column-<n>`; amounts are keyed by column id.
- Unplaced text includes the amount (`Bonus advance memo 75.00`); SL-04's note format should account for that.
- The module imports only `table_engine`, `dataclasses`, `itertools`, `re` and `statistics` (a test pins this). `table_engine.py` is unchanged.

## Not covered
Pay-vs-other classification, roles, guesses and box semantics (SL-02). No test calls the engine on a vision page; non-`embedded_text` pages are skipped by design.
