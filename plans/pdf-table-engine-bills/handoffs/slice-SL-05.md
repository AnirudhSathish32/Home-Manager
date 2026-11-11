```yaml
slice: SL-05
result: ready_for_verification
provider: claude            # route provider instance: claudeAgent
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: c456e92
end_head: 20a954f
commit: [daa5e69, 20a954f]  # daa5e69 source (finance/ledger.py), 20a954f tests (tests/test_bill_corrections.py). This handoff file is left uncommitted for the orchestrator.
checks:
  - command: ".venv/bin/python -m pytest tests/test_bill_corrections.py -q"
    exit_code: 0   # 8 passed
  - command: ".venv/bin/python -m pytest tests/test_bill_kinds.py tests/test_bills_ledger.py tests/test_receipt_item_table.py tests/test_receipt_kinds.py tests/test_receipt_segments.py tests/test_planned_bugfixes.py tests/test_family_ledger.py -q"
    exit_code: 0   # 244 passed, 1 skipped (opt-in browser test); also run once before the tests were committed, same result
  - command: ".venv/bin/python -m pytest tests/test_bill_engine_record.py -q"
    exit_code: 0   # 84 passed
  - command: ".venv/bin/python -m ruff check src/home_manager/finance/ledger.py tests/test_bill_corrections.py"
    exit_code: 0
escalations: []   # none needed; the open points below are gaps the contract does not reach, none changes a contract value or a receipt
```

# SL-05: line corrections after a reading again (plan P9, FR-119)

No command failed, so nothing in `baseline_failures` was hit. No private data touched. Receipts' behaviour is unchanged (second command and the receipt variant test).

