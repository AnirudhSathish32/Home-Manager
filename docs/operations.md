# Running Home Manager

Status: reference (2026-09-30). The operator's guide: install, commands, settings, where things live on disk, backups, background work and troubleshooting. Developer tasks (tests, checks, migrations) are in [development](development.md).

## Install

Home Manager needs Python 3.13 or newer. From PowerShell in the repository:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
```

Optional extras (`pyproject.toml`), which can be combined, as in `.[test,dev,browser-test]`:

| Extra | For |
|---|---|
| `test` | pytest and httpx, to run the test suite. |
| `browser-test` | Playwright, for the opt-in browser tests (they use the installed Microsoft Edge). |
| `dev` | `ruff`, `mypy`, `pytest-cov`. |

### Local models (LM Studio)

The app never downloads or loads model weights itself. It talks to an OpenAI-compatible server on loopback, normally LM Studio at `http://127.0.0.1:1234/v1`. That server must support streaming chat completions and JSON-schema output, and the vision model needs image input.

In **Settings → Local models**, save the URL and exact model ID for:
- **Vision model**: reads images into text. See [image transcription](receipt-parsing.md).
- **Reasoning model**: extraction, the assistant, item identification and the web lookups.
- **Decision model** (optional): the independent checks on every extraction. It can be a model in LM Studio 0.3.39 or later, or a `/v1/systemone` server such as Kev. See [decision models](decision-models.md).
- **Independent checks** for audit analyses (optional): a second chat model, or the decision model. See [assistant](assistant.md#the-independent-reviewer-independent-checks).

By default the app keeps one generative model loaded at a time. Before each request it unloads the others through LM Studio's `/api/v1` API; the **Keep one model loaded at a time** setting turns this off. See [financial reasoning](financial-reasoning.md) and [shared GPU](shared-gpu-plan.md) for residency, and for using another family member's GPU computer.

### Web lookups

Item identification, warranty lookups and tax-table lookups search the web with the Brave Search API. Set the key in the environment before starting the app:

```powershell
$env:HOME_MANAGER_BRAVE_API_KEY = "<key>"
```

Without the key, those lookups fail with "Web search is not configured". Everything else works.

## Commands

`home-manager` is installed as a console script. `python -m home_manager` is the same program.

| Command | What it does |
|---|---|
| `home-manager [--port 8765] [--control-dir DIR]` | Starts the app on `127.0.0.1`. Prints a private session link (`http://127.0.0.1:<port>/#token=…`) and the log's path. No browser opens by itself; open the link. The port must be between 1024 and 65535. |
| `home-manager check-ledger [--control-dir DIR] [--library DIR]` | Read-only [ledger health](architecture.md#diagnostics-and-checks) report for every individual profile, or for one library folder. It is safe while the app runs. Exits 1 if any error-level rule is broken. The report shows rule names and record ids, never amounts or text. |
| `home-manager index-documents [--rebuild] [--control-dir DIR] [--library DIR]` | Builds the [document search](document-search.md) index. The app indexes new readings by itself; use `--rebuild` to throw the index away and build it again. It takes each library's lock, so close the app first. |
| `home-manager gpu-host [--control-dir DIR] serve [--bind IP]` | Runs the family GPU relay. `add-member NAME` (prints the token once), `remove-member NAME` and `members` manage who can use it. See [shared GPU](shared-gpu-plan.md). |

Stop the app with Ctrl+C. Each start makes a new session link, so a tab left open from an earlier run must be opened again from the new link.

## Environment variables

| Variable | Effect |
|---|---|
| `LOCALAPPDATA` | Windows: the default control dir is `%LOCALAPPDATA%\HomeManager`. Elsewhere it is `~/.local/share/home-manager`. |
| `HOME_MANAGER_BRAVE_API_KEY` | Brave Search API key for web lookups. It is never written to settings files, prompts or logs. |
| `RUN_BROWSER_TESTS=1` | Test runs only: include the browser tests (or pass `--browser`). |

## Where things live

Described from the code; the app creates everything below. Keep the control dir and the library folders separate.

**Control dir** (`%LOCALAPPDATA%\HomeManager`, or `--control-dir`): this computer's settings.

| Path | Holds |
|---|---|
| `settings.json` | The library folder last opened. |
| `profiles.json`, `profiles/<id>/household.json` | Profiles ([sharing](sharing.md)) and each profile's financial preferences. An older single `household.json` moves into the first profile. |
| `vision.json`, `reasoning.json`, `reviewer.json`, `decision.json` | Model settings. Invalid saved settings fall back to defaults, which switch that model off. |
| `model_computer.json`, `gpu_token.txt` | Whether models run on this PC or a family GPU computer, and the member token (never returned by the API). |
| `gpu_host.json` | Only on a GPU host: its members and their tokens. |
| `logs/home-manager.log` (+ `.1`–`.5`) | The diagnostic log. It rotates at 1 MB. It records events, ids and code tracebacks, never document text, amounts, merchant names or file names. |
| `sessions/` | Temporary copies for an opened shared library; deleted at start. |
| `.home-manager.lock` | One process per control dir. |

**Library folder** (one per individual profile):

| Path | Holds |
|---|---|
| `.home-manager-store`, `.home-manager.lock` | Store marker, and the lock (one process per library). |
| `inventory.sqlite3` (+ `-wal`, `-shm`) | The database ([schema map](schema.md)). |
| `inventory.before-vN.sqlite3` | Copy taken before a schema upgrade; the two newest are kept. These are recovery aids, not backups. See [managed library](managed-library.md). |
| `originals/<2 hex>/<sha256>.blob` | Every captured file, byte for byte, named by hash. |
| `extracted/` | Image previews and derived files that readings refer to. |
| `work/` | Temporary files while capturing. |
| `Library/Inbox` | Drop documents here; the app watches it. |
| `Library/<folder>/YYYY/MM/` | Filed documents: `Receipts`, `Bank_Statements`, `Credit_Card_Statements`, `Housing`, `Insurance`, `Investments`, `Loans`, `Taxes`, and `Unfiled`. `Jobs/<Employer>/{Paystubs,Documents}` is laid out by employer ([jobs and paystubs](jobs-and-paystubs.md)). |

**Family folder** (in a synced folder, [sharing](sharing.md)): `.home-manager-family`, `family.json`, `members/`, `view/`, and deliveries (`to-<member>/*.hmdelivery`). Shared-library exports are `.hmshare` files.

## Backup and restore

In **Settings → Library folder**, **Back up** writes a folder to a destination you choose. It contains:
- a consistent SQLite snapshot (made with SQLite's backup API, never a file copy)
- `originals/` (hash-checked as it is copied)
- `Library/` and `extracted/`
- `manifest.json`, listing every file with its size and SHA-256

The folder appears under its final name only once it is complete. Keep backups on a different disk from the library.

A restore checks the whole backup first. It then builds a **new** library in an empty folder you choose; the active library is never touched. Switch to the restored folder in **Settings → Library folder**. A backup or restore can be cancelled from the activity list. If the app stops mid-backup, the backup is marked interrupted at the next start. Code: `library/backup.py`.

## Background work

- **Inbox watcher.** The `inbox-monitor` thread (`Manager.watch_inbox`) looks at `Library/Inbox` every 3 seconds. A file has to look the same (name, size, modified time) on two checks in a row before capture starts, and nothing starts while capture work is already running.
- **Watched folders.** Every 10 watcher ticks (about 30 seconds), each enabled watched folder is checked the same way, and also rescanned once after start and every `rescan_hours` (default 6). Its files are copied into the library; the folder is never changed. See [document reading](document-reading.md#1-discover-and-register).
- **Family checks.** Every 20 watcher ticks (about a minute), the app checks the family folder for new snapshots and deliveries. A member's changed library is published to the family at most every 10 minutes (`PUBLISH_EVERY_SECONDS`).
- **Two work queues.** `capture` handles scans, backups, restores and indexing. `inference` handles model work. Each runs one job at a time. Model work, backups and restores can be cancelled; scans can't be interrupted.
- **At each start**, when a library opens:
  - the database is checked and, if needed, upgraded (see [managed library](managed-library.md))
  - capture intents and filing moves that didn't finish are replayed
  - files queued for deletion from Trash are removed (`trash_cleanup`)
  - files in retired folders move on (`Bills` → `Unfiled`, `Income` → `Jobs`)
  - every model or lookup run left `queued` or `running` is marked `interrupted`, so it can be retried
  - readings not yet in the search index are indexed in the background

## Troubleshooting

| Symptom | What to do |
|---|---|
| The port is in use | Start with `--port 8766` (or any free port from 1024 to 65535). |
| "This directory is already in use by another Home Manager process." | Another Home Manager process, or `index-documents`, has it open. Close it. Only one process can own a control dir or library at a time. |
| A tab left open from before a restart stops working | Each start makes a new session token. Open the new link printed in the terminal. |
| Model work fails right away, or "cannot connect" | Check that LM Studio's server is running at the saved URL and the model ID matches exactly. **Settings → Local models** can test the connection. |
| Two models are loaded and the GPU runs out of memory | Leave **Keep one model loaded at a time** on, or turn on LM Studio's JIT "auto-evict". |
| Web lookups say search is not configured | Set `HOME_MANAGER_BRAVE_API_KEY` and restart. |
| Search misses documents you know are there | Close the app and run `home-manager index-documents --rebuild`. |
| "The library upgrade stopped at step NNN" | Leave the folder unchanged. Follow [recovering from a failed upgrade](managed-library.md). The log names the step. |
| Anything else | Look in `<control>/logs/home-manager.log` (the path is printed at start). Run `home-manager check-ledger` if money totals look wrong. |
