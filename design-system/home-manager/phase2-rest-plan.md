# Redesign: the rest — Records, Search, Ask, navigation, Money leftovers (phase 2) and cleanup (phase 3)

This plan has six builds. **Each build runs in its own implementation session**, in the order A → F, and is verified on
its own. Commit a build only when the user asks. **Step 0, right after this plan is approved (user request,
2026-10-11):** copy this file verbatim to `design-system/home-manager/phase2-rest-plan.md` in the working directory,
with the Write tool. Every build session reads it there. Build A writes
`design-system/home-manager/pages/records.md` and Build B writes `pages/search-ask.md`, both in the shape of
`pages/wealth.md` (jobs, Components, Layout, States, Decided), copied from here.

## Context
Phase 2 has built Taxes, Today, the document page, To check, the four Money screens, Wealth (Investments, Forecast, What
If), Inventory and Processing, and restyled Settings in place. Everything the redesign still owes (docs/open-work.md
"UI redesign" items 6–8, docs/ui.md "Redesigned navigation") falls into these builds:

| Build | Phase | What |
|---|---|---|
| A | 2 | **Records**: the library for `#/documents` and `#/receipts` (`records_v2.js`) |
| B | 2 | **Search** v2 (`search_v2.js`) and **Ask** restyled in place as a docked column |
| C | 2 | **Sidebar regroup**, the **transaction drawer** on `confirmCorrect`, **tax-tag links** (item 7), account names |
| D | 2 | **Money leftovers**: traces for This month's untraced numbers |
| E | 3 | **v2 becomes the only UI**: the flag goes, tests are ported |
| F | 3 | **Delete v1**: loaders, dead helpers, dead CSS; docs rewritten |

Decided with the user on 2026-10-11:
1. **Plan Phase 2 and Phase 3 together** (this file), one session per build.
2. **Records gets a work strip and quiet rows.** A strip above the list names the backlog with the page's only primary
   ("21 not read yet · Read all 21"). Each row's next step becomes a text link, and the ⋯ menu stays.
3. **Ask becomes a docked, non-modal column** beside the page at ≥1180px, sharing the breakdown panel's slot (opening
   one closes the other). It floats over the right edge at 900–1179px and is a bottom sheet below 900px. Toasts move
   out from under it.

What's wrong today (before screenshots plus three Explore passes):
- **Documents and Receipts (`library.js`):**
  - Every row has a filled primary button ("Read", "Import transactions"): 27 primaries on one page.
  - **At 390px the Name column collapses to one character wide**, so titles run down the page letter by letter
    (`receipts-390-light.png`).
  - In the folder tree, "All receipts & statements" collides with its count ("statements3").
  - Only `status` and `q` are in the URL. Folder, category, dates, sort and page are lost on reload (rule 5;
    open-work "Filters lost on reload").
  - Everything sits in the Inbox in the seed, and the backlog (21 not read) shows only as a chip count.
- **Search (`search.js`):**
  - A full-width input with a lone button, and results in plain bordered panels.
  - "View all" leaves the page (Documents, Transactions, Inventory).
  - No kind filter. A no-results state with no next step.
  - Account names double ("Household checking checking").
- **Ask (`assistant.js`):** a fixed overlay (`z-index: 40`) covers the page and the toast region (same z-index,
  same corner). `body.assistant-open` is set but unused.
