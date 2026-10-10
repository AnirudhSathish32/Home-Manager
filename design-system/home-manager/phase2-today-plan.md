# Redesign: Today (#/home) (phase 2)

First step for the implementer: save this hand-off as `design-system/home-manager/phase2-today-plan.md` and write
`design-system/home-manager/pages/today.md` from the "Design-system references", "Layout" and "States" sections below.
Plan mode couldn't write them.

## Context
Today is the second Phase 2 screen (docs/open-work.md "UI redesign" 6). The user comes here to see where the household
stands this month and what needs them, then jumps to it. What's wrong today (before shots, and the 2026-09-30 review):
- "Needs attention" sits below two tall charts, at y ≈ 1030 of a 2000px page. The decision isn't in view.
- Rows with a count of 0 still show ("0 receipts without a purchase date").
- There's no Cash or Net worth for a personal profile.
- Budgets are at the very bottom, as a separate card with "2026-10" as raw month text.
- Coverage prose fills a full-width panel.
- Bills, maturities, returns, warranties and the check-in are scattered cards.
- No figure on the page opens its breakdown.

**User decisions (this session, 2026-10-10):**
- Layout "Needs-you first, two columns": tiles, then Needs you plus dated sections on the left beside the budgets on
  the right, then the charts.
- **Keep both charts** (trend and donut), restyled only by what Phase 1a already did.
- Four tiles: **Cash, Net worth, Spent, Money in.** Net cash flow is Money in's subline.
- **Separate small sections** for Bills, CDs and Treasuries coming due, Weekly check-in, Return windows and Warranties,
  each hidden when empty.
- **Family view in this session too.**
- Phone: tiles in a 2×2 grid, then Needs you.
- **The name "Today" on v2 only.** The page h1 and document title say Today. The sidebar label says Today only while the
  v2 Today is on; v1 keeps "Home". The route stays `#/home`.

**Carried from Phase 0** (MASTER.md "Decided for later screens"):
- Budgets in the breakdown style, with meters that are amber when ahead or over, never red.
- Cash and Net worth side by side, with the date range and stale accounts (over 35 days) flagged.

## Before screenshots
`<scratchpad>/before-home/`. Look at `home-1440-light.png` and `home-390-light.png` (full page). The seed shows no
bills, no balances and a one-month trend, so the seeding below is added before the after shots.

## Design-system references
- MASTER.md "Components":
  - **Figure tile:** a 12.5px secondary label, `figure()` at `--figure-lg`, a muted subline, and an accent ring when its
    breakdown is open. Money in is `--positive` with `+`.
  - **Needs-attention row:** `--radius-md`, a 20px icon in its tone, a semibold *what*, a muted *why*, and one text-link
    action on the right. `--warning-subtle` when it needs you.
  - **Tinted region:** `--surface`, a 1px `--border`, `--radius-lg`, never nested, and lists inside use dividers.
  - **Budget meter:** 8px, "$spent of $budget" with the remaining amount or state. `on_track` is `--chart`; `ahead` is
    `--warning` with "Ahead of pace"; `over` is a full `--warning` bar with ⚠ and "Over by $12". Never red.
- MASTER.md "Decided for later screens": the Cash and Net worth wording above.
- **Deviations:**
  - The needs rows' 6px gap becomes `--space-1` (4px), to stay on the scale.
  - Under 600px the tile figure drops to `--text-lg`, as Taxes v2 does, so 2×2 tiles fit at 390.

## Tokens
Existing tokens only, with no new tokens or hex values:
- Regions and text: `--surface`, `--border`, `--radius-lg/md`, `--text`, `--text-secondary`, `--text-muted`.
- Accent and attention: `--accent`, `--warning`, `--warning-subtle`, `--positive`, `--danger` (overdue bills only,
  through `statusBadge`).
- Meters and spacing: `--chart`, `--chart-track`, `--space-1..7`.
- Type: `--text-xs/sm/md/lg`, `--figure-lg`.

