# Redesign: Taxes (phase 2)

First save this plan as `design-system/home-manager/phase2-taxes-plan.md`, as with phases 1a and 1b, and create
`design-system/home-manager/pages/taxes.md` from the "Design-system references" section below.

## Context
Taxes is the first Phase 2 screen and the first entry in `V2_SCREENS` and `MIGRATED`. Phase 1b built `figure()`, the
breakdown panel, `pageState()` and the `ui_v2_screens` flag; this screen is their first real user.

**What the user does here:** see where the tax year ends (refund or owed), why, and what to change, usually the W-4.
Then fix or add what the estimate is built from.

**What's wrong today** (before screenshots):
- The answer ("You'd owe 4,921.84") sits under about ten lines of Tax Zen prose.
- The "What it's built from" form is about 3,000px tall and runs beside the return.
- No figure opens its breakdown, although the backend traces every line.
- Write-offs, the CPA pack, rules and businesses are stacked below everything else.
- Five or more W-4 sentences have equal weight, so the one action doesn't stand out.

**Decided with the user (2026-10-10):**
1. **Six tabs, all built this session:** This year · Built from · Write-offs · Jobs & pay stubs · CPA pack ·
   Rules & sources (docs/ui.md "Redesigned navigation").
2. **The server sends full figures** for the return lines, the jobs' year figures, the records' values and Tax Zen's
   amounts. It's an additive change in `tax_traces.refs()`; the old fields stay.
3. **Tax figures show unsigned, and the label gives the direction.** "Refund" is green with `+`; "You'd owe" is text
   color with no sign. The breakdown answer follows the same setting. This closes the Phase 1b open item.
4. **This year** is the answer tiles, then one "What to do" region, then the return line by line.
5. **Built from** is a section list beside one section, shown as rows (Box · From records · Yours), with a sticky save bar.
6. **W-4 entries** move to Jobs & pay stubs, in each job's card.
7. **v1 stays** until Phase 3. v2 sits behind the flag with its own tests; nothing in v1 is deleted.

