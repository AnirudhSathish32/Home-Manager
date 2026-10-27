# Test contract: pdf-table-engine
Spec sha256: the bundle hash (spec.md + this file) from `~/.agent-harness/gate.py hash --feature pdf-table-engine --stage
spec`. It isn't copied here, because writing it in would change it.

Every expected value comes from `spec.md`, or is worked out by hand from the synthetic fixtures below. None comes from
running the current code or the engine. Where the spec leaves an outcome open, it is listed under "Gaps", not invented.
This contract covers phase 1 only (FR-01 – FR-34). FR-40 – FR-44 get their own contracts (OD-5).

## Conventions for every scenario
- **Environment.** A `tmp_path` library and database only. Never `P:\Finances`, `%LOCALAPPDATA%\HomeManager` or
  `P:\EvalCorpus`. Record tests go through the real extraction service, as `tests/test_statement_rebuild.py` and
  `tests/test_statement_forms.py` do: capture into the Inbox, read with the real PDF reader (`VisionConfig()`, no vision
  model), then `ExtractionService.run` with the `local_model` stub answering by `json_schema.name`
  (`tests/model_server.py` `by_schema`). PDF import tests use `create_app(…)` with `TestClient` and
  `POST /api/documents/{id}/transaction-import/preview` and `…/transaction-imports`. Browser tests are opt-in
  (`RUN_BROWSER_TESTS=1`, the `served()` helper and Edge channel of `tests/test_transactions_v2_browser.py`).
- **Engine-level tests** call the engine on a saved reading (the `PDFResult` the real reader produced from the fixture),
  with no store and no model. Engine-level tests stay independent of one another.
- **Synthetic PDFs only:** `tests/test_pdf.py` `make_pdf` with positioned items, 10 pt Helvetica unless stated. Every
  native page also prints a words-only footer of at least 40 characters with a `$` in it (`statement_account_fixtures.
  words_footer`), so the reader never sends it to the vision model and Record reads the amounts as USD.
- **Right-aligned amounts.** Where a fixture says "right edge R", the amount's left x is R minus its Helvetica width at
  10 pt: digits 5.56 pt, `,` and `.` 2.78 pt, `-`, `(` and `)` 3.33 pt, space 2.78 pt. Where it says "left x", the
  amount starts there, as in the existing statement-accounts and account-import-pdf fixtures. Both alignments are needed:
  A2 says columns line up by right edge, left edge or centre, and the existing fixtures are left-aligned.
- **Lines above a table** are printed from y = 780 down, 12 pt apart. The last one names no balance and no total
  (statement-accounts plan P17), so no fixture depends on a title line by accident. Table rows are 20 pt apart unless
  stated.
- **P-checks.** Before a scenario's first checkpoint, the test asserts the reading has the intended shape: every page is
  `embedded_text`, which pages have a native table, the stated layout issues, and for right-aligned columns that the
  saved word boxes' right edges in each amount column agree within 0.5 pt. A failed P-check is a fixture or reader
  problem, never a reason to change an expected value.
- **C-net.** An autouse fixture blocks non-loopback sockets (`socket.socket.connect`, `connect_ex`,
  `socket.create_connection`). Only the `local_model` stub on loopback is reachable.
- **Shared checks**
  - **C-money:** every new `transactions.amount_minor` has `typeof() = 'integer'`, and its currency is `USD`.
  - **C-docs:** the sha256 of each fixture document's original, preserved blob and every file in its reading folder is
    unchanged by Record, Extract again and PDF import preview.
  - **C-exact(fixture):** the statement's transactions, in printed order, equal the fixture's expected
    `(posted_date, amount_minor, description)` list exactly, with no extra row. Descriptions are compared with runs of
    spaces collapsed to one.
  - **C-reconciles:** the statement has no `Statement arithmetic does not reconcile` issue and the `statement.summary`
    trace holds.
  - **C-no-row-review:** the record's issues contain no unplaced line, no chain break, no rejected row and no
    "can't be told" issue. (Other checks may still add issues; they are named where they apply.)
  - **C-zero-engine-calls:** `local_model["requests"]` grows only by the stubbed reasoning calls the scenario names.
- **Doubles**

| Component | Real or double | Specification |
|---|---|---|
| PDF reader | Real | Every fixture is read by `pdf_reader` with `VisionConfig()`. |
| Reasoning model (Record) | `local_model` by schema | `Classification` as the fixture's kind. `BankStatementSummary` or `CreditCardStatementSummary` as in "Summary stubs" below, each value citing its printed line where one is printed. `Transactions`: `{"transactions": []}` unless the scenario says otherwise (on engine pages the model's rows decide nothing, FR-18). |
| Engine fault (SC-19) | `monkeypatch` | The engine's public entry point is replaced by a function that raises `RuntimeError("injected engine fault")`. |
| Old-path records (SC-13) | Fixture | Made with the smallest direct path and stated in the test's docstring: `Ledger.publish_statement` with the rows given in SC-13, then the review status set through `POST …/review`. No expected value depends on how the state was made. |
| Index version (SC-22) | Direct SQL | `UPDATE pdf_import_index SET analyzer_version = 2` for the fixture's run, the value before this feature (`pdf_import.py:29`). |
| Clock | Real | No assertion depends on today's date. |
| Layout generator (SC-18) | Real, seeded | Expected rows come from the generator's own inputs, never from the engine. |

- **Test files (new)**
  - `tests/table_engine_fixtures.py`: the fixture builders and hand-written expected values below.
  - `tests/test_table_engine.py`: engine-level scenarios (tokens, rows, columns, roles, dates, extent, accounting).
  - `tests/test_table_engine_record.py`: Record, PDF import, provenance, upgrade and fallback scenarios.
  - `tests/table_engine_generator.py` and `tests/test_table_engine_generator.py`: FR-33.
  - `tests/test_table_engine_browser.py`: the opt-in browser step of SC-03.
  - `tests/test_evals.py`: extended for SC-20.
- **Cleanup.** pytest removes `tmp_path`. Browser tests close the browser and server through `served()`.

## Fixtures
Dates in the expected tables are ISO. "W" is money out (negative `amount_minor`), "D" is money in.

### WF: the user's Wells Fargo-style case (SC-01)
Lines above: `SYNTH WF STYLE BANK`, `Everyday Checking`, `Account number 0000009988`,
`Beginning balance on 10/1 1,000.00`, `Ending balance on 10/31 2,113.45`, `Statement period 10/01/2026 - 10/31/2026`.
The two balance lines print a date and an amount, as real Wells Fargo statements do (D6, G7).
Two-line heading. Line 1 (y 712): `Check` left x 80, `Deposits/` right edge 390, `Withdrawals/` right edge 470,
`Ending daily` right edge 560. Line 2 (y 700): `Date` left x 40, `Number` left x 80, `Description` left x 130,
`Additions` right edge 390, `Subtractions` right edge 470, `balance` right edge 560. Rows from y 680. Amounts are right
aligned at those edges; the balance prints only on a day's last row.

| # | Date | Check | Description | Deposits | Withdrawals | Balance | Expected |
|---|---|---|---|---|---|---|---|
| wf1 | 10/2 | | PAYROLL SYNTH CO | 2,000.00 | | 3,000.00 | 2026-10-02, 200000 |
| wf2 | 10/3 | 1201 | CHECK | | 150.00 | | 2026-10-03, −15000 |
| wf3 | 10/3 | | GROCERY SYNTH | | 84.55 | 2,765.45 | 2026-10-03, −8455 |
| wf4 | 10/9 | | RENT SYNTH PROPERTIES | | 1,200.00 | 1,565.45 | 2026-10-09, −120000 |
| wf5 | 10/15 | | REFUND SYNTH SHOP | 48.00 | | | 2026-10-15, 4800 |
| wf6 | 10/15 | 1202 | CHECK | | 500.00 | 1,113.45 | 2026-10-15, −50000 |
| wf7 | 10/28 | | PAYROLL SYNTH CO | 1,000.00 | | 2,113.45 | 2026-10-28, 100000 |

