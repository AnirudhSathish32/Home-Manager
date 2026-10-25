# Plan reviews: account-import-pdf

## Pass 1 (2026-10-24): REVISE
Reviewer: provider `claude`, model `claude-opus-5-5`, native subagent `general-purpose` (route `review-plan`, `max_subs=0`,
recorded as `subagent-review-plan-1`). Comprehensive pass against spec, contract, interview and repository at `ea79e16`
plus the working tree. The planner checked every cited path before deciding a disposition.

| # | Sev | Finding (evidence) | Disposition |
|---|---|---|---|
| M1 | MAJOR | Day/month order is unresolved for the X, F, M, V and D-full fixtures, and year-less dates were guessed as MM/DD (`tabular.py:205–218`) | **Fixed.** Order is decided once across the linked tables for every date shape, and a year-less date is never assumed to be MM/DD. Contract fixture rules now state the `date_format` input (an input, not an expected value). Plan P10 |
| M2 | MAJOR | The manual-entry duplicate in SC-10 10-a can't happen: manual rows store `manual:<uuid>` (`ledger.py:481`), and `replace_manual` replaces them after reconciliation (`reconcile.py:699–722`) | **Escalated, and the user decided (replace manual).** FR-17 and contract 10-a amended. The plan adds `reconcile.manual_match` (extracted, behavior unchanged) for the preview label |
| M3 | MAJOR | The `document_currency` rule would block contract SC-18 18-a, where one EUR row would turn the whole document EUR | **Fixed.** The currency comes from a `Currency:` line, or from a code carried by every amount cell. Partial codes are row-level only |
| M4 | MAJOR | The SC-16 20,001-row double can't be saved through `publish` (24 MiB `PDF_EVIDENCE_BYTES` and 250,000-character caps) | **Escalated, and the user decided (analyzer plus lowered limit).** FR-21 and contract SC-16 amended. The plan exposes `MAX_ROWS`/`MAX_CELL` as module constants |
| M5 | MAJOR | Pages with fewer than 40 non-space characters fall back to vision (`pdf_reader.py`), so X page 3 would fail with no model | **Fixed.** A contract fixture rule adds a footer line of at least 40 characters per native page. The SL-01 gate checks that every intended native page is `embedded_text` |
| M6 | MAJOR | A new account's type doesn't reach the preview, so the sign default would be wrongly required | **Fixed.** The preview accepts `new_account` |
| M7 | MAJOR | The lazy 50-per-request index backfill copies `text_index` and can show partial lists silently (`text_index.py:84–99`) | **Fixed.** The index follows the text-index pattern: `index_quietly` on publish, a startup backfill in `open_library`, and an `indexing` flag shown in the picker |
| H1 | HUMAN | OD-1 (a) overrides interview D11. OD-2, OD-3, and the unmitigated R2 and R4 need explicit acceptance at plan approval | **Carried to plan approval.** To be listed for the user then |
| m1 | MINOR | The integrity comparison could falsely refuse, because the DB copy goes through `read_result` → `restore_text_tables` | **Fixed.** Both copies are parsed with `read_result` |
| m2 | MINOR | `make_pdf` can't draw `•`/`…` (Latin-1) | **Fixed.** A cp1252 option in SL-01, plus a contract fixture rule |
| m3 | MINOR | `date_format`/`sign` duplicate `ImportMapping`; `new_account` should reuse `AccountInput` | **Fixed.** `mapping` is refused for PDFs, and `new_account: AccountInput` |
| m4 | MINOR | FR-26 on the client would copy the `ledger_kind` and currency fallback rules | **Fixed.** `pdf_import.match` and `refused` are computed on the server |
| m5 | MINOR | SC-15 Ps message ("from statement …" against "from this statement") | **Fixed.** Contract amended to `from this statement` |
| m6 | MINOR | Schema map docs step missing (`docs/development.md`) | **Fixed.** Added to SL-08 |
| i1–i3 | INFO | Ordinals across selected tables; Today's count under P5; the mutex scope | Recorded as P11 and P12. The mutex point needs no change (the `reading_id` check is inside the transaction) |

**Routing:** M2 and M4 changed the approved spec bundle (spec.md FR-17, FR-21, SC-10, SC-16; test-contract.md 10-a,
SC-16, fixture rules, SC-15 Ps). The spec approval is now stale. Per plan-feature's review loop (step 5), planning paused
for the spec gate. Pass 2 runs after the amended bundle is approved again.

## Pass 2 (2026-10-24): REVISE
Reviewer: provider `claude`, model `claude-opus-5-5`, native subagent `general-purpose` (`subagent-review-plan-2`,
`max_subs=0`). It reviewed the pass-1 corrections, the amended spec bundle (re-approved a49e0ea8a230) and the changed
sections. It confirmed that M1, M3–M7 and m1–m6 hold, and that M2 holds only partly. The planner verified MJ-1 against
`reconcile.py:699–722` and MJ-2 against `tests/test_pdf.py` (`BT /F1 10 Tf`, fixed MediaBox 612×792) and
`pdf_layout.py:520`.

