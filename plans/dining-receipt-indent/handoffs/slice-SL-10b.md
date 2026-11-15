```yaml
slice: SL-10b
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: fe6d547
end_head: 83a904a   # the last code commit; the handoff itself is committed on top of it
commit: 83a904a
changed_files:
  - tests/test_paystub_split.py
checks:
  - command: "/home/anirudh/Documents/Projects/Home-Manager-dining/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_paystub_split.py tests/test_migrations.py tests/test_statement_accounts.py tests/test_document_split.py   (cwd Home-Manager-dining-fix1)"
    exit_code: 0     # 111 passed, 2 warnings (2m18s)
  - command: "python -m ruff check tests/test_paystub_split.py"
    exit_code: 0
escalations: []
```
SL-10b is a test-only fix; no src, spec, approval, plan or progress change.

## What was done
- `library_at_076` (tests/test_paystub_split.py) put the library back to the 076 income_records shape and set `user_version=76`, so reopening reran 077–081 and 081_dining_receipts.sql failed with "duplicate column name: one_category". The helper now first drops what 081 adds (`receipts.one_category`, `receipts.tip_worked_out_json`, `record_corrections.item_categories_json`), with a comment in the style of d3e151b's fixes in test_statement_accounts.py and test_document_split.py. This fixes `test_sc75_the_segment_migration_keeps_every_record_id_value_and_line` and `test_sc75_a_failed_upgrade_leaves_the_old_schema_and_data_untouched`.
- No schema-dump comparison in that file differed, so no assertion was loosened (`snapshot` reads only the income tables).

## Other helpers checked (`grep user_version tests/`)
- test_statement_accounts.py:335 and test_document_split.py:332: already fixed in d3e151b.
- test_migrations.py (lines 48–184, 602, 715, 784, 825 and the rest): every one builds its old schema by replaying `MIGRATIONS` scripts below a number (or a single old script), never from the latest schema, so no 081 column exists to collide. They need no change; the file passes.
- test_receipts.py:121, test_managed_library.py:407 and test_backup.py:116: they build from 001_inventory.sql or only set the version on a backup copy. Same conclusion; no change.
