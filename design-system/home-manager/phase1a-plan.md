# Redesign: Foundation, the look (phase 1a)

## Context
Phase 0 is done: direction **C · Family** is approved in `design-system/home-manager/MASTER.md`. Phase 1 (docs/open-work.md
"UI redesign" item 5) is too big for one session, so the user split it:
- **1a (this plan):** tokens in light and dark, self-hosted fonts, chart colors moved to tokens, the base components
  (Controls, Feedback, Tables, Menus and dialogs), and the shell and sidebar.
- **1b (next session):** `pageState()`, the `trace.js` components, the `ui_v2_screens` flag and `tests/test_ui_parity.py`.

Decided in planning (2026-10-10):
- **Dark theme** follows the system by default. A **Settings › Appearance** tab adds System / Light / Dark, saved
  per browser.
- **The sidebar is restyled only.** It keeps today's labels, groups, order and ids. The new labels from docs/ui.md
  "Redesigned navigation" come with the Phase 2 screens.

The user's job doesn't change, because page layouts don't change in Phase 1. What's wrong today, from the
before screenshots:
- Old ink-blue tokens and the system font.
- No dark theme at all: the dark screenshots look identical to the light ones.
- Hard-coded chart and meter hex values, and an exceeded budget drawn **red**, which breaks "red never means spending".
- At 390px a 64px icon rail takes a sixth of the width, and table text wraps letter by letter. MASTER wants a top
  bar below 820px.

## Before screenshots
`C:\Users\Anirudh\AppData\Local\Temp\claude\P--Dev-Environment-Projects-Home-Manager\07c83f63-9e1d-4dd7-bd16-e0c784100a8a\scratchpad\before`
covers all 16 routes at 390/768/1440 in light and dark, with no overflow and no page errors. The scratchpad is
session-scoped, so the implementer **re-runs the same command into `<its scratchpad>/before` before editing**, with the
routes below. Look at these files: `home-1440-light`, `transactions-390-light` (icon rail squeeze),
`forecast-768-light`, `spending-1440-light` (meters), and any `*-dark`.

Routes: `home,review,transactions,spending,bills,accounts,investments,taxes,forecast,whatif,inventory,documents,search,processing,settings,donate`

## Design-system references
- MASTER.md "Color tokens", "Typography", "Space, shape, density", "Layout" (sidebar and page), and "Components"
  (buttons, chips, status badge, table, share bar, budget meter, tinted region). The direction-C CSS in
  `design-system/home-manager/phase0-directions.html` (lines 71–94 and 120–316) is the visual reference. MASTER
  wins where they differ (`--text-muted` `#636B7B`, `--chart` `#3B6FDB`, `--chart-track` `#E4EBFA`).
- **Deviations, with reasons:**
  - Panel padding is `--space-4 --space-5` (16/20), not 16/18, to stay on the spacing scale.
  - Main padding stays `--space-6 --space-7` (24/32), not 28/32, for the same reason.
  - The nav count badge is a warning pill only with `.attention` (Review, Inbox, Unfiled). The check-in count stays a
    neutral pill: amber means it needs you.
  - Links in running text keep a thin underline. Accent against body text is under 3:1, so color alone can't mark a
    link (WCAG 1.4.1). Standalone text-link buttons (`button.link-button`) underline only on hover, as in MASTER.
- No `pages/<page>.md`, because no page layout changes.

## Tokens
Replace `style.css` lines 3–28 with three blocks: `:root` (light), then
`@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { … } }`, then `:root[data-theme="dark"] { … }`.
The two dark blocks are identical. Each block sets `color-scheme`.

**From MASTER as-is:** `--canvas`, `--surface`, `--surface-sunken`, `--border`, `--border-strong`, `--text`,
`--text-secondary`, `--text-muted`, `--accent`, `--accent-hover`, `--accent-subtle`, `--on-accent`, `--positive`,
`--positive-subtle`, `--warning`, `--warning-subtle`, `--danger`, `--danger-subtle`, `--chart` and `--chart-track`, with
light and dark values exactly as in the MASTER table. MASTER already checks their contrast.

**Kept names, now aliases or new values:**

