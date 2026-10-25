```yaml
slice: SL-01
result: escalated
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 803c588089c5ae659a96438172754282d2dbc646
end_head: <filled by the commit; see `git log -1`>
commit: <this commit>
changed_files:
  - tests/test_pdf.py                 # make_pdf additive options
  - tests/pdf_import_fixtures.py      # new: builders, hand-written expected values, P-check helpers
  - tests/test_pdf_imports.py         # new: P-check tests only (names contain `pcheck`)
  - plans/account-import-pdf/handoffs/slice-SL-01.md
checks:
  - command: ".venv/bin/python -m pytest tests/test_pdf_imports.py -k pcheck tests/test_pdf.py tests/test_pdf_layout.py -q"
    exit_code: 1   # 35 passed, 1 failed (the V gate test), 39 deselected
    note: "`-k pcheck` applies to every file on the command line, so it deselects the 39 tests of test_pdf.py and test_pdf_layout.py. They are run separately below."
  - command: ".venv/bin/python -m pytest tests/test_pdf.py tests/test_pdf_layout.py tests/test_pdf_reader.py tests/test_layout_consumers.py -q"
    exit_code: 0   # 59 passed: no existing test changed
  - command: ".venv/bin/python -m pytest tests/test_pdf_imports.py -k \"pcheck and not sc25_v_v5\" -q"
    exit_code: 0   # 35 passed, 1 deselected
  - command: "byte comparison of make_pdf output, HEAD version vs this version, on 5 existing call shapes (plain, None page, positioned items, rotation+crop, unicode_map)"
    exit_code: 0   # all 5 byte-identical (scratch script, not committed)
escalations:
  - gate: "V's v5 cell reads as one native cell, with no pdf_layout_review"
    status: NOT MET for V as the contract defines it. Test: test_pcheck_sc25_v_v5_cell_is_one_native_cell_without_a_layout_review (fails on purpose; not weakened, not xfailed).
```

# SL-01 handoff: fixtures and the G1/U2 gate — ESCALATED

No application code changed. I did not touch the spec, the plan, `progress.yaml`, approvals or `~/.agent-harness`.

## What was built

- **`tests/test_pdf.py` `make_pdf`** (additive; existing calls produce byte-identical files):
  - `images: n` page setting: n small image XObjects drawn at the page foot.
  - `encoding: "cp1252"` page setting: text is encoded as cp1252 and the font gets `/WinAnsiEncoding`, so `•` and `…` are one glyph each.
  - an optional 4th item element (font size, default 10).
  - `media`: a `"x0 y0 x1 y1"` string or `(width, height)`. It also sets the default CropBox. An explicit `crop` still wins.
- **`tests/pdf_import_fixtures.py`**:
  - builders for K, K2, K0, Keur, 18-a, Kc (CSV), R, X and its variants 7a to 7e, F, Fn, M, the SC-05 pattern pages, the SC-24 date pages, V, and the SC-16 long-cell and row-limit pages;
  - the contract's expected values, written out by hand (K, R, X, F, V, S-K, patterns and dates);
  - P-check helpers: `read_pdf` (real reader, no model), native grids, the page-issue codes, **visual rows** (baseline grouping per the plan), heading texts, column spans and straddle rule, and the candidate rows of a page.
  - Every native page has a words-only footer line of at least 40 non-space characters, and none has a digit followed by a word (Fn is the deliberate exception).
- **`tests/test_pdf_imports.py`**: 36 P-check tests (names contain `pcheck`).

## Gate bullets

1. **Every intended native page reads as `embedded_text` with no model: MET.**
   - Every `read()` in the P-check tests asserts `method == "embedded_text"` on every page. `complete_pdf` is given no model config, so a vision page would raise.
   - Page text is at least 40 non-space characters on every page.
   - M's page methods are `["embedded_text", "vision_model"]`, read once through `ReceiptService` and the `local_model` double (1 request).

