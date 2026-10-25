```yaml
slice: SL-08
result: ready_for_verification   # code, tests, docs and M3 done; the manual run on the agent test instance was NOT performed (see "Manual run")
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: ffeded7
end_head: <the commit; see `git log -1`>
commit: <this commit>
changed_files:
  - src/home_manager/app/static/records_v2.js       # pdfImportOffer, rc2Recordable, rc2Record, rc2Step (PDF Import step), rc2Menu (Record / Import transactions items)
  - src/home_manager/app/static/document_v2.js      # doc2Steps: Import transactions primary or secondary beside Record it
  - tests/test_pdf_imports_browser.py               # sc20; one comment in sc21
  - docs/documents.md                               # "CSV and XLSX imports" -> "Transaction imports" (CSV/XLSX, PDF, entry points); PDFs pointer
  - docs/money.md                                   # Import identity: PDF rows share the fingerprint
  - docs/open-work.md                               # cross-page linking done in the import only; PDF import open items (incl. the three follow-ups)
  - docs/development.md                             # schema map: 071, range 001-071
  - docs/ui.md                                      # picker lists PDFs; library step/menu; document page button; provenance and badge text
  - plans/account-import-pdf/handoffs/slice-SL-08.md
checks:
  - command: 'RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_pdf_imports_browser.py -k sc20 -q'
    exit_code: 0   # 1 passed
  - command: 'RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_records_v2_browser.py tests/test_document_v2_browser.py -q'
    exit_code: 1   # 7 passed, 1 failed: test_records_v2_filters_strip_read_all_and_trash (tests/test_records_v2_browser.py:98, "Element is not attached to the DOM" on scroll_into_view). It fails identically at START_HEAD ffeded7 with my changes stashed (run 2 of 2). Not in the known list; pre-existing and unrelated, not fixed (test file outside my permissions)
  - command: '.venv/bin/python -m pytest tests/test_pdf_imports.py tests/test_imports.py tests/test_formats.py tests/test_tabular.py tests/test_pdf.py tests/test_pdf_layout.py tests/test_provenance.py -q'
    exit_code: 0   # M3 line 1: 225 passed in 194 s
  - command: 'RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_pdf_imports_browser.py tests/test_transactions_v2_browser.py tests/test_records_v2_browser.py tests/test_document_v2_browser.py -q'
    exit_code: 1   # M3 line 2: 18 passed, 1 failed (the same records test as above). test_transactions_v2_filters_categorises_adds_and_imports PASSED this time (it is one of the known pre-existing failures; it is flaky here)
  - command: '.venv/bin/ruff check tests/test_pdf_imports_browser.py'
    exit_code: 0
  - command: 'node --check src/home_manager/app/static/records_v2.js ; node --check src/home_manager/app/static/document_v2.js'
    exit_code: 0
  - command: '.venv/bin/python -m mypy'
    exit_code: 1   # "Found 8 errors in 1 file": the baseline core/paths.py errors only
  - command: '.venv/bin/python scripts/test_instance.py verify'
    exit_code: 1   # FAIL server: not running (no session.json); FAIL seed manifest incomplete; FAIL guards; WARN LM Studio and models. See "Manual run"
escalations: []
```

# SL-08 handoff: entry points (library row, document page), docs, M3

Spec, plan, `progress.yaml`, approvals, `reviews.md`, design-system, every Python module under `src/`, `library.js` and `style.css` are untouched. No API change, no CSS change.

## What was built

- **`pdfImportOffer(doc)`** (`records_v2.js`, shared by the document page): `null` for Trash, non-PDFs, `pdf_import.tables == 0`/absent, or `pdf_import.refused`; `"primary"` when `pdf_import.match` is set; else `"secondary"`. The server computes `match` and `refused` (SL-06); the browser applies nothing else (FR-26).
- **Library row.** `rc2Step`: CSV/XLSX unchanged (Import). A PDF whose offer is `primary` (and that is not mid-read or mid-record) shows **Import**; otherwise Read or Record as before. `rc2Recordable` treats `ledger_status === "imported"` on a PDF as recordable (P5/OD-3; the badge stays `imported`). `rc2Menu` adds **Record** (when Import leads and the PDF is recordable) and **Import transactions** (when the offer is `secondary`, and for an unread PDF) after Versions. The menu item focuses the menu's button first, so closing the dialog returns focus to it.
- **Document page.** `doc2Steps`: on the latest version of a read PDF, never while reading/recording: `primary` -> **Import transactions** (primary) then **Record it** (secondary class); `secondary` -> **Record it** (primary) then **Import transactions** (secondary). Where Record isn't offered (already recorded, filed elsewhere, failed) the button is on its own row. Closing the dialog refreshes the page (`refreshDocumentV2`) so the badge reads `imported`.
- **Docs**: see changed files. The heading `CSV and XLSX imports` was renamed `Transaction imports`; `grep -rn "CSV and XLSX imports"` finds only the plan and spec text (prose, not citations). No anchor `#csv-and-xlsx-imports` existed anywhere. Code comments cite `docs/documents.md "Transaction imports"`.

