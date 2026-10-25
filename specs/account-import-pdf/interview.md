# Interview: Import account transactions from PDF
Date: 2026-10-24 · Status: complete

## Summary
The user's bank offers no CSV export, only PDFs, so the **Import transactions** flow that works for CSV/XLSX must also
accept a bank or card PDF and bring its rows into a chosen account. The first release handles downloaded (native-text)
PDFs only and never calls a model. Import and the existing **Record** step coexist on the same PDF in either order, with
rows de-duplicated by the existing fingerprint. Tables that continue across pages without repeated headings are linked
by the import. Nothing is cut: everything below ships together.

This interview supersedes the open decisions D1–D7 in the earlier non-interactive draft `spec.md`; where the two differ,
this file wins.

## Decisions
| # | Area | Question | Answer | Source |
|---|------|----------|--------|--------|
| D1 | Problem | Why import a PDF instead of using Record? | The bank gives only PDFs, no CSV; the user wants the same flow they use for CSVs. | user |
| D2 | Scope | Native-text PDFs, scanned, or both? | Downloaded (native-text) PDFs only. A scanned page is reported and points to Record. No "proposed" import state is needed. | user |
| D3 | Data | Can a PDF be both imported and Recorded? | Yes, in either order. Rows de-duplicated by the source-independent fingerprint; never counted twice. Importing must not hide Record (today `ledger_status = imported` removes it). | user |
| D4 | Data | Dates printed without a year | The user picks the year in the preview (one year, or the first date's year for a period crossing New Year). Import disabled until chosen; current year never assumed. Automatic period detection deferred. | user |
| D5 | Money | Sign for a single Amount column | Default by account type: `credit_card` → positive = money out; `checking`/`savings` → positive = money in; any other type → required choice. Default is visible, changeable, and preview totals (in/out) show the effect. Debit/Credit columns decide automatically. A balance column is never the amount. | user (per-type mapping delegated: default + reason "card statements print charges positive; bank statements print deposits positive") |
| D6 | Data | Account selection | Pre-select only when the last four digits of exactly one active account in the document's currency appear in the PDF text (e.g. "ending in 4821", "XXXX4821"). Show the match ("Matched …4821 printed on page 1"). Zero or several matches → no preselection. The remembered CSV account is not used. Never create or look up an account by bank name from the PDF. | user |
| D7 | Data | New account on first import | Same "New account" fieldset as CSV. Last four prefilled only when exactly one "ending in NNNN" pattern is printed (editable); institution, type and currency typed by the user. The account is created only together with the import, in one step; a failed import leaves no empty account. | user |
| D8 | Failures | Native page flagged `pdf_layout_review` / `pdf_table_ambiguous` | Its rows are shown **unticked**, with the page's issue message and the parsed date and amount. Rows the user ticks import and count like any other row. | user |
| D9 | Scope | Cross-page tables | **Added to this feature.** Linking lives in the import only (reader, saved reading format and Record unchanged; existing readings benefit without Read again). Moving it into the reader is a follow-up. | user |
| D10 | Money | When is a continuation table linked? | Always automatically when a headerless table has the same column count as the previous transactions table; rows are ticked and counted and labelled "continued from page N". User was warned that a schedule/interest table could be counted as spending and accepted the risk, relying on the preview totals. | user (after pushback) |
| D11 | Flow | Import on an unread PDF | The dialog says "Read this document first" with a **Read** button and refreshes into the preview when reading finishes. A reading started from Import runs no model; scanned pages found then are reported as scanned. | user |
| D12 | Interface | Entry points | Import picker (Transactions, Accounts, per-account) lists importable PDFs labelled PDF beside CSV/XLSX; fix the 200-document cap so a CSV is never hidden behind PDFs; copy mentions PDF. On a PDF row and its document page, **Import is the primary action** when the reading has a transactions table **and** a saved account's last four is printed (D6 rule) **and** it is not recorded as a receipt, bill or pay stub. Otherwise Record stays primary and Import transactions is under More actions whenever a reading exists. | user |
| D13 | Risky | Integrity, atomicity, limits, refusals, privacy | Kept from the draft spec: expected_hash and blob re-hash and reading-belongs-to-hash checks before any write; one DB transaction; CSV limits (20,000 rows, 2,000-char cells, 200 issues), refuse not truncate; receipts/bills/pay stubs/Trash refused with the record named; currency mismatch rejects; no network or model; synthetic fixtures only. | delegated (default + reason: same guarantees as CSV import; no reason to weaken) |
| D14 | Constraints | What gets cut if time is short? | Nothing. All of it ships together; no deadline given. | user |

## Main flow
1. User downloads a statement PDF from the bank and drops it in the Inbox.
2. From Transactions or Accounts → **Import**, the picker lists the PDF (labelled PDF) with any CSV/XLSX exports. Or, on the
   PDF itself, Import is the primary action when D12's rule holds, otherwise under More actions.
3. If the PDF is unread, the dialog offers **Read**; when reading finishes (no model), the preview appears.
4. Preview shows the transactions tables, including continuation pages linked by the import ("continued from page N"),
   rows from flagged pages unticked, and each row's page, as-printed date/description/amount, signed amount, and
   New / Already recorded (with source) / Rejected (with reason). Totals in/out for new rows.
5. Account is preselected only on a unique last-four match; otherwise the user chooses one or fills New account.
6. Year (if dates lack one) is a required choice; sign defaults by account type for a single Amount column.
7. **Import** writes everything in one transaction; the summary gives inserted, duplicates (with source), rejected, and
   pages that yielded no rows with reasons. The PDF still offers **Record**.

## Failures and edge cases
- PDF never read → "Read this document first" with a Read button; nothing written.
- Scanned page (no text layer) → reported "scanned page; use Record"; no rows from it, other pages still import.
- Flagged/ambiguous layout page → rows unticked with the issue; only ticked rows import.
- Headerless continuation page with the same column count → linked and ticked automatically; different column count → page reported "no transactions table found".
- Dates without year → import blocked until the year is chosen; impossible date (02/30) → row rejected with reason.
- Day/month order ambiguous across the column → required choice, as for CSV.
- Row with both debit and credit, blank description, unparseable amount → rejected and listed with page and row.
- Same PDF imported twice → 0 inserted, all reported as duplicates.
- PDF already Recorded as a statement awaiting reconciliation → rows are duplicates; message says they are not counted until the statement is reconciled.
- Record after import → statement takes over matching rows; they keep counting; no duplicates.
- Statement re-read after import → rows with import evidence are kept.
- Row previously rejected by the user → reported as "rejected earlier", stays rejected.
- Same PDF into a different account → rows inserted there; the summary names the account.
- PDF recorded as receipt/bill/pay stub, or in Trash → refused, naming the record or "restore from Trash".
- Different currency printed than the account's → rows rejected / import blocked with the reason.
- Over 20,000 rows → whole import refused with the limit named.
- Document replaced, reading redone, or blob corrupted after preview → refused; nothing written.
- Several accounts' last four printed, or none → no preselection.

## Acceptance checks (user's words)
Accepted the interviewer's recommendation:
- Synthetic PDFs that mimic the bank layout (no real statements):
  1. A 3-page checking statement, Date | Description | Withdrawals | Deposits | Balance, headings only on page 1, imports every row with correct signs and never uses Balance.
  2. A card statement with one Amount column (charges positive) and year-less dates like "08/03" imports charges as negatives after choosing the year.
  3. Importing the same PDF twice adds nothing.
  4. Import then Record produces no duplicates.
- Plus one manual run in the browser.

## Non-goals and follow-ups
- Scanned/photographed PDFs in the import (follow-up; would need a "proposed, not counted" import state).
- Moving cross-page table linking into the PDF reader so Record and the document page benefit (follow-up).
- Automatic detection of the statement period to infer the year (follow-up).
- Checking imported rows against printed opening/closing balances (Record does this).
- Changing statement extraction / Record itself.
- Investment, crypto and loan documents; receipts, bills, pay stubs.
- Currency conversion.

## Open questions
- Feasibility: the normal Read step sends scanned pages to the vision model. A Read started from Import must run with
  no model (D11). spec-feature should confirm the reader can do this or define how it stops at scanned pages.
- Exact text patterns for last-four detection (D6/D7), e.g. "ending in", "XXXX", "****", "…": spec-feature to enumerate.

## Repository context
- `specs/account-import-pdf/spec.md`: earlier non-interactive draft (FR-01–FR-28, D1–D7); to be revised from this interview. Not approved (no `approvals/account-import-pdf.json`).
- `src/home_manager/app/static/money_v2.js:77–113`: Import picker; filters to `.csv|.xlsx` after a `limit=200` fetch (the cap issue in D12).
- `src/home_manager/finance/ledger.py:1065–1105`: `table_rows` / `import_transactions`; line 1078 refuses non-CSV/XLSX.
- `src/home_manager/finance/ledger.py:39–43`: `HELD` and `COUNTABLE`; `import` rows count unless rejected.
- `src/home_manager/finance/tabular.py`: CSV mapping, header names, limits, date/sign handling to reuse.
- `src/home_manager/library/migrations/011_finance.sql:11–22`: `accounts.account_type` (needed for D5) and `account_last_four`.
- `src/home_manager/documents/pdf_reader.py`, `pdf_layout.py`, `vision_tables.py`: saved reading with `page.layout.tables` and layout issues.
- `src/home_manager/app/static/library.js:150–227`, `index.html:1128–1151`: `openImport` and `#import-dialog` (account remembered in localStorage).
- `src/home_manager/app/static/records_v2.js:454–463`, `storage.py:555–563`: next-step logic; `ledger_status = imported` currently hides Record.
- `docs/open-work.md:45`, `docs/documents.md:242`: cross-page tables listed as open work.
- `src/home_manager/finance/provenance.py:36–41, 93–98`: provenance reads only `locator.rows` for imports; PDF rows need page/cell evidence.

## Rejected ideas
- Scanned rows as proposals in this release (draft D1): user chose native-only.
- Never preselecting the account: user chose preselect on a unique last-four match.
- Required sign choice with no default: user chose a default by account type.
- Skipping or blocking flagged-layout pages: user chose unticked rows they can tick.
- Strict geometric match before auto-linking continuation tables: user kept "same column count is enough" after being warned.
- Record always primary on PDFs: user chose Import primary on PDFs that have a transactions table and a matching last four.
- Cutting linking or the extras to ship sooner: nothing is cut.
