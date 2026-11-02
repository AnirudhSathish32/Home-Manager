```yaml
slice: SL-01
round: fix (full-suite regression)
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: c6c0fd7
end_head: d607806   # fix commit; the handoff commit follows it
commit: d607806
changed_files:
  - tests/test_statement_accounts.py
checks:
  - command: ".venv/bin/python -m pytest tests/test_statement_accounts.py tests/test_migrations.py tests/test_receipt_tax_codes.py -q"
    exit_code: 0   # 92 passed
  - command: ".venv/bin/ruff check src tests"
    exit_code: 0
escalations: []
```

`Old.take_back` in `tests/test_statement_accounts.py` only dropped `accounts.origin` and set `user_version=72`.
Reopening the library then re-ran 075 on a database that already had its columns, so `ALTER TABLE receipt_items ADD COLUMN tax_code` failed.

`take_back` now also drops `receipt_tax_lines`, `receipts.tax_source` and `receipt_items.tax_code`, so the database is a real v72 shape.
No assertion changed.
The before/after snapshot comparison needs no change: both snapshots are taken after 075 has re-run, so both include the 075 objects.
Migration 075 and application code are untouched.

Other tests checked, none changed:
- `tests/test_migrations.py` replays the real migration files (`next_step`, `MIGRATIONS` slices), so it never leaves a schema with columns ahead of its version. It passed.
- `tests/test_managed_library.py` and `tests/test_receipts.py` build the old database from the real early migration files (001–006 and 001) before opening a `Store`. They don't hand-edit `user_version`.
- `tests/test_backup.py` sets `PRAGMA user_version=1` but only runs `verify_backup`, which doesn't open a `Store`.

I did not run those last three files; I judged them safe by reading them.
