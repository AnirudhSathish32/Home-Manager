```yaml
slice: SL-06
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: b3cc333
end_head: e0e1e0c   # last code commit; the handoff commit follows it
commit: e0e1e0c
checks:
  - command: ".venv/bin/python -m pytest tests/test_receipt_tax_codes.py tests/test_splits_by_code.py -q"
    exit_code: 0   # 78 passed
  - command: ".venv/bin/python -m pytest tests/test_receipt_kinds.py tests/test_extraction.py tests/test_reextraction.py -q"
    exit_code: 0   # 74 passed
  - command: ".venv/bin/ruff check src tests"
    exit_code: 0
escalations: []
```

Code review round 1 fixes, only these two:

1. FR-22: `food_stamp_meaning` (extraction.py, beside `FOOD_STAMP`) replaces the whole-quote food-stamp test in the legend loop. It looks only at the text printed for the entry's own code (after its `=`/`:`, up to the next code's definition or a `;`/`|`). A citation that shows no definition for the code is still judged as a whole, so a standalone "F = FOOD STAMP" entry is still dropped. On "T = TAXABLE; N = NON-TAXABLE; F = FOOD STAMP", T and N are kept and only F is dropped.
2. FR-09: `rate_printed` replaces `printed_in` for tax-line rates only. The rate must equal, as a Decimal, one whole number token (core.money `NUMBER`) printed in a cited line. `printed_in` is unchanged for its other callers.

Tests added to tests/test_receipt_tax_codes.py: the SC-14 combined-legend-line case (flags mug 1 / bread 0, source legend, shares 862/300, an F entry not used) and a rate parametrization (7.75000 and 7.75 kept; 75 and 7.7 left out with the existing issue). Against the old code the combined-legend test and the 75 and 7.7 cases fail.
