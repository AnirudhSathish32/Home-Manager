# Pay stubs, phase 2 follow-up: one path for text PDFs, and the open work closed
Feature: pdf-table-engine-paystubs-cleanup

<!-- Approval state lives in approvals/<slug>.json and is bound to this file's content hash.
     Do not add a Status line: changing it would change the hash. Check with gate.py. -->

Amends: `specs/pdf-table-engine-paystubs/spec.md` (approved and built, 2026-11-04): D5, FR-51 (bare integers), FR-52
(heading labels), FR-57 (b) and (c) (including "rows where either amount is negative don't vote"), FR-63, FR-64, FR-65, FR-71 and the "what is left" list in `docs/open-work.md` "PDF table engine". Every other
requirement of that spec stands.

## Decisions already made (not to be re-asked)
- **D1 Remove today's text-PDF pay stub path now** (user, 2026-11-04: "go ahead and do the open work for the pdf paystub
  reading go ahead and remove todays pay stub path and if we have issues we can tweak it together"). Supersedes phase 2's
  D5 (remove only after the donated-corpus run). Accuracy on real stubs is still unmeasured; problems found later are
  tweaked with the user.
- **D2 Close the open work for PDF pay stub reading** (same message): whole-number amounts, the layouts the generator
  avoids, unit tests for the generator-found engine repairs. Not in scope: the old statement path (phase 1 D4), FR-41 –
  FR-44, the pre-existing failing tax and agent tests.
- **D3 Guess, don't review** (phase 2 D6) holds for everything here.

## Goal / users / scope / non-goals
**Goal.** A text-PDF pay stub is read one way only: from the engine's pay tables, or, on a page with none, like flat text
(the rules photos use). The printed-table cells of the PDF reader never decide a text-PDF pay stub's amounts again, and
the layouts that sent stubs to that path are read by the engine.

**In scope.** Heading phrases split by column (FR-89); whole-number amounts in amount columns (FR-90); section totals that cover several sections (FR-91); the
generator's avoided layouts that the printed numbers can decide (FR-92); one path for text-PDF stubs (FR-93 – FR-95); the
evals and docs (FR-96, FR-97); unit tests for the eight generator-found repairs (FR-98).

**Non-goals.**
- Photos and scans: unchanged (vision tables, `anchor_paystub`'s heading rules and the paystub-columns checks stay; they
  are the photo path, not "today's text-PDF path").
- Other document kinds: `pdf_layout.table_grid`, `anchor_rows` and `anchor_summary` stay for receipts, bills, statements and
  investment documents (FR-44 is not this).
- A headless stub whose hours or rate print on one row only (no column can be formed from one unheaded row): stays a known
  limit, documented.

## Existing behavior (verified paths)
Paths under `src/home_manager/` unless noted. Built by `specs/pdf-table-engine-paystubs` (HEAD `ef7cff3`).
- `documents/extraction.py` `read`: for a pay stub PDF, `pay_tables_of` keeps the reader's `table_grid` tables on pages the
  engine read no trusted table on, and `anchor_paystub` copies their cells with heading rules (`paystub_columns`). On an
  engine fault (`PAY_FAILED`) the whole stub takes that path with the FR-65 note. `finance/paystub_tables.py`
  `untrusted_pages` / `fallback_pages` mark pages whose pay table's columns all ended `other`.
- `tests/test_layout_consumers.py::test_a_sectioned_payslip_copies_every_line_total_and_benefit` (fixture
  `tests/test_pdf_layout.py` `sectioned_payslip_items`) is read today by the `table_grid` fallback (`finance/paystub_tables.py`
  `untrusted_pages` marks page 1). The engine misses three things there (review pass 1, verified): hours `80` is a plain
  integer, which the engine drops (`4,000` is already an amount token, `documents/table_engine.py:197`); each block's
  heading is printed as one run ("Rate Hours This Period Year To Date"): column zones come from decimal amounts only, so
  `Rate` and `Hours` share a zone and `80` fits none, and a one-run heading line isn't detected as a heading
  (`documents/pay_tables.py:151–153`, `:366–382`, `:533`), so the deductions block's columns get no heading;
  and `Total Deductions (B)` covers both the Statutory and Voluntary sections, which FR-57 (b)'s "since the previous total
  or section title" doesn't add up to. Its printed year-to-date deductions total (28,434.00) is also 120.00 more than its
  rows (28,314.00): an invented amount.
- `tests/test_paystub_engine_record.py` SC-63's test asserts today's path ran on an engine fault (`cell_evidence`
  `source` `pdf_text` from the printed table).
