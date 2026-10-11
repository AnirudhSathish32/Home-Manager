# Redesign: the Money screens — This month, Transactions, Bills & subscriptions, Accounts (phase 2)

One plan, four builds. **Each build is its own implementation session**, in order A → B → C → D, built, verified and
(when the user asks) committed on its own. "Shared" sections apply to every build. Copy this plan to
`design-system/home-manager/phase2-money-plan.md` at the start of Build A (it's the hand-off the later sessions read),
and write `design-system/home-manager/pages/money.md` from the "Design-system references" section below.

## Context
docs/open-work.md "UI redesign" item 6 puts the Money screens next, after Taxes, Today, To check and the document page
(all built behind `ui_v2_screens`). docs/ui.md "Redesigned navigation" names them: **This month** (`#/spending`),
**Transactions** (+ Add, Import), **Bills & subscriptions** (`#/bills`), **Accounts** (+ Import).

User's jobs (asked 2026-10-11):
- **This month:** see where the money went, check budgets, compare with another month, and manage category rules —
  all four, on one page in two columns.
- **Transactions:** find a payment, fix its category, add one by hand (money.md "Manual transactions" says the
  redesigned screen adds the form), and import a bank/card export.
- **Bills:** see what's due and whether it was paid; decide on proposed recurring payments; bill vs subscription.
- **Accounts:** each account's balance and how fresh it is; import an export.

What's wrong today (before screenshots):
- Spending: the coverage paragraph dumps internal notes (`pending_review`, `usd_total`, `rate_ids`) under the figures;
  figures aren't traceable; budgets sit in a wide region with one-off forms; rules take a full region even when empty;
  category names are lower-case raw keys (`housing`); merchants are raw upper-case statement text.
- Transactions: at 390 the table squeezes to one character per line (EGGS → "EG / GS"); 16 category `<select>`s per
  screen; "Household checking checking" (display name + type); no Add, no Import; filters take three rows.
- Bills: "Upcoming" with one "Later" heading and a long note; subscriptions region is a big empty box; proposed
  payments' Confirm sits in a table at the bottom; no totals on bills.
- Accounts: no Import; stale badge says "Stale · Needs review"; an empty-balance row is a long sentence.
- All four: the global reconcile prompt sits above the h1 (out of scope here, see "Out of scope").

## Before screenshots
`C:\Users\Anirudh\.claude\jobs\2d4dc512\tmp\before-money\` (scratch; regenerate if gone). Look at
`spending-1440-light.png`, `transactions-1440-light.png`, `transactions-390-light.png`, `bills-1440-light.png`,
`accounts-1440-light.png`, and the dark versions. **Each build re-takes its own before shots first**, on the extended
seed (Shared › Seeding), with the flag off:
`.venv/Scripts/python.exe .claude/skills/ui-redesign/scripts/ui_shots.py --routes <route> --full-page --out <scratch>/before-<route>`.

## Design-system references
MASTER.md applies unchanged. Used sections:
- "Components" › Figure tile, Tinted region (never nested; lists inside use 1px dividers), Needs-attention row, Table
  (sticky `--surface-sunken` header, 40px rows, right-aligned amounts with a fixed sign slot, transfers muted with ⇄),
  Chips (30px pills, pressed = `--accent-subtle` + `--accent` border), Status badge, Budget meter (amber for ahead and
  over, **never red**), Buttons (one primary per region).
- "Layout" › Page header (h1, muted subline, actions on the right, one primary), breakdown panel (shared `#breakdown`).
- "Meaning is fixed": spending is `--text` with `−`/unsigned; money in `--positive` with `+`.

`pages/money.md` (new, Build A writes it; same shape as `pages/today.md`): the user's jobs above, then Components /
Layout / States / Decided per screen, copied from the Layout and States sections of this plan. Decided (2026-10-11):
one page in two columns for This month; rules folded at the bottom of This month; stacked rows at 390 for
Transactions; Import picks a CSV/XLSX already in the library (no browser upload).

Deviations: none from MASTER. One from v1 behaviour: **category names show through `categoryLabel()`** everywhere on
these screens (v1 Spending showed raw keys).

## Tokens
No new tokens. Used: `--canvas`, `--surface`, `--surface-sunken`, `--border`, `--border-strong`, `--text`,
`--text-secondary`, `--text-muted`, `--accent`, `--accent-subtle`, `--on-accent`, `--positive`, `--warning`,
`--warning-subtle`, `--danger` (overdue badge only, through STATUS), `--chart`, `--chart-track`, `--space-*`,
`--radius-*`, `--text-*`, `--figure-lg`. Every pair used is already in MASTER "Checked contrast" (text/surface,
secondary/sunken, accent/accent-subtle, warning/warning-subtle, chart/track, warning/track). No hex outside `:root`.

**New icons** in `ui.js` `ICONS` (Lucide paths, same license as the rest): `plus` `["M5 12h14","M12 5v14"]`,
`chevron-left` `["m15 18-6-6 6-6"]`, `arrow-up` `["m5 12 7-7 7 7","M12 19V5"]`, `arrow-down`
`["M12 5v14","m19 12-7 7-7-7"]`. Build A adds all four.

---

## Shared (applies to every build)

### Registration pattern (copy today_v2.js)
- One file per screen, loaded with `defer` in `index.html` after `today_v2.js` and before `shell.js`:
  `month_v2.js` (A), `money_v2.js` + `transactions_v2.js` (B; `money_v2.js` holds the Add and Import dialogs that D
  reuses), `bills_v2.js` (C), `accounts_v2.js` (D).
- **Every new static file must be added to `api.py`'s static allowlist**, or it 404s (seen in the Today build).
- Seeds: `Reconciler.run()` resets categories set without `category_source='user'`, so seeds must set it.
- Each registers `V2_SCREENS.<route> = {title, show: route => load…V2(route.params)}` with route names `spending`,
  `transactions`, `bills`, `accounts` and titles "This month", "Transactions", "Bills & subscriptions", "Accounts".
- Each adds `<section id="<prefix>-panel" class="page" data-page="<route>" data-ui="v2" aria-labelledby="<prefix>-title" hidden>`
  right after its v1 twin in `index.html`, with `header.page-header` (h1 `tabindex="-1"`, `p.page-subtitle`,
  `div.page-actions`), then `div#<prefix>-state.page-state`, then `div#<prefix>-body.page-body`.
  Prefixes: `month2`, `tx2`, `bills2`, `accounts2`. **Never reuse a v1 id**; v1 stays until item 8.
- `show` parses and validates its URL params into a module state object, sets the controls, and returns
  `pageState($("<prefix>-state"), render…V2, {loading, what, needsLibrary: !familyMode, content: [$("<prefix>-body")]})`.
- URL writes: `history.replaceState` with only non-default params, setting `currentRoute.params` when
  `currentRoute?.name === "<route>"` (today_v2.js `reloadToday`).
- `shell.js` `setHomeNavLabel` (104-109): extend so that while on, `#nav-spending` reads "This month" and `#nav-bills`
  reads "Bills & subscriptions" (Transactions and Accounts keep their labels).
- Amounts only through `amount()`/`figure()`; dates through `dateText()`/`dateDisplay()`; status through
  `statusBadge()`. No arithmetic: comparisons like `row.change.minor > 0` to pick an icon are allowed, sums are not.
- Family view: all four routes are in `FAMILY_ROUTES` (shell.js:75-76). Data comes through `ledgerTool` (finance.js:7)
  as v1 does. Personal-only controls (budgets, rules, Add, Import, kind select, Confirm/Ended) get `.personal-only`
  or aren't built when `familyMode`. Owner shows as a column (`.owner-col`) or a "· Jo" suffix as v1 does.
- Long text: names wrap (`overflow-wrap:anywhere`), amounts never wrap (`white-space:nowrap`).

### Reused helpers (don't re-create)
`ui.js`: `amount`, `dateText`, `monthText`, `dateDisplay`, `statusBadge(status, prefix, label)`, `emptyState`,
`alertBox`, `pageState`, `confirmAction`, `kindSelect`, `categoryLabel`, `FREQUENCY_LABELS`, `icon`, `menu`.
`trace.js`: `figure(fig, {size, signed, magnitude})`, `openBreakdown`. `app.js`: `element`, `cell`, `wireTabs`,
`notice`. `home.js`: `homeLink`. `finance.js`: `ledgerTool`, `tool`, `meter(row)`, `txHref`, `monthRange`,
`shiftMonth`, `todayIso`, `asyncButton`, `accountOption`, `accountArgs`, `loadCategoryOptions`, `openTransaction`,
`chargeCategorySelect`, `receiptLink`, `originalButton`, `describeFilters`, `refreshReviewCount`.
`library.js`: `openImport(doc)` and the existing `#import-dialog`. `today_v2.js` CSS classes: `.figure-tile`,
`.figure-label`, `.figure-sub`, `.today-region` (tinted region), `.needs-row(.attention)`, `.dated-list`, `.dated-row`.

### Seeding (`.claude/skills/ui-redesign/scripts/ui_shots.py`, Build A does this first)
Extend `seed_today()` (or add `seed_money()` called from `seed()`), synthetic data only:
- a confirmed **subscription** (three monthly "STREAMING PLUS" 15.99 charges → `Reconciler.run()` →
  `review_obligation(id, "verified")`, then kind `subscription`);
- a **proposed** recurring payment (e.g. "HARBOR INSURANCE" 100.00 monthly, left proposed);
- a posted **refund** credit this month on the card (Fresh Market, +12.48, type refund);
- one **manual** transaction (`ledger.add_manual_transaction` or the POST through the TestClient) "Farmers market"
  23.00 cash-out from checking;
- one **importable CSV** in the inbox with three real rows (`bank-export.csv`: `Date,Description,Amount`), not imported;
- a category rule ("METRO" → transport).
Keep the existing seed working for Today/Taxes/To check shots (re-run those routes once to confirm no page errors).

### Tests (pattern)
Each build adds `tests/test_<route>_v2_browser.py` using `served()` from `tests/test_taxes_v2_browser.py` and the
seeding helpers of `tests/test_today_v2_browser.py` (`inbox_scan`, `ledger.create_account`, `add`, `receipt`,
`set_budget`, `Reconciler`). Flag on with `page.request.put(f"{base}/api/ui-screens", data={"routes": [...]}, headers=…)`.
Every test collects `pageerror`s (none allowed) and checks `NO_OVERFLOW` at 390, 768 and 1440. Each build adds its
`MIGRATED` pair to `tests/test_ui_parity.py` where noted, extending `seeded_server` only if the screen has no traced
figure on the default parity seed.

---

## Build A — This month (`#/spending`, `month_v2.js`)

### Backend
None. Every traced figure already exists: `get_spending.by_currency[].net_spending` (`spending.net`),
`get_spending_by_category.categories[].spending` (`spending.category`), `get_budgets` `spent`/`remaining`/`projected`
(`spending.category`, `budget.remaining`, `budget.projected`). The previous month's figures come from calling
`get_spending` and `get_spending_by_category` **again for the comparison period**, so they're traced too.
`compare_categories` is still called for `change` and `percent_change` (plain, not traceable: shown as text).
**Check while building:** a category's previous-month figure from `get_spending_by_category` must equal
`compare_categories.first` for that category. If any differ on the seed, stop and report (don't show both).

### Data (one `Promise.all`, as v1 `loadSpending` 513-516)
`ledgerTool("get_spending", period)`, `ledgerTool("get_spending", comparePeriod)`,
`ledgerTool("get_spending_by_category", period)`, `ledgerTool("get_spending_by_category", comparePeriod)`,
`ledgerTool("compare_categories", {first: comparePeriod, second: period})`, `ledgerTool("get_refunds")`,
and when not family: `tool("get_budgets", {month, as_of: todayIso()})`, `api("/api/finance/category-rules")`,
`loadTransactionOptions()` (for the rule form's account select and `#category-options`).
URL params: `month` (YYYY-MM, default this month), `compare` (`previous` default | `last_year`), `currency`
(only when the data has more than one currency; default as Today: home currency, else USD, else first).

### Layout at 1440×900
```
┌ sidebar ┐ This month                       [‹] [October 2026 ▾] [›]   Compare [Previous month ▾]  [USD ▾]
│         │ Where October's money went, and how each budget is doing.
│         │ ┌Net spending──────┐┌September─────────┐┌Refunded─────────┐┌Budgets──────────────┐
│         │ │ 2,158.06 USD     ││ 1,902.50 USD     ││ 12.48 USD       ││ 1 over · 1 on track │
│         │ │ 8 transactions   ││ ▲ 255.56 more    ││ 1 credit posted ││ Day 10 of 31        │
│         │ └──────────────────┘└──────────────────┘└─────────────────┘└─────────────────────┘
│         │ ⚠ 3 lines (52.00 USD) wait for review or reconciling and aren't counted.  Open To check →
│         │ ┌By category ─────────────────────────────────┐ ┌Budgets ───────────────────────┐
│         │ │ Category      October  September  Change     │ │ Dining              101.40 left│
│         │ │ Housing      1,650.00   1,650.00  —          │ │ [=====──────────]              │
│         │ │ Groceries      254.75       0.00  ▲ 254.75   │ │ 18.60 of 120.00                │
│         │ │ Utilities       89.50       0.00  ▲ 89.50    │ │ Groceries [⚠ Over budget] Over by 4.75│
│         │ │ Uncategorized   79.41     252.50  ▼ 173.09 (68.6%)│ [===============]           │
│         │ │ …                                            │ │ 254.75 of 250.00 · expected …  │
│         │ │ Sums to 2,158.06 USD  (= Net spending)       │ │ [Change] [Remove]  (row menu)  │
│         │ └──────────────────────────────────────────────┘ │ 1,884.71 in categories without │
│         │                                                  │ a budget · [+ Add a budget]     │
│         │                                                  └────────────────────────────────┘
│         │ ┌Top merchants ───────────────┐ ┌Refunds ───────────────────────┐
│         │ └─────────────────────────────┘ └───────────────────────────────┘
│         │ ▸ Category rules (1)                               (closed <details>, tinted region)
│         │ ▸ What these numbers cover                         (closed <details>)
```
- **Header actions:** `button.icon-button#month2-prev` (chevron-left, aria-label "Previous month"),
  `input[type=month]#month2-month`, `button#month2-next` (chevron-right, "Next month", disabled at the current
  month), `select#month2-compare` (Previous month | Same month last year), `select#month2-currency` (hidden with one
  currency). No primary button in the header (the page has no single decision).
- **Tiles** (`div.month2-tiles`, 4 columns, 2×2 under 1100px, 1 column under 600px; `.figure-tile`):
  1. "Net spending": `figure(net_spending, {size:"lg", signed:false})`; sub "{n} transactions".
  2. "{Previous month name}" or "{Month} {year−1}" (from `monthText`): the comparison period's `net_spending` figure,
     unsigned; sub "{n} transactions". No difference amount: the server has no traced net-spending difference, and
     the browser doesn't subtract. The per-category changes in the table carry the amounts.
  3. "Refunded": `amount(row.refunds, {signed:false})` (plain); sub "{k} credits posted" counted from
     `get_refunds.posted_credits` in the month (a count, not a sum).
  4. "Budgets" (not in family): text "{a} over · {b} ahead of pace · {c} on track" counting rows by `status`
     (omit zero parts); sub "Day {elapsed} of {days}" when current month. No money.
  "From receipts only" moves into tile 1's second sub when `receipts > 0`:
  "Includes {from_receipts} from {n} receipts no charge has replaced yet" (plain amount).
- **Pending line** under the tiles, only when `pending_review` has rows: a `.needs-row.attention` with alert icon,
  what "{amount} across {n} lines isn't counted yet", why "They wait for review or for their statement to be
  reconciled.", action link "Open To check" (`#/review`).
- **Main grid** `div.month2-main`: `grid-template-columns: minmax(0,1.35fr) minmax(0,1fr)`, gap `--space-6`; one
  column under 1100px (By category first, then Budgets). Family: `.no-aside` (one column, no Budgets).
- **By category** (`section.today-region#month2-categories`, h2 "By category"): `div.table-wrap > table.data-table`
  columns Category | {Month} | {Comparison} | Change. Rows from `get_spending_by_category.categories` (this period)
  joined by category with the comparison's categories and `compare_categories.categories` (a lookup by
  `currency|category`, no math). Include categories present in either period, ordered as `compare_categories` returns.
  - Category: `homeLink(categoryLabel(cat), txHref({start,end,category,currency,metric:"categories"}))`; under it, when
    the category has a budget, a compact `meter(budget)` (6px, `.month2-inline-meter`) — no text.
  - {Month}: `figure(spending, {signed:false})` (size inline), right-aligned. {Comparison}: same, from the comparison
    call; "—" muted when absent.
  - Change: neutral text color, `icon("arrow-up"|"arrow-down")` + `amount(change, {signed:false})` + " ({p}%)" when
    `percent_change` isn't null; "—" when `change.minor === 0`. Never green/red.
  - No footer total: the Net spending tile is the total (its breakdown lists the parts).
  - Empty: `emptyState("No counted spending in {month} or {comparison}.")`.
- **Budgets** (`section.today-region#month2-budgets`, `.personal-only`): h2 "Budgets"; one `div.month2-budget` per
  row, exactly Today's markup (`today_v2.js` `todayBudgets` 178-205: head with category link + badge only for
  `ahead_of_pace` / over (`statusBadge("ahead_of_pace","","Over budget")`), right side `figure(remaining)` + " left"
  or "Over by " + `amount(over)` in `--warning`; `meter(row)`; muted "{spent} of {budget}" + " · expected
  {projected figure} by month end" when `recurring_due.minor`). Each row ends with a `menu("Budget actions",
  [Change…, Remove…])` button (icon `more`, aria-label "{Category} budget actions") instead of two buttons.
  - Change… opens the inline form below prefilled; Remove… uses v1's `confirmAction` text, DELETE, reload.
  - Below the rows: muted "{unbudgeted spent} in categories without a budget ({n} transactions)" (plain amount),
    then `button.secondary#month2-budget-add` (`icon("plus")` + "Add a budget"; Build A adds the `plus` icon). It reveals `form#month2-budget-form` (hidden by default): Category (`input list=category-options`), Currency
    (`select` of the currencies in the data, default the page currency — fixes the free-text open-work item), Monthly
    amount (`inputmode="decimal"`), primary "Save budget", text "Cancel". Errors from the PUT show in
    `p#month2-budget-error.field-error[role=alert]` under the form, not a toast. Success: toast, reload.
  - Empty: `emptyState("No budgets yet.", <Add a budget button>)`.
- **Top merchants / Refunds** (`div.month2-pair`, two equal columns, one under 900px): each a `.today-region`.
  Merchants: `ul.dated-list` rows: the server's merchant text unchanged · `amount` · "{n}×" muted;
  top 8, then "Show all 20" toggles the rest (`button.link-button`). Refunds: v1's two sources as `dated-row`s
  (`dateDisplay`, name, `amount(row.amount)` which is `+` green for credits, `statusBadge(settlement)` for receipts).
  Empty: muted "No refunds in {month}."
- **Category rules** (`details.today-region#month2-rules`, `.personal-only`, closed by default; open when the URL has
  `rules=1`, and toggling writes it): summary "Category rules ({n})". Inside: the one-line explanation from v1, a
  `table.data-table` Words | Category (`categoryLabel`) | Account | Transactions (numeric) | row action "Delete"
  (`button.link-button`, v1 confirm text, `danger: true`), then `form#month2-rule-form` inline: Words, Category
  (datalist), Account (`select`, "Any account" + `accountOption`s), secondary "Add rule". Errors inline in
  `p#month2-rule-error.field-error`.
- **What these numbers cover** (`details.today-about#month2-about`, closed): "{k} transfers and card payments
  excluded." then one line per coverage account "{name}: {first} – {last}" or "no data this month"; then
  `spending.notes` as small muted paragraphs. (This is where v1's coverage paragraph goes.)

### Layout at 390
Header wraps: h1, subline, then a row `[‹] [month] [›]` and a row `Compare [select]`. Tiles one column (figure at
`--text-lg`, only the first sub). Pending row. By category (table → stacked: each `tr` is a 2-line grid: category +
this month's figure; second line comparison · change, muted). Budgets. Merchants. Refunds. Rules, About.
At 768: tiles 2×2, main grid one column.

### Changes by file
- `index.html`: `#month2-panel` after `#rules-panel`'s parent `#spending-panel` (line ~564); `<script defer src="month_v2.js">`.
- `month_v2.js` (new): `month2` state; `loadMonthV2(params)`, `reloadMonth()`, `renderMonthV2()`, `month2Tiles`,
  `month2Pending`, `month2Categories`, `month2Budgets`, `month2BudgetForm`, `month2Pair`, `month2Rules`,
  `month2About`; listeners for prev/next/month/compare/currency and the forms.
- `style.css`: new section "This month v2" after "Today v2": `.month2-tiles`, `.month2-main(.no-aside)`,
  `.month2-inline-meter` (`.meter` at 6px, margin-top `--space-1`), `.month2-budget` (reuse `.today-budget` rules via
  a shared selector list rather than copying), `.month2-pair`, `.field-error` (if absent: `--danger` text,
  `--text-sm`, with the alert icon), stacked-table rules under `@media (max-width:600px)` for `#month2-categories`.
- `shell.js`: nav label (Shared).
- `ui.js`: icons `plus`, `chevron-left`, `arrow-up`, `arrow-down`.
- `tests/test_ui_parity.py`: add `("spending", "spending")` to `MIGRATED`; `NEW_ON_V2["spending"] =
  ("budget.remaining", "budget.projected")` plus `spending.net` and `spending.category` **only if** the comparison
  period's values aren't on v1's screen (v1 shows previous-month category values, so they should pass).
- `ui_shots.py`: Seeding (Shared).

### Selector contract (Build A)
v1 ids (`#spend-*`, `#budget-*`, `#rule-*`, `#spending-panel`, `#budget-panel`, `#rules-panel`, `#category-options`)
are untouched; `test_browser.py:324-333` and `assistant.js:47` (`$("spend-month")`) keep working with the flag off.
**assistant.js:47** reads `$("spend-month").value` for context: change it to read
`(uiV2Screens.includes("spending") ? $("month2-month") : $("spend-month")).value`. New ids are `#month2-*` only.
`#category-options` (the shared datalist) is reused, not duplicated.

### States
Loading/error/no library via `pageState`. No spending: tiles show 0.00 figures, By category empty state. Current month:
"Day N of M"; past month: no pace text, Next enabled. Multi-currency: currency select; figures never combined.
Long merchant names wrap. Family: no Budgets column/tile, no rules, owner on refund rows; tiles are family totals from
`ledgerTool` (whatever v1 shows). Dark theme: tokens only.

### Accessibility
Order: h1 → prev/month/next → compare → currency → tiles (figure buttons) → pending link → category links/figures →
budget rows (link, figure, menu) → Add a budget → merchants → refunds → rules summary → about. Prev/next have
aria-labels; the meter keeps `role=img` + label. Change arrows carry visually-hidden "more"/"less" text. Form errors
`role=alert` and `aria-describedby` on the field. Reduced motion: nothing animates.

### Verification (Build A)
- `$env:RUN_BROWSER_TESTS = "1"; .venv/Scripts/python.exe -m pytest tests/test_spending_v2_browser.py tests/test_ui_parity.py tests/test_browser.py -q`
- New `tests/test_spending_v2_browser.py`: tiles show traced figures that open `#breakdown`; prev/next change the URL's
  `month`; compare `last_year` relabels tile 2; a budget over shows "Over budget" amber (`data-tone="warning"`), never
  `danger`; Add a budget saves and shows; a bad amount shows `#month2-budget-error` (no toast); rules details opens
  with `rules=1`, add + delete a rule; family profile has no `#month2-budgets`; no overflow at 390/768/1440.
- `tests/test_traces.py -q` (unchanged, sanity).
- `ui_shots.py --routes spending --v2 spending --full-page --out <scratch>/after-spending`; compare with before.

---

## Build B — Transactions (+ Add, Import) (`#/transactions`, `money_v2.js`, `transactions_v2.js`)

### Backend
None. Add uses `POST /api/finance/transactions` (`api.py:1389`; body `account_id, date, description, amount,
direction, category?`). Import uses `GET /api/documents?status=ready_for_ledger` (filter `relative_path` ending
`.csv`/`.xlsx` in the browser — a filter, not math) and library.js `openImport(doc)` (needs `id`, `relative_path`,
`current_hash` from that list).

### `finance.js` refactor (small, keeps v1 behaviour)
- `openTransaction(id, member = null, {onChange} = {})`: replace the hard-coded `loadTransactions()` reloads
  (lines 337, 354, 369) with `(onChange || loadTransactions)()`; pass `onChange` through the internal recursive calls.
  Callers in search.js:58 and taxes.js:625 stay as they are.
- `chargeCategorySelect(row, onDone = loadTransactions)`; same for the `itemCategorySelect(..., () => loadTransactions())`
  callback the v2 rows pass their own reload into.
- `openFamilyTransaction` likewise takes `onChange`.

### `money_v2.js` (new; shared by B and D)
- `addTransactionDialog({accounts, onSaved})`: one `<dialog id="money2-add" class="dialog">` in `index.html` (after
  `#import-dialog`), built like the import dialog. h2 "Add a payment". Fields (`form#money2-add-form`, labels
  visible): Account (`select#money2-add-account`, own accounts only), Date (`input type=date#money2-add-date`, default
  today), Description (`#money2-add-description`, maxlength 200), Amount (`#money2-add-amount`, `inputmode=decimal`,
  placeholder "0.00", the account's currency shown as a suffix text), Direction (`fieldset` radios "Money out"
  (default) / "Money in"), Category (`#money2-add-category`, `list=category-options`, optional). Footer: text
  "Cancel", primary "Add payment". Explanation under the title, muted: "Counts at once. When its statement line
  arrives, the line replaces it."
  - Errors: 400/422 messages show in `p.field-error` under the field the error names (FastAPI `loc` last element →
    field id; otherwise `#money2-add-error` at the top of the form). Never a toast.
  - Success: close, `notice("Added {description}.")`, `onSaved(record)`.
- `importPicker({onImported})`: `<dialog id="money2-import" class="dialog">`: h2 "Import a bank or card export",
  muted "Files arrive through the Inbox or a watched folder. Choose one to import." List (`ul.dated-list
  #money2-import-list`) of ready CSV/XLSX docs: file name, folder muted, `dateDisplay` added; each row a secondary
  "Import" button that closes the picker and calls `openImport(doc)`. After `#confirm-import` succeeds, library.js
  already toasts; add a one-line hook: `openImport(doc, {onDone})` in library.js calling `onDone` after the import
  resolves (default none). Empty: `emptyState("No bank or card exports waiting. Put a CSV or XLSX export in the Inbox
  folder.", homeLink("Open Inbox", "#/documents?folder=inbox"))` — check the real Inbox route in shell.js.

### Layout at 1440×900
```
Transactions                                                     [⇪ Import]  [+ Add a payment]
Every payment and item, with its category and whether a statement and a receipt agree.
[Search description, merchant or item_______________]  [Items | Charges]
(This month) (Last month) (90 days●) (This year) (All) (Custom…)   Account [All ▾]  Category [All ▾]  [More filters ▾]
16 items · Jul 13 – Oct 10, 2026 · Clear filters
┌───────┬──────────────────────────────┬───────────────┬───────────────┬──────────────┬────────────┐
│ Date  │ Item                         │ Account       │ Category      │ Status       │       Paid │
│ Oct 8 │ Eggs                         │ Receipt       │ [Groceries ▾] │ ▣ Receipt only│  18.72 USD │
│       │ Fresh Market · price 18.00   │               │               │              │            │
│ Oct 4 │ Fresh Market                 │ Everyday card │ [Groceries ▾] │ ✓ Reconciled │  98.75 USD │
│ Oct 2 │ Transfer to savings ⇄        │ Household chk │ —             │ Not spending │ −500.00 USD│ (muted)
└───────┴──────────────────────────────┴───────────────┴───────────────┴──────────────┴────────────┘
                                                         ‹ Previous   1–16 of 16   Next ›
```
- **Header actions:** secondary `button#tx2-import` (`icon("upload")` + "Import"), primary `button#tx2-add`
  (`icon("plus")` + "Add a payment"). Both `.personal-only`. Header's one primary is Add.
- **Row 1:** `input type=search#tx2-search` (flex 1, max 480px) and the view as a 2-button segmented tablist
  `div.tabs#tx2-view` (`role=tablist`, buttons `#tx2-view-items`, `#tx2-view-charges`, `aria-selected`) — not a select.
- **Row 2:** period chips `div.chip-list#tx2-periods` (`button.chip[aria-pressed]`, values `this_month`, `last_month`,
  `last_90` (default), `year`, `all`, `custom`); Custom reveals `#tx2-from` / `#tx2-to` date inputs inline. Account
  `select#tx2-account`, Category `select#tx2-category` (same options as v1 `loadTransactionOptions`). "More filters"
  is a `details#tx2-more` holding Type, Status, Receipt, Sort (`#tx2-type`, `#tx2-status`, `#tx2-receipt`,
  `#tx2-sort`; options copied from v1 index.html 496-526); they apply to Charges only and are disabled with the hint
  "Charges view only" in Items. Chips wrap (`flex-wrap`).
- **Summary** `p#tx2-summary` (muted): count · `describeFilters(args)` · "Clear filters" link when filters are set.
  `#tx2-backfill` (v1's item-backfill offer) as a `.needs-row` (info, not attention) above the table when present.
- **Table** `div.table-wrap > table.data-table#tx2-table`, sticky header. Items columns: Date | (Owner) | Item |
  Account | Category | Status | Paid. Charges columns: Date | (Owner) | Description | Account | Category | Receipt |
  Status | Amount. Cells as v1 `itemRow`/`transactionRow` (finance.js 157-272), with these changes:
  - Names: shown as the server sends them (no case changes). The secondary line stays muted small.
  - Account: `account` text. (The "Household checking checking" duplication is server display text — leave it, list
    in open work.)
  - Amount: Items `amount(row.amount, {signed:false})`; Charges `amount(row.amount)` (signed: `−` out, `+` green in);
    transfers/payments muted with `icon("transfer")` before the description.
  - Row click opens the drawer: `openTransaction(id, member, {onChange: reloadTx2})`.
  - Selected row (drawer open) gets `aria-selected=true` styled `--accent-subtle`.
- **Pager** `div.pager`: `#tx2-prev`, `#tx2-page`, `#tx2-next` (same 200-row server offset; `offset` in URL).
- **URL params:** same keys as v1 `TX_FIELDS` + `period`, `offset`, `currency`, `metric`, `categories`, so every
  existing deep link (`txHref`, home.js `financeHref`, search.js, assistant.js) works unchanged on v2.
- **After Add:** reload, then scroll the new row into view and give it `.tx2-new` (an `--accent-subtle` background for
  the session; no animation). After Import: reload with the current filters; library.js already toasts the result.

### Layout at 390 (stacked rows, decided)
Header: h1, subline, then `[Import] [+ Add a payment]` full-width pair. Search full width; view tabs; chips wrap; then
Account and Category selects each full width; More filters. Table `thead` hidden visually (kept for screen readers);
each `tr` is `display:grid; grid-template-columns: 56px 1fr auto` with: row 1 date | name | amount, row 2 — | account ·
status badge | —, row 3 — | category select full width (spanning 2 columns). Owner joins row 2. 1px divider between
rows, 12px padding. No horizontal scroll. Breakpoint: `@media (max-width:700px)` for `#tx2-table`.
At 768: the table (desktop layout) in `.table-wrap`, Account column hidden (`.tx2-col-account` hidden under 900px;
the account shows in the name's secondary line instead).

### Changes by file
- `index.html`: `#tx2-panel` after `#transactions-panel`; dialogs `#money2-add` and `#money2-import` after
  `#import-dialog`; scripts `money_v2.js`, `transactions_v2.js`.
- `transactions_v2.js` (new): `tx2` state; `loadTransactionsV2(params)`, `tx2Changed()`, `tx2Query()` (reuse v1's
  `transactionQuery`/`itemQuery` logic by passing values, not by reading v1 ids — copy the arg-building into a
  function that takes a plain object), `renderTx2()`, `tx2ItemRow`, `tx2ChargeRow`, `reloadTx2()`.
- `money_v2.js` (new): `addTransactionDialog`, `importPicker`, `fieldError(form, field, message)`.
- `finance.js`: the refactor above.
- `library.js`: `openImport(doc, {onDone} = {})`.
- `style.css`: section "Transactions v2": `.tx2-toolbar` rows (flex, wrap, gap `--space-2`), `.chip-list`,
  `#tx2-table` stacked rules, `.tx2-col-account`, `.tx2-new`, `tr[aria-selected=true]`; dialog form layout for
  `#money2-add` (2-column grid at ≥600px: Account+Date, Description full, Amount+Direction, Category full).
### Selector contract (Build B)
v1 keeps every id in finance.js "Transactions" (`#tx-*`, `#item-rows`, `#charge-table`, `#item-table`,
`#item-backfill`, `#transactions-title`) and the drawer (`#tx-drawer`, `#tx-drawer-body`, `#tx-drawer-title`,
`#close-tx-drawer`, created `#tx-drawer-category`, `#tx-drawer-always`, `#tx-drawer-words`, `#family-fix-*`).
The drawer is **shared** and unchanged, so test_browser.py:317-323, test_family_browser.py:121-136 and
test_taxes_browser.py:234-245 keep working. `#import-dialog` and its ids (test_browser.py:297-303) are unchanged; v2
only opens it. New ids: `#tx2-*`, `#money2-add*`, `#money2-import*`.

### States
Loading/error via `pageState`; table load errors after first render show `alertBox` with Retry above the table (as
v1's message row, but styled). No transactions: `emptyState("No transactions yet.", [Import button, Add button])`
(personal) or v1's text (family). Filters match nothing: "No transactions match these filters." + Clear filters.
Long descriptions wrap. 200+ rows: pager. Family: Owner column, no Add/Import, drawer is `openFamilyTransaction`.
Pending/waiting rows keep v1's "Waiting for {owner}" small text.

### Accessibility
Order: h1 → Import → Add → search → view tabs (arrow keys via `wireTabs`) → chips (each a toggle button with
`aria-pressed`) → custom dates → account → category → More filters → summary link → rows (name button, category
select, receipt link) → pager. Dialogs: focus the first field on open, Esc closes, focus returns to the opener.
Status is icon + text. Stacked rows keep the table semantics (only `display` changes; `thead` gets
`.visually-hidden`).

### Verification (Build B)
- `$env:RUN_BROWSER_TESTS = "1"; .venv/Scripts/python.exe -m pytest tests/test_transactions_v2_browser.py tests/test_browser.py tests/test_family_browser.py tests/test_taxes_browser.py -q`
- New `tests/test_transactions_v2_browser.py`: chips change `period` in the URL and the summary; Items ↔ Charges tabs;
  a Home-style deep link (`#/transactions?category=groceries&metric=categories&start=…&end=…`) filters on v2;
  changing a row's category reloads v2's table (not v1's); the drawer opens and its Save category reloads v2; Add a
  payment with a missing amount shows the field error, a valid one appears in the list with "Entered"/Verified
  status; Import lists the seeded CSV, opens `#import-dialog`, imports, and the rows appear; at 390 no overflow and the
  first row's name is on one line at least 120px wide (stacked rows); family profile: owner column, no `#tx2-add`.
- No `MIGRATED` pair (Transactions shows record amounts, no traced figures — like To check). Say so in docs/ui.md
  "Migration".
- `ui_shots.py --routes transactions --v2 transactions --full-page --out <scratch>/after-transactions`.

---

## Build C — Bills & subscriptions (`#/bills`, `bills_v2.js`)

### Backend (additive, one line)
`finance/tools.py` `get_recurring_obligations` (line 792): make `expected_amount` a figure:
`figure(row["expected_amount_minor"], row["currency"], ref("bill.expected", obligation_id=row["id"]))`.
Add a case to `tests/test_traces.py` (pattern `same(trace(store, shown["trace"]), shown)`) for a confirmed and a
proposed obligation. If `bill.expected` doesn't reconcile for a proposed row, leave proposed rows plain and note it.

### Data
`ledgerTool("get_upcoming_bills", {as_of: todayIso(), days: 120})`, `ledgerTool("get_recurring_obligations")`.
URL params: `show` (`all` default | `bills` | `subscriptions`).

### Layout at 1440×900
```
Bills & subscriptions                                              [Look for recurring bills]
What's due, what it usually costs, and whether a payment was found.
┌Bills a month────────┐┌Subscriptions a month┐┌Subscriptions a year─┐
│ 1,650.00 USD        ││ 15.99 USD           ││ 191.88 USD          │
│ 1 bill              ││ 1 subscription      ││ What If can cancel… │
└─────────────────────┘└─────────────────────┘└─────────────────────┘
┌To decide (1) ───────────────────────────────────────────────────────────┐   (only when proposed exist)
│ ⚠ Harbor Insurance · about 100.00 USD a month · proposed from 3 payments │
│   Counts as [Bill ▾]   Every [month ▾]        [Confirm]  Not recurring   │
└─────────────────────────────────────────────────────────────────────────┘
┌Coming up ───────────────────────────────┐ ┌All recurring payments ──── (All|Bills|Subscriptions) ┐
│ OVERDUE · no payment found              │ │ Maple Street Rentals  1,650.00  month  Bill ▾  ✓  ⋯ │
│ NEXT 7 DAYS                             │ │ Streaming Plus           15.99  month  Subs ▾  ✓  ⋯ │
│ LATER                                   │ │                                                     │
│ Nov 1  Maple Street Rentals  1,650.00 Due│ │                                                     │
│        Monthly · last paid Oct 1        │ │                                                     │
└─────────────────────────────────────────┘ └─────────────────────────────────────────────────────┘
```
- **Header action:** secondary `button#bills2-scan` "Look for recurring bills" (`.personal-only`; disabled while
  `busy.inference`, same as v1 `#recurring-scan` in app.js:77 — add `bills2-scan` to that toggle). No primary in the
  header; the primary is Confirm in To decide.
- **Tiles** (`div.bills2-tiles`, 3 columns, 1 under 700px): from `recurring.totals` — "Bills a month" =
  `figure(total.monthly)` for `kind=bill`, "Subscriptions a month" / "a year" for `kind=subscription`
  (`recurring.total` traces). One tile set per currency (stacked) — never combined. Sub: "{count} bills" etc.; the
  year tile's sub: "What If can show your plan with them cancelled." linking `#/whatif`. Tiles with no rows are
  omitted; with no confirmed payments at all, no tiles.
- **To decide** (`section.today-region#bills2-decide`, `.personal-only`, only when proposed rows exist; h2 "To decide"
  + `.nav-count.attention`): one `.needs-row.attention` per proposed obligation: what "{merchant}", meta "about
  {expected figure} {FREQUENCY_LABELS}", why from its source if the row says so (else none); controls on the right:
  `kindSelect` (aria-label "{merchant} counts as"), primary `Confirm` (POST review `verified` with the row's
  `kind`), text-link "Not recurring" (POST `rejected`). One primary per row region. Confirm keeps v1's behaviour.
- **Main grid** `div.bills2-main` (`minmax(0,1fr) minmax(0,1.2fr)`, one column under 1100px):
  - **Coming up** (`section.today-region#bills2-upcoming`): v1's three groups as kicker headings (uppercase
    `--text-xs` muted; Overdue's kicker in `--danger` text with the alert icon — past due is red by MASTER), each a
    `ul.dated-list` of `dated-row`s: `dateDisplay(due_date)` | provider (+ " · {owner}") with muted
    "{frequency} · last paid {date}" | `figure(amount_due, {signed:false})` | `statusBadge(payment_state)`.
    Subscriptions show `statusBadge`-free "Subscription" muted tag after the name. Empty: `emptyState("Nothing
    confirmed is due in the next 120 days.")`. The v1 explanatory note moves into a closed
    `details.today-about#bills2-about` at the page bottom.
  - **All recurring payments** (`section.today-region#bills2-all`): segmented `div.tabs#bills2-show` (All | Bills |
    Subscriptions, writes `show`). `table.data-table`: Merchant | (Owner) | Expected (`figure`, right) | Every |
    Next | Counts as (`kindSelect`, aria-label "{merchant} counts as"; text in family) | Status (`statusBadge`) |
    actions: for verified a `menu("{merchant} actions", ["Mark as ended…"])` with v1's confirm text; ended/rejected
    rows muted at the bottom. Proposed rows are listed here too (status Proposed) without actions (they're in To
    decide).
- **About** (closed details): v1's "Confirmed recurring payments only…" and "Proposed from a steady cadence…" texts.

### Layout at 390
Header, scan button full width. Tiles one column. To decide rows stack: what/meta, then kind select full width, then
`[Confirm]` full width + "Not recurring" link. Coming up. All recurring: table stacked as in Build B (row 1 merchant |
expected, row 2 every · next · status, row 3 kind select + menu). At 768: tiles 3 columns, main one column.

### Changes by file
- `index.html`: `#bills2-panel` after `#bills-panel`; `<script defer src="bills_v2.js">`.
- `bills_v2.js` (new): `bills2` state; `loadBillsV2`, `renderBillsV2`, `bills2Tiles`, `bills2Decide`,
  `bills2Upcoming`, `bills2All`, `bills2About`; decide/setKind/end call the v1 endpoints and reload v2, and call
  `refreshReviewCount()`.
- `app.js:77`: also toggle `$("bills2-scan")` when present.
- `finance/tools.py`: the figure (Backend).
- `style.css`: section "Bills v2": `.bills2-tiles`, `.bills2-main`, `.bills2-kicker(.overdue)`, To-decide row
  controls layout, stacked table rules for `#bills2-all` under 700px.
- `tests/test_traces.py`: the case above.
- `tests/test_ui_parity.py`: `("bills", "bills")` in `MIGRATED`; `NEW_ON_V2["bills"] = ()` unless the year tile's
  figure isn't on v1 (v1 shows yearly in a sentence — `v1_amounts` reads text, so it should pass). The parity seed has
  no confirmed bill: extend `seeded_server` with one (three monthly payments + `review_obligation`) if needed.

### Selector contract (Build C)
v1 `#bills-panel`, `#bills-state`, `#bills-title`, `#bill-groups`, `#subscription-summary`, `#recurring-rows`,
`#recurring-scan` untouched (test_recurring_bills.py:317-389, test_browser.py:363). The accessible name
"{merchant} counts as" is kept on v2's kind selects. New ids `#bills2-*`.

### States
Loading/error/Retry via `pageState` (mirror test_recurring_bills.py:368-389's checks on v2). Nothing at all:
`emptyState("No recurring payments yet. They're found from receipts, statements and contracts.", scan button)`.
Only proposed: no tiles, To decide + All. Multi-currency tiles per currency. Family: no To decide, no scan, kind as
text, owner column; tiles from family data if `ledgerTool` returns totals (else omit tiles in family).

### Accessibility
Order: h1 → scan → tiles → To decide (kind, Confirm, Not recurring per row) → Coming up → All (tabs, rows: kind, menu)
→ About. Overdue = icon + "Overdue · no payment found" text. Confirm buttons' accessible names include the merchant
(`aria-label "Confirm {merchant}"`).

### Verification (Build C)
- `$env:RUN_BROWSER_TESTS = "1"; .venv/Scripts/python.exe -m pytest tests/test_bills_v2_browser.py tests/test_recurring_bills.py tests/test_ui_parity.py tests/test_traces.py -q`
- New `tests/test_bills_v2_browser.py` (seed like test_recurring_bills.py): tiles' figures open breakdowns and match
  `recurring.total`; Confirm a proposed payment moves it out of To decide and into the tiles; Not recurring removes
  it; kind change Bill↔Subscription moves the total between tiles; Mark as ended asks first; loading/error/Retry like
  test_recurring_bills.py:368-389; `show=subscriptions` filters; no overflow at 390/768/1440; the first Confirm is in
  view at 1366×768 (decision in view).
- `ui_shots.py --routes bills --v2 bills --full-page --out <scratch>/after-bills`.

---

## Build D — Accounts (+ Import) (`#/accounts`, `accounts_v2.js`)

### Backend
None. `get_accounts` already gives `balance` as an `account.balance` figure with `as_of`, `days_old`, `meaning`.

### Layout at 1440×900
```
Accounts                                                                       [⇪ Import an export]
Each account's latest statement balance and how recent it is. Cash and net worth across accounts are on Today.
┌Cash ───────────────────────────────────────────────────────────────────────────────────────┐
│ First Local Bank checking 4821   Statement balance   1,430.00 USD   as of Sep 30, 2026      │
│ First Local Bank ··4821 · USD    No counted transactions yet                 Transactions › │
│ ─────────────────────────────────────────────────────────────────────────────────────────── │
│ Savings                          No statement yet                                          │
│ Savings · USD                    1 counted transaction · Jan 5, 2026         Transactions › │
└────────────────────────────────────────────────────────────────────────────────────────────┘
┌Credit cards ───────────────────────────────────────────────────────────────────────────────┐
│ Everyday card                    Amount owed  312.45 USD  as of Aug 11 [⚠ Over 35 days old] │
│ Everyday card · USD              3 counted transactions · Oct 2 – Oct 4      Transactions › │
└────────────────────────────────────────────────────────────────────────────────────────────┘
```
- **Header action:** primary `button#accounts2-import` (`icon("upload")` + "Import an export", `.personal-only`) →
  `importPicker({onImported: reloadAccounts})` from `money_v2.js`.
- **Groups:** v1's `ACCOUNT_GROUPS` (finance.js:710), each a `section.today-region` with h2 and a `ul.accounts2-list`
  of `li.accounts2-row` (grid `minmax(0,1.2fr) minmax(0,1fr) auto`, 1px dividers):
  - col 1: `strong` display name; muted small "{owner · }{institution}{ ··last4} · {currency}".
  - col 2: label ("Statement balance" / "Amount owed" from `balance.meaning`) + `figure(balance, {signed:false})` +
    muted "as of {dateText}"; when `days_old > 35`: `statusBadge("needs_review", "", "Over 35 days old")`. No balance:
    muted "No statement yet" (the long v1 sentence moves to the About details).
  - second line, col 2: muted coverage "{n} counted transactions · {first} – {last}" or "No counted transactions yet".
  - col 3: `homeLink("Transactions", txHref({account, period:"all"}))` with `icon("chevron-right")`.
- **About** (closed `details.today-about#accounts2-about`): "Balances come from statements and show their dates. They
  aren't added up here; Today shows Cash and Net worth." + "Balances aren't estimated from partial transaction
  history." + v1's import hint.

### Layout at 390
Header, Import full width. Each row stacks: name / institution; label + figure; as-of + badge; coverage; link. At 768:
the 3-column row grid holds.

### Changes by file
- `index.html`: `#accounts2-panel` after `#accounts-panel`; `<script defer src="accounts_v2.js">`.
- `accounts_v2.js` (new): `loadAccountsV2`, `renderAccountsV2`, `accounts2Row`, `reloadAccounts`.
- `style.css`: section "Accounts v2": `.accounts2-list`, `.accounts2-row` grid + 600px stacking.
- `tests/test_ui_parity.py`: `("accounts", "accounts")` in `MIGRATED` (the parity seed has statement balances via
  `seed_today`-like data; extend `seeded_server` with one statement balance if it has none).

### Selector contract (Build D)
v1 `#accounts-panel`, `#accounts-state`, `#account-groups`, `#nav-accounts` untouched (test_browser.py:56-59, 305-306).
New ids `#accounts2-*`.

### States
Loading/error/no library ("Set up your library to see accounts." + Open Settings, same as v1 through `pageState`).
No accounts: `emptyState("No accounts yet.", Import button)`. Family: owner prefix, no Import, account link uses
`member_id:id`. Long names wrap.

### Accessibility
Order: h1 → Import → each group's rows (figure button, Transactions link). The stale state is icon + text. Links say
"Transactions for {name}" via `aria-label`.

### Verification (Build D)
- `$env:RUN_BROWSER_TESTS = "1"; .venv/Scripts/python.exe -m pytest tests/test_accounts_v2_browser.py tests/test_browser.py tests/test_ui_parity.py -q`
- New `tests/test_accounts_v2_browser.py`: balances are traced figures that open `#breakdown`; a 40-day-old statement
  shows "Over 35 days old"; Import → picker → `#import-dialog` → imported rows reach the account's coverage; no
  library state; family profile has no `#accounts2-import`; no overflow at 390/768/1440.
- `ui_shots.py --routes accounts --v2 accounts --full-page --out <scratch>/after-accounts`.

---

## Out of scope (all builds)
- The global `#reconcile-prompt` above every page (shell; its own session).
- The transaction drawer's design (shared by v1, Search and Taxes) — it inherits tokens only. Turning it into
  `confirmCorrect` for transactions goes to docs/open-work.md "UI redesign".
- Deleting v1 loaders and CSS (item 8). Receipts & statements (`#/receipts`) — a Records screen.
- Server display text such as "Household checking checking" and upper-case merchant names: list in open work, don't
  change the server.
- Browser file upload (decided: Import picks a library file).
- Any other page, the backend beyond the one `expected_amount` figure, and copy not listed here.

## Verification (every build, besides its own list)
- Run only the files listed for the build (memory: targeted test runs).
- After screenshots vs before at 390/768/1440 light and dark; the script must print no `HORIZONTAL OVERFLOW` and no
  page errors.
- docs/ui.md "Verifying a layout": scrollWidth check at 390/768/1440 in the build's test; Bills adds the 1366×768
  in-view assertion for the first Confirm.
- Tab through the page: visible focus ring, order as in its Accessibility list.
- No hex outside `:root` (Grep `#[0-9a-fA-F]{3,6}` in the new CSS section) and no inline `style=` in markup.

## Docs to update
Each build, in the same change:
- docs/ui.md "Pages": a bullet for the screen ("This month v2 (`month_v2.js`, behind `ui_v2_screens`; design in
  `design-system/home-manager/pages/money.md`) …"), and correct the Family view bullet (FAMILY_ROUTES really includes
  transactions, spending, bills, accounts).
- docs/ui.md "Migration": the registered list; Transactions has no `MIGRATED` pair and why.
- docs/money.md "Money pages": the v2 description; "Manual transactions": replace "There's no form for it yet" with
  the Add a payment dialog (Build B).
- docs/open-work.md "UI redesign": record each build as done (as the earlier screens are), and add: the drawer as
  `confirmCorrect`; account display names doubling the type; untraced numbers left plain (category change, top
  merchants, refunds, the previous-period net-spending difference). Remove "Budget and asset currencies are free
  text" for budgets once Build A ships (the currency is a select).
- `design-system/home-manager/pages/money.md`: written in Build A, each later build fills in its screen's section if
  anything changed while building.
- Memory: update `observability-redesign-plan.md`'s line in MEMORY.md as each build lands.
