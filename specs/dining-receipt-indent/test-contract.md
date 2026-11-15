# Test contract: dining-receipt-indent
Spec sha256: the bundle hash (spec.md + this file) comes from the user's gate tooling (`$HOME/.agent-harness/gate.py`;
there's no `scripts/gate.py` in this repository). It isn't copied here, because writing it in would change it.

Round 4 of this contract, written against `spec.md` round 5 (decisions D18 – D41; rounds 4 and 5 changed only the
spec's text, not `src/`). Every expected value
comes from the spec, or is worked out by hand below from the synthetic breakfast receipt. None comes from running the
code after the change. Two kinds of fixture are taken from today's code on purpose, because the spec defines them as
"today's": the saved shape of an old reading, and the extraction request an old reading sends (FR-17, FR-19, FR-21,
D28). Those are captured once from today's application code, before any application change, and checked in (see
"Baseline captures"). `src/` is identical at 2676e51 and a8542d8 (only spec files changed), so either commit serves.

Q1 takes the spec's default, accepted by the user (Edit details with the same category doesn't apply FR-10), tested by
X-Q1. Q2 was reversed by the user in round 5 (spec D34): a re-read whose new total no longer supports a charge link
removes the link, with a note (FR-28 – FR-30). SC-09 step 6 now tests the removal (it was a characterization of today's
rule), and SC-20 – SC-22 cover the rest. Every gap, G1 – G18, is settled (see "Resolved gaps"); none is open.

## Conventions for every scenario
- **Environment.** A `tmp_path` library and database only. Nothing reads `P:\Finances`, `%LOCALAPPDATA%\HomeManager`
  or `P:\EvalCorpus`. Record tests go through the real services with the `local_model` stub (`tests/conftest.py`,
  `tests/model_server.py`): vision answers through `local_model["output"]`/`["outputs"]`, reasoning answers by
  `json_schema.name` through `local_model["by_schema"]`, the way `tests/test_receipt_kinds.py` `read_receipt` and
  `tests/document_forms_fixtures.py` `record_document` do. Ledger-only checks use `Store` and `Ledger` the way
  `tests/test_spending_splits.py` does. API checks use `create_app(…)` with `TestClient`. Browser checks are opt-in
  (`RUN_BROWSER_TESTS=1`) through `tests/seed_documents.py` `document_server` with a `seed=` function.
- **Names the plan chooses.** The worked-out-tip marker, the "FR-10 has applied" state, the payload flag that says
  whether the Category column shows, and the new `PDF_VERSION`/`GROUP_VERSION` strings take whatever names the approved
  plan gives them. The tests read them by those names. Values are fixed here; names are not.
- **Vision stub shape (FR-16).** A v7 vision answer is `{"lines": [{"text", "indent"}], "tables"?: […]}`. The fixture
  helper `vision_lines(texts, indents)` builds it. Every existing helper that stubs `{"full_text": …}` (the
  `model_server` default output, `test_extraction.transcribe`, `document_forms_fixtures.record_document`,
  `test_vision_tables`) moves to `lines` with indent 0 on every line, unless the test is about an old answer shape
  or a missing indent. That is test infrastructure, not a behavior change. A line with no `indent` key is unknown (D25);
  helpers for "no indent" readings omit the key on purpose.
- **P-check.** Before a scenario's first real checkpoint, the test asserts that the stored receipt has the items,
  subtotal and tax the fixture says (items 4885, tax 391 where read). A failed P-check is a fixture problem, never a
  reason to change an expected value.
- **Shares.** "Receipt split" means the `category_splits` rows with `receipt_id` = the receipt and
  `transaction_id IS NULL`. "Charge split" means the rows with the charge's `transaction_id`. Item rows carry
  `receipt_item_id`; no-item rows don't. Amounts are minor units.
- **Shared checks**
  - **C-sum(rows, target):** the rows add up exactly to target, and every amount is an integer.
  - **C-cat(rows, category):** every row in rows has that category.
  - **C-snap(before):** every `category_splits` row (all columns, ordered by id) equals the snapshot.
  - **C-col(shown|hidden):** the record payload from `GET /api/finance/records/receipt/{id}` says whether the Category
    column shows. In the browser, the item table header matches it.
  - **C-mem(n):** `item_category_memory` has n rows.
  - **C-review(status, reasons):** `receipts.review_status` and the receipt's issues/reasons equal these exactly.
  - **C-cites(field, line ids):** the stored amount's evidence lists exactly these line ids.
  - **C-links(receipt, rows):** the receipt's `transaction_receipt_links` rows, of every status, are exactly these
    (charge, `review_status`) pairs. "Unchanged" means the same row id, status, score and method as before the step.
  - **C-nosplit(charge):** no `category_splits` row has the charge's `transaction_id`.
  - **C-note(receipt, text):** the receipt's issues hold exactly one removal note (an issue starting "The match"), equal
    to text. **C-nonote(receipt):** none.
- **Re-reads go through the app's job path.** Extract again, Read again and Try again run through the manager's
  extraction job (the API, or `Manager` the way `tests/test_receipt_kinds.py` drives kind changes), so the
  reconciliation that follows a published reading (`app/manager.py` `extract_and_file`) runs as it does in the app.
- **Doubles**

| Component | Real or double | Specification |
|---|---|---|
| Vision model (images, scanned PDF pages, combined images) | `local_model` stub | Answers are fixed per fixture: `lines` with indent, sometimes invalid on purpose (SC-11). The test asserts on the request the stub receives (FR-15, FR-18). |
| Reasoning model (classification, summary, rows, description, several-receipts question, rewards) | `local_model` by schema | Answers given per fixture. Some are wrong on purpose (the total citing a suggested-tip line, side lines published as items, Groceries item categories). |
| Image file | Real synthetic image (`tests/test_receipts.py` `make_receipt`) | Content is irrelevant: the stub returns the lines. |
| Scanned PDF | Synthetic image-only PDF as in `tests/test_pdf_reader.py` | Pages are read through the vision stub. |
| Old library (v56/v6) | Fixture | See "Old library". |
| Card charge | Ledger fixture | A USD card transaction, −61.55 or −52.76, on 2026-11-12, merchant text "GACHAS BREAKFAST BAR". SC-20 adds K60; SC-21 and SC-22 add the SYNTH MART charges (see "Charges for the link scenarios"). |
| ECB rates (SC-21 (d)) | Cached-rate fixture | Rows in the rates cache the way `tests/test_fx.py` seeds them; no network. |
| Clock | Real | No assertion depends on today's date. |
| Live vision model | User-run only | "Evals". Not part of pytest. |

- **Test files**
  - `tests/dining_receipt_fixtures.py` (new): the breakfast lines and indents, `vision_lines`, the stubs B0–B8 below,
    the old-library builder, and the baseline captures.
  - `tests/test_dining_receipts.py` (new): SC-01 – SC-09, SC-16 – SC-20, X-D8, X-Q1 and the FR-01 – FR-06 variants.
  - `tests/test_reread_links.py` (new): SC-21, SC-22 (FR-28 – FR-30 on other receipt kinds, bills and the cases the rule
    leaves alone).
  - `tests/test_vision_indent.py` (new): SC-10 – SC-12, FR-15 – FR-21 checks, the version checks.
  - `tests/test_receipt_side_lines.py` (new): SC-13, SC-14 and FR-22/FR-23 variants.
  - `tests/test_receipt_items_browser.py` (extended): the Category column, the worked-out Tip note and the footer
    (SC-07 step 1, SC-18).
  - `tests/test_document_v2_browser.py` (extended): the Text view's indentation (SC-15).
  - `tests/test_migrations.py` (extended, only if the plan adds a migration): X-UPG.
  - Existing tests whose expectations the spec changes on purpose: `test_vision_tables.py`
    `test_malformed_structured_response_gets_one_text_only_retry` (the rescue now asks for `lines`, FR-18), and any test
    asserting `VISION_VERSION`, `PDF_VERSION`, `GROUP_VERSION` or `EXTRACTION_VERSION` values. No other existing
    expectation may change. A suite-wide pass is part of the evidence.
- **Cleanup.** pytest removes `tmp_path`. Browser tests close the server through `document_server`.

## Fixtures