- `evals/run.py` / `evals/graders.py`: `pay_readers` compares a `legacy` reader (`table_grid` + `paystub_columns`) with the
  engine.
- `docs/open-work.md` "Pay stubs (phase 2 …): what is left" lists the avoided layouts (a – f below) and the eight repairs.

## Functional requirements
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-89 | **Heading phrases split by column.** A heading line printed as one run across several amount columns ("Rate Hours This Period Year To Date") is a heading, and gives each column the words that sit over its zone (words past the block's edge belong to the next block), for heading support (FR-04's "one row with a heading label") and for labels (FR-57 (d)). Supersedes FR-52's run-level labels. | The sectioned payslip's earnings columns are labelled Rate, Hours, This Period, Year To Date and its deductions columns This Period, Year To Date (SC-90). |
| FR-90 | **Whole-number amounts.** Numbers without decimals (`80`) that are runs of their own (not in the label's run) and line up in a column of their own, under a heading word or on at least two rows, are amounts of that column; they never start a second block. (A comma-grouped `4,000` is already an amount.) A number in the label's run (`SECTION 125`, `401K`) stays label text. Supersedes FR-51's "a bare integer is label text" for numbers in amount columns. | The sectioned payslip's hours `80` is the Hours cell of Regular Salary and rate × hours = this period decides the Hours and Rate roles; `SECTION 125 85.00` still gives one amount (SC-58 unchanged); a lone integer in a details box above a table (`Federal Allowances 2`) is no pay row (SC-90). |
| FR-91 | **Totals covering several sections.** A printed section total holds when it equals the sum of the rows since the previous total, or of those since the previous section title (FR-57 (b) and FR-63 use the same rule). | The sectioned payslip's `Total Deductions (B)` 1,354.00 holds over the Statutory and Voluntary rows this period; its year-to-date 28,434.00 is 120.00 more than its rows, so that column takes its role from its heading (FR-89) and the record has FR-63's note naming 28,434.00 (SC-90). |
| FR-92 | **Layouts the generator avoided**, read right where the printed numbers decide: (a) rows all printed negative, year to date left of this period, no heading: rows whose two amounts share a sign vote by magnitude (supersedes phase 2 FR-57 (c)'s "rows where either amount is negative don't vote"; rows of mixed sign still don't vote); (b) a stacked layout's second table starting a page: a page's first rows continue the open table only when every amount column they use lines up with one of the open table's columns at a single page offset within the alignment tolerance; otherwise they start a new table (a page repeating the same columns, phase 2 PS-CONT, still continues); (d) a one-column table under a two-line heading reads like one under a one-line heading; (e) hours equal to the stub's year-to-date multiple, so that hours × this period = year to date as well as hours × rate = this period (two triples sharing the hours column): the triple whose product is the smaller column is taken (this period), with a `columns_guessed` note only when headings don't settle it; two triples sharing the rate column (phase 2 PS-YTDH) keep FR-57 (a); (f) a leave or deposit table whose columns line up with a pay table's: columns are formed per table, between heading lines, so they don't merge. (c) one-row hours or rate with no heading stays a known limit. | The generator draws (a), (b), (d), (e), (f) again (each ≥ 3 times) and records every value exactly (SC-91). |
| FR-93 | **One path for text-PDF pay stubs.** On a pay stub PDF, once the file is classified as a pay stub, the reader's printed tables (`table_grid`, `source == "pdf_text"`) are never used to copy, check or show the model a pay stub's amounts (the classification question, asked before the kind is known, is unchanged; an engine cell may reuse a printed cell's id, phase 2 FR-66); vision tables of scanned pages in the same file are kept: every `embedded_text` page's amounts come from the engine's pay tables, and a page with no pay table the engine trusts is read like flat text (the model's values, FR-22 guards, and the paystub-columns checks on that page's lines), with FR-64's note. | Every text-PDF pay stub test reads through the engine or the flat rules; every recorded value cites a cell of the run's engine `pay_tables` or a flat line; no request after classification carries a `table_grid` table (SC-92). |
| FR-94 | **Engine fault.** When the engine raises, the stub is read like flat text on every page (the photo rules) with FR-65's note, never from printed-table cells. | SC-93. |
| FR-95 | **Parity.** Every existing text-PDF pay stub scenario keeps its values through the engine, in particular `test_a_sectioned_payslip_copies_every_line_total_and_benefit` (every line, gross/net this period and YTD, deductions, hours `80` and rate `50.00`, the page-two benefit row, no review issue named in that test). Tests that assert today's path ran change only as the test contract lists. | SC-90, SC-94. |
| FR-96 | **Evals.** The legacy pay reader is removed: `pay_readers` reports the engine only (its `legacy` entry and the legacy stand-in for "sent to review" go), `summary.json` stays counts only and passes the allowlist, and `report.md` shows the engine's counts. The statement comparison (`table_readers`) is unchanged. | `python -m pytest tests/test_evals.py` passes with the engine-only `pay_readers` (SC-95). |
| FR-97 | **Docs.** `docs/documents.md` "Pay stub rows from the printed columns", `docs/money.md` "Money in and paystubs" and `docs/evals.md` "The two table readers" describe the single path; `docs/open-work.md` drops the done items and keeps (c), the unmeasured accuracy on real stubs, and the probe for a stub that reads badly. Headings stay stable. | Doc diff present. |
| FR-98 | **Unit tests for the eight generator-found repairs** (`documents/pay_tables.py`, listed in `docs/open-work.md`): each has a test of its own on a hand-built synthetic page, written so that reverting that repair fails it. | Eight tests; the handoff records each revert-and-fail check (SC-96). |
| FR-99 | **Versions.** `EXTRACTION_VERSION` changes, so readings recorded through today's path are read again on Extract again; reviewed records are never rewritten (phase 2 FR-68). | SC-97. |

## Invariants, privacy, security and data retention
- Every recorded amount is a printed number; a whole-number amount is recorded as printed (`80` hours, 400000 minor for
  `4,000`). Money stays exact. No model or network call is added. Synthetic fixtures only; P:\Finances,
  %LOCALAPPDATA%\HomeManager and P:\EvalCorpus are never read.
- Photos, scans and every non-pay-stub kind behave exactly as before.

## Errors, recovery, restart
- Engine fault: FR-94. Extract again is deterministic (phase 2 FR-69). Reviewed records are kept (FR-99).

## Nondeterministic outputs and how they are verified
- Model answers are fixed stubs by schema; the engine and generator are deterministic; expected values come from the
  contract and the generator's inputs.

## Scenarios
| ID | FR IDs | Initial state | Actions | Expected |
|---|---|---|---|---|
| SC-90 | FR-89, FR-90, FR-91, FR-93, FR-95 | The sectioned payslip PDF of `test_a_sectioned_payslip_copies_every_line_total_and_benefit`, its stubs | Extract | That test's expected values, read from engine cells (no "no pay table" note on page 1); one FR-63 note naming 28,434.00 and none for 1,354.00 |
| SC-91 | FR-92 | The generator with (a), (b), (d), (e), (f) drawn again | Generator test | Every value exact; each drawn ≥ 3 times |
| SC-92 | FR-93 | A text-PDF stub whose page holds a printed table the engine doesn't trust (all columns other) and a model stub value on that page | Extract | The model's value judged by the flat rules on that page, FR-64's note; no `table_grid` cell cited |
| SC-93 | FR-94 | PS with the engine fault double | Extract | Flat reading with FR-65's note; no `table_grid` cell cited |
| SC-94 | FR-95 | Every text-PDF pay stub test of `tests/test_layout_consumers.py`, `tests/test_paystub_forms.py`, `tests/test_paystub_engine_record.py`, `tests/test_paystub_split.py` | Run | All pass, except those the contract lists as changed |
| SC-95 | FR-96 | Synthetic eval corpus | `tests/test_evals.py` | `pay_readers` has the engine only; allowlist passes |
| SC-96 | FR-98 | Eight hand-built pages | Engine tests | Each passes; each fails with its repair reverted |
| SC-97 | FR-99 | A stub recorded at the previous version; a reviewed one | Extract again | The undecided one re-read; the reviewed one unchanged |

## Supersedes
- Phase 2 D5 → D1. FR-52's run-level heading labels → FR-89. FR-51's bare-integer clause → FR-90 for amount columns. FR-57 (c)'s
  negative-row rule → FR-92 (a). FR-57 (b)'s total coverage → FR-91. FR-64 and
  FR-65's "today's path" → FR-93, FR-94 (flat rules). FR-71's legacy comparison → FR-96.

## Out of scope / open decisions (recommended defaults; "defaults ok" takes them)
- **OD-1 Pages the engine doesn't trust** read like flat text (FR-93) rather than refusing the stub. *Why:* the photo rules
  already guard flat values; it keeps D3.
- **OD-2 FR-92 (e)** takes the this-period triple and notes a guess only when no heading settles it. *Why:* a stub's
  hours × rate = this period is the normal line; the other product is a coincidence of n periods.
- **Domain risk R1:** a real stub that today reads right only through `table_grid` (a layout no fixture covers) will now
  read flat and may go to review. *Default:* accepted (D1); found stubs are tweaked with the user; the probe prints their
  shapes.
