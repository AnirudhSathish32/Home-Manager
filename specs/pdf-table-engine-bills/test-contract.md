# Test contract: pdf-table-engine-bills
Spec sha256: the bundle hash (spec.md + this file) from `~/.agent-harness/gate.py hash --feature pdf-table-engine-bills
--stage spec`. It isn't copied here, because writing it in would change it.

Every expected value comes from `spec.md`, is worked out by hand from the synthetic fixtures below (arithmetic shown), comes
from the existing tests named below (their assertions at `06cbb9b` are the oracle for "unchanged"), or comes from a
generator's inputs. None comes from running the code under change. Where the spec leaves an outcome open, it is listed
under "Gaps", not invented. Round 2 (2026-11-08) follows the spec's D21 (G1), D22 (G2) and D23 (G3 – G8 left to the plan).
Round 3 (2026-11-08) follows D24 (G12: the section title alone gives the holder; a disagreeing model holder gives way, with a
note) and D25 (a rate's precision is judged by its value), with the amended FR-102, FR-110, SC-102 and SC-112.

## Conventions for every scenario
- **Environment.** A `tmp_path` library and database only. Never `P:\Finances`, `%LOCALAPPDATA%\HomeManager`,
  `P:\EvalCorpus` or their Linux equivalents. Record tests go through the real services, as
  `tests/test_layout_consumers.py::test_native_paystub_reaches_ledger_search_and_source_cells` and
  `tests/test_paystub_cleanup.py` (`pdf_store`, `started(…)`) do: `make_pdf` into the Inbox, `capture`, the reading
  (`ReceiptService` with no vision call for text pages), then `ExtractionService.enqueue` + `run` with
  `ReasoningConfig(base_url=local_model…, model="synthetic-reasoning")`, home currency USD
  (`HouseholdConfig(home_currency="USD")`). The bill is the `receipts` row the run publishes
  (`run["publication"]`, `document_kind='bill'`); for split files, `run["publication"]["segments"]`. API steps use
  `create_app(…)` with `TestClient`. Browser steps are opt-in (`RUN_BROWSER_TESTS=1`, the `served()` helper).
- **Engine-level tests** call the engine on the saved reading as a bill, with no store and no model, and stay independent of
  one another. The entry point and result names are the plan's; the facts asserted (tables, columns and roles, rows and
  their labels and sections, totals, summary anchors by kind, other tables, unplaced lines, guesses, notes) are the spec's.
- **Synthetic PDFs only:** `tests/test_pdf.py` `make_pdf` with dict pages of positioned items `(x, y, text)`, 10 pt
  Helvetica, page 612 × 792. Every page ends with the words-only footer
  `This bill is for your records. Amounts are in US dollars.` at (40, 40), so no page is sent to the vision model and the
  footer holds no amount.
- **Right-aligned amounts.** "r R" means the token's right edge is at x R: its left x is R minus its Helvetica width at
  10 pt (digits 5.56 pt; `,` `.` 2.78 pt; `-` `(` `)` 3.33 pt; `$` 5.56 pt; letters by the Helvetica AFM widths, computed in
  the fixture builder). Labels start at the stated left x. Lines are 16 pt apart unless stated.
- **P-checks.** Before a scenario's first checkpoint the test asserts the reading has the intended shape: every page is
  `embedded_text` (except the scanned and image variants of SC-126 and SC-119's photographed bill), and each amount
  column's saved word boxes agree on their right edge within 0.5 pt. A failed P-check is a fixture or reader problem, never
  a reason to change an expected value.
- **C-net.** The autouse fixture blocking non-loopback sockets stays on. Only `local_model` on loopback is reachable.
- **Shared checks**
  - **C-money:** `receipts.total_minor`, `amount_due_minor` and every `receipt_items.line_total_minor` and
    `unit_price_minor` are integer or null (`typeof`), currency `USD`; details' `minor` values are integers
    (`tests/test_bill_kinds.py` `assert_published_bill` already checks this shape; reuse it).
  - **C-docs:** the sha256 of each fixture's original and every file of its reading folder is unchanged by Extract,
    Extract again, the split actions and the corrections.
  - **C-lines(expected):** the bill's `receipt_items` ordered by `position` equal the expected list of
    `(description, line_total_minor, line_kind or line_type)` exactly, with no extra line. A credit is stored negative
    (`documents/extraction.py` `bill_lines`: `-amount` when `line_kind == "credit"`), so "credit 500" means `-500`.
    Where quantity and unit price are listed, `quantity` is the printed text, the unit price is as C-rate says, and the
    line's quantity × unit price check holds on the printed quantity and the printed rate (FR-113).
  - **C-rate(printed rate, line)** (FR-110, D21, D25): when the printed rate's value is not a whole number of cents
    (`0.1430`, `0.125`; today's test, `core/money.py:63` – `:65`), `receipt_items.unit_price_minor` is the rate in cents rounded half up (`document_checks.product`'s
    `ROUND_HALF_UP`, never half-even) and `json.loads(details_json)["unit_price"]` is `{"text": <the rate exactly as
    printed>, "locator": …}` whose locator cites the rate's printed word (its line id); when its value is a whole number
    of cents (`0.1200`, `0.12`, `0.1500`), however many zeros it prints, `unit_price_minor` is that value exactly and
    details hold no `unit_price` key (the decision is by value, D25, so `0.1200` and `0.1500` keep no text). Either way no entry of `record["issues"]` contains
    `Amount has more precision than USD allows`, and none starts `Charge line` (today's
    "quantity times unit price does not equal its line total" check would fail on the rounded cents: 140 × 0.14 = 19.60 ≠
    20.02).
  - **C-note(text):** the text (or, where the spec gives no exact wording, every listed fact as a substring) is among the
    bill's notes (a kinded bill's `json.loads(details_json)[bill_kind]["notes"]`, as today's `bill_lines` notes; the plan
    names the field if engine notes are kept elsewhere, and this check moves with it) and is **not** in the bill's issues
    (`receipts.validation_json`, `record["issues"]`).
  - **C-reason(facts):** exactly one entry of `record["issues"]` contains every listed fact; `review_status`
    `needs_review`.
  - **C-auto:** `record["review_status"] == "verified"` and `record["issues"] == []` (counted automatically).
  - **C-no-feature-review:** no issue mentions a column, a guess, an unplaced or unclassified line, a charge table, a
    printed total or subtotal, a split, "native source column" or "native table row(s) were not accounted for".
  - **C-no-grid** (as phase 3): every copied amount's evidence cites a word or an engine cell, and no model request after
    the `Classification` request carries a `reported_tables` entry whose id is a `table_grid` table with
    `source == "pdf_text"` (`layout_context.evidence_tables`).
  - **C-model-calls:** `local_model["requests"]` grows only by the reasoning calls the scenario's stubs answer
    (Classification per part, then the bill summary and line schemas per part); the engine and the split rule add none.
  - **C-segments(n):** `document_segments` holds n rows for the file's current hash with ordinals 0 … n−1; the
    `receipts` rows of the file are segments 0 … n−1 (`UNIQUE(blob_hash, segment)`); every line id of the reading is in
    exactly one segment's range. For n = 1 (a file read as one), no `document_segments` row.
  - **C-ledger:** `tests/conftest.py` `assert_ledger_healthy(store)` passes at the end of every record test.
- **Doubles**

