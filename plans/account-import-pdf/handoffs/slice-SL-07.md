```yaml
slice: SL-07
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: c979bf2
end_head: <the commit; see `git log -1`>
commit: <this commit>
changed_files:
  - src/home_manager/app/static/library.js          # PDF mode of openImport/previewImport/confirm, Read-then-preview, new_account, ticks, tables
  - src/home_manager/app/static/index.html          # #import-dialog PDF controls; picker hint and the Accounts "About these balances" copy name PDF, CSV and XLSX
  - src/home_manager/app/static/style.css           # scoped rules for the PDF dialog (after #import-status)
  - src/home_manager/app/static/money_v2.js         # the one allowed change: the JS rewrite of the picker hint is removed (copy now in index.html)
  - tests/test_pdf_imports_browser.py               # sc21 (incl. 21-a), sc23, new-account/table-choice test, flagged-rows test
  - plans/account-import-pdf/handoffs/slice-SL-07.md
checks:
  - command: 'RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_pdf_imports_browser.py -k "sc21 or sc23" -q'
    exit_code: 0   # 2 passed
  - command: 'RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_transactions_v2_browser.py -q'
    exit_code: 1   # 1 failed, 1 passed. test_transactions_v2_filters_categorises_adds_and_imports fails at tests/test_transactions_v2_browser.py:129 (the 390px Charges row `.tx2-name` has no box), AFTER its CSV import steps passed. It fails identically at START_HEAD (checked with git stash): pre-existing, unrelated
  - command: 'RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_pdf_imports_browser.py -q'
    exit_code: 0   # 8 passed (sc19 x2, sc21, sc22 x2, sc23, new-account/table, flagged)
  - command: '.venv/bin/python -m pytest tests/test_pdf_imports.py -q'
    exit_code: 0   # 140 passed
  - command: 'RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_accounts_v2_browser.py -q'
    exit_code: 0   # 2 passed (CSV import from the Accounts picker)
  - command: '.venv/bin/ruff check tests/test_pdf_imports_browser.py'
    exit_code: 0
  - command: 'node --check src/home_manager/app/static/library.js'
    exit_code: 0
  - command: 'RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_browser.py -q -x -k configures'
    exit_code: 1   # fails at tests/test_browser.py:389-391 (extraction output validation / PDF viewer), before and after this slice; its CSV import step (:321) is passed through. Pre-existing, unrelated
escalations: []
```

# SL-07 handoff: the Import dialog's PDF mode

Spec, plan, `progress.yaml`, approvals, `reviews.md`, design-system and every Python module under `src/` are untouched. No API change was needed. The CSV/XLSX path of the dialog is unchanged (the same ids, requests and behavior; the CSV preview test in `test_accounts_v2_browser.py` and the CSV steps of `test_transactions_v2_browser.py` pass).

