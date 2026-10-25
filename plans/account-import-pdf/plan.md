# Import account transactions from PDF documents — implementation plan
Spec: specs/account-import-pdf/spec.md (with specs/account-import-pdf/test-contract.md)
Spec sha256: ed41557b825f87577b107abbfcdc04b80ff588f00b786ca15bf7997e1ee99a60
Review-Risk: HIGH
Review-Risk-Rationale: It writes money rows that count toward totals, creates accounts, adds a migration and changes a
public API contract (the import request), so a defect could miscount or duplicate household money.

<!-- Approval lives in approvals/account-import-pdf.json, bound to this file's hash. No Status line.
     Execution progress goes in plans/account-import-pdf/progress.yaml, never in this file. -->

Planned as one feature in three milestones (user decision 2026-10-24, instead of splitting the 30 FRs). Each milestone
can be verified on its own:
- **M1 — import core (backend):** SL-01 to SL-04.
- **M2 — evidence and lists:** SL-05 and SL-06.
- **M3 — dialog and entry points:** SL-07 and SL-08.

The spec bundle was approved on 2026-10-24 with OD-1 to OD-3 open and gaps G1 to G9 flagged. This plan adopts the
recommended default of each open decision. Where a gap needs a design choice, the plan states it (decisions P1 to P9,
below) without changing any expected value in the contract.

## Verified repository integration points

All paths are under `src/home_manager/` unless they start with `tests/` or `docs/`. Line numbers are from commit
`ea79e16` plus the uncommitted tree at planning time.

