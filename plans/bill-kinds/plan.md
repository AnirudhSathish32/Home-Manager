# Bill kinds: a rent form beside the general bill form — implementation plan
Spec: specs/bill-kinds/spec.md (+ specs/bill-kinds/test-contract.md)
Spec sha256: dbc82bbe04e896cc1f642a1fb484d0977d6b6a4b67541b41d5224aabe5b64d32 (amended 2026-10-19 after review pass 1)

<!-- Approval lives in approvals/bill-kinds.json, bound to this file's hash. No Status line.
     Execution progress goes in plans/bill-kinds/progress.yaml, never in this file. -->

## Verified repository integration points
All at the working tree on `reorganize-packages` (HEAD 50154b6, uncommitted paystub-columns work present), 2026-10-19.

| Where | What it does today | Used for |
|---|---|---|
| `documents/extraction.py:44` `EXTRACTION_VERSION = "typed-extraction-v30-pre-tax-deductions"` | Run reuse key (`enqueue`, `:2322`). | FR-52 |
| `extraction.py:55-62` `HEADERS["bill"]` | provider, account_reference, issue_date, due_date, period_start, period_end, amount_due, new_charges, currency, invoice fields incl. `payments_received`. `previous_balance` is in `AMOUNTS` (`:76`) but not in the bill header. | FR-43 rent form = these + `previous_balance`, `monthly_rent` |
| `extraction.py:120-127` `LABELS["bill"]` | Nothing about `issue_date` or the period. | FR-46, FR-47 instructions |
| `extraction.py:228-239` `RECEIPT_KINDS`, `Classification.receipt_kind(_evidence)` | Kind proposed in the sorting step; checked in code, never by `problems_in`. | FR-40 `bill_kind` fields beside them |
| `extraction.py:588-606` `receipt_kind()` | Requested kind wins; else cited, listed proposal; else general with a note. | FR-40/41 `bill_kind()` mirrors it |
| `extraction.py:319-330` `BillLine`, `:481` `BillLines`, `:494` `ROWS["bill"]` | `line_kind` from `core/categories.py:32` `LINE_KINDS`; no period or usage. | FR-44 `RentBillLine` |
| `extraction.py:431-453` `OPTIONAL_FIELDS`, `HEADER_MODELS`, `RECEIPT_FORMS` (`create_model` over a base) | How receipt-kind forms are built. | `BillRentSummary` built the same way |
| `extraction.py:1230-1281` `ask()` | One correction; then droppable identifying fields → missing with a note; else `base_answer` for `NEW_FIELDS`; else `ValueError`. | rent-form fallback (spec "Errors") wraps it |
| `extraction.py:1392-1529` `normalize(kind, header, rows, currency, lines, details, receipt_kind, printed_columns)` | `DATES` parsed with `iso_date` only (`:1422-1425`); bill branch calls `bill_lines` (`:1503`). Every entry of `issues` sends the record to review (`publish`, `:2640-2645`). | new `bill_kind=` keyword; date checks; note-only channel |
| `extraction.py:1726-1809` `bill_lines` | Lines (credit = money off), `total_minor` = new charges / lines / amount due, the lines-add-up cross-check, `recurrence` from period length, monthly when none (`:1773-1775`), invoice branch. | FR-44/45/47/49/54/56 |
| `extraction.py:2351-2458` `ExtractionService.extract` | Chooses `RECEIPT_FORMS.get(chosen) or HEADER_MODELS[kind]`; rows with `ROWS[kind]`; bill row instructions `:2407-2412`, `:2433-2436`. Returns `(classification, header, rows, identity, chosen)`. | form choice, fallback |
| `extraction.py:2683, 2713, 2746-2756` `run` / `requested_kinds` | Kind change (`settings["receipt_kind"]`) matched to its part by first line; else `ledger.chosen_kind(blob, segment)` from `record_corrections` field `receipt_kind`. | FR-42 for bills |
| `extraction.py:2591-2674` `publish` | `record_notes` → `record["notes"]` (overwritten, not shown on any page); `issues.extend(notes)`; `publish_bill`. | note channel |
| `extraction.py:2988-3005` `filing_identity` | A bill files under `issue_date`, else the classification's `document_date`. | unchanged (risk R7) |
| `finance/ledger.py:513-559` `publish_receipt` | Writes `receipt_kind`, `details_json` via `merged_details` (by kind; `None` when kind is None, i.e. every bill today), kind-change correction + `pending_details_json` when reviewed. | bills store `bill_kind` + details by kind |
| `ledger.py:571-626` `chosen_kind`, `apply_details`, `_undo_kind`, `current_details` | All keyed on `receipt_kind`. | generalized to the record's kind column |
| `ledger.py:1021-1043` `publish_bill` | Bill → receipt dict; own category = the category with most money. | passes `bill_kind`, details, `line_type`, item details |
| `ledger.py:740-809` `_replace_items` | A user category (`category_source='user'`) and person outlive readings; writes `line_kind`, `details_json`. | `line_type` column |
| `ledger.py:170, 1984-2012, 1826-1834, 1861-1870, 826-827` `LINE_FIELDS`, `correct_line`, `_set_line`, undo, `apply_corrections`, `delete_item` | Line corrections kept by position as `line_kind:N` / `member:N`. | `line_type:N` |
| `ledger.py:1136-1263` `record()` | `details` for receipts from `details_json[receipt_kind]`; bill `correctable` adds Type (`LINE_KINDS`) and Person; `checks` from `document_traces.checks`; `display` strings for every `_minor`. | bill details, `bill_summary`, rent Type options |
| `ledger.py:1756` correction labels | `{"receipt_kind": "Receipt kind", ...}`. | "Bill kind" |
| `finance/document_traces.py:71-74, 187-242` | `receipt_checks` returns `[]` for bills; `checks()` figures; `TRACES` refs `receipt.*`. | `bill.lines`, `bill.carried` |
| `finance/document_checks.py` | One function per check, `(computed, compared, passes)`, used by `normalize` (dining) and traces. | `bill_lines`, `bill_carried` |
| `finance/tools.py:818-855` `get_budgets` | Each unpaid verified recurring bill adds its whole `expected_amount_minor` to `(currency, bill["category"] or "bills")`; projected trace steps per payee. | FR-45a |
| `finance/reconcile.py:415-437` `bill_payment` | Window: `issue_date or due − 1 month` to due + 5 days. | FR-46 (unchanged code; SC-39) |
| `finance/reconcile.py:630-653` `propose_bills` | A verified receipt with a recurrence or bill category proposes `total_minor` at `recurrence or monthly`, unless the payee has a bill. | FR-56 |
| `app/manager.py:1510-1548` `change_receipt_kind` | Refuses bills ("A bill has no receipt kind."), 409 while a reading of the file runs, unchanged for the same kind, enqueues with `receipt_kind={segment, first_line_id, kind}`. | FR-42 |
| `app/api.py:189-203, 1005-1019` `LineInput` (`line_kind`/`member`), `ReceiptKindInput` (fuel/dining/grocery/general), routes | | `line_type`, `rent` |
| `app/static/receipt.js:34-41, 140-232` `RECORD_FIELDS.bill`, `LINE_KIND_LABELS`, `billLines` (tfoot New charges / Amount due) | | FR-50/51 |
| `app/static/document_v2.js:440-508, 521-532, 610-660` `doc2Fields` (Counts as `:504`), `doc2Forms` (kind control only for non-bills `:523`), `doc2Kind`, `doc2Pending` | | FR-42 UI, FR-50 |
| `app/static/records_v2.js:438` | Bill period "For {dateText} – {dateText}". | SC-48 step 8 text |
| `library/migrations/067_bills_as_receipts.sql:18-19`, `070_document_forms.sql:3` | `line_kind` CHECK; `receipt_kind` CHECK (fuel/dining/grocery/general). | migration 071 |
| `evals/tasks/document_forms.py:74-133` | `run()` passes a known `Classification` (no kind) and calls `extract` + `normalize`. `TYPES` lacks bill. | FR-53 |
| `tests/model_server.py:96-99` `by_schema` | Replies popped per schema name, then `outputs`. | stubs |
| `tests/document_forms_fixtures.py`, `tests/test_extraction.py:130,148` (`transcribe`, `extract`), `tests/test_bills_ledger.py:82,223` (`PHONE_TEXT`, phone share test) | Helpers and regressions the contract names. | tests |

