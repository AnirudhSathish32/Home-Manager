# Redesign: Foundation, the behaviour (phase 1b)

## Context
Phase 1a is built: tokens, theme switch, fonts, chart tokens, base components and shell (`design-system/home-manager/phase1a-plan.md`).
Phase 1b is the rest of docs/open-work.md "UI redesign" item 5. It covers the shared behaviour that every Phase 2 screen builds on.

Decided in planning (2026-10-10, user):
- **Scope: the core now, the rest later.** 1b builds:
  - `pageState()`;
  - the `ui_v2_screens` flag;
  - the parity harness;
  - `figure()`, `breakdownPanel()`, `provenanceBadge()` and `ruleCard()`.

  `confirmCorrect()`, `sourceViewer()` and `historyList()` move to the To check / document page session. That session
  also plans a correction-preview endpoint, which doesn't exist yet, and pulls `receipt.js`'s `highlightEvidence()`
  out of its global `receipt` state.
- **The flag is a per-profile server setting** in `HouseholdConfig`. You turn it on in a "New screens" checklist in
  Settings › Appearance.
- **`pageState()` is retrofitted** onto the five pages that lack it:
  - Bills and Accounts have no catch and no loading state.
  - Investments can stick on "Loading…".
  - Forecast and Taxes fall back to a toast.

  Home keeps its own pattern until its v2 screen.
- **Loading:** nothing for 300 ms, then a muted "Loading …" line with a spinning `loader` icon and `aria-busy` on the
  region. There are no skeletons.
- **The breakdown panel:**
  - at ≥1180px, a 360px column beside the page, with the content narrowing;
  - at 900–1179px, the same 360px panel floating over the right edge (non-modal, `--shadow-overlay`);
  - under 900px, a bottom sheet up to 70vh.

  This deviates from MASTER, which puts the panel "below the content" at 900–1179px. The reason: one shared panel
  placed after a long page is unreachable.
- **No visible use yet.** `figure()` and the panel are built and browser-tested by mounting them into a test container
  in the real app, with traces from the synthetic dashboard. Taxes v2 is the first real user. Old pages don't get
  `figure()`.

User job: none new. The visible changes are honest loading and error states, with Retry, on five pages.

## Before screenshots
The implementer runs this before editing (synthetic data only):
`.venv/Scripts/python.exe .claude/skills/ui-redesign/scripts/ui_shots.py --routes bills,accounts,investments,forecast,taxes,settings --out <scratchpad>/before-1b`

Look at `bills-1440-light`, `investments-1440-light`, `taxes-1440-light`, `settings-1440-light` and their `-dark` and
`-390` copies. Don't run browser tests while `ui_shots` runs, because they time out when run together.

## Design-system references
- **MASTER "Components" — Breakdown panel:**
  - kicker "How it's worked out", title, answer (`--figure-xl`), formula;
  - a steps table (label, amount, running) with footer "✓ Sums to …";
  - inputs, unconfirmed first: `--radius-md` with a `--border` outline, or a `--warning` outline on `--warning-subtle`;
  - provenance as icon + text;
  - a rule card with the version in mono;
  - "Calculated … · inputs unchanged".
- **MASTER "Components" — Figure tile:**
  - label 12.5px secondary, `figure()` at `--figure-lg`, subline 12.5px muted;
  - when its breakdown is open, an `--accent` border plus a 1px ring.
- **MASTER "Layout":** the panel is 360px, `--surface`, with a left `--border`. **Deviation** at 900–1179px (above).
- **MASTER "Space, shape, density":** 180ms panel motion, none under `prefers-reduced-motion`. `--shadow-overlay` is
  only for the floating and sheet forms.
- **docs/ui.md:** "Observability components", "Number display", "Migration", "Trace contract".
- No `pages/<page>.md`, because no page layout changes.

## Tokens
**No new color tokens.** The panel uses:
- `--surface`, `--surface-sunken`, `--border`, `--border-strong`;
- `--text`, `--text-secondary`, `--text-muted`;
- `--accent`, `--accent-subtle`, `--positive`, `--warning`, `--warning-subtle`;
- `--shadow-overlay`, `--radius-md`, `--radius-lg`;
- `--figure-lg`, `--figure-xl`, `--font-mono`, `--space-*`, `--motion-panel`.