| Component | Real or double | Specification |
|---|---|---|
| PDF reader | Real | Every PDF fixture is read by the real reader. |
| Reasoning model | `local_model` by schema (`tests/model_server.py` `by_schema`) | `Classification`: `bill`, `bill_kind` as the scenario says (`general` unless stated), citing the provider line. Bill summary (`BillSummary`, or `BillRentSummary` for rent): provider, dates, account last four, currency with printed values and lines; amounts as the scenario says. Line classification (today `BillLines` / `RentBillLines`; the plan may add an engine-row schema as phase 2 did, and the stubs move with it): one entry per charge row of the fixture with `description`, `category`, `line_kind` (or `rent_type`), `line_holder`, evidence citing the row's first line, amounts as the scenario says. For split files each list holds one answer per part, in file order. |
| Vision model (SC-119 photographed, SC-126 scanned and combined) | `local_model` vision stub | Returns the transcription lines given in the fixture, as `tests/test_bill_kinds.py` `read_bill` / `tests/test_extraction.py` `transcribe` build image readings. |
| Engine fault (SC-115) | `monkeypatch` | The bill engine's entry point raises `RuntimeError("injected engine fault")`. |
| Split-rule fault (SC-127 d) | `monkeypatch` | The bill split rule raises `RuntimeError("injected split fault")`; and separately a double returning 201 parts. |
| Previous version (SC-119, SC-121) | Fixture | `monkeypatch.setattr(extraction, "EXTRACTION_VERSION", "typed-extraction-v39-receipt-printed-signs")` while recording, and the DB state the v39 reading left seeded by SQL (as `tests/test_bill_kinds.py::test_version_a_v30_bills_line_kind_correction_survives_reading_it_again_as_rent` seeds v30), because the new code cannot reproduce the old reading. |
| Family (SC-119) | Fixture | `members=["alex", "blair"]` (for `correct_line`'s member check) and **no** Who has what entry, so no line's member is set by routing (`finance/family_routing.py` `FamilyRouting.refresh` is not called). |
| FAM-WHO (SC-102) | Fixture | Members alex and blair; Who has what = `tests/test_bills_ledger.py` `WHO[:2]` (phone `1111` alex, phone `2222` blair); routing applied by `FamilyRouting(store).refresh({}, FAM-WHO)` after Extract, as `tests/test_bills_ledger.py::test_a_phone_bill_is_shared_by_line_and_the_payers_charge_counts_only_their_part` does. |
| Clock | Real | No assertion depends on today's date (every due date is before 2026-11-08). |
| Bill layout generator (SC-123) | Real, seeded | Expected values from the generator's inputs, never from the engine. |

- **Test files (new unless stated):** `tests/bill_engine_fixtures.py` (builders, stubs and the hand-written expected values
  below); `tests/test_bill_engine.py` (engine level, SC-100 – SC-106); `tests/test_bill_engine_record.py` (SC-110 – SC-118,
  SC-121, SC-122); `tests/test_bill_corrections.py` (SC-119); `tests/test_bill_split.py` (SC-126 – SC-131);
  `tests/bill_engine_generator.py` and `tests/test_bill_engine_generator.py` (SC-123, SC-125's probe);
  `tests/test_bill_engine_browser.py` (SC-129 and SC-111 page steps, opt-in); `tests/test_evals.py` (extended, SC-124).
  The plan may rename them; the traceability table moves with them.
- **Cleanup.** pytest removes `tmp_path`; browser tests close through `served()`; the diagnose script's temporary folder
  is asserted gone (SC-125).

## Fixtures
Money is written as printed; expected values are minor units. Header lines are at x 40 from y 780 down, 12 pt apart.
Amounts in summary lines, charge rows, totals and stubs are at r 520 unless stated.

### BL-UTIL: the utility bill (one page)
| y | Left text (x 40 unless stated) | r 330 | r 420 | r 520 | Kind |
|---|---|---|---|---|---|
| 780 | `CITY POWER & WATER` | | | | header |
| 768 | `Account Number 1234-5678-9012` | | | | key (account) |
| 756 | `Statement Date 09/20/2026` | | | | key (statement date) |
| 744 | `Billing Period 08/15/2026 - 09/14/2026` | | | | header (no key) |
| 732 | `Due Date 10/15/2026` | | | | key (due date) |
| 708 | `Account Summary` | | | | text |
| 692 | `Previous Balance` | | | 82.10 | anchor previous balance |
| 676 | `Payment Received 09/20/2026` | | | -82.10 | anchor payments |
| 660 | `New Charges` | | | 97.55 | anchor new charges |
| 644 | `Total Amount Due` | | | 97.55 | anchor amount due |
| 620 | `Electric Charges` | | | | section title |
| 604 | (heading) | `Usage` | `Rate` | `Charge` | heading |
| 588 | `Energy Tier 1` | 500 kWh | 0.1200 | 60.00 | row |
| 572 | `Energy Tier 2` | 140 kWh | 0.1430 | 20.02 | row |
| 556 | `Customer Charge` | | | 12.00 | row |
| 532 | `Taxes and Fees` | | | | section title |
| 516 | `State Tax` | | | 5.53 | row |
| 492 | `Total Current Charges` | | | 97.55 | anchor new charges |
| 468 | `Usage History` | | | | text |
| 452 | `Month` | `kWh` | `Days` | | other-table heading |
| 440 – 308 | 12 rows, 12 pt apart: `Sep 2025` 590 30, `Oct 2025` 610 31, `Nov 2025` 540 30, `Dec 2025` 600 31, `Jan 2026` 680 31, `Feb 2026` 720 28, `Mar 2026` 650 31, `Apr 2026` 560 30, `May 2026` 500 31, `Jun 2026` 520 30, `Jul 2026` 610 31, `Aug 2026` 640 31 | kWh | Days | | other table |
| 280 | `Return this portion with your payment` | | | | text |
| 264 | `Account Number 1234-5678-9012` | | | | key (equal) |
| 248 | `Due Date 10/15/2026` | | | | key (equal) |
| 232 | `Amount Due` | | | 97.55 | anchor amount due (stub) |

Worked by hand: 500 × 0.1200 = 60.000 → 60.00; 140 × 0.1430 = 20.020 → 20.02; 60.00 + 20.02 + 12.00 + 5.53 = 97.55;
82.10 − 82.10 + 97.55 = 97.55. With the rounded cents the product would fail: 140 × 0.14 = 19.60 ≠ 20.02. The usage
history's kWh sum (7,220) and days are whole numbers matching no summary amount.

**EXP-UTIL:** C-lines `(Energy Tier 1, 6000, usage)` quantity `500 kWh`, C-rate(`0.1200`): `unit_price_minor` 12, no
`unit_price` in details; `(Energy Tier 2, 2002, usage)` quantity `140 kWh`, C-rate(`0.1430`): `unit_price_minor` 14 (14.30
cents, half up 14), details `unit_price.text` `0.1430` citing the y 572 r 420 word; `(Customer Charge, 1200, service)`
quantity and unit price null; `(State Tax, 553, tax_fee)` quantity and unit price null. `total_minor` 9755,
`amount_due_minor` 9755, `due_date` 2026-10-15, `issue_date` 2026-09-20, period 2026-08-15 – 2026-09-14, details
`previous_balance.minor` 8210, `payments_received.minor` 8210, `new_charges.minor` 9755; lines check and carried check
both hold (`cross_checks` counts both); C-auto.

**STUB-UTIL** (classes right): line kinds as EXP-UTIL, categories `utilities`. **STUB-UTIL-WRONG:** STUB-UTIL with every
amount 1.00 too high (61.00, 21.02, 13.00, 6.53; amount due and new charges 98.55; previous balance and payments 83.10),
quantities `600 kWh` / `150 kWh` and rates `0.1300` / `0.1500`, and Customer Charge given quantity `1` and unit price
`13.00`, so a value from the model is wrong everywhere.

### Variants of BL-UTIL
- **UTIL-2L:** the heading is two lines: y 616 `Usage` r 330 `Rate per` r 420 `This` r 520; y 604 `(kWh)` r 330, `kWh`
  r 420, `Charge` r 520. **UTIL-ODD:** headings `Consumed` r 330, `Price` r 420, `Amount Billed` r 520. **UTIL-NOHEAD:**
  no heading line. (SC-101.)
- **UTIL-SHUF (SC-105 a):** heading `Charge` r 330, `Usage` r 420, `Rate` r 520, each row's values moved with its column
  (Energy Tier 1: 60.00 r 330, 500 kWh r 420, 0.1200 r 520); Customer Charge 12.00 and State Tax 5.53 at r 330; all
  summary lines, totals and the stub keep r 520.
- **BL-HEADLESS (SC-105 b):** UTIL-SHUF with the heading line removed.
- **UTIL-LASTYEAR (SC-105 c):** the charge block replaced by heading `This Bill` r 420, `Last Year` r 520 and rows
  `Energy Charge` 80.02 / 72.15, `Customer Charge` 12.00 / 12.00, `State Tax` 5.53 / 4.98. This Bill: 80.02 + 12.00 + 5.53
  = 97.55 = new charges; Last Year: 72.15 + 12.00 + 4.98 = 89.13 (adds up to nothing printed). Variant **(c2)** with no
  heading: (b) still decides This Bill (the right-most rule would have picked Last Year, so this discriminates).
- **UTIL-LATE (SC-103):** BL-UTIL plus `If paid after 10/15/2026, pay $102.55` x 40 y 216, `$102.55` inside the run.
  **UTIL-LATE-COL:** the same with `102.55` alone at r 520.
- **UTIL-HALF (SC-110 step 6, FR-110's half-up boundary):** BL-UTIL with Energy Tier 2's rate printed `0.1450` and its
  charge `20.30`; `New Charges`, `Total Amount Due`, `Total Current Charges` and the stub `Amount Due` all `97.83`.
  Worked by hand: 140 × 0.1450 = 20.300 → 20.30; 60.00 + 20.30 + 12.00 + 5.53 = 97.83; 82.10 − 82.10 + 97.83 = 97.83;
  0.1450 $ = 14.50 cents → half up 15 (half-even would give 14, so this discriminates); with the rounded cents the product
  would fail: 140 × 0.15 = 21.00 ≠ 20.30.
- **UTIL-15 (SC-110 step 6, D25: whole cents printed with four decimals):** BL-UTIL with Energy Tier 2's rate printed
  `0.1500` and its charge `21.00`; `New Charges`, `Total Amount Due`, `Total Current Charges` and the stub `Amount Due` all
  `98.53`. Worked by hand: 140 × 0.1500 = 21.000 → 21.00; 60.00 + 21.00 + 12.00 + 5.53 = 98.53; 82.10 − 82.10 + 98.53 =
  98.53; 0.1500 $ = 15.00 cents, a whole number, so `unit_price_minor` 15 and no printed text kept.
- **UTIL-125 (SC-110 step 6, D25: three decimals, half a cent):** BL-UTIL with Energy Tier 2's rate printed `0.125` and its
  charge `17.50`; `New Charges`, `Total Amount Due`, `Total Current Charges` and the stub `Amount Due` all `95.03`. Worked by
  hand: 140 × 0.125 = 17.500 → 17.50; 60.00 + 17.50 + 12.00 + 5.53 = 95.03; 82.10 − 82.10 + 95.03 = 95.03; 0.125 $ = 12.5
  cents, not whole → half up 13 (half-even would give 12, so this discriminates), text `0.125` kept; with the rounded
  cents the product would fail: 140 × 0.13 = 18.20 ≠ 17.50.
- **UTIL-STRAY (SC-104):** BL-UTIL plus `Paperless billing saves paper` x 40, `2.00` r 590, at y 196 (outside every
  column).
- **UTIL-MISNC (SC-113 b):** BL-UTIL with `New Charges` and `Total Current Charges` both printed 99.55.
- **UTIL-2P (SC-114):** page 1 = BL-UTIL down to the usage table, with `New Charges` 99.55 and `Total Amount Due` 99.55
  in the box and no `Total Current Charges` line; page 2 prints prose at x 40 from y 780: `A message from City Power &
  Water`, `Your paper bill fee this month was 2.00.`, then the remittance stub at y 700 – 652 (`Return this portion…`,
  `Account Number 1234-5678-9012`, `Due Date 10/15/2026`, `Amount Due` 99.55 r 520). Page 2 has no charge table.
  Worked by hand: 97.55 + 2.00 = 99.55; 82.10 − 82.10 + 99.55 = 99.55.
- **BL-UTIL-R1 (SC-117, spec fixture):** (a) BL-UTIL plus `Balance Due` 50.00 at y 720 (above the box: first on page 1);
  `Previous Balance` 132.10; `Total Amount Due` 147.55; stub `Amount Due` 147.55. 132.10 − 82.10 + 97.55 = 147.55; with
  50.00 it would be 132.10 − 82.10 + 97.55 ≠ 50.00. (b) BL-UTIL without `Previous Balance`, `Payment Received`,
  `New Charges` and `Total Current Charges`, plus `Balance Due 50.00` at y 720; `Total Amount Due` 97.55; stub 97.55. Lines
  97.55 = 97.55. (c) BL-UTIL without `Previous Balance` and `Payment Received`, plus `Balance Due 50.00` at y 720;
  `Total Amount Due` 147.55; stub 147.55; new charges 97.55 still printed twice.
- **BL-UTIL-R2 (SC-118, spec fixture):** BL-UTIL without `New Charges` and `Total Current Charges`; `Previous Balance`
  150.00; `Payment Received 09/20/2026` -100.00; `Total Amount Due` 147.55; stub 147.55. 147.55 − 150.00 + 100.00 = 97.55
  = the lines. **R2-BAD:** amount due 150.55 in box and stub: 150.55 − 150.00 + 100.00 = 100.55 ≠ 97.55.
  **R2-NOPREV:** R2 without `Previous Balance` and `Payment Received` (today's rule: lines 97.55 against amount due 147.55).

### BL-PHONE: the phone bill (one page, no column heading)
Header: `METRO WIRELESS` (780), `Account Number 555-0100-7788` (768), `Due Date 10/12/2026` (756).

| y | Text (x 40 unless stated) | r 520 | Kind |
|---|---|---|---|
| 732 | `Previous Balance` | 120.00 | anchor |
| 716 | `Payments` | -120.00 | anchor |
| 700 | `New Charges` | 118.50 | anchor |
| 684 | `Amount Due` | 118.50 | anchor |
| 660 | `Alex 555-201-1111` | | section title |
| 644 | `Unlimited Plan` | 55.00 | row |
| 628 | `Device Payment` | 24.99 | row |
| 612 | `Total for Alex` | 79.99 | total |
| 588 | `Blair 555-202-2222` | | section title |
| 572 | `Basic Plan` | 35.00 | row |
| 556 | `International Pack` | 8.51 | row |
| 546 | `(Canada and Mexico)` x 52 | | wrapped label |
| 530 | `Total for Blair` | 43.51 | total |
| 506 | `Account Credits` | | section title |
| 490 | `Autopay Discount` | -5.00 | row (money off) |

Worked by hand: 55.00 + 24.99 = 79.99; 35.00 + 8.51 = 43.51; 79.99 + 43.51 − 5.00 = 118.50; 120.00 − 120.00 + 118.50 =
118.50.

**EXP-PHONE:** C-lines `(Unlimited Plan, 5500, service)`, `(Device Payment, 2499, K)`, `(Basic Plan, 3500, service)`,
`(International Pack (Canada and Mexico), 851, service)`, `(Autopay Discount, -500, credit)`, where K is the `LINE_KINDS`
value STUB-PHONE gives Device Payment (the fixture module names it once); `total_minor` 11850, `amount_due_minor` 11850;
details previous 12000, payments 12000; both checks hold; C-auto. Descriptions and kinds are the stub's (D7).

**STUB-PHONE:** classes as EXP-PHONE, Autopay Discount `credit`, amounts right; `line_holder` `Alex 555-201-1111` on
Unlimited Plan and `Blair 555-202-2222` on Basic Plan, each citing only its own row's line (so the holder is supported by
the section title, D22), and **null** on Device Payment, International Pack and Autopay Discount (so FR-110's "whether the
model gives that row a holder or none" is exercised, D24). Variants:
- **STUB-PHONE-NOHOLD (SC-102 b):** STUB-PHONE with `line_holder` null on every line.
- **STUB-PHONE-DISAGREE (SC-102 c):** STUB-PHONE with Basic Plan's `line_holder` `Alex 555-201-1111` (citing only its own
  row's line, y 572) instead of Blair's.
- **STUB-PHONE-AGREE (SC-102 d):** STUB-PHONE with Unlimited Plan's `line_holder` `Alex (555) 201-1111` (other format, same
  last four) and Basic Plan's `Blair` (a name only, a word of the title).
- **STUB-PHONE-CREDITHOLD (SC-102 e):** STUB-PHONE with Autopay Discount's `line_holder` `Alex 555-201-1111`.

**EXP-PHONE-HOLDERS** (FR-102, FR-110, D22, D24): `line_holder` `Alex 555-201-1111` on Unlimited Plan and Device Payment,
`Blair 555-202-2222` on Basic Plan and International Pack (Canada and Mexico), null on Autopay Discount; each of the four
holder lines' evidence (`financial_evidence_links` `locator_json` `line_ids` for the `receipt_item`) includes its section
title line (y 660 for Alex's rows, y 588 for Blair's) as well as its own lines; the credit's evidence includes no holder
title (`Account Credits` prints no phone number and no word of any model holder, so it is no holder title, FR-102). The
holder is the title as printed (whitespace collapsed, at most 80 characters), never the model's text. No holder note.

### BL-RENT: the rent bill as a text PDF
`tests/bill_kinds_fixtures.py` `RENT`'s seven lines printed at x 40 from y 780, 16 pt apart, each line's trailing `$`
amount split off into its own run at r 520 (`$1,450.00`, `$38.42`, `$1,488.42`); the dot leaders stay in the label runs.
Rent 1,450.00 + Water 38.42 = 1,488.42 = Amount Due. `Rent and Leasing Charges Due 10/01/2026` is no key line (FR-128).
**EXP-RENT:** C-lines `(Rent, 145000, rent)`, `(Water Usage, 3842, utility)`; Water's details `usage.text` `3,200 GAL`;
periods as `tests/test_bill_kinds.py::test_sc38_a_rent_bill_is_read_with_the_rent_form` asserts (Rent 2026-10-01 – 2026-10-31,
Water 2026-08-15 – 2026-09-14; the bill's period is the rent line's, FR-47); `amount_due_minor` 148842; `total_minor` 148842.
Stub: `rent_replies()` with every amount answered wrong (`1,540.00`, `83.42`, amount due `1,623.42`).

### MINI-BILL(k) and the multi-bill files (spec fixture, laid out)
One page each: header `CITY POWER & WATER` (780), `Account Number 1234-5678-9012` (768), `Statement Date S` (756),
`Billing Period B` (744), `Due Date D` (732); `Previous Balance` P (700), `Payment Received` R (684), `New Charges` N
(668), `Total Amount Due` A (652); `Customer Charge` 12.00 (620), `Energy Charge` E (604), `State Tax` T (588),
`Total Current Charges` N (564); stub `Due Date D` (300), `Amount Due` A (284). No column heading.

| k | S | B | D | P | R | E | T | N | A |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 07/02/2026 | 06/01/2026 - 06/30/2026 | 07/20/2026 | 80.00 | -80.00 | 64.80 | 4.62 | 81.42 | 81.42 |
| 2 | 08/03/2026 | 07/01/2026 - 07/31/2026 | 08/20/2026 | 81.42 | -81.42 | 70.20 | 5.06 | 87.26 | 87.26 |
| 3 | 09/02/2026 | 08/01/2026 - 08/31/2026 | 09/20/2026 | 87.26 | -50.00 | 58.50 | 4.22 | 74.72 | 111.98 |

Re-checked: 12.00 + 64.80 + 4.62 = 81.42 and 80.00 − 80.00 + 81.42 = 81.42; 12.00 + 70.20 + 5.06 = 87.26 and 81.42 − 81.42 +
87.26 = 87.26; 12.00 + 58.50 + 4.22 = 74.72 and 87.26 − 50.00 + 74.72 = 111.98; 81.42 + 87.26 + 74.72 = 243.40.

**EXP-MINI(k):** C-lines `(Customer Charge, 1200, service)`, `(Energy Charge, E, usage)`, `(State Tax, T, tax_fee)`;
`total_minor` N, `amount_due_minor` A, `due_date` D (ISO), `issue_date` S, period B, details previous P, payments |R|;
both checks hold; C-auto apart from the split note (a note).

- **BL-MULTI:** pages 1 – 3 = MINI-BILL(1), (2), (3).
- **BL-REMIT:** two pages. Page 1 = BL-UTIL from y 780 down to `Total Current Charges`. Page 2: `CITY POWER & WATER` (780),
  `Account Number 1234-5678-9012` (768), `Statement Date 09/20/2026` (756), the usage table (from 720), the sentence
  `Your previous bill, due 09/15/2026, is past due.` (520) and the stub (`Due Date 10/15/2026` 480, `Amount Due` 97.55 r 520
  at 464). Expected: EXP-UTIL, one bill.
- **BL-ACCT:** page 1 = MINI-BILL(1); page 2 = MINI-BILL(1)'s S, B, D with `Account Number 1234-5678-3456` and MINI-BILL(2)'s
  P, R, E, T, N, A. Expected bill 2: lines (1200, 7020, 506), total 8726, amount due 8726, due 2026-07-20.
- **BL-JOIN:** BL-MULTI with page 2's `Total Amount Due` and stub `Amount Due` lines removed.
- **BL-TWOONPAGE:** one page: MINI-BILL(1)'s fifteen lines in their order from y 780 down, 12 pt apart (to y 612), then
  MINI-BILL(2)'s fifteen lines from y 560 down, 12 pt apart (to y 392); amounts at r 520; footer as usual.
- **BL-NOKEY:** page 1 = MINI-BILL(1); page 2 = MINI-BILL(2) with **no** `Account Number`, `Statement Date` or `Due Date`
  line anywhere on the page, the stub's `Due Date` included (see G6).
- **BL-MULTI-VOID (SC-131 a):** BL-MULTI with `VOID` at x 260, y 720 on page 2 (a line of its own). **BL-MULTI-VOIDWORD:**
  `Checks are void after 90 days` at the same place instead (no void bill).
- **BL-MULTI-INV (SC-128):** BL-MULTI with `Invoice Number INV-2002` at x 40, y 720 on page 2; the stub's page-2
  `BillSummary` answers `invoice_number` `INV-2002` citing it.
- **MINI-2-ALONE (SC-131 b):** MINI-BILL(2) as a one-page file of its own (a different file hash).

Scanned and image forms (SC-126): **MULTI-SCAN** a three-page PDF of image-only pages (`make_pdf` page `None`) whose
vision stub transcribes each page's lines in MINI-BILL(k)'s text order (`Previous Balance 80.00`, … one line per printed
line, label and amounts joined by a space); **MULTI-IMAGES** three PNGs, one per MINI-BILL(k) with the same transcriptions,
combined into one document (`docs/documents.md` "Several images as one document"); **MINI-PNG** one PNG of MINI-BILL(1).

### GEN: the bill layout generator (SC-123)
Seeded (`SEED` fixed in `tests/bill_engine_generator.py`), at least 100 files, covering every variation FR-123 lists;
each case carries its own expected lines (description, minor, kind), summary amounts, chosen amount due, worked-out new
charges, split (pages per bill) and guesses from its inputs.

## SC-100 — charge rows: dates and usage are label text
Requirement IDs: FR-100
Initial state: BL-RENT; stub `rent_replies()` classes right, amounts wrong.
Actions/checkpoints:
1. P-checks.
2. Engine level -> one charge table, two rows; Rent's label `Rent 10/01/2026 - 10/31/2026`, one amount 1,450.00; Water's
   label `Water Usage 08/15/2026 - 09/14/2026 3,200 GAL`, one amount 38.42; `3,200` is no amount and no column; the
   `Due Date` and `Amount Due` lines are summary/key lines, not rows (Amount Due is an amount-due anchor, 1,488.42).
3. A unit check on a hand-built page: the single line `Payment Received 09/03/2026` with `-100.00` r 520 is an anchor whose
   only amount is -100.00 (the date is label text).
4. Extract -> EXP-RENT although every model amount was wrong; C-no-grid; C-money; C-docs.
Evidence: `pytest tests/test_bill_engine.py tests/test_bill_engine_record.py -k sc100`.

## SC-101 — headings are never required
Requirement IDs: FR-101
Initial state: UTIL-2L, UTIL-ODD, UTIL-NOHEAD, each with STUB-UTIL-WRONG.
Actions/checkpoints: engine level -> the same three columns (r 330, r 420, r 520) with roles quantity, rate, charge in
all three; UTIL-2L's charge column labelled `This`, `Charge`. Extract each -> EXP-UTIL; C-auto; no record note about
columns (the product rule decides, no guess).
Evidence: `-k sc101`.

## SC-102 — sections, subtotals, a wrapped label, holders from section titles
Requirement IDs: FR-102, FR-110 (holder, D22, D24)
Initial state: BL-PHONE; STUB-PHONE (holders on Unlimited Plan and Basic Plan only); FAM-WHO. Variants (b) – (e) are
separate tests from the same initial state with the stub named, each running steps 2 – 4 and asserting what it states.
Actions/checkpoints:
1. Engine level -> one charge table; five rows; sections: Unlimited Plan and Device Payment `Alex 555-201-1111`, Basic
   Plan and International Pack `Blair 555-202-2222`, Autopay Discount `Account Credits`; each of the four rows under a
   holder title is cited to that title line as well as its own lines; `Total for Alex` 79.99 and `Total for Blair` 43.51 are totals (not rows); the four summary
   lines are anchors; International Pack's label is `International Pack (Canada and Mexico)` and spans the y 556 and
   y 546 lines; no unplaced line.
2. Extract -> EXP-PHONE (five lines 5500, 2499, 3500, 851, -500, each with its section); the International Pack line's
   `locator.line_ids` lists its own lines y 556 then y 546 in that order (the title line y 588 is also listed; where it
   sits in the list is the plan's); no subtotal is a line; C-auto.
3. Holders -> EXP-PHONE-HOLDERS. Device Payment and International Pack carry the holder although the stub gave them none
   (from the section title, D24); the Unlimited Plan and Basic Plan holders are kept although their own row doesn't print
   them (printed in the title). No note starts `Line ` and contains `differs from its section title`. Before routing,
   every line's `member_id` is null.
4. Routing: `FamilyRouting(store).refresh({}, FAM-WHO)` -> by position: 1 Unlimited Plan `alex`, 2 Device Payment `alex`,
   3 Basic Plan `blair`, 4 International Pack `blair`, each `member_source` `configured`; 5 Autopay Discount member null,
   `member_source` null (`phone_member` of no holder). The bill's assignment suggestion is mode `lines` with members
   {alex, blair} and no ask (no holder's last four is unlisted; today's `suggest`).
5. (b) STUB-PHONE-NOHOLD (D24: the title alone gives the holder) -> step 2's lines; holders, evidence and members exactly
   as steps 3 – 4 (EXP-PHONE-HOLDERS; members alex, alex, blair, blair, null, `member_source` `configured` on the first
   four, null on the credit); no holder note; C-auto (no review reason).
6. (c) STUB-PHONE-DISAGREE -> Basic Plan (position 3) `line_holder` `Blair 555-202-2222` (the title wins), its evidence
   including the y 588 title line; after routing its member `blair`, `member_source` `configured`; the other lines' holders,
   evidence and members as steps 3 – 4; C-note(`Line 3: the holder Alex 555-201-1111 differs from its section title; the
   title's holder Blair 555-202-2222 was used.`) exactly, and it is the only holder note; C-auto (not a review reason).
7. (d) STUB-PHONE-AGREE (FR-110 "agrees") -> holders exactly EXP-PHONE-HOLDERS (the title as printed: Unlimited Plan
   `Alex 555-201-1111`, not `Alex (555) 201-1111`; Basic Plan `Blair 555-202-2222`, not `Blair`); no holder note (last four
   1111 match; `Blair` is a word of the title); members as step 4; C-auto.
8. (e) Regression, STUB-PHONE-CREDITHOLD -> Autopay Discount's `line_holder` null (under no holder title; today's rule:
   `Alex 555-201-1111` is not printed in its own line y 490, so it is dropped); its evidence cites no title; member null;
   no holder note; the other four lines as steps 3 – 4.
9. Holder-title parsing (FR-102), independent unit tests on hand-built one-section pages (a title line at x 40, then one
   row `Plan` 10.00 r 520); the entry point is the plan's. Phone-number titles, decided at engine level with no model:
   | Title as printed | Holder title? | Title's holder |
   |---|---|---|
   | `Alex 555-201-1111` (full) | yes | `Alex 555-201-1111` |
   | `Blair (555) 202-2222` (parentheses) | yes | `Blair (555) 202-2222` |
   | `Alex 555.201.1111` (dots) | yes | `Alex 555.201.1111` |
   | `Line 201-1111` (7 digits) | yes | `Line 201-1111` |
   | `Alex xxx-xxx-1111` (masked) | yes | `Alex xxx-xxx-1111` |
   | `Alex ***-1111` (masked) | yes | `Alex ***-1111` |
   | `Alex •••• 1111` (masked) | yes | `Alex •••• 1111` |
   | `Line ending 1111` | yes | `Line ending 1111` |
   | `Line ending in 1111` | yes | `Line ending in 1111` |
   | `Phone ends in 1111` | yes | `Phone ends in 1111` |
   | `Alex   555-201-1111` (three spaces) | yes | `Alex 555-201-1111` (whitespace collapsed) |
   | `555-201-1111 ` followed by 90 × `Z` | yes | its first 80 characters (`555-201-1111 ` + 67 × `Z`) |
   | `Charges 2026` (a year) | no | — |
   | `Electric Charges` | no (without a model holder; see below) | — |
   Through Extract (record level), the row's holder: under `Line 201-1111` with the model's holder null -> `line_holder`
   `Line 201-1111`; under `Charges 2026` with the model's holder `Alex 555-201-1111` -> null (no holder title; not printed
   in the row's own line, today's rule) and its evidence cites no title. Name-only titles (FR-102 (b)), a two-row section
   `Alex` (no number) with rows `Plan` 10.00 and `Device` 5.00: model holders `Alex 555-201-1111` on `Plan`, null on
   `Device` -> a holder title; both rows `line_holder` `Alex` (the title as printed), evidence including the title line,
   no holder note (a word, `Alex`, is printed in the title, so it agrees). The same section with model holders `Blair` on
   both rows (no word in the title) -> no holder title; both rows' holder null (today's rule: `Blair` is not printed in the
   rows' own lines), evidence cites no title. With no model holder on either row -> no holder title; both null. Section
   `Alex` with model holders `Alex` on `Plan` (position 1) and `Blair 555-202-2222` on `Device` (position 2) -> a holder
   title (`Plan`'s matches); both rows `Alex`; C-note(`Line 2: the holder Blair 555-202-2222 differs from its section
   title; the title's holder Alex was used.`); C-auto. (Positions equal the model lines' order in every case here; see
   G13.)
Evidence: `-k sc102`.

## SC-103 — summary anchors wherever printed; late amounts are nothing
Requirement IDs: FR-103
Initial state: BL-UTIL, UTIL-LATE, UTIL-LATE-COL; STUB-UTIL.
Actions/checkpoints:
1. Engine level on BL-UTIL -> six anchors: previous balance 82.10, payments -82.10, new charges 97.55 (box), amount due
   97.55 (box), new charges 97.55 (`Total Current Charges`), amount due 97.55 (stub); none is a row or a total; exactly
   four rows.
2. UTIL-LATE and UTIL-LATE-COL -> the same six anchors; the late line is no anchor, no row, no unplaced line.
3. Extract each -> EXP-UTIL; 102.55 is in no stored amount; no FR-117 guess note (97.55 printed alike).
4. Unit test on the anchor word list: each phrase FR-103 lists, in upper, lower and title case, is an anchor of its kind
   (`Balance Forward` previous balance; `Payments - Thank You` payments; `Current Charges` new charges; `Balance Due`,
   `Amount to Pay` amount due); `Previous Balances Report` is no anchor (whole words only). The list is one module
   constant. Anchor words inside a sentence are not asserted (G7).
Evidence: `-k sc103`.

## SC-104 — nothing dropped silently
Requirement IDs: FR-104
Initial state: UTIL-STRAY; STUB-UTIL.
Actions/checkpoints:
1. Engine level -> one unplaced line on page 1 with text `Paperless billing saves paper` and `2.00`; the usage history is
   one other table (12 rows) giving no rows and no unplaced line. Accounting: 4 rows + 0 totals + 6 anchors + 12
   other-table rows + 1 unplaced = 23 = every label-and-amount line of the page (counted by the test from the fixture's
   item list, not from the engine).
2. Extract -> EXP-UTIL; C-note contains `Page 1` and `Paperless billing saves paper`; C-auto; C-no-feature-review.
Evidence: `-k sc104`.

## SC-105 — which column is the charge
Requirement IDs: FR-105, FR-124 (guess)
Initial state: UTIL-SHUF, BL-HEADLESS (STUB-UTIL-WRONG); UTIL-LASTYEAR (c) and (c2) with a stub classifying the three rows.
Actions/checkpoints:
1. (a) UTIL-SHUF engine level -> r 330 charge, r 420 quantity (values `500 kWh`, `140 kWh`, unit kept), r 520 rate (decided
   by the product rule). Extract -> EXP-UTIL; C-auto.
2. (b) BL-HEADLESS -> the same roles and record; no guess note.
3. (c) UTIL-LASTYEAR -> r 420 charge, r 520 other; Extract -> lines `(Energy Charge, 8002)`, `(Customer Charge, 1200)`,
   `(State Tax, 553)`; 7215, 498 and 8913 in no stored amount; C-auto. (c2) with no heading -> the same (decided by (b),
   no guess note).
4. Tie (unit test on a hand-built page): two amount columns r 420 and r 520 each holding `Service` 10.00 and `Fee` 5.00,
   `New Charges` 15.00, `Amount Due` 15.00, no heading -> r 520 is the charge, one guess note naming the right-most choice,
   one guess of the column kind; with headings `Previous` r 420 / `Current` r 520 -> r 520 by heading, no guess.
Evidence: `-k sc105`.

## SC-106 — money off
Requirement IDs: FR-106
Initial state: (1) BL-PHONE with the stub answering Autopay Discount `line_kind` `service`; (2) BL-PHONE with the row
printed unsigned `5.00` under `Account Credits`, stub answering `credit`; (3) the same unsigned row with the stub answering
`service`; (4) BL-PHONE with the row printed `(5.00)`; (5) printed `5.00 CR`.
Actions/checkpoints:
1. (1) -> Autopay Discount `(-500, credit)`; C-note contains `Autopay Discount`; lines add up to 11850; C-auto.
2. (2) -> `(-500, credit)`; no note about the kind; C-auto.
3. (3) -> money off by the section title: `(-500, credit)`; C-auto (the section makes it money off; whether a note is
   added is not asserted, see G8).
4. (4), (5) -> as (1)'s amounts; engine level the row's amount is -5.00 in each.
Evidence: `-k sc106`.

## SC-110 — every amount from its printed cell; a rate kept as printed
Requirement IDs: FR-110, FR-113 (product on the printed rate)
Initial state: BL-UTIL; STUB-UTIL-WRONG. Variant UTIL-HALF with STUB-UTIL-WRONG (its Tier 2 amount answered 21.30).
Actions/checkpoints:
1. Extract -> EXP-UTIL (every amount, quantity and rate printed, none the model's); C-auto; C-no-grid; C-money; C-docs;
   C-model-calls. Energy Tier 1: quantity `500 kWh`, `unit_price_minor` 12, no `unit_price` in its details; Energy Tier 2:
   quantity `140 kWh`, `unit_price_minor` 14, details `unit_price.text` `0.1430` with a locator citing the `0.1430` word
   (y 572, r 420), `line_total_minor` 2002 (C-rate on both). No issue contains `Amount has more precision than USD
   allows`, and none starts `Charge line`.
2. The model's request for the line classification carries the engine's charge table as cells (each row's cells with
   their role) and no `table_grid` table.
3. A blank cell stays blank: Customer Charge's quantity and unit price are null although STUB-UTIL-WRONG gives it
   quantity `1` and unit price `13.00`.
4. Rent kind: BL-RENT with `bill_kind` `rent` -> EXP-RENT (SC-100); the same file classified `general` -> amounts as
   EXP-RENT, kinds the stub's `line_kind`.
5. Product on the printed rate (FR-113): the bill's quantity × unit price checks for Energy Tier 1 and Tier 2 (named by
   the plan; their inputs are the printed quantity and the printed rate text) compute 500 × 0.1200 = 6000 against 6000 and
   140 × 0.1430 = 2002 against 2002, both holding; neither uses 14 (140 × 0.14 = 1960 would fail). Customer Charge and
   State Tax have no product check (no quantity, no rate).
6. Half-up boundary, UTIL-HALF -> Energy Tier 2 `unit_price_minor` 15, details `unit_price.text` `0.1450`,
   `line_total_minor` 2030; product 140 × 0.1450 = 2030 holds; `total_minor` 9783, `amount_due_minor` 9783; C-auto; no
   precision issue. By value (D25), UTIL-15 (its Tier 2 rate answered `0.1600`, amount 22.00) -> Energy Tier 2
   `unit_price_minor` 15, **no** `unit_price` key in its details, `line_total_minor` 2100; product 140 × 0.1500 = 2100
   holds; `total_minor` 9853, `amount_due_minor` 9853; no precision issue; C-auto. UTIL-125 (its Tier 2 amount answered
   18.50) -> Energy Tier 2 `unit_price_minor` 13, details `unit_price.text` `0.125`, `line_total_minor` 1750; product
   140 × 0.125 = 1750 holds (140 × 0.13 = 1820 would fail); `total_minor` 9503, `amount_due_minor` 9503; no precision
   issue; C-auto. Unit test on the rate-to-cents rule (the function is the plan's): `0.1430` -> 14 with text,
   `0.1450` -> 15 with text, `0.1449` -> 14 with text, `0.1451` -> 15 with text, `0.0050` -> 1 with text, `0.125` -> 13
   with text, `0.1200` -> 12 no text, `0.1500` -> 15 no text, `0.12` -> 12 no text, `13.00` -> 1300 no text; none raises
   a precision issue.
7. The page: `GET /api/records/receipt/{id}` (the record API the document page uses) -> Energy Tier 2's unit price for
   display is the server-sent text `0.1430` (today's `display.unit_price_minor`, or the key the plan names) and Tier 1's
   is today's display of 12 cents; browser (opt-in): Energy Tier 2's line on the document page reads `Unit price: 0.1430`,
   built from the server's value (the page does no money arithmetic). A user unit-price correction on line 2
   (today's unit-price correction, value `0.15`) -> the page shows the corrected value as today, not `0.1430`.
Evidence: `-k sc110`; `tests/test_bill_engine_browser.py -k sc110`.

## SC-111 — summary amounts from the print, on a general bill
Requirement IDs: FR-111, FR-116
Initial state: BL-UTIL classified `general`; `BillSummary` stub with previous balance and payments not asked (the general
form has none) and amount due/new charges wrong (98.55).
Actions/checkpoints:
1. Extract -> details `previous_balance.minor` 8210 and `payments_received.minor` 8210 with locators citing the box lines;
   `amount_due_minor` 9755; `new_charges.minor` 9755; the carried check holds and is counted.
2. `GET /api/records/receipt/{id}` (the record API the page uses) -> `bill_summary.carried` = `[Previous balance 82.10,
   Payment received −82.10]`, `amount_due` 97.55; `earlier_balance` and `gap` null.
3. Browser (opt-in): the document page shows the lines, then the Previous balance and Payment received rows, then
   Amount due 97.55; the page loads no external resource.
4. Repeats (FR-111): a variant printing `Previous Balance` 82.10 in the box and `Previous Balance` 90.00 on a second line
   at y 476 -> previous balance 8210 (first on page 1), a C-note naming 90.00; the carried check runs on 82.10 and holds.
   A variant printing `Previous Balance` 90.00 first and 82.10 second -> 9000 used, note naming 82.10, carried check fails:
   C-reason(`Amount due: previous balance 90.00 USD`, `97.55 USD`).
Evidence: `-k sc111`; `tests/test_bill_engine_browser.py -k sc111`.

## SC-112 — matching model lines to engine rows
Requirement IDs: FR-112
Initial state: BL-PHONE; STUB-PHONE without `Device Payment` and with an extra line `Total for Alex` 79.99 citing y 612.
Variants: (b) the stub lists `Basic Plan` twice citing y 572; (c) the stub adds `Late fee waived` 3.00 citing the
`Account Credits` title line.
Actions/checkpoints:
1. Extract -> EXP-PHONE lines with `Device Payment` described `Device Payment` (the printed label), `line_kind` `other`,
   `category` null (the bill's), `line_holder` `Alex 555-201-1111` (the title's holder, for an engine row no model line
   cites; FR-110, D22, D24) with its evidence including the `Alex 555-201-1111` title line (y 660); C-note contains `Total for Alex` and
   `printed total`; C-note contains `Device Payment`; lines add up to 11850 (5500 + 2499 + 3500 + 851 − 500); C-auto;
   C-no-feature-review.
2. (b) -> one Basic Plan line (3500); C-note naming the second citation; C-auto.
3. (c) -> no `Late fee waived` line (3.00 is not printed in the cited line, today's `amount_supported`); C-note about it;
   the line list is EXP-PHONE's.
Evidence: `-k sc112`.

## SC-113 — checks keep today's effect
Requirement IDs: FR-113
Actions/checkpoints:
1. (a) BL-PHONE with `Total for Blair` printed 44.51 -> EXP-PHONE lines; C-note contains `Page 1` and `44.51`; C-auto
   (55.00 + 24.99 + 35.00 + 8.51 − 5.00 = 118.50 = new charges).
2. (b) UTIL-MISNC -> EXP-UTIL lines; `total_minor` 9955; C-reason(`New charges: the lines add up to 97.55 USD`,
   `99.55 USD`) and C-reason(`Amount due: previous balance 82.10 USD less payments 82.10 USD plus new charges 99.55 USD is
   99.55 USD, but the amount due is 97.55 USD`); no other issue; C-no-feature-review.
3. On every engine page of SC-100 – SC-118, no issue or note contains `no unambiguous native source column` or
   `native table row(s) were not accounted for` (asserted by a shared helper).
Evidence: `-k sc113`.

## SC-114 — a page with no charge table
Requirement IDs: FR-114
Initial state: UTIL-2P; STUB-UTIL-WRONG for page 1's rows, plus a line `Paper Bill Fee` 2.00, `line_kind` `tax_fee`,
citing page 2's prose line; summary amounts answered 99.55.
Actions/checkpoints:
1. Engine level -> page 1 one charge table; page 2 none; page 2's stub `Amount Due` is still an amount-due anchor (99.55).
2. Extract -> lines EXP-UTIL's four from cells (not the stub's wrong amounts), then `(Paper Bill Fee, 200, tax_fee)` from
   the model (2.00 is printed in its cited line); `total_minor` 9955, `amount_due_minor` 9955; C-note(`Page 2: no charge
   table was found in the printed columns, so its amounts are the reading's; check them.`); both checks hold; C-auto.
3. A reading saved without layout (`layout_context` absent; the plan names how the test builds it) -> read like a
   photographed bill: the model's amounts with today's citation checks; no page note.
Evidence: `-k sc114`.

## SC-115 — engine failure
Requirement IDs: FR-115
Initial state: (a) BL-UTIL with the engine fault double; STUB-UTIL (right amounts). (b) BL-MULTI with the engine fault
double; MINI stubs per part with right amounts.
Actions/checkpoints:
1. (a) Extract -> run succeeded; C-note(`The charge lines couldn't be read from the printed columns, so the reading's
   amounts were used; check them.`); the lines are the model's (EXP-UTIL values, each supported in its cited line);
   C-no-grid; `caplog` has one `log_failure` record naming `RuntimeError` and no record containing `CITY`, `Energy` or
   `97.55`.
2. (b) -> C-segments(3); three bills with EXP-MINI(k) values from the model; each carries the failure note; one
   `log_failure` record for the file.
Evidence: `-k sc115`.

## SC-116 — evidence lights the printed words
Requirement IDs: FR-116
Initial state: SC-102 done (BL-PHONE recorded); SC-110 done (BL-UTIL).
Actions/checkpoints:
1. `GET /api/provenance?record_type=receipt_item&…` for International Pack -> both lines (y 556, y 546) listed, in order,
   and its amount cites the word `8.51` (or its cell).
2. `provenance_for(db, "receipt", id, "amount_due")` on BL-UTIL -> cites the `97.55` word of the box's `Total Amount Due`
   line (the first amount-due anchor), with its line id.
3. Energy Tier 1's quantity and rate evidence cite `500` and `0.1200`.
Evidence: `-k sc116`.

## SC-117 — amount due printed several times
Requirement IDs: FR-117, FR-124 (guess `amount_due`)
Initial state: BL-UTIL-R1 (a), (b), (c); STUB-UTIL with amount due answered 50.00.
Actions/checkpoints:
1. (a) -> `amount_due_minor` 14755; no guess note; carried check holds; `total_minor` 9755; C-auto.
2. (b) -> `amount_due_minor` 9755; `total_minor` 9755 (lines' sum, no new charges printed); lines check against the amount
   due holds; no guess note; C-auto.
3. (c) -> `amount_due_minor` 5000; C-note(`The amount due is printed as 50.00 and 147.55; 50.00, the first on page 1, was
   used.`) (amounts asserted as substrings if the plan formats them with the currency); the record's guess list has one
   `amount_due` guess; `total_minor` 9755; C-auto (no check involves the amount due).
4. A late-payment amount is never chosen: UTIL-LATE-COL with R1 (c)'s box -> 102.55 is not among the values the guess note
   names.
Evidence: `-k sc117`.

## SC-118 — new charges worked out
Requirement IDs: FR-118
Initial state: BL-UTIL-R2, R2-BAD, R2-NOPREV; STUB-UTIL.
Actions/checkpoints:
1. R2 -> `total_minor` 9755; `amount_due_minor` 14755; details previous 15000, payments 10000; C-note(`New charges aren't
   printed; worked out as amount due 147.55 − previous balance 150.00 + payments 100.00 = 97.55.`) (amounts as substrings
   if formatted with currency); the lines check holds and its working (`finance/document_traces.py` "bill.lines") shows
   147.55 − 150.00 + 100.00; no carried-check entry among the record's checks; C-auto; spending counts 9755 on 2026-10-15.
2. R2-BAD -> `total_minor` 10055; `amount_due_minor` 15055; the worked-out note naming 150.55 and 100.55;
   C-reason(`the lines add up to 97.55 USD`, `100.55 USD`) (prefix: see G3); spending counts 10055 until corrected.
3. R2-NOPREV -> today's rule: `total_minor` 9755 (lines' sum); C-reason(`Amount due: the lines add up to 97.55 USD, but the
   amount due is 147.55 USD`); no worked-out note.
4. A photographed bill (RENT image, `rent_ledger(previous=True)` lines) is unchanged: its `test_bill_kinds.py` expectations
   hold (FR-120).
Evidence: `-k sc118`.

## SC-119 — line corrections after a re-read
Requirement IDs: FR-119, FR-121
### Journey A: BL-PHONE (one test, ordered checkpoints)
Seed (previous version double): BL-PHONE captured and read; recorded with the version patched to v39 and the engine fault
double (so the model's lines are used), stub lines `Unlimited Plan` 55.00, `Basic Plan` 35.00, `International Pack` 8.51,
`Autopay Discount` 5.00 credit (no Device Payment); then by SQL `receipt_items` position 3 `line_total_minor` 815 (the
misread), `review_status` `needs_review`, the run's `prompt_version` v39. Positions: 1 Unlimited Plan 5500, 2 Basic Plan
3500, 3 International Pack 815, 4 Autopay Discount -500.
1. User: `correct_line(id, 2, "member", "blair", members=["alex", "blair"])`; `correct_item(id, 3, "8.51")` ->
   `record_corrections` rows `member:2` (value `blair`, previous null) and `price:3` (value `8.51`, previous `8.15`);
   line 2 Basic Plan member `blair` (`member_source` `user`); line 3 `851`.
   The family has no Who has what entry (the Family double), so routing gives no line a member; this keeps the spec's
   "(no member)" for Device Payment true although it now has a holder.
2. Remove the engine fault double; Extract again under the new version (`reused: False`) with STUB-PHONE ->
   C-lines: 1 `(Unlimited Plan, 5500)`, 2 `(Device Payment, 2499)` member null, `member_source` null, `line_holder`
   `Alex 555-201-1111` (the title's holder; FR-110, D22, D24), 3 `(Basic Plan, 3500)` member `blair`
   (`member_source` `user`, kept by identity: same receipt_items id as before), 4 `(International Pack (Canada and
   Mexico), 851)`, 5 `(Autopay Discount, -500, credit)`.
3. Held: `review_status` `needs_review`; C-reason(`line 2`, `wasn't applied`, `24.99`, `35.00`) and
   C-reason(`line 3`, `wasn't applied`, `35.00`, `8.15`); each reason ends `Check the bill's lines and make the change again
   on the right line.`; no other issue; Device Payment's member is null; Basic Plan's amount is 3500 (the price 8.51 was not
   written onto it).
4. Kept: `record_corrections` still holds both rows unchanged (field, value, previous); they are still the latest of their
   fields; History lists them.
5. Extract again on the unchanged reading -> the same two held reasons, nothing applied, the same item ids (FR-122).
6. User: `correct_item(id, 3, "35.00")` -> a new `price:3` row replaces the held one; its reason is gone. User:
   `correct_line(id, 2, "member", "alex", …)` -> the `member:2` reason is gone; line 2 member `alex`. Extract again ->
   both applied (line 2 prints 24.99 = the amount it was made on; line 3 prints 35.00 = the corrected price), no held
   reason.
### Journey B: BL-UTIL, nothing shifted
Seed: BL-UTIL at v39 as above with lines 1 Energy Tier 1 6000, 2 Energy Tier 2 2002, 3 Customer Charge 1200, 4 State Tax
535 (misread). User: `correct_item(id, 4, "5.53")`; `correct_line(id, 3, "member", "alex", …)`.
1. Extract again -> EXP-UTIL; line 4 is 553 (the price correction now read exactly: applied, no reason); line 3 member
   `alex`; no held reason; C-auto.
### Journey C: photographed rent bill (D15)
Seed: `read_bill` with RENT (image) and `rent_replies()` -> lines 1 Rent 145000, 2 Water Usage 3842. User:
`correct_line(id, 2, "member", "blair", …)`.
1. Read the file again so its transcription is RENT with `Pet Fee $25.00` inserted between the Rent and Water lines and
   `Amount Due…$1,513.42` (1,450.00 + 25.00 + 38.42 = 1,513.42); stub lines Rent, Pet Fee 25.00 (`other`), Water ->
   lines 1 Rent 145000, 2 Pet Fee 2500 member null, 3 Water Usage 3842 member `blair` (kept by identity);
   C-reason(`line 2`, `25.00`, `38.42`); the same receipts id.
2. Read again with the original RENT transcription -> line 2 is Water Usage 3842 again: `member:2` applied, its reason gone.
### Variants
- **Made before this change:** Journey A with step 1's two `record_corrections` rows inserted by SQL in today's shape
  (`field`, `value`, `previous`, no remembered amount) instead of through the new code -> the same outcomes as steps 2 – 4
  (compared with the amounts the v39 reading stored: line 2 3500; for `price:3`, the `previous` 8.15; see G4).
- **Decided bill:** Journey A with the bill verified through the review API before step 2 -> its `receipts` and
  `receipt_items` rows are byte-identical after Extract again; nothing held.
- **Receipts unchanged:** a receipt (not a bill) with a `price:2` correction re-read with a line added above -> the price
  lands on position 2 as today (`tests/test_receipt_*` expectations); no held reason.
Evidence: `pytest tests/test_bill_corrections.py`.

## SC-120 — nothing else changes
Requirement IDs: FR-120, FR-125
Each passes unchanged: `tests/test_bill_kinds.py`, `tests/test_bills_ledger.py`, `tests/test_recurring_bills.py`,
`tests/test_layout_consumers.py` (including `test_native_invoice_and_statement_copy_amount_not_unit_price_or_balance`:
invoices stay on today's path), document-forms suites (`tests/test_document_forms*.py`), receipt suites
(`tests/test_receipt_*.py`, `tests/test_receipt_segments.py`), `tests/test_table_engine*.py`, `tests/test_statement_*.py`,
`tests/test_paystub_*.py` (split suite included), `tests/test_pdf_layout.py`, `tests/test_vision_tables.py`,
`tests/test_extraction.py`, `tests/test_spending_splits.py`, `tests/test_splits_by_code.py`, and the phase 1 and pay stub
generators.
**Tests this change edits** (and only these, each with its requirement):
- `tests/test_evals.py` tests asserting the corpus has 53 cases
  (`test_a_dry_run_checks_everything_and_writes_nothing`, `test_the_synthetic_corpus_and_the_example_config_are_valid`,
  `test_table_engine_aligned_statements_are_added_after_the_existing_documents_and_change_none_of_them`,
  `test_pay_stub_aligned_files_are_added_after_the_existing_documents_and_change_none_of_them`): 53 -> 58, the first 53 ids
  and answers unchanged (FR-124).
- None other is known at `06cbb9b`. If a bill test's seeded line correction now holds because its line shifted (FR-119),
  or a test asserts `retire_segments`' "receipt" wording on a bill row (FR-132 words it "bill"), the handoff names it
  with that requirement before it is edited.
Any other test whose expected value changes is a defect against this contract.
Evidence: the suites above.

## SC-121 — version and existing records
Requirement IDs: FR-121
Initial state, recorded with the version patched to v39: (1) BL-UTIL undecided (seeded as SC-119 B without corrections);
(2) BL-UTIL-R1 (a) verified through the review API; (3) BL-MULTI recorded as one undecided bill (split rule patched to one
part, as v39 did; receipts id R0, segment 0).
Actions/checkpoints:
1. `EXTRACTION_VERSION` != `typed-extraction-v39-receipt-printed-signs`.
2. Extract again on each -> (1) `reused: False`, EXP-UTIL; (2) its `receipts` and `receipt_items` rows byte-identical;
   (3) C-segments(3); segment 0 keeps id R0 with EXP-MINI(1); segments 1 and 2 are new ids with EXP-MINI(2), EXP-MINI(3).
3. No migration file is added (`migrations/` listing unchanged at HEAD's last migration).
Evidence: `-k sc121`.

## SC-122 — determinism
Requirement IDs: FR-122
Initial state: UTIL-STRAY (an unplaced line), BL-UTIL-R1 (c) (a guess), BL-MULTI.
Actions/checkpoints: Extract, then a second run on the same reading (forced through `ExtractionService.enqueue` + `run`,
as `tests/test_paystub_split.py::test_sc66_extract_again_on_the_three_stub_file_changes_nothing`) -> identical `receipts`
and `receipt_items` rows (ids included, `updated_at` excepted), `record_corrections`, `financial_evidence_links`,
`document_segments`, notes, guess lists and evidence; engine-level reads run twice on each reading give equal results;
C-model-calls (the second run's requests are the same schemas and count as the first's).
Evidence: `-k sc122`.

## SC-123 — the generator
Requirement IDs: FR-123
Actions/checkpoints: every generated file is built with `make_pdf`, read, and recorded with stubs drawn from its inputs ->
every line, quantity, rate, summary amount (amount due chosen, new charges printed or worked out) and split exact; every
bill's checks hold; the run covers each FR-123 variation at least once (asserted from the cases' choices: each kind, each
heading style, each credit style, each summary placement, previous balance/payments printed or not, new charges printed or
not, amount due twice alike and twice different, remittance stub on the page and on its own page, continuation page,
late-payment line, key word in a sentence, wrapped labels, two pages, usage history, dot leaders, files of 1, 2, 3 and 4
bills, one page and two pages per bill, two bills for different accounts with the same dates, and the rate kinds and
holder forms and stubs below). A miss prints seed, index
and layout choices, never fails silently.
- **Rates** (FR-110, D21, D25): the generator prints quantity × rate rows with rates whose value is a whole number of
  cents (`0.12`, `0.1200`, `0.1500`) and rates whose value is not (3 and 4 decimals, including at least one exactly half a
  cent past at each, such as `0.125` and `0.1450`); its printed charge is the product rounded half up. Expected per such
  line: `unit_price_minor` the rate rounded half up to cents; when the value is not whole cents the details'
  `unit_price.text` equals the printed rate text, else (by value, however many zeros are printed) no `unit_price` key; no
  precision issue; the product check holds on the printed rate. The run covers each of these four rate kinds at least once.
- **Holders** (FR-102, FR-110, D22, D24): phone layouts print holder section titles in each phone form FR-102 lists (full,
  parentheses, 7 digits, masked, `ending` / `ending in` / `ends in`) and at least one name-only title, plus a section with no
  holder (credits, taxes or shared fees). Per holder section the stub, drawn from the case's choice, gives (i) the holder on
  the first row only, (ii) **no holder on any row** (required for phone-number titles; a name-only section needs a matching
  model holder on some row, so it uses (i) or (iii)), or (iii) on one row a holder that disagrees with the title (another
  section's number). Expected: every charge row under a holder title has the title's holder (as printed, whitespace
  collapsed, at most 80 characters) as `line_holder` with the title line in its evidence; for (iii) exactly the note
  "Line N: the holder X differs from its section title; the title's holder Y was used." for that row, with N its position
  (the generator keeps model order equal to position, G13), and no review reason; rows outside a holder section have none.
  The run covers each phone form, the name-only title and each of (i) – (iii) at least once.
Evidence: `pytest tests/test_bill_engine_generator.py`.

## SC-124 — evals
Requirement IDs: FR-124
Uses `tests/test_evals.py`'s pattern (`evals.run.run` on a synthetic corpus with `local_model`).
- `python -m evals.synthetic <tmp>` writes 58 cases: the existing 53 with the same ids and answers, then five bill files
  (utility with Usage / Rate / Charge and a summary box; phone with holder sections, subtotals and a credit; rent with
  line periods, previous balance and payments; two-page headless bill with a remittance stub on its own page; BL-MULTI),
  each `native_pdf`, answers from their generator inputs; BL-MULTI's answer has 3 bills.
- `summary.json` `bill_readers` has exactly `engine`, with `documents`, `lines`, `exact`, `left_out`, `checkable`,
  `checks_held`, `to_review`, `unplaced`, `failed`, `files_split`, `split_right`, `split_review` and shares; on the five
  files: every line exact, `failed` 0, `files_split` 1, `split_right` 1, `split_review` 0; `guesses` by kind with
  made == right; image bills are not counted in `bill_readers`.
- `summary.json` passes the allowlist (`evals/report.py`) and holds no description, amount or date.
Evidence: `pytest tests/test_evals.py -k bill`.

## SC-125 — the `bill` diagnose mode
Requirement IDs: FR-127
Initial state: BL-MULTI and BL-UTIL written to `tmp_path` as PDFs.
Actions/checkpoints: run `python scripts/statement_diagnose.py <file> bill` as a subprocess (no model configured) ->
exit 0; BL-MULTI output contains `3 bills: pages 1, 2, 3`, per page the key kinds present with "equal"/"differs" and the
count of charge tables, rows, totals, section titles, wrapped labels, anchors by kind, other tables and unplaced lines,
each column's edges and zone as a percentage, role and how decided; BL-UTIL output contains `1 bill` and roles quantity,
rate, charge decided by the product rule; neither output contains any of: `CITY`, `POWER`, `WATER`, `Energy`, `Tier`,
`Customer`, `Electric`, `State Tax`, `kWh`, `Usage History`, any fixture amount as printed (`97.55`, `82.10`, `60.00`,
`20.02`, `12.00`, `5.53`, `0.1200`, `0.1430`, `81.42`, `87.26`, `74.72`, `111.98`, `64.80`, `70.20`, `58.50`, `4.62`,
`5.06`, `4.22`, `80.00`, `50.00`) or in minor units, any fixture date in `MM/DD/YYYY` or ISO form, or `1234`, `5678`,
`9012`; the temporary folder it reported is gone afterwards; no `local_model` request.
Evidence: `pytest tests/test_bill_engine_generator.py -k diagnose`.

## SC-126 — finding the bills in a file
Requirement IDs: FR-128
Actions/checkpoints (each a fresh library, stubs one answer per part):
1. BL-MULTI -> C-segments(3); due dates 2026-07-20, 2026-08-20, 2026-09-20; EXP-MINI(1 – 3).
2. BL-REMIT -> one bill, EXP-UTIL; C-segments(1); no split note.
3. BL-ACCT -> C-segments(2); account last four 9012 and 3456; bill 1 EXP-MINI(1), bill 2 as BL-ACCT expected.
4. BL-UTIL -> one bill, C-segments(1).
5. MULTI-SCAN and MULTI-IMAGES -> C-segments(3) each, the same due dates; values from the model stubs (EXP-MINI(k) answered
   right and supported in their cited lines); no engine rows (the lines' evidence cites transcription lines, no engine
   cell); FR-110 notes absent.
6. MINI-PNG -> one bill; C-segments(1).
7. Key lines (unit tests on the split rule with hand-built lines): `Account #: ****9012` and `Account Number 1234-5678-9012`
   are equal accounts; `Payment Due ........ 10/15/2026` is a due-date key; `Your previous bill, due 09/15/2026, is past
   due`, `Late fee if not paid by 10/15/2026`, `Previous Statement Date 08/20/2026`, `Rent and Leasing Charges Due
   10/01/2026` are no key lines; a page whose only differing value is its `Billing Period` continues the open bill; a part
   with no amount-due anchor (a late-payment line only) joins the part before; the first part without one joins the next;
   201 one-page bills -> FR-129 (d) (SC-127).
Evidence: `pytest tests/test_bill_split.py -k sc126`.

## SC-127 — uncertain boundaries go to review
Requirement IDs: FR-129
Actions/checkpoints:
1. BL-JOIN -> C-segments(2). Bill 1 (pages 1 – 2): C-reason(`Page 2 prints its own due date (08/20/2026) but no amount
   due, so it was read with the bill before it; check how the file was split.`); new charges 8142 (first on page 1) with
   a C-note naming 87.26; previous balance 8000 and payments 8000 with C-notes naming 81.42; lines `(1200, 6480, 462, 1200,
   7020, 506)` = 16868; C-reason(`New charges: the lines add up to 168.68 USD`, `81.42 USD`); amount due 8142 (carried
   check: 80.00 − 80.00 + 81.42 holds). Bill 2 (page 3): EXP-MINI(3) with C-note(`Split from a file holding several
   bills`); C-auto.
2. BL-TWOONPAGE -> C-segments(1); one bill; exactly one C-reason(`Page 1 prints more than one due date (07/20/2026,
   08/20/2026), so it may hold more than one bill; check it and split it on the document's page.`) (one reason for the bill
   although its statement dates differ too, see G5); C-reason(`New charges: the lines add up to 168.68 USD`, `81.42
   USD`); amount due 8142 (the carried check picks 81.42 over 87.26, no guess note).
3. BL-NOKEY -> C-segments(1); C-reason(`This bill prints new charges of 81.42 and 87.26 on different pages, so the file may
   hold more than one bill; check it and split it on the document's page.`); C-reason(`New charges: the lines add up to
   168.68 USD`, `81.42 USD`) (derived from FR-111 and FR-113; the spec's SC-127 row lists only (c), see G6); amount due
   8142.
4. BL-MULTI with the split-rule fault -> one bill; C-reason(`Where each bill starts couldn't be read, so the file was read
   as one; check whether it holds more than one bill.`); one `log_failure` record naming `RuntimeError`, no record
   containing `CITY` or `81.42`. With the 201-part double -> the same reason, one bill.
5. A split you made or confirmed raises none: after SC-129's Confirm split on BL-JOIN, reason (b) is gone and bill 1 keeps
   only its lines reason.
Evidence: `-k sc127`.

## SC-128 — one record per bill, and the library
Requirement IDs: FR-130, FR-135
Initial state: empty ledger; BL-MULTI.
Actions/checkpoints:
1. Extract -> three `receipts` rows, segments 0, 1, 2: lines (1200, 6480, 462), (1200, 7020, 506), (1200, 5850, 422);
   `total_minor` 8142, 8726, 7472; `amount_due_minor` 8142, 8726, 11198; details previous 8000 / 8142 / 8726, payments
   8000 / 8142 / 5000; both checks hold on each; each `verified`; C-note split note on each; C-model-calls (one
   Classification per part before any part is read).
2. Spending (`FinanceTools` category spending, as `tests/test_bill_kinds.py` uses) for 2026-07-01 – 2026-09-30 -> 8142 on
   2026-07-20, 8726 on 2026-08-20, 7472 on 2026-09-20; total 24340.
3. `GET /api/documents/{id}` -> `ledger_amount_minor` null, `ledger_currency` null, `document_date` `2026-07-20`, `merchant`
   `CITY POWER & WATER`, `due_date` `2026-07-20`, period 2026-06-01 – 2026-06-30 (the first non-rejected bill by segment);
   filed under CITY POWER & WATER and 2026-07-20. After the user rejects bill 1: `document_date` `2026-08-20`, due date and
   period bill 2's, still no single amount. After the user also rejects bill 2 (one non-rejected bill left):
   `ledger_amount_minor` 7472, `ledger_currency` `USD`, due date `2026-09-20` (as today for one bill).
4. Payment match: a checking account with `2026-07-18 CITY POWER & WATER -81.42`; `Reconciler(store).run()` ->
   `transaction_receipt_links` proposes the transaction for bill 1 only (`bill_links` of bills 2 and 3 empty).
5. Kind per part: a variant whose part 2 is classified `rent` -> part 2 read with the rent form, parts 1 and 3 general.
6. Not a bill: part 2 classified `receipt` -> one document, C-note(`A part of this file is not a bill, so the file was read
   as one document.`); C-segments(1).
7. BL-MULTI-INV -> one bill (segment 0), C-segments(1), read on today's path (invoice: the `anchor_rows` path, no engine
   rows), C-note(`A part of this file is an invoice, so the file was read as one document.`).
8. A split cutting a table: `PUT …/segments` with a start inside page 1's charge rows (at `Energy Charge`) -> the part
   before holds Customer Charge only, the part after Energy Charge and State Tax; every line in exactly one segment.
Evidence: `-k sc128`.

## SC-129 — no review for a certain split; the user can change it
Requirement IDs: FR-131
Initial state: SC-126 (1) BL-MULTI; separately SC-127 BL-TWOONPAGE.
Actions/checkpoints:
1. After Extract -> each of 3 bills carries C-note(`Split from a file holding several bills`); each C-auto;
   `GET /api/documents/{id}/segments` -> 3 segments, `confirmed` false, each with kind `bill` and its provider, due date and
   amount due (key names the plan's).
2. Browser (opt-in): the panel heading `This file holds 3 bills`; chips `CITY POWER & WATER` · due date · amount due
   (`81.42`, `87.26`, `111.98`); **Confirm split**, **Merge with next**, **Split here**; no "waits in To check" warning.
3. `PUT /api/documents/{id}/segments` with starts of bills 1 and 2 only (Merge with next on bill 2) -> 202; the file is read
   again: C-segments(2); bill 1 EXP-MINI(1) values; the old segment-2 bill is rejected automatically (SC-130);
   each bill has C-note(`You changed where the bills in this file start; the file was read with your split.`) and a
   `split_changed` guess.
4. Extract again -> still 2 segments (the user's split wins).
5. `POST /api/documents/{id}/segments/confirm` -> `confirmed` true; the split note is gone from both bills; each re-judged by
   its own checks (the merged bill keeps any lines reason, see G9).
6. BL-TWOONPAGE: the panel offers **Split here** although the file is one bill (API: `GET …/segments` gives what the page
   needs to offer it; the plan names it). `PUT …/segments` with MINI-BILL(2)'s first line (`CITY POWER & WATER` at y 500)
   as a second start -> C-segments(2); EXP-MINI(1) and EXP-MINI(2) values; reason (a) gone; both `verified`.
Evidence: `-k sc129`; `tests/test_bill_engine_browser.py -k sc129`.

## SC-130 — reading again and retired bills
Requirement IDs: FR-132
Initial state: SC-126 (1) BL-MULTI.
Actions/checkpoints:
1. Extract again twice (forced runs) -> the same 3 ids, segments, lines, notes and split each time.
2. Merge with next on bill 2 and Extract again -> the segment-2 bill is `rejected`, `review_source` `automatic`, with the
   issue `The latest reading of this file no longer finds this bill; check how the file was split.`; spending no longer
   counts it.
3. Second library: bill 3 verified by the user first, then the same merge -> bill 3 stays `verified`, `review_source`
   `user`, with the same note added.
4. Splitting back (bills 1, 2, 3 starts again) -> the automatically rejected bill is restored (found again), not a new id.
Evidence: `-k sc130`.

## SC-131 — VOID and duplicate bills
Requirement IDs: FR-133, FR-134
Actions/checkpoints:
1. (a) BL-MULTI-VOID -> 3 bills; bill 2 `rejected` automatically with C-note-or-issue `This bill is printed VOID, so it
   doesn't count.`; spending 8142 + 7472 = 15614. BL-MULTI-VOIDWORD -> 3 bills, none void, spending 24340. A void bill the
   user verified beforehand stays verified.
2. (b) BL-MULTI recorded; then MINI-2-ALONE captured and extracted -> its bill is recorded with its lines, `rejected`
   automatically, noted `This bill repeats the one from CITY POWER & WATER due 2026-08-20 (87.26), so it doesn't count.`;
   spending for August counts 8726 once. The user rejects BL-MULTI's bill 2; Extract again on MINI-2-ALONE -> it counts
   (8726 once), its duplicate note gone.
3. Corrected bill: MINI-2-ALONE with `Total Amount Due` and stub `Amount Due` printed 90.26 (a later corrected bill) after
   BL-MULTI -> both count; the later one has the note `Another bill from CITY POWER & WATER has the same due date.`
   (it reads into review by its own carried check: 81.42 − 81.42 + 87.26 ≠ 90.26).
4. (c) BL-ACCT -> both count; no duplicate or same-due-date note.
5. Invoices are never duplicates: two invoice files with the same provider, due date and total both count.
Evidence: `-k sc131`.

## Failure, retry and duplicate variants (across scenarios)
- **Retry after a failed run.** BL-MULTI with the `BillSummary` stub failing for part 2 on the first run (a model error) ->
  the run fails and publishes nothing (no `receipts` row, no `document_segments` row); Extract again with working stubs ->
  exactly SC-128 step 1's end state, no duplicate segment.
- **Duplicate capture.** BL-MULTI dropped into the Inbox twice -> one file (duplicate link, as today) and 3 bills.
- **Restart.** Extraction stopped after reading and before publishing (as
  `tests/test_paystub_split.py::test_a_run_stopped_after_reading_and_before_publishing_is_recovered_and_read_again`) -> on
  restart the end state equals SC-128 step 1.
- **Concurrent Extract.** Two Extract requests for BL-MULTI in a row -> one run (the existing queue's dedupe), 3 bills.

## Traceability
| FR | Scenarios | Test file / command |
|---|---|---|
| FR-100 | SC-100 | `tests/test_bill_engine.py`, `tests/test_bill_engine_record.py` |
| FR-101 | SC-101 | same |
| FR-102 | SC-102 (incl. step 9's holder-title parsing), SC-123 | same; `tests/test_bill_engine_generator.py` |
| FR-103 | SC-103 | same |
| FR-104 | SC-104 | same |
| FR-105 | SC-105 | same |
| FR-106 | SC-106 | same |
| FR-110 | SC-110 (incl. D25 by value), SC-102 (holder, variants b – e), SC-112 (holder), SC-119 A (holder), SC-123 (rates, holders) | `tests/test_bill_engine_record.py`, `tests/test_bill_corrections.py`, `tests/test_bill_engine_generator.py`; `tests/test_bill_engine_browser.py -k sc110` |
| FR-111 | SC-111 | same; `tests/test_bill_engine_browser.py` |
| FR-112 | SC-112 | same |
| FR-113 | SC-113, SC-110 (product on the printed rate) | same |
| FR-114 | SC-114 | same |
| FR-115 | SC-115 | same |
| FR-116 | SC-116 | same |
| FR-117 | SC-117 | same |
| FR-118 | SC-118 | same |
| FR-119 | SC-119 | `tests/test_bill_corrections.py` |
| FR-120, FR-125 | SC-120 | existing suites |
| FR-121 | SC-121, SC-119 | `tests/test_bill_engine_record.py`, `tests/test_bill_corrections.py` |
| FR-122 | SC-122, SC-119 step 5, SC-130 | `tests/test_bill_engine_record.py`, `tests/test_bill_split.py` |
| FR-123 | SC-123 | `tests/test_bill_engine_generator.py` |
| FR-124 | SC-124, SC-105, SC-117, SC-129 | `tests/test_evals.py -k bill` and the record tests' guess lists |
| FR-126 | — | doc diff at review (not a test); SC-103 step 4 checks the anchor list is documented |
| FR-127 | SC-125 | `tests/test_bill_engine_generator.py -k diagnose` |
| FR-128 | SC-126 | `tests/test_bill_split.py` |
| FR-129 | SC-127 | same |
| FR-130 | SC-128 | same |
| FR-131 | SC-129 | same; browser |
| FR-132 | SC-130 | same |
| FR-133, FR-134 | SC-131 | same |
| FR-135 | SC-128 | same |

## Gaps (the spec leaves these open; not invented here)
- **G1 Where a 4-decimal rate is stored. Resolved by D21:** kept as printed text in the line's details and in
  `unit_price_minor` rounded half up; asserted by C-rate, SC-110 steps 1, 5 – 7 and SC-123.
- **G2 A holder printed only in its section title. Resolved by D22:** it counts as printed; asserted by
  EXP-PHONE-HOLDERS, SC-102 steps 3 – 4, SC-112, SC-119 A and SC-123.
- **Rate precision wording (round 2). Resolved by D25:** judged by value; asserted by C-rate, SC-110 step 6 (UTIL-15,
  UTIL-125, the unit list) and SC-123.

G3 – G8 are left to the plan (spec D23): the plan chooses and records each. Until then the contract asserts only what it
states below for each; the plan's choice may add an assertion but changes no expected value written here.
- **G3 The worked-out new charges' lines reason prefix.** FR-118 says "today's lines reason"; today has two
  ("New charges: the lines add up to …" and "Amount due: the lines add up to …"). SC-118 R2-BAD asserts the shared facts
  only.
- **G4 Pre-change correction on a line whose price was also corrected.** FR-119 compares a pre-change correction with "the
  amount its line had in the bill's last reading", but also says "its amount as read, before any price correction of
  yours". For a `member:n` made before this change on a line that also has a `price:n` correction, the stored amount is
  the corrected one; which amount is meant is open. The contract's variants avoid that case.
- **G5 Which key reason (a) names when several keys differ on one page.** BL-TWOONPAGE's statement dates differ too;
  FR-129 gives the due-date wording and "one review reason". The contract asserts exactly one (a) reason naming the due
  dates.
- **G6 BL-NOKEY's stub due date, and its lines reason.** The fixture says "no account, statement date or due date line";
  the contract removes the stub's `Due Date` too (otherwise the page would split by key). The spec's SC-127 row lists only
  reason (c), but FR-111 / FR-113 give the bill a lines reason as well (168.68 against 81.42); the contract expects both.
- **G7 "Whole words" for anchors inside a sentence.** FR-103 makes anchors words "wherever printed" but FR-128 excludes a
  key word inside a sentence for keys only. Whether `Your previous balance was paid in full 82.10` is an anchor is open;
  SC-103 doesn't assert it, and the generator's "key word inside a sentence" variation is checked for keys only.
- **G8 A note for an unsigned credit the model called a charge.** FR-106 gives the note only for a row "printed as money
  off"; for an unsigned row under a credits section the model answered `service`, whether a note is added is open.
G9 – G11 stand as stated (spec D23).
- **G9 Values of a merged bill.** As phase 2 G3: a bill merged from two prints two amounts due; SC-129 asserts the count and
  that the user's split wins, not the merged bill's values.
- **G10 Library dates when bill 1 is rejected.** FR-135 gives the date as "the earliest non-rejected bill's due date" and
  the shown due date/period "the first non-rejected bill's by segment"; the contract asserts these as stated (SC-128 step 3).
- **G11 Note wording.** Exact wording is given for the FR-114, FR-115, FR-117, FR-118, FR-119, FR-129 – FR-134 texts and the
  split notes; other notes (unplaced, unclassified, subtotal mismatch, repeats, money-off) are checked by the facts they
  must name.
- **G12 A holder section where the model gives no row a holder. Resolved by D24, FR-102 and FR-110:** the section title
  alone gives the holder; a disagreeing model holder gives way to the title with the exact note; a name-only title counts
  only when a model holder of the section has a word in it. Asserted by SC-102 steps 3 and 5 – 9, SC-112, SC-119 A and
  SC-123.
- **G13 What "Line N" counts in the holder note** (new, round 3). FR-110's note "Line N: the holder X differs …" doesn't
  say whether N is the line's position on the bill (`receipt_items.position`, as FR-119's `line 2`) or the model line's
  index; SC-102 (c)'s "Line 3" fits both (Basic Plan is third either way). The contract asserts N only where the two agree
  (SC-102 steps 6 and 9, the generator keeping model order equal to position) and asserts no N where a model line is
  missing or repeated before the disagreeing row.
- **G14 Year ranges and account-like numbers in a section title** (new, round 3). FR-102 (a)'s phone form ("digits in
  groups separated by spaces, `-`, `.` or parentheses ending in a group of exactly four digits, at least 7 digits in all")
  read literally also matches `Charges 2025-2026` or `2025 - 2026` (8 digits, last group four) and `Account 1234-5678-9012`;
  only "a bare 4-digit number such as a year" is excluded. Whether such a title is a holder title is open; the contract
  asserts only the single-year case (`Charges 2026`, not a holder title) and no fixture prints a year range or an account
  number as a section title.
