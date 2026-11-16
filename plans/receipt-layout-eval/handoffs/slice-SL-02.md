```yaml
slice: SL-02
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: bb81cf2
end_head: c8104963f344c3421b4a8ff8332db1870f3b2c44   # the code commit; the handoff commit follows it
commit: c8104963f344c3421b4a8ff8332db1870f3b2c44
changed_files:
  - src/home_manager/models/vision.py
  - src/home_manager/documents/vision_layout.py        # new
  - src/home_manager/documents/pdf_reader.py
  - tests/test_vision_layout.py                        # new
  - tests/test_reading_formats.py                      # new
  - tests/model_server.py
checks:
  - command: ".venv/bin/python -m pytest tests/test_vision_layout.py tests/test_reading_formats.py tests/test_reading_format_capture.py tests/test_vision_indent.py tests/test_vision_tables.py tests/test_receipts.py tests/test_pdf_reader.py tests/test_pdf.py tests/test_document_groups.py tests/test_regions.py tests/test_sampling.py tests/test_vision_batch.py tests/test_gpu_host.py tests/test_eval_tasks.py -q"
    exit_code: 0   # 233 passed, 1 skipped (the env-gated SL-01 capture), 2 warnings
  - command: "git diff --exit-code 6f009e1 HEAD -- tests/reading_format_data"
    exit_code: 0   # run before the code commit; the commit touches no file there
escalations: []
```

## What was done
- **`models/vision.py`** (P1 – P5): `READING_FORMATS`, `DEFAULT_FORMAT`, `reading_format(name)` (lock, restored in `finally`, nesting-safe, unknown name raises the plan's message), `active_format()`. `transcribe` gains three lines after the base64 encoding that send any non-default format to `FORMAT_READERS`; **v7's body is textually unchanged**. `VisionText` gains `format`, `rows`, `spans`, `notes`, all `exclude=True`. `transcribe_preview` records `READING_FORMATS[active_format()]` as `engine.prompt_version` (v7's value by default) and one `vision_positions_unusable` issue when a reading has notes.
  - `v6-text`: `V6_PROMPT` / `V6_RESCUE_PROMPT` (checked equal to `git show 3128497^` with `ast`), keys `{"full_text"}` or `{"full_text","tables"}`, lines `lstrip`ped with indent `None`, tables validated like v7.
  - `layout-text`: `LAYOUT_TEXT_RULES` inserted after "footer text. " in the v6 prompt; schema names `document_layout_text` / `document_layout_text_fallback`; `parse_layout_text(full_text) -> (lines, rows)`.
  - `spans`: `SPANS_PROMPT`, `SPANS_SCHEMA`, `parse_spans`; schema `document_text_spans`; rescue `document_text_spans_fallback` with `'Return ONLY a JSON object with exactly one key: "spans". ' + SPANS_PROMPT`. Blank answer or blank rescue → `BLANK_RESPONSE`; two invalid answers → "Model output did not contain valid full text after a text-only retry.".
- **`documents/vision_layout.py`** (P6): `build_rows(pieces) -> (rows, notes)` with `Row`/`Cell`, named threshold constants.
- **`documents/pdf_reader.py`** (P2): scanned pages add the `vision_positions_unusable` issue beside the table issue; the combined-document issue filter keeps the code.
- **Tests**: `test_vision_layout.py` (39 tests: all the plan's list incl. all-caps/mixed, ±2.5°/±3°, perspective warp, axis scaling and a 0–1000 frame, whole-row pieces, SC-08). `test_reading_formats.py` (39 tests: selection, requests, parsers, rescue/blank/`length` per format, PDF/image/combined under `spans`, `engine.prompt_version`, SC-10 byte comparison with SL-01's captures after `mask_port` for image, PDF and combined, `VisionConfig` fields, `reading_format(` only in `vision.py`). `tests/model_server.py`: `v6_answer`, `layout_text_answer`, `spans_answer`.

## Deviations from the plan (local, within the spec; the row builder only)
1. **P6 step 3, slope choice.** The plan's rule (fewest rows, then within one row the tightest, then smallest |s|) failed on hand-built receipts: a slope that crowds rows together gives *fewer* rows than the true one, and one that pairs a row's left end with the next row's right end ties with it. What `row_slope` does instead (named constants at the top of the module):
   - candidates are searched with a tighter row tolerance (`SLOPE_ROW` = 0.25 text heights, the final grouping still uses `SAME_ROW` = 0.5);
   - all usable pieces take part (handwritten too: right-hand handwriting is the evidence that separates a pairing from the true rows);
   - slopes are ranked by (rows, mean distance from the row's centre line, |s|);
   - a slope must be nearly level (|s| ≤ 0.005) or have the margin's sign (margin slope `t` measured first; `|t|` ≥ 0.01), which is the geometry of a page turned in its plane; a page seen at an angle keeps level rows with a slanted margin, so level always stays allowed. With no margin estimate (< 3 bands) the search is unconstrained; with fewer than 6 usable pieces (`MIN_TO_MEASURE`) the rows are read level.
   Swept at ±0.5° … ±4° (0.5 steps), keystone 2/5/8%, all-caps and mixed case: all give the untilted rows.
2. **P6 step 3, margin slope.** Band minima whose left edge is more than 4 character widths right of the median band minimum (`MARGIN_OUTLIER`) are left out before the Theil–Sen slope: bands holding only centred rows otherwise dominated the pairwise slopes on a 15-row receipt.
3. **P6 step 9, order of unusable pieces.** Several unusable pieces after the same row are kept in answer order (a later one goes after the earlier ones already placed there).
4. `document_text_spans_fallback` as the spans rescue's schema name (the plan names only the main schema); SL-04's fake answers can key on it through `by_schema`.
5. `parse_layout_text` returns `(lines, rows)`; `v6_lines` returns the same pair shape.

## Notes for SL-03/SL-04
- SL-04's check "`build_rows` on the exact drawn boxes of all 24 cases" is the real test of deviation 1: my hand-built receipts have regular rows and constant right edges. If a drawn case fails, tune the constants at the top of `vision_layout.py` (plan R3), not the plan.
- A tilted box's axis-aligned height is inflated by its width (a 33-character row's box is ~22 px taller at 2.5°), so `h` (median box height) is larger on tilted pages; row membership uses centres only, which are exact under rotation.
- `test_reading_formats.py` imports `read_image`/`read_pdf`/`read_group`/`last_parse` from `tests/test_reading_format_capture.py`; do not rename them.
- The reading-format tests that start a `Manager` take ~25 s together.

## Open issues
None. SL-01's captures are untouched (`git diff --exit-code 6f009e1 HEAD -- tests/reading_format_data` exits 0).
