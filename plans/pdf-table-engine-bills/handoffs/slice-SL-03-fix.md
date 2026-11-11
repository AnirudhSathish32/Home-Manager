```yaml
slice: SL-03-fix
result: ready_for_verification
provider: claudeAgent
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 86d52eb
end_head: this commit (a file can't hold its own hash; see the orchestrator's return message or git log -1)
commit: this commit (parent 86d52eb; see git log -1)
checks:
  - command: ".venv/bin/python -m pytest tests/test_bill_engine_record.py -q"
    exit_code: 0   # 70 passed
  - command: ".venv/bin/python -m pytest tests/test_paystub_engine_record.py tests/test_paystub_split.py tests/test_paystub_cleanup.py tests/test_layout_consumers.py tests/test_bill_kinds.py -q"
    exit_code: 0   # 222 passed
  - command: ".venv/bin/ruff check src/home_manager/documents/extraction.py tests/test_bill_engine_record.py"
    exit_code: 0
escalations: []
```

# SL-03-fix: UTIL-2P page 2 is C-auto (SC-114 step 2)

## Changed files
- `src/home_manager/documents/extraction.py`: `pay_layout_notes(evidence, pay, lines, text_pages=None)`. The waived pages are `pay.engine_pages | text_pages`. `read` passes `text_pages` (the file's `embedded_text` pages that have a layout, already computed there) only for a bill reading (`None if engine else text_pages`), so a pay stub calls it as before and behaves exactly as before. A page whose layout issues are exactly `["unresolved_columns"]` is waived on every text page of a bill read by the engine, with or without a charge table. Any other issue (alone or alongside it) still raises its note and so review. `BILL_FAILED` parts and readings with no layout never reach this branch (`bill_part` is None), so they are unchanged.
- `tests/test_bill_engine_record.py`:
  - `test_sc114_a_page_with_no_charge_table_keeps_the_models_line_and_says_so` now asserts `auto(record)` (review_status verified, issues == []), after a P-check that page 2's reading carries `["unresolved_columns"]`. The old "issues == [Page 2 ...]" assertion and its comment are gone.
  - New `test_sc114_a_text_page_with_no_charge_table_and_another_layout_issue_still_needs_review`: page 2's layout is `["unresolved_columns", "glyph_outside_page"]` (via a `read_result` monkeypatch; `overlapping_text` would make the page non-native and change the model double's chunks), and exactly one issue holds the `Page 2 PDF layout needs review: unresolved_columns, glyph_outside_page.` note.
  - New `test_sc114_a_pay_stub_page_without_an_engine_table_keeps_its_layout_note` (unit-level, `SimpleNamespace`): with `text_pages=None` a page with no engine table keeps its note; it is waived on an engine page, or when a bill passes it as a text page.

## Decision for the orchestrator
The waiver set is the file's text pages, not just the part's pages. This is the same outcome for every page of the part. For a page that is in no part's `line_pages` but belongs to another part (BL-MULTI), the literal "this part's text pages" would leave that page's note on the other parts. File-wide avoids that. Say so if you want the narrower set.

## Not done
No doc changes (not permitted): `docs/` and the plan's P7.1 "Layout review notes" wording still say "a page the engine read a charge table on". The plan text is narrower than what is now built.
