```yaml
slice: SL-04
result: ready_for_verification
provider: claude            # route provider instance: claudeAgent
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 0ab6f53
end_head: 32fb96d
commit: [b244221, 32fb96d]  # b244221 source, 32fb96d tests. This handoff file is left uncommitted for the orchestrator.
checks:
  - command: ".venv/bin/python -m pytest tests/test_bill_engine_record.py -q"
    exit_code: 0   # 84 passed (70 from SL-03 + 14 new)
  - command: ".venv/bin/python -m pytest tests/test_bill_kinds.py tests/test_bills_ledger.py tests/test_recurring_bills.py tests/test_provenance.py -q"
    exit_code: 0   # 131 passed, 1 skipped (opt-in browser test)
  - command: ".venv/bin/python -m pytest tests/test_bill_engine.py -q"
    exit_code: 0   # 233 passed
  - command: ".venv/bin/python -m pytest tests/test_layout_consumers.py tests/test_extraction.py tests/test_invoice_ingestion.py tests/test_receipt_kinds.py tests/test_paystub_engine_record.py tests/test_paystub_split.py -q"
    exit_code: 0   # 180 passed (extra regression run: the code I touched is shared with pay stubs and invoices)
  - command: ".venv/bin/python -m ruff check src/home_manager/documents/extraction.py src/home_manager/finance/document_traces.py tests/test_bill_engine_record.py"
    exit_code: 0
escalations: []
```

# SL-04: repeated values, amount due printed several times, new charges worked out (plan P6)

No failure occurred in any command, so nothing in `baseline_failures` was hit. No private data touched.

