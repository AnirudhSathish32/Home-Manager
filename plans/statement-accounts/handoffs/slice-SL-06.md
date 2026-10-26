```yaml
slice: SL-06
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: fc2d68ecda82071b0dc0dadfcb575192881d3dfb
end_head: this commit (a commit cannot name itself; see `git log --grep "statement-accounts SL-06:"`)
commit: HEAD of "statement-accounts SL-06:"
checks:
  - command: ".venv/bin/python -m pytest tests/test_statement_accounts.py -k \"journey_j2 or sc12 or sc22\" -q"
    exit_code: 0   # 5 passed (the filtered part of the slice command)
  - command: ".venv/bin/python -m pytest tests/test_family_routing.py tests/test_reconcile_tools.py tests/test_finance.py tests/test_library.py -q"
    exit_code: 0   # 49 passed (the slice command's non-filtered files, run whole)
  - command: "M3: .venv/bin/python -m pytest tests/test_statement_rebuild.py tests/test_statement_forms.py tests/test_pdf_imports.py tests/test_extraction.py tests/test_layout_consumers.py tests/test_provenance.py tests/test_statement_accounts.py tests/test_migrations.py tests/test_imports.py tests/test_family_routing.py tests/test_finance.py tests/test_reconcile_tools.py tests/test_library.py -q"
    exit_code: 0   # 396 passed (the whole M3 set; tests/test_statement_accounts.py whole = 24 tests; re-run after a final docstring edit: ruff clean, test_statement_accounts.py 24 passed)
  - command: ".venv/bin/python -m ruff check src tests"
    exit_code: 0
escalations:
  - "No gate needed a change to the spec, test contract or an approved plan decision. Existing assertions changed: none (see 'Changed existing assertions')."
  - "Deviations from the plan's text, each local (see 'Deviations to look at'): an investment event that named a deleted transaction also loses transaction_previous_type and transaction_link; the preview counts refund links too; family.copy is computed from the profile link."
```

# SL-06: Deleting an account

