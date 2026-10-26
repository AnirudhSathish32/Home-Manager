# Test contract: statement-accounts
Spec sha256: the bundle hash (spec.md + this file) from the user's gate tooling. `gate.py` isn't in this repository
(spec U2), so the hash isn't copied here: writing it in would change it.

Every expected value comes from `spec.md`, or is worked out by hand from the synthetic fixtures below. None comes from
running the current code. Where the spec leaves an outcome open, it is listed under "Gaps", not invented.

## Conventions for every scenario
- **Environment.** A `tmp_path` library and database only. Ledger tests use `Store` and `Ledger` as in
  `tests/test_imports.py`. Record tests go through the real extraction service:
  - capture into the Inbox and read with the real PDF reader (`VisionConfig()`, no vision model);
  - then `ExtractionService.run` with the `local_model` stub answering by `json_schema.name` (`tests/model_server.py`
    `by_schema`), as `tests/test_statement_forms.py` `read_statement` does.

  API tests use `create_app(…)` with `TestClient`. Browser tests are opt-in (`RUN_BROWSER_TESTS=1`) with the `served()`
  helper and Edge channel of `tests/test_transactions_v2_browser.py`. Never `P:\Finances`, `%LOCALAPPDATA%\HomeManager`
  or `P:\EvalCorpus`.
- **Synthetic PDFs** only: `tests/test_pdf.py` `make_pdf` with positioned items (`{"items": [(x, y, text), …]}`).
  Every native page also prints a words-only footer of at least 40 characters, so the reader never sends it to the
  vision model (account-import-pdf contract, "Enough native text").
- **P-checks.** Before a scenario's first checkpoint, the test asserts the reading has the intended shape: page methods,
  layout issues, and where the heading is. A failed P-check is a fixture or reader problem, never a reason to change an
  expected value.
- **C-net.** An autouse fixture blocks non-loopback sockets. Only the `local_model` stub on loopback is reachable.
- **Shared checks**
  - **C-unchanged:** the row counts of `accounts`, `statements`, `transactions`, `transaction_imports`,
    `financial_evidence_links`, `review_events`, `record_corrections`, `transaction_receipt_links`,
    `transaction_income_links`, `transaction_links`, `category_rules`, `recurring_obligations`,
    `record_shares`, `family_assignments` and `family_corrections` are unchanged.
  - **C-docs:** the sha256 of each fixture document's original, preserved blob, library file and every file in its
    reading folder is unchanged.
  - **C-money:** every new `transactions.amount_minor` has `typeof() = 'integer'`; the currency is `USD`.
  - **C-orphans(account a, statements S, transactions T):** for every table with a column referring to accounts,
    statements or transactions, there is no row holding `a`, an id in `S` or an id in `T`. The list of tables is read
    from `sqlite_master` and `pragma_foreign_key_list` at test time, so a new table can't be missed. Columns:
    `account_id`, `ledger_account_id`, `statement_id`, `transaction_id`, `from_transaction_id`, `to_transaction_id`. For
    `financial_evidence_links`, `review_events`, `record_corrections`, `record_shares`, `family_assignments` and
    `family_corrections`, the test uses `record_type` with `record_id`.
  - **C-visible(account):** the account is in `get_accounts`, `GET /api/finance/accounts`, Today's figures, the Add
    transaction and Import account lists, PDF import's preselection candidates, and Forecast's accounts.
    **C-hidden(account)** is the opposite on every one of those surfaces.
- **Test files (new)**
  - `tests/statement_account_fixtures.py`: the fixture builders below.
  - `tests/test_statement_accounts.py`: account confirmation, upgrade and delete (ledger and API).
  - `tests/test_statement_rebuild.py`: Record's rows from rebuilt tables.
  - `tests/test_statement_accounts_browser.py`: opt-in UI scenarios.
- **Cleanup.** pytest removes `tmp_path`. Browser tests close the browser and server through `served()`.

