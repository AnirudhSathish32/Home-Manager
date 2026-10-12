# Home Manager design system: where things stand

This folder holds the redesign's visual decisions. Start here when you pick the redesign up again.

| File | What it is |
|---|---|
| `MASTER.md` | **The approved design system** (direction C · Family). Tokens, type, spacing, components, and decisions for later screens. It wins over the preview. |
| `phase0-directions.html` | The Phase 0 preview: the three directions (A · Ledger, B · Household book, C · Family) on Today and Transactions, light and dark, synthetic data. Open it in a browser. It loads fonts from Google Fonts, so it's a throwaway page outside the app's CSP. Also published at https://claude.ai/artifact/55gpu4BBFRmHy7nLUkSE7e. |
| `pages/<page>.md` | One per Phase 2 screen: `pages/taxes.md`, `pages/today.md`, `pages/document.md`, `pages/review.md`, `pages/money.md`, `pages/wealth.md`, `pages/inventory.md`, `pages/system.md`. |
| `phase1a-plan.md` | The Phase 1a hand-off (2026-10-10), **built 2026-10-10**. Kept as the record of what 1a covers. |
| `phase1b-plan.md` | The Phase 1b hand-off (2026-10-10), **built 2026-10-10**. Kept as the record of what 1b covers. |
| `phase2-taxes-plan.md` | The Phase 2 Taxes hand-off (2026-10-10), **built 2026-10-10**. Kept as the record of what it covers. |
| `phase2-today-plan.md` | The Phase 2 Today hand-off (2026-10-10), **built 2026-10-10**. Kept as the record of what it covers; `pages/today.md` has the page's design. |
| `phase2-review-document-plan.md` | The Phase 2 To check and document page hand-off (2026-10-10): **both builds done 2026-10-10** (A: the document page; B: To check). |
| `phase2-wealth-plan.md` | The Phase 2 Wealth & plans hand-off (2026-10-11), three builds: **A Investments, B Forecast and C What If, all built 2026-10-11**. `pages/wealth.md` has the design and Build A's deviations. |
| `phase2-system-plan.md` | The Phase 2 Home & things and System hand-off (2026-10-11), three builds: **A Inventory and B Processing built 2026-10-11**; C Settings not built. `pages/inventory.md` has Inventory's design and Build A's deviations; `pages/system.md` has Processing's (Build B), and Build C adds Settings to it. |
| `figure-fit-plan.md` | Figure tiles fit their amounts on every page (2026-10-11), a follow-up to Today's side-panel fix: a row-shared figure size fitted to the longest amount (`fitFigures`), the What If plan headline, and a currency-code wrap as the last resort. **Built 2026-10-11**, plus Forecast's tiles going 2 columns when the results column is under 480px and the What If paycheck headline's columns made equal. |

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
- Phases 0, 1a, 1b and Phase 2 Taxes and Today are committed on `reorganize-packages`; the document page (Build A) and
  To check (Build B) are not committed yet.

## Phase 2, the document page (Build A, done 2026-10-10)

Built from `phase2-review-document-plan.md` Build A; `pages/document.md` has the page's design.
- **Backend:** the correction preview, history and undo endpoints, `correctable` on the record view, and
  `?figures=1`. See docs/money.md "Corrections".
- **Components:** `sourceViewer`, `confirmCorrect`, `historyList`, `loadReading` and `loadHistory`, all in `trace.js`.
- **Page:** `document_v2.js` is behind the flag (`V2_SCREENS.document`, "Document page" in Settings), and v1 stays until
  Phase 3.
- **Tests:** `tests/test_correction_preview.py`, `tests/test_record_history.py`,
  `tests/test_record_components_browser.py` and `tests/test_document_v2_browser.py`.
- **Seeding:** `tests/seed_documents.py` reads and records a receipt, a needs-review receipt and a statement with the
  fake models. `ui_shots.py` seeds them too, and takes `{receipt_doc}`, `{review_doc}`, `{statement_doc}` and
  `{review_record}` in `--routes`.

**Where the build differs from the plan, and why:**
- **An amount correction keeps the match.** The plan expected a transaction's amount correction to end its receipt
  match. A real save keeps the proposed link, because reconciliation doesn't re-check existing links, and the preview
  mirrors the save. The test asserts that the preview equals the save. Whether a changed amount should end a match is
  a reconciliation question for later.