Every pair is already checked in MASTER.md "Color tokens": warning/warning-subtle 5.2 and 7.8, muted/surface 5.0+, and
warning/track 5.0 and 6.5.

## Layout
1440×900 (sidebar 220 → content about 1150px):
```
Today                                   Month [Oct 2026] Currency [USD▾] [Refresh]
Your household this month.
Oct 1 – Oct 10 · Updated 3:33 PM
┌Cash──────────┐┌Net worth─────┐┌Spent in October┐┌Money in──────┐   ← #today-tiles (4 cols)
│ 8,412.30 USD ││ 41,200.00 USD││ 2,106.06 USD   ││+4,125.00 USD │
│As of Aug 30 –││Cash + assets ││Sep 1–10:       ││Net cash flow │
│Oct 5 ⚠ Some  ││ − loans      ││ 1,950.00 USD   ││ 2,018.94 USD │
│balances old  ││              ││                ││              │
└──────────────┘└──────────────┘└────────────────┘└──────────────┘
┌Needs you  [3]──────────────────┐ ┌October budgets─────── Day 10 of 31┐  ← DECISION REGION:
│⚠ Taxes: a W-4 change is …  Open│ │dining                  101.40 left│    starts at y≈300,
│⚠ 1 record to check       Review│ │▓▓░░░░░░░░░░░░░                    │    first rows at y<500
│▢ 1 receipt with no charge Review│ │18.60 of 120.00 USD                │
└────────────────────────────────┘ │groceries ⚠Ahead of pace  26.45 left│
┌Bills───────────────────────────┐ │▓▓▓▓▓▓▓▓▓▓▓▓▓▓░                    │
│Oct 15  Maple rent    1,650.00  │ │223.55 of 250.00 USD               │
│All bills (1)                   │ │───────────────────────────────────│
└────────────────────────────────┘ │Not budgeted: 1,864.00 USD · 7 tx  │
┌CDs and Treasuries coming due───┐ │Set budgets                        │
┌Weekly check-in─────────────────┐ └───────────────────────────────────┘
┌Return windows closing──────────┐
┌Warranties ending soon──────────┐
┌Spending over time (v1 chart)─────────────┐┌Spending by category (donut)┐  ← .home-charts reused
└──────────────────────────────────────────┘└────────────────────────────┘
▸ What these numbers cover   (details, closed)
```
Left column `minmax(0,1.15fr)`, right `minmax(0,1fr)`, gap `--space-6`, `align-items:start`. Under 1100px it becomes
one column: Needs you, the budgets, then the dated sections.

390 (top bar, 16px gutters):
```
Today
[Month][Currency][Refresh]   (wraps)
┌Cash──────┐┌Net worth─┐
│8,412.30 …││41,200.00…│   tiles 2×2, figure --text-lg
└──────────┘└──────────┘
┌Spent─────┐┌Money in──┐
└──────────┘└──────────┘
Needs you [3]  rows …        ← starts at y≈420
October budgets …
Bills … / CDs … / Check-in … / Returns … / Warranties …
Trend, donut (stacked, as v1 already does)
▸ What these numbers cover
```
768: the tiles stay 2×2 (under 1100), with one column below.

**Family profile:** no budgets region (the family has none), so `.today-main` gets `no-aside` and the left column spans
the full width. The tiles are family Cash, Net worth, Spent and Money in. After the charts come "Each person" (the
per-person table with Cash and Net worth columns) and "Counted once".

Decision in view (Layout rule 1): at 1366×768 the first `.needs-row` action's bottom is ≤ 768, which the new test
asserts. Nothing of variable height sits above Needs you except the fixed-shape tiles.

## Changes by file

### Backend (additive; v1 keeps working)
- **`finance/forecast.py`:**
  - Add `STALE_DAYS = 35`.
  - Add `balance_dates(balances, today)`, returning `{"first", "last", "stale": [{"account","account_id","as_of"}]}`
    from `baseline()["balances"]`. A balance is stale when `as_of < today − 35 days`.
