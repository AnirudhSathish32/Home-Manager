```yaml
slice: SL-03
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 87ddb70
end_head: f941f76   # the code commit; the handoff file is committed right after it
commit: f941f76
checks:
  - command: ".venv/bin/python -m pytest tests/test_paystub_engine_record.py -k \"sc50 or sc51 or sc52 or sc53 or sc54 or sc55 or sc57 or sc58 or sc59 or sc63 or sc65 or sc66 or sc69\" -q"
    exit_code: 0   # 17 passed (2 more tests in the module, the engine-on-existing-payslips ones, are not selected by -k and pass in a plain module run)
  - command: ".venv/bin/python -m pytest tests/test_paystub_forms.py tests/test_layout_consumers.py tests/test_paycheck.py tests/test_vision_tables.py tests/test_extraction.py tests/test_provenance.py -q"
    exit_code: 0   # 141 passed, no existing test changed
  - command: ".venv/bin/python -m pytest tests/test_paystub_engine.py tests/test_table_engine.py -q"
    exit_code: 0   # 498 passed (218 engine + 280 phase 1); table_engine.py and test_table_engine.py have no diff
  - command: ".venv/bin/ruff check src tests"
    exit_code: 1   # only the 2 errors that exist at START_HEAD (tests/test_document_v2_browser.py:410, tests/test_receipt_kinds.py:977); my files are clean
escalations: []   # none blocking; the deviations below need the orchestrator's eye (D1 – D6)
```

# SL-03 handoff: Record reads text-PDF pay stubs from the pay engine's cells

Files: `src/home_manager/finance/paystub_tables.py` (`adapt`, `for_lines`, new fields), `src/home_manager/documents/extraction.py` (P7.1, 1a, 2, 3, 7, 8, 9, 11), `src/home_manager/documents/pay_tables.py` (three small additive changes, D1), `tests/test_paystub_engine_record.py` (new, 19 tests). `finance/ledger.py` needed no change (D7). Not committed: `plans/.../progress.yaml` (untracked, orchestrator-owned).

