# Receipt items: tax shared by its printed tax code
Feature: receipt-tax-codes

<!-- Approval state lives in approvals/<slug>.json and is bound to this file's content hash.
     Do not add a Status line: changing it would change the hash. Check with gate.py. -->

Amends: `specs/receipt-item-table` (the item table this builds on, built first). No earlier spec covers how tax is
shared. The baseline is the built behavior in `docs/money.md` "Item categories and splits" and the code cited below.

Split (user, 2026-11-01): the item-table half of the joint spec moved to `specs/receipt-item-table` (FR-01 – FR-07,
FR-25, the table half of FR-20, SC-02, SC-11, SC-12, the Printed-details half of SC-17). Requirement and scenario IDs
are kept, so the IDs here are not contiguous. SC-19 is new and holds the tax-code parts of the old SC-02 and SC-17.

## Decisions already made (user, 2026-10-26; not to be re-asked)
- **D1 Both columns.** The item table shows a **Line total** (quantity × unit price as printed, before tax) and a
  **Paid** column (the item's share of what was paid, with its part of tax and discounts).
- **D2 Two specs** (user, 2026-11-01; supersedes "One spec"). The item table (`receipt-item-table`) and tax by
  printed tax code (this spec) are specified, planned and approved separately. The item table is built first. Nothing
  is built before approval.
- **D3 Open decisions settled** (user, 2026-10-26). OD-4 and OD-5 take their recommended defaults ("defaults ok").
  (OD-1 – OD-3 moved to `receipt-item-table`.) Risks R1, R2, R3 and R5 become FR-21 – FR-24. R4's default is no
  change, so it needs no requirement.
- **D4 Test-contract gaps settled** (user, 2026-10-26). G1 and G3 take their recommended defaults ("defaults ok") and
  become FR-27 and FR-29. G2: correcting Tax never changes the saved total (FR-28).

Background (user report, 2026-10-26). A grocery receipt printed:

```
GROCERY
071057174 RUFFLES BF $4.29
211180042 LITLE VEGET BF $41.90
10 @ $4.19 ea
KITCHEN
07200120 WATER FILTER T $12.99
Regular Price $15.99
SUBTOTAL $59.18
T = GA TAX 7.75000 on $12.99 $1.01
B = GA TAX 7.75000 on $46.19 $1.73
```

All $2.74 of tax went to the water filter. (The "—" under Paid for the two grocery items is fixed by
`receipt-item-table`.) The right split is B's $1.73 across Ruffles and Little Veg and T's $1.01 on the filter: Ruffles $4.45,
Little Veg $43.47, Water filter $14.00 (total $61.92).

## Goal / users / scope / non-goals
**Goal.** When a receipt prints tax per tax code, each code's tax goes only to the items carrying that code, and the
page shows which code's tax each item carries.

**Users.** The household user reading a receipt on its document page, and every total that counts by item category
(Transactions Items, category totals, budgets, the Home donut, forecast, family shares).

**In scope.** Reading each item's printed tax code and the receipt's per-code tax lines (FR-08 – FR-11). Keeping them
(FR-12 – FR-13). Sharing tax by code (FR-14 – FR-18). Showing the tax lines in the item table's footer (FR-19). Docs
(FR-20). Uncoded tax lines, legends, repeated codes and food-stamp marks (FR-21 – FR-24). The tax-code note (FR-26).
Fallback flags, tax corrections and partly answered flags (FR-27 – FR-29).

**Non-goals.**
- The item table's columns, Qty, Unit price, the "—" rule under Paid and Printed details (`receipt-item-table`).
- Bills (`document_kind` bill) keep their own line table (`receipt.js` `billLines`).
- Statement transaction rows keep their columns.
- Working out tax rates or which goods are taxable. Only printed codes and printed tax amounts are used, never tax law.
- Recovering tax codes for receipts already recorded without a fresh reading (Extract again does that).
- Correcting a single tax line by hand (see OD-4).

## Existing behavior (verified)
- **The item table** is `src/home_manager/app/static/receipt.js:294` `ledgerRows`, used by the document page
  (`document_v2.js:436`). Its columns, footer and Paid note after `receipt-item-table` are that spec's FR-01 – FR-07.
- **Tax codes are a yes/no flag.** The model returns `taxed: bool | None` per item (`extraction.py:297`), prompted to
  read codes such as "A or E, T or N, X, F" (`:2909`). It is stored in `receipt_items.taxed` (migration 032). The code
  letters themselves are not kept.
- **One tax amount per receipt.** The receipt form has a single `tax` field (`extraction.py:56`), stored as
  `receipts.tax_minor`. Printed per-code tax lines are not read.
- **How tax is shared.** `finance/splits.py:83-85` shares all tax by amount across items marked taxed, or across every
  item when none is marked. Results are stored in `category_splits` and rebuilt when items, categories or links change
  (`ledger.py:983-1016`).
- **Likely cause of the report (assumption, not verified on the user's receipt):** the model read the "F" in "BF" (often
  a food-stamp-eligible mark) as untaxed and "T" as taxed, so only the filter was marked taxed.
- **Re-extraction** matches new rows to earlier items and keeps the user's categories and people (`ledger.py:880-922`).
- **Unknown:** how other chains print per-code tax lines (one line per code is assumed; see R2).

## Functional requirements
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-08 | When reading a receipt, each item's printed tax code is read exactly as printed beside its price ("BF", "T", "A", "N"), or empty when none is printed. The item cites the line it's on. | A stubbed reading of the report's receipt stores "BF", "BF" and "T". |
| FR-09 | Each printed per-code tax line is read with its code ("T"), its printed rate (7.75000) when there is one, its printed taxable amount ($12.99) when there is one, and its tax amount ($1.01). Each cites its line. A receipt that prints only one TAX line has no per-code tax lines. | The report's receipt stores two tax lines: T 7.75 on $12.99 $1.01, and B 7.75 on $46.19 $1.73, each with a working Find. |
| FR-10 | An item belongs to a tax line when its printed tax code contains that line's code, and contains no other tax line's code. The other letters ("F" in "BF") are kept but don't count. | "BF" belongs to B. "T" belongs to T. "N" belongs to no tax line. |
| FR-11 | When per-code tax lines exist, an item's taxed flag comes from them: taxed when it belongs to a tax line with a tax amount above zero, untaxed when it belongs to none. The model's own yes/no answer is ignored for that receipt. Without tax lines, the model's taxed answer is used as today. | In the report's receipt all three items are taxed whatever the model answered for "BF". |
| FR-12 | Items' tax codes and the receipt's tax lines are kept with the receipt, survive a restart, and are replaced by a new reading (Extract again) like other read fields. User-set categories and people still outlive the reading. | After Extract again with a different stub, the new codes and lines replace the old; a category the user chose stays. |
| FR-13 | Receipts recorded before this change keep their stored taxed flags, tax and splits unchanged until they are read again. | After the upgrade, every existing receipt's `category_splits` rows are identical to before. |
| FR-14 | When the receipt's per-code tax lines are consistent (FR-16), each tax line's amount is shared by amount only across the items belonging to it. Items belonging to no tax line get none of it. | The report's receipt: Ruffles $4.45, Little Veg $43.47, Water filter $14.00; categories add up to $61.92. |
| FR-15 | Sharing by code keeps every other rule in `docs/money.md` "How the money is shared out": discounts first, tip as dining, the charge difference, exact fractions, largest-remainder rounding, and the sum equal to the amount paid. A tax line's amount is shared over the items' amounts after any order-wide discount, as tax is today. | Per-category shares always add up exactly to the charge, including foreign-currency charges, gift-card receipts and shared receipts. |
| FR-16 | The tax lines are used only if their tax amounts add up exactly to the receipt's tax and every tax line with an amount has at least one item belonging to it. Otherwise tax is shared as today (FR-11's fallback: the taxed flags, else every item), and the receipt shows an issue naming the reason. | Tax lines $1.01 + $1.73 with receipt tax $2.84 share as today and show "The tax lines ($2.74) don't add up to the tax ($2.84), so tax was shared across the taxed items." |
| FR-17 | When the user corrects the receipt's Tax so the lines no longer add up to it, the receipt falls back as in FR-16, and the splits are rebuilt. | Correct Tax to $3.00 on the report's receipt: the splits rebuild without tax lines and the issue appears. |
| FR-18 | An item whose tax code contains two tax lines' codes (FR-10), or whose code matches no tax line on a receipt with tax lines, gets no share of any tax line and is named in an issue. When that leaves a tax line with no items, FR-16's fallback applies. | Code "BT" on a receipt printing B and T lines: the item is named in an issue. |
| FR-19 | When tax lines are used, the item table's footer (`receipt-item-table` FR-07) shows each one under Tax, with its code, printed rate and taxable amount, its amount, and a Find button for its line. Otherwise the footer shows the one Tax line as today. | Under Tax the footer shows "B · 7.75% on $46.19 · $1.73" and "T · 7.75% on $12.99 · $1.01". |
| FR-20 | `docs/money.md` "Item categories and splits" describes tax codes and tax lines, the code rule and the fallback. A worked example uses the report's receipt (synthetic). Correcting a single tax line is listed in `docs/open-work.md` (OD-4). | The doc section matches the built behavior; open-work has the tax-line correction entry. |
| FR-21 | (R1) Tax lines printed without a code ("STATE TAX $1.20", "LOCAL TAX $0.40") are not per-code tax lines. Tax is shared as one total, as today. | Stub with two uncoded tax lines: no tax lines are stored for sharing, and splits match today's rule. |
| FR-22 | (R2) A printed code legend with no per-code amounts ("T = TAXABLE", "N = NON-TAXABLE", one TAX line) sets each item's taxed flag from the legend (taxed or untaxed). The single tax amount is then shared across the taxed items as today. | Legend stub: T items taxed, N items untaxed, whatever the model answered; one tax amount shared over the T items. |
| FR-23 | (R3) Two tax lines with the same code (state and local, both "B") are added together for that code. Each stays shown and cited in the footer. | Stub with B $1.00 and B $0.73: B's items share $1.73; the footer shows both lines. |
| FR-24 | (R5) The reading treats a printed mark as untaxed only when the receipt says what it means (a legend, or a code with no tax line on a receipt with tax lines). A food-stamp or EBT mark (F, E) is not taken as untaxed on its own. Otherwise taxed is empty, so tax is shared across every item. | Prompt states this rule; with a stub returning taxed empty for "BF" items on a one-TAX-line receipt, tax is shared across all items. An eval case covers the live reading (user-run). |
| FR-26 | (OD-5) A taxed item's Paid note (`receipt-item-table` FR-05) names its tax code when tax lines are used ("with B tax"). The item's full printed code (BF) shows as the row's tooltip. No column is added. | Ruffles' Paid reads $4.45 "with B tax"; hovering its row shows "Tax code BF". |
| FR-27 | (G1) When a receipt has tax lines but falls back (FR-16, FR-17, FR-18), the taxed flags used are FR-11's, derived from the tax lines. The model's own yes/no answers are not used. | SC-04: with the model answering BF untaxed, the fallback still shares tax over all three items, not only the filter. |
| FR-28 | (G2) Correcting a receipt's Tax changes only its tax. The saved total, subtotal and tip stay as they were. The splits are rebuilt against the unchanged total. | SC-07: after Correct Tax to $3.00 the saved total is still $61.92. |
| FR-29 | (G3) On a receipt with no per-code tax lines and no code legend, when any item's taxed answer is empty, tax is shared across every item, whatever the other items' answers. | One TAX line; the T item answered taxed, the BF items empty: tax is shared over all three items. |

