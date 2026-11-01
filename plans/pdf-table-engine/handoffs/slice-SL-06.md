```yaml
slice: SL-06
result: ready_for_verification   # r3: all four verification commands exit 0; escalations 1-4 resolved by the user and the contract/plan amendment (3b46c5a)
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: ba6b1c6       # r3 start; r1 started at 90bf5b1
end_head: HEAD            # the handoff commit on top of code commit 2067fc9 (git log -1 on this file)
commit: 2067fc9           # last code/test commit (r1 code commits: 1e726c2, 68b7aeb, 284ff12, a995034, dd40b48, df8367c, d29bfb5, ba227c0)
code_commits: [1e726c2, 68b7aeb, 284ff12, a995034, dd40b48, df8367c, d29bfb5, ba227c0, 2067fc9]
changed_files:
  - src/home_manager/finance/pdf_import.py          # analyze = adapter over the engine (as_analysis); analyze_legacy = the old body; ANALYZER_VERSION = 3
  - src/home_manager/finance/statement_tables.py    # per-row outcomes, shared piece names, year walk, FR-13 reason for a one-row statement, outcome_key
  - src/home_manager/finance/ledger.py              # pdf_state: prior_order closure, engine-fault refusal (message G12)
  - src/home_manager/finance/statement_rows.py      # imports analyze_legacy
  - src/home_manager/documents/table_engine.py      # five engine repairs (escalation 4)
  - docs/documents.md                               # "Transaction imports" (PDF part), headings kept
  - tests/test_table_engine_record.py               # _import tests (SC-08 step 2, SC-12 x14, SC-16, SC-19 step 2) and journey_j1
  - tests/test_pdf_imports.py                       # 7-d, 7-a', X_PERIOD; r3: the 7-b and second-heading analyzer tests renamed and updated to the contract
  - tests/pdf_import_fixtures.py                    # x_pages(period=...) for 7-a'
  - tests/test_statement_rebuild.py                 # bank()/analysis() on the engine; listed changes; legacy() helper
  - tests/test_table_engine.py                      # patch target of the x-reasons test; three SL-03 tests follow the shared piece names / FR-13
  - plans/pdf-table-engine/handoffs/slice-SL-06.md
checks:   # r3 run on 2067fc9
  - command: ".venv/bin/python -m pytest tests/test_table_engine_record.py -k \"_import or journey_j1\" -q"
    exit_code: 0     # 18 passed
  - command: ".venv/bin/python -m pytest tests/test_statement_rebuild.py tests/test_pdf_imports.py tests/test_imports.py tests/test_layout_consumers.py -q"
    exit_code: 0     # 241 passed
  - command: "RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_pdf_imports_browser.py -q"
    exit_code: 0     # 10 passed
  - command: ".venv/bin/ruff check src tests evals scripts"
    exit_code: 0
  - note: "r1 also ran, all exit 0 (engine edits unchanged in r3): the SL-05 command (227 passed), tests/test_table_engine.py + test_table_engine_generator.py (575), test_table_engine_browser + test_statement_accounts_browser (11), test_migrations + test_evals + test_pdf_layout (76)"
skipped_checks: [mypy, the full suite (the known unrelated Linux failures are outside the slice)]
escalations:
  - {id: 1, status: resolved, what: "the 7-b and second-heading analyzer tests are now listed in the contract; updated to the listed values in r3 (renamed ..._7b_a_repeated_transactions_heading_does_not_end_the_chain and ..._a_second_heading_below_a_native_table_is_ignored_and_its_rows_are_read)"}
  - {id: 2, status: resolved, what: "7-a' period now ends 09/20 in the contract; X_PERIOD already matched, its comment no longer calls this a contradiction"}
  - {id: 3, status: resolved, what: "plan P11 amended to keep today's piece ids and row numbers and counts['unplaced'] only when >= 1; the code already did this, no change"}
  - {id: 4, status: resolved, what: "engine repairs a-e and the unlisted value changes accepted and listed in the contract; no change"}
helper_subagents_used: none
```

