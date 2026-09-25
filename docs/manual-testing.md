# Run and manually test D1–D2

Implemented: configurable local directories, immutable capture/history, and PNG/JPEG text-only vision transcription, batch extraction and QR decoding. Interpretation, titles and classification await a separate reasoning model. See [receipt manual testing](receipt-parsing.md) for model setup and the batch button. No financial posting, Gmail or Excel report generation yet.

## Start on Windows

From PowerShell in this repository:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m home_manager
```

Dependencies are already installed in this workspace. On a new checkout, create the environment with Python 3.13 or newer first: `py -3.13 -m venv .venv`.

Open the private `http://127.0.0.1:8765/#token=...` link printed by the launcher. It grants access to this running session; do not share it. The page removes the fragment from its address and stores the token in that browser tab's session storage. A new server launch needs its new link. The server binds only to loopback and rejects other Host/Origin values. Stop it with Ctrl+C. Normal shutdown waits for an active scan; force termination is recovered on the next launch.

No browser is opened automatically. If port 8765 is busy, run with `--port 8766`. Settings normally live in `%LOCALAPPDATA%\HomeManager\settings.json`. `--control-dir C:\SomeDedicatedFolder` selects a different settings location; it must remain separate from source/managed directories. Only one process can own a settings directory or managed store at a time.

## Choose directories in the UI

Open **Settings → Library & sources** in the sidebar. Model settings live under **Settings → Local models**. See [the folder browser and Trash](library-browser.md) for automatic post-scan organization and deletion/restoration.

For example:

```text
C:\Household\sources\2026\09\statement.csv
C:\Household\sources\2026\09\credit-card.xlsx
C:\Household\sources\2026\09\receipt.jpg
C:\Household\managed\
```

Set **Source directory** to `C:\Household\sources`, not to the individual month. It must exist. Set **Managed-data directory** to a separate empty folder (the app can create it) or a store this app already initialized. Paste absolute paths; native folder-picker integration is deferred. Keep these locations outside the repository, application settings, shared/cloud-synced folders and network drives. Existing nonempty personal folders cannot be selected as managed stores.

The source directory is read only to the application. The app creates its marker, process lock, SQLite inventory, `originals/` and `work/` only in managed storage. Source and managed paths cannot overlap; Windows links/junctions/reparse points are rejected. Use a local filesystem with hard-link support, such as NTFS. Captured bytes are published using an internal hard link for atomic no-overwrite publication; originals are never hard-linked to source files.

Changing managed directories selects a different independent library; it does not migrate or delete the previous one. Changing the source directory preserves older source history in the same database; the document list shows the currently selected root. Settings cannot change during a scan.

## Manual checks

Use copies of your documents when deliberately testing edits, rename or deletion.

| Action | Expected result |
| --- | --- |
| Add supported files beneath `2026/09`, save directories, then scan | `captured` entries and hashes in the document library; inputs unchanged |
| Scan again without editing anything | `unchanged`; no additional preserved blob or version |
| Copy identical bytes to a new filename or month | `duplicate`; distinct source path, same content hash and shared preserved bytes |
| Edit a source file at the same path and rescan | `new_version`; View versions shows both hashes |
| Rename a file and scan all relevant months | New occurrence reuses existing bytes; old path becomes `missing` |
| Delete a source copy and rescan | `missing`; original captures and previous versions remain |
| Scan only September after moving a file out of August | Only September's selected scope is assessed for missing files; scan August/all months to reconcile the old path |
| Leave a `.part`, `.tmp`, or `~$` file in the month | `ignored`, not captured |
| Add a PDF, legacy XLS or another unsupported extension | `unsupported`, visible in scan results; no capture |
| Add a file outside YYYY/MM or beneath month `13` | `invalid_folder`; invalid folders are not traversed |
| Keep a source file open for writing while scanning | File may be `deferred` due to Windows sharing; close the writer and rescan |
| Restart the app | Settings, inventory, versions and scan history persist |

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

An optional real-browser smoke test uses installed Microsoft Edge in headless mode:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test,browser-test]"
$env:RUN_BROWSER_TESTS = '1'
.\.venv\Scripts\python.exe -m pytest -q
```

This verifies directory setup, scans, edited-file versions and browser authentication with synthetic files. Without the environment flag, the browser test is skipped. Current upstream test-client dependencies emit deprecation warnings; these do not affect the capture tests.

## Implementation note

D1–D2 use the Python SQLite driver behind `Store`; schema 2 adds receipt parsing runs and backs up schema 1 before upgrading. The earlier SQLAlchemy/Alembic recommendation remains a future persistence decision. Image preparation and barcode decoding use a separate process with Windows resource limits; OS access confinement is not implemented. See [receipt parsing](receipt-parsing.md) for the precise security boundary.
