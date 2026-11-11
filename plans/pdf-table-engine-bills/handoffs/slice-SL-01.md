```yaml
slice: SL-01
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 5a7dd8b
end_head: cc1d80d
commit: cc1d80d
checks:
  - command: ".venv/bin/python -m pytest tests/test_bill_engine.py -q"
    exit_code: 0   # 153 passed
  - command: ".venv/bin/python -m pytest tests/test_paystub_engine.py tests/test_table_engine.py -q"
    exit_code: 0   # 498 passed (unchanged modules)
  - command: ".venv/bin/python -m ruff check src/home_manager/documents/charge_tables.py tests/bill_engine_fixtures.py tests/test_bill_engine.py"
    exit_code: 0
escalations: []
```

# SL-01: the charge table engine (plan P3, engine side)

## Changed files (commit cc1d80d, three new files, nothing else tracked)
- `src/home_manager/documents/charge_tables.py` (new): `read(result) -> BillReading` with the P2 contracts (`ChargeColumn`, `SectionTitle`, `ChargeRow`, `ChargeTotal`,
  `Anchor`, `Unplaced`, `ChargeTable`, `BillReading`), the word lists (`ANCHOR_WORDS`, `LATE_WORDS`, `TOTAL_WORDS`, `CREDIT_SECTION`, `KEY_LABELS`, `PHONE`), and
  the helpers `anchor_kind(label)`, `key_kind(text)`, `usage_value(text)`. Pure; imports `table_engine` and `pay_tables` helpers only; neither is changed.
- `tests/bill_engine_fixtures.py` (new): every contract PDF fixture as a `FIXTURES` builder (BL-UTIL and all its variants incl. R1/R2, BL-PHONE, BL-RENT,
  MINI-BILL(k) and the multi-bill files, the title pages for SC-102 step 9), the engine-level facts, the `EXP_*` values and the stubs as data.
- `tests/test_bill_engine.py` (new): 153 tests, no store, no model, `no_network` autouse.

Not edited: spec, test contract, plan, approvals, `progress.yaml` (it shows ` M` in `git status`: the orchestrator's change, left alone and not committed).
This handoff is uncommitted.

## Coverage against the SL-01 row
SC-100 steps 1-3 (rent: one table, two rows, `3,200 GAL` label text; the `Payment Received 09/03/2026` anchor), SC-101 engine (three columns r330/r420/r520, labels
`This`/`Charge` for UTIL-2L, UTIL-ODD, UTIL-NOHEAD, plus SHUF/HEADLESS/LASTYEAR column structure), SC-102 steps 1 and 9 (phone rows, sections, totals, wrapped
label, every phone form in the table), SC-103 steps 1, 2, 4 (six anchors; both late variants; the word list in three cases per phrase, `Previous Balances Report`
is none), SC-104 step 1 (one unplaced line, 12-row other table, the 23-line accounting counted from the fixture's item list), SC-114 step 1, G7 and G14 tests,
P-checks for every fixture. Extra: table continuation over pages (BL-MULTI), key-line classes, determinism (item order shuffled), a page without layout.
Mutation spot checks (late rule, usage merge, sentence rule, phone form, wrapped label) each fail 1-15 tests.

## Notes for the orchestrator and later slices (none changes an expected value)
1. **`KEY_LABELS` and `key_kind` live in `charge_tables`**, not in `bill_split` (SL-06's file). The plan has `bill_split` import `charge_tables.anchor_kind` and
   `charge_tables` call `bill_split.key_of`, a cycle. SL-06 can move the list and import it lazily, or keep it here.
2. **G7's "sentence" is the plan's gap.** `is_sentence`: the label holds a multi-word anchor phrase and at least 3 other words (`SENTENCE_EXTRA`). Single-word phrases
   (`payment`) never make a sentence, so BL-PHONE's `Device Payment` and a billed `Late Payment Charge` stay rows. A sentence is an unplaced line (only on a page
   with a charge table).
3. **G14 with `Account ****9012`:** FR-128 would make it a key line. Key lines that are title-shaped and sit directly above a row can also be a `SectionTitle`
   (otherwise the plan's own "`Account ****9012` is a holder title" test could not hold). An unmasked account number title has `phone` False.
4. **PHONE guard:** a match that is one plain decimal word (`123.4567`) is not a phone (it would turn a rate into text). The plan's regexes are otherwise as
   written; `(ii)` allows no separator before the 4-digit group (`****9012`, as G14 needs).
5. **SC-102 step 9 pages have two rows** (`Plan` 10.00, `Device` 5.00), not one: one amount alone forms no column (FR-101), so a one-row page has no table to hold a
   title. This is the contract's own name-only fixture shape.
6. **Usage tokens.** A number followed in its run by a word with a letter (not `CR`/`DR`/ISO) becomes one token of kind `usage`, merged *before* `split_tails`
   (otherwise `1,234 kWh` before a rate would be cut apart). `ChargeRow.usage[col] = (printed text, word ids)`; the number is `usage_value(text)`. A usage cell that
   forms no column joins the row's label. Whole numbers form `integer` columns (`ChargeRow.amounts` holds the integer Token there); a table whose columns are all
   integer or usage is in `other_tables`. Roles (a table with no charge column) are SL-02's, which may move more tables to `other_tables`.
7. **`pages_without_tables`** = layout pages holding no table in `tables` (a page with only an other table, e.g. BL-REMIT page 2, is in it). SL-03's FR-114 note
   wording applies to those pages; `unplaced` is only kept for pages that hold a charge table.
8. **Section titles** also sit over a heading (title, one or two heading lines, row). UTIL rows therefore carry `Electric Charges` / `Taxes and Fees`, and BL-RENT's rows
   carry the line `Rent and Leasing Charges Due 10/01/2026` as their section. A section ends with a total.
9. **Layout line ids:** the saved layout makes one line per run in some rows (a BL-UTIL row lists three ids), one per row in others (BL-PHONE). `ChargeRow.line_ids` is
   `view.lines(word_ids)`, in word order. The adapter (SL-02) maps through `PageMap`, as planned.
10. **P-check wording:** word boxes are glyph boxes. A word ending in `1` ends about 1.6 pt short and a letter (`kWh`) about 0.65 pt, so the 0.5 pt agreement is asserted
    among the other words and 2 pt for the `1` ones. A column's `align` can read `centre` when all its values have equal width (BL-UTIL's `Days` column); its
    extent's right end is the stated edge.
11. **Stubs are data, not model replies.** They need the evidence line ids, so the `BillLines`/`BillSummary` replies are built in SL-03 (pattern: `Run.stub`). Also left
    for later slices: the PNG builders for MULTI-IMAGES/MINI-PNG (`mini_transcription(k)` and `make_receipt` give the inputs; `MULTI-SCAN` is `[None]*3` pages) and GEN
    (SL-09). The `EXP_*` and stub values are written from the contract and untested until SL-03 uses them.
12. `.venv/bin/python` without `PYTHONPATH=src` imports the main checkout's installed package; pytest uses the checkout's `src` (pythonpath), so the plan's commands are
    right.

No full-suite run (orchestrator's). No private data touched.
