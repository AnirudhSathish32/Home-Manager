# Test contract: account-import-pdf
Spec sha256: the bundle hash (spec.md + this file) from the user's gate tooling (`gate.py` is not in this repository,
spec U1). It isn't copied here, because writing it into this file would change it.

Every expected value below is taken from `spec.md` and `interview.md`, or worked out by hand from the synthetic fixtures
defined here. None comes from running the current code. Where the spec leaves an outcome undefined, it is listed under
"Gaps in the spec", not invented.

## Conventions for every scenario

- **Environment:** a `tmp_path` library and database. API tests use `create_app(tmp_path / "control", token,
  limits=ScanLimits(stability_seconds=0))` with `TestClient`, as in `tests/test_imports.py:118`. Ledger-level tests use
  `Store(tmp_path / "managed")` + `Ledger(store)`, as in `tests/test_imports.py:157`. Documents are captured through
  the Inbox (`conftest.inbox_scan`, or `manager.start_inbox()`). Synthetic PDFs only: `tests/test_pdf.py` `make_pdf`,
  using positioned-item pages (`{"items": [(x, y, text), …]}`, as in `tests/test_pdf_layout.py:15`). Never a live
  library, `P:\Finances`, `%LOCALAPPDATA%\HomeManager` or a donated corpus.
- **Reading:** fixtures are read by the real reader (`ReceiptService(store).enqueue(doc_id, vision=VisionConfig())` and
  then `run`, as in `tests/test_pdf.py:110`), with no vision model, so every page is `embedded_text`. The only exceptions are
  SC-09, which needs a scanned page and uses the `local_model` stub (`tests/conftest.py:117`) for that page alone, and
  SC-16, which uses a fabricated reading (see "Doubles").
- **Fixture preconditions (P-checks):** before a scenario's first checkpoint, the test asserts the reading has the shape
  the fixture is meant to produce: methods per page, where the transactions heading is (a native table's row 0, or a
  **visual row**: the page's saved words grouped by baseline, FR-08), which pages have no native transactions table,
  and the stated layout issues. `unresolved_columns` alone on a page the import rebuilds doesn't count as flagged
  (FR-09 as amended). A failed P-check is a
  **fixture or reader problem, never a reason to change an expected value**. It is reported as such. As resolved under
  U2 (2026-10-24), the reader builds **no** native table for a headerless page, and none for a headed page with a
  column blank on every row. The P-checks assert that, and the import rebuilds those rows (FR-08 as amended).
- **Network and models (C-net):** an autouse fixture in the new test module replaces `socket.socket.connect`,
  `socket.socket.connect_ex` and `socket.create_connection` with a function that raises for any non-loopback address
  (the `TestClient` transport is in-process and opens no socket). No vision or reasoning model is configured unless the
  scenario says so. Wherever a scenario uses `local_model`, the test asserts `local_model["requests"]` is unchanged by
  every preview and import step.
- **Shared checks:**
  - **C-unchanged:** the row counts of `accounts`, `transactions`, `statements`, `financial_evidence_links`,
    `transaction_imports` and `review_events` are the same before and after, and the sha256 of the preserved blob and of
    every file under the document's saved reading folder is the same.
  - **C-money:** every new `transactions.amount_minor` has SQLite `typeof() = 'integer'`, and its currency is `USD`
    unless stated.
  - **C-evidence:** the original, preserved blob and saved reading files are byte-identical before and after every step
    (spec "Evidence is preserved").
  - **C-ids:** no stored column outside the saved reading holds more than four consecutive digits of the printed
    account number `000123454821`. `accounts.account_last_four` is null or 4 digits (FR-30).
  - **C-refusal (FR-29):** the response is a 4xx with the stated message, the message names the next step, and
    C-unchanged holds. Repeating the same request after removing the cause succeeds.
  - **C-import-id:** import ids and evidence `source_key`s are asserted only as matching `import:[0-9a-f]{32}`.
    Timestamps are asserted as present and ISO-formatted, never by value.
- **Test files (new):**
  - `tests/pdf_import_fixtures.py`: builders for the fixtures below.
  - `tests/test_pdf_imports.py`: ledger and API scenarios.
  - `tests/test_pdf_imports_browser.py`: opt-in browser scenarios (`RUN_BROWSER_TESTS=1`, the `served()` helper and
    Edge channel conventions of `tests/test_transactions_v2_browser.py`).
  - Existing files extended where named.
- **Cleanup:** pytest removes `tmp_path`. No other files are written. Browser tests close their browser and server
  through the `served()` context.

### Doubles

| Component | Real or double | Specification |
|---|---|---|
| PDF reader (native pages) | **Real** | Every fixture except SC-16 is read by `pdf_reader` with `VisionConfig()`. |
| Vision model (scanned page, SC-09 only) | Double: `local_model` | Returns `{"full_text": "SCANNED PAGE TWO\n08/04/2026 SCANNED CAFE 7.00"}`. The test asserts that this text never becomes a row. |
| Record / statement extraction (SC-11, J1) | Double | Preferred: the real `POST /api/documents/{id}/extraction-runs` with `local_model` answering by `json_schema.name` with the statement **S-K** below. Allowed fallback, when the scripted path can't produce an `awaiting` statement deterministically: `manager.ledger.publish_statement(S-K, evidence, "proposed")`, as `tests/test_imports.py:142` does. Which path the test used is written in its docstring. |
| Fault during import (SC-06, SC-17-e) | Double: SQLite trigger | `CREATE TEMP TRIGGER fault BEFORE INSERT ON transactions WHEN NEW.description_raw = '<marker>' BEGIN SELECT RAISE(ABORT, 'injected fault'); END`, created on the connection the import uses (through a test hook on `Store.connection`), or a permanent trigger dropped afterwards. This doesn't depend on how the implementation batches its inserts. |
| Row limit (SC-16) | Double: in-memory reading and a lowered limit | The analyzer gets a `PDFResult` built in memory (41 pages × 500-row tables), which is not saved. The API test lowers the module's row limit with `monkeypatch`. No real reading can reach 20,000 rows (amended 2026-10-24). |
| Clock | Real | No assertion depends on today's date. Year-less fixtures assert that **no** date uses the current year (2026 on the run date) unless the user chose it. For that reason SC-02 chooses 2025. |
| Network | Blocked | C-net. |

### Fixtures

Column x-positions for native tables: 40, 110, 300, 390, 480 (3-column tables use 40, 110, 300). Row y = 700 − 20 × row,
with headings on row 0. Amount cells are as printed below. Every page's table has at least one value in every column, so
the reader can see the column count. Each table has ≥ 2 rows (`PDFTable` minimum).

Fixture rules added from plan review (2026-10-24). They change no expected value:
- **Enough native text.** The reader sends a page with fewer than 40 non-space characters to the vision model
  (`pdf_reader.py`). Every native page therefore also prints a footer line, in words only, below its table: for example
  `FIRST LOCAL BANK statement page one of three`. That is at least 40 characters and is not a table row. A footer with a
  digit followed by a word (`Page 1 of 3`) makes the reader raise `unresolved_columns` even under a complete native
  table, which would flag pages meant to be clean (plan review pass 4).
- **Non-Latin-1 glyphs.** `make_pdf` encodes text as Latin-1, so the SC-05 lines `••••4821` and `…4821` need the
  helper to encode as cp1252 (WinAnsi, where `•` is 0x95 and `…` is 0x85). This is an additive change to the helper.
- **Date order is a choice whenever the column is ambiguous** (FR-06, the same rule as CSV). The rule applies across
  all rows of the selected and linked tables. The dates of X, F, M (k1–k3), V, D-full and D-2y have no day or month
  value above 12, so their tests send `date_format = MM/DD/YYYY`, which is an input, not an expected value. K is
  unambiguous across its linked chain (08/15 and later). R and D-ny are unambiguous (14, 20, 30).

**K: 3-page checking statement.** Page 1, above the table: `FIRST LOCAL BANK`, `Account ending in 4821`,
`Account number 000123454821`, `Statement period 08/01/2026 to 08/31/2026`. Headings on page 1 only:
`Date | Description | Withdrawals | Deposits | Balance`. Opening balance 1,000.00.

| # | Page | Date | Description | Withdrawals | Deposits | Balance | Expected signed `amount_minor` |
|---|---|---|---|---|---|---|---|
| k1 | 1 | 08/03/2026 | COFFEE SHOP | 4.50 | | 995.50 | −450 |
| k2 | 1 | 08/03/2026 | COFFEE SHOP | 4.50 | | 991.00 | −450 |
| k3 | 1 | 08/05/2026 | GROCERY MART | 45.10 | | 945.90 | −4510 |
| k4 | 2 | 08/15/2026 | PAYROLL ACME | | 2,000.00 | 2,945.90 | 200000 |
| k5 | 2 | 08/20/2026 | TRANSFER TO SAVINGS | 500.00 | | 2,445.90 | −50000 |
| k6 | 2 | 08/21/2026 | MONTHLY SERVICE FEE | 5.00 | | 2,440.90 | −500 |
| k7 | 3 | 08/25/2026 | REFUND BOOKSTORE | | 19.99 | 2,460.89 | 1999 |
| k8 | 3 | 08/28/2026 | UTILITY CO | 82.40 | | 2,378.49 | −8240 |
| k9 | 3 | 08/30/2026 | INTEREST PAID | | 0.12 | 2,378.61 | 12 |

Arithmetic: out = 4.50 + 4.50 + 45.10 + 500.00 + 5.00 + 82.40 = 641.50. In = 2,000.00 + 19.99 + 0.12 = 2,020.11.
1,000.00 − 641.50 + 2,020.11 = 2,378.61, which is the last balance. No balance value equals any amount, so a balance used as
an amount would always show. k1 and k2 are same-day, same-amount rows (ordinals 0 and 1).
P-check: 3 `embedded_text` pages. No page has an issue other than `unresolved_columns`; pages 2 and 3 (and page 1 when it is rebuilt) may have that one.
- Page 1 has the transactions heading `Date | Description | Withdrawals | Deposits | Balance`, either as a native
  table's row 0 or as one visual row. k1–k3 print no deposit, so the reader may build no transactions table (in the
  pass-4 probe it built a wrong `Date | Description` table, which FR-08 folds into the rebuilt table). Either form gives the
  same expected values.