## Before screenshots
These were taken in planning, in the session scratchpad (they are lost when it's cleaned):
- `before-taxes/`: the default seed, which has no tax data, so it shows "Not enough to go on".
- `before-taxes-seeded/`: a scratch wrapper that adds the tax seed below. Look at `taxes-1440-light.png` and
  `taxes-390-light.png`.

The implementer re-takes both sets before editing, once step 7 below has added the tax seed to `ui_shots.py`:
`.venv/Scripts/python.exe .claude/skills/ui-redesign/scripts/ui_shots.py --routes taxes --full-page --out <scratchpad>/before-taxes`
Don't run browser tests while `ui_shots` is running.

## Design-system references
These go into `pages/taxes.md`:
- **MASTER "Components":**
  - **Figure tile:** label 12.5px secondary, `figure()` at `--figure-lg`, subline muted; accent border and ring when
    open (already in CSS as `.figure-tile`).
  - **Tinted region:** `--surface`, `--border`, `--radius-lg`, never nested. Used for "What to do".
  - **Table:** `.table-wrap` and `.data-table`, sticky header, amounts right-aligned.
  - **Status badge:** through `statusBadge()`.
  - **Chips:** not used.
- **MASTER "Layout":** page header with h1, muted subline and actions on the right (the year select). The breakdown
  panel is 360px beside the page from 1180px (the Phase 1b deviation stands).
- **MASTER "Meaning is fixed":**
  - Owed is not red. It's text color, unsigned.
  - Refund is `--positive` with `+`.
  - "Change recommended" is amber through `tax_action`.
  - "Not CPA-reviewed" is neutral.
- **Pro Max** (`search.py "personal tax return estimate dashboard…" --density 8`) returned "Data-Dense Dashboard" plus
  marketing patterns (Enterprise Gateway, hero, Fira fonts, a blue and amber palette). Keep only the density and
  row-hover table discipline. Drop the pattern, palette and fonts, because MASTER wins.
- **Deviations from MASTER:** none.

## Tokens
- **Existing:** `--surface`, `--surface-sunken`, `--border`, `--text`, `--text-secondary`, `--text-muted`, `--accent`,
  `--accent-subtle`, `--positive`, `--warning`, `--warning-subtle`, `--space-1..8`, `--radius-md`, `--radius-lg`,
  `--text-xs/sm/md/lg/xl`, `--figure-lg`, `--control-md/lg`.
- **New tokens:** none, so there are no new contrast pairs to check.

## Layout
Taxes isn't a decision screen, but "What to do" must be in view at 1366×768 (assert it).

**1440×900, This year, breakdown closed** (sidebar 220px, content padding 24/32):
```
Taxes                                                         Tax year [2026 v]
Where the tax year ends, why, and what to change.
[This year] Built from  Write-offs  Jobs & pay stubs  CPA pack  Rules & sources     <- .tabs
(table alerts here if a tax table isn't confirmed)
+-You'd owe-------------+ +-Total tax-------------+ +-Paid and credited-----+
| 4,921.84 USD          | | 17,385.20 USD         | | 12,463.36 USD         |
| Likely 4,292.84-5,607.84| Top federal bracket 22%| | Withholding projected  |
+-----------------------+ +-----------------------+ +-----------------------+
2026 · filing Single · worked out by Engine 1 · Engine 2 agrees ✓              (muted)
+-What to do-------------------------------- ! Change recommended  Aim [Come out at $0 v]-+
| On Employer's W-4, add 1,230.46 USD of extra withholding a paycheck (Step 4(c)).        |
| The year then ends at 0.00 USD. Takes effect after the next paycheck (Oct 23): 4 of 5.  |
| > Other ways (Step 4(a) instead · estimated tax · from January)                         |
| > What changed since Tax Zen last looked                                                |
+------------------------------------------------------------------------------------------+
The return, line by line
| Income                                                                                   |
|   Wages (every job's W-2 box 1) · 1 job                                     95,160.00 >  |
|   Taxable interest                                                          24,000.00 >  |
|   Adjusted gross income                                                    119,160.00 >  |
| Deductions  Standard deduction · itemized 0.00 against standard 16,100.00  −16,100.00 >  |
| ...                                                                                      |
> About these numbers
```
"What to do" ends at about y≈520 at 1366×768.

**1440, breakdown open:** the content column is about 796px. The tiles wrap to `auto-fit minmax(200px,1fr)`, so all
three stay on one row at 796px. The panel is beside the page.

**1440, Built from:**
```
[tabs]
+-Sections------+  Income                                                   2 typed
| Jobs        1 |  Box                                  From records     Yours
| Income      2 |  Taxable interest                     24,000.00 >     [          ]
| Adjustments   |    Projected to Dec 31: interest so far, projected …
| Deductions  1 |  Qualified dividends (1099-DIV 1b)    Enter it        [          ]
| Credits       |  ...
| Payments      |
| State         |
| People        |
| Last year     |
| Businesses    |
+---------------+
=== sticky bottom bar: "3 unsaved changes"     [Discard]  [Save and estimate again] ===
```
The section list is 200px (`.settings-nav`-like) and sticky. Rows are a grid `minmax(0,1fr) 150px 160px`.

**1440, Jobs & pay stubs:** one tinted region per job:
- **Header:** the employer, then "6 pay stubs through Jan 2 · next payday Oct 23 · 5 paychecks left".
- **Two columns:**
  - left, "This year": wages, federal withheld and state withheld as figures, plus "Per paycheck now: federal 479.36 ·
    state 159.22";
  - right, "W-4 on file": Step 2 checkbox, Steps 3, 4(a), 4(b), 4(c), and the line "Tax Zen suggests: Step 4(c)
    1,230.46 a paycheck" (inline figure).
- **Below:** a "Pay stubs" table (Pay date as a link to `#/documents/{id}`, Gross, Federal withheld, Net).

The same sticky save bar sits at the bottom of the tab.

**768:** the sidebar is a 64px rail, so the content is about 640px. The tiles are one row of three, or wrap to 2+1. The
Built from list stays 200px, and the rows become two lines (Box above, records and Yours below). The panel floats from
900px; below 900 it's a bottom sheet.

**390:**
```
Taxes                 [Tax year 2026 v]
[This year][Built from][Write-offs]…   <- .tabs scroll inside themselves (overflow-x:auto)
You'd owe
4,921.84 USD
Likely 4,292.84–5,607.84
Total tax  17,385.20 >
Paid and credited  12,463.36 >
What to do  ! Change recommended
 Aim [Come out at $0 v]
 On Employer's W-4, add 1,230.46 …
 > Other ways
The return (table in .table-wrap, scrolls inside)
```
- Built from: the section list becomes a `<select id="taxes2-section">` above the rows. Each row stacks Box, then
  From records, then Yours (full width). The save bar is pinned to the bottom of the viewport.
- There is no horizontal page scroll.

## Changes by file
Paths are under `src/home_manager/`. Build in this order and run the step's tests at the end of each step.

### 1. Backend: full figures (`finance/tax_traces.py` `refs()`)
Use `core/trace.py` `figure(amount_minor, currency, trace)`. Add these keys and keep every existing one:
- `return.lines[].figure`, from the line's `amount_minor` and `line["trace"]`.
- `gathered.figures[key]` for each key in `gathered.traces`, from `gathered.values[key]`.
- `gathered.jobs[].figures[field]` for each field in `JOB_FIELDS`, from `job.values[field]`.
- Tax Zen, only when `zen.ready`:
  - `zen.safe_harbor.figure`, `zen.advance.figure`, `zen.cushion.figure`, `zen.state.figure` and
    `zen.job.extra.figure`;
  - `zen.range.figures.{low,high}`;
  - `zen.job.{rest,january,step3}.figures.{per_check,year_end}`.

  Each takes the minor value its trace function reports as its result. Read each function (`safe_harbor`, `advance`,
  `cushion`, `state_advice`, `extra`, `likely_range`, `w4`, `w4_year_end`) to pick the key. Don't guess.
- `gathered.jobs[]` also gets `stub_list` (in `finance/tax_year.py` `jobs()`, not refs): one entry per stub, oldest
  first. Each has `income_id`, `document_id`, `pay_date`, and `gross`, `net` and `federal` as `core/money.py`
  `money()` dicts, with federal from `amounts(lines_of[id], "current_minor", "tax", ("federal_income_tax",))`. These
  are record values, not figures: the source is the document link.
- `traces.shown_tax` / `shown_family_tax` are unchanged; only `result_figure` carries `stale`.
- **Tests** (`tests/test_traces.py`): for a ready view, every new `figure` / `figures` value's `display` equals its
  trace's `result.display`, and the trace `reconciles`. Reuse the existing tax view setup in that file
  (`test_traces.py:435` area).

### 2. `ui.js` `amount()` and `trace.js` `figure()`: the sign option
- `amount(value, {signed = true, magnitude = false} = {})`. With `magnitude: true` no sign glyph is added at all (also
  no "−"), and no direction class. It's lexical only.
- `figure(fig, {size = "lg", signed = true, magnitude = false} = {})` passes both to `amount()`, and sets
  `button.dataset.signed` and `button.dataset.magnitude`.
- `openBreakdown(ref, opener)` stores `breakdown.sign = {signed: opener?.dataset.signed !== "false",
  magnitude: opener?.dataset.magnitude === "true"}`. `breakdownHeader`'s answer, the Running column and "Sums to" use
  it. Step values already use `{signed:false}` with the `op` glyph, so leave them. Drilled traces keep the opener's
  setting. Home and other callers are unchanged (the defaults).
- **Test:** extend `tests/test_trace_components_browser.py`: mount a figure with `{magnitude:true}` and assert no sign
  glyph appears in the button or the breakdown answer.

### 3. Shell and section
- **`index.html`:** a new section after `#taxes-panel`:
  `<section id="taxes2-panel" class="page" data-page="taxes" data-ui="v2" aria-labelledby="taxes2-title" hidden>`.
  - Header: `h1#taxes2-title` "Taxes"; the subline "Where the tax year ends, why, and what to change."; and
    `.page-actions` with `label.inline-field` "Tax year" around `select#taxes2-year`, then `select#taxes2-unit`
    ("Return", family view only, hidden otherwise).
  - `div#taxes2-state.page-state`.
  - `div#taxes2-body.page-body` containing:
    - `div.tabs#taxes2-tabs[role=tablist][aria-label="Taxes sections"]` with six buttons `#taxes2-tab-year`,
      `-built`, `-writeoffs`, `-jobs`, `-pack`, `-rules` (`role=tab`, `aria-controls` the panels);
    - six `section[role=tabpanel]` panels: `#taxes2-year`, `#taxes2-built`, `#taxes2-writeoffs`, `#taxes2-jobs`,
      `#taxes2-pack`, `#taxes2-rules`, each `aria-labelledby` its tab.
  - Script `<script src="/taxes_v2.js" defer></script>` after `trace.js` and before `shell.js`.
- **New `app/static/taxes_v2.js`:**
  - Registers `V2_SCREENS.taxes = {title: "Taxes", show: route => loadTaxesV2(route.params)}`.
  - `loadTaxesV2(params)`: `pageState($("taxes2-state"), renderTaxesV2, {loading: "Loading this year's taxes …",
    what: "this year's taxes", needsLibrary: true, content: [$("taxes2-body")]})`.
  - URL params: `year`, `tab` (year|built|writeoffs|jobs|pack|rules, default year), `section` (Built from) and
    `unit` (family). Change them with `history.replaceState` (the `finance.js:106` pattern), not a reload.
  - Tabs use `wireTabs([...ids])` from `app.js`. Each tab renders on its `tabshow` (lazy) from the cached view. A save
    marks the other tabs stale, and they re-render on their next `tabshow`.
  - Year select: as v1 (next year down to five back). Changing it while the draft is dirty asks
    `confirmAction({title: "Discard 3 unsaved changes?", confirmLabel: "Discard", danger: true})`.
  - Data is fetched in parallel, the same calls as v1 `renderTaxes`, plus `GET /api/rule-sources` when the Rules tab
    is first shown.
  - `shell.js`: nothing to change. The registry and section switching already exist (`shell.js:86-87`).

### 4. This year tab (`renderYearTab(view)`)
**Alerts:** the v1 table alerts (`taxes.js:388-395`). Move that loop into a shared `taxTableAlerts(view)` in `taxes.js`
that returns nodes, and have v1 call it. v1's behaviour doesn't change.

**Not ready** (`result_minor == null`):
- `emptyState(result.notes[0])` and the Zen note;
- a `link-button` "Fill in what's missing" that switches to Built from;
- when `zen.status` is `INSUFFICIENT_DATA`, also a link to `#/settings`.

**Answer tiles,** `div.taxes2-answer`, a grid `repeat(auto-fit, minmax(200px, 1fr))` with gap `--space-4`. Each tile
is a `.figure-tile`:
1. **The result:**
   - Label: "Refund" if `result.result.refund`, "Tax Zen" if 0, else "You'd owe".
   - Figure: `figure(result.result_figure, {signed: refund, magnitude: !refund})`.
   - Subline, when `zen.range` exists and low ≠ high: "Likely " + figure(low, inline, magnitude) + " – " + figure(high,
     inline, magnitude) + " · {confidence} confidence".
2. **Total tax:** the `total_tax` line's `figure` (`{magnitude:true}`), with the subline "Top federal bracket
   {marginal_percent}%".
3. **Paid and credited:** the `total_payments` line's figure (`{magnitude:true}`), with the subline "Withholding
   projected to Dec 31".

**Meta line,** `p.muted.small`: "{year} · filing {filing_status_name} · worked out by {engine.label}", then
" · {other} agrees ✓" when `comparison.agree`. A disagreement shows the v1 warning `alertBox` with its diff table under
the return table. Keep the v1 wording; never name engine products.

**What to do,** `section.panel.taxes2-advice[aria-labelledby=taxes2-advice-title]` (`.panel` is the tinted region, `style.css:227`):
- Head row (flex, wrapping):
  - `h2#taxes2-advice-title` "What to do";
  - `statusBadge(ZEN_BADGES[zen.status])`;
  - right-aligned, `zenPolicyForm`'s Aim select and amount. Generalise v1's `zenPolicyForm(view)` to
    `zenPolicyForm(view, {ids, save})` so v2 uses ids `taxes2-zen-strategy` / `taxes2-zen-amount` and saves through
    the v2 save. v1 passes its current ids and save.
- **Lead**, `p.taxes2-advice-lead` (`--text-md`, 600). One sentence, picked like v1:
  - `zen.zen`: "You're Tax Zen for {year}: the return comes out at your aim ({aim})."
  - `job.primary === "extra"`: "On {job}'s W-4, add {figure(extra.figure, inline, magnitude)} of extra withholding a
    paycheck (Step 4(c))."
  - otherwise: "On {job}'s W-4, put {figure(rest.figures.per_check …)} …". Use v1's text (`taxes.js:343-350`), with
    `rest.display.amount` as text (a W-4 entry, not a figure).
  - `rest.unreachable`: v1's sentence.
  - no job but `zen.advance`: "Pay {figure(advance.figure)} as estimated tax (1040-ES); quarters below."
  - `zen.cushion`: its text.
- **Second line,** `p.small.muted`: "The year then ends at {refund of / owing} {figure(year_end, inline, magnitude)}."
  plus v1's timing sentence (`taxes.js:330-331`).
- `details` "Other ways" (only when there are any):
  - the non-primary option (4(a)/4(b) or 4(c));
  - step3;
  - January;
  - the "Change the W-4 at" job picker (`taxes2-zen-job`);
  - the estimated-tax block with v1's quarters table (`trackTable` …), its amounts through `amount()`.
- `details` "What changed since Tax Zen last looked": `zen.changed.texts`.
- `zen.state.text` and `zen.notes` as `p.muted.small`.

**The return, line by line:** `h2` "The return, line by line", then a `.table-wrap` holding a `table.data-table
.taxes2-return`:
- Group rows `th[scope=rowgroup]` as v1 (`RETURN_SECTIONS`). The same zero-line skip as v1 (`taxes.js:412`).
- Each row: `th[scope=row]` label plus `small.muted.block` how; the amount cell holds `figure(line.figure, {size:
  "inline", signed: false})` (keeps "−" for the standard deduction).
- Total rows keep a 600 weight (reuse the `.paystub-total` style or add `.taxes2-return .total`).

Then the state paragraph as v1, and `details` "About these numbers" (`result.notes` + `gathered.notes`).

### 5. Built from and Jobs & pay stubs (one shared draft)
- **`taxDraft`:** an object shaped like the PUT body (`fields, jobs, businesses, extra_jobs, people, w4,
  prior_year_tax` plus the rest of `view.inputs`). It's cloned from `view.inputs` when the view loads and updated on
  each `input`/`change`.
- **Dirty count:** the number of keys that differ from `view.inputs`.
- **`buildRequest()`:** returns the draft with the same trimming rules as v1 `taxInputsRequest` (`taxes.js:545-563`).
- **Save bar,** `div.taxes2-savebar` (`position: sticky; bottom: 0`; `--surface`, top `--border`, padding
  `--space-3 --space-4`), at the end of both the Built from and Jobs panels. It holds:
  - `span[aria-live=polite]`: "No changes" or "{n} unsaved change(s)";
  - `button.secondary` "Discard", disabled when clean;
  - `button.primary` "Save and estimate again", disabled when clean.

  Save: `PUT /api/tax/year/{y}` (or `/api/tax/family/{y}/{unit}`), then re-render from the returned view and
  `notice("Saved; the return is estimated again.")`. On failure, an `alertBox` (role=alert) inside the bar, not a
  toast.
- **Built from** (`renderBuiltTab`):
  - Left: `div.taxes2-sections[role=tablist][aria-orientation=vertical]`, with buttons `#taxes2-sec-<key>` for
    jobs, income, adjustments, deductions, credits, payments, state, people, last-year and businesses.
    - Each shows the label plus a count (`span.nav-count`, the neutral pill, `style.css:206`) of typed values in it.
    - It uses `wireTabs`.
    - Under 900px it's hidden, and `select#taxes2-section` is shown instead.
  - Right: `section#taxes2-section-body`, with an `h2` naming the section and "{n} typed" muted.
    - It holds a `div.taxes2-rows` grid with a header row (Box · From records · Yours).
    - Each money field row has:
      - Box: the label plus `small.value-kind.value-kind-{kind}`, reusing `valueKind()`'s words and sources (factor
        out a `valueKindText(typed, gathered, key)` that both call);
      - From records: `figure(gathered.figures[key], {size: "inline", signed: false})`, or "Enter it" muted for
        `to_enter`, or "—";
      - Yours: `input` (`inputmode=decimal`, 160px, `data-field=key`, labelled by the Box text via
        `aria-labelledby`).
    - Count fields, selects (HSA coverage, itemize, tipped occupation) and the `RETURN_FIELDS` grouping are reused
      from `taxes.js:197-214` as they are.
  - **Jobs section:** per `gathered.jobs`, the rows Wages, Federal withheld, State withheld, Medicare wages. Records
    are `job.figures[field]`; Yours goes in the draft `jobs[key][field]`. Below them, the extra jobs (v1
    `addExtra` rows, re-built as rows) and a secondary "Add a job not in your pay stubs" button.
  - **People:** spouse name and birth year.
  - **Last year:** total tax and AGI, plus `view.prior_year.source`.
  - **Businesses** (open-work item 7):
    - per business, rows for Income and Expenses (records = `business.display`, plain text) and Yours;
    - a "Rename" text button (inline input, `PUT /api/tax/businesses/{id}`);
    - "Remove" (`confirmAction`, danger, then `DELETE /api/tax/businesses/{id}`);
    - the add form (`POST /api/tax/businesses`), as v1.
    - Ids come from `GET /api/tax/setup` `businesses`, matched by `business-{id}` keys.
