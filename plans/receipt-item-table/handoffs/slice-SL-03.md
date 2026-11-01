```yaml
slice: SL-03
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 584c74b
end_head: 5a52fd1        # the slice commit; the handoff itself is committed after it
commit: 5a52fd1
changed_files:
  - src/home_manager/app/static/document_v2.js     # doc2DetailList: per-item weight/count block removed
  - tests/test_document_v2_browser.py              # Printed-details assertions replaced (FR-25)
  - tests/test_receipt_items_browser.py            # sc11 step 4, new sc17
  - docs/money.md                                  # "Item categories and splits" (heading kept)
checks:
  - command: "RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_receipt_items_browser.py tests/test_document_v2_browser.py -q"
    exit_code: 1          # 11 passed, 1 failed: the known pre-existing test_document_page_states_find_correct_and_decide
  - command: ".venv/bin/ruff check src tests"
    exit_code: 0
skipped_checks:
  - "full non-browser suite (.venv/bin/python -m pytest -q): deferred to the final verification (user instruction)"
escalations: []
```

## What was built
- `doc2DetailList` no longer appends the per-item weight ("2.31 lb @ 0.59/lb") or count ("2 × 2.00") lines. Tenders and
  deposit splits are untouched.
- `test_document_forms_show_printed_details_and_change_the_kind` (R-d, intended by FR-25): Printed details must not contain
  "2.31 lb" or "2 ×"; the item table (`.ledger-rows`) must contain "2.31 lb" and "0.59", and have a Qty cell with the count.
  The tender assertions (Gift card ****5555, 5.00, EBT, 3.55) are unchanged.
- `sc11` step 4: every `.doc2-details-section` (possibly none, since G has no tenders) lacks BANANAS, YOGURT and "2.31 lb".
- `sc17`: R's Little Veg row shows Qty "10" and Unit price "$4.19"; no Printed details section contains LITLE VEGET, "10 ×" or "4.19".
  R has no tenders or savings, so Printed details is absent for it; the assertion accepts that, per the plan.
- `docs/money.md` "Item categories and splits": columns, Code/Qty/Unit price/Line total rules, when Paid reads "with tax" or "—",
  footer under Line total, Printed details without item lines. Written from the plan's rules and checked against `receipt.js`
  and SL-01's contract. FR-30 is for review.

## Notes for the verifier
- The one failure is `test_document_page_states_find_correct_and_decide` (extraction validation in the fake model's replies),
  failing at earlier heads too. All other tests in both files pass, including sc02/sc11/sc12/sc17/sc20 and the updated SC-14 test.
- `plans/receipt-item-table/progress.yaml` and `specs/receipt-tax-codes/*` are uncommitted changes that are not mine; staged by explicit path only.

## Open issues
None.
