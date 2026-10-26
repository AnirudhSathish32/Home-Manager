```yaml
slice: SL-03
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 318e2ad
end_head: this commit (a commit cannot name itself; see `git log --grep "statement-accounts SL-03:"`)
commit: HEAD of "statement-accounts SL-03:"
checks:
  - command: ".venv/bin/python -m pytest tests/test_statement_rebuild.py -k sc19 tests/test_provenance.py tests/test_traces.py -q"
    exit_code: 0   # 2 passed. The -k also deselects test_provenance.py's and test_traces.py's own tests, so the whole files were run in the M1 run below.
  - command: ".venv/bin/python -m pytest tests/test_statement_rebuild.py tests/test_statement_forms.py tests/test_pdf_imports.py tests/test_extraction.py tests/test_layout_consumers.py tests/test_provenance.py tests/test_traces.py -q"
    exit_code: 1   # M1 whole plus test_traces.py: 304 passed, 3 failed. All 3 are in test_traces.py and fail identically on START_HEAD (stash check): this machine's node v18.19.1 rejects the open-tax engine's `--allow-fs-read` flag ("Engine 1 gave no answer (exit 9: node: bad option: --allow-fs-read=...)"). Nothing to do with this slice.
  - command: ".venv/bin/python -m pytest tests/test_statement_rebuild.py tests/test_statement_forms.py tests/test_pdf_imports.py tests/test_extraction.py tests/test_layout_consumers.py tests/test_provenance.py -q"
    exit_code: 0   # M1 as the plan states it (the same run minus test_traces.py, which M1 does not include): all passed, in the 304 above
  - command: "RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_pdf_imports_browser.py tests/test_trace_components_browser.py -q"
    exit_code: 0   # 12 passed (the two browser tests that exercise trace.js's sourceLink)
  - command: ".venv/bin/python -m ruff check src tests"
    exit_code: 0
escalations: []
```

# SL-03: where a row came from, and docs

## Changed files
- `src/home_manager/finance/provenance.py` `_extraction`: the evidence link's locator is read once (with its `document_id`). A transaction row has `source_document_id`, not `document_id`, so `document.id` used to be `null` for every extracted transaction; it is now the row's `source_document_id`, else the link's document. A **rebuilt** locator (`locator["rebuilt"]`) gives `document {id, page: locator.page, lines: line_ids, cells: word_ids or cell_ids, quote}`. Nothing else changes (header fields' `cells` from `summary_cell_evidence` are as before; the confidence and model fields are untouched).
- `src/home_manager/app/static/trace.js` `sourceLink`: for `kind === "extracted"` provenance it adds the string `cells` to `?lines=` (de-duplicated against `lines`). Imported rows' links stay lines only (see below).
- `tests/test_statement_rebuild.py`: `sc19` (2 tests, through the real API via the `env` fixture, with the Record done on `env.store`): S's s2 (a native table row: `cells` = its four table cell ids, `lines` = its line, page 1, the file's document id, the `.pdf` occurrence) and S-flag's s2 (no native table: `cells` = its word ids). Imports `opened` from `test_pdf_imports`. With `provenance.py` reverted both tests fail.
- `docs/documents.md`: "Transaction imports" (FR-30 as amended by D6, P18's rejection, `ANALYZER_VERSION=2` and the re-index at the next start); a bullet in "PDFs"; a new "Typed extraction" subsection "Statement rows from the printed columns" (pages, values, the model deciding nothing there, rejected rows, balance tables, checks, P8, evidence).
- `docs/money.md` "Reading a statement or receipt again": a paragraph on re-reading a statement PDF.

## Decisions and deviations to look at
- **trace.js is restricted to `extracted` provenance.** The plan row says "adds the cells to `?lines=` when present". Done for every kind, it would change the href of every imported row that carries words (a continuation or below-table row has `cells == word_ids`), and two existing browser assertions pin the href to the lines only (`tests/test_pdf_imports_browser.py:71` for k6 and `:120` for v5). Per the escalation rule I did not change those; the restriction keeps them as they are (both pass). The consequence: **today nothing calls `sourceLink` with a full extracted provenance** (a trace input carries only the light provenance, and `showPdfSources` only fetches imported rows), so the new branch is unreachable until SL-07's UI fetches a rebuilt row's provenance. Decide in SL-07 (or review) whether to extend it to imports and update those two assertions.
- **`document.id` was null for extracted transactions.** Fixed here because SC-19 needs the file. No existing assertion pinned `null`.
- **`cells` order:** `word_ids or cell_ids` as the plan says. A native-table row has no word ids (cell ids only); a flagged-page or below-table row has word ids and no cell ids.
- The doc page's own highlight (`showPage`) already lights words named in `?lines=`, so `?lines=<line ids>,<word ids>` highlights exactly the row's words. No change was needed in `document_v2.js` for SL-03 (SC-26 is SL-07's).

## Open issues for later slices
- `tests/test_traces.py` has 3 environment failures (node 18 lacks `--allow-fs-read`) that exist on START_HEAD. Any slice whose gate includes that whole file (SL-05) will see them. They are not caused by this feature.
- SL-07: the statement record view's rows (`tr[data-lines]` in `document_v2.js`) use the record API's line ids; to light a rebuilt row's exact words (SC-26), the record's transaction `locator` (or `GET /api/provenance/transaction/{id}`) `cells` has to be passed to `viewer.highlight` too.