- Pages 2 and 3 have no native transactions table. Each has 3 visual rows holding k4–k6 and k7–k9. The reader saves each of those rows as several lines, which doesn't matter (FR-08).

**Kc: CSV of K's rows**, `Date,Description,Amount` with signed amounts (−4.50, −4.50, −45.10, 2,000.00, −500.00, −5.00,
19.99, −82.40, 0.12) and 4-digit dates. It is used only for fingerprint duplicates, so it depends on no
Withdrawals/Deposits mapping.

**S-K: statement double for K.** `statement_type` bank, institution FIRST LOCAL BANK, last_four 4821, USD, period
2026-08-01 to 2026-08-31, opening 100000, closing 237861, transactions k1–k9 (date, amount_minor as above, description as
printed), each with a `line_ids` locator into K's reading.

**R: 2-page card statement.** Page 1, above the table: `SYNTH CARD SERVICES`, `Card number XXXX7700`. Headings on page 1
only: `Date | Description | Amount`. Charges are printed positive, payments and returns negative.

| # | Page | Date | Description | Amount | Into `C` (credit_card, default) | Into `A` (checking, default) |
|---|---|---|---|---|---|---|
| r1 | 1 | 08/03 | BOOKSTORE | 19.99 | −1999 | 1999 |
| r2 | 1 | 08/05 | PAYMENT THANK YOU | -250.00 | 25000 | −25000 |
| r3 | 1 | 08/09 | GAS STATION | 38.20 | −3820 | 3820 |
| r4 | 2 | 08/14 | RESTAURANT | 54.75 | −5475 | 5475 |
| r5 | 2 | 08/20 | RETURN BOOKSTORE | -19.99 | 1999 | −1999 |

