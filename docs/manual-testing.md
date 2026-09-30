# Run and manually test Home Manager

Updated 2026-09-30. This page covers starting the app, the capture checks (the original D1–D2 slice) and a manual check list for each built feature. Commands, settings files and troubleshooting are in [operations](operations.md). Automated tests are in [development](development.md). Not built yet: Gmail/email ingestion, the Excel report and currency conversion ([milestones](milestones.md)).

## Start on Windows

From PowerShell in this repository:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m home_manager
```

Dependencies are already installed in this workspace. On a new checkout, create the environment with Python 3.13 or newer first: `py -3.13 -m venv .venv`.

Open the private `http://127.0.0.1:8765/#token=...` link printed by the launcher. It grants access to this running session; do not share it. The page removes the fragment from its address and stores the token in that browser tab's session storage. A new server launch needs its new link. The server binds only to loopback and rejects other Host/Origin values. Stop it with Ctrl+C. Normal shutdown waits for an active scan; force termination is recovered on the next launch.

No browser is opened automatically. If port 8765 is busy, run with `--port 8766`. Settings normally live in `%LOCALAPPDATA%\HomeManager\settings.json`. `--control-dir C:\SomeDedicatedFolder` selects a different settings location; it must remain separate from the library folder. Only one process can own a settings directory or managed store at a time.

## Choose the library folder

Open **Settings → Library folder** in the sidebar. Model settings live under **Settings → Local models**. See [the folder browser and Trash](library-browser.md) for automatic filing and deletion/restoration.

Set **Managed library folder** to a separate empty folder (the app can create it) or a store this app already initialized, for example `C:\Household\managed`. Paste an absolute path; native folder-picker integration is deferred. Keep it outside the repository, application settings, shared/cloud-synced folders and network drives. Existing nonempty personal folders cannot be selected as managed stores. Windows links/junctions/reparse points are rejected. Use a local filesystem with hard-link support, such as NTFS; captured bytes are published through an internal hard link for atomic no-overwrite publication.

Documents enter the library only through its Inbox, `<library>\Library\Inbox`. Drop files directly into it (no subfolders). While the app runs, new files are captured automatically; **Processing → Scan Inbox** captures them at once. Changing the library folder selects a different independent library; it does not migrate or delete the previous one. Settings cannot change during a scan.

## Manual checks

Use copies of your documents when deliberately testing edits, rename or deletion.

| Action | Expected result |
| --- | --- |
| Drop supported files into Inbox, then scan | `captured` entries and hashes in the document library |
| Scan again without editing anything | `unchanged`; no additional preserved blob or version |
| Drop identical bytes under a new filename | `duplicate`; same content hash and shared preserved bytes |
| Edit an Inbox file in place and rescan | `new_version`; View versions shows both hashes |
| Rename an Inbox file and rescan | New occurrence reuses existing bytes; old name becomes `missing` |
| Delete an Inbox file before it is filed, then rescan | `missing`; captures and previous versions remain |
| Leave a `.part`, `.tmp`, or `~$` file in Inbox | `ignored`, not captured |
| Add a legacy XLS or another unsupported extension | `unsupported`, visible in scan results; no capture |
| Put a folder inside Inbox | `invalid_folder`; subfolders are not traversed |
| Keep an Inbox file open for writing while scanning | File may be `deferred` due to Windows sharing; close the writer and rescan |
| Restart the app | Settings, inventory, versions and scan history persist |

## Feature checks

Use synthetic or copied documents and a scratch library folder (`--control-dir` with a scratch settings folder keeps your real profiles untouched). Each feature doc describes the expected behavior in detail.

