# receipt-layout-eval — plan reviews

## Pass 1 — 2026-11-15
Reviewer: claude / claude-opus-5-5, native subagent `general-purpose` (route `via=subagent`, `max_subs=0`), recorded as
`subagent-review-plan-1`. Verdict: REVISE (4 MAJOR, 7 MINOR, 5 INFO). The planner re-checked each finding it acted on
against the code before changing the plan.

| # | Severity | Finding | Disposition |
|---|---|---|---|
| 1 | MAJOR | P6 corrected both axes with the margin slope in units that aren't equal in pixels; caps rows split under ±2.5–3° tilt, every `angled` case skewed level rows. | Fixed: P6.2–P6.4 measure the row slope directly (fewest rows, then smallest spread) and use the margin slope only for horizontal positions; SL-04 asserts `build_rows` on all 24 drawn cases. |
| 2 | MAJOR | A truncated answer raises after the 16,384 retry, the attempt is "failed", and `failure_kind` returns "other"; FR-12/FR-18's truncation would read 0. Verified at `model_client.py:281-287`, `:388-389`, `evals/graders.py:126-130`. | Fixed: P13 maps "incomplete or truncated" to `truncated` before the failed branch; per-format `run_one` tests in SL-04; R4 restated. |
| 3 | MAJOR | SC-10 captures built with `make_receipt` (Arial when present) only match on the computer that made them. Verified at `tests/test_receipts.py:19-22`; results keep `input_hash`. | Fixed: SL-01 commits font-free inputs with recorded hashes, checked first. |
| 4 | MAJOR | The observed "price after a side line" pattern grades as whole + extra. | Fixed: P8 whole requires every cell in the line; a missing cell found on a nearby unpaired line makes a split; SL-04 test. |
| 5 | MINOR | Format variants after schema variants break `schema_pairs`. | Fixed: formats first (P9), tested in SL-05. |
| 6 | MINOR | Documents dry run lacked model calls; results lacked prompt versions. | Fixed: P9, SL-05 asserts both suites. |
| 7 | MINOR | layout-text prompt asked for tabs before centred and right-only lines. | Fixed: P4 sentence added. |
| 8 | MINOR | v6 lines kept leading whitespace (D4). | Fixed: P3 strips it. |
| 9 | MINOR | Wall-time asserts flaky; FR-17 "shifted" and FR-16 "missed flag" acceptance missing. | Fixed: deterministic cost count (P8); both tests added to SL-04. |
| 10 | MINOR (possible) | `receipt_layout` would gate vision model choice. | Fixed as planner's call within the spec's non-goal: P14 measured only. |
| 11 | MINOR (possible) | RAQM vs basic layout; licence text hash vs CRLF. | Fixed: P7 basic layout engine; only `.ttf` hashed. |
| I-1 | INFO | `--formats` would re-run reasoning tasks per format. | Fixed: vision tasks only; reasoning tasks refused with `--formats` (P9). |
| I-2 | INFO | Risk text wrong: a rejected schema is resent in the prompt (`model_client.py:276-280`). | Fixed in Risks. |
| I-3 | INFO | Character width inflates with whole-row pieces. | Fixed: 25th percentile (P6.2) and a builder test. |
| I-4 | INFO | Notes issue dropped for scanned pages and combined documents. | Fixed: P2 and SL-02. |
| I-5 | INFO | App's OFL fonts could be reused. | Kept Liberation; rationale in P7. |

## Pass 2 — 2026-11-16
Reviewer: claude / claude-opus-5-5, native subagent `general-purpose` (route `via=subagent`, `max_subs=0`), recorded as
`subagent-review-plan-2`. Verdict: REVISE. All 16 pass-1 findings resolved (pass 1's #2 for the main call only, see N2);
1 new MAJOR, 4 MINOR, 5 INFO.

| # | Severity | Finding | Disposition |
|---|---|---|---|
| N1 | MAJOR | The committed `scan.pdf` has no NUL byte (569 bytes, 32 LFs; planner re-checked), the repo has no `.gitattributes`, and the developer's machine is Windows (`docs/development.md:124`), so a line-ending conversion would rewrite it and the JSON captures. | Fixed: SL-01 adds `tests/reading_format_data/** -text`, checked by the self-test. |
| N2 | MINOR | P13's substring caught a non-budget stream end and missed a rescue that ran out (`vision.py:217-225` rewrites its error). | Fixed: exact phrase plus the attempts signature (`invalid_or_truncated_output` at 16,384); an empty answer after the budget retry counts the same and is documented; three cases in the `tests/test_evals.py` table. |
| N3 | MINOR | Dry-run vision calls counted text-PDF pages. | Fixed: only cases that aren't `native_pdf`, worded "about N". |
| N4 | MINOR | P14 still summed `runs`, `valid`, `p95` over measured-only tasks. | Fixed: dropped from `mine` before any sum; SL-04 test. |
| N5 | MINOR (possible) | `layout-text` table rows use " \| " as their prompt asks, but cells split on tabs only. | Fixed: P8 treats " \| " as a cell boundary when grading; SL-04 test. |
| I-1 | INFO | SC-10 bytes include the server port; a pinned port collides in parallel runs. | Fixed: `mask_port` applied identically when writing and comparing; no fixed port. |
| I-2 | INFO | PNG bytes depend on zlib-ng. | Fixed: the recorded-hash skip condition includes `zlib_ng` 2.3.3; Risks updated. |
| I-3 | INFO | Unrounded boxes could change case ids across computers. | Fixed: boxes rounded to 0.1 px in the answers (P7). |
| I-4 | INFO | `--formats spans,spans` would make duplicate candidates. | Fixed: `check_formats` refuses repeats; SL-05 test. |
| I-5 | INFO | No test asserts `long` ≥ 80 rows (FR-02). | Fixed: SL-03 test. |

## Pass 3 — 2026-11-16 (final)
Reviewer: claude / claude-opus-5-5, native subagent `general-purpose` (route `via=subagent`, `max_subs=0`), recorded as
`subagent-review-plan-3`. Verdict: PASS WITH MINORS. All ten pass-2 findings resolved; no BLOCKER or MAJOR. The loop
exits here.

| # | Severity | Finding | Disposition |
|---|---|---|---|
| P3-1 | MINOR | SL-04's rescue-truncation test can't be built: the fake server's `finish_reason` is one value for every request (`tests/model_server.py:30`, `:111`). | Fixed: SL-04 adds an optional per-request `finish_reasons` list to `tests/model_server.py`. |
| P3-2 | INFO | After a schema rejection the resend gets no 16,384 retry, so a rescue that runs out there reads `other`. | Fixed: one sentence in `docs/evals.md` (P13). |
| P3-3 | INFO | A case saved by the 16,384 retry shows no truncation and `None` tokens, so the spec's 8,192-limit question stays unanswered. | Fixed: per-case `budget_retry` and partial token sums (P9); SL-05 asserts both. |