### Doubles
| Component | Real or double | Specification |
|---|---|---|
| PDF reader | Real | Every fixture is read by `pdf_reader` with `VisionConfig()`, except M's scanned page. |
| Vision model (M page 2 only) | `local_model` | Returns `{"full_text": "SCANNED PAGE\n09/27 SCANNED CAFE 7.00"}`. |
| Reasoning model (Record) | `local_model` by schema | `Classification`, `BankStatementSummary` or `CreditCardStatementSummary`, and `Transactions` answers given per fixture. The `Transactions` answers are deliberately wrong where a scenario says so. |
| Fault during delete (SC-11) | SQLite trigger | `CREATE TRIGGER fault BEFORE DELETE ON accounts BEGIN SELECT RAISE(ABORT,'injected fault'); END`, dropped before the retry. It fires on the last step whatever order the rows go in. |
| Old-schema library (SC-07) | Fixture | A library migrated up to the migration before this feature's, then filled through the public Ledger and extraction paths. Then the feature's migration runs. Where the current code can't produce a pre-feature state through public paths, the test makes it with the smallest direct SQL and says so: (a)'s statement and rows set to `verified`/`automatic`; (b)'s removed account re-inserted with its old id, still named by its run's `publication_json`. No expected value depends on how the state was made. |
| Reading without layout (SC-18 b) | Fixture | A saved reading with every page's `layout` set to `None`, as `tests/test_pdf_imports.py:2057` does. |
| Clock | Real | No assertion depends on today's date. |

### Fixtures
Column x-positions: Date 40, Description 110, Amount 380, Balance 470. For the Withdrawals | Deposits | Balance layout:
Date 40, Description 110, Withdrawals 330, Deposits 400, Balance 470. Rows are at y = 700 − 20 × row, with the heading on
row 0.

**S: the user's case, a 1-page savings statement.** Lines above the table:
- `SYNTH BANK`
- `SYNTH SAVINGS`
- `Account Number 000009000123456`
- `Statement period 09/01/2026 through 09/30/2026`
- `Beginning Balance 0.00`
- `Ending Balance 1,000.00`

The heading is `Date | Description | Amount | Balance`. The Balance cell is blank on s1.

| # | Date | Description | Amount | Balance | Expected `amount_minor` |
|---|---|---|---|---|---|
| s1 | 09/18 | SYNTH ACCTVERIFY PPD ID 1234567890 | 0.36 | | 36 |
| s2 | 09/18 | SYNTH ACCTVERIFY PPD ID 1234567890 | 0.02 | 0.38 | 2 |
| s3 | 09/18 | SYNTH ACCTVERIFY WEB ID 1234567890 | -0.38 | 0.00 | −38 |
| s4 | 09/20 | PAYROLL SYNTH WORKS | 1,500.00 | 1,500.00 | 150000 |
| s5 | 09/25 | TRANSFER TO CHECKING | -500.00 | 1,000.00 | −50000 |

Arithmetic: 0.00 + 0.36 + 0.02 − 0.38 + 1,500.00 − 500.00 = 1,000.00, the printed ending balance. All dates are
2026-09-xx (the year comes from the period).
- Summary stub: institution `SYNTH BANK`; account_type `savings` citing `SYNTH SAVINGS`; account_reference `3456`;
  the period; opening `0.00`; closing `1,000.00`; currency missing (USD from the setting, as today).
- **Wrong `Transactions` stub (S-bad)**, used wherever S is recorded: s1 as 0.36 credit; **s2 as `0.38` credit** (its
  balance); s3 as 0.38 debit; s4; s5; and **an extra row** `09/18 SYNTH ACCTVERIFY 0.38 credit` citing s2's line.
- **S-flag:** S with page 1 made to raise `overlapping_text` and `unsupported_text_rotation`: two words drawn at the
  same position, and one title word drawn rotated through `make_pdf`'s text matrix. P-check: those two codes are in
  `layout.issues`. If `make_pdf` can't produce one of them, use another real reader trigger from `pdf_layout.py` and
  record which one was used. Never inject the issue into a saved reading.
- **S2:** S printing account number `000009000127890`, so the last four is 7890. It is used to move a statement to
  another account (SC-05, SC-06).
