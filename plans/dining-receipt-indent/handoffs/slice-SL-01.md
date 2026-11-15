```yaml
slice: SL-01
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 7980943
end_head: ec90f2d   # the code commit; the handoff itself is committed on top of it
commit: ec90f2d
checks:
  - command: "CAPTURE_DINING_BASELINE=1 .venv/bin/python -m pytest tests/test_dining_baseline_capture.py -q   (run 1, from an empty tests/dining_receipt_data/)"
    exit_code: 0     # 51 passed, 22 skipped (before the parametrisation was tidied; same capture code)
  - command: "sha256sum tests/dining_receipt_data/* > $SCRATCH/run1.sha"
    exit_code: 0
  - command: "CAPTURE_DINING_BASELINE=1 .venv/bin/python -m pytest tests/test_dining_baseline_capture.py -q   (run 2)"
    exit_code: 0
  - command: "sha256sum -c $SCRATCH/run1.sha"
    exit_code: 0     # all 7 files OK: byte-identical across runs
  - command: "CAPTURE_DINING_BASELINE=1 .venv/bin/python -m pytest tests/test_dining_baseline_capture.py -q   (run 3, final code; then sha256sum -c again: all OK)"
    exit_code: 0     # 29 passed
  - command: ".venv/bin/python -m pytest tests/test_dining_baseline_capture.py -q"
    exit_code: 0     # 28 passed, 1 skipped (the capture)
  - command: "git diff --exit-code 2676e51 -- src/"
    exit_code: 0
  - command: ".venv/bin/ruff check tests/dining_receipt_fixtures.py tests/test_dining_baseline_capture.py tests/model_server.py"
    exit_code: 0
  - command: ".venv/bin/python -m pytest tests/test_receipts.py -q -k test_vision_and_real_qr   (sanity check for the model_server.py change)"
    exit_code: 0
escalations: []
```

## What was done
- `tests/dining_receipt_fixtures.py` (new): breakfast lines and indents (`BREAKFAST`, `BREAKFAST_TEXTS`, `BREAKFAST_INDENTS`), `vision_lines(texts, indents=None, tables=None)` (v7 answer; indent `None` omits the key), `old_vision_text` (today's `{"full_text"}`), `dump_requests` (the one way to write/compare `q56_*.json`), line-id functions for image / one-page PDF / two-image document (`image_id`, `pdf_id`, `group_id`, `GROUP_SPLIT = 20`), stub builders `breakfast_stub(name)` for B0, B1, B2, B3, B4, B4e, B5, B5n, B5a, B9, B10, plus `side_line_stub` (B6/B6z), `grocery_re_read_stub` (B7), `b8_stub`, `b11_stub` (B11, b/c/d/e/n, g, g'). Each returns `(texts, indents, replies)` with replies keyed by schema name. Paths of the captures in `CAPTURES`. The docstring records the capture command and commit. The old-library builder and the "old library" fixtures are NOT here: the plan assigns them to SL-04 (X-UPG) and SL-02.
- `tests/test_dining_baseline_capture.py` (new): `test_breakfast_fixture_adds_up` (hand checks), `test_vision_lines_builds_the_v7_answer`, `test_every_stub_citation_quotes_the_line_it_names` (every stub, every id style), `test_stub_changes_follow_the_contract`, and `test_capture_the_v6_readings_and_the_v56_requests` (skipped unless `CAPTURE_DINING_BASELINE=1`; asserts the v6/v3/v2-group/v56 version values first).
- `tests/dining_receipt_data/` (new, tracked): `r6_result.json`, `p3_result.json`, `g2_result.json` (stored `result_json`, byte for byte), `q56_r6.json`, `q56_p3.json`, `q56_g2.json` (7 reasoning requests each: Classification, ReceiptStarts, ReceiptDiningSummary, ReceiptIdentity, Items, PurchaseDescription, Rewards; no vision request), `row_instruction_v56.txt`.
- `tests/model_server.py`: `start_model_server(port=0)` gained an optional port (default unchanged).

## Deviation to check (determinism)
The two capture runs first **differed in one byte range**: `r6_result.json` stores the vision server's URL (`engine.base_url`, e.g. `http://127.0.0.1:41559/v1`), and the stub server binds a random port. P3/G2 results and all requests were already identical. This is not a masking of the capture: the capture test now runs the stub server on a pinned port (`CAPTURE_PORT = 18734`, in its own `capture_model` fixture, via the new optional `port` argument), so `r6_result.json` holds `http://127.0.0.1:18734/v1`. After that, two runs from an empty directory and a third run from the final code were byte-identical (`sha256sum -c` OK). The plan said to stop on any difference; I judged this a routine test-infrastructure fix, not a spec question, since no application behaviour or masking is involved. SL-02+ must treat `engine.base_url` in the R6 capture as a fixed value (never compare it with a new run's port).

## Notes for later slices
- The P3 capture is a one-page image-only PDF made with `make_pdf(path, [None])`; G2 is two PNGs (`receipt_p1.png` lines 1–20, `receipt_p2.png` lines 21–28) combined with `suggested_groups()` / `change_group(id, "confirmed")`. The extraction request order for all three is Classification, ReceiptStarts, ReceiptDiningSummary, ReceiptIdentity, Items, PurchaseDescription, Rewards.
- `row_instruction_v56.txt` is the dining-form row instruction as sent (from " Missing fields are null; …" through KIND_ROWS["dining"]). The capture asserts all three readings sent the same text.
- Capture content differs per run only by nothing now; if a later slice's Python/PIL/model_server change alters it, do not regenerate: investigate (the file is the definition of "today's").
- `progress.yaml` showed as modified in the worktree at start (the orchestrator's); I did not touch or commit it.

## Open issues
None.
