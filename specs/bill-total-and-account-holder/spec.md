# Bills: the account holder as the lines' person, and the printed total as the amount due
Feature: bill-total-and-account-holder

<!-- Approval state lives in approvals/<slug>.json and is bound to this file's content hash.
     Do not add a Status line: changing it would change the hash. Check with gate.py. -->

Amends: `specs/pdf-table-engine-bills/spec.md` (built and approved) FR-103 (two new kinds of printed line), FR-110 (who a line
is for, for display), FR-117 (its fallback when no check decides), FR-120 (photographed bills, for the amount due only, FR-145),
FR-128 (what counts as a part's own amount due) and its non-goal "any change to how a bill … is matched to its payment, is shared",
for FR-142 and FR-139 only; `specs/bill-kinds/spec.md` FR-50 (one more row below Amount due, FR-142). Every other requirement of
those specs stands, including FR-100 – FR-102, FR-104 – FR-116, FR-118, FR-119, FR-121 – FR-135, D1 – D25, and bill-kinds FR-40 –
FR-49, FR-51 – FR-58. IDs continue after pdf-table-engine-bills (FR-135, SC-131).

## Decisions already made (not to be re-asked)
- **D1 The wanted behaviour, account holder** (user, 2026-11-12): "So my person column should show my name since the bill
  literally says Account Name: <my name> since this name matches the profile name i have it should show my name but it says
  shared so this is incorrect behavior that needs fixing."
- **D2 The wanted behaviour, total** (user, 2026-11-12). Their bill prints `Current Charges due 11/01/2026 $62.91` and `Total
  Current Charges $1,667.91`: "It should default on Total rather than current for all bills but the due date should be captured
  since this is when the total is being paid."
- **D3 This is a behaviour change, not a defect.** No approved requirement says the bill's account name gives a person
  (pdf-table-engine-bills FR-102 / FR-110 give a holder only from a section title or the row's own lines), and FR-103 needs
  the whole label to match a phrase, so `Current Charges due 11/01/2026` is no anchor as approved. So this is an amendment,
  not `debug-issue`.
- **D4 Fixtures are synthetic.** The user's bill is not read; the scenario BL-TOTAL prints the user's two lines word for word
  with a synthetic provider and the synthetic name `Jordan A. Rivera`. P:\Finances, %LOCALAPPDATA%\HomeManager and
  P:\EvalCorpus are never read (CLAUDE.md).

## Goal / users / scope / non-goals
**Goal.** (A) A bill that prints whose account it is (`Account Name: Jordan A. Rivera`) shows that person on every line that
has no holder of its own, by the name the app knows them by (the profile's or the family member's name) when the printed
name is theirs, and by the printed name otherwise. "Shared" then means only what it says. (B) A bill's **amount due** is the
**total** it prints, not a "due now" part of it, on every bill; the date printed with the "due now" amount is the bill's
due date when no other due date is read, and the "due now" amount is kept, shown and still matches a payment.

**Users.** The household user recording bills and reading the bill's lines on the document page, in their own library or
in the family's inbox.

**In scope.**
- Reading the account holder from the bill's printed lines (FR-136), matching it to a person (FR-137), what the Person cell
  shows and what "Shared" means (FR-138), the account holder on the page (FR-139), on a family's bill (FR-140).
- A "due now" line (FR-141), which printed amount becomes the amount due (FR-142, FR-143), the due date from that line
  (FR-144), photographed bills (FR-145), a file of several bills (FR-146).
- Stored bills, re-reading and corrections (FR-147), determinism, diagnose, generator, evals and docs (FR-148 – FR-150).

**Non-goals.**
- What a bill **counts** (`total_minor`, the new charges, on the due date, by line category) does not change; neither do
  budgets, the forecast and the recurring bill's expected amount, which follow it (OD-1).
- Family routing by Who has what (`finance/family_routing.py` `phone_member`, cards) is unchanged: a name never assigns a
  line to a member (OD-7); the account holder can only make a whole-bill suggestion the user confirms (FR-140).
- Invoices (`invoice_marker`, `invoice_number` or `invoice_total` read) keep today's path (pdf-table-engine-bills D5); their
  `bill_to` is not an account holder (OD-5).
- Receipts, statements, pay stubs; the Tables tab; any model question, model form or network call; any new column or
  migration; per-provider templates (D1 of pdf-table-engine).
- Reading a person's name from anywhere but a labelled account-name line (an address block, a greeting "Dear Jordan").

## Existing behavior (verified paths, assumptions, unknowns)
Paths under `src/home_manager/` unless noted. Read at HEAD `5a560a7`.

**Who a line is for today.**
- A line's holder is `receipt_items.line_holder`, printed text only: from a holder section title above it
  (pdf-table-engine-bills FR-102, FR-110, D22, D24; `documents/extraction.py` `anchor_bill` ~:1529 – :1544), else the model's
  holder kept only when a word of it or the number's last four is printed in the row's own lines (`bill_lines` :3368,
  `name_supported` :2232). The bill's account name is never read: no bill field, engine label or note mentions it
  (`HEADERS["bill"]` :69 has `account_reference`, the provider's account number, and `bill_to` for invoices; `grep account_name`
  finds only investment and loan forms).
- The Person cell (`app/static/receipt.js` `billLines` :206 – :257): in the family's inbox (`familyMode`) a select of the
  family's members whose empty choice reads "Shared (taxes, fees)"; elsewhere text: the member's name, else "Someone in the
  family" for a member id, else `line_holder` with trailing digits, spaces, `()` and `-` stripped (`Alex 555-201-1111` →
  `Alex`), else **"Shared"**. In a person's own library `people` is empty, so a line without `line_holder` always says Shared.
- **Matching names to people: none exists.** A holder becomes a member only by the phone number's last four digits listed in
  the family's Who has what (`finance/family_routing.py` `phone_member` :60, applied in `FamilyRouting.refresh`, `member_source`
  `configured`); a hand-set member is `member_source` `user` (`finance/ledger.py` `_set_line` ~:3176). `normalize_name`
  (`finance/ledger.py` :379) is the merchant key (upper case, legal suffixes and store numbers removed); it is not a person
  matcher. `suggest` (`family_routing.py`) says "Nothing on it says whose it is" for a bill with no listed card or phone line.
