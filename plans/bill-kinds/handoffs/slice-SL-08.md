# Handoff: slice SL-08 — eval, regressions and docs

```yaml
result: done
start_head: b208ad19615262d7c63a567f712b46b0543ccde1
end_head: cfaf0f8
commit: cfaf0f8
verification_command: RUN_BROWSER_TESTS=1 python -m pytest tests/test_bill_kinds.py tests/test_bill_kinds_browser.py tests/test_bills_ledger.py tests/test_recurring_bills.py tests/test_invoice_ingestion.py tests/test_migrations.py tests/test_eval_tasks.py tests/test_document_v2_browser.py tests/test_budgets.py -q
verification_result: passed (167 passed, 0 skipped)
log: plans/bill-kinds/logs/slice-SL-08.log
escalations: 0
```

## What was built
- `evals/tasks/document_forms.py` gains the RENT case (index 5, tags `bill`, `rent`). It's read whole, with its kind taken from the sorting step. It reports kind, Issued, period, due, line count, the water line's type and amount due, and the report has a Bills table of each field's right count (SC-51, FR-53). VERSION is now `document-forms-v3`.
- `tests/test_eval_tasks.py`:
  - all-correct RENT row;
  - a wrong Issued (2026-10-01 cited on the rent line) → only Issued wrong;
  - it asserts the task's RENT equals `bill_kinds_fixtures.RENT`.
- `tests/test_bill_kinds.py`:
  - `test_sc46d_…`: a RENT bill shared by line, Rent to Alex and Water to Blair. The plan is 145000/3842. Alex's 148842 payment counts only 145000 housing (FR-57).
  - `test_version_a_v30_bills_line_kind_correction_survives_…`: a bill set to its v30 state, with a person's `line_kind:2` correction. Extract again: not reused, the kind becomes rent, Water is (`utility`, `service`) and the correction is kept (SC-49 step 3).
- Docs:
  - `docs/money.md` "Bills and their lines" covers bill kinds, the rent form, rent checks, date rules, corrections, budgets, the page and the earlier balance row.
  - `docs/documents.md` has a new "Bill kinds" section after "Receipt kinds".
  - `docs/open-work.md` adds utility/phone/insurance kinds, family routing not carrying `bill_kind`/`line_type`/details, and live accuracy.
  - `docs/evals.md` covers the RENT case.
  - Docs citations were added in `extraction.py` (`BILL_KINDS`, `bill_dates`) and `ledger.py` (`bill_summary`).

## Interfaces now available
- `document_forms.RENT`, `RENT_FIELDS`, `BILL_FIELDS`, `bill_output(config, work, lines, notes)`.
- The bill grade adds `checks["right"]: {field: bool}`.
- `tests/test_bill_kinds.py::october_spending(store)`.

## Decisions and deviations
- The bill eval asks Classification instead of passing a known one, so the kind is measured. Other cases are unchanged.
- In the wrong-Issued test, the date cites the rent line. A due-line citation would be dropped by FR-46 and show as right.
- The v30 state is made with SQL: the kind, details and line types are cleared, the run's version is set to v30 and the bill is put in `needs_review`. This follows SC-43 step 5's existing approach.
- SC-46d uses `set_line_member`, because rent lines have no phone holder.

## Open issues / escalations
None. mypy on `evals/` shows 3 errors that were already there, in `evals/tasks/library.py` and `evals/corpus.py`; none are in the touched module.
