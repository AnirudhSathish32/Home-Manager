# Test contract: receipt-tax-codes
Spec sha256: the bundle hash (spec.md + this file) comes from the user's gate tooling (`$HOME/.agent-harness/gate.py`;
there's no `scripts/gate.py` in this repository). It isn't copied here, because writing it in would change it.

Every expected value comes from `spec.md`, or is worked out by hand below from the synthetic fixtures. None comes from
running the current code. Where the spec leaves an outcome open, it is listed under "Gaps", not invented.

## Conventions for every scenario
- **Environment.** A `tmp_path` library and database only. Record tests go through the real extraction service with the
  `local_model` stub answering by `json_schema.name`, the way `tests/test_receipt_kinds.py` `read_receipt` does:
  transcribe the synthetic lines, then `extract`. Ledger-only checks use `Store` and `Ledger` the way
  `tests/test_spending_splits.py` `books` does. API checks use `create_app(…)` with `TestClient`. Browser scenarios are
  opt-in (`RUN_BROWSER_TESTS=1`) through `tests/seed_documents.py` `document_server` with a `seed=` function. They never
  touch `P:\Finances`, `%LOCALAPPDATA%\HomeManager` or `P:\EvalCorpus`.
- **Stub shape.** The reading's new fields (an item's printed tax code, the receipt's tax lines, a code legend) take
  whatever names and schema the approved plan gives them. Each stub answer below gives values, not field names. Every
  stubbed code, tax line and legend entry cites its line in the fixture (`document_forms_fixtures.cite`).
- **P-checks.** Before a scenario's first checkpoint, the test asserts that the stored receipt has the subtotal, tax
  and total the fixture says. A failed P-check is a fixture problem, never a reason to change an expected value.
- **Shares** are `category_splits` rows for the receipt with `transaction_id IS NULL`, read per item in position order,
  in minor units (cents). Every share check also asserts that the shares add up exactly to the target.
- **Shared checks**
  - **C-sum(target):** the receipt's or the charge's split rows add up exactly to target, and every amount is an
    integer.
  - **C-cited:** every stored tax line and item tax code has an evidence link whose line ids are the fixture line it
    cites. Find on the page highlights that line.
  - **C-noissue / C-issue(text):** the receipt's `issues` hold no tax-line issue, or hold one containing text.
- **Test files (new)**
  - `tests/receipt_tax_fixtures.py`: the fixtures and stub answers below.
  - `tests/test_receipt_tax_codes.py`: reading, keeping and sharing (SC-01, SC-03 – SC-10, SC-13 – SC-16, SC-18).
  - `tests/test_splits_by_code.py`: unit tests of the share rule with no database (FR-14 – FR-18, FR-23), each
    independent.
  - `tests/test_receipt_items_browser.py`: the item table and footer (SC-02, SC-11, SC-12, SC-17, plus FR-06 and
    FR-07).
- **Cleanup.** pytest removes `tmp_path`. Browser tests close the browser and the server through `document_server`.

### Doubles
| Component | Real or double | Specification |
|---|---|---|
| Image transcription | Real reader on a synthetic receipt image (`tests/test_receipts.py` `make_receipt`) | Lines exactly as in each fixture. |
| Reasoning model (classification, summary, items, descriptions) | `local_model` by schema | The answers given per fixture. Some are deliberately wrong where a scenario says so (SC-14, SC-16). |
| Reading failure (SC-08 b) | `local_model` | The items schema gets an answer that fails validation (an item with no evidence). |
| Old-schema library (SC-09) | Fixture | A library migrated up to the migration before this feature's, then filled through the public Ledger paths. Then the feature's migration runs. |
| Clock | Real | No assertion depends on today's date. |
| Live model (FR-24 eval) | Real, user-run only | Not part of pytest. See "Evals". |

