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
| `models/` | Model transport (`model_client.py`, `model_stream.py`), residency, decision models, vision settings, the shared GPU relay, `http_server.py` (`GracefulHTTPServer`), web lookup connectors. |
| `documents/` | Reading documents into evidence and records: image and PDF readers, regions and image grouping, vision transcription, reasoning runs, typed extraction, the reviewer, donations. |
| `finance/` | Ledger, reconciliation, splits, tools and the assistant, budgets and check-ins, the dashboard, forecast and charts, investments, lots and retirement, prices and FX, paychecks and scenarios, taxes (tags, year, return, engine, safe harbor, Tax Zen, withholding, family), the CPA pack, health checks. |
| `finance/engines/` | Tax engine adapters: `opentax.py` (Engine 1), `taxcalc.py` and `taxcalc_run.py` (Engine 2, in its own process). |
| `household/` | Items and inventory, item identification, item analysis, warranties, paycheck tax-table lookups. |
| `app/` | FastAPI app (`api.py`), `Manager` (queues and wiring), profiles, family sync, the CLI subcommands, and `static/` (the UI). |
| `vendor/` | The pinned OpenTax bundle (`vendor/opentax/`, never edited) and `NOTICES.md`. |

Outside `src/`:
- `tests/`: flat pytest modules, synthetic data only;
- `evals/`: the eval suite ([evals](evals.md));
- `scripts/`: `db_checks.py`, `loopback_stress.py`, `taxcalc_map_skeleton.py` (Engine 2's worksheet map upkeep,
  [taxes](taxes.md#the-engines-worksheets)) and `test_instance.py` (the agent test instance, below);
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
  - They live in the `test_*_browser.py` files (one `test_<screen>_v2_browser.py` per redesigned screen, plus
    `test_browser.py`, `test_document_search_browser.py`, `test_donate_browser.py`, `test_family_browser.py`,
    `test_record_components_browser.py`, `test_settings_browser.py`, `test_shell_browser.py` and
    `test_trace_components_browser.py`) and `test_ui_parity.py`.
  - Some other test files also have browser cases: `test_employers`, `test_receipt_counting` and `test_share`.
  - Run them all with `-k "browser or parity"`, plus those three files.
  - Layout checks are described in `docs/ui.md` "Verifying a layout".
- **Decision models** (`test_decisions.py`) use the same synthetic server. Set `local_model["decide"]` to a function
  `(path, body) -> reply` that answers `/v1/responses` and `/v1/systemone`. Requests to those paths are kept in
  `local_model["decisions"]`, apart from chat requests.
- **Opt-in tests** use `skipif` on those variables. The one custom marker, `lmstudio`, is deselected by default
  ("Agent test instance").
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
    own server, keeps connections alive, so browsers aren't affected; a client that sends `Connection: close` still is
    ([open work](open-work.md#app-server)). Tests: `tests/test_http_server.py`.
- **Checking it again:** `.\.venv\Scripts\python.exe scripts\loopback_stress.py --requests 20000 --response-bytes 40000`
  must report 0 failures. Use `--mode app` to go through `request_completion`. `--backlog 5` reproduces the old listen
  queue.
- **Any new HTTP server in this project,** test or product, should subclass `GracefulHTTPServer`.

## Agent test instance

A synthetic Home Manager that AI agents explore in a browser (Playwright, `playwright-cli`) and report on, without
going near real data. Spec and plan: `specs/agent-test-instance/`, `plans/agent-test-instance/`. Agents follow the
`agent-testing` skill (`.claude/skills/agent-testing/SKILL.md`).

```powershell
python scripts/test_instance.py reset    # rebuild the instance with the synthetic household (refused while it runs)
python scripts/test_instance.py start    # serve it in the background; writes <root>/session.json
python scripts/test_instance.py verify   # PASS/FAIL/WARN per check; --fresh also compares seed counts exactly
python scripts/test_instance.py stop
python scripts/test_instance.py finding ...   # record one finding in docs/bugs.md (below)
```

**Settings.** By flag or environment variable: `--root` / `HM_TEST_ROOT` (default `tests/.tmp`, gitignored), `--port`
/ `HM_TEST_PORT` (8775), `--lmstudio` / `HM_TEST_LMSTUDIO` (`http://127.0.0.1:1234/v1`). `reset` also takes
`--vision-model` / `--reasoning-model` (or `HM_TEST_VISION_MODEL` / `HM_TEST_REASONING_MODEL`); without them it keeps the
previous instance's model IDs, and with none at all `verify` warns until you pick models in Settings › Models. Test-only
variables: `HM_TEST_PROTECTED` (extra protected folders, `os.pathsep`-separated), `HM_TEST_SEED_FAIL` (break one seed
step), `HM_TEST_SERVE_FAIL`, `HM_TEST_FINDING_DATE`. `tests/environment.json` names the same commands.

**The instance folder.**
- `.hm-test-instance` is the sentinel. `reset` deletes a root only if it is missing, holds the sentinel, or is
  exactly `tests/.tmp`. Every other command refuses a root without it.
- `control/` and `library/` hold the app's settings and the seeded library: one profile, "Test", at `library/`.
- `uploads/` has one synthetic document per kind (see its `README.txt`), including a prompt-injection receipt.
- `evidence/` holds agents' screenshots. `reset` keeps it, so the screenshots cited in `docs/bugs.md` stay valid.
- `seed.json` has the seed date and manifest (counts per section and named values). `session.json` has `base_url`,
  `link` (with a fresh token on every `start`), `seed_date`, `seed_counts` and the LM Studio address and models.
- `server.pid` (pid plus process creation time, so a reused pid is never signalled), `server.log`,
  `.seed-incomplete` while seeding, and `stop.request`, which `stop` writes to shut the server down from any console.
- The app log is `control/logs/home-manager.log`.
- A root that overlaps a protected folder, in either direction, is refused before any filesystem call.

**The seed.** `tests/seed_household.py` `seed(manager, root, model, fail_step=None)` is the one household seed, used
by `reset`, `ui_shots.py` and the browser tests (`test_one_household_seed` checks this). It runs named steps
(`seed_ledger` … `seed_settings`) through the synthetic model server, then `reset` points every model setting at the
LM Studio address. A failing step is named (`seed step failed: <step>`), and `start` refuses a half-seeded instance.
Seeded taxes depend on Engine 1 covering this year (`taxes_seeded` in the manifest).

**Test mode** (`core/sandbox.py`). Only `scripts/test_instance.py serve` turns it on; `python -m home_manager` never
does, and nothing reads an environment variable for it. While it is on:
- **Paths.** `core/paths.py` `local_absolute`, which every path input goes through, refuses anything under
  `P:\Finances`, `P:\EvalCorpus` or `%LOCALAPPDATA%\HomeManager`, and anything outside the instance root. The check
  is lexical, before any filesystem call, so 8.3 short names and links are refused without being touched.
  `separate_folder` lets folders under the instance root sit inside the checkout (the default root does).
- **Network.** A process-wide audit hook refuses `socket.getaddrinfo` and `socket.connect` for any host that isn't
  loopback, and logs `test instance: refused outbound host=<host>` once per host. Prices, exchange rates, item lookups,
  web search and family sync then show their existing offline states. It covers this process only: the app's child
  processes (the OpenTax and Tax-Calculator runners, the PDF reader) make no network calls today, and a new child that
  needs the network must be checked separately. It handles TCP and name lookups, not UDP `sendto`.
- **Models and the hub.** The model computer refuses tailnet addresses (every other model setting already accepts
  only `127.0.0.1`), and the family hub never asks for the tailnet address, so it stays off.
- **Status.** `GET /api/settings` reports `test_instance: {"paths": bool, "egress": bool}`, which probes each guard
  instead of reporting a flag. It is `null` in the live app.
- **The marker.** The shell shows `#test-instance-marker`, an amber "Test data" pill ("Test" on the 64 px sidebar),
  at every width. Agents check it before every screenshot and finding.

**`verify`** checks that the server answers, that the seed is complete (exact counts only with `--fresh`, since agents'
changes move them), and that both guards report true. It warns, and still exits 0, when LM Studio doesn't answer, when
no model IDs are set, or when something listens on 8765. The developer's app may share LM Studio with the instance, so
don't run agent uploads while it is scanning.

**Findings.** `finding` is the only way agents write to `docs/bugs.md`. It takes `--url` (the page's current URL),
`--route`, `--symptom`, `--kind bug|friction|console-error`, `--severity low|medium|high`, `--steps`, `--expected`,
`--actual`, `--screenshot` (a file in `<root>/evidence/`) and `--agent`.
- **Refusals.** It refuses with exit 2 when a field is missing or the session isn't on `http://127.0.0.1:<port>`. It
  also refuses when the target isn't `docs/bugs.md` or a file in the root, when the page's origin isn't the session's
  `base_url`, or when that server doesn't report test mode. It refuses with exit 3 when `<target>.lock` is held for
  10 s or the file changed while it was writing.
- **The screenshot on refusal.** Every refusal deletes the screenshot, but only one inside `evidence/`. A screenshot
  elsewhere is refused and left alone.
- **Where it writes.** Only in the `## Agent findings` section, from its header to the next `## ` line or the end. It
  adds the header if it is missing and keeps the file's newline style. The bytes before the section never change, and
  any text after it is kept.
- **Duplicates.** Each entry starts with `<!-- finding:KEY -->`, where KEY comes from the route and the lower-cased,
  whitespace-collapsed symptom. The same key on a later date adds `- Seen again: DATE (seed DATE) — evidence: <file>`.
  On the same date it adds nothing.
- **Field text** can't end the section or forge a marker: `<!--` and lines starting `#` are escaped.

**Tests.**
- `test_agent_guards.py` covers the guards in-process, with real-path spies that raise and a `no_egress` socket
  double that never calls the real function for an outside host.
- `test_agent_instance.py` covers the lifecycle in subprocesses at a `tmp_path` root on a free port, with
  `LOCALAPPDATA` pointed at an empty decoy. It never uses `tests/.tmp` or 8775. A restored copy of one template reset
  keeps it fast.
- `test_agent_instance_browser.py` covers the marker, every route, and the refusals on screen.
- `test_agent_findings.py` covers `finding`, against a copy of `docs/bugs.md`.
- `test_sc06_real_lmstudio` uses the real LM Studio. It is marked `lmstudio` and deselected by default
  (`addopts = -m "not lmstudio"`). Run it with `pytest -m lmstudio`. Any other `-m` on the command line replaces the
  default, so `-m "not slow"` would bring it back.

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
| Shared GPU | Run `home-manager gpu-host serve`, `add-member`, and point another profile's Local models at it. | [family](family.md#shared-gpu) |
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
`src/home_manager/library/migrations/` (001–071). The `NNN_` prefix of each script matches `PRAGMA user_version`. The
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

**Provenance (061)**

| # | File | Tables added | Columns added / notes |
|---|---|---|---|
| 061 | `provenance` | `budget_changes`, `tax_input_changes`, `rule_sources`, `figure_snapshots` | `record_corrections` rebuilt to allow transaction, statement, investment valuation, tax form box, holding and budget, with `reason` and `actor`; `actor` on `review_events`, `family_assignments` and `transactions`; `transactions.replaced_by`; `created_at`/`updated_at` on `receipt_items`, `receipt_rewards`, `income_lines`, `tax_form_boxes` (filled from their record); `tax_tables.rule_version` ([ui](ui.md#whats-built)) |

**Family (062)**

| # | File | Tables added | Columns added / notes |
|---|---|---|---|
| 062 | `family_corrections` | `family_corrections` | `sent` rows in a family's own library, `received` rows in a member's; `reconciliation_issues` rebuilt to allow the `kept_mine` and `took_family` resolutions of a `family_correction` question ([family](family.md#family-corrections)) |

**Returns and cleanup (063–065)**

| # | File | Tables added | Columns added / notes |
|---|---|---|---|
| 063 | `returned_lots` | `lot_returns` (a returned receipt line's proposed lots and the answer) | `inventory_lots` and `lot_events` rebuilt to allow `returned` ([household](household.md#returned-items)) |
| 064 | `dead_columns` | | Drops the 2026-09-30 audit's dead columns: `jobs.year`/`month`, `occurrences.folder_year`/`folder_month` (and index `occurrences_root`), `investment_events.reverses_event_id` (table rebuilt) |
| 065 | `account_names` | | Renames `accounts.display_name` from the old generated form that doubled the type ("Household checking checking") to the institution alone; names the user chose stay ([money](money.md#money-pages)) |
| 067 | `bills_as_receipts` | `share_requests`, `transaction_income_links` | `receipts.document_kind`, `issue_date`, `due_date`, `period_start`, `period_end`, `amount_due_minor`, `account_last_four`; `receipt_items.line_holder`, `member_id`, `member_source`, `line_kind`; `record_shares.member_id`; `bills` copied into receipts and dropped, its typed-id rows renamed, a named payment made a verified match; `family_assignments` rebuilt to allow mode `lines`; model-assigned `housing` items marked `legacy` for re-sorting ([money](money.md#bills-and-their-lines)) |

**PDF import (071)**

| # | File | Tables added | Columns added / notes |
|---|---|---|---|
| 071 | `pdf_import_index` | `pdf_import_index` | Derived and rebuildable from the reading, keyed by `parse_runs.id` (`ON DELETE CASCADE`): table count, printed last fours, currency, `analyzer_version`, `error`. No money or row data; nothing backfilled by the migration ([documents](documents.md#transaction-imports)) |

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
