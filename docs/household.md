# Household

Household items bought on receipts: identifying receipt lines as products, the inventory, run-out tracking and weekly
check-ins, item-level analysis, return windows and warranties. Code: `household/items.py`, `household/resolver.py`,
`household/resolver_tools.py`, `household/analysis.py`, `household/warranty.py`, `models/web_lookup.py`,
`finance/checkin.py`; page `app/static/inventory.js`. Tests: `tests/test_items.py`, `tests/test_item_analysis.py`,
`tests/test_warranties.py`.

## Decisions

| Topic | Decision |
|---|---|
| Model output | Every product name, category and consumable flag the model proposes goes through Review. |
| Your answers | Check-in answers and manual inventory edits are your own input and apply directly. Free text the model interprets is shown back as structured changes and applied on one confirmation. |
| Inventory timing | A lot enters inventory only when its item identification is approved. The bought date is still the receipt date. |
| Consumable scope | Anything that can reasonably run out: groceries and household consumables (detergent, paper towels, toiletries, sealant…). |
| Search provider | Brave Search API. DuckDuckGo HTML scraping was rejected (CAPTCHAs, layout breakage, terms of use). |
| Not in scope | Product manual lookup. |

## Items and inventory

Data (migration 021); money is integer minor units plus ISO currency, and dates are ISO strings:
- **`products`**: the canonical product (name, brand, size text, parsed size value and unit, category, `consumable`,
  barcode). It is created or matched when an identification is approved.
- **`item_aliases`**: `(merchant_id, normalized_raw_text) → product_id`, plus `product_code` when printed. Written
  only on approval, so it is treated as ground truth.
- **`item_resolutions`**: one proposal per `receipt_items` row, recording the method (`alias`, `history`, `barcode`,
  `search`), its sources and the model run. A rejected proposal is kept and never proposed again for the same line.
- **`inventory_lots`**: one purchase of one product (units, cost, bought date, status `in_stock`, `finished` or
  `thrown_out`, closed date and its precision, next check date and interval, `opened_on`).
- **`lot_events`**: append-only history (`created`, `still_have`, `finished`, `thrown_out`, `reopened`, `opened`,
  `undo`), with source `checkin`, `manual` or `checkin_text`. Undo appends a reversing event rather than deleting one.

