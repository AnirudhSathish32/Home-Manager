# Running Home Manager

This is the operator's guide: install, local models, commands, environment variables, where things live on disk,
backups, background work, diagnostics and troubleshooting. Developer tasks (code layout, tests, checks, migrations) are
in [development](development.md).

## Install

Home Manager needs Python 3.13 or newer. From PowerShell in the repository:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m home_manager
```

Optional extras (`pyproject.toml`) can be combined, as in `.[test,dev,browser-test,engine2]`:

| Extra | For |
|---|---|
| `test` | pytest and httpx, to run the test suite. |
| `browser-test` | Playwright, for the opt-in browser tests (they use the installed Microsoft Edge). |
| `dev` | `ruff`, `mypy`, `pytest-cov`. |
| `engine2` | Tax-Calculator 6.8.4, the second tax engine that checks every return ([taxes](taxes.md#the-tax-engines)). |

**Engine 1**, the federal tax engine, runs as a Node.js process: install **Node.js 20 or later**. Without it, the Taxes
page and the health check say "Engine 1 needs Node.js 20 or later", and everything else works.

## First start

1. Open the private session link printed in the terminal (`http://127.0.0.1:8765/#token=…`). It grants access to this
   running session, so don't share it.
   - The page removes the token from its address and keeps it in that tab's session storage.
   - Each start makes a new link, and the terminal also shows the log's path. No browser opens by itself.
2. In **Settings → Library folder**, choose an empty folder for your library (the app can create it), or a library this
   app already made. Paste an absolute path, since there is no native folder picker yet. Keep the library:
   - outside the repository, the settings folder, cloud-synced folders and network drives;
   - on a local NTFS disk. Captured bytes are published through an internal hard link, and Windows links, junctions and
     reparse points are rejected.
3. Start LM Studio's server and save the model ids in **Settings → Local models** (see below).
4. Drop files into `<library>\Library\Inbox`, and approve what the models propose in **Review**.

**Server security.** The server binds only to loopback and rejects other Host/Origin values. Only one process can own a
settings folder or a library at a time. A normal shutdown (Ctrl+C) waits for an active scan; a forced stop is recovered
at the next start.

**Trust boundary.** The app assumes a trusted local Windows account. It doesn't install encryption, custom ACLs or
antivirus controls, so protect the folders with your normal account and an encrypted disk and backups. Don't edit the
database or the captured files by hand.

## Local models

The app never downloads or loads model weights itself. It talks to an OpenAI-compatible server on loopback, normally LM
Studio at `http://127.0.0.1:1234/v1`. That server must support streaming chat completions and JSON-schema output, and
the vision model needs image input. No request ever goes to a cloud model.

