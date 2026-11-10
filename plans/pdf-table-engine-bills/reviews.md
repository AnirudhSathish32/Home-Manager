# pdf-table-engine-bills — plan reviews

## Pass 1 (comprehensive)
Reviewer: provider claude, model claude-opus-5-5, subagent_type general-purpose (fresh native subagent; route
`review-plan` via=subagent, recorded `subagent-review-plan-1`). Verdict: REVISE. 0 BLOCKER, 5 MAJOR, 6 MINOR, 3 INFO.

| # | Finding | Disposition |
|---|---|---|
| M1 | SL-03 can't pass: its C-auto scenarios (SC-101, SC-105, SC-110, SC-114, SC-116) need P6's summary anchors, planned in SL-04 | Fixed: SL-03 builds P6's single-value anchors, `bill_fields` and summary cites; SL-04 keeps repeats, FR-117, FR-118. Slice table and matrix updated |
| M2 | `LATE_WORDS` (`late fee`, `late charge`) would drop a late fee billed this period | Fixed: a late line needs a condition with a date; an unconditional `Late Fee 5.00` is a charge row; generator prints both (P3.1, P12) |
| M3 | `(555)` tokenizes as an amount, so `Blair (555) 202-2222` could never be a title | Fixed: tokens a `PHONE` match covers become text before lines are classed (P3) |
| M4 | Undoing a held correction would write its previous value onto another line | Fixed: the undo row is recorded and marked `undone`, `receipt_items` untouched, the held reason removed; one SL-05 test (P9) |
| M5 | Scanned / combined-image parts (a `PDFResult` with pages) could fall into the engine path | Fixed: three part paths stated (engine page / text page without charge table / no text page = `bill=None`); scanned one-bill regression test in SL-03 (P7.1) |
| m1 | `PHONE` (i) as written matched `1234-5678` and `555-0100` | Fixed: reviewer's tightened regex adopted after re-checking every listed form (P3, G14) |
| m2 | `paystub_tables.covered_rows` is pay-typed | Fixed: local `covered` with the same rule (P4) |
| m3 | Full-match anchors miss `Amount Due by <date>` | Fixed: `by`/`on or before`/`as of`/`on` next to a removed date are stripped; generator prints them (P3.2, P12) |
| m4 | Split rule's `anchor_kind` must strip ` | ` separators | Fixed (P8.1) |
| m5 | SL-07 regression set missed the bill suites | Fixed: `test_bill_kinds`, `test_recurring_bills`, `test_invoice_ingestion` added |
| m6 | One-bill publication segment shape undefined | Fixed: same shape as split segments plus `"one": true` (P8.5) |
| INFO | Keys printed side by side on one line | Recorded as R-A2 (spec says a key starts the line); probe measures it |
| INFO | H1 – H3 are real human decisions | Kept as human decisions |

## Pass 2, first attempt (lost)
Dispatched 2026-11-09T05:41Z as `subagent-review-plan-2`. The planning task died on a provider rate limit before the
reviewer's findings were recorded. Nothing from it was used. Pass 2 was run again from scratch as `subagent-review-plan-2b`.

Changes made before pass 2b (resumed planner, no reviewer input):
- Re-based on HEAD `e2c2d5d` (landed during planning): `extraction.py` citations moved (+3 after `:697`, +10 after
  `:2510`); the Publish row's citations corrected (`issues.extend(notes)` is `:4050`); the Base paragraph rewritten (the
  once-uncommitted changes are now that commit); `EXTRACTION_VERSION` target v40 → `typed-extraction-v41-bill-engine`,
  with a "Version" decision (v40 is taken; SC-121 step 1 still holds; no spec amendment).
- Half-applied pass-1 fix finished: SL-03's `-k` expression now actually deselects the `sl04` cases.
- SC-121 step 3 (no migration) assigned to SL-04 (it was in no slice).
- P7.1: the layout-notes rule split out of the scanned-regression bullet; the scanned regression asserts no
  `bill_engine` table rather than no `reported_tables` at all.
- G14: a masked number in a section title (`Account ****9012`) is a holder title by FR-102 (a)'s masked form; recorded
  with a test.

## Pass 2 (`subagent-review-plan-2b`)
Reviewer: provider claude, model claude-opus-5-5, subagent_type general-purpose (fresh native subagent; route
`review-plan` via=subagent, max_subs 0). Verdict: REVISE. 0 BLOCKER, 1 MAJOR, 5 MINOR, 3 INFO. Pass-1 fixes M1 – M5 and
m1 – m6 all found applied correctly; every integration-point citation verified at `e2c2d5d`; v41 version decision sound;
G3 – G8, G13, G14 and the 80-character cut settled without changing a contract value; H1 – H3 correctly raised.

| # | Finding | Disposition |
|---|---|---|
| M1 | The plan says the tree is clean, but someone's in-flight tracked changes (`ledger.py`, `document_v2.js`, …) and an untracked `078_account_type_words.sql` exist; SC-121 step 3 hard-coded `077` | Fixed (verified with `git status`): SL-01 precondition (no tracked change, no untracked file under `src/`/`tests/`), citations re-checked against START_HEAD always, SC-121 step 3 compares with START_HEAD's listing; H4 added |
| m1 | SC-115 (b), SC-121 (3), SC-122 BL-MULTI need SL-06 but sit in the record file SL-03/SL-04 run | Fixed: they live in `tests/test_bill_split.py` and run in SL-06; matrix and traceability updated |
| m2 | SL-03 regression set misses `test_paystub_split.py`, `test_paystub_cleanup.py` (shared `pay_layout_notes`, `paystub_table_context`) | Fixed: added |
| m3 | Dateless late conditions (`if paid late`) not recognised | Fixed: added to `LATE_WORDS` (FR-103 names "if paid late"); generator prints one |
| m4 | `Payment Due <date> <amount>` is a split key but neither key nor anchor in P3 | Fixed: `payment due` is an amount-due synonym when an amount follows; P3 and P8.1 agree; generator prints it |
| m5 | `PHONE` (i) matched `1,234.5678` | Fixed: `,` added to both lookbehinds; re-checked with python3 against every listed form |
| INFO | Model new charges vs FR-118 worked-out value when no anchor | Fixed: one sentence in P6 (worked-out wins on an engine-read part) |
| INFO | Raw `0.1430` beside formatted unit prices | Accepted: the spec asks for the printed rate |
| INFO | H1 – H3 are real human decisions | Kept |

## Pass 3 (`subagent-review-plan-3`, last allowed)
Reviewer: provider claude, model claude-opus-5-5, subagent_type general-purpose (fresh native subagent; route
`review-plan` via=subagent, max_subs 0). Verdict: PASS WITH MINORS. 0 BLOCKER, 0 MAJOR, 2 MINOR. Every pass-2 fix
confirmed with no contract conflict (no fixture prints `Payment Due` with an amount or a dateless late condition; the
comma lookbehind re-run against every FR-102 (a) / SC-102 step 9 form).

| # | Finding | Disposition |
|---|---|---|
| m1 | How SC-121 step 3's test knows START_HEAD's migrations listing | Fixed: SL-04 writes the listing in as a literal read from START_HEAD at implementation time; the test runs no `git` |
| m2 | Matrix FR-121 row said SL-04 covers SC-121 steps 1, 2 only | Fixed: "SC-121 1–3 for (1), (2)" |

Loop exit: no BLOCKER/MAJOR remains. Plan READY for human review; H1 – H3 (spec-level choices) and H4 (commit or stash the
in-flight work before SL-01) are open.
