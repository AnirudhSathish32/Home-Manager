# Table engine, phase 2: pay stubs read from their printed columns
Feature: pdf-table-engine-paystubs

<!-- Approval state lives in approvals/<slug>.json and is bound to this file's content hash.
     Do not add a Status line: changing it would change the hash. Check with gate.py. -->

Amends: `specs/pdf-table-engine/spec.md` FR-40 (makes it concrete and corrects its rule for telling Current from YTD,
see "Supersedes") and its non-goal "Splitting one PDF into several accounts" (pay stubs only: several stubs in one file
are split, FR-80 – FR-84); `specs/document-forms/spec.md` cell anchoring of pay stubs, for text-PDF stubs only;
`specs/paystub-columns/spec.md` FR-31 for text-PDF stubs only (a text PDF "with no rebuilt table" is read like flat
text). Every other requirement of those specs stands, including pdf-table-engine FR-01 – FR-34, document-forms FR-21 –
FR-23 (hours × rate, the this-period guards, corrections) and paystub-columns FR-32 – FR-36 for photos and scans.

## Decisions already made (not to be re-asked)
- **D1 – D2 from phase 1** (user, 2026-10-27) hold: no per-employer or per-payroll-provider templates; one engine for every
  text PDF; what proves a table was read right is a small arithmetic check per document kind.
- **D3 Pay stubs are phase 2** (phase 1 D3 order, FR-40 first of the later phases). Phase 1 is built
  (`docs/open-work.md` "PDF table engine").
- **D4 Own spec and test contract** (phase 1 OD-5): this spec and its test contract are approved before anything is built.
  Bills, receipts, investment statements and replacing `pdf_layout.table_grid` for other kinds (FR-41 – FR-44) stay out.
- **D5 Old path kept until parity** (phase 1 D4): today's text-PDF pay stub path stays for the evals' comparison and the
  engine-fault fallback, and is removed only after the user reports the engine at least as good on their corpus.
- **D6 Guess, don't send to review** (user, 2026-11-03: "make it so that the least amount of items are sent to review …
  let it guess and we will work on making the guesses better and better"). Where the engine has to choose (which column
  is this period, which group an unclassified line is in, which summary value to trust), it picks its best choice,
  records it, and adds a note saying what it chose and why. A guess is never a review reason. The evals count every
  guess and how often it was right, so guesses can be improved (FR-74). A stub goes to review from this feature only
  when its printed numbers still don't add up after the best guess (today's arithmetic checks, unchanged).
- **D7 Summary box in scope** (user, 2026-11-03, on R1). A summary table printed on the stub itself, across rather than
  down (see FR-75), is read in this phase. The user also asked that the document page show what the engine read: the
  pay stub's Tables tab shows the engine's pay tables and their column roles (FR-76).
- **D8 Several pay stubs in one PDF are split** (user, 2026-11-03: "should be split into multiple paystubs within the
  system"). Each becomes its own pay stub record (FR-80 – FR-84). Supersedes the first draft's R2 (one review issue,
  no splitting).
- **D9 Defaults taken** (user, 2026-11-03, "defaults ok"): OD-1, OD-2, OD-5, OD-6 and OD-7 take their recommended
  defaults, and risks R6 – R8 are accepted with theirs: R6 adds nothing new, R7 is binding as FR-80's heading rule and a
  generator variation (FR-70), R8 is FR-85.

## Goal / users / scope / non-goals
**Goal.** Any text-PDF pay stub, from any employer or payroll provider, in any layout, gives every pay line's this-period
and year-to-date amount (and hours and rate where printed) from the column it is printed in, with as few stubs sent to
review as possible. Every choice the engine makes is written down so it can be measured and improved. A file holding
several stubs gives one record per stub. The model classifies lines; it never decides which printed number is which.

**Users.** The household user recording pay stubs (Extract / Record) and reviewing them on the document page.

**In scope.**
- The engine reads pay tables: rows with no date, side-by-side blocks, section titles, totals lines and the summary box
  (FR-50 – FR-56, FR-75).
- Pay column roles decided from printed numbers, with a recorded guess where they don't settle it (FR-57 – FR-59).
- Record copies a text-PDF stub's amounts from the engine's cells (FR-60 – FR-66).
- The document page shows the engine's pay tables (FR-76).
- Several stubs in one file split into separate pay stubs (FR-80 – FR-84).
- Statements unchanged, switch-over, determinism, generator, evals with guess counts, docs (FR-67 – FR-74).

**Non-goals.**
- Reading photos and scans with the engine: no word positions (pdf-table-engine non-goal). They keep vision tables and
  the paystub-columns rules. Splitting (FR-80) applies to them too, because it reads only the transcribed lines.
