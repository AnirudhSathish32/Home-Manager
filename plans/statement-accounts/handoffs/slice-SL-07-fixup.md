```yaml
slice: SL-07-fixup
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 820dd6e
end_head: <see commit>
commit: <filled after commit>
changed_files:
  - tests/seed_documents.py
  - tests/test_statement_accounts_browser.py
checks:
  - command: "RUN_BROWSER_TESTS=1 pytest tests/test_review_v2_browser.py tests/test_search_v2_browser.py tests/test_statement_accounts_browser.py tests/test_document_v2_browser.py tests/test_accounts_v2_browser.py tests/test_today_v2_browser.py"
    exit_code: 0   # 27 passed
  - command: "RUN_BROWSER_TESTS=1 pytest tests/test_statement_accounts_browser.py   # x5 shell loop"
    exit_code: 0   # 10 passed each time
  - command: "sc25 alone x10 under 16 busy-loop processes on 8 cores"
    exit_code: 0   # 10/10 (before the fix: 1 failure in 6 under the same load)
  - command: "RUN_BROWSER_TESTS=1 pytest tests/test_bill_kinds_browser.py tests/test_record_components_browser.py tests/test_planned_bugfixes_browser.py tests/test_records_v2_browser.py"
    exit_code: 1   # 7 passed, 1 failed = test_records_v2_filters_strip_read_all_and_trash (known pre-existing)
  - command: "pytest tests/test_bills_ledger.py tests/test_agent_instance.py tests/test_statement_accounts.py"
    exit_code: 1   # test_agent_instance: 7 failed + 20 errors, identical with my changes stashed (socket.SO_EXCLUSIVEADDRUSE is Windows-only); the rest 58 passed
  - command: "ruff check src tests"
    exit_code: 0
escalations: []
```

## Root causes

1. **test_to_check_decides_each_kind_with_its_source_in_view** — as suspected. FR-04: the seeded statement's account is new, so Record leaves the
   statement `proposed` and its account waiting. The proposed statement sorts first in "Records to verify", ahead of the needs-review receipt.
2. **test_ask_is_a_column_beside_the_page** — verified, not assumed. The test opens `#/accounts` and clicks the first `.figure-button`. Those are
   in account cards, and the Accounts page lists only confirmed accounts (`CONFIRMED`, ledger.py). With the seed stashed, the test timed out
   waiting for `.figure-button`; with the statement confirmed it passes.
3. **test_sc25_delete_from_waiting_for_confirm_by_keyboard** — a race in the test, not a UI bug. On load the app shows its route twice
   (shell.js:119 `showRoute(false)`, then app.js:275 after `loadSettings().then(refresh)`); the Accounts screen therefore fetches
   `/api/finance/accounts/waiting` twice and the second draw `replaceChildren`s the groups, including the "Waiting for confirm" `<details>`.
   `press_enter_on` is `locator.focus()` then `keyboard.press("Enter")`, two round trips; when the second draw lands between them, focus is
   lost, Enter does nothing, the details stays closed and "Delete …" is never found (the observed failure, "element(s) not found"). I counted
   the two waiting requests in a probe, then reproduced the failure by loading the CPU (1 of 6 runs; also once in an unloaded probe run).
   The dialog's own preview/focus/per-open counter logic was not involved.

## Fixes

- `tests/seed_documents.py` `seed_statement(manager, model, confirmed=True)`: after Record it Confirms the statement through
  `manager.ledger.review("statement", record_id, "verified")`, the call SL-05 used in `read_september` and `gift_card_library`. Every consumer
  of the seed (document_server, seed_household, ui_shots) sees the pre-feature state again. `confirmed=False` leaves it proposed with its account
  waiting, for a future caller; nothing in the repo uses it today.
- `tests/test_statement_accounts_browser.py` `open_page`: `page.wait_for_load_state("networkidle")` after navigating, so the second draw is
  done before the test acts. No sleeps. Applies to all nine tests in the file.

## Changed assertions / seed behaviour

- Seed behaviour: the seeded statement is now `verified` with its account confirmed (as before FR-04). No test assertion changed.
- No test that needs a waiting or proposed statement uses `seed_statement`: test_statement_accounts_browser.py builds its own (`record_s`), and
  test_document_v2_browser.py's statement states passed against the confirmed seed. No application code changed; no real bug found.

## Not run

- `test_agent_instance.py` cannot run on Linux (Windows-only socket option), so seed_household's use of the seed through it is unverified here;
  it calls the same `seed_statement`. The browser-test consumers of `document_server` all pass (except the known pre-existing failure).
