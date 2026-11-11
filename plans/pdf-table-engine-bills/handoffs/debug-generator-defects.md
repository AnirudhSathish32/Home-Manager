```yaml
task: debug-generator-defects     # SL-09's three escalated engine defects (SPLIT_BLIND, CARRIED_TITLE, LAST_YEAR)
result: fixed                      # all three fixed, no strict expected failure left; two SL-09 observations reported, not fixed (below)
provider: claudeAgent
model: claude-opus-5-5
model_family: anthropic
helper_subagents: 0
start_head: 0e7da22
end_head: 684b2f9                  # last code commit; this handoff is committed on top of it
commits: [7bb86e3, 4f886f3, 684b2f9]
changed_files:
  - src/home_manager/documents/bill_split.py
  - src/home_manager/finance/bill_tables.py
  - src/home_manager/documents/extraction.py
  - scripts/statement_diagnose.py
  - tests/test_bill_split.py
  - tests/test_bill_engine.py
  - tests/test_bill_engine_generator.py
checks:
  - command: ".venv/bin/python -m pytest tests/test_bill_engine_generator.py -q"
    exit_code: 0
    result: "281 passed, 0 xfailed (was 249 passed, 32 xfailed)"
  - command: ".venv/bin/python -m pytest tests/test_bill_engine.py tests/test_bill_engine_record.py tests/test_bill_split.py tests/test_bill_corrections.py -q"
    exit_code: 0
    result: "392 passed"
  - command: ".venv/bin/python -m pytest tests/test_paystub_engine.py tests/test_table_engine.py tests/test_paystub_split.py tests/test_paystub_engine_record.py tests/test_bill_kinds.py tests/test_bills_ledger.py -q"
    exit_code: 0
    result: "676 passed, 1 skipped (test_bills_ledger.py:335, the opt-in browser test, skipped before too)"
  - command: ".venv/bin/ruff check <the seven changed files>"
    exit_code: 0
full_suite: not run (per brief)
escalations:
  - "One contract-adjacent test value changed: test_sc105_one_amount_column_is_the_charge pinned BL-MULTI as decided_by 'single'; with sums judged per bill it is 'sum' (FR-105 b comes before d). The contract does not pin it; the role (charge) is unchanged. FR-105 (d) is now asserted on a hand-built table whose sums decide nothing. Please confirm."
  - "Not fixed, for docs/open-work.md (SL-10 owns the doc): a section title above a one-run heading is lost; a title-like key line (masked `Account No. ****NNNN`, also `Due Date …`) followed by rows in reading order becomes a section title, a holder title when masked (G14 by design)."
```

## 1. SPLIT_BLIND (23 files): the split saw no amount due when it was printed apart from its label
**Reproduced** with generator case 1 (phone, 4 bills, heading `known2`): the reader's evidence lines are `Amount Due ....` (no amount) and the amounts are separate
lines (`138.25`). No line matched `bill_split.anchor_of`, so `has_due` was false for every part and `bill_parts` returned one part with three FR-129 (b) reasons.
`charge_tables.read` already had each pair as an `amount_due` Anchor (label line id, amount word ids from the other layout line).

**Root cause (verified):** `documents/bill_split.py:171` (at 0e7da22): `has_due` read only `anchor_of(line)`, the label and amount on one evidence line.
Run (`documents/extraction.py:4594`) had the engine reading (`bills`) in hand but did not pass it to the split.

