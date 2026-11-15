```yaml
slice: SL-08
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 4fa0f04
end_head: c0cc970   # the last code commit; the handoff itself is committed on top of it
commit: c0cc970     # code commits: 7ed5fc5, c0cc970
checks:
  - command: "RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_receipt_items_browser.py tests/test_document_v2_browser.py -q"
    exit_code: 0     # 21 passed (2m15s), run before the unused-name fix below
  - command: "RUN_BROWSER_TESTS=1 UI_SHOTS_DIR=/tmp/sl08-scratch/after .venv/bin/python -m pytest tests/test_receipt_items_browser.py tests/test_document_v2_browser.py -q -k 'sc07 or sc15 or sc18'"
    exit_code: 0     # 4 passed
  - command: "RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_document_v2_browser.py -q -k sc15 (after the last commit)"
    exit_code: 0     # 1 passed
  - command: ".venv/bin/python .claude/skills/ui-redesign/scripts/ui_shots.py --routes 'document/{receipt_doc}' --widths 390,1440 --out /tmp/sl08-scratch/{before,after}-document"
    exit_code: 0     # both runs; see Open issues for a traceback the seed prints
  - command: ".venv/bin/ruff check src tests/test_receipt_items_browser.py tests/test_document_v2_browser.py tests/dining_receipt_fixtures.py"
    exit_code: 1     # one finding, I001 at test_document_v2_browser.py:421 (_newer_reading), not mine
  - command: "git diff --exit-code 4fa0f04 -- tests/dining_receipt_data"
    exit_code: 0
escalations: []
```
SL-08 is built: the page reads the server's fields and calculates nothing. No server change, no migration.

## What was done
- `app/static/receipt.js` `ledgerRows`: the Category column is left out when `record.category_column === false` (the Code/Paid filters are unchanged, and the footer spans are computed from the same column list, so they line up). The footer's Tip row carries `record.tip_note` as a small muted line (`.tip-note`) under its label. "Not matched to an item" already follows `record.unmatched_minor` (SL-05 makes it exclude the tip), so it needed no change.
- `app/static/trace.js` `renderLines`: `data-indent` is set from `line.indent` when it is 1 or 2 (absent, 0 or unknown: no attribute).
- `app/static/style.css`: `.sv-line[data-indent="1"|"2"]` inline-start padding = `--space-2` + 1 or 2 × `--space-4`; `.ledger-rows .tip-note`.
- Tests: `tests/dining_receipt_fixtures.py` gains `record_dining` and `dining_seed` (household USD; breakfast B0 and B8, read with their indents, recorded through the real path). `tests/test_receipt_items_browser.py`: `test_sc07_sc18_a_dining_receipt_has_no_category_column_and_its_footer_leaves_out_the_tip` (SC-07 step 1, SC-18 (b), the FR-02 note), `test_sc07_a_grocery_receipt_keeps_its_category_column`. `tests/test_document_v2_browser.py`: `test_sc15_text_view_indentation` (lines 11–14 and 16 indent 1, others at the edge, text equals the stored text, "No Allergies" matches line-11 and line-16 only, reload, plus a reading with no indent keys and B8 showing none).
- "Find" in SC-15 step 3 is a locator text match on the Text view's lines: the viewer has no text search box.

## Screenshots (synthetic data only, under /tmp/sl08-scratch, not committed)
- Regression shots, shared seed (`document_14`, light and dark): `before-document/document_14-{390,1440}-{light,dark}.png` and `after-document/…` (same names).
- Breakfast receipt from the extended browser tests (`after/`): `dining-b0-page-1440.png`, `dining-b0-page-390.png`, `dining-b0-text-1440.png`, `dining-b0-text-390.png`, and `dining-b8-page-1440.png`. No "before" of the breakfast receipt exists: the old code has no indent field to show.
- I looked at `dining-b0-text-1440` and `dining-b0-page-390`: indented side lines, no Category column, the Tip note in the footer, no horizontal overflow at 390 (also asserted).

## Open issues
- `ui_shots.py` prints a `receipt_service.py` traceback (a `ValueError` from a read child) for one seeded document, at START_HEAD and after; the shots are still written. Not investigated: outside the slice.
- The existing I001 ruff finding in `test_document_v2_browser.py` (`_newer_reading`) is left as it was.
- The document page's own Tip field (`document_v2.js`) does not show the note; only the footer does, as the plan says.
- Not run (outside the slice's command): the full suite, the non-browser tests.
