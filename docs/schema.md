# Library database schema map

Status: reference, current through migration 047 (2026-09-30).

Each library holds one SQLite database, `inventory.sqlite3`. It is built by the forward-only scripts in `src/home_manager/library/migrations/`. The `NNN_` prefix of each script matches `PRAGMA user_version`. How upgrades run, the copies taken before each one, and how to recover from a failed upgrade are in [managed library](managed-library.md). How to add a migration is in [development](development.md).

This page lists what each migration adds. The `.sql` file is the source of truth for columns and constraints. A table that was later rebuilt (a `_new` table swapped in) is listed under the migration that first created it.

## Capture and documents (001–010)

| # | File | Tables added | Columns added / notes |
|---|---|---|---|
| 001 | `inventory` | `jobs` (scan jobs), `blobs` (content-addressed originals), `occurrences` (a document at a path), `versions`, `events`, `capture_intents` (durable intent to publish a captured file; replayed at start) | |
| 002 | `receipts` | `parse_runs` (vision transcription runs) | |
| 003 | `batches` | `receipt_batches`, `receipt_batch_items` ("Read all documents" batches) | |
| 004 | `library` | `document_folders`, `library_events` | `occurrences.deleted_at`; `jobs.organization_status`, `organization_message`, `organization_batch_id` |
| 005 | `organization` | `organization_runs` | |
| 006 | `reasoning` | `reasoning_runs` ([financial reasoning](financial-reasoning.md)) | |
| 007 | `flat_document_folders` | `folder_aliases` (old nested folder names → flat ones) | |
| 008 | `managed_library` | `managed_files`, `managed_organization_intents`, `managed_organization_events` ([managed library](managed-library.md)) | `occurrences.source_kind` |
| 009 | `reviews` | `analysis_reviews` (the independent reviewer's results; see [assistant](assistant.md)) | |
| 010 | `model_runs` | `model_identities`, `model_runs` (provenance for every model call) | `parse_runs.model_identity`, `reasoning_runs.model_identity` |

## Ledger (011–020)

| # | File | Tables added | Columns added / notes |
|---|---|---|---|
| 011 | `finance` | `merchants`, `accounts`, `statements`, `transactions`, `receipts`, `receipt_items`, `bills`, `income_records`, `recurring_obligations`, `financial_evidence_links`, `review_events` | The ledger core. See [receipts and statements](receipts-and-statements.md). |
| 012 | `extraction` | `extraction_runs` (typed extraction to the ledger) | |
| 013 | `transaction_imports` | `transaction_imports` (CSV/XLSX imports) | |
| 014 | `reconciliation` | `transaction_receipt_links`, `transaction_links` (transfers, refunds), `reconciliation_issues` | |
| 015 | `review_operations` | `reconciliation_runs`, `backups`, `assistant_runs` | `bills.payment_transaction_id`, `reconciliation_issues.resolution` |
| 016 | `descriptions` | `document_descriptions` | `receipts.description` |
| 017 | `record_corrections` | `record_corrections` (the user's corrections to receipts, bills and income records) | `reconciliation_runs` rebuilt |
| 018 | `review_source` | | `review_source` on `statements`, `transactions`, `receipts`, `bills`, `income_records` |
| 019 | `receipt_location` | | `receipts.location` (store city, or Online) |
| 020 | `trash_cleanup` | `trash_cleanup` (file deletions queued with a permanent delete; retried at start) | |

## Household, budgets and money rules (021–035)

| # | File | Tables added | Columns added / notes |
|---|---|---|---|
| 021 | `household_items` | `products`, `item_aliases`, `item_resolutions`, `inventory_lots`, `lot_events`, `item_resolution_runs`, `web_search_cache` | [household items](household-items.md) |
| 022 | `assets` | `assets` (assets and loans for the forecast) | [forecast](forecast.md) |
| 023 | `budgets` | `category_rules`, `budgets`, `checkin_runs` | `transactions.category_source`, `category_rule_id`. See [money, review and inventory](money-review-inventory.md). |
| 024 | `returns_assets` | `return_policies` | `inventory_lots.opened_on`; `receipts.return_days_printed`, `return_policy_quote`; `assets.blob_hash`, `extraction_run_id`, `account_key`, `validation_json`; `lot_events` rebuilt. See [items, assets and search](items-assets-search.md). |
| 025 | `warranties` | `warranties`, `warranty_runs` | [warranties](warranties-assistant-processing.md) |
| 026 | `receipt_counting` | | `receipts.category`, `statements.reconciliation`. Receipts count on their own until a statement line replaces them. |
| 027 | `utilities_into_housing` | | Data only: the utilities category merged into housing. |
| 028 | `recurring_bills` | | `receipts.recurrence`; `recurring_obligations` rebuilt |
| 029 | `money_and_documents` | | Data only: bills no longer tracked; the Bills folder retired (its files move to Unfiled at start). |
| 030 | `model_recurring_bills` | `payee_recurrence` | `recurring_obligations.source_document_id`, `evidence` (bills proposed from contracts and statement payees) |
| 031 | `jobs` | `employers`, `job_filings`, `income_lines`, `tax_tables`, `tax_table_runs` | `income_records.gross_pay_ytd_minor`, `net_pay_ytd_minor`, `work_state`, `pay_frequency`. See [jobs and paystubs](jobs-and-paystubs.md). |
| 032 | `item_categories` | `category_splits` (a receipt's or charge's money divided by item category), `item_category_memory` | `receipt_items.taxed`, `category_source` |
| 033 | `receipt_rewards` | `receipt_rewards` | |
| 034 | `finer_categories` | | `receipt_items.category_source` rebuilt to allow `legacy` (the "shopping" category split up) |
| 035 | `family_shares` | `record_shares`, `family_assignments` (the family inbox's routing) | `receipts.payment_last_four`. See [sharing](sharing.md). |

## Investments, search, planning and taxes (036–047)

| # | File | Tables added | Columns added / notes |
|---|---|---|---|
| 036 | `investments` | `investment_kinds`, `investment_accounts`, `holdings`, `investment_valuations`, `investment_events` | [investments](investments.md) |
| 037 | `investment_links` | | Indexes only: a ledger savings account links to at most one investment account. |
| 038 | `investment_confirmations` | `investment_confirmations` | `holdings.face_minor`, `redeemable_date`, `rollover`, `source`, `confirmation_id`; `investment_events.confirmation_id` |
| 039 | `investment_contributions` | | `investment_accounts.payroll_merchant_id`, `payroll_link`, `monthly_contribution_minor` |
| 040 | `tax_lots_forms` | `tax_lots`, `tax_forms`, `tax_form_boxes` | |
| 041 | `investment_payment_links` | `investment_payment_rejections` ("Not this payment") | `investment_events.transaction_link`, `transaction_previous_type` (for undo) |
| 042 | `document_text` | `document_passages`, `document_passages_fts` (FTS5), `document_index_state` | [document search](document-search.md) |
| 043 | `scenarios` | `scenarios` | [What If](what-if.md) |
| 044 | `scenario_adoption` | | `scenarios.adopted_month` |
| 045 | `tax_tags` | `businesses`, `tax_rules`, `tax_tags` | [taxes](taxes.md) |
| 046 | `tax_figures` | `tax_figure_sets`, `tax_years` | Figure lookups reused `tax_table_runs`. The lookup was retired on 2026-10-04 (Engine 1 carries its own law); `tax_figure_sets` is kept, unused. |
| 047 | `tax_units` | `tax_units` (who files together; kept in the family's own library) | |
| 048 | `recurring_kind` | | `recurring_obligations.kind`: `bill` or `subscription`, suggested from the category and set by the user |
| 049 | `audit_cleanup` | | Fixes from the [database audit](../db_audit_report.md): removes `record_shares` and `family_assignments` rows whose record is gone; ISO timestamps on the seeded `return_policies`; indexes for per-row lookups on links, organization intents, reconciliation issues, a statement's transactions and a document's extractions; drops the unused `bills.bill_type` and `investment_valuations.vested_minor` |
| 050 | `strict_tables` | | Every table rebuilt `STRICT` (the full-text index excepted), so a wrong-typed value is refused. Adds `CHECK`s on run and job states (`jobs`, `receipt_batches`, `parse_runs`, `reasoning_runs`, `extraction_runs`, `managed_organization_intents`), `occurrences.source_status`/`source_kind`, `tax_rules.kind`, `investment_events.transaction_previous_type`, and the booleans `accounts.active` and `receipt_batch_items.reused`. Unknown run states become `interrupted` first. Generated from the version 49 schema. |
| 051 | `exchange_rates` | `fx_rate_sets`, `fx_rates` | [Currency conversion](currency-conversion.md). ECB downloads and the rates they brought, stored once per date and currency as decimal text; triggers refuse updates and deletes. Adds `transaction_receipt_links.estimate_rate_id`/`estimate_minor` (a foreign receipt's reference estimate, kept as provenance when its USD charge counts). |
| 052 | `generated_reports` | `generated_reports` | The year-end CPA pack ([taxes](taxes.md#cpa-pack)): file path under `Reports/`, SHA-256, manifest, and the request key (year + data fingerprint) that makes a rebuild from unchanged data return the same file. |
| 058 | `tax_calculations` | `tax_calculations` | Each distinct return a tax engine worked out, per year, filing unit, engine implementation, version and profile; never rewritten ([tax engines](tax-engines.md)). |
| 059 | `form_1098` | | `tax_form_boxes.form` allows `1098` (mortgage interest, Jan 1 principal, property tax) for the year's return. |
| 060 | `tax_zen_evaluations` | `tax_zen_evaluations` | What Tax Zen said for a return and why (status, likely range, W-4 answer, the figures it rested on, what changed), added only when something changed; `seen_at` clears Home's notice ([taxes](taxes.md)). |

## Runs and startup recovery

Tables named `*_runs` record model or lookup work with a status. When a library opens, each service's `recover()` marks a run that was still `queued` or `running` as `interrupted`, and the user can retry it. Capture intents, managed-organization intents and trash cleanup are replayed instead. See [operations](operations.md#background-work).
