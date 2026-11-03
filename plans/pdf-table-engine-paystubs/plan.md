# Table engine, phase 2: pay stubs read from their printed columns — implementation plan
Spec: specs/pdf-table-engine-paystubs/spec.md (with specs/pdf-table-engine-paystubs/test-contract.md)
Spec sha256: 113fef825d0078e8ea873c34c35c7f713b18e46ffda828e8342ddc91afca8117
Review-Risk: HIGH
Review-Risk-Rationale: It changes which printed number becomes each pay stub's gross, net, taxes and pay lines (money in
and tax figures), adds a schema migration to `income_records`, and turns one file into several income records.

<!-- Approval lives in approvals/pdf-table-engine-paystubs.json, bound to this file's hash. No Status line.
     Execution progress goes in plans/pdf-table-engine-paystubs/progress.yaml, never in this file. -->

**Scope.** FR-50 – FR-76, FR-80 – FR-85 and SC-50 – SC-76 of the approved spec. About 33 FRs, more than plan-feature's
guide of about 10. The spec was approved as one bundle (2026-11-03) and phase 1 set the precedent of one plan in
milestones, so this plan keeps one feature and splits it into milestones that are each verified on their own:
- **M1, the pay engine** (no visible change): SL-01, SL-02.
- **M2, Record uses it**: SL-03, SL-04, SL-05 (the Tables tab).
- **M3, several stubs in one file**: SL-06 (storage and migration), SL-07 (the split).
- **M4, proof and measurement**: SL-08 (generator), SL-09 (evals and docs).
Splitting M3 into its own feature was considered (alternatives, at the end) and is not needed: it has its own
milestone and slices.

Line numbers are from HEAD `4be2942`. Paths are under `src/home_manager/` unless they start with `tests/`, `evals/`,
`scripts/` or `docs/`.

## Verified repository integration points

| Area | Where | What this plan uses |
|---|---|---|
| Engine primitives | `documents/table_engine.py`: `PageView` (`:50`), `Token` (`:95`), `Column` (`:110`), `tokenize`/`tokenize_page` (`:286`, `:383`), `Line` (`:367`), `cluster` (`:342`), `choose_alignments` (`:419`), `zones_between` (`:449`), `label_support` (`:407`), `union`, `in_zone`, `fits`, `whole_inside`, `edge_of`, `span`; row finding is date-led throughout (`build_layout` `:460` returns None without date tokens; `scan` `:848`; `cuts` `:697`; `continuation` `:777`) | A new pay module reuses the primitives. `table_engine.read`, `build_layout`, `scan`, `cuts` and `continuation` are **not** changed, so statements can't move (FR-67) |
| Native projection | `documents/layout_context.py:18–39` `project_page`: a `table_grid` table's rows become lines `"<table>-row-<i>"` with text `"a \| b \| c"`; other lines keep their layout ids; `evidence_lines` (`:42`), `evidence_tables` (`:48`), `viewer_context` (`:63`) | The model cites these ids. Engine rows map to them through word ids (P3) |
| Today's pay stub path | `documents/extraction.py`: `read` (`:3775`), `tables = reported_tables(evidence)` (`:3780`), `printed_columns` (`:3797`), `anchor_paystub` (`:1272`) with `paystub_columns` (`:973`), `role_column` (`:1266`), `TOTAL_ROWS` (`:1262`), `cell_amount` (`:1236`), `cell_labels` (`:1247`); summary references (`:3798–3812`); unaccounted-row note (`:3838–3852`); `paystub_chunks`/`paystub_table_context` (`:1164–1205`); `paystub_lines` (`:3029`), `column_checks` (`:1064`), `this_period_guards` | Kept as today's path (D5) and the fallback (FR-64, FR-65); engine tables enter through the same table shape (P4) |
| Notes vs review | `publish` (`:3572`): `issues.extend(notes)` (`:3640`) makes every `read` note a review reason; `record_notes` (`:3575`, `:3642–3645`) are shown with the record, not reasons; statements store them in `details["notes"]` | Every note this feature adds is a record note (D6), carried on the reading as `record_notes` (P5) |
| Run and split | `run` (`:3684–3755`): classify once; `segments` only for receipts (`:3709–3710`); each part classified (`:3713–3720`); `record(... segment=ordinal, split=…)` (`:3731`); `save_segments` (`:4019`), `retire_segments` (`ledger.py:959`, receipts only); `record` adds `SPLIT_NOTE` to the issues (`:3881`); `split`/`confirm_split`/`set_split` (`:3954–4006`, joined to `receipts`) | Pay stubs get their own parts rule (P8) and reuse the segment plumbing |
| Income storage | `income_records` (`library/migrations/050_strict_tables.sql:408–426`, `blob_hash … UNIQUE` at `:411`); `Ledger._upsert` (`ledger.py:699–714`: segment only for `receipts`); `publish_income` (`:1452–1475`); `Ledger.record` (`:1838`) | Migration 077 adds `segment`; `_upsert` keys income by segment (P9) |
| One-per-file queries | `library/storage.py:558`, `:561`, `:576`, `:579`, `:588`, `:595`, `:615` (scalar subqueries on `income_records WHERE blob_hash=o.current_hash`); `library/managed_library.py:506`; `documents/donations.py:57` (`segment=0` only for receipts); `finance/ledger.py:1578` (EXISTS, fine) | Updated for several stubs (P9) |
| Per-record money | `finance/tools.py:457`, `:745`, `:757` (`STANDALONE_INCOME`, deposit links); `Reconciler.income`; `finance/family_routing.py:40` | Per record already; unchanged |
| Document page | `app/static/document_v2.js:224` `viewer.update({doc, run, result})`; `:366` `doc2Split` (`:848–890`, worded for receipts); `app/static/trace.js:257` `sourceViewer`, Tables tab `:274`, tables from `result.layout_context.tables` (`:363–400`) | Engine tables and guesses shown (P7); split panel worded for pay stubs (P8) |
| Segments API | `app/api.py:844–856` (`GET/PUT /api/documents/{id}/segments`, `POST …/confirm`) → `app/manager.py:1529–1541` | Reused unchanged |
| Evals | `evals/run.py:156` `table_readers`, `:187` `pipeline` (a split result returns only segment 0, `:237–238`); `evals/graders.py:172` `table_reader`, `:214` `grade`; `evals/synthetic.py:158` `paystub`, `:204` `aligned_statement`, `:74` `case(…, layout=…)`, `:333` `write_layout_pdf`; `evals/statement_layouts.py`; `evals/report.py` allowlist | A pay stub reader comparison, multi-stub answers, five aligned files (P10) |
| Test helpers | `tests/test_pdf.py` `make_pdf`; `tests/test_layout_consumers.py` (`pdf_store`, `capture`, `cite` pattern `:101–158`); `tests/model_server.py` `by_schema`; `tests/table_engine_generator.py` | Reused |
| Version | `extraction.py:47` `EXTRACTION_VERSION = "typed-extraction-v34-order-discounts"` | → `typed-extraction-v35-paystub-engine` (FR-68) |

