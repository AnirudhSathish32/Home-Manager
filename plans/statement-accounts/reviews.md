# Plan reviews: statement-accounts

## Pass 1 (2026-10-26): HUMAN DECISION, then REVISE
- **Reviewer:** provider `claude`, model `claude-opus-5-5`, native subagent `general-purpose`. Route `review-plan`,
  caller `plan-feature`, `max_subs=0`, recorded as `subagent-review-plan-1`.
- **Scope:** a comprehensive pass against the spec, the test contract and the repository at HEAD `05f9aa4`, with
  synthetic probes only.
- **Gate:** spec APPROVED `733d7de7728f`, equal to the plan's `Spec sha256`.
- **Planner's checks:** B1 was reproduced by the planner with the real reader on the contract's S geometry. A flagged
  page with no table rejected s1–s3, and the same page unflagged read all five rows. B3 (`native_values.py:113–116`,
  `extraction.py:3330–3344`), M2 (`family_sync.py:684–697`, `family_routing.py:53`, `tools.py:559–563`) and the
  correction minor (`ledger.py:2009–2011`) were read and confirmed.

| # | Sev | Finding (evidence) | Disposition |
|---|---|---|---|
| B1 | BLOCKER | On S-flag (no native table), `visual_row` takes the description's `1234567890` as an amount and rejects s1–s3 (`pdf_import.py:229–242`). SC-13 can't pass under "PDF import's rules, unchanged" | **Escalated to the spec (E1).** The recommended amendment refines `visual_row`'s placement rule, removes the non-goal for it, and adds the account-import-pdf regression gate. An SL-01 gate asserts S-flag gives s1–s5 exactly |
| B2 | BLOCKER | On a flagged page the rebuilt table runs to the page end, so a daily balance section becomes rows of it, and FR-27's table-level exclusion never fires | **Fixed.** A Record-side section cut at a balance title or a second heading, plus a D-flag test beyond the contract |
| B3 | BLOCKER | FR-20 notes as review issues, `anchor_rows`' per-row direction note, and the duplicate-cite and omitted-row notes make J1 step 1 `needs_review`, not `proposed`, and break J1-b and SC-16 | **Fixed.** FR-20 notes are record notes (P13, E3 for confirmation). `anchor_rows` and the coverage block run only on pages that aren't rebuilt. FR-29 stays a review reason |
| B4 | BLOCKER | (1) Undo leaves rows `verified`/`user`, so a re-read can't empty the old account. (2) A re-read of a confirmed statement is `kept_reviewed`, yet `account_in` already created …7890. (3) J1-a/SC-06 expect a confirmed statement to move, against FR-26 | **(1) Fixed:** P15, so Undo returns the rows its decision cascaded. **(2) Fixed:** P16, so no account is created for a statement kept as reviewed. **(3) Escalated to the spec (E2).** The recommended amendment makes SC-06/J1-a `kept_reviewed`, with …3456 keeping its statement and no …7890 |
| M1 | MAJOR | `POST /api/finance/accounts` on a waiting account's identity returns it still hidden (`ledger.py:428–431`) | **Fixed.** `account_in(origin='user')` promotes an existing `record` account |
| M2 | MAJOR | `_joint_accounts`, `member_facts` and `_coverage` read accounts outside `accounts()`. The first changes family money | **Fixed.** All three gain the filter (P5, SL-04) |
| M3 | MAJOR | Defaulting `publish_statement` to `origin='record'` breaks about 28 direct test calls and many Record tests, with no guidance | **Fixed.** The ledger default stays `user`, and only `ExtractionService.publish` passes `record`. SL-05 lists the Record-based tests whose FR-01/FR-04 assertions legitimately change, and forbids weakening any other assertion |
| m1 | MINOR | A family delivery into an unconfirmed account is downgraded by FR-04 | **Fixed.** No downgrade when `origin='family'` |
| m2 | MINOR | `Ledger.correct`'s automatic promotion bypasses FR-04 | **Fixed.** It stays `proposed` while the account is unconfirmed |
| m3 | MINOR | The mutex claim was wrong: the import runs outside the mutex | **Fixed.** The text now names the real guards (`BEGIN IMMEDIATE`, the token) |
| m4 | MINOR | Identical overlapping words raise `unresolved_columns`, not `overlapping_text` | **Fixed.** SL-01 uses different overlapping words, else another real trigger, recorded |
| m5 | MINOR | SC-07 fixture (a) can't be built through public paths under the new code | **Fixed.** A documented direct UPDATE, which changes no expected value |
| m6 | MINOR | The `CONFIRMED` predicate is stated twice (SQL and Python) | **Fixed.** A test asserts both agree |
| m7 | MINOR | The `-- sort:` marker isn't a runner feature | **Fixed.** The test splits the script text and executes it again |
| m8 | MINOR | `rebuilt_pages` could fail Record from `read` | **Fixed.** It is caught in `read` as in P8 |
| m9 | MINOR | Provenance zips `line_ids` with `quotes` | **Fixed.** One quote per line id |
| m10 | MINOR | A balance table's second heading on native pages would send every such statement to review | **Fixed.** No issue when the second heading is a balance table's |
| i1–i5 | INFO | Delete inventory matches the schema; C-orphans must filter by FK target; FR-08 hides upgraded hand-made accounts holding only automatic statements; the reconcile queue lists unconfirmed statements; P8 loses the missed-row net | i1 noted. i2 fixed in the oracle text. i3 goes to `docs/money.md` in SL-04. i4 accepted (reconciling confirms the account). i5 accepted, since P8's issue covers it |