## Changed files
- `src/home_manager/finance/ledger.py`
  - `AccountNotFound(ValueError)` (raised by `account()` as before, same message, so every other caller still answers 400) and `AccountChanged(RuntimeError)` (the API's RuntimeError handler already answers 409 with the message).
  - `delete_counts(db, id)`, `delete_token(db, id, counts)`, `family_rows(db, id)`, `delete_preview(id)`, `delete_account(id, token)`.
  - `_remove_account(db, id)` is now the full delete in the plan's order (below). FR-06's `remove_if_empty` calls it unchanged; with nothing in steps 1–5 it does what the SL-05 version did.
- `src/home_manager/app/manager.py`: `delete_preview` (adds `family.copy`), `family_copy`, `delete_account` (`require(False)`, then ledger, then best-effort `reconciler.run("import")`, a failure logged with `log_failure` and not undoing the delete).
- `src/home_manager/app/api.py`: `AccountDelete` (strict body `{"token": str}`), `GET /api/finance/accounts/{id}/delete-preview`, `POST /api/finance/accounts/{id}/delete`; `AccountNotFound` → 404.
- `src/home_manager/documents/extraction.py` `get`: `publication["removed"] = True` when a statement publication's statement no longer exists (P11).
- `tests/test_statement_accounts.py`: `journey_j2` (3 tests), `sc12`, `sc22` (5 tests, listed below).
- `tests/statement_account_fixtures.py`: `orphans` now counts an `account_id`/`ledger_account_id` column only where its foreign key targets `accounts` (`pragma_foreign_key_list`; plan "Final-state oracle", pass 1 INFO), and also checks `transactions.replaced_by`.
- `docs/money.md` new section "Deleting an account"; `docs/family.md` "Family ledger" (one bullet); `docs/open-work.md` (Statement accounts bullet: the delete API is built, the screens are not).

## What a delete touches (exact)
`_remove_account(db, A)` runs in one connection under `BEGIN IMMEDIATE`. T = transactions with `account_id=A`, S = statements with `account_id=A`; sets are subqueries, so there is no variable limit. Order:
1. For T: `DELETE` from `transaction_receipt_links`, `transaction_income_links`, `category_splits`, `tax_tags`, `investment_payment_rejections` (by `transaction_id`); `transaction_links` where either side is in T; `UPDATE investment_events SET transaction_id=NULL,transaction_previous_type=NULL,transaction_link=NULL` for T.
2. `UPDATE transactions SET replaced_by=NULL WHERE account_id<>A AND replaced_by IN T` (R2).
3. `DELETE` from `financial_evidence_links`, `review_events`, `reconciliation_issues`, `record_corrections`, `family_corrections`, `family_assignments`, `donation_checks` where (`record_type='transaction'` and `record_id` in T) or (`record_type='statement'` and `record_id` in S).
4. `DELETE FROM reconciliation_issues` for each `status='open'` row whose `detail_json.candidate_transaction_ids` includes an id in T (rows with no or malformed JSON are skipped).
5. `DELETE` from `transactions`, `statements`, `transaction_imports` where `account_id=A`.
6. `DELETE` from `category_rules`, `tax_rules` where `account_id=A`; `UPDATE recurring_obligations SET account_id=NULL`; `UPDATE investment_accounts SET ledger_account_id=NULL` (where it was A).
7. `DELETE FROM accounts WHERE id=A`.

Not written: `record_shares` (receipts only, per the plan), `receipts`, `income_records`, `merchants`, anything of another account except the `replaced_by` pointer, `extraction_runs`, `parse_runs`, documents, blobs, readings, library files. A transaction of another account that points at a statement of A (`statement_id`) is not rewritten: the delete would fail on the foreign key and roll back (it does not widen).

Measured on J2's fixture (A with 3 statements, 12 transactions, one import; every other table identical), the rows that differ after the delete are exactly: `accounts` −1, `statements` −3, `transactions` −12, `transaction_imports` −1, `financial_evidence_links` −15, `review_events` −1, `category_rules` −1, `transaction_receipt_links` −1, `transaction_links` −1, `recurring_obligations` 2 changed (`account_id` → NULL), `investment_accounts` 1 changed (`ledger_account_id` → NULL), `reconciliation_runs` +1 (the reconcile after commit). The test asserts that dict.

## Behaviour
- Preview `counts`: `statements`, `transactions`, `imports`, `receipts` (distinct receipts with a verified or proposed link to T), `pay_stubs` (same, income), `transfer_links`, `refund_links` (verified or proposed), `recurring_payments` (`kind='subscription'`), `recurring_bills` (`kind='bill'`, N1), `category_rules`. SC-08 expects 2, 9, 1, 1, 1 (transfer), 2 (payment + bill), 1: it gets them.
- `token`: sha256 of canonical JSON of the counts, `(id, updated_at)` of every statement and transaction of the account, and every import id. Stable for an unchanged account; changes when a statement is recorded, a row is touched or an import lands (FR-14, G4). It is also checked inside `BEGIN IMMEDIATE`.
- `family`: `{"rows": n, "copy": null | {"statements": n, "transactions": m}}`. `rows` counts, in this library, the `family_assignments` (statements), `family_corrections` (statement or transaction) and `family:` evidence links for A's records. `copy` (the manager's, P9) counts the statements and transactions of A with `created_at` ≤ the profile link's `published_at`; all of them for a link with `local` and no `published_at`; null when the profile has no family link, `publishing` is false, or it is not local and has not published yet.
- A missing account is 404 on both routes. A wrong or stale token is 409 with the FR-14 message. An injected SQLite error is 500 with the app's generic message and no traceback (the existing `sqlite3.Error` handler), the transaction rolls back, and the retry with the same token succeeds.
- `ExtractionService.get`: `publication["removed"] = True` when `publication.record_type == 'statement'` and no statement with that `id` and that run's blob hash exists (ids are reused after a delete, so the blob is checked too). `ledger_status` goes NULL by itself (`transaction_imports` and `statements` are gone).

