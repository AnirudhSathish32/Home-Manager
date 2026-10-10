# Screen inventory

This is a starting map for planning one screen. The Grep commands below are authoritative for selectors, and this table
may lag the code. Routes come from `ROUTES` in `shell.js`. All files are in `src/home_manager/app/static/` unless a
path says otherwise.

| Route | Loader → file | Main containers in `index.html` | `style.css` section | Browser tests touching it |
|---|---|---|---|---|
| `#/home` | `loadHome` → `home.js` | `#home-panel` | (Base/Shell) plus home rules | `test_home_browser.py`, `test_investments.py` (home card) |
| `#/review` | `loadReview` → `review.js` | `#review-panel`, `#review-detail`, `#group-suggestions-panel`, `#family-routing-panel`, `#review-unmatched-panel` | "Review." | `test_browser.py`, `test_receipt_counting.py`, `test_family_browser.py` |
| `#/transactions` | `openTransactions` → `finance.js` | `#transactions-panel` | "Finances", "Transaction drawer." | `test_browser.py`, `test_family_browser.py`, `test_receipt_counting.py` |
| `#/spending` | `openSpending` → `finance.js` | `#spending-panel`, `#budget-panel`, `#rules-panel` | "Finances", "Budget meters" | `test_browser.py`, `test_home_browser.py` (drill-down) |
| `#/bills` | `loadBills` → `finance.js` | `#bills-panel` | "Bills and accounts." | `test_recurring_bills.py`, `test_browser.py` |
| `#/accounts` | `loadAccounts` → `finance.js` | `#accounts-panel` | "Bills and accounts." | `test_browser.py` |
| `#/investments` | `loadInvestments` → `investments.js` | `#investments-panel` | "Investments" | `test_investments.py` |
| `#/taxes` | `loadTaxes` → `taxes.js` | `#taxes-panel`, `#taxes-family-panel`, `#taxes-return-panel`, `#taxes-zen` | "Taxes:" | `test_taxes_browser.py` |
| `#/forecast` | `loadForecast` → `forecast.js` (SVG from `finance/charts.py`) | `#forecast-panel`, `#forecast-charts` | "Forecast" | `test_forecast.py` |
| `#/whatif` | `loadWhatIf` → `whatif.js` | `#whatif-panel`, `#track-panel`, `#paycheck-result` | "What If:" | `test_whatif_browser.py` |
| `#/inventory` | `loadInventory` → `inventory.js` | `#inventory-panel`, `#checkin-panel`, `#return-policies-panel` | "Inventory and check-in." | (check with Grep) |
| `#/documents`, `#/receipts` | `showLibrary` → `library.js` | `#library-panel` | "Documents" | `test_browser.py`, `test_document_search_browser.py`, `test_share.py` |
| `#/documents/ID` | `openDocument` → `receipt.js` | `#document-page` | "Document inspector", "Pay stubs", multi-receipt rules | `test_browser.py`, `test_employers.py`, `test_document_search_browser.py` |
| `#/search` | `openSearch` → `search.js` | `#search-panel` | "Search" | `test_document_search_browser.py` |
| `#/processing` | `loadProcessing` → `processing.js`; `loadJobs`/`loadModelHistory` → `app.js` | `#scan-panel`, `#model-history-panel` | "Processing", "Processing and settings" | `test_browser.py` |
| `#/settings` | `shell.js` tabs; `profiles.js` | `#settings-panel` | "Settings" | `test_family_browser.py`, `test_share.py` |
| `#/donate` | `openDonate` → `donate.js` | `#donate-panel` | "Donate documents" | `test_donate_browser.py` |
| Ask panel | `assistant.js` | (assistant drawer) | "Assistant panel" | (check with Grep) |
| Shell, sidebar, nav | `shell.js`, `app.js` | `.nav-link[data-route]`, `#toasts` | "Shell", "Responsive" | every browser test |

## Shared helpers (reuse, don't re-create)
- `ui.js` has `icon()`, `amount()`, `dateText()`, `dateDisplay()`, `statusBadge()`/`setStatusBadge()` with the `STATUS` map,
  `emptyState()`, `alertBox()`, `technicalDetail()`, `toast()`, `menu()`, `confirmAction()`, `kindSelect()` and
  `categoryLabel()`. `pageState(host, load, {loading, what, content, needsLibrary})` gives a page its loading, error
  (with Retry) and no-library states in a `.page-state` host after its header; `setStatusBadge()`/`statusBadge()` take
  an optional 4th `label` that keeps the status's tone and icon.
- `trace.js` (docs/ui.md "Observability components"): `figure(fig, {size})` for any traced figure, the shared breakdown
  panel (`openBreakdown(ref, opener)`, `drillBreakdown`, `backBreakdown`, `closeBreakdown`; `<aside id="breakdown">`),
  `provenanceBadge(prov)` and `ruleCard(rule)`. A v2 screen registers in `shell.js` `V2_SCREENS` and adds its
  `(route, v1 route)` pair to `MIGRATED` in `tests/test_ui_parity.py`, whose `check_figures()` and `v1_amounts()` it
  reuses.
- DOM factories: `element()` and `cell()` in `app.js`, `homeLink()` in `home.js`, and `asyncButton()` in `finance.js`.
- Icons come from `icons.svg` through `icon(name)`.
- Charts: `CHART_COLORS` in `home.js` and the server-drawn SVG in `src/home_manager/finance/charts.py`.

## Getting a page's selector contract
Run these with the Grep tool (`output_mode: content`). Don't print whole files.
- Ids the tests use: pattern `locator\("#[\w-]+` in the test files from the table, or `#<prefix>-` for a page
  (e.g. `#donate-`, `#investment`).
- Classes and roles the tests use: patterns `locator\("\.[\w-]+` and `get_by_role\(` in those files.
- Ids the JS looks up: pattern `\$\("[\w-]+"\)` in the page's JS file.

Any id or class in these results is part of the contract. Keep it, or list the rename and the test edit it needs in the
plan.
