```yaml
slice: SL-09
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 203b7c8
end_head: d58fce2   # the docs commit; this handoff is committed right after it
commit: d58fce2     # commits of the slice: 936a649 (evals, previous worker), 800ec68 (probe), d58fce2 (docs)
checks:
  - command: ".venv/bin/python -m pytest tests/test_evals.py -q"
    exit_code: 0   # 27 passed in 52.8 s (re-run by this worker on 936a649's code)
  - command: ".venv/bin/python -m evals.synthetic <tmp dir>"
    exit_code: 0   # "Synthetic corpus with 53 cases"
  - command: ".venv/bin/python -m pytest tests/test_paystub_engine_generator.py -k probe -q"
    exit_code: 0   # 4 passed, 363 deselected (cases 3, 4, 5, 11)
  - command: ".venv/bin/ruff check src tests evals scripts"
    exit_code: 1   # only the 2 errors present at START_HEAD (tests/test_document_v2_browser.py:410, tests/test_receipt_kinds.py:977); my files are clean
escalations: []
```

# SL-09 handoff (resume r2): evals, probe, docs

The previous worker stopped on an API rate limit after committing the evals part. This worker re-ran its checks, read the uncommitted probe and its test, kept both, wrote the docs and committed in two steps.

## Commits
- **936a649 (previous worker; verified here, not changed).** `evals/corpus.py`, `graders.py`, `report.py`, `run.py`, `synthetic.py`, `tests/test_evals.py`: five aligned pay stub files appended after the 48 documents (ids and answers pinned by a hash test), the three-stub case carries `stubs`, split results are graded per stub, the model-free `pay_readers` comparison (legacy `table_grid` + paystub columns vs `paystub_tables.read`), `guesses: {kind: {made, right}}` in `summary.json`, allowlist and `report.md`. `tests/test_evals.py` passes (27) and `evals.synthetic` writes 53 cases.
- **800ec68 (probe, R-A / OD-6).** `scripts/statement_diagnose.py <pdf> paystub` prints only shapes and counts: per page the pay tables (column count, edges and zones as percentages of the page width, roles and how they were decided, rows, totals by kind, heading-line count, block, partner), summary boxes, other tables, unplaced-line counts, guesses by kind, and how many stubs the file splits into with the lines of each. Exceptions are printed by class only. `tests/test_paystub_engine_generator.py::test_generator_only_probe_prints_no_document_text_amounts_or_dates` (cases 3, 4, 5, 11) runs it in a subprocess (`python -I`) on a generated PDF and asserts no capitalised fixture word, amount (with or without separators), date, pay date or employer appears, that `pay stubs found: N` equals the case's stubs, and that "summary box," / "block: left" appear exactly when the case has a box / side-by-side layout.
- **d58fce2 (docs).** `docs/documents.md` gains "Pay stub rows from the printed columns" and "Several pay stubs in one file" (before "Model runs, queues and cancellation"); `docs/money.md` "Money in and paystubs" gets a paragraph (engine amounts, guesses are notes, VOID / duplicates don't count, summary taxes and deductions stored as magnitudes); `docs/evals.md` "The two table readers" covers pay stubs, the counts, the legacy review stand-in, guess counts and the generator (and the "48-case" mention is now 53); `evals/README.md` 48 → 53 (command comment and the tests line); `docs/open-work.md` records FR-40 as built and what is left (below). No heading was renamed.

## Doc claims checked against the code
Note texts, guess kind names, `EXTRACTION_VERSION` (`typed-extraction-v35-paystub-engine`), VOID regex and duplicate identity (`pay_stub_twin`), the split rule, the summary field names in `evals/graders.py` / `report.py` (`to_review`, `checkable`, `checks_held`, `split_right`, `unplaced`, `failed`) were read in the source, not taken from past handoffs. `docs/ui.md` already covers the Tables tab (SL-05), so it is not touched.

## Left in docs/open-work.md
Removing today's pay stub path after your corpus run (D5); FR-41 – FR-44 unchanged; whole-number hours read as label text; the generator's avoided combinations (SL-08 E2); the eight engine repairs without their own unit tests; the 8 `tests/test_tax_engines.py` failures (also failing at 44f40b0); a file whose only pay stub is rejected shows no library amount; a reissued stub with another net pay counts.

## Notes
- Not run: the full suite, any eval against a real model or corpus, the 3.5-minute generator module beyond `-k probe`.
- `plans/pdf-table-engine-paystubs/progress.yaml` untouched and uncommitted.
- In "Several pay stubs in one file" I described the library file row as "earliest non-rejected stub's pay date; amount only with one non-rejected stub" and the status as the worst of the stubs' (from the SL-06 handoff and `storage.py`); I read the handoff, not every line of the query.
