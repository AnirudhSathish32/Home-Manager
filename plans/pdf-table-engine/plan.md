# One table engine for text PDFs, phase 1 (bank and card statements) — implementation plan
Spec: specs/pdf-table-engine/spec.md (with specs/pdf-table-engine/test-contract.md)
Spec sha256: 31d06e09ac86d98038369be6c963d04d07bc2030512fd68437fd6f6bcf200e3a
Review-Risk: HIGH
Review-Risk-Rationale: It replaces how every text-PDF statement's dates, amounts and signs reach the ledger (Record and
PDF import), so a defect would put wrong money into the household's books, and it changes a public API's preview rows.

<!-- Approval lives in approvals/pdf-table-engine.json, bound to this file's hash. No Status line.
     Execution progress goes in plans/pdf-table-engine/progress.yaml, never in this file. -->

**Scope.** Phase 1 only: FR-01 – FR-34 and SC-01 – SC-25 (OD-5). FR-40 – FR-44 are not built here. The user asked for
phase 1 as one feature (2026-10-27). It has about 30 FRs, more than plan-feature's guide of about 10, so the plan
splits it into milestones that can each be verified and reviewed on their own:
- **M1, the engine** (no app change visible): SL-01 – SL-03.
- **M2, proof at scale**: SL-04 (the layout generator and the redacted probe).
- **M3, the app uses it**: SL-05 (Record), SL-06 (PDF import and the index).
- **M4, measurement**: SL-07 (evals and docs).

Line numbers are from HEAD `3ee7d56`. All paths are under `src/home_manager/` unless they start with `tests/`, `evals/`,
`scripts/` or `docs/`.

## Verified repository integration points

