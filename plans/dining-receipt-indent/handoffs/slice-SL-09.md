```yaml
slice: SL-09
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: ab82408
end_head: 68a217c   # the docs commit; the handoff itself is committed on top of it
commit: 68a217c
checks:
  - command: "grep -rnoE 'docs/[a-z-]+\\.md \"[^\"]+\"' src  (resolved against each doc's # headings by /tmp/cites.py)"
    exit_code: 0     # 356 citations, 3 unresolved, all older than this feature (see Open issues)
  - command: "git diff ab82408 -- src tests specs approvals plans/dining-receipt-indent/plan.md"
    exit_code: 0     # empty (docs only)
escalations: []
```
SL-09 is built: the FR-25 docs describe the behavior of SL-01 – SL-08 as built. Docs only; no code, test, spec, plan, approval or progress change.

## What was done
- `docs/documents.md`
  - "Images (vision transcription)": the reading returns `lines` `{text, indent}` (text joined for the full text; ids, citations and Tables unchanged), a new **Indent** bullet (FR-15 rules, unknown indent, the `{full_text}` shape gets the rescue, blank answer), **Reading versions** (`receipt-vision-v7-indent`), a **Text view** bullet (indented one step per level, text unchanged).
  - "PDFs": scanned pages keep indent, `pdf-pages-v4-indent`, older `pdf-pages-v3-layout` readings still open.
  - "Several images as one document": `receipt-images-v3-indent`, old v2 readable, lines keep indent.
  - "Receipt kinds": the dining bullet now covers the charged total (pre-tip labels, the nearest pre-tip amount, the disagreeing-amounts issue), the worked-out tip (note, Review reason, trace, FR-03 issue, no invented tip), the suggested-tip table and the fallback after a rejected total, Correct…, and old receipts until Extract again (v57). A new "Lines printed under an item" bullet (indent in the payload, the row instruction, the backstop and its note). The Stored bullet names `tip_worked_out_json` and `item_categories_json` (migration 081). The code line cites `dining_total.py` and the spec.
- `docs/money.md`
  - "Item categories and splits": the Category column and footer spans, the footer's "Not matched to an item" without the tip plus the Tip note, rules 4 and 5 amended, and a new `### A dining receipt` subsection (when it applies, what it does, the column, the 400 refusal, receipts recorded before, the backfill, a kind change and Undo). The backfill paragraph points to it. The new heading breaks no existing citation.
  - "Reading a statement or receipt again": a new bullet for a charge link the new total no longer supports (the rules, what removing does, the note, not a rejection).
  - "Near matches and foreign receipts": a removed link is not a rejection and can be linked again.
  - "Gift cards": a removed link gets no "Amount paid (" note (D40).
- `docs/open-work.md`: under Ingestion, "Dining receipts and indentation, still open" (D2's four items, D16, plus the unmeasured vision indentation accuracy from the spec's Unknowns); under Money, "Stale links a re-read doesn't remove" (bill and pay stub links, Correct… on a total, a date- or merchant-only re-read, no lasting history entry). No Q2 entry. No SC-19 note: SC-19 passes in `tests/test_dining_receipts.py`.
- `docs/evals.md` (not on the task list): the transcription row's shape `{full_text, tables}` became `{lines: [{text, indent}], tables}`, because the vision schema changed.

## Citations
`/tmp/cites.py` took every `docs/<doc>.md "Heading"` match in `src` (356) and looked for the heading in the named doc. All resolve except three, which exist unchanged at 2676e51 (before this feature), so I left them:
- `app/static/trace.js:368` and `app/static/document_v2.js:345`: `docs/ui.md "Source viewer"` (no such heading in ui.md).
- `documents/pay_tables.py:270`: `docs/documents.md "Known limits"` (only a bold bullet, not a heading).
Every citation this feature's slices added resolves ("Receipt kinds", "Images (vision transcription)", "Item categories and splits", "Corrections").

## Open issues
- The three older broken citations above.
- Some statements come from the handoffs and the spec rather than from re-reading code: the exact note texts for a removed link (checked only for the "was removed" fragment in `reconcile.py:852`), and the Text view's `data-indent` CSS.
- Browser/UI behavior (the Text view indentation, the Tip note) is described from SL-08's handoff and tests, not rechecked in a browser.
