# Home Manager design system: where things stand

This folder holds the redesign's visual decisions. Start here when you pick the redesign up again.

| File | What it is |
|---|---|
| `MASTER.md` | **The approved design system** (direction C · Family). Tokens, type, spacing, components, and decisions for later screens. It wins over the preview. |
| `phase0-directions.html` | The Phase 0 preview: the three directions (A · Ledger, B · Household book, C · Family) on Today and Transactions, light and dark, synthetic data. Open it in a browser. It loads fonts from Google Fonts, so it's a throwaway page outside the app's CSP. Also published at https://claude.ai/artifact/55gpu4BBFRmHy7nLUkSE7e. |
| `pages/<page>.md` | One per Phase 2 screen: `pages/taxes.md`, `pages/today.md`. |
| `phase1a-plan.md` | The Phase 1a hand-off (2026-10-10), **built 2026-10-10**. Kept as the record of what 1a covers. |
| `phase1b-plan.md` | The Phase 1b hand-off (2026-10-10), **built 2026-10-10**. Kept as the record of what 1b covers. |
| `phase2-taxes-plan.md` | The Phase 2 Taxes hand-off (2026-10-10), **built 2026-10-10**. Kept as the record of what it covers. |
| `phase2-today-plan.md` | The Phase 2 Today hand-off (2026-10-10), **built 2026-10-10**. Kept as the record of what it covers; `pages/today.md` has the page's design. |

## Phase 0 (done 2026-10-06)

**How it went:**
- **Your preferences:** a spread of three looks, balanced density, light and dark weighted equally, and Pro Max picking
  the fonts.
- **References:** you like Stripe best, especially its ledger, and Copilot Money's per-budget "how it's worked out".
  You dislike Monarch and Excel-style spreadsheets.
- **Pro Max** gave generic or marketing results (glassmorphism, hero/CTA layouts, handwriting fonts, a green accent).
  Only the palette and font ideas were kept; MASTER.md "Pro Max input" lists what was dropped and why.
- **Your verdict:** "Layout C is the best one by far", with no changes to the visual language.

