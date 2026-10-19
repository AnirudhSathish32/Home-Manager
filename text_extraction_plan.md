# Structured vision text extraction plan

Status: native PDF layout is now connected to classification, typed extraction, general reasoning, search and the source viewer (2026-10-13). The user-visible wiring described below is implemented. The user's failing paystub has not been inspected, and synthetic tests do not establish its accuracy. No OCR dependency was added. Paths below are relative to the repository root.

## Document forms: what it closes for pay stubs (2026-10-18)

`typed-extraction-v23-document-forms` (specs/document-forms; docs/money.md "Money in and paystubs") closes these pay stub items:
- **Wrong-column values counted automatically** (the paystub diagnosis below): a this-period value whose printed label or column heading reads as year to date or annual, that is larger than its year to date, or that equals it after the first pay period, is now left out and sent to review on every path (validated cells, native PDF cells and flat text). A characterization test reproduced the defect on the earlier code (an all-year-to-date stub was verified with gross 32,500.00) and passes now.
- **Recording which row and column a value came from**: every pay amount keeps its printed row label and column heading, cited.
- **Hours, rate, PTO and deposit splits** are kept, with hours × rate and the split sum as checks.
- **Recording wrong-column values separately** (step 1 of the diagnosis): the `document_forms` eval task reports, per pay stub fixture, the wrong-column values that would have counted automatically (target 0).

Still open from this plan: the user's own paystub reproduction (run in their terminal; only `summary.json` is shared), live-model evaluation, the focused vision pass and saved payroll templates ([open work](docs/open-work.md)).

## Consumer wiring implementation (2026-10-13)

- `documents/layout_context.py` provides one readable projection and typed table adapter. Native rows have distinct IDs, even in side-by-side tables; cells retain their original native IDs, words and source lines. Native evidence never becomes a `VisionCell`. Historical text and citations stay accessible. Unsupported orientation, damaged Unicode/geometry and overlapping text use the original text with review issues instead of promoting a broken layout.
- `typed-extraction-v22-native-cells` gives every document type table headings and row/cell IDs during classification, summary and row extraction. Paystub table rows and uncovered text use separate requests, so a table cannot suppress a nearby deduction or other flat-text row. Whole-document summaries prioritize labels and document ends when bounded input cannot fit; omissions are recorded for review. Unaccounted native body rows also require review.
- Paystub column roles support independent Current and YTD columns, including current-only Amount tables, and exclude Hours/Rate columns. Invoice/receipt quantities, unit prices and extended amounts; statement debit/credit columns; investment quantities, prices, market values, basis and explicit net amounts; and named summary amounts are copied from unambiguous printed cells in application code. Unknown roles stay unresolved and require review. Required transaction/trade/tax amounts that cannot be resolved leave that row out of the ledger with a review issue; they do not become guessed amounts.
- Cell evidence persists in extraction results and ledger locators. Summary Find actions and supported ledger amounts resolve to native cell IDs. The **Tables** tab labels these tables **From PDF text positions**. Clicking a nonblank cell shows its individual word boxes on the saved page preview using the saved affine transform. Page switching, **Original**, **Text**, and **Original text order** retain access to the source and historical evidence. Vision cells continue to link to text without invented geometry.
- Search index version 2 and `financial-interpretation-v6-native-layout` use the same readable projection. General reasoning repeats table headings within bounded chunks. Index backfill runs on opening the library; historical search/citation line IDs can still be retrieved.
- Existing v3 native readings acquire tables and previews when reopened; rerun ledger extraction to use the new adapters. Older PDFs need **Read again** to capture positions from the preserved original. Existing protection for user-reviewed/corrected records remains in place. No saved library was modified during implementation.
- The transcription evaluation now has ten clear/faded table fixtures, covering reversed Current/YTD, blank/zero/negative/equal cells, Hours/Rate and invoice quantities/prices/totals. It reports correct, missing, wrong and extra cells, wrong-column values, table review cases and text length alongside the runner's existing latency statistics. A perfect flat transcription with no table fails table coverage. This is measurement infrastructure, not a measured live-model accuracy result.

Verification includes a real bounded PDF read through typed extraction and ledger publication using a scripted model that deliberately chooses YTD as Current, plus search/citation checks, invoice and statement column tests, current-only side-by-side rows, mixed table/text chunk coverage, and an Edge browser test of tables, cell highlights, rotated/cropped previews and original-text access.

Final verification: the extraction/layout/paystub/vision-table/region regression run passed 59 tests (one opt-in browser test skipped), and all five document-page browser tests passed with browser testing enabled. Ruff and mypy passed. The broader suite initially reported 891 passed, 66 skipped and five failures caused by stale test fixtures; those fixtures were corrected and all five failing cases passed in focused reruns. The full suite was not repeated after those corrections. No live-model accuracy claim follows from these scripted-model checks.

Still open: live configured-model and private-corpus evaluation, comparison against a saved text-only baseline, automatic merged/stacked-header reconstruction, wrapped-cell joins, form-field association, cross-page continuation and repeated-header/footer detection. Focused scan rereads and user-confirmed payroll templates remain proposed alternatives, not prerequisites or implemented features. The private-corpus run remains a user-run step under the repository's privacy rule; no private document or local profile settings were inspected.

## PDF ingestion implementation (2026-10-13)