## Tests (`tests/test_statement_accounts.py`)
- `test_journey_j2_deleting_an_account_with_everything_in_it`: the SC-08 fixture through public paths (W recorded and confirmed, W′, both reconciled, a CSV import into A, B with a CSV import, the transfer link the import's reconcile made, made the user's; a verified receipt linked to w1; a recurring payment and bill; a category rule; a linked investment account). Steps 1–6 as the contract: counts, same token twice, nothing changes on cancel (`dump` of every table + C-docs); W″ recorded after the dialog (SC-10) gives the 409 with no change; the fault trigger (`BEFORE DELETE ON accounts`) gives a 500 with no traceback and no change (SC-11); then the delete, C-orphans, B's rows and account unchanged, recurring rows with NULL account, the investment account unchanged but for the link, the exact touched-tables dict above, per-month spending and money in against `get_spending`/`calculate_cashflow` for the household and for A (before − A's counted + 4500 for the receipt in 2026-08), and step 6: C-docs, `publication.removed`, `ledger_status` NULL for the statement document and the CSV, Record again makes a new waiting account.
- `…_every_table_that_names_the_accounts_records_is_cleared_and_the_others_keep_theirs`: rows in every dependent table for account C and a control account D (splits, tags, payment rejections, income and receipt links, transfer and refund links, `replaced_by`, corrections, review events, family corrections and assignments, donation checks, open questions with C's, D's and no candidates, tax and category rules, an investment event). C-orphans for C; D's rows survive; the pay stub and receipt stay.
- `…_a_missing_account_is_404_the_body_is_strict_and_a_fault_in_any_step_leaves_everything`: 404s, 422s, a wrong token, a fault on `transactions` (a step before the account row) rolls back, the retry with the same token works.
- `test_sc12_…`: a fresh Record of S (waiting account), deleted by the id from `GET …/accounts/waiting`; account, statement and 5 rows gone, C-orphans, C-docs, `publication.removed`, Record again works.
- `test_sc22_…`: a statement's `family_assignments` row (made by `FamilyRouting.refresh`), a family correction, a `family:` evidence link; the preview counts 3; `manager.delete_preview(...).family.copy` for six profile links (via `monkeypatch`); after the delete no family row names the account's records and `FamilyRouting` lists none.
Mutation checks (each fails at least one test, then restored): token check off; `family_assignments` not deleted; candidate-question step off; category rules not deleted; recurring `account_id` not cleared; investment event not cleared.

## Changed existing assertions
None. `orphans()` in `tests/statement_account_fixtures.py` (SL-05's helper) got the foreign-key rule and `replaced_by`; its only existing caller (`journey_j1`) passes unchanged.

## Deviations to look at
1. **Investment events** (plan step 1: "`investment_events.transaction_id` is set NULL"): I also clear `transaction_previous_type` and `transaction_link`, as `reconcile.unlink_investment` does (`reconcile.py:367`). A `transaction_link='user'` with no transaction would otherwise still read as a decision about a transaction that is gone. It touches only events that named a deleted transaction.
2. **Counts**: the preview also reports `refund_links` (reconcile makes `refund` links as well as `transfer`; both are deleted). SC-08 asserts the contract's counts; `refund_links` is 0 there. SL-07 may show the line when non-zero or ignore it.
3. **`require(False)`**: it only checks that a library is open (as `import_transactions` does). The plan's "refuses only while non-inference work is running" is not what it does; the guards against a concurrent Record or import are `BEGIN IMMEDIATE` and the token, as the plan also says.
4. **`family.copy`** is computed in the manager from the profile's family link and the `created_at` of A's rows. The plan's wording ("Your family's copy has these n statements and m transactions") is built from that; if SL-07 wants other wording it is a UI string.
5. `record_shares` is not touched (receipts only). C-orphans checks it and holds.

## Gates
- `tests/test_traces.py` is not in SL-06's or M3's command, so the known 3 failures do not arise here.
- SL-06 command: the filtered file (`-k "journey_j2 or sc12 or sc22"`) 5 passed; the other four files whole 49 passed. (Run as one command with `-k` the other files are deselected, so they were run separately.)
- M3, whole: 396 passed (see the header).
- `progress.yaml` was not touched or staged.

## Open issues for SL-07
- The dialog needs: `GET …/delete-preview` → `account`, `counts` (show statements, transactions and imports always; the others only when non-zero), `family.rows` and `family.copy` (show the family line when either is non-zero/non-null), `token`; `POST …/delete` with `{"token"}`. On 409, reload the preview. On success the response has `deleted` and `counts`.
- The text "The documents stay in your library; you can record or import them again." and "This can't be undone." are not in the API; SL-07 renders them.
- `doc2Steps` should read `publication.removed` (set by `ExtractionService.get`) as "no record": offer "Record it" (`doc2Record(true)`).
- A waiting account's delete from its document page uses `waiting_accounts()`'s `statement_id`/`statement_document_id` (SL-04) and the same routes.
- After a delete the reconcile in `manager.delete_account` has run; the client should refresh Accounts, Today and the document page.
