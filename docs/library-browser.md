# Library folders, settings and Trash

Status: built; folder layout updated 2026-09-30 to match `core/folders.py`.

The sidebar has **Search**, **Home** (the default dashboard) and **Review** at the top; a **Money** group (Transactions, Receipts & statements, Spending & budgets, Bills & recurring, Accounts, Investments, Taxes, Forecast, What If); **Household** (Inventory); **Records** (Documents, with Inbox and Unfiled shortcuts); and at the foot **Ask** (the assistant), **Processing** (capture controls, scan history and model runs) and **Settings** (profiles and library folder, home currency, local models, independent checks). Secondary document actions live in each row's **More actions** menu.

Receipt ledger extraction assumes USD when currency is missing, including when the vision model did not read a dollar sign. The assumption is recorded in extraction notes. Explicit currencies and the existing home-currency setting for compatible printed symbols take precedence; conflicting foreign-currency evidence is not replaced with USD.

## Folder layout

Flat folders in two groups ([receipts and statements](receipts-and-statements.md)):

```text
Money (the ledger counts and reconciles these)
  Receipts/
  Bank_Statements/
  Credit_Card_Statements/
Documents (papers kept because they matter)
  Housing/
  Insurance/
  Investments/
  Jobs/<Employer>/Paystubs/ and Jobs/<Employer>/Documents/
  Loans/
  Taxes/
Unfiled/
```

On disk each is `Library/<folder>/YYYY/MM/` ([operations](operations.md#where-things-live)). The retired `Bills` and `Income` folders are emptied at startup into `Unfiled` and `Jobs`. The original nested layout (`01_Banking/…06_Obligations/…`) survives only as `LEGACY_HIERARCHY`, so old folder names in history still resolve.

The browser also includes All documents, Inbox, Unfiled and Trash. Counts and pagination are calculated across the library, not just the visible page. Each row's name is **Merchant - Location - Description**, for example "Target - Main St W - Snacks/Office": the seller (printed on the receipt, or inferred from a house brand and flagged for you to confirm), the store's street name (without building number, city or postal code; omitted when no street is printed) or Online for delivery orders, and a one-or-two-word description of what was bought. **Edit description…** in the row's menu or on the document page replaces the description part; Edit details on the document page corrects the merchant, location and date. The file name appears beneath, then type, the document's own date with its year, amount and one state such as Not read yet, Needs review or Recorded; hover the state for per-step detail. The name opens the document page. Rows offer one next step (Read, Record, Import transactions or Restore) and a **More actions** menu with Versions, Move and Delete. Select rows to read, move or delete several at once. Filter by state or document date, and sort by date, name, recently added or path.

These are virtual folders in Home Manager. Manual filing selects a fixed folder identifier; it never becomes an operating-system path, shell command or filename. Preserved blobs stay hash-addressed and original source files remain in their year/month directories.

## Automatic text extraction

Configure a local vision model and leave **Read newly scanned images automatically** enabled. Scanning transcribes new/changed PNG/JPEG captures, one request per distinct image. **Processing → Read all documents** processes existing image and PDF captures across folders and months; **Read selected** in Documents reads only the chosen ones.

Vision returns text only. The separate reasoning model then titles, classifies and extracts each document, and the app files it from those cited results; documents it cannot file stay Unfiled. Missing model settings do not prevent capture, but extraction requires a configured model. PDFs are read like images (embedded text, vision for scanned pages); CSV/XLSX files import transactions without a model.

Historical results remain available. Scan history reports capture and extraction separately; API/database fields retain their older organization names for compatibility.

Use **Move** to correct a folder. The manual choice overrides model classification for that occurrence and exact source hash, including after reprocessing. Identical documents at other source paths can be organized independently. Changed content needs a fresh folder decision; it does not inherit a manual choice for an older version.

## Delete and restore

**Delete** opens a confirmation dialog naming the document and source path. **Delete to Trash** removes that occurrence from active views and future parsing batches. It retains originals, extraction history and the source file on disk. Trash offers **Restore** and **Empty trash…**. Empty trash permanently removes all trashed documents across filters and pages after confirmation, including managed copies, preserved versions, readings and associated ledger records. Evidence still used by other documents is retained. External originals and existing backups remain; rescanning an external original can add it again after permanent deletion. Edited managed files block deletion so edits can be preserved first. Running background work must finish before emptying Trash. Interrupted file removal is retried on restart or the next Empty trash action.

Rescanning does not resurrect a trashed entry, even if the source still exists. A newly discovered path is a distinct entry. Removing one entry does not remove another entry that shares identical bytes. Restoring retains a manual folder if its source hash still matches. Library changes are refused while capture/parsing is active; stale source hashes require refreshing and reconfirming. The model has no delete/restore capability.

Authenticated API actions record manual moves, deletion and restoration in `library_events`. Migration 004 added persistent Trash state, per-version manual folder overrides and scan-organization status ([schema map](schema.md)).

## Manual checks

- Open the gear; verify both settings tabs and keyboard navigation.
- Scan a new image with a configured model; verify its transcription appears under its source filename in Unfiled without pressing the batch button.
- Move it to a different leaf folder; reprocess and confirm the manual choice remains.
- Cancel a Delete confirmation; verify the document is unchanged.
- Confirm Delete, rescan and restart; verify it remains in Trash, and that the source file still exists.
- Restore it; verify it returns to its folder with preserved results.
- Compare transcription with your image. Synthetic tests verify plumbing and persistence, not model accuracy.
