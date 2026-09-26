# Household items: resolution, inventory and consumption

Design spec (drafted 2026-09-25). H1 and H2 are implemented (see Status); H3 and H4 are open. Builds on the canonical finance store (`receipt_items`, migration 011), the review states (`proposed`, `needs_review`, `verified`, `rejected`) and the Phase 9 assistant loop in `assistant.py`. The local model is gpt-oss-20b served by LM Studio on loopback.

## Goals

1. Turn abbreviated receipt lines (`GV WHL MLK 1GL`) into full product names, with brand, size and category.
2. Keep a household inventory of everything bought, so "do I have X?" can be answered before buying it.
3. For anything that can run out, record when it was bought and when it ran out, and derive what it costs per day to consume.
4. Ask about run-out once a week, backing off for items that are rarely used.
5. Give the assistant item-level spending analysis.

## Decisions

| Topic | Decision |
|---|---|
| Model output | Every resolution, category and consumable flag the model proposes goes through review. |
| User answers | Check-in answers and manual inventory edits are the user's own input and apply directly, without review. Free text interpreted by the model is shown back as structured changes and applied on one confirmation tap. |
| Inventory timing | A lot enters inventory only when its item resolution is approved. The bought date is still the receipt date. |
| Consumable scope | Anything that can reasonably run out: groceries and household consumables (detergent, paper towels, toiletries, sealants…). |
| Search provider | Brave Search API. DuckDuckGo HTML scraping was rejected (CAPTCHAs, layout breakage, terms of use). |
| Not in scope | Product manual lookup. |

## Data model (migration 021)

Money stays integer minor units plus ISO currency. Dates are ISO strings.

- **`products`**: canonical product. `id, name, brand, size_text, size_value, size_unit, category, consumable (0/1), barcode, created_at, updated_at`. Created or matched when a resolution is approved.
- **`item_aliases`**: `(merchant_id, normalized_raw_text) → product_id`, plus `product_code` when printed. Written only by approval, so it is ground truth. `UNIQUE(merchant_id, normalized_raw_text)`.
- **`item_resolutions`**: one proposal per `receipt_items` row. `receipt_item_id, product_id (nullable), proposed_name, brand, size_text, category, consumable, confidence, method ('alias'|'history'|'barcode'|'search'), sources_json, model_run_id, review_status`. Rejected proposals are kept and never re-proposed for the same line.
- **`inventory_lots`**: one purchase of one product. `id, product_id, receipt_item_id, units, cost_minor, currency, bought_on, status ('in_stock'|'finished'|'thrown_out'), closed_on, closed_precision_days, next_check_on, check_interval_days`.
- **`lot_events`**: append-only history. `lot_id, event ('created'|'still_have'|'finished'|'thrown_out'|'reopened'|'undo'), effective_on, precision_days, source ('checkin'|'manual'|'checkin_text'), created_at`. Lot state is updated from events; undo appends a reversing event rather than deleting.
- **`checkins`**: one row per weekly check-in. `id, due_on, opened_at, completed_at, lot_ids_json`.

## Pipeline

```
receipt extracted → resolve items (deterministic, then agent) → review
   → approval writes products / item_aliases → inventory lot created
   → consumable lots enter the check-in schedule
```

Resolution runs in this order, stopping at the first hit. The model is involved only in the last step.

1. **Alias**: exact `(merchant, normalized text)` or `(merchant, product_code)` match in `item_aliases`.
2. **History**: the same normalized text on an earlier verified receipt from the same merchant.
3. **Barcode**: when the line has a UPC/EAN whose check digit validates, look it up in Open Food Facts (no key). A hit becomes a proposal with method `barcode`.
4. **Agent search**: the item-resolution agent below.

Steps 1–3 still produce proposals that go through review; they are pre-filled with high confidence so review is one tap.

## Agents and tools

Agents keep separate, short tool lists: a 20b model chooses tools noticeably worse past roughly eight. All tools use the existing JSON action loop (`call_tool` / `answer`) with typed Pydantic inputs, and tool results are labelled as data, not instructions.

### Item-resolution agent

Receives only lines unresolved by steps 1–3. Limits: 3 searches and 3 page opens per line, 30 searches per receipt, medium reasoning effort.

| Tool | Kind | Notes |
|---|---|---|
| `get_receipt_line(line_id)` | local read | Raw text, product code, quantity, prices, merchant, neighbouring lines |
| `find_similar_lines(merchant_id, text)` | local read | Verified lines with similar text, with their resolved products |
| `lookup_barcode(code)` | network, deterministic | Validates check digit first |
| `web_search(query)` | network | Returns result IDs, titles, snippets. See the query rules below |
| `open_result(result_id)` | network | Fetches a page by ID from an earlier `web_search`. Never takes a URL |
| `find_in_page(result_id, pattern)` | local | Returns matching passages from a fetched page, bounded |
| `propose_item_resolution(line_id, name, brand, size_text, category, consumable, confidence, source_ids)` | local write | The only write. Creates an `item_resolutions` row for review |

The search, open and find tools deliberately mirror gpt-oss's trained browsing tool (`search` / `open` / `find`).

### Check-in agent

Used only when the user answers a check-in in free text. Structured taps bypass the model.

| Tool | Kind | Notes |
|---|---|---|
| `get_checkin_candidates()` | local read | Lots in this check-in, with product, bought date and predicted run-out |
| `get_inventory(query)` | local read | In-stock lots matching a product name or category |
| `propose_lot_update(lot_id, status, effective_on, precision_days)` | local, staged | Shown to the user as a list of changes; applied on confirmation |

### Finance assistant additions

These are added to `finance_tools.py`. As with the existing tools, the model restates figures and never computes them.

