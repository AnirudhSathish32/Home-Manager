# One table engine for every text PDF: rows by shape, columns by alignment, roles by arithmetic
Feature: pdf-table-engine

<!-- Approval state lives in approvals/<slug>.json and is bound to this file's content hash.
     Do not add a Status line: changing it would change the hash. Check with gate.py. -->

Amends: `specs/statement-accounts/spec.md` FR-16 – FR-19, FR-21, FR-23, FR-27 (how a statement's rows are found and
read) and `specs/account-import-pdf/spec.md` FR-06 – FR-08, FR-10 (how PDF import finds tables and rows). Every other
requirement of both specs stands, including statement-accounts FR-20, FR-22, FR-24 – FR-26, FR-29, FR-30 and
account-import-pdf FR-09, FR-11 – FR-30. Superseded and kept requirements are listed under "Supersedes".

## Decisions already made (user, 2026-10-27; not to be re-asked)
- **D1 No per-bank templates.** A statement is read by what every statement shares, not by its wording or layout: a
  transaction row starts with a date and carries amounts; the amounts line up in columns; the running balance and the
  printed summary add up. Heading wording is a hint, never a requirement. A bank changing its layout must not need
  code or configuration changes (user: "We shouldn't have to build a schema for every type of account statement").
- **D2 One engine for all stored PDFs.** The same engine turns a text PDF's positioned words into tables for every
  document kind. What proves a table was read right is a small arithmetic check per document kind, not per issuer.
- **D3 Statements first.** Phase 1 is the engine plus the bank and card statement check, used by Record and by PDF import
  (Add missed transactions). Pay stubs, bills, receipts and investment statements follow as later phases (FR-40 –
  FR-44).
- **D4 Old path per kind until parity.** Each document kind keeps its current table reading until the engine is shown to
  do at least as well on it (FR-33, FR-34); the old code for that kind is then removed.
- **D5 Open decisions settled** (user, 2026-10-27, "defaults ok"): OD-1 through OD-6 take their recommended defaults,
  and risks R1 – R5 are accepted with their defaults: R1 as FR-13, R2 as FR-17, R5 in FR-04, and R3 (a column that fits
  no role is never an amount) and R4 (rows under a "pending" section title are unplaced, not recorded) are binding as
  written under "Domain risks".
- **D6 Test-contract gaps settled** (user, 2026-10-27):
  - G7: a printed opening or closing balance line is captured, never listed as an unplaced line, wherever it sits on the
    page and whether or not it prints a date. The engine replaces the reader's table reading, so the printed values are
    what the statement records and the document page shows (FR-07).
  - G1: a table whose rows all fall outside the statement period is a schedule, not transactions (FR-09).
  - G2: the engine reads the printed statement period itself, so PDF import decides the year and date order the same
    way Record does (FR-14, FR-21).
  - G4: a dated line with no amount is never dropped silently (FR-05, FR-08).
  - G14: the synthetic eval corpus gains aligned-column text-PDF statements, so the evals measure the engine (FR-34).

Background (user reports, 2026-10-27): a DD/MM/YYYY statement recorded 7–8 transactions and dropped the rest, with dates
read month-first; a Wells Fargo statement got no rebuilt table at all. Reproduced on synthetic pages (no user data
opened): a Wells Fargo-style two-line heading (`Deposits/` over `Additions`, `Ending daily` over `balance`) and headings
such as `Narration`, `Withdrawal Amt.`, `Deposit Amt.`, `Closing Balance` give no table, so Record silently falls back to
the model's rows; wrapped descriptions and rows that print no date (one date per day) are rejected as "No date is
printed", and on a rebuilt page the missed-row check is off, so those rows are lost to the ledger.

## Goal / users / scope / non-goals
**Goal.** Any text-PDF statement, from any bank, in any layout, gives every printed transaction with its exact date,
amount and direction, or says exactly which printed lines it could not place. A misread can't reach the ledger quietly,
because the rows must add up to the statement's own balances.

**Users.** The household user recording statements (Record) and adding missed rows (Add missed transactions).

**In scope (phase 1).**
- The engine: tables from positioned words, with no heading required (FR-01 – FR-09).
- Bank and card statement roles, signs and dates decided by arithmetic and whole-document evidence (FR-10 – FR-17).
- Record and PDF import use the engine's statement tables (FR-18 – FR-24).
- Existing data, determinism, evidence and the switch from the old path (FR-25 – FR-34).

