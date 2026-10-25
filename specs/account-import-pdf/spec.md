# Import account transactions from PDF documents
Feature: account-import-pdf

<!-- Approval state lives in approvals/<slug>.json and is bound to this file's content hash.
     Do not add a Status line: changing it would change the hash. Check with gate.py. -->

Amends: no earlier spec exists for this feature. The baseline is the built behavior of the CSV/XLSX transaction import
(`docs/documents.md` "CSV and XLSX imports", `docs/money.md` "What counts", `src/home_manager/finance/tabular.py`,
`src/home_manager/finance/ledger.py:1065–1105`) and of PDF reading (`docs/documents.md` "PDFs",
`src/home_manager/documents/pdf_reader.py`, `pdf_layout.py`). It sits beside `specs/document-forms/spec.md`, which governs
what statement extraction (**Record**) reads; this spec changes none of that.

Source of decisions: `specs/account-import-pdf/interview.md` (2026-10-24, complete). Its decisions D1–D14 are settled and
are cited below as "interview Dn". This revision replaces the earlier non-interactive draft and its open decisions D1–D7.

## Goal / users / scope / non-goals

**Goal.** The user's bank offers no CSV export, only PDFs (interview D1). A downloaded bank or card PDF can be imported
into an account through the same **Import transactions** flow as a CSV: preview, choose the account, import, see each row's
source. Nothing is counted that was not read by code from the PDF's text, and the same transaction is never counted twice,
whichever of CSV import, PDF import or Record brought it in.

**Users.** The household user who captures documents in the Inbox and imports them from Transactions, Accounts or the
document library.

**In scope.**
- PDF import from the saved reading of **native-text** pages (FR-01 to FR-03).
- Preview, table selection, cross-page table linking, year and sign choices, ticked/unticked rows (FR-04 to FR-12).
- Account preselection by printed last four, new account created with the import (FR-13 to FR-15).
- Relation to Record and to CSV/XLSX imports: one fingerprint, duplicates reported, both paths stay available (FR-16 to FR-20).
- Limits, integrity, atomicity, evidence (FR-21 to FR-24).
- Entry points: Import picker, library row, document page, primary-action rule (FR-25 to FR-28).

**Non-goals** (interview "Non-goals and follow-ups").
- Rows from scanned (`vision_model`) pages. They are reported and point to Record; no "proposed, not counted" import state.
- Moving cross-page linking into the PDF reader or changing the saved reading format; Record and the document page do
  not gain linking.
- Inferring the year from a printed statement period.
- Checking rows against printed opening and closing balances (Record does this).
- Changing statement extraction / Record, classification, statement forms or reconciliation.
- Investment, crypto and loan documents; receipts, bills and pay stubs as transaction sources.
- Currency conversion; importing into an account of another currency.
- A model or network call at import time.

## Existing behavior (verified paths, assumptions, unknowns)

All paths under `src/home_manager/` unless noted.

**Verified — CSV/XLSX import.**
- `core/formats.py:5–8` routes `.csv`/`.xlsx` to deterministic import; `finance/ledger.py:1078` refuses any other
  extension ("Transaction import supports CSV and XLSX documents.").
- `ledger.table_rows` (`ledger.py:1065–1085`) reads the preserved blob for `expected_hash`, refuses Trash, re-hashes the
  bytes, enforces 32 MiB. Limits in `finance/tabular.py:21–23`: 20,000 data rows, 60 columns, 2,000 characters per cell;
  over a limit the whole file is refused.
- Mapping, dates, signs: `tabular.py` `HEADER_NAMES`, header row in the first 25 rows, ambiguous day/month raises
  `MappingError`, sign is a choice with default `negative_is_outflow`. `core/money.py:32–58` `to_minor` reads `(45.10)`,
  `45.10-`, a currency code or symbol, and refuses a currency different from the account's.
- API: `POST /api/documents/{id}/transaction-import/preview` writes nothing (`app/api.py:920–927`);
  `POST …/transaction-imports` requires `account_id` ("Choose the account these transactions belong to.",
  `api.py:929–933`) and reconciles after (`app/manager.py:1439–1444`).
- Insert: `Ledger.import_transactions` (`ledger.py:1095–1105`), one DB transaction, origin `import`, a
  `transaction_imports` row (migration 013), evidence `source_key = "import:<id>"`, locator `{"rows": [n]}`.
- Fingerprint (`ledger.py:299–305`): account, posted date, amount, currency, ordinal among equals; source-independent.
  `insert_transactions` (`ledger.py:424–451`) is `INSERT OR IGNORE`; a duplicate gets an evidence link only.