- **`finance/dashboard.py` `dashboard()`:**
  - Inside the snapshot, run `base = baseline(FinanceTools(snap), Assets(snap), 3, chosen, today)`, where `snap` is the
    dashboard's `SnapshotStore`.
  - Add `found["worth"] = {"cash": figure(cash, chosen, ref("worth.today", figure="cash", currency=chosen,
    history_months=3)), "net_worth": figure(…, figure="net_worth"…), "dates": balance_dates(base["balances"], today),
    "notes": base["notes"]}`.
  - Cash and net worth add up exactly as `wealth_traces.worth_today` does. Pull that sum into one helper,
    `worth_totals(base)`, in `wealth_traces.py` and call it from both places.
  - `figures(found)` also returns `cashflow.inflow`, `worth.cash` and `worth.net_worth`, so their `stale` flags work.
- **`finance/tools.py` `calculate_cashflow`:**
  - Set `row["inflow"]["trace"] = ref("cashflow.in", **shown)`.
  - Take `only=None`. When `only == "inflow"`, the live recorder skips the "Net spending" step and keeps the money-in
    step and its inputs.
- **`finance/traces.py`:**
  - Add `cashflow_in(store, ref_text, params)`, which mirrors `cashflow_net` with `only="inflow"`. Its label is
    "Money in, {start} to {end}" and its formula is "Deposits, interest and other money in. Transfers between your own
    accounts and card payments aren't money in."
  - Register it in `TRACES` as `"cashflow.in"`, and add `"cashflow.in"` to the `FAMILY_TRACES` names.
- **`finance/wealth_traces.py` `worth_today`:** a cash step for a stale balance is labelled
  `"{account} · {as_of} · over 35 days old"`. Use `balance_dates`.
- **`finance/family.py`:**
  - `family_dashboard`: set `total["cashflow"]["inflow"] = figure(…, ref("family.cashflow.in", **shown))`. The member
    copies get `ref("cashflow.in", **mine)`, as `net` does today.
  - `family_net_worth`: add `"dates"`, which is `balance_dates` across every member's balances, each stale row carrying
    `member`.
- **Tests** in `tests/test_traces.py`:
  - `cashflow.in` reconciles and equals the dashboard's Money in.
  - `family.cashflow.in` reconciles.
  - The dashboard's `worth.cash` and `worth.net_worth` equal their traces.
  - A balance 40 days old appears in `dates.stale`, and its trace step says "over 35 days old".

### New `app/static/today_v2.js` (loaded after `home.js`, before `shell.js`)
- **Registration:** `V2_SCREENS.home = {title: "Today", show: route => loadTodayV2(route.params)}`.
- **State:** `today = {month, currency, months}`, read from the URL params `month`, `currency` and `months` (6|12). Each
  change writes back with `history.replaceState` (Layout rule 5).
- **`loadTodayV2(params)`** sets `#today-month` (max = `localMonth()`), the currency select and `homeMonths`, then calls
  `pageState($("today-state"), renderTodayV2, {loading: "Loading today …", what: "your household", needsLibrary:
  !familyMode, content: [$("today-body")]})`.
- **`renderTodayV2()`:**
  - Fetch `/api/dashboard?month&months&currency`. In family mode also fetch `/api/family/net-worth?currency`. In
    personal mode also fetch, in parallel: `tool("get_budgets", {month, as_of: todayIso()})`, `/api/inventory/checkin`,
    `/api/inventory/returns` and `/api/warranties/expiring`.
  - When `data.family_empty`, show the v1 empty-state text and link inside `#today-needs`, and hide the tiles, budgets
    and charts.
  - Otherwise fill the currency select, then call `todayTiles`, `todayNeeds`, `todayDated`, `todayBudgets` (personal
    only), the charts, `todayFamily` (family only) and `todayAbout`. Set `#today-status` to
    "{period start} – {end} · Updated {time}", as v1 does.
