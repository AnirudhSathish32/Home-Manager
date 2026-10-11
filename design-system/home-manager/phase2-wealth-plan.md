# Redesign: Wealth & plans — Investments, Forecast, What If (phase 2)

This is one plan with three builds. **Each build runs in its own implementation session**, in the order A → B → C.
Each build is built and verified on its own, and committed on its own when the user asks. The "Shared" sections apply
to every build. At the start of Build A, copy this plan to `design-system/home-manager/phase2-wealth-plan.md`, because
the later sessions read it from there. Build A also writes `design-system/home-manager/pages/wealth.md` from the
"Design-system references" section below.

## Context
docs/open-work.md "UI redesign" item 6 says the next screens are Investments, Forecast and What If. docs/ui.md
"Redesigned navigation" groups them as **Wealth & plans**. Taxes, Today, To check, the document page and the four
Money screens are already built behind `ui_v2_screens`.

The user's jobs, from docs/planning.md "Investments", "Forecast" and "What If":
- **Investments:**
  - See the total invested in each currency, how it splits by section and tax treatment, and how fresh the values are.
  - Act on what needs them: values waiting in Review, the payroll-account question, the I bond yearly limit, CDs and
    Treasuries coming due, required distributions still owed, unmarked 529 withdrawals, and sales with no purchase lot.
  - Open one account to see its holdings, lots, history and activity, and fix its settings.
  - Add an account, and check each year's 1099/5498 boxes against what's recorded.
- **Forecast:**
  - Change the assumptions and see right away where cash and net worth end up, and whether cash ever goes below zero.
  - Keep the assets and loans that feed the forecast up to date.
- **What If:**
  - Build a plan (paychecks, set spending, changes, one-offs, cutting subscriptions, retirement) and compare it with
    now.
  - Work out a paycheck from gross pay to net pay.
  - Follow a saved plan: adopt its budgets, then see plan against actual.

What's wrong today (before screenshots, plus code read through Explore):
- **No figure on any of the three pages is traceable.** The server sends traces for the following, and the pages
  show them as plain `amount()` or hand-built `.display` text:
  - Investments: `investments.total`, `investments.value`, `investments.holding`, `investments.lot_gain`,
    `investments.rmd`, `investments.rmd_left`.
  - Forecast: `years[].traces`.
  - What If: `paycheck.net`, `paycheck.line`, `taxzen.paycheck`, `taxzen.plan`, `plan.actual`.
- **Investments:**
  - The things that need you are spread across alerts, a "Coming due" table and an RMD panel.
  - The account detail opens above the groups, mixed into the list.
  - A large "Add an account" form always sits at the bottom of the page.
  - "Current value" in the detail and the lot gains are hand-built text.
- **Forecast:**
  - The page is 4,300px tall at 1440. Five assumption lists come first, then assets, then a "Starting point" block of
    raw facts, then three full-width charts.
  - The answer (cash going below zero in April 2027) is a one-line alert above a wall of inputs.
  - The assumptions are lost on reload (docs/open-work.md "Filters lost on reload").
  - Every chart's SVG uses the ids `t`/`d`, so they repeat across charts.
  - Series are told apart by hue alone.
- **What If:**
  - One 3,500px stack: plan form, compare, then a 35-field paycheck planner.
  - "Follow this plan" is hidden unless a plan is open.
  - The paycheck summary repeats the raw input ("104000 a year").
- **All three:** the global reconcile prompt sits above the h1. That's out of scope here.

## Before screenshots
Taken 2026-10-11 into `C:\Users\Anirudh\.claude\jobs\2d4dc512\tmp\before-wealth\`, a scratch folder that may be gone
by the time you read this. The useful files are `investments-1440-light.png` (empty state only),
`forecast-1440-light.png`, `whatif-1440-light.png` and their 390 and dark versions. **The default seed has no
investment accounts and no saved plans**, so each build first extends the seed (Shared › Seeding). Each build then
re-takes its own before shots, with the flag off:
`.venv/Scripts/python.exe .claude/skills/ui-redesign/scripts/ui_shots.py --routes <route> --full-page --out <scratch>/before-<route>`.

## Design-system references
MASTER.md applies unchanged. The sections used:
- **"Components":**
  - Figure tile, and the tinted region (never nested; lists inside it use 1px dividers).
  - Needs-attention row (`--warning-subtle` when it needs you, one text-link action).
  - Table (sticky `--surface-sunken` header, 40px rows, right-aligned amounts with a fixed sign slot).
  - Chips: 30px pills; pressed is `--accent-subtle` with an `--accent` border.
  - Status badge, and buttons (one primary per region).
- **"Layout":**
  - Page header: h1, a muted subline, actions on the right, one primary.
  - The shared `#breakdown` panel.
- **"Meaning is fixed":**
  - Money in is `--positive` with `+`, money out is `--text` with `−`. Red never marks spending, a fall in value,
    or a forecast going negative: cash below zero is **amber** (it needs you), with ⚠ and text.
- **Charts:** docs/ui.md "Conventions" › Charts. Each chart has a text summary and a **View data table** control,
  and its colors come from `--chart-cat-1..3`. Following Pro Max's chart guidance ("never distinguish series by hue
  alone"), series 2 is dashed and series 3 is dotted, and the end labels stay.

`pages/wealth.md` is new. Build A writes it in the same shape as `pages/money.md`: the user's jobs above, then
Components, Layout, States and Decided for each screen, copied from this plan. Decided on 2026-10-11:
- An Investments account opens in its own view (`?account=`) with Back and four tabs.
- Forecast puts the assumptions in a column beside the results, with one chart and a three-way switch. The
  assumptions live in the URL.
- What If uses tabs: Plan · Compare · Paycheck planner · Follow this plan.

Deviations: none from MASTER. The changes from v1 behaviour are listed per build. They are figures instead of plain
amounts, the URL keeping the forecast's assumptions, and dashed and dotted chart series. The dashes are a CSS change
on the shared `c-line-*` classes, so the v1 charts get them too.

## Tokens
No new tokens are needed. The tokens used are:
- Surfaces and borders: `--canvas`, `--surface`, `--surface-sunken`, `--border`, `--border-strong`.
- Text: `--text`, `--text-secondary`, `--text-muted`.
- Accent: `--accent`, `--accent-subtle`, `--on-accent`.
- Status: `--positive`, `--warning`, `--warning-subtle`, and `--danger` (only for Remove account and for past-due
  badges through STATUS).
