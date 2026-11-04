```yaml
slice: SL-07
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 0d4e455   # round 1; round r2 started at 2521859
end_head: 8246356   # fix round r2: the code commit; the handoff file is committed with it
commit: 8246356
checks:
  - command: ".venv/bin/python -m pytest tests/test_paystub_split.py -q"
    exit_code: 0   # 35 passed (5 SL-06 tests + 30 new)
  - command: ".venv/bin/python -m pytest tests/test_receipt_segments.py tests/test_extraction.py tests/test_paycheck.py -q"
    exit_code: 0   # 48 passed; receipt splitting unchanged
  - command: "RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_paystub_engine_browser.py -q"
    exit_code: 0   # 3 passed (2 existing, 1 new: SC-74 step 2)
  - command: ".venv/bin/ruff check src tests"
    exit_code: 1   # only the 2 errors present at START_HEAD (tests/test_document_v2_browser.py:410, tests/test_receipt_kinds.py:977); my files are clean
  - command: ".venv/bin/python -m pytest tests/test_paystub_engine_record.py tests/test_layout_consumers.py tests/test_paystub_forms.py tests/test_library.py tests/test_bills_ledger.py tests/test_reconcile_tools.py -q"
    exit_code: 0   # extra regression run: 133 passed, 1 skipped (opt-in browser test)
  - command: "RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_document_v2_browser.py -q"
    exit_code: 0   # extra, the page's JS changed: 9 passed
  - command: "r2: .venv/bin/python -m pytest tests/test_paystub_split.py -q"
    exit_code: 0   # 37 passed (35 + 2 new tax_tables tests); the new two-year test fails (only 2025 asked) with the manager.py change stashed
  - command: "r2: .venv/bin/python -m pytest tests/test_tax_engines.py tests/test_paycheck.py -q"
    exit_code: 1   # 8 failed, 32 passed; the same 8 fail at START_HEAD 2521859 with my changes stashed (tests/test_tax_engines.py, engine output keys such as taxable_income/agi missing; not touched here)
  - command: "r2: .venv/bin/ruff check src tests"
    exit_code: 1   # only the 2 errors present at START_HEAD (tests/test_document_v2_browser.py:410, tests/test_receipt_kinds.py:977); my files are clean
escalations: []   # none blocking; D1 – D3 below are decisions to review (D3 is resolved in round r2)
```

# SL-07 handoff: several pay stubs in one file

