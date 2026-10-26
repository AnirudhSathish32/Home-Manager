# The Money screens (Phase 2)

These are the page overrides for the four Money screens v2: This month (`month_v2.js`, route `#/spending`),
Transactions (`transactions_v2.js` with `money_v2.js`, `#/transactions`), Bills & subscriptions (`bills_v2.js`,
`#/bills`) and Accounts (`accounts_v2.js`, `#/accounts`). MASTER.md wins wherever this file says nothing. The hand-off
is `../phase2-money-plan.md`.

**The user's jobs** (asked 2026-10-11):
- **This month:** see where the money went, check budgets, compare with another month, manage category rules.
- **Transactions:** find a payment, fix its category, add one by hand, import a bank or card export.
- **Bills:** see what's due and whether it was paid, decide on proposed recurring payments, bill or subscription.
- **Accounts:** each account's balance and how fresh it is; import an export.

All four show category names through `categoryLabel()` (v1 showed raw keys).

## This month
- **Components:** four figure tiles (Net spending and the comparison month, both traced; Refunded, plain; the budgets'
  states as text). A needs-attention row for lines awaiting review. By category as a table (this month, the comparison
  month, the change as an arrow and a neutral amount, never green or red), with a 6px meter under budgeted names.
  Budgets reuse Today's rows (`.today-budget`), each ending in a Change… / Remove… menu. Top merchants and Refunds are
  dated lists. Category rules and "What these numbers cover" are closed `<details>`.
- **Layout:** header with ‹ month › (Next disabled at this month), Compare and Currency (only with more than one).
  Tiles in 4 columns, 2×2 under 1100px, one under 600px. By category `1.35fr` beside Budgets `1fr`, one column under
  1100px. Merchants and Refunds side by side, one column under 900px. Under 600px By category stacks (category and this
  month, then the comparison and the change).
- **States:** `pageState`. No spending: 0.00 tiles and an empty By category. Past month: no day count. Family: three
  tiles, no Budgets, no rules. Forms show errors under themselves (`.field-error`), never as toasts.

## Transactions
- **Components:** Import (secondary) and Add a payment (primary) in the header. Search, an Items | Charges segmented
  switch, period chips, Account and Category selects, More filters (Charges only). One table with sticky header; the
  drawer (shared, unchanged) opens on a row and reloads v2. A row just added gets `--accent-subtle`.
- **Layout:** desktop table; under 900px the Account column moves into the name's secondary line; under 700px each row
  is a grid (date | name | amount, receipt · account · status, the category select across).
- **States:** `pageState` first, then table errors as an alert with Retry above the table. Empty: Import and Add.
  Filters matching nothing: Clear filters. Family: owner column, no Add or Import.

## Bills & subscriptions
- **Components:** tiles from `recurring.totals` (per currency). To decide: one attention row per proposed payment with
  the kind select, Confirm (primary) and Not recurring (text). Coming up: uppercase kickers, Overdue in `--danger` with
  the alert icon (past due is red by meaning). All recurring payments: an All | Bills | Subscriptions switch, the kind
  select, the status badge and a "Mark as ended…" menu.
- **Layout:** tiles 3 columns, one under 700px. To decide full width. Coming up and All side by side from 1600px, one
  column below. Under 700px To decide's controls stack and All stacks into rows.
- **States:** `pageState`. Nothing at all: one empty state with Look for recurring bills. Family: no To decide, no scan,
  kind as text.

## Accounts
- **Components:** one tinted region per group; each row has the name and institution, the balance figure with its
  label and "as of", an "Over 35 days old" badge past 35 days, coverage, and a Transactions link. A Rename link button
  under the name swaps it for an inline form (Name, and Institution with a note only for an account whose institution
  clashes in case with another; Save, Cancel) with the error under the fields.
- **Layout:** a 3-column row grid, stacking under 600px. Import an export is the header's primary.
- **States:** `pageState`. No accounts: empty state with Import. Family: owner prefix, no Import.

## Decided (2026-10-11)
- This month is one page in two columns; category rules fold at its bottom.
- Transactions stacks its rows at 390.
- Import picks a CSV or XLSX already in the library (no browser upload).

## Deviations (built 2026-10-11)
- Bills' Coming up and All recurring payments sit side by side only from 1600px, not at 1440: at 1440 the table
  didn't fit beside Coming up and scrolled sideways.
- Transactions' Items | Charges switch has its own small tab handler: `wireTabs` hides each tab's panel, and both
  views share one results region.
