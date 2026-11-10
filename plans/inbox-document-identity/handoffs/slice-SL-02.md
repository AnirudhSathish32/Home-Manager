```yaml
slice: SL-02
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 3312952
end_head: 2a36bab   # a following commit changes only this header
commit: 2a36bab
checks:
  - command: ".venv/bin/python -m pytest tests/test_document_split.py -p no:cacheprovider -q"
    exit_code: 0   # 14 passed (12 from SL-01 + 2 new)
  - command: ".venv/bin/python -m pytest tests/test_managed_library.py tests/test_capture.py tests/test_library.py -p no:cacheprovider -q"
    exit_code: 0   # 36 passed, 2 skipped (Windows sharing semantics)
  - command: ".venv/bin/ruff check src/home_manager/library/managed_library.py tests/test_document_split.py"
    exit_code: 0
escalations: []
```

# SL-02 handoff: renaming split copies (FR-08)

Covers FR-08, SC-08. The full suite was not run.

## Changed files
- `src/home_manager/library/managed_library.py`
  - `safe_name(name)` pulled out of `filename` (same length / `..` / `/\:` rules); `filename` calls it.
  - `organize(..., name=None)`: a given name replaces the computed one (via `safe_name`) and the full-hash fallback is skipped,
    so a clash reaches `execute` and blocks with "Managed destination contains different bytes. It was not overwritten."
  - `retag_ids()` (new, `@locked`) and its call in `recover()` after `relayout()`: for managed_files rows of documents named in
    `document_splits` (as `document_id` or `from_document_id`), not in Trash, with no pending/blocked intent, whose name ends
    `__d<n>.<ext>` with `n` != `document_id`, calls `organize(..., action="layout", name=<same name with __d<document_id>>)`;
    `(ValueError, OSError, RuntimeError)` caught per row.
- `tests/test_document_split.py`: `test_sc08_split_copies_are_renamed_to_their_ids_durably` (steps 1–4 with the decoy, the fault keyed on
  C's target name wrapping `os.link` / `os.rename` on Windows, step 1 via `storage.apply_migrations` on a raw connection, and a final
  "no second rename" check) and `test_sc08_a_given_name_never_falls_back_to_a_full_hash_name` (unsafe names, clash blocks, bytes kept).

## Notes for the verifier
- **Check (a) needed no change.** SL-01's `counts` already leaves `action='layout'` intents/events out, so SL-01 tests pass unchanged.
- **Contract wording that differs from the repo.** SC-08 step 1 says `GET /api/documents/{id}/file`; no such route exists
  (the app serves the preserved blob at `/api/documents/{id}/preview`). The test checks the managed file at the `managed_files` path
  exists with the document's bytes instead. Not a requirement change.
- **The same pass also relayouts B's copy.** B's pay stub record is dated September, so `relayout()` moves its copy from `2026/10` to
  `2026/09` (keeping `__d1`) before `retag_ids()` renames it there. The test's decoy therefore sits at the `2026/09` target.
- **Step 4 outcome.** With the decoy, B stays blocked at its (relaid-out) `__d1` name across reopens; the test then removes the decoy and
  the blocked intent to show B takes its id, which is test setup, not an app path (a blocked intent is retried by `recover()`, and with the decoy gone it would complete by itself).
- A trashed split document is skipped, as the plan says.

## Open issues
None.