- `documents/pdf_layout.py` defines a versioned native evidence contract, independent of `VisionCell`: raw engine Unicode values and indexes, decoded characters, words, visual lines, ordered blocks, tables/cells, coverage issues, source hash and page metadata. Validators reject unknown references, copied-text changes, duplicate membership, missing word/line coverage, invalid bounds and overlapping or missing cell slots. Original embedded text and `page-N-line-M` citations remain unchanged.
- `documents/pdf_reader.py` captures this evidence inside the existing bounded worker. Every page receives a bounded preview and a PDF-canvas-to-preview affine transform derived from PDFium's own coordinate conversion. Crop boxes and all four page rotations are tested. UTF-16 continuation indexes and engine-expanded ligatures are retained explicitly; generated whitespace gets no invented glyph box.
- Reconstruction handles independent X/Y placements, shuffled content streams, ordinary textual headings with repeated numeric rows, right-aligned values, blanks, zeros, separate tables alongside one another, and narrative columns. Native tables preserve printed headings without assigning financial meanings. The readable projection now supplies search and model inputs through the shared adapter above.
- The parser is `pdf-pages-v3-layout`; completed v1/v2 results can still be read/recovered. A new read uses the preserved PDF and keeps earlier runs. Native previews are available through the existing page-image endpoint. Publication checks the source hash, page number and preview dimensions. `typed-extraction-v21-pdf-layout-review` carries native coverage issues into record review so ambiguous or possibly incomplete native evidence cannot automatically count.
- Scanned/near-empty pages still use vision. A native page containing image objects retains its native evidence and requires review; automatic region OCR/vision merging is not implemented. Image detection is deliberately conservative, including logos. Duplicate/overlapping glyphs, unsupported text orientation, missing glyph geometry, Unicode mapping errors and unresolved columns are flagged. Page rotation metadata and preview transforms are supported; reconstructing text that runs vertically or upside down is not yet supported.
- Limits: 100,000 engine characters per page, 250,000 per document, 30,000 words and 5,000 layout lines per page, 100 tables per page, 500 rows/40 columns per table, 24 MiB each for manifest/result, and 64 MiB of page/region previews per run. Exceeding a bound fails explicitly without saving a truncated manifest/result. The existing 200-page, worker timeout and process-memory limits remain. Storage admission reserves 128 MiB for the new artifacts.

Current limitations: table detection requires an ordinary single header row and at least two supported body rows. The schema represents spans, but automatic merged/stacked-header reconstruction, wrapped-cell joins, rich form-field association, cross-page continuation and repeated-header/footer detection remain future work. Ambiguous candidates retain text rather than fabricated cell relationships. Narrative blocks are currently conservative line-sized paragraphs/lists/fields, not full semantic sections. Native tables and source overlays are now visible; their accuracy on the user's paystub remains unmeasured.

Verification lives in `tests/test_pdf_layout.py`, `tests/test_pdf_reader.py`, `tests/test_pdf.py` and the extraction review regression. Fixtures use independently positioned text without pipes, including shuffled text order, paystub/invoice/statement columns, side-by-side tables, narrative columns, negative/blank/zero cells, Unicode, duplicate layers, mixed native/raster pages, bounds, versioned recovery and resource limits. No private financial document was opened.

One local synthetic size/timing check (not a throughput guarantee): two pages with 100 body rows total, 3,438 engine characters and 608 words took 0.258 seconds in-process for worker capture plus assembly, without a model. It produced two tables, a 970,466-byte manifest, an 878,770-byte result and 525,122 bytes of PNG previews. This excludes child-process startup, database publication and model work; native geometry is substantially larger than flat text, so the artifact bounds can be reached before the character count limit.

## Follow-up: paystub alternatives and purchase invoices (2026-10-13)

The sections below preserve the earlier diagnosis, proposals and delivery record. Their descriptions of missing native geometry, consumer wiring and evaluation counters are superseded by the implementation records above; the explicitly listed remaining work above is current.

### Paystub diagnosis and proposed next step

The user's report is evidence that the current approach is insufficient for their case. It does not yet establish whether the failure is in producing tables, validating them, assigning column meanings, passing all rows to reasoning, or displaying the result. Correct transcription alone does not establish which printed column supplies an amount. The current native PDF reader also accepts embedded text without preserving character positions, so a readable PDF can bypass vision and arrive as flat text with no separators.

Recommended sequence (proposed, not implemented):

