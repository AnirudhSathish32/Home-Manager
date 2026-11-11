```yaml
slice: SL-08-fix
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 39fd824
end_head: 5d91932   # the code commit; the handoff itself is committed on top of it
commit: 5d91932
checks:
  - command: "RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_bill_engine_browser.py tests/test_document_v2_browser.py -q"
    exit_code: 0   # 14 passed
escalations: []
```

The bill chip in `doc2Split` (`document_v2.js`) now shows `segment.display?.amount_due` exactly as the server sends it
(for example `81.42 USD`); the currency-stripping regex and its comment are gone.

- `tests/test_bill_engine_browser.py`: the two exact chip-text assertions now expect `<due> · <amount> USD`. The contract
  values (81.42, 87.26, 111.98) are unchanged; only the server's currency code is added to the expected text.
- `docs/ui.md` "The split panel for bills" bullet: now says the amount is shown as sent, with its currency code.

Open issues: none.
