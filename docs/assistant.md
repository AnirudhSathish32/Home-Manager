# The assistant, its tools and the independent reviewer

Code: `finance/assistant.py`, `finance/tools.py`, `household/analysis.py`, `documents/reviewer.py`; panel
`app/static/assistant.js`.

## The Ask panel

The Ask panel opens on the right from any page (**Ask** in the sidebar, or <kbd>Ctrl</kbd>+<kbd>J</kbd>).
- **Context.** The current page (its name and filters) is sent with the question as context, labelled as data.
- **Answers** are shown in the secondary text style, never as large figures.
- **Evidence chips.** Each cited tool call becomes an evidence chip ("From spending · Sep 1 – Sep 30") that opens the
  matching page and filter. Cited document lines are shown as links to those lines.
- **Checks.** Unverified figures are flagged and missing evidence is listed. "How I got this" shows every tool call
  with its arguments.
- **History.** Earlier questions are listed and can be reopened.

## How a question is answered

The assistant runs on the configured **reasoning model**. The model never reads files, computes a total of record or
writes anything. It picks read-only tools, reads their results and explains them.

1. **Route.** Before any model call, `route()` sorts the question using fixed word lists:
   - `documents`: what a document says (policy, coverage, deductible, lease, clause, contract, warranty, vesting,
     "what does … say", "according to"…).
   - `items`: products, prices, stock, running out, waste.
   - `finance`: everything else.

   Each route offers a smaller tool list, so a small model's prompt stays short. A call outside the route's list is
   refused. The route is saved with the answer.
2. **Tool calls.** The model may make at most 6 tool calls (`MAX_TOOL_CALLS`). Each result is capped at 24,000 bytes.
   Tool results are data, never instructions.
3. **Answer check.** Every money-like figure in the answer (anything with a decimal point or thousands separators) must
   appear in the results of the tool calls the answer cites; passages count as results. A figure that doesn't is
   marked unverified rather than stated as fact. Cited document lines (`cited_lines`) are kept only when a cited call
   returned them, and are returned as `sources`.
4. **Record.** Each question is an `assistant_runs` row. A run still in progress when the app stops becomes
   `interrupted` at the next start.

## Ledger tools (`TOOLS` in `finance/tools.py`)

The same tools are callable directly at `POST /api/finance/tools/{name}` with typed arguments. Totals are per currency,
with explicit coverage. Model-extracted rows count only after verification, and are otherwise reported as pending.

