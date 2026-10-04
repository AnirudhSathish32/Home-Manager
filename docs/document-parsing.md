# Document parsing: decisions (historical record)

> Status update, 2026-09-30: the slices this page planned are built. The CSV/XLSX readers are in `finance/tabular.py` (XLSX is read with the standard library's `zipfile` and XML parser, not openpyxl), the PDF reader is `documents/pdf_reader.py`, and interpretation is typed extraction on the reasoning model ([V2 phases](v2-phases.md)). Two items are still open: OS-level confinement of the reader worker (identity, ACL, network), and grouping several images into one document. The rest of this page is the original decision record.

Decision update, 2026-09-24: image reading uses a local vision model strictly for text extraction. OCR execution and label-based field inference are removed. A separate reasoning model, to be selected by the user, will consume saved text for fields, titles and classification. Earlier OCR-first and judge-cascade proposals below are superseded by this separation. See [current extraction behavior](receipt-parsing.md).

Implemented: text-only vision extraction and barcode decoding for PNG/JPEG, immutable evidence and a viewer. Further sections describe planned readers and interpretation. Worker resource limits exist; restricted identity/ACL/network confinement remains future hardening.

## Outcome and current integration point

The next usable result is a document detail screen showing preserved source evidence, extracted text/tables, proposed financial fields, and explicit issues. Capturing a file and successfully parsing it are independently testable. D1–D2 already test byte preservation and history; parsing adds content-level testing rather than replacing those checks.

The application has a `Scanner`, SQLite `Store`, immutable blobs, occurrence/version history and a serial work coordinator. Receipt parsing adds typed extraction results, `parse_runs`, a bounded image-preparation subprocess and local vision request and an evidence viewer. The existing `jobs` table still represents scans. Financial tables and model interpretation remain future work.

Do not add financial extraction directly to `Scanner.capture`. After a successful capture commit, a coordinator can queue parsing by immutable blob hash. On restart or repeat scans, reconcile eligible captured blobs against parse-run records so a crash between capture and queueing cannot strand a document. Backfill already captured files through the same mechanism; users should not need to edit or recopy their originals.

## Decisions and defaults

| Decision | Proposed choice | Status |
| --- | --- | --- |
| Parse input | Immutable captured blob, resolved by trusted application code; verify its hash before parsing | Ready |
| Stage boundaries | Read content -> interpret fields -> validate -> review; keep separate outputs/statuses | Ready |
| Required formats | PNG/JPEG receipts first; CSV/XLSX, scanned bills and PDF statements next | Confirmed by user |
| CSV reader | Python standard-library `csv`, explicit string-preserving dialect/encoding handling | Ready |
| XLSX reader | openpyxl with hardened package inspection and preservation of raw numerical evidence | Ready, exact dependency pin at implementation |
| Image text reader | Local vision returns only full text; no OCR fallback or financial inference | Implemented |
| Interpretation | Separate local reasoning model consumes saved evidence; optional judge assessment follows later | Implemented (typed extraction; decision-model independent checks advisory) |
| Persistence | Add versioned SQLite extraction tables and artifact manifests; retain existing inventory tables | Ready |
| Trigger | UI option to parse newly captured supported files, plus Parse/Reprocess on existing captured versions | Ready; default off until parser setup passes |
| Review | Source alongside proposed fields, editable corrections with provenance; no model approval rights | Ready |
| Private deployment | Local parsing; separate resource-limited worker initially, restricted identity/ACL/network confinement still planned | Initial worker is not an OS sandbox |
| Financial publication | Separate later service/milestone; parsing success creates no posted transactions | Ready |

## A. One common evidence contract

Define Pydantic contracts before implementing any reader. `ParseResult` is a manifest referencing bounded, paginated units, not one enormous text string sent to a model or browser.

| Object | Required information |
| --- | --- |
| Parse request | Blob hash, parser ID/version, explicit options, schema version, limits, effective configuration fingerprint |
| Parse result | Run ID, input hash, actual detected format, reader/dependency versions, status, units/artifact references, structured issues, timing, coverage and truncation flags |
| Content unit | Stable ID within the run; sheet/table/page/image identity; ordered blocks/cells; original evidence references |
| Evidence anchor | Run ID plus CSV record/column and physical line span; XLSX sheet/cell; or image ID and coordinate polygon |
| Raw cell/text | Original extracted string or source lexical value, source type/format, normalized display value if any, extraction method |
| Parse issue | Machine-readable code, severity, affected unit/field, recoverable flag, user-facing explanation |

Anchor IDs are scoped to a parse run. Never silently reuse them after a new parser or vision version changes segmentation. Record input byte hash and all derivation steps so an anchor is resolvable even if a source file moves or changes later.

For images, store dimensions and transformations linking any oriented image derivative back to original coordinates. Preserve reading order as a proposed order and indicate uncertain table/column structure. For CSV quoted multiline fields, a logical record number is not the same as a physical line number; retain both. For workbook cells, preserve sheet names and explicit cell coordinates rather than trusting column headers to be unique.

`succeeded` means the requested content was extracted within declared scope, not that its interpretation is correct. `partial` must enumerate omitted sheets, image regions, rows or pages. An empty result must distinguish genuinely empty content, no readable text, unsupported content and failure. No hidden truncation.

## B. Format-specific reading rules

### CSV

Use `csv.reader` with newline handling and string values; avoid float conversion and automatic dataframe coercion. Python's CSV reader supports string-preserving rows and dialect settings; header inference is heuristic rather than authoritative ([Python documentation](https://docs.python.org/3.13/library/csv.html)).

Handle BOM-marked encodings explicitly; default to strict UTF-8 when no BOM exists. Invalid decoding creates an actionable issue and a user-selected encoding option rather than replacement characters. Delimiter/header inference proposes settings with a preview; conflicting candidates require a choice saved in an import profile. Keep duplicate headers, empty cells, leading-zero identifiers, quoted commas/newlines, preamble rows and trailing totals intact. Preserve raw values such as `(1,234.56)` and `03/04/2026`; interpretation determines sign, locale and date semantics later.

### XLSX

Use bounded package inspection before opening the workbook: validate it as XLSX, cap ZIP entries/expanded bytes, protect XML parsing, and reject unsupported encrypted/macro-enabled formats. openpyxl documents XML security considerations and recommends defusedxml; its read-only and data-only options support separate formula and cached-value views ([project documentation](https://openpyxl.readthedocs.io/en/stable/), [reader tutorial](https://openpyxl.readthedocs.io/en/stable/tutorial.html)).

Extract sheet inventory, hidden-sheet status, merged ranges, data cell coordinates, source types and formatting metadata. Include hidden data with an explicit flag; do not silently treat the active sheet as the whole workbook. Never execute formulas, macros, links or Excel/COM automation. Preserve formulas as inert strings alongside any cached results; missing/stale caches cannot be promoted to authoritative values without review.

Preserve the raw numeric lexical values from worksheet XML alongside decoded values and number formats. Financial normalization must use Decimal over preserved source decimals, not arithmetic on a library-provided float. Preserve workbook date epoch and distinguish dates, identifiers and amounts through an explicit mapping. Display formatting may show rounding or leading zeros; retain source value and formatting rather than silently choosing one as truth. The preview is a data-grid view, not a pixel-perfect Excel rendering. Images/charts/embedded objects are detected and flagged as unread components initially; extracting embedded receipt images would be an explicit extension.

### PNG/JPEG

Verify decoding and enforce pixel/memory limits before preview generation. Send the oriented image to the configured local vision model for text only. Preserve full transcription and line IDs without fabricated geometric anchors or confidence scores. Decode QR/barcodes separately with exact bytes and coordinates.

One image forms one evidence unit, unless it holds several pieces of paper, or is a page of a combined document (both below). Evaluate transcription coverage, decimals, signs, faded text, columns and languages locally. Interpretation belongs in the separate reasoning stage.

### Several receipts in one file (built 2026-10-01)

A file can hold several receipts: a feeder or scan-app PDF with one receipt per page, a flatbed scan or photo with several receipts on it, or receipts stacked one under another in one tall image. Each one is recorded as its own receipt. This happens in two steps.

**1. Pieces of paper (reading, no model).** `documents/regions.py` looks for separate pieces of paper on a coarse grid of the image (numpy only), inside the bounded reader child. It splits only where the split is plain:
- On a contrasting background (scanner lid open, a dark table), each separate bright area big enough to be a receipt is one region.
- On a background as light as the paper, only side-by-side receipts with a clear full-height gap are separated. A gap inside one receipt is usually a full-width band, so light backgrounds are never cut horizontally.

Each region is cropped (`region-N.png`, or `page-N-region-M.png` for a scanned PDF page) and transcribed on its own. Lines stay numbered across the regions (`line-N`, `page-N-line-I`), and `regions` in the reading records each region's box and line range. An image with one piece of paper reads exactly as before, so parser versions did not change.

**2. Receipts in the text (extraction).** The file is classified once as usual. When it is a receipt, it may hold several if it has more than one page or region, or more than one receipt total line (not a subtotal or total tax). Then one `ReceiptStarts` question, asked chunk by chunk, lists the first line of each receipt; a single receipt costs nothing extra. Code then checks and adjusts the answer:
- A start within two lines of a page or region break moves to that break.
- A part without a total, payment or balance line joins its neighbour: a heading joins the receipt after it, and a second page joins the receipt before it.
- If the answer is unusable, the file is split at its page and region breaks.

Every part is then classified before any is read. If one is not a receipt, the file is read as one document, so statements and other types stay one per file. Otherwise each part is read on its own lines (summary, seller, items, description, and the rewards and codes printed on its own piece of paper) and published as receipt segment N (`receipts.segment`, `UNIQUE(blob_hash, segment)`, migration 054).

**Review the split once.** `document_segments` records each part's first and last line.
- Until the user confirms the split, each receipt carries the note "split from a file holding several" and waits in Review.
- **Confirm split** on the document's page drops that note, and each receipt then counts by its own checks.
- The user can also **Merge with next** or **Split here** at a line of the receipt's own text. That split is saved as the user's (it wins over the model's on later readings), and the file is recorded again.

A receipt whose segment a later reading no longer finds stops counting (rejected automatically, restored if found again). A receipt the user already decided keeps that decision, with a note to check the split.

In the library, a file holding several receipts is titled "First merchant + N more". It shows no single amount, and its date is the earliest receipt's. It is filed under the first receipt's merchant and date. Code: `ExtractionService.segments`, `split`, `confirm_split`, `set_split`; `GET/PUT /api/documents/{id}/segments`, `POST …/segments/confirm`.

### Several images as one document (built 2026-10-01)

A long receipt photographed in parts, or a document scanned one page per image, can be read as one document whose pages are those images (`documents/grouping.py`, migration 055).

- **Suggested, never automatic.** After each capture, images from the same folder suggest a group when their names continue one numbered series (`IMG_0012`, `IMG_0013`; `scan (1)`, `scan (2)`; `receipt_p1`, `receipt_p2`) and their files were saved within two minutes of each other. Suggestions wait in **Review → Images that look like one document**, where you choose **Combine** or **Keep separate**. A dismissed suggestion is never made again.
- **Combining directly.** In the library, select 2 to 20 PNG or JPEG images and choose **Combine as pages**. Pages go in file-name order.
- **Reading.** A confirmed group is read under its first page, the lead, with parser version `receipt-images-v1`:
  - Each page image is prepared by its own bounded worker child and transcribed.
  - The result has the PDF's page-aware shape: `pages`, with line ids `page-N-line-I`. Each image's own pieces of paper keep their line ranges.
  - `page_hashes` names each page's preserved bytes. `options_json` holds the page hashes in order, so a reorder is a new reading.
  - Codes decoded from the pages are not carried into the combined result.
- **Records.** The lead carries the reading and the records; the later pages are hidden from lists and counts. A later page's own receipt stops counting (rejected automatically). A later page can't be read on its own.
- **Changing it.** The document's page shows its pages beside the image. You can move a page earlier or later, which reads it again in the new order. **Separate pages** makes each image its own document again, and each is read and recorded on its own.
- **Limit.** Only receipts of later pages are retired. A later page recorded as another type, such as a bill, keeps its record.

Code: `Groups.suggest`, `create`, `set_status`, `reorder`; `ReceiptService.run` (group branch) with `combine_pages`; `Manager.read_group`. API: `GET/POST /api/document-groups`, `PATCH /api/document-groups/{id}`, `GET /api/documents/{id}/group`, `GET /api/receipt-runs/{id}/pages/{n}`.

### PDF decision

Current capture rejects PDF. If real statements are PDFs, PDF support must move into the next scope with both capture eligibility and a tested reader, not merely a new extension in the allowlist. The design would classify each page as native text, scanned or mixed, preserving page coordinates and transcribing scanned regions with the vision model. It must not assume the existence of a text layer means the entire page is correctly represented. PDF engine, encrypted-file handling and page limits are decisions to settle if this format is confirmed.

## C. Interpretation and financial schemas

Preserve two different outputs: evidence from reading, and `InterpretationResult` containing candidate fields supported by evidence. A model cannot rewrite the parse result to make its interpretation appear consistent.

Every candidate field carries its raw evidence references, proposed normalized value, method (mapping/model/user), field status, issues, and producer/profile/model versions. Currency uses an unambiguous ISO code; money uses Decimal strings until validated and converted to integer minor units. Store currency/date ambiguity as unresolved alternatives, not guesses. Account matching uses local aliases or user-selected bindings, never automatically full identifiers inferred from a filename.

Initial interpretation schemas:

| Type | Candidate payload | Required interpretation distinctions |
| --- | --- | --- |
| Transaction table | Account binding, rows with description, amount/currency, transaction/posted dates, status and source identifiers where present | Debit/credit conventions, duplicate evidence, transfers, and summary rows versus transactions |
| Bank/card statement | Account candidate, statement period, balance snapshots, transaction table, due/minimum-payment fields where applicable | Opening/closing balances and payment obligations are not spending rows |
| Receipt | Merchant, purchase date, total and currency; optional subtotal/tax/tip/line items | Total versus subtotal; paid purchase versus quote; match a posting before creating a second expense |
| Bill | Issuer, invoice reference, service period, due date, amount due and currency | Amount due does not prove payment |
| Unknown/mixed | Evidence and candidate component types | Preserve uncertainty instead of forcing a type |

Required fields are schema-dependent. Missing account/date/currency or a blocking extraction issue prevents financial publication but does not hide extracted text. Receipt line-item itemization can be deferred while total/date/currency accuracy is established. A model-proposed date cannot inherit the folder month without evidence.

Import profiles are versioned data describing sheet/range/header, field mappings, date format, decimal convention, sign policy and account binding. The LLM may suggest a profile; the user accepts it. Save reusable layout settings separately from account-specific context. A bank changing its export headers invalidates the profile match and triggers review.

## D. Judge and escalation contract

Use the existing `ExtractionAssessment` contract and local-only capability boundaries. Format reading happens before Laya's textual assessment. Laya does not have image pixels and cannot certify visual transcription correctness; a low score is one escalation trigger, not the only one.

Pass bounded evidence packets containing the candidate, surrounding rows/text, headers, relevant totals, transcription completeness signals and deterministic check results. Truncated evidence must be explicit and prevent a high-confidence pass. Split large statements by coherent tables/row groups with repeated header/context references, then validate whole-document coverage; never equate the first context window with the whole statement.

Keep distinct routing results: sufficient-for-review, needs-text-interpretation, needs-vision-inspection, needs-profile, needs-better-source, and unavailable. Hard schema, coverage or arithmetic failures cannot be overridden by a model score. Re-evaluation after escalation compares alternatives without dropping the original. Unresolved disagreement remains visible to the user.

LangChain wraps local adapters and schema handling; it does not own the database queue, file access, policy, approvals or money calculations. Initially run Laya assessments in shadow mode and use conservative interpretation/review. Activate model-skipping only after held-out evaluation establishes that the routing policy does not sacrifice critical-field accuracy. Fine-tuning is not a prerequisite: reject an unsuitable judge configuration rather than expanding this project into model development.

## E. Persistence, jobs and versioning

Keep existing inventory tables intact. Schema 2 now adds `parse_runs` through sequential migration, with a SQLite backup before upgrading schema 1. Additional extraction/review tables can follow in later migrations. Do not copy a live WAL database as if it were a single standalone file.

Proposed new tables: `parse_runs`, `parse_units`, `parse_artifacts`, `parse_issues`, `interpretation_runs`, `candidate_fields`, `assessments`, `import_profiles`, and `review_revisions`. Implement only those needed by the next slice. Financial transaction/account tables remain a separate boundary.

Cache parsing by blob hash + parser/build version + schema version + options fingerprint. Use an active-run uniqueness constraint and durable lease to avoid duplicate work. Interpretation caching must also include the parse-run ID, profile version, account binding, relevant user context and model/prompt versions. Identical bytes can safely share format parsing; they must not inherit another account's financial interpretation merely because the hashes match.

Large extracted content lives in immutable bounded artifacts under the managed root; SQLite stores manifests and indexed metadata. Use staged write, hash, atomic publication, then transactional visibility, with a recovery journal as in capture. A worker never writes to SQLite directly: it returns schema-validated artifacts/results to the trusted coordinator. Store UTC timestamps and explicit run state separately from source dates.

Runs progress through queued -> running -> succeeded/partial/failed/needs-configuration, with interrupted work retried or surfaced on restart. Limits, timeouts and missing runtimes use typed errors, not empty success. Reprocessing creates a new immutable run. The UI keeps the last complete result available but labels it stale when a newer source version is selected; failure cannot replace it with an empty result. User corrections and approvals bind to an exact run/field and cannot silently transfer to changed evidence. Changing amount/currency/date invalidates dependent conversion and match candidates.

## F. Worker and security boundary

D1–D2 currently copy bytes in one in-process worker. Parsing invokes complex third-party code and needs a separate local worker with a minimal environment, no secrets, no source-directory access, no arbitrary URLs, read-only access to the selected snapshot, and write access only to that job's scratch space. A plain subprocess does not provide these restrictions automatically.

For Windows, implement a restricted worker identity/token plus explicit file ACLs and a network-denial mechanism; use a Job Object for process-tree cleanup and CPU/memory limits. Validate the actual confinement with tests before parsing personal files. The parent owns the database and invokes model endpoints separately; the parser itself does not receive a loopback-network exemption or bearer credentials. If enforcing this boundary needs setup outside ordinary user permissions, document that concrete setup requirement before implementation; do not claim sandboxing merely from using a subprocess.

Start with one extraction job at a time. Proposed initial limits for benchmarking: 120 seconds and 1 GiB worker memory per document, 40 megapixels per image, 100,000 rows/one million nonempty cells across a workbook, 256 MiB expanded workbook content, and 64 MiB extracted output. These are conservative starting values, not accuracy targets; overruns return an explicit partial/limit result and allow a controlled rerun, never silent truncation. Separate local model budgets and VRAM admission apply when escalation is enabled.

Do not render workbook/CSV content as executable HTML, formulas or hyperlinks. Serve authorized image previews through opaque IDs, with correct MIME and no external resources. Raw originals, previews, transcribed text and interpretation outputs are equally private. Logs keep IDs, statuses and timings rather than document contents. Hosted tracing remains disabled.

## G. UI and API additions

Keep Scan documents as capture/discovery. Add explicit Parse selected / Parse pending controls, then an optional auto-parse-after-capture preference once engines are configured. Display capture, parsing, interpretation and review status independently.

Add a document details panel with version selector, parsed-sheet/table preview or image with transcription and barcode highlights, field candidates, issues and run provenance. Selecting a candidate should highlight its evidence. A user can correct values or import-profile settings, request another parse, and compare versions. Initial parse-only slices may show evidence without financial fields, clearly labeled; financial review is a subsequent capability.

Proposed authenticated API contracts: enqueue parsing for a captured version, retrieve parse-run status, paginate units, retrieve a bounded unit/preview, list interpretation fields/issues, and create a review revision bound to an exact run. Never accept filesystem paths from a model or document. Unknown run IDs, inaccessible artifacts and stale revision submissions fail explicitly. Existing loopback auth/origin checks continue to apply.

FX lookup/conversion remains after amount/currency/date interpretation; preserve the existing agent tool sequence. Parsing itself does not fetch rates, calculate spending, match financial duplicates definitively, or write an Excel report.

## H. Implementation order and gates

1. **Contracts and migration:** synthetic parse results, versioning, durable jobs, and empty-state UI; no reader dependency yet.
2. **Vision transcription plus evidence viewer:** initial PNG/JPEG implementation is available. Validate accuracy on local examples; strengthen worker confinement separately.
3. **Remaining readers:** CSV then XLSX and PDF statements/scanned bills. Exact strings, cell/page anchors and declared coverage are independently testable without models.
4. **Interpretation and judge cascade:** one document type end to end, local adapters and Laya shadow results; build calibration dataset before enabling confidence-based shortcuts.
5. **Review integration:** typed corrections, revision conflicts, deterministic validations, and explicit publication boundary; then connect approved records to the financial services roadmap.

Test parsing success/failure independently of model behavior. Structured-reader fixtures require exact raw evidence preservation, including leading zeros, duplicate headers, newline-containing cells, formula caches, merged/hidden sheets and decimal/date conventions. Vision/reasoning fixtures require field-level ground truth and acceptable abstentions, with splits by source/layout. Measure missing-row/region rate, critical-field error and false-acceptance rate alongside readability scores and latency. Keep real document test sets local and out of Git; synthetic fixtures remain the committed regression suite.

## User inputs that change the next slice

- Resolved: scanned receipts first; CSV, Excel, scanned bills and PDF statements are also required.
- Which document languages are required? This changes vision language evaluation, judge checkpoint evaluation and parsing conventions.
- Resolved: show both complete extracted receipt text/decoded codes and provisional financial fields. Formal model interpretation and editable review remain subsequent capabilities.

Representative redacted layouts will eventually be needed for accurate mappings and evaluation. GPU model and inference runtime remain necessary before the vision/model spike, but not for deciding or implementing deterministic parser contracts. No additional permission question is needed merely to continue architecture work.
