```yaml
slice: SL-02
result: ready_for_verification
provider: claude            # route provider instance: claudeAgent
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 6218ae8
end_head: 4782414
commit: 4782414
checks:
  - command: ".venv/bin/python -m pytest tests/test_bill_engine.py -q"
    exit_code: 0   # 233 passed (153 from SL-01 + 80 new)
  - command: ".venv/bin/python -m pytest tests/test_paystub_engine.py tests/test_table_engine.py -q"
    exit_code: 0   # 498 passed (unchanged modules)
  - command: ".venv/bin/python -m ruff check src/home_manager/finance/bill_tables.py tests/bill_engine_fixtures.py tests/test_bill_engine.py"
    exit_code: 0
escalations: []
```

# SL-02: roles, money off, the rate rule, guesses and the adapter (plan P4)

## Changed files (commit 4782414)
- `src/home_manager/finance/bill_tables.py` (new). Contracts `Roles`, `Guess`, `PrintedRate`, `BillTables`; `GUESS_KINDS` and the four kind constants; `ROLES`;
  `printed_rate(text, currency)`; `signed(token, section)`, `money_off(row, roles)`, `charge_column(roles)`; `decide(table, anchors)`; `adapt`; `read(evidence)`;
  `for_lines(bills, line_ids)`. Imports only `charge_tables`, `paystub_tables` (`PageMap`, `cell_of`, `spans_of`, `evidence_index`, `multiplies`, plus `adapt_header` and
  `page_number`), `document_checks.decimal` and `core.money.EXPONENTS`. Nothing else is changed (`charge_tables`, `paystub_tables`, `table_engine` untouched).
- `tests/bill_engine_fixtures.py`: `phone_pages(discount, credits)` (defaults give the old BL-PHONE; SC-106's variants use the parameters) and `role_pages(...)`, a small
  hand-built page for the role tests. Not added to `FIXTURES`.
- `tests/test_bill_engine.py`: new section "SL-02" (80 tests): rate unit list, SC-105 a/b/c/c2 and step 4 (tie and headings), the other role rules, SC-106, the adapter
  shape, `for_lines`, determinism.

The handoff is uncommitted. `progress.yaml` is not touched.

## Actual interfaces (for SL-03 onward; the plan's P2/P4 names kept)
- `bill_tables.read(evidence) -> BillTables(reading, roles, adapted, guesses, notes, engine_pages, line_pages, lines_of, pages)`.
  - `reading` is `charge_tables.read`'s `BillReading` with `tables` = tables that have a charge column; a table with no charge column is moved to `other_tables`, its
    pages join `pages_without_tables`, and `unplaced` is kept only for pages that hold a charge table.
  - `roles[i]` belongs to `reading.tables[i]` (`Roles.roles` is `{column id: charge|quantity|unit_price|other}`, `decided_by` is `product|sum|subtotals|heading|single|guess`).
  - `line_pages` is a set of page numbers and `lines_of` maps layout line id to evidence line id, both from `paystub_tables.evidence_index` (as for pay stubs). This differs
    from `BillReading.line_pages` (a dict of layout line id to page), which stays inside `reading`.
  - `pages` (not in the plan's shape list, but P7.1's `for_lines` text names it) is the set of pages holding a charge table; after `for_lines` it equals `engine_pages`.
- Adapted table: `SimpleNamespace(id, page, pages, source="bill_engine", header_rows=[row 0], rows, roles={cell index: role}, spans)`. Row: `id "<table>-row-<r>"`, `line_id`,
  `line_ids` (label's lines first), `cells` (cell 0 label, then one per column; usage cell quote is `500 kWh`, a money cell's is the token text, blank cells have `word_ids == []`),
  `total`, `label`, `section`, `title_line_id` (evidence line of the section title or None), `title_phone`, `page`, `money_off`. A wrapped label's cell 0 has `cites` (two lines),
  otherwise None. Cell fields as `paystub_tables.cell_of`: `id, line_id, quote, word_ids, source_line_ids, cites`.
- `printed_rate("0.1430", "USD") -> PrintedRate(14, "0.1430")`; whole-unit rates give `PrintedRate(minor, None)`. Uses `document_checks.decimal` to read the text, so `$0.1430` and
  `1,234.5678` parse; text that is no number raises `ValueError` (the engine only passes amount-token text). Currency exponent from `core.money.EXPONENTS` (JPY 0, KWD 3).
- `money_off(row, roles)` takes a `charge_tables.ChargeRow` and the table's `Roles`; `signed(token, section)` is the signed magnitude (minus, parentheses, trailing minus, `CR` and an
  unsigned amount under a `CREDIT_SECTION` title are negative; `debit` and `plus` are not).