## What was built
- **`documents/paystub_split.py` (new, pure, lines only).** `stub_parts(lines)` as P8: starts are lines with a pay date / check date / payment date / pay period / period ending label (the engine's own `pay_tables.STUB_START`) and a date token; a start opens a new stub only after the open stub printed a net pay line (`net pay`/`net payment`, lettered, optional colon, with an amount); parts without a net pay line join the part before (the first joins the next); after the joins each stub's first line moves up over its heading lines (at most 4, same page only, no amount, after the previous stub's last net pay line); one part is `[(0, len(lines))]`. Projected table rows (`Net Pay | 1,800.00 | …`) are read with the `|` separators dropped.
- **`documents/extraction.py`.** `run` calls `pay_parts` for pay stubs (the user's saved split wins, as receipts; else `stub_parts`; a failure is logged by class and run id, the file is read as one with the record note `PAY_SPLIT_FAILED`), runs the per-part classification for pay stubs too (a part that isn't a pay stub reads the file as one, with the split note "A part of this file is not a pay stub, so the file was read as one document."), and reads each part with `read(…, lines[first:last], …, pay=pay)`. `requested_kinds` is called with the file's type. `record` adds `PAY_SPLIT_NOTE` as a record note (never an issue) for a split, unconfirmed pay stub; receipts keep `SPLIT_NOTE` in the issues. `publish` adds the VOID note and the two duplicate notes before the record is written, and after publishing calls `Ledger.mark_void` / `mark_duplicate` and returns `review_status: rejected`. `split()` joins `income_records` (rows get `kind` `"paystub"`/`"receipt"`, `income_record_id`, `employer`, `pay_date`, `display.net_pay`; receipt rows get `kind: "receipt"` and are otherwise as before). `confirm_split` also removes `PAY_SPLIT_NOTE` from `income_records.details_json["notes"]` (any status, no status change). `set_split` stamps the user's rows with the replaced run's id (see "split_changed" below).
- **`finance/ledger.py`.** `pay_stub_twin(record, source)` (the earlier non-rejected stub with the same employer and pay date; lower id wins, so Extract again is stable), `mark_void`, `mark_duplicate` (both via `reject_automatically`: rejected/automatic, never a user-decided record; a duplicate's original must still count). `publish_income` now keeps each line's id by position when it rewrites a stub's lines (D2).
- **`app/static/document_v2.js` `doc2Split`.** For pay stub segments: "This file holds N pay stubs", chips = employer + "pay date · net pay", no "waits in To check" warning, Confirm split / Merge with next / Split here as today with pay-stub wording. No inline style, no new asset; the ui-ux-pro-max skill was loaded and `docs/ui.md` "Screen rules" followed (existing chip/button markup reused).

## Rules as built (P8, with the user's duplicate decision)
- **VOID:** a part holding a line whose whole text is VOID (case-insensitive, surrounding `*`/`-` allowed) gets the note "This pay stub is printed VOID, so it doesn't count." and is rejected/automatic after publishing (a user-decided record is left alone). Extract again re-publishes it (status reset by `_upsert`) and marks it again.
- **Duplicates:** identity = employer, pay date, net pay, currency. The stub with another non-rejected stub of lower id of that identity is recorded with its lines, noted "This pay stub repeats the one paid by <employer> on <pay date> (<net pay as 1,800.00 USD>), so it doesn't count." and rejected/automatic. Same employer and pay date with another net pay counts and carries "Another pay stub from <employer> has the same pay date."; only the later-recorded stub carries it. When the original is rejected, the next Extract again of the duplicate counts it (tested).
- **split_changed (FR-74):** `set_split` stamps the user rows' `extraction_run_id` with the replaced model run's id; when the user splits a file that had no segments into more than one part, with the latest succeeded run's id; re-submitting the rule's own split is not a change. The next run adds one `split_changed` guess (kind `split_changed`, page of the part's first line, no table, text "You changed where the pay stubs in this file start; the file was read with your split.") to each part's `details.guesses`, not to the notes.

## Tests (`tests/test_paystub_split.py`, 30 new; expected values are the contract's literals)
SC-72 a–d (d: PNG via the vision stub, flat path); SC-73 (26 MINI-C stubs, 26 deposits: segments 0–25, 26 proposed links to the deposit on each pay date, cash flow 4,680,000, library row with no amount and earliest date, filing identity); SC-74 steps 1, 3, 4, 5 and a separate confirm-drops-the-note test (user-decided stub keeps its status); SC-75 step 2; SC-76 plus a user-decided void stub and a regex test (a word is no void line); SC-66 for the three-stub file (identical income rows incl. line ids, notes, guesses, evidence, segments, same questions asked); the retry, duplicate-capture and restart variants; the two layout-note cases (headerless page 2 → both C-auto; plus `overlapping_text` → stub 1 C-auto, stub 2 `needs_review` with a "Page 2" issue); the one-part split guess (and "confirming the rule's own split is no change"); the three duplicate cases (same file, reissue with another net pay, second file incl. the original rejected → the copy counts) and a unit test that marking never overrides a user decision; `stub_parts` unit tests; the split-rule failure (record note, one log record, no fixture text); a non-pay-stub part. Browser: `tests/test_paystub_engine_browser.py` SC-74 step 2.

## Decisions to review
- **D1: library title.** Left unchanged. A pay stub file's title is "Paystub MM/DD/YYYY" from `min(pay_date)` (SL-06), so a split file reads "Paystub <earliest date>"; the "X + n more" form is only the receipt branch. No change needed.
- **D2: line ids (touches `Ledger.publish_income`).** SC-66 says the three-stub file's `income_lines` rows are identical "ids included". Lines were deleted and re-inserted, so with several stubs the ids of the earlier stubs' lines moved up on Extract again (a single stub reuses its own ids by chance). `publish_income` now re-inserts each line with its previous id by position. Same columns and values; only id stability changes.
- **D3: `look_up_tax_tables` (`app/manager.py`) is untouched** and still reads only the first segment's `publication["id"]`; later stubs in other tax years don't trigger a lookup. Not in the slice's files.

## Not done / notes
- SC-74's API steps are tested through `ExtractionService.split/set_split/confirm_split` (what `Manager` and the three endpoints call), not through HTTP; the page step is the browser test. The user's PUT triggers `Manager.start_extraction(force=True)`, mirrored by `Run.extract(force=True)`.
- The merged segment's values (G3) are not asserted; the run succeeds and the unclassified rows of the second stub get guessed groups.
- `PaystubTables.viewer` is still unused, and a multi-page table is still one entry per page with the same id; neither broke a split file's Tables tab (not changed).
- Docs (`docs/documents.md` "Several pay stubs in one file") are SL-09.
- `progress.yaml` untouched and uncommitted.

# Fix round r2: tax tables for every stub of a split file

Defect (found by the orchestrator): `Manager.extract_and_file` called `look_up_tax_tables` only for the top-level publication, which for a split file is segment 0's, so a file spanning two tax years never looked up the second year's tables. This resolves D3.

- **`app/manager.py` `extract_and_file`.** The income-record branch now loops over `publication.get("segments") or [publication]` (as the receipt loop above it) and calls `look_up_tax_tables(published["id"], work)` for each published income record. The one-stub path is the same call as before. `look_up_tax_tables` is unchanged: it still skips years whose tables exist (`tax_tables.tables.needed`) and never fails the extraction.
- **`tests/test_paystub_split.py`.** Two tests with `tax_tables` in the name, running the real `Manager.extract_and_file` and `Manager.look_up_tax_tables` on a stand-in manager (real extraction service and ledger, `tax_tables.enqueue` recorded and raising its own "no key/model" `ValueError`, so no model or network call): a two-stub MINI-C file paid 2025-12-19 and 2026-01-02 asks for both years in order; a one-stub file asks once. With the `manager.py` change stashed the two-year test fails (only 2025 asked).
- `tests/test_tax_engines.py` has 8 failures that already exist at START_HEAD 2521859 (verified with my changes stashed); not related to this change and not touched.
- `progress.yaml` untouched and uncommitted.
