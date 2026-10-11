# Wealth & plans (Phase 2)

These are the page overrides for the three Wealth & plans screens v2: Investments (`investments_v2.js`, route
`#/investments`), Forecast (`forecast_v2.js`, `#/forecast`) and What If (`whatif_v2.js`, `#/whatif`). MASTER.md wins
wherever this file says nothing. The hand-off is `../phase2-wealth-plan.md`, built in three sessions (A, B, C).

**The user's jobs** (docs/planning.md "Investments", "Forecast", "What If"):
- **Investments:** see the total invested per currency, how it splits and how fresh it is; act on what needs it (values
  in To check, the payroll-account question, the I bond yearly limit, CDs and Treasuries coming due, required
  distributions owed, unmarked 529 withdrawals, sales with no purchase lot); open one account; add an account; check
  each year's 1099/5498 boxes.
- **Forecast:** change the assumptions and see where cash and net worth end up and whether cash goes below zero; keep
  the assets and loans up to date.
- **What If:** build a plan and compare it with now; work out a paycheck; follow a saved plan.

Shared: Figure tiles, the tinted region (never nested; lists inside use 1px dividers), needs-attention rows
(`--warning-subtle`, one text-link action), tables (sticky sunken header, right-aligned amounts), 30px chips, status
badges, one primary per region. Money in is `--positive` with `+`; red never marks spending, a fall in value or a
negative forecast (cash below zero is amber with ⚠ and text). Charts: text summary, View data table, `--chart-cat-1..3`,
series 2 dashed and series 3 dotted.

