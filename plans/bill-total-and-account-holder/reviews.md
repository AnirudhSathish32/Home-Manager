## Code review (round 1)

Reviewer: OpenAI Codex, `gpt-6.1-sol`, high reasoning effort; independent delegated reviewer, no helper subagents. Independence: model family and fresh context (both implementation handoffs identify `model_family: anthropic`, model `claude-sonnet-5-5`).

Reviewed branch `bill-total-and-account-holder`, revision `931fa45234350c330386bcc6f77be91976c3e51b`, against `git diff reorganize-packages bill-total-and-account-holder` (33 files). Risk: **HIGH**. The expected risk-gate BLOCKED result for the absent feature plan is a user-authorized process exception, not a finding. The binding review contract is `specs/bill-total-and-account-holder/spec.md`, including Decisions taken and User clarification (2026-11-12), with the inherited bill-engine spec, test contract and plan as context. No feature plan, test contract, approval file or progress file was invented or required.

### Findings

1. **MAJOR — A photographed due-now summary can still count automatically as a charge.** `src/home_manager/documents/extraction.py:3612` (`bill_lines`; row intake at line 3493). Requirements: **FR-141, FR-143, FR-145**, binding User clarification.

   Concrete reproduction: use `scanned_total` with `bf.total_transcription()`, remove `new_charges` from `FIELDS`, and let the model return just one service row citing `Current Charges due`, amount `62.91`. The summary's amount due also cites that line. The existing code recognizes the due-now summary, but never excludes that same summary from the model's charge rows. The new safety guard only executes when there are no rows; the lines-sum branch executes first. Independently observed persisted result: `total_minor=6291`, `amount_due_minor=6291`, `review_status='verified'`, `issues=[]`; `paid(store)` returns `[('bill', '2026-11-01', 6291)]`. Thus the due-now amount silently reaches the Transactions page's Paid, despite the printed total of 1,667.91.

   Suggested fix: exclude rows supported only by a recognized due-now summary before computing charge sums, including photo/scan and engine-failure paths. With no genuine new charges or charge rows left, retain the existing null-total/review fallback. Add an end-to-end regression for this model answer.

2. **MAJOR — Engine-supplied due-now metadata bypasses the model new-charges safeguard.** `src/home_manager/documents/extraction.py:2996` (`normalize`). Requirements: **FR-141, FR-143**, binding User clarification.

   Concrete reproduction: start with the BL-TOTAL text PDF, remove only the `Total Current Charges` label and amount (the items at y=604), retain its three charge rows and due-now line, and extract with `WRONG` (model new charges 62.91 citing the due-now line). `anchor_bill` supplies `due_now` but has no new-charges anchor to replace the model's answer. Because `due_now is not None`, `due_now_cited` is skipped, including its check that drops this invalid new-charges answer. Independently observed persisted `total_minor=6291`, rather than the genuine charge-row sum `166791`; confirming the review would count 62.91. A mismatch review reason limits automatic impact, but does not make the stored counted amount correct.

   Suggested fix: separate rejection of model new-charges answers citing due-now lines from photo-only amount-due selection, and apply that rejection even when the engine supplied due-now metadata. Preserve genuine printed new-charges anchors and FR-118 worked-out values. Add this engine-without-new-charges-anchor regression.

3. **MAJOR — The photo parser turns a due-now credit into a debit payment candidate.** `src/home_manager/documents/extraction.py:3406` (`due_now_line`). Requirements: **FR-141, FR-143, FR-145** and the exact-money invariant.

   Concrete reproduction: photograph BL-TOTAL with `Current Charges due 11/01/2026 -$62.91`; let the model correctly answer amount due `-62.91` citing that line and new charges `1667.91` citing the total. The parser removes every character except digits and the decimal point, so it stores `details.due_now.minor=6291` instead of `-6291`. Independently exercised through extraction and reconciliation: adding an outgoing provider payment of `-6291` proposes it as the bill's match, although the printed due-now amount is a credit. Parentheses and the accepted trailing `CR` also lose their sign here.

   Suggested fix: parse the matched amount with the shared signed-money/token parser, preserving minus, parentheses and credit markers; do not obtain decimal text by stripping sign characters. Cover signed due-now amounts and verify that a credit cannot supply a positive outgoing-payment candidate.

