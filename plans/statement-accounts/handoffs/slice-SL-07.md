```yaml
slice: SL-07
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 4eb5a2e
end_head: this commit (a commit cannot name itself; see `git log --grep "statement-accounts SL-07:"`)
commit: HEAD of "statement-accounts SL-07:"
checks:
  - command: "RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_statement_accounts_browser.py tests/test_document_v2_browser.py tests/test_transactions_v2_browser.py -q"
    exit_code: 1   # 1 failed (test_transactions_v2_filters_categorises_adds_and_imports), 18 passed. That test fails identically on START_HEAD (git stash check): its 390px `.tx2-name` bounding box is None. Not caused by this slice.
  - command: "RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_statement_accounts_browser.py tests/test_document_v2_browser.py -q"
    exit_code: 0   # the contract's browser regression line: 17 passed (10 new + 7); re-run after the last edit inside the combined run below
  - command: "RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_accounts_v2_browser.py tests/test_pdf_imports_browser.py tests/test_trace_components_browser.py tests/test_review_v2_browser.py tests/test_record_components_browser.py tests/test_records_v2_browser.py tests/test_family_browser.py tests/test_today_v2_browser.py -q"
    exit_code: 1   # 22 passed, 2 failed (test_review_v2 test_to_check_decides_each_kind_with_its_source_in_view, test_records_v2 test_records_v2_filters_strip_read_all_and_trash). Both fail identically on START_HEAD (stash check); the review one now starts on a statement item (SL-05's proposed statement), the records one is a Playwright "element not stable" scroll. The three gate files you named (accounts_v2, pdf_imports, trace_components) all pass.
  - command: "RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest <SL-07 files + test_accounts_v2, test_pdf_imports, test_trace_components, test_review_v2, test_record_components browser files> -q   # final, after the last edit"
    exit_code: 1   # 37 passed, 2 failed: the two pre-existing failures (transactions_v2, review_v2) only
  - command: ".venv/bin/python -m pytest tests/test_statement_accounts.py tests/test_statement_rebuild.py tests/test_statement_forms.py tests/test_pdf_imports.py tests/test_imports.py tests/test_extraction.py tests/test_layout_consumers.py tests/test_family_routing.py tests/test_reconcile_tools.py tests/test_finance.py tests/test_provenance.py -q"
    exit_code: 0   # 371 passed (the contract's non-browser regression line)
  - command: ".venv/bin/python -m ruff check src tests"
    exit_code: 0
escalations: []
```

# SL-07: Screens

No gate needed a change to the spec, test contract or an approved plan decision. **Changed existing assertions: none.**

## Changed files
- `src/home_manager/app/static/accounts_v2.js`
  - Each row (not in the family view) gets **Delete…** beside Rename (`.accounts2-row-actions`, `aria-label` "Delete {name}…").
  - New collapsed `<details id="accounts2-waiting">` "Waiting for confirm (n)" at the bottom, from `GET /api/finance/accounts/waiting` (not in the family view; its open state survives a reload). Each entry has **Open statement** (its `statement_document_id`) and **Delete…**.
  - `openAccountDelete(accountId, {opener, onDeleted})`: the shared dialog (preview, counts, stays/family lines, 409 reloads the preview, 404 disables, focus on Cancel, focus back to the opener on Cancel/Esc, to the page heading after a delete or when the opener was redrawn). A stale preview that arrives after a close and reopen is dropped (found by the keyboard test: it re-enabled Delete before the new preview had loaded, and the click then threw on a null token).
  - `afterAccountDelete()`: re-shows the current route (Accounts, Today, To check), or for the document page resets `renderedKey` and re-reads the extraction and the document header; refreshes the nav counts.
- `src/home_manager/app/static/index.html`: `#account-delete-dialog` (class `money2-dialog`).
- `src/home_manager/app/static/trace.js`
  - `confirmCorrect(awaitingAccount)` (P4): a `verified`/`automatic` record whose account waits shows Confirm and Reject as a `proposed` one does. Undo is the default `needs_review`.
  - `accountNoteBlock(record)`: the `account_note` text with a **Delete account** link-button (shared by the document page and Review).
  - `sourceLink` unchanged (decision b below).