- Counting (`ledger.py:36–43`): `COUNTABLE` counts an `import` row unless rejected; `extraction` rows only once verified
  and not `HELD` by an `awaiting` statement.
- Provenance reads only `locator.rows` for imports and treats imports as confirmed (`finance/provenance.py:36–41, 93–98`).
- UI: `library.js:150–227` `openImport` and `index.html:1128–1151` `#import-dialog`. The account select preselects the
  remembered `home-manager-import-account` or the first account; "New account…" is the empty option
  (`library.js:154–160`). New accounts are created through `POST /api/finance/accounts` (`api.py:915–918`,
  `ledger.create_account` `ledger.py:363`), separately from the import request.
- Import picker `money_v2.js:77–113`: fetches `status=ready_for_ledger&limit=200`, then filters to `.csv|.xlsx`
  client-side (`money_v2.js:85–86`); empty-state copy says "CSV or XLSX".
- Next step (`records_v2.js:452–466` `rc2Step`): table → Import; unread → Read; read and `!doc.ledger_status` → Record.
  `storage.py:555–563`: `ledger_status` becomes `imported` when any `transaction_imports` row exists for the hash, which
  today removes Record.
- Accounts carry `account_type` in `checking, savings, credit_card, brokerage, loan, other` and an optional 4-digit
  `account_last_four` (`library/migrations/011_finance.sql:11–22`, `ledger.py:30`).

**Verified — PDF reading.**
- `pdf_reader.complete_pdf` (`pdf_reader.py:64–108`): each page has `method` `embedded_text` or `vision_model`; native
  pages with layout issues add `pdf_layout_review` issues. Reader limits: 1–200 pages and existing character/evidence
  limits.
- Native tables (`pdf_layout.py:66–72`, built at `:526`): `PDFTable` with `rows` 2–500, `columns` 2–40, cells with
  `row`, `column`, `word_ids`, `line_ids`, `text`. **Every native table has `header_rows=[0]`**, so on a continuation page
  whose table has no printed heading, row 0 is a data row labelled as a header. Word geometry is reachable through
  `word_ids`.
- **A reading with no vision model fails as a whole when any page is scanned**: `transcribe` raises "Configure a local
  vision model ID before extracting text." (`models/vision.py:124–126`), and the run fails with no result
  (`tests/test_pdf.py:110–128`). A fully native PDF reads with no model and the result is reusable (same test).
- Record (`extraction.py`, `ledger.py:950–1000`) creates a statement `awaiting` reconciliation with `extraction` rows; a
  re-read keeps rows with evidence from another source (`ledger.py:973–990`).

**Assumptions.**
- A1. For the user's bank, each statement prints its transactions as one heading line (Date, Description, Amount or
  Debit/Credit) followed by one visual row per transaction. The reader may or may not build a native table for it (U2);
  FR-08 rebuilds the rows when it doesn't. Live accuracy is unmeasured; tests use synthetic PDFs modelled on the layouts in interview
  "Acceptance checks".
- A2. Last-four patterns printed by banks are covered by a small fixed list (FR-13); others simply produce no preselection.

**Unknowns.**
- U1. `gate.py` is not present in this repository; no `approvals/account-import-pdf.json` exists. Approval is recorded by the
  user with their own gate tooling. This spec asserts no status.