- **Jobs & pay stubs** (`renderJobsTab`): one `section.panel.taxes2-job` per `gathered.jobs`:
  - `h2` with the employer name.
  - `p.muted.small` built from v1's sentence parts (`taxes.js:461-464`), with dates via `dateText`.
  - `div.taxes2-job-grid` (2 columns ≥ 900, 1 below):
    - **This year:** a `dl` of figures (`job.figures.wages/federal_withheld/state_withheld`, `{signed:false}`), plus
      "Per paycheck now" from `job.per_check_display` as text.
    - **W-4 on file:** the Step 2 checkbox and four inputs with `data-w4`/`data-key` exactly as v1
      (`taxes.js:471-477`), bound to the draft.
    - When `zen.job.key === job.key`, a line "Tax Zen suggests …" with the same lead wording and a link-button "Why"
      that switches to This year.
  - A "Pay stubs this year" `.table-wrap` table: Pay date (a `homeLink` to `#/documents/{document_id}`, text
    `dateDisplay`), Gross, Federal withheld, Net, each through `amount(..., {signed:false})`.
  - No jobs: `emptyState("No confirmed pay stubs for {year} yet. Pay stubs you add go in Documents › Jobs.")`.
  - The same save bar at the end.

### 6. Write-offs, CPA pack, Rules & sources; the family view
- **Write-offs:** a v2 `renderWriteOffsV2(host, summary, tags)` with the same content as v1 `renderWriteOffs`. The
  "Counts" column uses `figure(line.counted, {size:"inline", signed:false})` (already a full `tax.tags` figure) and
  "Amount" stays `amount`. Reuse `taxItemLink`, `TAX_SOURCES` and the "Not a write-off" action (then reload v2). The
  empty text is the same as v1.