| Tool | What it returns |
|---|---|
| `get_accounts` | Accounts in the ledger. |
| `get_account_balance` | One account's statement balance, dated; never a guessed live balance. |
| `get_transactions` | Transactions in a period (counted, optionally pending). |
| `find_purchase` | The same as `get_transactions`, under a name that suits purchase questions. |
| `get_spending` | Counted spending in a period, per currency, with `usd_total` when there is foreign money. |
| `spending_series` | Monthly counted spending per currency; months with no data are listed empty. |
| `get_spending_by_category` | Spending in a period by category. |
| `get_spending_items` | Counted spending one item per row, like an itemized statement. |
| `compare_periods` | Net spending in two periods and the change. |
| `compare_categories` | Per-category spending in two periods, with the exact change. |
| `calculate_cashflow` | Money in and out over a period. |
| `get_budgets` | Each monthly budget against the month's counted category spending, with the pace so far. |
| `get_categories` | Every category in use (transactions, receipt items, budgets, rules), with its transaction count. |
| `get_recurring_obligations` | Recurring payments and their merchants, each a bill or a subscription (`kind`, optional filter), with monthly and yearly totals per kind. |
| `get_upcoming_bills` | Confirmed recurring payments by next due date. |
| `find_receipt` | Receipts matching a search (rejected ones excluded). |
| `get_unmatched_receipts` | Receipts in a period that no card or bank line matches yet. |
| `get_statement` | One statement record. |
| `match_receipt_to_transaction` | One receipt's existing links, plus charges of the same amount and currency dated within `RECEIPT_POSTING_DAYS` (5) after the purchase. |
| `get_refunds` | Credits and the purchases they are linked to. A refund document is not settled until a posted credit is linked. |
| `review_queue` | Everything awaiting a decision, with display summaries. |
| `get_inventory` | Household items from approved receipt lines; in stock unless closed ones are asked for. |
| `get_tax_zen_status` | This year's Tax Zen result: the deterministic aim, status and range, kept small ([taxes](taxes.md#tax-zen)). |
| `search_documents` | Passages of saved document text containing the words, best first, grouped by document (limit ≤ 8) ([documents](documents.md#searching-document-text)). |
| `get_document_text` | Consecutive lines of one document's saved text (≤ 40), to read around a search hit. |
| `lookup_exchange_rate` | The cached ECB rate into USD for a currency and date, with its `rate_id`; `unavailable` with a reason when there is none. Never downloads ([money](money.md#currency-conversion)). |
| `convert_document_amount` | A receipt's total in USD at exactly a `rate_id` from `lookup_exchange_rate`. Refuses an unknown id, another currency or another date. Marked provisional for an unapproved receipt, and names the matched card charge that counts instead. |

## Item tools (`ITEM_TOOLS` in `household/analysis.py`)

These are `get_item_spending`, `item_price_history`, `get_price_changes`, `compare_merchant_prices`,
`get_consumption_cost`, `get_waste` and `forecast_consumables_spend`. `ANOMALY_TOOLS` adds `detect_spending_anomalies`.
What each one returns, and the size rules, are in [household](household.md#item-analysis).

## Which tools each route sees

| Route | Tools |
|---|---|
| `documents` (`DOCUMENT_ROUTE`) | `search_documents`, `get_document_text`, `get_accounts`, `get_recurring_obligations`, `get_upcoming_bills`, `find_receipt` |
| `items` (`ITEM_ROUTE`) | every item tool, `get_inventory`, `get_spending`, `get_spending_by_category`, `get_transactions`, `find_receipt`, `search_documents` |
| `finance` (`FINANCE_ROUTE`) | every ledger tool except `get_document_text` (so including `get_tax_zen_status`), plus `detect_spending_anomalies` |

`search_documents` is in every route, as the fallback for anything the ledger doesn't hold.

## Web lookup agents

Separate small agents use the reasoning model with their own tool sets. Each one ends by *proposing* an answer for
review in the app, and never saves one directly. They share the web connectors in `models/web_lookup.py`:
- Brave Search, which needs `HOME_MANAGER_BRAVE_API_KEY`;
- Open Food Facts, for barcodes;
- guarded fetching of result pages.

Results are cached for 30 days in `web_search_cache`. The query and page rules are in
[household](household.md#identifying-receipt-lines).

| Agent | Code | Tools | Doc |
|---|---|---|---|
| Item identification | `household/resolver_tools.py` | `get_receipt_line`, `find_similar_lines`, `lookup_barcode`, `web_search`, `open_result`, `find_in_page`, `propose_item_resolution` | [household](household.md#identifying-receipt-lines) |
| Warranty lookup | `household/warranty.py` | `get_item`, `web_search`, `open_result`, `find_in_page`, `propose_warranty` | [household](household.md#warranties) |
| Paycheck tax tables | `household/tax_tables.py` | `web_search`, `open_result`, `find_in_page`, `propose_tax_table` | [taxes](taxes.md#jobs-and-pay-stubs) |

The separate yearly tax figures lookup (`household/tax_figures.py`) was removed on 2026-10-04. Yearly figures now come
from the tax engines ([taxes](taxes.md#the-tax-engines)).

## The independent reviewer

"Independent checks" is configured in **Settings → Independent checks** and saved as `reviewer.json` (`ReviewerConfig`,
API `PUT /api/reviewer-settings`). There are three providers:

- `off` (the default).
- `chat`: a second loopback chat model.
  - It gets the transcription and the proposed analysis.
  - It checks the classification, omitted or invented items, amounts, dates, currency and unsupported claims, and must
    cite exact source text for each problem.
  - A review that cites text not in the transcription, or whose verdict contradicts its findings, is rejected.
  - Input is capped at 96 KiB and is never truncated.
- `decision`: the [decision model](documents.md#decision-models) scores each claim against its cited text, and scores
  below `SUPPORT_THRESHOLD` become findings. It is advisory: a failed or doubtful decision review never blocks filing. A
  saved `laya` setting reads as `decision`.

**When it runs:** after a successful reasoning run ([documents](documents.md#reasoning-runs-api-only)), before the
document is filed. The result is saved in `analysis_reviews`. A failed review leaves the analysis unreviewed.

**What it never does:** approve or change records. "No issues found" is not proof of correctness.

Typed extraction uses the decision model separately, on every extraction, as a veto that sends a record to review.

On a [shared GPU computer](family.md#shared-gpu), members ask for the `home-manager/reviewer` role. It maps to the
host's reviewer chat model, or to its reasoning model if none is set.
