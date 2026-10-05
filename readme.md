# Home Manager

Home Manager is a local-first household document and money assistant. It runs on your own computer, and its models run on a local server (LM Studio) or on a family member's GPU computer. Nothing is sent to a cloud model.

Drop documents into the app-owned **Library/Inbox** (or a watched folder): receipts, bank and card statements, CSV/XLSX exports, pay stubs, tax forms, policies, leases. Home Manager keeps every original byte for byte. A local vision model reads each document, and the app files it into Library folders. Typed extraction proposes ledger records with citations to the source text. A record counts only when every check passes or you approve it in **Review**.

What is built:
- **Documents:** capture, reading (images, PDFs, CSV/XLSX), several receipts in one file, several images as one document, automatic filing, independent checks, full-text search. See [documents](docs/documents.md).
- **Money:** receipts and statements reconciled against each other, item-level categories, budgets and rules, recurring bills, currency conversion, a Home dashboard. See [money](docs/money.md).
- **Planning:** a long-range forecast with assets and loans, What If plans and a paycheck planner, investment accounts with lots, RMDs and specific kinds. See [planning](docs/planning.md).
- **Taxes:** pay stubs with a tax breakdown, tax tags, the year's return worked out by two open-source tax engines, Tax Zen (the W-4 that brings the year to $0), and a year-end CPA pack. See [taxes](docs/taxes.md).
- **Household items:** inventory from receipt lines, run-out check-ins, returns, warranties. See [household](docs/household.md).
- **Ask:** an assistant that answers from read-only tools. See [assistant](docs/assistant.md).
- **Profiles, family and sharing:** a library per person, a family view and inbox, encrypted `.hmshare` exports, and a shared GPU for family and testers. See [family](docs/family.md).

## Quick start (PowerShell)

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m home_manager
```

1. Open the private session link printed in the terminal. It is a new link each start, and the terminal also shows the log's path.
2. In **Settings → Library folder**, choose an empty folder for your library.
3. Start LM Studio's server (default `http://127.0.0.1:1234/v1`). In **Settings → Local models**, save the vision and reasoning model IDs.
4. Drop files into `Library/Inbox`. They are captured and read automatically. Approve what the models propose in **Review**.

Options: `--port 8766`, and `--control-dir DIR` for a different settings folder. Other commands are `home-manager check-ledger`, `home-manager index-documents --rebuild` and `home-manager gpu-host`. The tax engines need Node.js 20+ (Engine 1) and optionally `pip install -e ".[engine2]"`. For all commands, extras, environment variables, where files live, backups and troubleshooting, see **[operations](docs/operations.md)**.

## Development

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test,dev]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m mypy
```

For tests (including the opt-in browser tests), checks and adding a migration, see [development](docs/development.md). Every doc is listed in the [docs index](docs/README.md); open work is in [open work](docs/open-work.md).
