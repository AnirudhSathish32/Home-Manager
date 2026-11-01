# Plan reviews: receipt-item-table

## Pass 1 (2026-11-01)
Reviewer: claude / claude-opus-5-5, native subagent `general-purpose`, max_subs 0. Verdict: REVISE.

| ID | Sev | Finding | Disposition |
|---|---|---|---|
| M1 | MAJOR | `test_planned_bugfixes_browser.py:44-46` becomes vacuous: EGGS is seeded with unit price 18.00, which the new Unit price cell keeps showing after a correction. | Fixed: `data-col` cell selectors; SL-02 scopes `:44,:46` to the Line total cell (R-e). |
| M2 | MAJOR | Test-contract fixture N (R's sale totals with one item returned) is an unresolvable exchange: `sign_return` issue, nonsense shares, but SC-12's oracle still passes. | Verified (`extraction.py:1658-1665`). Routed to the spec gate. Resolved there: the user amended the contract (N is now a whole return of the filter, NA unsigned with `return_marker` "RETURN"; SC-12 has a P-check −1299/−101/−1400, share −1400, and page checks −$12.99 / −$14.00 "with tax") and re-approved the spec bundle (f9ace30b…). Plan updated: new spec hash, `sign_return` whole-return row in the integration table, NA fixture shape, SL-01 N unit and `Ledger.record` tests, SC-12 oracle with a hand trace through `sign_return` and `allocate`, P3 note. |
| m1 | MINOR | Rule 4 gives a line total for "0.5" and raises on "NaN". | Fixed: only a finite ±1 takes rule 5; unit tests added. |
| m2 | MINOR | `tax_included` is true when tax weights sum to zero, but `allocate` gives the tax to an extra row. | Fixed: require a non-zero basis sum; unit test added. |
| m3 | MINOR | SC-02 is missing the quantity-stays-empty and reload checkpoints. | Fixed in the oracle section. |
| m4 | MINOR | FR-07 alignment oracle unspecified. | Fixed: geometry check with and without Code. |
| m5 | MINOR | Paid's `{signed:false}` not stated. | Fixed. |
| INFO | — | Row Correct label "Price"; SC-11 Printed details may be absent; `tax_basis` single basis vs per-line tax later. | Label kept (P5); SC-11 step 4 accepts absence; `tax_basis` note left for receipt-tax-codes. |

## Pass 2 (2026-11-01)
Reviewer: claude / claude-opus-5-5, native subagent `general-purpose`, max_subs 0. Verdict: PASS WITH MINORS (no BLOCKER/MAJOR).
Scope: prior fixes, the changes for the amended contract, and an independent trace of fixture N. The trace confirms
whole return → −1299/−101/−1400, share −1400, `tax_included` true, unit price "-12.99 USD".

| ID | Sev | Finding | Disposition |
|---|---|---|---|
| M1, M2, m1–m5 | — | All confirmed fixed against the code. | Closed. |
| p2-m1 | MINOR | The browser tests never set a home currency, so `amount` renders "12.99 USD", not "$12.99" (`ui.js:191,203`; `seed_documents.py:40`). | Verified and fixed: each seed sets `home_currency` USD as `test_bill_kinds_browser.py:15-17` does; the `ui.js` row notes the precondition. |
| p2-i1 | INFO | P3's "−1" quantity only takes rule 5 as ASCII "-1"; U+2212 falls to rule 4. | Fixed: the unit test uses ASCII "-1", and the U+2212 text is tested as "—". |

Loop exits after pass 2: no BLOCKER/MAJOR remains.
