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
  - A changed Inbox file creates a new captured version, and the earlier bytes stay in the evidence store.
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
  - The merchant is the seller printed on the receipt, or inferred from a house brand and flagged for you to confirm.
  - The location is the store's street name (no building number, city or postal code), or Online for delivery
    orders. It is left out when no street is printed.
  - The description is one or two words for what was bought.
  - **Edit description…** replaces the description. **Edit details** on the document page corrects the merchant,
    location and date.
  - A file holding several receipts is titled "First merchant + N more" (see
    [Several receipts in one file](#several-receipts-in-one-file)).
- **Row details.** Under the name: the file name, type, the document's own date, amount, and one state such as Not
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
- Trash offers **Restore** and **Empty trash…**. Empty trash permanently removes every trashed document after
  confirmation: managed copies, preserved versions, readings, text-index passages and ledger records.
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

A PDF is imported from its **saved reading** (`finance/pdf_import.py analyze`, pure code, nothing decoded in the
request). It makes no model or network call, and never touches the Inbox or Library file. A PDF stays a document that
is read and recorded as before: it is not a table file, and `needs_text` and `ready_for_ledger` return the same PDFs
(a PDF the import marked `imported` is still recordable, and still counts as ready for the ledger).
- **What is read.** Only `embedded_text` pages. A scanned page is listed ("Page N is a scanned page; no rows imported.
  Use Record for scanned statements.") and contributes nothing. A PDF read before native layout was saved is blocked
  until **Read again**.
- **Tables and rows.** Every native transactions table is listed (page, headings, row count) and ticked by default;
  other native tables are listed as "not a transactions table". A table that continues on the next page is linked to
  it ("continued from page N"). Pages with no native table are rebuilt from the saved words by baseline and the
  heading's column positions, and so are rows printed below a native table the reader cut short. The import does this
  itself; the reader's tables are unchanged. A balance column is never an amount.
- **Dates, amounts and signs are exact.** A four-digit year is read as printed. A date without a year (or with a
  two-digit year) waits for the year you choose, and the current year is never assumed. A day/month order that the
  column does not settle is a required choice. Amounts go through `core/money.to_minor`. Debit and Credit columns
  decide the sign; a single Amount column uses the chosen account's default (card: positive is money out; checking or
  savings: positive is money in; other types ask), which you can change. The choice is offered whenever any selected
  table has an Amount column, even when another one has Debit and Credit columns. A row whose date or amount does not fit is
  rejected with a reason, never guessed.
- **A number inside the description.** In a row rebuilt from the words, an amount-shaped word that continues the
  description's printed text (joined to the word before it, closer than 1.5 font sizes, in a run that starts in the
  Description column) is description text, not an amount: `09/18 ACCTVERIFY PPD ID 1234567890 0.36` is 0.36 with that
  description, where it used to be rejected. It stays the row's amount only when its whole box lies inside one amount
  column's span (Amount, Debit or Credit; no tolerance) and it is the row's only amount-shaped word centred in an
  amount column (`09/22 LONG DESCRIPTION 12.34`). A Balance column is never an amount column. A joined amount that
  is the row's only amount but crosses its column's edge is rejected with "The amount is printed against the
  description, so it can't be told apart from it." (the row is listed, not lost). An amount printed apart from the
  description inside an amount column is rejected as before. Record rebuilds its rows the same way ([Typed
  extraction](#typed-extraction)). Because this changes what the analyzer finds, `ANALYZER_VERSION` is 2: every PDF
  reading is indexed again at the next start, and the picker shows `indexing: true` until that is done.
- **Flagged pages.** Rows from a page with a layout issue (other than the harmless `unresolved_columns` on a page whose
  rows are rebuilt) start unticked, with the page's message. Ticked rows import like any other.
- **Account.** The dialog ignores the remembered CSV account. An account is preselected only when exactly one active
  account in the document's currency has its last four printed in the reading ("ending in 4821", `XXXX4821`, `*4821`,
  …) and the dialog says where ("Matched …4821 printed on page 1"). Otherwise Import waits for a choice. **New
  account…** prefills the last four and creates the account inside the import request itself, in the same database
  transaction as the rows. A refused or failed import leaves no account. A different currency on the document blocks
  the import; no conversion.
- **Duplicates.** A row already recorded by a CSV/XLSX import, a statement or an earlier PDF import is not inserted
  again, and its evidence is linked. The preview names the source ("Already recorded from import …") and totals money in
  and out for these rows apart from the ticked New ones. A manual entry
  with the same values is replaced, as for CSV. A statement row not yet counted says so.
- **Refusals** name the next step and write nothing: recorded as a receipt, bill, pay stub, tax form or investment
  statement; in Trash; the reading, document or preserved blob changed since the preview; over 20,000 rows or 2,000
  characters in a cell; nothing to import. A PDF recorded as a statement, or not recorded, can be imported.
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
    its row's line; and a quote that is in its line once spacing and the " | " cell separators are ignored (a table
    row quoted with plain spaces) becomes the line's exact text there, when found in one place only. The error names
    which way a citation failed: a line id that isn't in the lines, or a quote that isn't in its line;
  - every amount is printed in its cited line;
  - names appear in their citation;
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

- **Four kinds.** The classifier also proposes a receipt's kind, citing the lines that show it: `fuel`, `dining`,
  `grocery` or `general` (no extra model call). A proposal that is uncited, cites a line that doesn't print its quote,
  or isn't one of the four is read as `general`, with the note "Receipt kind: … was not used" and the receipt in Review.
  No proposal at all is `general` with no note. Each receipt of a file split into several gets its own kind.
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
- **Changing the kind** (the document page, `PATCH /api/receipts/{id}/kind`) reads that receipt again from its saved
  transcription with the new kind's form, never the image. The change is a correction with Undo, written with the
  reading, and later readings keep it. It is refused (409) while any reading of the same file is queued or running.
  On a receipt you reviewed, the amounts, items and review state stay; the new details wait as a proposal until
  **Apply details** (`POST /api/receipts/{id}/details/apply`), itself a correction with Undo that changes no amount.
- **Details that can't be read.** If the kind's new fields fail their checks after the one correction request, the
  receipt is published with today's fields and rows only, and the note "Document details could not be read". The same
  holds for the new pay stub and statement fields.

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
- **Statement rows the model skipped.** After Record, any line the model was given that starts with a date, prints an
  amount after it, and isn't a balance or total line is checked. If no transaction or summary field cites it, the model
  is asked once more for the rows in those lines alone, with the printed period (`missed_statement_lines`,
  `missed_rows`). Rows it finds are checked like the others and placed in printed order. Any still left out become a
  review note quoting up to three of them. The instruction also names small amounts, such as account-verification
  deposits and their reversals, as rows.
- **Amount or running balance.** A row read from one flat line (not a table cell) whose amount is the last of two or
  more amounts printed with cents after its date is sent to review: on a line such as `09/18 DEPOSIT 0.02 0.38` the
  last is the balance (`balance_taken`). The instruction says so too.
- **Account numbers.** The last four are the printed number's own. When the model gives four digits from inside a
  longer number it cites (1234 of 000009000123456), the number's last four are kept instead
  (`core/identifiers.last_four`).
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

Code: `finance/statement_rows.py` (`rebuild`, `rebuilt_pages`), `documents/extraction.py` (`read`, `normalize`,
`publish`), `finance/provenance.py`. Rows are rebuilt by PDF import's rules ([Transaction imports](#transaction-imports)),
with no model and no network.

- **Which pages.** Recording a bank or credit-card statement PDF rebuilds the rows of every `embedded_text` page that
  has a transactions table, a page flagged for overlapping or rotated text included. Those pages' transactions are the
  rebuilt rows. A page with no transactions heading that continues none, a scanned (`vision_model`) page and a reading
  saved without layout keep the model's rows and today's checks. A reading with no layout adds the note "Read this
  document again to take its rows from the printed columns." Readings made before this are rebuilt on **Extract
  again**; a statement you confirmed or rejected is not rewritten.
- **Values.** The date is the Date cell; the description is the Description cell as printed; the amount is the Amount
  cell or the one filled Debit/Withdrawals or Credit/Deposits cell, in minor units. A Balance column is never an
  amount. With one Amount column a bank statement reads negative as money out and a card statement reads positive as
  money out. A description printed in pieces with wide gaps ("ACCTVERIFY      PPD ID: 1234") stays one description:
  text after it that ends before the Amount heading begins is description text, even past the midpoint between the
  two headings (an amount-shaped word is placed as before). This narrows `account-import-pdf` FR-08's midpoint rule
  for both features. The Balance cell is kept as the row's printed balance (`balance_minor` in its evidence), shown in
  the document page's transactions table beside the amount and never read as one. A date with no year, or a two-digit
  year, takes its year from the printed period (a month before the
  period's start month falls in its end year); with no printed period such rows are not recorded and are listed. A
  day/month order the dates can't settle is listed too.
- **The model decides nothing there.** Its rows on a rebuilt page change no date, amount or direction and add no rows.
  One that matches no rebuilt row (by date and amount) becomes a record note quoting it ("The reading listed a row the
  printed columns don't have…"); notes show with the record but are not reasons for review. A rebuilt row the model
  didn't list is still recorded. The missed-row check does not run on rebuilt pages.
- **Rows that are not recorded** are review issues with page, row and reason, in PDF import's words, and the statement
  needs review: a date or amount outside every column, a word straddling two columns, two amounts in one column, both
  debit and credit, an impossible date, an unreadable amount, a currency other than the statement's. A rebuilt page
  with a layout issue other than `unresolved_columns` still gives its rows and the statement needs review, naming the
  page. The same row (date, amount, description) printed on two pages or tables is recorded twice with an issue naming
  both places.
- **Opening and closing balances in the table.** When the model cites a summary amount from a native table row, the
  amount is copied from that row's cell (`native_values.anchor_summary`). A Beginning or Ending Balance row inside the
  transactions table is found by its first printed cell, and its value is read from the Balance column when Amount is
  blank.
- **Balance tables.** A table whose title line (the row directly above its heading) or heading names a balance (or
  "daily ending balance", "daily balance") is not read, starts no continuation, and ends a table that has no reader
  table where its title or a second heading begins. A `Date | Amount | Balance` heading doesn't make a table a balance
  table. When only a title excludes a table that has Description and Amount columns, a note says its rows came from the
  reading.
- **Checks** are unchanged and run on the rebuilt amounts. The arithmetic check is skipped when a row was dropped
  or a model row on another page was left out, so it never reports a false mismatch.
- **If the rebuild fails** the model's rows are used on every page with one issue ("The rows couldn't be rebuilt from
  the printed columns…"); nothing else changes.
- **Evidence.** A rebuilt row's evidence link keeps `{rebuilt, page, table_id, row, line_ids, word_ids, cell_ids,
  quotes}`. `GET /api/provenance/transaction/{id}` gives `document: {id, page, lines, cells}`: the document, the row's
  page, its line ids, and the words to highlight (`cells` is the row's word ids, or its table cells for a row of a
  native table). A trace's **Open source** link for such a row adds the cells to `?lines=`, and the document page
  lights those words.

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
