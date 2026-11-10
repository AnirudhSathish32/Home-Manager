# Table engine, phase 4: bills read from their printed columns
Feature: pdf-table-engine-bills

<!-- Approval state lives in approvals/<slug>.json and is bound to this file's content hash.
     Do not add a Status line: changing it would change the hash. Check with gate.py. -->

Amends: `specs/pdf-table-engine/spec.md` FR-41 (makes it concrete and corrects its arithmetic, see "Supersedes") and its
non-goal "Splitting one PDF into several accounts" for bill files (FR-128 – FR-135); `specs/bill-kinds/spec.md` FR-43 and
FR-49 for text-PDF bills only (the previous balance and payments come from the printed summary on every non-invoice bill, so
the carried check also runs on general bills); `specs/pdf-table-engine-paystubs-cleanup/spec.md` non-goal "`anchor_rows` and
`anchor_summary` stay for receipts, bills, statements and investment documents", for non-invoice text-PDF bills only;
`docs/documents.md` "Several receipts in one file" for bill files (they split as pay stubs do, not as receipts do). Every
other requirement of those specs stands, including bill-kinds FR-40 – FR-42, FR-44 – FR-48, FR-50 – FR-58, document-forms as
built for bills and invoices, pdf-table-engine FR-01 – FR-34, and phases 2 and 3 as built (the pay stub split, FR-80 – FR-85,
is reused, not changed). IDs continue after phase 3 (FR-99, SC-97).

## Decisions already made (not to be re-asked)
- **D1 – D2 from phase 1** (user, 2026-10-27) hold: no per-provider templates; one engine for every text PDF; what proves a
  table was read right is a small arithmetic check per document kind.