Preview totals for ticked New rows: into `C`, out −112.94 USD (19.99 + 38.20 + 54.75) and in 269.99 USD (250.00 + 19.99).
Into `A`, out −269.99 USD and in 112.94 USD.
P-check: 2 `embedded_text` pages. Page 1 has the heading `Date | Description | Amount` (as a native table's row 0 or a visual row) and r1–r3. Page 2 has no native transactions table, and 2 visual rows holding r4–r5.

**Accounts.** `A`: USD checking, FIRST LOCAL BANK, …4821. `C`: USD credit_card, SYNTH CARD SERVICES, …7700. `B`: USD
savings, OTHER BANK, …1111. `L`: USD loan, SYNTH LENDER, …3333. `E`: EUR checking, EURO BANK, …4821.

Other fixtures are defined in the scenario that uses them.

---

## Journey J1 (SC-01, SC-13, SC-14, SC-12): import, import again, rejected row, other account, Record later
Requirement IDs: FR-01, FR-02, FR-04, FR-07, FR-08, FR-10, FR-12, FR-13, FR-16, FR-17, FR-18, FR-20, FR-23, FR-24, FR-30
Environment: API (`TestClient`). C-net is on for every step except step 9, where the `local_model` loopback is allowed.
Nondeterministic components: none in steps 1–8. Step 9 uses the Record double.
Initial state: accounts `A`, `C`, `B`. K is captured and read. 0 transactions, 0 statements, 0 `transaction_imports`.
No model configured.
Actions/checkpoints:
1. **(SC-01, FR-02)** Overwrite the Inbox/Library copy of K with different bytes, **without** a new scan → the document's
   `current_hash` is unchanged. Every later step uses the preserved blob and its reading.
2. **(SC-01, FR-01)** `GET /api/documents?status=ready_for_ledger` → K is listed, and its document type is not changed to a
   table file.
3. **(SC-01, FR-04, FR-08, FR-13)** `POST /api/documents/{K}/transaction-import/preview` with `expected_hash` and no account
   →
   - The tables listed are one transactions table on page 1 (native or rebuilt) and two continuation entries (pages 2
     and 3), all selected. The continuation entries are linked to page 1's table.
   - The preselected account is `A`, with match text `Matched …4821 printed on page 1`.
   - There are 9 rows, in order k1…k9. Each has its source page, as-printed date, description and amount, and these equal
     the reading's text: the cell text for a native row, the words' text for a rebuilt row (FR-05). The signed amounts are as in table K.
   - Every row is New and ticked. Rows k4–k9 carry `continued from page 1`, and so does k4, which is page 2's first row.
   - The totals are out −641.50 USD and in 2,020.11 USD.
   - The Balance cell is never an amount. The issue list is empty: K's pages carry only `unresolved_columns`, which
     is not listed (FR-09 as amended).
   - C-unchanged holds.
4. **(SC-01, FR-23)** `POST …/transaction-imports` with `expected_hash`, `account_id = A` and the preview's reading id
   →
   - The response is `inserted 9, duplicates 0, rejected 0, left out 0`, and the summary names `A`.
   - DB: 9 `transactions` rows in `A`, all with origin `import`, counted by `COUNTABLE`, with the dates 2026-08-03 …
     2026-08-30 and the amounts in table K. C-money holds.
   - DB: 1 `transaction_imports` row. It records the reading id, the 3 tables (page 2 and 3 marked linked to page 1),
     the mapping (date, description, debit = Withdrawals, credit = Deposits; no Balance), year none, sign none
     (Debit/Credit), 9 ticked and 0 unticked, and the counts.
   - DB: 9 evidence links with C-import-id. Each locator holds the document, blob hash, reading id, page, table, row and
     cell or line ids.
   - C-ids holds.
   - Reconciliation ran after (as for CSV).
5. **(SC-01, FR-18, FR-12)** Check the Spending view and the library row.
   - Spending for 2026-08 includes the 6 outflows.
   - `GET /api/documents/{K}` shows that Record is still offered: under OD-3's recommended default the badge is
     `imported` and `rc2Step` still returns Record. This is checked in the browser in SC-20.
   - A second preview after the import shows all 9 rows as `Already recorded from import K.pdf`.
6. **(SC-13, FR-20)** Import K into `A` again with the same choices → `inserted 0, duplicates 9`, and a 2nd
   `transaction_imports` row exists. Transactions are still 9. Evidence links are 18: every row has 2 import links. The
   totals are unchanged.
7. **(SC-14, FR-17)** Reject k8 through the existing transaction review action (`review_status = rejected`). Then preview
   and import K into `A` again →
   - k8 is reported `rejected earlier` and the other 8 are duplicates.
   - k8 keeps `review_status = rejected` and is not counted. Spending for 2026-08 drops by 82.40.
   - Inserted is 0.
8. **(SC-13, FR-20)** Import K into `B`. `B` has no last-four match, so the request must name it →
   - `inserted 9` into `B`, and the summary names `B`.
   - `A`'s 9 rows, and their review state, are unchanged.
9. **(SC-12, FR-18)** Record K into `A` with the Record double S-K →
   - A statement exists for `A`, status `awaiting`.
   - `A`'s 9 rows (including the rejected k8) have `statement_id` set to it. They keep origin `import` and keep their
     review status: 8 counted and k8 rejected.
   - The count of transactions in `A` is still 9: Record created no duplicates.
   - `B`'s rows are not touched: their account differs, so their fingerprints differ.
10. **(FR-18, spec "Errors")** Re-read the statement (extract again with the same double) → `A` still has the same 9 row
    ids. Every row with import evidence is kept.
Expected final state:
- Database:
  - `transactions`: 18 rows, 9 in `A` and 9 in `B`, all origin `import`. 17 are counted, and `A`.k8 is rejected.
  - `transaction_imports`: 4 rows (steps 4, 6, 7, 8).
  - `statements`: 1 row, for `A`.
  - `accounts`: 3 rows. C-ids and C-money hold.
- Filesystem: C-evidence.
- UI: covered in SC-20 and SC-22.
Failure/retry/restart variants:
- J1-a (restart): after step 4, close and reopen `Manager` on the same folders and repeat step 6 → the same result.
  Nothing from step 4 is lost or doubled.
- J1-b (Kc first, i.e. SC-10 in this order): see SC-10.
Evidence: `pytest tests/test_pdf_imports.py -k journey_j1`
Cleanup: tmp_path.

## SC-02: card statement with dates printed without a year
Requirement IDs: FR-06, FR-07, FR-15
Initial state: account `C`. R is read.
Actions/checkpoints:
1. Preview with `account_id = C`, no year →
   - Every row shows its as-printed date, and the year is reported as a required choice: `Choose the year` (in the
     dialog, Import is disabled).
   - The sign default is `positive is money out` (credit_card), shown as the selected option.
   - Signed amounts follow the `C` column. Totals are out −112.94 USD and in 269.99 USD.
2. Import without a year → refused naming the year choice (C-refusal). 0 written.
3. Preview, then import, with year 2025 →
   - `inserted 5`, posted dates 2025-08-03, 2025-08-05, 2025-08-09, 2025-08-14, 2025-08-20.
   - Amounts −1999, 25000, −3820, −5475, 1999.
   - No posted date in 2026.
Expected final state: DB has 5 transactions in `C`, all origin `import` and counted, and 1 `transaction_imports` row with
year 2025 and sign `positive_is_outflow`. C-money holds.
Evidence: `pytest tests/test_pdf_imports.py -k sc02`

## SC-03: the sign default follows the chosen account
Requirement IDs: FR-07, FR-15
Initial state: accounts `A`, `C`, `L`. R is read. Year 2025 is chosen in every preview.
Actions/checkpoints:
1. Preview with `C` → default `positive is money out`. Amounts and totals as in the `C` column.
2. Preview with `A` → default `positive is money in`. Amounts and totals as in the `A` column (out −269.99 USD, in 112.94
   USD).
3. Preview with `A` and sign `positive is money out` → the `C` column again (the choice flips them).
4. Preview with `L` → no default, sign reported as a required choice. Importing into `L` without a sign → refused
   (C-refusal). With sign `positive is money out` → it imports, with the `C` column's amounts.
Expected final state: only step 4's import is written (5 rows in `L`).
Variant 3-a: a `savings` account behaves as `checking`. An `other` or `brokerage` account behaves as `loan`.
Evidence: `pytest tests/test_pdf_imports.py -k sc03`

## SC-04: preview writes nothing and repeats exactly
Requirement IDs: FR-05, FR-12
Initial state: an empty ledger with no accounts. K is read.
Actions/checkpoints:
1. Preview three times with the same body → all three response bodies are identical, apart from any field documented as
   a per-request id.
2. Check the rows → all 9 are New, and there is no preselection (no account exists).
3. C-unchanged across the three previews, including `accounts` (the preview creates no account).
Evidence: `pytest tests/test_pdf_imports.py -k sc04`

## SC-05: account preselection only on a unique, same-currency last-four match
Requirement IDs: FR-13
Initial state: accounts `A` (USD …4821) and `E` (EUR …4821). K is read. Fixture **K2**: K's page 1 with an added line
`Payment to card XXXX7700`, so the text prints both 4821 and 7700. Account `C` exists for K2's case.
Actions/checkpoints:
1. Preview K → `A` is preselected (`E`'s currency differs), with match text `Matched …4821 printed on page 1`.
2. Preview K2 with accounts `A`, `E`, `C` → nothing is preselected (two matching accounts), and an account choice is
   required.
3. Fixture **K0** (K with no last four printed and no account number line) → nothing is preselected.
4. `POST …/transaction-imports` for K2 without `account_id` → 400 `Choose the account these transactions belong to.`
   C-unchanged holds.
5. Pattern table. One-page fixtures with a 2-row table plus one line each, accounts `A` and `C` → each of these lines
   preselects `A`:
   - `ending in 4821`
   - `ending 4821`
   - `XXXX4821`
   - `xxxxxxxx4821`
   - `****4821`
   - `••••4821`
   - `*4821`
   - `…4821`

   These lines preselect nothing: `Ref 4821` and `4821` alone.
Variant 5-a: the remembered CSV account (`home-manager-import-account` in localStorage) is set to `C`. Opening the PDF
dialog for K still preselects `A`, and for K0 preselects nothing. This is checked in the browser in SC-23.
Evidence: `pytest tests/test_pdf_imports.py -k sc05`

## SC-06: a new account is created only together with a successful import
Requirement IDs: FR-14, FR-23, FR-30
Initial state: no accounts. R is read.
Actions/checkpoints:
1. Preview with no account → no preselection, and the new-account last four is prefilled `7700` (exactly one distinct
   NNNN).
2. Install the fault trigger on marker `RETURN BOOKSTORE` (r5, the last row). Import with year 2025 and a new account
   (institution `Bank`, `credit_card`, USD, name `Synth card`, last four `7700`) → the request fails, with no raw traceback.
   C-unchanged holds: 0 accounts, 0 transactions, 0 evidence links, 0 imports.
3. Remove the trigger and send the same request → `inserted 5`.
   - DB: 1 account, `credit_card`, `account_last_four = '7700'`, holding the 5 rows with the `C` column's amounts.
   - DB: 1 `transaction_imports` row.
4. A new-account request with last four `123456` → refused, as for CSV's 422 (`tests/test_imports.py:131`).
   C-unchanged holds.
Variant 6-a: K2 (two distinct NNNN) → the last four is not prefilled.
Evidence: `pytest tests/test_pdf_imports.py -k sc06`

## SC-07: cross-page linking, rebuilt rows and pages without a transactions table
Requirement IDs: FR-04, FR-08, FR-10 (FR-08 as amended 2026-10-24)
Fixture **X** (3 pages):
- Page 1 has two tables.
  - The first is a summary table `Summary | Amount`, with rows `Purchases | 100.00` and `Payments | 50.00`. It has no
    date heading, so it is not a transactions table.
  - The second is a 5-column transactions table like K's, with a heading and 2 rows: 09/01/2026 A1 10.00 out (in
    Withdrawals), and 09/02/2026 A2 20.00 in (in Deposits). Every column holds a value, so the reader builds a native
    table.
- Page 2 has no headings, and 2 lines at K's column positions: 09/03/2026 B1 1.00 out, and 09/04/2026 B2 2.00 in.
- Page 3 has a headed 3-column table `Fee summary | Count | Total`, with rows `Monthly fee | 1 | 5.00` and `Wire fee | 2
  | 30.00`. It has no date heading, and no line on it has a date.

Account `A` exists. `date_format = MM/DD/YYYY` is sent (fixture rule).
P-check: page 1 has a native 5-column transactions table. Page 2 has no native table. Page 3 has a native 3-column table
whose row 0 is `Fee summary | Count | Total`.
Actions/checkpoints:
1. Preview →
   - The summary table and the fee summary are listed as `not a transactions table`. They are not selectable and
     contribute no rows.
   - Page 1's transactions table is selected.
   - Page 2's 2 rows are rebuilt with page 1's columns, ticked, and labelled `continued from page 1`. B1, page 2's first
     line, is included.
   - Page 3 is reported `Page 3: no transactions table found`.
   - There are 4 rows. Totals: out −11.00 USD, in 22.00 USD.
2. Accounting identity (FR-10) → imported + duplicates + rejected + left out = 4 rows seen. Every page (1, 2, 3)
   appears either as a row source or in the issue list. The footer lines are not rows and are not counted.
3. Import into `A` → `inserted 4`.

Variants:
- **7-a (D10, accepted risk, as amended):** page 3 instead has a title line `Payment schedule` and, with no headings,
  2 lines at K's column positions: 10/01/2026 `Scheduled payment` with 25.00 under Withdrawals, and 11/01/2026
  `Scheduled payment` with 25.00 under Withdrawals. Without a description the rows would be rejected (FR-10, pass 5).
  They are rebuilt, ticked, labelled `continued from page 1`, and their −50.00 is in the out total. This asserts the
  accepted behavior. It is not a defect. The title line has no date, so it is not a row.
- **7-b:** a transactions table on page 2 with its own headings sits between page 1 and a headerless page 3 → page 3's
  rows are labelled `continued from page 2`, not page 1.
- **7-c (a blank column on every row, new 2026-10-24):** page 1's transactions table prints only withdrawals (A1 10.00,
  A2 20.00), so the reader builds no transactions table for it. P-check: page 1 has no native transactions table, and
  has the heading as a visual row. Preview → page 1 is listed as a rebuilt table with A1 −10.00 and A2 −20.00. Page 2 continues it as in
  step 1. There are 4 rows, out −31.00 USD (10.00 + 20.00 + 1.00), in 2.00 USD.
