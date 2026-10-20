# Pay stub columns on photos — implementation plan
Spec: specs/paystub-columns/spec.md
Spec sha256: 52016f01e73580fb41013e6fb4acef4ef6152ee6c5c077562fb69541f352c5f8

<!-- Approval lives in approvals/paystub-columns.json, bound to this file's hash. No Status line.
     Execution progress goes in plans/paystub-columns/progress.yaml, never in this file. -->

## Verified repository integration points
All at the working tree on `reorganize-packages` (HEAD 50154b6).

| Where | What it does today | Used for |
|---|---|---|
| `src/home_manager/documents/extraction.py:2509-2516` `read()` | `tables = reported_tables(evidence)`; `has_table_contract` is true for any vision reading (`vision_tables` not None) or native layout page; a pay stub with it runs `anchor_paystub`. | FR-31 routing |
| `extraction.py:733-800` `anchor_paystub` | Copies cells for cited rows in validated tables; with no row found, nulls `current`/`ytd` (`:773-775`) or a summary field (`:797-799`) when any cited line has >1 `NUMBER` match. | FR-31, FR-34 |
| `layout_context.py:48` `evidence_tables` | Validated vision tables (`vision_tables.tables`, all-or-nothing validation in `vision_tables.py:6`), tables rebuilt from pipe-separated text (`restore_text_tables`, `vision_tables.py:103-118`, via `pdf_reader.py:61-62`), or native PDF tables. | "validated table" = an entry here; pipe-separated photo stubs (e.g. `seed_paystub`) stay on the anchor path |
| `pdf_reader.py:100-107` | Every PDF page gets `vision_tables`; an embedded-text page gets `embedded_tables(...)`, or `[]` plus a `pdf_table_ambiguous` issue. | a text PDF with no rebuilt table has no validated table (P6) |
| `extraction.py:1020-1054` `ask()` / `amount_supported` (`:908`) | Rejects (or, for PayLines on retry, nulls with a note) an amount not printed in its cited evidence. | FR-32 "today's citation check" — unchanged |
| `extraction.py:1179` `normalize(kind, header, rows, currency, lines=None, details=True, receipt_kind=None)` | Calls `paystub_lines(..., fields, line_text)` (`:1291`). Callers: `publish()` (`:2349`, `:2354`), `evals/tasks/document_forms.py:72`, `evals/tasks/receipt_kinds.py:90`. | new keyword |
| `extraction.py:1891-1976` `paystub_lines` | Builds lines, labels, FR-22 slots, runs `this_period_guards` (`:1942`), marks guarded lines `details.current_status="ambiguous"`, stores `record["details"]["guards"]`, then arithmetic. | FR-33/FR-35 hook |
| `extraction.py:1852` `this_period_guards` | FR-22 rules a/b/c on slot values; clears via `slot["clear"]`. Unchanged. | FR-32, SC-29, SC-34 |
| `extraction.py:2572-2605` `read()` return → `record()` → `publish()` | The reading dict carries `cell_references`/`summary_references` to `publish`. | carries the new flag |
| `finance/ledger.py:1906-1931` `_correct_income_line`, `income_line_label` | A line correction drops issues that **start with** `"This period: <description>"` / `"Year to date: <description>"`, stores them for undo. | FR-36 |
| `finance/ledger.py:1944-1961` `apply_income_line_corrections` | Re-applies the latest line corrections after a re-read and drops their label-prefixed issues. | FR-36 on reading again |
| `finance/ledger.py:1615-1628, 1888` | Summary-field corrections drop issues starting with the field label (`CORRECTION_LABELS`, e.g. "Gross pay"). | FR-36 for summaries |
| `core/money.py:18` `NUMBER`, `:70` `decimals_in`, `:75` `printed_decimal` | Number matching; `NUMBER` matches "401" in "401k". | FR-34 |
| `extraction.py:44` `EXTRACTION_VERSION = "typed-extraction-v23-document-forms"` | Run reuse key. | FR-37 |
| `evals/tasks/document_forms.py` | Fixtures P-table / P-flat; `run()` calls `extract` + `normalize` directly (not `read()`), so anything placed only in `read()` is invisible to the eval. Report: fields present/right, invented, wrong column counted. | FR-38 |
| `tests/test_paystub_forms.py:356-387` | `SIDE_BY_SIDE` and the strict-xfail `test_a_photo_stub_keeps_this_period_beside_year_to_date` (uncommitted). `read_stub`, `transcribe` (`tests/test_extraction.py:130`) give a vision reading with empty `vision_tables`. | SC-28 et al. |
| `tests/test_eval_tasks.py:236-270` | Asserts the document_forms report rows' exact text. | updated by SL-03 |
| `docs/money.md:129` "Money in and paystubs"; `text_extraction_plan.md` | Docs targets. | FR-39 |

