```yaml
slice: SL-06
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 244dee0
end_head: 12dbb13
commit: 12dbb13   # code commit; the handoff is the commit after it
checks:
  - command: ".venv/bin/python -m pytest tests/test_paystub_split.py -k \"sc75 or library\" -q"
    exit_code: 0   # 5 passed
  - command: ".venv/bin/python -m pytest tests/test_migrations.py tests/test_library.py tests/test_managed_library.py tests/test_paycheck.py tests/test_reconcile_tools.py tests/test_donations.py -q"
    exit_code: 0   # 68 passed
  - command: ".venv/bin/python -m pytest tests/test_receipt_segments.py tests/test_bills_ledger.py tests/test_correction_preview.py tests/test_paystub_engine_record.py -q"
    exit_code: 0   # extra: 62 passed, 1 skipped (opt-in browser test)
  - command: ".venv/bin/ruff check src tests"
    exit_code: 1   # only the 2 errors present at START_HEAD (tests/test_document_v2_browser.py:410, tests/test_receipt_kinds.py:977); my files are clean
escalations: []
```

# SL-06: storage for several pay stubs per file

## Changed files
- `src/home_manager/library/migrations/077_income_segments.sql` (new; 077 was the next free number). One script (the runner wraps it in one transaction), table-rebuild pattern of 054: `segment INTEGER NOT NULL DEFAULT 0 CHECK (segment BETWEEN 0 AND 199)` after `blob_hash`, `UNIQUE (blob_hash, segment)` replacing the column `UNIQUE`; every row copied with its id as segment 0; all later columns (`review_source`, `*_ytd_minor`, `work_state`, `pay_frequency`, `details_json`) carried over. Verified in `sqlite_master` of a fully migrated schema: `income_records` has no index or trigger besides the autoindex of its unique constraint, so none is recreated (stated in the script's header).
- `src/home_manager/finance/ledger.py`: `_upsert` keys `income_records` by `source["segment"]` like receipts (so `publish_income` needed no change: it already passes `source`); `retire_segments(blob_hash, keep, note=None)` now retires receipts and pay stubs by the same rules. Default notes: "…no longer finds this receipt…" / "…no longer finds this pay stub; check how the file was split." An explicit `note` (the combined-document call at `app/manager.py:1411`) applies to both. `refresh_splits` is receipt-only.
- `src/home_manager/library/storage.py` (library query): income `pay_date` and `document_date` = `min(pay_date)` over non-rejected records; merchant `ORDER BY segment LIMIT 1`; amount and currency only when exactly one non-rejected record (`CASE WHEN count(*)=1 …`); `ledger_status` takes the receipt-style order (needs_review, proposed, verified, rejected); `reconciliation_status` takes the worst state per file.
- `src/home_manager/library/managed_library.py:506`: payer `ORDER BY i.segment LIMIT 1`.
- `src/home_manager/documents/donations.py:57`: `segment=0` for `income_record` too.
- `tests/test_paystub_split.py` (new): `sc75` x2 and `library` x3 tests (below).

## Tests (expected values from the contract / hand-written inputs)
- `test_sc75_the_segment_migration_keeps_every_record_id_value_and_line`: a library with two income records (ids 1, 2) published by `Ledger.publish_income` with 2 lines each and one reconciled `transaction_income_links` row, put back to the 076 shape (see note 1), then started: ids, every column value (incl. created/updated stamps), lines and the link unchanged; segment 0; `PRAGMA foreign_key_check` empty and foreign keys back on; a second segment-0 row for the same file refused; segment 200 refused; segment 1 for the same file accepted (rolled back); unique index is `(blob_hash, segment)`.
- `test_sc75_a_failed_upgrade_leaves_the_old_schema_and_data_untouched`: 077's own script with a bad statement before its version pragma → `MigrationError` at step 77, version 76, snapshot of records/lines/links/columns/unique index equal to before, no `income_records_new`; the real script then finishes the upgrade on the next start.
- `test_library_row_of_a_file_with_two_pay_stubs_…` (`GET /api/documents/{id}`): segment 0 = later stub (2026-06-19, employer OTHER SYNTH CO), segment 1 = earlier (2026-06-05) published first → `ledger_amount*` and currency None, `document_date` and `pay_date` 2026-06-05, merchant = segment 0's employer, `ledger_status` needs_review. Re-publishing segment 0 gives the same id. A one-stub file still lists amount 180000 USD, its date, employer and status.
- `test_library_row_counts_only_pay_stubs_that_are_not_rejected`: `retire_segments(hash, [0])` rejects segment 1 automatically with the pay-stub note and the file gets its amount back; publishing segment 1 again restores it. And `test_library_retiring_a_pay_stub_the_user_decided_…`: user-decided stub keeps status/source, gets the note once (not doubled).
- Mutation check: with `storage.py` at START_HEAD the two library-row tests fail.

## Notes and open items for the orchestrator
1. **SC-75 fixture.** `Ledger.publish_income` at the 076 schema is impossible with the new `_upsert` (it writes `segment`), so the previous-schema library is made by publishing at the current schema, then rebuilding `income_records` to the 076 table text (read from migrations ≤ 076, not copied by hand) with foreign keys off and `user_version=76`. The lines and the link come from the real publish and reconcile.
2. **SC-75 step 2 (three-stub file extracted twice) is not written**: it needs SL-07's split. Left for SL-07; the record-id stability it asserts is already guaranteed by `_upsert` keying on `(blob_hash, segment)` (covered here by the re-publish check).
3. **Behaviour change for a single rejected record**, per the plan's "non-rejected" wording: a file whose only pay stub is rejected now shows no `ledger_amount`/`document_date` in the library (receipts already behave so); before, those subqueries did not filter rejected. A one-stub, non-rejected file is unchanged. Tell me if the old behaviour for the rejected single stub must be kept.
4. **Reconciliation status for several stubs:** a stub with no deposit has no state (NULL, today's single-stub result), ordered after `ambiguous` and before `proposed`, so a file with one matched and one unmatched stub shows no status rather than "Matched". Plan said "receipt-style worst state"; this is my reading for income's NULL. Not covered by a test (no test in the contract for it).
5. `retire_segments` now also retires pay stubs when called with `keep=[]` from `app/manager.py:1411` (a page absorbed into a combined document): same rules, using that call's note. Intended by "same rules"; no existing test exercised it for pay stubs.
6. The library `title` ("Merchant + n more") is still receipt-count based; split pay stubs are not part of FR-84's contract in this slice. SL-07 may want it.
7. Docs: the heading "Several pay stubs in one file" cited in the migration's header is written in SL-09 per the plan.
