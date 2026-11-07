# Test contract: pdf-table-engine-paystubs-cleanup
Spec sha256: the bundle hash from `~/.agent-harness/gate.py hash --feature pdf-table-engine-paystubs-cleanup --stage spec`
(not copied here, because writing it in would change it).

Expected values come from `spec.md`, from the existing tests named below (their assertions are the oracle for parity, as
they stand at `ef7cff3`), from the phase 2 contract's fixtures, or from the generator's inputs. None comes from running the
code under change. Where the spec leaves an outcome open it is listed under "Gaps".

## Conventions
As `specs/pdf-table-engine-paystubs/test-contract.md` "Conventions for every scenario": `tmp_path` libraries, the real
reader, `ExtractionService` with `local_model` answering by schema, C-net, P-checks, C-lines, C-note, C-auto and
C-no-feature-review with the same meanings. New shared check:
- **C-no-grid** (review pass 1, B3): (1) every summary reference and every line's `cell_evidence` of the record cites a
  cell present in the run result's top-level `pay_tables` (an engine cell may reuse a printed cell's id, phase 2 FR-66),
  or the value came from a flat line (no cell reference); and (2) no model request after the `Classification` request
  carries a `reported_tables` entry whose `table_id` is a `table_grid` table id (`layout_context.evidence_tables(result)`
  ids with `source == "pdf_text"`). The `Classification` request is not checked: it is asked before the kind is known.

## SC-90 — the sectioned payslip through the engine
Requirement IDs: FR-90, FR-91, FR-93, FR-95
Fixture: exactly the PDF and model stubs of `tests/test_layout_consumers.py::test_a_sectioned_payslip_copies_every_line_total_and_benefit`
(`tests/test_pdf_layout.py` `sectioned_payslip_items` plus its page-two benefits table).
Actions/checkpoints:
1. Engine level: page 1 has two pay tables side by side; the earnings columns are labelled `Rate`, `Hours`,
   `This Period`, `Year To Date` and the deductions columns `This Period`, `Year To Date` (FR-89, from the one-run headings);
   roles: rate, hours, current, ytd and current, ytd; `80` is the Hours cell of Regular Salary (50.00 × 80 = 4,000.00) and
   `4,000` the Year To Date cell of Relocation Bonus; `Total Deductions (B)` holds this period (1,354.00 = the nine
   Statutory and Voluntary rows) and not year to date (rows 28,314.00, printed 28,434.00); page 1 is not untrusted; page
   2's one-row table is a pay table with This Period and Year to Date. The details box's `Federal Allowances` line forms no
   row (m7: the same page with a lone `2` printed at an amount column's right edge on that line still gives no row).
   Whole hours on several rows (review pass 2, M-2): a page with heading `Description` x 40, `Rate` r 260, `Hours` r 330,
   `Current` r 430, `YTD` r 520 and rows `Regular 25.00 40 1,000.00 13,000.00`, `Overtime 37.50 4 150.00 600.00`,
   `Holiday 25.00 8 200.00 400.00`, then `Gross Pay 1,350.00 14,000.00`: one block, one table; hours 40, 4, 8 and rates
   25.00, 37.50, 25.00 (25.00 × 40 = 1,000.00; 37.50 × 4 = 150.00; 25.00 × 8 = 200.00); no row labelled with a number.
2. Extract -> exactly that test's assertions: gross 400000 / 8800000, net 264600 / 5956600, deductions None,
   display deductions "358.00 USD" and total deductions "1,354.00 USD", the twelve lines with their current/YTD as listed
   there, hours "80" and rate "50.00", none of that test's forbidden issue words.
3. C-no-grid; no record note "Page 1: no pay table was found…"; exactly one record note containing "doesn't match", naming
   28,434.00 and the rows' 28,314.00 (FR-63, the fixture's invented year-to-date total).
Evidence: `pytest tests/test_layout_consumers.py -k sectioned` (unchanged test) and `pytest tests/test_paystub_cleanup.py -k sc90`.

