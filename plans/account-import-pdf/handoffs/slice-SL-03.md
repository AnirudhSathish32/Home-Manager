```yaml
slice: SL-03
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: cc6a0aa
end_head: <the commit; see `git log -1`>
commit: <this commit>
changed_files:
  - src/home_manager/finance/ledger.py          # pdf_reading, pdf_refusal, account_match, row_status, pdf_state, preview_pdf_import, import_pdf_transactions, is_pdf, .pdf dispatch, insert_transactions(fingerprints=)
  - src/home_manager/app/api.py                 # ImportInput PDF fields, preview route skips the account/currency check for a PDF
  - src/home_manager/app/manager.py             # import_transactions passes `pdf` through
  - tests/test_pdf_imports.py                   # C-net fixture, API harness (Env), 32 new tests; the P-check and analyzer tests are untouched
  - plans/account-import-pdf/handoffs/slice-SL-03.md
checks:
  - command: ".venv/bin/python -m pytest tests/test_pdf_imports.py -k \"sc02 or sc03 or sc04 or sc05 or sc07 or sc08 or sc09 or sc15 or sc16 or sc17 or sc18 or sc24 or sc25\" tests/test_imports.py tests/test_tabular.py -q"
    exit_code: 0   # 91 passed, 39 deselected
  - command: ".venv/bin/python -m pytest tests/test_pdf_imports.py -k pcheck -q"
    exit_code: 0
  - command: ".venv/bin/python -m pytest tests/test_pdf_imports.py -k analyzer -q"
    exit_code: 0
  - command: ".venv/bin/python -m pytest tests/test_pdf_imports.py -k sc01 -q"   # J1 steps 1-4; not selected by the slice's -k
    exit_code: 0
  - command: ".venv/bin/python -m pytest tests/test_pdf_imports.py tests/test_imports.py tests/test_formats.py tests/test_tabular.py tests/test_pdf.py tests/test_pdf_layout.py tests/test_library.py tests/test_finance.py tests/test_reconcile_tools.py -q"
    exit_code: 0   # regression sweep over the files that touch import, ledger and the API
  - command: ".venv/bin/ruff check src/home_manager/finance/ledger.py src/home_manager/app/api.py src/home_manager/app/manager.py tests/test_pdf_imports.py tests/pdf_import_fixtures.py"
    exit_code: 0
  - command: ".venv/bin/python -m mypy"
    exit_code: 1   # 8 errors, all in core/paths.py (Windows-only attributes), identical to START_HEAD; none in the touched files
escalations: []
```

# SL-03 handoff: ledger preview and import of PDF rows, API fields

Spec, plan, `progress.yaml`, approvals, `reviews.md`, the reader, `tabular.py`, `pdf_import.py` and `tests/pdf_import_fixtures.py` are untouched. No migration. The CSV/XLSX
code paths are unchanged: `preview_import` and `import_transactions` gain one early `if self.is_pdf(...)` branch (a read of `occurrences.relative_path`)
and a `pdf=None` keyword, and nothing else.

## Interfaces as built

`Ledger` (`finance/ledger.py`), all after `import_transactions`:

- `is_pdf(document_id) -> bool`: the extension of the occurrence is `.pdf`.
- `pdf_reading(db, document_id, digest, reading_id=None) -> (document, version, run, PDFResult)`. In order: document and version exist; Trash
  (`Restore the document from Trash before importing it.`); `digest != current_hash` (`This document changed since the preview; preview again.`, P8);
  blob re-hash; the latest `succeeded`/`partial` parse run for the hash, `parser_version<>'receipt-ocr-v1'` (the SQL of `text_run_id`, not
  `store.document()`), none -> `Read this document first.`; `reading_id` given and different -> `This document was read again since the preview; preview again.`;
  `result_json` and the run folder's `result.json` both through `read_result`, size-checked against `PDF_EVIDENCE_BYTES`, compared with `model_dump()`, and
  `input_hash == version.hash`; any failure -> `PDF_INTEGRITY` = `Preserved evidence failed its integrity check. Nothing was imported.`. A non-PDF result gives `pdf_import.NO_LAYOUT`.
  It never opens the extracted folder through `ReceiptService.folder` (that mkdirs); it builds `store.root/extracted/<run id>/result.json` with `safe_path`.
- `pdf_refusal(db, blob_hash) -> str | None`: `This PDF is recorded as a <receipt|bill|pay stub|tax form|investment statement>.` from non-rejected `receipts`
  (bill if `document_kind='bill'`), `income_records`, `tax_forms`, `investment_valuations`. A statement or nothing gives None.
