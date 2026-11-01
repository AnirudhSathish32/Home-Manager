# Receipt items: a fuller item table — implementation plan
Spec: specs/receipt-item-table/spec.md (+ specs/receipt-item-table/test-contract.md)
Spec sha256: f9ace30ba4a003c8b40c1a0b284fdcac6e3460b662182abda1e8d558fd0fd5f2
Review-Risk: HIGH
Review-Risk-Rationale: Display only and no schema change, but SL-01 changes `finance/splits.py` `allocate` (money
correctness) to share one taxed-items rule with the new "with tax" flag, and the item table is the money display
`receipt-tax-codes` builds on.

<!-- Approval lives in approvals/receipt-item-table.json, bound to this file's hash. No Status line.
     Execution progress goes in plans/receipt-item-table/progress.yaml, never in this file. -->

## Verified repository integration points
All read at HEAD `ebedfef` on `reorganize-packages` (clean tree plus the two spec folders), 2026-11-01. The spec's line
numbers have drifted in a few places. The ones below are current.

| Where | What it does today | Used for |
|---|---|---|
| `app/static/receipt.js:294-365` `ledgerRows(record, categories, onSaved, find, correctField)` | Bills go to `billLines` (`:295`). Receipt columns `["Item","Code","Price","Category","Paid",""]` (`:307`). `codes` = any `product_code` (`:304`). `shares` = any truthy `display.share_minor` (`:305`). `paid` is "—" when there's no line total or when `share_minor === line_total_minor` (`:318`). "with tax" is added to every shown share (`:326`). Footer rows Subtotal/Tax/Tip/Not matched/Total (`:340`): label `colSpan = codes ? 2 : 1`, one amount cell, actions `colSpan = shares ? 3 : 2` (`:343-347`), Correct buttons `aria-label="Correct <field>"` (`:349`). | FR-01 – FR-07 |
| `app/static/document_v2.js:450` | The only caller of `ledgerRows`. The receipt section is `<h3>Items (n)</h3>` plus the table (`:455-457`). | — |
| `document_v2.js:744-767` `doc2RowCorrect` | Appends the row's Correct/Delete buttons to `tr.lastElementChild` (the source cell). The form row's `colSpan = tr.children.length`. | Unchanged. It depends on the source cell staying last (FR-01). |
| `document_v2.js:604-633` `doc2DetailList` | Printed details. For each item it appends weight "2.31 lb @ 0.59/lb" (`:622-626`), or on grocery receipts "n × unit price" (`:627-631`). | FR-25: remove `:620-632` |
| `finance/ledger.py:1742-1890` `Ledger.record` | Receipt items are `SELECT *` from `receipt_items` (`:1761`). `item["details"]` = `shown_details(...)` (`:1763`). `item["share_minor"]` = the receipt's own `category_splits` row (`transaction_id IS NULL`) (`:1765-1770`). `bill = document_kind == 'bill'` (`:1768`). At the end every `*_minor` int gets `row["display"][key] = format_minor(...)` ("4.19 USD") for items too (`:1878-1880`). | SL-01 adds `item["table"]` |
| `ledger.py:236-252` `shown_details` | A detail with `minor` gets `display` = money. A text detail with a unit gets `display` = "text unit". Weight is therefore "2.31 lb", and price_per_weight is "0.59 lb" with `text` "0.59" and `unit` "lb". | FR-02, FR-03 weighed rows |
| `documents/extraction.py:1977-1985` `grocery_item` | Weight and price_per_weight are stored as text details with the row's unit, only when cited. `receipt_items.quantity` is TEXT (`library/migrations/011_finance.sql:90`), and `unit_price_minor` is an integer. | qty/unit price source |
| `documents/extraction.py:1633-1669` `sign_return`, `:1734-1736` | A line marked `returned` is made negative (`:1735`). With a cited return marker (`says_return`, `ledger.py:282-289`: "RETURN" matches) and returned lines but no sold ones, the whole-return branch (`:1649-1657`) negates every positive line and `RECEIPT_AMOUNTS` (`:1617`) and sets `sale_type` "return". Then subtotal + tax = total and the line sum = subtotal both hold (`:1745-1758`), with no issue. `tests/test_returns.py:20,50-62` is the same shape (TOWEL SET → −2500/−200/−2700, verified, splits sum −2700). | fixture N, SC-12 |
| `ledger.py:1033-1046` `split_inputs` | The items that are shared: `review_status<>'rejected'`, by position, with `taxed`. | the same item set for "with tax" |
| `finance/splits.py:61-97` `allocate` | Tax: `taxed = [value if item.get("taxed") else 0 ...]`. `spread(tax, taxed if sum(taxed) else base)` (`:83-85`). Negative amounts work unchanged: `share` only rejects a zero weight sum (`:28-30`). | SL-01 extracts `tax_basis`; N's share |
| `ui.js:193-208` `amount(value)` | Parses "4.19 USD" (`/^(-)?([\d,]+(?:\.\d+)?) ([A-Z]{3})$/`) and renders "$4.19" for the home currency. Anything else is shown as text. With `{signed:false}`, "-14.00 USD" (`core/money.py:87-89` `format_minor`) renders as the text "−$14.00" (U+2212, `:202,205`), with no direction. "$" appears only when the currency is the household's home currency (`ui.js:191,203`, set from settings at `app.js:182`); `document_server` doesn't set one (`tests/seed_documents.py:40`), which is why `test_planned_bugfixes_browser.py:43,45` expects "19.00 USD". | FR-03 unit price |
| `app/static/*.css:285` `.table-wrap { overflow-x: auto }` | Wide tables scroll inside their wrap, not the page. | narrow widths |
| `tests/seed_documents.py:196` `document_server(..., seed=)` | `seed(manager, model)` returns ids. | browser tests |
| `tests/document_forms_fixtures.py:403` `record_document(manager, model, name, lines, replies)`, `:28` `cite`, `:149` `grocery_replies` | Records a synthetic image through the real service with schema-keyed replies. | fixtures |
| `tests/test_document_v2_browser.py:123-125` | Asserts Printed details shows "2.31 lb @ 0.59/lb" and a "2 ×" line. | updated by SL-03 (FR-25 removes them on purpose) |
| `tests/test_planned_bugfixes_browser.py:28-46` | Footer contains "Tax", tbody contains "with tax", the first row contains "19.00 USD" after a price correction and "18.00 USD" after Undo (`:44-46`). The seeded EGGS item has quantity "1" and unit price 18.00 (`tests/seed_documents.py:21,28`). | SL-02 scopes `:44` and `:46` to the Line total cell (R-e) |
| `.claude/skills/ui-redesign/scripts/ui_shots.py` | Synthetic screenshots. The test contract says `scripts/ui_shots.py`; this is its real path. | SC-02 evidence |
| `docs/money.md:536-545` "Item categories and splits" | Describes Price and Paid ("with tax only when it differs"). | FR-30 |

