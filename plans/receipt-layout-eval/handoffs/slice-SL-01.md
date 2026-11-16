```yaml
slice: SL-01
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 10f873814adf8b226d94f11aaa0af0cc20b041eb
end_head: 6f009e145b63d3701259fb0921037415ac85650a   # the code commit; the handoff commit follows it
commit: 6f009e145b63d3701259fb0921037415ac85650a
changed_files:
  - .gitattributes
  - tests/reading_format_fixtures.py
  - tests/test_reading_format_capture.py
  - tests/reading_format_data/inputs/{receipt.png,page1.png,page2.png,scan.pdf}
  - tests/reading_format_data/v7_{image,pdf,group}_{requests,result,options}.json
  - tests/reading_format_data/v7_vision_settings.json
checks:
  - command: "CAPTURE_READING_BASELINE=1 .venv/bin/python -m pytest tests/test_reading_format_capture.py -q (run 1)"
    exit_code: 0   # 6 passed
  - command: "sha256sum tests/reading_format_data/*.json > $SCRATCH/c1.sha"
    exit_code: 0
  - command: "CAPTURE_READING_BASELINE=1 .venv/bin/python -m pytest tests/test_reading_format_capture.py -q (run 2)"
    exit_code: 0   # 6 passed
  - command: "sha256sum -c $SCRATCH/c1.sha"
    exit_code: 0   # all 10 files OK: the capture is deterministic
  - command: ".venv/bin/python -m pytest tests/test_reading_format_capture.py -q"
    exit_code: 0   # 5 passed, 1 skipped (the env-gated capture)
  - command: "git diff --exit-code HEAD -- src/"
    exit_code: 0
escalations: []
```

## What was done
- **Inputs** (drawn with `ImageDraw` rectangles only, no font): `receipt.png`, `page1.png`, `page2.png` (900×1100, white, grey bars) and `scan.pdf` (`make_pdf(path, [None])`). Their sha256 are pinned in `INPUT_HASHES`. `find_regions` returns `[]` for them, so each page is one vision request (no regions in the stored result).
- **`.gitattributes`** (new): `tests/reading_format_data/** -text`; `git ls-files --eol` shows `-text` for the files.
- **`tests/reading_format_fixtures.py`**: capture paths, `INPUT_FILES`/`INPUT_HASHES`, `write_inputs()` (how the inputs were drawn; the files are the source of truth), `mask_port`, `dump_vision_requests` (indent 2, each `data:image/png;base64,…` URL becomes `sha256:<hex of image bytes>`) and `v7_answer(texts, indents)`.
- **`tests/test_reading_format_capture.py`**: the capture is skipped unless `CAPTURE_READING_BASELINE=1`. It asserts `VISION_VERSION`, `PDF_VERSION`, `GROUP_VERSION` (v7-indent / pdf-pages-v4-indent / receipt-images-v3-indent) and the input hashes before it writes. It reads the image, the PDF and the combined document (helpers mirror `test_dining_baseline_capture.py`; v7 answers of the breakfast lines, imported from `dining_receipt_fixtures`; the combined document is split at line 20 across the two pages). The server runs on a free port and every file goes through `mask_port`. Five self-tests run without the variable (input hashes, `.gitattributes` line, `mask_port`, `dump_vision_requests`, `v7_answer`).
- The capture holds 1 request for image and PDF and 2 for the combined document. `v7_vision_settings.json` is the same file for all three kinds.

## Notes for SL-02
- The captured result/options include `engine.base_url` with `127.0.0.1:PORT`; compare after `mask_port`, as the plan says.
- The PDF page's image hash depends on pdfium rendering of `scan.pdf` (pinned `pypdfium2`); it is stable on this machine across two runs. If a different pdfium version renders different pixels, `v7_pdf_requests.json` would differ on another computer. This is not an issue today, but SL-02's comparison would show it first.

## Open issues
None.
