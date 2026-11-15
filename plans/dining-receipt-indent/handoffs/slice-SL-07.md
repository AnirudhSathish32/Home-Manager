```yaml
slice: SL-07
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 3ad658d
end_head: f65c1ed   # the code commit; the handoff itself is committed on top of it
commit: f65c1ed
checks:
  - command: ".venv/bin/python -m pytest tests/test_reread_links.py tests/test_dining_receipts.py tests/test_receipt_counting.py tests/test_reconcile_tools.py tests/test_fx.py tests/test_receipt_kinds.py tests/test_bills_ledger.py tests/test_reextraction.py tests/test_statement_accounts.py -q -p no:cacheprovider -rf"
    exit_code: 1     # 267 passed, 2 skipped, 1 failed (5m32s): tests/test_statement_accounts.py::test_sc07_the_upgrade_sorts_existing_accounts_and_running_it_again_changes_nothing. NOT in baseline-failures.txt, and NOT caused by SL-07: it fails the same with my src/ changes stashed (see Open issues).
  - command: ".venv/bin/ruff check src tests/test_dining_receipts.py tests/test_reread_links.py tests/dining_receipt_fixtures.py"
    exit_code: 0
  - command: "git diff --exit-code 3ad658d -- tests/dining_receipt_data"
    exit_code: 0
escalations: []
```
SL-07 is built: a reading that rewrites a receipt and changes its counted total removes each charge link the new total no longer supports. No UI change, no migration, no change to `tests/dining_receipt_data/`.

## What was done
- `finance/reconcile.py`
  - `Reconciler.link_holds(db, receipt, link)` (D35): same currency, a proposed link holds only at `-amount == total`; a verified one also when `total > 0`, `-amount > total` and `-amount*100 <= total*NEAR_PERCENT`. Another currency: estimate from the link's stored `estimate_rate_id` (`EcbRates.resolve`), else `self.estimate(...)`, and it holds when `-amount*100` is within `estimate * CROSS_RANGE`; no rate (any `FxError`) never holds. `total_minor` None: nothing holds.
  - `Reconciler.drop_stale_links(db, receipt_id, before)` (P13): for each live (non-rejected) link that doesn't hold: the row is deleted (never marked rejected); `transactions.merchant_id` is cleared when it equals the receipt's merchant before the reading; `apply_rules` and `TaxTags.apply_rules` for the charge; the verified `same_record` `occurrence_links` row between the two documents is deleted (`unlink_documents`) unless another live link of the receipt still joins a charge from that document; FR-30's note is appended (with "you confirmed" for a verified link, "this reading has no total." with no total), the receipt goes `needs_review`, `review_source` NULL; then `refresh_paid` again (drops a gift-card "Amount paid (" note, D40) and `refresh_splits` (the charge's rows go). Notes use `amount_text` (charge currency for the charge, receipt currency for the total) and the charge's transaction date, else posted date.
- `finance/ledger.py` `publish_receipt`: the `before` read also takes `total_minor` and `merchant_id`; right after `refresh_paid` in the written branch, when the receipt existed, is not a bill after corrections, and its counted total differs from before, it calls `drop_stale_links` (lazy import) inside the same transaction. Not called for an approved/rejected record (`_upsert` doesn't write it), for the reviewed kind-change branch, for bills, or for `correct` on a total.
- Tests: `tests/test_dining_receipts.py` — SC-05 step 5's "A held the link" branch tightened (link removed, A's reasons are the FR-06 reason and the note, K52 has no split rows for A and follows B's item categories), SC-09 steps 6–7 added to `test_sc09_…` plus (a) restart, (b) link review / unlink / relink, (c) approved link; SC-20 (+ a not a rejection and Correct Total links K52 again, b restart, c `occurrence_links`). New helpers `links_of`, `link_rows`, `charge_rows_of`, `charge_state`, `removal_notes`, `open_questions`, `note`, `REMOVED_52`, `CONFIRMED_52`. New `tests/test_reread_links.py` — SC-21 steps 1–7, (a) boundary 7.70/7.69, (b) no total, (c) gift card, (d) a foreign receipt (EUR, built through the ledger, 4 tests), the gift-card note staying for a link that holds, and SC-22 (a–f, one parametrised test). The new tests fail without the `src/` change (checked by stashing it: SC-05/09/20 and 8 of the 9 SC-21 tests failed).

## Notes for later slices / the orchestrator
- **SC-21 (d) is built through the ledger, as the contract says**, so its re-reads are `Ledger.publish_receipt` plus `Reconciler.run("extraction")` (what the job does), not the manager's extraction job; a EUR receipt through the job would need a printed-currency reading the B11 stubs don't have. Everything else re-reads through the job path.
- **SC-21 (d) variant "the cached rate removed after linking" can't be built**: cached rates are immutable (a trigger raises "Exchange rates are immutable"), so a stored `estimate_rate_id` always resolves. I tested instead (1) the stored rate beats a newer rate a lookup would find now, (2) a stored id naming no cached rate means no rate, so the link goes (the plan's FxError rule), (3) a link with no stored rate follows the rate found now, (4) no stored rate and no cached rate at all: removed on any change of total.
- SC-22 (c) bill: the re-read changes the bill's total by answering only the rent line (the bill's total is its lines, 1,450.00 instead of 1,488.42); the payment link is unchanged with no note. A different `amount_due` alone doesn't change a bill's total (the lines win), so it isn't used.
- SC-20 Correct Total uses `Manager.correct_record` (the API's path, which reconciles after).
- SL-08 needs nothing from this slice; the removal note is an ordinary issue on the receipt.

## Open issues
- **`tests/test_statement_accounts.py::test_sc07_the_upgrade_sorts_existing_accounts_and_running_it_again_changes_nothing` fails, and it is not SL-07's.** It builds an old library with the current schema, sets `PRAGMA user_version=72` (line 331) and reopens it, so every migration from 73 up is replayed; 081's `ALTER TABLE receipts ADD COLUMN one_category` then fails with "duplicate column name: one_category" (the older migrations tolerate a replay). It fails the same with SL-07's `src/` changes stashed, so it comes from SL-04's migration 081, which the SL-04 command (`test_migrations.py` etc.) didn't include and `baseline-failures.txt` couldn't list. I didn't touch it (no migration change, and the test is outside the slice). The orchestrator should decide: make that test's old-library builder drop the 081 columns, or another fix by the owner of SL-04. The final full run will show it.
- Not run (outside the slice's command): the full suite, browser tests, other slices' commands.
