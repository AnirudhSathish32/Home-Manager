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
  Bank_Statements/
  Credit_Card_Statements/
Documents (papers kept because they matter)
  Housing/  Insurance/  Investments/  Loans/  Taxes/
  Jobs/<Employer>/Paystubs/ and Jobs/<Employer>/Documents/   (see taxes.md, "Jobs and pay stubs")
```

The retired `Bills` and `Income` folders are emptied at startup into `Unfiled` and `Jobs`. The original nested layout
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
  and date is filed. Anything missing or unknown goes to Unfiled. No confidence threshold is invented.
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
  menu with Versions, Move and Delete. Select rows to read, move, delete or combine several at once.
- **Filters.** Filter by state or document date. Sort by date, name, recently added or path. Receipts show their
  reconciliation status ("Matched to a charge", "Match proposed", "Several possible charges", "No matching charge
  yet"). Unfiled documents show why they are unfiled.
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

- **Text only.** The vision model returns `full_text`: the visible wording in reading order, including line items and
  footers. It doesn't choose titles, folders, dates, currencies or totals. There is no OCR fallback and no label-based
  field inference.
- **Server requirements.** It needs a server with streaming chat completions, image input and JSON-schema output. The
  app doesn't download or load weights.
- **Codes.** QR codes and barcodes are decoded independently, and their payloads are added as inert text with their
  exact bytes and polygons. Links are never followed.
- **What is kept.** Each result keeps the source hash, dimensions, rotation, preview, full text, line ids, endpoint,
  model id and prompt version. No coordinates or confidence scores are invented.
- **Rotating.** The document page compares the transcription with the preserved image. You can rotate the image and
  create a new reading under **History**.
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
- scanned or near-empty pages are transcribed by the vision model;
- evidence ids are `page-N-line-M`;
- no page is silently skipped, and long PDFs are analysed in chunks.

Mixed digital and scanned PDFs are covered by tests.

### CSV and XLSX imports

**Import transactions** on a CSV/XLSX row previews and imports from the preserved copy (`finance/tabular.py`). No
model is involved.

- **Mapping.** Column mapping is detected or chosen. Date order is inferred only when the whole column is unambiguous.
  The sign convention is explicit, and each rejected row comes with a reason.
- **CSV** is read with the standard `csv` module as strings. Raw values such as `(1,234.56)` and `03/04/2026` are kept
  as they are, along with duplicate headers, empty cells, leading zeros and quoted newlines.
- **XLSX** is read with the standard library's `zipfile` and XML parser, under size and ratio limits.
  - No DOCTYPE processing, no formula evaluation, and no macros or external links.
  - Formula results can't become authoritative without review.
- **Re-importing never duplicates.** Transactions have a source-independent fingerprint (see
  [Typed extraction](#typed-extraction)).

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
- **Reading.** A confirmed group is read under its first page, the lead, with parser version `receipt-images-v1`.
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
  credit card statement, pay stub, investment or loan statement, tax form, contract terms…) in bounded chunks with
  task-specific output limits. A failed chunk is corrected on its own.
- **Deterministic checks:**
  - every citation is an exact quote;
  - every amount is printed in its cited line;
  - names appear in their citation;
  - dates are unambiguous ISO dates;
  - the currency is explicit, or taken from a known account for statements;
  - document arithmetic reconciles: receipt totals, item sums, statement opening and closing balances, pay stubs.
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
  - receipts to transactions, by exact amount, posting window and merchant;
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