## Invariants, privacy, security and data retention
- Per-category shares of a receipt or charge always add up exactly to its amount (`splits.py` invariant).
- Money comes from the server. The page shows stored shares and never calculates Paid or tax itself.
- Each tax line, like every read field, cites its source line ("source beside the record", `docs/ui.md` "Screen rules").
- Nothing leaves the machine. Readings use the configured local model, as today.
- Tests use synthetic receipts only. Nothing under P:\Finances or P:\EvalCorpus is read.
- The upgrade adds stored fields but doesn't rewrite existing receipts' amounts or splits (FR-13). Migrations follow
  the safe-migration rules already in the repo.

## Errors, recovery, duplicates, restart behavior
- A tax line whose amount can't be read is kept with no amount. It counts as not adding up (FR-16).
- A tax line that prints the same code twice: their amounts are added for that code (see R3).
- A reading that fails leaves the receipt's earlier codes, tax lines and splits as they were.
- Splits are rebuilt whenever codes, tax lines, tax, items or links change, as today. A restart changes nothing.
- Reading the same receipt twice gives the same tax lines; no duplicates pile up.

## Nondeterministic outputs and how they are verified
- The model's reading (codes, tax lines) is tested with fixed stub responses for the report's receipt and the failure
  cases. No exact output from a live model is expected.
