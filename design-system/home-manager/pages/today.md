# Today (Phase 2)

These are the page overrides for Today v2 (`src/home_manager/app/static/today_v2.js`, route `#/home`). MASTER.md wins
wherever this file says nothing. The hand-off is `../phase2-today-plan.md`.

**The user's job:** see where the household stands this month (cash, net worth, what's spent, what came in) and what
needs them, then go and deal with it.

## Components (from MASTER "Components")
- **Figure tile:** four tiles: Cash, Net worth, Spent in {month}, and Money in.
  - Each figure is a `figure()` that opens its breakdown.
  - Spent shows unsigned, with the label giving the direction. Money in is `--positive` with `+`.
  - Cash's subline gives the date range of the balances. Any balance over 35 days old adds the stale badge with
    "Some balances are old".
- **Tinted region:** Needs you, the budgets, and each dated section are one region each. Regions never nest, and the
  lists inside them use 1px dividers.
- **Needs-attention row:**
  - Rows that need a decision use `--warning-subtle` with a `--warning` icon. These are taxes, records to check,
    matches and questions, and family routing.
  - Informational rows have no fill and a muted icon. These are receipts with no charge, receipts with no date, and
    documents ready to record.
  - Every row has one text-link action. Rows with a count of 0 aren't shown, and when nothing needs you there's one
    muted ✓ row.
- **Budget meter:** `meter()` from finance.js.
  - The row head shows the category link and a badge (only when the budget is ahead of pace or over). On the right it
    shows either "{remaining} left" or "Over by {over}" in `--warning`.
  - Below the meter: "{spent} of {budget}". Amber, never red.
- **Charts:** the v1 trend and donut, reused unchanged (`homeTrend`, `homeCategories`).

## Layout (from MASTER "Layout")
- **Header:** the h1 "Today", the subline, and Month, Currency and Refresh on the right.
- **Tiles:** 4 columns, and 2×2 under 1100px. Under 600px the figure is `--text-lg` and only the first subline shows.
- **Main grid:** a left column `minmax(0,1.15fr)` (Needs you, then Bills, CDs and Treasuries coming due, Weekly
  check-in, Return windows closing and Warranties ending soon, each hidden when empty) beside the budgets
  `minmax(0,1fr)`. It becomes one column under 1100px.
- **Below the main grid:** the charts, then "What these numbers cover" as a closed `<details>`.
- **Family profile:**
  - No budgets, check-in, returns or warranties, so the left column takes the full width.
  - The tiles are the family totals.
  - "Each person" (with Cash and Net worth) and "Counted once" follow the charts.
- **Decision in view:** the first Needs you action is in view at 1366×768.
- **The URL** keeps `month`, `currency` and `months`.

## States
- Loading, error with Retry, and no library: all through `pageState`.
- Family with no members: the v1 empty text in Needs you.
- No budgets: an empty state with a "Set a budget" link.
- No balances: "No statement balances yet" on the Cash tile.
- Long names wrap (`overflow-wrap:anywhere`), and amounts don't.

## Decided (2026-10-10)
- Needs-you first, in two columns.
- Both charts kept.
- Four tiles.
- Separate small dated sections.
- The family view built in this session.
- At 390, the tiles come before Needs you.
- The name "Today" only when v2 is on; the route stays `#/home`.
