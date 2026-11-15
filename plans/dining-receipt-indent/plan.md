# Dining receipts: charged total and tip, one category, indented lines — implementation plan
Spec: specs/dining-receipt-indent/spec.md (with specs/dining-receipt-indent/test-contract.md)
Spec sha256: 0f8ed366305f320d7ab4bee1eb45f1b115770e30910a65d658ea63b54bbbc224
Review-Risk: HIGH
Review-Risk-Rationale: It changes stored money (total, tip, splits), removes charge links on re-read, adds a schema migration, and changes three reading versions and the vision output contract.

<!-- Approval lives in approvals/<slug>.json, bound to this file's hash. No Status line.
     Execution progress goes in plans/<slug>/progress.yaml, never in this file. -->

## Verified repository integration points
Read at HEAD 66e97d5 (`git diff 2676e51 HEAD -- src/ tests/` is empty, so the test contract's capture commit still holds).

| Area | Where (verified) | What this plan does there |
|---|---|---|
| Versions | `models/vision.py:20` `VISION_VERSION = "receipt-vision-v6-tables"`; `documents/pdf_reader.py:14-17` `PDF_VERSION = "pdf-pages-v3-layout"`, `PDF_VERSIONS`, `GROUP_VERSION = "receipt-images-v2-tables"`; `pdf_reader.py:31` `PDFResult.parser_version` Literal; `documents/extraction.py:52` `EXTRACTION_VERSION = "typed-extraction-v56-money-sign-rule"` | New values (P1). The spec's FR-24 "v57" is correct: v56 is current, so the next is v57. |
| Group/PDF version checks | `documents/receipt_service.py:65` (new run key), `:118` publish (`(*PDF_VERSIONS, GROUP_VERSION, "receipt-images-v1")`), `:120`/`:126` (size limit and layout check `== PDF_VERSION`), `:179-180` (only the current PDF version executes), `:192` run (`== GROUP_VERSION`), `:254-263` `recover` → `publish` | `GROUP_VERSIONS` used at `:118` and `:192` (D24, D32); `LAYOUT_PDF_VERSIONS` at `:120`/`:126` so a v3 run published by recovery keeps v3's checks. |
| Vision call | `vision.py:113-198` `VisionText{full_text}`, prompt, strict schema `document_transcription`, keys check `:181`, rescue `document_text_fallback` `:184-197`, table validation `:189-196`; `transcribe_preview` `:200-239` builds `TextLine`s per region | `lines: [{text, indent}]` (FR-15 – FR-18). `VisionText.full_text` stays as a property (joined text) for `evals/tasks/transcription.py:55` and `pdf_reader.py:92`. |
| Line model | `documents/receipt_schema.py:25-28` `TextLine{id,text,block_ids}` strict; `:146-150` model_text check; `TextLine(...)` constructors at `vision.py:191,217`, `pdf_reader.py:94,117`, `layout_context.py:25,36` (native PDF projection, no indent) | Optional `indent`, left out of every dump when unknown, so old readings serialize byte-identically (P2). |
| Line payloads to the extraction model | `extraction.py:975` (`chunks` byte budget), `:1226`, `:1234`, `:1249` (pay-stub table window byte budgets), `:2009` (byte budget), `:2349` (`ask` content) — all build `{"line_id","text"}` (found with `grep -n '"line_id": [a-z_]*\.id' src/home_manager/documents/extraction.py`) | One helper `line_payload(line)` used at all six, so budgets and the request agree (FR-21). `documents/reasoning.py:125` is the older interpretation path, not extraction: unchanged. |
| Receipt row instruction | `extraction.py:4383-4392` (with `KIND_ROWS` `:544-551`, dining `:547`) | FR-22 sentence appended to the receipt branch (every receipt form). No other prompt changes (D33). |
| Dining summary prompt | `extraction.py:539-541` | Unchanged (D33). |
| Reading → saved result → publish | `ExtractionService.record` `extraction.py:5052-5084` saves `result["header"]`/`["rows"]`/`["item_categories"]` then calls `publish` `:4605` → `normalize` `:2774` (receipt branch `:2822-2878`, dining check `:2860`, `unprinted_amounts` `:2716`) → `review_reasons` `:4160` → `Ledger.publish_receipt` | The dining total/tip decision and the side-line backstop run at the top of `record`, before `result` is built, so the saved header/rows (which `document_traces.provenance` reads for citations, `finance/document_traces.py:38-55`) hold the decided values (P4). |
| Several receipts in one file | `looks_like_several` `extraction.py:2104-2106`, `TOTAL_LINE` `:2088`, used at `:5102` | Unchanged (D14, SC-19 characterization). |
| Ledger publication | `finance/ledger.py:731-743` `_upsert`; `:752-811` `publish_receipt` (order: upsert → kind correction → items `_replace_items` → `apply_corrections` → `refresh_paid` → rewards/tax lines → `refresh_splits`); `:903-942` `refresh_paid` (gift-card note `:930-935`, `PAID_ISSUES` `:233`) | FR-10 step, FR-28 link test and removal, worked-out marker column (P5, P8). |
| Items and categories | `_replace_items` `ledger.py:1046-1107` (memory `:1078-1081`, user choice kept `:1088-1089`); `set_item_category` `:1224-1239`; Edit details category `:2580-2583`; `_undo_kind` `:867-881`; family copies `finance/family_routing.py:322`, `:390` | FR-10 – FR-14. |
| Splits | `refresh_splits` `ledger.py:1151-1166`, `split_inputs` `:1168-1185`, `shares` `:1206-1222`; `finance/splits.py:158-198` `allocate` (tip `:185-186`, rule 5 `:187-190`), `scale` `:207`, `by_line` | `allocate(..., one_category=False, tip_category=None)` (D18, FR-27). |
| Payload | `Ledger.record` `ledger.py:2003-…`: `unmatched_minor` `:2074-2075`, `totals_mismatch` `:2076-2078`, `splits` `:2081-2083` | `category_column`, `tip_note`, FR-27 `unmatched_minor`. |
| Corrections | `correct` `ledger.py:2509-2534` (auto-verify), `_apply_correction` `:2536-2586` (resolves issues starting with the label, "Tip" `:168`), `apply_corrections` `:2982-3041`, `undo_corrections` `:2766`, `UNDO_REASON` `:220` | Tip marker rule (P6); FR-14 (c). |
| Reconciliation | `finance/reconcile.py`: `NEAR_PERCENT` `:33`, `CROSS_RANGE` `:36`, `Reconciler.__init__` `:189-190` (`EcbRates`), `run` `:201-224` (full `refresh_splits`), `issue` `:233-241`, `link_choice` `:271-277`, `estimate` `:310-319`, `link_receipt` `:321-332`, `receipts` `:401-436`, `cross_currency` `:467-482`, `review_link` `:778-809`, `link_documents` `:811-821`; `finance/fx.py:203` `EcbRates.resolve(rate_id, db)` | FR-28 – FR-30 in a new `Reconciler.drop_stale_links` (P8). |
| Backfill | `finance/item_categories.py:28-91` | D27 dining rule. |
| Kind change job | `app/manager.py:1567-1612` `change_kind` (from the saved transcription), `:1614-1625` `extract_and_file` (reconcile after a published reading) | Unchanged; FR-13 is in `publish_receipt`'s reviewed branch and `_undo_kind`. |
| Item table and footer | `app/static/receipt.js:125-142` dropdown, `:305-306` `RECEIPT_COLUMNS`, `:356` filter, `:396-415` footer (Tip, "Not matched to an item" from `record.unmatched_minor`), `:417` "Doesn't add up" | Hide Category from `record.category_column`; Tip note from `record.tip_note`. |
| Text view | `app/static/trace.js:323-330` `renderLines` (`li.sv-line`); `style.css:1133-1136` `.sv-lines`, `.sv-line` | `data-indent` + CSS padding (FR-26). |
| Migrations | `library/storage.py:67` loads `library/migrations/NNN_*.sql`; last is `080_split_merged_documents.sql` | `081_dining_receipts.sql` (P5). |
| Money text | `core/money.py:89` `format_minor` gives "52.76 USD"; no "$52.76" helper exists | New `amount_text(minor, currency)` (P7). |
| Test stubs | `tests/model_server.py:24` default `{"full_text": …}`, `:96-100` `by_schema`/`outputs`; 30 test files and `scripts/statement_diagnose.py:63`, `scripts/loopback_stress.py:68` stub `full_text` | Move to `lines` (contract "Vision stub shape"). |
| Tests that assert version values | `tests/test_bill_account_holder.py:311`, `tests/test_bill_engine_record.py:248`, `tests/test_bill_printed_total.py:367` (exact v56 string), `tests/test_document_groups.py:88`, `tests/test_bill_split.py:538` ("receipt-images-v2-tables"), `tests/test_pdf.py:137` ("pdf-pages-v3-layout"), `tests/test_vision_tables.py:119` (rescue shape) | Updated on purpose (contract "Existing tests whose expectations the spec changes on purpose"). |
| Docs | `docs/documents.md` headings "Images (vision transcription)" `:206`, "PDFs" `:243`, "Several images as one document" `:446`, "Receipt kinds" `:532`; `docs/money.md` "Gift cards" `:318`, "Reading a statement or receipt again" `:544`, "Near matches and foreign receipts" `:597`, "Item categories and splits" `:637`; `docs/ui.md` "Screen rules"; `docs/open-work.md` | FR-25. Headings unchanged. |

## Architecture, contracts, data flow and decisions

Data flow (new parts in bold): image → vision `lines[{text, indent}]` → **`TextLine.indent`** → parse run under v7 →
extraction requests carry **`indent`** for known lines → `ExtractionService.record`: **dining decision** (total, tip,
table exclusion) and **side-line backstop** rewrite header/rows → saved result → `normalize` → **FR-06 reason** →
`publish_receipt`: items → corrections → **FR-10 (one category)** → `refresh_paid` → **FR-28 stale links** →
`refresh_splits` with **`one_category`** → payload **`category_column`, `tip_note`, FR-27 `unmatched_minor`** → page.

Plan decisions (P#). Names here are the names the test contract leaves to the plan.

- **P1 Versions.** `VISION_VERSION = "receipt-vision-v7-indent"`, `PDF_VERSION = "pdf-pages-v4-indent"`,
  `PDF_VERSIONS = ("pdf-pages-v1", "pdf-pages-v2-tables", "pdf-pages-v3-layout", PDF_VERSION)`,
  `LAYOUT_PDF_VERSIONS = ("pdf-pages-v3-layout", PDF_VERSION)` (both carry a native layout capture and the larger
  evidence limit), `GROUP_VERSION = "receipt-images-v3-indent"`,
  `GROUP_VERSIONS = ("receipt-images-v1", "receipt-images-v2-tables", GROUP_VERSION)`. `PDFResult.parser_version`
  Literal gains both new values. `receipt_service.py:118` becomes `in (*PDF_VERSIONS, *GROUP_VERSIONS)`, `:192`
  becomes `in GROUP_VERSIONS` (same set, D32), `:120`/`:126` test `in LAYOUT_PDF_VERSIONS`, `:179` stays
  `== PDF_VERSION` (only current PDF runs execute). `EXTRACTION_VERSION = "typed-extraction-v57-dining-indent"`.
- **P2 Indent on a line.** `TextLine.indent: int | None = Field(default=None, ge=0, le=2)` with a wrap
  `model_serializer` that drops `indent` when it is None (the pattern of `Sampling.omit_unset_sampling`,
  `vision.py:44-57`). So an old line dumps exactly as today (`{id,text,block_ids}`) everywhere: `ReceiptService.get`
  `:94`, `layout_context.viewer_context`/`saved_lines`, stored results. `combine_pages` and `complete_pdf` pass indent
  through; embedded-text and native-projection lines have none.
- **P3 Vision contract.** Main schema: `{"lines": [{"text": string, "indent": integer}], "tables": [...]}`, both
  required, strict. Rescue schema `document_text_fallback`: only `lines` (same item shape), no tables (D9). Both
  prompts state FR-15's rules (0 main left edge; 1 printed further right under the line above: sides, modifiers,
  notes under an item; 2 deeper; centered headings and footers 0; indent for no other reason; text without leading
  spaces); the main prompt's `line_index` sentence says it counts the final lines after any line break inside a
  `text` is split (same indexes as today's `full_text.split("\n")`, SC-10 (d)). Parsing: the answer must be a dict
  whose keys are `{"lines"}` or `{"lines","tables"}` (main) / exactly `{"lines"}` (rescue); `lines` a non-empty list
  of dicts, each with a string `text`; anything else (including the old `{full_text}` shape, D25) is invalid → rescue
  → "Model output did not contain valid full text after a text-only retry." as today (FR-18). Indent per entry: kept
  only when the value is an `int` (not `bool`) in 0–2; missing key, other types, floats, out of range → None (FR-17).
  An entry's text containing `\n` becomes several lines with the same indent. All text blank → "Model response was
  blank." `VisionText` becomes `{lines: list[tuple[str, int | None]], tables, table_issue}` with a `full_text`
  property; `scripts/statement_diagnose.py` builds it from lines.
- **P4 Dining decision in code, before the result is saved.** New module `documents/dining_total.py` with a pure
  function `decide(header, lines) -> DiningDecision(header, tip_basis, issues)` (issues as `(template, amounts)` pairs,
  amounts as printed decimals; see the last bullet for where they become text) applied in `ExtractionService.record`
  when `classification.document_type == "receipt"` and `reading["receipt_kind"] == "dining"` and `header` is not
  None. It works on printed decimals (`line_amount`, `extraction.py:2170`), so it needs no currency, and returns a new
  header whose `total`/`tip` `Value`s carry the decided amount text and cite whole-line quotes. Rules (FR-01 – FR-05,
  D19, D22, D23, D29, D30):
  - **Suggested-tip table:** maximal runs of consecutive lines that print a percentage and an amount ("18.00% of sale:
    $8.79 Total $61.55"), plus a directly preceding heading line "Suggested Tip"/"Tip Guide"/"Tip Suggestions" if
    present. Its lines are never pre-tip, post-tip or tip lines.
  - **Pre-tip amount:** a line outside the table that starts (after whitespace) with `Total` or `Grand Total` — not
    Subtotal/Sub Total, Total Tax, Total Item(s)/Item Count, Total Savings/Saved/Discount(s) — or with `Bill`,
    `Amount due` or `Balance due`, and ends with an amount. Nothing else (D30: "Amount: $52.76" is not one).
  - **Post-tip total:** a Total/Grand Total line larger than the nearest pre-tip amount before it; the latest one
    counts. When found: the header total becomes its amount, citing that line only (D19: with or without a tip line).
  - **Disagreement (D23, D29):** if a pre-tip amount before the nearest one differs from it, add "The receipt prints
    different amounts before the tip ($X and $Y), so the tip wasn't worked out." ($X the earliest differing one, $Y
    the nearest) and work out no tip.
  - **Table citations (FR-05):** a model total whose evidence cites only table lines is dropped with "The total the
    reading took from the suggested-tip table was not used."; it is replaced by the post-tip total if any, else the
    nearest pre-tip amount printed before the table (cited to its line), else the total is `missing`. A tip cited only
    to table lines is dropped with "The tip the reading took from the suggested-tip table was not used." The model is
    never asked again.
  - **Worked-out tip (FR-02):** when a post-tip total exists, a tip line is printed outside the table (a line starting
    with `Tip`; the "Suggested Tip" heading is in the table), the amounts agree, and the model's tip is missing, blank,
    dropped (table), or not printed on any of its cited lines: tip = post-tip − nearest pre-tip, as a `Value` citing
    the pre-tip line then the post-tip line. `tip_basis = {"total": {"label", "line_id", "text"}, "bill": {…}}` with
    labels as printed-normalised ("Total", "Grand Total", "Bill", "Amount due", "Balance due").
  - **Printed tip (FR-03):** kept; if tip + nearest pre-tip ≠ post-tip total, add "Tip ($X) and the bill ($Y) don't
    make the total ($Z)." (normalize still adds today's dining-check issue when the sum fails.)
  When `decide` replaces or drops the total or the tip, the matching entry of `reading["summary_references"]` (the
  model's table cell for it, `extraction.py:4655-4656`) is dropped too, so no cell evidence points at the old amount.
  The saved result also gets `result["dining"] = {"tip_basis": …, "issues": […]}` so a later Extract again or a trace
  can show it. `decide` runs before the currency is known (`ExtractionService.publish` resolves it with `currency_for`,
  `extraction.py:4621`), so it returns its issues unformatted. `record` passes the decision to `publish` as a new
  keyword `dining=None`; `publish` formats each amount with `amount_text` (P7) once `currency_for` has run and appends the
  texts to `notes` before `issues.extend(notes)` (`extraction.py:4689`). Receipts keep notes as issues, so the FR-05
  notes are review reasons (P11). The FR-05 notes carry no amount and are formatted the same way for one code path.
- **P5 Migration `081_dining_receipts.sql`.** Adds `receipts.one_category INTEGER NOT NULL DEFAULT 0` (FR-10 has applied)
  and `receipts.tip_worked_out_json TEXT` (NULL = the tip is printed or missing), and
  `record_corrections.item_categories_json TEXT` (NULL; set only on a kind-change correction, P8 "Undo of a kind
  change"). Three `ALTER TABLE … ADD COLUMN` statements and nothing else: no `UPDATE`, `INSERT`, `DELETE` or `DROP`, no table rebuild, and no statement touching
  `category_splits`, `receipt_items`, `transaction_receipt_links` or any money column. Every existing receipt reads
  "FR-10 has not applied, no worked-out tip", so no stored total, tip or split changes at upgrade (D5, FR-08). Verified
  by X-UPG and by SL-04's grep check.
  `publish_receipt` writes `tip_worked_out_json` = `tip_basis` plus `total_minor`/`bill_minor` (the amounts in minor units,
  for the note) when the record carries a worked-out tip, else NULL.
- **P6 The tip marker and corrections (FR-09, D26).** The marker is "worked out now" when `tip_worked_out_json` is set and
  no tip correction is in force: the latest `record_corrections` row for field `tip` is absent, or is an undo back to
  the first value (the same test as `document_traces.provenance` `:42`). So Correct Tip hides it, Undo shows it again
  (SC-06 (a)), and a later Extract again keeps it hidden while the correction stands. The FR-06 reason starts with
  "Tip", so today's correction rule resolves it. The payload's `tip_note` is "Worked out: Total $61.55 − Bill $52.76"
  (server-made text) or None. The dining trace labels the Tip input "Tip (worked out)" with provenance citing both
  lines (from the saved header). FR-06's reason "Tip $8.79 was worked out from Total $61.55 less Bill $52.76, not
  printed; check it." is added in `publish` (`extraction.py`) after `normalize`, since only there is the currency known.
- **P7 Amount text.** `core/money.py` `amount_text(minor, currency)`: magnitude with thousands separators and the
  currency's exponent, prefixed "$" for USD, "€" for EUR, "£" for GBP, else `format_minor`'s "1,234.50 CAD". Used by
  every new issue (FR-01, FR-03, FR-06, FR-30) and `tip_note`.
- **P8 FR-10 and the split rules.**
  - `splits.allocate(..., one_category=False, tip_category=None)`: with `one_category`, every item row takes `fallback`
    (the receipt's category) whatever the item says, the tip row takes `fallback` (or DINING when the receipt has none),
    and a positive difference is one no-item row in `fallback` (never spread). Without it, today's rules 4 and 5
    exactly. `tip_category`, when given, overrides the tip row's category only (used by FR-27).
  - `Ledger.shares` passes `one_category = receipt["one_category"] and receipt["receipt_kind"] == "dining" and
    receipt["document_kind"] == "receipt"`. Every rebuild (reconcile, links, deletion, family) reads the flag, so a
    rebuild never undoes it and never applies it (D8).
  - New `Ledger.apply_one_category(db, receipt_id)`: for a dining receipt, sets `one_category = 1` and stores the
    receipt's category with source `receipt` on every item whose source isn't `user` (D20). Called on FR-14's events
    only: (a) `publish_receipt` after `apply_corrections` when `written` and the record is a dining receipt; (b) a kind
    change to dining — the reviewed branch of `publish_receipt` (`ledger.py:784-787`) and, only when the undone
    correction has no snapshot (see "Undo of a kind change"), `_undo_kind` when the kind
    put back is dining; (c) `_apply_correction` when `category` changes to a different value on a dining receipt
    (Q1: the same value is not a change).
  - At recording, a dining receipt's category is dining (`record["category"] = "dining"` in `publish` for receipt kind
    dining); a category correction you made is replayed by `apply_corrections` and wins, as today.
  - `_replace_items` on a dining receipt reads no `item_category_memory` (FR-12's "never read").
  - The reviewed kind-change branch (`ledger.py:784-787`) today only sets the kind and parks the details; it never
    rebuilds splits. It gains `apply_one_category` (to dining) or `recategorise_items` (away from dining) and then
    `refresh_splits(db, receipt_id)`, so the split follows FR-13 in the same publication, not only after the
    reconciliation that follows the job. `_undo_kind` (`ledger.py:867-881`) likewise ends with the flag set or cleared and
    `refresh_splits(db, receipt_id)`: `undo_corrections` (`ledger.py:2815-2817`) calls `_undo_kind` and `continue`s, and
    nothing on that path rebuilds splits today.
  - **Undo of a kind change (FR-13 "Undo restores the earlier splits").** Before `publish_receipt` changes anything on a
    kind change (both branches), it snapshots `{"one_category": …, "items": [[item id, category, category_source], …]}`
    and stores it in the kind correction row's `item_categories_json` (`ledger.py:781-783`). `_undo_kind` restores each
    listed item still present (ids are kept by `_replace_items` for matched items) and the flag, then
    `refresh_splits`. So Undo of grocery → dining on a verified receipt gives back the grocery categories exactly, which
    the latest extraction run can't (on a reviewed receipt the latest run is the dining reading itself, and
    `apply_one_category` has already overwritten the non-`user` items). Items not in the snapshot keep what they have.
    With a snapshot, Undo restores it and nothing else: `apply_one_category` and `recategorise_items` are not called,
    so an old dining receipt FR-10 hadn't applied to comes back with its own categories and the flag unset. The kind
    correction row `_undo_kind` itself inserts (`ledger.py:873-874`) stores a snapshot of the state just before the
    Undo, so undoing the Undo is exact too. Only a kind correction recorded before 081 has NULL there: Undo then
    applies FR-10 (back to dining) or `recategorise_items` from the latest succeeded run (away from dining).
  - Away from dining (FR-13): `one_category = 0`. In the written branch `_replace_items` already gives memory, then the
    model, keeping `user`. In the reviewed branch (items kept) and in `_undo_kind` back to a non-dining kind, new
    `Ledger.recategorise_items(db, receipt_id, rows)` sets each non-`user` item to memory, else the model's category,
    matching items by `item_keys` against the reading's rows (the new reading's `record["items"]`; for Undo only when the
    correction has no snapshot, see above).
- **P9 Category column (FR-11, FR-12, D6, D7).** `Ledger.category_column(db, receipt_row)` → False (hidden) when the
  record is a receipt with `receipt_kind` dining and every item row of the receipt's own split
  (`transaction_id IS NULL AND receipt_item_id IS NOT NULL`) has the receipt's category; with no split yet, from the
  categories the split would use (`fallback` for all when `one_category`, else each item's category or the
  fallback). True otherwise (every other kind). The payload sends `category_column`; `set_item_category` refuses
  with 400 and the exact FR-12 message, before writing anything, exactly when it is False.
- **P10 FR-27.** `unmatched_minor` = today's sum less the tip's own row. The tip row is found without a schema change
  by building the receipt's own split once more with `shares(..., tip_category=TIP_MARK)` (a sentinel no real
  category uses) and summing the rows carrying the sentinel; that is exactly the stored tip row, resized like it for a
  gift card or family share, since `rounded`, `scale` and `by_line` never look at categories. No `category_splits` row
  is written.
- **P11 Notes are issues.** A receipt stores no notes apart from its issues (`document_v2.js:610` shows `details.notes`
  only for bills, statements and pay stubs), so the FR-05 notes and the FR-23 notes are issues. A receipt with one of
  them waits in Review. SC-04/SC-13 assert their presence only.
- **P12 FR-23 backstop.** In `ExtractionService.record`, for `document_type == "receipt"` only (not bills): a row is
  dropped when every cited line has a known indent ≥ 1, none of them prints an amount (`line_amount(text) is None`),
  and a kept row precedes it; its citations append to the previous kept row's evidence, and `item_categories` and
  `reading["cell_references"]` (zipped with the saved rows by index, `extraction.py:5064-5066`) drop the same index. One issue per dropped row's first cited line, “{line}” is printed under “{previous row's
  description}” with no price of its own, so it was kept with that item, not as an item., at most three, then "and N
  more". Unknown indent on any cited line → kept (SC-14).
- **P13 FR-28 – FR-30, stale links.** New `Reconciler.drop_stale_links(db, receipt_id, before)` in
  `finance/reconcile.py` (lazy-imported by `publish_receipt`, as `tax_tags` is). `publish_receipt` reads, before
  `_upsert`, the existing row's `total_minor`, `merchant_id`, `document_kind`; after `refresh_paid`, when `written`,
  the record is not a bill (`document_kind` after corrections) and `total_minor` differs from before, it calls
  `drop_stale_links`. For each live link (`review_status <> 'rejected'`): same currency → holds if
  `-amount == total`; for `verified`, also if `total > 0` and `-amount > total` and `-amount * 100 <= total * NEAR_PERCENT`.
  Other currency → estimate = the stored `estimate_rate_id` via `EcbRates.resolve`, else `self.estimate(...)`; holds
  when `-amount * 100` is within `estimate * CROSS_RANGE`; no rate (including an `FxError` from `resolve` or `estimate`) → doesn't hold. `total_minor` None → nothing holds.
  A link that doesn't hold: its row is deleted (never marked rejected); `transactions.merchant_id` is cleared when it
  equals the receipt's merchant before the reading; `ledger.apply_rules(db, [tx])` and `TaxTags.apply_rules(db, [tx])`;
  the `occurrence_links` row(s) `same_record` between the two documents with status verified are deleted unless another
  live receipt link still joins a transaction from that document to this receipt; the FR-30 issue is appended and the
  receipt set `needs_review`, `review_source` NULL. Then `refresh_paid` runs again (drops a gift-card "Amount paid ("
  note for the removed link, D40) and `refresh_splits` (the charge's rows go). Note text: "The match{ you confirmed}
  to the {amount_text(|charge|, charge currency)} charge on {transaction_date or posted_date} was removed: this
  reading's total ({amount_text(|total|, receipt currency)}) no longer matches it." / "…: this reading has no total."
  All inside the publication's one transaction.

## Error handling, idempotency and recovery
- Vision: invalid main → one rescue → fail as today; a failed run publishes nothing and the earlier reading stays
  (FR-18). Bad indent never fails a reading (FR-17).
- `dining_total.decide` and the backstop are pure and deterministic; with no qualifying lines they return the header and
  rows unchanged (today's behaviour). An unparseable amount on a candidate line makes that line not a candidate.
- A failed extraction never reaches `publish_receipt`: total, tip, marker, splits and links stay (SC-01 (d), SC-22 (b)).
- Link removal, the FR-30 note, `one_category` and the marker are written in `publish_receipt`'s single SQLite
  transaction: a crash before commit leaves everything as before.
- Re-running Extract again with the same answers converges: FR-10 is idempotent, `drop_stale_links` tests nothing when
  the total is unchanged (D39), `_replace_items` keeps item ids.
- Restart: all state is in columns (`one_category`, `tip_worked_out_json`, link rows); nothing runs at startup (D5).
- Recovery publishing an interrupted v6/v3/v2-group run keeps working via `GROUP_VERSIONS`/`LAYOUT_PDF_VERSIONS`.

## Privacy/security and migration impact
- No new endpoint, network call or data leaving the machine; prompts gain rules and the request gains small integers.
- Tests use the synthetic breakfast receipt and stubs only. Nothing under P:\Finances, %LOCALAPPDATA%\HomeManager or
  P:\EvalCorpus is read. The capture in SL-01 runs only against `tmp_path` libraries.
- Migration 081 adds three nullable or defaulted columns (two on `receipts`, one on `record_corrections`); `X-UPG` proves every pre-existing column of the listed tables (plus `record_corrections`, which 081 extends) is
  unchanged and `check_ledger` reports no errors. No backfill, no split rewrite (D5).
- UI: `docs/ui.md` "Screen rules": the page decides nothing (column flag, tip note and footer amount come from the
  server), no framework, no CDN, CSS only in `style.css`. Implementers load `ui-ux-pro-max` before touching
  `receipt.js`, `trace.js` or `style.css` (repo CLAUDE.md).

## Vertical slices
Sequential (implementation_parallelism = 1), one Sonnet worker per slice, each slice's checks targeted. Commands run from
the repo root with `.venv/bin/python`. Every new test file grows slice by slice; a slice adds only the scenarios its code
makes pass.

| ID | FR/SC covered | Dependencies | Files/changes | Verification command / evidence |
|---|---|---|---|---|
| SL-01 | D28 baseline (FR-21, SC-12 captures), fixture self-test | none (no `src/` change) | New `tests/dining_receipt_fixtures.py` (breakfast lines/indents, B0 – B11 stub data, `vision_lines`, paths to the captures; docstring records the capture command and commit). New `tests/test_dining_baseline_capture.py`: skipped unless `CAPTURE_DINING_BASELINE=1`; asserts `VISION_VERSION == "receipt-vision-v6-tables"` and `EXTRACTION_VERSION` v56 before writing, then in `tmp_path` reads the breakfast image (R6), a one-page image-only PDF (P3) and a two-image combined document (G2) with today's `{"full_text"}` stub, records each with B0, and writes to `tests/dining_receipt_data/`: `r6_result.json`, `p3_result.json`, `g2_result.json` (each parse run's stored `result_json`, byte for byte), `q56_r6.json`, `q56_p3.json`, `q56_g2.json` (every reasoning request body `local_model["requests"]` recorded, in order), `row_instruction_v56.txt` (today's receipt row instruction). `test_breakfast_fixture_adds_up` (contract hand checks). | `CAPTURE_DINING_BASELINE=1 .venv/bin/python -m pytest tests/test_dining_baseline_capture.py -q` run twice, with `sha256sum tests/dining_receipt_data/* > $SCRATCH/run1.sha` after the first run and `sha256sum -c $SCRATCH/run1.sha` after the second (the files are new and untracked, so `git diff` can't see a change; determinism: if any byte differs between runs, stop and report — D28 allows no masking beyond the row instruction); `.venv/bin/python -m pytest tests/test_dining_baseline_capture.py -q` (fixture self-test); `git diff --exit-code 2676e51 -- src/` |
| SL-02 | FR-15, FR-16, FR-17, FR-18, FR-19, FR-20; SC-10 steps 1–3, 5 (+a–d), SC-11, SC-12 steps 1, 2, 4–8 (+a, b, c) | SL-01 | `models/vision.py` (P3, `VISION_VERSION`), `documents/receipt_schema.py` (P2), `documents/pdf_reader.py` (P1, indent through `complete_pdf`/`combine_pages`), `documents/receipt_service.py` (P1 checks), `scripts/statement_diagnose.py`, `scripts/loopback_stress.py`. Test infrastructure: `tests/model_server.py` default output and a `vision_answer(text, indents=None)` helper; every `{"full_text": …}` vision stub in `tests/` moves to `lines` (indent 0) except tests about the old shape; `tests/test_vision_tables.py::test_malformed_structured_response_gets_one_text_only_retry` asserts the `lines` rescue; `tests/test_document_groups.py:88` and `tests/test_bill_split.py:538` use `GROUP_VERSION`; `tests/test_pdf.py:137` uses `PDF_VERSION`. New `tests/test_vision_indent.py` (SC-10, SC-11, SC-12 parts listed), old runs built from the SL-01 captures. | `.venv/bin/python -m pytest tests/test_vision_indent.py tests/test_vision_tables.py tests/test_document_groups.py tests/test_pdf_reader.py tests/test_pdf.py tests/test_regions.py tests/test_receipts.py tests/test_sampling.py tests/test_vision_batch.py tests/test_extraction.py tests/test_eval_tasks.py tests/test_bill_split.py -q`; plus every test file the slice edited and every test file that imports a shared helper it changed (command C-SL02 under the table; the stub move touches ~27 files); `grep -rn '"full_text"' tests scripts` lists only old-shape tests and the capture |
| SL-03 | FR-21, FR-22, FR-23, FR-24; SC-10 step 4, SC-12 step 3 (+e), SC-13 (+a–e), SC-14 | SL-02 | `documents/extraction.py`: `line_payload` at `:975`, `:1226`, `:1234`, `:1249`, `:2009`, `:2349`; FR-22 sentence in the receipt row instruction; backstop (P12) in `record`; `EXTRACTION_VERSION` v57 (P1). `tests/test_bill_account_holder.py:311`, `tests/test_bill_engine_record.py:248`, `tests/test_bill_printed_total.py:367` assert the new value. New `tests/test_receipt_side_lines.py`; `tests/test_vision_indent.py` gains SC-10 step 4 and SC-12 step 3/(e) (byte compare against `q56_*.json`, masking `row_instruction_v56.txt` and the new FR-22 text with one placeholder). | `.venv/bin/python -m pytest tests/test_receipt_side_lines.py tests/test_vision_indent.py tests/test_extraction.py tests/test_receipt_kinds.py tests/test_bill_account_holder.py tests/test_bill_engine_record.py tests/test_bill_printed_total.py tests/test_receipt_tax_codes.py tests/test_layout_consumers.py -q` |
| SL-04 | FR-01, FR-02, FR-03, FR-04, FR-05, FR-06, FR-07, FR-09; SC-01 steps 1–5, 8 (+a, b, d), SC-02 (+a), SC-03 (+a–d), SC-04 (+a–d), SC-06 (+a, b), SC-19; X-UPG. **Amounts, citations, review state, links and C-sum only:** every C-cat, "By category" and stored-item-category check in these scenarios (SC-01 steps 6, 8; SC-02 step 3; SC-03 step 2, (c), (d); SC-06 step 5) needs FR-10 and is added in SL-05 | SL-03 | New `documents/dining_total.py` (P4). `extraction.py` `record` (decision, `result["dining"]`), `publish` (FR-06 reason, `record["tip_worked_out"]`). `core/money.py` `amount_text` (P7). Migration `library/migrations/081_dining_receipts.sql` (P5). `finance/ledger.py`: `publish_receipt` writes `tip_worked_out_json`; `record()` payload `tip_note` (P6). `finance/document_traces.py` dining Tip label. The SL-04 test functions for SC-01 – SC-03 and SC-06 leave a marked place (`# SL-05: C-cat`) where SL-05 adds its checks. New `tests/test_dining_receipts.py` (these scenarios; unit tests of `dining_total.decide` for every rule branch incl. "Sub Total", "Grand Total", a table without heading, no tip line); `tests/test_migrations.py` X-UPG (old library builder in `dining_receipt_fixtures.py`). | `.venv/bin/python -m pytest tests/test_dining_receipts.py tests/test_migrations.py tests/test_receipt_kinds.py tests/test_reextraction.py tests/test_traces.py tests/test_receipt_discounts.py -q`; command C-SL04 under the table prints 0 (only `ALTER TABLE … ADD COLUMN`) |
| SL-05 | FR-08, FR-10, FR-11 (server), FR-12, FR-14 (a, c), FR-27, D18, D20; SC-01 steps 6–7 (+c) and the C-cat/category checks SL-04 left out (SC-01 step 8, SC-02 step 3, SC-03 step 2, (c), (d), SC-06 step 5), SC-05, SC-07 (+a–c), SC-09 steps 1–5, SC-16, SC-18 steps 1–4 (+a), X-D8 (all three cases), X-Q1 | SL-04 | `finance/splits.py` `allocate` (P8). `finance/ledger.py`: `shares` flag, `apply_one_category`, dining category at recording, `_replace_items` no memory on dining, `set_item_category` refusal, `_apply_correction` (c), `category_column` (P9), payload `category_column` and FR-27 `unmatched_minor` (P10). `finance/traces.py:211-214`: the split trace's server-made text says "a tip as dining"; it says "a tip and any difference under the receipt's category" when FR-10 has applied (D18). `extraction.py` `publish` (dining category). `tests/test_dining_receipts.py` grows. | `.venv/bin/python -m pytest tests/test_dining_receipts.py tests/test_spending_splits.py tests/test_family_routing.py tests/test_family_ledger.py tests/test_receipt_counting.py tests/test_receipt_item_table.py tests/test_receipt_kinds.py tests/test_bills_ledger.py -q` |
| SL-06 | FR-13, FR-14 (b, backfill), D27; SC-08 (+a, b), SC-17 (+a–c); plus a test from FR-13's criterion the contract doesn't spell out: SC-08 (a)'s verified grocery receipt changed to dining, then Undo → its receipt split equals the snapshot taken before the change (C-snap) | SL-05 | `finance/ledger.py`: reviewed kind-change branch and `_undo_kind` (P8 away/back, the Undo snapshot), `recategorise_items`. `finance/item_categories.py` dining rule (after the retired-category replacement; a dining receipt with no category uses dining). `tests/test_dining_receipts.py` grows. | `.venv/bin/python -m pytest tests/test_dining_receipts.py tests/test_receipt_kinds.py tests/test_spending_splits.py -q`; `tests/test_spending_splits.py` (already listed) holds today's backfill test (`test_receipts_recorded_before_item_categories_are_categorised_once`), so SC-17 (b) has a regression control |
| SL-07 | FR-28, FR-29, FR-30 (D34 – D41); SC-05 step 5 (link branch), SC-09 steps 6–7 (+a–c), SC-20 (+a–c), SC-21 (+a–d), SC-22 (a–f) | SL-06 | `finance/reconcile.py` `drop_stale_links` (P13); `finance/ledger.py` `publish_receipt` (before-values, call, second `refresh_paid`). New `tests/test_reread_links.py`; `tests/test_dining_receipts.py` grows. | `.venv/bin/python -m pytest tests/test_reread_links.py tests/test_dining_receipts.py tests/test_receipt_counting.py tests/test_reconcile_tools.py tests/test_fx.py tests/test_receipt_kinds.py tests/test_bills_ledger.py tests/test_reextraction.py tests/test_statement_accounts.py -q` |
| SL-08 | FR-11 (page), FR-26, FR-27 (page), FR-02 (page note); SC-07 step 1 (browser), SC-15, SC-18 (b) | SL-07 | `app/static/receipt.js` (filter Category by `record.category_column`; Tip note from `record.tip_note`), `app/static/trace.js` `renderLines` (`data-indent`), `style.css` (`.sv-line[data-indent="1"]`, `[data-indent="2"]` inline-start padding in token units). `tests/test_receipt_items_browser.py`, `tests/test_document_v2_browser.py` extended (seeds set `home_currency` USD). Screenshots: the extended browser tests save the breakfast receipt's document page and Text view at 1440 and 390 wide to `$UI_SHOTS_DIR` when it is set (the seed is the test's own `seed=` function; `tests/seed_household.py` is unchanged). Regression shots with the shared seed, before and after the slice's change: `.venv/bin/python .claude/skills/ui-redesign/scripts/ui_shots.py --routes "document/{receipt_doc}" --widths 390,1440 --out $SCRATCH/before-document` (and `after-document`). | `RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_receipt_items_browser.py tests/test_document_v2_browser.py -q`; `RUN_BROWSER_TESTS=1 UI_SHOTS_DIR=$SCRATCH/after .venv/bin/python -m pytest tests/test_receipt_items_browser.py tests/test_document_v2_browser.py -q -k "sc07 or sc15 or sc18"`; the `ui_shots.py` command beside |
| SL-09 | FR-25 | SL-08 | `docs/documents.md` ("Images (vision transcription)", "PDFs", "Several images as one document", "Receipt kinds"), `docs/money.md` ("Item categories and splits", "Reading a statement or receipt again", "Near matches and foreign receipts", "Gift cards" for D40), `docs/open-work.md` (D2's items, D16, stale bill/pay-stub links, link after Correct… on a total, re-read changing only date/merchant, lasting history entry; no Q2 entry; SC-19 outcome if it ever fails). Code comments added in SL-02 – SL-08 cite these headings. | Review of the doc diff against FR-25's list; `grep -rn 'docs/[a-z-]*\.md "' src` citations resolve to existing headings |

Commands kept out of the table (Markdown table cells can't hold a shell pipe):

```bash
# C-SL02: every test file SL-02 edited, plus every test file importing a shared helper it changed
{ git diff --name-only HEAD -- 'tests/test_*.py'
  grep -lE 'document_forms_fixtures|test_extraction import|receipt_item_fixtures|seed_documents' tests/test_*.py
} | sort -u | xargs .venv/bin/python -m pytest -q

# C-SL04: migration 081 rewrites nothing (prints 0)
grep -ciE '^[[:space:]]*(update|insert|delete|drop|create|replace)' src/home_manager/library/migrations/081_dining_receipts.sql
```

## Final verification
1. **Baseline (recorded, run by the planner at 66e97d5 before any change, 2026-11-14, Linux):**
   `.venv/bin/python -m pytest -q -p no:cacheprovider -rf -rE` gave **54 failed, 4366 passed, 121 skipped, 1 deselected,
   20 errors** (44 min). Every failing and erroring id is listed in `plans/dining-receipt-indent/baseline-failures.txt`.
   By file: `test_agent_instance.py` (7 failed, 20 errors in the agent-instance fixture),
   `test_agent_findings.py` 9, `test_agent_guards.py` 3, `test_engine_worksheets.py` 18, `test_tax_engines.py` 8 (the
   ones `docs/open-work.md` notes), `test_traces.py` 3 (tax-engine traces), `test_tax_year.py` 2, `test_tax_family.py`
   1, `test_tax_zen.py` 1, `test_cpa_pack.py` 1, `test_scenarios.py` 1. None is in an area this feature touches, but
   `tests/test_traces.py` is in SL-04's command: its three listed tax-trace failures are pre-existing, and any other
   failure in that file is the slice's.
2. **After SL-09, once:** `.venv/bin/python -m pytest -q -p no:cacheprovider -rf -rE` — the failing and erroring ids
   must be a subset of `baseline-failures.txt`. Then `RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_receipt_items_browser.py
   tests/test_document_v2_browser.py tests/test_browser.py tests/test_planned_bugfixes_browser.py -q`.
3. `.venv/bin/ruff check src tests`, and `git diff <SL-01 commit> HEAD -- tests/dining_receipt_data` is empty (the
   captures were never regenerated by the changed code, contract "Baseline captures").
4. Review checks (not tests): SC-12 (d) (`receipt_service.py` `:118` and `:192` use the same `GROUP_VERSIONS`), pay
   stubs (`publish_income` touches no link), FR-25 docs.

## Requirements & scenarios coverage matrix
| FR | Slice | Scenarios |
|---|---|---|
| FR-01 | SL-04 | SC-01, SC-03 (c, d), SC-04 (c, d), SC-19 |
| FR-02 | SL-04 (+ note SL-08) | SC-01, SC-03 (d), SC-04 (a) |
| FR-03 | SL-04 | SC-02 (+a), SC-03 (d), SC-06 |
| FR-04 | SL-04 | SC-03 |
| FR-05 | SL-04 | SC-04 (+a–d) |
| FR-06 | SL-04 | SC-01, SC-05, SC-09 |
| FR-07 | SL-04, SL-05 | SC-01 step 8, SC-07 step 5, X-D8 old-rules |
| FR-08 | SL-04 (migration), SL-05 | SC-05, SC-09, SC-16, SC-22 (a), X-D8, X-UPG |
| FR-09 | SL-04 | SC-06 |
| FR-10 | SL-05 | SC-01, SC-05, SC-07, SC-09, SC-16, X-D8 |
| FR-11 | SL-05, SL-08 | SC-07, SC-09, SC-16, SC-17 |
| FR-12 | SL-05 | SC-07, SC-09, SC-16 |
| FR-13 | SL-06 | SC-08, X-D8 old-rules |
| FR-14 | SL-05 (a, c), SL-06 (b, backfill) | SC-05, SC-07 (c), SC-09, SC-16, SC-17, X-D8, X-Q1 |
| FR-15 – FR-18 | SL-02 | SC-10, SC-11 |
| FR-19, FR-20 | SL-02 | SC-12 |
| FR-21 | SL-03 | SC-10 step 4, SC-12 step 3 (+e) |
| FR-22, FR-23 | SL-03 | SC-13, SC-14 |
| FR-24 | SL-03 | SC-05 |
| FR-25 | SL-09 | review |
| FR-26 | SL-02 (data), SL-08 | SC-15 |
| FR-27 | SL-05, SL-08 | SC-01 step 7, SC-03 (c, d), SC-07 step 3, SC-16, SC-18 |
| FR-28 – FR-30 | SL-07 | SC-05 step 5, SC-09 step 6, SC-20, SC-21, SC-22 |

Every SC (SC-01 – SC-22, X-D8, X-Q1, X-UPG) is owned by the slices above; a scenario spread over slices is completed by
the last slice listed for it (SC-01: SL-04/05; SC-05: SL-05/07; SC-09: SL-05/07; SC-18: SL-05/08).

## Test environments, data, stubs for nondeterministic components, final-state oracle
- Unit/integration: pytest with `tmp_path` libraries, `local_model` (`tests/conftest.py:125`, `tests/model_server.py`)
  answering vision through `output`/`outputs` and reasoning `by_schema`. Ledger-only checks through `Store`/`Ledger`;
  API through `create_app` + `TestClient`; re-reads through the manager's extraction job so the reconciliation after a
  published reading runs (contract "Re-reads go through the app's job path").
- Browser: opt-in `RUN_BROWSER_TESTS=1`, `tests/seed_documents.py` `document_server(seed=)`.
- Old library: built in `tests/dining_receipt_fixtures.py` by applying migrations below 081, inserting receipts A – H,
  charges and `parse_runs` whose `result_json` is the SL-01 capture (R6/P3/G2), then opening with the changed code. The
  builder also writes each old run's folder (`ReceiptService.folder(run_id)`) with the captured `result.json` (and, for
  P3, the page previews the v3 publish check reads), because `ReceiptService.publish` reads a page-based result from the
  folder, not from `result_json` (`receipt_service.py:118-133`; SC-12 (c) recovery).
- Oracle: the test contract's expected values (worked by hand there) and its shared checks C-sum, C-cat, C-snap, C-col,
  C-mem, C-review, C-cites, C-links, C-nosplit, C-note. Each scenario's P-check runs before its first checkpoint.
  Byte-identity (D28) compares against the SL-01 capture files, never against output of the changed code.
- Live model: only the user-run optional eval (contract "Evals"); not in pytest.

## Risks, unresolved decisions, alternatives
- **Size.** 30 FRs and 9 slices: the plan-feature guideline suggests splitting above ~10 FRs/~5 slices. Not split: the
  spec bundle is approved as one feature, and the slices are already separately verifiable and ordered by dependency.
- **SL-01 determinism.** If two capture runs differ (a timestamp or random id in a request body), D28 can't be met as
  written; the worker stops and reports it (a spec question, not a plan change).
- **Test-stub migration in SL-02** touches ~30 test files mechanically. Risk of changing an expectation by accident;
  the slice's grep check and the final suite comparison against the baseline contain it.
- **Recorded category of a dining receipt (P8)** becomes dining even when the description model says otherwise. This is
  the spec's FR-10 wording ("The receipt's category is dining when recorded"); a corrected category still wins.
- **P11** sends receipts with an FR-05 or FR-23 note to Review; the spec calls them notes but a receipt has nowhere
  else to keep one.
- **Undo of a kind change (P8)** restores the snapshot stored with the correction. An item a later reading added
  after the change isn't in it and keeps its category. Kind corrections made before the upgrade have no snapshot and
  fall back to the latest reading's categories (memory may have changed since); accepted, FR-13 says items get
  categories "as on any receipt".
- **Labels in the worked-out note** come from the printed label ("Bill", "Amount due"…); a receipt printing an unusual
  label form ("BILL TOTAL") still matches only if it starts with one of FR-01's labels.
- **Amount text (P7)** uses "$" only for USD; a CAD receipt's issue reads "61.55 CAD".
- Alternatives rejected: storing the tip row's identity in `category_splits` (would change C-snap'd rows and need a
  migration that rewrites nothing but still alters every row on the next rebuild); applying FR-10 in every rebuild
  (D8 forbids); doing the dining decision in `normalize` (the saved header would keep the model's citations, so
  C-cites and the trace would be wrong).
- No new dependencies.