Design guidance used: `ui-ux-pro-max` (visible labels, errors and status in a live region, tables scroll inside their own wrapper, no hover-only controls), `design-system/home-manager/MASTER.md` (tokens only, tinted region, status badges, 120ms focus ring from the shared styles) and `docs/ui.md` "Screen rules" (decision in view: the Import button sits above the rows, which scroll in a 38vh region; money is the server's text; strict CSP, no inline style).

## The dialog as built (`isPdf(doc)` from the library row's extension)

- **Controls shown/hidden.** The worksheet/column-mapping row (`#import-csv-map`), the CSV sign label and the CSV rows table are hidden; added: a **Tables to import** list, a **Year** select, the existing **Date format** select, a PDF **Amount sign** select, and a PDF rows table.
- **Account.** Starts from `account_match` (never localStorage): options are `Choose an account…` (value `none`), `New account…` (value ``, the CSV meaning), then the accounts. The first successful preview selects the match and writes its text (`Matched …4821 printed on page 1`) under the select; with no match it says `No saved account matches this PDF. Choose one, or add a new account.` The note follows the select (shown only while the matched account is selected).
- **New account.** The fieldset shows with `New account…`. The last four is prefilled from `new_account_last_four` until the user types in it. Previews send `account_type` and the valid part of `currency`, plus `new_account` once institution, 3-letter currency and a 0- or 4-digit last four are valid. The import sends `new_account` and no `POST /api/finance/accounts` (a test watches the requests). Import stays disabled until institution/currency/last four are valid.
- **Tables.** Selectable tables are checkboxes (`Page N · headings · n rows`, `(rebuilt from the page)` for rebuilt); continuation tables are plain text (`continues the table on page M`), others `not a transactions table`. A toggle sends `tables` (the ids still ticked); nothing is sent until the user toggles one.
- **Year / date order / sign.** Year select (`Choose…` + the years from next year back 30 years; no default) appears while `required` includes `year` (and stays once chosen). Date format is the existing select (reset to `auto` on open). The sign select appears when the first table has a single Amount column (`"amount" in mapping`) or the server requires it; it shows the server's sign in force (the choice, else the default, else `Choose…`), with `This is the usual sign for this type of account.` Only an explicit choice is sent as `sign`, so switching the account moves the default (FR-15).
- **Rows.** Columns Page, Date as printed, Description, Amount as printed, Signed amount (the server's `display_amount` through `amount()`), Status (a `statusBadge` carrying the server's `status_text`, then each label such as `Page 2 PDF layout needs review …` or `replaces a manual entry`), and a tick (`aria-label` names page, row and description; disabled for rejected rows). A tick sends `ticked`/`unticked` (kept exclusive); the default ticks are the server's.
- **Totals and status.** `#import-status` (role status, aria-live polite) shows the required-choice messages, the blocking reason, or `N new, N already recorded[, N rejected earlier], N not importable, N left out. Money out …; money in ….` (the counts and totals are the server's; the browser adds nothing).
- **Re-preview.** Every change re-previews. A stale answer is dropped (sequence number), and focus stays on the control that was changed while the table and list redraw (`data-key`).
- **Import** is disabled while there is no preview, `blocked`, `required`, no complete account, or no ticked row that is not rejected. It waits for a preview started a moment earlier (a field's change event fires as the click lands). The request carries `reading_id`. On success the summary (`Imported N new transactions into <account>; N were already recorded, N rows were not importable and N were left out.` plus pages without rows) stays in the live region, the dialog locks its controls, focus moves to Close, `importDone` runs (the Money screens reload) and the nav counts refresh. Closing returns focus to the opener (native, with a fallback in the close handler).
- **Unread PDF.** The preview's `Read this document first.` refusal shows the panel `Read this document first` with a **Read** button (focused). Read posts `/api/documents/{id}/receipt-runs`, polls `/api/receipt-runs/{id}` until it ends, then re-previews in the same dialog and moves focus to the account select. A failed reading shows the run's error in the live region (21-a: `Configure a local vision model ID before extracting text.`) and re-enables Read. Nothing is written by the dialog before Import.
- **Copy.** `index.html` now names PDF, CSV and XLSX in the picker hint (moved from `importPicker`; its rewrite line is deleted) and in the Accounts "About these balances" note (the old `CSV or XLSX` line).

## Tests (`tests/test_pdf_imports_browser.py`)

- `sc21`: Ku (native, reading disabled by setting `organize_after_scan` off, so it waits unread). Unread dialog shows the Read panel and no Import; ledger tables and parse runs unchanged; 21-a on a mixed PDF: the vision-model message, no reading, ledger unchanged; Ku: Read -> the 9-row preview in the same dialog (a `close` listener proves it was not reopened), `A` preselected, one reading, ledger tables unchanged, closing writes nothing.
- `sc23`: keyboard only after one `goto` (accounts A, C, L; K and R read; localStorage points at C). PDF mode, tables, page labels, mapping controls hidden, `A` matched not `C`, focus inside; Tab reaches table checkbox, account, the new-account fields, Preview, Import and every row tick in order; a row tick by Space keeps focus; the summary lands in the live region; focus on Close, then back on the opener; R: card default sign, year required (typed by keyboard), totals flip between C (out -112.94, in 269.99) and A (out -269.99, in 112.94), L needs a sign; no pageerror and `NO_OVERFLOW` throughout.
- Extra: a new account is created by the import request alone (and the table list can be switched off); flagged-page rows start unticked with the reader's label, the date order is a required choice, and the ticked ones import.

## Deviations and notes (please confirm)

1. **The row's More actions entry is SL-08's.** SC-21 step 1 says "From Ku's More actions"; the test opens the dialog with `openImport(<library row>)`, which is what that entry will call. The picker path is covered by SC-23.
2. **Ku is made unread by turning automatic reading off.** Capture reads a native PDF as it arrives (SL-03 note), so the test sets `manager.vision.organize_after_scan = False` (a user setting) rather than deleting a reading.
3. **Row status badges reuse `STATUS` entries** (`ui.js` is outside this slice): New -> `not_imported` tone, already recorded -> `imported` (check icon), rejected / rejected earlier -> `rejected`, each with the server's own text as the label. A dedicated vocabulary can come with the redesign.
4. **The sign select is hidden for a table with Debit/Credit columns** (where the sign has no effect), and its options read `Negative is money out` / `Positive is money out` so they fit the row.
5. **Year choices** are a fixed list built in the browser from the clock (next year back 30 years); the server has no list. No default is chosen.
6. **The Import button is not disabled while a preview is in flight** (it would swallow the click that blurs a field). The click waits for the latest preview and does nothing if it now blocks.
7. **`Read` detection compares the error text** `Read this document first.`; there is no structured error for it (no API change was needed or made).
8. **Pre-existing failures** (both fail the same way at START_HEAD): `tests/test_transactions_v2_browser.py::test_transactions_v2_filters_categorises_adds_and_imports` (390px Charges row has no `.tx2-name` box, after the CSV import steps pass) and `tests/test_browser.py::test_real_browser_configures_scans_and_inspects_versions` (extraction/PDF-viewer assertions). The slice's verification command for `test_transactions_v2_browser.py` therefore exits 1 for a reason outside this slice; the CSV import portion of it passes.
9. Not done here (SL-08): the library row / document page entry points, trace badge link text, docs. `docs/ui.md` and `docs/documents.md` are not edited by this slice.

## Screenshots (synthetic data, not in the repo; script `/tmp/sl07/shots.py`)

- Before: `/tmp/sl07/before-K-pdf.png`, `/tmp/sl07/before-R-pdf.png` (the old CSV-only dialog on a PDF), `/tmp/sl07/before-bank-csv.png`.
- After: `/tmp/sl07/after-K-pdf.png` (matched account, tables, rows), `/tmp/sl07/after-R-pdf.png` (year required, sign default), `/tmp/sl07/after-U-pdf.png` (unread: Read panel), `/tmp/sl07/after-bank-csv.png` (CSV dialog unchanged).

## Notes for SL-08

- `openImport(doc, {onDone})` takes a library row; PDF mode is chosen by `relative_path`. The `rc2Menu`/`doc2Steps` entries only need to call it.
- After a PDF import the dialog stays open on the summary; `onDone` receives the import response (`inserted`, `duplicates`, `rejected`, `left_out`, `account_id`, `account_name`, …).
