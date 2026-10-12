# Screen inventory

This is a starting map for planning one screen. The Grep commands below are authoritative for selectors, and this table
may lag the code. Routes come from `ROUTES` in `shell.js`; each screen registers its loader in `V2_SCREENS` from its own
`*_v2.js` file. All files are in `src/home_manager/app/static/` unless a path says otherwise.

| Route | Loader → file (shared builders) | Section in `index.html` | `style.css` section | Browser tests touching it |
|---|---|---|---|---|
| `#/home` | `loadTodayV2` → `today_v2.js` (`home.js`: charts, family tables, `homeLink`) | `#today-panel` | "Today v2", "Finances" (charts) | `test_today_v2_browser.py`, `test_family_browser.py` |
| `#/review` | `loadReviewV2` → `review_v2.js` (`review.js`: `reviewData`, `summaryBlock`, `assetParts`, item dialog) | `#review2-panel` | "To check v2" | `test_review_v2_browser.py`, `test_browser.py`, `test_family_browser.py` |
| `#/spending` | `loadMonthV2` → `month_v2.js` (`finance.js`: `meter`, `txHref`, `loadCategoryOptions`) | `#month2-panel` | "This month v2", "Budget meters" | `test_spending_v2_browser.py` |
| `#/transactions` | `loadTransactionsV2` → `transactions_v2.js` (`finance.js`: drawer, `chargeCategorySelect`; `money_v2.js` dialogs) | `#tx2-panel` | "Transactions v2", "Transaction drawer." | `test_transactions_v2_browser.py`, `test_family_browser.py`, `test_receipt_counting.py` |
| `#/bills` | `loadBillsV2` → `bills_v2.js` | `#bills2-panel` | "Bills v2" | `test_bills_v2_browser.py` |
| `#/accounts` | `loadAccountsV2` → `accounts_v2.js` (`finance.js` `ACCOUNT_GROUPS`) | `#accounts2-panel` | "Accounts v2" | `test_accounts_v2_browser.py` |
| `#/taxes` | `loadTaxesV2` → `taxes_v2.js` (`taxes.js`: tax tags, CPA pack, Tax Zen form, rules) | `#taxes2-panel` | "Taxes v2" | `test_taxes_v2_browser.py` |
| `#/investments` | `loadInvestmentsV2` → `investments_v2.js` (`investments.js`: account builders, `inv2Reload` after a save) | `#inv2-panel` | "Investments v2", "Investments" | `test_investments_v2_browser.py` |
| `#/forecast` | `loadForecastV2` → `forecast_v2.js` (`forecast.js` on the `fc2-` inputs; SVG from `finance/charts.py`) | `#fc2-panel` | "Forecast v2", "Forecast's shared parts" | `test_forecast_v2_browser.py` |
| `#/whatif` | `loadWhatIfV2` → `whatif_v2.js` (`whatif.js` on the `wi2-` inputs) | `#wi2-panel` | "What If v2", "What If:" | `test_whatif_v2_browser.py` |
| `#/inventory` | `loadInventoryV2` → `inventory_v2.js` (`inventory.js`: check-in, `lotMenu`, warranty dialog) | `#it2-panel` | "Inventory v2", "Inventory and check-in." | `test_inventory_v2_browser.py` |
| `#/documents`, `#/receipts` | `loadRecordsV2` → `records_v2.js` (`library.js`: states, dialogs, nav counts) | `#rc2-panel` | "Records v2" | `test_records_v2_browser.py`, `test_browser.py`, `test_document_search_browser.py` |
| `#/documents/ID` | `openDocumentV2` → `document_v2.js` (`receipt.js`: record builders; `trace.js` viewer and decision) | `#doc2-panel` | "Document page v2", "Source viewer", "Confirm and correct" | `test_document_v2_browser.py`, `test_browser.py`, `test_record_components_browser.py` |
| `#/search` | `loadSearchV2` → `search_v2.js` (`search.js`: sidebar box, shortcuts, `matchSnippet`) | `#se2-panel` | "Search v2", "Search" | `test_search_v2_browser.py`, `test_document_search_browser.py` |
| `#/processing` | `loadProcessingV2` → `processing_v2.js` (`processing.js`: `JOB_KINDS`, `LANES`) | `#pr2-panel` | "Processing v2" | `test_processing_v2_browser.py`, `test_browser.py` |
| `#/settings` | `showSettingsTab` → `shell.js`; forms in `app.js`, `profiles.js`, `processing.js` | `#settings-panel` | "Settings" | `test_settings_browser.py`, `test_family_browser.py` |
| `#/donate` | `openDonate` → `donate.js` | `#donate-panel` | "Donate documents" | `test_donate_browser.py` |
| Ask panel | `assistant.js` | `#assistant-panel` | "Assistant panel" | `test_search_v2_browser.py` |
| Shell, sidebar, nav | `shell.js`, `app.js` | `.nav-link[data-route]`, `#toasts` | "Shell", "Responsive" | `test_shell_browser.py` and every browser test |

## Shared helpers (reuse, don't re-create)
- `ui.js` has `icon()`, `amount()`, `dateText()`, `dateDisplay()`, `statusBadge()`/`setStatusBadge()` with the `STATUS` map,
  `asyncButton()`, `dataTable(columns, rows, {caption, className})`, `emptyState()`, `alertBox()`, `technicalDetail()`,
  `toast()`, `menu()`, `confirmAction()`, `kindSelect()` and `categoryLabel()`. `pageState(host, load, {loading, what,
  content, needsLibrary})` gives a page its loading, error (with Retry) and no-library states in a `.page-state` host
  after its header; `setStatusBadge()`/`statusBadge()` take an optional 4th `label` that keeps the status's tone and
  icon.
- `trace.js` (docs/ui.md "Observability components"): `figure(fig, {size})` for any traced figure, `fitFigures(row)`, the
  shared breakdown panel (`openBreakdown(ref, opener)`, `drillBreakdown`, `backBreakdown`, `closeBreakdown`;
  `<aside id="breakdown">`), `provenanceBadge(prov)`, `ruleCard(rule)`, `confirmCorrect`, `sourceViewer` and
  `historyList`. A screen with traced figures adds its route to `TRACED` in `tests/test_ui_parity.py`, whose
  `check_figures()` it reuses.
- DOM factories: `element()` and `cell()` in `app.js`, and `homeLink()` in `home.js`.
- Icons come from `icons.svg` through `icon(name)`.
- Charts: the `--chart-*` tokens, `categorySlot()` in `home.js`, and the server-drawn SVG in
  `src/home_manager/finance/charts.py`.

## Getting a page's selector contract
Run these with the Grep tool (`output_mode: content`). Don't print whole files.
- Ids the tests use: pattern `locator\("#[\w-]+` in the test files from the table, or `#<prefix>-` for a page
  (e.g. `#donate-`, `#inv2-`).
- Classes and roles the tests use: patterns `locator\("\.[\w-]+` and `get_by_role\(` in those files.
- Ids the JS looks up: pattern `\$\("[\w-]+"\)` in the page's JS file and its shared builder file.

Any id or class in these results is part of the contract. Keep it, or list the rename and the test edit it needs in the
plan.
