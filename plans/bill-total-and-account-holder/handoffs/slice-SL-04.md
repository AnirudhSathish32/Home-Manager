```yaml
slice: SL-04
feature: bill-total-and-account-holder
part: fixes for code review round 2 (plans/bill-total-and-account-holder/reviews.md, R2-1 and R2-2, both major)
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 74878e4
end_head: see the last commit of this branch (the handoff is committed after the code commit below)
commits:
  - 32f28bf  R2-1, R2-2, version bump to v54, docs, tests
  - (this handoff)
escalations: []
checks:
  - command: ".venv/bin/python -m pytest tests/test_bill_printed_total.py tests/test_bill_account_holder.py tests/test_bill_engine_record.py tests/test_bills_ledger.py tests/test_bill_kinds.py tests/test_extraction.py tests/test_reconcile_tools.py -q -p no:cacheprovider"
    exit_code: 0   # 378 passed, 1 skipped (opt-in browser test), 363.85 s
  - command: ".venv/bin/ruff check src/home_manager/documents/extraction.py tests/test_bill_printed_total.py tests/test_bill_account_holder.py tests/test_bill_engine_record.py"
    exit_code: 0   # All checks passed
```

No requirement changed (FR-141, FR-143, FR-145, FR-142 (b), FR-148 stand as written; the user clarification that a due-now amount never becomes what a bill counts is untouched).

## Findings → fix → tests

Both new/extended tests were run against the pre-fix code first (tests added, source unchanged): exactly 3 failed, for the reasons named below; every other sign form already passed.

| # | Fix | Tests (tests/test_bill_printed_total.py) |
|---|---|---|
| R2-1 MAJOR `$-62.91 CR` negated twice, stored +6291, linked an outgoing payment | `extraction.due_now_line` no longer rewrites the text: it returns the amount as printed plus `credit` (the `CR` marker). `due_now_cited` parses the amount once with `core.money.to_minor` (which already reads `-`, `$-`, parentheses, trailing minus), then `CR` makes the result `-abs(figure)`: any combination of markers is negative, once. | `test_review1_a_photographed_due_now_credit_keeps_its_sign_and_is_no_payment_candidate` now parametrized over `-$62.91`, `$-62.91`, `($62.91)`, `(62.91)`, `62.91-`, `$62.91 CR`, `62.91 CR`, `$-62.91 CR`, `-62.91 CR` (all `details.due_now.minor == -6291`, and an outgoing −6291 payment is linked to nothing through `Reconciler.run` → `bill_payment`) plus `$62.91` (+6291, the payment IS linked). Pre-fix: `[$-62.91 CR]` failed. |
| R2-2 MAJOR cited payments `20.001` raised an uncaught `MoneyError`, extraction failed, nothing published | New `extraction.carried_minor(field, currency)`: None unless the field is proposed and its citations support the amount, and a `MoneyError` also gives None. `due_now_cited` reads previous balance and payments through it. A rejected carried amount is unavailable to the worked-out calculation (the amount due is then the new charges alone, no "worked out" note, `worked` None) and keeps the review issue `normalize` already recorded (`Payments received: …`). | `test_review2_a_cited_payments_amount_that_is_not_valid_money_is_left_out_with_its_issue_and_extraction_still_succeeds[20.001, 20.00 EUR]` (rent bill through the real pipeline: run not failed, publication present, `Payments received:` issue present, needs_review, total and amount due 166791, no "worked out" note, `due_now.worked` None). Pre-fix: both failed with `MoneyError` from `due_now_cited`. |

Same-pattern grep: the diff of SL-03 (`ed49983..HEAD`, `src`) added only two `to_minor` calls: the due-now amount (already guarded by `try/except MoneyError`) and the carried amounts (now guarded). `due_now_settled`'s `to_minor` calls read text the code itself produced with `as_decimal_text` (photo path) or `format(figure, "f")` from an integer (engine path), so they can't raise.

## Version and docs

`EXTRACTION_VERSION` is `typed-extraction-v54-bill-total-signs`: a `$-62.91 CR` bill read again now stores −6291 where v53 stored +6291, so stored output for already-read files changes. Pins updated in tests/test_bill_printed_total.py, tests/test_bill_account_holder.py, tests/test_bill_engine_record.py and the sentence in docs/documents.md "Bill lines from the printed columns"; the grep finds no other mention in `src`, `tests`, `docs`, `scripts`, `evals`, `specs` (SL-03's handoff keeps its historical v53 text). The same doc paragraph's sign sentence now lists all the credit forms and says a previous balance or payments amount that is not valid money is left out of the calculation with its usual review issue and never fails the reading.

## Not run

Full suite (orchestrator's final run), browser tests, `tests/test_family_*` / `test_profiles.py` (no `manager.py` change).