### The breakfast receipt (spec, "Synthetic receipt used by every scenario")
| # | Text | Indent |
|---|---|---|
| 1 | Gacha's Breakfast Bar | 0 |
| 2 | 12 Peach St | 0 |
| 3 | Order #: 179580 | 0 |
| 4 | Server: Crimson H | 0 |
| 5 | Date: 11/12/26, 10:31 AM | 0 |
| 6 | Amount: $52.76 | 0 |
| 7 | Bottled Water $3.95 | 0 |
| 8 | Bottled Water $3.95 | 0 |
| 9 | Coffee $14.95 | 0 |
| 10 | Georgia Peach Stack $18.70 | 0 |
| 11 | No Allergies | 1 |
| 12 | Fresh Berry Pancakes | 1 |
| 13 | Veggie Sausage | 1 |
| 14 | Jalapeno Cheese Grits | 1 |
| 15 | Better Than No Y'all Biscuits (3) $7.30 | 0 |
| 16 | No Allergies | 1 |
| 17 | Total Item Count: 6 | 0 |
| 18 | Subtotal: $48.85 | 0 |
| 19 | Total Tax: $3.91 | 0 |
| 20 | Total: $52.76 | 0 |
| 21 | Paid With: VISA CARDHOLDER | 0 |
| 22 | Bill: $52.76 | 0 |
| 23 | Total: $61.55 | 0 |
| 24 | Tip: $ | 0 |
| 25 | Suggested Tip | 0 |
| 26 | 18.00% of sale: $8.79 Total $61.55 | 0 |
| 27 | 20.00% of sale: $9.77 Total $62.53 | 0 |
| 28 | 22.00% of sale: $10.75 Total $63.51 | 0 |

Hand checks (fixture self-test `test_breakfast_fixture_adds_up`, no app code): items 395 + 395 + 1495 + 1870 + 730 =
4885 = Subtotal. 4885 + 391 = 5276 = Bill. 6155 − 5276 = 879. 879 / 4885 = 18.0%. 5276 + 977 = 6253 and 5276 + 1075 =
6351, as lines 27 and 28 print. Five lines match today's `TOTAL_LINE` with a digit (20, 23, 26, 27, 28), so the
several-receipts question is asked (SC-19).

### Stubs
- **B0 (SC-01's reading).** Vision: the 28 lines with the indents above. Classification: receipt, kind dining, kind
  evidence line 4. Summary (`ReceiptDiningSummary`): merchant "Gacha's Breakfast Bar" (line 1), date 2026-11-12 (line
  5), subtotal 48.85 (line 18), tax 3.91 (line 19), total 52.76 (line 20), tip missing, gratuity missing, server
  "Crimson H" (line 4). Items: Bottled Water 3.95 (line 7), Bottled Water 3.95 (line 8), Coffee 14.95 (line 9),
  Georgia Peach Stack 18.70 (line 10), Better Than No Y'all Biscuits 7.30 (line 15). `PurchaseDescription`: category
  dining, `item_categories` [groceries, groceries, dining, dining, dining]. `ReceiptStarts`: one receipt (start
  line-1). Rewards: none.
- **B1.** B0 with the summary's total 61.55 citing line 23.
- **B2 (printed tip).** Line 24 reads "Tip: $8.79". Summary tip 8.79 citing line 24.
- **B3 (printed wrong tip).** Line 24 reads "Tip: $5.00". Summary tip 5.00 citing line 24.
- **B4 (customer copy).** Lines 1–22, then "Tip: $" (23) and "Total: $" (24). Summary as B0 (total 52.76, line 20).
  Variant B4e: line 24 reads "Total: $52.76".
- **B5 (no line 23).** B0's lines without line 23 (lines 24–28 become 23–27, so the table is lines 24–27 and
  "18.00% of sale: $8.79 Total $61.55" is line-25). One summary answer only: total 61.55 citing only line-25. The model is
  not asked again (D22), so the stub has no second answer; a second summary request fails the test.
  Variant B5n (no pre-tip amount before the table): B5 without lines 6 ("Amount: $52.76"), 20 ("Total: $52.76") and 22
  ("Bill: $52.76"). Variant B5a: B5n with line 6 ("Amount: $52.76") kept. It is not a pre-tip amount (D30), so B5a
  ends like B5n.
- **B9 (pre-tip amounts disagree, D23).** B0 with line 22 reading "Bill: $50.00". The summary as B0 (total 52.76, line
  20).
- **B10 (no tip line, D19).** B0's lines without line 24 (lines 25–28 become 24–27). Summary as B0.
- **B6 (side lines as items).** B0 with rows adding "No Allergies", "Fresh Berry Pancakes", "Veggie Sausage",
  "Jalapeno Cheese Grits" after Georgia Peach Stack, each `line_total` null, each citing its own line (11–14).
  `item_categories` gets four more entries (groceries). Variant B6z: the four with `line_total` 0.00.
- **B7 (grocery re-read, SC-08).** `ReceiptGrocerySummary` with B0's amounts. `PurchaseDescription` category
  groceries, `item_categories` [groceries, groceries, dining, dining, dining].
- **B8 (printed tip, $2.00 left over).** Lines "SYNTH DINER", "2026-11-10", "SERVER: JO", "BURGER 20.00",
  "SUBTOTAL 20.00", "TAX 1.00", "TIP 3.00", "TOTAL 26.00". Kind dining. Summary subtotal 20.00, tax 1.00, tip 3.00,
  total 26.00, each citing its line. One item, Burger 20.00. Category dining.

- **B11 (a grocery receipt, SC-21, SC-22).** Lines: 1 "SYNTH MART", 2 "2026-11-12", 3 "MILK 4.00", 4 "BREAD 5.00",
  5 "SUBTOTAL 9.00", 6 "TAX 1.00", 7 "TOTAL 10.00", 8 "CHANGE 7.00", 9 "SAVED 7.70", 10 "SAVED 7.69", all indent 0.
  Classification receipt, kind grocery. `ReceiptGrocerySummary`: merchant "SYNTH MART" (line 1), date 2026-11-12 (line
  2), subtotal 9.00 (line 5), tax 1.00 (line 6), total 10.00 (line 7). Items Milk 4.00 (line 3), Bread 5.00 (line 4),
  category groceries. Each variant changes only the summary's total and its citation, the model misreading on purpose:
  **B11b** total 9.00 (line 5), **B11c** 7.00 (line 8), **B11d** 7.70 (line 9), **B11e** 7.69 (line 10), **B11n** total
  missing. The grocery check may add its own issues on the variants; only the removal note is asserted (C-note).
  **B11g** (gift card): B11 plus line 11 "GIFT CARD -1.00" and a gift-card tender of 1.00 citing it, read the way
  `tests/test_receipt_kinds.py` reads gift-card tenders (printed 10.00, paid 9.00); **B11g'** the same with total 9.00
  (line 5), so paid 8.00.

### Charges for the link scenarios
- **K60**: −60.00 on 2026-11-12, "GACHAS BREAKFAST BAR", with a fixture `transaction_receipt_links` row to receipt C,
  `review_status` rejected, method "near_amount", score 30 (SC-20). Snapshot the row.
- **K10**: −10.00 on 2026-11-12, "SYNTH MART". **K9**: −9.00, same date and text (SC-21 (d)). **K8**: −8.00, same
  date and text (SC-22 (f)).