**One new size token:** `--panel-width: 360px` in `:root`. It is the same in light and dark.

Every pairing already exists in 1a and is contrast-checked in MASTER.md "Color tokens". There are no new pairs.

## Layout
Breakdown panel (`<aside id="breakdown">`, a sibling after `</main>` inside `.app-shell`):
```
≥1180  .app-shell.breakdown-open: columns sidebar | minmax(0,1fr) | var(--panel-width)
┌ nav ─┬ page ──────────────────────┬ #breakdown (sticky, 100vh, own scroll) ┐
│      │ [figure] ◀ aria-expanded    │ HOW IT'S WORKED OUT            [×]     │
│      │                             │ Net › Card purchases  (breadcrumbs)    │
│      │                             │ Net spending, September 2026  (h2)     │
│      │                             │ −$1,842.33                (--figure-xl)│
│      │                             │ Purchases counted this month, minus …  │
│      │                             │ ┌ Step ─────────── Amount ── Running ┐ │
│      │                             │ │ Card and bank…  +$2,010.00 $2,010.00│ │
│      │                             │ │ Refunds         −$167.67  $1,842.33 │ │
│      │                             │ │ Rounding        +$0.01             │ │
│      │                             │ └ ✓ Sums to $1,842.33 ──────────────┘ │
│      │                             │ Inputs (42)                            │
│      │                             │ ▢ Costco · Sep 3  −$84.12  ⚠Unconfirmed│
│      │                             │   ⎘ Read by model · page 1 · Open source│
│      │                             │ Rule card · Calculated Oct 10 · unchanged│
└──────┴─────────────────────────────┴────────────────────────────────────────┘
900–1179  position:fixed; right/top/bottom 0; width var(--panel-width); --shadow-overlay; z-index 30
          (assistant panel stays z 40). Under 1280 the sidebar is the icon rail as in 1a.
<900      position:fixed; left/right/bottom 0; max-height 70vh; top corners --radius-lg; --shadow-overlay;
          own scroll. Under 820 the 1a top bar stays above it.
```
pageState region (each retrofitted page; the region sits right after the page header):
```
┌ Bills & recurring (h1) ───────────────────────────────┐
│ subtitle                                              │
│ #bills-state:  ◌ Loading bills…      (after 300 ms)    │
│   or: [⛔ Couldn't load bills. <message>  Retry]  role=alert, technical details │
│   or: empty-state "Set up your library…  Open Settings"│
│ …page content (hidden while error/unconfigured)…      │
```
There's no decision region: rules 1–2 don't apply. Rule 6 (no horizontal scroll at 390) applies to the panel and
the state lines.

## Changes by file
All paths are under `src/home_manager/app/static/` unless stated.

### ui.js
- **`ICONS`**: add these, copying Lucide's exact paths (ISC, as noted at the top of the file) from lucide.dev source:
  - `refresh` (refresh-cw): stale or changed;
  - `user`: entered;
  - `scan-text`: read by a model;
  - `upload`: imported;
  - `calculator`: worked out;
  - `pencil`: changed by hand;
  - `book-open`: rule.

  Use the existing `trend` for a rate.
- **`STATUS`**: add the entries below (each is [label, tone, icon]). The existing `checked` ("Checked automatically")
  and `needs_review` stay.
  - `unconfirmed`: ["Unconfirmed", "warning", "alert"]
  - `stale`: ["Changed", "warning", "refresh"]
  - `prov_manual`: ["Entered", "neutral", "user"]
  - `prov_extracted`: ["Read by model", "info", "scan-text"]
  - `prov_imported`: ["Imported", "neutral", "upload"]
  - `prov_computed`: ["Worked out", "neutral", "calculator"]
  - `prov_override`: ["Changed by hand", "info", "pencil"]
  - `prov_rule`: ["Rule", "neutral", "book-open"]
  - `prov_rate`: ["Exchange rate", "neutral", "trend"]
- **`setStatusBadge(target, status, prefix = "", label = null)`**: the new 4th argument replaces the label text and
  keeps the tone and icon. `statusBadge()` passes it through. Existing callers are unchanged.
