# Statement accounts: confirm before adding, delete, and rows from the rebuilt table — implementation plan
Spec: specs/statement-accounts/spec.md (with specs/statement-accounts/test-contract.md)
Spec sha256: 100a178661f78869d293313f792467d8945290f7f943977fb2cd4397afa11184
Review-Risk: HIGH
Review-Risk-Rationale: It changes which statement rows count as money and how amounts are read, adds a migration that
deletes rows from existing libraries, and adds a delete that removes ledger rows across many tables. A defect could
miscount household money or remove records the user wanted.

<!-- Approval lives in approvals/statement-accounts.json, bound to this file's hash. No Status line.
     Execution progress goes in plans/statement-accounts/progress.yaml, never in this file. -->

The spec has 30 FRs, more than plan-feature's guide of about 10. The spec bundle was approved as one feature, and
splitting it would need a spec change, so this plan keeps one feature in four milestones, as `account-import-pdf` did
(open question Q1). Each milestone can be verified on its own:
- **M1, rows from the printed columns:** SL-01 to SL-03 (FR-16 – FR-27, FR-29, FR-30).
- **M2, accounts wait for Confirm:** SL-04 and SL-05 (FR-01 – FR-08).
- **M3, deleting an account:** SL-06 (FR-09 – FR-15, FR-28; API and ledger).
- **M4, screens:** SL-07 (the UI parts of FR-02, FR-05, FR-09, FR-10, FR-13 and OD-5; SC-24 – SC-26).

M1 comes first because journey J1's final state expects the rebuilt amounts (36, 2, −38, 150000, −50000), not the
S-bad stub's.

**Spec amended (D5, user, 2026-10-26).** Review pass 1 found two contradictions inside the first approved bundle
(`733d7de7728f`). The user accepted the plan's defaults (Q1–Q6) and asked for the recommended amendments. The user
approved the amended bundle (`043927bcf806`) on 2026-10-26.
- **E1 → FR-30, SC-27.** On a page rebuilt from its words (no native table), `visual_row` (`pdf_import.py:229–242`)
  took the description's last word `1234567890` for an amount and rejected s1–s3.
  - The planner's probe on the contract's S geometry, with the page flagged: the word's box is 500–608 (preview units),
    centred at 554, inside the Amount span, which starts at 539.5.
  - The reader's own text grouping (`PageView.texts`) joins it to `… PPD ID`, in one run starting in the Description
    column.
  - The contrary cases print the number apart from the description. In `account-import-pdf` 7-e, `12345` is 100 pt from
    `B1 REF`. In this contract's x3, `REF 55.55` sits wholly in the Amount span.
  - FR-30 therefore makes a number that continues the description's joined run description text, and leaves every other
    placement as it was. A geometry-only rule (centre, or the heading's left edge) would have flipped 7-e.
- **E2 → SC-06, J1-a amended.** A re-read of a statement you confirmed is `kept_reviewed` (FR-26): one account, …3456,
  with its statement and rows, and no …7890 account (P16).
- **E3 → FR-20 amended.** The note for a model row that matches no rebuilt row is a record note, not a review reason
  (P13).

**Spec amended again (D6, user, 2026-10-26).** The user decided the plan's Q7 and Q8 after review pass 3 and approved
the amended bundle (`100a178661f7`) on 2026-10-26.
- **Q7 → fallback accepted, FR-27 unchanged.** A value line naming a balance printed directly above a transactions
  heading makes that table a balance table, and its page keeps the model's reading (R4, P20's note). The gap and its
  deferred fix are listed in `docs/open-work.md` "Money" (Statement accounts).
- **Q8 → FR-30 amended, SC-28 and fixture T added to the bundle.** A joined amount-shaped word stays the amount when its
  whole box lies inside one amount column's span (no tolerance) and it is the row's only amount-shaped word centred in
  an amount column. T's t1 (`09/22 SYNTH LONG DESCRIPTION 12.34`) records 1234, by Record and PDF import alike. P18's
  rejection is left only for a joined only-amount that crosses the column edge (contract gap G5), which a plan-level
  test covers (`fr30_edge`).

## Verified repository integration points

All paths are under `src/home_manager/` unless they start with `tests/` or `docs/`. Line numbers are from HEAD `05f9aa4`.

