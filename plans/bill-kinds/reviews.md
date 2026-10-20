# bill-kinds plan reviews

Each review pass appends its findings and their dispositions here. Reviewers read this file first; items fixed or
rejected here are settled.

## Pre-review decisions (planner, 2026-10-19)
- Split: the spec has 21 FRs. The user chose one plan in 8 slices (2026-10-19), as document-forms was planned.
- FR-50 on general bills: the user chose an "Earlier balance" row for a general bill whose lines add up to its printed
  new charges; "Not accounted for" only when a check fails (2026-10-19). Recorded in plan R1 as a spec amendment the spec
  should carry.

## Pass 1 (fresh reviewer, 2026-10-19): REVISE
| ID | Finding | Disposition |
|---|---|---|
| B1 | FR-50 "Earlier balance" isn't in the approved spec; the plan's hash binds the unamended spec | **Escalated** to the user as spec item S1: amend FR-50/SC-46/SC-50, re-approve the spec, update the plan hash |
| M1 | A kind change on a reviewed bill, Apply details and undo leave line types inconsistent | **Fixed**: plan "Kind and lines". Lines follow readings only; undo to general clears `line_type`; a NULL-type rent line accepts a `line_type` correction; journey asserts each. Also raised as spec item S5 |
| M2 | Old `line_kind:N` vs new `line_type:N` replay conflict; SC-49 step 3 oracle undefined | **Fixed**: replay rule in the plan (`line_type` only on rent; then `line_kind` wins); SC-49 step 3 oracle stated |
| M3 | SL-02 needs `printed_dates`, which SL-03 builds | **Fixed**: moved into SL-02 |
| m1 | R3 wrong; SC-50 means unchanged suites | **Fixed**: R2 is now a stop-and-report deviation; R3 corrected (verified lines 133, 372) |
| m2 | Budget part steps traced to the whole `bill.expected` | **Fixed**: part steps carry no drill-down trace; each part's inputs are the expected amount and the splitting bill |
| m3 | Utility part computed two ways (category vs `line_type`) | **Fixed**: both use category `utilities`; final rule pending spec item S3 |
| m4 | `printed_dates` match boundaries | **Fixed**: no digit or `/` adjacent |
| m5 | Invoice answered rent still read with the rent schemas | **Accepted** in the plan, with the reason |
| m6 | `NEW_FIELDS` would bypass the fallback; 38b end state | **Fixed**: kept out of `NEW_FIELDS`; 38b end state and stubs stated |
| m7 | Where the kind citation lives | **Fixed**: `result_json` classification named as the oracle |
| m8 | Family routing drops the new fields | **Accepted** as risk R9 and logged in `docs/open-work.md` (D21) |
| m9 | Prorated skip only in the receipts loop | **Accepted** as risk R8 |
| S1–S6 | Spec items (FR-50 earlier balance; FR-43 `monthly_rent`; FR-45a category vs utility lines; FR-54 circular anchor; FR-42/D7 for bill lines; Schema "rebuild" wording) | **Escalated** to the user. The review loop is paused until the spec is amended and re-approved |

## Spec amended 2026-10-19 (user asked for the recommended changes)
S1–S6 written into specs/bill-kinds/spec.md and test-contract.md (FR-42, FR-43, FR-45a, FR-50, FR-54, FR-56, SC-50,
"Schema"; contract SC-38 step 2, 43a-2, journey step 7, SC-46a, SC-50, traceability). The gate reports the new bundle
dbc82bbe… approved; the plan's hash is updated. B1 and S1–S6 are settled. Pass 2 reviews the plan against the amended spec.