- **CPA pack:** generalise `loadCpaPacks(year, host = $("taxes-pack"), reload)` so v2 passes `#taxes2-pack-body`.
  Put the v1 explainer paragraph (index.html 187-189) above it as a `p.muted`. `downloadCpaPack` is reused.
- **Rules & sources,** three `h2` blocks:
  1. **"Tax rules"**: generalise `renderTaxRules(rules, setup, host, reload)`, plus the v1 explainer line.
  2. **"Tax tables for {year}"**: one row per `view.tables` entry (federal or state, status badge: verified → no
     badge, "Confirmed"; proposed → `needs_review`; missing → the v1 lookup button).
  3. **"Rules and sources"**: `ruleCard(rule)` for each `GET /api/rule-sources` entry, in a single column with
     `--space-3` gaps (`ruleCard` already styles itself).
- **Family view** (`familyMode`):
  - `#taxes2-unit` is shown, with one option per `family.returns` ("{name} · {filing}").
  - The This year tab starts with `p` (the v1 family Zen line) and a `.table-wrap` table of returns: Name, Filing,
    Result (`figure(item.view.return.result_figure, {size:"inline", …sign as above})` or the note), and actions
    "Open" (sets `unit`) and "Remove" (v1 confirm).
  - Then "Add a return": move v1's form builder (`taxes.js:249-266`) into `familyUnitForm(family, onAdded)`, used by
    both.
  - The selected unit's view drives This year, Built from and Jobs.
  - Write-offs, CPA pack and Rules & sources tabs are `hidden` in the family view, with this note under the tabs:
    "Write-offs and tax rules are kept in each person's own profile."