4. **MAJOR — Photographed rent bills never include payments in the worked-out amount due.** `src/home_manager/documents/extraction.py:3437` (`due_now_cited`). Requirements: **FR-142(b), FR-145**.

   Concrete reproduction: a photographed rent bill has cited previous balance 50.00, payments received 20.00, total current charges 1,667.91, and due-now 62.91. `BillRentSummary` supplies all four checked values. `normalize(..., bill_kind='rent')` independently produces `amount_due_minor=166791`, rather than `5000 - 2000 + 166791 = 169791`, and raises a carried-check failure instead of recording the worked-out total. `payments_received` belongs to the common header `fields`; it is never in `kind_fields` (`BILL_KIND_FIELDS['rent']` contains only previous balance and monthly rent). Consequently `payments` is always None in this calculation.

   Suggested fix: resolve these carried fields from the merged common-header and kind-field map (or explicitly use `fields['payments_received']`), then keep the worked-out provenance/note and suppress the carried check as required. Add a photographed rent regression with both nonzero and printed-zero payments.

5. **MAJOR — The fallback due date bypasses the required date-order check.** `src/home_manager/documents/extraction.py:3460` (`due_now_settled`; call order at lines 2994–2998). Requirements: **FR-144, FR-148**, inherited **bill-kinds FR-48**.

   Concrete reproduction: BL-TOTAL prints `Statement Date 11/10/2026` and its usual `Current Charges due 11/01/2026`; the model supplies the printed issue date but no due date. Independently exercised through the real extraction/publication path: the record is `verified`, has no issues, and retains `issue_date='2026-11-10'`, `due_date='2026-11-01'`. `bill_dates` runs before the fallback exists, and `due_now_settled` sets the earlier due date without checking order. The bill counts before its issue date and its payment search window starts after it ends. FR-48 requires the dates involved to be dropped and the bill sent to review.

   Suggested fix: select the fallback before final date validation, or factor date-order validation into a step that runs after due-now settlement. Preserve the required review behavior for issued-after-due and the existing month-first fallback.

6. **MAJOR — Due-now recognition omits FR-103's separator-dash cleaning.** `src/home_manager/documents/charge_tables.py:222` (`due_now_of`). Requirements: **FR-141, FR-142, FR-146**.

   Concrete reproduction: change only BL-TOTAL's label to `Current Charges - due 11/01/2026`. `clean_label` removes the separating dash as specified, but `due_now_of` does not, so its pattern fails. Independently observed through the text-PDF path: the due-now amount becomes a fourth charge row of 6291, the amount due remains 6291, and the otherwise correct bill goes to review because the lines now add up to 173082 instead of 166791. The shared split-rule recognition also fails for this allowed label form.

   Suggested fix: share the non-date label normalization with `clean_label`, including separating hyphen/en/em dashes, while retaining the date and printed label for due-now metadata. Exercise the engine, photographed-label rule and split `has_due` with these separators.

7. **MINOR — Family candidates with the same name are collapsed into one person.** `src/home_manager/app/manager.py:334` (`account_people`). Requirements: **FR-137, FR-138**.

   Concrete reproduction: two valid family members have different member IDs but the same name `Jordan Rivera` (family membership does not enforce unique names). Calling `Manager.account_people` with these members independently returns only the first. The account name then incorrectly has an exact-one-person match and displays `Jordan Rivera (Jordan Rivera)` instead of the unmatched printed text. A line explicitly assigned to the second member also loses its known member name and displays `Someone in the family`, because `annotate` builds its member-name lookup from the already truncated candidates.

   Suggested fix: preserve family members by identity, not case-folded name. Distinct members remain distinct matching candidates even when their names coincide, and all member IDs must remain available for explicit line assignments. Add this case at the Manager boundary, not only to `person_of`.

8. **MINOR — Hyphenated first names can match a different first name and suggest the wrong member.** `src/home_manager/finance/account_holder.py:30` (`words_of`). Requirements: **FR-137, FR-140**.

   Concrete reproduction: printed `Anne-Marie Smith`, candidate/member `Anne Smith`. FR-137 removes punctuation, so the comparable first words are `annemarie` and `anne`, which must not match. The code instead changes the hyphen to a space and then ignores `Marie` as an unmatched middle word. Independently observed `names_match(...) == True`; `suggest(...)` returns `('member', ['anne'], "The account is in Anne Smith's name", None)`. This remains a suggestion, with no automatic line member assignment, but identifies the wrong person. The SL-01 handoff acknowledges the normalization deviation; it is not among the binding delegated defaults.

   Suggested fix: remove the hyphen as punctuation under FR-137, rather than replacing it with whitespace. Test both this false positive and equivalence of `Anne-Marie Smith` with `AnneMarie Smith`.