| Area | Check | Doc |
| --- | --- | --- |
| Reading and extraction | With vision and reasoning models set, drop a receipt image. It is read automatically; **Extract to ledger** on the document page proposes a receipt with cited values that waits in **Review**. | [V2 phases](v2-phases.md), [receipt parsing](receipt-parsing.md) |
| Statements and reconcile | Import a CSV/XLSX export with **Import transactions**, or drop a statement PDF. Its lines wait uncounted until you **Reconcile** receipts against them; matched receipts are then replaced by their card line. | [receipts and statements](receipts-and-statements.md) |
| Budgets, rules, recurring bills | Set a budget, categorize a line with a rule, confirm a proposed recurring bill; Home shows it under upcoming bills. | [money, review and inventory](money-review-inventory.md) |
| Items, returns, warranties | Approve an itemized receipt; its lines appear in Inventory, with a return window and (after a lookup) a warranty. Lookups need `HOME_MANAGER_BRAVE_API_KEY`. | [household items](household-items.md), [items, assets and search](items-assets-search.md), [warranties](warranties-assistant-processing.md) |
| Search and Ask | Search for a word printed in a document; ask the assistant a spending question and a "what does my lease say…" question. Figures in answers come from cited tools. | [document search](document-search.md), [assistant](assistant.md) |
| Jobs and paystubs | Drop a pay stub; it files under `Jobs/<Employer>/Paystubs`, and its tax breakdown shows once the year's tax table is confirmed. | [jobs and paystubs](jobs-and-paystubs.md) |
| Investments | Drop a brokerage statement and a trade confirmation; check holdings, lots, and **Not this payment** undo on a matched contribution. | [investments](investments.md) |
| Forecast and What If | Add an asset and a loan; open the forecast. Save a scenario, adopt it, and check plan-vs-actual next month. | [forecast](forecast.md), [What If](what-if.md) |
| Taxes | Tag a business expense and an itemized deduction; open the year's estimate and Tax Zen's W-4 advice. | [taxes](taxes.md) |
| Profiles, family, sharing | Add a second profile with its own library; make a family and check the family view and inbox; export a `.hmshare` and open it with **Open shared**. | [sharing](sharing.md) |
| Shared GPU | Run `home-manager gpu-host serve` on one computer, `add-member`, and point another profile's **Local models** at it. | [shared GPU](shared-gpu-plan.md) |
| Backup and restore | **Back up** to another folder, then **Restore** into a new empty folder and switch to it; documents and ledger match. | [operations](operations.md#backup-and-restore) |
| Ledger health | `home-manager check-ledger` while the app runs; it should report 0 errors. | [architecture](architecture.md#diagnostics-and-checks) |

Use **View versions** to inspect each content hash or open a historical receipt image. The `originals/<first-two-hash-characters>/<sha256>.blob` file contains exactly the captured bytes; its extension is intentionally neutral. The receipt viewer supports PNG/JPEG only. You can verify a preserved file's hash using PowerShell `Get-FileHash -Algorithm SHA256 -LiteralPath '...'`.

## Status and limits

- `completed`: all supported discovered candidates captured; ignored temporary files are possible. This never means a month has complete financial coverage.
- `partial`: one or more unsupported, invalid, deferred or rejected entries. Read the per-file results and rescan after resolving issues.
- `failed`: the scan could not finish. Completed captures remain; missing-file detection is not applied after an incomplete inventory.
- `interrupted`: an earlier process ended mid-scan. Startup recovers durable capture intents where possible; run a new scan to complete discovery.

Defaults: 256 MiB per file, 5 GiB of unique evidence, 100,000 entries per scan, and a one-second stability observation interval. Temporary copies, SQLite metadata and history require additional disk space. These are currently service configuration values, not UI settings. Every scan rereads and hashes supported files; this is deliberately more reliable than relying on size/mtime alone for D1–D2. Large libraries may take time. Use year/month scopes to limit work.

File extensions identify capture eligibility only. The app has not validated CSV syntax, workbook structure, image decoding or readability. “Captured” means preserved bytes, never “financially verified.” Empty files are rejected. Source files removed from disk are not auto-deleted from managed storage. If a stored blob fails its integrity check, it is not overwritten; restore from a known-good backup before continuing.

`present` in the library means the latest source observation was captured successfully. `not_captured`, `unavailable` or `rejected` means the source could not be verified on the latest attempt; any displayed hash remains the last successful capture, not a claim about the source's current contents.

The app assumes a trusted local Windows user account. It does not install encryption, custom ACLs, backup automation or antivirus controls. Protect the selected folders using your normal Windows account and encrypted disk/backup setup. Application immutability prevents app overwrites; an OS user with write access can still modify managed files. Do not manually edit the inventory or captures.

## Automated checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests use synthetic documents in temporary directories. They cover copy/edit/rename/delete, repeated scans, scopes, crashes between capture publication and database commit, Windows sharing semantics, path validation, quotas, auth, and persistence. The symlink integration test skips when Windows does not permit symlink creation; other path checks still run. Actual source documents are never used by the test suite.

Opt-in browser tests use the installed Microsoft Edge in headless mode:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test,browser-test]"
.\.venv\Scripts\python.exe -m pytest -q --browser
```

`--browser` is the same as setting `RUN_BROWSER_TESTS=1`. About a dozen test files have browser cases (Home, Review, family, search, taxes, What If, investments and others); see [development](development.md#tests). Without the flag they are skipped.

## Implementation note

The library uses the Python SQLite driver behind `Store`; the schema is upgraded by numbered scripts (047 as of 2026-09-30) with a copy taken before each upgrade ([schema map](schema.md), [managed library](managed-library.md)). Image preparation and barcode decoding use a separate process with Windows resource limits; OS access confinement is not implemented. See [receipt parsing](receipt-parsing.md) for the precise security boundary.