- **D3 Bills are the next phase** (phase 1 FR-41, after FR-40 pay stubs, built as phases 2 and 3; `docs/open-work.md` "PDF
  table engine"). This spec and its test contract are approved before anything is built (phase 1 OD-5). Text-PDF receipts,
  investment statements and replacing `pdf_layout.table_grid` for every consumer (FR-42 – FR-44) stay out.
- **D4 The phase is worth building** (user, 2026-11-08, answering U1): the user's real bills are mostly text PDFs, downloaded.
- **D5 Invoices are left out** (user, 2026-11-08, OD-1 default): they keep today's path (`anchor_rows` / `anchor_summary`) and
  move with text-PDF receipts (FR-42), whose arithmetic they share.
- **D6 Engine only, no old path** (user, 2026-11-08, OD-2 default), as phase 3 did for pay stubs: a text-PDF bill's amounts
  come from the engine; a page without a charge table, a reading without layout, or an engine fault is read like a
  photographed bill; the reader's printed tables never decide a bill.
- **D7 Defaults taken for OD-3, OD-4, OD-6** (user, 2026-11-08, not raised): the Tables tab is unchanged; guess, don't
  review (unplaced lines, unclassified rows, column and amount-due guesses are notes; review only when today's checks fail,
  apart from the review this spec names in FR-119 and FR-129); a line's description is the model's, cited.
- **D8 The redacted shape probe is a requirement** (user, 2026-11-08, OD-5 yes): `scripts/statement_diagnose.py` gains a
  `bill` mode printing line shapes and counts, never text (FR-127, SC-125).
- **D9 Amount due printed several times** (user, 2026-11-08, R1 accepted as proposed): FR-117.
- **D10 Carried balance with no "New charges" line** (user, 2026-11-08, R2 accepted as proposed): FR-118.
- **D11 Several bills in one PDF are split automatically** (user, 2026-11-08, R3 changed from "review flag only"): a PDF
  holding several bills (a year of monthly bills downloaded together) becomes one bill record each, reusing the built pay
  stub split and its semantics (FR-128 – FR-135). Where the boundaries are uncertain the bill goes to review; the split is
  never a silent guess (FR-129). A certain split needs no review, as pay stubs (phase 2 FR-82).
- **D12 Budget or levelized billing** (user, 2026-11-08, R4 accepted as proposed): nothing new in code (today's review);
  recorded in `docs/open-work.md` by FR-126.
- **D13 Corrections by position after a re-read** (user, 2026-11-08, R5 accepted with the alternative): a kept position-based
  line correction is re-applied only when the line at that position prints the same amount; otherwise it is held, unapplied,
  with a review note (FR-119).
- **D14 Scanned and combined-image bill files split too** (user, 2026-11-08, OD-7 default): the split rule reads lines and
  their pages only, as the pay stub split does for scans and photos (phase 2 FR-80), so a scanned PDF or a combined-image
  document (`docs/documents.md` "Several images as one document") of several bills splits the same way, each part read like a
  photographed bill. A single image is one page and is never split by the rule (FR-128).
- **D15 FR-119 guards every bill** (user, 2026-11-08, OD-8 default): every bill's line corrections (text PDF, photographed,
  scanned, invoice), since a model re-read of an image can also add or drop a line; receipt items are unchanged (FR-119).
- **D16 A file of several invoices is not split** (user, 2026-11-08, OD-9 default): if any part of a split bill file reads as
  an invoice, the whole file is read as one document on today's path, with a note; splitting invoice files moves with FR-42
  (D5) (FR-130).
- **D17 Duplicate bills across files, exact matches only, rejected automatically** (user, 2026-11-08, OD-10 default), as pay
  stubs are (FR-134).
- **D18 Splits only between pages** (user, 2026-11-08, OD-11 default): two bills on one page are not split but sent to review,
  and Split here splits them by hand (FR-128, FR-129 a).
- **D19 No cross-bill previous-balance check** (user, 2026-11-08, R6 default): a bill's previous balance is not compared with
  the bill before it in the same file (a mismatch is common on real bills, so it would be noise); recorded in
  `docs/open-work.md` by FR-126.
- **D20 Record-level corrections after a split change: nothing new** (user, 2026-11-08, R7 default): bills are kept by file
  and segment, so after you change the split a bill whose part moved takes the record, and the record-level corrections (a
  corrected due date, provider or amount due), of whatever bill had its segment number before, as split receipts and pay
  stubs do today. Documented as a limit by FR-126.
- **D21 A rate printed with more decimals than the currency allows is kept as printed and in cents** (user, 2026-11-08,
  test contract G1: "I want you to store the rate and populate the cents field for rates like this"). An engine-read line's
  unit price such as BL-UTIL's `0.1430` $/kWh is kept exactly as printed text in the line's details, and
  `receipt_items.unit_price_minor` gets it rounded half up to the nearest minor unit (14). It raises no "Amount has more
  precision than USD allows" issue; quantity × unit price is checked with the printed rate, never the rounded cents; the
  line shows the printed rate (FR-110, FR-113).
- **D22 A holder printed only in a section title counts as printed** (user, 2026-11-08, test contract G2; amended by D24).
  Every charge row under a holder title such as BL-PHONE's `Alex 555-201-1111` takes that holder, cited to the title, so
  family routing by the phone's last four works, whatever holder the model gives (FR-102, FR-110).
- **D23 Test contract G3 – G8 are left to the plan** (user, 2026-11-08): the plan chooses and records each; G9 – G11 stand as
  the test contract states them. Nothing else in scope changes.
- **D24 The section title alone gives the holder** (user, 2026-11-08, test contract G12). Every charge row under a section title
  that prints a holder takes the holder parsed from that title, cited to the title line, even when the model names no holder
  for any row of the section. The title is parsed as FR-102 says (its phone number, or a name the model recognises). When the
  model's holder for a row disagrees with its section title, the printed title wins, with a note (FR-110).
- **D25 "More decimals than the currency allows" is judged by the rate's value** (user, 2026-11-08, test contract round 2).
  `0.1200` equals 0.12, so it is stored exactly (`unit_price_minor` 12) with no printed text kept; only a rate whose value is
  not a whole number of minor units (`0.1430`, 14.3 cents) keeps its printed text (FR-110, D21). This is today's test
  (`core/money.py:63` – `:65`: the value scaled by the currency's exponent must be whole).

## Goal / users / scope / non-goals
**Goal.** Any text-PDF bill (utility, phone, rent, any provider and layout) gives every printed charge line's amount from the
column it is printed in, and its amount due, new charges, previous balance and payments from the lines that print them. The
lines must add up to the bill's own printed totals, so a misread can't count quietly. The model names and classifies the lines;
it never decides which printed number is a line's charge. A file holding several bills becomes one bill each, and a kept line
correction never lands on a different line after a re-read.

**Users.** The household user recording bills (Extract / Record) and reviewing them on the document page.

**In scope.**
- The engine reads charge tables: label-and-amount rows that may print dates and usage, sections, subtotals, the bill's
  summary lines, other tables (FR-100 – FR-104).
- Which column is the charge, and which rows are money off, from printed numbers (FR-105, FR-106).
- Record copies a text-PDF bill's amounts from the engine, chooses among repeated amounts due, and works out new charges
  that aren't printed (FR-110 – FR-118).
- Line corrections kept by position are re-applied only to a line printing the same amount (FR-119).
- Unchanged kinds, versions, determinism, generator, evals, docs, the `bill` diagnose mode (FR-120 – FR-127).
- Several bills in one file (a text PDF, a scanned PDF or a combined-image document, D14): finding them, uncertain boundaries, one record each, the split's notes and changes, re-reads,
  VOID and duplicate bills, the library (FR-128 – FR-135).

**Non-goals.**
- Reading photographed and scanned bills from the engine: no word positions (phase 1 non-goal). Every bill in today's tests
  and eval corpus is an image (`tests/bill_kinds_fixtures.py` pages are `rent.png` etc.; `evals/synthetic.py`
  `bill(…, source="png")`), and they read as today. A scanned or combined-image file of several bills is still split (D14,
  FR-128), each part read like a photographed bill.
- Invoices (`invoice_marker`, `invoice_number` or `invoice_total` read): today's path (D5), and a file of several invoices is
  not split (D16, FR-130).
- Receipts of any kind, including the item table (`specs/receipt-item-table`) and tax by printed tax code
  (`specs/receipt-tax-codes`), and the receipt split (model question, review until confirmed): see "Boundary with the
  receipt specs".
- Budget or levelized billing arithmetic (D12), decimal-comma amounts (phase 1 OD-3), splitting two bills printed on one page
  automatically (D18; the user's Split here does it), a consolidated bill covering several service accounts, a check that a
  bill's previous balance equals the bill before it in the same file (D19), and holding record-level corrections after a split
  change (D20).
- New bill kinds (utility, phone, insurance: `docs/open-work.md`), and any change to how a bill counts, is matched to its
  payment, is shared or projects into budgets (`docs/money.md` "Bills and their lines", unchanged), apart from the worked-out
  new charges of FR-118 and the rejected VOID and duplicate bills of FR-133 – FR-134.
- The document page's layout: `receipt.js` `billLines` and the earlier-balance rows (`Ledger.bill_summary`) are unchanged
  (the one change in them: a line's Unit price shows a rate kept as printed, FR-110, D21); the Tables tab is unchanged (D7). The split panel changes only as FR-131 says.
- Donating a file holding several bills (as for receipts and pay stubs today).
- Any model or network call added by the engine or the split rule.

## Existing behavior (verified paths, assumptions, unknowns)
Paths under `src/home_manager/` unless noted. Read at HEAD `06cbb9b`.

**How a text-PDF bill is read today.**
- The model answers the bill form: `HEADERS["bill"]` (`documents/extraction.py:66`: provider, dates, `amount_due`,
  `new_charges`, `payments_received`, the invoice fields), plus for `rent` the fields of `BILL_KIND_FIELDS` (`:550`:
  `previous_balance`, `monthly_rent`). The general form has no `previous_balance`. Lines are `BillLine` (`:365`) or
  `RentBillLine` (`:385`): description, amount, quantity, unit price, category, kind or rent type, holder, evidence; rent lines
  add their printed period and usage.
- `read` (`:4202`) passes the reader's own printed tables (`table_grid`, `source == "pdf_text"`, `layout_context.evidence_tables`)
  to the model and then anchors (`:4260`): `native_values.anchor_summary` (`:32`) copies a summary amount from a table cell
  only when the cited row is in a `table_grid` table and a column heading or the row label matches `SUMMARY_ROLES`;
  `anchor_rows` (`:84`) copies a line's amount only from a column headed one of `amount`, `total`, `line total`, `extended
  amount`, `extended price`. Read from the code (not run): a line citing a table whose money column is headed otherwise
  (`Charges`, `Current Charges`) or not headed at all gets its amount set to none with the note "Amount has no unambiguous
  native source column; check the row." A page with no `table_grid` table (a headerless one, wrapped rows, the common case for
  utility bills) keeps the model's amounts, checked only by `amount_supported` against the cited line.
- `read` adds "N native table row(s) were not accounted for…" (`:4299`) for uncited native rows. These `read` notes become
  review reasons (`publish`, `issues.extend(notes)`, `:4040`).
- `bill_lines` (`:2954`) then: charges count by magnitude and a `credit` line is money off, whatever sign was printed;
  quantity × unit price must equal the line total; the lines must add up to the new charges, or to the amount due when no new
  charges are printed (`finance/document_checks.py:110` `bill_lines`); previous balance − payments + new charges = amount due
  when all four are printed (`:122` `bill_carried`, specs/bill-kinds FR-49). Failing either is a review reason. With no new
  charges printed, the lines' sum is what counts (`docs/money.md` "Bills and their lines"). The rent rules (FR-54 earlier
  months, FR-56 prorated rent) and date rules (FR-46 – FR-48, FR-55) run on the lines.
- A line's unit price goes through `read`'s `money` (`documents/extraction.py:2399`, `core/money.to_minor`), which refuses a
  number with more decimals than the currency allows (`core/money.py:65`): `0.1430` becomes the issue "Charge line N unit
  price: Amount has more precision than USD allows." (`bill_lines` `:2978`) and the line keeps no unit price. Where a unit price is kept, quantity × unit
  price is checked on it in minor units, rounded half-even (`bill_lines` `:2983`); the receipt and pay stub product checks round
  half up to the minor unit (`finance/document_checks.py:36` `product`, `hours_rate`). `receipt_items.unit_price_minor` is
  an integer (`050_strict_tables.sql`); `receipt_items.details_json` (`070_document_forms.sql`) already holds a line's
  printed text values with their locator (a rent line's `usage` `{"text", "locator"}`, `rent_line` `:2887`; a receipt
  item's `price_per_weight` text, shown by `finance/ledger.py:261` `item_table`). Pay stubs keep each line's rate as printed
  text in its details (`finance/document_traces.py:182`). The bill line table shows "Quantity: … · Unit price: …" from the
  server's display value (`app/static/receipt.js:229 – :230`).
- A line's holder (`line_holder`) is kept only when printed in a line the row cites: a word of the name
  (`name_supported` `:1892`) or the number's last four digits (`bill_lines` `:2973 – :2976`); otherwise it is dropped
  silently. Family routing matches a holder to a member by the phone's last four (`finance/family_routing.py:60`
  `phone_member`, `:72`).
- Notes from `bill_lines` are kept in the bill's details (`record["details"]["notes"]`) and are not review reasons for a kinded
  bill. The page's carried rows come from `details` (`finance/ledger.py:2459` `bill_summary`).

**Line corrections and a reading again.**
- A bill is a `receipts` row with `document_kind='bill'` (`finance/ledger.py:48`, `publish_bill` `:1428`); its lines are
  `receipt_items`. A line's corrections (kind `line_kind`, rent type `line_type`, member, and an item's price, description,
  code, quantity, unit price) are `record_corrections` rows with `record_type='receipt_item'`, the bill's id, and field
  `<name>:<position>` (`LINE_FIELDS`, `ITEM_FIELDS` `:203 – :212`; `correct_line` `:2879`; `_correct_item`). A row keeps the
  value and the previous value of that field (for a price, the line's amount before the correction), never the line's amount
  otherwise (`record_corrections` columns as rebuilt by `066_library_revision_bills.sql`: id, record_type, record_id, field, value, previous,
  resolved_issues_json, reason, actor, created_at).
- On a reading again, `_replace_items` (`:990`) keeps an item's id, its user category and its user member when its
  description and line total match an earlier item (`docs/money.md` "Reading a statement or receipt again"); then
  `apply_corrections` (`:2694`) re-applies the latest correction of each `<name>:<position>` field at that position,
  whatever line is now there. So a line the new reading adds above (or drops) shifts later positions, and a kept kind, member
  or price lands on another line, silently.

**Several documents in one file today.**
- `run` (`documents/extraction.py:4126 – :4130`) splits only receipts (`segments` `:4370`, a model `ReceiptStarts` question,
  page and region breaks as fallback) and pay stubs (`pay_parts` `:4395` → `documents/paystub_split.py` `stub_parts`, lines
  only, no model). A file classified as a bill is always one record (segment 0). Every part is classified before any is read;
  a part of another type makes the file read as one document with a note (`:4131 – :4140`).
- Bills are already numbered by segment: `receipts.segment` (0 – 199) with `UNIQUE(blob_hash, segment)` and
  `document_segments` (migration `054_receipt_segments.sql`). No schema change is needed for bill records.
- `record` (`:4333`) adds `SPLIT_NOTE`, a review reason, to every split record except a pay stub, which gets `PAY_SPLIT_NOTE`
  as a record note (`:1704 – :1706`). `confirm_split` (`:4451`) drops `SPLIT_NOTE` from receipts rows and re-judges their
  status, and drops `PAY_SPLIT_NOTE` from pay stub details. `set_split` (`:4474`) saves the user's split, records which
  reading it replaced (`split_changed` guess for pay stubs), and works on any file already recorded.
- `retire_segments` (`finance/ledger.py:959`) rejects automatically a receipts row or pay stub that a later reading no longer
  finds (restored if found again), worded "receipt" for every receipts row; a decided one keeps its decision with the note.
- VOID and duplicates are pay stubs only: `VOID_LINE` (`:1707`), `pay_stub_twin` (`finance/ledger.py:1481`), `mark_void`,
  `mark_duplicate`. Receipts and bills have no record-level duplicate rule; a file captured twice is one file.
- The split panel (`app/static/document_v2.js:860` `doc2Split`) appears only for a file recorded as several parts, worded
  for receipts or pay stubs; a receipt is named merchant · total · date, and unconfirmed receipts get the "waits in To check"
  warning.
- The library (`library/storage.py:576 – :586`) shows a file's amount only when it has one non-rejected receipts row; a bill
  file's due date and period come from the first non-rejected bill row with no order (`LIMIT 1`); its date is the earliest
  `purchase_date` (a bill's due date, else issue date).

**The engine today** reads statements (`documents/table_engine.py`: a row needs a date) and pay stubs
(`documents/pay_tables.py`: a row is a label and amounts, no date needed; sections, wrapped labels, totals by words, blocks,
continuation pages, whole numbers in a column, unplaced lines; `finance/paystub_tables.py`: roles by arithmetic, guesses with
notes, the adapter Record reads). Neither is used for bills.

**The diagnose script** (`scripts/statement_diagnose.py`) reads a PDF with this checkout's reader into a temporary folder and
prints shapes and counts only, for a statement or (`paystub`) a pay stub, including how many stubs the file splits into; it
has no bill mode.

**Tests and evals.** The only text-PDF bill test is `tests/test_layout_consumers.py::test_native_invoice_and_statement_copy_amount_not_unit_price_or_balance`
(an invoice table headed Item / Qty / Unit price / Total through `anchor_rows`). The synthetic eval corpus has 53 documents, two
of them bills (a phone bill read per holder with a past-due balance, a rent bill with water and trash), both images
(`evals/synthetic.py:313–317`). `evals/tasks/document_forms.py` reads the RENT lines as flat text. The pay stub split is
tested in `tests/test_paystub_split.py` (`specs/pdf-table-engine-paystubs/test-contract.md` SC-72 – SC-76).

**Assumptions**
- A1: A charge line prints its label and its amount on one visual line, or its label wraps onto the line(s) directly below.
  Dates (a line's period), usage (`3,200 GAL`), rates and meter reads may print on the same line.
- A2: A bill names its summary amounts in words (previous balance, payments, new or current charges, amount due), as pay stubs
  name their totals (phase 2 A3). Column headings are still never required.
- A3: The charge amount is a money column whose amounts take part in the bill's arithmetic; a column that never does (usage,
  rate, meter reads, a last-year comparison) is not money.
- A4: In a file of several downloaded bills, each bill starts on a new page, and each bill prints at least one of its due date,
  its statement (bill) date or its account number as a label and value, plus its amount due. A remittance stub or a
  continuation page repeats the same due date, statement date and account number as the bill it belongs to.

**Unknowns**
- U1: answered by the user (D4).
- U2: How common summary boxes, remittance stubs and per-service subtotals are on the user's bills.
- U3: How the user's multi-bill files lay out (one bill per page? keys printed?). The `bill` diagnose mode (FR-127) answers it
  without showing text.

## Functional requirements

### The engine: charge tables (text PDFs)
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-100 | **Charge rows.** On a bill, a row starts at a visual line with text at its left (the label) and an amount token in an amount column; no date or heading is needed (as phase 2 FR-50, FR-51 with phase 3 FR-90). Dates printed on the line (`Rent 10/01/2026 - 10/31/2026 $1,450.00`, `Payment Received 09/03/2026`) are label text, never a row start or an amount. A number followed in its own run by a word other than `CR`/`DR` (`3,200 GAL`, `1,234 kWh`, `450 min`) is usage: label text, never money. Where such numbers line up in a column of their own (two rows, or one under a heading), they are that column's values with their unit kept as printed, so FR-105 (a) can take the column as quantity; it is still never money. | `Water Usage 08/15/2026 - 09/14/2026 3,200 GAL $38.42` alone gives one row with one amount 38.42 and label `Water Usage 08/15/2026 - 09/14/2026 3,200 GAL` (SC-100); BL-UTIL's two `kWh` rows form a quantity column (SC-105). |
| FR-101 | **Columns by alignment** as phase 1 FR-04 (same tolerance). Headings, when printed (one or two lines, or one run over several columns, phase 3 FR-89), label the columns under them; their wording is never required. Other numeric columns (quantity, rate, meter reads, a last-year column) are found as columns and get roles in FR-105. | Headed, unknown-wording and headless variants give the same columns (SC-101). |
| FR-102 | **Sections, subtotals, wrapped labels, pages.** A text-only line at the label column's left edge followed by a row is a section title, kept as the rows' section (`Electric Charges`, `Taxes, Surcharges and Fees`, a holder title `Alex 555-201-1111`). A section title is where its rows' holder is printed when it prints one (D22, D24); such a title is a **holder title** when **(a)** it prints a phone number: digits in groups separated by spaces, `-`, `.` or parentheses ending in a group of exactly four digits, either at least 7 digits in all (`555-201-1111`, `(555) 201-1111`, `201-1111`) or masked (`xxx-xxx-1111`, `***-1111`, `•••• 1111`) or after `ending` / `ending in` / `ends in` (`Line ending 1111`); a bare 4-digit number such as a year is not a phone number; or **(b)** it prints no phone number but the model's holder for some row of that section is a name a word of which is printed in the title (today's `name_supported` rule, applied to the title line alone), since the engine cannot tell a name from a heading on its own. The **title's holder** is the title as printed, whitespace collapsed and cut to 80 characters (today's `line_holder` format, `documents/extraction.py:2973`: `Alex 555-201-1111`), so family routing's `phone_member` (`finance/family_routing.py:60`) finds the member by the number's last four digits. Every charge row under a holder title is cited to the title line as well as its own lines, and FR-110 gives it the title's holder. A line naming a total or subtotal (`Total Electric Charges`, `Total for Alex`, `Subtotal`) is a total with its value, not a charge row. An indented text-only line directly under a row joins its label. A table continues over pages as phase 3 FR-92 (b). | A phone bill with two holder sections, a subtotal each and a wrapped label gives one row per charge, its section the holder title, subtotals as totals; on the record each line under a holder title has that holder, cited to the title (SC-102). |
| FR-103 | **Summary lines.** A line naming a summary amount is a summary anchor with its printed amount, never a charge row, wherever it is printed (a summary box above the charges, lines below them, a remittance stub, another page): **previous balance** (previous balance, balance forward, last bill), **payments** (payment(s) received, payment(s) – thank you, payments), **new charges** (new charges, current charges, total current charges), **amount due** (amount due, total amount due, total due, balance due, amount to pay). The words are a fixed list, case-insensitive, whole words, kept in one place and documented; the plan may add synonyms found by the generator. A line printing an amount that applies only after a date or if paid late (`If paid after 10/15/2026, pay $102.55`, `Late fee after …`) is no anchor and no charge (bill-kinds FR-58). | BL-UTIL's summary box gives four anchors, `Total Current Charges` a fifth (new charges) and its remittance stub a sixth (amount due), values alike; none is a row (SC-103). |
| FR-104 | **Other tables and nothing dropped silently.** A table is a charge table when FR-105 finds a charge column in it; any other table (usage history, meter reads, rate details, payment history, a budget billing schedule) is another table and gives no lines. Every line on a bill's text pages that holds a label and an amount is a charge row, a total, a summary anchor, a row of another table, or an **unplaced line**, listed in a note with page and text (a note, not a review reason, D7). | rows + totals + anchors + other-table rows + unplaced = every label-and-amount line (SC-104); a 12-month usage table gives no lines and no unplaced lines. |

### Which column is the charge (from printed numbers only)
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-105 | **Roles** per charge table, in order: **(a)** quantity and rate: the pair of columns whose product equals a third column on every row printing all three (document-forms FR-21's product rule on the printed numbers; a rate may print 4 or more decimals, kept as FR-110 says) are quantity and unit price, the third the charge; **(b)** the column whose amounts, with their printed signs (FR-106), add up to the bill's new charges (printed, or worked out by FR-118), else to the amount due when neither is available, or whose printed subtotals each equal the rows they cover (phase 3 FR-91's coverage rule); **(c)** headings break a tie, and are the only guide when (a) and (b) decide nothing; **(d)** one amount column is the charge. Every other column is **other** and never money. When two columns both satisfy (b) and no heading decides, the right-most is the charge, and a note says so (a guess, FR-124). | Columns `Usage`, `Rate`, `Charge` in any order, with and without headings, give the right charge (SC-105); a `Last Year` column beside `This Bill` is other (SC-105 c). |
| FR-106 | **Money off.** A row printed with a minus, parentheses or `CR` is money off. An unsigned row under a section titled credits, discounts or adjustments is money off. Any other row is a charge. A row printed as money off is recorded as a `credit` line (rent type `credit` on a rent bill) whatever the model classified, with a note when the model said otherwise; an unsigned row the model calls `credit` stays money off (today's rule) and the lines check judges it. | `Autopay Discount -5.00` with the model answering `service` is a credit of 5.00 with a note; the lines add up (SC-106). |

### Where the engine is used (Record)
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-110 | Record uses the engine's charge tables on every `embedded_text` page of a non-invoice bill PDF, of either kind (D6). After classification, the model is shown the engine's charge tables (as cells) instead of the reader's printed tables, and classifies each line (description, category, line kind or rent type, holder, period, usage) citing its row. Every amount, quantity and unit price is copied from the row's cell in its role column; a blank cell stays blank. The model's numbers decide nothing there. The description is the model's, cited (D7). **A rate printed with more decimals than the currency allows** (D21, D25; BL-UTIL's `0.1430`), judged by the rate's value, not its printed digits: a rate is within the currency's precision when its value is a whole number of minor units (today's test, `core/money.py:63` – `:65`), so `0.1200` (= 0.12, 12 cents) is within it and only a rate such as `0.1430` (14.3 cents) is not. For a rate that is not: the printed text is kept exactly in the line's details (`receipt_items.details_json`, `unit_price` `{"text", "locator"}`, as a rent line's `usage`; an existing column, no migration), and `unit_price_minor` is that rate rounded half up to the nearest minor unit (0.1430 → 14, 0.1450 → 15; the rounding of `finance/document_checks.py` `product`); no "Amount has more precision than … allows" issue is raised for it. A rate within the currency's precision, however many zeros it prints (`0.12`, `0.1200`), is stored in `unit_price_minor` exactly as today (12), with no printed text kept and no precision issue. The line's Unit price on the document page shows the printed rate (`0.1430`), sent by the server; a unit-price correction of yours replaces it as today. **Holder** (D22, D24): every charge row under a holder title (FR-102) takes the title's holder, whether the model gives that row a holder or none, and for an engine row no model line cites (FR-112) too; the line's evidence includes the title line. When the model gives such a row a holder that disagrees with the title, the printed title wins and the bill gets the note "Line N: the holder X differs from its section title; the title's holder Y was used." The model's holder agrees when the last four digits match where both print digits, else when a word of it is printed in the title (`name_supported`); it is not a review reason. A row under no holder title keeps today's rule: the model's holder is kept only when printed in the row's own lines (a word of the name or the number's last four digits), else dropped. | A bill whose model stub answers every amount wrong still records the printed amounts (SC-110); BL-UTIL's Energy Tier 2 has `unit_price_minor` 14, its printed rate `0.1430` in its details and on the page, no precision issue, and its product check holds (SC-110); BL-PHONE's lines under `Alex 555-201-1111` have that holder, with or without a model holder, and a disagreeing model holder gives way to the title with a note (SC-102). |
| FR-111 | **Summary amounts.** Amount due, new charges, payments received and previous balance come from their summary anchors, else the model's value with today's checks. Previous balance and payments are kept in the bill's details on every non-invoice bill kind (general too), so the carried check (bill-kinds FR-49) and the page's carried rows (FR-50) run wherever they are printed. When the amount due is printed more than once with different values, FR-117 decides; when new charges isn't printed, FR-118 says what counts. When new charges, previous balance or payments print more than one value in one bill, the first on the bill's first page in reading order is used, with a note naming the others, and the checks judge it (no check chooses among them, so a misprint still fails its check). | A general utility bill printing previous balance, payments, new charges and amount due gets all four from the print, the carried check, and the Previous balance and Payment received rows on its page (SC-111). |
| FR-112 | **Matching.** A model line citing a line of an engine row takes that row; two model lines on one row keep the first, with a note. A model line citing a total, a summary line or a section title is left out, with a note ("… is a printed total, not a charge"). An engine charge row no model line cites is still recorded: its description is the printed label, its kind from FR-106 (`credit` or `other`), no category of its own (the bill's), with a note; not a review reason (D7). A model line citing a line that is no engine row keeps its value only when its amount is printed in the cited line (today's `amount_supported`), with a note. | SC-112: a subtotal the model listed as a line is left out; a row the model missed is recorded with the note; neither is a review reason, and the lines add up. |
| FR-113 | **Checks** run on the copied values with today's effect (bill-kinds FR-48, FR-49, FR-54 – FR-58; quantity × unit price, on the printed quantity and the printed rate, never the rounded `unit_price_minor` of FR-110, with `document_checks.product`'s rule: rounded half up to the minor unit, within its tolerance; invoice checks untouched): a failing check still sends the bill to review. A printed subtotal its rows don't add up to is a note naming page and value. Apart from FR-119 and FR-129, the engine and the split add no review reason of their own, and on engine pages the anchoring notes ("… has no unambiguous native source column", "N native table row(s) were not accounted for") are not raised. | A misprinted section subtotal with lines that add up to new charges: note, counts automatically; lines that don't add up: review with today's reason (SC-113). |
| FR-114 | **Pages with no charge table** (and readings saved without layout) are read like a photographed bill: the model's values with today's citation checks; the reader's printed tables don't decide them (D6). A text page with no charge table adds the note "Page N: no charge table was found in the printed columns, so its amounts are the reading's; check them." (a note). | SC-114. |
| FR-115 | **Engine failure** (an exception): the whole bill is read like a photographed bill with the note "The charge lines couldn't be read from the printed columns, so the reading's amounts were used; check them.", logged by `log_failure` without document text. In a file of several bills, the split (FR-128) still runs on the lines, and every bill of the file is read that way. | SC-115. |
| FR-116 | **Evidence.** Each copied amount cites its printed words (or its cell when the row is one native row), so the line's Find and the Amount due's Find (bill-kinds FR-51) light the printed amount. A wrapped label cites every line. | `GET /api/provenance` for a wrapped line lists both lines; Amount due cites the anchor's words (SC-116). |
| FR-117 | **Amount due printed several times** (D9). When a bill's amount-due anchors (FR-103, only the bill's own lines, FR-130) print more than one value, its amount due is the value that makes the bill's checks hold: the carried check (previous balance − payments + new charges = amount due) when the other three are printed, else the lines check when it is run against the amount due (no new charges printed or worked out). If no check decides, the amount due is the first amount-due anchor on the bill's first page in reading order, with the guess note "The amount due is printed as X and Y; X, the first on page N, was used." (guess kind `amount_due`, FR-124). A late-payment amount (FR-103) is never the amount due. The value chosen is still checked as today: if the checks then fail, the bill goes to review with today's reason. A value printed several times alike is one value, no note. | SC-117: the carried check picks 147.55 over a first-printed 50.00; the lines check picks 97.55; with nothing to decide, the first on page 1 with the guess note. |
| FR-118 | **New charges worked out** (D10). On an engine-read bill (FR-110) that prints no new charges but prints its previous balance and payments (a printed 0.00 counts as printed), the new charges are worked out as amount due − previous balance + payments (payments by magnitude). The lines must add up to that worked-out value (the lines check, with today's effect), and that value is what counts (`total_minor`), not the lines' sum. The bill carries the note "New charges aren't printed; worked out as amount due A − previous balance P + payments R = N." in its details, and the lines check's working shows the same subtraction. The carried check is not run on such a bill (it would hold by construction). Without a printed previous balance or payments, today's rule stands (lines against the amount due; the lines' sum counts). Photographed bills are unchanged. | SC-118: lines 97.55 equal 147.55 − 150.00 + 100.00 and the bill counts 97.55 automatically; a misprinted amount due 150.55 gives worked-out 100.55, review with today's lines reason naming 100.55, and the bill counts 100.55 until corrected. |
| FR-119 | **Line corrections after a re-read** (D13). A kept position-based correction of a bill line (line kind, rent type, member, price, description, code, quantity, unit price: every `receipt_item` `<name>:<position>` field) is re-applied after a reading again only when the line now at that position prints the same amount as the line the correction was made on (its amount as read, before any price correction of yours), or, for a price correction, prints exactly your corrected price. Otherwise the correction is **held**: not applied, kept (it stays in the history and the latest of its field), and the bill gets the review reason "Your change to line N (what you changed) wasn't applied: that line now prints X, not Y. Check the bill's lines and make the change again on the right line." A held correction is applied again, and its reason goes, when a later reading prints the remembered amount at that position again; making the same kind of change on that position again replaces it. A correction made before this change is compared with the amount its line had in the bill's last reading before the re-read. What `_replace_items` keeps by description and line total (the line's id, your category, your member) is kept as today. A bill you decided is never rewritten, so nothing is held on it. Applies to every bill, text PDF, photographed, scanned or invoice (D15); receipts are unchanged. | SC-119: after the engine finds a line the model missed, member Blair stays on Basic Plan (kept by identity) and is not given to Device Payment; a price correction for the old position 3 is held with the reason, and Basic Plan keeps 35.00; unshifted lines take their corrections as today; a price correction the engine now reads exactly is applied with no reason. |

### Unchanged kinds, data, measurement
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-120 | **Unchanged.** Photographed and scanned bills, invoices (D5), receipts, statements and pay stubs read exactly as before: the phase 1 and phase 2 generators, the `aligned` eval cases, and the bill, invoice, receipt, statement and pay stub suites pass unchanged, except tests the contract lists one by one with the requirement that changes them. The only changes to bills that aren't text PDFs are FR-119's held corrections (D15), the split of a scanned or combined-image file of several bills, FR-128 – FR-135 (D14), and FR-133 – FR-134's VOID and duplicate bills (D17); a single photographed or scanned bill is otherwise read as before. | SC-120. |
| FR-121 | `EXTRACTION_VERSION` changes (from `typed-extraction-v39-receipt-printed-signs`), so older readings aren't reused. No migration rewrites a record; a bill you confirmed or rejected is never rewritten; Extract again re-reads an undecided one, items matching as today (description and line total) and position corrections re-applied by FR-119. An undecided bill file recorded before this change as one bill that the rule now splits becomes several bills: its record keeps segment 0 and its id, and the others are new (FR-132). | SC-121. |
| FR-122 | Deterministic: the same reading gives the same lines, amounts, anchors, guesses, notes, evidence and split; Extract again on an unchanged reading changes nothing; the engine and the split rule make no model or network call. | SC-122. |
| FR-123 | **Bill layout generator.** At least 100 synthetic text-PDF bill files from a fixed seed, varying: kind (utility with usage and rate, phone with holder sections, rent with line periods); one table or sections with subtotals; headings known, unknown, none, one or two lines; quantity × rate columns, a last-year column; credits signed, in parentheses, `CR`, or unsigned in a credits section; summary box above, lines below, both, or none; previous balance and payments printed or not; new charges printed or not (FR-118); an amount due printed twice alike, or with a second different value (FR-117); a remittance stub repeating the amount due, on the bill's page or a page of its own; a continuation page repeating the header; a late-payment amount line; a key word inside a sentence; wrapped labels; two pages; a usage history table; dot leaders between label and amount; and files of 1 to 4 bills, one per page or two pages each, two of them for different accounts with the same dates. Each records every line, summary amount and split exactly (expected from the generator's inputs, the model's classification stubbed from them). | The generator test passes with zero misses; failures print seed and layout (SC-123). |
| FR-124 | **Eval.** The synthetic corpus gains five aligned-column text-PDF bill files (a utility bill with Usage / Rate / Charge and a summary box; a phone bill with holder sections, subtotals and a credit; a rent bill with line periods, previous balance and payments; a two-page headless bill with a remittance stub on its own page; a file of three monthly bills, BL-MULTI), appended after the existing 53 documents so no id or answer changes. The documents suite reports `bill_readers: {engine}` for text-PDF bills: `documents`, `lines`, `exact`, `left_out`, `checkable`, `checks_held`, `to_review`, `unplaced`, `failed`, `files_split`, `split_right`, `split_review` and shares; each guess (FR-105, FR-112 unclassified rows, FR-117 `amount_due`, a split the user later changes `split_changed`) adds to `guesses` by kind, with how many were right. Counts only, so `summary.json` passes the allowlist. The user runs it on the donated corpus in their own terminal (docs/evals.md). | `python -m evals.run` on the synthetic corpus shows the counts, exact on the five aligned files, the three-bill file split right, every guess right (SC-124). |
| FR-125 | Existing tests: bill-kinds, document-forms, invoice, bills-ledger, recurring-bills, layout-consumer and pay stub split tests pass unchanged, except those the contract lists one by one. | SC-120. |
| FR-126 | **Docs.** `docs/documents.md` gains "Bill lines from the printed columns" and "Several bills in one file", the latter saying scanned and combined-image files split too (D14) and stating the limit of D20 (after you change the split, a bill whose part moved keeps the record and record-level corrections of the bill that had its segment number before); `docs/money.md` "Bills and their lines" says text-PDF bills take amounts from the print, guesses are notes, new charges may be worked out (FR-118), and VOID and duplicate bills don't count; `docs/money.md` "Reading a statement or receipt again" says when a bill line's correction is held (FR-119); `docs/evals.md` "The two table readers" covers bills and the split counts; `docs/open-work.md` moves FR-41 to built and records what is left: invoices (D5, with a file of several invoices, D16), budget or levelized billing (D12), two bills on one page split only by hand (D18), consolidated bills over several accounts, the cross-bill previous-balance check (D19), record-level corrections not held after a split change (D20), donating split bills, and accuracy on real bills unmeasured. Headings stay stable. | Doc diff present. |
| FR-127 | **The `bill` diagnose mode** (D8). `python scripts/statement_diagnose.py "<bill PDF>" bill` reads the file as a bill and prints, per page: the charge tables found (each column's edges and zone as a percentage of the page width, its role and how the role was decided), counts of rows, totals, section titles, wrapped labels, summary anchors by kind, other tables and unplaced lines; the guesses by kind; and for the file, how many bills it splits into, the pages of each, which keys each page prints (due date, statement date, account: present, and whether its value equals the open bill's or differs, never the value), and which uncertainty rules of FR-129 fired. Shapes and counts only: no label, heading word, provider, amount, date or account digit. Like the other modes it reads into a temporary folder that is deleted at the end, and needs no model. | SC-125: on BL-MULTI and BL-UTIL the output gives the counts and splits; none of the fixtures' words, amounts, dates or account digits appear in it. |

### Several bills in one file
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-128 | **Finding the bills** (D11; the pay stub rule's shape, phase 2 FR-80). The rule reads the transcribed lines with their pages and asks no model, so it runs on every bill file: a text PDF, a scanned PDF or a combined-image document (D14); a single image is one page and is never split. A **key line** is a line whose text starts with a key label directly followed by its value (dot leaders and a colon allowed): **due date** (due date, payment due date, payment due), **statement date** (statement date, bill date, billing date), **account** (account number, account no., account #, account). Due and statement dates are compared as dates; an account by its last four digits (masked prints such as `****9012` count). A key word inside a sentence (`Your previous bill, due 09/15/2026, is past due`, `Late fee if not paid by 10/15/2026`) or after other words (`Previous Statement Date …`, `Rent and Leasing Charges Due 10/01/2026`) is no key line. The labels are a fixed list kept in one place and documented, as FR-103's. A **page starts a new bill** when one of its key lines prints a value that differs from the value the open bill already printed for that key; a page that prints only equal values, keys the open bill hasn't printed, or no keys continues the open bill (a remittance stub, a repeated header, a usage-history page). The rule splits only between pages (D18): two bills on one page stay one bill, with FR-129 (a). A billing or service period is no key: one bill can print a period per service. Each part must print its own amount due (an amount-due anchor of FR-103, never a late-payment line): a part without one joins the part before it (the first joins the next), and FR-129 (b) applies. A file with one bill reads exactly as without this rule. At most 200 bills per file (`receipts.segment` 0 – 199); beyond that the file is read as one bill with FR-129 (d). | BL-MULTI gives 3 bills; BL-REMIT (a remittance stub and a repeated header on page 2) gives 1; BL-ACCT (same dates, another account on page 2) gives 2; BL-MULTI as a scanned PDF and as three combined images gives 3, each read like a photographed bill (SC-126). |
| FR-129 | **Uncertain boundaries go to review** (D11, never a silent guess). Each of these gives the bill concerned one review reason, worded with the page and the printed values: **(a)** a page whose key lines print two different values for one key (two bills on one page; not split, D18): "Page N prints more than one due date (A, B), so it may hold more than one bill; check it and split it on the document's page."; **(b)** a part joined to the one before because it prints no amount due of its own: "Page N prints its own due date (A) but no amount due, so it was read with the bill before it; check how the file was split."; **(c)** one bill whose new-charges anchors print different values on different pages with no key line telling them apart: "This bill prints new charges of A and B on different pages, so the file may hold more than one bill; check it and split it on the document's page."; **(d)** the rule raises, or finds more than 200 bills: the file is read as one bill with "Where each bill starts couldn't be read, so the file was read as one; check whether it holds more than one bill." (the error logged by `log_failure` without text). A split you made or confirmed raises none of these. Every other part of a file is judged by its own checks. | SC-127: BL-JOIN gives 2 bills, the first in review with (b), the third bill counting automatically; BL-TWOONPAGE gives 1 bill in review with (a); BL-NOKEY gives 1 bill in review with (c); a raising rule gives 1 bill in review with (d). |
| FR-130 | **Each bill is a record of its own** (phase 2 FR-81). Every part is classified before any is read; a part that classifies as something other than a bill makes the file read as one document with the note "A part of this file is not a bill, so the file was read as one document." A file of several invoices is not split (D16): if any part reads as an invoice (`invoice_marker`, `invoice_number` or `invoice_total` read), the whole file is read as one document on today's path with the note "A part of this file is an invoice, so the file was read as one document." Each part is then read on its own lines: its own bill kind (general or rent, the kind chosen per part as today), the engine's charge rows, totals and summary anchors whose lines lie in the part (a table cut by your split gives each part its own rows), FR-117 and FR-118 on its own anchors (a part of a scanned or combined-image file has no text pages, so it is read like a photographed bill, FR-110 applying only to text pages), its own checks (the lines against its own new charges, its own carried check), and it is published as its own bill (segment 0, 1, …) with its own review status, payment match, recurring bill and counting on its own due date. The engine reads the file once. | BL-MULTI gives 3 bills with their own lines, amounts due 81.42, 87.26 and 111.98, new charges 81.42, 87.26 and 74.72, every check holding; spending counts 243.40 over their three due dates; with an invoice number on page 2 the file reads as one document with the invoice note (SC-128). |
| FR-131 | **No review for a certain split; the user can change it** (phase 2 FR-82). A bill split from a file by FR-128 with none of FR-129's reasons carries the note "Split from a file holding several bills" in its details, which is not a review reason. The document page's split panel names the file's bills (provider · due date · amount due), says "This file holds N bills", offers **Confirm split** (drops the split note, and FR-129's reasons, re-judging each bill by its own checks), **Merge with next** and **Split here** as for pay stubs, and shows no "waits in To check" warning for bills. A bill read as one with an FR-129 reason (a), (c) or (d) also shows the panel's **Split here**, so the user can split it. Your own split wins on later readings and the file is recorded again; when you change where the bills start, the next reading adds a `split_changed` guess note to each bill ("You changed where the bills in this file start; the file was read with your split."). | SC-129. |
| FR-132 | **Reading again** (phase 2 FR-83). Extract again on an unchanged reading gives the same bill records (ids, segments), lines, notes and split. A bill a later reading no longer finds stops counting (rejected automatically; restored if found again) with the note "The latest reading of this file no longer finds this bill; check how the file was split."; a bill you decided keeps your decision and gets the same note. No schema change: every existing bill is segment 0 already. | SC-130: BL-MULTI read twice gives the same 3 ids; after Merge with next on bill 2, the third record stops counting with the note. |
| FR-133 | **VOID bills** (phase 2 FR-85). A bill with a line whose whole text is VOID (as pay stubs: `*` and `-` around it allowed; inside a sentence it doesn't count) is recorded with the note "This bill is printed VOID, so it doesn't count." and rejected automatically, so it counts nowhere; a bill you decided is left alone. | SC-131 (a). |
| FR-134 | **Duplicate bills** (phase 2 FR-84 semantics; D17). A non-invoice bill with the same provider, due date (else issue date), amount due and currency as another bill that counts, and the same account last four when both print one, in this file or another, is recorded with its lines, noted "This bill repeats the one from P due D (A), so it doesn't count." and rejected automatically; the first recorded counts (a lower id). If the first is rejected, the duplicate counts on its next Extract again. Only exact duplicates stop counting: the same provider, account and due date with another amount due (a corrected bill) counts, and the later one carries the note "Another bill from P has the same due date." A bill you decided is left alone. | SC-131 (b): bill 2 of BL-MULTI captured again as a one-bill file is rejected with the note and counts once; BL-ACCT's two bills, same dates, different accounts, both count with no note. |
| FR-135 | **In the library** (phase 2 FR-84), a file holding several bills has no single amount; its date is the earliest non-rejected bill's due date (its counting date), and it is filed under the first non-rejected bill's provider and date; its shown due date and period are the first non-rejected bill's by segment. A file with one non-rejected bill shows that bill's amount, as today. | SC-128: BL-MULTI shows no single amount, date 2026-07-20, filed under CITY POWER & WATER and 2026-07-20. |

## Boundary with the receipt specs
- `specs/receipt-item-table` and `specs/receipt-tax-codes` are about `document_kind` receipt only: the item table on the
  document page, and tax shared by printed tax code. Both name bills as a non-goal ("Bills keep their own line table
  (`receipt.js` `billLines`)"). This spec changes no receipt reading, item table, tax line or share, and no page layout.
- Text-PDF receipts (quantity × unit price, lines to subtotal, subtotal + tax (+ tip) = total) are phase 1 FR-42, a later
  phase. Invoices share that arithmetic, which is why they move with FR-42 (D5).
- Bills are `receipts` rows, so the split shares code with the receipt split (`document_segments`, `split`, `confirm_split`,
  `set_split`, `retire_segments`). A receipt file splits exactly as today (model question, `SPLIT_NOTE`, review until
  confirmed); only files classified as bills take FR-128 – FR-135. FR-119 changes bill lines only; receipt item corrections
  are re-applied as today.
- Shared code: the receipt specs' recent changes (`EXTRACTION_VERSION` v39) sit in `documents/extraction.py` beside
  `bill_lines`; FR-121's version change comes after v39, and FR-120 keeps every receipt test passing.

## Invariants, privacy, security and data retention
- Nothing leaves the machine; no model or network call is added (the split rule reads lines only).
- Money stays exact (`core/money.to_minor`, the engine's `Decimal` tokens); no float decides a role, a sign or a boundary.
- Every recorded amount is a printed number, or (FR-118) the printed amount due − previous balance + payments, shown as worked
  out, or (FR-110, D21) a printed rate rounded half up to the minor unit, kept beside the rate as printed, which is what is
  shown and checked. A guess only chooses which printed cell, column or amount-due value; it never makes up an amount, and is written down
  (FR-124).
- What counts doesn't change for a correctly read single bill: the new charges, by line category, on the due date
  (docs/money.md). Each bill of a split file counts once; a VOID or duplicate bill counts nowhere.
- Every line of a split file is in exactly one bill's segment.
- A kept correction never moves to a line printing another amount (FR-119); nothing the user did is deleted.
- Identifiers stay masked to their last four (bill-kinds, unchanged); a holder title and an account key are evidence, not new
  stored fields (a holder from a title goes in the existing `line_holder`, FR-110); notes and the diagnose output never print a full account number.
- Synthetic fixtures only. P:\Finances, %LOCALAPPDATA%\HomeManager and P:\EvalCorpus are never read (CLAUDE.md); the `bill`
  diagnose mode (FR-127) is run by the user and prints shapes, never text or amounts.

## Errors, recovery, duplicates, restart behavior
- Engine exception: FR-115. Split rule exception: FR-129 (d). Roles undecided: a guess with a note (FR-105). Amount due
  undecided: a guess with a note (FR-117). Unplaced and unclassified lines: notes (FR-104, FR-112). Review from this feature
  only when today's checks fail after the best choices (FR-113), a correction is held (FR-119), or a boundary is uncertain
  (FR-129).
- Corrections outlive reading again, guarded by FR-119; Extract again is idempotent (FR-122, FR-132).
- Duplicates: a file captured twice is one file (as today); a bill repeating another counts once (FR-134).
- Retry and restart: a run that fails part-way publishes nothing, as today; Extract again then gives exactly the split and
  records of a clean run, with no duplicate segment.

## Nondeterministic outputs and how they are verified
- The engine and the split rule are deterministic, verified by exact values hand-written in the test contract, never computed
  by the code under test; generator cases take expected values from the generator's inputs.
- The model's classification comes from fixed stubs (`tests/model_server.py` `by_schema`); no test asserts live model output.
  The donated-corpus eval is run by the user; only `summary.json` is shared.

## Scenarios (expand into test-contract.md with design-tests before approval)
Fixtures are synthetic text PDFs (`tests/test_pdf.py` `make_pdf`), amounts right-aligned. Arithmetic below is hand-checked.

**BL-UTIL** (one page): `CITY POWER & WATER`, `Account Number 1234-5678-9012`, `Statement Date 09/20/2026`,
`Billing Period 08/15/2026 - 09/14/2026`, `Due Date 10/15/2026`; summary box `Previous Balance 82.10`,
`Payment Received 09/20/2026 -82.10`, `New Charges 97.55`, `Total Amount Due 97.55`; then `Electric Charges` with
`Usage Rate Charge` columns (`Energy Tier 1 500 kWh 0.1200 60.00`, `Energy Tier 2 140 kWh 0.1430 20.02`,
`Customer Charge 12.00`), `Taxes and Fees` (`State Tax 5.53`), `Total Current Charges 97.55`; a 12-month usage table; a
remittance stub `Account Number 1234-5678-9012`, `Due Date 10/15/2026`, `Amount Due 97.55`.
Check: 500 × 0.1200 = 60.00; 140 × 0.1430 = 20.02; 60.00 + 20.02 + 12.00 + 5.53 = 97.55; 82.10 − 82.10 + 97.55 = 97.55.

**BL-PHONE**: `METRO WIRELESS`, `Account Number 555-0100-7788`, `Due Date 10/12/2026`; summary `Previous Balance 120.00`,
`Payments -120.00`, `New Charges 118.50`, `Amount Due 118.50`; section `Alex 555-201-1111`: `Unlimited Plan 55.00`,
`Device Payment 24.99`, `Total for Alex 79.99`; section `Blair 555-202-2222`: `Basic Plan 35.00`, `International Pack 8.51`
with the indented line `(Canada and Mexico)` below it, `Total for Blair 43.51`; section `Account Credits`:
`Autopay Discount -5.00`. Check: 55.00 + 24.99 = 79.99; 35.00 + 8.51 = 43.51; 79.99 + 43.51 − 5.00 = 118.50;
120.00 − 120.00 + 118.50 = 118.50.

**BL-RENT**: bill-kinds' RENT lines (`tests/bill_kinds_fixtures.py` `RENT`) printed as a text PDF in two columns:
1,450.00 + 38.42 = 1,488.42 = Amount Due. **BL-HEADLESS**: BL-UTIL with every heading removed and the columns shuffled.

**BL-UTIL-R1** (FR-117): (a) BL-UTIL with `Balance Due 50.00` printed first on page 1 (a past-due banner), the box's
`Previous Balance 132.10`, `Payment Received -82.10`, `Total Amount Due 147.55`, and the stub's `Amount Due 147.55`.
Check: 132.10 − 82.10 + 97.55 = 147.55 (the carried check picks 147.55; 50.00 makes it fail). (b) BL-UTIL with no previous
balance, payments, new charges or `Total Current Charges` lines, `Balance Due 50.00` first, then `Total Amount Due 97.55`:
lines 97.55 pick 97.55. (c) BL-UTIL as printed but with no previous balance or payment lines, `Balance Due 50.00` first and
`Total Amount Due 147.55`, and the stub's `Amount Due 147.55`: new charges 97.55 is printed, so no check involves the amount due: 50.00 with the guess note.

**BL-UTIL-R2** (FR-118): BL-UTIL with no `New Charges` and no `Total Current Charges` line, `Previous Balance 150.00`,
`Payment Received -100.00`, `Total Amount Due 147.55`, stub `Amount Due 147.55`. Check: 147.55 − 150.00 + 100.00 = 97.55 =
the lines. Variant: amount due 150.55 (box and stub): 150.55 − 150.00 + 100.00 = 100.55 ≠ 97.55.

**MINI-BILL(k)** (one page each, for files of several): `CITY POWER & WATER`, `Account Number 1234-5678-9012`,
`Statement Date S`, `Billing Period B`, `Due Date D`; summary `Previous Balance P`, `Payment Received R`, `New Charges N`,
`Total Amount Due A`; `Customer Charge 12.00`, `Energy Charge E`, `State Tax T`, `Total Current Charges N`; stub
`Due Date D`, `Amount Due A`.

| k | S | B | D | P | R | E | T | N | A |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 07/02/2026 | 06/01/2026 - 06/30/2026 | 07/20/2026 | 80.00 | -80.00 | 64.80 | 4.62 | 81.42 | 81.42 |
| 2 | 08/03/2026 | 07/01/2026 - 07/31/2026 | 08/20/2026 | 81.42 | -81.42 | 70.20 | 5.06 | 87.26 | 87.26 |
| 3 | 09/02/2026 | 08/01/2026 - 08/31/2026 | 09/20/2026 | 87.26 | -50.00 | 58.50 | 4.22 | 74.72 | 111.98 |

Check: 12.00 + 64.80 + 4.62 = 81.42, 80.00 − 80.00 + 81.42 = 81.42; 12.00 + 70.20 + 5.06 = 87.26, 81.42 − 81.42 + 87.26 =
87.26; 12.00 + 58.50 + 4.22 = 74.72, 87.26 − 50.00 + 74.72 = 111.98. New charges over the three: 81.42 + 87.26 + 74.72 =
243.40.

- **BL-MULTI**: three pages, MINI-BILL(1), (2), (3).
- **BL-REMIT** (must not split): BL-UTIL over two pages; page 2 repeats `CITY POWER & WATER`, `Account Number 1234-5678-9012`,
  `Statement Date 09/20/2026`, then the usage table, the sentence `Your previous bill, due 09/15/2026, is past due.` and the
  remittance stub (`Due Date 10/15/2026`, `Amount Due 97.55`).
- **BL-ACCT**: two pages, MINI-BILL(1) and MINI-BILL(1) with `Account Number 1234-5678-3456` and MINI-BILL(2)'s P, R, E, T,
  N, A (same S, B, D as page 1).
- **BL-JOIN**: BL-MULTI with page 2's `Total Amount Due` and stub `Amount Due` lines removed.
- **BL-TWOONPAGE**: MINI-BILL(1) and MINI-BILL(2) printed one above the other on one page.
- **BL-NOKEY**: two pages; page 1 MINI-BILL(1); page 2 MINI-BILL(2) with no account, statement date or due date line.

| ID | FR IDs | Initial state | User/API actions | Expected final DB/files/UI state |
|---|---|---|---|---|
| SC-100 | FR-100 | BL-RENT; stub classifies correctly, amounts wrong | Extract | Rent 145000, Water 3842 from the cells; `3,200 GAL` is usage on the line, no amount; periods per bill-kinds |
| SC-101 | FR-101 | BL-UTIL with headings two-line, unknown wording, none | Extract each | Same lines and amounts in all three |
| SC-102 | FR-102, FR-110 | BL-PHONE; the stub gives a holder for Unlimited Plan and Basic Plan only (none for Device Payment and International Pack); a family whose Who has what lists phone lines ending 1111 (Alex) and 2222 (Blair) | Extract | Five lines (5500, 2499, 3500, 851, credit 500), each with its section; subtotals are no lines; `International Pack (Canada and Mexico)` cites both lines. Record: Unlimited Plan and Device Payment have `line_holder` naming Alex 555-201-1111, Basic Plan and International Pack Blair 555-202-2222, each line's evidence including its section title line; the credit has no holder; family routing (`finance/family_routing.py` `phone_member`) sets the first two lines' member to Alex and the next two to Blair, `member_source` configured. (b) The same with a stub that gives no holder for any line (D24): the same holders, evidence and members. (c) The same with a stub that gives Basic Plan the holder `Alex 555-201-1111`: Basic Plan has `line_holder` Blair 555-202-2222 and member Blair, and the bill's notes include "Line 3: the holder Alex 555-201-1111 differs from its section title; the title's holder Blair 555-202-2222 was used."; not a review reason |
| SC-103 | FR-103 | BL-UTIL, and a variant adding `If paid after 10/15/2026, pay $102.55` | Extract | Four box anchors, `Total Current Charges` (new charges) and the stub's amount due, all 9755, no extra lines; the late amount is no anchor and no line |
| SC-104 | FR-104 | BL-UTIL plus one label-and-amount line outside every column | Extract | One unplaced note; usage table gives nothing; no review reason from either |
| SC-105 | FR-105 | (a) BL-UTIL columns shuffled; (b) BL-HEADLESS; (c) a `This Bill` / `Last Year` pair | Extract | (a), (b) charge column by quantity × rate and the sums; (c) Last Year is other |
| SC-106 | FR-106 | BL-PHONE, discount answered `service`; a variant printing it unsigned under `Account Credits` | Extract | Credit 500 off both times, a note in the first; lines add up to 11850 |
| SC-110 | FR-110, FR-113 | BL-UTIL, stub amounts all wrong | Extract; open the page | Printed amounts; checks hold; counts automatically; no `table_grid` table in any request after classification. Energy Tier 1: quantity 500 kWh, `unit_price_minor` 12, no rate text kept; Energy Tier 2: quantity 140 kWh, `unit_price_minor` 14, details `unit_price.text` `0.1430` citing its printed words, line total 2002; no "more precision" issue on either; both product checks hold (140 × 0.1430 = 20.02, not 140 × 0.14 = 19.60); the page shows Unit price 0.1430 for Tier 2 |
| SC-111 | FR-111 | BL-UTIL read as `general` | Extract; open the page | Previous balance 8210 and payments 8210 in details; carried check holds; page shows both rows, then Amount due 97.55 |
| SC-112 | FR-112 | BL-PHONE; stub lists `Total for Alex` as a line and omits `Device Payment` | Extract | Subtotal left out with a note; Device Payment 2499 recorded with the printed label and a note, and holder Alex 555-201-1111 from its section title, its evidence including the title line (FR-110, D22, D24); no review reason; lines add up to 11850 |
| SC-113 | FR-113 | (a) BL-PHONE with `Total for Blair 44.51`; (b) BL-UTIL with `New Charges` and `Total Current Charges` both printed 99.55 | Extract | (a) note naming page 1 and 44.51, counts automatically; (b) review with today's "New charges: the lines add up to…" reason (and the carried check's, 82.10 − 82.10 + 99.55 ≠ 97.55) |
| SC-114 | FR-114 | Two-page bill: page 1 charge table, page 2 prose with a stub line | Extract | Page 2 line from the model with the note; page 1 from cells |
| SC-115 | FR-115 | BL-UTIL with the engine made to raise; BL-MULTI with the engine made to raise | Extract | Photo-bill reading with the failure note, logged without text; BL-MULTI still gives 3 bills, each read that way |
| SC-116 | FR-116 | SC-102 done | `GET /api/provenance` for the wrapped line and Amount due | Both lines listed; Amount due cites its printed words |
| SC-117 | FR-117 | BL-UTIL-R1 (a), (b), (c) | Extract each | (a) amount due 14755, no guess note, carried check holds; (b) 9755, no guess note; (c) 5000 with the guess note naming 50.00 and 147.55, guess kind `amount_due` |
| SC-118 | FR-118 | BL-UTIL-R2 and its variant | Extract each | Total 9755, amount due 14755, the worked-out note, counts automatically, no carried check; variant: total 10055, review with the lines reason naming 100.55 |
| SC-119 | FR-119 | BL-PHONE recorded at v39 with a stub that missed `Device Payment` (positions: 1 Unlimited Plan 55.00, 2 Basic Plan 35.00, 3 International Pack 8.15 misread, 4 Autopay Discount), undecided; the user set member Blair on line 2 and price 8.51 on line 3. BL-UTIL recorded at v39 with State Tax misread 5.35 at line 4, price corrected to 5.53, and member Alex on line 3 (Customer Charge 12.00) | Extract again under the new version | BL-PHONE: lines 1 Unlimited 5500, 2 Device Payment 2499 (no member), 3 Basic Plan 3500 (member Blair, kept by identity), 4 International Pack 851, 5 credit 500; `member:2` and `price:3` held, two review reasons naming 24.99 vs 35.00 and 35.00 vs 8.15; corrections still in history. BL-UTIL: line 4 is 553 and line 3 has Alex, no held reason, counts automatically. Photographed (D15): bill-kinds' RENT image recorded with member Blair on line 2 (Water 38.42), re-read with a stub adding a line above it: `member:2` held with the reason naming the new line 2's amount and 38.42 |
| SC-120 | FR-120, FR-125 | Bill-kinds RENT images, the invoice table test, statement and pay stub generators and suites, pay stub split suite, receipt suites | Run | Pass, except tests the contract lists |
| SC-121 | FR-121 | A BL-UTIL bill read at v39; a reviewed bill; BL-MULTI recorded at v39 as one undecided bill | Start; Extract again | Undecided one re-read by the engine; reviewed one unchanged; BL-MULTI becomes 3 bills, the first keeping the old id as segment 0 |
| SC-122 | FR-122 | Any fixture, and BL-MULTI | Extract, then Extract again | Identical values, notes, guesses, evidence and split; zero engine or split model calls |
| SC-123 | FR-123 | 100+ seeded generated bill files | Generator test | Every line, summary amount and split exact |
| SC-124 | FR-124 | Synthetic corpus with the five aligned files | `python -m evals.run` | `bill_readers` counts; aligned files exact; BL-MULTI split right; guesses all right; allowlist passes |
| SC-125 | FR-127 | BL-MULTI and BL-UTIL as files | Run the script with `bill` | Per-page counts and roles; "3 bills: pages 1, 2, 3" and "1 bill"; no fixture word, amount, date or account digit in the output; the temporary folder is gone |
| SC-126 | FR-128 | BL-MULTI; BL-REMIT; BL-ACCT; a one-page BL-UTIL; BL-MULTI as a scanned PDF (page images, lines from the stubbed reading) and as three PNG pages combined into one document; a single photographed MINI-BILL(1) | Extract each | 3 bills (segments 0 – 2, due dates 2026-07-20, 2026-08-20, 2026-09-20); 1 bill, no split note; 2 bills with last fours 9012 and 3456; 1 bill, no `document_segments` rows; scanned and combined: 3 bills each with the same due dates, read like photographed bills (no engine rows); single image: 1 bill, no `document_segments` rows. Every line in exactly one segment |
| SC-127 | FR-129 | BL-JOIN; BL-TWOONPAGE; BL-NOKEY; BL-MULTI with the split rule made to raise | Extract each | BL-JOIN: 2 bills, pages 1 – 2 in review with (b) naming 08/20/2026 (and today's lines reason: 16868 against 8142), page 3 (MINI-BILL 3) counts automatically with the split note; BL-TWOONPAGE: 1 bill in review with (a) naming 07/20/2026 and 08/20/2026 (and today's lines reason); BL-NOKEY: 1 bill in review with (c) naming 81.42 and 87.26; raising: 1 bill in review with (d), logged without text |
| SC-128 | FR-130, FR-135 | BL-MULTI, empty ledger | Extract; open the library | 3 bills: lines (1200, 6480, 462), (1200, 7020, 506), (1200, 5850, 422); totals 8142, 8726, 7472; amounts due 8142, 8726, 11198; previous balance and payments in details; every check holds; each verified; spending counts 8142 on 2026-07-20, 8726 on 2026-08-20, 7472 on 2026-09-20 (24340); library: no single amount, date 2026-07-20, filed under CITY POWER & WATER and 2026-07-20. Variant (FR-130, D16): page 2 also prints `Invoice Number INV-2002`: 1 bill (segment 0), no `document_segments` rows, the note "A part of this file is an invoice, so the file was read as one document.". Variant: a checking payment −81.42 to CITY POWER & WATER on 2026-07-18 is proposed as bill 1's match only |
| SC-129 | FR-131 | SC-126 BL-MULTI; and SC-127 BL-TWOONPAGE | Extract; `GET …/segments`; Merge with next on bill 2; Extract again; Confirm split. For BL-TWOONPAGE: Split here at MINI-BILL(2)'s first line | Each of the 3 bills has the split note and none is in review for it; panel says "This file holds 3 bills", names CITY POWER & WATER · due date · amount due, no To check warning; after the merge 2 segments and the user's split wins on Extract again, with the `split_changed` guess note; confirm drops the note. BL-TWOONPAGE: the panel's Split here is offered; after it, 2 bills with MINI-BILL(1) and (2)'s values, reason (a) gone, both verified |
| SC-130 | FR-132 | SC-126 BL-MULTI | Extract again twice; then Merge with next on bill 2 and Extract again; decide bill 3 first in a second library and do the same | Same 3 ids both times; after the merge, segment 2's bill is rejected automatically with the "no longer finds this bill" note; a decided bill 3 keeps its decision with the note |
| SC-131 | FR-133, FR-134 | (a) BL-MULTI with a line `VOID` on page 2; (b) BL-MULTI recorded, then MINI-BILL(2) alone as a new file; then bill 2 of BL-MULTI rejected by the user and the new file Extracted again; (c) BL-ACCT | Extract | (a) 3 bills, bill 2 rejected with the VOID note, spending 8142 + 7472 = 15614; (b) the new file's bill rejected with "This bill repeats the one from CITY POWER & WATER due 2026-08-20 (87.26)…", 8726 counted once; after the user rejects the original, the new bill counts on Extract again; (c) both count, no duplicate or same-due-date note |

## Supersedes
- pdf-table-engine FR-41 "their sum equals the amount due, and previous balance − payments + new charges = balance where
  printed" → FR-105, FR-111, FR-113, FR-117, FR-118 with bill-kinds FR-49's arithmetic: the lines add up to the **new
  charges** (printed, else worked out by FR-118; the amount due only when neither), because the amount due may include a
  past-due balance; and the carried check is against the **amount due**.
- pdf-table-engine non-goal "Splitting one PDF into several accounts" → for bill files, FR-128 – FR-135. Statements are
  unchanged.
- bill-kinds FR-43 (previous balance asked on the rent form only) → on text-PDF bills of either kind, read from the print
  (FR-111). The model forms are unchanged.
- pdf-table-engine-paystubs-cleanup non-goal "`anchor_rows` and `anchor_summary` stay for … bills" → not for non-invoice
  text-PDF bills (FR-110, FR-111).
- docs/money.md "Bills and their lines" "With no new charges printed, the lines' sum counts" → on an engine-read bill printing
  its previous balance and payments, the worked-out new charges count (FR-118).
- docs/money.md "Reading a statement or receipt again" / `apply_corrections` re-applying a bill line's position correction to
  whatever line is there → FR-119.

## Out of scope / product decisions requiring approval
**Answered (2026-11-08, see D4 – D20):** U1, OD-1 – OD-11, R1 – R7. None is to be asked again.

**Answered (2026-11-08, see D21 – D22, D24 – D25):** test contract G1, G2, G12 and the rate-precision wording.

**Left to the plan (user's decision, D23):** the test contract's gaps G3 – G8 are not settled here; the plan chooses and
records each. G9 – G11 stand as the test contract states them.

**Open decisions:** none. **Candidate domain risks:** none open.

**Out of scope:** photographed and scanned bills read by the engine; invoices and files of several invoices; receipts and the
receipt split; budget billing; two bills on one page split automatically (D18); consolidated multi-account bills; the
cross-bill previous-balance check (D19); holding record-level corrections after a split change (D20); new bill kinds; the
Tables tab; per-provider templates; donating split bills.