| Token | Light | Dark | Note |
|---|---|---|---|
| `--info` / `--info-subtle` | `var(--accent)` / `var(--accent-subtle)` | same | MASTER: info is accent |
| `--neutral-subtle` | `var(--surface-sunken)` | same | badges, counts |
| `--danger-hover` | `#912018` | `#F59D8C` | |
| `--on-danger` (new) | `#FFFFFF` | `#12141A` | white on `#B42318` 6.5:1; `#12141A` on `#F2836F` ≈6.6:1, verify |
| `--paper` (new) | `#FFFFFF` | `#FFFFFF` | document image frames stay paper-white in dark |
| `--backdrop` (new) | `rgb(16 24 40 / 40%)` | `rgb(0 0 0 / 60%)` | `dialog::backdrop` |
| `--shadow-overlay` | as today | `0 8px 28px rgb(0 0 0 / 45%), 0 1px 3px rgb(0 0 0 / 30%)` | |
| `--chart-cat-1..6` (new) | `#2a78d6 #eb6834 #1baf7a #eda100 #e87ba4 #008300` | same, except slot 6 `#4CB04C` | `#008300` is about 2.5:1 on dark surface; verify every dark slot ≥3:1 on `#191C24` |
| `--chart-seq-1..10` (new) | `BUCKET_BLUES` from charts.py | same | sequential ramp, labels sit outside the bars |
| `--chart-grid` / `--chart-baseline` | `var(--border)` / `var(--border-strong)` | same | |

**Type, space and shape:**
- `--font: "Plus Jakarta Sans", "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif` and
  `--font-mono: "JetBrains Mono", "Cascadia Mono", Consolas, ui-monospace, monospace`.
- Sizes: `--text-lg` 15px, `--text-xl` 26px, `--figure-lg` 28px, and new `--figure-xl` 30px.
- `--radius-sm` 6px, `--radius-md` 10px, `--radius-lg` 14px, new `--radius-pill` 999px.
- `--sidebar-width` 220px, new `--motion-panel: 180ms ease-out`.
- Unchanged: the space scale, control sizes and `--content-max`.

## Layout
Page layouts don't change. Only the shell changes.

```
1440×900 (≥1280)                          1024 (820–1279)        390 (<820)
┌──────────┬──────────────────────────┐   ┌──┬─────────────────┐  ┌──────────────────────┐
│HM Home M.│ h1 26/700  [sec][Primary]│   │HM│ h1     [actions]│  │HM Home Manager [≡ Menu]│ ← sticky top bar, --surface,
│Profile ▾ │ muted subline            │   │🔍│                 │  ├──────────────────────┤   bottom --border
│[Search  ]│                          │   │⌂ │ page content    │  │ h1                   │
│ Search   │ page content (unchanged  │   │☑3│ (unchanged)     │  │ page content         │
│█Home█████│ layout, new tokens)      │   │… │                 │  │ (full width, 16px    │
│ Review  3│                          │   │  │                 │  │  padding)            │
│Money     │                          │   │💬│                 │  └──────────────────────┘
│ Transact.│                          │   │⚙ │                 │  Menu open: the sidebar contents drop
│ …        │                          │   └──┴─────────────────┘  down as a sheet under the bar
│──────────│                          │   icon rail 64px, as today (fixed, full width, max-height
│ Ask      │                          │                           calc(100vh - bar), scrolls, --shadow-overlay).
│ Processing                          │
│ Settings │                          │
└──────────┴──────────────────────────┘
```
█ = selected: `--accent` fill, `--on-accent` text, weight 600. No decision region is added. Decision screens keep their
current in-view behavior, and the top bar is ≤56px so it doesn't push decision bars off screen at 390. The routing
"Send" in-view assertion runs at 768 height.

## Changes by file

### `src/home_manager/app/static/fonts/` (new)
- Download into a **new empty scratchpad folder**, never the repo, and copy only the needed files:
  - **Plus Jakarta Sans** (github.com/tokotype/PlusJakartaSans releases). Prefer the variable `wght` woff2, saved as
    `PlusJakartaSans-Variable.woff2`. If the release only has TTFs, convert with fontTools
    (`python -I -m fontTools.ttLib.woff2 compress`) run from the scratchpad. If only static weights exist, use 400, 500,
    600 and 700, and every 550 below becomes 600.
  - **JetBrains Mono** 400 and 500 woff2 (github.com/JetBrains/JetBrainsMono releases, `fonts/webfonts/`).
  - The licenses: `PlusJakartaSans-OFL.txt` and `JetBrainsMono-OFL.txt`.