Arithmetic: 1,000.00 + 2,000.00 = 3,000.00; − 150.00 − 84.55 = 2,765.45; − 1,200.00 = 1,565.45; + 48.00 − 500.00 =
1,113.45; + 1,000.00 = 2,113.45, the ending balance. In 3,048.00, out 1,934.55. Day-first would put 10/2 in February,
outside the period, and 10/15 has a day over 12, so the order is month-first. No amount equals a balance.
Date-and-amount lines on page 1: wf1–wf7 (rows) + the two balance lines (summary anchors) = 9.

**WF-bare (SC-05):** WF with both heading lines removed and the amount columns in a new order: Balance right edge 330,
Withdrawals right edge 410, Deposits right edge 490. Date, check number and description stay where they are. Same
expected rows.

**WF-flag:** WF plus `statement_account_fixtures.flag_items()` (overlapping and rotated text below the footer).

### DM: the user's DD/MM/YYYY case (SC-02)
Lines above: `SYNTH DAYFIRST BANK`, `Savings Account`, `Account No 000000004417`, `Opening Balance 10,000.00`,
`Closing Balance 33,754.10`, `Statement From 01/10/2026 To 31/10/2026`.
Heading (y 700): `Date` left x 40, `Narration` left x 110, `Withdrawal Amt.` right edge 380, `Deposit Amt.` right edge
460, `Closing Balance` right edge 560. Amounts right aligned. Rows from y 680, 20 pt apart (the 20th at y 300).

| # | Date | Narration | Withdrawal | Deposit | Balance | Expected |
|---|---|---|---|---|---|---|
| 1 | 01/10/2026 | UPI SYNTH GROCER | 250.00 | | 9,750.00 | 2026-10-01, −25000 |
| 2 | 02/10/2026 | SALARY SYNTH LTD | | 45,000.00 | 54,750.00 | 2026-10-02, 4500000 |
| 3 | 03/10/2026 | ATM WDL SYNTH | 2,000.00 | | 52,750.00 | 2026-10-03, −200000 |
| 4 | 05/10/2026 | RENT TRANSFER | 15,000.00 | | 37,750.00 | 2026-10-05, −1500000 |
| 5 | 06/10/2026 | UPI SYNTH CAFE | 180.50 | | 37,569.50 | 2026-10-06, −18050 |
| 6 | 08/10/2026 | ELECTRICITY SYNTH | 1,240.00 | | 36,329.50 | 2026-10-08, −124000 |
| 7 | 10/10/2026 | INTEREST CREDIT | | 12.35 | 36,341.85 | 2026-10-10, 1235 |
| 8 | 12/10/2026 | UPI SYNTH PHARMACY | 455.00 | | 35,886.85 | 2026-10-12, −45500 |
| 9 | 13/10/2026 | NEFT SYNTH FRIEND | | 3,000.00 | 38,886.85 | 2026-10-13, 300000 |
| 10 | 14/10/2026 | CARD SYNTH FUEL | 2,100.00 | | 36,786.85 | 2026-10-14, −210000 |
| 11 | 16/10/2026 | UPI SYNTH GROCER | 1,325.75 | | 35,461.10 | 2026-10-16, −132575 |
| 12 | 18/10/2026 | MUTUAL FUND SIP | 5,000.00 | | 30,461.10 | 2026-10-18, −500000 |
| 13 | 19/10/2026 | UPI SYNTH CAFE | 95.00 | | 30,366.10 | 2026-10-19, −9500 |
| 14 | 21/10/2026 | REFUND SYNTH STORE | | 799.00 | 31,165.10 | 2026-10-21, 79900 |
| 15 | 22/10/2026 | MOBILE RECHARGE | 399.00 | | 30,766.10 | 2026-10-22, −39900 |
| 16 | 24/10/2026 | UPI SYNTH TAXI | 342.60 | | 30,423.50 | 2026-10-24, −34260 |
| 17 | 26/10/2026 | INSURANCE PREMIUM | 8,500.00 | | 21,923.50 | 2026-10-26, −850000 |
| 18 | 28/10/2026 | NEFT SYNTH CLIENT | | 12,500.00 | 34,423.50 | 2026-10-28, 1250000 |
| 19 | 30/10/2026 | UPI SYNTH GROCER | 610.40 | | 33,813.10 | 2026-10-30, −61040 |
| 20 | 31/10/2026 | BANK CHARGES | 59.00 | | 33,754.10 | 2026-10-31, −5900 |

Arithmetic: every balance is the one above ± its amount (checked row by row). Deposits 61,311.35, withdrawals
37,557.25; 10,000.00 + 61,311.35 − 37,557.25 = 33,754.10. Rows 1–8 have day ≤ 12, so month-first reads them as valid
dates (2026-01-10 … 2026-12-10), which is the reported bug.

**BRK (SC-06 a):** DM with row 14's deposit printed `797.00`; its balance stays `31,165.10`. Expected: row 14 is
2026-10-21, 79700; every other row as DM.

### WR: wrapped descriptions (SC-03)
Lines above: `SYNTH WRAP BANK`, `Account number 0000002208`, `Beginning balance 500.00`, `Ending balance 2,007.66`,
`Statement period 11/01/2026 to 11/30/2026`. Heading `Date | Description | Withdrawals | Deposits | Balance` at
`statement_account_fixtures.COLUMNS5` (left x 40, 110, 330, 400, 470). Every printed line is 14 pt below the one above.
Continuation lines start at x 110 and hold no date and no digit.

| # | Date line | Continuation lines | W | D | Balance | Expected description, amount |
|---|---|---|---|---|---|---|
| r1 | 11/02/2026 COFFEE SYNTH | | 4.25 | | 495.75 | `COFFEE SYNTH`, −425 |
| r2 | 11/04/2026 PAYROLL SYNTH | | | 1,800.00 | 2,295.75 | `PAYROLL SYNTH`, 180000 |
| r3 | 11/07/2026 GROCERY SYNTH | | 63.10 | | 2,232.65 | `GROCERY SYNTH`, −6310 |
| r4 | 11/10/2026 PHONE SYNTH | | 45.00 | | 2,187.65 | `PHONE SYNTH`, −4500 |
| r5 | 11/14/2026 ONLINE TRANSFER TO SYNTH | `SAVINGS ACCOUNT ENDING ALPHA` | 300.00 | | 1,887.65 | `ONLINE TRANSFER TO SYNTH SAVINGS ACCOUNT ENDING ALPHA`, −30000 |
| r6 | 11/20/2026 CARD PURCHASE SYNTH | `HARDWARE SUPPLY STORE`, `SPRINGFIELD US` | 129.99 | | 1,757.66 | `CARD PURCHASE SYNTH HARDWARE SUPPLY STORE SPRINGFIELD US`, −12999 |
| r7 | 11/25/2026 DEPOSIT SYNTH | `MOBILE CHECK` | | 250.00 | 2,007.66 | `DEPOSIT SYNTH MOBILE CHECK`, 25000 |

Arithmetic: 500.00 − 4.25 + 1,800.00 − 63.10 − 45.00 − 300.00 − 129.99 + 250.00 = 2,007.66. Dates are 2026-11-02,
-04, -07, -10, -14, -20, -25. P-check: the reader saves each continuation line as its own visual line.

