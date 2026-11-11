---
slice: SL-07
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 2885575
end_head: 6c8eed6
commit: [2b8165d, 6c8eed6]
checks:
  - command: ".venv/bin/python -m pytest tests/test_bill_split.py -k sc131 -q"
    exit_code: 0   # 10 passed, 51 deselected
  - command: ".venv/bin/python -m pytest tests/test_paystub_split.py tests/test_bills_ledger.py tests/test_bill_kinds.py tests/test_recurring_bills.py tests/test_invoice_ingestion.py tests/test_reconcile_tools.py -q"
    exit_code: 0   # 164 passed, 1 skipped (opt-in browser test)
  - command: ".venv/bin/python -m pytest tests/test_bill_split.py tests/test_bill_engine_record.py -q"
    exit_code: 0   # 145 passed
  - command: ".venv/bin/python -m ruff check src/home_manager/documents/extraction.py src/home_manager/finance/ledger.py tests/test_bill_split.py"
    exit_code: 0
escalations: []
---

# SL-07: VOID and duplicate bills (FR-133, FR-134; SC-131)

No failures, so nothing to compare with `baseline_failures`. Full suite not run (orchestrator's).

## What changed
- `finance/ledger.py` (after `mark_duplicate`):
  - `bill_twin(record, source)` returns `{"original": id|None, "same_date": bool}` or `None`. It looks only at non-rejected, non-invoice bills (`document_kind='bill'`, `invoice_json IS NULL`) with a lower id than this bill's `(blob_hash, segment)` row (any id while it is not recorded yet), the same merchant and the same `coalesce(due_date, issue_date)`. The account last four must be equal only when both bills print one. `original`: also the same `amount_due_minor` and currency. `same_date`: any such bill with another amount. An invoice, or a record with no provider, date, amount due or currency, gets `None`.
  - `reject_receipt_automatically(receipt_id, original_id=None)` mirrors `reject_automatically`. It refuses when the original is the bill itself or no longer counts, never touches `review_source='user'`, and runs `refresh_splits` when it marks.
  - `mark_bill_void` and `mark_bill_duplicate` call it.
- `documents/extraction.py` `publish`:
  - For `kind == "bill"` it runs on every bill publish, photographed and scanned included. A line where `VOID_LINE.fullmatch` holds gives `BILL_VOID_NOTE` ("This bill is printed VOID, so it doesn't count."). Otherwise `bill_twin` gives `This bill repeats the one from P due D (A), so it doesn't count.` (A is `as_decimal_text`) or `Another bill from P has the same due date.`
  - The note goes to `record_notes` and `details[bill_kind]["notes"]`, never to the issues.
  - After publishing, `mark_bill_void` or `mark_bill_duplicate` runs and the publication's `review_status` becomes `rejected` if it marked.
  - Imports `as_decimal_text`. `BILL_VOID_NOTE` is a new constant.
- `tests/test_bill_split.py` (10 `sc131` tests):
  - (a) BL-MULTI-VOID: bill 2 rejected automatically with the note, recorded with its lines, spending 8142+7472=15614, and Extract again gives identical rows. BL-MULTI-VOIDWORD: three counting bills, 24340. A void bill you verified stays verified (`user`). A scanned bill with a `VOID` line is rejected.
  - (b) MINI-2-ALONE after BL-MULTI: rejected with the exact note, August counts 8726 once, the first file's bills unchanged and keeping their ids on Extract again. After you reject bill 2 and Extract the copy again, it counts (same id, note gone). A scanned copy is a duplicate too.
  - Corrected bill (90.26): both count, the later one has the same-due-date note and waits in review, the first has none, and Extract again is idempotent.
  - (c) BL-ACCT: both count, no note.
  - Invoices: two invoice files with the same provider, due date and total both count.
  - Ledger guards: a bill you decided is not overridden, and a rejected original or a missing id refuses to mark.

## For the orchestrator and reviewers
- **Fixture and reader.**
  - BL-MULTI-VOID's `VOID` at x 260, y 720 (the contract's literal) makes the reader read page 2's summary block by column: labels `Previous Balance`, …, `Total Amount Due`, then `VOID`, then the amounts as lines of their own. The same happens at x 300 and x 600. At x 40, or at y 740 or 800, the lines stay joined.
  - So the default stub's citation (`Total Amount Due`, quote `87.26`) is not in that line. The first summary reply then fails validation, and the retry consumes part 3's reply.
  - I did not change the fixture or any assertion. `recite_split_amounts(run)` in the test patches the stub's citation to the amount's own line, as a model reading those lines would. This is a reader quirk, not an SL-07 behavior.
  - The bill is rejected either way. All contract assertions hold: 3 bills, bill 2 rejected automatically with the VOID note, spending 15614.
  - Reviewers may want to check that the contract's "(a line of its own)" was meant to read this way.
- **Same-file duplicates.** The twin lookup spans the same file (a lower segment/id), but no fixture can produce two identical bills in one file: the split treats an identical key as the same bill continuing. So that case is covered by the lookup alone, not by a test.
- **"Counts" means non-rejected.** A needs_review original still makes a later identical bill a duplicate. This follows the plan (P8.6) and pay stubs.
- **Spending for the corrected bill.** The corrected bill waits in review (carried check), so it is not asserted in spending. The contract asserts its status and note only.