| Area | Where | What this plan uses |
|---|---|---|
| Account find/create | `finance/ledger.py:414–432` `account_in(db, …)`; `:444–456` `find_account` (institution NOCASE, types, last four) | `account_in` gains `origin=` (default `'user'`). `find_account` is unchanged and still finds unconfirmed accounts, so a second Record of the same account lands in it |
| Account lists | `ledger.py:503–505` `accounts()` (`SELECT * FROM accounts`, no filter). Reached by `FinanceTools.get_accounts` (`finance/tools.py:312`), the assistant (`tools.py:1242`), `GET /api/finance/accounts` (`app/api.py:920–923`, the Import dialog, `static/library.js:160`), the `get_accounts` tool route (`api.py:1071`; Accounts `accounts_v2.js:12`, Add transaction `money_v2.js:38`, Transactions filter, Month), Forecast `baseline()` (`forecast.py:287–319`), and through it Today's Cash and Net worth (`dashboard.py:112`), What If (`scenarios.py:138`) and the family view (`family.py:243,302,328`), plus search (`api.py:1867`) | One filter in `accounts()` covers every FR-02 surface except the three below |
| Lists outside `accounts()` | `ledger.py:1303–1312` `account_match` (`WHERE active=1 AND currency=?`, PDF import's last-four preselection); `finance/investments.py:603` (ledger accounts offered for linking) | Both gain the confirmed filter |
| Statement publish | `ledger.py:1065–1115` `publish_statement`: find or create the account, `_upsert` (`:594–609`, keeps user-decided records), remove earlier undecided rows not found again (`:1095–1108`), `insert_transactions` | Gains `origin=`, the FR-04 downgrade, FR-06 removal and `review_status` in its result |
| Review | `ledger.py:1509–1533` `review`: sets `review_source='user'`, cascades to undecided extraction rows, writes `review_events` | Unchanged. Confirmation is derived from its result (P1) |
| Undo of Confirm | `static/trace.js:524–566` `confirmCorrect`: Confirm posts `{status:"verified"}`; the toast's Undo posts `undoBody = {status:"needs_review"}` | FR-07 follows from P1 with no new endpoint |
| Automatic statements | `trace.js:536, 559–566`: a `verified`/`automatic` record shows only "Not right? Reject" | Gains the case of a statement whose account is unconfirmed (P4) |
| Reconcile | `finance/reconcile.py:491–496` `reconcile_statement` sets `reconciliation='reconciled'` (not on a rejected statement); `api.py:974` | Confirms the account through P1 |
| Family delivery | `finance/family_routing.py:329–377` `apply_delivery` calls `publish_statement(record, source, "verified")`, maybe sets `reconciled` | Passes `origin='family'` (P3) |
| Record path | `documents/extraction.py:3291–3330` `read` (adds `pdf_layout_review` notes at `:3296`, `anchor_rows`, then `missed_rows` `:2941–2979`); `:3370` `record`; `:3113–3198` `publish` → `normalize` (`:1745–1777`: rows to transactions, period check, `balance_taken`, arithmetic check when `len(transactions)==len(rows)`) → `ledger.publish_statement` (`:3193–3198`, returns `{**published, "review_status": status}`) | Rebuilt rows are merged in `normalize` (P6). Missed-row lines skip rebuilt pages. `review_status` is taken from the ledger's result |
| Model-facing pages | `documents/layout_context.py:12–15` `native_page` (excludes `overlapping_text`, `unsupported_text_rotation`, `unicode_mapping`, `degenerate_glyph`), `:43–45` `evidence_lines` | Unchanged: the model still sees what it sees today. The rebuild reads the saved layout itself |
| Row rebuild | `finance/pdf_import.py`: pure, no store or model (docstring `:1–8`). `structure` (`:339–417`), `analyze(result, *, tables, year, date_format, sign, account_type, currency)` (`:530–627`), `ImportRow` (`:66–84`), `read_shape` (`:422`), `read_date` year walk (`:465–501`), `read_amount` (`:503–521`), `BALANCE_NAMES` (`:30`), `assign` (`:180`; a Balance heading is never an amount), `PageView` (`:122–160`), `NO_LAYOUT` (`:36`), `SIGN_DEFAULTS` (`:33`) | Called as is, except FR-30's change to `visual_row` and `ANALYZER_VERSION=2` (see "FR-30 in `pdf_import.visual_row`"). Native rows carry `cell_ids` and `line_ids`; visual rows carry `word_ids` and `line_ids` (`:270, 305–306`) |
| Layout line ids | `documents/pdf_layout.py:327, 363, 486` (`page-N-layout-line-K`, `page-N-layout-word-K`); `pdf_reader.py:94` raw lines `page-N-line-K` | Every id the model or the rebuild cites starts `page-N-`, so a row's page is read from its ids |
| Provenance | `finance/provenance.py:43–79` `_extraction` (document lines from the evidence locator, `page_of(lines[0])`); `:99–104` the PDF-import shape `document {id, page, cells, lines}` | Extraction rows with a rebuilt locator report `page`, `lines` and `cells` (word or cell ids) |
| Highlight | `static/trace.js:437–462` `showPage` highlights words whose id is in `?lines=`, and the words of wanted lines and cells | A rebuilt row's link names its layout line ids and word ids |
| Document page step | `static/document_v2.js:268–313` `doc2Steps`, `:340–356` (latest extraction run's `publication` → `doc2Ledger`); `documents/extraction.py:2807` `get` loads `publication_json` | `get` adds `publication.removed` when the record is gone (P11) |
| Library status | `library/storage.py:584–592` `ledger_status`: statements by `blob_hash`, else `'imported'` from `transaction_imports` | Becomes NULL after delete with no change, so the library offers Record or Import again |
| Schema | Migration runner `library/storage.py:98–160`: SQL scripts only, foreign keys OFF while scripts run, a step that adds broken references is rolled back. Latest is `072_pdf_import_index.sql`. `accounts` (`050_strict_tables.sql:18–33`) has `active` and no origin | Migration 073 |
| Connections | `storage.py:271–281`: each `connection()` is one transaction with `PRAGMA foreign_keys=ON` | Delete and FR-06 removal run in one connection. With foreign keys on, the account row can only go after its children, so it is the last step (the SC-11 trigger fires there) |
| References (FR-11) | Direct: `statements.account_id`, `transactions.account_id`/`statement_id`/`replaced_by`, `transaction_imports.account_id`, `category_rules.account_id`, `recurring_obligations.account_id` (no ON DELETE); `tax_rules.account_id` CASCADE; `investment_accounts.ledger_account_id` SET NULL; `transaction_links` from/to, `transaction_receipt_links.transaction_id` (no ON DELETE); `transaction_income_links`, `category_splits`, `tax_tags`, `investment_payment_rejections` CASCADE; `investment_events.transaction_id` SET NULL. Typed (no FK): `financial_evidence_links`, `review_events`, `reconciliation_issues`, `record_corrections`, `family_corrections`, `family_assignments` (statement), `donation_checks` (statement). JSON: `reconciliation_issues.detail_json` `candidate_transaction_ids` (`reconcile.py:240`) | The delete order in "Delete" below |
| No `bills` table | `067_bills_as_receipts.sql` drops `bills`; a bill is a receipt, and a recurring bill is `recurring_obligations.kind='bill'` (`050:1098`) | "Bills tied to it" (FR-10, FR-11, SC-08) means `recurring_obligations` rows of kind `bill` (spec note N1) |
| Family copies | Members send a sealed copy of their **whole** database (`app/family_sync.py:225` `seal_copy`; `family_client.py:112`), resealed when the database file changed since the last publish (`family_sync.py:279–284` `changed_since`; `manager.py:750–764`). `record_shares` holds receipts only (`050:1068`, `067:57`). Statements are routed whole to one member (`family_routing.py` `assign`; `tests/test_family_routing.py:81`) | U1 resolution (P9) |
| UI | `static/accounts_v2.js:11–68` (groups, Rename hidden in `familyMode`); `static/ui.js:417` `confirmAction` (the shared confirm dialog, title/message/label only); `static/index.html:1084` `#confirm-dialog`; `static/review_v2.js:139, 273, 340`; `static/document_v2.js:376, 416` | SL-07 |
| Test helpers | `tests/test_pdf.py:17` `make_pdf` (text matrix fixed at `1 0 0 1 x y Tm`, `:45`); `tests/pdf_import_fixtures.py` (`read_pdf`, footer rule); `tests/test_layout_consumers.py:125–140` (Record of a real PDF reading through `ExtractionService`); `tests/model_server.py:96–99` `by_schema`; `tests/conftest.py:34` `assert_ledger_healthy`, `:116` `local_model`, `--browser`; `tests/test_pdf_imports.py:34–56` `no_network`, `:2056–2066` (layout set to None) | Reused. `make_pdf` gains a per-item text matrix (SL-01) |

**Verified facts that shaped the design:**
- **Record can't tell a statement it created from one you made, so a stored origin is needed.** FR-08 confirms an account
  "you created", and FR-04 keeps the automatic check for statements into a confirmed account, including one you made
  yourself. Nothing in `accounts` records who made it.
- **An empty account left by a re-read has a trace.** `extraction_runs.publication_json` keeps the published
  `{record_type, id, account_id, …}` (`ledger.py:611–612`, `extraction.py:3260`). This is how migration 073 tells
  FR-08's (b) from (d).
- **`analyze` with `year=None` leaves year-less rows unrejected,** with `posted_date=None` (`read_date` returns
  `(None, None)`, `pdf_import.py:487–489`). Its year walk is order dependent, and FR-19's rule is not, so the year is
  resolved outside `analyze` from the printed date (`read_shape`).
- **PDF import's page issues include wording that is wrong for Record** ("Use Record for scanned statements",
  `pdf_import.py:345`). Record keeps only the issue codes it maps (P7).
- **Today no code resolves a statement's years.** The model is told to (`extraction.py:900`), and `normalize` accepts
  ISO dates only. FR-19 is new code.
- **`make_pdf` can't draw rotated text.** S-flag needs `unsupported_text_rotation`. The contract allows another real
  trigger, but a rotated title word is simple to add as a per-item text matrix.

## Architecture, contracts, data flow and decisions

### Data flow (Record of a statement PDF)
1. `ExtractionService.read` runs as today: classify, summary, the model's `Transactions` rows, `anchor_rows` on native
   tables.
2. **New:** for a bank or card statement whose evidence is a `PDFResult` (has `pages`),
   `statement_rows.rebuilt_pages(evidence)` gives the pages with rebuilt rows. `missed_rows` gets only the lines of the
   other pages, so it asks nothing about rebuilt pages and leaves no "printed line(s) … aren't in the transactions" note
   for them. The reading keeps `evidence` for step 3.
3. `publish` resolves the currency (`currency_for`, as today). For a statement with a `PDFResult` it then calls
   `statement_rows.rebuild(evidence, statement_type=…, period_start=…, period_end=…, currency=…)`, using the header's
   period fields read the way `normalize` reads them (`iso_date` of a `proposed` value).
4. `normalize(…, rebuild=…)` builds `record["transactions"]` from the rebuilt rows plus the model's rows on other pages
   (P6), and adds the rebuild's issues.
5. `publish_statement` publishes. For an unconfirmed account it downgrades `verified` to `proposed` (FR-04), and returns
   the status it used.

### New module `finance/statement_rows.py` (pure, deterministic)
Beside `pdf_import.py`, because it applies that module's row rules. No store, no model, no network. It imports only from
`pdf_import`, `core.money` and the standard library.

```python
@dataclass
class Rebuild:
    available: bool          # False: no layout (FR-23), or the rebuild failed (P8); pages is then empty
    pages: set[int]          # rebuilt pages (spec term): at least one rebuilt row, recorded or rejected
    rows: list[dict]         # transactions in normalize's shape, in printed order, for recorded rows only
    issues: list[str]        # review reasons: rejected rows, missing years, duplicates, second headings, a failed rebuild
    notes: list[str]         # record notes, not review reasons: the FR-23 no-layout note

def rebuilt_pages(result) -> set[int]
def rebuild(result, *, statement_type, period_start, period_end, currency) -> Rebuild
```

Each row is `{"posted_date", "transaction_date": None, "description", "currency", "amount_minor", "locator"}`, and the
locator is `{"rebuilt": True, "page", "table_id", "row", "line_ids", "word_ids", "cell_ids", "quotes": [printed line text]}`.
`insert_transactions` truncates the description to 500 characters, as today.

**Steps of `rebuild`:**
1. **No layout.** If any `embedded_text` page has no layout, return `available=False` with the note
   `Read this document again to take its rows from the printed columns.` (FR-23).
2. **Tables (FR-27).** Call `pdf_import.analyze(result, year=None, sign=…, currency=…)` once to list the tables. A table
   is a **balance table** when either of these names a balance: its title line (the visual row directly above its
   heading, found with `PageView` from the table's top baseline), or a heading text that `assign` didn't already take as
   the Balance column. "Names a balance" means it contains, lower-cased, one of `BALANCE_NAMES`, `daily ending balance`
   or `daily balance`. The S heading's `Balance` column is the Balance column, not a table naming a balance, so S is
   kept (P10). Call `analyze` again with `tables=` set to every selectable table that isn't a balance table, so a
   balance table's rows are never read and its chain is never followed.
   - **Note when a title excludes a transactions-shaped table (pass 3 minor, P20).** When a table is a balance table
     only because of its title line, and its heading has Description and Amount (or Debit/Credit) columns, `rebuild`
     adds the record note (not a review reason)
     `Page {p}: the line above the table headed "{heading}" names a balance, so its rows were taken from the reading, not the printed columns; check them.`
     D's daily table (Date | Amount) gives no note.
   - A continuation whose parent is a balance table is dropped with it. Its page then has no rebuilt rows and keeps the
     model's reading (FR-23).
   - **Section cut (pass 1 B2).** On a page with no native table, `analyze` reads every visual row from the heading to
     the page end under the first heading's columns, so a daily balance section below would become rows of the
     transactions table. `statement_rows` therefore ends a rebuilt or continuation table at the first visual row after
     its heading that is a balance title or a transactions heading. A **balance title** here is a row that names a
     balance *and* sits directly above a heading (the next visual row is a heading by `is_heading`); a row that merely
     contains `balance`, such as a `BALANCE TRANSFER` description or a `Beginning Balance` line under the heading,
     never cuts the table (pass 3 minor). A `rows_*` test on S-flag with both such rows asserts the table isn't cut. The table's rows at or after that visual
     row are dropped, recorded or rejected, located through `PageView.row_of` of their `word_ids`. Native tables need no
     cut, because the reader already ends them.
     - A section after the cut that has its own heading and isn't a balance section isn't read (as PDF import's
       `second_heading`). It gives the step 7 issue.
     - A continuation page after a cut continues nothing, so it keeps the model's reading.
   - Variant **D-flag** (D drawn on S-flag's page, contract SC-21) is tested in `tests/test_statement_rebuild.py`. It
     asserts only s1–s5 are recorded and no issue comes from the daily rows.
   - **Title lines of the fixtures (pass 2 M1).** FR-27 takes the title line as the visual row directly above the
     heading, however far above it sits, and "names a balance" is a lower-cased *contains* of `BALANCE_NAMES`, which
     includes `balance` (`pdf_import.py:30`). The contract lists S's lines above the table ending with
     `Ending Balance 1,000.00`, and C's ending with `New Balance 108.19`. Printed in that order, those lines would be the
     title lines, and S's and C's transactions tables would be balance tables with no rows rebuilt. The fixture builders
     therefore print the same lines (none added or removed) in an order where the row directly above every transactions
     heading names no balance: S, S-flag and S2 print `Statement period …` last; C prints `Statement period …` last;
     C0, which prints no period, prints `Card number XXXX7700` last; W, D, X, Q and M follow the same rule. D's
     `DAILY ENDING BALANCE` stays directly above the daily table's heading, as SC-21 needs. This is a deviation from
     the contract's listed order that changes no expected value (Q7, decided in D6: FR-27 unchanged). SL-01 P-check
     `pcheck_title_lines` asserts the title line of every transactions table in S, S-flag, S2, W, C, C0, T, X, Q and M
     names no balance, and that D's daily table's title does.
3. **Sign (FR-18).** `sign="positive_is_outflow"` for a card statement and `"negative_is_outflow"` for a bank
   statement, always passed explicitly. Debit and Credit columns keep their own sign inside `read_amount`.
4. **Date order.** If `analyze` decides the order (a day over 12), use it. If it can't (every day and month ≤ 12), take
   the order under which every dated row falls inside the printed period ±7 days, the tolerance `normalize` already
   uses (`extraction.py:1759`). If neither or both orders fit, the slash-dated rows aren't recorded, and the issue
   `Page N rows: the date order (month/day or day/month) can't be told from the printed dates.` is added (P12).
5. **Year (FR-19).** For a row whose printed date has no year or a two-digit year (from `read_shape`):
   - With no printed period (`period_start` or `period_end` missing), the row isn't recorded. Issue:
     `Page {p} row {r}: no year is printed and the statement period wasn't read, so the date {date} can't be placed.`
   - Otherwise the year is the period's start year when start and end years are equal. Across a year end, it is the
     end year for a month earlier than the start month, and the start year for any other month.
   - A two-digit year that disagrees with that year is rejected:
     `Page {p} row {r}: the printed year in "{date}" disagrees with the statement period.`
   - An impossible date in that year (02/29 in a non-leap year) is rejected with PDF import's wording
     `The date "{date}" is not a real date.`
6. **Rejections (FR-21).** Every row `analyze` rejects becomes the issue `analyze` wrote (`Page {p} row {r}: {reason}`,
   `pdf_import.py:607`), in PDF import's words. It isn't recorded.
7. **Page issues kept.** `second_heading` on a rebuilt page becomes
   `Page {p}: rows after a second transactions heading on this page weren't read; check them against the statement.`
   It does not arise when the second heading belongs to a balance table (its title or heading names a balance), since
   those rows are never transactions (pass 1 minor).
   `scanned_page`, `no_table`, `no_rows` and `unassigned_column` are dropped (they're PDF-import guidance). Layout flags
   are not repeated: `read` already adds the reader's `pdf_layout_review` note (FR-22).
   - A `document_currency_mismatch` blocks the rows: none is recorded and its message is an issue.
8. **Duplicates (FR-29).** Two recorded rows with equal (`posted_date`, `amount_minor`, description with whitespace
   collapsed and case folded) on different pages, or in different tables, give one issue per pair:
   `The same row is printed twice: {date} {description} {amount} on page {p1} (row {r1}) and page {p2} (row {r2}). Both were recorded; check whether it is one payment.`
   Both stay, and their ordinals keep their fingerprints apart.
9. **Pages.** A rebuilt page is any page with a row in the selected tables, recorded or rejected. Rows are in page
   order, then in `analyze`'s order.

`rebuilt_pages(result)` runs steps 1, 2 and 9 with `currency="USD"`. The pages don't depend on the currency: the
currency only decides which rows are rejected, and rejected rows still make a page rebuilt. This lets `read` skip those
pages before the currency is known. `read` catches any exception from it as P8 does: no page counts as rebuilt, and the
issue is added once (pass 1 minor).

The locator's `quotes` holds one entry per line id, the text of that layout line. `provenance._extraction` zips
`line_ids` with `quotes` (`provenance.py:64`), so a shorter list would drop lines (pass 1 minor).

### FR-30 in `pdf_import.visual_row` (shared with PDF import)
FR-30 (as amended by D6 Q8) is the one change to `finance/pdf_import.py`. It happens before the candidate and fit
checks in `visual_row`:
1. Group the row's words as `PageView.texts(index)` does: a word closer than 1.5 font sizes to the one before joins its
   text. (`texts` returns strings; `visual_row` needs the words, so the grouping is shared through a helper that
   `texts` also uses, with no change to `texts`' result.)
2. In a text whose **first** word is placed (`place`) in the Description column, every later amount-shaped word is a
   **joined** word.
3. **Exception (FR-30 (a) and (b)).** A joined word stays an amount candidate when both hold:
   - (a) its whole box lies inside one amount column's span (Amount, Debit or Credit; `Spec.spans`), with no tolerance:
     `left <= box[0]` and `box[2] <= right`, not `place`'s 20% allowance;
   - (b) it is the only amount-shaped word in the row whose centre is in an amount column's span. A Balance column
     isn't an amount column.
4. Every other joined word is description text. It is left out of `amounts`, it is put in the description's cell
   whatever span its centre is in, and the fit check ignores it.

Only a row with a `description` role is affected, and only words joined to description text. A number printed apart
(7-e, x3) is still an amount candidate and is still rejected. How the fixtures fall:
- S-flag's `1234567890` (box 500–608 in preview units; the Amount span starts at 539.5) fails (a), and with `0.36` also centred in the
  Amount column it fails (b). It is description text, and s1–s3 record 36, 2 and −38 with their full descriptions.
- T's t1 `12.34` is joined to `SYNTH LONG DESCRIPTION`, lies wholly in the Amount span and is the row's only amount, so
  it stays the amount: 2026-09-22, 1234, description `SYNTH LONG DESCRIPTION` with no number (SC-28).
5. **No silent loss (pass 2 M3, P18; covers contract gap G5).** When a joined word fails the exception, the row can be
   left with a date and no amount. `visual_row` would then return `None` (`pdf_import.py:250–251`) and `structure`
   would skip it with no issue (`:369–370`, `:383–384`, and the continuation path `:397–398`). So when FR-30 has taken
   a word that would otherwise be an amount candidate (it `touches` an amount column's span, centred in it or
   straddling into it), and the row has a date and no amount candidate left,
   `visual_row` rejects the row with the reason `The amount is printed against the description, so it can't be told apart from it.`
   It isn't dropped silently: PDF import lists it as rejected, and Record turns it into an issue (step 6 of `rebuild`,
   FR-21). Under the amended FR-30 this arises only for a joined only-amount that crosses an amount column's edge (fails
   (a), including one centred in the Description column that straddles into an amount column, which today is rejected
   too), or for several joined amount-shaped words centred in amount columns (fails (b)). The spec doesn't say how such a
   row is shown (G5); this plan keeps the reason-rejection.
   - **Plan-level fixture T-edge (beyond the contract, G5).** T with t1's `12.34` moved left so that its box starts
     left of the Description/Amount midpoint by less than 20% of its width, its centre stays in the Amount span, and the
     gap to `DESCRIPTION` stays under 1.5 font sizes. Today's `place` says it fits (the 20% allowance), so the row would
     be read; under FR-30 it fails (a). A P-check `pcheck_t_edge` asserts those four placements. Test `fr30_edge`
     asserts that `analyze` rejects t1 with P18's reason and doesn't record it, that `rebuild` gives one issue
     `Page 1 row {r}: The amount is printed against the description, …` for it, and that s1–s5 are unchanged.
- `ANALYZER_VERSION` goes to 2, because what the analyzer finds changes for such rows. Every PDF reading is indexed
  again at the next start (`pdf_import.py:29`).
- Native tables are untouched, because the reader built their cells.
- **Regression gate:** the whole `tests/test_pdf_imports.py` passes unchanged, including 7-d and 7-e.

### `read` on rebuilt pages (pass 1 B3)
Today, `read` adds notes about the model's rows on native tables, and each note sends the statement to review:
- `anchor_rows` adds "A statement amount has no debit/credit column; check its direction." per row
  (`native_values.py:113–116`), and an "unresolved required amount" note.
- The coverage block adds "Several extracted records cite the same native table row" and "N native table row(s) were not
  accounted for" (`extraction.py:3330–3344`).

On rebuilt pages the model's rows decide nothing, so these notes are noise there:
- For a statement with rebuilt pages, `anchor_rows` gets only the tables and model rows of the other pages. The
  rebuilt-page model rows are kept unanchored, for FR-20's matching only.
- The coverage block counts only tables on the other pages.
- `anchor_summary` is unchanged: the summary values are still anchored on every page.

### `normalize` with a rebuild (P6)
`normalize(kind, header, rows, currency, lines, …, rebuild=None)`. For a statement with `rebuild.available`:
- **A model row's page** is the set of `page-N-` prefixes of its cited line ids. A model row citing any line on a
  rebuilt page is a **rebuilt-page model row**. It adds no transaction, and its date, amount and direction are never used
  for a recorded row.
- **Matching (FR-20).** Rebuilt-page model rows are matched one-to-one to recorded rebuilt rows of the same page by
  (`posted_date`, signed `amount_minor`), with the model row's date and amount read by today's rules, in printed order
  (multiset matching).
  - A rebuilt-page model row that matches none becomes the **record note** (P13, E3)
    `The reading listed a row the printed columns don't have, on page {p}: {date} {description} {amount} ({money in|money out}). It wasn't recorded.`
    (contract G2: it quotes date, description and amount). It is shown on the record, not a review reason.
  - A model row with no usable date or amount on a rebuilt page gives the same note, with the text as given.
  - A rebuilt row the model didn't list is still recorded.
- **Other model rows** go through today's code unchanged: date, period check, `balance_taken`, the "no unambiguous date"
  issue.
- **Order.** `record["transactions"]` is the rebuilt rows and the other model rows merged by page. Within a page the
  source keeps its order. Fingerprint ordinals follow this order, the same for the same reading (FR-26).
- **Period check.** The "dated outside the statement period" check also runs on rebuilt rows.
- **Arithmetic check (FR-25).** The condition `len(transactions) == len(rows)` becomes "no row was dropped". That means
  no model row on other pages was dropped, and the rebuild rejected no row and left out no row for a missing year or
  order. The formula is unchanged.
- `rebuild.issues` are added to `issues`. `rebuild.notes` and the FR-20 notes go to `record_notes`.
- **Where record notes are kept (pass 2 M2).** Today `record["notes"]` (`extraction.py:3166–3167`) reaches only the
  extraction run's `result_json`. `publish_statement` stores `validation_json`, `summary_json` and `details_json`
  (`ledger.py:1085–1093`), and `Ledger.record` returns only those (`:1535–1552`), so a statement's notes would never be
  shown. For a statement, `publish` therefore also writes the notes to `record["details"]["notes"]` (creating
  `details` if the summary check left none), the pattern bills already use (`extraction.py:2196–2198`). `Ledger.record`
  returns them through `shown_details`, which passes strings through (`ledger.py:217–223`). The Printed details list
  skips keys without a label (`document_v2.js:593–594`), so `notes` isn't shown as a field. SL-07 shows the notes
  under the statement's fields as bills do (`document_v2.js:549–554`), and leaves `notes` out of `doc2DetailList`'s
  emptiness check (`:589–590`), so a statement whose details hold only notes shows no empty "Printed details" section. The SC-13, SC-16 and SC-18 tests read the notes
  from `GET /api/finance/records/statement/{id}` (`api.py:1080`), not from the run's result.

When `rebuild` is None or `available=False`, `normalize` behaves exactly as today. When the reading has no layout,
`publish` adds the note.

### Account confirmation (P1 to P5)
- **P1, confirmation is derived.** The predicate is defined once in `ledger.py`:
  ```python
  CONFIRMED = ("(a.origin<>'record' OR EXISTS(SELECT 1 FROM transaction_imports i WHERE i.account_id=a.id) "
               "OR EXISTS(SELECT 1 FROM statements s WHERE s.account_id=a.id AND "
               "(s.review_status='verified' AND s.review_source='user' OR s.reconciliation='reconciled')))")
  ```
  Confirm sets `verified`/`user`, so the account shows at once (FR-03). Undo sets `needs_review`, so it is unconfirmed
  again unless another statement, an import or a reconcile confirms it (FR-07, OD-1). Reject doesn't confirm. No
  separate state can drift (spec "Errors": "without separate state that could drift").
  - Consequence: if you later reject the only statement you confirmed, the account goes back to "Waiting for confirm".
    Its rows are rejected and count for nothing either way (Q3).
- **P2, origin.** `accounts.origin TEXT NOT NULL DEFAULT 'user' CHECK (origin IN ('user','record','family'))`:
  - `account_in(…, origin='user')` is the default. `POST /api/finance/accounts`, the import dialog's New account and PDF
    import's new account keep it (FR-01).
  - When `account_in` with `origin='user'` finds an existing `record` account (same identity), it sets that account's
    origin to `user`. Adding by hand an account that waits for Confirm therefore confirms it, rather than returning a
    hidden account (pass 1 M1).
  - `publish_statement(record, source, status, origin='user')` keeps `user` as its default, so the about 28 direct ledger
    calls in tests keep today's behavior. **Only `ExtractionService.publish` passes `origin='record'`** (pass 1 M3).
- **P3, family deliveries.** `apply_delivery` passes `origin='family'`, so an account a family delivery creates is
  confirmed. The family confirmed the record (`family_routing.py:331`, "counted, since the family confirmed it"), and
  the statement isn't downgraded. Migration 073 treats accounts whose statements cite a `family:` source the same way.
- **P4, Confirm on old automatic statements.** After the upgrade, an FR-08 (a) account's statement is still
  `verified`/`automatic`, which today offers only "Not right? Reject". `Ledger.record` adds `account_confirmed` to a
  statement. `confirmCorrect` gains `awaitingAccount`, which offers Confirm and Reject as for `proposed`. The
  statement's stored status isn't rewritten.
- **P5, where unconfirmed accounts are hidden.** In `Ledger.accounts()` (`WHERE {CONFIRMED}` with alias `a`),
  `account_match`, and `investments.py:603`. Three readers outside `accounts()` also gain the filter (pass 1 M2):
  - `FinanceTools._coverage` (`tools.py:559–563`), which feeds Spending and `get_spending`.
  - `member_facts` (`family_routing.py:53`).
  - `family_sync._joint_accounts` (`app/family_sync.py:684–697`). Without the filter, an unconfirmed account in one
    member's copy would "own" a shared identity and reject the other member's real transactions in the family view. New `Ledger.waiting_accounts()` lists the others for the "Waiting for
  confirm" group (OD-5), at `GET /api/finance/accounts/waiting`. It is kept out of `get_accounts`, so the assistant
  never sees them (FR-02).
  - `add_manual_transaction` into an unconfirmed account is refused:
    `This account waits for you to confirm its statement.` The pickers don't offer it, so only a crafted request
    reaches this.
  - Imports by `account_id` into an unconfirmed account are accepted. They confirm it (FR-03, SC-04).
  - `find_account` is unchanged, so Record and family sync still find the account.

### Record into an unconfirmed account (FR-04 – FR-06)
- **P16, the account is created only when the statement is written (pass 1 B4).** Today `account_in` creates the
  account before `_upsert` decides to keep a reviewed statement (`ledger.py:1073, 1088`). A re-read of a confirmed
  statement with a changed last four would therefore leave a new empty account.
  - `publish_statement` first reads the existing statement by `blob_hash`. If you decided it (`verified` or `rejected`,
    `user`), it returns `kept_reviewed` with the existing account, before any account lookup or creation.
  - Otherwise it proceeds as below.
- **P15, Undo restores the rows (pass 1 B4).** Today `review` cascades only `verified` and `rejected` to a statement's
  undecided extraction rows (`ledger.py:1520–1524`). Undo (`needs_review`) leaves the rows `verified`/`user`, so a
  re-read keeps them in the old account (`ledger.py:1096–1099`).
  - With this change, when you set a statement to `needs_review`, its extraction rows that are `verified` or
    `rejected`/`user` and have no `review_events` row of their own go back to `needs_review`, with `review_source` NULL.
    Rows you reviewed one by one have their own `review_events` row and keep their decision.
  - This puts things back as they were (OD-1's rationale), and it makes J1 step 4 reach one account and 5 transactions.
- **FR-04.** In `publish_statement`, after the account is found or created and before `_upsert`: if the account isn't
  confirmed (the predicate evaluated in the same transaction), `origin` isn't `family` (pass 1 minor), and
  `status == 'verified'`, then `status = 'proposed'`.
  - `Ledger.correct`'s automatic promotion to `verified`/`automatic` (`ledger.py:2009–2011`) also stays at `proposed`
    for a statement whose account is unconfirmed, so a correction doesn't skip the wait (pass 1 minor).
  The rows are inserted with the same status, as today. The result gains `review_status` and `account_confirmed`.
  `ExtractionService.publish` returns `published["review_status"]` instead of its own `status`.
  - A later statement into an account that is now confirmed keeps `verified`/`automatic` (J1-b).
- **FR-05.** `Ledger.record("statement", id)` adds `account_confirmed` and, when it's false,
  `account_note = "New account: {display_name} — added to Accounts when you confirm this statement."` The document page
  and Review show it (SL-07). The API test reads it from `GET /api/finance/records/statement/{id}`.
- **FR-06.** `publish_statement` reads the statement's current `account_id` by `blob_hash` before `_upsert`. After the
  rows are moved, it calls `self.remove_if_empty(db, old_id)` when the old account is different. That removes the old
  account when it is unconfirmed and has no statement, transaction or import record, using the shared account removal
  (below), in the same connection and transaction. A confirmed account is never removed.
  - If a row you worked on was kept in the old account, the account isn't empty, so it stays.

### Delete (FR-09 – FR-15, FR-28)
**Ledger** (`finance/ledger.py`):
- `delete_preview(account_id)` → `{account, counts, family, token}`.
  - `counts` holds statements, transactions, import records, matched receipts (verified or proposed links), matched pay
    stubs, transfer links, recurring payments, recurring bills (`kind='bill'`) and category rules.
  - `family` is filled in by the manager (P9).
  - `token` is a sha256 of the canonical JSON of the counts plus the sorted `(id, updated_at)` of the account's
    statements and transactions and the sorted ids of its import records. A statement recorded, a re-read or an import
    in between changes it (FR-14, contract G4).
- `delete_account(account_id, token)`: `BEGIN IMMEDIATE`, recompute the token, and on mismatch raise
  `AccountChanged("This account changed since you opened Delete; check the counts again.")`. Then `_remove_account(db, id)`.
- `_remove_account(db, account_id)`, shared with FR-06's `remove_if_empty`. With S its statement ids, T its transaction
  ids and I its import ids, the deletes run in this order, with the account row last:
  1. Rows of T: `transaction_receipt_links`, `transaction_income_links`, `transaction_links` (either side; the other
     account's transaction stays), `category_splits`, `tax_tags`, `investment_payment_rejections`.
     `investment_events.transaction_id` is set NULL.
  2. `UPDATE transactions SET replaced_by=NULL` where it points into T from another account (R2).
  3. Typed rows for (`transaction`, T) and (`statement`, S): `financial_evidence_links`, `review_events`,
     `reconciliation_issues`, `record_corrections`, `family_corrections`, `family_assignments`, `donation_checks`.
  4. Open `reconciliation_issues` whose `candidate_transaction_ids` include an id in T are deleted. They are machine
     questions, and the reconciliation run after commit asks again where it's still ambiguous.
  5. `transactions` (T), `statements` (S), `transaction_imports` (I).
  6. `category_rules` and `tax_rules` for the account are deleted. `recurring_obligations.account_id` and
     `investment_accounts.ledger_account_id` are set NULL (OD-4).
  7. The `accounts` row.
- FR-12 needs no extra step. `STANDALONE_RECEIPT` and `STANDALONE_INCOME` (`ledger.py:56–63`) count a receipt or pay
  stub on its own once no unrejected link to an unrejected transaction exists.

**Manager** (`app/manager.py`):
- `delete_preview` adds `family` (P9).
- `delete_account` checks `self.require(False)` under `self.mutex`, as `import_transactions` does
  (`manager.py:1443–1448`). Like the import, the work itself then runs outside the mutex. It refuses only while
  non-inference work is already running. The real guards against a concurrent Record or import are `BEGIN IMMEDIATE`
  and the token (pass 1 minor). After commit it runs `self.reconciler.run("import")`.

**API** (`app/api.py`, additive):
- `GET /api/finance/accounts/{id}/delete-preview` → the preview.
- `POST /api/finance/accounts/{id}/delete` with strict body `{"token": str}`. It returns
  `{"deleted": id, "counts": {…}}`, or 409 with the FR-14 message. A missing account is 404. An injected SQLite error is
  a 500 with the app's generic message and no traceback (SC-11).
- `GET /api/finance/accounts/waiting`.
- POST rather than DELETE with a body, because the token travels in the body.

**Documents (FR-13).** Nothing under the library, blobs or reading folders is touched.
- `ExtractionService.get` (`extraction.py:2807`) adds `publication["removed"] = True` when a published statement's
  record no longer exists.
- `doc2Steps` treats a removed publication like no extraction: it offers "Record it" (`doc2Record(true)`).
- The library's `ledger_status` goes NULL with no change, so Record (statement) and Import (CSV/XLSX/PDF) are offered
  again.

### Migration 073 (`library/migrations/073_statement_accounts.sql`, FR-08)
One script, one transaction (the runner's), foreign keys off as the runner sets them:
1. `ALTER TABLE accounts ADD COLUMN origin …` (P2).
2. `-- sort:` marker. This is a comment only; the runner knows nothing of it. The statements after it are idempotent.
   SC-07's test reads the script file, splits it at the marker, and executes the part after it a second time with
   `executescript`, then asserts equality row by row. It also asserts that reopening the store is a no-op upgrade.
   - The predicate is stated twice, in SQL here and as `ledger.CONFIRMED`. A test asserts that both give the same set
     on the SC-07 fixture and on J1's states (pass 1 minor).
3. Set `origin='record'` for accounts with a statement, an `origin='extraction'` transaction, or an extraction run whose
   `publication_json` names them (`json_extract(…,'$.record_type')='statement' AND json_extract(…,'$.account_id')=id`).
4. Set `origin='family'` for accounts with a statement whose evidence has `source_key LIKE 'family:%'`.
5. In a temp table `removed`: accounts with `origin='record'`, not confirmed by the P1 predicate, and with no statement,
   no transaction and no import record.
6. For `removed`: delete `category_rules` and `tax_rules`, set `recurring_obligations.account_id` and
   `investment_accounts.ledger_account_id` NULL, then delete the accounts. Foreign keys are off in migrations, so
   cascades don't fire and every step is explicit. The runner's `reference_problems` check rolls back a missed
   reference.
7. `PRAGMA user_version=73;`

Results for the contract's fixtures:
- (a) automatic statement only → `record`, unconfirmed.
- (b) empty, named in a publication → removed.
- (c) import → confirmed.
- (d) hand-made, never published into → `user`.
- (e) user-confirmed statement → confirmed.
- (f) reconciled → confirmed.

A hand-made account that a statement was once recorded into and then moved out of is removed by step 5 when it is
empty. This is FR-08's "(b)", and recording again recreates it (R1).

### UI (SL-07)
Before changing any page, use the `ui-ux-pro-max` skill and `design-system/home-manager/MASTER.md` (CLAUDE.md), within
`docs/ui.md` "Screen rules": counts come from the server, no CDN, no framework.
- **Accounts tab** (`accounts_v2.js`):
  - Each row gains **Delete…** beside Rename (hidden in `familyMode`, as Rename is), with `aria-label="Delete {name}…"`.
  - A collapsed `<details>` group "Waiting for confirm" at the bottom lists `GET …/accounts/waiting` (OD-5). Each entry
    links to its statement's document and offers Delete….
- **Delete dialog:** a new `<dialog id="account-delete-dialog">` in `index.html`. `confirmAction` takes a message
  string only, and the counts need a list.
  - It shows the account name, the counts list (only the non-zero lines after statements, transactions and import
    records), the family line (P9), the sentences "The documents stay in your library; you can record or import them
    again." and "This can't be undone.", and Cancel and **Delete account** (danger, the second click).
  - Focus starts on Cancel and returns to the opener on close.
  - A 409 shows the server message, and the dialog then reloads the preview.
- **Document page and Review:** the statement's record shows `account_note`, with a **Delete account** link-button that
  opens the same dialog (OD-5).
- **Confirm:** `confirmCorrect(…, awaitingAccount)` (P4).
- **Record again:** `doc2Steps` treats `publication.removed` as "Record it" (FR-13).

### Decisions this plan makes (none changes the spec; listed for plan approval)
- **P1** Confirmation is a derived predicate, not a stored flag.
- **P2** `accounts.origin` (`user`, `record`, `family`).
- **P3** Family-delivered statements' accounts are confirmed.
- **P4** Confirm is offered on automatic statements of unconfirmed accounts. The stored status isn't rewritten.
- **P5** The hidden surfaces and the waiting list endpoint. A manual add into an unconfirmed account is refused.
- **P6** Rebuilt rows are merged in `normalize`, and model rows on rebuilt pages only produce notes.
- **P7** PDF import's issues are kept only where they mean something to Record, in Record's words.
- **P8** A rebuild that raises (a malformed saved layout, or a `PDFImportError` over a limit) falls back to the model's
  reading for **all** pages, with the issue
  `The rows couldn't be rebuilt from the printed columns, so the reading's rows were used; check them.` The amended spec's
  error rule says every page (Q4). `analyze` reads continuation chains across pages, so one page can't be isolated.
- **P9** U1 resolution (FR-28): which family rows a delete reaches, and what the dialog counts. See "Privacy/security".
- **P10** FR-27's "heading names a balance" excludes the column `assign` already treats as Balance (Q2).
- **P11** A removed publication is detected when it's read. `extraction_runs` isn't rewritten.
- **P12** Ambiguous date order is decided by the printed period, else the rows wait in review.
- **P13** FR-20's notes are record notes, not review reasons, as J1 step 1 (`proposed`) and SC-16 require (E3). FR-29's
  note is a review reason (SC-23).
- **P15** Setting a statement back to `needs_review` returns the rows its decision cascaded.
- **P16** No account is created for a statement that will be kept as you reviewed it.
- **P14** The no-layout note (FR-23) is a record note, not a review reason, so such a reading records "as today".
- **P17** The fixture builders print the contract's lines above each table in an order whose last line names no
  balance, so FR-27's title rule doesn't exclude the fixtures' transactions tables (pass 2 M1; Q7 decided in D6).
- **P18** A row that FR-30 leaves with a date but no amount, because a joined amount-shaped word in or straddling an
  amount column failed FR-30's exception (it crosses the column's edge, or it isn't the row's only amount), is rejected with a
  reason instead of skipped silently (pass 2 M3). This is how the plan shows contract gap G5; test `fr30_edge`.
- **P20** A table excluded by its title line alone, whose heading has Description and Amount (or Debit/Credit) columns,
  gives a record note, so the user can see the rows came from the reading (pass 3 minor, R4).
- **P19** A statement's record notes are stored in `details["notes"]`, as a bill's are, so the record shows them
  (pass 2 M2).

## Error handling, idempotency and recovery
- **Delete** is one connection and transaction under `BEGIN IMMEDIATE`. The token is checked inside it (FR-14). A
  failure at any step rolls back everything, so the retry with the same token succeeds when nothing changed (FR-15,
  SC-11).
  - The reconciliation run after commit is best effort, as after an import. A failure there is logged and doesn't undo
    the delete.
- **FR-06 removal** runs inside `publish_statement`'s transaction. With the contract's trigger on `DELETE FROM accounts`,
  the whole publish rolls back, and the extraction run fails with today's "nothing was published" message.
- **Migration 073** is one runner step. A failure rolls it back and the next start retries. The `sort` part is
  idempotent.
- **Rebuild:** pure. Exceptions are caught in `publish` (P8) and logged with `log_failure`, without row text (no money
  or names in logs).
- **Concurrency:** Record (inference work) and Delete can overlap. `BEGIN IMMEDIATE` serializes them, and the token
  catches a Record that landed first. A Record that lands after a delete finds no account and creates a new unconfirmed
  one (FR-13: "can be recorded again").
- **Duplicates:** fingerprints are unchanged (account, date, amount, currency, ordinal). Rebuilt rows dedupe against
  imports as today.

## Privacy/security and migration impact
- **No data leaves the machine.** No model or network call is added. The rebuild runs on the saved layout (FR-26).
- **Logs:** counts and ids only.
- **Delete is destructive by design** (D2, OD-2). It is guarded by an explicit second click, the token, the mutex and
  one transaction. It removes ledger rows only: originals, blobs, readings and library files are never opened for write
  (C-docs).
- **P9, family hub (U1, FR-28).** What the code holds:
  1. **The family's copy of a member's whole database** (`members/<id>.sqlite3` and views). It is replaced at the
     member's next publish. The delete writes the database file, so `changed_since` makes that publish due, and the
     delete reaches the family's copy at the next share with no new code.
  2. **Family rows in this library:** `family_assignments` (statements this library routes), `family_corrections`
     (`statement` or `transaction`) and `family:` evidence links. These are deleted with the records (steps 3 and 5
     above).
  3. **Statements this library already delivered to another member** live in that member's own library. The delete
     doesn't reach into another person's library. Their copy stays theirs, and they can delete it there (Q6).
     `record_shares` holds receipts only, which a delete never removes.
  - The dialog's `family` line is filled when the profile publishes to a family: "Your family's copy has these {n}
    statements and {m} transactions; it drops them at your next share." It is followed by the count of in-library family
    rows. SC-22 asserts those counts and that no family row in this library refers to the account, its statements or its
    transactions.
- **Migration impact:** one additive column and a sort. It may delete empty accounts that Record made (FR-08 b).
  Upgrade backups follow the runner's existing snapshot (`storage.py:256`). `docs/development.md`'s schema map gains 073.

## Vertical slices

| ID | FR/SC covered | Dependencies | Files/changes | Verification command / evidence |
|---|---|---|---|---|
| SL-01 | FR-30 (SC-27 and SC-28, PDF-import side and module level; G5 by `fr30_edge`), FR-16 (page selection), FR-17, FR-18, FR-19, FR-21, FR-26 (pure part), FR-27, FR-29 at module level; fixtures and P-checks for S, S-flag, S2, W, C, C0, D, D-flag, T, T-edge, X, Q, M | none | `finance/pdf_import.py` (`visual_row` FR-30 with D6's exception and P18, `ANALYZER_VERSION=2`); `finance/statement_rows.py` (new); `tests/test_pdf.py` `make_pdf` (optional per-item text matrix, additive); `tests/statement_account_fixtures.py` (new: builders S, S-flag, S2, W, W′, C, C0, D, T, X, Q, M, and T-edge beyond the contract, the stubs S-bad and summaries, the footer rule and the title-line order); `tests/test_statement_rebuild.py` (new: `pcheck_*` and `rows_*` unit tests on real readings) | `.venv/bin/python -m pytest tests/test_statement_rebuild.py -k "pcheck or rows or sc27 or sc28 or fr30_edge" tests/test_pdf.py tests/test_pdf_layout.py tests/test_pdf_imports.py -q` (the whole PDF import suite must pass unchanged). **Gate:** every P-check holds (S-flag raises `overlapping_text` and `unsupported_text_rotation`, and `native_page` is false; `pcheck_title_lines`; T's P-check (t1's `12.34` in the description's `PageView.texts` run, wholly inside the Amount span, the row's only amount-shaped word centred in an amount column); `pcheck_t_edge`; D's daily table is its own heading; Q's two tables; X's rows sit as the contract places them). On failure, stop and escalate before SL-02 |
| SL-02 | FR-16, FR-20, FR-22, FR-23, FR-25, FR-26, FR-17/18/19/21/27/29 through Record; SC-13, SC-14, SC-15, SC-16, SC-17, SC-18, SC-20, SC-21, SC-23, SC-27 and SC-28 (Record side) | SL-01 | `documents/extraction.py` (`read`: `rebuilt_pages`, `missed_rows` on the other pages' lines, the reading keeps `evidence`; `publish`: `rebuild`, P8 fallback, uses `published["review_status"]`, a statement's record notes in `details["notes"]` (pass 2 M2); `normalize(rebuild=)`); `tests/test_statement_rebuild.py` (scenario tests through `ExtractionService.run` with `by_schema` stubs and the no-network fixture) | `.venv/bin/python -m pytest tests/test_statement_rebuild.py -k "sc13 or sc14 or sc15 or sc16 or sc17 or sc18 or sc20 or sc21 or sc23 or sc27 or sc28" tests/test_statement_forms.py tests/test_extraction.py tests/test_layout_consumers.py -q` |
| SL-03 | FR-24; SC-19 (API) | SL-02 | `finance/provenance.py` `_extraction` (a rebuilt locator → `document {id, page, lines: line_ids, cells: word_ids or cell_ids}`); `static/trace.js` (the source link adds the cells to `?lines=` when present, if it doesn't already); `tests/test_statement_rebuild.py` `sc19`; `docs/documents.md` "PDFs" and "Typed extraction" (rows from the printed columns, FR-30 with D6's exception and P18's rejection in PDF import, and the re-index of every PDF reading that `ANALYZER_VERSION=2` causes at the next start), `docs/money.md` "Reading a statement or receipt again" | `.venv/bin/python -m pytest tests/test_statement_rebuild.py -k sc19 tests/test_provenance.py tests/test_traces.py -q` |
| SL-04 | FR-01, FR-02, FR-03, FR-07, FR-08; SC-02 and SC-03 (ledger/API), SC-04, SC-07 | SL-02 | `library/migrations/073_statement_accounts.sql` (new); `finance/ledger.py` (`CONFIRMED`, `account_in(origin=)`, `accounts()`, `waiting_accounts()`, `account_match`, `add_manual_transaction` refusal, `record()` `account_confirmed`); `finance/investments.py:603`; `finance/tools.py` `_coverage`; `finance/family_routing.py` `apply_delivery` (`origin='family'`) and `member_facts`; `app/family_sync.py` `_joint_accounts`; `app/api.py` (`GET /api/finance/accounts/waiting`); `tests/test_statement_accounts.py` (new: `sc04`, `sc07`, `c_visible` helpers); `tests/test_migrations.py` (073 applies, sorts, is idempotent); `docs/development.md` schema map | `.venv/bin/python -m pytest tests/test_statement_accounts.py -k "sc04 or sc07" tests/test_migrations.py tests/test_imports.py tests/test_pdf_imports.py tests/test_family_routing.py tests/test_finance.py -q` |
| SL-05 | FR-04, FR-05 (API), FR-06; SC-01, SC-02, SC-03, SC-05, SC-06; J1 complete with J1-a and J1-b | SL-04 | `finance/ledger.py` `publish_statement` (P16 order, `origin=`, downgrade, `remove_if_empty`, `_remove_account` for the empty case, result fields), `review` (P15), `correct` (no automatic promotion while unconfirmed), `record()` `account_note`; `documents/extraction.py` (passes `origin='record'`, published status); existing tests that Record statements through `ExtractionService` (`test_statement_forms`, `test_layout_consumers`, `test_extraction`, `test_reextraction`, `test_traces`, `test_provenance`, and Record steps in `test_pdf_imports`): only the assertions FR-01/FR-04 change (account hidden until confirmed, `proposed` where it was `verified`) are updated, each citing the FR; no other assertion is weakened; `tests/test_statement_accounts.py` `journey_j1`; `docs/money.md` "New statements wait for you" (new accounts wait for Confirm) | `.venv/bin/python -m pytest tests/test_statement_accounts.py -k "journey_j1 or sc04 or sc07" tests/test_statement_forms.py tests/test_reconcile_tools.py tests/test_layout_consumers.py tests/test_extraction.py tests/test_reextraction.py tests/test_traces.py tests/test_provenance.py tests/test_record_history.py -q` |
| SL-06 | FR-09 (API), FR-10, FR-11, FR-12, FR-13 (API and library), FR-14, FR-15, FR-28; SC-08, SC-09, SC-10, SC-11, SC-12, SC-22; J2 complete | SL-05 | `finance/ledger.py` (`delete_preview`, `delete_account`, full `_remove_account`, `AccountChanged`); `app/manager.py` (`delete_preview` with `family`, `delete_account` under the mutex, reconcile after); `app/api.py` (two routes, 409 mapping); `documents/extraction.py` `get` (`publication.removed`); `tests/test_statement_accounts.py` `journey_j2`, `sc12`, `sc22` (C-orphans from `sqlite_master`/`pragma_foreign_key_list`); `docs/money.md` (new section "Deleting an account"); `docs/family.md` "Family ledger" (a delete reaches the family's copy at the next share) | `.venv/bin/python -m pytest tests/test_statement_accounts.py -k "journey_j2 or sc12 or sc22" tests/test_family_routing.py tests/test_reconcile_tools.py tests/test_finance.py tests/test_library.py -q` |
| SL-07 | FR-02 (UI), FR-05 (UI), FR-09, FR-10 (dialog), FR-13 (UI), OD-5, P4; SC-24, SC-25, SC-26 | SL-03, SL-06 | `static/accounts_v2.js` (Delete…, the Waiting for confirm group); `static/index.html` (`#account-delete-dialog`); `static/trace.js` (`awaitingAccount`; `account_note` in the statement record view); `static/document_v2.js` (note, Delete account, `publication.removed`, the statement's record notes shown as a bill's are (pass 2 M2)); `static/review_v2.js` (note); `static/style.css` (scoped rules); `tests/test_statement_accounts_browser.py` (new); `docs/ui.md` (Accounts page entry) | `RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_statement_accounts_browser.py tests/test_document_v2_browser.py tests/test_transactions_v2_browser.py -q`; then the contract's full regression run (below) |

### SL-01 details
- `make_pdf` gains an optional item form `(x, y, text, size, matrix)`, where `matrix` is the 4 numbers `a b c d` of
  `Tm`. Existing calls are unchanged. S-flag draws one title word with `matrix=(0, 1, -1, 0)` (90°) and two words at the
  same position.
  - Pass 1's probe found that two identical words at one position raise `unresolved_columns`, not `overlapping_text`.
    SL-01 first tries two **different** overlapping title words. If either code still doesn't appear, it uses another
    real reader trigger from `pdf_layout.py` (as the contract allows) and records which one was used. No expected value
    changes.
- **Additional SL-01 gate (pass 1 B1, FR-30):** S-flag's rebuild gives s1–s5 exactly (36, 2, −38, 150000, −50000),
  with none rejected and the full descriptions kept. 7-e and x3 are still rejected.
- **FR-30 exception (D6 Q8, SC-28):** T is the contract's fixture: S-flag plus t1 (`09/22`, `SYNTH LONG DESCRIPTION`,
  `12.34`, Balance blank) below s5, with the contract's placement at 10 pt (`SYNTH` x 110, `LONG` 155, `DESCRIPTION`
  194, `12.34` 272). `sc28` (PDF-import side) asserts the PDF-import preview by `account_id` parses 6 rows, none
  rejected, t1's amount cell `12.34` and description `SYNTH LONG DESCRIPTION`; `rebuild` gives s1–s5 as in SC-27 and
  t1 as 2026-09-22, 1234. T isn't balanced, so no test asserts its arithmetic. SL-02's `sc28` (Record, S-bad stub,
  which doesn't list t1) asserts the transactions are s1–s5 then t1 (2026-09-22, 1234, `SYNTH LONG DESCRIPTION`),
  recorded though the model didn't list it (FR-20), that no issue names t1, and that `1234567890` stays in s1–s3's
  descriptions.
- **G5 (plan level):** T-edge and `fr30_edge`, as in "FR-30 in `pdf_import.visual_row`" step 5.
- Every native page prints the words-only footer of at least 40 characters (contract "Synthetic PDFs").
- W′ is W with dates moved one month, and W″ with two (SC-10), built by the same builder.
- The C-orphans, C-unchanged, C-docs, C-money and C-visible helpers go in `tests/statement_account_fixtures.py`.
  C-unchanged skips `bills`, which no longer exists (note N1).

### Milestone checks
- **M1, after SL-03:** `.venv/bin/python -m pytest tests/test_statement_rebuild.py tests/test_statement_forms.py tests/test_pdf_imports.py tests/test_extraction.py tests/test_layout_consumers.py tests/test_provenance.py -q`.
- **M2, after SL-05:** the M1 set plus `tests/test_statement_accounts.py -k "journey_j1 or sc04 or sc07" tests/test_migrations.py tests/test_imports.py tests/test_family_routing.py tests/test_finance.py`.
- **M3, after SL-06:** the M2 set plus `tests/test_statement_accounts.py tests/test_reconcile_tools.py tests/test_library.py`.
- **M4, after SL-07:** the contract's regression run, both lines, then the full suite `.venv/bin/python -m pytest -q`
  and `.venv/bin/python -m ruff check src tests`. Windows: `.\.venv\Scripts\python.exe` (`docs/development.md`).

## Requirements & scenarios coverage matrix

| FR | Design | Slice | Scenarios / tests |
|---|---|---|---|
| FR-01 | P2 origin; `account_in` default `user` | SL-04 | J1 step 1, SC-04 (POST account) |
| FR-02 | P5 filters, waiting endpoint | SL-04, SL-07 | J1 step 1 C-hidden, SC-04 reject case, SC-24 |
| FR-03 | P1 predicate | SL-04 | J1 step 2, SC-04, SC-24 |
| FR-04 | downgrade in `publish_statement` | SL-05 | J1 step 1, J1-b |
| FR-05 | `account_note` | SL-05, SL-07 | J1 step 1, SC-24 |
| FR-06 | `remove_if_empty` in the publish transaction; P16 | SL-05 | J1 step 4 (with fault), J1-a (SC-06, `kept_reviewed`) |
| FR-07 | P1 (Undo is `needs_review`) | SL-04 | J1 step 3 |
| FR-08 | migration 073 | SL-04 | SC-07 |
| FR-09 | Delete… and the dialog | SL-06, SL-07 | J2, SC-12, SC-25 |
| FR-10 | `delete_preview` counts | SL-06, SL-07 | J2 step 1, SC-25 |
| FR-11 | `_remove_account` order | SL-06 | J2 step 4, SC-12 |
| FR-12 | standalone rules (no step) | SL-06 | J2 step 5 |
| FR-13 | no file writes; `publication.removed`; `ledger_status` | SL-06, SL-07 | J2 step 6 |
| FR-14 | token | SL-06 | J2 step 2 (SC-10) |
| FR-15 | one transaction | SL-06 | J2 steps 3–4 (SC-11) |
| FR-16 | `rebuilt_pages`, `rebuild` on every `embedded_text` page | SL-01, SL-02 | SC-13 |
| FR-17 | `analyze` cells | SL-01, SL-02 | SC-13, SC-14 |
| FR-18 | explicit sign | SL-01, SL-02 | SC-14 |
| FR-19 | year rule | SL-01, SL-02 | SC-15 |
| FR-20 | `normalize` matching | SL-02 | SC-13, SC-16 |
| FR-21 | rejected rows as issues | SL-01, SL-02 | SC-17 |
| FR-22 | `read`'s page note, rows kept | SL-02 | SC-13 |
| FR-23 | model path on other pages; no-layout note | SL-02 | SC-18 |
| FR-24 | rebuilt locator; provenance | SL-03, SL-07 | SC-19, SC-26 |
| FR-25 | arithmetic on recorded rows | SL-02 | SC-20 |
| FR-26 | pure module; `_upsert` keeps reviewed | SL-01, SL-02 | SC-20 |
| FR-27 | balance tables excluded | SL-01, SL-02 | SC-21 |
| FR-28 | P9 | SL-06 | SC-22 |
| FR-29 | duplicate note | SL-01, SL-02 | SC-23 |
| FR-30 | joined description numbers in `visual_row`; D6's exception; P18 | SL-01, SL-02 | SC-27, SC-28, SC-13; `fr30_edge` (G5) |

Every SC-01 – SC-28 appears above, directly or as a journey step named in the contract: J1 steps 1, 2, 3 and 4 are
SC-01, SC-02, SC-03 and SC-05, and J1-a is SC-06 (SL-05 `journey_j1`); J2 steps 1, 2, 3–4 and 5 are SC-08, SC-10,
SC-11 and SC-09 (SL-06 `journey_j2`). SC-24 – SC-26 are browser scenarios (opt-in).

## Test environments, data, stubs for nondeterministic components, final-state oracle
- **Environment:** `tmp_path` stores only, as the contract's conventions say. API tests use `create_app` with
  `TestClient`. Browser tests use `served()` and Edge, opt-in. Nothing reads `P:\Finances`, `%LOCALAPPDATA%\HomeManager`
  or `P:\EvalCorpus`.
- **Data:** synthetic PDFs from `make_pdf` only (`tests/statement_account_fixtures.py`).
- **Stubs:** the reasoning model through `local_model` with `by_schema` (`Classification`, `BankStatementSummary` or
  `CreditCardStatementSummary`, `Transactions`). The vision stub serves only M's page 2.
  - An autouse no-network fixture (copied from `tests/test_pdf_imports.py:34–56`) blocks non-loopback sockets.
  - SC-20 asserts that `local_model["requests"]` grows only by the reasoning calls.
- **Fault double:** a permanent SQLite trigger created and dropped by the test. Each `connection()` is a new
  connection, so a TEMP trigger wouldn't be seen.
- **Old-schema library (SC-07):** the fixtures are built through public paths at the current schema. Then
  `ALTER TABLE accounts DROP COLUMN origin` and `PRAGMA user_version=72` take the library back. The column's CHECK is a
  column constraint, which SQLite drops with the column. Reopening the store applies 073. Two fixtures need direct SQL,
  a deviation from the contract's "filled through the public Ledger and extraction paths" that changes no expected
  value:
  - **(a)** Under the new code, Record into a new account gives `proposed`. The test therefore sets that statement and
    its rows to `verified`/`automatic` with one UPDATE, the state the pre-feature code left (pass 1 minor).
  - **(b)** The test re-inserts, with its old id, the account a re-read removed. The first run's `publication_json`
    still names that id, exactly as the pre-feature code left it.
- **Final-state oracle:** C-orphans reads the tables from `sqlite_master` and `pragma_foreign_key_list` at test time.
  It covers the six id columns plus the typed tables (contract). An `account_id` column counts only where its foreign key
  targets `accounts`. `holdings`, `investment_events` and others have `account_id` → `investment_accounts` (pass 1
  INFO). B's rows are compared by full snapshot. Money is
  compared in integer minor units (C-money). C-docs hashes every original, blob, library file and reading-folder file.
  `assert_ledger_healthy` runs at the end of every stateful test.
- **Expected values** come from the contract only. A failing P-check is a fixture problem, never a reason to change an
  expected value.

## Risks, unresolved decisions, alternatives
- **R1 (migration).** A hand-made account that once held a statement which later moved away is removed by FR-08's sort
  if it's empty. That is rare, and the account is recreated by recording again. Alternative: keep every account with
  `origin` unknown. That would fail FR-08 (b).
- **R2 (`replaced_by`).** A manual payment in another account that a deleted transaction had replaced would count again.
  Manual replacements match within an account (`reconcile.replace_manual`), so this shouldn't happen. The delete clears
  the pointer rather than failing, and J2's totals check would catch a miss.
- **R3 (date order).** P12 can leave a statement's rows in review when all dates are ≤ 12 in both positions and both
  orders fit the period. That's rare for a month-long period, and those rows are shown, not guessed.
- **R4 (balance titles).** FR-27 relies on the title being the visual row directly above the heading. A table titled two
  rows up is read as transactions. The spec defines it this way (R2 accepted).
  - The converse (pass 2 M1): a real statement whose account summary's last line (`Ending Balance 1,000.00`) sits
    directly above the transactions heading has that table classed as a balance table. No rows are rebuilt for it, and
    its page keeps the model's reading, as today (FR-23), and P20 adds a record note saying so. That loses this
    feature's fix for such a statement. The user accepted this fallback with FR-27 unchanged (D6 Q7). The gap and its
    deferred fix (a title only when the row holds no amount-shaped word) are listed in `docs/open-work.md` "Money",
    under Statement accounts. No test asserts it, since the spec defines the behavior and no fixture prints it.
- **R6 (FR-30 in PDF import, P18).** Under the amended FR-30 (D6 Q8) a PDF-import row whose description ends within
  1.5 font sizes of its only amount is read as today when that amount lies wholly inside its amount column (fixture T,
  SC-28). What changes for PDF import:
  - A description number that crosses into an amount column beside the real amount is now description text, so the
    row is read where today it is rejected (E1, S-flag, SC-27).
  - A joined only-amount that crosses its column's edge by less than 20% of its width is read today (`place`'s
    allowance) and is now rejected with P18's reason, since FR-30 (a) has no tolerance. One that crosses by more was
    already rejected, now with P18's reason instead of "The amount doesn't fit a column.". The row is listed, not lost
    (G5). The existing suite's descriptions sit far from their amounts, so T-edge (`fr30_edge`) is the only test of it.
  - SL-03 records the change in `docs/documents.md`.
- **R5 (old publications).** Extraction runs whose `publication_json` predates `account_id` can't mark an account
  `record`. Such an empty account is kept as hand-made, which is the safe direction.
- **Alternatives considered:**
  - A stored `confirmed` flag: rejected, because it can drift from review history and Undo would need its own write.
  - Rewriting old automatic statements to `proposed`: rejected for P4, which changes no stored decision.
  - Deleting extraction runs on delete: rejected for P11, which keeps the run history.
  - A per-page rebuild: not possible with continuation chains (P8).
- **New dependencies:** none.

### Notes on the spec bundle (now written into the amended spec as N1–N3)
- **N1.** FR-10, FR-11 and SC-08 speak of "bills tied to it", and the contract's C-unchanged lists a `bills` table.
  Migration 067 dropped `bills`. The plan reads a bill tied to an account as `recurring_obligations.kind='bill'`. SC-08's
  "1 recurring payment and 1 bill" are two `recurring_obligations` rows (kinds `subscription` and `bill`), and the count
  "recurring payments and bills 2" holds. C-unchanged skips the missing table.
- **N2.** FR-28 and SC-22 speak of a member's statement "shared to the family". In the code, statements aren't shared by
  row: `record_shares` holds receipts, and statements are routed whole. P9 says which rows exist.
- **N3.** The spec's background says "Record already resolves years" from the period. Today the model does, and no code
  does. FR-19 is implemented as new code.

### Decisions the user settled (D5, 2026-10-26: the defaults below were accepted)
- **Q1.** One feature in four milestones (default), or split into three features: rows, confirm, delete?
- **Q2.** FR-27: is a table headed `Date | Amount | Balance` a transactions table? Default: yes, the Balance column is
  the Balance column. A heading like `Daily balance` or a balance title excludes the table.
- **Q3.** P1: after you confirm and then reject an account's only statement, the account returns to "Waiting for
  confirm". Default: accept.
- **Q4.** P8: a rebuild failure falls back for every page, not only the failing one. Default: accept.
- **Q5.** E3/P13: FR-20's notes are record notes (shown, not a review reason). Default: yes, as J1 and SC-16 require.
- **Q6.** P9: a delete doesn't reach statements already delivered into another member's own library. Default: accept.
  The alternative is sending a `retract` delivery, which only marks their copy rejected.

### Decisions the user settled after review pass 3 (D6, 2026-10-26)
- **Q7 (decided: accept the fallback, FR-27 unchanged).** A summary line such as `Ending Balance 1,000.00` printed
  directly above the transactions heading makes that table a balance table, and its page falls back to the model's
  reading. The plan keeps P17 (fixture line order) and P20 (a record note when a title excludes a transactions-shaped
  table). The gap and the deferred fix are listed in `docs/open-work.md` "Money" (R4).
- **Q8 (decided: amend FR-30).** A joined amount-shaped word stays the amount when its whole box lies inside one amount
  column's span, with no tolerance, and it is the row's only amount-shaped word centred in an amount column. The
  contract adds fixture T (t1 records 1234) and SC-28. P18's reason-rejection remains for a joined only-amount that
  crosses the column edge (contract G5), tested at plan level by `fr30_edge` (R6).

## Review history
See `plans/statement-accounts/reviews.md`. Pass 1 (HUMAN DECISION, then REVISE) found four BLOCKERs and three MAJORs. B2, B3, M1, M2 and M3, the plan-side part of B4, and every MINOR are fixed in this plan. B1 (E1) and the SC-06/J1-a part of B4 (E2) are contradictions inside the approved bundle. Per the review loop's step 5, they went back to the spec. On 2026-10-26 the user accepted the defaults and the recommended amendments (spec D5, FR-30, SC-27, SC-06/J1-a). The user approved the amended bundle `043927bcf806` on 2026-10-26, and pass 2 reviews this plan against it.

Pass 2 (REVISE) found no BLOCKER and three MAJORs, all fixed in the plan: M1 (fixture title lines, P17, Q7), M2 (statement record notes stored in `details["notes"]`, P19) and M3 (FR-30's silent row loss, P18). The minors and the INFO are fixed too.

Pass 3 (PASS WITH MINORS) found no BLOCKER or MAJOR. Its minors and INFOs are fixed in the plan (section-cut balance title, P20 note, R6, the empty details section, Q7's wording, citations, stale counts, fixture T's placement). Q7 and Q8 went to the user.

After pass 3 the user decided Q7 and Q8 (spec D6) and approved the amended bundle `100a178661f7` on 2026-10-26. The plan was updated narrowly to match (see "Post-review update for D6" in `reviews.md`); no further review pass was run, since the loop's three passes are used.
