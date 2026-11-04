```yaml
slice: SL-05
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 5b94f11
end_head: 35e40b7   # the code commit; the handoff fix is committed right after it
commit: 35e40b7
checks:
  - command: ".venv/bin/python -m pytest tests/test_paystub_engine_record.py -k pay_tables -q"
    exit_code: 0   # 3 passed
  - command: "RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_paystub_engine_browser.py tests/test_document_v2_browser.py -q"
    exit_code: 0   # 11 passed (2 new, 9 existing)
  - command: ".venv/bin/ruff check src tests"
    exit_code: 1   # only the 2 errors that exist at START_HEAD (tests/test_document_v2_browser.py:410, tests/test_receipt_kinds.py:977); my files are clean
  - command: ".venv/bin/python -m pytest tests/test_paystub_engine_record.py tests/test_layout_consumers.py tests/test_paystub_forms.py -q"
    exit_code: 0   # 110 passed (extra regression run for the run-result change)
escalations: []
```

# SL-05 handoff: `pay_tables` in the run result and the engine's Tables tab

## What was built
- **`documents/extraction.py`** (`pay_tables_for_viewer`, `viewer_row`, `viewer_cell`, `viewer_box`; called in `run` after the split handling): the extraction run result gains a top-level `pay_tables` (absent keys never: `[]` when the engine failed). One entry per adapted table **per page it covers** (a one-page table is one entry; `id` repeats across pages, rows are that page's rows): `id`, `page`, `roles` (cell index → hours/rate/current/ytd/other; JSON keys are strings), `header_rows`, `rows` (`id`, `line_id`, `total`, `cells` with `id`, `quote`, `word_ids`, `line_id`) and `guesses` (the guess texts about that table, on the first page entry only). The summary box follows in the same shape: a header row of its named columns (printed heading words, else Gross/Taxes/Deductions/Net), a this-period and a year-to-date row, `roles` naming each column gross/taxes/deductions/net. Guess texts come from the engine's guesses (FR-58/59/75) **and** the readings' guesses Record made (`group_guessed`, FR-62), keyed by table id, deduplicated.
- **`app/static/trace.js`**: `setEngineTables(tables)` (stores and redraws). Pages with an engine table show it instead of `layout_context` tables (and vision tables) for that page; caption "Page N · Table k · Read from the printed columns"; header cells carry a `.sv-role` label (`data-role`); total rows get the existing `muted` class; cells with `word_ids` are find-cell buttons that highlight the cell's **word ids** (only that word lights) and tell the cell's line; guesses render as a `ul.muted.small.sv-guesses` under the table. `highlight` now also recognises a native page by a word id (needed for word-id highlights).
- **`app/static/document_v2.js`**: the new `doc2EngineTables` is called from `doc2Extraction` with `run.result.pay_tables` (also `[]` when the file has no extraction run); it redraws the viewer only when the tables change. `doc2Forms` now shows `record.details.notes` for `income_record` too.
- **`app/static/style.css`**: two small rules, `.sv-role` (block, normal weight) and `.sv-guesses` (spacing). No inline style, no new asset.
- **`docs/ui.md`**: the `sourceViewer` row in the component table describes `setEngineTables`, the pay stub Tables tab and the notes; no headings changed.

## Deviation from the plan text, with reason
P11 says the document page calls `setEngineTables` "after an extraction run loads" next to `viewer.update` in `doc2ShowRun`. `doc2ShowRun` loads the *parse* (receipt) run; `pay_tables` is in the *extraction* run result, so the call is in `doc2Extraction` (`document_v2.js`), which loads it. Initial draw shows the printed tables until the extraction run arrives, then redraws.

## Tests
- `tests/test_paystub_engine_record.py` (+3, all `-k pay_tables`): PS shape (roles `{1: hours, 2: rate, 3: current, 4: ytd}`, header, ten rows with the totals flagged, cell texts = the contract's PS table, word ids spell the quote, blank cells hold no words, no guess, no box); B1's single guess text equals the record's columns-guessed note and contains "left column"; SB's box in the same shape (header Gross Pay/Taxes/Deductions/Net Pay, the two value rows, roles).
- `tests/test_paystub_engine_browser.py` (new, opt-in, +2): SC-71 steps 1–4 and SC-61 b1 (one engine table with the caption, role labels Hours/Rate/This period/Year to date, ten rows, four muted total rows, every figure equals the run result's text, choosing `2,500.00` lights exactly that word, B1's guess shown under its table and, in the record panel, in `.doc2-notes`; no page error, CSP violation or request outside the app); SC-54 step 4 (the wrapped Federal line's Find lights the words of both lines; its this-period value button lights `295.63`).

## Notes for the orchestrator
- Multi-page tables are emitted once per page (see above); SL-07's `pay_parts` per-part engine tables should keep calling the same builder on the file-wide reading.
- `PaystubTables.viewer` (empty field "Filled with the tables tab's data by a later slice") is still unused; the data is built in `extraction.py` as the slice row says. Can be deleted by a later slice.
- No change to `table_engine.py`, the statement path, spec, contract or plan.
