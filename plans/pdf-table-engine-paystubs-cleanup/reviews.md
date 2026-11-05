# Plan reviews: pdf-table-engine-paystubs-cleanup

## Pass 1
Reviewer: claude / claude-opus-5-5 / subagent general-purpose (fresh context; reviewed spec, contract and plan before approval). Verdict: REVISE (3 BLOCKER, 6 MAJOR, 7 MINOR).

| ID | Finding | Disposition |
|---|---|---|
| B1 | The sectioned payslip's YTD deductions rows (28,314.00) don't add up to its printed total (28,434.00); FR-91 can't give that column a role, and its deductions heading is one run | Fixed: new FR-89 (heading phrases split by column) gives the role from the heading; FR-91 and SC-90 now expect the YTD mismatch note |
| B2 | `80` can't become hours: heading support is per run (`pay_tables.py:533`) | Fixed: P0 (FR-89) splits heading runs into per-zone pieces; P1 relies on it |
| B3 | C-no-grid impossible: engine cells reuse printed cell ids (FR-66); Classification request carries grid tables | Fixed: C-no-grid redefined (cells of the run's `pay_tables`; requests after Classification); FR-93 reworded |
| M1 | `test_paystub_engine_record.py:543-551` asserts `fallback_pages` | Fixed: named in SC-94, rewritten in SL-02 |
| M2 | Probe script prints `fallback_pages` | Fixed: SL-04 updates it and runs the probe test |
| M3 | P4 would drop vision tables of scanned pages | Fixed: drop only `source == "pdf_text"`; mixed-file test |
| M4 | FR-92 (b) undefined; collides with `offset_of`/`repeats()` | Fixed: defined by column positions at one offset within ALIGN; PS-CONT and STK stated |
| M5 | FR-92 (f) has no design; its case may already pass | Fixed: SL-03 first records the failing generator cases; every sc91 test must fail at the start head; (f) rule follows its failing case |
| M6 | SL-01 too large; repair revert checks must precede rewrites | Fixed: five slices, repair tests first with no source change |
| m1 | `4,000` already an amount; `80` dropped, not label text | Fixed in "Existing behavior" and FR-90 acceptance |
| m2 | FR-92 (a) changes phase 2 FR-57 (c) | Fixed: Amends/Supersedes |
| m3 | FR-92 (e) would catch PS-YTDH | Fixed: limited to triples sharing the hours column; three-triple case stated |
| m4 | SC-92 doesn't reach the untrusted branch | Fixed: unit-test variant |
| m5 | SC-93 stub needs hours and rate | Fixed |
| m6 | Say tokenize/Line unchanged | Fixed in P1 |
| m7 | Lone integer in a details box | Fixed: SC-90 step 1 and FR-90 acceptance |

## Pass 2
Reviewer: claude / claude-opus-5-5 / subagent general-purpose (fresh context; ran the engine at ef7cff3 on the sectioned payslip fixture). Verdict: REVISE (2 BLOCKER, 2 MAJOR, 4 MINOR). B3, M1–M6, m1–m7 resolved; B1, B2 partly.

| ID | Finding | Disposition |
|---|---|---|
| B-1 | `80` never becomes a column: zones come from decimals only, so `Rate`/`Hours` share a zone and `80` fits none (P0 and P1 depend on each other) | Fixed: P1 rewritten as an ordered procedure (tentative integer columns → zones with them → P0 pieces → keep if headed or ≥ 2 rows) |
| B-2 | The deductions block's one-run heading line is never detected (`is_heading_like` needs two runs) | Fixed: P0 makes a one-run line splitting into ≥ 2 zone pieces heading-like; FR-89 reworded |
| M-1 | Earnings label would be "Year To Date Deductions" | Fixed: P0 cuts pieces at the block edge |
| M-2 | Whole hours on several rows start a second block | Fixed: P1 step 1 (a single-integer run never starts a group); contract case with hours 40/4/8 |
| m-a | `heading_runs` already splits by zone | Fixed: P0 extends `heading_runs`; `size/2` gap kept |
| m-b | Which sum FR-63's note prints | Fixed: the wider set (since the previous total); contract names 28,314.00 |
| m-c | Baseline for sc91 failures | Fixed: `ef7cff3` in both |
| m-d | `offset_of` line | Fixed |

## Pass 3
Reviewer: claude / claude-opus-5-5 / subagent general-purpose (fresh context; ran the engine at ef7cff3 on the sectioned payslip and the contract's 40/4/8 page). Verdict: REVISE (0 BLOCKER, 1 MAJOR, 3 MINOR). All pass-2 findings resolved (B-1 subject to MAJOR-1).

| ID | Finding | Disposition |
|---|---|---|
| MAJOR-1 | P1 step 2's "fit no decimal column" keeps 4 and 8 of the 40/4/8 page as text (they pass `fits` for the Current zone) | Fixed with the reviewer's exact wording: an integer run is a tentative column when its edge is more than ALIGN from every decimal column's median edge at every alignment. Not re-reviewed: the three-pass limit is reached |
| MINOR-1 | Heading detection timing is circular | Fixed: decimal columns keep today's whole-run `supported`; `attached` recomputed after zones; piece support only in step 5 |
| MINOR-2 | Gap sentence misstated today's rule | Fixed |
| MINOR-3 | SL-02 runs too few layout tests | Fixed: all of tests/test_layout_consumers.py |

Loop exit: the three-pass limit is reached with one MAJOR fixed after the last pass but not independently re-checked. Status: NOT READY under plan-feature's rule; the user decides whether to approve with that fix or to run another review round.

## Pass 4 (extra pass, asked for by the user, 2026-11-05)
Reviewer: claude / claude-opus-5-5 / subagent general-purpose (fresh context; simulated P0 and P1 steps 1–5 on the HEAD engine with the real fixtures, outside the repo). Verdict: PASS WITH MINORS (0 BLOCKER, 0 MAJOR). Pass-3 MAJOR-1 and MINOR-1–3 resolved: the sectioned payslip gives Hours 80 / Rate 50.00 / deductions YTD by heading; the 40/4/8 page gives one block, one table, hours 40, 4, 8.

| ID | Finding | Disposition |
|---|---|---|
| MINOR | Step 5 didn't say how a kept integer column enters the reading (re-choosing it via `choose_alignments` loses it) | Fixed: added to the block's columns directly; its runs' `led_by_text` becomes False |
| INFO | Name the exact block edge for cutting heading words | Fixed: the edge `blocks_of` uses (`split − tolerance`) |

Loop exit: no BLOCKER/MAJOR remains. READY for approval.