## Architecture, contracts, data flow and decisions

### P1 Modules
- **`documents/pay_tables.py` (new): pay tables from a saved reading** (FR-50 – FR-56). Pure like the engine: no store,
  model, network, clock or randomness; imports `documents/table_engine` primitives and nothing from `finance/`.
- **`finance/paystub_tables.py` (new): what the columns mean** (FR-57 – FR-59, FR-75), the guesses (FR-74), and the
  adapter that hands Record its tables (P4). Imports `pay_tables`, `core/money`.
- **`documents/paystub_split.py` (new): where each stub starts** (FR-80, FR-85's VOID test). Pure, lines only.
- `documents/extraction.py`, `finance/ledger.py`, `library/storage.py`, `library/managed_library.py`,
  `documents/donations.py`, `app/static/trace.js`, `app/static/document_v2.js`: changed as below.
- `documents/table_engine.py`: unchanged except that helpers the new module needs and that start with no underscore
  are already importable; nothing is renamed or moved.

### P2 Contracts
```
PayColumn(id, align, edge, extent, zone, labels: [heading words top to bottom])
PayRow(page, table_id, row, line_ids, word_ids, label, amounts: {column_id: Token}, section: str|None)
PayTotal(page, line_id, word_ids, label, kind: "gross"|"earnings"|"taxes"|"deductions"|"net", values: {column_id: Token})
PayTable(id: "page-<p>-pay-<n>", pages, label_column: (left, right), columns: [PayColumn], rows: [PayRow],
         totals: [PayTotal], headings: [str], block: "left"|"right"|None, partner: table_id|None)
SummaryBox(page, line_ids, columns: [PayColumn], rows: [PayRow])      # two rows, ≥ 4 amount columns (FR-75)
Unplaced(page, line_id, text)
PayReading(tables, boxes, other_tables: [PayTable], unplaced, pages_without_tables: [int])

Roles(table_id, roles: {column_id: "current"|"ytd"|"hours"|"rate"|"other"}, decided_by: "numbers"|"headings"|"guess")
Guess(kind: "headings_overruled"|"columns_guessed"|"group_guessed"|"box_columns_guessed"|"split_changed",
      page, table_id|None, text)
PaystubTables(tables: [adapted tables, P4], roles: [Roles], box: {current: {...}, ytd: {...}}|None,
              notes: [str], guesses: [Guess], unplaced: [Unplaced], pages: set[int], viewer: [dict])
```
Serialization for determinism: `json.dumps(dataclasses.asdict(x), sort_keys=True)`. Money stays `Decimal` tokens until
`core/money.to_minor` in Record.

### P3 Pay rows, columns and tables (FR-50 – FR-56)
1. **Lines and tokens.** `PageView` + `tokenize_page` as the engine. A line is a **pay line** when its first run starts
   with text (the label) and it holds at least one amount token in a run not led by text, or after the label run
   (amounts printed 1.5 font sizes past the label are their own runs, the reader's rule). Integers and numbers joined to
   letters stay text (FR-02, FR-51): the engine's `tokenize` already does this.
2. **Blocks (FR-53).** On each line, the runs are split into label-and-amounts groups: a text run that starts after an
   amount run, with at least one amount run after it, starts a second group. A page whose pay lines carry a second group
   on at least two lines, whose second-group labels line up by left edge (within `ALIGN`), has two blocks split at the
   median left edge of those labels; every token right of the split belongs to the right block. Each block is read on
   its own below, with the same rules. Two blocks of one page are `partner`s.
3. **Columns (FR-52).** Within a block, amount tokens of pay lines are grouped by `choose_alignments` with the engine's
   tolerance and support rule (two rows, or one with a heading label). Zones by `zones_between`; the label column runs
   from the block's left to the first amount zone. Headings: text-only lines directly above the first row (up to two
   lines, as `heading_start`) whose runs sit over amount zones label those columns; two-line labels join top to bottom.
4. **Rows, sections, wrapped labels (FR-54).** Scanning down a block's lines: a pay line is a row unless it is a totals
   line; a text-only line at the label column's left edge (within `ALIGN`) followed by a pay line is a section title
   (kept as `section` on the rows below); a text-only line directly under a row and indented past the label column's
   left edge by more than `ALIGN` joins that row's label (and its line and words, FR-66). Other text-only lines end
   nothing.
5. **Totals (FR-55).** A pay line whose label matches the extended totals words (today's `TOTAL_LABEL` family: gross pay,
   total earnings, total gross, total taxes, total deductions, total pre-tax deductions, total employee deductions, net
   pay, net payment, each optionally lettered) is a `PayTotal` with one value per amount column, not a row. Its `kind`
   comes from the words (gross/total earnings → gross; taxes → taxes; deductions → deductions; net → net).
6. **Table extent.** A table is a run of rows sharing its column set; a line whose amounts don't fit the current zones
   but form a new column set on two or more rows starts a new table (stacked tables, STK). A section title doesn't end a
   table. A table also ends (review pass 1, M1, M2): after its net pay total; at a new heading line (text-only, two or more
   runs over amount zones, words other than the table's own headings), alone or under a title line, which starts a new
   table there (PS-OTHER's deposit and leave tables, whose columns line up with PS's); and at a stub start line
   (P8's pay date line), so stubs in one file never share a table. A next page whose rows fit the same columns at a page offset (the median difference of the rows' amount edges)
   continues it, with or without a repeated heading (the `continuation` idea, re-done for label-led rows).
7. **Summary box (FR-75, found here, read in P6).** Two consecutive pay lines, each with at least four amounts in the
   same columns, whose largest amount equals the sum of three others on both lines, form a `SummaryBox` instead of a
   table; its heading words (if printed) label its columns.
8. **Pay tables and other tables (FR-56).** Each table found is passed to P5's role pass. It is a pay table when P5 (a)
   or (b) finds a pay column, or its headings name this period or year to date (`COLUMN_WORDS`, `extraction.py:1045`), or
   it is the partner of a pay table; otherwise it is an other table (deposit, leave). Other tables' lines are accounted
   for and never pay lines.
9. **Unplaced (FR-56).** After all tables, any line on a page holding a pay table that has a label and an amount and is
   not a row, total, heading, box line or other-table line is `Unplaced(page, line_id, text)`.
10. **Pages without tables.** Native pages with a layout and no pay table go in `pages_without_tables` (FR-64).

### P4 The adapter: engine tables in today's table shape
`paystub_tables.adapt(reading, roles, evidence)` turns each pay table into the shape `anchor_paystub`,
`paystub_table_context` and the unaccounted-row check already read: `SimpleNamespace(id, page, source="pay_engine",
header_rows, rows, roles)`. Each row is `SimpleNamespace(id="<table>-row-<r>", line_id, line_ids, cells)`, cells
`SimpleNamespace(id="<table>-row-<r>-cell-<c>", line_id, quote, word_ids, source_line_ids)`: cell 0 is the label, then
one cell per amount column in column order (blank quote when empty). Totals are rows too (so `TOTAL_ROWS` finds them,
as today), flagged `total=True`.
- **Line ids.** A row's `line_id` is the evidence line id (what the model was shown, `evidence_lines`) that holds its
  label's first word: the projected `"<table>-row-<i>"` id when `table_grid` projected that word into a table, else the
  layout line id. `line_ids` lists every evidence line holding any of its words (wrapped rows: both). Built from
  `project_page`'s cells' `word_ids` and the layout lines' `word_ids`.
- **Roles.** `table.roles` maps cell column index to role. `paystub_columns(table)` and `role_column(table, …)` return
  from `table.roles` when present, else today's heading rule. Nothing else in `anchor_paystub` changes shape.
- **Evidence (FR-66).** A copied value's reference is `native_values.reference(cell)`-shaped:
  `{cell_id, line_id, quote, source: "pdf_text", source_line_ids, word_ids}`, so provenance and the document page light
  the words as today (`finance/provenance.py:78`); when the row is exactly one `table_grid` row, `cell_id` is that
  native cell's id instead.

### P5 Roles and guesses (FR-57 – FR-59)
Per pay table (both blocks of a page are decided separately; the box is P6). With amount columns `C`:
- **(a)** For each unordered pair {a, b} of distinct columns and a third column p: every row printing all three has
  a × b == p under document-forms FR-21's rounding (reuse `document_checks.product`, the rule `hours_rate` uses), and at
  least one row does (review pass 1, M3: a product is symmetric, so pairs are unordered). Which of a, b is the rate:
  the column shared by two matching pairs (Hours × Rate = Current and YTD hours × Rate = YTD); else the one printing more
  decimal places on its rows (rates print 4, hours 2: PS's 46.8750); else heading words; else the right one (Hours is
  printed before Rate). With one matching pair, p is this period, the other column hours. With two pairs sharing the
  rate, both product columns are pay columns, (c) tells them apart, and the hours column of this period's pair is hours,
  the other other. Anything else → (a) decides nothing.
- **(b)** A column is a pay column when at least one `PayTotal` of kind gross/earnings/taxes/deductions has a value in
  it and each such value equals the sum of that column's rows since the previous total or section title (exact
  `Decimal`, signs as printed; negative values counted with their sign).
- **(c)** Of exactly two pay columns X, Y: voting rows print both, neither negative. X is this period when X ≤ Y in
  magnitude on every voting row and X < Y on one. All equal → headings, else the left. No voting row → FR-59.
- **(d)** Headings break ties; with no (a) or (b) result, columns headed this period/YTD (`COLUMN_WORDS`) take those
  roles and Hours/Rate headings take theirs (also the hours-without-rate case).
- **(e)** One pay column with no heading → this period.
- **FR-58.** When (a)–(c) decided and a heading names the other role, the decision stands and a `Guess`
  (`headings_overruled`) is added with the note "Page N: the column headed "YTD" was taken as this period and the one
  headed "Current" as year to date, because the printed amounts say so."
- **FR-59.** Two pay columns, undecided: the one smaller on more voting rows is this period; a tie → the left. `Guess`
  `columns_guessed`, note "Page N: the left column was taken as this period; the printed amounts didn't tell the two
  columns apart." (or "… the column smaller on more lines …").
- Columns left without a role are other. A pay table whose columns all end other is an other table (P3.8).

### P6 Summary box (FR-75)
For each box: gross = the largest amount on each row (the same column on both rows); the remaining three columns whose
values sum to gross on both rows are taxes, deductions and net; net = the largest of the three on the this-period row;
heading words, when printed, name gross/taxes/deductions/net instead and must agree with the sum (if they don't, the
sum wins and a `Guess` `box_columns_guessed` notes it). Taxes vs deductions with no heading words → left is taxes,
`Guess` `box_columns_guessed`. Rows: this period is the row smaller in gross (A2); equal → heading words (`Current`,
`YTD`) of the row labels, else the upper row. Extra columns are other.

### P7 Record (FR-60 – FR-66, FR-68, FR-69)
The engine runs **once per file**, in `run` (`extraction.py:3684`), after classification says `paystub` and the evidence
has pages: `pay = paystub_tables.read(evidence)` inside `try` (on any exception: `log_failure(log, "pay table read",
exc)`, `pay = PAY_FAILED`, a sentinel that makes each part add FR-65's note verbatim and take today's path). `run`
passes it to `read` as a new **keyword-only** argument `pay=None`; `read` keeps its positional signature and calls only
module-level functions for this (review pass 1, m6: `tests/test_layout_consumers.py:482–492` calls `read` with a fake
`self`). With `pay=None` (that test, other kinds), `read` behaves as today. In `read`, for pay stubs with `pay`:
1. `pay.for_lines(part_line_ids)` keeps only the rows, totals, boxes, unplaced lines and notes whose lines lie in the
   part (review pass 1, M2); today's `table_grid` tables are filtered the same way (rows whose `line_id` is in the part),
   so a split file's fallback can't see another stub's Net Pay row.
1a. **Layout-review note (review pass 1, B1; pass 2, MAJOR-1).** For pay stubs, `read` adds a page's
   `pdf_layout_review` note (`:3780`, messages start "Page N") only for pages holding the part's lines (`line_page`,
   `:1998`), so in a split file one stub's page never sends another stub to review. The note is also left out for a page
   that has an engine pay table in the **file-wide** reading (before `for_lines`) when that page's
   `layout.issues == ["unresolved_columns"]`, the rule
   `finance/pdf_import.py:408`, `:779` already uses (`table_grid` raises it exactly when it can't build a headerless
   table). Any other layout issue stays a review note. Statements are untouched.