### Fixtures
**R: the user's receipt** (synthetic copy of the report). Lines:
`SYNTH MART`, `2026-10-20`, `GROCERY`, `071057174 RUFFLES BF $4.29`, `211180042 LITLE VEGET BF $41.90`,
`10 @ $4.19 ea`, `KITCHEN`, `07200120 WATER FILTER T $12.99`, `Regular Price $15.99`, `SUBTOTAL $59.18`,
`T = GA TAX 7.75000 on $12.99 $1.01`, `B = GA TAX 7.75000 on $46.19 $1.73`, `TOTAL $61.92`.

Stub answer R0, read as a grocery receipt:
- **Summary:** subtotal 59.18, tax 2.74, total 61.92.
- **Items**, each with the model's own `taxed` answer:
  - Ruffles: code 071057174, line 4.29, tax code BF, taxed false.
  - Little Veg: code 211180042, quantity 10, unit price 4.19, line 41.90, tax code BF, taxed false. It cites its line
    and the `10 @` line.
  - Water filter: code 07200120, line 12.99, tax code T, taxed true.
- **Tax lines:** T, rate 7.75000, on 12.99, amount 1.01; B, rate 7.75000, on 46.19, amount 1.73.

The `taxed: false` answers reproduce the reported bug. FR-11 says tax lines override them.

**Hand-worked shares for R0 (FR-14).**
- B's 173 is shared over Ruffles 429 and Little Veg 4190 (basis 4619):
  - Ruffles: 173 × 429 / 4619 = 16.068.
  - Little Veg: 173 × 4190 / 4619 = 156.932.
- T's 101 goes to the water filter.
- Exact shares: Ruffles 445.068, Little Veg 4346.932, Water filter 1400. Rounded down they come to 6191 against a
  target of 6192, so the cent left over goes to the largest remainder (Little Veg).
- **Expected: Ruffles 445, Little Veg 4347, Water filter 1400 (sum 6192).**

**D: the docs' Costco example** (`docs/money.md`). One `TAX 40.12` line, no codes printed.
- Items: Hot dog 1.50 (taxed true, dining), Mattress 499.99 (taxed true, furniture & decor), Groceries 80.00 (taxed
  false, groceries).
- Total 621.61.
- Expected (from the doc): 162, 53999, 8000.

**G: grocery count and weight.** Lines `SYNTH MARKET`, `2026-10-03`, `BANANAS 2.31 lb @ 0.59/lb 1.36`,
`3 @ YOGURT 4.50`, `MILK 3.49`, `SUBTOTAL 9.35`, `TAX 0.00`, `TOTAL 9.35`.
- Yogurt is read with quantity 3, no unit price, line 4.50.
- Milk has no quantity and no unit price.

**N: a return.** R's lines with `RETURN` above the filter's line, and the filter read as returned (line −12.99).

## SC-01 — Recording the user's receipt shares tax by code
Requirement IDs: FR-08, FR-09, FR-10, FR-11, FR-12, FR-14, FR-15
Nondeterministic components: model stubbed with R0
Initial state: empty library; no receipts.
Actions/checkpoints:
1. Record R with R0 → run succeeded; one receipt; P-check: subtotal 5918, tax 274, total 6192.
2. Items stored → tax codes are BF, BF and T. Each item's taxed flag is 1, although the stub answered false for both
   BF items (FR-11).
3. Tax lines stored → exactly two: (T, 7.75000, 1299, 101) and (B, 7.75000, 4619, 173). C-cited for both lines and
   all three codes.
4. Shares → Ruffles 445, Little Veg 4347, Water filter 1400. C-sum(6192). C-noissue.
5. Restart: close the manager and open the same library again → codes, tax lines and shares are unchanged (FR-12).
Expected final state:
- Database: 1 receipt, 3 items, 2 tax lines, 3 split rows as above. Nothing else is added beyond what recording
  already adds.