**Later phases (outlined here; each gets its own amendment spec and test contract before it is built, OD-5).**
Pay stubs (FR-40), bills (FR-41), receipts printed as text PDFs (FR-42), investment statements (FR-43), and replacing
the reader's own header-required table finder for every consumer (FR-44).

**Non-goals.**
- Scanned pages and photos. The vision path saves no word positions (`documents/vision_tables.py` has no box or word
  data, verified), so they keep the model's reading. Revisit only if a reader that saves word boxes is added.
- Tax forms (W-2, 1099 boxes). They are labelled boxes, not tables, and keep the form reader.
- Splitting one PDF into several accounts (R2).
- Per-institution templates, stored layouts, or a learned layout that is required to read a statement.
- Any model or network call added by this feature.
- Decimal-comma amounts (`1.234,56`) unless OD-3 says otherwise.

## Existing behavior (verified paths, assumptions, unknowns)
All paths are under `src/home_manager/` unless noted.

**Today's table finding is heading-first and exact.**
- PDF import and Record find a transactions table only from a heading row whose cells exactly equal (lower-cased) a
  name in `finance/tabular.py:27` `HEADER_NAMES` (`is_heading`, `finance/pdf_import.py:165`). No partial words, no
  punctuation tolerance, no heading over two lines.
- Rows on a page with no native table are rebuilt by `pdf_import.visual_row` (`pdf_import.py:261`). A row needs a date
  word and an amount word on the same visual line; a line without one is not a row (`return None`, `:274`) or is
  rejected ("No date is printed", `read_date`, `:503`).
- Column spans are midpoints between heading texts (`make_spec`, `:204`). With no recognised heading there are no spans.
- A continuation page (no heading) reuses the previous page's spec (`structure`, `:428–438`).
- The PDF reader builds its own native tables only under a printed text header with repeated numeric alignment
  (`documents/pdf_layout.py:453` `table_grid`, "Require a printed textual header").

**Record.**
- `statement_rows.rebuild` (`finance/statement_rows.py:199`) applies PDF import's rules, decides the date order
  (`date_order`, `:179`: a day over 12, else the order that fits the period) and the year from the period (`placed`,
  `:161`).
- Pages it rebuilds replace the model's rows (`documents/extraction.py:1767–1791`), and the missed-row check is skipped
  for them (`extraction.py:3413–3417`). Pages it doesn't rebuild keep the model's rows with no note saying so.
- A failed rebuild falls back to the model on every page with `REBUILD_FAILED` (`extraction.py:3376–3379`).
- The statement checks (opening + transactions = closing; printed summary) run on the recorded amounts
  (`statement.summary` trace, `finance/document_traces.py:216–225`).

**Pay stubs** pick Current and YTD columns by heading words (`extraction.py:864` `paystub_columns`) and anchor values
to native cells (`anchor_paystub`, `:1161`). **Receipts and bills** anchor model values to native tables
(`documents/native_values.py:84` `anchor_rows`).

**Evals.** The synthetic corpus has text-PDF statements, card statements, receipts and pay stubs with known answers
(`evals/synthetic.py:219–238`), and graders compare statement transactions (`evals/graders.py:148`). `--compare-schema`
compares prompt-schema variants, not table readers (`docs/evals.md:132`), so it does not measure this feature.

**Assumptions**
- A1: Text-PDF statements print each transaction's date on the same visual line as at least one of its amounts, or on a
  line directly above or below it within the same row block (wrapped rows). Statements that print the date in a
  separate block from the amounts are not handled.
- A2: Amounts in the same column share a right edge (or a left edge, or a centre) within a small tolerance. True of
  every statement fixture and of right-aligned money columns generally; not verified on the user's PDFs.
- A3: Most bank statements print a running balance or a summary (opening, closing, total in, total out); card
  statements print previous and new balance and section totals. Where neither exists, roles fall back to hints (FR-12).

**Unknowns**
- U1: The user's two failing statements were not opened (CLAUDE.md). The causes above are reproduced on synthetic pages,
  not confirmed on the real PDFs. The redacted layout probe (OD-6) would confirm them.
