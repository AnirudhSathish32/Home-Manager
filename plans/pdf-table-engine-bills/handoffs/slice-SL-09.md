```yaml
slice: SL-09
result: ready_for_verification   # with 3 engine defects escalated below (32 strict expected failures)
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 8fc02cb            # plus the uncommitted draft of the worker that died on a rate limit (backup /tmp/bills-sl09-partial)
end_head: cde2fe7              # last code commit; this handoff is committed on top of it
commit: [25d3dc9, 75bd763, 5dc8e1a, cde2fe7]
changed_files:
  - evals/bill_layouts.py
  - tests/bill_engine_generator.py
  - tests/test_bill_engine_generator.py
  - scripts/statement_diagnose.py
checks:
  - command: ".venv/bin/python -m pytest tests/test_bill_engine_generator.py -q"
    exit_code: 0
    result: "249 passed, 32 xfailed (strict), 0 failed"
  - command: ".venv/bin/python -m pytest tests/test_bill_engine.py tests/test_bill_engine_record.py -q"
    exit_code: 0
    result: "317 passed"
  - command: ".venv/bin/python -m pytest tests/test_bill_engine_generator.py -q -k diagnose"
    exit_code: 0
    result: "9 passed"
  - command: ".venv/bin/ruff check evals/bill_layouts.py tests/bill_engine_generator.py tests/test_bill_engine_generator.py scripts/statement_diagnose.py"
    exit_code: 0
baseline_failures_hit: none     # nothing in progress.yaml baseline_failures was touched or failed
escalations:
  - SPLIT_BLIND (23 files, Record test, strict xfail)
  - LAST_YEAR (4 files, rows test and Record test, strict xfail)
  - CARRIED_TITLE (1 file, Record test, strict xfail)
```

## What was done
The draft left by the dead worker was read against FR-123, SC-123, SC-125 and P11/P12, kept where it was right and corrected where it was not:

- `evals/bill_layouts.py` — `make(seed, index, **choices) -> Layout(pages, bills, choices)`, 120 files from `SEED = 20261111`, every dimension drawn by a balanced `pick`, expected values from the inputs only (integer minor units, products rounded half up, FR-117 / FR-118 rules in `settle` and `Case.bill`). Fixes made to the draft: the heading is now printed before the section titles (as BL-UTIL does; with the title above the heading the engine loses the title); a continuation page's repeated header keeps the due date last (the draft's swap dropped the due line and left the account line directly above the first row); a last-year column with no heading no longer puts its summary on the page after the table (FR-105 b reads only the new charges on the table's own pages, so that file has no decidable column).
- `tests/bill_engine_generator.py` — `layout`, `build` (make_pdf), `SEED`, `CASES = 120`.
- `tests/test_bill_engine_generator.py` — per file: the engine's charge rows against the generator's lines (no store, no model); the real reader + Record with the `local_model` double, every answer drawn from the case (classification, summary, each row's description / kind / category / holder citing its row, never an amount, quantity or rate), asserting lines, quantity, rate (`unit_price_minor`, `unit_price.text` only when the value is not whole cents), holder and the "differs from its section title" note, summary amounts, the amount due FR-117 picks and its guess note, worked-out new charges, checks, notes, segments and the number of model questions; misses print seed, index and choices. Also: byte-identical PDFs on regeneration, every FR-123 variation / rate kind / holder form / holder mode seen (and seen again among the files that are not escalated), the generator's own rules, rates exactly half a cent past at 3 and 4 decimals, and the probe tests (`-k diagnose`, subprocess with `-I`, `TMPDIR` pointed at a folder of the test's own that must be empty afterwards): BL-MULTI and BL-UTIL against SC-125's forbidden list (words, amounts as printed and in minor units, dates, account digits), generated one-bill, split and wrapped two-page files against the generator's own page spans, and a file with no bill table.
- `scripts/statement_diagnose.py` — `bill` mode (P11): per page the charge tables with each column's edge, extent and zone as percentages of the page width, its role (`unit_price` shown as `rate`) and how it was decided; counts of rows, totals, section titles (holder titles apart), wrapped labels, anchors by kind, late-payment lines, other tables and unplaced lines; guesses by kind; `N bills: pages …` / `1 bill: pages 1`; per page the key kinds with opens / equal / differs; the FR-129 letters that fired (a – c from `bill_split.REASONS`, d for a split that raises or finds more than `MAX_BILLS`). Exceptions are reported by type only. No model, temporary folder deleted at the end (unchanged `with` block).

## Escalations: engine defects the generator found (source changes are outside this slice)
Each is a strict expected failure in `tests/test_bill_engine_generator.py` (`ESCALATED_RECORD`, `ESCALATED_ROWS`), the case still judged in full, so the entry turns into a loud failure once the engine is fixed. Each escalated file's layout is also run as a single bill (`test_escalated_layout_as_a_single_bill_is_recorded_exactly`), which passes, so only the several-bills part is pending.

1. **SPLIT_BLIND** — seed 20261111, indices 1, 7, 15, 18, 19, 20, 28, 34, 37, 40, 45, 60, 63, 77, 83, 87, 93, 96, 100, 112, 113, 117, 119 (all files of 2 – 4 bills). Examples: case 1 = phone, 4 bills, heading `known2`, summary `below`, stub on page; case 7 = utility, 2 bills, heading `unknown2`, summary `above`, usage history. When a page prints a heading over its amount column (or a rate column, or a usage history table), the reader sets the column's values in lines of their own: no evidence line reads `Amount Due <amount>`. `bill_split.bill_parts` (`has_due`, `anchor_of`, FR-129 b) then finds no amount due on pages 2 on and returns one part with reason (b), so the file is recorded as one bill ("1 records for 4 bills"). BL-MULTI's headingless MINI-BILLs join label and amount, which is why SC-126 passes. 23 of the 80 several-bill files are affected; headingless one-column pages split fine (e.g. dropping the heading of case 1 gives 4 parts). Needs a source decision (the split rule should read the engine's anchors, or the reader's lines should join label and amount), not a generator change.
2. **LAST_YEAR** — indices 29, 33, 64, 67 (several bills, `columns: lastyear`, no heading or a heading on the first bill only; rows test and Record test). The column roles are decided once for the whole table and the sum rule compares the whole column's sum with each bill's new charges (`finance/bill_tables.py` `targets_of`, `decide`); with several bills' new charges on the table's pages nothing matches and the right-most column is taken with a guess note, which is wrong when the last-year column is right-most (`swap: False`). The earlier worker found 64 and 67; 29 and 33 are the same. (A single-bill case of this kind where the summary is on the page after the table is also undecidable under FR-105 b, and the generator now avoids it.)
3. **CARRIED_TITLE** — index 56 (utility, 2 bills, `sections: one`, `credit: section`, heading none, columns `qr`, summary `both`, cut `mid`). The last section title of the first bill (`Account Credits`) stays the section of the second bill's rows when that bill prints no title of its own, so all seven rows read as money off ("printed as money off, so it was recorded as a credit", lines add up to -97.05). A row's section is the last title above it whatever bill it belongs to.

## Observations (not escalated, not pinned by a test)
- While the draft printed each section title above the table heading, the engine did not attach the title to its rows (a phone holder title above the heading gave rows with no `line_holder`). The generator was changed to the heading-first order of BL-UTIL, so this layout is not generated.
- Rent accounts print as `****NNNN` and a continuation header's `Account No. ****NNNN` directly above the first row was read as a phone holder title (rows got `line_holder` "Account No. ****8163"). The generator now ends a continuation header with the due date, so this is not generated either. Worth a look if real rent bills repeat the account line directly above their rows.

## Open issues
- None other than the escalations. Full suite not run (per procedure); no baseline failure was touched. The `ESCALATED_*` lists in the test file must be removed when the engine fixes land (strict xfail makes that unavoidable).
