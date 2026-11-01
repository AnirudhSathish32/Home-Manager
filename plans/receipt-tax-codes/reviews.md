# Plan reviews: receipt-tax-codes

## Pass 1 (2026-11-01)
Reviewer: claude / claude-opus-5-5, native subagent `general-purpose`, max_subs 0. The first attempt was cut off by a
rate limit with no findings and isn't counted. The retry's verdict: REVISE.

| ID | Sev | Finding | Disposition |
|---|---|---|---|
| M1 | MAJOR | The general receipt's form `ReceiptSummary` isn't a `NEW_FIELDS` key (`extraction.py:527-528,1572`), so bad tax fields fail the whole summary; the fallback is untested. | Verified. Fixed: `NEW_FIELDS` names `ReceiptSummary`, each kind form, `Items`, `GroceryItems`; SL-03 `new_fields_fail` test. |
| M2 | MAJOR | `family_routing.record_payload` (`:254-266`) drops codes and lines, so a member's copy shares tax by today's rule (449/4384/1359 vs 445/4347/1400). | Verified. Fixed: payload carries `tax_code`, `tax_source` and tax lines (P6); SL-01 delivery test, family suites in SL-01/SL-02 checks. |
| m1 | MINOR | New schema fields need defaults (`StrictModel`). | Fixed in the schema sketch. |
| m2 | MINOR | `Item.taxed`'s Field description also prompts the old rule. | Fixed: reworded too. |
| m3 | MINOR | Correction preview reads `validation_json`, not `record()`. | Fixed: claim removed. |
| m4 | MINOR | Filter tax issues before `doc2Why`'s length check. | Fixed, with a browser assertion. |
| m5 | MINOR | An unreadable amount would leave BF untaxed and bring the bug back. | Decided P7 (counts as taxed, then fallback); unit case with expected 449/4384/1359. Flagged for the user. |
| m6 | MINOR | SC-07 should use the public correction path (which also runs the reconciler). | Fixed: `manager.correct` + `PATCH` via `TestClient`. |
| m7 | MINOR | The legend instruction must leave out food-stamp meanings. | Fixed: instruction plus a `legend_food_stamp` case. |
| I1 | INFO | R-c is moot (discount spread is proportional). | R-c rewritten. |
| I2 | INFO | Kept items keep stale codes. | P8, documented. |
| I3 | INFO | Line numbers; `scrubbed` does mask new fields. | Fixed. Key name `tax_lines` kept (scoped under a receipt record). |

## Pass 2 (2026-11-01)
Reviewer: claude / claude-opus-5-5, native subagent `general-purpose`, max_subs 0. Verdict: PASS WITH MINORS (no BLOCKER/MAJOR).
All of pass 1 (M1, M2, m1–m7, I1–I3) confirmed fixed or properly decided against the repository.

| ID | Sev | Finding | Disposition |
|---|---|---|---|
| p2-m1 | MINOR | `tests/test_table_engine_record.py:214-215` pins v32; the SL-03 bump would break it. | Verified. Fixed: becomes a `!=` check; the file is in SL-03's checks. |
| p2-m2 | MINOR | `manager.correct` is really `correct_record` (`manager.py:2189`); the `record_shares` pattern is in `test_family_inbox.py:64`. | Verified. Fixed. |
| p2-m3 | MINOR | A 0.00 tax line's members and the "every line with an amount" check were unspecified. | Fixed: members untaxed; every readable line needs a member (P9); unit cases. |
| p2-m4 | MINOR | A normalized Decimal can print "1E+1". | Fixed: `format(..., "f")`, with unit cases. |
| p2-i1 | INFO | Single-letter codes barely test the citation. | Consistent with FR-08; no change. |

Loop exits after pass 2: no BLOCKER/MAJOR remains.