| # | Sev | Finding | Disposition |
|---|---|---|---|
| MJ-1 | MAJOR | `manual_match` asked the reverse of `replace_manual`'s question, so "replaces a manual entry" could be promised when the reconciler will find two candidates | **Fixed.** `reconcile.manual_candidates(db, manual, extra)` is extracted from `replace_manual` (unchanged behavior). The label is computed from each manual entry's side, with the preview's ticked New rows as `extra`, and is shown only for a single candidate. Test variant 10-b (two candidates: no label, no replacement) is added in SL-04 |
| MJ-2 | MAJOR | The long-cell fixtures (V v5, SC-16 step 4) can't yield a native table at 10 pt on a 612 pt page | **Fixed.** `make_pdf` gets additive per-item font size and `media` page size options. The long cell goes on a wide page with the other columns past it. A new SL-01 gate check escalates if the reader still refuses |
| m-1 | MINOR | One failing reading would stall the index backfill forever | **Fixed.** `index_row` always writes a row (`error` column), so the backfill never stalls |
| m-2 | MINOR | Out-of-date text in Doubles and Review history | **Fixed** |
| m-3 | MINOR | Import steps of SC-07/24/25 weren't run before M1 | **Fixed.** Added to SL-03's command |
| m-4 | MINOR | A partly typed new account in the preview gets a 422 | **Fixed.** The preview takes `account_type` and `currency` on their own; only the import needs a full `AccountInput` |
| m-5 | MINOR | Rejected-earlier rows weren't placed in the counts | **Fixed.** They count as duplicates, plus `rejected_earlier`. J1 step 7 = 0/9/1 |
| m-6 | MINOR | Readings from before the native layout have no tables | **Fixed.** A blocking issue "Read this document again …", and the reading isn't indexed |
| m-7 | MINOR | Inconsistencies (refused null against field; "pure" module with DB functions; the decisions table was split) | **Fixed** |
| INFO | — | `tabular` date helpers accept only 4-digit years | **Recorded.** `pdf_import` has its own date-shape parser using the same order rule |

No spec change was needed for pass 2.

## Pass 3 (2026-10-24): PASS WITH MINORS (no BLOCKER/MAJOR; loop exits)
Reviewer: provider `claude`, model `claude-opus-5-5`, native subagent `general-purpose` (`subagent-review-plan-3`,
`max_subs=0`). It confirmed that MJ-1 and m-1 to m-7 hold, and that MJ-2's direction is right.

| # | Sev | Finding | Disposition |
|---|---|---|---|
| MINOR-1 | MINOR | The preview route refuses a request with neither an account nor a currency (`api.py:924–926`), but J1 step 3, SC-04 and SC-06 step 1 need it | **Fixed.** The check is skipped for `.pdf`. The currency fallback chain and the row-status account (request, else match, else all New) are defined. Verified by the planner at `api.py:924–926` |
| MINOR-2 | MINOR | The long-cell fixtures need `media` to set the CropBox, and the 2,001-character cell must split into words of at most 1,000 characters (`pdf_layout.py:44, 284, 305`) | **Fixed** in the SL-01 details. The font stays at the default 10 pt |
| INFO | — | A failed index write at publish leaves `indexing` true until the next start | **Accepted.** It matches the text index |

H1 (OD-1 option a against interview D11; OD-2; OD-3; unmitigated R2 and R4) goes to the human with the plan for
approval.

## After the loop (2026-10-24): FR-08 amended after the G1 reader check
SL-01's planned G1 gate was run early, in the new Linux `.venv`, as a throwaway script outside the repo. It confirmed that
the reader builds no native table for a headerless page, by design (`pdf_layout.py:421–440`). It also builds none for a
headed page with a column blank on every row. The user chose (2026-10-24) to have the import rebuild those rows from
the saved words. That amended:
- spec: the terms, FR-08, FR-24, U2, SC-07, and the D10 and R1 wording;
- contract: the P-checks, SC-07 (rewritten, plus 7-c and 7-d), SC-22, G1 and G2;
- plan: verified facts, the analyzer design, row fields, locators, the badge link, the SL-01 gate and Risks.

These changes came **after** the three review passes, so the changed sections are unreviewed. Plan-feature allows at most
three passes. A fourth, scoped to this change, needs the user's agreement.

## Pass 4 (2026-10-24, extra pass the user authorized, scoped to the FR-08 amendment): REVISE
Reviewer: provider `claude`, model `claude-opus-5-5`, native subagent `general-purpose` (`subagent-review-plan-4`,
`max_subs=0`). It ran throwaway reader probes in `/tmp/hm-review4/` against the project `.venv`. The planner verified
BLOCKER-1 and BLOCKER-2 with its own probe (`/tmp/hm-spike/lines.py`: X page 2 is saved as `'09/03/2026 B1'`, `'1.00'`,
`'1,009.00'` …; K page 1 gives a native 3×2 `Date | Description` table). It then checked that grouping saved words by
baseline recovers every printed row on both pages (`/tmp/hm-spike/rows.py`).