- **T (SC-28, spec D6 Q8):** S-flag with one more row, t1, below s5: date `09/22`, description `SYNTH LONG DESCRIPTION`,
  amount `12.34`, Balance blank. Expected: 2026-09-22, `amount_minor` 1234 (money in), description
  `SYNTH LONG DESCRIPTION`. The description's words are placed one by one so that `SYNTH` is centred in the Description
  column, each gap is under 1.5 font sizes, and `12.34` starts just past the Description/Amount midpoint. P-check: on
  t1's visual row, `12.34` is in the same `PageView.texts` run as `SYNTH LONG DESCRIPTION`, its whole box lies inside
  the Amount column's span, and it is the only amount-shaped word centred in an amount column. One placement that
  passes, at 10 pt with S's columns: `SYNTH` at x 110, `LONG` at 155, `DESCRIPTION` at 194, `12.34` at 272. T isn't
  balanced (s1–s5 already reach the ending balance), so no scenario asserts its arithmetic.

**W: bank statement, Withdrawals | Deposits | Balance**, period 08/01/2026–08/31/2026, opening 1,000.00, closing
2,450.00.
- w1 `08/03/2026 RENT`: withdrawal 1,200.00, balance −200.00 → −120000.
- w2 `08/15/2026 PAYROLL`: deposit 2,500.00, balance 2,300.00 → 250000.
- w3 `08/20/2026 REFUND SHOP`: deposit 150.00, balance 2,450.00 → 15000.

**C: card statement, Date | Description | Amount**, charges positive. Lines above the table: `SYNTH CARD`,
`Card number XXXX7700`, `Statement period 12/15/2025 to 01/14/2026`, `Previous Balance 300.00`,
`New Balance 108.19`.
- c1 `12/20 BOOKSTORE 19.99` → 2025-12-20, −1999.
- c2 `01/03 PAYMENT THANK YOU -250.00` → 2026-01-03, +25000.
- c3 `01/05 GAS STATION 38.20` → 2026-01-05, −3820.

Card check: 300.00 − (−19.99 + 250.00 − 38.20) = 108.19. C0 is C with no statement period printed, and the summary stub
gives period start and end as missing.

**D: S plus a second table below it**, titled `DAILY ENDING BALANCE` and headed `Date | Amount`, with rows
`09/18 0.00`, `09/20 1,500.00` and `09/25 1,000.00`.

**X: rejections**, a 1-page Date | Description | Amount | Balance statement:
- x1 `09/02/2026 GOOD 10.00`: recorded, 1000.
- x2: the amount word straddles the Amount/Balance midpoint → rejected, "doesn't fit a column".
- x3: `REF 55.55` falls in the Amount span beside `5.00` → rejected, two amounts in one column.
- x4 `02/30/2026 BADDATE 1.00` → rejected, not a real date.
- x5 `09/05/2026 BADAMT 1.2.3` → rejected, unparseable amount.
- x6 `09/06/2026 EURO 4.00 EUR` → rejected, currency mismatch.

**Q: duplicates across sections.** Page 1 is a `CHECKS PAID` table (Date | Description | Amount) with
`09/10/2026 CHECK 1001 -75.00`. Page 2 is the main transactions table, with the same line among others.

**M: mixed.** Page 1 is S's page. Page 2 is scanned (`None` in `make_pdf`), read once with the vision stub.

**Accounts and records for delete (SC-08)**, built through public paths:
- Account **A**: confirmed, USD checking, SYNTH BANK …4821.
- 2 statements recorded into A: W, and W′ for 09/2026, made from W with its dates moved one month.
- 1 CSV import of 3 rows into A, dated 10/2026 so none duplicates a statement row. A then holds 9 transactions: 3 from
  W, 3 from W′ and 3 from the import.
- 1 receipt matched (verified link) to w1.
- 1 transfer link between w1 and a transaction in account B.
- 1 recurring payment and 1 recurring bill with `account_id = A` (two `recurring_obligations` rows, kinds `subscription` and `bill`; there is no `bills` table, spec N1).
- 1 category rule for A.
- 1 investment account with `ledger_account_id = A`.
- Account **B**, confirmed, holding 3 transactions, is the control and must be untouched.

---

## Journey J1: a statement's account waits for Confirm
SC-01, SC-02, SC-03, SC-05. Requirement IDs: FR-01 – FR-07.
Environment: API plus Record through the service. Doubles: the reasoning stub (S summary, S-bad rows).
Initial state: no accounts. S is captured and read.
1. **(SC-01)** Record S →
   - 1 account exists: savings, `SYNTH BANK savings 3456`, **unconfirmed**. C-hidden(it).
   - The statement is `review_status = 'proposed'` (not `verified`/`automatic`), although the rows it records reconcile.
   - `GET /api/finance/records/statement/{id}` shows Confirm and Reject, and the text
     `New account: SYNTH BANK savings 3456 — added to Accounts when you confirm this statement.`
   - Spending and money-in for 2026-09 are 0, the same as before Record.
