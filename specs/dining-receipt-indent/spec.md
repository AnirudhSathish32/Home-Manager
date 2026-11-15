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

Round 3 (user, 2026-11-14; not to be re-asked). The test contract's gaps (`test-contract.md` "Gaps", G1 – G13), decided:
- **D18 A dining receipt's tip and charge difference follow the receipt's category (G1, user's choice).** Once FR-10
  has applied to a dining receipt, its tip counts under the receipt's category, not always dining. This amends
  `docs/money.md` "Item categories and splits" rule 4. The receipt's category is dining unless you changed it, so an
  unchanged dining receipt counts exactly as today. Rule 5 follows the same reasoning (spec decision): on such a
  receipt, a positive difference between the amount divided and what the items and tip carry (a tip added after
  signing, an accepted near match) is an amount no item carries, under the receipt's category. Rationale: the user's
  intent is that a recategorised dining receipt counts wholly under the chosen category, and a tip at Travel while the
  leftover stays at Dining would split one meal across two categories for no reason. Keeping the difference as its own
  row, rather than spreading it over the items as rule 5 does today for a category other than dining
  (`splits.py:187-190`, where the test is `fallback == DINING`, the receipt's category), keeps "Not matched to an item" and every item's Paid
  the same whatever category you pick. The category totals are the same either way, since every item is in the
  receipt's category. Scope, consistent with D5 and D8: the rule is part of FR-10, so it applies only once FR-10 has
  applied to the receipt (FR-14), and stays through later rebuilds until the kind changes away from dining. Old dining
  receipts FR-10 hasn't applied to keep today's rules 4 and 5 (tip dining; difference dining when the receipt's
  category is dining, else spread), so no old receipt changes unprompted. Non-dining receipts are unchanged: tip dining
  (rule 4), difference by today's rule 5. FR-10, FR-07, FR-13, FR-25, SC-07.
- **D19 With no tip line, FR-01 still gives the charged total (G2, recommendation accepted).** FR-01 wins over FR-04's
  old wording. With no tip line and a later larger total, the total is the post-tip total ($61.55), the tip stays
  missing (D12), and the $8.79 is "Not matched to an item" (rule 5 on a dining receipt). FR-04, SC-03.
- **D20 Stored item categories once FR-10 applies (G3, accepted).** Items the model or memory categorised store the
  receipt's category with source `receipt`, as Edit details (`ledger.py:2580-2583`) and the backfill already do. Your
  own per-item choices (source `user`) stay stored. FR-10, SC-01, SC-09.
- **D21 The charge link after a re-read changes the total (G4, accepted). Superseded by D34 (round 5): the user
  reversed it; kept here as the record of the earlier decision.** The link follows today's rule
  (`docs/money.md` "Reading a statement or receipt again"): reading again replaces the record's lines and amounts but
  keeps the record and what is attached to it. `publish_receipt` never touches `transaction_receipt_links`
  (`ledger.py:752-811`), and reconciliation only links receipts that have no live link (`reconcile.py:405-407`). So the
  link stays, the charge's split is divided to the charge's amount as today (`ledger.py:1161-1164`), and no note is
  added (the "no longer equals the linked charge" note is for gift-card receipts only, `ledger.py:927-934`). SC-09.
  Whether to add such a note is Q2 below.
- **D22 After a total from the suggested-tip table is rejected, the code decides (G5, accepted).** The model is not
  asked again. The total is the nearest pre-tip amount printed before the table (FR-01's definition), cited to its
  line. With none, the total is missing, as for a receipt with no readable total today. FR-05.
- **D23 The nearest pre-tip amount (G6, accepted).** FR-01 compares the post-tip total with the nearest pre-tip amount
  before it in reading order, and FR-02 works out the tip from that one. When an earlier pre-tip amount disagrees with
  the nearest, FR-01 still gives the total, but no tip is worked out (which figure was the bill is unclear), with an
  issue (FR-01, FR-02). Spec decision for the disagreeing case: working out a tip from an ambiguous bill would invent
  a money figure.
- **D24 The old group reading version stays readable (G7, accepted).** Like `PDF_VERSIONS`, the old `GROUP_VERSION`
  value stays in the set of versions that open (e.g. a `GROUP_VERSIONS` tuple; `receipt_service.py:118` checks the
  group version by exact value today). FR-19, SC-12.
- **D25 Missing indent and the old answer shape (G8, accepted).** A line entry with no `indent` key is unknown, like a
  bad value. A `{full_text}`-only answer is invalid against the new schema, so the rescue runs (FR-18). FR-17.
- **D26 Correcting the tip (G9, G10, accepted).** The FR-06 Review reason goes when you correct the tip: today's
  correction rule resolves every issue whose text starts with the corrected field's label ("Tip", `ledger.py:168`,
  `:2565-2566`), and the FR-06 reason starts with "Tip", so its wording must keep that start. Corrections don't re-run
  checks (`Ledger.correct`, `ledger.py:2509-2534`): the footer calls out a difference over one cent
  (`totals_mismatch`, `ledger.py:2076-2078`), and no new FR-03 issue is added. Review follows today's rule: a receipt
  waiting in Review that you haven't reviewed is verified automatically when no issue remains. This corrects round 2's
  SC-06 ("the check issue names the gap"), which today's code doesn't do. FR-09, SC-06.
- **D27 The backfill and retired categories (G11, confirmed).** On a dining receipt the backfill gives every item it
  would categorise the receipt's category (after it replaces a retired receipt category, as today). For an item with no
  category that leaves its split unchanged. An item under a retired category moves from that category to the
  receipt's, as the backfill already moves such items today (only to the receipt's category instead of the model's or
  memory's answer). The backfill isn't one of FR-14's events, so it doesn't apply D18's tip and difference rule. FR-14,
  SC-17.
- **D28 What "today's request" means for an old reading (G12, G13, accepted).** For an old reading, every extraction
  request has a `lines` payload byte-identical to today's, and the rest of the request is identical apart from the
  row instruction FR-22 changes. The only faithful expected value is a capture from today's code, so the plan must
  schedule capturing today's requests (and the old-version readings they come from) before the first application
  change. FR-21, SC-12.

Round 4 (user, 2026-11-14; not to be re-asked). The test contract's round-2 gaps (`test-contract.md` "Gaps", G14 –
G18), the contract's recommended fixes accepted:
- **D29 The disagreeing-amounts issue lists the amounts in reading order (G14).** Earlier first: "The receipt prints
  different amounts before the tip ($52.76 and $50.00), so the tip wasn't worked out." for the breakfast receipt with
  line 22 reading "Bill: $50.00" (line 20 before line 22). FR-01, SC-03.
- **D30 Only FR-01's labels make a pre-tip amount (G15).** A printed total line, Bill, Amount due or Balance due. Any
  other label is not one, including a card-terminal "Amount:" line (line 6 of the breakfast receipt), so it never takes
  part in D23's comparison or D22's fallback. FR-01, FR-05, SC-04.
- **D31 The correction's footer warning is today's (G16).** Today's "Doesn't add up" warning names no amount
  (`receipt.js:423`, from `totals_mismatch`, `ledger.py:2077-2078`). FR-09 and SC-06 say the footer shows that warning;
  the $0.21 is the difference behind it, not text on the page. FR-09, SC-06.
- **D32 Both exact group-version checks accept the old value (G17).** FR-19.
- **D33 Old readings' extraction requests change nowhere else (G18).** FR-21.

Round 5 (user, 2026-11-14; not to be re-asked). The user reversed Q2 and D21: "i want q2 to be fixed in this session i
dont want the link to remain". D34 is the user's decision; D35 – D41 are the spec's decisions that make it precise, each
with its rationale, and approval of the spec covers them.
- **D34 A re-read removes a charge link its new total no longer supports (user; supersedes D21 and Q2's default).**
  When reading a receipt again changes its total so that its link to a charge no longer holds (D35), the link is
  removed: the charge and the receipt are both unlinked, and the reconciliation that follows every published reading
  (`app/manager.py:1621-1625`, `extract_and_file`) may link a matching charge or leave the receipt open. SC-09's old
  $52.76 link after Read again gives $61.55 is the case the user named. This is now in scope. FR-28 – FR-30, SC-09,
  SC-20 – SC-22.
- **D35 When a link still holds (spec decision).** The test is the one reconciliation uses to make that kind of link,
  applied to the receipt's new counted total (`total_minor`: the amount paid after gift cards, with your corrections,
  `refresh_paid`, `ledger.py:903-942`), and to the charge's amount:
  - **A link the app made** (`review_status` proposed) holds only at the **exact amount**, in the same currency.
    Reconciliation links automatically only at the exact amount (`reconcile.py:415-421`); a charge up to 30% larger is
    only ever a question (`:424-432`). So a proposed link whose charge is now larger than the total by a plausible tip is
    removed, and the near-match question can offer that charge again (D37).
  - **A link you confirmed or chose** (`review_status` verified: you approved a proposed link, `review_link`
    `reconcile.py:778`, or picked the charge in a question, `link_choice` `:271-277`) holds at the exact amount, or within
    the **near-match allowance**: same currency, a total above zero, and a charge larger than the total by at most 30%
    (`NEAR_PERCENT` 130, `reconcile.py:33`, `:429`: charge × 100 ≤ total × 130). A charge smaller than the total is never
    a tip, so it never holds. Rationale: a tip added after signing is the case the allowance exists for, and you had
    accepted such a pairing.
  - **A charge in another currency** (always a link you chose, `docs/money.md` "A foreign receipt and its USD card
    charge") holds when the charge is within 97 – 106% (`CROSS_RANGE`, `reconcile.py:36`) of the new total's estimate,
    at the rate stored on the link (`estimate_rate_id`), else at the rate reconciliation would look up now (`estimate`,
    `reconcile.py:310-319`). With no rate it doesn't hold: reconciliation can't make such a link without one (`:471-473`).
  - **No total** (the new reading has none): no link holds.
  - **Not re-tested:** the merchant and the posting window. Rationale: the user's concern is the total; the merchant test
    only narrows which charges a question offers, and a reading that changes the date or merchant is a different change
    (a `docs/open-work.md` entry, FR-25).
- **D36 Links you confirmed are removed too, with a note that says so (spec decision, the recommended default).** The
  user doesn't want the link to remain, and a link you confirmed was confirmed for the old total. So nothing disappears
  silently: the receipt goes to Review with a note naming the charge, its date, its amount and the new total, and saying
  the match was one you confirmed (FR-30).
- **D37 A removed link is not a rejection (spec decision, the recommended default).** It was removed because the receipt
  changed, not because you said the pair was wrong. The link's row is removed, not marked rejected, so the pair can be
  linked again when it matches again (exactly, or as a near-match question). Rejected links are rows of
  `transaction_receipt_links` with `review_status` rejected (there is no separate table); they are untouched, and only
  they keep a pair from being proposed again (`reconcile.py:408-409`). A question you answered "leave unmatched" stays
  answered (today's rule, `reconcile.py:237-241`).
- **D38 Every receipt kind; not bills, pay stubs or corrections (spec decision, the recommended default).** A stale link
  is wrong for any receipt, so FR-28 applies to every record recorded as a receipt, whatever its kind. Risk: a grocery or
  other receipt whose re-read misreads its total loses a link that was right; the note, Review and D37 (the pair is
  offered again once the total is fixed) contain it. Records recorded as bills (`document_kind` bill, which publish
  through the same `publish_receipt`, `ledger.py:1491-1518`) and pay stubs (`publish_income`, which touches no link) are
  unchanged; their payment and deposit links can go stale the same way, a `docs/open-work.md` entry. Correct… on a
  receipt's total is unchanged too (your own change; the gift-card note stays as today), also an open-work entry.
- **D39 Only when a reading rewrites the record and changes its total (spec decision).** A reading never rewrites a
  record you approved or rejected (`_upsert`, `ledger.py:731-743`), so its links stay; a kind change on a reviewed
  receipt keeps its amounts (`ledger.py:784-787`), so its links stay. FR-28 compares the counted total before and after
  the reading. When it is unchanged, nothing is tested, even for a link that wouldn't pass D35 (this reading didn't make
  it stale).
- **D40 The note lives with the receipt's issues (spec decision).** It stays until you review the receipt or a later
  reading replaces the issues, like every issue today. A lasting history entry for the removal is not built (an
  open-work entry). A removed link never gets the gift-card note "Amount paid (…) no longer equals the linked charge
  (…)" (`ledger.py:930-935`); that note stays for a link that still holds.
- **D41 After the removal (spec decision).** The charge's split rows for that receipt go, so the charge counts under its
  own category (`TRANSACTION_CATEGORY`, `ledger.py:85-94`, falls back from a linked receipt's category). A merchant the
  charge took from the receipt goes and its category and tax rules decide again, as when you reject a link
  (`reconcile.py:793-809`). The two documents no longer show each other as the same purchase (`link_documents`,
  `reconcile.py:811-821`), without that being marked rejected, unless another live link still joins them. The receipt's
  own split follows FR-10 and D18 as on any reading.

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
**Goal.** A restaurant receipt counts what was charged, including the tip, all under one category: dining, unless you
change the receipt's category (D18). Lines printed under an item stay with that item instead of becoming items of their
own.

**Users.** The household user reading a receipt on its document page, and every total that counts receipts:
category totals, budgets, Home, reconciliation with card charges, family shares.

**In scope.** The dining total and tip (FR-01 – FR-09). Dining categories (FR-10 – FR-14). Indentation in the vision
prompts and structured lines (FR-15 – FR-20). Indent in receipt extraction (FR-21 – FR-24). Docs (FR-25). Indentation
in the Text view (FR-26, D11). The footer's "Not matched to an item" without the tip (FR-27, D13). A re-read removes a
charge link its new total no longer supports, on every receipt kind (FR-28 – FR-30, D34 – D41).

**Non-goals.**
- D2's items.
- Bills, statements, pay stubs, investment documents and tax forms: their prompts may see indent in their line JSON
  (FR-21), but no rule of theirs uses it.
- Images read before this change, until they are read again (FR-19).
- Rewriting existing dining receipts' splits at upgrade, or by any migration (D5).
- Two copies of one dining receipt (already in `docs/open-work.md`).
- Stale links on bills and pay stubs, links after Correct… on a total, and a re-read that changes only the date or the
  merchant (D35, D38; open-work entries, FR-25).

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
- **Money rules 4 and 5 in code.** `allocate` adds the tip as a dining row no item carries (`splits.py:185-186`). A
  positive difference becomes a dining row only when the receipt's category is dining (`fallback == DINING`,
  `:187-189`); otherwise it is spread over the items.
- **Corrections** don't re-run checks. They resolve issues whose text starts with the field's label ("Tip",
  `ledger.py:168`, `:2565-2566`) and verify a receipt automatically when no issue remains and you haven't reviewed it
  (`Ledger.correct`, `ledger.py:2509-2534`).
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
  again", `_upsert` `ledger.py:731-743`). It keeps the record and its charge links (`publish_receipt` doesn't touch
  `transaction_receipt_links`, `ledger.py:752-811`), and reconciliation links only receipts with no live link
  (`reconcile.py:405-407`). A kind change re-reads from the saved transcription; on a reviewed receipt the amounts,
  items and review state stay (`docs/documents.md` "Receipt kinds", `app/manager.py:1567`). Bills publish through the
  same `publish_receipt` (`ledger.py:1491-1518`). After a published reading, reconciliation runs (`app/manager.py:1621-1625`).
  Only a gift-card receipt gets a note when its amount paid no longer equals the linked charge (`refresh_paid`,
  `ledger.py:927-934`). This round changes the link part (D34, FR-28).
- **Matching** (`reconcile.py:401-436`). A receipt is linked automatically (`proposed`) to a charge of its exact total,
  same currency, within the posting window (`RECEIPT_POSTING_DAYS`, 5 days), when it is the only candidate or clearly the
  best. With no exact charge, a same-merchant charge up to 30% larger (`NEAR_PERCENT` 130) becomes a near-match question,
  never a link; choosing it links the two as `verified` (`link_choice`, `:271-277`). A foreign receipt's USD charge
  within 97 – 106% of the ECB estimate is also only a question (`cross_currency`, `:467-482`). Approving a proposed link
  makes it `verified`; rejecting it keeps its row as `rejected`, takes away the merchant the charge got from the
  receipt and re-runs the charge's rules (`review_link`, `:778-809`), and a rejected pair is never proposed again
  (`:408-409`). A charge's category falls back to its linked receipt's (`TRANSACTION_CATEGORY`, `ledger.py:85-94`).
  Today the breakfast receipt ($52.76) against a $61.55 charge is a near-match question.
- `EXTRACTION_VERSION = "typed-extraction-v56-money-sign-rule"` (`extraction.py:52`). Extract again never reuses a run
  of an older version (`docs/documents.md:765`).
- **Unknowns.** How often vision models get indentation right on phone photos. Whether the real transcription printed
  Subtotal/Tax/Total on one line or three. How many existing dining receipts carry an item under another category
  (they keep the Category column until FR-14 applies, D6).

## Functional requirements
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-01 | On a dining receipt, a **pre-tip amount** is a printed total line (a line labelled Total or Grand Total with an amount, never Subtotal, Total Tax, Total Item Count or Total Savings) or a printed Bill, Amount due or Balance due line. Only these labels count (D30): a line with any other label, such as a card-terminal "Amount: $52.76", is never a pre-tip amount. A **post-tip total** is a printed total line larger than the **nearest pre-tip amount before it** in reading order (D23). The latest post-tip total counts, never a line of a suggested-tip table (FR-05). When there is one, the receipt's total is its amount, cited to its line, whether or not a tip line is printed (D19). Otherwise the total is read as today. When an earlier pre-tip amount before the post-tip total disagrees with the nearest one, the total still follows this rule, no tip is worked out (FR-02), and the issue "The receipt prints different amounts before the tip ($X and $Y), so the tip wasn't worked out." is added, where $X is the earliest pre-tip amount before the nearest one that disagrees with it, and $Y the nearest one, so the two read in reading order (D29). | Breakfast receipt, with the model answering total 52.76: the stored total is 6155, citing line 23, and the pre-tip amount is line 22 (Bill $52.76), not line 20 or line 6. With the model answering 61.55 citing line 23: the same. Line 22 reading "Bill: $50.00": total 6155, tip missing, and exactly the issue "The receipt prints different amounts before the tip ($52.76 and $50.00), so the tip wasn't worked out." |
| FR-02 | When FR-01 applies, the tip line is printed (D12), the pre-tip amounts before the post-tip total agree (D23), and the tip is missing or not used (blank, unreadable, cited only to a suggested-tip table, or failing its checks), the tip is **worked out** as post-tip total − the nearest pre-tip amount. It is stored as the tip, marked worked out (not printed), and cites both lines. The page shows Tip with "Worked out: Total $61.55 − Bill $52.76". The dining check's trace shows the tip as worked out from those two lines. | Breakfast receipt: `tip_minor` 879, marked worked out, citing lines 22 and 23. Footer Tip $8.79 with the worked-out note. The trace's Tip step names both lines. |
| FR-03 | When a tip is printed and read, it is kept as today. With a post-tip total, the dining check uses that total. Tip + pre-tip amount ≠ post-tip total adds the issue "Tip ($X) and the bill ($Y) don't make the total ($Z)." | Printed Tip: $8.79: tip 879, total 6155, no issue. Printed Tip: $5.00: tip 500 and the issue. |
| FR-04 | A tip is never invented: with one printed total, when the later total equals the pre-tip amount, or with no tip line printed (D12), the tip stays missing (never 0). With one printed total or equal totals, FR-01 doesn't apply and the total is read as today. With no tip line but a larger later total, FR-01 still gives the total (D19): the dining check reports the gap as today, and the difference is "Not matched to an item" (money rule 5 on a dining receipt). | Customer copy (Bill $52.76, Tip: $, Total: $ blank): total 5276, tip missing. Later total equal to bill: total 5276, tip missing. Breakfast receipt without line 24 (no tip line): total 6155 citing line 23, tip missing, no worked-out note, "Not matched to an item $8.79". |
| FR-05 | A **suggested-tip table** is a block of lines offering tip percentages ("18.00% of sale: $8.79 Total $61.55"), with or without a "Suggested Tip" or "Tip Guide" heading. It is never the source of the total or the tip. A total or tip the model cites only to such lines is not used, with the note "The {total or tip} the reading took from the suggested-tip table was not used." The model is not asked again (D22). A rejected total is replaced by FR-01's post-tip total when there is one, else by the nearest pre-tip amount printed before the table, cited to its line; with none, the total is missing. A rejected tip is missing, so FR-02 may work it out. | The model answers total 61.55 citing line 26 only: FR-01 still records 6155 from line 23, and the note is added. Without line 23: the total is 5276 citing line 22 (Bill), tip missing, and the note is added. Without line 23 and with lines 20 and 22 removed, line 6 ("Amount: $52.76") is not used (D30): the total is missing, and the note is added. |
| FR-06 | A worked-out tip enters the subtotal + tax + tip (+ gratuity) = total check like a printed one, and a passing check counts as a cross-check. A receipt with a worked-out tip goes to Review with "Tip $8.79 was worked out from Total $61.55 less Bill $52.76, not printed; check it." (D4). | Breakfast receipt: 4885 + 391 + 879 = 6155 passes. `review_status` is `needs_review` with that reason only. |
| FR-07 | Reconciliation uses the stored total: a card charge equal to the post-tip total links by exact amount. Money rule 5 (a difference between charge and receipt counts as dining on a dining receipt) is unchanged, except that on a dining receipt FR-10 has applied to it counts under the receipt's category (D18). Splits add up exactly to each charge. | Breakfast receipt and a $61.55 card charge: an exact link, no near-match question. Splits sum to 6155: all dining. |
| FR-08 | Receipts already recorded keep their total, tip, tax and splits until read again (Extract again, a kind change, a new reading) or changed by one of FR-14's events (D5). A record you approved or rejected is never rewritten by a reading (today's rule). No migration rewrites splits. | After the upgrade and a reconciliation run, existing receipts' `total_minor`, `tip_minor` and `category_splits` are unchanged. |
| FR-09 | Correcting Tip or Total with Correct… works as today, and a corrected tip replaces the worked-out tip and its marker. The FR-06 reason goes with it (D26: today's rule resolves issues starting with "Tip"). Checks are not re-run: a difference over one cent shows today's "Doesn't add up" warning in the footer, which names no amount (D31), and review follows today's correction rule (with no issue left, a receipt waiting in Review that you haven't reviewed is verified automatically). Later readings keep your correction. | Correct Tip to $9.00 on the breakfast receipt: tip 900, not marked worked out, no FR-06 reason, the footer shows today's "Doesn't add up" warning (the difference is $0.21; `totals_mismatch` true), `review_status` `verified` (automatic). Extract again keeps 900. |
| FR-10 | When it applies (FR-14), every item of a dining receipt counts under the **receipt's category**. Whatever the model, `item_category_memory`, an earlier reading or your per-item choice said about an item is not used for its split. Items the model or memory categorised store the receipt's category with source `receipt`; your per-item choices (source `user`) stay stored and are used again if the kind changes away from dining (FR-13) (D20). The tip, and a positive difference no item carries (money rule 5), also count under the receipt's category (D18), so the whole receipt counts under it. The receipt's category is dining when recorded, unless you corrected it (then yours wins, as today); with none, the tip counts as dining as today. | Breakfast receipt with the stub giving item_categories Groceries for two rows: every split row is dining, those items store dining with source `receipt`. The "By category" line reads "Dining $61.55". After Edit details → Categories → Travel: every split row, the tip's included, is travel, sum 6155. |
| FR-11 | A dining receipt's item table has no **Category** column, and the footer spans match the remaining columns, **only when every item's split counts under the receipt's category** (D6). The server decides and sends it with the receipt; the page only reads it (`docs/ui.md` "Screen rules"). The test is on the receipt's own split (`category_splits` rows with no charge, one per item): hidden when the receipt is dining and every such item row has the receipt's category. A receipt with no split yet (no total) is decided from the categories its split would use. An old dining receipt with any item under another category shows the column as today, with the dropdown. Other kinds keep the column. The receipt's category is changed with Edit details → Categories, and every item, the tip and any difference follow it (FR-14, D18). | Breakfast receipt recorded under v57: header Item, Qty, Unit price, Line total, Paid. A v56 dining receipt with a Groceries item: the column shows. After Read again, or after Edit details → Categories → Travel, it doesn't. A grocery receipt still shows Category. |
| FR-12 | When FR-11 hides the column, changing one item's category is refused (400, "Every item on a dining receipt counts as the receipt's category; change it with Edit details."), and nothing is written to `item_category_memory`. While the column shows (an old dining receipt FR-10 hasn't applied to), the PUT works as today, memory included (D7). Memory is never read for a dining receipt's items when FR-10 applies. | `PUT …/items/1/category` on the breakfast receipt → 400, no memory row. On a v56 dining receipt showing the column → 200, the item and memory updated as today. |
| FR-13 | After a kind change away from dining, the items get categories as on any receipt (memory, the model, an item's own earlier choice), and the tip and any difference follow today's rules 4 and 5 (tip dining). A kind change to dining applies FR-10 at once, on a reviewed receipt too (the change is yours, with Undo). | Dining → grocery: items take model or memory categories. Grocery → dining on a verified receipt: splits all in the receipt's category. Undo restores the earlier splits. |
| FR-14 | **When FR-10 applies** (D5, D8). It applies to a dining receipt when: (a) a reading of it is recorded (a new file, Extract again or Try again, a family-sent receipt), where the reading may rewrite the record (not one you approved or rejected); (b) its kind changes to dining (FR-13); (c) Edit details changes its Categories. Once applied, every later rebuild keeps it until the kind changes away from dining. It does not apply on the upgrade, or on rebuilds that aren't about categories: reconciliation runs, linking, unlinking or reviewing a charge, item deletion, Correct… on an amount or an item, other Edit details fields, family shares. Those rebuild from the items' stored categories, as today. The item-category backfill never gives an item of a dining receipt a category of its own: an item it would categorise takes the receipt's category (source `receipt`, "From the receipt's category"; after any replacement of a retired receipt category). That leaves the split unchanged for an item with none. An item under a retired category moves to the receipt's category (D27). The backfill isn't an FR-14 event, so the tip and difference keep today's rules on that receipt. | v56 dining receipt with a Groceries item: upgrade and reconcile, then link a card charge: the item's splits are still Groceries, each split sums to its charge. Read again: all dining. A later reconciliation run keeps all dining. A dining receipt with uncategorised items: the backfill leaves its splits unchanged. |
| FR-15 | Both vision prompts (the main one and the rescue) ask for each line with an **indent** of 0, 1 or 2. 0 is a line starting at the main left edge. 1 is a line printed further right, under the line above it (sides, modifiers, notes under an item). 2 is deeper. Centered headings and footers are 0. Indent is never for any other reason. Text has no leading spaces. | The prompt texts contain these rules (asserted on the request a stub receives). |
| FR-16 | The vision output schema replaces `full_text` with **`lines`: [{text, indent}]** (D9 covers the rescue). The app builds the full text by joining the lines' text with line breaks. Line ids (`line-N`, `page-P-line-N`), table `line_index`, `model_text`, `extracted_text`, search, citations and the Tables view keep today's forms. | A stub returning 28 lines gives `line-1`…`line-28` with the texts above, `model_text` equal to the joined text, and tables validating against the same indexes. |
| FR-17 | Each line keeps its indent with the reading. Lines from OCR, embedded-text PDF pages and readings saved before this change have no indent (unknown), are still read, and behave as today. An indent outside 0–2, one that isn't an integer, or a line entry with no `indent` key is stored as unknown for that line, and the reading is kept (D25). An answer in the old `{full_text}` shape is invalid and gets the rescue call (FR-18). A line text holding a line break becomes several lines with the same indent. All-blank lines fail as "Model response was blank." | An old `result.json` without indent loads. A stub with indent 5 on one line, or with no indent key on one line, stores that line's indent as unknown. A `{full_text}` main answer triggers the rescue. A stub line "A\nB" with indent 1 gives two lines, both indent 1. |
| FR-18 | The rescue call asks for `lines` [{text, indent}] with FR-15's rules and no tables (D9). If it also fails, the reading fails as today, without publishing or replacing an earlier reading. | Main stub invalid, rescue stub valid: the reading is kept with indent and the `vision_table_invalid` issue. Both invalid: the run fails, and the earlier reading stays. |
| FR-19 | `VISION_VERSION` becomes a new value (`receipt-vision-v7-indent`), and so do the PDF and combined-image reading versions (`PDF_VERSION`, `GROUP_VERSION`; D10), the old values kept readable: `PDF_VERSIONS` as today, and the old group value likewise (D24). Two places check the group version by exact value today, and both accept every group version, old and new (D32; e.g. a `GROUP_VERSIONS` tuple): `ReceiptService.publish` (`receipt_service.py:118`, `(*PDF_VERSIONS, GROUP_VERSION, "receipt-images-v1")`), which validates and stores a page-based result, also when startup recovery publishes an interrupted run (`recover`, `:254-263`); and `ReceiptService.run` (`:192`, `== GROUP_VERSION`), which transcribes a combined document page by page before publishing. So an old group run stays publishable as a combined result and never takes the single-image path. New runs are created only under the current versions (`:65`), so an old group run is never executed again, only published (by recovery); the `run` check is kept on the same set of group versions so the two never disagree. Earlier readings stay readable and selectable under History. A new reading is never served from a parse run of an older version. | Reading an image read under v6 again creates a new parse run under v7. A v6 image run, a `pdf-pages-v3-layout` run and a `receipt-images-v2-tables` run still open and extract. |
| FR-20 | Scanned (vision) PDF pages and the pages of a combined document keep each line's indent. Embedded-text pages have none. | A two-image combined document and a scanned PDF page from stubs carry indent on `page-1-line-N`. |
| FR-21 | The lines the extraction model receives carry `indent` beside `line_id` and `text`, only for lines whose indent is known. For a reading without indent, every extraction request's `lines` payload is byte-identical to today's, and the rest of the request is identical apart from the row instruction FR-22 changes (D28). The expected values are captured from today's code before any change (the plan schedules it). So, under D28, no other extraction prompt (the dining summary prompt included) may change for old readings, and `EXTRACTION_VERSION` never goes into a request body (D33). | Request JSON for the breakfast receipt has `"indent": 1` on lines 11–14 and 16. For an old reading, each request's `lines` is byte-identical to the capture, and the rest matches it except FR-22's instruction. |
| FR-22 | Every receipt form's row instruction says: a line indented under an item with no price of its own belongs to that item (cite it with the item) and is never an item. A priced indented line keeps today's rules (a count line belongs to its item; any other priced line is its own row). | The instruction text contains the rule (asserted on the request). |
| FR-23 | **Backstop.** On a receipt, an item whose cited lines all have indent ≥ 1, none printing an amount, and that has an item before it, is dropped. Its lines join the previous item's citation, with the note "“Fresh Berry Pancakes” is printed under “Georgia Peach Stack” with no price of its own, so it was kept with that item, not as an item." (one note per dropped line, at most three, then "and N more"). Not applied when the cited lines' indent is unknown. Bills and other kinds are unaffected. | Stub publishing the four side lines as $0/null items: 5 items stored (sum 4885). Georgia Peach Stack cites lines 10–14, and the notes are present. The same stub with no indent data: as today. |
| FR-24 | `EXTRACTION_VERSION` becomes v57. Extract again re-reads under it. | Extract again after the upgrade creates a new extraction run. |
| FR-25 | `docs/documents.md` "Images (vision transcription)" (lines, indent, the Text view's indentation), "PDFs" (vision pages), "Several images as one document" (indent kept) and "Receipt kinds" (dining total, worked-out tip and Review, suggested-tip table, side lines) describe the built behavior. `docs/money.md` "Item categories and splits" says when a dining receipt's items count as its category (FR-14), that older ones keep their categories and the Category column until then, when the item dropdown is refused, that "Not matched to an item" leaves out the tip (FR-27), and amends rules 4 and 5: on a dining receipt FR-10 has applied to, the tip and the difference count under the receipt's category (D18). "Receipt kinds" also covers the nearest pre-tip amount, which labels make a pre-tip amount, and the fallback after a rejected table total (D22, D23, D30). `docs/money.md` "Reading a statement or receipt again" and "Near matches and foreign receipts" describe FR-28 – FR-30 (when a re-read removes a link, the note, that it isn't a rejection). `docs/open-work.md` lists D2's items, D16 (tax among other amounts on one line), and from D35, D38 and D40: stale payment links on bills and deposit links on pay stubs after a re-read, a link after Correct… on a receipt's total, a re-read that changes only the date or merchant, and a lasting history entry for a removed link. The Q2 entry from round 4 is not added (Q2 is reversed, D34). | The doc sections match the built behavior; open-work has the entries and no Q2 entry. |
| FR-26 | (D11) The source viewer's Text view shows each line indented by its level. The text itself is unchanged, so copying and Find stay exact. | Text view of the breakfast receipt: lines 11–14 and 16 render one step in. Their text content equals the stored text. |
| FR-27 | (D13) The footer's "Not matched to an item" leaves out the tip; the Tip row shows it. The server sends the shown amount: the sum of the receipt's own split rows that carry no item (today's `unmatched_minor`), less the tip's own row in that split (the row `allocate` adds for the tip, `splits.py:185-186`). Its category is dining, or the receipt's category once FR-10 has applied (D18). That row is exactly `tip_minor` when the split is divided at the receipt's total, since `rounded` never moves a whole-unit value (`splits.py:39-45`); with a gift card or a family share it is the tip's resized share. The row is hidden when the result is zero. Display only: FR-27 itself changes no `category_splits` row, "By category", total or stored amount. | Breakfast receipt (items 4885, tax 391, tip 879, total 6155): no "Not matched to an item" row; By category "Dining $61.55". A printed-tip receipt with a $2.00 difference left over: "Not matched to an item $2.00", Tip shown on its own row. A v56 dining receipt with tax missed (total 5276, subtotal 4885, no tip): "Not matched to an item $3.91" as today. |
| FR-28 | (D34, D35, D38, D39) **A re-read removes a stale charge link.** When a reading of a receipt is recorded and rewrites the record (not one you approved or rejected; a new file, Extract again, Try again, a kind change on a receipt you haven't reviewed, a family-sent receipt), and its counted total (`total_minor`, after gift cards and your corrections) differs from before the reading, each live link (`proposed` or `verified`) between the receipt and a charge is tested against the new total. It holds: a proposed link only at the exact amount in the same currency; a verified link at the exact amount or when the charge is larger than a positive total by at most 30% (charge × 100 ≤ total × 130), same currency; a link to a charge in another currency when the charge is within 97 – 106% of the new total's estimate at the link's stored rate, else at the rate reconciliation would look up now, and never with no rate. With no total, nothing holds. A link that doesn't hold is removed (FR-29). The merchant and posting window aren't re-tested. Unchanged total, a record you reviewed, a record recorded as a bill, a pay stub, a failed reading and Correct… on a total remove nothing. Applies to every receipt kind. | SC-09: the proposed link to the $52.76 charge is removed after Read again gives 6155. A verified $10.00 link holds when a re-read gives $9.00 and is removed when it gives $7.00; a proposed $10.00 link is removed when it gives $9.00. Extract again with the same total keeps the link row (same id and status). An approved receipt, a bill and a failed reading keep their links. |
| FR-29 | (D37, D41) **What removing a link does.** The link's row is removed, not marked rejected; every rejected row stays as it was. The charge's split rows for the receipt go, so the charge counts under its own category. A merchant the charge took from the receipt goes, and its category and tax rules decide again, as on rejecting a link. The two documents no longer show each other as the same purchase (not marked rejected). The receipt's own split follows FR-10 and D18. All of this is part of the publication that records the new total. The reconciliation after the reading then runs as usual: it may link a charge of the new total, ask a near-match question (the removed charge included when it fits), or leave the receipt open; a question you answered "leave unmatched" stays answered. A removed pair can be linked again whenever it matches again. | SC-20: after Read again the receipt links the $61.55 charge exactly; the $52.76 charge has no link row and no split rows; the rejected row to the $60.00 charge is unchanged. Correct Total back to $52.76 (without the $61.55 charge) links the $52.76 charge again. |
| FR-30 | (D36, D40) **The note.** Each removed link adds one issue to the receipt, and the receipt waits in Review (`needs_review`): "The match to the $52.76 charge on 2026-11-12 was removed: this reading's total ($61.55) no longer matches it." For a link you confirmed or chose: "The match you confirmed to the $52.76 charge on 2026-11-12 was removed: this reading's total ($61.55) no longer matches it." With no total: "… was removed: this reading has no total." The charge's amount and the counted total are magnitudes, written as FR-01's issue writes amounts; the date is the charge's transaction date, else its posted date, as YYYY-MM-DD. The note stays until you review the receipt or a later reading replaces the issues. A removed link gets no gift-card "Amount paid (…) no longer equals the linked charge (…)" note. | SC-09: C's reasons are exactly the FR-06 reason and the first note. SC-20: the "you confirmed" note. SC-21 (d): the gift-card receipt has the note naming $8.00 and no "Amount paid (" note. |

## Invariants, privacy, security and data retention
- Per-category shares of a receipt or a charge add up exactly to it (`splits.py`). The page calculates nothing: the
  worked-out tip, its note, the splits, whether the Category column shows (FR-11) and the "Not matched to an item"
  amount (FR-27) come from the server ("money from the server", `docs/ui.md` "Screen rules").
- No migration and no upgrade step rewrites `category_splits` (D5). Only FR-14's events change which category a dining
  receipt's items count under.
- A charge link is never removed silently: each removal adds FR-30's note and puts the receipt in Review. A removal is
  never recorded as a rejection, and no rejected link is changed (D37).
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
- A failed extraction leaves the earlier record, its tip, splits and charge links as they were. A link is removed only
  in the same publication that records the new total (FR-28), so a crash before it commits leaves both as they were.
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
| SC-01 | FR-01, FR-02, FR-06, FR-07, FR-10 | Empty synthetic library. The vision stub returns the breakfast receipt with indent. The extraction stub gives total 52.76 (line 20), tip missing, tax 3.91, subtotal 48.85, five items with model categories Groceries for two | Record; import a $61.55 card charge on 11/12/26; reconcile | total 6155, tip 879 worked out (lines 22, 23), cross-check passes, `needs_review` with the FR-06 reason only. Exact link to the charge. Splits all dining, sum 6155. Every item stores dining with source `receipt` (D20) |
| SC-02 | FR-03 | The SC-01 stub with "Tip: $8.79" printed and read | Record | tip 879 printed (not worked out), total 6155, no tip issue, verified automatically |
| SC-03 | FR-04, FR-01 | Customer copy: lines 1–22 and "Tip: $", "Total: $" (blank). Variant: the breakfast receipt without line 24 (no tip line). Variant: line 22 reads "Bill: $50.00" | Record each | Customer copy: total 5276, tip missing (not 0), no worked-out note. No tip line: total 6155 citing line 23, tip missing, no worked-out note, the dining check's gap issue as today, "Not matched to an item $8.79" (D19). Bill $50.00: total 6155, tip missing, the issue "The receipt prints different amounts before the tip ($52.76 and $50.00), so the tip wasn't worked out." (D23, D29) |
| SC-04 | FR-05, FR-01 | SC-01 without line 23; the model's total cites line 26. Variant: also without lines 20 and 22 (line 6 "Amount: $52.76" kept) | Record each | total 5276 citing line 22 (Bill), no second model call, tip missing, suggested-table note (D22). Variant: total missing (line 6 is not a pre-tip amount, D30), the note |
| SC-05 | FR-08, FR-14, FR-24, FR-28 | A library with dining receipts recorded under v56 (total 5276), one approved by the user, and a $52.76 card charge | Upgrade; run reconciliation; Extract again on both | After upgrade and reconciliation, every `category_splits` row is unchanged. After Extract again, the approved one is unchanged, its link included. The other becomes total 6155 and tip 879, under a v57 extraction run, with all splits dining; if it held the link to the charge, that link is removed with FR-30's note |
| SC-06 | FR-09 | SC-01 recorded | Correct Tip to $9.00; Extract again | tip 900, not worked out. The FR-06 reason is gone; no new issue (checks aren't re-run); the footer shows today's "Doesn't add up" warning (the difference is $0.21) (D31); verified automatically (D26). Extract again keeps 900 |
| SC-07 | FR-10, FR-11, FR-12 | SC-01 recorded | Open the document page; PUT an item category; Edit details → Categories → Travel | No Category column (the payload says so). PUT → 400, no memory row. All splits travel, the tip row included (D18), sum 6155; By category "Travel $61.55"; still no column |
| SC-08 | FR-13 | SC-01 recorded and approved | Change kind to grocery; Undo; change to dining again | Grocery: items take memory or model categories. Each change rebuilds splits; Undo restores them; sums constant |
| SC-09 | FR-08, FR-11, FR-12, FR-14, FR-28, FR-29, FR-30 | A v56 library: a dining receipt waiting in Review (total 5276), one item set to Groceries by the user and one by the model, linked to no charge; a $52.76 card charge | Upgrade; open the page; reconcile (links the charge); PUT a third item to Groceries; Read again | Before Read again: the Category column shows; the two Groceries items' splits stay Groceries on the receipt and on the charge, each sum unchanged; the PUT → 200 and writes memory as today. After Read again: no column, every split dining, the user's stored item choices still there, the model's item stores dining with source `receipt` (D20). The link to the $52.76 charge is removed (D34; it was proposed and 6155 ≠ 5276): no link row joins them, none is rejected, the charge has no split rows, and the receipt's reasons are the FR-06 reason and "The match to the $52.76 charge on 2026-11-12 was removed: this reading's total ($61.55) no longer matches it." The reconciliation after the reading links nothing and asks nothing (the charge is smaller than the total). A further reconciliation run keeps every split dining and the receipt unlinked |
| SC-10 | FR-15, FR-16, FR-17, FR-21 | Vision stub with 28 lines, indents as in the table, one indent 5, one line containing a line break | Read the image; record | Line ids continuous, the broken line split, the indent-5 line unknown. The extraction request carries indent where known |
| SC-11 | FR-18 | Main vision stub invalid; rescue stub returns lines with indent | Read the image | Reading kept with indent and `vision_table_invalid`. With both invalid, the run fails and the earlier reading stays |
| SC-12 | FR-19, FR-20, FR-21 | Image, scanned-PDF and combined-image readings under the old versions, and today's extraction requests for them captured before any change (D28) | Read each again | New parse runs under the new versions with indent; old runs, the old combined one included (D24), still open and extract, with `lines` byte-identical to the capture and the rest identical apart from FR-22's instruction |
| SC-13 | FR-22, FR-23 | The SC-01 stub, but rows publish the four side lines as null-price items | Record | 5 items, sum 4885. Georgia Peach Stack cites lines 10–14. Notes for the dropped lines |
| SC-14 | FR-23 | SC-13's rows over a reading with no indent | Record | 9 items, as today, no drop notes |
| SC-15 | FR-26 | SC-01 recorded | Open the Text view | Lines 11–14 and 16 indented one level; text unchanged |
| SC-16 | FR-11, FR-12, FR-14 | A v56 dining receipt you approved, with one item under Groceries | Read again; open the page; Edit details → Categories → Travel; PUT an item category | After Read again: unchanged (approved), the column still shows. After Categories → Travel: every split travel, no column, the PUT → 400 |
| SC-17 | FR-14 | A v56 dining receipt whose items have no category (backfill pending) and a model stub that would answer Groceries | Run the item-category backfill | Items take the receipt's category, source `receipt`; `category_splits` unchanged; no column. Variant: an item under a retired category moves to the receipt's category, its split with it (D27) |
| SC-18 | FR-27 | SC-01 recorded; a printed-tip receipt with $2.00 left over; a v56 dining receipt with tax missed | Open each document page | Breakfast: no "Not matched to an item" row. Printed tip: Tip and "Not matched to an item $2.00". v56: "Not matched to an item $3.91". `category_splits` identical before and after FR-27 |
| SC-19 | FR-01 (D14) | The breakfast receipt; the several-receipts stub answers "one receipt" | Record | One receipt, total 6155. Characterization only: no rule change |
| SC-20 | FR-28, FR-29, FR-30 | SC-09's v56 library with a $52.76 charge, a $61.55 charge, and a $60.00 charge whose link to the receipt you rejected | Reconcile (links the $52.76 charge); approve that link; Read again | The link you confirmed is removed with "The match you confirmed to the $52.76 charge on 2026-11-12 was removed: this reading's total ($61.55) no longer matches it."; the reconciliation after the reading links the $61.55 charge exactly (proposed), its split all dining, sum 6155; the $52.76 charge has no link row and no split rows; the rejected row to the $60.00 charge is unchanged. Variant without the $61.55 charge: Correct Total to $52.76 → the $52.76 charge is linked again (not a rejection, D37) |
| SC-21 | FR-28, FR-29, FR-30 | A grocery receipt (SYNTH MART, total $10.00) and a $10.00 card charge from SYNTH MART | Record and reconcile (exact, proposed); Extract again with the same total; Extract again reading $9.00; choose the charge in the near-match question; Extract again reading $10.00, then $9.00, then $7.00 | Same total: the link row unchanged, no note. $9.00 with the proposed link: removed with the note, then a near-match question offering the $10.00 charge. After you choose it: $10.00 and $9.00 keep the link you chose (exact; within the 30% allowance), no note. $7.00: removed with the "you confirmed" note (10.00 is more than 30% above 7.00), no question. Variants: a gift-card receipt (removal note names the amount paid, no "Amount paid (" note); a foreign receipt linked to a USD charge (kept within 97 – 106% of the estimate at the stored rate, removed outside it) |
| SC-22 | FR-28 (D38, D39) | Each independent: an approved dining receipt linked to a $52.76 charge; SC-09 after the link; a bill linked to its payment; a reviewed receipt linked to a charge | Extract again; Try again that fails; read the bill again with a different amount; change the reviewed receipt's kind; Correct… the total of a linked receipt | Every link row unchanged (same id and status), no removal note, no charge split changed by the rule |

`design-tests` is recommended before approval. SC-01, SC-05, SC-08, SC-09, SC-12, SC-16, SC-17, SC-20 and SC-21 are
stateful: they cover stored splits, review state, parse and extraction runs, the upgrade, reconciliation rebuilds, the
backfill and charge links across re-reads.

Trace (FR → SC): FR-01 SC-01, SC-03, SC-04, SC-19 · FR-02 SC-01 · FR-03 SC-02 · FR-04 SC-03 · FR-05 SC-04 · FR-06 SC-01 ·
FR-07 SC-01 · FR-08 SC-05, SC-09 · FR-09 SC-06 · FR-10 SC-01, SC-07, SC-09 · FR-11 SC-07, SC-09, SC-16 · FR-12 SC-07, SC-09,
SC-16 · FR-13 SC-08 · FR-14 SC-05, SC-09, SC-16, SC-17 · FR-15–FR-17 SC-10 · FR-18 SC-11 · FR-19, FR-20 SC-12 ·
FR-21 SC-10, SC-12 · FR-22 SC-13 · FR-23 SC-13, SC-14 · FR-24 SC-05 · FR-25 doc review · FR-26 SC-15 · FR-27 SC-18 ·
FR-28 SC-05, SC-09, SC-20, SC-21, SC-22 · FR-29 SC-09, SC-20, SC-21 · FR-30 SC-09, SC-20, SC-21.

## Out of scope / product decisions requiring approval
All round-1 open decisions (OD-1 – OD-6) and risk candidates (R1 – R5) are decided: D4 – D17 above. The test
contract's gaps G1 – G13 are decided: D18 – D28, and G14 – G18: D29 – D33. Round 5's reversal of Q2 is decided:
D34 – D41.

Q1 takes its recommended default, accepted by the user (tested in `test-contract.md` X-Q1). Q2's default was accepted
in round 4 and reversed by the user in round 5 (D34): it is now in scope as FR-28 – FR-30. Nothing in this spec is open.
- **Q1 Edit details with the same category (default accepted).** FR-14 (c) applies FR-10 when Categories *changes*. An old dining receipt
  whose category is already dining gets FR-10 only by Read again, a kind change, or setting each item through the
  dropdown (D7). Decided: leave it so. Read again is the documented way, and the dropdown covers an approved receipt.
- **Q2 A note when a re-read total no longer equals the linked charge (from D21). Reversed in round 5 (D34).** Round 4
  accepted the default (keep the link as today, with an open-work entry). The user reversed it: the link must not
  remain. FR-28 – FR-30 replace it, and no open-work entry for Q2 is added (FR-25).

Round 5 risk pass (FR-28 – FR-30). Each candidate is settled by a decision above, so none is open:
- **R6 A misread re-read drops a right link** (a grocery total misread on Try again). Contained by the note and Review
  (D36), and by D37: the pair is offered again once the total is right. Accepted risk (D38).
- **R7 A link you confirmed disappears.** Removed per the user's words, never silently (D36, FR-30).
- **R8 The same staleness on bills, pay stubs and Correct… on a total.** Out of scope, open-work entries (D38, FR-25).
- **R9 A re-read that moves the date or merchant out of the match.** Not re-tested, open-work entry (D35).
- **R10 The note lost on a later reading.** Accepted (D40); a lasting history entry is an open-work entry.
