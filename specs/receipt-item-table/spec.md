# Receipt items: a fuller item table
Feature: receipt-item-table

<!-- Approval state lives in approvals/<slug>.json and is bound to this file's content hash.
     Do not add a Status line: changing it would change the hash. Check with gate.py. -->

Amends: no earlier spec covers receipt items. The baseline is the built behavior in `docs/money.md` "Item categories
and splits" and the code cited below.

Split from: `specs/receipt-tax-codes` (user, 2026-11-01). This is the first of the two features and is built first.
`receipt-tax-codes` builds on the table defined here. Requirement and scenario IDs are kept from the joint spec, so
the IDs here are not contiguous. FR-30 and SC-20 are new and replace the table halves of FR-20 and SC-03.

## Decisions already made (user; not to be re-asked)
- **D1 Both columns** (2026-10-26). The item table shows a **Line total** (quantity × unit price as printed, before
  tax) and a **Paid** column (the item's share of what was paid, with its part of tax and discounts).
- **D2 Two specs** (2026-11-01). Supersedes the joint spec's "One spec". The item table (this spec) and tax by printed
  tax code (`receipt-tax-codes`) are specified, planned and approved separately. This one is built first. Nothing is
  built before approval.
- **D3 Open decisions settled** (2026-10-26). OD-1: with no quantity printed, Qty shows **1** as a plain value with no
  "not printed" mark. It is display only: the stored quantity stays empty and the extraction rule "never assume a
  quantity of one" is unchanged. OD-2 and OD-3 take their recommended defaults ("defaults ok").

Background (user report, 2026-10-26). On a grocery receipt the two grocery items showed "—" under Paid even though
their prices were read correctly. Quantity and unit price were read but not shown in the item table. (The wrong tax
split in the same report is `receipt-tax-codes`.)

## Goal / users / scope / non-goals
**Goal.** Every receipt item shows what it is, its code, how many, the price of one, its category, its line total and
what it actually cost.

**Users.** The household user reading a receipt on its document page.

**In scope.** The receipt item table on the document page (FR-01 – FR-07). Printed details' count lines (FR-25). Docs
(FR-30).

**Non-goals.**
- Reading tax codes, per-code tax lines, or changing how tax is shared (`receipt-tax-codes`).
- Any change to stored amounts, shares, extraction or the database schema.
- Bills (`document_kind` bill) keep their own line table (`receipt.js` `billLines`).
- Statement transaction rows keep their columns.

## Existing behavior (verified)
- **Table columns.** `src/home_manager/app/static/receipt.js:294` `ledgerRows` shows Item, Code, Price, Category,
  Paid. Code is hidden when no item has a product code (`:304`). Paid is hidden when no item has a share (`:305`).
  Price is `line_total_minor` (`:319`). The document page uses this table (`document_v2.js:436`).
- **The "—" under Paid.** `receipt.js:318` shows "—" whenever an item's share equals its price, and adds "with tax"
  whenever a share is shown (`:326`). An untaxed item, or one wrongly left untaxed, therefore shows "—".
- **Quantity and unit price are already read and stored** (`documents/extraction.py:293-294`, `:1723-1724`;
  `receipt_items.quantity`, `unit_price_minor`, `finance/ledger.py:900`). They only show today on grocery receipts,
  under Printed details (`document_v2.js:612`). A weighed item's weight and price per weight are in `item.details`
  (`document_v2.js:607`).
- **Shares** are stored in `category_splits` and shown as stored; the page never calculates them.

## Functional requirements
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-01 | A receipt's item table has the columns **Item, Code, Qty, Unit price, Category, Line total, Paid**, in that order, then the source button. | The table header on a receipt's document page reads those column titles in order. |
| FR-02 | **Qty** shows the printed quantity (10). A weighed item shows its printed weight and unit (2.31 lb). With neither printed, it shows 1 (D3). | Little Veg shows 10; a weighed banana shows 2.31 lb; Ruffles shows 1. The stored quantity stays empty for Ruffles. |
| FR-03 | **Unit price** shows the printed unit price ($4.19), or a weighed item's printed price per weight ($0.59/lb). With no quantity and no unit price printed, it shows the line total, the price of one. With a printed quantity above one but no unit price, it shows "—" and nothing is calculated. | Little Veg $4.19; Ruffles $4.29; banana $0.59/lb; "3 @" with no unit price printed shows "—". |
| FR-04 | **Line total** shows the item's printed line total, before tax and before any receipt-wide discount, as **Price** does today. | Little Veg $41.90; Water filter $12.99. A returned item's line total stays negative. |
| FR-05 | **Paid** shows the item's share whenever one is stored, even when it equals the line total. "—" appears only when the item has no stored share (no line total, or a receipt with no total). "with tax" appears only when the share includes tax. | An untaxed item at $80.00 shows Paid $80.00 with no "with tax" note. No item that has a share shows "—". |
| FR-06 | **Code** shows the item's printed product code, or "—" when it has none. The column is left out only when no item on the receipt has a product code, as today. | The report's receipt shows 071057174, 211180042 and 07200120. A dining receipt with no codes has no Code column. |
| FR-07 | The footer (Subtotal, Tax, Tip, Not matched, Total) and its Correct buttons stay lined up with the new columns: labels in the first column(s), amounts under Line total. | Correct on Tax still opens the tax correction. The footer amounts sit in the Line total column. |
| FR-25 | (OD-2) A grocery item's count and unit price ("10 × $4.19") and weight ("2.31 lb @ $0.59/lb") no longer appear under Printed details. They show only in the item table. | Printed details on the grocery receipt has no lines for Little Veg or Bananas; tenders and savings still show there. |
| FR-30 | `docs/money.md` "Item categories and splits" describes the item table's columns, the Qty and Unit price rules, and when Paid shows "—" or "with tax". | The doc section matches the built behavior. |

## Invariants, privacy, security and data retention
- Money comes from the server. The page shows stored amounts and shares and never calculates Paid, tax or a unit
  price itself. Qty "1" (FR-02) and Unit price equal to the line total (FR-03) are display rules, not calculations.
- Every row keeps its source button ("source beside the record", `docs/ui.md` "Screen rules").
- No stored value changes. No migration.
- Tests use synthetic receipts only. Nothing under P:\Finances or P:\EvalCorpus is read.

## Errors, recovery, duplicates, restart behavior
- An item with no line total shows "—" under Line total and Paid, as today.
- Nothing is stored by this feature, so restart and retry change nothing.

## Nondeterministic outputs and how they are verified
- Readings are fixed stub responses. The table is deterministic given stored values and is checked exactly.

## Scenarios
| ID | FR IDs | Initial state | User/API actions | Expected final DB/files/UI state |
|---|---|---|---|---|
| SC-02 | FR-01–FR-07 | Stub returns the report's receipt with today's fields only; Ruffles and Little Veg taxed false, filter taxed true; tax $2.74, total $61.92 | Record; open the receipt's document page | Header Item, Code, Qty, Unit price, Category, Line total, Paid; Little Veg 10 · $4.19 · $41.90 · $41.90; Ruffles 1 · $4.29 · $4.29 · $4.29; filter 1 · $12.99 · $12.99 · $15.73 with tax; no "—" in Paid; footer amounts under Line total; Correct on Tax opens |
| SC-11 | FR-02, FR-03, FR-25 | Grocery stub: BANANAS 2.31 lb @ 0.59/lb 1.36; "3 @" item with no unit price | Open the page | Banana Qty 2.31 lb, Unit price $0.59/lb, Line total $1.36; the "3 @" item shows Unit price "—"; Printed details has no count or weight lines |
| SC-12 | FR-04, FR-05 | Return receipt stub with a returned item | Open the page | Line total and Paid negative, as today's Price and share |
| SC-17 | FR-25 | SC-02 recorded | Open the page | Printed details has no Little Veg count line |
| SC-20 | FR-05, FR-06 | Stub: the docs' one-TAX-line receipt (hot dog / mattress / groceries) | Record; open the page | Splits as today (162, 53999, 8000); groceries Paid $80.00 without "with tax"; no Code column; one Tax line in the footer |

## Out of scope / product decisions requiring approval
All settled by D3. Kept for the record:
- **OD-1 Quantity when none is printed.** Settled: show a plain **1**, not stored (D3, FR-02).
- **OD-2 Where Printed details' count lines go.** Default taken: remove the count and weight lines from Printed
  details so they aren't shown twice (FR-25).
- **OD-3 Code column on receipts without product codes.** Default taken: hide it as today (dining receipts).