In **Settings → Local models**, save the URL and exact model id for:
- **Vision model:** reads images into text ([documents](documents.md#images-vision-transcription)).
- **Reasoning model:** extraction, the assistant, item identification and the web lookups.
- **Decision model** (optional): the independent checks on every extraction. This can be a model in LM Studio 0.3.39 or
  later, or a `/v1/systemone` server such as Kev ([documents](documents.md#decision-models)).
- **Independent checks** for reasoning runs (optional): a second chat model, or the decision model
  ([assistant](assistant.md#the-independent-reviewer)).

**Test connection** checks each model without loading anything or sending content.

**One model loaded at a time** (`models/residency.py`). The app serializes all model work on one inference queue. Before
each request it makes sure the target is the only generative model loaded:
- it asks LM Studio's native API what is loaded (`GET /api/v1/models`);
- it unloads every other LLM or VLM (`POST /api/v1/models/unload`), leaving embedding models alone;
- then it loads the target (`POST /api/v1/models/load`).

More detail:
- **Confirmed** on 2026-10-03 against the installed LM Studio: swapping vision → reasoning → vision left exactly one
  model loaded after each step, with loads taking 6–11 s.
- **Context length.** A model loaded by key gets LM Studio's default context (8,192 here), not its maximum.
- **Older servers.** A server without the `/api/v1` API (a 404) falls back to JIT loading, and Settings suggests LM
  Studio's "JIT models auto-evict". There is no `/api/v0` fallback, because v0 can't unload.
- **Turning it off.** The setting **Keep one model loaded at a time** (on the model computer setting,
  `model_computer.json`) turns this off.
- **Family GPU.** A family GPU computer manages residency for the requests it relays, so members skip this step
  ([family](family.md#family-gpu)).

### Web lookups

Item identification, warranty lookups and tax-table lookups search the web with the Brave Search API. Set the key in
the environment before starting the app:

```powershell
$env:HOME_MANAGER_BRAVE_API_KEY = "<key>"
```

Without the key, those lookups fail with "Web search is not configured", and everything else works. The only other
outbound requests are:
- ECB exchange-rate downloads (on by default, can be turned off; [money](money.md#currency-conversion));
- crypto prices (off by default; [planning](planning.md#crypto)).

## Commands

`home-manager` is installed as a console script. `python -m home_manager` is the same program.

| Command | What it does |
|---|---|
| `home-manager [--port 8765] [--control-dir DIR]` | Starts the app on `127.0.0.1` and prints the session link and the log's path. The port must be between 1024 and 65535. |
| `home-manager check-ledger [--control-dir DIR] [--library DIR]` | Read-only [ledger health](#ledger-health) report for every individual profile, or for one library folder. Safe while the app runs. Exits 1 if any error-level rule is broken. Also reports whether each tax engine can run. |
| `home-manager index-documents [--rebuild] [--control-dir DIR] [--library DIR]` | Builds the [document search](documents.md#searching-document-text) index. The app indexes new readings by itself; `--rebuild` throws the index away and builds it again. It takes each library's lock, so close the app first. |
| `home-manager gpu-host [--control-dir DIR] serve [--bind IP]` | Runs the [family GPU relay](family.md#family-gpu) on port 8766. `add-member NAME` prints the member's token once, `remove-member NAME` revokes it, and `members` lists them. |

Stop the app with Ctrl+C. Each start makes a new session link, so a tab left open from an earlier run must be opened
again from the new link.

## Environment variables

| Variable | Effect |
|---|---|
| `LOCALAPPDATA` | Windows: the default settings folder is `%LOCALAPPDATA%\HomeManager`. Elsewhere it is `~/.local/share/home-manager`. |
| `HOME_MANAGER_BRAVE_API_KEY` | Brave Search API key for web lookups. It is never written to settings files, prompts or logs. |
| `HOME_MANAGER_NODE` | The `node` executable for tax Engine 1, when it isn't the one on `PATH`. |
| `RUN_BROWSER_TESTS=1` | Test runs only: include the browser tests (same as `--browser`). |

The tax engine adapter always sets `OPENTAX_TELEMETRY=0` and `DO_NOT_TRACK=1` for Engine 1's process.

## Where things live

The app creates everything below. Keep the settings folder and the library folders separate.

**Settings folder** (`%LOCALAPPDATA%\HomeManager`, or `--control-dir`): this computer's settings.

| Path | Holds |
|---|---|
| `settings.json` | The library folder last opened. |
| `profiles.json`, `profiles/<id>/household.json` | Profiles ([family](family.md#profiles)) and each profile's financial preferences. |
| `vision.json`, `reasoning.json`, `reviewer.json`, `decision.json` | Model settings. Invalid saved settings fall back to defaults, which switch that model off. |
| `model_computer.json`, `gpu_token.txt` | Whether models run on this PC or a family GPU computer, and the member token (never returned by the API). |
| `gpu_host.json` | Only on a GPU host: its members and their token hashes. |
| `logs/home-manager.log` (+ `.1`–`.5`) | The diagnostic log (see [Diagnostic log](#diagnostic-log)). |
| `sessions/` | Temporary copies for an opened shared library; deleted at start. |
| `.home-manager.lock` | One process per settings folder. |

**Library folder** (one per individual profile):

| Path | Holds |
|---|---|
| `.home-manager-store`, `.home-manager.lock` | Store marker, and the lock (one process per library). |
| `inventory.sqlite3` (+ `-wal`, `-shm`) | The database ([schema map](development.md#schema-map)). |
| `inventory.before-vN.sqlite3` | A copy taken before a schema upgrade; the two newest are kept. These are recovery aids, not backups ([documents](documents.md#schema-upgrades-and-recovering-from-a-failed-one)). |
| `originals/<2 hex>/<sha256>.blob` | Every captured file, byte for byte, named by hash. |
| `extracted/` | Image previews and derived files that readings refer to. |
| `work/` | Temporary files while capturing. |
| `Library/Inbox` | Drop documents here; the app watches it. |
| `Library/<folder>/YYYY/MM/` | Filed documents ([documents](documents.md#the-managed-library)). |
| `Reports/<year>/` | CPA packs, kept outside `Library/` so they are never read back in ([taxes](taxes.md#cpa-pack)). |

**Family folder** (in a synced folder; [family](family.md)): `.home-manager-family`, `family.json`, `members/`, `view/`,
`library/` (the family inbox), and deliveries (`to-<member>/*.hmdelivery`). Shared-library exports are `.hmshare`
files, and family invites are `.hminvite`.

## Backups

**Settings → Backup & restore → Back up** writes a folder to a destination you choose (`library/backup.py`). It
contains:
- a consistent SQLite snapshot, made with SQLite's backup API, never a file copy;
- `originals/`, hash-checked as it is copied;
- `Library/` and `extracted/`;
- `manifest.json`, listing every file with its size and SHA-256.

The folder appears under its final name only once it is complete. Keep backups on a different disk from the library.
Backups record their `schema_version`.

A **restore** checks the whole backup first: manifest paths stay inside the backup, hashes match, `integrity_check`
passes, and the schema version is known. It then builds a **new** library in an empty folder you choose; the active
library is never touched.
- **Older and newer backups.** A backup from an older version restores and then upgrades. One from a newer version is
  refused.
- **Switching.** Switch to the restored folder in **Settings → Library folder**.
- **Cancelling.** A backup or restore can be cancelled from the activity list. If the app stops mid-backup, the backup
  is marked interrupted at the next start.

## Background work

- **Inbox watcher.** The `inbox-monitor` thread (`Manager.watch_inbox`) looks at `Library/Inbox` every 3 seconds. A file
  has to look the same (name, size, modified time) on two checks in a row before capture starts, and nothing starts
  while capture work is already running.
- **Watched folders.** Every 10 ticks (about 30 seconds), each enabled watched folder is checked the same way. Each is
  also rescanned once after start and every `rescan_hours` (default 6)
  ([documents](documents.md#watched-folders)).
- **Family checks.** Every 20 ticks (about a minute), the app checks the family folder for new snapshots and
  deliveries. A member's changed library is published to the family at most every 10 minutes
  (`PUBLISH_EVERY_SECONDS`).
- **Two work queues.** `capture` handles scans, backups, restores and indexing. `inference` handles model work. Each runs
  one job at a time. Model work, backups and restores can be cancelled; scans can't be interrupted.
- **Exchange rates** refresh in the background when a profile opens, if they are due. **Tax Zen** is re-evaluated in the
  background when a newer pay stub, tax form, tag or typed value arrives.
- **At each start**, when a library opens:
  - the database is checked and, if needed, upgraded;
  - capture intents and filing moves that didn't finish are replayed;
  - files queued for deletion from Trash are removed (`trash_cleanup`);
  - files in retired folders move on (`Bills` → `Unfiled`, `Income` → `Jobs`);
  - every model or lookup run left `queued` or `running` is marked `interrupted`, so it can be retried (each `*_runs`
    service's `recover()`);
  - readings not yet in the search index are indexed in the background.

## Diagnostics

### Diagnostic log

`core/logs.py` writes `<settings folder>/logs/home-manager.log`. The file rotates at 1 MB, and five old files are kept.
The launcher prints the log's path.
- **What it records:** what happened and where: event names, record and run ids, counts, and exception classes with
  their code tracebacks.
- **What it never records:** what a document says. Exception messages are left out because they can quote document
  text. So are amounts, merchant names and file names. This covers the web server's own tracebacks too
  (`PrivateFormatter`).
- **Failures.** Every failure the app turns into a stored "failed" state also writes a `log_failure` entry, so a failed
  run can be traced afterwards.

### Ledger health

`finance/health.py` checks rules the money data must keep but the schema can't enforce. It recomputes derived values
rather than trusting them:
- category shares add up to receipt and charge totals;
- a charge is matched to at most one receipt, in the same currency;
- a matched receipt's money is still counted somewhere;
- currencies are supported;
- statement balances;
- shared-record totals, and shares or typed references whose record is gone (`orphan_share`, `orphan_reference`);
- tax lots against sales and holdings.

Each problem names its rule and record id only. Ways to run it:
- `home-manager check-ledger` prints the report for every profile, reading each database read-only, so it works while
  the app is open.
- `GET /api/finance/health` returns the same list, plus whether each tax engine can run (`tax_engines`).
- Tests call `conftest.assert_ledger_healthy(store)` after ledger-changing scenarios.

For a deeper read-only check of a database file (integrity, type drift, orphans, unchecked values), see
[development](development.md#database-checks).

## Troubleshooting

| Symptom | What to do |
|---|---|
| The port is in use | Start with `--port 8766` (or any free port from 1024 to 65535). |
| "This directory is already in use by another Home Manager process." | Another Home Manager process, or `index-documents`, has it open. Close it. Only one process can own a settings folder or library at a time. |
| A tab left open from before a restart stops working | Each start makes a new session token. Open the new link printed in the terminal. |
| Model work fails right away, or "cannot connect" | Check that LM Studio's server is running at the saved URL and the model id matches exactly. Use **Test connection** in Settings → Local models. |
| Two models are loaded and the GPU runs out of memory | Leave **Keep one model loaded at a time** on, or turn on LM Studio's JIT "auto-evict". |
| The decision model's answers are all "unknown" | The model is answering with a thinking token. Use a model that answers directly ([documents](documents.md#decision-models)). |
| Web lookups say search is not configured | Set `HOME_MANAGER_BRAVE_API_KEY` and restart. |
| "Engine 1 needs Node.js 20 or later" | Install Node.js 20+, or point `HOME_MANAGER_NODE` at it, and restart. |
| Search misses documents you know are there | Close the app and run `home-manager index-documents --rebuild`. |
| "The library upgrade stopped at step NNN" | Leave the folder unchanged and follow [recovering from a failed upgrade](documents.md#schema-upgrades-and-recovering-from-a-failed-one). The log names the step. |
| A file stays `deferred` | Windows sharing: another program has it open for writing. Close it; the next look captures it. |
| Anything else | Look in `<settings folder>/logs/home-manager.log` (the path is printed at start). Run `home-manager check-ledger` if money totals look wrong. |
