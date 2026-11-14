```yaml
slice: SL-05
feature: bill-total-and-account-holder
part: fix for code review round 3 (plans/bill-total-and-account-holder/reviews.md, R3-1, major)
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: e574cd9
end_head: see the last commit of this branch (the handoff is committed after the code commit below)
commits:
  - 07c27f3  R3-1 fix, engine CR fix, v55, docs, tests
  - (this handoff)
escalations: []
checks:
  - command: ".venv/bin/python -m pytest tests/test_bill_printed_total.py tests/test_bill_engine.py tests/test_bill_engine_record.py tests/test_bills_ledger.py tests/test_extraction.py tests/test_bill_account_holder.py -q -p no:cacheprovider"
    exit_code: 0   # 841 passed, 1 skipped (opt-in browser test), 459 s
  - command: ".venv/bin/python -m pytest tests/test_bill_printed_total.py -q -p no:cacheprovider -k 'review3 or review1_a_photographed_due_now'"
    exit_code: 0   # 320 passed, 218 s (the new matrix + the SL-04 sign tests)
  - command: ".venv/bin/ruff check src/home_manager/documents/extraction.py tests/test_bill_printed_total.py tests/bill_engine_fixtures.py tests/test_bill_account_holder.py tests/test_bill_engine_record.py"
    exit_code: 0   # All checks passed (ruff on all of tests/ reports 2 existing errors in test_document_v2_browser.py and test_receipt_kinds.py, untouched)
```

No requirement changed (FR-141, FR-143, FR-145 stand; a due-now amount still never becomes what a bill counts).

## R3-1 → fix → tests

Cause: `core.money.to_minor` toggles its negative flag once per marker (parentheses, trailing minus, leading minus, each XOR), so `(-62.91)`, `($-62.91)` and `-62.91-` came out positive; SL-04 only made `CR` idempotent.

Fix (`src/home_manager/documents/extraction.py`):
- `due_now_minor(line, currency)` (new) is the one rule for a photographed due-now amount: negative when ANY negative mark is printed (a minus before or after the `$`, parentheses, a trailing minus, `CR`), positive with none, `-abs(...)`, applied once. The magnitude comes from `to_minor` (so `$` and an ISO code must be the bill's currency, and the decimals must be valid) after the marks are taken off, so there is no second sign toggle. Unpaired parentheses, more than one `$`, another currency or too many decimals raise `MoneyError`.
- `DUE_NOW_AMOUNT` now accepts what the matrix needs: `$` before the parenthesis (`$(62.91)`), `($-62.91)`, `(62.91-)`, `-$62.91`, and an ISO code before or after the number (`USD 62.91`, `62.91 USD`; the ISO list is `core.money.EXPONENTS`). Before this, a code made the line unrecognized (the round-3 report's "recognition limitation"). Non-dollar symbols (`€62.91`) are still not recognized (unchanged, out of scope).
- `due_now_cited` takes `issues`: an amount `due_now_minor` rejects is left out of the details with the review issue `Due now: the printed amount "…" on "…" is not valid USD money (…); the due-now line was left out.` (before, silent).
- Engine (text-PDF) path, found while writing the matrix: `anchor_bill` read the due-now figure with `table_engine.value_of`, which treats `CR` as positive, so a text-PDF `$62.91 CR` due-now line stored +6291 (a fourth sign rule; also what SL-03's handoff said was never probed). It now uses `bill_tables.signed(token, None)`, the same rule as a charge line (minus or `CR` is money off). The engine's tokenizer (`table_engine.amount_of`) already leaves a word with two marks unreadable; those lines then go through the photographed path and the rule above, so a text PDF with `(-62.91)` also stores −6291 (tested).
- `EXTRACTION_VERSION` is `typed-extraction-v55-bill-total-sign-rule`: stored output for an already-read bill changes. Pins updated in tests/test_bill_printed_total.py, tests/test_bill_account_holder.py, tests/test_bill_engine_record.py and docs/documents.md "Bill lines from the printed columns" (grep finds no other v54).

Tests (tests/test_bill_printed_total.py; fixture `bf.total_pages(due_amount=…)` is new):
- `SIGN_CASES`: every subset of {leading minus, parentheses, trailing minus, CR} (none, 4 singles, 6 pairs, 4 triples, all four = 16) × `$` {none, before everything (`$-62.91`, `$(62.91)`), after the parenthesis (`($-62.91)`), after the minus (`-$62.91`)} × code {none, `USD ` before, ` USD` after}, de-duplicated by printed form (`test_review3_the_sign_matrix_has_every_combination_once` checks the table and a sample of ids incl. the three review forms).
- `test_review3_a_due_now_amount_is_negative_when_any_negative_marker_…` (unit, every case): `due_now_line` → `due_now_minor` is −6291 with any marker, +6291 with none.
- `test_review3_a_signed_due_now_amount_is_stored_with_its_sign_and_never_links_an_outgoing_payment` (end to end, every case): photographed scan → extraction → publication → `Reconciler.run`; stored `details.due_now.minor` has the sign, total and amount due 166791, no issues, verified; an outgoing −6291 payment is linked to nothing when the sign is negative and linked when positive (control).
- `test_review3_an_unparseable_due_now_amount_is_left_out_with_a_review_issue_and_never_stored_positive` (`(62.91`, `62.91)`, `62.91 EUR`, `EUR 62.91`, `62.91 GBP CR`, `$$62.91`): no `details.due_now`, a `Due now:` issue, needs_review, no payment link.
- `test_review3_a_text_pdf_due_now_amount_has_the_same_sign_rule` (engine path, 15 printed forms incl. `62.91 CR`, `$62.91 CR`, `(-62.91)`, `($-62.91)`, `-62.91-`, `62.91 DR` positive).
- The SL-04 `test_review1_a_photographed_due_now_credit_…` cases still pass (they are in the 320 run).

Failing before the fix (run with the tests added and the source unchanged): the three review forms `(-62.91)`, `($-62.91)`, `-62.91-` failed the end-to-end test with `6291 == -6291`; `$-62.91 CR`, `62.91`, `-62.91` passed. After the fix only the engine fix was needed for `62.91 CR` and `$62.91 CR` on a text PDF (both failed with `6291 == -6291` before the `bill_tables.signed` change).

## Decisions and what is left

- `core.money.to_minor` itself was not changed (it is shared across every amount in the app; its toggle semantics are right for ordinary amounts such as `(45.10)` and `45.10-`). The due-now rule only takes its magnitude.
- The model's own amount-due answer (`field.value`) still goes through `money()` → `to_minor`; a model answer like `(-62.91)` would toggle. Not touched (the spec's source of truth for a due-now amount is the printed line; the answers in the tests are plain `-62.91`).
- Not run: the full suite (orchestrator's final run), browser tests, family/profile tests (no `manager.py` change).