- Charts: `--chart`, `--chart-track`, `--chart-cat-1..3`, `--chart-grid`, `--chart-baseline`.
- Scales: `--space-*`, `--radius-*`, `--text-*`, `--figure-lg`.

Every pair is already in MASTER "Checked contrast". No hex values outside `:root`.

**Icons:** `plus`, `chevron-left`, `arrow-up` and `arrow-down` already exist (Money Build A). Add **one** to `ui.js`
`ICONS`: `trending-down` (Lucide `["M22 17 13.5 8.5 8.5 13.5 2 7","M16 17h6v-6"]`), for the "Cash goes below zero"
tile and row.

---

## Shared (applies to every build)

### Registration pattern (copy month_v2.js)
- **Files:** one per screen, loaded with `defer` in `index.html` after `accounts_v2.js` and before `shell.js`:
  `investments_v2.js` (A), `forecast_v2.js` (B), `whatif_v2.js` (C). **Add every new static file to `api.py`'s static
  allowlist**, or it returns 404.
- **Registration:** `V2_SCREENS.<route> = {title, show: route => load…V2(route.params)}` for the routes
  `investments`, `forecast` and `whatif`, with the titles "Investments", "Forecast" and "What If".
- **Section markup:** `<section id="<prefix>-panel" class="page" data-page="<route>" data-ui="v2" aria-labelledby="<prefix>-title" hidden>`
  goes right after its v1 twin. Inside it:
  - `header.page-header` (h1 `tabindex="-1"`, `p.page-subtitle`, `div.page-actions`);
  - `div#<prefix>-state.page-state`;
  - `div#<prefix>-body.page-body`.

  The prefixes are `inv2`, `fc2` and `wi2`. **Never reuse a v1 id**; v1 stays until item 8.
- **`show`:**
  - Parses and validates its URL params into a module state object.
  - Sets the controls.
  - Returns `pageState($("<prefix>-state"), render…V2, {loading, what, needsLibrary: !familyMode, content: [$("<prefix>-body")]})`.
- **URL writes:** `history.replaceState` with only non-default params, setting `currentRoute.params` when
  `currentRoute?.name === "<route>"`, as `month_v2.js` does.
- **Tabs** (A's detail and C) use the Taxes v2 tab markup and `wireTabs` (`app.js`). That's a `div.tabs[role=tablist]`
  of `button[role=tab]` with `aria-controls` and roving tabindex, panels `[role=tabpanel]` that draw on first show, and
  `?tab=` in the URL.
- **Display rules:**
  - Amounts go only through `amount()`/`figure()`, and dates through `dateText()`/`dateDisplay()`/`monthText()`.
  - Status goes through `statusBadge()`.
  - **No arithmetic.** A sign test like `fig.minor < 0` to pick an icon is allowed, sums are not, and counts of
    rows are allowed.
  - Percentages are the server's `*_percent` text.
  - Long text wraps (`overflow-wrap:anywhere`); amounts never wrap (`white-space:nowrap`).
- **Figures without a figure object:** some traces arrive as a separate ref beside a display string (Forecast
  `years[]`, What If `runs[].years[]`, `paycheck.traces`). Build the figure as
  `{display: <the display string>, trace: <the ref>}` and pass that to `figure()`. That's not arithmetic.
- **Family:** `whatif` is in `FAMILY_ROUTES`; `investments` and `forecast` aren't (family mode redirects them, so
  they need no family code).

### Reused helpers (don't re-create)
- **`ui.js`:** `amount`, `dateText`, `monthText`, `dateDisplay`, `statusBadge(status, prefix, label)`, `emptyState`,
  `alertBox`, `pageState`, `confirmAction`, `categoryLabel`, `icon`, `menu`, `technicalDetail`.
- **`trace.js`:** `figure(fig, {size, signed, magnitude})` and `openBreakdown`.
- **`app.js`:** `element`, `cell`, `wireTabs`, `notice`.
- **`finance.js`:** `asyncButton`, `todayIso`.
- **`money_v2.js`:** `errorField()`, which puts a FastAPI validation error under the field it names.
- **CSS from `today_v2.js` and `month_v2.js`:** `.figure-tile`, `.figure-label`, `.figure-sub`, `.today-region` (the
  tinted region), `.needs-row(.attention)`, the chips (`.chip[aria-pressed]`), and Taxes v2's `.tabs`.

### Seeding (`.claude/skills/ui-redesign/scripts/ui_shots.py`)
Each build adds its own seeding to `seed()`, using synthetic data only, and re-runs the `home,spending` shots once to
confirm they show no page errors.
- **A:** `seed_investments(manager)` follows `tests/test_investments.py:274-305`, except that the RMD person is left
  out because the seed's birth year 1985 belongs to Taxes. It adds:
  - a Work 401(k) of 60,000 (Fidelity);
  - an Ally CD account with a 12-month CD maturing 30 days from today;
  - the Rollover IRA statement with VTSAX (80 shares, cost 8,000.00, so a gain) and a CD holding, plus one
    contribution;
  - TreasuryDirect I bonds over the yearly limit;
  - a State pension;
  - a Maya 529 with an unmarked withdrawal last year;
  - a Brokerage account with one VTI holding and one tax lot;
  - a verified Chase 1099-INT for last year.
- **B:** give the seed's car loan a rate (6%) and a monthly payment (350.00). Its 0% rate makes the notes say "this
  loan never shrinks".
- **C:** create two plans with `Scenarios(store).create(ScenarioInput…)`, as `tests/test_whatif_browser.py:231` does:
  - "Tom moves to Denver": one paycheck (85,000 a year, Georgia, biweekly), set spending of rent 2,100 from next
    month, and a one-off of −3,000.00.
  - "Raise in 2027": an income change of +500 a month from Jan 2027.

### Tests (pattern)
- Each build adds `tests/test_<route>_v2_browser.py`. It uses `served()` from `tests/test_taxes_v2_browser.py` and
  the seeding recipes named per build.