- **The statement is recorded, not published.** `seed_statement` takes the fake model and records the statement the
  way extraction does. The page finds its record through the extraction run, so a directly published statement never
  shows. Its seed also captures one unread document.
- **`.cc-state` is a `div`, not a `p`,** because it holds an `alertBox` when a decision fails.
- **New `confirmCorrect` options:** `showState: false` (the document page's header already shows the status badge),
  `decision: false` and `onClose` (a statement row's Correct-only form).
- **The header stops being sticky while the Correct form is open,** and Save scrolls into view after the preview. A
  sticky header taller than the screen hid Save at 1366×768. The preview is capped at `min(40vh, 280px)`.
- **Reading notes stay in the source viewer's "Reading notes & codes",** not repeated in Details.
- **The record header names what was recorded** ("Receipt from Hardware Depot"), since the h1 already has the
  document's name. "Counts in" lists each category and month beside its figure.
- **Under 900px the page's grid unwraps the record column** (`display: contents`), so the order is header, source,
  tabs.
- **Not covered by browser tests:** the reading, read-failed, extracting, blocked and split states. They need a model
  run in progress or a failure, and the copied v1 logic covers them. Covered: unread, needs review, Confirm → verified,
  checked automatically, Correct with preview and Undo, the History tab, a statement row's Correct, and Esc.

## Phase 2, To check (Build B, done 2026-10-10)

Built from `phase2-review-document-plan.md` Build B; `pages/review.md` has the page's design.
- **Page:** `review_v2.js` is behind the flag (`V2_SCREENS.review`, "To check" in Settings), and v1 stays until Phase 3.
  The sidebar says "To check" while it's on.
- **Refactors, v1 unchanged:** `reviewData()` in `review.js`, v1's keys stand down while v2 is on, `openItemDialog`
  takes an `onDone`, and `routingRow` takes `onSent` and an id prefix.
- **Backend:** `/api/items/resolutions` gives each line's `document_id` and `line_ids` (plan 1e).
- **Tests:** `tests/test_review_v2_browser.py` (each kind, keys and URL, V with Undo, Correct, Combine, an unmatched
  receipt's Correct, the family's "Who is it for?", every width, v1's keys staying quiet). `tests/test_items.py`
  checks the new fields.
- **Seeding:** `seed_review_items` in `tests/seed_documents.py` adds a product to identify, a warranty found online, a
  tax table and an image group; `ui_shots.py` seeds them too and takes `{warranty}`, `{tax_table}`, `{group}` and
  `{item_resolution}` in `--routes`.

**Where the build differs from the plan, and why:**
- **`--review2-top` is a `:root` token,** not a `.review2-layout` property: `tests/test_style_tokens.py` requires every
  `var()` to be defined in the light block. It is 140px, and 192px at 900–1179px, where the picker row sits above the
  columns. The plan's 120px under 820 isn't needed: under 900 the columns aren't sticky.
- **Statement values, confirmations and tax forms reuse v1's `reviewParts` evidence** instead of a copy; their
  evidence has no state of its own. Every other kind is copied, because its v1 controls feed v1's decision.
- **Image groups switch pages by loading each page's reading,** not `viewer.showDocument`, so a page that was read
  shows its text too. Chips are shared with a proposed match's Receipt / Charge's statement.
- **A lone evidence block is divided, not boxed** (MASTER "Tinted region"); only the Charge | Receipt pair keeps
  outlines.
- **`confirmCorrect`'s inner "Decision" group drops its role,** since the bar is that group.
- **A selection made while the queue loads wins:** the app re-routes once settings arrive, and that second load used to
  reset J/K moves made in between.
- **Two small fixes outside the plan:** the reconcile prompt now reloads a v2 screen, not its v1 loader
  (`finance.js` `reconcileStatement`), and `sourceViewer` hides its empty frame when a preview can't be shown (a CSV
  statement showed a broken image beside the error).
- **A needs-review record's preview says "No totals change."** It isn't counted until confirmed, so the test checks
  that and "Still needs you" rather than moved totals.

**Your decisions (planning):**
- To check is three columns at 1440: queue | source | the item, with a pinned decision bar.
- The document page has a sticky record header (steps, next action, Confirm / Reject / Correct…) above the tabs Record ·
  History · Details. Re-run actions move to the ⋯ menu.
- Correct covers receipts, bills, pay stubs, statements and statement rows. It doesn't cover investments.

## Phase 3, v2 becomes the only UI (Build E, done 2026-10-12)

Built from `phase2-rest-plan.md` Build E; docs/ui.md "Migration" describes the result.
- **Routing:** `shell.js` `showRoute` shows a route's `data-ui="v2"` section whenever `V2_SCREENS` has it.
  `uiV2Screens`, `renderUiV2Choices` and `setHomeNavLabel` are gone; the sidebar labels are written in `index.html`.
  The flag checks in `app.js` (poll), `assistant.js`, `finance.js`, `inventory.js`, `profiles.js`, `library.js`
  (`showFolder` always opens Records), `records_v2.js` and `review_v2.js` are gone, and v1's J/K/V/R listener in
  `review.js` is deleted (it could only press v1's hidden buttons).
- **The flag:** `PUT /api/ui-screens`, `UiScreensInput`, `UiRoute`, the New screens fieldset and the household
  payload's `ui_v2_screens` are removed. `HouseholdConfig.retired_keys` drops a stored key; `tests/test_settings_api.py`
  loads one and saves Preferences with one.
- **Parity:** `test_every_screen_reconciles` over `home, spending, bills, accounts, investments, forecast, taxes,
  inventory?tab=insights`. The document test checks "Counts as" against the receipt's own total from the record API.
- **`ui_shots.py`** has no `--v2`. `seed_tax_year` and `this_year_covered` moved to `tests/seed_taxes.py`.

**v1 browser tests, one decision each:**
- `test_home_browser.py`: **deleted**. `test_today_v2_browser.py` covers the spent total, budgets, error with Retry
  and widths.
- `test_taxes_browser.py`: **deleted**. Tax Zen and the joint return are covered by `test_taxes_v2_browser.py`; the
  aim (saved with the year) and Engine 2's agreement were added there, and the tagging flow (drawer, To check's
  IRS suggestion, Write-offs, Rules, Businesses, the refund, a typed job) is ported as
  `test_taxes_v2_adds_up_tags_from_the_drawer_and_to_check`.
- `test_whatif_browser.py`: **deleted**. Following a plan is covered by `test_whatif_v2_follow_this_plan`; the
  planner's gross-to-net and building/saving/reopening a plan are ported to `wi2-` ids.
- `test_recurring_bills.py`: the loading/error test **deleted** (`test_bills_v2_shows_loading_and_a_retryable_error`);
  confirming a bill with its frequency **ported** to `test_bills_v2_browser.py`. Its non-browser tests stay.
- `test_investments.py`: the browser test **deleted** (both Investments v2 tests cover it); I bonds' "If cashed today"
  added to the account view test. `statement` stays for `seed_wealth.py`.
- `test_forecast.py`: the browser test **deleted** (`test_forecast_v2` covers assets, one-offs and the retirement
  controls). `TODAY` and `base` stay for `test_scenarios.py`.
- `test_family_browser.py`: **ported in place** (it spans Today, To check, Transactions and Settings, so no single twin):
  Today's tiles, routing in To check, the 199.01 after delivery, a correction from the Transactions v2 drawer, and
  Settings › Profiles. `spend` stays.
- `test_receipt_counting.py`: the browser test **ported in place**: the reconcile prompt, Records' receipt categories,
  and the PDF frame and preview error in the document page's source viewer.
- `test_browser.py`: all four **ported in place** to Records, the document page, Processing, This month, Transactions,
  To check, Inventory and Search. Dropped with v1's inspector: "Edit details" (location, all-items category) and the
  transcription caret position; the document page corrects one field at a time and finds lines with `.sv-line.selected`.
- Also ported: `test_document_search_browser.py` (Search v2, Records' snippet, the document page's found line),
  `test_employers.py`'s browser test (Records' Jobs tree), `test_shell_browser.py`, `test_trace_components_browser.py`.

**Fixes found while porting:**
- `tests/seed_items.py` set check-in questions due *today*, which only counts on the check-in weekday (Sunday): the
  Inventory test passed only on Sundays. They're now due on the latest check-in day.
- Several tests now wait for the page to settle (`networkidle`) before acting where a background refresh redraws the
  item under the clicks (To check's recurring payment, Taxes' Add a return, Records' row menus).
