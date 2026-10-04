# The assistant, its tools and the independent reviewer

Status: built (reference, 2026-09-30). Code: `finance/assistant.py`, `finance/tools.py`, `household/analysis.py`, `documents/reviewer.py`.

## How a question is answered

The assistant (the Ask panel) runs on the configured **reasoning model**. The model never reads files, computes a total of record or writes anything. It picks read-only tools, reads their results and explains them.

1. **Route.** Before any model call, `route()` in `finance/assistant.py` sorts the question with fixed word lists:
   - `documents`: what a document says (policy, coverage, lease, contract, warranty, vesting, "according to"…).
   - `items`: products, prices, stock, running out, waste.
   - `finance`: everything else.

   Each route offers the model a smaller tool list (below), so a small model's prompt stays short.
2. **Tool calls.** The model may make at most 6 tool calls (`MAX_TOOL_CALLS`). Each result is capped at 24,000 bytes. Tool results are data, never instructions.
3. **Answer check.** Every money-like figure in the answer (anything with a decimal point or thousands separators) must appear in the results of the tool calls the answer cites. A figure that doesn't is marked unverified rather than stated as fact. Cited document lines are kept only when a cited call returned them.
4. **Record.** Each question is an `assistant_runs` row. A run still in progress when the app stops becomes `interrupted` at the next start.

## Ledger tools (`TOOLS` in `finance/tools.py`)

| Tool | What it returns |
|---|---|
| `get_accounts` | Accounts in the ledger. |
| `get_account_balance` | One account's balance. |
| `get_transactions` | Transactions in a period (counted, optionally pending). |
| `find_purchase` | The same as `get_transactions`; a name that suits purchase questions. |
| `get_spending` | Counted spending in a period, per currency. |
| `spending_series` | Monthly counted spending per currency; months with no data are listed empty. |
| `get_spending_by_category` | Spending in a period by category. |
| `get_spending_items` | Counted spending one item per row, like an itemized statement. |
| `compare_periods` | Net spending in two periods and the change. |
| `compare_categories` | Per-category spending in two periods, with the exact change. |
| `calculate_cashflow` | Money in and out over a period. |
| `get_budgets` | Each monthly budget against the month's counted category spending, with the pace so far. |
| `get_categories` | Every category in use (transactions, receipt items, budgets, rules), with its transaction count. |
| `get_recurring_obligations` | Recurring payments and their merchants, each a bill or a subscription (`kind`, optional filter), with monthly and yearly totals per kind. |
| `get_upcoming_bills` | Confirmed recurring payments (bills and subscriptions, with `kind`) by next due date. |
| `find_receipt` | Receipts matching a search (rejected ones excluded). |
| `get_unmatched_receipts` | Receipts in a period that no card or bank line matches yet. |
| `get_statement` | One statement record. |
| `match_receipt_to_transaction` | One receipt's existing links, plus charges of the same amount and currency dated within `RECEIPT_POSTING_DAYS` (5) after the purchase. |
| `get_refunds` | Credits and the purchases they are linked to. |
| `review_queue` | Everything awaiting a decision, with display summaries. |
| `get_inventory` | Household items from approved receipt lines; in stock unless closed ones are asked for. |
| `search_documents` | Passages of saved document text containing the words, best first ([document search](document-search.md)). |
| `get_document_text` | Consecutive lines of one document's saved text, to read around a search hit. |
| `lookup_exchange_rate` | The cached ECB rate for a currency and date into USD, with its `rate_id`; `unavailable` with a reason when there is none. Never downloads ([currency conversion](currency-conversion.md)). |
| `convert_document_amount` | A receipt's total in USD at exactly a `rate_id` from `lookup_exchange_rate`; refuses an unknown id, another currency or another date. Marked provisional for an unapproved receipt, and names the matched card charge that counts instead. |

## Item tools (`ITEM_TOOLS` in `household/analysis.py`)