## Pass 2 (fresh reviewer, 2026-10-19): REVISE (2 MAJOR, 5 MINOR)
| ID | Finding | Disposition |
|---|---|---|
| M1 | Slice commands: one `-k` filtered the regression files to nothing; SL-01's second `-k` replaced the first | **Fixed**: each slice runs its `-k` on test_bill_kinds.py and the regression suites unfiltered, one `-k` per command |
| M2 | FR-56: an 8-day prorated move-in falls in `BILL_PERIODS["weekly"]` | **Fixed**: prorated lines are left out of the schedule test; plan-level 8-day variant added to sc46c |
| m1 | P7 vs the page changes (Counts as, top fields) for pre-kind bills | **Fixed**: every page change is gated on `bill_kind` |
| m2 | SL-08 `version` wording contradicted the replay rule | **Fixed**: asserts that the `line_kind:N` correction survives |
| m3 | FR-46 guard was based on words, so Issued could equal the due date on a statement-and-due line | **Fixed**: also dropped when the matched date follows `due` or equals the due date on a due-naming quote |
| m4 | FR-45a split applied to a bank-payment obligation | **Fixed**: only an obligation whose `source_receipt_id` is a rent bill; test added |
| m5 | The order-check issue duplicated "Due date was not found" | **Fixed**: the issue starts with "Due date" |
| Spec gaps | 46c-1 proposal (prorated + full month); FR-46 combined line; FR-45a obligation source | FR-46 and FR-45a resolved by m3/m4 (literal reading). **46c-1 is open for the user** (plan R10) |

## Pass 3 (fresh reviewer, 2026-10-19): REVISE (1 MAJOR, 4 MINOR); pass-2 fixes confirmed
| ID | Finding | Disposition |
|---|---|---|
| M1 | A rent line with one date became a 1-day "prorated" period | **Fixed**: a "dated line" has no period; its date (`details.date`) counts only for FR-54; plan-level sc46a variant |
| m1 | SL-01 ran test_bill_kinds.py before any slice created it | **Fixed**: SL-01 creates it with the `version` test |
| m2 | SL-01 touches the receipt-kind path but ran no receipt suite | **Fixed**: test_receipt_kinds.py and test_traces.py run unfiltered in SL-01 |
| m3 | Issued guard dropped a correct date printed after a Due label | **Fixed**: drop only when the nearest date label before the date is `due` |
| m4 | Kind control on bills with `bill_kind` NULL | **Fixed**: "Not read with kinds", and choosing a kind re-reads |
| info | `\bpayment|paid\b` regex grouping | **Fixed** to `\b(payment|paid)\b` |
| Spec gap | One-dated rent line | Resolved by M1, following FR-54's "with no period, is dated" |
| Spec gap | 46c-1 proposal | Still open for the user (plan R10) |

## Pass 4 (fresh reviewer, 2026-10-19): REVISE (1 MAJOR, 6 MINOR)
| ID | Finding | Disposition |
|---|---|---|
| M1 | The dated-line rule beat the whole-month rule (SC-41 broke) | **Fixed** with one explicit order: month-only answers are expanded first, then the dated-line rule. Same area as pass-3 M1, so per the loop rule the simplest single rule was adopted, not another patch |
| m1 | Recurrence with no rent line period | **Fixed**: monthly |
| m2 | FR-54 with no kept due date | **Fixed**: nothing is left out (the bill is already in review) |
| m3 | Model not told where a one-date line's date goes | **Fixed**: sentence added to the rent row instructions |
| m4 | Regex case | **Fixed**: `re.IGNORECASE` |
| m5 | Nearest-label set; column-header edge | **Fixed**: label set named; the column case is accepted (a note only) |
| m6 | SL-01 skips the bill and migration suites | **Fixed**: run unfiltered in SL-01 |

## Pass 5 (fresh reviewer, 2026-10-19): READY (0 BLOCKER, 0 MAJOR, 2 MINOR)
| ID | Finding | Disposition |
|---|---|---|
| m1 | Rent row instruction excluded "payments received" while naming a payment as a one-date line | **Fixed**: only the payments-received total is excluded; a ledger's dated payment row is a line |
| m2 | `Previous Balance $0.00` must count as printed | **Fixed**: "printed" means kept, 0 included (`is not None`) |
| info | SC-41 stub wording (`October 2026` vs `YYYY-MM`) | **Noted** in Risks: the test stubs `2026-10` |
| Spec gap | 46c-1 proposal | Open for the user (R10); doesn't block implementation |
Loop closed: no BLOCKER or MAJOR open.