- W-2 and other tax forms (form reader).
- Direct-deposit splits, leave balances (PTO, sick) and tax filing details stay as the model reads them
  (`pay_details`, docs/documents.md "Pay stub and statement fields"). Their tables are found and set aside (FR-56).
- The Tables tab for other document kinds, and the other `table_grid` consumers (FR-44).
- Decimal-comma amounts (phase 1 OD-3), and any model or network call added by the engine.
- Donating a split pay stub (as for split receipts, docs/documents.md "Several receipts in one file").

## Existing behavior (verified paths, assumptions, unknowns)
Paths under `src/home_manager/` unless noted.

**Text-PDF pay stubs today.**
- Tables come from the reader's own finder, `documents/pdf_layout.py` `table_grid`, which needs a printed text header
  row and refuses headerless, spanning and wrapped tables ("Headerless, spanning and wrapped candidates stay text").
  A headed side-by-side payslip is already split into its two tables (`side_table`; verified by
  `tests/test_layout_consumers.py::test_a_side_by_side_payslip_copies_every_line_and_total`).
  `layout_context.evidence_tables` passes them to extraction as `source == "pdf_text"` tables, and
  `layout_context.viewer_context` gives the same tables to the document page's Tables tab.
- With any table, `read` runs `anchor_paystub` (`documents/extraction.py:3798`). Columns are named by heading words
  only (`paystub_columns`, `:973`: `current`/`this period`, `ytd`/`year to date`, else a lone `amount`); headings that
  conflict or are missing give "Pay line N has conflicting or unknown column headings; check its amounts." Hours and
  rate come from columns headed Hours/Rate (`role_column`, `PAY_ROLES`, `:1263`). Gross and net come from the one
  totals row when exactly one is printed (`TOTAL_ROWS`, `:1262`).
- With no table, the stub is read like flat text (`printed_columns`, `:3797`): the model's values, then the
  paystub-columns position checks (`column_checks`, `printed_header`), which null a value and send the stub to review
  when it doesn't match the printed columns. Verified by
  `tests/test_layout_consumers.py::test_a_text_pdf_stub_with_no_rebuilt_table_is_read_like_flat_text`.
- Unaccounted native rows are one count note: "N native table row(s) were not accounted for…" (`:3846`), totals rows
  excepted.
- `paystub_lines` (`:3029`) checks earnings = gross and gross − pre-tax − taxes − post-tax = net, per column (YTD only
  when every line has one), runs the FR-22 guards (`this_period_guards`), and hours × rate (`document_checks.hours_rate`).
- A record counts automatically only when its checks pass and "nothing was ambiguous or dropped"; anything else goes
  to Needs review (docs/documents.md "Counted automatically or reviewed"). A note kept in a record's details is not a
  review reason (`extraction.py:2179`, as bills use it).

**One pay stub per file today.** `income_records.blob_hash` is `UNIQUE`
(`library/migrations/050_strict_tables.sql:411`), and `Ledger.publish_income` upserts one record per file
(`finance/ledger.py:1452`). Receipts already split: `receipts.segment` with `UNIQUE(blob_hash, segment)` and
`document_segments` (`library/migrations/054_receipt_segments.sql`), a `ReceiptStarts` model question, and Confirm
split / Merge with next / Split here on the document page (docs/documents.md "Several receipts in one file"). A split
receipt waits in Review until the split is confirmed.

**The engine** (`documents/table_engine.py`, phase 1) finds a row only at a line with a **date** and an amount
(`EngineRow.dates`; module docstring). Pay stub rows print no date, so today it finds no pay table. It already gives
columns by alignment (`ALIGN = 0.75`), two-line headings, continuation pages, totals (`Total`) and unplaced lines; amount
tokens are exact `Decimal`s, a bare integer is an `integer` token and a number joined to text stays text (FR-02).

**Evals.** The synthetic corpus has 7 pay stubs (`evals/synthetic.py:263–269`); one is a PDF printed as flowed lines
(`write_pdf`), none in aligned columns, none several to a file. The `document_forms` task reports pay stub values per
layout (`docs/evals.md`). The phase 1 comparison (`table_readers`) covers statements only.

**Assumptions**
- A1: A pay line prints its label and its amounts on one visual line, or its label wraps onto the line(s) directly
  below, indented or within the label column (OD-2).
- A2: Year to date includes this period, so on a line printing both, |this period| ≤ |year to date|.
- A3: A stub that prints totals names them in words (gross, net, total …). Totals are found by those words, as phase 1
  finds balance lines by theirs; column headings are still never required.