- An optional live check on the agent test instance, with a synthetic receipt like the report's: both tax lines are
  read with codes and amounts, and items get "BF"/"T" codes. Only presence and amounts within one cent are checked. The
  user runs this themselves.
- Shares are deterministic given stored values and are checked exactly.

## Scenarios
| ID | FR IDs | Initial state | User/API actions | Expected final DB/files/UI state |
|---|---|---|---|---|
| SC-01 | FR-08–FR-12, FR-14, FR-15 | Empty synthetic library; stub returns the report's receipt with items BF, BF, T and tax lines T $1.01 on $12.99, B $1.73 on $46.19; tax $2.74, total $61.92 | Record the receipt | Items keep codes BF, BF, T; two tax lines with citations; all items taxed; splits: Ruffles 445, Little Veg 4347, Filter 1400 (sum 6192) |
| SC-03 | FR-11 | Stub: a receipt with one TAX line, items marked taxed / untaxed (the docs' hot dog / mattress / groceries) | Record | No tax lines stored; splits as today (Dining $1.62, Furniture $539.99, Groceries $80.00) |
| SC-04 | FR-16 | Stub: tax lines $1.01 + $1.73, receipt tax $2.84 | Record | Tax shared by taxed flag (else all items); issue names the $2.74 vs $2.84 gap; categories sum to the total |
| SC-05 | FR-16, FR-18 | Stub: tax lines B and T; no item carries T | Record | Fallback as SC-04; issue says the T line has no items |
| SC-06 | FR-18 | Stub: one item coded "BT" | Record | That item gets no tax line share and is named in an issue; FR-16 fallback if a line is left with no items |
| SC-07 | FR-17 | SC-01 recorded | Correct Tax to $3.00 | Splits rebuilt by the fallback; issue shown; Correct Tax back to $2.74 rebuilds by code again |
| SC-08 | FR-12 | SC-01 recorded; user sets Water filter's category to Household supplies | Extract again with a stub that reads the filter as N (no tax lines) | New reading's codes replace the old; tax lines gone; filter keeps Household supplies; splits rebuilt by the taxed flags |
| SC-09 | FR-13 | Library with receipts recorded before the change (taxed flags, splits) | Apply the upgrade; restart | Every `category_splits` row and `receipt_items.taxed` value is unchanged; no item tax codes or tax lines |
| SC-10 | FR-15 | SC-01 receipt matched to a card charge of $61.92, and separately shared 50/50 with a family member | Rebuild splits | Charge split equals SC-01's; each person's part sums to their share; foreign-currency charge resized with sums exact |
| SC-13 | FR-21 | Stub: STATE TAX $1.20 and LOCAL TAX $0.40, no codes, receipt tax $1.60 | Record | No per-code sharing; splits as today's rule |
| SC-14 | FR-22 | Stub: legend T = TAXABLE, N = NON-TAXABLE; one TAX line; model's taxed answers contradict the legend | Record | Taxed flags follow the legend; tax shared over the T items |
| SC-15 | FR-23 | Stub: B $1.00 and B $0.73 lines, T $1.01; receipt tax $2.74 | Record; open the page | B items share $1.73; footer shows three tax lines, each with Find |
| SC-16 | FR-24 | Stub: one TAX line; "BF" items returned with taxed empty | Record | Tax shared across every item |
| SC-19 | FR-19, FR-26 | SC-01 recorded | Open the receipt's document page | Paid: Ruffles $4.45 "with B tax", Little Veg $43.47 "with B tax", filter $14.00 "with T tax"; Ruffles' row tooltip "Tax code BF"; footer lists the B and T tax lines with Find; Correct on Tax still opens |
| SC-18 | FR-29 | Stub: one TAX line $2.74; water filter answered taxed true, BF items taxed empty | Record | Tax shared across all three items: 449, 4384, 1359 |

The test contract (`test-contract.md`) covers SC-01, SC-07, SC-08 and SC-10, which are stateful and change stored
splits.

## Out of scope / product decisions requiring approval
All settled by D3. Kept for the record (OD-1 – OD-3 moved to `receipt-item-table`):
- **OD-4 Correcting tax lines.** Default: not in this change. The user corrects the total Tax (FR-17), and Extract
  again re-reads the lines. Tax-line correction goes into `docs/open-work.md`.
- **OD-5 Where the tax code shows.** Default: on the item, beside Paid's "with tax" note ("with B tax"), and the full
  printed code (BF) in the row's title, without adding a column.

Domain risk pass. R1, R2, R3 and R5 were accepted as FR-21 – FR-24. R4 was accepted as no change:
- **R1 Tax lines printed without codes** ("STATE TAX $1.20", "LOCAL TAX $0.40"). Consequence: lines with no code
  can't be matched to items. Default: treat them as one tax total, as today (no per-code sharing).
- **R2 Codes defined in a legend apart from the tax lines** ("T = TAXABLE", "N = NON-TAXABLE" at the bottom, one TAX
  line). Consequence: codes are known but no per-code amounts. Default: use the legend only to set taxed flags (taxed
  / untaxed), sharing the single tax amount as today. Needs a test with a synthetic legend receipt.
- **R3 Two rates on one code** (state + local printed as two lines, both "B"). Consequence: double counting or a
  missed line. Default: add the amounts for a code (Errors section). Accept as an FR if wanted.
- **R4 Item-level discounts printed under an item** ("Regular Price $15.99" is not a discount; a "SAVINGS -$3.00" line
  is). Consequence: tax basis off from the printed taxable amount. Default: no change. The printed taxable amount is
  shown but not used to adjust shares. A gap between it and the items' total is not flagged (it often differs by the
  discount).
- **R5 Food-stamp or EBT-eligible marks** (F, E) read as tax-exempt again on receipts without tax lines. Consequence:
  the original bug on receipts with one TAX line. Default: reword the prompt so a mark is called untaxed only when the
  receipt says what it means. Otherwise taxed is null, and tax is shared across all items. Needs an eval case.
