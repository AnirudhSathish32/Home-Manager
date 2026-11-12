# pdf-table-engine-bills — plan reviews

## Pass 1 (comprehensive)
Reviewer: provider claude, model claude-opus-5-5, subagent_type general-purpose (fresh native subagent; route
`review-plan` via=subagent, recorded `subagent-review-plan-1`). Verdict: REVISE. 0 BLOCKER, 5 MAJOR, 6 MINOR, 3 INFO.

| # | Finding | Disposition |
|---|---|---|
| M1 | SL-03 can't pass: its C-auto scenarios (SC-101, SC-105, SC-110, SC-114, SC-116) need P6's summary anchors, planned in SL-04 | Fixed: SL-03 builds P6's single-value anchors, `bill_fields` and summary cites; SL-04 keeps repeats, FR-117, FR-118. Slice table and matrix updated |
| M2 | `LATE_WORDS` (`late fee`, `late charge`) would drop a late fee billed this period | Fixed: a late line needs a condition with a date; an unconditional `Late Fee 5.00` is a charge row; generator prints both (P3.1, P12) |
| M3 | `(555)` tokenizes as an amount, so `Blair (555) 202-2222` could never be a title | Fixed: tokens a `PHONE` match covers become text before lines are classed (P3) |
| M4 | Undoing a held correction would write its previous value onto another line | Fixed: the undo row is recorded and marked `undone`, `receipt_items` untouched, the held reason removed; one SL-05 test (P9) |
| M5 | Scanned / combined-image parts (a `PDFResult` with pages) could fall into the engine path | Fixed: three part paths stated (engine page / text page without charge table / no text page = `bill=None`); scanned one-bill regression test in SL-03 (P7.1) |
| m1 | `PHONE` (i) as written matched `1234-5678` and `555-0100` | Fixed: reviewer's tightened regex adopted after re-checking every listed form (P3, G14) |
| m2 | `paystub_tables.covered_rows` is pay-typed | Fixed: local `covered` with the same rule (P4) |
| m3 | Full-match anchors miss `Amount Due by <date>` | Fixed: `by`/`on or before`/`as of`/`on` next to a removed date are stripped; generator prints them (P3.2, P12) |
| m4 | Split rule's `anchor_kind` must strip ` | ` separators | Fixed (P8.1) |
| m5 | SL-07 regression set missed the bill suites | Fixed: `test_bill_kinds`, `test_recurring_bills`, `test_invoice_ingestion` added |
| m6 | One-bill publication segment shape undefined | Fixed: same shape as split segments plus `"one": true` (P8.5) |
| INFO | Keys printed side by side on one line | Recorded as R-A2 (spec says a key starts the line); probe measures it |
| INFO | H1 – H3 are real human decisions | Kept as human decisions |

## Pass 2, first attempt (lost)
Dispatched 2026-11-09T05:41Z as `subagent-review-plan-2`. The planning task died on a provider rate limit before the
reviewer's findings were recorded. Nothing from it was used. Pass 2 was run again from scratch as `subagent-review-plan-2b`.

Changes made before pass 2b (resumed planner, no reviewer input):
- Re-based on HEAD `e2c2d5d` (landed during planning): `extraction.py` citations moved (+3 after `:697`, +10 after
  `:2510`); the Publish row's citations corrected (`issues.extend(notes)` is `:4050`); the Base paragraph rewritten (the
  once-uncommitted changes are now that commit); `EXTRACTION_VERSION` target v40 → `typed-extraction-v41-bill-engine`,
  with a "Version" decision (v40 is taken; SC-121 step 1 still holds; no spec amendment).
- Half-applied pass-1 fix finished: SL-03's `-k` expression now actually deselects the `sl04` cases.
- SC-121 step 3 (no migration) assigned to SL-04 (it was in no slice).
- P7.1: the layout-notes rule split out of the scanned-regression bullet; the scanned regression asserts no
  `bill_engine` table rather than no `reported_tables` at all.
- G14: a masked number in a section title (`Account ****9012`) is a holder title by FR-102 (a)'s masked form; recorded
  with a test.

