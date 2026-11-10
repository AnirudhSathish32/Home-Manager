# Documents

How a file gets into the library, how it is read and turned into ledger records, how it is checked and reviewed, and
how its text is searched. What the records mean for money is in [money](money.md). Every model runs locally: LM Studio
on this PC, or on the shared GPU computer ([family](family.md#shared-gpu)).

The pipeline: capture immutable bytes → read (vision transcription, PDF text, CSV/XLSX rows) → classify → typed
extraction in chunks → deterministic checks and the decision model → counted automatically or sent to Review → file
the managed copy → index the text.

## The managed library

Code: `library/storage.py`, `library/managed_library.py`, `library/scanner.py`, `library/organization.py`,
`library/trash.py`, `core/folders.py`.

The library folder you choose in **Settings → Library folder** contains `Library/` with these folders:

```text
Inbox/                       the only way documents enter (plus watched folders)
Unfiled/
Money (the ledger counts and reconciles these)
  Receipts/
  Bills/
  Bank_Statements/
  Credit_Card_Statements/
Documents (papers kept because they matter)
  Housing/  Insurance/  Investments/  Loans/  Taxes/
  Jobs/<Employer>/Paystubs/ and Jobs/<Employer>/Documents/   (see taxes.md, "Jobs and pay stubs")
```

The retired `Income` folder is emptied at startup into `Jobs`. Bills is an active money folder, shown in Receipts & statements. The original nested layout
(`01_Banking/…`) survives only as `LEGACY_HIERARCHY`, so old folder names in history still resolve. Where the database,
blobs and settings live is in [operations](operations.md#where-things-live).

- **Inbox.** Drop PNG/JPEG, PDF, CSV or XLSX files directly into `Library/Inbox`. They are captured automatically
  while the app runs, or you can choose **Processing → Scan Inbox**.
  - Subfolders, links and unsupported formats are reported, not silently traversed.
  - Files are hashed, fsynced, verified and registered before anything else happens to them.
  - The Inbox monitor captures a file once two looks in a row see it unchanged.
- **Year/month folders.** Category folders are organized by the document's own date, for example
  `Receipts/2026/09/2026-09-22__Cafe__Receipts__….png`.
  - The date is the ledger record's: purchase date for receipts, period end for statements, issue date otherwise, or
    the cited date the document was filed with.
  - `Inbox` and `Unfiled` stay flat. A document with no known date stays at the top of its category until a date is
    known.
  - A move that empties a month or year folder removes that folder.
  - At startup every file, including older versions' copies, is checked and moved into its month.
- **Automatic filing.** After extraction, a document with a cited classification and an unambiguous merchant or issuer
  and date is filed. A recognized bill files to Bills even without an issuer or date. Other missing or unknown
  identities go to Unfiled. No confidence threshold is invented.
- **Manual filing.** **Move** moves the app-owned library file. A manual choice takes precedence over automatic filing
  for that exact captured version, including after reprocessing. Changed content needs a fresh choice.
- **File names.** Trusted code picks an allow-listed folder and generates the name from validated dates, a
  conservative merchant or issuer label, a content-hash suffix and the document id.
  - The extension is kept. Original file names and account references are never embedded.
  - Digits are removed from model-derived labels so account numbers can't leak through merchant text.
  - A deterministic full-hash fallback handles name collisions without overwriting anything.
- **Evidence never changes.** Library copies don't share an inode (no hard links) with the immutable blobs, so editing
  a managed copy can't change the evidence.
  - An edited managed file blocks movement rather than being overwritten. Rescan it through Inbox, or restore the
    expected copy.
  - A file that changes while it is still in the Inbox creates a new captured version, and the earlier bytes stay in
    the evidence store.
  - **A file dropped in under a name an earlier, already filed file used is a new document**, never that document's
    next version: banks name every download alike (`document.pdf`). The filed document gives up the Inbox path it no
    longer holds (`Store.publish`, `RELEASED_PATH`). The same bytes as one of those filed documents dropped again are
    that document, unchanged, and their Inbox copy is consumed. A family delivery follows the same rule
    (specs/inbox-document-identity FR-01 – FR-05).
  - **Only an edit to a file still in the Inbox is a version.** A file filed or archived out of the Inbox never gets
    a next version under its old name; a different file under that name is a new document.
- **Documents merged before that are split once, by an upgrade (migration 080).** Before capture changed, each
  download called `document.pdf` became the next version of the first one. The upgrade gives every merged-in file a
  document of its own; edits made in the Inbox before filing stay versions of their document.
  - **The earliest file keeps the document id**, so links and bookmarks to the old id still open it.
  - **Every record follows its file**: the reading, statement, receipt or pay stub record, rows and their evidence,
    filings, folder choices, history and duplicate links move with the version they were made from. Nothing is
    deleted, and blobs and Library files keep their bytes.
  - **Trash is kept on every piece.** A merged document in Trash leaves each split document in Trash.
  - **A failed upgrade leaves the library as it was**, with a recovery message. Opening the library again after it
    has been upgraded changes nothing.
  - **The Library copies are renamed to their own id.** A copy named `…__d<n>` keeps `n` from the merged document,
    so on the next start each split copy is renamed to its own document id, durably like any move. The rename never
    overwrites: a file already at the new name blocks it and both stay.
  - To see what an upgrade would split or did, run `scripts/document_splits.py`
    ([development](development.md#database-checks)).
- **Durable organization.** Every move records an intent first (version hash, source path, target, action, reason).
  - On Windows, a non-overwriting rename is used for existing managed files.
  - New copies are staged, flushed, hash-verified and published atomically.
  - The database records the final path only after verification.
  - Startup retries pending or blocked intents. Repeated scans and recovery never create duplicate copies.

### Watched folders

Besides Inbox, you can register folders outside the library on **Processing → Watched folders** (`sources` table,
migration 053). Code: `Store.create_job(root)`, `Scanner.run(job, root, recursive)`, `Manager.check_sources`.

- **Copied, never changed.** Files are copied, never moved, renamed or deleted, so the folder is left exactly as it was.
- **Subfolders** are read when "Include subfolders" is on.
- **Other file types** are listed but don't make the scan partial.
- **Missing files.** A file that disappears from a watched folder is marked missing, and its library copy stays.
- **When it looks.** The `inbox-monitor` thread looks at each enabled folder every 10 ticks (about 30 seconds), using
  the same two-matching-looks rule as Inbox. It also rescans every folder once after the app starts and every
  `rescan_hours` (a profile preference, default 6). That rescan is the source of truth.

### Duplicate links

`occurrence_links` records two documents found to be the same, without merging anything:
- `same_bytes`: identical bytes at two paths, for example a file in Downloads that was also dropped in Inbox. It is
  recorded at capture, and the two share one blob and one reading.
- `same_record`: you verify a receipt matched to a charge whose transaction came from another document (a statement
  or CSV export). Rejecting the match rejects the link.

The document page lists every link under "Also found". Different files describing the same purchase are handled by
transaction fingerprints and reconciliation ([money](money.md#what-counts)).

### Browsing the library

The Documents page lists All documents, Inbox, Unfiled and Trash, plus the folders. Counts and paging cover the whole
library, not just the visible page.

- **Row names.** Each row is named **Merchant - Location - Description**, for example "Target - Main St W -
  Snacks/Office".
  - The merchant is the seller printed on the receipt, or inferred from a house brand or the file's name
    ([Merchant from the file name](#merchant-from-the-file-name)) and flagged for you to confirm.
  - The location is the store's street name (no building number, city or postal code), or Online for delivery
    orders. It is left out when no street is printed.
  - The description is one or two words for what was bought.
  - **Edit description…** replaces the description. **Edit details** on the document page corrects the merchant,
    location and date.
  - A file holding several receipts is titled "First merchant + N more" (see
    [Several receipts in one file](#several-receipts-in-one-file)).
  - A bank or card statement is named by its account: the institution and the account's last four, such as
    "Chase 3456", followed by your own description if you set one. The model's description isn't used.
- **Row details.** Under the name: the file name (as the library names it now: the organized copy's name once the
  file is filed in a folder, else the name it was added with; an Unfiled copy's `Document__…` name isn't shown, and a file still in the Inbox keeps its own name), type, the document's own date, amount, and one state such as Not
  read yet, Needs review or Recorded. Hover the state for per-step detail.
- **Row actions.** Each row offers one next step (Read, Record, Import transactions or Restore) and a **More actions**
  menu with Versions, Move and Delete. Select rows to read, record, move, delete or combine several at once.
  **Record selected** reads any unread selections, then records them sequentially in one model job. Read alone
  leaves documents in Inbox. Successful extraction without a ledger publication shows **Filed — not tracked**,
  with no Record action and no inclusion in Ready to record.
- **Live counts.** A persistent `library_version` in settings changes on captures, filing and reading/recording
  updates. The poll refreshes sidebar counts and the list even when work finishes between polls.
- **Read under a filter.** Under Inbox → Not read yet, a just-read row remains visible until manual refresh or a
  filter change. A toast explains that it is ready to record and still in Inbox.
- **Filters.** Filter by state or document date. Sort by date, name, recently added or path. Receipts show their
  reconciliation status ("Matched to a charge", "Match proposed", "Several possible charges", "No matching charge
  yet"). Unfiled documents show why they are unfiled. On the redesigned screen (Records v2, [ui](ui.md#pages)) the
  folder, filters, sort and page are kept in the URL, and a strip above the list counts what is waiting with **Read
  all**.
- **Virtual folders.** A manual folder choice is a fixed folder identifier; it never becomes an operating-system path,
  a shell command or a file name.

### Trash

- **Delete** asks for confirmation, naming the document. **Delete to Trash** removes it from active views and future
  reading batches, but keeps the originals, the reading history and the file on disk.
- Trash offers **Restore** and **Empty trash…**. Empty trash permanently removes every trashed document in that
  section (Documents, or Receipts & statements) after confirmation: managed copies, preserved versions, readings,
  text-index passages and ledger records. The other section's Trash is left alone.
  - Evidence still used by other documents is kept. External originals and backups are untouched.
  - Edited managed files block deletion, so the edits can be saved first.
  - Running background work must finish first. Interrupted removal is retried at restart or on the next Empty trash.
- A rescan never brings back a trashed entry. Restoring keeps a manual folder choice if the source hash still matches.
- The model can't delete or restore anything. Moves, deletes and restores are recorded in `library_events`.

### Schema upgrades and recovering from a failed one

Each script in `library/migrations/` runs in its own transaction and records its number in `PRAGMA user_version`. How
to write one is in [development](development.md#adding-a-migration). Before upgrading, the app:
1. runs `PRAGMA quick_check`, and never upgrades a database that fails it;
2. saves a complete copy, `inventory.before-v<latest>.sqlite3`, beside the database. An existing copy is kept, because
   it may predate an earlier upgrade that was interrupted; it is replaced only if it is unreadable.

After a successful upgrade, the two newest copies are kept. These copies are for upgrade recovery, not backups (use
**Settings → Backup & restore** for backups).

If a step fails, the app still starts. The alert names the step that stopped and the pre-upgrade copy
(`storage.MigrationError`), and the log records the step and the error class. Every earlier step stays applied, the
failed step is rolled back, and the next start tries again from there. To recover:
1. Close the app.
2. Leave the library folder and its `inventory.before-v…` copy unchanged.
3. Either update Home Manager to a version with the fix and start it again, or restore a backup into a new folder
   (**Settings → Backup & restore**).

Don't delete the pre-upgrade copy until the library opens normally.

## Reading documents

**Read newly scanned images automatically** (Settings → Local models) reads each new capture. **Processing → Read all
documents** reads existing captures, and **Read selected** in Documents reads only the chosen ones. Identical bytes
share one reading. Missing model settings don't stop capture, but reading needs a configured model.

A version can have several readings (Read again, or a newer reader). The document page opens the reading that was
recorded last, so a later reading nobody recorded never hides the record; with none recorded it opens the newest.
Its Saved readings list (History tab) marks each recorded one, and choosing another reading shows that reading's record or Record it.

Every reading, from any reader, keeps the same evidence:
- the input hash, reader and model versions, and status;
- line or cell references, so every later value can cite its source;
- `succeeded` means the declared scope was read, not that the reading is correct;
- `partial` lists what was left out;
- an empty result says whether the content was empty, unreadable, unsupported or failed. Nothing is truncated
  silently.

### Images (vision transcription)

Code: `documents/receipt_service.py`, `documents/receipt_worker.py`, `models/vision.py`.

- **Text and reported tables.** The vision model returns `full_text` and table header/row cells with zero-based source
  line indexes. The app accepts cells only when they match exact, ordered substrings of their lines and rectangular
  header widths. Invalid tables are discarded with a review issue while the full text remains available. The model
  does not choose titles, folders, dates, currencies or totals.
- **Server requirements.** It needs a server with streaming chat completions, image input and JSON-schema output. The
  app doesn't download or load weights.
- **Codes.** QR codes and barcodes are decoded independently, and their payloads are added as inert text with their
  exact bytes and polygons. Links are never followed.
- **What is kept.** Each result keeps the source hash, dimensions, rotation, preview, full text, line ids, validated
  `vision_tables` version 1, endpoint, model id and prompt version. Each cell has a stable ID, exact quote and source
  line ID. These are model reports, not independently located image regions; no coordinates or confidence scores are
  invented.
- **Rotating.** The document page compares the transcription with the preserved image. You can rotate the image and
  create a new reading under **History**.
- **Tables view.** The source viewer offers Image, Text and Tables. Tables show copied headings, blank cells, page
  labels and links to the original text lines. Missing or rejected table structures have an explanatory state.
  Saved text with explicit pipe separators and recognizable headings can supply the same validated table view and
  reasoning input without another vision call; it is labeled as reconstructed from text separators. Original text
  and saved parse JSON remain unchanged. Whitespace alone is insufficient to reconstruct columns.
- **Failures.** Blank or invalid output, and interrupted or token-truncated streams, fail without publishing partial
  text or replacing an earlier good reading. `[unreadable]` and `[no visible text]` markers produce partial results
  for you to inspect.
- **Limits.** Image preparation runs in a bounded child process:
  - one PNG/JPEG frame, 24 megapixels, 40,000 pixels per side, 180 seconds, and a 2 GiB Windows worker limit;
  - requests send the whole oriented preview, up to 16 MiB, with 8,192 output tokens and 15 minutes without socket
    activity;
  - outputs are limited to a 64 MiB preview, 4 MiB of JSON and 2 GiB of extraction artifacts in total.
- **Requests.** Requests go only to a validated `http://127.0.0.1:PORT/v1` URL or the shared GPU host on the tailnet.
  They bypass proxies, reject redirects and offer the model no tools.

Workers have resource limits, but they are not an OS security sandbox; see [open work](open-work.md). Synthetic tests
check the plumbing and evidence, not model accuracy.

### PDFs

`documents/pdf_reader.py` reads page by page:
- a page with a usable text layer uses its embedded text;
- new `pdf-pages-v3-layout` reads also retain native character indexes, words, geometry, ordered blocks and conservative tables in `page.layout`, before document classification;
- scanned or near-empty pages are transcribed by the vision model;
- explicit pipe-delimited rows in embedded text are retained as cells when their header and width agree;
- evidence ids are `page-N-line-M`;
- native layout IDs are separate, so existing text citations remain stable; new native and scanned pages both have rendered previews with saved coordinate transforms;
- ambiguous native layout or possible image-only content creates a review issue that prevents automatic record verification;
- no page is silently skipped, and long PDFs are analysed in chunks.
- a read PDF with a transactions table can also be imported as account transactions with no model; see [Transaction imports](#transaction-imports).
- a bank or credit-card statement PDF recorded as a statement takes its transactions from the same table rules, on every page with a text layer; see [Statement rows from the printed columns](#statement-rows-from-the-printed-columns).

Classification, typed extraction, general reasoning and search now use the same readable native layout. Table headings
are repeated with each extraction chunk. Code copies monetary values from recognized printed columns, keeping
Current separate from YTD, quantities separate from prices, and debits/credits separate from running balances.
Ambiguous roles and unaccounted native rows require review. Nearby non-table pay lines are extracted separately.
Columns may be packed tightly, as payroll sites print This period and YTD: an amount never shares a cell with the
amount or label after it, and a heading that runs into the next ("this period year to date") is split where the
cells below it fall into separate columns (right-aligned amounts may reach past their heading). A label wider than its
heading may run right (and a wide amount left) as long as it stays clear of the neighbouring headings. Text printed in
pieces with wide gaps continues the text cell before it while it ends before the next column's heading begins. Two tables
sharing rows (a payslip's Earnings beside its Deductions) are read as two tables. A section label alone on its row
("Statutory", "Voluntary") stays in its table when amount rows follow it, and needs no record. Rows after a blank
stretch (a section after a blank row, the totals at the foot of a mostly empty box) continue the table above when
they line up with its columns and each prints two amounts or more or is a section label; a details box right above
the heading row isn't part of it. One body row is a table when it prints two amounts or more (a benefits table's Co
Match 401K). Where no table is found (a statement's continued page with no heading, or a page whose Deposits column is
empty), a gutter splits the page into columns only when the right side is more than the amounts of the rows on its
left: amounts that each sit on a row printed to their left stay on that row's line, so the model never has to pair
them back up. A reading saved before this needs **Read again**.

**Tables** shows native cells as **From PDF text positions**. Click a value to highlight its actual words on the saved
page preview. **Original** opens the preserved PDF; **Text → Original text order** shows historical text and citations.
Saved v3 readings gain this display when reopened; rerun ledger extraction for the new amount mappings. Older PDF
readings need **Read again** to create native layout evidence. User-reviewed records keep their existing replacement protection.

Stacked headers, wrapped cells, rich forms and cross-page table linkage remain follow-up work. Overlapping or damaged
native geometry uses original text with review issues.

Text size is the size each glyph is drawn at: PDFium's reported font size times the scale of the glyph's matrix
(text matrix and graphics state), or the height of the font's loose glyph box when that is more than twice as large
(a scale inside the font, such as a Type 3 font's FontMatrix, which the matrix doesn't include). A bank's statement
sets its font at 0.24 pt and draws it about 10 pt tall, and read at 0.24 pt every gap was a word break, kerning looked
like overlapping text, and no row or table was found. Turned text (a
reference number printed up the margin) still flags the page for review, but it is kept out of the rows: each run is
a line of its own after the page's other text, and only a table it lies across is refused. See the [implementation status and remaining design](../text_extraction_plan.md).
Mixed digital/scanned PDFs, positioned tables, shuffled streams, crop/rotation transforms, compatibility, ledger publication,
search and browser highlights are covered by synthetic tests; live-document accuracy remains to be evaluated.

### Transaction imports

**Import transactions** on a CSV, XLSX or PDF previews and imports account transactions from the preserved copy (CSV and
XLSX: `finance/tabular.py`; PDF: `finance/pdf_import.py`, below). No model is involved. The dialog (`openImport` in
`library.js`) and the API (`POST /api/documents/{id}/transaction-import/preview` and `…/transaction-imports`) are the
same for all three.

**CSV and XLSX**
- **Mapping.** Column mapping is detected or chosen. Date order is inferred only when the whole column is unambiguous.
  The sign convention is explicit, and each rejected row comes with a reason.
- **CSV** is read with the standard `csv` module as strings. Raw values such as `(1,234.56)` and `03/04/2026` are kept
  as they are, along with duplicate headers, empty cells, leading zeros and quoted newlines.
- **XLSX** is read with the standard library's `zipfile` and XML parser, under size and ratio limits.
  - No DOCTYPE processing, no formula evaluation, and no macros or external links.
  - Formula results can't become authoritative without review.
- **Re-importing never duplicates.** Transactions have a source-independent fingerprint (see
  [Typed extraction](#typed-extraction)).

**PDF**

A PDF is imported from its **saved reading** (`finance/pdf_import.py analyze`, an adapter over the table engine, [Statement
rows from the printed columns](#statement-rows-from-the-printed-columns); pure code, nothing decoded in the request). It makes no model or network call, and never touches the Inbox or Library file. A PDF stays a document that
is read and recorded as before: it is not a table file, and `needs_text` and `ready_for_ledger` return the same PDFs
(a PDF the import marked `imported` is still recordable, and still counts as ready for the ledger).
- **What is read.** Only `embedded_text` pages. A scanned page is listed ("Page N is a scanned page; no rows imported.
  Use Record for scanned statements.") and contributes nothing. A PDF read before native layout was saved is blocked
  until **Read again**.
- **Tables and rows.** The engine finds the tables and rows (columns by alignment, with or without headings: Record reads
  the same ones). `analyze` shows each engine table as one table per page: the first page's is listed (page, headings,
  row count) and ticked by default, named after the reader's native table it sits on (`transactions`) or
  `page-N-import-table-M` (`rebuilt`); every later page's is a `continuation` linked to it ("continued from page N",
  `page-N-import-continuation`), however its headings are printed. A row's key is `<table id>:<row>`, unique across pages;
  its row number is the reader's for a native table and counts from 0 for the others (the saved import records keep
  them). Other tables (summaries, fee and daily balance tables, a payment schedule dated outside the printed period ±
  7 days) are listed as "not a transactions table" and give no rows. A balance column is never an amount; the balance
  chain, the printed summary or the headings decide which columns are money in and out.
- **Lines that fit no column.** A printed line with a date and an amount that is no row of any table (an amount
  across two columns, a courtesy line) is not a row and can't be imported: it is an issue with code `unplaced_line`, its
  page and its text, and a pending-transactions row is one too. The counts gain `unplaced` (present when there are any),
  and imported + duplicates + rejected + unplaced + left out = lines seen.
- **The money issues Record raises** are the preview's issues too, and are saved with the import: a balance chain break
  (`balance_chain_break`, with the row as the import numbers it), a printed total the rows don't add up to
  (`total_mismatch`), two chains that don't join (`two_accounts`), signs only the headings or the type give
  (`roles_differ`, `signs_unchecked`, `lead_title_unchecked`) and a row printed twice (`duplicate_row`). One is shown only when every table it is
  about is imported, and none unticks rows.
- **Dates, amounts and signs are exact.** A four-digit year is read as printed. A date without a year (or with a
  two-digit year) takes its year from the **printed statement period**, and waits for the year you choose only when no
  period is printed; the current year is never assumed. The day/month order is the one a day over 12 decides, else the
  one that fits the period, else the one the account's earlier statements decided (`ledger.pdf_state` looks it up by the
  account's last four), and only then a required choice. Amounts go through `core/money.to_minor`. A balance chain or a printed
  summary that fixes the columns decides the sign first; otherwise Debit and Credit columns decide it, and a single
  Amount column takes the row's own marker, its section title, then the chosen account's default (card: positive is
  money out; checking or savings: positive is money in; other types ask), which you can change. The choice is offered whenever any selected
  table has an Amount column, even when another one has Debit and Credit columns. A row whose date or amount does not fit is
  rejected with a reason, never guessed.
- **A number inside the description.** In a row not on a native table, an amount-shaped word that continues the
  description's printed text (joined to the word before it, closer than 1.5 font sizes, in a run that starts in the
  Description column) is description text, not an amount: `09/18 ACCTVERIFY PPD ID 1234567890 0.36` is 0.36 with that
  description, where it used to be rejected. It stays the row's amount only when its whole box lies inside one amount
  column's span (Amount, Debit or Credit; no tolerance) and it is the row's only amount-shaped word centred in an
  amount column (`09/22 LONG DESCRIPTION 12.34`). A Balance column is never an amount column. A joined amount that
  is the row's only amount but crosses its column's edge is rejected with "The amount is printed against the
  description, so it can't be told apart from it." (the row is listed, not lost). An amount printed apart from the
  description inside an amount column is rejected as before. Record rebuilds its rows the same way ([Typed
  extraction](#typed-extraction)). Because this changes what the analyzer finds, `ANALYZER_VERSION` was bumped to 2, and the table engine took it to 3: every PDF
  reading is indexed again at the next start, and the picker shows `indexing: true` until that is done. The reader before
  the engine is kept as `analyze_legacy` for the eval comparison and `finance/statement_rows.py`.
- **Flagged pages.** Rows from a page with a layout issue (other than the harmless `unresolved_columns` on a page whose
  rows are rebuilt) start unticked, with the page's message. Ticked rows import like any other.
- **Account.** The dialog ignores the remembered CSV account. An account is preselected only when exactly one active
  account in the document's currency has its last four printed in the reading ("ending in 4821", `XXXX4821`, `*4821`,
  …) and the dialog says where ("Matched …4821 printed on page 1"). When several accounts print it, the one this same
  file's rows were imported into before is preselected ("…; this file's rows were imported into it before"), so a second
  Add missed transactions shows those rows as already recorded rather than New. Otherwise Import waits for a choice. **New
  account…** prefills the last four and creates the account inside the import request itself, in the same database
  transaction as the rows. A refused or failed import leaves no account. A different currency on the document blocks
  the import; no conversion.
- **Duplicates.** A row already recorded by a CSV/XLSX import, a statement or an earlier PDF import is not inserted
  again, and its evidence is linked. The preview names the source ("Already recorded from import …") and totals money in
  and out for these rows apart from the ticked New ones. A manual entry
  with the same values is replaced, as for CSV. A statement row not yet counted says so.
- **Refusals** name the next step and write nothing: recorded as a receipt, bill, pay stub, tax form or investment
  statement; in Trash; the reading, document or preserved blob changed since the preview; over 20,000 rows or 2,000
  characters in a cell; nothing to import; and a fault in the engine itself ("This PDF's rows couldn't be read from its
  printed columns. Read it again, or use Record."), which is logged with the exception and the reading's id and never any
  text. A PDF recorded as a statement, or not recorded, can be imported.
- **Atomic and recorded.** The account, rows, evidence and the `transaction_imports` record (reading, tables, each
  table's columns in `mappings`, year, sign, ticks and counts, in `mapping_json` and `issues_json` with `kind: "pdf"`)
  are one transaction. It takes the write lock before checking the reading, so a reading saved meanwhile waits for the
  import to finish. Reconciliation runs after. Re-importing the same PDF inserts nothing, reports all duplicates and adds a record.
- **Where a row came from.** Each row's evidence keeps the document, reading, page, table, row and the cell, word or
  line ids. The source badge reads `Imported · <file> page N` (plus `continued from page M`) and links to the page with
  those lines lit ([ui](ui.md#whats-built), "Provenance").

**Entry points.** The picker (Transactions → Import, Accounts → Import an export and each account's own button) lists
CSV and XLSX files and the read PDFs that have a transactions table, labelled **PDF** (a PDF recorded as a statement
included), from
`GET /api/finance/import-candidates` (`indexing: true` while older readings are still being checked). A small
derived index (`pdf_import_index`, migration 072; a library that applied it under its first number, 071, gets bill
kinds' 071 at its next start and keeps its index) holds each reading's table count, printed last fours and currency so
the picker and the library need not analyze readings on every request. It is rebuilt when a reading is saved, at
start for older readings, and when `ANALYZER_VERSION` changes. On a PDF the import is a correction to its recording,
so it is called **Add missed transactions**: it adds the rows the recording left out and changes no recorded row
(those are fixed with Correct). It is offered only once the PDF is **recorded** (as a statement; a PDF recorded as a
receipt, bill or pay stub is refused). Until then its **library row** offers Read or Record and nothing more, and its
**document page** shows **Add missed transactions** turned off beside **Record it**. Once recorded, it
(`doc.pdf_import`, computed by the server) is the row's step (**Add missed**) and the page's primary button when the
reading has a transactions table and exactly one saved account matches by last four and currency; otherwise it is in
More actions and a secondary button on the page. Its dialog is titled **Add transactions the reading missed**. The
picker still opens the same dialog as **Import transactions**, which says **Read this document first** with a
**Read** button for a PDF with no reading, reads it, and shows the preview in the same dialog. A CSV or XLSX row's
step is **Add missed** too, opening the dialog as **Add missed transactions**.

### Several receipts in one file

A file can hold several receipts: a feeder or scan-app PDF with one receipt per page, a flatbed scan or photo with
several receipts on it, or receipts stacked in one tall image. Each one is recorded as its own receipt.

1. **Pieces of paper (reading, no model).** `documents/regions.py` looks for separate pieces of paper on a coarse grid
   of the image (numpy only), inside the bounded reader child. It splits only where the split is plain:
   - On a contrasting background (scanner lid open, a dark table), each separate bright area big enough to be a
     receipt is one region.
   - On a background as light as the paper, only side-by-side receipts with a clear full-height gap are separated.
     Light backgrounds are never cut horizontally.

   Each region is cropped (`region-N.png`, or `page-N-region-M.png` for a scanned PDF page) and transcribed on its own.
   Lines stay numbered across regions, and `regions` in the reading records each region's box and line range. An
   image with one piece of paper reads exactly as before.
2. **Receipts in the text (extraction).** The file is classified once. A receipt file may hold several receipts if it
   has more than one page or region, or more than one total line (not a subtotal or total tax). In that case one
   `ReceiptStarts` question, asked chunk by chunk, lists the first line of each receipt. Code then checks the answer:
   - A start within two lines of a page or region break moves to that break.
   - A part with no total, payment or balance line joins its neighbour: a heading joins the receipt after it, and a
     second page joins the receipt before it.
   - If the answer is unusable, the file is split at its page and region breaks.

   Every part is classified before any is read. If one part is not a receipt, the file is read as one document.
   Otherwise each part is read on its own lines and published as receipt segment N (`receipts.segment`,
   `UNIQUE(blob_hash, segment)`, migration 054).

**Reviewing the split.** `document_segments` records each part's first and last line.
- Until you confirm, each receipt carries the note "split from a file holding several" and waits in Review.
- **Confirm split** on the document's page drops the note.
- **Merge with next** or **Split here** (at a line) saves your own split. It takes precedence over the model's on later
  readings, and the file is recorded again.
- A segment that a later reading no longer finds stops counting (it is restored if found again). A receipt you already
  decided keeps your decision, with a note to check the split.

In the library, the file has no single amount, its date is the earliest receipt's, and it is filed under the first
receipt's merchant and date. Code: `ExtractionService.segments`, `split`, `confirm_split`, `set_split`;
`GET/PUT /api/documents/{id}/segments`, `POST …/segments/confirm`. Donating split receipts is not supported yet.

### Several images as one document

A long receipt photographed in parts, or a document scanned one page per image, can be read as one document whose pages
are those images (`documents/grouping.py`, migration 055).

- **Suggested, never automatic.** After each capture, images from the same folder are suggested as a group when their
  names continue one numbered series (`IMG_0012`, `IMG_0013`; `scan (1)`, `scan (2)`; `receipt_p1`, `receipt_p2`) and
  they were saved within two minutes of each other. Suggestions wait in Review under **Images that look like one
  document**, with **Combine** or **Keep separate**. A dismissed suggestion is never made again.
- **Combining directly.** In the library, select 2 to 20 PNG or JPEG images and choose **Combine as pages**. Pages go in
  file-name order.
- **Reading.** A confirmed group is read under its first page, the lead, with parser version `receipt-images-v2-tables`.
  - Each page is prepared by its own bounded worker child and transcribed.
  - The result has the PDF's page-aware shape (`pages`, line ids `page-N-line-I`).
  - `page_hashes` names each page's bytes. `options_json` holds them in order, so reordering creates a new reading.
  - Codes decoded from the pages are not carried into the combined result.
- **Records.** The lead carries the reading and the records. Later pages are hidden from lists and counts, and a later
  page's own receipt stops counting. A later page recorded as another type keeps its record.
- **Changing it.** The document page shows its pages. You can move a page earlier or later (this reads the group
  again), or use **Separate pages** to make each image its own document again.

Code: `Groups.suggest`, `create`, `set_status`, `reorder`; `ReceiptService.run` with `combine_pages`;
`Manager.read_group`. API: `GET/POST /api/document-groups`, `PATCH /api/document-groups/{id}`,
`GET /api/documents/{id}/group`, `GET /api/receipt-runs/{id}/pages/{n}`.

## Typed extraction

Code: `documents/extraction.py`, `finance/ledger.py`.

- **Two steps.** Extraction classifies the document, then extracts only that type's schema (receipt, bank statement,
  credit card statement, bill, pay stub, investment or loan statement, tax form, contract terms…) in bounded chunks with
  task-specific output limits. A failed chunk is corrected on its own.
- **Bills** are read line by line (`BillLine`: description, amount, category, `line_kind`, `line_holder`) with their
  provider, account digits, dates, period, amount due and new charges, and recorded as a receipt with
  `document_kind='bill'` ([money](money.md#bills-and-their-lines)).
- **Deterministic checks:**
  - every citation is an exact quote. How a citation is written is repaired first, never what it says
    (`repair_quotes`): one layer of wrapping quotation marks is dropped; a table cell's id cited as the line becomes
    its row's line; a quote that is in its line once spacing, the " | " cell separators, currency symbols and case
    are ignored (a table row quoted with plain spaces, or "Total 31.20" for a scan's split "T OTAL 31.20") becomes the
    line's exact text there, when found in one place only; and a quote found that way in no part of its cited line but
    in exactly one other line cites that line (a miscounted line id). The error names which way a citation failed: a
    line id that isn't in the lines, or a quote that isn't in its line. When a citation still fails, the one correction
    request shows the model the exact text of each line it misquoted;
  - every amount is printed in its cited line;
  - names appear in their citation;
  - an item's code and quantity drop the transcription's `[unreadable]` marks (`readable_text`), so a mark copied as a
    code is no code, never one that would match other items' products;
  - dates are unambiguous ISO dates;
  - the currency is explicit, or taken from a known account for statements;
  - document arithmetic reconciles: receipt totals, item sums, statement opening and closing balances, pay stubs, and
    a bill's lines against its new charges.
- **Problems** mark the record `needs_review`. A missing currency blocks publication. Records you already reviewed are
  never overwritten. How a second reading replaces the first is in
  [money](money.md#reading-a-statement-or-receipt-again).
- **The finance store** holds accounts (last four digits only), merchants, statements, transactions, receipts and
  items, recurring obligations, evidence links and review history.
  - Money is stored as integer minor units with an ISO currency; database checks reject floats.
  - Review states are `proposed`, `needs_review`, `verified` and `rejected`.
- **Transaction fingerprint.** A transaction's fingerprint is source-independent: account, date, amount, currency, and
  ordinal among equal entries. So a CSV row and the same statement row are one transaction, while two equal purchases
  on one day stay distinct.
- **Reconciliation** runs after each import and extraction, or from **Reconcile now**. It matches:
  - receipts to transactions, by exact amount, posting window and merchant, and bills to their payments;
  - pay stubs to their deposits;
  - transfers and card payments between owned accounts, which are excluded from spending;
  - refunds to their purchases;
  - recurring payments.

  Scores are integer rule points, not probabilities. Several plausible matches create an open question and no link.
  Rejected links are never proposed again.

### Counted automatically or reviewed

An extracted record counts in your finances automatically ("Checked automatically") when every deterministic check
passes:
- its required fields are present (for a receipt: merchant, date and total);
- at least one arithmetic cross-check ran and agreed (subtotal, tax and tip equal the total, or items equal the
  subtotal; statement balances reconcile);
- nothing was ambiguous or dropped;
- the decision model doubted nothing.

Anything else goes to Needs review, with the reasons listed. Correcting a field with **Edit details** clears the
reasons about that field; when none remain, the record passes. Only your own decisions stop a later extraction from
rewriting a record.

### Receipt kinds

Code: `documents/extraction.py` (`receipt_kind`, `RECEIPT_FORMS`, `receipt_details`), `finance/ledger.py`,
`app/manager.py` `change_kind`. Spec: `specs/document-forms`.

- **Four kinds.** `fuel`, `dining`, `grocery` or `general`. The kind isn't shown on the document page; it is decided
  from three signals (`receipt_kind`), and each receipt of a file split into several gets its own kind:
  - **The model's proposal.** The classifier proposes a kind, citing the lines that show it (no extra model call). It
    is usable only when it is one of the four and every citation is an exact quote of its line. A null or `general`
    proposal is no signal.
  - **What the receipt prints** (`printed_kind_of`, `KIND_CLUES`). Weighted patterns: fuel has volume at a price
    (`10.312 GAL @`, 2), a price per gallon or litre, a pump number and a grade (1 each); dining has a tip or gratuity
    line (2), a server, a table number and guests (1 each); grocery has weight pricing (`lb @`, `/kg`, 2), a bag fee,
    a bottle deposit or CRV, and EBT or SNAP (1 each). Each pattern counts once. The printed kind is the top score
    when it is at least 2 and beats every other kind's.
  - **This merchant's kind** (`Ledger.remembered_kind`). The kind of the merchant's receipts you settled, by
    merchant key: confirmed by you, or kind changed by you. None when they don't all agree.

  With no usable proposal, a printed kind on two clues or more (a score of 3) is used, else the merchant's kind,
  else `general`, with no note. A usable proposal is used unless the printed kind contradicts it: then the printed
  kind wins, or the proposal when the merchant's kind sides with it, with the note "Receipt kind: the reading
  proposed …, but its printed lines look like …" and the receipt in Review. An unusable proposal the printed kind
  agrees with is used with no note. Otherwise it is read as the printed kind, the merchant's kind or `general`, with
  the note "Receipt kind: … was not used" and the receipt in Review.
- **Each kind has its own form**: the receipt summary plus its printed fields, each optional and never filled in.
  - fuel: volume and its unit (gallon or litre), price per unit, grade, pump number, fuel amount. The fuel sale is one
    item, in `transportation`; a row that cites only the pump line is left out, with a note. Check: volume × price,
    rounded half-up to the cent, equals the fuel amount within a cent (skipped when the unit isn't printed).
  - dining: the included gratuity's words and amount, party size, server, table. The check is subtotal + tax + tip +
    included gratuity = total. A blank tip line stays missing, never 0.
  - grocery: per item, weight, unit and price per weight; a line sold as several units checks count × unit price
    against its line total. Deposits, bag fees and member savings are rows of their own; the savings total is kept.
    Tenders (gift card, EBT, card, cash) are kept with their amounts and last four digits only, never as items. A gift
    card lowers what the receipt counts ([money](money.md#gift-cards)).
  - general: today's form.
- **Stored** in `receipts.receipt_kind` and `details_json` (one entry per kind read, so an undo of a kind change brings
  the earlier kind's details back), and `receipt_items.details_json` (migration 070). Decimals that aren't money keep
  their printed text; amounts are integer minor units. Receipts read before migration 070 have no kind until read again.
- **Changing the kind** (the document page's **Correct…** form, `PATCH /api/receipts/{id}/kind`) reads that receipt again from its saved
  transcription with the new kind's form, never the image. The change is a correction with Undo, written with the
  reading, and later readings keep it. It is refused (409) while any reading of the same file is queued or running.
  On a receipt you reviewed, the amounts, items and review state stay; the new details wait as a proposal until
  **Apply details** (`POST /api/receipts/{id}/details/apply`), itself a correction with Undo that changes no amount.
- **Details that can't be read.** If the kind's new fields fail their checks after the one correction request, the
  receipt is published with today's fields and rows only, and the note "Document details could not be read". The same
  holds for the new pay stub and statement fields.

### Counts on their own line

Code: `documents/extraction.py` (`COUNT_LINE`, `count_lines`, called from `normalize` after the items).

Many receipts print an item's count and price each on the line under it (`211180042 LILIFE VEGET BF $37.71`, then
`9 @ $4.19 ea`). The instructions for every receipt form tell the model that such a line belongs to the item above,
with its count as quantity and its price each as unit_price, citing both lines, and is never an item of its own.
When the model still reads the item without a count, `count_lines` looks at the lines the item cites and, if no other
item cites it, the next printed line. A line holding only a count and a price each (`9 @ $4.19 ea`, `2 @ 1.50`,
`3 x 0.99 EA`) gives the item its quantity and unit price only when count × price, rounded half-up, makes its printed
line total within a cent; the line is added to the item's citation and it counts as a cross check. Otherwise nothing
changes, and the table shows Qty 1 as before. Bills are not read this way.

### Merchant from the file name

Code: `documents/extraction.py` (`file_seller`, `ExtractionService.seller_from_file`, called from `publish`).

A snippet of an online order often prints no seller at all, while the file is named for it (`walmart.com order.png`).
When a receipt's text gives no merchant (not the summary, the classifier or the seller question), the name the file was
dropped in with (`occurrences.relative_path`, which keeps it after the file is organized) is read:
- a web address in it names its site: `walmart.com` is Walmart, `best-buy.com` is Best Buy, or the merchant already in
  the ledger that spells it (`homedepot.com` is The Home Depot);
- otherwise words of the name that spell a merchant already in the ledger (`Target_receipt.jpg` is Target).

Words such as receipt, order, screenshot, scan and IMG never name a seller, and a name with neither gives none. The
receipt goes to review with "Merchant Walmart was taken from the file name “walmart.com order.png”, not printed; confirm
it with Edit details." A merchant found in the text always wins over the file name.

### Tax codes on receipts

Code: `documents/extraction.py` (`Item.tax_code`, `TaxLine`, `TaxCodeMeaning`, `TAXED_RULE`, `tax_codes`),
`finance/ledger.py` (`publish_receipt`). Spec: `specs/receipt-tax-codes`. What is done with them is in
[money](money.md#tax-codes-and-tax-lines).

- **What is read.** Each receipt item also gets `tax_code`, the code printed beside its price exactly as printed (BF,
  T, A, N), or none. Every receipt form (general and the fuel, dining and grocery kinds, not bills) also gets
  `tax_lines`, each printed per-code line with its code, rate, taxable amount and amount ("T = GA TAX 7.75000 on $12.99
  $1.01"), and `tax_legend`, each printed meaning of a code ("T = TAXABLE", "N = NON-TAXABLE"). All are optional, and
  every one cites its line. The instructions say that a tax line is one that prints the tax for one code, never a single
  TAX line, a total or a line with no code, and that a food-stamp, EBT or SNAP meaning is never a legend entry.
- **The item's `taxed` answer** (`TAXED_RULE`, in the instructions and in the schema the model is given): true or
  false only when the receipt says what the item's code means, a legend or a tax line printed for its code. A
  food-stamp or EBT mark such as F or E never means untaxed on its own. Otherwise the answer is null.
- **Checks** (`tax_codes`, in `normalize` after the items):
  - an item's code is kept only when it is printed as its own mark in a line the item cites ("4.29B" is a B mark. The T
    of "WATER FILTER" isn't a T mark). When the model gives no code, or one not printed there, the code printed as its own
    mark just before or after the price ending a line the item cites is used instead ("BF" in "RUFFLES BF $4.29", "X" in
    "MILK 3.49 X", `code_beside_price`). It must hold one of the codes the receipt's tax lines or legend print, the item's
    lines must agree on it, and units (LB, EA, OZ…) and count lines ("10 @ $4.19 ea") are never read as codes. Otherwise
    the issue is "Item n tax code was not printed where it was cited and was left out.";
  - a tax line needs a code printed in its citation, else "Tax line n code was not printed where it was cited, so the tax
    lines were not used." and none are kept. Its rate, taxable amount and amount are each kept only when printed in a
    citation, else "Tax line n amount was not printed where it was cited and was left out." (an amount left out leaves the
    line with none);
  - a legend entry needs its code printed in its citation, and is ignored when its quote names food stamps, EBT or SNAP.
- **What the record gets.** `tax_source` (`tax_lines`, `legend` or `printed`) and, with tax lines, the `taxed` flag of
  every item worked out from them, ignoring the model's. A receipt that prints its tax lines but no tax total (the
  model's tax is missing) gets their sum as its tax, when every line's amount was read. With a legend, the `taxed` flag
  follows the legend. The rules are in [money](money.md#tax-codes-and-tax-lines).
- **A tax or subtotal the model didn't read** (`unprinted_amounts`). With no subtotal printed, the item lines stand for
  it. When the model leaves the tax out (often by putting a single TAX line among the tax lines, with no code, where it
  isn't used), yet the total is more than the subtotal (less discounts, plus tip), the gap is the tax if a transcribed
  line naming tax ends with exactly that amount: "TAX 0.73" on a 19.39 subtotal and a 20.12 total, or "B = GA TAX 3.
  75000 on $13.77 $0.52" under a 13.77 item and a 14.29 total with no subtotal printed. That line is added to the
  receipt's citations. A subtotal that isn't printed is the total less tax and tip (plus an order-wide discount), and the
  item lines are checked against it: "Item line totals (13.77 USD) do not equal the subtotal worked out from the total
  less tax (14.47 USD)." sends the receipt to review. With no tax read, it is the item lines when they make the total. A
  check of a value worked out here counts only when the tax was read (the item lines and the read tax making the printed
  total), so with a worked-out tax the receipt is verified only when its item lines add up to a printed subtotal or
  another check holds. With no such line the issue is "Tax was not read, but the total is 2.82 USD away from the
  subtotal; check the tax with Edit details." ("from the item lines" with no subtotal printed) and the receipt goes to
  review, never verified with its tax left out. A dining receipt with a gratuity is left as read. The instructions also
  say that a single TAX line is the summary's tax.
- **Rates split by the scan.** A rate the transcription printed with a space after its point ("3. 75000") is read as
  3.75000, not 3.
- **Stored** in `receipt_items.tax_code`, `receipt_tax_lines` and `receipts.tax_source` (migration 075), written with the
  reading like the other read fields. A reading that fails before publishing changes none of them.
- **Details that can't be read.** If the new fields fail their checks after the one correction request, the receipt is
  published with today's fields and rows only, as for the kinds' details: no codes or tax lines, `tax_source`
  `printed`, and the model's `taxed` answers.
- **Run reuse.** Tax codes came with `typed-extraction-v33-tax-codes` (later `typed-extraction-v39-receipt-printed-signs`, which
  added the missing tax and subtotal and the printed signs; then `typed-extraction-v40-statement-fixes`, which stopped an
  example account number in the instruction from being copied and told card statements from bank ones; then
  `typed-extraction-v41-closing-date-period`, which dates a statement's rows from its closing date alone; then
  `typed-extraction-v42-short-year-period`, which reads a period printed with two-digit years; then
  `typed-extraction-v43-zero-lines`, which leaves out lines printing only zero amounts; then
  `typed-extraction-v44-two-digit-years`, which reads dates printed with two-digit years; then
  `typed-extraction-v45-printed-labels`, which reads a card's minimum payment and due date from their labels; now
  `typed-extraction-v46-rates-and-codes`, which leaves out rate rows and stops flagging period and barcode lines), so a receipt read by an earlier version is read again when it is next extracted.
- **Measured** by the `receipt_tax_codes` eval, on synthetic receipts ([evals](evals.md)).

### Bill kinds

Code: `documents/extraction.py` (`bill_kind`, `BILL_KINDS`, `BILL_FORMS`, `RENT_ROWS`, `bill_dates`, `bill_lines`),
`finance/ledger.py` (`bill_summary`), `app/manager.py` `change_kind`. Spec: `specs/bill-kinds`. What a rent bill reads
and how it counts: [money](money.md#bills-and-their-lines).

- **Two kinds.** The classifier also proposes a bill's kind, citing the lines that show it (a heading or line naming
  rent, a resident or a lease charge): `rent` or `general` (no extra model call). An uncited, mis-cited or unlisted
  proposal is read as `general`, with the note "Bill kind: … was not used" and the bill in Review; no proposal is
  `general` with no note. An invoice is always `general`.
- **Each kind has its own form.** `rent` is the bill summary plus previous balance, payments received and monthly
  rent, and its lines carry a rent type, period and usage (`RentBillLines`). `general` is the bill form as before. A
  rent form that fails after its correction request is read with the general form, with a note and the bill in Review.
- **Stored** in `receipts.bill_kind` and `receipt_items.line_type` (migration 071, two nullable columns, no rebuild);
  the kind's details in `details_json` under the kind, as a receipt kind's are. Bills read before migration 071 have no
  kind, keep their values and keep the page's old rows until read again; the extraction version changed, so Extract
  again reads them anew, keeping a person's line corrections.
- **Changing the kind** works as for receipts: the document page's **Bill kind** control (`PATCH /api/receipts/{id}/kind`
  with `rent` or `general`) reads the bill again from its saved transcription with that form, is refused (409) while a
  reading of the same file is queued or running, is kept across readings and can be undone. A bill's lines change only
  when it is read: a reviewed bill's kind change and Apply details leave its lines as they are, and undoing back to
  general clears its lines' rent types. Invoices have no kind control.

### Pay stub and statement fields

Code: `documents/extraction.py` (`PayValue`, `this_period_guards`, `pay_details`, `statement_details`),
`finance/document_checks.py`, `finance/document_traces.py`, `core/identifiers.py`.

- **Printed dates.** The model writes dates as YYYY-MM-DD and is told a two-digit year is 20YY (`11/23/26` is
  2026-11-23). A date it gives back as printed is still recorded when it can be read only one way
  (`one_way_date`: one part over 12 is the day, a two-digit year is 20YY), so `Payment Due Date: 11/23/26` gives
  2026-11-23. A date either order could read (`12/05/26`) stays unrecorded, with the issue "… is not an unambiguous ISO
  date".
- **A card's minimum payment and due date from their printed labels.** When the reading leaves either out, the value
  printed right after `Minimum Payment Due` (or `Minimum Payment`, `Minimum Amount Due`) or `Payment Due Date` is
  recorded (`printed_value`, `PRINTED_LABELS`), with a note naming its line, and the reading's issue about it goes. Only
  when the lines print one value after the label: two different ones record neither. A due date either order could read
  takes the order the statement's rows were read in.

- **Pay stubs** keep, for each earning line, its printed hours and rate; the paid-time-off and sick-leave balances;
  each direct-deposit split (account last four digits and amount); and for every pay amount the row label and column
  heading it was printed under, each cited (from the validated table cell where there is one). Checks: hours × rate
  per earning line, and the splits' sum against net pay. This period is guarded against year-to-date and annual
  amounts ([money](money.md#money-in-and-paystubs)).
- **Bank statements** keep the account type (from printed words only, else `other`), deposits, withdrawals, interest
  earned, fees and APY. An answer that is the printed words themselves ("Chase Savings") counts by the one type word
  in it, when its citation prints that word too. Check: opening + deposits − withdrawals = closing, only when all four are printed, beside the
  check from the transaction rows.
  - The printed type is the account's: a savings or money-market statement records into a savings account, and
    checking or `other` into checking (`ledger.PRINTED_ACCOUNT_TYPES`). A checking account that a later statement prints
    as savings, or the other way round, takes the printed type. Its name follows only while it is still the default
    name (`retype_account`).
  - The document page shows the account type with the statement's fields. A bank statement offers no statement
    balance, minimum payment or due date, and a card statement offers no opening or closing balance
    (`ledger.OTHER_STATEMENT_FIELDS`).
- **Statement rows the model skipped.** After Record, any line the model was given that holds a date anywhere in it (not
  right after a digit or `/`), prints an amount other than the date, and isn't a balance or total line is checked. If no transaction or summary field cites it, the model
  is asked once more for the rows in those lines alone, with the printed period (`missed_statement_lines`,
  `missed_rows`). Rows it finds are checked like the others and placed in printed order. Any still left out become a
  review note quoting up to three of them. The instruction also names small amounts, such as account-verification
  deposits and their reversals, as rows.
- **Amount or running balance.** A row read from one flat line (not a table cell) whose amount is the last of two or
  more amounts printed with cents after its date is sent to review: on a line such as `09/18 DEPOSIT 0.02 0.38` the
  last is the balance (`balance_taken`). The instruction says so too.
- **Account numbers.** The last four are the printed number's own. When the model gives four digits from inside a
  longer number it cites (1234 of 000009000123456), the number's last four are kept instead. Digits printed in none of
  the quoted lines are never kept: the quote's one printed number gives the last four (XXXX7890 gives 7890), and with
  several or none, no account is suggested (`core/identifiers.last_four`). The instruction carries no example number,
  which a model could copy.
- **Card statements** keep the purchase and cash-advance APRs, credit limit, available credit and rewards (points stay
  text). Check: previous − payments − credits + purchases + fees + interest = statement balance, when all are printed.
- **Nothing counts differently**: the new fields are shown, checked and traced only.
- **Identifiers.** Account, card and routing numbers, employee IDs and SSNs are never stored outside the saved
  transcription: only last four digits are kept, and identifier fields' citations, new details and their part of the
  saved reading are masked to their last four digits (`core/identifiers.py`). The saved transcription and its search
  index keep the document as printed.
- **Each check is a figure** on the record (`checks`), traced by `receipt.fuel`, `receipt.dining`, `receipt.unit_line`,
  `receipt.paid`, `paystub.hours`, `paystub.deposits` and `statement.summary` ([ui](ui.md#trace-contract)).

### Statement rows from the printed columns

Code: `documents/table_engine.py` (columns, rows, lines that are not rows), `finance/statement_tables.py` (what the columns
mean, the period, the date order, notes and issues), `finance/statement_dates.py` (dates and the shape Record reads),
`documents/extraction.py` (`read`, `publish`, `normalize`), `finance/provenance.py`. The rows come from the saved
reading's words and their positions, with no model and no network. The same input always gives the same rows, ids and
evidence (Extract again on an unchanged reading changes nothing).

- **Which pages.** Recording a bank or credit-card statement PDF takes the rows of every `embedded_text` page that holds
  a transactions table from the printed columns, a page flagged for overlapping or rotated text included. A page where
  no table is found, a scanned (`vision_model`) page and a reading saved without layout keep the model's rows and the
  missed-row check; a text page with no table adds the note "Page N: no table was found in the printed columns, so its
  rows are the reading's; check them." A reading with no layout adds "Read this document again to take its rows from
  the printed columns." Readings made before this are read again on **Extract again**; a statement you confirmed or
  rejected is not rewritten. Extract again never reuses a run of an older
  `EXTRACTION_VERSION` (`documents/extraction.py`).
- **Columns are found by alignment, not headings.** Amounts that line up by right edge, left edge or centre on at least
  two dated rows (one, with a heading over them) are a column; the date column is the dates at the left, a second date
  column is the posted date, and the text between is the description. The tolerance is `ALIGN = 0.75` font sizes
  (`table_engine.py`), which the layout generator confirmed (0.5 and 1.0 read the same 200 statements). Headings only
  name columns and break ties. A table continues over later pages at the page's offset, with or without a repeated
  heading; a heading with another number of columns, or another column set, starts a table of its own.
- **What each amount column is.** For each transactions table the roles (balance, money in, money out, one signed
  amount, other) are the first of: the assignment under which every printed running balance follows from the one above
  (two or more links); the one that makes the printed summary hold (opening + in − out = closing, card: previous −
  payments + charges = new, and any column totals); the one with the most holding links; the heading words; the
  statement type's default. A balance column and an `other` column (a rate, a foreign amount) are never amounts, and a
  column headed Balance is never money however its numbers add up (`Balance Transfers` is not such a heading; it is a
  kind of charge). A printed balance marked `DR` is a bank balance
  overdrawn and one marked `CR` a card balance in the holder's favour; both are negative (a card's balance is what is
  owed), in the running balances and in the opening and closing balances alike. A single unsigned amount column takes each row's sign from its own marker (`CR`/`DR`, minus, parentheses), then its
  section title (payments and credits are money in; purchases, charges, fees and interest are money out; `Credit Card`
  in a title names the card and says nothing), then the type's default. A title directly above a table with no heading may be a page's title (`Credit Card Activity`), so its
  direction is used only when the balance chain or the printed summary checks it (it always marks pending rows). When
  nothing checks it and it would have given other signs, that is an issue naming the title. A `CR` printed in a money-out
  column is money in, and a `DR` in a money-in column money out. Where roles can't be told, nothing is guessed: the rows are listed, or recorded from the headings or
  the type with a review reason saying why.
- **Values.** The date is the printed date; the description is the printed description, with wrapped lines joined and a
  check number kept in it; the amount is in minor units. A dateless row takes the date of the row above, with a record
  note ("Page P row R: no date is printed; it takes D from the row above"). A date with no year, or a two-digit year,
  takes its year from the period. The period is the printed one (the line outside every table with exactly two dates
  and no amount; two-digit years count, read as 20YY, when the dates are at most 100 days apart, as in
  `Opening/Closing Date 09/27/26 - 10/26/26`), else the model's summary period. A statement that prints only its closing date (many card statements)
  places them in the 62 days up to the closing date the model read, or the 92 days up to its due date when that is all
  it read; without that, every such row waited for a year and the statement recorded none. The printed period is also the record's: if the reading gave another,
  the record notes it ("The printed statement period … was recorded; the reading gave …"). The day/month order is the one a day over 12 decides, else the one
  under which every date falls within the period (± 7 days) and rows don't run backwards, else the order last decided
  for the same account's other statements (`statement_tables.prior_order`, at most ten, newest first), else the rows
  are not recorded and one issue per page says so. The balance a row prints is kept as `balance_minor` in its
  evidence and shown beside the amount, never read as one. A date line with no amount joins an amount line directly
  below it; with none it is a rejected row.
- **Opening and closing balances.** The statement's recorded opening (card: previous) and closing (new) balances are the
  ones it prints, from a balance line inside the table or one above it, with or without a date. If the reading gave
  another value, the record notes it ("The printed opening balance … was recorded; the reading gave …").
- **The model decides nothing there.** Its rows on a page the engine read change no date, amount or direction and add
  no rows. One that matches no engine row (by page, date and amount) becomes a record note ("The reading listed a row
  the printed columns don't have…"); notes show with the record but are not reasons for review. An engine row the model
  didn't list is still recorded. A page the engine recorded none of its rows from (the columns' roles or the date order
  couldn't be told) is the exception: its rows are the reading's, with a record note saying so, and the page's issue
  still sends the statement to review. Before, both were dropped and the statement had no rows at all.
- **Lines that are not recorded** are review issues, and the statement needs review. Nothing printed is dropped
  silently: every line with a date and an amount is a recorded row, a rejected row, a balance line, a column total, a
  row of another table, or an **unplaced line** ("Page P: a printed line wasn't placed in any column, so it wasn't
  recorded: "…""). Rejected rows keep PDF import's reasons (two amounts in a column, both debit and credit, an
  impossible date, an unreadable amount, a currency other than the statement's) and add a page and row number counted
  from 1 on that page's table. A pending transaction ("Pending transactions" section) is listed, not recorded. A
  balance break is one issue at the first row where a printed balance doesn't follow from the one above ("Page P row R:
  the balance … doesn't follow from the row above"). Two chains that don't join are one issue ("This PDF may hold more
  than one account…") and both tables' rows are recorded. A printed column total that isn't the sum of the column's
  printed amounts is an issue ("Page P: the printed total … doesn't match the rows above it…"), however the roles were
  decided. Each amount counts with its printed sign (a reversal printed with a minus, or a CR in a money-out column,
  counts against the total). Which rows a total covers isn't decided: it holds when any plausible group adds up to it
  (the table's rows, those above it, its page's, those since the column's previous total, or the section above it, with
  or without pending rows, or the last few sections above it), so only a total that no group adds up to is an issue. A
  total printed with `CR` in a money-out column is a net reversal. The printed summary's column totals are added the
  same way, so a correct net total beside a reversal never stops the summary from deciding the roles. A signed column whose amounts print
  CR or DR isn't checked. A page with a layout issue other than `unresolved_columns`
  still gives its rows and the statement needs review, naming the page. The same row printed on two pages or tables is
  recorded twice with an issue naming both places.
- **Other tables are not read as transactions:** a balance table (dates and one amount column, no descriptions), a
  fee or interest summary, a list of checks that repeats main-table rows, and a payment schedule (rows all dated outside
  the period ± 7 days; with no period nothing is a schedule). A section title (`Daily ending balance`) or a balance
  line in a table is a hint, not an exclusion: a table with descriptions whose balances chain is still read.
- **A rate is never a row.** A row the reading lists with a percentage for its amount (an APR line it took for a payment)
  is not recorded; one note counts them instead of an issue or note per line.
- **Lines the reading missed** (`missed_statement_lines`) are dated lines that print money once every date is taken out:
  a number with a decimal point or a thousands comma, not a rate. A period line (`09/27/26 - 10/26/26`) prints only
  dates and a mailing barcode only bare codes, so neither is asked about again or listed as missed.
- **Lines printing only zero amounts are no rows** (`table_engine.zero_line`): a line whose every amount is zero and
  whose other text in an amount column is only dashes, such as a card's interest charge calculation printed under the
  charges (`Purchases 19.99% (v) 10/26/26 - 0 -`). No payment is zero, so such a line is not recorded and gives no review
  reason; one note per page counts them ("Page P: N lines printing only zero amounts … were not recorded").
- **Checks** run on the engine's amounts. The arithmetic check is skipped when a printed line wasn't recorded, so it
  never reports a false mismatch.
- **If the engine fails** (an exception) the model's rows are used on every page with one issue ("The rows couldn't be
  rebuilt from the printed columns…"); the failure is logged by class and place, never with document text. The model's
  rows are then anchored to a native table like any other reading, so a native table whose columns the reader couldn't
  resolve leaves them out for review.
- **Evidence.** A row's evidence link keeps `{rebuilt, page, table_id, row, balance_minor, line_ids, word_ids, cell_ids,
  quotes}`: every line the row cites (a wrapped row cites all of them) and one quote per line. A row that is one row of a
  native table, with every word in its cells, cites those cells (`cell_ids`) and no words; any other row, wrapped over
  several table rows or with words outside the cells, cites every word. `GET /api/provenance/transaction/{id}` gives
  `document: {id, page, lines, cells}`: the document, the row's page, its line ids, and the words or table cells to
  highlight. A trace's **Open source** link for such a row adds them to `?lines=`, and the document page lights them.

### Pay stub rows from the printed columns

Code: `documents/pay_tables.py` (tables, rows, totals, blocks, the summary box, unplaced lines), `finance/paystub_tables.py` (which
tables are pay tables, what each column is, the guesses, and the cells Record reads), `documents/extraction.py` (`anchor_paystub`,
`guess_groups`, `pay_tables_for_viewer`), `documents/layout_context.py`. Like the statement engine it reads the saved reading's
words and their positions, with no model and no network; the same input gives the same tables, roles, guesses and evidence.

- **Which pages (one path).** Every `embedded_text` page of a pay stub PDF that holds a pay table takes its amounts from the
  engine. Every other page of a text PDF stub is read like flat text, with the column checks in
  [money](money.md#money-in-and-paystubs): a page with no pay table, a reading saved without layout, and a page whose tables the
  engine does not trust (a page with a pay table none of whose columns is this period, year to date, hours or rate). The
  reader's own printed tables (`table_grid`) are no longer used for a text-PDF pay stub: once the stub is classified, the
  model is shown the engine's cells only, never those tables (the classification request, made before the kind is known,
  still sees them). A scanned or photographed stub keeps the model's vision tables, on its own pages too when it is mixed
  into a text PDF. A text page without a pay table adds the note "Page N: no pay table was found in the printed columns, so its
  amounts are the reading's; check them." If the engine raises, every page of the stub is read like flat text with the note "The
  pay table couldn't be read from the printed columns, so the reading's amounts were used; check them." (logged by class, never
  with document text). Readings made before extraction version `typed-extraction-v37-paystub-one-row-headings` are read again on
  **Extract again**; a stub you confirmed or rejected is not rewritten.
- **Rows.** A row is a label followed by amounts, found by alignment alone; no date or heading is needed. A number joined to
  letters (`401K`, `403(b)`) is label text, never an amount. A whole number (`80` hours) is an amount only in a column: a line of
  one integer starts no row, and a column of integers that no decimal column lies within 0.75 font sizes of counts when a
  heading sits over it or two rows line up in it; one printed alone under no heading (`SECTION 125`, one row of `40`) stays
  label text. A row printed in whole numbers only (`Regular 100 1300`, no decimal amount) is read under a heading: a whole number
  within 0.75 font sizes of a decimal column's edge is an amount of that column (`100` under `20.00`); a column made only of
  such rows is kept only with a heading over it and two rows lined up in it; and the row is a pay row only when every one of its
  numbers is read as an amount. A details-box line (`Federal Allowances 2`) above the first heading, or a number under no
  heading, stays text. Columns are amounts that line up by right edge, left edge or centre; headings, when printed (one or two lines, or
  one line of words that fall over two or more columns, such as "This Period Year To Date"), only label them. A column of one row has the second point of support (`choose_alignments`) from a heading run only when its edge
  lines up with the amount's; where two close headings read as one run (`This Period Year to Date`), the edge of a piece of the run (`This Period`) counts too. A text line at the table's left edge above a row is a section title and the rows' section; an indented text line under
  a row joins that row's label (a wrapped label). A different column set starts a table of its own (stacked Earnings / Taxes /
  Deductions tables); so does a heading after a totals line, so a leave table whose columns line up with a pay column doesn't merge with it: two or more
  runs of words, or one run that holds a leave or deposit heading word (accrued, accrual(s), balance(s), used, available, remaining, carryover, deposit(s), account,
  routing; whole words, any case), does not start at the label column, and has a piece or an aligned word over each amount of the pay line after it (`Used Balance`, a phrase
  at one pitch), never a section title, however long; a one-run title without such a word never cuts, however it is placed. A table continues over later pages, with or without a repeated heading, only when the page's first
  rows line up with the open table's columns at a page offset within the alignment tolerance (0.75 font sizes); a page whose
  columns sit further off starts a table of its own. A page
  holding two tables next to each other (earnings left, taxes and deductions right) is read as two blocks, each row holding
  only its own block's words. Totals lines (Gross Pay, Total Earnings, Total Taxes, Total Deductions, Net Pay, also lettered)
  are totals with a value per column, not pay lines; a table ends after its net pay.
- **Pay tables and others.** A table is a pay table when a column of it is a pay column (below), its headings name this
  period or year to date, or it sits beside a pay table. Direct-deposit and leave-balance tables are other tables: their rows
  are no pay lines.
- **What each column is** (from the printed numbers; the model decides nothing). In order: hours × rate equals a third column
  (that column is this period, the hours column hours, the rate column rate; when two such products share the hours column,
  because the hours equal the stub's year-to-date multiple, the first triple's product is this period and the other's year to
  date, a guess unless a heading names them); a column whose printed section totals each equal the rows they cover (the rows
  since the previous total, or since the previous total or section title, whichever adds up) is a pay column; of two pay
  columns, this period is the one with the smaller magnitude on more rows (a row votes when its two amounts share a sign,
  both negative included; mixed-sign rows and totals don't vote); headings break any tie and are the only guide when nothing else decides; one pay
  column with no heading is this period. Any other column (year-to-date hours, an employer-cost column that fails the totals)
  is `other` and never money. When the numbers decide against the headings, the numbers win. When they cannot decide (two
  pay columns, no voting row, no heading), the column smaller on more rows is this period, and on a tie the left one.
- **The summary box.** A small table printed across the stub, two rows (this period, year to date) and at least four amount
  columns, where the largest amount on each row is the sum of three others, is a summary box and not a table. Its columns are
  gross, taxes, deductions and net by their heading words where printed (they must agree with the sums), else by the sums
  (net is the largest of the other three on the this-period row), and taxes before deductions when nothing else says.
- **Where the totals come from.** Gross, net, taxes and deductions are the pay table's totals line in the matching column
  when exactly one is printed; else the summary box; else the model's value with today's checks. When a totals line and the
  box print different amounts, the one the pay lines add up to is kept, with a note. A single combined deductions total still
  never fills pre-tax deductions.
- **What the model does.** It classifies each pay line (group, category) and cites its row; every this-period, year-to-date,
  hours and rate value is copied from that row's cell in its column. A blank cell stays blank. An engine row that no model
  line cites is still recorded, in the group of its section title, else the group under which the stub's totals hold, else the
  group of the line next to it.
- **Guesses are notes.** Wherever the engine or Record has to choose it picks its best choice, writes it down and says so; a
  guess is never a review reason. The kinds (`details.guesses` on the record, each with the page, the table and the note text):
  `headings_overruled` (the numbers decided against the headings), `columns_guessed` (the numbers could not tell the two
  columns apart), `group_guessed` (an unclassified row's group), `box_columns_guessed` (the summary box's taxes and
  deductions told by order) and `split_changed` ([below](#several-pay-stubs-in-one-file)). The note texts are also in
  `details.notes`, shown under the stub's fields. The evals count every guess and how often it was right
  ([evals](evals.md#the-two-table-readers)).
- **Review.** Today's checks run on the copied values, unchanged: earnings against gross, gross less deductions and taxes
  against net, per column; hours × rate; the guards of [money](money.md#money-in-and-paystubs). A stub goes to review from
  this feature only when its printed numbers still do not add up after the best guesses. Notes, not review reasons: a printed
  section total its rows do not add up to ("Page P: the printed total "…" … doesn't match the lines above it, which add up to
  …"), and an **unplaced line** (a label and an amount that is no row, total, heading, summary box line or other-table row:
  "Page P: a printed line wasn't placed in any column, so it wasn't recorded: "…"").
- **Evidence.** Every copied value cites its printed words (or its native cell when the row is one native row), and a pay
  line's row label and column heading cite the label's and the heading's words (a wrapped label cites every line). The
  document page lights them. The Tables tab of a stub the engine read shows the engine's tables and summary box with each
  column's role and the guesses beside the table ([ui](ui.md#observability-components)).
- **Checking it on a real stub.** `python scripts/statement_diagnose.py "<pay stub PDF>" paystub` prints the engine's shapes
  and counts only (columns and their roles, how roles were decided, rows, totals, blocks, summary boxes, unplaced lines, guesses
  by kind, how many stubs the file splits into, and the pages the engine does not trust), never a heading word, label,
  amount, date or employer, so its output can be pasted anywhere.
- **Known limits.** Each ends in a guess or a note, never an invented number.
  - A table continues the open table of the previous page only at a page offset within the alignment tolerance (0.75 font
    sizes). A later page whose columns sit further off starts a table of its own, even when it is the same table printed
    shifted; a page that starts another table within that offset is read as a continuation.
  - A whole number printed within 1.5 font sizes after an amount in the same run (`25.00 40` in tight columns) stays inside the
    amount's run and is not seen as a column.
  - A section title that holds one of the leave and deposit heading words, starts right of the label column, and has a word
    lined up by one edge with each amount of the row below it (the same edge for every amount) is cut as a heading: the row below it goes to its own table or is
    unplaced, with the note. A section title without such a word ("Health Insurance Premiums", "Reimbursements") never is, wherever it is placed, and neither is a
    title at the label column. A leave or deposit heading without any of the words, printed as one run, is not cut either: its table merges with the pay columns.
  - A headless stub whose hours or rate print on one row only has no column to form from one unheaded row.
  - A page the engine does not trust is read like flat text: its amounts come from the model with the column checks, with the
    "no pay table" note (a summary box on the page still gives its own cells). A stub that read right only through the reader's
    printed tables, in a layout no fixture covers, now reads flat and may go to review. Accuracy on real stubs is unmeasured
    ([open work](open-work.md#pdf-table-engine)).
  - With the engine down, the column checks on the flat lines run only while the part's classification is still pay stub; a
    part re-classified to another kind keeps the flat behaviour it had before.

### Several pay stubs in one file

Code: `documents/paystub_split.py` (`stub_parts`), `documents/extraction.py` (`ExtractionService.segments`, `split`,
`set_split`, `confirm_split`), `finance/ledger.py` (`publish_income`, `retire_segments`), migration 077.
A file such as a year of stubs in one PDF is recorded as one pay stub each.

- **Finding the stubs (no model).** The rule reads the transcribed lines only, so it works on text PDFs, scans and photos.
  A stub starts at a line with a pay date label (pay date, check date, payment date, pay period, period ending) and a date. A
  start opens a new stub only after the open stub has printed its net pay (a net pay label and an amount, or the label alone
  on its line): a stub prints both a pay date and a pay period, and a later page repeats its heading, so those continue the
  stub. Each stub's first line then moves up over its employer heading lines (at most four, on the same page, never past
  the previous stub's net pay). A part left without a net pay line joins the stub before it (the first joins the next). If the
  rule raises, the file is read as one stub with the note "Where each pay stub starts couldn't be read, so the file was read as
  one." A part the model classifies as something other than a pay stub makes the file read as one document, as for receipts.
- **Each stub is a record of its own** (`income_records.segment`, unique with the file, migration 077: every earlier record
  became segment 0, unchanged). Each part is read on its own lines (the engine on text pages), checked, matched to its own
  deposit, counted as money in on its own pay date, and has its own review status. Extract again on an unchanged reading
  gives the same records, line ids and notes.
- **No review for the split.** Unlike receipts, a split pay stub does not wait in Review: it carries the record note "Split from
  a file holding several pay stubs", which is not a review reason. The document page offers **Confirm split** (drops the note),
  **Merge with next** and **Split here** as for receipts; your own split wins on later readings and the file is recorded
  again. The split panel names the stubs (employer · pay date · net pay). When you change where the stubs start, the
  next reading adds a `split_changed` guess note to each stub ("You changed where the pay stubs in this file start; the file
  was read with your split.").
- **A stub a later reading no longer finds** stops counting (it is restored if found again), with the note "… no longer finds
  this pay stub; check how the file was split." A stub you decided keeps your decision and gets the same note.
- **VOID stubs.** A stub with a line whose whole text is VOID (case-insensitive, `*` and `-` around it allowed; a VOID inside a
  sentence does not count) is recorded with the note "This pay stub is printed VOID, so it doesn't count." and is rejected
  automatically, so it counts nowhere; a stub you decided is left alone.
- **Duplicates.** A stub with the same employer, pay date, net pay and currency as another stub that counts (in this file or
  another) is recorded with its lines, noted "This pay stub repeats the one paid by …, so it doesn't count." and rejected
  automatically; the first recorded stub counts. If the first is rejected, the duplicate counts on its next Extract again.
  Only exact duplicates stop counting: the same employer and pay date with another net pay (a reissued stub) counts, and the
  later one carries the note "Another pay stub from … has the same pay date."
- **In the library** the file has no single amount, its date is the earliest non-rejected stub's pay date, and it is filed
  under the first stub's employer and pay date (a file with one non-rejected stub shows that stub's amount). The file's
  shown reconciliation status is the worst of its stubs'; a stub with no deposit has none. A file whose only pay stub is
  rejected shows no library amount, as receipts. Tax tables are looked up for the tax year of every stub.
  Donating a file with several pay stubs is not supported.

### Model runs, queues and cancellation

- **Telemetry** (`model_runs`, migration 010). Every model request records:
  - the task, the run it belongs to, the model id, the server-reported identity and the prompt version;
  - time to first token, prompt and completion tokens, generation rate, total model time and bytes;
  - the finish reason, including for failed and cancelled requests.

  Server `timings`/`usage` are used when reported; otherwise the rate is estimated and labelled `estimated`. The data
  is shown under **Processing → Model runs** and per run on the document page.
- **Model identity.** A fingerprint of the server's `/v1/models` entry. Finished readings are reused only for the same
  identity. If the server can't identify the model, nothing is reused.
- **Queues.** Capture (filesystem) and inference (model, one at a time) run independently. Browsing, moving,
  importing, reviewing and most settings work while a model generates.
- **Cancellation.** The sidebar activity indicator and **Processing → Now running** offer **Cancel**.
  - The worker is released at once. The HTTP exchange runs on a helper thread, because Windows can't interrupt a
    blocked receive.
  - The socket is shut down so the server stops at its next token, and the image-preparation child is killed.
  - Cancelled runs are marked `cancelled` and never publish.
- **Interrupted runs.** Runs interrupted by a restart become retryable ([operations](operations.md#background-work)).

### Reasoning runs (API only)

The original line-by-line "financial reasoning" analysis is no longer shown in the interface. Typed extraction, the
deterministic checks and the decision model do its job. The service remains at
`POST /api/documents/{id}/reasoning-runs` (`documents/reasoning.py`):
- **Input and output.** It reads one saved transcription, never calling the vision model again. Every fact must cite
  a transcription line with an exact quote.
- **Prompt versions.** Version 2 requires one row per printed item and accounts for every non-blank line. Version 3
  separates unreviewed values from ambiguous ones (null).
- **Retries.** At most one correction request follows a validation failure.
- **Limits.** Input is capped at 64 KiB of lines and output at 8,192 tokens. Results are never authoritative.
- **Reviewer.** If **Independent checks** is on, the reviewer runs after it
  ([assistant](assistant.md#the-independent-reviewer)).

## Decision models

A decision model answers typed questions with probabilities instead of text. A yes/no question ("is this claim
supported by its cited line?") returns the probability of yes. A pick-one question ("what kind of document is this?")
returns a probability for every option. They are also called System One models, after TypeSafe's Jev.

The app uses one for its **independent checks**, chosen in **Settings → Independent checks**. Laya, the in-process
checkpoint used before, was removed on 2026-10-03. Code: `models/decisions.py`. Eval task: `evals/tasks/decisions.py`.

**What it checks**
- **Every ledger extraction** (`ExtractionService.assess`):
  - a shadow classification over `DOCUMENT_TYPES`, shown for reference only;
  - a support score for every proposed header value and row, against the lines it cites;
  - a value below `SUPPORT_THRESHOLD` (0.8) sends the record to review with a reason.
- **Reasoning runs**, when Independent checks uses the decision model (the reviewer's provider `decision`,
  `decision_review`).

**Advisory only.** The scores can send a record to review, but they never approve, reject or file one.
- A failed or unreachable decision model never fails an extraction; the error is saved beside the record.
- The result is saved under `"decision"`, with the provider, model id, calibration temperature and a calibrated flag.
- The decision setting is part of the run options, so changing the model starts a new run.
- Extractions saved before 2026-10-03 carry Laya's result under `"laya"`; the document page still shows it.

**Why only a veto.** Scores earn routing or gating authority only after calibration on real documents. The old Laya
checkpoint showed why: on real Target receipts it scored exact totals correctly (0.94 for the printed total, 0.03 for a
wrong one), but gave a correct merchant taken from the footer 0.17, and classified a receipt as a bill with 95%
confidence.

| Provider | Server | How probabilities are read |
|---|---|---|
| LM Studio | Any model in LM Studio 0.3.39 or later | The options get one-letter labels, and the model is asked for one token on `/v1/responses` with `top_logprobs: 20`. (LM Studio's `/v1/chat/completions` accepts `logprobs` but returns none.) |
| System One server | Any server speaking TypeSafe's `POST /v1/systemone` contract | The server returns the probabilities itself (`noul`, or `probabilities` per option). |

**LM Studio provider**
- **Reading the token.** The label's probability is read from the first token's top log-probabilities. Variants of
  one label (`" A"`, `"a"`) are merged, and the result is renormalized over the labels.
- **Coverage** is the share of that token's probability that landed on the labels. Below 0.5, the answer is unknown,
  never guessed. The usual cause is a thinking model whose first token is `<think>`; use a model that answers directly,
  or one fine-tuned for decisions (for example Winnow-12B).
- **Requests.** There is one request per question. The state comes first, so LM Studio's prefix cache reuses it.
- **Residency.** Decision requests go through the same eject-then-load step as every other model task
  ([operations](operations.md#local-models)).
- **Still to check:** the `/v1/responses` log-probability shape against the installed LM Studio
  ([open work](open-work.md)).

**System One server**
- **Kev** (Apache-2.0, Qwen3.5 0.8B–9B and Qwen3.8 27B): run `python -m kev.serve --run jaredpalmer/kev-4b --port 8009`,
  then set the URL to `http://127.0.0.1:8009/v1`. Kev ships fitted temperatures. Kev-0.8B needs about 4 GB of VRAM and
  can sit beside LM Studio; Kev-4B needs about 17 GB and has to take turns with it.
- **Winnow's own llama.cpp-based server** also works. In LM Studio, use Winnow through the LM Studio provider instead.
- The app doesn't manage this server's loading. Each state is one request, with all its questions.

**Rules for both providers**
- **Local only.** Both accept loopback URLs only. Hosted Jev or any other remote endpoint is refused.
- **Size limit.** States over 24 KiB are refused, never truncated.
- **Test connection** (`POST /api/decision-model-tests`) asks one fixed yes/no question about a made-up sentence, never
  document content.
- **Shared GPU.** With the LM Studio provider, the decision model is shared under the role `home-manager/decision`, and
  the relay forwards `/v1/responses` for that role only. A System One server stays on this PC.

**Calibration.** `calibration_temperature` (default 1.0) divides the log-probabilities before they are normalized.
`calibrated` records that the temperature was fitted on this household's documents. Both come from an eval run, never
from a guess. Until a model is calibrated, the review scope and the document page say so. To fit the temperature:
1. Add candidates with a `decision` model to `evals/models.toml`.
2. Run `python -m evals.tasks --tasks decisions`. The cases classify every synthetic document, and check true and
   planted-wrong claims for each synthetic receipt's merchant, date and total.
3. The report gives each candidate's accuracy, expected calibration error, Brier score, and the temperature that
   minimises log loss (with the log loss before and after).
4. Confirm the result on your own documents ([evals](evals.md)), then put the fitted temperature in `decision.json`.
   The Settings form keeps the saved calibration values when you save.

## Searching document text

Search and the assistant can use the words inside documents, not only their names. A local SQLite FTS5 index covers
every saved reading (migration 042, `library/text_index.py`). No model and no GPU are involved.

- **Why not RAG.** Money documents are already read line by line into typed ledger records, each value citing its
  source line, and money questions are answered from those records by exact SQL. Retrieving text chunks for them
  would miss rows and leave the arithmetic to a small model. The index exists for prose documents (insurance, leases,
  loans, employment and tax letters), whose clauses have no ledger rows. Embeddings stay deferred until keyword
  retrieval measurably misses.
- **Passages.** `document_passages` holds eight consecutive non-blank lines of one page, overlapping by two lines so a
  phrase broken across lines still matches. Each passage keeps its line ids.
- **Full-text table.** `document_passages_fts` is an external-content FTS5 table (`unicode61`, diacritics removed,
  prefix indexes), kept in step by triggers.
- **What is indexed.** Only finished readings (`succeeded`/`partial`) are indexed. Queries join through the library's
  `text_run_id`, so only a document's current reading matches.
- **When it is built.**
  - `ReceiptService.publish` indexes a reading as it is saved. A failure is logged and never fails the reading.
  - At library open, readings not yet indexed (or indexed under older rules, `INDEX_VERSION`) are indexed on the
    capture queue.
  - `home-manager index-documents --rebuild` rebuilds the index with the app closed.
- **Removal.** Emptying Trash removes passages through their `parse_runs` foreign key.
- **Query safety.** Typed words become quoted FTS phrases. All words must appear, and the last may be unfinished.
  Operators, quotes and colons are never passed through.
- **Search results.** `LibraryStore.documents(query=…)` also matches passages.
  - Each matched row carries `match: {snippet, line_ids}`. The snippet marks matched words with `\x02…\x03`, which the
    browser turns into `<mark>` from text nodes.
  - The link opens `#/documents/ID?lines=…`, selecting those lines in the text.
- **Global search.** `GET /api/search?q=` searches documents (title, merchant, file name, text), transactions,
  inventory items and accounts. The sidebar search box (<kbd>Ctrl</kbd>+<kbd>K</kbd> or <kbd>/</kbd>) opens
  `#/search?q=`, grouped by kind, each group with "View all".
- **Assistant.** `search_documents` and `get_document_text` answer from passages, with cited lines
  ([assistant](assistant.md)).
- **Limits.**
  - Keyword search doesn't find synonyms: "excess" won't find "deductible".
  - A misread word can only be found as it was misread.
  - CSV and Excel imports have no transcription, so they aren't indexed.