## Changed files
`daa5e69`: `src/home_manager/finance/ledger.py` only (+168 / -9).
- **Storage (no migration).** A reserved top-level key `line_corrections` in `receipts.details_json` (constant `LINE_CORRECTIONS`): `{"amounts": {"<correction id>": minor}, "held": ["<id>"], "undone": ["<undo row id>"]}`. `line_state` / `save_line_state` read and write it (the key is dropped when empty; `details_json` stays NULL if it was NULL and nothing is stored). `merged_details` already kept it; it now also keeps it for a reading with no kind (a bill without `bill_kind`) instead of returning NULL.
- **When a correction is made** (`remember_line_amount`, called right after the `record_corrections` insert in `_correct_item`, `_correct_item_field`, `correct_line`, and the inline undo row of a line field in `undo_corrections`; before the line changes): on a `document_kind='bill'` row it stores the line's amount as read before any price correction of yours. That is the remembered amount of the position's latest earlier `price:<n>` when that one is applied (not held, not undone), else the row's current `line_total_minor`. A price correction made before this change and still applied uses the start of its price chain. The same `<field>:<position>` made again drops its held id and its reason from `validation_json`. Receipts keep nothing.
- **When a bill is read again** (`publish_receipt` snapshots `{position: line_total_minor}` for bills before `_replace_items` and passes it to `apply_corrections(..., stored)`; `guard_line_corrections` runs first): each latest `receipt_item` correction is found its remembered amount `Y` (from `amounts`, else G4's price-chain start, else the snapshot; the result is persisted so later readings agree, FR-122). `X` is the amount the line now at the position prints. It is applied when `X == Y`, or for a price when `X` equals your corrected price. Otherwise it is held: skipped, id in `held`, reason appended to `validation_json` (`Your change to line N (L) wasn't applied: that line now prints X, not Y. Check the bill's lines and make the change again on the right line.`, L being `person: blair`, `type: …`, `price: 8.51`, `name:`, `code:`, `quantity:`, `unit price:`; X, Y plain decimals), `review_status='needs_review'`, `review_source=NULL`. `held` is recomputed each reading, so a correction that fits again is applied and its reason goes. `line_type` on a bill not read as rent is neither applied nor held (as before it was skipped).
- **Undo of a held correction** (`undo_held_line`, called first in the `receipt_item` branch of `undo_corrections`; review pass 1, M4): writes the undo row as today (value = previous, previous = value, "Undid a change"), adds its id to `undone`, removes the held id and the reason, touches no `receipt_items` row. `apply_corrections` skips a latest correction whose id is in `undone` on every later reading.
- Decided bills are never written (`_upsert`), so nothing is held on them; receipts pass `stored=None` and re-apply by position exactly as before.

`20a954f`: `tests/test_bill_corrections.py`, 8 tests (they use `BillRun`, `started`, `expect_util`, `finished`, `model_rows`, `lines_of` from `tests/test_bill_engine_record.py`; the v39 seeding follows SC-121's):
- SC-119 Journey A steps 1 – 6 in one ordered test (rows unchanged, remembered amounts 3500 and 815, EXP-PHONE lines, Basic Plan the same item id with member Blair by identity, Device Payment member null with holder `Alex 555-201-1111`, exactly the two reasons naming 24.99/35.00 and 35.00/8.15, History, the unchanged re-read, then the replacing corrections and both applied).
- Journey A, then undo of the held `price:3` (Basic Plan stays 3500, reason gone, History lists the undo, two further Extract agains change nothing).
- Variant "made before this change" (rows inserted by SQL, no remembered amount; same outcomes, amounts then persisted and stable on the next reading).
- Variant "decided bill" (`receipts` and `receipt_items` byte-identical, nothing held).
- Journey B (BL-UTIL): EXP-UTIL, line 4 is 553, member Alex on line 3, no reason, C-auto.
- Journey C (photographed RENT, Pet Fee inserted, reason `line 2`/25.00/38.42, then the original transcription applies it again).
- Variant "receipts unchanged" (a receipt's `price:2` still lands on position 2 with a line added above, no reason, `details_json` NULL).
- G4 unit test (ledger level: a price chain 5.35 → 5.53 then a member, no remembered amount; the new reading prints 5.53: the price applies, the member is held with 5.53/5.35).
I checked the tests bite: with the fit test forced true, the five that expect a hold fail and the three that expect none still pass.

## Gaps the plan and contract do not reach (decided here; please look)
1. **A correction whose position has no line now.** Held with `…wasn't applied: the bill no longer has a line N; it printed Y.` (instead of "now prints X, not Y"). No contract value covers it.
2. **A missing amount** (`line_total_minor` NULL on either side) is shown as `no amount` in the reason.
3. **Label for a cleared value:** `person: nobody` for a member set to none, `type: none` for a cleared type.
4. **G4 as written:** a `member`/`line_kind`/etc. made on a line whose price you had also corrected is compared with the amount before the price correction (the plan's chain start), so if the new reading prints the corrected price rather than the misread one, that other correction is held while the price correction applies. This is G4's literal wording and the G4 test pins it; it is stricter than "same amount as stored", which is the conservative direction for a financial correction.
5. **`delete_item`** removes a position's correction rows but not a held id, remembered amount or reason for them; a dangling held id is replaced at the next reading, but its reason stays in `validation_json` until then. Not handled (out of the SL-05 row); worth a line in open work or SL-06/07 if wanted.
6. A bill with no `bill_kind` (read before bill kinds, or sent by a family) that holds a correction now has `details_json` `{"line_corrections": …}` (not NULL); `current_details` ignores it.

## Notes for later slices
- `apply_corrections(db, record_type, record_id, stored=None)` has a new optional parameter. SL-06's split publishes each bill through `publish_receipt` unchanged, so the guard applies per bill segment with no further change (the snapshot and key are per `receipts` row).
- Docs (`docs/money.md` "Reading a statement or receipt again", FR-126) are not in this slice's row and were not edited.
- No existing test changed its expected value; no bill test's seeded line correction held.

## Checks not run
Browser tests and the full suite (the orchestrator's). Only the targeted sets above.