- **New `pageState(host, load, {loading = "Loading …", what = "this page", content = [], needsLibrary = false} = {})`**,
  placed after `alertBox()`:
  - `host` is the page's state element.
  - `load` is an async function.
  - `content` lists the page's own regions, which are hidden on error or when there's no library.
  - It returns `load()`'s value, or `undefined` when it errors or a newer call took over.

  Behaviour:
  1. **A newer call wins.** Bump `host.dataset.generation`. Every write below first checks the generation still
     matches.
  2. **No library.** If `needsLibrary && !configured`, the host shows
     `emptyState(\`Set up your library to see ${what}.\`, homeLink("Open Settings", "#/settings"))` and hides `content`.
  3. **Busy.** Set `aria-busy="true"` on `host.closest("[data-page]")`. Set a 300 ms timer that puts
     `p.page-loading[role=status]` in the host, holding `icon("loader", "icon spin")` and the `loading` text.
  4. **Success.** Clear the timer, empty the host, unhide `content` and remove `aria-busy`.
  5. **Error.** Clear the timer, remove `aria-busy`, hide `content`, and put this in the host:
     `alertBox(\`Couldn't load ${what}. ${error.message}\`, {tone: "error", detail: error.detail || "", action: retryButton})`.
     - `retryButton` is a `button.secondary` reading "Retry". It re-calls `pageState` with the same arguments and then
       moves focus to the host.
     - The rejection is not re-thrown, so the shell toast doesn't fire too.

  Empty data stays each page's own `emptyState()`, as today. `pageState` covers only loading, error and an unconfigured
  library.

### trace.js (new; loaded after `ui.js` and `app.js`, before `shell.js`)
The header comment cites `docs/ui.md "Observability components"`. Only vanilla factories, with no inline styles.

**`figure(fig, {size = "lg"} = {})`**
- When `fig` is falsy or has no `trace`, return `amount(fig)`.
- Otherwise return a `button.figure-button` (type=button) with these attributes:
  - `data-figure-ref = fig.trace` and `data-figure-display = fig.display`;
  - `data-size = size` (`lg` | `xl` | `inline`);
  - `aria-controls="breakdown"` and `aria-expanded="false"`;
  - an `aria-label` of `${fig.display}, show how it's worked out`.
- The button holds `amount(fig)` followed by flags. Each flag is a `span.figure-flag` made with `setStatusBadge`:
  - when `fig.verification === "needs_review"` or `fig.verification?.state` is in ("unverified", "partial"): `unconfirmed`;
  - when `fig.stale === true`: `stale`.
- A click calls `openBreakdown(fig.trace, button)`.

**`breakdownPanel()`**: module state `{stack: [], opener: null}`, plus:
- **`openBreakdown(ref, opener)`**
  - Reset the stack to `[ref]` and set `opener`.
  - Set `aria-expanded="true"` on the opener, and `"false"` on any previous opener.
  - Unhide `#breakdown` and add `.breakdown-open` to `.app-shell`.
  - Render, then move focus to `#breakdown-title`.
- **`drillBreakdown(ref)`** pushes a ref and renders.
- **`backBreakdown()`** pops a ref, or closes the panel at the root.
- **`closeBreakdown()`**
  - Hide the panel and remove the class.
  - Set `aria-expanded="false"` on the opener and return focus to it.
