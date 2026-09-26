# Item analysis, returns, statement assets and search

Status: implemented 2026-09-25 (migration 024, `item_analysis.py`, `static/search.js`).

Plan and record (2026-09-25) for: category rules after reconciliation, global search, B9 in the
Documents list, H4 item analysis tools with assistant routing, opened/unopened tracking with
return windows, and investment/loan statements as forecast assets. Migration 024.

## 1. Category rules after reconciliation

Reconciliation can attach a merchant to a transaction (from its matched receipt) and rejecting a
receipt link removes it. Rules match merchant names too, so `Reconciler.run` and `review_link` end
by re-applying rules to rule-managed and uncategorized rows. Hand-set categories stay untouched.

## 2. Global search

`GET /api/search?q=` returns the first matches, with totals, across documents (title, merchant, file
name), transactions (description and merchant words), inventory items (product, brand, category)
and accounts. A search box at the top of the sidebar (<kbd>Ctrl</kbd>+<kbd>K</kbd> or <kbd>/</kbd>)
opens `#/search?q=`, grouped by kind, each with "View all" into the page's own filtered view
(`#/documents?q=`, `#/transactions?q=`, `#/inventory?q=`).

## 3. B9 in the Documents list

The library query already returns `reconciliation_status` and `unfiled_reason`. The list now shows
them: under the state badge, "Matched to a charge", "Match proposed", "Several possible charges" or
"No matching charge yet" for receipts ("Paid" / "Marked unpaid" for bills), and under the name of an
Unfiled document, why it is unfiled.

## 4. H4: item analysis tools

Read-only tools over approved inventory lots (`item_analysis.py`); the model restates figures and
never computes them. Exact Decimal arithmetic, rounded half-even to the minor unit for display.

| Tool | Answers |
|---|---|
| `get_item_spending(query, start, end)` | Item-level totals per currency, top products |
| `item_price_history(query)` | Each purchase with merchant, size, quantity, line cost and price per 100 g / 100 ml / item |
| `get_price_changes(start, end)` | Largest increases in price per base unit between the first and last purchase in the period; a changed package size is flagged (shrinkflation) |
| `compare_merchant_prices(query)` | Latest price per base unit at each merchant, cheapest first |
| `get_consumption_cost(query)` | Cost per day and per 30 days from finished lots; approximate with fewer than three |
| `get_waste(start, end)` | Cost of thrown-out lots |
| `forecast_consumables_spend(month)` | Consumption rate × days in the month, per product with at least two finished lots |
| `detect_spending_anomalies(start, end)` | Categories and merchants above 1.5× their average over the three preceding periods of equal length |

Sizes are parsed from the product's size text (oz, lb, g, kg, fl oz, ml, l, qt, pt, gal, ct/pack).
Bare "oz" is weight. Purchases whose sizes are in different dimensions are not compared. A missing
quantity is treated as one unit, and the result says so.

**Routing.** Before the loop, the question is routed by keywords: item questions (products, prices,
inventory, running out, waste) get the item tools plus spending basics; everything else gets the
finance tools. The prompt lists only the routed tools and a call outside them is refused. The route
is saved with the answer.

## 5. Opened items and return windows

**Opened.** Lots in non-food categories (household cleaning, paper & disposables, personal care,
health, baby, pet, home maintenance, other) can be marked opened: `inventory_lots.opened_on`, event
`opened`, undoable. Food and drink categories are not tracked.

**Return windows.** A receipt's window comes from, in order:
1. **Printed on the receipt**: "returns within 30 days", "30-day return", "no returns", "all sales
   final". Found in the transcription when the receipt is recorded, and stored with its quote.
2. **The merchant's policy**: `return_policies` matches merchant name words (like category rules).
   It is seeded with a few well-known general policies marked *typical*; they can be edited,
   removed or added to. Policies change and have exceptions (electronics are often shorter), so the
   screen says to check the receipt.

A non-food lot that is in stock and unopened is *returnable* until purchase date + days. The
Inventory list shows "Returnable until …" or "Opened". Home shows windows closing within 14 days.

## 6. Investment and loan statements as assets

The classifier already recognizes `investment_statement` and `loan_document`; they now get field
schemas and publish to `assets` with `source='statement'`:

- **Investment:** institution, account name, account reference, statement date, ending value,
  currency. Retirement is recognized from the cited account name (401(k), 403(b), IRA, Roth,
  pension, TSP), and bond accounts from "bond" or "treasury".
- **Loan:** lender, account reference, statement date, principal balance, interest rate, regular
  monthly payment, currency. The rate must be printed as a percentage in its citation.

One asset row per account (institution + last four digits + kind). A newer statement updates the
value and date and returns the row to *proposed*; an older one is ignored. Every statement value
waits for review (the user's choice), in Review under "Statement values to confirm", and counts in
the forecast once confirmed. The document inspector shows the proposed asset with a link to Forecast.

## Verification

`tests/test_item_analysis.py` (sizes, each tool, routing), `tests/test_items.py` (opened, returns,
printed policy), `tests/test_extraction.py`-style synthetic statement for assets, rule re-run in
`tests/test_budgets.py`, search API. Browser tests updated for search and B9.