- A4: Each pay stub in a file prints its own pay date (or pay period) and its own net pay. A second page of one stub
  that repeats the employer and pay date but prints no net pay of its own is a continuation, not a new stub.

**Unknowns**
- U1: The layouts of the user's own pay stubs were never opened (CLAUDE.md). A redacted shape probe like
  `scripts/statement_diagnose.py` (OD-6) would confirm how common side-by-side blocks and summary boxes are.

## Functional requirements

### The engine: pay tables (text PDFs)
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-50 | **Labelled rows.** On a pay stub, a row starts at a visual line with text at its left (the label) and at least one amount token in an amount column. No date or heading is needed. The statement row shape (FR-03) is unchanged for statements. | A stub with its headings deleted gives the same rows as with them (SC-55). |
| FR-51 | **Amounts and labels.** An amount column holds amount tokens (FR-02). A bare integer (`SECTION 125`) and a number joined to letters (`401K`, `403(b)`, `W2`) are label text, never amounts. Hours and rates are amount tokens until FR-57 gives them their role; a rate may print more decimals than the currency. | `PRE-TAX 401K 184.98 2,404.74` gives label `PRE-TAX 401K` and two amounts; `SECTION 125 85.00` gives one amount (SC-58). |
| FR-52 | **Columns by alignment** as FR-04 (same tolerance). Headings, when printed, label the columns under them, including two-line headings (`This` over `Period`, `Year to` over `Date`); their wording is never required. | Two-line, unknown-wording and missing headings give the same columns (SC-51, SC-55). |
| FR-53 | **Side-by-side blocks.** Many stubs print two tables next to each other on the same lines: earnings on the left half of the page, taxes and deductions on the right half, so one printed line reads `Regular 80.00 2,500.00 32,500.00   Federal tax 250.00 3,250.00`. When lines carry two label-and-amounts groups like this (a label column after amount columns, with amount columns after it), each group is a table of its own. A row holds only its own block's words. | An ADP-style stub with earnings left and taxes and deductions right gives two tables, every row in its own block (SC-52). |
| FR-54 | **Sections and extent.** A text-only line at the table's left edge followed by a row is a section title (`Earnings`, `Taxes`, `Statutory`, `Pre-tax deductions`), kept as the rows' section; the table continues across it when the next rows fit its columns. A different column set starts a new table (stacked Earnings / Taxes / Deductions tables). An indented text-only line directly under a row joins that row's label (OD-2). Continuation pages follow FR-06. | Stacked tables with and without their own headings, section titles and 2-line wrapped labels give one row per pay line with its full label (SC-53, SC-54). |
| FR-55 | **Totals lines** (gross pay, total earnings, total taxes, total deductions, net pay, also lettered: `Total Earnings (A)`, `Net Payment (A-B)`) inside or below a pay table are totals with a value per amount column, not pay lines. A heading or repeated page heading is ignored. | `Gross Pay 2,500.00 32,500.00` is a total in both columns and no row (SC-51). |
| FR-56 | **Non-pay tables and nothing dropped silently.** A table is a pay table when FR-57 (a) or (b) finds a pay column in it, or its headings name this period or year to date, or it sits side by side with a pay table (FR-53); FR-57 (c) – (e) then name its columns. Others (deposit distribution, leave balances, filing status) are other tables: their rows are no pay lines. Every other line on a pay table's pages that holds a label and an amount and is not a row, a total, a heading, a summary box line or an other-table row is an **unplaced line**: it is listed in a note with page and text (D6: a note, not a review reason). | rows + totals + summary + other-table rows + unplaced = every label-and-amount line (SC-60); a PTO table (`Vacation 40.00 8.00 32.00`) gives no pay lines (SC-56). |