## Architecture, contracts, data flow and decisions

### Data flow after the change (bills only)
```
run(): Classification (now also bill_kind + bill_kind_evidence)          [same call as today]
  requested_kinds(..., document_type)  -> kind change, else the user's last bill_kind correction, else None
read() -> extract():
  kind == "bill": chosen = bill_kind(classification, lines, notes, requested)    (FR-40, FR-41)
  header = ask(BILL_FORMS.get(chosen) or HEADER_MODELS["bill"], ...)              [same number of calls]
  rows   = ask(RentBillLines if chosen == "rent" else BillLines, ...) per chunk
  rent header or a rent row chunk fails after its correction -> note "Read as a general bill: …",
       header and rows asked again with the general form, chosen = "general"      (spec "Errors")
record() -> publish(..., bill_kind=chosen) -> normalize(..., bill_kind=chosen)
normalize, bill branch:
  bill_dates(...)   FR-46, FR-48, FR-55 on the header dates (every bill kind)
  bill_lines(...)   lines; rent: types, line periods/usage, FR-45/45b categories, FR-54 earlier lines,
                    FR-47 period from rent lines, FR-56 recurrence + prorated, FR-49 checks (both kinds)
  record["details"] = {new_charges?, previous_balance?, payments_received?, monthly_rent?, period?, prorated?, notes: [...]}
publish_bill -> publish_receipt: bill_kind column, details_json[bill_kind], items with line_type + details_json
```

### Storage (migration `071_bill_kinds.sql`, no table rebuild)
```sql
-- Bill kinds (specs/bill-kinds; docs/money.md "Bills and their lines", docs/documents.md "Bill kinds").
-- Nullable, nothing backfilled: a bill gets its kind when it is read again (FR-52).
ALTER TABLE receipts ADD COLUMN bill_kind TEXT CHECK (bill_kind IS NULL OR bill_kind IN ('rent','general'));
ALTER TABLE receipt_items ADD COLUMN line_type TEXT
    CHECK (line_type IS NULL OR line_type IN ('rent','parking','pet','utility','fee','credit','other'));
PRAGMA user_version=71;
```
- **Decision P1: a new `bill_kind` column, not `rent` in `receipt_kind`.** Widening `receipt_kind`'s CHECK means rebuilding
  `receipts`, which a dozen tables reference (`011`, `014`, `021`, `028`, `033`, `045`, `050`, `063`, `067`, `068`).
  `ADD COLUMN … CHECK` on a STRICT table needs no rebuild (`docs/development.md` "Adding a migration" step 4 applies only
  to changing a CHECK). `receipt_kind` stays receipt-only; `bill_kind` is bill-only. The kind machinery is generalized
  over "the record's kind column": `kind_column(row) = "bill_kind" if row["document_kind"] == "bill" else "receipt_kind"`.
- **Decision P2: rent line types in a new `receipt_items.line_type` column**, and `line_kind` keeps a mapped value so
  every existing consumer (credit sign, `includes` for subscriptions, splits, Bills page) is unchanged:
  `RENT_LINE_KINDS = {"rent": "service", "parking": "service", "pet": "service", "utility": "usage", "fee": "tax_fee",
  "credit": "credit", "other": "other"}`. A general bill's `line_type` is NULL.
- Bill details go in the existing `receipts.details_json` keyed by kind (`{"rent": {...}}` / `{"general": {...}}`),
  exactly as receipts do (`merged_details`). A line's period and usage go in the existing `receipt_items.details_json`.
- Money stays integer minor units; usage is its printed text (C-money).

### New and changed contracts

**Constants and schema (`extraction.py`):**
- `BILL_KINDS = ("rent", "general")`. `Classification` gains `bill_kind: str | None` (enum `[*BILL_KINDS, None]`,
  "For a bill only: rent or general; null for any other document.") and `bill_kind_evidence: list[EvidenceQuote]`,
  both defaulted, checked in code only (like `receipt_kind`). `CLASSIFY` gains one sentence: rent = "a rent or resident
  bill from a landlord or property manager: rent, a resident or lease charge, utilities billed by the property";
  general for any other bill; null for anything that is not a bill.
- `BillRentSummary = create_model("BillRentSummary", __base__=HEADER_MODELS["bill"], previous_balance=(Value, MISSING_VALUE),
  monthly_rent=(Value, MISSING_VALUE))`; `payments_received` already exists (optional). `BILL_FORMS = {"rent": BillRentSummary}`.
  `previous_balance` and `monthly_rent` go in `AMOUNTS`-checked names (`previous_balance` already is; add `monthly_rent`).
  `OPTIONAL_FIELDS` gains both.
- `BILL_KIND_LABELS["rent"]` (appended to the summary instruction like `KIND_LABELS`): previous_balance = "the printed
  balance carried from before this bill, missing when none is printed"; payments_received = "the printed payments or
  credits received since the last bill, as one amount"; monthly_rent = "the printed monthly rent rate, only when printed
  apart from this bill's rent charge"; period = "the rent line's printed period"; "Never calculate a missing amount".
- `LABELS["bill"]` gains, for every bill: "issue_date: a printed statement, bill or invoice date only, never the due
  date or a date on a Due line or heading; missing when none is printed. period_start and period_end: the printed
  billing or service period."
