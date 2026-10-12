# Redesign: Home & things and System — Inventory, Processing, Settings (phase 2)

There are three builds in this plan. **Each build runs in its own implementation session**, in the order A → B → C,
and is verified on its own. Commit a build only when the user asks. At the start of Build A, copy this plan to
`design-system/home-manager/phase2-system-plan.md`; the later sessions read it there. Build A writes
`design-system/home-manager/pages/inventory.md`, and Build B writes `pages/system.md` (Processing and Settings). Both
take the same shape as `pages/wealth.md`: the jobs, then Components, Layout, States and Decided, copied from here.

## Context
docs/open-work.md "UI redesign" item 6 lists the next screens: Inventory (Item insights) → Processing (Data health) →
Settings (Independent checks editable, Donate). Item 7 asks for a screen for `GET /api/finance/health` (built in B) and
`PUT /api/reviewer-settings` (built in C). `POST /api/decision-model-tests` already has a button (`#test-decision`),
so that part of item 7 is only recorded as done. docs/ui.md "Redesigned navigation" sets the structure:
- **Inventory** gets the tabs Check-in · Items · Warranties · Returns · Item insights.
- **Processing** gets a Data health tab.
- **Settings** gets Donate ("route kept").

Decided with the user on 2026-10-11:
1. **Item insights adds item traces** (backend, at the start of A), so every insight figure opens `#breakdown`.
2. **Independent checks becomes editable**, and the tab says plainly where each check applies.
3. **Processing becomes an overview strip plus tabs** (Recent work · Data health · Watched folders · Scans · Model
   runs), with `?tab=` in the URL.

The user's jobs:
- **Inventory:** answer the weekly check-in, see what's in the house, keep warranties and return windows straight,
  answer "did this go back?", and see what items cost over time (insights).
- **Processing:** see what's running and whether each stage is healthy, start a scan or a batch read, manage watched
  folders, find failed work, and see whether the ledger breaks any rule (Data health).
- **Settings:** change one setting and confirm it was saved; know what each model and check does.

