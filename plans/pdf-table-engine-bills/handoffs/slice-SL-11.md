```yaml
slice: SL-11
result: ready_for_verification
provider: claude            # fresh worker for the code review round 1 fixes
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 4e31dc4
end_head: ca48df8   # the handoff file is committed after this (its commit is not in the list)
commit: [df976e5, 9ecb4bf, 0f4f923, 117b95c, d1e9a73, c758a0f, f9d2628, ca48df8]
checks:
  - command: ".venv/bin/python -m pytest tests/test_bill_engine.py tests/test_bill_engine_record.py tests/test_bill_corrections.py tests/test_bill_split.py tests/test_bill_engine_generator.py tests/test_evals.py -q -p no:cacheprovider"
    exit_code: 0   # 742 passed, 2 warnings, 553.81s
  - command: ".venv/bin/python -m pytest tests/test_receipt_segments.py tests/test_paystub_split.py tests/test_paystub_engine_record.py tests/test_bill_kinds.py tests/test_bills_ledger.py tests/test_extraction.py tests/test_planned_bugfixes.py tests/test_family_ledger.py tests/test_receipt_item_table.py tests/test_receipt_kinds.py tests/test_library.py -q -p no:cacheprovider"
    exit_code: 0   # 347 passed, 1 skipped (opt-in browser test), 365.17s: the other files that touch the transaction, the split, the ledger or the extraction
  - command: ".venv/bin/ruff check src/home_manager/finance src/home_manager/documents src/home_manager/library/storage.py tests/test_bill_engine.py tests/test_bill_engine_record.py tests/test_bill_corrections.py tests/test_bill_split.py"
    exit_code: 0
escalations: []
```

# SL-11: fixes for code review round 1 (all nine findings)

Synthetic data only: nothing under P:\Finances, %LOCALAPPDATA%\HomeManager or P:\EvalCorpus was read or run. No migration. Not changed: spec, test contract, plan,
approvals, progress.yaml, reviews.md. Every new test below was run against the tree with the fix removed (`git stash push src`) and failed there, and passes with it.

## Findings

