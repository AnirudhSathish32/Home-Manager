# Dining receipts: the charged total and tip, one category, and indented lines from the vision reading
Feature: dining-receipt-indent

<!-- Approval state lives in approvals/<slug>.json and is bound to this file's content hash.
     Do not add a Status line: changing it would change the hash. Check with gate.py. -->

Amends: `specs/document-forms` (FR-08, the dining check and the blank-tip rule) and `specs/receipt-item-table` (FR-01,
the item table's columns). No earlier spec covers the vision reading's line structure. The baseline is the built
behavior in `docs/documents.md` "Images (vision transcription)" and "Receipt kinds", `docs/money.md` "Item categories
and splits", and the code cited below.

## Decisions already made (user, 2026-11-14; not to be re-asked)
- **D1 Scope.** Four parts: (1) a dining receipt's charged total and tip; (2) every item on a dining receipt is dining,
  with no per-item Category; (3) the vision prompts ask for discrete indentation levels; (4) the vision JSON carries
  structured lines `{text, indent}`, and receipt extraction uses indent so unpriced side lines stay with their item.
- **D2 Out of scope.** OCR engines and word positions for images; Bottled Water collapsing to quantity 1; arithmetic
  cross-checks that catch misread digits (suggested-tip % × subtotal); the printed "Total Item Count" check.
- **D3 Text stays unindented.** Indent is data beside the text, never leading spaces added to it. Exact-quote
  citations, `count_lines`, regexes and table-cell substring checks see the same text as today.

Round 2 (user, 2026-11-14; not to be re-asked). The round-1 open decisions and risk candidates, decided:
- **D4 Worked-out tip goes to Review (OD-1, default accepted).** A receipt with a worked-out tip always goes to Review
  with FR-06's reason, even when the check passes. It is a money figure that isn't printed.
- **D5 Only new readings (OD-2, alternative chosen).** Existing dining receipts are not rebuilt at upgrade, and no
  migration rewrites splits. FR-10 applies only on the events in FR-14. The round-1 upgrade rebuild (old FR-14) and its
  scenario (old SC-09) are removed.
- **D6 Keep the Category column until FR-10 has applied (user, consequence of D5).** A dining receipt hides the column
  only when every item's split counts under the receipt's category. An old dining receipt with any item under another
  category keeps the column, as today, so nothing wrong is hidden (FR-11).
- **D7 One item's category can be changed while the column shows (spec decision, round 2).** FR-12's refusal applies
  exactly when the column is hidden. On an old dining receipt still showing the column, the dropdown works as today
  (memory written). Rationale: a visible control that always answers 400 is a dead control. The dropdown is also the
  user's way to fix an old receipt one item at a time without reading it again. Once every item is under the
  receipt's category, the column hides and the refusal starts, so the two never disagree.
- **D8 Incidental rebuilds don't apply FR-10 (spec decision, round 2).** Splits are rebuilt from the items' stored
  categories on many events that aren't about categories. Reconciliation rebuilds every receipt's splits on every run
  (`finance/reconcile.py:214`, `refresh_splits(db)`), and also on each link and link review (`reconcile.py:330`,
  `:797`). If those rebuilds applied FR-10, the first reconciliation after the upgrade would rewrite every old dining
  receipt, which is the rebuild D5 rejected. So FR-10 applies only on the events in FR-14, and every other rebuild uses
  the categories as stored. Once FR-10 has applied to a receipt, later rebuilds keep it, until the kind changes away
  from dining.
- **D9 The rescue asks for lines with indent (OD-3, default accepted).** FR-18.
- **D10 All three reading versions change (OD-4, accepted).** `VISION_VERSION`, `PDF_VERSION` and `GROUP_VERSION`
  (FR-19).
- **D11 Indentation shows in the Text view (OD-5, accepted).** FR-26.
- **D12 A tip is worked out only when a tip line is printed (OD-6, accepted).** FR-02, FR-04.
- **D13 The footer doesn't list the tip twice (R1, accepted as FR-27).**
- **D14 Several total lines (R2).** A characterization test only (SC-19): a stubbed "one receipt" answer keeps the
  breakfast receipt whole. No rule change. If it splits in practice, it goes to open-work.
- **D15 A blank Total line filled from the suggested-tip table (R3).** Covered by D4 (Review) and a matched card
  charge. No extra rule.
- **D16 Tax printed among other amounts on one line (R4).** Out of scope, with a `docs/open-work.md` entry beside D2's
  digit checks (FR-25).
- **D17 Priced indented lines stay items (R5).** A priced line indented under an item stays its own item (FR-22). Only
  unpriced ones are backstopped (FR-23).

Background (user report, 2026-11-14). A phone photo of a restaurant receipt was read as below (shape kept, details
made up). The side lines (Fresh Berry Pancakes, Veggie Sausage, Jalapeno Cheese Grits, No Allergies) are printed
indented under their main item, but the transcription lost the indentation:

```
Gacha's Breakfast Bar / address / Order #: 179580 / Server: Crimson H / Date: 11/12/26, 10:31 AM
(card terminal block ... Amount: $52.76)
Bottled Water $3.95 · Bottled Water $3.95 · Coffee $14.95 · Georgia Peach Stack $18.70
No Allergies · Fresh Berry Pancakes · Veggie Sausage · Jalapeno Cheese Grits · No Allergies
Better Than No Y'all Biscuits (3) $4.25 · Total Item Count: 6
Subtotal: $49.85   Total Tax: $3.91   Total: $52.76 · Paid With: VISA CARDHOLDER
Bill: $52.76 · Total: $61.55 · Tip: $
Suggested Tip 18.00% of sale: $8.97 Total $61.55 / 20.00% ... $62.53 / 22.1% ... $63.61
```

What was recorded: total $52.76 (the charged total is the last one, $61.55), no tip, no tax, "Not matched to an item
$2.91", and a Category dropdown on each item, with the three side lines as $0 Groceries items. The digit misreads
(the real subtotal is $48.85) are out of scope (D2).

**Synthetic receipt used by every scenario ("the breakfast receipt").** Consistent made-up amounts, in reading
order, with indent levels where the vision reading gives them:

| # | Text | Indent |
|---|---|---|
| 1–5 | Gacha's Breakfast Bar · 12 Peach St · Order #: 179580 · Server: Crimson H · Date: 11/12/26, 10:31 AM | 0 |
| 6 | Amount: $52.76 | 0 |
| 7–9 | Bottled Water $3.95 · Bottled Water $3.95 · Coffee $14.95 | 0 |
| 10 | Georgia Peach Stack $18.70 | 0 |
| 11–14 | No Allergies · Fresh Berry Pancakes · Veggie Sausage · Jalapeno Cheese Grits | 1 |
| 15 | Better Than No Y'all Biscuits (3) $7.30 | 0 |
| 16 | No Allergies | 1 |
| 17–20 | Total Item Count: 6 · Subtotal: $48.85 · Total Tax: $3.91 · Total: $52.76 | 0 |
| 21–23 | Paid With: VISA CARDHOLDER · Bill: $52.76 · Total: $61.55 | 0 |
| 24 | Tip: $ | 0 |
| 25–28 | Suggested Tip · 18.00% of sale: $8.79 Total $61.55 · 20.00% of sale: $9.77 Total $62.53 · 22.00% of sale: $10.75 Total $63.51 | 0 |

Items 48.85, tax 3.91, bill 52.76, tip (worked out) 8.79, charged total 61.55.

## Goal / users / scope / non-goals
**Goal.** A restaurant receipt counts what was charged, including the tip, all as dining. Lines printed under an item
stay with that item instead of becoming items of their own.

**Users.** The household user reading a receipt on its document page, and every total that counts receipts:
category totals, budgets, Home, reconciliation with card charges, family shares.

**In scope.** The dining total and tip (FR-01 – FR-09). Dining categories (FR-10 – FR-14). Indentation in the vision
prompts and structured lines (FR-15 – FR-20). Indent in receipt extraction (FR-21 – FR-24). Docs (FR-25). Indentation
in the Text view (FR-26, D11). The footer's "Not matched to an item" without the tip (FR-27, D13).

**Non-goals.**
- D2's items.
- Bills, statements, pay stubs, investment documents and tax forms: their prompts may see indent in their line JSON
  (FR-21), but no rule of theirs uses it.
- Images read before this change, until they are read again (FR-19).
- Rewriting existing dining receipts' splits at upgrade, or by any migration (D5).
- Two copies of one dining receipt (already in `docs/open-work.md`).

## Existing behavior (verified)
- **The vision reading** returns `{full_text, tables}` (`models/vision.py:130-162`). The prompt asks for line breaks
  and `|` table cells, and nothing about indentation. The one rescue call asks for `{full_text}` only
  (`vision.py:170-173`). Lines are `full_text.split("\n")` with nothing stripped, so leading spaces would survive, but
  none are asked for (`vision.py:191`, `:217`). `VISION_VERSION = "receipt-vision-v6-tables"` (`vision.py:20`) is the
  image reading's parse-run key (`documents/receipt_service.py:65`).
- **Scanned PDF pages and combined images** call the same `transcribe` (`documents/pdf_reader.py:85`), under
  `PDF_VERSION = "pdf-pages-v3-layout"` and `GROUP_VERSION = "receipt-images-v2-tables"` (`pdf_reader.py:14-17`). A
  parse run is reused when its parser version and options match (`receipt_service.py:65-78`). The options hold the
  vision config, not the prompt version. `combine_pages` rebuilds each `TextLine` from id and text only
  (`pdf_reader.py:116-117`).
- **A line** is `TextLine{id, text, block_ids}` on a strict model with no extra keys (`documents/receipt_schema.py:14-28`).
  A vision result requires `model_text == "\n".join(line.text)` (`receipt_schema.py:146-150`). Extraction gets lines
  through `evidence_lines` (`documents/layout_context.py:42-45`), and the source viewer gets `line.model_dump()`
  (`layout_context.py:69`).
- **The extraction model** receives `{"lines": [{"line_id", "text"}]}` (`documents/extraction.py:2349`). Receipt rows
  are asked for chunk by chunk (`extraction.py:4397`, `chunks`). The receipt row instruction (`extraction.py:4383-4392`)
  covers two-line items and count lines under an item, but not unpriced side lines. Dining adds only "A tip, gratuity
  or service charge is never an item" (`extraction.py:547`).
- **Dining summary.** The dining form asks for "tip: only a tip amount written or printed on the tip line, missing when
  that line is blank" (`extraction.py:539-541`). Nothing tells the model which of several printed totals is the charged
  one. `document_checks.dining` (`finance/document_checks.py:52-66`) checks subtotal + tax + tip + gratuity = total
  only when subtotal, tax and total are present. An unprinted tip adds nothing. When there is no gratuity,
  `unprinted_amounts` (`extraction.py:2716-2752`) works out a missing tax only when a line naming tax ends with exactly
  the gap. Otherwise it adds an issue.
- **Why $2.91 was "Not matched to an item".** With total 52.76, subtotal 49.85 and no tax, `allocate` spreads the
  subtotal over the items. The remaining difference (2.91) on a receipt whose category is dining becomes an amount no
  item carries (`finance/splits.py:185-189`). The page lists amounts no item carries as "Not matched to an item"
  (`finance/ledger.py:2074`, `app/static/receipt.js:401`). **A tip is also such an amount** (`splits.py:185-186`), so
  a printed tip appears both as Tip and as "Not matched to an item" (`ledger.py:2074-2075` sums every no-item row; not run; FR-27).
- **Several totals.** `looks_like_several` treats more than one total line with a digit as a sign that the file may
  hold several receipts. That asks the model where each receipt starts (`extraction.py:2104-2106`, `:5102`). The
  breakfast receipt has five total lines.
- **Splits are rebuilt from stored categories.** `Ledger.refresh_splits` (`finance/ledger.py:1151-1166`) deletes and
  rebuilds a receipt's `category_splits` from `split_inputs`, whose items carry their stored `category`. `allocate`
  uses `item.get("category") or fallback`, and the fallback is the receipt's category (`splits.py:194`,
  `ledger.py:1212-1216`). Callers include recording a reading, item deletion (`ledger.py:1131`), the per-item PUT
  (`:1238`), Edit details (`:2586`), every reconciliation run for all receipts (`finance/reconcile.py:214`), each
  receipt link and link review (`reconcile.py:330`, `:797`), family routing (`finance/family_routing.py:135`, `:390`)
  and the item-category backfill (`finance/item_categories.py:82`).