- `RENT_LINE_TYPES = ("rent", "parking", "pet", "utility", "fee", "credit", "other")`.
  `RentBillLine(StrictModel)`: `description`, `amount`, `quantity`, `unit_price`, `category`, `line_holder` as `BillLine`;
  `rent_type: Literal[*RENT_LINE_TYPES]` (with the spec's descriptions); `period_start`, `period_end`: `str | None`,
  "YYYY-MM-DD as printed on this line, or YYYY-MM when the line prints only a month (Rent for October 2026)";
  `usage: str | None` "the printed usage with its unit, such as 3,200 GAL, or null"; `evidence`.
  `RentBillLines = create_model("RentBillLines", line_items=(list[RentBillLine], ...))`. Added to `SCHEMA_FIELDS`.
- Rent row instructions (`extract`, beside `:2407`): one entry per charge on this bill; the water, sewer, trash, gas or
  electric line is its own utility line, never folded into rent; "only charges on this bill are lines, never a warning,
  a term or a fee that may apply later (a late fee of 75.00 applies after …)" (FR-58); never the amount due, the new
  charges total, the previous balance or the payments-received total printed beside it. A dated payment row in a
  resident ledger is a line (R5-m1; FR-54 then leaves it out). "A line printing one date (a payment or a past charge): that date as
  both period_start and period_end." (R4-m3)

**`bill_kind(classification, lines, notes, requested=None)`** — `receipt_kind`'s rules with `BILL_KINDS` and the note
"Bill kind: {shown} was not used: {why}. It was read as a general bill." `requested` wins. Null or `general` → general, no
note. (FR-40, FR-41)

**`extract()`**: `chosen = receipt_kind(...) if kind == "receipt" else bill_kind(...) if kind == "bill" else None`.
Form `RECEIPT_FORMS.get(chosen) or BILL_FORMS.get(chosen) or HEADER_MODELS[kind]`; rows `RentBillLines` when
`chosen == "rent"`. The rent header ask and the rent row loop run inside one `try`; a `ValueError` from either appends
`f"Read as a general bill: {message}"` to `notes`, discards rent rows, and asks the general header and `BillLines` again;
`chosen = "general"`. (Spec "Errors"; 38b, 38c.) `BillRentSummary` and `RentBillLines` stay **out of `NEW_FIELDS`**, so
`ask()`'s `base_answer` path never answers for them and the fallback always runs (R1-m6). 38b's end state: published as
`general` with the "Read as a general bill" note, `needs_review`, the `BillLines` re-ask stubbed with the correct two
lines, and no line of 148842.
An invoice answered `rent` (44d) is still asked the rent header and `RentBillLines` (same number of calls) and is made
general in `bill_lines`; accepted, since checking the header's invoice fields first would only save work on a wrong
kind (R1-m5).

**Date checks — `printed_dates(text)` (new, `extraction.py`)**: every date written in a quote, as
`(date | (month, day) | (year, month), form)`:
- ISO `YYYY-MM-DD`; numeric `M/D/YYYY` (1–2 digit month and day; both the M/D and the D/M reading when each is a valid
  date, since the model already resolved the order under `RULES`); month name `Oct 1, 2026` / `October 1 2026` /
  `1 Oct 2026` (3-letter or full names, optional period and ordinal); yearless `M/D` (not followed by `/digits`);
  month only `October 2026` / `10/2026`. Two-digit years and `MM-DD-YYYY` are not forms (dropped, decision P5).
  Every numeric match is bounded: no digit or `/` directly before or after it (so `01/2026` inside `10/01/2026` and
  `10/20` inside `10/2026` are not matches; R1-m4).
- `date_printed(value, evidence, due=None) -> (kept_date | None, how)` where how ∈ {`printed`, `year_from_due`,
  `whole_month`}. A full date is kept when a cited quote prints that date. A yearless match is kept when `due` is
  given, the month is the due month or one month either side (December/January wrap), and the value's year is the one
  that puts it there: how=`year_from_due` (FR-55). A month-only match is used only for rent line periods (below).

**`bill_dates(record, fields, issues, notes, line_text)`** (new, called first in the bill branch of `normalize`; every
bill kind):
1. Due date: kept only as `printed` (a yearless due is dropped: FR-55 "the due date itself must print its year"). A dropped
   due date → issue `"Due date: the cited line doesn't print {value}; it was left out."` (review, FR-48; it also blocks
   `review_reasons`' duplicate).
2. Issued: dropped as a **note** `"Issued: the cited line is a due date"` when every cited quote names `\bdue\b` and none
   names a statement/bill/invoice/issue date word (`statement|bill(?:ing)? date|invoice date|issued?|date of bill`)
   (FR-46). It is also dropped with the same note when the nearest date label before the date it matches in the
   quote is `due` (labels, case-insensitive: `due` and the statement words above; a column header quote such as
   `Bill Date Due Date 09/15/2026 10/01/2026` can drop a correct Issued, a note only, accepted under R4; R4-m5) (so `Due Date 10/01/2026 Statement Date 09/15/2026` keeps 09/15; R3-m3), or when it equals the due date and the quote names `due` (a line printing both a statement date
   and a due date; R2-m3). Otherwise `date_printed(..., due)`; not printed → note `"Issued: the cited line doesn't print {value}; it was
   left out."` (FR-48: a note only).
3. Header period start/end: `date_printed(..., due)`; not printed → issue `"Period: … left out."` (review).
4. Order: start > end → both dropped, issue `"Period: the printed period starts after it ends; it was left out."`;
   issued > due → both dropped, one issue `"Due date: the issued date ({issued}) is after the due date; both were left
   out."` (starting with "Due date" so `review_reasons` adds no "Due date was not found" duplicate; R2-m5).
5. Each `year_from_due` adds the note `"{Field}: year taken from the due date."` (FR-55).

`normalize`'s generic `DATES` loop is unchanged for other kinds; for bills it still parses ISO first and `bill_dates`
then judges citations. A `Value` whose evidence was masked (identifier fields) is not a date field, so masking doesn't
interact.

**Note-only channel.** `normalize` for a bill fills `record["details"]["notes"]` (strings) for what the spec calls "a note
only" (Issued dropped, a line date or usage dropped, year from due, FR-54 left-out lines, prorated rent, "No rent line was
read"); `issues` stays the review channel. `notes` are stored in `details_json[bill_kind]["notes"]` and shown on the
document page under the bill's fields (SL-07). They never change `review_status`.

**`bill_lines(record, rows, money, issues, currency, total, fields, line_text, bill_kind)`** — today's logic plus:
- Invoice detected (`invoice` true) → `record["bill_kind"] = "general"` whatever was chosen (FR-40, 44d); rent-only steps
  are skipped and a rent row's `rent_type` maps through `RENT_LINE_KINDS`.
- **Rent rows** (`bill_kind == "rent"`): `line_type` = the row's `rent_type`, except a description naming
  `\b(water|sewer|trash|garbage|refuse|gas|electric(?:ity)?)\b` is `utility` (FR-45b, 43b-1; no note).
  `line_kind = RENT_LINE_KINDS[line_type]`. Category (FR-45, decision D25): utility → `utilities`; rent, parking, pet,
  fee → `housing`; credit, other → the model's category. No note when it overrides.
  Line period: each of start/end via `date_printed(..., due)` on the row's evidence; a `YYYY-MM` start (or start/end that
  are a month's first and last day while the quote prints only that month) becomes the whole month, how=`whole_month`
  (FR-47, SC-41, 41a). Order start ≤ end. A failed date → both dropped, note `"{description}: its period isn't printed in
  its line; it was left out."` Usage kept only when its text is in a cited quote (`printed_in`), else a note (FR-44).
  Stored as item `details = {"period": {"start", "end", "how", "locator"}, "usage": {"text", "locator"}}`.
  **Order of the line-date rules (R4-M1; the simplest single rule after two passes on this area):** (1) a month-only
  answer (`YYYY-MM` on either side, or full dates that are a month's bounds while the quote prints only that month) is
  expanded to the whole month first and is a period; (2) only then, **a dated line** (R3-M1, FR-54 "with no period, is
  dated"): full-date answers with start == end, or with only one side, have no period. Its one kept date is stored as `details.date = {"value", "how", "locator"}`. It counts only in FR-54's
  earlier-month comparison, and never feeds the FR-47 bill period or the FR-56 prorated or schedule rules. A plan-level
  variant in sc46a covers it (`10/01/2026 Rent $1,450.00`: no prorated note, the bill's period from the header rule).
- **FR-54 earlier lines** (rent only, before totals): a line whose `line_type` is rent or credit, or whose description
  names `\b(payment|paid)\b` (`re.IGNORECASE`, as the utility pattern above; R4-m4), with a kept period ending (or a
  dated line's date falling) before the first day of the due date's month is left out (with no kept due date, nothing is
  left out: the bill is already in review; R4-m2), with a note `"{description} ({period}) is from an earlier month; the printed previous
  balance stands for it."`. Utility lines are never left out (A3, G2). "Printed" means the field was kept, 0 included (`Previous Balance $0.00`
  counts; test `is not None`, never truthiness; R5-m2). Left out with no printed `previous_balance` → issue
  `"Earlier months' lines were left out, but no previous balance is printed; check this bill's charges."`
  (Decision P3: the anchor is the due date's month, not "the bill's period", because the bill's period is itself worked out
  from the remaining rent lines; it gives the spec's outcome on every fixture.)
- **FR-47 bill period** (rent): from the kept rent lines with a period: earliest start to latest end; `details["period"] =
  {"from": "rent_lines", "how", "locator"}` with how = `whole_month` when any part was. The model's header period is
  ignored (SC-40). With no rent line period: the header period as checked by `bill_dates`. With no rent line at all: also
  the note `"No rent line was read."` (38d).
- **FR-56 recurrence** (rent): `monthly`, unless every kept, **non-prorated** rent line's period length falls in one other
  `BILL_PERIODS` range (a prorated line sits inside one calendar month and shows no schedule, so an 8-day move-in is
  never "weekly"; R2-M2). With only prorated lines, or no non-prorated rent line with a period (only dated lines, or
  none as in 38d): `monthly` (R4-m1). A rent line within one calendar month but shorter than it adds the note `"Prorated rent: N days."` and
  `details["prorated"] = {"days": N}`; with no printed `monthly_rent` the note gains `" The recurring bill is proposed from
  the next full month."` General bills keep today's recurrence rule.
- **FR-49 checks** (every non-invoice bill): the lines check goes through `document_checks.bill_lines(lines, compared,
  currency)` against new charges when printed, else the amount due. A mismatch against the amount due (no new charges
  printed) is now also an issue `"Amount due: the lines add up to {lines}, but the amount due is {due}. A line may be
  missing or misread."` (it was only the generic `CROSS_CHECKED` reason). The carried check
  `document_checks.bill_carried(previous, payments, new, due, currency)` runs when previous balance, payments and new
  charges are all printed; pass → `cross_checks += 1`; fail → issue naming the four values (`"Amount due: previous
  balance {p} less payments {q} plus new charges {n} is {x}, but the amount due is {d}."`).
- `record["details"]` (both kinds) also holds the printed `new_charges`, `previous_balance`, `payments_received`,
  `monthly_rent` as `{minor, locator}` (payments as a magnitude).

**`document_checks.bill_lines(lines_minor, compared_minor, currency, recorder=NULL)`** and
**`bill_carried(previous, payments, new, due, currency, recorder=NULL)`** → `(computed, compared, passes)`.
`document_traces.receipt_checks` gains a bill branch (`bill_kind` set, no invoice): `lines` ("Charge lines", ref
`bill.lines`) and `carried` ("Previous balance, payments and new charges", ref `bill.carried`), with inputs' provenance
from line evidence and `detail:<name>` / header fields. `TRACES` gains both refs.

**Ledger (`finance/ledger.py`):**
- `kind_column(row)`; `publish_receipt` writes `bill_kind` (from `record["bill_kind"]`) and `merged_details(db, source,
  kind, details)` with the record's kind; the kind-change correction field is `bill_kind` for bills.
- `publish_bill` passes `bill_kind`, `details`, and each line's `line_type` and `details`.
- `_replace_items` writes `line_type`.
- `chosen_kind(blob_hash, segment, field="receipt_kind")`; `_undo_kind` and `undo_corrections` (`:1839`) handle
  `bill_kind`; `current_details` / `record()` / `document_traces.current` read `details_json[row[kind_column(row)]]`.
- `LINE_FIELDS["line_type"] = "line_type"`. `correct_line`: `line_type` only on a bill with `bill_kind='rent'`, value in
  `RENT_LINE_TYPES` or None; `line_kind` on a rent bill is refused ("Choose one of the rent bill's line types.").
  `_set_line` for `line_type` sets `line_type` and `line_kind = RENT_LINE_KINDS[value]`. `delete_item` also clears
  `line_type:N`. Correction labels: `"bill_kind": "Bill kind"`, `("line_type", "Type of")`.
- `record()` for a rent bill offers `{"field": "line_type", "label": "Type", "options": RENT_LINE_TYPES}` instead of
  `line_kind`; and for a non-invoice bill with a kind, `bill_summary` (SL-07).
- **Kind and lines (R1-M1).** Lines follow a *reading*, never a kind correction by itself:
  - A reading of a not-reviewed bill writes every line's `line_type` (rent) or NULL (general), as read.
  - A reviewed bill's kind change keeps its lines as they are (D7: amounts and items stay); only `bill_kind` and the
    pending details change. Apply details applies the bill's details only, never line types.
  - Undoing a kind change back to a kind other than rent also sets that bill's `line_type` to NULL (each line keeps its
    `line_kind`, a valid general type), so a general bill never carries rent types.
  - A rent bill line whose `line_type` is NULL (a reviewed bill changed to rent) shows its `line_kind` label with the
    rent Type choice "Not set", and accepts a `line_type` correction. `correct_line` refuses `line_kind` on a rent bill
    only for lines that have a `line_type`.
  - The journey (SL-06) asserts each of these: step 7 (reviewed → rent) lines unchanged with `line_type` NULL and a
    `line_type` correction accepted; step 6 (undo to general) every `line_type` NULL.
- **Replaying line corrections on a re-read (R1-M2)**, in `apply_corrections`: the latest `line_type:N` applies only when
  the bill's `bill_kind` is `rent` and sets `line_type` and the mapped `line_kind`; then the latest `line_kind:N`, on any
  bill, sets `line_kind` (a person's choice wins over the mapping; `line_type` is left as read). So a v30 bill's
  `line_kind` correction survives being read again as rent (SC-49 step 3 asserts `line_kind` = the person's value and
  `line_type` = the reading's), and a `line_type:N` correction does nothing on a bill read again as general.

**Kind change (`app/manager.py`, `app/api.py`):** `change_receipt_kind` → `change_kind`: kinds allowed by
`document_kind` (`receipt`: fuel/dining/grocery/general; `bill`: rent/general); another kind → `ValueError` (400,
"Choose one of a bill's kinds: rent or general."). An invoice may be read as general only (rent → 400). Everything else
as today: 409 while a reading runs, 200 unchanged, enqueue with `{"segment", "first_line_id", "kind"}`. The enqueue
option key stays `receipt_kind` (it's only the reuse key; decision P4). `ReceiptKindInput.kind` adds `"rent"`; the route
stays `PATCH /api/receipts/{id}/kind`. `LineInput.field` adds `"line_type"`.
`requested_kinds(parse, lines, parts, kind_change, document_type)`: chosen kinds are read from the correction field that
fits the type; a requested kind that doesn't fit the reading's type is ignored with the note `"{Kind} was not used: this
document was read as a {type}."`.

**Budgets (`finance/tools.py` `get_budgets`, FR-45a):** for each due bill, `parts(bill)`. Only a recurring bill whose
`source_receipt_id` is a bill with `bill_kind='rent'` is split (FR-45a "proposed from a rent bill"; one proposed from a
bank payment stays whole, R2-m4). For it:
the latest verified rent bill of the obligation's merchant and currency (`document_kind='bill' AND bill_kind='rent'`,
`due_date DESC, id DESC`); none → `[(bill["category"] or "bills", expected)]` (today). Found → utilities =
min(expected, that bill's non-rejected lines in category `utilities`), rest = expected − utilities:
`[(bill["category"] or "housing", rest), ("utilities", utilities)]`, zero parts dropped. Each part is added to its key. The
projected trace adds one step per part, `"{merchant} · due {date} · {category label} part"`, **without** a drill-down
trace (`bill.expected`'s result is the whole amount, R1-m2). Each part has two inputs: the expected amount (`trace=bill.expected`)
and the bill whose lines split it (`light("receipt", latest_bill_id, kind="computed")`).
The utility part is the lines in category `utilities` (FR-45a as amended); FR-56's "the bill's utility lines" uses the
same rule, so both splits agree (R1-m3).
(Decision P6: "the rest" goes to the recurring bill's own category, which is `housing` for every rent proposal (FR-45's
bill category); a person's change of that category wins, as everywhere else.)

**Recurring proposals (`reconcile.py` `propose_bills`, FR-56):** for a receipt with `bill_kind='rent'`: details
`prorated` and no `monthly_rent` → skipped; `monthly_rent` printed → expected = monthly rent + the bill's utility lines
(category `utilities`, as FR-45a). Otherwise unchanged. The transactions loop is unchanged (risk R8).

**Page (SL-07):** `Ledger.record()` adds, for a non-invoice bill with a `bill_kind`:
```
bill_summary = {"carried": [{"label": "Previous balance", "minor", "display", "field": "detail:previous_balance", "line_ids"},
                            {"label": "Payment received", "minor": -payments, ...}],     # only those printed
                "earlier_balance": {"minor", "display"} | None,
                "gap": {"minor", "display", "reason"} | None,
                "amount_due": {"minor", "display", "line_ids"}}
```
`rows = sum(lines) + previous − payments`; `remainder = amount_due − rows`. Remainder 0 → neither. Otherwise, **user
decision 2026-10-19 (spec amendment, see Risks R1)**: when nothing is carried, new charges are printed and the lines check
against them passed, the remainder is `earlier_balance` ("Earlier balance", worked out); else it is `gap` ("Not
accounted for", the failing check's reason text). Bills read before this change (`bill_kind` NULL) keep today's rows until
read again (decision P7, FR-52).
- `receipt.js`: `RECORD_FIELDS.bill` keeps Provider, Issued, Due, Period, Categories, Billed; New charges and Amount due
  only for invoices (as Invoice total / Remaining balance). An Issued that is null is left out (FR-46). `billLines`:
  rent bills show `line_type` labels (`RENT_TYPE_LABELS`), each line's period (`dateRangeText`) and usage under the
  description, each with Find (the line's `line_ids`); the tfoot becomes the carried rows, Earlier balance or Not
  accounted for (with the reason), a rule, then **Amount due** last with Find (provenance field `amount_due`) and Correct.
  The "Only the new charges count…" paragraph goes for kinded bills. Every change in this bullet and the next applies
  only to a non-invoice bill **with a `bill_kind`**; a bill with `bill_kind` NULL keeps today's top fields, tfoot and
  Counts as (P7; R2-m1).
- `document_v2.js`: no "Counts as" for kinded bills (`document_kind === "bill" && bill_kind`), Counts in stays; `doc2Forms` shows
  `doc2Kind` for bills that aren't invoices with `BILL_KINDS = {rent: "Rent", general: "General"}` and label "Bill kind";
  for a bill with `bill_kind` NULL the control reads "Not read with kinds" with nothing pre-selected, as receipts do
  today (document_v2.js:613), and choosing General or Rent re-reads it (NULL ≠ the chosen kind, so `change_kind`
  enqueues; R3-m4); `doc2Pending` labels by the record's kind; bill `details.notes` render as a muted list under the fields; a period
  worked out from a rent line shows "Worked out from “…”".
- `ui.js`: `dateRangeText(start, end)` → "Aug 15 – Sep 14, 2026" (one year) / "Dec 15, 2026 – Jan 14, 2027". Used for
  line periods and in `records_v2.js:438` (SC-48 step 8 expects "Oct 1 – Oct 31, 2026").
- Before changing these pages the implementer loads `ui-ux-pro-max` (CLAUDE.md) and keeps `docs/ui.md` "Screen rules"
  (money from the server: every amount above, the gap included, is a server `display`).

**Eval (`evals/tasks/document_forms.py`, FR-53):** `TYPES` adds `bill`. Cases RENT (+ RENT-PLAIN as a measured case).
`run()` for a bill asks the sorting step (`extract(..., classification=None)`) so the kind is graded, then
`normalize(..., bill_kind=chosen)`. Output fields: `kind`, `issue_date`, `period`, `due_date`, `lines`, `water` (its
`line_type`), `amount_due`. Expected RENT: `rent`, None, `2026-10-01..2026-10-31`, `2026-10-01`, `2`, `utility`,
`1488.42`. `report_lines` prints the bill row like the other types.

**Version:** `EXTRACTION_VERSION = "typed-extraction-v31-bill-kinds"`.

### Decisions taken in this plan
- P1 `bill_kind` column; P2 `line_type` column + mapped `line_kind`; P3 FR-54 anchors on the due date's month;
  P4 the enqueue option key stays `receipt_kind`; P5 date forms are exactly FR-48's list plus yearless and month-only
  (no 2-digit years, no `MM-DD-YYYY`); P6 FR-45a's rest goes to the recurring bill's category; P7 pre-kind bills keep
  today's page rows; P8 FR-49's lines-vs-amount-due mismatch becomes a named issue for every bill (it was a generic
  reason); P9 note-only outcomes live in `details.notes`, review outcomes in `issues`.

## Error handling, idempotency and recovery
- **Rent form fails twice** → general form, note "Read as a general bill: …" (an issue → review). Never lost (38c).
- **Unusable kind** → general + note + review (FR-41); null → general, no note.
- **Kind change**: refused (409) while any reading of the blob is queued/running (existing query); same kind → 200, no
  correction, no request; the correction is written only by the reading's publish (`kind_change`), so a cancelled or
  interrupted run leaves the kind unchanged (J-b, J-c). Restart: `ExtractionService.recover()` marks runs interrupted
  (unchanged). Undo writes an `UNDO_REASON` correction so later readings see the undone choice.
- **Reviewed bill** (user verified): a re-read keeps amounts and review (`_upsert` `kept_reviewed`); a kind change sets
  `bill_kind` and `pending_details_json` (D7); Apply details works by kind.
- **Re-reading** keeps a user's category, person and `line_type:N` corrections by position (existing re-apply loop).
- **Idempotency**: `publish_receipt` upserts by (blob, segment); budgets/proposals are pure reads/INSERT OR IGNORE.
- **Dates**: every drop is either an issue (review) or a note, never silent; nothing is filled in except `whole_month` and
  `year_from_due`, each marked.

## Privacy/security and migration impact
- No new model call (C-calls): the kind rides the existing Classification; the rent form replaces the general form's
  calls one for one. The fallback adds calls only after a failed reading. No `image_url`.
- Identifiers: `account_reference` keeps last four (FR-30, unchanged); no tenant name/unit/address field; line holders as
  today. C-ids checked with `stored_identifiers` on `4821`.
- Migration 071: two nullable `ADD COLUMN`s with CHECKs, no backfill, no rebuild, so no FK risk; upgrade takes the
  `inventory.before-v071` copy as every migration does. Forward-only. `tests/test_migrations.py` gets a `bill_kinds` case.
- Synthetic fixtures only; never `P:\Finances`, `%LOCALAPPDATA%\HomeManager`, `P:\EvalCorpus`.
- No new dependencies.

## Vertical slices
Every slice: `python -m ruff check` and `python -m mypy` on touched modules, and the targeted tests listed (memory:
targeted runs only). Tests use `tmp_path` libraries and `local_model` stubs keyed by schema name.

| ID | FR/SC covered | Dependencies | Files/changes | Verification command / evidence |
|---|---|---|---|---|
| SL-01 | FR-52; SC-49 steps 1–2 | none | `library/migrations/071_bill_kinds.sql`; `EXTRACTION_VERSION` v31; ledger: `bill_kind`/`line_type` written and read (`kind_column`, `merged_details`, `record()`, `current_details`, `document_traces.current`); `publish_bill` passes `bill_kind`/details/`line_type`/item details (no producer yet: all None). `tests/test_migrations.py` (`bill_kinds`): a v70 DB with a verified PHONE bill and a rent-like bill with a `line_kind` correction upgrades with every money/line/date/category/review column equal, `bill_kind` NULL, 0 runs, 0 jobs, health check passes; a parse with only a v30 run gets `reused: False`. Creates `tests/test_bill_kinds.py` with the `version` test (R3-m1). | `python -m pytest tests/test_migrations.py -k bill_kinds -q`; `python -m pytest tests/test_bill_kinds.py -k version -q`; `python -m pytest tests/test_receipt_kinds.py tests/test_traces.py tests/test_migrations.py tests/test_bills_ledger.py tests/test_invoice_ingestion.py -q` (unfiltered: SL-01 touches the receipt-kind and bill publish paths and every migration upgrades to the latest; R3-m2, R4-m6) (one `-k` per command: pytest keeps only the last `-k` and applies it to every file; R2-M1) |
| SL-02 | FR-40, FR-41, FR-43, FR-44, FR-45, FR-45b; SC-38 (1–3, lines, C-*), 38a–38d, SC-43 (1–4, 43a, 43b), SC-43b (43b-1), SC-44 (a–d), SC-50 PHONE part | SL-01 | `extraction.py`: `printed_dates` + `date_printed` with their unit tests (moved here from SL-03, R1-M3: line periods and the whole month need them), `BILL_KINDS`, Classification fields, `CLASSIFY` sentence, `bill_kind()`, `BillRentSummary`, `BILL_FORMS`, `BILL_KIND_LABELS`, `RentBillLine(s)`, rent row instructions (incl. FR-58 sentence), `extract()` form choice + general fallback, `normalize(bill_kind=)`, `bill_lines` rent rows (types, FR-45b, categories, mapped `line_kind`, line period/usage citation checks, whole month), `record["bill_kind"]`, invoice guard; `publish` threads `bill_kind`. New `tests/bill_kinds_fixtures.py` (RENT and variants per the contract, `rent_replies(lines, **changes)`); `tests/test_bill_kinds.py` gains (`sc38*`, `sc43` steps 1–4 + 43a/b, `sc43b*`, `sc44*`). | `python -m pytest tests/test_bill_kinds.py -k "sc38 or sc43 or sc44" -q`; `python -m pytest tests/test_bills_ledger.py tests/test_invoice_ingestion.py tests/test_extraction.py -q` (unfiltered) |
| SL-03 | FR-46, FR-47, FR-48, FR-55; SC-39 (+39a–c), SC-40, SC-41 (+41a), SC-42 (a–e), SC-46b (+46b-1, 46b-2) | SL-02 | `extraction.py`: `bill_dates` (header dates, every bill kind), FR-47 period from rent lines, `LABELS["bill"]` Issued/period sentences; yearless-date cases added to the `printed_dates` unit tests. (SL-02 already writes line-date notes into `details.notes`.) `tests/test_bill_kinds.py` `sc39` (with `Reconciler`, 39a published directly via `publish_bill`), `sc40`, `sc41`, `sc42`, `sc46b`. | `python -m pytest tests/test_bill_kinds.py -k "sc39 or sc40 or sc41 or sc42 or sc46b or dates" -q`; `python -m pytest tests/test_bills_ledger.py tests/test_invoice_ingestion.py tests/test_recurring_bills.py tests/test_extraction.py -q` (unfiltered; this is where R2 shows) |
| SL-04 | FR-49, FR-54, FR-56, FR-58; SC-38 trace, SC-46 extraction (1, 3), SC-46a, SC-46c (1–3, 46c-1, 46c-2 proposal), SC-46e extraction (a, b) | SL-03 | `finance/document_checks.py` `bill_lines`, `bill_carried`; `extraction.py` `bill_lines` checks + named issues, FR-54 earlier lines, FR-56 recurrence/prorated/`monthly_rent`; `document_traces.py` bill branch + `bill.lines`/`bill.carried`; `reconcile.py` `propose_bills` FR-56. Tests `sc38` trace assertion, `sc46` (extraction checkpoints + trace lists four values), `sc46a`, `sc46c` (plus a plan-level 8-day move-in variant `Rent 10/24/2026 - 10/31/2026`: monthly, prorated note; R2-M2), `sc46e`. | `python -m pytest tests/test_bill_kinds.py -k "sc38 or sc46" -q`; `python -m pytest tests/test_traces.py tests/test_recurring_bills.py tests/test_bills_ledger.py -q` (unfiltered) |
| SL-05 | FR-45a; SC-43a (+43a-1, 43a-2 after SL-06's step-5 correction), SC-46c-2 projection | SL-04 | `finance/tools.py` `get_budgets` parts + trace steps. Test `sc43a`: verified RENT → proposal (monthly, 148842, next due 2026-11-01) → confirm via `POST /api/finance/recurring/{id}/review` → `get_budgets(month=2026-11, as_of=2026-11-01)` housing projected 145000, utilities 3842, neither 148842; `budget.projected` trace steps name the payee; 43a-1 PHONE unchanged; a recurring bill proposed from a bank payment to the rent payee stays whole. | `python -m pytest tests/test_bill_kinds.py -k "sc43a or sc46c" -q`; `python -m pytest tests/test_budgets.py tests/test_recurring_bills.py -q` (unfiltered) |
| SL-06 | FR-42, FR-45 (corrections); Journey SC-45 (1–8, J-a–J-d), SC-43 step 5 | SL-02 | `manager.py` `change_kind` (bills), `api.py` `ReceiptKindInput`/`LineInput`, `extraction.py` `requested_kinds(..., document_type)`, ledger `chosen_kind(field)`, `_undo_kind`/`undo_corrections` for `bill_kind`, `LINE_FIELDS`/`correct_line`/`_set_line`/`delete_item` for `line_type`, labels "Bill kind" / "Type of". Tests `journey` (one function, one library; step 5 holds a reading with a stub that waits on an event), `sc43` step 5. | `python -m pytest tests/test_bill_kinds.py -k "journey or sc43" -q`; `python -m pytest tests/test_receipt_kinds.py tests/test_bills_ledger.py -q` (unfiltered) |
| SL-07 | FR-50, FR-51, FR-42 UI; SC-46 page (2, 4), SC-46e page, SC-47, SC-48 (1–8), SC-50 PHONE page (`-k phone`: Earlier balance 12.00, still verified) | SL-04, SL-06 | `ledger.py` `bill_summary`, rent `correctable` Type options; `receipt.js` `RECORD_FIELDS.bill`, `billLines`, `RENT_TYPE_LABELS`; `document_v2.js` Counts as, `doc2Forms`/`doc2Kind`/`doc2Pending` for bills, notes list, worked-out mark; `ui.js` `dateRangeText`; `records_v2.js:438`; `style.css` (tfoot rule) if needed. New `tests/test_bill_kinds_browser.py` (`sc46`, `sc46e`, `sc48`, 360 px no horizontal scroll, no console/CSP errors) on the `test_document_v2_browser.py` fixture pattern; `test_document_v2_browser.py` and `test_bills_v2_browser.py` run unchanged (R3); a failure there is reported as a deviation, not edited away. Synthetic before/after shots via `.claude/skills/ui-redesign/scripts/ui_shots.py` (the `ui-redesign` skill's procedure). | `python -m pytest tests/test_bill_kinds_browser.py tests/test_document_v2_browser.py tests/test_bills_v2_browser.py -q`; `python -m pytest tests/test_bill_kinds.py -k summary -q`; `python .claude/skills/ui-redesign/scripts/ui_shots.py` (synthetic) |
| SL-08 | FR-53, FR-57; SC-46d, SC-49 step 3, SC-50, SC-51 | SL-01–SL-07 | `evals/tasks/document_forms.py` bill cases + report; `tests/test_eval_tasks.py` (`document_forms and rent`: all-correct row; one wrong Issued → only Issued wrong); `tests/test_bill_kinds.py` `sc46d` (share by line as the phone test), `version` (step 3: the v30 bill's `line_kind:N` correction survives reading it again as rent: `line_kind` = the person's value, `line_type` = the reading's, per the replay rule; R2-m2); docs: `docs/money.md` "Bills and their lines" (kinds, rent form, date rules, earlier balance row), `docs/documents.md` "Bill kinds" beside "Receipt kinds", `docs/open-work.md` (utility, phone, insurance kinds; family routing doesn't carry `bill_kind`, `line_type` or bill details yet, R1-m8), `docs/evals.md` (the RENT case), code citations to those headings. Full targeted run from the contract. | `python -m pytest tests/test_bill_kinds.py tests/test_bill_kinds_browser.py tests/test_bills_ledger.py tests/test_recurring_bills.py tests/test_invoice_ingestion.py tests/test_migrations.py tests/test_eval_tasks.py tests/test_document_v2_browser.py tests/test_budgets.py -q`; `git diff docs/` reviewed |

## Requirements & scenarios coverage matrix
| FR | Slice | Scenarios / tests |
|---|---|---|
| FR-40 | SL-02 | SC-38 (kind + C-cite of its citation), SC-44d, SC-47 (SL-07) |
| FR-41 | SL-02 | SC-44, 44a–44c |
| FR-42 | SL-06, SL-07 | Journey SC-45, J-a–J-d; SC-48 step 7 |
| FR-43 | SL-02 | SC-38 step 2 (schema on the captured request: `previous_balance`, `payments_received` with instructions, rent types, line period, usage; no fuel/dining/grocery field; no general request); previous/payments null |
| FR-44 | SL-02 | SC-38 lines, 38a, 38b |
| FR-45 | SL-02, SL-06 | SC-43 1–4, 43a, 43b (SL-02); step 5 (SL-06) |
| FR-45a | SL-05 | SC-43a, 43a-1, 46c-2 projection |
| FR-45b | SL-02 | SC-43b, 43b-1 |
| FR-46 | SL-03 | SC-39, 39a–39c |
| FR-47 | SL-03 | SC-38 period, SC-40, SC-41, 41a, 46c-1 (SL-04) |
| FR-48 | SL-03 | SC-42a–e, SC-46b water, 38a |
| FR-49 | SL-04 | SC-38 trace, SC-46 1/3, SC-46e b |
| FR-50 | SL-07 | SC-46 2/4, SC-46e b page, SC-47, SC-48 1/5/6 |
| FR-51 | SL-07 | SC-48 2–5, 8 |
| FR-52 | SL-01, SL-08 | SC-49 1–2 (SL-01), 3 (SL-08) |
| FR-53 | SL-08 | SC-51 |
| FR-54 | SL-04 | SC-46a |
| FR-55 | SL-03 | SC-46b, 46b-1, 46b-2 |
| FR-56 | SL-04, SL-05 | SC-46c, 46c-1, 46c-2 |
| FR-57 | SL-08 | SC-46d |
| FR-58 | SL-02 (instruction), SL-04 (check), SL-07 (page) | SC-46e |
| Invariants C-cite, C-date, C-money, C-ids, C-calls | SL-02 onward | a shared `assert_published_bill(db, lines)` oracle in `tests/test_bill_kinds.py`, called in every publishing scenario |
| Regression | SL-02, SL-07, SL-08 | SC-47, SC-50, 43a-1 |

## Test environments, data, stubs for nondeterministic components, final-state oracle
- **Unit**: `printed_dates`/`date_printed` table tests; `document_checks.bill_lines`/`bill_carried`; `bill_kind()` on
  hand-built `Classification`s (SL-02, SL-03, SL-04).
- **Integration** (`tests/test_bill_kinds.py`): `transcribe`/`extract` (`tests/test_extraction.py`) or
  `document_forms_fixtures.library` + `record_document` on `tmp_path`; the `local_model` loopback with `by_schema` replies
  (`Classification`, `BillRentSummary`/`BillSummary`, `RentBillLines`/`BillLines`); request assertions read
  `local_model["requests"]` (schema names, field names, no `image_url`, request count equal to a general bill's).
  Reconcile/budget scenarios use `Reconciler(store).run()` and `FinanceTools.get_budgets` with explicit `as_of`; no test
  reads today's date. The journey's "reading in progress" uses a stub that blocks on a `threading.Event`.
  The bill kind's citation (C-cite, SC-38 step 3) is checked in the run's `result_json` classification
  (`bill_kind_evidence`), the only place it is stored (R1-m7).
- **Final-state oracle** (independent of the code under test): direct SQL on the library database: `receipts`
  (`bill_kind`, dates, `total_minor`, `amount_due_minor`, `review_status`, `review_source`, `validation_json`,
  `details_json`), `receipt_items` (`line_type`, `line_kind`, `category`, `details_json`), `record_corrections`,
  `transaction_receipt_links`, `recurring_obligations`, `extraction_runs`; `stored_identifiers` for C-ids; the ledger
  health check (`tests` helper used by `test_bills_ledger.py`).
- **UI** (`tests/test_bill_kinds_browser.py`): Playwright on the synthetic library, seeded through the same publish path;
  asserts visible text, row order, Find highlighting the cited line ids, console/CSP clean, 360 px no horizontal scroll.
- **Eval**: stubbed CI run of `document_forms` (`tests/test_eval_tasks.py`). Live accuracy only by the user on their own
  bill, sharing `summary.json` (U3).
- Synthetic data only; `tmp_path` cleanup by pytest.

## Risks, unresolved decisions, alternatives
- **R1 — resolved in the spec (amended 2026-10-19).** FR-50 now defines "Earlier balance" (nothing carried, new charges
  printed, lines add up to them; any bill kind) and "Not accounted for" otherwise; SC-50 asserts the PHONE page. The
  amendments also settled S2 (`monthly_rent` in FR-43), S3 (FR-45a: categories decide; FR-56 uses lines in `utilities`),
  S4 (FR-54 anchored on the due date's month, as P3), S5 (FR-42: lines change only on a reading, as "Kind and lines")
  and S6 (no rebuild, as P1). SL-07 adds `tests/test_bill_kinds_browser.py -k phone`; SL-05 adds 43a-2.
- **R2 — existing fixtures whose date citations don't print the date** would now drop those dates (FR-48 applies to every
  bill). SC-50 requires the bill suites to pass unchanged, so any such failure stops the slice and is reported as a
  deviation for the user to decide; no test is edited silently (R1-m1).
- **R3 — existing browser suites.** Verified: `test_bills_v2_browser.py:133` ("Counts as" in the review drawer) and
  `test_document_v2_browser.py:372` (a receipt page) don't assert the bill rows FR-50 removes, so both run unchanged (R1-m1).
- **R8 — prorated skip covers the bill only.** `propose_bills`' transactions loop can still propose from a housing-category
  bank payment to the same payee (today's behaviour). Accepted; FR-56 is about the bill's own proposal.
- **SC-41 stub wording.** The contract says the line is "answered as `October 2026`"; the schema asks for `YYYY-MM`, so the
  test stubs `2026-10` for that line (R5 info).
- **R10 — prorated plus full-month lines on one bill (46c-1).** The spec doesn't say whether it proposes a recurring bill.
  As planned it carries the prorated note and proposes none (with no printed `monthly_rent`); the next bill proposes it.
  Open for the user (spec gap from pass 2).
- **R9 — family routing** (`finance/family_routing.py` `record_payload`) doesn't carry `bill_kind`, `line_type` or bill
  details, so a routed rent bill arrives without a kind (spec D21: family sharing unchanged). Logged in `docs/open-work.md`.
- **R4 — numeric date order.** Both M/D and D/M readings count as "printed" (P5). A model that swaps day and month on an
  ambiguous date (10/01 vs 01/10) passes the check; the order rule in `RULES` is unchanged.
- **R5 — FR-54 anchor (P3).** A ledger printout whose due date is in an earlier month than the current rent (rent billed
  far in advance) could leave out nothing; measured only by the user's real bills.
- **R6 — "gas" in a description** makes a line a utility on a rent bill (FR-45b); accepted for rent bills only.
- **R7 — filing date.** A rent bill with no Issued files under the classification's document date (today's fallback),
  which is usually the due date. Unchanged; noted.
- **Alternatives rejected:** rebuilding `receipts` to widen `receipt_kind` (P1); storing the rent type only in
  `details_json` (corrections and the CHECK would be lost); `base_answer` instead of the general re-read (it wouldn't
  give the spec's "Read as a general bill" outcome for row failures).
- **No new dependencies.**