**WR-split (SC-03 variant, FR-05 as settled in D6):** WR with r7 printed over two lines: the date line
`11/25/2026 DEPOSIT SYNTH` with no amount, and directly below it `MOBILE CHECK` with `250.00` (Deposits) and `2,007.66`
(Balance). Below r7, before the footer, one more line: `11/27/2026 SYNTH MEMO NOTICE` with no amount and no line with an
amount below it. Expected: r1–r7 exactly as WR (r7 is one row citing both lines, `DEPOSIT SYNTH MOBILE CHECK`, 25000);
the memo line is a rejected row listed with page 1, its row number and a reason; it is not recorded.

### OD: one date per day (SC-04)
Lines above: `SYNTH DAILY BANK`, `Account number 0000006630`, `Beginning balance 200.00`, `Ending balance 437.85`,
`Statement period 12/01/2026 to 12/31/2026`. Heading and columns as WR, rows 20 pt apart. Rows o2, o4 and o5 print no
date (their date cell is empty).

| # | Date | Description | W | D | Balance | Expected |
|---|---|---|---|---|---|---|
| o1 | 12/03 | COFFEE SYNTH | 3.50 | | | 2026-12-03, −350 |
| o2 | | BAKERY SYNTH | 6.25 | | 190.25 | 2026-12-03, −625, carried |
| o3 | 12/05 | PAYROLL SYNTH | | 900.00 | 1,090.25 | 2026-12-05, 90000 |
| o4 | | GROCERY SYNTH | 40.00 | | | 2026-12-05, −4000, carried |
| o5 | | PHARMACY SYNTH | 12.40 | | 1,037.85 | 2026-12-05, −1240, carried |
| o6 | 12/09 | RENT SYNTH | 600.00 | | 437.85 | 2026-12-09, −60000 |

Arithmetic: 200.00 − 3.50 − 6.25 = 190.25; + 900.00 = 1,090.25; − 40.00 − 12.40 = 1,037.85; − 600.00 = 437.85. Every day
is ≤ 12. Day-first would read 12/03, 12/05 and 12/09 as March, May and September, outside the period, so the period
decides month-first (FR-14 second clause).

### ONE: one row, no summary (SC-06 b)
Lines above: `SYNTH ONE BANK`, `Account number 0000006611`, `Statement period 09/01/2026 to 09/30/2026`. No balance or
summary line. Heading `Date | Description | Withdrawals` at left x 40, 110, 380. One row: `09/15/2026 SYNTH SERVICE FEE
25.00`. Expected: 2026-09-15, −2500 (the heading word decides, FR-13).

### CS: card with sections (SC-07)
Lines above: `SYNTH REWARDS CARD`, `Card number XXXX5512`, `Previous Balance 1,250.00`, `New Balance 481.62`,
`Statement period 10/05/2026 to 11/04/2026`. Heading `Date | Description | Amount`: Date left x 40, Description left
x 110, Amount right edge 420; amounts right aligned, all unsigned. Section titles at x 40 on their own lines:
`Payments and Credits` above p1, `Purchases` above q1.

| # | Section | Date | Description | Amount | Expected |
|---|---|---|---|---|---|
| p1 | Payments and Credits | 10/12 | PAYMENT THANK YOU | 1,000.00 | 2026-10-12, 100000 |
| p2 | Payments and Credits | 10/20 | RETURN SYNTH SHOP | 45.00 | 2026-10-20, 4500 |
| q1 | Purchases | 10/07 | SYNTH GROCERY | 120.40 | 2026-10-07, −12040 |
| q2 | Purchases | 10/15 | SYNTH FUEL | 52.18 | 2026-10-15, −5218 |
| q3 | Purchases | 10/22 | SYNTH STREAMING | 15.99 | 2026-10-22, −1599 |
| q4 | Purchases | 11/01 | SYNTH RESTAURANT | 88.05 | 2026-11-01, −8805 |

Card check: 1,250.00 − 1,045.00 + 276.62 = 481.62. Reading every row as a charge would give 1,250.00 + 1,321.62 =
2,571.62, which doesn't hold.

### NB: no balance column, no headings, printed summary (SC-07 variant)
Lines above: `SYNTH PLAIN BANK`, `Account number 0000004040`, `Beginning balance 100.00`, `Ending balance 624.80`,
`Statement period 11/01/2026 to 11/30/2026`. No heading. Date left x 40, description left x 110, two amount columns
right aligned at edges 380 (column A) and 460 (column B).

| # | Date | Description | A | B | Expected |
|---|---|---|---|---|---|
| n1 | 11/03/2026 | SYNTH PAYROLL | | 1,500.00 | 2026-11-03, 150000 |
| n2 | 11/05/2026 | SYNTH RENT | 900.00 | | 2026-11-05, −90000 |
| n3 | 11/18/2026 | SYNTH UTILITY | 75.20 | | 2026-11-18, −7520 |

Summary: 100.00 + 1,500.00 − 975.20 = 624.80 holds with A out and B in. The reverse gives 100.00 + 975.20 − 1,500.00 =
−424.80, which doesn't.

### K3: three pages, continuation with and without a heading (SC-08)
account-import-pdf's K (`pdf_import_fixtures.k_pages`, k1–k9, expected values in that contract's K table) with two
changes: page 2 repeats the heading `Date | Description | Withdrawals | Deposits | Balance` at the top, and every item on
page 3 is drawn 6 pt to the right. Expected: k1–k9 exactly as K's table (−450, −450, −4510, 200000, −50000, −500, 1999,
−8240, 12; dates 2026-08-03 … 2026-08-30).

### B, BL, UP, PR: the checking family (SC-09 – SC-11)
**B.** Lines above: `SYNTH CHECKING BANK`, `Account number 0000005521`, `Beginning balance 1,000.00`,
`Ending balance 2,950.00`, `Statement period 08/01/2026 to 08/31/2026`. Heading and columns as WR, rows 20 pt apart.

| # | Date | Description | W | D | Balance | Expected |
|---|---|---|---|---|---|---|
| b1 | 08/03/2026 | RENT SYNTH | 700.00 | | 300.00 | −70000 |
| b2 | 08/15/2026 | PAYROLL SYNTH | | 2,500.00 | 2,800.00 | 250000 |
| b3 | 08/20/2026 | REFUND SYNTH SHOP | | 150.00 | 2,950.00 | 15000 |

**BL (SC-09).** B without the two balance lines above, and with these lines inside its table, in this order:
1. `08/01/2026` (x 40), `Beginning Balance` (x 110), `1,000.00` (x 470, the Balance column).
2. b1, b2, b3.
3. `Total withdrawals` (x 110), `700.00` (x 330).
4. `Total deposits` (x 110), `2,650.00` (x 400).
5. `08/31/2026` (x 40), `Ending Balance` (x 110), `2,950.00` (x 470).

Below the table: the title `Daily ending balance` (x 40), then three lines with no heading, `08/03/2026 300.00`,
`08/15/2026 2,800.00` and `08/20/2026 2,950.00` (date x 40, amount x 470). Then the title `Fee summary` and two lines
with no date, `Monthly service fee 0.00` and `Overdraft fees 0.00` (text x 40, amount x 470). Then the footer.
Page 2 (a schedule, FR-09 as settled in D6): the title `Payment schedule` (x 40) at the top, then two lines at BL's
columns with no heading: `09/15/2026 SCHEDULED PAYMENT` with `125.00` under Withdrawals, and
`10/15/2026 SCHEDULED PAYMENT` with `125.00` under Withdrawals; no balance; then a words-only footer. Both dates fall
after 2026-08-31 + 7 days.
Lines holding a date and an amount: Beginning (anchor), b1–b3 (rows), Ending (anchor), 3 daily lines and 2 schedule lines
(other-table rows) = 10. The totals and fee lines hold no date.

