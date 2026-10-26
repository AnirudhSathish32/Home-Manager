# Statement accounts: confirm before adding, delete, and rows from the rebuilt table
Feature: statement-accounts

<!-- Approval state lives in approvals/<slug>.json and is bound to this file's content hash.
     Do not add a Status line: changing it would change the hash. Check with gate.py. -->

Amends: `specs/document-forms/spec.md` (statement extraction / **Record**) where it creates accounts and reads statement
rows, and reuses the row rules of `specs/account-import-pdf/spec.md` FR-07 and FR-08 without changing that feature.
Baseline for the account parts: the built behavior cited below (no earlier spec covers account creation or deletion).

## Decisions already made (user, 2026-10-26; not to be re-asked)
- **D1 Accounts wait for Confirm.** An account Record creates is kept but marked unconfirmed. It stays off Accounts,
  Today and totals until a statement in it is confirmed. A re-read that moves the statement removes an unconfirmed
  account it leaves empty.
- **D2 Delete with its records.** Delete on the Accounts tab removes the account and every statement, transaction and
  import record in it, after a confirmation showing the counts. Documents stay in the library and can be recorded
  again.
- **D3 Columns decide.** For a statement PDF, Record rebuilds the transactions table from the page layout the way PDF
  import does. Each transaction's date and amount come from its rebuilt row's cells, and Balance is never an amount.
  The model doesn't decide those values. Rows the rebuild can't place go to review. Scanned pages keep the model's
  reading.

- **D4 Open decisions settled** (user, 2026-10-26, "defaults ok"): OD-1 through OD-5 take their recommended defaults,
  and risks R1, R2 and R3 are accepted as FR-27 – FR-29. R4 and R5 need no requirement.

Background (user report): one Chase savings statement, read twice, left two accounts (last four 1234, then 3456 after
the last-four fix, both from the same statement). A row took its running balance 0.38 as its amount instead of 0.02.

## Goal / users / scope / non-goals
**Goal.** Reading a statement never adds accounts you haven't confirmed. You can remove an account you don't want,
with everything recorded in it. A statement's amounts come from its printed columns, not from the model's choice of
number on a line.

**Users.** The household user who records statements and keeps the Accounts tab.

**In scope.** Unconfirmed accounts (FR-01 – FR-08). Deleting an account (FR-09 – FR-15). Record's rows from the rebuilt
table (FR-16 – FR-27, FR-29). The family hub's copies on delete (FR-28).

**Non-goals.**
- Merging two accounts into one, or moving records between accounts.
- Changing an account's type or currency by hand.
- Undoing a delete. Recording the documents again is the way back (OD-2).
- Changing PDF import (`account-import-pdf`), CSV/XLSX import, reconciliation rules, receipts or pay stubs.
- Rebuilding tables for photos or scanned pages, or for investment, loan or tax documents.
- Any model or network call added by this feature.

## Existing behavior (verified paths, assumptions, unknowns)
All paths are under `src/home_manager/` unless noted.

**Accounts**
- Record creates the account while it publishes. `Ledger.publish_statement` (`finance/ledger.py:1065–1115`) finds the
  account by institution, type group and last four, or creates it with `account_in` (`ledger.py:402`).
- Every statement and transaction needs an account: `statements.account_id` and `transactions.account_id` are
  `NOT NULL REFERENCES accounts(id)` (`library/migrations/050_strict_tables.sql`, tables `statements_new` and
  `transactions_new`).
- Other tables refer to accounts:
  - `bills`, `category_rules`, `recurring_obligations` and `transaction_imports` have `account_id`.
  - `tax_rules.account_id` is `ON DELETE CASCADE`.
  - `investment_accounts.ledger_account_id` is `ON DELETE SET NULL`.
- A re-read writes over an undecided statement (`_upsert`, `ledger.py:594–609`). The account comes from the new
  reading, so a changed last four moves the statement to another account. Earlier rows that no one worked on are
  removed (`ledger.py:1095–1108`), so the old account is left empty. Nothing removes empty accounts.