- U2: Whether any of the user's statements print amounts left-aligned or centred (A2).

## Functional requirements

### The engine (all text PDFs)
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-01 | The engine reads only a saved reading's `embedded_text` pages with saved layout (words with boxes, lines). It opens no PDF, makes no model or network call, and is deterministic: the same reading gives the same tables, rows, ids and issues. | Run twice on every fixture: byte-identical output. A network guard and a model stub with zero expected calls pass. |
| FR-02 | **Tokens.** Each word or run is tagged as a date, an amount, or text. Dates: `M/D`, `MM/DD`, `M/D/YY`, `MM/DD/YYYY`, the same day-first, `-` and `.` separators, `YYYY-MM-DD`, and month names (`01 Oct 2026`, `1-Oct-26`, `Oct 1`, `Oct 01, 2026`). Amounts: digits with `,` thousands and `.` decimals, optional currency symbol or ISO code, sign as leading `-`/`+`, trailing `-`, parentheses, or `CR`/`DR`. A number joined to description text stays text (statement-accounts FR-30). | A table of printed tokens to expected tags, hand-written in the test contract, all pass; `PPD ID 1234567890` stays text. |
| FR-03 | **Transaction rows by shape.** A row starts at a visual line holding a date token in the table's date column and at least one amount token in an amount column. No heading is needed to find rows. | A page with the headings deleted gives the same rows as with them (SC-05). |
| FR-04 | **Columns by alignment.** Amount columns are the groups of amount tokens whose right edges (else left edges or centres) line up within a tolerance, supported by at least two rows (OD-4 sets the tolerance). The date column is the group of date tokens at the rows' left. The description is the text between the date and the first amount column. A second date column is the posted date when its heading says post/posting, else the transaction date stays the first and the second is the posted date (R5). Headings, when printed, label the columns they sit over, including headings printed on two lines; their wording is never required. | Wells Fargo-style two-line headings, headings with unknown wording, and no headings all give the right columns (SC-01, SC-02, SC-05). |
| FR-05 | **Wrapped rows.** A line with no date and no amount whose words lie within the description column joins the description of the row above, which then cites both lines. A line with no date but an amount in an amount column is its own row (OD-1 decides its date). A line above a row's date line that holds only description text joins that row when the statement prints descriptions above their amounts (A1). A line with a date in the date column but no amount joins the line directly below when that line has an amount and no date (one row citing both, A1); otherwise it is a rejected row listed with page, row and a reason (an amount joined to the description keeps today's reason, statement-accounts FR-30), never dropped (D6). | Descriptions wrapped onto 2 and 3 lines give one row each with the full description (SC-03); dateless same-day rows follow OD-1 (SC-04); a date line over its amount line is one row, and a dated line with no amount is listed as rejected (SC-03). |
| FR-06 | **Table extent.** A table is the run of rows that share its column set. It ends where a line with a different column set starts a new run of at least two rows, at a line that names a balance or totals section directly above a new run, or at the page end. A next page whose rows fit the same column set (positions within the tolerance, after page offset) continues it, with or without a repeated heading. | Continuation pages with and without headings link to page 1's table (SC-08); a daily balance table below the transactions starts a new table (SC-09). |
| FR-07 | **Lines inside a table that aren't transactions** are classed, not recorded as rows: a balance line (opening/beginning/previous, closing/ending/new) gives a balance anchor; a total line (a total or subtotal of a column) gives a check value; a repeated page heading or footer is ignored. A line's class comes from the words in it and where its amount sits (a balance line's amount sits in the balance column or alone), not from a bank-specific list. A balance line outside every table on the statement's pages (opening/beginning/previous, closing/ending/new, with or without a date, such as `Beginning balance on 10/1 1,000.00`) is a summary anchor, not an unplaced line. The statement's recorded opening (previous) and closing (new) balances are the printed anchor values, so the document page shows what the statement prints; where the model's summary gave a different value, the record notes it (D6). | Beginning and Ending Balance rows inside the table anchor the chain and are not transactions; `Total deposits 2,000.00` is a check, not a row (SC-09); dated summary lines above the table are anchors, and the record shows their values (SC-01). |
| FR-08 | **Nothing is dropped silently.** Every line on a table's pages that holds a date token and an amount token and is not a recorded row, a rejected row (FR-16), a balance or summary anchor (FR-07), a total, or a row of a non-transactions table is an **unplaced line**, listed with page and line text. A dated line with no amount follows FR-05. | Every fixture's printed lines are accounted for: rows + rejected + anchors + totals + other-table rows + unplaced = all date-and-amount lines (SC-10). |
| FR-09 | **Non-transaction tables** (daily balance, interest or fee summaries, check images lists that repeat main-table rows, payment schedules) are found as tables and not read as transactions. A table is a transactions table when its rows have a description and its amounts fit the statement roles (FR-10); a date-and-balance-only table is a balance table. A schedule is not transactions, and its rows are other-table rows: a table, or a run of at least two consecutive rows that starts at a page's top or after a line with no date and continues a table, whose every row is dated outside the statement period ± 7 days (FR-14's period). With no period known, dates don't decide this (D6). | Daily ending balance and fee summary tables, and a payment schedule dated after the period, give no rows (SC-09); statement-accounts FR-27's fixtures keep their results (SC-15). |

