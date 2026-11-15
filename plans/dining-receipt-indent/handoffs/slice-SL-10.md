```yaml
slice: SL-10
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: ce84cb6
end_head: f9303e5   # the last code commit; the handoff itself is committed on top of it
commit: f9303e5     # code commits: a150f9c (findings 1, 2), 9037ef3 (finding 3), 38d7d78 (finding 4), f9303e5 (import order)
checks:
  - command: "cd Home-Manager-dining-fix1 && python -m pytest -q -p no:cacheprovider tests/test_dining_receipts.py tests/test_receipt_side_lines.py tests/test_reread_links.py tests/test_vision_indent.py"
    exit_code: 0     # 188 passed (5m07s)
  - command: "pytest -q -p no:cacheprovider tests/test_family_routing.py tests/test_family_inbox.py tests/test_bills_ledger.py tests/test_bill_kinds.py tests/test_returns.py tests/test_statement_accounts.py   (run after finding 1)"
    exit_code: 0     # 158 passed, 1 skipped (opt-in browser)
  - command: "pytest -q -p no:cacheprovider tests/test_extraction.py tests/test_receipt_kinds.py tests/test_family_routing.py tests/test_family_inbox.py tests/test_record_history.py tests/test_spending_splits.py tests/test_bill_kinds.py tests/test_bills_ledger.py tests/test_bill_split.py tests/test_paystub_split.py tests/test_vision_tables.py   (all four fixes in)"
    exit_code: 1     # 390 passed, 1 skipped, 2 failed: test_paystub_split.py::test_sc75_* ("duplicate column name: one_category", migration 081); both fail identically at START_HEAD ce84cb6 (checked in a throwaway worktree, since removed)
  - command: "ruff check src tests"
    exit_code: 1     # only the 2 pre-existing findings: test_document_v2_browser.py I001, test_receipt_kinds.py F402 (my own two import findings were fixed in f9303e5)
  - command: "git diff ce84cb6 -- tests/dining_receipt_data specs approvals plans/dining-receipt-indent/plan.md"
    exit_code: 0     # empty
escalations: []
```
SL-10 fixes the four confirmed code-review findings. No requirement or test-contract value changed; no migration.

## Finding 1 (MAJOR): family delivery bypassed one-category allocation
- Root cause: `record_payload` (family_routing.py) built the receipt record without `receipt_kind`/`bill_kind`, so `publish_receipt` saw `kind=None` and published the copy as not dining (no `one_category`, ordinary split rules, recipient's item memory could override items).
- Change: for a receipt row the payload now carries the kind in its own column (`kind_column(row)`: `receipt_kind`, or `bill_kind` for a bill, where the same omission applied), plus that kind's details (`details_json[kind]`) and the worked-out tip (`tip_worked_out`), which `publish_receipt` already reads from the record. Other consumers (`import_request`, `payload`) just pass the record on.
- Regression test: `tests/test_dining_receipts.py::test_a_dining_receipt_delivered_by_the_family_counts_wholly_under_its_category` — a real `record_payload` → `apply_delivery` roundtrip into a second library of B0 whose category is travel, one item groceries/model, and the recipient's item memory says Coffee is groceries: the copy is dining, `one_category=1`, items `("travel","receipt")` ×5, and its split (items, tip, difference, with a 30.00 share) is all travel and sums to the share.

## Finding 2 (MAJOR): Undo of a kind change left the replacement reading's receipt category
- Root cause: `category_snapshot` stored only `one_category` and the item categories; the kind-change reading rewrites `receipts.category` (dining for a dining reading, the model's otherwise) and Undo never put it back.
- Change: `category_snapshot` also stores `"category"`; `_undo_categories` restores it with the flag and the items, unless a `receipts` correction with `field='category'` exists after the kind correction (id greater), in which case the user's category stays. A snapshot without the key leaves the category alone. The Undo's own correction snapshots the category too, so undoing the Undo is exact.
- Regression tests (tests/test_dining_receipts.py): `test_undo_of_a_kind_change_on_an_unreviewed_receipt_gives_back_the_whole_split_both_ways` (dining→grocery→Undo and grocery→dining→Undo, comparing the complete `splits_of`, item categories, category and flag; the grocery reading is `same_amounts_grocery_stub`, B7 with total 61.55 and tip 8.79 cited so the amounts match B0's), and `test_undo_of_a_kind_change_keeps_a_category_you_corrected_since_and_a_snapshot_without_one_leaves_it`.

## Finding 3 (MAJOR): zero-price side rows failed before the backstop
- Root cause: `problems_in`'s row check required each row's amount to be printed in its cited lines; a 0.00 row citing only an unpriced indented line failed it, the correction retry failed too, and the run raised "Nothing from this document was published" before `attach_side_lines` ran.
- Change (extraction.py): `side_line_ids(lines)` (lines with indent ≥ 1 and no amount: attach_side_lines' drop condition) is passed through `ask` → `problems_in`/`verify`/`base_answer`. Only for an item row (`item_row=True`, in the rows loop, not summary fields) whose amount is zero and whose cited lines are all in that set, the amount check is skipped. `ask` computes the set only when the rows call is a receipt's (`kind == "receipt"`), so a bill's rows are unchanged. Everything else (unindented or unknown-indent line, nonzero amount, a summary field) keeps strict validation.
- Regression tests (tests/test_receipt_side_lines.py): `test_sc13a_side_lines_published_as_zero_dollar_items_are_dropped_too` now drives B6z through the real extraction path with the same assertions as SC-13 steps 2–4 (shared helper `assert_side_lines_stay_with_their_item`, also used by `test_sc13_…`), and `test_sc13a_a_zero_dollar_row_citing_an_unindented_or_unknown_line_is_still_refused` (indent 0 and unknown indent → run fails with the amount message and "Nothing from this document was published").

## Finding 4 (MINOR): a reread dropped a document association another segment still needed
- Root cause: `Reconciler.unlink_documents` kept the association only when the same receipt (`l.receipt_id=?`) still had a live link to a charge from that document.
- Change (reconcile.py): the keep-query now joins `receipts r` and tests `r.document_id=<receipt_document>`, so a live link of any receipt read from the same document counts. The now-unused `receipt_id` parameter stays in the signature (one caller).
- Regression test: `tests/test_dining_receipts.py::test_sc20c_a_second_receipt_of_the_document_still_joined_keeps_the_documents_shown_as_the_same_purchase` — two segments of one document, each linked to a charge read from the same other document; a reread of the first removes its link and the shared same_record link remains. It fails before the fix (empty list).

## Open issues
- The SC-20 (c) test lives in `tests/test_dining_receipts.py` (`test_sc20c_the_documents_of_a_removed_link_…`), not `test_reread_links.py`; the finding-4 test sits next to it there.
- `tests/test_paystub_split.py::test_sc75_*` (two tests) fail with "duplicate column name: one_category" at migration 081, identically at START_HEAD ce84cb6; not caused by this slice, not investigated.
- A zero-valued item row citing only unpriced indented lines now passes the amount check even if it is the first row of a chunk (nothing kept before it, so `attach_side_lines` leaves it as a 0.00 item, as it does an unpriced one in SC-13 (b)).
- Undo restores the category only; amounts a kind-change reading rewrote (total, tip) are not restored, as before. Finding 2's tests therefore use readings whose amounts match.
- Not run: the full suite; browser tests.