- **7-d (a word straddling two columns):** on page 2, B2's amount is placed so that its horizontal centre falls on the
  midpoint between Withdrawals and Deposits → B2 is reported as a rejected row, with page 2 and the reason that its
  amount doesn't fit a column. B1 imports.
- **7-e (text in an amount column, plan review pass 4):** on page 2, B1's description is `B1 REF 12345`, placed so that
  `12345` falls in the Withdrawals span beside `1.00` → B1 is rejected (two amounts in one amount column), with page 2
  and that reason. B2 imports. Nothing is joined or guessed.

Evidence: `pytest tests/test_pdf_imports.py -k sc07`

## SC-08: rows from a flagged page start unticked
Requirement IDs: FR-09, FR-10
Fixture **F** (2 pages):
- Page 1 has a 3-column table (`Date | Description | Amount`), a heading and 2 rows: 07/01/2026 F1 10.00, and
  07/02/2026 F2 20.00.
- Page 2 has a headerless 3-column table with 4 rows (07/03/2026 F3 1.00, F4 2.00, F5 3.00 and F6 4.00, on 07/03–07/06).
  It also has one extra glyph placed outside the page's CropBox (the `crop` page setting of `make_pdf`). This makes the
  real reader raise the `glyph_outside_page` layout issue and a `pdf_layout_review` page issue.