- Turn the flag on with `page.request.put(f"{base}/api/ui-screens", data={"routes": [...]}, headers=…)`.
- Every test collects `pageerror`s (none allowed) and checks `NO_OVERFLOW` at 390, 768 and 1440.
- Every build that touches a v1 file also re-runs that v1 page's browser test.

---

## Build A — Investments (`#/investments`, `investments_v2.js`)

### `investments.js` refactor (keeps v1 behaviour exactly)
The v1 builders call `loadInvestments()` after saving (lines 193, 227, 389, 403, 483, 497, 536, 570, 581, 606, 627,
670, 688, 707).
- Add `let investmentsReload = () => loadInvestments();` near line 4.
- Set it back at the top of `loadInvestments`, and replace each of those calls with `await investmentsReload()`.
  `investments_v2.js` sets it to its own reload in `show`.
- Make no other change to v1. The builders use no fixed ids, so v2 calls them directly: `payrollQuestion`,
  `maturedButtons`, `investmentSettingsForm`, `investmentValueForm`, `pensionForm`, `investmentHoldings`,
  `investmentLots`, `investmentHoldingForm`, `ibondRates`, `cryptoTools`, `educationWithdrawalForm`,
  `investmentActivity`, `investmentConfirmations`, `investmentHistory`, `shareTable`, `fillKindSelect`.
- Two builders need figures:
  - `investmentHoldings` (427): render `holding.value` with `figure(…, {size: "sm", signed: false})` when it has a
    `trace`.
  - `investmentLots` (478): put `lot_gain` in a `figure(…, {size: "sm"})` instead of `.display` text.

  `figure()` without a trace is `amount()`, so v1 only gains buttons where a trace exists. That's accepted:
  `test_investments.py` checks text, and the figure button keeps the display text.

### Data
- **List view:** one `Promise.all` of the four v1 `renderInvestments` (15) calls: `/api/investment-kinds`,
  `/api/investments[?include_archived=true]`, `/api/investments/rmd`, and `/api/investments/tax-years/{year}` (the year
  from `?year=`, default last year).
- **Detail view:** `GET /api/investments/{id}`.

### URL
`?removed=1&year=YYYY` on the list. `?account=ID&tab=overview|holdings|activity|settings&renew=H` on the detail
(`renew` as v1: open Holdings with "Add a CD or Treasury" expanded and prefilled).

### Layout at 1440×900 — list
```
Investments                                   [Show removed]  [+ Add an account]
Retirement, savings, CDs and Treasuries, I bonds, brokerage, crypto and 529s.
┌Invested, USD──────────┐┌Coming due · 90 days─┐┌Required distributions──┐
│ 182,410.00 USD (fig)  ││ 1 CD                ││ Begin in 2060 (age 75) │
│ oldest value Aug 31   ││ next Nov 10, 2026   ││ or "Left: 3 accounts"  │
│ ⚠ 2 estimated         │└─────────────────────┘└────────────────────────┘
└───────────────────────┘
Needs you  (needs-row list, each one action; hidden when empty)
 ⚠ 1 value waits in To check                                   Open To check
 ⚠ I bonds over the 10,000.00 USD yearly limit (2024)          Open account
 ⚠ Ally 12-month CD matures Nov 10                     Paid out · Renewed
 ⚠ Maya 529: a 2025 withdrawal isn't marked                    Open account
 ⚠ Which account do Acme's 401(k) contributions go to? [select] Save
Accounts                                     (one table, section rows as group headers)
 Account          Kind         Value (figure)    As of     Change      Status
 ── Retirement ──────────────────────────────────────────────────────────────
 Work 401(k)      401(k)       60,000.00 USD    Aug 31    —
 Rollover IRA     IRA          15,000.00 USD    Sep 30   +…           Needs review
 State pension    Pension      2,400.00 USD a month from Jun 2040 (not counted)
 ── Cash and savings ───── …
┌How it splits, USD───────────────┐┌Taxes for [2025 ▾]──────────────────────┐
│ By section    share table       ││ Realized gains: short · long (amounts) │
│ By tax treatment share table    ││ ⚠ sales with no purchase lot           │
└─────────────────────────────────┘│ 1099/5498 checks table                 │
                                   └────────────────────────────────────────┘
```
- **Tiles** (`.figure-tile` ×3, grid `repeat(auto-fit, minmax(220px, 1fr))`):
  - **Invested**: one tile per `totals[]` currency. `figure(total.total, {signed: false})`. Subline: "oldest value
    {dateText(oldest_as_of)}", plus "⚠ {n} estimated" when `estimated_accounts` is above 0.
  - **Coming due**: the count of `maturities` and the first one's date, or "Nothing in 90 days".
  - **Required distributions**, from `rmd`:
    - with no birth year, "Set your birth year in Settings" as a link;
    - when they begin later, "Begin in {first_year} (age {start_age})";
    - otherwise "Left this year" and the count of accounts with `left.minor > 0`, each listed in Needs you.
- **Needs you** (`.today-region` holding `.needs-row.attention` rows), in this order:
  - `awaiting_review` → `#/review`.
  - `ibond_warnings` → Open account.
  - `maturities` that need action → `maturedButtons`.
  - RMD accounts with `left > 0`: "{name}: {figure(left)} left to take by {dateText(deadline)}".
  - `education[].unmarked` → Open account `&tab=activity`.
  - `gains[].missing` → Open account `&tab=holdings`.
  - `payroll_questions`, built with `payrollQuestion()`.

  The region is hidden when it has no rows.
- **Accounts:**
  - One `.table-wrap` table. Each `sections[]` group is a `tr.group-row` (`th[colspan]`, 12px semibold secondary,
    `--surface-sunken`).
  - The name cell is a link to `?account=ID`; the whole row is clickable, but the link is the focus target.
  - Value is `figure(current.value, {signed: false, size: "sm"})`.
  - Change is `amount(change)` (signed, plain).
  - Status is `statusBadge`, and none when verified.
  - A pension row shows "{amount} a month from {monthText}" in the Value cell, and "not counted in totals" muted
    under the name.
  - A removed account (when `?removed=1`) is muted with a "Removed" badge.
- **How it splits:** `shareTable` ×2 per currency in a tinted region.
- **Taxes for {year}:** a `select[aria-label="Tax year"]` in its heading, and the body built as v1
  `renderInvestmentTaxes` (72) does, moved into a v2 function `investmentTaxesV2(data)` that writes into its own
  region. It keeps v1's texts ("Chase 1099-INT", "No account"). Gains use `amount()`; they aren't traced.