- **Esc** in the panel calls `backBreakdown()`, unless the event is inside an input or a `dialog` is open.
- **Rendering**
  - Fetch with `api("/api/traces/" + encodeURIComponent(ref))` through
    `pageState($("breakdown-state"), …, {what: "this breakdown", content: [$("breakdown-body")]})`.
  - The header contains:
    - `p.breakdown-kicker` "How it's worked out";
    - when the stack is deeper than one, a breadcrumb `nav[aria-label="Breakdown path"]`: each earlier label is a
      `button.link-button`, the last is plain text, and the separator is `chevron-right`;
    - `h2#breakdown-title` with `trace.label`;
    - a close `button.icon-button` with `icon("x")` and aria-label "Close";
    - `p.breakdown-answer` with `amount(trace.result)` at `--figure-xl`;
    - `p.breakdown-formula` (secondary).
  - **Steps** go in a `div.table-wrap > table.breakdown-steps` with the header Step | Amount | Running. Each row has:
    - the label (a `button.link-button` when `step.trace` is set, which calls `drillBreakdown(step.trace)`);
    - `step.count` as muted "· 42 lines" when present;
    - the amount: `span.sign` holding `step.op`, then `amount(step.value, {signed: false})`;
    - the running value, `amount(step.running)`.

    Then come two extra rows:
    - **Rounding:** when `trace.rounding?.adjustment`, a row "Rounding" with `amount(adjustment)` and the note in muted
      text.
    - **Footer** (`tfoot`): when `trace.reconciles`, `icon("check")` + "Sums to " + `amount(trace.result)` in
      `--positive`. Otherwise `alertBox("These steps don't add up to the figure. This is a bug; please report it.", {tone: "warning"})`.
  - **Inputs:**
    - **Heading:** `h3` "Inputs" with the count `trace.inputs_page.total`.
    - **Rows:** `ul.breakdown-inputs` with `li.input-row` and `data-verification`. Each row has:
      - the label, plus `amount(input.value)` right-aligned;
      - `provenanceBadge(input.provenance)`;
      - `statusBadge("unconfirmed")` when `needs_review`;
      - muted text "Checked automatically" when `checked_automatically`;
      - links: "How it's worked out" (`link-button`, `drillBreakdown(input.trace)`) when `input.trace`, and "Open
        source" (`homeLink`) to `#/documents/${doc.id}?lines=${doc.lines.join(",")}` when
        `input.provenance?.document`.
    - **Paging:** when `inputs_page.total > inputs_page.shown`, add a muted "Showing {shown} of {total}."
  - **Rule:** `ruleCard(trace.rule)` when present.
  - **Meta line:** `p.breakdown-meta` muted, reading "Calculated {dateText(computed_at)} · inputs unchanged". When
    `trace.stale`, it reads "· inputs changed since this was last shown" with `statusBadge("stale")`.

**`provenanceBadge(prov)`** returns `setStatusBadge(span, "prov_" + prov.kind, "", text)`. The text comes from
server fields only (no arithmetic):

| `prov.kind` | Text |
|---|---|
| `manual` | "Entered by {actor.person} · {dateText(actor.at)}", or "Entered" |
| `extracted` | "Read by model {model.id}", plus " · page {document.page}" when known. When `confidence?.level === "doubted"`, add " · doubted by {confidence.by}". |
| `imported` | "Imported · {import.file} row {import.row}" |
| `computed` | "Worked out" |
| `override` | "Changed by {actor.person}", plus " · {reason}" when given |
| `rule` | "Rule" |
| `rate` | "Exchange rate" |

Any other kind gets its `statusLabel`.

**`ruleCard(rule)`** returns `section.rule-card`, a `dl` with:
- Name;
- Source (text, never a link);
- Version (`code`, mono);
- Tax year;
- Checked on: `dateText(rule.checked_on)`, or "No check recorded";
- CPA review: `dateText(rule.cpa_reviewed_on)`, or "Not CPA-reviewed" (neutral text, no badge).

### index.html
- **Script.** Add `<script src="/static/trace.js" defer></script>` after `investments.js`/`donate.js` and before
  `shell.js`. Check the static route loop in `api.py` (~:620) serves it, and add it there if the files are listed.
- **Breakdown panel.** After `</main>` (line 923), inside `.app-shell`:
  `<aside id="breakdown" class="breakdown-panel" aria-labelledby="breakdown-title" hidden><div id="breakdown-state"></div><div id="breakdown-body"></div></aside>`.
  The header is rendered into `#breakdown-body` too, so `breakdown-title` exists once loaded. While loading, label the
  aside with `aria-label="How it's worked out"`.
- **State hosts.** Put one right after each page header:
  - `<div id="bills-state" class="page-state"></div>` in `#bills-panel`;
  - `#accounts-state` in `#accounts-panel`;
  - `#investments-state` in `#investments-panel`, replacing nothing: `#investments-status` stays for the archived
    toggle's text;
  - `#forecast-state` in `#forecast-panel`;
  - `#taxes-state` in `#taxes-panel`.
- **Settings › Appearance**, after the theme `<small>`:
  `<fieldset id="ui-v2-choice" class="theme-choice"><legend>New screens</legend><div id="ui-v2-list"></div></fieldset><small>Redesigned screens that are ready to try. Saved for this profile.</small>`

