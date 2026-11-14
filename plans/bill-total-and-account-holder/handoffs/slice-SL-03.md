```yaml
slice: SL-03
feature: bill-total-and-account-holder
part: fixes for code review round 1 (plans/bill-total-and-account-holder/reviews.md, 6 major + 2 minor)
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: ed49983
end_head: see the last commit of this branch (the handoff is committed after the code commits below)
commits:
  - 8ec3bef  findings 7, 8 (same-named family members, hyphen)
  - 20b3678  finding 6 (separator dashes in the due-now label)
  - 64e8d2d  findings 1 - 5, version bump, docs, tests for findings 1 - 6
  - (this handoff)
escalations: []
```

No finding needed a change to the spec's requirements. `EXTRACTION_VERSION` is now `typed-extraction-v53-bill-total-review-fixes` (stored reading output changes for findings 1 - 6); pins in tests/test_bill_engine_record.py, tests/test_bill_account_holder.py, tests/test_bill_printed_total.py and the sentence in docs/documents.md updated (grep finds no other mention).

## Findings → fix → tests

Each new test was run against the pre-fix code first and failed for the reason named in the finding (findings 7, 8: before the first commit; 1 - 5: with `extraction.py` restored to `HEAD`; 6: before the `charge_tables.py` change). All tests below are in tests/test_bill_printed_total.py (`test_review1_…`) unless noted.

