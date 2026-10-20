# Handoff: bill-kinds SL-02

- **Status:** done (pending orchestrator acceptance)
- **START_HEAD:** 99e24a58ae23431924d2cf9e9b5585fad952a747
- **Commit:** d7bcb3f (`bill-kinds SL-02: rent form, bill kind and rent lines`)
- **Git state after:** clean except the pre-existing `M plans/bill-kinds/progress.yaml` (not touched) and this handoff.
- **Covers:** FR-40, FR-41, FR-43, FR-44, FR-45, FR-45b; SC-38 (1–3, lines, C-*), 38a–38d, SC-43 1–4 + 43a/43b variants, SC-43b + 43b-1, SC-44 a–d, SC-50 PHONE part.

## What changed (`documents/extraction.py`)
- `BILL_KINDS`, `Classification.bill_kind(_evidence)`, CLASSIFY sentence, `bill_kind()` (note "Bill kind: … read as a general bill.").
- `BILL_KIND_FIELDS`, `BILL_FORMS`/`BillRentSummary`, `BILL_KIND_LABELS`, `RENT_ROWS` (FR-58 sentence), `RENT_LINE_TYPES`, `RENT_LINE_KINDS`, `UTILITY_WORDS`, `RENT_CATEGORIES`, `RentBillLine(s)`; `monthly_rent` in `AMOUNTS`.
- `printed_dates`, `date_printed(value, evidence, due)`, `month_printed`.
- `extract()` picks the kind; new `read_form()` holds the old header+rows body. Rent failing → notes from that attempt dropped, `"Read as a general bill: …"`, general re-read.
- `normalize(..., bill_kind=)`; `bill_lines(..., fields, bill_kind)` + `rent_line()`: type/FR-45b/category, line period (printed / whole_month / year_from_due / dated line → `details.date`), usage, notes in `record["details"]["notes"]`, "No rent line was read.", rent details `previous_balance`/`payments_received`/`monthly_rent` as `{minor, locator}` when printed; invoice → `bill_kind` general. `publish` passes `bill_kind`.
- A requested kind is used for a bill only if it is in `BILL_KINDS` (SL-06 reworks `requested_kinds`).

## Interfaces for later slices
- `date_printed`, `printed_dates`, `month_printed`; `bill_lines` notes list (note-only channel); `rent_line` already does FR-55 year notes for lines.
- Tests: `tests/bill_kinds_fixtures.py` (`RENT`, `rent_replies`, `general_replies`, `rent_row`, `water_row`, `with_line`, `rent_plain`); `read_bill`, `stored_lines`, `assert_published_bill` in `tests/test_bill_kinds.py`.

## Verification (log: `plans/bill-kinds/logs/slice-SL-02.log`)
- `pytest tests/test_bill_kinds.py -k "sc38 or sc43 or sc44"`: 20 passed. The whole file: 33 passed.
- `pytest tests/test_bills_ledger.py tests/test_invoice_ingestion.py tests/test_extraction.py`: 43 passed, 1 skipped (opt-in browser).
- `pytest tests/test_receipt_kinds.py tests/test_eval_tasks.py tests/test_traces.py tests/test_recurring_bills.py tests/test_migrations.py`: 93 passed.
- Also run: `test_agent_instance`, `test_family_routing`, `test_document_v2_browser`, `test_bills_v2_browser`: 36 passed, 12 skipped (opt-in browser tests, not run).
- `ruff`: clean. `mypy extraction.py` (outside configured files): 29 errors, 26 before; the 3 new ones are the same kinds already there (`Literal[*X]`, `create_model`).

## Escalations / deviations
- **Existing test edited:** `tests/test_receipt_kinds.py::test_sc06…` asserted `details_json` NULL for an invoice. Under FR-40 an invoice is now `bill_kind='general'`, so `details_json` is `{"general": {}}`. The assertion now checks `receipt_kind` NULL, `bill_kind` general and that details value. Revert it if this isn't wanted.
- `previous_balance` was **not** added to `OPTIONAL_FIELDS`, though the plan says to. It is a required credit-card-statement field, and adding it would change that schema and its ambiguity check. It is optional on the rent form through its default anyway.
- Bill `details` hold only the rent fields and notes. Printed `new_charges` in details is left to SL-04/SL-07. Adding it now would show an empty "Printed details" heading on general bills.
- 38d sends the bill to review through the existing cross-check reason; the test doesn't assert review.
- The handoff template under `$HOME/.agent-harness` was not read; this handoff follows the worker procedure.
