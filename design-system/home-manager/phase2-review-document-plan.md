# Redesign: To check (#/review) and the document page (#/documents/ID) (phase 2)

First step for the implementer: save this hand-off as `design-system/home-manager/phase2-review-document-plan.md`, and
write `design-system/home-manager/pages/review.md` and `pages/document.md` from "Design-system references", "Layout"
and "States". Plan mode couldn't write them. Use the `ui-redesign` skill (§5 implementation rules, §6 verification).

**Two builds from this one plan, each verified and committed on its own (when the user asks):**
- **Build A:** backend (correction preview, history, undo, record view additions), the three `trace.js`
  components, and the document page v2.
- **Build B:** To check v2, which reuses `sourceViewer` and `confirmCorrect`.

## Context
This is the third Phase 2 screen pair (docs/open-work.md "UI redesign" 6). It also builds the remaining components in
docs/ui.md "Observability components" (`confirmCorrect`, `sourceViewer`, `historyList`) and plans the
correction-preview endpoint.

**What the user comes to do:**
- **To check:** decide each item the app isn't sure of. That means confirming a match or record, or rejecting or
  correcting it, with the evidence in view.
- **The document page:** check a record against its source, correct what the model got wrong, and see what changed and
  who changed it.

**What's wrong today** (before shots, the 2026-09-30 review and the code map):
- **To check:**
  - The evidence is a small thumbnail (images only), not the source beside the record (rule 2).
  - The *why* repeats the title ("Does this receipt match this charge? Does this receipt match…").
  - Nothing is in the URL (rule 5).
  - "Receipts with no matching charge" is a separate full-width card below.
  - There's no Correct; only Confirm or Reject.
  - Warranty, tax-table, tax-tag and item kinds have no source shown.
- **Document page:**
  - Read and Extract sit in a footer below both panes (below the fold, open-work "UI" findings).
  - The vocabulary is mixed: Count it anyway, Reject, Not right?, Extract to ledger.
  - Corrections are a whole-record form with no reason, no preview and no history.
  - Nothing shows provenance or a traced figure.
  - Details (hashes, managed paths) take the main scroll.

**User decisions (2026-10-10, this session):**
- **To check: three columns at 1440.** Queue (260px) | the source viewer | the item, with a decision bar pinned at the
  bottom of its column.
- **Document page: a sticky record header plus tabs.** The right pane's header holds the title, status, the Read →
  Recorded steps with the one next action, and the decision (Confirm / Reject / Correct…). Under it are the tabs
  Record · History · Details. Re-run actions move to the ⋯ menu.
- **One plan, two builds** (A, then B).
- **Correct covers** receipts, bills, pay stubs (`income_record`), statements and statement transaction rows. It
  doesn't cover investments, which wait for the Wealth screens.

**Carried rules:**
- One action vocabulary on v2: **Confirm, Reject, Correct**.
- v1 stays until Phase 3 cleanup, apart from small refactors that don't change behaviour (listed below).

## Before screenshots
In `<scratchpad>/before-review/`, look at:
- `review-1440-light.png`: queue and detail; the thumbnail is missing because the item has no image.
- `review-390-light.png`: the decision buttons are below the fold.
- `documents_1-1440-light.png`: an unread CSV. Read/Extract are in the footer, and Details fill the page.

The default seed has no read receipt, no needs-review record with lines, and no statement with rows. Build A adds the
seeding in "Seeding" before the after shots. Retake the before shots with the new seed on v1 (`--v2` empty) so they
compare like for like.

## Design-system references
- **MASTER.md "Layout"**, breakdown and detail panel: a 360px panel on the right at ≥1180, a float at 900–1179, a
  bottom sheet below 900. To check's right column must leave room: when the breakdown opens beside To check at ≥1180,
  the item column narrows to `minmax(320px,360px)`.