## Changed files
`b244221` (source):
- `src/home_manager/documents/extraction.py`
  - `anchor_bill` (the `ANCHOR_FIELDS` loop is replaced). It now returns a ninth value, `worked_out`.
    - **Repeats (FR-111).** For previous balance, payments and new charges, the distinct values (payments by magnitude, so `-100.00` and `100.00` are one) are taken in reading order (`anchor.order`). The first is used. When there are several, the note is `The <previous balance|payment received|new charges> is printed as A and B; A, the first on page N, was used.` (A, B are the printed token texts, a value printed alike once).
    - **Amount due (FR-117).** One distinct value is used as before. With several, in first-printed order: when previous, payments and new charges are all anchored, the first `v` with `prev - |pay| + new == v`; else when no new charges are printed or worked out (FR-118 not in play), the first `v` equal to the signed sum of the lines `anchor_bill` keeps (credits negative); else (or when no value satisfies the branch) the first value with the note `The amount due is printed as X and Y; X, the first on page N, was used.` and `Guess("amount_due", page, None, text)` in `guesses`.
    - **Worked out (FR-118).** When there is no new-charges anchor but a previous-balance anchor and a payments anchor (a printed 0.00 counts) and an amount-due anchor: `worked_out = {amount_due, previous_balance, payments, new_charges: due - prev + |pay|, locator}` as decimal text, the locator being the three anchors' lines and quotes. The header's `new_charges` is replaced by a `missing` Value, so the model's new charges are not used.
    - The anchor-to-header-`Value` plumbing (the amount's own line, the amount word as the quote, the cell reference) is now a local `cited(anchor, kind)`.
  - `worked_out` is threaded: `read` returns it in the reading dict, `record` passes it to `publish`, `publish` to `normalize`, `normalize` to `bill_lines` (`worked_out=None` keyword each).
  - `bill_lines`: when `worked_out` is set (and its currency has an exponent), `record["new_charges_minor"]` is the worked-out value, `details["new_charges"] = {"minor", "locator", "worked_out": {"amount_due","previous_balance","payments"} (minor)}`, and the note `New charges aren't printed; worked out as amount due A − previous balance P + payments R = N.` (U+2212 minus, plain decimals) is added. The lines check is the existing new-charges one (G3: `New charges: the lines add up to X, but the bill's new charges are N …`). The carried check is not run.
- `src/home_manager/finance/document_traces.py` `bill_checks`: when `details.new_charges.worked_out` is set, the `lines` check's inputs are the lines plus Amount due, Previous balance and Payments received (each with its provenance), its formula reads `…the new charges worked out as the amount due A − previous balance P + payments R = N; the bill doesn't print them.`, and the `carried` check is not offered (so it is not among `record["checks"]` either).

`32fb96d` (tests): `tests/test_bill_engine_record.py`, 14 new tests:
- SC-111 step 4 (`sl04` in the names): `Previous Balance` 82.10 then 90.00 (note names 90.00, carried holds, C-auto); 90.00 first then 82.10 (9000 used, note, `Amount due: previous balance 90.00 USD … 97.55 USD`); and 82.10 printed twice (no note).
- SC-117 (a), (b), (c), and the late-payment case (UTIL-LATE-COL with R1 (c)'s box: 102.55 appears in no note, issue or guess).
- SC-118 R2, R2-BAD, R2-NOPREV. R2 reads the lines check's trace through `traces.trace` and asserts the three inputs and the working in the formula.
- SC-121 steps 1 – 3 for cases (1) and (2) (case (3) is SL-06's), and SC-122 R1 (c) (`sl04` in the name).

## Things the plan or contract left to the worker, or that differ from their wording
1. **Which previous/payments/new values FR-117 uses.** Only anchored (printed) values count, not the model's, so a previous balance the model supplied with no anchor never decides the amount due. The contract's fixtures all print them.
2. **FR-117 falls to the guess when its check branch finds no value.** E.g. previous, payments and new charges are printed but no amount due satisfies the carried check: the first value is used with the guess note, and the carried check then fails as today. The spec says "if no check decides … the first … with the guess note"; the plan's text doesn't say what happens when a branch finds nothing.
3. **SC-118 R2-BAD "spending counts 10055 until corrected".** A bill in To check isn't in `get_spending` (model-extracted rows count once verified; `tools.py`). The test verifies the bill through `Ledger.review` first and then asserts spending 10055 on 2026-10-15 (R2: 9755 with no review needed, since it is C-auto). `total_minor` is 10055 as the contract says.
4. **SC-121 step 3.** The test asserts the migrations listing is 001..080 with `080_split_merged_documents.sql` last (80 files, no gap). It doesn't embed the 80 names.
5. **SC-121 (1)/(2) seeding.** The v39 reading is made with `EXTRACTION_VERSION` patched and the engine fault double (the model's lines used), inside `monkeypatch.context()`, then (1) left `needs_review` by SQL and read again, (2) verified with `Ledger.review` and read again, with the `receipts`/`receipt_items` rows compared before and after (`SELECT *`, so `updated_at` is included and is unchanged). The `reused` value in the contract is `False`; `enqueue` returns `(run_id, True)` when it makes a new run, and the tests assert exactly that.
6. **SC-118 step 4** (photographed rent bill unchanged) is covered by the second verification command (`tests/test_bill_kinds.py` passes unchanged); no new test.
7. **Stubs again wrong-but-printed.** R1's stub answers amount due `50.00` (printed in the banner); R2's `150.00`/`100.00`; for R1 (b) and R2-NOPREV the new charges are `MISSING` (no new charges printed and none worked out, so the model's value would stand and fail the lines check); R2-NOPREV's amount due is `12.00`, printed but wrong, replaced by the anchor's 147.55.
8. **Guess list.** Read from `record["details"]["guesses"]` (SL-03 stores it there).

## For later slices
- `anchor_bill`'s return value is now a 9-tuple; SL-06 scoping anchors per bill (BL-MULTI) works through `part.reading.anchors` as before, so FR-117/FR-118 apply per part with no further change (`for_lines` already restricts the anchors).
- `worked_out` flows as a reading key; `read` for a split part should return its own.
- SL-10 can count `amount_due` guesses from `details["guesses"]` (kind `amount_due`, page, text).

## Checks not run
Browser tests and the full suite (the orchestrator's). SC-111 step 3 (browser) is SL-08's.
