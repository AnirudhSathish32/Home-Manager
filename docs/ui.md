# UI

The web UI (`src/home_manager/app/static`) is plain JavaScript with hash routes, no framework and no build step. The
rules to apply on every UI change are under "Screen rules" below. Visual direction comes from the `ui-ux-pro-max`
skill (`.claude/skills/ui-ux-pro-max/`). Where they conflict, the screen rules win. This document also records the
pages, the design system, accessibility and money display.

## Screen rules

### Layout

1. **Decision in view.** A screen that asks the user to decide (Review, reconcile prompts, confirmations) shows
   *what*, *why it needs you*, the evidence and the decision buttons together, with no scrolling, at 1366×768 and
   1440×900. Primary actions never sit below content of variable height. Tall evidence scrolls inside its own region,
   and the decision bar stays put.
2. **Source beside the record.** Wherever a record is checked against its document, the document preview sits beside
   the record. Below 900px it stacks, and the decision bar pins to the bottom of the viewport.
3. **Many-valued facts show every value.** For example, a receipt shows all of its categories, largest share first. The
   same goes for matches, sources and linked records.
4. **One primary button per region.** Destructive actions ask first, say what will happen, and focus Cancel.
5. **Filters and views live in the URL**, so Back, reload and new windows keep them.
6. **No horizontal page scroll at 390px.** Tables scroll inside `.table-wrap`.

### Conventions

- **Tokens only.** Use the `:root` block in `style.css` and add no new hex values. The redesign may replace the
  tokens, but it does so in that block.
- **Color carries meaning.** Accent means interactive. Green means money in or verified. Red means errors, past due or
  destructive. **Red never means spending.**
- **Status** always goes through `statusBadge()` and the `STATUS` map in `ui.js`, as icon, text and tone. Color is
  never used alone.
- **Money.** The browser does no arithmetic. It renders the server's text with `amount()`, right-aligned with tabular
  figures. Dates use `dateText()`/`dateDisplay()`.
- **DOM idiom.** Use vanilla factory functions (`element()`, `cell()`, `homeLink()`, `asyncButton()`). There is no
  framework and no build step. A strict CSP allows no inline scripts or styles and no CDN assets, so fonts are self-hosted
  and icons come from `icons.svg`.
- **Copy.** Use plain words from the user's side. Internal IDs and scores go in a Details disclosure.
- **Keyboard.** Every control is reachable in visual order. Review keeps J/K, V and R, and shortcuts never fire inside
  inputs. The focus ring is visible.
- **Links read from documents** are shown as text, never as live links.
- **Charts** each have a text summary and a **View data table** control. Colors come from the `--chart-*` tokens:
  categorical slots `--chart-cat-1..6` (`home.js` `categorySlot()` gives a category its `cat-N` class), the
  sequential ramp `--chart-seq-1..10`, and the `c-*` classes on the server's SVG (`finance/charts.py`).

### Verifying a layout

- Extend the opt-in browser tests (`tests/test_browser.py`, `tests/test_home_browser.py`) and run them with
  `.venv/Scripts/python.exe -m pytest tests/test_browser.py --browser`.
- On a decision screen, assert the primary button is in view at 1366×768:
  `box = page.locator("#review-confirm").bounding_box(); assert box and box["y"] + box["height"] <= 768`.
- At 390, 768 and 1440 widths, check `page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")`.
- Use synthetic data only.

## Pages

The sidebar has **Search** (<kbd>Ctrl</kbd>+<kbd>K</kbd> or <kbd>/</kbd>), then **Home** and **Review** (with a count
badge from `GET /api/review/counts`). Then come a **Money** group, **Household**, and **Records** (Documents, with Inbox and Unfiled counts). The
foot of the sidebar has **Ask**, the activity indicator, **Processing** and **Settings**, plus the **Profile** menu.
Routes are in `ROUTES` in `shell.js`.