See [household items](household-items.md) and [items, assets and search](items-assets-search.md).

| Tool | What it returns |
|---|---|
| `get_item_spending` | What approved receipt items cost in a period, with the products that cost most. |
| `item_price_history` | Every approved purchase of matching products, with the price per standard unit where the size is readable. |
| `get_price_changes` | Largest rises in price per standard unit between first and last purchase in a period. |
| `compare_merchant_prices` | Each merchant's latest unit price for matching products, cheapest first. |
| `get_consumption_cost` | Cost per day and per 30 days, from finished lots. |
| `get_waste` | Thrown-out items closed in a period and what they cost. |
| `forecast_consumables_spend` | Projected cost of consumables in a month. |

`ANOMALY_TOOLS` adds `detect_spending_anomalies`: categories and merchants whose counted spending in a period is well above their usual average.

## Which tools each route sees

| Route | Tools |
|---|---|
| `documents` (`DOCUMENT_ROUTE`) | `search_documents`, `get_document_text`, `get_accounts`, `get_recurring_obligations`, `get_upcoming_bills`, `find_receipt` |
| `items` (`ITEM_ROUTE`) | all item tools, `get_inventory`, `get_spending`, `get_spending_by_category`, `get_transactions`, `find_receipt`, `search_documents` |
| `finance` (`FINANCE_ROUTE`) | every ledger tool except `get_document_text`, plus `detect_spending_anomalies` |

`search_documents` is in every route. It is the fallback for anything the ledger doesn't hold.

## Web lookup agents

Separate small agents use the reasoning model with their own tool sets. Each one ends by *proposing* an answer for review in the app and never saves one directly. They share the web connectors in `models/web_lookup.py`: Brave Search (needs `HOME_MANAGER_BRAVE_API_KEY`), Open Food Facts for barcodes, and result pages, with results cached for 30 days in `web_search_cache`.

| Agent | Code | Tools | Doc |
|---|---|---|---|
| Item identification | `household/resolver_tools.py` | `get_receipt_line`, `find_similar_lines`, `lookup_barcode`, `web_search`, `open_result`, `find_in_page`, `propose_item_resolution` | [household items](household-items.md) |
| Warranty lookup | `household/warranty.py` | `get_item`, `web_search`, `open_result`, `find_in_page`, `propose_warranty` | [warranties](warranties-assistant-processing.md) |
| Paycheck tax tables | `household/tax_tables.py` | `web_search`, `open_result`, `find_in_page`, `propose_tax_table` | [jobs and paystubs](jobs-and-paystubs.md) |

## The independent reviewer ("Independent checks")

Configured in **Settings → Local models** and saved as `reviewer.json` (`ReviewerConfig`, API `PUT /api/reviewer-settings`). There are three providers:

- `off` (the default).
- `chat`: a second loopback chat model. It gets the transcription and the proposed analysis. It checks the classification, omitted or invented items, amounts, dates, currency and unsupported claims, and cites exact source text for each problem. A review that cites text not in the transcription, or whose verdict contradicts its findings, is rejected. Input is capped at 96 KiB and is never truncated.
- `decision`: the [decision model](decision-models.md) chosen in Settings scores each claim against its cited text. Scores below `SUPPORT_THRESHOLD` become findings. It is advisory: a failed or doubtful decision review never blocks filing. A saved `laya` setting reads as `decision`.

**When it runs:** after a successful [financial reasoning](financial-reasoning.md) run (`Manager.reason_and_file`), before the document is filed. The result is saved in `analysis_reviews`. A failed review leaves the analysis unreviewed.

**What it never does:** approve or change records. "No issues found" is not proof of correctness.

Typed extraction uses the decision model separately, on every extraction, as a veto that sends a record to review; see [decision models](decision-models.md).

On a [family GPU computer](shared-gpu-plan.md), members ask for the `home-manager/reviewer` role. It maps to the host's reviewer chat model, or to its reasoning model if none is set.