- **Where people's names are.** A profile's name is in `<settings folder>\profiles.json` (`app/profiles.py`, `clean_name` :24:
  whitespace collapsed, at most 60 characters, default "My profile" for the first migrated profile, docs/family.md "Profiles"),
  not in the library. `Manager.people()` (`app/manager.py` :311) lists the profile's name, the spouse named on the latest tax
  return (`TaxYears.spouse_names`), and in a family every member's name; `GET` settings sends `profile` and `people` to the
  page. Family members' names are in `family.json` (`app/family_sync.py` `add_member`, `clean_name`).
- `value["shareable_by_line"]` (`finance/ledger.py` ~:2050) is true when the lines have more than one distinct `line_holder`
  or member. A bill shared by line keeps `record_shares.member_id` (docs/family.md "Sharing a bill by line"); lines nobody is
  named on are shared out in proportion (`splits.line_shares`).

**Which amount is the amount due today.**
- `receipts.amount_due_minor` is "everything the bill asks for, past-due balance included" (model instruction,
  `documents/extraction.py` :137 – :138); `total_minor` is the new charges and is what counts (`bill_lines` :3453 – :3475;
  docs/money.md "Bills and their lines"). The page's last row, **Amount due**, is `amount_due_minor` (bill-kinds FR-50,
  `Ledger.bill_summary` ~:2586); the split panel and the duplicate rule (FR-134, `ledger.py` ~:1567 – :1579) name a bill by its
  amount due; the library's file amount is `total_minor` (`library/storage.py` :649).
- Engine anchors (`documents/charge_tables.py` `ANCHOR_WORDS` :56 – :61): `new_charges` includes `total current charges`;
  `amount_due` is amount due, total amount due, total due, balance due, amount to pay, total amount to pay, payment due.
  `clean_label` (:198) removes a date and a directly preceding `by`, `on or before`, `as of` or `on`, but not `due`; `anchor_kind`
  (:207) needs the whole cleaned label to be a phrase. So `Current Charges due 11/01/2026 $62.91` cleans to `current charges
  due`, no anchor: read from the code (not run), it is a charge row when its amount sits in a charge column, else an unplaced
  line (FR-104). `Total Current Charges $1,667.91` is a new-charges anchor (1,667.91), so on an engine-read text PDF the bill
  already **counts** 1,667.91; with no amount-due anchor, the amount due is the model's value (`anchor_bill` keeps the model's
  field when no anchor fills it), here 62.91 per the user's report.
- FR-117 (`anchor_bill` ~:1618 – :1640): among different amount-due anchors, the value making the carried check, else the lines
  check, hold; else the **first** on the bill's first page, with an `amount_due` guess note.
- FR-118: no new charges printed but previous balance and payments printed → new charges = amount due − previous balance +
  payments; the carried check isn't run.
- Payment matching (`finance/reconcile.py` `bill_payment` :438, :444): money out of exactly `total_minor` or `amount_due_minor`,
  from the issue date to five days after the due date, naming the provider or account number.
- The due date is the model's answer, kept only when its cited line prints that date (`bill_dates` :909, bill-kinds FR-48);
  a date on a "Due" line is never Issued (FR-46). The engine gives no due date. FR-128's key line `due date` needs the label at
  the line's start, so `Current Charges due 11/01/2026` is no key line.
- Corrections: a record-level correction (`amount_due`, `due_date`, the new charges, a `detail:` field) is re-applied after every
  reading by `Ledger.apply_corrections` (`finance/ledger.py` :2953, latest correction of each field; `reapply_detail` :2665
  applies a `detail:` correction only when the reading still has that detail). Line corrections are guarded by FR-119. A decided
  (confirmed or rejected) bill is never rewritten. `EXTRACTION_VERSION` is `typed-extraction-v50-bill-account-cells` (:52).

**Assumptions**
- A5: An account name is printed as a label at the start of a line followed by the name (`Account Name: Jordan A. Rivera`,
  `Customer Name ..... JORDAN RIVERA`), possibly followed on the same line by another label (`Account Number …`).
