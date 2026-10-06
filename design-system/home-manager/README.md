# Home Manager design system: where things stand

This folder holds the redesign's visual decisions. Start here when you pick the redesign up again.

| File | What it is |
|---|---|
| `MASTER.md` | **The approved design system** (direction C · Family). Tokens, type, spacing, components, and decisions for later screens. It wins over the preview. |
| `phase0-directions.html` | The Phase 0 preview: the three directions (A · Ledger, B · Household book, C · Family) on Today and Transactions, light and dark, synthetic data. Open it in a browser. It loads fonts from Google Fonts, so it's a throwaway page outside the app's CSP. Also published at https://claude.ai/artifact/55gpu4BBFRmHy7nLUkSE7e. |
| `pages/<page>.md` | Not created yet. Each Phase 2 screen session adds one. |

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
3. **Your own layout notes** for the other Today sections are still to come. Today's session must ask you for them.

**How you like to work:** you want to be asked for input at each step rather than handed defaults. Use
AskUserQuestion with previews for real choices.

## Next: Phase 1 foundation

Wait for the weekly usage reset; this is the heavy phase. The work list is docs/open-work.md "UI redesign" 5.

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
- Nothing from this redesign is committed yet. It sits with the rest of the uncommitted work on `reorganize-packages`.