- `account_match(db, last_fours, document_currency, home_currency=None) -> {account_id, last_four, page, text} | None`: active (`accounts.active=1`)
  accounts in `document_currency or home_currency or "USD"` whose last four is among `last_fours`; exactly one -> `Matched …NNNN printed on page N`.
- `row_status(db, account, fingerprints, blob_hash) -> [{"status": "new"|"already_recorded"|"rejected_earlier", "text": ...}]`, in the order of `fingerprints`. Reads only.
  `Already recorded from import <file>`, `…from statement <file>`, `…from this statement` (earliest evidence link's `blob_hash` is this document's), and
  `; not counted until you reconcile it.` appended when the existing row is not `COUNTABLE`. `<file>` is the basename of the earliest link's occurrence path.
- `pdf_state(db, document_id, digest, *, reading_id, account_id, account_type, currency, home_currency, mapping, tables, year, date_format, sign, ticked, unticked)`:
  shared by both entry points. `mapping` not None -> `Column mapping applies to CSV and XLSX files.`; `pdf_refusal` -> ValueError. Account in force = the request's
  `account_id`, else the single `account_match` when no `account_type` was sent (and `currency`, if sent, equals the match's), else none (every row New). Currency =
  the account's, else the request's, else the document's, else `home_currency or "USD"`. Runs `analyze` (twice when there is no `account_id`, the first to read
  `last_fours` and `document_currency`). Ticks = the analyzer's `row.ticked`, then `ticked` keys (not for rejected rows), then `unticked` keys; the same key in both -> ValueError;
  unknown keys are ignored. Fingerprints are over **all parsed rows in document order** (P3), only when an account is in force and `required` is empty.
- `preview_pdf_import(document_id, digest, *, mapping, account_id, account_type, currency, home_currency, reading_id, tables, year, date_format, sign, ticked, unticked)`
  returns `{kind: "pdf", reading_id, currency, account_id, tables [asdict(ImportTable)], rows, issues [asdict], counts, required, required_messages, blocked,
  totals, already_recorded_totals, account_match, new_account_last_four, sign_default, sign, mapping, document_currency}`.
  - row: `key, page, table_id, row, date, description, amount` (as printed), `posted_date, amount_minor, currency, display_amount, ticked, labels, rejected,
    status` (`new|already_recorded|rejected_earlier|rejected`), `status_text` (`New`, the messages above, `Rejected: <reason>`), `continued_from, cell_ids, line_ids, word_ids`.
  - `totals` / `already_recorded_totals` = `{outflow, inflow, outflow_minor, inflow_minor}` (formatted strings as the CSV preview, and integers) over **ticked** rows; Already recorded
    and rejected-earlier rows go to the second.
  - `counts` = the analyzer's counts with `left_out` recomputed from the ticks, plus `new`, `already_recorded`, `rejected_earlier` (ticked parsed rows). `new + already_recorded + rejected + left_out == seen`.
  - With `required` non-empty no status lookup is made (a date or amount is not known), so rows are New, and rows with an amount still count in the totals (SC-02 step 1).
- `import_pdf_transactions(document_id, digest, *, account_id, mapping, reading_id, tables, year, date_format, sign, ticked, unticked)`:
  `Choose the account these transactions belong to.` without `account_id`; `Preview this document again before importing it.` without `reading_id`. One `store.connection()`:
  `pdf_state` (every check again), blocked -> its message, `required` -> the `REQUIRED` texts, nothing ticked -> `Nothing to import: <reason>` (P7), `insert_transactions(..., "import", source, fingerprints=…)`
  with `source_key = "import:<uuid hex>"` and `parse_run_id = reading_id`, then the `transaction_imports` row (11 existing columns; `mapping_json` as the plan, `issues_json` = `[asdict(issue)]`; `sign` is stored only when the mapping has a single
  Amount column, else null). Returns `{import_id, account_id, account_name, inserted, duplicates, rejected, left_out, rejected_earlier, pages_without_rows, issues, duplicate_sources}`
  (`duplicate_sources` = status text -> count, taken before the insert).
  - Locator per row: `{document_id, blob_hash, reading_id, page, table_id, row, cell_ids | word_ids, line_ids, continued_from?}`.
- `REQUIRED = {"year": "Choose the year: …", "date_format": "Choose the date order: …", "sign": "Choose whether positive amounts are money in or money out …"}`, `PDF_INTEGRITY`, `PDF_ONLY`.
- `insert_transactions(..., refresh=(), fingerprints=None)`: given fingerprints replace the computed ones. A module alias `identities = fingerprints` is used inside because the
  parameter shadows the function. Existing callers are unchanged.
