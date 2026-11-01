# Test contract: receipt-item-table
Spec sha256: the bundle hash (spec.md + this file) comes from the user's gate tooling (`$HOME/.agent-harness/gate.py`;
there's no `scripts/gate.py` in this repository). It isn't copied here, because writing it in would change it.

Split from `specs/receipt-tax-codes/test-contract.md` (user, 2026-11-01). Every expected value comes from `spec.md`, or
is worked out by hand below from the synthetic fixtures. None comes from running the current code.

## Conventions for every scenario
- **Environment.** Browser scenarios are opt-in (`RUN_BROWSER_TESTS=1`) through `tests/seed_documents.py`
  `document_server` with a `seed=` function that records the fixture through the real extraction service with the
  `local_model` stub answering by `json_schema.name`, the way `tests/test_receipt_kinds.py` `read_receipt` does. Share
  checks read `category_splits` the way `tests/test_spending_splits.py` does. They never touch `P:\Finances`,
  `%LOCALAPPDATA%\HomeManager` or `P:\EvalCorpus`.
- **Stub shape.** Today's reading schema only. No tax codes or tax lines (those are `receipt-tax-codes`).
- **P-checks.** Before a scenario's first checkpoint, the test asserts that the stored receipt has the subtotal, tax
  and total the fixture says. A failed P-check is a fixture problem, never a reason to change an expected value.
- **Shares** are `category_splits` rows for the receipt with `transaction_id IS NULL`, per item in position order, in
  minor units. Every share check also asserts that the shares add up exactly to the total.
- **Test files (new)**
  - `tests/receipt_item_fixtures.py`: fixtures R, D, G and N and their stub answers. `receipt-tax-codes` extends it.
  - `tests/test_receipt_items_browser.py`: SC-02, SC-11, SC-12, SC-17, SC-20.
- **Cleanup.** pytest removes `tmp_path`. Browser tests close the browser and the server through `document_server`.

### Doubles
| Component | Real or double | Specification |
|---|---|---|
| Image transcription | Real reader on a synthetic receipt image (`tests/test_receipts.py` `make_receipt`) | Lines exactly as in each fixture. |
| Reasoning model | `local_model` by schema | The answers given per fixture. |
| Browser | Real (Edge), opt-in | — |

### Fixtures
**R: the user's receipt** (synthetic copy of the report). Lines:
`SYNTH MART`, `2026-10-20`, `GROCERY`, `071057174 RUFFLES BF $4.29`, `211180042 LITLE VEGET BF $41.90`,
`10 @ $4.19 ea`, `KITCHEN`, `07200120 WATER FILTER T $12.99`, `Regular Price $15.99`, `SUBTOTAL $59.18`,
`T = GA TAX 7.75000 on $12.99 $1.01`, `B = GA TAX 7.75000 on $46.19 $1.73`, `TOTAL $61.92`.

Stub answer RA, read as a grocery receipt with today's fields:
- **Summary:** subtotal 59.18, tax 2.74, total 61.92.
- **Items:**
  - Ruffles: code 071057174, line 4.29, taxed false.
  - Little Veg: code 211180042, quantity 10, unit price 4.19, line 41.90, taxed false. It cites its line and the
    `10 @` line.
  - Water filter: code 07200120, line 12.99, taxed true.