| # | Sev | Finding | Disposition |
|---|---|---|---|
| BLOCKER-1 | BLOCKER | A saved line is not a visual row on rebuilt pages (`pdf_layout.py:504–517`), so FR-08's per-line rule finds no rows | **Fixed (spec amended).** FR-08 now works on visual rows: saved words grouped by baseline with the reader's 0.25 × font-size rule. The plan re-implements that grouping and pins it with unit tests against native tables |
| BLOCKER-2 | BLOCKER | A blank-column heading page yields a wrong native `Date \| Description` table that hides the heading and rows | **Fixed (spec amended).** The heading is searched in visual rows. A native non-transactions table that shares baselines with the rebuilt heading or rows is absorbed into the rebuilt table |
| HUMAN-1 | HUMAN | Every headerless page carries `unresolved_columns` → `pdf_layout_review`, so FR-09 would untick the rows FR-08 says are ticked | **The user decided: ticked.** FR-09 amended: `unresolved_columns` alone on a page the import rebuilds is not a flag. Other issues still flag the page |
| MAJOR-1 | MAJOR | The footer `Page N of M` raises `unresolved_columns` on clean pages | **Fixed (contract fixture rule):** the footer is words only. No expected value changes |
| MAJOR-2 | MAJOR | J1 step 3 still says "three native tables" | **Fixed:** one transactions table (native or rebuilt) plus two continuation entries |
| MINOR-1 | MINOR | FR-05 "cell text" has no meaning for rebuilt rows | **Fixed:** "for a rebuilt row, its words' text" |
| MINOR-2 | MINOR | A1 out of date; SC-22 singular line; FR-08 "every saved line" | **Fixed:** A1 restated; SC-22 lines plural; rows are only visual rows after the heading |
| MINOR-3 | MINOR | Text or a second amount in an amount column is undefined | **Fixed:** the row is rejected with a reason (FR-08), and contract variant 7-e is added |

Spec bundle amended (FR-05, FR-08, FR-09, A1; contract fixture rule, P-checks, J1 step 3, SC-07 7-e, SC-22). It needs
re-approval before pass 5 (scoped to the pass-4 corrections). The user authorized pass 5 on 2026-10-24.

## Pass 5 (2026-10-24, extra pass the user authorized, scoped to the pass-4 corrections): HUMAN DECISION, no BLOCKER
Reviewer: provider `claude`, model `claude-opus-5-5`, native subagent `general-purpose` (`subagent-review-plan-5`,
`max_subs=0`). Its probes are in `/tmp/hm-review5/`. It confirmed that every pass-4 finding holds against the reader
(visual rows for K, R, X and 7-c; heading absorption; the FR-09 exception on K; words-only footers clean; 7-c, 7-d and
7-e behave as written; `?lines=` highlights line ids). The planner reproduced MAJOR-1 (`/tmp/hm-spike/footer.py`): the
same complete native table gives `['unresolved_columns']` with a `Page 1 of 3` footer and `[]` with a words-only footer.

| # | Sev | Finding | Disposition |
|---|---|---|---|
| MAJOR-1 | MAJOR / HUMAN | A `Page N of M` footer flags native-table pages, so every row starts unticked, which is inconsistent with rebuilt pages | **The user decided: extend the exception.** FR-09 amended: a page holding a transactions table (native or rebuilt), or a continuation page, whose only issue is `unresolved_columns` is not flagged, and the issue isn't listed. Contract variant 8-a added |
| MINOR-1 | MINOR | The row rule silently dropped straddling rows; "outside every span" can't happen | **Fixed:** candidate rows include straddles; accept/reject rules; Balance-only rows aren't candidates |
| MINOR-2 | MINOR | 7-a schedule lines have no description, so they would be rejected | **Fixed (contract fixture input):** `Scheduled payment` |
| MINOR-3 | MINOR | Unflagged pages' issue messages weren't defined | **Fixed:** not listed, and not used as row labels (spec FR-09 too) |
| MINOR-4 | MINOR | SC-22 table and row were ambiguous | **Fixed** in the SL-05 notes: `page-2-import-continuation`, row 1 |
| MINOR-5 | MINOR | Stale Terms, data flow, SL-02 list, G1 list, J1 cell text, review history | **Fixed** (the spec Terms in this amendment) |
| INFO | — | Absorption wording; baseline compared to the row's first glyph; wrapped-description risk wording | **Fixed in the plan** |

No BLOCKER remains. The only remaining spec change after pass 5 is MAJOR-1's FR-09 wording, decided by the user, plus
minor wording. No further pass is planned unless the user asks for one.
