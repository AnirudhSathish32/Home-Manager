```yaml
slice: SL-03
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 30a2ccf
end_head: COMMIT_PLACEHOLDER
commit: COMMIT_PLACEHOLDER
changed_files:
  - scripts/document_splits.py
  - tests/test_document_split.py
checks:
  - command: ".venv/bin/python -m pytest tests/test_document_split.py -k \"sc10 or sc11_count or merged_in\""
    exit_code: 0   # 5 passed
  - command: ".venv/bin/ruff check scripts/document_splits.py tests/test_document_split.py"
    exit_code: 0
escalations: []
```

# SL-03: the FR-09 diagnostic

`scripts/document_splits.py "<inventory.sqlite3>"` opens the file read-only (`?mode=ro`), backs it up into memory, closes it and prints exactly
four lines (FR-09, plan P3). `MERGED_IN` is unchanged, so the migration-080 agreement test still holds.

- `would split: N document(s)` is `count(DISTINCT occurrence_id)` over `MERGED_IN`.
- `split: N document(s)` is `count(DISTINCT from_document_id)` from `document_splits`, 0 when the table is absent.
- `versions moved: N` is the row count of `MERGED_IN` when `document_splits` is absent, else `sum(versions)` (0 when empty).
- `left as a version, history incomplete: N` comes from a new `HISTORY_INCOMPLETE` query: versions of Inbox documents whose
  predecessor has a `managed_files` row outside `Inbox/` and no `managed_organization_events` row at all.

The work runs under `__main__` and in `report(db)`, so `from scripts.document_splits import MERGED_IN` in the tests still imports nothing heavy.
Added a module docstring like db_checks.py's.

Tests (`tests/test_document_split.py`, all through the `merged_library` fixture, the script run in a subprocess):
- `test_sc10_the_diagnostic_reports_counts_only_before_and_after_the_upgrade` checks the exact lines before and after the upgrade (fixture named
  `zz-unique-name.pdf`), that the database bytes and mtime are unchanged by the run, that every line matches the contract regex, and that no
  file name, path, merchant, hash or date appears.
- `test_sc10_the_diagnostic_prints_all_four_lines_for_a_library_that_never_merged` covers a fresh library: four zero lines.
- `test_sc11_count_the_diagnostic_counts_the_version_left_without_history` shows `history incomplete: 1` before and after the upgrade.

Notes for the orchestrator/SL-04: the diagnostic's docs entry under "Database checks" is SL-04's. The "no fixture name/path/merchant" assertion uses
the fixture's `managed_files.relative_path` and `occurrences.path_key` values plus the literals `zz-unique-name`, `SYNTH`, `Bank` and
`Supported metadata`. The script never prints an amount, so no amount assertion was added beyond the digit-run and hash checks.
No open issues; full suite not run (per instructions).
