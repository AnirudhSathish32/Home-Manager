```yaml
slice: SL-10
result: ready_for_verification
provider: claude            # route provider instance: claudeAgent
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: caf9449
end_head: 2a222b2          # the handoff file is committed after this (its commit is not in the list)
commit: [ab98767, c8cb614, 2a222b2]   # ab98767 evals code and tests; c8cb614 evals README and docs/evals.md; 2a222b2 documents.md, money.md, open-work.md
checks:
  - command: ".venv/bin/python -m pytest tests/test_evals.py -q"
    exit_code: 0   # 31 passed
  - command: ".venv/bin/python -m pytest tests/test_evals.py -q -k bill"
    exit_code: 0   # 4 passed (SC-124 evidence)
  - command: ".venv/bin/python -m evals.synthetic \"$(mktemp -d)\""
    exit_code: 0   # "Synthetic corpus with 58 cases"
  - command: ".venv/bin/ruff check evals tests/test_evals.py"
    exit_code: 0
escalations: []
```

# SL-10: evals and docs (FR-124, FR-126; SC-124)

No test failed, so nothing in `baseline_failures` was hit. Synthetic data only: nothing under P:\Finances, %LOCALAPPDATA%\HomeManager or P:\EvalCorpus was read or run. No migration. Not changed: spec, contract, plan, approvals, progress.yaml, `evals/bill_layouts.py`.

## Changed files
- `evals/synthetic.py`: `BILL_SEED = SEED + 3`, `BILL_BASE`, `BILL_FILES` (five fixed layouts: utility with Usage/Rate/Charge and a summary box above and below, phone with holder sections and a `paren` credit, rent with new charges not printed and a second printed amount due, two-page headless with a stub on its own page, three bills), `aligned_bill(index, **choices)`, appended after the 53 documents. A multi-bill file carries `stubs.json` (the existing `Case.stubs()`). Each page's footer `US dollars.` becomes `US dollars (USD).` so the answers' currency is printed (as `aligned_statement` does for `$ (USD)`); `test_every_synthetic_answer_is_printed_and_adds_up` needs the code in the text.
- `evals/graders.py`: `BILL_GUESS_KINDS`, `bill_reader(bills, rows, parts, reasons, unplaced, failed)`, `bill_split_is_right`; `guess_counts` also counts the bill kinds. `GUESS_KINDS` stays the five pay kinds (a test pins it).
- `evals/run.py`: `bill_rows`, `bill_readers` (model-free, `native_pdf` bills with an `embedded_text` page and a confirmed-complete row list only, so the image bills aren't counted), `details["bill_readers"]`, `to_review` for bills; a bill file's records are graded as a list through `grade_stubs`, like pay stubs.
- `evals/report.py`: `bill_readers` aggregate, `bill_reader_summary`, `bill_comparison` in report.md, allowlist keys (`bill_readers`, `lines`, `files_split`, `split_review`, the bill guess kinds), `guess_kinds`/`guess_line`.
- `evals/README.md`, `tests/test_evals.py`, `docs/documents.md`, `docs/money.md`, `docs/evals.md`, `docs/open-work.md`.

## Decisions and deviations (for the reviewer)
1. **`files_split` / `split_right`.** SC-124 wants `files_split` 1 and `split_right` 1 on the five files. `files_split` = files that hold several bills (answers) or that the rule cut into several; `split_right` = of those, files cut into exactly the answers' bills, each part holding its bill's amount due. A one-bill file left whole counts in neither; a missed split or a wrong split shows as `files_split` 1, `split_right` 0. `split_review` = files where the rule raised an FR-129 reason on any part.
2. **`checks_held`/`checkable` is the lines check only.** The answers hold no previous balance or payments, so the carried check can't be graded from them (the plan's "lines and carried checks"). Recorded in docs/evals.md and open-work.
3. **Lines are matched by amount** (a credit by magnitude, since Record signs it by kind), not by label: the answer's description is the model's, not the printed label.
4. **Guess kinds in `summary.json`.** `guesses` holds the five pay kinds as before, and the bill kinds (`charge_column`, `unclassified_row`, `amount_due`; `split_changed` is shared) only when the run read text-PDF bills, so the existing pay-only tests' `set(summary["guesses"]) == set(GUESS_KINDS)` hold unchanged. A run that read bills reports all seven. Suppressed below 3 files counted over pay and bill files together.
5. **`to_review` for bills counts bills** (not files), like pay stubs count stubs; the report column says so.
6. **Edits to `tests/test_evals.py` beyond the plan row's list.** The four 53 → 58 tests, plus: `bill` count 2 → 7 in the corpus test; the pay stub test slices `everything[48:53]`, excludes bill files from its "every other case is its own stub" and `stubs.json` count checks; three `document_type != "paystub"` filters (statement tests) became `in ("bank_statement", "credit_card_statement")`, because the five bills are also `aligned` and not pay stubs. Added: `BEFORE_BILLS` pin, `test_bill_aligned_files_are_added_after_...`, `test_bill_readers_are_compared_and_the_engine_reads_every_aligned_bill_exactly` (SC-124), `test_bill_comparison_leaves_out_image_bills_...`, `test_bill_reader_counts_lines_checks_and_the_split_and_never_text`. The SC-124 test: 5 files, 39 lines all exact, 7 bills all checks held, `files_split` 1, `split_right` 1, `split_review` 0, `failed` 0, `unplaced` 0, every guess made == right, summary passes `check_summary` and holds no provider, description, amount or date.
7. **venv note.** The editable install in `.venv` points at the main checkout's `src`, so `python -m evals.synthetic` (a plan verification command) imports `home_manager` from there, and `-m evals.run` would too. It ran fine because `evals.synthetic` imports only `home_manager.core.answers`. pytest uses `pythonpath = ["src", "."]` and the worktree's own code. I used `PYTHONPATH=src:.` for my own probes.

