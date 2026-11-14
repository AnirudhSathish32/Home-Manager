```yaml
slice: to-minor-sign-rule
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
worktree: /home/anirudh/Documents/Projects/Home-Manager-tominor
branch: to-minor-sign-rule
start_head: 92ec969
end_head: see "Heads" (the handoff commit follows the code commit)
commit: 90336e4   # code, tests, docs, version
checks:
  - command: ".venv/bin/python -m pytest tests/test_finance.py -q -p no:cacheprovider -k 'money or negative or marks'  (before the fix)"
    exit_code: 1   # 25 failed, 70 passed: `(-62.91)` and `-62.91-` read +6291
  - command: "same, after the fix"
    exit_code: 0   # 95 passed
  - command: ".venv/bin/python -m ruff check <changed .py files>"
    exit_code: 0
  - command: "targeted list below"
    exit_code: 0   # 1715 passed, 2 warnings, 19m51s
escalations: []
```

# to_minor sign rule: any negative mark, applied once

## Heads / commits
- start `92ec969` (branch `to-minor-sign-rule`).
- `90336e4` to-minor-sign-rule: the fix, tests, docs, EXTRACTION_VERSION v56.
- the handoff commit follows (`git log` on the branch).

## The fix
- `src/home_manager/core/money.py` `to_minor`: the three places that toggled `negative` (parentheses was a set, trailing minus and the two leading/after-symbol minus
  checks flipped it) now only ever set it: `negative = True` for a trailing minus, `negative or value[0] == "-"` for a leading minus and for a minus after the
  currency symbol. A `+` leaves it as it is, so `(+5)` stays negative. Everything else (currency code/symbol checks, `NUMBER`, precision, separators) is untouched.
  Side effect: `--5` / `-$-5` (two minuses) are now negative, where they were positive before.
- `src/home_manager/documents/extraction.py` `due_now_minor`: its own mark detection and `CR` handling are kept (they read marks to_minor cannot, such as
  `(62.91)-` or a code before the amount, and it validates paired parentheses/`$`). The final sign is now applied by `to_minor`, handed one leading `-` when negative
  (was `abs(to_minor(...))` then negating). Same results and same `MoneyError`s; the test_bill_printed_total.py sign table passes unchanged.
- `EXTRACTION_VERSION` bumped to `typed-extraction-v56-money-sign-rule`: a re-read of an already-read document whose model/printed amount is doubly marked
  (e.g. a receipt total `(-13.77)`, a statement row `-45.10-`) now stores a negative amount, where it stored a positive one. Pins updated in
  tests/test_bill_account_holder.py, test_bill_printed_total.py, test_bill_engine_record.py and the sentence in docs/documents.md ("Bills read before extraction version ...").

## Caller audit (80 `to_minor(` call sites in 19 files, plus `scripts/statement_records.py` and `evals/run.py`)
Looked for: a "-" prepended to a possibly negative string, an amount wrapped in parentheses, a printed credit negated expecting a positive. **None found.**
`grep` for `f"-{`, `"-" +`, `"(" +`, `lstrip("-")` in src finds only SQL (`-{RECEIPT_SPENT}`), dates and formatting, none feeding `to_minor`.

| Caller (file:line) | What it builds before `to_minor` | Verdict |
|---|---|---|
| extraction.py 3436 `due_now_minor` | rebuilds `[$]digits[ CODE]` from the due-now line | Changed to hand `to_minor` one `-` when any mark/CR is present; same behaviour |
| extraction.py 3531, 3532 `due_now_settled` | `as_decimal_text(figure)` / `format(Decimal,"f")` strings: a single leading minus at most | Safe |
| extraction.py 3622 `bill_lines` worked_out | `format(Decimal,"f")` strings | Safe |
| extraction.py 3446 `carried_minor` | model's field value, stripped | Safe (a doubly marked amount is now negative, as printed) |
| extraction.py 2795 `money()` / `cell_amount` text | `cell_amount` already prefixes at most one `-` when any mark is printed (the same rule) | Safe; consistent with the new rule |
| extraction.py 2923, 4551 | `abs(to_minor(...))` of the model's text | Safe (abs) |
| extraction.py 2986 | `printed_value` text: `$?digits` only, no marks | Safe |
| extraction.py 1054 | `str(abs Decimal)` from `line_amounts` | Safe |
| extraction.py 3185 | digits only (`COUNT_LINE`) | Safe |
| extraction.py `sign_return`, `minus_printed` | work on ints after parsing / on the cited quote | Not callers of the text rule; unaffected |
| finance/pdf_import.py 504 | `raw.amount` as printed, then `-value` if `positive_is_outflow` | Safe: parse is now right for `(-5.00)`, direction applied once after |
| pdf_import.py 511 | debit/credit wrapped in `abs()` | Safe |
| pdf_import.py 602 | `raw.balance` as printed | Safe |
| finance/statement_tables.py 147 `minor_of` | `f"{abs(value):f}"` | Safe (no marks) |
| finance/tabular.py 241, 249 | cell value, or `f"{exact:f}"` of a quantized Decimal parsed from a `-?digits` regexp | Safe (one minus at most) |
| finance/ledger.py 712, 2254, 2372, 2474, 3138 | typed text, then `<= 0`/`< 0` "must be positive" checks | Safe; `(-5)` is now correctly rejected, it used to pass as +5 |
| ledger.py 983, 2553 | `abs(to_minor(text))` | Safe |
| ledger.py 2743, 2882, 2948, 3008, 3107 | stored `as_decimal_text` strings or typed text, no rewrap | Safe |
| finance/family_corrections.py 92, 96 | typed text, positive check on 96 | Safe |
| finance/tools.py 1082 | `abs(to_minor(value.amount))` | Safe |
| finance/tax_tags.py 142 | typed text, `< 0` check follows | Safe |
| documents/donations.py 288 | typed text | Safe |
| finance/investments.py (868, 918, 941, 957, 992, 1012, 1031, 1032, 1048, 1136, 1289, 1290, 1342, 1381, 1425) | typed/model text, a few followed by `< 0` "zero or more" checks | Safe |
| finance/forecast.py (233 ... 644), scenarios.py 238, plan_tracking.py 36 | typed plan inputs | Safe |
| finance/tax_year.py (402-452), tax_zen.py 80, 344, tax_traces.py 361 | `str(typed text)` | Safe |
| household/tax_tables.py 235 | `str(Decimal)` from `printed_decimal` (no sign) | Safe |
| finance/paycheck.py 128 `cents` | typed text, negative rejected | Safe |
| paycheck.py 522 | `as_decimal_text` strings | Safe |
| scripts/statement_records.py 100, evals/run.py 195, 278 | the answer file's / the row's text, `format(value,"f")` of a Decimal | Safe |

