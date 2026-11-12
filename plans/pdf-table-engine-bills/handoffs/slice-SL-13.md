```yaml
slice: SL-13
result: ready_for_verification
provider: claude            # fresh worker for the code review round 3 fixes
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 608dcd8
end_head: f153ed4   # the handoff file is committed after this (its commit is not in the list)
commit: [f153ed4]
checks:
  - command: ".venv/bin/python -m pytest tests/test_bill_split.py tests/test_bill_engine.py tests/test_bill_engine_record.py tests/test_bill_engine_generator.py tests/test_evals.py tests/test_receipt_segments.py tests/test_paystub_split.py -q -p no:cacheprovider"
    exit_code: 0   # 822 passed, 2 warnings, 596.79s
  - command: ".venv/bin/ruff check src/home_manager/documents tests/test_bill_split.py tests/test_bill_engine_record.py"
    exit_code: 0
escalations: []
```

# SL-13: fixes for code review round 3 (R3-1, R3-2)

Synthetic data only: nothing under P:\Finances, %LOCALAPPDATA%\HomeManager or P:\EvalCorpus was read or run. No migration. Not changed: spec, test contract, plan,
approvals, progress.yaml, reviews.md.

## Findings

1. **R3-1 (major, FR-128): a later alphanumeric account group was truncated.** `documents/bill_split.py` `key_of`: `ACCOUNT_START` is gone; one `ACCOUNT_GROUP`
   (digits / hyphens / masking characters, or letters mixed with at least one digit) now applies to every word of the account value, so `AB1234 5678 CD9012`,
   `AB1234-5678-CD9012` and `****9012` all key `9012`, and `AB1234 5678 CD9012` vs `AB1234 5678 CD3456` split. The key is still the last four digits of the whole
   value, never a prefix. Still no key: fewer than four digits, a first word with no digit and no masking (`Service 1234`, `AB-CD`); the value still stops at a
   word that is none of those (`Service`, `Due`, `Phone`, `Page`). Tests (`tests/test_bill_split.py`):
   - `test_sl13_r3_1_a_digit_bearing_alphanumeric_group_counts_anywhere_in_the_account_value` (6 key cases, incl. a following `Service Address` / `Due Date`).
   - `test_sl13_r3_1_the_same_account_with_a_later_alphanumeric_group_continues_the_bill_in_any_format` (3 first forms x 5 second forms, through `bill_parts`: parts `[(0, 8)]`, no reasons).
   - `test_sl13_r3_1_accounts_with_the_same_prefix_and_another_tail_are_two_bills` (space and hyphen forms: `[(0, 4), (4, 8)]`, no reasons).
2. **R3-2 (major, FR-128): a following address/phone cell supplied the last four digits.** `bill_split.py`: new `cells_of(line)` gives the cell (number of `|` separators
   before it) of each word of `text_of(line)`; `key_of` takes the cells of the words after the label and stops the account at the first word outside the first
   value word's cell. A separator may still sit between the label and the value (`Account Number | AB1234-5678-9012`). `text_of` is unchanged, so dates and
   every other user of it key as before (`Due Date | 07/20/2026`, `Due Date | 10/15/2026 | 12 Main St`). Tests:
   - `test_sl13_r3_2_the_account_value_stops_at_the_next_cell` (7 cases incl. `AB1234-5678-9012 | 12 Main St`, `... | 212-555-0123`, label then separator).
   - `test_sl13_r3_2_digits_in_another_cell_never_complete_an_account` (`AB12 | 3456`, `123 | 4567 9012`, ...: no key).
   - `test_sl13_r3_2_a_repeated_account_beside_another_address_cell_continues_the_bill` (`[(0, 8)]`).
   - `test_sl13_r3_2_two_accounts_beside_the_same_phone_cell_are_two_bills` (`[(0, 4), (4, 8)]`).
3. **Unchanged behaviour, pinned:** `test_sl13_labelled_text_fields_still_end_the_value_and_the_older_forms_still_key` (`Service Address 12 Main St`, `Phone 212-555-0123`,
   `Due Date 10/15/2026`, `Account #:`, `Account No.`, `# #`, `xxxx 345` and `Service 1234` give no key) and `test_sl13_dates_key_the_same_with_or_without_cell_separators`.
   The SL-11 / SL-12 / SC-126 tests pass unchanged.
4. **Real path:** `test_sl13_the_real_evidence_path_splits_and_continues_on_the_account_cells` builds a synthetic `PDFResult` (two `PDFPage(method="vision_model")` of
   four `TextLine`s) and runs `evidence_lines -> bill_parts` for the reviewer's cases (repeated account beside an address cell: one part; different accounts beside
   one phone cell: two; space vs hyphen alphanumeric: one; different tail: two; masked: one), asserting parts and empty reasons.

**Failed before the fix:** with the source unfixed, `-k sl13` gave 24 failed, 12 passed (every R3-1 and R3-2 case above, plus the real-path test). After: all pass.

## Version
`EXTRACTION_VERSION` is `typed-extraction-v50-bill-account-cells` (was v49): split decisions for already-read files change for these layouts, so v49-read files are
read again on Extract again. The pin in `tests/test_bill_engine_record.py` and the sentence in `docs/documents.md` ("Bill lines from the printed columns") follow.
`docs/documents.md` "Several bills in one file" (Finding the bills) now describes alphanumeric groups throughout and the stop at the next cell (headings unchanged).

## Not run
The full suite (the orchestrator's final run) and the browser tests. Real-bill accuracy is not measured (no corpus access).

## Not fixed / residual
- A digit-bearing word in the same cell after the account with no label (`Account Number 1234 5678 9012 12th St`) is still read as part of the value: only labelled
  fields and cell boundaries end it. A cell boundary is the `|` the readers write; a line with no cells has no other boundary.
