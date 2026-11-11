```yaml
slice: SL-06
result: ready_for_verification
provider: claude            # route provider instance: claudeAgent
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: c838537
end_head: 2416759
commit: [5f1628d, 891214a, 1c9c199, aade38d, 5ec1057, 2416759]  # 5f1628d source; 891214a, 1c9c199, aade38d tests; 5ec1057 drops an unused helper; 2416759 the filing fix (extraction.py, tests/test_bill_split.py). The handoff file is committed after 2416759 (its commit is not in this list).
checks:
  - command: ".venv/bin/python -m pytest tests/test_bill_split.py -k \"not sc131\" -q"
    exit_code: 0   # 51 passed, 0 xfailed (the filing test is a plain test now)
  - command: ".venv/bin/python -m pytest tests/test_paystub_split.py tests/test_receipt_segments.py tests/test_library.py tests/test_managed_library.py tests/test_extraction.py -q"
    exit_code: 0   # 90 passed
  - command: ".venv/bin/python -m pytest tests/test_bill_engine_record.py tests/test_bill_corrections.py -q"
    exit_code: 0   # 92 passed
  - command: ".venv/bin/python -m pytest tests/test_bill_kinds.py tests/test_bills_ledger.py tests/test_recurring_bills.py tests/test_layout_consumers.py tests/test_paystub_engine_record.py tests/test_paystub_cleanup.py tests/test_invoice_ingestion.py tests/test_receipt_kinds.py tests/test_bill_engine.py -q"
    exit_code: 0   # 504 passed, 1 skipped (opt-in browser test)
  - command: ".venv/bin/ruff check src/home_manager/documents/extraction.py tests/test_bill_split.py"
    exit_code: 0
escalations: []   # the earlier filing-date escalation is resolved by 2416759; one-bill and other-kind filing are unchanged
```

# SL-06: several bills in one file (plan P8.1 - P8.7)

No failing test hit `baseline_failures`. No private data touched; synthetic fixtures only. No migration.

## Changed files
- `documents/bill_split.py` (new): `key_of(line)` (key line: label directly followed by its value, ` | ` separators removed; account = last four of the first word with 4+ digits whose first word holds a digit, so `Account Balance 100.00` is no key), `bill_parts(lines) -> BillSplit(parts, reasons)`, `reason_of`, `offers_split`. Walk by page (`page-N-` in line ids; no page = page 1, never split), first value per key compared with the open bill's, first differing key in due/statement/account order starts the bill (G5); (a) one reason per page; (b) parts without an amount-due anchor (`anchor_kind`, never a late line) join the previous, the first joins the next; (c) new-charges anchors differing on pages with no differing key. Labels come from `charge_tables.KEY_LABELS` (SL-01 put them there).
- `documents/extraction.py` (fix: `filing_identity`, `first_bill_identity`): `BILL_SPLIT_NOTE/FAILED/CHANGED`, `MAX_BILLS`; `ExtractionService.bill_parts` (user split first, rule second, exception or >200 parts = one bill + reason (d), `log_failure` without text); `run` (per-part classification for bills, noun "bill"; invoice in any part = whole file read again as one on today's path with the D16 note; reasons attached only when the split isn't confirmed; `split_changed` note + guess on a user-changed split; the one-bill `segments` offer with `"one": true` for (a), (c), (d), no row saved); `record` (bills carry `BILL_SPLIT_NOTE` as a record note, not `SPLIT_NOTE`); `split()` (bill rows: `kind: "bill"`, `merchant`, `due_date`, `display.amount_due`; `one_bill` when no segment rows); `confirm_split` (drops FR-129 reasons and the bill note, re-judges).
- `finance/ledger.py`: `retire_segments` words its note "bill" for bill rows.
- `library/storage.py`: `ORDER BY r.segment` before `LIMIT 1` on the four bill subqueries. (SQLite already walks the unique (blob_hash, segment) index, so the test can't discriminate; it only locks the behaviour.)
- `tests/test_bill_split.py` (new, 51 tests, plus the filing tests above): SC-126 (unit tests on key lines, BL-MULTI/REMIT/ACCT/UTIL, scanned MULTI-SCAN, three combined PNGs, single photographed bill, 201 parts), SC-127 (JOIN, TWOONPAGE, NOKEY, rule fault, 201-part double, confirm), SC-128 (steps 1 - 8 and the library), SC-129 steps 1, 3 - 6 through the real API, SC-130, SC-115 (b), SC-121 (3), SC-122 BL-MULTI, and the retry, duplicate-capture, restart and concurrent variants. The scanned and combined-image MINI-BILL versions are built here (`started_scan`, `combined_images`).

## Decisions and gaps for the reviewer
- **Filing date (fixed in 2416759, orchestrator decision).** `ExtractionService.filing_identity` now takes, for a bill whose run recorded more than one segment, the provider and date of the first non-rejected bill by segment (`first_bill_identity`: `receipts.purchase_date`, which a bill keeps as `coalesce(due_date, issue_date)`, so it falls back to the issue date when no due date is printed). BL-MULTI is filed `Bills/2026/07/2026-07-20__CITY_POWER_WATER…`. A one-bill file and every other kind go through the unchanged path (`IDENTITY['bill']` = issue_date: MINI-BILL(1) alone is still `2026-07-02`), asserted by `test_fr120_a_file_of_one_bill_is_filed_under_its_statement_date_as_before`. If every bill of the file is rejected the run's own identity is used.
- **Filing when bill 1 is rejected.** Filing is never renamed by a review decision for any kind: it is refreshed only when the file is extracted or filed again (`file_extraction`, which also runs on a reused extraction). So rejecting bill 1 leaves the file where it was; the next Extract / file pass refiles it under the first non-rejected bill (bill 2, `Bills/2026/08/2026-08-20__CITY_POWER_WATER…`). Kept as is, and locked by `test_fr135_filing_follows_the_first_non_rejected_bill_whenever_the_file_is_filed_again`. The library row's `document_date`/`due_date` follow the decision at once (SQL, unchanged).
- **First part joins the next** (SC-126 step 7): reason (b) is worded "…read with the bill after it" because "before it" would be false. Parts with no key at all name no key: "Page N prints no amount due, so …". The contract words only the usual case.
- **Fallback to one document** (a part isn't a bill, or reads as an invoice): the rule's reasons are dropped; the user's saved split is deleted by `save_segments`, as the pay stub path already does.
- **Invoice check** runs after every part is read (as P7.9 reads), so a multi-invoice file costs the extra model calls; the stubs for it ask each invoice part's summary twice (D5).
- **Account key** requires the first word after the label to hold a digit (same as `charge_tables.key_kind`); `Account no. xxxx 3456` is therefore no key, `Account no. ****3456` is.
- `display.amount_due` is `format_minor` ("81.42 USD"); SC-129 step 2 shows chips as `81.42`, so SL-08 must trim the currency in `doc2Split`.
- Offer of Split here is for (a), (c), (d) only, as FR-131 says, not for (b) joined down to one part.
- SC-122's BL-MULTI test compares the rows `test_bill_engine_record.snapshot` reads, the engine reading and the split rule's output across two runs.
- `plans/.../progress.yaml` shows as modified in the checkout; that was not me, and it is not staged.