2. On engine pages (`PaystubTables.pages`), the adapted tables replace `tables` entries of the same pages; other pages
   keep today's tables. **FR-64's flat checks (review pass 1, M6):** `printed_columns` becomes the set of line ids on
   pages with neither an engine pay table nor a `table_grid` table (empty set = off); `paystub_lines` passes it to
   `column_checks`, which judges only pay lines and summary fields citing those lines (an engine-copied value is never
   judged by it). `paystub_chunks`,
   `paystub_table_context` and the summary's `table_summary` get the merged `tables` list, so the model is shown the
   engine's cells and classifies rows (`PayRowClasses`), as today with `table_grid` tables.
3. `anchor_paystub` runs as today on the merged list. Changes, each only for `source == "pay_engine"` tables:
   `by_line` maps every id in `row.line_ids`; `totals_row` also finds `taxes` and `deductions` totals (FR-61), and a
   gross/net `PayTotal` wins over the model's citation; after classification, an engine row with an amount that no
   model line took is added as a pay line with a guessed group (FR-62): the section title's group by words (earn →
   earnings; tax/statutory → tax; pre-tax/before tax → pre_tax; post-tax/deduction/voluntary → post_tax; employer →
   employer_paid), else the group under which `paystub_lines`' earnings = gross and net checks hold (tried in that
   order: earnings, tax, pre_tax, post_tax), else the group of the nearest classified row above; category `other`;
   `Guess` `group_guessed` with the note "Page N: the printed pay line "…" wasn't classified, so it was recorded as … ".
   The "native table row(s) were not accounted for" note is not added for `pay_engine` tables.
   **Evidence wiring (review pass 1, m1):** the word-level reference at `:1328` and `read`'s `summary_references`
   (`:3806`) are built for `source in ("pdf_text", "pay_engine")`; and for a `pay_engine` row, the pay line's `evidence`
   gains one cite per line in `row.line_ids` not already cited, so `locator(row.evidence)` (`:1761`) lists a wrapped
   label's second line (SC-54 step 2).