## Architecture, contracts, data flow and decisions

**Data flow after the change** (pay stubs only):

```
read(): tables = reported_tables(evidence)
  paystub and tables        -> anchor_paystub(...)            (unchanged; FR-34 counter in its multi-amount rule)
  paystub and not tables    -> no anchoring; reading["printed_columns"] = True     (FR-31, FR-32)
  other types               -> unchanged
record() -> publish(..., printed_columns) -> normalize(..., printed_columns=...) -> paystub_lines(..., printed_columns)
paystub_lines: build lines/labels/slots
  -> column_checks(...) when printed_columns      (FR-33, FR-35: decides, notes, but does NOT clear yet)
  -> this_period_guards(...)                       (FR-22, unchanged; judges the model's values)
  -> apply column clears                           (null + ambiguous markers)
  -> arithmetic (unchanged)
```

FR-31's condition replaces `has_table_contract` for pay stubs with "at least one validated table" (`bool(tables)`).
`has_table_contract` had no other use, so it is deleted (R1-04). The `elif tables and header is not None` branch is
unaffected (a pay stub with tables always took the first branch).

**Why the column check lives in `paystub_lines`, not `read()`:** (1) SC-29 expects FR-22 rule (b) to name the swapped
Regular too, so FR-22 must see the model's values before FR-33 clears them; (2) line `details` (where the ambiguous
markers live) are built there; (3) the eval calls `normalize` directly, so FR-38 measures exactly the app's rule by
passing the same flag.

**New contracts (all in `extraction.py`, next to `paystub_columns`):**