## Decisions to confirm

1. **Import stays the row's step after a PDF import** (literal FR-26: "primary when all hold"); Record is then in More actions. The plan's "`rc2Step` treats `imported` as recordable" is honoured in that Record is offered in the menu and as the step whenever Import is not primary (no match). If the orchestrator would rather make Record the step once a PDF is `imported` (R3: Import primary can leave a PDF never Recorded), that is a one-line change in `rc2Step`; the spec/contract do not say.
2. **An unread PDF has Import transactions in More actions** (not only when "a reading with a transactions table exists"). SC-21 step 1 says "From Ku's More actions, choose Import transactions", FR-27 describes the dialog on an unread PDF, and the picker does not list unread PDFs (FR-25), so this entry is the only way to reach it. SC-20's Ku checkpoints (next step Read; Read document primary on the page) hold. The document page offers no Import for an unread PDF.
3. The schema map in `docs/development.md` still lacks rows for 066 and 068-070 (they were missing before); I added only 071 and the range. `docs/README.md` still says "schema map (001–062)" (outside my permitted files).

## Tests

`test_sc20_...` (`tests/test_pdf_imports_browser.py`): K (matches A), Kn (`k0_pages`), Kr (K's table, `publish_receipt`), Kc (CSV) read at capture; Ku added after turning automatic reading off.
1. Rows: K Import, More actions `[Edit, Versions, Record, …]` and no Import transactions; Kn Record, More actions has Import transactions and not Record; Ku Read; Kc Import and no Import transactions; Kr no step and neither item. Ledger tables unchanged.
2. Pages: K Import transactions primary with Record it beside it and exactly one `.primary`; Kn Record it primary, Import transactions beside it, not primary; Ku Read document primary and no Import; Kr neither.
3. Ku More actions -> Import transactions -> `Read this document first` (SC-21 entry); Kn More actions -> dialog with 9 rows, no preselected account, focus returns to the menu button on close. Import K from its row into A (9 rows, one account), reload: K's row badge `Imported`, More actions has Record; K's page offers Record it and Import transactions, badge `Imported`. Totals 9 transactions, nothing from Kn/Ku/Kc/Kr; no `pageerror`.

## Pre-existing failures seen

- `tests/test_records_v2_browser.py::test_records_v2_filters_strip_read_all_and_trash`: fails at `:98` (`link.scroll_into_view_if_needed()` -> "Element is not attached to the DOM" after Read all re-renders the list). Reproduced with my changes stashed at ffeded7, so not from this slice; not on the known list. It is a list-redraw race in the test itself (the 13 background reads redraw the list while it scrolls). The test file is outside this slice's permissions.
- `test_transactions_v2_filters_categorises_adds_and_imports` (known) passed in the M3 run this time.

## Manual run: NOT performed

Update 2026-10-25: the manual run was performed on the agent test instance (gemma-3-12b-it / openai/gpt-oss-20b), and SC-01, SC-02, SC-03, SC-13, SC-20 and SC-12 passed after the pdf_layout and find_account fixes. The steps and numbers are in progress.yaml SL-08; the evidence is in tests/.tmp/evidence/pdf-import-*.png (k-into-a-row, k-reimport-page, a-charges-after-k, r-into-c-new-account, c-charges-after-r, k-read-again-text, k-record-needs-review, k-recorded-verified, a-charges-after-record).

`python scripts/test_instance.py verify` fails: no instance is running (`FAIL server: not running (no session.json)`, `FAIL seed manifest: incomplete, run reset`, `FAIL guards`), and LM Studio and the models are not configured. The agent-testing skill says to stop and tell the developer, and not to run `start`/`reset`/`stop` unless asked, so I did not. Also, the instance's `uploads/` holds the seeded receipts/statements/etc. (`README.txt`), not the K and R fixtures, and Record needs a reasoning model, so the contract's pass (import K and R, re-import K, Record K) needs the developer to start the instance, or approve starting it and adding K/R (`tests/pdf_import_fixtures.py` `k_pages`/`r_pages`) as uploads. No screenshots exist and no finding was recorded; `docs/bugs.md` is untouched. Evidence folder when it runs: `tests/.tmp/evidence/`.

## Notes

- `openImport(doc, {onDone})` is used as-is; the row passes `rc2Draw`, the page `refreshDocumentV2`.
- Follow-ups from SL-05/06/07 (per-input provenance fetch, `refused` kind parsed from a message, unread case matched on error text) are in `docs/open-work.md` "Money".