2. **(SC-02)** Confirm the statement (`POST …/review {"status": "verified"}`) →
   - The account is confirmed. C-visible(it) in the same response's state.
   - The statement is `verified`, `review_source = 'user'`.
3. **(SC-03, FR-07)** Undo (the toast's undo body) → the account is unconfirmed again, and C-hidden(it).
4. **(SC-05, FR-06)** Record S2, the same document version re-read with the S2 summary stub (account_reference `7890`)
   →
   - Exactly 1 account remains: `…7890`, unconfirmed.
   - The `…3456` account is gone. C-orphans(`…3456` id, {}, {}) holds.
   - The move and the removal are one transaction: with a fault trigger on `DELETE FROM accounts`, Record fails and the
     account and statement are as after step 3.

Expected final state: 1 account (…7890, unconfirmed), 1 statement, 5 transactions with amounts 36, 2, −38, 150000,
−50000 (from the rebuild, not the S-bad stub). C-docs holds.
Variant J1-a (**SC-06**, amended E2): confirm at step 2 and skip step 3. Step 4's re-read is `kept_reviewed` (FR-26): exactly 1
account remains, …3456, confirmed, with its statement and 5 rows unchanged (snapshot equal), and no …7890 account exists.
Variant J1-b: a second statement of the same account, recorded after it was confirmed, with no issues, is `verified`,
`automatic` (FR-04's second half).
Evidence: `pytest tests/test_statement_accounts.py -k journey_j1`

## SC-04: other actions that confirm, and one that doesn't
Requirement IDs: FR-03
Each from a fresh unconfirmed account made by recording S:
- Reconcile its statement (`POST /api/finance/statements/{id}/reconcile`) → confirmed.
- Import a 2-row CSV into it → confirmed. The Import dialog's account list didn't offer it (FR-02), so the test imports
  through the API with `account_id`.
- PDF-import S into it by `account_id` → confirmed.
- Reject its statement → still unconfirmed, and C-hidden.
- An account made with `POST /api/finance/accounts` → confirmed at once.
Evidence: `pytest tests/test_statement_accounts.py -k sc04`

## SC-07: upgrade sorts existing accounts
Requirement IDs: FR-08
Initial state: old-schema library with:
- (a) an account whose only statement is `verified`/`automatic`, `reconciliation = 'awaiting'`;
- (b) an account left with no rows by a re-read;
- (c) an account with a CSV `transaction_imports` row;
- (d) an account made by hand with no rows;
- (e) an account whose statement was confirmed by the user;
- (f) an account whose statement was reconciled.

Actions: run the migration, then run it again.
- After the first run: (a) is unconfirmed; (b) is removed, C-orphans holds for it; (c), (d), (e) and (f) are confirmed.
- The second run changes nothing (row-by-row equal).

Evidence: `pytest tests/test_statement_accounts.py -k sc07`

## Journey J2: delete an account
SC-08, SC-09, SC-10, SC-11. Requirement IDs: FR-09 – FR-15.
Initial state: the SC-08 fixture.
1. **(SC-08, FR-10)** Open Delete for A →
   - The counts shown equal the database counts for A: statements 2; transactions 9; import records 1;
     matched receipts 1; transfer links 1; recurring payments and bills 2; category rules 1.
   - The text says the documents stay and can be recorded or imported again, and that this can't be undone.
   - Cancel → C-unchanged and C-docs.
2. **(SC-10, FR-14)** Open Delete, then record another statement into A (W with its dates moved two months), then
   Delete with the counts the dialog showed → 4xx
   `This account changed since you opened Delete; check the counts again.` C-unchanged since the recording.
3. **(SC-11, FR-15)** Open Delete again with the fault trigger installed, then Delete → fails with no raw traceback.
   C-unchanged and C-docs.
4. Drop the trigger, then Delete (counts current) →
   - C-orphans(A, A's statements, A's transactions) holds.
   - B's rows are unchanged (snapshot equal).
   - The recurring payment and the bill still exist with `account_id` NULL (OD-4).
   - The investment account still exists with `ledger_account_id` NULL and its values unchanged.
5. **(SC-09, FR-12)** Money →
   - The matched receipt counts standalone: it is in Spending once, on its purchase date.
   - Each affected month's spending equals (the value before − the counted amounts of A's deleted transactions + the
     newly standalone receipt), computed from the snapshot taken before step 4.
6. **(FR-13)** Documents →
   - C-docs holds.
   - W's document shows no record, and its next step is Record.
   - The CSV's next step is Import.
   - Recording W again creates a new unconfirmed account (FR-01).

Evidence: `pytest tests/test_statement_accounts.py -k journey_j2`

## SC-12: deleting an unconfirmed account
Requirement IDs: FR-09, FR-11; OD-5
From a fresh S recording (unconfirmed account), call Delete with its counts → it is removed with its statement and 5
rows, and C-orphans holds. The browser part is in SC-25.
Evidence: `pytest tests/test_statement_accounts.py -k sc12`

## SC-22: delete reaches the family hub
Requirement IDs: FR-28
Initial state: two profiles in a family. The member's statement in A was shared to the family (the public share path
used in `tests/test_family_routing.py`). P-check: `record_shares`/`family_assignments` rows exist for it.
1. Open Delete → the dialog counts the shared copies.
2. Delete → C-orphans covers `record_shares`, `family_assignments` and `family_corrections`. The family view lists none
   of A's records.