- **Two columns** (How it splits | Taxes) when the body is ≥1000px wide (container query on `#inv2-body`); stacked
  below that.

### Layout at 1440×900 — account (`?account=ID`)
```
‹ Investments
Rollover IRA                                             [Record value]
IRA · Schwab · Tax-deferred
15,000.00 USD (figure, lg)   as of Sep 30, 2026 · +500.00 since Aug 31   Needs review
[Overview] Holdings & lots  Activity  Settings
Overview:  facts <dl> (2 columns) · Record a value (inline form; pension → pension terms)
           · I bond warnings · crypto Prices and imports · 529 Record a withdrawal (details)
           · Values over time (table)
Holdings:  "Holdings on Sep 30, 2026" table (holding value figure when traced) · Tax lots (per holding,
           lot gain figure, Add lot) · details "Add a CD or Treasury" · details "I bond rates" (i_bond only)
Activity:  activity table (Not this payment, Qualified/Not qualified) · Purchase confirmations
Settings:  settings form · Remove account… (danger button, confirmAction, focus Cancel)
```
- **"Record value"** (primary) switches to Overview and focuses the value form's first input. A pension has no
  Record value; its primary is "Save terms" inside the form.
- **The header figure** is `figure(current.value, {signed: false})`. It replaces v1's hand-built "Current value"
  text, and the facts `<dl>` leaves that row out.
- **Tabs:** Activity is hidden when there are no `events` and no `confirmations`. Holdings is hidden for a pension.

### Layout at 390
- The tiles are 1 column; Needs-you rows wrap their action under the text.
- The Accounts table drops Kind and As of into the name cell's second line ("401(k) · Aug 31"), and Change is hidden
  under 560px. The table stays in `.table-wrap` with no page scroll.
- In the detail, the tabs scroll inside `.tabs` (overflow-x auto) and the facts `<dl>` is one column.

