# Handoff: slice SL-05 — budgets project a rent bill's recurring bill by line

```yaml
result: done
start_head: f3c3a00dbd572bfe84ec1ab2c41213fcd9d1df2e
end_head: f666829e61fcc1617af1fe13072d3a2fc9085b1e
commit: f666829e61fcc1617af1fe13072d3a2fc9085b1e
verification_command: python -m pytest tests/test_bill_kinds.py -k "sc43a or sc46c" -q; python -m pytest tests/test_budgets.py tests/test_recurring_bills.py -q
verification_result: passed
log: plans/bill-kinds/logs/slice-SL-05.log
escalations: 0
```

## What was built
FR-45a lives in `finance/tools.py`. `FinanceTools._bill_parts(bill)` returns `[(category, minor, splitting receipt id | None)]`. A split happens only when `source_receipt_id` is a bill with `bill_kind='rent'`. The split uses the latest verified rent bill for the same merchant and currency, ordered by `due_date DESC, id DESC`. Its utilities part is min(expected, that bill's non-rejected lines in `utilities`), and the rest goes to `category or "housing"`. Zero parts are dropped. Any other bill projects whole, as before. `get_budgets` adds each part to its key. The `budget.projected` trace has one step per part, `"{merchant} · due {date} · {category} part"`, with no drill-down. Its inputs are `recurring:{id}` (the whole expected amount, `bill.expected`) and `receipt:{id}` (the part, `light("receipt", …, kind="computed")`).

Tests (`tests/test_bill_kinds.py`):
- `sc43a`: proposal (monthly, 148842, 2026-11-01, source the bill), then confirm through `POST /api/finance/recurring/{id}/review`. November gives housing 145000, utilities 3842, and a `bills` budget at 0. Trace steps and inputs are checked over `/api/traces`, and the final state is checked.
- `sc43a_2`: the Water category is corrected through the existing `PUT /api/receipts/{id}/items/{pos}/category`, giving housing 148842 and utilities 0.
- `sc43a_1`: a PHONE bill projects whole.
- A recurring bill from a bank payment stays whole.
- `sc46c_2` projection: 145000 / 3842.

Three of the new tests fail on HEAD without the tools.py change. 43a-1 and the bank-payment test pass either way, as regressions should. Git state after: clean except the existing `M progress.yaml` and this handoff.

## Decisions and deviations
- **43a-2 is done in this slice, using only the category correction.** FR-45a says categories decide. The line-type PATCH (SL-06) doesn't affect the split, so this test doesn't wait for SL-06.
- **The bank-payment test sets its origin with SQL.** It runs `UPDATE recurring_obligations SET source_receipt_id=NULL, confidence_source='category_single_payment'`. A payee gets one recurring bill, and the receipt loop proposes first, so the real path can't produce this case once a rent bill exists.
- **Utilities are floored at 0.** This is in addition to the plan's min(expected, …), so credits in `utilities` can't push the rest above expected.
- The code cites `specs/bill-kinds FR-45a`. Doc headings come in SL-08.

## Open issues / escalations
- None.
- Handoff template at `$HOME/.agent-harness/templates` is unreadable (outside the allowed directories); this follows SL-04's format.
- ruff clean on the touched files; mypy on tools.py: no issues. Also ran: `tests/test_traces.py` (10 passed) and the whole of `tests/test_bill_kinds.py` (76 passed).
