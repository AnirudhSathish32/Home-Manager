# paystub-columns — plan reviews

Each pass appends its findings and dispositions. Reviewers read this first; items fixed or rejected here are settled.

## Decisions taken with the user before review (2026-10-19)
- Column notes start with the value's correction label ("This period: Regular …"), one per cleared value, so the
  existing prefix clearing satisfies FR-36. The spec's quoted "Pay line N…" texts are treated as illustrative. (plan P1)
- FR-35 applies to pay lines only, not gross/net. (P2)
- A standalone whole number ("SECTION 125") counts as an amount; FR-33 is then skipped for that line; an eval case
  measures it. (P3)

## Pass 1 (reviewer)
Date 2026-10-19. Gate: `gate.py check --stage spec` → APPROVED; spec hash 52016f01e735… matches the plan's `Spec sha256`.
Integration-table line numbers checked against the working tree (extraction.py :44, :618-638, :733-800, :908, :1179,
:1291, :1852, :1891-1976, :2349/:2354, :2509-2516, :2572-2605; ledger.py :1615-1628, :1888, :1906-1931, :1944-1961;
money.py :18/:70/:75; test_paystub_forms.py :356-387; test_eval_tasks.py :236-270; test_extraction.py :130;
layout_context.py :48; docs/money.md :129): all accurate. Every FR-31..39 and SC-28..37 maps to a slice and a check.
P1–P3 settled above and not reopened.
Verdict: **REVISE** (R1-01 needs a human decision; R1-02 is a wrong test expectation).

- **R1-01 MAJOR (human decision): native PDF pages leave the anchor path, against the spec's scope, and the claimed regression coverage does not exist.**
  Evidence: `pdf_reader.py:100-107` gives every PDF page a `vision_tables` (embedded-text pages get `embedded_tables(...)`, or `[]` plus a `pdf_table_ambiguous` issue on ValueError). Under the plan's `bool(tables)` routing, a native or embedded-text stub with no reconstructed table therefore drops `anchor_paystub` blanking and also gets `printed_columns=True` (FR-33/FR-35). The spec scopes the feature to "images and scanned PDF pages" (spec.md:17) and lists "Native PDF text with positions" as a non-goal (spec.md:24). The plan's P6/R3 says regressions are "covered by `test_pdf`/`test_layout_consumers`", but `test_pdf.py` has no pay stub at all. The pay stub tests in `test_layout_consumers.py` (:178-189, :215-223) all have tables. No test anywhere asserts the "multiple amounts" blanking (grep finds it only in extraction.py:775/:799 and docs). So the change to native pages would go unnoticed.
  Failure scenario: a native PDF stub whose pipe rows can't be reconstructed (`pdf_table_ambiguous`) used to blank its two-column lines and now keeps the model's values with only FR-22/FR-33 protecting them, which is out of scope and untested.
  Suggested fix: ask the user. Recommended: route on `bool(tables)` only for non-native pages and keep `anchor_paystub` for native pages (`native_page(page)` in layout_context), which is R3's fallback and matches the spec's scope. Either way, add one test with a native or embedded-text stub that has no reconstructed table, and assert the chosen behavior.
  Disposition:

- **R1-02 MAJOR: SC-34's planned assertion expects FR-22 rule (c) notes that cannot fire on SIDE_BY_SIDE.**
  Evidence: SIDE_BY_SIDE prints no `PAY FREQUENCY` (test_paystub_forms.py:356-358), so `first_pay_period` returns None (extraction.py:1845-1847). Rule (c) needs `first is False` (:1870). With the period unknown, equality keeps the value and only adds the "equals its year to date … the pay period isn't known" note (:1871-1874). SL-02 says "FR-22 c notes and FR-33 notes on two-amount rows". In fact the clears come from FR-33 on the two-amount rows: on those rows the YTD values are cleared too, because a failing pair clears both. On the one-amount bonus line, FR-35 does the clearing.
  Suggested fix: assert the FR-22 "pay period isn't known" notes plus the FR-33 notes (this period and year to date) on Regular, Federal, Gross and Net, and the FR-35 note on the bonus. Also assert those rows' YTD values are null and the stub is `needs_review`. Don't add a pay frequency, because the spec fixes SIDE_BY_SIDE.
  Disposition:

