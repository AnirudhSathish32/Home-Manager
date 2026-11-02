```yaml
slice: SL-04
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: d47a195
end_head: 2d8344b      # the code commit; the handoff commit follows it
commit: 2d8344b
changed_files:
  - src/home_manager/app/static/receipt.js
  - src/home_manager/app/static/document_v2.js
  - tests/test_receipt_items_browser.py
checks:
  - command: "RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_receipt_items_browser.py -q"
    exit_code: 0            # 7 passed (5 existing + sc19 + sc15_footer); sc19/sc15 fail with the JS stashed
  - command: "RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_planned_bugfixes_browser.py tests/test_document_v2_browser.py -q"
    exit_code: 1            # 8 passed, 2 failed; both failures are pre-existing (same assertion at START_HEAD, see below)
  - command: ".venv/bin/ruff check src tests"
    exit_code: 0
escalations: []
```

## What changed
- `receipt.js`: Paid shows `row.table.tax_note`, else "with tax" when `table.tax_included` (as before). A row with `tax_code` gets `tr.title = "Tax code BF"`.
  When `record.tax_lines_used`, each tax line is listed under Tax (`taxLineRow`), sorted by code then position: label `B · 7.75% on $46.19` (rate and taxable left out when not printed; the taxable
  is `amount()` of the server's `display.taxable_minor`), amount in the `line_total` cell, `sourceButton` with aria-label "Find B tax line". The Tax row keeps its Correct button.
  `record.tax_issues` render under the table as `.item-warning` paragraphs after the "Doesn't add up" note, whatever the review status.
- `document_v2.js`: `doc2Issues(record)` drops `record.tax_issues` from `record.issues`; both `doc2Why` call sites (doc2Ledger, doc2Other) use it before the length check.
- No CSS, no new tokens (ui-ux-pro-max consulted: no new visual element beyond table rows using existing classes). Money is the server's text via `amount()`; DOM nodes only.
- `tests/test_receipt_items_browser.py`: `tax_seed` (R0, the SC-04 variant with `TAX $2.84`/`TOTAL $62.02`, SC-15's two B lines; USD), `test_sc19_tax_lines_and_codes`
  (P-checks by SQL; Paid notes; tooltips; no new column; footer rows with Find, geometry; Find on B lights the B line; Correct on Tax; reload and DB unchanged; NO_OVERFLOW at 390/768/1440;
  SC-04 variant: one Tax line $2.84, "with tax" notes, the reason shows once as `.item-warning` and not in `#doc2-why`), `test_sc15_footer_three_tax_lines`.
  Footer labels use the server's rate text ("2.17%", "1.58%" for SC-15's printed rates).

## Pre-existing failures (same assertion at START_HEAD with my JS and test changes stashed)
- `tests/test_planned_bugfixes_browser.py::test_idle_badge_read_filter_and_record_selected`: `#rc2-table tbody tr` count 0 (line 108).
- `tests/test_document_v2_browser.py::test_document_page_states_find_correct_and_decide`: `.cc-preview-row` not visible (line 320).

## Screenshots (synthetic, outside the repo; light theme, 390 and 1440 px)
- `/tmp/rtc-sl04-shots/{before,after}-{r0,r4,r15}-{390,1440}.png` (R0, SC-04 variant, SC-15; made by `/tmp/rtc-sl04-scratch/shots.py`, because `ui_shots.py`'s household seed has no tax lines).
- `/tmp/rtc-sl04-shots/ui_shots-{before,after}/documents_14-{390,1440}-light.png`: `ui_shots.py` on the household receipt (unchanged page; no horizontal overflow reported).
