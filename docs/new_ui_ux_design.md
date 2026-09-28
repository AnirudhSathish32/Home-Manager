# UI/UX review and round-one redesign: "Household ledger"

## Context
The user asked for a thorough UI/UX review of the whole app (colours and spacing included), using the frontend-design
skill rather than the current `app-ux` token limits. Two read-only audits covered every screen and the full style
sheet. The user chose the **Household ledger** direction, a **dark theme that follows Windows**, and
**round one = foundation + key screens**. Round two applies the new layouts to the remaining screens.

**Product brief.** A private, local ledger and filing cabinet for one household. Its jobs:
- check what the machine read against the paper (Review, the document viewer);
- see where the money went (Home, Transactions, Spending).

## The review

### Worth keeping
- **Honest money.**
  - Exact server-formatted amounts, never summed across currencies.
  - Pending and "not counted" totals kept apart.
  - A coverage note on Home.
- **Evidence.**
  - Source beside the record in the document viewer, with Find buttons on every row.
  - Clicking an image region finds the rows that cite it.
- **Review basics.** The what / why / evidence structure, plain-language match reasons, J/K/V/R shortcuts, and undo
  toasts.
- **Transactions.**
  - Filters kept in the URL, with period presets and a readable filter summary.
  - Rule creation from the drawer.
- **Home charts.** Focus and hover details, a data-table fallback, and dashed bars for partial months.
- **Inventory check-in.** The "confirm these changes" step.
- **The import dialog.** Live preview and remembered account.
- **Security and basics.**
  - The strict CSP and no network assets.
  - Reduced-motion support and a global focus ring.
  - A solid token base: 4px spacing, three radii, six type sizes.

### Visual system problems (`style.css`, 589 dense lines)
- **Generic look.** Cool grey, ink blue and Segoe UI: correct, but indistinguishable from any business tool.
- **Too many boxes.** Every section is a bordered card, against the plan's own "type and space, not boxes".
- **Off-token colours.**
  - Budget meters: `#dbe8f8 #2a78d6 #fab219…` (346-350)
  - Receipt overlay orange: `#C2410C` (463)
  - `#fff` and `#FAFBFC`
  - Home chart hex colours in `home.js`
- **Off-token sizes.**
  - Text: 10, 11, 18 and 30px (a `clamp()` goes past the largest token).
  - Radii: 999px and 3px.
  - Spacing: many raw 2px, 5px and 6px values.
- **Duplicated rules that fight each other.**
  - `.review-detail` sets its colour twice, and the grey one wins (378 vs 402).
  - `.review-actions` twice (387 vs 403).
  - `.folder-link`, `.batch-status`, `.connection-result`, and two different "quiet" buttons.
  - Seven different "selected" styles.
- **Sticky table headers never stick.** `.table-wrap { overflow-x:auto }` becomes the scroll container.
- **Append-only structure.** Forecast and edit-form rules sit after the Responsive block, and the Review rules are
  split in two.
- **Small-screen and theme gaps.**
  - No phone layout: below 800px a 64px icon rail stays.
  - At 1279px or narrower the rail hides search, Inbox and Unfiled.
  - No dark mode, and no forced-colours support.
- **Weak focus in menus.** Menu items lose the focus outline (202).
- **All-caps nav group labels** (116).

### UX problems, cross-cutting
- **Things buried below the fold.**
  - Review's decision buttons sit under a 360px thumbnail that loads late.
  - Home's "Needs attention" comes after both charts.
  - Forecast results come after two forms.
  - Processing actions are the fourth panel.
  - The document viewer's Read and Record buttons live in a footer below both panes.
- **One action, many names.**
  - Read: Read, Read document, Read again, Read selected, Read all documents.
  - Record: Record, Extract to ledger, Extract again, Ready to record, Recording to the ledger.
  - Verify: Count it, Count it anyway, Confirm, Confirm recurring, Confirm value, Approve.
  - Reject: Reject, Not right? Reject, Reject (not a real transaction).
  - Remove: Delete, Remove, Ended.
  - "Reconcile now" means two different things.
- **Loading and error states.**
  - Only Home, Review and Spending show them.
  - Bills, Accounts, Inventory, Forecast, Processing and the viewer fail to a toast and stay blank or stale.
  - Unconfigured pages render empty tables with live pagers.
- **Form errors** are toasts, not next to the field. Budget and asset currencies are free text.
- **Filters lost on reload.** Documents, Inventory, Spending month, Forecast assumptions and the Settings tab aren't
  in the URL.
- **Deep links into the wrong library.** Home, Review and Search deep links open the Documents library, which leaves
  out receipts and statements.
- **Too many primary buttons.**
  - Every Documents row has its own filled button, up to 100 per page.
  - Several "This one" primaries in Review questions.
  - Two primaries on Settings › Sharing.
