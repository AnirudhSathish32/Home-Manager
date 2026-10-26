```yaml
slice: SL-05
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 0793b8c   # plus a previous worker's uncommitted draft, reviewed and kept in part (see below)
end_head: this commit (a commit cannot name itself; see `git log --grep "statement-accounts SL-05:"`)
commit: HEAD of "statement-accounts SL-05:"
checks:
  - command: ".venv/bin/python -m pytest tests/test_statement_accounts.py -k \"journey_j1 or sc04 or sc07\" -q"
    exit_code: 0   # 19 passed (the new file, whole: 6 journey_j1 tests, 11 sc04, 2 sc07)
  - command: ".venv/bin/python -m pytest tests/test_statement_forms.py tests/test_reconcile_tools.py tests/test_layout_consumers.py tests/test_extraction.py tests/test_reextraction.py tests/test_traces.py tests/test_provenance.py tests/test_record_history.py -q"
    exit_code: 1   # 107 passed, 3 failed: the 3 known tests/test_traces.py failures (node v18.19.1 rejects --allow-fs-read), nothing else; see below
  - command: ".venv/bin/python -m pytest tests/test_statement_rebuild.py tests/test_statement_forms.py tests/test_pdf_imports.py tests/test_extraction.py tests/test_layout_consumers.py tests/test_provenance.py tests/test_migrations.py tests/test_imports.py tests/test_family_routing.py tests/test_finance.py -q"
    exit_code: 0   # M2 (M1 set + the non-filtered files of the M2 line, whole): 362 passed. Its filtered part is the first command (19 passed).
  - command: ".venv/bin/python -m ruff check src tests"
    exit_code: 0
  - command: ".venv/bin/python -m pytest -q --deselect tests/test_traces.py   # whole suite, before the test_receipt_kinds fix"
    exit_code: 1   # 1401 passed, 53 failed, 20 errors; 51 failed and the 20 errors fail the same on 0793b8c, the other 2 were mine (fixed, below)
  - command: ".venv/bin/python -m pytest tests/test_receipt_kinds.py -q"
    exit_code: 0   # 43 passed, after the fix below
escalations:
  - "Kept existing assertions that changed; each is a direct consequence of the spec (list under 'Changed existing assertions')."
```

# SL-05: Recording into an account that isn't confirmed yet

