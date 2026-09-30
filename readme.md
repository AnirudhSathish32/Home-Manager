# Home Manager

Home Manager is a local-first household document and money assistant. It runs on your own computer, and its models run on a local server (LM Studio) or on a family member's GPU computer. Nothing is sent to a cloud model.

Drop documents into the app-owned **Library/Inbox**: receipts, bank and card statements, CSV/XLSX exports, pay stubs, tax forms, policies, leases. Home Manager keeps every original byte for byte. A local vision model reads each document, and the app files it into Library folders. Typed extraction proposes ledger records with citations to the source text. Nothing counts until you approve it in **Review**.

What is built:
- **Money:** receipts and statements reconciled against each other, transfers and refunds, budgets and categories, recurring bills, a ledger health check. See [receipts and statements](docs/receipts-and-statements.md) and [money, review and inventory](docs/money-review-inventory.md).
- **Home, forecast and What If:** a dashboard, a long-range forecast with assets and loans, and saved scenarios with plan-vs-actual. See [forecast](docs/forecast.md) and [What If](docs/what-if.md).
- **Jobs, investments and taxes:** pay stubs with a tax breakdown; investment accounts, lots, RMDs and withdrawals; tax tags; the year's return estimate; Tax Zen. See [jobs and paystubs](docs/jobs-and-paystubs.md), [investments](docs/investments.md) and [taxes](docs/taxes.md).
- **Household items:** inventory from receipt lines, returns, warranties. See [household items](docs/household-items.md).
- **Search and Ask:** full-text search of document text, and an assistant that answers from read-only tools. See [document search](docs/document-search.md) and [assistant](docs/assistant.md).
- **Profiles, family and sharing:** a library per person, a family view and inbox, encrypted `.hmshare` exports, and a shared family GPU. See [sharing](docs/sharing.md).

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

Options: `--port 8766`, and `--control-dir DIR` for a different settings folder. Other commands are `home-manager check-ledger`, `home-manager index-documents --rebuild` and `home-manager gpu-host`. For all commands, extras, environment variables, where files live, backups and troubleshooting, see **[operations](docs/operations.md)**.

## Development

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test,dev]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m mypy
```

For tests (including the opt-in browser tests), checks and adding a migration, see [development](docs/development.md). Every doc is listed in the [docs index](docs/README.md).