**Changed after the preview** (MASTER.md wins over the preview):
- `--text-muted` light became `#636B7B` (it was `#687080`, 4.29:1 on sunken).
- The bar colors became `--chart` `#3B6FDB` on `--chart-track` `#E4EBFA` (the preview's 2.35:1 fails the 3:1 rule).
- The preview's Today layout was a **placeholder** for showing the look. Only the two decisions below are real.

**Your decisions for Today** (also in docs/open-work.md "UI redesign" 6 and MASTER.md "Decided for later screens"):
1. **Budgets on Today in the breakdown style.** Each category line gets a budget meter, not a running total.
   - On track: blue fill.
   - Ahead of pace (spent a larger share than the share of the month gone): amber.
   - Over: full bar, amber, ⚠ and "Over by $12".
   - **Never red.** You chose to keep "red never means spending".
   - The backend already returns all of it: `get_budgets(month)`, with `meter_percent`, `remaining_state` and `over`.
2. **Cash and Net worth across all accounts, as two figures side by side.** Both are already traced (`worth.today`,
   `finance/wealth_traces.py:192`, with `figure=cash` and `figure=net_worth`).
   - Cash adds up each account's latest statement balance.
   - The figure shows the date range ("as of Jun 30 – Sep 30").
   - Accounts over 35 days old are flagged stale in the breakdown, with a "Some balances are old" note under the
     figure.
   - This replaced the old "no total across accounts" decision (docs/ui.md "Decisions" 4).
3. **Your own layout notes** for the other Today sections were given when Today was planned (below).

**How you like to work:** you want to be asked for input at each step rather than handed defaults. Use
AskUserQuestion with previews for real choices.

## Phase 1a (done 2026-10-10)

Built from `phase1a-plan.md`:
- tokens in light and dark;
- a Settings › Appearance switch (System / Light / Dark, saved per browser);
- Plus Jakarta Sans (variable) and JetBrains Mono, self-hosted;
- chart and meter colors as tokens, with over budget amber, not red;
- the base components;
- the shell, restyled, with a top bar and menu sheet under 820px.

docs/ui.md "Design system" describes it, and `tests/test_style_tokens.py` and `tests/test_shell_browser.py` check it.

**Left open for you to decide:**
- In dark, `--chart-seq-8..10` (the tax-bucket ramp's darkest steps) are under 3:1 on `--surface`. MASTER.md
  "Color tokens" has the ratios. The labels sit outside the bars and the table carries every value, but a ramp
  reversed for dark would read better.
- Light `--chart-cat-3..5` are under 3:1, as they always were. That's the validated palette, relieved by the legend
  and the table.

## Phase 1b (done 2026-10-10)

Built from `phase1b-plan.md`:
- `pageState()` in `ui.js`, on Bills, Accounts, Investments, Forecast and Taxes: a delayed "Loading …" line, the error
  with Retry instead of a toast, and "Set up your library" without one;
- the `ui_v2_screens` flag: per profile, `PUT /api/ui-screens`, a Settings › Appearance › New screens checklist, and the
  `V2_SCREENS` registry with `data-ui="v2"` sections in `shell.js`;
- `trace.js`: `figure()`, the breakdown panel (beside the page from 1180px, floating at 900–1179, a bottom sheet
  below), `provenanceBadge()` and `ruleCard()`;
- `tests/test_ui_parity.py` (the harness, with `MIGRATED` empty) and `tests/test_trace_components_browser.py`.

docs/ui.md "Design system", "Observability components" and "Migration" describe it. Before and after screenshots of
the six touched routes are identical once loaded.

**Resolved in Phase 2 Taxes:** a breakdown's answer and running column used `amount()` signed, so a positive spending
figure read "+149.00 USD" in green. Now `figure()` takes `signed`/`magnitude` and the breakdown follows its opener;
tax figures show unsigned with the label giving the direction. Home and other callers keep the signed default until
their own screen decides.

## Phase 2, Taxes (done 2026-10-10)

Built from `phase2-taxes-plan.md`; `pages/taxes.md` has the page's design. `taxes_v2.js` is behind the flag
(`V2_SCREENS.taxes`, `("taxes", "taxes")` in `MIGRATED`), and v1 stays until Phase 3. Tests:
`tests/test_taxes_v2_browser.py`, the parity run, `tests/test_traces.py` (the full figures, `stub_list`).

**Where the build differs from the plan, and why:**
- `V2_SCREENS` moved from `shell.js` to `app.js`: `taxes_v2.js` loads before `shell.js` (as planned), so the registry
  has to exist first.
- The tab panels are `#taxes2-<tab>-panel`, not `#taxes2-<tab>`: `#taxes2-year` is the year select.
- Built from's sections each have their own panel (`#taxes2-secpanel-<key>`) inside `#taxes2-section-body`, because
  `wireTabs` hides each tab's own panel.
- A records value you typed over shows its records figure untraced: its trace ends at the typed value, so pairing them
  would fail `check_figures`.
- The parity check counts a figure's unsigned form as shown on v1 (v1 writes the result as "4,921.84 USD", the figure
  is "-4,921.84 USD").
- The likely range shows unsigned only when both ends fall the same way; a range crossing $0 keeps its signs.
- Under 600px, Total tax and Paid and credited become one-line tiles, so "What to do" sits higher, as the 390 sketch.

**Your decisions (planning):**
- Six tabs, all this session: This year, Built from, Write-offs, Jobs & pay stubs, CPA pack, Rules & sources.
- The server sends full figures for the lines, the records' values, the jobs and Tax Zen.
- Tax figures show unsigned, with the label giving the direction. This resolves the Phase 1b sign item.
- This year shows the answer tiles, then "What to do", then the return.
- Built from is a section list beside rows, with a sticky save bar.
- W-4 entries are on Jobs & pay stubs.
- v1 stays until Phase 3.

## Phase 2, Today (done 2026-10-10)

Built from `phase2-today-plan.md`; `pages/today.md` has the page's design. `today_v2.js` is behind the flag
(`V2_SCREENS.home`, `("home", "home")` in `MIGRATED` with `NEW_ON_V2` for the figures v1 never showed), and v1 Home
stays until Phase 3. Tests: `tests/test_today_v2_browser.py` (personal and family), the parity run,
`tests/test_traces.py` (Money in, Cash, Net worth, the old-balance flag). `ui_shots.py` now seeds statement
balances (one stale), a car and its loan, a confirmed rent and two earlier months.

**Where the build differs from the plan, and why:**
- An over-budget row's badge is the warning badge relabelled "Over budget": `statusBadge("over")` is the danger
  (red) tone, and MASTER.md says over is amber, never red.
- `/api/dashboard` keeps `worth` off the family dashboard (it would be the first member's); the family tiles use
  `/api/family/net-worth`, which now also adds up with `worth_totals`.
- `balance_dates` keeps a balance's `member` tag, so the family's stale list says whose it is.
- The sidebar label also switches when the screen is toggled in Settings › Appearance, not only on load
  (`setHomeNavLabel` in `shell.js`).
- `today_v2.js` had to be added to the static file allowlist in `app/api.py`.
- Tile, column and section spacing comes from `.page-body`'s gap; empty parts take no room.
- `budgets.unbudgeted` is a list by currency, so the footer finds the shown currency's row.

**Your layout notes (planning):**
- Needs you first, in two columns: the tiles, then Needs you and the dated sections on the left beside the budgets on
  the right.
- Both charts kept.
- Four tiles: Cash, Net worth, Spent and Money in.
- Bills, CDs and Treasuries coming due, Weekly check-in, Return windows and Warranties as separate small sections,
  each hidden when empty.
- The family view built in the same session.
- At 390, the tiles come before Needs you.
- The name "Today" shows only when v2 is on.

**Backend additions (additive):**
- the `cashflow.in` trace;
- Cash and Net worth on the personal dashboard;
- the 35-day stale rule (`balance_dates`).

The steps below were the original Phase 1 outline, kept for reference; 3–5 were 1a and 6 was 1b.

1. Load the `ui-redesign` skill in **plan mode** and read what it lists: CLAUDE.md, docs/ui.md "Screen rules", this
   MASTER.md, and the Pro Max SKILL.md.
2. **Before screenshots** of every page:
   `.venv/Scripts/python.exe .claude/skills/ui-redesign/scripts/ui_shots.py --routes <all> --out <scratchpad>/before`
   (390/768/1440, light and dark, synthetic data only).
3. **Tokens:** replace the `:root` block in `src/home_manager/app/static/style.css` with MASTER.md's tokens, and add
   the dark block under `[data-theme=dark]` and `prefers-color-scheme: dark`. Find hard-coded colors with Grep
   `#[0-9a-fA-F]{3,6}` in `style.css` outside `:root`, `home.js` `CHART_COLORS` and `finance/charts.py`.
4. **Fonts:** download the Plus Jakarta Sans (github.com/tokotype/PlusJakartaSans) and JetBrains Mono
   (github.com/JetBrains/JetBrainsMono) woff2 files into `app/static/fonts/`, with their OFL license files, and add
   `@font-face` rules in `style.css`. Never use a CDN link: the CSP is `style-src 'self'`.
5. **Base components** in `style.css` "Controls", "Feedback", "Tables" and "Menus and dialogs", plus the shell and
   sidebar, as in MASTER.md "Components" and "Layout". Page layouts stay the same in Phase 1.
6. **The rest of item 5:** one `pageState()` loading/error/empty helper, the `trace.js` components (`figure()`,
   `breakdownPanel()`, `provenanceBadge()` and the others in docs/ui.md "Observability components"), the
   `ui_v2_screens` flag, and `tests/test_ui_parity.py`. Plan how much fits in one session; the skill says one unit per
   session.
7. **Verify:** after screenshots of every page (no `HORIZONTAL OVERFLOW`, no page errors), the touched browser tests
   with `$env:RUN_BROWSER_TESTS = "1"`, contrast for any new token pair, and keyboard focus rings.

Then Phase 2 screens in this order: Taxes → Today → To check and the document page → Money screens → Wealth → the rest.

## Rules to keep in mind
- Synthetic data only. Never touch `P:\Finances`, `%LOCALAPPDATA%\HomeManager` or `P:\EvalCorpus`.
- No framework, no build step, no inline styles or scripts (strict CSP), and tokens only.
- Use Edit/Write for changes. No `cd …;` compound commands; run commands from the project root.
- Phases 0, 1a and 1b are committed on `reorganize-packages`; Phase 2 Taxes and Today are not committed yet.

## Next: Phase 2, To check and the document page

Plan it with the `ui-redesign` skill in plan mode (docs/open-work.md "UI redesign" 6).