### The five pages (wrap each loader body in `pageState`, keeping its internal renders unchanged)
- **finance.js `loadBills`**
  - Make the body an inner `async` function.
  - Call `pageState($("bills-state"), inner, {loading: "Loading bills …", what: "bills", needsLibrary: true, content: [the panels inside #bills-panel after the header]})`.
  - Drop the bare `if (!configured) return;`.
  - Collect `content` with `[...$("bills-panel").querySelectorAll(":scope > section.panel")]`. The implementer checks
    the markup at index.html:476–489 and uses the panels that are there.
- **finance.js `loadAccounts`**: the same, with `#account-groups` as content and "accounts".
- **investments.js `loadInvestments`**
  - The unconfigured branch becomes `needsLibrary`.
  - Delete `$("investments-status").textContent = "Loading…"` and its clearing.
  - The `investmentsLoad` guard stays.
  - The content is `#investments-groups` plus the summary region.
  - The taxes, RMD and detail sub-panel catches stay as they are.
- **forecast.js `loadForecast`**
  - The body runs through `pageState($("forecast-state"), …, {what: "the forecast", needsLibrary: true, content: [$("forecast-charts")]})`.
  - The `forecast-form` submit handler calls `loadForecast()` with no `.catch(notice)`, because pageState shows the
    error.
- **taxes.js `loadTaxes`**
  - The whole body (family branch included) goes through
    `pageState($("taxes-state"), …, {what: "this year's taxes", needsLibrary: true, content: [...]})`.
  - The content is the `.taxes-layout` region (or `#taxes-return-panel` with `.taxes-personal` and
    `#taxes-family-panel`). Hide its parent layout only, so the year select in the header stays usable.
- **shell.js `ROUTES`**: `bills`, `accounts`, `forecast` and `taxes` drop their own `configured ? … : null`, because
  pageState shows the "Set up your library" state. The shell's `.catch(notice)` stays for every other page.

### shell.js: the flag
- Add near `ROUTES`: `const V2_SCREENS = {};  // route → {title, show}. Each Phase 2 screen registers itself here (docs/ui.md "Migration").`
- Add `let uiV2Screens = [];`, filled from `settings.household.ui_v2_screens` in `app.js loadSettings`.
- **`showRoute`**
  - Choose `const v2 = uiV2Screens.includes(route.name) && V2_SCREENS[route.name]`.
  - A section shows when `section.dataset.page === page && (section.dataset.ui || "v1") === (v2 ? "v2" : "v1")`.
    Today no section has `data-ui`, so nothing changes.
  - Call `(v2 || ROUTES[route.name]).show(route)`.
- **After `loadSettings`**: if the list changed and `currentRoute` is affected, call `showRoute(false)` again.
- **Appearance list**: `renderUiV2Choices()` fills `#ui-v2-list`.
  - It shows one checkbox per `V2_SCREENS` entry (`input#ui-v2-<route>`, label = title), checked from `uiV2Screens`.
  - Each change sends `api("/api/ui-screens", {method: "PUT", body: JSON.stringify({routes})})`, then
    `notice("Saved.")`, then updates `uiV2Screens` and re-routes.
  - With no entries it shows `emptyState("No redesigned screens are ready yet.")`.
  - It is disabled in a family profile when there's no household (same rule as the household form).

### app.js
- **`loadSettings`**: set `uiV2Screens = settings.household?.ui_v2_screens || []`, then call `renderUiV2Choices()`.
- **The household-form payload** (app.js:419): add `ui_v2_screens: uiV2Screens`, so saving Preferences doesn't reset
  it. Also add `tax_engine: settings.household.tax_engine` if the full model is required. Check how the payload is
  built today and follow it.

### Backend
- **`finance/ledger.py` `HouseholdConfig`**: add the field with a comment:
  `ui_v2_screens: list[Annotated[str, StringConstraints(pattern=r"^[a-z]+$", max_length=32)]] = Field(default_factory=list, max_length=32)`
  The comment reads: "Routes that show their redesigned screen (docs/ui.md "Migration")."