| Area | Where | What this plan uses |
|---|---|---|
| Format routing | `core/formats.py:5–8` `TABLES = {".csv", ".xlsx"}`, `TEXT_READERS` includes `.pdf` | Unchanged: a PDF stays a text document (FR-01). PDF import is routed by extension inside the ledger, not by adding `.pdf` to `TABLES` |
| CSV import | `finance/ledger.py:1065–1105` `table_rows`, `preview_import`, `import_transactions` | Untouched for `.csv`/`.xlsx`. A `.pdf` branch dispatches to the new PDF functions before `table_rows` raises "supports CSV and XLSX" (`:1078`) |
| Insert and dedupe | `ledger.py:424–451` `insert_transactions` (`INSERT OR IGNORE` on fingerprint; a duplicate gets evidence, and `statement_id` through `coalesce`) | Reused. Gains an optional `fingerprints=` argument (see P3) |
| Fingerprint | `ledger.py:299–305` `fingerprints(account_id, rows)`: ordinal among equal (date, amount, currency) in the order given | Computed over all parsed rows of the selected tables, before unticked rows are dropped |
| Counting | `ledger.py:39–43` `HELD`, `COUNTABLE` | Unchanged. Import rows count unless rejected; extraction rows stay held while `awaiting` |
| Accounts | `ledger.py:363–398` `account_in(db, …)`: find-or-create inside the caller's transaction; rejects anything but 4 digits | Used for FR-14 inside the import's own connection. Existing identical accounts are reused (P6) |
| Statement publish | `ledger.py:953–1000` `publish_statement`: matches the account by institution + last four, and keeps rows with non-extraction evidence on a re-read (`:977–980`) | FR-18 already works at the ledger layer. SL-04 proves it with tests, without changing it |
| Review | `ledger.py:1110` `review(record_type, id, status)`, `POST /api/finance/records/{type}/{id}/review` (`app/api.py:1356`) | How the user rejects a row (J1 step 7) |
| API | `app/api.py:296–301` `ImportInput` (strict, `extra="forbid"`), routes `:920–933` | `ImportInput` gains optional PDF fields. CSV bodies validate as before |
| Manager | `app/manager.py:1439–1444` `import_transactions` (refuses while non-inference work runs, then reconciles) | Passes the new fields through. Reconciliation stays after commit |
| Reading | `library/storage.py:539–540` `text_run_id` (latest `succeeded`/`partial` parse run for the current hash); `documents/receipt_service.py:82–98` `get`, `:130–160` `publish` (the folder's `result.json` is validated against `blob_hash`) | The reading is resolved by `text_run_id`. Its integrity is re-checked at import (FR-22) |
| PDF evidence | `documents/pdf_layout.py:66–72` `PDFTable` (rows 2–500, columns 2–40, `header_rows=[0]`), `:520–527` table emission | Native tables only. **Verified:** no table is emitted when page issues include `overlapping_text`, `unsupported_text_rotation`, `glyph_outside_page` or `unicode_mapping` (`:520`). Tables can coexist with `degenerate_glyph`, `possible_image_content`, `insufficient_native_text` and `unresolved_columns` |
| Page issues | `documents/pdf_reader.py:76–78` (`pdf_layout_review`), `:101–105` (`pdf_table_ambiguous`) | The flagged-page rule (FR-09) reads these from `PDFResult.issues` by page number |
| Mapping helpers | `finance/tabular.py:27–34` `HEADER_NAMES`, `:197` `detect`, `:205` `date_order`, `:221` `parse_date`, `:238` `spreadsheet_amount`; `core/money.py:32` `to_minor` | `HEADER_NAMES`, `detect` and `to_minor` are reused. `date_order`/`parse_date` accept only 4-digit slashed or ISO dates, so `pdf_import` has its own date-shape parser for `MM/DD`, `MM/DD/YY` and `MM/DD/YYYY`, using the same order rule (pass-2 INFO). `tabular.py` is not modified (FR-01) |
| Status filters | `storage.py:24–31` `TABLE_FILE`, `WORK_FILTERS`; `:545–563` `ledger_status` (`imported` once any `transaction_imports` row exists for the hash) | `ready_for_ledger` is adjusted for PDFs (P5) |
| Provenance | `finance/provenance.py:93–98` (imports read only `locator.rows`), `app/api.py:1462` `GET /api/provenance/{type}/{id}` | Extended for PDF locators (FR-24) |
| Trace badge | `app/static/trace.js:183` `Imported · {file} row {row}` | Gains the page form, and a link to the document page |
| Document page | `app/static/document_v2.js:40–47` (`?lines=` highlights ids, cell ids included through `trace.js:361, 435`), `:273–310` `doc2Steps` | The provenance link target, and the primary action (FR-26) |
| Library row | `app/static/records_v2.js:455–470` `rc2Step`, `:491–502` `rc2Menu`; `library.js:9` `isTable` | Next step and More actions (FR-26) |
| Import dialog | `app/static/library.js:151–218` `openImport`, `previewImport`, confirm handler; `index.html:1128–1151` `#import-dialog` | Gains a PDF mode (FR-28) |
| Picker | `app/static/money_v2.js:78–113` `importPicker` (`limit=200`, then filtered to `.csv|.xlsx`) | Uses a new candidates endpoint (FR-25) |
| Migrations | `library/migrations/070_document_forms.sql` (latest, `user_version=70`), `tests/test_migrations.py:357` pattern | Migration 071 |
| Test helpers | `tests/test_pdf.py:17` `make_pdf` (positioned items, `crop`, `rotation`; no images), `tests/test_pdf_layout.py:15`, `tests/test_imports.py:118` (API pattern), `tests/conftest.py:117` `local_model`, `tests/test_transactions_v2_browser.py` (`served`, `RUN_BROWSER_TESTS`) | Reused. `make_pdf` gains an optional image object (SL-01) |
| Connections | `storage.py:241–251` opens a new SQLite connection per `connection()` | So the contract's fault double must be a **permanent** trigger, created and dropped by the test. A TEMP trigger would not be seen by the import's connection |

**Verified facts that shaped the design:**
- **The contract's first flagged-page trigger yields no table.** A glyph outside the page raises `glyph_outside_page`,
  which suppresses table emission (`pdf_layout.py:520`). That would leave nothing to untick. SC-08 therefore uses
  `possible_image_content`, a page with a small image object (`pdf_layout.py:315–316`), which keeps the table. The
  contract's P-check explicitly allows another real trigger, and no expected value changes. `make_pdf` needs an image
  option for this.
- **Fingerprint ordinals depend on which rows are passed in.** If unticked rows were dropped before fingerprinting, k2
  (same day and amount as k1) would take k1's ordinal 0 whenever k1 is unticked, and be reported as a false duplicate.
  So fingerprints are computed over every parsed row in document order (P3).
- **`account_in` already finds or creates** by institution, type and last four (`ledger.py:383`). Spec risk R5 (an
  identity collision raising a raw constraint error) therefore can't happen through this path. An identical account is
  reused.
- **`publish_statement` matches the account by exact institution text** (`find_account`, `:399`). Import-then-Record
  (FR-18) de-duplicates only when the statement's institution and last four match the import account's. The contract's
  `A` (FIRST LOCAL BANK) and S-K agree. A mismatch in real use would create a second account and duplicate rows. This
  existing Record behavior is out of scope (spec non-goal), and is listed under Risks.
- **The reader builds no table for a headerless page (G1/U2, checked 2026-10-24).** This was confirmed by reading
  `table_grid` (`pdf_layout.py:421–440`: it returns None when row 0 holds a number; its docstring says "Headerless …
  candidates stay text with a review issue"). A throwaway reader run on synthetic K pages, in the new Linux `.venv`
  (Python 3.13.12), agreed:
  - a headed page whose amounts are right-aligned, with every column filled, gave a native 5×4 table;
  - the same rows with no headings gave no table and `unresolved_columns`;
  - a headed page with Deposits blank on every row also gave no table;
  - one narrow spacing gave a wrong 2-column table.

  FR-08 was amended so the import rebuilds such rows from saved word geometry (below).

## Architecture, contracts, data flow and decisions

### Data flow

```
saved reading (parse_runs.result_json + run folder result.json)
  └─ pdf_import.analyze(reading, choices)                       pure, deterministic, no DB
       ├─ classify native tables per page: transactions / other
       ├─ group saved words into visual rows; find transactions headings among them where no native one exists → rebuilt tables
       ├─ rebuild continuation-page rows from saved words with the continued table's columns (FR-08)
       ├─ rebuild the rows below a native transactions table that the reader cut short, with its columns (P13)
       ├─ map columns, drop balance columns, parse dates, amounts and currency
       ├─ tick rule (flagged pages), issues, counts and limits
       └─ last-four candidates and document currency
  └─ Ledger.preview_pdf_import(...)   reads only; adds account match, sign default, row status (New / Already recorded / Rejected)
  └─ Ledger.import_pdf_transactions(...)
       one connection, one transaction: [new account] → insert_transactions(origin='import') → transaction_imports row
  └─ Manager: reconcile after commit (as for CSV)
```

### New module: `finance/pdf_import.py`

`analyze` and the parsing helpers are pure (no DB, no store). The index functions added in SL-06 (`index_row`,
`index_quietly`, `pending`, `backfill`) are the only parts that touch the database (pass-2 m-7).

- `analyze(result: PDFResult, *, tables=None, year=None, date_format="auto", sign=None, account_type=None,
  currency) -> Analysis`. It doesn't touch the store.
- `Analysis` contains:
  - `tables`: one entry per native table and per rebuilt table, with `id`, `page`, `kind` (`transactions`,
    `rebuilt`, `continuation` or `other`), `linked_to` (table id), `headings`, `columns`, `rows`, `selected` and
    `selectable`.
    - A rebuilt table's id is `page-N-import-table-K`.
    - A continuation page's rows form a `continuation` entry, `page-N-import-continuation`, linked to the table it
      continues.
  - `rows`: one entry per data row of the selected tables, with these fields:
    - `key` = `"<table_id>:<row>"`, `page`, `table_id` and `row` (for rebuilt and continuation rows, `row` counts the
      rows on that page from 0; below-table rows instead continue the native table's numbering, P13);
    - the as-printed `date`, `description` and `amount` cell texts;
    - `posted_date`, `amount_minor`, `currency`;
    - `ticked`, `labels` (`continued from page N`, or the page issue message), `rejected` (a reason or null);
    - `cell_ids` (native rows), `line_ids`, and `word_ids` (rebuilt rows).
  - `issues`: each with `page`, `row` (optional), `code` and `message`, capped at 200.
  - `counts`: `seen`, `parsed`, `rejected`, `left_out`, `pages_without_rows`.
  - `required`: the subset of `year`, `date_format` and `sign` that must still be chosen.
  - `mapping`: the column per role.
  - `last_fours`: each distinct NNNN found, with the page of its first occurrence.
  - `document_currency`.
- **Table classification and rebuilt rows (FR-08 as amended twice; revised after review pass 4):**
  - **Why visual rows.** On pages without a native transactions table, the reader cuts each region at gaps wider than
    2.5 × the font size and saves each side as its own lines (`pdf_layout.py:504–517`). X page 2 is saved as
    `'09/03/2026 B1'`, `'1.00'`, `'1,009.00'` …. A blank-column heading page gives a wrong native `Date | Description`
    table, with the amounts as separate lines (verified by the planner on synthetic pages, 2026-10-24). Saved lines and
    those tables therefore can't be used as rows. `analyze` regroups the words.
  - **Visual rows.**
    - For each `embedded_text` page, the saved `layout.words` are grouped into visual rows by baseline. A word's
      baseline is its first character's saved `origin`, mapped through `layout.page_to_preview`. A word with no origin
      uses the bottom of its box (`pdf_layout.py:334`).
    - A new row starts when a word's baseline differs by more than 0.25 × the page's font size from the baseline of
      the **first** word of the current row, as the reader compares against the row's first glyph (`:337`). The font size is the
      median saved `font_size` × the transform's scale, as at `:332`.
    - Words in a row are ordered by their left x.
    - This re-implements about 10 lines of `reconstruct`, which is a closure that can't be imported without changing
      the reader.
  - **Heading texts.** A visual row's words are grouped into texts by the reader's gap rule: a new text when the gap
    exceeds 1.5 × the font size (`:375–386`, re-implemented).
    - A row whose texts include a `HEADER_NAMES["date"]` name and an `amount`, `debit` or `credit` name is a
      **transactions heading**. Matching is stripped and lower-cased, and multi-word names match within one text.
    - Unit tests pin both re-implementations. On every native table in the fixtures, the visual rows must equal the
      table's rows, and the heading texts must equal its header cells.
  - **Native tables.**
    - A native table whose row 0 is a transactions heading is a `transactions` table. Its own rows are used, as the
      reader built them.
    - **Rows below a native table (P13, after the SL-01 gate).** The reader keeps the longest prefix of rows that forms a table
      (`emit`, `pdf_layout.py:494–498`), and a table needs an alphabetic label on every body row (`table_grid`,
      `:435–440`). So a row with a blank description ends the native table. The
      rows after it stay loose lines, and the page gets only `unresolved_columns` (fixture V: the native table is the
      heading, v1 and v2; v3 to v5 are loose lines; verified by the SL-01 worker and the planner on 2026-10-24).
      - So on a page with a native `transactions` table, the visual rows whose baseline is below the table's last row
        form its **below-table region**. The region ends at the page's next native transactions table, if any.
      - A visual row in the region that is a transactions heading ends the region, and adds the issue `Page N: rows
        after a second transactions heading on this page were not read.` Those rows are reported, not guessed.
      - A visual row in the region that meets the candidate rule (below) is a **below-table candidate** row. It uses the native table's columns (from its row-0 cell words) and the same candidate, accept and
        reject rules as rebuilt rows (below).
      - Below-table rows belong to the native table's entry, with its `table_id`. Their `row` numbers continue after
        the table's last native row (V: v3 is row 3, v4 row 4, v5 row 5). They are ticked, labelled and counted like
        the table's own rows, and they get no extra label.
      - They are cited like rebuilt rows (`word_ids` and `line_ids`, no `cell_ids`; see "Evidence"). Everywhere this
        plan says "rebuilt rows" about evidence, locators or links, below-table rows are included. Row numbering is
        the exception: it follows the bullet above.
      - A page with a native transactions table is still not a continuation page, and the next page's continuation
        rules are unchanged.
    - Any other native table is `other`, unless its words share baselines with the rebuilt table's heading or with one
      of its candidate rows (accepted or rejected, below), or with a below-table **candidate** row (accepted or
      rejected) of a native transactions table (P13). (Spec FR-08 says "shares a line" here; it means a baseline, as
      in its rebuilt-table sentence, because loose words sit in their own saved lines. Pass-7 m-1.) Sharing a baseline with any other visual row lower on the page
      is not enough. Such a table is absorbed into the rebuilt table, or the native table's below-table rows, and is
      not listed (review pass 4, BLOCKER-2: the wrong `Date | Description` table on K page 1; pass-5 INFO).
    - An `other` table that shares no baselines (Summary, Fee summary) is listed as `not a transactions table`
      (FR-04). That includes a Summary printed below a native transactions table (pass-6 MAJOR-2).
  - **Rebuilt tables.** On a page with no native `transactions` table, the first visual row that is a transactions
    heading starts a `rebuilt` table. Only visual rows **after** the heading are candidates, so title and
    statement-period rows above it never are.
  - **Column positions** come from the heading texts' boxes, or from a native transactions table's row-0 cell words.
    - Each span runs from the midpoint after the previous heading to the midpoint before the next. The first and last
      spans are open to the page edges.
    - A word goes to the span holding its horizontal centre. It straddles when its box crosses a midpoint by more than
      20% of its own width.
  - **Rows (revised after pass-5 MINOR-1).**
    - A word is **date-like** when it fully matches one of FR-06's printed shapes, `\d{1,2}/\d{1,2}(/\d{2}|/\d{4})?` or `\d{4}-\d{2}-\d{2}`, and **amount-like** when,
      after an optional leading `-`, `+` or `(` and currency symbol and an optional trailing `)`, `-`, `CR`/`DR` or
      three-letter code, it starts with a digit and holds only digits, `,` and `.` (so `1.2.3` is amount-like, and
      contract V's v4 becomes a candidate that is rejected as an unparseable amount). Whether the text parses is decided
      later (FR-06, FR-07), never by these shapes.
    - A visual row is a **candidate** when it has a date-like word that falls in, or straddles, the date span, and an
      amount-like word that falls in, or straddles, an amount, debit or credit span. A Balance-only amount doesn't make
      a candidate.
    - A candidate is accepted when its date and its amounts each sit wholly inside one span, and each amount column
      holds at most one amount-like word and no other text. One three-letter upper-case code word directly after the
      amount, in the same span, is part of the amount cell, not other text (Keur prints `4.50 EUR` as two words,
      checked by the planner on the SL-01 fixture, 2026-10-24). Its currency is then judged by FR-11.
    - Otherwise it is **rejected**, with page, row and reason: the date or amount straddles (contract 7-d), or an amount
      column holds two amount-like words or other text (7-e). A rejected candidate counts in `seen` and `rejected`
      (FR-10).
    - The spans are open to the page edges, so no word is ever outside every span.
    - Visual rows that aren't candidates (titles, footers, totals text, a row with a date and only a Balance amount, the
      second line of a wrapped description) are not rows, and aren't counted.
    - Nothing is joined or guessed.
  - **Continuation pages.** A later `embedded_text` page with no transactions table of its own continues the nearest
    earlier transactions table (native or rebuilt), as long as no other transactions table lies between them. All of
    its visual rows are candidates, with that table's columns.
    - The rows are labelled `continued from page <heading page>`, and are ticked and counted like the continued
      table's.
    - A new transactions table ends the chain (contract 7-b).
    - A scanned page in between doesn't break the chain. It reports itself and contributes nothing (FR-03).
  - **Evidence.** A rebuilt row (including a continuation or below-table row) cites its `word_ids`, and as `line_ids` every saved line its words fall in (through
    `PDFLayoutLine.word_ids`). Contract SC-22 highlights them all.
  - **No rows.** A continuation page with no rows, or a page with neither a native nor a rebuilt transactions table,
    is reported `Page N: no transactions table found`.
  - **Determinism.** The rebuild uses only saved geometry, so the same reading always gives the same rows (FR-12).
- **Balance columns (OD-2 default, PDF only):** a heading equal to `balance`, `running balance`, `new balance` or
  `ending balance` is never mapped to amount, debit or credit.
- **Dates (FR-06), revised after review M1:**
  - Day/month order is decided **once**, across all rows of the selected and linked tables: the `date_order` rule
    (`tabular.py:205`), applied to every printed date shape (`MM/DD/YYYY`, `MM/DD/YY`, `MM/DD`, ISO). Deciding per
    table would make K's page-1 table ambiguous on its own.
  - When no day or month value is above 12, `date_format` is required. A year-less date is never assumed to be MM/DD.
  - A four-digit year is read as printed.
  - Year-less and two-digit-year dates need `year`. Rows are walked in document order. The year starts at the chosen
    one and advances by 1 each time a month is lower than the previous row's.
  - Two-digit years (G4, P1): a printed `YY` that disagrees with the computed year rejects the row with a reason.
  - An impossible date rejects its row, with the date named.
  - The current year is never used.
- **Amounts (FR-07):** `to_minor`.
  - With Debit/Credit columns: debit → `-abs`, credit → `+abs`, and both filled → rejected.
  - With a single Amount column, the sign is `sign`, else the default for `account_type`: `credit_card` →
    `positive_is_outflow`; `checking` or `savings` → `negative_is_outflow`; any other type, or no account →
    required.
  - A blank description, an unparseable amount, or a cell over 2,000 characters → rejected, or a limit refusal
    (FR-21).
- **Currency (FR-11):**
  - `document_currency` (revised after review M3) is the code on a printed `Currency: XXX` line, or the one code that
    **every** amount cell of the selected tables carries. Otherwise it is null.
  - A code printed on only some rows is a row-level code, and rejects only its own rows.
  - A printed code different from the account's rejects that row. A document-level code different from the account's
    sets the blocking issue `document_currency_mismatch`.
- **Flagged pages (FR-09, as amended):** a page with a `pdf_layout_review` or `pdf_table_ambiguous` issue in
  `PDFResult.issues` → its rows have `ticked=false` and are labelled with that issue's message.
  - The exception (user decisions after passes 4 and 5): a `pdf_layout_review` whose `layout.issues ==
    ["unresolved_columns"]` is not a flag on a page that holds a transactions table, native or rebuilt, or on a
    continuation page.
    - The reader raises that issue for every headerless page (`pdf_layout.py:516, 531`), and for text outside a complete
      native table. A `Page 1 of 3` footer is enough, as verified by the planner on a synthetic page on 2026-10-24.
    - Such an issue is not added to `Analysis.issues`, and doesn't label rows (pass-5 MINOR-3; J1 step 3 expects an
      empty issue list). Contract variant 8-a covers a native page with that footer.
  - Any other layout issue (`possible_image_content`, `degenerate_glyph` …) still flags the page (contract SC-08).
- **Readings without native layout (pass-2 m-6):** `pdf-pages-v1` and `v2-tables` readings have `layout = None`.
  Such a reading gives the single blocking issue `This PDF was read before transaction import existed. Read this
  document again to import its transactions.` It isn't indexed as importable.
- **Scanned pages (FR-03):** every `vision_model` page adds the issue `Page N is a scanned page; no rows imported. Use
  Record for scanned statements.` and contributes no tables.
- **Limits (FR-21):** more than `MAX_ROWS = 20_000` data rows across the selected tables, or a cell over `MAX_CELL =
  2_000` characters, raises `PDFImportError` naming the limit. Issues are capped at 200, and the counts stay exact. The
  constants are module-level, so the API test can lower `MAX_ROWS` (contract SC-16 as amended). No real reading can
  reach 20,000 rows.
- **Last four (FR-13 patterns):** the regexes for `ending in NNNN`, `ending NNNN`, `[Xx*•]{2,}NNNN` (with optional
  spaces or dashes), `*NNNN` and `…NNNN` (or `...NNNN`) run over the native page text only.
- **Identity (FR-10):** `seen == parsed + rejected` and `left_out == unticked parsed rows` hold by construction.
  The import's `inserted + duplicates + rejected + left_out == seen` is asserted in tests.
  - A row matching an existing **user-rejected** transaction counts as a duplicate (it isn't inserted), and is also
    reported in `rejected_earlier` (pass-2 m-5).
  - `rejected` means rows the import itself rejected (bad date, amount or currency). J1 step 7 is therefore
    `inserted 0, duplicates 9, rejected_earlier 1` ("the other 8" are the duplicates without that flag).

### Ledger (`finance/ledger.py`) additions

- `pdf_reading(db, document_id, digest, reading_id=None) -> (document, version, run, PDFResult)`. In order, it:
  - refuses Trash (`Restore the document from Trash before importing it.`);
  - checks that `expected_hash` is the **current** version, which `document_version` alone doesn't check (P8);
  - re-hashes the blob (the integrity message);
  - resolves `text_run_id`, and if there is none: `Read this document first.` (FR-27);
  - when `reading_id` is given and differs: `This document was read again since the preview; preview again.`;
  - loads `result_json` and the run folder's `result.json`, and parses **both** with the same function, `read_result`
    (`pdf_reader.py`; it applies `restore_text_tables` to each, which addresses review minor 1). The two must be equal
    after `model_dump`, and `input_hash` must equal `version.hash`. Otherwise it fails with the integrity message
    (FR-22). The folder file is size-checked against `PDF_EVIDENCE_BYTES` before it is read, as `publish` does.
  - It never opens the PDF bytes beyond the hash (FR-02).
- `pdf_refusal(db, hash) -> str | None` (FR-19): a non-rejected `receipts` row (receipt kind → "receipt"; bill
  → "bill"), an `income_records` row → "pay stub", or another non-account record (asset, investment, tax form) → "<that
  kind>" gives `This PDF is recorded as a <kind>.`. A statement, or no record, gives none.
- `account_match(db, last_fours, document_currency)` (FR-13):
  - The document currency is `document_currency or household.home_currency or "USD"`, the established fallback
    (`manager.py:1967, 2024`; decision P2).
  - Candidates are the active accounts whose `currency` equals it and whose `account_last_four` is in `last_fours`.
  - Exactly one candidate → `{account_id, text: "Matched …NNNN printed on page N"}`. Otherwise null.
- `row_status(db, account, rows, fingerprints)` (FR-16, FR-17), with no writes:
  - a fingerprint that isn't found → `New`;
  - an existing row with `review_status='rejected'` → `rejected earlier`;
  - otherwise the source comes from the existing row's `origin` and its earliest evidence link:
    - `import:` → `Already recorded from import <file>`;
    - `extraction:` → `Already recorded from statement <file>`, or `Already recorded from this statement` when that
      link's `blob_hash` is this document's (contract SC-11 and SC-15 Ps);
    - A fingerprint never matches a manual row, because manual rows store `manual:<uuid>` (`ledger.py:481`). The label
      is computed **from the manual entry's side, by `replace_manual`'s own rule** (revised after pass-2 MJ-1).
      - `reconcile.manual_candidates(db, manual, extra=())` is a new read-only helper, extracted from `replace_manual`
        (`reconcile.py:707–712`). For one manual entry it returns its candidate lines: countable, non-manual, same
        account, currency and amount, posted within ±`RECEIPT_POSTING_DAYS`, and not already claimed (`replaced_by`).
        `extra` adds hypothetical lines. `replace_manual` calls it with no `extra`, so its behavior is unchanged.
      - The preview calls it for each un-replaced manual entry in the account, passing this preview's ticked New rows
        as `extra`. A row is labelled `replaces a manual entry` only when it is that entry's **single** candidate.
      - So two equal New rows (k1/k2 against a manual −4.50 on 08-03), or an existing matching line, label nothing.
        That is exactly the case where `replace_manual` replaces nothing.
      - The replacement itself happens in the reconciliation pass after commit (FR-17 as amended). A test variant (10-b,
        added to SL-04's test without changing the contract) covers the two-candidate case: no label, no replacement,
        and the existing counting is unchanged.
  - When the existing row isn't counted (`extraction`, not verified or held), the message adds `; not counted until you
    reconcile it.`
- `preview_pdf_import(document_id, digest, *, account_id=None, new_account=None, currency=None, tables, year,
  date_format, sign, ticked=None, unticked=None)` returns the structure below.
  - The preview takes `account_type` and `currency` on their own (not the full `AccountInput`), so a partly typed new
    account still updates the sign default, totals and currency checks (FR-15, review M6, pass-2 m-4).
  - Only the import requires a complete `new_account: AccountInput`.
  - **No account and no currency is valid for a PDF** (pass-3 MINOR-1). `api.py:924–926` raises `Choose an account or
    a currency for the preview.` for that case; the route skips that check for `.pdf`. The rules:
    - The currency is the account's, else the request's `currency`, else `document_currency`, else `home_currency or
      "USD"` (P2).
    - Row statuses and totals use the request's `account_id`, else the single `account_match`, else every parsed row
      is New. This is J1 step 3 (no account sent, `A` matched) and SC-04 (no accounts).
  - Nothing is created.
  - `{"kind": "pdf", "reading_id", "tables", "rows" (all, each with status, display amounts and ticked), "issues",
    "counts", "required", "blocked" (reason or null), "totals" {inflow, outflow} for ticked New rows,
    "already_recorded_totals", "account_match", "new_account_last_four" (one distinct NNNN or null), "sign_default",
    "mapping"}`.
  - It writes nothing (FR-05).
- `import_pdf_transactions(document_id, digest, *, reading_id, account_id=None, new_account=None, …same choices)`:
  - It refuses (`ValueError`) unless `required` is empty, nothing is `blocked`, and exactly one of `account_id` and
    `new_account` is given.
  - In **one** `store.connection()`:
    1. the integrity checks again;
    2. `account_in(db, …)` when `new_account` is given;
    3. `insert_transactions(db, account, ticked_parsed_rows, "import", source, fingerprints=…)`;
    4. the `transaction_imports` row.
  - `source_key = "import:<uuid hex>"`, `parse_run_id = reading_id`. Each row's locator is `{"document_id", "blob_hash",
    "reading_id", "page", "table_id", "row", "cell_ids" (native rows) | "word_ids" (rebuilt rows), "line_ids",
    "continued_from"?}`.
  - The `transaction_imports` row reuses the existing columns: `mapping_json` holds `{"kind": "pdf", "reading_id",
    "tables": [{id, page, linked_to}], "mapping", "year", "date_format", "sign", "ticked": [...], "unticked": [...],
    "left_out": n}`, and `issues_json` holds the issue list. No new columns (P4).
  - It returns `{import_id, account_id, account_name, inserted, duplicates, rejected, left_out, pages_without_rows,
    issues, duplicate_sources}`.
- `insert_transactions(..., fingerprints=None)`: when given, the precomputed fingerprints are used in place of
  `fingerprints(account["id"], rows)` (P3). There is no behavior change for existing callers.
- `preview_import`/`import_transactions` dispatch `.pdf` to the functions above. The CSV/XLSX path is byte-for-byte
  unchanged.

### API contract (additive)

- `ImportInput` gains these optional fields: `account_type` (preview only, with `currency`), `reading_id: str` (32 hex), `tables: list[str]`, `year: int`
  (1900–2100), `date_format` (`auto` or a `DATE_FORMATS` value), `sign` (`negative_is_outflow`,
  `positive_is_outflow`, or null for "not chosen"), `ticked: list[str]`, `unticked: list[str]`, and
  `new_account: AccountInput`. `new_account` reuses the existing model (`api.py:287–293`), so a 6-digit last four is a
  422, as for CSV (contract SC-06 step 4).
- It stays `strict`, with `extra="forbid"`. CSV requests are unchanged.
  - For a PDF, `mapping` must be null (400 `Column mapping applies to CSV and XLSX files.`). The top-level `date_format`
    and `sign` are its only sources, because `ImportMapping.sign` defaults to `negative_is_outflow` and couldn't express
    "not chosen" (review minor 3).
  - For CSV/XLSX, the PDF fields must be absent (400).
- `POST …/transaction-imports` keeps its 400 `Choose the account these transactions belong to.` when neither
  `account_id` nor `new_account` is given.
- Refusals are `ValueError` → 400, through the existing handler (`api.py:644`).
- `GET /api/finance/import-candidates` (new, SL-06) returns `{"items": [{document fields…, "import_kind": "csv"|"xlsx"|"pdf"}]}`:
  - CSV/XLSX files that are `ready_for_ledger`;
  - PDFs whose current reading has at least one transactions table and that `pdf_refusal` doesn't refuse.
  - It filters before limiting, sorts by added (newest first), and is capped at 500 **after** filtering.
- Document listing rows gain `pdf_import`, either `{"tables": n, "match": {"account_id", "last_four", "page"} | null,
  "refused": "<kind>" | null}` or null (no indexed reading).
  - It is computed **on the server** from the index row, the active accounts, `pdf_refusal` and the `home_currency or
    "USD"` fallback, so the client copies no rule (review minor 4: `ledger_kind` carries only `bill`).
  - The FR-26 primary rule is `tables > 0 && match && !refused`.

### Import index (migration 071, SL-06)

- `pdf_import_index(parse_run_id TEXT PRIMARY KEY REFERENCES parse_runs(id) ON DELETE CASCADE, analyzer_version INTEGER
  NOT NULL, transactions_tables INTEGER NOT NULL, last_fours_json TEXT NOT NULL, document_currency TEXT, error TEXT, created_at
  TEXT NOT NULL) STRICT`.
- This is derived data, rebuildable from the reading. It follows the text index's pattern (review M7):
  - `pdf_import.index_quietly(store, run_id)` is called beside `text_index.index_quietly` in `ReceiptService.publish`
    (`receipt_service.py:140`). A failure is logged and never fails the reading.
  - `index_row` always writes a row, even when analysis raises: `transactions_tables = 0` and an `error` text column.
    The backfill therefore never stops at a bad reading, and `pending` can't loop on it (pass-2 m-1). The table gains
    `error TEXT`.
  - `pdf_import.pending(db)` and `backfill(store, work)` are submitted from `Manager.open_library` beside the text-index
    backfill (`manager.py:1149–1152`). They cover readings saved before this feature, and any reading whose
    `analyzer_version` is old (FR-08, last sentence).
  - Until the backfill finishes, the candidates endpoint returns `"indexing": true`, and the picker says `Still
    checking older PDFs …`, so a short list is never silent.
- It holds no money and no row data, only counts, last fours and a currency code.

### UI (SL-07, SL-08)

**Import dialog in PDF mode (FR-28),** when `isPdf(doc)`:
- The worksheet and column-mapping controls are hidden. New controls are added:
  - a table list (checkboxes for selectable tables, plain text `not a transactions table` for the others);
  - a year select, shown when `required` includes `year`;
  - the date-order select (the existing one);
  - a sign select, showing the default as selected, with an empty "Choose…" option when there is no default.
- The rows table shows these columns: Page, Date as printed, Description, Amount as printed, Signed amount, Status and
  a tick checkbox (labels in the row).
- The account select starts from `account_match`, not localStorage (FR-13). It is empty when there is no match, and
  the match text is shown.
- With "New account…", the last four is prefilled from `new_account_last_four`. Confirming sends `new_account` in the
  import request, with no separate `POST /api/finance/accounts` (FR-14).
- Import is disabled while `required` is not empty, while `blocked` is set, or while no account or new account is
  chosen.
- Every change re-previews (FR-15). Status goes to the existing `#import-status` live region, and focus returns to
  the opener.
- **Unread PDF:** the dialog shows `Read this document first` and a Read button, which calls the existing
  `POST /api/documents/{id}/receipt-runs` (OD-1 option a). It then polls the run until it is terminal, and re-previews in
  place. Failures show the server's message (FR-27).

**Primary action (FR-26, OD-3), library row and document page:**
- **Import transactions** is primary when all hold:
  - `doc.pdf_import?.tables > 0`;
  - exactly one active account matches by last four and currency;
  - `pdf_import.refused` is null (the server sets it from `pdf_refusal`, which covers receipt, bill and pay stub).
- Otherwise the existing step stays (Read or Record). When a reading with a transactions table exists, an Import
  transactions item is added to More actions, and a secondary button beside `Record it` on the document page.
- `rc2Step` treats `ledger_status === "imported"` on a PDF as recordable (Record is still offered). The badge stays
  `imported`.

**Trace badge (FR-24):** `Imported · <file> page N` plus `continued from page M` when present. It links to
`#/documents/<id>?lines=<cell_ids>`, or `?lines=<line_ids>` for rebuilt rows (these highlight in `trace.js:435`).

### Decisions this plan makes (each needs no spec change except P13; all are listed for plan approval)

| ID | Gap | Decision |
|---|---|---|
| P1 | G4: two-digit years | A two-digit year is treated as year-less, so the user must choose the year. After the rollover walk, a printed `YY` that disagrees with the computed year rejects the row with a reason. The contract asserts only "blocked until chosen", and this conservative rule never guesses. |
| P2 | FR-13: the document's currency when none is printed | `household.home_currency or "USD"`, the fallback already used by the forecast and dashboards. This is what makes contract SC-05 step 1 hold. |
| P3 | Fingerprint ordinals with unticked rows | Fingerprints are computed over all parsed rows of the selected tables in document order, and passed into `insert_transactions`. So unticking a row never changes another row's identity. |
| P4 | FR-23: what the import record keeps | It is stored in the existing `mapping_json` and `issues_json`, with `kind: "pdf"`. No columns are added to `transaction_imports`, and CSV records are unchanged. |
| P5 | FR-01 and FR-18: `ready_for_ledger` once a PDF is imported | A PDF counts as ready for the ledger while it has no statement, receipt or income record, even after a PDF import. The filter becomes `(TABLE_FILE AND ledger_status IS NULL) OR (NOT TABLE_FILE AND text_run_id IS NOT NULL AND (ledger_status IS NULL OR ledger_status='imported'))`. For PDFs this is the same set as before the feature, because no PDF could previously be `imported`. CSV/XLSX are unchanged. |
| P6 | R5 (not accepted): a new account identical to an existing one | `account_in` reuses the existing account, as it already does for Record. There is no raw constraint error, and the summary names the account. |
| P7 | G6: an import that yields 0 rows | It is allowed only when it records something: 0 ticked New rows plus at least one duplicate writes the import record (FR-20). With 0 rows seen, the import is refused with `Nothing to import: <reason>` (FR-29) and nothing is written. |
| P8 | G3: document replaced after the preview | `store.document_version` accepts **any** earlier version of the document (`storage.py:800–809`), so it can't detect this. `pdf_reading` adds an explicit check that `expected_hash == document["current_hash"]`, and refuses with "This document changed since the preview; preview again." (new text). The contract asserts only refusal with no write. |
| P9 | G5: the transaction source UI | The existing trace input badge (`trace.js:183`, shown wherever a total's trace lists its transactions, e.g. Spending) is the source panel. No new Transactions-page panel is added. |
| P10 | Review M1: date order for fixtures with no value above 12 | FR-06's existing rule applies (a required choice). The tests for X, F, M, V, D-full and D-2y send `date_format = MM/DD/YYYY` (contract fixture rules, as amended). |
| P11 | INFO from review: ordinals across tables | Fingerprint ordinals are computed over the **selected** tables, so deselecting a table can renumber same-day, same-amount rows in later tables. This is accepted. It matches CSV, whose ordinals are over the parsed rows, and the preview shows the resulting statuses before Import. |
| P12 | INFO from review: Today's "ready to record" | Under P5, an imported-only PDF stays in Today's "ready to record" count (`finance/dashboard.py:106`). That is intended, because Record is still the next step for checking balances (FR-18, R3). |
| P13 | SL-01 gate (user decision 2026-10-24, option 1): a native table the reader cut short | Visual rows below a native transactions table's last row are rebuilt with its columns as below-table rows (see "Rows below a native table"), so no printed row with a date and an amount is dropped without a report. This is how contract SC-25 gets 5 rows from V, and it applies to any real statement with a row that has no alphabetic description. FR-08's rules for candidates, acceptance and rejection apply to these rows unchanged, and no expected value in the contract changes. Spec amended for it (pass-6 MAJOR-1): FR-08 and Terms, FR-05, FR-24 and R1 name below-table rows; re-approved ed41557b825f. |

G7 needs no decision: `insert_transactions` already truncates descriptions to 500 characters (`ledger.py:436`). The
contract only asserts ≤ 500. G8 (FR-15's reference to FR-13's totals) is read as FR-05's totals, as the contract does. G9
is handled by the contract's own fallback.

## Error handling, idempotency and recovery

- **Every refusal is a `ValueError` raised before any write:** integrity, a re-read, Trash, a recorded-as-receipt
  document, a required choice, a currency block, a limit, a missing account, or nothing to import. The API maps it to
  400 with the message. Messages name the next step (FR-29).
- **Atomicity:** the new account, inserts, evidence and the import record share one `with store.connection()` block
  (`storage.py:248`, `with db:`). Any exception rolls all of it back. Reconciliation runs after commit (as for CSV). A
  crash between commit and reconciliation is repaired by Reconcile now.
- **Idempotency:** a retry inserts 0 and links duplicates' evidence (`INSERT OR IGNORE`, `add_evidence` is `INSERT OR
  IGNORE` on the link). Each request adds one `transaction_imports` row (FR-20).
- **Restart:** there is no in-memory state between preview and import. The import re-derives everything from the saved
  reading and the request's choices, so a restart between the two changes nothing.
- **Concurrency:** `Manager.import_transactions` already takes `self.mutex` and `require(False)` (it refuses during
  non-inference work, and doesn't wait for model work). A re-read that finishes between preview and import is caught
  by the `reading_id` check.
- **Index staleness:** the index is keyed by `parse_run_id` and `analyzer_version`. A newer reading gets a new row, and
  a version bump is recomputed lazily. A stale or missing index affects only the picker and the primary action, never
  what is imported (import always analyzes the reading).

## Privacy/security and migration impact

- No network or model call in preview or import. `pdf_import.py` imports nothing from `models/`. The C-net test fixture
  blocks non-loopback sockets.
- Only the last four digits are ever stored (`account_in` enforces `\d{4}`). The import record stores the chosen
  options, row keys and issue messages (which hold dates, amounts and descriptions, as CSV issues already do). It
  stores no account number. Row contents are not logged.
- **Migration 071** adds one derived, STRICT table with an `ON DELETE CASCADE` on `parse_runs`. There is no backfill in
  the migration and no change to existing rows. `tests/test_migrations.py` gains `test_071_pdf_import_index`, which
  checks that the upgrade from 070 leaves every existing table's row counts unchanged and sets `user_version=71`.
- Backups and the CPA pack: the index is derived data. If backups enumerate tables, the index is included harmlessly.
  SL-06 checks `tests/test_backup.py` still passes.

## Vertical slices

| ID | FR/SC covered | Dependencies | Files/changes | Verification command / evidence |
|---|---|---|---|---|
| SL-01 | Fixtures and the G1/U2 gate (contract P-checks for K, R, X, F, M, V, D-*, K0, K2, Keur) | none | `tests/pdf_import_fixtures.py` (new: builders, with footer lines of at least 40 non-space characters per native page, and P-check helpers); `tests/test_pdf.py` `make_pdf` (additive options, see "SL-01 details" below); `tests/test_pdf_imports.py` (new; P-check tests only) | `python -m pytest tests/test_pdf_imports.py -k pcheck tests/test_pdf.py tests/test_pdf_layout.py -q`. **Gate:** see "SL-01 details". If it fails, stop and escalate before SL-02 |
| SL-02 | FR-03, FR-04, FR-06, FR-07 (parsing), FR-08 (native and rebuilt tables, continuation pages; SC-07 7-a to 7-e), FR-09 exception (SC-08 8-a), FR-09 (tick rule), FR-10, FR-11 (row/document), FR-12, FR-13 (patterns), FR-21; SC-07, SC-24, SC-25, SC-16 (analyzer level), SC-05 step 5, SC-09 (analyzer level) | SL-01 | `finance/pdf_import.py` (new, pure); `tests/test_pdf_imports.py` (analyzer tests on real readings; SC-16 uses a fabricated `PDFResult` built in memory; SC-25 at analyzer level asserts V's 5 rows: v1 and v2 native, v3 to v5 below-table rows numbered 3 to 5, P13; plus synthetic analyzer cases for a Summary native table
below a transactions table (still listed, nothing absorbed) and a second visual heading below a native table (the
issue is reported)) | `python -m pytest tests/test_pdf_imports.py -k "analyzer or sc07 or sc24 or sc25 or sc16" -q` |
| SL-03 | FR-02, FR-05, FR-07 (default by account), FR-11 (block), FR-12, FR-13 (match), FR-15, FR-19, FR-22, FR-23, FR-29, FR-30; SC-02, SC-03, SC-04, SC-05, SC-08, SC-09, SC-15, SC-16 (API), SC-17, SC-18; J1 steps 1–4 | SL-02 | `finance/ledger.py` (`pdf_reading`, `pdf_refusal`, `account_match`, `row_status`, `preview_pdf_import`, `import_pdf_transactions`, `.pdf` dispatch, `insert_transactions(fingerprints=)`); `app/api.py` (`ImportInput` fields); `app/manager.py` (pass-through); tests | `python -m pytest tests/test_pdf_imports.py -k "sc02 or sc03 or sc04 or sc05 or sc07 or sc08 or sc09 or sc15 or sc16 or sc17 or sc18 or sc24 or sc25" tests/test_imports.py tests/test_tabular.py -q`. SC-07, SC-24 and SC-25 run here for their import steps (pass-2 m-3); in SL-02 only their analyzer checkpoints run |
| SL-04 | FR-01, FR-14, FR-16, FR-17, FR-18 (ledger), FR-20, FR-23 (new account in the transaction); SC-06, SC-10 (including 10-a), SC-11, SC-26; J1 complete (SC-01, SC-12, SC-13, SC-14), J1-a | SL-03 | `finance/ledger.py` (`new_account` path, duplicate messages); `finance/reconcile.py` (`manual_candidates` extracted; `replace_manual` uses it, with unchanged behavior); `library/storage.py` `WORK_FILTERS["ready_for_ledger"]` (P5); tests, including the permanent-trigger fault double | `python -m pytest tests/test_pdf_imports.py -k "journey_j1 or sc06 or sc10 or sc11 or sc26" tests/test_imports.py tests/test_formats.py tests/test_tabular.py tests/test_library.py tests/test_finance.py tests/test_reconcile_tools.py -q` |
| SL-05 | FR-24; SC-22 (API and badge; k5's locator is `table_id = page-2-import-continuation`, `row = 1`, continued from `page-1-…` table, pass-5 MINOR-4; plus V's v5, a below-table row: native `table_id`, `row = 5`, `word_ids` and `line_ids`, no `cell_ids`, and the API and badge link `?lines=<line_ids>`, pass-7 m-2) | SL-04 | `finance/provenance.py` (PDF locator → `import {file, page, row, table, continued_from}`, `document {id, page, lines, cells}`); `app/static/trace.js:183` (page form and link); tests | `python -m pytest tests/test_pdf_imports.py -k sc22 tests/test_provenance.py tests/test_traces.py -q`; `RUN_BROWSER_TESTS=1 python -m pytest tests/test_pdf_imports_browser.py -k sc22` |
| SL-06 | FR-25, FR-01 (filters for imported PDFs, re-checked); SC-19 (API twin), SC-26 step 2 | SL-04 | `library/migrations/071_pdf_import_index.sql`; `documents/receipt_service.py` (`index_quietly` on publish); `finance/pdf_import.py` (`index_row`, `pending`, `backfill`, `ANALYZER_VERSION`); `app/manager.py` `open_library` (submits the backfill); `library/storage.py` and the listing (server-computed `pdf_import`); `app/api.py` (`GET /api/finance/import-candidates`); `app/static/money_v2.js` (picker uses it; `PDF` label; copy names PDF, CSV and XLSX); `tests/test_migrations.py`; tests | `python -m pytest tests/test_pdf_imports.py -k "sc19 or index" tests/test_migrations.py tests/test_backup.py tests/test_library.py -q`; `RUN_BROWSER_TESTS=1 python -m pytest tests/test_pdf_imports_browser.py -k sc19` |
| SL-07 | FR-13 (UI), FR-14 (UI), FR-15, FR-27, FR-28 (and the UI side of FR-04–FR-09); SC-21, SC-23 | SL-04, SL-06 | `app/static/library.js` (PDF mode, Read-then-preview, `new_account` in the request); `app/static/index.html` `#import-dialog` (PDF controls); `app/static/style.css` (scoped rules only); `tests/test_pdf_imports_browser.py` | `RUN_BROWSER_TESTS=1 python -m pytest tests/test_pdf_imports_browser.py -k "sc21 or sc23" tests/test_transactions_v2_browser.py -q` |
| SL-08 | FR-18 (UI), FR-26; SC-20; docs; manual run | SL-06, SL-07 | `app/static/records_v2.js` (`rc2Step`, `rc2Menu`); `app/static/document_v2.js` (`doc2Steps` primary or secondary import); `docs/documents.md` ("PDFs", "CSV and XLSX imports" → "Transaction imports"), `docs/money.md` ("Import identity": PDF rows share the fingerprint), `docs/open-work.md:45` (cross-page linking done in the import only), `docs/development.md` schema map (migration 071, review minor 6); tests | `RUN_BROWSER_TESTS=1 python -m pytest tests/test_pdf_imports_browser.py -k sc20 tests/test_records_v2_browser.py tests/test_document_v2_browser.py -q`; the manual run on the agent test instance, with evidence under its folder |

### SL-01 details

`make_pdf` gains these additive options. Existing calls are unchanged:
- an `images` page setting: an image XObject, for F's `possible_image_content` trigger;
- cp1252 text encoding for `•`/`…`: a WinAnsi `/Encoding` on the font, with Latin-1 output unchanged;
- an optional 4th item element, the font size;
- an optional `media` page size (pass-2 MJ-2).

The long-cell fixtures (V's 480-character v5, and the 2,001-character cell of SC-16 step 4) put the long Description
cell on a wide page (`media` up to 14,400 pt, the PDF maximum), at the default 10 pt so that the reader's
row and word grouping thresholds keep their meaning. The other columns are placed past its right edge, so the reader sees
no `glyph_outside_page` or `overlapping_text`. Only those two fixtures' x-positions differ from the contract's
convention; no expected value changes. Pass-3 MINOR-2 adds two more details:
- `media` also sets the default CropBox, because the reader's bounds are the crop box (`pdf_layout.py:284`), and
  glyphs past it suppress the table (`:305`, `:520`).
- The 2,001-character cell is built from space-separated words of at most 1,000 characters, because
  `PDFWord.character_indexes` is capped at 1,000 (`pdf_layout.py:44`). The reading then succeeds, and the **import**
  refuses on the cell limit.

**Gate:** each must hold before SL-02 starts. On failure, stop and escalate: a heading that doesn't form one visual row, or a contract
feasibility question for the long cells.
- Every intended native page reads as `embedded_text` with no model.
- The contract's amended P-checks hold. Every headerless page has **no** native transactions table, as the reader
  is built to do. Every rebuilt page has its heading as one **visual row** (FR-08), whose words carry the boxes the
  column spans need. X page 1 and page 3 have the stated native tables. The footers are words-only (contract fixture
  rule), so no page meant to be clean carries `unresolved_columns`.
- SC-16's 2,001-character cell reads as **one** native cell, with no `pdf_layout_review`.
- V (amended after the first SL-01 run, P13): the reader's native table is the heading, v1 and v2, the page's only
  layout issue is `unresolved_columns`, and v3, v4 and v5 are each **one** visual row below it. Each maps to the
  heading's column spans with no straddling word, and v5's 480-character description is one text in the Description
  span. No `glyph_outside_page`, `overlapping_text` or rotation issue. (V shows the reader's behavior, which the
  P-check pins; it doesn't need V to read as one complete native table.)

Milestone checks:
- **M1, after SL-04:** the full backend contract passes: `python -m pytest tests/test_pdf_imports.py
  tests/test_imports.py tests/test_formats.py tests/test_tabular.py tests/test_pdf.py tests/test_pdf_layout.py -q`.
- **M2, after SL-06:** the M1 set plus `tests/test_provenance.py tests/test_migrations.py tests/test_backup.py`.
- **M3, after SL-08:** the contract's full targeted run, both lines.

## Requirements & scenarios coverage matrix

| FR | Slice(s) | Contract scenarios |
|---|---|---|
| FR-01 | SL-03 (dispatch), SL-04 (filter), SL-06 | J1 2, 5; SC-26 |
| FR-02 | SL-03 | J1 1; C-net throughout |
| FR-03 | SL-02, SL-03 | SC-09 |
| FR-04 | SL-02, SL-07 | J1 3; SC-07 |
| FR-05 | SL-03, SL-07 | SC-04; J1 3 |
| FR-06 | SL-02, SL-03 | SC-02; SC-24 |
| FR-07 | SL-02, SL-03 | J1; SC-02; SC-03; SC-25 |
| FR-08 | SL-02 | J1 3; SC-07 |
| FR-09 | SL-02, SL-03 | SC-08 |
| FR-10 | SL-02 | SC-07; SC-08; SC-09; SC-25 |
| FR-11 | SL-02, SL-03 | SC-18 |
| FR-12 | SL-02, SL-03 | SC-04; J1 4–5 |
| FR-13 | SL-02, SL-03, SL-07 | J1 3; SC-05; SC-23 |
| FR-14 | SL-04, SL-07 | SC-06 |
| FR-15 | SL-03, SL-07 | SC-03; SC-23 5 |
| FR-16 | SL-04 | SC-10; SC-11; J1 6, 9 |
| FR-17 | SL-04 | SC-10 (10-a); SC-11; J1 7 |
| FR-18 | SL-04, SL-08 | J1 5, 9, 10; SC-11; SC-20 |
| FR-19 | SL-03 | SC-15 |
| FR-20 | SL-04 | J1 6, 8 |
| FR-21 | SL-02, SL-03 | SC-16 |
| FR-22 | SL-03 | SC-17 a–d |
| FR-23 | SL-03, SL-04 | SC-06; SC-17 e; J1 4 |
| FR-24 | SL-03 (locators), SL-05 | SC-22; J1 4 |
| FR-25 | SL-06 | SC-19 |
| FR-26 | SL-06 (index), SL-08 | SC-20 |
| FR-27 | SL-03 (message), SL-07 | SC-21 |
| FR-28 | SL-07 | SC-23 |
| FR-29 | SL-03, SL-04 | C-refusal in SC-02, 03, 05, 06, 15, 16, 17, 18 |
| FR-30 | SL-03, SL-04 | C-net, C-ids; SC-06; SC-25 v5 |

Every contract scenario (J1, SC-02 to SC-11, SC-15 to SC-26) appears in at least one slice's verification command
above.

## Test environments, data, stubs for nondeterministic components, final-state oracle

- **Isolation:** every test uses `tmp_path` (`create_app(tmp_path / "control", …)` or `Store(tmp_path / "managed")`),
  with synthetic PDFs from `tests/pdf_import_fixtures.py` only. Browser tests use `served()` on a loopback port. The
  manual run uses the agent test instance (`agent-testing` skill), never a live library.
- **Test types:**
  - Unit: `pdf_import.analyze` on real readings of the fixtures (SL-02).
  - Integration: ledger and API through `TestClient` (SL-03, SL-04, SL-05, SL-06).
  - Stateful end-to-end: J1, as **one** test function with ordered checkpoints. It includes the J1-a restart (a new
    `Manager` on the same folders).
  - UI: opt-in Playwright tests (SL-05, SL-07, SL-08).
- **Doubles (contract "Doubles"):**
  - **Vision:** `local_model` for SC-09's scanned page only.
  - **Record:** `local_model` answering by `json_schema.name` with S-K, with the `publish_statement(…, "proposed")`
    fallback. The test's docstring records which one it used.
  - **Fault:** a **permanent** `BEFORE INSERT` trigger on `transactions` (see "Connections"), dropped in `finally`.
  - **Row limit (contract SC-16 as amended):** the analyzer gets an in-memory `PDFResult` (20,001 and 20,000 rows),
    which is never saved. The API test lowers `pdf_import.MAX_ROWS` to 3 with `monkeypatch`, and uses a real 4-row
    reading.
  - **No clock dependence:** SC-02 chooses 2025, and asserts no date in the run year.
- **Final-state oracle (independent of the code under test):** each test reads SQLite directly (`store.connection()`)
  for the count of each contract table, `typeof(amount_minor)`, `origin`, `review_status`, `statement_id`, and evidence
  `locator_json`. It hashes the blob and the reading folder files for C-evidence. It never asserts through the
  preview's own response alone. Expected values are the contract's tables, hard-coded in `tests/pdf_import_fixtures.py`
  next to each fixture, never computed by `pdf_import`.

## Risks, unresolved decisions, alternatives

- **Rebuilt rows depend on layout (A1).** The rebuild is only as good as the saved word boxes and the column
  midpoints. Unusual layouts can produce several outcomes:
  - wrapped descriptions: the second line has no date, so it isn't a row, and only the first line's text is the
    description;
  - amounts far from their headings: reported as straddling;
  - two-line headings: not found, so the page is reported.

  - a native table cut short by a row with no alphabetic description: the rows below it are rebuilt (P13). A dated
    line with an amount printed below a table (for example a payment-due line) becomes a candidate too. It is
    accepted or reported like any rebuilt row, and the preview totals are the mitigation, as for D10.

  - a second transactions heading below a native table (pass-7 m-3, not accepted by the user and not mitigated):
    its page's later rows are reported, but the next page still continues the **first** table, because the spec's
    continuation rule ends a chain only at a new transactions table. If the second table's columns differ, the next
    page's rows could be mapped to the first table's columns. The preview shows each row's columns and signed amount.

  Money is never guessed: a row's date or amount that doesn't fit is reported. The second line of a wrapped
  description is dropped without a report, which affects only the description text. Accuracy on the user's real bank
  PDFs is unmeasured. The manual run
  (SL-08) on a synthetic copy of that layout is the first check.
- **D10, the accepted risk, as amended:** any later-page line with a date and an amount in the continued table's
  columns is counted, schedules included (contract 7-a asserts it). The only mitigation is the preview totals.
- **R2, R3, R4** (not accepted): a last four printed for another account preselects the wrong account; Import made
  primary leads to never Recording; newest-first statements break the rollover. None is mitigated beyond the spec. R4
  can produce rows a year off for newest-first card statements.
- **Record's account matching** is by exact institution text (`find_account`). A user whose PDF-import account name
  differs from the institution that Record extracts gets a second account and duplicate rows. This is existing Record
  behavior, out of scope (spec non-goal "Changing statement extraction / Record"). It's worth a follow-up.
- **Preview size:** the preview returns every row (up to 20,000) so that ticks work. That is a large response and a long
  table at the limit. It is acceptable for household statements (tens to hundreds of rows). The dialog renders plainly,
  with no virtualization.
- **The index adds a migration**, which could have been avoided by analyzing readings on each picker or listing request.
  That was rejected, because SC-19's 250 PDFs would each be parsed from multi-MB JSON on every picker open.
- **The `make_pdf` image option** changes a shared test helper. It is additive (a new optional page key). SL-01 runs
  `tests/test_pdf.py` and `tests/test_pdf_layout.py` to confirm that no existing test changes.
- **Environment:** the project's test runner isn't installed on this Linux machine. The verification commands are
  written as `python -m pytest`, for the project's `.venv`. Browser tests require Edge (`channel="msedge"`), as the
  existing ones do.
- **Alternatives considered:**
  - Adding `.pdf` to `TABLES`: rejected, because it breaks FR-01 (reclassification and filters).
  - A separate PDF import endpoint: rejected, because FR-01 requires the same flow and API.
  - Storing PDF options in new `transaction_imports` columns: rejected (P4).

## Review history

See `plans/account-import-pdf/reviews.md`. Pass 1 (REVISE) led to amendments to the spec bundle (FR-17, FR-21, SC-10,
SC-16, and contract fixture rules), which the user chose on 2026-10-24. The amended bundle was re-approved on
2026-10-24 (a49e0ea8a230). Pass 2 (REVISE) was fixed in the plan alone. Pass 3 found no BLOCKER or MAJOR; its two minors are fixed.
After the loop, the G1 reader check led to FR-08 rebuilt rows (spec re-approved ea03f0026930). Pass 4, which the user
authorized, found two blockers. They were fixed with visual rows (spec re-approved 501d6bbf3a70). Pass 5 found one MAJOR,
the footer flag, which the user decided by extending the FR-09 exception; its minors are fixed. That amendment needs the
spec approved again.
After approval, SL-01's gate failed on fixture V: the reader cuts a native table short at v3's blank description. The
user chose a plan change (P13, below-table rows), reviewed in pass 6.