### Bank and card statements (phase 1)
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-10 | **Roles by arithmetic.** With k amount columns, the engine tries each role assignment: which column, if any, is the running balance; whether the others are one signed amount or a money-in and a money-out column (and which is which). It keeps the assignment under which the running balance chain holds (each row's balance = the previous balance ± its amount, exactly in minor units, starting from the opening balance anchor or the first row). | Fixtures with columns in any order (Balance first or last; Withdrawals before or after Deposits; Debit/Credit unnamed) give the right roles (SC-01, SC-05). |
| FR-11 | **With no running balance**, the assignment that makes the printed summary hold is kept: opening + money in − money out = closing (bank), previous − payments/credits + charges = new balance (card), and any column totals (FR-07). Heading words break a tie between assignments that both hold, and are the only guide when neither the chain nor the summary is printed. A Balance column is never an amount (unchanged). | A statement with no balance column but a printed summary gets its signs from the summary (SC-07). |
| FR-12 | **A single unsigned amount column with no chain** (typical card statements) takes each row's sign from, in order: its own `CR`/`DR`, minus or parentheses; the section title above its run (payments and credits vs purchases, charges, fees, interest, cash advances); then the statement type's default (card: positive is money out; bank: negative is money out; statement-accounts FR-18). The result must still satisfy the summary when one is printed; if it doesn't, FR-15 applies. | A card statement with "Payments and Credits" and "Purchases" sections records payments as money in and purchases as money out (SC-07). |
| FR-13 | **Too few rows to decide.** An assignment counts as decided by the chain only with at least two chain links, or by the summary only when the summary is printed. A statement with one row and no summary is decided by heading words and the type default, and needs review naming the reason (R1). | A one-row statement with no summary is recorded and needs review (SC-06). |
| FR-14 | **Date order from the whole document.** The order is: the one a day over 12 decides; else the one under which every row date falls within the printed period ± 7 days and the rows are in non-decreasing printed order within each table; else OD-2's fallback; else the rows are not recorded and one issue per page says the order can't be told. A four-digit year is read as printed; a missing or two-digit year comes from the period (statement-accounts FR-19, unchanged). **The period** is read by the engine from the printed text: the line outside every table nearest the top of page 1 that holds exactly two dates with four-digit years and no amount, the first not after the second (its own date order is the one a day over 12 decides, else the rows' order, else it is not used). Record uses it, and falls back to the model's summary period only when none is printed; PDF import uses it the same way (D6). | DD/MM fixtures whose first rows all have days ≤ 12 read day-first (SC-02); an all-≤-12 statement with no period is not guessed (SC-16); PDF import of a year-less statement that prints its period asks for no year (SC-12). |
| FR-15 | **Outcome.** When the chain (or the summary) holds for every row and there are no unplaced lines, the rows are recorded and the rows add no review reason. Otherwise the rows that could be read are recorded, and the statement needs review naming each unplaced line and the first row where the chain breaks ("Page 2 row 14: the balance 1,203.40 doesn't follow from the row above"). | A fixture with one misprinted amount needs review naming that row; its other rows are recorded (SC-06). |
| FR-16 | Rows rejected by the existing exact rules (impossible date, unreadable amount, both debit and credit, currency differing from the statement's, two amounts in one column) are still rejected with the same reasons and listed (statement-accounts FR-21, account-import-pdf FR-10). | statement-accounts fixture X keeps its expected results (SC-15). |
| FR-17 | Two tables whose balance chains don't join (each chain holds, but the second doesn't start from the first's last balance) are reported as one review issue naming both tables ("This PDF may hold more than one account"); both tables' rows are recorded (R2). | A combined checking-and-savings fixture is recorded with that one issue (SC-17). |

### Where the engine is used (phase 1)
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-18 | Record uses the engine's transactions tables on every `embedded_text` page of a bank or card statement PDF. On those pages the model's rows decide nothing (statement-accounts FR-20, unchanged: unmatched model rows become record notes). | The user's two reported layouts, rebuilt as synthetic fixtures, record every row from the printed columns (SC-01, SC-02). |
| FR-19 | A statement page where the engine finds no transactions table keeps the model's rows and the missed-row check, as today, and now adds a record note: "Page N: no table was found in the printed columns, so its rows are the reading's; check them." | A page with prose only gets the note and the model's rows (SC-11). |
| FR-20 | Unplaced lines (FR-08) on engine pages are review reasons. This replaces skipping the missed-row check on rebuilt pages. | SC-10. |
| FR-21 | PDF import (Add missed transactions) lists the engine's transactions tables and rows. For the same reading, its preview rows (date, amount, direction, description) equal the rows Record records, before duplicates. Its year, date-order and sign choices are offered only when the engine can't decide them (FR-12 – FR-14, with the printed period). All other account-import-pdf behavior is unchanged. | SC-12: preview and Record agree on every phase 1 fixture. |
| FR-22 | Evidence keeps today's shape: `{rebuilt, page, table_id, row, line_ids, word_ids, cell_ids, quotes}`; a row of several lines cites every line and word; the document page lights them. | `GET /api/provenance/transaction/{id}` for a wrapped row lists both lines (SC-03). |
| FR-23 | Pages flagged for overlapping or rotated text still give engine rows and the statement needs review naming the page (statement-accounts FR-22, unchanged). | statement-accounts S-flag fixtures keep their results (SC-15). |
| FR-24 | If the engine fails on a reading (an exception), Record falls back to the model's rows on every page with the existing `REBUILD_FAILED` note, and PDF import refuses with its existing message; nothing else changes. | A fault-injected engine gives the fallback (SC-19). |

### Existing data, switch-over and measurement
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-25 | No migration rewrites a record. Statements recorded before this change keep their rows until **Extract again**; a statement you confirmed or rejected is never rewritten (statement-accounts FR-26, unchanged). | SC-13. |
| FR-26 | `ANALYZER_VERSION` is bumped, so every PDF reading is indexed again at the next start (`pdf_import_index`, migration 072; no schema change). | The index rebuilds once and the picker shows `indexing: true` until done. |
| FR-27 | Re-running Record on an unchanged reading gives identical rows and transaction ids (statement-accounts SC-20, unchanged). | SC-14. |
| FR-28 | Existing tests: every statement-accounts and account-import-pdf scenario passes unchanged, except the ones whose expected result this spec changes, which are listed one by one in the test contract with the requirement that changes them. | SC-15. |
| FR-33 | **Layout generator.** The test suite generates at least 200 synthetic text-PDF statements from a fixed seed, varying: column order; heading wording (known, unknown, none, one line, two lines); date format and order (month-first, day-first, ISO, month names, with and without year); wrapped descriptions (1–3 lines); one date per day; signs (one signed column, in/out columns, `CR`/`DR`, parentheses); with and without a balance column and summary; continuation pages with and without headings; extra non-transaction tables. Every generated statement records every row with exact date, amount and direction, and reconciles. | The generator test passes in CI with zero misses; failures print the seed and layout. |
| FR-34 | **Eval metric.** The evals suite reports, for text-PDF statements, the share of printed rows recorded with exact date, amount and direction, the share of statements that reconcile, and unplaced lines, for the old reader and the engine side by side. It runs on the synthetic corpus in CI. The synthetic corpus gains four text-PDF statements printed in aligned columns (a Wells Fargo-style two-line heading, a DD/MM/YYYY statement, one with wrapped descriptions, and a card statement with sections), added after the existing cases so their ids and answers don't change; the docs' corpus counts are updated (D6). The user runs it on the donated corpus in their own terminal and shares only `summary.json` (docs/evals.md). The old statement path is removed only after the user reports the engine at least as good on their corpus (D4). | `python -m evals.run` on the synthetic corpus shows both readers; the engine is ≥ the old reader on every metric. |

### Later phases (outline; each needs its own amendment spec, OD-5)
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-40 | Pay stubs: earnings, taxes and deductions tables from the engine; Current and YTD columns decided by earnings − taxes − deductions = net pay holding in each, with heading words as tie-breaks. Hours and rates are never pay (unchanged). | Its own spec. |
| FR-41 | Bills: charge lines from the engine; their sum equals the amount due, and previous balance − payments + new charges = balance where printed. | Its own spec. |
| FR-42 | Text-PDF receipts: item lines from the engine; quantity × unit price = line total; lines sum to subtotal; subtotal + tax (+ tip) = total. | Its own spec. |
| FR-43 | Investment statements: holdings from the engine; shares × price = value; holdings sum to the account total. | Its own spec. |
| FR-44 | The reader's header-required table finder (`pdf_layout.table_grid`) is replaced by the engine for every consumer (layout context, native anchoring, the document page's cell highlights), once every kind above has switched. | Its own spec. |

## Invariants, privacy, security and data retention
- Nothing leaves the machine. No model or network call is added; the engine reads only saved readings.
- Money stays exact: integer minor units via `core/money.to_minor`; no float arithmetic decides a role or sign.
- The engine never invents a row, a date or an amount. A carried date (OD-1) is the printed date of the row above, and
  the row says so in its record note.
- A Balance column is never an amount. A misread can't be recorded as verified: a row set that fails the chain or the
  summary needs review (FR-15).
- Tests use only synthetic fixtures. P:\Finances, %LOCALAPPDATA%\HomeManager and P:\EvalCorpus are never read (CLAUDE.md);
  the redacted probe (OD-6), if used, is run by the user, and its output holds no descriptions or amounts.
- Account numbers are stored only as their last four (account-import-pdf FR-30, unchanged).

## Errors, recovery, duplicates, restart behavior
- Engine exception: FR-24 fallback; the failure is logged through `log_failure` without document text.
- A statement with unplaced lines or a broken chain is recorded with the rows that could be read and needs review
  (FR-15). Correcting it is the existing Correct and Add missed transactions flows.
- Duplicates: the same row printed in two tables follows statement-accounts FR-29 (both recorded, one note); PDF import
  duplicate detection is unchanged (account-import-pdf FR-16, FR-17).
- Extract again is idempotent (FR-27). Index rebuild after the version bump resumes after a restart, as today.

## Nondeterministic outputs and how they are verified
- The engine is deterministic; it is verified by exact expected rows, hand-written in the test contract, never computed
  from the code under test.
- Model output on non-engine pages and the model's summary fields come from fixed stubs (as in
  `tests/statement_account_fixtures.py`). No test asserts a live model's output.
- The layout generator (FR-33) is seeded; each case's expected rows come from the generator's own inputs, not from the
  engine.
- The donated-corpus eval is run by the user; only aggregate metrics in `summary.json` are shared.

## Scenarios (expand into test-contract.md with design-tests before approval)
| ID | FR IDs | Initial state | User/API actions | Expected final DB/files/UI state |
|---|---|---|---|---|
| SC-01 | FR-03, FR-04, FR-07, FR-10, FR-18 | Synthetic Wells Fargo-style checking PDF: two-line heading `Date / Check Number / Description / Deposits/ Additions / Withdrawals/ Subtractions / Ending daily balance`, `M/D` dates, balance printed only on some rows, period printed, `Beginning balance on 10/1` and `Ending balance on 10/31` lines above the table | Record | Every row recorded with exact date, amount and sign; check number not in the amount; statement reconciles and has no row review reason; the summary lines are anchors, not unplaced, and the record's opening and closing balances are their printed values |
| SC-02 | FR-04, FR-14, FR-18 | DD/MM/YYYY statement with `Date / Narration / Withdrawal Amt. / Deposit Amt. / Closing Balance`, 20 rows, the first 8 dated day ≤ 12 | Record | 20 rows, every date day-first; reconciles |
| SC-03 | FR-05, FR-08, FR-22 | Statement whose descriptions wrap onto 2–3 lines from row 5 on; a variant with a date line over its amount line and a dated line with no amount | Record; open a wrapped row's source | One row per transaction with the full description; provenance lists all its lines; the date-over-amount pair is one row; the dated line with no amount is a rejected row listed with page and row |
| SC-04 | FR-05, OD-1 | Statement printing the date only on a day's first row | Record | Per OD-1: each later row takes the date above and carries the note; nothing is rejected as "No date is printed" |
| SC-05 | FR-03, FR-04, FR-10 | SC-01's page with every heading removed; columns in a shuffled order | Record | Same rows as SC-01 |
| SC-06 | FR-13, FR-15 | (a) Statement with one amount altered so the chain breaks at row 14; (b) one-row statement with no summary | Record | (a) All rows recorded, review names page and row 14; (b) row recorded, review gives the reason |
| SC-07 | FR-11, FR-12 | Card statement, one unsigned Amount column, no balance column, sections "Payments and Credits" and "Purchases", printed previous/new balance | Record | Payments money in, purchases money out; summary holds |
| SC-08 | FR-06 | 3-page statement: page 2 repeats the heading, page 3 has none and sits 6 pt to the right | Record and PDF import preview | One table linked across 3 pages; every row recorded |
| SC-09 | FR-07, FR-09 | Statement with Beginning/Ending Balance lines inside the table, a `Total deposits` line, and a Daily ending balance table below, and a payment schedule dated after the period on page 2 | Record | Balance lines anchor the chain, the total checks, the daily table and the schedule give no rows and no unplaced lines |
| SC-10 | FR-08, FR-20 | Statement with a dated, amounted line printed outside every table's columns | Record | That line is listed as unplaced; the statement needs review; the other rows recorded |
| SC-11 | FR-19 | Statement with page 1 table and page 2 prose with model-stub rows | Record | Page 2 keeps the stub rows, carries the "no table was found" note, missed-row check runs |
| SC-12 | FR-14, FR-21 | Each phase 1 fixture | PDF import preview, then Record | Preview rows equal recorded rows (date, amount, direction, description); no year or date-order choice is asked where the period is printed |
| SC-13 | FR-25 | A statement recorded and confirmed by the old path; another recorded but undecided | Upgrade; start; Extract again on both | Confirmed statement unchanged; undecided one rebuilt by the engine |
| SC-14 | FR-01, FR-27 | Any fixture | Record, then Extract again | Identical rows and transaction ids; zero model calls from the engine |
| SC-15 | FR-16, FR-23, FR-28 | Existing statement-accounts and account-import-pdf fixtures (S, S-flag, T, W, C, C0, X, Q, D, K, R, F, V) | Their existing tests | All pass, except those the test contract lists as changed by this spec |
| SC-16 | FR-14 | Statement whose dates all have day ≤ 12 and no printed period | Record | No row recorded; one issue per page says the order can't be told (or OD-2's fallback, if chosen) |
| SC-17 | FR-17 | One PDF with a checking table and a savings table, each chain holding separately | Record | Both tables' rows recorded; one review issue says it may hold two accounts |
| SC-18 | FR-33 | 200+ seeded generated statements | Generator test | Every row exact; every statement reconciles |
| SC-19 | FR-24 | Engine made to raise | Record; PDF import preview | Record uses the model's rows with `REBUILD_FAILED`; import refuses with its message |
| SC-20 | FR-34 | Synthetic eval corpus, with the four aligned-column statements | `python -m evals.run` | Summary shows old reader and engine metrics; engine ≥ old on each; the engine reads the aligned-column statements exactly |
| SC-21 | FR-02, OD-3 | The printed-token table in the test contract | Engine token tagging | Every token gets its expected tag and value; `PPD ID 1234567890` stays text |
| SC-22 | FR-26 | A library whose PDF readings are indexed at the previous analyzer version | Start | The index rebuilds once; the picker shows `indexing: true` until done |
| SC-23 | FR-10, FR-11, R3 | Card statement with foreign amount and rate columns beside the Amount column | Record | Only the Amount column's values are recorded; summary holds |
| SC-24 | FR-08, FR-20, R4 | Card statement with a "Pending transactions" section | Record | Pending rows not recorded, each listed as unplaced; needs review |
| SC-25 | FR-04, R5 | Card statement with transaction and posted date columns, with and without headings | Record | Each row's transaction date and posted date are the printed ones |