## Pass 2 (`subagent-review-plan-2b`)
Reviewer: provider claude, model claude-opus-5-5, subagent_type general-purpose (fresh native subagent; route
`review-plan` via=subagent, max_subs 0). Verdict: REVISE. 0 BLOCKER, 1 MAJOR, 5 MINOR, 3 INFO. Pass-1 fixes M1 – M5 and
m1 – m6 all found applied correctly; every integration-point citation verified at `e2c2d5d`; v41 version decision sound;
G3 – G8, G13, G14 and the 80-character cut settled without changing a contract value; H1 – H3 correctly raised.

| # | Finding | Disposition |
|---|---|---|
| M1 | The plan says the tree is clean, but someone's in-flight tracked changes (`ledger.py`, `document_v2.js`, …) and an untracked `078_account_type_words.sql` exist; SC-121 step 3 hard-coded `077` | Fixed (verified with `git status`): SL-01 precondition (no tracked change, no untracked file under `src/`/`tests/`), citations re-checked against START_HEAD always, SC-121 step 3 compares with START_HEAD's listing; H4 added |
| m1 | SC-115 (b), SC-121 (3), SC-122 BL-MULTI need SL-06 but sit in the record file SL-03/SL-04 run | Fixed: they live in `tests/test_bill_split.py` and run in SL-06; matrix and traceability updated |
| m2 | SL-03 regression set misses `test_paystub_split.py`, `test_paystub_cleanup.py` (shared `pay_layout_notes`, `paystub_table_context`) | Fixed: added |
| m3 | Dateless late conditions (`if paid late`) not recognised | Fixed: added to `LATE_WORDS` (FR-103 names "if paid late"); generator prints one |
| m4 | `Payment Due <date> <amount>` is a split key but neither key nor anchor in P3 | Fixed: `payment due` is an amount-due synonym when an amount follows; P3 and P8.1 agree; generator prints it |
| m5 | `PHONE` (i) matched `1,234.5678` | Fixed: `,` added to both lookbehinds; re-checked with python3 against every listed form |
| INFO | Model new charges vs FR-118 worked-out value when no anchor | Fixed: one sentence in P6 (worked-out wins on an engine-read part) |
| INFO | Raw `0.1430` beside formatted unit prices | Accepted: the spec asks for the printed rate |
| INFO | H1 – H3 are real human decisions | Kept |

## Pass 3 (`subagent-review-plan-3`, last allowed)
Reviewer: provider claude, model claude-opus-5-5, subagent_type general-purpose (fresh native subagent; route
`review-plan` via=subagent, max_subs 0). Verdict: PASS WITH MINORS. 0 BLOCKER, 0 MAJOR, 2 MINOR. Every pass-2 fix
confirmed with no contract conflict (no fixture prints `Payment Due` with an amount or a dateless late condition; the
comma lookbehind re-run against every FR-102 (a) / SC-102 step 9 form).

| # | Finding | Disposition |
|---|---|---|
| m1 | How SC-121 step 3's test knows START_HEAD's migrations listing | Fixed: SL-04 writes the listing in as a literal read from START_HEAD at implementation time; the test runs no `git` |
| m2 | Matrix FR-121 row said SL-04 covers SC-121 steps 1, 2 only | Fixed: "SC-121 1–3 for (1), (2)" |

Loop exit: no BLOCKER/MAJOR remains. Plan READY for human review; H1 – H3 (spec-level choices) and H4 (commit or stash the
in-flight work before SL-01) are open.

## Code review (round 1)

Reviewer: Codex / OpenAI `gpt-6.1-sol`, high reasoning effort, independent delegated reviewer; two read-only mapping helpers. Risk: **HIGH**. Independence: **model-family** (all implementation/fix handoffs identify `model_family: anthropic`; the review router selected OpenAI with `independence: model-family`).

Reviewed `git diff f95182a pdf-table-engine-bills` (`f95182a843b174a82071fe396ebfde8dd3c6f85a` to `183b3d0e46709c3c8aaa51eea1c9c8212f913aa7`) and the merged checkout `68d921fe531dce060cdd5a3711f83071d6dba2ab` on `reorganize-packages`. Checked both parents' changes to `library/storage.py` and `docs/open-work.md`: the segment ordering and the other branch's capture/recovery changes are present; no separate merge defect found. Reviewed against the approved spec/test contract, plan including the 2026-11-10 answers, progress and handoffs. The documented v47/migrations 078–080 base drift is not a finding. H1–H3's accepted behavior is not a finding.