### Old library (v56 / v6)
Built the way `tests/test_migrations.py` `pre_document_forms` and `pre_bill_kinds` do. Apply every migration below this
feature's first one (all of them if the plan adds none). Then insert the rows below by SQL. Nothing in it is produced
by the changed code.
- A `blobs`/`occurrences` document per receipt. A `parse_runs` row with `parser_version` `receipt-vision-v6-tables` and
  status succeeded, whose stored result is **R6**: the breakfast lines in today's saved shape (`TextLine{id, text,
  block_ids}`, no indent), captured at 2676e51 (see "Baseline captures"). An `extraction_runs` row with
  `prompt_version` `typed-extraction-v56-money-sign-rule`, status succeeded.
- **Receipt A** (dining, approved automatically: `verified`, `review_source` automatic). Total 5276, subtotal 4885,
  tax null, tip null, category dining. Items as B0 with Bottled Water ×2 under groceries (`category_source` model), the
  rest dining (model). Receipt split as today's `allocate` makes it (splits.py:185-189, tax missed on a dining
  receipt): item rows 395 groceries, 395 groceries, 1495 dining, 1870 dining, 730 dining, and one no-item row 391
  dining. C-sum 5276.
- **Receipt B** (dining, approved by the user: `verified`, `review_source` user). Same rows as A.
- **Receipt C** (dining, `needs_review`). Same as A, except item 1 is groceries with `category_source` user and item
  2 groceries with `category_source` model. Not linked.
- **Receipt D** (dining, approved by the user). Same as A, except item 1 is groceries with `category_source` user and
  item 2 is dining.
- **Receipt E** (dining, `needs_review`). Items with category null and `category_source` null. Receipt split: item
  rows 395, 395, 1495, 1870, 730 dining (fallback), no-item 391 dining.
- **Receipt G** (grocery, verified). A small grocery receipt with two items under groceries and household supplies.
  The regression control: nothing about it changes in any scenario.
- **Receipt H** (dining, `needs_review`, an old receipt whose category you changed to travel before the upgrade). The
  lines of B8. Total 2600, subtotal 2000, tax 100, tip 300 (printed), receipt category travel. One item, Burger 2000,
  category travel with `category_source` receipt. Receipt split as today's `allocate` makes it with fallback travel
  (rules 4 and 5, `splits.py:185-191`): the tip row 300 **dining** with no item; the 200 difference spread over the items,
  so the item row is 2000 + 100 tax + 200 = 2300 travel. C-sum 2600. FR-10 has not applied to it.
- **Charge K52**: a card transaction −52.76 on 2026-11-12, unlinked. **Charge K61**: −61.55, same date, unlinked.

Each scenario uses only the receipts it names (the builder takes a list).

### Baseline captures (from today's code, before any application change)
- **R6**: the stored result of a v6 image reading of the breakfast lines (the vision stub answering today's
  `{"full_text": …}`). Plus its PDF twin **P3** (a one-page scanned PDF read under `pdf-pages-v3-layout`) and its group
  twin **G2** (two images read as one document under `receipt-images-v2-tables`). Saved as files in the fixture
  module's data, byte for byte.
- **Q56**: the full JSON body of every reasoning request that `extract` sends for R6, P3 and G2 with stub B0 (the
  requests `local_model["requests"]` records), in order, plus today's receipt row instruction text
  (`extraction.py:4383-4392`) as its own file. The test compares each request's `lines` payload byte for byte, and the
  rest of the body byte for byte after masking the row instruction: today's text in the capture and the new FR-22 text
  in the new request are each replaced by the same placeholder (D28). Nothing else may differ.
- **Order (D28).** The plan's first slice captures these, before any application change. The script, and the commit it
  ran at, are recorded in the fixture module's docstring. Review checks `git diff <that commit> a8542d8 -- src/` is
  empty. Once checked in, the captures are never regenerated by the changed code.

## SC-01 — The breakfast receipt counts what was charged, all as dining
Requirement IDs: FR-01, FR-02, FR-06, FR-07, FR-10 (and FR-11, FR-27 through the payload)
Nondeterministic components: vision and reasoning stubbed with B0
Initial state: empty library; one card charge K61 imported (ledger fixture).
Actions/checkpoints:
1. Capture the image and record it with B0 → the extraction run succeeded; 1 receipt. P-check: 5 items, sum 4885, tax
   391, subtotal 4885.
2. Total → `total_minor` 6155. C-cites(total, [line-23]).
3. Tip → `tip_minor` 879, marked worked out, C-cites(tip, [line-22, line-23]) (FR-02; line 22 is the nearest pre-tip
   amount before line 23, D23. Line 20 also reads $52.76, so they agree).
4. Dining check → passes. `cross_checks` counts it (4885 + 391 + 879 = 6155). The trace's Tip step (`finance/traces`
   for the dining check) names line-22 and line-23 and says the tip was worked out. No FR-03 issue.
5. Review → C-review(`needs_review`, exactly ["Tip $8.79 was worked out from Total $61.55 less Bill $52.76, not
   printed; check it."]) (FR-06, D4). The reason starts with "Tip", which today's correction rule needs (D26).
6. Receipt split → C-sum(6155), C-cat(dining). By category reads "Dining $61.55". The item rows are dining although
   the stub said groceries for items 1 and 2 (FR-10). C-mem(0).
7. Record payload → Tip shows the note "Worked out: Total $61.55 − Bill $52.76". C-col(hidden). The "Not matched to an
   item" amount is 0 (FR-27: 879 − 879).
8. `POST /api/finance/reconcile` → one exact receipt link to K61. No "ambiguous receipt match" question exists (FR-07).
   Charge split → C-sum(6155), C-cat(dining). Receipt split → still C-sum(6155), C-cat(dining).
Expected final state:
- Database: `receipts` 1 row (total 6155, tip 879 with the worked-out marker, tax 391, subtotal 4885,
  `needs_review`). `receipt_items` 5 rows (the B0 items, positions 1–5, no side lines). Receipt split: 5 item rows plus
  the tip row (879), all dining, sum 6155. Charge split all dining, sum 6155. 1 receipt link. `parse_runs`: 1 row,
  `receipt-vision-v7-indent`. `extraction_runs`: 1 row, `EXTRACTION_VERSION` (v57). `item_category_memory`: 0 rows.
- Stored item categories (D20): all 5 items `category` dining, `category_source` receipt (the model said groceries for
  items 1 and 2 and dining for 3 – 5; all are model-categorised).
Failure/retry/restart variants:
- (a) B1 (the model already answers 61.55 citing line 23) → the same end state (FR-01's second criterion).
- (b) Record the same document again (a second capture of the same file) → still 1 receipt, 6 receipt split rows, 1
  link after reconcile. No duplicates.
- (c) Restart (close the manager, open the same library) and run reconciliation again → C-snap of the state after step
  8 (D8: the applied state survives).
- (d) A failed extraction on Try again (summary answer fails validation twice) → the run fails; total, tip, marker and
  splits are exactly as after step 8 (spec "Errors": a failed extraction leaves the record as it was).
Evidence: pytest `tests/test_dining_receipts.py::test_sc01…`.

## SC-02 — A printed tip is kept
Requirement IDs: FR-03
Nondeterministic components: B2
Initial state: empty library.
Actions/checkpoints:
1. Record B2 → `tip_minor` 879, not marked worked out, C-cites(tip, [line-24]). `total_minor` 6155 (line 23).
2. No FR-03 issue. No FR-06 reason. C-review(`verified`, []) (verified automatically).
3. Receipt split C-sum(6155), C-cat(dining).
Failure/retry/restart variants:
- (a) B3 (printed Tip: $5.00) → tip 500, total 6155, issue exactly "Tip ($5.00) and the bill ($52.76) don't make the
  total ($61.55)." The receipt is not verified automatically (it has an issue). Receipt split still C-sum(6155).
Evidence: pytest.

## SC-03 — No tip is invented
Requirement IDs: FR-04, FR-01 (D19, D23)
Nondeterministic components: B4, B10, B9
Initial state: empty library.
Actions/checkpoints:
1. Record B4 → `total_minor` 5276 citing line 20, `tip_minor` NULL (not 0). No worked-out marker or note. No FR-06
   reason.
2. Receipt split C-sum(5276), C-cat(dining).
Failure/retry/restart variants:
- (a) B4e (the later Total equals the Bill) → total 5276, tip NULL.
- (b) One printed total: B0's lines 1–20 only → total 5276, tip NULL.
- (c) No tip line (B10, D19) → `total_minor` 6155, C-cites(total, [line-23]). `tip_minor` NULL, no worked-out marker
  or note (D12), no FR-06 reason. The dining check fails as today (4885 + 391 = 5276 ≠ 6155) and adds today's check
  issue; the receipt is `needs_review`. Receipt split by today's rule 5 on a dining receipt: item rows 5276 (items plus
  tax), one no-item difference row 879, all dining, C-sum(6155). Record payload: "Not matched to an item" 879 (no tip
  row to leave out, FR-27).
- (d) Pre-tip amounts disagree (B9, D23) → `total_minor` 6155 citing line-23 (FR-01 still applies: 61.55 is larger than
  the nearest pre-tip amount, line 22's $50.00). `tip_minor` NULL, no worked-out marker or note, no FR-06 reason. The
  issue "The receipt prints different amounts before the tip ($52.76 and $50.00), so the tip wasn't worked out." is
  present exactly, the amounts in reading order, earlier first (line 20 before line 22; D29). Line 6 "Amount: $52.76"
  takes no part (D30). The dining check uses the post-tip total
  (FR-03) and fails as today. Receipt split C-sum(6155), C-cat(dining), with a no-item 879 row; "Not matched to an item"
  879.
Evidence: pytest.

## SC-04 — The suggested-tip table is never the source
Requirement IDs: FR-05, FR-01
Nondeterministic components: B5, B5n, B5a; and B1' (B0 with the total 61.55 citing only line 26)
Initial state: empty library.
Actions/checkpoints:
1. Record B1' (line 23 present) → `total_minor` 6155 citing line 23, from FR-01, not from line 26. Tip 879 worked out.
2. Record B5 in a fresh library → `total_minor` 5276, C-cites(total, [line-22]) (Bill: the nearest pre-tip amount
   printed before the table, D22; not line 20). Exactly one summary request was sent (counted in
   `local_model["requests"]` by schema name): the model is not asked again. `tip_minor` NULL, no worked-out marker
   (FR-01 doesn't apply: no post-tip total outside the table). The note "The total the reading took from the
   suggested-tip table was not used." is on the record.
3. No stored amount of either receipt cites a line of the table ("Suggested Tip" and the three "% of sale" lines).
Failure/retry/restart variants:
- (a) A tip cited only to "18.00% of sale: $8.79 Total $61.55" on B0's lines (summary tip 8.79 citing that line) →
  that tip isn't used. FR-02 works out 879 from lines 22 and 23 instead, and the note "The tip the reading took from
  the suggested-tip table was not used." is present.
- (b) A table without the "Suggested Tip" heading (line 25 removed) → the same outcomes as step 1 and step 2.
- (c) B5n (no pre-tip amount before the table) → `total_minor` NULL (missing, as for a receipt with no readable total
  today), the note present, one summary request. The record is handled as today's receipt with no total.
- (d) B5a (B5n with line 6 "Amount: $52.76" kept) → the same as (c): `total_minor` NULL, nothing cites line 6, the note
  present, one summary request (D30).
Evidence: pytest.

## SC-05 — Old receipts stay until read again
Requirement IDs: FR-08, FR-14, FR-24
Nondeterministic components: B0 for Extract again
Initial state: old library with receipts A, B, G and charge K52.
Actions/checkpoints:
1. Snapshot every `receipts`, `receipt_items` and `category_splits` row.
2. Upgrade: open the library with the changed code (migrations run if there are any), then restart once → C-snap; the
   `receipts` and `receipt_items` rows equal the snapshot in every pre-existing column. No job is queued and no model
   request is made (`local_model["requests"]` is empty).
3. `POST /api/finance/reconcile` → exactly one of A and B links to K52 (exact amount, proposed, today's rules); record
   which. The receipt splits of A, B and G are unchanged from the snapshot, and the groceries rows of items 1 and 2 stay
   groceries. That charge split has the item rows' categories (2 groceries rows), C-sum(5276).
4. Extract again on B (approved by you) → a new extraction run under v57 exists. B's `receipts`, `receipt_items` and
   receipt split rows equal the snapshot (FR-08, today's rule). If B holds the link, it is unchanged and C-nonote(B)
   (D39: a reading never rewrites a record you approved).
5. Extract again on A → a new extraction run with `prompt_version` = `EXTRACTION_VERSION` (starts
   `typed-extraction-v57`), not a reuse of the v56 run (FR-24). A: total 6155, tip 879 worked out (lines 22, 23).
   Receipt split C-sum(6155), C-cat(dining). A's 5 items store dining with `category_source` receipt (D20: all were
   model-categorised). Review and the link, by step 3's branch:
   - B held the link → C-links(A, []), C-review(`needs_review`, [FR-06 reason]); B's link unchanged.
   - A held the link (proposed; 6155 ≠ 5276, FR-28) → C-links(A, []), C-nosplit(K52) as A's charge, C-review(
     `needs_review`, [FR-06 reason, "The match to the $52.76 charge on 2026-11-12 was removed: this reading's total
     ($61.55) no longer matches it."]). The reconciliation after the reading links K52 to B (exact, proposed; FR-29),
     and that charge split follows B's item categories (2 groceries rows), C-sum(5276).
6. Run reconciliation again → A's receipt split is still all dining (FR-14: once applied, kept). G unchanged.
Expected final state:
- Database: A changed as in step 5. B and G exactly as in the snapshot (B's `receipts`, `receipt_items` and receipt
  split rows; B may hold K52's link and its charge split, by step 5's branch). No `transaction_receipt_links` row is
  rejected. `extraction_runs`: the old v56 rows still
  there and succeeded, plus one new v57 row each for A and B. `parse_runs`: unchanged (Extract again reuses the v6
  reading; no new image reading). `item_category_memory`: 0 rows.
- Filesystem: the v6 parse runs' stored results are byte-identical to R6.
Failure/retry/restart variants:
- (a) Extract again on A a second time with the same stub → under the current version it re-reads (today's behavior
  for Extract again). A's state is the same as after step 5, with no duplicate items or split rows.
Evidence: pytest.

## SC-06 — Your tip correction wins
Requirement IDs: FR-09
Nondeterministic components: B0
Initial state: SC-01 after step 7 (not reconciled).
Actions/checkpoints:
1. Correct Tip to 9.00 (`POST /api/finance/records/receipt/{id}/corrections`, changes {tip: "9.00"}) → `tip_minor`
   900, not marked worked out. The record payload has no worked-out note.
2. Issues → none. The FR-06 reason is resolved (it starts with "Tip", D26). No FR-03 issue is added: corrections
   don't re-run checks, so no issue text starts with "Tip ($9.00)".
3. Footer → the record payload's `totals_mismatch` is true (4885 + 391 + 900 = 6176, 21 more than 6155), so the page
   shows today's "Doesn't add up" warning (the difference is $0.21; D26, D31). The test asserts `totals_mismatch` and,
   in the browser, today's warning text; it doesn't look for "$0.21" on the page.
4. Review → C-review(`verified`, []), `review_source` automatic (today's rule: waiting in Review, not reviewed by you,
   no issue left).
5. Receipt split → C-sum(6155) (the total is unchanged), C-cat(dining).
6. Extract again with B0 → `tip_minor` 900, not marked worked out. Total 6155.
Failure/retry/restart variants:
- (a) Undo the tip correction → tip 879 and the worked-out marker are back. Review state and issues after Undo follow
  today's Undo rule and are not asserted.
- (b) Characterization: a printed tip corrected the same way on B2 → today's behavior, no worked-out marker involved.
Evidence: pytest.

## SC-07 — One category on a dining receipt
Requirement IDs: FR-10, FR-11, FR-12
Nondeterministic components: B0
Initial state: SC-01 after step 7.
Actions/checkpoints:
1. Open the document page → the payload says hidden (C-col(hidden)). In the browser the item table header reads Item,
   Qty, Unit price, Line total, Paid (no Code column: no codes printed), and the footer spans line up with those 5
   columns.
2. `PUT /api/receipts/{id}/items/1/category` {category: "groceries"} → 400 with exactly "Every item on a dining
   receipt counts as the receipt's category; change it with Edit details." C-mem(0). The item's stored category and
   source, and the receipt split, are unchanged.
3. Edit details → Categories → Travel (`POST …/corrections` {category: "travel"}) → receipt category travel. Receipt
   split C-sum(6155), C-cat(travel): the 5 item rows (5276) and the tip row (879) (D18). By category reads "Travel
   $61.55", with no Dining line. The 5 items store travel with `category_source` receipt (D20). "Not matched to an
   item" 0 (FR-27 leaves out the tip's row in the receipt's category). C-col(hidden).
4. Repeat step 2 → still 400. C-mem(0).
5. Reconcile with K61 → exact link. Charge split C-cat(travel), C-sum(6155). A further reconciliation run keeps both
   splits all travel (D18: once FR-10 has applied, later rebuilds keep it).
Expected final state: 1 receipt, category travel, 5 items, receipt and charge splits all travel, sum 6155 each, no
memory rows.
Failure/retry/restart variants:
- (a) A grocery receipt (G built through the ledger) → C-col(shown); its PUT → 200 and writes a memory row (today).
- (b) A dining receipt with no total (B5n) → the payload still decides the column: hidden, decided from the
  categories its split would use (FR-11).
- (c) Q1 counterpart: Edit details → Categories → Travel again on the travel receipt → no change to any split.
Evidence: pytest, plus the browser test for step 1.

## SC-08 — Changing the kind away from dining and back
Requirement IDs: FR-13
Nondeterministic components: B0, then B7 for the grocery re-read, then B0's dining form
Initial state: SC-01 after step 7, approved (review action "approve", `review_source` user). One memory row
inserted as fixture state: seller "Gacha's Breakfast Bar", item "Coffee" → groceries.
Actions/checkpoints:
1. Snapshot the receipt split S0 (all dining, 6155).
2. `PATCH /api/receipts/{id}/kind` {kind: "grocery"} → 202; the run succeeds. Total 6155, tip 879, the items and
   `verified` stay (reviewed receipt, today's rule). Item categories: Bottled Water ×2 groceries (model), Coffee
   groceries (memory beats the model's dining), Georgia Peach Stack and Biscuits dining (model). Receipt split: item
   rows take those categories; the tip row stays dining (splits.py:185-186). C-sum(6155). C-col(shown).
3. Undo the kind correction (`POST …/corrections/undo` with the kind correction's id) → kind dining. Receipt split
   C-snap(S0).
4. `PATCH …/kind` {kind: "grocery"} then {kind: "dining"} → after the change to dining the split is C-cat(dining),
   C-sum(6155), on the approved receipt (FR-13). C-col(hidden).
Expected final state: kind dining, `verified`, split all dining, sum 6155 throughout. Memory: the one fixture row only
(a kind change writes no memory).
Failure/retry/restart variants:
- (a) Grocery → dining on a verified grocery receipt (the dining stub answers for the same lines) → split all in the
  receipt's category at once.
- (b) A kind change while a reading of the file is running → refused as today; split unchanged.
Evidence: pytest.

## SC-09 — An old dining receipt keeps its categories until read again
Requirement IDs: FR-08, FR-11, FR-12, FR-14 (D6, D7, D8), FR-28, FR-29, FR-30 (D34)
Nondeterministic components: B0 for Read again
Initial state: old library with receipt C and charge K52.
Actions/checkpoints:
1. Upgrade (as SC-05 step 2) → C-snap.
2. Open the page → C-col(shown); each item has the dropdown.
3. `POST /api/finance/reconcile` → C links to K52 exactly. Receipt split: items 1 and 2 groceries (395 each), the rest
   dining, no-item 391 dining, C-sum(5276). Charge split: the same categories, C-sum(5276).
4. `PUT …/items/3/category` {groceries} → 200. Item 3 (Coffee) groceries, `category_source` user. C-mem(1): seller
   "Gacha's Breakfast Bar", item "Coffee", groceries. Receipt and charge splits: items 1–3 groceries, C-sum(5276) each.
5. Extract again from the v6 reading with B0 → total 6155, tip 879 worked out, `needs_review` with the FR-06 reason.
   Receipt split C-cat(dining), C-sum(6155). C-col(hidden). Items 1 and 3 still hold groceries with `category_source`
   user (FR-10: your choice stays stored, D20). Items 2, 4 and 5 store dining with `category_source` receipt (D20).
   C-mem(1) (unchanged; FR-12's "never read" means it didn't change the split).
6. The link to K52 (D34; it was proposed, and K52's 5276 isn't the new total 6155, FR-28) → removed: C-links(C, [])
   (no row, and none rejected; FR-29, D37). C-nosplit(K52): K52's category is what its own rules give it, equal to its category
   snapshotted before step 3, and its `merchant_id` is NULL again, as before step 3 (FR-29). C-review(`needs_review`, exactly
   [the FR-06 reason, "The match to the $52.76 charge on 2026-11-12 was removed: this reading's total ($61.55) no longer
   matches it."]) (FR-30). The reconciliation after the reading links nothing and opens no question (no charge of
   6155; K52 is smaller than the total, so no near match). No "Amount paid (" note (no gift card).
7. `POST /api/finance/reconcile` again → receipt split still C-cat(dining), C-sum(6155). C-links(C, []), C-nosplit(K52).
   The note is still there (FR-30: until you review or a later reading replaces the issues).
Expected final state: C as after step 5, unlinked, with the two reasons above. K52 unlinked, no split rows. C-mem(1).
No `transaction_receipt_links` row at all.
Failure/retry/restart variants:
- (a) Restart between steps 5 and 7 → the same as step 7: still no link to K52, the note still there.
- (b) Steps 1–4 with a link review (approve the link) and an unlink and re-link in place of step 3 → after each, the
  groceries rows stay groceries and each split sums to its target (D8; also X-D8).
- (c) Steps 1–5 with the link approved after step 3 → step 6 as above, except the note is "The match you confirmed to
  the $52.76 charge on 2026-11-12 was removed: this reading's total ($61.55) no longer matches it." (D36).
Evidence: pytest.

## SC-10 — Lines with indent from the vision reading
Requirement IDs: FR-15, FR-16, FR-17, FR-21
Nondeterministic components: vision stub V10: 27 entries. The breakfast lines, except lines 13 and 14 are one entry
"Veggie Sausage\nJalapeno Cheese Grits" with indent 1, and line 16 "No Allergies" has indent 5. Reasoning stub B0.
Initial state: empty library.
Actions/checkpoints:
1. Capture the image → the vision request asks for the `lines` schema, each item {text, indent} (FR-16). Its prompt
   text states: an indent of 0, 1 or 2 per line; 0 for a line at the main left edge; 1 for a line printed further
   right under the line above (sides, modifiers, notes under an item); 2 deeper; centered headings and footers 0;
   indent for no other reason; text with no leading spaces (FR-15). The test asserts each rule is present by key
   phrase, not exact wording.
2. The reading → 28 lines, `line-1` … `line-28`, texts exactly the table's (no leading spaces). Line 13 and line 14
   both indent 1. Line 16 indent unknown. Lines 11, 12 indent 1. Every other line indent 0.
3. `model_text` == "\n".join(the 28 texts). `extracted_text` and the Tables view keep today's forms (FR-16).
   `count_lines` over the reading gives 28 (D3).
4. Record with B0 → the extraction request's `lines` payload: `{"line_id", "text", "indent"}` with indent 1 on
   line-11 … line-14, indent 0 on the known-0 lines, and no `indent` key on line-16 (FR-21).
5. Citations: B0's quotes (whole line text) validate. Find on line-12 matches "Fresh Berry Pancakes" exactly.
Expected final state: 1 parse run (v7, succeeded), its stored result holding the 28 lines with indent. 1 receipt as in
SC-01.
Failure/retry/restart variants:
- (a) Indent values "1" (string), 1.5, −1, null → that line's indent unknown; the reading kept (FR-17).
- (b) A line entry with no indent key → unknown, the reading kept (D25).
- (c) Every line blank or whitespace → the run fails with "Model response was blank." No reading is published.
- (d) Tables: a stub table with `line_index` rows 7–10 → validates against the same indexes as a `full_text` reading
  of the same text would (FR-16).
Evidence: pytest `tests/test_vision_indent.py`.

## SC-11 — The rescue asks for lines with indent
Requirement IDs: FR-18
Nondeterministic components: vision `outputs` sequences
Initial state: an image already read once under v7 with V0 (the clean breakfast lines). Hash its parse folder.
Actions/checkpoints:
1. Read again (force) with outputs [old-shape answer `{"full_text": …}` (invalid against the new schema, D25), valid
   `lines` with indent] → 2 vision
   requests. The second asks for a schema whose only property is `lines` (items {text, indent}), with no `tables`, and
   its prompt states FR-15's rules. The new reading: 28 lines with indent, issue code `vision_table_invalid`.
2. Read again (force) with outputs [{"wrong": "shape"}, {"also": "wrong"}] → that parse run fails (status failed, an
   error as today). The reading from step 1 is still listed under History as succeeded. The document's recorded reading
   and its record are unchanged. Nothing is published from the failed run.
Expected final state: parse runs: initial (succeeded), step 1 (succeeded), step 2 (failed). The folders of the two
succeeded runs are byte-identical to before step 2.
Evidence: pytest.

## SC-12 — New reading versions; old readings stay readable
Requirement IDs: FR-19, FR-20 (and FR-17, FR-21 for old readings)
Nondeterministic components: vision stub with indent; B0
Initial state: one image document with an R6 run (`receipt-vision-v6-tables`), one scanned one-page PDF with a P3 run
(`pdf-pages-v3-layout`), one two-image combined document with a G2 run (`receipt-images-v2-tables`). Each old run is
recorded (a v56 extraction run). Hash every old parse folder.
Actions/checkpoints:
1. Version values → `VISION_VERSION` == "receipt-vision-v7-indent". `PDF_VERSION` != "pdf-pages-v3-layout" and the
   old value is still readable (in `PDF_VERSIONS`). `GROUP_VERSION` != "receipt-images-v2-tables", and the set of group
   versions that open (`GROUP_VERSIONS` or the plan's name) holds both the new value and "receipt-images-v2-tables"
   (D24).
2. Open each old run (`GET /api/documents/{id}/receipt-runs/…`) → it loads. Line ids, texts, `block_ids`, `model_text`
   and `extracted_text` equal the capture's. Every line's indent is unknown.
3. Extract again from the R6 run with B0 → the same number of reasoning requests as Q56, in the same order. In each,
   the `lines` payload equals Q56's byte for byte (FR-21). The rest of each body equals Q56's byte for byte once the row
   instruction is masked in both (D28; see "Baseline captures"). Same for the P3 and G2 runs: no request carries an
   `indent` key.
4. Read the image again (no force) → exactly one new parse run under v7 (not a reuse of the v6 run). Its lines carry
   indent.
5. Read the scanned PDF again → exactly one new parse run under the new `PDF_VERSION`, not one per page. Its lines
   `page-1-line-N` carry indent (FR-20).
6. Read the combined document again → exactly one new run under the new `GROUP_VERSION`. Lines on both pages carry
   their indent through `combine_pages` (FR-20).
7. Read the image again a second time with the same model identity, no force → reused: no new parse run (today's
   reuse rule).
8. History lists the old runs and they can still be selected and opened.
Expected final state: parse runs: 3 old (unchanged status) + 3 new. Old parse folders byte-identical to their hashes.
Failure/retry/restart variants:
- (a) An embedded-text PDF page → its lines have no indent, and its extraction request carries no `indent` key.
- (b) A PDF mixing an embedded-text page and a scanned page → only the scanned page's lines carry indent.
- (c) Old group run published (D32, `receipt_service.py:118`): a G2-shaped run under "receipt-images-v2-tables" left
  `running` with its `result.json` in its folder, then the manager restarts → startup recovery (`recover`) publishes it
  as a page-based result: status succeeded, lines `page-1-line-N` and `page-2-line-N`, no indent. It isn't marked
  interrupted and doesn't fail validation.
- (d) The second check (D32, `receipt_service.py:192`, in `ReceiptService.run`): checked by review, not by a test.
  `run` only executes runs created under the current versions (`:65`), so no public path executes an old group run.
  Review confirms the `:192` condition tests the same set of group versions as `publish` (`:118`).
- (e) D33: across step 3's requests (R6, P3, G2), no body contains `EXTRACTION_VERSION`'s value or an `indent` key,
  and every prompt but the masked row instruction equals Q56's.
Evidence: pytest `tests/test_vision_indent.py`, plus `tests/test_pdf_reader.py` and `tests/test_document_groups.py`
for the page and group paths.

## SC-13 — Side lines stay with their item
Requirement IDs: FR-22, FR-23
Nondeterministic components: B6 over the indented reading
Initial state: empty library.
Actions/checkpoints:
1. The rows request's instruction (every receipt form's) says an indented line with no price of its own belongs to the
   item above, is cited with it, and is never an item; and that a priced indented line keeps today's rules (FR-22).
2. Record → `receipt_items` 5 rows (the B0 items), sum 4885. No item named after a side line.
3. Georgia Peach Stack's evidence: line-10, line-11, line-12, line-13, line-14.
4. Notes, in order: "“No Allergies” is printed under “Georgia Peach Stack” with no price of its own, so it was kept
   with that item, not as an item.", the same for "Fresh Berry Pancakes" and "Veggie Sausage", then "and 1 more".
5. Receipt split C-sum(6155), C-cat(dining).
Failure/retry/restart variants:
- (a) B6z ($0.00 side lines) → the same as steps 2–4.
- (b) A side line published as the first item (no item before it) → kept as an item.
- (c) An indented line printing an amount (line 12 reads "Fresh Berry Pancakes $2.00", published as an item 2.00) →
  kept as its own item (D17).
- (d) A bill read from the same lines with an unpriced indented row → unaffected (no drop, no note).
- (e) Only two dropped lines → two notes, no "and N more".
Evidence: pytest `tests/test_receipt_side_lines.py`.

## SC-14 — No indent, no backstop
Requirement IDs: FR-23
Nondeterministic components: B6 over a reading with no indent (vision answer lines without indent keys, unknown per
D25; and the R6 old reading)
Initial state: empty library; and separately an old library with an R6 run.
Actions/checkpoints:
1. Record → 9 items, as today: the 5 B0 items plus the 4 side lines. No drop notes.
2. Extract again from the R6 run with B6 → 9 items, no notes.
Evidence: pytest.

## SC-15 — The Text view shows indentation
Requirement IDs: FR-26
Nondeterministic components: B0; real browser, opt-in
Initial state: `document_server` with a seed that records the breakfast receipt (SC-01 step 7).
Actions/checkpoints:
1. Open the document's source viewer → Text view. Lines 11–14 and 16 render one step in; other lines at the edge.
2. Each line's text content equals its stored text (no leading spaces in the text).
3. Find "No Allergies" → both line 11 and line 16 are found, and nothing else.
4. Reload → the same.
Failure/retry/restart variants: an old v6 reading in the Text view → no line indented, otherwise as today.
Evidence: browser test plus synthetic screenshots (`scripts/ui_shots.py`) at desktop and phone widths.

## SC-16 — An approved old receipt, then Categories
Requirement IDs: FR-11, FR-12, FR-14
Nondeterministic components: B0 for Read again
Initial state: old library with receipt D (approved by you, item 1 groceries by you).
Actions/checkpoints:
1. Extract again with B0 → D's `receipts`, `receipt_items` and receipt split equal the snapshot (approved). C-col(shown).
2. Edit details → Categories → Travel → receipt category travel. Item 1 keeps groceries stored (`category_source`
   user, as today); items 2 – 5 store travel with `category_source` receipt (D20). Receipt split: item rows 395, 395,
   1495, 1870, 730 travel, and the 391 difference as one no-item row, travel (D18: once FR-10 applies the difference is
   an amount no item carries, under the receipt's category, not spread as today's rule 5 does for a category other
   than dining). C-sum(5276). "Not matched to an item" 391. C-col(hidden).
3. `PUT …/items/2/category` {groceries} → 400, the FR-12 message. C-mem(0).
4. Run reconciliation → the split is still all travel, the no-item 391 row included.
Evidence: pytest.

## SC-17 — The backfill on an old dining receipt
Requirement IDs: FR-14
Nondeterministic components: the backfill's description stub answering groceries for every item
Initial state: old library with receipt E (items with no category) and one memory row (seller, "Coffee") →
groceries.
Actions/checkpoints:
1. Snapshot the receipt split (all dining, 5276).
2. Run the item-category backfill (`ItemCategorizer.run`, or its API entry point) → E's 5 items have category dining
   with `category_source` receipt ("From the receipt's category"). Coffee too, despite the memory row and the model.
3. Receipt split → C-snap. C-col(hidden).
4. Run the backfill again → E isn't pending; nothing changes.
Failure/retry/restart variants:
- (a) Receipt E with item 1 under a retired category (one the app's category list marks retired, picked by the fixture
  from that list) → the backfill gives item 1 dining with `category_source` receipt; its receipt split row (395) moves
  from the retired category to dining (D27). Every other row, the no-item 391 row included, equals the snapshot.
  C-sum(5276). Nothing else about the split changes: the backfill applies no D18 rule.
- (b) A grocery receipt with items with no category → categorised as today (memory, then the model).
- (c) Receipt H with its item's category set to null (backfill pending) → the item takes travel (the receipt's
  category), source receipt. Receipt split C-snap: the tip row stays dining and the difference stays spread (today's
  rules 4 and 5; the backfill isn't an FR-14 event, D27).
Evidence: pytest.

## SC-18 — "Not matched to an item" leaves out the tip
Requirement IDs: FR-27
Nondeterministic components: B0, B8
Initial state: three libraries (or one with three documents): SC-01 after step 7; B8 recorded; old receipt E with its
items categorised dining (the v56 tax-missed receipt).
Actions/checkpoints:
1. Breakfast payload → the "Not matched to an item" amount is 0, so the row is hidden. Tip $8.79 shown. By category
   "Dining $61.55". Receipt split: item rows 5276 + tip row 879.
2. B8 payload → "Not matched to an item" $2.00 and Tip $3.00 on its own row. Receipt split, worked by hand: item row
   2100 (Burger 2000 + tax 100), tip row 300, difference row 200; all dining, C-sum(2600).
3. E payload → "Not matched to an item" $3.91, as today. Receipt split as the snapshot (item rows + 391).
4. For all three, `category_splits` equals what it was before the payload was built (display only).
Failure/retry/restart variants:
- (a) The breakfast receipt partly paid by a $10.00 gift card (SC-01 with a gift-card line, paid 5155) → the shown amount
  is the receipt split's no-item rows less the tip's resized row, read from `category_splits`. With no other no-item
  row it is 0 and hidden.
- (b) Browser: SC-01's page and B8's page show the footers above.
Evidence: pytest, plus the browser test.

## SC-19 — Several total lines, one receipt (characterization)
Requirement IDs: FR-01 (D14)
Nondeterministic components: B0 (its `ReceiptStarts` answer: one receipt)
Initial state: empty library.
Actions/checkpoints:
1. Record → the `ReceiptStarts` question was asked once (five total lines).
2. One receipt, total 6155, no document segments split it.
Evidence: pytest. Characterization only: if it fails in practice, an open-work entry, not a rule change.

## SC-20 — A link you confirmed is removed, and the matching charge links
Requirement IDs: FR-28, FR-29, FR-30 (D34, D36, D37, D41)
Nondeterministic components: B0 for Read again
Initial state: old library with receipt C and charges K52, K61 and K60 (K60's rejected link row to C as fixture state).
Actions/checkpoints:
1. Upgrade (as SC-05 step 2) → C-snap. Snapshot K60's link row.
2. `POST /api/finance/reconcile` → C links K52 (exact, proposed; K61 isn't considered while an exact charge exists).
   C-links(C, [(K52, proposed), (K60, rejected)]).
3. Approve that link (the link review, verified) → C-links(C, [(K52, verified), (K60, rejected)]). Charge split
   C-sum(5276).
4. Extract again from the v6 reading with B0 → total 6155, tip 879 worked out. Then:
   - The link to K52 is removed, not rejected (FR-29, D37). C-nosplit(K52). K52's `merchant_id` is NULL again.
   - C-note(C, "The match you confirmed to the $52.76 charge on 2026-11-12 was removed: this reading's total ($61.55)
     no longer matches it.") and C-review(`needs_review`, [the FR-06 reason, that note]) (FR-30, D36).
   - The reconciliation after the reading links K61 (exact, proposed; signals include `amount`). C-links(C, [(K61,
     proposed), (K60, rejected)]). Charge split for K61: C-cat(dining), C-sum(6155).
   - K60's row equals its snapshot. No open `ambiguous_receipt_match` question for C.
5. `POST /api/finance/reconcile` again → nothing changes: C-links as after step 4, both splits as after step 4.
Expected final state: C linked to K61 only (proposed); K52 with no link row and no split rows; K60's rejected row as at
the start; C waiting in Review with the FR-06 reason and the note. C-mem(0).
Failure/retry/restart variants:
- (a) Not a rejection (D37): without K61 in the library, after step 4 C-links(C, [(K60, rejected)]) and no question
  (K52 is smaller than 6155). Then Correct Total to 52.76 (`POST …/corrections` {total: "52.76"}, which reconciles
  after it) → C links K52 again, exact, proposed: C-links(C, [(K52, proposed), (K60, rejected)]). The removal note is
  still present (it doesn't start with "Total", so the correction doesn't resolve it).
- (b) Restart between steps 4 and 5 → the same end state.
- (c) K52 read from a document (imported from a synthetic CSV, as the import tests do, so it has evidence): after step
  3 the two documents show each other as the same purchase (an `occurrence_links` row, reason `same_record`, status
  verified). After step 4 they no longer do, and no `occurrence_links` row between them is `rejected` (D41).
Evidence: pytest `tests/test_dining_receipts.py`.

## SC-21 — Which links hold after a re-read (every receipt kind)
Requirement IDs: FR-28, FR-29, FR-30 (D35, D36, D38)
Nondeterministic components: B11 and its variants
Initial state: empty library; charge K10.
Actions/checkpoints:
1. Record B11; `POST /api/finance/reconcile` → total 1000; C-links(receipt, [(K10, proposed)]). Remember the row.
2. Extract again with B11 (same total) → the link row unchanged; C-nonote (D39: an unchanged total tests nothing).
3. Extract again with B11b (900) → the proposed link is removed: reconciliation never links a charge larger than the
   total by itself (D35). C-links(receipt, []), C-nosplit(K10), C-note(receipt, "The match to the $10.00 charge on
   2026-11-12 was removed: this reading's total ($9.00) no longer matches it."), `needs_review`. The reconciliation
   after the reading opens an `ambiguous_receipt_match` question for the receipt with candidates exactly [K10] (a
   same-merchant charge at most 30% larger; the removed pair isn't rejected, D37).
4. Answer the question with K10 → C-links(receipt, [(K10, verified)]), method containing `near_amount` and
   `user_choice`. Charge split C-sum(1000); receipt split C-sum(900).
5. Extract again with B11 (1000) → the link you chose holds at the exact amount: unchanged, C-nonote.
6. Extract again with B11b (900) → it holds within the allowance (1000 × 100 ≤ 900 × 130): unchanged, C-nonote. Charge
   split C-sum(1000).
7. Extract again with B11c (700) → 1000 × 100 > 700 × 130, so it's removed: C-links(receipt, []), C-nosplit(K10),
   C-note(receipt, "The match you confirmed to the $10.00 charge on 2026-11-12 was removed: this reading's total ($7.00)
   no longer matches it."). The reconciliation after the reading opens no question (K10 is more than 30% larger).
Expected final state: the receipt (kind grocery) total 700, unlinked, `needs_review` with the note; K10 unlinked with no
split rows; no `transaction_receipt_links` row (none rejected); no open question.
Failure/retry/restart variants:
- (a) The allowance boundary, from step 6's state (verified link, total 900): Extract again with B11d (770) → holds
  (100000 ≤ 100100), C-nonote. Then with B11e (769) → removed (100000 > 99970), with the "you confirmed" note naming
  $7.69.
- (b) No total, from step 6's state: Extract again with B11n → removed, C-note(receipt, "The match you confirmed to the
  $10.00 charge on 2026-11-12 was removed: this reading has no total.").
- (c) Gift card (D40), fresh library with K9: record B11g (paid 900) and reconcile → linked to K9, proposed. Extract
  again with B11g' (paid 800) → removed. C-note(receipt, "The match to the $9.00 charge on 2026-11-12 was removed: this
  reading's total ($8.00) no longer matches it."). No issue starts with "Amount paid (". The reconciliation after the
  reading asks the near-match question with candidates [K9] (900 ≤ 800 × 1.3).
- (d) A foreign receipt (D35), built through the ledger as `tests/test_fx.py` builds one: EUR total 100.00, a cached
  EUR→USD rate of 1.10 on its date, a USD charge of −112.00 from the merchant, linked by choosing it in the
  cross-currency question (verified, `estimate_rate_id` stored). Extract again with total 102.00 (estimate 112.20;
  112.00 is 99.8% of it) → holds, C-nonote. Extract again with 90.00 (estimate 99.00; 112.00 is 113%) → removed, with
  the "you confirmed" note naming $112.00 and the total as FR-01's issue writes a EUR amount. Variant: the cached rate
  removed after linking → the stored rate still decides (same outcomes). Variant: a link with no stored rate and no
  cached rate → removed on any change of total.
Evidence: pytest `tests/test_reread_links.py`.

## SC-22 — What the rule leaves alone
Requirement IDs: FR-28 (D38, D39)
Parametrized; each case independent and from a fresh library.

| Case | Initial state | Action | Expected |
|---|---|---|---|
| (a) A receipt you approved | Old library with receipt B and K52; reconcile (B links K52) | Extract again with B0 | B as in the snapshot; the link unchanged; C-nonote(B) |
| (b) A failed reading | SC-09 after step 3 | Try again with the summary failing validation twice | The run fails; the link unchanged; C's issues unchanged; C-nonote |
| (c) A bill | A synthetic bill from the bill tests' fixtures (`tests/bill_kinds_fixtures.py`), linked to its payment by reconciliation | Read it again with a stub answering a different total | The link unchanged; no removal note (bills unchanged, D38) |
| (d) A kind change on a reviewed receipt | SC-01 after step 8 (linked to K61), approved | Change the kind to grocery (B7) | Amounts stay; the link unchanged; C-nonote |
| (e) Correct… on a linked receipt's total | SC-01 after step 8 | Correct Total to 60.00 | The link unchanged (today's rule); C-nonote |
| (f) Unchanged total, link that wouldn't pass D35 | B11 recorded (unlinked), then a fixture link to K8, verified | Extract again with B11 (1000) | The link to K8 unchanged; C-nonote (D39) |

Pay stubs: checked by review (`publish_income` touches no link; the suite's pay-stub tests keep their expectations).
Evidence: pytest `tests/test_reread_links.py`.

## X-D8 — Rebuilds that aren't about categories don't apply FR-10
Requirement IDs: FR-08, FR-14 (D5, D8)
Parametrized integration test; each case independent, from a fresh old library with receipt C (items 1 and 2
groceries) and, where needed, charge K52.

| Event | Entry point |
|---|---|
| Upgrade and restart | open the library with the changed code |
| Reconciliation run | `POST /api/finance/reconcile` |
| Link, then link review (approve) | reconcile, then `POST` review of the link |
| Unlink | the link review's reject |
| Item deletion | `DELETE /api/receipts/{id}/items/5` |
| Correct an amount | `POST …/corrections` {tax: "3.91"} |
| Correct an item | `PATCH /api/receipts/{id}/items/4` {quantity: 1} |
| Other Edit details fields | `POST …/corrections` {description: "Breakfast"} |
| Family share | the family routing path (`finance/family_routing.py`, as `tests/test_family_routing.py` drives it) |

Expected after each: items 1 and 2's rows (receipt split, and charge split where linked) are still groceries. Every
split C-sum to its target (the receipt's total, or the charge). C-col(shown). C-mem(0).

Mirror case (after FR-10 has applied): SC-01 after step 7, then each event above → the receipt split stays all
dining (FR-14: once applied, kept), and each split sums to its target. Second mirror: SC-07 after step 3 (travel) →
every row stays travel, the tip row included (D18 kept through rebuilds).

Old-rules case (D18 scope): a fresh old library with receipt H and a charge of −26.00 on its date. For each event above
that applies to H (upgrade and restart, reconciliation run, link and link review, unlink, correct an amount, correct
an item, other Edit details fields) → H's receipt split equals its fixture rows: tip row 300 dining, item row 2300
travel (the difference spread), C-sum(2600); where linked, the charge split has the same categories, C-sum(2600).
For H the amount correction is {tax: "1.50"}: total and tip are unchanged, so the item row is still 2600 − 300 = 2300
travel (the 150 difference spread) and the tip row 300 dining.
Contrast (FR-14 (c) applies FR-10): Edit details → Categories → Groceries on H → item row 2100 groceries, tip row 300
groceries, difference row 200 groceries with no item, C-sum(2600); "Not matched to an item" 200.

## X-Q1 — Edit details with the same category doesn't apply FR-10
Requirement IDs: FR-14 (c), Q1 (spec default, accepted)
Initial state: old library with receipt D (dining, item 1 groceries by you).
Actions/checkpoints:
1. Edit details → Categories → Dining (the category it already has) → item 1's split stays groceries; C-col(shown).
2. The item dropdown still works (D7): `PUT …/items/1/category` {dining} → 200, as today.
Evidence: pytest.

## X-UPG — The upgrade rewrites nothing (only if the plan adds a migration)
Requirement IDs: FR-08 (D5)
In `tests/test_migrations.py`, like `test_070_document_forms_leaves_existing_records_untouched`: build receipts A, B,
C, E and G at the previous schema version, run the feature's migration → every pre-existing column of `receipts`,
`receipt_items`, `category_splits`, `item_category_memory`, `parse_runs` and `extraction_runs` is unchanged. New
columns hold their "not applied / not worked out" value. `check_ledger` reports no errors.

## Other FR checks (no journey)
- **FR-15, FR-18, FR-22 prompt texts:** asserted on the requests the stubs receive (SC-10, SC-11, SC-13).
- **FR-25:** checked by review, not by a test: the `docs/documents.md` and `docs/money.md` sections (including "Reading
  a statement or receipt again" and "Near matches and foreign receipts" for FR-28 – FR-30) and the `docs/open-work.md`
  entries (D2's items, D16, stale links on bills and pay stubs, a link after Correct… on a total, a re-read that changes
  only the date or merchant, a lasting history entry for a removed link). No Q2 entry.
- **Version reuse summary** (SC-12): same version + same options + same identity → reused; a new version → exactly one
  new run per document, never one per page or call; `force` → a new run, as today.

## Evals (user-run, live model)
- Optional live check (spec "Nondeterministic outputs"): a synthetic image of the breakfast receipt on the agent test
  instance. Pass means lines 11–14 come back with indent ≥ 1, the total is 61.55, and no side line is an item. Only
  presence and these values are checked. If added to `evals/`, it follows `docs/evals.md`. The user runs it. Results
  are never read by Claude beyond an allowlisted `summary.json`.

## Traceability
| FR | Scenarios / tests | Test file |
|---|---|---|
| FR-01 | SC-01, SC-03 (c, d), SC-04 (c, d), SC-19 | test_dining_receipts.py |
| FR-02 | SC-01, SC-03 (d), SC-04 (a) | test_dining_receipts.py |
| FR-03 | SC-02, SC-03 (d), SC-06 (no new issue) | test_dining_receipts.py |
| FR-04 | SC-03 | test_dining_receipts.py |
| FR-05 | SC-04 (+ c, d) | test_dining_receipts.py |
| FR-06 | SC-01, SC-05, SC-09 | test_dining_receipts.py |
| FR-07 | SC-01 step 8, SC-07 step 5, X-D8 old-rules case | test_dining_receipts.py |
| FR-08 | SC-05, SC-09, SC-16, SC-22 (a), X-D8, X-UPG | test_dining_receipts.py, test_migrations.py, test_reread_links.py |
| FR-09 | SC-06 | test_dining_receipts.py |
| FR-10 | SC-01, SC-05, SC-07, SC-09, SC-16, X-D8 | test_dining_receipts.py |
| FR-11 | SC-07, SC-09, SC-16, SC-17 | test_dining_receipts.py, test_receipt_items_browser.py |
| FR-12 | SC-07, SC-09, SC-16 | test_dining_receipts.py |
| FR-13 | SC-08, X-D8 old-rules case (tip dining before FR-10) | test_dining_receipts.py |
| FR-14 | SC-05, SC-07 (c), SC-09, SC-16, SC-17, X-D8, X-Q1 | test_dining_receipts.py |
| FR-15 | SC-10, SC-11 | test_vision_indent.py |
| FR-16 | SC-10 | test_vision_indent.py |
| FR-17 | SC-10, SC-11, SC-12, SC-14 | test_vision_indent.py |
| FR-18 | SC-11 | test_vision_indent.py, test_vision_tables.py |
| FR-19 | SC-12 (+ c; d by review) | test_vision_indent.py |
| FR-20 | SC-12 | test_vision_indent.py, test_pdf_reader.py, test_document_groups.py |
| FR-21 | SC-10, SC-12 (step 3, e) | test_vision_indent.py |
| FR-22 | SC-13 | test_receipt_side_lines.py |
| FR-23 | SC-13, SC-14 | test_receipt_side_lines.py |
| FR-24 | SC-05 | test_dining_receipts.py |
| FR-25 | review | — |
| FR-26 | SC-15 | test_document_v2_browser.py |
| FR-27 | SC-01 step 7, SC-03 (c, d), SC-07 step 3, SC-16, SC-18, X-D8 | test_dining_receipts.py, test_receipt_items_browser.py |
| FR-28 | SC-05 step 5, SC-09 step 6, SC-20, SC-21 (+ a–d), SC-22 | test_dining_receipts.py, test_reread_links.py |
| FR-29 | SC-05 step 5, SC-09 step 6, SC-20 (+ a, c), SC-21 steps 3, 7 | test_dining_receipts.py, test_reread_links.py |
| FR-30 | SC-05 step 5, SC-09 step 6 (+ c), SC-20 step 4, SC-21 (+ b, c) | test_dining_receipts.py, test_reread_links.py |

| SC | Test |
|---|---|
| SC-01 | test_dining_receipts.py::test_sc01_breakfast_counts_what_was_charged (+ variants a–d) |
| SC-02 | test_dining_receipts.py::test_sc02_printed_tip_is_kept (+ a) |
| SC-03 | test_dining_receipts.py::test_sc03_no_tip_is_invented (+ a–d) |
| SC-04 | test_dining_receipts.py::test_sc04_suggested_tip_table_is_never_the_source (+ a–d) |
| SC-05 | test_dining_receipts.py::test_sc05_old_receipts_stay_until_read_again |
| SC-06 | test_dining_receipts.py::test_sc06_your_tip_correction_wins (+ a, b) |
| SC-07 | test_dining_receipts.py::test_sc07_one_category_on_a_dining_receipt (+ a–c); browser step 1 |
| SC-08 | test_dining_receipts.py::test_sc08_kind_change_and_undo (+ a, b) |
| SC-09 | test_dining_receipts.py::test_sc09_old_receipt_keeps_categories_until_read_again (+ a–c) |
| SC-10 | test_vision_indent.py::test_sc10_lines_with_indent (+ a–d) |
| SC-11 | test_vision_indent.py::test_sc11_rescue_asks_for_lines |
| SC-12 | test_vision_indent.py::test_sc12_new_versions_old_readings_readable (+ a–c, e; d by review) |
| SC-13 | test_receipt_side_lines.py::test_sc13_side_lines_stay_with_their_item (+ a–e) |
| SC-14 | test_receipt_side_lines.py::test_sc14_no_indent_no_backstop |
| SC-15 | test_document_v2_browser.py::test_sc15_text_view_indentation |
| SC-16 | test_dining_receipts.py::test_sc16_approved_old_receipt_then_categories |
| SC-17 | test_dining_receipts.py::test_sc17_backfill_on_old_dining_receipt (+ a–c) |
| SC-18 | test_dining_receipts.py::test_sc18_not_matched_leaves_out_the_tip (+ a); browser (b) |
| SC-19 | test_dining_receipts.py::test_sc19_several_totals_one_receipt |
| SC-20 | test_dining_receipts.py::test_sc20_confirmed_link_removed_matching_charge_links (+ a–c) |
| SC-21 | test_reread_links.py::test_sc21_which_links_hold_after_a_reread (+ a–d) |
| SC-22 | test_reread_links.py::test_sc22_what_the_rule_leaves_alone[a–f] |

Commands: `python -m pytest tests/test_dining_receipts.py tests/test_vision_indent.py tests/test_receipt_side_lines.py
tests/test_reread_links.py`,
then the whole suite (`python -m pytest`) for the existing tests the stub-shape change touches. Browser:
`RUN_BROWSER_TESTS=1 python -m pytest tests/test_receipt_items_browser.py tests/test_document_v2_browser.py`.

## Resolved gaps (round 1 → spec round 3; round 2 → spec round 4)
| Gap | Decision | Where the contract now tests it |
|---|---|---|
| G1 tip row on a recategorised dining receipt | D18 | SC-07 step 3, SC-16 step 2, X-D8 mirror and old-rules case, SC-17 (c) |
| G2 no tip line, later larger total | D19 | SC-03 (c) |
| G3 stored item categories once FR-10 applies | D20 | SC-01, SC-05, SC-07, SC-09, SC-16 |
| G4 charge link after a re-read changes the total | D21 (Q2 default), superseded by D34 – D41 in round 5 | SC-05 step 5, SC-09 step 6 (+ c), SC-20 – SC-22 |
| G5 fallback after a rejected table total | D22 | SC-04 step 2, (c); B5 has one summary answer |
| G6 nearest pre-tip amount; disagreeing amounts | D23 | SC-01 step 3, SC-03 (d) |
| G7 old group version readable | D24 | SC-12 step 1 |
| G8 missing indent key; `{full_text}` answer | D25 | SC-10 (b), SC-11 step 1, SC-14 |
| G9, G10 FR-06 reason and review after Correct Tip | D26 | SC-06 steps 2 – 4 |
| G11 backfill and retired categories | D27 | SC-17 (a), (c) |
| G12, G13 old-reading request and its capture | D28 | "Baseline captures", SC-12 step 3 |
| G14 order of the amounts in D23's issue | D29 (reading order, earlier first) | SC-03 (d), exact text |
| G15 card-terminal "Amount:" line | D30 (only FR-01's labels) | SC-03 (d), SC-04 (c), (d) with B5a |
| G16 footer wording after Correct Tip | D31 (today's warning, no amount) | SC-06 step 3 |
| G17 second exact group-version check | D32 (`receipt_service.py:118` in `publish`, `:192` in `run`) | SC-12 step 1, (c), (d) by review |
| G18 no other change to old readings' requests | D33 | SC-12 step 3, (e) |

## Gaps
None open. G14 – G18 are settled by the spec's D29 – D33 (see "Resolved gaps"). Round 5 (Q2 reversed) opened no gap:
every expected value in SC-09 step 6 and SC-20 – SC-22 comes from FR-28 – FR-30 and D34 – D41.
