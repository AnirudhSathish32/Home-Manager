# Managed Library — Phase 1

Implemented from `Home_Manager_Architecture_Implementation_Spec.docx`. The application still preserves immutable evidence and treats financial interpretation as unreviewed.

## Workflow

Restart Home Manager to apply pending schema migrations. Existing stores receive one SQLite-consistent `inventory.before-vN.sqlite3` snapshot (N = the latest schema version) before changes. This same-directory snapshot is for migration recovery, not an independent disaster-recovery backup; use Backup for that. After an upgraded store opens, only the two newest snapshots are kept. Older ones are deleted only when the newest snapshot passes SQLite's integrity check, and only files with the exact `inventory.before-vN.sqlite3` name.

The configured managed root now contains `Library/Inbox`, `Unfiled`, `Bank_Statements`, `Credit_Card_Statements`, `Receipts`, `Income`, `Bills`, `Taxes`, `Investments`, `Loans`, `Insurance` and `Housing`.

- **Inbox:** the only way documents enter the library. Place PNG/JPEG, PDF, CSV or XLSX files directly into `Library/Inbox`; they are captured automatically while the app runs, or choose **Processing → Scan Inbox**. No year/month folders are needed here. Subfolders, links and unsupported formats are reported, not silently traversed. Files are hashed, fsynced, verified and registered before any organization.
- **Automatic filing after analysis:** a successful saved analysis with cited classification and unambiguous merchant/issuer and date metadata can file the managed copy. Receipts use purchase date; statements use period end; other supported documents use issue date. This narrow adapter uses the existing interpretation contract until the dedicated classifier/extractors in Phase 5. Missing/unknown metadata goes to Unfiled; no confidence threshold is invented.
- **Manual filing:** Move now moves the app-owned physical Library file. A manual choice takes precedence over future automatic filing for the same captured version.
- **Trash:** still requires confirmation and remains a logical, restorable library action. It does not delete source files, managed files or evidence from disk.

Unclassified Inbox files stay in Inbox. The document list includes the original Inbox name, managed path, organization reason and any blocked-organization error. The Inbox count represents captured documents waiting to be filed.

## Year/month folders

Category folders are organized by the document's own date: `Receipts/2026/09/2026-09-22__Cafe__Receipts__….png`. The date is the ledger record's (purchase date for receipts, period end for statements, due or issue date for bills, pay date for income), or the cited date the document was filed with. `Inbox` and `Unfiled` stay flat. A category document with no known date stays at the top of its category until a date is known, then moves into its month. The app only ever creates `YYYY/MM` folders; a library path is either `Folder/name` or `Category/YYYY/MM/name`.

Moves keep the known date in both the name and the folder. A move that leaves a month or year folder empty removes that empty folder; category folders stay. At startup, every file, including older versions' copies, is checked and moved into its month with the same durable, verified, never-overwriting organization intents; files filed before this layout existed move there on the first start. Names never change during these moves, and the application's folders and views are unchanged.

## Filenames and integrity

Trusted code selects an allow-listed folder and generates the basename. It uses validated dates, a conservative merchant/issuer label where available, a content-hash suffix and document ID. It preserves the extension and never embeds original filenames or account references. Digits are removed from model-derived labels to prevent account numbers leaking through merchant text. A deterministic full-hash fallback handles short-name collisions without overwriting unrelated files.

Library copies do not share an inode with immutable blobs. Editing a managed copy cannot change the evidence. An edited managed file blocks movement rather than being overwritten. Preserve that edit and rescan it through Inbox, or restore the expected copy before retrying. A changed Inbox file creates a captured version; its previous captured bytes remain in the evidence store and a separate managed version copy.

## Durable organization

Every organization records an intent before touching files: document/version hash, app-owned source path if any, target folder/name, action, reason and timestamps. Windows uses non-overwriting rename for existing managed files. Independent copies are staged, flushed, hash-verified and atomically published without clobbering a destination. Other platforms publish the verified copy before removing the verified app-owned source. The database records the final path and an organization event only after verification.

Startup retries pending/blocked intents and fills gaps after a capture committed but before organization began. Repeated scans and recovery do not create duplicate copies. Hash mismatches, changed versions and unavailable storage preserve evidence and retain diagnostic state; paths outside Library are never organization destinations.

Migration 007 explicitly maps legacy folders to flat folders and appends migration events. Existing folder events and parsing/organization JSON remain historical evidence. Migration 008 adds managed paths/intents/events and marks Inbox occurrences separately from external roots. Inbox folder-period values are 0 (no source folder period), never an inferred financial date.

## Next phases

Phases 2–8 (telemetry and cancellation, PDF reading, canonical finance, typed extraction, CSV/XLSX import, reconciliation and deterministic tools) are described in [v2-phases.md](v2-phases.md). The agent and email ingestion remain later phases. The earlier read-only `YYYY/MM` source folder was removed (2026-09-25); Inbox is the only import route. Documents captured from a source folder by older versions stay in the library. No private live database was migrated during development tests.
