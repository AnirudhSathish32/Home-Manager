```yaml
slice: SL-04
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 4e9b933
end_head: <the commit; see `git log -1`>
commit: <this commit>
changed_files:
  - src/home_manager/finance/ledger.py      # new_account path (import + preview), pdf_state(account=), replacing_manual, "replaces a manual entry" label
  - src/home_manager/finance/reconcile.py   # module-level manual_candidates(db, manual, extra=()); replace_manual uses it
  - src/home_manager/library/storage.py     # WORK_FILTERS["ready_for_ledger"] per P5
  - src/home_manager/app/api.py             # ImportInput.new_account, pdf_choices(), import route accepts new_account
  - tests/test_pdf_imports.py               # opened() harness, J1 complete (+J1-a), SC-06, SC-10 (10-a, 10-b), SC-11, SC-26, P6
  - plans/account-import-pdf/handoffs/slice-SL-04.md
checks:
  - command: ".venv/bin/python -m pytest tests/test_pdf_imports.py -k \"journey_j1 or sc06 or sc10 or sc11 or sc26\" tests/test_imports.py tests/test_formats.py tests/test_tabular.py tests/test_library.py tests/test_finance.py tests/test_reconcile_tools.py -q"
    exit_code: 0   # 13 passed, 186 deselected. NOTE: -k applies to every path on the command line, so the other six files are deselected by it (see below)
  - command: ".venv/bin/python -m pytest tests/test_imports.py tests/test_formats.py tests/test_tabular.py tests/test_library.py tests/test_finance.py tests/test_reconcile_tools.py -q"
    exit_code: 0   # 72 passed: the same files without -k
  - command: ".venv/bin/python -m pytest tests/test_pdf_imports.py tests/test_imports.py tests/test_formats.py tests/test_tabular.py tests/test_pdf.py tests/test_pdf_layout.py -q"
    exit_code: 0   # M1 milestone check: 196 passed
  - command: ".venv/bin/python -m pytest tests/test_migrations.py tests/test_health.py tests/test_investment_confirmations.py tests/test_provenance.py tests/test_reconcile_tools.py tests/test_finance.py tests/test_investments.py tests/test_organization.py tests/test_backend_dependencies.py tests/test_investment_contributions.py tests/test_extraction.py tests/test_forecast.py tests/test_planned_bugfixes.py tests/test_tax_year.py tests/test_managed_library.py -q"
    exit_code: 0   # extra sweep over files that mention manual entries or ready_for_ledger: 208 passed, 2 failed (test_tax_year x2, fail identically at START_HEAD); tests/test_agent_guards.py (3 failures, socket bind in this sandbox) also fails at START_HEAD
  - command: ".venv/bin/ruff check src/home_manager/finance/ledger.py src/home_manager/finance/reconcile.py src/home_manager/library/storage.py src/home_manager/app/api.py src/home_manager/app/manager.py tests/test_pdf_imports.py tests/pdf_import_fixtures.py"
    exit_code: 0
  - command: ".venv/bin/python -m mypy"
    exit_code: 1   # 8 errors, all in core/paths.py, identical to START_HEAD
escalations: []
```

# SL-04 handoff: new account in the import's transaction, manual-entry label, ready_for_ledger, J1 complete

Spec, plan, `progress.yaml`, approvals, `reviews.md`, `pdf_import.py`, `manager.py`, fixtures and the CSV/XLSX paths are untouched. No migration. M1 (backend) is complete.

## Interfaces as built

- `reconcile.manual_candidates(db, manual, extra=())` (module level in `finance/reconcile.py`, after `shift`): the countable, non-manual lines of the manual entry's account, currency and amount, posted within +/-`RECEIPT_POSTING_DAYS`, not already someone's `replaced_by` (the SQL that `replace_manual` had inline). `extra` is a list of dicts `{posted_date, amount_minor, currency, ...}` for lines that don't exist yet; the ones that match are returned after the stored rows (sqlite rows first, then the dicts). `replace_manual` calls it with no `extra`: same SQL, same behavior (`tests/test_reconcile_tools.py` and the rest pass unchanged).
- `Ledger.replacing_manual(db, account, lines) -> set[key]`: for each un-replaced, non-rejected manual entry in the account it calls `manual_candidates(db, manual, lines)` (`lines` = `[{key, posted_date, amount_minor, currency}]` of the ticked New rows); the key is returned only when that entry has exactly one candidate and it is an extra. Local import of `.reconcile` (circular otherwise).
- `preview_pdf_import(..., new_account=None, ...)`: the row's `labels` gain `"replaces a manual entry"` for the keys above (status stays `new`, `status_text` stays `New`). `new_account` (dict, same fields as `AccountInput`) with no `account_id`: an existing account found by `find_account` (and with the same currency) is the account in force, so statuses are those of the real rows (P6); otherwise its `account_type` and `currency` stand in for the typed ones (explicit `account_type`/`currency` in the request win). Nothing is created.
- `pdf_state(..., account=None)`: the account row itself, used by the import after it creates the account in its own connection (`self.account(id)` opens another connection that cannot see it).
- `import_pdf_transactions(..., account_id=None, new_account=None, ...)`: neither -> `Choose the account these transactions belong to.`; both -> `Choose an existing account or a new one, not both.` (400). In the single `store.connection()` the first step is `account_in(db, institution, account_type, currency, display_name, last_four)` (find or create; a different currency for an identical account -> `This account already exists with a different currency.`), then `pdf_state(account=...)`, the inserts and the `transaction_imports` row. Any exception (blocked, required, nothing to import, a SQLite fault) rolls the account back with the rest. The response is unchanged (it names the account through `account_id` and `account_name`).
- `ImportInput.new_account: AccountInput | None` (strict, so a 6-digit last four is a 422 as for the account route). `pdf_choices()` carries it as `new_account = model_dump()`, so the manager and ledger pass it through the existing `pdf` dict: **`manager.py` needed no change**. The import route's 400 is now raised only when both `account_id` and `new_account` are absent. A CSV/XLSX request with `new_account` gets the existing `PDF_ONLY` 400.
- `WORK_FILTERS["ready_for_ledger"]` (P5), wrapped in outer parentheses because both users join it with `AND`: `(TABLE_FILE AND ledger_status IS NULL) OR (NOT TABLE_FILE AND text_run_id IS NOT NULL AND (ledger_status IS NULL OR ledger_status='imported'))`.
- Duplicate messages: already complete from SL-03 (`Already recorded from import <file>`, `... from statement <file>`, `... from this statement`, `; not counted until you reconcile it.`). SL-04 only proves them (SC-10, SC-11, J1 5/7).

