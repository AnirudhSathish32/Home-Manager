```yaml
slice: SL-06
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 92dfea1
end_head: <the commit; see `git log -1`>
commit: <this commit>
changed_files:
  - src/home_manager/library/migrations/071_pdf_import_index.sql   # new: pdf_import_index (STRICT), user_version=71, no backfill
  - src/home_manager/finance/pdf_import.py                         # ANALYZER_VERSION, index_row, index_quietly, pending, backfill, summaries
  - src/home_manager/documents/receipt_service.py                  # pdf_import.index_quietly beside the text index on publish (PDF branch)
  - src/home_manager/app/manager.py                                # open_library submits pdf_import.backfill (capture queue) when pending
  - src/home_manager/library/storage.py                            # Store.import_candidates
  - src/home_manager/app/api.py                                    # GET /api/finance/import-candidates; pdf_import on GET /api/documents and /api/documents/{id}
  - src/home_manager/app/static/money_v2.js                        # picker uses the endpoint; PDF/CSV/XLSX badge; copy; "Still checking older PDFs …"
  - tests/test_migrations.py                                       # test_071_pdf_import_index_adds_one_derived_table_and_changes_nothing_else
  - tests/test_pdf_imports.py                                      # 3 sc19 API tests, 7 index tests; Env.add lists with limit=100_000
  - tests/test_pdf_imports_browser.py                              # 2 sc19 browser tests
  - plans/account-import-pdf/handoffs/slice-SL-06.md
checks:
  - command: ".venv/bin/python -m pytest tests/test_pdf_imports.py -k \"sc19 or index\" -q"
    exit_code: 0   # 10 passed (3 sc19, 7 index); ~116 s
  - command: ".venv/bin/python -m pytest tests/test_migrations.py tests/test_backup.py tests/test_library.py -q"
    exit_code: 0   # 33 passed
  - command: "RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_pdf_imports_browser.py -k sc19 -q"
    exit_code: 0   # 2 passed; ~86 s
  - command: ".venv/bin/python -m pytest tests/test_pdf_imports.py tests/test_imports.py tests/test_formats.py tests/test_tabular.py tests/test_pdf.py tests/test_pdf_layout.py tests/test_provenance.py tests/test_migrations.py tests/test_backup.py -q"
    exit_code: 0   # M2 milestone: 254 passed
  - command: ".venv/bin/python -m pytest tests/test_trash.py tests/test_text_index.py tests/test_managed_library.py tests/test_receipts.py -q"
    exit_code: 0   # 50 passed (Trash emptying, schema version checks)
  - command: ".venv/bin/ruff check <touched python files>"
    exit_code: 0
  - command: ".venv/bin/python -m mypy"
    exit_code: 1   # "Found 8 errors in 1 file": the baseline core/paths.py errors only
escalations: []
```

# SL-06 handoff: import index (migration 071), backfill, `pdf_import` in listings, import-candidates, picker

Spec, plan, `progress.yaml`, approvals, `reviews.md`, fixtures (`tests/pdf_import_fixtures.py` was not needed), `ledger.py` and the CSV/XLSX paths are untouched. M2 is complete with this slice.

## Interfaces as built

- **Migration 071** `pdf_import_index(parse_run_id TEXT PRIMARY KEY REFERENCES parse_runs(id) ON DELETE CASCADE, analyzer_version INTEGER NOT NULL, transactions_tables INTEGER NOT NULL, last_fours_json TEXT NOT NULL, document_currency TEXT, error TEXT, created_at TEXT NOT NULL) STRICT`, exactly as the plan. No data is touched. Backups copy the whole database (`db.backup`), so the table is in them; Trash emptying follows foreign keys generically, so it needed no change (`test_trash.py` passes).
- **`pdf_import.py`**
  - `ANALYZER_VERSION = 1`.
  - `PDF_READINGS`: SQL predicate on `parse_runs p`: `status IN ('succeeded','partial')` and `parser_version IN PDF_VERSIONS` (so `pdf-pages-v1` and `-v2-tables` readings are indexed too, as "no layout").
  - `index_row(db, run_id) -> dict | None`: replaces the reading's row and returns it; `None` (and deletes any stale row) when the run is not a finished PDF reading. It runs `analyze(result, currency="USD")` (the currency does not change tables, last fours or document currency). `transactions_tables` = the tables with `selectable` (transactions and rebuilt; continuations and `other` are not counted). A blocked reading (`NO_LAYOUT`), a `PDFImportError` (the 20,000-row limit) or any other exception writes `transactions_tables = 0` and `error`; an unexpected exception is logged by `log_failure` and the row says only `The reading could not be analyzed (<ExceptionType>).` (no row content). `last_fours_json` is `{"4821": 1}` (digits to first page); `document_currency` is `analysis.document_currency`.
  - `index_quietly(store, run_id)`, `pending(db)` (PDF readings with no row or an older `analyzer_version`), `backfill(store, work=None) -> int` (one connection per reading, `work.check()` between them).
  - `summaries(db, ledger, rows, home_currency=None)`: sets `row["pdf_import"]` on library-row dicts: `None` for non-PDFs and for a PDF whose current reading (`text_run_id`) has no row; else `{"tables": n, "match": {"account_id","last_four","page"} | null, "refused": "<kind>" | null}`. `match` comes from `Ledger.account_match` (index last fours and currency; `home_currency or "USD"` fallback inside it) and `refused` from `Ledger.pdf_refusal`, with the kind taken out of its message (`bill`, `receipt`, `pay stub`, `tax form`, `investment statement`). Match and refusal are only computed when `tables > 0` (a table-less PDF gets `match: null, refused: null`).