- `line_amounts(text) -> list[Decimal]` (FR-34): the absolute `NUMBER` matches of a line, left to right, skipping
  label digits: a match whose preceding character is a letter, or whose following character is a letter, or that is
  followed by `(` and a letter ("401k", "401K", "403(b)", "401(k)", "W2"). A parenthesized amount "(50.00)" stays an
  amount (spec domain risk 3). Whole numbers standing alone ("SECTION 125") **count** as amounts — user decision
  2026-10-19: the line then prints more amounts than the header names columns, so FR-33 is skipped there (safe), and
  an eval case measures it.
  - An amount joined to letters ("50.00CR", "2,500.00USD", OCR's "REGULAR2,500.00") is also dropped. The value is
    then not located in its line, or the line prints fewer amounts than the header names, so FR-33/FR-35 skip it
    (fails safe; pinned by a unit case, R1-10).
- `printed_header(line_texts) -> (columns | None, both_named: bool)`:
  - A header line is a source line that prints no `line_amounts` (R1-08) and names at least one this-period word
    (`\bcurrent\b|\bthis\s+(?:pay\s+)?period\b`) and one year-to-date word (`\bytd\b|\byear[ -]?to[ -]?date\b`), the
    same vocabulary as `paystub_columns`.
  - Its columns are the column words found in it, left to right, from {current, ytd, hours (`hours?|hrs`), rate}.
  - `both_named` is true when any header line exists (it gates FR-35).
  - `columns` is the shared sequence when every header line yields the same sequence with no column word repeated.
    Otherwise it is None (header ambiguous, spec "Errors"): FR-33 is skipped and no note is added. A two-block
    header ("CURRENT YTD … CURRENT YTD") repeats words, so it is ambiguous.
- `column_checks(rows, fields, record, lines, line_text) -> list[clear]`, run only when `printed_columns`:
  - **Locating a value.** A value's line is the single cited line (from the line's or field's `evidence`, text taken from
    `line_text`) whose `line_amounts` contain the value's `printed_decimal` (absolute). If no cited line holds it, or
    several do, both checks are skipped for that value.
  - **FR-33, pay lines.** Runs when `columns` is not None, the value's line has `len(line_amounts) == len(columns)`,
    and `columns` holds both current and ytd. The value must equal the amount at its own column's position.
    - If either of the line's values fails, both of the line's values are cleared.
    - It adds one note per value it clears, each starting with that value's correction label, so a correction clears
      it (user decision 2026-10-19). The spec's quoted "Pay line N…" texts are illustrative; the line number stays in
      the body:
      - `"This period: Regular 32,500.00 USD doesn't match the printed columns (pay line 1, line-7): it is printed under YTD; it was left out. Enter this paycheck's amount with Edit details."`
      - `"Year to date: Regular 2,500.00 USD doesn't match the printed columns (pay line 1, line-7); it was left out. Enter the year-to-date amount with Edit details."`
    - The column named in "printed under …" is the header word at the position where the value is printed, or
      "another column" when it isn't at any column position.
  - **FR-33, summary amounts.** The same check runs on `gross_pay`/`gross_pay_ytd` and `net_pay`/`net_pay_ytd` as pairs
    (a failure clears both of the pair), and on `taxes` and `deductions` alone (this-period column).
    - Notes start with `CORRECTION_LABELS[name]` ("Gross pay …", "Gross pay year to date …").
    - A cleared field becomes `None` with an entry in `record["details"]["columns"][name]`, and `review_reasons` then
      doesn't add a duplicate "not found" reason (`:1989`, the issue starts with the label).
  - **FR-35, pay lines only.** User decision 2026-10-19: summary amounts are excluded, since "NET PAY 2,250.00" alone
    is common.
    - Runs when `both_named` is true, the line's this-period value is not None, and its line prints exactly one
      amount: the this-period value is cleared.
    - Note: `"This period: Relocation bonus 5,000.00 USD: pay line 2 prints one amount; check whether it is this period or year to date (line-8). It was left out; enter it with Edit details."`
    - A year-to-date value on a one-amount line is kept, with no note.
    - With no header line at all, nothing runs.
  - **Order in `paystub_lines` (R2-02).** `column_checks` runs before `this_period_guards`. Its clears and
    `record["details"]["columns"]` are applied after `record["details"]` is rebuilt (`:1946`), merging into that dict,
    and before `pay_details` (`:1948`) and the arithmetic.
  - **Clears and markers.** Each clear sets the minor value to None. A line's `details` gain
    `current_status`/`ytd_status` = `"ambiguous"` and
    `column = {"rule": "position" | "one_amount", "line_ids": [...], "value_minor": …, "ytd_minor": …}`.
    These are JSON keys in the existing `income_lines.details_json`, with no schema change. Summary results go in
    `record["details"]["columns"]`.
- Plumbing: `read()` adds `"printed_columns": bool` to the reading; `record()` passes `reading.get("printed_columns",
  False)` to `publish(..., printed_columns=False)`, which passes it to `normalize(..., printed_columns=False)`; default
  False keeps every other caller (receipts, statements, `receipt_kinds` eval, non-published kinds) unchanged.
- `anchor_paystub`'s two multi-amount checks (`:773`, `:797`) count with `len(line_amounts(...)) > 1` instead of
  `len(NUMBER.findall(...)) > 1` (FR-34 "any check that counts a line's amounts"). `cell_amount` is per cell and is
  unchanged (a "401(k)" label cell is never a money column; SC-32 b is a regression assertion).
- `EXTRACTION_VERSION = "typed-extraction-v24-paystub-columns"` (FR-37).

**Decisions taken in this plan:**
- P1 (user, 2026-10-19): column notes start with the value's correction label, one note per cleared value. This is
  needed for FR-36 with the existing prefix clearing, and means no ledger change.
- P2 (user, 2026-10-19): FR-35 applies to pay lines only.
- P3 (user, 2026-10-19): standalone whole numbers count as amounts (FR-34 literal rule).
  - A two-column "SECTION 125 150.00 1,800.00" line prints 3 amounts against 2 columns, so FR-33 is skipped.
  - A one-column "SECTION 125 150.00" under CURRENT YTD prints 2 amounts (R2-01), so FR-33 runs on shifted
    positions and FR-35 doesn't. A this-period 150.00 is then cleared with the column note, not the one-amount note.
  - A model that answered 125 as this period would be kept, as it is today, since 125 is printed in the line.
  - Unit and eval cases pin both lines.