2. **The amended P-checks hold: MET for every fixture except V (see below).**
   - **K**:
     - 3 native pages, with only `unresolved_columns` as a layout issue.
     - No native table on any page.
     - Page 1's heading is exactly one visual row, `Date | Description | Withdrawals | Deposits | Balance`, each with a box.
     - Pages 2 and 3 have no heading and 3 candidate rows each.
     - Every printed cell of k1 to k9 falls in its own heading's column span. No word straddles, and Balance is its own column.
     - The arithmetic of K_ROWS (out 641.50, in 2,020.11, closing 2,378.61) is asserted.
   - **K2, K0, Keur, 18-a**: these have the same K shape. K2 prints 4821 and 7700. K0 prints neither, and no account number. Keur prints `EUR` on every amount and `Currency: EUR`. 18-a prints `EUR` on k3 only.
   - **R**: page 1 is a native 3-column table with no issues; page 2 has no native table and 2 candidate rows, with only `unresolved_columns`.
   - **X**:
     - Page 1 has two native tables (the summary, and a 5-column transactions table), with no issues.
     - Page 2 has no native table.
     - Page 3 has the native `Fee summary | Count | Total` table and no dated line.
     - **Fixture decision:** X's rows carry Balance values (990.00, 1,010.00, 1,009.00, 1,011.00). A blank Balance column on every row would stop the reader building the page 1 table. The contract's "every column filled" rule needs them.
   - **X variants**:
     - 7a: a headerless payment schedule, with a title row that has no date.
     - 7b: page 2 has its own native heading, and page 3 is headerless.
     - 7c: page 1 prints only withdrawals, so it has no native transactions table, and its heading is one visual row.
     - 7d: B2's `2.00` is centred within 1 pt of the Withdrawals/Deposits midpoint, and is reported straddling.
     - 7e: `12345` and `1.00` are both in the Withdrawals span.
   - **F**: page 2 is flagged by a real trigger, `possible_image_content` (the plan's choice), together with `unresolved_columns`. Its message is `Page 2 PDF layout needs review: possible_image_content, …`. Page 1 is clean. Nothing is injected.
   - **Fn**: a native 5-column table, with `layout.issues == ["unresolved_columns"]`.
   - **SC-05 patterns** (8 matches and 2 misses): each has a clean native 2-row table, and its line is one visual row, with `•` and `…` read as single glyphs.
   - **SC-24 date pages** (D-ny, D-bad, D-full, D-amb, D-2y) and the SC-16 3-row and 4-row pages: each is a clean native `Date | Description | Amount` table.
   - **Helper agreement**: the visual rows and heading texts equal every native table of the checked fixtures. The one difference is the non-transactions `Fee summary | Count | Total` heading. There the reader's `split_headings` separates `Fee summary` from `Count`, which sit about 9 pt apart, so the plain 1.5-font-size rule gives `Fee summary Count`. The test pins this. It matters only for non-transactions headings.
   - **Heading rows**: every heading that is meant to be rebuilt forms exactly one visual row (K, K0, K2, Keur, 18-a, X 7c, M).

3. **V's v5 cell and SC-16's 2,001-character cell each read as one native cell, with no `pdf_layout_review`: NOT MET for V. MET for SC-16.**
   - **SC-16 step 4 (MET):**
     - Page 10,000 pt wide, with the amount heading at x = 9,500.
     - It reads as a native `Date | Description | Amount` table. The description cell is one cell of exactly 2,001 characters (two 1,000-character words and a space), and the page issues are empty.
     - Test: `test_pcheck_sc16_long_cell_reads_as_one_native_cell_without_a_layout_review`.
   - **V (NOT MET).** The contract's V table has v3 with a blank description. The reader requires a label (an alphabetic group) on every body row (`table_grid`, `pdf_layout.py:435–440`). With v3 blank, no window containing v3 can be a table.
     - Evidence, V as contracted (wide page, and also a plain 612 pt page with a short v5):
       - the native table is `heading, v1, v2` only (3 rows, 5 columns);
       - v3, v4 and v5 are loose lines (`08/03/2026`, `08/04/2026 BAD AMOUNT`, `08/05/2026 DDDD…`, then the amounts as separate lines);
       - `layout.issues == ["unresolved_columns"]` and the page has `pdf_layout_review`.
     - Diagnostics (scratch, not committed):
       - giving v3 any description (`NAMED`) makes the page one full 6-row native table, with v5's cell as one cell, no layout issues and no page issues.
       - dropping the v3 row gives the same, a full 5-row native table.
       - so the blank description alone is the cause, and the 480-character cell geometry is fine.
     - Failing test: `test_pcheck_sc25_v_v5_cell_is_one_native_cell_without_a_layout_review`. It asserts the gate literally: no page issue, a full native table whose last description is the 480-character v5.
     - A second V test, `…v_page_keeps_the_long_cell_clear_of_the_other_columns`, passes. It shows the fixture itself is sound:
       - there is no `glyph_outside_page`, `overlapping_text` or rotation issue;
       - the heading is one visual row;
       - v5 maps to Date, Description (all 480 characters, in one column span), Withdrawals 2.00 and Balance 987.00, with no straddling.

## Why this needs a decision (not a fixture tweak)

V's read is a **partial native table**: the heading, v1 and v2 as a native table, and v3 to v5 as loose lines. The plan's `analyze` says "A native table whose row 0 is a transactions heading is a `transactions` table. Its own rows are used, as the reader built them", and rebuilt rows exist only for pages with no native transactions table. So `analyze` would see 2 rows (v1, v2), not the 5 that SC-25 expects (2 New and 3 rejected, 2 + 0 + 3 + 0 = 5). v3 to v5 would be silently lost.

This is a real product risk, not just a test problem. Any statement row with no alphabetic description would cut a native table short, and the rows below it would be dropped without a report.

I could not make V meet the gate without changing the contract's V rows (v3's blank description) or the plan's rule. The only other way is x-position tricks that dodge the reader, which would not be the contract's table. The plan and contract do not allow that, so I stopped.

Options for the decision-maker (not taken here):
1. **Plan change (my recommendation)**: `analyze` treats any page's candidate visual rows outside the native table's own rows as extra candidates, and rebuilds, or at least reports, them. For example, treat the native table as covering only the rows it holds and rebuild the rest from visual rows. This would also protect real statements.
2. **Contract change**: give v3 a description, or define V's expected result for a partly native page.
3. **Gate wording**: split the V bullet into "V reads as a native table" (needs option 2) and "V's v5 cell is one visual-row cell" (already holds).

## Other notes for later slices

- **Verification command**: `-k pcheck` also deselects `tests/test_pdf.py` and `tests/test_pdf_layout.py`. To check that existing tests are unchanged, run those files without `-k`.
- **K and X page 1** carry only `unresolved_columns`. A page with a complete native table plus a `… Page 1 of 3` footer (Fn) also carries it, as the plan says.
- **Column spans** are midpoints between heading boxes, so a long Description needs the next heading far past its right edge. V's headings are at x = 40, 110, 7200, 7300, 7400 on a 7,600 pt page. The SC-16 amount heading is at 9,500 on a 10,000 pt page. These are the only two fixtures whose x-positions differ from the contract's convention.
- **Pass-through**: `make_pdf`'s docstring documents all new settings.
- **Not added**: the C-net socket fixture (SL-03 and later), and no browser tests.
