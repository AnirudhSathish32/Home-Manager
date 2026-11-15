```yaml
slice: SL-02
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: f2572f3
end_head: 3128497   # the code commit; the handoff itself is committed on top of it
commit: 3128497
checks:
  - command: ".venv/bin/python -m pytest tests/test_vision_indent.py tests/test_vision_tables.py tests/test_document_groups.py tests/test_pdf_reader.py tests/test_pdf.py tests/test_regions.py tests/test_receipts.py tests/test_sampling.py tests/test_vision_batch.py tests/test_extraction.py tests/test_eval_tasks.py tests/test_bill_split.py -q -p no:cacheprovider"
    exit_code: 0     # 269 passed
  - command: "C-SL02 (58 files: every edited test file + every file importing document_forms_fixtures / test_extraction / receipt_item_fixtures / seed_documents), run before the commit; pytest -q -rf -rE"
    exit_code: 123   # 8 failed, 1973 passed, 39 skipped, 20 errors, all in tests/test_agent_instance.py (see below)
  - command: ".venv/bin/python -m pytest tests/test_agent_instance.py -q -p no:cacheprovider   (rerun of the only file with failures)"
    exit_code: 1     # 7 failed, 20 errors, 22 passed: exactly the baseline's ids (baseline-failures.txt)
  - command: ".venv/bin/python -m pytest tests/test_agent_instance.py -q -k test_seed_fills_the_open_library"
    exit_code: 0     # the 8th failure in the C-SL02 run; passes alone and in the file rerun: a flake under load (a PDF child failed in the seed)
  - command: ".venv/bin/ruff check src scripts tests"
    exit_code: 1     # 2 errors, both pre-existing and in untouched code: F402 tests/test_receipt_kinds.py:978, I001 tests/test_document_v2_browser.py:418 (file not edited)
  - command: ".venv/bin/ruff check src scripts tests/test_vision_indent.py tests/model_server.py"
    exit_code: 0
  - command: "grep -rn '\"full_text\"' tests scripts"
    exit_code: 0     # only tests/dining_receipt_fixtures.py, tests/test_dining_baseline_capture.py (old shape) and four lines of tests/test_vision_indent.py (old-shape answer, 'full_text not in prompt')
  - command: "git diff --exit-code f2572f3 -- tests/dining_receipt_data"
    exit_code: 0
escalations: []
```

## What was done
- `models/vision.py` (P3): `VISION_VERSION = "receipt-vision-v7-indent"`. `VisionText` is now `{lines: [(text, indent|None)], tables, table_issue}` with a `full_text` property (joined text; `evals/tasks/transcription.py` and `pdf_reader` still use it). Main schema `{"lines": [{"text","indent"}], "tables"}` (both required, strict), rescue schema `document_text_fallback` = only `lines`. Both prompts carry `INDENT_RULES` (FR-15); the main prompt's `line_index` sentence says it counts the final lines after a line break inside a text is split. `parse_lines` keeps an indent only when it is an `int` (not bool) in 0–2; a `\n` inside a text becomes several lines with the same indent; anything that is not a non-empty list of objects with a string `text` (the old `{full_text}` shape, extra keys) is invalid → one rescue → "Model output did not contain valid full text after a text-only retry." as today.
- `documents/receipt_schema.py` (P2): `TextLine.indent: int | None` (0–2), dropped from every dump when None (wrap `model_serializer`), so old lines serialize byte-identically.
- `documents/pdf_reader.py` (P1): `PDF_VERSION = "pdf-pages-v4-indent"`, `PDF_VERSIONS` gains it, new `LAYOUT_PDF_VERSIONS = ("pdf-pages-v3-layout", PDF_VERSION)`, `GROUP_VERSION = "receipt-images-v3-indent"`, new `GROUP_VERSIONS`; `PDFResult.parser_version` Literal has both new values; `complete_pdf` (scanned pages) and `combine_pages` carry indent; embedded-text lines have none.
- `documents/receipt_service.py` (P1): `:118` and `:192` use `GROUP_VERSIONS` (the same set, D32); the size limit and the layout/preview check use `LAYOUT_PDF_VERSIONS`; `:179` stays `== PDF_VERSION`.
- `scripts/statement_diagnose.py`, `scripts/loopback_stress.py` move to `lines`.
- Tests: `tests/model_server.py` default output and a `vision_answer(text, indents=None, tables=None)` helper (text is a string or a list of lines; indent 0 by default). Every `{"full_text": …}` stub in 24 test files and `seed_documents.py`/`document_forms_fixtures.py` now uses it; accesses of the default output's `full_text` read `lines`; `test_vision_batch` asserts the new schema; `test_vision_tables::test_malformed_structured_response_gets_one_text_only_retry` asserts the `lines` rescue; `test_library`/`test_regions` construct `VisionText(lines=…)`; `test_sampling.SCHEMA` no longer uses the key name `full_text` (an arbitrary schema); `test_document_groups.py:88`, `test_bill_split.py:538` use `GROUP_VERSION`, `test_pdf.py:137` uses `PDF_VERSION`.
- New `tests/test_vision_indent.py` (29 tests): SC-10 steps 1–3, 5 and (a)–(d) (bad indent kinds, no indent key, all blank → run fails with "Model response was blank.", table `line_index` after a split entry); SC-11 steps 1–2 (+ other invalid main answers get the rescue); SC-12 steps 1, 2, 4–8 and (a), (b), (c) (old runs = a fresh reading whose run is rewritten to the old version and the SL-01 capture, for R6, P3 and G2; the old folders are hashed before and after); unserialization test for `TextLine`.

## Notes for later slices
- The old-run builder is `old_library(tmp_path, local_model, kind)` in `tests/test_vision_indent.py`; it returns (manager, document id, old run id). SL-03 can use it for SC-12 step 3 and (e); it does not record the old run yet.
- A blank answer is reported as "Model response was blank." (also after the rescue, when the rescue's answer is blank too). Before this slice a blank answer surfaced as the generic "valid full text" message. FR-17 and SC-10 (c) ask for the blank message.
- SC-10 step 3's "`count_lines` over the reading gives 28": `count_lines` (extraction.py) is about item counts, not line counts, so the test asserts 28 lines instead. SL-03's step 4 can extend if the contract meant something else.
- Step 5's "B0's quotes validate" is tested by recording B0 on the v7 reading (the extraction request is unchanged until SL-03).
- `test_browser.py:299` counts `document_transcription` requests (browser test, opt-in, not run here); its `full_text` stubs were migrated with the rest.

## Open issues
- `tests/test_agent_instance.py::test_seed_fills_the_open_library_and_returns_a_manifest` failed once in the long C-SL02 run (a PDF child error while seeding) and passed alone and in the file rerun. Not in the baseline list; treated as a flake.
- Browser tests (`RUN_BROWSER_TESTS=1`) were not run in this slice (not in its command).