## Docs (FR-126)
- `docs/documents.md`: new "Bill lines from the printed columns" (pages and fallbacks, SC-114 layout-note waiver on every text page of an engine-read bill, rows, roles, money off, the anchor, key, total, late, heading and credit word lists, holder titles with G14's narrowing and the 80-character cut, what the model does, the rate rule, repeated amounts and FR-117, worked-out new charges, guess kinds, review, evidence, the `bill` diagnose mode, limits incl. SL-09's two misread layouts and the user-split scoping) and "Several bills in one file" (keys, the rule reading the engine's anchors, reasons (a)–(d) as built incl. (b)'s "after it" wording, one record each, invoices not split, scanned and combined-image files split too (D14), no review for a certain split, the split panel with the server's currency chip, `split_changed`, reading again, VOID, duplicates, filing by the first non-rejected bill's due date for several bills, D20's limit, no donating). A pointer in "Bill kinds".
- `docs/money.md` "Bills and their lines": text-PDF bills take amounts from the print, guesses are notes, new charges worked out, the rate, holder titles, VOID and duplicates don't count; "Reading a statement or receipt again": a bill line's correction is held (rule, reason texts, undo).
- `docs/evals.md` "The two table readers": a **Bills** block (what is counted, counts, split counts, guess counts, the aligned files, the generator, reading the counts on your corpus).
- `docs/open-work.md` "PDF table engine": FR-41 built; the left-over list: real-bill accuracy unmeasured (`scripts/statement_diagnose.py <pdf> bill`, `python -m evals.run` in your own terminal), invoices D5 and a file of several invoices D16, budget billing D12, two bills on one page D18, consolidated bills, D19, D20, donating split bills, a user-saved split that differs from the rule's, G14's narrowing (H1), the 80-character cut (H2), SL-09's two misread layouts, plus two small ones I found (a deleted line leaves a held correction's reason; `checks_held` is the lines check only).

## Citations
Every `docs/<doc>.md "Heading"` in src, evals, scripts, tests and docs that names documents, money, evals or open-work was checked against the headings: the one added citation (`documents.md "Several bills in one file"`, in `extraction.py` and `docs/ui.md`) resolves, and no heading I touched was renamed. Three citations were already unresolved at START_HEAD and are not from this feature: `documents.md "Known limits"` (`pay_tables.py:270`), `documents.md "Native PDF layout"` (`tests/test_pdf_layout.py:141`), `open-work.md "UI redesign"` (several tests). The in-doc links I added (`#bill-lines-from-the-printed-columns`, `#several-bills-in-one-file`, `#several-images-as-one-document`, `#bills-and-their-lines`, `#reading-a-statement-or-receipt-again`, `#the-document-page`, `#the-two-table-readers`, `#pdf-table-engine`) all match a heading.

## Not run
The full suite and the browser set (the orchestrator's final verification). Real-corpus evals (not mine to run).
