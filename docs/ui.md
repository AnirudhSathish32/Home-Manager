# UI

The web UI (`src/home_manager/app/static`) is plain JavaScript with hash routes, no framework and no build step. The
rules to apply on every UI change are under "Screen rules" below. Visual direction comes from the `ui-ux-pro-max`
skill (`.claude/skills/ui-ux-pro-max/`). Where they conflict, the screen rules win. This document also records the
pages, the design system, accessibility and money display.

## Screen rules

### Layout

1. **Decision in view.** A screen that asks the user to decide (To check, reconcile prompts, confirmations) shows
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

- **Tokens only.** Use the `:root` block in `style.css` and add no new hex values. Changing a token's value happens in
  that block.
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
- **Keyboard.** Every control is reachable in visual order. To check keeps J/K, V and R, and shortcuts never fire inside
  inputs. The focus ring is visible.
- **Links read from documents** are shown as text, never as live links.
- **Charts** each have a text summary and a **View data table** control. Colors come from the `--chart-*` tokens:
  categorical slots `--chart-cat-1..6` (`home.js` `categorySlot()` gives a category its `cat-N` class), the
  sequential ramp `--chart-seq-1..10`, and the `c-*` classes on the server's SVG (`finance/charts.py`). Series are
  never told apart by hue alone: on a line chart series 2 is dashed (`.c-line-2`) and series 3 dotted (`.c-line-3`),
  legend lines too, and the end labels stay. Each server chart's title and desc ids come from its `key`
  (`line_chart(…, key=)`, `tax_buckets_svg(…, key=)`), so several charts on one page keep unique ids.

### Verifying a layout

