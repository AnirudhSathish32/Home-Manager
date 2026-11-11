```yaml
slice: SL-08
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: fc3b0eb
end_head: ffefadb   # the handoff commit follows; see git log
commit: ffefadb
changed_files:
  - src/home_manager/app/static/document_v2.js
  - tests/test_bill_engine_browser.py   # new
  - docs/ui.md
checks:
  - command: "RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_bill_engine_browser.py tests/test_document_v2_browser.py -q"
    exit_code: 0   # 14 passed
  - command: ".venv/bin/python -m pytest tests/test_bill_engine_record.py -k sc110 -q"
    exit_code: 0   # 9 passed, 75 deselected
  - command: "RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_bill_engine_browser.py -q   # rerun after ruff's import sort"
    exit_code: 0   # 4 passed
  - command: ".venv/bin/ruff check tests/test_bill_engine_browser.py"
    exit_code: 0   # after --fix (one I001 import order)
  - command: "stash of document_v2.js, RUN_BROWSER_TESTS=1 pytest tests/test_bill_engine_browser.py -q   # red check"
    exit_code: 1   # the two split panel tests failed without the change, as intended; popped afterwards
escalations: []
```

## What changed
- `doc2Split` (`document_v2.js`), same panel markup and classes as the pay stub panel, no new CSS, no money arithmetic:
  - `bills` = every segment is `kind === "bill"`; noun "bill"; aria-label "Bills in this file"; heading `This file holds N bills`, or
    `This file may hold more than one bill` when `split.one`.
  - No "waits in To check" warning for bills. Chips: `merchant` (fallback `Bill N`) and `dateText(due_date) · display.amount_due`.
  - **Confirm split** hidden when `split.one`; Merge with next was already absent for one segment (`chosen < length - 1`); Split here is unchanged.
  - Chip amount: the server's `display.amount_due` is `81.42 USD`; the chip drops a trailing 3-letter currency code with `replace(/ [A-Z]{3}$/, "")`
    (a lexical trim, as docs/ui.md allows; the orchestrator note from SL-06). A non-USD bill's chip therefore shows no currency; the record below it does.
    Say if you'd rather the chip keep it (the contract's `contain text` assertions would still pass).
  - `doc2Ledger(... published.status === "kept_reviewed" ? published : null)` kept as it was.
- `tests/test_bill_engine_browser.py` (new, opt-in): SC-129 step 2 (BL-MULTI: heading, chips `CITY POWER & WATER` + `Jul 20, 2026 · 81.42` etc., three
  buttons, no "To check"/"receipt"; last bill has no Merge with next), SC-129 step 6 (BL-TWOONPAGE: "may hold more than one bill", Split here offered with
  the second bill's first line among the options, no Confirm split or Merge), SC-110 step 7 (Tier 2 `Unit price: 0.1430`, Tier 1 `0.12 USD`, then a
  `correct_item_fields(.., 2, {"unit_price": "0.15"})` shows `0.15 USD` and not `0.1430`), SC-111 step 3 (four lines, then foot rows Previous balance 82.10,
  Payment received 82.10, Amount due 97.55). Each test watches page errors, CSP violations and any request outside the app (none).
- `docs/ui.md`: a bullet "The split panel for bills" under the document page's description.

## Notes for the orchestrator
- SC-110 step 7's server side is the existing `-k sc110` run (9 passed); nothing there changed.
- SC-129 step 6 asserts the panel offers Split here and its options; it does not click it (the PUT and its result are SC-129 step 6 in `tests/test_bill_split.py`).
- docs/ui.md cites `documents.md` "Several bills in one file", which SL-10 adds (plan SL-10 row); the heading doesn't exist until then.
- Baseline: no failure seen in either command; none of `baseline_failures` was touched. The full suite was not run (the orchestrator does that once).