- A statement with no issues is published `verified` with `review_source='automatic'`. Such a statement shows no
  Confirm button, only "Not right? Reject" (`app/static/trace.js:536, 559–566`). Only `Ledger.review` sets
  `review_source='user'` (`ledger.py:1509–1533`).
- The Accounts tab lists every account (`FinanceTools.get_accounts`, `finance/tools.py:312–321`, via
  `Ledger.accounts`, `ledger.py:503`). An account's balance comes from its latest statement that isn't rejected, even
  an unverified one (`tools.py:323–337`).
- Statement rows aren't counted until the statement is reconciled (`HELD`, `ledger.py:49`).
- Accounts have no delete path: no `DELETE FROM accounts` anywhere in `src/`. The Accounts tab can only rename
  (`PUT /api/finance/accounts/{id}`, `app/api.py:941`; `accounts_v2.js:95`).

**Statement rows**
- The model lists the rows (`documents/extraction.py` `read_form`, `ROWS`, `STATEMENT_ROWS`). Code checks each quote
  and amount against its cited line. On native tables, cells are anchored by heading (`native_values.anchor_rows`).
- Pages flagged `overlapping_text`, `unsupported_text_rotation`, `unicode_mapping` or `degenerate_glyph` aren't
  "native" for the model (`documents/layout_context.native_page`). Their raw text lines are sent instead, with no
  columns. The user's statement had `overlapping_text` and `unsupported_text_rotation` on page 1.
- PDF import already rebuilds rows from the saved layout of every `embedded_text` page (`finance/pdf_import.py`
  `PageView`, `structure`, `analyze`). It finds the transactions heading, rebuilt and continuation tables and
  below-table rows. It reads dates and amounts exactly, never takes Balance as an amount, and rejects rows with
  reasons (`ImportRow.rejected`). It needs a year for year-less dates, and a sign convention for a single Amount
  column. Its rows cite page, table, row, cell, line and word ids.
- Readings saved before layouts existed can't be rebuilt (`pdf_import.NO_LAYOUT`).

**Assumptions**
- A1: Bank and card PDFs print a transactions heading (Date plus Amount, or Debit/Credit) that `is_heading` recognizes.
  The user's Chase statement prints Date | Description | Amount | Balance (inferred from the report; not verified).
- A2: The printed statement period is read by Record as today (`period_start`, `period_end`) and is reliable enough to
  supply the year (OD-3).

**Unknowns**
- U1: Whether the family hub (`finance/family_routing.py`) holds copies of a member's account or statements that a
  delete must also reach. To check in the plan (R1).
- U2: `gate.py` isn't in this repository. Approval is recorded with the user's own tooling.

## Functional requirements
Terms:
- **Unconfirmed account:** an account Record created that no confirming action (FR-03) has reached.
- **Rebuilt row:** a row PDF import's rules produce from a page's saved layout (`account-import-pdf` FR-08): a native
  transactions table row, a rebuilt-table row, a continuation-page row or a below-table row.
- **Rebuilt page:** an `embedded_text` page that has at least one rebuilt row or rejected rebuilt row.

| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| **Unconfirmed accounts** | | |
| FR-01 | An account Record creates for a statement starts unconfirmed. Accounts you create yourself (Accounts, the import dialog's New account, PDF import's new account) start confirmed. | After recording a statement into a new account, the account exists with its statement and rows, and is unconfirmed. An account made through `POST /api/finance/accounts` is confirmed. |
| FR-02 | Unconfirmed accounts are left out of: the Accounts tab; Today's figures (cash, net worth, balances); Forecast and What If; account pickers (Add transaction, the Import dialog's account list); PDF import's last-four preselection; and the assistant's `get_accounts`. Their rows are already not counted (`HELD`). | With one confirmed and one unconfirmed account, every listed surface shows only the confirmed one. Spending and money-in totals are the same as with no unconfirmed account. |
| FR-03 | An account becomes confirmed when you confirm a statement in it (review to `verified` by you), reconcile a statement in it, or import CSV, XLSX or PDF transactions into it. Rejecting a statement doesn't confirm its account. | Confirming the statement makes the account appear on Accounts and Today in the same response. Rejecting leaves it unconfirmed. |
| FR-04 | The first statement into an unconfirmed account always waits for your Confirm. It is published `proposed`, with Confirm and Reject offered, even when it has no issues. Statements into a confirmed account keep today's automatic check. | A clean statement (no issues) into a new account shows Confirm on its document page and in Review. The same statement recorded again into a confirmed account is `verified`, `automatic`. |
| FR-05 | The statement's record says where it goes: "New account: *name* — added to Accounts when you confirm this statement." | Shown on the document page and in Review for a statement whose account is unconfirmed. |
| FR-06 | When a re-read records a statement into a different account, an unconfirmed account it leaves with no statements, transactions or import records is removed, in the same database transaction. A confirmed account is never removed automatically. | Record K, then record it again with a different last four: one account exists, the new one. The same sequence with the first account confirmed leaves both. |
| FR-07 | Undoing a Confirm (the toast's Undo) returns the account to unconfirmed when nothing else confirmed it (OD-1). | Confirm, then Undo: the account leaves Accounts again. |
| FR-08 | Existing data on upgrade. An account is confirmed if it has an import record, or a statement you reviewed (`review_source='user'`) or reconciled, or if you created it (no statement and no extraction rows at all). Other accounts become unconfirmed. An unconfirmed account with no statements, transactions or import records is removed. | Fixture with (a) an account holding only an automatically checked statement, (b) an empty account left by a re-read, (c) an account with a CSV import, (d) an account made by hand: after upgrade (a) is unconfirmed, (b) is gone, and (c) and (d) are confirmed. |
| **Delete an account** | | |
| FR-09 | Each account on the Accounts tab offers **Delete…**. | The action is in the account's actions, keyboard reachable, with an accessible name naming the account. |
| FR-10 | Delete first shows what will go: the account's name and the counts of statements, transactions and import records. It also counts receipts and pay stubs linked to its transactions (these go back to counting on their own), transfer links, recurring payments and bills tied to it, and category rules for it. It says the documents stay in the library and can be recorded or imported again, and that this can't be undone. Delete needs an explicit second click. | The dialog's numbers equal the database counts for a fixture account. Cancel changes nothing. |
| FR-11 | Deleting removes, in one database transaction: the account; its statements and transactions; its import records; and everything that belongs only to those statements and transactions (evidence links, corrections, review history, tags, category splits, receipt and pay-stub links, transfer links). Category rules and tax rules for the account are removed. Recurring payments and bills keep their row with no account (OD-4). An investment account linked to it keeps its own values with the link cleared. | After delete, no row anywhere refers to the account id or to the ids of its statements or transactions (checked table by table). Rows of other accounts are unchanged. |
| FR-12 | Money after a delete. Receipts and pay stubs that were matched to deleted transactions count on their own again, as if never matched (`STANDALONE_RECEIPT`, `STANDALONE_INCOME`). Totals drop by exactly what the deleted transactions counted. | Fixture: a receipt matched to a deleted transaction is in Spending once, standalone, after the delete. The month's totals equal (before − deleted transactions' counted amounts + newly standalone receipts and pay stubs). |
| FR-13 | Documents are untouched: originals, preserved blobs, readings and library files stay byte-identical. A statement document shows no record and offers **Record** again. A CSV or PDF that was imported offers **Import** again. | Hashes of the document files and reading folder are unchanged. The document's next step is Record (statement) or Import (import file). |
| FR-14 | Delete is refused, changing nothing, when the account changed after the dialog opened (a statement recorded or an import into it in between). The message is "This account changed since you opened Delete; check the counts again." | Open the dialog, record another statement into the account, then Delete: 4xx with that message, and all rows remain. |
| FR-15 | Delete works for confirmed and unconfirmed accounts alike, and is atomic: a failure part way leaves everything as it was, and the delete can be retried. | Fault injected on the last delete step: every row is still there; the retry succeeds. |
| **Rows from the rebuilt table (Record)** | | |
| FR-16 | When Record reads a bank or credit-card statement PDF, it rebuilds the rows of every `embedded_text` page by PDF import's rules (`account-import-pdf` FR-08), whether or not the page counts as native for the model (a page with overlapping or rotated text included). | The user's case as a fixture: a page flagged `overlapping_text` and `unsupported_text_rotation`, headed Date \| Description \| Amount \| Balance, gets rebuilt rows. |
| FR-17 | Each rebuilt row's transaction takes these values from its cells. The posted date comes from the Date cell. The description is the Description cell as printed (up to 500 characters). The amount is exact, in minor units, from the Amount cell or the one filled Withdrawals/Debit or Deposits/Credit cell. The Balance column (`pdf_import.BALANCE_NAMES`) is never an amount. | `09/18 … 0.02 0.38` under Amount \| Balance records 0.02, never 0.38. A Debit/Credit statement records each row's filled cell. |
| FR-18 | Direction. Separate Debit and Credit columns decide it. With a single Amount column, a bank statement reads negative as money out, and a card statement reads positive as money out (charges). The rule is not a choice in Record. | A card statement whose charges print positive records them as money out. A bank statement printing `-500.00` records money out. |
| FR-19 | Year. A four-digit year is read as printed. A date with no year, or a two-digit year, takes its year from the statement's printed period (OD-3). A month earlier than the period's start month falls in the period's end year, so a December–January statement works. With no printed period, such rows aren't recorded and the statement goes to review, naming the rows. | Period 2025-12-15 to 2026-01-14: `12/20` gives 2025-12-20 and `01/03` gives 2026-01-03. No period read: the rows are listed in review and not recorded. |
| FR-20 | On a rebuilt page, the transactions are the rebuilt rows. The model's rows citing that page don't change any rebuilt row's date, amount or direction, and add no rows there. A model row on that page that matches no rebuilt row (by date and amount) becomes a review note quoting it. A rebuilt row the model didn't list is still recorded. | Stubbed model answers with the balance as an amount and an extra row: the record holds exactly the rebuilt rows, plus one review note for the extra row. |
| FR-21 | Rows the rebuild rejects (date or amount outside every column, a word straddling two columns, two amounts in one column, both debit and credit, an impossible date, an unparseable amount, a currency differing from the statement's) are not recorded. Each becomes a review issue with page, row and reason. The statement needs review. | A fixture with one row of each kind records the good rows. Each rejected row is in `issues` with its page and reason, and the status is `needs_review`. |
| FR-22 | A rebuilt page with a layout issue other than `unresolved_columns` (overlapping or rotated text, glyphs outside the page, and so on) still gives its rows. The statement needs review, naming the page and issue, as the page note does today. | The flagged-page fixture records its rows, and the statement is `needs_review` with "Page 1 PDF layout needs review: …". |
| FR-23 | Pages without rebuilt rows keep today's reading: the model's rows with the existing checks, including the missed-row check. That covers scanned (`vision_model`) pages, pages with no transactions heading that continue none, and readings saved before layouts existed. A reading with no layout adds the note "Read this document again to take its rows from the printed columns." | A 2-page PDF with page 2 scanned: page 1 rows come from the rebuild, and page 2 rows from the stubbed model. An old reading without layout records as today, with the note. |
| FR-24 | Evidence. Each rebuilt-row transaction cites its document, blob hash, page, line ids and word ids (cell ids for a native table row). Its source opens the page with those words highlighted. | `GET /api/provenance/transaction/{id}` for a rebuilt row names its page and line and word ids. The document page highlights them. |
| FR-25 | The statement's checks are unchanged and now run on the rebuilt amounts: opening + transactions = closing (bank), previous − transactions = new balance (card), and the printed-summary check. | The user's case fixture (0.36, 0.02 with balance 0.38, −0.38) reconciles when the printed balances agree, with no "Rows may be missing" issue. |
| FR-27 | A table on a statement whose title line (the visual row directly above its heading) or heading names a balance (`pdf_import.BALANCE_NAMES`, or "daily ending balance", "daily balance") is not a transactions table for Record. Its rows are never recorded, and it starts no continuation chain (R2, accepted). | A page with the transactions table and a "DAILY ENDING BALANCE" table headed Date \| Amount records only the transactions table's rows. |
| FR-28 | Delete reaches the family hub. Family copies of the account's statements and transactions (`finance/family_routing.py`) are removed with it, and the dialog counts them (R1, accepted; U1 is resolved in the plan). | After deleting an account whose statement was shared to the family, no family row refers to it, and the dialog showed the shared count. |
| FR-29 | Two rebuilt rows with the same date, amount and description on different pages or in different tables get a review note naming both places. Both are recorded, as their ordinals keep them apart (R3, accepted). | A statement printing a check in "Checks paid" and again in the main list records both rows, and the statement is `needs_review` with the note. |
| FR-26 | Rebuilding is deterministic and local: the same reading gives the same rows. No model or network call is added. Readings made before this feature are rebuilt on **Extract again**. Statements you already confirmed or rejected aren't rewritten (as today). | Extract again twice gives identical rows. With network blocked and no model configured, the rebuild step itself succeeds (the model steps fail as today). |

## Invariants, privacy, security and data retention
- **Money is exact.** Amounts are integer minor units from `core/money.to_minor`. Balance is never an amount. A sign is
  never guessed beyond FR-18's fixed rule for the statement's type.
- **The model proposes, the code decides.** On rebuilt pages the model decides no date, amount or direction.
- **One transaction, one record.** Fingerprints are unchanged (account, date, amount, currency, ordinal), so re-reading
  and imports still find duplicates.
- **Evidence is preserved.** Delete removes ledger rows only. Originals, blobs, readings and library files are never
  changed or removed by this feature.
- **Data leaving the machine:** none.
- **Retention.** A deleted account and its rows are gone from the database (no Trash for ledger rows). The way back is
  recording or importing the documents again (OD-2).
- **Privacy.** Account numbers stay last-four only, as today. Counts and names in the Delete dialog show nothing beyond
  what Accounts already shows.

## Errors, recovery, duplicates, restart behavior
- **Delete** is one transaction. A crash before commit leaves everything. The stale-counts check (FR-14) prevents
  deleting rows the user didn't see.
- **Re-read moving a statement** (FR-06): the removal of the empty unconfirmed account is in the same transaction as
  the statement's move, so a crash leaves either the old state or the new one.
- **Confirm and Undo** (FR-03, FR-07) are recorded in review history as today. Confirmation status follows them
  without separate state that could drift (how is the plan's choice).
- **Upgrade** (FR-08) is one migration step and repeatable: running it again changes nothing.
- **Rebuild failures** (a malformed saved layout) fall back to the model's reading for that page, with a review note,
  and never fail the whole Record.

## Nondeterministic outputs and how they are verified
- The rebuild is deterministic. Tests assert exact rows, dates, amounts, directions and issues from synthetic PDFs built
  with `tests/test_pdf.py` `make_pdf`.
- Model answers are stubbed by schema name (`tests/model_server.py` `by_schema`). Tests assert that a stubbed wrong
  model row (balance as amount, an extra row) never changes the recorded rows (FR-20).
- Ids and timestamps are asserted as present and well formed only.

## Scenarios (expand into test-contract.md with design-tests for stateful features)
| ID | FR IDs | Initial state | User/API actions | Expected final DB/files/UI state |
|---|---|---|---|---|
| SC-01 | FR-01, FR-02, FR-04, FR-05 | No accounts; a clean bank statement PDF read | Record it | One unconfirmed account. The statement is `proposed` with Confirm and says "New account: …". Accounts and Today list no account. Spending is unchanged |
| SC-02 | FR-03 | SC-01 | Confirm the statement | The account is confirmed and on Accounts and Today. The statement is `verified`, `user` |
| SC-03 | FR-07 | SC-02 | Undo the Confirm | The account is unconfirmed and off Accounts |
| SC-04 | FR-03 | Unconfirmed account | Reconcile its statement; separately, import a CSV into it | Each action confirms the account |
| SC-05 | FR-06 | SC-01 | Record the same PDF again so its last four changes (stubbed reference) | One account (the new one); the old unconfirmed account is gone |
| SC-06 | FR-06 | SC-02 (confirmed) | Same as SC-05 | Both accounts exist; the confirmed one is left empty |
| SC-07 | FR-08 | Fixtures (a)–(d) of FR-08 in an old-schema library | Upgrade | (a) unconfirmed, (b) removed, (c) and (d) confirmed. Upgrading again changes nothing |
| SC-08 | FR-09, FR-10 | Confirmed account with 2 statements, 30 transactions, 1 CSV import record, 1 receipt matched, 1 transfer link, 1 recurring payment, 1 category rule | Open Delete | The dialog shows exactly those counts and the documents-stay sentence. Cancel changes nothing |
| SC-09 | FR-11, FR-12, FR-13 | SC-08 | Confirm Delete | No row refers to the account, its statements or transactions. The receipt counts standalone. Totals are as FR-12 states. The recurring payment remains with no account. Document hashes are unchanged; the statement offers Record and the CSV offers Import |
| SC-10 | FR-14 | Dialog open on an account | Record another statement into it, then Delete | Refused with the "changed" message; nothing removed |
| SC-11 | FR-15 | SC-08 with a fault on the last delete step | Delete; remove the fault; Delete | First: everything remains. Retry: deleted |
| SC-12 | FR-09, FR-11 | An unconfirmed account, from its statement's document page and from Accounts' "Waiting for confirm" group (OD-5) | Delete it | Removed with its statement and rows |
| SC-13 | FR-16, FR-17, FR-22 | User's case fixture: page 1 flagged `overlapping_text` and `unsupported_text_rotation`, Date \| Description \| Amount \| Balance, rows including `09/18 … 0.02 0.38` and `09/18 … -0.38 0.00` | Record (model stub returns 0.38 as that row's amount) | The rows record 0.02 and −0.38, never 0.38 or 0.00. The statement is `needs_review` with the page-1 layout note |
| SC-14 | FR-17, FR-18 | Bank statement with Withdrawals \| Deposits \| Balance; card statement with Amount, charges positive | Record each | Exact signed amounts per row; Balance never an amount |
| SC-15 | FR-19 | Card statement, year-less dates, period 2025-12-15 to 2026-01-14; variant with no period read | Record | Dates fall in 2025-12 and 2026-01. Variant: rows not recorded and listed in review |
| SC-16 | FR-20 | Rebuilt page; model stub adds one extra row and misreads one amount | Record | The rebuilt rows exactly, plus a review note for the extra row |
| SC-17 | FR-21 | One row of each rejection kind | Record | Good rows recorded; each rejected row an issue with page, row and reason; `needs_review` |
| SC-18 | FR-23 | 2 pages, page 2 scanned (stub vision); and an old reading without layout | Record | Page 1 rows from the rebuild, page 2 from the model; the old reading as today, with the note |
| SC-19 | FR-24 | A rebuilt-row transaction | Open its source; call provenance | Page with its words highlighted; provenance names page, line and word ids |
| SC-20 | FR-25, FR-26 | The user's case fixture with matching printed balances | Record twice | No reconcile issue; identical rows both times |
| SC-21 | FR-27 | Bank statement with a transactions table and a "DAILY ENDING BALANCE" Date \| Amount table | Record | Only the transactions rows are recorded |
| SC-22 | FR-28 | Account whose statement was shared to the family hub | Open Delete; Delete | The dialog counts the shared copies; afterwards no family row refers to the account |
| SC-23 | FR-29 | Statement printing one check in two sections | Record | Both rows recorded; review note naming both places |
| SC-24 | FR-02, FR-03, FR-05 | Browser; S recorded | Accounts tab, document page, Confirm | Account under "Waiting for confirm" until Confirm, then in its group and in Today's cash |
| SC-25 | FR-09, FR-10, OD-5 | Browser; unconfirmed account | Delete from Accounts and from the document page, by keyboard | Dialog with counts; Cancel returns focus; Delete removes it |
| SC-26 | FR-24 | Browser; a rebuilt-row transaction | Open its source | Page opens with the row's words highlighted |

## Out of scope / product decisions requiring approval

**Decisions** (settled 2026-10-26 with the defaults below, D4)

| ID | Decision | Default taken and rationale |
|---|---|---|
| OD-1 | Does Undo of a Confirm return the account to unconfirmed? | **Yes**, when nothing else confirmed it: Undo should put things back as they were. |
| OD-2 | Delete has no undo. | **No undo**; the dialog says so and that documents can be recorded again. A ledger Trash would be a separate feature. |
| OD-3 | May Record take a year-less date's year from the printed statement period? (PDF import asks the user instead, and lists inferring the year as a non-goal; Record has the cited period.) | **Yes**: the period is printed and cited on the same statement, and Record already resolves years from it today. Rows are refused when no period was read. |
| OD-4 | Recurring payments and bills tied to a deleted account: keep them without an account, or delete them? | **Keep them without an account**: they come from contracts and bills too, not only from the account's rows. |
| OD-5 | Where does an unconfirmed account appear so it can be deleted without confirming it? | On the statement's document page ("New account: … · Delete account"), and in a "Waiting for confirm" group at the bottom of Accounts, collapsed. Delete there behaves as FR-10 – FR-15. |

**Domain risk pass** (R1 – R3 accepted as FR-27 – FR-29; R4 and R5 need no requirement)

| # | Scenario | Consequence if unhandled | Recommended default |
|---|---|---|---|
| R1 | The family hub holds shared copies of a member's statements or transactions (U1). | A delete leaves orphan family rows, or fails on a reference. | Check in the plan. Shared copies from a deleted account are removed with it, and the dialog counts them. |
| R2 | A statement prints a "Daily ending balance" table (Chase does) with a Date and an Amount column. Under FR-16 it looks like a transactions table. | Every daily balance is recorded as a transaction: phantom money. | A table whose title line or heading names a balance ("Daily ending balance", "Balance") is not a transactions table, and its rows are never counted. This differs from PDF import, which would list it. Accept? |
| R3 | A statement prints the same transactions twice: a "Checks paid" section and the main list. | Duplicate rows; the arithmetic check fails. | Same-fingerprint rows citing different pages get a review note. Ordinals already keep both, so nothing is silently dropped. |
| R4 | Deleting an account that holds rows a confirmed PDF/CSV import also brought in from documents of other accounts (cross-account duplicates don't exist, since fingerprints include the account). | None expected. | Noted only; no requirement. |
| R5 | An account was confirmed only by an import, then the user deletes the import's document. | The account stays confirmed with rows whose document is in Trash. | Today's Trash behavior stands; no change. |

**Workflow.** `gate.py` isn't in this repository (U2). No approval was queried or recorded, and `approvals/` wasn't
touched. Next steps:
1. Run `design-tests` to write `test-contract.md`: the feature is stateful, deletes data and changes money.
2. The user approves `spec.md` and `test-contract.md` with their own gate command.
3. Then `plan-feature`.