- Extend the opt-in browser tests (`tests/test_browser.py` and the screen's `tests/test_*_v2_browser.py`) and run them with
  `.venv/Scripts/python.exe -m pytest tests/test_browser.py --browser`.
- On a decision screen, assert the primary button is in view at 1366×768:
  `box = page.locator("#review-confirm").bounding_box(); assert box and box["y"] + box["height"] <= 768`.
- At 390, 768 and 1440 widths, check `page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")`.
- Use synthetic data only.

## Pages

Routes are listed in `ROUTES` in `shell.js`. Each screen's script registers its title and loader in `V2_SCREENS`
(`route → {title, show}`, declared in `app.js` so a script can register before `shell.js` routes the first page), and
its markup is one `<section data-page="…">` in `index.html`. `showRoute` shows the route's section and calls the
screen's `show`; Settings, Donate and the old `#/finances` links keep their loader in `ROUTES`. `#/documents` and
`#/receipts` share one section (`records_v2.js`, which sets `libraryScope` for the shell and `leaveDocument`, and
`libraryCatalog` for the shared move dialog). The screens' scripts end in `_v2.js`; the scripts without the suffix hold
the builders, dialogs and helpers the screens share (forecast.js, whatif.js, investments.js, inventory.js, review.js,
receipt.js, taxes.js, finance.js, library.js, processing.js, home.js and search.js).

| Route | Page | Doc |
|---|---|---|
| `#/home` | Today (default) | [money](money.md#home) |
| `#/search?q=&kind=` | Search across documents, transactions, items and accounts | [documents](documents.md#searching-document-text) |
| `#/review` | To check: everything that needs a decision | [Review](#review) |
| `#/spending` | This month: spending and budgets | [money](money.md#category-rules-and-budgets) |
| `#/transactions` | Transactions (Items and Charges views) | [money](money.md#money-pages) |
| `#/bills` | Bills & subscriptions | [money](money.md#recurring-bills) |
| `#/accounts` | Accounts | [money](money.md#money-pages) |
| `#/taxes` | Taxes (`?year=&tab=year\|built\|writeoffs\|jobs\|pack\|rules&section=&unit=`) | [taxes](taxes.md) |
| `#/investments` | Investments | [planning](planning.md#investments) |
| `#/forecast` | Forecast | [planning](planning.md#forecast) |
| `#/whatif` | What If | [planning](planning.md#what-if) |
| `#/inventory` | Inventory | [household](household.md#the-inventory-page) |
| `#/receipts` | Receipts & statements (the money store) | [money](money.md#two-stores-one-library) |
| `#/documents`, `#/documents/ID` | Documents and the document page | [documents](documents.md#browsing-the-library) |
| `#/processing` | Processing | [Processing](#processing) |
| `#/settings` | Settings | [Settings](#settings) |
| `#/donate` | Donate documents | [evals](evals.md#donating-documents) |

- **Family view.** In the family view, only Today, To check, Receipts & statements, Documents, the document page,
  Processing, Settings, What If, Taxes and the family ledger's This month, Transactions, Bills and Accounts are offered
  (`FAMILY_ROUTES`).
- **Old links.** `#/finances?…` links redirect to the money pages.
- **Taxes** (`taxes_v2.js`; design in `design-system/home-manager/pages/taxes.md`) has six
  tabs: **This year** (three answer tiles, one "What to do" region with Tax Zen's one action and "Other ways", then the
  return line by line), **Built from** (a section list beside rows of Box · From records · Yours), **Write-offs**,
  **Jobs & pay stubs** (each job's year figures, its W-4 on file and its pay stubs), **CPA pack** and **Rules &
  sources** (tax rules, the year's tax tables, every rule set as a `ruleCard`). Built from and Jobs edit one draft with
  a sticky save bar; a year or return change asks before discarding it. Tabs draw when first shown, and the URL keeps
  the year, tab, section and family return (`history.replaceState`). The family view hides Write-offs, CPA pack and
  Rules & sources, and shows its returns above This year with a Return select.
- **Today** (`today_v2.js`; design in `design-system/home-manager/pages/today.md`) is the home route. Four figure tiles,
  whose figures shrink to fit (Cash with its balances' date range and an "old" flag past 35 days, Net worth, Spent in the month, Money in with net
  cash flow), then **Needs you** (attention rows first, each with one action; rows with a count of 0 are left out)
  with the dated sections under it (Bills, CDs and Treasuries coming due, Weekly check-in, Return windows closing,
  Warranties ending soon, each only when it has rows) beside the month's **budgets** (amber meters, "Over by" or
  "left"), then the spending trend and the category donut (`home.js` `homeTrend`, `homeCategories`), and "What these
  numbers cover" folded. Under 1100px it is one column (Needs you,
  budgets, dated sections) and tiles go 2×2, as they do whenever a side panel leaves the page under 980px; a
  stale or unconfirmed badge drops under its amount when it doesn't fit. The family view drops the budgets, check-in, returns and warranties and
  adds "Each person", the family's net worth and "Counted once". The URL keeps `?month=&currency=&months=`.
- **The document page** (`document_v2.js`; design in `design-system/home-manager/pages/document.md`) puts the source
  beside a record whose sticky header holds the decision, then the tabs Record · History · Details
  ([The document page](#the-document-page)).
- **To check** (`review_v2.js`; design in `design-system/home-manager/pages/review.md`) is three columns: the queue,
  the item's source with its evidence lit, and the item with its decision bar pinned at the bottom of its column
  ([Review](#review)).
- **The Money screens** (design in `design-system/home-manager/pages/money.md`). Category names show through
  `categoryLabel()` on all four.
  - **This month** (`month_v2.js`, the spending route) has month
    stepping (‹ month ›, Next stops at this month), Compare (previous month or the same month last year) and a
    currency select only when the data has more than one. Four tiles: Net spending and the comparison month's (both
    traced), Refunded with its posted credits, and the budgets' states with the day of the month. A needs-attention row
    says what awaits review. Then **By category** (this month, the comparison, and the change as text with an arrow,
    never green or red; a 6px budget meter under budgeted names) beside **Budgets** (Today's rows, each with a Change…
    and Remove… menu, then "Add a budget": an inline form whose currency is a select and whose errors show under it),
    Top merchants (8, then all 20) and Refunds, then **Category rules** and "What these numbers cover" folded. The URL
    keeps `?month=&compare=&currency=&rules=1`. The family view drops budgets and rules.
  - **Transactions** (`transactions_v2.js`) has Import and **Add a payment** in its header (`money_v2.js` dialogs),
    search and an Items | Charges switch, All | Out | In chips (`direction`), period chips (This month, Last month, 90 days,
    This year, All, Custom…), Account and Category, and Type, Status, Receipt and Sort under "More filters" (Charges
    only). An In / Out / Net line (`#tx2-totals`) sits under the summary. Charges also lists the receipts, bills and pay
    stubs that count on their own (`tr[data-source]`, their Receipt / Bill / Pay stub tag in the Account column); their
    name opens the document. Its URL keys (`q, start, end, account, category, types, status, receipt, sort, period, view,
    direction`, and Today's `currency, metric, categories`) are the ones every deep link uses. Under 900px the Account column moves into the name's line; under
    700px each row stacks (date | name | amount, account · status, then the category select). A row opens the
    transaction drawer (`finance.js` `openTransaction(id, member, {onChange})`), which reloads the list after a change.
    A payment just added is marked and scrolled to.
  - **Bills & subscriptions** (`bills_v2.js`) has tiles from `recurring.totals` (Bills a
    month, Subscriptions a month and a year, per currency), **To decide** for proposed payments (kind, Confirm, Not
    recurring), **Coming up** in overdue / next 7 days / later groups, and **All recurring payments** with All | Bills |
    Subscriptions (`?show=`), the kind select and a "Mark as ended…" menu. Expected amounts are `bill.expected` figures.
    Coming up and All sit side by side from 1600px.
  - **Accounts** (`accounts_v2.js`) lists the accounts in groups (Cash, Credit cards, Investments, Loans, Other;
    `finance.js` `ACCOUNT_GROUPS`), each row with its balance as an `account.balance` figure, "as of", an "Over 35 days
    old" badge, coverage and a Transactions link; **Import an export** opens the picker. **Rename** (not in the family
    view) edits the name in place (`PUT /api/finance/accounts/{id}`), and the institution too while the account's
    `institution_clash` is set; a refusal shows under the fields, Escape or Cancel puts the row back, and focus returns
    to Rename. **Delete…** sits beside it (also not in the family view; `aria-label` "Delete {name}…") and opens the
    delete dialog (below).
  - **Waiting for confirm** is a collapsed `<details>` region at the bottom of Accounts (`#accounts2-waiting`,
    `GET /api/finance/accounts/waiting`, hidden when none wait and in the family view). An account a statement made isn't
    in the groups, Today or the pickers until its statement is confirmed ([money](money.md#new-statements-wait-for-you));
    each entry has **Open statement** (its document, where Confirm is) and **Delete…**, so the account can go without being
    confirmed. Its open state survives a reload of the list.
  - **The delete dialog** (`#account-delete-dialog`, `openAccountDelete` in `accounts_v2.js`) is shared by the Accounts
    rows, the Waiting group, the document page and To check. It loads `GET …/accounts/{id}/delete-preview` and shows the
    account's name, a list of the server's counts (statements, transactions and import records always; receipts and pay
    stubs linked to its transactions, transfer and refund links, recurring payments and bills, and category rules only when
    not 0), what stays (linked receipts and pay stubs count on their own again; recurring payments and bills stay with no
    account, each said only when it applies), the family line when the preview has family rows or a copy ("Your family's copy
    has n statements and m transactions of this account; it drops them at your next share. k family records in this library
    about them are deleted too."), "The documents stay in your library; you can record or import them again." and "This can't
    be undone." Focus starts on **Cancel** and returns to the opener when the dialog closes by Cancel or Esc; **Delete
    account** (danger) is the second click and sends the preview's token. A 409 ("This account changed since you opened
    Delete; check the counts again.") shows under the list, loads the preview again and leaves Delete account enabled for the
    new counts; a 404 disables it. A preview that arrives after the dialog was closed and opened again is dropped. After a
    delete the page on screen is drawn again (Accounts, Today, To check; the document page shows its statement as not
    recorded), the To check count is refreshed, a toast says the documents are still in the library, and focus goes to the
    page's heading, because the opener is gone.
  - **Add a payment** posts `POST /api/finance/transactions`; a validation error shows under the field it names
    (`errorField()` reads FastAPI's `loc`). **Import** lists the library's ready CSV and XLSX files and PDFs with a
    transactions table (`/api/finance/import-candidates`, PDFs labelled **PDF**) and opens the
    import dialog (`library.js` `openImport(doc, {onDone})`), which reloads the screen afterwards.
- **Wealth & plans** (design in `design-system/home-manager/pages/wealth.md`).
  - **Investments** (`investments_v2.js`) has tiles (Invested per currency as an `investments.total` figure with its
    oldest value and how many are estimated, Coming due in 90 days, Required distributions), **Needs you** (values in
    To check, the I bond yearly limit, matured CDs with Paid out / Renewed, distributions left this year, unmarked 529
    withdrawals, sales with no purchase lot, and the payroll-account question), every account in one table grouped by
    section (values are `investments.value` figures; a pension shows its monthly income, not counted), then How it
    splits beside Taxes for a year. The URL keeps `?removed=1&year=`. **Add an account** is a dialog whose field errors
    show under their field. An account opens in its own view (`?account=ID&tab=overview|holdings|activity|settings`,
    and `renew=ID` while a matured holding's renewal is added) with Back, the value as a figure, and the tabs Overview ·
    Holdings & lots · Activity · Settings; Record value (not for a pension) goes to Overview's value form. The tabs use
    investments.js's builders, which call `inv2Reload` after a save. Estimated holding values and lot gains are figures.
  - **Forecast** (`forecast_v2.js`) puts the assumptions in a sticky column (340px) beside the results: four scalar
    inputs, then one folded list each for spending changes, income changes, one-offs, education costs and retirement,
    each summary counting its rows, and Update forecast (the header's copy submits the same form). Under 1100px the
    column folds above the results as "Assumptions: 10 years · 2% inflation · 1 change", open only when the URL sets
    nothing. Tiles: Cash and Net worth at the end of the last year (`forecast.cash` / `forecast.net_worth` figures; net
    worth in today's dollars below it), and Cash below zero (amber with the trending-down icon, or "Stays above zero").
    One chart at a time behind a three-chip switch (`?chart=`), its `<desc>` as a summary and View data table, whose
    end cash and net worth cells are figures; then About these numbers, Assets and loans (add form folded), and the
    Starting point (folded). **The assumptions live in the URL**: `years`, `inflation`, `growth`, `history`, and
    repeated `spend=category~percent`, `income=YYYY-MM~amount`, `oneoff=` / `edu=YYYY-MM~amount~label`,
    `retire=YYYY-MM~mode~amount|floor~tax`; invalid values are dropped. forecast.js's builders work on the page's
    `fc2-` inputs and call `fc2Reload` after an asset change.
  - **What If** (`whatif_v2.js`) has the plan select, Duplicate, Delete… and Save plan in the header, then four tabs
    (`?plan=ID|new&tab=plan|compare|planner|follow`; `stub=ID` opens the planner from a pay stub). **Plan** puts the inputs
    (name, start from, three scalars, then folded Paychecks, Set spending, Spending changes, Subscriptions, One-off
    amounts and Retirement, each summary counting its rows or saying On/Off) beside a sticky **Against now** region
    (420px): Try it runs the plan on screen against Now and shows net worth at the end (`forecast.net_worth` figures),
    when cash goes below zero (amber with trending-down, or "Never"), and Tax time (`taxzen.plan` / `tax.result`
    figures, or the server's not-ready note), with a link to the full comparison. The paychecks then show the server's
    take-home per paycheck (`paycheck.net`) instead of the raw salary. **Compare** has the plans as chips (each keeps
    its checkbox), Compare (disabled with "Choose up to three" when none is chosen), the chart with its `<desc>` and View
    data table, Tax Zen per run, and each run's details; end cash and net worth are figures. **Paycheck planner** keeps
    the result sticky beside the form (440px) with the federal and state fields folded; the take-home headline and the
    tax lines are figures. **Follow this plan** (saved plans in a personal profile only) sets the plan's spending as
    budgets and compares pay and spending with it, with plan-vs-actual amounts as `plan.actual` figures. Under 1100px
    Against now and the planner result move above their forms. whatif.js builds the page on its `wi2-` inputs and asks
    whatif_v2.js to open a tab (`wi2ShowTab`), show Against now (`renderAgainstNowV2`), show or hide Follow this plan
    (`wi2FollowChanged`) and link a plan (`wi2Href`).
- **Home & things and System.**
  - **Inventory** (`inventory_v2.js`; design in `design-system/home-manager/pages/inventory.md`) has five tabs
    (`?tab=checkin|items|warranties|returns|insights`, Items by default; `q` and `closed=1` for Items, which `q` always
    opens; `period=30|90|365|year` for insights), each drawn on its first show. Check-in and Returns count what waits
    in their tab's name. The header's one primary action is **+ Warranty** on Warranties (pick an item that lasts, then
    the shared warranty dialog) and **+ Return policy** elsewhere (a dialog; Change in a policy's menu pre-fills it).
    **Items** is one table grouped by category, with To identify above it when receipts wait. **Warranties** lists the
    confirmed ones (those ending within 30 days say so) after a row for any waiting in To check. **Returns** is Did
    this go back? first, then return windows closing in 14 days, then the policies. **Item insights** has four tiles
    (`items.*` figures), Prices that went up beside Costs most, and what was thrown out. inventory.js's builders
    (`renderCheckin`, `lotMenu`, `returnedRow`, the warranty dialog) call `afterInventoryChange`, which runs `it2Reload`
    on this page and `reloadToday` on Today.
  - **Processing** (`processing_v2.js`; design in `design-system/home-manager/pages/system.md`) puts **Read all
    documents** (a small panel with "Also re-read…" and Start reading) and **Scan Inbox** (primary) in the header, then a
    strip: Now running (a polite live region; Cancel names the work) over the five stages in columns, each with its
    state and last run (3 + 2 under 1100px, one row each under 600px). Five tabs follow
    (`?tab=work|health|folders|scans|models`, Recent work by default; `kind` and `status=failed` for Recent work, `task`
    and `status` for Model runs), each drawn on its first show; see [Processing](#processing). While work runs and when
    it finishes, app.js `poll()` calls `pr2Refresh` (the strip and the shown tab) on this page, and `renderActivity`
    redraws the strip on every poll. The Reading stage shows the batch being read (`receiptBatch`, from the settings
    poll).
  - **Settings** (design in `design-system/home-manager/pages/system.md`): `?tab=` in the URL, Independent checks
    editable, and a Donate tab; see [Settings](#settings).
- **Records** (`records_v2.js`; design in `design-system/home-manager/pages/records.md`) is the library for
  `#/documents` and `#/receipts`. A work strip names the store's backlog ("21 not read yet · 2 ready to record · …",
  each count setting the state filter) with the page's only primary, **Read all N** (one batch of up to 500 not-read
  documents; a 409 while model work runs stays in the strip). Then search, the state chips with counts, From/To and
  Sort (under "More filters" below 600px), a "Showing … — Clear filters" line when filtered, and one region with the
  folder tree (a select below 1100px) beside the list. Rows carry their next step as a text link (Read, Record,
  Import, Restore) and the ⋯ menu. A PDF offers Import only once it is recorded: a recorded PDF with a transactions table
  has **Import** as its step when exactly one saved account matches its last four and it isn't recorded as a receipt,
  bill or pay stub (`doc.pdf_import`, from the server; `pdfImportOffer` and `rc2Importing` in `records_v2.js`), else ⋯
  holds **Import transactions** ([documents](documents.md#transaction-imports)); selecting rows shows a sticky bar
  (Read, Combine, Move, Delete, or Restore in Trash).
  Under 820px rows stack (name · amount, folder · date, state · step · ⋯). **Every filter is in the URL**:
  `?folder=&category=&employer=&section=&status=&q=&from=&to=&sort=&offset=`, non-default values only, invalid ones
  dropped. The sidebar's Inbox and Unfiled open `#/documents?folder=…`, and their counts (`library.js`
  `renderNavCounts`, with To check's and the check-in's) refresh on start-up and whenever work finishes. app.js
  `poll()` calls `rc2Refresh`, which redraws only when the documents changed (after an open row menu closes). The
  move, delete, description, versions and import dialogs are library.js's, shared with the document page.
- **Search** (`search_v2.js`; design in `design-system/home-manager/pages/search-ask.md`): the query box with the
  page's only primary, a status line ("14 matches for “fresh”."), then kind chips with counts (All, Documents,
  Transactions, Items, Accounts; a kind with none is disabled). Each kind is a tinted region, "Documents · 9", with a
  divided list: documents open at their matched lines with the snippet (two lines, full text in the title),
  transactions open the transaction drawer, items open Inventory filtered to them, and accounts open their
  transactions. "All" shows six of each and "Show all N" switches to that kind (up to 50, then a link to the kind's own
  page). No results suggests searching Documents' text or Transactions. `?q=&kind=` is in the URL (kind left out when
  it's All). The sidebar box, <kbd>Ctrl</kbd>+<kbd>K</kbd> and <kbd>/</kbd> go to it (`search.js`).
- **Ask.** The Ask panel opens from anywhere as a column beside the page, sharing the breakdown panel's slot
  ([assistant](assistant.md#the-ask-panel)).

### Navigation

The sidebar in `index.html` follows these groups. Every `.nav-link` has an id, `data-route` and icon (the selector
contract). Documents keeps its Inbox and Unfiled sub-links, which carry the counts the user relies on, and To check
carries its count badge (`GET /api/review/counts`). Donate has no sidebar link; it's Settings › Donate, and `#/donate`
still works. The icon rail hides the group labels, and the top-bar menu under 820px shows the same order. In the
family view only the Home & things label hides with Inventory.

```
Search · Today (#/home) · To check (#/review)
Money:          This month (#/spending) · Transactions (+ Add, Import) · Bills & subscriptions · Accounts (+ Import)
Taxes:          tabs This year · Built from · Write-offs · Jobs & pay stubs · CPA pack · Rules & sources
Wealth & plans: Investments · Forecast · What If
Home & things:  Inventory tabs Check-in · Items · Warranties · Returns · Item insights
Records:        Receipts & statements · Documents · the document page
Footer:         Ask · Processing (+ Data health tab) · Settings (+ Donate tab) · Who's here
```

Features that had no page live here: ledger health in Processing › Data health; reviewer settings in Settings ›
Independent checks; the decision-model test in Settings › Local models; tax businesses in Taxes › Built from; tax tags
on the document page and in the transaction drawer; item analysis in Inventory › Item insights; reasoning and
organization runs in the document page's Details.

### Review

`#/review?item=<kind>:<id>` is To check (`review_v2.js`), one queue of everything awaiting a decision. Its data is
`reviewData()` in `review.js`, with its titles (`reviewTitle`), record summaries (`summaryBlock`) and the asset kinds'
evidence (`assetParts`).
- **Keyboard.** <kbd>J</kbd>/<kbd>K</kbd> move, <kbd>V</kbd> confirms and <kbd>R</kbd> rejects, never in inputs,
  dialogs or the open Correct form. Each decision advances to the next item.
- **Groups**, in order (`REVIEW_GROUPS` in `review.js`): Questions, Proposed matches, Records to verify, Investment and
  loan documents to confirm, Warranties to confirm, Tax tables to confirm, Possible write-offs and tax payments,
  Recurring payments, Receipt items to identify.
- **Plain language.** No internal ids or scores in the default view; match signals are in words ("Same amount · 2 days
  apart · merchant matches"). The score and method are in a Details disclosure.
- **When a decision fails,** the item stays selected with an inline error, and the queue doesn't advance.
- **Three columns at 1440:** the queue (260px), the source (`sourceViewer`), and the item (340–400px): its position, an
  h2 for what it is, the *why* (the reason only, never the title again; a record's failed checks as a needs-attention
  row), the evidence, then the decision bar. Each column is sticky and scrolls on its own, so the bar stays in view at
  1366×768. Under 1180px the queue becomes a select with Previous and Next; under 900px it is one column (item, then
  source) and the bar is fixed to the viewport bottom.
- **The queue** adds two groups after `REVIEW_GROUPS`: "Images that look like one document" and "Receipts with no
  matching charge", or "Who is it for?" in the family view (`profiles.js` `routingRow`). Failed and unfiled counts are
  links at its foot.
- **The source by kind:** a record, issue, asset, recurring payment, unmatched receipt or family upload shows its
  document, a record's cited lines lit (`/api/provenance`). A proposed match shows the receipt with a chip for the
  charge's statement; an image group shows its pages as chips; a tax tag its target's document, or a "Bank line" card;
  a receipt item its receipt with the line lit (`line_ids` from `/api/items/resolutions`). Warranties and tax tables
  show a `.source-card` with the quote and the address as text, never a link.
- **The decision:** records, statement values, purchase confirmations and tax forms use `confirmCorrect` (Confirm,
  Reject, Correct…; the form opens in the item's column, a failure shows above the bar). Other kinds have their own
  labels as bar buttons (Confirm match, Not a match, …). Labels keep " (V)" / " (R)". A decided item leaves the queue
  and the next takes its place; Undo brings it back for 8 seconds. An unmatched receipt offers Correct (its purchase
  date) and Open document. A family upload's "For" form is the bar.

### The document page

`#/documents/ID[?version=HASH][&lines=…][&tab=history|details]` (`document_v2.js`) is a full-width view, because
checking evidence side by side needs the width. It is opened over the current page, and Back (or <kbd>Esc</kbd>)
returns to the list with its filters, page and scroll position.
- **The title** is set once, from the best name available, and never changes as data loads.
- **States:** loading, unread (**Read document**), reading (live stage, Cancel), read but not recorded, needs review,
  verified (with Undo), failed (reason plus Retry), cancelled, publication blocked (for example, no currency), and an
  earlier version (with a banner).
- **Import transactions** on a read PDF with a transactions table can be clicked only once the PDF is recorded; until then
  it is a turned-off secondary button beside **Record it**, which stays primary. Once recorded it is the primary button
  when one saved account matches, else secondary. It is offered only on the latest version and never while the page is
  reading or recording; closing the dialog refreshes the page's badge.
- **Correct on an approved statement.** Once you confirm a statement, its fields' and rows' **Correct** buttons hide
  until the record's own **Correct** (in the header) is open, as a receipt's row edits do.
- The page also hosts the split controls for several receipts in one file, the page order of combined images, and
  "Also found" duplicate links ([documents](documents.md)). The decision model's result is an advisory disclosure
  under Checks.
- **The builders** for the record's rows, pay stub, rewards and investment records, its details and its readings'
  telemetry are in `receipt.js`.
- **Layout.** The source (`sourceViewer`) is on the left, sticky and scrolling on its own, at 45:55, or 40:60 from
  900–1179px.
- **Record header.** The record column's sticky header holds:
  - the record's title and status;
  - the steps (Read → Recorded), each with an icon and a hidden state word;
  - the one next action: **Read document**, **Record it** (was "Extract to ledger") or **Try again**;
  - the *why* as a needs-attention row: a count ("3 warnings to check") over one bullet per warning, with
    **Hide / Show** (`aria-expanded`). The count stays when hidden, and this browser remembers the choice for every
    document (`localStorage`);
  - the decision (`confirmCorrect`): **Confirm / Reject / Correct…**.

  The Correct form opens in the header, and the header stops being sticky while the form is open, so Save stays
  reachable. Re-run actions (Read again, Extract again, Copy text) live in the `⋯` menu.
- **Tabs.** Under the header are three tabs:
  - **Record:** field rows, each with a "Changed by" mark when corrected, plus **Find** (the field's cited line) and
    **Correct** (opens the form at that field). Every category shows as a tag. "Counts as" and "Counts in" are traced
    figures. Receipt money fields include Correct even when missing; pay-period ranges offer both ends. Then items
    or transactions (each receipt item and statement row has its own Correct), matched records, rewards, the pay stub,
    taxes and Checks.
    Receipt items show printed Price and, when different, Paid with tax. Correctable Subtotal, Tax, Tip and Total
    rows follow, plus any amount not matched to an item and an arithmetic mismatch message.
    After the fields (`doc2Forms`, [documents](documents.md#receipt-kinds)): a reviewed receipt's waiting details with
    **Apply details**; the **Receipt kind** row with a kind select and **Change kind…** (a preview, then one reading of
    the saved text); "Total · Gift card · Paid" with Paid as a traced figure; **Printed details** (each with Find and,
    for receipts, Correct; tenders, deposit splits, grocery weights and counts); and **Arithmetic checks**, each a figure that opens its
    trace. A receipt with a gift card shows its printed total as Total.
  - **Statements** (`type === "statement"`) add these to the Record tab:
    - **The account note** (`accountNoteBlock` in `trace.js`, from `account_note`): "New account: … — added to Accounts when
      you confirm this statement." with **Delete account**, which opens the same dialog (OD-5). It goes once the account is
      confirmed. To check shows the same note and button under the evidence of a statement item.
    - **The record's notes** (`details.notes`: rows the printed columns didn't have, rows the reading listed that were
      replaced, and the like) in `.doc2-notes` under the fields, as a bill's are.
    - **Find on a row** read from the printed columns asks `GET /api/provenance/transaction/{id}` for the row's own words or
      table cells and lights those with its line (`doc2RowSources`). A row whose amount cell the reading cited keeps its
      own Find.
    - **A deleted account's statement.** `publication.removed` (the record went with its account) reads as "no record": the
      page says nothing is recorded and offers **Record it** again (`doc2Record(true)`), since the document and its reading
      are untouched (FR-13). Recording it again makes a new account that waits for Confirm.
  - **History:** `historyList` with the record's changes, then the readings.
  - **Details:** where the file is, versions and how the text was read.
- **Under 900px.** It's one column (header, source, tabs), and the decision pins to the bottom of the screen.
- **Esc** closes the Correct form or the breakdown first, then goes back to the list.
- **What it doesn't decide.** An earlier version or a document in Trash shows its record without a decision.
  Investment values, purchases and tax forms are confirmed or rejected here but not corrected (Wealth screens).

### Processing

`processing_v2.js` draws the page; `processing.js` keeps `JOB_KINDS`, `LANES`, `duration` and `whenText`, and
Settings' connection tests and backups.
- **Pipeline lanes:** Capture, Reading, Recording, Item identification and Reconciliation (`LANES` in `processing.js`),
  each with its live state and last run. Cancel is offered only where supported (inference); capture can't be
  interrupted. Reconciliation runs as part of imports and extraction; there is no separate action for it.
- **Actions:** **Scan Inbox**, **Read all documents**, and **Watched folders**.
- **Jobs.** One job history across every kind of work (`GET /api/jobs[?kind=…]`), with a kind filter and links to
  documents. The last reconciliation is shown with its counts (`GET /api/finance/reconciliation-runs`). Every kind the
  filter offers (`JOB_KINDS`) is one `storage.py` `JOB_HISTORY` knows; a test reads the list from the JS.
- **Scans.** Each scan's files with their result, paged.
- **Model runs.** Telemetry filtered by task and status, with `~` marking estimates.
- **Data health.** `GET /api/finance/health` ([operations](operations.md)) as one needs-row per broken rule:
  what the rule says, how many records and the severity (errors in the danger tone, warnings amber, notes neutral, each
  with an icon), and **Open** when the rule has one record with a page. Otherwise a disclosure lists up to 20 records,
  each a link (`#/documents/ID` or `#/investments?account=ID`, from the problem's `link`) or "(no page to open)" for
  rows named by their table, then "and N more (run `home-manager check-ledger` for all)". The rule's code is in
  Technical details. A summary line counts each severity ("✓ No problems found" when none), and **Tax engines** lists
  each engine with Ready or Not ready and its note. The tab's name counts errors and warnings ("Data health, 2
  problems"); a failed check shows its error in the tab only and no count.

### Settings

Settings is a page with tabs: **Library folder**, **Profiles & family**, **Financial preferences**, **Appearance**,
**Local models**, **Independent checks**, **Backup & restore**, **Sharing**, **Privacy & security**, **Donate** (design in
`design-system/home-manager/pages/system.md`). Its loader stays in `ROUTES` (`shell.js` `showSettingsTab`), and its
forms are bound by fixed ids in `app.js`, `profiles.js` and `processing.js`.
- **URL.** `#/settings?tab=library|profiles|preferences|appearance|models|checks|backup|sharing|privacy|donate`; Library
  folder is the default and leaves the URL bare. Changing tabs rewrites `?tab=` with `history.replaceState`, so reload
  keeps the tab. The collapsed sidebar's profile icon links to `?tab=profiles`.
- **Layout.** A 220px tablist beside a content column at most 760px wide. Each tab is an h2, a muted lead, then groups
  32px apart under h3s. Below 800px the tablist is one horizontally scrolling row (`aria-orientation` follows).
- **Saving.** Each form's Save is the one primary button in its group, with a result line under it (`aria-live`):
  "Saved.", or the error. A validation error goes under the field it names (`[data-error-for]`). The toast still
  appears. Saving moves no focus.
- **Independent checks.** **Every ledger extraction** says which decision model checks extractions (`#decision-status`)
  and links to Local models. **Document reasoning reviewer** (`PUT /api/reviewer-settings`) is Off, a second chat model
  (loopback URL and model ID, with Test connection) or the decision model. Only the fields shown are sent; sampling
  keeps its saved values. It's hidden in a family profile, like the model forms.
- **Donate.** How many documents are checked and ready (`GET /api/donations`), and a link to `#/donate`, where the work
  stays.
- **Appearance.** Theme: System (the default, following Windows), Light or Dark. The choice is saved in this browser
  (`localStorage["home-manager-theme"]`, `theme.js`); with storage blocked it falls back to System.
- **Library folder.** Changing it switches libraries, so it asks for confirmation.
- **Local models.** Grouped as This computer or a shared GPU, Reading documents (vision), Reasoning, and Decision model.
  Each model has **Test connection** (`POST /api/model-connection-tests`: lists the served models, loads nothing, sends
  no content; the decision model's uses `POST /api/decision-model-tests`).
- **Model settings while busy.** Saving model settings (the reviewer's too) is disabled while the model queue is busy,
  with an explanation.
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
- `--paper` stays white in both themes, behind document images (the source viewer's, `.donate-frame`).
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
- **Components** are vanilla factory functions that return DOM nodes: `element()` and `cell()` (`app.js`), and in
  `ui.js` `statusBadge()`, `amount()`, `dateText()`, `alertBox()`, `emptyState()`, menus, dialogs and toasts.
  `asyncButton(label, onClick, className)` runs its action once at a time (disabled while it runs; an error becomes a
  toast). `dataTable(columns, rows, {caption, className})` is every generic table in its `.table-wrap`: columns are
  `[title, className]` pairs, rows are `<tr>` elements or arrays of cell values (Today's and the family's tables,
  Inventory's, Processing's and What If's tracking tables build on it).
  `pageState(host, load, {loading, what, content, needsLibrary})` gives a page its loading, error and no-library
  states in a `.page-state` host after its header: nothing for 300 ms, then a muted "Loading …" line with a spinner
  (`role=status`, `aria-busy` on the page); an error is an `alertBox` (`role=alert`) with Technical details and Retry,
  shown in place of the shell's toast; without a library, "Set up your library to see …" with Open Settings. `content`
  is hidden on an error or without a library. A newer call wins over an older one. Retry keeps focus on the host while
  it loads, then moves it to the page heading. Empty data stays each page's own `emptyState()`. Every screen uses it
  (Taxes hides `#taxes2-body`, so the year select stays usable).
  This matches the strict CSP (`script-src 'self'; style-src 'self'`): no inline scripts or styles, no CDN fonts,
  scripts or chart libraries. Icons come from the vendored `icons.svg` (a Lucide subset, ISC license).
- **Charts** are inline SVG with a data-table fallback. Today draws its own (`home.js`); the forecast's, What If's and
  the tax buckets are drawn by the server (`finance/charts.py`).

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

### Every number explained

The visual direction (C · Family, 2026-10-06) is in `design-system/home-manager/MASTER.md`; the session process for
changing a screen (per-screen hand-offs, screenshots on synthetic data) is in the `ui-redesign` skill. Every number on
screen can be explained. These rules override visual or layout preferences.
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
  and `verification`. The older plain fields stay beside it.
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
    `spending.category`, Today's
    `spending.other` and `spending.gross`, `spending.usd` (each converted line with its ECB rate), `split.receipt` and
    `split.charge` (largest-remainder cents as the rounding row), This month's `spending.change` (a category's change:
    the two months' `spending.category` as steps), `spending.net_change` (the two months' `spending.net`; the Net
    spending tile's "more/less than" line), `spending.merchant` (a top merchant, refunds taken off) and
    `spending.refunds` (the Refunded tile), `budget.remaining`, `budget.projected`,
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
  - **Household items** (`household/item_traces.py`): `items.spending` and `items.waste` (one step per product, for a
    period), `items.per_30_days` and `items.forecast` (one step per product's rounded rate, its cost, days and lots as
    an input, and the half-even rounding of the total). `Recorder.only()` keeps the rounding of the currency asked for.
  - **Family** (`finance/traces.py`): `family.spending.net`, `family.cashflow.net`, `family.cashflow.in`, `family.spending.category`,
    `family.spending.gross`, `family.spending.other` and `family.worth.today` add up each member's own figure. Any ref
    with `member=<id>` runs the same calculation on that member's read-only copy.
  - **Document checks** (`finance/document_traces.py`, [documents](documents.md#pay-stub-and-statement-fields)): a
    record's own arithmetic checks, each a figure in the record's `checks`: `receipt.fuel` (volume × price per unit),
    `receipt.dining` (subtotal, tax, gratuity and tip; a tip that isn't printed is a step with no value),
    `receipt.unit_line` (`&position=`; count × unit price), `receipt.paid` (the printed total less gift cards),
    `paystub.hours` (`&position=`; hours × rate), `paystub.deposits` and `statement.summary` (a bank or card summary).
    **The one exception to `reconciles`:** for these it is the check's outcome, the result against the printed amount in
    `compared_with`, so it can be false by design (the parity loop must leave them out). A product is one step at its
    rounded value, the exact product in the rounding note (`half_up_minor`). Non-money inputs are `input_text` (exact
    text and unit; their text and unit are hashed, so a corrected volume makes the figure stale). Inputs are
    `extracted` (document, cited lines, quote) or `override` (the reading's value, who and why). A ref for something the
    record doesn't have is "This isn't worked out for this record." (400).
- **Review state.** A breakdown takes its inputs as correct: figures don't carry whether an input still waits in To check
  (decided 2026-10-05). The trace's own `verification` roll-up is informational.
- **Stale.** Opening a trace compares its `inputs_hash` with the one in `figure_snapshots` for that ref, then stores the
  new one. Today (net spending and cash flow), Taxes and the family's returns (the refund or amount owed) do the same
  when they show the figure (`traces.shown`, `traces.shown_tax`, `traces.shown_family_tax`), so the figure carries
  `stale` without its breakdown being opened. A return figure (`tax.result`, `tax.line`, `tax.node`) also hashes its
  engine's pinned SHA-256 (`build(..., hash_extra=)`), so a changed engine marks it stale too.
- **Provenance.** `finance/provenance.py provenance_for(db, type, id, field)` is served at
  `GET /api/provenance/{type}/{id}?field=`. It resolves imported (file and row; for a PDF row also the page, the table and `continued_from`, with `document.lines` or the word ids that
  light the cited lines), manual (who, when), extracted (model, run,
  cited lines, quote, page from the line id, the independent check's doubt), a market rate, and override (original,
  newest value, who, when, why, how many times). Trace inputs carry a light provenance (kind and the record). The page fetches the full one for an imported PDF
  row (`trace.js showPdfSources`, one request per such input; see [open work](open-work.md#money)).
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
`tests/test_trace_components_browser.py` mounts `figure`, `breakdownPanel`, `provenanceBadge` and `ruleCard` in the
real app with the synthetic dashboard's traces, and `tests/test_record_components_browser.py` mounts `confirmCorrect`,
`sourceViewer` and `historyList` (with their loaders `loadReading` and `loadHistory`) on read and recorded synthetic
documents (`tests/seed_documents.py`). Each makes its own ids from a counter (`sv{n}-…`, `cc{n}-…`). The document page
and To check use the record components; To check moves `confirmCorrect`'s form and state line into its own regions and
gives the buttons the `#review2-*` ids its keys press.

- **`figure(fig, {size, signed, magnitude})`** is a `button.figure-button` (`data-figure-ref`, `data-figure-display`,
  `data-signed`, `data-magnitude`, `aria-controls`, `aria-expanded`) around `amount()`, flagged `unconfirmed` when the
  figure's verification is `needs_review`, partial or unverified, and `stale` when it changed. A `.figure-tile` holding
  the open figure gets the accent border and ring. `signed` and `magnitude` go to `amount()`; a tax figure uses
  `magnitude` and its label gives the direction ("Refund", green with `+`; "You'd owe", text color with no sign).
  Sizes are `lg` (a tile's figure), `inline` (the text around it) and `sm` (no size of its own: the surrounding
  font's, at the button's default line height).
- **A row of figure tiles shares one figure size.** `fitFigures(row)` sets `--figure-chars` on the row (or a What If
  plan headline) to its longest amount's visible length, and each `.figure-tile` (a size container) sizes its figure
  to its width, from `--figure-lg` down to `--text-lg`. Pages call it after filling the row. Digits never wrap; at the
  smallest size the currency code may drop under them, and a badge drops under its amount.
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
| `provenanceBadge(prov)` | Icon + text through the `STATUS` map: Entered by …, Read by model …, Imported · file row (a PDF row: Imported · file page N, with "continued from page M" and an Open source link), Worked out, Changed from … · reason, the rule name, the ECB rate date. |
| `confirmCorrect(opts)` | `div.confirm-correct`: a `role=group` "Decision" with the state's buttons, then `.cc-state`, then the hidden `form.cc-form`. Needs review or proposed shows Confirm (primary), Reject (secondary: it can be undone) and Correct…. Verified shows Undo verification and Correct…. Checked automatically shows "Not right? Reject" and Correct…. Rejected shows Undo rejection. Decisions post to `reviewPath` (default: the record's `/review`, as Review V) and offer Undo for 8 s; a failure stays inline. Correct… opens one field per `correctable` entry plus "Why (optional)". On input (450 ms debounce, late answers dropped) it shows the correction preview: before (a traced figure) → after (a plain amount) and the difference, then what stays, the match, review and notes. A 400 disables Save. Save PATCHes, then offers Undo (`/corrections/undo`). Esc closes the form. Options: `labels`, `undoBody`, `preview: false`, `decision: false` (Correct only, for a statement's row), `showState`, `onClose`, `awaitingAccount` (a statement whose account waits for Confirm: a record that was checked automatically before accounts waited offers Confirm and Reject as a proposed one does, and the stored status isn't rewritten). |
| `sourceViewer(doc, reading, {runId, digest})` | `section.source-viewer`: Image \| Text tabs, a PDF page select, the preserved image (bearer fetch into a blob URL; a PDF gets a fresh iframe) with its read regions, the text as a roving list of `li.sv-line[data-line-id]` (↑/↓, Enter), and "Reading notes & codes". `highlight(ids)` goes to Text for a vision or PDF reading and marks the lines; otherwise it lights the regions. A region click or Enter on a line calls `onRegionClick` callbacks with `{blockId, lineIds}`. Also `update(reading, runId)`, `showDocument(id)` (a group's other page) and `destroy()`. Text read from documents stays text. |
| `historyList(entries, {field, empty})` | `ol.history-list` of `li.history-row[data-kind]`: when, who ("Automatic check" for a review a correction made), then from → to (dates, categories and empty values in words; a statement row's label first) or a review's status → status, then why. `loadHistory(type, id)` fetches the entries. |
| `loadReading(documentId, digest)` | `{doc, run, result}` for a document's newest finished reading (else its newest), cached until `clearReadings()`; one still running isn't cached. |
| `ruleCard(rule)` | Name, source as text, version, tax year, checked on, CPA review state. |

### Number display

- Amounts are server `display` text through `amount()` only. Hand-typed "$" is removed. Money out is `−` (U+2212) in a
  fixed sign slot; money in is `+` and `--positive`. The UI never uses parentheses.
- Percentages are server `*_percent` text. The browser doesn't convert basis points.
- When the server reports a rounding adjustment, it is shown as a row ("Rounding: +0.01"). A cent is never hidden.
- Verified, unverified, stale and changed each carry an icon and text, never color alone.
- **Every screen reconciles.** `tests/test_ui_parity.py` (browser, synthetic seed from `tests/seed_taxes.py` and
  `tests/seed_wealth.py`) runs `test_every_screen_reconciles` over every screen with traced figures (`home`,
  `spending`, `bills`, `accounts`, `investments`, `forecast`, `taxes` (skipped when Engine 1 doesn't cover this year)
  and `inventory?tab=insights`): every figure has a ref, equals its trace's result and reconciles (`check_figures`).
  The harness's self-test also checks that it fails on a seeded mismatch. It sees a screen's first tab only; each
  screen's own browser test checks its other tabs, and screens whose figures appear only after an action (What If) or
  that need a seeded document id (the document page, which also checks "Counts as" against the record's own total) run
  `check_figures` there.
- **Retired settings.** The old per-screen flag (`ui_v2_screens`) is gone; `HouseholdConfig` drops a stored key when it
  loads (`finance/ledger.py` `retired_keys`), so settings saved while it existed still open.

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
  - Today's category shares as `share_bp` (whole basis points summing to 10,000, so the donut closes) with
    `categories_chartable`;
  - the budget meter's `meter_percent`, `remaining_state` and `over`;
  - each upcoming bill's `group` (overdue, this_week, later);
  - To check's badge and group counts from `GET /api/review/counts` (uncapped), and the check-in count with them;
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

1. **Accent color:** one accent for interaction (cobalt, `design-system/home-manager/MASTER.md`); green means only
   money in or verified. An exceeded budget is amber, never red (2026-10-06).
2. **Money parts:** no backend change. The UI splits the server's `display` text lexically.
3. **To check** shows display summaries (merchant, amount, date, account, document) for every item, never bare ids.
4. **Accounts** shows per-account balances with "as of" dates. It stays a top-level page. Since 2026-10-06, Today shows
   **Cash** and **Net worth** across all accounts (`worth.today`), with the date range and stale accounts flagged.
5. **The document page** is a route, not a modal. Lists use a non-modal drawer where a detail view is needed.
6. **One UI** (2026-10-12): the redesigned screens replaced the old ones, which are deleted. Passing tests were enough
   to delete an old screen; there was no separate sign-off.