## What was built
- **`pdf_import.analyze`** (`as_analysis`) runs `statement_tables.read(result, choices={year, date_format, sign}, statement_type=card for credit_card / bank for checking and savings / None, currency, prior_order)`
  and maps it to the old `Analysis`: one `ImportTable` per page of each engine transactions table (first page selectable, later pages `continuation` linked to it), one `ImportRow` per row the
  engine found (rejected rows keep `rejected` and their printed date/description/amount), other tables (summary, fee, daily, schedule) as `other`, `unplaced_line` issues (also for pending rows,
  P9 texts), `required` (`year`, `date_format`, `sign`), counts (`seen` = rows + unplaced), the document-currency block, flags, scanned pages and the `no_table` issue as before.
  `analyze_legacy` is the old body, unchanged. `ANALYZER_VERSION = 3`. `index_row` calls the new `analyze`, so the index backfill (and J1's checkpoint 2) runs the engine.
- **Choices apply only where the printed columns can't decide.** `year` = the printed period first, else the chosen year walked through the rows (the old rule: advances when the month falls);
  `date_format` = a day over 12, the period, `prior_order`, then the choice; `sign` replaces the default only (a chain or summary still decides). When no sign is known and nothing decides the
  signs, the adapter reads once as if `negative_is_outflow` was chosen to have the rows, and reports `required == ["sign"]` with `amount_minor = None` (the old behavior, SC-03 loan/other).
- **`statement_tables`**: `Reader.outcome_of` records per row (state ok/rejected/needs/roles, reason, posted date, signed minor amount, printed amount text, printed date, ids); `StatementReading.outcomes`,
  `.pieces`, `.others`. `Reader.name_pieces` names each page of a table once, and the rows' locators (`table_id`) and the import use the same names (below). `written()` walks a chosen year.
- **`ledger.pdf_state`**: `analyzed(**kwargs)` passes `prior_order = lambda: statement_tables.prior_order(db, last_four, document_id)` (last four = the chosen account's, else the one the PDF prints) and turns
  any non-`PDFImportError` exception into `ValueError("This PDF's rows couldn't be read from its printed columns. Read it again, or use Record.")` after `log_failure(log, "pdf import", exc, run=...)`
  (exception and run id only). The API's existing handler gives the 4xx; nothing is written (the exception is raised in the read-only state step).
- **Docs**: `docs/documents.md` "Transaction imports" (PDF part) describes the above. Headings kept.

## Tests
- `tests/test_table_engine_record.py`: `test_sc08_k3_pdf_import_previews_the_nine_rows_with_page_three_linked_to_page_one_import`, `test_sc12_the_preview_agrees_with_record_import[WF … TD]` (14 fixtures: account matching the stub,
  preview with no choices, required == [], printed-period year, Record, parsed ticked rows == recorded transactions, preview writes nothing, original blob unchanged, UP/PD unplaced issues equal Record's issue
  strings, none importable, identity), `test_sc16_nd_the_date_order_is_a_required_choice_in_the_preview_import`, `test_sc19_an_engine_fault_is_refused_with_a_4xx_and_nothing_written_import` (fixture S, the contract's double,
  counts of transactions/transaction_imports/accounts unchanged, no traceback, log has no fixture text) and `test_journey_j1_…` (restart x3 on the same folders; amended J1: one account, Z confirmed with 8 rows, Y ends with 19).
  SL-05's SC-13 Extract-again test (Z in its own account) is untouched. SL-05's SC-19 step 1 test now captures the document before installing the fault (otherwise the capture-time index also logs a failure and "one failure is logged" fails).
- `tests/test_pdf_imports.py`: 7-d analyzer + import tests updated to the contract (B2 is an unplaced line `Page 2: … "09/04/2026 B2 2.00 1,011.00"`, B1 imports, `counts.unplaced == 1`, import `rejected == 0`);
  7-a' added at analyzer and import level (fixture `x_pages("7a", period=X_PERIOD)`; page 3's rows are `other` tables with no rows, nothing unplaced, 4 rows, totals as step 1).
- `tests/test_statement_rebuild.py`: `bank()` = `statement_tables.read(...).as_rebuild()`; `analysis()` = the new `analyze`; `legacy()` = `analyze_legacy`. Listed changes applied (x2 unplaced issue + x3–x6 rows 2–5; balance title: s1–s5 recorded, no note;
  second heading: `LATE ROW` is a row, issue gone, opening 0.00/closing 1,000.00 printed; `ANALYZER_VERSION == 3`, test renamed `…_is_three_…`).
  **Tests that stay on the old reader**: `heading_titles` and every test importing `Reading`, `heading_row`, `cut_at`, `rebuilt_pages` (they call `statement_rows` directly, unchanged);
  `test_pcheck_x_the_rows_sit_as_the_contract_places_them` (uses `make_spec`/`touches`/`place`; its `analysis` call is `legacy`); `test_sc27_without_fr30_…` (patches `pdf_import.joined_amounts`; `legacy`);
  in `tests/test_table_engine.py`, `test_rows_x_the_reasons_are_the_old_readers_words` (`analyze_legacy`, patch target only).
- Expected values that moved beyond the contract's list (all follow from P9's 1-based numbering or from the shared piece names; please confirm): `test_rows_q_…` duplicate issue "page 2 (row 1)" → "(row 2)";
  `test_fr30_edge_a_joined_only_amount…` `built.issues` "Page 1 row 5" → "Page 1 row 6" (the same T-edge fixture and rule as the listed `test_sc17_a_rejected_row…`; its import-side `('rejected_row', 1, 5)` is unchanged);
  `test_rows_the_date_order_…` builds its page without X_ABOVE's printed September period (a printed period now beats the period passed in, FR-14, so March/April dates were a schedule);
  SL-03's `test_stmt_sc08_k3…` and `test_stmt_as_rebuild…` expect the shared piece names in `locator["table_id"]`; SL-03's CS-split test no longer expects the FR-13 issue (renamed, see escalation 4 e).

