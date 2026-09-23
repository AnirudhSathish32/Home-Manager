# Library folders, settings and Trash

The top-right gear opens Settings with **Directories** and **Local model** tabs. **Inspect documents** is the default workspace; **Scan documents** contains capture controls/history. Directory settings are no longer part of the main page.

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

The browser also includes All documents, Unfiled and Trash. Parent folders show documents from their children. Counts and pagination are calculated across the library, not just the visible page. Titles and source paths appear together, with Inspect document, Versions, Move and Delete actions.

These are virtual folders in Home Manager. Model output selects a fixed folder identifier; it never becomes an operating-system path, shell command or filename. Preserved blobs stay hash-addressed and original source files remain in their year/month directories.

## Automatic organization

1. Configure a running image-capable local model under Settings → Local model.
2. Leave **Read and organize newly scanned images automatically** enabled (the default).
3. Scan the source folders. After capture, a serial batch reads new/changed PNG/JPEG images and generates complete transcription, title and a folder selection in one model call per distinct image.
4. Open Inspect documents to see files appear in their assigned folders. Review classifications; they are unverified model output.

Only images newly captured, duplicated to a new path, or changed during that scan enter its automatic batch. Unchanged files are not repeatedly sent to the model. The manual **Parse and organize all images** action processes all active preserved images, independent of the folder currently being browsed. Reprocessing uses the current classification prompt version, so old title-only results can gain folders.

Uncertain documents are assigned Unfiled. Model/schema failures leave new documents Unfiled with failed parsing status. CSV/XLSX are captured but need their content readers before automatic classification; they can be moved manually. PDF capture remains a later slice. Without a configured model, captures still work and remain Unfiled. Scan history separately reports capture and organization status. An unavailable model never deletes a capture or silently substitutes a guess based on its filename.

Use **Move** to correct a folder. The manual choice overrides model classification for that occurrence and exact source hash, including after reprocessing. Identical documents at other source paths can be organized independently. Changed content needs a fresh folder decision; it does not inherit a manual choice for an older version.

## Delete and restore

**Delete** opens a confirmation dialog naming the document and source path. **Delete to Trash** removes that occurrence from active views and future parsing batches. It retains originals, extraction history and the source file on disk. Trash offers **Restore**. There is no permanent purge or disk-space reclamation in this release.

Rescanning does not resurrect a trashed entry, even if the source still exists. A newly discovered path is a distinct entry. Removing one entry does not remove another entry that shares identical bytes. Restoring retains a manual folder if its source hash still matches. Library changes are refused while capture/parsing is active; stale source hashes require refreshing and reconfirming. The model has no delete/restore capability.

Authenticated API actions record manual moves, deletion and restoration in `library_events`. Schema 4 adds persistent Trash state, per-version manual folder overrides and scan-organization status. Existing schema 1–3 stores receive a SQLite backup at `inventory.before-v4.sqlite3` before upgrade.

## Manual checks

- Open the gear; verify both settings tabs and keyboard navigation.
- Scan a new image with a configured model; verify its title/path and folder appear without pressing the batch button.
- Move it to a different leaf folder; reprocess and confirm the manual choice remains.
- Cancel a Delete confirmation; verify the document is unchanged.
- Confirm Delete, rescan and restart; verify it remains in Trash, and that the source file still exists.
- Restore it; verify it returns to its folder with preserved results.
- Compare model folder choices against your actual documents. Synthetic server tests verify plumbing and persistence, not classification accuracy.