- **`todayTile(label, fig, opts, sub)`:** a `.figure-tile` with a `p.figure-label`, `figure(fig, opts)` and a
  `p.figure-sub`. Copy `taxes2Tile`'s shape; don't import it.
  - **Cash:** `worth.cash`, signed. Its sub is "As of {dateText(first)} – {dateText(last)}". When `dates.stale.length`,
    add a second line with a `statusBadge(span, "stale", …, "Some balances are old")`. With no balances, the sub is
    "No statement balances yet" plus a link to Accounts.
  - **Net worth:** `worth.net_worth`, signed. Its sub is "Cash + assets − loans".
  - **"Spent in {monthText}":** `totals.net_spending` with `{magnitude: true}`. Its sub is
    "{dateText(prev.start)} – {dateText(prev.end)}: {comparison.first.display}" (neutral, no arrows), or "Nothing
    recorded the month before".
  - **Money in:** `cashflow.inflow`, signed (green "+"). Its sub is "Net cash flow " + `figure(cashflow.net, {size:
    "inline"})`.
  - With a missing figure (no data), the tile shows `amount()` of nothing as "No recorded data", muted.
- **`todayNeeds(data, checkin)`:** `section#today-needs.today-region`.
  - The heading is `h2` "Needs you" plus a `span.nav-count.attention` count, omitted when the count is 0.
  - The list is `ul.needs-list` of `li.needs-row`, with `.needs-row.attention` on rows that need a decision.
  - Each row holds `icon(name, "icon needs-icon")`, then `div` > `strong` *what* + `small.muted` *why*, then one
    `homeLink(action, href, "needs-action")`.
  - Rows, in order, each only when its count is above 0. The `.attention` rows are:
    1. (family) routing waiting: icon `users`; "{n} document(s) waiting for a person"; "They count for nobody until
       you say whose they are."; action "Choose who" → `#/review`.
    2. `attention.tax`: icon `receipt-tax`; "Taxes: {status_text}"; why is "What changed: {trigger}" or "{year}
       return"; action "Open Taxes" → `#/taxes`.
    3. `records`: icon `list-checks`; "{n} record(s) to check"; "Read from your documents, waiting for you"; action
       "Review" → `#/review`.
    4. `links` + `issues`: icon `list-checks`; "{links} proposed match(es) · {issues} open question(s)", leaving out a
       zero half; "Review" → `#/review`.
  - The neutral rows are:
    5. `unmatched`: icon `receipt-tax`; "{n} receipt(s) with no matching charge · {total.display}"; "They count on
       their own until a card or bank charge replaces them."; "Review".
    6. `undated`: icon `calendar`; "{n} receipt(s) without a purchase date"; "Review".
    7. `ready`: icon `file`; "{n} document(s) ready to record"; "Open" → `#/documents?status=ready_for_ledger`.
  - In family mode the why for 3–7 is "Added up across the family. Review happens in each person's own profile."
  - When there are no rows: one `li.needs-row` with icon `check-circle` and "Nothing needs you right now.", muted,
    with no action.
  - Use a small local `plural(n, one, many)`.
- **`todayDated(data, extras)`:** `div#today-dated`, holding one `section.today-region.today-section` per kind, each
  hidden (not rendered) when empty. Each has an `h2` and a `ul.dated-list` of `li.dated-row`:
  `span.dated-when` (dateText) | `div` (name link + `small.muted` meta) | `amount()` right-aligned, or blank.
  - **Bills:** overdue rows first, each with `statusBadge(..., "past_due")` in the meta, then the next 30 days. The
    footer `homeLink("All bills ({total})", "#/bills", "today-footer")`. Family meta adds the member.
  - **CDs and Treasuries coming due:** the `data.maturities` row text, as v1 builds it with `MATURITY_STATES`, and "All
    {n} coming due" when there are more.
  - **Weekly check-in** (personal only): `renderCheckin(body, checkin, {compact: true})`.
  - **Return windows closing** (personal only): up to 6 rows, "Return by {date}", linking to the Inventory search, as
    v1 does.
  - **Warranties ending soon** (personal only): up to 6, "{kind} warranty ends {date}".
