```yaml
slice: SL-04
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 3e1f752
end_head: 74feadf   # the slice's commit; this handoff is committed on top of it
commit: 74feadf
changed_files:
  - src/home_manager/finance/paystub_tables.py     # P4: untrusted pages -> pages_without_tables; fallback_pages removed
  - src/home_manager/documents/extraction.py       # P4: pay_tables_of / PAY_FAILED drop pdf_text tables; EXTRACTION_VERSION v36
  - scripts/statement_diagnose.py                  # prints untrusted_pages(pay)
  - tests/test_paystub_cleanup.py                  # sc90 (record), sc92 (x2), sc93, sc97, mixed text-and-scan file
  - tests/test_paystub_engine_record.py            # SC-63 test rewritten (SC-93); one assertion in the SL-02 rewritten test
checks:
  - command: ".venv/bin/python -m pytest tests/test_paystub_cleanup.py tests/test_paystub_engine_record.py tests/test_paystub_split.py tests/test_layout_consumers.py tests/test_paystub_forms.py tests/test_vision_tables.py tests/test_extraction.py -q"
    exit_code: 0   # 198 passed (3 min 22 s)
  - command: ".venv/bin/python -m pytest tests/test_paystub_engine_generator.py -k probe -q"
    exit_code: 0   # 4 passed
  - command: ".venv/bin/python -m ruff check src scripts tests/test_paystub_cleanup.py tests/test_paystub_engine_record.py"
    exit_code: 0
  - command: ".venv/bin/python -m ruff check src scripts tests"
    exit_code: 1   # only the 2 pre-existing errors (tests/test_document_v2_browser.py, tests/test_receipt_kinds.py)
  - command: "revert-and-fail R1 – R4 (below), temporary edits restored from backups"
    exit_code: 1   # each reverted run fails the named tests
escalations: []
```

# SL-04 handoff: one path for text-PDF pay stubs (FR-93, FR-94, FR-95, FR-99)

## What changed

`finance/paystub_tables.py`
- `fallback_pages` is removed. `untrusted_pages(pay)` stays as the test of "a pay table the engine trusts" (now via a small `distrusted_pages(tables, roles)`).
  `read` puts those pages in `pages_without_tables` and out of `pages`, so `for_lines`, `adapt` and Record's `NO_PAY_TABLE` note (FR-64) treat them as flat.
  `for_lines` no longer unions `fallback_pages`.

`documents/extraction.py`
- `EXTRACTION_VERSION = "typed-extraction-v36-paystub-one-path"` (FR-99).
- `pay_tables_of` drops every `source == "pdf_text"` table on every page (new `without_printed_tables`), keeps vision tables (no `source`) filtered to the part's
  lines, plus `part.adapted`. The old "skip tables on engine pages" test is gone: it only ever covered printed tables.
- With `PAY_FAILED`, `read` applies `without_printed_tables`, and `printed_columns` is the set of the part's lines on pages no remaining table covers
  (every native page, scanned pages with a vision table keep theirs). Same set logic as the engine case, so `column_checks` judge those lines (FR-94).
- The `Classification` request (`reported_tables` before the kind is known) is unchanged. `anchor_paystub`, `paystub_columns`, `role_column` and the grid
  branches are untouched.

`scripts/statement_diagnose.py`: prints `sorted(paystub_tables.untrusted_pages(pay))`. The probe test in `tests/test_paystub_engine_generator.py` only runs the
script and checks redaction, so it needed no edit; it passes.

## Tests

`tests/test_paystub_cleanup.py` (new in this slice):
- `test_sc90_the_sectioned_payslip_record_has_the_same_values_from_engine_cells_and_one_total_note`: the parity test's stubs and assertions, plus no "Page 1: no pay
  table" note, exactly one "doesn't match" note naming 28,434.00 and 28,314.00 and not 1,354.00, and C-no-grid (`check_no_grid`).
- `test_sc92_a_page_whose_table_the_engine_does_not_trust_is_read_like_flat_text` (the contract's two-page MINI(13) + other-table fixture): Adjustment recorded with
  the model's 5000, FR-64's note, MINI(13)'s values, C-no-grid.
- `test_sc92_m4_…`: a hand-built untrusted case (`decide` patched so page 2's table is a pay table whose roles are all `other`): page in `pages_without_tables`,
  not in `pages`/`engine_pages`/any adapted table, also through `for_lines`.
- `test_sc93_with_the_engine_down_a_wrongly_swapped_amount_is_nulled_by_the_flat_rules_on_every_page`: engine raises, one earning's amounts swapped: nulled by
  `column_checks` with the "doesn't match the printed columns" issue, all other lines right, no `cell_evidence`, no table shown after the classification.
- `test_sc97_…`: a stub recorded at v35 is re-read (new run, `created`), a reviewed one's `income_records`/`income_lines` rows are byte-identical.
- `test_a_scanned_page_of_a_text_pdf_stub_keeps_its_vision_tables_beside_the_engine_page` (M3): page 1 text (engine cells `page-1-pay-1`), page 2 a scan whose
  transcription has a table; the model is shown `page-2-table-1` and no `layout-table` id; the page-2 Bonus line is recorded (10000 / 50000).

`tests/test_paystub_engine_record.py`: `test_sc63_…` rewritten per SC-93 (renamed `…reads_like_flat_text…`): the model gives correct amounts as `PayLines`
(hours and rate as printed), asserts FR-65's note, `expect(record)` (EXP-PS), no `cell_evidence`, no `layout-table` shown after the classification, and the
unchanged log assertions. In `test_the_sectioned_payslip_page_is_trusted…` (already SL-02's rewrite) `found.fallback_pages == set()` became
`paystub_tables.untrusted_pages(found) == set()`.

Unit tests of removed code: none edited or removed (the only reader of `fallback_pages` in tests was the line above, an SC-94-listed test).
`test_sc65_…` and `test_sc50_…` still pass unchanged: SC-65's docstring says "today's path" and its engine-down stubs now get no PayLines, which it doesn't assert on.

## Revert-and-fail (temporary, restored)

| Edit | Failing tests |
|---|---|
| R1 `without_printed_tables` returns every table | sc90 record, sc92, sc93, mixed, SC-63 (5 of 6 selected; m4 unaffected) |
| R2 `PAY_FAILED` no longer drops printed tables | sc93, SC-63 |
| R3 untrusted pages not added to `pages_without_tables` | sc92 m4 |
| R4 version back to v35 | sc97 |

## Remaining uses of `fallback_pages`
`grep -rn fallback_pages src scripts evals tests docs` finds none. Nothing in `evals/` needs SL-05 for this.

## Open issues
- `printed_columns` for `PAY_FAILED` is only set when the part's classification is still `paystub`; a part re-classified to another kind keeps the old flat behaviour.
- Docs (FR-97) and the evals' legacy reader are SL-05's; I did not touch them. The explicit docs heading cited in new comments is `docs/documents.md "Pay stub rows from the printed columns"` (exists).
- A summary box on an untrusted page would lose the missing-table note (the page is excluded from `without` when a box sits on it); no fixture has this.