**Verdict: REQUEST CHANGES — 7 major, 2 minor; no blocker or nit.**

### Findings

1. **major — A failed split publication leaves counting bills behind.** `src/home_manager/documents/extraction.py:4632` (`run`; also `:4648`), `src/home_manager/finance/ledger.py:736`. Requirements: FR-130, FR-132; spec "Errors, recovery, duplicates, restart behavior" (a failed run publishes nothing).

   Every `self.record` commits separately through `Ledger.publish_receipt`; saving the split, retiring old records and marking the run successful happen afterward. I injected a `RuntimeError` before publishing segment 1 of synthetic BL-MULTI, after all model reading completed. The run ended `failed` with `Extraction failed; nothing was published.`, but SQL showed `(segment=0, total_minor=8142, review_status='verified')` and zero `document_segments` rows. That bill counts despite the failed run. During re-splitting, an analogous failure can also leave rewritten early bills alongside obsolete, unretired later bills. The existing failure/restart tests fail before any publication, so do not exercise this boundary.

   **Suggested fix:** make all segment publications, automatic rejection, split persistence, retirement and successful run-state persistence one transaction, or provide equivalent durable staging and rollback. Add a failure after the first actual publication and assert the entire prior ledger/split/evidence state survives unchanged, followed by a clean retry.

2. **major — An explicitly positive adjustment becomes a credit.** `src/home_manager/finance/bill_tables.py:106` (`signed`). Requirements: FR-106, FR-110, FR-113.

   The credits-section rule applies to `marker in (None, "plus")`, although FR-106 applies that rule only to unsigned amounts. A printed `+5.00` under `Account Credits` or `Adjustments` is explicitly a charge, such as a reversal of a discount. The real tokenizer returns `(Decimal('5.00'), 'plus', None)`; `signed(token, 'Account Credits')` returns `-5.00`. `money_off` consequently forces the model's service/charge line to `credit`, reversing its persisted sign and affecting column sums. The tests cover a positive `DR` marker in that section, but omit `+`.

   **Suggested fix:** apply the section-based negative sign only when the token has no explicit sign; preserve `plus` just as `debit` is preserved. Test the role sum and persisted line kind/amount for `+5.00` in each money-off section.

3. **major — Invoices lose their old native-column path when no engine charge table exists.** `src/home_manager/documents/extraction.py:4126` (`read_form`), `:4706` (`read`). Requirements: FR-120, FR-125; D5.

   `read` removes the native tables before asking the summary, but raises `InvoiceBill` only if an engine table was supplied. Thus an invoice with no engine charge table never restores `anchor_rows`/`anchor_summary`; the same gap exists when the engine fails. I ran a synthetic native PDF headed `Item / Qty / Unit price / Total`, with integer-printed totals `100` and `200`, quantities `1`, and a printed invoice number. The engine correctly found zero charge tables (the numeric columns were integers); the old `anchor_rows` on the preserved native table copied `100` and `200`. Through the new real extraction path, a model answering the printed quantity `1` as each amount produced invoice lines **100 and 100 minor units**, rather than **10000 and 20000**. There was only one summary call, confirming the invoice fallback never ran. The current invoice test starts with BL-UTIL, which already has an engine table.

   **Suggested fix:** detect an invoice whenever a bill summary was read after suppressing native tables, irrespective of engine-table presence/success, and restart on the original invoice path. Cover no-charge-table and `BILL_FAILED` invoices through `run`, asserting persisted amounts and source-cell evidence.