Gap G1: which family rows exist is U1, resolved by the plan. This scenario asserts only "no family row refers to them".
Evidence: `pytest tests/test_statement_accounts.py -k sc22`

---

## SC-13: the user's case, from the printed columns
Requirement IDs: FR-16, FR-17, FR-20, FR-22
Fixture: S-flag. Stub: S-bad.
P-check: page 1 is `embedded_text`, `native_page` is false, and the issues include `overlapping_text` and
`unsupported_text_rotation`.
Record →
- The transactions are exactly s1–s5 in printed order: dates 2026-09-18 ×3, 2026-09-20, 2026-09-25; amounts 36, 2, −38,
  150000, −50000. **No row has 38 or 0** (s2's and s3's balances).
- Two stub rows match no rebuilt row: the misread s2 and the extra row, both `09/18 0.38` money in. Each gets one
  note on the record quoting it (FR-20; gap G2 covers the wording), in `notes`, not in `issues`. The stub's s1, s3, s4 and s5 match rebuilt rows and add
  no note.
- The statement is `needs_review` with `Page 1 PDF layout needs review: …` (FR-22).
- C-money holds.

Evidence: `pytest tests/test_statement_rebuild.py -k sc13`

## SC-14: debit/credit columns and the card sign
Requirement IDs: FR-17, FR-18
- W (Model stub: rows with every amount as its Balance cell) → −120000, 250000, 15000. No balance value is recorded.
- C with period 12/15/2025–01/14/2026 → −1999, 25000, −3820.

Evidence: `pytest tests/test_statement_rebuild.py -k sc14`

## SC-15: the year from the printed period
Requirement IDs: FR-19
- C → 2025-12-20, 2026-01-03, 2026-01-05.
- C0 (no period) → no transactions are recorded. Each of c1–c3 is in `issues` with page and row and a reason naming the
  missing year. The status is `needs_review`.
- S's rows (year-less) → 2026-09-xx.

Evidence: `pytest tests/test_statement_rebuild.py -k sc15`

## SC-16: the model can't change rebuilt rows
Requirement IDs: FR-20
S (not flagged) with S-bad → the same 5 rows as SC-13, and the same two notes. The status follows the other checks
(it reconciles). A rebuilt row the model didn't list (the stub with s4 removed) is still recorded.
Evidence: `pytest tests/test_statement_rebuild.py -k sc16`

## SC-17: rejected rows
Requirement IDs: FR-21
X → only x1 recorded (1000). x2–x6 are each in `issues` with `page 1`, its row number and its reason, in the words of
PDF import's rejection reasons. The status is `needs_review`.
Evidence: `pytest tests/test_statement_rebuild.py -k sc17`

## SC-18: pages and readings without rebuilt rows
Requirement IDs: FR-23
- (a) M → page 1 rows from the rebuild (s1–s5). The page 2 row comes from the stubbed model (`SCANNED CAFE`, 700
  money out). No rebuilt row cites page 2.