### Pay column roles (from printed numbers only)
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-57 | **Roles** are decided per pay table from the printed numbers alone (no model output), in this order: **(a) hours and rate:** the one pair of columns where hours × rate gives the amount of a third column on every row printing all three (at least one row), by document-forms FR-21's product rule (a rate printed to 4 decimals included); that third column is this period. When two pairs share the rate column (Hours × Rate = Current and YTD hours × Rate = YTD), both product columns are pay columns, (c) tells them apart, and the hours column of this period's pair is hours; the other is other. With no rate column, a column headed Hours is hours. **(b) pay columns:** a column with at least one printed section total in it (gross pay, total earnings, total taxes, total deductions; net pay is not a section total) where each such total equals the sum of the rows it covers (the rows since the previous total or section title), is a pay column. Net pay is checked afterwards by today's checks (FR-63). **(c) this period or year to date:** of two pay columns, this period is the one whose amount is ≤ the other's in magnitude on every row printing both, and smaller on at least one. Totals don't vote, and rows where either amount is negative (retro pay, reversals) don't vote. With no voting row, FR-59 applies. When every voting row is equal (a first paycheck), either column gives the right values: the headings decide, else the left column is this period. **(d) headings** break any remaining tie, and are the only guide when (a) – (c) decide nothing (no totals, one row). **(e)** One pay column with no heading is this period, within a pay table. Any other amount column is **other** and never money (YTD hours, prior period, an employer-cost column that fails the totals). | Columns in any order, with or without headings, give the right roles (SC-50, SC-55); YTD hours, rate and employer columns are other (SC-57). |
| FR-58 | **Headings that contradict the numbers.** When (a) – (c) decide against the headings (the column headed YTD is the smaller), the numbers win and a note names the page and both headings (D6). | SC-61 (a): values by the numbers, the note, no review reason. |
| FR-59 | **When the numbers don't settle it** (two pay columns with no voting row, or whose rows disagree on which is larger, and no deciding heading), the engine guesses in this order: the column smaller on more voting rows is this period; on a tie, the left column. The values are copied by the guess, and a note says so ("Page N: the left column was taken as this period; the printed amounts didn't tell the two columns apart"). Not a review reason (D6). | SC-61 (b): values by the guess, the note; the guess is no review reason (FR-22 still judges a row printed larger in the column taken as this period). |

### Where the engine is used (Record)
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-60 | Record uses the engine's pay tables on every `embedded_text` page of a pay stub PDF. On those pages the model classifies each pay line (group, category) and cites its row; every this-period, year-to-date, hours and rate value is copied from that row's cell in its role column. A blank cell stays blank. The model's numbers decide nothing there. | A stub whose model stub answers every amount wrongly still records the printed amounts (SC-50); a bonus printed only under YTD keeps this period blank (SC-69). |
| FR-61 | **Gross, net, taxes and deductions** come from, in order: the pay table's totals line in the matching column when exactly one is printed (as today's `TOTAL_ROWS`); the summary box (FR-75); the model's value with today's checks. When a totals line and the summary box disagree, the one that agrees with the pay lines' sums is kept, with a note. A single printed combined deductions total still never fills pre-tax deductions (unchanged). | SC-51, SC-70. |
| FR-62 | **Matching and unclassified lines.** A model pay line citing a line of an engine row takes that row; two model lines on one row keep the first and add a note (as today). A model line citing a pay table line that is no row (a total, a section title) is left out with today's note. An engine row with an amount that no model line cites is still recorded, with a guessed group: its section title's group (earnings; taxes; pre-tax; post-tax or deductions; employer), else the group under which the stub's totals hold, else the group of the rows around it. A note names it and the guess (D6). This replaces today's count note on engine pages. | SC-60: the unclassified row is recorded in its guessed group with a note; no review reason. |
| FR-63 | **Checks.** Today's checks run on the copied values (earnings = gross, gross − pre-tax − taxes − post-tax = net, per column; hours × rate; the FR-22 guards), with today's effect: a check that fails after the best guesses still sends the stub to review, because the printed numbers then don't add up. A printed section total that its rows don't add up to is a note naming page and total. The engine adds no review reason of its own. paystub-columns FR-33 and FR-35 don't run on engine pages (the cells decide). | A stub whose Total taxes is misprinted but whose gross and net hold has a note and no review reason; one whose net doesn't follow from its lines needs review (SC-62). |
| FR-64 | **Pages with no pay table** (and readings saved without layout) keep today's path for those pages (`table_grid` cells if any, else flat text with the paystub-columns checks) and add a record note: "Page N: no pay table was found in the printed columns, so its amounts are the reading's; check them." Photos and scans are unchanged. | SC-59. |
| FR-65 | **Engine failure** (an exception): the whole stub takes today's path with a note "The pay table couldn't be read from the printed columns, so the reading's amounts were used; check them.", logged by `log_failure` without document text. | SC-63. |
| FR-66 | **Evidence.** Each copied value cites its printed words (or its native cell when the row is one native row), and `row_label` / `column_heading` cite the row's label words and the column's heading words when printed (none when no heading is printed). The document page lights them. | `GET /api/provenance` for a pay line lists its words; a wrapped label cites both lines (SC-54). |

