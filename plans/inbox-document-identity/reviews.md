# Plan reviews: inbox-document-identity

## Pass 1 — claude / claude-opus-5-5 / general-purpose subagent (2026-11-10)
Verdict: REVISE. Three MAJOR, nine MINOR, four INFO.

| Finding | Severity | Disposition |
|---|---|---|
| M1 A document already released by 3466ebb collides with a recomputed bare key; 080 would fail at every start | MAJOR | Fixed: P1 stage 6 uses the stored key and a `base` before any `|`; released keys are built from `base`; an already-released variant of SC-14 was added to the test data |
| M2 `organize` falls back to a full-hash name instead of blocking on a clash (verified, `managed_library.py` after `target = …`) | MAJOR | Fixed: with `name=` there is no fallback, so `execute` blocks it (`:337`), as SC-08 step 4 says |
| M3 The `-k` filter deselected the regression files | MAJOR | Fixed: each slice runs the split selection and the regression files as separate commands |
| m1 SC-14 needs the row moves; a half-written 080 could reach a library | MINOR | Fixed: all of 080 is one slice (SL-01); slices renumbered SL-01 – SL-04 |
| m2 `receipt_batch_items.run_id` is a parse run (verified, `050_strict_tables.sql`) | MINOR | Fixed: mapped through `parse_runs.blob_hash` |
| m3 Run-0 updates would fire revision triggers | MINOR | Fixed: only rows moving to a new id are updated |
| m4 `Store(root)` runs `recover()` after migrating (verified, `storage.py:267`); platform-specific move | MINOR | Fixed: SC-08 step 1 uses `apply_migrations` on a raw connection; patch points named per platform |
| m5 The fixture's latest schema already has `document_splits` | MINOR | Fixed: the fixture drops it before setting 79 |
| m6 `no_network` isn't autouse from conftest | MINOR | Fixed: the new file imports it |
| m7 Diagnostic wording vs the contract's regex | MINOR | Fixed: singular and plural stated; four lines always |
| m8 occurrence_links rule, released keys from base, TEMP drops, STRICT | MINOR | Fixed in P1 |
| m9 `test_migrations.py` needs no edit | MINOR | Fixed: kept as a regression file only |
| `retag_ids` should be limited to split documents | INFO | Adopted |
| R1 wording (spec "re-pointed" vs contract "deleted") | INFO | Recorded under Risks; the contract governs |
| SC-06 archive `source_path` is NULL | INFO | No change: the verdict is the same |
| Bills plan migration check left to its owner | INFO | No change |

## Pass 2 — claude / claude-opus-5-5 / general-purpose subagent (2026-11-10)
Verdict: REVISE. Two MAJOR, five MINOR. Pass-1 M2, M3 and m2 – m6 confirmed fixed against the repo.

| Finding | Severity | Disposition |
|---|---|---|
| 1 An already-released merged document gives two pieces the same `|released-d1` key | MAJOR | Fixed: when the stored key is released, every piece including the holder gets `base|released-d<own id>`; only a bare stored key is kept by the holder |
| 2 FR-08 renames add intents and events in `Store(root)`, breaking check (a); SL-02 didn't re-run SL-01's tests | MAJOR | Fixed: check (a) leaves out post-upgrade `layout` intents and events of split documents; SL-02 runs all of `tests/test_document_split.py` |
| m1 `retag_ids` must catch errors per row | MINOR | Fixed in P2 |
| m2 The SC-08 fault can't key on the source path | MINOR | Fixed: keyed on C's target name; wrapper calls the original otherwise |
| m3 The released variant must be built inside the fixture | MINOR | Fixed |
| m4 The coverage test was named in two slices | MINOR | Fixed: SL-01 |
| m5 `test_receipts.py` runs every step | MINOR | Fixed: added to SL-01's regression command |

## Pass 3 — claude / claude-opus-5-5 / general-purpose subagent (2026-11-10)
Verdict: REVISE. One MAJOR, one INFO. Every pass-2 correction confirmed against the repo.

| Finding | Severity | Disposition |
|---|---|---|
| The already-released variant was built on SC-14's base (C never filed), where release can't happen; its `unchanged` check couldn't pass | MAJOR | Fixed after the pass: the variant starts from SC-05's base, D is dropped and filed inside the fixture with later fixed times. **Not re-reviewed** (three passes is the limit) |
| SC-11's two checkpoints belong to two slices | INFO | Adopted: tests `sc11_version` (SL-01) and `sc11_count` (SL-03) |

**Plan status after pass 3: NOT READY.** A MAJOR finding remained at the end of pass 3. Its fix is applied but
unreviewed, so the plan is not offered for approval until the user decides how to proceed.

## Pass 4 (extra, at the user's request) — claude / claude-opus-5-5 / general-purpose subagent (2026-11-10)
Verdict: PASS WITH MINORS. The pass-3 MAJOR is resolved (traced through `publish` and P1 stage 6).

| Finding | Severity | Disposition |
|---|---|---|
| The variant's test name wasn't fixed but SL-01 selected it by `released` | MINOR | Fixed: `test_sc14_already_released`, picked by `sc14` |
| SL-03 edits `MERGED_IN`'s file without the agreement test | MINOR | Fixed: `or merged_in` added to SL-03 |
| D probably reuses a freed id | INFO | Adopted: expected data finds D by hash, as not split |
| Stage 6 "no piece takes the stored key" wording | INFO | Fixed: document 1 ends with its own released key |
| Check (a) before the re-drop | INFO | Adopted |

**Plan status after pass 4: READY for approval.** No BLOCKER or MAJOR remains.