## Tests (all in `tests/test_pdf_imports.py`)

- Harness: `opened(tmp_path, configure=True)` context manager (a second `with opened(tmp_path, configure=False)` is a restart of the Manager on the same folders); the `env` fixture uses it.
- `test_sc01_journey_j1_import_restart_import_again_reject_other_account_record_later`: one test, replaces SL-03's steps-1-to-4 test with the same step 1-4 assertions, then the restart (J1-a) right after step 4 (rows, links, import record and files compare equal), then steps 5-10 on the new Manager, final state read from SQLite. Step 6 is therefore the "repeat step 6 after restart". Step 9 (Record) uses the allowed fallback `publish_statement(S-K, ..., "proposed")` (docstring says so).
- SC-06 (steps 1-4 with the permanent `BEFORE INSERT` trigger on `RETURN BOOKSTORE`, dropped in `finally`), 6-a, refusal cases (neither/both/CSV/different currency), P6 reuse (import and preview), typed new account's sign default and totals.
- SC-10 (Kc then K, snapshot of the 9 rows before/after, 9 new evidence links on K's blob, Spending unchanged), 10-a (label, import, manual `rejected` with `replaced_by` = k3, k3 counted, Spending 45.10 once), 10-b (two equal rows: no label, no replacement, manual still counts), a variant where two stored lines already match (no label, no replacement), and a direct test of `manual_candidates` with `extra`.
- SC-11 (Record first with the fallback double, preview text, import 0/9, rows unchanged and still `HELD`).
- SC-26 steps 2-3 (`TABLES`, ready/needs_text filters before and after a CSV import, after a PDF import, after Record) plus the CSV import through the same route; step 1 is the three suites, run unchanged (72 passed with test_library, test_finance, test_reconcile_tools).

## Deviations and notes (please confirm)

1. **`new_account` also accepted by the preview** (additive; the plan's signature lists it for the preview while the prose says the preview takes `account_type` and `currency`). Both work. It is what lets the dialog send the same body to preview and import, and what makes a reused account (P6) preview with the right statuses.
2. **The `replaces a manual entry` label is a row `label`**, not a status text; contract SC-10-a says "New and labelled", and `status`/`status_text` stay `new`/`New`.
3. **Spending oracle (J1 5/7, SC-10):** "includes the 6 outflows" in the contract is loose: k5 is a transfer and k9 interest. The tests assert the Spending view's net spending by hand: `12139` = purchases 450+450+4510+8240, fee 500, less interest 12, less refund 1999 (refunds `1999`); without k8 `3899`. They read it through `FinanceTools.get_spending`.
4. **Step 7's `duplicate_sources`** is `{"Already recorded from import K.pdf": 8, "rejected earlier": 1}` (SL-03's design counts the rejected row as a duplicate), `duplicates 9`, `rejected_earlier 1`, as the plan's J1 step 7 line says.
5. **SC-11 step 3 (the page offers Record and Import)** is UI (rc2Step, SC-20 / SL-08) and is not asserted here.
6. **Verification command:** `-k` filters across all the paths given, so the command as written runs 13 tests and deselects `test_imports`, `test_formats`, `test_tabular`, `test_library`, `test_finance`, `test_reconcile_tools`. I ran those six files separately (72 passed) and recorded both.
7. After a restart, a capture-free Inbox overwrite (J1 step 1) did not produce a new version (asserted after the restart).
8. Pre-existing failures unrelated to this slice: `tests/test_agent_guards.py` (socket bind in this sandbox) and two in `tests/test_tax_year.py`; both fail identically at START_HEAD.

## Notes for SL-05 and later

- Evidence locators are as built in SL-03; J1 asserts them for K (`word_ids`, `line_ids`, `continued_from` on pages 2 and 3). SL-05 (provenance) can build on `env.sql("SELECT locator_json ...")`.
- `ready_for_ledger` for SL-06: the candidates endpoint should keep a PDF with an import in its list (P5); the filter above is the one source.
- `import_pdf_transactions` still returns no flag for "account created". Add one in SL-07 if the dialog's summary needs it (the account's name is already returned).
