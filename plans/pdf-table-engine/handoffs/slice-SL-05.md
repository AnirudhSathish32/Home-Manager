```yaml
slice: SL-05
result: escalated          # all built and verified except the items under `escalations`; one existing test fails on purpose (see 1)
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 3ec646c
end_head: HEAD            # the handoff commit on top of code commit ae36886 (git log -1 on this file)
commit: ae36886           # last code/test/docs commit; the handoff file is committed on top of it
code_commits: [d9ce7cc, 06456a6, 5d9b3a5, 0e3d396, 147c58b, ae36886]
changed_files:
  - src/home_manager/documents/extraction.py          # P10: statement_tables.engine_pages / read (+ prior_order closure), printed opening/closing in normalize, EXTRACTION_VERSION v32
  - src/home_manager/documents/table_engine.py        # one repair: a page heading of another column count starts its own table (continuation)
  - src/home_manager/finance/statement_tables.py      # one repair: a row cites its native-table cells and no words only when it is one table row (cited_words)
  - tests/test_table_engine_record.py                 # new: 31 passed + 1 xfail (Record side of the contract)
  - tests/test_table_engine_generator.py              # +10 end-to-end Record cases (test_sc18_end_to_end_through_record_case[...])
  - tests/test_table_engine_browser.py                # new: SC-03 step 4 (opt-in)
  - tests/test_statement_rebuild.py                   # P8 patch targets retargeted; test_sc17_rejected_rows_are_issues_... updated to the contract's x2 change
  - docs/documents.md                                 # "Statement rows from the printed columns" rewritten (heading kept)
  - plans/pdf-table-engine/handoffs/slice-SL-05.md
checks:
  - command: ".venv/bin/python -m pytest tests/test_table_engine_record.py tests/test_table_engine_generator.py tests/test_statement_rebuild.py tests/test_statement_accounts.py tests/test_statement_forms.py tests/test_extraction.py tests/test_provenance.py tests/test_reextraction.py -k \"not _import and not journey_j1 and not generator_only\" -q"
    exit_code: 1     # 196 passed, 1 xfailed, 1 failed in 218 s. The failure is test_sc17_a_rejected_row_turns_the_arithmetic_check_off_... (escalation 1); the xfail is escalation 2
  - command: ".venv/bin/python -m pytest tests/test_table_engine.py tests/test_table_engine_generator.py -k \"generator_only or not generator\" -q"
    exit_code: 0     # 575 passed (243 engine/statement tests + 332 generator_only tests), 68 s
  - command: ".venv/bin/ruff check src tests evals scripts"
    exit_code: 0
  - command: "RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_table_engine_browser.py tests/test_statement_accounts_browser.py -q"
    exit_code: 0     # 11 passed (Edge is installed here: /usr/bin/microsoft-edge); run before the docs/import-order commits, which touch no code path
  - command: ".venv/bin/python -m pytest tests/test_evals.py tests/test_layout_consumers.py tests/test_pdf_imports.py tests/test_pdf_layout.py -q"
    exit_code: 0     # 218 passed; extra evidence, not in the slice's list
escalations:
  - id: 1
    kind: unlisted existing expected value (row numbers)
    detail: >
      `tests/test_statement_rebuild.py::test_sc17_a_rejected_row_turns_the_arithmetic_check_off_rather_than_reporting_a_false_mismatch`
      (statement-accounts SC-17/FR-25, T-edge) asserts "Page 1 row 5: The amount is printed against the description…". The old reader numbered
      rows from 0 (s1…s5 are rows 0–4, so t1 is row 5). The engine numbers them from 1 (plan P9; contract SC-04 "Page 1 row 2/4/5", SC-06 "Page 1 row 14"),
      so t1 is row 6. The contract's "Scenarios this spec changes" lists T-edge as "unchanged" but only about the reason text. I did NOT edit the
      expected value (rule: escalate); the test fails with `row 6` for `row 5`, the reason text is identical. The same renumbering will touch
      `test_rows_x_records_only_x1_and_lists_x2_to_x6…` (SL-06 moves it to the engine, where x3–x6 are rows 2–5, as they were) — decide once for both.
      Needed from you: confirm 1-based numbering and approve changing that one expected value to `row 6` (a one-character change), or say how to keep both.
  - id: 2
    kind: contract contradiction (SC-11)
    detail: >
      SC-11 says "the missed-row check ran for page 2: `local_model` received a second `Transactions` request whose lines include the interest line". PR's
      page 2 is three prose lines that do not START with a date (`Interest of 0.42 was paid on 08/31/2026 …`). `extraction.missed_statement_lines` only flags
      lines that match `ROW_DATE` at their start, and FR-19 keeps the check "as today", so no second request is made. Everything else in SC-11 holds
      (4 rows incl. the stub's fee −250, the exact "Page 2: no table was found…" note once, no such note for page 1, reconciles). The literal bullet is
      `test_sc11_pr_page_two_is_asked_about_again_with_its_own_lines_only`, marked `xfail(strict=True)` with this reason, so it turns red the day the check is
      broadened. Needed: either amend SC-11 (check ran = `missed_statement_lines` found nothing), or say that the missed-row check should look for dates anywhere
      in a line (that would add requests to many existing fixtures; I did not do it).
  - id: 3
    kind: contract contradiction (SC-19 step 1)
    detail: >
      SC-19 step 1 says that with the engine faulted the statement's rows are the stub's 7 WF rows. WF's native table has `unresolved_columns` (SC-01's own
      P-check), and today's fallback anchors each model row to the native table's cells: with no resolved amount column it says "Amount has no unambiguous
      native source column" and leaves all 7 rows out ("A table row with an unresolved required amount was left out of the ledger"), so no row is
      recorded. DM (also a native table with unresolved headings) does the same. That is the old path's behavior on exactly the layouts this feature fixes, not
      something the fault changes. `test_sc19_an_engine_fault_…` asserts the rest of step 1 (REBUILD_FAILED exactly once, statement `needs_review`, no `rebuilt`
      evidence, the failure logged once by class with no description, amount or account number) and not the rows. The old S fixture (native table resolves)
      keeps its rows: `test_sc18_p8_*` still pass. Needed: amend SC-19's fixture (e.g. S, or WF without a native table) or accept the weaker assertion.
```

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
- The three escalations above. The T-edge failure keeps the first verification command's exit code at 1 until it is resolved (the one-line edit is yours to approve).
- Please confirm or amend the two engine repairs above (continuation heading rule, `cited_words`).