- **R1-03 MINOR: the version bump lands in SL-01, but the protection that replaces blanking lands in SL-02.**
  Evidence: SL-01 removes blanking and sets v24. FR-33/FR-35 come only in SL-02. Readings made between the two slices, on the dev or test instance, are reused under v24 without column checks. A commit of SL-01 alone would also count swapped values that only FR-22 guards.
  Suggested fix: move the `EXTRACTION_VERSION` bump and SC-35 to SL-02, or state that SL-01 and SL-02 are committed together.
  Disposition:

- **R1-04 MINOR: `has_table_contract` becomes an unused variable.**
  Evidence: its only use is extraction.py:2515. The `elif tables and header is not None` branch (:2530) never read it, so the plan's "stays for the non-paystub branch" is wrong, and SL-01's `ruff check` will report F841.
  Suggested fix: delete it in SL-01. If R1-01 keeps native pages anchored, replace it with the native-page test instead.
  Disposition:

- **R1-05 MINOR: summary pair notes collide on their correction prefix.**
  Evidence: `CORRECTION_LABELS` "Gross pay" is a prefix of "Gross pay year to date", and likewise for Net pay (extraction.py:181-182). Corrections drop every issue that `startswith(label)` (ledger.py:1627-1628, :1888). Correcting only gross pay this period also clears the FR-33 note on gross pay year to date, while `gross_pay_ytd_minor` stays null.
  Suggested fix: accept this (correcting one side of a pair answers both notes) and say so in docs/money.md, and add an assertion for it in the summary-pair test. Or tell the user it's a known limit of P1's prefix rule.
  Disposition:

- **R1-06 MINOR: FR-34's change inside `anchor_paystub` has no test.**
  Evidence: SC-32 b as planned asserts P-table's `401(k)` 50.00/650.00 from cells. That path uses `cell_amount` (extraction.py:764), not the counters at :773/:797 that SL-01 changes. The spec's SC-32 b also names 184.98 / 2,404.74, not the P-table values.
  Suggested fix: add a table-reading case whose cited row is outside the validated table, e.g. P-table plus a line `401K 184.98`. Today it is nulled with the "multiple amounts" note. After the change it keeps 18498. Optionally use the spec's 184.98/2,404.74 row for SC-32 b.
  Disposition:

- **R1-07 MINOR: SL-03 misses test plumbing that the new eval outputs will break.**
  Evidence: the perfect-answer stub (test_eval_tasks.py:65-66) returns only `fields/counted/wrong_column_counted`, so a `grade` that reads `kept`/`blanked` would fail `test_every_task_has_enough_unique_cases_and_a_perfect_answer_passes`. The document_forms test runs `case_limit=4` (:262) and asserts the order of the first four cases (:264-265), so the `p_photo` case must come after them, or the test must change.
  Suggested fix: list both changes in SL-03.
  Disposition:

- **R1-08 MINOR: `printed_header` treats any line with both column words as a header, even one that prints amounts.**
  Evidence: plan "printed_header". Summary lines such as `GROSS PAY CURRENT 2,500.00 YTD 37,500.00` would count as header lines. One printed in the other order (`YTD NET 34,250.00 CURRENT 2,250.00`) makes the header ambiguous, which silently turns FR-33 off for the whole stub. Either kind sets `both_named`, which turns FR-35 on.
  Suggested fix: a header line must have no `line_amounts`.
  Disposition:

- **R1-09 INFO: "validated table" also covers text-separator tables.**
  Evidence: saved vision results get pipe-delimited rows rebuilt as tables (`restore_text_tables`, vision_tables.py:103-118, called from pdf_reader.py:61-62). Pipe-delimited photo stubs, such as `seed_paystub` (tests/seed_documents.py:122-123) used by test_document_v2_browser.py:204, therefore stay on the anchor path and are unaffected. The integration table's "validated vision tables or native PDF tables" leaves this source out.
  Suggested fix: mention it in the table and in docs/money.md.
  Disposition:

- **R1-10 INFO: the label-digit rule also drops amounts joined to letters.**
  Evidence: plan `line_amounts`. Amounts such as `50.00CR`, `2,500.00USD` or OCR's `REGULAR2,500.00` would not count. Fewer amounts means FR-33/FR-35 are skipped, which fails safe.
  Suggested fix: add one such case to the unit test so the behavior is pinned.
  Disposition:

- **R1-11 INFO: the eval measures the rule, not the routing.**
  Evidence: the eval sets `printed_columns` by tag (`p_photo`), because `run()` has no evidence object (document_forms.py:68-72). It measures FR-33/FR-35, not FR-31's routing.
  Suggested fix: say so in docs/evals.md.
  Disposition:

### Pass 1 dispositions (author, 2026-10-19)
- R1-01 MAJOR: **escalated → user decided: include text PDFs** (follow FR-31's wording, beyond the spec's scope
  line). Plan P6/R3 rewritten. SL-01 adds an embedded-text no-table test pinning the new behavior. The false coverage
  claim is removed. Settled.
- R1-02 MAJOR: **fixed.** SC-34 now asserts FR-33 notes (both columns) on Regular/Federal/Gross/Net, the FR-35 note
  on the bonus, FR-22 "pay period isn't known" notes (not rule c), YTD nulls and `needs_review`. Verified at
  extraction.py:1845-1874.
- R1-03: fixed. The version bump and SC-35 moved to SL-02, and SL-01 is committed together with SL-02.
- R1-04: fixed. `has_table_contract` is deleted in SL-01.
- R1-05: fixed as accepted behavior (P8), documented in SL-04 and asserted in SL-02's summary-pair test.
- R1-06: fixed. SL-01 adds the anchor-counter case, and SC-32 b uses the spec's 184.98/2,404.74 row.
- R1-07: fixed. SL-03 adds the perfect-answer stub keys and places `p_photo` after the first four cases.
- R1-08: fixed. A header line must print no amounts.
- R1-09: fixed. Integration table and SL-04 docs updated.
- R1-10: fixed. Plan text and a unit case ("50.00CR" → 0) added.
- R1-11: fixed. SL-04's docs/evals.md note added.

## Pass 2 (reviewer)
Date 2026-10-19. Gate: `gate.py check --stage spec` → APPROVED; spec hash 52016f01e735… matches the plan's `Spec sha256`.
Pass-1 fixes checked in plan.md: R1-01 (P6, R3, SL-01 text-PDF test, false coverage claim gone), R1-02 (SL-02 SC-34
now matches extraction.py:1845-1874: no frequency → equality note, no rule c; FR-33 clears both columns), R1-03 (bump in
SL-02, SL-01 not committed alone), R1-04, R1-05 (P8; ledger.py:1888 prefix confirmed), R1-06 (anchor counter case hits
extraction.py:773), R1-07, R1-08, R1-09, R1-10 ("50.00CR" → 0 under the following-letter rule), R1-11: all reflected
correctly. Plumbing re-checked: `publish` (:2354) and `record()` (:2601) are the only app path to `normalize` for
published kinds, so `printed_columns` can't be lost on another publish path. No new BLOCKER or MAJOR.
Verdict: **READY** (PASS WITH MINORS).

- **R2-01 MINOR: P3's rationale doesn't hold for one-column rows with a standalone label number.**
  Evidence: plan.md:63-65 and P3 (:121-122) say a "Section 125" line "prints more amounts than the header names
  columns, so FR-33 is skipped". That is true only when the row prints both columns. `SECTION 125 150.00` (one column)
  under `DESCRIPTION CURRENT YTD` gives `line_amounts` [125, 150.00]. That is 2 = len(columns), so FR-33 runs with
  shifted positions (current=125, ytd=150.00), and FR-35 does not run (it needs exactly one amount). The outcome mostly
  fails safe: a this-period 150.00 is cleared, but with a column note ("printed under YTD") instead of FR-35's
  one-amount note. A model answering this period = 125 (the label digits) would pass FR-33 and be kept.
  Suggested fix: correct the P3 wording. Add a `column_checks` unit case and an eval variant for the one-column
  `SECTION 125 150.00` line, asserting the chosen outcome (cleared, and which note).
  Disposition:

- **R2-02 MINOR: `record["details"]` is rebuilt after the FR-22 guards, which would drop summary column results.**
  Evidence: extraction.py:1946 assigns `record["details"] = {labels, guards}` after `this_period_guards` (:1942), then
  `pay_details` (:1948) and the arithmetic (:1957) follow. The plan's flow (plan.md:42-46) writes summary results to
  `record["details"]["columns"]` but doesn't say where. If `column_checks` writes them before :1946, they are lost. The
  clears must also land before `pay_details` and the arithmetic.
  Suggested fix: state in SL-02 that column results are merged into the dict built at :1946, and clears are applied
  before :1948. SC-29's `details_json` assertion covers lines; add one assertion on `record["details"]["columns"]` in
  the summary-pair case.
  Disposition:

- **R2-03 MINOR: no eval variant measures FR-35 on a column-split transcription.**
  Evidence: FR-35 (plan.md:97-103) clears every this-period value on a one-amount line once any both-column header
  exists. A vision transcription that puts each column's amount on its own line (header "DESCRIPTION CURRENT YTD", then
  "REGULAR 2,500.00" and the YTD figures on separate lines) would have every pay line cleared. That reproduces the
  "everything empty" symptom this feature fixes, though it is spec D19 behavior. SL-03's variants (two blocks on one
  line, SECTION 125) don't cover it.
  Suggested fix: add a `p_photo` variant with amounts split one per line, so U1's measurement includes it. No rule
  change.
  Disposition:

- **R2-04 MINOR: SL-02 verification doesn't re-run the SC-33 suites, though the matrix says it does.**
  Evidence: plan.md:182 says "SC-33 | SL-01 (re-run in SL-02)", but the SL-02 command (plan.md:161) leaves out
  `tests/test_vision_tables.py tests/test_pdf.py tests/test_extraction.py`. SL-02 changes `paystub_lines`/`normalize`,
  which every pay stub reading uses, and the version.
  Suggested fix: add those three files to SL-02's verification command.
  Disposition:

- **R2-05 INFO: the P6 text-PDF test needs a page whose layout projects no table.**
  Evidence: `evidence_tables` takes `project_page(page)[1]` for `native_page` pages (layout_context.py:12-15, :48-55).
  `make_pdf` stubs with separately positioned items already get a positional table
  (test_layout_consumers.py:101-109, 155). A "SIDE_BY_SIDE without separators" PDF can therefore still have a table, and
  then the test exercises the anchor path, not FR-31's flat path.
  Suggested fix: in the new test, assert the precondition `evidence_tables(result) == []`. Build each row as one text
  item, or use an embedded-text page with no layout.
  Disposition:

### Pass 2 dispositions (author, 2026-10-19)
- R2-01: fixed. P3 wording now covers the one-column "SECTION 125 150.00" line, with a unit case (→ 2) and an eval
  variant. A model answering 125 as this period stays kept, as today (accepted, stated in P3).
- R2-02: fixed. SL-02 defines the order: column checks before the FR-22 guards, results merged after
  `record["details"]` is rebuilt (:1946) and before `pay_details`/arithmetic. The summary-pair test asserts
  `details.columns`.
- R2-03: fixed. A split-per-line `p_photo` eval variant is added (measurement only, no rule change).
- R2-04: fixed. SL-02's command re-runs the SC-33 suites.
- R2-05: fixed. The P6 test asserts `evidence_tables(...) == []` as a precondition.

No BLOCKER/MAJOR open after pass 2. The pass-2 changes are minor-only, so there is no third pass.