- `preview_import(document_id, currency, mapping=None, digest=None, pdf=None)` and `import_transactions(document_id, account_id, mapping=None, digest=None, pdf=None)`: a `.pdf` document
  goes to the functions above with `**pdf`; a non-PDF with `pdf` set raises `PDF_ONLY` (400). The import drops `account_type` from `pdf` (preview only).

API (`app/api.py`): `ImportInput` gains `account_type` (preview only), `reading_id` (32 hex), `tables`, `year` (1900–2100), `date_format` (`auto` or a `DATE_FORMATS` value), `sign`
(`negative_is_outflow` | `positive_is_outflow` | null), `ticked`, `unticked` (up to 20,000 keys each), all optional; `ImportInput.pdf_choices()` returns the non-null ones. The preview route, for a PDF,
skips `Choose an account or a currency for the preview.` and passes `account_id`, `home_currency` (from `manager().household`) and the choices. The import route is unchanged apart from the pass-through.
`Manager.import_transactions(..., pdf=None)` passes `pdf` to the ledger.

## Deviations from the plan (please confirm)

1. **`new_account` is not in `ImportInput`, `preview`, or `import_pdf_transactions`** (the task puts the `new_account` path in SL-04). SL-04 adds the field (the 6-digit 422 comes free from `AccountInput`),
   the exactly-one-of check, and `account_in` inside the import's connection. `preview` already returns `new_account_last_four`, and takes `account_type` + `currency`.
2. **`row_status(db, account, fingerprints, blob_hash)` has no `rows` argument.** The plan's `rows` is only needed for the `replaces a manual entry` label, which needs `reconcile.manual_candidates` (SL-04). SL-04 adds
   it. Otherwise `row_status` is complete (import / statement / this statement / not-counted suffix / rejected earlier), because SC-15 Ps needs the statement messages here.
3. **`import_pdf_transactions` requires `reading_id`** (plan signature has it as a required keyword). The API field is optional because the preview does not send it.
4. **`ImportInput` PDF-vs-CSV validation is in the ledger**, not the route: the route passes `pdf=None` when no PDF field was sent, and the ledger raises `PDF_ONLY` for a CSV with PDF fields and the `mapping` refusal for a PDF.
5. **`is_pdf` dispatch.** The preview route calls `ledger.is_pdf` to skip the account/currency check; the CSV branch of the route is otherwise byte-identical.
6. **Match used for statuses/sign only when the request names no `account_type`** (and any `currency` equals the match's): a user who is typing a new account must not get the matched account's sign or statuses. Not stated in the plan.
7. **Unknown or rejected row keys in `ticked`/`unticked` are ignored**; the same key in both is a refusal.

## Notes for SL-04 and later

- `Env` in `tests/test_pdf_imports.py` (the `env` fixture) is the API harness: `add` puts a PDF in the Inbox and captures it. **Capture already reads a native PDF with no model**, so `add` reads
  again only when none was saved or a model config is passed; a fixture that must stay unread is a scanned page without a model (`fx.m_pages()`, as the unread test uses). Fixtures that share bytes
  share a `blob_hash` and so a record: SC-15's five K copies print a distinct `Copy <name>` line.
- `Env.state()` = row counts of the six contract tables + sha256 of every blob and every saved-reading file (C-unchanged / C-evidence). The C-net fixture is autouse for the whole module.
- SC-15 Ps: after `publish_statement`, "reconciled" is `reconciler.reconcile_statement(id)` (the user's yes), not `review` nor `run()`; until then the preview says `; not counted until you reconcile it.` (asserted).
- J1 steps 1–4 are `test_sc01_journey_j1_steps_1_to_4_preview_and_import_k` (not selected by SL-03's `-k`; selected by `-k journey_j1`, which SL-04 extends). Steps 5+ (Spending, duplicates, rejected k8, `B`, Record, restart) are SL-04.
- The fault double (SC-17 e) is a permanent trigger dropped in `finally`; the 500 is read with a second `TestClient(raise_server_exceptions=False)`. The app has no handler for `sqlite3.Error`, so the response is Starlette's plain 500 (no traceback, no text). SC-06 (SL-04) can use the same pattern.
- Not covered here: the `replaces a manual entry` label, SC-10/SC-11 as scenarios, the provenance/trace changes (SL-05), `ready_for_ledger` (P5, SL-04), the candidates endpoint and `pdf_import` index (SL-06).
- A PDF read before this feature (layout `None`) previews with `blocked = NO_LAYOUT` and no rows; there is no test of it through the API (covered by the analyzer test).