- `api.py` `STATIC`: add each `"fonts/<file>.woff2": "font/woff2"`. The route loop already serves `"/" + name`. The
  license `.txt` files aren't served.
- The CSP stays as it is: `font-src` falls back to `default-src 'self'`.

### `style.css`
- **Tokens:** as above, plus `@font-face` rules at the top with `font-display: swap`.
- **Base:**
  - `:root` font comes from `--font`. Body text is 14/20.
  - `h1`: `--text-xl`, 32px line height, 700, `letter-spacing: -0.02em`.
  - `h2` and `h3`: `--text-lg`, 22px line height, 600. `h4`: 13/18, 600.
  - `a`: `--accent`, 1px underline with `text-underline-offset: 2px`. The decoration color is
    `color-mix(in srgb, var(--accent) 40%, transparent)`, and full `--accent` on hover.
  - `code` and `pre` use `--font-mono`.
  - `:focus-visible` stays a 2px `--accent` outline with a 2px offset.
- **Controls:**
  - Buttons: `--radius-sm`, weight 550 (600 if static fonts).
  - `.primary` uses `color: var(--on-accent)`. `.danger` uses `color: var(--on-danger)`, with `--danger-hover` on hover.
  - `.primary-action` and new `.button.lg` get `min-height: var(--control-lg)` with `0 14px` padding.
  - `button.link-button`: `--accent`, 550, no underline until hover.
  - Inputs and selects: `--radius-sm` and `--border-strong`, with `::placeholder` in `--text-muted`.
  - New `.chip` (pill, 30px, `--border` outline, `--text-secondary`, 13px).
  - `.chip[aria-pressed="true"]` and the existing `.home-range [aria-pressed="true"]` share the pressed style:
    `--accent-subtle` fill, `--accent` border and text.
- **Shell:**
  - `.sidebar`: `--surface` with a right `--border`, padding `--space-4 10px`.
  - `.brand-mark`: `--radius-md`, `--on-accent` text.
  - `.nav-group` and `.profile-picker label`: 12px 600 `--text-muted`, **no uppercase, no letter-spacing**.
  - `.nav-link`: 32px high, padding `0 10px`, `--radius-md`, `--text-md`, 500, `--text-secondary`.
  - `.nav-link[aria-current="page"]`: `--accent` fill, `--on-accent` text, 600.
  - `.nav-count`: a pill (`--radius-pill`) on `--neutral-subtle`. `.attention` is `--warning` on `--warning-subtle`.
  - `.sidebar-footer`: `border-top: 1px solid var(--border)` and `padding-top: var(--space-3)`.
  - `.page-subtitle` color is `--text-muted`.
  - `.panel`: `--radius-lg`, padding `--space-4 --space-5`.
- **Feedback:**
  - `.alert`: `--radius-md`, no border, filled with the tone's `-subtle` color.
  - `.toast`: `--radius-md`.
  - `.status-badge`: `--radius-pill`, padding `1px 9px 1px 6px`, line height 20px, 600.
- **Amounts:** new `.amount .sign { display: inline-block; width: .7em; text-align: center; }`.
- **Tables:**
  - `.table-wrap`: `--surface`, 1px `--border`, `--radius-md`.
  - `.panel .table-wrap, dialog .table-wrap, details .table-wrap` drop the border, radius and background, so regions
    never nest (MASTER "Tinted region").
  - `th`: 32px high, padding `0 var(--space-3)`, 12px 600 `--text-secondary` on `--surface-sunken`, sticky as today.
  - `td`: padding `10px var(--space-3)`, about 40px rows.
  - New `table.compact td`: padding `6px var(--space-3)`, about 32px rows.
  - `tbody tr:hover` uses `--surface-sunken` (replaces `#FAFBFC`).
  - `tr[aria-selected="true"] td` uses `--accent-subtle`. The last row has no bottom border.
- **Menus and dialogs:**
  - `.menu-list`: `--radius-md`.
  - `dialog`: `--radius-lg`.
  - `::backdrop` uses `var(--backdrop)`.
  - `dialog.drawer` keeps `border-radius: 0`, and its open transition uses `--motion-panel`.