- **MASTER.md "Components":**
  - **Source text:** mono 11.5px on `--surface-sunken`, scrolling in its own box; the highlighted line is
    `--warning-subtle` with a 1px `--warning` outline.
  - **Needs-attention row:** for the *why* when it has issues (`--warning-subtle`, a 20px warning icon, a semibold
    *what*, a muted *why*).
  - **Buttons:** one primary per region (Confirm). Correct… is secondary; Reject is secondary (not destructive red,
    since it's reversible with Undo).
  - **Status badge** through `statusBadge()`; verified rows show no badge.
  - **Tinted region:** for the evidence cards, never nested. Cards inside the item column are dividers within one
    region, not boxes in a box.
- **MASTER.md "Typography":** h1 `--text-xl`; record title `--text-lg`; field labels `--text-xs` secondary; values
  `--text-sm`; amounts tabular.
- **Deviations:**
  - The evidence cards in To check (Charge | Receipt) stay two side-by-side bordered blocks inside the item column.
    This is the one allowed nesting, because comparing two records needs the pairing. They use `--radius-md`, a
    `--border` outline and no fill.
  - Reject on v2 is secondary, not `danger`. It's reversible (Undo 8s), and rule 4's "ask first" applies to
    irreversible actions only.

## Tokens
Existing tokens only, with no new tokens or hex values:
- `--canvas`, `--surface`, `--surface-sunken`, `--border`, `--border-strong`, `--paper` (behind document images)
- `--text`, `--text-secondary`, `--text-muted`
- `--accent`, `--accent-subtle`, `--on-accent`
- `--warning`, `--warning-subtle`, `--positive`, `--positive-subtle`, `--danger` (errors only)
- `--radius-sm/md/lg`, `--space-1..8`, `--text-xs..xl`, `--shadow-overlay` (only the fixed bar under 900)

Every pair is already checked in MASTER.md "Color tokens": warning/warning-subtle 5.2 and 7.8; muted/sunken 4.6 and
5.1; secondary/sunken 6.3 and 7.7; accent/accent-subtle 5.1. Check the new pair `--text` on `--warning-subtle` (the
selected source line) in light and dark, and record it in MASTER.md. It's expected ≥ 12:1.

## Backend (Build A, additive; no migration)
`record_corrections` already has `reason`, `actor` and `transaction` rows (migration 061), and `review_events` has
`actor`. Verify both with Grep before relying on them.

### 1a. Correction preview: `POST /api/finance/records/{type}/{id}/correction-preview`
- **Request:** the `CorrectionInput` the PATCH takes (`app/api.py:410`), with `reason` ignored. `?member=` returns 400
  ("The preview isn't available for family records.").
- **Response:**
```jsonc
{"record_type":"receipt","record_id":12,
 "changes":[{"field":"purchase_date","label":"Purchase date","kind":"date","from":"2026-09-28","to":"2026-10-02"}],
 "figures":[{"ref":"spending.net?…","label":"Spending in September 2026",
             "before":{/*figure*/},"after":{/*money()*/},"difference":{/*money(), signed*/},"changed":true}],
 "unchanged_count":2,
 "matching":{"before":[{"kind":"receipt","counterpart":{/*summary*/}}],"after":[],"changed":true},
 "review":{"before":"needs_review","after":"verified","automatic":true},
 "issues":{"resolved":["…"],"remaining":[]},
 "notes":["Taxes for 2026 are worked out again from your pay stubs."]}
```
- **New module `src/home_manager/finance/correction_preview.py`:**
  - On one connection: `BEGIN IMMEDIATE`, then wrap it in `SnapshotStore(store, db)` (`finance/dashboard.py:17`), then
    gather the before state and refs.
  - `SAVEPOINT`, then apply the same code the PATCH runs: `Ledger(snap).correct(...)` or `correct_transaction(...)`,
    then `Reconciler(snap).run("correction")`, as `Manager.correct_record` does.
  - Gather the after state and refs. Compute the after values over the union of refs with `traces.build_for(snap, ref)`;
    a `ValueError` gives `None`.
  - `ROLLBACK TO` the savepoint, compute the before values, then `rollback()` in a `finally`.
  - Never call `trace()`/`remember()`, because they write `figure_snapshots`.
- **Refs by record type** (`_refs`, `tools.last_day` for month ends):
  - **receipt:** for each of the purchase month and the linked charges' months, `spending.net` and `cashflow.net`; for
    each split category in those months, `spending.category`; plus `split.receipt` and the linked charges'
    `split.charge`.
  - **transaction:** the month's `spending.net`, `cashflow.net`, `cashflow.in` and `spending.category`, plus
    `split.charge` when linked.
  - **statement:** `account.balance`, and `worth.today` with `figure=cash` and `figure=net_worth` (Today's refs).
  - **bill:** no figures, with the note "Bills don't change any totals; the due date moves on Bills and Today."
  - **income_record:** no figures, with the tax note above.
  - `_label()` gives plain labels: "Spending in September 2026", "Groceries in September 2026", "Cash flow in …",
    "This receipt by category", "{account} balance", "Cash across accounts", "Net worth".
- **Wiring:** `Manager.preview_correction()` runs under `self.mutex` with `self.require(False)`, like
  `correct_record`. The route sits beside the PATCH (`app/api.py:1235`), and a `ValueError` gives 400 with the same
  message the PATCH gives.
- **Watch for:** `SnapshotStore.__getattr__` passes other store methods through, and any that open their own connection
  would escape the transaction or deadlock. A `with db:` inside the correction path would commit early. The
  "nothing persists" and timing tests catch both. Fix any found by passing the connection through, never by dropping
  the rollback.

### 1b. History: `GET /api/finance/records/{type}/{id}/history`
- Newest first by `(created_at, id)`. Entries have three kinds:
  - `correction`: `id, at, who, field, label, value_kind, from, to, reason, resolved_issues, undoable, row` (`row` is
    `{type,id,label}` for a statement's transaction rows);
  - `review`: `at, who, automatic, from_status, to_status, note`;
  - `family`: corrections received from the family.
- `Ledger.history(type, id)` reads `record_corrections` (for a statement, also its transactions), `review_events`
  (without `bill_payment`) and received `family_corrections`.
  - Field labels come from `CORRECTABLE`, plus a new `TRANSACTION_LABELS`.
  - Money fields use `format_minor`.
  - Add the `AUTO_VERIFIED_NOTE` constant to `ledger.py` and use it in `correct()`. An event with that note and no
    actor is `automatic: true`.
  - `undoable` means the correction is the latest for its field.

### 1c. Undo a correction: `POST /api/finance/records/{type}/{id}/corrections/undo`
- `{"ids":[…]}` → `{"record":…, "reconciliation":…}`.
- First refactor `Ledger.correct`'s body into `_apply_correction(db, type, id, changes, reason) -> ids`.
- `undo_corrections`:
  - refuses with "It was changed again since; correct it instead." when a later correction exists;
  - otherwise re-applies each `previous` with the reason "Undid a change" and restores `resolved_issues_json` into the
    validation issues;
  - if the correction auto-verified the record and it's still automatic-verified, sets it back to `needs_review` with
    an "Undid a correction" review event.
- The PATCH response gains `correction_ids` (additive).

### 1d. Record view additions to `GET /api/finance/records/{type}/{id}` (additive)
- **`correctable`** (always): `[{field,label,kind,value,shown_as,options?}]`, from `CORRECTABLE` and
  `TRANSACTION_CORRECTABLE`. `value` is the text form a correction takes. `shown_as` maps `provider` and `payer` to the
  merchant row. `options` cover category, sale type, direction and transaction type.
- **`?figures=1`** (opt-in, through `Manager.record_view`):
  - receipt: `figures.split` from `split.receipt`, labelled "Counts as"; `figures.counts_in[]`, the
    `spending.category` figure for each split category in the purchase month;
  - statement: `figures.balance` (`account.balance`) when it's the account's latest statement.

### 1e. For Build B
`household/items.py _line` also selects `r.document_id`, and `resolutions()` adds `line_ids` from
`Ledger.evidence("receipt_item", id)`.

## Components (Build A, in `trace.js` after `ruleCard`)
Each component has a module counter for unique ids and never reuses v1 ids. Reuse `element()`, `amount()`,
`dateText()`, `statusBadge()`, `emptyState()`, `alertBox()`, `toast()`, `categoryLabel()` and `icon()`.

### `loadReading(documentId, digest)` → `{doc, run, result}`
`GET /api/documents/{id}`, then `/receipt-runs?blob_hash=`, then the newest `/api/receipt-runs/{id}`. `result` is
`null` when the document is unread. It caches in a Map with `clearReadings()`.

### `sourceViewer(doc, reading, {runId, digest})` → `{el, highlight(ids), onRegionClick(cb), update(reading, runId), showDocument(id), destroy()}`
- **DOM:** `section.source-viewer[aria-label="Source document"]` holds:
  - `.sv-toolbar`: a tablist `.sv-tabs` (Image | Text, ids `sv{n}-image-tab`/`sv{n}-text-tab`), a `.sv-page` select
    (PDF pages, hidden otherwise) and the badge "Original preserved";
  - `.sv-panel.sv-image`: `.sv-alert`, `iframe.sv-pdf[hidden]`, and `.sv-scroll > .sv-frame > img.sv-img` +
    `svg.sv-overlay`, then `p.sv-hint`;
  - `.sv-panel.sv-text[hidden]`: `ol.sv-lines > li.sv-line[data-line-id][tabindex=-1]` and `button.sv-copy` "Copy
    text";
  - `details.sv-extras` "Reading notes & codes" (issues and QR/barcode cards).
- **Behaviour:** copy v1's `highlightEvidence`, `renderReceipt` and `showCitingRows` (`receipt.js:259–338`), but
  reading from its arguments, not the global `receipt`.
  - The image comes through the bearer fetch into a blob URL. A PDF gets a fresh iframe each time (v1 `showPdf`).
  - `highlight()`: a vision or PDF reading without `code-` ids goes to the Text tab, marks `.sv-line.selected` and
    scrolls the first into view inside `.sv-lines`. Otherwise it goes to the Image tab and toggles `.selected` on the
    polygons for the lines' `block_ids` (and marks the lines too).
  - A polygon click, or Enter on a line, calls `cb({blockId, lineIds})`.
  - Text read from documents is always `textContent`; links stay text.
- **Keyboard:** the tabs have arrow keys. `.sv-lines` is a roving list (one `tabindex=0`, ↑/↓ move, Enter selects).
  Polygons are mouse-only, since the list is their keyboard equivalent.
- **CSS:**
  - `.sv-scroll` and `.sv-lines` have `overflow:auto` and fill their column.
  - `.sv-frame` is on `--paper`.
  - `.sv-line` is mono 11.5px on `--surface-sunken` with padding 2/8.
  - `.sv-line.selected` and `.sv-overlay .selected` are `--warning-subtle` with a 1px `--warning` outline.
  - The polygon styles are v1's `#receipt-overlay` rules under the new class.

### `confirmCorrect(opts)` → `{el, confirmButton, rejectButton, correctButton, openCorrect(field), close()}`
- **Options:** `{recordType, recordId, reviewStatus, reviewSource, correctable, reviewPath, confirmBody,
  rejectBody, undoBody, labels, onChange, preview=true, member}`. `reviewPath` defaults to
  `/api/finance/records/{t}/{id}/review`, the endpoint Review V uses.
- **DOM:** `div.confirm-correct` holds:
  - `div.cc-actions[role=group][aria-label="Decision"]`;
  - `p.cc-state`;
  - `form.cc-form[hidden]` (`cc{n}-form`), with one `div.field` per correctable field (date / text with maxlength /
    select / amount as text), a "Why (optional)" input (maxlength 500, hint "Kept with the change."),
    `div.cc-preview[role=status][aria-live=polite]`, `p.error-text[role=alert]`, and Save (primary) and Cancel.
- **States:**
  - needs_review or proposed: **Confirm** (primary), Reject and Correct….
  - verified by a person: "Verified", Undo verification and Correct….
  - checked automatically: "Checked automatically", "Not right? Reject" and Correct….
  - rejected: "Rejected" and Undo rejection.
  - Correct… appears only with `correctable.length`, and has `aria-expanded` and `aria-controls`.
- **Confirm/Reject:** POST, then an 8s Undo toast, then `onChange`. A failure is an inline `alertBox` in `.cc-state`,
  and the item doesn't advance.
- **Correct:**
  - The preview runs on input, debounced 450ms, with a sequence number to drop late answers. "Working out what
    changes …" shows after 300ms.
  - Preview rows are `ul.cc-preview-list > li.cc-preview-row`: label | `figure(before,{size:"inline"})` | → (sr-only
    "becomes") | plain `amount(after)` | `span.cc-delta`. "After" is never a `figure()`, because its ref would open
    today's breakdown, not the corrected one.
  - Then come "N other totals stay the same.", the matching line, the review line ("It will count automatically: every
    check passes.") and the notes.
  - A 400 is a field error and disables Save. Other failures show "Couldn't work out the preview" and leave Save
    enabled.
  - Save sends a PATCH `{changes, reason}`, then the toast "Saved. {k} totals changed." with an 8s Undo
    (`/corrections/undo`).
  - Esc in the form cancels it with `preventDefault()`, so the page stays. `preview:false` skips the preview (family).

### `loadHistory(type, id)` and `historyList(entries, {field, empty})`
- `ol.history-list > li.history-row[data-kind]` holds:
  - `time.history-when`;
  - `span.history-who` (the person, "Automatic check" or "Home Manager");
  - `p.history-what`: a correction is "Purchase date: `span.history-from` → `span.history-to`" (dates through
    `dateText`, categories through `categoryLabel`, "empty" for null), with a row prefix for statement rows; a review
    is `statusBadge(from)` → `statusBadge(to)`;
  - `p.history-why.muted`.
- The empty state is "No changes yet. Corrections and review decisions appear here."

## Layout

### Document page v2 at 1440×900
```
← Documents
Fresh Market (h1, set once)                                   [state badge] [⋯ #doc2-menu]
Receipt · Oct 4, 2026 · fresh-market.png
[earlier-version banner, when shown]
┌#doc2-source (45fr, sticky, own scroll)┐ ┌#doc2-record (55fr)───────────────────────────┐
│ [page chips #doc2-group]             │ │ #doc2-header (sticky top:0, --surface)       │
│ [Image] [Text]   Page[1▾]  Original  │ │  Receipt from Fresh Market   [Needs review]   │
│ ┌──────────────────────────────────┐ │ │  ol#doc2-steps  Read ✓ → Recorded ⚠           │
│ │ receipt image on --paper,        │ │ │  #doc2-why  ⚠ Total differs from the items    │ ← DECISION
│ │ cited regions lit                │ │ │  #doc2-decision [Confirm] [Reject] Correct…   │   REGION, in
│ │                                  │ │ │  (Correct form opens here, preview below it)  │   view at
│ └──────────────────────────────────┘ │ ├──[Record] [History] [Details]─────────────────┤   1366×768
│ Select a highlighted region to find… │ │ Merchant   Fresh Market   ✎Changed  Find Correct│
│ ▸ Reading notes & codes              │ │ Date       Oct 4, 2026              Find Correct│
└──────────────────────────────────────┘ │ Category   [groceries] [household]  Find Correct│
                                         │ Counts as  98.75 USD (figure)                  │
                                         │ Counts in  Groceries · Oct  412.30 USD (figure)│
                                         │ Items (3)  table, Find per row                 │
                                         │ Matched charge · Rewards · Tax · Checks ▸      │
                                         └────────────────────────────────────────────────┘
```
- **Grid:** `.doc2-body { grid-template-columns: minmax(0,45fr) minmax(0,55fr); gap: var(--space-5) }`. The source
  column is `position:sticky; top: var(--space-5); max-height: calc(100vh - 2*var(--space-5))`, and its `.sv-scroll` /
  `.sv-lines` scroll inside it.
- **Header:** `#doc2-header` is sticky inside the record column with a `--border` bottom.
- **900–1179:** columns 40/60, and the breakdown floats as already built.
- **Under 900:** one column (header, source with max-height 60vh, tabs). `#doc2-decision` gets `.doc2-pinned`
  (`position:fixed; bottom:0; left:0; right:0`, `--surface`, top `--border`, `--shadow-overlay`, z-index 20, below the
  breakdown's 30). `main` gets bottom padding the same height. At 390 the h1 wraps; the subtitle truncates with
  ellipsis.
- **The decision region stays in view:** the header is sticky and comes first in the record column, so Confirm sits at
  y < 400 at 1366×768 even with issues. The Correct form opens inside the header. Its preview list is capped at
  `max-height: 40vh` with its own scroll, so Save stays visible.

### To check v2 at 1440×900
```
To check                                                [Reconcile now] [Refresh]
3 items need you · checked 3:31 PM
┌#review2-queue 260┐┌#review2-source (1fr)────────┐┌#review2-item (340–400)─────────┐
│Questions (1)     ││ sourceViewer of the item's  ││ 3 of 12                         │
│ Fresh Market …   ││ document, evidence lines lit││ Does this receipt match?  (h2)  │
│Proposed matches 2││                             ││ Same amount · 2 days apart ·    │
│▸Hardware Depot … ││                             ││ merchant matches (why)          │
│Records to verify ││                             ││ ┌Charge────┐┌Receipt────┐       │
│ Receipt: Fresh … ││                             ││ │−63.42    ││63.42      │       │
│Images like one 1 ││                             ││ └──────────┘└───────────┘       │
│No matching charge││                             ││ [Correct form slot]             │
│ Maple Street …   ││                             │├#review2-bar────────────────────┤ ← DECISION BAR
│ 2 failed·1 unfiled│└─────────────────────────────┘│[Confirm match V][Not a match R] │   pinned, in view
└──────────────────┘                               │Correct…           Open document │   at 1366×768
                                                   └─────────────────────────────────┘
```
- **Grid:** `.review2-layout { grid-template-columns: 260px minmax(0,1fr) minmax(340px,400px); gap: var(--space-4) }`.
- **Columns:** each is sticky with `max-height: calc(100vh - var(--review2-top))`, where `--review2-top` is a
  `.review2-layout` custom property (the header's height, set in CSS: 140px at ≥820, 120px under). Each scrolls inside
  itself. The item column is a flex column: head, `.review2-scroll` (flex 1, overflow auto) and `#review2-bar` (flex
  none, top `--border`).
- **Queue:** group titles are `--text-xs` semibold secondary with a count pill. Entries are 36px rows, and the selected
  one is `--accent-subtle` with an `--accent` left bar 3px and `aria-current="true"`.
- **Under 1180:** the queue becomes `#review2-picker` (a select with an optgroup per group) plus `#review2-prev` /
  `#review2-next`, above two columns `minmax(0,1fr) minmax(320px,380px)`.
- **Under 900:** one column (picker, item, source at 60vh). `#review2-bar` is fixed to the viewport bottom, the same
  as `.doc2-pinned`.
- **390:** the picker is full width; the bar's buttons wrap to two lines (Confirm and Reject on the first, Correct… and
  Open on the second).

## Changes by file

### Build A
- **`finance/correction_preview.py`** (new), **`finance/ledger.py`** (`_apply_correction`, `history`,
  `undo_corrections`, `correctable` in `record`, `AUTO_VERIFIED_NOTE`, `TRANSACTION_LABELS`) and **`manager.py`**
  (`preview_correction`, `undo_corrections`, `record_view(figures=)`, `correct_record` returns ids).
- **`app/api.py`:**
  - three routes beside line 1235, and `figures` on the record GET;
  - `document_v2.js` added to the `STATIC` allowlist (about line 64).
- **`trace.js`:** the components above.
- **`receipt.js`:** refactors only, whose defaults keep v1 identical:
  - `sourceButton(lineIds, find = highlightEvidence)`;
  - `ledgerRows(record, categories, onSaved, find)`;
  - `rewardsList(rewards, find)`;
  - `paystubRow(…, find)` and `paystubBreakdown(record, find)`;
  - `segmentLines(segment, lines = receipt?.result?.lines)`.
- **`document_v2.js`** (new, loaded after `receipt.js`, `library.js`, `taxes.js` and `trace.js`, before `shell.js`;
  the script tag goes after `taxes_v2.js`):
  - **Registration:** `V2_SCREENS.document = {title: "Document", show: route => openDocumentV2(route.id,
    route.params)}`. `parseRoute` already names `#/documents/ID` `document`. `show` first calls `closeReceipt()`, so
    v1's polling sees no state. The Settings checkbox label is "Document page".
  - **State:** `doc2 = {doc, digest, runId, run, result, extraction, record, type, segment, viewer, cc, tab}`, with
    `doc2 !== state` guards.
  - **Copied from `receipt.js`:** `openReceipt`, `receiptHistory`, `displayReceiptRun`, `startReceipt`,
    `loadExtraction`, `renderRecordPane` (which becomes `#doc2-steps` + `#doc2-next`), `loadGroupPages`,
    `changeGroup` and `renderSplit`. They're copied because they touch v1 ids or the global `receipt`.
  - **Reused from `receipt.js`:** `RECORD_FIELDS`, `ledgerTitle`, `directionText`, `decisionPanel`,
    `itemCategorySelect`, `receiptCategories`, `runTelemetry`, `copyButton`, `detailRow`, `sourcePath`, the state
    maps, and `renderAssetRecord`/`renderInvestmentRecord`/`renderConfirmationRecord`/`renderTaxFormRecord`.
  - **Reused from elsewhere:** `documentName`, `folderLabel`, `documentStateBadge`, `openDescription`,
    `openLibraryAction` and `restoreDocuments` from `library.js`; `showVersions` from `app.js`; `taxReceiptSection`
    from `taxes.js`.
  - **Record tab:**
    - `dl.doc2-fields` from `RECORD_FIELDS[type]`. Each row has its value, a `provenanceBadge({kind:"override"…})`
      when corrected, **Find** (lazy `/api/provenance/{type}/{id}?field=` → `viewer.highlight`) and **Correct**
      (`cc.openCorrect(field)`).
    - Every category as a `category-tag`, largest first (rule 3).
    - "Counts as" `figure(figures.split)` and "Counts in" rows of `figure(…, {size:"inline"})`.
    - `ledgerRows(..., ids => viewer.highlight(ids))`; statement rows get a per-row Correct (a row
      `confirmCorrect` for `transaction`).
    - "Matched charge" from `record.links`, `rewardsList`, the pay stub breakdown and withholding,
      `taxReceiptSection`, and `decisionPanel` under "Checks".
    - Other publications have `correctable: []` and that kind's `reviewPath`, with undo `{status:"proposed"}`.
  - **History tab:** `historyList`, then "Readings": `#doc2-runs`, `#doc2-rotation`, "Read again as a new run" and
    `#doc2-telemetry`.
  - **Details tab:** location, original source, **Also found**, folder, preserved version with Copy hash, versions,
    "How the text was read", reading notes.
  - **⋯ menu:** Edit description…, Versions (n), Move, Delete or Restore, then Read again, Extract again, Copy text.
  - **URL:** `?tab=` kept with `history.replaceState` alongside `version` and `lines`. `?lines=` highlights on open.
  - **Hooks:** `closeDocumentV2()` and `pollDocumentV2()`, plus `refreshDocumentV2()` and `renameDocumentV2()`.
- **`shell.js`:** leaving `document` also calls `closeDocumentV2?.()`. `#doc2-back` calls `leaveDocument()`. Esc and
  Back already key on the route name.
- **`app.js`:** the poll calls `pollDocumentV2()` after `pollReceipt()` (about line 335).
- **`library.js`:** `afterLibraryChange` (about line 331) and rename (about line 366) also call the v2 hooks.
- **`index.html`:** a new `<section id="doc2-panel" data-page="document" data-ui="v2" hidden>` with the ids in the
  contract, next to `#document-page`.
- **`style.css`:** new blocks "Source viewer", "Confirm and correct", "History list" and "Document page v2", after
  the "Document inspector" section (about line 912). Tokens only.
- **`tests/seed_documents.py`** (new) and **`ui_shots.py`** (see "Seeding").

### Build B
- **`review.js`:** refactors only:
  - `reviewData()` returns `{items, catalog, unmatched, counts}` out of `loadReview`'s `Promise.all`;
  - the keydown handler returns early when `uiV2Screens.includes("review")`. This is a real bug otherwise, since V
    would click a hidden v1 `#review-confirm`;
  - `openItemDialog(resolution, onDone = () => loadReview(false))`.
- **`profiles.js`:** `routingRow(record, people, onSent = loadFamilyRouting, idPrefix = "route")`.
- **`app.js`:** about line 326, reload v2 when it's on.
- **`household/items.py`:** backend 1e.
- **`review_v2.js`** (new; registered in `STATIC` and loaded before `shell.js`):
  - **Registration:** `V2_SCREENS.review = {title: "To check", show: route => loadReviewV2(route.params)}`. The
    sidebar label becomes "To check" while it's on (like `setHomeNavLabel`).
  - **Queue:** v1's `REVIEW_GROUPS`, then "Images that look like one document" (`group:<id>`), "Receipts with no
    matching charge" (`unmatched:receipt-<id>`), and in the family view "Who is it for?" (`routing:<type>-<id>`)
    instead of unmatched. Failed and unfiled counts are link rows at the queue's foot.
  - **URL:** `#/review?item=<reviewKey>` via `replaceState` on select, J/K and advance. A missing key selects the
    first item.
  - **Middle column by kind:** see the table under "States". The right column comes from `review2Parts(item)`, copied
    from v1's `reviewParts`, with the *why* deduplicated: v1 repeats the title; v2's *why* is the reason only.
  - **Reused from `review.js`:** `summaryBlock`, `reviewTitle`, `reviewKey`, `REVIEW_GROUPS`, `ISSUE_KINDS`,
    `LINK_KINDS`, `proposedAssets`, `SIGNALS` and `kindSelect`.
  - **Records, assets, tax forms and confirmations** use `confirmCorrect`, with `cc.confirmButton.id =
    "review2-confirm"` and `rejectButton.id = "review2-reject"`. Assets have `correctable: []`.
  - **Other kinds** use bar buttons with the same ids and `review2Decide(path, body, message, undo)`: 8s Undo for
    record-like kinds, and an inline error that keeps the item on failure. Group: Combine (V) / Keep separate (R).
    Routing: `routingRow`'s form is the bar. Unmatched: Correct… (purchase date) and Open document.
  - Labels keep v1's " (V)" / " (R)" suffix.
  - **Keys:** J/K/V/R, never in inputs, dialogs or the open Correct form.
- **`index.html`:** `<section id="review2-panel" data-page="review" data-ui="v2" hidden>`.
- **`style.css`:** a "To check v2" block after "Review." Tokens only.

## Selector contract
**v1 selectors:** every v1 id and class stays, unchanged. v1 isn't restyled. That covers:
- `#review-detail`, `#review-unmatched`, `#review-queue`, `#review-confirm`, `#review-reject`, `#review-status`,
  `#group-suggestions-panel`, `#family-routing .routing-row`, `.routing-people`, `#reconcile`, `#reconcile-prompt`,
  `#nav-review`;
- `#document-page`, `#record-empty`, `#parse-receipt`, `#extract-ledger`, `#extraction-state`, `#extraction-result`
  (`.ledger-record-heading`, `.receipt-summary`, `.ledger-rows`, `.receipt-splits`, `.receipt-rewards`),
  `#receipt-title`, `#receipt-subtitle`, `#receipt-text`, `#receipt-codes`, `#receipt-overlay`, `#receipt-pdf`,
  `#receipt-image`, `#receipt-status`, `#receipt-preview-error`, `#close-receipt`, `#source-text-tab`,
  `#source-image-tab`, `#details-tab`, `#document-details`, `#document-state`, `#group-pages`, `.split-panel`,
  `.paystub-breakdown`, `.paystub-taxes`, `#correct-*`;
- the globals `receipt` and `imageForReceipt` (`test_receipt_counting.py:222`).

**The tests that use them:** `test_browser.py`, `test_receipt_counting.py`, `test_family_browser.py`,
`test_recurring_bills.py:308–316`, `test_taxes_browser.py:247–251`, `test_shell_browser.py:97–104`,
`test_employers.py:252–259` and `test_document_search_browser.py:78–83`.

| Selector | Used by | Keep / rename to | Test edit |
|---|---|---|---|
| all v1 ids/classes above | v1 tests listed | Keep | none |
| `receipt.js` `sourceButton`/`ledgerRows`/`rewardsList`/`paystub*` signatures | v1 callers | Keep, with a new optional last param | none |
| `review.js` keydown handler | v1 J/K/V/R | Keep, plus the v2 guard | none (the new v2 test checks the guard) |
| new `#doc2-*`: panel, back, title, subtitle, state, menu, version-banner, loading, body, source, group, viewer, record, header, record-title, steps, next, why, decision, tab-record/history/details, panel-record/history/details, runs, rotation, telemetry, status | `test_document_v2_browser.py` | new | new file |
| new `.source-viewer`, `.sv-*`, `.confirm-correct`, `.cc-*`, `.history-list`, `.history-row`, `.history-*` | `test_record_components_browser.py` | new | new file |
| new `#review2-*`: panel, title, reconcile, refresh, status, state, body, layout, queue, picker, prev, next, source, item, position, evidence, bar, confirm, reject, correct, open | `test_review_v2_browser.py` | new | new file |

## States

### Document page v2
| State | `#doc2-steps` | `#doc2-next` / decision |
|---|---|---|
| Loading | none | `pageState` "Loading the document …" |
| Unread | Read ○ | **Read document**, plus the "needs a local vision model" note with a Settings link |
| Reading | Read ⟳ | "Reading … progress shows in the sidebar" |
| Read failed or cancelled | Read ✕ | the reason, plus **Try again** |
| Read, not recorded | Read ✓ → Recorded ○ | **Record it** (was "Extract to ledger"), plus the reasoning-model note |
| Extracting | Recorded ⟳ | status text |
| Extract failed or cancelled | Recorded ✕ | the reason, plus **Try again** |
| Publication blocked | Recorded ⚠ | `alertBox` "Can't record this: {reason}" |
| No ledger record | Recorded – | "Filed as {kind}. Use Move to put it elsewhere." |
| Needs review | Recorded ⚠ | `#doc2-why` warning row, then Confirm / Reject / Correct… |
| Verified | Recorded ✓ | "Verified", Undo, Correct… |
| Checked automatically | Recorded ✓ | "Checked automatically", "Not right? Reject", Correct… |
| Rejected | Recorded ✕ | Undo rejection |

Also carried:
- earlier version (banner, and the decision hidden);
- in Trash ("Restore it from ⋯");
- combined page n>1 ("Open the combined document");
- proposed image group ("Decide in To check");
- split file (segment chips, Confirm split, Merge, Split here; the header shows the chosen segment);
- the item category select, rewards, pay stub breakdown and withholding, the tax section, and the decision-model
  disclosure.

### To check v2, middle column by kind
| Kind | Middle column |
|---|---|
| record, issue, asset (and investment, tax form), recurring, unmatched, routing | The document via `loadReading`. A record highlights its evidence lines. |
| link | The receipt, with chips "Receipt · Charge's statement" when the charge has a document. |
| group | The first page, with page chips (`viewer.showDocument`). |
| tax_tag | The target transaction's or receipt's document, fetched lazily; if it has none, a "Bank line" card. |
| item | `line.document_id`, highlighting `line_ids` (backend 1e). |
| warranty | `.source-card` "Found online": the quote as a blockquote, source title, URL as mono text (never a link). |
| tax_table | `.source-card` with the quoted sources and the brackets table. |
| no document | `emptyState("This has no document.")` |

**Other states:**
- **Empty queue:** `emptyState` "Nothing needs you. New documents show here after they're read.", with the source and
  item columns hidden.
- **Loading:** `pageState` in `#review2-state`.
- **Error:** `pageState` error with Retry.
- **Decision failed:** an inline `alertBox` above the bar; the item stays.
- **No library:** pageState "Set up your library".
- **Long text:** merchant and file names wrap in the item column and ellipsize in queue rows (`title=` holds the full
  text).
- **Many rows:** the queue scrolls inside itself. Groups over 200 show "first 200 listed" (as v1).
- **Family profile:** both screens are in `FAMILY_ROUTES`.
  - To check shows "Who is it for?" instead of unmatched.
  - The document page passes `member` where v1 does and sets `confirmCorrect({preview:false})`.
  - The preview endpoint refuses `member`.
- **Dark theme:** tokens only; `--paper` keeps document images white.

## Accessibility
- **Focus order, document page:** back, h1, ⋯, source tabs, lines, header decision, tabs, record rows.
- **Focus order, To check:** header actions, queue, source, item, bar.
- **Opening the Correct form** moves focus to the named field. Cancel and Esc return focus to Correct….
- **Keys:** To check keeps J/K/V/R, and they never fire in inputs, dialogs or the Correct form. The document page keeps
  Esc, which goes back to the list unless the Correct form or the breakdown is open (closes that first).
- **ARIA:**
  - `role=tablist`/`tab`/`tabpanel` with `aria-selected` and `aria-controls`;
  - `.cc-preview` and `#doc2-status` are `aria-live=polite`, and errors are `role=alert`;
  - the queue is a list of buttons with `aria-current`;
  - the bar is `role=group` labelled "Decision".
- **Not by color alone:** status uses `statusBadge` (icon + text). Steps use ✓/⟳/✕/⚠ icons plus a visually hidden
  state word ("done", "in progress", "failed", "needs you"). Selected source lines also get a `--warning` outline.
  Before/after in the preview has the "becomes" sr-only text and a signed difference.
- **Reduced motion:** no scroll smoothing; `scrollIntoView({block:"nearest"})` without `behavior:"smooth"`.
- **Focus ring:** the 2px accent ring is visible on `.sv-line`, queue rows and the bar buttons.

## Out of scope
- Restyling v1 Review or v1 document page.
- Any other page.
- Investment corrections.
- The Transactions drawer's Correct (Money screens).
- Deleting v1 loaders (Phase 3).
- Copy changes beyond those listed (Confirm / Reject / Correct, "Record it", "To check", the deduplicated *why*).
- Live LM Studio runs; seeding uses the fake model server.

## Seeding
New **`tests/seed_documents.py`**, reusing the `test_extraction.py`/`test_browser.py` fake-model pattern on the app's
manager. Household settings are set with `model_copy` so `ui_v2_screens` isn't reset.
- `seed_read_receipt(manager, model, needs_review=False)` makes a PNG with `make_receipt`, reads it with the fake
  vision model, and extracts it with the fake reasoning outputs (classification, summary, identity, items, rewards).
  With `needs_review=True`, the summary total is off, so the arithmetic check fails. Returns `{doc_id, record_id}`.
- `seed_statement(manager)` makes a statement PNG and publishes it as in `test_receipt_counting.statement`, with a row
  to correct.

**`ui_shots.py`:**
- `seed()` starts `model_server.start_model_server()`, stopped in `finally`, and returns the ids.
- `--routes` accepts `{receipt_doc}`, `{review_doc}`, `{statement_doc}` and `{review_record}` via `str.format`.
- Example: `--routes "documents/{receipt_doc},documents/{review_doc},documents/{statement_doc},review" --v2 document,review`.

## Verification

### Build A
1. Backend:
   `.venv/Scripts/python.exe -m pytest tests/test_correction_preview.py tests/test_record_history.py tests/test_provenance.py tests/test_receipt_counting.py tests/test_traces.py tests/test_api.py tests/test_family_ledger.py -q`
   - **`test_correction_preview.py`:**
     - Moving a receipt from September to October moves September's and October's `spending.net` and
       `spending.category`.
     - After the real PATCH, each `/api/traces/{ref}` equals the preview's "after".
     - Nothing persists (`record_corrections`, `reconciliation_runs`, `merchants`, `review_events`,
       `figure_snapshots`, the receipt row).
     - A bad date gives 400 with PATCH's message.
     - Auto-verify is shown.
     - A transaction amount change ends its match.
     - A statement balance changes `account.balance`.
     - A bill or pay stub shows notes only.
     - `member=` gives 400.
     - It finishes in under 5s.
   - **`test_record_history.py`:**
     - Order, from/to, reason, who, labels, the automatic entry.
     - A statement's row entries.
     - Undo restores the value, the issues and needs_review; a second undo gives 400.
     - The PATCH gives `correction_ids`.
     - `correctable` per type.
     - `figures=1`: `split` equals its trace and reconciles.
2. Components: `tests/test_record_components_browser.py`, mounting each component into `#parity-fixture` like
   `test_trace_components_browser.py`. Check:
   - `highlight` switches tabs and selects lines;
   - `onRegionClick` fires on Enter;
   - Correct, then preview with two months, then Save, then Undo, and History shows both;
   - Esc closes the form and stays on the page;
   - no overflow at 390.
3. `tests/test_document_v2_browser.py`, with `PUT /api/ui-screens {"routes":["document"]}`. Check:
   - every state in the table;
   - Find highlights a `.sv-line`;
   - Correct with preview, then Undo, then History;
   - Confirm posts to `/review`;
   - `?tab=history` survives a reload;
   - Esc returns to the list;
   - **`#doc2-decision` Confirm bottom ≤ 768 at 1366×768** (rule 1), including with issues showing;
   - no horizontal scroll at 390, 768 and 1440;
   - `check_figures` (from `test_ui_parity.py`) on `#doc2-panel`, plus "Counts as" in `v1_amounts` of the v1 page for
     the same document.
4. Browser run:
   `$env:RUN_BROWSER_TESTS = "1"; .venv/Scripts/python.exe -m pytest tests/test_document_v2_browser.py tests/test_record_components_browser.py tests/test_browser.py tests/test_receipt_counting.py tests/test_document_search_browser.py tests/test_employers.py tests/test_trace_components_browser.py tests/test_ui_parity.py tests/test_shell_browser.py tests/test_style_tokens.py -q`
5. Screenshots:
   `.venv/Scripts/python.exe .claude/skills/ui-redesign/scripts/ui_shots.py --routes "documents/{receipt_doc},documents/{review_doc},documents/{statement_doc}" --v2 document --out <scratchpad>/after-document`
   Compare with the before shots (retaken with the new seed). No `HORIZONTAL OVERFLOW` and no page errors.

### Build B
1. `tests/test_review_v2_browser.py`. Check:
   - **`#review2-confirm` bottom ≤ 768 at 1366×768** and ≤ 900 at 1440×900;
   - J/K move and update `?item=`, and a reload keeps the item;
   - V confirms and Undo restores;
   - the v1 handler doesn't fire (render v1 first, then switch on v2);
   - a record highlights evidence in `#review2-source`;
   - warranty and tax_table show `.source-card`;
   - Correct with preview;
   - group Combine;
   - unmatched Correct;
   - family routing (setup from `test_family_browser.py`);
   - the picker under 1180, the fixed bar under 900, no overflow at 390.
2. Browser run:
   `$env:RUN_BROWSER_TESTS = "1"; .venv/Scripts/python.exe -m pytest tests/test_review_v2_browser.py tests/test_browser.py tests/test_family_browser.py tests/test_recurring_bills.py tests/test_taxes_browser.py tests/test_shell_browser.py tests/test_ui_parity.py tests/test_style_tokens.py -q`
3. Screenshots: `ui_shots.py --routes "review,review?item=record:receipt-{review_record}" --v2 review,document --out <scratchpad>/after-review`.

### Both builds
- **Parity:** no `MIGRATED` pair. To check shows no traced figures (the harness requires some), and the document page
  needs a seeded id. Its parity check lives in `test_document_v2_browser.py`. Record this in docs/ui.md "Migration".
- **Keyboard:** tab through both pages and check the focus ring.
- **Contrast:** check `--text` on `--warning-subtle` in light and dark.

## Docs to update
- **docs/ui.md:**
  - "Pages": two v2 bullets, for To check and the document page.
  - "Review" and "The document page": what v2 adds.
  - "Observability components": all seven built, with `loadReading`/`loadHistory`.
  - "Migration": registered `document` and `review`; no `MIGRATED` pair, and why.
- **docs/money.md "Corrections":** the preview, history and undo endpoints. Remove "There's no screen for these yet".
- **docs/open-work.md "UI redesign":** mark To check and the document page built. Item 6 moves on to the Money
  screens.
- **design-system:** README (a Phase 2 section, plus where the build differs from the plan), `pages/review.md` and
  `pages/document.md`. Add the new contrast pair to MASTER.md.

## Risks
1. **The preview holds the write lock** for a reconciliation pass. The 450ms debounce, one preview in flight, and the
   timing test cover it.
2. **The preview could drift from a real save.** The "after equals the trace after PATCH" test guards it.
3. **Per-field Find** depends on extraction keys mapping to `RECORD_FIELDS` keys. Check against
   `provenance._extraction` and hide Find when the provenance has no lines.
4. **v1 and v2 coexisting:** the key handler, the global `receipt`, polling and duplicate ids. Each is guarded or
   given a new id above.
5. **Very long PDFs** in `.sv-lines` may be slow. Render 500 lines at a time if needed.
