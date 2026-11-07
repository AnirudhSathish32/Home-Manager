```yaml
slice: SL-05
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 6fb0570
end_head: e7370f1   # the slice's commit; this handoff is committed on top of it
commit: e7370f1
changed_files:
  - evals/run.py        # pay_readers: engine only; reported_tables import dropped
  - evals/report.py     # PAY_READERS = ("engine",); summary and markdown show the engine only
  - evals/graders.py    # pay_reader: the left_out_stubs stand-in removed (it lived here)
  - tests/test_evals.py # legacy pay reader assertions -> engine only (SC-94 edit list)
  - docs/documents.md
  - docs/money.md
  - docs/evals.md
  - docs/open-work.md
checks:
  - command: ".venv/bin/python -m pytest tests/test_evals.py -q"
    exit_code: 0   # 27 passed (run twice: after the test edit and after the docs)
  - command: ".venv/bin/python -m evals.synthetic <fresh tmp dir>"
    exit_code: 0   # "Synthetic corpus with 53 cases"; 53 answers.json written
  - command: ".venv/bin/python -m ruff check evals tests/test_evals.py"
    exit_code: 0
  - command: "grep legacy under pay readers in evals/ src/ scripts/ docs/"
    exit_code: 0   # only evals.md's sentence saying the legacy pay reader was removed / ignored in old runs
  - command: "docs heading citation scan over src scripts evals tests"
    exit_code: 0   # no heading renamed (git diff docs has no changed '#' line); 15 non-matching citations are line-wrapped citations or pre-existing, none to a heading touched here
escalations: []
```

# SL-05 handoff: evals report the pay engine only, docs describe one path (FR-96, FR-97)

## Code
- `evals/run.py` `pay_readers` returns `{"engine": pay_reader(...)}`; the `legacy` branch (`pay_rows(reported_tables(...))`, single-part split) is gone, as is the `reported_tables` import. A raising engine still yields `pay_reader(..., failed=True)`.
- `evals/graders.py` `pay_reader`: the stand-in lived here: `left_out_stubs` removed from the result and its docstring. `left_out` stays.
- `evals/report.py`: `PAY_READERS = ("engine",)`, `READER_NAMES_PAY = {"engine": "Pay engine"}`; `aggregate`, `pay_reader_summary` and `pay_comparison` use it, so `summary.json` `pay_readers` has `engine` only and `report.md` has one row ("read by the pay engine (N files, M stubs ...", no "stand-in", no "n/a"). Statement `table_readers` (`READERS`, `legacy` kept) is untouched. Allowlist keys unchanged (`left_out_stubs` was never in it). One addition: `aggregate` skips a `legacy` entry under `pay_readers` of an older `results.jsonl` instead of raising a KeyError when it re-reports that run.
- `tests/test_evals.py`: `test_pay_reader_counts...` (no `left_out_stubs`), `test_pay_stub_readers_are_compared...` (engine counts as the phase 2 test asserted them: 5 files, 7 stubs, exact == values, split_right 5, to_review 0, guesses; `pay_readers` keys == {engine}; report has no "Today's reader"/"stand-in"), the suppression/failing-engine test (no `legacy` key). The test function name still says "compared" (kept to avoid a rename outside the edit list's need).

## Docs (FR-97), headings unchanged
- `documents.md` "Pay stub rows from the printed columns": "Which pages (one path)" (flat text for pages without a pay table, untrusted pages and an engine fault; the grid tables no longer used; vision tables kept for scans; v36); rows (whole-number columns, one-run headings); continuation bound; column roles (negative rows vote, shared-hours products, totals since a title); the probe prints untrusted pages; new "Known limits" bullet: SL-03's (b) continuation bound (0.75 font sizes), SL-02's tight-column limit (a whole number within 1.5 font sizes after an amount in the same run), headless one-row hours/rate (c), untrusted page / flat reading may go to review, SL-04's notes (summary box on an untrusted page loses the "no pay table" note; PAY_FAILED checks only while the part is still classified pay stub).
- `money.md` "Money in and paystubs": the one-path sentence and the flat-text paragraph name the flat cases.
- `evals.md` "The two table readers": pay stubs measure the engine alone; `pay_readers: {engine}`; legacy gate replaced by "reading the counts on your corpus".
- `open-work.md`: dropped the legacy-path removal, whole-number hours, avoided layouts a/b/d/e/f and the eight-repairs items; kept layout (c), unmeasured real-stub accuracy with the probe, split edge cases and the `test_tax_engines.py` note.

## Open issues
- The citation scan found 15 non-matching `docs/<doc>.md "Heading"` citations, all line-wrapped citations or to headings absent before this slice (e.g. `docs/ui.md "Source viewer"`, `docs/open-work.md "UI redesign"`); none involves a heading this slice touched. Not changed.
- I wrote the "Known limits" and the SL-04 note from the handoffs and read the code only where noted; wording about "re-classified part" and "summary box on an untrusted page" rests on SL-04's own notes.
- The orchestrator still runs the full suite once.