- **`todayBudgets(budgets, month)`:** `section#today-budgets.today-region`.
  - The `h2` is "{monthText(month)} budgets", with a `small.muted` "Day {elapsed} of {days}" while the month is under
    way.
  - Each row is `div.today-budget` containing:
    - a head: `homeLink(category, "#/spending?month=…")`, then `statusBadge(row.status)` only for `ahead_of_pace` or
      `over`, then on the right either "Over by " + `amount(row.over, {magnitude: true})` (when
      `remaining_state === "over"`) or `figure(row.remaining, {size: "inline", magnitude: true})` + " left";
    - `meter(row)` from finance.js, reused;
    - a `small.muted` line: `figure(row.spent, {size: "inline", magnitude: true})` " of " `amount(row.budget,
      {magnitude: true})`, plus " · expected " `figure(row.projected, …inline)` when `recurring_due.minor > 0`.
  - Footer: "Not budgeted: {unbudgeted[currency].spent.display} · {n} transactions" for the shown currency, and
    `homeLink("Set budgets", "#/spending")`.
  - With no budgets: `emptyState("No budgets for this month yet.", homeLink("Set a budget", "#/spending"))`.
- **Charts:** `div.home-charts` holding `homeTrend(data, reloadToday)` and `homeCategories(data)`, reused from home.js.
- **`todayFamily(data, worth)`:** `familyMembers(data)` (re-id it `today-family-members`), then
  `familyWorthPanel(worth)` (re-id `today-family-worth`), then `familyAdjustments(data.family)`.
- **`todayAbout(data)`:** `details#today-about` with the summary "What these numbers cover". Inside: the coverage
  sentence, the pending warning, and v1's fixed explanation, with v1's text and classes.
- **Controls:** a month or currency `change` and `#today-refresh` call `reloadToday()`, which updates the URL and runs
  `loadTodayV2`. Export `reloadToday` for the hooks below.

### `home.js` (small refactors; v1's behaviour is unchanged)
- `homeTrend(data, reload = loadHome)`: the 6/12 buttons call `reload()`.
- Pull `renderNetWorth`'s panel building into `familyWorthPanel(worth)`, which returns the panel. `renderNetWorth`
  calls it and still sets `id="family-net-worth"`.

### Hooks that reload Home
Each of these reloads the v1 or v2 screen, whichever is shown:
- `app.js:332`, `inventory.js:40` and `profiles.js:372`: when the route is `home`, call
  `uiV2Screens.includes("home") ? reloadToday() : loadHome()`. In inventory.js the v1 branch stays
  `renderHomeExtras()`.
- `assistant.js:45`: read `$("today-month")` instead of `$("home-month")` when v2 Today is on.

### `shell.js`
- `showRoute`: `document.title` uses `(v2 || ROUTES[route.name]).title`.

### `app.js` (loadSettings, after `uiV2Screens` is set)
- `#nav-home .nav-label` text, and the link's `title`, become "Today" when `uiV2Screens.includes("home")`, otherwise
  "Home".

### `index.html`
- After `#home-panel`, add:
```html
<!-- Today, redesigned (today_v2.js; docs/ui.md "Pages"), behind the ui_v2_screens flag. -->
<section id="today-panel" class="page" data-page="home" data-ui="v2" aria-labelledby="today-title" hidden>
  <header class="page-header"><div><h1 id="today-title" tabindex="-1">Today</h1><p id="today-subtitle" class="page-subtitle"></p></div>
    <div class="page-actions"><label class="inline-field">Month <input id="today-month" type="month"></label>
      <label class="inline-field">Currency <select id="today-currency" aria-label="Today's currency"></select></label>
      <button id="today-refresh" type="button">Refresh</button></div></header>
  <div id="today-state" class="page-state"></div>
  <div id="today-body" class="page-body">
    <p id="today-status" class="muted small" role="status"></p>
    <div id="today-tiles" class="today-tiles"></div>
    <div id="today-main" class="today-main"><div class="today-col"><section id="today-needs" class="today-region" aria-labelledby="today-needs-title"></section><div id="today-dated"></div></div>
      <section id="today-budgets" class="today-region" aria-labelledby="today-budgets-title"></section></div>
    <div id="today-charts"></div><div id="today-family"></div><details id="today-about" class="today-about"></details>
  </div>
</section>
```
- Subtitle text: "Your household this month." (personal) or "Your family, added up. Each person's records stay in
  their own profile." (family).