4. **Summary box.** When no gross/net totals row exists and a box was read, gross/net/taxes/deductions (this period) and
   gross/net (YTD) come from it (FR-61, after totals rows, before the model). When both exist and disagree, the one equal
   to the pay lines' sum is kept and a record note says which.
5. **Section total mismatch (FR-63).** A `PayTotal` of kind earnings/gross/taxes/deductions whose value differs from its
   rows' sum in a this-period or YTD column → record note "Page N: the printed total … doesn't match the lines above it,
   which add up to …". No review reason.
6. **Unplaced (FR-56)** → record note 'Page N: a printed line wasn\'t placed in any column, so it wasn\'t recorded: "…"'.
7. **FR-64.** Each page in `pages_without_tables` → record note verbatim.
8. `paystub_lines` (`:3029`) takes `printed_columns` as P7.2's set of line ids (lines whose `line_page` is None count as
   table-less) and passes it to `column_checks` (`:1064`, called at `:3094`) as a new parameter; `column_checks` skips
   any pay line or summary field citing no line in the set. An empty set means it doesn't run (review pass 2, MINOR-1).
   Guards and arithmetic checks unchanged (FR-63's review only from them).
9. **Record notes.** `read` returns `reading["record_notes"]` (the notes above) and `reading["guesses"]`; `publish`
   adds them to `record_notes` and stores `details["notes"]` and `details["guesses"]` on income records (as statements
   do, P19 of statement-accounts), so they survive reloading. Nothing new goes into `notes`/`issues`.
10. **Viewer data (FR-76).** The run result gains, at its top level (file-wide, so every stub of a split file has its
    tables; review pass 1, m4), `pay_tables`: per adapted table `{id, page, roles: {column index:
    role}, header_rows, rows: [{id, line_id, total, cells: [{id, quote, word_ids, line_id}]}], guesses: [text]}` and
    the box in the same shape.
11. `EXTRACTION_VERSION = "typed-extraction-v35-paystub-engine"`.

### P8 Several stubs in one file (FR-80 – FR-82, FR-85)
- **Rule (`documents/paystub_split.py`, `stub_parts(lines) -> [(first, last)]`).** A start is a line holding a pay date
  label (`pay date`, `check date`, `payment date`, `pay period`, `period ending`) and a date token
  (`table_engine.tokenize` dates). Net pay lines: `TOTAL_ROWS["net_pay"]` with an amount. Walk the starts in order: a
  start opens a new stub **only after the open stub has printed its net pay line** (review pass 1, M4: a stub prints both
  `Pay date` and `Pay period`, and a stub's later page repeats its heading; both are then continuations, which covers A4
  and the spec's same-pay-date rule). Then: a part without a net pay line joins the part before it (the first joins the
  next); **after** the joins, each stub's first line moves up over its employer heading lines: the lines directly above
  its first start, on the same page (review pass 1, m5: never the previous page's footer), after the previous stub's last
  net pay line, up to 4 lines, holding no amount. One part → `[(0, len(lines))]`.
- **Run.** In `run` (`:3709`), `classification.document_type == "paystub"` → `parts = self.pay_parts(run, parse,
  lines, split_notes)`: the user's saved split wins (`saved_segments(source="user")`, `user_ranges`, as receipts), else
  `stub_parts(lines)`. The per-part classification loop (`:3713–3720`) runs for pay stubs too, comparing to `paystub`;
  `requested_kinds` passes `None` kinds for pay stubs. Each part is read with `self.read(…, lines[first:last], …)`;
  the engine is run on the whole evidence once and each part keeps the tables whose rows lie in its lines (`read` gets
  the part's line ids and filters `PaystubTables` by them).
- **No review (FR-82).** `record(... split=…)` adds `PAY_SPLIT_NOTE = "Split from a file holding several pay stubs"` to
  the record notes (not the issues) for pay stubs; receipts keep `SPLIT_NOTE` as today.
- **Split API.** `split()` joins `income_records` too (`LEFT JOIN income_records i ON i.blob_hash=s.blob_hash AND
  i.segment=s.ordinal`), returning `kind: "paystub"`, `income_record_id`, employer, pay date, net pay display.
  `confirm_split` also removes `PAY_SPLIT_NOTE` from `income_records.details_json["notes"]` (no status change: the note
  was never a reason). `set_split` unchanged (it stores line ids). `save_segments` unchanged.
- **VOID (FR-85; contract G4 settled: narrow rule).** A part with a line whose whole text is `VOID` (case-insensitive,
  allowing surrounding `*` or `-`) is published with the record note "This pay stub is printed VOID, so it doesn't count.", then set to
  `review_status='rejected'`, `review_source='automatic'` by a `Ledger.mark_void(income_id)` update (review pass 1, m3:
  `_upsert` gives `review_source='automatic'` only to verified records, `ledger.py:707`; a user-decided record is left
  alone). A rejected record counts nowhere
  (`STANDALONE_INCOME`, reconciliation), and `retire_segments`' restore logic treats it as automatic.
- **Duplicates (FR-84, FR-85 second sentence; user, 2026-11-03: "follow duplicate handling").** Pay stubs follow the
  app's duplicate rule for transactions (docs/money.md "Money rules": one identity per record, and real entries that
  merely look alike are never dropped). A pay stub's identity is employer (`payer_merchant_id`), pay date, net pay and
  currency. When a stub being published has the identity of another non-rejected pay stub (in the same file or another
  one), the one recorded first (lowest `income_records.id`; within one run, the lower segment) keeps counting and the
  other is the duplicate: it is still recorded, with its lines, and `Ledger.mark_duplicate(income_id, original_id)` sets
  `review_status='rejected'`, `review_source='automatic'` (as `mark_void`) with the record note "This pay stub repeats
  the one paid by <employer> on <pay date> (<net pay>), so it doesn't count." A user-decided record is never marked. A
  reissued stub whose net pay differs is not a duplicate and counts (an off-cycle bonus stub on the same pay date has a
  different net pay too); it gets the record note "Another pay stub from <employer> has the same pay date." so you can
  reject one. Extract again gives the same result (ids are stable by `(blob_hash, segment)`), and when the original is
  rejected or deleted, the next Extract again of the duplicate lets it count.
- **Guess (FR-74, review pass 1, m2).** `set_split` deletes the old rows (`:4001`); before that it reads whether they
  had source `model` and differed, and if so writes the user's rows with `extraction_run_id` set to the replaced model
  run's id (the column exists and is NULL for user rows today). When there were no model rows (the rule found one stub)
  and the user chose more than one start, it counts as a changed split too: the rows get the latest succeeded run's id,
  which the query at `:3988` already finds (it gains `e.id`) (review pass 2, MINOR-2). The next run, finding user rows with an
  `extraction_run_id`, adds one `split_changed` guess to each part's `details.guesses`. No schema change. Tested in SC-74, plus a one-part file the user splits in two.

### P9 Storage (FR-83, FR-84)
- **Migration `library/migrations/077_income_segments.sql`**, one transaction, the table-rebuild pattern of 054: new
  `income_records` with `segment INTEGER NOT NULL DEFAULT 0 CHECK (segment BETWEEN 0 AND 199)` and
  `UNIQUE (blob_hash, segment)` replacing the column's `UNIQUE`; copy every column with segment 0; recreate every index
  and trigger of the old table (read from `sqlite_master` at write time and listed in the migration); foreign keys from
  `income_lines`, `transaction_income_links` and others keep their ids. `PRAGMA foreign_key_check` passes after.
- `Ledger._upsert`: `segment` for `receipts` **and** `income_records`. `publish_income` passes `source["segment"]`.
- `Ledger.retire_segments(blob_hash, keep, …)` also retires `income_records` segments not kept (same rules, its own note
  "The latest reading of this file no longer finds this pay stub; check how the file was split.").
- `library/storage.py`: the income subqueries become: amount `CASE WHEN count(*)=1 THEN max(net_pay_minor) END` (and the
  currency likewise) over non-rejected records; `pay_date`, `document_date` → `min(pay_date)`; merchant and
  `reconciliation_status` take `ORDER BY segment LIMIT 1` / the receipt-style worst state; `ledger_status` takes the
  receipt-style priority order. `managed_library.py:506` → `ORDER BY i.segment LIMIT 1`. `donations.py:57` → `segment=0`
  for `income_record` too (split files are already refused at `:86`).
- Filing (`filing_identity`) already reads the first segment's result (`run` keeps `outcomes[0]` as `result`).

### P10 Evals (FR-71, FR-74) and the generator (FR-70)
- **`evals/paystub_layouts.py` (new):** `make(seed, index, **choices) -> Layout(pages, answers: [stub answers], choices)`,
  drawing every FR-70 variation; answers come from inputs only. `tests/paystub_engine_generator.py` builds PDFs with
  `make_pdf` (as phase 1). Rule: every drawn stub prints either totals or headings naming the columns (so it has a pay
  table), and its this-period amounts are ≤ YTD unless a negative row is drawn.
- **Synthetic corpus:** five fixed layouts from the generator appended after the 48 documents, drawn from
  `random.Random(SEED + 2)`, source `pdf`, tag `aligned`; the three-stub file's case carries `stubs: [answers…]`
  (`evals/corpus.py` loads it; one-stub cases unchanged).
- **Pipeline:** a split pay stub result (`result["segments"]`) is graded per segment against `stubs`, in order; a count
  mismatch is a split miss.
- **Pay readers comparison** (model-free, like `table_readers`): for native-PDF pay stubs, "legacy" = `table_grid` tables
  + `paystub_columns`; "engine" = `paystub_tables.read`. For each answer line (matched by label, case- and
  space-insensitive), the reader's current/YTD cell values; per reader: `values`, `exact`, `left_out` (answer values the
  reader couldn't place), `checks_held` (stubs whose reader values sum to the answers' gross and
  net), `unplaced` (engine only; legacy null), `split_right` (files whose parts equal the answers' stubs; legacy: one part
  always). "Stubs sent to review" (review pass 1, m9): for the engine, the pipeline's own records' `review_status`; for the
  legacy reader, which has no run of its own, `left_out > 0` stands in for it, and docs/evals.md says so. In
  `summary.json`: `pay_readers: {legacy, engine}` counts; `guesses: {kind: {made, right}}` from the engine's
  records (a guess is right when the values it chose equal the answers). `report.allowed_keys` gains these keys.
- Contract G2 settled: those key names; guess kinds as P2.

### P11 Tables tab (FR-76)
- `document_v2.js`: after an extraction run loads, call `state.viewer.setEngineTables(run.result.pay_tables || [])`.
- `trace.js` `sourceViewer`: `setEngineTables(tables)` stores them; in the tables render, pages that have engine tables
  show those instead of `layout_context.tables` for that page; caption "Page N · Table k · Read from the printed columns";
  each header cell gets its role label (This period, Year to date, Hours, Rate, Other) from `roles`; total rows get the
  existing muted row style; each cell with `word_ids` is the same find-cell button as native cells (highlight words,
  tell line); the table's `guesses` render below it as a `muted small` list. No new dependency, no inline style, CSP
  unchanged. Contract G1 settled: the extraction run's `result.pay_tables`.
- Before changing these pages the implementer loads the `ui-ux-pro-max` skill (CLAUDE.md) and follows docs/ui.md
  "Screen rules" and `design-system/home-manager/MASTER.md`.
- **Pay stub notes on the page (review pass 1, M5).** `doc2Forms` shows `record.details.notes` only for bills and
  statements (`document_v2.js:577`); the condition gains income records, so guess, FR-64, FR-65, split and VOID notes
  show under the pay stub's fields with the same list.
- Split panel (`doc2Split`): when `publication.segments` are pay stubs (`split.segments[i].kind == "paystub"`), heading
  "This file holds N pay stubs", chips show employer · pay date · net pay, and no "waits in To check" warning (FR-82).

### Decisions taken in this plan (contract gaps)
- G1: P11 (run result `pay_tables`). G2: P10 key names. G3: a merged segment is read like any part (both stubs' lines
  in one record); nothing special is asserted, and its checks decide its status. G4: P8 narrow VOID rule. G5: note texts
  as written in P5 – P8.
- Totals coverage: rows since the previous total or section title (as the spec, P5 b).
- No new dependency.

## Error handling, idempotency and recovery
- Pay engine or role exception: FR-65 note, today's path, logged by class and run id only. A failure in
  `paystub_split.stub_parts` is caught the same way: the file is read as one stub with a record note "Where each pay
  stub starts couldn't be read, so the file was read as one."
- Deterministic and pure: Extract again on an unchanged reading gives identical records, notes, guesses and segments
  (FR-69). Record ids are stable by `(blob_hash, segment)`.
- A failed run publishes nothing (the existing `run` structure publishes only after every part is read, `:3729–3742`);
  Extract again gives the full set (contract's retry variant).
- Migration: one transaction; on failure the existing recovery (docs/documents.md "Schema upgrades and recovering from
  a failed one") restores the old schema.
- Reviewed records are never rewritten (`_upsert`'s user-decided rule, unchanged, now per segment).

## Privacy/security and migration impact
- No model or network call added by the engine, the roles or the split rule; C-net in every new test module.
- Money in integer minor units via `core/money.to_minor`; `Decimal` until then; positions are floats, money never.
- Migration 077 on `income_records` (rebuild with `segment`); every existing row becomes segment 0, ids unchanged.
- `summary.json` stays counts; no text, amount or date. Identifiers still masked (unchanged code paths).

## Vertical slices
| ID | FR/SC covered | Dependencies | Files/changes | Verification command / evidence |
|---|---|---|---|---|
| SL-01 | FR-50 – FR-55 and FR-56's unplaced lines (engine level: rows, labels, columns, headings, blocks, sections, wrapped labels, totals, extent incl. P3.6's new-heading and net-pay ends, continuation, box detection); SC-51/52/53/54/58 engine steps, SC-56's table split (two extra tables found) | none | `documents/pay_tables.py` (P3); `tests/paystub_engine_fixtures.py` (every contract fixture and hand-written expected value); `tests/test_paystub_engine.py` (P-checks and engine steps) | `python -m pytest tests/test_paystub_engine.py -k "pcheck or rows or blocks or sections or totals or other_tables or unplaced or continuation" -q`; `python -m pytest tests/test_table_engine.py -q` (unchanged) |
| SL-02 | FR-56 (pay vs other tables, P3.8), FR-57 – FR-59, FR-75 (roles, guesses, box), FR-74 (guess records); SC-50, SC-55, SC-56, SC-57, SC-61, SC-70 engine steps | SL-01 | `finance/paystub_tables.py` (P5, P6, `read`, `Guess`); `tests/test_paystub_engine.py` role and box tests | `python -m pytest tests/test_paystub_engine.py -q` |
| SL-03 | FR-60, FR-61, FR-64 (incl. the flat checks on table-less pages), FR-65, FR-66, FR-68, FR-69, FR-72 (part); SC-50, SC-51, SC-52, SC-53, SC-54 (steps 1–3), SC-55, SC-57, SC-58, SC-59, SC-63, SC-65, SC-66 (single stubs), SC-69; plus a test that PS-NH's reading carries `unresolved_columns` (P-check) and its record has no layout-review issue (B1), and one that a table-less page's swapped flat line is still nulled by `column_checks` (M6) | SL-02 | `finance/paystub_tables.py` (`adapt`, `for_lines`, P4); `documents/extraction.py` (engine once in `run`, `read(…, *, pay=None)`, P7.1–P7.4, P7.7–P7.9, P7.11, evidence wiring; `paystub_columns`/`role_column` roles; `by_line` line_ids; record notes plumbing; `EXTRACTION_VERSION`); `finance/ledger.py` (`publish_income` stores `details.notes`/`guesses`); `tests/test_paystub_engine_record.py` | `python -m pytest tests/test_paystub_engine_record.py -k "sc50 or sc51 or sc52 or sc53 or sc54 or sc55 or sc57 or sc58 or sc59 or sc63 or sc65 or sc66 or sc69" -q`; `python -m pytest tests/test_paystub_forms.py tests/test_layout_consumers.py tests/test_paycheck.py tests/test_vision_tables.py tests/test_extraction.py tests/test_provenance.py -q` |
| SL-04 | FR-56 (notes), FR-58, FR-59, FR-62, FR-63, FR-74 (record side), FR-75 (Record), FR-72; SC-56, SC-60, SC-61, SC-62, SC-64 (changed test), SC-70 | SL-03 | `documents/extraction.py` (P7.3 unclassified rows, P7.4 box, P7.5, P7.6, guesses on the record); `tests/test_paystub_engine_record.py`; `tests/test_layout_consumers.py::test_missing_native_rows_are_reviewed_and_blank_current_is_not_ytd` updated per the contract's SC-64 entry (and only that test) | `python -m pytest tests/test_paystub_engine_record.py -q`; `python -m pytest tests/test_layout_consumers.py tests/test_paystub_forms.py tests/test_table_engine_record.py tests/test_statement_forms.py -q` |
| SL-05 | FR-76, FR-66 (page lights words); SC-71, SC-54 step 4 | SL-04 | `documents/extraction.py` (P7.10 `pay_tables` in the run result); `app/static/trace.js`, `app/static/document_v2.js` (P11 Tables tab, and pay stub notes under the fields), `app/static/style.css` if a role label needs a class from the design system; `tests/test_paystub_engine_record.py` (`pay_tables` shape); `tests/test_paystub_engine_browser.py` (SC-71, SC-54 step 4, and SC-61 b1's guess note under the pay stub's fields); `docs/ui.md` (Tables tab) | `python -m pytest tests/test_paystub_engine_record.py -k pay_tables -q`; `RUN_BROWSER_TESTS=1 python -m pytest tests/test_paystub_engine_browser.py tests/test_document_v2_browser.py -q` |
| SL-06 | FR-83, FR-84 (storage, library); SC-75, SC-73 step 4 (library row) | SL-03 | `library/migrations/077_income_segments.sql`; `finance/ledger.py` (`_upsert`, `publish_income`, `retire_segments`); `library/storage.py`, `library/managed_library.py`, `documents/donations.py` (P9); `tests/test_paystub_split.py` (`sc75`, library-row unit test with two segments published directly) | `python -m pytest tests/test_paystub_split.py -k "sc75 or library" -q`; `python -m pytest tests/test_migrations.py tests/test_library.py tests/test_managed_library.py tests/test_paycheck.py tests/test_reconcile_tools.py tests/test_donations.py -q` |
| SL-07 | FR-80, FR-81, FR-82, FR-84, FR-85, FR-74 (split guess); SC-72, SC-73, SC-74, SC-76, SC-66 (three-stub file), the contract's retry/duplicate/restart variants | SL-04, SL-06 | `documents/paystub_split.py`; `documents/extraction.py` (P8: `pay_parts`, per-part engine tables, `PAY_SPLIT_NOTE`, `split`/`confirm_split` for income, VOID, duplicates); `finance/ledger.py` (`mark_void`, `mark_duplicate`); `app/static/document_v2.js` (split panel wording, P11); `tests/test_paystub_split.py` (with a two-stub file whose page 2 holds a headerless table: both records C-auto, review pass 2 MAJOR-1; and the same file with page 2 also carrying `overlapping_text`: stub 1 C-auto, stub 2 `needs_review`, review pass 3 MINOR-A; the one-part split guess, MINOR-2; and duplicates: a 3-stub file whose stub 3 repeats stub 1's employer, pay date and net pay → stub 3 recorded, rejected automatically with the duplicate note, money in counts stub 1 once; the same with stub 3's net pay changed → both count, stub 3 carries the same-pay-date note; the same stub dropped as a second file → the second file's record is the duplicate); `tests/test_paystub_engine_browser.py` (SC-74 step 2) | `python -m pytest tests/test_paystub_split.py -q`; `python -m pytest tests/test_receipt_segments.py tests/test_extraction.py tests/test_paycheck.py -q` (receipt splitting unchanged); `RUN_BROWSER_TESTS=1 python -m pytest tests/test_paystub_engine_browser.py -q` |
| SL-08 | FR-70; SC-67 | SL-07 | `evals/paystub_layouts.py`; `tests/paystub_engine_generator.py`; `tests/test_paystub_engine_generator.py` (≥ 100 files through the real reader and Record with stubs drawn from inputs; every FR-70 variation ≥ 3 times, plus stubs printing both a pay date and a pay period line (review pass 1, M4); byte-identical PDFs on regeneration) | `python -m pytest tests/test_paystub_engine_generator.py -q` (0 misses; seed, index and choices printed on failure) |
| SL-09 | FR-71, FR-73, FR-74 (evals); SC-68; docs | SL-08 | `evals/synthetic.py`, `evals/corpus.py`, `evals/run.py`, `evals/graders.py`, `evals/report.py` (P10); `tests/test_evals.py`; `docs/documents.md` ("Pay stub rows from the printed columns", "Several pay stubs in one file"), `docs/money.md` "Money in and paystubs", `docs/evals.md` "The two table readers", `evals/README.md` (48 → 53), `docs/open-work.md` (FR-40 built; the old pay stub path's removal after the user's corpus run, D5; FR-41 – FR-44); `scripts/statement_diagnose.py` (pay stub section, R-A / OD-6) and its test | `python -m pytest tests/test_evals.py -q`; `python -m evals.synthetic <tmp>` writes 53 cases; `python -m pytest tests/test_paystub_engine_generator.py -k probe -q` (the probe runs on a generated pay stub PDF and prints no fixture word, as `tests/test_table_engine_generator.py:106–112` does for statements) |

## Final verification
After SL-09, once:
```
python -m pytest -q
RUN_BROWSER_TESTS=1 python -m pytest tests/test_paystub_engine_browser.py tests/test_table_engine_browser.py \
  tests/test_document_v2_browser.py tests/test_statement_accounts_browser.py -q
```
Every failure outside the contract's "Tests this spec changes" list is a defect to fix, not an expected value to edit.

## Requirements & scenarios coverage matrix
| Requirement | Slice | Scenarios |
|---|---|---|
| FR-50 – FR-52 | SL-01, SL-03 | SC-50, SC-51, SC-55, SC-58 |
| FR-53 | SL-01, SL-03 | SC-52 |
| FR-54 | SL-01, SL-03 | SC-53, SC-54 |
| FR-55 | SL-01, SL-03 | SC-51 |
| FR-56 | SL-01, SL-04 | SC-56, SC-60 |
| FR-57 | SL-02, SL-03 | SC-50, SC-55, SC-57, SC-69 |
| FR-58, FR-59 | SL-02, SL-04 | SC-61 |
| FR-60, FR-61 | SL-03, SL-04 | SC-50, SC-51, SC-62, SC-69, SC-70 |
| FR-62 | SL-04 | SC-60, SC-64 |
| FR-63 | SL-04 | SC-62 |
| FR-64, FR-65 | SL-03 | SC-59, SC-63 |
| FR-66 | SL-03, SL-05 | SC-54 |
| FR-67 | SL-01 (no engine change), final | SC-64 |
| FR-68, FR-69 | SL-03, SL-07 | SC-65, SC-66 |
| FR-70 | SL-08 | SC-67 |
| FR-71 | SL-09 | SC-68 |
| FR-72 | SL-03, SL-04, final | SC-64 |
| FR-73 | SL-05, SL-09 | doc diff |
| FR-74 | SL-02, SL-04, SL-07, SL-09 | SC-61, SC-68, SC-70 |
| FR-75 | SL-01, SL-02, SL-04 | SC-70 |
| FR-76 | SL-05 | SC-71 |
| FR-80 – FR-82 | SL-07 | SC-72, SC-74 |
| FR-83 | SL-06 | SC-75 |
| FR-84 | SL-06, SL-07 | SC-73 |
| FR-85 | SL-07 | SC-76 |

## Test environments, data, stubs for nondeterministic components, final-state oracle
- **Isolation:** `tmp_path` libraries; C-net autouse in every new module; never `P:\Finances`,
  `%LOCALAPPDATA%\HomeManager` or `P:\EvalCorpus`.
- **Levels:** engine and role tests are integration tests on real readings of synthetic PDFs with no store
  (`tests/test_paystub_engine.py`, independent). Record tests go through `ReceiptService` and `ExtractionService`
  (`tests/test_paystub_engine_record.py`, `tests/test_paystub_split.py`); SC-74 and SC-75 are single tests with ordered
  checkpoints. API steps use `create_app`/`TestClient`. Browser tests opt-in.
- **Stubs:** `local_model` by schema as the contract's doubles table; for split files each schema's list holds one answer
  per part in file order. Engine fault: `monkeypatch` of `paystub_tables.read`.
- **Oracle:** expected values are the contract's hand-written literals in `tests/paystub_engine_fixtures.py` and the
  generator's inputs; final state read back through `Ledger.record("income_record", id)`, `run["result"]["normalized"]`,
  `GET /api/documents/{id}`, `GET /api/documents/{id}/segments`, `provenance_for` and SQL snapshots of
  `income_records`, `income_lines`, `transaction_income_links` and `document_segments`.

## Risks, unresolved decisions, alternatives
- **R-A Real stubs unlike the fixtures (U1).** The eval comparison (P10) on the user's corpus is the gate for removing
  today's path (D5). OD-6's probe: `scripts/statement_diagnose.py` gains a pay stub section in SL-09 printing only
  shapes and counts (column count, roles, rows, totals, box found, blocks), never text, with a test that greps its output
  for every fixture word.
- **R-B Block detection on prose-like lines.** A label run after an amount (an address line beside a pay line) could
  start a false second block; bounded by needing two lines whose second labels line up, and covered by the generator's
  layouts with address blocks beside the table.
- **R-C Line-id mapping.** Engine rows must map to the ids the model saw (P4); a miss would leave rows unclassified and
  guessed. SC-50 – SC-53 assert classified groups match the stub's, which catches it.
- **R-D Migration on a large library.** A table rebuild of `income_records`; income tables are small (one row per
  stub). Tested with foreign keys from `income_lines` and links.
- **R-E Twenty-six parts mean twenty-six classification calls.** Same cost model as split receipts; accepted.
- **Alternative rejected: extending `table_engine.read` with a pay mode.** It would touch statement row finding and
  risk FR-67; the new module reuses its primitives instead.
- **Alternative considered: a separate feature for M3 (splitting).** Not taken: the spec bundle is approved as one, and
  M3 is two slices with their own checks.
- **Settled by the user (2026-11-03):** reissued and repeated stubs follow duplicate handling (P8 "Duplicates").
