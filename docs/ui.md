# UI

The web UI (`src/home_manager/app/static`) is plain JavaScript with hash routes, no framework and no build step. The
rules to apply on every UI change are in the `app-ux` skill (`.claude/skills/app-ux/SKILL.md`): decision in view,
source beside the record, one primary button per region, tokens only, and filters in the URL. This document is the
fuller record behind those rules: the pages, the design system, accessibility and money display. Charts follow the
`forecast-charts` skill.

## Pages

The sidebar has **Search** (<kbd>Ctrl</kbd>+<kbd>K</kbd> or <kbd>/</kbd>), then **Home** and **Review** (with a count
badge). Then come a **Money** group, **Household**, and **Records** (Documents, with Inbox and Unfiled counts). The
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
| `#/taxes` | Taxes | [taxes](taxes.md) |
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

Settings is a page with tabs: **Library folder**, **Profiles & family**, **Financial preferences**, **Local models**,
**Independent checks**, **Backup & restore**, **Sharing**, **Privacy & security**.
- **Library folder.** Changing it switches libraries, so it asks for confirmation.
- **Local models.** Each model has **Test connection** (`POST /api/model-connection-tests`: lists the served models,
  loads nothing, sends no content). The model computer setting (this PC or the family GPU) is here too.
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

**Tokens** (CSS custom properties at the top of `style.css`):

| Token | Value | Use |
|---|---|---|
| `--canvas` | `#F6F7F9` | app background |
| `--surface` | `#FFFFFF` | content regions, tables, drawer |
| `--surface-sunken` | `#EFF1F4` | table header, evidence background, code |
| `--border` | `#E1E4E8` | default dividers |
| `--border-strong` | `#C9CED6` | inputs, focusable outlines |
| `--text` | `#1A1F26` | primary text and amounts |
| `--text-secondary` | `#4D5663` | labels, metadata |
| `--text-muted` | `#6B7480` | tertiary text (≥4.5:1 on surface) |
| `--accent` | `#2B5A8A` (ink blue) | primary buttons, links, selected nav, focus |
| `--accent-subtle` | `#E8EFF7` | selected row, nav hover |
| `--positive` | `#1E6B45` | money in, verified |
| `--positive-subtle` | `#E4F2EA` | verified badge background |
| `--warning` | `#8A5A00` | needs review, stale, partial |
| `--warning-subtle` | `#FDF1D8` | |
| `--danger` | `#A33A2E` | failed, past due, destructive |
| `--danger-subtle` | `#FBE9E6` | |
| `--info` | `#2B5A8A` | proposed, running (shares the accent hue) |

- **Money colors.** Money out uses the default text color with a `−` sign. Money in uses `--positive` with a `+` sign.
  Transfers are muted, with the ⇄ icon. **Red never means spending.** Red is for errors, past-due bills and
  destructive actions.
- **Typography.** The system stack: `"Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif`. Monospace is
  `"Cascadia Mono", Consolas, ui-monospace`. Every amount, date and count column uses
  `font-variant-numeric: tabular-nums`.

| Token | Size / line height | Weight | Use |
|---|---|---|---|
| `--text-xs` | 12 / 16 | 400–600 | badges, table meta |
| `--text-sm` | 13 / 18 | 400 | table body (compact), secondary |
| `--text-md` | 14 / 20 | 400 | body default |
| `--text-lg` | 16 / 24 | 600 | panel headings |
| `--text-xl` | 20 / 28 | 600 | page titles |
| `--figure-lg` | 28 / 34 | 600 | the one headline figure per page |

- **Spacing** uses a 4px base: `--space-1..8` = 4, 8, 12, 16, 20, 24, 32, 48.
- **Radii:** `--radius-sm` 4px (inputs, buttons, badges), `--radius-md` 6px (panels, drawer, popovers), `--radius-lg`
  10px (dialogs). There are no pill shapes except count badges.
- **Elevation.** Nothing in the page flow has a shadow. `--shadow-overlay` is used only for the drawer, popovers, menus
  and dialogs.
- **Controls:** `--control-sm` 28px (tables, toolbars), `--control-md` 32px (default), `--control-lg` 36px (the page's
  primary action). Table rows are 32px (compact) or 40px (comfortable), with sticky 12px semibold headers.
- **Layout.** The sidebar is 232px and collapses to an icon rail below 1280px. Content is at most 1600px wide, the
  drawer 520px, and a form column 720px.
- **Motion.** 120ms ease-out for hover and focus, 180ms for the drawer. Everything is disabled under
  `prefers-reduced-motion`. The only looping animation is the running-job indicator.
- **Components** are vanilla factory functions in `ui.js` that return DOM nodes: `element()`, `cell()`,
  `statusBadge()`, `amount()`, `dateText()`, `asyncButton()`, `alertBox()`, `emptyState()`, menus, dialogs and toasts.
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
- **Focus:** a 2px `--accent` outline with a 2px offset on every interactive element.
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
  text without it. That is lexical, not arithmetic.
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

1. **Accent color:** ink blue for interaction; green means only money in or verified.
2. **Money parts:** no backend change. The UI splits the server's `display` text lexically.
3. **Review** shows display summaries (merchant, amount, date, account, document) for every item, never bare ids.
4. **Accounts** shows per-account balances with "as of" dates only, with no total across accounts. It stays a top-level
   page.
5. **The document page** is a route, not a modal. Lists use a non-modal drawer where a detail view is needed.

## Proposed restyle: "Household ledger" (not started)

A UI/UX review on 2026-09-30 proposed a restyle. You chose the direction, a dark theme that follows Windows, and a first
round covering the foundation and key screens. None of it is built: there is no `app/static/fonts/`, no dark theme, and
the tokens above are unchanged. Follow the system above until the restyle is done; when it is, update the `app-ux`
skill and this document together.

- **Look.** A cool grey-green "index card" canvas (`--canvas #ECEFEA`, `--paper #FAFBF7`), graphite ink (`#1F2523`) and
  an indigo accent (`#34409A`). Positive, warning and danger keep their meanings. The dark theme goes on
  `[data-theme=dark]` and follows `prefers-color-scheme`, with every pair contrast-checked.
- **Type.** Source Serif 4 for page titles and headline figures (lining, tabular figures), and Public Sans for
  everything else. Both are OFL fonts, bundled locally. The scale is 12/13/14/16/20 sans and 24/32 serif. Nav labels
  are in sentence case.
- **Round one.**
  - Rewrite `style.css` into ordered sections, removing duplicate rules and routing off-token colors to tokens.
  - Fix sticky table headers. Add a phone layout below 800px and forced-colors support.
  - Add one shared loading/error/empty helper on every page.
  - Use one action vocabulary (Read, Record, Count it, Reject, Confirm, Delete, Remove).
  - Review in three columns with a sticky decision bar.
  - Home with Needs attention first.
  - A document page with the Read and Record steps in the record header, a **Matched charge** link, and technical
    details folded away.
- **Round two.** Transactions (sticky toolbar, non-modal drawer), Documents (row actions into ⋯, filters in the URL),
  Spending, Bills, Accounts (Import), Forecast (results first), Inventory, Processing, Settings, the Assistant as a
  push panel, a shortcut help overlay, and a first-run welcome.
- **Problems the review found** are listed in [open work](open-work.md#ui), whether or not the restyle goes ahead.