**Routing:** E1 and E2 are contradictions inside the approved bundle (spec.md FR-16 and its non-goal against SC-13;
SC-06 and contract J1-a against FR-26). Per plan-feature's review loop, step 5, planning stops for the spec gate.
`spec.md` and `test-contract.md` were not edited. Pass 2 runs after the amended bundle is approved again.

**Spec amendment (2026-10-26).** The user accepted Q1–Q6 and asked for the recommended amendments. The spec bundle now
has spec D5, FR-30 and SC-27, and amends FR-06, FR-10, FR-11, FR-20, FR-27, FR-28, SC-06, SC-16, SC-21, the error
rules and OD-3. The contract amends C-unchanged (no `bills`), the SC-07 double, SC-08's recurring bill, J1-a, SC-13's
note, and SC-21 D-flag, and adds SC-27. The new hash is `043927bcf806`, not yet approved.

E1's rule as written in the plan (number wholly inside a non-amount column) proved wrong on the probe: the word's centre
is inside the Amount span. FR-30 instead uses the reader's own text joining, which keeps `account-import-pdf` 7-e and
x3 rejected. Pass 2 runs once the user has approved the amended bundle.

## Pass 2 (2026-10-26): REVISE
- **Reviewer:** provider `claude`, model `claude-opus-5-5`, native subagent `general-purpose`. Route `review-plan`,
  caller `plan-feature`, `max_subs=0`, recorded as `subagent-review-plan-2`.
- **Scope:** pass 1's findings and their corrections, the amended requirements (D5, FR-30, SC-27 and the amended FR/SC
  and contract rows) and the changed plan sections, at HEAD `05f9aa4` with the uncommitted bundle. No probes run.
- **Gate:** spec APPROVED `043927bcf806`, equal to the plan's `Spec sha256`.
- **Pass 1 follow-up:** B2, B3, B4(1)/(2), M1–M3 and the minors confirmed addressed. Every FR-01 – FR-30 and SC-01 –
  SC-27 maps to a slice and a test.
- **Planner's checks:** M1 confirmed (`BALANCE_NAMES` contains `balance`, `pdf_import.py:30`; contract S and C list a
  balance line last, test-contract.md:65–71, :102–104). M2 confirmed (`ledger.py:1085–1093`, `:1535–1552`;
  `extraction.py:3166`, `:2196–2198`; `document_v2.js:549–554`, `:593–594`). M3 confirmed by reading
  (`pdf_import.py:268–269`, `Raw.reject`).

| # | Sev | Finding (evidence) | Disposition |
|---|---|---|---|
| M1 | MAJOR | Fixtures S and C print a balance line directly above the heading, so FR-27's title rule classes their transactions tables as balance tables and SC-13 – SC-27 fail | **Fixed in the plan (P17).** The builders print the contract's lines (none added or removed) in an order whose last line names no balance; `pcheck_title_lines` asserts it. The real-statement case is added to R4. A spec clarification is offered as **Q7** for the human; not needed for the plan to pass |
| M2 | MAJOR | `record["notes"]` never reaches the stored statement, so FR-20/FR-23 notes aren't shown | **Fixed (P19).** Statement notes go to `details["notes"]` as bills' do; SL-07 shows them; SC-13/16/18 read them from the records API |
| M3 | MAJOR | FR-30 can join the real amount to a long description, so `visual_row` returns `None` and the row is lost silently | **Fixed (P18).** Such a row is rejected with a reason, in PDF import and Record; fixture T added to SL-01 |
| m1 | MINOR | Stale text: `pdf_import` "never changed", D-flag "beyond the contract", P8 "for that page" | **Fixed** |
| i1 | INFO | `ANALYZER_VERSION=2` re-indexes every PDF reading | **Fixed.** SL-03 documents it in `docs/documents.md` |

## Pass 3 (2026-10-26): PASS WITH MINORS
- **Reviewer:** provider `claude`, model `claude-opus-5-5`, native subagent `general-purpose`. Route `review-plan`,
  caller `plan-feature`, `max_subs=0`, recorded as `subagent-review-plan-3`.
