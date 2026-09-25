# Managed Library — Phase 1

Implemented from `Home_Manager_Architecture_Implementation_Spec.docx`. The application still preserves immutable evidence and treats financial interpretation as unreviewed.

## Workflow

Restart Home Manager to apply pending schema migrations. Existing stores receive one SQLite-consistent `inventory.before-vN.sqlite3` snapshot (N = the latest schema version) before changes. This same-directory snapshot is for migration recovery, not an independent disaster-recovery backup; export/restore is a later milestone.

The configured managed root now contains `Library/Inbox`, `Unfiled`, `Bank_Statements`, `Credit_Card_Statements`, `Receipts`, `Income`, `Bills`, `Taxes`, `Investments`, `Loans`, `Insurance` and `Housing`.

- **External imports:** keep using the existing read-only `YYYY/MM` scanner. Captured files get independent managed copies. External names and bytes are unchanged.
- **Inbox:** place PNG/JPEG, CSV or XLSX files directly into `Library/Inbox`, then choose **Processing → Scan Inbox**. No year/month folders are needed here. Subfolders, links and unsupported formats are reported, not silently traversed. Files are hashed, fsynced, verified and registered before any organization.
- **Automatic filing after analysis:** a successful saved analysis with cited classification and unambiguous merchant/issuer and date metadata can file the managed copy. Receipts use purchase date; statements use period end; other supported documents use issue date. This narrow adapter uses the existing interpretation contract until the dedicated classifier/extractors in Phase 5. Missing/unknown metadata goes to Unfiled; no confidence threshold is invented.
- **Manual filing:** Move now moves the app-owned physical Library file. A manual choice takes precedence over future automatic filing for the same captured version.
- **Trash:** still requires confirmation and remains a logical, restorable library action. It does not delete source files, managed files or evidence from disk.

Unclassified Inbox files stay in Inbox. External files without classification appear in Unfiled. The document list includes the original source name, managed path, organization reason and any blocked-organization error. The Inbox count represents captured documents; Scan Inbox discovers newly dropped files. There is no filesystem watcher yet.

## Filenames and integrity

Trusted code selects an allow-listed folder and generates the basename. It uses validated dates, a conservative merchant/issuer label where available, a content-hash suffix and document ID. It preserves the extension and never embeds original filenames or account references. Digits are removed from model-derived labels to prevent account numbers leaking through merchant text. A deterministic full-hash fallback handles short-name collisions without overwriting unrelated files.

Library copies do not share an inode with immutable blobs. Editing a managed copy cannot change the evidence. An edited managed file blocks movement rather than being overwritten. Preserve that edit and rescan it through Inbox, or restore the expected copy before retrying. A changed Inbox file creates a captured version; its previous captured bytes remain in the evidence store and a separate managed version copy.

## Durable organization

Every organization records an intent before touching files: document/version hash, app-owned source path if any, target folder/name, action, reason and timestamps. Windows uses non-overwriting rename for existing managed files. Independent copies are staged, flushed, hash-verified and atomically published without clobbering a destination. Other platforms publish the verified copy before removing the verified app-owned source. The database records the final path and an organization event only after verification.

Startup retries pending/blocked intents and fills gaps after a capture committed but before organization began. Repeated scans and recovery do not create duplicate copies. Hash mismatches, changed versions and unavailable storage preserve evidence and retain diagnostic state; paths outside Library are never organization destinations.

Migration 007 explicitly maps legacy folders to flat folders and appends migration events. Existing folder events and parsing/organization JSON remain historical evidence. Migration 008 adds managed paths/intents/events and marks Inbox occurrences separately from external roots. Inbox folder-period values are 0 (no source folder period), never an inferred financial date.

## Next phases

Phases 2–8 (telemetry and cancellation, PDF reading, canonical finance, typed extraction, CSV/XLSX import, reconciliation and deterministic tools) are described in [v2-phases.md](v2-phases.md). The agent and email ingestion remain later phases. Current configuration still includes the legacy external source root; Inbox is an additional import route. No private live database was migrated during development tests.
