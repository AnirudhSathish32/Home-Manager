# Handoff: bill-kinds SL-01

- **Status:** done (pending orchestrator acceptance)
- **START_HEAD:** 4d9a3e27bb55d8beca0b88d1a0eca4f7c11afadb
- **Commit:** 6adbe16 (`bill-kinds SL-01: bill_kind and line_type columns, v31 extraction version`)
- **Git state after:** clean except the pre-existing `M plans/bill-kinds/progress.yaml` (not touched by this worker) and this handoff.
- **Covers:** FR-52; SC-49 steps 1–2.

## What changed
- `src/home_manager/library/migrations/071_bill_kinds.sql`: nullable `receipts.bill_kind` (rent/general) and
  `receipt_items.line_type` (rent types), CHECKs, `user_version=71`, no backfill, no rebuild (P1, P2).
- `documents/extraction.py`: `EXTRACTION_VERSION = "typed-extraction-v31-bill-kinds"`.
- `finance/ledger.py`: module-level `kind_column(row)`; `publish_receipt` writes the kind to `bill_kind` for bills and
  `receipt_kind` otherwise (the other column NULL), uses that column for the kind-change correction field;
  `current_details`, `correct_detail`'s write-back and `record()` read `details_json[row[kind_column(row)]]`;
  `_replace_items` writes `line_type`; `publish_bill` passes `bill_kind`, `details`, each line's `line_type` and `details`.
- `finance/document_traces.py`: `current()` uses `kind_column` (imported from `.ledger`; no cycle, `provenance` already imports it).
- Tests: `tests/test_migrations.py` `pre_bill_kinds`, `test_071_bill_kinds_leaves_existing_bills_untouched`,
  `test_071_bill_kinds_record_view_of_an_old_bill`; new `tests/test_bill_kinds.py` with
  `test_version_ledger_stores_a_bills_kind_details_and_line_types` and `test_version_changed_and_a_bill_read_under_v30_is_read_again`.

## Interfaces for later slices
- `kind_column(row)` in `finance/ledger.py` (needs `document_kind` in the row).
- `publish_bill` reads `record["bill_kind"]`, `record["details"]`, `item["line_type"]`, `item["details"]`; with no
  `bill_kind`, `merged_details` stores `details_json` NULL (as before).
- Not done here (SL-06 per plan): `chosen_kind(field)`, `_undo_kind`/`undo_corrections` for `bill_kind`, `LINE_FIELDS`/`correct_line` for `line_type`.

## Verification (log: `plans/bill-kinds/logs/slice-SL-01.log`, gitignored by `*.log`)
- `pytest tests/test_migrations.py -k bill_kinds`: 2 passed.
- `pytest tests/test_bill_kinds.py -k version`: 2 passed.
- `pytest tests/test_receipt_kinds.py tests/test_traces.py tests/test_migrations.py tests/test_bills_ledger.py tests/test_invoice_ingestion.py`:
  85 passed, 1 skipped (`test_bills_ledger.py:335`, opt-in local browser test, environment-gated, pre-existing).
- `ruff check` on touched files: clean. `mypy` on `finance/ledger.py`, `finance/document_traces.py`: clean.
  `documents/extraction.py` is outside the configured mypy `files`; a direct run shows 26 pre-existing errors, none on the changed line.

## Escalations / deviations
- The handoff template `$HOME/.agent-harness/templates/handoff-template.md` could not be read (outside the allowed
  read directories); this handoff follows the worker procedure's required content instead.
- SC-49's "rent-like bill with a user line-type correction" is seeded as a `line_kind:2` correction (pre-feature bills
  have no `line_type`), as the plan's SL-01 row states.
