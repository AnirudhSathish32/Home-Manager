```yaml
slice: fix-081-replay   # regression in SL-04 (migration 081), found verifying SL-07
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 768f2b4
end_head: d3e151b   # the code commit; the handoff commit follows it
commit: d3e151b
checks:
  - command: ".venv/bin/python -m pytest tests/test_statement_accounts.py tests/test_migrations.py -q -p no:cacheprovider -rf"
    exit_code: 0   # 54 passed
  - command: ".venv/bin/python -m pytest tests/test_document_split.py tests/test_statement_accounts.py tests/test_migrations.py tests/test_backup.py tests/test_managed_library.py -q -p no:cacheprovider -rf"
    exit_code: 0   # 110 passed
  - command: ".venv/bin/ruff check tests/test_document_split.py tests/test_statement_accounts.py"
    exit_code: 0
escalations: []
```

SQLite allowed `DROP COLUMN one_category` despite its CHECK (the constraint is on that column only). No src/ file or migration changed.

- `tests/test_statement_accounts.py` `Old.take_back`: added the three DROP COLUMN lines for 081 (receipts.one_category, receipts.tip_worked_out_json, record_corrections.item_categories_json).
- Other helper found: `tests/test_document_split.py` `merged_library` takes a library back to 079 (`SPLIT_STEP - 1`) and so replays 080 and 081. It had the same collision: 17 tests failed before the fix (not in baseline-failures.txt, which predates 081). Added the same three drops. That exposed one assertion: `test_sc13_the_repair_runs_once...` compares full dumps around `apply_migrations(db, 79)`, which now also runs 081 and changes the CREATE text of receipts and record_corrections (columns appended, no row touched). It now ignores those two CREATE statements (helper `without_081_columns`); rows and every other table are still compared exactly.
- Checked, no change needed: tests/test_migrations.py:715 (replays scripts from scratch up to 071, no drops), tests/test_backup.py:116 and tests/test_managed_library.py (edit user_version only to test the version check/backup name, no replay over a latest-shape schema).
- Failures: none in the files run.
