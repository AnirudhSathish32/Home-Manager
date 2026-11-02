```yaml
slice: SL-05
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: cc11dbf
end_head: 60115db      # the code commit; the handoff commit follows it
commit: 60115db
changed_files:
  - docs/money.md
  - docs/documents.md
  - docs/open-work.md
  - docs/evals.md
  - evals/tasks/receipt_tax_codes.py     # new
  - evals/tasks/__init__.py
  - tests/test_eval_tasks.py
checks:
  - command: ".venv/bin/python -m pytest tests/test_eval_tasks.py -q"
    exit_code: 0            # 19 passed
  - command: ".venv/bin/python -m pytest tests/test_eval_tasks.py -k tax_codes -q"
    exit_code: 0            # 2 passed, 17 deselected
  - command: ".venv/bin/ruff check src tests evals"
    exit_code: 0
escalations: []
```

## Docs (FR-20)
- `docs/money.md`: new `### Tax codes and tax lines` under "Item categories and splits" (heading unchanged). It covers what is kept
  (`tax_code`, `receipt_tax_lines`, `tax_source`), the `tax_source` table, FR-10 membership, sharing by code and the fallback with its
  reasons, items named in issues, issues never stored (Correct Tax changes only tax), the legend and the model's answer, earlier receipts
  and Extract again (incl. P8 and family copies), and a worked example on the synthetic R (445/4347/1400 = 4.45/43.47/14.00, against
  429/4190/1573 under the old rule). Edited in place: the Paid and footer bullets, "How items get a category" and rule 3.
- `docs/documents.md`: new `### Tax codes on receipts` before "Bill kinds" (what is read, the `taxed` rule, the checks, storage, the
  "details can't be read" case, `typed-extraction-v33-tax-codes`). Also replaced a stale pin of v32 in the table-engine section with a
  version-neutral sentence.
- `docs/open-work.md`: one entry, tax lines (and item tax codes) can't be corrected one by one (OD-4). No family-copy entry (P6 is built).
- No heading was renamed; no code comment's citation changed.

## Eval (FR-24)
- `evals/tasks/receipt_tax_codes.py`: 22 cases, 11 per shape (R and its 10 variants with a tax line per code; the SC-16 one-TAX-line receipt
  and its 10 variants). The first two print R's and SC-16's lines exactly as `tests/receipt_item_fixtures.py` does (asserted in the test).
  Run: `ExtractionService.extract` then `normalize`, like `receipt_kinds`.
  Grading: the first shape needs each tax line read with its code and an amount within 0.01 and each item's code to contain its line's
  code (B for the grocery items, T for the other); the second needs every item read and no BF item with `taxed` false. Report row per candidate.
- 22 cases because `test_every_task_has_enough_unique_cases…` wants at least 20 per task. Variant tax amounts are computed (rate on the
  taxable amount, half up); only R's own are the printed 1.01/1.73.
- `tests/test_eval_tasks.py`: oracle entry, a stub-model test (cases 1-2 with `r0_replies` / `one_tax_replies`: pass; then the filter code
  unread and BF answered untaxed: fail on exactly `all_codes` and `bf_untaxed`, with the report rows), and a grader unit test (a cent of
  slack, a wrong code, a T item untaxed is not the bug).
- `docs/evals.md`: row 17 in the task table; a `receipt_tax_codes` paragraph; run command `python -m evals.tasks --tasks receipt_tax_codes --config evals/models.toml`.

## Notes
- The one-TAX-line case also requires every item to be read (a missing item would otherwise pass trivially); the contract says only "no BF
  item read as taxed false". Flag if you want it strictly the contract's.
- Not run: the full suite, browser tests, and any live model or `P:\EvalCorpus`. `progress.yaml` still has the orchestrator's uncommitted edit.
