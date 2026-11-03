# Plan reviews: pdf-table-engine-paystubs

## Pass 1
Reviewer: claude / claude-opus-5-5 / subagent general-purpose (fresh context). Verdict: REVISE (1 BLOCKER, 6 MAJOR, 9 MINOR).

| ID | Finding | Disposition |
|---|---|---|
| B1 | `pdf_layout_review` (`unresolved_columns`) becomes a review issue on headerless engine stubs (`extraction.py:3780`, `:3640`; `pdf_reader.py:76`) | Fixed: P7 step 1a drops it on engine pages whose only issue is `unresolved_columns` (the `pdf_import.py:408`/`:779` rule); SL-03 test |
| M1 | Deposit/leave tables aligned with PS's columns merge into the pay table | Fixed: P3.6 — a table ends after net pay, at a new heading line, and at a stub start |
| M2 | Stubs in one file share a table; per-part filter was table-level; engine run place ambiguous | Fixed: engine once in `run`, `read(…, *, pay=None)`, `for_lines` filters rows/totals and `table_grid` fallback rows by the part's lines |
| M3 | Ordered triples can't tell hours from rate | Fixed: unordered pairs + rate rule (shared column, more decimals, headings, right one) |
| M4 | Pay date + pay period lines mis-split | Fixed: a start opens a new stub only after the open stub's net pay; move-up after joins; generator variation |
| M5 | Pay stub notes not shown on the page (`document_v2.js:577`) | Fixed: SL-05 extends the condition to income records; browser assertion |
| M6 | FR-64's flat checks lost on table-less pages | Fixed: `printed_columns` becomes the set of flat-page line ids; SL-03 test |
| m1 | Evidence wiring for `pay_engine` (`:1328`, `:3806`, locator `:1761`) | Fixed in P7.3 |
| m2 | `split_changed` guess had no mechanism | Fixed: `set_split` keeps the replaced model run id on user rows; no schema change |
| m3 | VOID needs `review_source='automatic'`; reissued stubs both count | Fixed: `Ledger.mark_void`; reissued pair raised to the user (plan's open question) |
| m4 | `pay_tables` only for segment 0 | Fixed: file-level in the run result |
| m5 | Heading move-up could take the previous page's footer | Fixed: same page only |
| m6 | `read` called with a fake `self` in a protected test | Fixed: keyword-only `pay`, module-level calls only |
| m7 | SL-01 claimed steps needing roles | Fixed: re-scoped SL-01/SL-02 |
| m8 | OD-6 probe not scheduled | Fixed: SL-09 files and verification |
| m9 | "Sent to review" approximated | Fixed: engine from records; legacy proxy stated and documented |

## Pass 2
Reviewer: claude / claude-opus-5-5 / subagent general-purpose (fresh context). Verdict: REVISE (0 BLOCKER, 1 MAJOR, 2 MINOR). All 16 pass-1 findings resolved.

| ID | Finding | Disposition |
|---|---|---|
| MAJOR-1 | In a split file, file-wide `pdf_layout_review` notes (`extraction.py:3780`) reach every part and send all stubs to review; the 1a waiver was checked after the part filter | Fixed: P7.1a keeps only the part's own pages' layout notes (`line_page`, `:1998`) and checks the waiver on the file-wide reading; SL-07 test |
| MINOR-1 | P7.8 still said `printed_columns` is False on engine stubs | Fixed: P7.8 rewritten to the line-id set; `column_checks` gains the parameter; page-less lines count as table-less |
| MINOR-2 | `split_changed` missed when the rule found one stub | Fixed: `set_split` stamps the latest run id when it splits a one-part file; test added |
| INFO | A top summary printing net pay between pay date and pay period would split under FR-80 as written | Not a plan defect (the spec defines the rule); left for R-A's corpus run |

## Pass 3
Reviewer: claude / claude-opus-5-5 / subagent general-purpose (fresh context). Verdict: PASS WITH MINORS (0 BLOCKER, 0 MAJOR). Pass-2 findings resolved.

| ID | Finding | Disposition |
|---|---|---|
| MINOR-A | SL-07's MAJOR-1 test passes with either half of the fix alone | Fixed: second case with an unwaivable `overlapping_text` on page 2 (stub 1 C-auto, stub 2 needs review) |
| INFO | P7.1a parses the page from the message text ("Page N"); `Issue` has no page field | Accepted; the MINOR-A case catches a reworded message |

Loop exit: no BLOCKER/MAJOR remains after pass 3. READY for plan approval.

## After the loop: user decision (2026-11-03)
The plan's open question (a reissued stub with the same employer and pay date counting twice) was answered by the user:
"follow duplicate handling". P8 "Duplicates" now gives pay stubs the transaction duplicate rule (identity: employer, pay
date, net pay, currency; the first recorded counts, the duplicate is kept but rejected automatically with a note; a
same-date stub with a different net pay counts, with a note). SL-07 gains the matching tests. No other section changed,
so no further review pass was run.