- Add `<script src="today_v2.js">` after `home.js` and before `shell.js`.

### `style.css`
Add a new block after the "Home" rules (around line 661): `/* Today v2 (today_v2.js; design-system/home-manager/pages/today.md). Tokens only. */`.

**Tiles**
- `.today-tiles`: grid, `repeat(4, minmax(0,1fr))`, gap `--space-4`, margin-bottom `--space-5`.
- `.today-tiles .figure-tile`: `min-width:0; overflow-wrap:anywhere`.
- `.figure-label` and `.figure-sub` inside the tiles: margin 0, and `.figure-sub + .figure-sub` gets margin-top
  `--space-1`.

**Main grid**
- `.today-main`: grid, `minmax(0,1.15fr) minmax(0,1fr)`, gap `--space-6`, `align-items:start`, margin-bottom
  `--space-6`.
- `.today-main.no-aside`: `grid-template-columns:minmax(0,1fr)`, and `#today-budgets` is hidden.
- `.today-col`: flex column, gap `--space-4`.

**Regions**
- `.today-region`: `--surface`, a 1px `--border`, `--radius-lg`, padding `--space-4 --space-5`, `min-width:0`.
- `.today-region > h2`: `--text-lg`, margin `0 0 --space-3`, flex with gap `--space-2`, align-items center.

**Needs you**
- `.needs-list`: list-style none, margin 0, padding 0, flex column, gap `--space-1`.
- `.needs-row`: grid `20px minmax(0,1fr) auto`, gap `--space-3`, align-items center, padding `--space-3 --space-4`,
  `--radius-md`.
- `.needs-row + .needs-row:not(.attention)`: a 1px `--border` top border.
- `.needs-row.attention`: background `--warning-subtle`.
- `.needs-icon`: 20px wide and high; `--warning` in `.attention`, `--text-muted` otherwise.
- `.needs-row strong`: `--text-md`, 600.
- `.needs-row small`: block.
- `.needs-action`: the text-link style (accent 550, underlined on hover), `white-space:nowrap`.

**Dated sections**
- `.dated-list`: list-style none, margin 0, padding 0.
- `.dated-row`: grid `88px minmax(0,1fr) auto`, gap `--space-3`, padding `--space-2 0`, and a 1px `--border` top
  border between rows.
- `.dated-when` and the amount: tabular-nums, `--text-sm`.
- `.today-footer`: block, margin-top `--space-3`.

**Budgets**
- `.today-budget`: flex column, gap `--space-2`, padding `--space-3 0`, and a 1px `--border` top border between rows.
- `.today-budget-head`: flex, gap `--space-2`, align-items center.
- `.today-budget-left`: margin-left auto, tabular-nums.
- `.today-budget-left.over`: color `--warning`, 600.

**About and responsive**
- `.today-about > summary`: cursor pointer, color `--accent`, weight 550 (copy `.taxes2-about`).
- `@media (max-width:1099px)`: `.today-tiles` becomes `repeat(2, …)` and `.today-main` one column.
- `@media (max-width:599px)`:
  - `.today-tiles` gap `--space-2`;
  - tiles padding `--space-3 --space-4`;
  - `.today-tiles .figure-button[data-size="lg"]` `font-size: var(--text-lg)`;
  - the second `.figure-sub` is hidden; the first stays;
  - `.dated-row`: `grid-template-columns: 72px minmax(0,1fr)`, with the amount on its own line
    (`grid-column: 2`).

### Other files
- `.claude/skills/ui-redesign/scripts/ui_shots.py` `seed()` adds:
  - checking and card statements (SQL as in `tests/test_forecast.py:147`): checking `period_end` 5 days ago,
    closing 8,412.30; card `period_end` 60 days ago, so it's stale;
  - a verified car asset and a loan (`Assets.add`, as in `test_forecast.py:160`);
  - one confirmed recurring bill due in 10 days, using the helper `tests/test_recurring_bills.py` uses to confirm one;
  - spending in each of the two previous months, so the trend has bars.
