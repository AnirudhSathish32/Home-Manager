```yaml
slice: SL-06
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 043aa76
end_head: cb01afd   # a following commit changes only this header
commit: cb01afd
changed_files:
  - src/home_manager/library/storage.py
  - tests/test_managed_library.py
checks:
  - command: ".venv/bin/python -m pytest tests/test_document_split.py tests/test_managed_library.py tests/test_library.py tests/test_statement_accounts.py tests/test_migrations.py tests/test_capture.py tests/test_trash.py tests/test_receipts.py -q -p no:cacheprovider"
    exit_code: 0   # 133 passed, 2 skipped (Windows sharing semantics in test_capture.py)
  - command: ".venv/bin/ruff check src/home_manager/library/storage.py tests/test_managed_library.py"
    exit_code: 0   # All checks passed
escalations: []
```

# SL-06 handoff: fixes for code review round 2

## Findings, fixes and tests
- **CR2-1 (MAJOR), `storage.py` `Store.publish`.** The released-document lookup now has `AND o.deleted_at IS NULL`. With no live match the drop creates a new occurrence as usual (`duplicate`, with a `same_bytes` link to the trashed one), is filed and listed; the trashed document keeps its released key and stays in Trash.
  - Tests in `tests/test_managed_library.py`, next to the CR1-3 tests, sharing one helper `_a_trashed_earlier_document_is_not_reclaimed(store, purge_b)`: `test_dropping_earlier_bytes_again_after_it_was_trashed_and_the_holder_of_the_name_was_deleted_is_a_new_document` (A, B filed as `document.csv`; B trashed and emptied through `trash.empty`; A trashed through `library_action`; A's bytes dropped) and `…_while_another_holds_the_name_is_a_new_document` (B keeps the name). Both use the real trash and purge paths and assert the persisted end state: counts `{"duplicate": 1}` (no `organization_failed`), a new live document `organized` holding A's bytes and listed by `documents()`, no Inbox file left, trashed A's row unchanged (same key, hash, status, `deleted_at` set), the blob intact.
  - Both fail on the pre-fix `storage.py` (stashed): `{'organization_failed': 1, 'unchanged': 1}`; both pass with the fix.

## Notes for the verifier
- Not touched: spec, test-contract, plan, approvals, `progress.yaml` (modified in the checkout by the orchestrator, left unstaged), other features' untracked files, docs.
- Bare-key `previous` lookup left unchanged, as instructed. **It shows the same mismatch** in a different sequence: A filed and trashed (A still holds the bare `document.csv`), A's bytes dropped again. Probe (a scratch test, not kept): counts `{'organization_failed': 1, 'unchanged': 1}`, A still trashed, zero listed documents, the Inbox file left behind. This predates the feature (a trashed holder of the bare key is found by the bare-key lookup, not the released one). Reported, not fixed.

## Open issues
- The bare-key trashed-holder case above needs a decision (spec / plan scope) before a fix.
