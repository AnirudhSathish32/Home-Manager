# Pay stubs, phase 2 follow-up: one path for text PDFs — implementation plan
Spec: specs/pdf-table-engine-paystubs-cleanup/spec.md (with its test-contract.md)
Spec sha256: dc29671638800aa91bc9e61d0b08645f712b6c5210c6d2ba387c1ec65d40580d
Review-Risk: HIGH
Review-Risk-Rationale: It removes the fallback that decided some text-PDF pay stubs' amounts (money in, tax figures) and
changes which printed numbers the engine accepts as amounts, so a defect would put wrong pay into the ledger.

<!-- Approval lives in approvals/<slug>.json, bound to this file's hash. No Status line.
     Execution progress goes in plans/<slug>/progress.yaml, never in this file. -->

**Scope.** FR-89 – FR-99, SC-90 – SC-97. Five slices (review pass 1, M6): unit tests for the eight repairs against today's
code; the sectioned payslip through the engine (FR-89 – FR-91); the avoided layouts (FR-92); the removal (FR-93 – FR-95,
FR-99); evals and docs. Line numbers are from HEAD `ef7cff3`; paths under `src/home_manager/` unless they start with
`tests/`, `evals/` or `docs/`.

## Verified repository integration points
| Area | Where | Use |
|---|---|---|
| Tokens and runs | `documents/pay_tables.py:211` (a run is cut where text or an `integer` follows an amount), `:220` (`led`: a run led by text or an integer); integers come from `documents/table_engine.py` `tokenize` (`INTEGER`) | FR-90: an integer run of its own in an amount zone becomes an amount token |
| Section totals | `finance/paystub_tables.py:170` (rows a total covers: since the previous total or the start of its section), `:179` `pay_columns` (FR-57 b); FR-63's mismatch note uses the same coverage | FR-91: hold if either coverage sums to it |
| Roles | `finance/paystub_tables.py` (P5 a – e of phase 2: pairs, ordering, headings) | FR-92 (a), (e) |
| Extent, headings, continuation | `documents/pay_tables.py` (phase 2 P3.6; SL-08 repairs) | FR-92 (b), (d), (f) |
| Trust gate | `finance/paystub_tables.py:93` `fallback_pages`, `:486`, `:505` `untrusted_pages`, `:556`, `:659` | FR-93: untrusted pages join `pages_without_tables` (flat) — no longer a grid fallback |
| Record | `documents/extraction.py:1277–1279` (`PAY_FAILED`, notes), `:1292` `pay_tables_of` (keeps `table_grid` tables of non-engine pages), `:4123–4150` (`read`: `engine`, `printed_columns`), `:4039` (fault) | FR-93, FR-94 |
| Viewer | `documents/extraction.py` `pay_tables` builder (`:1338–`): empty on a fault | unchanged |
| Evals | `evals/run.py:225–245` (`pay_readers`, the `legacy` branch with `reported_tables`), `evals/report.py:30–32`, `:136`, `:207` | FR-96: engine only |
| Generator | `evals/paystub_layouts.py` (choices that avoid (a) – (f)), `tests/test_paystub_engine_generator.py` | FR-92 |
| Untrusted test and probe | `tests/test_paystub_engine_record.py:543–551` (asserts `fallback_pages == {1}` on the sectioned payslip), `scripts/statement_diagnose.py:80` (prints `fallback_pages`) | Rewritten (SC-94) |
| Vision tables in a pay stub PDF | `documents/layout_context.py:12–15`, `:48–55` (`reported_tables` returns a scanned page's vision tables) | Kept by P4 |
| Classification request | `documents/extraction.py:4030–4031` (`reported_tables` before the kind is known) | Unchanged |
| Parity oracle | `tests/test_layout_consumers.py::test_a_sectioned_payslip_copies_every_line_total_and_benefit` (`tests/test_pdf_layout.py:182` fixture) | FR-95 |
| Version | `documents/extraction.py` `EXTRACTION_VERSION = "typed-extraction-v35-paystub-engine"` | → `typed-extraction-v36-paystub-one-path` |

## Architecture, contracts and decisions
### P0 Heading phrases split by column (FR-89; review pass 1, B2; pass 2, B-2, M-1, m-a)
`heading_runs` (`pay_tables.py:366–382`) already splits a run by zone when two words are more than `size/2` apart; this plan
extends it rather than adding a splitter:
- **Detection.** An all-text line of one run whose words split into two or more zone pieces counts as heading-like for
  `heads_above` / `attached` (`:151–153`, `:419–431`), so the deductions block's one-run line "This Period Year To Date" is
  its heading (today `is_heading_like` needs two runs and `heads_above` stops at that line).
- **Pieces.** Words are assigned to zones by their box centre, after the zones of P1 exist; a new piece starts where the zone
  changes and the gap exceeds `size/2`, as today (pass 3, MINOR-2). Words past the edge `blocks_of` uses (`split − tolerance`, `pay_tables.py:228`, not `block_split`'s own value; review
  pass 4, INFO) belong to the next block and are cut off (so
  the earnings label is "Year To Date", not "Year To Date Deductions"); words over the label zone are dropped from amount
  labels.
- **Support.** A piece supports the column under it (FR-04's one row plus a heading label) at any alignment.
The deductions block's year-to-date column then takes its role from its heading (FR-57 (d)), since its printed total
doesn't hold (B1).

### P1 Whole-number amounts (FR-90; review pass 2, B-1, M-2)
Order inside `read_block`:
1. **Blocks.** A run made of a single integer, between amount runs or after the label run, does not start a group
   (`split_tails`, `group_starts`, `:206–245`), so whole-number hours never start a second block (today three rows of
   `40`, `4`, `8` split the page and become row labels).
2. **Tentative integer columns.** On pay lines, runs holding a single integer whose edge, at every alignment, is more
   than `ALIGN` font sizes from every decimal column's median edge (not `fits`, not `in_zone`: review pass 3, MAJOR-1) form
   tentative columns by alignment (any of right/left/centre, `ALIGN`). Decimal columns are chosen first with today's
   whole-run `supported` rule unchanged (it keeps the sectioned payslip's one-row Rate column; pass 3, MINOR-1).
3. **Zones** are computed from decimal and tentative columns together (on the sectioned payslip the boundaries move to about
   363 and 432, so `Rate` and `Hours` fall in separate zones).
4. **Heading pieces** (P0) are cut over all zones, and `attached` (`pay_tables.py:531`) is recomputed with P0's one-run
   detection now that the zones exist (pass 3, MINOR-1).
5. A tentative integer column is kept when a heading piece sits over it or at least two rows line up in it (piece support
   applies here, not while decimal columns are chosen); its tokens
   become amount tokens (`Token("amount", …, (Decimal(int), None, None))`, the phase 1 `read_line` precedent,
   `table_engine.py:571–572`); otherwise its integers stay text. A kept column is added to the block's columns
   (`found` / `groups` in `read_block`, `pay_tables.py:524–535`) directly, not chosen again by `choose_alignments`, and its
   runs' `led_by_text` becomes False, so `amounts_of`, `is_pay` and `label_of` see it (review pass 4, MINOR). A comma-grouped whole number (`4,000`) is already an amount.
6. Integers in the label run (`SECTION 125`) stay label text; an integer on a line that is no pay line (a details-box line
   such as `Federal Allowances 2`, above the table's first row) is never an amount.
`table_engine.tokenize`, `tokenize_page` and `Line` are not changed (statements can't move, FR-67): everything happens in
`pay_tables.py` (m6).
With `80` an amount under `Hours`, the earnings pair rate × hours = this period (50.00 × 80 = 4,000.00) decides Rate and
Hours by FR-57 (a).

### P2 Totals over several sections (FR-91)
The coverage function returns both candidate row sets (since the previous total; since the previous total or section title);
a total holds when either sums to it. `pay_columns` (b) and the FR-63 note use it. When neither holds, FR-63's note prints the
sum of the rows since the previous total (the wider set): 28,314.00 for the sectioned payslip's year to date (pass 2, m-b).

### P3 Avoided layouts (FR-92)
First step of the slice: re-enable each of (a), (b), (d), (e), (f) in the generator and record, per case, the failing
generator index and what goes wrong at the slice's start head; each fix below is then checked against those failures, and
each hand-built `sc91_*` test must fail at `ef7cff3` (SL-02 doesn't touch these rules; review pass 2, m-c) (M5).
- (a) a voting row is one whose two amounts share a sign (both negative included); magnitudes compare; mixed-sign rows
  don't vote.
- (b) `offset_of` (defined `pay_tables.py:485`, called `:568`) decides continuation from the page's first row: change it so a page's rows continue
  the open table only when every amount column they use lines up with one of the open table's columns at one page offset
  within `ALIGN` font sizes (not the looser within-80-pt match); otherwise they start a new table. `repeats()` (`:552`) keeps
  deciding whether a printed heading is the open table's own. PS-CONT (same columns, 6 pt offset) still continues; STK's
  second table (400/500 against 430/520) on a new page starts its own (M4).
- (d) a one-column table's two-line heading attaches to its column like a one-line heading (the heading-label attachment
  for a single amount zone).
- (e) only when two matching triples share the hours column (hours × rate = this period and hours × this period = year to
  date): take the triple whose product column is the other's factor (this period); headings break the tie first; with no
  heading add a `columns_guessed` guess. Two triples sharing the rate column (PS-YTDH) keep FR-57 (a). Three or more
  triples: (a) decides nothing, and (b) – (e) decide as today (m3).
- (f) the failing generator layout found in the first step decides the fix. Expected direction: before alignment clustering,
  the block's lines are cut at heading lines that start a new table (a heading after a totals line, P3.6 of phase 2), so
  each table's amounts are clustered on their own; the handoff states the failing case and the rule built.
(c) stays avoided.

### P4 One path (FR-93, FR-94)
- `paystub_tables`: `untrusted_pages` stays as the test of "pay table the engine trusts"; those pages go to
  `pages_without_tables` (already at `:556`), and `fallback_pages` is removed as a separate concept.
- `extraction.py` `pay_tables_of`: for pay stub PDFs drops every table with `source == "pdf_text"` (the `table_grid`
  tables) on every page and keeps vision tables of scanned pages (`layout_context.py:48–55`; review pass 1, M3), plus
  `part.adapted`. With `PAY_FAILED`, `read` drops the `pdf_text` tables likewise (flat on every native page) and
  `printed_columns` is every line of the part on those pages. The `Classification` request (`extraction.py:4030–4031`,
  before the kind is known) is unchanged (B3).
- `scripts/statement_diagnose.py:80` and its probe test read `untrusted_pages(pay)` instead of `pay.fallback_pages` (M2). `anchor_paystub`, `paystub_columns`, `role_column` and the grid branches stay
  (vision tables use them). `reported_tables` for the model context is the adapted tables only.
- `EXTRACTION_VERSION = "typed-extraction-v36-paystub-one-path"` (FR-99).

### P5 Evals and docs (FR-96, FR-97)
`evals/run.py` `pay_readers`: the `legacy` branch and its stand-in go; `out = {"engine": …}`. `evals/report.py`: pay reader
summary and markdown show the engine only (`READER_NAMES_PAY` keeps `engine`); allowlist keys unchanged except `legacy`
under `pay_readers` no longer emitted (statement `table_readers` keeps `legacy`). Docs per FR-97; `docs/open-work.md` keeps
(c), unmeasured real-stub accuracy, the probe.

## Error handling and recovery
Engine fault: flat on every page with FR-65's note (P4). Extract again deterministic. Reviewed records kept (`_upsert`).

## Privacy/security and migration impact
No model or network call added; no schema change; `EXTRACTION_VERSION` bump only. Synthetic data only.

## Vertical slices
| ID | FR/SC covered | Dependencies | Files/changes | Verification command / evidence |
|---|---|---|---|---|
| SL-01 | FR-98; SC-96 | none | `tests/test_pay_tables_repairs.py` only (eight tests against today's `pay_tables.py`; each revert-and-fail check recorded in the handoff; no source change) | `.venv/bin/python -m pytest tests/test_pay_tables_repairs.py tests/test_paystub_engine.py -q` |
| SL-02 | FR-89, FR-90, FR-91; SC-90 step 1 (engine level, with m7, and the multi-row whole-hours case) | SL-01 | `documents/pay_tables.py` (P0, P1), `finance/paystub_tables.py` (P2), `tests/test_paystub_cleanup.py` (`sc90` engine step), `tests/test_paystub_engine_record.py::test_a_table_whose_columns_all_end_other_is_not_trusted_on_its_page` (rewritten per SC-94; only that test), `tests/test_layout_consumers.py`'s two partial-stub tests (stubs classify all 11 rows, per SC-94; E-1) | `.venv/bin/python -m pytest tests/test_paystub_cleanup.py tests/test_pay_tables_repairs.py tests/test_paystub_engine.py tests/test_paystub_engine_record.py tests/test_paystub_engine_generator.py tests/test_table_engine.py -q`; `.venv/bin/python -m pytest tests/test_layout_consumers.py -q` (all of it: P0 and P1 change every engine reading; the sectioned payslip is now read by the engine on page 1; pass 3, MINOR-3) |
| SL-03 | FR-92; SC-91 | SL-02 | `documents/pay_tables.py` (P3 b, d, f), `finance/paystub_tables.py` (P3 a, e), `evals/paystub_layouts.py` and `tests/test_paystub_engine_generator.py` (re-enable a, b, d, e, f; ≥ 3 each), `tests/test_paystub_cleanup.py` (`sc91_*`) | `.venv/bin/python -m pytest tests/test_paystub_cleanup.py tests/test_pay_tables_repairs.py tests/test_paystub_engine.py tests/test_paystub_engine_record.py tests/test_paystub_engine_generator.py tests/test_table_engine.py -q` |
| SL-04 | FR-93, FR-94, FR-95, FR-99; SC-90, SC-92, SC-93, SC-94, SC-97 | SL-03 | `finance/paystub_tables.py` (P4 trust → flat), `documents/extraction.py` (P4, version), `tests/test_paystub_cleanup.py` (`sc90`, `sc92`, `sc93`, `sc97`), `tests/test_paystub_engine_record.py` (SC-63 test edited as SC-93 says), `scripts/statement_diagnose.py` and its probe test (M2), a mixed text-and-scan file test (M3) | `.venv/bin/python -m pytest tests/test_paystub_cleanup.py tests/test_paystub_engine_record.py tests/test_paystub_split.py tests/test_layout_consumers.py tests/test_paystub_forms.py tests/test_vision_tables.py tests/test_extraction.py -q`; `.venv/bin/python -m pytest tests/test_paystub_engine_generator.py -k probe -q` |
| SL-05 | FR-96, FR-97; SC-95 | SL-04 | `evals/run.py`, `evals/report.py`, `evals/graders.py` (if the stand-in lives there), `tests/test_evals.py` (legacy pay reader tests → engine only), `docs/documents.md`, `docs/money.md`, `docs/evals.md`, `docs/open-work.md` | `.venv/bin/python -m pytest tests/test_evals.py -q`; `.venv/bin/python -m evals.synthetic <tmp>` writes 53 cases |

## Final verification
```
.venv/bin/python -m pytest -q
RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_paystub_engine_browser.py tests/test_table_engine_browser.py tests/test_document_v2_browser.py -q
```
The 74 failing ids recorded in `plans/pdf-table-engine-paystubs/progress.yaml` `final_verification` (pre-existing at
`44f40b0`) are the only accepted failures; any other is a defect.

## Requirements & scenarios coverage matrix
| Requirement | Slice | Scenarios |
|---|---|---|
| FR-89, FR-90, FR-91 | SL-02, SL-04 | SC-90 |
| FR-92 | SL-03 | SC-91 |
| FR-93 | SL-04 | SC-90, SC-92 |
| FR-94 | SL-04 | SC-93 |
| FR-95 | SL-02, SL-04, final | SC-94 |
| FR-96 | SL-05 | SC-95 |
| FR-97 | SL-05 | doc diff |
| FR-98 | SL-01 | SC-96 |
| FR-99 | SL-04 | SC-97 |

## Test environments, data, stubs, oracle
`tmp_path` libraries; C-net; `local_model` by schema; engine fault by `monkeypatch` of `paystub_tables.read`; oracle: the
contract's literals, the sectioned payslip test's existing assertions, the generator's inputs.

## Risks, alternatives
- **R-A Real stubs that only `table_grid` read right** now read flat and may go to review (spec R1, accepted by D1).
- **R-B FR-90 accepts an integer that is not an amount** (a printed code under an amount column): bounded by alignment and the
  label-run rule; the generator draws label digits and codes beside amount columns.
- **Alternative rejected:** keeping the grid fallback but hiding it. D1 asks for its removal.
