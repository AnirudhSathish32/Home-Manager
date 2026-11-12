```yaml
slice: SL-01
feature: bill-total-and-account-holder
part: A (the account holder, FR-136 - FR-140)
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 85727ee
end_head: see the last commit of this branch (code commit cf46be2; this handoff is committed after it)
commit: cf46be2
```

## What was built

`EXTRACTION_VERSION` is now `typed-extraction-v51-bill-account-holder` (pin in tests/test_bill_engine_record.py and the sentence in docs/documents.md updated; no other file names it).

| FR | Code | Tests (tests/test_bill_account_holder.py unless noted) |
|---|---|---|
| FR-136 reading | `documents/charge_tables.py` `ACCOUNT_HOLDER_LABELS`, `NEXT_LABEL`, `account_holder_of` (labels kept beside `ANCHOR_WORDS`/`KEY_LABELS`; value cut before the next FR-103/FR-128/account label, 80 chars); `documents/extraction.py` `account_holder(lines)` (first line wins, later different value adds the note), called in `normalize` and stored by `bill_lines` as `details["account_holder"] = {text, locator}` for kinded non-invoice bills; never `line_holder` | `test_fr136_an_account_name_line_gives_its_value_as_printed` (18 rows), `..._labels_are_a_fixed_list...`, `..._first_account_name_line_is_used_and_a_different_later_one_adds_a_note`, `test_sc132_a_the_user_s_bill_keeps_the_account_holder...`, `test_sc134_a_bill_printing_no_account_name_or_only_a_sentence...`, `test_fr136_a_photographed_bill_reads...`, `test_fr136_an_invoice_keeps_todays_path...`, `test_fr136_each_part_of_a_file_of_several_bills_reads_only_its_own_lines` |
| FR-137 matching | `finance/account_holder.py` `words_of`, `names_match`, `person_of` (NFKC, accents, case, `Last, First`, titles/suffixes, joint names, initial never matches, one-word rule, "My profile" never, exactly-one-candidate) | `test_sc133_matching_table` (19 rows), `test_sc133_two_candidates_matching_one_name_match_nobody...` |
| FR-138 Person cell | `finance/account_holder.py` `annotate` (adds `item["person"] = {text, source, title}` and `record["account_holder_view"]`); `Manager.account_people`, `Manager.record_view`, `Manager.family_record` call it; `static/receipt.js` shows `row.person.text` with `title` and a small "Account name on the bill" for the account source (family-inbox select untouched) | `test_sc132_fr138_every_line_shows_the_profile_name...`, `test_sc133_renaming_the_profile_changes_what_is_shown_with_no_re_read` (also asserts the library never holds the profile name), `test_fr138_a_section_title_holder_wins_and_the_credit_line_takes_the_account_holder` (SC-135), `test_fr138_a_member_set_on_the_line_wins_and_a_bill_shared_by_line_leaves_unheld_lines_shared`, `test_fr138_the_manager_decides_the_people...`, `test_fr138_the_page_shows_the_servers_text_and_its_source`; browser `test_account_holder_the_person_cells_show_the_servers_text...` |
| FR-139 page + correction | `static/document_v2.js` `doc2Fields` adds the Account holder row (`account_holder_view.display`, Find via `locator`, Correct); `finance/ledger.py` `ACCOUNT_HOLDER`, `detail_fields` (kinded non-invoice bills only), `_set_account_holder` (creates the entry when the bill printed none; 80 chars, needs a letter, `None` clears), `reapply_detail`, `correctable` | `test_sc139_correct_sets_the_account_holder_extract_again_keeps_it_and_undo_restores...`, `test_fr139_cleared_means_no_account_holder_and_a_bad_value_is_refused`, `test_fr139_the_page_offers_account_holder_only_on_a_kinded_bill...`; browser (Find button, Correct form, Save, cells update) |
| FR-140 family | `finance/family_routing.py` `suggest(..., people, holder)` new last rule (no line holders, exactly one member matches; "The account is in <member>'s name"), `FamilyRouting.account_holder`, `refresh(facts, who, people)`; `Manager.family_routing` passes `family_people()`. No code sets `member_id` from a name | `test_sc136_the_account_name_suggests_a_whole_bill_for_one_member_and_never_sets_a_line`, `test_sc136_a_phone_bill_keeps_its_share_by_line_suggestion...`, `test_fr140_suggest_gains_one_rule...` (7 rows + unlisted card), `test_fr140_the_suggestion_follows_the_person...` |
| FR-147 | version bump; account holder is a `detail:` correction so `apply_corrections` re-applies it; decided bills untouched by the existing mechanism | `test_sc143_the_version_moved_an_undecided_bill_gains_its_account_holder_on_extract_again`, `test_sc143_a_correction_made_before_the_re_read_wins_and_a_confirmed_bill_is_never_rewritten` |
| FR-148 | deterministic by construction | `test_fr148_a_second_reading_changes_nothing_and_asks_the_model_nothing_more` (snapshot, notes, questions equal after `force=True`) |
| FR-149 (diagnose only) | `scripts/statement_diagnose.py` prints `account-name lines: N` per page (count only) | `test_sc145_diagnose_counts_account_name_lines_per_page_and_prints_no_name` |
| FR-150 (this slice's docs) | docs/money.md "Bills and their lines" + "Corrections", docs/documents.md "Bill lines from the printed columns" (+ version sentence), docs/family.md "Family inbox" + "Sharing a bill by line", docs/open-work.md "PDF table engine" (new bullet) | doc diff |

Fixtures added to tests/bill_engine_fixtures.py: `total_pages` (BL-TOTAL, synthetic `LAKESIDE GAS & ELECTRIC` / `Jordan A. Rivera`), `STUB_TOTAL`, an `account` parameter on `util_items`/`phone_pages` (BL-UTIL-AH, BL-PHONE-AH), registered in `FIXTURES`.

## Verification (all from /home/anirudh/Documents/Projects/Home-Manager-billtotal, `.venv/bin/python -m pytest ... -q -p no:cacheprovider`)

| Command | Result |
|---|---|
| `tests/test_bill_engine.py tests/test_bill_engine_record.py tests/test_bill_corrections.py tests/test_bill_split.py tests/test_family_routing.py` | exit 0, 489 passed |
| `tests/test_bill_account_holder.py tests/test_bill_kinds.py tests/test_bills_ledger.py tests/test_family_inbox.py tests/test_family_ledger.py tests/test_family_routing.py tests/test_receipt_kinds.py tests/test_record_history.py tests/test_correction_preview.py tests/test_profiles.py tests/test_provenance.py tests/test_bill_corrections.py` | exit 0, 297 passed, 1 skipped |
| `tests/test_bill_account_holder.py tests/test_bill_engine_generator.py` | exit 0, 349 passed |
| `RUN_BROWSER_TESTS=1 ... tests/test_bill_engine_browser.py tests/test_document_v2_browser.py tests/test_bill_kinds_browser.py tests/test_family_browser.py` | 17 passed, 1 failed: `test_bill_kinds_browser.py::test_sc48_a_rent_bills_page_its_lines_and_its_kind` ("For Oct 1 – Oct 31, 2026" not on the Bills page). **Pre-existing**: it fails identically at start head 85727ee (checked with `git stash -u`, then restored); it depends on today's date (2026-11-12). Not caused by this slice. |
| `RUN_BROWSER_TESTS=1 ... tests/test_bill_engine_browser.py` (after adding the new browser test) | 5 passed |
| `.venv/bin/ruff check src scripts tests/test_bill_account_holder.py tests/bill_engine_fixtures.py tests/test_bill_engine_record.py tests/test_bill_engine_browser.py` | All checks passed |

The full suite was not run (per the instructions).

## Decisions I had to make

- **Where the match happens:** `Manager.record_view` / `family_record` (the ledger has no profile name and must not store it, FR-137). The API sends `account_holder_view` and `items[].person`; the page falls back to its old logic only when `person` is absent (a record not served through those two paths).
- **Candidates:** `Manager.account_people()` is the profile's name (`you`) + `TaxYears.spouse_names()` in a person's library, `family_people()` in a family; the same name twice is one candidate.
- **Hyphen** reads as a word separator (`Mary-Jane` = `Mary Jane`), other punctuation is removed (`O'Brien`). The spec says "other punctuation removed"; this only makes `Anne-Marie Smith` match `Anne Smith` by the middle-word rule.
- **A cleared/corrected account holder keeps the reading's source line** (so Undo and Find are consistent); a holder set on a bill that printed none has an empty locator, so Find isn't offered.
- **Correct form kind** `detail_text` (not `text`, whose input is capped at 60 chars in trace.js; the server caps at 80).
- **Cut labels** for FR-136 are every FR-103 anchor phrase, every FR-128 key label and the account-name labels, at a word boundary after position 0 of the value.
- **BL-TOTAL's "Current Charges due ..." line** is today a 4th charge row (as the spec predicted for part B), so the tests assert Person cells as a set, not a count of 3.
- **Unlisted card:** the new family rule sits after the card rule as the spec orders it, so a bill with an unlisted card still asks about the card instead of suggesting by name.

## What is left

- **Part B** (FR-141 – FR-146: the due-now line, amount due = total, due-now detail row, payment matching, due date, photographed rule, several-bills rule) is untouched; nothing here blocks it (the account holder lives in `details["account_holder"]`; `bill_lines` got an `account` keyword; `ANCHOR_WORDS` is unchanged).
- **FR-149 remainder, not built:** the bill generator (evals/bill_layouts.py) account-name line forms, and the documents eval's `account_holder_read` count with the appended synthetic bill. The generator uses one shared `rng` per case, so adding a dimension shifts every drawn layout and the generator's exact pins; this is better done with part B's generator changes (due-now lines) in one go. Recorded in docs/open-work.md "PDF table engine" (new bullet) and docs/evals.md still describes only the existing counts.
- **Page text for non-bill-lines uses of the family `familyView`** (the inbox select) is unchanged by design.
- No docs/ui.md change was needed.
