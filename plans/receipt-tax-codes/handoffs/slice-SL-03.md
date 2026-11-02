```yaml
slice: SL-03
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 29afc51
end_head: 2c8ba59          # the code commit; the handoff commit follows it
commit: 2c8ba59
changed_files:
  - src/home_manager/documents/extraction.py
  - tests/receipt_item_fixtures.py
  - tests/test_receipt_tax_codes.py
  - tests/test_table_engine_record.py
checks:
  - command: ".venv/bin/python -m pytest tests/test_receipt_tax_codes.py tests/test_splits_by_code.py -q"
    exit_code: 0            # 73 passed (45 + 28)
  - command: ".venv/bin/python -m pytest tests/test_receipt_kinds.py tests/test_table_engine_record.py tests/test_receipt_segments.py tests/test_extraction.py tests/test_reextraction.py tests/test_receipt_item_table.py tests/test_eval_tasks.py -q"
    exit_code: 0            # 211 passed (run through `| tail`, so the shell code is tail's; the summary line has no failures)
  - command: ".venv/bin/ruff check src tests"
    exit_code: 0
escalations: []
```

## What changed (`documents/extraction.py`)
- **Schema.** `Item.tax_code` (default None); `TaxLine` (code, rate, taxable_amount, amount, evidence) and `TaxCodeMeaning` (code, taxed, evidence);
  `DETAIL_FIELDS["receipt"]` = `tax_lines`, `tax_legend` (both default empty), so the general `ReceiptSummary` and every `Receipt<Kind>Summary` carry them
  (bills do not). `NEW_FIELDS` gains `ReceiptSummary`, the two fields on each receipt form, `Items` -> `tax_code`, `GroceryItems` + `tax_code`. `SCHEMA_FIELDS`
  includes both new models. Nothing new is required, so earlier stubs and answers still validate (tested).
- **Instructions.** `LABELS["receipt"]` explains `tax_lines` and `tax_legend` (never a single TAX line, a total, a lineless code, or a food-stamp/EBT/SNAP
  meaning). The item row prompt now has a `tax_code:` sentence and the FR-24 `taxed:` sentence. One constant, `TAXED_RULE`, is used by the prompt and by
  `Item.taxed`'s own Field description, so the schema the model gets says the same.
- **`tax_codes()`** (called in `normalize`'s receipt branch after the items, before `sign_return`):
  - an item's code (whitespace collapsed, upper case) is kept only when it appears as its own mark in one of the item's cited lines
    (letters either side don't count: the T of "WATER FILTER" is not a T mark; "4.29B" is a B mark), else an issue "Item n tax code was not printed where it was cited and was left out.";
  - a tax line needs a code printed in its citation; rate, taxable amount and amount are each kept only when printed in a citation (an amount that is
    not stays `None` with an issue; the line is kept). Amounts are stored as magnitudes. If any line has no (valid) code, no lines are kept (P1/FR-21);
  - with kept lines: `tax_source='tax_lines'`, taxed derived per item (FR-10/FR-11/P7: exactly one line code in the item's code, whose summed amount is > 0 or unreadable);
  - else with legend entries that some item's code contains: `tax_source='legend'`, taxed = the one meaning the item's code holds (contradicting or several
    different meanings give None; an entry whose quote names food stamps, EBT or SNAP is ignored, as a guard behind the prompt);
  - else `tax_source='printed'` (the model's flags stay). With `details` False (new fields failed twice) it is `printed` with no codes or lines.
  - `record["tax_source"]`, `record["tax_lines"]` and each item's `tax_code` feed `publish_receipt` (SL-01). `EXTRACTION_VERSION` = `typed-extraction-v33-tax-codes`.
- Imports `printed_code` from `finance/splits.py` so the item/line code comparison is the same one the sharing rule uses.

## Tests
- `tests/receipt_item_fixtures.py`: `r0_replies(lines, codes, taxed, tax_lines, legend, tax, total, rows)` (R0 and its variants), `r_tax_lines`,
  `tax_line_reply`, `legend_entry`, `r_one_tax_lines` and `one_tax_replies` (SC-16/SC-18's lines).
- `tests/test_receipt_tax_codes.py` (all through the real extraction service, `local_model` stub): SC-01 (+ second Record, restart, C-cited tax lines and item
  links), SC-03, SC-04, SC-05, SC-06, SC-08 (+ b, c), SC-13, SC-14, SC-15 (three lines, B summed), SC-16 (prompt text, schema description and fields asserted on
  `local_model["requests"]`; 449/4384/1359), SC-18 (+ all-answered variant 429/4190/1573), `legend_food_stamp` (TF takes T's meaning; a stray F entry is ignored),
  `new_fields_fail` for a general (D) and a grocery (R0) receipt, an unprinted code, an unprinted tax-line amount, an uncoded/unprinted line code, the
  `NEW_FIELDS` coverage test, and the version test. Every expected share is the contract's number.
- `tests/test_table_engine_record.py`: the v32 pin is now `!=`.

## Things the verifier should know
- **Fixture variants where the contract's stub names a code the receipt's own line doesn't print.** The plan's rule keeps a code only when it is printed in
  the cited line (FR-08), so SC-06's "Ruffles BT" prints `071057174 RUFFLES BT $4.29` in that test's transcription, and SC-08's R1 (filter coded N) is read from
  a new transcription of the same document whose filter line prints `... WATER FILTER N $12.99` (`manager.start_receipt(force=True)`, then Extract again). Stub values,
  expected codes and shares are unchanged. SC-04 prints `TAX $2.84` and `TOTAL $62.02` (the tax and total can't be cited otherwise); SC-15 prints B as two lines
  (`B = GA STATE TAX 2.17000 on $46.19 $1.00`, `B = LOCAL TAX 1.58000 on $46.19 $0.73`).
- SC-01's C-cited for items checks the evidence links' line ids (`line-4`, `line-5`+`line-6`, `line-8`).
- Extra issues the plan didn't list (each only when a printed-check fails): "Tax line n rate/amount/taxable amount was not printed where it was cited and was left out." and
  "Tax line n code was not printed where it was cited, so the tax lines were not used."
- No docs, UI or `progress.yaml` changes. `progress.yaml` still has the orchestrator's uncommitted edit.
- Not run: the full suite and browser tests (not in the slice's commands). No pre-existing failure appeared in the commands run.