1. **Inspect the handoff on a shareable or synthetic failing example.** Compare saved text, table validation issues, accepted cells, summary and row request coverage, and the normalized paystub. In particular, check chunks containing both table rows and non-table rows: currently any table context selects the classification-only row schema for that chunk. Rows outside those tables must retain their own extraction path. Record wrong-column values, missing values and review decisions separately.
2. **For PDFs with a usable text layer, retain native text positions.** The existing `pypdfium2` dependency exposes character boxes. Group characters into words and sections using their actual PDF positions, and associate amounts with printed headings. Preserve page coordinates, reading order and blank cells. This needs layout code and validation, but no OCR engine or extra package. PDFs without usable text positions use the image path. See the [pypdfium2 character-box API](https://pypdfium2.readthedocs.io/en/stable/python_api.html#pypdfium2.PdfTextPage.get_charbox).
3. **For images/scans, try a focused second vision pass.** Read earnings, taxes, employee deductions, employer contributions and summary separately, keeping headings in each crop. Start with manual or template section boundaries for repeat layouts; do not assume a model's proposed crop coordinates are accurate. Ask for named values with the printed label, printed column heading and source quote for each amount. Example handoff: `section=earnings; label=Regular pay; current=2000.00 [heading: This period]; ytd=52000.00 [heading: Year to date]`. Preserve blank as null. The reasoning model categorizes these records, and code copies and checks values. This removes the need to infer column meaning again from a wide matrix, but cannot repair a wrong visual association without rereading the source. Compare against the existing transcription and send disagreements to review; a second vision read is not independent spatial evidence.
4. **For a stable payroll layout, save a user-confirmed template.** Store section boundaries and column mappings for that employer/provider, validated against headings on every read. Fall back to review when the layout changes. This can reduce repeated ambiguity but adds a setup step and must not apply to a different layout silently.

Prefer native PDF positions when available; otherwise prototype the focused vision pass before adopting a heavier document engine. Merely replacing the displayed table with Markdown or HTML would not restore lost column associations. All options still need amount citations and arithmetic checks. No private financial document was opened during this assessment.

### Shared PDF layout implementation design (proposed 2026-10-13)

Scope correction from the user: apply this to all PDF ingestion, not only paystubs. Build one shared layout/evidence layer before document classification, then let the existing typed extractors interpret it. PDFs with a usable text layer use the installed `pypdfium2` package for text positions; scanned pages retain the vision path. The first ingestion implementation is described above; the full design below remains the target and has not been evaluated against the user's documents. The earlier paystub diagnosis motivates this work; it does not limit its scope.

#### Gaps at design time (before the ingestion implementation above)

- `pdf_reader.worker()` calls `get_text_bounded()` and saves only the resulting text in `pages.json`. It closes the text page before keeping any character geometry. The native/scan decision tests character count and replacement characters, not layout quality.
- `complete_pdf()` calls `embedded_tables()`, which recognizes literal pipe separators. Most positioned PDF tables need a different reconstruction path.
- Structured table context currently reaches paystub and bill extraction, while other document types still need a common layout adapter. Layout must be accessible to classification, summaries, row extraction, document reasoning, search text and the source viewer, not gated on a paystub classification.
- `VisionRow` has one `line_id`, and `anchor_paystub()` indexes rows by that line. Two separate tables at the same vertical position or a wrapped row cannot safely be forced into this assumption.
- `paystub_columns()` requires exactly one Current column and one YTD column. A current-only summary or a multi-level heading such as Current → Hours / Rate / Amount needs explicit column roles.
- The viewer uses an embedded PDF frame, native pages do not have saved page images, and PDF Find actions currently switch to flat text. Actual cell highlighting requires a rendered page surface with a known transform.

#### Proposed flow

```text
Preserved PDF
  → bounded page reader
      native text: characters + positions + page transform
      scanned/unsupported regions: existing vision path with explicit provenance
  → shared layout: blocks, headings, paragraphs, lists, fields and tables
  → document classification + document-specific interpretation
  → cited block/row/cell IDs sent to reasoning
  → application validates selected evidence, copies values and applies type-specific checks
  → existing record publication/filing + search + source viewer
```

1. **Capture native evidence before flattening.** In the existing child worker, retain the raw embedded text and collect characters with their PDFium character indexes, Unicode values and boxes. Persist source hash, page number, effective page bounds, rotation and the transform used to render a preview. Work in one documented page coordinate system. Do not zip a flattened Python string with character boxes: PDFium can insert or exclude characters in its text APIs, so preserve the engine indexes and handle index translation explicitly. Generated whitespace has no invented glyph box; ligatures, undecodable characters, unusual text rotation and degenerate boxes must be accounted for or flagged. The installed package's `get_text_range()` also has a Unicode limitation; a native character adapter must use tested engine APIs rather than silently dropping characters.
2. **Add a shared, versioned layout contract.** Add an optional `layout` field to `PDFPage`, containing page metadata, source words and character references, geometry, ordered blocks and tables. Each block has a stable ID, source type and coverage/status; block kinds include heading, paragraph, list, key-value group and table. A table records header rows, body rows, cell spans and word references. Cells may cite several words and source lines; merged headers must not be forced into a fabricated rectangular transcription. Native elements use `source="pdf_text"`; vision elements keep model provenance and optional/absent geometry. Do not put native geometry into `VisionCell` or give it OCR confidence. Store copied text separately from normalized reading-order text. Preserve raw text and historical line citations. Native validation checks source word membership, exact copied characters, bounds and unambiguous assignment. It must support different PDF text-stream order from visual order.
3. **Reconstruct generic page layout before knowing document type.** A new `documents/pdf_layout.py` module should group characters into words using spacing relative to font/character size, then identify blocks from headings, whitespace and repeated alignment. Recover reading order separately within multiple text columns. Identify tables from repeated row/column relationships; alignment alone must not turn an address block, a two-column letter or a form into a table. Group rows within each candidate table, not across everything sharing a page Y coordinate. Infer column bands using printed headers and repeated text/numeric alignment, including right-aligned amounts. Keep table detection separate from semantic labels such as current pay or debit. Join wrapped cells only when geometry supports it. Handle stacked/merged headings and explicit row/column spans, preserve blank cells, and flag uncertain membership. Link tables across pages only when section/header compatibility supports continuation; retain page-local evidence IDs. Repeated page headers/footers stay stored but should not become transaction rows or duplicate summary values.
4. **Interpret fields using document-specific adapters.** All PDF types receive the same blocks and tables, including documents that are filed but do not produce ledger entries. The shared reader copies printed labels and values; typed adapters assign meanings. Keep narrative paragraphs and lists as text, and represent forms/summary boxes as labeled values even when they are not tables. Document-specific examples and validation rules are listed below. Unknown or conflicting column roles remain unresolved rather than being inferred from magnitude or position alone.
5. **Give every reasoning/extraction path structured evidence.** Introduce a common layout-to-context adapter for classification, summary extraction, row extraction and general document reasoning. Send ordered blocks, printed column headers, row/cell IDs and copied values; keep full geometry server-side for validation and the viewer rather than spending prompt tokens on every coordinate. Where an adapter has established a column's meaning, include its named role as well as the original heading. Have reasoning select cited IDs and classify meaning; validate IDs against the supplied input. Copy monetary values from selected cells in application code, retaining existing type-specific date, sign and currency rules. Preserve source IDs in result locators. Split table-covered rows from uncovered text so a table in one part of a chunk cannot suppress extraction elsewhere. Chunk by block and complete row, repeat associated headers, and retain section identity. Select summary candidates by relevant labels/sections rather than dropping middle lines blindly. Every omitted candidate or input limit remains a coverage issue. Search consumes a deterministic readable projection of the same blocks, without silently replacing historical evidence or duplicating headers/values.
6. **Show the same evidence to the user.** Render native table and summary values from the cells used by extraction. Label them **From PDF text positions**. Save bounded native page previews in the worker so a cell's Source action highlights its actual text on the rendered page; use the saved page-to-preview transform for crop, rotation, scaling and zoom. An iframe displaying the original PDF alone cannot provide these application-controlled overlays. Retain opening the original PDF and the existing Text view. Highlight separate word boxes for wrapped/discontinuous cells instead of one oversized rectangle that covers unrelated text.
7. **Validate structure and meaning separately, then apply type-specific checks.** Structural validation checks cell membership, source characters, reading order and extraction coverage. Typed validation checks period, amount/quantity/rate distinctions, transaction direction and summary-versus-line roles. Arithmetic passing never proves a column association: uncertain placement, missing coverage or disagreement requires review. PDF text layers can themselves be wrong or misaligned, including layers created by earlier OCR; label the evidence as PDF text positions without claiming independent recognition accuracy. A page with a native header but an image-only body must not pass as complete just because it contains more than 40 characters. Assess native text coverage against rendered regions and route unsupported/image regions through existing vision or review. Retain each source's provenance and deduplicate overlap explicitly; never merge conflicting native/vision values silently. The first release may conservatively flag mixed-content coverage instead of promising automatic detection of every image-based field.
8. **Version and re-read saved PDFs.** Introduce a new PDF parser version and extraction version. Update `PDFResult` compatibility, `ReceiptService` publication/recovery/reuse dispatch and page-preview access; keep v1/v2 reads working explicitly. Existing saved flat text cannot recover coordinates: reread the preserved PDF, then rerun ledger extraction. Retain old runs, source hashes and user corrections. Geometry can be much larger than text, so measure payload growth and bound characters, words, cells and serialized artifacts within the worker's timeout/memory/storage controls; do not silently truncate. No new dependency or source-file modification is required.

#### Document-specific interpretation on shared evidence

| Document | Shared structure used | Interpretation/checks |
|---|---|---|
| Paystub | Earnings/tax/deduction tables and summary boxes | Current versus YTD; Hours/Rate/Amount; employee versus employer contributions; gross/net checks when all components are present. A current-only field does not require a YTD column. |
| Invoice, bill or receipt PDF | Item table, supplier/customer blocks and totals/payment fields | Quantity versus unit price versus extended amount; subtotal/tax/total; full charge versus payments and remaining balance. Record-as correction remains authoritative. |
| Bank/credit-card statement | Account/period summary and transaction tables | Posting versus transaction date; debit versus credit versus running balance; continued descriptions and repeated page headers; balance checks where applicable. |
| Investment statement/confirmation/tax form | Holdings/trades tables and labeled form boxes | Quantity versus unit price versus market value; trade dates; tax box number and printed amount. Reuse existing supported record schemas. |
| Loan/insurance/housing/employment document | Paragraphs, headings, lists, payment schedules and labeled terms | Preserve reading order and clause context; distinguish principal, balance, payment and rate. Only existing supported facts/records are published. |
| Other/unknown PDF | Generic blocks, tables and text | Make evidence readable, searchable and citable without inventing a financial record type. |

#### Accuracy checks before claiming this works

- Extend the synthetic PDF generator to place headers and amounts at independent X/Y positions **without pipe separators**, including deliberately scrambled PDF content-stream order. Existing pipe-delimited fixtures do not test native reconstruction.
- Cover blanks, zeros, identical current/YTD values, reversed column order, Hours/Rate/Amount, stacked/repeated headings, wrapped labels, side-by-side sections, current-only summaries, negative adjustments, multi-page continuation, cropped/rotated pages and duplicate or misaligned text layers.
- Add equivalent invoice quantity/unit/total tests, statement debit/credit/balance tests, form-box association tests, and narrative two-column/list/address layouts that must not become tables. Exercise all supported PDF extraction routes and search text, not just paystub and bill prompts.
- Assert cell contents **and** row/column membership, source character references, summary amounts, visible source overlays and review outcomes. Include incomplete coverage and a mixed native/scanned PDF; digital-only cases must require no vision model.
- Require zero automatically counted wrong-column values on the supported critical cases, report coverage/review rate and latency by document type as well as accuracy, and compare the user's failing layout through a shareable/redacted sample or a user-run evaluation. Passing synthetic tests alone does not establish accuracy on the user's PDFs.

#### Delivery order

1. Implement native geometry capture, the common evidence schema, generic layout reconstruction and compatibility in PDF ingestion for every document type.
2. Connect the common context adapter to classification, reasoning and all existing typed PDF extractors. Implement document-specific column/field roles on that shared interface, with critical paystub, invoice and statement cases as the first acceptance fixtures. Do not ship a paystub-only ingestion branch.
3. Connect table/field display, source highlighting and search projection to that same evidence; complete mixed-page handling and versioned rereads.
4. Run the cross-document regression/accuracy gate and user-run failing-layout evaluation before claiming reliable coverage. No OCR dependency is part of this phase.

Primary implementation files: `documents/pdf_reader.py`, new `documents/pdf_layout.py` and common layout-context helpers, `documents/receipt_schema.py`, `documents/extraction.py`, `documents/reasoning.py`, `documents/receipt_service.py`, the document search projection, `app/static/trace.js`, and PDF/extraction/search/browser tests. Preserve `vision_tables.py` as the historical/model-reported validator; adapt evidence sources into the shared context/viewer interface without relabeling model claims as native geometry.

Reference: the [pypdfium2 text-page API](https://pypdfium2.readthedocs.io/en/stable/python_api.html#text-page) documents character boxes, text/character index differences and the absence of built-in layout analysis. The installed 5.13.0 helper code was also inspected for this design.

### OCR dependency and effort estimate

Tesseract is the smallest local prototype to assess. Its TSV output includes word text, positions and engine confidence; the Windows setup needs the engine executable and language data, not just a Python package. It can be invoked through a bounded subprocess without a Python wrapper. See [installation](https://tesseract-ocr.github.io/tessdoc/Installation.html) and [TSV output](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html#tsv-output).

Rough engineering estimates for one developer, including verification, not measured delivery promises:

| Scope | Effort | Deliverable |
|---|---|---|
| Install/configure the engine and English data on this Windows machine | 1–2 hours | Executable discovery and one local smoke read |
| Bounded OCR adapter prototype | 0.5–1 working day total | TSV parsing, word boxes, timeout/error handling and a few synthetic pages |
| Integrated paystub fallback | 3–5 working days total | Versioned evidence, page/rotation/crop transforms, row/column association, reasoning handoff, review behavior, source highlighting, Windows setup notes and regression checks |

Complex layouts, poor scans or a need to redistribute the engine can extend these estimates. Word boxes alone do not solve table semantics. OCR would provide another text/layout source to compare with vision, with disagreement requiring review. A heavier table engine should be considered only if the small prototype fails on the same cases. No OCR package, executable or language data was installed.

### Implemented: remove the Bill label from a purchase invoice

- The document record now has **Record as → Correct → Purchase / Bill**. It uses the existing correction preview, save, history and Undo flow; the API field is `document_kind`, with values `receipt` and `bill`.
- Purchase removes the financial Bill tag and selects ordinary receipt behavior. Invoice number, printed status, payments and balance remain visible, and items, totals, source evidence and existing payment matches remain stored. This does not mark an unpaid invoice paid.
- The existing counting date is retained when switching to Purchase; **Purchase date** then becomes editable. The preview asks the user to check it. Switching to Bill uses the existing due-date/issue-date counting rule.
- The library folder stays as filed; folder moves remain the existing separate library action. The correction changes the financial record label, not the saved source or original classification history.
- Invalid or empty kinds are rejected. Reapplying corrections restores the user's record kind before applying its other fields, so a later extraction cannot silently reinstate Bill or skip purchase-specific corrections. Family correction validation uses the same kind whitelist.
- Verification: 13 invoice/correction API tests, 16 bill/family ledger regression tests and one browser test passed using synthetic documents (one optional browser test skipped). Coverage includes preview rollback, retained payment matching, removal of the library Bill tag, preserved invoice details, reread protection and Undo. A focused rerun also verified that saved kind and purchase-date corrections are reapplied in the right order. No live paystub accuracy claim is made.

## Implementation record (2026-10-13)

- `src/home_manager/models/vision.py` now requests strict `{full_text, tables}` JSON. The model copies header and row cells with zero-based line indexes; code assigns IDs. The parser version is `receipt-vision-v6-tables`. A malformed response gets one bounded text-only retry. A response with valid full text but an invalid or missing table keeps its transcription and records `vision_table_invalid`.
- `src/home_manager/documents/vision_tables.py` validates line indexes, distinct and ordered row references, rectangular widths, exact nonoverlapping cell substrings, and stable IDs. `ReceiptResult.vision_tables` is version 1; historical results without it remain readable. Model-reported cells have quotes and source line IDs, with no OCR polygon or confidence.
- `src/home_manager/documents/pdf_reader.py` stores tables per scanned page and per grouped image page. Native PDF text creates tables only from explicit pipe-delimited rows with recognizable Current/YTD or item/amount headings. Other embedded layouts remain flat text. PDF and grouped-image parser versions are `pdf-pages-v2-tables` and `receipt-images-v2-tables`.
- `src/home_manager/documents/extraction.py` passes bounded, named table cells and repeated headings to both paystub summary extraction and row classification. The reasoning model classifies the row; code maps copied Current/This period and YTD/Year to date headings and copies money from those cells. Blank or conflicting columns stay null with review notes. Multi-amount flat-text lines without a validated row also require review. The extraction prompt version is `typed-extraction-v20-invoices-tables`.
- Paystub line locators retain each used cell ID, exact quote, and source line ID. Summary citations are replaced with the exact cell quote when money is copied from a cell. The source viewer now offers Image, Text and Tables tabs, with copied headings, explicit blank cells, page labels and source-line links. Text also offers a View extracted tables button. No image boxes are invented.
- Deterministic tests cover the wrong-column case end to end, blank current cells, equal values in both columns, multiple headings and tables, chunk boundaries, invalid table JSON, text-only retry, native and scanned PDF paths, grouped images, historical reading compatibility, reuse, and preservation of an earlier good result. The focused receipt/extraction/reasoning suite passed 65 tests; the table/PDF/group/receipt suite passed 38 tests; the paystub ledger suite passed 19 tests with one optional browser test skipped.

The configured vision model has not yet been tested against these richer requests. No synthetic baseline or private-corpus comparison has been run, and table completeness, placement accuracy, wrong-field value rate, review rate, output length, and latency have not been measured. The release gate in step 4 remains open. No OCR method or dependency was added.

### Follow-up: invoice ingestion and visible paystub tables (2026-10-13)

Implemented after receipts improved but invoices remained confusing and the user could not see paystub tables:

- **Reuse saved text.** Reading loads reconstruct missing tables from explicit pipe separators and recognizable headings, with `origin: "text_separators"`. The viewer and reasoning receive the same validated cells and IDs. This is a derived view: saved transcription text and historical parse JSON remain unchanged, and no additional vision call is made. Existing reported tables take precedence. Separate receipts on one image are not joined. Arbitrary whitespace is never treated as column evidence.
- **Explain absent tables.** The Tables tab distinguishes unread documents, absent table structure, and a rejected table claim. When no reliable structure can be recovered, Text remains available. A rejected vision table can be replaced only by an independently validated reconstruction from explicit separators in its saved transcription; this is still model-transcribed text, not independent image evidence.
- **Complete paystub input.** Both the summary and row requests receive the saved table headings and cells. Summary text plus cells fits the 48 KiB whole-document budget; row chunks retain the 80-line/24 KiB budget including repeated headers. Truncated summary coverage produces a review note. Source-line navigation and existing paystub correction controls remain available.
- **Small invoice adapter.** Keep `bill` as the ingestion and ledger type. Classify supplier invoices for goods or services as bills whether unpaid, partially paid, or paid with zero balance. Quotes, estimates and pro-forma invoices are excluded by the classifier instruction. Distinguish supplier from bill-to customer. Optional cited fields retain invoice number, customer, subtotal, tax, full invoice total, payments/deposits, remaining balance, and printed payment status. Charge lines retain quantity and unit price separately from the extended amount. Bill summaries and rows also receive available table context.
- **Financial validation.** The full invoice total is the purchase amount; payments and deposits are excluded from charge rows. A missing invoice total never falls back to a zero balance as the purchase amount. Check line sums, quantity × unit price, subtotal + tax, and total − payments = balance when the required values are printed. Contradictions and partial payments require review. Invoice metadata is stored in `receipts.invoice_json` by migration 069 and displayed with source links. Invoices remain in the Bills folder; they do not automatically become monthly recurring obligations. A missing due date can use the printed issue date for counting.
- **Payment matching.** Reuse the existing single-payment bill reconciliation only for the full invoice charge. A smaller remaining-balance payment cannot replace the whole invoice. Full-payment synthetic cases count the invoice and matching bank charge once. Partial invoices require review; automatic reconciliation of deposits plus several payments remains future work.
- **Existing documents.** Reopen a document to see saved or reconstructable tables. Run ledger extraction again to use the updated summary/invoice prompts. User-verified or corrected ledger records retain the existing protection against automatic replacement. A new vision read is needed only when saved text has neither usable tables nor explicit separators.

Verification for this follow-up: 63 existing extraction, bill-ledger, PDF, grouped-image, receipt and table tests passed (one optional browser test skipped). The added invoice and table-handoff checks passed 15 tests, including paid/unpaid/partial invoices, a missing full total, a unit-price/line-total mismatch, inconsistent balance, separator reconstruction, bounded summary input, and exact paystub summary citations. The final invoice/reconciliation/correction suite passed 18 tests, including recurring-inference checks through matched payments. Two document-page browser tests passed, covering table rendering, source navigation, paystub corrections, and existing document-page states. These overlapping suites use synthetic data and a scripted model server; live-model accuracy and private-corpus evaluation remain pending.

## Goal and first scope

Make a small reasoning model less likely to put a printed value in the wrong field. First ask the existing vision model for table-shaped JSON as well as document text. Start by evaluating paystubs, especially **Current/This period** versus **Year to date/YTD**. Preserve the source image and the existing reading history. Add coordinate-aware OCR only if structured vision output leaves a measured gap.

Success means the app can say which reported table cell supplied each paystub amount, reject an amount cited from a different reported column, and send uncertain cells to review. A model-reported cell is still unverified image evidence; it must never be described as an independently located image region.

## Previous behavior and failure

- `src/home_manager/documents/receipt_worker.py` orients an image, creates `preview.png`, and optionally crops separate pieces of paper. Before this phase, `src/home_manager/models/vision.py` requested strict JSON with only `full_text`. The prompt asked for table rows separated by `|`, then the app split the answer into `TextLine` objects without cells or coordinates.
- `src/home_manager/documents/pdf_reader.py` uses `get_text_bounded()` for a PDF text layer and vision transcription for near-empty pages. Before this phase, both became flat lines. The near-empty check remains a character-count/replacement-character heuristic, not a table-layout check.
- Without validated tables, `src/home_manager/documents/extraction.py` checks exact line quotes and whether an amount appears somewhere on the cited line. That cannot establish its column. The legacy flat-text test, `tests/test_extraction.py::test_paystub_line_without_amount_evidence_is_left_blank_for_review`, demonstrates the old wrong-column risk; the new structured end-to-end test verifies correction from the Current cell.
- `ReceiptResult` already has legacy OCR `TextBlock` geometry. Its current vision invariant requires `blocks=[]` and `ocr_text=""`. Structured vision tables must be saved separately from verified pixel geometry.

## First contract: structured vision reading (implemented)

The vision schema now requests `full_text` and `tables` (`[]` when no ordinary table is clear). A full-text-only response remains readable with a table issue. The task is **transcription**, not financial interpretation: the model copies text, visible header cells, blank cells, and row cells in visual order. It does not decide gross pay, net pay, expense categories, or which column the app calls `current`.

For an initial paystub, ask for a structure like this (IDs are assigned by code after validation):

```json
{
  "full_text": "Description | This period | Year to date\nRegular pay | 2000.00 | 52000.00",
  "tables": [{
    "header_rows": [{"line_index": 0, "cells": ["Description", "This period", "Year to date"]}],
    "rows": [{"line_index": 1, "cells": ["Regular pay", "2000.00", "52000.00"]}]
  }]
}
```

Use zero-based indexes into the line breaks preserved by `full_text` (`split("\n")` in code). Require every nonblank cell to be an exact substring of its named line, in the same left-to-right order with nonoverlapping spans. Require the row width to match its header for ordinary rectangular tables, keep empty cells explicit as `""`, and reject duplicate, out-of-order, or nonexistent line references. Multiple header rows and tables are allowed; an unsupported merged-cell layout remains uncertain. Validate that `full_text` is nonblank and the response was not truncated. A failed table check discards the table structure and leaves the text available with an issue; it never silently repairs a number.

This is stored as a versioned `vision_tables` field in `ReceiptResult`/PDF page evidence. Historical results remain readable. The model-generated `full_text` remains the canonical transcription for search and existing citations. Code assigns stable table, row, and cell IDs only to validated structures, with each cell pointing to its source line and exact quote. OCR `TextBlock` polygons and confidence remain empty for model-reported cells: structured JSON constrains the *shape* of the answer, not its fidelity to image pixels.

Code maps `This period`/`Current` and `Year to date`/`YTD` from the copied headings. The reasoning model receives named cells and stable IDs, while code copies each numeric value from its cell. Unknown, conflicting, or absent headers leave the relevant column ambiguous and require review. This checks internal column consistency; it cannot prove the vision model read the visual table correctly.

## Later contract if spatial evidence is needed

If evaluation shows structured vision still misplaces cells, add local OCR word boxes or native-PDF character boxes as a separate, versioned `layout` evidence source. For images use oriented-preview pixel coordinates, adding crop offsets for regions; for PDF text retain page coordinates and an explicit view transform. Validate bounds, membership, text and engine provenance. Never attach an OCR box to a vision-only word by assumption, and never treat raw OCR confidence as the probability that a financial field is correct.

## Delivery steps

### 1. Baseline and structured-output prototype

Status: the structured-output request and deterministic prototype are implemented. The expanded synthetic image set, saved baseline, configured local-server check, output-limit measurement, and one-call latency comparison remain to do.

- Add synthetic paystub images with current/YTD, a blank current cell, repeated equal amounts, close values, wrapped labels, totals, multi-level headings, shifted columns, skew/blur, and a second table. Include a native PDF and a scanned PDF variant. Record transcription error separately from row/column placement error.
- Run the existing end-to-end synthetic suite and save a baseline summary. Do not inspect `P:\Finances`, `%LOCALAPPDATA%\HomeManager`, or `P:\EvalCorpus` with an agent. The user can run the private corpus suite later and share only its allowlisted `summary.json`.
- Prototype the expanded JSON schema in `src/home_manager/models/vision.py` with the configured local vision model. Check whether its server enforces arrays/nested objects while accepting image input, whether a full page still fits the 8,192-token output limit, and whether the extra structure improves paystub placement. Measure one structured vision call against the current one-call text baseline. No new OCR dependency is needed for this phase.

### 2. Persist and validate the vision tables

Status: implemented for images, scanned PDF pages, grouped images, and explicit pipe-delimited native PDF rows. Native PDF layouts without reliable separators remain flat text. A malformed overall response gets one bounded text-only retry; a valid transcription with invalid table cells keeps its text and discards those tables without another model call.

- Add a versioned `vision_tables` field to `src/home_manager/documents/receipt_schema.py` and PDF page evidence. Preserve legacy result loading, grouped-image pages, region ordering, full text, line IDs, and source hashes. Bump the parser/prompt version and reuse key so old and new readings cannot be confused.
- Validate table headers, rows, cell count, line indexes, exact quotes, and cell order before publication. For malformed overall JSON, retry once with the text-only schema. For invalid table cells with valid full text, discard the table and record the issue. The model client can also retry a rejected schema request with schema instructions in the prompt. Do not replace a previously good reading with a partial result. Keep model output out of private logs and error text.
- For native PDFs, first build equivalent rows/cells from the embedded text layer when its row order is clear. Scanned pages use structured vision. If a PDF table cannot be reconstructed faithfully, keep the flat text and a review issue; character-box extraction belongs to the later spatial phase.

### 3. Use cells in paystub extraction

Status: implemented and active for paystubs with validated tables, including reconstructable saved readings. There is no opt-in toggle. Invoice/bill requests also receive table context through their existing extraction path. The source viewer renders tables and resolves cells to their lines and quotes, with no image geometry.

- After classification, use validated tables for paystub summaries and rows. Repeat their header with each bounded chunk so the 80-line/24 KiB limit cannot detach amounts from their column names. Send the small model row IDs, labels, and cells; have it classify earning/deduction/tax group and category. Copy `current` and `ytd` amounts from the mapped cells in code.
- Extend evidence locators and the source viewer so a cell citation resolves to its exact text and source line. A model-reported cell may highlight its line but must not show a made-up image box. Existing line citations continue to work.
- Reject a wrong-column amount even when the number occurs elsewhere on the same row. If a reported row has conflicting headings or an empty cell, set the affected value to null with a review reason. Without a validated row, retain flat-text extraction but null amounts from ambiguous multi-number lines for review. Keep paystub arithmetic as an independent check.

### 4. Evaluate and decide whether OCR is justified

Status: the deterministic tests listed in the implementation record pass. More fixtures are needed for wrapped labels, shifted columns, skew/blur, totals mistaken for lines, and measured table completeness. Live-model placement accuracy, synthetic and private-corpus comparisons, evaluation counters, and the release gate remain open. Do not start the OCR branch unless table results expose a measured gap.

- Add deterministic tests for the known wrong-column case, equal values in both columns, a missing current cell, totals mistaken for lines, inconsistent JSON/full text, table header separated by a chunk boundary, PDF pages, grouped images, invalid model output, cancellation, restart/reuse, historical readings, and preservation of verified ledger records. The known case must reject `current=52000.00` when that value is only in the YTD cell.
- Add evaluation counters for table completeness, row/cell placement, wrong-field money values, missing values, review rate, output length, and latency. Compare with the saved baseline by source and document type. The release gate is **zero wrong-column values automatically counted on critical paystub cases**, no regression in the existing critical-money gate, and an explicit report of coverage and latency. Synthetic success is followed by the user's private-corpus run before default enablement.
- If structured vision still confuses columns or cannot anchor cells to source text, prototype local OCR word boxes on the same cases. Compare Tesseract TSV first; assess a table-aware option such as PaddleOCR PP-StructureV3 only if basic geometry fails. Measure Windows setup, resource use, character accuracy, cell accuracy, and latency before pinning a dependency. Native PDFs can use `pypdfium2` character boxes. Keep all processing local, bounded, and versioned.
- The current stage copies amounts from cells for paystubs with saved or reconstructable tables; it has no opt-in switch. Invoice/bill requests receive table context and invoice-specific arithmetic validation, while their amounts still come from cited model fields. Extend deterministic cell-to-field mapping to those documents only where column semantics are defined and evaluated.

## Files and work products

- Reading and evidence implemented: `src/home_manager/models/vision.py`, `src/home_manager/documents/vision_tables.py`, `receipt_schema.py`, `pdf_reader.py`, and `receipt_service.py`. A local OCR/layout adapter remains conditional on evaluation.
- Extraction and display implemented: `src/home_manager/documents/extraction.py`, `src/home_manager/finance/ledger.py`, and the paystub source display in `src/home_manager/app/static/receipt.js`.
- Verification implemented: `tests/test_vision_tables.py`, `tests/test_extraction.py`, `tests/test_vision_batch.py`, `tests/test_pdf.py`, `tests/test_document_groups.py`, `tests/test_receipts.py`, and `tests/test_bills_ledger.py`. Expanded synthetic cases and placement graders under `evals/` remain to do.
- Built behavior is described in `docs/documents.md`, `docs/money.md`, and `docs/evals.md`; remaining evaluation work is listed in `docs/open-work.md`. Update `evals/README.md` when the new measurements are available.

## Decisions to make from the prototype

1. Does the configured local vision model reliably produce the richer strict JSON schema within the output limit? If not, keep the existing full-text read and run a focused second vision call for tables only on classified paystubs.
2. Does structured vision reduce wrong-field values enough without increasing missed text or review? Which table patterns remain unreliable?
3. If spatial evidence is needed, does basic OCR word geometry recover those patterns, or is a dedicated table detector justified? Set usability thresholds from observed errors and missed values, not a raw OCR confidence number alone.

The target release rule is that a paystub amount in a multi-column table needs a cited source cell and a validated reported column association before it can be counted automatically. The implementation now copies from cells where validated tables exist and sends ambiguous multi-amount flat lines to review; legacy and clear single-amount flat-text paths remain. Confirm that this coverage satisfies the release gate during evaluation. Structured vision improves the information passed to the small model, but an independent spatial/text source could only corroborate its image placement; human review resolves remaining disagreement.

## Reference capabilities

- LM Studio supports JSON-schema responses through its OpenAI-compatible chat-completions API: <https://beta.lmstudio.ai/docs/developer/openai-compat/structured-output>.
- Tesseract TSV supplies text, word boxes, and raw confidence: <https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html#tsv-output>.
- PaddleOCR PP-StructureV3 exposes table cell boxes and recognized cell text: <https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/pipeline_usage/PP-StructureV3.en.md>.
- `pypdfium2` exposes PDF character boxes, while leaving layout analysis to the application: <https://pypdfium2.readthedocs.io/en/stable/python_api.html>.