- **Sidebar:** Taxes and Wealth sit inside Money, Receipts & statements sits under Money not Records, and Donate is still
  in the footer (it's now a Settings tab).
- **Transaction drawer (`finance.js` `openTransaction`):** its own Count it / Reject / Undo buttons instead of
  `confirmCorrect` (open-work item 6).
- **Tax tags:** Taxes › Write-offs rows tagged on a receipt or a receipt line are plain text with no link to the
  document. The document page already shows receipt and line tags (`document_v2.js:415` → `taxReceiptSection`), so
  item 7's `GET /api/tax-tags/on/{receipt|receipt_item}` is covered by `?receipt_id=` and needs no new screen.
- **This month:** a category's change, top merchants and the Refunded tile are untraced plain amounts. There's no
  traced difference between the two months' net spending (open-work item 6).
- **Cleanup:** the v2 files depend on v1 files. Twelve call `homeLink` (home.js), `document_v2.js` uses about 40
  `receipt.js` names, and `transactions_v2.js` opens v1's drawer. So whole v1 files can't simply be deleted (Build F).

## Before screenshots
Taken 2026-10-11, flag off, into the session scratchpad `…\scratchpad\before-rest\` (it may be gone). Look at:
- `documents-1440-light.png` (full page, 2,345px)
- `receipts-1440-light.png`
- `receipts-390-light.png` (the collapsed Name column)
- `search_q=fresh-1440-light.png`
- `search_q=coffee-1440-light.png` (no results)

**Each build re-takes its own before shots first:**
`.venv/Scripts/python.exe .claude/skills/ui-redesign/scripts/ui_shots.py --routes <routes> --full-page --out <scratch>/before-<build>`.
The default seed has 27 Inbox documents, three money documents and 14 matches for "fresh". It is enough for A and B.

## Design-system references
MASTER.md applies unchanged. Pro Max (`--domain ux`) returned generic advice that MASTER already covers: bulk actions
via a checkbox column and an action bar, an overflow wrapper for tables, a confirmation for every action, disabled
buttons while busy, and suggestions on no results.
- **"Components":**
  - Tinted region (`.today-region`, never nested; lists inside use 1px dividers).
  - Needs-attention row (`.needs-row.attention`): the work strip.
  - Table (sticky `--surface-sunken` header, 40px rows, amounts right-aligned).
  - Chips (30px pills; pressed is `--accent-subtle` fill with an `--accent` border).
  - Status badge, and buttons (one primary per region; text links for row steps).
- **"Layout":**
  - The page header (h1, muted subline, actions on the right).
  - The breakdown panel's column, float and sheet behaviour, which Ask reuses.
  - The sidebar groups follow docs/ui.md "Redesigned navigation".
- **"Meaning is fixed":**
  - "Couldn't process" is `danger` through `statusBadge` (it is an error).
  - Not read / needs review are `warning`. Recorded/verified shows a `positive` badge only where v1 did. Money out
    is `−` in `--text`, never red.
- **Deviation (B, Ask):** Ask is **restyled in place, not a `data-ui="v2"` twin**. It isn't a page (no `data-page`).
  The only test is `test_browser.py:347–361`, and a twin would duplicate the polling and history code. The column
  is 360px (`--panel-width`, shared with the breakdown panel), not the 400px in the mock-up, so the two share one grid
  track.
- **Deviation (C, sidebar):** "Inbox" and "Unfiled" stay as sub-links under Documents. They aren't in "Redesigned
  navigation", but they carry the attention counts the user relies on. Update the doc to say so.

## Tokens
No new tokens. Used:
- Surfaces and borders: `--canvas`, `--surface`, `--surface-sunken`, `--border`, `--border-strong`.
- Text: `--text`, `--text-secondary`, `--text-muted`.
- Accent: `--accent`, `--accent-subtle`, `--on-accent`.
- Status: `--warning`/`--warning-subtle`, `--danger`/`--danger-subtle`, `--positive`.
- Size: `--panel-width`, `--sidebar-width`, `--shadow-overlay`, `--motion-panel`.
- Scales: `--space-*`, `--radius-*`, `--text-*`, `--figure-lg`.

Every pair is already in MASTER "Checked contrast". No hex outside `:root`.

**Icons:** check `ui.js` `ICONS` first, and add only what's missing. Records uses `file-text`, `inbox`, `folder`,
`trash-2` and `book-open` (Read). Search uses `search`. Ask uses `message-square` (the nav icon already exists) and
`x`. Take Lucide paths as earlier plans did.

---

## Shared (every build)

### Registration pattern (A and B; copy `transactions_v2.js` and `investments_v2.js`)
- **Load order:** each new file loads with `defer` in `index.html` after `processing_v2.js` and before `shell.js`.
  **Add each new static file to `api.py`'s static allowlist**, or it returns 404.
- **Section:** `<section id="<p>-panel" class="page" data-page="<page>" data-ui="v2" aria-labelledby="<p>-title" hidden>`
  goes right after its v1 twin. It holds `header.page-header` (h1 `tabindex="-1"`, `p.page-subtitle`,
  `div.page-actions`), then `div#<p>-state.page-state`, then `div#<p>-body.page-body`.
- **Prefixes:** `rc2` (Records) and `se2` (Search). **Never reuse a v1 id.** v1 stays until Build F.
- **URL:** filters are read in `show` and written with `history.replaceState`, non-default params only, also setting
  `currentRoute.params` (`transactions_v2.js` `tx2WriteUrl`, :74–77).
- **`show`:** `return pageState($("<p>-state"), render…, {loading, what, needsLibrary: true, content: [$("<p>-body")]})`.
- **Display:** dates go through `dateText()`/`dateDisplay()` and status through `statusBadge()`. Amounts are server
  text, through `amount()` where the server sends a money object, or as the `ledger_amount` display string in a
  `.numeric` cell. No arithmetic in the browser. Long text wraps with `overflow-wrap:anywhere`; amounts never wrap.

### Reused helpers (don't re-create)
- `ui.js`: `amount`, `dateText`, `dateDisplay`, `statusBadge`, `emptyState`, `alertBox`, `pageState`, `confirmAction`,
  `icon`, `menu`, `toast`.
- `app.js`: `element`, `cell`, `api`, `notice`, `wireTabs`, `showVersions`.
- `finance.js`: `asyncButton`, `openTransaction`.
- `trace.js`: `figure`, `openBreakdown`, `closeBreakdown`, `confirmCorrect`.
- `library.js`: `documentName`, `fileName`, `folderLabel`, `documentStateBadge`, `openLibraryAction` (the move/delete
  dialog), `restoreDocuments`, `openImport({onDone})`, plus the description dialog's opener (Grep `description-dialog`
  in library.js for its function).
- CSS: `.today-region`, `.needs-row(.attention)`, `.chip[aria-pressed]`, `.table-wrap`, `.figure-tile`.

### Tests (pattern)
- A and B each add `tests/test_<screen>_v2_browser.py`, using `served()` from `tests/test_taxes_v2_browser.py` and
  `tests/seed_documents.py`. Turn the flag on with `page.request.put(f"{base}/api/ui-screens", data={"routes": [...]}, headers=…)`.
- Every test collects `pageerror`s (none allowed) and checks `NO_OVERFLOW` at 390, 768 and 1440.
- A build that touches a v1 file re-runs that file's v1 browser tests (`tests/test_browser.py` for library.js,
  finance.js, assistant.js and shell.js).
- **Run only the build's own tests** (memory: targeted test runs).

---

## Build A — Records (`#/documents`, `#/receipts`, `records_v2.js`)

### Registration
- `V2_SCREENS.documents = {title: "Documents", show: route => loadRecordsV2("documents", route.params)}`.
- `V2_SCREENS.receipts = {title: "Receipts & statements", show: route => loadRecordsV2("money", route.params)}`.
- One `data-page="documents" data-ui="v2"` section serves both. `ROUTES.receipts.page` is already "documents".
- **`loadRecordsV2` sets the global `libraryScope`** (library.js:29), so `shell.js` still highlights `#nav-receipts`
  on an open money document and `leaveDocument()` falls back to the right list.
- `history.back()` from a document lands on the list's URL, which now holds its filters, so `openedFromList` and
  `listScroll` work unchanged.
- **Sidebar sub-links:** `#nav-inbox` and `#nav-unfiled` call `showFolder` (library.js:148). While the v2 screen is
  on, make them set `#/documents?folder=Inbox` (or `Unfiled`) instead. Add a guard in `showFolder`: when
  `uiV2Screens.includes("documents")`, set the hash and return.

### URL (rule 5)
`#/documents?folder=&category=&employer=&section=&status=&q=&from=&to=&sort=&offset=`. The same keys work for
`#/receipts`. `status` and `q` keep v1's meaning (search and Home links use them). Defaults (folder `all`, status
`all`, sort `date`, offset 0) are left out of the URL. Validate each value against the folder list, `WORK_FILTERS`
(library.js:16) and `DOCUMENT_SORTS` (storage.py:36), and drop bad ones.