**Product categories** come from a fixed list (`CATEGORIES` in `household/items.py`): produce, dairy & eggs, meat &
seafood, bakery, pantry, frozen, snacks, beverages, household cleaning, paper & disposables, personal care, health,
baby, pet, home maintenance, other. These describe products and are separate from the receipt spending categories in
[money](money.md#categories). `consumable` is a separate flag, because a category such as home maintenance mixes things
that run out (sealant) with things that don't (a drill).

## Identifying receipt lines

The goal is to turn abbreviated receipt lines (`GV WHL MLK 1GL`) into full product names with brand, size and category.
When a receipt is recorded and **Identify receipt items automatically** is on (the `auto_identify_items` setting,
default on), the resolver runs on its lines in the same model job. The Inventory page also lists receipts with lines
not yet identified, each with **Identify items**.

Resolution stops at the first step that finds an answer:
1. **Alias**: an exact `(merchant, normalized text)` or `(merchant, product_code)` match in `item_aliases`.
2. **History**: the same normalized text on an earlier verified receipt from the same merchant.
3. **Barcode**: a UPC/EAN whose check digit validates is looked up in Open Food Facts (no key needed).
4. **Agent search**: one short agent loop per remaining line.

Every result, including those from steps 1–3, is a proposal in Review (**Receipt items to identify**, which lets you
edit before approving). Steps 1–3 are pre-filled, so reviewing them takes one tap.

**The resolver agent** keeps a short tool list, because small models choose tools noticeably worse beyond about eight.
- Its tools are `get_receipt_line`, `find_similar_lines`, `lookup_barcode`, `web_search`, `open_result`,
  `find_in_page` and `propose_item_resolution`. The last is its only write: a proposal for review.
- The search, open and find tools mirror gpt-oss's trained browsing tools.
- Limits: 3 searches and 3 page opens per line, and 30 searches per receipt.

**The search connector** (`models/web_lookup.py`):
- **Key.** The Brave Search API key is read from `HOME_MANAGER_BRAVE_API_KEY`, never from settings files, prompts or
  logs. Storing it in Windows Credential Manager is open work.
- **Queries.** At most 120 characters. A query is refused if it contains any amount, date, card digits, address or
  store location from the receipt. Merchant name, item text and product code are allowed.
- **Opening pages.** `open_result` takes only result ids from this run, never a URL.
  - HTTPS only, and public addresses only: loopback and private ranges are refused after DNS resolution and on each
    redirect.
  - At most 5 redirects, a 10 s timeout and a 1 MB response cap. HTML is converted to text, with scripts and styles
    dropped.
- **Caching and pacing.** Results are cached by normalized query for 30 days, at most one request per second.
- **Failures.** A network, quota or parse error leaves the line unidentified with a reason, and the rest of the receipt
  continues. Offline, steps 1–3 still run.
- **Untrusted content.** Page text is passed as data. A manipulated page can at worst produce a proposal you reject.

## Run-out, cost per day and check-ins

**Consumption**
- **Cost.** A lot's cost is its printed line total. Line discounts are not subtracted, because the way they are printed
  varies.
- **Lot length.** Several units bought together are used one after another, so the lot lasts from `bought_on` to the
  day the last unit is finished. When several lots of a product are open, answers apply to the oldest lot first.
- **Lot days** = `closed_on − bought_on`, at least 1.
- **Consumption rate** = total cost of finished lots ÷ total lot days, per currency. Thrown-out lots are left out of
  the rate and reported as waste.
- **Predicted run-out** = `bought_on` + the median lot days of the product's finished lots, once there are at least
  two. Until then the category default is used.
- **Approximate answers.** A "sometime this week" answer stores the midpoint of the window with `precision_days = 3`.
  Figures are marked approximate while fewer than three lots back them.

**Schedule**
- **First check** for a new lot: the predicted run-out if the product has history, otherwise the category default.
  Produce, dairy, bakery, meat and seafood are checked after 7 days. Frozen, pantry, snacks, beverages, household and
  personal care are checked after 28.
- **Still have it** sets the next gap to 7 days, then 14, 28, 56, 112 and 182 (the cap), so a rarely used item is still
  asked about about twice a year.
- **Finished** or **thrown out** closes the lot and removes it from the schedule.
- **Repurchase.** When a new lot of a product is created while an older one is still open, the older lot's next check
  moves to the next check-in. It is never closed automatically.
- **Manual updates** on the Inventory page apply at once, remove the lot from any pending check-in and reset its
  schedule. These are Still have it, Finished, Thrown out (with a date picker), Reopen, Undo and History.

**Weekly check-in.** No extra state is stored. The check-in day is the latest configured weekday on or before today
(Settings, default Sunday), so a missed day opens on the next launch.
- **What it holds.** Consumable lots in stock whose next question is due by then, most overdue first, at most 15.
  Leftovers carry over by construction.
- **Answers.** Home shows the check-in card with one-tap answers: Still have it · Finished today · Finished this week
  (the midpoint, ±3 days) · Thrown out.
- **Free-text answers.** An answer like "Finished the milk and eggs on Tuesday, still have rice" goes to one structured
  model call along with the check-in's lots.
  - The model only names lots from the list and picks among fixed options. Dates are resolved in code.
  - The updates are shown as a list and apply only when you confirm (source `checkin_text`).
  - It runs on the inference queue like other model work.

## The Inventory page

`#/inventory` has search, a "show finished items" switch, and a table grouped by category with:
- the bought date and status;
- the next question;
- "Returnable until …" or "Opened", and "Warranty until …";
- the row actions listed above.

A panel lists receipts with lines not yet identified. Home shows cards for return windows closing within 14 days and
warranties ending within 60 days.

## Opened items and return windows

**Opened.** Lots in non-food categories can be marked opened (`inventory_lots.opened_on`, event `opened`, undoable).
These are household cleaning, paper & disposables, personal care, health, baby, pet, home maintenance and other. Food
and drink are not tracked.

**Return windows.** A receipt's return window comes from, in order:
1. **Printed on the receipt**: "returns within 30 days", "30-day return", "no returns", "all sales final". This is
   found in the transcription when the receipt is recorded, and stored with its quote.
2. **The merchant's policy**: `return_policies` matches merchant name words (like category rules). It is seeded with a
   few well-known general policies marked *typical*, which you can edit, remove or add to. Policies change and have
   exceptions (electronics are often shorter), so the screen says to check the receipt.

A non-food lot that is in stock and unopened is *returnable* until the purchase date plus the window's days.

## Returned items

A line on a return receipt (a negative line, [money](money.md#returns)) brings nothing home: identifying it never
creates a lot. It may instead close the lot that bought it (`household/items.py`, migration 063).
- **Proposed** by each reconciliation pass (`ItemLedger.propose_returns`), for a returned line on an approved receipt.
  The candidates are in-stock lots from the same seller, bought on or before the return, with the same printed product
  code, the same printed text, or the product that text was identified as. A line with no candidate is left alone and
  tried again on the next pass. The proposal is kept in `lot_returns`.
- **Asked on the Inventory page** under **Returned items**: "Yes, … went back" (or which of several), or "Not this
  item" / "None of these". Each line is asked once (`POST /api/inventory/returned/{receipt_item_id}`).
- **Confirming** closes the lot as `returned` on the return's date (lot event `returned`, source `approval`). Like any
  answer it can be undone from the lot's Actions menu. A returned lot leaves the check-in questions and the return
  windows.

## Warranties

Warranties apply to durable items (products not marked as running out), migration 025.
- **Suggestions.** Items costing at least 100 in the currency's main unit (a bed, a computer) are suggested for a
  warranty lookup. Any durable item can have one entered by hand.
- **Data.** `warranties` has one row per lot and kind (manufacturer, store or extended). Each row holds months or
  lifetime, start (the purchase date) and end, source (`user` or `lookup`), the source page's title, URL and quote, and
  a review status. A warranty you enter counts at once. A looked-up one is *proposed* until you confirm it in Review
  (**Warranties to confirm**).
- **Lookup.** A short agent run on the inference queue with Brave web search. Its tools are `get_item`, `web_search`,
  `open_result`, `find_in_page` and `propose_warranty`.
  - Queries may not contain prices, dates, long numbers or the store location.
  - A proposal must quote the opened page exactly, and the quote must mention a warranty or guarantee.
  - The months proposed must be stated in the quote ("1-year", "12 months", "two year", "lifetime"). Anything else is
    refused and returned to the model.
  - Without a search key or a reasoning model, lookup is unavailable, but entering a warranty by hand still works.
- **Links** from documents and web pages are shown as text, never as clickable links.

## Item analysis

These are read-only tools over approved inventory lots (`household/analysis.py`), available to the assistant on its item
route ([assistant](assistant.md)). The model restates figures and never computes them. Arithmetic is exact Decimal,
rounded half-even to the minor unit for display.

| Tool | Answers |
|---|---|
| `get_inventory(query)` | "Do I have dish soap?" |
| `get_item_spending(query, start, end)` | Item-level totals per currency, top products |
| `item_price_history(query)` | Each purchase with merchant, size, quantity, line cost and price per 100 g / 100 ml / item |
| `get_price_changes(start, end)` | Largest increases in price per base unit between the first and last purchase in the period; a changed package size is flagged (shrinkflation) |
| `compare_merchant_prices(query)` | Latest price per base unit at each merchant, cheapest first |
| `get_consumption_cost(query)` | Cost per day and per 30 days from finished lots; approximate with fewer than three |
| `get_waste(start, end)` | Cost of thrown-out lots |
| `forecast_consumables_spend(month)` | Consumption rate × days in the month, per product with at least two finished lots |
| `detect_spending_anomalies(start, end)` | Categories and merchants above 1.5× their average over the three preceding periods of equal length |

- **Sizes** are parsed from the product's size text: oz, lb, g, kg, fl oz, ml, l, qt, pt, gal, ct/pack. A bare "oz"
  means weight.
- Purchases whose sizes are in different dimensions are not compared.
- A missing quantity is treated as one unit, and the result says so.