- **Item categories.** The description model gives `item_categories` (`extraction.py:664-672`, applied at `:4673-4674`).
  At recording, the seller's remembered choice in `item_category_memory` wins, then the model's. A matched item's own
  choice outlives a new reading (`ledger.py:1079-1093`). The item dropdown (`receipt.js:125-140`) calls
  `PUT /api/receipts/{id}/items/{position}/category` (`ledger.py:1224-1239`), which also writes memory. Edit details →
  Categories sets every item not categorised by you (`ledger.py:2580-2583`). The Category column is always shown on a
  receipt (`receipt.js:305-306`, `:356`). The backfill `finance/item_categories.py` categorises older receipts' items
  with the same model question: receipts whose items have no category, or a retired one (`item_categories.py:28-35`),
  from memory, then the model (`:60-73`). Today it would give a dining receipt's items categories of their own.
- **The footer's "Not matched to an item"** is `unmatched_minor`, the sum of the receipt's own split rows
  (`transaction_id IS NULL`) that carry no item (`ledger.py:2074-2075`). Those rows are every amount `allocate` puts in
  `extra`: the tip as its own dining row (`splits.py:185-186`), a positive difference on a dining receipt
  (`:188-189`), and any amount whose weights give no proportion (`:170-172`). The page shows the row when the value
  isn't zero (`receipt.js:401-402`).
