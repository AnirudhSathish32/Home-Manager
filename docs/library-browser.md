# Library folders, settings and Trash

The sidebar opens **Home** (the default dashboard), **Finances**, **Documents** (with Inbox and Unfiled shortcuts), **Processing** (capture controls, scan history and model runs) and **Settings** (library folders, home currency, local models, independent checks). Home shows spending totals, monthly and category charts, attention counts and upcoming bills; chart links open filtered Finances records. Secondary document actions live in each row's **More actions** menu.

Receipt ledger extraction assumes USD when currency is missing, including when the vision model did not read a dollar sign. The assumption is recorded in extraction notes. Explicit currencies and the existing home-currency setting for compatible printed symbols take precedence; conflicting foreign-currency evidence is not replaced with USD.

## Folder layout

```text
01_Banking/
  Bank_Statements/
  Credit_Card_Statements/
02_Income/
  Pay_Stubs/
  Tax_Documents/
03_Purchases/
  Receipts/
  Invoices/
  Refunds_Returns/
04_Bills/
  Utilities/
  Subscriptions/
  Other_Bills/
05_Investments/
  Brokerage/
  Retirement/
06_Obligations/
  Housing/
  Loans/
  Insurance/
```

The browser also includes All documents, Unfiled and Trash. Parent folders show documents from their children. Counts and pagination are calculated across the library, not just the visible page. Each row's name is **Merchant - Location - Description**, for example "Target - Main St W - Snacks/Office": the seller (printed on the receipt, or inferred from a house brand and flagged for you to confirm), the store's street name (without building number, city or postal code; omitted when no street is printed) or Online for delivery orders, and a one-or-two-word description of what was bought. **Edit description…** in the row's menu or on the document page replaces the description part; Edit details on the document page corrects the merchant, location and date. The file name appears beneath, then type, the document's own date with its year, amount and one state such as Not read yet, Needs review or Recorded; hover the state for per-step detail. The name opens the document page. Rows offer one next step (Read, Record, Import transactions or Restore) and a **More actions** menu with Versions, Move and Delete. Select rows to read, move or delete several at once. Filter by state or document date, and sort by date, name, recently added or path.

These are virtual folders in Home Manager. Manual filing selects a fixed folder identifier; it never becomes an operating-system path, shell command or filename. Preserved blobs stay hash-addressed and original source files remain in their year/month directories.

## Automatic text extraction

Configure a local vision model and leave **Read newly scanned images automatically** enabled. Scanning transcribes new/changed PNG/JPEG captures, one request per distinct image. **Processing → Read all documents** processes existing image and PDF captures across folders and months; **Read selected** in Documents reads only the chosen ones.

Vision returns text only. New files keep their source filenames and remain Unfiled until manually moved. Automatic titles and classification await a separate reasoning model. Missing model settings do not prevent capture, but extraction requires a configured model. CSV/XLSX readers and PDF capture remain future work.

Historical results remain available. Scan history reports capture and extraction separately; API/database fields retain their older organization names for compatibility.

Use **Move** to correct a folder. The manual choice overrides model classification for that occurrence and exact source hash, including after reprocessing. Identical documents at other source paths can be organized independently. Changed content needs a fresh folder decision; it does not inherit a manual choice for an older version.

## Delete and restore

**Delete** opens a confirmation dialog naming the document and source path. **Delete to Trash** removes that occurrence from active views and future parsing batches. It retains originals, extraction history and the source file on disk. Trash offers **Restore** and **Empty trash…**. Empty trash permanently removes all trashed documents across filters and pages after confirmation, including managed copies, preserved versions, readings and associated ledger records. Evidence still used by other documents is retained. External originals and existing backups remain; rescanning an external original can add it again after permanent deletion. Edited managed files block deletion so edits can be preserved first. Running background work must finish before emptying Trash. Interrupted file removal is retried on restart or the next Empty trash action.

Rescanning does not resurrect a trashed entry, even if the source still exists. A newly discovered path is a distinct entry. Removing one entry does not remove another entry that shares identical bytes. Restoring retains a manual folder if its source hash still matches. Library changes are refused while capture/parsing is active; stale source hashes require refreshing and reconfirming. The model has no delete/restore capability.

Authenticated API actions record manual moves, deletion and restoration in `library_events`. Schema 4 adds persistent Trash state, per-version manual folder overrides and scan-organization status. Existing schema 1–3 stores receive a SQLite backup at `inventory.before-v4.sqlite3` before upgrade.

## Manual checks

- Open the gear; verify both settings tabs and keyboard navigation.
- Scan a new image with a configured model; verify its transcription appears under its source filename in Unfiled without pressing the batch button.
- Move it to a different leaf folder; reprocess and confirm the manual choice remains.
- Cancel a Delete confirmation; verify the document is unchanged.
- Confirm Delete, rescan and restart; verify it remains in Trash, and that the source file still exists.
- Restore it; verify it returns to its folder with preserved results.
- Compare transcription with your image. Synthetic tests verify plumbing and persistence, not model accuracy.