- **Budget meters (lines 428–432):**
  - The track is `--chart-track` and the fill `--chart`.
  - `ahead_of_pace`: the track is `--warning-subtle` and the fill `--warning`.
  - `over`: the track is `--warning-subtle` and the fill `--warning`. **Not red** (MASTER, decided 2026-10-06).
  - The track is 8px high with a 4px radius.
- **Charts:**
  - The home trend bar gets classes `.chart-bar` (fill `--chart`) and `.chart-bar.partial` (fill `--chart-track`,
    stroke `--chart`), plus `.chart-axis` (stroke `--chart-baseline`).
  - Category slices and swatches get `.cat-1`…`.cat-6`, setting `stroke` and `fill` to `var(--chart-cat-N)`.
    `.cat-none` uses `--text-muted`.
  - Server SVG gets `.c-surface` (fill `--surface`), `.c-grid`, `.c-baseline`, `.c-text` (fill `--text`),
    `.c-muted` (fill `--text-muted`), `.c-line-1..3` (stroke `--chart-cat-1..3`), `.c-dot-1..3` (fill
    `--chart-cat-1..3`, stroke `--surface`), `.c-seq-1..10` and `.c-untaxed` (fill `--chart-baseline`).
- **Document page:**
  - `#receipt-image-frame` and `.donate-frame` use `--paper`.
  - The overlay polygon stroke is `color-mix(in srgb, var(--accent) 45%, transparent)`.
  - `.selected` has a `--warning` stroke and a `color-mix(in srgb, var(--warning) 18%, transparent)` fill. The
    highlighted source line is amber, as MASTER "Source text" says.