1. **Atomic publication (major).** `library/storage.py`: `Store.transaction()` (a per-thread shared connection opened with `BEGIN IMMEDIATE`; a nested `connection()` on
   the same thread becomes a `SAVEPOINT`, so a caught inner failure still takes back only its own writes; commit when the block ends, rollback when it raises).
   `documents/extraction.py` `run`: every `record` (segment publication, automatic VOID/duplicate rejection), `save_segments`, `retire_segments` and the
   `status='succeeded'` update run inside `with self.store.transaction()`. The same transaction now covers receipts and pay stubs (the code path is shared). The
   `failed` update of the `except` branch runs after the rollback, so the run says "nothing was published" and that is true. Tests (`tests/test_bill_split.py`):
   `test_sl11_f1_a_failure_after_the_first_bill_was_published_leaves_nothing_behind_and_a_clean_retry_succeeds`,
   `test_sl11_f1_a_failure_while_the_file_is_read_again_leaves_the_earlier_bills_and_split_unchanged_and_a_retry_succeeds`,
   `test_sl11_f1_a_failure_while_the_file_is_split_again_keeps_the_obsolete_bill_counting_exactly_as_before`,
   `test_sl11_f1_store_transaction_commits_together_rolls_back_together_and_keeps_a_failed_inner_step_alone`. The fault is injected in the second `record` call (after the
   first bill's real publication); the assertion is whole-row equality of receipts, items, segments, evidence links, category splits, review events, corrections, merchants
   and shares before and after.
2. **Explicit `+` under a money-off section (major).** `finance/bill_tables.py` `signed`: the section rule applies to `marker is None` only; `plus` and `debit` stay charges.
   Tests: `test_bill_engine.py::test_sl11_f2_*` (token, `money_off`, adapted rows, and the role sum, for Account Credits / Discounts / Adjustments) and
   `test_bill_engine_record.py::test_sl11_f2_a_plus_five_under_a_money_off_section_is_stored_as_a_charge_of_five` (persisted 500, not a `credit`, sum 12850).
3. **Invoice fallback without an engine table (major).** `extraction.py`: `read` computes `suppressed` (the engine took the reader's printed tables away: `bill is BILL_FAILED`
   or a bill part exists, whatever tables it found) and passes it through `extract` to `read_form`, which raises `InvoiceBill` for an invoice summary whenever it is set (it
   used to require an engine table). The BILL_FAILED note is dropped when the invoice falls back. Tests (`test_bill_engine_record.py`):
   `test_sl11_f3_an_invoice_with_no_engine_charge_table_is_read_again_on_todays_native_path` and `..._read_after_the_engine_failed_...`: persisted 10000 / 20000 minor,
   source cells `100` / `200` from the reader's table (`pdf_text`), two summary questions, no BILL_FAILED note.
4. **Saved split scopes sections and signs (major).** `bill_tables.py`: new `Cuts` (the first line of each bill by position among the non-blank evidence lines) built by
   `cuts_of(evidence, anchors, lines_of, firsts=None)`; `read(evidence, firsts=None)` takes the evidence line ids that start the bills of the user's saved split, which
   replace the rule's page boundaries for `own_sections` (section ownership, also inside a page) and the per-bill sum rule; `extraction.py` `run` reads the saved user
   split first (new `ExtractionService.user_split`, which `bill_parts` now shares) and passes its first lines. The PDF is still read once. Tests: `test_bill_split.py::
   test_sl11_f4_a_saved_split_scopes_the_credit_section_so_the_next_bills_charges_stay_charges` (real `PUT /segments` then re-extraction through the app; persisted
   +1200 ... charges and holders, the first bill keeps its -250 credit) and `test_bill_engine.py::test_sl11_f4_a_users_cut_inside_a_page_...`.
5. **Summary on another page (major).** `bill_tables.py`: `targets_of(anchors)` takes the anchors of the bill (`Cuts.bill_of`), whatever page; `adds_up` sums only the table's
   rows of that bill. Tests: `test_bill_engine.py::test_sl11_f5_*` (roles `charge, other`, `decided_by == "sum"`, no guess; and the other side: a summary on the next bill's
   page does not decide) and `test_bill_engine_record.py::test_sl11_f5_a_two_page_headless_table_...` (stored 1000 / 2000, no column note).
6. **Fresh correction remembers a previous reading's amount (major).** `finance/ledger.py`: `line_state` carries `read` (position to the raw amount the latest reading of a
   bill with line corrections printed, set in `guard_line_corrections` before any correction is applied, only when the bill has line corrections); `remember_line_amount`
   uses it for a position with an applied price correction, and keeps the old path (the prior correction's remembered amount, else the price-chain start) when no reading has
   been guarded yet. The approved G4 case (a correction made before the reread caught up; `test_sc119_g4_*`) is untouched and passes. Tests (`test_bill_corrections.py`):
   `test_sl11_f6_a_code_set_after_the_reading_caught_up_...` (remembered 553, kept on an unchanged reread), `..._a_member_set_after_the_reading_caught_up_...`,
   `..._the_fresh_correction_is_held_for_a_shifted_line_that_happens_to_print_the_older_amount` (held with "that line now prints 5.35, not 5.53").
7. **Space-grouped accounts (major).** `documents/bill_split.py` `key_of`: an account is the last four digits of the whole contiguous printed value (groups of digits, hyphens and
   masking characters `x X * •`), stopping at the first other word; at least four digits. `XXXX XXXX 9012` now keys 9012 (it was no key before). Tests (`test_bill_split.py`):
   `test_sl11_f7_*`: the key per format, different accounts with all dates and amounts alike split, the same account in four formats continues.
8. **Held unit price shows the rounded cents (minor).** `ledger.py`: module function `unit_price_correction_applies(db, receipt_id, position)` (latest change not held, not
   undone while held, not an undo back to the print); `record` shows the printed rate when it is False. Tests: `test_bill_corrections.py::test_sl11_f8_f9_*` (applied, held,
   undone while held, recovery; the server's display string).
9. **Product check ignores an applied unit-price correction (minor).** `finance/document_traces.py` `bill_checks` uses the same function, so the rate is: an applied
   correction, else the exact printed rate, else the stored cents. The same four tests assert the check's arguments and result (`(1500, 1430)` for the applied 0.15; `(1435,
   1435, True)` for the held one).

## Version, docs, test edits
- `EXTRACTION_VERSION` is `typed-extraction-v48-bill-review-fixes` (2, 4, 5 and 7 change the stored reading for files already read). The pin in
  `test_bill_engine_record.py` and `docs/documents.md` ("Bill lines ...") follow. No other test pins the string.
- Docs (headings unchanged): `docs/documents.md` ("Bill lines from the printed columns": the sum rule's page scope and saved split, `+`/`DR`, the account key, the "Known limits" line
  about the saved split removed; "Several bills in one file": the account key, a failed run, the rate); `docs/money.md` ("Bills and their lines" the rate;
  "Reading a statement or receipt again": the amount a later correction remembers, the shown rate while held); `docs/open-work.md`: the "A split you saved can differ from
  the rule's" limitation removed.
- Existing tests edited because an interface or a pinned plan restriction changed (no expected contract value changed):
  - `test_bill_engine.py::test_sc105_only_summary_amounts_on_the_tables_own_pages_are_sum_targets` pinned the plan's "targets are on the table's pages" (plan.md P2, line 202),
    which finding 5 shows contradicts FR-103/FR-105 b. It is now `test_sc105_summary_amounts_on_another_page_of_the_same_bill_are_sum_targets` and asserts the opposite
    (same bill: sum). The plan text is not edited; the orchestrator may want to note it.
  - The four engine fault doubles (`fault`/`broken`/the lambda in `test_bill_corrections.py`, `test_bill_engine_record.py`, `test_bill_split.py`) now accept `firsts=None`,
    since `bill_tables.read` has that optional second argument.
- `Store.connection()` is the one core change: when the thread is inside `Store.transaction()` it hands out the shared connection (savepoint per use). Outside it is
  unchanged, so nothing else sees a difference.

## Commands
See the header. Not run: the full suite (the orchestrator's final run) and the browser tests (`RUN_BROWSER_TESTS=1`, `test_bill_engine_browser.py` asserts the applied-correction
display only, which is unchanged). Not independently re-measured: real-bill accuracy (no corpus access, as ever).

## Not fixed / residual
- Nothing left unfixed. Two notes for the reviewer:
  1. Finding 1's transaction holds the write lock from the first `record` to the run's success update (no model call happens in that span, only code). Another writer waits
     up to the 15 s connection timeout.
  2. When a saved user split is used but the parts then fall back to one document (a part is not a bill, or an invoice, D16), the engine's per-bill decisions were made on
     the user's bills while the file is read as one. The automatic split has the same property already.
