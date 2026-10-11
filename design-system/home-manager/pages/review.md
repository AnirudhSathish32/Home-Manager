# To check (Phase 2)

These are the page overrides for To check v2 (`src/home_manager/app/static/review_v2.js`, route `#/review`). MASTER.md
wins wherever this file says nothing. The hand-off is `../phase2-review-document-plan.md` (Build B).

**The user's job:** decide each item the app isn't sure of, with the evidence in view. That means confirming a match or
record, or rejecting or correcting it.

## Components (from MASTER "Components")
- **Queue:**
  - Group titles are `--text-xs`, semibold, secondary, with a count pill.
  - Entries are 36px rows that ellipsize, with the full text in `title=`.
  - The selected entry is `--accent-subtle` with a 3px `--accent` left bar and `aria-current="true"`.
- **Source viewer:** `sourceViewer()` in the middle column.
  - Source text is mono 11.5px on `--surface-sunken`.
  - The selected line is `--warning-subtle` with a 1px `--warning` outline.
  - Images sit on `--paper`.
- **Item column:**
  - The position ("3 of 12"), an h2 for *what*, and the *why* (the reason only, never a repeat of the title).
  - Issues show as a needs-attention row on `--warning-subtle`.
- **Evidence cards:** Charge | Receipt are two side-by-side blocks with `--radius-md`, a `--border` outline and no
  fill. A lone evidence block has no outline; blocks are divided by a `--border` rule.
  - **Deviation:** this is the one allowed nesting, because comparing two records needs the pairing.
- **Decision bar:** `confirmCorrect()` for records, assets, tax forms and confirmations; plain buttons for the other
  kinds.
  - Confirm is the one primary. Reject is secondary, not danger, because it's reversible with an 8s Undo. Correct… is
    secondary.
  - Labels keep the " (V)" / " (R)" suffix.
- **`.source-card`:** used for warranties ("Found online") and tax tables. A quote is a blockquote, and URLs are mono
  text, never links.

## Layout (from MASTER "Layout")
- **1440:** `260px | minmax(0,1fr) | minmax(340px,400px)`, gap `--space-4`.
  - Each column is sticky with `max-height: calc(100vh - var(--review2-top))` (140px at ≥820, 120px under) and
    scrolls inside itself.
  - The item column is a flex column: head, `.review2-scroll`, then `#review2-bar`.
  - When the breakdown is open at ≥1180, the item column narrows to `minmax(320px,360px)`.
- **Under 1180:** the queue becomes `#review2-picker` (a select with an optgroup per group) plus Prev/Next, above two
  columns; `--review2-top` becomes 192px for the picker's row.
- **Under 900:** one column (picker, item, source at 60vh), with `#review2-bar` fixed to the viewport bottom.
- **390:** the bar's buttons wrap to two lines.
- **Decision in view:** `#review2-confirm` ends at y ≤ 768 at 1366×768.

## States
- **Middle column by kind:**
  - document kinds: the document with the evidence lit;
  - link: the receipt, with a chip for the charge's statement;
  - group: the first page with page chips;
  - tax_tag: the target's document, or a "Bank line" card;
  - item: the receipt line;
  - warranty and tax_table: `.source-card`;
  - otherwise "This has no document."
- **Empty:** "Nothing needs you. New documents show here after they're read."
- **Loading, error and no library** come from `pageState`.
- **A failed decision** shows an inline alert above the bar, and the item stays selected.
- **Family view:** "Who is it for?" replaces "Receipts with no matching charge", and the preview is off.
- **URL:** `#/review?item=<reviewKey>`.
