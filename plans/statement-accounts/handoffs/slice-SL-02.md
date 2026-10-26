```yaml
slice: SL-02
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 0e379a7f44714fae570bdba257bf6b1e90fc8081
end_head: this commit (a commit cannot name itself; see `git log --grep "statement-accounts SL-02:"`)
commit: HEAD of "statement-accounts SL-02:"
checks:
  - command: ".venv/bin/python -m pytest tests/test_statement_rebuild.py -k \"sc13 or sc14 or sc15 or sc16 or sc17 or sc18 or sc20 or sc21 or sc23 or sc27 or sc28\" tests/test_statement_forms.py tests/test_extraction.py tests/test_layout_consumers.py -q"
    exit_code: 0   # 34 passed. The -k also deselects the three other files' own tests, so the whole suites were run next.
  - command: ".venv/bin/python -m pytest tests/test_statement_rebuild.py tests/test_statement_forms.py tests/test_extraction.py tests/test_layout_consumers.py tests/test_pdf_imports.py -q"
    exit_code: 0   # 279 passed (63 in test_statement_rebuild.py: 40 from SL-01, 23 new); no existing assertion changed
  - command: ".venv/bin/python -m ruff check src tests"
    exit_code: 0
escalations: []
```

# SL-02: Record uses the rebuilt rows

## Changed files
- `src/home_manager/documents/extraction.py`
  - `normalize(rebuild=)`: for a statement with `rebuild.available`, the transactions are the rebuilt rows plus the model's rows on the other pages, merged by page (stable). The merge is only done when a page is rebuilt, so every other statement keeps the model's order as before.
    - A model row that cites a rebuilt page decides nothing (FR-20). It is matched one-to-one on (page, date, signed amount) to a rebuilt row, else it becomes a record note (`The reading listed a row the printed columns don't have, on page N: …`). Notes go to `record["notes"]`.
    - The period check also runs on rebuilt rows. The arithmetic check (FR-25) runs when no row was dropped: no model row on another page, and `Rebuild.dropped == 0`.
    - `rebuild.issues` are added to the issues, and `rebuild.notes` to the notes (FR-23's no-layout note).
  - `read`: `rebuilt_pages` (P8: any exception means no page is rebuilt, and `REBUILD_FAILED` goes in the notes once). On rebuilt pages the model rows are not anchored, tables and lines of those pages are left out of `anchor_rows`, the coverage block and `missed_rows`. `anchor_summary` is unchanged. The reading keeps `evidence`, only for a statement PDF whose rebuild didn't fail.
  - `publish`: `rebuild(...)` with the resolved currency and the header's period (`iso_date` of proposed values). An exception gives `REBUILD_FAILED` once and today's reading. A statement's record notes go to `details["notes"]` (P19), and the returned `review_status` is `published["review_status"]` when the ledger gives one (SL-05 adds it).
  - `line_page` helper (`page-N-` prefix).
- `tests/test_statement_rebuild.py`: 23 Record scenario tests through `ExtractionService.run` with `by_schema` stubs (SC-13 to SC-18, SC-20, SC-21, SC-23, SC-27 and SC-28 on the Record side, P8 in `read` and in `publish`, and the arithmetic check turned off by a rejected row).
- `tests/statement_account_fixtures.py`: additive. Stubs made to work through Record (below), plus `classified`, `w_summary`, `w_rows`, `c_summary`, `x_summary`, `q_summary`, `daily_page`/`d2_pages`.

## Mutation check
With the `publish` rebuild call disabled, 18 of the 26 new SC tests fail, so they depend on the change. The file was restored afterwards.

## Fixture and stub adjustments (not expected values)
- **Currency.** The contract says the summary stub leaves the currency missing, "USD from the setting, as today". With no `$` printed, `currency_for` returns None and blocks the publish, so the footer of every native page now reads `…amounts shown in $…`. Record then uses the home currency (USD), with the existing note. Expected values are unchanged.
- **X** prints an extra line `All amounts in USD`, and `x_summary` cites it for the currency. x6's `EUR` means the home-currency path can't apply.
- **Stub citations.** The SL-01 stubs' `evidence_lines` ids do work through Record: native pages cite `page-1-layout-table-1-row-N`, flagged pages cite `page-1-line-K`. Only the summary citations needed fixing: the first line containing the text, since Q repeats `SYNTH BANK`.
- **`w_rows`** (SC-14): every amount is the row's Balance cell, with the column's direction.

## Notes for the verifier and later slices
- **SC-21 variant, daily table alone on page 2.** The page has no rebuilt rows, so it keeps today's reading (FR-23). The rows are s1–s5 only, but the statement shows the reader's `Page 2 PDF layout needs review: unresolved_columns` and the missed-row issue (`3 printed line(s) with a date and an amount aren't in the transactions`) for the daily lines. The contract only asserts the rows. If that issue is unwanted, closing it is a separate decision (it is the existing missed-row check on a balance table).
- **D on one page** (not flagged) also carries the reader's `unresolved_columns` note on page 1, so its status is `needs_review`, but no issue names a daily row.
- **P8 in `publish`:** if the rebuild fails only there, the missed-row check was already skipped on the pages `read` thought were rebuilt. The model rows stand, with the one issue.
- SC-13/16 notes appear in the record's `details.notes`, together with the currency note, not in `issues`. The test reads them from `Ledger.record`, which is what `GET /api/finance/records/statement/{id}` returns.
- The `review_status` still comes from the extraction's own `status`, since `publish_statement` doesn't return one yet (SL-05).
- The whole-suite gate takes about five minutes.

## Open issues
- None blocking. SL-03 (provenance) can read the rebuilt locator `{rebuilt, page, table_id, row, line_ids, word_ids, cell_ids, quotes}` from `financial_evidence_links` for a transaction. The SC-18 test already checks `rebuilt` on those links.