## What now happens
`run` classifies, and for a `paystub` with `evidence.pages` calls `paystub_tables.read(evidence)` once inside `try`; on any exception it logs `log_failure(log, "pay table read", exc, run=run_id)` (class and run id only) and passes the sentinel `extraction.PAY_FAILED`. `read(..., *, pay=None)` (keyword-only; module-level calls only, so `test_layout_consumers.py`'s fake-`self` call is unchanged) then:
- `for_lines(pay, part line ids)` keeps the part's rows, totals, boxes, unplaced, other tables and guesses; `pay_tables_of` replaces printed tables on engine pages (file-wide) by the adapted ones and keeps only the part's rows of other tables.
- layout-review notes (`pay_layout_notes`): only for pages holding the part's lines, and none for a page with an engine table whose only layout issue is `unresolved_columns` (P7.1a).
- `printed_columns` is the set of line ids on pages with neither an engine table nor any printed table (empty = off); `column_checks(..., scope)` and `anchor_paystub(..., flat=)` use it (FR-64).
- `anchor_paystub` works on `source == "pay_engine"` tables: roles from `table.roles` (`paystub_columns`, `role_column`), `by_line` maps every `row.line_ids`, `cited_row` counts distinct rows, `totals_row` also finds taxes and deductions totals (and a gross/net total wins over the model's citation, as for printed tables), native-shaped references (`source: "pdf_text"`, word ids, the native cell id when the row is one projected row), a wrapped label's other lines are added to the pay line's evidence, and heading/label cites are one per line (`cell.cites`).
- Record notes: `reading["record_notes"]` (the engine's guess texts, FR-65 note, FR-64 note per page without a table) and `reading["guesses"]`; `publish` adds them to `record_notes` and, for pay stubs, stores `details["notes"]` / `details["guesses"]`. Nothing new goes into `notes`/`issues`.
- `EXTRACTION_VERSION = "typed-extraction-v35-paystub-engine"`.

Adapted table (verified interface): `SimpleNamespace(id "page-N-pay-K", page, pages, source "pay_engine", header_rows [one row], rows, roles {cell index: role}, spans)`. Row: `(id "<table>-row-<r>", line_id, line_ids, cells, total, kind, label, section, page)`; cell 0 is the label; `cites` on a multi-line label or heading. `PaystubTables` gained `adapted`, `engine_pages`, `lines_of`, `line_pages`, `fallback_pages`.

## Deviations and decisions to review
- **D1: three additive changes to SL-01's `pay_tables.py`.** Existing tests that must pass unchanged exposed engine gaps: (a) `split_tails`: a second label printed < 1.5 font sizes after the first group's last amount shares that amount's run (`52,000.00 Federal Income Tax`), so the tightly padded side-by-side payslip read as one 4-column table with wrong rows (money in the wrong cells); the tail now starts its own run when amounts follow. (b) `under`: an amount mostly inside exactly one column's extent but not aligned with it (`300.00` under a column whose first amount chose left alignment) was a silent `stray`; it is now placed. (c) `PayColumn.label_words` (heading word ids, so a heading can be cited, FR-66). All 218 engine tests still pass; two new engine-level tests pin (a) and (b) with the existing payslip's printed literals.
- **D2: trust gate (`fallback_pages`), not in the plan.** The ruled sectioned payslip (`test_a_sectioned_payslip_*`) is read with its right block's columns all `other` (no usable heading, and FR-57 b's "rows since the previous section title" never equals the grand total); its rows would carry no money. A page with a pay table none of whose columns is current/ytd/hours/rate is not engine-read: the printed tables stay, and the FR-64 note is added. Contract fixtures are unaffected (SL-02 engine tests and all SC tests pass). The sectioned payslip also shows FR-51's cost: whole-number hours (`80`) are label text, so the engine can't see them; the gate is what keeps that stub on today's path. Worth a look in SL-04/R-A: a stub with integer hours and no other failure would lose its hours/rate on the engine path.
- **D3: the model is told engine tables are `pdf_text`.** `test_native_paystub_reaches_ledger_search_and_source_cells` asserts every `reported_tables[0].source == "pdf_text"` in the requests; `paystub_table_context` maps `pay_engine` to `pdf_text` (the cells are the printed page's own). Internally `source` stays `pay_engine`.
- **D4: `spans` for chunking.** A printed table's section-title and blank rows are rows, so `paystub_chunks` kept them inside one question; engine tables expose `spans` (evidence lines from first to last row) and `paystub_chunks` counts them as covered, so the existing sectioned-payslip stubs (one question per table) still match. This is the same chunking as today, not a new rule.
- **D5: flat checks per page.** `column_checks` reads the printed header only from the judged (table-less) lines, and `anchor_paystub` no longer leaves out a multi-amount value that cites a table-less page (`flat`), so `column_checks` is the one judge there. Without both, SC-59's prose line (one amount, page 1's `Current`/`YTD` header) would be judged by page 1's header and a swapped flat line would be nulled by the "multiple amounts" rule instead of FR-33. Pages with no engine table and a printed table are unchanged (not in the set).
- **D6: `cited_label` accepts a label spread over several cites** (`text in " ".join(all quotes)`, each cite still printed in its line). Needed for a wrapped label (SC-54) and a two-line heading (SC-51). A label that fits one quote passes as before.
- **D7: `ledger.publish_income` unchanged.** It already stores `record["details"]` whole; `publish` puts `notes` and `guesses` there (as statements do). `Ledger.record("income_record")["details"]` returns both.
- **C-no-feature-review** in the tests ignores the reader's own "Page N PDF layout needs review: …" issues (they name `unresolved_columns` and are not this feature's); SC-59 asserts that page 2's layout-review issue is still there.
- **SC-65** confirms the second stub with `Ledger.review(…, "verified")`, the function the review API calls; the "previous version" records are made by monkeypatching `EXTRACTION_VERSION` and the engine fault, so the first reading takes today's path (FR-65 note), and Extract again shows the note gone (engine) and the confirmed record byte-identical.
- **SC-66** compares `income_records`, `income_lines`, `document_segments` and the set of evidence locators across `Extract` and `Extract again (force)`, dropping only timestamps, run ids and source keys; the evidence link table gains one link per run by design, so it is compared as a set. The MINI three-stub file is SL-07's.

## Not in this slice (as assigned)
Unclassified rows with guessed groups, section-total mismatch notes, unplaced notes, the summary box in Record (the box is read and its guess notes are carried, but gross/net/taxes/deductions come from totals only), `pay_tables` viewer data and UI, splitting. SC-60, SC-61 (records of guesses), SC-62, SC-70 are SL-04.

## Tests
`tests/test_paystub_engine_record.py`: SC-50 (plus a shuffled content stream, C-docs, C-model-calls, the model shown engine cells), SC-51, SC-52, SC-53, SC-54 (locator lists both lines, provenance and the Federal line cite the printed words), SC-55 and its `unresolved_columns` / no-layout-review test, SC-57 a and b, SC-58, SC-59 and its table-less swapped-flat-line test, SC-63 (note, today's path, one log record naming the class and no fixture word), SC-65, SC-66 (single stub), SC-69, and two engine-level tests on the existing payslip fixtures. The double answers each question with the entries whose cited line lies in that question's lines, so chunking needs no hand-written order; expected values are the contract's literals (`tests/paystub_engine_fixtures.py`) and the swapped summary is derived from the fixture rows, never from the code.