## Supersedes
- statement-accounts FR-16 (rows by PDF import's heading rules) → FR-03 – FR-06, FR-18.
- statement-accounts FR-17, FR-18 (values from named cells; direction from named columns or type) → FR-10 – FR-12;
  the type default survives as FR-12's last step.
- statement-accounts FR-19 (year) → kept as written; the date order part → FR-14.
- statement-accounts FR-21 (rejected rows) → kept, extended by FR-08 and FR-15.
- statement-accounts FR-23 (pages without rebuilt rows) → FR-19 (adds the note).
- statement-accounts FR-27 (balance tables by title/heading names) → FR-09.
- account-import-pdf FR-06 (year and date-order choices) → kept, offered only when FR-14 can't decide.
- account-import-pdf FR-07 (sign from columns or account default) → FR-10 – FR-12; the choice survives when undecided.
- account-import-pdf FR-08 (cross-page linking and rebuilt rows) → FR-03 – FR-06.
- account-import-pdf FR-10 (nothing skipped) → kept, made concrete by FR-08.

## Out of scope / product decisions requiring approval
**Open decisions (recommended defaults; reply "defaults ok" to take them all)**
- **OD-1 Rows with no printed date** (one date per day). *Default:* take the date of the row above in the same table and add
  a record note ("Page 2 row 7: no date is printed; it takes 14/10/2026 from the row above"); not a review reason when the
  chain holds. *Why:* that is how these statements are meant to be read, and the chain still proves the amounts.
  Alternative: reject them, as today.
- **OD-2 Date-order fallback** when FR-14 can't decide. *Default:* the order last decided for the same account (by last
  four), then no guess. No new setting. *Why:* stable per bank, and needs no UI. Alternative: a per-account "dates are
  day-first" setting.