### The summary box and the document page
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-75 | **The summary box.** Many stubs print a small table at the top, across rather than down: its column headings are the totals (`Gross Pay`, `Taxes`, `Deductions`, `Net Pay`, in any order and wording) and its rows are this period and year to date (`Current`, `YTD`), for example `Current 2,500.00 412.50 250.00 1,837.50` / `YTD 32,500.00 5,362.50 3,250.00 23,887.50`. The engine finds it as a table of two rows and at least four amount columns where, on every row, the largest amount (gross) equals the sum of three others. Net is the largest of those three on the this-period row; heading words, where printed, name the columns instead and must agree with the sum. Taxes and deductions are told apart by heading words, else by left-to-right order (taxes first), with a note (D6). Other columns in the box (federal taxable wages, say) are other. Its rows take this period and YTD by A2's ordering, headings breaking ties. | SC-70: values from the box with no heading wording needed; a box whose columns are shuffled reads the same. |
| FR-76 | **The document page shows what the engine read.** On a pay stub read by the engine, the Tables tab shows the engine's pay tables and summary box instead of `table_grid`'s for those pages: rows, each column's role (This period, Year to date, Hours, Rate, Other), and the cells each value came from, linked to their lines as today. Every guess the engine made (FR-58, FR-59, FR-62, FR-75) is shown beside the table it concerns, in the note's words. The page follows docs/ui.md "Screen rules" (source beside the record, money from the server, strict CSP, no framework). | SC-71. |

### Several pay stubs in one file
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-80 | **Finding the stubs.** A pay stub file holds several stubs when its transcribed lines print more than one stub start: a pay date (or pay period) line followed, before the next such line, by its own net pay. Each stub runs from its start, with the employer heading lines just above it, to the line before the next stub's start. A pay date line that repeats the pay date of the stub being read, before that stub has printed its net pay, continues it (a stub's second page repeating its heading, A4). Any part left without a net pay of its own joins the stub before it (the first part joins the one after it). The rule reads lines only, so it works on text PDFs, scanned PDFs and images, and needs no model question. A file with one stub reads exactly as today. | A PDF of 3 stubs, one per page, gives 3 stubs; a 2-page stub whose page 2 repeats the heading gives 1; 2 stubs on one page give 2 (SC-72). |
| FR-81 | **Each stub is its own pay stub.** Each part is read on its own lines (the engine on text pages), checked, and published as its own pay stub record (segment 0, 1, …), with its own deposit match, money in on its own pay date and its own review status. A part that classifies as something other than a pay stub makes the file read as one document, as for receipts. | 26 bi-weekly stubs in one file give 26 records, each with its pay date and net pay, each matched to its own deposit (SC-73). |
| FR-82 | **No review for the split** (D6). Unlike receipts, a split pay stub doesn't wait in Review: it carries a note "Split from a file holding several pay stubs", which is not a review reason. The document page offers Confirm split, Merge with next and Split here, as for receipts; your own split wins on later readings and the file is recorded again. | SC-74. |
| FR-83 | **Storage.** Pay stub records are numbered by segment within their file, like receipts: a schema migration makes them unique by file and segment, and every existing record becomes segment 0, unchanged. A segment a later reading no longer finds stops counting (restored if found again); a stub you decided keeps your decision, with a note to check the split. | SC-75: an upgraded library keeps every record and id; re-reading a 3-stub file twice gives the same 3 records. |
| FR-85 | **Void and reissued stubs** (R8). A stub that prints VOID is recorded but doesn't count as money in, with a note. Two stubs with the same employer and pay date follow duplicate handling. | SC-76. |
| FR-84 | **In the library**, a file holding several stubs has no single amount, its date is the earliest stub's pay date, and it is filed under the first stub's employer and pay date (as split receipts). Duplicates (the same stub in two files, or twice in one file) follow today's duplicate handling. | SC-73. |