- (b) S's reading with layout removed → rows exactly as the stubbed model gives them under today's checks. The note is
  `Read this document again to take its rows from the printed columns.`

Evidence: `pytest tests/test_statement_rebuild.py -k sc18`

## SC-19: evidence of a rebuilt row
Requirement IDs: FR-24
After SC-16, `GET /api/provenance/transaction/{s2}` names S's file, page 1, and s2's line ids and word ids. It doesn't
offer only a bare row number. The browser part is in SC-26.
Evidence: `pytest tests/test_statement_rebuild.py -k sc19`

## SC-20: checks and determinism
Requirement IDs: FR-25, FR-26
- S, Record → no `Statement arithmetic does not reconcile` issue.
- Extract again → identical rows, ids and amounts. With S's statement confirmed by the user first, Extract again leaves
  it untouched (`kept_reviewed`).
- Network blocked (C-net), no vision model → the rebuild step makes no request (`local_model["requests"]` grows only by
  the stubbed reasoning calls).

Evidence: `pytest tests/test_statement_rebuild.py -k sc20`

## SC-21: a daily balance table is never transactions
Requirement IDs: FR-27
D → only s1–s5 are recorded. No transaction has the amount 150000 on 2026-09-20 twice, and none comes from the
`DAILY ENDING BALANCE` rows.
Variant: the daily table on page 2 by itself, after S's page 1 → it starts no continuation; page 2 gives no rows.
Variant D-flag: D drawn on S-flag's page (no native table) → only s1–s5 are recorded, and no issue names a daily row.
Evidence: `pytest tests/test_statement_rebuild.py -k sc21`

## SC-27: a number that ends a description (E1)
Requirement IDs: FR-30
S-flag, Record (S-bad stub) → s1–s3 are recorded as 36, 2, −38, with descriptions `SYNTH ACCTVERIFY PPD ID 1234567890`,
`SYNTH ACCTVERIFY PPD ID 1234567890` and `SYNTH ACCTVERIFY WEB ID 1234567890`. None is rejected.
PDF import of the same reading (preview by `account_id`) → the same 5 rows parse, none rejected.
Regression: `account-import-pdf` 7-e (`12345` printed apart from `B1 REF` in the Withdrawals span) is still rejected,
and X's x3 still is.
Evidence: `pytest tests/test_statement_rebuild.py -k sc27 tests/test_pdf_imports.py`

## SC-28: a description joined to its only amount (spec D6 Q8)
Requirement IDs: FR-30
Fixture: T. Stub: S-bad, which doesn't list t1.
P-check: T's (above), and S-flag's page issues.
- Record →
  - The transactions are s1–s5 as in SC-27 (36, 2, −38, 150000, −50000, with their full descriptions), then t1:
    2026-09-22, 1234, `SYNTH LONG DESCRIPTION`. t1 is recorded though the model didn't list it (FR-20).
  - No issue names t1.
- PDF import of the same reading (preview by `account_id`) → the same 6 rows parse with those amounts and descriptions,
  none rejected. t1's amount cell is `12.34`, and its description holds no number.
- Regression: S-flag's `1234567890` stays in the description of s1–s3 (it crosses into the Amount column, and it isn't
  the row's only amount), and `account-import-pdf` 7-e and X's x3 are still rejected.

Evidence: `pytest tests/test_statement_rebuild.py -k sc28 tests/test_pdf_imports.py`

## SC-23: the same row in two sections
Requirement IDs: FR-29
Q → both CHECK 1001 rows are recorded (ordinals 0 and 1). The statement is `needs_review` with a note naming page 1 and
page 2.
Evidence: `pytest tests/test_statement_rebuild.py -k sc23`

---

## Browser scenarios (`tests/test_statement_accounts_browser.py`, opt-in)
Entry points from the UI source:
- **Accounts tab:** `accounts_v2.js` `renderAccountsV2`. Rows come from `get_accounts`, with Rename on each row. Delete
  sits beside it, and the "Waiting for confirm" group is new.
- **Document page:** `document_v2.js`, with the decision area (`doc2Decision`, Confirm/Reject from `trace.js`
  `confirmCorrect`) and the record's fields.
- **Today:** the cash and net worth figures.

