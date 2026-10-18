# Plan reviews: document-forms

Every reviewer reads this file first. Items marked fixed or rejected here are settled.

## Settled before review (user decisions, 2026-10-18)
- One phased plan rather than splitting the feature (30 FRs).
- D-P2: a kind change is an asynchronous run, and its correction is written with publication (PATCH returns a run id).
- D-P4: Apply details never changes amounts or review state, even with a gift card. The page shows a note.
- D-P5: FR-30 is met by masking digit runs of 5 or more to their last four in identifier fields, new details and
  result_json. parse_runs and document_passages_fts count as the saved transcription. C-cite compares under the mask.
- D-P6: the spec's domain risk candidates 1–7 are out of scope, listed in docs/open-work.md.

## Pass 1 (fresh subagent, 2026-10-18): REVISE
| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | MAJOR | Several `-k` filters in one pytest command (only the last applies); wrong test file names | **Fixed**: one command per filter, regression files run with no `-k`, real names (`test_reconcile_tools.py`, `test_spending_splits.py`) |
| 2 | MAJOR | Masking regex matches ISO dates; `scrub` over all of result_json breaks `filing_identity` and masks product codes | **Fixed**: the regex is unbroken 5+ digits or card blocks; `scrub` runs on identifier and detail keys only; unit tests show dates, phones and amounts survive |
| 3 | MAJOR | `total_minor` means two things; the `total` correction and `refresh_paid` ordering | **Fixed**: `refresh_paid` is idempotent and runs inside the publish and correction transactions, before splits; a `total` correction writes `printed_total_minor`; `_field_text` shows the printed total |
| 4 | MAJOR | The return guard trips SC-04 (a savings row makes it an exchange) | **Fixed**: return means a negative total or `sale_type='return'`; exchanges count as sales; SC-04 asserts it |
| 5 | MAJOR | Labels not cited; table cell evidence can't contain the labels | **Fixed**: `PayLabel` has its own evidence and must be an exact substring; table labels come from cell 0 and the header cell; 20-a asserts rule (a) |
| 6 | MAJOR | Characterization stubs with new keys fail for the wrong reason under extra=forbid | **Fixed**: the 20-e stubs use only pre-change fields; the pre-change output must show verified and 3250000 |
| 7 | MAJOR | SC-24 contradicts fixture P's dates | **Escalated → resolved**: spec D16 (fixture P-sept), re-approved spec 7cf26b4ec7e9; plan updated |
| 8 | MINOR | SC-27: the spec says "not 12.10", the contract expects 12.10 | **Escalated → resolved**: spec D17 (the contract stands, the spec reworded) |
| 9 | MINOR | Undo branches, null kind, plain re-read, item details | **Fixed**: explicit undo branches; a null correction means no choice; a plain re-read leaves reviewed receipts alone; pending covers summary details only (Risk) |
| 10 | MINOR | Line issue clearing on re-read and undo | **Fixed**: `_correct_income_line` stores resolved issues; `apply_income_line_corrections` clears them |
| 11 | MINOR | Atomicity overclaimed | **Fixed**: reworded per record; J-c asserts no partial details |
| 12 | MINOR | Tip step with no value; amount paid with no other tender; the parity test's real file | **Fixed**: `step(missing=True)` gives value null; `compared_with` null and `reconciles` = deductions ≤ total; `test_ui_parity.py:114` noted |
| 13 | MINOR | `allocate` doesn't scale the negative savings row | **Fixed**: `allocate` on the printed total, then `splits.scale` |
| 14 | MINOR | Bank signs, normalize-time failures, concurrent PATCH, ui_shots path, SC-18 queued setup, version timing | **Fixed**: all six addressed in the plan (the SC-18 setup was wrong; fixed again in pass 2 #1) |

## Pass 2 (fresh subagent, 2026-10-18): REVISE
Verified correct: the regex, the 20-e stub under extra=forbid, allocate→scale, step(missing=True), line issue clearing, the exchange guard.
| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | MAJOR | SC-18 setup: `enqueue` reuses a queued or running row with the same options; an unsubmitted run never runs | **Fixed**: the second reading uses other options (`home_currency`) and is submitted behind the held run |
| 2 | MAJOR | `document_passages` (the content table) holds transcription text; exempting only the FTS table fails C-ids | **Fixed**: `document_passages` and the FTS shadow tables named as the saved transcription (falls within D-P5's meaning; verified in migration 042, rebuildable from parse_runs) |
| 3 | MAJOR | A gift-card receipt corrected to a return loses its sign | **Fixed, simplest alternative adopted** (rule 9: second MAJOR in the refresh_paid area): `printed_total_minor` is a magnitude; the sign comes from `effective_receipt_direction`; SL-06 adds a direction variant |
| 4 | MINOR | Stale `printed_total_minor` after a re-read | **Fixed**: publish writes NULL and the signed printed total, then derives |
| 5 | MINOR | `run()` would reject the `receipt_kind` option | **Fixed**: popped before `ReasoningConfig` |
| 6 | MINOR | Label quotes not checked against their lines | **Fixed**: `normalize` checks them under mask |
| 7 | MINOR | `inputs_hash` skips text inputs | **Fixed**: hashes text and unit |
| 8 | MINOR | `split` trace recorder routing on the printed-total path | **Fixed**: `allocate` gets NULL, `scale` gets the recorder |
| 9 | MINOR | SC-11's record-view checkpoint not asserted | **Fixed**: added in SL-07 |
| 10 | MINOR | FR-18 must also cover parse runs and the same blob | **Fixed**: checked by blob_hash across extraction and parse runs |
| 11 | MINOR | Undo branches underspecified | **Fixed**: undo inserts a correction row; a pending proposal is cleared on kind undo |
| 12 | MINOR | `refresh_paid` scope contradicts D-P4 | **Fixed**: an explicit trigger list; never on apply or unrelated corrections |
| 13 | MINOR | 4d stores a card number in item text | **Fixed**: the 4d stub quotes `-5.00`; item masking rejected (it would mask product codes); listed under Risks |
| 14 | MINOR | Characterization tree and multi-number lines | **Fixed**: run after SL-01; P-flat has one amount per line |
| 15 | MINOR | SL-02/SL-03 details-write boundary | **Fixed**: the write moved to SL-02 |

## Pass 3 (fresh subagent, 2026-10-18): REVISE (1 MAJOR)
Verified correct: the sign from effective_receipt_direction with direction applied last, the publish write, total-correction undo, SC-18 reuse and RLock, the FR-18 parse-run check, the transcription exemption.
| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | MAJOR | `refresh_paid` crashes on a NULL total (bills, missing totals); SL-06 regression too narrow | **Fixed, simplest form (rule 9: third MAJOR in this area)**: returns early for bills, NULL totals and receipts without gift cards; SL-06 runs the extraction, receipt, invoice, bill and family suites |
| 2 | MINOR | Issue ownership and rule precedence | **Fixed**: first-match order; it removes and re-adds its own issues; needs_review on add |
| 3 | MINOR | SC-27 step 6's auto-verify after undo | **Fixed**: `refresh_paid` restores verified/automatic when it clears the last issue and nobody has decided since |
| 4 | MINOR | False retry claim | **Fixed**: a retry is the same PATCH again; J-b and J-c assert it |
| 5 | MINOR | Kind change missing home_currency and decision | **Fixed**: same arguments as `start_extraction` |
| 6 | MINOR | SC-18 currency change | **Fixed**: USD vs None both resolve USD on SC-01 (receipt fallback); asserted |
| 7 | MINOR | Details write vs `apply_corrections` order | **Fixed**: details are upsert columns, before `apply_corrections`, `refresh_paid`, splits |
| 8 | MINOR | FR-18 batch window | **Listed under Risks** (safe outcome) |
| 9 | MINOR | Segment index drift on unconfirmed splits | **Fixed**: matched by first line id; a mismatch fails with nothing written |
| 10 | MINOR | Family copies and double subtraction | **Fixed**: a family publish writes NULL kind, details and printed total; display gap listed under Risks |
| 11 | MINOR | Shared-receipt recorder routing | **Fixed**: `last(not shared)` |
| 12 | MINOR | Broken markdown table cell | **Fixed**: the SC-18 setup moved under Test environments |

## Pass 4 (fresh subagent, 2026-10-18): REVISE (1 MAJOR)
Verified correct: the table renders, the SC-18 currency claim (the stub's currency must be `missing`; already true of SC-01), the enqueue arguments, popping before validation, segment matching, the family early return, sale→return→undo, the publish order.
| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | MAJOR | The verified restore is undone by `undo_corrections`' own revert; issues wiped by the `_apply_correction` write | **Fixed, simplest alternative (rule 9: fourth MAJOR in this area)**: `refresh_paid` never sets verified; it's called once as the last write of `correct()` (before auto-verify) and of `undo_corrections`; it's never in `resolved_issues_json`. SC-27 step 6 asserts only "the note clears", as the contract says |
| 2 | MINOR | Whole-column upsert vs per-kind details | **Fixed**: publish merges `details_json[kind]`; a journey assertion checks it |
| 3 | MINOR | first_line_id source, submitted function, failure scope | **Fixed**: all three stated |
| 4 | MINOR | A blank total correction | **Fixed**: both columns NULL; the early return covers coalesce IS NULL |
| 5 | MINOR | Mismatch text varies | **Fixed**: matched by fixed prefixes outside correction labels |
| 6 | MINOR | A total or direction correction counts an uncounted gift card | **Fixed by rewording**: the D-P4 page note names all three corrections |

## Pass 5 (fresh subagent, 2026-10-18): READY (no BLOCKER or MAJOR)
Verified correct: `refresh_paid`'s call points and no-restore rule, prefix ownership, the merged details write, blank totals, the first_line_id source and failure scope, every SC-27 checkpoint and its final state, the SC-04 direction variant.
| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | MINOR | A gift-card receipt corrected to a bill keeps `printed_total_minor` | **Fixed**: `document_kind` is a trigger; bills apply rule 4 once, then return early |
| 2 | MINOR | An undo of a `detail:*` field gone from the current kind raises KeyError | **Fixed**: ValueError → 400; journey assertion |
| 3 | MINOR | first_line_id fallback for a retired segment | **Fixed**: fallback only when the hash has no segment rows; otherwise 400; match placed after the classify loop, before `read` |
| 4 | MINOR | review_source on the move to needs_review; owned issues on early return | **Fixed**: review_source NULL (as at :501); owned issues stripped on the NULL-total return |

Loop closed after pass 5: no BLOCKER or MAJOR open.