**Fix (7bb86e3):** `bill_split.bill_parts(lines, anchors=None)` also takes the engine's anchors keyed by the evidence line that holds the label
(`bill_split.py:148` `anchors_of`, used by `has_due` :181 and by (c)'s new-charges values :213). `bill_tables.split_anchors(bills)` builds the map through
`lines_of` (layout line to evidence line). `ExtractionService.bill_parts` passes it when the engine read the file (`extraction.py:4928`). A scanned file, or one
where the engine failed, passes none and reads the lines as before. The `bill` diagnose mode passes it too (`scripts/statement_diagnose.py:224`), so it reports the
same split. This follows FR-128's rule as written: an amount-due anchor of FR-103, which the engine is.
**Tests:** `test_bill_split.py::test_sc126_an_amount_due_printed_apart_from_its_label_is_the_parts_amount_due_when_the_engine_pairs_them` (hand-built lines:
one part without anchors, two with) and `::test_sc126_generator_case_1_with_a_heading_over_the_amount_column_is_four_bills_from_the_engines_anchors` (real
reader: no line holds `Amount Due <amount>`, four parts at pages 1-4, no reason). Two existing test doubles of `bill_parts` (`lambda lines: …`,
`broken(lines)`) take the new optional argument. Without that, the "201 parts" case would have hit a TypeError and still passed, for the wrong reason.
**Uncertainty:** (c) now also sees engine new-charges anchors. No test changed because of it. A file whose own lines show no new charges but whose engine anchors
differ between unkeyed pages can now get (c), which is what FR-129 (c) asks for.

## 2. CARRIED_TITLE (case 56, and case 83 once it split): a section crossed a bill boundary
**Reproduced:** case 56 (utility, 2 bills over pages 1-2 and 3-4, `Account Credits` last on page 2). `charge_tables.read` runs one table over pages 1-4. A
continued table takes `section = builder.section` (`documents/charge_tables.py:530`), so bill 2's rows on pages 3 and 4 kept the `Account Credits`
SectionTitle of page 2 and were signed as money off (`bill_tables.signed`). Case 83 (3 one-page bills, heading `known2`) showed the same defect once fix 1 split it.

**Root cause (verified):** the table continuation over pages (FR-102, phase 3 FR-92 b) does not know where bills start. Neither `charge_tables` nor
`bill_tables` limited a row's section to its own bill.
**Fix (4f886f3):** `bill_tables.bill_starts` (`finance/bill_tables.py:344`) runs the split rule (lines plus the engine's anchors, as Run does) to find each
bill's first page. `[1]` if the rule raises, since Run words FR-129 (d) itself. `own_sections` (:359) drops a row's section and title when the title was
printed in an earlier bill. `read` (:373) applies both before roles and the adapter. Within one bill a title still carries over pages.
**Tests:** `test_bill_engine.py::test_a_section_title_of_one_bill_does_not_reach_the_rows_of_the_next_bill` (MINI-BILL 1 + `Account Credits` / MINI-BILL 2;
one table over both pages; bill 2's rows have no section and are not money off, also in the adapted rows). It fails without the fix.
`::test_a_section_title_carries_onto_the_next_page_of_the_same_bill` covers the other side.
**Uncertainty:** the engine scopes by the rule's split, not a user's saved split (`saved_segments(source="user")`), which Run reads later. With a user split
that differs from the rule, a section can still cross the user's boundary (or be dropped at the rule's). Rare; the engine has no access to the store.

## 3. LAST_YEAR (cases 29, 33, 64, 67): the sum rule mixed the bills of one table
**Reproduced:** case 64 (phone, 2 bills, `lastyear`, no heading, `swap: False`). One table over pages 1-2. `targets_of` gave [113.07, 118.44] (each bill's new
charges), but `decide` compared the whole column's sum (231.51) with them. Nothing held, so the right-most column (last year) was guessed. Per page, column 1
adds up to 113.07 and 118.44 exactly.
**Root cause (verified):** `finance/bill_tables.py:256-257` (at 0e7da22): targets from all the table's pages against one sum over all its rows. SL-02's
handoff item 4 had flagged it.
**Fix (684b2f9):** `adds_up(table, column, anchors, starts)` (`finance/bill_tables.py:222`) judges each bill's rows of the column against `targets_of(table,
anchors, that bill's pages of the table)` (:208, new `pages` argument). Every bill with rows in the column must add up. `decide` (:266, and the one-column
`sum`/`single` label) uses it, and `read` passes `bill_starts` (:375). One bill is one portion: identical to before. `amounts_in` was used only there and is
removed.
**Tests:** `test_bill_engine.py::test_sc105_c_a_last_year_column_over_two_bills_is_other_the_sums_judged_per_bill` (two headingless `This Bill`/`Last Year`
bills, last year right-most; `This Bill` is the charge by `sum`, no guess). It fails without the fix. `::test_sc105_the_sum_rule_still_needs_every_bill_to_add_up`
(the second bill does not add up, so the result is a guess as before). Changed: `test_sc105_one_amount_column_is_the_charge` (see escalations).
**Uncertainty:** "every bill must add up" is the conservative reading of FR-105 b ("the bill's new charges"). A bill printing no summary on its table pages
has no targets, so the sums decide nothing for that table and headings or the guess follow, as before for one bill.

## SL-09's two observations (not fixed)
- **A section title above its heading loses the title.** Reproduced by hand: `Alex 555-201-1111` (or a plain `Plan Charges`) above a heading printed only
  over the amount column (`Charge`, or `This`/`Charge`) gives rows with no section. A heading with a word at the label side as well (`Description … Charge`)
  keeps it, which is why BL-UTIL's `Electric Charges` works. Root cause: `pay_tables.is_heading_like` (`documents/pay_tables.py:154`, two or more runs)
  rejects a one-run heading, so `heads_above` does not attach it. The title look-ahead (`documents/charge_tables.py:622-626`) skips only attached lines, so the
  title's next line is a text line, not a row, and the title is dropped. FR-101 lists headings as "one or two lines, or one run over several columns". A one-run
  heading over a single column is not among them, and FR-102 defines a title as a line "followed by a row". So this is not clearly required. A fix would widen
  the heading shape in `charge_tables` without touching `pay_tables` (FR-120) and needs its own test pass. Left for docs/open-work.md.
- **A masked `Account No. ****NNNN` directly above a continuation page's rows is read as a holder.** Root cause: a key line that is title-shaped is not consumed
  (`documents/charge_tables.py:546`, `name == "key" and not is_title_like(line)`), so it may become a SectionTitle when the next line in reading order is a
  row, however far below it sits. `****NNNN` matches PHONE (ii) (SL-01 decision 4), so it is a holder title. This is by design: plan G14 / SL-01 decision 3
  need `Account ****9012` to be a holder title. The same mechanism makes `Due Date 07/20/2026` a (non-holder) section title when rows follow it directly.
  I hit that while writing test 2 and put an anchor line between the keys and the rows. Not required by the spec either way. Changing it conflicts with G14's
  test, so it is a decision for docs/open-work.md (for example: a key line is a title only when it sits within one line gap of the row).

## Docs
`docs/documents.md` "Several bills in one file" should say that the split reads the engine's anchors on a text PDF, and that a table running over several bills
keeps sections and sums per bill. Per the plan that doc is SL-10's (not edited here).