| Area | Where | What this plan uses |
|---|---|---|
| Saved layout | `documents/pdf_layout.py:28–124`: `PDFCharacter` (bbox, origin, font_size), `PDFWord` (id, text, character_indexes, bbox), `PDFLayoutLine` (id, word_ids, text), `PDFTable`/`PDFCell`, `PDFLayout` (page_to_preview, words, lines, tables, issues) | The engine's only input (FR-01). No reader change |
| Visual rows | `finance/pdf_import.py:123–163` `PageView` (baseline grouping at ¼ font size, `runs` at 1.5 font sizes, `texts`, `lines`) | Moved to the engine module and re-exported from `pdf_import` under the same name (`scripts/statement_diagnose.py:24` imports it) |
| PDF import analyzer | `pdf_import.py:565–651` `analyze` → `Analysis` (`:102`), `ImportRow` (`:66`), `ImportTable` (`:88`), `ImportIssue` (`:58`); old row reading `structure` (`:374`), `visual_row` (`:261`), `read_date` (`:500`), `read_amount` (`:538`) | `analyze` keeps its signature and return types, built from the engine. The old body is kept as `analyze_legacy` for the eval comparison (D4) |
| Index | `pdf_import.py:29` `ANALYZER_VERSION = 2`; `index_row` (`:673`), `pending` (`:714`), `backfill` (`:721`); started by `app/manager.py:1154–1156`; `GET /api/finance/import-candidates` returns `indexing` (`app/api.py:1974–1981`) | Bump to 3 (FR-26). Nothing else changes |
| Import preview/import | `finance/ledger.py:1538–1579` `pdf_state` (calls `analyze` twice, `:1553`, `:1559`); `:1581–1630` `preview_pdf_import` (rows, `issues` as `asdict(ImportIssue)`, `counts`, `required`); `:1632–` `import_pdf_transactions` (refuses on `required`, `blocked`) | `pdf_state` passes the OD-2 lookup and catches an engine exception (FR-24). The response shape is unchanged; unplaced lines arrive as issues with code `unplaced_line` and a new `counts.unplaced` |
| Import dialog | `app/static/library.js:176` renders `import-issues` from the response's issues generically | No UI code change: unplaced lines show in the existing issue list |
| Record, rows | `documents/extraction.py:3187–3198` (`statement_rows.rebuild` with the model's period, `REBUILD_FAILED` on exception, `:1283`); `normalize` `:1675`, statement branch `:1757–1820` (rebuilt rows, model rows as notes `:1781–1791`, `rebuild.issues/notes/dropped` `:1808–1811`, arithmetic check `:1814–1822`) | Swap `statement_rows.rebuild` for `statement_tables.read`; same `Rebuild` shape plus anchors and period |
| Record, pages | `extraction.py:3370–3416`: `statement_rows.rebuilt_pages` (`:3375`), fallback (`:3376–3379`), model rows on rebuilt pages not anchored (`:3398–3405`), missed-row check only on other pages (`:3410–3416`, `missed_rows` `:2997–3011`) | Swap for `statement_tables.engine_pages`; add FR-19's note for embedded_text pages without an engine table |
| Reuse key | `extraction.py:45` `EXTRACTION_VERSION`, used only as the extraction-run reuse key (`:2835–2840`) | Bump to `typed-extraction-v32-table-engine`, so Extract again never reuses an old-path run. It triggers nothing by itself (FR-25) |
| Old Record rebuild | `finance/statement_rows.py` (`Rebuild` `:25`, `rebuild` `:199`, `rebuilt_pages` `:143`, `read_period` `:152`, `placed` `:161`, `date_order` `:179`, `duplicates` `:252`; it imports `pdf_import` at module top, `:13`) | Kept, importing `analyze_legacy`, as the "old reader" for FR-34 and `scripts/statement_diagnose.py`. `Rebuild`, `read_period`, `placed`, `duplicates` and `PERIOD_SLACK` move to a new `finance/statement_dates.py` that imports nothing from `pdf_import`; `statement_rows` re-exports them, so its callers and tests keep their imports and no import cycle forms (`pdf_import` → `statement_tables` → `statement_dates`) |
| Statement storage | `statements` (`library/migrations/050_strict_tables.sql:1149–1171`): `extraction_run_id`, `opening_balance_minor`, `closing_balance_minor`, `statement_balance_minor`, `summary_json`; `extraction_runs.parse_run_id` (`:306–321`); `accounts.account_last_four` (`:23`) | OD-2's lookup reads these; no schema change |
| Statement fields on the document page | `ledger.py:183–184` (Opening/Closing balance fields), `app/static/receipt.js:38` | FR-07's printed values show through the existing fields |
| Provenance | `finance/provenance.py` reads a transaction's evidence `locator` (`{rebuilt, page, table_id, row, line_ids, word_ids, cell_ids, quotes}`, `statement_rows.py:239–243`) | Same locator shape (FR-22) |
| Evals | `evals/run.py:154` `pipeline` (reads each case in a throwaway library), `:229` `run`; `evals/report.py:167` `summary`, `:228–278` allowlist and `check_summary`; `evals/synthetic.py:102–149` statements, `:219–238` the document list, `:280` `write_pdf` (one flowed text line per row), `:301–` `create` (case id from source and lines) | Add the reader comparison and four aligned-column statements (FR-34) |
| Test helpers | `tests/test_pdf.py:17` `make_pdf`; `tests/statement_account_fixtures.py` (`page`, `words_footer`, `flag_items`, `COLUMNS4/5`, stubs); `tests/pdf_import_fixtures.py` (`k_pages`, `x_pages`, `table_items`, `footer`); `tests/model_server.py` `by_schema`; `tests/test_evals.py:202–262` (`run` with `local_model`) | Reused by the new fixtures |
| Diagnose script | `scripts/statement_diagnose.py` (prints shapes and counts only, never text) | Extended for OD-6 |

## Architecture, contracts, data flow and decisions

### P1 Modules
- **`documents/table_engine.py` (new): the generic engine** (FR-01 – FR-09 minus anything statement-specific). Input: a
  `PDFResult`. Output: `EngineReading` (below). Pure: no store, model, network, clock or randomness. It imports nothing
  from `finance/`, so FR-44 can later give it to every consumer.
- **`finance/statement_tables.py` (new): bank and card statements** (FR-09's schedule rule, FR-10 – FR-17, FR-14's
  period, OD-1, OD-2). Input: an `EngineReading` plus the statement type, currency, choices and an optional
  `prior_order` callable. Output: `StatementReading`, and two adapters: `as_rebuild()` (the `statement_rows.Rebuild`
  shape Record already consumes) and `as_analysis()` (the `pdf_import.Analysis` shape).
- **`finance/pdf_import.py`**: `analyze` becomes a thin adapter over `statement_tables`; the old function body is
  renamed `analyze_legacy` with its helpers untouched.
- **`finance/statement_rows.py`**: imports `analyze_legacy` and re-exports the helpers moved to
  `finance/statement_dates.py`. It is the old reader (D4).
- **`finance/statement_dates.py` (new):** `Rebuild`, `read_period`, `placed`, `duplicates`, `PERIOD_SLACK`, moved from
  `statement_rows` unchanged except that `Rebuild` gains `opening_minor`, `closing_minor` and `period`, each defaulting
  to `None` (the legacy reader leaves them unset). `statement_tables` imports only this, `documents/table_engine` and `core/money`.

### P2 Contracts
```
Token(kind: "date"|"amount"|"integer"|"text", word_ids, box, text, value)
    date value: (day_or_first, month_or_second, year|None, form: "slash"|"iso"|"month_name")
    amount value: (decimal: Decimal|None, marker: "minus"|"plus"|"credit"|"debit"|None, code|None); None = unreadable.
    The engine never converts to minor units: it has no currency. statement_tables calls core/money.to_minor only on
    tokens in columns whose role is balance, in, out or signed, after roles are decided (P7), and on anchors and totals
    with the statement's currency.
Column(id, kind: "date"|"amount"|"text", align: "right"|"left"|"centre", edge, extent: (left, right),
       zone: (left, right), labels: [heading words over it, top to bottom])
EngineRow(page, table_id, row, line_ids, word_ids, cell_ids, dates: [Token] by date column, description,
          amounts: {column_id: Token}, carried_from: (page,row)|None, section: str|None, reject: str|None)
EngineTable(id: "page-<p>-table-<n>", pages, columns, rows, kind: "transactions"|"balance"|"schedule"|"other",
            continues: table_id|None, headings, anchors: [Anchor], totals: [Total])
Anchor(page, line_id, kind: "opening"|"closing", value: Decimal, inside_table: bool)
Total(page, line_id, column_id, value: Decimal)
Unplaced(page, line_id, text, reason: "no_column"|"pending")
EngineReading(tables, unplaced, summary_anchors: [Anchor], period_lines: [(page, line_id, Token, Token)],
              other_native_tables: [PDFTable ids], pages_without_tables: [int])
StatementReading(rows: [{posted_date, transaction_date, description, currency, amount_minor, locator}],
                 issues: [str], notes: [str], dropped: int, pages: set[int],
                 opening_minor|None, closing_minor|None, period: (start, end)|None,
                 order: "MM/DD/YYYY"|"DD/MM/YYYY"|None, decided: {order, year, signs},
                 roles: {table_id: {column_id: role}})
```
Serialization for FR-01's byte-identity check: `json.dumps(dataclasses.asdict(x), sort_keys=True)`.

Record's locator per row is today's: `{rebuilt: true, page, table_id, row, balance_minor, line_ids, word_ids, cell_ids,
quotes}` (`statement_rows.py:239–243`; `balance_minor` is read by `ledger.py:1857` and the document page's balance column,
`receipt.js:307`). `balance_minor` is the row's printed balance, when the balance column holds one. `cell_ids` are the
native reader cells (if the page has a native table) that hold any of the row's words, in reading order; else `[]`.
`line_ids` lists every line the row cites (wrapped rows: all of them).

### P3 Tokens (FR-02; SC-21)
- Words come from `PageView` visual rows; a **run** is the reader's run (gap ≤ 1.5 font sizes).
- Within a run, multi-word tokens are matched first, left to right: month-name dates (`01 Oct 2026`, `Oct 1`,
  `Oct 01, 2026`), an amount with a code before or after (`USD 1,234.56`, `1,234.56 USD`), an amount followed by
  `CR`/`DR`. Then single words.
- **Date:** `d{1,2}[/.-]d{1,2}([/.-]d{2}|d{4})?` with one separator kind, ISO `dddd-dd-dd`, `d{1,2}-Mon-d{2,4}`, and
  month names. A numeric date that is no real date in either order (`13/45`) is text.
- **Amount:** digit-led with `,` thousands and `.` decimals, optional leading currency symbol, sign as leading `-`/`+`,
  trailing `-`, parentheses, or `CR`/`DR`, held as an exact `Decimal`. A digit-led word with separators that isn't such
  a number (`1.2.3`, `1.234,56`) is an **unreadable amount**: it takes part in rows. If it sits in a column whose role
  is money (balance, in, out, signed), the row is rejected with today's "can't be read" reason (OD-3, contract G18).
  A value with more precision than the currency allows is rejected the same way, but only in a money column: FX's rate
  column (`1.0850`) is `other` and is never parsed as money (R3, SC-23).
- **Integer** (plain digits, no separator or marker): an amount only when it fits an amount column's zone (P4);
  otherwise text. This keeps check numbers (`1201`) in the description (contract G8) and keeps account-import-pdf
  7-e's `12345` a second amount in the Withdrawals column (FR-16).
- **Joined to text** (statement-accounts FR-30): an amount or integer inside a run whose first word sits in the
  description zone is text, except that it stays the amount when its whole box lies inside one amount zone and it is the
  row's only amount-shaped word centred in an amount zone (statement-accounts FR-30 as amended, fixture T).

### P4 Columns by alignment (FR-04; OD-4)
- **Order of work:** columns are built first from amount tokens that are not in a text-led run (no integers, no joined
  tokens); zones follow; integers and joined tokens are then resolved against the zones (P3). So a check-number column
  of integers (`1201`, `1202`) never becomes an amount column.
- Per page, gather those amount tokens from lines that hold a date token. Group them by right edge, then by left
  edge, then by centre: a group is the tokens within **0.75 font sizes** of the group's median (OD-4; the value is a
  module constant `ALIGN = 0.75`, tuned only against SL-04's generator, with any change recorded in `docs/documents.md`).
  Each token goes to the alignment whose group has the most support; a group needs **≥ 2 rows** (FR-04). A heading
  label printed over the group, aligned with it on the same edge within the tolerance, counts as one row's support, so
  a one-row table with a heading forms (contract ONE, SC-06 b).
- **A page with fewer than 2 supporting rows** (a one-row last page): its lines are matched against the previous
  table's columns, with the page offset taken from the date column's left edge (P4 continuation). A plan-level test
  covers a one-row continuation page (`test_table_engine.py -k one_row_continuation`).
- The date column is the group of date tokens at the rows' left (left-edge alignment). A second date-token group to its
  right is the second date column (R5).
- **Zones.** Columns are ordered left to right. A zone runs from the midpoint between a column's extent and the previous
  column's extent to the midpoint with the next. The text zone between the last date column and the first amount
  column is the description. The outermost amount zone extends past its column's extent by at most half the median gap
  between adjacent amount columns (so UP's `35.00` at x 545 is outside every zone).
- A token **fits** a zone when its centre is in the zone and its box crosses the zone's edges by no more than 20% of its
  width (today's `place` rule). A token that does not fit is **straddling**.
- **Headings** (labels only, never required). A text-only line is a **heading line** when it has at least two runs
  (P3's run gap) that each fall in a different zone, and at least one of those zones is an amount column's. The one or
  two heading lines directly above a table's first row are its heading: each run labels the column whose zone holds its
  centre, and two lines stack into one label per column (`Deposits/` + `Additions`). A heading line later on the page
  or on a continuation page is a repeated heading and is ignored (FR-07). A heading line is never a section title and
  never a table end, even when it contains `balance` (WF's `Ending daily balance`).
- **A single run** of text on its own line, starting in the date or description zone (CS's `Payments and Credits`,
  PD's `Pending transactions`), is a **section title** (P6), even directly above a table's first row. A plan-level test
  asserts CS's p1 and p2 carry the title `Payments and Credits` and q1–q4 `Purchases` (`test_table_engine.py -k
  section_titles`).
- Continuation pages (FR-06): a page's columns match the previous table's when every amount column's edge differs by
  the same offset within the tolerance; the offset is the median edge difference (K3's page 3, +6 pt).

### P5 Rows (FR-03, FR-05, FR-16; OD-1)
Scanning each table's lines top to bottom:
1. A line with a date token in the date column and ≥ 1 amount token fitting an amount zone starts a row.
2. A text-only line whose words lie in the description zone joins the description of the row above, which then cites
   both lines (wrapped rows, WR).
3. A line with a date but no amount: if the line directly below has an amount and no date, the two are one row citing
   both; else it is a row rejected with a reason (today's "The amount is printed against the description…" when FR-30's
   joined amount is the cause, else "No amount is printed."). Never dropped (D6; WR-split, T-edge).
4. A line with no date and an amount fitting an amount zone is its own row and takes the date of the row above in the
   same table, across continuation pages, with a record note (OD-1). A table's first row with no date has no row above:
   it is rejected with "No date is printed." (contract G6).
5. Rejections keep today's texts (FR-16): both debit and credit; more than one amount in a column (a second amount or
   integer fitting an already-filled zone, including an unaligned one); text that is not an amount in an amount column;
   not a real date; can't be read; currency other than the statement's; a blank description.
6. A line with a date token and an amount token that is none of the above (its amount straddles, or sits outside every
   zone) is an **unplaced line** (FR-08). This replaces today's "doesn't fit a column" rejection (contract: statement-
   accounts x2, account-import-pdf 7-d).
7. **Descriptions above their amounts** (FR-05's third sentence; contract G5 gives no criterion, so this plan sets
   one): within a table, when every row's date line has a text-only line directly above it and no row's date line has
   one directly below, each such line joins the row below it instead of the row above. Otherwise rule 2 applies. A
   plan-level test covers it (`test_table_engine.py -k description_above`), with fixture WR-above: WR with every
   description moved to its own line directly above its date line.

### P6 Table extent and line classes (FR-06, FR-07, FR-09)
- A table is a run of lines sharing its column set. It ends at the page end; at a line with a different column set that
  starts a run of ≥ 2 rows; or at a text-only line that names a balance or totals section (`balance`, `total`,
  `summary`) directly above a run. A heading line does not end a table (it is a repeated heading, ignored), so the
  existing test with `LATE ROW` changes as the contract lists.
- **Balance line** (inside a table): its words contain one of opening, beginning, previous, starting, closing, ending,
  new together with balance, and its only amount sits in the column decided to be the balance (P7) → an anchor, not a
  row. A line with those words whose amount sits in an amount column is a transaction (existing
  `test_rows_a_balance_row_under_the_heading_does_not_cut_the_table`: `Beginning Balance carried -3.00` stays −300).
  Since the balance column is known only after roles, anchors inside a table are classed in `statement_tables`; the
  engine marks them as candidates. **Total line**: words contain total or subtotal, and its amount fits an amount zone → a check value.
- **Summary anchors** outside every table, on any page of the reading: a line whose words name an opening or closing
  balance as above and that holds exactly one amount (here "alone" is the rule, as there are no columns) (with or without a date: `Beginning balance on 10/1 1,000.00`).
  The first opening and the last closing anchor in reading order are the statement's (FR-07 as settled in D6). They are
  never unplaced.
- **Section titles**: a text-only line between rows (or between the heading and the first row) labels the rows below it
  until the next title. Used for FR-12's signs and R4 (any title containing `pending`).
  A section title needs a row below it on the same page. It carries on to the same table's continuation rows on the
  next page until another title (a Purchases list that runs onto page 2 keeps its section). Text below a page's last
  row is the footer and is ignored (FR-07), so a footer never becomes a title (a footer with "pending" or "fees"
  changes nothing).
- **Kinds:** a table whose rows have a description on at least half its rows and an amount column other than the
  balance is `transactions`; a table of dates and one amount column with no descriptions is `balance` (BL's daily
  lines, statement-accounts D); `schedule` is set by `statement_tables` (P8). Native reader tables the engine's tables
  don't cover are listed as `other` (account-import-pdf SC-07's summary and fee tables), as `structure` does today.
- **Unplaced** (FR-08): computed last, over every line of a table's pages holding a date token and an amount token
  (an amount, not an integer, and not joined to text) that is not a row, a rejected row, an anchor, a total or an
  other-table row.

### P7 Statement roles and signs (FR-10 – FR-13; R1, R3)
For each transactions table (with its continuations), with amount columns C1…Ck:
1. **Enumerate** assignments in a fixed order: each column is one of balance, signed, in, out, other, with ≤ 1 balance
   and either one signed column or ≥ 1 of in/out (not both kinds). k is capped at 6; above that the table's roles are
   undecided.
2. **Chain** (FR-10). For each candidate assignment, the table's balance-line candidates (P6) are re-classed first:
   a candidate whose amount is in that assignment's balance column is an anchor, else it is a row. Then, over rows with
   a printed balance, consecutive links where the balance equals the previous balance
   plus the signed amounts of the rows between, in integer minor units, starting from the opening anchor when the
   table has one, else the first balance. For a signed column both conventions (minus is out, minus is in) are tried.
   An assignment is **chain-decided** when every link holds and there are ≥ 2 links (FR-13, R1).
3. **Summary** (FR-11): opening + in − out = closing (bank), previous − credits + charges = new (card), using the
   anchors; plus every printed column total. **Summary-decided** when it holds and the anchors are printed.
4. **Signs for a signed column** are read per row, in FR-12's order: the row's own marker (minus, parentheses,
   trailing minus, `DR` → out; `CR` → in), else its section title (payments, credits, refunds, returns → in;
   purchases, charges, fees, interest, cash advances → out), else the type default (card: positive is out; bank:
   negative is out). With a chain, the two whole-column conventions are tried too. Each such reading is a candidate
   alongside the whole-column assignments, so the summary check in step 3 sees CS's per-row signs.
5. **Choose, by tiers**: (a) chain-decided candidates; else (b) summary-decided candidates; else (b′) the candidates
   with the most holding chain links, when that is at least 2 and more than any candidate in another role set (a
   statement with a misprint: its first break is then reported under FR-15, G11); else (c) label-decided ones
   (withdrawal/debit/paid out → out; deposit/credit/paid in/addition → in; balance → balance; amount → signed);
   else (d) the type default for a single signed column. Within the first non-empty tier, if every candidate gives every
   row the same signed amount, that is the result. Otherwise keep those with the fewest `other` columns, then those
   whose labels agree; if the survivors still differ on any row's signed amount, the roles are **undecided**: the rows
   are recorded with tier (c) or (d)'s reading when one exists, and the statement needs review (FR-15), else they are
   not recorded and listed. Enumeration order breaks no tie that changes money.
6. In tiers (c) and (d), the result is checked against the summary when printed; a mismatch is FR-15.
7. A Balance column is never an amount; `other` columns are never amounts (R3).
8. **FR-13 reason** when signs were decided only by labels or the type default and fewer than two links or no summary:
   `Page {p}: the signs of these rows come from the column headings or the statement type, because there are too few
   rows and no printed summary to check them.`

### P8 Dates, period and schedules (FR-09, FR-14; OD-2)
- **Period** (FR-14 as settled in D6): the line outside every table nearest the top of page 1 (then later pages) holding
  exactly two numeric or month-name dates with four-digit years and no amount, the first not after the second. Its
  own order: a day over 12 in it; else the rows' day-over-12 order; else the period isn't used. Record falls back to
  the model's summary period only when none is found; PDF import has no fallback.
- **Order**: over every numeric slash/dot/dash date token of the transactions tables: a first part over 12 → DD/MM, a
  second part over 12 → MM/DD (both → undecided); else the orders under which every row date falls within the period
  ± 7 days and each table's rows are non-decreasing; exactly one → it; else **OD-2**: `prior_order()`; else undecided:
  no row with an ambiguous date is recorded, and one issue per page: `Page {p} rows: the date order (month/day or
  day/month) can't be told from the printed dates.` (today's text). Month-name and ISO dates are never ambiguous.
- **Year**: `statement_rows.placed` (four-digit as printed; else from the period; two-digit checked against it).
- **Schedule** (FR-09 as settled in D6): a table, or a run of ≥ 2 consecutive rows starting at a page's top or after a
  text-only line and continuing a table, whose every row is dated outside period ± 7 days, is `schedule`: its rows are
  other-table rows. With no period, nothing is a schedule (account-import-pdf 7-a unchanged; 7-a′ new).
- **OD-2 `prior_order(last_four, document_id)`**, implemented in `statement_tables.prior_order(db, last_four,
  document_id)`: the statements of accounts with that `account_last_four`, from other documents, whose extraction
  run's parse run is a PDF reading, newest `period_end` first. For each, it re-runs the engine's order decision on that
  reading **without** the OD-2 step (so it never recurses) and returns the first decided order; None if none decides.
  At most 10 statements are tried. No schema change; the
  decision is deterministic, so it equals the order last decided. Record passes the summary's last four; PDF import
  passes the chosen account's.

### P9 Outcome, notes and issues (FR-15, FR-17, FR-20, OD-1)
- Chain break: `Page {p} row {r}: the balance {printed} doesn't follow from the row above` for the first failing link
  only, per table. Rows are numbered 1-based among that page's transaction rows of the table.
- Unplaced: `Page {p}: a printed line wasn't placed in any column, so it wasn't recorded: "{line text}"`. Pending
  (R4): `Page {p}: a pending row isn't recorded until it posts: "{line text}"`. Both are review issues (FR-20).
- Two chains that don't join (FR-17), one issue for the PDF: `This PDF may hold more than one account: the table on
  page {a} and the table on page {b} don't continue each other's balances. Both tables' rows were recorded.`
- OD-1 note (a record note, not an issue): `Page {p} row {r}: no date is printed; it takes {date} from the row above`,
  `{date}` printed as `MM/DD/YYYY`, `DD/MM/YYYY` or ISO, by the decided order (contract G15).
- FR-07 note when the model's summary value differs from the printed anchor: `The printed {opening|closing} balance
  {printed} was recorded; the reading gave {model}.`
- `dropped` counts rejected rows, unplaced lines and undated rows, so normalize's arithmetic check is skipped, as today,
  when anything printed wasn't recorded.

### P10 Record (FR-07, FR-18 – FR-20, FR-22 – FR-25, FR-27)
- `extraction.py:3370–3379`: `statement_tables.engine_pages(evidence)` replaces `rebuilt_pages`: the pages holding a
  transactions table's rows. Same fallback on exception (FR-24).
- For each `embedded_text` page with a layout and no engine table, `statement_tables.read` puts FR-19's note verbatim
  in `StatementReading.notes` → `Rebuild.notes`, which `normalize` moves into `record_notes` (`extraction.py:1810`).
  It is never appended to `read`'s `notes` list, which becomes review issues (`extraction.py:3182`, `:3230`).
  Scanned pages get no note (non-goal).
- `extraction.py:3187–3195`: `statement_tables.read(evidence, statement_type=…, currency=…, fallback_period=<model
  period>, prior_order=<closure over self.store and header.account_reference's last four>)` replaces
  `statement_rows.rebuild`, returning the `Rebuild` shape with `opening_minor`, `closing_minor`.
- `normalize` (`:1757–1822`): before the arithmetic check, when `rebuild.opening_minor`/`closing_minor` is set, it
  becomes `opening_balance_minor`/`closing_balance_minor` (bank) or `previous_balance_minor`/`statement_balance_minor`
  (card), and the same keys in `record["summary"]` (built earlier at `extraction.py:1759`, read by the card and bank
  summary traces, `finance/document_traces.py:216–225`), with P9's note when the model's value differed (FR-07 as
  settled in D6). The field's evidence still cites the model's line; the printed anchor's line is added to the record's
  notes text.
- A reading saved without layout: unchanged (`NO_LAYOUT_NOTE`, statement-accounts SC-18 b).
- The model's rows on engine pages decide nothing; unmatched ones stay record notes (`:1781–1791`, unchanged).

### P11 PDF import (FR-21, FR-24, FR-26)
- `pdf_import.analyze(result, *, tables, year, date_format, sign, account_type, currency, prior_order=None)` runs the
  engine and `statement_tables` with statement type card for `credit_card`, bank for `checking`/`savings`, and none
  otherwise. Choices apply only where the engine couldn't decide: `year` when no period is found and a date has no
  four-digit year; `date_format` when the order is undecided; `sign` for a signed column decided only by the type
  default or with no default (account-import-pdf FR-07: the user's sign choice replaces the default, never a chain or
  summary decision). `required` lists what is still open, as today.
- Each engine table is shown as one `ImportTable` per page, as today: the first page's piece has kind
  `transactions`, each later page's piece has kind `continuation`, id `page-<p>-table-<n>`, and `linked_to` the first
  piece (`pdf_import.py:436` today). Rows map to `ImportRow` one to one with key `"<piece id>:<row>"`, so keys are
  unique across pages; `continued_from` and the label `continued from page N` as today; flags from `page_flags` as
  today. SC-08 step 2's test also asserts the keys are unique. Rejected rows keep `rejected`. Unplaced lines and pending
  rows become `ImportIssue(page, None, "unplaced_line", <P9 text>)`, and `counts["unplaced"]` is added. The identity
  becomes imported + duplicates + rejected + unplaced + left out = lines seen (contract G13, plan decision).
- `ledger.pdf_state` (`:1553`, `:1559`): passes `prior_order` (a closure over `db` and the account's last four) and
  catches a non-`PDFImportError` exception from `analyze`, logging it with `log_failure` and raising
  `ValueError("This PDF's rows couldn't be read from its printed columns. Read it again, or use Record.")` → the API's
  4xx refusal, nothing written (FR-24; contract G12).
- `ANALYZER_VERSION = 3` (FR-26). Index rows of version 2 are re-indexed by the existing backfill.

### P12 Evals (FR-34) and the shared layout generator (FR-33)
- **`evals/statement_layouts.py` (new):** a seeded generator of aligned-column text-PDF statements: `make(seed, index)`
  → `Layout(pages: [items as make_pdf takes them], answers: {rows, period, opening, closing, kind}, choices: dict)`.
  It writes no PDF itself. `tests/table_engine_generator.py` (the contract's file) is a thin module that turns each
  layout into a PDF with `tests/test_pdf.py` `make_pdf`, as the contract says; the evals corpus writes the same items
  with a small positioned writer in `evals/synthetic.py` (evals can't import tests). Expected rows come only from the
  generator's inputs. Rules: every case prints a chain or a summary; year-less dates come with a printed period; dates
  all ≤ 12 come with a period that decides the order. It varies every dimension FR-33 names.
- **Synthetic corpus:** `evals/synthetic.py` appends four fixed layouts from the generator (WF-style, DD/MM/YYYY,
  wrapped, sectioned card), source `pdf`, after the existing documents, drawn from `random.Random(SEED + 1)` so the
  existing cases' random draws, ids and answers are unchanged. `create` writes them with the generator's writer.
- **Reader comparison:** in `evals/run.py`'s `pipeline`, after the reading and for native-PDF bank and card statements,
  run `statement_rows.rebuild` (old; given the answers' period, as the model would supply it) and
  `statement_tables.read` (engine; its own period) on the saved reading. `evals/graders.py` gains
  `table_reader(expected, rows, record)` → `{rows, exact, reconciled, dropped, unplaced}` (exact = date, amount and sign equal;
  reconciled = the reader's rows take the answers' opening to the answers' closing; `dropped` = `Rebuild.dropped` for
  both readers (rejected rows, undated rows and, for the engine, unplaced lines), plus the engine's `unplaced` count
  shown on its own). Lower is better for `dropped`, so the comparison is engine ≥ old on `exact` and `reconciled` and
  engine ≤ old on `dropped`. The four new corpus cases carry a new tag `aligned`, added to `TAGS` in `evals/corpus.py:26`
  (imported by `evals/report.py`).
  Results go in `results.jsonl`; `report.summary` adds per candidate `table_readers: {legacy: {...}, engine: {...}}`
  with `documents`, `rows`, `exact`, `reconciled`, `dropped`, `unplaced` (counts only); `allowed_keys` gains
  `table_readers`, `legacy`, `engine`, `exact`, `reconciled`, `dropped`, `unplaced`. `report.markdown` shows both side by side.

### P13 OD-6 probe
`scripts/statement_diagnose.py` gains an engine section: per page, column edges and zones as a percentage of the page
width, each column's kind and role, counts of rows, rejected rows, anchors, totals, other-table rows and unplaced
lines, whether a period was found, the decided order, whether roles were chain-, summary- or label-decided, and the
first chain-break row number. It prints no text and no amounts. The user runs it on their own PDFs; the agent never
does (CLAUDE.md).

### Decisions taken in this plan (spec left them open)
- G5 description-above lines: built with P5.7's criterion. G6 dateless first row: rejected (P5.4). G8 check numbers: integers are
  text outside amount zones (P3). G9 a failed column total: makes the summary check fail, so it is FR-15 review (P7.3).
  G10 same-layout combined accounts: one table and a chain-break issue; FR-17 applies only to different column sets.
  G11 no assignment holds everywhere: the chain-decided rule fails, the summary or labels decide, and the first break is
  reported. G12, G13: P11. G15 – G17: P9 and P4. G18: P3.
- No new dependency.

## Error handling, idempotency and recovery
- Engine or statement-layer exception: Record falls back with `REBUILD_FAILED` on every page (existing); PDF import
  refuses with P11's message; the index row stores the error as today (`index_row`'s `except`). `log_failure` carries
  only the exception and run id, never text.
- Deterministic and pure: Extract again on an unchanged reading gives identical rows, ids and locators (FR-27). The
  fingerprints PDF import uses are unchanged in kind.
- Statements recorded by the old path are untouched until Extract again; a confirmed or rejected statement is
  `kept_reviewed` (existing). `EXTRACTION_VERSION` makes a non-forced extraction start a new run.
- The index rebuild resumes after a restart (`pending` is a query).

## Privacy/security and migration impact
- No model or network call is added; the engine reads saved readings only. C-net in every new test.
- Money in integer minor units through `core/money.to_minor`; no float decides a role or sign (positions are floats,
  money is never).
- No schema migration. `ANALYZER_VERSION` and `EXTRACTION_VERSION` bumps only. Last fours stay four digits.
- `summary.json` stays allowlisted counts; the probe prints no document text.

## Vertical slices
| ID | FR/SC covered | Dependencies | Files/changes | Verification command / evidence |
|---|---|---|---|---|
| SL-01 | FR-01, FR-02, FR-03, FR-04, FR-05 (rows 1–4), OD-3, OD-4; SC-21, SC-05 (engine), SC-14 (engine) | none | `documents/table_engine.py` (PageView moved, tokens, columns, zones, headings, rows); `finance/pdf_import.py` (re-export `PageView`); `tests/table_engine_fixtures.py` (all contract fixtures and hand-written expected values); `tests/test_table_engine.py` (P-checks, SC-21, engine rows for WF, WF-bare, DM, WR, OD, NB, TD, CS) | `python -m pytest tests/test_table_engine.py -k "pcheck or sc21 or rows or sc14" -q`; `python -m pytest tests/test_pdf_imports.py tests/test_statement_rebuild.py -q` (unchanged) |
| SL-02 | FR-05 (rows 5–7, WR-above), FR-06, FR-07, FR-08, FR-09 (balance/other), FR-16; SC-08 (engine), SC-09 (engine), SC-10 (engine) | SL-01 | `documents/table_engine.py` (extent, continuation offset, line classes, summary anchors, section titles, unplaced, rejections); tests for K3, BL, UP, WR-split, WR-above, X, statement-accounts T/T-edge, a one-row continuation page | `python -m pytest tests/test_table_engine.py -k "sc08 or sc09 or sc10 or rejected or section_titles or one_row_continuation or description_above" -q` |
| SL-03 | FR-09 (schedule), FR-10 – FR-15, FR-17, OD-1, OD-2 (function); R1, R3 – R5; engine-level SC-02, SC-04, SC-06, SC-07, SC-16, SC-17, SC-23 – SC-25 | SL-02 | `finance/statement_dates.py` (moved helpers; `statement_rows` re-exports); `finance/statement_tables.py` (roles, signs, anchors inside tables, period, order, year, schedule, outcome texts, `prior_order`, `as_rebuild`, `as_analysis`); `tests/test_table_engine.py` statement tests per fixture | `python -m pytest tests/test_table_engine.py -q` |
| SL-04 | FR-33, OD-4 (tuning), OD-6; SC-18 (engine path) | SL-03 | `evals/statement_layouts.py`; `tests/table_engine_generator.py`; `tests/test_table_engine_generator.py` (≥ 200 cases through the real reader and the engine's statement path; generating twice gives byte-identical PDFs; every FR-33 variation in ≥ 5 cases); `scripts/statement_diagnose.py` (engine section) | `python -m pytest tests/test_table_engine_generator.py -k generator_only -q` (0 misses, seed printed on failure); `python scripts/statement_diagnose.py <a generated synthetic PDF>` prints no text (asserted by a test that greps its output for every fixture word) |
| SL-05 | FR-07 (record), FR-18 – FR-20, FR-22 – FR-25, FR-27, FR-28 (Record side); SC-01 – SC-07, SC-09 – SC-11, SC-13 (Extract again), SC-14, SC-15, SC-16, SC-17, SC-19 (Record), SC-23 – SC-25 | SL-03 | `documents/extraction.py` (P10; `EXTRACTION_VERSION`); `tests/test_table_engine_record.py`; `tests/test_table_engine_generator.py` (the 10 seeded cases end to end through Record); `tests/test_table_engine_browser.py` (SC-03 step 4); `tests/test_statement_rebuild.py`: only Record-level changes here: `test_sc18_p8_*` (`:825–845`) retarget their `monkeypatch` from `statement_rows.rebuilt_pages`/`statement_rows.rebuild` to `statement_tables.engine_pages`/`statement_tables.read` (patch target only, no expected value changes), and Record-level tests of the scenarios the contract lists as changed get their new expected values; its `bank()`/`analysis()` helpers stay on the old reader until SL-06; `docs/documents.md` "Statement rows from the printed columns" rewritten (heading kept) | `python -m pytest tests/test_table_engine_record.py tests/test_table_engine_generator.py tests/test_statement_rebuild.py tests/test_statement_accounts.py tests/test_statement_forms.py tests/test_extraction.py tests/test_provenance.py tests/test_reextraction.py -k "not _import and not journey_j1 and not generator_only" -q` (one `-k`: pytest keeps only the last one); `RUN_BROWSER_TESTS=1 python -m pytest tests/test_table_engine_browser.py tests/test_statement_accounts_browser.py -q` |
| SL-06 | FR-21, FR-24 (import), FR-26, FR-28 (import side); SC-08 (import), SC-12, SC-13 + SC-22 (J1), SC-16 (import), SC-19 (import); test names for import steps end in `_import` | SL-05 | `finance/pdf_import.py` (`analyze` adapter, `analyze_legacy`, `ANALYZER_VERSION = 3`); `finance/statement_rows.py` (import `analyze_legacy`); `finance/ledger.py` (`pdf_state`: `prior_order`, exception refusal); `tests/test_pdf_imports.py` (7-d updated, 7-a′ added); `tests/test_statement_rebuild.py`: its `bank()` (`:43`) and `analysis()` (`:51`) helpers move together to the engine (`statement_tables.read(...).as_rebuild()` and the new `analyze`), so every `rows_*`, `sc27`, `sc28` and `fr30_*` test checks the engine; the helper-level tests the contract lists as changed (x2, the balance title, the second heading) get their new expected values; `ANALYZER_VERSION == 3`; only tests of the old reader's internals stay on the old reader (`heading_titles` `:61`; any test importing `Reading`, `heading_row`, `cut_at` or `rebuilt_pages`; and any test that patches an old internal such as `pdf_import.joined_amounts`, e.g. `test_sc27_without_fr30_…` `:401–405`, which calls `pdf_import.analyze_legacy`), listed in the slice's handoff; `docs/documents.md` "Transaction imports" | `python -m pytest tests/test_table_engine_record.py -k "_import or journey_j1" -q`; `python -m pytest tests/test_statement_rebuild.py tests/test_pdf_imports.py tests/test_imports.py tests/test_layout_consumers.py -q`; `RUN_BROWSER_TESTS=1 python -m pytest tests/test_pdf_imports_browser.py -q` |
| SL-07 | FR-34; SC-20 | SL-04, SL-06 | `evals/synthetic.py`, `evals/run.py`, `evals/graders.py`, `evals/report.py`; `tests/test_evals.py`; `docs/evals.md`, `evals/README.md` (counts 44 → 48, tag `aligned`, the comparison); `docs/open-work.md` (remove the old path after the user's corpus run, D4; G10; FR-40 – FR-44) | `python -m pytest tests/test_evals.py -q` (runs `evals.run.run` with the `local_model` stub on a generated synthetic corpus and asserts the comparison in `summary.json` and `report.md`); `python -m evals.synthetic <tmp>` writes 48 cases |

Full regression after SL-07 (the contract's run plus the suites touched):
```
python -m pytest -q
RUN_BROWSER_TESTS=1 python -m pytest tests/test_table_engine_browser.py tests/test_statement_accounts_browser.py \
  tests/test_pdf_imports_browser.py tests/test_document_v2_browser.py -q
```

## Requirements & scenarios coverage matrix
| Requirement | Slice | Scenarios |
|---|---|---|
| FR-01 | SL-01, SL-05 | SC-14 |
| FR-02 | SL-01 | SC-21 |
| FR-03, FR-04 | SL-01 | SC-01, SC-02, SC-05, SC-25 |
| FR-05 | SL-01, SL-02 | SC-03 (with WR-split), SC-04 |
| FR-06 | SL-02 | SC-08 |
| FR-07 | SL-02, SL-05 | SC-09, SC-01 (anchors, record values) |
| FR-08 | SL-02 | SC-10, SC-24 |
| FR-09 | SL-02, SL-03 | SC-09 (with the schedule), SC-15 (D), 7-a′ |
| FR-10 – FR-13 | SL-03 | SC-01, SC-05, SC-06, SC-07, SC-23 |
| FR-14 | SL-03 | SC-02, SC-04, SC-12, SC-16 |
| FR-15 | SL-03 | SC-06 |
| FR-16 | SL-02 | SC-15 |
| FR-17 | SL-03 | SC-17 |
| FR-18 – FR-20 | SL-05 | SC-01, SC-02, SC-10, SC-11, SC-24 |
| FR-21 | SL-06 | SC-12, SC-08, SC-16 |
| FR-22, FR-23 | SL-05 | SC-03, SC-01 (WF-flag), SC-15 |
| FR-24 | SL-05, SL-06 | SC-19 |
| FR-25 | SL-05, SL-06 | J1 (SC-13) |
| FR-26 | SL-06 | J1 (SC-22) |
| FR-27 | SL-05 | SC-14 |
| FR-28 | SL-05, SL-06 | SC-15 and the contract's "Scenarios this spec changes" |
| FR-33 | SL-04 | SC-18 |
| FR-34 | SL-07 | SC-20 |
| OD-1, OD-2, OD-3, OD-4, OD-6 | SL-01, SL-03, SL-04 | SC-04, SC-16, SC-21, SC-18 |
| R1 – R5 | SL-03 | SC-06 b, SC-17, SC-23, SC-24, SC-25 |
| FR-40 – FR-44 | not in phase 1 (OD-5) | — |

## Test environments, data, stubs for nondeterministic components, final-state oracle
- **Isolation:** `tmp_path` libraries only; C-net autouse in every new module; never `P:\Finances`,
  `%LOCALAPPDATA%\HomeManager` or `P:\EvalCorpus`.
- **Levels:** engine and statement-layer tests are unit/integration tests on real readings of synthetic PDFs, with no
  store (`tests/test_table_engine.py`, independent tests). Record and import tests go through `ExtractionService` and
  `create_app`/`TestClient` (`tests/test_table_engine_record.py`); J1 and SC-03 are single tests with ordered
  checkpoints. Browser: opt-in.
- **Stubs:** `local_model` answers by schema with the contract's summary stubs; `Transactions` empty unless a
  scenario says otherwise. Engine fault: `monkeypatch` of `statement_tables.read`/`engine_pages` and of the engine entry
  used by `analyze`.
- **Oracle:** expected rows are the contract's hand-written tables, held as literals in `tests/table_engine_fixtures.py`
  and the generator's own inputs; final state is read back through `GET /api/finance/records/statement/{id}`,
  `GET /api/provenance/transaction/{id}` and SQL row snapshots of `statements`, `transactions` and
  `pdf_import_index`.
- **OD-4:** if SL-04's generator shows misses, the slice may change `ALIGN` only within 0.5 – 1.0 font sizes and must
  rerun SL-01 – SL-03; the value used is written in `docs/documents.md`.

## Risks, unresolved decisions, alternatives
- **R-A Real statements unlike the fixtures** (U1, U2). The probe (P13) lets the user confirm on their two failing PDFs
  without sharing text; the eval comparison (FR-34) is the gate for removing the old path (D4).
- **R-B Role enumeration picks a wrong assignment that also adds up.** Bounded by FR-13's two-link rule and by the
  "different signed amounts → undecided" rule (P7.4).
- **R-C Behavior changes in existing tests** are exactly the contract's list; any other existing failure is a defect
  of the slice, not a reason to edit an expected value.
- **R-D Performance.** Enumeration is at most 6 columns × 5 roles with constraints, per table; the generator test reads
  ≥ 200 PDFs and must finish in under 2 minutes on CI (asserted loosely by the suite's time, not by a test).
- **Deviation from the contract's file plan:** the generator's logic lives in `evals/statement_layouts.py` so the eval
  corpus can reuse it; `tests/table_engine_generator.py` still exists and builds the PDFs with `make_pdf` (P12).
- **Alternative rejected:** extending `pdf_import.structure` with more heading names. It keeps the heading-first design
  that D1 rules out.
- **Open, for the user:** none blocking. Deferred items go to `docs/open-work.md` in SL-07.