**UP (SC-10).** B plus one line between b3 and the footer: `08/12/2026` (x 40), `SYNTH COURTESY CREDIT` (x 110),
`35.00` (left x 545, to the right of every column). Date-and-amount lines: b1–b3 + that line = 4.

**PR (SC-11).** Page 1 is B with `Ending balance 2,947.50` instead of `2,950.00`. Page 2 is prose, each line at x 40,
14 pt apart from y 700:
- `Important information about your account. Paper statement fees apply from this month.`
- `A paper statement fee of 2.50 was charged on 08/28/2026 to this account.`
- `Interest of 0.42 was paid on 08/31/2026 and will show on next month's statement.`

and a words-only footer. Summary: 1,000.00 − 700.00 + 2,500.00 + 150.00 − 2.50 = 2,947.50.

### CC: two accounts in one PDF (SC-17)
Page 1 lines above: `SYNTH COMBINED BANK`, `Statement period 09/01/2026 to 09/30/2026`, then the title
`CHECKING ACCOUNT 0000003311`, then a table at COLUMNS5 (`Date | Description | Withdrawals | Deposits | Balance`):
c1 `09/02/2026 SYNTH RENT` W 100.00, balance 400.00; c2 `09/10/2026 SYNTH PAYROLL` D 250.00, balance 650.00;
c3 `09/20/2026 SYNTH GAS` W 50.00, balance 600.00.
Page 2: the title `SAVINGS ACCOUNT 0000003322`, then a table at COLUMNS4 (`Date | Description | Amount | Balance`):
v1 `09/05/2026 TRANSFER FROM CHECKING 1,000.00`, balance 6,000.00; v2 `09/25/2026 SYNTH WITHDRAWAL -200.00`, balance
5,800.00; v3 `09/30/2026 INTEREST 2.15`, balance 5,802.15.
Each chain holds (400 + 250 = 650, − 50 = 600; 6,000 − 200 = 5,800, + 2.15 = 5,802.15). The savings chain starts from
5,000.00 (6,000.00 − 1,000.00), not from 600.00, so the two don't join. The column sets differ, so they are two tables
(FR-06; see G10). Expected: −10000, 25000, −5000, 100000, −20000, 215.

### ND: dates that can't tell the order (SC-16)
Two pages, COLUMNS4, heading `Date | Description | Amount | Balance` on page 1 only. Lines above: `SYNTH NODATE BANK`,
`Account number 0000007788`. No period, no balance lines. Page 1: n1 `03/04/2026 ALPHA 10.00`, balance 110.00; n2
`03/05/2026 BRAVO -5.00`, balance 105.00. Page 2: n3 `04/06/2026 CHARLIE 1.00`, balance 106.00; n4
`04/07/2026 DELTA 2.00`, balance 108.00. Both orders give valid dates in non-decreasing order.
**ND-prior (SC-16 b):** a 1-page statement of the same layout and account number, rows `15/02/2026 ECHO 3.00` balance
103.00 and `16/02/2026 FOXTROT 1.00` balance 104.00 (day over 12: day-first).

### FX, PD, TD: card risks (SC-23 – SC-25)
**FX (R3).** Lines above: `SYNTH TRAVEL CARD`, `Card number XXXX7001`, `Previous Balance 0.00`, `New Balance 210.00`,
`Statement period 10/01/2026 to 10/31/2026`. Heading `Date | Description | Foreign amount | Rate | Amount`: left x 40,
110; right edges 330, 400, 480; right aligned.
- fx1 `10/03 SYNTH HOTEL PARIS`, foreign 92.17, rate 1.0850, amount 100.00 → 2026-10-03, −10000.
- fx2 `10/09 SYNTH CAFE LONDON`, foreign 38.50, rate 1.2987, amount 50.00 → 2026-10-09, −5000.
- fx3 `10/15 SYNTH BOOKS`, no foreign amount or rate, amount 60.00 → 2026-10-15, −6000.

Card check: 0.00 + 210.00 = 210.00. Taking the foreign column as the charge gives 130.67, which doesn't hold.

**PD (R4).** Lines above: `SYNTH PENDING CARD`, `Card number XXXX7002`, `Previous Balance 100.00`,
`New Balance 145.00`, `Statement period 10/01/2026 to 10/31/2026`. Heading `Date | Description | Amount` as CS. Section
`Purchases`: `10/05 SYNTH GROCERY 30.00` → 2026-10-05, −3000; `10/18 SYNTH FUEL 15.00` → 2026-10-18, −1500. Then section
`Pending transactions`: `10/30 SYNTH HOTEL 200.00`, `10/31 SYNTH TAXI 12.50`. Card check: 100.00 + 45.00 = 145.00.

**TD (R5).** Lines above: `SYNTH POSTING CARD`, `Card number XXXX7003`, `Previous Balance 0.00`, `New Balance 439.25`,
`Statement period 09/20/2026 to 10/19/2026`. Heading `Trans Date | Post Date | Description | Amount`: left x 40, 90, 150;
Amount right edge 420.

| # | Trans | Post | Description | Amount | Expected transaction_date, posted_date, amount |
|---|---|---|---|---|---|
| t1 | 09/28 | 10/01 | SYNTH AIRLINE | 412.00 | 2026-09-28, 2026-10-01, −41200 |
| t2 | 10/02 | 10/03 | SYNTH CAFE | 7.25 | 2026-10-02, 2026-10-03, −725 |
| t3 | 10/14 | 10/15 | SYNTH BOOKS | 20.00 | 2026-10-14, 2026-10-15, −2000 |

**TD-bare:** TD with the heading removed. Same expected values (FR-04: with no heading, the first is the transaction
date and the second the posted date).