Account `A` exists. The sign is the checking default (positive is money in).
P-check: page 2 carries a `pdf_layout_review` issue. If this trigger does not raise it, use another real reader trigger
(an unmappable glyph through `unicode_map`) and record which one was used. Do not inject the issue into a saved reading.
Actions/checkpoints:
1. Preview →
   - F1 and F2 are ticked.
   - F3–F6 are **unticked**. Each shows page 2's issue message (`Page 2 PDF layout needs review: …`), the parsed date and
     the signed amount.
   - The totals count only the ticked rows: in 30.00 USD.
2. Import with F3 and F5 ticked →
   - `inserted 4` (F1, F2, F3, F5), all counted, and `left out by you 2`.
   - The `transaction_imports` row lists F4 and F6 as unticked.
3. Check the database → F4 and F6 are not in `transactions`.
Variant 8-a (FR-09 as amended, plan review pass 5): fixture **Fn** is a 1-page native transactions table (K's
headings, rows A1 and A2 from X, every column filled) with the footer `FIRST LOCAL BANK - Page 1 of 3`.
P-check: there is a native 5-column table, and `layout.issues == ["unresolved_columns"]`. Preview → both rows are
ticked, with no issue message and an empty issue list.
Evidence: `pytest tests/test_pdf_imports.py -k sc08`

## SC-09: a scanned page is reported and contributes nothing
Requirement IDs: FR-03, FR-10
Fixture **M**: page 1 is K's page 1 (heading + k1–k3). Page 2 is scanned (`None` in `make_pdf`). It is read once with the
`local_model` vision double, then `local_model` is left running so that its request count can be checked.
Account `A` exists.
Actions/checkpoints:
1. P-check → the page methods are `["embedded_text", "vision_model"]`.
2. Preview →
   - k1–k3 are the only rows.
   - The issue list contains `Page 2 is a scanned page; no rows imported. Use Record for scanned statements.`
   - `SCANNED CAFE` is nowhere in the rows.
   - `local_model["requests"]` is unchanged.
3. Import → `inserted 3`. No evidence locator names page 2. `local_model["requests"]` is unchanged.
Variant 9-a: an all-scanned 1-page PDF (read with the double) → the preview has 0 rows and that message. Importing writes
nothing beyond what the spec requires. Whether an empty import writes a `transaction_imports` row is G6.
Evidence: `pytest tests/test_pdf_imports.py -k sc09`

## SC-10: a row already imported from CSV
Requirement IDs: FR-16, FR-17
Initial state: account `A`. Kc is captured and imported into `A` (9 rows). K is read.
Actions/checkpoints:
1. Preview K with `A` → all 9 rows are `Already recorded from import Kc.csv`, and the New totals are 0.
2. Import → `inserted 0, duplicates 9`.
   - Transactions are 9, still origin `import`, and their category, tags, review status and `statement_id` are unchanged
     (snapshot before and after).
   - There are 9 new evidence links pointing to K's blob.
   - The Spending totals for 2026-08 are unchanged.
Variant 10-a (manual entry; FR-17 as amended 2026-10-24): a manual transaction 2026-08-05 −45.10 in `A` exists before
K is first imported.
- In the preview, k3 is New and labelled `replaces a manual entry`.
- The import inserts 9.
- After the import's reconciliation pass:
  - the manual row has `review_status = rejected` and `replaced_by` = k3's id;
  - k3 is counted;
  - Spending for 2026-08 counts 45.10 once.
Evidence: `pytest tests/test_pdf_imports.py -k sc10`

## SC-11: a statement already Recorded and awaiting reconciliation
Requirement IDs: FR-16, FR-17, FR-18
Initial state: account `A`. K is read and Recorded into `A` through the Record double S-K.
P-check: the statement status is `awaiting`, the 9 rows are origin `extraction`, and none is counted (`HELD`).
Actions/checkpoints:
1. Preview K with `A` → every row says `Already recorded from this statement; not counted until you reconcile it.`
2. Import → `inserted 0, duplicates 9`.
   - The 9 rows keep origin `extraction`, their review status and `statement_id`, and are still not counted.
   - 1 `transaction_imports` row and 9 import evidence links are added.
3. Check what the page offers → Record is still offered and Import is still offered (FR-18: either order).
Evidence: `pytest tests/test_pdf_imports.py -k sc11`

## SC-15: documents that cannot be imported
Requirement IDs: FR-19, FR-29
Initial state: accounts `A`. Four read PDFs:
- **Pr**: recorded as a receipt.
- **Pb**: recorded as a bill.
- **Pp**: recorded as a pay stub.
- **Pt**: K moved to Trash.
- **Ps**: K Recorded as a statement in `A`, then reconciled (verified).

Each PDF has K's transactions table, so only the record decides.
Actions/checkpoints:
1. Preview Pr → refused `This PDF is recorded as a receipt.` (C-refusal). Pb and Pp are the same, naming bill and pay stub.
2. Preview and import Pt → refused `Restore the document from Trash before importing it.` Restore it, then preview →
   succeeds.