### Data
- `GET /api/folders?scope=` gives folders, counts, `work` (the per-status counts), receipt categories and jobs.
- `GET /api/documents?scope=&folder=&status=&q=&sort=&date_from=&date_to=&category=&employer=&section=&offset=&limit=50`.
- **Read all:**
  1. Collect the ids with `GET /api/documents?scope=…&status=needs_text&limit=200`, paging while
     `offset < total`, up to 500.
  2. `POST /api/receipt-batches {document_ids}`.
  3. On 202, toast "Reading N documents. Follow it on Processing." with a link to `#/processing`, then reload.
  4. On 409 (model work running), show the server's message inside the strip and leave the button enabled.

### Layout at 1440×900
```
┌nav┐ Documents                                                   [Refresh]
│   │ Your papers: leases, policies, pay stubs, tax forms. New files arrive in the Inbox.
│   │ ┌───────────────────────────────────────────────────────────────────────────────┐
│   │ │ ⚠  21 not read yet · 2 ready to record · 4 need review · 1 couldn't process   │  ← .needs-row.attention
│   │ │    (each count is a text link that sets ?status=)              [Read all 21]   │  ← the page's one primary
│   │ └───────────────────────────────────────────────────────────────────────────────┘
│   │ [🔍 Search names, files or words…      ] (All 27)(Not read 21)(To record 2)(Review 4)(Couldn't 1)
│   │                                               From [    ] To [    ]  Sort [Document date ▾]
│   │ Showing Inbox · Not read yet — Clear filters                               (only when filtered)
│   │ ┌ Folders ──────────┐┌──────────────────────────────────────────────────────────────────┐
│   │ │ All documents  27 ││ ☐ 3 selected · Read · Combine · Move · Delete · Clear  (only w/ selection)
│   │ │ Inbox          27 ││ ☐ Name                    Folder   Date     Amount   State       │
│   │ │ Unfiled         0 ││ ☐ Target                  Inbox    Oct 8   −25.00   ⚠ Not read   Read  ⋯
│   │ │ Housing         0 ││   items-7.png                                          No matching charge
│   │ │ Insurance       0 ││ ☐ Fresh Market            Inbox    Oct 4    98.75   To import    Import ⋯
│   │ │ › Jobs          0 ││   card-statement.csv
│   │ │ Trash           0 ││ …                                                               │
│   │ └───────────────────┘│ ‹ Previous   1–27 of 27   Next ›                                 │
│   │                      └──────────────────────────────────────────────────────────────────┘
```
- **Header:**
  - The h1 is "Documents" or "Receipts & statements", with the v1 subtitles from `LIBRARY_SCOPES` (library.js:23–28).
  - Actions: Refresh (secondary). No primary in the header; the strip holds it.
- **Work strip:**
  - It shows only when some `work` count other than "all" is above zero, and lists only the counts above zero, in
    `WORK_FILTERS` order with v1's labels. Each count is a `link-button` that sets `status`.
  - The **Read all N** primary appears only when not-read is above zero. When every count is zero, the strip is
    replaced by one muted line: "Everything here has been read." with a positive check icon.
- **Toolbar:**
  - Search input (debounced 250ms, writes `q`), then the status chips with counts (`aria-pressed`), then From/To
    dates and the Sort select on the right.
  - Under 1100px the dates and sort wrap onto a second line.
- **Filter summary line** (muted, `aria-live="polite"`): "Showing {breadcrumb} · {status label} · “q” — Clear filters".
  Clear resets everything but the scope.
- **Body:** a grid of a `220px` folder column plus `minmax(0,1fr)` for the list, both inside one `--surface` region
  with a 1px `--border` and `--radius-md` (one region; the folder column has a right border, not its own box).
  - **Folder tree:** the same structure as v1 `renderFolders` (library.js:155–179):
    - groups (Receipts → categories; Jobs → employer → Paystubs/Documents) with `aria-expanded` toggles;
    - Trash last.
  - **Folder rows:** each is `button.rc2-folder` in a `grid-template-columns: minmax(0,1fr) auto` row, so the label
    wraps and the count keeps its own column (this fixes the "statements3" collision). The selected folder is
    `--accent-subtle` with `aria-current="page"`. Empty folders are `--text-muted`.
  - **Folder description:** shown under the list head, from `/api/folders`. In Trash, **Empty trash** (secondary)
    sits at the right of the list head and runs through `confirmAction` with danger wording.
- **List:** a `table.rc2-table` inside `.table-wrap`, with a sticky header. Columns:
  - Checkbox (`#rc2-select-all` in the head).
  - **Name:** the title from `documentName` as `a.rc2-name` → `#/documents/ID` for png/jpg/pdf, or plain text for other
    files. Under it: the file name (muted, `--text-xs`), any `.search-snippet` with `<mark>`, and warnings or the
    unfiled reason as muted text.
  - **Folder:** `folderLabel`.
  - **Date:** `dateText`.
  - **Amount:** `ledger_amount` text, `.numeric`.
  - **State:** `documentStateBadge` plus the match state in muted text under it.
  - **Next step:** a `button.link-button.rc2-step`, chosen as v1 `nextStep` does (library.js:196–208): Restore,
    Import (csv/xlsx → `openImport({onDone: reload})`), Read (`POST /documents/ID/receipt-runs`), Record
    (`POST /documents/ID/extraction-runs`), or nothing. While running it's disabled with "Starting…". Then
    `notice` and reload.
  - **⋯:** `menu()` with Edit description…, Versions (n) (`showVersions`), Move, Delete (`openLibraryAction`), and the
    managed-path note as a disabled item.
- **Selection bar:** shown above the head when one or more rows are selected (sticky inside the list).
  - Text: "N selected".
  - **Read**, **Combine** (2–20 images, otherwise disabled with a title saying why), **Move**, **Delete** (all
    secondary), **Restore** in Trash only, and **Clear** as a text link.
  - It reuses v1's endpoints (`/api/receipt-batches`, `/api/document-groups`, the move/delete dialog).
