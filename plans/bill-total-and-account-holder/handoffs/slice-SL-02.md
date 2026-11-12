```yaml
slice: SL-02
feature: bill-total-and-account-holder
part: B (the printed total and the due-now line, FR-141 - FR-146) plus the part-B pieces of FR-147 - FR-149 and what SL-01 deferred from FR-149
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 2577e5b
end_head: see the last commit of this branch (the handoff is committed after the code commits below)
commits:
  - 0761bce  the due-now line, the printed total as the amount due, due date, payment match, page row (code; WIP tests)
  - f9e1fb4  tests/test_bill_printed_total.py and the fixtures
  - 7dac783  generator, eval counts, diagnose, docs
  - 02dd187  browser test for the due-now row
  - (this handoff)
```

## How 62.91 became the counted amount, and how each path is fixed

The user's bill was never read (CLAUDE.md), so this is from the code and from synthetic BL-TOTAL run through the real `run`/publish path **before** my change (a probe, not kept).

| # | Path found | What it did to `Current Charges due 11/01/2026 $62.91` + `Total Current Charges $1,667.91` | Fix |
|---|---|---|---|
| 1 | **Engine path on a text PDF** (the user's case as described). `clean_label` gives `current charges due`, no anchor, so the line was a **4th charge row** (an item with amount 62.91, category none, recorded "as other"). `Total Current Charges` is a new-charges anchor, so `total_minor` was already 166791 and the model's new-charges answer lost to the anchor. The amount due stayed the **model's 62.91** (no amount-due anchor). The lines (1,730.82) no longer added up to the new charges, so the bill went to review with "New charges: the lines add up to 1,730.82 … but the bill's new charges are 1,667.91", and its line list held a 62.91 item. A line item's Paid in the Transactions page's items view is 62.91 here. | FR-141: `charge_tables.due_now_of` makes it a `due_now` anchor (never a row, never new charges, never an amount-due anchor). FR-142: the amount due is the printed total. The bill verifies and shows 1,667.91 as Paid. |
| 2 | **No engine anchor**: a photographed/scanned bill, a text page with no charge table, `BILL_FAILED`, the invoice re-read, a bill read before v47 (all "read like a photographed one"). The **model's own new-charges answer** cites the `Current Charges …` line and `bill_lines` sets `total_minor = new`: 62.91 counted, Paid 62.91. | `extraction.due_now_cited` (normalize): a new-charges answer that cites a due-now line is dropped, with the note "New charges: the cited line … is a due-now line, not the bill's new charges; it was left out." The lines' sum then counts. FR-145 where the model cites a `Total …` line too. |
| 3 | **The fallback to the amount due** (`bill_lines`, no new charges and no lines → `total_minor = due`) and `Ledger.publish_bill`'s `record.get("total_minor", amount_due_minor)`. With the amount due 62.91 (the model's, or the due-now amount), 62.91 was counted. | `bill_lines`: when the amount due equals the due-now amount, `total_minor` is `None` with the review reason "New charges: the bill's new charges were not read, and its amount due is the due-now amount … so nothing is counted; set the new charges." `publish_bill`: no fallback to an amount due that equals `details.due_now.minor`. |
| 4 | **`anchor_bill`'s `cited()` returning None** (anchor line not in the part) leaves the model's header value. | Not changed in `anchor_bill`; path 2's guard runs on the same record whenever the engine gave no due-now line, so a model new-charges answer citing a due-now line is still dropped. |
| 5 | **Bills already stored** (read before): keep 62.91 until **Extract again** (EXTRACTION_VERSION moved). | v52. A confirmed/rejected bill is never rewritten (FR-147); your earlier amount-due correction wins. |

OD-10 / SC-132 (b) (charge rows adding up to 62.91 with `Total Current Charges 1,667.91` printed): the bill **goes to review** with "New charges: the lines add up to 62.91 USD, but the bill's new charges are 1,667.91 USD. A line may be missing or misread." It stores `total_minor` **166791** (the printed total, so confirming it counts 1,667.91), `amount_due` 166791, `due_now` 6291. It is not on the Transactions page until confirmed; it never counts 62.91 silently (test below).

## What was built

`EXTRACTION_VERSION` is `typed-extraction-v52-bill-printed-total` (pins in tests/test_bill_engine_record.py, tests/test_bill_account_holder.py and the sentence in docs/documents.md updated).

