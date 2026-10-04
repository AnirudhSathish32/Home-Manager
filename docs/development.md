# Developing Home Manager

This doc covers code layout, architecture rules, tests, manual checks, code checks, migrations, the schema map and
database checks. Setup, commands and the layout on disk are in [operations](operations.md). The index of every doc is
in [docs/README.md](README.md).

## Layout

`src/home_manager/` is grouped by responsibility. Package `__init__.py` files are empty, and modules import each other
directly (`from ..core.money import format_minor`). `__main__.py` is the launcher: `home-manager`, `gpu-host`,
`check-ledger` and `index-documents`.

| Package | Holds |
|---|---|
| `core/` | Foundations with no domain knowledge: money, formats, folders, categories, paths and locks, the work queue (`jobs.py`), worker limits, the log, donation answers (`answers.py`). |
| `library/` | The document store and its lifecycle: `storage.py` and `migrations/`, scanning and capture, the managed Library and filing, backups, shares, trash, the text index. |
| `models/` | Model transport (`model_client.py`, `model_stream.py`), residency, decision models, vision settings, the family GPU relay, `http_server.py` (`GracefulHTTPServer`), web lookup connectors. |
| `documents/` | Reading documents into evidence and records: image and PDF readers, regions and image grouping, vision transcription, reasoning runs, typed extraction, the reviewer, donations. |
| `finance/` | Ledger, reconciliation, splits, tools and the assistant, budgets and check-ins, the dashboard, forecast and charts, investments, lots and retirement, prices and FX, paychecks and scenarios, taxes (tags, year, return, engine, safe harbor, Tax Zen, withholding, family), the CPA pack, health checks. |
| `finance/engines/` | Tax engine adapters: `opentax.py` (Engine 1), `taxcalc.py` and `taxcalc_run.py` (Engine 2, in its own process). |
| `household/` | Items and inventory, item identification, item analysis, warranties, paycheck tax-table lookups. |
| `app/` | FastAPI app (`api.py`), `Manager` (queues and wiring), profiles, family sync, the CLI subcommands, and `static/` (the UI). |
| `vendor/` | The pinned OpenTax bundle (`vendor/opentax/`, never edited) and `NOTICES.md`. |

Outside `src/`:
- `tests/`: flat pytest modules, synthetic data only;
- `evals/`: the eval suite ([evals](evals.md));
- `scripts/`: `db_checks.py` and `loopback_stress.py`;
- `docs/`.

## Architecture rules

Home Manager is a modular Python monolith. FastAPI serves a loopback API and the UI. Deterministic domain services own
the financial rules. Two work queues (capture and inference) run background jobs. A separately operated local model
server provides the models. There are no microservices, no message broker and no agent swarm.

| Component | Owns | Must not do |
|---|---|---|
| Assistant / agents | Interpreting the question, choosing tools, bounded workflow state, composing a grounded answer | SQL, arbitrary code or shell, filesystem access, credentials, financial arithmetic, authorization |
| Tools | Typed request/result schemas, argument validation, policy, dispatch to services, stable errors | Put business rules in prompts, or bypass services |
| Domain services (`finance/`, `household/`) | Money and date semantics, calculations, matching rules, coverage, validation | Depend on FastAPI or model clients |
| Store and migrations | Parameterized persistence, constraints, transactions, provenance | Treat chat history as financial records |
| Ingestion (`library/`, `documents/`) | Immutable capture, reading, staged extraction, deduplication, retries | Run document content, grant permissions, silently promote model guesses |
| Model adapters (`models/`) | Protocol normalization, capability checks, timeouts, residency | Hold source credentials or call tools themselves |
| API (`app/`) | Session auth, Host/Origin checks, request limits, schema validation, job lifecycle, review commands | Reimplement calculations, or accept model assertions as authorization |

Principles:
- **Read-only tools.** The assistant and agents only read. Their single write is a proposal that waits for review.
- **Models propose, people decide.** Model output is stored as proposed until a deterministic check or a person accepts
  it. A model-produced "yes" can't approve anything.
- **Document content is untrusted.** It is passed as data, never as instructions. Links read from documents are shown
  as text.
- **No cloud fallback,** no remote embeddings, no hosted OCR, no hosted tracing. A missing local model gives an
  actionable error.