3. Preview Ps → succeeds, with all 9 rows `Already recorded from this statement` (Ps is the statement's own PDF). Importing inserts 0.
Evidence: `pytest tests/test_pdf_imports.py -k sc15`

## SC-16: limits refuse the whole import
Requirement IDs: FR-21, FR-29
No real reading can hold 20,000 rows: the reader caps evidence at 24 MiB and a document at 250,000 characters (spec FR-21,
as amended 2026-10-24). The limit is tested at two levels.
Doubles: an in-memory `PDFResult` built in the test (not saved) for the analyzer. For the API, a real reading of a
1-page fixture, with the module's row limit lowered by `monkeypatch` to 3.
Actions/checkpoints:
1. Analyzer with an in-memory reading of 20,001 data rows → raises with text containing `exceeds 20,000 data rows`.
2. Analyzer with 20,000 rows → no limit error, and `counts.seen` is 20,000.
3. API, with the limit lowered to 3, on a fixture with 4 data rows → preview and import are both refused, naming the row
   limit. C-unchanged holds. On a fixture with 3 rows → it imports 3.
4. A real reading whose one Description cell has 2,001 characters → refused, naming the 2,000-character cell limit. No
   rows are inserted.
5. Analyzer with an in-memory reading producing 250 rejected rows → the issue list has exactly 200 entries, and the
   counts still report 250 rejected.
Evidence: `pytest tests/test_pdf_imports.py -k sc16`

## SC-17: integrity checks before any write
Requirement IDs: FR-22, FR-23, FR-29
Initial state: account `A`. K is read. Each sub-case starts from a fresh `tmp_path` and a successful preview whose reading
id is kept.
Actions/checkpoints (import after each change, sending the preview's `expected_hash` and reading id):
- (a) Overwrite the preserved blob with `b"corrupt"` → `Preserved evidence failed its integrity check. Nothing was
  imported.`
- (b) Change one amount's character in the saved reading's `result.json` → the same message.
- (c) A changed K is captured as a new version (new `current_hash`). Import with the old `expected_hash` → refused, with
  no write (the message is G3).
- (d) Read the document again so that a new reading id exists for the same hash → `This document was read again since
  the preview; preview again.` A new preview and import then succeed.
- (e) Atomicity: install the fault trigger on marker `TRANSFER TO SAVINGS` (k5, after k1–k4 have been sent), then
  import → 0 transactions, 0 evidence links and 0 imports. Remove the trigger and retry → `inserted 9`.

Expected final state: for each of (a)–(e) before its retry, C-unchanged holds. C-evidence holds except for the file the
test itself tampered with.
Evidence: `pytest tests/test_pdf_imports.py -k sc17`

## SC-18: a different currency blocks the import
Requirement IDs: FR-11, FR-29
Fixture **Keur**: K with every amount printed with `EUR` (for example `4.50 EUR`) and `Currency: EUR` printed on page 1.
Account `A` (USD).
Actions/checkpoints:
1. Preview with `A` → the import is blocked, and the reason names EUR against the account's USD.
2. Import → refused with the reason. C-unchanged holds.
Variant 18-a: K with only row k3 printed `45.10 EUR` and no document-level currency → k3 is rejected (`currency
mismatch`) and the 8 other rows import.
Evidence: `pytest tests/test_pdf_imports.py -k sc18`

## SC-24 (new): exact dates
Requirement IDs: FR-06
One-page fixtures with a `Date | Description | Amount` table and account `A`:
- **D-ny**: `08/03 X 1.00`, `12/30 Y 2.00`, `01/02 Z 3.00`. The import is refused until a year is chosen. With first year
  2025 → 2025-08-03, 2025-12-30, 2026-01-02.
- **D-bad**: `02/27/2026 P 1.00`, `02/30/2026 Q 2.00` → Q is rejected with a reason that names the date. P imports as
  2026-02-27.
- **D-full**: `08/03/2026 W 1.00`, `08/04/2026 V 2.00` → imports with no year choice.
- **D-amb**: `03/08/2026 G 1.00`, `04/09/2026 H 2.00` → the day/month order is a required choice. With `DD/MM/YYYY` →
  2026-08-03 and 2026-09-04. With `MM/DD/YYYY` → 2026-03-08 and 2026-04-09.
- **D-2y**: `08/03/26 T 1.00`, `08/04/26 U 2.00` → the import is refused until a year is chosen. What a chosen year does
  to a printed two-digit year is G4, and is not asserted.
Evidence: `pytest tests/test_pdf_imports.py -k sc24`

## SC-25 (new): rejected rows are listed with page, row and reason
Requirement IDs: FR-07, FR-10, FR-30
Fixture **V**: one page with a `Date | Description | Withdrawals | Deposits | Balance` table and account `A`:

| # | Date | Description | Withdrawals | Deposits | Balance | Expected |
|---|---|---|---|---|---|---|
| v1 | 08/01/2026 | GOOD | 10.00 | | 990.00 | imported −1000 |
| v2 | 08/02/2026 | BOTH | 5.00 | 5.00 | 990.00 | rejected: both debit and credit |
| v3 | 08/03/2026 | *(blank)* | 1.00 | | 989.00 | rejected: blank description |
| v4 | 08/04/2026 | BAD AMOUNT | 1.2.3 | | 989.00 | rejected: unparseable amount |
| v5 | 08/05/2026 | 480-char `D…` description | 2.00 | | 987.00 | imported −200, description stored exactly as printed |

Actions/checkpoints:
1. Preview → v2–v4 are listed as Rejected, each with page 1, its row number and its reason. Counts are 2 New and 3
   rejected. Identity: 2 + 0 + 3 + 0 = 5.
2. Import → `inserted 2, rejected 3`. No Balance value appears as an amount anywhere.
Evidence: `pytest tests/test_pdf_imports.py -k sc25`

## SC-26 (new): CSV/XLSX import and PDF status filters are unchanged
Requirement IDs: FR-01
Actions/checkpoints:
1. `pytest tests/test_imports.py tests/test_formats.py tests/test_tabular.py` pass, with no edits to their expected
   values.
2. A read, unrecorded K is in `status=ready_for_ledger`. An unread PDF is in `status=needs_text`, the same as before the
   feature. `core/formats.py` still routes `.pdf` as a document, not a table.
3. Import Kc with the CSV dialog's remembered account → behaves as today (FR-13 is PDF only).
Evidence: `pytest tests/test_pdf_imports.py -k sc26` and the three suites.

---

## Browser scenarios (`tests/test_pdf_imports_browser.py`, opt-in)

Entry points, taken from the UI source:
- **Transactions → Import an export**: `#tx2-import`, or the empty-state button. Both call `importPicker`
  (`transactions_v2.js:183, 361`).
- **Accounts → Import an export**, and the per-account import buttons (`accounts_v2.js:25–33, 61`).
- The picker is the `#money2-import` dialog (`money_v2.js:78–113`). It opens the import dialog (`openImport`,
  `#import-dialog`, `library.js:150–227`).
- **Documents library row**: the next-step link (`rc2Step`, `records_v2.js:455–470`) and the row's More actions menu
  (`rc2Menu`).
- **Document page**: the next-step area (`doc2Steps`, `document_v2.js:273–300`), with buttons `Read document` and
  `Record it`.

Steps are written in user terms. Selectors are the implementer's.

## SC-19: the Import picker lists PDFs
Requirement IDs: FR-25
Initial state: 250 read, unrecorded PDFs, each with K's table and a distinct description, captured **before** the CSV.
Then 1 CSV (Kc), 1 unread native PDF (K, not read), and 1 read PDF with text only and no table.
Actions/checkpoints:
1. Open Transactions → Import an export → the picker lists Kc, labelled CSV, and the 250 table PDFs, each labelled
   `PDF`. The unread and table-less PDFs are not listed. The copy mentions PDF.
2. Close it. Open Accounts → Import an export → the same list. Do the same from one per-account button.
3. With an empty library → the empty state names PDF, CSV and XLSX.
API twin: the endpoint or query the picker uses returns Kc even though 250 PDFs were added before it. The browser test
checks that Kc is visible.
Evidence: `RUN_BROWSER_TESTS=1 pytest tests/test_pdf_imports_browser.py -k sc19`

## SC-20: the primary action on library rows and document pages
Requirement IDs: FR-18, FR-26
Initial state: account `A`.
- K: read, and matches `A`.
- **Kn**: read, with K's table but no last four.
- **Ku**: an unread PDF.
- Kc: a CSV.
- **Kr**: K's table, recorded as a receipt.
Actions/checkpoints:
1. Documents library:
   - K's next step is **Import**. Its More actions menu has Record.
   - Kn's next step is **Record**, and More actions has Import transactions.
   - Ku's next step is **Read**.
   - Kc's next step is **Import**.
   - Kr shows no Import action.
2. Document pages:
   - On K, Import transactions is the primary button and Record is beside it.
   - On Kn, `Record it` is primary and an Import transactions button is beside it.
   - On Ku, `Read document` is primary.
3. Import K into `A` from its row, then reload → K's row and page still offer Record (FR-18). Under OD-3, the badge
   shows `imported`.
Evidence: `RUN_BROWSER_TESTS=1 pytest tests/test_pdf_imports_browser.py -k sc20`

## SC-21: Import on an unread PDF
Requirement IDs: FR-27
Initial state: account `A`. Ku is a fully native copy of K that has not been read. No model is configured.
Actions/checkpoints:
1. From Ku's More actions, choose Import transactions → the dialog says `Read this document first` and shows a **Read**
   button. C-unchanged holds.
2. Choose Read, and wait for the reading job → the same dialog, without being reopened, shows K's preview (9 rows, `A`
   preselected). Up to this point C-unchanged holds for the ledger tables, and a new reading exists.
3. Close the dialog without importing → 0 transactions.
Conditional: this follows OD-1's recommended option (a). If OD-1 is decided differently, the Read in step 2 changes and
this scenario must be revised before approval.
Variant 21-a: Ku is mixed (one scanned page) and no model is configured → the dialog shows today's `Configure a local
vision model …` message. Nothing is written (OD-1 (a)).
Evidence: `RUN_BROWSER_TESTS=1 pytest tests/test_pdf_imports_browser.py -k sc21`

## SC-22: where a PDF-imported row came from
Requirement IDs: FR-24
Initial state: J1 through step 4 (K imported into `A`).
Actions/checkpoints:
1. `GET /api/provenance/transaction/{k5}` → names file K.pdf, page 2, the rebuilt table, its row, and k5's line ids
   (every saved line its words fall in) and word ids (a rebuilt row has no native cells). It says `continued from page 1`. It is not only `{"rows": [n]}`.
2. `GET /api/provenance/transaction/{k1}` → page 1, with no `continued from` label.
3. Browser: open k5's source → `Imported from K.pdf, page 2` and `continued from page 1`. Its link opens the page-2
   preview with k5's lines highlighted. The entry point of a transaction's source panel is G5.
Evidence: `pytest tests/test_pdf_imports.py -k sc22` (API) and `RUN_BROWSER_TESTS=1 pytest
tests/test_pdf_imports_browser.py -k sc22`

## SC-23: the PDF dialog by keyboard and screen reader
Requirement IDs: FR-13, FR-15, FR-28
Initial state: accounts `A`, `C`, `L`. K and R are read. localStorage `home-manager-import-account` is set to `C`.
Actions/checkpoints (keyboard only, with no mouse calls after `goto`):
1. Transactions → Import an export → choose K → the dialog opens in PDF mode.
   - The table list, ticks and page labels are shown.
   - The worksheet and column-mapping controls are hidden.
   - `A` is preselected with `Matched …4821 printed on page 1`, not the remembered `C` (SC-05 5-a).
   - Focus is inside the dialog.
2. Tab through the controls → each one is reachable: the table checkboxes, the row ticks, the account select, the
   new-account fields and Import.
3. Import → the summary is announced in the dialog's live region (`aria-live`).
4. Close the dialog → focus returns to the opener.
5. Reopen with R. Choose `C` → the sign default is `positive is money out`, and Import is disabled until a year is
   chosen. Choose year 2025, then switch to `A` → the sign default and the totals flip (out −269.99, in 112.94). Switch
   to `L` → Import is disabled until a sign is chosen.
6. Throughout, there are no `pageerror` events and no horizontal overflow (`NO_OVERFLOW`).
Evidence: `RUN_BROWSER_TESTS=1 pytest tests/test_pdf_imports_browser.py -k sc23`

### Manual run (interview "Acceptance checks")
One manual browser pass on the isolated test instance (`agent-testing` skill, synthetic data): import K and R, re-import
K, then Record K. Screenshots go under the instance's evidence folder. This supplements the automated tests and does not
replace them.

---

## Traceability

| FR | Scenarios | Test file / command |
|---|---|---|
| FR-01 | J1 steps 2, 5; SC-26 | `tests/test_pdf_imports.py -k "journey_j1 or sc26"`, `tests/test_imports.py`, `tests/test_formats.py`, `tests/test_tabular.py` |
| FR-02 | J1 step 1, C-net throughout | `tests/test_pdf_imports.py -k journey_j1` |
| FR-03 | SC-09 | `tests/test_pdf_imports.py -k sc09` |
| FR-04 | J1 step 3; SC-07 | `tests/test_pdf_imports.py -k "journey_j1 or sc07"` |
| FR-05 | SC-04; J1 step 3 | `tests/test_pdf_imports.py -k sc04` |
| FR-06 | SC-02; SC-24 | `tests/test_pdf_imports.py -k "sc02 or sc24"` |
| FR-07 | J1 (Debit/Credit); SC-02; SC-03; SC-25 | `tests/test_pdf_imports.py -k "journey_j1 or sc02 or sc03 or sc25"` |
| FR-08 | J1 step 3; SC-07 (7-a to 7-e) | `tests/test_pdf_imports.py -k "journey_j1 or sc07"` |
| FR-09 | SC-08 | `tests/test_pdf_imports.py -k sc08` |
| FR-10 | SC-07; SC-08; SC-09; SC-25 | `tests/test_pdf_imports.py -k "sc07 or sc08 or sc09 or sc25"` |
| FR-11 | SC-18 | `tests/test_pdf_imports.py -k sc18` |
| FR-12 | SC-04; J1 steps 4–5 | `tests/test_pdf_imports.py -k "sc04 or journey_j1"` |
| FR-13 | J1 step 3; SC-05; SC-23 | `tests/test_pdf_imports.py -k sc05`, browser `-k sc23` |
| FR-14 | SC-06 | `tests/test_pdf_imports.py -k sc06` |
| FR-15 | SC-03; SC-23 step 5 | `tests/test_pdf_imports.py -k sc03`, browser `-k sc23` |
| FR-16 | SC-10; SC-11; J1 steps 6, 9 | `tests/test_pdf_imports.py -k "sc10 or sc11 or journey_j1"` |
| FR-17 | SC-10 (10-a); SC-11; J1 step 7 (SC-14) | same |
| FR-18 | J1 steps 5, 9, 10 (SC-12); SC-11; SC-20 | `tests/test_pdf_imports.py -k "journey_j1 or sc11"`, browser `-k sc20` |
| FR-19 | SC-15 | `tests/test_pdf_imports.py -k sc15` |
| FR-20 | J1 steps 6, 8 (SC-13) | `tests/test_pdf_imports.py -k journey_j1` |
| FR-21 | SC-16 | `tests/test_pdf_imports.py -k sc16` |
| FR-22 | SC-17 (a–d) | `tests/test_pdf_imports.py -k sc17` |
| FR-23 | SC-06; SC-17 (e); J1 step 4 | `tests/test_pdf_imports.py -k "sc06 or sc17 or journey_j1"` |
| FR-24 | SC-22; J1 step 4 (locators) | `tests/test_pdf_imports.py -k sc22`, browser `-k sc22` |
| FR-25 | SC-19 | browser `-k sc19` |
| FR-26 | SC-20 | browser `-k sc20` |
| FR-27 | SC-21 | browser `-k sc21` |
| FR-28 | SC-23 | browser `-k sc23` |
| FR-29 | C-refusal in SC-02, SC-03, SC-05, SC-06, SC-15, SC-16, SC-17, SC-18 | the commands above |
| FR-30 | C-net and C-ids throughout; SC-06; SC-25 (v5) | `tests/test_pdf_imports.py` |

| Spec SC | Where |
|---|---|
| SC-01 | J1 steps 1–5 |
| SC-02 – SC-11 | the sections of the same ID |
| SC-12 | J1 steps 9–10 |
| SC-13 | J1 steps 6, 8 |
| SC-14 | J1 step 7 |
| SC-15 – SC-23 | the sections of the same ID |
| SC-24 – SC-26 | new, added to the spec's table |

Targeted run:
```
python -m pytest tests/test_pdf_imports.py tests/test_imports.py tests/test_formats.py tests/test_tabular.py \
  tests/test_pdf.py tests/test_pdf_layout.py tests/test_provenance.py -q
RUN_BROWSER_TESTS=1 python -m pytest tests/test_pdf_imports_browser.py tests/test_transactions_v2_browser.py \
  tests/test_records_v2_browser.py tests/test_document_v2_browser.py -q
```

## Gaps in the spec (flagged, not invented)

- **G1 (U2, FR-08): resolved 2026-10-24.** The reader builds no table for headerless pages. FR-08 now rebuilds those
  rows in the import (SC-07 and its variants 7-c, 7-d and 7-e).
- **G2 (FR-08): resolved by the amended FR-08.** The label names the page of the heading, and a new transactions table
  ends the chain (7-b).
- **G3 (FR-22).** No message is named for "document replaced" (SC-17 c). The contract asserts only a refusal with no
  write.
- **G4 (FR-06).** Two-digit years: it is not defined what the chosen year does with a printed `26` (whether it replaces
  it, checks it, or supplies the century). Only "blocked until chosen" is asserted.
- **G5 (FR-24).** The Transactions page has no transaction source panel today (`transactions_v2.js` has no
  provenance call; only `review_v2.js` and `document_v2.js` call `/api/provenance`). The UI entry point for SC-22's
  browser step must be named by the plan.
- **G6 (FR-03, FR-20).** It is not stated whether an import that yields 0 rows (all scanned, or all left out) is refused
  or writes a `transaction_imports` record.
- **Resolved 2026-10-24 from plan review:** the FR-17 manual-entry case (now "replaces a manual entry"), the SC-16 double, the fixture text minimum, the cp1252 glyphs, date-order inputs, and SC-15 Ps's message.
- **G7 (FR-30).** It is not defined whether a description over 500 characters is truncated or rejected. Only ≤ 500 is
  asserted (SC-25 v5).
- **G8 (FR-15).** "FR-13's preview totals" reads as a typo for FR-05's totals. The contract tests FR-05's totals.
- **G9 (statement status).** Whether Record followed by a reconciliation pass leaves S-K `awaiting` (its balances add up)
  isn't stated. SC-11 makes `awaiting` a precondition and allows the `publish_statement(…, "proposed")` fallback.
- **Open decisions affect the contract:** OD-1 (SC-21 assumes option a), OD-2 (the Balance heading list: K uses
  `Balance`, which is in the recommended list), OD-3 (SC-20 step 3 assumes the badge stays `imported`). Domain risks R2–R5
  are not accepted requirements, so no scenario asserts them. R5 in particular (a new account colliding with
  `accounts_identity`) has no defined outcome.
