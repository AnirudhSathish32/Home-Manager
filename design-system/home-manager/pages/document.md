# The document page (Phase 2)

These are the page overrides for the document page v2 (`src/home_manager/app/static/document_v2.js`, route
`#/documents/ID`). MASTER.md wins wherever this file says nothing. The hand-off is `../phase2-review-document-plan.md`
(Build A).

**The user's job:** check a record against its source, correct what the model got wrong, and see what changed and who
changed it.

## Components (from MASTER "Components")
- **Source viewer:** `sourceViewer()` in the left column, with the source text and highlight styling as on To check.
- **Record header** (`#doc2-header`): sticky at the top of the record column, on `--surface` with a `--border` bottom.
  It holds:
  - the record title (`--text-lg`) and its `statusBadge`;
  - the steps strip (Read → Recorded, with ✓/⟳/✕/⚠ icons and a visually hidden state word);
  - the one next action;
  - the *why* as a needs-attention row;
  - the decision, `confirmCorrect()`.
  - The Correct form opens inside the header. Its preview list is capped at 40vh and scrolls inside itself.
- **Tabs:** Record · History · Details. The URL keeps `?tab=`.
- **Record rows:** `dl.doc2-fields`. Each row has a label (`--text-xs` secondary) and a value (`--text-sm`). A
  corrected field adds `provenanceBadge` (override). Find and Correct are text links.
  - Every category shows as a tag, largest share first.
  - "Counts as" and "Counts in" are `figure()`s.
- **History:** `historyList()` (newest first: when, who, from → to, why), then the readings.
- **Vocabulary:** Confirm, Reject, Correct…, and "Record it" in place of "Extract to ledger". Re-run actions live in
  the ⋯ menu.

## Layout (from MASTER "Layout")
- **1440:** `minmax(0,45fr) | minmax(0,55fr)`, gap `--space-5`. The source column is sticky with its own scroll.
- **900–1179:** 40/60.
- **Under 900:** one column (header, source at 60vh, tabs). `#doc2-decision` pins to the viewport bottom
  (`.doc2-pinned`: `--surface`, a top `--border`, `--shadow-overlay`, z-index 20, below the breakdown's 30).
- **Decision in view:** Confirm ends at y ≤ 768 at 1366×768, even with issues showing.

## States
- Loading, unread, reading, read failed or cancelled, read but not recorded, extracting, extract failed, publication
  blocked, no ledger record, needs review, verified, checked automatically, rejected (see the hand-off's table).
- Also: earlier version (a banner, with the decision hidden), in Trash, a combined page, a proposed image group, and a
  split file.
- **Family view:** the `member` param, with the preview off.