| Route | Page | Doc |
|---|---|---|
| `#/home` | Home: the dashboard (default) | [money](money.md#home) |
| `#/search?q=` | Search across documents, transactions, items and accounts | [documents](documents.md#searching-document-text) |
| `#/review` | Review: everything that needs a decision | [Review](#review) |
| `#/transactions` | Transactions (Items and Charges views) | [money](money.md#money-pages) |
| `#/receipts` | Receipts & statements (the money store) | [money](money.md#two-stores-one-library) |
| `#/spending` | Spending & budgets | [money](money.md#category-rules-and-budgets) |
| `#/bills` | Bills & recurring | [money](money.md#recurring-bills) |
| `#/accounts` | Accounts | [money](money.md#money-pages) |
| `#/investments` | Investments | [planning](planning.md#investments) |
| `#/taxes` | Taxes (v2 with the flag: `?year=&tab=year\|built\|writeoffs\|jobs\|pack\|rules&section=&unit=`) | [taxes](taxes.md) |
| `#/forecast` | Forecast | [planning](planning.md#forecast) |
| `#/whatif` | What If | [planning](planning.md#what-if) |
| `#/inventory` | Inventory | [household](household.md#the-inventory-page) |
| `#/documents`, `#/documents/ID` | Documents and the document page | [documents](documents.md#browsing-the-library) |
| `#/processing` | Processing | [Processing](#processing) |
| `#/settings` | Settings | [Settings](#settings) |
| `#/donate` | Donate documents | [evals](evals.md#donating-documents) |

- **Family view.** In the family view, only Home, Review, Receipts & statements, Documents, the document page,
  Processing, Settings, What If and Taxes are offered (`FAMILY_ROUTES`).
- **Old links.** `#/finances?…` links redirect to the money pages.
- **Taxes v2** (`taxes_v2.js`, behind `ui_v2_screens`; design in `design-system/home-manager/pages/taxes.md`) has six
  tabs: **This year** (three answer tiles, one "What to do" region with Tax Zen's one action and "Other ways", then the
  return line by line), **Built from** (a section list beside rows of Box · From records · Yours), **Write-offs**,
  **Jobs & pay stubs** (each job's year figures, its W-4 on file and its pay stubs), **CPA pack** and **Rules &
  sources** (tax rules, the year's tax tables, every rule set as a `ruleCard`). Built from and Jobs edit one draft with
  a sticky save bar; a year or return change asks before discarding it. Tabs draw when first shown, and the URL keeps
  the year, tab, section and family return (`history.replaceState`). The family view hides Write-offs, CPA pack and
  Rules & sources, and shows its returns above This year with a Return select.
- **Today v2** (`today_v2.js`, behind `ui_v2_screens`; design in `design-system/home-manager/pages/today.md`) is the
  home route redesigned; the h1, the tab title and the sidebar label say Today only while it is on. Four figure tiles
  (Cash with its balances' date range and an "old" flag past 35 days, Net worth, Spent in the month, Money in with net
  cash flow), then **Needs you** (attention rows first, each with one action; rows with a count of 0 are left out)
  with the dated sections under it (Bills, CDs and Treasuries coming due, Weekly check-in, Return windows closing,
  Warranties ending soon, each only when it has rows) beside the month's **budgets** (amber meters, "Over by" or
  "left"), then v1's trend and donut, and "What these numbers cover" folded. Under 1100px it is one column (Needs you,
  budgets, dated sections) and tiles go 2×2. The family view drops the budgets, check-in, returns and warranties and
  adds "Each person", the family's net worth and "Counted once". The URL keeps `?month=&currency=&months=`.
- **Ask.** The Ask panel opens from anywhere ([assistant](assistant.md#the-ask-panel)).

### Review

`#/review` is a two-pane queue. On the left, the groups, each with a count. On the right, the selected item's **what**,
**why it needs you** and **evidence**, with the decision buttons.
- **Keyboard.** <kbd>J</kbd>/<kbd>K</kbd> move, <kbd>V</kbd> confirms and <kbd>R</kbd> rejects. Each decision advances to
  the next item.
- **Undo.** Record decisions offer Undo for 8 seconds, returning the record to Needs review. Link and issue decisions
  are final.
- **Groups**, in order (`REVIEW_GROUPS` in `review.js`): Questions, Proposed matches, Records to verify, Investment and
  loan documents to confirm, Warranties to confirm, Tax tables to confirm, Possible write-offs and tax payments,
  Recurring payments, Receipt items to identify.
- **Beside the queue:** statements awaiting reconciliation, image groups to combine, receipts with no matching charge,
  and counts of documents that couldn't be processed or are unfiled. In the family view, family routing replaces the
  unmatched-receipts panel.
- **Plain language.** No internal ids or scores in the default view; match signals are in words ("Same amount · 2 days
  apart · merchant matches"). The score and method are in a Details disclosure.
- **When a decision fails,** the item stays selected with an inline error, and the queue doesn't advance.

### The document page

`#/documents/ID[?version=HASH][&lines=…]` is a full-width view, because checking evidence side by side needs the
width. It is opened over the current page, and Back (or <kbd>Esc</kbd>) returns to the list with its filters, page and
scroll position.
- **The title** is set once, from the best name available, and never changes as data loads.
- **Two panes.** The left pane is the image, with region highlights, or the text, with PDF pages. The right pane is the
  record: field rows with **Find**, plain-language checks, items or transactions, the linked charge, the split and
  rewards.
  - Clicking a region highlights the rows that cite it.
  - The decision model's result is an advisory disclosure under Checks.
- **The footer** shows the steps (Read → Recorded), with Details, History and audit tabs. Re-run actions live there and
  in the `⋯` menu.
- **States:** loading, unread (**Read document**), reading (live stage, Cancel), read but not recorded, needs review,
  verified (with Undo), failed (reason plus Retry), cancelled, publication blocked (for example, no currency), and an
  earlier version (with a banner).
- The page also hosts the split controls for several receipts in one file, the page order of combined images, and
  "Also found" duplicate links ([documents](documents.md)).

### Processing

- **Pipeline lanes:** Capture, Transcription, Extraction, Item identification and Reconciliation, each with its live
  state and last run. Cancel is offered only where supported (inference); capture can't be interrupted.
- **Actions:** **Scan Inbox**, **Read all documents**, **Reconcile now**, and **Watched folders**.
- **Jobs.** One job history across every kind of work (`GET /api/jobs[?kind=…]`), with a kind filter and links to
  documents. The last reconciliation is shown with its counts (`GET /api/finance/reconciliation-runs`).
- **Model runs.** Telemetry filtered by task and status, with `~` marking estimates.

### Settings

Settings is a page with tabs: **Library folder**, **Profiles & family**, **Financial preferences**, **Appearance**,
**Local models**, **Independent checks**, **Backup & restore**, **Sharing**, **Privacy & security**.
- **Appearance.** Theme: System (the default, following Windows), Light or Dark. The choice is saved in this browser
  (`localStorage["home-manager-theme"]`, `theme.js`); with storage blocked it falls back to System.
- **Library folder.** Changing it switches libraries, so it asks for confirmation.
- **Local models.** Each model has **Test connection** (`POST /api/model-connection-tests`: lists the served models,
  loads nothing, sends no content). The model computer setting (this PC or a shared GPU) is here too.
- **Model settings while busy.** Saving model settings is disabled while the model queue is busy, with an
  explanation.
- **Backup & restore.** Backup writes to a separate folder; restore builds a new library
  ([operations](operations.md#backups)).

## Design system

**Principles**
- **Hierarchy through type and space, not boxes.** Panels are separated by a heading and 32px of space. A border appears
  only where a region needs containment: tables, the drawer, the document page panes.
- **Color only means something.** The neutral palette carries layout, one accent carries interactivity, and semantic
  colors carry state.
- **One primary button per region.**
- **A calm default.** Healthy states are quiet (no "Succeeded" badges everywhere), and exceptions stand out.

**Tokens** are CSS custom properties at the top of `style.css`, in three blocks: light `:root`, then dark under
`prefers-color-scheme: dark` (unless Light was chosen) and again under `:root[data-theme="dark"]` (Dark chosen in
Settings › Appearance). The values, light and dark, and their checked contrast are in
`design-system/home-manager/MASTER.md` "Color tokens" (direction C · Family). No color appears outside the token
blocks, and `tests/test_style_tokens.py` enforces it. Beyond MASTER's table:
- `--info` is `--accent`, and `--neutral-subtle` is `--surface-sunken`.
- `--on-accent` and `--on-danger` are the text on accent and danger fills, `--danger-hover` the danger button's hover.
- `--paper` stays white in both themes, behind document images (`#receipt-image-frame`, `.donate-frame`).
- `--backdrop` is the dialog backdrop.
- `--chart`, `--chart-track`, `--chart-grid`, `--chart-baseline`, `--chart-cat-1..6` and `--chart-seq-1..10` color
  the charts and meters ("Conventions").

- **Money colors.** Money out uses the default text color with a `−` sign. Money in uses `--positive` with a `+` sign.
  The sign sits in a fixed-width slot (`.amount .sign`) so magnitudes line up. Transfers are muted, with the ⇄ icon.
  **Red never means spending**, including an exceeded budget: the meter is amber with "Over by …" and the ⚠ icon. Red
  is for errors, past-due bills and destructive actions.
- **Typography.** Plus Jakarta Sans (variable, 200–800) for UI and figures, and JetBrains Mono 400/500 for code and
  source lines. Both are self-hosted woff2 in `app/static/fonts/` under the SIL OFL 1.1, with the license files beside
  them, and the CSP is unchanged (`font-src` falls back to `'self'`). The fallbacks are `"Segoe UI Variable Text",
  "Segoe UI", system-ui` and `"Cascadia Mono", Consolas, ui-monospace`. Every amount, date and count column uses
  `font-variant-numeric: tabular-nums`.

| Token | Size / line height | Weight | Use |
|---|---|---|---|
| `--text-xs` | 12 / 16 | 500–600 | badges, table meta, nav group labels |
| `--text-sm` | 13 / 18 | 400–550 | table body, secondary, buttons |
| `--text-md` | 14 / 20 | 400 | body default, nav |
| `--text-lg` | 15 / 22 | 600 | section headings (h2, h3) |
| `--text-xl` | 26 / 32 | 700, −0.02em | page titles (h1) |
| `--figure-lg` | 28 / 34 | 700 | headline figures |
| `--figure-xl` | 30 / 34 | 700 | the answer at the top of a breakdown |

- **Spacing** uses a 4px base: `--space-1..8` = 4, 8, 12, 16, 20, 24, 32, 48.
- **Radii:** `--radius-sm` 6px (inputs, buttons), `--radius-md` 10px (nav items, table wrap, alerts, menus, toasts),
  `--radius-lg` 14px (panels, dialogs). `--radius-pill` is only for chips (`.chip`), status badges and count badges.
- **Links** in running text keep a thin underline, because accent against body text is under 3:1. Text-link buttons
  (`button.link-button`) underline only on hover.
- **Tables** sit in `.table-wrap` (`--surface`, `--border`, `--radius-md`). Inside a panel, dialog, disclosure or pane
  the wrap drops its box, so regions never nest.
- **Elevation.** Nothing in the page flow has a shadow. `--shadow-overlay` is used only for the drawer, popovers, menus
  and dialogs.
- **Controls:** `--control-sm` 28px (tables, toolbars), `--control-md` 32px (default), `--control-lg` 36px (the page's
  primary action). Table rows are 32px (compact) or 40px (comfortable), with sticky 12px semibold headers.
- **Layout.** The sidebar is 220px and collapses to a 64px icon rail below 1280px. Below 820px it becomes a sticky top
  bar (brand and a **Menu** button, at most 56px high), and the menu opens the sidebar's contents as a sheet under it.
  The selected nav item is an `--accent` fill with `--on-accent` text. Content is at most 1600px wide, the drawer
  520px, a form column 720px, and the breakdown panel `--panel-width` (360px, the same in both themes).
- **Motion.** 120ms ease-out for hover and focus, 180ms (`--motion-panel`) for the drawer and the menu sheet. Everything is disabled under
  `prefers-reduced-motion`. The only looping animation is the running-job indicator.
- **Components** are vanilla factory functions in `ui.js` that return DOM nodes: `element()`, `cell()`,
  `statusBadge()`, `amount()`, `dateText()`, `asyncButton()`, `alertBox()`, `emptyState()`, menus, dialogs and toasts.
  `pageState(host, load, {loading, what, content, needsLibrary})` gives a page its loading, error and no-library
  states in a `.page-state` host after its header: nothing for 300 ms, then a muted "Loading …" line with a spinner
  (`role=status`, `aria-busy` on the page); an error is an `alertBox` (`role=alert`) with Technical details and Retry,
  shown in place of the shell's toast; without a library, "Set up your library to see …" with Open Settings. `content`
  is hidden on an error or without a library. A newer call wins over an older one. Retry keeps focus on the host while
  it loads, then moves it to the page heading. Empty data stays each page's own `emptyState()`. Bills, Accounts,
  Investments, Forecast and Taxes use it (Taxes hides `#taxes-body`, so the year select stays usable).
  This matches the strict CSP (`script-src 'self'; style-src 'self'`): no inline scripts or styles, no CDN fonts,
  scripts or chart libraries. Icons come from the vendored `icons.svg` (a Lucide subset, ISC license).
- **Charts** are inline SVG with a data-table fallback. Home draws its own; the forecast's are drawn by the server
  (`finance/charts.py`).

**Status vocabulary.** There is one `STATUS` map in `ui.js`, giving each status an icon, text and tone, never color
alone. Add new states to that map.

| Internal | Label | Tone |
|---|---|---|
| `proposed` | Proposed | info |
| `needs_review` | Needs review | warning |
| `verified` | Verified | positive |
| `rejected` | Rejected | neutral (struck through) |
| `queued` | Queued | neutral |
| `running` | Processing | info (animated) |
| `succeeded` | Done (usually hidden) | positive |
| `partial` | Partly done | warning |
| `failed` | Failed | danger |
| `interrupted` | Interrupted | warning |
| `cancelled` | Cancelled | neutral |
| `imported` | Imported | positive |

**Errors in user language.** `api()` maps the HTTP status and known messages to a sentence, with the server's `detail`
kept in a "Technical details" disclosure.
- 401: "This session has expired. Reopen Home Manager from its launcher."
- An unreachable model server: "The local model server isn't responding at 127.0.0.1:1234. Start it in LM Studio,
  then retry."
- The server never puts document content in errors, and the UI never adds it back.

## Accessibility

- **Landmarks:** `nav` (sidebar), `main`, `aside` (drawer), one `h1` per page, and an `h2` for each panel.
- **Keyboard.**
  - Every control is reachable, in visual order.
  - Tables are navigable with the arrow keys when focused (roving tabindex), and <kbd>Enter</kbd> opens the row.
  - <kbd>F6</kbd> cycles between the sidebar, main and drawer regions.
  - Dialogs use native `<dialog>`, set an initial focus, and return focus to the trigger on close.
  - Shortcuts are never required and never fire inside inputs.
- **Narrow menu.** Under 820px, `#nav-toggle` carries `aria-expanded` and `aria-controls="sidebar-sheet"`. Opening it
  focuses the first nav link. <kbd>Esc</kbd> closes the sheet and returns focus to the toggle, and a route change or a
  click outside also closes it. Focus order is the skip link, the brand, the toggle, the sheet, then main.
- **Focus:** a 2px `--accent` outline with a 2px offset on every interactive element. On the selected nav item (an
  accent fill) the ring is `--text`.
- **Contrast.** Every text token is at least 4.5:1 on `--surface` and `--canvas`. Badge text is at least 4.5:1 on
  subtle backgrounds. Non-text UI (input borders, focus) is at least 3:1.
- **Never color alone.** Every status has an icon and text. Amounts carry a `+`/`−` sign, and money in or out is also
  announced.
- **Live regions.** One polite region for toasts and job completion. Running-job progress is announced at start and
  finish, not every second.
- **Tables and charts.** Tables use `<th scope>` and `aria-sort`. Charts carry a data table.
- **Zoom.** The UI is usable at 200% zoom on a 1440px screen. Browser tests check 390, 768 and 1440px widths for
  horizontal overflow.

## Money and dates on screen

- **No money arithmetic in the browser.** It never sums, subtracts, converts or rounds; totals come only from server
  tools. `amount()` takes the sign from the leading `-` of the server's `decimal`, and shows the server's `display`
  text without it. That is lexical, not arithmetic. `amount(value, {magnitude: true})` adds no sign glyph at all (not
  even `−`) and no direction, for figures whose label says which way (tax figures).
- **No other figures worked out in the browser either.** The server returns them ready to show:
  - percents as `*_percent` text beside each `*_bp` (`core/money.py` `percent_text`);
  - Home's category shares as `share_bp` (whole basis points summing to 10,000, so the donut closes) with
    `categories_chartable`;
  - the budget meter's `meter_percent`, `remaining_state` and `over`;
  - each upcoming bill's `group` (overdue, this_week, later);
  - the Review badge and group counts from `GET /api/review/counts` (uncapped), and the check-in count with them;
  - counts the pages show: the independent check's `confirmed`/`scored`/`unscored`, check-in `applied`/`failed`,
    search `total`, an employer folder's `total`, Tax Zen's `aim` text, a job's `paydays_without_stub`.

  `.minor` is read only for chart pixel geometry and for "is there any" checks.
- **Months** show as `September 2026` (`monthText()` in `ui.js`).
- **Currency.** The home currency uses its symbol. Every other currency uses its ISO code. Each currency shows its own
  minor-unit precision (JPY 0, USD 2).
- **Alignment.** Amounts are right-aligned with tabular figures, and the sign sits in a fixed-width slot so digits
  line up.
- **Dates.** Tables show `Sep 24` (current year) or `Sep 24, 2025`. Detail views show `Sep 24, 2026`. Tooltips and
  provenance show ISO `2026-09-24`. Relative dates ("2 days ago") are used only for activity and freshness, never for
  financial dates.
- **Balances** always carry "as of <date>". Credit card balances are labelled "Owed". Statement balances from
  different dates are never added into one total.

## Decisions

1. **Accent color:** one accent for interaction (cobalt from the redesign, `design-system/home-manager/MASTER.md`);
   green means only money in or verified. An exceeded budget is amber, never red (2026-10-06).
2. **Money parts:** no backend change. The UI splits the server's `display` text lexically.
3. **Review** shows display summaries (merchant, amount, date, account, document) for every item, never bare ids.
4. **Accounts** shows per-account balances with "as of" dates. It stays a top-level page. Since 2026-10-06, Today shows
   **Cash** and **Net worth** across all accounts (`worth.today`), with the date range and stale accounts flagged.
   This reverses the earlier "no balances on Home" for Today v2 (built 2026-10-10); v1 Home still shows none.
5. **The document page** is a route, not a modal. Lists use a non-modal drawer where a detail view is needed.

## Redesign: calculation observability

Approved 2026-10-04. The backend is built: the trace contract with a trace for each calculation, provenance,
corrections with who and why, the rule registry, stale detection and manual transactions (see "What's built" under
"Trace contract"). The screens and components aren't built yet. The work items left, in build order, are in
[open work](open-work.md#ui-redesign). The session process (phases, per-screen hand-offs, screenshots on synthetic
data) is in the `ui-redesign` skill. This design replaces the 2026-09-30 "Household ledger" restyle proposal. Phase 0
chose the visual direction (C · Family, 2026-10-06), recorded in `design-system/home-manager/MASTER.md`. Some of that proposal's round-one ideas carry over here: one
loading/error/empty helper, one action vocabulary, Needs attention first on Home, and the Read and Record steps in the
document page's record header.

### The principle

Every number on screen can be explained. These rules override visual or layout preferences.
1. **Traceable.** Any figure opens its breakdown:
   - the formula in plain words;
   - every input with its value;
   - the steps in order with running values;
   - the rule source, version and tax year;
   - when it was calculated, and whether an input changed since.
2. **Provenance on every input:** entered (by whom, when), read by a model (which model, the independent check's doubt,
   the source line), imported (file and row), worked out (a link to its own breakdown), or changed (original, new, who,
   when, an optional reason).
3. **Model-read values aren't silently trusted.** A total that depends on a value still needing review shows it.
4. **The browser does no math** (see "Money and dates on screen"). A figure the backend can't explain isn't shown as
   traceable.
5. **Totals reconcile.** The components are one click away and visibly sum to the total, including any rounding
   adjustment.
6. **Progressive disclosure.** The answer comes first, the breakdown one interaction away, and input detail one more
   level down. The default view stays uncluttered.

### Trace contract

`GET /api/traces/{ref}` returns the breakdown of one figure. It's built in `core/trace.py`.

```jsonc
{
  "ref": "spending.net?month=2026-09&currency=USD",
  "label": "Net spending, September 2026",
  "result": {"minor": -184233, "currency": "USD", "decimal": "-1842.33", "display": "1,842.33 USD"},
  "formula": "Purchases counted this month, minus refunds. Transfers and pending lines aren't counted.",
  "steps": [{"n": 1, "label": "Card and bank purchases", "op": "+", "value": {}, "running": {}, "trace": "…", "count": 42}],
  "rounding": {"method": "half_even_minor", "adjustment": null, "note": "…"},
  "inputs": [{"key": "txn:812", "label": "Costco · Sep 3", "value": {},
              "provenance": {"kind": "extracted|imported|manual|computed|override|rule|rate",
                             "document": {"id": 55, "lines": ["page-1-line-12"], "quote": "TOTAL 84.12", "page": 1},
                             "model": {"id": "…", "run": "…", "at": "…"}, "confidence": {"level": "doubted", "by": "independent check"},
                             "import": {"file": "…", "row": 14}, "actor": {"person": "…", "at": "…"},
                             "override": {"original": {}, "reason": "…"}},
              "verification": "confirmed|checked_automatically|needs_review", "trace": null}],
  "inputs_page": {"total": 42, "next": "…"},
  "rule": {"name": "…", "source": "…", "version": "…", "tax_year": 2026, "checked_on": "…", "cpa_reviewed_on": null},
  "computed_at": "…", "inputs_hash": "sha256:…", "stale": false,
  "verification": {"state": "verified|partial|unverified", "unverified_count": 3, "unverified_value": {}},
  "reconciles": true
}
```

- **Figures.** Every number the API returns is a *figure*: the `money()` dict (`core/money.py`) plus `trace` (a ref)
  and `verification`. Old fields stay, so screens that haven't been redesigned keep working.
- **No parallel explainer.** A `Recorder` (`step`, `input`, `rule`, `round`) is passed into the existing calculation
  functions; its default does nothing. A trace request re-runs the same function with a live recorder. Tests assert
  `reconciles`, and that `trace.result` equals the figure shown.
- **Verification states.** Confirmed means a person confirmed it, or it was imported. Checked automatically means
  `review_source='automatic'`. Needs review means `review_status='needs_review'`. **Only needs review** flags a total
  as unverified; checked automatically gets a quieter label inside the breakdown.
- **Who.** A who's-here picker in the sidebar foot chooses the person for the session. The app sends it as
  `X-HM-Actor`, the server validates it against the profile's people, and it is stored on corrections, review events,
  tax input changes and manual entries.
- **Source.** The breakdown shows the cited line highlighted in the text pane, the quote and the page (from the line
  id). An image region is drawn only where an older reading recorded one, and there's no geometry pass.
- **Rules.** Each rule set (tax tables, supplemental rates, the meals share, the RMD table, HSA and mortgage limits, AOTC,
  safe harbor) has a version, tax year, source and checked date. "Not CPA-reviewed" is shown as a neutral fact, not a
  warning.

#### What's built

- **Traces.** `core/trace.py` has `Recorder` (the default `NULL` does nothing; `add()` is a signed step), `figure()`,
  `ref()`, `build()`, `verification_of()` and `remember()`. `finance/traces.py` maps a ref name to the calculation that
  re-runs with a live recorder, and `GET /api/traces/{ref}` serves it. A step that is itself a figure carries its ref,
  so a breakdown opens the next one down. Figures worked out with the app's settings, tables or engine (tax and some
  wealth figures) are built with the Manager as context (`CONTEXT_TRACES`). `tests/test_traces.py` checks every one:
  `reconciles`, and that the trace's result is the figure shown. Traced figures:
  - **Ledger and spending** (`finance/traces.py`): `spending.net`, `cashflow.net`, `cashflow.in` (money in alone),
    `spending.category`, Home's
    `spending.other` and `spending.gross`, `spending.usd` (each converted line with its ECB rate), `split.receipt` and
    `split.charge` (largest-remainder cents as the rounding row), `budget.remaining`, `budget.projected`,
    `recurring.total` (a month or a year), `bill.expected` (the last three payments averaged) and `account.balance`.
  - **Taxes** (`finance/tax_traces.py`): `tax.result` and `tax.line` (the engine's own lines as a chain: a total traces
    to the lines it adds up; any other line is its engine's own step), `tax.node` (one step of the engine's worksheet,
    [taxes](taxes.md#the-engines-worksheets): a sum or difference as signed steps, a smaller-of or larger-of as the input
    it took, a rate, product, rounding or rate table with its inputs and the rule as a card, the branch that applied in
    the formula text, and the rule's citation as the card; facts join `tax.field` and `tax.job`, and an engine default
    says so), `tax.field` (each tax form's box, each sale lot by lot, each tag line, each estimated
    payment, what's projected, and anything typed over it) and `tax.job`, `tax.tags`, `tax.safe_harbor`, and Tax Zen's
    `taxzen.advance`, `taxzen.extra`, `taxzen.range` (each end of the likely range), `taxzen.cushion`, `taxzen.state`,
    `taxzen.w4` (a paycheck's withholding with a W-4 answer, Pub 15-T bucket by bucket) and `taxzen.w4_year_end`.
    A family return's figures carry `unit=unit-<id>`, and each member's share of an input traces on their copy.
  - **Pay and plans** (`finance/tax_traces.py`): `paystub.tax` (a pay stub's estimated income tax, Social Security or
    Medicare); the planner's and a plan's paycheck: `paycheck.net` (a paycheck or a month) and `paycheck.line` (each
    tax), from the paycheck's own input; `taxzen.paycheck` and `taxzen.plan` (the year at that pay); `plan.actual`
    (each plan-against-actual figure).
  - **Wealth** (`finance/wealth_traces.py`): `investments.value`, `investments.total`, `investments.holding` (a CD or
    Treasury from its terms, an I bond a rate period at a time), `investments.lot_gain`, `investments.rmd`,
    `investments.rmd_left`, `worth.today` (cash, assets, loans, net worth), and `forecast.cash` and
    `forecast.net_worth` for every month and year's end of the Forecast and of each What If plan (the ref holds the
    input, or the plan, and the day it was worked out).
  - **Family** (`finance/traces.py`): `family.spending.net`, `family.cashflow.net`, `family.cashflow.in`, `family.spending.category`,
    `family.spending.gross`, `family.spending.other` and `family.worth.today` add up each member's own figure. Any ref
    with `member=<id>` runs the same calculation on that member's read-only copy.
- **Review state.** A breakdown takes its inputs as correct: figures don't carry whether an input still waits in Review
  (decided 2026-10-05). The trace's own `verification` roll-up is informational.
- **Stale.** Opening a trace compares its `inputs_hash` with the one in `figure_snapshots` for that ref, then stores the
  new one. Home (net spending and cash flow), Taxes and the family's returns (the refund or amount owed) do the same
  when they show the figure (`traces.shown`, `traces.shown_tax`, `traces.shown_family_tax`), so the figure carries
  `stale` without its breakdown being opened. A return figure (`tax.result`, `tax.line`, `tax.node`) also hashes its
  engine's pinned SHA-256 (`build(..., hash_extra=)`), so a changed engine marks it stale too.
- **Provenance.** `finance/provenance.py provenance_for(db, type, id, field)` is served at
  `GET /api/provenance/{type}/{id}?field=`. It resolves imported (file, row), manual (who, when), extracted (model, run,
  cited lines, quote, page from the line id, the independent check's doubt), a market rate, and override (original,
  newest value, who, when, why, how many times). Trace inputs carry a light provenance (kind and the record) and the
  page fetches the full one.
- **Who's here.** The picker in the sidebar foot shows when the profile has more than one person (the owner, the
  spouse named on the latest return, and every member in a family). The choice lasts for the browser session and is sent as `X-HM-Actor` (URI-encoded). The server
  checks it against `Manager.people()`: an unknown name is refused (400), and with one person the server fills in that
  person itself. `core/actor.py` holds it for the request. It's stored on corrections, review events, family
  assignments, budget changes, typed tax changes and manual transactions.
- **Corrections** (`record_corrections`, with `reason` and `actor`): receipts, bills, pay stubs, statements,
  transactions (date, amount, direction, merchant, type; a category set by hand is kept as one too), account values,
  tax form boxes and holdings (rate, maturity, a dated value). Each one outlives a new reading of its document. The
  endpoints are in [money](money.md#corrections).
- **History.** Budgets keep `budget_changes`, served at `GET /api/finance/budgets/history`. Typed tax values keep
  `tax_input_changes`: the records' value at the time, before and after, who and why, served at
  `GET /api/tax/year/{year}/changes`. The tax view's `typed_over` lists each typed value beside the records' value.
- **Rules.** `finance/rules.py RULES` gives each rule set a version, source, checked date (None when no check is
  recorded) and a pinned digest of its values. `GET /api/rule-sources` lists them. Tax tables store `rule_version`.
- **Timestamps.** Receipt items and rewards, pay stub lines and tax form boxes have `created_at`/`updated_at`.
- **Manual transactions.** See [money](money.md#manual-transactions).

### Observability components

These are vanilla factories in `app/static/trace.js`, loaded after `ui.js`. They use tokens only and are CSP-safe.
`figure`, `breakdownPanel`, `provenanceBadge` and `ruleCard` are built (Phase 1b). Taxes v2 is their first user.
`tests/test_trace_components_browser.py` mounts them in the real app with the synthetic dashboard's traces.
`confirmCorrect`, `sourceViewer` and `historyList` come with the To check and document page session.

- **`figure(fig, {size, signed, magnitude})`** is a `button.figure-button` (`data-figure-ref`, `data-figure-display`,
  `data-signed`, `data-magnitude`, `aria-controls`, `aria-expanded`) around `amount()`, flagged `unconfirmed` when the
  figure's verification is `needs_review`, partial or unverified, and `stale` when it changed. A `.figure-tile` holding
  the open figure gets the accent border and ring. `signed` and `magnitude` go to `amount()`; a tax figure uses
  `magnitude` and its label gives the direction ("Refund", green with `+`; "You'd owe", text color with no sign).
- **The breakdown follows its opener's sign:** its answer, the Running column and "Sums to" use the opener's `signed`
  and `magnitude` (drilled traces keep them). Step values keep their `op` glyph.
- **The breakdown panel** is one `<aside id="breakdown">` after `</main>`: a 360px column beside the page from
  1180px, the same panel floating over the page's right edge (`--shadow-overlay`, z-index 30) at 900–1179px, and a
  bottom sheet up to 70vh below 900px. Opening moves focus to its title; a step or input with a trace drills in as a
  breadcrumb; Esc goes back one level, then closes and returns focus to the figure. Its fetch goes through
  `pageState`, so a failed trace shows its own error with Retry (and Close).
- **Provenance labels** are `STATUS` entries `prov_manual`, `prov_extracted`, `prov_imported`, `prov_computed`,
  `prov_override`, `prov_rule` and `prov_rate` (plus `unconfirmed` and `stale`); `statusBadge()`'s 4th argument puts the
  server's details in the label and keeps the tone and icon.

| Component | Behaviour |
|---|---|
| `figure(fig)` | A button around `amount()`. Its underline appears only on hover or focus. Unverified shows an icon + "unconfirmed"; stale shows an icon + "changed". Enter opens the breakdown. No `trace` ref means a plain `amount()`. |
| `breakdownPanel(ref)` | Non-modal: beside the content at 1440, a bottom sheet under 900. It shows the answer and formula; a steps table (n, label, op, value, running); a rounding row; a "Sums to" footer with ✓; paged inputs (unverified first); the rule card; and "Calculated … · inputs unchanged". Computed inputs open as breadcrumbs, and Esc goes back. |
| `provenanceBadge(prov)` | Icon + text through the `STATUS` map: Entered by …, Read by model …, Imported · file row, Worked out, Changed from … · reason, the rule name, the ECB rate date. |
| `confirmCorrect(input)` | Confirm uses the same endpoint as Review V. Correct is an inline value + **optional** reason, with a server-computed preview of the affected figures. It offers Undo for 8 s. |
| `sourceViewer(doc, lines)` | Reuses the document page's highlighting (`receipt.js`). Text read from documents stays text. |
| `historyList(record, field)` | Corrections, review events and tax input changes, newest first: when, who, from → to, why. |
| `ruleCard(rule)` | Name, source as text, version, tax year, checked on, CPA review state. |

### Redesigned navigation

```
Search · Today (#/home) · To check (#/review)
Money:          This month (#/spending) · Transactions (+ Add, Import) · Bills & subscriptions · Accounts (+ Import)
Taxes:          tabs This year · Built from · Write-offs · Jobs & pay stubs · CPA pack · Rules & sources
Wealth & plans: Investments · Forecast · What If
Home & things:  Inventory tabs Check-in · Items · Warranties · Returns · Item insights
Records:        Receipts & statements · Documents · the document page
Footer:         Ask · Processing (+ Data health tab) · Settings (Donate moves here; route kept) · Who's here
```

- **Hidden features get a home:**
  - Ledger health becomes Processing › Data health.
  - Reviewer settings go in Settings › Independent checks.
  - Decision-model test goes in Settings › Local models.
  - Tax businesses edit and delete go in Taxes › Built from.
  - Tax tags on receipts and items go on the document page and in the drawer.
  - Item analysis becomes Home & things › Item insights.
  - Reasoning and organization runs go in the document page's Details.
- **Kept as they are:**
  - Review's two panes with J/K/V/R.
  - The document page's source beside the record.
  - Accounts as per-account balances (the cross-account Cash and Net worth figures live on Today).
  - The pay-stub tax explanation and the Taxes input kinds, which already work this way.

### Number display

- Amounts are server `display` text through `amount()` only. Hand-typed "$" is removed. Money out is `−` (U+2212) in a
  fixed sign slot; money in is `+` and `--positive`. The UI never uses parentheses.
- Percentages are server `*_percent` text. The browser doesn't convert basis points.
- When the server reports a rounding adjustment, it is shown as a row ("Rounding: +0.01"). A cent is never hidden.
- Verified, unverified, stale and changed each carry an icon and text, never color alone.

### Migration

- **The flag** is `HouseholdConfig.ui_v2_screens`, a per-profile list of route names (lower-case letters, at most
  32), sent in `/api/settings` and set with `PUT /api/ui-screens` `{routes}` or Settings › Appearance › New screens
  (one checkbox per registered screen). The Preferences form sends the list back, so saving it keeps the flag. The old
  loader stays until its screen passes. Old and new screens may coexist, since the app isn't in daily use yet.
- **A v2 screen** registers itself in `V2_SCREENS` (`route → {title, show}`, declared in `app.js` so a screen's script
  can register before `shell.js` routes the first page) and is a `data-ui="v2"` section with the same `data-page` as
  the old one. `showRoute` shows the v2 section and calls its `show` when the route is on the list; sections without
  `data-ui` are v1. Registered: `taxes` (`taxes_v2.js`), `home` (`today_v2.js`).
- `tests/test_ui_parity.py` (browser, synthetic seed, with `seed_tax_year` from `test_taxes_browser.py`) checks that
  every figure on a new screen has a ref, that it equals its trace's result and reconciles (`check_figures`), and that
  it matches the old screen's values (`v1_amounts`: the old screen's `.amount` titles and its text, since old screens
  write some amounts inside sentences; a figure's unsigned form counts too). Each Phase 2 session adds its
  `(route, v1 route)` pair to `MIGRATED`; it has `("taxes", "taxes")`, skipped when Engine 1 doesn't cover this year,
  and `("home", "home")`. `NEW_ON_V2` lists ref prefixes a v2 screen shows that the old one never did (Today's
  `worth.today`, `budget.remaining`, `budget.projected`); those are checked against their trace only.
  The harness's self-test also checks that it fails on a seeded mismatch. The parity run sees a screen's first tab
  only; the screen's own browser test checks the other tabs' figures.
- **Passing tests are enough** to delete an old screen; no separate sign-off.
- Phase 0's visual directions are shown as browser pages.