## Where the previous worker's draft stood
I read the uncommitted diff first. The `ledger.py` and `extraction.py` changes matched the plan and I kept them
after checking each line against the plan (P16 order, FR-04 downgrade not touching `origin='family'`, FR-06 removal
through `remove_if_empty`/`_remove_account`, `review` P15, `correct`, `account_note`, `ExtractionService.publish` passing
`origin="record"` and taking `review_status` from the ledger's result). Nothing needed replacing. What the draft lacked:
every new test, the C-orphans helper, the docs, and the `tests/test_receipt_kinds.py` setup that the new rule broke (found
by the whole-suite run). I mutation-checked the new journey: removing the removal, the FR-04 downgrade, the P16 early
return or the P15 cascade each fails `journey_j1`.

## Changed files
- `src/home_manager/finance/ledger.py`
  - `publish_statement`: P16 (a statement you decided is returned as `kept_reviewed` before any account lookup or creation);
    FR-04 (`verified` becomes `proposed` when the account is unconfirmed and `origin != 'family'`); FR-06
    (`remove_if_empty(db, old_account)` after the rows moved, same transaction); the result gains `review_status` and
    `account_confirmed` (also on `kept_reviewed`).
  - `remove_if_empty` and `_remove_account` (static): the shared removal for an account with no statement, transaction or
    import. It deletes its `category_rules` and `tax_rules`, sets `recurring_obligations.account_id` and
    `investment_accounts.ledger_account_id` NULL, then deletes the account. **SL-06 extends `_remove_account` for the full
    delete** (plan "Delete").
  - `review` (P15): when a statement is set to `needs_review`, its `origin='extraction'` rows that are `verified`/`rejected`
    with `review_source='user'` and no `review_events` row of their own go back to `needs_review`, source NULL.
  - `correct`: the automatic promotion after a correction is `proposed` (source NULL) while the account is unconfirmed.
  - `record("statement", id)`: `account_note` = `New account: {display_name} — added to Accounts when you confirm this statement.`
    when the account is unconfirmed (absent otherwise).
- `src/home_manager/documents/extraction.py`: `publish` passes `origin="record"` for statements (a `functools.partial`) and returns
  `published.get("review_status", status)`.
- `tests/test_statement_accounts.py`: `journey_j1` (6 tests; see below).
- `tests/statement_account_fixtures.py`: `orphans(db, account_id, statements, transactions)`, the C-orphans check (SL-06 reuses it).
- `tests/test_statement_forms.py`, `tests/test_extraction.py`, `tests/test_statement_rebuild.py`, `tests/test_receipt_kinds.py`: existing tests, below.
- `docs/money.md` "New statements wait for you": three paragraphs (accounts that wait, what confirms one, a re-read that moves a statement).
- `docs/open-work.md`: the Statement accounts bullet now lists only Delete account and the screens. It also drops "Record takes
  a statement's dates and amounts from its rebuilt columns" and the "until built" sentence: the rebuilt rows were built in
  SL-01–SL-03 and documented in `docs/documents.md`, but that bullet still listed them (stale since M1).

## Tests (`tests/test_statement_accounts.py`)
All names carry `journey_j1`, so the gate's `-k` picks them up.
- `test_journey_j1_a_statements_account_waits_for_confirm_and_a_re_read_moves_it`: steps 1–4 through the real API and `ExtractionService`
  (S pages read by the real reader; `local_model` stubs with S-bad rows). Step 1: one `record` account `SYNTH BANK savings 3456`,
  C-hidden on six surfaces, statement `proposed` with no issues, API record shows `account_confirmed False` and the exact note,
  rows 36, 2, −38, 150000, −50000, September money in and spending 0. Step 2: Confirm, C-visible, `verified`/`user`, note gone.
  Step 3: Undo, C-hidden, rows back to `needs_review`/NULL (P15). Step 4: with the `BEFORE DELETE ON accounts` fault trigger the
  re-read fails and `accounts`, `statements`, `transactions`, `financial_evidence_links`, `review_events`, `category_rules` and
  `transaction_imports` equal their step-3 snapshot; after dropping the trigger one account `…7890` (waiting) remains, `…3456`
  has no row in any table (C-orphans), the same statement id holds the five rebuilt amounts, and `env.files()` (C-docs) is unchanged.
- `…_a_re_read_of_a_statement_you_confirmed_keeps_it_as_you_reviewed_it` (SC-06, J1-a, E2): `kept_reviewed`, one account `…3456`
  confirmed, no `…7890`, full snapshot equal, files unchanged.
- `…_b_a_second_statement_of_a_confirmed_account_keeps_the_automatic_check` (J1-b): `verified`/`automatic`, no issues, same account.
- Extra beyond the contract: a correction doesn't skip the wait (and does promote to `verified` for a confirmed account); Undo keeps a
  row you rejected one by one (P15); a family delivery's statement is not held, and a later Record statement into that confirmed
  account keeps `verified`.

**Deviation to look at (S2's stub).** The contract says step 4 re-reads "the same document version with the S2 summary stub". `sf.s2_summary`
cites S2's own `Account Number 000009000127890` line, which S's document doesn't have, so it can't be used on S's lines. `moved()`
in the test is S's summary with `account_reference` `7890` cited from S's printed number line (whole line as the quote; `last_four`
then takes the model's four digits). Nothing in the spec or contract values changes.

## Changed existing assertions (kept; each from the previous worker's draft, re-checked by me)
All of them follow FR-04 ("the first statement into an account that waits is `proposed`, whatever the checks found") and
FR-01/FR-02 (a Record-made account is hidden until confirmed), P1/P2/P5. None weakens what it checks.
1. `tests/test_extraction.py::test_long_statement_is_chunked_…`: `review_status == "verified"` becomes `"proposed"` (FR-04, P2: Record makes
   the account). `"000123454821" not in json.dumps(manager.ledger.accounts())` read `accounts()`, which now hides this new account
   (FR-02, P5), so it would pass vacuously; it now reads every row of `accounts` (stronger).
2. `tests/test_statement_forms.py`: `record["review_status"] == "verified"` becomes `"proposed"` in `test_sc22_bank_statement_fields_and_summary_check`,
   `test_skipped_statement_rows_are_asked_for_again_…`, `test_the_printed_words_as_the_account_type_…`, `test_sc22_b_no_type_word_is_other`,
   `test_sc22_c_without_a_withdrawals_total_…`, `test_sc23_card_statement_fields_and_summary_check`, `test_sc23_b_without_a_fees_line_…`
   (FR-04: each is the first statement into a new account and its checks pass). `read_september` (the SC-24 library) asserts `proposed`
   and then confirms the statement with `ledger.review(…, "verified")` before `reconcile_statement`: with FR-04 the rows count only
   after the user's Confirm, and `september()` finds the checking account through `accounts()`, which lists it only once confirmed
   (FR-03, FR-04).
3. `tests/test_statement_rebuild.py`: `test_sc15_the_year_comes_from_the_printed_period` and
   `test_sc16_the_model_cannot_change_rebuilt_rows_…`: `"verified"` becomes `"proposed"` (FR-04). Their other assertions are unchanged.
4. **Found by me** in the whole-suite run (not in the plan's SL-05 list): `tests/test_receipt_kinds.py::gift_card_library` records a card
   statement into a new account and then reconciles it; the lines no longer counted. It now confirms the statement
   (`ledger.review(…, "verified")`) before `reconcile_statement`, with a comment citing FR-04. No assertion in
   `test_sc27_a`/`test_sc27_b` changed (43 pass).

No other existing test changed. `test_layout_consumers`, `test_reextraction`, `test_provenance`, `test_record_history`,
`test_reconcile_tools`, `test_pdf_imports`, `test_imports`, `test_finance`, `test_family_routing` and `test_migrations` pass unchanged.

## Gates
- `tests/test_traces.py` (in SL-05's gate): the same 3 fail as before this slice, `test_the_return_and_tax_zen_trace_to_the_engines_lines_and_the_records`,
  `test_the_engines_own_steps_trace_down_to_the_return_inputs_and_the_law` and `test_family_figures_trace_to_each_members_own`. Cause:
  `Engine 1 gave no answer (exit 9: /usr/bin/node: bad option: --allow-fs-read=…)`, node v18.19.1. I ran `tests/test_traces.py` on a clean
  checkout of 0793b8c (a temporary `git worktree`, removed): the same 3 fail, 7 pass. Nothing else in the gate fails.
- Whole suite (not required by the plan; run to catch Record tests the plan's list missed): outside `tests/test_traces.py`, 64 tests fail or error
  (tax engines and worksheets, `test_agent_*`, `test_scenarios`, `test_cpa_pack`, `test_tax_*`, and 13 `test_agent_instance` teardown errors on
  `socket.SO_EXCLUSIVEADDRUSE`, which is Windows-only). I ran those exact 64 ids on 0793b8c: they fail or error the same way (51 failed, 13 passed with a teardown
  error, 20 errors, equal to this checkout). Only the 2 `test_receipt_kinds` tests were mine, now fixed.
- `progress.yaml` was not touched or staged.

## Open issues for SL-06 and SL-07
- **SL-06:** `_remove_account` is the *empty-account* version (no statements, transactions or imports). Extend it per the plan's "Delete" order
  (receipt/transfer/income links, splits, tags, typed rows, `replaced_by`, open reconciliation issues, then the rows, then the account) and keep
  FR-06's caller working. `sf.orphans(db, account_id, statements, transactions)` is ready for C-orphans (it reads columns with `PRAGMA table_info`
  over `sqlite_schema`, not `pragma_foreign_key_list`; the contract names the column list, which it uses).
- **SL-06:** `publication.removed` in `ExtractionService.get` is not done. After FR-06 removes an account, a run's `publication_json` still names the
  old `account_id`; that is migration 073's trace and is fine.
- **SL-07:** `Ledger.record("statement", id)` returns `account_confirmed` and, when false, `account_note`. `waiting_accounts()` rows carry
  `statement_id` and `statement_document_id` (SL-04). `publish_statement`'s result carries `review_status` and `account_confirmed`; the run's
  `publication.review_status` is the ledger's (so the document page shows `proposed` for the first statement).
- **SL-07:** Confirm on an old `verified`/`automatic` statement of an unconfirmed account (P4, `awaitingAccount`) needs `account_confirmed` from the record.
  Undo of a Confirm returns the rows to `needs_review` (not to their earlier `proposed`); the UI shows the statement as `needs_review` again.
- A re-read of a statement you haven't decided that lands in a *confirmed* account keeps `verified`/`automatic` only if the checks pass (FR-04 second half; J1-b).
- `docs/ui.md` is not touched (SL-07).
