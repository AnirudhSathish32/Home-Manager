```yaml
slice: SL-05
result: ready_for_verification   # r3: the three settled escalations are applied; all four verification commands exit 0
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 1175b62        # r3 (r2 started at 3ec646c)
end_head: HEAD             # the handoff commit on top of code commit 9f4278e (git log -1 on this file)
commit: 9f4278e            # r3 code/test/docs commit; r2's code commits: d9ce7cc, 06456a6, 5d9b3a5, 0e3d396, 147c58b, ae36886
code_commits: [d9ce7cc, 06456a6, 5d9b3a5, 0e3d396, 147c58b, ae36886, 9f4278e]
changed_files:   # r3 only; r2's list is in "What was built" below and git log
  - src/home_manager/documents/extraction.py          # ANY_DATE; missed_statement_lines flags a date anywhere (FR-19 / plan P10 bullet)
  - tests/test_table_engine_record.py                 # SC-11 xfail removed; SC-19 step 1 rewritten on fixture S (imports s_replies from test_statement_rebuild)
  - tests/test_statement_rebuild.py                   # T-edge "Page 1 row 5" -> "Page 1 row 6" (one value, nothing else)
  - docs/documents.md                                 # "Statement rows the model skipped": the date may be anywhere in the line (heading kept)
  - plans/pdf-table-engine/handoffs/slice-SL-05.md
checks:
  - command: ".venv/bin/python -m pytest tests/test_table_engine_record.py tests/test_table_engine_generator.py tests/test_statement_rebuild.py tests/test_statement_accounts.py tests/test_statement_forms.py tests/test_extraction.py tests/test_provenance.py tests/test_reextraction.py -k \"not _import and not journey_j1 and not generator_only\" -q"
    exit_code: 0     # 198 passed, 0 failed, 0 xfailed, 200 s (SC-11 and the T-edge test pass; no other test changed)
  - command: ".venv/bin/python -m pytest tests/test_table_engine.py tests/test_table_engine_generator.py -k \"generator_only or not generator\" -q"
    exit_code: 0     # 575 passed, 61 s
  - command: ".venv/bin/ruff check src tests evals scripts"
    exit_code: 0
  - command: "RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_table_engine_browser.py tests/test_statement_accounts_browser.py -q"
    exit_code: 0     # 11 passed
  - command: ".venv/bin/python -m pytest tests/test_evals.py tests/test_layout_consumers.py tests/test_pdf_imports.py tests/test_pdf_layout.py -q"
    exit_code: 0     # 218 passed; extra evidence, not in the slice's list (the broader check moved none of them)
escalations:
  - id: 1
    status: resolved   # 1-based numbering confirmed; test_sc17_a_rejected_row_turns_the_arithmetic_check_off... now expects "Page 1 row 6" (9f4278e)
  - id: 2
    status: resolved   # FR-19 amended: missed_statement_lines flags a date anywhere in an uncited line with an amount besides it; SC-11's xfail removed, the test passes as written (9f4278e)
  - id: 3
    status: resolved   # SC-19 step 1 on fixture S: the stub's 6 rows [36, 2, -38, 150000, -50000, 2], needs_review, REBUILD_FAILED once, no `rebuilt` evidence, one failure logged with no description/amount/account number (9f4278e)
```

## Round r3 (the three settled escalations)
- **Missed-row check.** `ANY_DATE` is `ROW_DATE`'s date forms behind `(?<![\d/])`. `missed_statement_lines` flags an uncited, non-`BALANCE_LINE` line when removing some date match
  leaves text holding an amount (`line_amounts` over the text before and after the date, joined by a space). The old rule (a date at the start, an amount after it) is a special case.
  No other test in the four verification commands or in the extra PDF-import/evals/layout run changed.
- **SC-19** uses the contract's engine-fault double (`statement_tables.engine_pages` and `read` raise `RuntimeError("injected engine fault")`) on `sf.s_pages()` with `s_replies()` imported from
  `test_statement_rebuild` (that file's behavior is unchanged). `_import` (step 2) stays for SL-06.
- The r2 text below is kept as it was; where it describes the three escalations as open, this section supersedes it.

## What was built
- **`documents/extraction.py` (P10).** `read` calls `statement_tables.engine_pages(evidence)` (same exception fallback: `REBUILD_FAILED` and no rebuild on any page). `publish`
  calls `statement_tables.read(evidence, statement_type, currency, fallback_period=(model start, end) when both, prior_order=closure over self.store)`.
  The closure runs `statement_tables.prior_order(db, last four of the summary's account_reference, this document's id)`, only when a last four is cited.
  FR-19's note travels `StatementReading.notes` → `Rebuild.notes` → record notes (never into `read`'s `notes` list). `normalize`: before the arithmetic check, printed opening/closing
  (`rebuild.opening_minor/closing_minor`) replace `opening_balance_minor/closing_balance_minor` (bank) or `previous_balance_minor/statement_balance_minor` (card) and the
  matching `record["summary"]` entries, with P9's note ("The printed opening balance 1,000.00 USD was recorded; the reading gave 1,100.00 USD.") when the reading gave another
  value. `EXTRACTION_VERSION = "typed-extraction-v32-table-engine"`. A reading without layout is unchanged (`NO_LAYOUT_NOTE`).
- **Deviations from the plan's wording** (none changes a contract value): (a) `summary_json` is keyed by field name without `_minor` (`opening_balance`, `closing_balance`,
  `previous_balance`, `statement_balance`; `document_traces.py` reads those), so I wrote those keys, not "the same keys"; (b) no note when the reading gave NO value (there is
  nothing that differed); (c) "the printed anchor's line is added to the record's notes text" is not done: `Rebuild` carries only the value, not the anchor's line (the
  note names the values; the evidence of the field still cites the model's line, as the plan says).
