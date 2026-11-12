```yaml
slice: SL-12
result: ready_for_verification
provider: claude            # fresh worker for the code review round 2 fixes
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: a4b8578
end_head: d00c3fa   # the handoff file is committed after this (its commit is not in the list)
commit: [d00c3fa]
checks:
  - command: ".venv/bin/python -m pytest tests/test_bill_split.py tests/test_bill_engine.py tests/test_bill_engine_generator.py tests/test_evals.py tests/test_receipt_segments.py tests/test_paystub_split.py -q -p no:cacheprovider"
    exit_code: 0   # 696 passed, 2 warnings, 465.36s
  - command: ".venv/bin/python -m pytest tests/test_bill_engine_record.py -q -p no:cacheprovider -k \"version or v49 or sc1\""
    exit_code: 0   # 81 passed, 9 deselected, 106.87s (includes the EXTRACTION_VERSION pin)
  - command: ".venv/bin/ruff check src/home_manager/documents tests/test_bill_split.py"
    exit_code: 0
escalations: []
```

# SL-12: fixes for code review round 2 (R2-1, R2-2)

Synthetic data only: nothing under P:\Finances, %LOCALAPPDATA%\HomeManager or P:\EvalCorpus was read or run. No migration. Not changed: spec, test contract, plan, approvals,
progress.yaml, reviews.md.

## Findings

1. **R2-1 (major, FR-128): alphanumeric account values keyed again.** `documents/bill_split.py` `key_of`: the account's *first* word may now be `ACCOUNT_START`
   (the old group of digits / hyphens / masking characters, or letters mixed with at least one digit such as `AB1234-5678-9012`, `ACCT-77889900`); the words after it
   must still be `ACCOUNT_GROUP` (digits, hyphens, `x X * •`), so the value stops at the first text field (`Service`, `Due`, `Page`). The key is the last four digits of
   the whole value; fewer than four digits, or a first word with no digit and no masking (`Service 1234`, `AB-CD`), gives no key. The SL-11 behaviour (`1234 5678 9012`
   vs `1234 5678 3456`, `XXXX XXXX 9012`) is unchanged. Tests (`tests/test_bill_split.py`):
   - `test_sl12_r2_1_alphanumeric_accounts_that_differ_with_every_date_and_amount_alike_are_two_bills` (a): `AB1234-5678-9012` / `AB1234-5678-3456` split `[(0,4),(4,8)]`.
     **Failed before the fix** (run with the source unfixed: 1 failed, plus 5 of the key cases below), passes after.
   - `test_sl12_r2_1_the_same_alphanumeric_account_in_an_equivalent_format_continues_the_bill` (b): hyphens vs spaces, a masked middle, `****9012` continue as one bill.
   - `test_sl12_r2_1_an_alphanumeric_account_keys_its_last_four_digits_and_stops_at_a_following_text_field` (d): includes
     `Account Number 1234 5678 9012 Service Address 12 Main St` -> 9012, the same with `AB1234-5678-9012`, and `... Due Date 10/15/2026`.
   - `test_sl12_r2_1_fewer_than_four_digits_or_a_first_word_with_no_digit_gives_no_key`.
   - (c) the SL-11 tests `test_sl11_f7_*` and the SC-126 key tests pass unchanged (`-k "sl12 or sl11_f7 or sc126 or sc128"`: 59 passed).
2. **R2-2 (minor, FR-126): docs example.** `docs/documents.md` ("Several bills in one file", Finding the bills): `Account no. xxxx 3456` now reads as keying `3456`;
   the fewer-than-four-digits example is `Account no. xxxx 345`; the alphanumeric form and the stop at a following field (`Service Address 12 Main St`) are mentioned.
   Headings unchanged.

## Version
`EXTRACTION_VERSION` is `typed-extraction-v49-bill-account-keys` (was v48). Bumped because a file whose bills print alphanumeric accounts was split correctly before
v48 but read as one bill at v48, so v48-read files must be read again on Extract again. The pin in `tests/test_bill_engine_record.py` and the sentence in
`docs/documents.md` ("Bill lines from the printed columns") follow; no other file pins the string (grep over src, tests, docs). `plans/pdf-table-engine-bills/`
files that mention v48 are history and were left alone.

## Not run
The full suite (the orchestrator's final run) and the browser tests. Real-bill accuracy is not measured (no corpus access).

## Not fixed / residual
- Nothing left unfixed. A later group that mixes letters and digits (`1234 5678 AB9012`) still stops the value, as the finding asked (only following numeric or masked
  groups accumulate).