- **`app/api.py`**: add `PUT /api/ui-screens`, which takes a `UiScreensInput(StrictModel): routes: <same type>`. It
  calls `manager().configure_household(manager().household.model_copy(update={"routes"→"ui_v2_screens"}))` and
  returns the household dump. It goes next to `/api/household-settings` (:793).
- No migration (household config is a profile file).

### style.css
- **"Feedback"**: add these rules.
  - `.page-state:empty { display: none; }`
  - `.page-loading`: flex, gap `--space-2`, `--text-muted`, `--text-sm`, margin `--space-4` 0.
  - `.page-state .alert` and `.page-state .empty-state`: margin-bottom `--space-5`.
- **New section "Observability (trace.js)"**, after "Menus and dialogs", with these rules.
  - **`.figure-button`**
    - reset: no background or border, padding 0, inherit color, cursor pointer, `font-variant-numeric: tabular-nums`;
    - `[data-size=lg]` uses `--figure-lg`/600 and `[data-size=xl]` uses `--figure-xl`/600;
    - hover and focus-visible underline the `.amount` (1px, offset 4px, `--accent`);
    - focus ring as 1a (2px `--accent`, 2px offset);
    - `.figure-flag` sits beside it at `--text-xs`, margin-left `--space-2`, vertically centered.
  - **`.figure-tile`**
    - `--surface`, 1px `--border`, `--radius-lg`, padding `--space-4 --space-5`;
    - `.figure-label` 12.5px → use `--text-xs` secondary, and `.figure-sub` `--text-xs` muted;
    - `.figure-tile:has(.figure-button[aria-expanded="true"])` gets `border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent)`.
  - **`.breakdown-panel`**
    - `--surface`, a left 1px `--border`, padding `--space-5`, `overflow-y: auto`, width `var(--panel-width)`.
    - `≥1180`: `grid-column: 3`, `position: sticky; top: 0; height: 100vh`, and
      `.app-shell.breakdown-open { grid-template-columns: var(--sidebar-width) minmax(0,1fr) var(--panel-width); }`.
      Make sure the 1279 and 819 media-query `grid-template-columns` overrides also get the third column at 1180–1279.
    - `@media (max-width: 1179px)`: `position: fixed; top: 0; right: 0; bottom: 0; z-index: 30; box-shadow: var(--shadow-overlay)`.
      `.breakdown-open` doesn't add a column.
    - `@media (max-width: 899px)`: `left: 0; top: auto; width: auto; max-height: 70vh`, top-left and top-right
      `--radius-lg`, a top border instead of the left one.
    - It enters with `animation: sheet-in var(--motion-panel)` (reusing 1a's keyframes), and none under reduced motion
      (add it to the existing reduced-motion block at :795).
  - **Panel parts**
    - `.breakdown-kicker`: `--text-xs`, 600, uppercase, letter-spacing .04em, `--text-muted`.
    - `.breakdown-answer`: `--figure-xl`/600, tabular.
    - `.breakdown-formula`: `--text-sm` secondary.
    - `.breakdown-steps`: inherits the 1a table rules. Amount and running cells are right-aligned and tabular, and
      `tfoot` is `--text-sm` with 600 weight.
    - `.breakdown-inputs`:
      - the list has no bullets and a gap of 6px → use `--space-2`;
      - `.input-row` has `--radius-md`, a 1px `--border`, padding `--space-3`, and a grid of `minmax(0,1fr) auto`;
      - `.input-row[data-verification=needs_review]` gets `border-color: var(--warning); background: var(--warning-subtle)`.
    - `.rule-card`: `--surface-sunken`, `--radius-md`, padding `--space-3`, a `dl` grid of `max-content 1fr`, and
      `code` in `--font-mono`.
    - `.breakdown-meta`: `--text-xs` muted.
    - Breadcrumbs: inline flex, wrap, `--text-xs`.

## Selector contract
| Selector | Used by | Keep / rename to | Test edit |
|---|---|---|---|
| `#bill-groups`, `#recurring-rows`, `#subscription-summary` | test_recurring_bills.py:318–323 | keep | none |
| `#account-groups` | test_browser.py:301 | keep (now in pageState `content`) | none |
| `#forecast-charts` (svg, details, table) | test_forecast.py:265–284 | keep | none |
| `#investments-status` | investments.js | keep (no longer gets "Loading…") | none. The implementer Greps test_investments.py for `investments-status`/"Loading" first, and the earlier grep found none |
| `#investment*`, `#taxes-*`, `#forecast*`, `#asset*` (61 test locators) | test_investments.py, test_taxes_browser.py, test_forecast.py | keep all, none renamed | none |
| `.nav-link[data-route]`, `[data-page]` | every browser test, shell.js | keep. `data-ui` is additive | none |
| `#appearance-tab`, `#theme-*` | test_shell_browser.py | keep | none |
| CSP string | test_shell_browser.py:13 | unchanged (trace.js is `'self'`) | none |

Before editing, re-run the inventory Greps (`locator\("#[\w-]+`, `locator\("\.[\w-]+`, `get_by_role\(`) on
test_recurring_bills.py, test_browser.py, test_investments.py, test_forecast.py, test_taxes_browser.py and
test_shell_browser.py. Every hit must be kept.

## States
- **Loading:** fast loads (<300 ms) show nothing, and slow ones show the line. Seed a slow response in a test with
  `page.route` delaying `/api/finance/tools/*` (or whichever path `ledgerTool` hits) by 800 ms.
- **Error:** the alert has `role=alert`, the message, Technical details and Retry. Retry succeeds after the route is
  unblocked, and focus lands on the host. There's no duplicate toast.
- **No library:** each of the five pages shows "Set up your library to see …" with Open Settings, and no empty tables.
- **Empty data:** unchanged per page.
- **Breakdown:**
  - a long label wraps (`overflow-wrap: anywhere`);
  - 200+ inputs give "Showing 200 of N";
  - no rule means no card;
  - `reconciles:false` shows the warning;
  - stale shows the badge;
  - a trace fetch error shows the panel's own error with Retry;
  - opening the panel twice resets the stack.
- **Narrow:** at 390 the bottom sheet has no horizontal page scroll, and the steps table scrolls in `.table-wrap`.
- **Dark:** every part uses tokens. Check with `ui_shots` and the test mount.
- **Family profile:** Bills, Accounts and Taxes are FAMILY_ROUTES. pageState works the same, and family Taxes goes
  through the same wrapper.

## Accessibility
- **The page.** The page section gets `aria-busy` while loading. The loading line is `role=status`, and the error is
  `role=alert`. Retry moves focus to the state host, which gets `tabindex=-1`.
- **`figure()`** is a real button. It has `aria-expanded` and `aria-controls="breakdown"`, and Enter or Space opens the
  panel.
- **The panel** is non-modal (no focus trap). Opening moves focus to `#breakdown-title` (`tabindex=-1`).
  - Esc goes back one breadcrumb, then closes and returns focus to the opener.
  - The close button is labelled.
  - The breadcrumb is a `nav` with an aria-label, and the current crumb has `aria-current="page"`.
- **Color is never alone:**
  - unconfirmed and stale are icon + text;
  - the reconciled ✓ is icon + "Sums to";
  - money signs are text (`−`/`+`).
- **Reduced motion:** there's no panel animation, and the spinner obeys the 1a rule.
- **Keyboard:** Review's J/K/V/R is untouched. Esc handling checks `event.defaultPrevented` and skips inputs and open
  dialogs, like shell.js:100.

## Out of scope
- `confirmCorrect`, `sourceViewer`, `historyList`, and a correction-preview endpoint (planned with To check).
- Any v2 screen. Any `figure()` on old pages.
- Home's loading pattern. Pages other than the five.
- Nav relabels. Share bars in breakdown steps (the server sends no step shares yet).
- Full provenance fetching per input (`/api/provenance`). Reversing the dark `--chart-seq-8..10` ramp (still open for
  the user).

## Verification
New tests:
- **`tests/test_ui_parity.py`** (browser, gated on `RUN_BROWSER_TESTS`). Its server fixture copies
  test_home_browser.py:20–47, with the same synthetic seed.
  - **`check_figures(page, token)`**:
    - collect every `[data-figure-ref]`;
    - fetch `/api/traces/{quote(ref, safe="")}` for each with the token;
    - assert `reconciles` and that `result.display == data-figure-display`.
  - **`v1_amounts(page)`** returns the set of `.amount[title]` texts on an old screen, for later screens' "matches
    the old screen" check.
  - **`MIGRATED = []`** lists `(route, v1 route)` pairs. Each Phase 2 session adds its own, and a parametrized test
    flips the flag through `PUT /api/ui-screens`, opens the v2 route, runs `check_figures` and asserts every v2 display
    is in the v1 amounts. It is skipped while empty.
  - **Harness self-test:**
    - fetch `/api/dashboard?month=…`;
    - mount `figure()` for each dashboard figure that has a `trace` into a `div#parity-fixture` appended to `main`, via
      `page.evaluate`;
    - `check_figures` passes;
    - then mount one with a wrong `display` and assert `check_figures` raises `AssertionError` (A16: it fails on a
      seeded mismatch).
- **`tests/test_trace_components_browser.py`** (browser): using the same mount, it checks:
  - clicking a figure opens `#breakdown` with title, answer, steps and "Sums to";
  - a step with a trace drills in, the breadcrumb shows, and Esc goes back then closes, with focus back on the figure;
  - the panel at 1440 is beside the page (its box.x ≥ main's right edge), at 1000 it floats, and at 390 it's a bottom
    sheet;
  - `scrollWidth <= innerWidth` at 390/1000/1440;
  - `provenanceBadge` and `ruleCard` render from a fixture object via `page.evaluate`.
- **pageState tests**, added to the existing files:
  - test_recurring_bills.py (Bills): an 800 ms delay shows "Loading bills", and an aborted route shows the alert;
    Retry then succeeds.
  - test_browser.py (Accounts): no library shows "Set up your library".
  - test_taxes_browser.py: an error leaves the year select usable, and no toast appears.
- **Flag tests:**
  - `tests/test_settings_api.py` (or the existing settings test file; Grep `household-settings` in tests):
    - `PUT /api/ui-screens` saves and round-trips through `GET /api/settings`;
    - a bad route name gives 422;
    - saving the household form keeps the list.
  - test_shell_browser.py: Appearance shows "No redesigned screens are ready yet."

Run (not concurrently with ui_shots):
- `$env:RUN_BROWSER_TESTS = "1"; .venv/Scripts/python.exe -m pytest tests/test_ui_parity.py tests/test_trace_components_browser.py tests/test_recurring_bills.py tests/test_browser.py tests/test_taxes_browser.py tests/test_investments.py tests/test_forecast.py tests/test_shell_browser.py -q`
- `.venv/Scripts/python.exe -m pytest tests/test_traces.py tests/test_style_tokens.py <settings test file> -q`
- `.venv/Scripts/python.exe .claude/skills/ui-redesign/scripts/ui_shots.py --routes bills,accounts,investments,forecast,taxes,settings --out <scratchpad>/after-1b`.
  Compare it with before-1b at every width and theme. There must be no `HORIZONTAL OVERFLOW` and no page errors.
- Tab through Bills (Retry), Appearance (New screens) and the mounted breakdown, and check the focus ring and order.
- `ruff` and `mypy` on the touched Python, as the confidence work set up.

## Docs to update
- **docs/ui.md:**
  - "Observability components": mark `figure`, `breakdownPanel`, `provenanceBadge` and `ruleCard` built, with the
    panel placement (side ≥1180, floating 900–1179, sheet <900). Note that the other three come with To check.
  - "Migration": the flag is `HouseholdConfig.ui_v2_screens`, set via `PUT /api/ui-screens` and Settings › Appearance.
    Describe the `V2_SCREENS` registry and `data-ui="v2"` sections, and `tests/test_ui_parity.py` `MIGRATED`.
  - "Design system": add `pageState()` to the helper list and the `--panel-width` token.
- **design-system/home-manager/MASTER.md:**
  - "Deviations built in Phase 1a" → rename it "Deviations built in Phase 1" (Grep docs and code for citations of the
    old heading first);
  - add the panel's 900–1179 floating form.
- **design-system/home-manager/README.md:** Phase 1b done, and next is Phase 2 Taxes.
- **docs/open-work.md "UI redesign" 5:** remove the built items, and keep `confirmCorrect`/`sourceViewer`/`historyList`
  (+ the correction preview endpoint) under item 6 "To check and the document page".
- **The ui-redesign skill's `references/screen-inventory.md` "Shared helpers":** add `pageState()` and the trace.js
  factories.
