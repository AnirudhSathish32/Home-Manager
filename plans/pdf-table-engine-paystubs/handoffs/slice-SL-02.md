```yaml
slice: SL-02
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 13837cd
end_head: c3e3a91   # the code commit; the handoff file is committed right after it
commit: c3e3a91
checks:
  - command: ".venv/bin/python -m pytest tests/test_paystub_engine.py -q"
    exit_code: 0   # 218 passed (156 from SL-01 + 62 new)
  - command: ".venv/bin/python -m pytest tests/test_table_engine.py -q"
    exit_code: 0   # 280 passed; table_engine.py and test_table_engine.py have no diff
  - command: ".venv/bin/ruff check src tests"
    exit_code: 1   # only the 2 errors that exist at START_HEAD (tests/test_document_v2_browser.py:410, tests/test_receipt_kinds.py:977); my files are clean
escalations: []
```

# SL-02 handoff: pay vs other tables, column roles, guesses, summary box

New `src/home_manager/finance/paystub_tables.py`; `tests/test_paystub_engine.py` extended (a section "Roles, guesses and the summary box"). `tests/paystub_engine_fixtures.py`, `documents/pay_tables.py` and `documents/table_engine.py` are untouched. No fixture expected value was changed; every role, guess and box value in the tests is the contract's.

## Interface (verified, for SL-03)
`paystub_tables.read(evidence: PDFResult) -> PaystubTables` calls `pay_tables.read(evidence)` and then:
- `tables`: the **engine's `PayTable`s that are pay tables**. The P4 adapter (`adapt`, `for_lines`) is SL-03, so these are not yet "adapted tables".
- `other_tables`: tables set aside (PS-OTHER's deposit and leave). Not in `tables`, so their rows are no pay lines.
- `roles: [Roles(table_id, roles: {column_id: current|ytd|hours|rate|other}, decided_by: numbers|headings|guess)]`, same order as `tables`.
- `box`: `{"current": {gross, taxes, deductions, net: Token}, "ytd": {...}}` of the first summary box, else `None`. `boxes: [BoxRead(id, page, columns: {column_id: gross|taxes|deductions|net|other}, rows: {"current": PayRow, "ytd": PayRow}, current, ytd, decided_by)]` for all boxes (a file of several stubs can have several). Values are the engine's `Token`s (exact `Decimal` in `.value[0]`, `.word_ids` for evidence).
- `guesses: [Guess(kind, page, table_id|None, text)]`; for a box `table_id` is the box id (`page-1-box-1`). `notes` = the guess texts in order. Kind names are constants in the module (`HEADINGS_OVERRULED`, `COLUMNS_GUESSED`, `GROUP_GUESSED`, `BOX_COLUMNS_GUESSED`, `SPLIT_CHANGED`); only the first, second and fourth are made here.
- `unplaced`: the engine's unplaced lines, kept only for pages holding a pay table or box (their note is SL-04). `pages`: set of pages with a pay table or box. `pages_without_tables`: the engine's list plus pages whose only tables are other tables. `viewer: []` is a placeholder (SL-05).
- Module-level helpers the tests use: `heading_role`, `multiplies`, `products`, `product_columns`, `pay_columns`, `smaller_on`, `order`, `decide`, `read_box`. `COLUMN_WORDS` is copied from `extraction.py:1045` (extraction will import this module in SL-03, so importing it here would be circular).

## Rules as built (plan P3.8, P5, P6)
- **Pay table (FR-56):** (a) finds a product, or (b) finds a pay column, or a column heading names this period or year to date, or it is the partner of a pay table. A table with none is an other table.
- **(a)** over unordered pairs and a third column, rows printing all three, at least one, using `document_checks.product` (the `hours_rate` rule: half-up, ±1 minor unit) against the third column's exact `Decimal` converted to minor units. One matching pair: the third column is this period; the rate is the column printing more decimal places, else the one headed Rate/Hours, else the right one. Two pairs sharing the rate column: both products are pay columns, (c) orders them, the hours column of this period's pair is hours, the other hours column stays other. Anything else: (a) decides nothing.
- **(b)** per gross/earnings/taxes/deductions total, the rows covered are those since the previous total (any kind) or the section's first row; a column is a pay column when every such total in it matches. Signs as printed.
- **(c)** voting rows print both columns, neither negative; the column never larger (and smaller on one row) is this period. All voting rows equal: headings, else the left (no guess record: either column gives the same values). Otherwise headings if they say, else FR-59.
- **FR-58:** when numbers decided and a heading names the other role, a `headings_overruled` guess with P5's text (variants naming only one heading when only one contradicts).
- **FR-59:** `columns_guessed`; `decided_by="guess"`.
- **(d)/(e):** with no pair and no pay column, the headings name current/ytd/hours/rate (one column per role). One pay column: its heading if it names year to date, else this period. When this period is decided and year to date is not, a unique column headed year to date takes that role (this is what makes the YTD column of SB's totals-less table `ytd`).
- **Box (P6):** the gross column is the largest on the row; the trio summing to it on both rows; net the largest of the trio on the this-period row (smaller gross, else the row labels, else the upper row). Heading words name taxes/deductions when exactly one or both are named consistently; otherwise left is taxes with a `box_columns_guessed`. A heading that names gross/net differently from the sums: sums win, a `box_columns_guessed` says so.

## Decisions to review
1. **Guess wording (G5).** For FR-59 I use P5's text for a tie ("Page N: the left column was taken as this period; the printed amounts didn't tell the two columns apart.") and for the "smaller on more lines" case "Page N: the {left|right} column was taken as this period, because it was the smaller one on more lines; the printed amounts didn't tell the two columns apart." P5 words the second as "the column smaller on more lines", but the contract says B2's note is "as (b1)" (contains `left column`), so the side is named. B2 passes with both words.
2. **Headings before a guess.** FR-59 reads "…and no deciding heading", so when the numbers can't tell two pay columns apart and the headings name them, the headings decide with `decided_by="headings"` and no guess (tested: B1's rows under `Current`/`YTD` and `YTD`/`Current`).
3. **Partner of a pay table** stays a pay table (FR-56) even if its own columns end up all `other`; P5's last bullet ("all other → other table") is applied to non-partners only. Nothing in the contract exercises this.
4. **More than two pay columns, or one pay column plus several others** are not ordered beyond "exactly one other pay column is YTD" and the unique-column rule in `later_year`; otherwise those columns are `other` (never money).
5. **Currency** for the product rule is the amount token's code, else `USD`; an unknown code means no match.

## Added tests (all expected values from the contract or worked by hand in the test)
SC-50, SC-55 (also with (a) switched off, so (b)+(c) alone give the same current/ytd), SC-56 (other tables, label-and-amount line count), SC-57 a and b, SC-61 a/b1/b2 (roles, guess record kind, page, text), SC-70 (SB, SB-SHUF, SB-NOHEAD box columns, rows, values as exact Decimals, the headless guess), SC-59 engine step, SC-69 roles, SBS/STK roles, determinism over all fixtures, and no float in the module. Extras built with `pf.page_of/lay/head` in the test: headings deciding without a guess, equal columns (first paycheck), negative rows not voting.

## Not done (later slices)
`adapt`/`for_lines`, Record wiring, `group_guessed` and `split_changed` guesses, unplaced and FR-64 notes, viewer data.