## Investments (built 2026-10-11, Build A)
- **Components:** header with Show removed and **Add an account** (primary, opens `dialog#inv2-add-dialog`; field
  errors under their field). Tiles: Invested per currency (`investments.total` figure, oldest value, "N estimated" with
  the clock icon), Coming due · 90 days, Required distributions. **Needs you**: one attention row per item, each with
  one action (a link, Paid out / Renewed, or the payroll account select). **Accounts**: one table, a `tr.group-row`
  (`th scope=colgroup`, 12px semibold, `--surface-sunken`) per section; Value is an `investments.value` figure, Change a
  signed amount, Status a badge (none when verified); a pension shows its monthly income and "not counted in totals";
  removed accounts are muted. **How it splits** (two share tables) beside **Taxes for {year}** (year select in its
  heading; v1's texts).
- **Account view** (`?account=ID`): Back link, h1 = name, subline kind · institution · tax treatment, Record value
  (primary; not for a pension or a removed account). Head: the value as a large figure, "as of" and the change, and a
  badge. Tabs Overview · Holdings & lots · Activity · Settings (Activity hidden when empty, Holdings for a pension).
  Overview: facts `dl` in 2 columns, Record a value (or Pension terms), crypto tools, 529 withdrawal, Values over time.
  Holdings: holdings table (estimated values are figures), Tax lots (lot gain figure), Add a CD or Treasury, I bond
  rates. Activity: activity table and purchase confirmations. Settings: the settings form, then Remove account… (danger,
  confirm with Cancel focused).
- **Layout:** tiles `repeat(auto-fit, minmax(220px, 1fr))`. How it splits | Taxes side by side (`2fr 3fr`) when
  `#inv2-body` is at least 1000px wide (container query), stacked below. Under 700px Kind and As of fold into the
  name's second line, the facts are one column and Needs-you actions wrap under the text; under 560px Change hides,
  the tiles are one column and the header buttons full width. Tables keep a 140–150px first column and scroll inside
  `.table-wrap` rather than breaking words.
- **States:** `pageState` (loading, error with Retry). RMD and tax data fail on their own (an alert in their tile or
  region). No accounts: tiles hidden, an empty state with Add an account. Unknown account id: "That account isn't
  here" with a link back. A render that finishes after a newer one draws nothing.

## Forecast (built 2026-10-11, Build B)
See `../phase2-wealth-plan.md` "Build B".
- **Components:** an Assumptions region (`.today-region`, sticky, 340px) holding a 2×2 grid of scalars, one `details`
  per list ("Spending changes (n)", "Retirement On/Off", open when it has rows) and a full-width primary Update
  forecast; three figure tiles (`.fc2-tiles`; the third is `.figure-tile.attention` with `trending-down` when cash goes
  below zero, else a positive `check-circle` "Stays above zero"); a chip switch (`.chart-switch`, `aria-pressed`); the
  server SVG at full width, its `<desc>` as a muted line and View data table (traced cells are `size: "sm"` figures);
  folded About these numbers; Assets and loans in a region with its add form folded; folded Starting point.
- **Layout:** `340px minmax(0,1fr)` at 1100px and up; below that one column with the assumptions folded above the
  results ("Assumptions: 10 years · 2% inflation · 1 change"), tiles 2 + 1, then one column under 600px. Under 700px
  the assets table folds Kind and As of into the name line.
- **States:** `pageState` for the first load (assets + run); a failed run shows an error alert above the tiles and keeps
  the inputs; a stale run is dropped; a `role=status` line says "Forecast updated".

## What If (built 2026-10-11, Build C)
See `../phase2-wealth-plan.md` "Build C".
- **Components:** header actions (Plan select, Duplicate, Delete…, primary Save plan with `form=`); tabs Plan · Compare
  · Paycheck planner · Follow this plan (Follow hidden without a saved plan or in the family view). Plan: the inputs in
  a tinted region, each list a `.fc2-list` details with a count or On/Off; Against now (`.today-region`, sticky) with
  Try it in its heading row and three groups of Now / This plan rows (figures, `trending-down` / `check-circle` for
  cash below zero, Refund / You'd owe magnitudes for tax time), then "See the full comparison". Compare: checkbox
  chips (`:has(input:checked)` pressed), Years ahead, primary Compare. Planner: v1's form with the tax fieldsets as
  folded details, the result sticky at 440px with the take-home per paycheck at `--figure-lg` and per month beside it.
- **Layout:** Plan `minmax(0,1fr) 420px`, planner `minmax(0,1fr) 440px`; under 1100px one column with Against now and
  the planner result first. Tabs scroll inside `.tabs`.
- **States:** `pageState` for the first load; Against now's empty state until Try it, an error alert there on failure;
  Compare disabled with "Choose up to three" when nothing is chosen.

## Deviations
- **I bond warnings carry `account_id`** (`Investments.ibond_limits`: the first account holding that year's bonds), so
  the Needs-you row can say "Open account". The plan had no backend change for Build A; this one is additive.
- **Add an account's currency select** lists the home currency, USD and the currencies of accounts already here; the
  app has no other list of currencies.
- **Matured CDs only** get a Needs-you row; CDs still coming due are counted in the tile (the plan's mock showed a
  coming-due row with Paid out / Renewed, which only apply once matured).
- **How it splits | Taxes is `2fr 3fr`**, not equal halves: the seven-column tax table didn't fit half the width at 1440.
- **`MONEY2_FIELDS`** (`money_v2.js`) gained the add-account fields, so `errorField()` places their errors.
- **Forecast tile figures scale with their tile** (`clamp(--text-lg, 9cqi, --figure-lg)`): a projection like
  "−225,011.82 USD" overflowed a third of the results column at `--figure-lg`.
- **Forecast's traced table cells** are the Net worth column (Net worth chart) and the Cash column (Cash, assets and
  loans chart), the two columns `years[].traces` covers; the plan named both under the Net worth table, which has no
  cash column.
- **`chart_key(prefix, name)`** (`finance/charts.py`) slugifies the tax-buckets key, so the manager and any later
  caller share it.
- **What If reuses `.fc2-list`** for its groups; the plan named a shared `.assume-group` class, but Build B shipped
  `.fc2-list`.
- **Try it sits in Against now's heading row**, not under the results, so the focus order is inputs → Try it → the
  figures (the plan's Accessibility list).
- **The planner headline** puts per month beside the per-paycheck figure and the year under them: three columns don't
  fit 440px at `--figure-lg`.
- **What If's paycheck rows** say "Try the plan to see its take-home" before a run, instead of the raw salary.
- **The planner's error** links to To check only when the server's message is about a tax table.