## SC-91 — the layouts the generator avoided
Requirement IDs: FR-92
1. `evals/paystub_layouts.py` draws again each of (a) all-negative rows with YTD left and no heading, (b) a stacked
   layout's second table starting a page under its own heading, (d) a one-column table under a two-line heading,
   (e) hours equal to the stub's year-to-date multiple, (f) a leave or deposit table whose columns line up with the pay
   table's; the generator test asserts each appears ≥ 3 times, and every generated file still records exactly (values from
   the generator's inputs).
2. One hand-built test per case in `tests/test_paystub_cleanup.py` (`sc91_a` … `sc91_f`, no `c`) with literals written in
   the test; each must fail at `ef7cff3` (the handoff records the run), so (f) is built from the generator layout that
   failed there, not from phase 2's PS-OTHER, which already passes: (a) two rows `-50.00 / -600.00` and `-20.00 / -240.00` with YTD printed left: this period is the right column;
   (b) page 2 opens with a stacked layout's second table whose amount columns sit at other right edges than page 1's (as
   STK's 400/500 against 430/520): a new table, page 1's columns unchanged; and phase 2 PS-CONT still continues; (d) the one-column
   table's value is this period; (e) Regular `12.00` hours × `25.00` rate = `300.00` this period, YTD `3,600.00` (12 periods):
   hours 12.00, rate 25.00, this period 30000, YTD 360000, and a `columns_guessed` note only in the no-heading variant;
   phase 2 PS-YTDH (two triples sharing the rate) keeps its SC-57 values;
   (f) the leave table's lined-up columns are a table of their own and give no pay line.
3. (c) is not drawn; `docs/open-work.md` keeps it.
Evidence: `pytest tests/test_paystub_engine_generator.py tests/test_paystub_cleanup.py -k sc91`.

## SC-92 — a page with no pay table the engine trusts
Requirement IDs: FR-93
Fixture: two pages. Page 1: MINI(13) dated 2026-07-03 (phase 2 contract). Page 2 at x 40 from y 700: heading `Item`
`Code A` (right edge 430) `Code B` (right edge 520); rows `Adjustment 50.00 50.00` and `Other 10.00 10.00` (no totals; the
headings name no role, so it is an other table). Model stubs: MINI(13)'s classes, plus a `PayLines` line `Adjustment`,
group `earnings`, current `50.00`, citing page 2's `Adjustment` line.
Actions/checkpoints: Extract -> page 1's lines from engine cells (MINI(13) expected values); the Adjustment line recorded with
the model's 5000 this period; C-note("Page 2: no pay table was found in the printed columns, so its amounts are the reading's; check them.");
C-no-grid (page 2's printed table is not shown to the model nor used to copy).
Variant (m4): a unit test on `finance/paystub_tables.py` with a hand-built pay table whose roles all end `other` (the
untrusted case) asserts its page is in `pages_without_tables` and in no adapted table, so Record reads it flat.
Evidence: `pytest tests/test_paystub_cleanup.py -k sc92`.

## SC-93 — engine fault reads like flat text
Requirement IDs: FR-94
Fixture: phase 2 PS with the engine fault double (`paystub_tables.read` raises). Model stubs: STUB-PS-SWAPPED's classes
with **correct** amounts, and each earning's `hours` and `rate` as printed (m5).
Actions/checkpoints: Extract -> C-note(FR-65's text); C-no-grid; the lines hold the model's correct amounts as judged by the
flat rules (paystub-columns: PS's heading names Current and YTD, so positions are checked and the correct answers pass):
C-lines(EXP-PS); the log has one failure record naming the class and no fixture text.
This replaces `tests/test_paystub_engine_record.py`'s SC-63 assertion that today's path ran (`cell_evidence` `source`
`pdf_text` from the printed table); its note and log assertions stay.
Evidence: `pytest tests/test_paystub_engine_record.py -k sc63` and `pytest tests/test_paystub_cleanup.py -k sc93`.

## SC-94 — parity of the existing pay stub tests
Requirement IDs: FR-95
Each passes **unchanged**: `tests/test_layout_consumers.py` (all but the two listed below), `tests/test_paystub_forms.py` (all; its photo tests are
the photo path), `tests/test_paystub_split.py` (all), `tests/test_paystub_engine.py` (all; SC-58's `SECTION 125` still one
amount), `tests/test_paystub_engine_generator.py` (all, with SC-91's variations added), `tests/test_vision_tables.py`,
`tests/test_extraction.py`, `tests/test_table_engine*.py`.
Also: a file mixing a text page and a scanned page keeps the scanned page's vision tables for its stub (M3).
**Tests this change edits** (and only these): `tests/test_paystub_engine_record.py::test_sc63_*` (SC-93);
`tests/test_paystub_engine_record.py::test_a_table_whose_columns_all_end_other_is_not_trusted_on_its_page` (its page 1
is the sectioned payslip, now trusted: rewritten as SC-90 step 1's engine assertions, FR-89 – FR-91); the probe test in
`tests/test_paystub_engine_generator.py` and `scripts/statement_diagnose.py` where they read `fallback_pages` (they report
untrusted pages from `untrusted_pages` instead);
`tests/test_layout_consumers.py::test_a_sectioned_payslip_records_when_the_model_quotes_rows_without_separators` and
`::test_a_pay_row_listed_again_is_one_pay_line` (their model stubs classified only 4 and 2 of the sectioned payslip's 11 pay
rows, and the grid fallback recorded only those; with page 1 now read by the engine, phase 2 FR-62 records every printed
row, so each stub classifies all 11 rows and each test asserts the 11 lines with their amounts, keeping what it checks:
rows quoted without separators record; a row listed again is one pay line with no note; SL-02 escalation E-1);
`tests/test_evals.py` tests of the legacy pay reader (FR-96); unit tests
of removed code, each named in the handoff with the requirement that removes it.
Evidence: the commands above.

## SC-95 — evals with the engine only
Requirement IDs: FR-96
`tests/test_evals.py`: `summary.json`'s `pay_readers` has `engine` and no `legacy`; its counts are those the phase 2 tests
asserted for the engine on the five aligned files; `guesses` unchanged; the allowlist check passes; `report.md` shows the
engine's pay reader counts and no legacy column. `python -m evals.synthetic <tmp>` still writes 53 cases.
Evidence: `pytest tests/test_evals.py`.

## SC-96 — unit tests for the eight repairs
Requirement IDs: FR-98
`tests/test_pay_tables_repairs.py`: one test per repair listed in `docs/open-work.md` (a summary box above side-by-side
blocks; a repeated stub heading on a later page; a start line ending an empty block's table; a second table with the same
heading words; a partner table beside several tables; two heading phrases printed close together; a text-only line of
several runs; a continuation's column at another alignment), each on a hand-built page with literals in the test. The
handoff records, per test, that reverting its repair (a temporary local edit, not committed) makes it fail.
Evidence: `pytest tests/test_pay_tables_repairs.py`.

## SC-97 — version
Requirement IDs: FR-99
`EXTRACTION_VERSION` differs from `typed-extraction-v35-paystub-engine`; an undecided stub recorded at v35 is re-read on
Extract again (`reused: False`); a confirmed one's `income_records` and `income_lines` rows are unchanged.
Evidence: `pytest tests/test_paystub_cleanup.py -k sc97`.

## Traceability
| FR | Scenarios | Tests |
|---|---|---|
| FR-90, FR-91 | SC-90 | `tests/test_paystub_cleanup.py`, `tests/test_layout_consumers.py` |
| FR-92 | SC-91 | `tests/test_paystub_cleanup.py`, `tests/test_paystub_engine_generator.py` |
| FR-93 | SC-90, SC-92 | `tests/test_paystub_cleanup.py` |
| FR-94 | SC-93 | `tests/test_paystub_cleanup.py`, `tests/test_paystub_engine_record.py` |
| FR-95 | SC-94 | existing suites |
| FR-96 | SC-95 | `tests/test_evals.py` |
| FR-97 | — | doc diff at review |
| FR-98 | SC-96 | `tests/test_pay_tables_repairs.py` |
| FR-99 | SC-97 | `tests/test_paystub_cleanup.py` |

## Gaps
- G1: the exact wording of the FR-92 (e) guess note: the phase 2 `columns_guessed` wording is reused.
- G2: SC-91 (b) – (f) hand-built page coordinates are the implementer's, written as literals in the test; their expected
  values follow from the literals by the spec's rules, stated in each test's docstring.