- A6: A "due now" amount is printed with a summary phrase, the word `due` and a date on one line, as in D2.

**Unknowns**
- U4: On the user's bill, what the charge lines add up to (62.91 or 1,667.91), whether a previous balance or credit is printed,
  and whether it is a text PDF. This decides whether the bill counts automatically after the change (see SC-132 (b)); asked as
  OD-10, answerable without sharing the bill.

## Functional requirements

### A. The account holder
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-136 | **Reading the account holder.** On every non-invoice bill (text PDF, photographed, scanned, combined images), an **account-name line** is a transcribed line of the bill whose text starts with one of the labels `account name`, `account holder`, `account holder name`, `customer name`, `name on account` (a fixed list kept with FR-103's in one place and documented; case ignored; a colon, dot leaders or `-` may follow), directly followed by a value holding a letter. The **account holder** is that value as printed, whitespace collapsed, ending before the next label of FR-103, FR-128 or this list printed on the same line (`Account Name: JORDAN A RIVERA  Account Number 4455-…` → `JORDAN A RIVERA`), cut to 80 characters. It is read from the lines by code, not asked of the model (no model form changes). The first account-name line of the bill in reading order is used; a different value printed later adds the note "The account name is printed as X and Y; X, the first, was used." A label inside a sentence or after other words (`Your account name is …`, `Service Account Name …`) is no account-name line. It is kept in the bill's details as `account_holder` (`{"text", "locator"}`, an existing column, no migration), never in any line's `line_holder`. A bill printing none has no account holder. | BL-TOTAL gives account holder `Jordan A. Rivera` citing its line (SC-132); the same line photographed gives the same (SC-140); `Your account name is Jordan` gives none (SC-134). |
| FR-137 | **Matching a printed name to a person.** The **candidates** are, in a person's own library, the profile's name and the spouse names of `Manager.people()`; in a family's library, the family's member names. Matching happens when the record is shown (the profile's name is not in the library), so renaming a profile or member changes what is shown with no re-read. Both names are compared after: Unicode NFKC, accents removed, case ignored; `Last, First [Middle]` (one comma) read as `First [Middle] Last`; the titles `mr`, `mrs`, `ms`, `mx`, `dr` and the suffixes `jr`, `sr`, `ii`, `iii`, `iv` dropped; other punctuation removed. A printed name naming two people (`&`, `and`, `/`, `+` between words) matches nobody. Two names **match** when (a) both have two or more words, their first words are equal, their last words are equal, and any middle word they both have in the same place is equal or is the other's initial (`A` ↔ `Alex`), a middle word only one has being ignored; or (b) one of them is one word and it equals the other's first word (OD-6). A first-name initial (`J. Rivera`) never matches. The printed name **is a person's** when exactly one candidate matches; none or several (two members named Jordan) is no match. The candidate "My profile", or any name containing no letter, never matches anything. The same rule applies to a line's own holder after its digits are removed (`Alex 555-201-1111` → `Alex`), for what is shown only (FR-138). | SC-133: the matching table, each row exact. |
| FR-138 | **What the Person cell shows** (the document page's bill lines, outside the family's inbox; the server sends the shown text and where it came from with each line, so the page decides nothing). For each line, in order: **(1)** a member set on the line (by hand or by Who has what): the member's name, as today; **(2)** the line's own `line_holder`: the matched person's name (FR-137), else the holder with its trailing number stripped, as today; **(3)** the bill's account holder, when the line has no holder of its own and the bill is not shared by line (`record_shares.member_id` absent): the matched person's name, else the account holder as printed; **(4)** otherwise **Shared**. A section holder title therefore wins over the account holder for its lines. After this change "Shared" appears only on a line with no holder of its own on a bill that prints no account name, or on a line nobody is named on in a bill shared by line in the family (it is then truly shared out with the taxes and fees). The cell's tooltip / small text says where the person came from ("Account name on the bill", "Printed for this line"). | BL-TOTAL in a profile named `Jordan Rivera`: every line shows `Jordan Rivera` (SC-132); after renaming the profile `Jordan Alex Rivera` the lines show the new name with no re-read, and after renaming it `Sam Lee` they show the printed `Jordan A. Rivera` (SC-133); BL-PHONE-AH: titled lines show their holders, the credit line the account holder (SC-135); no account name: Shared as today (SC-134). |
| FR-139 | **The account holder on the page.** The bill's fields show **Account holder** with the printed name, its Find lighting the account-name line (source beside the record), and, when it matches, "(you)" or the matched person's name. It is correctable like the bill's other details (text; cleared means "no account holder"); the correction is kept in the history and re-applied after a reading as other `detail:` corrections are. A corrected account holder is matched like a printed one. | SC-139: Correct sets `Morgan Lee` → Person cells show `Morgan Lee`; Extract again keeps it; Undo restores the printed one. |
| FR-140 | **On a family's bill** (the family's inbox). Lines' members are set only as today (Who has what, or by hand); the account holder never sets `member_id`, so a bill shared by line divides exactly as before (`splits.line_shares` unchanged). In the inbox's Person select the empty choice keeps "Shared (taxes, fees)". The **suggestion** (`suggest`) gains one rule, after the phone and card rules and before "Nothing on it says whose it is": a bill with no line holders and no listed card whose account holder matches exactly one member (FR-137 against the members' names) is suggested for that member, with the reason "The account is in <member>'s name". It is only a suggestion; nothing is sent until **Send**, as today. In a member's own library, a delivered bill shared by line shows Shared on its lines nobody is named on (FR-138 (3) doesn't apply); a bill delivered to one person shows FR-138's rule with that person's profile. | SC-136: a family with members Alex Sample and Blair Sample; BL-UTIL-AH (`Account Name: Blair Sample`) is suggested for Blair with that reason; BL-PHONE-AH keeps its "Share by line" suggestion and the same parts as SC-102. |

### B. The bill's total
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-141 | **A "due now" line.** A line whose label, cleaned as FR-103 (`clean_label`), is a **new-charges** or **amount-due** phrase of FR-103 followed by `due`, `due on`, `due by` or `payable by` and a date (`Current Charges due 11/01/2026 $62.91`, `New Charges Due Nov 1, 2026 62.91`) is a **due-now line**: a summary anchor of a new kind `due_now`, with its printed amount and its printed date. It is never a charge row, never the new charges and never an amount-due anchor for FR-117 (so it can't be counted twice). `Amount Due by 11/01/2026` stays an amount-due anchor as today (FR-103's `by` + date); a late line (FR-103) is never a due-now line. On text pages the engine finds it (FR-104's accounting counts it as an anchor); on photographed and scanned bills the same label rule is applied to the lines the model cites (FR-145). | BL-TOTAL's `Current Charges due 11/01/2026 $62.91` is a due-now anchor (62.91, 2026-11-01), no charge row, no unplaced line (SC-132). |
| FR-142 | **The amount due is the bill's total.** A bill's amount due (`amount_due_minor`, the page's Amount due row, the split panel, FR-134's duplicate rule) is chosen in this order: **(a)** amount-due anchors are printed: FR-117 as built, except that when no check decides, the first amount-due anchor whose phrase starts with `total` (total amount due, total due, total amount to pay) is used, else the first, with the guess note "The amount due is printed as X and Y; X, the total, was used." (or "…, the first on page N, was used." as today); **(b)** no amount-due anchor but a due-now line is printed: the bill's **total**, which is previous balance − payments + new charges when the previous balance and payments are printed (a printed 0.00 counts) and new charges are printed or worked out, with the note "The amount due is worked out as previous balance P − payments R + new charges N = A."; else the new charges when printed (`Total Current Charges 1,667.91`); else the due-now amount. When the chosen total differs from the due-now amount the bill gets the note "The bill prints <label> <date> <amount> and a total of <A>; the total is the amount due." **(c)** neither: as today (the model's value with today's checks). Amounts are never added together except in (b)'s worked-out total, so a total that already includes the previous balance (`Total Amount Due 147.55`) is never added to again. The carried check is not run when (b) worked the amount due out (it would hold by construction, as FR-118). | SC-132: amount due 166791 with the note; SC-137: 50.00 − 20.00 + 97.55 = 127.55 worked out; SC-138: `Total Amount Due 147.55` stays 147.55, not 245.10; SC-141: BL-UTIL-R1 (c) now 147.55 with the "total" note. |
| FR-143 | **The due-now amount is kept and still matches a payment.** When a due-now line is printed and its amount differs from the amount due, it is kept in the bill's details (`due_now`: `{"minor", "date", "label", "locator"}`) and shown on the page as one row below **Amount due**, with its printed label and date (`Current Charges due 11/01/2026 62.91`) and its Find; it is not one of the rows that add up to Amount due (bill-kinds FR-50's difference ignores it). `bill_payment` accepts money out of exactly the new charges, the amount due **or the due-now amount**, in the same window and with the same provider or account rule; a payment of either is proposed as the bill's match, several are a question as today. What counts is unchanged: `total_minor` is the new charges (printed, worked out by FR-118, or as today), and the lines check is against them (FR-105 (b) unchanged), so budgets, the forecast and the recurring bill's expected amount (from `total_minor`) don't change. | SC-132: details `due_now` 6291 / 2026-11-01; the page shows the extra row; a checking payment −62.91 on 2026-10-30 to LAKESIDE GAS & ELECTRIC is proposed as the match, and so is −1,667.91 in a variant; spending counts 166791 on 2026-11-01. |
| FR-144 | **The due date from the due-now line.** The bill's due date stays the model's answer kept by bill-kinds FR-48; when it is missing or dropped, the due-now line's date is the due date, cited to that line (and the bill counts on it). When both are kept and differ, the model's (or a `Due Date` key line's) stands and the bill gets the note "The bill also prints <label> <date>." The due-now line's date is never Issued (FR-46, unchanged) and is no FR-128 key line. | SC-132 (c): the model gives no due date → due date 2026-11-01 citing the due-now line, counting on it; SC-132 (d): `Due Date 11/15/2026` also printed → 2026-11-15 with the note. |
| FR-145 | **Photographed and scanned bills** (no engine). When the model's amount due cites a line that is a due-now line by FR-141's rule, and the model's new charges cite a different line whose label is a new-charges phrase starting with `total`, FR-142 (b) applies to the model's (cited, checked) values: the amount due becomes the new charges (or the worked-out total when previous balance and payments are read), the due-now amount is kept by FR-143 and the due date by FR-144. Otherwise a photographed bill reads exactly as before (FR-120). | SC-140: BL-TOTAL as a PNG with a stub answering amount due 62.91 citing the due-now line and new charges 1,667.91 citing `Total Current Charges`: amount due 166791, `due_now` 6291, account holder read (FR-136). |
| FR-146 | **A file of several bills.** For FR-128 a part "prints its own amount due" when it prints an amount-due anchor **or a due-now line**; FR-129 (b) fires only when it prints neither. Each part applies FR-136 and FR-142 – FR-144 to its own lines; an account-name line belongs to the part it is printed in and is never carried to another part. | SC-142: MINI-DUE(1), (2) give 2 bills, amounts due 81.42 and 87.26, no FR-129 (b) reason. |

### Stored bills, determinism, measurement
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-147 | **Existing bills.** `EXTRACTION_VERSION` changes (from `typed-extraction-v50-bill-account-cells`). No migration rewrites a record. Extract again re-reads an undecided bill: it gains its account holder, due-now amount and the amount due of FR-142. **A correction of yours wins:** every record-level correction (amount due, due date, provider, a `detail:` field including the account holder) is re-applied after the re-read as today (`apply_corrections`), so a bill whose amount due you corrected keeps your value, not the new total; line corrections stay guarded by FR-119. A bill you confirmed or rejected is never rewritten (OD-8): it keeps its amount due and shows its lines as today (no account holder) until you set **Account holder** by Correct (FR-139). | SC-139, SC-143: undecided BL-TOTAL read at v50 (amount due 62.91 from the model) → 166791 after Extract again; with your earlier correction of amount due to 70.00 → 7000, the correction in history; a confirmed one unchanged. |
| FR-148 | **Deterministic and unchanged elsewhere.** The same reading gives the same account holder, match, due-now line, amount due, notes and evidence; Extract again on an unchanged reading changes nothing; no model or network call is added. Every existing bill, invoice, receipt, statement and pay stub test passes unchanged except those the test contract lists one by one with the requirement that changes them (at least SC-117 (c), FR-142 (a)). | SC-144. |
| FR-149 | **Diagnose, generator, eval.** The `bill` diagnose mode (FR-127) also counts account-name lines and due-now lines per page (present or not; never the name, label text, amount or date). The bill generator (FR-123) gains: an account-name line in each label form, alone or followed by an account number on the same line; a due-now line with and without a printed amount due, total current charges and previous balance. The documents eval's `bill_readers` gains `account_holder_read`, `due_now` and `amount_due_total` counts (counts only; `summary.json` passes the allowlist); a synthetic bill with an account-name line and a due-now line is appended after the existing documents so no id or answer changes. | SC-145. |
| FR-150 | **Docs.** `docs/documents.md` "Bill lines from the printed columns" (the account-name labels and the due-now line beside the summary phrases) and "Several bills in one file" (a due-now line is a part's own amount due); `docs/money.md` "Bills and their lines" (the amount due is the printed total; the due-now amount is kept, shown and matches a payment; what counts is unchanged; the account holder and the Person column) and "Corrections" if it lists bill fields; `docs/family.md` "Family inbox" (the account-name suggestion) and "Sharing a bill by line" (lines nobody is named on still say Shared and are shared out); `docs/evals.md` (the new counts); `docs/open-work.md` (whatever OD-5, OD-8 and OD-6 leave unbuilt: invoices' `bill_to`, decided bills without an account holder, a bare `Name:` label). Headings stay stable. | Doc diff present. |

## Invariants, privacy, security and data retention
- Nothing leaves the machine; no model or network call is added. The account holder is read from lines already transcribed.
- The account holder is personal data kept in the bill's details in the person's own library, as the bill's text already is.
  The profile's name is never written into the library (matching happens when shown, FR-137). The diagnose output, eval
  counts, logs and `log_failure` never print a name; notes that name it are in the bill's own details only.
- Money stays exact; every amount due is a printed amount or, in FR-142 (b), printed previous balance − payments + new charges,
  shown as worked out. A due-now amount is never added to another amount.
- What counts is unchanged (new charges, by line category, on the due date); each bill counts once.
- A name never assigns a line or a bill to a member by itself (FR-140); Who has what stays the only automatic owner.
- Nothing the user did is lost: corrections win over the new reading (FR-147).
- Synthetic fixtures only (D4).

## Errors, recovery, duplicates, restart behavior
- An account-name line whose value is unreadable (no letter) gives no account holder, no note. An unmatched or ambiguous name
  shows as printed (FR-137, FR-138); no review reason.
- FR-142's choices are notes, never review reasons; today's checks (the lines against the new charges, the carried check when
  run) still send a bill to review.
- The duplicate rule (FR-134) compares amounts due; a bill read before and after this change in two files could differ in
  amount due until both are re-read, so both count until then (the rule stays exact-match only).
- Extract again is idempotent (FR-148); a failed run publishes nothing, as today.

## Nondeterministic outputs and how they are verified
- The account-holder reading, matching, due-now lines and the amount-due choice are deterministic, verified by exact values
  hand-written in the test contract. Photographed bills use fixed model stubs (`tests/model_server.py` `by_schema`); no test
  asserts live model output.

## Scenarios (expand into test-contract.md with design-tests before approval)
Fixtures are synthetic text PDFs (`tests/test_pdf.py` `make_pdf`), amounts right-aligned; the profile is named as each row says.

**BL-TOTAL** (the user's two lines, D2, D4): `LAKESIDE GAS & ELECTRIC`, `Account Name: Jordan A. Rivera`, `Account Number
4455-6677-8899`, `Statement Date 10/10/2026`, `Billing Period 09/01/2026 - 09/30/2026`; lines `Delivery Charges 1,180.40`,
`Supply Charges 412.26`, `Taxes and Fees 75.25`; then **`Current Charges due 11/01/2026 $62.91`** and **`Total Current Charges
$1,667.91`**. No previous balance, payments, amount-due or `Due Date` line. Check: 1,180.40 + 412.26 + 75.25 = 1,667.91.
**BL-TOTAL-NOW** (U4's other case): BL-TOTAL with lines `Monthly Plan 58.00`, `Taxes 4.91` (= 62.91).
**BL-PHONE-AH**: BL-PHONE (pdf-table-engine-bills) plus `Account Name: Alex Sample`. **BL-UTIL-AH**: BL-UTIL plus `Account
Name: Blair Sample`. **BL-DUE-CARRIED**: BL-UTIL's lines (97.55) with `Previous Balance 50.00`, `Payment Received -20.00`,
`Current Charges due 11/01/2026 62.91`, `Total Current Charges 97.55`, no amount-due line; 50.00 − 20.00 + 97.55 = 127.55.
**BL-TOTAL-DUE**: BL-UTIL's lines with `Previous Balance 50.00`, `Payments 0.00`, `Total Current Charges 97.55`, `Total Amount
Due 147.55`, `Current Charges due 10/15/2026 97.55`; 50.00 − 0.00 + 97.55 = 147.55. **MINI-DUE(k)**: MINI-BILL(k) with its
`Total Amount Due` and stub `Amount Due` lines replaced by `Current Charges due D N`.

| ID | FR IDs | Initial state | User/API actions | Expected final DB/files/UI state |
|---|---|---|---|---|
| SC-132 | FR-136, FR-138, FR-141 – FR-144 | (a) BL-TOTAL, profile `Jordan Rivera`, stub classifies lines and answers amount due 62.91, due date 2026-11-01 citing the due-now line; (b) BL-TOTAL-NOW; (c) BL-TOTAL with the stub giving no due date; (d) BL-TOTAL plus `Due Date 11/15/2026` | Extract; open the page; a checking payment −62.91 on 2026-10-30 to LAKESIDE GAS & ELECTRIC (variant −1,667.91); reconcile | (a) total 166791, amount due 166791, details `account_holder` `Jordan A. Rivera` citing its line, `due_now` 6291 / 2026-11-01, the "total is the amount due" note; lines check holds, counts automatically on 2026-11-01; every line's Person `Jordan Rivera`, from "Account name on the bill"; page rows: lines, Amount due 1,667.91, then `Current Charges due 11/01/2026 62.91`; Account holder `Jordan A. Rivera (you)`; the payment (either variant) proposed as the match. (b) amount due 166791, review with today's "New charges: the lines add up to 62.91, but the bill's new charges are 1,667.91" reason. (c) due date 2026-11-01 citing the due-now line. (d) due date 2026-11-15 with the note "The bill also prints Current Charges due 11/01/2026." |
| SC-133 | FR-137, FR-138 | Candidate `Jordan Rivera` (and a second candidate where named) | Show BL-TOTAL with each printed account name | `JORDAN RIVERA` ✓; `Rivera, Jordan` ✓; `Jordan A. Rivera` ✓; `Jordan Alex Rivera` ✓; `Mr. Jordan Rivera Jr.` ✓; `Jordan` ✓ (one word, OD-6); `J. Rivera` ✗; `Jordan Riviera` ✗; `Jordan & Casey Rivera` ✗; candidate `Jordan B Rivera` vs printed `Jordan A Rivera` ✗; candidates `Jordan Rivera` and spouse `Jordan Lee` vs printed `Jordan` ✗ (two match); profile `My profile` ✗. ✓ shows the candidate's name, ✗ the printed name. Renaming the profile to `Jordan Alex Rivera` changes the shown name with no re-read. |
| SC-134 | FR-136, FR-138 | BL-TOTAL with no account-name line; and with `Your account name is Jordan Rivera` | Extract; open the page | No account holder; every line's Person `Shared` (today's behaviour); no note |
| SC-135 | FR-138 | BL-PHONE-AH in an individual library, profile `Alex Sample` | Extract; open the page | Unlimited Plan, Device Payment: `Alex Sample` (title `Alex 555-201-1111` matched by first name); Basic Plan, International Pack: `Blair` (printed, unmatched); Autopay Discount: `Alex Sample` from the account name |
| SC-136 | FR-140 | Family with members Alex Sample, Blair Sample; Who has what phones 1111 Alex, 2222 Blair; no cards | Upload BL-UTIL-AH and BL-PHONE-AH to the family inbox; refresh | BL-UTIL-AH: suggestion member Blair, reason "The account is in Blair Sample's name", status suggested, nothing sent; no line `member_id` set. BL-PHONE-AH: suggestion "lines" as today; members and parts exactly SC-102's; the credit's select shows "Shared (taxes, fees)". After Send by line, Alex's library shows the credit's Person `Shared` |
| SC-137 | FR-142 (b) | BL-DUE-CARRIED | Extract | amount due 12755 with the worked-out note; total 9755 (counts); `due_now` 6291; no carried check; lines check holds |
| SC-138 | FR-142 (a) | BL-TOTAL-DUE | Extract | amount due 14755 (not 24510); total 9755; carried check holds; due-now 97.55 equals the new charges and differs from the amount due, so `due_now` 9755 kept and shown |
| SC-139 | FR-139, FR-147 | SC-132 (a) recorded | Correct Account holder to `Morgan Lee`; Extract again; Undo | Person cells `Morgan Lee`; kept after Extract again; after Undo `Jordan Rivera` again |
| SC-140 | FR-136, FR-145 | BL-TOTAL as a PNG; stub answers amount due 62.91 citing the due-now line, new charges 1,667.91 citing `Total Current Charges`, lines as printed | Extract | amount due 166791, `due_now` 6291, account holder read; a photographed bill whose amount due cites `Amount Due 62.91` reads exactly as before |
| SC-141 | FR-142 (a), FR-148 | BL-UTIL-R1 (a), (b), (c) | Extract each | (a) 14755, (b) 9755 as built; (c) **14755** (was 5000) with the guess note "The amount due is printed as 50.00 and 147.55; 147.55, the total, was used.", guess kind `amount_due` |
| SC-142 | FR-146 | Two pages, MINI-DUE(1), MINI-DUE(2) | Extract | 2 bills; amounts due 8142 and 8726 (worked out, 80.00 − 80.00 + 81.42 and 81.42 − 81.42 + 87.26); no FR-129 (b) reason; each verified |
| SC-143 | FR-147 | BL-TOTAL recorded at v50, undecided, amount due 6291 from the model; a copy where the user corrected amount due to 70.00; a confirmed copy | Start under the new version; Extract again each | Undecided: amount due 166791, account holder and `due_now` set. Corrected: amount due 7000, correction still latest in history. Confirmed: unchanged (6291, no account holder), its Person cells `Shared` until Account holder is set by Correct |
| SC-144 | FR-148 | Every fixture above; existing bill, invoice, receipt, statement, pay stub suites | Extract twice; run suites | Identical values, notes, evidence; zero model calls added; suites pass except the listed tests (SC-117 (c)) |
| SC-145 | FR-149 | BL-TOTAL as a file; generator; synthetic corpus | `statement_diagnose.py … bill`; generator test; `python -m evals.run` | Diagnose shows 1 account-name line and 1 due-now line on page 1, and no fixture name, label, amount or date; generator exact; eval reports the three counts, allowlist passes |

## Supersedes
- pdf-table-engine-bills FR-117 "If no check decides, the amount due is the first amount-due anchor on the bill's first page"
  and SC-117 (c) (5000) → FR-142 (a): the first `total`-worded anchor when one is printed (14755, SC-141).
- pdf-table-engine-bills FR-103's anchor kinds → plus `due_now` (FR-141); the account-name labels join the documented lists.
- pdf-table-engine-bills FR-128 "Each part must print its own amount due (an amount-due anchor …)" → or a due-now line (FR-146).
- pdf-table-engine-bills FR-120 "Photographed … bills read exactly as before" → except FR-136 and FR-145.
- pdf-table-engine-bills non-goal "any change to how a bill … is matched to its payment, is shared" → FR-143 (the due-now amount
  also matches) and FR-140 (the account-name suggestion).
- bill-kinds FR-50 "Last comes one Amount due row" → plus the due-now row below it when printed and different (FR-143).
- `receipt.js` `billLines` Person text "else Shared" → FR-138.

## Decisions taken (2026-11-12)
The user delegated the process and the decisions: "If you already know the fixes for this change we dont have to go through the
spec plan review phase. I will leave it up to you whether or not these changes warrant a whole planning loop or if the change is
trivial enough to just go in and fix". The orchestrator took every recommended default below (OD-1 – OD-9, OD-11, R1 – R5) and
skipped the test contract, plan and plan review; the change is built in slices against this spec, with targeted tests per
requirement, the full suite and an independent HIGH code review. OD-10 is unanswered: SC-132 (b)'s case (lines adding up to the
due-now amount) stays a review case.

## Out of scope / product decisions requiring approval
**Open decisions** (recommended default first; the user can answer "defaults ok"):
1. **OD-1 Which field the "total" becomes.** Default: the **amount due** only (the page's Amount due row, the split panel, the
   duplicate rule, payment matching), while what **counts** stays the new charges. On the user's bill both are 1,667.91.
   Alternative: also count the total. Risk of the alternative: a total that includes a previous balance would count last
   month's charges twice in spending and budgets.
2. **OD-2 How far "Total" overrides a printed amount due.** Default: the total rule replaces a "due now" line (FR-142 (b)) and
   breaks FR-117's tie between printed amounts due (FR-142 (a)), but a bill that prints a plain `Amount Due 62.91` and `Total
   Current Charges 1,667.91` keeps 62.91, because the bill itself says what is owed (credits or a payment plan may cover the
   rest; the carried check judges it). Alternative: the largest `total`-worded figure always wins. Risk: with the default, a
   bill worded `Amount Due` (not `due <date>`) still shows the smaller amount; with the alternative, a bill with a credit
   balance shows more owed than it asks for and its payment may not match.
3. **OD-3 A bill with a previous balance and a "due now" line but no amount due.** Default: amount due = previous balance −
   payments + new charges, worked out and noted (FR-142 (b)). Alternative: the printed total current charges alone. Risk: the
   alternative drops a past-due balance from what is owed.
4. **OD-4 Photographed bills.** Default: FR-145's cited-line rule (only when the model cites a due-now line and a
   `total`-worded new-charges line). Alternative: text PDFs only. Risk: the default is narrower than "for all bills" on photos
   whose lines the model cites differently; the alternative leaves photos showing 62.91.
5. **OD-5 Account-name labels.** Default: `account name`, `account holder`, `account holder name`, `customer name`, `name on
   account`; a bare `Name:` is left out (it also prints for plans, services and contacts), and invoices' `bill_to` is not used.
   Risk: a bill printing only `Name:` or `Customer:` keeps showing Shared.
6. **OD-6 Matching strictness.** Default as FR-137: first and last word equal, middle names ignored or matched by initial,
   `Last, First` and titles/suffixes handled, a first-name initial never matches, joint names match nobody, and a one-word
   name (a profile named just `Jordan`, a title `Alex 555-…`) matches the other's first word when it is the only candidate that
   does. Risk: the one-word rule could show your name on a bill in the name of another Jordan; it is display only and the
   printed name is one click away (Find). Stricter alternative: full first and last names required.
7. **OD-7 A family's bill.** Default as FR-140: the account holder never sets a line's member; it only suggests a whole bill
   with no line holders for that member, and unheld lines of a bill shared by line stay shared out and say Shared. Alternative:
   unheld lines go to the account holder's member. Risk of the alternative: the account holder would pay all of a phone bill's
   taxes and shared plan, changing docs/family.md "Sharing a bill by line".
8. **OD-8 Bills you already confirmed.** Default: never rewritten; they show Shared until you set Account holder by Correct.
   Alternative: on Extract again, add only the account holder (no amount) to decided bills too, recorded in their history.
   Risk: the default leaves the reported bill showing Shared if you already confirmed it.
9. **OD-9 Two different due dates printed** (`Due Date 11/15/2026` and `Current Charges due 11/01/2026`). Default: the model's
   kept due date (normally the `Due Date` line) stands, with a note (FR-144). Alternative: the due-now line's date wins, since
   it is printed beside the amount being paid. Risk: either can be wrong on an installment bill; the bill counts on that date.
10. **OD-10 (U4) About your bill**, answerable without sharing it: do its charge lines add up to 62.91 or to 1,667.91, does it
    print a previous balance or credit, and is it a downloaded PDF? If they add up to 62.91, the bill will still go to review
    after this change (SC-132 (b)), because 1,667.91 is then read as its new charges; that case would need its own rule.
11. **OD-11 Spouse names.** Default: the spouse named on your latest return is a candidate in your own library (as the
    who's-here picker), so a bill in your spouse's name shows their name. Risk: none known beyond OD-6's.

**Candidate domain risks** (only those you accept become requirements; the defaults above already cover R1 – R3):
- **R1 Joint account names** (`Jordan & Casey Rivera`): unhandled, they'd match whoever's first and last words fit. Default:
  match nobody, show printed (in FR-137).
- **R2 Profile renamed or still "My profile".** Unhandled, a stored match would go stale. Default: match when shown; "My
  profile" never matches (in FR-137).
- **R3 Payment plans** where only the due-now amount is paid this month: unhandled, the payment wouldn't match a bill now
  showing the total. Default: the due-now amount also matches (FR-143).
- **R4 Upcoming bills and the Bills page** show the recurring bill's expected amount (from the new charges), not the amount
  due; after this change the page's Amount due and the Bills page can still differ on a bill with a previous balance, as
  today. Default: unchanged (OD-1); recorded in docs/money.md.
- **R5 A business or landlord printed as "Customer Name"** (a bill addressed to a company): it matches nobody and shows the
  printed name instead of Shared. Default: accept; Correct can clear it (FR-139).

**Next step:** this is a stateful, multi-step change (re-reads, held corrections, family routing, payment matching), so run
`design-tests` to write `specs/bill-total-and-account-holder/test-contract.md` before approval.

**Out of scope:** invoices; what a bill counts; family routing by name; any model form change; a bare `Name:` label; budget or
levelized billing; consolidated multi-account bills.
