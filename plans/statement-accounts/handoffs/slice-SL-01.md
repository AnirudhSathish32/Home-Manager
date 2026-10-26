```yaml
slice: SL-01
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: f3fad94
end_head: this commit (a commit cannot name itself; see `git log --grep "statement-accounts SL-01:"`)
commit: this commit, the one on top of f3fad94
checks:
  - command: ".venv/bin/python -m pytest tests/test_statement_rebuild.py -k \"pcheck or rows or sc27 or sc28 or fr30_edge\" tests/test_pdf.py tests/test_pdf_layout.py tests/test_pdf_imports.py -q"
    exit_code: 0   # 97 passed. The -k also deselects the three PDF files' own tests, so the whole suite was run again next.
  - command: ".venv/bin/python -m pytest tests/test_statement_rebuild.py tests/test_pdf.py tests/test_pdf_layout.py tests/test_pdf_imports.py -q"
    exit_code: 0   # 230 passed (40 new, 190 existing, unchanged)
  - command: ".venv/bin/python -m ruff check tests src"
    exit_code: 0
escalations: []
```

# SL-01: rows rebuilt from the page, FR-30, fixtures

Resumed from a worker cut off by a rate limit. I treated its uncommitted diff as a draft and checked it against the plan and the real reader.

## Changed files
- `src/home_manager/finance/pdf_import.py`: `PageView.runs`/`texts`, `joined_amounts` and the FR-30 change in `visual_row` (D6's exception (a)/(b), P18's rejection), `ANALYZER_VERSION = 2`.
- `src/home_manager/finance/statement_rows.py` (new): `rebuild`, `rebuilt_pages`, `Rebuild`, `Reading` (FR-27 balance tables and section cuts), year/date-order rules, duplicates.
- `tests/test_pdf.py`: `make_pdf` only, the optional fifth item element (text matrix). No assertion touched.
- `tests/statement_account_fixtures.py` (new): builders S, S-flag, S2, D, D-flag, T, T-edge, W (W′, W″ by `shift`), C, C0, X, Q, M; expected values; the stubs (`s_bad_rows`, `s_summary`, `s2_summary`, `reading_lines`).
- `tests/test_statement_rebuild.py` (new): 40 tests (`pcheck_*`, `rows_*`, `fr30_*`, `sc27`, `sc28`, `stubs_*`).

## Kept or replaced from the partial diff
- **Kept, after checking against the plan and running it on every fixture:** `statement_rows.py` (one redundant ISO line in `placed` removed), the `pdf_import.py` changes, and the `make_pdf` matrix item. Without FR-30, s1–s3 are rejected ("doesn't fit a column"); the test `sc27_without_fr30...` shows that.
- **Written new:** the fixtures and the tests (the draft had neither). The existing PDF tests are unchanged; the `tests/test_pdf.py` edit changes no existing assertion.

## Notes for the verifier and SL-02
- **S-flag triggers:** two *different* overlapping words at one position (`STAMPED`/`OVERLAID`) plus a rotated word via the matrix give `overlapping_text` and `unsupported_text_rotation` (and `unresolved_columns`), as the plan expected. They are printed below the footer, so the table's visual rows are untouched. No reader-trigger substitution was needed.
- **P17:** the fixtures print the contract's lines with the period (or `Card number …` for C0) last. `pcheck_title_lines` asserts no transactions table's title names a balance.
- **D (not flagged):** the real reader builds no native table for the daily `Date | Amount` rows (it never does for dated/amount-only rows), so they stay visual rows under a `DAILY ENDING BALANCE` title. The cut still excludes them; rows are s1–s5 with no issue. `pcheck_d` asserts the daily heading is its own heading and the title names a balance.
- **X:** the reader builds no native table (a straddling amount), so x1–x6 are rebuilt rows 0–5 on page 1; the issues read `Page 1 row 1…5`. Reasons are PDF import's own (x5 `The amount "1.2.3" can't be read.`, x6 `The amount "4.00 EUR" is not in USD.`).
- **T-edge:** `12.34` at x 268 (T is 272). `pcheck_t_edge` asserts the four placements plus that `place` says it fits; `fr30_edge` asserts the P18 reason, one issue, and s1–s5 unchanged.
- **PDF-import preview by `account_id`:** `sc27`/`sc28` reuse the `env` fixture and the `no_network` guard from `test_pdf_imports.py` (imported), and call the real preview route on account "B" (savings) with `year=2026`.
- **Stubs are provisional for SL-02.** They cite `evidence_lines(result)` ids (`page-1-layout-table-1-row-2`, `page-1-layout-line-3`, …) and are checked only against the reading's lines here, not through `ExtractionService`. SL-02 may need to adjust the citations to what the model is actually shown.
- `Rebuild.dropped` is an extra field beyond the plan's dataclass (rows rejected or left out, for FR-25's arithmetic check).
- The plan's verification command applies `-k` to all four files, so the three PDF files' tests are deselected by it; I ran them whole separately (above).

## Open issues
- None blocking. The M scanned-page P-check is in `test_pcheck_m...` and runs the vision stub; `rows_*` tests do not cover FR-25/FR-26 (SL-02).