### Summary stubs
Values cite their printed line where the fixture prints one; "missing" means `{"status": "missing"}`. Currency missing
(USD from the footer's `$`).

| Fixture | Kind | Institution | Last four | Period | Opening / previous | Closing / new |
|---|---|---|---|---|---|---|
| WF, WF-bare, WF-flag | bank, checking | SYNTH WF STYLE BANK | 9988 | 2026-10-01 – 2026-10-31 | 1,000.00 | 2,113.45 |
| DM, BRK | bank, savings | SYNTH DAYFIRST BANK | 4417 | 2026-10-01 – 2026-10-31 | 10,000.00 | 33,754.10 |
| WR | bank, checking | SYNTH WRAP BANK | 2208 | 2026-11-01 – 2026-11-30 | 500.00 | 2,007.66 |
| OD | bank, checking | SYNTH DAILY BANK | 6630 | 2026-12-01 – 2026-12-31 | 200.00 | 437.85 |
| ONE | bank, checking | SYNTH ONE BANK | 6611 | 2026-09-01 – 2026-09-30 | missing | missing |
| CS | card | SYNTH REWARDS CARD | 5512 | 2026-10-05 – 2026-11-04 | 1,250.00 | 481.62 |
| NB | bank, checking | SYNTH PLAIN BANK | 4040 | 2026-11-01 – 2026-11-30 | 100.00 | 624.80 |
| K3 | bank, checking | FIRST LOCAL BANK | 4821 | 2026-08-01 – 2026-08-31 | 1,000.00 | 2,378.61 |
| B, BL, UP | bank, checking | SYNTH CHECKING BANK | 5521 | 2026-08-01 – 2026-08-31 | 1,000.00 | 2,950.00 |
| PR | bank, checking | SYNTH CHECKING BANK | 5521 | 2026-08-01 – 2026-08-31 | 1,000.00 | 2,947.50 |
| CC | bank, checking | SYNTH COMBINED BANK | 3311 | 2026-09-01 – 2026-09-30 | 500.00 | 600.00 |
| ND | bank, checking | SYNTH NODATE BANK | 7788 | missing | missing | missing |
| ND-prior | bank, checking | SYNTH NODATE BANK | 7788 | 2026-02-01 – 2026-02-28 | 100.00 | 104.00 |
| FX | card | SYNTH TRAVEL CARD | 7001 | 2026-10-01 – 2026-10-31 | 0.00 | 210.00 |
| PD | card | SYNTH PENDING CARD | 7002 | 2026-10-01 – 2026-10-31 | 100.00 | 145.00 |
| TD | card | SYNTH POSTING CARD | 7003 | 2026-09-20 – 2026-10-19 | 0.00 | 439.25 |

---

## SC-21 (new): tokens
Requirement IDs: FR-02. Level: engine unit test, no PDF.
Each printed token (a word or run as the reader saves it) gets the tag shown. For amounts the expected value is the
magnitude in minor units and the printed sign marker.

| Printed | Tag | Value |
|---|---|---|
| `9/1`, `09/01`, `9/1/26`, `09/01/2026`, `01/09/2026`, `09-01-2026`, `09.01.2026`, `2026-09-01` | date | (order decided later, FR-14) |
| `01 Oct 2026`, `1-Oct-26`, `Oct 1`, `Oct 01, 2026` | date | 2026-10-01 where a year is printed; month Oct, day 1 |
| `13/45`, `1/2/3/4`, `2026-13-01` | text | |
| `0.36` | amount | 36, unsigned |
| `1,234.56` | amount | 123456, unsigned |
| `$1,234.56`, `USD 1,234.56`, `1,234.56 USD` | amount | 123456, unsigned, currency USD where printed |
| `-12.00` | amount | 1200, negative |
| `+12.00` | amount | 1200, positive |
| `12.00-` | amount | 1200, negative |
| `(12.00)` | amount | 1200, negative |
| `12.00 CR` | amount | 1200, credit |
| `12.00 DR` | amount | 1200, debit |
| `PPD ID 1234567890` | text | |
| `SYNTH LONG DESCRIPTION12.34` (no space) | text | |

`1.234,56` is never read as any amount (OD-3). Whether it is tagged as an amount that is then rejected or as text is G18.
Evidence: `pytest tests/test_table_engine.py -k sc21`

## SC-01: the Wells Fargo-style statement
Requirement IDs: FR-03, FR-04, FR-10, FR-18
Fixture: WF. Stubs: WF summary; `Transactions` deliberately wrong: one row `10/2 PAYROLL SYNTH CO 3,000.00 credit`
citing wf1's line.
P-check: one `embedded_text` page; the heading's words sit on two visual lines (y 712 and 700); no native transactions
table built under the old header rules.
1. Engine on the reading → one transactions table with 7 rows; columns: date, description, three amount columns whose
   roles are Deposits = money in, Withdrawals = money out, Ending daily balance = balance.
2. Record →
   - C-exact(WF). No transaction has 120100 or 120200 (the check numbers) or any balance value (300000, 276545,
     156545, 111345, 211345). wf2's and wf6's descriptions contain `CHECK` (where the check number goes is G8).
   - C-reconciles. C-no-row-review. C-money.
   - The wrong stub row matches no engine row and becomes one record note (statement-accounts FR-20, unchanged).
   - The two dated balance lines are summary anchors: no unplaced line, no issue quoting them. Engine identity: 7 rows +
     2 anchors = 9.
   - `GET /api/finance/records/statement/{id}` shows opening balance 100000 and closing balance 211345 (the document
     page's Opening and Closing balance fields).
3. Variant WF-summary-off: the summary stub gives opening 1,100.00 and closing 2,213.45 → the record still shows 100000
   and 211345 (the printed values), and its notes include one naming each differing value. The rows are as step 2.
4. Variant WF-flag → the same 7 rows; the statement needs review with `Page 1 PDF layout needs review: …` (FR-23).
Evidence: `pytest tests/test_table_engine_record.py -k sc01`

## SC-02: the DD/MM/YYYY statement
Requirement IDs: FR-04, FR-14, FR-18
Fixture: DM. P-check: one `embedded_text` page; 20 visual lines with a date at x 40.
Record → C-exact(DM): 20 rows, every date day-first (2026-10-01 … 2026-10-31); no row dated 2026-01-10, 2026-02-10,
2026-03-10, 2026-05-10, 2026-06-10, 2026-08-10 or 2026-12-10. C-reconciles. C-no-row-review.
Evidence: `pytest tests/test_table_engine_record.py -k sc02`

## SC-03: wrapped descriptions and their source
Requirement IDs: FR-05, FR-22
Fixture: WR. One test, ordered checkpoints:
1. Record → C-exact(WR): 7 rows with the full descriptions above. C-reconciles. No issue says "No date is printed".
2. `GET /api/provenance/transaction/{r6}` → `rebuilt` true, `page` 1, `line_ids` lists the three lines of r6 in
   printed order, `word_ids` holds every word of those lines (date, description words, 129.99, 1,757.66), and `quotes`
   has one entry per line.
3. The same for r5 → two lines.
4. Browser (opt-in): open r6's source from the document page → page 1 opens with all three lines highlighted.
5. Variant WR-split, Record → C-exact(WR); r7's provenance lists its two lines; the issues include one rejected row naming
   page 1 and the memo line's row; the statement is `needs_review`; no transaction is dated 2026-11-27.
Evidence: `pytest tests/test_table_engine_record.py -k sc03`; `RUN_BROWSER_TESTS=1 pytest tests/test_table_engine_browser.py`

## SC-04: one date per day
Requirement IDs: FR-05, OD-1
Fixture: OD. Record →
- C-exact(OD) with dates 2026-12-03, 2026-12-03, 2026-12-05, 2026-12-05, 2026-12-05, 2026-12-09.
- Exactly three record notes, one each for o2, o4 and o5, each starting `Page 1 row 2: no date is printed; it takes `,
  `Page 1 row 4: …` and `Page 1 row 5: …` and naming the carried date (12/03 or 12/05 of 2026; format G15).
- The notes are not review reasons: C-no-row-review and C-reconciles hold. No issue says "No date is printed".
Evidence: `pytest tests/test_table_engine_record.py -k sc04`

## SC-05: no headings, columns in another order
Requirement IDs: FR-03, FR-04, FR-10
Fixture: WF-bare. P-check: no visual line holds `Date`, `Description` or `balance`.
1. Engine → the same rows as SC-01 step 1, with roles found by the chain: the column at 330 is the balance, 410 money
   out, 490 money in.
2. Record → C-exact(WF) (same rows, dates, amounts, descriptions as SC-01). C-reconciles.
Evidence: `pytest tests/test_table_engine_record.py -k sc05`

## SC-06: a broken chain, and too few rows
Requirement IDs: FR-13, FR-15
- (a) BRK, Record →
  - 20 rows recorded, equal to DM's except row 14, which is 2026-10-21, 79700.
  - The issues include exactly one chain issue, `Page 1 row 14: the balance 31,165.10 doesn't follow from the row
    above`. No other row is named by a chain issue.
  - The statement is `needs_review`.
- (b) ONE, Record → one row, 2026-09-15, −2500. The statement is `needs_review`, and its issues include one that names
  page 1 and gives the reason the signs couldn't be proved (too few rows, no summary; wording G16).
Evidence: `pytest tests/test_table_engine_record.py -k sc06`

## SC-07: signs from the summary and from sections
Requirement IDs: FR-11, FR-12
- CS, Record → C-exact(CS): p1 and p2 money in, q1–q4 money out. The card check holds (C-reconciles). C-no-row-review.
- NB, Record → C-exact(NB): A is money out, B money in. C-reconciles.
- Engine on NB with the summary lines removed (no chain, no summary, no headings) → the roles can't be decided: no
  assignment is reported as decided by the chain or summary (FR-11, FR-13). What the outcome is in Record follows FR-13
  and is asserted only as `needs_review`.
Evidence: `pytest tests/test_table_engine_record.py -k sc07`

## SC-08: one table across three pages
Requirement IDs: FR-06
Fixture: K3. P-check: page 3's items are 6 pt right of pages 1–2's.
1. Engine → one transactions table whose rows cite pages 1, 2 and 3 (k1–k3, k4–k6, k7–k9); page 2's repeated heading is
   not a row.
2. PDF import preview with account `A` (USD checking …4821) → the same 9 rows (dates and signed amounts as K), page 3's
   rows linked to page 1's table; no row rejected; no unplaced line.
3. Record (S-K summary, `Transactions` empty) → C-exact(K3). C-reconciles.
Evidence: `pytest tests/test_table_engine_record.py -k sc08`

## SC-09: balance lines, totals and other tables
Requirement IDs: FR-07, FR-09
Fixture: BL. Record →
- C-exact: b1–b3 only (−70000, 250000, 15000).
- No transaction comes from `Beginning Balance`, `Ending Balance`, a total line, a daily line, a fee line or the
  schedule: there are exactly 3 transactions, and none has 100000, 295000, 265000, 30000, 280000, 0 or −12500.
- C-reconciles. C-no-row-review (in particular, no unplaced line).
- Engine → the balance lines are anchors (opening 1,000.00 and closing 2,950.00), the totals are checks that hold
  (700.00, 2,650.00), the daily lines are a separate balance table with no rows, the fee lines are no table's rows.
  The page 2 lines are a schedule: other-table rows, not transactions and not unplaced; no transaction is dated
  2026-09-15 or 2026-10-15.
  The FR-08 identity holds: 3 rows + 0 rejected + 2 anchors + 0 totals + 5 other-table rows + 0 unplaced = 10
  date-and-amount lines.
- statement-accounts D (`DAILY ENDING BALANCE` table) keeps its result (SC-15).
Evidence: `pytest tests/test_table_engine_record.py -k sc09`

## SC-10: a printed line that fits no column
Requirement IDs: FR-08, FR-20
Fixture: UP. Record →
- b1–b3 are recorded as in B; no transaction has 3500.
- The statement is `needs_review`. Its issues include one that names page 1 and quotes the line
  `08/12/2026 SYNTH COURTESY CREDIT 35.00`.
- Engine → identity: 3 rows + 0 rejected + 0 anchors + 0 totals + 0 other-table rows + 1 unplaced = 4 date-and-amount
  lines.
- For every fixture in this contract, the engine's identity holds (rows + rejected + anchors + totals + other-table rows +
  unplaced = all date-and-amount lines on the table pages, FR-08), using the hand counts given with each fixture or counted
  from its expected table.
Evidence: `pytest tests/test_table_engine.py -k sc10`, `pytest tests/test_table_engine_record.py -k sc10`

## SC-11: a page with no table
Requirement IDs: FR-19
Fixture: PR. Stubs: PR summary. First `Transactions` answer: one row `08/28/2026 PAPER STATEMENT FEE 2.50 debit`
citing the fee line. Second `Transactions` answer (the missed-row request): `{"transactions": []}`.
Record →
- 4 transactions: b1–b3 from the engine and the stub's fee, 2026-08-28, −250.
- The notes include exactly `Page 2: no table was found in the printed columns, so its rows are the reading's; check
  them.` and no such note for page 1.
- The missed-row check ran for page 2: `local_model` received a second `Transactions` request whose lines include the
  interest line and no line from page 1.
- C-reconciles (1,000.00 − 700.00 + 2,500.00 + 150.00 − 2.50 = 2,947.50).
Evidence: `pytest tests/test_table_engine_record.py -k sc11`

## SC-12: PDF import preview agrees with Record
Requirement IDs: FR-21
For each fixture WF, WF-bare, DM, WR, OD, CS, NB, K3, BL, UP, CC, FX, PD and TD, in a fresh library:
1. Create an account matching the fixture's summary stub (`POST /api/finance/accounts`, kind and last four).
2. Preview by `account_id` with no choices → no year, date-order or sign choice is reported as required: every one of
   these fixtures prints its period, which the engine reads (FR-14), and the engine decides order and signs (FR-21).
   The preview's dates use the printed period's year (WF, OD, CS, FX, PD and TD print no year on their rows).
3. Then Record the same reading (its summary stub).
4. The preview's parsed, ticked rows, in printed order, equal the recorded transactions on
   `(posted_date, amount_minor, description)`. The preview lists UP's and PD's unplaced lines with page and line text (presentation: G13), and none of them is
   importable.
Account-import-pdf behavior otherwise unchanged: C-docs, and the preview writes nothing.
Evidence: `pytest tests/test_table_engine_record.py -k sc12`

## SC-13 + SC-22 (Journey J1): an upgraded library
Requirement IDs: FR-25, FR-26
Initial state, built before the feature's start-up runs:
- DM captured and read twice as two documents, Y and Z (Z is DM with its footer text changed so the hashes differ).
- Statement Y published with the old path's rows: DM rows 1–8 with month-first dates (2026-01-10, 2026-02-10,
  2026-03-10, 2026-05-10, 2026-06-10, 2026-08-10, 2026-10-10, 2026-12-10) and their amounts; status `needs_review`.
