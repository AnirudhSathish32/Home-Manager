# Handoff: slice SL-07 — a kinded bill's page

```yaml
result: blocked   # code done and committed; one existing regression test conflicts with FR-50 (escalation 1)
start_head: 416af132b590dfd34911e9f9eedb1524a5c7ab94
end_head: 01bc6f1
commit: 01bc6f1
verification_command: RUN_BROWSER_TESTS=1 pytest tests/test_bill_kinds_browser.py tests/test_document_v2_browser.py tests/test_bills_v2_browser.py tests/test_records_v2_browser.py -q; pytest tests/test_bill_kinds.py -k summary -q; pytest tests/test_bill_kinds.py tests/test_receipt_kinds.py tests/test_bills_ledger.py tests/test_invoice_ingestion.py tests/test_ui_parity.py tests/test_style_tokens.py -q; ui_shots.py (synthetic)
verification_result: 13 passed; 6 passed; 164 passed, 1 FAILED (test_bills_ledger browser test, below); ui_shots 24 shots, no overflow, no page errors
log: plans/bill-kinds/logs/slice-SL-07.log
escalations: 1
```

## What was built
- `Ledger.bill_summary` (in `record()`), for non-invoice bills with a `bill_kind`:
  - `carried` rows (Previous balance, Payment received as a negative), each with `line_ids`.
  - `earlier_balance` when nothing carried is printed and the lines check passed against printed new charges.
  - Otherwise `gap`, with the failing check's issue text as its reason.
  - `amount_due` with the cited line ids.
  - It's None for invoices and for bills read before kinds.
- The Type entry in a rent line's `correctable` is now `line_type` with the `RENT_LINE_TYPES` choices.
- `receipt.js`:
  - `RENT_TYPE_LABELS`, plus `billLineFacts`: each line's period (or one date) and usage, each with Find.
  - `billSummaryRows`: the tfoot ends with Amount due (`tr.bill-total`, a rule) with Find and Correct.
  - A rent line with no `line_type` shows its line kind under the Type choice "Not set".
  - The "Only the new charges count" paragraph is gone for kinded bills.
- `document_v2.js`:
  - Kinded bills drop New charges, Amount due, Counts as, and an Issued they don't print.
  - Bills that aren't invoices get the kind control (`BILL_KINDS`, "Bill kind"), and `doc2Pending` labels by the record's kind.
  - Bill notes show as a muted list, and a whole-month period shows "Worked out from “…”".
- `ui.js` has `dateRangeText`, which `records_v2.js` uses. `style.css` adds the `.bill-total` rule and `.doc2-notes`.
- Tests:
  - `tests/test_bill_kinds.py -k summary` (6 tests).
  - The new `tests/test_bill_kinds_browser.py` covers sc48 steps 1–8 (360 px, console/CSP clean) and one test covering sc46 a/b, sc46e b and phone.
  - `seed_documents.document_server` takes a `seed(manager, model)` callback.

## Decisions and deviations
- A gap's reason sits in the wide cell beside the amount, because `th` is nowrap and the reason widened the Line column.
- The synthetic before/after shots of the bill pages come from a scratchpad script (`document_server` with these seeds). The household seed has no bill, and adding one would change the shared agent instance. `ui_shots.py` ran on its default routes as a regression check.
- The Counts as rule follows the plan literally (`bill && bill_kind`), so invoices, which are now `general`, also lose Counts as.

## Open issues / escalations
1. `tests/test_bills_ledger.py::test_bills_and_pay_stubs_on_transactions_and_the_document_page` (line 371) expects "Only the new charges count" on the PHONE page. FR-50 and the plan remove that paragraph for kinded bills (PHONE is now `general`). Plan R3 checked only the v2 browser suites, and SC-50 says "pass unchanged", so I left it unedited. Recommended fix: assert "Earlier balance" instead. This needs a user decision.
- Git state: clean apart from the existing `M progress.yaml` and this handoff. The log is git-ignored. Docs are left for SL-08.