4. **major — A saved split does not scope sections/signs to the user's bills.** `src/home_manager/finance/bill_tables.py:373` (`read`), `:397` (`for_lines`). Requirements: FR-106, FR-130, FR-131.

   Section ownership and `money_off` are decided using the automatic page boundaries, then `for_lines` filters already-adapted rows without recalculating their ownership or sign. I extracted a synthetic two-page file whose equal keys made the rule keep it as one bill, with page 1 ending in `Account Credits` and page 2 printing a summary followed by unsigned service charges 10.00 and 20.00. After saving a user split at page 2 and extracting again through the real services, SQL showed the second bill's lines as **-1000 / credit and -2000 / credit**. Its own part contains no credit-section title. The user's split suppresses boundary uncertainty but cannot correct the engine's earlier sign decision. The limitation is recorded in progress/open-work, but is not an approved exception to FR-130/FR-131. The SC-128 inside-table test at `tests/test_bill_split.py:693` asserts a separately computed row filter, not successful re-extraction and persisted money.

   **Suggested fix:** apply the effective saved boundaries before section ownership and role/sign decisions, including boundaries inside a page; alternatively recompute those decisions from each part's raw rows/titles/anchors. Keep reading the PDF only once. Assert persisted charges and holders after an actual saved-split extraction.

5. **major — The sum rule ignores a bill's summary on another page.** `src/home_manager/finance/bill_tables.py:231` (`adds_up`; anchor filtering at `:212`). Requirements: FR-103, FR-105, FR-110.

   The allowed anchor pages are restricted to pages containing the charge table, rather than all pages of that bill. A headless table on page 1 with charge columns `(10.00, 20.00)` and comparison columns `(100.00, 200.00)`, followed by its `New Charges 30.00` and `Amount Due 30.00` on page 2, has a uniquely decidable charge column. I read this synthetic PDF with the real reader: both anchors were found on page 2, but the roles were `other, charge`, decided by `guess`, selecting the comparison column and therefore 100.00/200.00. FR-103 explicitly allows summary anchors on another page; FR-105(b) refers to the bill's new charges. The plan's table-page restriction and the generator's avoidance of this layout do not fulfill that requirement.

   **Suggested fix:** scope anchors by the bill's complete effective line/page range, while summing only that table's rows for the bill. Add a two-page headless/comparison-column case with its summary only on the other page, and verify the stored line amounts and absence of a column guess.

6. **major — A fresh correction can remember a previous reading's amount and disappear on an unchanged reread.** `src/home_manager/finance/ledger.py:2857` (`remember_line_amount`). Requirements: FR-119, FR-122.

   Any earlier applied price correction unconditionally supplies its remembered original amount, even after a later reading has printed the corrected amount itself. Reproduced through the real ledger: read a tax line as 535; correct its price to 553; publish a new reading that prints 553; now set that line's `product_code` to `TAX-CODE`; publish the same 553 reading again. The fresh code correction remembers **535**, is held with `that line now prints 5.53, not 5.35`, and the stored code becomes null. A newly set member similarly gets an incorrect held reason (its member may survive independently by item identity). These new corrections were made on a line whose current as-read amount was 553. This differs from the approved G4 case, where the non-price correction was made before the reread caught up.

   **Suggested fix:** retain the current extraction's raw line amount separately from historical correction provenance, and use that current amount for fresh corrections. Test price-correct → reread catches up → new non-price correction → unchanged reread, as well as a subsequent shifted line that happens to print the older amount.

7. **major — Space-grouped account numbers are compared by their first group.** `src/home_manager/documents/bill_split.py:83` (`key_of`). Requirement: FR-128.

   The account parser takes the last four digits of the first whitespace-delimited word holding four digits. Consequently `Account Number 1234 5678 9012` and `Account Number 1234 5678 3456` both yield key **1234**, instead of 9012 and 3456. A synthetic two-page file with those account lines and equal due dates, new charges and amounts due returned one part and no boundary reason. The accounts differ by the last four required by FR-128, so they must split even when their dates agree. The tested hyphenated format does not expose this. The plan's first-word algorithm narrows the account value beyond the spec; H1's phone-title decision does not authorize this account-key truncation.

   **Suggested fix:** parse the complete contiguous printed account value, including digit groups separated by spaces and supported masking, then compare only its last four. Stop at a following textual field rather than treating its digits as part of the account. Add different-account/same-date split and same-account/different-format continuation cases.