- U2. **Resolved 2026-10-24 by a reader check on synthetic pages: it does not.** `table_grid` (`pdf_layout.py:421–440`)
  requires a printed text heading row, so a page whose rows have no heading line gets no native table, by design ("stay
  text with a review issue"). A headed page whose Withdrawals or Deposits column is blank on every row also got no table
  in that check. FR-08 was therefore amended so the import rebuilds such rows itself from the saved words. The reader and
  the reading format stay unchanged (interview D9).

## Functional requirements

Terms. **PDF import** is this feature. **Record** is existing statement extraction. A **reading** is the saved
`pdf_reader` result for the document's exact bytes. A **transactions heading** is a set of heading cells or words that includes a date heading and an
Amount or Debit/Credit heading, using `tabular.HEADER_NAMES`. A **transactions table** is either a native table whose row 0
is a transactions heading, or a **rebuilt table**: rows the import rebuilds from a page's saved words when a visual row (FR-08)
is a transactions heading but the reader built no native transactions table for it. A **continuation page** is a later native page with no
transactions table of its own, that follows a transactions table with no other transactions table between them. Its rows
are rebuilt by the import (FR-08). (Amended 2026-10-24.) A **flagged page** is a native page with a
`pdf_layout_review` or `pdf_table_ambiguous` issue. **Counted** means included by `COUNTABLE`.

| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| **Source and boundary** | | |
| FR-01 | A PDF can be imported as account transactions through the same Import transactions flow and API as CSV/XLSX. A PDF stays a document that is read and recorded as today: it is not reclassified as a table file, and `needs_text` / `ready_for_ledger` filters return the same PDFs as before. CSV/XLSX behavior is unchanged. | `tests/test_imports.py` and `tests/test_formats.py` still pass; an unrecorded read PDF is still in `ready_for_ledger`. |
| FR-02 | PDF import reads only the saved reading for the version named by `expected_hash`. It makes no model or network call, does not decode the PDF in the request process, and does not read the Inbox or Library file. | With no model configured and network blocked, preview and import of a read native PDF succeed; changing the Inbox file after capture changes nothing. |
| FR-03 | Only `embedded_text` pages contribute rows. Every `vision_model` (scanned) page is listed in the preview and summary as "Page N is a scanned page; no rows imported. Use Record for scanned statements." Other pages still import. A PDF whose pages are all scanned previews with no rows and that message. | A 2-page PDF with one scanned page imports the native page's rows and lists the scanned page; no row has a scanned page as its source. |
| **Preview, tables and rows** | | |
| FR-04 | The preview lists every transactions table and every continuation table linked to one (FR-08), each with page, heading cells, row count and first rows, all selected by default. Other native tables are listed as "not a transactions table" and are not selectable. The preview and the import use the same selection. | A statement with a summary table and a two-page transactions table previews the transactions tables selected and the summary listed as not importable. |
| FR-05 | The preview writes nothing and is repeatable. Per row it shows: source page, as-printed date, description, as-printed amount, the signed amount in the account's currency, its status (New, Already recorded with source, Rejected with reason), whether it is ticked, and labels "continued from page N" (FR-08) or the page's layout issue (FR-09). Totals of money in and money out are shown for ticked New rows, separately from Already recorded rows. | Row counts in `accounts`, `transactions`, `financial_evidence_links`, `transaction_imports` are identical before and after three previews; preview output is identical each time; as-printed text equals the reading's cell text (for a rebuilt row, its words' text). |
| FR-06 | Dates are exact. A four-digit year is read as printed. A date with no year or a two-digit year is read only after the user picks the year in the preview (one year, or the first row's year for a period crossing New Year, after which a month that goes backwards advances the year by one). Import is disabled until chosen; the current year is never assumed. An ambiguous day/month order across the column is a required choice, as for CSV. A date that is not a real calendar date rejects its row with a reason. (Interview D4.) | "08/03 … 12/30 … 01/02" with no year cannot be imported until the year is chosen; with 2025 chosen as the first year the dates are 2025-08-03 … 2026-01-02. "02/30" is rejected. "08/03/2026" imports directly. |
| FR-07 | Amounts and signs are exact. Amounts are read with `core/money.to_minor` (integer minor units). A balance column (heading matching a balance name) is never used as an amount. Separate Debit and Credit columns decide the sign: debit is money out, credit is money in; a row with both is rejected with a reason. With a single Amount column, the sign convention defaults by the **chosen** account's type: `credit_card` → positive is money out; `checking` or `savings` → positive is money in; any other type → no default, choice required. The default is shown as the selected option, can be changed, and changes when the account changes. (Interview D5.) | Card statement, Amount column with charges positive, imported into a `credit_card` account: charges are negative without further choice. Same file into a `checking` account: charges positive (default), changing the choice flips them. Into a `loan` account: Import disabled until a choice is made. Balance never becomes the amount. |
| FR-08 | **Cross-page linking and rebuilt rows**, done by the import only (interview D9, D10; amended 2026-10-24 after U2 was resolved, and again after plan review pass 4). **Visual rows:** the import groups a page's saved words into visual rows by baseline, using the reader's own rule, regardless of how the reader split them into saved lines or tables. It does this because, on pages without a native transactions table, the reader saves one printed row as several lines. **Heading:** on a page with no native transactions table, the first visual row that is a transactions heading starts a **rebuilt table**. A native non-transactions table whose words share baselines with that heading or with the rows under it is part of the rebuilt table, not listed separately. **Column positions** come from the heading's words, or from a native transactions table's header cells. Each column spans from the midpoint before its heading to the midpoint after it, and each word goes to the column whose span holds its horizontal centre. **Rows:** after the heading on a rebuilt page, and on every continuation page that follows, a visual row is a row when it has a date in the date column and an amount in an amount column. A row whose date or amount doesn't fit a column (a word straddling two columns, or outside every column) is rejected with a reason. So is a row with text that isn't an amount, or two amounts, in one amount column. Other visual rows (titles, statement-period lines, footers, totals text without a date) are not rows and aren't counted. Rows on continuation pages use the continued table's mapping, are ticked and counted like its rows, and are each labelled "continued from page N", where N is the page of the heading. A continuation page with no rows is reported "Page N: no transactions table found". A new transactions table ends the chain. The reader and the saved reading are not changed; readings saved before this feature are linked the same way. | A 3-page statement, headings only on page 1: all rows of pages 1–3 import, and the rows of pages 2–3 are labelled "continued from page 1", including page 2's first row. A page-1 table whose Deposits column is blank on every row still imports its rows. A page whose only table is a headed non-transactions table (e.g. "Fee summary") is reported, and its rows are not imported. Any later-page row with a date and an amount in the continued table's columns is counted, a schedule included (accepted risk, interview D10); its rows appear in the preview totals. |
| FR-09 | Rows from a **flagged page** appear **unticked**, with the page's issue message and the parsed date and amount. A page holding a transactions table, native or rebuilt (FR-08), whose only layout issue is `unresolved_columns` counts as not flagged, and so does a continuation page with only that issue. The reader raises it for text outside its tables, such as a "Page 1 of 3" footer, or for headerless rows the import rebuilds itself. Such an issue is not listed in the preview either. Any other issue still flags the page (amended 2026-10-24, user decisions after plan review passes 4 and 5). Rows the user ticks import and count like any other row; unticked rows are not imported and are counted in the summary as "left out by you". (Interview D8.) | A flagged page's 4 rows preview unticked; ticking 2 and importing inserts 2 counted rows and reports 2 left out. |
| FR-10 | Anything the import cannot place is reported, never skipped silently or guessed: a scanned page, a page with no transactions table, an unlinked continuation, an unassigned column, a rejected row (bad date, both debit and credit, blank description, unparseable amount, currency mismatch). Each is listed with page and row and reason (first 200 issues), with counts imported, duplicate, rejected, left out and pages with no rows. | `imported + duplicates + rejected + left out` equals the rows seen in selected tables; every page of the reading appears either as a row source or in the issue list. |
| FR-11 | Currency is the chosen account's. A row whose printed currency differs is rejected; a document-level currency differing from the account's blocks the import with the reason. No conversion. | A PDF printing EUR amounts into a USD account imports nothing and says why. |
| FR-12 | Native import is deterministic: the same bytes, reading, selection, ticks and choices always give the same rows. Rows are inserted with origin `import` and count at once, as CSV rows do. | Preview twice gives identical rows; an imported row is counted and appears in Spending. |
| **Account** | | |
| FR-13 | The PDF dialog ignores the remembered CSV account. It preselects an account **only** when the last four digits of exactly one active account whose currency matches the document appear in the reading's native text in one of these forms: "ending in NNNN", "ending NNNN", "XXXXNNNN" or "xxxxNNNN" (any count of X/x/\*/•/… before the digits), "\*NNNN", "…NNNN". The match is shown ("Matched …4821 printed on page 1") and can be changed. Zero or several matching accounts → nothing preselected and Import disabled until the user chooses. No account is looked up or created by bank name. (Interview D6.) | Accounts A (…4821) and B (…7700); PDF prints "Account ending in 4821": A preselected with the match text. PDF prints both numbers, or neither: nothing preselected; Import disabled; POST without `account_id` returns 400 "Choose the account these transactions belong to." |
| FR-14 | New account: the PDF dialog keeps the "New account" fieldset (institution, type, currency, name typed by the user). Last four is prefilled only when exactly one distinct NNNN is found by the FR-13 patterns, and is editable. The account is **created by the import request itself, in the same database transaction** as the rows: a refused or failed import leaves no new account. (Interview D7; this differs from CSV, which creates the account by a separate request.) | Import with a new account and a forced failure on the last row: no account, transaction, evidence or import record exists. Success: one account with at most 4 digits stored, holding the rows. |
| FR-15 | The account type chosen or created drives FR-07's sign default and FR-13's preview totals are recomputed when the account changes. | Switching from a card account to a checking account in the dialog flips the default sign and the totals before import. |
| **Duplicates and Record** | | |
| FR-16 | One transaction, whichever source: PDF import uses the existing source-independent fingerprint. A row already recorded by CSV/XLSX import, Record or an earlier PDF import is a duplicate: not inserted, its evidence is linked, and its origin, review status, category, tags, links and statement are unchanged. | Importing a CSV then the PDF of the same period: 0 inserted, N duplicates, totals unchanged. Same for the other orders (SC-09 to SC-12). |
| FR-17 | Duplicates are explained per source: "Already recorded from import *name*", "…from statement *name*" ("…from this statement" when it is this PDF's own statement). A manual entry has no shared fingerprint, so a matching manual entry is not a duplicate: the PDF row is New, labelled "replaces a manual entry", and after the import reconciliation replaces the manual entry as it does for CSV (`reconcile.replace_manual`, amended 2026-10-24 from plan review). When the existing row is a statement row not yet counted (unverified or `awaiting`), the message says it is still not counted and that reconciling the statement releases it. A row the user rejected earlier is reported "rejected earlier" and stays rejected. | Importing the PDF of a statement awaiting reconciliation: all rows duplicates; message "Already recorded from this statement; not counted until you reconcile it." |
| FR-18 | Import and Record coexist in either order (interview D3). After a PDF import, the PDF still offers Record (an `imported` ledger status from PDF import must not hide Record). After Record, PDF import is still offered. A later statement takes over matching rows (`statement_id` set) without changing their origin or counting; a statement re-read keeps rows with import evidence. | Import then Record: statement exists, its matching rows reference it, keep origin `import` and stay counted; no duplicates; Record visible before and after import. |
| FR-19 | A PDF recorded as a receipt, bill, pay stub or other non-account document, or in Trash, cannot be imported. The refusal names the record ("This PDF is recorded as a receipt.") or says "Restore the document from Trash before importing it." A PDF recorded as a bank or card statement, or not recorded, can be. | Preview of a receipt PDF returns the error and writes nothing. |
| FR-20 | Re-importing the same PDF into the same account inserts 0 and reports all duplicates, adding a `transaction_imports` record. Importing into a different account inserts rows there; the summary names the account. | SC-13. |
| **Limits, integrity and evidence** | | |
| FR-21 | Limits: at most 20,000 data rows across selected tables, 2,000 characters per cell, 200 listed issues; reader limits (1–200 pages) apply. Exceeding a limit refuses the whole import naming the limit; nothing is truncated. No real reading can reach 20,000 rows (24 MiB evidence and 250,000-character reader caps), so the row limit is defence in depth (amended 2026-10-24). | Analyzer: 20,001 rows refused with "exceeds 20,000 data rows", 20,000 accepted. API with the limit lowered for the test: one row over refuses the whole import, 0 inserted. |
| FR-22 | Before any write: `expected_hash` equals the document's current version, the preserved blob re-hashes to it, the reading belongs to that hash and validates as saved evidence, and the reading is the one the preview used. Any failure refuses with "Preserved evidence failed its integrity check. Nothing was imported." or "This document was read again since the preview; preview again." and writes nothing. | Corrupt blob, tampered reading, replaced document, or re-read after preview: each refused, zero new rows, accounts, evidence or import records. |
| FR-23 | The import is atomic: new account (FR-14), inserts, evidence links and the `transaction_imports` record are one database transaction; reconciliation runs after, as for CSV. The record keeps the reading id, selected and linked tables, mapping, year, sign, ticked/unticked rows and counts. | Fault after the third insert: nothing written; retry imports all. |
| FR-24 | Every PDF-imported transaction keeps evidence of its printed source: document, blob hash, reading id, page, table, row, and cell/line ids (a rebuilt row cites its line and word ids). The transaction's source panel and `GET /api/provenance/transaction/{id}` show "imported from *file*, page *N*" with a link to the page preview and the cited cells (or, for a rebuilt row, its line) highlighted, and "continued from page N" for linked rows. | Provenance of a PDF row returns file, page and row and the UI opens the page with cells highlighted; it is not reduced to a bare row number. |
| **Entry points and dialog** | | |
| FR-25 | The Import picker (Transactions Import, Accounts Import an export, per-account buttons) lists importable PDFs (a reading with at least one transactions table, not refused by FR-19) labelled "PDF", with CSV/XLSX files; copy mentions PDF. The list is not cut to the first 200 `ready_for_ledger` documents before filtering by type, so a CSV is never hidden behind PDFs. | 250 read unrecorded PDFs and 1 CSV: the CSV is listed; an unread PDF and a table-less PDF are not; empty state names PDF, CSV and XLSX. |
| FR-26 | On a PDF's library row and document page, **Import transactions** is the **primary** action when all hold: a reading exists, it has a transactions table, the FR-13 rule finds exactly one matching account, and the PDF is not recorded as a receipt, bill or pay stub (interview D12). Otherwise Record (or Read) stays primary as today and Import transactions is a secondary action (More actions, and a button beside Record on the document page) whenever a reading with a transactions table exists. CSV/XLSX keep Import as theirs. | A read bank PDF printing a saved account's last four shows Import as its step; a read PDF with no matching last four shows Record with Import under More actions; an unread PDF shows Read. |
| FR-27 | Unread PDF: choosing Import on a PDF with no usable reading shows "Read this document first" and a **Read** button; when reading finishes the dialog refreshes into the preview. Import itself never reads the PDF. How the Read started here treats scanned pages is open decision OD-1. | Unread native PDF: Read, then preview without reopening the dialog; nothing written before Import. |
| FR-28 | The dialog is the existing `openImport` / `#import-dialog` with a PDF mode: table list, year choice, sign choice with its default, row ticks, page labels, duplicate messages, preselection match text. CSV-only controls (worksheet, column mapping) are hidden. Keyboard and screen reader behavior as for CSV: all controls reachable, status in a live region, focus returns to the opener. | Browser test following `tests/test_transactions_v2_browser.py` conventions operates the dialog by keyboard only. |
| **Failure and privacy** | | |
| FR-29 | Every refusal names what is wrong and the next step (Read, preview again, choose an account, choose the year or sign, Restore, or "Use Record for scanned statements"), leaves all data unchanged and can be retried. | Each refusal scenario returns its message with unchanged row counts. |
| FR-30 | Nothing leaves the machine. Printed account numbers are never stored as account identity beyond the last four. Descriptions are stored as printed (up to 500 characters, as CSV). | With network blocked, preview and import succeed; created accounts store at most 4 digits. |

## Invariants, privacy, security and data retention

- **Money is exact and per currency** (`docs/money.md` "What counts"): integer minor units from `to_minor`, ISO currency,
  negative = money out after normalization, no floats, no currency inferred from an ambiguous symbol.
- **The model proposes, the code decides.** PDF import adds no model step and imports nothing a model read.
- **One transaction, one record.** The source-independent fingerprint is the only identity; PDF import changes existing rows
  only by adding evidence links.
- **Evidence is preserved.** The original, preserved blob and saved reading are never changed. Import adds evidence links,
  at most one account and one `transaction_imports` row.
- **Data leaving the machine: none.** Reading is local; import is local computation (FR-02, FR-30). Descriptions may hold
  personal text as printed, as with CSV; row contents are not logged (`docs/operations.md`).
- **Retention** follows existing Trash behavior; import is refused while the document is in Trash.
- **Private data.** Development, tests and evals use synthetic PDFs only (`tests/test_pdf.py` `make_pdf`); no live library
  or donated corpus is read.

## Errors, recovery, duplicates, restart behavior

- **No half imports.** One request, one database transaction including any new account (FR-14, FR-23). A crash before
  commit leaves nothing; after commit, a missed reconciliation pass is repaired by **Reconcile now**, as for CSV.
- **Retry** with the same choices: 0 inserted, all duplicates, one more import record (FR-20).
- **Reading replaced** after preview: refused, preview again (FR-22). Rows imported from the earlier reading keep that
  reading's evidence.
- **Document replaced**: new hash, separate import; earlier evidence still points to the earlier hash.
- **Record later / statement re-read**: FR-18; a re-read never deletes a row with import evidence.
- **Overlapping periods**: duplicates by fingerprint, as for CSV. Same-day, same-amount rows are told apart only by their
  ordinal, a limitation shared with CSV and statements (`docs/money.md` "Import identity").
- **Model busy**: import neither waits for nor blocks model work.

## Nondeterministic outputs and how they are verified

- PDF import is deterministic (FR-12): tests assert exact rows, signs, dates, ticks, counts and messages from synthetic
  PDFs built with `make_pdf`.
- No row comes from a model (FR-03), so no tolerance-style assertion is needed for this feature. A test may use a stub
  vision model (`local_model`) only to produce a mixed reading, and asserts that the scanned page contributes no rows.
- Import ids, timestamps and evidence ids are asserted only as present and well formed (`import:<32 hex>`).

## Scenarios (expand into test-contract.md with design-tests for stateful features)

Synthetic fixtures (interview "Acceptance checks"): `K` is a 3-page checking statement, Date | Description | Withdrawals |
Deposits | Balance, headings only on page 1, 4-digit years, 9 rows, prints "Account ending in 4821". `R` is a 2-page card
statement, Date | Description | Amount, charges positive, payments negative, dates like "08/03" with no year, prints
"XXXX7700". `Kc` is a CSV of the same rows as `K`. `A` is a USD checking account …4821; `C` is a USD credit card …7700.

| ID | FR IDs | Initial state | User/API actions | Expected final DB/files/UI state |
|---|---|---|---|---|
| SC-01 | FR-01, FR-02, FR-04, FR-08, FR-12, FR-13 | `K` read; accounts `A`, `C`; no model configured; network blocked | Import picker → `K`; Import | `A` preselected with "Matched …4821 printed on page 1"; 9 rows in `A`, origin `import`, counted; pages 2–3 rows labelled "continued from page 1"; Balance never an amount; withdrawals negative; PDF still offers Record |
| SC-02 | FR-06, FR-07, FR-15 | `R` read; account `C` | Preview; choose year 2025; Import | Before year: Import disabled with "Choose the year"; sign defaults to positive = money out (card); charges negative, payments positive; no date uses the current year |
| SC-03 | FR-07, FR-15 | `R` read; accounts `A`, `C`, and a `loan` account | Choose `A`, then the loan account | `A`: default positive = money in, totals flip; loan: Import disabled until a sign is chosen |
| SC-04 | FR-05 | `K` read; empty ledger | Preview three times | Counts in all ledger tables unchanged; identical output; all rows New |
| SC-05 | FR-13 | `K` read; accounts `A` and another with …4821 in EUR; then a PDF printing both 4821 and 7700 | Open dialog for each | First: `A` preselected (only currency match). Second: nothing preselected, Import disabled; POST without account → 400 |
| SC-06 | FR-14, FR-23 | `R` read; no card account | New account (Bank, credit_card, USD); last four prefilled 7700; inject fault on last row; Import; remove fault; Import | After fault: no account, transaction, evidence or import record. After retry: one account …7700 with all rows |
| SC-07 | FR-08, FR-10 | 3-page PDF: page 1 transactions table (5 cols), page 2 headerless rows, page 3 a headed "Fee summary" table; variants: a page-1 column blank on every row, a schedule after the table | Preview | Page 2 rows rebuilt, ticked, labelled; page 3 reported "no transactions table found"; counts add up; the blank-column page imports; the schedule is counted (D10) |
| SC-08 | FR-09 | PDF with page 2 flagged `pdf_layout_review` (4 rows) | Preview; tick 2; Import | Page-2 rows unticked with the issue message; 2 inserted and counted; 2 reported "left out by you" |
| SC-09 | FR-03, FR-10 | Mixed PDF read with stub vision model: page 1 native, page 2 scanned | Preview; Import | Page 1 rows imported; page 2 listed "scanned page; use Record"; no row sourced from page 2 |
| SC-10 | FR-16, FR-17 | `Kc` imported into `A`; variant: a manual entry matching k3 | Import `K` into `A` | 0 inserted, 9 duplicates "already recorded from import *Kc*"; totals unchanged; evidence links added. Variant: k3 New "replaces a manual entry", 9 inserted, manual entry replaced after reconciliation |
| SC-11 | FR-16, FR-17, FR-18 | `K` Recorded into `A` (statement `awaiting`, `extraction` rows proposed) | Import `K` | 0 inserted; message says not counted until reconciled; origin and status unchanged; rows still held |
| SC-12 | FR-18 | `K` imported into `A` | Record `K` (stub extraction returns the same rows) | Statement `awaiting`; rows get `statement_id`, keep origin `import`, stay counted; no new rows; Record shown before and after import |
| SC-13 | FR-20 | `K` imported into `A`; account `B` exists | Import `K` into `A` again; then into `B` | `A`: 0 inserted, new import record; `B`: 9 inserted; summary names `B` |
| SC-14 | FR-17 | One `K` row rejected by the user | Import `K` again | That row reported "rejected earlier", stays rejected |
| SC-15 | FR-19 | A receipt PDF; a PDF in Trash; a statement-recorded PDF | Preview each | Receipt refused naming the record; Trash refused with Restore; statement previews with duplicates |
| SC-16 | FR-21 | In-memory reading with 20,001 / 20,000 rows; a real reading with the row limit lowered | Analyze; Preview; Import | 20,001 refused with the limit, 20,000 accepted; over the lowered limit the whole import is refused, 0 inserted |
| SC-17 | FR-22 | `K` previewed; then (a) blob corrupted, (b) reading tampered, (c) document replaced, (d) document read again | Import after each | Each refused with its message; nothing written |
| SC-18 | FR-11 | PDF printing EUR amounts; account `A` USD | Preview; Import | Blocked with the currency reason; nothing inserted |
| SC-19 | FR-25 | 250 read unrecorded PDFs, 1 CSV, 1 unread PDF, 1 read PDF with no table | Open the picker from Transactions and Accounts | CSV listed; only PDFs with a transactions table listed, labelled PDF; copy mentions PDF |
| SC-20 | FR-26 | `K` read (matches `A`); a read PDF with a table but no matching last four; an unread PDF; a CSV | View library rows and document pages | `K`: Import primary; second: Record primary, Import under More actions; unread: Read; CSV: Import |
| SC-21 | FR-27 | Unread native `K` | Import picker → … → dialog | "Read this document first" + Read; after reading finishes the preview appears without reopening; nothing written |
| SC-22 | FR-24 | A row imported from page 2 of `K` | Open its source panel and provenance | "Imported from K, page 2", "continued from page 1", page preview with cells highlighted |
| SC-23 | FR-28 | `K` read; browser | Operate the dialog by keyboard only | All controls reachable; status announced; focus returns to opener |
| SC-24 | FR-06 | One-page PDFs: year-less dates crossing New Year; "02/30/2026"; 4-digit years; ambiguous day/month; two-digit years | Preview; choose year / order; Import | New Year rows advance the year; 02/30 rejected; 4-digit dates import directly; day/month order and two-digit years blocked until chosen |
| SC-25 | FR-07, FR-10, FR-30 | One-page Debit/Credit PDF with a both-columns row, a blank description, an unparseable amount and a 480-character description | Preview; Import | Three rows rejected with page, row and reason; two imported; long description stored as printed; Balance never an amount |
| SC-26 | FR-01 | CSV/XLSX suites; a read and an unread PDF | Run existing suites; list `ready_for_ledger` / `needs_text` | Suites pass unchanged; PDFs appear in the same filters as before; CSV dialog behavior unchanged |

Recommended next step: run `design-tests` before approval. The feature is stateful, multi-step and touches money and
account creation.

## Out of scope / product decisions requiring approval

**Settled in the interview** (not to be re-asked): D1–D14 in `interview.md`, including the accepted risk in D10. As amended on
2026-10-24, that risk reads: any later-page line with a date and an amount in the continued table's columns is counted.

**Open decisions**

| ID | Decision | Recommended default and rationale |
|---|---|---|
| OD-1 | Interview D11 asked that a Read started from the Import dialog run no model. Verified: a reading with no vision model **fails as a whole** if any page is scanned (`models/vision.py:125`, `tests/test_pdf.py:124–128`), so a no-model Read of a mixed PDF would yield nothing to import. Options: (a) the dialog's Read starts the normal Read (configured vision model transcribes scanned pages; the import still ignores them per FR-03); (b) add a reader mode that saves native pages and marks scanned pages untranscribed, which changes the shared reading format that interview D9 chose not to touch. | **(a)**: the import still never uses a model's rows; the model only runs in the existing, visible Read job, and no reader format changes. If no model is configured, a fully native PDF reads fine; a mixed PDF fails with today's "Configure a local vision model" message and the dialog says so. |
| OD-2 | What is a balance heading for FR-07, and does the rule also apply to CSV? `tabular.py` has no balance handling today (verified: no "balance" in the file). | A fixed list ("Balance", "Running balance", "New balance", "Ending balance") applied to **PDF import only**, so CSV behavior stays unchanged (FR-01). Applying it to CSV too would be a separate change. |
| OD-3 | How is `ledger_status` presented once a PDF has both an import and no statement (FR-18)? | Keep `imported` as the badge, but `rc2Step` treats a PDF with only `imported` as still recordable. |

**Domain risk pass (candidates; accepted ones become FR/SC)**

| # | Scenario | Consequence if unhandled | Recommended default |
|---|---|---|---|
| R1 | FR-08 counts the lines of a "Payment schedule" or "Interest charge" table that carry a date and an amount in the continued table's columns. | Phantom spending. | Accepted risk by the user (interview D10); mitigated only by preview totals. Not raised again. |
| R2 | FR-13 preselects an account from a last four printed for a *different* account (e.g. "Payment from account ending 4821" on a card statement). | Rows land in the wrong account; sign default follows the wrong type. | Candidate: preselect only when the match is on page 1. Needs user decision. |
| R3 | FR-26 makes Import primary; the user imports a PDF, then never Records it, so balances are never checked. | Missing or extra rows go unnoticed. | Candidate: the import summary says "Record this statement to check its balances." Needs user decision. |
| R4 | FR-06 New Year rollover: a statement listing rows newest-first makes a "month goes backwards" rule advance the year wrongly. | Rows a year off. | Candidate: detect row order from the first and last dates and apply the rollover in that direction; if both orders fit, require the user to pick each year boundary. Needs user decision. |
| R5 | FR-14 new account with the same institution/type/last four as an existing one (`accounts_identity` unique index, `011_finance.sql:22`). | Import fails with a raw constraint error. | Candidate: refuse with "An account …NNNN at *bank* already exists; choose it." Needs user decision. |

**Workflow limitation.** `gate.py` is not present (U1); no approval was queried or recorded and `approvals/` was not
touched. The user approves `spec.md` (and `test-contract.md` if `design-tests` produces one) with their own gate command.