### Independent verification and coverage

All probes used synthetic fixture text, temporary libraries and the loopback model stub; no protected financial library or donated corpus was accessed. No source, test or documentation file was edited. This uncommitted report is the only intended worktree change.

- `.venv/bin/python -m pytest tests/test_bill_printed_total.py tests/test_bill_account_holder.py tests/test_bill_corrections.py tests/test_bill_split.py tests/test_evals.py -q -p no:cacheprovider` — **292 passed**, 251.25 seconds. This covers the nominal SC-132–SC-145 paths, held corrections, multi-bill publication and the synthetic eval/summary allowlist.
- `.venv/bin/python -m pytest tests/test_bill_engine.py tests/test_bill_engine_record.py tests/test_bill_engine_generator.py tests/test_reconcile_tools.py tests/test_family_routing.py -q -p no:cacheprovider` — **638 passed**, 404.13 seconds.
- `RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_bill_engine_browser.py -q -p no:cacheprovider` — **6 passed**, 32.29 seconds, including account-holder display/correction and the due-now row/Find.
- `git diff --check reorganize-packages bill-total-and-account-holder` — passed.
- Independent targeted-test total: **936 passed** across the three commands; only existing dependency deprecation warnings were emitted.
- Additional in-memory/synthetic probes reproduced all eight findings; findings 1–3, 5 and 6 used real extraction/publication services. Finding 4 exercised the production normalizer with a valid cited `BillRentSummary`; findings 7–8 exercised the production candidate/matching/routing functions.
- Repeated reconciliation with both a 62.91 and a 1,667.91 eligible payment produced **0 links, 1 open ambiguity question**. After removing the larger payment in the synthetic library, two passes produced **1 link, 0 open questions**. No duplicate link was observed.

| Contract | Assessment |
| --- | --- |
| FR-136 / SC-132, SC-134 | Verified nominal label forms, same-line fields, first-name-line selection, photo account-name reading and absence handling. |
| FR-137–FR-138 / SC-133, SC-135 | Nominal matching, precedence, renaming, spouse-candidate code path and server annotation inspected; candidate collisions and hyphen normalization fail (7–8). Privacy: matching is view-time; no new write of the profile's display name into the library was found. |
| FR-139–FR-140 / SC-136, SC-139 | Correction/re-read/undo and browser display pass. Family names supply suggestions only; no new account-name assignment to line `member_id` was found. Hyphen false-positive suggestion remains (8). |
| FR-141–FR-145 / SC-132, SC-137–SC-141 | Nominal printed-total selection, total-worded tie, no double addition of previous balance, due date, fallback, displayed due-now row and positive matching pass existing tests. Edge cases fail (1–6); these paths are not adequately covered by the passing tests. |
| FR-146 / SC-142 | Nominal due-now-only parts pass; separator form fails shared recognition (6). |
| FR-147 / SC-143 and inherited FR-119 | v52, preserved record/detail corrections, confirmed-record immutability and held corrections pass targeted tests. No migration was added. |
| FR-148 / SC-144 | Fixture determinism passes targeted tests; unchanged full-suite behavior is **not covered** by this review run. Date-order preservation fails (5). |
| FR-149 / SC-145 | Diagnose counts and privacy assertions, appended synthetic case, unchanged existing corpus IDs/answers, generator regressions and summary allowlist pass. New summary fields are aggregated counts; no new name/label/amount/date output path was found. |
| FR-150 | Required document, money, family, eval and open-work doc changes inspected. They describe the intended behavior; the universal due-now/counting and matching claims need the code fixes above to be accurate. |

The full suite was not run, as instructed. The known date-dependent `test_sc48_a_rent_bills_page_its_lines_and_its_kind` baseline failure was not run or reported as a finding. Handoff verification counts are implementation evidence, distinct from the independently run commands above; their claims do not cover these added failure variants.

### Verdict and summary

**REQUEST CHANGES — 6 major and 2 minor findings; no blockers.** Fix the photographed due-now charge-row path, engine new-charges bypass, signed due-now parsing, photographed carried-total calculation, fallback date validation and separator normalization. Preserve distinct family identities and apply the specified hyphen normalization. Passing nominal tests do not resolve the independently reproduced money and date failures. Full-suite regression verification remains outstanding.