## Architecture, contracts, data flow and decisions
**Money from the server.** The browser shows strings the server made. It never decides a unit price, formats a price
per weight or works out whether tax is in a share. So SL-01 adds one server field per receipt item. SL-02 renders it.

**Contract (SL-01).** In `Ledger.record`, for each item of a receipt that is not a bill:

```
item["table"] = {
  "qty": str,                        # "10", "2.31 lb" or "1"; never empty
  "unit_price": {"display": str, "per": str | None} | None,   # None renders "—"
  "tax_included": bool,              # the stored share includes part of the receipt's tax
}
```

Bills get no `table` key; `billLines` is untouched. Rules, in order:

- **qty** (FR-02):
  1. Weight detail present → `details.weight.display` ("2.31 lb").
  2. Else stored `quantity` (whitespace-collapsed) when non-empty → it ("10").
  3. Else `"1"`. The stored `quantity` is never written (D3).
- **unit_price** (FR-03):
  1. Weight present and `price_per_weight` present → `{"display": "<n> <CUR>", "per": unit}`. Here `<n>` is
     `price_per_weight.text` with one leading currency symbol stripped and `,` removed, when it matches `^\d+(\.\d+)?$`.
     `per` is the detail's unit, else the weight's. If the text isn't a plain number, use `{"display": "<text>/<unit>",
     "per": None}` (shown as text, unformatted).
  2. Weight present, no price per weight → `None`. Nothing is calculated.
  3. Else `unit_price_minor` not None → `{"display": format_minor(unit_price_minor), "per": None}`.
  4. Else stored `quantity` is non-empty and is not a finite `Decimal` equal to 1 or −1 → `None` ("—"). This covers a
     number above one, a fraction like "0.5", text like "2x", and "NaN". `InvalidOperation` is caught, and the
     comparison only runs after `is_finite()`.
  5. Else `line_total_minor` not None → `{"display": format_minor(line_total_minor), "per": None}` (the price of one).
     Else `None`.
- **tax_included** (FR-05): `receipt.tax_minor` is non-zero, the item has a stored share, `sum(splits.tax_basis(items))`
  is non-zero (otherwise `allocate` puts the tax in a row no item carries, `splits.py:28-30,74-76`), and the item's
  basis is non-zero. `items` is `split_inputs`' list, matched by id. Rejected items and
  items without a share are `False`.

**One taxed-items rule.** SL-01 adds `splits.tax_basis(items) -> list[int]`: each item's `item_amount` where it's
taxed, or every item's when no taxed item has an amount. That is exactly today's `taxed if sum(taxed) else base`.
`allocate` calls it. The flag and the shares can therefore never disagree, and `receipt-tax-codes` changes the rule in
one place. Behavior is identical: `tests/test_spending_splits.py` and `tests/test_receipt_kinds.py` must pass
unchanged.

**Rendering (SL-02).** `ledgerRows` receipt columns become `["Item","Code","Qty","Unit price","Category","Line total",
"Paid",""]`. Code is hidden by today's `codes` rule (FR-06; an item without a code shows "—", not empty). Paid is
hidden only when no item has `share_minor != null`.

- **Qty** is plain text, numeric-aligned.
- **Unit price** is `amount(unit_price.display, {signed:false})`, plus `"/" + per` when `per` is set, or "—".
- **Line total** is today's Price cell, `amount(..., {signed:false})` as today (`receipt.js:325`).
- **Paid** is `amount(display.share_minor, {signed:false})` whenever `share_minor != null`, and "—" otherwise. A
  negative share shows "−" with no money-in/out direction, as today.
- Every receipt cell carries `data-col` = `item|code|qty|unit_price|category|line_total|paid|source`, and footer amount
  cells `data-col="line_total"`. This gives tests a stable selector that doesn't depend on column indices. The "with tax" note is
  added only when `table.tax_included` is true.

Footer (FR-07):
- The label cell spans every column before Line total: `codes ? 5 : 4`.
- The amount cell sits under Line total.
- The actions cell spans the rest: `shares ? 2 : 1`, Paid plus source.
- Correct buttons, their aria-labels and `correctField` are unchanged.

Column constants live in one place in `ledgerRows`, an index map, so `shown()`, the `numeric` classes and the footer
spans can't drift. Statement rows keep their branch untouched.

**Decisions taken in the plan** (not product decisions; each is consistent with the spec):
- P1. A printed quantity of 1 with no unit price shows the line total (rule 5). FR-03 only names "above one" as "—".
- P2. A weighed item without a printed price per weight shows "—" (no calculation).
- P3. A returned item's Unit price from rule 5 is the stored, negative line total, shown as stored with the sign.
  For fixture N that is −$12.99 (no quantity printed, so Qty "1"). SC-12 checks only Line total and Paid, so SL-01's
  unit test pins it. A returned item stored with quantity "−1" also takes rule 5.
- P5. The row Correct form keeps its field label "Price" (`ledger.py:1772`) while the column is now "Line total".
  The spec doesn't ask for a rename, and renaming it would change the correction API's labels.
- P4. Visual: the ui-ux-pro-max skill is consulted before SL-02's CSS (CLAUDE.md). The table keeps MASTER.md
  "Components: Table": right-aligned amounts with a sign slot, sunken sticky header. At 390px the `.table-wrap`
  scrolls horizontally inside itself, and the page doesn't overflow. No new tokens or fonts, and no inline styles (CSP).

## Error handling, idempotency and recovery
- Nothing is stored and there's no migration, so restart and retry change nothing. `table` is recomputed on every
  `GET /api/finance/records/receipt/{id}`.
- Bad stored data (non-numeric quantity text, a price per weight that isn't a number) never raises. It falls to "—" or
  to raw text (rules 1 and 4).
- `split_inputs` returns `None` for a receipt with no total or no items. Then every `tax_included` is `False` and
  Paid is "—" (no share), as FR-05 says.

## Privacy/security and migration impact
- No schema change, no migration, no stored-value change. `EXTRACTION_VERSION` is unchanged.
- No new dependencies. CSP: DOM nodes only, no inline style or HTML strings.
- Tests use synthetic fixtures under `tmp_path`. Nothing under P:\Finances, %LOCALAPPDATA%\HomeManager or
  P:\EvalCorpus.

## Vertical slices
| ID | FR/SC covered | Dependencies | Files/changes | Verification command / evidence |
|---|---|---|---|---|
| SL-01 | FR-02, FR-03, FR-05 (server half); the data behind SC-02, SC-11, SC-12, SC-20 | none | `finance/splits.py`: `tax_basis(items)`, `allocate` uses it. `finance/ledger.py` `record()`: `item["table"]` per the contract (helper `item_table(item, receipt, basis_by_id, currency)` beside `shown_details`). New `tests/test_receipt_item_table.py`: unit tests of `item_table` for every rule branch (R's three items, G's banana/yogurt/milk, quantity "1", "−1", "0.5", "2x" and "NaN", a bill gets no key, items [+1000, −1000] with tax and none taxed (`tax_included` false for both), N's returned filter (line −1299, tax −101: qty "1", unit price "-12.99 USD", `tax_included` true), `tax_included` for D's three items and for a receipt with tax 0), plus two `Ledger.record` tests through `read_receipt`: R/RA asserting the `table` values and the shares 429/4190/1573, and N/NA asserting `direction` "return" (as `test_returns.py:59` does), subtotal/tax/total −1299/−101/−1400, the one share −1400 and the filter's `table`. Adds `tests/receipt_item_fixtures.py` (R, RA, D, G, N/NA per the contract). | `.venv/bin/python -m pytest tests/test_receipt_item_table.py -q`; `.venv/bin/python -m pytest tests/test_spending_splits.py tests/test_receipt_kinds.py tests/test_reextraction.py tests/test_bills_ledger.py -q` (unchanged shares and bills) |
| SL-02 | FR-01 – FR-07; SC-02, SC-12, SC-20, SC-11 steps 1–3 | SL-01 | `app/static/receipt.js` `ledgerRows` receipt branch (columns, Qty/Unit price/Line total/Paid cells, "with tax" from `tax_included`, footer spans). CSS in the existing stylesheet only if the numeric Qty/Unit price columns need alignment classes (after ui-ux-pro-max). New `tests/test_receipt_items_browser.py` with `sc02`, `sc11` (steps 1–3), `sc12`, `sc20`, each seeding through `document_server(seed=)` and `record_document`. `sc02` also asserts `NO_OVERFLOW` at 390, 768 and 1440 px, and the source button is the last cell of each row. `tests/test_planned_bugfixes_browser.py:44,46`: scope the "19.00 USD"/"18.00 USD" assertions to the first row's `[data-col=line_total]` cell, and also assert that cell no longer holds the old value (R-e). | `RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_receipt_items_browser.py -q`; `RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_planned_bugfixes_browser.py tests/test_document_v2_browser.py tests/test_browser.py -q` (footer, Correct, row Correct/Delete regressions); before/after screenshots with `.claude/skills/ui-redesign/scripts/ui_shots.py` at desktop and phone widths |
| SL-03 | FR-25, FR-30; SC-11 step 4, SC-17 | SL-02 | `document_v2.js` `doc2DetailList`: remove the per-item weight and count block (`:620-632`). Tenders and deposit splits stay. `tests/test_document_v2_browser.py:123-125`: replace the two Printed-details assertions with assertions that Printed details has no "2.31 lb" or "2 ×" line, and that the item table shows them (the intended FR-25 change). `tests/test_receipt_items_browser.py`: `sc11` step 4 (G has no tenders, so Printed details may be absent, and the assertion accepts no `.doc2-details-section` or one without a Bananas/Yogurt line), `sc17`. `docs/money.md` "Item categories and splits": replace the Price/Paid paragraph with the columns, the Qty and Unit price rules, and when Paid shows "—" or "with tax". The heading is unchanged. | `RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_receipt_items_browser.py tests/test_document_v2_browser.py -q`; FR-30 by review of the doc diff |

Each slice ends with the full non-browser suite (`.venv/bin/python -m pytest -q`) green, and SL-02/SL-03 with the
browser files above.

## Requirements & scenarios coverage matrix
| FR | Slice | Scenarios / tests |
|---|---|---|
| FR-01 | SL-02 | SC-02 step 2 |
| FR-02 | SL-01, SL-02 | SL-01 unit tests; SC-02 steps 3–5; SC-11 steps 1–3 |
| FR-03 | SL-01, SL-02 | SL-01 unit tests; SC-02; SC-11 |
| FR-04 | SL-02 | SC-02; SC-12 |
| FR-05 | SL-01, SL-02 | SL-01 `tax_included` tests; SC-02 steps 3–6; SC-12; SC-20 step 3 |
| FR-06 | SL-02 | SC-02 (Code column present); SC-20 step 2 (absent) |
| FR-07 | SL-02 | SC-02 steps 7–8; `test_planned_bugfixes_browser.py` |
| FR-25 | SL-03 | SC-11 step 4; SC-17; updated `test_document_v2_browser.py` |
| FR-30 | SL-03 | review |

| SC | Slice | Test |
|---|---|---|
| SC-02 | SL-02 | `test_receipt_items_browser.py::test_sc02_item_table` |
| SC-11 | SL-02 (1–3), SL-03 (4) | `::test_sc11_count_and_weight` |
| SC-12 | SL-02 | `::test_sc12_returned_item` |
| SC-17 | SL-03 | `::test_sc17_printed_details_without_counts` |
| SC-20 | SL-02 | `::test_sc20_no_codes_untaxed_item` |

## Test environments, data, stubs for nondeterministic components, final-state oracle
- **Data:** `tests/receipt_item_fixtures.py` holds the contract's fixtures R (with stub RA), D, G and N (with stub NA)
  as line lists plus `*_replies()` builders keyed by schema name, citing lines with `document_forms_fixtures.cite`.
  NA's summary is unsigned (12.99, 1.01, 14.00) with `return_marker` "RETURN" citing the `RETURN` line, as
  `tests/test_returns.py` `summary_of` does. The filter's line is "-12.99", taxed true. `returned` true is harmless
  (the line is already negative, `extraction.py:1735`).
- **Home currency:** every seed in `test_receipt_items_browser.py` first calls
  `manager.configure_household(manager.household.model_copy(update={"home_currency": "USD", "auto_identify_items": False}))`,
  as `tests/test_bill_kinds_browser.py:15-17` `usd` does, before recording and before the page loads. Without it the
  page shows "4.19 USD", not the contract's "$4.19". `test_planned_bugfixes_browser.py` keeps its own server and its
  "USD" strings.
- **Minus signs in unit tests:** SL-01's quantity "−1" case uses an ASCII "-1" (what `Decimal` parses). A U+2212
  minus is not a number and falls to rule 4 ("—"), which is also tested as text.
  `receipt-tax-codes` extends this file later.
- **Stubs:** the fake model server from `document_server`/`local_model` answers by `json_schema.name`. There is no
  live model.
- **Oracles** are independent of the page:
  - each browser scenario first P-checks the stored receipt (subtotal, tax, total) and its `category_splits` shares
    (`transaction_id IS NULL`, by position) by SQL through `manager.store.connection()`, against the contract's
    hand-worked values (RA: 429, 4190, 1573; D: 162, 53999, 8000);
  - only then does it check the rendered table;
  - SC-02 step 3 also asserts by SQL that Ruffles' `receipt_items.quantity IS NULL` (D3: display only);
  - SC-02 step 9 reloads the page and re-asserts the header and the three rows, then re-reads the split rows and item
    quantities by SQL and asserts they are unchanged (no write on view);
  - FR-07 alignment is checked by geometry, independent of colspans: each footer amount cell's bounding box lies
    horizontally within the Line total header's box. This runs on SC-02 (with Code) and SC-20 (without Code);
  - SC-12 P-checks fixture N's stored subtotal −1299, tax −101 and total −1400, and its one share −1400 (sum = total),
    against the contract's hand-worked values. Then the filter row's `[data-col=line_total]` reads "−$12.99" and
    `[data-col=paid]` reads "−$14.00" with "with tax". Text is compared with U+2212, which `amount` emits.
    The planner traced these values through the code, not by running it: whole-return branch → −1299/−101/−1400.
    `allocate`: subtotal spread 0; `tax_basis` = [−1299], so `share(−101, [−1299])` = [−101]; amounts [−1400];
    difference 0; `rounded` → [−1400]. `tax_included`: tax ≠ 0, a share is stored, basis sum −1299 ≠ 0 and the item's
    basis ≠ 0, so true.
- **Browser:** Playwright with `channel="msedge"`, headless (`/usr/bin/microsoft-edge` is present), opt-in via
  `RUN_BROWSER_TESTS=1`, `@browser_test` from `test_ui_parity`. Page errors are collected and asserted empty.

## Risks, unresolved decisions, alternatives
- **R-a `allocate` refactor.** A mistake changes stored shares everywhere. Mitigation: a pure extraction with an
  identical expression. The existing split, receipt-kind, re-extraction and bill suites run unchanged in SL-01.
- **R-b Hidden-column index drift.** Adding two columns shifts indices that `shown()`, the numeric classes and the
  footer spans rely on. Mitigation: one named-index map, plus the SC-02 header-order and footer-alignment assertions
  with and without Code (SC-20).
- **R-c Narrow screens.** Eight columns at 390px. The wrap scrolls inside (`.table-wrap` `overflow-x: auto`).
  `NO_OVERFLOW` is asserted at three widths. Collapsing columns on phones is not in scope.
- **R-e Planned-bugfix test scoping.** Once Unit price shows the seeded 18.00, the row-wide "18.00 USD" assertion after
  Undo would pass even with a broken Undo. Scoping it to the Line total cell keeps it meaningful. This is an intended
  test change.
- **R-d Printed details test update.** Intended by FR-25, not a regression. It is called out so review doesn't read it
  as weakening a test.
- **Alternative rejected:** computing Qty/Unit price/"with tax" in `receipt.js`. Cheaper, but it breaks "money from
  the server" (`docs/ui.md` "Money and dates on screen"). "with tax" also needs the taxed-items rule, which lives only
  on the server.
- No unresolved product decisions. P1 – P3 are recorded above for review.
