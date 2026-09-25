# Homepage proposal

Proposal only; the current change implements the receipt inspector, not this homepage redesign.

## Start with the work that needs attention

The current homepage gives scanning controls, batch messages and the folder tree similar visual weight. The document table exposes one parsing status but hides whether financial analysis is ready. A user must open documents to find the next action.

Make the homepage a document workspace with one primary **Scan documents** button and a compact activity indicator. Keep technical scan logs in an Activity drawer.

```text
HOME MANAGER                                      Scan documents   Settings
Your documents                      Last scan: today · No active jobs

All documents    Needs extraction    Ready to analyze    Analysis failed

Search documents…                 Month ▾  Document type ▾  Status ▾

Collections        Document                  Text          Analysis       Action
All documents      Target · Sep 24            Extracted     Needs review   Review
Unfiled            Electricity bill          Extracted     Not analyzed   Analyze
Receipts           Receipt photo             Failed        —              Retry
Bills
Statements
Trash

                           Previous    1–25 of 83    Next
```

The names, dates and counts above illustrate the layout; they are not real household data.

## Proposed changes

| Area | Change | Benefit |
| --- | --- | --- |
| Top bar | Scan documents as the main action; last scan time and active processing stage nearby | Clear starting point and visible progress |
| Work filters | Clickable counts for needs extraction, ready to analyze, analysis failed and all documents | Surfaces the next useful action |
| Navigation | Compact collection names without numeric prefixes; keep the existing stored folder structure | Less visual clutter without moving documents |
| Search and filters | Filename/merchant/title search, month, document type and processing status | Find a receipt without opening each folder |
| Document rows | Title or filename, date and source subtitle; separate Text and Analysis columns | Distinguishes completed extraction from completed interpretation |
| Row action | One primary action: Extract, Analyze, Retry or Review; Move/Versions/Delete in an overflow menu | Avoids a wall of competing buttons |
| Activity | Small persistent indicator for the current document and stage, with an expandable log | Progress stays visible without dominating the library |
| Batch actions | Select rows, then Extract or Analyze; show selection count and scope | Clearer than a global “all images” action above every folder |
| Empty states | Explain the next step: configure directories, scan, extract or analyze | Helps users get unstuck |

Use the inspector's muted green palette, compact status badges, white cards and consistent spacing. On narrow screens, collections become a picker and document rows become stacked cards with the primary action visible.

## Status and data rules

- “Succeeded” describes processing. “Needs review” describes the resulting financial proposals; completion never implies approval.
- Derive statuses from the latest relevant runs for the current document version. A new transcription must not inherit an older transcription's analysis status.
- Show a proposed merchant/title as such until reviewed; retain the filename as a secondary label.
- Do not show household spending, savings or balances from unapproved receipt analyses. Those dashboard metrics need approved records, currency handling and duplicate reconciliation first.

## Suggested implementation order

1. Separate Text and Analysis statuses, improve row actions, and move batch/log controls into a toolbar and Activity drawer.
2. Add search, status filters and collection counts backed by server queries (not just the visible page).
3. Add explicit selected-document batches with durable progress and retry behavior.