- **Pager:** 50 a page. "‹ Previous · 1–50 of 132 · Next ›". `offset` goes in the URL.

### Layout at 768 and 390
- **768:** the folder column becomes a `select#rc2-folder` ("Folder: Inbox (27)", with indented options for categories
  and jobs) above the list. The table stays.
- **390:**
  - The strip stacks (counts wrap, Read all goes full width under them).
  - The chips scroll in one row (`overflow-x:auto`, no wrap).
  - Dates and sort go into a `details` "More filters".
  - **Rows stack** through CSS on the same table: `tr` becomes a grid. Line 1 is the checkbox, name and amount.
    Line 2 is file · folder · date (muted). Line 3 is the state badge, then the next step and ⋯ on the right.
  - The `thead` is visually hidden but stays for screen readers, and the select-all checkbox moves into the selection
    bar.
  - **No column narrower than its content; no horizontal page scroll.**

### Changes by file
- `records_v2.js` (new):
  - Loading and URL: `loadRecordsV2(scope, params)`, `rc2Read/WriteUrl`.
  - Strip, toolbar and tree: `rc2Strip`, `rc2Toolbar`, `rc2Folders`/`rc2FolderSelect`.
  - List: `rc2Table`, `rc2Row`, `rc2Step`, `rc2Menu`, `rc2Selection`, `rc2ReadAll`, `rc2Pager`.
  - It keeps its own state (no use of library.js's module variables except setting `libraryScope`).
- `index.html`: the v2 section with `#rc2-title`, `#rc2-subtitle`, `#rc2-refresh`, `#rc2-state`, `#rc2-body`. The rest
  is drawn by JS.
- `style.css`: a new "Records v2" section (after "Processing v2"), covering `.rc2-*`: the grid, folder rows, the
  sticky selection bar, and the stacked rows under 820px.
- `library.js`: the `showFolder` guard only.
- `api.py`: the static allowlist.
- `.claude/skills/ui-redesign/scripts/ui_shots.py`: no seeding change. Add `documents?folder=trash` to the shot list.

### Selector contract (Build A)
v1's library ids (`#documents`, `#document-count`, `.folder-link[data-folder]`, `#empty-folder`, `#select-all`, the
dialogs `#library-action-*`, `#description-*`, `#import-*`, `#versions-*`, `#nav-inbox`, `#nav-documents`,
`#nav-receipts`) are **all kept untouched**. v1 runs with the flag off, and the dialogs are shared. New ids:
`#rc2-*` only. No existing test edits.

### States
- Loading: through `pageState`.
- No library: `needsLibrary`.
- Error: an alert with Retry.
- An empty folder:
  - The Inbox empty state shows the Inbox path with a copy button (as v1 library.js:241–243).
  - Other folders say "Nothing in {folder}."
  - A filtered empty list says "No documents match. Clear filters".
- Long titles and paths wrap. A failed step shows `alertBox` in the row's state cell.
- **Family profile** (`documents`, `receipts` and `document` are in FAMILY_ROUTES): the library is that profile's
  Inbox. The strip and steps work the same, and nothing is hidden.
- Dark theme: tokens only.

### Accessibility
- **Focus order:** header → strip (count links, Read all) → search → chips → dates/sort → folders → selection bar →
  rows → pager.
- The tree is a list of buttons with `aria-current`; groups use `aria-expanded`.
- The checkbox label is "Select {title}". The ⋯ button is named "More actions for {title}".
- The step link's accessible name includes the title ("Read Target receipt").
- The selection bar and summary line are `aria-live="polite"`.
- Every state carries a badge with an icon and text.