- **Two repairs in SL-01..03 code, forced by existing tests that the contract keeps unchanged** (both are small; please say if you'd rather they be a different shape):
  1. `table_engine.continuation`: a page whose own heading has a different number of runs than the open table's heading no longer continues that table. statement-accounts D2
     (a `DAILY ENDING BALANCE` table of `Date | Amount` alone on page 2, under the same date and amount columns as page 1's table) was read as page 1's continuation, so its
     rows came out as "The description is blank." rejections. It is now its own (balance) table, as before the engine. K3's repeated heading has the same run count, so it still continues.
  2. `statement_tables.Reader.cited_words`: statement-accounts SC-19 pins that a row which is one row of a native table cites that table's cells and **no words**
     (`word_ids == []`, `document.cells == cell_ids`), while SC-03 here wants a wrapped row to cite every word. A row now cites no words only when all of its cells are in one
     native table row and hold every word of the row; WR's wrapped rows (cells in 2–3 table rows) and every row with no native table cite every word. S's single-row rows are unchanged.
- **Tests.** `tests/test_table_engine_record.py`: the contract's Record scenarios through the real `ExtractionService` and the `local_model` stub by schema, C-net autouse, summary stubs from
  the contract (one spec table, each value cites its printed line): SC-01 (WF; WF-summary-off; WF-flag), SC-02, SC-03 (WR with provenance of r6 and r5, and WR-split), SC-04, SC-05, SC-06 a and b, SC-07
  (CS, NB, NB without summary), SC-08 step 3 (K3), SC-09 (BL), SC-10 (UP), SC-11 (PR, 2 tests), SC-13 (Extract again), SC-14 (WF and WR), SC-16 a, b, c and a real-library `prior_order`
  test, SC-17, SC-19 step 1, SC-23, SC-24, SC-25 (TD and TD-bare), and the `EXTRACTION_VERSION` check. None needs PDF import, so none is named `_import` / `journey_j1`; those scenarios
  (SC-08 step 2, SC-12, SC-16's preview, SC-19 step 2, J1) are left for SL-06 and absent. `tests/test_table_engine_generator.py`: 10 cases chosen by `random.Random(SEED).sample(range(200), 10)`
  run end to end through Record (names `test_sc18_end_to_end_through_record_case[idx]`; the model's summary is built from the lines the generator printed; expected rows only from the generator's inputs).
  `tests/test_table_engine_browser.py`: SC-03 step 4 (r6's source lights exactly its 11 words on page 1, three lines).
  `tests/test_statement_rebuild.py`: `test_sc18_p8_*` retargeted (patch target only); `test_sc17_rejected_rows_are_issues_with_their_page_row_and_reason` updated to the contract's x2 change
  (x2 → one unplaced-line issue quoting `09/03/2026 STRADDLE 100.00`; x3–x6 rejected as before, rows 2–5).
- **`docs/documents.md` "Statement rows from the printed columns"** rewritten to what is built (columns by alignment, `ALIGN = 0.75` as SL-04 confirmed, roles, values, balances, issues, evidence); heading unchanged.

## Contract/stub deviations in the new tests (none changes an expected value)
- A summary value the fixture does not print is `missing`, because a cited amount must be printed in its line: K3's opening/closing (K prints none), CC's, ND's and ONE's.
- K3's footers print no `$`, so Record could not read the amounts as USD (no explicit currency, no symbol): the K3 Record test adds `, amounts shown in $,` to the three footers, as the contract's
  conventions require of every native page. The generator cases get the same footer text.
- WF-summary-off: "opening 1,100.00 / closing 2,213.45" must be printed somewhere to be cited, so the variant prints two extra lines below the footer (`Average collected 1,100.00`, `Available now 2,213.45`).
- SC-04 "exactly three record notes": every fixture's `$` footer also gives the currency note ("No currency code is printed; the $ amounts were read as your home currency (USD)."); the test counts the
  three `Page 1 row N: no date is printed…` notes.
- SC-13 (Extract again): Z is published in its own account (`…4418`). In one account the ledger drops a row already held by another statement (same date, amount and text) as a duplicate, so Z's 8 old
  rows would insert none, and Y's re-read would hold 19 rows (its row 7, `2026-10-10 INTEREST CREDIT`, equals the old path's). **This will break SL-06's `journey_j1` as the contract writes it (Y and Z in one account, "Z unchanged with 8 rows; Y with 20")**; flag it there.
  Row ids also keep the old row 7 first, so Y's 20 rows are compared in date order.
- SC-24 / SC-10: the arithmetic check is skipped when a pending or unplaced line was not recorded (P9), so C-reconciles is "no arithmetic issue" there, not "the check ran and held".
- SC-01 `opening/closing shown`: asserted on `GET /api/finance/records/statement/{id}` (`opening_balance_minor` 100000, `closing_balance_minor` 211345).

## Not done / left for later slices
- PDF import (`pdf_import.analyze`, `ledger.py`, `ANALYZER_VERSION`), `statement_rows` as the old reader, the `bank()`/`analysis()` helpers in `test_statement_rebuild.py`: untouched (SL-06).
- `docs/documents.md` "Transaction imports" (SL-06) and the evals docs (SL-07).

## Open issues
- None from r3. Still open from r2: please confirm or amend the two engine repairs (continuation heading rule, `cited_words`); SC-13's note about `journey_j1` (Y and Z in one account) is for SL-06.
