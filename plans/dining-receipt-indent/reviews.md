# dining-receipt-indent — plan reviews

## Before pass 1 (resumed planner, no reviewer input)
The first planning attempt left a complete draft and stopped on a provider rate limit before any review. The resumed
planner checked it against the spec, the test contract and the code at HEAD `66e97d5` and changed it before pass 1:
- Line payloads to the extraction model: six sites, not four (`extraction.py:1226`, `:1234` were missing).
- P4: `decide` runs before the currency is known, so its issues are formatted in `publish` with `amount_text` after
  `currency_for` (`extraction.py:4621`), through a new `dining=` keyword.
- P8: the reviewed kind-change branch (`ledger.py:784-787`) and `_undo_kind` rebuild no splits today; both now call
  `refresh_splits` after setting or clearing FR-10.
- Old-library builder writes each old run's folder `result.json`, since `ReceiptService.publish` reads it from there.
- SL-02 runs `test_extraction.py`, `test_eval_tasks.py` and every test file it edits; SL-06's claim that no backfill
  test exists was wrong (`tests/test_spending_splits.py:131`).
- Migration 081 stated as `ALTER TABLE … ADD COLUMN` only, with a grep check in SL-04 (D5).
- Final verification: the capture check compares against the SL-01 commit; baseline recorded (see the plan).

## Pass 1 (comprehensive, `subagent-review-plan-1`)
Reviewer: provider claude, model claude-opus-5-5, subagent_type general-purpose (fresh native subagent; route
`review-plan` via=subagent, max_subs 0). Verdict: REVISE. 0 BLOCKER, 2 MAJOR, 7 MINOR, 6 INFO. Spec gate and hash
confirmed; every FR/SC owned by a slice; cited integration points verified; P10's tip-row sentinel found sound.

| # | Finding | Disposition |
|---|---|---|
| M1 | SL-04 claims C-cat checks (SC-01 step 8, SC-02 step 3, SC-03 (c)/(d), SC-06 step 5) that need FR-10 from SL-05 | Fixed: SL-04 asserts amounts, citations, review, links and C-sum only; those checks move to SL-05's list |
| M2 | Undo of a change *to* dining on a reviewed receipt can't restore the earlier categories from "the latest run" (it is the dining reading, and `apply_one_category` overwrote the items) | Fixed: migration 081 adds `record_corrections.item_categories_json`; the kind correction stores the items' categories and the flag before the change; `_undo_kind` restores them and rebuilds splits. Pre-081 corrections fall back to the latest run. SL-06 adds the grocery → dining → Undo C-snap test (from FR-13's criterion) |
| m1 | SL-01 determinism check used `git diff` on untracked files | Fixed: `sha256sum` of run 1, `sha256sum -c` after run 2 |
| m2 | `test_bill_printed_total.py:367`, `test_bill_split.py:538`, `test_pdf.py:137` assert old version values | Fixed: listed as updated on purpose and added to SL-02/SL-03 commands |
| m3 | SL-03 file list named 4 payload sites | Fixed: all six |
| m4 | SL-02 doesn't run tests that use the shared helpers it changes | Fixed: SL-02 also runs every test file importing those helpers |
| m5 | Dropped rows misalign `cell_references`; replaced total/tip keep stale `summary_references` | Fixed: P12 drops the same index; P4 drops the summary reference for a replaced total/tip |
| m6 | Split trace text says "a tip as dining" (`finance/traces.py:213`) | Fixed: SL-05 updates it for receipts FR-10 has applied to |
| m7 | SL-08 screenshot command incomplete | Fixed: browser tests save shots to `$UI_SHOTS_DIR`; `ui_shots.py --routes "document/{receipt_doc}" --widths 390,1440 --out …` before/after |
| INFO | `FxError` from `resolve` | Adopted: treated as no rate (P13) |
| INFO | Only `record` calls `publish`; standing tip correction removes FR-06 reason on re-read; `same_record` deletion has no collateral; Undo of Categories re-applies FR-10; later slices don't re-run `test_vision_indent.py` | Noted; no change (Final verification covers the last) |

## Pass 2 (`subagent-review-plan-2`)
Reviewer: provider claude, model claude-opus-5-5, subagent_type general-purpose (fresh native subagent; route
`review-plan` via=subagent, max_subs 0). Verdict: PASS WITH MINORS. 0 BLOCKER, 0 MAJOR, 2 MINOR, 3 INFO. Every pass-1
fix (M1, M2, m1 – m7, the `FxError` INFO) found applied and correct at `66e97d5` (snapshot point safe before `_upsert`
side effects, item ids kept by `_replace_items`, `category_splits.id` stable for C-snap, `summary_references` keyed by
field, `ui_shots.py` routes and Edge channel available). The loop exits here: no BLOCKER/MAJOR remains.

| # | Finding | Disposition |
|---|---|---|
| m1 | P8 left the order between the Undo snapshot and `apply_one_category` open; `_undo_kind`'s own correction row had no snapshot | Fixed: with a snapshot, Undo restores it and nothing else; `_undo_kind` stores a snapshot in the row it inserts; FR-10 / `recategorise_items` only for pre-081 corrections |
| m2 | `\|` inside table cells made SL-04's migration grep (and SL-02's pipeline) never fail / not pipe | Fixed: commands C-SL02 and C-SL04 moved to a code block under the slice table; the grep was checked to print 1 on a file containing `UPDATE` |
| INFO | X-UPG should include `record_corrections` | Adopted in "Privacy/security and migration impact" |
| INFO | 19 `local_model` test files outside SL-02's run set | Accepted: they don't use the default vision stub (reviewer spot-checked); Final verification covers stragglers |
| INFO | Baseline pending at review time | Recorded in the plan's Final verification after the run finished |