**Hand-worked shares for RA (today's rule).** Only the filter is taxed, so all 274 goes to it. Subtotal + tax = total,
so there is no charge difference. **Expected: Ruffles 429, Little Veg 4190, Water filter 1573 (sum 6192).**

**D: the docs' Costco example** (`docs/money.md`). One `TAX 40.12` line, no codes printed.
- Items: Hot dog 1.50 (taxed true, dining), Mattress 499.99 (taxed true, furniture & decor), Groceries 80.00 (taxed
  false, groceries).
- Total 621.61.
- Expected (from the doc): 162, 53999, 8000.

**G: grocery count and weight.** Lines `SYNTH MARKET`, `2026-10-03`, `BANANAS 2.31 lb @ 0.59/lb 1.36`,
`3 @ YOGURT 4.50`, `MILK 3.49`, `SUBTOTAL 9.35`, `TAX 0.00`, `TOTAL 9.35`.
- Bananas is read with its weight 2.31 lb and price per weight 0.59/lb in its details, line 1.36.
- Yogurt is read with quantity 3, no unit price, line 4.50.
- Milk has no quantity and no unit price.

**N: a whole return of the filter.** Lines `SYNTH MART`, `2026-10-20`, `RETURN`, `KITCHEN`,
`07200120 WATER FILTER T $12.99`, `SUBTOTAL $12.99`, `T = GA TAX 7.75000 on $12.99 $1.01`, `TOTAL $14.00`.
Only returned lines, so `sign_return` takes the whole-return branch and every amount is money back. (A return of one of
R's items next to its sold ones would be an exchange whose arithmetic holds under neither sign; see
`plans/receipt-item-table/reviews.md` M2.)

Stub answer NA:
- **Summary:** subtotal 12.99, tax 1.01, total 14.00, unsigned. `return_marker` "RETURN", citing the `RETURN` line.
- **Items:** Water filter: code 07200120, line −12.99, taxed true.

**Hand-worked values for NA (today's rule).** Whole return: subtotal −1299, tax −101, total −1400. The filter is the
only item and is taxed, so all the tax goes to it. **Expected share: Water filter −1400 (sum −1400 = total).**

## SC-02 — The item table on the document page
Requirement IDs: FR-01 – FR-07
Nondeterministic components: model stubbed with RA; real browser, opt-in
Initial state: `document_server` with a seed that records R with RA.
Actions/checkpoints:
1. P-check: subtotal 5918, tax 274, total 6192. Shares 429, 4190, 1573.
2. Open the receipt's document page → the item table's column titles read Item, Code, Qty, Unit price, Category,
   Line total, Paid, in that order (FR-01).
3. Ruffles row → 071057174, 1, $4.29, $4.29, Paid $4.29 with no "with tax" note. Qty 1 is a plain value with no "not
   printed" mark (FR-02, FR-03, D3). The stored quantity is still empty.
4. Little Veg row → 211180042, 10, $4.19, $41.90, Paid $41.90 with no note.
5. Water filter row → 07200120, 1, $12.99, $12.99, Paid $15.73 "with tax".
6. No Paid cell reads "—" (FR-05).
7. Footer → Subtotal $59.18, Tax $2.74, Total $61.92. The amounts sit in the Line total column (FR-07).
8. Click Correct on Tax → the tax correction opens for the field `tax` (FR-07). Cancel it.
9. Reload the page → the same table.
Expected final state: UI as above. Database unchanged by the visit.
Evidence: browser test output, plus synthetic before and after screenshots (`scripts/ui_shots.py`) at desktop and
phone widths.

## SC-11 — Count and weight in the table
Requirement IDs: FR-02, FR-03, FR-25
Nondeterministic components: model stubbed with G; browser
Initial state: `document_server` seeded with G.
Actions/checkpoints:
1. Bananas row → Qty "2.31 lb", Unit price "$0.59/lb", Line total $1.36.
2. Yogurt row → Qty 3, Unit price "—", Line total $4.50.
3. Milk row → Qty 1, Unit price $3.49.
4. Printed details has no line for Bananas or Yogurt (FR-25).
Evidence: browser test.

## SC-12 — Returned items
Requirement IDs: FR-04, FR-05
Nondeterministic components: model stubbed with NA; browser
Initial state: `document_server` seeded with N read with NA.
Actions/checkpoints:
1. P-check: subtotal −1299, tax −101, total −1400. Share −1400.
2. Open the receipt's document page → the filter row's Line total is −$12.99 and Paid is −$14.00 with "with tax".
   Paid is the stored share, shown as stored.
Evidence: browser test.

## SC-17 — Printed details without count lines
Requirement IDs: FR-25
Nondeterministic components: RA; browser
Initial state: SC-02's server.
Actions/checkpoints:
1. Printed details has no "10 × $4.19" line for Little Veg. Tenders and savings lines, if the fixture has any, still
   show.
Evidence: browser test.

## SC-20 — A receipt with no product codes and an untaxed item
Requirement IDs: FR-05, FR-06
Nondeterministic components: model stubbed with D; browser
Initial state: `document_server` seeded with D.
Actions/checkpoints:
1. P-check: total 62161. Shares 162, 53999, 8000.
2. The table has no Code column (FR-06).
3. Groceries' Paid shows $80.00 with no "with tax" note. Hot dog and Mattress show "with tax" (FR-05).
4. The footer has one Tax line, $40.12.
Evidence: browser test.

## Other FR checks (no journey)
- **FR-06 with codes:** SC-02 has a Code column.
- **FR-30:** checked by review, not by a test: the `docs/money.md` section.

## Traceability
| FR | Scenarios | Test file |
|---|---|---|
| FR-01 | SC-02 | test_receipt_items_browser.py |
| FR-02 | SC-02, SC-11 | test_receipt_items_browser.py |
| FR-03 | SC-02, SC-11 | test_receipt_items_browser.py |
| FR-04 | SC-02, SC-12 | test_receipt_items_browser.py |
| FR-05 | SC-02, SC-12, SC-20 | test_receipt_items_browser.py |
| FR-06 | SC-02, SC-20 | test_receipt_items_browser.py |
| FR-07 | SC-02 | test_receipt_items_browser.py |
| FR-25 | SC-11, SC-17 | test_receipt_items_browser.py |
| FR-30 | review | — |

Commands: `RUN_BROWSER_TESTS=1 python -m pytest tests/test_receipt_items_browser.py`.

## Gaps
None open.