### 7. Seeds, harness and screenshots
- **The seed:** move the tax seed into a helper `seed_tax_year(manager, store, ledger)` in
  `tests/test_taxes_browser.py`. It sets the birth year 1985, the `confirmed(TaxTables(store), "US", FEDERAL)` table, a
  pay stub via `stub(...)` with pay_frequency 26, and 20,000 of interest: today the inline code at
  `test_taxes_browser.py:48-61`. The existing test calls the helper. The helper is a no-op returning False when
  `date.today().year not in YEARS`.
- **`ui_shots.py`:**
  - `seed()` calls `seed_tax_year` (imported from `test_taxes_browser`).
  - After each route's `networkidle`, it waits with `page.wait_for_selector("[aria-busy='true']",
    state="detached", timeout=120000)`. That's a selector wait; string `wait_for_function` is blocked by the CSP.
- **`tests/test_ui_parity.py`:**
  - `seeded_server` also calls `seed_tax_year`.
  - `MIGRATED = [("taxes", "taxes")]`, with the param skipped when the year isn't covered (as `this_year_covered`).
  - `v1_amounts(page)` returns the `.amount[title]` set **and** the v1 main text
    (`page.locator("[data-page]:not([hidden])").inner_text()`).
  - `missing` = displays found in neither. v1 writes Tax Zen amounts inside sentences.
  - The self-test must still fail on the seeded mismatch, so keep "999,999.99 USD".
  - The parity run sees the This year tab only (the tabs are lazy). The other tabs' figures are checked by the new
    browser test with `check_figures`.

### 8. CSS (`style.css`, a new block `/* Taxes v2 (taxes_v2.js) */` after the Taxes section, tokens only)
- `.taxes2-answer` is the tile grid.
- `.taxes2-advice` takes its box from `.panel`. Its head is `display:flex; flex-wrap:wrap; gap:var(--space-3);
  align-items:center`, and the Aim field is pushed right with `margin-left:auto`.
- `.taxes2-advice-lead` is `font-size: var(--text-md); font-weight: 600`.
- `.taxes2-built` is a grid `200px minmax(0,1fr)`, gap `--space-6`. Below 900 it's a single column, the sections
  tablist is hidden and `#taxes2-section` is shown.