- **Reading again** never rewrites a record you approved or rejected (`docs/money.md` "Reading a statement or receipt
  again"). A kind change re-reads from the saved transcription; on a reviewed receipt the amounts, items and review
  state stay (`docs/documents.md` "Receipt kinds", `app/manager.py:1567`).
- **Matching.** A receipt is linked to a card charge of its exact total. A charge up to 30% larger becomes a near-match
  question (`docs/money.md` "Near matches and foreign receipts"). Today the breakfast receipt ($52.76) against a
  $61.55 charge is such a question.
- `EXTRACTION_VERSION = "typed-extraction-v56-money-sign-rule"` (`extraction.py:52`). Extract again never reuses a run
  of an older version (`docs/documents.md:765`).
- **Unknowns.** How often vision models get indentation right on phone photos. Whether the real transcription printed
  Subtotal/Tax/Total on one line or three. How many existing dining receipts carry an item under another category
  (they keep the Category column until FR-14 applies, D6).

## Functional requirements
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-01 | On a dining receipt, a **post-tip total** is a printed total line that comes after a **pre-tip amount** (an earlier printed total, or a printed Bill, Amount due or Balance due line) and is larger than it. The latest such line in reading order counts, never a line of a suggested-tip table (FR-05). When there is one, the receipt's total is its amount, cited to its line. Otherwise the total is read as today. | Breakfast receipt, with the model answering total 52.76: the stored total is 6155, citing line 23. With the model answering 61.55 citing line 23: the same. |
| FR-02 | When FR-01 applies, the tip line is printed (D12), and the tip is missing or not used (blank, unreadable or failing its checks), the tip is **worked out** as post-tip total − pre-tip amount. It is stored as the tip, marked worked out (not printed), and cites both lines. The page shows Tip with "Worked out: Total $61.55 − Bill $52.76". The dining check's trace shows the tip as worked out from those two lines. | Breakfast receipt: `tip_minor` 879, marked worked out, citing lines 22 and 23. Footer Tip $8.79 with the worked-out note. The trace's Tip step names both lines. |
| FR-03 | When a tip is printed and read, it is kept as today. With a post-tip total, the dining check uses that total. Tip + pre-tip amount ≠ post-tip total adds the issue "Tip ($X) and the bill ($Y) don't make the total ($Z)." | Printed Tip: $8.79: tip 879, total 6155, no issue. Printed Tip: $5.00: tip 500 and the issue. |
| FR-04 | A tip is never invented: with one printed total, with no tip line, or when the later total equals the pre-tip amount, the tip stays missing (never 0) and the total is read as today. | Customer copy (Bill $52.76, Tip: $, Total: $ blank): total 5276, tip missing. Later total equal to bill: tip missing. |
| FR-05 | A **suggested-tip table** is a block of lines offering tip percentages ("18.00% of sale: $8.79 Total $61.55"), with or without a "Suggested Tip" or "Tip Guide" heading. It is never the source of the total or the tip. A total or tip the model cites only to such lines is not used, with the note "The {total or tip} the reading took from the suggested-tip table was not used." | The model answers total 61.55 citing line 26 only: FR-01 still records 6155 from line 23. Without line 23, the total is 5276 and the note is added. |
| FR-06 | A worked-out tip enters the subtotal + tax + tip (+ gratuity) = total check like a printed one, and a passing check counts as a cross-check. A receipt with a worked-out tip goes to Review with "Tip $8.79 was worked out from Total $61.55 less Bill $52.76, not printed; check it." (D4). | Breakfast receipt: 4885 + 391 + 879 = 6155 passes. `review_status` is `needs_review` with that reason only. |
| FR-07 | Reconciliation uses the stored total: a card charge equal to the post-tip total links by exact amount. Money rule 5 (a difference between charge and receipt counts as dining on a dining receipt) is unchanged. Splits add up exactly to each charge. | Breakfast receipt and a $61.55 card charge: an exact link, no near-match question. Splits sum to 6155: all dining. |
| FR-08 | Receipts already recorded keep their total, tip, tax and splits until read again (Extract again, a kind change, a new reading) or changed by one of FR-14's events (D5). A record you approved or rejected is never rewritten by a reading (today's rule). No migration rewrites splits. | After the upgrade and a reconciliation run, existing receipts' `total_minor`, `tip_minor` and `category_splits` are unchanged. |
| FR-09 | Correcting Tip or Total with Correct… works as today, and a corrected tip replaces the worked-out tip and its marker. Later readings keep your correction. | Correct Tip to $9.00: tip 900, not marked worked out. Extract again keeps 900. |
| FR-10 | When it applies (FR-14), every item of a dining receipt counts under the **receipt's category**. Whatever the model, `item_category_memory`, an earlier reading or your per-item choice said about an item is not used for its split. Your per-item choice stays stored and is used again if the kind changes away from dining (FR-13). The receipt's category is dining when recorded, unless you corrected it (then yours wins, as today). | Breakfast receipt with the stub giving item_categories Groceries for three rows: every item split is dining. The "By category" line reads "Dining $61.55". |
| FR-11 | A dining receipt's item table has no **Category** column, and the footer spans match the remaining columns, **only when every item's split counts under the receipt's category** (D6). The server decides and sends it with the receipt; the page only reads it (`docs/ui.md` "Screen rules"). The test is on the receipt's own split (`category_splits` rows with no charge, one per item): hidden when the receipt is dining and every such item row has the receipt's category. A receipt with no split yet (no total) is decided from the categories its split would use. An old dining receipt with any item under another category shows the column as today, with the dropdown. Other kinds keep the column. The receipt's category is changed with Edit details → Categories, and every item follows it (FR-14). | Breakfast receipt recorded under v57: header Item, Qty, Unit price, Line total, Paid. A v56 dining receipt with a Groceries item: the column shows. After Read again, or after Edit details → Categories → Travel, it doesn't. A grocery receipt still shows Category. |
| FR-12 | When FR-11 hides the column, changing one item's category is refused (400, "Every item on a dining receipt counts as the receipt's category; change it with Edit details."), and nothing is written to `item_category_memory`. While the column shows (an old dining receipt FR-10 hasn't applied to), the PUT works as today, memory included (D7). Memory is never read for a dining receipt's items when FR-10 applies. | `PUT …/items/1/category` on the breakfast receipt → 400, no memory row. On a v56 dining receipt showing the column → 200, the item and memory updated as today. |
| FR-13 | After a kind change away from dining, the items get categories as on any receipt (memory, the model, an item's own earlier choice). A kind change to dining applies FR-10 at once, on a reviewed receipt too (the change is yours, with Undo). | Dining → grocery: items take model or memory categories. Grocery → dining on a verified receipt: splits all in the receipt's category. Undo restores the earlier splits. |
| FR-14 | **When FR-10 applies** (D5, D8). It applies to a dining receipt when: (a) a reading of it is recorded (a new file, Extract again or Try again, a family-sent receipt), where the reading may rewrite the record (not one you approved or rejected); (b) its kind changes to dining (FR-13); (c) Edit details changes its Categories. Once applied, every later rebuild keeps it until the kind changes away from dining. It does not apply on the upgrade, or on rebuilds that aren't about categories: reconciliation runs, linking, unlinking or reviewing a charge, item deletion, Correct… on an amount or an item, other Edit details fields, family shares. Those rebuild from the items' stored categories, as today. The item-category backfill never gives an item of a dining receipt a category of its own: an item it would categorise takes the receipt's category (source "From the receipt's category"), which leaves the split unchanged for an item with none. | v56 dining receipt with a Groceries item: upgrade and reconcile, then link a card charge: the item's splits are still Groceries, each split sums to its charge. Read again: all dining. A later reconciliation run keeps all dining. A dining receipt with uncategorised items: the backfill leaves its splits unchanged. |
| FR-15 | Both vision prompts (the main one and the rescue) ask for each line with an **indent** of 0, 1 or 2. 0 is a line starting at the main left edge. 1 is a line printed further right, under the line above it (sides, modifiers, notes under an item). 2 is deeper. Centered headings and footers are 0. Indent is never for any other reason. Text has no leading spaces. | The prompt texts contain these rules (asserted on the request a stub receives). |
| FR-16 | The vision output schema replaces `full_text` with **`lines`: [{text, indent}]** (D9 covers the rescue). The app builds the full text by joining the lines' text with line breaks. Line ids (`line-N`, `page-P-line-N`), table `line_index`, `model_text`, `extracted_text`, search, citations and the Tables view keep today's forms. | A stub returning 28 lines gives `line-1`…`line-28` with the texts above, `model_text` equal to the joined text, and tables validating against the same indexes. |
| FR-17 | Each line keeps its indent with the reading. Lines from OCR, embedded-text PDF pages and readings saved before this change have no indent (unknown), are still read, and behave as today. An indent outside 0–2, or one that isn't an integer, is stored as unknown for that line, and the reading is kept. A line text holding a line break becomes several lines with the same indent. All-blank lines fail as "Model response was blank." | An old `result.json` without indent loads. A stub with indent 5 on one line stores that line's indent as unknown. A stub line "A\nB" with indent 1 gives two lines, both indent 1. |
| FR-18 | The rescue call asks for `lines` [{text, indent}] with FR-15's rules and no tables (D9). If it also fails, the reading fails as today, without publishing or replacing an earlier reading. | Main stub invalid, rescue stub valid: the reading is kept with indent and the `vision_table_invalid` issue. Both invalid: the run fails, and the earlier reading stays. |
| FR-19 | `VISION_VERSION` becomes a new value (`receipt-vision-v7-indent`), and so do the PDF and combined-image reading versions (`PDF_VERSION`, `GROUP_VERSION`; D10), the old values kept readable (`PDF_VERSIONS`, `receipt_service.py:118`). Earlier readings stay readable and selectable under History. A new reading is never served from a parse run of an older version. | Reading an image read under v6 again creates a new parse run under v7. A v6 run still opens and extracts. |
| FR-20 | Scanned (vision) PDF pages and the pages of a combined document keep each line's indent. Embedded-text pages have none. | A two-image combined document and a scanned PDF page from stubs carry indent on `page-1-line-N`. |
| FR-21 | The lines the extraction model receives carry `indent` beside `line_id` and `text`, only for lines whose indent is known. A reading without indent sends exactly today's payload. | Request JSON for the breakfast receipt has `"indent": 1` on lines 11–14 and 16. For an old reading it is byte-identical to today's. |
| FR-22 | Every receipt form's row instruction says: a line indented under an item with no price of its own belongs to that item (cite it with the item) and is never an item. A priced indented line keeps today's rules (a count line belongs to its item; any other priced line is its own row). | The instruction text contains the rule (asserted on the request). |
| FR-23 | **Backstop.** On a receipt, an item whose cited lines all have indent ≥ 1, none printing an amount, and that has an item before it, is dropped. Its lines join the previous item's citation, with the note "“Fresh Berry Pancakes” is printed under “Georgia Peach Stack” with no price of its own, so it was kept with that item, not as an item." (one note per dropped line, at most three, then "and N more"). Not applied when the cited lines' indent is unknown. Bills and other kinds are unaffected. | Stub publishing the four side lines as $0/null items: 5 items stored (sum 4885). Georgia Peach Stack cites lines 10–14, and the notes are present. The same stub with no indent data: as today. |
| FR-24 | `EXTRACTION_VERSION` becomes v57. Extract again re-reads under it. | Extract again after the upgrade creates a new extraction run. |
| FR-25 | `docs/documents.md` "Images (vision transcription)" (lines, indent, the Text view's indentation), "PDFs" (vision pages), "Several images as one document" (indent kept) and "Receipt kinds" (dining total, worked-out tip and Review, suggested-tip table, side lines) describe the built behavior. `docs/money.md` "Item categories and splits" says when a dining receipt's items count as its category (FR-14), that older ones keep their categories and the Category column until then, when the item dropdown is refused, and that "Not matched to an item" leaves out the tip (FR-27). `docs/open-work.md` lists D2's items and D16 (tax among other amounts on one line). | The doc sections match the built behavior; open-work has the entries. |
| FR-26 | (D11) The source viewer's Text view shows each line indented by its level. The text itself is unchanged, so copying and Find stay exact. | Text view of the breakfast receipt: lines 11–14 and 16 render one step in. Their text content equals the stored text. |
| FR-27 | (D13) The footer's "Not matched to an item" leaves out the tip; the Tip row shows it. The server sends the shown amount: the sum of the receipt's own split rows that carry no item (today's `unmatched_minor`), less the tip's own row in that split (the row `allocate` adds for the tip, `splits.py:185-186`). That row is exactly `tip_minor` when the split is divided at the receipt's total, since `rounded` never moves a whole-unit value (`splits.py:39-45`); with a gift card or a family share it is the tip's resized share. The row is hidden when the result is zero. Display only: `category_splits`, "By category", every total and every stored amount are unchanged. | Breakfast receipt (items 4885, tax 391, tip 879, total 6155): no "Not matched to an item" row; By category "Dining $61.55". A printed-tip receipt with a $2.00 difference left over: "Not matched to an item $2.00", Tip shown on its own row. A v56 dining receipt with tax missed (total 5276, subtotal 4885, no tip): "Not matched to an item $3.91" as today. |

## Invariants, privacy, security and data retention
- Per-category shares of a receipt or a charge add up exactly to it (`splits.py`). The page calculates nothing: the
  worked-out tip, its note, the splits, whether the Category column shows (FR-11) and the "Not matched to an item"
  amount (FR-27) come from the server ("money from the server", `docs/ui.md` "Screen rules").
- No migration and no upgrade step rewrites `category_splits` (D5). Only FR-14's events change which category a dining
  receipt's items count under.
- Every stored amount cites its source lines. A worked-out tip cites both totals ("source beside the record").
- The model proposes, the code decides. The post-tip total, the worked-out tip, the suggested-tip exclusion and the
  side-line backstop are deterministic rules over the transcription.
- Saved readings are never rewritten. New fields are optional, so every saved `result.json` still validates.
- Nothing new leaves the machine. Prompts change; the endpoints and the data sent (the image, the line text) are as
  today, plus the indent numbers.
- Tests use the synthetic breakfast receipt and stubs only. Nothing under P:\Finances, %LOCALAPPDATA%\HomeManager or
  P:\EvalCorpus is read.

## Errors, recovery, duplicates, restart behavior
- Vision output that fails validation gets the one rescue call, then fails as today (FR-18). A bad indent never fails
  a reading (FR-17).
- An unreadable post-tip total (no amount on the line) means FR-01 doesn't apply, and today's behavior holds.
- A failed extraction leaves the earlier record, its tip and splits as they were.
- Reading the same image twice under the same version reuses the parse run as today. A new version makes one new run,
  not one per page or call.
- Splits rebuild on every change, as today, so a restart changes nothing. Nothing runs at upgrade (D5). Whether FR-10
  has applied to a receipt survives restarts and later rebuilds (FR-14), so a reconciliation run never undoes it.

## Nondeterministic outputs and how they are verified
- Every FR is tested with fixed stub responses: the vision stub returns `lines` with indent, and the extraction stub
  returns the summary and rows. No exact output from a live model is expected.
- The prompt texts are asserted on the request the stub receives (FR-15, FR-18, FR-22).
- An optional live check on the agent test instance, with a synthetic image of the breakfast receipt, which the user
  runs: lines 11–14 come back with indent ≥ 1, the total is 61.55 and no side line is an item. Only presence and these
  values are checked.

## Scenarios
| ID | FR IDs | Initial state | User/API actions | Expected final DB/files/UI state |
|---|---|---|---|---|
| SC-01 | FR-01, FR-02, FR-06, FR-07, FR-10 | Empty synthetic library. The vision stub returns the breakfast receipt with indent. The extraction stub gives total 52.76 (line 20), tip missing, tax 3.91, subtotal 48.85, five items with model categories Groceries for two | Record; import a $61.55 card charge on 11/12/26; reconcile | total 6155, tip 879 worked out (lines 22, 23), cross-check passes, `needs_review` with the FR-06 reason only. Exact link to the charge. Splits all dining, sum 6155 |
| SC-02 | FR-03 | The SC-01 stub with "Tip: $8.79" printed and read | Record | tip 879 printed (not worked out), total 6155, no tip issue, verified automatically |
| SC-03 | FR-04 | Customer copy: lines 1–22 and "Tip: $", "Total: $" (blank) | Record | total 5276, tip missing (not 0), no worked-out note |
| SC-04 | FR-05 | SC-01 without line 23; the model's total cites line 26 | Record | total 5276, tip missing, suggested-table note |
| SC-05 | FR-08, FR-14, FR-24 | A library with dining receipts recorded under v56 (total 5276), one approved by the user | Upgrade; run reconciliation; Extract again on both | After upgrade and reconciliation, every `category_splits` row is unchanged. After Extract again, the approved one is unchanged. The other becomes total 6155 and tip 879, under a v57 extraction run, with all splits dining |
| SC-06 | FR-09 | SC-01 recorded | Correct Tip to $9.00; Extract again | tip 900, not worked out. The check issue names the gap. Extract again keeps 900 |
| SC-07 | FR-10, FR-11, FR-12 | SC-01 recorded | Open the document page; PUT an item category; Edit details → Categories → Travel | No Category column (the payload says so). PUT → 400, no memory row. All splits travel, sum 6155, still no column |
| SC-08 | FR-13 | SC-01 recorded and approved | Change kind to grocery; Undo; change to dining again | Grocery: items take memory or model categories. Each change rebuilds splits; Undo restores them; sums constant |
| SC-09 | FR-08, FR-11, FR-12, FR-14 | A v56 library: a dining receipt waiting in Review (total 5276), one item set to Groceries by the user and one by the model, linked to no charge; a $52.76 card charge | Upgrade; open the page; reconcile (links the charge); PUT a third item to Groceries; Read again | Before Read again: the Category column shows; the two Groceries items' splits stay Groceries on the receipt and on the charge, each sum unchanged; the PUT → 200 and writes memory as today. After Read again: no column, every split dining, the user's stored item choices still there. A further reconciliation run keeps every split dining |
| SC-10 | FR-15, FR-16, FR-17, FR-21 | Vision stub with 28 lines, indents as in the table, one indent 5, one line containing a line break | Read the image; record | Line ids continuous, the broken line split, the indent-5 line unknown. The extraction request carries indent where known |
| SC-11 | FR-18 | Main vision stub invalid; rescue stub returns lines with indent | Read the image | Reading kept with indent and `vision_table_invalid`. With both invalid, the run fails and the earlier reading stays |
| SC-12 | FR-19, FR-20 | Image and scanned-PDF readings under the old versions | Read both again | New parse runs under the new versions with indent; old runs still open and extract (no indent, today's payload) |
| SC-13 | FR-22, FR-23 | The SC-01 stub, but rows publish the four side lines as null-price items | Record | 5 items, sum 4885. Georgia Peach Stack cites lines 10–14. Notes for the dropped lines |
| SC-14 | FR-23 | SC-13's rows over a reading with no indent | Record | 9 items, as today, no drop notes |
| SC-15 | FR-26 | SC-01 recorded | Open the Text view | Lines 11–14 and 16 indented one level; text unchanged |
| SC-16 | FR-11, FR-12, FR-14 | A v56 dining receipt you approved, with one item under Groceries | Read again; open the page; Edit details → Categories → Travel; PUT an item category | After Read again: unchanged (approved), the column still shows. After Categories → Travel: every split travel, no column, the PUT → 400 |
| SC-17 | FR-14 | A v56 dining receipt whose items have no category (backfill pending) and a model stub that would answer Groceries | Run the item-category backfill | Items take the receipt's category, source "receipt"; `category_splits` unchanged; no column |
| SC-18 | FR-27 | SC-01 recorded; a printed-tip receipt with $2.00 left over; a v56 dining receipt with tax missed | Open each document page | Breakfast: no "Not matched to an item" row. Printed tip: Tip and "Not matched to an item $2.00". v56: "Not matched to an item $3.91". `category_splits` identical before and after the change |
| SC-19 | FR-01 (D14) | The breakfast receipt; the several-receipts stub answers "one receipt" | Record | One receipt, total 6155. Characterization only: no rule change |

`design-tests` is recommended before approval. SC-01, SC-05, SC-08, SC-09, SC-12, SC-16 and SC-17 are stateful: they
cover stored splits, review state, parse and extraction runs, the upgrade, reconciliation rebuilds and the backfill.

Trace (FR → SC): FR-01 SC-01, SC-04, SC-19 · FR-02 SC-01 · FR-03 SC-02 · FR-04 SC-03 · FR-05 SC-04 · FR-06 SC-01 ·
FR-07 SC-01 · FR-08 SC-05, SC-09 · FR-09 SC-06 · FR-10 SC-01, SC-07 · FR-11 SC-07, SC-09, SC-16 · FR-12 SC-07, SC-09,
SC-16 · FR-13 SC-08 · FR-14 SC-05, SC-09, SC-16, SC-17 · FR-15–FR-17 SC-10 · FR-18 SC-11 · FR-19, FR-20 SC-12 ·
FR-21 SC-10 · FR-22 SC-13 · FR-23 SC-13, SC-14 · FR-24 SC-05 · FR-25 doc review · FR-26 SC-15 · FR-27 SC-18.

## Out of scope / product decisions requiring approval
All round-1 open decisions (OD-1 – OD-6) and risk candidates (R1 – R5) are decided: D4 – D17 above.

Still open (small, with recommended defaults; none blocks planning):
- **Q1 Edit details with the same category.** FR-14 (c) applies FR-10 when Categories *changes*. An old dining receipt
  whose category is already dining gets FR-10 only by Read again, a kind change, or setting each item through the
  dropdown (D7). Default: leave it so. Read again is the documented way, and the dropdown covers an approved receipt.
