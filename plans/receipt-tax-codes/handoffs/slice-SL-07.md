```yaml
slice: SL-07
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 068cd52
end_head: bfc70e6   # code commit; the handoff commit follows it
commit: bfc70e6
checks:
  - command: "pytest tests/test_receipt_tax_codes.py tests/test_splits_by_code.py -q"
    exit_code: 0   # 89 passed
  - command: "pytest tests/test_receipt_kinds.py tests/test_extraction.py tests/test_reextraction.py -q"
    exit_code: 0   # 74 passed
  - command: "ruff check src tests"
    exit_code: 0
escalations: []
```

# SL-07: fix for code review round 2 (CR2-M1)

`food_stamp_meaning` (src/home_manager/documents/extraction.py) cut an entry's meaning at the next `word:`/`word=`, so in
"F = EBT: ELIGIBLE" the F entry's meaning was empty and F was not dropped. Now a start whose word ends exactly where a `FOOD_STAMP`
match ends (EBT, SNAP, FOOD STAMP) is not a boundary, so the check sees "EBT: ELIGIBLE". CR1-M1 is unchanged: the combined line
"T = TAXABLE; N = NON-TAXABLE; F = FOOD STAMP" still keeps T and N and drops only F. No change to sharing, storage, UI or contracts.

Tests (tests/test_receipt_tax_codes.py): a parametrized unit test of `food_stamp_meaning` (9 cases, incl. the combined lines and
"FOOD STAMP:"), and the reviewer's case through extraction and publication for "F = EBT: ELIGIBLE" and "F = SNAP: ELIGIBLE"
(flags TF 1, N 0, source 'legend', amounts (1100, 62, 1162), shares 862/300). Against START_HEAD's extraction.py, 5 of these new
cases fail (3 unit, 2 end-to-end); with the fix all pass.

Also moved the `SimpleNamespace` import into ruff's sorted position. Open issues: none.