- **Scope:** pass 2's corrections (P17, P18, P19, Q7) and the changed sections. No probes run.
- **Gate:** spec APPROVED `043927bcf806`, equal to the plan's `Spec sha256`.
- **Pass 2 follow-up:** M1–M3, m1 and i1 confirmed fixed. P17 judged a plan-side choice, not a contract change (the
  contract fixes no positions for the lines above a table, and no expected value or P-check depends on their order).
  P18 judged within FR-30 and FR-21. Coverage of FR-01 – FR-30 and SC-01 – SC-27 complete.

| # | Sev | Finding (evidence) | Disposition |
|---|---|---|---|
| m1 | MINOR | The section cut's "balance title" could be read as any row containing `balance` (`BALANCE TRANSFER`, a `Beginning Balance` row), cutting the table | **Fixed.** A balance title must sit directly above a heading; a `rows_*` test covers both rows |
| m2 | MINOR | P18 changes PDF import: a tight-gap row read today is now rejected | **Fixed.** R6, SL-03 docs, and Q8 for the user |
| m3 | MINOR | A statement whose `details` holds only `notes` shows an empty "Printed details" section (`document_v2.js:589–592`) | **Fixed.** SL-07 leaves `notes` out of the emptiness check |
| m4 | MINOR | R4/Q7 called the fallback harmless, but the model's reading is the misread this feature fixes, and it is silent | **Fixed.** Q7 reworded with a recommendation to amend FR-27, to be decided at plan approval; P20 adds a record note when a title excludes a transactions-shaped table |
| i1 | INFO | Wrong line citations (`pdf_import.py:250–251`, `:369–370/:383–384/:397–398`, `:29`) | **Fixed** (verified by the planner) |
| i2 | INFO | "29 FRs" and M1's FR list missing FR-30 | **Fixed** |
| i3 | INFO | Fixture T can't be built on S's columns as described | **Fixed.** Placement spelled out with a P-check |

**Result:** no BLOCKER or MAJOR remains after three passes. The plan is READY for the user's approval, with Q7 and Q8
to answer at approval.

## Post-review update for D6 (2026-10-26)
After pass 3 the user decided Q7 and Q8, and the spec bundle was amended (spec D6, FR-30's exception, SC-28; contract
fixture T, SC-28 and gap G5; a Q7 entry in `docs/open-work.md`). The user approved it on 2026-10-26:
`100a178661f78869d293313f792467d8945290f7f943977fb2cd4397afa11184` (`gate.py check --stage spec` passes). The review
loop's three passes are used, so no further pass was run. The plan changed only here:
- **Header:** `Spec sha256` is the new hash. A "Spec amended again (D6)" note follows the D5 note.
- **FR-30 in `pdf_import.visual_row`:** rewritten for the amended FR-30. Joined words come from the same grouping as
  `PageView.texts`; the exception keeps a joined word as the amount when (a) its box lies wholly inside one amount
  column's span with no tolerance and (b) it is the row's only amount-shaped word centred in an amount column. S-flag's
  `1234567890` fails both; T's `12.34` passes and records 1234 with the description `SYNTH LONG DESCRIPTION`.
- **P18:** the reason-rejection now applies only when a joined word that would otherwise be an amount candidate fails the
  exception and leaves the row with no amount (contract G5). Plan-level fixture T-edge (`12.34` crossing the
  Description/Amount midpoint within `place`'s 20% allowance), with `pcheck_t_edge` and test `fr30_edge`, covers it.
  Earlier text saying T's row is rejected is gone.
- **P17, step 2's title-line note:** Q7 marked decided; `pcheck_title_lines` also covers T.
- **SL-01:** covers SC-27 and SC-28 (PDF-import side and module level) and G5. T is the contract's fixture, T-edge is
  beyond it. The gate command is `-k "pcheck or rows or sc27 or sc28 or fr30_edge"` (it was `fr30_tight`). T's P-check
  and `pcheck_t_edge` are added to the gate. SL-01 details gain the SC-28 and G5 bullets.
- **SL-02:** covers SC-28 (Record side); `sc28` added to its command.
- **SL-03:** `docs/documents.md` also describes D6's exception.
- **Coverage matrix:** FR-30 maps to SC-27, SC-28, SC-13 and `fr30_edge`. The footer says SC-01 – SC-28 and names the
  journey steps that carry SC-01 – SC-03, SC-05, SC-06 and SC-08 – SC-11.
- **R4:** the fallback is accepted with FR-27 unchanged (D6 Q7), and the gap is listed in `docs/open-work.md` "Money".
- **R6:** rewritten: what FR-30 changes in PDF import now (E1's rows read; a joined only-amount crossing its column's
  edge rejected with P18's reason).
- **Q7 and Q8:** moved from "Open question" to "Decisions the user settled after review pass 3 (D6)".
- **Review history:** one paragraph for D6.
- **Outside the plan:** `docs/open-work.md`'s Statement accounts entry now says the spec was approved on 2026-10-26
  (was "drafted …, awaiting approval").