## Escalations
All four were settled by the user and the contract/plan amendment in 3b46c5a (status in the header). The original text follows for the record.
1. **Two existing tests fail by design and are left as they were** (FR-06, the engine ignores a repeated heading; the contract lists no change for them):
   - `test_analyzer_sc07_7b_a_new_transactions_table_ends_the_chain`: page 2 repeats the heading, page 3 has none. X-7b and K3 are the same shape (K3's page 2 is a native table too), and SC-08 step 2
     says K3's page 3 is linked to page 1's table, so the engine gives one table: pieces (1, transactions), (2, continuation → page 1's), (3, continuation → page 1's); labels `[[]]*2 + [["continued from page 1"]]*4`.
   - `test_analyzer_sc07_a_second_heading_below_a_native_table_is_reported_and_its_rows_are_not_read`: the repeated heading is ignored and its rows are read (C2, C3 appear), and the `second_heading` issue is gone: the
     same change the contract lists for `test_rows_a_second_transactions_heading_on_a_rebuilt_page_is_listed`.
   Proposed fix: add both to "Scenarios this spec changes" with those values (I did not edit the contract).
2. **7-a' as printed can't hold.** `Statement period 09/01/2026 to 09/30/2026` makes 10/01 one day after the period; FR-09 counts dates within 7 days as inside, so the first schedule row isn't outside and no schedule is found.
   The tests print `09/01/2026 to 09/20/2026` (`X_PERIOD`, commented). Every other 7-a' expectation is as the contract says. Alternative: change the schedule rows' dates (7-a would change).
3. **Piece ids and row numbers.** Plan P11 says pieces are named `page-<p>-table-<n>` and rows are 1-based. About eight unchanged tests pin the old names and numbers (`page-1-import-table-1`, `page-2-import-continuation`,
   native `page-1-layout-table-1`, native rows 1-based, others 0-based, e.g. `test_sc22_the_provenance_of_a_pdf_row…` `row == 1` for the second row of page 2). I kept them, so `ImportRow.row` and keys are as before; the
   engine's 1-based numbers stay in the *Record* issue texts (P9) and in `ImportRow` only for native tables. The same names are used for Record's locators (`table_id`). Plan P11's wording needs amending, or those tests do.
   Also: `counts["unplaced"]` is present only when there are unplaced lines (the existing equality assertions on `counts` would break otherwise); the dialog treats a missing key as 0.
4. **Engine repairs (for review; no contract value changed, all engine/statement/generator suites pass):**
   a. `continuation()`: a continuation page with no repeated heading may add a column where a heading label of the table's own first page sits (K's Deposits, which has no amount on page 1); the repeated-heading rule is unchanged.
      Plain K (used by ~25 unchanged account-import-pdf tests) cannot be read otherwise: its one deposit per page has no support.
   b. `continuation()`: stray amounts (no column) on at most half the page's rows no longer stop the page continuing the table; they stay unplaced lines (7-d).
   c. `bound_by_headings()`: between two amount columns that both have labels, the zone boundary is the midpoint between the labels when it lies in the gap between the columns' extents (the old heading spans). 7-d's B2 (centred on that midpoint, P-checked)
      then straddles and fits no zone.
   d. `scan()`: a dated line holding an amount that fits no zone is an unplaced line even when it has other amounts (7-d's B2 also prints a balance); before, the amount was swallowed into the description.
   e. `EngineTable.labels` (the heading's runs, for the import's column mapping of a heading over an empty column). And in `statement_tables.outcome()`: FR-13's reason is added only when the statement has fewer than 2 rows
      (SL-03 added it for every statement decided by headings or the type default, which the unchanged `bank()` helper tests (S, 6 rows, no summary) reject; FR-13 says "one row and no summary").
5. Smaller notes: (i) J1 publishes Z before Y: in one account the ledger leaves a row the account already holds out of the statement published after it, so published the other way round Z would hold no row
   ("Z unchanged with 8 rows" needs Z first; Y then holds none until Extract again); (ii) a rejected row in an unreadable-roles table shows the first cell problem (e.g. "not in USD") else
   "Which amount columns are money in, money out or the balance can't be told."; (iii) `ImportRow.amount` of a "More than one amount" row is rebuilt from the words in the money columns (`12345 1.00`), as before.

## Round r3
r2 hit a rate limit before doing anything. r3 changed only `tests/test_pdf_imports.py`: the 7-b analyzer test now expects one table across pages 1-3 (pieces (1, transactions), (2, continuation of page 1's),
(3, continuation of page 1's); rows of pages 2 and 3 labelled `continued from page 1`); the second-heading analyzer test expects C2 and C3 as rows 4 and 5 (after the rejected blank-description row 3) and no
`second_heading` issue; the X_PERIOD comment follows the amended contract. Nothing else in those tests changed. The code already matched the amended P11 (piece ids, row numbers, `unplaced` only when >= 1).

## Open issues
- None blocking. The index (`index_row`) now runs the engine for every reading; the time per reading was not measured on a large library.
- `scripts/statement_diagnose.py` still imports `PageView`, `assign`, `is_heading`, `native_spec` from `pdf_import` (unchanged); nothing else in `scripts/` or `evals/` calls `analyze`.