- **Dead ends.**
  - A receipt doesn't link to its matched charge.
  - Accounts has no Import.
  - Bill rows lead nowhere.
  - CSV and XLSX files can't be opened.
- **Internal wording.**
  - "Preserved version", engine, parser and schema versions and token telemetry in the viewer's default tab.
  - Raw status keys and underscores in Processing and Review titles.
  - Raw ISO dates on Home and Forecast.
- **Assistant panel overlaps.** It covers the page and the toasts: same z-index, and the `assistant-open` class is
  unused.
- **Not built from the plan.**
  - A first-run welcome.
  - A shortcut help overlay (`?`).
  - A non-modal drawer.
  - Skeletons.

### Bugs found in review
1. The Backup list doesn't load when the tab is reached with arrow keys (`app.js:25-31`, `processing.js:118`).
2. The document viewer is stuck on "Loading…" if the preview fetch fails (`receipt.js:127`, `:37`).
3. "Ended" is offered on rows that are already ended or rejected, with no confirmation (`finance.js:539`).
4. Clicking an earlier Assistant question duplicates its answer (`assistant.js:86`).
5. The Review badge (limit 1000) and the queue (limit 200) can disagree (`review.js:22` vs `:36`).
6. Home and chart drill-downs pass `currency`/`metric`, which the Items view ignores (`finance.js:162-172`).
7. Tax-table source URLs are live links (`receipt.js:642`); they must be text.
8. Share, Backup, "Look up warranty" and "Look for recurring bills" aren't disabled while running, so double
   clicks start duplicate runs.

## The design: Household ledger

### Tokens
The **light** theme:

| Token | Value | Role |
|---|---|---|
| `--canvas` | `#ECEFEA` | index-card grey-green page ground |
| `--paper` | `#FAFBF7` | content surface (not cream) |
| `--paper-sunken` | `#F1F3EE` | table headers, evidence, callouts |
| `--rule` | `#D9DED6` | dividers |
| `--rule-strong` | `#BCC4B9` | inputs |
| `--ink` | `#1F2523` | graphite text and amounts |
| `--ink-2` | `#4A534F` | secondary text |
| `--ink-3` | `#667069` | muted text (≥4.5:1 on paper) |
| `--accent` | `#34409A` | indigo: links, primary, selection, focus |
| `--accent-subtle` | `#E7E9F6` | selection background |
| `--positive` | `#2E6B3F` | money in, verified only |
| `--warning` | `#8F5B00` | needs review, stale |
| `--danger` | `#9C3B2B` | errors, overdue, destructive; never spending |

Each semantic colour keeps a `-subtle` background.

The **dark** theme is set on `[data-theme=dark]` and follows `prefers-color-scheme`:

| Token | Value |
|---|---|
| canvas | `#121614` |
| paper | `#1A1F1D` |
| paper-sunken | `#222826` |
| rule | `#2F3733` |
| ink | `#E4E8E4` |
| ink-2 | `#B3BBB6` |
| ink-3 | `#8E9892` |
| accent | `#A9B1F2` |
| positive | `#86C79A` |
| warning | `#E2B866` |
| danger | `#F09A86` |

Every pair is contrast-checked: text ≥4.5:1 and interface elements ≥3:1.

### Type
Both fonts are OFL-licensed and bundled in `app/static/fonts/` as WOFF2 files with their licenses. The CSP's
`default-src 'self'` already allows local fonts.
- **Source Serif 4** for page titles and headline figures, with lining, tabular figures (`font-variant-numeric:
  lining-nums tabular-nums`). This is the one bold element: money reads like a printed ledger.
- **Public Sans** for everything else, with tabular numbers in tables.
- **Scale:** 12 / 13 / 14 (body) / 16 / 20 (sans) and 24 / 32 (serif titles, headline figure). Line heights come
  from tokens, with a line-length cap of 72ch for prose.
- **Nav group labels** in sentence case, not all caps.

### Layout principles
- **Hierarchy by space and rules, not boxes.** Sections are separated by a serif heading, 32px of space and a
  hairline rule. Borders stay only on tables, the drawer and viewer panes, and dialogs.
- **Radii:** 3px on controls, 6px on panels and popovers, 10px on dialogs. No pills except count badges.
- **One shadow**, overlays only.
- **One primary button per region.** Row actions go into ⋯ menus. One "selected" style everywhere: indigo left bar
  plus accent-subtle background.
- **Decision in view, source beside the record** (the `app-ux` rules).

### Checked against the skill's list of generic looks
- **Cream and serif.** The paper is a cool grey-green, not cream, and there's no terracotta.
- **No newspaper look.** The serif is limited to titles and figures, and radii and colour stay.
- **Dropped:** all-caps labels, and the monospace data labels outside the transcription view.
- **Fewer middle dots.** Middle-dot joins in the new key screens become laid-out fields, where each value has a
  label.

