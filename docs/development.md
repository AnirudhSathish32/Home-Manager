# Developing Home Manager

Status: reference (2026-09-30). Setup, commands and on-disk layout are in [operations](operations.md). Design background is in [architecture](architecture.md). The index of every doc is in [docs/README.md](README.md).

## Layout

`src/home_manager/`:

| Package | Holds |
|---|---|
| `core/` | Paths and locks, folders, categories, the work queue (`jobs.py`), worker limits, the log. |
| `library/` | The store and migrations, scanning and capture, the managed Library, backups, shares, trash, the text index. |
| `documents/` | Readers (images, PDF, CSV/XLSX), vision transcription, reasoning, typed extraction, the reviewer. |
| `finance/` | Ledger, reconciliation, tools and assistant, budgets, forecast, investments, paychecks, scenarios, taxes, charts, health checks. |
| `household/` | Items and inventory, item identification, warranties, returns, tax tables and figures (web lookups). |
| `models/` | Model client, residency, decision models, GPU host, web lookup connectors. |
| `app/` | FastAPI app (`api.py`), `Manager`, profiles, family sync, the CLI subcommands, and `static/` (the UI). |

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q                 # unit and API tests (about 60 files)
.\.venv\Scripts\python.exe -m pytest -q --browser       # also the browser tests
.\.venv\Scripts\python.exe -m pytest -q --cov           # with coverage (needs .[dev])
```

- **Unit and API tests** need `.[test]`. They use a synthetic local model server (`tests/conftest.py` `local_model`) and never contact a real model or the network.
- **Tax engine tests:** Engine 1's need Node.js 20+ and Engine 2's need `.[engine2]` (Tax-Calculator); each skips
  without its engine. Install both before changing anything in `finance/tax_*.py` or `finance/engines/`.
- **Browser tests** need `.[browser-test]`. They drive the installed **Microsoft Edge** through Playwright (`channel="msedge"`), so `playwright install` isn't needed. They are skipped unless you pass `--browser` or set `RUN_BROWSER_TESTS=1`. They live in the `test_*_browser.py` files and `test_browser.py`, plus browser cases inside `test_employers`, `test_forecast`, `test_investments`, `test_receipt_counting`, `test_recurring_bills` and `test_share`.
- **Decision models** (`test_decisions.py`) use the same synthetic server: set `local_model["decide"]` to a function `(path, body) -> reply` that answers `/v1/responses` and `/v1/systemone`. Requests to those paths are kept in `local_model["decisions"]`, apart from chat requests.
- There are no custom pytest markers. Opt-in tests use `skipif` on those variables.
- After a scenario that changes the ledger, call `conftest.assert_ledger_healthy(store)`.
- When changing a component, run that component's tests rather than the whole suite. A connection reset in a loopback test is a bug now, not noise: see the next section.

## Windows loopback resets

Fixed 2026-10-01. For a long time a rare test failed with "Local model connection failed or disconnected"
(`ConnectionResetError`, WinError 10054) and passed on a rerun.

- **Symptom:** the client got the start of a reply (the `200` status line), waited about 19 s for the rest, then the
  connection was reset.
- **Cause:** on this Windows machine, when a server closes its socket, or sends FIN with `shutdown(SHUT_WR)`, right
  after a reply that spans several TCP segments, a segment still in flight is sometimes lost. Python's `socketserver`
  does exactly that after every HTTP/1.0 reply. Small replies fit in one segment and were never hit.
- **Measured** with 40 KB replies, raw sockets, 600 transfers each:

  | How the server ends the reply | Lost |
  | --- | --- |
  | `shutdown(SHUT_WR)` then close | 8 |
  | close at once | 5 |
  | `shutdown` then wait for the client | very many (FIN right behind the data is the trigger) |
  | wait 0.2 s, then close | 0 |
  | wait for the client to close first | 0 |

  Through the synthetic model server: 16 of 1,000 requests. The long-statement extraction test failed 4 of 100 runs.
- **Not the cause:**
  - The client's request was always delivered: 57,000 requests up to 1 MB were sent with no failure.
  - The 2026-09-25 "one write per response" change made no difference.
  - Unproven whether a filter driver (Tailscale, antivirus) is involved. The fix doesn't depend on it.
- **Fix:** `models/http_server.py` `GracefulHTTPServer`. After a reply the server reads until the client closes (at
  most 10 s). It never sends FIN first. Every client of these servers closes first, after Content-Length or the
  stream's `[DONE]`.
  - Once the client has closed, the server closes with a reset (`SO_LINGER` 0). The client has read everything by then,
    and the reset leaves neither side in TIME_WAIT.
  - Without the reset, the client, now the side that closes first, keeps each port in TIME_WAIT for 2 minutes. About
    16,000 requests in 2 minutes then exhausted Windows' client ports (WinError 10048 on connect), which also broke the
    next test runs.
  - A client that never closes gets an ordinary close after 10 s.
  - The GPU host relay (`RelayServer`) and the tests' synthetic model server (`tests/model_server.py`) both use it.
  - FastAPI/uvicorn, the app's own server, isn't affected: it keeps connections alive and doesn't close after each
    reply.
  - Tests: `tests/test_http_server.py`.
- **Checking it again:** `.\.venv\Scripts\python.exe scripts\loopback_stress.py --requests 20000 --response-bytes 40000`
  must report 0 failures. Use `--mode app` to go through `request_completion`. `--backlog 5` reproduces the old listen
  queue.
- **Any new HTTP server in this project**, test or product, should subclass `GracefulHTTPServer`.

## Checks

Install with `.[dev]`. There is no CI, so run these before committing:

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests    # likely bugs, current idioms, import order; no formatter
.\.venv\Scripts\python.exe -m mypy                    # types in core, finance and library only
```