- `.taxes2-sections` reuses the `.settings-nav` look. Add it to that selector list rather than copying the rules.
- `.taxes2-rows` is a grid `minmax(0,1fr) 150px 160px`. Row padding `--space-2 0` with a 1px `--border` divider. The
  records column is right-aligned with `tabular-nums`. Below 600 each row is one column.
- `.taxes2-savebar` as in step 5. Below 900 it's `position: sticky; bottom: 0` within the viewport (as
  `.donate-decision`).
- `.taxes2-job-grid` is 2 columns ≥ 900.
- Nothing in the page flow gets a shadow, and no hex values are added.

## Selector contract
v1 is unchanged, so its contract holds. Every selector below stays as it is in this change:
- **Ids:** `#nav-taxes`, `#taxes-zen`, `#taxes-inputs`, `#taxes-return`, `#taxes-year`, `#taxes-state`, `#taxes-body`,
  `#taxes-family`, `#taxes-unit-status`, `#taxes-return-title`, `#taxes-write-offs`, `#taxes-rules`,
  `#taxes-businesses`, `#taxes-zen-strategy`, `#taxes-zen-amount`, `#taxes-extra-jobs`.
- **Classes and attributes:** `.taxes-personal`, `.taxes-zen-headline`, `.value-kind`, `.plan-figure`,
  `.taxes-extra-job`, `[data-w4][data-key]`, `.status-badge[data-status=tax_action]`.