- `Guess(kind, page, table_id, text)`; this slice makes only `charge_column` (text `Page N: two printed columns add up to the bill's charges; the right-most was taken as the
  charge.` when two columns add up, and `Page N: the printed columns could not be told apart; the right-most was taken as the charge.` when nothing decides). `unclassified_row`,
  `amount_due` and `split_changed` are named in `GUESS_KINDS` for Record (SL-03/04/06) to build.
- `for_lines(bills, line_ids)` keeps adapted rows whose first evidence `line_id` is in the part, and filters the engine tables' rows/totals to the same rows, anchors, late lines,
  unplaced lines, other tables (any row line in the part), guesses of kept tables (and those with no table), `pages_without_tables` among the part's pages, `line_pages`, `roles`,
  `engine_pages`, `pages`, `notes`. `lines_of` and `line_pages` (the set) are passed through.

## Choices the plan left open (none changes an expected value)
1. **Order inside (b).** `sum` is tested before `subtotals`; a column that holds either qualifies. One qualifier decides; several go to headings, then the right-most with a guess.
   When none qualifies, headings alone decide (one charge-headed column, or the only column not headed as something else), else the right-most with the "could not be told
   apart" guess. A single amount column is the charge (`single`, or `sum` when it adds up to a target).
2. **A table with no charge column** (plan P3/P4: "goes to `other_tables`"). The plan's roles always find one when a table has an amount column, so the only case I made is: two
   or more amount columns, no sum or subtotal holds, and every heading says the column is something else (`Last Year`, `Previous`, `Prior`, `Usage`, `Rate`, `kWh`, `Meter`,
   `Reading`, `Days`). Then the table is another table (tested). Everything else gets a charge column.
3. **(a) triples.** The charge is an `amount` column; quantity and rate may be `usage`, `integer` or `amount`. Quantity is the usage/integer one, else the one printing fewer decimals
   (left one when equal). Of several holding triples: most rows judged, then the right-most charge. The product uses `paystub_tables.multiplies` (half up, one minor unit) on the
   printed numbers; the charge is compared by magnitude so a credit row printing all three still judges.
4. **Sum targets** use only anchors on the table's own pages (a table over three pages, like BL-MULTI's one table, therefore has a target set from all three pages; SL-06 may need to
   decide per bill). Targets: new-charges values; else amount due − first previous balance + |first payments| for each amount due; else amount-due values.
5. **Subtotal coverage** uses `covered(entries, position)` on `ChargeRow`/`ChargeTotal` with phase 3's two row sets; signed values are summed.
6. **Heading words** (`CHARGE_HEADS`, `OTHER_HEADS`) are the plan's lists as whole-word regexes; a heading naming both kinds says neither.

## Coverage
SC-105 a, b, c, c2 and step 4 (tie: one `charge_column` guess naming the right-most; `Previous`/`Current` headings decide with no guess); SC-106 step 4 and the engine side of steps 1-3
(`-5.00`, `(5.00)`, `5.00-`, `5.00 CR`, unsigned under `Account Credits`/`Discounts`/`Adjustment`/`Credit`, and unsigned under non-credit titles stays a charge); SC-110 step 6's
unit list (all ten values plus 0.1449, 0.1451, 0.0050 in the parametrized test, and the engine-read rates of BL-UTIL, UTIL-HALF, UTIL-15, UTIL-125, each decided by the product on the
printed rate); the adapter's ids, line ids, wrapped label lines and title line ids; `for_lines` between pages (SC-128 step 8's rows/anchors) and inside a page.
Mutation spot checks (half-even rounding, dropped sign, leftmost instead of right-most, always keeping the text, `for_lines` row filter) each fail at least one test; scoping the sum
targets to the table's pages was not caught by the fixtures, so `test_sc105_only_summary_amounts_on_the_tables_own_pages_are_sum_targets` was added.

## Not done here (belongs to later slices)
Record's use (model cells, copying values, product checks on the printed rate, holder rule P5, notes for unplaced lines and money off, guesses beyond `charge_column`), the browser
tests, docs. `adapt` keeps rows only on `native_page` pages like pay stubs; BL-MULTI and UTIL-2P behave as expected. No full-suite run (orchestrator's). No private data touched.