### Statements, existing data, switch-over and measurement
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-67 | **Statements unchanged.** Labelled rows are read only on pay stubs. Every statement result is the same: the phase 1 generator's 200 cases, the `aligned` eval cases and every statement test pass unchanged. | SC-64. |
| FR-68 | `EXTRACTION_VERSION` changes, so older readings aren't reused. No migration rewrites a record's values; a reviewed stub is never rewritten; Extract again re-reads an undecided one (document-forms D5). | SC-65. |
| FR-69 | Deterministic: the same reading gives the same pay lines, values, guesses, evidence, notes and splits; Extract again on an unchanged reading changes nothing; the engine and the split rule make no model or network call. | SC-66. |
| FR-70 | **Pay stub layout generator.** At least 100 synthetic text-PDF stubs from a fixed seed, varying: one table, stacked tables, side-by-side blocks; with and without a summary box; with and without Hours/Rate (and YTD hours, and 4-decimal rates); column order; headings known, unknown, none, one or two lines; with and without YTD; rows printed in one column only (a YTD-only bonus); retro and negative lines; label digits; parenthesised and minus deductions; totals present or absent; an employer-cost column; wrapped labels; two pages; a deposit and a leave table; and files of 1 to 4 stubs, with the employer heading above or below the pay date (R7). Each records every value exactly and splits exactly (expected from the generator's inputs, the model's classification stubbed from them). | The generator test passes with zero misses; failures print seed and layout (SC-67). |
| FR-71 | **Eval.** The synthetic corpus gains five aligned-column text-PDF pay stub files (one table with Hours/Rate/Current/YTD; stacked sections with no headings; side-by-side blocks with a summary box; two-line headings with a YTD-only row; a file of three stubs), appended after the existing 48 documents so no id or answer changes. The documents suite compares, for text-PDF pay stubs, today's path and the engine: share of pay values recorded exactly, stubs whose checks hold, stubs sent to review, stubs split right, and unplaced lines; counts only, so `summary.json` stays within its allowlist. The user runs it on the donated corpus in their own terminal (docs/evals.md). | `python -m evals.run` on the synthetic corpus shows both readers; the engine ≥ today's path on each metric and exact on the five aligned files (SC-68). |
| FR-72 | Existing tests: document-forms, paystub-columns and layout-consumer pay stub tests pass unchanged, except those the test contract lists one by one with the requirement that changes them. | SC-64. |
| FR-73 | Docs: `docs/documents.md` gains "Pay stub rows from the printed columns" and "Several pay stubs in one file"; `docs/money.md` "Money in and paystubs" says text-PDF stubs take their amounts from the engine and guesses are notes; `docs/evals.md` "The two table readers" covers pay stubs and guess counts; `docs/ui.md` covers the Tables tab change; `docs/open-work.md` moves FR-40 to built and records what is left. | Doc diff present. |
| FR-74 | **Guesses are measured.** Every guess (FR-58, FR-59, FR-62, FR-75, and a split the user later changes) is recorded on the record by kind, and the evals report per kind how many guesses were made and how many were right (against the synthetic answers, or the donated corpus's confirmed answers), as counts in `summary.json`. | SC-68: the summary shows guess counts by kind; on the synthetic corpus every guess is right. |

## Invariants, privacy, security and data retention
- Nothing leaves the machine; no model or network call is added by the engine or the split rule.
- Money stays exact (`core/money.to_minor`); no float decides a role. Hours and rate stay printed text (`PayValue`).
- Every recorded amount is a printed cell. A guess chooses which printed cell a value comes from or which group a line
  is in; it never makes up a number, and every guess is written down (D6, FR-74).
- This period never takes a year-to-date amount by design: FR-57 (c) and FR-59 only ever pick the smaller column as this
  period, and the FR-22 guards still run after the copy.
- Splitting never changes a printed amount and never loses a line: every line of the file belongs to exactly one stub.
- Tests and evals use synthetic fixtures only. P:\Finances, %LOCALAPPDATA%\HomeManager and P:\EvalCorpus are never
  read (CLAUDE.md). Identifiers stay masked to their last four (document-forms, unchanged).

## Errors, recovery, duplicates, restart behavior
- Engine exception: FR-65. Roles undecided: a guess (FR-59). Unplaced or unclassified lines: notes, and unclassified rows
  are recorded with a guessed group (FR-56, FR-62).
- Review from this feature happens only when today's arithmetic checks fail after the best guesses (FR-63).
- Corrections with Edit details clear their notes and outlive reading again (document-forms FR-23, unchanged).
- The segment migration is one transaction, like 054; a failed upgrade follows docs/documents.md "Schema upgrades and
  recovering from a failed one".
- Extract again is idempotent (FR-69); duplicate pay stubs follow today's duplicate handling (FR-84).

## Nondeterministic outputs and how they are verified
- The engine and the split rule are deterministic, verified by exact expected values hand-written in the test contract,
  never computed by the code under test. Generator cases take their expected values from the generator's inputs.
- The model's classification and summary come from fixed stubs (`tests/model_server.py` `by_schema`); no test asserts
  live model output. The donated-corpus eval is run by the user; only `summary.json` is shared.

## Scenarios (expand into test-contract.md with design-tests before approval)
| ID | FR IDs | Initial state | User/API actions | Expected final DB/files/UI state |
|---|---|---|---|---|
| SC-50 | FR-50, FR-57, FR-60 | Text-PDF stub: `Description Hours Rate Current YTD`; Regular 80.00 31.25 2,500.00 32,500.00; Overtime; Federal, SS, Medicare; 401K; Gross and Net totals. Model stub classifies correctly but answers every amount swapped | Extract | Every line's current/ytd/hours/rate are the printed cells; checks hold; counts automatically |
| SC-51 | FR-52, FR-55, FR-61 | Same stub with two-line headings (`This`/`Period`, `Year to`/`Date`) | Extract | Same values; gross and net from the totals lines in each column |
| SC-52 | FR-53 | ADP-style stub: earnings block left, taxes and deductions block right, on shared lines | Extract | Two pay tables; every line recorded from its own block; checks hold |
| SC-53 | FR-54 | Stacked Earnings / Taxes / Deductions tables, the second and third with no heading, section titles `Statutory`, `Voluntary` | Extract | One pay line per printed row with its section; titles are no lines |
| SC-54 | FR-54, FR-66 | A label wrapped onto an indented second line | Extract; open the line's source | One pay line with the full label; provenance lists both lines |
| SC-55 | FR-50, FR-52, FR-57 | SC-50 with every heading removed and YTD printed before Current | Extract | Same values as SC-50 (roles from hours × rate, totals and ordering) |
| SC-56 | FR-56 | SC-50 plus a deposit table and a PTO table (`Vacation 40.00 8.00 32.00`) | Extract | No pay lines and no unplaced lines from them; deposit splits as today |
| SC-57 | FR-57 | Columns `Hours Rate Current YTD-Hours YTD`, and a variant with an `Employer` cost column | Extract | YTD hours and Employer are other; values as SC-50 |
| SC-58 | FR-51 | Lines `PRE-TAX 401K 184.98 2,404.74`, `SECTION 125 85.00 1,105.00` | Extract | Labels keep the digits; amounts 18498/240474 and 8500/110500 |
| SC-59 | FR-64 | Two-page stub: page 1 a pay table, page 2 prose with a model-stub line | Extract | Page 2 keeps the model's value with the "no pay table" note; page 1 from cells |
| SC-60 | FR-56, FR-62 | SC-50 plus a printed line outside every column, and a row under `Taxes` the model stub doesn't classify | Extract | One unplaced note; the unclassified row recorded as a tax with a note; no review reason from either |
| SC-61 | FR-58, FR-59 | (a) Headings say YTD over the smaller column; (b1) no headings, totals in both columns, and no row printing both columns; (b2) no headings and rows that disagree on which column is larger | Extract | (a) values by the numbers, a note naming the headings; (b1) the left column is this period, a note, no review reason; (b2) values by the guess, a note; review only from FR-22 for the row printed larger in this period |
| SC-62 | FR-63 | (a) SC-50 with Total taxes misprinted; (b) SC-50 with a net pay that doesn't follow from its lines | Extract | (a) note naming the total, counts automatically; (b) needs review with today's net-pay check reason |
| SC-63 | FR-65 | Engine made to raise | Extract | Today's path with the failure note |
| SC-64 | FR-67, FR-72 | Phase 1 generator, statement suites, document-forms, paystub-columns and layout-consumer suites | Run | All pass, except tests the contract lists as changed |
| SC-65 | FR-68 | A stub read at the previous version; a reviewed stub | Start; Extract again | The undecided one is re-read by the engine; the reviewed one unchanged |
| SC-66 | FR-69 | Any fixture, including a 3-stub file | Extract, then Extract again | Identical values, guesses, evidence, notes and segments; zero engine model calls |
| SC-67 | FR-70 | 100+ seeded generated stub files | Generator test | Every value exact; every split exact; every stub's checks hold |
| SC-68 | FR-71, FR-74 | Synthetic corpus with the five aligned pay stub files | `python -m evals.run` | Both readers shown; engine ≥ today's path; aligned files exact; guess counts by kind, all right |
| SC-69 | FR-57, FR-60 | SC-50 with a bonus printed only under YTD | Extract | Bonus current null (blank cell), ytd 500000; no note |
| SC-70 | FR-61, FR-75 | Stub with a summary box (`Gross Pay Taxes Deductions Net Pay` × `Current`/`YTD`) and no totals lines; a variant with the box's columns shuffled (headings kept); a variant with no box headings, taxes printed left of deductions | Extract | Gross, taxes, deductions and net, this period and YTD, from the box in all three; the headless variant notes its taxes/deductions guess |
| SC-71 | FR-76 | SC-50, and SC-61 (b) | Open the document page's Tables tab | The engine's table with column roles; clicking a value lights its cell; SC-61 (b) shows its guess note beside the table |
| SC-72 | FR-80 | (a) 3 stubs one per page; (b) 1 stub over 2 pages, page 2 repeating the heading; (c) 2 stubs on one page; (d) a scanned PDF of 2 stubs | Extract | (a) 3 stubs; (b) 1; (c) 2; (d) 2 |
| SC-73 | FR-81, FR-84 | A file of 26 bi-weekly stubs and 26 matching deposits in the ledger | Extract | 26 pay stub records, each linked to its own deposit; money in counts each once; the library shows the file with no single amount, dated by the earliest stub |
| SC-74 | FR-82 | SC-72 (a) | Extract; then Merge with next on stub 2 | 3 stubs, none in Review for the split, each with the split note; after the merge, 2 stubs, and the user's split wins on Extract again |
| SC-76 | FR-85 | A 3-stub file whose second stub prints VOID | Extract | 3 records; the void one carries the note and adds nothing to money in |
| SC-75 | FR-83 | A library at the previous schema with pay stub records | Upgrade; start; Extract again on a 3-stub file twice | Every existing record keeps its id and values as segment 0; the 3-stub file gives the same 3 records both times |

## Supersedes
- pdf-table-engine FR-40 "Current and YTD columns decided by earnings − taxes − deductions = net pay holding in each" →
  FR-57. Both columns pass that check on every correct stub, so it tells pay columns from other columns (FR-57 b) but not
  this period from year to date; that comes from A2's ordering (FR-57 c) and hours × rate (FR-57 a). "Hours and rates
  are never pay" is kept.
- pdf-table-engine non-goal "Splitting one PDF into several accounts" → for pay stubs, FR-80 – FR-84. Statements are
  still not split.
- document-forms / `anchor_paystub` column naming by headings (`paystub_columns`) → FR-57 – FR-61 on text-PDF engine
  pages; kept for vision tables and as today's path (D5).
- paystub-columns FR-31 "a text PDF with no rebuilt table is read like flat text" → only text-PDF pages with no pay
  table (FR-64); kept for photos and scans.
- The "native table row(s) were not accounted for" count note → FR-56 / FR-62 notes, on engine pages only.
- The Tables tab's tables for pay stub pages read by the engine (`viewer_context`) → FR-76.

## Out of scope / product decisions requiring approval
**Open decisions (defaults taken, D9)**
- **OD-1 Side-by-side blocks in scope.** *Default:* yes (FR-53). *Why:* ADP- and Paychex-style stubs print earnings and
  deductions side by side; without it most provider stubs miss.
- **OD-2 Text-only line between rows.** *Default:* at the table's left edge and followed by a row → section title; indented
  under a row → wrapped label. *Why:* the common print convention; the generator covers both.
- **OD-5 Model still classifies groups.** *Default:* yes, as today; section titles are used to guess the group only when
  the model gives none (FR-62). *Why:* group words vary too much ("Statutory", "Pre-tax", "Voluntary"); the arithmetic
  checks catch a wrong group.
- **OD-6 Redacted shape probe.** *Default:* extend `scripts/statement_diagnose.py` to pay stubs (line shapes and counts,
  never text) so you can check U1 on your own stubs. Optional; nothing depends on it.
- **OD-7 Failed arithmetic still goes to review** (D6's one exception, FR-63). *Default:* yes. *Why:* when the printed
  numbers don't add up after every guess, something was misread, and that stub is exactly what the guesses need to
  learn from. Alternative: count it automatically with a note.

Settled by the user on 2026-11-03: OD-3 and OD-4 of the first draft (guess instead of review, D6); R1 (summary box, in
scope, D7); R2 (several stubs, split, D8). R3 – R5 of the first draft are folded into FR-57 (negative rows don't vote;
employer-cost column is other; 4-decimal rates).

**Domain risks (accepted with their defaults, D9)**
- **R6 Two employers in one file** (a job change mid-year, both employers' stubs exported together). Consequence: each
  stub's year to date restarts, so the FR-22 "equal to year to date after the first period" guard may fire on the new
  job's first stub. *Default:* nothing new; each stub is read on its own lines and the guard's existing first-paycheck
  rule applies (it is printed twice, docs/money.md).
- **R7 A stub split at the wrong line** (the employer heading printed below the pay date on some layouts). Consequence:
  heading lines land on the previous stub, so a stub's employer is read from the wrong part. *Default:* the employer
  heading lines above a start belong to that start's stub (FR-80); the generator includes headings above and below the pay
  date; a wrong split is fixed with Split here and counted as a guess (FR-74).
- **R8 Corrected or voided stubs** printed in the same file (a stub marked VOID, or a reissued stub with the same pay
  date). Consequence: both count as money in. *Default:* a stub printing VOID is recorded but doesn't count, with a note;
  two stubs with the same employer and pay date follow duplicate handling.

**Out of scope:** reading photos and scans with the engine; tax forms; deposit, leave and filing details; splitting
statements; the Tables tab for other kinds and other `table_grid` consumers (FR-44); bills, receipts and investment
statements (FR-41 – FR-43); per-employer templates.
