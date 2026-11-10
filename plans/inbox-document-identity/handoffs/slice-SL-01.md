```yaml
slice: SL-01
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: adff24b
end_head: c3f5ddd
commit: c3f5ddd
checks:
  - command: ".venv/bin/python -m pytest tests/test_document_split.py -k \"sc05 or sc06 or sc07 or sc09 or sc11_version or sc12 or sc13 or sc14 or merged_in or coverage\" -p no:cacheprovider -q"
    exit_code: 0   # 12 passed (all of the file's 12 tests)
  - command: ".venv/bin/python -m pytest tests/test_migrations.py tests/test_receipts.py tests/test_statement_accounts.py tests/test_managed_library.py -p no:cacheprovider -q"
    exit_code: 0   # 78 passed
  - command: ".venv/bin/ruff check tests/test_document_split.py scripts/document_splits.py"
    exit_code: 0
escalations: []
```

# SL-01 handoff: migration 080 and its tests

Covers FR-06, FR-07; SC-05, SC-06, SC-07, SC-09, SC-11 (version stays), SC-12, SC-13, SC-14 and `test_sc14_already_released`.
The full suite was not run (the orchestrator does that once after the last slice).

## Changed files
- `src/home_manager/library/migrations/080_split_merged_documents.sql` (new): all of P1, stages 1–8, as one step.
  Creates `document_splits` (STRICT), builds TEMP tables, inserts the new occurrences before any row moves, moves the 19 version-keyed
  tables plus `versions`, then the rows without a version (`extraction_runs`, `receipt_batch_items`, `transactions`,
  `recurring_obligations`, `occurrence_links`), re-keys the Inbox paths, records the split and drops the TEMP tables.
- `scripts/document_splits.py` (new): only the `MERGED_IN` constant. It returns every version from the first merged-in one on
  (`occurrence_id, version_id, hash, captured_at, previous_hash, merged, run`, `run > 0`). SL-03 adds the report.
- `tests/test_document_split.py` (new, 12 tests): the `merged_library(tmp_path, plan)` fixture, the oracle `check_split`
  (row counts, version-keyed rows, per-run documents, blob and Library bytes, `foreign_key_check`), SC-05 (DB, and API in a second
  test), SC-06, SC-07, SC-09, SC-11 (version), SC-12, SC-13, SC-14, `test_sc14_already_released`, the `MERGED_IN` agreement test
  and the R-a coverage test.

## Notes for the verifier
- **`MERGED_IN` agreement.** The test runs the constant on the pre-upgrade copy and compares it to the versions `document_splits`
  ends up holding. It also asserts that the constant's CTE text (without its last `WHERE run > 0`) appears, whitespace-normalised, in
  the migration file, so the two copies can't drift apart silently.
- **Small refinement of P1 stage 6.** The plan says "base is the stored `path_key` up to its first `|`". The SQL finds the
  already-released form by the `|released-d` marker (`storage.RELEASED_PATH`) instead, and takes the whole key as base otherwise. The result
  is the same for every key the app writes. It only differs for a Linux file name containing `|`, which the plan's rule would cut wrongly.
  Not a requirement change.
- **Event test uses `substr(...,1,6)='Inbox/'`** rather than `LIKE 'Inbox/%'`: the same for every path the app writes, but exact on case.
- **Fixture details that differ from the contract's wording.**
  - Files are `document.pdf` (`document.csv` for SC-07, whose B needs a real CSV import). Their bytes are synthetic text, not PDFs: no
    test here reads them.
  - SC-05 files C too (at T6), as the plan's "Test environments" says; the contract's SC-05 text lists only A's and B's filings.
  - Document ids are found by hash and never by value. SC-12's "document 9" is a real second capture of B's bytes as `copy.pdf` (so the
    `same_bytes` link is the real one), found by `merged.other`.
- **SC-13 step 2 runs the step alone** (`storage.apply_migrations(db, 79)`), not `Store(root)`: the startup `recover()` itself bumps
  `library_revision` on the first reopen of any fixture library, which is unrelated to the repair.
- **Not done here (later slices):** FR-08 renames (`organize(name=)`, `retag_ids`), the diagnostic report, docs and the opt-in browser
  checkpoint. `check_split` already leaves `action='layout'` organization rows out of the row-count comparison, as the plan says for
  SL-02 on.
- **Untouched:** spec, contract, plan, `reviews.md`, `progress.yaml` (its pre-existing modification is not mine and is not in the
  commit), `approvals/`, and the other features' untracked files.

## Open issues
None found. `plans/pdf-table-engine-bills/plan.md` SC-121 ("migrations end at 077") is stale already; the plan records it as R-d and it is not edited here.