- **Roles and labels:** the button "Save and estimate again", the button "Add a return", the button "Add a job not in
  your pay stubs".

All of those are used by `tests/test_taxes_browser.py`. Also unchanged:
- `#tx-drawer`, `.tax-tag-form` and `#close-tx-drawer` (used by `test_taxes_browser.py` through `finance.js`, untouched);
- `#breakdown`, `#breakdown-title` and `#breakdown-state` (used by `test_trace_components_browser.py`).

Two refactors must keep v1's ids:
- `zenPolicyForm` called with `{ids: {strategy: "taxes-zen-strategy", amount: "taxes-zen-amount"}}`;
- `loadCpaPacks` / `renderTaxRules` with the default host `#taxes-pack` / `#taxes-rules`.

New v2 selectors all use the `taxes2-` prefix (ids above), so nothing clashes while both sections are in the DOM.

## States
- **Loading / error / no library:** `pageState` on `#taxes2-state`. On an error it hides `#taxes2-body`, and the year
  select stays usable.
- **Not ready** (no table, no birth year): This year shows the empty state with links. The other tabs still work;
  Built from is how the user fixes it.
- **Table not confirmed:** the warning alert at the top of This year, and the Rules & sources table list.
- **Zen statuses:**
  - ZEN: the lead sentence, with no Other ways unless there are alternatives;
  - WATCH and AT_RISK: the reason as the lead;
  - REVIEW_REQUIRED and ENGINE_UNSUPPORTED: the badge and note only.
- **Engines disagree:** the warning alert with its diff table.
- **Long text:** employer and business names wrap (`overflow-wrap:anywhere` in tiles and job headers). A long rule
  pattern wraps in its cell.
- **Many rows:** the return and pay-stub tables scroll inside `.table-wrap`; the Built from list is sticky.
- **Dark theme:** tokens only. Check tiles, the advice region, the save bar and the rows in dark screenshots.
- **Family profile:** as in step 6. The Return select, no write-off/CPA/rules tabs, and per-unit saves.
- **Unsaved edits:** kept across tab switches; a year or unit change asks first.

