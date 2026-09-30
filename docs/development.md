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
| `models/` | Model client, residency, Laya runtime, GPU host, web lookup connectors. |
| `app/` | FastAPI app (`api.py`), `Manager`, profiles, family sync, the CLI subcommands, and `static/` (the UI). |

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q                 # unit and API tests (about 60 files)
.\.venv\Scripts\python.exe -m pytest -q --browser       # also the browser tests
.\.venv\Scripts\python.exe -m pytest -q --cov           # with coverage (needs .[dev])
```

- **Unit and API tests** need `.[test]`. They use a synthetic local model server (`tests/conftest.py` `local_model`) and never contact a real model or the network.
- **Browser tests** need `.[browser-test]`. They drive the installed **Microsoft Edge** through Playwright (`channel="msedge"`), so `playwright install` isn't needed. They are skipped unless you pass `--browser` or set `RUN_BROWSER_TESTS=1`. They live in the `test_*_browser.py` files and `test_browser.py`, plus browser cases inside `test_employers`, `test_forecast`, `test_investments`, `test_receipt_counting`, `test_recurring_bills` and `test_share`.
- **The Laya test** (`test_laya.py`) needs `.[laya]` and installed weights. It is skipped unless `RUN_LAYA_TESTS=1`.
- There are no custom pytest markers. Opt-in tests use `skipif` on those variables.
- After a scenario that changes the ledger, call `conftest.assert_ledger_healthy(store)`.
- When changing a component, run that component's tests rather than the whole suite. A rare connection reset in the loopback tests on Windows is environmental.

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
4. SQLite can't change a `CHECK` constraint or drop some columns in place. Build a `*_new` table, copy the rows, drop the old one and rename (see `024`, `028`, `034`).
5. Upgrades are forward-only. Existing libraries get the new schema at their next start, after the app takes an `inventory.before-vNNN.sqlite3` copy ([managed library](managed-library.md)).
6. Backups record their `schema_version`. A backup from an older version restores and then upgrades; one from a newer version is refused (`library/backup.py`). No extra step is needed, but don't renumber or edit a released migration.
7. If new work has a `*_runs` table, give its service a `recover()` that marks `queued`/`running` rows `interrupted`, and call it from `Manager.open_library`.
8. Test the feature against the new tables in the feature's own test file. `tests/test_migrations.py` covers the upgrade machinery (failed step, missing version, damaged database).
9. Add the migration to [schema.md](schema.md).

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
