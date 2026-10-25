slice: SL-05
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 58d9796
end_head: <the commit; see `git log -1`>
commit: <this commit>
changed_files:
  - src/home_manager/finance/provenance.py     # PDF locator -> import {file,row,page,table,continued_from} and document {id,page,lines,cells}
  - src/home_manager/app/static/trace.js       # page-form badge, "continued from page M", Open source link, lazy fetch of the full provenance
  - tests/test_pdf_imports.py                  # 3 sc22 tests (K, V below-table row, CSV unchanged)
  - tests/test_pdf_imports_browser.py          # new; 2 sc22 browser tests
  - plans/account-import-pdf/handoffs/slice-SL-05.md
checks:
  - command: ".venv/bin/python -m pytest tests/test_pdf_imports.py -k sc22 -q"
    exit_code: 0   # 3 passed
  - command: ".venv/bin/python -m pytest tests/test_pdf_imports.py -q"
    exit_code: 0   # 130 passed
  - command: ".venv/bin/python -m pytest tests/test_provenance.py tests/test_traces.py -q"
    exit_code: 1   # 3 failed, 23 passed. The same 3 fail at START_HEAD (git stash): test_traces.py tax/family tests, the sandbox's node rejects --allow-fs-read. Not touched by this slice.
  - command: "RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_pdf_imports_browser.py -k sc22 -q"
    exit_code: 0   # 2 passed
  - command: "RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_trace_components_browser.py -q"
    exit_code: 0   # 2 passed (provenanceBadge and the CSV badge text unchanged)
  - command: ".venv/bin/ruff check src/home_manager/finance/provenance.py tests/test_pdf_imports.py tests/test_pdf_imports_browser.py"
    exit_code: 0
  - command: ".venv/bin/python -m mypy"
    exit_code: 1   # "Found 8 errors in 1 file": the baseline core/paths.py errors only
escalations: []


## Interfaces as built

`provenance_for(db, "transaction", id)` for a row whose first evidence link's locator has `table_id` (a PDF row):

- `provenance.kind = "imported"`.
- `provenance.import = {file, row, page, table, continued_from}`. `continued_from` is the heading page (int) or `null`.
- `provenance.document = {id, page, lines, cells}`:
  - native row: `lines = cells = cell_ids`.
  - rebuilt, continuation or below-table row: `lines = line_ids`, `cells = word_ids`.
  - `id` is the locator's `document_id`.
- A CSV locator (`rows`) is unchanged: `import = {file, row}`, `document = null`.

Observed values (tests): K's k5 is `table = page-2-import-continuation`, `row = 1`, `page = 2`, `continued_from = 1`. V's v5 is the native table's id, `row = 5`, no `cell_ids`, `word_ids` and `line_ids` set. Line and word ids look like `page-2-layout-line-N` and `page-2-layout-word-N`.

`trace.js`:

- `provenanceBadge`: `Imported · <file> page N[ · continued from page M]` when `import.page` is set, else the old `row N` text.
- `sourceLink(prov)`: the existing "Open source" link, extracted. It targets `#/documents/<id>?lines=<document.lines>`.
- `showPdfSources(rows)`: after the inputs render, for each imported transaction input whose light provenance has no `import`, it fetches `/api/provenance/transaction/<id>` (3 at a time). It replaces the badge and adds the link only when `import.page != null`, so CSV and XLSX rows keep their bare `Imported` badge and get no link. A failure leaves the light badge.

## Deviations and notes for the orchestrator

1. **Trace inputs carry only a light provenance** (`light()` gives kind and record; `import` is never filled in a real trace). docs/ui.md says "the page fetches the full one", but `trace.js` did not. The badge therefore needed the fetch above (a UI call to an existing endpoint, no API change). Cost: one request per imported transaction input in an open breakdown (up to 200). Server-side enrichment would avoid that, but `tools.py` and `core/trace.py` are outside this slice.
2. **`document.cells` holds word ids for rebuilt rows.** The plan names `document {id, page, lines, cells}` but not what `cells` holds for a row with no native cells. SC-22 step 1 asks for word ids in the API, so they are carried there.
3. **The browser test uses k6, not k5.** k5 is a transfer, so no spending or cashflow trace lists it. k6 is also on page 2 and continued from page 1. The API test uses k5 as the contract says. The second browser test covers V (a native row and the below-table row, both linking by `lines`) and a CSV row (bare `Imported`, no link).
4. The browser test clicks the link and checks that the page-2 preview opens with the row's words lit.
5. docs (docs/ui.md "Provenance", docs/documents.md) are not updated; they are outside the permitted files (SL-08 owns docs).
