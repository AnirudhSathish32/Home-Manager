```yaml
slice: SL-02
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: b5427c8
end_head: bfbbc04        # the slice commit; the handoff itself is committed after it
commit: bfbbc04
changed_files:
  - src/home_manager/app/static/receipt.js              # ledgerRows receipt branch, RECEIPT_COLUMNS, receiptCell
  - tests/test_receipt_items_browser.py                 # new: sc02, sc11 (steps 1-3), sc12, sc20
  - tests/test_planned_bugfixes_browser.py              # :44,:46 scoped to the Line total cell (R-e)
checks:
  - command: "RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_receipt_items_browser.py -q"
    exit_code: 0          # 4 passed
  - command: "RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_planned_bugfixes_browser.py tests/test_document_v2_browser.py tests/test_browser.py -q"
    exit_code: 1          # 11 passed, 3 failed; the same 3 fail at START_HEAD, see below
  - command: ".venv/bin/ruff check src tests"
    exit_code: 0
skipped_checks:
  - "full non-browser suite (.venv/bin/python -m pytest -q): deferred to the final verification after SL-03 (user instruction)"
  - "no non-browser test file was changed, so there are no extra targeted non-browser runs"
screenshots:
  before:
    - /tmp/sl02-shots/before/documents_14-1440-light.png
    - /tmp/sl02-shots/before/documents_14-390-light.png
  after:
    - /tmp/sl02-shots/after/documents_14-1440-light.png
    - /tmp/sl02-shots/after/documents_14-390-light.png
escalations: []
```

## What was built
- `receipt.js`: `RECEIPT_COLUMNS` (one list of `[data-col, title, numeric]`) and `receiptCell(key, row, ...)` above `ledgerRows`.
  The receipt branch builds the header, the cells and the footer spans from `receiptColumns`, which is that list with Code
  dropped when no item has a product code and Paid dropped when no item has `share_minor != null`. The columns are Item, Code,
  Qty, Unit price, Category, Line total, Paid, then the source cell, which stays last because `doc2RowCorrect` appends to
  `tr.lastElementChild`.
  - Qty is `table.qty`. Unit price is `amount(display, {signed:false})` plus `/<per>`, or "—". Line total is the old Price
    cell. Paid is the stored share as stored, or "—" when there is none. "with tax" shows only when `table.tax_included` is
    true. Code shows "—" for an item with no code.
  - Every header, body and source cell carries `data-col`. The footer amount cell is `data-col="line_total"`.
  - The footer label spans every column before Line total (5 with Code, 4 without). The actions cell spans Paid plus
    source (2 with Paid, 1 without). The Correct buttons and their aria-labels are unchanged.
  - The statement branch is behaviorally unchanged (same columns, numeric header classes, signed amounts and balance
    handling). Its code was only re-indented to sit beside the receipt branch.
- No CSS change. `.numeric` already right-aligns and keeps amounts from wrapping, as MASTER.md "Components: Table" and
  `docs/ui.md` "Screen rules" ask. I consulted that table section of the design system and added no tokens, fonts or inline styles.
- `tests/test_receipt_items_browser.py`:
  - **Seeding.** `seed` sets `home_currency` USD (and `auto_identify_items` False) first, then records R, D, G and N
    through `record_document`.
  - **P-checks.** Each scenario checks the stored subtotal, tax, total and the shares by SQL before it looks at the page.
    Values are R 5918/274/6192 with shares 429/4190/1573, D 62161 with 162/53999/8000, G 935, and N −1299/−101/−1400
    with share −1400.
  - **sc02.** Covers the header order, the source button last in each row, the three rows' cells, no "—" under Paid and the
    footer amounts. It checks footer alignment by bounding box, as the plan says, and does so again after the record's
    Correct… is opened, since the footer's Correct buttons show only then. Correct on Tax opens `Tax` focused and Cancel
    hides it. It then reloads, re-reads the splits, totals and quantities by SQL and asserts they are unchanged. Ruffles'
    stored quantity is still NULL. `NO_OVERFLOW` holds at 390, 768 and 1440.
  - **sc11 (steps 1–3).** Bananas 2.31 lb · $0.59/lb · $1.36. Yogurt 3 · "—" · $4.50. Milk 1 · $3.49. There's no Code column.
  - **sc12.** The filter's Line total is "−$12.99" and Paid is "−$14.00 with tax" (U+2212).
  - **sc20.** There's no Code column. Groceries Paid is "$80.00" with no note. Hot dog "$1.62 with tax", mattress "$539.99 with tax".
    One Tax footer line reads "$40.12", and its amount sits under Line total.
- `test_planned_bugfixes_browser.py`: the first row's `[data-col=line_total]` cell is asserted to contain "19.00 USD" and
  not "18.00 USD" after the price correction, and the reverse after Undo (R-e).

## Notes for the verifier
- The second command exits 1 on **3 failures that are not from this slice**: `test_planned_bugfixes_browser.py::test_idle_badge_read_filter_and_record_selected`,
  `test_document_v2_browser.py::test_document_page_states_find_correct_and_decide` and
  `test_browser.py::test_real_browser_configures_scans_and_inspects_versions`. They fail with extraction validation errors
  (`extra_forbidden`, `document_type: missing`) in the fake model's replies. I ran the same three files from a clean
  `git worktree` at START_HEAD b5427c8, with its own `src` first on the path (checked), and got the same 3 failures and 11
  passes. The worktree is removed. `test_receipt_money_item_price_undo_and_pay_period` (my R-e change) and the SL-03-owned
  `test_document_v2_browser.py:123-125` Printed-details test both pass.
- The brief's other targeted check, ruff, is clean. I did not run the full suite (user instruction). SL-01's unit tests are
  unchanged and weren't re-run.
- Screenshots are full-page, light theme, from `ui_shots.py --routes "documents/{receipt_doc}" --widths 390,1440 --full-page`.
  The seeded receipt (EGGS, BREAD, SOAP) has no product codes. So the "after" shot shows no Code column, Qty 1, Unit
  price 18.00/12.00/20.00 USD, Line total and Paid with "with tax". It shows "USD" amounts, not "$", because `ui_shots`'
  household has no home currency. The page doesn't overflow at 390 (asserted in sc02). I viewed only the 1440 "after" shot.
- The Correct buttons in the footer exist only once the record's Correct… is open, as before. The plan's SC-02 step 8
  ("click Correct on Tax") therefore clicks Correct… first.
- Left alone: `plans/receipt-item-table/progress.yaml`, `specs/receipt-tax-codes/*` (uncommitted, not mine), `doc2DetailList`, `docs/money.md`.

## Open issues
None for SL-02. P5 stands: the row Correct form still labels the field "Price" while the column is now "Line total".