- Statement Z published with the same 8 rows, then confirmed by the user (`POST …/review {"status": "verified"}`).
- Both readings' `pdf_import_index` rows set to `analyzer_version = 2`.
Checkpoints:
1. Start the app → no transaction or statement row changes (snapshot of `statements` and `transactions` equal).
   `pdf_import.pending(db)` lists both runs, and `GET /api/finance/import-candidates` reports `indexing: true`.
2. Let the index job finish → both index rows have the new `ANALYZER_VERSION` (greater than 2);
   `indexing: false`. Running start-up again doesn't re-index (pending is empty).
3. Extract again on Z → `kept_reviewed`; Z's statement and its 8 rows are unchanged (snapshot equal).
4. Extract again on Y → Y now holds DM's 20 rows exactly (C-exact(DM)), and none of the month-first dates.
Expected final state: Z unchanged with 8 rows; Y with 20 rows; no schema change (the migration list is the same as before
the feature). C-docs.
Evidence: `pytest tests/test_table_engine_record.py -k journey_j1`

## SC-14: determinism and no model calls
Requirement IDs: FR-01, FR-27
- For every fixture: the engine run twice on the same reading gives byte-identical serialized output (tables, rows, ids,
  issues), with `local_model` running, C-net active, and zero requests from the engine.
- WF and WR: Record, then Extract again → identical transaction ids, dates, amounts and descriptions, and identical
  locators.
Evidence: `pytest tests/test_table_engine.py -k sc14`, `pytest tests/test_table_engine_record.py -k sc14`

