# Split documents merged under one Inbox name — implementation plan
Spec: specs/inbox-document-identity/spec.md
Spec sha256: ff52135c2aad27d054d28eed04a1dd55e1d87e45e1e44d05c57e8ac80cdac7e6 (spec.md + test-contract.md)
Review-Risk: HIGH
Review-Risk-Rationale: A schema upgrade rewrites document identity across about 25 tables of the user's financial library,
and a later pass renames Library files. A wrong row move would attach statements, pay stubs or evidence to the wrong
file.

<!-- Approval lives in approvals/inbox-document-identity.json, bound to this file's hash. No Status line.
     Execution progress goes in plans/inbox-document-identity/progress.yaml, never in this file. -->

Scope: FR-06 – FR-10 and SC-05 – SC-14 of the test contract (four slices). FR-01 – FR-05 are built (`3466ebb`, `library/storage.py`
`publish`, `RELEASED_PATH`). Decisions D3 and D4 of the spec are settled: the earliest file keeps the id (OD-1), watched
folders are out of scope (OD-2), there is no "split from" link (OD-4), and Trash applies to every piece (OD-5).

## Verified repository integration points
Read at `3466ebb`.
- **Upgrade runner.** `library/storage.py` `_apply_migrations` (`:132`) runs each `migrations/NNN_*.sql` as
  `BEGIN IMMEDIATE` + script, then checks the script set `user_version` to its number and left no new broken reference
  (`reference_problems`), then `COMMIT`. On any `sqlite3.Error` it rolls back and raises `MigrationError(number, version,
  snapshot)`. The snapshot `inventory.before-v<latest>.sqlite3` is taken before upgrading (`docs/documents.md` "Schema
  upgrades and recovering from a failed one"). Foreign keys are off while scripts run. `docs/development.md` "Adding a
  migration": no `BEGIN`/`COMMIT` in the script; end with `PRAGMA user_version=NNN;`. The highest step is 079.
- **SQLite** 3.50.4 in the venv. Window functions (`LAG`, `SUM() OVER`) and `CREATE TEMP TABLE` are available inside a
  script.
- **Identity tables** (`PRAGMA table_info` at 079):
  - `occurrences(id, source_root, path_key, relative_path, current_hash, source_status, first_seen, last_seen, last_job,
    deleted_at, source_kind)`, `UNIQUE(source_root, path_key)`;
  - `versions(id, occurrence_id, hash, captured_at, source_mtime_ns)`, `UNIQUE(occurrence_id, hash)`.
- **Tables naming a document and a version** (`document_id` + `blob_hash`): `managed_files` (PK
  `(document_id, blob_hash)`, `relative_path UNIQUE`), `managed_organization_intents`, `managed_organization_events`,
  `library_events`, `document_folders` (PK `document_id`), `document_segments`, `organization_runs`, `job_filings` (PK
  `(document_id, blob_hash)`), `donation_checks`, `statements`, `receipts`, `income_records`, `assets`, `tax_forms`,
  `investment_confirmations`, `investment_events`, `investment_valuations`, `transaction_imports`,
  `financial_evidence_links`.
- **Tables naming a document without a version**:
  - `extraction_runs(document_id, parse_run_id)`, whose version is `parse_runs.blob_hash`;
  - `transactions.source_document_id`;
  - `recurring_obligations.source_document_id` with `source_receipt_id`;
  - `receipt_batch_items(batch_id, document_id, run_id, reused)`;
  - `occurrence_links(occurrence_id < other_occurrence_id, reason IN ('same_bytes','same_record'), UNIQUE(...))`;
  - `document_descriptions(document_id)` and `document_group_pages(group_id, occurrence_id)`.
- **Filing history.** `managed_library.py` `finish` (`:354`) writes `managed_files`, a `managed_organization_events`
  row (`source_path`, `target_path`, `created_at`) and, for an Inbox document, `source_status='organized'`.
- **Library names.** `managed_library.py` `filename` (`:95`) ends every name `__<hash16>__d<document_id>.<ext>`.
  `organize` (`:233`) records a durable intent and never overwrites. Its `keep_name=True` keeps the existing name;
  there is no way yet to give a name.
- **Startup.** `ManagedLibrary.recover` (`:481`) re-runs pending or blocked intents, fills missing copies, then
  `retire_folders()` and `relayout()`. Both skip documents with a pending or blocked intent, and documents in Trash.
- **Family copies** are keyed by `blob_hash` (`app/family_sync.py` `CITING_TABLES`, `cited_blobs`). So R2 needs no
  change: a split moves no hash.
- **Read-only checkers** follow `scripts/db_checks.py`: open `?mode=ro`, back up into memory, close, then report.

## Architecture, contracts, data flow and decisions
**P1 One SQL upgrade step, `080_split_merged_documents.sql`.** It runs inside the existing runner, so it inherits all or
nothing, the snapshot, the broken-reference check and the recovery message (SC-09) with no runner change. No Python
step type is added. The step creates `document_splits` and then repairs, in this order. Each stage is a `TEMP` table
built from the one before:
1. `split_versions`: every version of every `source_kind='inbox'` occurrence with its order
   (`ROW_NUMBER() OVER (PARTITION BY occurrence_id ORDER BY captured_at, id)`) and its predecessor's hash (`LAG(hash)`).
   - `merged` is 1 when a `managed_organization_events` row exists for (occurrence, predecessor hash) with
     `source_path LIKE 'Inbox/%'`, `target_path NOT LIKE 'Inbox/%'` and `created_at < captured_at` (contract
     "Definitions").
   - `run = SUM(merged) OVER (PARTITION BY occurrence_id ORDER BY captured_at, id)`.
2. `split_runs`: one row per (occurrence, run > 0), with the run's first and last hash and its version count.
3. **New occurrences** are inserted for each `split_runs` row, copying the merged row's `source_root`, `relative_path`,
   `source_kind`, `last_seen`, `last_job` and `deleted_at` (OD-5). `current_hash` is the run's last hash and
   `first_seen` its first version's `captured_at`. `path_key` is a placeholder
   `path_key || '|split-' || occurrence_id || '-' || run`, unique and never a real path.
   `split_map(occurrence_id, run, new_id)` is read back by that placeholder.
4. `split_hashes(occurrence_id, hash, target_id)`: every version hash of a run > 0 mapped to its new document. Run 0
   isn't listed, so no update touches a row that stays. A do-nothing update would still fire the `revision_*_update`
   triggers and change `library_revision` on a library that never merged (SC-13 step 2). Every version-keyed table
   above is then `UPDATE … SET document_id = target_id FROM split_hashes WHERE document_id = occurrence_id AND
   blob_hash = hash`, and `versions` the same way by `occurrence_id` / `hash`. Every later stage also moves only rows
   whose target differs from the original id.
5. **Rows without a version**, in this order, each a `FROM` join (contract "Rows that name a document but no
   version"):
   - `extraction_runs`, through `parse_runs.blob_hash`;
   - `transactions.source_document_id`: from its statement, else its import, else its first evidence link (all
     already moved in stage 4);
   - `recurring_obligations`, from its receipt;
   - `receipt_batch_items`, through `parse_runs.blob_hash`. Its `run_id` references `parse_runs(id)`
     (`050_strict_tables.sql` `receipt_batch_items_new`), so "its run's version" (contract) is that parse run's hash;
   - `occurrence_links`: a `same_bytes` link naming a merged document goes to the pair of documents, one from each
     side's pieces (a side that wasn't split is its own only piece), that hold a version with the same hash. Of several
     such pairs, the one whose shared version was captured latest on either side, then the lowest ids; with none, the
     link is deleted (amended after code review round 1, finding 2: both sides may have split and moved on from the
     file they shared, so the other side's `current_hash` alone can miss it). Insert the re-pointed pair with
     `min()`/`max()` and `OR IGNORE`, then delete the old row. A pair naming one document twice is deleted (R1 as the
     contract states it).
   - `document_descriptions` and `document_group_pages` are left alone.
6. **Inbox paths.** Let `base` be the merged row's stored `path_key` up to its first `|`, or all of it when there is
   none. The key is never recomputed from `relative_path`. Since `3466ebb` a merged document may already have been
   released, with a later file holding the bare key, so a recomputed bare key could collide and stop the upgrade on
   every start.
   - **Stored key bare** (no `|`): the piece holding the merged occurrence's `current_hash` takes that key and the
     merged `source_status`. Every other piece gets `base || '|released-d' || <its own id>` and `organized`.
   - **Stored key already released** (it has a `|`, because a later file took the bare key on `3466ebb`): every piece,
     the holder included, gets `base || '|released-d' || <its own id>` and `organized`. No piece takes the stored key,
     except document 1 itself: the stored `base|released-d1` is exactly document 1's own released key, so it ends with the
     same string. Any other piece taking it would clash. A later file keeps the bare key
     untouched.
   - Either way, released keys are built from `base` (`storage.RELEASED_PATH`), never from stage 3's `|split-`
     placeholder. That way `Store.publish`'s re-drop lookup
     (`substr(path_key, 1, …) = base || '|released-d'`) still finds each piece.
   - The original row's `current_hash` becomes its run-0 last hash.
   - Order: the original row first takes a temporary `base || '|split-0-' || id` key, then the holder takes the
     stored key, then the rest take their released keys. So `UNIQUE(source_root, path_key)` never clashes.
7. **The record.** One `document_splits(document_id, from_document_id, versions, created_at)` row per new document.
   It is a `STRICT` table (`docs/development.md` "Adding a migration").
   This is the record the diagnostic reads (contract open point, chosen here over `library_events`: a table of its
   own can't be confused with library actions, and the step creates it anyway). No UI reads it (OD-4).
8. The TEMP tables are dropped, then `PRAGMA user_version=80;`.

A step written this way is idempotent (SC-13): after it runs, no occurrence has a merged-in version left. Its
`CREATE TABLE` uses `IF NOT EXISTS`, and the runner never re-runs a recorded step.

**P2 Renaming split copies (FR-08).** `ManagedLibrary.organize` gains `name=None`, a target file name used as given
(validated by the same safe-name rules `filename` applies).
- **With `name` there is no fallback.** Today a target holding other bytes makes `organize` retarget to a full-hash name
  (`managed_library.py` after `target = …`). With a given name that retargeting is skipped, so the intent goes to
  `execute`, which blocks it with "Managed destination contains different bytes. It was not overwritten." (`:337`).
  That is SC-08 step 4.
- **The pass.** A new `ManagedLibrary.retag_ids()` runs in `recover()` after `relayout()`, for documents named in
  `document_splits` only (as `document_id`, or as `from_document_id` for its own run-0 copies). Each row is tried on its own and
  `(ValueError, OSError, RuntimeError)` is caught per row, as `relayout` and `retire_folders` do. A blocked rename
  then leaves its intent visible without stopping `recover()` or the other renames. For each of their
  `managed_files` rows whose name ends `__d<n>.<ext>` with `n` different from its `document_id`, it calls `organize(document_id, blob_hash, folder, reason, action="layout", name=<the same name with
__d<document_id>>)`. It applies only to documents not in Trash and without a pending or blocked intent, like
`relayout`. The move is the normal durable intent: never overwriting, blocked on a clash with its error kept, and
resumed by the next `recover()` (SC-08). Until it runs, `managed_files` still names the `__d1` file, so the document
opens (SC-08 step 1). A trashed split document is renamed after it is restored: `recover()` skips Trash today, and the
plan keeps that.

**P3 The diagnostic (FR-09).** `scripts/document_splits.py "<inventory.sqlite3>"` follows `scripts/db_checks.py`:
read-only, backed up into memory. It prints exactly four lines:
1. `would split: N document` or `N documents` (singular for 1): the P1 stage-1 query run on the copy as a SELECT;
2. `split: N document` or `N documents`: `count(DISTINCT from_document_id)` from `document_splits`, 0 when the table is
   absent (before the upgrade);
3. `versions moved: N`: before the upgrade the versions the query would move, after it `sum(versions)` from
   `document_splits`;
4. `left as a version, history incomplete: N`: versions whose predecessor has a `managed_files` row outside `Inbox/`
   and no `managed_organization_events` row (contract "Definitions").

All four lines are always printed, so case (a) of SC-10 shows `split: 0` as well. Each line matches the contract's
regex. The SQL for stage 1 is one string
constant shared with the tests (`scripts/document_splits.py` `MERGED_IN`). The migration repeats it, since a migration
script can't import. A test asserts the two find the same versions (SL-01).

## Error handling, idempotency and recovery
- A failure anywhere in 080 rolls back the whole step through the runner. The library stays at 79 and the next start
  retries (SC-09). The fault in SC-09 is a fixture trigger on `occurrences`, as the contract allows.
- The broken-reference check runs after the step: every moved row points at an existing occurrence because the new
  occurrences are inserted before any row moves.
- History incomplete: such versions stay versions (the `merged` test needs the event). The diagnostic counts them
  (SC-11).
- FR-08 renames reuse `organize` intents. A crash between the move and `finish` is recovered as today. A clash is
  `blocked`, never overwritten (SC-08 step 4).
- Re-running the upgrade is impossible (the version is recorded). Re-running `recover()` renames nothing twice: names
  already match their id.

## Privacy/security and migration impact
- No model call, no network, nothing leaves the machine. The diagnostic prints counts and fixed words only (SC-10).
- No blob is written or deleted. Library files change name only, through FR-08 intents.
- **Migration 080** adds `document_splits` and rewrites `document_id` and `source_document_id` values. Row counts are
  unchanged except `occurrences` (+splits) and `document_splits` (+splits). `docs/development.md`'s schema map gets an
  entry. `tests/test_migrations.py` reads `LATEST` from `MIGRATIONS`, so it needs no edit; it still runs as a
  regression file.
- **Another feature's plan.** `plans/pdf-table-engine-bills/plan.md` SC-121 expects migrations to end at 077. That
  plan is another session's uncommitted work, and its approval is bound to its hash, so this plan doesn't edit it. The
  risk is recorded below for whoever resumes it.

## Vertical slices
| ID | FR/SC covered | Dependencies | Files/changes | Verification command / evidence |
|---|---|---|---|---|
| SL-01 | FR-06, FR-07; SC-05, SC-06, SC-07, SC-09, SC-11 (the version stays), SC-12, SC-13, SC-14, the already-released variant | none | `library/migrations/080_split_merged_documents.sql`, all of P1 in one slice: 080 must be complete before any library takes it, because the runner never runs a recorded step again; `scripts/document_splits.py` with the `MERGED_IN` constant only; new `tests/test_document_split.py` with the `merged_library` fixture (contract "Fixtures"), the table-coverage test of R-a and the `MERGED_IN` agreement test | `.venv/bin/python -m pytest tests/test_document_split.py -k "sc05 or sc06 or sc07 or sc09 or sc11_version or sc12 or sc13 or sc14 or merged_in or coverage"`, then separately `.venv/bin/python -m pytest tests/test_migrations.py tests/test_receipts.py tests/test_statement_accounts.py tests/test_managed_library.py` (`test_receipts.py::test_existing_v1_database_migrates_with_backup` runs every step) |
| SL-02 | FR-08; SC-08 | SL-01 | `library/managed_library.py` (`organize(name=…)` with no fallback, `retag_ids`, `recover`) | `.venv/bin/python -m pytest tests/test_document_split.py` (all of it: `recover()` now renames during every reopen), then separately `.venv/bin/python -m pytest tests/test_managed_library.py tests/test_capture.py tests/test_library.py` |
| SL-03 | FR-09; SC-10, SC-11 (the count) | SL-01 | `scripts/document_splits.py` (the report) | `.venv/bin/python -m pytest tests/test_document_split.py -k "sc10 or sc11_count or merged_in"` |
| SL-04 | FR-10; SC-05 UI checkpoint | SL-01, SL-02, SL-03 | `docs/documents.md` "The managed library"; `docs/development.md` schema map (080) and the diagnostic under "Database checks"; `docs/open-work.md` (remove the item, add OD-2's watched folders); `tests/test_document_v2_browser.py` (opt-in split checkpoint) | `.venv/bin/python -m pytest --browser tests/test_document_v2_browser.py -k split`; doc review |

## Final verification
After SL-04, once:
- `.venv/bin/python -m pytest -q -p no:cacheprovider` (the unit and integration suite);
- `.venv/bin/python -m pytest -q --browser -p no:cacheprovider tests/test_document_v2_browser.py tests/test_browser.py tests/test_records_v2_browser.py`
  (the browser files touching documents);
- `.venv/bin/ruff check src tests scripts`.

Failures are compared with the pre-existing ones of the 2026-11-10 run (agent instance, agent findings, tax engines,
engine worksheets, traces, records filters, planned bugfixes, real-browser versions). Only new failures count.

## Requirements & scenarios coverage matrix
| Requirement | Scenarios | Slices |
|---|---|---|
| FR-06 | SC-05, SC-06, SC-11, SC-13, SC-14 | SL-01 |
| FR-07 | SC-05, SC-07, SC-12 | SL-01 |
| FR-08 | SC-08 | SL-02 |
| FR-09 | SC-10, SC-11 | SL-03 (constant in SL-01) |
| FR-10 | review, SC-05 UI | SL-04 |
| Errors | SC-09, SC-11 | SL-01 |
| OD-1, OD-5 | SC-05, SC-07 | SL-01 |

## Test environments, data, stubs for nondeterministic components, final-state oracle
- **Isolated stores** under `tmp_path`, using `merged_library(tmp_path, plan)` exactly as the contract's "Fixtures"
  says. Files and records are made by the real capture, organize and `Ledger`. The database is then rewritten to the
  old merged shape with fixed times. Before `user_version` is set to 79, the fixture drops `document_splits`, which the
  latest schema already holds, so the upgrade starts from a real 079 schema.
- **Two ways to upgrade.** Most scenarios reopen with `Store(root)`, which migrates and then runs
  `library.recover()` (`storage.py:267`).
  - SC-08 step 1 needs the state between the two, so it upgrades a raw connection with `storage.apply_migrations(db,
    79)`.
  - SC-08 step 2 installs its rename fault before `Store(root)`. On Linux, `execute` publishes with
    `os.link(stage, target)` (copy, link, unlink), and on Windows with `os.rename`. Neither call sees the source path,
    so the fault matches on C's **target** path: the name ending `__d<C's id>`. `monkeypatch.setattr` replaces the
    global `os.link` (or `os.rename`) with a wrapper that raises `OSError` once for that target and otherwise calls the
    original.
- **The already-released variant** (`test_sc14_already_released`, a test of its own beside SC-14; it starts from SC-05's state, where C is filed and
  document 1 is `organized`, because release only happens to a filed document: `storage.py` `publish`). Inside fixture
  step 2, after the rewrite and before step 3 sets `user_version` to 79 (any later open would run 080 first), the
  fixture drops D as `document.pdf` on today's capture and files it with `store.library.organize`. D's version and
  filing get fixed times later than C's filing, which the fixture fixes too. So document 1 is released and D holds the
  bare key. Then the upgrade runs. D usually gets a freed id (occurrence ids have no `AUTOINCREMENT`), so the expected
  data lists D as a document that isn't split, found by its hash, and check (a) is taken before C's bytes are dropped
  again. It must succeed: D keeps the bare key,
  every piece of document 1 has a released key built from the base, and dropping C's bytes again is `unchanged`: D is
  filed and so released, and C's piece is found by `base|released-d` and its hash (pass-1 M1, pass-3).
- **No nondeterminism:** no model (records are published through `Ledger` from the synthetic statement and pay stub
  fixtures). There is no network: `no_network` isn't in `conftest.py`, so the new test file imports it from
  `test_table_engine`, as other files do. New ids are found by their versions' hashes.
- **Final-state oracle.** The fixture returns the expected split from its plan, never from the repair. Every test
  asserts:
  - (a) every table's row count against the snapshot. The renames of FR-08 (from SL-02 on, run by `Store(root)`'s
    `recover()`) are left out of the comparison: the `managed_organization_intents` and `managed_organization_events`
    rows with `action='layout'` for split documents created after the upgrade. Everything else must match exactly;
  - (b) every version-keyed row names a document whose versions include its hash;
  - (c) each record's document by hash;
  - (d) blob and Library file bytes by sha256.
- **Fault injection** (SC-08, SC-09) as the contract says: a monkeypatched rename for SC-08, a fixture trigger for
  SC-09.

## Risks, unresolved decisions, alternatives
- **R-a A table that names a document is missed.** Mitigation: SL-01's coverage test lists every table with a `document_id`,
  `occurrence_id` or `source_document_id` column from `PRAGMA table_info` at runtime. It fails when one is neither
  moved by 080 nor named as staying (contract "Definitions"; `document_splits` is named as staying), so a future
  table can't be skipped silently.
- **R-b Version order by `captured_at` text.** Times are ISO strings of one format (`core.paths.now`), so text order is
  time order. `versions.id` breaks ties.
- **R-c `merged` rests on one event per filing.** An Inbox document filed by hand, by classification or by the
  "Repeated Inbox capture" path all write `finish`'s event. A library whose events were pruned has none, so it falls
  under "history incomplete" and nothing is split (the safe side).
- **R-d Bills plan migration check** (`plans/pdf-table-engine-bills/plan.md` SC-121, "ends at 077"). It is stale
  already (078 – 079) and needs amending by that feature's owner. Not edited here.
- **Alternative rejected: a Python upgrade step.** It would need a second kind of migration in `MIGRATIONS` and in the
  runner, plus the same transaction and broken-reference wrapping. The SQL step needs neither and keeps "Adding a
  migration" true.
- **Alternative rejected: recording splits in `library_events`.** It would need an `action` value of its own and a
  `blob_hash` per row. `document_splits` is clearer for the diagnostic and adds no CHECK change.
- **Wording kept from the approved contract.** The spec's R1 says a self-pointing `same_record` link is "re-pointed";
  the approved contract (which governs) deletes it, and so does this plan.