### Verification (Build A)
- `$env:RUN_BROWSER_TESTS = "1"; .venv/Scripts/python.exe -m pytest tests/test_records_v2_browser.py tests/test_browser.py tests/test_document_search_browser.py -q`
- The new `tests/test_records_v2_browser.py`:
  - **Filters survive reload:** `?folder=Inbox&status=needs_text&sort=name&offset=0` → reload → the same chip
    pressed, the same folder selected, the same rows.
  - **Only one primary button** in the page (count `.primary:visible` = 1 with no selection).
  - **Read all:** it posts the needs_text ids (intercept the request and check the count equals the strip's number).
  - **The Name column at 390:** every `.rc2-name` has a bounding width ≥ 120px.
  - Back from a document returns to the same filtered URL and scroll position.
  - `#/receipts` shows the money folders and highlights `#nav-receipts`.
  - Trash → Empty trash asks first.
  - `NO_OVERFLOW` at 390/768/1440.
- Shots: `--routes "documents,receipts,documents?status=needs_text,documents?folder=trash" --v2 documents,receipts`
  (check `ui_shots.py --help` for the flag's exact form).

---

## Build B — Search v2 (`#/search`, `search_v2.js`) and Ask in place

### B1. Search: registration and URL
- `V2_SCREENS.search = {title: "Search", show: route => loadSearchV2(route.params)}`.
- URL `#/search?q=&kind=all|documents|transactions|items|accounts`, with `kind` left out when it's `all`.
- Ctrl+K and `/` behave as today (search.js:79–86), as do both forms setting `#/search?q=…`. The v2 page's own form
  writes `q` and keeps `kind`.
- `search` isn't in FAMILY_ROUTES and stays that way.

### Data
`GET /api/search?q=&limit=` uses `limit=6` for `kind=all` and `limit=50` for a single kind (the server already returns
every group with its `total`). Keep v1's `searchLoad` counter idea: a newer search drops older replies.

### Layout at 1440×900
```
Search
Documents, transactions, household items and accounts in one place.
[🔍 fresh                                                   ] [Search]     ← the one primary
(All 14) (Documents 9) (Transactions 5) (Items 0) (Accounts 0)            ← chips; zero-count chips disabled
┌ Documents · 9 ─────────────────────────────────────── Show all 9 ┐       ← .today-region, h2
│ Fresh Market – Groceries                               52.00 USD  │
│ Receipts · Oct 9, 2026                                            │
│ FRESH MARKET 2026-10-09 … Total 52.00 EGGS…   (snippet, <mark>)  │
│ ───────────────────────────────────────────────────────────────── │
│ Fresh Market                                           98.75 USD  │
│ Inbox · Oct 4, 2026                                               │
└───────────────────────────────────────────────────────────────────┘
┌ Transactions · 5 ──────────────────────────────────── Show all 5 ┐
│ Fresh Market   (button → drawer)                         −98.75   │
│ Oct 4, 2026 · Everyday card · Groceries                           │
└───────────────────────────────────────────────────────────────────┘
```
- **Input row:**
  - `#se2-input` (type search, `max-width: 720px`) plus `#se2-submit` primary. The status line `#se2-status`
    (`role=status`) reads "14 matches for “fresh”."
- **Chips:** `#se2-kinds .chip[data-kind]`, each with its total. A chip with 0 is disabled.
- **Groups:** each group is a `.today-region` with an h2 "Documents · 9", and "Show all 9" (a `link-button` that sets
  `kind`) when total > shown.
  - In single-kind mode the documents group ends with "Open these in Documents" → `#/documents?q=` when total > 50,
    and transactions with "Open in Transactions" → `#/transactions?q=&period=all`.
- **Rows:** `.se2-row` is a grid of `minmax(0,1fr) auto` with 1px dividers.
  - **Documents:** `a.se2-title` → `documentHref(doc)` (search.js:35–37, with `?lines=`), then muted "folder · date",
    then a `.search-snippet` with `<mark>` (reuse search.js's marker parsing). `ledger_amount` goes on the right.
  - **Transactions:** `button.link-button` → `openTransaction(id)`. Then muted "date · account · category" (category
    through `categoryLabel`), and `amount(row.amount.display)` on the right, signed.
  - **Items:** a link → `#/inventory?q=<name>`, then muted "category · bought date", then `statusBadge(status)`.
  - **Accounts:** a link → `#/transactions?account=ID&period=all`, then muted "institution · currency".
- **No results:** `emptyState` "Nothing matches “coffee”." plus a line of suggestions: "Try fewer words, or search
  the text of your documents" → `#/documents?q=coffee`, and "your transactions" → `#/transactions?q=coffee&period=all`.
- **Empty query:** a hint, "Search names, merchants, items, accounts and the words inside your documents.", with
  focus in the input.

### Layout at 390
The input row stacks (the button goes full width), the chips scroll in one row, and in each row the amount goes under the
name (`grid-template-columns: minmax(0,1fr)`).

### B2. Ask, restyled in place (deviation noted above)
- **Placement:**
  1. Move `aside#assistant-panel` into `.app-shell`, right after `aside#breakdown`, and give it the class
     `side-panel` together with `.breakdown-panel`'s layout rules. Refactor `.breakdown-panel`'s position rules into
     `.side-panel` and keep `.breakdown-panel` for its own content rules.
  2. Add `.app-shell.assistant-open` with the same three-column grid as `.breakdown-open` at ≥1180px.
  3. At 900–1179px the panel floats over the right edge (`--shadow-overlay`, non-modal), as MASTER "Deviations"
     describes for the breakdown.
  4. Below 900px it becomes a bottom sheet (max 80vh).
- **One at a time:**
  - `toggleAssistant(true)` calls `closeBreakdown()`.
  - `openBreakdown` (trace.js:25) calls `toggleAssistant(false)` when the Ask panel is open. Guard it with
    `typeof toggleAssistant === "function"`.
  - Toggle `.app-shell.assistant-open` alongside the existing `body.assistant-open`.
- **Toasts:** at ≥900px, `body.assistant-open .toast-region, .app-shell.breakdown-open ~ .toast-region` gets
  `right: calc(var(--panel-width) + var(--space-5))`. Check that `#toasts` is a sibling after `.app-shell`, and pick the
  selector that matches the real DOM. Below 900px, while a sheet is open, toasts sit at the top
  (`top: var(--space-4); bottom: auto`).
- **Inside the panel (every id kept):**
  - **Header:** `#assistant-title` "Ask", a muted line "Answers from your records by the local model, with where each
    came from.", and `#close-assistant` (icon `x`, `aria-label="Close Ask"`).
  - **`#assistant-log`** scrolls in its own region.
    - Each exchange is a question line (semibold `--text`, muted time) then the answer (`--text-sm`, 1.5 line height).
    - Evidence chips (`.chip` styled links: "From Fresh Market receipt", "From Spending · Sep 2026"), then the
      unverified alert (`alertBox` warning), then `details.assistant-how` "How I got this (N lookups)" in a
      `technical-detail`.
    - Exchanges are separated by 1px dividers. No bubbles.
  - **Waiting:** a spinner icon plus "Looking through your records with the local model…" in the log's live region.
  - **Composer:** `form#assistant-form`, pinned to the panel bottom with a top border.
    - `#assistant-question` is a 3-row textarea, `resize: vertical`, max 8 rows.
    - Under it, a muted hint "Ctrl+Enter to ask" with `#assistant-ask` (primary) on the right. Add the Ctrl+Enter
      submit handler in assistant.js.
  - **`details#assistant-earlier`** sits under the log, above the composer, collapsed, with `ul#assistant-history`
    as a divided list.
- Behaviour, endpoints, polling, `pageContext()` and Ctrl+J are unchanged.

### Changes by file (B)
- `search_v2.js` (new): `loadSearchV2`, `se2Render`, `se2Group`, `se2DocumentRow`, `se2TransactionRow`, `se2ItemRow`,
  `se2AccountRow`, `se2Empty`. Reuse search.js's snippet and `documentHref` helpers (call them; don't copy them).
- `index.html`:
  - the Search v2 section (`#se2-title`, `#se2-form`, `#se2-input`, `#se2-submit`, `#se2-status`, `#se2-kinds`,
    `#se2-results`);
  - move the assistant `aside` into `.app-shell`.
- `assistant.js`: the shell class toggle, `closeBreakdown()` on open, and Ctrl+Enter.
- `trace.js`: close Ask in `openBreakdown`.
- `style.css`:
  - a "Search v2" section;
  - the "Assistant panel" section rewritten for the column, float and sheet;
  - a `.side-panel` rule pulled out of "Breakdown panel";
  - toast offsets in "Feedback".
- `api.py`: the allowlist.

### Selector contract (B)
- **Search v1:** `#search-panel`, `#search-results`, `#search-results .search-snippet`, `a[href*='lines=']`,
  `#global-search`, `#global-search-form`, `#nav-search`. **Keep all of them.** The flag is off in those tests.
- **Ask:** `#nav-ask`, `#assistant-panel`, `#assistant-question` (focused on open), `#assistant-log`,
  `#assistant-form`, `#assistant-ask`, `#close-assistant`, `#assistant-earlier`, `#assistant-history`. **Keep all of
  them.** `test_browser.py:347–361` must pass unchanged.
- New: `#se2-*`.

### States (B)
- **Search:** loading (status "Searching…"), error alert with Retry, no results, empty query, a long snippet (clamped
  to 2 lines with `-webkit-line-clamp`, full text in the `title`), and dark theme.
- **Ask:** empty log ("Ask about your spending, bills or documents." plus three example questions as `link-button`s
  that fill the textarea), a failed run (`alertBox` error with the server's message), a busy model, a family profile
  (Ctrl+J does nothing, as today; `#nav-ask` is hidden in family mode, so check what CSS does now and keep it).

### Accessibility (B)
- **Search:** results groups are `section`s with h2s, and the chips are a `group` named "Kind".
- **Ask:**
  - The panel is `role="complementary"` with `aria-labelledby="assistant-title"`, and it's non-modal (focus isn't
    trapped).
  - Opening focuses the textarea; Escape inside closes it and returns focus to `#nav-ask`.
  - The log stays `aria-live="polite"`.
  - Reduced motion: no slide.

### Verification (B)
- `$env:RUN_BROWSER_TESTS = "1"; .venv/Scripts/python.exe -m pytest tests/test_search_v2_browser.py tests/test_document_search_browser.py tests/test_browser.py -q`
- `tests/test_search_v2_browser.py`:
  - `?q=fresh` shows both groups.
  - The Documents chip → `kind=documents` in the URL, it survives reload, and up to 50 rows show.
  - A transaction row opens `#tx-drawer`.
  - No results shows both suggestion links.
  - At ≥1180px with Ask open, `#assistant-panel`'s left edge is ≥ the page's right edge (it doesn't overlap), a
    toast doesn't intersect the panel, and opening a breakdown closes Ask.
  - `NO_OVERFLOW` at 390/768/1440 with Ask open and closed.
- Shots: `--routes "search,search?q=fresh,search?q=fresh&kind=documents,search?q=coffee" --v2 search`, plus one shot
  of Today with Ask open (add an `--open-ask` option to `ui_shots.py` that presses Control+J before capturing).

---

## Build C — Sidebar regroup, the transaction drawer, tax-tag links, account names

### C1. Sidebar (`index.html` nav, lines ~62–94)
Regroup to docs/ui.md "Redesigned navigation". **Every `.nav-link` id, `data-route` and `data-icon` stays**; only
order and group labels change.
```
Search · Home/Today · Review/To check                       (no group label)
Money:          Spending/This month · Transactions · Bills · Accounts
Taxes:          Taxes
Wealth & plans: Investments · Forecast · What If
Home & things:  Inventory
Records:        Receipts & statements · Documents (› Inbox, › Unfiled)
Footer:         Ask · Processing · Settings · Who's here
```
- Remove `#nav-donate` from the sidebar. The route and the Settings › Donate tab stay. Grep the tests for `nav-donate`
  and change any click to `page.goto(f"{base}/#/donate")`.
- The labels still switch on the flag through `setHomeNavLabel` until Build E.
- In the icon rail the group labels hide, as today. In the top bar menu (under 820px) the groups follow the same
  order.

### C2. The transaction drawer on `confirmCorrect` (`finance.js` `openTransaction`, :321–423)
- Replace the status block (:333–342: the `counted`/`badge` logic and the Count it / Reject / Undo buttons) with
  `confirmCorrect({recordType: "transaction", recordId: id, reviewStatus: record.review_status, reviewSource: record.review_source, onChange: () => Promise.all([reopen(), reload(), refreshReviewCount()])})`.
  - Keep the "Counted in your totals." / "Not counted…" sentence beside it.
  - Pass `correctable: []`, because the Category form stays as the correction for transactions.
- **Wording:** the default Confirm/Reject words (open-work "One action, many names"). Grep the tests for
  `"Count it"` and `"Reject (not a real transaction)"` and update those clicks to "Confirm" / "Not right? Reject".
- **Restyle "Transaction drawer." in style.css:** sections get an h3 (`--text-sm` semibold) with 1px dividers, no
  boxes. The drawer stays a modal `dialog` (the non-modal drawer is in open-work "Not built").
- `openFamilyTransaction` is unchanged.

### C3. Tax-tag links (closes item 7)
- `finance/tax_tags.py` `target()`: add `document_id` to the receipt and receipt_item targets (`receipts.document_id`;
  join it for items).
- `taxes_v2.js` Write-offs rows (:671–695) and `taxes.js` `taxItemLink` (:625): a row whose `target.type` is
  `receipt` or `receipt_item` links to `#/documents/{target.document_id}`; transaction rows keep the drawer.
- docs/open-work.md item 7 is removed. docs/taxes.md "Tax tags" says the document page lists a receipt's and its lines'
  tags through `GET /api/tax-tags?receipt_id=`, and that `GET /api/tax-tags/on/…` serves the drawer.

### C4. Account names (server display text)
- `finance/ledger.py` `account_in` (:313–314): the default name leaves out the type when the institution already ends
  with it, compared case-insensitively ("Household checking" + checking → "Household checking").
- **Migration `065_account_names.sql`:** renames existing rows only where `display_name` is exactly the old generated
  form, i.e. `institution || ' ' || replace(account_type,'_',' ')`, with an optional `' ' || account_last_four`, *and*
  the institution ends with the type. User-chosen names are never touched. Follow docs/operations.md's migration rules
  (the safe runner).
- The merchant upper case stays in open-work. It's a merchant-naming decision, not layout.

### Verification (C)
- `$env:RUN_BROWSER_TESTS = "1"; .venv/Scripts/python.exe -m pytest tests/test_shell_browser.py tests/test_browser.py tests/test_transactions_v2_browser.py tests/test_taxes_v2_browser.py tests/test_tax_tags.py tests/test_donate_browser.py tests/test_family_browser.py -q`,
  plus the migration tests (`tests/test_migrations*.py`; Grep for the file).
- New assertions:
  - the nav group order (labels' text in order);
  - the drawer's Confirm undoes within 8 seconds;
  - a receipt write-off row links to `#/documents/`;
  - `account_in("Household checking", "checking", …)` gives "Household checking";
  - the migration leaves a custom name alone.
- Shots: `--routes "home,transactions" --full-page` at all widths (the sidebar), plus a drawer-open shot.

---

## Build D — Money leftovers: This month's untraced numbers
- **New traces in `finance/traces.py`** (register in `TRACES`; follow `spending_category` at :79 and `build`/`Recorder`):
  - `spending.change`: params `start,end,before_start,before_end,currency,category`. Its two inputs are the two
    periods' `spending.category` values (as drill-down refs) and its result is their difference. The formula reads
    "{Category} this month minus {Category} last month."
  - `spending.merchant`: params `start,end,currency,merchant`. One merchant's counted spending, the same rows as
    `get_spending_by_category`'s `top_merchants`.
  - `spending.refunds`: params `start,end,currency`. The refunds figure on the Refunded tile (the `refunds` bucket in
    `_totals`).
  - `spending.net_change`: the two periods' `spending.net` and their difference.
- **Server rows carry refs**, the same way `spending.category` refs are attached today (Grep `"spending.category` in
  `src/home_manager/finance/` and copy that mechanism): `compare_categories` rows get a `change` figure,
  `top_merchants` rows a `spending` figure, and `get_spending`'s totals a `refunds` figure.
- **`month_v2.js`:**
  - the change cell (:126–131), top merchants (:246–271) and the Refunded tile (:92) render through `figure()`;
  - under the Net spending tile's subline, add "↑ $X more than September" / "↓ $X less" as a `figure()` of
    `spending.net_change`. The arrow is text plus an icon, never red.
- **Parity:** add `spending.change`, `spending.merchant` and `spending.net_change` to `NEW_ON_V2` in
  `tests/test_ui_parity.py`. Add `spending.refunds` there too only if v1 never showed it (check `v1_amounts`).
- **Verification:**
  `.venv/Scripts/python.exe -m pytest tests/test_traces.py -q` (one test per trace: result equals the shown value and
  the steps reconcile), then
  `$env:RUN_BROWSER_TESTS = "1"; .venv/Scripts/python.exe -m pytest tests/test_month_v2_browser.py tests/test_ui_parity.py -q`
  (Grep for This month's test file name). Docs: ui.md "Trace contract" › "What's built", money.md if it lists the
  traces.

---

## Build E — v2 becomes the only UI (phase 3, part 1)
1. **Routing (`shell.js` `showRoute`):** a route shows its `data-ui="v2"` section when `V2_SCREENS[route.name]`
   exists, and otherwise the plain section (Settings, Donate, document-less pages).
   - Delete `uiV2Screens`, `renderUiV2Choices` and the `(v2 || ROUTES…)` switch; use the v2 entry when it exists.
   - `setHomeNavLabel` goes. Write the v2 labels (Today, To check, This month, Bills & subscriptions) straight into
     `index.html`.
   - `review_v2.js:420` loses its flag check, and `finance.js:765` loses its v1/v2 choice.
2. **The flag:**
   - Remove `PUT /api/ui-screens` (`api.py:809–812`, `UiScreensInput`).
   - Remove Settings › Appearance › New screens (`#ui-v2-choice`, `#ui-v2-list`) and the `ui_v2_screens` line in
     the household payload (app.js:484, :228–232).
   - In `finance/ledger.py` `HouseholdConfig`, delete the field and add a `model_validator(mode="before")` that drops
     a stored `ui_v2_screens` key. `StrictModel` forbids extras, so saved settings would otherwise fail to load.
   - Add a test that loads a config containing the old key.
3. **Tests:**
   - Remove the `PUT /api/ui-screens` line from every `test_*_v2_browser.py`, `test_review_v2_browser.py:230`,
     `test_document_v2_browser.py:144`, `seed_documents.py:37,160`, `test_settings_api.py:11–26` and
     `test_shell_browser.py:56–58`.
   - **`test_ui_parity.py`:** delete `MIGRATED`, `NEW_ON_V2`, `v1_amounts`, `shown_before` and the old-screen test.
     Replace them with `test_every_screen_reconciles`, which opens each traced v2 route
     (`home, spending, bills, accounts, investments, forecast, taxes, inventory?tab=insights`) and runs
     `check_figures`.
     - Keep `check_figures`, `browser_test`, `seeded_server`, `mount_dashboard_figures` and the harness self-test.
     - Rework `test_document_v2_browser.py:9`, which imports `v1_amounts`/`shown_before`: compare "Counts as" with the
       record's server amount instead.
   - **v1 browser tests:** for each test in `test_browser.py`, `test_home_browser.py`, `test_receipt_counting.py`,
     `test_recurring_bills.py`, `test_investments.py`, `test_forecast.py`, `test_whatif_browser.py`,
     `test_taxes_browser.py` and `test_family_browser.py`:
     - delete it when its v2 twin covers the same behaviour;
     - otherwise port its assertions to v2 selectors in that twin file.
     - **List each decision in the build's notes.**
     - Keep the helpers other tests import: `test_family_browser.spend`, `test_taxes_browser.seed_tax_year` and
       `this_year_covered`, `test_investments.statement`, `test_forecast.TODAY`/`base`. Move them into `tests/seed_*.py`
       if their file empties.
4. `ui_shots.py`: drop `--v2` (:166, :193). Every shot is the redesign.
- **Verification:** the full browser set once (the exception to targeted runs, because routing changed everywhere):
  `$env:RUN_BROWSER_TESTS = "1"; .venv/Scripts/python.exe -m pytest tests -q -k "browser or parity"`. Then
  `ui_shots.py` on every route, with no overflow and no page errors.

## Build F — Delete v1 (phase 3, part 2)
1. **index.html:** delete every v1 `[data-page]` section that has a v2 twin, and the "behind the ui_v2_screens flag"
   comments. Drop `data-ui="v2"` (and its CSS/JS checks), since only one section per page remains.
2. **v1 loaders:** delete the loaders open-work item 8 names for each screen:
   - `home.js` `renderHome`, `renderHomeExtras`;
   - `review.js` `loadReview`, `renderReviewQueue`, `renderReviewDetail`, `renderUnmatched`;
   - `finance.js` `openSpending`/`loadSpending`, `openTransactions`/`loadTransactions`/`loadItems`,
     `loadBills`/`renderBills`, `loadAccounts`/`renderAccounts`;
   - `investments.js` `loadInvestments`, `renderInvestments`, `renderInvestmentDetail`;
   - `forecast.js` `loadForecast`, `renderForecast`;
   - `whatif.js` `loadWhatIf`;
   - `inventory.js` `loadInventory`, `inventoryRow`, `renderReturned`, `renderPolicies` and the policy form;
   - `processing.js` `loadProcessing`, `renderLanes`, `loadJobHistory`, `loadModelFacets`;
   - `app.js` `loadSources`/`loadEvents`/`loadModelHistory`;
   - `receipt.js`'s v1 inspector entry (`openDocument` and its polling/keys, keeping what `document_v2.js` calls);
   - `library.js` `showLibrary`/`renderFolders`/`loadDocuments` (`app.js`);
   - `search.js` `openSearch`.
3. **Collapse the hooks and prefixes:** `investmentsReload`, `forecastReload` and its `""`/`"fc2-"` id prefix,
   `wi.p`/`wi.hooks`, `inventoryReload`, `processingReload`.
4. **Dead-code pass:**
   - List every top-level function in the v1 files. For each one, Grep `\bname\b` across `static/*.js` and delete it
     if it has no callers. Repeat until nothing changes.
   - **Helpers stay in their files** (no moving), so the v2 files keep working. A file left with only helpers stays
     with its name. Renaming files is out of scope.
5. **Duplicate helpers:**
   - Merge `actionButton` (library.js:180) into `asyncButton` (finance.js:32). Move `asyncButton` into `ui.js` and
     switch the `actionButton` callers in receipt.js, document_v2.js and whatif.js.
   - **Table builders:** add `dataTable(columns, rows, {caption})` to `ui.js`, and make `homeTable`/`familyTable`
     (if they survive), `it2Table`, `pr2Table` and `trackTable` call it. The generic `(columns, rows)` builders are the
     "five" in item 8. Inline `element("table")` code stays.
6. **Dead CSS:**
   - Delete the v1-only sections: "What If (v1)", "Bills and accounts (v1)", "Review (v1)", "Inventory and check-in
     (v1)", "Processing (v1)", "Document inspector (v1)", "Investments (v1)", "Forecast (v1)", "Finances"/home rules
     with no remaining selector.
   - **Check each selector with Grep across `static/*.js` and `index.html` before deleting it.** Keep "Budget meters"
     (`meter()`), "Transaction drawer", and the Taxes v1 rules that Taxes v2 reuses (comment at style.css:1483).
7. **Docs:**
   - Rewrite docs/ui.md "Design system" and "Pages" to match what's built.
   - Retire "Redesign: calculation observability" into them: keep "Trace contract", "Observability components" and
     "Number display" as Design system subsections, and drop "Migration".
   - Update "Screen rules" if any token name changed.
   - Update `.claude/skills/ui-redesign/references/screen-inventory.md` to the new loaders and files.
   - Fix code comments that cite renamed headings (`docs/<doc>.md "Heading"`; Grep for each old heading).
   - Empty docs/open-work.md "UI redesign" and leave the "UI" findings that remain.
- **Verification:** the full browser set and `tests/test_ui_parity.py`, then `ruff` and `mypy` as
  docs/operations.md lists them. Grep `static/` for every deleted function name (zero hits). Run `ui_shots.py` on
  every route at all widths in both themes.

---

## Out of scope (all builds)
- The global `#reconcile-prompt` above every h1.
- The `?` shortcut overlay, the first-run welcome and skeletons (open-work "UI" findings).
- The non-modal transaction drawer, and a viewer for CSV/XLSX files.
- Merchant upper case. Home's customizable panels.
- Renaming `*_v2.js` files after Build F.
- Copy not listed here.

## Verification (every build, besides its own list)
- Run only the build's tests (E and F run the full browser set, as stated).
- After shots versus before shots at 390/768/1440, light and dark. No `HORIZONTAL OVERFLOW`, no page errors.
- Keyboard: tab through the page. The focus ring is visible, and the order matches each build's Accessibility notes.
- No hex outside `:root` (Grep `#[0-9a-fA-F]{3,6}` in new CSS), no inline `style=`, and new static files are in the
  allowlist.

## Docs to update
- **A:** docs/ui.md "Pages" (a Records v2 bullet, design in `pages/records.md`), "Migration" (add `documents`/`receipts`
  and why there's no MIGRATED pair: no traced figures), and docs/library or documents doc if it describes the library
  page (Grep docs/ for "Inbox" page text).
- **B:** "Pages" (Search v2), docs/assistant.md "The Ask panel" (the docked column, one panel at a time, Ctrl+Enter),
  MASTER.md "Layout" (Ask shares the panel column).
- **C:** "Redesigned navigation" (built; Inbox/Unfiled kept), taxes.md "Tax tags", money.md (account default names),
  and open-work: remove item 7 and the drawer and names bullets.
- **D:** ui.md "Trace contract" › "What's built", and open-work: remove the untraced-numbers bullet.
- **E/F:** as listed in Build F step 7. Record each build in docs/open-work.md "UI redesign", and at the end remove
  the section.
- **Memory:** update `ui-redesign-pro-max.md`/the observability memory line after each build.
