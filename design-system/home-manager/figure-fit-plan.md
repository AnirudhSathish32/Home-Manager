# Figure tiles fit their amounts on every page (Today follow-up, widened)

> **This session only saves this plan.** It goes to `design-system/home-manager/figure-fit-plan.md`, with a row in
> `design-system/home-manager/README.md`, and nothing is built here. A separate session builds it from that file.

## Context
After the Today panel fix, docs/open-work.md "UI redesign" still records that six-figure amounts ("+155,707.53 USD")
spill out of Today's four tiles at 1100–1365px with no panel open. The cause is that `.figure-button` is nowrap and the
figure is a fixed `--figure-lg` (28px). The first proposal (a fixed `11cqi` on Today only) left two cases out of scope.
The user wants both fixed too:
1. **Other pages' tiles.** They have the same nowrap figure at a fixed 28px in narrow tiles, and they get narrower
   still with Ask or a breakdown open: This month (`.month2-tiles`), Bills (`.bills2-tiles`), Investments
   (`.inv2-tiles`), Forecast (`.fc2-tiles`, which has its own fixed `9cqi` shrink), Inventory insights (`.it2-tiles`)
   and Taxes (`.taxes2-answer`).
2. **Amounts of a million or more** (17 characters, "+1,155,707.53 USD"). A fixed coefficient can't fit them
   without shrinking every short figure too.

**Approach:** each row of tiles shares one figure size, fitted to the **longest amount in that row**.
- A small helper in `trace.js` counts the visible characters of the row's longest tile amount and sets
  `--figure-chars` on the row through CSSOM. `element.style.setProperty` isn't blocked by the CSP's `style-src 'self'`,
  and `finance.js:497` already sets `fill.style.width` the same way.
- One base rule in `style.css` sizes the figure as `tile width ÷ (chars × 0.6)`, clamped between `--text-lg` and
  `--figure-lg`. The width is measured on each `.figure-tile`, which becomes a size container.

The result:
- Short amounts keep 28px wherever they fit, so default layouts barely change.
- A long amount shrinks its whole row just enough, so tiles in a row never differ in size.
- Everything stays pure layout: no browser money math, no wrapping, no new design tokens.

Measured: "+155,707.53 USD" is 236px at 28px, which is 0.56em per character. A factor of 0.6 means the longest
amount takes about 93% of the tile's text width.

At the 15px floor, a tile 179px wide (Today at 1180 with no panel) fits 19 characters, that is up to
"+99,999,999.99 USD". Anything longer gets the last-resort wrap in section A below.

## Changes by file
- **`src/home_manager/app/static/trace.js`**, after `figure()`:
  ```js
  // A row of figure tiles shares one figure size, fitted to its longest amount (style.css "Observability": figure tile).
  // Counts what's on screen: the visually-hidden "money in/out" words aren't.
  function fitFigureTiles(row) {
    const shown = node => [...node.childNodes].filter(child => !child.classList?.contains("visually-hidden")).map(child => child.textContent).join("");
    const amounts = row.querySelectorAll(".figure-tile > .figure-button[data-size='lg'] > .amount, .figure-tile > .amount");
    row.style.setProperty("--figure-chars", String(Math.max(1, ...[...amounts].map(node => shown(node).length))));
    return row;
  }
  ```
  First check that `figure()` puts the `.amount` span directly inside the button. If it's nested deeper, use
  `.figure-button[data-size='lg'] .amount`.
- **`style.css`, "Observability" at `.figure-tile` (:363):**
  - Add `min-width: 0; container-type: inline-size;` to `.figure-tile`.
  - Add:
    ```css
    /* A row's figures share one size: --figure-chars (fitFigureTiles in trace.js) is the row's longest amount, which then
       takes about 93% of a tile's width. Amounts never wrap; a stale or unconfirmed badge drops under its amount. */
    .figure-tile > .figure-button[data-size="lg"], .figure-tile > .amount {
      font-size: clamp(var(--text-lg), calc(100cqi / (var(--figure-chars, 12) * 0.6)), var(--figure-lg));
    }
    .figure-tile > .figure-button { flex-wrap: wrap; column-gap: var(--space-2); row-gap: var(--space-1); }
    .figure-tile > .figure-button .figure-flag { margin-left: 0; }
    ```
  - Remove the per-page rules that now repeat or override this:
    - Today's `.today-tiles .figure-button` wrap and `.figure-flag` rules (they move to the base rule);
    - `font-size: var(--figure-lg)` from `.month2-tiles .figure-tile > .amount` (:746), `.inv2-tiles … > .amount`
      (:1507) and `.fc2-tiles … > .amount` (:1861). Keep their `display: block; line-height: 1.2; font-weight: 600`;
    - `.fc2-tiles`'s `container-type` (:1857) and its `9cqi` rule (:1859), with its comment.
  - Keep the phone and narrow rules that set `--text-lg`: Today, This month, Bills and Inventory at ≤599px, and Taxes
    :576. They're later or more specific, so they still win. Keep Today's 2×2 `@container` rule on `#today-body`.
  - Remove `overflow-wrap: anywhere` from the per-page `.figure-tile` rules only if it becomes redundant. It isn't
    redundant: labels and sublines still need it, so leave it.