## Accessibility
- **Focus order:** year → (Return) → the tabs (one tab stop; arrows move, as `wireTabs`) → the panel → the save bar.
- Opening a figure focuses `#breakdown-title`. Esc returns focus to the figure (built).
- Each tab panel has an `h2` (This year's are "What to do" and "The return, line by line"). The page has one `h1`.
- **Inputs** in Built from rows are labelled by their Box text (`aria-labelledby`). The W-4 inputs keep visible
  `<label>`s.
- **Save bar:** the count is in an `aria-live=polite` span, and a save error has `role=alert`.
- **Never color alone:** refund is `+` and the word "Refund"; owed is the words "You'd owe". The Zen status is a badge
  with icon and text, and typed values carry "You typed: …" text.
- **Reduced motion:** nothing new animates. The panel motion is already handled.

## Out of scope
- v1 Taxes markup, CSS and behaviour, except the four refactors named above (`taxTableAlerts`, `zenPolicyForm`
  options, `loadCpaPacks`/`renderTaxRules` host params, `familyUnitForm`, `valueKindText`).
- Any other page; the sidebar labels (renaming nav waits for its screens).
- `historyList()` for typed-over history (To check session). Built from shows the current typed value only.
- Backend beyond step 1, and any new tax logic.
- The Phase 1a open items (dark `--chart-seq-8..10`).

## Verification
- **Backend:** `.venv/Scripts/python.exe -m pytest tests/test_traces.py tests/test_tax_year.py -q`. Use whichever tax
  view tests exist; Grep `def test_.*tax_view|refs\(` in tests/.
- **Browser** (don't run while `ui_shots` runs):
  `$env:RUN_BROWSER_TESTS = "1"; .venv/Scripts/python.exe -m pytest tests/test_taxes_v2_browser.py tests/test_ui_parity.py tests/test_trace_components_browser.py tests/test_taxes_browser.py -q`
- **New `tests/test_taxes_v2_browser.py`** (the server set up as in `test_taxes_browser.py` with `seed_tax_year`, then
  `PUT /api/ui-screens {"routes":["taxes"]}`):
  1. This year:
     - three `.figure-tile`s, the first labelled "You'd owe";
     - its figure has no sign glyph;
     - clicking it opens `#breakdown` with the focus on `#breakdown-title`;
     - "What to do" contains "of extra withholding a paycheck";
     - `#taxes2-advice-title` is in view at 1366×768 (`box.y + box.height <= 768`);
     - `check_figures` passes.
  2. Built from:
     - `?tab=built&section=income` is in the URL after clicking;
     - typing in Taxable interest shows "1 unsaved change";
     - switching to Jobs and back keeps the value;
     - Save re-estimates, and the count goes back to "No changes";
     - `check_figures` passes on this tab.
  3. Jobs & pay stubs:
     - entering 5000 in `[data-w4][data-key=other_income]` and saving changes the "Other ways" Step 4(a) text on This
       year;
     - a pay stub row links to `#/documents/`;
     - `check_figures` passes.
  4. Write-offs shows the empty text; CPA pack shows "Build the {year} CPA pack"; Rules & sources shows at least one
     `.rule-card`.
  5. Family: the Write-offs/CPA/Rules tabs are hidden and the Return select is visible. Reuse the family setup from
     `test_the_family_files_a_joint_return`.
  6. A failed `/api/tax/year/*` shows the `#taxes2-state` alert, hides `#taxes2-body`, and keeps the year select
     enabled.
  7. No horizontal overflow at 390/768/1440 on every tab, and no page errors.
- **After screenshots:** `ui_shots.py --routes taxes --full-page --out <scratchpad>/after-taxes` with the flag on. Add
  `--v2 taxes` to `ui_shots.py`: it PUTs `/api/ui-screens` before the shots. Compare with the before set at every width
  and theme. There must be no `HORIZONTAL OVERFLOW` and no page errors.
- **Keyboard:** Tab through every tab; arrow keys move between tabs; the focus ring shows on figures, tabs, section
  buttons and inputs.
- **Contrast:** no new tokens. Check that the refund tile's green on the tile surface is in MASTER (positive/surface 5.4
  light, 8.4 dark).

## Docs to update
- **docs/ui.md:**
  - "Observability components": `figure()`'s `signed`/`magnitude` options and the breakdown following its opener; Taxes
    v2 is the first user.
  - "Migration": Taxes is registered, `MIGRATED` has `("taxes","taxes")`, and `v1_amounts` also reads the old screen's
    text.
  - "Pages": a Taxes v2 line with its six tabs and URL params.
  - "Money and dates on screen": `amount()`'s `magnitude`.
- **docs/taxes.md:** the intro (lines 3-10) describes the v2 tabs, and "Jobs and pay stubs" mentions the Taxes tab
  (`stub_list`).
- **docs/open-work.md "UI redesign":** Taxes v2 is built (v1 removal in item 8 cleanup); remove "PUT/DELETE
  /api/tax/businesses/{id}" from item 7; the next screen is Today.
- **design-system/home-manager/:** `pages/taxes.md` (new), `README.md` (a Phase 2 Taxes section, and the Phase 1b
  sign open item resolved), and `phase2-taxes-plan.md` (this plan).