## Round one: what gets built
**1. Foundation** (`style.css` rewritten, `index.html`, a new `app/static/fonts/`)
- New tokens for light and dark, plus a theme override in Settings › Preferences, stored in the household settings.
- **Style sheet reorganised** into ordered sections: tokens, base, type, layout, components, pages, responsive
  last.
  - Remove the duplicated and dead rules.
  - Route every off-token value (meters, overlay, `#fff`, the Home chart colours) to tokens.
  - Unify "selected" and the quiet button.
- Fix sticky table headers: `.table-wrap` gets its own `max-height` scroll region, or `overflow: clip`.
- **Phone layout below 800px:** a top bar with the page title, a menu button that opens the navigation as a sheet,
  and search.
- **Forced colours**, and a visible focus ring on menu items.
- **Charts.** The Home donut and trend, and the server-drawn forecast charts, take text, axis and grid colours from
  theme variables, and keep their validated series palette in both themes. The `forecast-charts` skill governs
  this; re-validate the palette against the dark paper.

**2. Shared states** (`ui.js`)
- One `pageState(target, {loading | error+retry | empty+action})` helper.
- Skeleton rows at their final size.
- Used on every page, replacing toast-only failures.
- Unconfigured pages show a setup message instead of empty tables.

**3. Consistent wording.** A single action vocabulary, applied everywhere:

| Action | Label |
|---|---|
| Read | **Read** / **Read again** |
| Record | **Record** / **Record again** |
| Verify | **Count it** |
| Reject | **Reject** |
| Recurring / warranty / tax table / asset | **Confirm** |
| Document to Trash | **Delete** |
| Settings rows | **Remove** |

- Status and title text through `statusLabel()`, and dates through `dateText()`.
- The two "Reconcile now" labels become **Reconcile all** and **Reconcile this statement**.

**4. Review** (`review.js`, `style.css`)
- **Three columns at 1280px and wider:**
  - the queue;
  - the record (why, checks, evidence), with a sticky decision bar at the top holding Count it / Reject / Open;
  - the document preview, scrolling on its own with zoom and "Open in viewer".
- **At 800–1279px:** the queue collapses to a list button, with the record and document side by side.
- **Below 800px:** stacked, with the decision bar pinned to the bottom.
- **Questions** get one primary: choose a candidate, then **Link**.
- Undo on every decision.
- Failed and Unfiled documents become queue groups.
- Match score and method go in a Details disclosure.
- Badge and queue use the same limit.

**5. Home** (`home.js`)
- Needs attention moves first, as one strip that lists only what's non-zero, with each row deep-linking to its Review
  group. It ends with "Review N items" as the single primary, or "All caught up".
- Then the serif headline figure, trend and categories, and upcoming bills. Readable dates throughout.

**6. Document viewer** (`receipt.js`, `index.html`)
- **Record header.** The Read / Record step buttons move into the record-pane header, next to its state.
- **Link to the charge.** A **Matched charge** link opens the transaction drawer.
- **Plain Details tab.** Engine, parser and schema versions, hashes and token counts move to a "Technical details"
  disclosure.
- Fix the stuck-loading bug with an inline error and Retry.

**7. Bugs 1–8** above.

**8. Keep the rules current**
- Rewrite `.claude/skills/app-ux/SKILL.md` for the new tokens, type and layout rules.
- Update `docs/ui-design-plan.md` §4 to the Household ledger system.

**Round two**, planned separately: Transactions (sticky toolbar, non-modal drawer), Documents (row actions into ⋯,
filters in the URL, the right library for deep links), Spending, Bills, Accounts (Import), Forecast (results first),
Inventory, Processing, Settings, Assistant (a push panel instead of an overlay), shortcut help, first-run welcome.

## Verification
- **Screenshot review.**
  - Extend the browser tests' screenshot hooks (`HOME_SCREENSHOT`, `BROWSER_SCREENSHOT`,
    `INSPECTOR_SCREENSHOT`…) to cover Review, Home and the viewer at 390, 1024 and 1440 widths, in light and dark.
  - Save them to the scratchpad and critique each pass against this plan.
  - Use synthetic data only.
- **New browser assertions** (`tests/test_browser.py`, `tests/test_home_browser.py`, run with `--browser`):
  - Review's Count it button is inside the viewport at 1366×768 (`bounding_box`).
  - No horizontal overflow at 390px on the key screens.
  - `prefers-color-scheme: dark` switches the tokens (`page.emulate_media`).
  - Home's first region is Needs attention.
  - The viewer shows Matched charge for a linked receipt.
- **Contrast.** A small test computes WCAG contrast for every text/background token pair, in both themes.
- **Regression.** Update existing browser-test selectors and labels for the renamed actions. Run the targeted suites:
  browser, `test_receipt_counting.py`, `test_api.py`, `test_forecast.py`, `test_dashboard.py`.