- **Call `fitFigureTiles(row)` right after each row is filled:**
  - `today_v2.js:84`, on `$("today-tiles")`;
  - `month_v2.js:101`, on `$("month2-tiles")`;
  - `bills_v2.js:63`, on each per-currency `row`;
  - `investments_v2.js:117`, on `$("inv2-tiles")`;
  - `forecast_v2.js:212`, on `$("fc2-tiles")`;
  - `inventory_v2.js:382`, on `tiles`;
  - `taxes_v2.js:253–256`, on `tiles`.
- **`tests/conftest.py`:** add a shared check, `assert_tiles_fit(page, row_selector, long_text="+1,155,707.53 USD")`.
  - For every row it finds, it calls `fitFigureTiles(row)` and asserts that each `.figure-button[data-size="lg"]`,
    `.figure-flag` and `.figure-tile > .amount` sits inside its tile's box (±0.5px).
  - It then replaces the visible text of each row's first lg amount with `long_text`, calls `fitFigureTiles(row)`
    again, and re-asserts.
  - Move `TILES_FIT` here from `tests/test_today_v2_browser.py`, and have that file import it.
- **Browser tests, one added block each, at the end before `browser.close()`:**
  - Set the viewport to 1180, then 1440. Open Ask with `Control+j` and call `assert_tiles_fit`, then close Ask and
    call it again.
  - Files:
    - test_today_v2_browser (`#today-tiles`, plus 1280 and 1366; at 1366×768 also re-assert the Needs you
      decision box is in view after the long amounts);
    - test_spending_v2_browser (`#month2-tiles`);
    - test_bills_v2_browser (`#bills2-tiles > .bills2-tiles`);
    - test_investments_v2_browser (`#inv2-tiles`);
    - test_forecast_v2_browser (`#fc2-tiles`);
    - test_inventory_v2_browser (`.it2-tiles`, after opening the insights tab);
    - test_taxes_v2_browser (`.taxes2-answer`).
- **Docs:**
  - docs/ui.md "Design system" or "Observability components", the figure tile: add one sentence on the row-shared
    size and `fitFigureTiles`.
  - docs/ui.md "Pages", Today bullet: add "figures shrink to fit".
  - `pages/today.md` and MASTER.md "Components", Figure tile: "a row's figures share one size, from `--figure-lg` down
    to `--text-lg`, fitted to its longest amount; amounts never wrap". Change today.md's "never wrap or shrink" to
    match.
  - docs/open-work.md: delete the 1100–1365px paragraph. With the last-resort wrap below, there's no remaining limit.
  - Memory `ui-redesign-pro-max.md`: replace the "Still open" sentence with "tile figures fit on every page".

## Formerly out of scope (now planned)
Each was checked against the code.

**A. Amounts too long even at the 15px floor** (19+ characters, "+123,456,789.00 USD").
- Last resort: let only the currency code drop to a second line, never the digits. Add:
  `.figure-tile > .figure-button .amount, .figure-tile > .amount, .plan-figure .amount { white-space: normal; overflow-wrap: normal; }`
- `amount()` (`ui.js:198`) writes the magnitude and the code as one text node, "155,707.53 USD". With
  `overflow-wrap: normal` the only break point is the space before the code, so digits can't split. Without it, the
  tile's inherited `overflow-wrap: anywhere` would split them.