What's wrong today (from the before screenshots and an Explore pass over the code):
- **Inventory:**
  - One long page: check-in, search, one panel per category ("other (1)", lower case), receipts to identify, and a
    return-policies table with an always-visible inline form.
  - Warranties show only as small notes inside rows. Returned-item questions show only when present.
  - Filters are lost on reload (docs/open-work.md "Filters lost on reload").
  - The item-analysis tools (`household/analysis.py`) have no screen and no traces.
  - `.history-row` (trace.js's grid rule, style.css L1240) also matches inventory's `tr.history-row`.
- **Processing:**
  - The page is 4,400px tall at 1440: two 20-row tables (scans, model runs), forms in the middle.
  - `GET /api/finance/health` has no UI.
  - **Bug:** `JOB_KINDS` offers `tax_table_lookup`, which `storage.py` `JOB_HISTORY` (L44–59) lacks, so choosing it
    fails the request (`ValueError("Unknown job kind.")`).
  - **Bug:** the model-run facets load only inside `loadProcessing`, so new tasks never appear in the filter.
  - The model-runs table shows negative tok/s and "0.0 s" from the synthetic server (data, not layout; leave it).
  - docs/ui.md "Processing" names the lanes Transcription/Extraction; the code says Reading/Recording, and lists a
    "Reconcile now" action the page doesn't have.
- **Settings:**
  - The tab isn't in the URL, so reload always opens Library folder.
  - Independent checks is one sentence. `settings.reviewer` is sent but never read.
  - Donate is a separate sidebar item.
- **All three:** the global `#reconcile-prompt` above the h1 is out of scope.

## Before screenshots
Taken 2026-10-11, with the flag off, into the session scratchpad
`…\scratchpad\before-system\` (it may be gone). The useful files are `inventory-1440-light.png`,
`processing-1440-light.png` (full page, 4,388px), `settings-1440-light.png` and `donate-1440-light.png`, plus their 390
and dark versions. **The default seed has one inventory item, no failed work, no health problems and no reviewer.**
Each build extends the seed (Shared › Seeding) and then re-takes its own before shots:
`.venv/Scripts/python.exe .claude/skills/ui-redesign/scripts/ui_shots.py --routes <route> --full-page --out <scratch>/before-<route>`.

## Design-system references
MASTER.md applies unchanged. Pro Max (`--design-system --density 8`) returned only generic "data-dense dashboard"
advice: filtering, row hover, and a loading-then-result on every submit. Those are already MASTER rules.
- **"Components":**
  - Tinted region (`.today-region`, never nested; lists inside use 1px dividers).
  - Needs-attention row (`.needs-row`, `.attention` = `--warning-subtle`, one text-link action).
  - Figure tile (`.figure-tile`).
  - Table (sticky `--surface-sunken` header, 40px rows, amounts right-aligned with a fixed sign slot).
  - Chips (30px pills, pressed = `--accent-subtle` with an `--accent` border).
  - Status badge, and buttons (one primary per region).
- **"Layout":** the page header (h1, muted subline, actions on the right, one primary) and the shared `#breakdown`
  panel.
- **"Meaning is fixed":**
  - Thrown-out (waste) money is `--text` with `−`, **never red**.
  - Health `error` problems use the `danger` tone through `statusBadge` (red means error, which they are), `warning`
    problems use amber, and `info` is neutral.
  - Price rises are text plus ↑, not red.
- **Deviation (C, Settings):** Settings is restyled **in place, not as a `data-ui="v2"` twin**. Its forms are bound by
  fixed ids from `profiles.js`, `app.js` and `processing.js` (`[data-test]`, `saveSettingsForm`), and about 60 ids are
  used by six browser test files. A twin would duplicate all of that wiring, and the flag's own checkboxes live in
  Settings › Appearance. The in-place changes keep every id and role name.

## Tokens
No new tokens. The ones used:
- Surfaces and borders: `--canvas`, `--surface`, `--surface-sunken`, `--border`, `--border-strong`.
- Text: `--text`, `--text-secondary`, `--text-muted`.
- Accent: `--accent`, `--accent-subtle`, `--on-accent`.
- Status: `--positive` (verified), `--warning`/`--warning-subtle`, and `--danger`/`--danger-subtle` (health errors,
  Remove and Stop watching confirmations, failed jobs through STATUS).
- Scales: `--space-*`, `--radius-*`, `--text-*`, `--figure-lg`.

Every pair is already in MASTER "Checked contrast". No hex values outside `:root`.
**Icons:** check `ui.js` `ICONS` first. Add only the ones missing from this list: `package` (exists for nav),
`shield-check` (Lucide `["M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z","m9 12 2 2 4-4"]`)
for warranties, `undo-2` (`["M9 14 4 9l5-5","M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5a5.5 5.5 0 0 1-5.5 5.5H11"]`) for returns,
and `heart-pulse` (`["M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z","M3.22 12H9.5l.5-1 2 4.5 2-7 1.5 3.5h5.27"]`)
for Data health.

---

## Shared (applies to every build)

### Registration pattern (A and B; copy `investments_v2.js`)
- **Files:** `inventory_v2.js` (A) and `processing_v2.js` (B), loaded with `defer` in `index.html` after
  `whatif_v2.js` and before `shell.js`. **Add each new static file to `api.py`'s static allowlist**, or it returns
  404.
- **Registration:** `V2_SCREENS.inventory = {title: "Inventory", show: route => loadInventoryV2(route.params)}`, and
  the same for `processing` with the title "Processing".
- **Section markup:** `<section id="<p>-panel" class="page" data-page="<route>" data-ui="v2" aria-labelledby="<p>-title" hidden>`
  goes right after its v1 twin. Inside: `header.page-header` (h1 `tabindex="-1"`, `p.page-subtitle`,
  `div.page-actions`), then `div#<p>-state.page-state`, then `div#<p>-body.page-body`.
  - The prefixes are `it2` (Inventory) and `pr2` (Processing). **Never reuse a v1 id.** v1 stays until item 8.
- **Tabs:** the Taxes v2 markup with `wireTabs` (`app.js`): a `div.tabs[role=tablist]` of `button[role=tab]` with
  `aria-controls` and roving tabindex. Panels are `[role=tabpanel]` and draw on first show (`tabshow`). `?tab=` goes in
  the URL through `history.replaceState`, writing only non-default params and setting `currentRoute.params`, as
  `investments_v2.js:15` does.
- **`show`:** parse and validate the params, set the controls, then
  `return pageState($("<p>-state"), render…V2, {loading, what, needsLibrary: true, content: [$("<p>-body")]})`.
- **Display rules:**
  - Amounts go only through `amount()`/`figure()`, dates through `dateText()`/`dateDisplay()`, and status through
    `statusBadge()`.
  - **No arithmetic.** Counting rows is allowed; sums aren't. Percentages are server text.
  - Long text (product names, folder paths, merchants) wraps with `overflow-wrap:anywhere`. Amounts never wrap.
- **Family:** `processing` and `settings` are in `FAMILY_ROUTES`; `inventory` isn't (it redirects).
  `processing_v2.js` shows "Choose a library folder first." in Watched folders in family mode, as `loadSources` does.

### Reused helpers (don't re-create)
- `ui.js`: `amount`, `dateText`, `dateDisplay`, `statusBadge`, `emptyState`, `alertBox`, `pageState`,
  `confirmAction`, `icon`, `menu`, `technicalDetail`, `toast`.
- `trace.js`: `figure(fig, {size})` and `openBreakdown`.
- `app.js`: `element`, `cell`, `wireTabs`, `notice`, `api`, `saveSettingsForm`.
- `finance.js`: `asyncButton`.
- `money_v2.js`: `errorField()`, for validation errors under the field they belong to.
- `inventory.js`: `productName`, `returnText`, `askedAt`, `renderCheckin`, `answerLot`, `openWarrantyDialog`,
  `lookUpWarranty` (after A's refactor below).
- CSS: `.figure-tile`, `.figure-label`, `.figure-sub`, `.today-region`, `.needs-row(.attention)`,
  `.chip[aria-pressed]`, `.tabs`.

### Seeding (`.claude/skills/ui-redesign/scripts/ui_shots.py`)
Synthetic data only. After seeding, each build re-runs the `home,spending` shots and confirms there are no page errors.
- **A:** `seed_items(manager)`, using the recipes in `tests/test_item_analysis.py:20–49` (the `pantry` fixture's
  `buy(day, merchant, lines)`, `milk()`, `cereal(size)`) and `tests/test_items.py:39,257` (`receipt()`, `stock()`):
  - Oat milk 64oz bought three times over 90 days at rising prices, two lots marked finished (gives cost per day, a
    price rise, and the forecast).
  - Cereal 18oz, then 15.5oz at the same price (a package-size change).
  - One lot thrown out last week (waste).
  - A Walmart receipt from 10 days ago with a durable, unopened item (a return window open).
  - A user warranty (`Warranties(store).add(lot_id, "manufacturer", 24, …)`) on the existing Acme Toaster, plus one
    warranty expiring in 30 days.
  - One returned-item proposal, following `tests/test_returns.py:143,290–310` (a purchase, a negative return line,
    `Reconciler(store).run()`).
  - Two consumables due in this week's check-in (set `next_check_on` to today).
- **B:**
  - One failed job: a failed text reading of an invalid image, as at `tests/test_receipts.py:82–93`.
  - One failed model run: `local_model["status"]=500`, as at `tests/test_sampling.py:92`.
  - One watched folder (`POST /api/sources` on a scratch folder).
  - One health problem at **warning** level, made with a safe `damage()` from `tests/test_health.py`. Use
    `orphan_reference` (L142–150), not the currency breakage, which disturbs other screens.
- **C:** a reviewer config (`provider:"chat"`, the synthetic server's URL and `synthetic-reasoning`) and one checked
  donation, so Ready to donate isn't empty.

### Tests (pattern)
- A and B each add `tests/test_<route>_v2_browser.py`, using `served()` from `tests/test_taxes_v2_browser.py`. Turn the
  flag on with `page.request.put(f"{base}/api/ui-screens", data={"routes": [...]}, headers=…)`.
- Every test collects `pageerror`s (none allowed) and checks `NO_OVERFLOW` at 390, 768 and 1440.
- A build that touches a v1 file re-runs that page's v1 browser test: `tests/test_browser.py` for inventory.js,
  processing.js and app.js.

---

## Build A — Inventory (`#/inventory`, `inventory_v2.js`)

### A1. Backend: item insights with traces
- **`household/analysis.py`:** give `get_item_spending`, `get_waste`, `get_consumption_cost` and
  `forecast_consumables_spend` an optional `recorder=NullRecorder()` (core/trace.py). Record **one step per product**,
  not per lot (`recorder.add(product_label, minor, currency, count=purchases)`). Cost per day and the forecast record
  each product's `(cost, days, lots)` as `recorder.input(...)`, with provenance "your check-in answers", plus
  `recorder.round(...)` for the half-even rounding. The tool outputs are unchanged when no recorder is passed.
- **New `household/item_traces.py`** with `TRACES` entries, following `finance/traces.py` `spending_net`:
  - `items.spending` (start, end, currency): "What approved receipt items cost in the period: each product's lines
    added up, as printed, before separate discounts."
  - `items.waste` (start, end, currency): "Items you marked thrown out in the period, at what they cost."
  - `items.per_30_days` (currency): "Each finished product's cost divided by the days it lasted, times 30, added up."
  - `items.forecast` (month, currency): "Each product's rate times the month's days; products with under two finished
    lots are left out."
  - Register them with `TRACES.update(ITEM_TRACES)` in `finance/traces.py` (next to `WEALTH_TRACES`).
- **New endpoint `GET /api/inventory/insights?start&end&currency`** (default: the last 90 days, the home currency). It
  returns:
  ```
  {period:{start,end}, currency,
   figures:{spending:{display,minor,currency,trace,stale}, waste, per_30_days, forecast},   // via traces.shown()
   counts:{purchases, thrown_out, finished_products},
   top_products:[{product, spent:money, purchases}],
   increases:[{product, per, first:{…}, last:{…}, change_percent:"14.3%", package_size_changed}],
   waste_items:[…], consumption:[{product, per_30_days:money, approximate}], notes:[…]}
  ```
  - `change_percent` is formatted on the server from `percent_change`.
  - The forecast month is next month.
- **Tests:** `tests/test_item_traces.py`. Each trace's total equals the matching tool figure, its steps sum to the
  answer, and the endpoint shape is checked, all on the `pantry` fixture.

### A2. `inventory.js` refactor (v1 behaviour unchanged)
- Pull the row menu out of `inventoryRow` into `lotMenu(lot)`, which returns the `menu()` element. History stays
  v1-only.
- `renderReading(run, host = $("checkin-reading"))`. Move the free-text submit logic into
  `submitCheckinText(text, host, button)`, which the v1 form handler calls.
- `afterInventoryChange()` calls `window.inventoryReload?.()` first when it's set (v2 sets it), and keeps its v1/Home
  reload otherwise.
- Rename the inventory `tr.history-row` class to `tr.lot-history-row` (and its CSS `.history-row td` rule), to end the
  clash with trace.js. No test uses it.

### Data (v2)
These are the same endpoints v1 uses:
- `GET /api/inventory?limit=1000[&query][&include_closed]`
- `/api/inventory/checkin`, `/api/inventory/receipts-to-identify`, `/api/inventory/returned`
- `/api/return-policies`

Plus:
- `GET /api/warranties` and `/api/warranties/expiring?days=60`
- `GET /api/inventory/returns?days=14`
- `GET /api/inventory/insights` (A1)

Each tab fetches its own data on first show. The header needs the check-in count only, from `/api/inventory/checkin`.

### URL (rule 5)
`#/inventory?tab=checkin|items|warranties|returns|insights&q=…&closed=1&period=30|90|365|year`.
- The default tab is **items**.
- `q` (already linked from Today, Search and the assistant) forces `tab=items`.
- `period` belongs to insights only; its default is 90.

### Layout at 1440×900
```
Inventory                                                    [+ Return policy]
Household items from receipt lines you approved.
[Check-in 2] [Items] [Warranties] [Returns 1] [Item insights]
─── Items ───────────────────────────────────────────────────────────────────
[Search product, brand or category      ] [ ] Show finished and thrown out
┌ To identify (tinted region, only when receipts wait) ────────────────────┐
│ Hardware Depot · Oct 9 · 2 of 2 lines not identified  Identify items · Open│
│ Fresh Market   · Oct 9 · 1 of 3 lines not identified  Identify items · Open│
└──────────────────────────────────────────────────────────────────────────┘
┌ table-wrap ─────────────────────────────────────────────────────────────┐
│ Item              Bought     Status        Returnable / warranty   Next │
│ Dairy (2)                                                (group row)    │
│ Oat milk 64oz     Oct 2      ● In stock    Not returnable          Sat …│ ⋯
│ Other (1)                                                                │
│ Acme · Toaster    Oct 9      ● In stock    ⛨ Warranty to Oct 9 2027 · … │ ⋯
└─────────────────────────────────────────────────────────────────────────┘
```
- **Group rows:** `tr.it2-group > th[colspan][scope=colgroup]`, with the category through `categoryLabel()` (proper
  case) and a count. One table, not one panel per category.
- **Check-in tab:** `renderCheckin(host, checkin)` (full mode) in a tinted region, then the free-text form
  (`#it2-checkin-text`, `#it2-checkin-submit`) and the reading host `#it2-checkin-reading[aria-live=polite]`. The
  decision buttons sit on each row (rule 1); the list is at most 15 rows.
- **Warranties tab:** first a "Waiting in To check" needs-row (`.attention`, link to `#/review`) for proposed ones.
  Then one table: Item, Kind, Ends (`dateText`, or "Lifetime"), Source ("You added" / "Found online" + `source_title`
  as text, never a link), and status. "Ends in 30 days" is `statusBadge` warning. The row menu has Remove (confirm,
  focus Cancel). The header action changes to "+ Warranty" on this tab and opens a picker of in-stock items, then
  `openWarrantyDialog`.
- **Returns tab, three regions:**
  1. **"Did this go back?"** One needs-row per returned proposal, using the v1 `renderReturned` buttons. **This is a
     decision region, so it comes first.**
  2. **"Return windows closing"** (14 days): item, store, `returnText(lot)`.
  3. **"Return policies"**: the table without the inline form. "+ Return policy" (the header action on this tab)
     opens `dialog#it2-policy-dialog` with the same fields and PUT. Change pre-fills it, and Remove confirms.
- **Item insights tab:**
  - Period chips (30 days · 90 days · 12 months · This year).
  - Four figure tiles in a row: Spent on items, Cost per 30 days, Thrown out, Next month's consumables. The subline
    of each is `counts.*`, plus "~ approximate" where any row is approximate.
  - Then two side-by-side tables at ≥1180px: "Prices that went up" (product, first → last unit price, `change_percent`
    with ↑ and "smaller pack" when `package_size_changed`) and "Costs most" (top_products).
  - Below them, a "Thrown out" list.
  - The notes go in a muted footnote list.

### Layout at 390
Tabs scroll horizontally inside `.tabs` (no page scroll). The table drops "Next question" into the Item cell's second
line, and the menu stays. Figure tiles stack in two columns. The policy dialog fills the full width.

### Changes by file
- `style.css`: a new section "Inventory v2" (`.it2-*`) with the group row, the insights grid
  (`grid-template-columns: repeat(4, minmax(0,1fr))`, 2 columns under 820px) and the two-table row. Rename
  `.history-row td` → `.lot-history-row td`.
- `inventory_v2.js`: `loadInventoryV2(params)`, `renderItemsTab`, `renderCheckinTab`, `renderWarrantiesTab`,
  `renderReturnsTab`, `renderInsightsTab`, `openPolicyDialog(policy)`, and `writeUrl()`. Set
  `window.inventoryReload = () => loadInventoryV2(it2.params)` while the screen is shown.
- `inventory.js`: the A2 refactor only.
- `index.html`: the `#it2-panel` section and `dialog#it2-policy-dialog`; the script tag.
- `shell.js`: nothing (the `V2_SCREENS` registration is in the screen file). The v1 `ROUTES.inventory` `q` handling
  stays for v1.
- `api.py`: the insights endpoint and the static allowlist entry.
- `tests/test_ui_parity.py`: add `("inventory", "inventory")` to `MIGRATED`, with `items.*` figures in `NEW_ON_V2`.
  v1 shows no figures, so if the harness needs v1 figures, leave the pair out and say why in docs (as What If does).

### Selector contract (Build A)
| Selector | Used by | Keep / rename to | Test edit |
|---|---|---|---|
| `#nav-inventory`, `#nav-checkin-count` | test_browser.py:339, shell | keep | none |
| `#inventory-groups` ("No items yet") | test_browser.py:340 | keep (v1) | none; v2 test asserts `#it2-body` "No items yet" |
| `#policy-rows` ("Walmart") | test_browser.py:341 | keep (v1) | none |
| `#inventory-search` set from `?q=` | shell.js:12 | keep (v1) | none; v2 reads `q` itself |
| `#warranty-dialog` and its fields | inventory.js | keep, shared by v2 | none |
| `tr.history-row` (inventory) | inventory.js, style.css | rename → `tr.lot-history-row` | none (no test uses it) |
| `renderCheckin`, `productName` | home.js, today_v2.js | keep signatures | none |

### States
- **Empty:** "No items yet. Items appear when you approve receipt lines." with a link to `#/review`.
- **Tabs:** each has its own `emptyState`.
- **Insights with no finished lots:** tiles show the server's zero figure, plus the note "Mark items finished in the
  check-in to see cost per day."
- **Loading and error:** `pageState` per page; each tab shows a small inline loading line, then `alertBox` with Retry
  on error.
- **Long product names** wrap. A check-in run that is queued or running shows "Reading your answer…" and disables
  submit.
- **Dark theme:** tokens only.

### Accessibility
- The h1 gets focus on show. Tabs use arrow keys (`wireTabs`). The count in each tab name is in its accessible name
  ("Check-in, 2 waiting").
- Every row menu button has `aria-label="Actions for <product>"`. Dialogs focus their first field, and Escape closes
  them.
- The insight tiles are `figure()` buttons. Price rises carry ↑ and the words "went up", not color alone.

### Verification (Build A)
- `$env:RUN_BROWSER_TESTS = "1"; .venv/Scripts/python.exe -m pytest tests/test_item_traces.py tests/test_inventory_v2_browser.py tests/test_browser.py -q -k "inventory or item or browser"`.
  Also run `tests/test_item_analysis.py` and `tests/test_ui_parity.py`.
- The new browser test covers:
  - each tab via the URL;
  - `?q=` landing on Items;
  - a check-in answer with Undo;
  - adding and removing a return policy in the dialog;
  - a returned-item answer;
  - an insights tile opening `#breakdown` with steps;
  - reload keeping tab, q and period;
  - `NO_OVERFLOW` at 390/768/1440.
- Shots: `ui_shots.py --routes "inventory,inventory?tab=checkin,inventory?tab=warranties,inventory?tab=returns,inventory?tab=insights" --v2 inventory`.

---

## Build B — Processing (`#/processing`, `processing_v2.js`)

### B1. Backend
- **Health links:** add `record_links(db, problems)` to `finance/health.py`, which the endpoint calls. It adds `link` to
  each problem:
  - receipt, statement or bill → `{document_id}` (each table's `document_id`);
  - transaction → `{document_id}` from `source_document_id`, else the statement's `document_id`;
  - holding or investment_event → `{investment_account_id}` (`account_id`);
  - table-name record types → `null`.
  - Test it in `tests/test_health.py` (one problem of each kind, using the existing `damage()` fixtures).
- **Job kinds bug:** look at whether tax table lookups are recorded in a table. If they are, add `tax_table_lookup` to
  `storage.py` `JOB_HISTORY`. If not, remove it from `processing.js` `JOB_KINDS`. Either way, add an API test that
  every `JOB_KINDS` value works with `GET /api/jobs?kind=` (read `JOB_KINDS` with a regex from the JS file, or mirror
  the list in the test).

### URL
`#/processing?tab=work|health|folders|scans|models&kind=…&task=…&status=…`. The default tab is **work**.

### Layout at 1440×900
```
Processing                                [Read all documents] [Scan Inbox]
Capture and reading run on separate queues; you can keep working meanwhile.
┌ tinted region: Now running ──────────────────────────────────────────────┐
│ ⟳ Reading hardware-depot.png · Transcribing · 12 s            [Cancel]   │  (or "Nothing running.")
│ Capture     │ Reading     │ Recording   │ Item identif. │ Reconciliation │
│ Idle        │ Idle        │ Idle        │ Not run yet   │ Idle           │
│ 3:31 PM ✓   │ 3:31 PM ✓   │ 3:31 PM ✓   │ —             │ 3:31 PM ✓      │
│             │             │             │               │ 0 links · 0 open│
└──────────────────────────────────────────────────────────────────────────┘
[Recent work] [Data health ⚠ 1] [Watched folders] [Scans] [Model runs]
 Show [All kinds of work v]
 Work            Started         Took   Result          Details
 Reading         Oct 11 3:31 PM  <1 s   ✕ Failed        Open document · Details
```
- **Lanes:** five equal columns in one tinted region, separated by 1px `--border` dividers (no nested boxes). The
  label is 12.5px secondary, the state `statusBadge`, and the last run muted. The batch status
  (`showReceiptBatch` text) appears under the Reading lane while a batch runs. "Read all documents" opens a small
  menu with "Also re-read documents that already have text" before it starts. Scan Inbox is the primary action.
- **Recent work:** the v1 columns. Failed rows are sorted first only when the filter is "Failed only" (a chip next to
  the kind select: All · Failed). The error goes in `technicalDetail`.
- **Data health:**
  - A summary line: "1 warning · 0 errors · 0 notes", through statusBadges; "✓ No problems found" (positive) when
    there are none.
  - Then one needs-row per rule (problems grouped by `code`). The row has: an icon in its tone, *what* = the first
    problem's `detail`, *why* = "N records" + severity, and the action "Open" when exactly one record has a link.
    Otherwise it is a disclosure listing up to 20 record links (`#/documents/{id}` or `#/investments?account={id}`)
    and "record #id" text for unlinked ones.
  - Then "Tax engines": each `tax_engines[]` as label + ready badge + note.
  - The `code` goes in `technicalDetail`.
  - Copy for the tab intro: "Rules your records should always follow. A problem here means a figure somewhere may be
    wrong; open the record to fix it."
- **Watched folders:** the v1 table (Folder, Subfolders, Last scan, actions Scan now · Pause/Resume · Stop watching,
  which confirms). "+ Watch a folder" opens `dialog#pr2-source-dialog` with path, name and subfolders. The Inbox path
  appears above it in mono as "Inbox: <path>".
- **Scans:** the scan select, state line and events table with the pager, as in v1, in new `pr2-` ids.
- **Model runs:** task and status selects; facets are refetched on every show of this tab (fixes the bug). The table
  is the v1 9 columns; `~` stays.
- **Polling:** `app.js` `poll()` calls `loadProcessing()` on the processing route. Add `window.processingReload` (set
  by v2, like `inventoryReload`), and have `poll()` call it when set, otherwise `loadProcessing()`. v2 refreshes only
  the strip and the visible tab.

### Layout at 768 and 390
At 768 the lanes become a 3+2 grid; at 390 one column of compact rows (title · state · last). Tabs scroll inside
`.tabs`. Tables scroll inside `.table-wrap`.

### Changes by file
- `style.css`: a new section "Processing v2" (`.pr2-*`) with the lanes grid and dividers, and the health rows (reuse
  `.needs-row`; add `.needs-row.error`, with `--danger-subtle` fill and a `--danger` icon, only if it isn't there
  yet).
- `processing_v2.js`: `loadProcessingV2(params)`, `renderStrip(activity, history, recon)`, `renderWorkTab`,
  `renderHealthTab`, `renderFoldersTab`, `renderScansTab`, `renderModelsTab`, `openSourceDialog()`, `writeUrl()`.
  Reuse `JOB_KINDS`, `LANES`, `duration`, `whenText` from processing.js and `telemetryText`, `cancelButton` from
  app.js.
- `app.js`: the `processingReload` hook in `poll()`, and `renderActivity` also fills `#pr2-activity` when it exists.
- `processing.js`: the `JOB_KINDS` fix only, if that's the chosen side.
- `index.html`: `#pr2-panel`, `dialog#pr2-source-dialog`, and the script tag.
- `api.py`: the static allowlist; `ledger_health` calls `record_links`.
- `tests/test_ui_parity.py`: no `MIGRATED` pair (Processing shows no traced figures). Say so in docs/ui.md
  "Migration".

### Selector contract (Build B)
Every v1 id stays: `#scan-inbox`, `#scan-state`, `#parse-all-receipts`, `#receipt-batch-status`, `#force-receipts`,
`#model-history`, `#activity-indicator`, `#activity`, `#pipeline-lanes`, `#job-rows`, `#source-rows`, `#source-path`,
`#source-label`, `#add-source`, `#scan-panel`, and `#nav-processing` (`test_browser.py` 30–355, 412–455). v1 tests
run with the flag off, so no test edits are needed. v2 uses only `pr2-` ids.

### States
- **Nothing running:** "Nothing running."
- **No work yet:** "No work recorded yet."
- **Health:** "✓ No problems found".
- **Family mode:** Watched folders shows "Choose a library folder first."
- **Errors:** a health fetch error shows `alertBox` inside that tab only, and the tab name keeps no count.
- **Long folder paths** wrap in mono.
- **Many problems:** grouped by rule, at most 20 links per rule, then "and N more (run `home-manager check-ledger`
  for all)".

### Accessibility
- The strip is `aria-live="polite"` only for the Now running line (not the lanes, to avoid chatter).
- The Cancel button names the work ("Cancel reading hardware-depot.png").
- Health tones carry icon + text. The tab count is in the accessible name ("Data health, 1 problem").

### Verification (Build B)
- `$env:RUN_BROWSER_TESTS = "1"; .venv/Scripts/python.exe -m pytest tests/test_processing_v2_browser.py tests/test_health.py tests/test_browser.py -q`.
  Also run the jobs-kind API test.
- The new browser test covers:
  - Scan Inbox from the header updating the strip;
  - the Data health tab listing the seeded warning with a working link;
  - adding and stopping a watched folder via the dialog;
  - the model-runs filter;
  - reload keeping `tab`;
  - `NO_OVERFLOW`.
- Shots: `--routes "processing,processing?tab=health,processing?tab=folders,processing?tab=models" --v2 processing`.

---

## Build C — Settings, in place (`#/settings`), with Donate

### URL
- `#/settings?tab=library|profiles|preferences|appearance|models|checks|backup|sharing|privacy|donate`.
- `ROUTES.settings.show` reads `tab` and clicks that tab (keeping `activate` from `wireTabs` in `shell.js:40`). A
  `tabshow` listener on every tab writes `?tab=` (only when it isn't the default) with `history.replaceState`.
- `profiles.js:49`'s `#nav-profile` jump becomes a link to `#/settings?tab=profiles`.

### Changes
- **Layout and style (`style.css` "Settings"):**
  - Keep the 220px left tablist and the content column.
  - Content max width 760px. Each tab panel: an h2, a muted lead, then groups separated by 32px with h3 headings (no
    nested cards; `.settings-content` stays one `--surface` region).
  - Each form's Save is the one primary button in its group, with a result line under it (`aria-live`): "Saved." or
    the field error through `errorField()`. Toasts stay for v1 tests that expect them, so both appear.
  - Under 800px the tablist becomes a horizontally scrolling row (no wrapping into many lines).
- **Local models:** visual grouping only: "This computer or a shared GPU", "Reading documents (vision)", "Reasoning",
  "Decision model". Every id stays.
- **Independent checks (`#checks-panel`), rewritten:**
  - **"Every ledger extraction":** a read-only line built from `settings.decision` (`#decision-status` keeps its text,
    which test_browser.py:118 expects), plus a link "Change the decision model" → `?tab=models`.
  - **"Document reasoning reviewer":** `form#reviewer-form` with:
    - `select#reviewer-kind` (Off / A second chat model / The decision model). It's **not** `reviewer-provider`, so
      the generic `[data-test]` handler doesn't add `provider` to the connection test.
    - `#reviewer-url` and `#reviewer-model` (hidden when Off; URL and model are hidden for "decision" too).
    - `#save-reviewer` (primary).
    - `#test-reviewer` with `data-test="reviewer"`, and `#test-reviewer-result`.
  - Filled from `settings.reviewer` in `loadSettings()`. Saved with
    `saveSettingsForm("reviewer-form", "/api/reviewer-settings", () => ({provider, base_url, model}), "Reviewer saved.")`.
    Only the fields the form shows are sent; the Sampling fields keep their saved values, sent back from
    `settings.reviewer`, as `#decision-form` does.
  - The lead copy: "Checks the reasoning runs that organize documents (started by the assistant or the API) against
    the document text before anything is filed automatically. A failed check from a second chat model stops
    automatic filing; a decision-model check is advice only."
- **Donate tab (`donate-tab` → `#donate-settings-panel`):** added **after Privacy & security**, so the
  Independent checks → Backup arrow order (test_browser.py:353–356) is unchanged. It contains:
  - a short lead (the Donate page's subtitle);
  - "N documents checked, ready to donate" from the existing donate list endpoint donate.js uses;
  - a primary link button "Open Donate documents" → `#/donate`.
  - The `#/donate` route and page stay as they are. `#nav-donate` stays in the sidebar until the navigation
    restructure (out of scope).
- **`processing.js` `[data-test]`:** no change. The `reviewer` kind works with `#reviewer-url`/`#reviewer-model` and no
  provider.

### Selector contract (Build C)
Every id and role name from the Explore list is kept, notably:
- the tab names "Library folder", "Local models", "Independent checks" (exact);
- `#checks-tab` → ArrowRight → `#backup-tab`;
- `#decision-status`, `#test-decision(-result)`;
- `#appearance-tab`, `#theme-*`, `#ui-v2-*`;
- `#profiles-tab`, `#family-section`, `#profile-*`;
- `#sharing-tab`, `#share-*`, `#session-*`;
- `#limits`, `#managed`, `#save-settings`;
- the toast texts.

New: `#reviewer-form`, `#reviewer-kind`, `#reviewer-url`, `#reviewer-model`, `#save-reviewer`, `#test-reviewer`,
`#test-reviewer-result`, `#donate-tab`, `#donate-settings-panel`. No existing test edits.

### States
- Busy inference disables the reviewer Save (add it to `controls()` with the vision and reasoning inputs) and says why.
- The server's 422 for a remote URL appears under `#reviewer-url`.
- In family mode the reviewer group is hidden (models are per computer), as the model forms are.
- Settings in dark theme: tokens only.

### Accessibility
The tablist is vertical (`aria-orientation="vertical"` at ≥800px, horizontal below). Every result line is
`aria-live="polite"`, and Save moves no focus.

### Verification (Build C)
- `$env:RUN_BROWSER_TESTS = "1"; .venv/Scripts/python.exe -m pytest tests/test_settings_browser.py tests/test_browser.py tests/test_shell_browser.py tests/test_family_browser.py tests/test_share.py tests/test_donate_browser.py -q`.
- The new `tests/test_settings_browser.py` covers:
  - `?tab=checks` opens Independent checks on reload;
  - saving the reviewer round-trips through `/api/settings`;
  - a remote URL shows the field error;
  - the Donate tab links to `#/donate`;
  - `NO_OVERFLOW` at 390/768/1440 on every tab.
- Shots: `--routes "settings,settings?tab=models,settings?tab=checks,settings?tab=donate"` (there is no flag; take
  before shots first from the current code).

---

## Out of scope (all builds)
- The global `#reconcile-prompt`, the sidebar's regrouping into the Redesigned navigation (Donate leaving the sidebar
  happens there), Search, Ask, and the `?` overlay.
- Deleting v1 loaders and CSS (item 8). `GET /api/tax-tags/on/…` (item 7's last endpoint, document page and drawer).
- Starting reasoning runs from the UI. Showing lot costs on Inventory rows (the server sends raw `cost_minor` only).
- Changing the synthetic model server's telemetry numbers.
- Copy not listed here.

## Verification (every build, besides its own list)
- Run only the build's files (memory: targeted test runs), plus the v1 test of any refactored v1 file.
- After shots versus before shots at 390/768/1440, in light and dark. No `HORIZONTAL OVERFLOW`, no page errors.
- Keyboard: tab through the page; the focus ring is visible and the order is header actions → tabs → tab content.
- No hex outside `:root` (Grep `#[0-9a-fA-F]{3,6}` in the new CSS), and no inline `style=`.

## Docs to update
- **docs/ui.md "Pages":** a "Home & things and System v2" bullet per screen (design in `pages/inventory.md` /
  `pages/system.md`, plan in `phase2-system-plan.md`).
- **"Processing":** fix the lane names, drop "Reconcile now", and add Data health.
- **"Settings":** add Independent checks, the Donate tab, and `?tab=`.
- **"Migration":** add `inventory` and `processing`, and say why Processing has no MIGRATED pair.
- **docs/household.md "The Inventory page":** tabs and Item insights.
- **docs/household.md "Item analysis":** the four traces.
- **docs/ui.md "Trace contract" › "What's built":** `items.*`.
- **docs/operations.md** (ledger health): the Data health tab and `link`.
- **docs/open-work.md:**
  - Record each build and name its v1 loader for item 8: `inventory.js` `loadInventory`, `inventoryRow`, and the
    `inventoryReload` hook; `processing.js` `loadProcessing`, `renderLanes`, `loadJobHistory`, plus `app.js`
    `loadSources`/`loadEvents`/`loadModelHistory` and the `processingReload` hook.
  - Remove Inventory, Processing and Settings from item 6.
  - Mark item 7's health, reviewer-settings and decision-model-tests as done.
  - Remove "Inventory" and "the Settings tab" from "Filters lost on reload".
- **Memory:** update the `observability-redesign-plan.md` line in MEMORY.md as each build lands.