## Adding a migration

1. Add `src/home_manager/library/migrations/NNN_short_name.sql`, where `NNN` is one more than the highest number there. `MIGRATIONS` picks it up by name. The package data in `pyproject.toml` already ships `migrations/*.sql`.
2. Start it with a comment saying what it is for and which doc covers it. End it with `PRAGMA user_version=NNN;`. The runner refuses a step that doesn't record its own number.
3. Don't write `BEGIN` or `COMMIT`. The runner wraps each script in one `BEGIN IMMEDIATE … COMMIT`, so a failed step rolls back whole, earlier steps are kept, and the next start retries.
4. SQLite can't change a `CHECK` constraint or drop some columns in place. Build a `*_new` table, copy the rows, drop the old one and rename (see `024`, `028`, `034`). Foreign keys are off while scripts run, so the `DROP TABLE` doesn't delete the rows that cascade from it. Recreate the table's indexes and triggers after the rename. The runner runs `PRAGMA foreign_key_check` before committing, and refuses a step that leaves new broken references.
5. Every table is `STRICT` (since `050`): end each `CREATE TABLE … ) STRICT;` and use only `INTEGER`, `REAL`, `TEXT`, `BLOB` or `ANY`. Dates and JSON are `TEXT`; money is `INTEGER` minor units; a boolean is `INTEGER … CHECK (x IN (0,1))`; a state or kind gets a `CHECK (x IN (…))` listing every value the code writes. A rebuilt table must stay `STRICT`, and SQLite writes the renamed table's name quoted (`CREATE TABLE "receipts"`).
6. Upgrades are forward-only. Existing libraries get the new schema at their next start, after the app takes an `inventory.before-vNNN.sqlite3` copy ([managed library](managed-library.md)).
7. Backups record their `schema_version`. A backup from an older version restores and then upgrades; one from a newer version is refused (`library/backup.py`). No extra step is needed, but don't renumber or edit a released migration.
8. If new work has a `*_runs` table, give its service a `recover()` that marks `queued`/`running` rows `interrupted`, and call it from `Manager.open_library`. If its status has a `CHECK`, list `interrupted` in it.
9. Test the feature against the new tables in the feature's own test file. `tests/test_migrations.py` covers the upgrade machinery (failed step, missing version, damaged database, table rebuilds, broken references).
10. Add the migration to [schema.md](schema.md).

## Rules that apply everywhere

- **Privacy in logs** (`core/logs.py`): log event names, ids, counts and exception class names. Never exception messages, amounts, merchant names, file names or document text. Use `log_failure` for failures.
- **Models propose, people decide.** Model output is stored as proposed until reviewed. Tools the model can call are read-only.
- **Never test against real financial data.** Tests use synthetic documents and the fake model server.

## UI and charts

Before changing the UI, read the project skills in `.claude/skills/`:
- `app-ux`: screen rules and tokens, for anything in `app/static/`.
- `forecast-charts`: chart rules and palette, for `finance/charts.py` or any chart.
- `frontend-design`: visual direction within the `app-ux` tokens.

Design history: [UI design plan](ui-design-plan.md) (built), [new UI/UX design](new_ui_ux_design.md) (planned, not built), [home screen](home-screen-design.md).