## Tests
- Added in `tests/test_finance.py` (next to `test_money_parses_exactly`): 
  - `test_any_negative_mark_makes_an_amount_negative_once`: every subset of {leading `-`, `-` after `$`, parentheses, trailing `-`} (none, singles, pairs, triples, all four)
    × with/without `$` × with/without ` USD` (a minus after the `$` only with a `$`); 56 cases; negative whenever a mark is present, positive with none.
    The code sits inside the marks and parentheses wrap the rest, which is where `to_minor` reads them (`-(5)` and `62.91- USD` still raise, as before).
  - `test_marks_do_not_cancel_and_a_plus_never_cancels_a_minus`: `(-62.91)`, `-62.91-`, `(62.91-)`, `(+5)`, `(+5.00-)`, `-$-62.91`, `($-62.91-)`, `(5)`, `+5`; and `$(-5)`, `-(5)` still raise.
  - `test_money_stays_strict_with_negative_marks`: ambiguous separators, precision (EUR/JPY/KWD-style), another code or symbol, unpaired parenthesis, all with marks, raise `MoneyError`.
- Before the fix: 25 failed / 70 passed (including `(-62.91)` → 6291 and `-62.91-` → 6291). After: 95 passed.
- Existing tests that encode the toggle: none found. A grep for `(-…)`, `…-)`, `-…-` amount literals in tests finds only tests/test_bill_printed_total.py's due-now SIGN_CASES, which already assert "negative" (and pass). The three version pins were updated for v56; nothing else changed.

## Docs
- docs/money.md "Money rules": new bullet, "A printed amount has one sign rule".
- docs/documents.md: due-now sign sentence now points to that rule; version sentence is v56.
- docs/open-work.md: the entry "Doubly marked negative amounts read as positive" removed. No headings renamed.

## Commands run (cwd the worktree)
- `.venv/bin/python -m ruff check src/home_manager/core/money.py src/home_manager/documents/extraction.py tests/test_finance.py tests/test_bill_account_holder.py tests/test_bill_printed_total.py tests/test_bill_engine_record.py` → All checks passed.
- `.venv/bin/python -m pytest tests/test_finance.py tests/test_bill_printed_total.py tests/test_bill_engine.py tests/test_bill_engine_record.py tests/test_bill_account_holder.py tests/test_extraction.py tests/test_evals.py tests/test_paycheck.py tests/test_investments.py tests/test_statement_accounts.py tests/test_statement_forms.py tests/test_statement_rebuild.py tests/test_receipt_discounts.py tests/test_receipt_kinds.py tests/test_receipt_segments.py tests/test_receipt_tax_codes.py tests/test_paystub_engine_record.py tests/test_paystub_forms.py tests/test_paystub_split.py tests/test_bill_kinds.py tests/test_bill_corrections.py tests/test_bill_split.py tests/test_invoice_ingestion.py tests/test_layout_consumers.py tests/test_vision_tables.py tests/test_decisions.py tests/test_fx.py tests/test_dashboard.py tests/test_tax_return.py -q -p no:cacheprovider` → exit 0, 1715 passed, 2 warnings (19m51s).
- Not run: the full suite; test_tax_engines.py (it has known failures from before this change); browser tests.

## Open issues
None. Note for the orchestrator: bills/receipts/statements already read keep their stored amounts until **Extract again** (that is what the v56 bump triggers).