| FR | Code | Tests (tests/test_bill_printed_total.py unless noted) |
|---|---|---|
| FR-141 due-now line | `documents/charge_tables.py` `DUE_NOW`, `DUE_NOW_LINE`, `due_now_of`, `Anchor.label/.date`, `classify` (due-now first, then `anchor_kind`); consumed like any anchor so never a row/unplaced; `documents/bill_split.py` `anchor_of` | `test_fr141_a_new_charges_or_amount_due_phrase…` (6 rows), `test_fr141_other_labels_are_not_due_now_lines` (9 rows), `…amount_due_by_a_date_stays_an_amount_due_anchor`, `…the_engine_finds_it_as_an_anchor…`, `…a_late_line_is_never_a_due_now_line` |
| FR-142 amount due | `documents/extraction.py` `anchor_bill` ((a) total-worded tie; (b) previous balance − payments + new charges, else new charges, else due-now amount; notes), `details.amount_due_worked_out` + `finance/document_traces.py` (no carried check when worked out) | `test_sc132_a_the_user_s_bill_counts_the_printed_total…`, `test_sc137_…`, `test_sc138_…`, `test_sc141_a_a_plain_amount_due_beside_the_total_keeps…` (OD-2); tests/test_bill_engine_record.py `test_sc117_c_nothing_decides_so_the_total_is_used_with_a_guess_note` (SC-141 (c)) |
| FR-143 kept, shown, matches a payment | `bill_lines` (`details.due_now` when it differs), `Ledger.bill_summary` (`due_now` row), `static/receipt.js` `billSummaryRows`, `Reconciler.bill_payment` | `test_sc132_a_the_page_rows_end_with_the_amount_due…`, `test_sc132_a_a_payment_of_the_due_now_amount_or_of_the_total…[-6291, -166791]`, `test_fr143_a_payment_of_some_other_amount…`, browser `test_due_now_the_page_shows_the_printed_total_as_the_amount_due…` |
| FR-144 due date | `extraction.due_now_settled` (missing/dropped → the line's date, cited to it; both kept and different → note "The bill also prints …") | `test_sc132_c_with_no_due_date…`, `test_sc132_c_a_dropped_due_date…`, `test_sc132_d_a_printed_due_date_stands…` |
| FR-145 photographed | `extraction.due_now_cited` | `test_sc140_…reads_the_total`, `test_sc140_…plain_amount_due_reads_exactly_as_before`, `test_sc132_the_model_s_new_charges_citing…`, `test_sc132_a_due_now_amount_is_never_what_a_bill_counts_even_when_nothing_else_is_read`, `test_sc132_a_bill_read_after_the_engine_failed…` |
| FR-146 several bills | `bill_split.bill_parts` `has_due` counts a due-now line | `test_sc142_each_bill_of_a_file_prints_a_due_now_line…`, `test_fr141_a_due_now_line_is_a_parts_own_amount_due_for_the_split_rule` |
| FR-147 | version bump; corrections via the existing `apply_corrections` | `test_sc143_the_version_moved_…`, `test_sc143_a_correction_of_the_amount_due_…`, `test_sc143_a_confirmed_bill_is_never_rewritten` |
| FR-148 | deterministic by construction | `test_fr148_a_second_reading_changes_nothing…`; the generator and engine suites pass unchanged (except the tests below) |
| FR-149 | `scripts/statement_diagnose.py` (`due-now lines: N`); generator `evals/bill_layouts.py` (`ACCOUNT_LINES` label forms incl. one followed by an account number on the same line; `DUE_NOWS`: beside an amount due, or alone where it would be, with/without previous balance and total current charges); eval `evals/run.py total_counts`, `evals/graders.py bill_reader` (`account_holder_read`, `due_now`, `amount_due_total`), `evals/report.py` allowlist, `evals/synthetic.py` `TOTAL_BILL_FILES` (sixth bill file appended last; the five fixed files draw `account_line="none"`, `due_now="none"` so nothing existing moves) | `test_sc145_diagnose_counts_due_now_lines…`; tests/test_bill_engine_generator.py (every case incl. the new dimensions, `REQUIRED` coverage of each new form); tests/test_evals.py `test_bill_readers_count_account_holders_due_now_lines_and_printed_totals_and_only_counts_reach_the_summary` |
| FR-150 docs | docs/documents.md (both sections), docs/money.md "Bills and their lines", docs/evals.md, docs/open-work.md (the entry rewritten) | doc diff |

New fixtures (tests/bill_engine_fixtures.py): `total_pages(extra=)`, `TOTAL_NOW_ROWS`/`STUB_TOTAL_NOW` (BL-TOTAL-NOW), `total_transcription` (BL-TOTAL photographed), `due_carried_pages` (BL-DUE-CARRIED), `total_due_pages` (BL-TOTAL-DUE), `mini_items(due_now=)`/`mini_due_pages` (MINI-DUE); registered in `FIXTURES`.

## Existing tests changed, and why (the spec lists SC-117 (c); everything else is listed here)

- tests/test_bill_engine_record.py `test_sc117_c_nothing_decides_so_the_first_on_page_one_is_used_with_a_guess_note` → renamed `…the_total_is_used…`: amount due 14755 (was 5000), note "…; 147.55, the total, was used." (SC-117 (c) / SC-141 (c)).
- tests/test_bill_engine_record.py `test_sc117_a_late_payment_amount_is_never_the_amount_due`: built on BL-UTIL-R1 (c), so its amount due is now 14755 (was 5000). The point of the test (the late 102.55 is never the amount due) still holds. A consequence of SC-117 (c), not a separate behaviour change.
- tests/test_bill_engine_record.py / tests/test_bill_account_holder.py: the version pin.
- tests/test_bill_split.py `Bills.answer`: a new `amount_label` keyword (default unchanged) so MINI-DUE's model double cites the due-now line; no test of it changed.
- tests/test_bill_engine_generator.py: `DUE_GUESS` accepts "the total" besides "the first on page N" (FR-142 (a)); `assert_bill` also checks the account holder and the due-now detail, and that no carried check runs where the amount due was worked out; the model double cites the due-now line for the amount due when none is printed; the phone-notes rule accepts the two due-now notes; `REQUIRED` gains the new dimensions' tags; one added invariant that the due-now part is never the new charges or the amount due.
- tests/test_evals.py: corpus count pins 58 → 59 (documents, dry run "177 documents", `bill: 8`, slices `everything[53:58]`, six aligned bill cases with answer counts `[1,1,1,1,1,3]`); the `bill_reader` dict pin gains the three zero counts. The first 53 documents' hash (`BEFORE_BILLS`) and the five aligned bills' ids and answers are unchanged.

## Verification (from /home/anirudh/Documents/Projects/Home-Manager-billtotal; `.venv/bin/python -m pytest … -q -p no:cacheprovider`)

| Command | Result |
|---|---|
| `tests/test_bill_printed_total.py tests/test_bill_engine.py tests/test_bill_engine_record.py tests/test_bill_corrections.py tests/test_bill_split.py tests/test_bill_account_holder.py tests/test_evals.py tests/test_bills_ledger.py tests/test_bill_kinds.py tests/test_extraction.py tests/test_receipt_segments.py` | exit 0, **772 passed, 1 skipped** (the opt-in browser test in test_bills_ledger.py), on the final tree |
| `tests/test_bill_engine_generator.py` (every generated case, incl. the new account-name and due-now dimensions) | exit 0, **281 passed** |
| `RUN_BROWSER_TESTS=1 tests/test_bill_engine_browser.py` | exit 0, **6 passed** (incl. the new due-now row test) |
| `.venv/bin/ruff check src scripts evals tests/test_bill_printed_total.py tests/bill_engine_fixtures.py tests/test_bill_split.py tests/test_bill_engine_record.py tests/test_bill_engine_generator.py tests/test_evals.py tests/test_bill_engine_browser.py` | All checks passed |

Not run: the full suite; `tests/test_bill_kinds_browser.py` (its SC-48 test fails at baseline on today's date). `tests/test_bill_account_holder.py` is in the 772 and passes with the part-A tests unchanged except the version pin.

## Decisions I had to make

- **Where the due-now line is recognised:** by label alone (`DUE_NOW_LINE`: a new-charges/amount-due phrase, then `due`, `due on`, `due by` or `payable by`, then a date, nothing else), before `anchor_kind`, after the late check. Everything after the amount on the line is ignored as for any anchor.
- **Photographed bills** use the same label rule on the lines the model's amount due / new charges cite (`due_now_cited`), also whenever the engine gave no due-now line (BILL_FAILED, a text page with no charge table).
- **The first due-now line** of a bill is the one kept (a bill printing it twice, e.g. in the summary and on the stub, keeps one).
- **Numeric dates** that read two ways (`11/01/2026`) are month first for the due date taken from the line (`dates_in`'s first reading); a model due date kept by the date check wins. Recorded in open-work.
- **No carried check where the amount due was worked out** is stored as `details.amount_due_worked_out` (the page's check list is computed from the stored record, so a flag at read time was not enough).
- **Evidence for the worked-out amount due** cites the previous balance, payments and new charges lines; for "the total" it cites the new-charges line.
- **The generator** draws the two new dimensions with `pick`, which is independent of the shared random stream, and uses no random draw for them, so no existing draw shifts; a few existing cases print one more line. The fixed corpus files name the new dimensions as "none", so no corpus id or answer moved.

## What is left

- Not run (per instructions): the full suite; `tests/test_bill_kinds_browser.py::test_sc48_a_rent_bills_page_its_lines_and_its_kind` fails at baseline (date-dependent) and was ignored.
- The real bill is unread (OD-10). If its lines add up to 62.91 it still goes to review (above).
- The Bills page and the forecast still follow the new charges (OD-1); noted in docs/open-work.md.
- A bill read before v52 keeps its old amount due until Extract again.
