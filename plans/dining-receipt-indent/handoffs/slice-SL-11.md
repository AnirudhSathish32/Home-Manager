```yaml
slice: SL-11
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 72a9634
end_head: 6746b8a   # the code commit; the handoff itself is committed on top of it
commit: 6746b8a
checks:
  - command: "python -m pytest -q -p no:cacheprovider tests/test_dining_receipts.py"
    exit_code: 0     # 130 passed (3m40s); includes the three new tests
  - command: "python -m pytest -q -p no:cacheprovider tests/test_family_routing.py tests/test_family_inbox.py tests/test_bills_ledger.py tests/test_bill_kinds.py tests/test_returns.py tests/test_statement_accounts.py tests/test_receipt_kinds.py tests/test_reread_links.py"
    exit_code: 0     # 233 passed, 1 skipped (opt-in browser); the apply_delivery / record_payload files and the gift-card files
  - command: "git stash (src change only) && pytest -k 'not_paid_for_twice or worked_out_tip_is_delivered or bill_delivered' tests/test_dining_receipts.py"
    exit_code: 1     # the three new tests fail without the fix (gift-card copy counts 6000, not 8000), pass with it
  - command: "ruff check src tests"
    exit_code: 1     # only the 2 known findings: test_document_v2_browser.py I001, test_receipt_kinds.py F402
escalations: []
```
SL-11 fixes the two confirmed code-review round 2 findings on SL-10's family delivery. No requirement or test-contract value changed; no migration.

## Finding 1 (MAJOR): gift cards deducted twice on a delivered receipt
- Root cause: SL-10 made `record_payload` send the kind's `details` (`details_json[kind]`) with the record. Those hold the gift-card tenders, while the payload's `total_minor` is already the amount paid (`refresh_paid` keeps paid in `total_minor`, printed in `printed_total_minor`). The destination's `publish_receipt` sets `printed_total_minor` NULL, so `refresh_paid` treated the received paid total as the printed one and subtracted the gift card again ($100 printed, $20 gift card, counts $80 → copy counted $60).
- Change (family_routing.py `record_payload`): a receipt (`document_kind != 'bill'`) carries only `receipt_kind`, which is all FR-14 (a) needs (`publish_receipt` reads the kind for `dining` / one-category). `bill_kind` and `details` are no longer sent (back to the pre-SL-10 payload for those). `publish_receipt` with no `details` is fine: `merged_details` stores `{kind: {}}`, and the only other reads of `record["details"]` are in that call and the kind-change branch (`record.get("details") or {}`). The now-unused `kind_column` import was removed.
- Regression test: `test_a_receipt_delivered_by_the_family_is_not_paid_for_twice_with_a_gift_card` (tests/test_dining_receipts.py, next to the SL-10 roundtrip test). A grocery receipt with printed 100.00, gift card 20.00 and card 80.00 is read (source: total 8000, printed 10000), delivered with a share of 8000: the copy's total is 8000, `printed_total_minor` NULL, no issues, and its category split sums to 8000. Without the fix the copy counted 6000.

## Finding 2 (MINOR): a corrected tip was delivered with its "Worked out" marker
- Root cause: SL-10 copied the raw `tip_worked_out_json`; the source hides it with `Ledger.worked_out_tip` while a tip correction of the user stands, but the copy has no correction history, so it showed "Worked out: …" beside a corrected tip.
- Change: `record["tip_worked_out"] = Ledger.worked_out_tip(db, row)`: the effective marker, None while a correction stands (and again present once Undo of that correction restores it).
- Regression test: `test_a_worked_out_tip_is_delivered_only_while_no_correction_of_yours_stands`: B0 with the tip corrected 8.79 → 9.00: the payload's `tip_worked_out` is None and the copy has tip 900, `tip_worked_out_json` NULL, kind dining; after Undo at the source a delivery into a second library has tip 879 and the marker (equal to the source's).

## Bill (c)
- `test_a_bill_delivered_by_the_family_carries_no_kind_as_before`: a bill's payload has no `receipt_kind`, `bill_kind` or `details`. The test turns B0's row into a bill by UPDATE (`document_kind='bill'`, `bill_kind='general'`, `receipt_kind` NULL) because `record_payload` only reads the row.

## Open issues
- A family-sent grocery/other receipt still loses its kind's details (tenders, store info) in the copy, as before SL-10; only the kind itself now travels. A copy of a dining receipt has no tip-table or tender details either. Not in FR-14 (a).
- Not run: the full suite, browser tests.