- UI: not checked here (SC-02).
Failure/retry/restart variants:
- Record the same document again (a second Record) → still 2 tax lines and 3 split rows. No duplicates.
Evidence: pytest output for `tests/test_receipt_tax_codes.py::test_sc01…`.

## SC-02 — The item table on the document page
Requirement IDs: FR-01 – FR-07, FR-19
Nondeterministic components: model stubbed with R0; real browser (Edge), opt-in
Initial state: `document_server` with a seed that records R with R0 (SC-01's state).
Actions/checkpoints:
1. Open the receipt's document page → the item table's column titles read Item, Code, Qty, Unit price, Category,
   Line total, Paid, in that order (FR-01).
2. Ruffles row → 071057174, 1, $4.29, $4.29, $4.45. Qty 1 is a plain value with no "not printed" mark (FR-02, D3).
3. Little Veg row → 211180042, 10, $4.19, $41.90, $43.47 "with B tax".
4. Water filter row → 07200120, 1, $12.99, $12.99, $14.00 "with T tax".
5. No Paid cell reads "—" (FR-05).
6. Footer → Subtotal $59.18. Under Tax: "B · 7.75% on $46.19 · $1.73" and "T · 7.75% on $12.99 · $1.01", each with
   Find. Total $61.92. The amounts sit in the Line total column (FR-07, FR-19).
7. Click Find on the B tax line → the B line of the source is highlighted (C-cited).
8. Click Correct on Tax → the tax correction opens for the field `tax` (FR-07). Cancel it.
9. Reload the page → the same table.
Expected final state: UI as above. Database unchanged by the visit.
Failure/retry/restart variants: none.
Evidence: browser test output, plus synthetic before and after screenshots (`scripts/ui_shots.py`) at desktop and
phone widths.

## SC-03 — Receipts without tax lines keep today's sharing (regression)
Requirement IDs: FR-05, FR-11
Nondeterministic components: model stubbed with D
Initial state: empty library.
Actions/checkpoints:
1. Record D → no tax lines stored. The taxed flags are the model's answers (1, 1, 0).
2. Shares → 162, 53999, 8000. C-sum(62161).
3. Open the page (browser) → Groceries' Paid shows $80.00 with no "with tax" note. The footer has one Tax line, $40.12.
Expected final state: as today, apart from the new columns.
Evidence: pytest, plus the browser test.

## SC-04 — Tax lines that don't add up fall back
Requirement IDs: FR-16
Nondeterministic components: model stubbed with R0, but the summary's tax is 2.84 and the total 62.02
Initial state: empty library.
Actions/checkpoints:
1. Record → 2 tax lines stored. P-check: tax 284, total 6202.
2. Shares by the fallback. The taxed flags from FR-11 are all 1, so 284 is shared over 5918:
   - Ruffles: 429 + 20.587.
   - Little Veg: 4190 + 201.075.
   - Water filter: 1299 + 62.338.
   - Rounded down they come to 6201, so the cent left over goes to Ruffles.
   - **Expected: Ruffles 450, Little Veg 4391, Water filter 1361.** C-sum(6202).
3. C-issue("The tax lines ($2.74) don't add up to the tax ($2.84), so tax was shared across the taxed items.").
Expected final state: tax lines are kept (for display and for a later correction) but not used to share. The flags
are FR-11's (FR-27). R0's own answers would have put all the tax on the filter.
Evidence: pytest.

## SC-05 — A tax line with no items falls back
Requirement IDs: FR-16, FR-18
Nondeterministic components: R0, with the water filter's tax code empty
Initial state: empty library.
Actions/checkpoints:
1. Record → the filter's taxed flag is 0 (it belongs to no line, FR-11). Ruffles and Little Veg are 1.
2. Shares by the fallback, 274 over 4619:
   - Ruffles: 429 + 25.448.
   - Little Veg: 4190 + 248.552.
   - Water filter: 1299.
   - Rounded down they come to 6191, so the cent left over goes to Little Veg.
   - **Expected: Ruffles 454, Little Veg 4439, Water filter 1299.** C-sum(6192).
3. C-issue containing "T" and saying the T tax line has no items.
Evidence: pytest.

## SC-06 — An item carrying two tax codes
Requirement IDs: FR-18
Nondeterministic components: R0, with Ruffles' tax code BT
Initial state: empty library.
Actions/checkpoints:
1. Record → B's only item is Little Veg and T's only item is the filter. Both lines have items, so there's no
   fallback.
2. Shares → Ruffles 429 (no tax), Little Veg 4190 + 173 = 4363, Water filter 1400. C-sum(6192).
3. C-issue naming RUFFLES as carrying more than one tax line's code.
Evidence: pytest, plus a unit test in `test_splits_by_code.py`.

## SC-07 — Correcting the tax total
Requirement IDs: FR-16, FR-17, FR-27, FR-28
Nondeterministic components: R0
Initial state: SC-01's state.
Actions/checkpoints:
1. Correct Tax to 3.00 through the public correction API → tax 300. Subtotal 5918, total 6192 and tip are unchanged
   (FR-28 assertion, not a P-check).
2. Shares are rebuilt by the fallback: all three items are taxed, 300 is shared by amount, and the charge difference
   −26 is shared by amount. Each share is therefore the item's amount × 6192 / 5918:
   - Ruffles: 448.862.
   - Little Veg: 4383.995.
   - Water filter: 1359.143.
   - Rounded down they come to 6190, so the two cents left over go to Little Veg and then Ruffles.
   - **Expected: Ruffles 449, Little Veg 4384, Water filter 1359.** C-sum(6192).
3. C-issue("The tax lines ($2.74) don't add up to the tax ($3.00), so tax was shared across the taxed items.").
4. Correct Tax back to 2.74 → shares are 445, 4347 and 1400 again. C-noissue.
Evidence: pytest.

## SC-08 — Extract again replaces codes and lines, and keeps the user's category
Requirement IDs: FR-12
Nondeterministic components: R0 first, then stub R1. R1 is R0 with:
- the filter's tax code N and taxed false;
- Ruffles and Little Veg taxed true;
- no tax lines, and one tax of 2.74.
Initial state: SC-01's state.
Actions/checkpoints:
1. Set the Water filter's category to Household supplies through the item category API.
2. Extract again with R1 → the codes are BF, BF and N, and no tax lines are stored.
3. The filter's category is still Household supplies, with category source user.
4. Shares by the model's flags, 274 over 4619 → 454, 4439, 1299 (as SC-05). C-sum(6192).
Failure/retry/restart variants:
- (b) Extract again with an answer that fails validation → the run fails. The codes, both tax lines and the shares
  445, 4347 and 1400 are unchanged.
- (c) Extract again with R0 twice → still 2 tax lines, with no duplicates.
Evidence: pytest.

## SC-09 — Upgrading keeps existing receipts as they were
Requirement IDs: FR-13
Nondeterministic components: none (ledger paths)
Initial state: an old-schema library holding D, plus R recorded the old way, with only taxed flags (filter 1, BF
items 0) and splits.
Actions/checkpoints:
1. Snapshot every `category_splits` row and every `receipt_items.taxed` value.
2. Run the feature's migration, then restart → every snapshotted row and value is identical.
3. Both receipts have no item tax codes and no tax lines. `GET` of each record succeeds.
4. The ledger health check (`finance/health.py` `check_ledger`) passes.
Evidence: pytest.

## SC-10 — Charges, shared receipts and other currencies stay exact
Requirement IDs: FR-15
Nondeterministic components: R0
Initial state: SC-01's state.
Actions/checkpoints:
1. Match R to a card charge of −61.92 USD → the charge's split rows are 445, 4347 and 1400. C-sum(6192).
2. Share the receipt 50/50 with a family member → that person's part comes to 3096 (C-sum). Each category is within
   1 cent of half its SC-01 share.
3. Separately, match R to a charge of −57.00 EUR → the split rows come to 5700 (C-sum). Each is within 1 cent of its
   SC-01 share × 5700 / 6192.
Evidence: pytest.

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
Nondeterministic components: model stubbed with N; browser
Initial state: `document_server` seeded with N.
Actions/checkpoints:
1. The filter row's Line total and Paid are both negative. Paid is the stored share, shown as stored.
Evidence: browser test.

## SC-13 — Tax lines without codes
Requirement IDs: FR-21
Nondeterministic components: stub for the lines `SYNTH SHOP`, `LAMP 10.00`, `CARDS 5.00`, `SUBTOTAL 15.00`,
`STATE TAX 1.20`, `LOCAL TAX 0.40`, `TOTAL 16.60`.
- Lamp: taxed true.
- Cards: taxed false.
- Two tax lines with no code: 1.20 and 0.40.
- Tax 1.60.
Initial state: empty library.
Actions/checkpoints:
1. Record → nothing is used for sharing by code.
2. Shares → Lamp 1160, Cards 500. C-sum(1660). C-noissue.
Evidence: pytest.

## SC-14 — A code legend sets the taxed flags
Requirement IDs: FR-22
Nondeterministic components: stub for the lines `SYNTH SHOP`, `MUG T 8.00`, `BREAD N 3.00`, `SUBTOTAL 11.00`,
`T = TAXABLE`, `N = NON-TAXABLE`, `TAX 0.62`, `TOTAL 11.62`.
- The legend: T taxed, N untaxed.
- The model answers taxed false for the mug and true for the bread (wrong on purpose).
Initial state: empty library.
Actions/checkpoints:
1. Record → the mug's taxed flag is 1 and the bread's is 0.
2. Shares → Mug 862, Bread 300. C-sum(1162).
Evidence: pytest.

## SC-15 — Two lines with the same code
Requirement IDs: FR-23, FR-19
Nondeterministic components: R0, with B split into two lines, B 1.00 and B 0.73
Initial state: empty library.
Actions/checkpoints:
1. Record → 3 tax lines stored. The B lines together come to 173, and with T they add up to the tax, 274.
2. Shares → 445, 4347, 1400. C-noissue.
3. Browser: the footer shows three tax lines, each with Find.
Evidence: pytest, plus the browser test.

## SC-16 — Food-stamp marks without a legend
Requirement IDs: FR-24
Nondeterministic components: R's lines with the two tax lines replaced by `TAX $2.74`. The stub answers taxed empty
for all three items, with codes BF, BF and T.
Initial state: empty library.
Actions/checkpoints:
1. The items request's prompt states that a mark counts as untaxed only when the receipt says what it means, and that
   a food-stamp or EBT mark (F, E) is not untaxed on its own.
2. Record → no tax lines. All taxed flags are empty.
3. Shares across every item, 274 over 5918 → 449, 4384, 1359 (the same arithmetic as SC-07). C-sum(6192).
Evidence: pytest. The live reading is the eval below.

## SC-18 — Partly answered flags on a one-TAX-line receipt
Requirement IDs: FR-29
Nondeterministic components: SC-16's lines. The stub answers taxed true for the water filter and empty for both BF
items.
Initial state: empty library.
Actions/checkpoints:
1. Record → no tax lines. Flags: filter 1, BF items empty.
2. Shares across every item, 274 over 5918 → 449, 4384, 1359 (SC-16's arithmetic), not 429/4190/1573. C-sum(6192).
Failure/retry/restart variants: the same stub with every flag answered (true, false, false) → today's rule, 429, 4190,
1573. C-sum(6192).
Evidence: pytest, plus a unit test in `test_splits_by_code.py`.

## SC-17 — Printed details and the tax-code note
Requirement IDs: FR-25, FR-26
Nondeterministic components: R0; browser
Initial state: SC-02's server.
Actions/checkpoints:
1. Printed details has no "10 × $4.19" line for Little Veg.
2. Ruffles' Paid reads $4.45 "with B tax". Its row's tooltip reads "Tax code BF".
Evidence: browser test.

## Other FR checks (no journey)
- **FR-06:** on D, which has no product codes, the table has no Code column. On R it has one. Checked in the SC-03 and
  SC-02 browser tests.
- **FR-20:** checked by review, not by a test: the `docs/money.md` section and the `docs/open-work.md` entry.

## Evals (user-run, live model)
- Add a synthetic case to `evals/` modelled on R (see `docs/evals.md`). Pass means:
  - both tax lines are read with codes T and B, and amounts within 0.01 of 1.01 and 1.73;
  - the item codes contain B for both grocery items and T for the filter.
- Add a synthetic case modelled on SC-16 (a single TAX line with BF items). Pass means no BF item is read as taxed
  false.
- The user runs both. Results are never read by Claude beyond an allowlisted `summary.json`.

## Traceability
| FR | Scenarios | Test file |
|---|---|---|
| FR-01 | SC-02 | test_receipt_items_browser.py |
| FR-02 | SC-02, SC-11 | test_receipt_items_browser.py |
| FR-03 | SC-02, SC-11 | test_receipt_items_browser.py |
| FR-04 | SC-02, SC-12 | test_receipt_items_browser.py |
| FR-05 | SC-02, SC-03, SC-12 | test_receipt_items_browser.py |
| FR-06 | SC-02, SC-03 | test_receipt_items_browser.py |
| FR-07 | SC-02 | test_receipt_items_browser.py |
| FR-08 | SC-01 | test_receipt_tax_codes.py |
| FR-09 | SC-01, SC-15 | test_receipt_tax_codes.py |
| FR-10 | SC-01, SC-06 | test_receipt_tax_codes.py, test_splits_by_code.py |
| FR-11 | SC-01, SC-03, SC-05 | test_receipt_tax_codes.py |
| FR-12 | SC-01 (restart), SC-08 | test_receipt_tax_codes.py |
| FR-13 | SC-09 | test_receipt_tax_codes.py |
| FR-14 | SC-01 | test_receipt_tax_codes.py, test_splits_by_code.py |
| FR-15 | SC-01, SC-10 | test_receipt_tax_codes.py, test_splits_by_code.py |
| FR-16 | SC-04, SC-05, SC-07 | test_receipt_tax_codes.py, test_splits_by_code.py |
| FR-17 | SC-07 | test_receipt_tax_codes.py |
| FR-18 | SC-05, SC-06 | test_receipt_tax_codes.py, test_splits_by_code.py |
| FR-19 | SC-02, SC-15 | test_receipt_items_browser.py |
| FR-20 | review | — |
| FR-21 | SC-13 | test_receipt_tax_codes.py |
| FR-22 | SC-14 | test_receipt_tax_codes.py |
| FR-23 | SC-15 | test_receipt_tax_codes.py, test_splits_by_code.py |
| FR-24 | SC-16, evals | test_receipt_tax_codes.py, evals/ |
| FR-25 | SC-11, SC-17 | test_receipt_items_browser.py |
| FR-26 | SC-17 | test_receipt_items_browser.py |
| FR-27 | SC-04, SC-07 | test_receipt_tax_codes.py |
| FR-28 | SC-07 | test_receipt_tax_codes.py |
| FR-29 | SC-18 | test_receipt_tax_codes.py, test_splits_by_code.py |

Commands: `python -m pytest tests/test_splits_by_code.py tests/test_receipt_tax_codes.py`. The browser tests need
`RUN_BROWSER_TESTS=1` and `python -m pytest tests/test_receipt_items_browser.py`.

## Gaps
None open. G1 – G3 were settled by the user on 2026-10-26 (spec D4) and became FR-27 – FR-29.