| # | Fix | Tests |
|---|---|---|
| 1 MAJOR photographed due-now summary as a charge row | `extraction.without_due_now_rows` (called in `normalize` before `bill_lines`, with `engine_lines` kept in step): a row whose every citation is a due-now line (`due_now_line`) is left out of the charge rows, with the note `The charge line "<description>" cites the due-now line "<label>", which is no charge; it was left out.` With no genuine rows and no new charges, the existing null-total / review fallback applies (amount due = due-now amount → nothing counted). | `test_review1_a_photographed_bill_whose_model_returns_the_due_now_summary_as_a_charge_row_counts_nothing_instead_of_62_91` (the review's reproduction: total None, Paid empty, review); `test_review1_a_due_now_row_among_real_charge_rows_is_left_out_and_the_rows_still_add_up_to_the_printed_total` (verified, 166791) |
| 2 MAJOR engine due-now metadata bypassed the new-charges safeguard | `due_now_cited(..., engine=due_now)`: the "new-charges answer citing a due-now line is dropped" step now always runs (with its note), then returns the engine's due-now line as it is; photo-only selection of the amount due unchanged. `normalize` now calls it on every non-invoice bill. | `test_review1_an_engine_found_due_now_line_with_no_new_charges_line_still_drops_the_models_new_charges_that_cite_it` (total_minor 166791, not 6291; amount due 6291 = the only printed amount, lines disagree → review; Paid 1,667.91 after confirming) |
| 3 MAJOR `-$62.91` became +6291 | `due_now_line` no longer strips to digits: it keeps the amount as printed (regex accepts `-`, `(…)`, `$-`, trailing `-`, `CR`/`DR` marker; `CR` makes it negative as `bill_tables.signed` does) and `due_now_cited` reads it with `core.money.to_minor` (and `as_decimal_text`), a `MoneyError` meaning no due-now line. `Reconciler.bill_payment` already ignores amounts ≤ 0. | `test_review1_a_photographed_due_now_credit_keeps_its_sign_and_is_no_payment_candidate[-$62.91, ($62.91), $62.91 CR, $62.91]` (details `due_now.minor` −6291 / +6291; an outgoing −6291 payment is linked only for the positive one) |
| 4 MAJOR rent payments read from the wrong field map | `due_now_cited` reads previous balance and payments from `{**fields, **kind_fields}`. | `test_review1_a_photographed_rent_bill_works_the_amount_due_out_with_its_payments[20.00-169791, 0.00-171791]` (through the real pipeline with the rent form; the note and no `Amount due:` carried issue) |
| 5 MAJOR fallback due date before the issue date | `extraction.drop_unordered` (FR-48's order check, factored out of `bill_dates`) is also run by `due_now_settled` right after the fallback is chosen; both dates are left out with the usual issue, and the due-now line's locator is not added to the bill's. The month-first fallback is unchanged. | `test_review1_a_due_now_date_before_the_issue_date_is_no_fallback_due_date_both_dates_are_left_out`; `test_review1_a_due_now_date_after_the_issue_date_is_still_the_fallback_due_date` |
| 6 MAJOR separator dash | `charge_tables.without_separators` (dot leaders, `$`, `:`, `\|`, separating hyphen/en/em dashes) is shared by `clean_label` and `due_now_of`; the date stays in the due-now label. | `test_review1_a_separator_in_a_due_now_label_is_cleaned_as_fr103_cleans_it[9 forms: dash, en dash, em dash, colon, dot leaders, pipe, dash before the date, two en dashes, dollar]` (rule, `anchor_kind` None, and `bill_split.anchor_of` = due_now for FR-146's `has_due`); `test_review1_the_engine_reads_a_separated_due_now_label_as_the_due_now_line_and_never_as_a_charge_row[- / : / .....]` (engine anchors, no 4th row, amount due 166791, verified; the PDF test font has no en dash, so en/em dash are covered by the rule test). Fixture `total_pages` gained `due_label` and `total_label` keywords (tests/bill_engine_fixtures.py). |
| 7 MINOR same-named family members collapsed | `Manager.account_people` de-duplicates by `member_id` for family members (by case-folded name only in a person's library, as before: a spouse named like the profile is one person). Two same-named members now match nobody (FR-137) and a line assigned to the second keeps its name. | tests/test_bill_account_holder.py `test_fr137_two_family_members_with_the_same_name_stay_two_people_so_the_printed_name_matches_nobody_and_a_line_keeps_its_member` (at the Manager boundary: `account_people`, `record_view`, `annotate`) |
| 8 MINOR hyphen | `account_holder.words_of` removes the hyphen like other punctuation (no longer a space). FR-137 already says "other punctuation removed" and needs no rewording; no doc described the hyphen rule (SL-01 had recorded the deviation only in its handoff). | tests/test_bill_account_holder.py `test_sc133_matching_table` gained 4 rows: `Anne-Marie Smith` vs `Anne Smith` False (both directions), vs `AnneMarie Smith` True, vs itself True |

Docs: docs/documents.md "Bill lines from the printed columns" (the due-now paragraph: separator cleaning, the new-charges rule also on engine paths, due-now rows left out, signed amounts, the due-now date and the order check; version sentence). docs/money.md needed no change (it did not describe the behaviours that changed).

## Verification (from /home/anirudh/Documents/Projects/Home-Manager-billtotal; `.venv/bin/python -m pytest … -q -p no:cacheprovider`)

| Command | Result |
|---|---|
| `tests/test_bill_printed_total.py tests/test_bill_account_holder.py tests/test_bill_engine.py tests/test_bill_engine_record.py tests/test_bill_corrections.py tests/test_bill_split.py tests/test_bills_ledger.py tests/test_bill_kinds.py tests/test_extraction.py tests/test_evals.py tests/test_bill_engine_generator.py` | exit 0, **1075 passed, 1 skipped** (the opt-in browser test in test_bills_ledger.py), 804.87 s, on the final code tree |
| `tests/test_family_hub.py tests/test_family_inbox.py tests/test_family_routing.py tests/test_family_ledger.py tests/test_profiles.py tests/test_receipt_kinds.py` (the manager.py family/profile paths) | exit 0, **92 passed** |
| `.venv/bin/ruff check src scripts evals tests/test_bill_printed_total.py tests/test_bill_account_holder.py tests/bill_engine_fixtures.py tests/test_bill_engine_record.py` | All checks passed |

Not run: the full suite; the browser tests (no UI file changed); `tests/test_bill_kinds_browser.py` (its SC-48 test fails at baseline). The pre-fix failure runs above were run on subsets (`-k review1`, `-k "sc133 or two_family_members"`).

## Decisions and what is left

- **Which rows are left out (finding 1):** only rows whose every citation is a due-now line; a row that also cites a genuine charge line is kept. The exclusion runs on every non-invoice bill, engine rows included (it keeps `engine_lines` aligned), though engine rows never cite a due-now line.
- **Finding 2's outcome on an engine-read bill with no new-charges line:** the due-now amount is the only amount due (62.91) and equals `due_now`, so `details.due_now` is not kept (FR-143 keeps it only when it differs from the amount due); the lines (1,667.91) disagree with it, so the bill goes to review, and it counts the lines' sum once confirmed. This follows the spec (FR-142 (b) last branch); no new rule was added.
- **Finding 5:** when the fallback date is left out with the issue date, `details.due_now.date` still shows the printed 2026-11-01 (it is the printed line, not the bill's due date).
- **Not changed:** the engine path's `value_of(anchor.token)` for a signed due-now anchor on text PDFs (not part of finding 3, which is the photographed parser); a text-PDF credit due-now line was not probed.
- **Existing bills** read at v52 keep their stored values until Extract again (FR-147 as before).