**SC-24 (FR-02, FR-03, FR-05):**
1. With S recorded, the Accounts tab shows no account in its groups, and "Waiting for confirm" lists SYNTH BANK
   savings 3456, collapsed.
2. S's document page shows the "New account: …" text and Confirm.
3. Confirm → the account moves into the Savings group, and Today's cash includes its 1,000.00 balance.

**SC-25 (FR-09, FR-10, OD-5):**
1. From "Waiting for confirm", open Delete on the account → the dialog shows the counts and the documents-stay text.
   Focus is inside the dialog.
2. Cancel → focus returns to the opener.
3. Delete → the account is gone from the page after reload.
4. The same from S's document page.
5. All of this works by keyboard only.

**SC-26 (FR-24):** open s2's source → page 1 opens with s2's words highlighted.

Throughout: no `pageerror` events and no horizontal overflow.
Evidence: `RUN_BROWSER_TESTS=1 pytest tests/test_statement_accounts_browser.py`

---

## Traceability
| FR | Scenarios | Command |
|---|---|---|
| FR-01, FR-02 | J1 step 1; SC-04; SC-24 | `pytest tests/test_statement_accounts.py -k "journey_j1 or sc04"` |
| FR-03 | J1 step 2; SC-04; SC-24 | same |
| FR-04, FR-05 | J1 step 1, J1-b; SC-24 | `-k journey_j1` |
| FR-06 | J1 step 4, J1-a | `-k journey_j1` |
| FR-07 | J1 step 3 | `-k journey_j1` |
| FR-08 | SC-07 | `-k sc07` |
| FR-09 – FR-15 | J2; SC-12; SC-25 | `-k "journey_j2 or sc12"`, browser |
| FR-16, FR-17 | SC-13; SC-14 | `pytest tests/test_statement_rebuild.py -k "sc13 or sc14"` |
| FR-18 | SC-14 | `-k sc14` |
| FR-19 | SC-15 | `-k sc15` |
| FR-20 | SC-13; SC-16 | `-k "sc13 or sc16"` |
| FR-21 | SC-17 | `-k sc17` |
| FR-22 | SC-13 | `-k sc13` |
| FR-23 | SC-18 | `-k sc18` |
| FR-24 | SC-19; SC-26 | `-k sc19`, browser |
| FR-25, FR-26 | SC-20 | `-k sc20` |
| FR-27 | SC-21 | `-k sc21` |
| FR-28 | SC-22 | `pytest tests/test_statement_accounts.py -k sc22` |
| FR-29 | SC-23 | `pytest tests/test_statement_rebuild.py -k sc23` |
| FR-30 | SC-27; SC-28; SC-13 | `pytest tests/test_statement_rebuild.py -k "sc27 or sc28 or sc13" tests/test_pdf_imports.py` |

Regression run, touched components only:
```
python -m pytest tests/test_statement_accounts.py tests/test_statement_rebuild.py tests/test_statement_forms.py \
  tests/test_pdf_imports.py tests/test_imports.py tests/test_extraction.py tests/test_layout_consumers.py \
  tests/test_family_routing.py tests/test_reconcile_tools.py tests/test_finance.py tests/test_provenance.py -q
RUN_BROWSER_TESTS=1 python -m pytest tests/test_statement_accounts_browser.py tests/test_document_v2_browser.py -q
```

## Gaps (flagged, not invented)
- **G1 (FR-28).** Which family tables hold copies of a member's statements (U1). Only "nothing refers to them" is
  asserted.
- **G2 (FR-20).** The exact wording of the "model row matches no rebuilt row" note isn't given by the spec. It is
  asserted to quote the model row's date, description and amount.
- **G3 (FR-12).** The spec doesn't say whether a matched pay stub, once its deposit is deleted, appears in the same
  month: it counts on its pay date, as STANDALONE_INCOME already says. Asserted only for the receipt (SC-09); pay stubs
  by the same rule, with no separate month assertion.
- **G4 (FR-10).** "Counts the dialog showed" in FR-14: how the request carries them is the plan's choice. The contract
  asserts only the refusal when they differ.
- **G5 (FR-30).** A word joined to the description that is the row's only amount but crosses an amount column's edge
  is description text under FR-30, so the row has no amount. The spec doesn't say how that row is shown (the plan's
  P18 rejects it with a reason). No scenario asserts it.
