# Add missed transactions waits for the statement's decision
Feature: missed-transactions-staging

<!-- Approval state lives in approvals/<slug>.json and is bound to this file's content hash.
     Do not add a Status line: changing it would change the hash. Check with gate.py. -->

Amends: `specs/account-import-pdf/spec.md` (the PDF import and its "Add missed transactions" entry point) for a PDF
recorded as a bank or card statement; `docs/documents.md` "Transaction imports" ("PDF", "Account", "Atomic and recorded",
"Entry points"); `docs/money.md` "New statements wait for you" (a statement's decision also covers rows added to it).
CSV and XLSX imports, and a PDF import into an account when no statement is recorded, are unchanged.

## Decisions already made (not to be re-asked)
- **D1 The wanted behavior** (user, 2026-11-09): "The expected behavior of adding missing transactions is to create a
  transaction table within that document viewer itself and then I can approve of the document from there, not for
  the transactions to auto apply in the system."
- **D2 What went wrong** (user, 2026-11-09): a card statement read as checking recorded no rows. Add missed transactions
  offered every row, created a new card account and posted the rows into it at once. The user was then left with an
  unconfirmed statement in one account and its rows counting in another, with no way to join them. The reading defect
  itself was fixed in the same session (`documents/extraction.py` publish: a page the engine records no rows from keeps
  the reading's rows, for review).

## Goal / users / scope / non-goals
**Goal.** On a recorded statement, Add missed transactions adds rows to that statement's record. They show in the
document's own transaction table, wait with the statement, and count only when the user confirms the statement (or
the row). Nothing is posted to an account behind the user's back, and no second account is made.

**Users.** The household user recording bank and card statements and fixing a reading that left rows out.

**In scope.** Where the rows go and how they wait (FR-01 – FR-04); a statement already confirmed (FR-05); the
document page (FR-06); re-reads, duplicates, undo and removal (FR-07 – FR-09); the import picker for a recorded statement
(FR-10); docs (FR-11).

**Non-goals.**
- Changing the statement's account or type from the dialog. When the statement is in the wrong account, that is fixed on
  the statement first (OD-3).
- CSV and XLSX imports, and a PDF that is not recorded as a statement: unchanged (they post to the chosen account and
  count unless rejected).
- Moving rows already imported before this ships (OD-4 default: they stay as they are).
- Any change to the engine's reading, the dialog's preview, ticks, sign, year or date-order choices.

## Existing behavior (verified paths, assumptions, unknowns)
Paths under `src/home_manager/` unless noted. Read at HEAD `06cbb9b` plus this session's uncommitted changes.

- The document page offers **Add missed transactions** on a read PDF once it is recorded
  (`app/static/document_v2.js:285 – :290`); it opens `openImport(doc, {missed: true})` (`app/static/library.js:155`),
  titled "Add transactions the reading missed".
- The import (`finance/ledger.py` `import_pdf_transactions`, `:1786`) takes an existing account or a `new_account`,
  which `account_in` finds or creates in the same database transaction (`:1801`). Rows are inserted with
  `origin='import'`, no `statement_id`, and `review_status` `proposed` (`insert_transactions`, `:626`), plus a
  `transaction_imports` row and `import:<id>` evidence.
- An `origin='import'` row counts unless rejected: `COUNTABLE` (`finance/ledger.py:59`) only holds back
  `origin='extraction'` rows that are not verified. The transaction drawer says the same
  (`app/static/finance.js` `openTransaction`).
- A statement's decision cascades only to its `origin='extraction'` rows (`Ledger.review`, `:1857 – :1870`). Confirm
  verifies them, Reject rejects them, Undo puts back the ones it cascaded.
- A row already recorded (same source-independent fingerprint) is not inserted again. Its evidence is linked, and when
  the caller passes a `statement_id`, an existing row without one takes it (`insert_transactions`, `:646 – :649`).
- A statement read again removes earlier extraction rows it no longer finds, except rows with evidence from another
  source (`publish_statement`, `:1260 – :1272`), so imported rows survive a re-read.
- The document page's record lists `record.transactions` (`app/static/receipt.js:334`), the statement's rows by
  `statement_id`.
- **Assumption:** the reconciliation of a statement (opening + rows = closing) runs over its rows by `statement_id`,
  so added rows join the check once they carry it. The plan confirms this.

## Functional requirements
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-01 | On a PDF recorded as a bank or card statement, **Add missed transactions adds the ticked rows to that statement**: its account, and its record. | After Add, each new row has the statement's `account_id` and `statement_id`, and `import:<id>` evidence; a `transaction_imports` row records the import as today. |
| FR-02 | **No account is chosen or created.** The dialog shows the statement's account by name and last four, and has no account picker or New account. | The dialog lists no account choice; a request naming another account or a `new_account` for a recorded statement is refused with "These rows are added to the statement's account. To use another account, correct the statement's account first." and writes nothing. |
| FR-03 | **Added rows wait with the statement.** While the statement is not confirmed, they don't count anywhere (totals, budgets, forecast, Home, reconciliation of other documents). | A statement waiting in review with 3 added rows: spending and cash flow for the period are unchanged by them; each row's drawer says "Not counted until you decide." |
| FR-04 | **The statement's decision covers them.** Confirm counts them, Reject rejects them, and Undo puts back the ones it decided, exactly as for the statement's own read rows. A row decided on its own keeps its decision. | Confirm → the 3 rows are verified and count; Undo → they wait again; a row rejected by hand before Confirm stays rejected. |
| FR-05 | **A statement already confirmed** goes back to review when rows are added, with the reason "N rows were added from the printed columns; check them." Its earlier rows keep counting; the added ones wait until it is confirmed again. | Confirmed statement, add 2 rows: statement `needs_review` with that reason; earlier rows still verified and counted; the 2 rows don't count until Confirm. |
| FR-06 | **In the document viewer.** The added rows show in the document's transaction table among the statement's rows, in printed order, each marked "Added from the printed columns" and linked to its source lines. The statement's balance check includes them. | The record view lists the rows with the mark; clicking one lights its lines; a statement whose rows now reach its closing balance shows the check as passing. |
| FR-07 | **Duplicates.** A ticked row the statement or account already holds is not added; it is listed as already recorded, as today. | Re-running Add on the same PDF adds nothing and reports every row as already recorded. |
| FR-08 | **A re-read keeps them, once.** Reading the statement again never removes an added row and never makes a second copy of one the new reading also finds; that row keeps one id with both evidence links. | Add 2 rows, then Record again with a reading that now finds one of them: the statement holds each row once; both rows remain. |
| FR-09 | **Removing them.** Rejecting the statement rejects them (FR-04). Deleting the statement's account removes them with it, as today. | Account delete counts and removes them; the dialog's counts include them. |
| FR-10 | **The import picker** (Transactions → Import, Accounts → Import) on a PDF recorded as a statement behaves as FR-01 – FR-05. On a PDF not recorded as a statement it is unchanged. | Picker import of a recorded statement adds to the statement; picker import of an unrecorded PDF still asks for an account and posts as today. |
| FR-11 | **Docs.** `docs/documents.md` "Transaction imports" and `docs/money.md` "New statements wait for you" describe FR-01 – FR-10; the open-work item is removed. | Doc text present; open-work entry gone. |

## Invariants, privacy, security and data retention
- Nothing leaves the machine; no model call is added.
- Money from the server: the dialog, the record and the totals show server-formatted amounts only (`docs/ui.md`
  "Screen rules").
- One database transaction per Add, as today: rows, evidence, the import record and the statement's status change
  together, or none of them.
- The decision trail stays complete: the statement's status change (FR-05) and each cascaded decision are
  `review_events` rows.

## Errors, recovery, duplicates, restart behavior
- If the statement changes between preview and Add (re-read, decided, removed), Add is refused with today's "changed
  since the preview" wording and writes nothing.
- If the statement's record was removed (its account deleted), the button is off as for an unrecorded document.
- A crash during Add leaves nothing (single transaction).

## Nondeterministic outputs and how they are verified
None new. Readings in tests are the synthetic fixtures and stubbed model replies already used by
`tests/test_pdf_imports.py` and `tests/test_statement_accounts.py`.

## Scenarios
| ID | FR IDs | Initial state | User/API actions | Expected final DB/files/UI state |
|---|---|---|---|---|
| SC-01 | FR-01, FR-02, FR-03 | Statement recorded with 2 of 5 rows, waiting | Add missed transactions, tick the 3 missing rows, Add | 5 rows on the statement in its account; the 3 added ones don't count; no new account |
| SC-02 | FR-04 | After SC-01 | Confirm the statement; then Undo | All 5 count; after Undo all 5 wait again |
| SC-03 | FR-04 | After SC-01, one added row rejected by hand | Confirm | 4 rows count; the rejected one stays rejected |
| SC-04 | FR-05 | Statement confirmed with 4 rows | Add 1 row | Statement needs review with the reason; 4 keep counting; the new one waits |
| SC-05 | FR-02 | Statement recorded | API call naming another account, then one naming `new_account` | Both refused with the FR-02 message; nothing written |
| SC-06 | FR-06 | After SC-01 | Open the document page | 5 rows in printed order, 3 marked; lines light on click; the balance check passes |
| SC-07 | FR-07 | After SC-01 | Add again | Nothing added; every row reported as already recorded |
| SC-08 | FR-08 | After SC-01 | Record again with a reading that now finds one of the 3 | 5 rows, each once; the found one has two evidence links |
| SC-09 | FR-10 | Unrecorded PDF; separately a recorded statement | Import from the picker | Unrecorded: today's flow; recorded: as SC-01 |
| SC-10 | Errors | Preview open; statement re-read meanwhile | Add | Refused; nothing written |

Recommended: run `design-tests` before approval (multi-step, counting).

## Out of scope / product decisions requiring approval
- **OD-1 A statement already confirmed (FR-05).** Default: it goes back to review. Alternative: the added rows wait on
  their own and the statement stays confirmed.
- **OD-2 The rows' origin.** Default: they stay `import` rows with their import evidence, joined to the statement, so
  provenance still says where they came from. Alternative: record them as the statement's own read rows.
- **OD-3 Statement in the wrong account or type** (the user's own case: a card statement recorded as checking). Default:
  out of scope here. A separate change gives the statement page a way to correct the statement's account or type.
  Until then, reading it again (with this session's fix) is the way. Recorded in `docs/open-work.md`.
- **OD-4 Rows imported before this ships.** Default: unchanged; they keep counting in the account they went to.
  Recording the statement again links any that match (same fingerprint) to it, as today.

**Domain risk candidates (accept or reject each):**
- **R1 The rows add up to more than the statement.** Added rows plus read rows may now overshoot the closing balance.
  Default: the balance check fails, which is a review reason; nothing is blocked.
- **R2 A family member's view.** Rows added to a statement routed to a family member wait for that member's decision
  as the statement does. Default: the same routing as the statement.
- **R3 Pending rows ticked by hand.** A row the engine marked pending is offered unticked today. Default: unchanged; if
  ticked it is added and waits like the others.
- **R4 A row older than the statement period.** Default: today's period check makes it an issue on the statement.