## SC-15: existing scenarios
Requirement IDs: FR-16, FR-23, FR-28
Every statement-accounts and account-import-pdf scenario passes with its expected values unchanged, except those listed
under "Scenarios this spec changes" below, which are updated to the expected values given there and nothing else.
In particular: statement-accounts SC-13 (S-flag, FR-23), SC-14 (W and C), SC-15 (C, C0), SC-16, SC-17 x1 and x3–x6
(FR-16), SC-18, SC-19, SC-20, SC-21 (D, D-flag, daily table on page 2), SC-23 (Q), SC-27, SC-28; account-import-pdf J1,
SC-02 – SC-05, SC-07 (except 7-a and 7-d), SC-08, SC-09, SC-24, SC-25.
Record now takes the period from the printed line (FR-14). The existing fixtures print the same period their summary stubs
give (`S_ABOVE`, `W_ABOVE` and C's lines, checked), so no expected value changes on that account.
Evidence: `pytest tests/test_statement_rebuild.py tests/test_statement_accounts.py tests/test_pdf_imports.py`

## SC-16: dates whose order can't be told
Requirement IDs: FR-14, OD-2
- (a) ND, Record → no transaction recorded. Exactly two issues about the date order, one naming page 1 and one naming
  page 2, each saying the order can't be told. The statement is `needs_review`.
- (b) Record ND-prior first (day-first decided by 15 and 16), then ND with the same last four → ND's rows are recorded
  day-first: 2026-04-03 1000, 2026-05-03 −500, 2026-06-04 100, 2026-07-04 200. No date-order issue.
- (c) As (b) but ND-prior prints last four 7799 → ND as in (a).
- PDF import preview of ND into a fresh account → the date order is a required choice.
Evidence: `pytest tests/test_table_engine_record.py -k sc16`

## SC-17: two accounts in one PDF
Requirement IDs: FR-17
Fixture: CC. Record →
- All 6 rows recorded: −10000, 25000, −5000, 100000, −20000, 215, dated 2026-09-02, -10, -20, -05, -25, -30.
- Exactly one issue containing `This PDF may hold more than one account`, naming both tables (page 1 and page 2).
- No chain issue (`doesn't follow from the row above`).
- The statement is `needs_review`.
Evidence: `pytest tests/test_table_engine_record.py -k sc17`

## SC-18: the layout generator
Requirement IDs: FR-33
- `tests/table_engine_generator.py` builds at least 200 statements from a fixed seed with `make_pdf`. Each case
  carries its own expected rows (date, signed amount, description) from its inputs.
- The generator's own check: every variation named in FR-33 occurs in at least 5 cases (column order; heading wording
  known, unknown, none, one line, two lines; date formats month-first, day-first, ISO and month names, with and without
  a year; wrapped descriptions of 1, 2 and 3 lines; one date per day; one signed column, in/out columns, `CR`/`DR`,
  parentheses; with and without a balance column; with and without a summary; continuation pages with and without a
  heading; extra non-transaction tables).
- Generator rules so every case is decidable under the spec: each case prints a running balance or a summary (or both);
  a case with year-less dates prints its period; a case whose dates are all ≤ 12 prints a period that decides the order.
- Generating twice from the seed gives byte-identical PDFs.
- Each case is read by the real reader and run through the engine's statement path. Every row matches its expected row
  exactly and the case reconciles. A failure prints the seed, the case index and its layout choices.
- 10 cases chosen by the seed also go end to end through Record with stubbed summaries and C-exact.
Evidence: `pytest tests/test_table_engine_generator.py`

## SC-19: the engine fails
Requirement IDs: FR-24
Engine fault double active. Fixture: WF, with a `Transactions` stub listing wf1–wf7 correctly.
1. Record → the statement's rows are the stub's 7 rows; notes include `REBUILD_FAILED`'s text exactly
   (`extraction.py:1283`). One failure is logged; no log record holds any fixture description, amount or the account
   number.
2. PDF import preview → a 4xx refusal, nothing written (`transactions`, `transaction_imports`, `accounts` counts
   unchanged), and the response holds no traceback (message: G12).
Evidence: `pytest tests/test_table_engine_record.py -k sc19`

## SC-20: the eval metric
Requirement IDs: FR-34
Uses `tests/test_evals.py`'s pattern: `evals.run.run` on a synthetic corpus with the `local_model` stub.
- `python -m evals.synthetic` writes the existing cases unchanged (the same case ids and answers as before), plus four
  text-PDF statements in aligned columns: a Wells Fargo-style two-line heading, a DD/MM/YYYY statement, one with
  wrapped descriptions, and a card statement with sections. Each one's answers come from its generator inputs.
- On those four, the engine records every printed row with exact date, amount and direction, and each reconciles.
- `summary.json` has, for text-PDF statements and for each reader (old and engine): the share of printed rows recorded
  with exact date, amount and direction, the share of statements that reconcile, and the count of unplaced lines.
- `summary.json` still passes the report's allowlist (`evals/report.py`), and holds no description or amount.
- report.md shows both readers side by side.
- The engine's value is ≥ the old reader's on each metric for the synthetic corpus (see G14).
Evidence: `pytest tests/test_evals.py -k table_engine`

## SC-23 (new): an extra amount column is never an amount
Requirement IDs: FR-10, FR-11; R3
FX, Record → C-exact(FX): −10000, −5000, −6000. No transaction has 9217, 3850 or a rate. C-reconciles.
Evidence: `pytest tests/test_table_engine_record.py -k sc23`

## SC-24 (new): pending rows are not recorded
Requirement IDs: FR-08, FR-20; R4
PD, Record → 2 transactions (2026-10-05 −3000, 2026-10-18 −1500). The statement is `needs_review`, with one issue per
pending line naming page 1 and quoting `10/30 SYNTH HOTEL 200.00` and `10/31 SYNTH TAXI 12.50`. C-reconciles (the card
check uses only the posted rows).
Evidence: `pytest tests/test_table_engine_record.py -k sc24`

## SC-25 (new): two date columns
Requirement IDs: FR-04; R5
TD and TD-bare, Record → for each row, `transaction_date` and `posted_date` as in TD's table; amounts −41200, −725,
−2000. C-reconciles.
Evidence: `pytest tests/test_table_engine_record.py -k sc25`

---

## Scenarios this spec changes (FR-28)
Each is updated to the expected value given here, with the requirement that changes it. Nothing else in them changes.

| Existing scenario or test | Was | Now | Changed by |
|---|---|---|---|
| statement-accounts SC-17, x2 (`test_rows_x_records_only_x1…`) | Rejected: the amount doesn't fit a column | Not a row: an unplaced line naming page 1 and quoting the line. x1 recorded, x3–x6 rejected as before; status `needs_review` | FR-04 (columns by alignment), FR-08, FR-20 |
| account-import-pdf SC-07 7-d | B2 rejected: the amount doesn't fit a column | B2 listed as an unplaced line with page 2 and its text; not importable; B1 imports | FR-04, FR-08, FR-21 |
| `test_rows_a_balance_title_above_a_transactions_shaped_table_leaves_the_page_to_the_model_with_a_note` | No rows rebuilt; a note gives the page to the model | s1–s5 recorded from the printed columns; no such note (the title is a hint, the rows have descriptions and the chain holds) | D1, FR-09 |
| `test_rows_a_second_transactions_heading_on_a_rebuilt_page_is_listed` | `LATE ROW` not read; issue "rows after a second transactions heading … weren't read" | The repeated heading is ignored and `10/01 LATE ROW 9.00` is a row of S's table: 2026-10-01, 900. That issue is gone. Opening 0.00 + rows = 1,009.00 ≠ 1,000.00, so the statement doesn't reconcile and needs review | FR-06, FR-07, FR-08 |
| account-import-pdf SC-07 7-a | Payment schedule rows imported as `continued from page 1` (accepted risk D10) | Unchanged: X prints no period, so dates don't decide (FR-09). New variant 7-a′: X with `Statement period 09/01/2026 to 09/30/2026` printed above page 1's tables → page 3's two `Scheduled payment` rows are other-table rows, not importable, not unplaced; 4 rows, totals as step 1 | FR-09, FR-14 (D6) |
| `test_fr30_edge_a_joined_only_amount…` (T-edge) | t1 rejected with today's reason | Unchanged: a dated line with no amount is a rejected row and keeps today's reason (FR-05 as settled in D6) | FR-05 |
| `test_fr30_the_analyzer_version_is_two…` | `ANALYZER_VERSION == 2` | `ANALYZER_VERSION == 3` | FR-26 |

