# Handoff: bill-kinds SL-03

- **Status:** done (pending orchestrator acceptance)
- **START_HEAD:** 22e08a7da3bf6438fd04a197e3471720677054d0
- **Commit:** 05940e6 (`bill-kinds SL-03: dates on every bill, rent period from rent lines, printed amounts in details`)
- **Git state after:** clean except the pre-existing `M plans/bill-kinds/progress.yaml` (not touched) and this handoff.
- **Covers:** FR-46, FR-47, FR-48, FR-55; SC-39 (+39a–c), SC-40, SC-41 (+41a), SC-42 (a–e), SC-46b (+46b-1, 46b-2); the user's carried item (printed amounts in details).

## What changed (`documents/extraction.py`)
- `dates_in` (positions); `printed_dates` wraps it. `ISSUE_WORDS`, `DUE_WORD`, `ISSUED_WORD`, `DATE_LABEL`, `due_labelled`.
- `bill_dates(record, fields, issues, notes)` runs first in the bill branch, on every bill. It returns the header period's `(issues, notes)`.
- `bill_lines(..., notes, header_period)`. The rent period comes from the rent lines and goes in `details["period"] = {"from": "rent_lines", how, locator}`. The header period's outcomes count only when no rent line gives a period. Without that, SC-41's correct answers (a header citing "October 2026") would go to review. Non-invoice bills keep the printed `new_charges`, `previous_balance`, `payments_received` (as a magnitude) and `monthly_rent` as `{minor, locator}`. A bill printing none of them stays `{}`. A bill with `bill_kind` None has nowhere to keep notes, so its notes become issues (only legacy/test callers reach this).
- `LABELS["bill"]`: the Issued/period sentence.

## Verification (log: `plans/bill-kinds/logs/slice-SL-03.log`)
- Slice `-k "sc39 or sc40 or sc41 or sc42 or sc46b or dates"`: 34 passed.
- `test_bills_ledger`, `test_invoice_ingestion`, `test_recurring_bills`, `test_extraction`: 53 passed, 1 skipped (opt-in browser test).
- `test_bill_kinds` (whole file), `test_receipt_kinds`, `test_eval_tasks`, `test_traces`, `test_migrations`: 141 passed. (The first try of step 3 named a nonexistent `test_document_forms.py`; the rerun is in the log.)
- ruff: clean. mypy `extraction.py`: 29 errors, the same as HEAD.

## Escalations / deviations
- **SL-02 tests changed:** the `== {}` details checks now expect the rent `period` entry. sc50 (PHONE) now expects `{"general": {"new_charges": …}}`. The C-money oracle checks only details that have `minor`.
- **42b:** the contract's header-only reversed period would be ignored on a rent bill (FR-47). So the test reverses both the header and the rent line, and a general-bill variant is added.
- Invoices get no printed-amount details; `invoice_json` keeps their payments.
- Page: `doc2DetailList` already hides a section with no rows, so no empty "Printed details" heading appears. No JS changed.
