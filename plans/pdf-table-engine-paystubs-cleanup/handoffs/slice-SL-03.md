```yaml
slice: SL-03
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 98b0b65
end_head: 4ff0956   # the slice's commit; the handoff itself is committed on top of it
commit: 4ff0956
changed_files:
  - src/home_manager/documents/pay_tables.py     # P3 (b), (d), (f)
  - src/home_manager/finance/paystub_tables.py   # P3 (a), (e)
  - evals/paystub_layouts.py                     # (a), (b), (d), (e), (f) drawn again; 5 new REQUIRED variations
  - tests/test_paystub_cleanup.py                # sc91_a, sc91_b, sc91_d, sc91_e (x2), sc91_f
  # tests/test_paystub_engine_generator.py is unchanged: its coverage test (every layouts.REQUIRED variation in >= 3 cases) and its
  # exact-record / engine-row tests pick the new layouts up through evals/paystub_layouts.py.
checks:
  - command: ".venv/bin/python -m pytest tests/test_paystub_cleanup.py tests/test_pay_tables_repairs.py tests/test_paystub_engine.py tests/test_paystub_engine_record.py tests/test_paystub_engine_generator.py tests/test_table_engine.py -q"
    exit_code: 0   # 919 passed (5 min 16 s)
  - command: ".venv/bin/python -m pytest tests/test_layout_consumers.py -q"
    exit_code: 0   # 17 passed, file unchanged (SC-94)
  - command: ".venv/bin/python -m pytest tests/test_evals.py tests/test_eval_tasks.py -q -x"
    exit_code: 0   # 46 passed; both build cases with evals/synthetic.py, which draws from the changed generator
  - command: ".venv/bin/python -m ruff check evals/paystub_layouts.py src/home_manager/documents/pay_tables.py src/home_manager/finance/paystub_tables.py tests/test_paystub_cleanup.py"
    exit_code: 0
  - command: "tests/test_paystub_cleanup.py -k sc91 at 98b0b65 source (git stash of src/, new tests and generator kept)"
    exit_code: 1   # 6 failed, each for the intended reason (table below); with the fix: 10 passed in the file
  - command: "scratch scan of the generator (seed 20261104 cases 0-119, seeds 1-3 cases 0-39) at 98b0b65 source, then with the fix"
    exit_code: 0   # 49 of 240 files fail at 98b0b65 (table below); 0 of 240 with the fix
escalations: []
```

# SL-03 handoff: the avoided layouts (FR-92, SC-91)

## First step: the layouts re-enabled in the generator, and what fails at START_HEAD (98b0b65)