- **Wiring**: `ReceiptService` calls `pdf_import.index_quietly` right after the text index in the PDF branch of `publish` (non-PDF readings are not indexed). `Manager.open_library` checks `pdf_import.pending` and submits `pdf_import.backfill` on the `capture` queue (kind `pdf_import_index`, label `Checking PDFs for transactions`) beside the text-index backfill.
- **`Store.import_candidates(refusal, limit=500)`** (`library/storage.py`): library rows not in Trash or grouped, with the `ready_for_ledger` filter (the one source, P5), and either `TABLE_FILE` or a `.pdf` whose `text_run_id` has an index row with `transactions_tables > 0`; sorted by added (newest first), PDFs dropped when `refusal(db, current_hash)` is truthy, **cap applied after filtering**. Each item is a library row plus `import_kind` (`csv`, `xlsx`, `pdf`). `refusal` is passed in (the API passes `ledger.pdf_refusal`) so `storage.py` stays below the ledger.
- **API**
  - `GET /api/finance/import-candidates` -> `{"items": [...], "indexing": bool}`; `indexing` is true while `pdf_import.pending` is non-empty (always present, plan: "until the backfill finishes").
  - `GET /api/documents` items and `GET /api/documents/{id}` gain `pdf_import` (above), computed in the route (`manager().household.home_currency`). `Store.documents()` / `Store.document()` themselves are unchanged (they have no ledger), so other callers get no `pdf_import`.
- **Picker** (`money_v2.js importPicker`): fetches `/api/finance/import-candidates`, no client-side filtering; each row shows a `status-badge` `PDF`/`CSV`/`XLSX` in the small line beside the folder (the row grid is unchanged); the empty state reads `No bank or card exports waiting. Put a PDF, CSV or XLSX statement or export in the Inbox folder.`; when `indexing`, a muted `Still checking older PDFs …` line follows the list (or the empty state). The dialog's hint paragraph is rewritten in JS to name PDF, CSV and XLSX (see deviation 2).

## Tests

- `tests/test_pdf_imports.py` (11 new): `sc19` x3 (250 table PDFs + CSV + unread scan + table-less PDF: 251 listed, CSV first, `indexing` false; filter before cap and refusal via a stub; imported and recorded-as-bill PDFs follow the listing rules), `index` x7 (listing `pdf_import` on K/K0/unread/CSV/table-less, two accounts with one last four -> no match, a recorded bill -> `refused: "bill"`; index contents hold only counts, last fours and a code; written on publish and again on request; failing analysis still writes a row and backfill neither stops nor repeats; no-layout and 20,000-row-limit readings; `pending` follows `ANALYZER_VERSION`; next start indexes older readings and the endpoint says `indexing: true` before, false after).
- `Env.add` now lists documents with `limit=100_000` (it used the default 100, which hid the 101st document).
- `tests/test_migrations.py`: `test_071_...` (row counts of every existing table unchanged, `user_version` 71, STRICT, columns, unique/foreign key/NOT NULL, cascade, nothing backfilled).
- `tests/test_pdf_imports_browser.py`: `sc19` (Transactions Import, Accounts Import, and the empty-state "Import an export" button on Accounts all list the CSV plus 250 PDFs labelled PDF; unread and table-less PDFs absent; a PDF opens the import dialog) and the empty-library copy test.

## Deviations and notes (please confirm)

1. **Cost of the 250-PDF scenario.** The reader runs in a subprocess (about 0.3 s a PDF), so the API test takes about 100 s and the browser test about 95 s. Indexing itself is about 1 ms a reading. The contract's size is kept.
2. **Dialog hint is set from JS.** `index.html` (`#money2-import` hint: "Files arrive through the Inbox or a watched folder. Choose one to import.") and `index.html:624` ("CSV or XLSX") are outside this slice's files, so `importPicker` sets the hint text. SL-07/SL-08 should move that copy into `index.html` and drop the line from the JS.
3. **`pdf_import` for a table-less read PDF is `{"tables": 0, "match": null, "refused": null}`** (an indexed reading), and `null` only when the reading is not indexed. A reading without layout is `tables: 0` with the reason in the index's `error` column (not in the listing).
4. **`refused` is the kind**, parsed from `pdf_refusal`'s message (`This PDF is recorded as a(n) <kind>.`) so the rule stays in `ledger.py`, which this slice does not edit. If that message changes, `pdf_import.REFUSED` must follow (a test pins `bill`).
5. **Stale index rows are used.** The candidates query accepts a row of any `analyzer_version`; `indexing` is true until the backfill refreshes them.
6. **`indexing` is `pending`-based**, so if the backfill failed repeatedly the picker would keep saying `Still checking older PDFs …`. A bad reading cannot cause it (a row is always written); only a crash of the backfill itself would.
7. **Currency mismatch does not hide a PDF.** `analyze(currency="USD")` blocks a EUR document with `document_currency_mismatch`; the index ignores that block (only `reading_without_layout` is an index error), records `document_currency = "EUR"`, and the picker lists the PDF. A test pins it (Keur). The import itself still blocks until an account in the document's currency is chosen (FR-11).
8. Scanned (`vision_model`) pages and combined groups: only PDF parser versions are indexed; `receipt-images-*` readings are not.
9. The statement/receipt/etc. "ready" interplay is unchanged: a PDF recorded as a statement leaves `ready_for_ledger` (P5), so it is not a candidate whether or not `pdf_refusal` covers it.

## Notes for SL-07 and later

- The picker passes the library row (now with `import_kind`) to `openImport(doc, ...)`; the import dialog (SL-07) can read `isPdf` from `relative_path` as before.
- SL-08's primary-action rule is `doc.pdf_import?.tables > 0 && doc.pdf_import.match && !doc.pdf_import.refused`; `match` is already null when two accounts share the last four or the currency differs.
