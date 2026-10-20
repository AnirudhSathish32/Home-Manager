# Handoff: slice SL-04 — bill checks, traces, resident ledgers, prorated rent

```yaml
result: done
start_head: 822f35c561cd171985d3577bed96ccb88efc3dbb
end_head: f9b7c13
commit: f9b7c13
verification_command: python -m pytest tests/test_bill_kinds.py -k "sc38 or sc46" -q; python -m pytest tests/test_traces.py tests/test_recurring_bills.py tests/test_bills_ledger.py -q
verification_result: passed
log: plans/bill-kinds/logs/slice-SL-04.log
escalations: 2
```

## What was built
FR-49: `document_checks.bill_lines` / `bill_carried`. `normalize` runs them on every non-invoice bill. Lines vs amount due is now a named issue (P8), and the carried mismatch names the four values. `bill.lines` / `bill.carried` traces cover kinded, non-invoice bills (SC-38 trace, SC-46, SC-46e). FR-54: `earlier_lines` covers SC-46a, plus the dated-line variant. FR-56: `prorated_rent`, `rent_recurrence`, and `propose_bills` skipping a prorated bill or expecting the rate plus its `utilities` lines (SC-46c, 46c-1, 46c-2 proposal, 8-day move-in). Git state after: clean except the existing `M progress.yaml` and this handoff.

## Interfaces now available
- `document_checks.bill_lines(lines, compared_minor, currency, recorder=NULL)`, where `lines` = `[(label, signed_minor)]`.
- `document_checks.bill_carried(previous, payments, new, due, currency, recorder=NULL)`.
- `document_traces.bill_checks(db, row)`: checks `lines` and `carried`.
- `reconcile.usual_payments(db, paid)`.
- Details: `prorated: {"days": N}` on rent bills.
- Fixtures: `rent_ledger(previous=True)`, `rent_prorated(rate=False)`.

## Decisions and deviations
- `bill_lines` takes `(label, minor)` pairs, not bare minors as the plan named them, so the trace steps carry the line descriptions.
- **Beyond the plan's file list:** `track_bills` (extraction's reconcile run) set the expected amount to the average of "payments". That average includes the bill receipt itself, which turned 46c-2's 148842 into 83358. `usual_payments` now leaves prorated rent bills out of that average (they still count for last paid). `traces.bill_expected` uses the same rule, so the trace matches the stored value.
- The printed-details block in `bill_lines` moved up, so FR-54 and FR-56 can see `previous_balance` and `monthly_rent`. Same code, same output.
- SC-46c step 3 (RENT-NOV) runs in its own library, because the helpers transcribe one document per library.
- FR-54 note format: `Rent (2026-09-01 – 2026-09-30) …` / `Payment (2026-09-01) …`.

## Open issues / escalations
1. Escalation: the `track_bills` / `bill.expected` change above (reconcile.py, traces.py) is outside the plan's stated SL-04 scope. It's needed for 46c-2 and for SL-05's projection.
2. Intermittent test: `test_receipt_kinds.py::test_sc18_a_kind_change_waits_for_a_reading_of_the_same_document` failed once in the broader run (requests 8 vs 7) and passed alone. It's a race in the test: `requests` is counted when the run says `running`, before the held request reaches the stub. The fuel receipt path doesn't touch SL-04 code. Not fixed.
- Broader run (user-approved): test_bill_kinds (whole), test_invoice_ingestion, test_extraction, test_receipt_kinds, test_eval_tasks, test_statement_forms, test_budgets: 181 passed, 1 failed (the race above).
- ruff clean. mypy: 29 errors, the same as HEAD.