- **Responsive:**
  - Keep the 1279px icon rail, with `--sidebar-width` 64px.
  - New `@media (max-width: 819px)`:
    - `.app-shell` becomes a single column, and `.sidebar` a sticky top bar (`position: sticky; top: 0; z-index: 20;
      height: auto; flex-direction: row; align-items: center;` bottom `--border`).
    - Everything except `.brand` and `#nav-toggle` is hidden.
    - `.app-shell.nav-open .sidebar-sheet` is shown as a fixed sheet with `top: 56px`, the full width,
      `max-height: calc(100vh - 56px)`, overflow auto, `--surface`, `--shadow-overlay` and `--space-4` padding. Inside
      it, labels show again (undo the rail's visually-hidden labels and nav-group hiding).
    - `main` padding is `--space-4`.
  - `#nav-toggle` is hidden at 820px and wider.
  - The motion rules get `--motion-panel` for the sheet. They're off under `prefers-reduced-motion`, as today.
- **Hex sweep:** after this, no `#…` or `rgb(` appears outside the three token blocks. A test enforces it, below.

### `index.html`
- `<head>`:
  - `<meta name="color-scheme" content="light dark">`.
  - `<script src="/theme.js"></script>` **without `defer`**, before the stylesheet, so the theme applies before
    first paint.
  - `<link rel="preload" href="/fonts/PlusJakartaSans-Variable.woff2" as="font" type="font/woff2" crossorigin>`.
- Sidebar:
  - After `.brand`, add `<button id="nav-toggle" class="icon-button quiet" type="button" aria-expanded="false"
    aria-controls="sidebar-sheet" hidden>` with the `menu` icon and visually-hidden text "Menu".
  - Wrap the profile switch, search form, primary nav and `.sidebar-footer` in
    `<div id="sidebar-sheet" class="sidebar-sheet">`. All existing ids stay.
- Settings: add `<button id="appearance-tab" role="tab" aria-selected="false" aria-controls="appearance-panel"
  tabindex="-1">Appearance</button>` after `preferences-tab`. Its panel `#appearance-panel` has an `<h2>Appearance</h2>`
  and a `<fieldset>` with legend "Theme" and three radios, `name="theme"`, ids `theme-system`, `theme-light` and
  `theme-dark`, labelled System, Light and Dark. Under it goes
  `<small>Saved in this browser. System follows Windows.</small>`.

### `theme.js` (new, about 10 lines, added to `STATIC`)
- Read `localStorage["home-manager-theme"]` inside try/catch. For `"light"` or `"dark"`, set
  `document.documentElement.dataset.theme`. Otherwise remove it.
- Expose `setTheme(value)`, which writes the key (try/catch) and applies it.

### `shell.js`
- Add `"appearance-tab"` to the `wireTabs([...])` list (line 36).
- Wire the radios: check the stored value on load (`system` if none), and call `setTheme` on change.
- `#nav-toggle`:
  - Unhide it, and toggle `.nav-open` on `.app-shell` and `aria-expanded` on click.
  - On open, focus the first `.nav-link` in the sheet.
  - Close on Esc (return focus to the toggle), on any route change, and on a click outside.
  - Add `menu` to `ICONS` in `ui.js` (Lucide `menu`: `M4 6h16`, `M4 12h16`, `M4 18h16`).

### `ui.js`
- `amount()`: put the sign in `element("span", sign, "sign")` before the magnitude text. `textContent` stays the same,
  so existing text assertions still hold.
- Add the `menu` icon.

### `home.js`
- Delete `CHART_COLORS`. `categoryColor()` becomes `categorySlot(name)`, which returns `"cat-none"` for uncategorized
  and otherwise `cat-1..6`, with the same hash and dedupe logic over slot names.
- The donut circle and the legend swatch use `class: categorySlot(...)` instead of `stroke` and `fill` hex.
- Trend: the axis line becomes `class: "chart-axis"`, and the bar becomes `class: row.partial ? "chart-bar partial" : "chart-bar"`.
  Keep `stroke-dasharray` and `stroke-width` as attributes.

### `finance/charts.py`
- Replace `SERIES`, `GRID`/`BASELINE`/`TEXT`/`MUTED`/`SURFACE`, `BUCKET_BLUES` and `UNTAXED` with class names (the
  `c-*` list above). Every `fill=`/`stroke=` color attribute becomes `class=`. `fill="none"` and
  `fill="transparent"` stay.
- Keep the output deterministic.
- Update the module comment: colors come from the app's tokens.
- The SVG is only ever inlined through `forecastSvg()` (forecast.js:109), so CSS reaches it. No other consumer exists.

### `docs/ui.md`
See "Docs to update".

## Selector contract
| Selector | Used by | Keep / rename to | Test edit |
|---|---|---|---|
| `#nav-*` ids (home, review, transactions, receipts, spending, bills, accounts, investments, taxes, forecast, whatif, inventory, documents, inbox, unfiled, processing, donate, settings, profile) | test_browser, test_family_browser, test_home_browser, test_forecast, test_investments, test_taxes_browser, test_recurring_bills, test_share, test_whatif_browser, test_donate_browser, test_employers, test_receipt_counting | keep, moved inside `#sidebar-sheet` | none (all clicks run at ≥1280 wide) |
| `#nav-inbox .nav-count` | test_browser:283 | keep | none |
| `.nav-link[data-route]`, `.nav-group-money`, `.family-mode …` rules | shell.js, style.css | keep | none |
| `#profile-select`, `#profiles-tab`, `#directories-tab` … | test_family_browser, test_share | keep | none |
| `svg.forecast-chart`, `svg.tax-buckets`, `#forecast-charts svg` | test_whatif_browser, test_employers, test_forecast | keep (root classes unchanged) | none |
| `.home-metric`, `#home-content` | test_family_browser, test_home_browser | keep | none |
| `.meter`, `.meter-fill`, `data-status` | finance.js, home.js | keep | none |
| `.amount` text | many tests (`to_contain_text`) | keep; `.sign` span is inside | none |
| new: `#nav-toggle`, `#sidebar-sheet`, `#appearance-tab`, `#appearance-panel`, `#theme-system/light/dark` | new tests | n/a | added |

## States
- **Dark:** every page through `ui_shots --themes dark`. Look for leftover white panels, unreadable chart text,
  native controls (dates, selects, scrollbars) following `color-scheme`, and document images on `--paper`.
- **Forced theme:** with Light chosen on a dark OS, the page is light, and the reverse. The choice survives a reload.
  With storage blocked, it falls back to System without errors.
- **Empty, loading and error:** unchanged in 1a (`pageState()` is 1b). The restyled `.empty-state` and `.alert` show
  on Investments, Bills and Accounts.
- **Long text:** sidebar labels ellipsize instead of wrapping. Long folder names in the Documents tree and long merchant
  names behave as today.
- **Family profile:** `.family-mode` hiding works the same inside the sheet, and the who's-here picker shows in the
  sheet.
- **Narrow:** at 390 the menu opens over the content, the body doesn't scroll sideways, and the sheet scrolls on its own.

## Accessibility
- Focus order: skip link, brand, menu toggle (narrow), then the sheet contents in the old order, then main.
- The toggle has `aria-expanded` and `aria-controls`. Esc closes the sheet and returns focus. F6 region cycling still
  works.
- The selected nav item on `--accent` keeps a visible focus ring: add
  `.nav-link[aria-current="page"]:focus-visible { outline-color: var(--text); }`, because an accent ring on an accent
  fill is invisible.
- Theme radios sit in a native fieldset with a legend.
- Reduced motion turns off the sheet and drawer transitions.
- Over-budget meters keep their badge and text: amber plus "Over by …" and the ⚠ icon, never color alone.
- Contrast:
  - Check `--on-danger`/`--danger` and every `--chart-cat-*` against `--surface` in both themes (≥3:1).
  - Check `--text-secondary` on `--surface-sunken` (table headers) in dark.
  - Record the ratios in MASTER.md.

## Out of scope
- Page layouts, copy, nav labels and groups.
- `pageState()`, `trace.js`, `ui_v2_screens` and the parity test (all 1b).
- Any backend change other than the `STATIC` entries and `charts.py` classes.
- Phase 2 screens and dead-CSS cleanup (Phase 3).

## Verification
- **New `tests/test_style_tokens.py` (not a browser test):**
  - `style.css` has no `#[0-9a-fA-F]{3,8}\b` and no `rgb(` outside the three token blocks.
  - `home.js` and `finance/charts.py` contain no hex colors.
  - Every `var(--x)` used in `style.css` is defined in the light `:root` block.
  - Every key in the light `:root` block whose value isn't a `var()` is redefined in both dark blocks, or is on a short
    allowlist of theme-independent tokens (sizes, fonts, `--paper`).
- **New `tests/test_shell_browser.py` (opt-in browser test):**
  - The theme radio sets `data-theme`, and the computed `--canvas` changes and survives a reload.
  - `document.fonts.check('14px "Plus Jakarta Sans"')` is true after load. `/fonts/…woff2` returns `font/woff2`, and
    the CSP header is unchanged.
  - At 390×844, `#nav-toggle` is visible and `#nav-review` hidden. A click opens the sheet, clicking `#nav-review`
    navigates and closes it, and Esc returns focus to the toggle.
  - There's no horizontal overflow at 390, 768 and 1440 in both themes.
- **Run:**
  - `.venv/Scripts/python.exe -m pytest tests/test_style_tokens.py tests/test_forecast.py -q`
  - `$env:RUN_BROWSER_TESTS = "1"; .venv/Scripts/python.exe -m pytest tests/test_shell_browser.py tests/test_browser.py tests/test_home_browser.py tests/test_family_browser.py tests/test_forecast.py tests/test_whatif_browser.py tests/test_taxes_browser.py tests/test_employers.py tests/test_investments.py tests/test_recurring_bills.py -q`
- **After screenshots:**
  `.venv/Scripts/python.exe .claude/skills/ui-redesign/scripts/ui_shots.py --routes <all 16 above> --out <scratchpad>/after`.
  Compare with `before` at every width and theme. There must be no `HORIZONTAL OVERFLOW` and no page errors.
- **Manual checks:**
  - Tab through the shell at 1440 and 390 to check the focus ring and the order.
  - Check Review J/K/V/R still work.
  - Run ruff on the touched Python files.

## Docs to update
- `docs/ui.md`:
  - "Design system": the token table, typography, radii (pills now allowed for chips, status and count badges),
    sidebar width (220), the top bar under 820, and the theme switch. Point to MASTER.md.
  - "Screen rules › Conventions": charts' categorical colors are now `--chart-cat-*` tokens, not `CHART_COLORS`.
  - "Accessibility": the menu toggle and the Esc behavior.
- `docs/settings.md` (or wherever Settings tabs are described; Grep for "Privacy & security"): the Appearance tab.
- `design-system/home-manager/MASTER.md`: the new tokens (`--on-danger`, `--paper`, `--backdrop`, `--chart-cat-*`,
  `--chart-seq-*`) with their checked contrast, and the deviations above.
- `design-system/home-manager/README.md`: Phase 1a done, and next is 1b.
- `docs/open-work.md` "UI redesign" 5: remove tokens, dark theme, fonts and chart hex. `pageState()`, `trace.js`, the
  flag and the parity test remain.