8. **minor — A held unit-price correction hides the current printed rate.** `src/home_manager/finance/ledger.py:2019` (`record`). Requirements: FR-110, FR-119.

   Printed-rate display considers whether any unit-price history exists at that position, ignoring whether the latest correction is held or undone while held. Reproduced: record 100 units at printed rate 0.1430 (line 14.30); correct the unit price to 0.15; reread a line at that position printing 14.35 with rate 0.1435. FR-119 correctly holds the correction, and the new details retain `unit_price.text = '0.1435'`, but the server sends `display.unit_price_minor = '0.14 USD'`. The page therefore shows the rounded cents instead of the current printed rate. The browser test covers an applied correction only.

   **Suggested fix:** base printed-rate display on whether the latest correction actually applies to the current row, using held/undone state. Verify the server string and rendered value after hold, undo while held, and recovery.

9. **minor — Product traces ignore an applied unit-price correction.** `src/home_manager/finance/document_traces.py:111` (`bill_checks`). Requirements: FR-110, FR-113.

   The trace always prefers `details_json.unit_price.text`, even after the user replaces that rate. A synthetic line of quantity 140, printed rate 0.1430 and total 2002, corrected to unit price 0.15, displays `0.15 USD` but its product check still receives `('140', '0.1430', 2002)` and passes. The displayed current rate would produce 2100. This makes the check explain different money from the current record. Existing tests verify the corrected display but do not inspect the corrected product trace.

   **Suggested fix:** use one effective-rate selection rule for display and checks: an applicable correction wins; otherwise the exact printed rate wins over rounded cents. Test applied, held and undone unit-price corrections against both the displayed value and product-check arguments/result.

### Verification and coverage

Independently ran on the merged checkout (synthetic fixtures only):

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider \
  tests/test_bill_engine.py tests/test_bill_engine_record.py \
  tests/test_bill_corrections.py tests/test_bill_split.py \
  tests/test_bill_engine_generator.py tests/test_evals.py -q
704 passed, 2 warnings in 511.28s
```

The nine findings above were reproduced separately with inline Python against the real tokenizer/reader, bill adapters, ledger or extraction services and temporary synthetic libraries, without adding or changing tests. Finding 4 includes a real `set_split` and subsequent extraction with SQL verification; finding 3 compares the existing native anchor's output with the newly persisted invoice lines; finding 1 checks persisted state after a failed publication. For findings 5 and 7, the independent observed boundary/role outputs are engine-level, with the downstream consequence traced in source.

Requirement/scenario status:

- **Failed edge cases:** FR-105 (finding 5), FR-106 (2/4), FR-110 (2/5/8/9), FR-113 (2/9), FR-119 (6/8), FR-120 and FR-125 (3), FR-128 (7), FR-130/FR-131 (4), and failed-run persistence for FR-130/FR-132 (1). The corresponding supplied SC-105/106/110/113/119/126/128/129/130 cases pass but do not cover these failure variants.
- **Verified within the passing targeted synthetic contract:** SC-100–106, SC-110–119, SC-121–128, and the service/API portions of SC-129–131; the generator's 120 input files and the five aligned bill eval fixtures pass. This includes FR-100–104, FR-111, FR-114–118, FR-121–124, FR-127, FR-129 and FR-133–135 within their tested shapes, subject to the findings and limits above. G1/D21/D25's half-up rate storage and value-based precision tests pass. FR-126's documentation and the merge-specific ordering were inspected; a documented unapproved omission does not waive a requirement.
- **Reported evidence, not rerun in this review:** SC-120/FR-125's full legacy regression matrix; the supplied merged-tree full-suite result is 54 failed / 3741 passed / 20 errors with the same 74 baseline failure/error IDs. Progress records a pre-merge 54 failed / 3733 passed / 20 errors and browser verification. These baseline failures are not findings and the full suite was not rerun.
- **Skipped/blocked:** independent browser execution of SC-110 step 7, SC-111 step 3 and SC-129's page steps; running-app validation remains **BLOCKED** by missing `~/.agent-harness/environment.py`. No live household data, donated corpus or protected path was accessed. Real-bill accuracy and uncommon layouts remain unmeasured. The already documented one-column-heading/title limitation is a residual risk, not an additional finding here.

Only this findings section was written; no source, tests, other docs, commits, pushes or merges were changed by the reviewer.