- `src/home_manager/app/static/document_v2.js`
  - The account note and Delete account (statements); `awaitingAccount` from `account_confirmed === false`, passed to `confirmCorrect` and to the Recorded step (attention).
  - A statement's `details.notes` are shown under its fields as a bill's are (pass 2 M2). `doc2DetailList` needed no change (it already returns null when no key has a label).
  - `publication.removed`: the record panel says nothing is recorded, the Recorded step is "todo", and the next step is **Record it** (`doc2Record(true)`) with a sentence saying the account was deleted.
  - `doc2RowSources` (decision a below).
- `src/home_manager/app/static/review_v2.js`: a statement item shows the note and Delete account under the evidence (`note()` hook, fetched once with the record `cc` already needs) and passes `awaitingAccount`.
- `src/home_manager/app/static/style.css`: scoped rules only (`.accounts2-row-actions`, `.accounts2-waiting*`, `.account-delete-counts`, `.doc2-account-note`), tokens only.
- `tests/test_statement_accounts_browser.py` (new, 10 tests): SC-24, SC-25 (Accounts by keyboard; the document page by keyboard then Record it again; a 409), a confirmed account's Delete…, P4, SC-26 (S and S-flag), the dialog's other lines and the family line at 390px (the preview answered with other counts through `page.route`; the numbers are the server's), and Review.
- `docs/ui.md` (Accounts page entry: Delete…, Waiting for confirm, the dialog; the document page: the note, notes, Find on rebuilt rows, `publication.removed`; `confirmCorrect` row: `awaitingAccount`), `docs/money.md` (two sentences: where the delete is offered, and Waiting for confirm / P4), `docs/open-work.md` (the Statement accounts bullet: built, only the accepted FR-27 gap stays).

## Decisions
**(a) SC-26.** A rebuilt row's own cells and words weren't in the record API (rows carry `line_ids` and `cell_evidence` only). Rather than change the backend (outside SL-07's row), `doc2RowSources` replaces each statement row's Find button: on click it fetches `GET /api/provenance/transaction/{id}`, takes the string `document.cells` when `kind === "extracted"`, and calls `viewer.highlight([...line_ids, ...cells])`. A row whose amount cell the reading cited by its own id (`cell_evidence` with `pdf_text`) keeps its old Find. The test shows the highlight call is exactly `[line, ...table cell ids]` for S's s2 and `[line, ...word ids]` for S-flag's s2, and page 1 lights exactly the row's printed words. Note: for these fixtures the row alone fills its line, so the line ids alone light the same words; the cells matter when a line holds other text.
**(b) trace.js `sourceLink`.** Kept extracted-only; `tests/test_pdf_imports_browser.py:71` and `:120` are untouched and pass. SC-26 doesn't need it (it opens the source from the document page). The branch is still unreachable from the UI, as SL-03 noted. Reviewer: delete it or extend it deliberately later.

## Deviations and things to look at
1. The plan row lists "`account_note` in the statement record view" under `trace.js`; the shared helper is there (`accountNoteBlock`), but the statement record view itself is `document_v2.js`/`review_v2.js`, where it is used.
2. The dialog's counts lines for receipts and pay stubs say "linked to its transactions", and a muted line says what stays. Wording is mine (spec FR-10/FR-12 give none). `refund_links` shows when non-zero (SL-06 deviation 2).
3. The dialog doesn't close if the route changes under it (browser Back). Not handled.
4. `design-system/home-manager/pages/*.md` not updated (not in the slice row); no new colors or components beyond `.danger-text` links and the existing dialog class.

## Pre-existing failures seen (identical on START_HEAD 4eb5a2e, checked by stashing the tracked changes)
`tests/test_transactions_v2_browser.py::test_transactions_v2_filters_categorises_adds_and_imports`; `tests/test_review_v2_browser.py::test_to_check_decides_each_kind_with_its_source_in_view`; `tests/test_records_v2_browser.py::test_records_v2_filters_strip_read_all_and_trash`. Not touched.

## Open issues
- Orchestrator: `plans/statement-accounts/progress.yaml` was not touched or staged.