- **OD-3 Decimal-comma amounts** (`1.234,56`). *Default:* out of scope; such an amount is rejected as unreadable. *Why:*
  `to_minor` doesn't read it today and none of the reported statements need it. Say if the DD/MM statement prints them.
- **OD-4 Alignment tolerance.** *Default:* amounts belong to one column when their right edges are within 0.75 font sizes.
  The plan may tune it against the generator (FR-33) and record the value.
- **OD-5 Later phases.** *Default:* each of FR-40 – FR-44 gets its own amendment spec and test contract, approved before
  it is built; this approval covers phase 1 only. *Why:* each kind's check and fixtures need their own review.
- **OD-6 Redacted layout probe.** *Default:* the plan includes a script the user runs on their two failing statements. It
  prints only heading texts and each line's shape (`dd/dd/dddd aaaa ddd.dd`), never descriptions or amounts, to confirm
  U1 before the engine is built. Optional; phase 1 doesn't depend on it.

**Domain risks (candidates; only those accepted become requirements — drafted above as FR-13, FR-17, FR-04's second date column)**
- **R1 A wrong assignment that also adds up.** With very few rows, two role assignments can both satisfy the chain.
  Consequence: signs flipped silently. *Default:* FR-13 (decide by the chain only with two or more links, else review).
- **R2 Two accounts in one PDF.** Combined statements print checking and savings tables. Consequence: one account gets both
  accounts' rows, and the balance looks wrong. *Default:* FR-17 (record both tables' rows, one review issue); splitting stays
  a non-goal.
- **R3 Extra amount columns** (foreign amount and exchange rate on card statements, fees). Consequence: a foreign amount
  read as the charge. *Default:* a column that fits no role under the chain or summary is "other" and never an amount; if
  no assignment holds, FR-15 review.
- **R4 Pending or memo rows** printed in a table without being posted (pending authorisations). Consequence: double counting
  when they post next month. *Default:* a row under a "pending" section title is listed as unplaced, not recorded.
- **R5 Two date columns** (transaction and posted). Consequence: the wrong date as posted. *Default:* FR-04 (heading words
  decide; else first is the transaction date and second the posted date).

**Out of scope:** scanned pages and photos; tax form boxes; splitting accounts; decimal commas (unless OD-3 changes);
per-institution templates; any UI change beyond the record notes and review texts named above.