- When the fitted size fits (always, above the floor), there's no wrap, and nothing changes visually.
- Home-currency amounts ("$155,707.53") have no space, but at 15px they fit up to $9,999,999,999.99 in Today's
  narrowest tile.
- The flex item shrinks to its min-content inside the inline-flex button, which wraps, so the wrap happens when it's
  needed.
- Docs wording becomes "digits never wrap; at the smallest size the currency code may drop under them".

**B. The What If plan headline** (`.plan-headline .plan-figure`, live in v2 through `whatif.js:241–246` with
`wiMoney`). It's three 28px figures in a 3-column `<dl>`, the same problem as the tiles.
- Extend the same mechanism rather than inventing a second one.
- In `fitFigureTiles`, rename it to `fitFigures(row)` and also count `.plan-figure > .figure-button > .amount` and
  `.plan-figure > .amount`. Update the seven call sites above.
- In `style.css` "Plan headline" (:460–463):
  - `.plan-headline .plan-figure { container-type: inline-size; min-width: 0; }`, dropping its fixed `font-size`;
  - add `.plan-figure > .figure-button, .plan-figure > .amount` to the base fit rule's selector list. The rule sits at
    :363, before :463, so make sure no later rule resets it.
- Call `fitFigures(headline)` after `whatif.js:246`'s loop.
- `taxes.js:417–421` is the v1 Taxes loader, which is deleted in item 8, so leave it. It keeps its fixed size through
  `.plan-figure`'s line-height only.
- Test: in `tests/test_whatif_v2_browser.py`, add an
  `assert_tiles_fit` call with row selector `.plan-headline` at 1180 with Ask open. Generalize the conftest check so
  its cell selector is `.figure-tile, .plan-figure`.

**C. `data-size="xl"`** (`style.css:358`). No caller passes `size: "xl"` (Grep finds none), so it's dead CSS. Delete
the rule, and say so in ui.md "Observability components" if it lists the sizes.

**D. `.figure-value`** (`style.css:958`). Its only users are `investments.js:166` and `finance.js:525`, both v1
loaders that item 8 deletes. No change now. Add "`.figure-value` goes with them" to item 8's dead-CSS list in
docs/open-work.md.

**E. `.drawer-amount`** (`finance.js:329`, `:426`, the transaction drawer). It's a single block-level amount, not
nowrap, in a drawer at least 350px wide on a phone. "−1,155,707.53 USD" is about 267px at 28px, so it fits, and a
longer one already breaks at the space before the code. No change. Add one assertion to `tests/test_transactions_v2_browser.py` where it opens the
drawer: at 390, the `.drawer-amount` box sits inside `#tx-drawer-body`.

**F. Table cells.** Numeric cells are `white-space: nowrap` inside `.table-wrap { overflow-x: auto }` (`style.css:281`,
`:296`). That includes the breakdown's steps table (`trace.js:99`). A long amount scrolls the table and never clips.
No change, since that's the intended table behavior in MASTER "Components": table.

**G. Backend and copy.** Nothing in this fix needs either. Amounts stay server text through `amount()` and `figure()`,
and no wording changes.

## Verification
1. Run the touched browser tests:
   `$env:RUN_BROWSER_TESTS = "1"; .venv/Scripts/python.exe -m pytest tests/test_today_v2_browser.py tests/test_spending_v2_browser.py tests/test_bills_v2_browser.py tests/test_investments_v2_browser.py tests/test_forecast_v2_browser.py tests/test_inventory_v2_browser.py tests/test_taxes_v2_browser.py tests/test_whatif_v2_browser.py tests/test_transactions_v2_browser.py tests/test_ui_parity.py -q`
2. Run `ui_shots.py --routes home,spending,bills,investments,forecast,whatif,taxes --v2 <same> --widths 390,768,1180,1280,1440`,
   with and without `--open-ask`. Compare with earlier shots:
   - no `HORIZONTAL OVERFLOW` and no page errors;
   - at 1280, Today's Net worth sits inside its tile;
   - short-amount rows look the same as before;
   - at 390, phone sizes are unchanged.
3. Extra checks for the formerly out-of-scope items:
   - add a second `assert_tiles_fit` pass with "+123,456,789.00 USD" on Today at 1180 with Ask open. Expect a
     two-line amount with the code on line two, and every box inside its tile;
   - run the What If test and the drawer test;
   - Grep `data-size="xl"` and `size: "xl"`, and expect no hits after the deletion.
