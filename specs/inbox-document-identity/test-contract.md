# Test contract: inbox-document-identity, the one-time repair (FR-06 – FR-10)
Spec sha256: see the bundle hash in approvals/inbox-document-identity.json once approved (gate.py is not on this machine;
`sha256sum specs/inbox-document-identity/spec.md` gives the same value).

Scope. FR-01 – FR-05 (capture) are built (commit 3466ebb, `library/storage.py` `publish`, `RELEASED_PATH`) and tested in
`tests/test_managed_library.py` (`test_a_different_file_under_a_filed_files_inbox_name_is_a_new_document`,
`test_files_reusing_one_inbox_name_stay_their_own_documents_when_dropped_again`,
`test_family_deliveries_under_one_name_are_one_document_each`, `test_changed_inbox_versions_and_readded_identical_file`).
This contract covers the repair of documents merged before that: SC-05 – SC-10 of the spec, and SC-11 – SC-14 added here.

## Definitions used by every scenario (from the spec, made testable)

- **Version order.** A document's versions in `versions.captured_at` order, `versions.id` breaking ties.
- **Merged in** (FR-06). Version k (k ≥ 2) of an Inbox document (`source_kind='inbox'`) was merged in when a
  `managed_organization_events` row for (the document, version k−1's hash) has a `source_path` starting `Inbox/`, a
  `target_path` not starting `Inbox/`, and `created_at` before version k's `captured_at`. Otherwise it is a version
  (FR-02).
- **History incomplete** (spec "Errors"). Version k−1 has a `managed_files` row outside `Inbox/` but no
  `managed_organization_events` row at all. Version k stays a version and is counted (SC-11).
- **Runs.** A document's versions are cut before each merged-in version. Each run becomes one document. The first run
  keeps the document's id (OD-1 default); every other run gets a new id. Its versions keep their order.
- **Following a version.** A row that names the merged document and a `blob_hash` (or, for `extraction_runs`, a
  `parse_run_id` whose `parse_runs.blob_hash`) in a run moves to that run's document. The tables, from the schema
  (`PRAGMA table_info` at migration 079), are:
  `versions` (by `hash`), `managed_files`, `managed_organization_intents`, `managed_organization_events`,
  `library_events`, `document_folders`, `document_segments`, `organization_runs`, `job_filings`, `donation_checks`,
  `extraction_runs`, `statements`, `receipts`, `income_records`, `assets`, `tax_forms`, `investment_confirmations`,
  `investment_events`, `investment_valuations`, `transaction_imports`, `financial_evidence_links`.
- **Rows that name a document but no version** follow a version when one is named through another row, else stay with
  the first run's document (FR-07):
  - `transactions.source_document_id`: the document of its `statement_id`'s statement; else of the `transaction_imports`
    row its `import:<id>` evidence names; else of its first evidence link's `blob_hash`; else unchanged.
  - `recurring_obligations.source_document_id`: the document of its `source_receipt_id`'s receipt; else unchanged.
  - `receipt_batch_items.document_id`: the document of its `run_id` when that names an extraction run of a run's
    version; else unchanged.
  - `occurrence_links` naming the merged document: a link follows the run whose versions include the other
    document's `current_hash` (a `same_bytes` link, R5); else unchanged. A link that would name one document twice
    is removed (R1).
  - `document_descriptions`, `document_group_pages`: unchanged (document-level).
  - `occurrences.deleted_at` (Trash): **open decision OD-5**, see the end. The contract's default is that every split
    document takes the merged document's `deleted_at`: what was in Trash stays wholly in Trash.
- **The Inbox path.** After the repair, the document whose run holds the merged document's `current_hash` holds the
  bare `path_key` and its `source_status`. Every other split document holds `path_key || RELEASED_PATH || id` and
  `source_status='organized'`. Each split document's `current_hash` is its run's last version, `first_seen` its first
  version's `captured_at`, and `relative_path`, `source_root`, `source_kind`, `last_seen` and `last_job` are the
  merged document's.

## Fixtures (synthetic only)

`merged_library(tmp_path, plan)` in `tests/test_document_split.py`:
1. Opens a real `Store` at the latest schema and captures each file of `plan` as its own document through
   `inbox_scan` and `store.library.organize`, so blobs, Library copies, intents and events are real. Records are
   published through the real `Ledger` with the synthetic statement and pay stub fixtures already used by
   `tests/test_statement_accounts.py` (`statement_account_fixtures.s_pages`) and `tests/test_receipts.py`; no model.
2. Rewrites the database into the shape the old capture left (one occurrence, several versions). Every row naming
   documents 2..n names document 1. The occurrences of 2..n are deleted. Document 1 gets the last file's
   `current_hash`, the bare Inbox `path_key` and its `source_status`. Each Library copy is renamed on disk and in
   `managed_files` to the `__d1` name the old capture gave it.
3. Sets `versions.captured_at` and `managed_organization_events.created_at` to the fixed times the scenario names
   (T1 < T2 < …, ISO strings), sets `PRAGMA user_version` to 79, and closes the store.
4. Returns the expected split as data (which hashes go to which run, the records of each), computed from `plan`,
   never by running the repair.

The upgrade under test is reopening the store: `Store(root)` runs every migration above 79.

Nondeterministic components: none (spec). New document ids are found by what they hold (their versions' hashes),
never by value. Times are fixed strings. No model or network: `test_table_engine.no_network` is autouse.

## SC-05 — Three files merged under document.pdf are split, each with its own records
Requirement IDs: FR-06, FR-07
Environment: isolated store under tmp_path; synthetic fixtures only.
Initial state: document 1 with versions A (T1), B (T3), C (T5). A was filed out of the Inbox at T2 and B at T4.
- A carries a confirmed bank statement with 3 rows, each with `extraction:` evidence.
- B carries a pay stub record (`income_records`).
- C has a statement reading that wasn't recorded (an `extraction_runs` row only).
- The Library holds copies `…__d1` for A, B and C.
Actions/checkpoints:
1. Snapshot: row count of every table, every blob's hash, and the bytes of every Library file.
2. Reopen the store -> it opens. `user_version` is the latest. No `MigrationError` is raised.
3. Document 1's versions are [A]; its `current_hash` is A.
4. Exactly two new documents exist, holding versions [B] and [C], one version each.
5. The statement, its 3 transactions and their evidence name document 1:
   - `statements.document_id` and `financial_evidence_links.document_id` are 1, with `blob_hash` A;
   - `transactions.source_document_id` is 1.
6. The `income_records` row names B's document, with `blob_hash` B.
7. The `extraction_runs` row of C's reading names C's document.
8. API: `GET /api/documents` totals 3. `GET /api/documents/{id}/versions` has length 1 for each.
   `GET /api/finance/transactions/{id}` for a statement row gives evidence with `document_id` 1 and `blob_hash` A, and
   document 1's `current_hash` is A. So the page opens A with no "You're viewing an earlier preserved version of this
   document" banner (`document_v2.js` shows it only when the opened hash isn't `current_hash`).
Expected final state:
- Database:
  - every table's row count equals the snapshot, except `occurrences` (+2), and `library_events` (+2 only if the plan
    records splits there; see SC-10);
  - every row of the version-following tables names a document whose versions include its `blob_hash`;
  - the statement keeps `review_status='verified'`, `review_source='user'` and its `review_events`.
- Filesystem: every blob file's bytes and name unchanged; every Library file's bytes unchanged (names: SC-08).
- UI (opt-in browser, `tests/test_document_v2_browser.py`): opening B's document from the library shows B's pay stub
  record and no earlier-version banner; opening A's statement row's evidence shows A with no banner.
Failure/retry/restart variants: reopening a second time changes nothing (SC-13).
Evidence: `.venv/bin/python -m pytest tests/test_document_split.py -k sc05`
Cleanup: tmp_path only.

## SC-06 — A real edit made in the Inbox stays a version
Requirement IDs: FR-06, FR-02
Initial state: document 1 with versions A (T1) and A′ (T2), both captured before any filing. A was archived from
`Inbox/` to Unfiled at T3 (the old "Preserved previous Inbox version", after A′'s capture). A′ was filed at T4.
Actions/checkpoints:
1. Reopen -> document 1 still has versions [A, A′]. No new document. `occurrences` row count unchanged.
Expected final state: database identical to the snapshot except `user_version` (and any split record, of which there
are none).
Evidence: `pytest tests/test_document_split.py -k sc06`

## SC-07 — A tag, folder choice, Trash state and transaction import on B follow B
Requirement IDs: FR-07
Initial state: as SC-05, plus on B:
- a `document_folders` row (B's hash, folder `Housing`);
- a `library_events` row;
- a `transaction_imports` row with 2 imported transactions and their `import:` evidence;
- a `donation_checks` row;
- the merged document in Trash (`deleted_at` set, from the document page's Trash action);
- a `document_descriptions` row.
("Tag" in the spec is the document's description; the library has no other per-document tag table.)
Actions/checkpoints:
1. Reopen -> the following name B's document:
   - the `document_folders` row, `library_events` row, `transaction_imports` row, both imported transactions'
     `source_document_id`, their evidence, and the `donation_checks` row.
2. The `document_descriptions` row stays with document 1 (document-level).
3. Trash: every split document has the merged `deleted_at` (OD-5 default). `GET /api/documents?folder=trash` totals 3.
Expected final state: as SC-05's invariants.
Evidence: `pytest tests/test_document_split.py -k sc07`

## SC-08 — Library copies are renamed to their new ids, durably
Requirement IDs: FR-08
Initial state: after SC-05's upgrade. B's and C's Library copies still carry `__d1`.
Actions/checkpoints:
1. Right after the upgrade, before any organization pass -> each split document's `managed_files.relative_path`
   still names its `__d1` file, and that file opens: `GET /api/documents/{id}/file` returns B's and C's bytes.
2. Run one organization pass (the startup recovery `Store(root)` runs, or `store.library.recover()`) with the rename
   of C's copy failing once (test double: monkeypatch the library's non-overwriting rename to raise `OSError` for C's
   source path on the first call) -> B's copy is now `…__d<B's id>.<ext>` with unchanged bytes, and `__d1` for B is
   gone. C's intent is `pending` or `blocked`, and C's file still opens at its old name.
3. Reopen the store -> C's copy is `…__d<C's id>`, bytes unchanged, and no intent is left pending.
4. A file already at a target name is never overwritten. Test double: before step 2, put a different file at B's
   target name. B's rename is then `blocked` with its error, both files keep their bytes, and B still opens.
Expected final state: every `managed_files.relative_path` of a split document ends `__d<its id>.<ext>` (after step 3),
and no two documents share a file. File count in the Library is unchanged except the decoy of step 4.
Evidence: `pytest tests/test_document_split.py -k sc08`

## SC-09 — A failure in the middle of the repair leaves the library as it was
Requirement IDs: spec "Errors", invariants (all or nothing)
Initial state: as SC-05, plus a fault: the repair aborts after its first new document. Test double, by the plan's form
of the step: for SQL, a `BEFORE INSERT ON occurrences WHEN (SELECT count(*) FROM occurrences) >= 2` trigger with
`RAISE(ABORT, 'test fault')` installed in the fixture; for Python, a monkeypatched helper that raises on its second
call.
Actions/checkpoints:
1. Reopen -> the app starts with the failed-upgrade alert: `storage.MigrationError` naming the repair's step number,
   per `docs/documents.md` "Schema upgrades and recovering from a failed one".
2. `user_version` is 79. A full dump of every table (`iterdump` minus the fault trigger) equals the pre-upgrade dump.
   Every blob and Library file is unchanged.
3. The pre-upgrade copy `inventory.before-v<latest>.sqlite3` exists beside the database.
4. Remove the fault and reopen -> the repair completes as in SC-05.
Evidence: `pytest tests/test_document_split.py -k sc09`

## SC-10 — The diagnostic reports counts only
Requirement IDs: FR-09
Initial state: (a) the SC-05 library before the upgrade, and (b) after it. Fixture file names, merchants and paths are
distinctive (`zz-unique-name.pdf`, `SYNTH UNIQUE BANK`).
Actions/checkpoints:
1. Run `python scripts/document_splits.py "<root>/inventory.sqlite3"` on (a). It exits 0 and opens read-only (the
   file's mtime and bytes are unchanged). Output: `would split: 1 document`, `versions moved: 2`,
   `left as a version, history incomplete: 0`. The wording is the plan's; numbers and fixed words only.
2. Run it on (b) -> `split: 1 document`, `versions moved: 2`, `left as a version, history incomplete: 0`, and
   `would split: 0`.
3. For both outputs, none of these appears: the fixture's file names, merchants, institution, any `relative_path`,
   `path_key`, hash, amount or date. Each line matches `^[a-z ,:()]+: \d+( documents?)?$`.
Evidence: `pytest tests/test_document_split.py -k sc10`

## SC-11 — Missing filing history keeps the version, and is counted
Requirement IDs: FR-06, FR-09, spec "Errors"
Initial state: document 1 with A (T1) and B (T3). A's Library copy is outside `Inbox/`, but its
`managed_organization_events` rows were deleted (a blocked or never-finished move).
Actions/checkpoints:
1. Reopen -> document 1 keeps [A, B]. No new document.
2. The diagnostic prints `left as a version, history incomplete: 1`.
Evidence: `pytest tests/test_document_split.py -k sc11`

## SC-12 — A merged-in version whose bytes exist elsewhere keeps its same_bytes link
Requirement IDs: FR-07, R5
Initial state: as SC-05, plus document 9 at another path with B's bytes, and an `occurrence_links` `same_bytes` row
(1, 9).
Actions/checkpoints:
1. Reopen -> the link names (B's document, 9). No link names document 1 and 9. No link names one document twice.
Evidence: `pytest tests/test_document_split.py -k sc12`

## SC-13 — The repair runs once
Requirement IDs: FR-06, invariants
Actions/checkpoints:
1. After SC-05's upgrade, reopen the store twice -> the database dump is identical after each. No new documents.
   `user_version` unchanged.
2. A library that never had a merged document (each file its own document) -> the upgrade changes no row but
   `user_version`.
Evidence: `pytest tests/test_document_split.py -k sc13`

## SC-14 — The newest file still in the Inbox at upgrade time keeps the Inbox path
Requirement IDs: FR-06, FR-01, FR-03
Initial state: as SC-05, but C was never filed. Its file is still at `Inbox/document.pdf`, and document 1's
`source_status` is `present`.
Actions/checkpoints:
1. Reopen -> C's document holds the bare `path_key` with `source_status='present'`. Document 1 and B's document hold
   released keys and `organized`.
2. `inbox_scan` -> the scan reports `unchanged: 1`, and no document is created.
3. Drop a new file D as `document.pdf` after C is filed -> D is a new document (FR-01).
Evidence: `pytest tests/test_document_split.py -k sc14`

## FR-10 — Docs
Checked by review, not a test: `docs/documents.md` "The managed library" describes the repair, and the open-work item
"Split the documents already merged under one Inbox name" is removed. `docs/development.md`'s schema map lists the
repair step.

## Traceability
| Requirement / scenario | Test | Command |
|---|---|---|
| FR-01 – FR-05 (built) | `tests/test_managed_library.py` (four tests named above) | `pytest tests/test_managed_library.py -k "inbox_name or one_name or readded"` |
| FR-06 | SC-05, SC-06, SC-11, SC-13, SC-14 | `pytest tests/test_document_split.py -k "sc05 or sc06 or sc11 or sc13 or sc14"` |
| FR-07 | SC-05, SC-07, SC-12 | `pytest tests/test_document_split.py -k "sc05 or sc07 or sc12"` |
| FR-08 | SC-08 | `pytest tests/test_document_split.py -k sc08` |
| FR-09 | SC-10, SC-11 | `pytest tests/test_document_split.py -k "sc10 or sc11"` |
| FR-10 | review | — |
| Errors (all or nothing, recovery) | SC-09 | `pytest tests/test_document_split.py -k sc09` |
| Migration ordering | `tests/test_migrations.py` (the latest version and the step's place) | `pytest tests/test_migrations.py` |
| UI (opt-in) | SC-05 step 8 in `tests/test_document_v2_browser.py` | `pytest --browser tests/test_document_v2_browser.py -k split` |

## Open points for the plan's approval (not decided here)
- **OD-5 Trash on a merged document.** `deleted_at` is one flag per document, so the spec's rule that "Trash state
  follows its version" can't apply as written. Default above: every split document keeps the merged one's Trash state.
  The alternative is that only the document holding the merged `current_hash` stays in Trash.
- **Where the repair records what it split** (SC-10 step 2 needs it): `library_events` rows (action `split`, detail
  ids only) or a new table. The plan picks; the contract only asserts the diagnostic's counts and the row-count
  invariant either way.
- **SQL step or Python step.** Migrations are SQL scripts today (`storage.MIGRATIONS`). The repair needs per-document
  logic; the plan says how it runs inside the existing upgrade, snapshot and recovery path (SC-09).
- **Migration numbers elsewhere.** `plans/pdf-table-engine-bills/plan.md` SC-121 expects migrations to end at 077;
  078 – 079 exist now and this repair adds one more. That plan's check needs updating, whichever step number this
  repair takes.
