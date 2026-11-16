```yaml
slice: SL-03
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 74cbbe7
end_head: d76d99b9e637a4ddd71620bfa852d3244b61d5df   # the code commit; the handoff commit follows it
commit: d76d99b9e637a4ddd71620bfa852d3244b61d5df
changed_files:
  - evals/fonts/LiberationMono-Regular.ttf        # new, copied from /usr/share/fonts/truetype/liberation/
  - evals/fonts/LiberationSans-Regular.ttf        # new, same
  - evals/fonts/Caveat-VariableFont_wght.ttf      # new, google/fonts 5571d84c… ofl/caveat/Caveat[wght].ttf
  - evals/fonts/OFL-Caveat.txt                    # new, same commit
  - evals/fonts/LICENSE-Liberation.txt            # new
  - evals/receipt_layouts.py                      # new
  - tests/test_receipt_layouts.py                 # new
checks:
  - command: "sha256sum evals/fonts/*.ttf evals/fonts/OFL-Caveat.txt"
    exit_code: 0   # all three .ttf and OFL.txt equal the plan's hashes (checked before use)
  - command: ".venv/bin/python -m pytest tests/test_receipt_layouts.py -q"
    exit_code: 0   # 32 passed, 0 skipped (Pillow 12.3.0, FreeType 2.14.3, zlib-ng 2.3.3: the recorded-hash test ran)
  - command: ".venv/bin/ruff check evals/receipt_layouts.py tests/test_receipt_layouts.py"
    exit_code: 0
escalations: []
```

## What was done
- **Fonts** (`evals/fonts/`): the two Liberation files copied, Caveat and its OFL downloaded (data only, into a scratch directory, then copied under the plan's names). `LICENSE-Liberation.txt` is the copyright lines and OFL 1.1 text of `/usr/share/doc/fonts-liberation/copyright` with Debian's `" ."` paragraph markers removed.
- **`evals/receipt_layouts.py`** (P7): `FONTS`, `Cell`, `Row`, `Receipt`, `CASES` (the plan's 24 triples; indexes are positions in the family's list, so `dining/clean/0` is the fixture case), `make(family, condition, index)`, `draw(receipt, only=None) -> (image, boxes[row][cell])`, `answers(receipt, boxes, size)`, `png_bytes`, `parse_amounts`, `printed_amounts`. `font()` refuses a file whose sha256 isn't in `FONTS`. All fonts use `Layout.BASIC`. Thermal: 760 px, Mono 26, pitch 34, margin 52, right 708, centre 380, indent step 2 × 16 px. Ereceipt: Sans 24, 900 px, margin 60, right 840, centre 450, pitch 38. Handwriting: Caveat 34, dark blue, vertically centred on the printed row. Conditions as in P7; every box is the text box (the cell's own ink box, at least the height of `"Hgjpqy|"` so a row's boxes line up) with its four corners mapped through the same transform; the tilt sign per case comes from the seeded rng.
- **Answers** (`answers`): `{"size": [w, h], "rows": [{"cells": [{"text", "handwritten", "box"}], "indent", "align", "amounts"}]}`; blank lines are not rows; a one-cell row's align is its cell's, a multi-cell row's is "left".
- **`tests/test_receipt_layouts.py`**: every item in the plan's SL-03 list (font hashes, licences, identical PNG bytes for 7 cases, the recorded hash for `dining/clean/0` gated on Pillow/FreeType/zlib-ng versions, FR-01 geometry for both styles, family coverage, long ≥ 80 rows, `make` twice → equal answers and `make_case` ids, `0000` numbers, no "179580"/"Crimson", arithmetic, SC-13 ink-in-box for `dining/tilted/2`, `dining/angled/3`, `grocery/tilted/2`, `itemized/angled/1`), plus the dining fixture's items and suggested-tip rows, the amount rule, and a changed font file being refused.
- **Sanity check for SL-04** (not committed): `build_rows` on each case's exact drawn boxes, pieces shuffled, returns every case's rows, cell texts, indents and alignments exactly, for all 24 cases (tilted, angled, small_text included), with no notes. So the SL-02 constants needed no tuning.

## Deviations from the plan (local, within the spec)
1. **`Row.kind` and `Receipt.checks`** added (defaults empty): the arithmetic test needs each receipt's sums and products, and rows need a kind for tests like "the written tip". `checks` holds `("sum", parts, total)` and `("product", a, b, total, divisor)` in minor units; every part and total is asserted to be printed.
2. **`parse_amounts` lives in `receipt_layouts.py`** because `evals/layout_grading.py` (P8) doesn't exist yet. It implements P8's rule (two decimals, optional `$`, thousands commas, leading/trailing minus or parentheses, not followed by `%` or a digit, not preceded by a digit, `.` or `,`). SL-04 should make the grader's amount function agree with it (or import it); a test here pins its behaviour (`3.459`, `10.234`, `8.000%`, `18.00%` are not money).
3. **Row `align` for a mixed printed + handwritten row** is "left" (two cells), as `build_rows` gives.
4. `draw(receipt, only=(row, cell))` is an extra keyword used by the SC-13 test (draws one cell alone through the same transform).
5. The plan's "background" condition uses ink `(70, 70, 76)` for the 60 px margin; "angled" uses a top inset of 5% and bottom corners fixed.

## Notes for SL-04
- Drawing 24 cases takes about 0.6 s in total; `long` cases are 3,600 px tall (clean/faded) or about 1,750 px (small_text, 45%).
- Row counts of `long` cases: 99, 110, 107, 102. Case ids: use `make_case("receipt_layout", {...}, answers(...), tags=receipt.tags)`; boxes are rounded to 0.1 px so ids are stable.
- The recorded PNG sha256 of `dining/clean/0` is `7fbfc8c6f0cf659296df76864ff388da20ac884f17ec190b776189eeb7f56b49` (the test skips with its reason on other imaging versions).

## Open issues
None. Nothing under `src/` changed.