- `tests/test_ui_parity.py`:
  - Add `pytest.param("home", "home")` to `MIGRATED`.
  - Add `NEW_ON_V2 = {"home": ("worth.today", "budget.remaining", "budget.projected")}`. Figures whose ref starts with
    one of these are checked against their trace only and skip the old-screen comparison, because v1 never showed them.
  - Change `missing` to skip them (`ref.startswith(NEW_ON_V2.get(route, ()))`).

## Selector contract
| Selector | Used by | Keep / rename to | Test edit |
|---|---|---|---|
| `#home-panel`, `#home-content`, `#home-month`, `#home-currency-select`, `#home-refresh`, `#home-error`, `#home-status`, `#home-extras`, `#home-subtitle`, `#home-title` | test_home_browser, test_shell_browser, test_ui_parity, test_trace_components_browser, test_recurring_bills, test_family_browser, test_investments; home.js, assistant.js | Keep. They're all v1; v2 uses new `today-*` ids. | none |
| `.home-metric`, `.home-figure` | test_home_browser:53, test_family_browser:72/77/100 | Keep (v1) | none |
| `.home-trend`, `.home-donut`, `.home-legend`, `.home-range`, the "12 months" button | test_home_browser | Keep, and v2 reuses them through `homeTrend` and `homeCategories` | none (the new test asserts them in `#today-panel`) |
| `#family-members`, `#family-net-worth` | test_family_browser:75–78, home.js `renderNetWorth` | Keep for v1; v2 uses `#today-family-members` and `#today-family-worth` to avoid duplicate ids | none |
| `#nav-home` | test_home_browser:63 | Keep the id; the label text changes only with v2 on | none |
| "CDs and Treasuries coming due" text | test_investments:360 (in `#home-content`) | Keep the text in v1, and v2 uses the same heading | none |
| `#breakdown`, `[data-figure-ref]` | test_ui_parity, test_trace_components_browser | Reused | none |

New ids and classes (the contract from now on): `#today-panel`, `#today-title`, `#today-month`, `#today-currency`,
`#today-refresh`, `#today-state`, `#today-body`, `#today-status`, `#today-tiles`, `#today-main`, `#today-needs`,
`#today-dated`, `#today-budgets`, `#today-charts`, `#today-family`, `#today-about`, `.needs-row`, `.needs-action`,
`.today-budget`, `.dated-row`.

## States
- **Loading:** `pageState`'s delayed "Loading today …" line.
- **Error:** `pageState`'s error with Retry. The body is hidden, so there are never mixed figures, matching the "one
  snapshot" rule.
- **No library** (personal): "Set up your library to see your household" with an Open Settings link.
- **Family with no members:** the v1 empty text and "Manage family members" link in `#today-needs`, with everything
  else hidden.
- **Nothing needs you:** one muted ✓ row.
- **No budgets:** an empty state with a "Set a budget" link.
- **No balances:** the Cash tile reads "No statement balances yet", and Net worth still shows assets less loans.
- **Every dated section is empty:** `#today-dated` is empty, and only Needs you shows on the left.
- **Long text** (merchant, account or category names): `overflow-wrap:anywhere` on rows and tiles, and amounts stay
  `nowrap`.
- **Many rows:** Bills shows 3 overdue and 3 upcoming (the server caps it), maturities 3, returns and warranties 6. The
  budget list is unbounded but short.
- **Narrow screen:** 2×2 tiles, one column, dated rows wrap.
- **Dark theme:** tokens only.
- **Family profile:** described in "Layout"; the check-in, returns, warranties and budgets are hidden.

## Accessibility
- **Focus order:** h1, Month, Currency, Refresh, the four tile figures (each Enter opens `#breakdown`, and Esc returns
  focus to the figure), the Needs you actions, the dated links, the budget links and figures, the chart controls, then
  the about summary.
