# Money pages, category rules and budgets, Review, Inventory and check-ins

Status: implemented 2026-09-25 (migration 023, `checkin.py`, `static/finance.js`, `review.js`, `inventory.js`).

Plan and record for four upgrades (2026-09-25): UI Phase C and Phase D from
[ui-design-plan.md](ui-design-plan.md), category rules and monthly budgets, and the household
inventory screen with H3 check-ins from [household-items.md](household-items.md). The backend
behind Phase C and D (B1–B15) already exists; this work is mostly the pages, plus two small
data additions.

## 1. Money pages (UI Phase C)

The single Finances page becomes four routes. `#/finances?…` links (from Home and bookmarks)
are redirected: `section=review|unmatched` goes to Review, `section=bills` to Bills, anything
else to Transactions with the same filters.

| Route | Content | Server calls |
|---|---|---|
| `#/transactions` | Toolbar: search, from/to, account, category, type, status, receipt evidence, sort. Table with paging (200 per page, server offset). A row opens a drawer: amount, status with Count/Reject, category with "always use for this merchant", evidence and links, history. | `get_transactions` (server filters, B2), `GET /api/finance/records/transaction/{id}` (links, B3) |
| `#/spending` | Month and comparison (previous month, same month last year). Figure row, by-category table with change and budget, top merchants, refunds, coverage notes. Budgets and category rules are managed here. | `get_spending`, `compare_categories`, `get_spending_by_category`, `get_refunds`, `get_budgets`, rules API |
| `#/bills` | Bills grouped past due, next 7 days, later, paid; Mark paid / Mark unpaid. Recurring payments with Confirm / Not recurring / Ended. | `get_upcoming_bills`, bill payment and recurring review endpoints (B6) |
| `#/accounts` | Accounts grouped by type, statement balance with "as of", coverage, stale marker (over 35 days), link to Transactions for the account. No cross-account total (decision §10.4). | `get_accounts` |

## 2. Category rules and budgets (migration 023)

**Rules.** `category_rules(pattern, category, account_id?)`: a transaction whose merchant key
(`normalize_name` of the description plus merchant name) contains every word of the pattern gets
the category. The most specific rule wins (most words, then newest). `transactions.category_source`
records `user` or `rule`: a category the user set by hand is never touched by a rule. Rules apply
when rows are inserted (imports and extractions) and when a rule is added, changed or deleted.
Clearing a hand-set category hands the row back to the rules.

**Budgets.** `budgets(category, currency, amount_minor)`: one monthly amount per category and
currency. The `get_budgets(month)` tool returns spent (the same counted category spending as
By category), remaining, percent used, and pace for the current month: `over` when spent exceeds
the budget, `ahead` when the share spent is above the share of the month elapsed, else `on_track`.
All figures are exact integer arithmetic with display text; percentages are exact Decimal strings.
Home shows a Budgets card when budgets exist.

## 3. Review page (UI Phase D)

`#/review`: a two-pane queue. Left: groups with counts. Right: the selected item's what, why and
evidence, with decision buttons. <kbd>J</kbd>/<kbd>K</kbd> move, <kbd>V</kbd> confirms, <kbd>R</kbd>
rejects; each decision advances. Record decisions offer Undo for 8 seconds (back to Needs review).

Groups, in priority order: questions (ambiguous matches), proposed links, records awaiting
verification, recurring payments to confirm, receipt items to identify (item resolutions, with
edit-before-approve), receipts with no matching charge (informational), and counts of documents
that couldn't be processed or are unfiled (linking to Documents). No internal IDs or scores in the
default view; the match signals are in words. The sidebar Review badge replaces the Finances one.

## 4. Inventory and weekly check-ins (H3)

`#/inventory`: search, show finished items, table grouped by category with bought date, status,
next question, and actions (Still have it, Finished, Thrown out, Reopen, Undo, History). A panel
lists receipts with lines not yet identified, each with **Identify items** (starts the existing
item-resolution run; proposals appear in Review).

**Check-in.** No new state: the weekly check-in day is the latest configured weekday on or before
today (Settings, default Sunday). The check-in holds consumable lots in stock whose next question
is due by then, most overdue first, at most 15; leftovers carry over by construction. Answers use
the existing lot events with source `checkin`. Home shows the check-in card with one-tap answers:
Still have it · Finished today · Finished this week (midpoint, ±3 days) · Thrown out.

**Free-text answers.** "Finished the milk and eggs on Tuesday, still have rice" goes to one model
call with the check-in's lots, returning structured updates (lot, event, today / this week / date).
The model only names lots from the list and chooses among fixed options; dates are resolved in
code, never by the model. The updates are shown as a list and apply only on confirmation
(source `checkin_text`). This replaces the planned tool loop with a single structured call, which
fits the small models this app targets. It runs on the inference queue like other model work.

## Verification

- `tests/test_budgets.py`: rules (specificity, user override, clear hands back, apply on insert,
  delete re-derives), budgets (spent, remaining, pace, currency separation), API.
- `tests/test_items.py`: check-in window and limit, weekday, free-text parsing and confirmation.
- The opt-in browser tests are updated for the new routes and IDs.