- P4: FR-33 also checks `taxes` and `deductions` summary fields (single, this-period column). The spec's "summary
  amount that prints both columns" covers them, and the check only ever clears a value, never fills one.
- P5: FR-33 clears are applied after FR-22 so FR-22 judges the model's values (SC-29's "FR-22 b also names it"). The
  end state is identical to clearing first.
- P6 (user, 2026-10-19, R1-01): text PDFs are included. An embedded-text page with no rebuilt table (including
  `pdf_table_ambiguous`) is read like flat text and gets FR-33/FR-35, as FR-31 words it. This goes past the spec's
  "images and scanned pages" scope line. No test covered the old behavior, so SL-01 adds one pinning the new one.
- P7: `docs/bugs.md` (uncommitted, holds the user's report) is not edited by this plan.
- P8 (R1-05): "Gross pay" is a prefix of "Gross pay year to date" (same for Net pay). Correcting only a pair's this
  period therefore also clears that pair's year-to-date column note, while that value stays null. This is accepted:
  correcting one side answers the column question for the pair. It is documented and asserted in SL-02. Changing the
  prefix rule would touch the ledger, which P1 avoids.

## Error handling, idempotency and recovery
- Header ambiguous / no header / count mismatch / value in several or no cited lines → the check is skipped silently;
  FR-22 still runs (spec "Errors").
- Two rows on one line: more amounts than columns, so FR-33 is skipped and the values are kept when cited (FR-32).
- Nothing raises: column checks never fail a document, they only clear and note.
- Reading again: `column_checks` runs again on the model's values; `apply_income_line_corrections` and the summary
  correction re-apply drop the label-prefixed notes for corrected values (existing code, no change). Undo restores
  them (stored `resolved_issues_json`).
- Run reuse: the version bump forces a new run for v23 readings (FR-37). No bulk re-reading (D5).

## Privacy/security and migration impact
- No new model call, no network, no new dependency.
- No migration: new keys go into existing JSON columns (`income_lines.details_json`, `income_records.details_json`).
  Existing records are untouched until **Extract again**.
- Gated: it changes how money values are persisted from extraction. It needs plan approval via
  `gate.py approve --stage plan` before SL-01.
- Tests and evals use synthetic lines only. Nothing under `P:\Finances`, `%LOCALAPPDATA%\HomeManager` or
  `P:\EvalCorpus` is touched.

## Vertical slices
Each slice runs only the tests for touched components (memory: targeted test runs), with `.venv/Scripts/python.exe`.

| ID | FR/SC covered | Dependencies | Files/changes | Verification command / evidence |
|---|---|---|---|---|
| SL-01 | FR-31, FR-32, FR-34; SC-28, SC-32, SC-33 | none | `extraction.py`: `line_amounts`; `read()` routes pay stubs on `bool(tables)`, sets `printed_columns`, deletes `has_table_contract`; `anchor_paystub` counts with `line_amounts`; plumbing `record`→`publish`→`normalize`→`paystub_lines` (flag accepted, no check yet). No version bump yet (R1-03). `tests/test_paystub_forms.py`: drop the strict-xfail mark (SC-28) and also assert no "multiple amounts" note; SC-32 a (SIDE_BY_SIDE + `401K 184.98 2,404.74`); SC-32 b (P-table plus a `401(k) \| 184.98 \| 2,404.74` row, kept 18498 from its cell); the anchor counter (R1-06): P-table plus a line `401K 184.98` outside the table, cited by a pay line → kept 18498, no "multiple amounts" note (today: nulled). `tests/test_layout_consumers.py` (P6): an embedded-text PDF stub printing SIDE_BY_SIDE without separators, so no table is rebuilt, answered correctly → values kept, no "multiple amounts" note. It first asserts `evidence_tables(parse result) == []`, so the no-table path is really taken (R2-05). Unit test of `line_amounts`: "401K 184.98 2,404.74" → 2, "403(b) 10.00 20.00" → 2, "SECTION 125 150.00 1,800.00" → 3, "SECTION 125 150.00" → 2, "(50.00)" → 1, "50.00CR" → 0. **Not committed alone:** SL-01 is committed together with SL-02 (R1-03), since alone it removes blanking without its replacement. | `pytest tests/test_paystub_forms.py tests/test_layout_consumers.py -q`; `pytest tests/test_vision_tables.py tests/test_pdf.py tests/test_extraction.py -q` (SC-33); `ruff check` on touched files |
| SL-02 | FR-33, FR-35, FR-36, FR-37; SC-29, SC-30, SC-31, SC-34, SC-35 | SL-01 | `extraction.py`: `printed_header`, `column_checks`, deferred clears in `paystub_lines`, line/summary markers; version v24 (FR-37). `tests/test_paystub_forms.py`: <br>**SC-29:** swapped Regular → null/null, both column notes + FR-22 b note, `needs_review`. Then `correct_income_line(id, 1, {"current": "2500.00", "ytd": "32500.00"})` → column notes gone, other issues unchanged, 250000/3250000. Then `extract(force=True)` keeps the corrections and the notes stay cleared. <br>**SC-30:** HOURS RATE header, 4-amount Regular kept, hours/rate check counted, no column note. <br>**SC-31:** bonus as this period → null, one-amount note, `needs_review`, ytd None. <br>**SC-34 (R1-02):** every this-period = YTD. Regular, Federal, Gross and Net get FR-33 notes for this period and year to date, with both values null. The bonus gets the FR-35 note. FR-22 adds "pay period isn't known" equality notes, not rule (c): SIDE_BY_SIDE prints no frequency. `needs_review`. <br>**Header-ambiguous case:** two header lines in different orders → no column note. **No-header case:** FR-35 silent. <br>**Summary pair case:** gross swapped → gross and gross YTD null, notes starting "Gross pay", and `record["details"]["columns"]` holds both (R2-02). Correcting gross pay alone clears both notes (P8). <br>**Version test (SC-35):** asserts `!= v23` and marks the run `typed-extraction-v23-document-forms`. | `pytest tests/test_paystub_forms.py tests/test_layout_consumers.py tests/test_vision_tables.py tests/test_pdf.py tests/test_extraction.py -q` (SC-33 re-run, R2-04); `pytest tests/test_eval_tasks.py -k document_forms -q`, `tests/test_employers.py tests/test_paycheck.py tests/test_correction_preview.py -q` (pay stub consumers); `ruff check` |
| SL-03 | FR-38; SC-36 | SL-02 | `evals/tasks/document_forms.py`: `P_PHOTO` (= SIDE_BY_SIDE) case tagged `p_photo`, with expected per-value columns, appended **after** the existing first four cases (R1-07). Measurement variants: two blocks on one line; `SECTION 125 150.00 1,800.00` and `SECTION 125 150.00` (P3); each column's amount on its own transcribed line (R2-03: shows how often FR-35 then blanks this period). `run()` passes `printed_columns=True` for `p_photo` cases only. New outputs/grades: `kept`, `blanked`, and `wrong_column_counted`, extended to "a kept value equal to the other column's expected value" on a counted stub. Report gains "Kept / Blanked" columns (shown as "–" without expected columns). `VERSION = "document-forms-v2"`. `tests/test_eval_tasks.py`: the perfect-answer stub (`:65-66`) gains `kept`/`blanked` (R1-07); update the existing report-row strings; new test with stubbed correct answers on `p_photo` → row shows all kept, 0 blanked, 0 wrong column. | `pytest tests/test_eval_tasks.py -q`; `ruff check evals/tasks/document_forms.py` |
| SL-04 | FR-39; SC-37 | SL-02, SL-03 | `docs/money.md` "Money in and paystubs" covers: <br>- what a stub with no validated table keeps (photos, scans, and text PDFs with no rebuilt table): model values kept when cited; <br>- that pipe-separated stubs keep the cell path (R1-09); <br>- the FR-33/FR-35 checks and label digits; <br>- that notes clear on correction, and correcting one side of a gross/net pair clears both its notes (P8); <br>- that old records need Extract again. <br>`text_extraction_plan.md`: dated follow-up note (blanking replaced by FR-22 + column position). `docs/evals.md`: document_forms gains `p_photo` and the kept/blanked columns, and measures the rule, not FR-31's routing (R1-11). Code comments cite `docs/money.md "Money in and paystubs"`. | `git diff --stat docs/ text_extraction_plan.md`; grep that cited headings exist |

## Requirements & scenarios coverage matrix
| ID | Slice | Test / evidence |
|---|---|---|
| FR-31 | SL-01 | SC-28 (no "multiple amounts" note), SC-33 suites, text PDF no-table test (P6) |
| FR-32 | SL-01 | SC-28; SC-34 (FR-22 still judges) in SL-02 |
| FR-33 | SL-02 | SC-29, SC-30, SC-34, summary pair case, header-ambiguous case |
| FR-34 | SL-01 | SC-32 a/b, anchor-counter case, `line_amounts` unit test |
| FR-35 | SL-02 | SC-28 (YTD kept, no note), SC-31, no-header case |
| FR-36 | SL-02 | SC-29 correction + re-read; SC-31/SC-34 `needs_review` |
| FR-37 | SL-02 | SC-35 |
| FR-38 | SL-03 | SC-36 |
| FR-39 | SL-04 | SC-37 |
| SC-28 | SL-01 | former xfail test, passing |
| SC-29 | SL-02 | new test |
| SC-30 | SL-02 | new test |
| SC-31 | SL-02 | new test |
| SC-32 | SL-01 | new tests |
| SC-33 | SL-01 (re-run in SL-02) | existing suites |
| SC-34 | SL-02 | new test |
| SC-35 | SL-02 | version test |
| SC-36 | SL-03 | eval test |
| SC-37 | SL-04 | doc diff |

## Test environments, data, stubs for nondeterministic components, final-state oracle
- **Environment:** pytest with `local_model` (`tests/model_server.py`, replies keyed by schema name via `by_schema`);
  `transcribe` + `extract` give a real vision-shaped parse with empty `vision_tables`, real extraction service, real
  SQLite in `tmp_path`.
- **Data:** synthetic `SIDE_BY_SIDE` and its variants (header with HOURS RATE; 401K line; swapped / this-period bonus /
  all-YTD answers), the document-forms fixtures P-table and P-flat. No live data.
- **Final-state oracle** (independent of the code under test): read back through `manager.ledger.record("income_record",
  id)`, which comes from the DB.
  - Assert `gross_pay_minor`, `net_pay_minor`, each line's `current_minor`/`ytd_minor`, `review_status`, and the
    exact issue list membership (column note prefixes, FR-22 notes).
  - For SC-29, also query `income_lines.details_json` for `current_status`/`ytd_status`, and `record_corrections` for
    the stored `resolved_issues_json` after correction.
- **Unit level:** `line_amounts`, `printed_header` (pure functions) with literal strings.
- **Eval:** stubbed answers only, and no live-model claims. U1 is measured by the user running the eval on their machine.
- **Not tested:** live model behavior; the UI (no UI change; the document page already lists issues and line
  details); the user's own stub (the user re-extracts it themselves).

## Risks, unresolved decisions, alternatives
- **R1 Header vocabulary misses** ("Current Period" splits over two lines, "This Pay" / "Year-To-Date" variants):
  no header is found, so FR-33/FR-35 don't run and FR-22 alone protects. That is less checking, never a wrong value
  counted beyond today's FR-22 behavior. Spec domain risk 2 is deferred until the eval shows it matters.
- **R2 Removing blanking widens what counts automatically** on photos where the model swaps columns on a line FR-33
  can't check (count mismatch, no header). FR-22 b/c still catch a swap whenever this period > YTD or the two are equal.
  The residual risk is a swap between two lines' values, which no rule here catches. The eval's wrong-column count
  measures it.
- **R3 Text PDFs without a rebuilt table** (P6, user's choice) change from blanking to flat reading plus column checks.
  This goes beyond the spec's "images and scanned pages" line. It is pinned by the new test in SL-01, since no
  earlier test covered it. The fallback, if wanted later, is to keep `anchor_paystub` for `native_page(page)` pages.
- **R4 Two notes per swapped line** (P1) means slightly more review text than the spec's one-note wording.
- **R5 Locating a value** fails when the same amount prints on two cited lines (e.g. "2,500.00" in Regular and Gross
  when both are cited). The check is skipped for that value, which fails safe.
- Spec domain risk 5 (a page note for old records) is not built. It would go in `docs/open-work.md` if you want it.
- Alternative rejected: running the column check in `read()` on PayLine models (like `anchor_paystub`). FR-22 would
  then never see the swapped value (SC-29), and the eval, which calls `normalize`, wouldn't measure it.
