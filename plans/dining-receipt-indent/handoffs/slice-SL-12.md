```yaml
slice: SL-12
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 0935cac
end_head: cefd114   # the code commit; the handoff itself is committed on top of it
commit: cefd114
checks:
  - command: "python -m pytest -q -p no:cacheprovider tests/test_dining_receipts.py tests/test_receipt_kinds.py tests/test_bill_kinds.py tests/test_bills_ledger.py tests/test_family_routing.py tests/test_family_inbox.py tests/test_returns.py tests/test_statement_accounts.py"
    exit_code: 0     # 349 passed, 1 skipped (opt-in browser); the two new tests plus every apply_delivery / record_payload file
  - command: "git stash (src change only) && pytest -k 'gratuity or gift_card_delivered' tests/test_dining_receipts.py"
    exit_code: 1     # both new tests fail without the fix (the payload has no details); pass with it
  - command: "ruff check src tests"
    exit_code: 1     # only the 2 known findings: test_document_v2_browser.py I001, test_receipt_kinds.py F402 (a third, import order in the edited test file, was fixed)
escalations: []
```
SL-12 fixes the confirmed code-review round 3 MINOR finding on SL-11's family delivery. No requirement or test-contract value changed; no migration.

## Finding (MINOR): a delivered dining receipt lost its gratuity
- Root cause: SL-11 sent only `receipt_kind` for a receipt. A dining receipt's gratuity lives only in its dining details (read by `document_traces.py` for the arithmetic check), so the copy of a $50 + $4 + $9 = $63 receipt showed a failed check ($54 vs $63).
- Change (family_routing.py `record_payload`): a receipt whose kind is `dining` also sends `record["details"]` = `Ledger.current_details(row)` without the `tenders` key. Nothing else is sent for other kinds or bills (no `bill_kind`, no details), and `tip_worked_out` still comes from `Ledger.worked_out_tip`. The comment says why.
- Why only `tenders` is dropped: the paid total is read from the details only through `tenders` (`Ledger.refresh_paid`, the record's `tenders` list and its gift-card sum at ledger.py ~:2269/:2321, and the tender check in `document_traces.py` ~:188). The other dining details (gratuity, gratuity_included, party_size, server, table) don't touch the paid total; the copy's details are stored by `publish_receipt` as `{dining: details}`.

## Tests (tests/test_dining_receipts.py, next to the SL-10/SL-11 delivery tests, reusing `delivered`)
- `test_a_dining_receipt_delivered_by_the_family_keeps_its_gratuity_and_its_arithmetic_check`: DINING ($50/$4/$9/$63) read and delivered; the payload's details hold gratuity 900 and no tenders; the copy's `details_json` keeps gratuity 900; the dining check's trace (`traces.trace` on source and copy) gives 63.00 vs 63.00, reconciles, with the gratuity input 900 on both.
- `test_a_dining_receipt_with_a_gift_card_delivered_by_the_family_is_not_paid_for_twice`: the same receipt with a $10 gift-card tender put in its dining details as `test_sc18a` does (the dining form reads no tenders); source counts 5300 of 6300 printed; the payload carries total 5300 and details with gratuity but no tenders; the copy counts 5300, `printed_total_minor` NULL, `one_category` 1, its details carry no tenders, and every split is in the receipt's category and sums to 5300.
- The SL-11 grocery gift-card, worked-out-tip and bill tests still pass.

## Open issues
- A copy of a dining receipt now carries the dining details except its tenders (so no gift-card tender row on the copy); other kinds' details are still not sent, as in SL-11.
- Not run: the full suite, browser tests.