- **Live regions:** `#today-status` has `role=status`; pageState handles `aria-busy` and errors.
- **Regions:** each section has `aria-labelledby` pointing at its h2 (ids `today-needs-title` and
  `today-budgets-title`, plus a generated id per dated section).
- **Color is never alone:** attention rows carry an icon plus words, stale uses the stale badge's text, overdue uses
  the `past_due` badge text, the budget state uses a badge plus "Over by" or "left" text, and meters have
  `role=img aria-label` from `meter()`.
- **Reduced motion:** nothing new animates.

## Out of scope
- v1 Home's behaviour, and deleting it (Phase 3, item 8).
- Spending, Accounts and other pages.
- The chart internals: the trend and donut are reused as they are, and their legend amounts stay text.
- Customizable panels, a month-end projection and a daily view (docs/open-work.md "UI").
- Budget editing on Today.
- Any copy not listed above.

## Verification
- `.venv/Scripts/python.exe -m pytest tests/test_traces.py tests/test_dashboard.py -q`, if that file exists.
  Otherwise run the dashboard tests that Grep finds for `dashboard(`.
- New file `tests/test_today_v2_browser.py`. Seed as `tests/test_ui_parity.py` `seeded_server` does, plus a
  40-day-old statement balance and a confirmed bill. Then `PUT /api/ui-screens {"routes":["home"]}` and check:
  - `#today-panel` is visible, its h1 says "Today", `#nav-home` says Today, and `document.title` starts "Today".
  - The four tile figures show, and Spent contains "149.00 USD".
  - Clicking Cash opens `#breakdown`, which contains "over 35 days old". Esc returns focus.
  - `#today-needs` lists the review row and has no "0 " rows.
  - `#today-budgets` contains "Over by 25.00 USD".
  - At 1366×768, the first `.needs-row .needs-action`'s bottom is ≤ 768.
  - "12 months" sets `aria-pressed` and puts `months=12` in the URL, and a reload keeps it. Changing the month puts
    `month=` in the URL.
  - Routing `/api/dashboard` to 503 shows pageState's error, and Retry recovers.
  - At 390, 768 and 1440 there's no horizontal scroll.
  - Family: reuse `tests/test_family_browser.py`'s setup (its `spend()` helper and profile creation) with `home` on.
    The tiles show the family Money in, `#today-family-members` lists both people, `#today-budgets` is hidden, and the
    routing row shows.
- `$env:RUN_BROWSER_TESTS = "1"; .venv/Scripts/python.exe -m pytest tests/test_today_v2_browser.py tests/test_ui_parity.py tests/test_home_browser.py tests/test_family_browser.py tests/test_investments.py tests/test_shell_browser.py tests/test_trace_components_browser.py -q`.
  Don't run it alongside `ui_shots`.
- `.venv/Scripts/python.exe .claude/skills/ui-redesign/scripts/ui_shots.py --routes home --v2 home --full-page --out <scratchpad>/after-today`,
  plus a run without `--v2` to confirm v1 Home is unchanged apart from the new seed data. Compare against
  `before-home` at every width and theme, with no `HORIZONTAL OVERFLOW` and no page errors.
- Tab through the page, checking focus order and the visible ring.

## Docs to update
- **docs/ui.md "Pages":** add a Today v2 bullet (tiles, Needs you, dated sections, budgets, charts, family; URL
  `?month=&currency=&months=`).
- **docs/ui.md "Migration":** "Registered: `taxes`, `home`".
- **docs/money.md "Home":** add Cash and Net worth, Money in traced, and the 35-day stale rule.
- **docs/ui.md "Trace contract" / "What's built":** add `cashflow.in`.
- **docs/ui.md "Decisions" 4:** note that it is reversed for Today.
- **docs/open-work.md "UI redesign":** "Phase 2 Today is built; To check and the document page is next".
- **design-system/home-manager/README.md:** a "Phase 2, Today" section with these decisions and any deviations, plus
  the table row for `phase2-today-plan.md` and `pages/today.md`.
- **Memory** `observability-redesign-plan.md`: Today planned or built.
