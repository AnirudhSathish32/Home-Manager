# Plan reviews: pdf-table-engine

## Pass 1 (2026-10-27)
Reviewer: provider claude, model claude-opus-5-5, native subagent `general-purpose` (route: review-plan via subagent,
max_subs 0). Plan at spec bundle `31d06e09ac86`, HEAD `3ee7d56`. Verdict: REVISE (2 BLOCKER, 4 MAJOR, 11 MINOR).
Every cited line was rechecked by the planner before acting.

| ID | Severity | Finding | Disposition |
|---|---|---|---|
| B1 | BLOCKER | A one-row table forms no columns (≥ 2 rows of support), so SC-06 b's ONE and one-row continuation pages are lost | Fixed: a heading label aligned with a group counts as one row's support (P4); a page with < 2 supporting rows matches the previous table's columns by the date column's offset; plan-level test `one_row_continuation` |
| B2 | BLOCKER | `tests/test_statement_rebuild.py` `bank()` calls `statement_rows.rebuild` (legacy), so FR-16/FR-28 regressions never exercise the engine | Fixed: SL-05 moves `bank()` and `analysis()` to the engine; only tests of the old reader's internals stay on `statement_rows` |
| M1 | MAJOR | FR-19's note appended to `read`'s `notes` becomes a review issue (`extraction.py:3182`, `:3230`) | Fixed: the note goes through `Rebuild.notes` → `record_notes` (P10) |
| M2 | MAJOR | "Only amount on the line" makes `Beginning Balance carried -3.00` an anchor, breaking an unchanged existing test | Fixed: inside a table, an anchor only when its amount is in the decided balance column; "alone" only for summary lines outside tables (P6) |
| M3 | MAJOR | `to_minor` on every token rejects FX's rate column; the engine has no currency for minor units | Fixed: tokens hold `Decimal`; `to_minor` only on money-role columns after roles (P2, P3) |
| M4 | MAJOR | Row keys `<table_id>:<row>` collide across pages | Fixed: one `ImportTable` piece per page (continuation kind), key `<piece id>:<row>`; SC-08 asserts unique keys (P11) |
| m1 | MINOR | FR-05's description-above clause dropped without sign-off | Fixed: built with a stated criterion (P5.7) and a plan-level test (WR-above) |
| m2 | MINOR | Printed card balances don't reach `record["summary"]` | Fixed (P10) |
| m3 | MINOR | Locator omits `balance_minor`; `cell_ids` rule unstated | Fixed (P2 locator paragraph) |
| m4 | MINOR | Import cycle `pdf_import` → `statement_tables` → `statement_rows` → `pdf_import` | Fixed: helpers move to `finance/statement_dates.py`, re-exported by `statement_rows` |
| m5 | MINOR | SL-05's `-k` selection runs import-side tests | Fixed: import tests end in `_import`; SL-05 excludes them |
| m6 | MINOR | Generator: Record's 10 cases in no slice; differs from the contract's file plan | Fixed: 10 Record cases in SL-05; `tests/table_engine_generator.py` builds PDFs with `make_pdf`; deviation stated |
| m7 | MINOR | P7 decision flow gaps (CS's per-row signs vs summary; tie-break contradiction) | Fixed: P7.4–P7.6 rewritten as tiers; per-row sign readings are candidates; no tie that changes money is broken by order |
| m8 | MINOR | OD-2 stops at the newest statement even when undecided | Fixed: walk newest first, up to 10, return the first decided |
| m9 | MINOR | Eval metric directions, legacy unplaced, TAGS allowlist, dry-run verification | Fixed (P12, SL-07) |
| m10 | MINOR | Repeated heading containing "balance" vs balance-section title | Fixed: a text line labelling ≥ 2 zones is a heading (P4) |
| m11 | MINOR | Line numbers off by a few | Fixed |

## Pass 2 (2026-10-27)
Reviewer: provider claude, model claude-opus-5-5, native subagent `general-purpose` (fresh context; given pass 1's
findings and dispositions). Verdict: REVISE (1 MAJOR, 6 MINOR). Pass-1 findings: all resolved except m5 (N2) and the
remainders noted in N3–N5, N7.

| ID | Severity | Finding | Disposition |
|---|---|---|---|
| N1 | MAJOR | CS's `Payments and Credits` (x 40, directly above p1) would be read as a heading line, losing FR-12's section signs | Fixed: a heading line needs ≥ 2 runs in different zones, one of them an amount zone; a single run on its own line is a section title; plan-level test `section_titles` (P4) |
| N2 | MINOR | SL-05's command used two `-k` options (pytest keeps the last) | Fixed: one combined `-k` |
| N3 | MINOR | `analysis()` moved before the new `analyze` exists; `test_sc18_p8_*` patch `statement_rows` | Fixed: SL-05 retargets the p8 patches only; both helpers move together in SL-06 with the helper-level changed tests |
| N4 | MINOR | `Rebuild` lacks `opening_minor`/`closing_minor`/`period` | Fixed: added with `None` defaults (P1) |
| N5 | MINOR | `Anchor`/`Total` in minor units from a currency-less engine | Fixed: `Decimal`; converted in `statement_tables` |
| N6 | MINOR | An unheaded table with one misprint records nothing | Fixed: tier (b′), most holding links (≥ 2), first break reported (P7.5) |
| N7 | MINOR | Eval `unplaced` compared unlike counts; `TAGS` lives in `evals/corpus.py:26` | Fixed: compare `dropped` with `dropped`, show `unplaced` separately; citation corrected |
| INFO | — | Anchors depend on the assignment's balance column | Fixed: re-classed per candidate (P7.2) |

## Pass 3 (2026-10-27)
Reviewer: provider claude, model claude-opus-5-5, native subagent `general-purpose` (fresh context; given passes 1–2).
Verdict: **READY** (no BLOCKER/MAJOR). All pass-2 findings resolved; the heading-line rule checked against WF, K, X, S,
BL, CS, PD, TD and ONE. Two new MINORs, both folded in without another pass:

| ID | Severity | Finding | Disposition |
|---|---|---|---|
| P3-1 | MINOR | `test_sc27_without_fr30_…` (`tests/test_statement_rebuild.py:401–405`) patches `pdf_import.joined_amounts`, which the engine never calls | Fixed: SL-06 keeps tests that patch old internals on `analyze_legacy` |
| P3-2 | MINOR | A one-run footer would become a section title for the next page (R4/FR-12 risk) | Fixed: a title needs a row below it on its page (it still carries to the same table's continuation rows); text below a page's last row is the footer and is ignored, so it never becomes a title (P6) |