I changed `evals/paystub_layouts.py` first (source untouched, via `git stash` of `src/`), then scanned every generated file with the engine (the
generator test's own rows-are-exact comparison). Main seed 20261104, cases 0-119, plus the sweep seeds 1-3 (cases 0-39). 49 of 240 files fail at
START_HEAD; every one carries one of the five new layouts, and none fails without one (so nothing else regressed). Failing cases per layout
(main seed first; "seed:case" is a sweep seed):

| Layout | Draws in the main seed | Failing at 98b0b65 | What goes wrong |
|---|---|---|---|
| (a) taxes/deductions negative, YTD left, no heading | 5 | 21, 24, 77, 89, 106; 2:11, 3:0, 3:11, 3:17 | this period and year to date swapped on every row of the table (the left column is read as this period): rows that print negative don't vote, so the order is a `left` guess |
| (b) second stacked table starts page 2 | 7 | 7, 49 (also 40, 71, 97, which are (d) cases too) | page 2's rows lie 33 pt left of page 1's Hours/Rate columns (cases 7, 49: `cy_hr` order), so they continue page 1's table at offset -33 and their amounts land in Hours/Rate (`Federal Income Tax Withholding` has hours `(483.29)`, rate `(7,732.64)` and no current/YTD) |
| (d) one amount column, two-line heading | 14 | 6, 25, 90 (and 40, 71, 97); 2:37, 3:13, 3:16, 3:36 | the rows are missing and page 2 can be left without a pay table (cases 40, 71, 97: `pages_without_tables` [2, 4, 6] / [2]): only the lower heading line (`Period`, `Date`) is attached, so the headings name no role and the column has no section total to decide it |
| (e) hours = the YTD multiple | 13 | 13, 55, 60, 76, 100, 113, 118 (and 4, 29, 43, 78, 98 with (f)); 1:7, 1:9, 1:17, 1:22, 1:30, 1:36, 2:6, 2:14, 2:30, 2:38, 3:5, 3:11, 3:12, 3:15, 3:22 | hours and rate swapped on every row (case 13: expected hours `15.00`, rate `39.00`, read hours `39.00`, rate `15.00`): the two triples share the hours column and FR-57 (a) names it the rate |
| (f) leave table lined up with the pay column | 33 drawn | 52 only (also 3:13, 3:36 with (d)) | side layout, one pay column, two stubs on a page: the leave table's columns line up with the earnings column by left and centre edges, so the block's amounts cluster together and stub 1's earnings table is split (`Base Pay` in a table of its own, `Retro Pay` and the totals in others); stub 2's rows join the leave column |

The scan script was scratch only (`/tmp/sl03`, not committed). Draw counts are the counts of `layouts.variations` tags in the main seed's 120
cases: every new tag is drawn at least 5 times (the generator test requires 3).

## What I built (each checked against those failures; after it, 0 of 240 fail)

`documents/pay_tables.py`:
- **(b)** `MAX_OFFSET = ALIGN`. `offset_of` (unchanged otherwise) now lets the page's first row continue the open table only when its columns line up
  with the table's at a page offset within ALIGN (0.75) font sizes. The plan's "(not the looser within-80-pt match)" is `MAX_OFFSET = 8` font sizes,
  and the lined-up check was already at one offset within ALIGN; so the change is the offset bound itself. The generator's failing layout lines up
  *exactly* at -33 with the wrong columns, so only a bound on the offset separates it. PS-CONT (offset 0) and PS-CONT-NH (6 pt, under 7.5 pt)
  still continue, and STK's 400/500 against 430/520 (offsets -30, -20) starts its own table. `repeats()` is untouched.
- **(d)** `heads_above` takes a one-run all-text line over a column as a heading line when a heading line is already found below it
  (`splits_by_column(..., least=1)`): `This` over `Description  Period` is one heading, like the one-line case. Needs `wide`, so only the second
  `attached` pass (after the zones exist) sees it.
- **(f)** the failing layout is generator case 52 (table row). Rule built: `tables_cut(block, starts)` cuts a block's lines into one list per table
  before clustering, at (1) the first line after a totals line when a heading line follows before the next pay line, and (2) a stub start line that
  follows pay lines (the line after the previous stub's last row). `read` calls `read_block` once per piece (lines outside the piece are emptied, so
  the page's line indexes hold; the piece gets only its own start lines, because a start line seen by an earlier piece's loop would mark the stub's
  dates as already open; only the first piece takes the open tables of the previous page; only the last piece's open table goes on to the next page).
  Cut (1) alone fixed case 81-like layouts but left case 52 (the second stub's earnings still clustered with the first stub's leave table), hence (2).
  `read_block`, `place`, `column_sets` and the rest are unchanged; no change to `table_engine.tokenize`, `tokenize_page` or `Line` (FR-67).

`finance/paystub_tables.py`:
- **(a)** `smaller_on`: a row votes when its two amounts share a sign (both negative included); the smaller *magnitude* gets the vote; mixed-sign rows
  don't vote. The existing test `smaller_on(...) == (2, 1, 3)` holds.
- **(e)** `products` now also settles two triples where one's product is a factor of the other's (the hours column shared): it returns the first
  triple's product as this period, the other's as year to date, plus a `guessed` flag: True when no heading names the columns and none contradicts
  them (`by_heading(...) is None and not contradicted`). `decide` uses the returned year to date column (there may be no section totals to name it)
  and sets the `columns_guessed` basis `left` when guessed, so the note is the phase 2 wording ("the right column was taken as this period; the printed
  amounts didn't tell the two columns apart.", gap G1). A heading that contradicts the numbers goes through the existing `headings_overruled` path.
  Two triples sharing the rate column (PS-YTDH) are unchanged; three or more triples are unchanged (`None`).
  `products` is not used outside `decide`; its return grew from 3 to 5 values.

`evals/paystub_layouts.py` (no new rng draws, so every file the five layouts don't touch is byte-identical to before):
- (a) the `settle` rule that turned year-to-date-first into current-first for unheaded negative tables is gone; (d) the `known2` -> `known1` rule for
  one-column tables is gone.
- (b) new choice `break_table` (3 or 2): a stacked two-page stub breaks before its third or its *second* table; for 2 the page opens with that table's
  own title or heading (no repeat of the first table's heading).
- (e) new choice `hours_multiple`: hours = the stub's year-to-date multiple, set after the existing draw (so the stub's other numbers are the draw's);
  needs hours and a year-to-date column, and drops the year-to-date hours column.
- (f) new choice `lined_up`: `leave_edges(state, lined=True)` takes the first set of leave edges (the contract's, then the old scan) whose amounts
  line up with a printed amount by left or centre edge; the old (False) behaviour is unchanged.
- `REQUIRED` gains `negative_rows:ytd_first_unheaded`, `stacked:second_table_starts_page`, `one_column:two_line_heading`, `hours:ytd_multiple`,
  `leave:lined_up`, each computed in `variations` from the printed choices. (c) stays avoided.

## SC-91 hand-built tests (`tests/test_paystub_cleanup.py`), each failing at 98b0b65

Run at 98b0b65's source (`git stash push -- src/`, then `pytest tests/test_paystub_cleanup.py -k sc91 --tb=line`): 6 failed, in these ways.

| Test | Failure at 98b0b65 |
|---|---|
| `sc91_a` (-600.00/-50.00, -240.00/-20.00, Total Taxes -840.00/-70.00, no heading) | roles `{'current': ['-600.00', '-240.00'], ...}`: the left column is this period |
| `sc91_b` (page 1 Current/YTD/Hours/Rate at 304/376/448/520; page 2 `Taxes` at 415/487; plus PS-CONT and PS-CONT-NH still continuing) | one table instead of two (`not enough values to unpack`): page 2 continues page 1's table |
| `sc91_d` (`This`/`Period`, `Year to`/`Date` over one column) | `[['Period']] == [['This', 'Period']]` |
| `sc91_e` with headings (12.00 × 25.00 = 300.00, 3,600.00; 12.00 × 37.50 = 450.00, 5,400.00; also PS-YTDH keeps its SC-57 roles) | `rate` holds `12.00`: hours/rate swapped |
| `sc91_e` no heading (same values; one `columns_guessed` note) | same swap |
| `sc91_f` (two stubs' left blocks, a Leave table lined up by its left/centre edges, from case 52) | `[['Base Pay'], ['Base Pay']]` where `Base Pay` and `Retro Pay` are expected in each stub's table |

With the fix all 10 tests in the file pass. The PS-YTDH check is inside `sc91_e` (heading variant) so every `sc91_*` function fails at 98b0b65.
Coordinates are literals in the tests (gap G2); `sc91_f` uses case 52's left blocks (the engine still reads a side layout page with a right block the same
way; the left block alone reproduces the failure).

## Open issues

- None blocking. Decision for review: (b) is read as "the page offset itself is within ALIGN font sizes" (`MAX_OFFSET = ALIGN`). The plan's wording
  could also mean only "within ALIGN at one offset", which the code already did and which cannot reject the generator's failing layout (it lines up
  exactly at -33). I judged this a reading of the plan's parenthetical, not a deviation; flagging it for the reviewer.
- (f)'s cut also applies to every other layout (stacked tables, two stubs on a page): the 240 generated files and all verification tests still pass,
  but real stubs were not available (synthetic data only).
- `tests/test_paystub_engine_generator.py` needed no edit (see changed_files); if the reviewer expects an explicit per-layout assertion there, the
  `REQUIRED` check (every variation in at least 3 of the 120 cases) is what enforces "≥ 3" for the five new tags.
- The orchestrator still runs the full suite once after the last slice.
