```yaml
slice: SL-05
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 219c55f
end_head: 81b28ad   # a following commit changes only this header
commit: 81b28ad
changed_files:
  - src/home_manager/library/storage.py
  - src/home_manager/library/migrations/080_split_merged_documents.sql
  - tests/test_capture.py
  - tests/test_document_split.py
  - tests/test_managed_library.py
checks:
  - command: ".venv/bin/python -m pytest tests/test_document_split.py tests/test_managed_library.py tests/test_library.py tests/test_statement_accounts.py tests/test_migrations.py tests/test_capture.py tests/test_trash.py tests/test_receipts.py -q -p no:cacheprovider"
    exit_code: 0   # 131 passed, 2 skipped (Windows sharing semantics in test_capture.py)
  - command: ".venv/bin/python -m pytest tests/test_document_split.py tests/test_managed_library.py tests/test_capture.py -q -p no:cacheprovider"
    exit_code: 0   # 55 passed, 2 skipped; re-run after the final ruff import fix in test_document_split.py
  - command: ".venv/bin/ruff check src/home_manager/library/storage.py tests/test_document_split.py tests/test_managed_library.py tests/test_capture.py"
    exit_code: 0   # All checks passed
escalations: []
```

# SL-05 handoff: fixes for code review round 1

The full suite was not run (the orchestrator does that once). `tests/test_migrations*.py` is the one file `tests/test_migrations.py`; I added `test_capture.py`, `test_trash.py` and `test_receipts.py` (the upgrade-from-v1 test) to the run because the changes touch capture, the Trash purge and every migration step.
Each new test was also run against the pre-fix `storage.py` and 080 (stashed): all six fail there and pass with the fix.

## Findings, fixes and tests
- **CR1-1 (MAJOR), `storage.py` `Store.publish`.** The intent's job date is read first. The organized Inbox path is released only when `previous["job_created"] <= intent_job_date`. A stale intent skips the release and the released lookup and reaches the existing `recovered_version` branch. The released lookup moved out of the release `if` (see CR1-3).
  - Test `tests/test_capture.py::test_recovering_an_older_capture_after_the_newer_version_was_filed_makes_no_second_document`, next to `test_recovery_preserves_newer_current_version`. Asserts `occurrences` is exactly `[(id, "document.csv", newest hash, "organized")]`, the three versions, no capture intent left and the job counted `{"recovered_version": 1}`.
- **CR1-2 (MAJOR), 080 `split_links`.** The plan's amended rule. New TEMP tables `split_link_pieces` (the pieces of each split document, and each unsplit linked document as its own only piece) and `split_link_pairs` (`ROW_NUMBER()` over the pairs holding a version with the same hash, ordered by the later of the two shared versions' `captured_at` DESC, then the a-side id, then the b-side id; the versions are those after stage 4). A `same_bytes` link with no pair gets NULL and is deleted. `same_record` and other reasons keep their pair. The `min()`/`max()` `OR IGNORE` insert, the delete of the old row and the "one document twice is deleted" rule are kept. Both new tables are dropped in stage 8.
  - Test `tests/test_document_split.py::test_cr1_2_a_link_between_two_merged_documents_names_the_pieces_that_share_a_file`: `A→B→C` as `document.pdf` and `B→D` as `copy.pdf`, linked when B arrived twice. After the upgrade the only link is `(min, max, same_bytes)` of the B piece and the `copy.pdf` document, which now holds only B. The fixture gained a `copy=[entry…]` plan key (merged under `copy.pdf` too) and `Merged.copies`.
  - Test `…::test_cr1_2_a_same_bytes_link_with_no_shared_file_left_is_dropped`: no pair, no link.
  - `test_sc12…` stays green.
- **CR1-3 (MINOR), `storage.py` `Store.publish`.** When no occurrence holds the bare key (the holder was permanently deleted), the released lookup (same `source_root`, `path_key + RELEASED_PATH`, `current_hash` equal) runs too and, when found, gives the document its bare key back. The key is reclaimed only when the found document's job isn't newer than the intent's.
  - Tests in `tests/test_managed_library.py`: `test_dropping_earlier_bytes_again_after_the_holder_of_the_name_was_deleted_finds_the_earlier_document` (Inbox files: A, B, B purged through `trash.empty`, A again → `unchanged`, id of A, one row `(id, "document.csv", A, "organized", NULL)`, one version) and `test_a_family_delivery_dropped_again_after_the_holder_of_the_name_was_deleted_is_the_earlier_document` (`import_document`).
- **CR1-4 (MINOR), 080 `document_splits`.** `from_document_id` is now `INTEGER NOT NULL` with no `REFERENCES` (provenance; the comment says why). The upgrade runner's broken-reference check and the whole migration run pass. `retag_ids`' `from_document_id IN` clause still behaves: it selects only `managed_files` rows of documents that exist and aren't in Trash, and skips a file already named for its own id, so a stale `from_document_id` (even one whose id is later reused) renames nothing it shouldn't.
  - Test `tests/test_document_split.py::test_cr1_4_a_restored_piece_is_still_renamed_after_the_original_is_emptied_from_trash`: trashed merged document upgraded, B restored, `trash.empty` (2 documents purged), `recover()`. Asserts only B remains in `occurrences`, its `document_splits` row `(B, 1)` survives, `managed_files` has one row named `…__d<B>.pdf` with a succeeded `layout` intent, the Library holds only that file and its bytes hash to B's.

## Notes for the verifier
- Not touched: spec, test-contract, plan, approvals, progress.yaml, reviews.md, `managed_library.py`, `scripts/document_splits.py`, docs (the `docs/development.md` 080 row still reads right: it lists the columns and says nothing of a foreign key), other features' untracked files.
- The tie-break "lowest ids" is implemented as the a-side piece id, then the b-side piece id (a side being the link's `occurrence_id`). The plan says only "the lowest ids".
- Not tested by a scenario of its own: several candidate pairs (the ordering is in the SQL), and a link between a split document and a non-split one beyond SC-12.

## Open issues
None.