### Add an account (dialog)
- The header's "Add an account" (primary) opens `dialog#inv2-add-dialog`. It holds v1's fields with `inv2-add-*` ids
  (name, kind select from `fillKindSelect`, institution, currency **select** from the currencies the app knows, as
  This month v2's budget form does, value, as of, rate) and v1's value note.
- Submit POSTs `/api/investments` with v1's body (716-727). Field errors go through `errorField()`. On success, close
  the dialog and go to `?account=ID`.

### Changes by file
- **`index.html`:** `#inv2-panel`; `dialog#inv2-add-dialog`; the script tag.
- **`api.py`:** add `investments_v2.js` to the allowlist.
- **`investments_v2.js` (new):**
  - `loadInvestmentsV2(params)`, `renderInvestmentsV2`, `investmentTilesV2`, `investmentNeedsV2`,
    `investmentAccountsV2`, `investmentTaxesV2`;
  - `renderInvestmentAccountV2(id, tab, renew)`;
  - the add-account dialog wiring;
  - `V2_SCREENS.investments`.
- **`investments.js`:** the `investmentsReload` hook and the two figure changes above.
- **`style.css`:** a new section "Investments v2" after "Investments" (1417-1432). It holds:
  - `.inv2-tiles` grid;
  - `tr.group-row`;
  - the account header (`.inv2-account-head`: figure, as-of line and badge in a flex row that wraps);
  - `.inv2-facts` (a 2-column `dl` grid, 1 column under 700px);
  - the container query for the two-column bottom row;
  - the 390 rules above.
- **`ui.js`:** the `trending-down` icon (used in B; adding it in A keeps icons in one place).
- **`ui_shots.py`:** `seed_investments`.
- **`tests/test_ui_parity.py`:**
  - add `pytest.param("investments", "investments")` to MIGRATED;
  - add a `seed_investments(manager)` call in `seeded_server` (one 401(k) and one CD with a holding, so
    `investments.total`, `investments.value` and `investments.holding` appear on both screens);
  - re-run the other MIGRATED pairs, because Today's net worth now includes them on both sides.
- **`tests/test_investments_v2_browser.py` (new):**
  - tiles, with the Invested figure opening `#breakdown`;
  - Needs-you rows;
  - the group rows;
  - opening an account → URL `account=`, the tabs, and a holding figure;
  - a lot added from Holdings reloads v2 (not v1);
  - Not qualified on Activity;
  - Add-an-account dialog field error and success;
  - Remove account asks first;
  - `?removed=1` and `?year=` survive reload;
  - overflow at 390/768/1440.

### Selector contract (Build A)
v1 is untouched apart from the reload hook, so every v1 selector stays.

| Selector | Used by | Keep / rename | Test edit |
|---|---|---|---|
| `#nav-investments` | test_investments.py:312, test_family_browser.py:79 | keep | none |
| `#investments-summary`, `#investments-groups`, `#investments-taxes`, `#investments-rmd`, `#investment-detail`, `#investment-form`, `#investment-*` fields, `#add-investment` | test_investments.py:314-381 | keep (v1) | none |
| `get_by_role("button", name="Not qualified")`, the "Add a CD or Treasury" and "I bond rates" summaries | test_investments.py:351, 372, 388 | keep (the v1 builders v2 reuses) | none |
| new `#inv2-*` ids | test_investments_v2_browser.py | new | — |

### States
- **Loading:** `pageState`.
- **Error:** `pageState` with Retry. The RMD and tax sections fail on their own, each showing its own `alertBox`
  (as v1).
- **No accounts:** the tiles are hidden; an `emptyState` says "No investment accounts yet", with the Add an account
  button and the text "or add a statement to Receipts & statements".
- **No tax forms:** the Taxes region shows v1's sentence.
- **Removed accounts:** shown muted.
- **Unknown account id:** `alertBox` "That account isn't here" with a link back.
- **Long names:** wrap.
- **Many accounts:** the table grows; the header doesn't stick (the page scrolls).
- **Dark theme:** tokens only.

### Accessibility
- **Focus order:** h1 → header actions → tiles' figures → Needs-you actions → table links → bottom regions.
- **Detail:** Back link → h1 → Record value → tabs (←/→) → the panel.
- The dialog traps focus and Esc closes it.
- Group rows are `th scope="colgroup"`.
- Status and estimated use icon + text.

### Verification (Build A)
- `$env:RUN_BROWSER_TESTS = "1"; .venv/Scripts/python.exe -m pytest tests/test_investments_v2_browser.py tests/test_investments.py tests/test_ui_parity.py -q`
- `ui_shots.py --routes investments --v2 investments --full-page --out <scratch>/after-investments`, plus
  `"investments?account=<id>"` for one account (print the seeded ids in the script, as `{receipt_doc}` is handled).

---

## Build B — Forecast (`#/forecast`, `forecast_v2.js`)

### Backend (small, two changes)
1. **`finance/charts.py`:**
   - Add a `key` argument to `line_chart(title, subtitle, labels, series, currency, key="chart")`. It uses
     `aria-labelledby="{key}-t {key}-d"` and the ids `{key}-t`/`{key}-d`.
   - `forecast_charts` passes `"fc-net-worth"`, `"fc-cash-flow"` and `"fc-balance"`.
   - `scenarios.py:216` passes `"compare-net-worth"`.
   - `tax_buckets_svg` takes `key` the same way, and the manager passes `f"tb-{part['name']}"` slugified (lower-case,
     non-alphanumerics to `-`).
   - Add one test to `tests/test_forecast.py`, next to its existing `forecast_charts` test: the three forecast
     charts' ids are distinct.
2. **Dashes:** none in the backend. In `style.css` (650), add `.c-line-2 { stroke-dasharray: 6 4; }` and
   `.c-line-3 { stroke-dasharray: 2 4; }` (the legend lines carry the same classes).

### `forecast.js` refactor (keeps v1 behaviour)
- `forecastRequest(p = "")` reads `$(p + "forecast-years")` and so on, and the retirement ids `p + "retire-*"`.
  `showRetirementFields(p = "")` does the same.
- `loadAssets(p = "")` reads and writes `p + "asset-rows"` and the `p + "asset-*"` fields. Its reload after Remove
  calls whichever loader is showing; use a `forecastReload` hook, as Build A's `investmentsReload`.
- `forecastRow` and `forecastItems` already take the list id. The "Add" button listeners and the retire and asset
  listeners move into `wireForecast(p)`, called once with `""` at load (v1) and once with `"fc2-"` from
  `forecast_v2.js`.
- The v2 markup copies v1's ids with the `fc2-` prefix: `fc2-forecast-years`, `fc2-add-one-off`,
  `fc2-forecast-one-offs`, `fc2-retire-plan`, `fc2-asset-form` and so on. The category datalist is
  `fc2-forecast-category-options`, built by `renderForecastV2`. In the v2 markup, each "Add …" spending-change row's
  `list` attribute must point at it; `forecastRow`'s field spec takes the list id from the caller, so `wireForecast(p)`
  builds the spec with `p + "forecast-category-options"`.

### URL (rule 5)
- **Scalars:** `?years=10&inflation=2&growth=0&history=6&chart=net_worth|cash_flow|balance_sheet`. Only non-default
  values are written.
- **Lists:** repeated keys built with `URLSearchParams.append`:
  - `spend=<category>~<percent>`;
  - `income=<YYYY-MM>~<amount>`;
  - `oneoff=<YYYY-MM>~<amount>~<label>`;
  - `edu=<YYYY-MM>~<amount>~<label>`;
  - `retire=<YYYY-MM>~<mode>~<amount|floor>~<tax>`.

  Split each on the first `~`s only, so the label keeps any `~`.
- `show` parses these, builds the rows (`forecastRow` and then sets the values), and runs.
- Update writes the URL, then runs. The runs keep v1's stale-drop counter.
- An invalid value is dropped silently, and the page shows defaults.

### Data
- `POST /api/forecast` with `forecastRequest("fc2-")`.
- `GET /api/assets`, through `loadAssets("fc2-")`.

### Layout at 1440×900
```
Forecast                                                        [Update forecast]
Projected from your balances, recent income and spending, and the assets below.
┌Assumptions (340px, sticky top)┐ ┌Cash, end of 2036┐┌Net worth, end of 2036┐┌Cash below zero─────┐
│ Years ahead [10] Inflation [2]│ │ −229,000.00 USD │ │ −232,000.00 USD     ││ ⚠ from Apr 2027    │
│ Income growth [0] Average [6] │ │ (figure)        │ │ (figure)            ││ (or ✓ "Stays above │
│ ▸ Spending changes  (1)       │ └─────────────────┘ │ −190,000 today's $  ││  zero" positive)   │
│ ▸ Income changes    (0)       │                     └─────────────────────┘└────────────────────┘
│ ▸ One-off amounts   (0)       │ [Net worth] [Income and spending] [Cash, assets and loans]   (chips)
│ ▸ Education costs   (0)       │ ┌chart (server SVG), legend + end labels────────────────────────┐
│ ▸ Retirement        Off       │ │                                                               │
│ [Update forecast]             │ └───────────────────────────────────────────────────────────────┘
└───────────────────────────────┘ Summary sentence (chart <desc>) · [View data table] (details)
                                  About these numbers (details, folded: notes list)
                                  Assets and loans  (table + "Add an asset or loan" details form)
                                  Starting point (details, folded)
```
- **Assumptions column:**
  - A tinted region, `position: sticky; top: var(--space-5)`, `max-height: calc(100vh - 48px)`, scrolling inside.
  - Four scalar inputs in a 2×2 grid.
  - Each list is a `details` whose summary reads "{label} ({count})" (the count is the number of rows; "Retirement"
    reads On/Off) and holds the list plus its "Add …" text button. A details opens when its count is over 0.
  - The column's footer holds the primary "Update forecast". The header's copy of it is the same button type and
    submits the same form (`form` attribute); MASTER allows one primary per region.
- **Tiles**, from the last `years[]` row `Y`:
  - **Cash, end of {Y.year}:** `figure({display: Y.display.end_cash, trace: Y.traces.end_cash})`.
  - **Net worth, end of {Y.year}:** `figure({display: Y.display.end_net_worth, trace: Y.traces.end_net_worth})`.
    Subline: `amount(Y.display.end_net_worth_today)` + "in today's dollars" (plain; it isn't traced).
  - **Cash below zero:** when `first_month_cash_below_zero` is set, `.figure-tile.attention` (`--warning-subtle`)
    with the `trending-down` icon, "From {monthText}", and the subline "Cash goes below zero; see the Cash chart."
    Otherwise a positive check icon and "Stays above zero".
- **Chart switch:** chips with `aria-pressed`, and `?chart=` in the URL. Only the selected `charts[key]` SVG is
  imported (v1's `forecastSvg`).
  - Under it: the SVG `<desc>` text as a muted paragraph, and `details` "View data table" holding v1's
    `forecastTable(years, key)` for that chart.
  - In the Net worth table's End cash and End net worth columns, each cell is a `figure(…, {size: "sm"})` built from
    `years[i].traces`.
- **About these numbers:** a `details` with `notes` as a list. The "below zero" alert moves to the tile.
- **Assets and loans:** a heading, a muted one-line explainer (v1's), the table built by `loadAssets("fc2-")`, and a
  `details` "Add an asset or loan" holding the form (`fc2-asset-*`).
- **Starting point:** a `details`, folded, holding v1's `#forecast-start` content rebuilt into `fc2-start`. It keeps
  "Required distributions" and the retirement sentence (`retirementFacts`, reused). Category names go through
  `categoryLabel()`.

### Layout at 768 and 390
- **Under 1100px,** the Assumptions column stops being sticky and sits **above** the results as a `details` "Assumptions:
  10 years · 2% inflation · 1 change" (open by default when the URL has no params; folded otherwise). The tiles go
  2 + 1, then 1 column under 600px.
- **Chart:** the SVG scales (`width:100%`). The chips wrap.
- **Assets table:** Kind and As of fold into the name line under 700px.

### Changes by file
- **`index.html`:** `#fc2-panel` with the assumptions form (`fc2-forecast-form`), a results host, and the script
  tag.
- **`api.py`:** the allowlist.
- **`forecast.js`:** the prefix and reload refactor above.
- **`forecast_v2.js` (new):** `loadForecastV2(params)`, `forecastParamsV2` (parse and write), `renderForecastV2`,
  `forecastTilesV2`, `forecastChartV2`, `V2_SCREENS.forecast`.
- **`style.css`:**
  - the dash rules (650);
  - a new section "Forecast v2" with `.fc2-layout` (grid `340px minmax(0,1fr)`, gap `--space-6`, one column under
    1100px), `.fc2-assumptions` (sticky), `.fc2-tiles`, `.figure-tile.attention`, `.chart-switch` (chips row), and the
    table folding rules.
- **`ui_shots.py`:** the car loan's rate and payment.
- **`tests/test_ui_parity.py`:** add `pytest.param("forecast", "forecast")`, and
  `NEW_ON_V2["forecast"] = ("forecast.cash", "forecast.net_worth")`. v1 showed these only inside folded tables.
- **`tests/test_forecast_v2_browser.py` (new):**
  - tiles and their breakdowns;
  - below-zero tile on the seed;
  - chart switch → `?chart=` and the SVG changes;
  - View data table;
  - one-off added → Update → URL has `oneoff=` → reload restores the row and the result;
  - retirement fields toggle;
  - asset add and remove (confirm) reloads v2;
  - the chart ids are unique in the document (`document.querySelectorAll('[id$="-t"]')` has no duplicates);
  - overflow at 390/768/1440.

### Selector contract (Build B)
| Selector | Used by | Keep / rename | Test edit |
|---|---|---|---|
| `#nav-forecast`, `#asset-rows`, `#asset-name/value/kind/rate/payment`, `#add-asset`, `#forecast-years`, `#add-one-off`, `#forecast-one-offs input[...]`, `#run-forecast`, `#forecast-charts svg/details/table`, `#forecast-alerts`, `#retire-*`, `#forecast-start` | test_forecast.py:246-286 | keep (v1, unchanged ids) | none |
| SVG `#t`/`#d` | nothing in tests | becomes `{key}-t`/`{key}-d` | none (new test asserts unique) |
| new `#fc2-*` | test_forecast_v2_browser.py | new | — |

### States
- **Loading:** `pageState`. An Update while a run is pending drops the stale result.
- **Error:** an error from the run shows in an `alertBox` above the tiles and keeps the inputs.
- **No ledger data:** the tiles show what the server returns; the Starting point explains it.
- **Assets:** an empty table shows "No assets or loans yet" (v1's text).
- **Long category labels and notes:** wrap.
- **100 years:** the data table scrolls inside `.table-wrap`.
- **Dark theme:** the `c-*` classes already use tokens.

### Accessibility
- **Focus order:** h1 → Update (header) → assumptions → tiles → chips → View data table → About → Assets → Starting
  point.
- **Chips:** `aria-pressed`.
- **Charts:** each SVG keeps `role=img` with unique `aria-labelledby`.
- **Live region:** a `role=status` line announces "Forecast updated" after a run.
- **Below-zero tile:** icon + text, not color alone.
- **Reduced motion:** nothing animates.

### Verification (Build B)
- `$env:RUN_BROWSER_TESTS = "1"; .venv/Scripts/python.exe -m pytest tests/test_forecast_v2_browser.py tests/test_forecast.py tests/test_ui_parity.py tests/test_whatif_browser.py -q`.
  The What If test is included because `scenarios.py`'s chart changed.
- `ui_shots.py --routes forecast --v2 forecast --full-page --out <scratch>/after-forecast`.

---

## Build C — What If (`#/whatif`, `whatif_v2.js`)

### `whatif.js` refactor (keeps v1 behaviour)
This is the same technique as B, at a larger scale:
- **Prefix:** a module `let wi = {p: ""};`. Every `$("…")` of a page id becomes `$(wi.p + "…")`. That covers
  `plan-*`, `paycheck-*`, `run-paycheck`, `scenario-*`, `compare-*` and `track-*`. The dynamic ids
  `plan-{i}-*`, `bonus-*-N`, `{list}-{key}-N` and `compare-{value}` get the prefix too.
- **Wiring:** the top-level listeners move into `wireWhatIf(p)`, called with `""` at load and with `"wi2-"` from
  `whatif_v2.js`. Each handler sets `wi.p = p` before running, so a handler always works on its own screen.
- **Entry points:** `loadWhatIf` sets `wi.p = ""`; `loadWhatIfV2` sets `"wi2-"`.
- **Money:** add `const wiMoney = (fig, opts) => wi.p ? figure(fig, opts) : amount(fig, opts);`. Use it where the
  data is traced:
  - the paycheck's tax lines (`paycheck.line`), in `planTableRow`;
  - the headline take-home per check and per month, built from `paycheck.traces` as `{display, trace}`;
  - Compare's Tax Zen (`runs[].tax_zen`);
  - the runs' paychecks (`net_per_check`, `net_monthly`);
  - the by-year end cash and net worth (`years[].traces`);
  - plan-vs-actual (`pay[].rows[].planned/average/difference`, `spending[].planned/actual`,
    `spending[].rows[].actual/difference`).

  v1 renders exactly as today.
- **Sentences:** the hand-built sentences in v2 become an amount or figure followed by text:
  - `${actual} spent of ${planned} planned` becomes `[figure actual] spent of [figure planned] planned`;
  - the paycheck summary uses the server's `net_per_check` display when a run exists. The raw "104000 a year" stays
    in v1, whose test asserts it.

  These are built in the shared functions under `if (wi.p)`.

### Markup
`#wi2-panel` copies v1's form markup (index.html 259-398) with every id prefixed `wi2-`. Its regions are rearranged
into tab panels:
- **Header:**
  - h1 "What If", subline (v1's).
  - `div.page-actions`: a `wi2-scenario-select` (label "Plan"), the text buttons Duplicate and Delete…
    (`wi2-scenario-duplicate`, `wi2-scenario-delete`), and the primary "Save plan" (`wi2-scenario-save`, with
    `form="wi2-scenario-form"`).
- **Tabs:** Plan · Compare · Paycheck planner · Follow this plan. Follow this plan shows only when a saved plan is
  open and the view is personal (`renderTracking`'s rule).
- **URL:** `?plan=ID|new&tab=plan|compare|planner|follow&stub=ID`. `stub` opens the planner tab, as v1 does.

### Layout at 1440×900 — Plan tab
```
What If     Plan [Tom moves to Denver ▾]  Duplicate  Delete…          [Save plan]
Try money plans before they're real …
[Plan] Compare  Paycheck planner  Follow this plan
┌Plan inputs (minmax 0, 1fr)──────────────────┐ ┌Against now (420px, sticky)──────────┐
│ Name [Tom moves to Denver] Start from [▾]   │ │ Net worth, end of 2036              │
│ Years [10] Inflation [2] Income growth [0]  │ │  Now          −232,000.00 (figure)  │
│ ▸ Paychecks (1)   Tom · 2,706.71 a check    │ │  This plan    −198,400.00 (figure)  │
│ ▸ Set spending (1)                          │ │ Cash below zero  Now: Apr 2027      │
│ ▸ Spending changes (0)                      │ │                  Plan: never ✓      │
│ ▸ Subscriptions  Off                        │ │ Tax time  Now: refund +420 (figure) │
│ ▸ One-off amounts (1)                       │ │           Plan: owe 180 (figure)    │
│ ▸ Retirement     Off                        │ │ [Try it]  (= v1 Compare with now)   │
└─────────────────────────────────────────────┘ └─────────────────────────────────────┘
```
- **Plan inputs:** the same `details`-with-count pattern as Forecast's assumptions. The Paychecks summary lists each
  paycheck's label and, after a run, its take-home.
- **"Against now":**
  - It is the result of `#wi2-scenario-try` (v1's `#scenario-try`: `POST /api/scenarios/compare {draft,
    include_now: true, years}`).
  - It shows the last `years[]` of both runs as figures, `first_month_cash_below_zero` for each, and each run's
    `tax_zen` as a figure. A Tax Zen figure takes `{magnitude: true}` with its label "Refund"/"You'd owe", as on
    Taxes v2.
  - Its button is "Try it" (secondary). Before the first run it shows an `emptyState`: "Try the plan to see it
    against now."
  - The plan's full detail (chart, by-year tables, each run's notes) goes to the Compare tab with a link "See the
    full comparison".

### Compare tab
- **Selection:** "Show, up to three" chips (`wi2-compare-now`, `wi2-compare-{id}`, using v1's checkbox logic, styled
  as chips with the checkbox kept for the test contract), Years ahead, and Compare (primary).
- **Result:** the SVG (`compare-net-worth` ids), its `<desc>` text, `details` "View data table", the Tax Zen list,
  and `details.compare-run` per run (v1's `compareRun`, with figures through `wiMoney`).

### Paycheck planner tab
- v1's two-column `.whatif-layout`: the form (`wi2-paycheck-form`) at `minmax(0,1fr)` and the result
  (`wi2-paycheck-result`) at 440px, **sticky** (`top: var(--space-5)`) so it stays beside the inputs at 1366×768.
- **Form:** the federal and state fieldsets become `details` (folded; open when any field has a value).
- **Result:** the headline "Take-home per paycheck" is `figure()` at `--figure-lg`, with per month beside it. Then
  the rate text, Tax Zen text, the table (tax lines as figures), the schedule and the jurisdictions (v1's builders).
- **Footer:** "Work it out" (primary) and "Add to plan" (secondary) stay.

### Follow this plan tab
v1's `#track-panel` content with `wi2-track-*` ids:
- the status line;
- the month input and Preview, giving the budgets table and "Set N budgets and follow this plan";
- Stop following (confirm);
- the plan-vs-actual tables, with figures.

The tab is hidden in the family view and when no saved plan is open.

### Layout at 390 and 768
- **Header:** the plan select and its buttons wrap under the h1, and Save plan stays the last header item.
- **Tabs:** scroll horizontally inside `.tabs`.
- **Columns:** under 1100px, "Against now" and the planner's result move **above** their forms (no longer sticky).
- **Tables:** stay in `.table-wrap`.

### Changes by file
- **`index.html`:** `#wi2-panel` (above), and the script tag.
- **`api.py`:** the allowlist.
- **`whatif.js`:** the prefix, wiring and `wiMoney` refactor.
- **`whatif_v2.js` (new):** `loadWhatIfV2(params)`, the tab wiring, `renderAgainstNowV2(result)`,
  `V2_SCREENS.whatif`.
- **`style.css`:** a section "What If v2" with `.wi2-plan-layout` (grid `minmax(0,1fr) 420px`, one column under
  1100px with the result first via `order`), the sticky result, the details summaries with counts (shared with fc2:
  name the class `.assume-group`, defined in Build B and reused here), and the compare chips.
- **`ui_shots.py`:** the two plans. Add a `{plan}` route placeholder (the first plan's id) so `"whatif?plan={plan}"`
  works.
- **`tests/test_whatif_v2_browser.py` (new):**
  - with the flag on, `?plan=` opens the plan;
  - tabs and `?tab=` survive reload;
  - Try it fills "Against now" with figures that open `#breakdown`;
  - Compare with Now and the plan shows the chart and runs;
  - the planner works a paycheck and its headline figure opens a `paycheck.net` breakdown;
  - at 1366×768 `#wi2-paycheck-result`'s top is in view beside the form (x > 600);
  - Follow this plan: preview → Set budgets → status → actual tables (reuse `test_following_a_plan`'s seeding);
  - Delete… asks first;
  - the family view hides Follow this plan (seed a family as `tests/test_family_browser.py` does);
  - overflow at 390/768/1440.
- **No MIGRATED pair.** Its figures appear only after actions; say so in docs/ui.md "Migration", as Transactions does.

### Selector contract (Build C)
| Selector | Used by | Keep / rename | Test edit |
|---|---|---|---|
| Every v1 id in test_whatif_browser.py:48-259 (`#paycheck-result`, `.plan-figure`, `#plan-*`, `#add-plan-*`, `.plan-line`, `#plan-bonuses .quiet`, `#scenario-*`, `#compare-*`, `.compare-run`, `svg.forecast-chart`, `#track-*`, `#confirm-accept`, the role buttons "Open in planner" and "Set 2 budgets and follow this plan") | test_whatif_browser.py | keep: v1 is unchanged with `wi.p = ""` | none |
| `.plan-figure`, `.plan-line`, `.compare-run`, `.scenario-paycheck`, `.forecast-row` classes | v1 and v2 builders | keep (the shared builders) | none |
| new `#wi2-*` | test_whatif_v2_browser.py | new | — |

### States
- **New plan:** the form is empty and "Against now" shows its empty state.
- **No plans:** the select shows "New plan" only.
- **Tax tables not confirmed:** the planner shows v1's error in `#wi2-paycheck-error` and a link to Review.
- **Compare with nothing selected:** the Compare button is disabled, with a muted note "Choose up to three".
- **Errors:** a failed save or compare shows an `alertBox` in its region and keeps the inputs.
- **Family:** bases are family or blank; there's no Follow tab, no 401(k)/HSA selects, and Tax Zen shows its "not
  ready" note.
- **Long plan names:** wrap in the select's options and in the header.
- **Dark theme:** tokens only.

### Accessibility
- **Focus order:** h1 → plan select → Duplicate → Delete… → Save plan → tabs → the panel.
- **Inside Plan:** inputs → Try it → Against now's figures.
- Tabs use ←/→.
- Each live result region (`wi2-paycheck-result`, Against now, `wi2-compare-result`) is `aria-live="polite"`.
- Delete focuses Cancel.
- Figures say "show how it's worked out".

### Verification (Build C)
- `$env:RUN_BROWSER_TESTS = "1"; .venv/Scripts/python.exe -m pytest tests/test_whatif_v2_browser.py tests/test_whatif_browser.py -q`
- `ui_shots.py --routes "whatif,whatif?plan={plan},whatif?plan={plan}&tab=planner" --v2 whatif --full-page --out <scratch>/after-whatif`

---

## Out of scope (all builds)
- The global `#reconcile-prompt` above every page (shell; its own session).
- Deleting v1 loaders and CSS (item 8). v1 must keep working unchanged; that's why each refactor uses a prefix.
- **Backend:** nothing beyond the chart `key` argument. Raw-input display text the server doesn't format stays as it
  is: the paycheck summary in v1, and the asset rate as `${annual_rate_percent}%`.
- **Item 7** (surfacing backend-only features), Inventory, Processing, Settings, Search, Ask, and the dark `chart-seq`
  ramp.
- Retirement withdrawals on Investments: they live in Forecast and What If, as today.
- Copy not listed here.

## Verification (every build, besides its own list)
- Run only the files listed for the build (memory: targeted test runs), plus the v1 page test whose JS was refactored.
- Take after screenshots and compare them with the before ones at 390/768/1440, light and dark. The script must
  print no `HORIZONTAL OVERFLOW` and no page errors.
- **docs/ui.md "Verifying a layout":** the scrollWidth check at 390/768/1440. C adds the in-view assertion for the
  planner result at 1366×768.
- **Keyboard:** tab through the page and check the focus ring is visible and the order matches the build's
  Accessibility list.
- **Hex and inline styles:** no hex outside `:root` (Grep `#[0-9a-fA-F]{3,6}` in the new CSS section), and no inline
  `style=`.

## Docs to update
Each build updates these in the same change:
- **docs/ui.md "Pages":** a "Wealth & plans v2" bullet with a sub-bullet per screen (design in
  `design-system/home-manager/pages/wealth.md`, plan in `phase2-wealth-plan.md`).
- **docs/ui.md "Migration":** add to the registered list. Investments and Forecast have MIGRATED pairs; What If
  doesn't, and the bullet says why.
- **docs/ui.md "Conventions" › Charts:** add that series 2 and 3 are dashed and dotted (B).
- **docs/planning.md** "Investments", "Forecast" and "What If": one line each pointing to the v2 screen. For B, add
  that the forecast's assumptions live in the URL. Then remove "the Forecast assumptions" from docs/open-work.md
  "Filters lost on reload".
- **docs/open-work.md "UI redesign":**
  - Record each build as done, and name its v1 loader for item 8: `investments.js` `loadInvestments`,
    `renderInvestments`, `renderInvestmentDetail`; `forecast.js` `loadForecast`, `renderForecast`; `whatif.js`
    `loadWhatIf`, and the `wi.p` prefix, which collapses once v1 goes.
  - Remove Investments, Forecast and What If from item 6's list.
- **`design-system/home-manager/pages/wealth.md`:** written in A. B and C fill in their sections if anything changed
  while building.
- **Memory:** update `observability-redesign-plan.md`'s line in MEMORY.md as each build lands.