- **Future actions that change things in the world** (paying, sending, deleting) would need a separate command service.
  It would produce a concrete proposal, show the target and effect, bind a single-use approval to exact arguments,
  revalidate, and audit. None exists; money movement, email sending and model-initiated deletion are deliberately left
  out.
- **No vector database,** multi-agent system or distributed queue until a measured shortcoming calls for one. Keyword
  search (FTS5) covers prose documents ([documents](documents.md#searching-document-text)).

**Security controls**

| Risk | Control |
|---|---|
| Prompt injection in documents | Content is untrusted evidence, separate from instructions; allowlisted typed tools; no arbitrary execution |
| Exfiltration through URLs or model settings | Loopback model endpoints (or the tailnet relay); no model-supplied fetch URLs; outbound network only in named connectors (Brave, Open Food Facts, ECB, CoinGecko) |
| Browser attacks on localhost | Session token in the URL fragment, Host/Origin validation, strict CSP, loopback bind only |
| Household access | Profiles separate libraries but aren't access control ([family](family.md#profiles)); families exchange only encrypted files through a folder |
| Malicious files and parsers | Size, page, pixel and time limits; bounded child processes; no macros, scripts or formula evaluation. OS-level confinement is still open ([open work](open-work.md)) |
| Path traversal | Opaque ids; root-confined paths; symlinks and reparse points rejected |
| Credential theft | The Brave key comes only from the environment; the GPU token lives in its own file, never in configs, prompts or logs |
| Disk and backup disclosure | Your own encrypted disk and backups; SQLite isn't encrypted at rest |
| Private trace leakage | Metadata-only logs; no document text, amounts, names or file names in logs or errors |
| Supply chain | Pinned dependencies; the vendored tax engine is hash-pinned and audited ([taxes](taxes.md#engine-1-opentax)) |
| Runaway work | Tool-call, result-size and time caps; one job per queue |
| Corrupted records | Constraints, `STRICT` tables, transactional imports, immutable originals, pre-upgrade copies, verified backups, ledger health |

**Privacy in logs** (`core/logs.py`): log event names, ids, counts and exception class names, never exception messages,
amounts, merchant names, file names or document text. Use `log_failure` for failures.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q                 # unit and API tests (78 test files)
.\.venv\Scripts\python.exe -m pytest -q --browser       # also the browser tests
.\.venv\Scripts\python.exe -m pytest -q --cov           # with coverage (needs .[dev])
```

- **Unit and API tests** need `.[test]`. They use a synthetic local model server (`tests/conftest.py` `local_model`,
  `tests/model_server.py`) and never contact a real model or the network. They use synthetic documents in temporary
  folders, never real financial data.
- **Tax engine tests.** Engine 1's tests need Node.js 20+, and Engine 2's need `.[engine2]`; each skips without its
  engine. Install both before changing anything in `finance/tax_*.py` or `finance/engines/`.
- **Browser tests** need `.[browser-test]`. They drive the installed **Microsoft Edge** through Playwright
  (`channel="msedge"`), so `playwright install` isn't needed.
  - They are skipped unless you pass `--browser` or set `RUN_BROWSER_TESTS=1`.
  - They live in `test_browser.py`, `test_document_search_browser.py`, `test_donate_browser.py`,
    `test_family_browser.py`, `test_home_browser.py`, `test_taxes_browser.py` and `test_whatif_browser.py`.
  - Some other test files also have browser cases: `test_employers`, `test_forecast`, `test_investments`,
    `test_receipt_counting`, `test_recurring_bills` and `test_share`.
  - Layout checks are described in the `app-ux` skill.
- **Decision models** (`test_decisions.py`) use the same synthetic server. Set `local_model["decide"]` to a function
  `(path, body) -> reply` that answers `/v1/responses` and `/v1/systemone`. Requests to those paths are kept in
  `local_model["decisions"]`, apart from chat requests.
- **Opt-in tests.** There are no custom pytest markers; opt-in tests use `skipif` on those variables.
- **Ledger health.** After a scenario that changes the ledger, call `conftest.assert_ledger_healthy(store)`.
- **Run what you touched.** When changing a component, run that component's tests rather than the whole suite.
- **Connection resets are bugs.** A connection reset in a loopback test is a bug now, not noise (see the next section).
- **Evals** have their own tests (`test_evals.py`, `test_eval_tasks.py`, `test_sampling.py`), on synthetic fixtures
  only.

## Windows loopback resets

Fixed 2026-10-01. For a long time a rare test failed with "Local model connection failed or disconnected"
(`ConnectionResetError`, WinError 10054) and passed on a rerun.

- **Symptom:** the client got the start of a reply (the `200` status line), waited about 19 s for the rest, then the
  connection was reset.
- **Cause:** on this Windows machine, a segment still in flight is sometimes lost when a server closes its socket (or
  sends FIN with `shutdown(SHUT_WR)`) right after a reply that spans several TCP segments. Python's `socketserver` does
  exactly that after every HTTP/1.0 reply. Small replies fit in one segment and were never hit.
- **Measured** with 40 KB replies, raw sockets, 600 transfers each:

  | How the server ends the reply | Lost |
  | --- | --- |
  | `shutdown(SHUT_WR)` then close | 8 |
  | close at once | 5 |
  | `shutdown` then wait for the client | very many (FIN right behind the data is the trigger) |
  | wait 0.2 s, then close | 0 |
  | wait for the client to close first | 0 |

  Through the synthetic model server, 16 of 1,000 requests failed, and the long-statement extraction test failed 4 of
  100 runs. The client's request was always delivered (57,000 requests up to 1 MB with no failure). It is unproven
  whether a filter driver is involved; the fix doesn't depend on it.
- **Fix:** `models/http_server.py` `GracefulHTTPServer`. After a reply, the server reads until the client closes (at
  most 10 s), and never sends FIN first. Every client of these servers closes first, after Content-Length or the
  stream's `[DONE]`.
  - Once the client has closed, the server closes with a reset (`SO_LINGER` 0). The client has read everything by then,
    and the reset leaves neither side in TIME_WAIT.
  - Without the reset, the client (now the side that closes first) keeps each port in TIME_WAIT for 2 minutes. That
    exhausted Windows' client ports at about 16,000 requests in 2 minutes (WinError 10048).
  - A client that never closes gets an ordinary close after 10 s.
  - The GPU host relay (`RelayServer`) and the tests' synthetic model server both use it. FastAPI/uvicorn, the app's
    own server, keeps connections alive and isn't affected. Tests: `tests/test_http_server.py`.
- **Checking it again:** `.\.venv\Scripts\python.exe scripts\loopback_stress.py --requests 20000 --response-bytes 40000`
  must report 0 failures. Use `--mode app` to go through `request_completion`. `--backlog 5` reproduces the old listen
  queue.
- **Any new HTTP server in this project,** test or product, should subclass `GracefulHTTPServer`.

## Manual checks

Use synthetic or copied documents and a scratch library. A scratch settings folder (`--control-dir`) keeps your real
profiles untouched.

**Capture**

| Action | Expected result |
| --- | --- |
| Drop supported files into Inbox | `captured` entries and hashes in the library |
| Scan again without editing anything | `unchanged`; no extra preserved blob or version |
| Drop identical bytes under a new file name | `duplicate`; same content hash and shared preserved bytes |
| Edit an Inbox file in place and rescan | `new_version`; Versions shows both hashes |
| Rename an Inbox file and rescan | The new occurrence reuses existing bytes; the old name becomes `missing` |
| Delete an Inbox file before it is filed, then rescan | `missing`; captures and earlier versions remain |
| Leave a `.part`, `.tmp` or `~$` file in Inbox | `ignored`, not captured |
| Add a legacy XLS or another unsupported extension | `unsupported`, visible in scan results; not captured |
| Put a folder inside Inbox | `invalid_folder`; subfolders aren't traversed |
| Keep an Inbox file open for writing | It may be `deferred` (Windows sharing); close the writer |
| Restart the app | Settings, inventory, versions and scan history persist |

- **Scan statuses.** `completed` means every supported file found was captured; it never means a month's finances are
  complete. `partial` means some entries were unsupported, invalid, deferred or rejected. `failed` means the scan
  couldn't finish, and missing-file detection isn't applied. `interrupted` means an earlier process ended mid-scan.
- **Default limits:** 256 MiB per file, 5 GiB of unique evidence, and 100,000 entries per scan (`library/scanner.py`).
  Every scan rereads and hashes supported files. Empty files are rejected.
- **Checking a preserved file.** The `originals/<2 hex>/<sha256>.blob` file holds exactly the captured bytes. Check it
  with `Get-FileHash -Algorithm SHA256 -LiteralPath '…'`.

**Features**

| Area | Check | Doc |
| --- | --- | --- |
| Reading and extraction | With vision and reasoning models set, drop a receipt image. It is read and recorded automatically, with cited values; a doubtful one waits in **Review**. | [documents](documents.md) |
| Several receipts, combined images | Drop a scan with two receipts side by side; each is recorded, and **Confirm split** clears the note. Drop `IMG_0012`/`IMG_0013` and combine them from Review. | [documents](documents.md#several-receipts-in-one-file) |
| Watched folders | Add a folder under Processing → Watched folders; a file dropped there is copied, and the folder is unchanged. | [documents](documents.md#watched-folders) |
| Decision model | Set one in Settings → Independent checks and use **Test connection**; an extraction shows its advisory scores. | [documents](documents.md#decision-models) |
| Statements and reconcile | Import a CSV/XLSX export, or drop a statement PDF. Its lines wait uncounted until you reconcile; matched receipts are then replaced by their card line. | [money](money.md) |
| Budgets, rules, recurring bills | Set a budget, categorize a line with a rule, confirm a proposed recurring bill; Home shows it under upcoming bills. | [money](money.md#category-rules-and-budgets) |
| Currency | With rates on, record a receipt in EUR; spending shows `usd_total`, and a USD card charge is offered as a match. | [money](money.md#currency-conversion) |
| Items, returns, warranties | Approve an itemized receipt; its lines appear in Inventory, with a return window and (after a lookup) a warranty. Lookups need `HOME_MANAGER_BRAVE_API_KEY`. | [household](household.md) |
| Search and Ask | Search for a word printed in a document; ask a spending question and a "what does my lease say…" question. | [assistant](assistant.md) |
| Jobs and pay stubs | Drop a pay stub; it files under `Jobs/<Employer>/Paystubs`, and its tax breakdown shows once the year's tax table is confirmed. | [taxes](taxes.md#jobs-and-pay-stubs) |
| Investments | Drop a brokerage statement and a trade confirmation; check holdings, lots, and **Not this payment** on a matched contribution. | [planning](planning.md#investments) |
| Forecast and What If | Add an asset and a loan; open the forecast. Save a plan, follow it, and check plan vs actual. | [planning](planning.md) |
| Taxes | Tag a business expense and an itemized deduction; open the year's estimate and Tax Zen. Build the CPA pack. | [taxes](taxes.md) |
| Profiles, family, sharing | Add a second profile; make a family and check the family view and inbox; export a `.hmshare` and open it. | [family](family.md) |
| Family GPU | Run `home-manager gpu-host serve`, `add-member`, and point another profile's Local models at it. | [family](family.md#family-gpu) |
| Donations | Check a receipt on Donate documents and export the bundle; open the zip and confirm nothing else is inside. | [evals](evals.md#donating-documents) |
| Backup and restore | **Back up** to another folder, then **Restore** into a new empty folder and switch to it. | [operations](operations.md#backups) |
| Ledger health | `home-manager check-ledger` while the app runs; it should report 0 errors. | [operations](operations.md#ledger-health) |

## Checks

Install with `.[dev]`. There is no CI, so run these before committing:

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests evals scripts   # likely bugs, current idioms, import order; no formatter
.\.venv\Scripts\python.exe -m mypy                                 # types in core, finance and library only
```

## Adding a migration

1. Add `src/home_manager/library/migrations/NNN_short_name.sql`, where `NNN` is one more than the highest number there.
   `MIGRATIONS` picks it up by name, and the package data in `pyproject.toml` already ships `migrations/*.sql`.
2. Start it with a comment saying what it is for and which doc covers it. End it with `PRAGMA user_version=NNN;`. The
   runner refuses a step that doesn't record its own number.
3. Don't write `BEGIN` or `COMMIT`. The runner wraps each script in one `BEGIN IMMEDIATE … COMMIT`. So a failed step
   rolls back whole, earlier steps are kept, and the next start retries.
4. SQLite can't change a `CHECK` constraint or drop some columns in place. Instead, build a `*_new` table, copy the
   rows, drop the old table and rename (see `024`, `028`, `034`, `050`, `056`).
   - Foreign keys are off while scripts run, so the `DROP TABLE` doesn't cascade-delete child rows. (Before this rule,
     a rebuild silently deleted child rows; the 2026-09-30 audit proved it.)
   - Recreate the table's indexes and triggers after the rename.
   - The runner runs `PRAGMA foreign_key_check` before committing, and refuses a step that leaves new broken
     references.
5. Every table is `STRICT` (since `050`). End each `CREATE TABLE … ) STRICT;`, and use only `INTEGER`, `REAL`, `TEXT`,
   `BLOB` or `ANY`.
   - Dates and JSON are `TEXT`. Money is `INTEGER` minor units. A boolean is `INTEGER … CHECK (x IN (0,1))`.
   - A state or kind gets a `CHECK (x IN (…))` listing every value the code writes.
   - A rebuilt table must stay `STRICT`. SQLite writes the renamed table's name quoted (`CREATE TABLE "receipts"`).
6. Upgrades are forward-only. Existing libraries get the new schema at their next start, after the app takes an
   `inventory.before-vNNN.sqlite3` copy ([documents](documents.md#schema-upgrades-and-recovering-from-a-failed-one)).
7. Backups record their `schema_version`. Don't renumber or edit a released migration.
8. If new work has a `*_runs` table, give its service a `recover()` that marks `queued`/`running` rows `interrupted`, and
   call it from `Manager.open_library`. If its status has a `CHECK`, list `interrupted` in it.
9. Test the feature against the new tables in the feature's own test file. `tests/test_migrations.py` covers the upgrade
   machinery (failed step, missing version, damaged database, table rebuilds, broken references).
10. Add the migration to the [schema map](#schema-map).

## Schema map

Each library holds one SQLite database, `inventory.sqlite3`, built by the forward-only scripts in
`src/home_manager/library/migrations/` (001–060). The `NNN_` prefix of each script matches `PRAGMA user_version`. The
`.sql` file is the source of truth for columns and constraints. A table that was later rebuilt is listed under the
migration that first created it.

**Naming.** `occurrences` is the documents table: `document_id` always means `occurrences.id`. `hash`, `blob_hash` and
`current_hash` are all a `blobs.hash`.
- **Typed references.** These tables point at records through `(record_type, record_id)` with no foreign key:
  `financial_evidence_links`, `reconciliation_issues`, `review_events`, `record_corrections`, `record_shares` and
  `family_assignments`. Emptying Trash cleans them up (`library/trash.py`), and the health check looks for orphans.
- **Reused ids.** Row ids are reused after a delete (no AUTOINCREMENT), so a leftover typed reference would attach to a
  new record.

**Capture and documents (001–010)**

| # | File | Tables added | Columns added / notes |
|---|---|---|---|
| 001 | `inventory` | `jobs` (scan jobs), `blobs` (content-addressed originals), `occurrences` (a document at a path), `versions`, `events`, `capture_intents` (durable intent to publish a captured file; replayed at start) | |
| 002 | `receipts` | `parse_runs` (readings) | |
| 003 | `batches` | `receipt_batches`, `receipt_batch_items` ("Read all documents" batches) | |
| 004 | `library` | `document_folders`, `library_events` | `occurrences.deleted_at`; `jobs.organization_*` |
| 005 | `organization` | `organization_runs` | |
| 006 | `reasoning` | `reasoning_runs` (reasoning runs, API only) | |
| 007 | `flat_document_folders` | `folder_aliases` (old nested folder names → flat ones) | |
| 008 | `managed_library` | `managed_files`, `managed_organization_intents`, `managed_organization_events` | `occurrences.source_kind` |
| 009 | `reviews` | `analysis_reviews` (the independent reviewer's results) | |
| 010 | `model_runs` | `model_identities`, `model_runs` (provenance for every model call) | `parse_runs.model_identity`, `reasoning_runs.model_identity` |

**Ledger (011–020)**

| # | File | Tables added | Columns added / notes |
|---|---|---|---|
| 011 | `finance` | `merchants`, `accounts`, `statements`, `transactions`, `receipts`, `receipt_items`, `bills`, `income_records`, `recurring_obligations`, `financial_evidence_links`, `review_events` | The ledger core ([money](money.md)) |
| 012 | `extraction` | `extraction_runs` (typed extraction) | |
| 013 | `transaction_imports` | `transaction_imports` (CSV/XLSX imports) | |
| 014 | `reconciliation` | `transaction_receipt_links`, `transaction_links` (transfers, refunds), `reconciliation_issues` | |
| 015 | `review_operations` | `reconciliation_runs`, `backups`, `assistant_runs` | `bills.payment_transaction_id`, `reconciliation_issues.resolution` |
| 016 | `descriptions` | `document_descriptions` | `receipts.description` |
| 017 | `record_corrections` | `record_corrections` (your corrections to records) | `reconciliation_runs` rebuilt |
| 018 | `review_source` | | `review_source` on `statements`, `transactions`, `receipts`, `bills`, `income_records` |
| 019 | `receipt_location` | | `receipts.location` |
| 020 | `trash_cleanup` | `trash_cleanup` (file deletions queued with a permanent delete; retried at start) | |

**Household, budgets and money rules (021–035)**

| # | File | Tables added | Columns added / notes |
|---|---|---|---|
| 021 | `household_items` | `products`, `item_aliases`, `item_resolutions`, `inventory_lots`, `lot_events`, `item_resolution_runs`, `web_search_cache` | [household](household.md) |
| 022 | `assets` | `assets` (assets and loans for the forecast) | [planning](planning.md#assets-and-loans) |
| 023 | `budgets` | `category_rules`, `budgets`, `checkin_runs` | `transactions.category_source`, `category_rule_id` |
| 024 | `returns_assets` | `return_policies` | `inventory_lots.opened_on`; `receipts.return_days_printed`, `return_policy_quote`; `assets.blob_hash`, `extraction_run_id`, `account_key`, `validation_json`; `lot_events` rebuilt |
| 025 | `warranties` | `warranties`, `warranty_runs` | |
| 026 | `receipt_counting` | | `receipts.category`, `statements.reconciliation`. Receipts count on their own until a statement line replaces them |
| 027 | `utilities_into_housing` | | Data only |
| 028 | `recurring_bills` | | `receipts.recurrence`; `recurring_obligations` rebuilt |
| 029 | `money_and_documents` | | Data only: bills no longer tracked; the Bills folder retired |
| 030 | `model_recurring_bills` | `payee_recurrence` | `recurring_obligations.source_document_id`, `evidence` |
| 031 | `jobs` | `employers`, `job_filings`, `income_lines`, `tax_tables`, `tax_table_runs` | `income_records.gross_pay_ytd_minor`, `net_pay_ytd_minor`, `work_state`, `pay_frequency` |
| 032 | `item_categories` | `category_splits`, `item_category_memory` | `receipt_items.taxed`, `category_source` |
| 033 | `receipt_rewards` | `receipt_rewards` | |
| 034 | `finer_categories` | | `receipt_items.category_source` rebuilt to allow `legacy` (shopping retired) |
| 035 | `family_shares` | `record_shares`, `family_assignments` (family inbox routing) | `receipts.payment_last_four` |

**Investments, search, planning and taxes (036–052)**

| # | File | Tables added | Columns added / notes |
|---|---|---|---|
| 036 | `investments` | `investment_kinds`, `investment_accounts`, `holdings`, `investment_valuations`, `investment_events` | Moved investment rows out of `assets` |
| 037 | `investment_links` | | Indexes only: a ledger savings account links to at most one investment account |
| 038 | `investment_confirmations` | `investment_confirmations` | `holdings.face_minor`, `redeemable_date`, `rollover`, `source`, `confirmation_id`; `investment_events.confirmation_id` |
| 039 | `investment_contributions` | | `investment_accounts.payroll_merchant_id`, `payroll_link`, `monthly_contribution_minor` |
| 040 | `tax_lots_forms` | `tax_lots`, `tax_forms`, `tax_form_boxes` | |
| 041 | `investment_payment_links` | `investment_payment_rejections` ("Not this payment") | `investment_events.transaction_link`, `transaction_previous_type` |
| 042 | `document_text` | `document_passages`, `document_passages_fts` (FTS5), `document_index_state` | |
| 043 | `scenarios` | `scenarios` | |
| 044 | `scenario_adoption` | | `scenarios.adopted_month` |
| 045 | `tax_tags` | `businesses`, `tax_rules`, `tax_tags` | |
| 046 | `tax_figures` | `tax_figure_sets`, `tax_years` | The figures lookup was retired on 2026-10-04; `tax_figure_sets` is kept, unused |
| 047 | `tax_units` | `tax_units` (who files together; in the family's own library) | |
| 048 | `recurring_kind` | | `recurring_obligations.kind`: `bill` or `subscription` |
| 049 | `audit_cleanup` | | Removes `record_shares`/`family_assignments` rows whose record is gone; ISO timestamps on seeded `return_policies`; indexes for per-row lookups; drops `bills.bill_type` and `investment_valuations.vested_minor` |
| 050 | `strict_tables` | | Every table rebuilt `STRICT` (FTS excepted), with `CHECK`s on run and job states, `occurrences.source_status`/`source_kind`, `tax_rules.kind`, `investment_events.transaction_previous_type`, and booleans. Unknown run states become `interrupted` first |
| 051 | `exchange_rates` | `fx_rate_sets`, `fx_rates` | Rates stored once per date and currency as decimal text; triggers refuse updates and deletes. `transaction_receipt_links.estimate_rate_id`/`estimate_minor` |
| 052 | `generated_reports` | `generated_reports` | CPA packs: path under `Reports/`, SHA-256, manifest, request key |

**Ingestion, investments and tax engines (053–060)**

| # | File | Tables added | Columns added / notes |
|---|---|---|---|
| 053 | `sources` | `sources` (watched folders), `occurrence_links` (`same_bytes`, `same_record`) | [documents](documents.md#watched-folders) |
| 054 | `receipt_segments` | `document_segments` | `receipts` rebuilt with `segment`, `UNIQUE(blob_hash, segment)` |
| 055 | `document_groups` | `document_groups`, `document_group_pages` | Several images read as one document |
| 056 | `investment_kinds_v2` | `pension_terms`, `price_quotes`, `ibond_rates` (seeded) | `investment_kinds` rebuilt with value model `income`; `investment_valuations.source` allows `quote`; `tax_form_boxes` allows 1099-Q and 1099-DA; `investment_accounts.beneficiary`, `plan_state`, `yield_bp`, `reinvest` |
| 057 | `donation_checks` | `donation_checks` | Checked answers for donated documents; never changes the ledger ([evals](evals.md#donating-documents)) |
| 058 | `tax_calculations` | `tax_calculations` | Each distinct return an engine worked out; never rewritten |
| 059 | `form_1098` | | `tax_form_boxes.form` allows `1098` |
| 060 | `tax_zen_evaluations` | `tax_zen_evaluations` | What Tax Zen said and why, added only when something changed; `seen_at` clears Home's notice |

**Runs and startup recovery.** Tables named `*_runs` record model or lookup work with a status. When a library opens,
each service's `recover()` marks a run still `queued` or `running` as `interrupted`, and you can retry it. Capture
intents, managed-organization intents and trash cleanup are replayed instead.

## Database checks

`scripts/db_checks.py` is a read-only checker for a library database file. It opens the file with `?mode=ro`, copies it
into memory with SQLite's backup API, closes the file, then runs:
- `integrity_check` and `foreign_key_check`;
- type drift on every INTEGER column;
- orphaned typed references;
- values in enum-like columns that have no `CHECK`;
- date and timestamp formats;
- duplicates.

It prints only counts, row ids and app enum values, never names, amounts, text or paths. Never run it against a live
library yourself. You run it in your own terminal and paste the output, redacted as you like:

```powershell
.\.venv\Scripts\python.exe scripts\db_checks.py "<library>\inventory.sqlite3"
```

The database audit of 2026-09-30 found and fixed four problems:
- migration rebuilds cascade-deleting rows (now foreign keys off plus `foreign_key_check`);
- re-extraction deleting your tags and identifications (now line matching; see
  [money](money.md#reading-a-statement-or-receipt-again));
- orphaned family shares attaching to new records (migration 049 plus trash cleanup);
- missing type and state constraints (migration 050).

What it left open is in [open work](open-work.md#database).