| Tool | Answers |
|---|---|
| `get_inventory(query)` | "Do I have dish soap?" |
| `get_item_spending(product \| category, start, end)` | Item-level totals per currency |
| `item_price_history(product)` | Unit price over time, per merchant |
| `get_price_changes(start, end)` | Largest unit-price increases, normalized by size, so shrinkflation shows |
| `compare_merchant_prices(product)` | Cheapest merchant per unit |
| `get_consumption_cost(product \| category)` | Cost per day and projected per month |
| `get_waste(start, end)` | Cost of thrown-out lots |
| `forecast_consumables_spend(month)` | Projected cost from consumption rates |
| `detect_spending_anomalies(start, end)` | Categories and merchants well above their trailing baseline |

The assistant already has about 17 tools. Adding nine more makes it worth routing questions to a tool subset (finance vs. items) before the loop starts, rather than sending all schemas every time.

## Categories

A fixed list so analysis is stable. The model must choose from it: produce, dairy & eggs, meat & seafood, bakery, pantry, frozen, snacks, beverages, household cleaning, paper & disposables, personal care, health, baby, pet, home maintenance, other. `consumable` is a separate flag, since categories such as home maintenance mix consumables (sealant) and durables (a drill).

## Consumption and cost per day

- A lot's cost is its line total after discounts, `cost_minor`. Multiple units in one purchase are used one after another, so the lot lasts from `bought_on` to the day the last unit is finished.
- When several lots of a product are open, answers apply to the oldest lot first.
- **Lot days** = `closed_on − bought_on`, minimum 1.
- **Consumption rate** for a product = Σ cost of finished lots ÷ Σ lot days, per currency. Thrown-out lots are excluded from the rate and reported as waste.
- **Predicted run-out** = `bought_on` + median lot days of the product's finished lots, once there are at least two. Until then, the category default is used.
- A "sometime this week" answer stores the midpoint of the window with `precision_days = 3`. Results show a figure as approximate while fewer than three lots back it.

## Check-in schedule

- One check-in per week, on a configurable weekday. If the app is not running that day, the check-in opens on next launch. At most 15 lots per check-in, most overdue first. Items left over carry to the next week.
- **First check** for a new lot: predicted run-out if the product has history, else the category default (produce, dairy, bakery 7 days; meat and seafood 7; frozen, pantry, snacks, beverages 28; household and personal care 28).
- **Still have it** doubles the interval: 7 → 14 → 28 → 56 → 112 → 182 days, capped at 182, so a rarely used item is still asked about about twice a year.
- **Finished / thrown out** closes the lot and removes it from the schedule.
- **Repurchase**: when a new lot of a product is created while an older lot is still open, the older lot's next check moves to the next check-in. It is never closed automatically.
- **Manual updates** on the inventory screen (finished, thrown out with a date picker, still have it, reopen, undo) apply immediately, remove the lot from any pending check-in and reset its schedule from the new state.

## Search connector

- **Provider**: Brave Search API web search. The key is stored in Windows credential storage, never in settings files, prompts or logs.
- **Query rules**: the model supplies query text; the connector validates it before sending. Maximum 120 characters. Rejected if it contains any amount, date, card digits, address or store-location text from the receipt. Merchant name, item text and product code are allowed.
- **Result pages**: `open_result` accepts only result IDs from this run. HTTPS only, public addresses only (loopback and private ranges are refused after DNS resolution and on each redirect), 5 redirects, 10 s timeout, 1 MB response cap, HTML converted to text with scripts and styles dropped.
- **Caching and pacing**: search responses are cached by normalized query for 30 days; at most one request per second.
- **Failure**: a network, quota or parse error leaves the line unresolved with its reason, and the receipt continues. Offline, steps 1–3 still run.
- **Untrusted content**: page text is passed as data. The resolver's only write is a reviewed proposal, so a manipulated page can at worst produce a proposal the user rejects.

## Status (2026-09-25)

Built: migration 021, `items.py` (proposals, approval, products, aliases, lots, run-out schedule, manual updates and one-level undo), `web_lookup.py` (Brave search, Open Food Facts, guarded page fetch), `item_tools.py` (the seven resolver tools), `item_resolver.py` (alias → product code → barcode → one short agent loop per line), API routes under `/api/receipts/{id}/item-resolution-runs`, `/api/items/resolutions` and `/api/inventory`, and `get_inventory` in the finance assistant. Tests: `tests/test_items.py`.

Differences from the design above: the Brave key is read from the `HOME_MANAGER_BRAVE_API_KEY` environment variable until Windows credential storage is added. The first "still have it" answer sets a 7-day gap, then 14, 28 … 182. A lot's cost is the printed line total; how line discounts are printed varies, so they are not subtracted. There is no UI yet, and resolution runs only when requested, not automatically after extraction.

Update (2026-09-25): the inventory screen, resolution review (in Review) and H3 check-ins are built; see [money-review-inventory.md](money-review-inventory.md) §4. The free-text check-in is one structured model call instead of a tool loop. H4 analysis tools, assistant routing, opened/unopened tracking (non-food only) and return windows followed the same day; see [items-assets-search.md](items-assets-search.md).

## Delivery order

1. **H1**: migration 021, alias and history resolution, barcode lookup, review of resolutions, product creation, inventory lots, and the inventory screen with manual updates.
2. **H2**: item-resolution agent with the Brave connector.
3. **H3**: check-in scheduling, the check-in card on the home screen, the check-in agent for free text.
4. **H4**: analysis tools in the assistant, with routing to tool subsets.

## Open questions

- Track opened vs. unopened? Useful for stockpiles, costs an extra tap. Deferred.
- Warranty and return-window lookup, and recall checks (CPSC/FDA): undecided.
- Brave free-tier limits should be confirmed before H2.