---

## Traceability
| FR / SC | Scenarios | Command |
|---|---|---|
| FR-01 | SC-14 | `pytest tests/test_table_engine.py -k sc14` |
| FR-02 | SC-21 | `pytest tests/test_table_engine.py -k sc21` |
| FR-03 | SC-01, SC-05 | `pytest tests/test_table_engine_record.py -k "sc01 or sc05"` |
| FR-04 | SC-01, SC-02, SC-05, SC-25 | `-k "sc01 or sc02 or sc05 or sc25"` |
| FR-05 | SC-03 (with WR-split), SC-04 | `-k "sc03 or sc04"` |
| FR-06 | SC-08 | `-k sc08` |
| FR-07 | SC-09, SC-01 (dated summary lines; opening and closing shown) | `-k "sc09 or sc01"` |
| FR-08 | SC-10, SC-24 | `pytest tests/test_table_engine.py -k sc10`; `…record.py -k "sc10 or sc24"` |
| FR-09 | SC-09 (with the schedule), SC-15 (D), 7-a′ | `-k sc09`; `tests/test_statement_rebuild.py -k sc21` |
| FR-10 | SC-01, SC-05, SC-23 | `-k "sc01 or sc05 or sc23"` |
| FR-11 | SC-07, SC-23 | `-k "sc07 or sc23"` |
| FR-12 | SC-07 | `-k sc07` |
| FR-13 | SC-06 (b), SC-07 | `-k "sc06 or sc07"` |
| FR-14 | SC-02, SC-04, SC-12 (printed period), SC-16 | `-k "sc02 or sc04 or sc16"` |
| FR-15 | SC-06 (a) | `-k sc06` |
| FR-16 | SC-15 | the three existing suites |
| FR-17 | SC-17 | `-k sc17` |
| FR-18 | SC-01, SC-02 | `-k "sc01 or sc02"` |
| FR-19 | SC-11 | `-k sc11` |
| FR-20 | SC-10, SC-24 | `-k "sc10 or sc24"` |
| FR-21 | SC-12, SC-08 step 2, SC-16 | `-k "sc12 or sc08 or sc16"` |
| FR-22 | SC-03 | `-k sc03`; browser |
| FR-23 | SC-01 (WF-flag), SC-15 | `-k sc01` |
| FR-24 | SC-19 | `-k sc19` |
| FR-25 | J1 (SC-13) | `-k journey_j1` |
| FR-26 | J1 (SC-22) | `-k journey_j1` |
| FR-27 | SC-14 | `-k sc14` |
| FR-28 | SC-15, "Scenarios this spec changes" | the existing suites |
| FR-33 | SC-18 | `pytest tests/test_table_engine_generator.py` |
| FR-34 | SC-20 | `pytest tests/test_evals.py -k table_engine` |
| FR-40 – FR-44 | not in this contract (OD-5) | their own specs |
| OD-1 | SC-04 | `-k sc04` |
| OD-2 | SC-16 (b, c) | `-k sc16` |
| OD-3 | SC-21 | `-k sc21` |
| OD-4 | SC-18 (the tolerance the plan records is used by every fixture) | generator suite |
| R1 – R5 | SC-06 b; SC-17; SC-23; SC-24; SC-25 | as above |

Regression run, touched components only:
```
python -m pytest tests/test_table_engine.py tests/test_table_engine_record.py tests/test_table_engine_generator.py \
  tests/test_statement_rebuild.py tests/test_statement_accounts.py tests/test_statement_forms.py tests/test_pdf_imports.py \
  tests/test_extraction.py tests/test_layout_consumers.py tests/test_provenance.py tests/test_reextraction.py \
  tests/test_evals.py -q
RUN_BROWSER_TESTS=1 python -m pytest tests/test_table_engine_browser.py tests/test_statement_accounts_browser.py \
  tests/test_pdf_imports_browser.py -q
```

## Gaps (flagged, not invented)
- **G1 (FR-09): resolved 2026-10-27 (D6).** A run of rows all dated outside the period is a schedule. SC-09's schedule
  page and 7-a′ assert it; 7-a (no period printed) is unchanged.
- **G2 (FR-14, FR-21): resolved 2026-10-27 (D6).** The engine reads the printed period; SC-12 asserts no year or
  date-order choice where it is printed.
- **G3 (FR-08): resolved by the amended FR-08**, which counts rejected rows as their own term.
- **G4 (FR-05, FR-08): resolved 2026-10-27 (D6).** A dated line with no amount joins an amount line directly below,
  else it is a rejected row with a reason (WR-split in SC-03; T-edge unchanged).
- **G5 (FR-05): descriptions printed above their amounts.** The third sentence has no criterion for "when the statement
  prints descriptions above their amounts", and conflicts with the first (a text-only line joins the row above). Not
  asserted.
- **G6 (OD-1): a dateless first row.** A table's or a continuation page's first row with no date has no row above in
  the same table on that page. Not asserted.
- **G7 (FR-07, FR-08): resolved 2026-10-27 (D6).** Balance lines outside the table, dated or not, are summary anchors,
  and the record's opening and closing balances are their printed values (SC-01 steps 2–3).
- **G8 (FR-02, FR-04): check numbers.** Whether an integer like `1201` is an amount token, and whether a check-number
  column's text joins the description, is not stated. SC-01 asserts only that it is never an amount.
- **G9 (FR-07): a column total that doesn't match.** Whether it is a review reason is not stated. Not asserted.
- **G10 (FR-06, FR-17): two accounts in the same layout.** If checking and savings print the same columns, FR-06 makes
  them one table, and FR-15 reports a chain break instead of FR-17's issue. CC uses different column sets.
- **G11 (FR-10): roles when no assignment holds on every row.** SC-06 (a) asserts only the outcome the spec states.
- **G12 (FR-24): the PDF import refusal text.** No existing message covers an analyzer exception
  (`ledger.py` calls `pdf_import.analyze` without a handler). SC-19 asserts a 4xx with no write and no traceback.
- **G13 (FR-21): unplaced lines in the import preview.** account-import-pdf's identity (imported + duplicates + rejected
  + left out = rows seen) has no term for unplaced lines, and the dialog's presentation is not stated. SC-12 asserts
  only that the preview lists them with page and text.
- **G14 (FR-34): resolved 2026-10-27 (D6).** Four aligned-column statements are added to the synthetic corpus (SC-20);
  `docs/evals.md` and `evals/README.md` update their counts.
- **G15 (OD-1): the carried date's format and row numbering** in the note. Asserted by prefix and the date's value.
- **G16 (FR-13, FR-17): wording** of the too-few-rows reason and the two-accounts issue beyond the quoted phrase.
- **G17 (FR-04, R5): reversed headings.** With `Posting Date | Transaction Date`, FR-04 reads as keeping the second
  column as the posted date either way. Not asserted.
- **G18 (OD-3): decimal-comma tokens.** "Rejected as unreadable" doesn't say whether the token is an amount (so its row
  is rejected) or text (so the line may not be a row). SC-21 asserts only that it is never read as an amount.
