# Table engine, phase 4: bills read from their printed columns — implementation plan
Spec: specs/pdf-table-engine-bills/spec.md (with specs/pdf-table-engine-bills/test-contract.md)
Spec sha256: 3e503a0397d6d19e92f8e7406f145f9c0b41eb1919e3801a42abd3334d491128
Review-Risk: HIGH
Review-Risk-Rationale: It changes which printed number becomes every text-PDF bill's lines, amount due and counted new
charges (money out, budgets), turns one file into several bill records, rejects VOID and duplicate bills automatically, and
changes when a kept user correction is re-applied after a reading again.

<!-- Approval lives in approvals/pdf-table-engine-bills.json, bound to this file's hash. No Status line.
     Execution progress goes in plans/pdf-table-engine-bills/progress.yaml, never in this file. -->

**Scope.** FR-100 – FR-135 and SC-100 – SC-131 of the approved spec and test contract. That is 32 FRs, more than
plan-feature's guide of about 10. The spec was approved as one bundle (2026-11-09). Phases 1 and 2 set the precedent of
one plan in milestones, so this plan keeps one feature in milestones, each verified on its own:
- **M1, the bill engine** (no visible change): SL-01, SL-02.
- **M2, Record uses it for one bill**: SL-03 (lines), SL-04 (summary amounts).
- **M3, corrections**: SL-05 (FR-119; every bill).
- **M4, several bills in one file**: SL-06 (the split), SL-07 (VOID, duplicates), SL-08 (the document page).
- **M5, proof and measurement**: SL-09 (generator and the `bill` probe), SL-10 (evals and docs).

Splitting M4 into its own feature was considered (see "Alternatives") and not taken.

**Base.** Line numbers are from HEAD `e2c2d5d`. Paths are under `src/home_manager/` unless they start with `tests/`,
`evals/`, `scripts/` or `docs/`.

Planning began at `06cbb9b`. Commit `e2c2d5d` ("Statement fixes: copied account digits, card statements with no rows,
evidence version") landed during planning. It committed the edits that were then uncommitted (`docs/documents.md`,
`core/identifiers.py` `last_four`, the `RULES` and `CLASSIFY` text in `documents/extraction.py`, a statement-only branch in
`normalize`, `tests/test_identifiers.py`, `tests/test_statement_accounts.py`, `tests/test_table_engine_record.py`), and it
bumped `EXTRACTION_VERSION` to `typed-extraction-v40-statement-fixes`. Every citation below was re-checked against
`e2c2d5d`: `extraction.py` lines after `:697` moved by 3 and lines after `:2510` by 10; no other cited file changed. The
statement branch and the `last_four` change don't touch the bill path. The bill's account last four still comes from
`normalize`'s identifier fields (`:2428`), and since `e2c2d5d` `last_four` keeps only digits printed in the cited lines, so
every stub's account answer cites the fixture's `Account Number` line (as the contract's doubles say: "with printed values
and lines"). **Precondition of SL-01 (review pass 2, M1).** On 2026-11-09 the working tree again holds someone else's in-flight
tracked changes (among them `finance/ledger.py`, which SL-03, SL-05 – SL-07 edit, `app/static/document_v2.js`, which SL-08
edits, `docs/documents.md` and `docs/money.md`, which SL-10 edits, and an untracked
`library/migrations/078_account_type_words.sql`). Before START_HEAD is recorded, `git status --porcelain
--untracked-files=no` must print nothing, and no untracked file may sit under `src/` or `tests/`: the human commits or
stashes that work first. The orchestrator then re-checks every citation in this plan against START_HEAD, always, not
only when HEAD has moved, and the baseline failures (Final verification) are taken on START_HEAD.

## Verified repository integration points

| Area | Where (HEAD `e2c2d5d`) | What this plan uses |
|---|---|---|
| Engine primitives | `documents/table_engine.py`: `ALIGN` `:30`, `AMOUNT`/`NUMBER`/`INTEGER` `:197–200`, `amount_of` `:234`, `tokenize` `:286` (`3,200` is an amount token, `500` an `integer`, `10/01/2026` a date, `0.1430` an amount), `read_tokens` `:310`, `tokenize_page` `:383`, `choose_alignments` `:419`, `zones_between` `:449`, `cluster` `:342`, `edge_of`/`in_zone`/`fits` | Reused unchanged by the new charge-table module (P3) |
| Pay engine helpers | `documents/pay_tables.py`: `split_tails` `:221`, `amounts_of` `:136`, `text_only` `:150`, `is_heading_like` `:154`, `heading_runs` `:461`, `heads_above` `:510`, `place` `:527`, `column_sets` `:561`, `offset_of` `:578`; `finance/paystub_tables.py`: `PageMap` `:412`, `cell_of` `:454`, `spans_of` `:531`, `evidence_index` `:542`, `multiplies` `:111` (`covered_rows` `:176` is pay-typed, so it is not reused) | Imported, not changed. Pay stubs can't move (FR-120) |
| Native projection | `documents/layout_context.py:12` `native_page`, `:18` `project_page`, `evidence_lines`, `evidence_tables` | What the model cites; engine rows map to it through word ids (`PageMap`) |
| Classification and run | `documents/extraction.py` `run` `:4105`: one `Classification` (`:4127`); `pay = paystub_tables.read(evidence)` with `PAY_FAILED` (`:4128–4134`); parts only for receipts (`segments` `:4138`) and pay stubs (`pay_parts` `:4140`); per-part classification and "not a …" note (`:4143–4150`); `requested_kinds` (`:4151`, bill kinds per part already supported, `:4198–4200`); `record(... segment, split)` (`:4166`); `save_segments`, `retire_segments` (`:4178–4179`) | Bills get their engine reading once, their own parts rule and the per-part loop (P7, P8) |
| Read | `read` `:4212`, keyword `pay=None`; `pay_layout_notes` `:1368` (drops `unresolved_columns` review notes on engine pages); `pay_tables_of` `:1296`; `without_printed_tables` `:1308`; `anchor_summary` / `anchor_rows` for other kinds (`:4270–4282`); the "native table row(s) were not accounted for" note (`:4290–4309`, `pdf_text` tables only) | A `bill=None` keyword with the same shape as `pay` (P7) |
| Questions | `extract` `:3668`, `read_form` `:3694` (bill forms `BILL_FORMS` `:551`, rows `BillLines` / `RentBillLines`, the row direction text `:3749–3755`, `:3768–3771`); `paystub_table_context` `:1180` (maps `pay_engine` to `pdf_text`); `paystub_chunks` `:1195`; `table_summary` `:1218`; `ask(…, amount_field, …)` `:1963` | The model is shown engine cells and its numbers are not checked where cells decide (P7.3) |
| Bill normalization | `normalize` `:2389` (`money` `:2402`, half-even quantity check in `bill_lines`); `bill_dates` `:905`; `bill_lines` `:2964` (holder rule `:2983–2986`, quantity × unit price `:2988–2997`, details `:3005–3015`, notes into `record["details"]["notes"]` `:3034–3037`, lines and carried checks `:3039–3071`); `rent_line` `:2847`; `earlier_lines` `:2906`; `name_supported` `:1895`; `amount_supported` `:1801`; `printed_in` `:3131` | Extended (P7.5): copied values, printed rates, title holders, worked-out new charges, engine notes |
| Publish | `publish` `:3977`: `issues.extend(notes)` (`:4050`) makes `read` notes review reasons; `record_notes` go to `details["notes"]` only for statements and pay stubs (`:4065–4068`); `guesses` stored for pay stubs only (`:4069–4070`); pay stub VOID and twins (`:4053–4064`, `:4099–4101`) | Bill engine notes join the bill's own `details[bill_kind]["notes"]`; guesses stored for bills (P7.6) |
| Splits | `SPLIT_NOTE` `:1705`, `PAY_SPLIT_*` `:1707–1709`, `VOID_LINE` `:1710`; `pay_parts` `:4405`; `split` `:4438` (joins receipts and income); `confirm_split` `:4461`; `set_split` `:4484`; `saved_segments` `:4514`, `split_confirmed` `:4519`, `save_segments` `:4525`; `user_ranges` `:1767`; `documents/paystub_split.py` `stub_parts` (lines only) | Bills reuse all of it with their own rule and notes (P8) |
| Bill ledger | `finance/ledger.py`: `_upsert` `:699` (receipts by `(blob_hash, segment)`); `publish_receipt` `:719`; `merged_details` `:779` (keeps every top-level key except the kind it replaces); `retire_segments` `:959` (worded "receipt" for every receipts row); `_replace_items` `:990`; `publish_bill` `:1428`; `pay_stub_twin` `:1481`, `reject_automatically` `:1498` (income only); `record` `:1878` (item `display` from `*_minor` ints `:2049–2052`); `bill_summary` `:2459`; `apply_corrections` `:2694` (`receipt_item` fields at their position, whatever line is there); `correct_item` `:2821`, `_correct_item_field` `:2865`, `correct_line` `:2879`, `_correct_item` `:2932`; `LINE_FIELDS` `:205`, `ITEM_FIELDS` `:208`; `history` `:2562`, `undo_corrections` `:2626` | FR-119 guard (P9), bill twins and VOID (P8.6), retire wording, unit-price display (P7.7) |
| Corrections table | `record_corrections` (`066_library_revision_bills.sql`: id, record_type, record_id, field, value, previous, resolved_issues_json, reason, actor, created_at); `receipt_items.details_json` (`070_document_forms.sql`); `receipts.details_json` `{<bill kind>: details}`; `receipts.segment`, `document_segments` (`054`) | No migration (FR-121, SC-121 step 3): see P9's storage |
| Checks and traces | `finance/document_checks.py`: `product` (half up, `TOLERANCE = 1`), `unit_line`, `bill_lines`, `bill_carried`; `finance/document_traces.py` `bill_checks` `:73`, `current` `:56`, the `bill.lines` / `bill.carried` refs `:285–286` | Product checks per engine line on the printed rate; worked-out working (P7.5, P7.8) |
| Family | `finance/family_routing.py:60` `phone_member` (the last four of all the holder's digits), `:68` `suggest` | Unchanged; title holders feed it (P5) |
| Library | `library/storage.py:576–581` (an amount only when one non-rejected receipts row); `:583–586` (a bill file's kind, due date and period: `LIMIT 1`, no order); `:596` (date `min(purchase_date)` over non-rejected); `:559` (merchant `ORDER BY r.segment`) | `ORDER BY r.segment` added to `:583–586` (FR-135) |
| Document page | `app/static/document_v2.js:377` (the panel only when `publication.segments`); `:860–905` `doc2Split` (`receipt`/`pay stub` nouns, the To check warning `:870`, chips `:874–876`, Split here `:892–901`); `:589` notes shown for bills; `app/static/receipt.js:229–230` (Unit price from `display.unit_price_minor`) | Bill wording, the one-bill Split here (P10) |
| Diagnose | `scripts/statement_diagnose.py`: argv `:125`, temporary folder `:127–131`, `paystub` mode `:133–135`, `pay_section` `:64` | A `bill` mode (P11) |
| Evals | `evals/run.py`: `table_readers` `:159`, `pay_readers` `:219`, `pipeline` `:265` (`:303–308`), `grade_case` `:252–262`; `evals/graders.py`: `pay_reader` `:209`, `split_is_right` `:261`, `grade_stubs` `:298`, `guess_counts` `:307`; `evals/report.py` (`:79–80`, `:130–141`, `pay_reader_summary` `:214`, `guess_summary` `:228`, the allowed keys `:301–315`); `evals/corpus.py:73` `Case.stubs()`; `evals/synthetic.py`: 53 documents, `PAYSTUB_SEED` `:37`, `aligned_paystub` `:247`, appended `:329`, image bills `:206`, `:314–317`; `evals/paystub_layouts.py` | A bill readers comparison, multi-bill answers, five aligned files (P12) |
| Tests to reuse | `tests/test_pdf.py` `make_pdf`, `pdf_store` (`:101`); `tests/test_paystub_engine_record.py` `no_network` (autouse, `:48`), `Run` (`:92`), `started` (`:170`); `tests/test_paystub_split.py` `mini_file`, `Stubs`, `segments_of`; `tests/conftest.py:34` `assert_ledger_healthy`, `local_model`; `tests/model_server.py` `by_schema`; `tests/test_bill_kinds.py` `assert_published_bill`, `read_bill`, `rent_replies`; `tests/test_bills_ledger.py` `WHO` | Reused by the new test modules |
| Version | `extraction.py:49` `EXTRACTION_VERSION = "typed-extraction-v40-statement-fixes"` (phase 3 set v37; the receipt specs set v38 and v39; `e2c2d5d` set v40 for statements) | → `typed-extraction-v41-bill-engine` (FR-121: it changes; the spec's "from v39" names HEAD when it was written, see "Version" in Decisions) |

## Architecture, contracts, data flow and decisions

### P1 Modules
- **`documents/charge_tables.py` (new): charge tables from a saved reading** (FR-100 – FR-104). It is pure, like the
  engine: no store, model, network, clock or randomness. It imports `table_engine` and `pay_tables` helpers and nothing
  from `finance/`. It holds the fixed word lists: `ANCHOR_WORDS` (FR-103), `LATE_WORDS`, `TOTAL_WORDS`, `CREDIT_SECTION`
  (FR-106), and the phone form `PHONE` (FR-102 a).
- **`finance/bill_tables.py` (new): what the columns mean** (FR-105, FR-106). It also holds the rate-to-cents rule
  (FR-110, D21, D25), the guesses (FR-124), and the adapter Record reads (P4). It imports `charge_tables`, `paystub_tables`
  (`PageMap`, `cell_of`, `spans_of`, `evidence_index`, `multiplies`), `document_checks` and `core/money`.
- **`documents/bill_split.py` (new): where each bill starts** (FR-128, FR-129 a – c). It is pure and reads lines only. It
  imports `charge_tables.anchor_kind`, the key-label list it owns (`KEY_LABELS`, FR-128) and `table_engine.read_tokens`.
- Changed: `documents/extraction.py`, `finance/ledger.py`, `finance/document_traces.py`, `library/storage.py`,
  `app/static/document_v2.js`, `scripts/statement_diagnose.py`, `evals/*`. `documents/table_engine.py`,
  `documents/pay_tables.py`, `finance/paystub_tables.py` and `documents/paystub_split.py` are **not changed**.

### P2 Contracts
```
ChargeColumn(id, align, edge, extent, zone, labels: [heading words top to bottom], label_words: [[word ids]],
             kind: "amount" | "usage" | "integer")        # usage: numbers printed with a unit word ("500 kWh"), kept as printed text
ChargeRow(page, table_id, row, line_ids, word_ids, label, amounts: {column_id: Token}, usage: {column_id: (text, word_ids)},
          section: str|None, title: SectionTitle|None, stray: [Token])
ChargeTotal(page, table_id, row, line_id, word_ids, label, values: {column_id: Token})
SectionTitle(page, line_id, word_ids, text, phone: bool)  # phone: FR-102 (a) holds on its text alone
Anchor(page, line_id, word_ids, kind: "previous_balance"|"payments"|"new_charges"|"amount_due", token: Token, order: int)
ChargeTable(id "page-<p>-charges-<n>", pages, label_column, columns, rows, totals, titles, headings)
Unplaced(page, line_id, text)
BillReading(tables, other_tables, anchors, late_lines: [line ids], unplaced, pages_without_tables: [int], line_pages)

Roles(table_id, roles: {column_id: "charge"|"quantity"|"unit_price"|"other"},
      decided_by: "product"|"sum"|"subtotals"|"heading"|"single"|"guess")
Guess(kind: "charge_column"|"unclassified_row"|"amount_due"|"split_changed", page, table_id|None, text)
BillTables(reading, roles, adapted, guesses, notes, engine_pages: set, line_pages, lines_of)   # the shape for_lines keeps
PrintedRate(minor: int, text: str|None)    # text only when the value is not a whole number of minor units (D25)
BillSplit(parts: [(first, last)], reasons: {part index: [str]})
```
Serialization for determinism: `json.dumps(dataclasses.asdict(x), sort_keys=True)`. Money stays `Decimal` tokens until
`core/money.to_minor`. Positions are floats; money never is.

### P3 Charge tables (FR-100 – FR-104), `charge_tables.read(result) -> BillReading`
Only `embedded_text` pages with a saved layout are read. Per page: `PageView`, `tokenize_page`, `pay_tables.split_tails`
(a run is cut where text or an integer follows an amount). Then, before any line is classed, the tokens a `PHONE` match
covers (below) become `text` tokens (review pass 1, M3). The tokenizer reads `(555)` as a readable amount, so without this
`Blair (555) 202-2222` would not be text-only and could never be a section title. Each line is classed **in this order**.
The first match wins, and every class is accounted for in FR-104:
1. **Late-payment line** (FR-103, bill-kinds FR-58). It is an amount that applies only later, so the line must print a
   **condition with a date** (review pass 1, M2). `LATE_WORDS` matches, case-insensitive: `if (paid|received) after
   <date>`, `if not paid by <date>`, `after <date>, (pay|a late)`, and `late (fee|charge|payment charge) (after|if not paid
   by|applies after) <date>`. A condition with no date counts too, since FR-103 names "if paid late" (review pass 2,
   m3): `if paid late`, `if (payment is|paid) (late|after the due date)`, `if not paid on time`, `if not paid by the due
   date`. A late line is no anchor, no row and not unplaced; it is kept in `late_lines`, and its amount
   is never an anchor value (SC-103 step 2, SC-117 step 4). A charge billed this period, such as `Late Fee 5.00` or `Late
   Payment Charge 4.50` with no condition, is an ordinary charge row (step 5). The generator prints both forms, and one dateless late condition (P12).
2. **Summary anchor** (FR-103). The *label* is the text before the line's last amount token, with these removed: dates,
   together with a `by`, `on or before`, `as of` or `on` directly before a removed date (review pass 1, m3), dot leaders, a
   trailing `:`, `$`, ` | ` cell separators, and `–`/`-` used as a separator. So `Amount Due by 10/15/2026 97.55` is an
   amount-due anchor. If that label **fully** matches one of the
   `ANCHOR_WORDS` phrases (case-insensitive, whole words, whitespace collapsed), the line is an `Anchor` of that kind. Its
   value is the last amount token. Lists:
   - previous balance: `previous balance`, `balance forward`, `last bill`, `previous bill amount`;
   - payments: `payment`, `payments`, `payment received`, `payments received`, `payment - thank you`,
     `payments - thank you`, `payment thank you`;
   - new charges: `new charges`, `current charges`, `total current charges`, `total new charges`;
   - amount due: `amount due`, `total amount due`, `total due`, `balance due`, `amount to pay`, `total amount to pay`,
     `payment due` (review pass 2, m4: a remittance stub's `Payment Due 10/15/2026 97.55` prints the amount due after
     the due date; the date is removed from the label as above, so the label is `payment due`).

   Without an amount, `Payment Due 10/15/2026` is no anchor (an anchor needs an amount) and is a key line (step 3). With an
   amount it is an amount-due anchor here **and** the split rule's due key (P8.1 reads every line's text, whatever its class
   here), so the two definitions agree on it. `Minimum Payment Due` stays no anchor (the label must fully match).

   (The plan may add synonyms the generator prints. The list is one module constant, and docs/documents.md documents it,
   SC-103 step 4.) A label that only *contains* an anchor phrase (a sentence) is no anchor; see G7 below.
3. **Key line** (FR-128's key labels, via `bill_split.key_of(line)`). It prints a key label and its value and no amount
   token outside a date: header text, never a row. Key lines with an amount (`Account Number 1234-5678-9012`) are tokens
   of `text`/`integer` kind, so they are no charge row anyway.
4. **Total** (FR-102). The label matches `TOTAL_WORDS` (`^(?:sub)?total\b`, `^total for\b`, `\btotal$`) and the line holds
   an amount. It becomes a `ChargeTotal` with one value per column it fits. Lines that matched an anchor in step 2
   (`Total Amount Due`, `Total Current Charges`) never get here.
5. **Charge-row candidate** (FR-100). The first run starts with text (the label), and the line holds at least one amount
   token after the label. Dates are label text. An amount or integer token followed **in its own run** by a word other
   than `CR`/`DR`/an ISO code (`3,200 GAL`, `1,234 kWh`, `450 min`) is **usage**: label text, never money. Dot leaders are
   dropped from labels.
6. Everything else is text (headings, titles, prose, wrapped label lines).

**Columns (FR-101).** Within a page, amount tokens of the candidates are grouped by `choose_alignments` with the engine's
`ALIGN` tolerance and support rule (two rows, or one under a heading label): `kind="amount"`. Usage runs that line up on
two rows (or one under a heading) form a `kind="usage"` column. Their value is the printed text (`500 kWh`), and `Decimal`
of the number is kept for FR-105 (a). Columns of bare integers that line up form `kind="integer"` columns (a usage history),
which never hold money. Zones come from `zones_between`. Headings are text-only lines directly above the first row, up to
two, or one run over several zones split by zone (`pay_tables.heading_runs` / `heads_above`, phase 3 FR-89). They label the
columns under them; their wording is never required.

**Rows, sections, wrapped labels, tables (FR-102, FR-104).** Scanning a page's lines top to bottom:
- A candidate is a `ChargeRow` of the open table when its amounts fit the table's zones.
- A text-only line at the label column's left edge (within `ALIGN`) followed by a candidate is a `SectionTitle`. It is kept
  as `section` (its text) and `title` on the rows below, until the next title or total-ending.
- An indented text-only line directly under a row (left edge past the label column by more than `ALIGN`) joins that row's
  label, line ids and words (`International Pack (Canada and Mexico)`, FR-116).
- A table is a run of rows sharing its column set. A new column set on two or more rows starts a new table. A next page
  whose rows fit the same columns at a page offset (`pay_tables.offset_of`, at most `MAX_OFFSET`) continues the table
  (phase 3 FR-92 b).
- A table whose columns are all `integer` or `usage`, or that P5 gives no `charge` column, goes to `other_tables` (FR-104).
  Its lines are accounted for and give no lines.

**Holder titles, engine side (FR-102 a).** `SectionTitle.phone` is true when the title text holds a phone number by
`PHONE`, one of these alternatives:
- (i) grouped digits:
  `(?<![\d,])(?<!\d[\s.,-])(?:\+?1[\s.-])?(?:\(\d{3}\)\s?|\d{3}[\s.-])?\d{3}[\s.-]\d{4}(?![\s.-]?\d)`. That is a
  4-digit last group directly after a **3-digit** group, optionally after a 3-digit area code and a country code `1`, with
  no digit group directly before or after (review pass 1, m1).
  - Checked against: `Alex 555-201-1111`, `Blair (555) 202-2222`, `Alex 555.201.1111`, `Line 201-1111`, `+1 555-201-1111`
    and `1-555-201-1111` match.
  - Checked against: `Charges 2025-2026`, `2025 - 2026`, `Account 1234-5678-9012`, `555-0100-7788`, `Charges 2026` and
    `Card 4111 1111 1111 1111` don't match, nor does a quantity printed `1,234.5678` (a comma before the digits is
    excluded too; review pass 2, m5).
- (ii) masked: one or more groups of `x`/`X`/`*`/`•` (separated as above) then a 4-digit group: `xxx-xxx-1111`,
  `***-1111`, `•••• 1111`.
- (iii) after `ending`, `ending in` or `ends in`: `\b(?:ending(?:\s+in)?|ends\s+in)\s+\d{4}\b`.

A bare 4-digit number is never a phone. Year ranges and account numbers are excluded by (i)'s 3-digit group; see G14.
Rule (b) (a name the model gave) needs the model's holders and is decided in Record (P7.4).

**Unplaced (FR-104).** On a page holding a charge table, any candidate or total not taken by a table is `Unplaced(page,
line_id, text)`. The text includes its amount, as phase 2 did. The same goes for a line whose label contains an anchor
phrase but is no anchor (G7). Pages with a layout and no charge table go to `pages_without_tables` (FR-114). Pages with no
layout are not read and get no note (SC-114 step 3).

### P4 Roles, money off, rates and the adapter: `finance/bill_tables.py`
**Roles (FR-105)**, per charge table, in order:
- **(a) product.** Columns q, r, c where `multiplies(q, r, c)` (the `document_checks.product` rounding, half up, within
  `TOLERANCE`) holds on every row printing all three, and at least one row does. q is the `usage` or `integer` column, or
  else the column printing fewer decimal places. r is the other one: rates print 4 decimals, quantities print whole
  numbers. Then q is `quantity`, r is `unit_price` and c is `charge`.
- **(b) sum.** The column whose signed amounts add up exactly to a target is the charge. Signs come from FR-106: a
  money-off row counts negative. The targets are every new-charges anchor value on the table's pages; else, with
  previous-balance and payments anchors there, the FR-118 value amount due − previous + |payments|; else every amount-due
  anchor value. A column also qualifies when every printed `ChargeTotal` value in it equals the rows it covers. Coverage is
  phase 3 FR-91's rule: the rows since the previous total, or since the start of the total's section, and either holding
  is enough. `paystub_tables.covered_rows` breaks only on `PayTotal` instances, so `bill_tables` uses its own
  `covered(entries, position)` on `ChargeRow`/`ChargeTotal` with the same rule (review pass 1, m2).
- **(c) headings** break a tie, and are the only guide when (a) and (b) decide nothing. Charge words: `charge`, `charges`,
  `amount`, `current`, `this bill`, `this period`, `total`. Other words: `last year`, `previous`, `prior`, `usage`, `rate`,
  `kwh`, `meter`, `reading`, `days`.
- **(d)** One amount column is the charge (`single`).
- Two columns that both satisfy (b), with no deciding heading: the right-most is the charge. This adds a
  `Guess("charge_column", page, table_id, "Page N: two printed columns add up to the bill's charges; the right-most was taken as the charge.")`.
- Every other column is `other` and never money. A table with no charge column is an other table (P3).

**Money off (FR-106).** A row is money off when its charge token has a `minus` marker (minus sign, parentheses or a
trailing `-`), or a `credit` marker (`CR`). It is also money off when it is unsigned and its section title matches
`CREDIT_SECTION` (`credit(s)`, `discount(s)`, `adjustment(s)`, whole words). `money_off(row, roles) -> bool` is used by
(b) and by Record.

**Rate to cents (FR-110, D21, D25):** `printed_rate(text, currency) -> PrintedRate`. Take `value = Decimal(text without ,
and $)` and `scaled = value × 10^exponent`. When `scaled` is whole: `PrintedRate(int(scaled), None)`, with no text kept.
Otherwise: `PrintedRate(int(scaled.quantize(1, ROUND_HALF_UP)), text)`. It never raises a precision issue. It gives
`0.1430` → 14 with text, `0.1450` → 15 with text, `0.1449` → 14, `0.1451` → 15, `0.0050` → 1, `0.125` → 13, each with
text. It gives `0.1200`, `0.12` → 12 and `0.1500` → 15 with no text, and `13.00` → 1300 with no text (SC-110 step 6's
unit list).

**Read:** `bill_tables.read(evidence) -> BillTables`. Steps: `charge_tables.read`, roles per table, then the adapter. The
adapter makes `SimpleNamespace(id, page, pages, source="bill_engine", header_rows, rows, roles, spans)`, the shape phase 2's
`paystub_tables.adapt` makes, built with its `PageMap` and `cell_of`:
- **Rows and totals.** Each row is `(id "<table>-row-<r>", line_id, line_ids, cells, total, label, section, title_line_id,
  title_phone, page, money_off)`. Totals are rows with `total=True`. Cell 0 is the label, then one cell per column in
  column order (blank when empty).
- **Cell content.** A usage cell's quote is its printed text, and a money cell's quote is its token text.
- **Lines.** `line_ids` are the evidence lines holding the row's words. A wrapped label lists both, label first.
- **Roles.** `roles` maps a cell index to its role.

`for_lines(bills, line_ids)` keeps what lies in one part: rows, totals, anchors, unplaced lines, other tables, guesses and
pages without tables. It works like `paystub_tables.for_lines`; a table cut by a user split gives each part its own rows
(SC-128 step 8). `pages`, `engine_pages` and `line_pages` feed the layout-notes rule (P7.1).

### P5 Holders from section titles (FR-102 b, FR-110, D22, D24)
This is decided in Record (P7.4), per engine row with a title, after the model's lines are matched to rows:
- **When a title is a holder title.** It is one when `title_phone` (rule a) holds, or else when some model line matched to
  a row of that section gives a holder `h` for which `name_supported(h, [cite of the title line])` holds (rule b). That is
  today's rule, applied to the title line alone.
- **The holder.** The title's holder is `" ".join(title.split())[:80]` (today's `line_holder` format).
- **Rows under a holder title.** Every charge row under it, whether a model line cites it or not (FR-112), takes the
  title's holder. Its evidence gains a cite of the title line. The model's holder for that row *agrees* when the last four
  digits match where both print at least four digits, else when `name_supported(h, title cite)`. A disagreeing model holder
  gives way and adds the note `Line N: the holder X differs from its section title; the title's holder Y was used.`, where
  N is the line's final position (G13) and X is the model's holder with whitespace collapsed.
- **Rows under no holder title** keep today's rule untouched: the holder is kept only when printed in the row's own lines,
  and no title is cited.

In `bill_lines` the title cite is in the row's evidence, so today's support check (`:2983–2986`) passes for the title's
holder unchanged.

### P6 Summary amounts (FR-111, FR-117, FR-118), in Record for one part
These use the part's anchors only (`for_lines`), with late lines excluded. SL-03 builds the single-value case and the
plumbing (`bill_fields`, `summary_references`), because every C-auto record scenario against STUB-UTIL-WRONG needs it.
SL-04 adds repeated values (the FR-111 note), FR-117 and FR-118 (review pass 1, M1).
- **Each kind.** For previous balance, payments and new charges: with no anchor, the model's value stands, with today's
  checks, except that on an engine-read part where FR-118 applies (no new-charges anchor, previous-balance and payments
  anchors present) the model's new charges are not used: the worked-out value is (review pass 2, INFO). With anchors of one value, that value is used. With several values, the first in reading order on the part's
  first page with that kind is used (page, then line order). The note says
  `The <kind> is printed as A and B; A, the first on page N, was used.` and names every other value (FR-111).
- **Amount due (FR-117).** Distinct values printed alike count once and get no note. With several distinct values, in
  first-printed order:
  - When previous, payments and printed new charges all exist, the first value v for which `bill_carried(prev, pay, new,
    v)` holds is used.
  - Else, when no new charges are printed or worked out, the first v for which the lines' signed sum equals v is used.
  - Else, the first value on the part's first page is used, with the note `The amount due is printed as X and Y; X, the
    first on page N, was used.` and `Guess("amount_due", …)`.

  The value chosen is then checked as today.
- **Worked out (FR-118).** This applies on an engine-read part when no new-charges anchor exists and previous-balance and
  payments anchors exist (a printed 0.00 counts). Then N = amount due − previous + |payments|, and the reading carries
  `worked_out = {amount_due, previous_balance, payments, new_charges: N}`. With FR-118 in play, FR-117's lines branch does
  not apply ("no new charges printed or worked out"), so several amounts due are settled by the guess. The generator's
  expectations follow this rule.
- **How the values reach the record.** They become header `Value`s, whose evidence cites the anchor line with the amount
  word as the quote: `amount_due`, `new_charges` and `payments_received` are in `HEADERS["bill"]`, and `previous_balance` is
  on the rent form. For a general bill, `previous_balance` (and `payments_received` when the form lacks it) goes into the
  reading's `bill_fields`, which `normalize` merges into `bill_lines`' `fields` (FR-111: kept on every non-invoice kind).
  `summary_references[name]` is the anchor word's reference, so Find lights the printed amount (FR-116, SC-116 step 2).

### P7 Record (FR-110 – FR-116, FR-120 – FR-122)
1. **Run.** In `run` (`:4105`), once `classification.document_type == "bill"` and the evidence has at least one
   `embedded_text` page with a layout, the engine runs:
   `bills = bill_tables.read(evidence)` inside `try`. On any exception, `log_failure(log, "bill table read", exc,
   run=run_id)` and `bills = BILL_FAILED` (FR-115). `run` passes it to `read` as a new keyword `bill=None`, next to
   `pay`. With `bill=None` (other kinds, and the layout-consumer test calling `read` with a fake `self`), `read` behaves
   exactly as today.
   **Which path a part takes** (review pass 1, M5):
   - **The engine path (steps 2–6).** Only a part whose `for_lines` reading has at least one engine page, a page with a
     charge table.
   - **Text pages but no charge table.** A part with text pages (`embedded_text` with a layout) but no engine page is read
     like a photographed bill. That is today's questions and checks (`amount_field` as today, no `anchor_bill`), with
     `without_printed_tables(tables)` (D6) and FR-114's page notes.
   - **No text page.** A part with no text page at all (a scanned PDF, a combined-image document, a photo) is read with
     `bill=None`, exactly as today. Only the split (P8) and FR-119 reach it. A scanned PDF is a `PDFResult` with pages, so
     this has to be said.
   - **Regression test (SL-03).** A scanned one-bill PDF (MULTI-SCAN's page 1 alone) records exactly
     `tests/test_bill_kinds.py`-style values from the model. Its line request carries no engine direction text and no
     `reported_tables` entry with `source == "bill_engine"`, and its amount is checked against its cited line as today.
   - **Layout review notes.** For bills they use `pay_layout_notes`' rule, generalized (it reads `engine_pages` and
     `line_pages` from either reading). Then a page the engine read a charge table on, whose only layout issue is
     `unresolved_columns`, raises no review note, and a part sees only its own pages' notes.
2. **Tables shown to the model.** With an engine reading, `tables = bill_tables_of(tables, part, line_ids)`, the same
   function as `pay_tables_of`. Every `pdf_text` table is dropped on every page, and the engine's adapted tables stand in.
   Vision tables of scanned pages keep only the part's rows. On `BILL_FAILED`, `without_printed_tables(tables)` applies.
   No request after `Classification` then carries a `table_grid` table (C-no-grid).
3. **Questions.** The `BillSummary` / `BillRentSummary` and `BillLines` / `RentBillLines` schemas are unchanged, and the
   stubs answer them (contract doubles table). On engine chunks (`paystub_chunks(lines, tables, split_covered=True)`, and
   `paystub_table_context`, which maps `bill_engine` to `pdf_text`), `ask` is called with `amount_field=None`, so the
   model's numbers are not checked against the print where the cells decide. The row direction gains: "The application
   copies each amount, quantity and unit price from the cited reported table cells; cite the row's first line; classify
   it." The model's amount on a line citing no engine row is still checked in Record (step 4, `amount_supported`).
4. **`anchor_bill(header, rows, part, line_text)`** (new, in `extraction.py` beside `bill_lines`) returns `(header, rows,
   cell_references, summary_references, bill_fields, engine_lines, notes, guesses)`. In order:
   - **Match (FR-112).** A model line citing a line of an engine charge row takes that row. When a second model line cites
     the same row, the first is kept and the note says
     `Two lines were read from the printed line "L"; the first was kept.` A model line citing a total, an anchor, a key
     line or a section title is left out, with the note `"L" is a printed total, not a charge; it was left out.` (for an
     anchor: "a printed summary amount"; for a title: "a printed section title"). A model line citing no engine row keeps
     its values only when `amount_supported(row.amount, row.evidence)` holds. Otherwise it is left out, with the note
     `The line "D" isn't printed with its amount in the line it cites, so it was left out.`
   - **Copy (FR-110).** For a matched row, `amount` becomes the magnitude of the charge token. `quantity` becomes the
     quantity cell's printed text, or None when the cell is blank (whatever the model said). `unit_price` becomes the rate
     cell's printed text, or None. The evidence becomes every line of the row: label lines, then the amount's line, then
     the title line if it is a holder title. `cell_references` cite the charge cell, and its quantity and rate words, as
     `native_values.reference`-shaped dicts.
   - **Money off (FR-106).** A money-off row's `line_kind` becomes `credit` (on a rent bill, `rent_type` becomes
     `credit`). The note `"D" is printed as money off, so it was recorded as a credit.` is added when the model said
     otherwise. This includes an unsigned row under a credits section (G8).
   - **Unclassified rows (FR-112).** Every engine charge row no model line took is added. Its description is the printed
     label. Its `line_kind` is `credit` if it is money off, else `other` (rent `rent_type` `credit` or `other`). It has no
     category, takes the title's holder if its title is a holder title, and its evidence is the row's lines (and title).
     It adds the note `Page N: the printed charge line "L" wasn't classified, so it was recorded as other.` (or "as a
     credit") and `Guess("unclassified_row", …)`.
   - **Holders.** P5.
   - **Summary.** P6.
   - **Order.** Lines are ordered by their first cited line's position in reading order (page, then evidence line order),
     so engine rows keep printed order and FR-114's model lines sit where they print (SC-114 step 2).
   - **Engine lines.** `engine_lines` is a list parallel to `rows`: `{"copied": bool, "rate": PrintedRate|None,
     "rate_locator", "model_holder": str|None, "title_holder": str|None}`.
5. **`normalize` / `bill_lines`** gain the keyword arguments `engine_lines=None`, `bill_fields=None` and
   `worked_out=None`. With `engine_lines=None` (photographed, scanned and invoice bills), behavior is byte-for-byte today's
   (FR-120). For a copied line:
   - `unit_price_minor` is `rate.minor`. When `rate.text` is set, `item["details"]["unit_price"] = {"text": rate.text,
     "locator": rate_locator}`.
   - The quantity check is `document_checks.unit_line(quantity, rate.text or decimal(minor), amount, currency)`: half up,
     within tolerance, on the printed rate. A failure keeps today's issue text. `money()` is not called on the rate, so no
     precision issue arises.
   - After `earlier_lines` (rent), each item with a disagreeing `model_holder` adds P5's note with N = its final 1-based
     index (G13).
   - When `worked_out` is set, `record["new_charges_minor"] = N`, `details["new_charges"] = {"minor": N, "worked_out":
     {"amount_due", "previous_balance", "payments"}, "locator": the three anchors' lines}`, and the note
     `New charges aren't printed; worked out as amount due A − previous balance P + payments R = N.` is added (plain
     decimals, no currency). The lines check is the new-charges one (G3), and the carried check is not run.
6. **Notes and guesses.**
   - The engine's notes (FR-104, FR-105, FR-106, FR-111, FR-112, FR-113, FR-114, FR-117, FR-118, P5) and FR-115's note go
     to `read`'s `record_notes` (never `notes`, so never review reasons).
   - `publish` appends them, deduplicated, to the bill's own `record["details"]["notes"]` after `bill_lines`' notes. That
     is `details_json[bill_kind]["notes"]`, the field C-note reads.
   - `details["guesses"]` is stored for bills as for pay stubs.
   - FR-113's subtotal mismatch note: `Page N: the printed subtotal "L" (V) doesn't match the lines above it, which add up
     to S.`
   - FR-104's unplaced note: `Page N: a printed line wasn't placed in any column, so it wasn't recorded: "T"`.
   - FR-114's note is used verbatim for each page in `pages_without_tables` among the part's pages.
7. **Unit price on the page (FR-110).** `Ledger.record` sets `item["display"]["unit_price_minor"]` to the item's details
   `unit_price.text` when the item has one and no `unit_price:<position>` correction is the latest of its field. Your
   correction then shows as today (SC-110 step 7). `receipt.js` is unchanged: it already shows `display.unit_price_minor`.
8. **Traces.** `document_traces.bill_checks` gains:
   - one `product:<position>` check per item with a quantity and a unit price. It runs `document_checks.unit_line` on the
     quantity text and the printed rate (`details.unit_price.text`, else the decimal of `unit_price_minor`), labelled
     "<description>: quantity × unit price". `record["cross_checks"]` counts the ones `bill_lines` checked, so SC-110
     step 5 can read both checks from the record's checks.
   - when `details.new_charges.worked_out` is set, the lines check's inputs list amount due, − previous balance and
     + payments as the working, with the formula "New charges aren't printed: amount due − previous balance + payments,
     against the lines". There is no `carried` entry.
9. **Invoices (D5, FR-120).** After the summary answer, if the part's header reads as an invoice (`invoice_marker`,
   `invoice_number` or `invoice_total` proposed), `read` throws the engine work away and reads the part again on today's
   path: `bill=None`, today's tables and `anchor_summary` / `anchor_rows`. That is one extra summary question, for
   text-PDF invoices only. No existing test runs a text-PDF invoice through `run`
   (`test_native_invoice_and_statement_copy_amount_not_unit_price_or_balance` calls `anchor_rows` directly), so that test
   and every invoice expectation stay unchanged.
10. **Engine failure (FR-115).** On `BILL_FAILED`, every part is read like a photographed bill with
    `BILL_FAILED_NOTE = "The charge lines couldn't be read from the printed columns, so the reading's amounts were used;
    check them."` The split (P8) still runs, since it reads lines. There is one `log_failure` per file.
11. `EXTRACTION_VERSION = "typed-extraction-v41-bill-engine"` (v40 is taken by `e2c2d5d`).

### P8 Several bills in one file (FR-128 – FR-135)
1. **Rule: `bill_split.bill_parts(lines) -> BillSplit`.**
   - **Key line.** It is matched on the line text with ` | ` cell separators removed: `^\s*(?P<label>KEY_LABELS)\b[\s.:#]*`
     then the value. The due-date and statement-date values are the first date token (`read_tokens`); the account value is
     the last four of the digits in the first value token that holds 4 or more digits, so masked `****9012` counts.
     `KEY_LABELS`:
     - due: `payment due date`, `due date`, `payment due`;
     - statement: `statement date`, `bill date`, `billing date`;
     - account: `account number`, `account no.`, `account #`, `account`.

     The label must start the line, so `Previous Statement Date …` and `Rent and Leasing Charges Due …` are no keys, and
     neither is a sentence (SC-126 step 7). A billing or service period is never a key.
   - **Walk.** Pages are walked in order, and page 1 opens bill 1. For each later page, if any key line on it prints a
     value that differs from the open bill's value for that key, a new bill starts at the page's first line. Otherwise the
     page continues the open bill, and its new keys join the open bill's values.
   - **Two values on one page (a).** A page whose key lines print two different values for one key is never split. Its
     first value is the one compared, and the bill holding it gets reason (a).
   - **No amount due of its own (b).** Each part must hold an amount-due anchor line (`charge_tables.anchor_kind`, never
     a late line). `anchor_kind` strips ` | ` cell separators itself, so a scanned transcription's `Total Amount Due |
     81.42` counts (review pass 1, m4). A part without one joins the part before it (the first joins the next), and the joined bill gets
     reason (b).
   - **New charges on different pages (c).** One part whose new-charges anchors print different values on different
     pages, where no key line differs between those pages, gets reason (c).
   - **One part.** A single part returns `BillSplit([(0, len(lines))], reasons)` and is read exactly as without the rule.
2. **Run.** `classification.document_type == "bill"` gives `parts, changed = self.bill_parts(run, parse, lines,
   split_notes, record_notes)`, built like `pay_parts`. The user's saved split wins (`saved_segments(source="user")`,
   `user_ranges`), and then FR-129's reasons are not raised. Otherwise the rule runs. If it raises, or finds more than 200
   parts, the file is one part with reason (d), `BILL_SPLIT_FAILED` as an issue, and `log_failure(log, "bill split", exc,
   run=…)` (no text). The per-part classification loop runs for bills (noun "bill"). A part of another type gives the note
   "A part of this file is not a bill, so the file was read as one document." (C-segments(1)). A part read as an invoice
   (P7.9) means the whole file is read again as one document on today's path, with the note "A part of this file is an
   invoice, so the file was read as one document." (FR-130, D16).
3. **Notes per part.**
   - FR-129's reasons go into the part's `notes` (review reasons) unless the split is the user's or confirmed
     (`split_confirmed`).
   - `BILL_SPLIT_NOTE = "Split from a file holding several bills"` goes into the part's `record_notes` for every split part.
     It is a note, not a reason (FR-131), and it replaces `SPLIT_NOTE` for bills in `record`.
   - When `changed`: `BILL_SPLIT_CHANGED = "You changed where the bills in this file start; the file was read with your
     split."` and `Guess("split_changed")` (the phase 2 `set_split` mechanism, unchanged).
4. **Reason texts** (FR-129, exact):
   - (a) `Page N prints more than one due date (A, B), so it may hold more than one bill; check it and split it on the
     document's page.`
   - (b) `Page N prints its own due date (A) but no amount due, so it was read with the bill before it; check how the file
     was split.`
   - (c) `This bill prints new charges of A and B on different pages, so the file may hold more than one bill; check it
     and split it on the document's page.`
   - (d) `Where each bill starts couldn't be read, so the file was read as one; check whether it holds more than one
     bill.`

   Dates are as printed, and amounts are plain decimals. G5 says which key (a) and (b) name.
5. **Split API and actions.**
   - `split()` also selects `r.document_kind`, `r.due_date` and `r.amount_due_minor`. A bill row gets `kind: "bill"`,
     `merchant` (the provider), `due_date` and `display.amount_due`.
   - For a file read as one bill whose segment-0 row holds an FR-129 (a), (c) or (d) reason, `split()` returns
     `{"segments": [{ordinal 0, first_line_id, last_line_id, kind "bill", …}], "confirmed": false, "one": true}`.
     `run` sets `publication["segments"] = [{"ordinal": 0, "first_line": …, "last_line": …, **outcome[1], "one": True}]`
     and `publication["split_confirmed"] = False`. That is the same shape as a split file's segments: it carries the
     record's `record_type`, `id` and `status`, which `manager.extract_and_file` and `doc2Split` read (review pass 1, m6).
     It lets the panel offer Split here (FR-131). No `document_segments` row is written for it.
   - `confirm_split` also removes FR-129's reasons (matched by their fixed prefixes) and `BILL_SPLIT_NOTE` (from
     `details_json[kind]["notes"]`) from each bill row. It then re-judges each one by its remaining issues, as receipts.
   - `set_split` is unchanged.
   - `retire_segments` words its note by `document_kind`: "… no longer finds this bill; …" for bill rows (FR-132).
6. **VOID and duplicates (FR-133, FR-134).**
   - **VOID.** A part with a line where `VOID_LINE.fullmatch` holds gets the record note `This bill is printed VOID, so it
     doesn't count.`, then `Ledger.mark_bill_void(receipt_id)`.
   - **Duplicate.** For a non-invoice bill, `Ledger.bill_twin(record, source)` looks for a non-rejected bill (`receipts
     document_kind='bill'`, `invoice_json IS NULL`) with a lower id, the same merchant, the same `due_date` (else
     `issue_date`), the same `amount_due_minor` and the same currency. When both bills print an `account_last_four`, it must
     be equal. This is the pay stub rule's shape.
     - An original gives the note `This bill repeats the one from P due D (A), so it doesn't count.` (D as ISO, A as a plain
       decimal) and `Ledger.mark_bill_duplicate(receipt_id, original_id)`.
     - Same provider, account and due date with another amount due gives `Another bill from P has the same due date.`
   - **Rejecting.** Both marks call `reject_receipt_automatically(receipt_id, original_id=None)`, which mirrors
     `reject_automatically`. It sets `review_status='rejected'` and `review_source='automatic'` unless the user decided the
     bill, then runs `refresh_splits`. Extract again lets a duplicate count once its original is rejected (SC-131 step 2).
     Invoices are never twins.
7. **Library (FR-135).** `library/storage.py:583–586` gain `ORDER BY r.segment` before `LIMIT 1`. Amount (count=1),
   date (`min(purchase_date)` over non-rejected rows) and merchant (`ORDER BY r.segment`) already hold. Filing uses segment
   0's result, as today (`run` keeps `outcomes[0]`).

### P9 Line corrections after a reading again (FR-119)
**Remembered amounts, no migration.** Each bill's `receipts.details_json` gains one reserved top-level key beside its
kind entries: `"line_corrections": {"amounts": {"<correction id>": minor}, "held": ["<correction id>", …], "undone": ["<correction id>", …]}`.
- `merged_details` already keeps every top-level key except the kind a reading replaces, and `current_details` /
  `record()` read only `details_json[kind]`, so the key is invisible elsewhere.
- `record_corrections` rows keep exactly today's shape and values (SC-119 step 1, 4).
- A bill read before bill kinds has `bill_kind` NULL. On its next reading `merged_details` still keeps the key, because
  every new reading has a kind (general for invoices).

**When a correction is made** (`correct_line`, `_correct_item`, `_correct_item_field`, and the undo rows they write), on
a `document_kind='bill'` row:
- Its remembered amount is the line's amount as read before any price correction of yours. That is the remembered amount
  of the position's latest `price:<n>` correction when that one is applied (not held), else the row's current
  `line_total_minor`.
- The remembered amount is written under the new correction's id.
- Any held reason and held id of the same `<field>:<position>` are removed: making the same kind of change again replaces
  it (SC-119 step 6).

**When a bill is published again** (`publish_receipt`, `written`, bills only), `apply_corrections` gets these steps:
1. Before `_replace_items`, snapshot the stored `{position: line_total_minor}`.
2. After it, snapshot the new as-read amounts.
3. For each latest `receipt_item` correction, find its remembered amount `Y`:
   - from `amounts`;
   - else (a correction made before this change), for a `price:<n>`, the `previous` of the start of the position's latest
     unbroken price chain (G4);
   - else for any other field, the same price-chain start when the position has a price correction (G4), else the
     pre-replace snapshot at that position.

   A `Y` found this way is persisted, so later readings agree (FR-122).
4. Let `X` be the new as-read amount at the position. The correction is applied when `X == Y`, or, for a price
   correction, when `X` equals your corrected price. Otherwise it is **held**: it is not applied, its id is added to
   `held`, and this reason goes into `validation_json`, with `review_status='needs_review'` and `review_source=NULL`:
   `Your change to line N (L) wasn't applied: that line now prints X, not Y. Check the bill's lines and make the change
   again on the right line.` L is the history label's word and the value: `person: blair`, `type: subscription`,
   `price: 8.51`, `name: …`, `code: …`, `quantity: …`, `unit price: …`. X and Y are plain decimals.
5. A correction applied again leaves `held` and its reason goes.

**Undoing a held correction** (review pass 1, M4). `undo_corrections` on a `receipt_item` row whose id is in `held`
writes its undo row as today (field, value = previous, previous = value, reason "Undid a change"). It then adds that undo
row's id to `line_corrections["undone"]`, and removes the held id and its reason. It **does not touch `receipt_items`**:
nothing was applied, so nothing is put back, and the line now at that position keeps its own values. `apply_corrections`
skips any latest correction whose id is in `undone`, on this and every later reading, so the field stays uncorrected
until you correct it again. One SL-05 test: SC-119 Journey A, then undo the held `price:3`. Basic Plan stays 3500, the
reason is gone, History lists the undo, and Extract again changes nothing.

What `_replace_items` keeps by description and line total (id, your category, your member) is unchanged, so Basic Plan
keeps member Blair by identity (SC-119 A step 2). A decided bill is never written (`_upsert`), so nothing is held on it.
Receipts (`document_kind='receipt'`) skip all of this (SC-119 "Receipts unchanged").

### P10 The document page (FR-131, FR-110)
Before changing these pages the implementer loads the `ui-ux-pro-max` skill (CLAUDE.md). They follow docs/ui.md "Screen
rules" and `design-system/home-manager/MASTER.md`. No new dependency, no inline style, CSP unchanged, no money arithmetic
in the page. In `doc2Split`:
- **Wording.** When every segment is `kind === "bill"`, the noun is "bill". The heading is `This file holds N bills`
  (`This file may hold more than one bill` when `split.one`). Chips show `merchant` · due date · `display.amount_due`.
  There is no "waits in To check" warning, and the aria-label is "Bills in this file".
- **Actions.** Confirm split is hidden when `split.one`, and so is Merge with next (there is one segment). Split here is
  offered from the bill's own lines, as today.
- **Notes.** Bill notes already show under the fields (`:589`).

The Unit price text comes from the server (P7.7). `receipt.js` is unchanged.

### P11 The `bill` diagnose mode (FR-127)
`scripts/statement_diagnose.py <pdf> bill` calls `bill_section(result)` inside the existing temporary folder and exits
0. It needs no model. It prints:
- per page: the charge tables, and per column its left and right edges and zone as percentages of the page width, its
  kind, role and `decided_by`;
- per page: counts of rows, totals, section titles (holder titles counted apart), wrapped labels, anchors by kind, late
  lines, other tables and unplaced lines;
- the guesses by kind;
- `N bills: pages 1, 2, 3` (`1 bill` for one), and per page the key kinds present with `equal` / `differs` against the
  open bill, never a value;
- which FR-129 reasons fired, by letter.

It never prints labels, heading words, providers, amounts, dates or digits of an account. The module docstring says so.

### P12 Evals (FR-124) and the generator (FR-123)
- **Generator.** `evals/bill_layouts.py` (new) has `make(seed, index, **choices) -> Layout(pages, bills: [answers per
  bill], choices)`. It draws every FR-123 variation and SC-123's rate kinds and holder forms, and its answers come from its
  inputs only. Besides FR-123's list it prints a charge `Late Fee` with no condition (a row) beside a conditional late line
  (no row), and amount-due labels with `by <date>` / `on or before <date>` (review pass 1, M2, m3), a dateless late condition (`if
  paid late`) and a stub line `Payment Due <date> <amount>` (review pass 2, m3, m4). Its printed charges
  are the product rounded half up. Its amounts due, new charges and worked-out values
  follow P6's rules, so expected values never come from the engine. `tests/bill_engine_generator.py` builds the PDFs with
  `make_pdf` and the stubs from the answers.
- **Synthetic corpus.** Five fixed layouts are appended after the 53 documents, drawn with `BILL_SEED = SEED + 3`,
  source `pdf`, tag `aligned`: utility, phone, rent, two-page headless with a stub page, and BL-MULTI as three bills. The
  multi-bill case carries `stubs.json` with three bills' answers, the existing `Case.stubs()` mechanism, so no new loader.
- **Pipeline.** A split bill result is graded per segment by `grade_stubs`, which already handles any list record.
- **Bill readers.** `bill_readers(case, bills, evidence)` is model-free, like `pay_readers`, and returns `{"engine":
  bill_reader(...)}`:
  - `documents`, `lines`, `exact`, `left_out`;
  - `checkable`, `checks_held` (bills whose engine values pass the lines and carried checks);
  - `to_review` (the pipeline records' `review_status`);
  - `unplaced`, `failed`;
  - `files_split`, `split_right` (`split_is_right` against `bill_parts`), `split_review` (FR-129 reasons raised);
  - shares.

  It runs only for `native_pdf` bills, so image bills are not counted.
- **Guesses.** `guess_counts` takes the bill kinds of P2. `report.py` gains `bill_readers` and the new keys in the
  allowlist.
- **Tests and README.** `tests/test_evals.py`'s four 53-count tests move to 58, and a `BEFORE_BILLS` hash pins the first
  53. `evals/README.md` says 58.

### Decisions taken in this plan (contract gaps; none changes an expected value of the contract)
- **G3: the worked-out lines reason's prefix.** The prefix is `New charges: the lines add up to …, but the bill's new
  charges are …`. FR-118 compares the lines with the (worked-out) new charges, and that is what counts. It contains
  SC-118's facts.
- **G4: a correction made before this change, on a line that also has a price correction.** It is compared with the
  line's amount as read before your price correction: the `previous` of the start of the position's latest unbroken
  `price:<n>` chain. A chain is broken where a row's `previous` differs from the prior row's `value`. This is FR-119's own
  "its amount as read, before any price correction of yours", and the stored amount in that case is the corrected price,
  which is not what was printed. The contract's variants don't reach it. The plan adds one unit test in
  `tests/test_bill_corrections.py`.
- **G5: which key reasons (a) and (b) name.** The first key that differs, in the order due date, statement date,
  account. (a) is worded "more than one due date", "more than one statement date" or "more than one account (ending A,
  ending B)", and so is (b)'s "its own …". There is one reason per page. BL-TWOONPAGE names the due dates (SC-127 step 2).
- **G6.** As the contract says: BL-NOKEY has no due-date line anywhere, and the bill gets reason (c) and the lines reason.
- **G7: anchor words inside a sentence.** An anchor's whole label must be an anchor phrase (P3.2). A label-and-amount line
  whose label only contains one (`Your previous balance was paid in full 82.10`) is no anchor and no charge row: it is an
  unplaced line, with a note and no review reason. A sentence can't set a summary amount, and nothing is dropped silently
  (FR-104). One added engine test.
- **G8: an unsigned row under a credits section that the model called a charge.** It gets FR-106's money-off note, worded
  as for a signed row. It is a note, not a review reason. SC-106 (3) doesn't assert it, so no expected value moves.
- **G13: what N counts in "Line N".** N is the line's final position on the bill, `receipt_items.position` (1-based). That
  is the number the page shows and the number FR-119's "line N" uses. It is computed in `bill_lines` after earlier-month
  lines are left out (P7.5).
- **G14: year ranges and account numbers in a section title.** They are **not** phone numbers. `PHONE` (i) requires the
  4-digit last group directly after a group of exactly 3 digits, optionally after a 3-digit area code, with no digit group
  directly before or after (P3, regex as checked in review pass 1).
  - `Charges 2025-2026`, `2025 - 2026`, `Account 1234-5678-9012` and BL-PHONE's `555-0100-7788` don't match.
  - Every phone form FR-102 (a) and SC-102 step 9 list does match.
  - The plan reads "a phone number" through the spec's own examples and its exclusion of a year; see "Human decisions"
    H1, since it is narrower than the literal wording.
  - One added engine test asserts `Charges 2025-2026` and `Account 1234-5678-9012` titles are no holder titles.
  - A **masked** number in a title (`Account ****9012`) does match (ii), as FR-102 (a) says masked prints count. Such a
    title's rows take it as their holder; routing gives a member only if a listed phone ends in those four digits, else the
    line has no member, as today for an unknown holder. The added test records this (`Account ****9012` is a holder title)
    so the behavior is deliberate, not accidental.
- **Version.** FR-121 says the version changes "from `typed-extraction-v39-receipt-printed-signs`", which was HEAD when
  the spec was written; `e2c2d5d` has since set v40. The plan sets `typed-extraction-v41-bill-engine`. SC-121 step 1
  (`!= v39`) holds, and the contract's previous-version double (the version patched to v39 while recording) still stands
  for an older reading: any version other than v41 is not reused, so v39 and v40 readings behave alike. No expected value
  changes, and the spec needs no amendment for this.
- G9 – G12 stand as the contract states them. G9: a merged bill is read like any part, and its own checks decide it.
- No new dependency.

## Error handling, idempotency and recovery
- **Engine exception.** FR-115's note, with every part read like a photographed bill, logged by exception class and run
  id only. **Split-rule exception or more than 200 parts:** FR-129 (d). **Roles undecided:** the right-most column, with a
  guess note. **Amount due undecided:** a guess note.
- **Pure.** The engine, the roles and the split rule make no model or network call. Deterministic and pure, Extract again
  on an unchanged reading gives identical rows, notes, guesses, evidence, segments and held corrections (FR-122). The
  remembered amounts are persisted the first time they are worked out, so a second reading compares with the same values.
- **Failed runs.** A failed run publishes nothing: `run` publishes only after every part is read. The contract's retry
  variant then gives the full set with no duplicate segment. The restart variant uses the existing `recover`.
- **Decided records.** A record you decided is never rewritten (`_upsert`). A bill a later reading no longer finds is
  retired with the bill-worded note. A rejected-automatically bill found again is restored by the existing logic.
- **No migration.** There is nothing to roll back. The only new stored data are the reserved `line_corrections` key in
  `receipts.details_json` and the line `details.unit_price` text in `receipt_items.details_json`. Both are JSON in existing
  columns, and the old code ignores both.

## Privacy/security and migration impact
- No model or network call is added by the engine, the roles or the split rule. Every new test module imports the
  `no_network` autouse fixture (C-net).
- Money is in integer minor units via `core/money.to_minor`, or `printed_rate`'s half-up cents. It stays `Decimal` until
  then.
- Identifiers stay masked to their last four. A holder title is stored only as today's `line_holder` (80 characters, as
  printed). Notes and the diagnose output never print a full account number. FR-129 names an account by `ending NNNN`.
- `summary.json` stays counts. The diagnose `bill` mode prints shapes and counts only.
- No migration. `SC-121` step 3 asserts the `library/migrations/` listing equals START_HEAD's (the contract's "unchanged at
  HEAD's last migration"); it names no file, since in-flight work may add `078` before implementation starts. SL-04 writes START_HEAD's listing
  into the test as a literal tuple, read from START_HEAD (`git ls-tree --name-only START_HEAD
  src/home_manager/library/migrations/`) when the slice is implemented; the test compares the directory with that literal
  and runs no `git` (review pass 3, m1).
- Synthetic fixtures only. P:\Finances, %LOCALAPPDATA%\HomeManager and P:\EvalCorpus are never read; the user runs the
  probe and the corpus eval.

## Vertical slices
Every slice's verification is targeted. The full suite runs once, in "Final verification".

| ID | FR/SC covered | Dependencies | Files/changes | Verification command / evidence |
|---|---|---|---|---|
| SL-01 | FR-100 – FR-104 engine side, FR-102 (a) phone titles (with G14), FR-103 word list, G7; SC-100 steps 1–3, SC-101 engine, SC-102 steps 1 and 9 (phone rows), SC-103 steps 1, 2, 4, SC-104 step 1, SC-114 step 1 | none (committed base, no tracked change) | `documents/charge_tables.py` (P3); `tests/bill_engine_fixtures.py` (every contract fixture, stub and hand-written EXP value; Helvetica widths for "r R"); `tests/test_bill_engine.py` (P-checks and engine steps, plus G7 and G14 tests) | `.venv/bin/python -m pytest tests/test_bill_engine.py -q`; `.venv/bin/python -m pytest tests/test_paystub_engine.py tests/test_table_engine.py -q` (unchanged) |
| SL-02 | FR-105, FR-106, the rate rule (FR-110 D21/D25 unit), guesses (FR-124 kinds), the adapter and `for_lines`; SC-105 engine steps incl. step 4's tie, SC-106 step 4, SC-110 step 6's unit list | SL-01 | `finance/bill_tables.py` (P4); `tests/test_bill_engine.py` (roles, money off, rate unit, adapter shape: ids, line ids, wrapped label lines, title line ids) | `.venv/bin/python -m pytest tests/test_bill_engine.py -q` |
| SL-03 | FR-110 (copying, blank cells, rates, holders P5), FR-111 (single printed values, `bill_fields` for a general bill, summary cites), FR-112, FR-113, FR-114, FR-115 (one bill), FR-116, FR-106 record side, FR-121 (version), FR-122 (one bill), FR-120/FR-125 (incl. the scanned one-bill regression of P7.1); SC-100 step 4, SC-101, SC-102 steps 2–9, SC-103 step 3, SC-104 step 2, SC-105, SC-106, SC-110 steps 1–6, SC-111 steps 1–2, SC-112, SC-113, SC-114, SC-115 (a), SC-116, SC-122 (UTIL-STRAY) | SL-02 | `documents/extraction.py` (P7.1–P7.7, P7.9–P7.11: `bill=` in `run`/`read`, the three part paths, `bill_tables_of`, layout notes, `anchor_bill` with P6's single-value anchors, `bill_lines`/`normalize` keywords, bill engine notes into details, guesses stored, invoice re-read, `BILL_FAILED`, version); `finance/ledger.py` (`record` unit-price display); `finance/document_traces.py` (`product:<n>` checks); `tests/test_bill_engine_record.py` | `.venv/bin/python -m pytest tests/test_bill_engine_record.py -k "(sc100 or sc101 or sc102 or sc103 or sc104 or sc105 or sc106 or sc110 or sc111 or sc112 or sc113 or sc114 or sc115 or sc116 or sc122 or scanned) and not sl04" -q` (SC-111 step 4 and SC-122's R1 (c) case are marked `sl04` in their names and deselected here); `.venv/bin/python -m pytest tests/test_bill_kinds.py tests/test_bills_ledger.py tests/test_layout_consumers.py tests/test_extraction.py tests/test_provenance.py tests/test_paystub_engine_record.py tests/test_family_routing.py tests/test_receipt_kinds.py tests/test_invoice_ingestion.py tests/test_paystub_split.py tests/test_paystub_cleanup.py -q` (unchanged; the last two because `pay_layout_notes` and `paystub_table_context` are generalized) |
| SL-04 | FR-111 (repeated values and their note), FR-117, FR-118, FR-124 (`amount_due` guess); SC-111 step 4, SC-117, SC-118, SC-122 (R1 c), SC-121 steps 1–3 for (1) and (2) (step 3: the `library/migrations/` listing equals START_HEAD's) | SL-03 | `documents/extraction.py` (P6's repeats, FR-117 and FR-118 in `anchor_bill`; `worked_out` through `normalize`/`bill_lines`); `finance/document_traces.py` (worked-out working, no carried check); `tests/test_bill_engine_record.py` | `.venv/bin/python -m pytest tests/test_bill_engine_record.py -q`; `.venv/bin/python -m pytest tests/test_bill_kinds.py tests/test_bills_ledger.py tests/test_recurring_bills.py tests/test_provenance.py -q` |
| SL-05 | FR-119 (D13, D15), FR-121/FR-122 for corrections; SC-119 Journeys A – C and its variants, plus the G4 unit test | SL-03 | `finance/ledger.py` (P9: `line_corrections` in `receipts.details_json`, remembered amounts at correction time, the guard in `apply_corrections`/`publish_receipt`, held reasons, same-field replacement); `tests/test_bill_corrections.py` | `.venv/bin/python -m pytest tests/test_bill_corrections.py -q`; `.venv/bin/python -m pytest tests/test_bill_kinds.py tests/test_bills_ledger.py tests/test_receipt_item_table.py tests/test_receipt_kinds.py tests/test_receipt_segments.py tests/test_planned_bugfixes.py tests/test_family_ledger.py -q` (receipts and their corrections unchanged) |
| SL-06 | FR-128 – FR-132, FR-130 invoice and other-kind fallbacks, FR-135, FR-115 (split file), FR-121 (one bill becomes three), FR-122 (split); SC-115 (b), SC-121 step 2 (3), SC-122 (BL-MULTI), SC-126, SC-127, SC-128, SC-129 API steps 1, 3–6, SC-130, the contract's retry, duplicate-capture, restart and concurrent variants | SL-04 | `documents/bill_split.py` (P8.1); `documents/extraction.py` (P8.2–P8.5: `bill_parts`, notes, reasons, `split()`/`confirm_split` for bills, the one-bill offer); `finance/ledger.py` (`retire_segments` wording); `library/storage.py` (P8.7); `tests/test_bill_split.py` (with SC-115 (b), SC-121 (3) and SC-122's BL-MULTI case) | `.venv/bin/python -m pytest tests/test_bill_split.py -k "not sc131" -q`; `.venv/bin/python -m pytest tests/test_paystub_split.py tests/test_receipt_segments.py tests/test_library.py tests/test_managed_library.py tests/test_extraction.py -q` |
| SL-07 | FR-133, FR-134; SC-131 | SL-06 | `documents/extraction.py` (VOID and twin in `publish` for bills); `finance/ledger.py` (`bill_twin`, `mark_bill_void`, `mark_bill_duplicate`, `reject_receipt_automatically`); `tests/test_bill_split.py` (`sc131`) | `.venv/bin/python -m pytest tests/test_bill_split.py -k sc131 -q`; `.venv/bin/python -m pytest tests/test_paystub_split.py tests/test_bills_ledger.py tests/test_bill_kinds.py tests/test_recurring_bills.py tests/test_invoice_ingestion.py tests/test_reconcile_tools.py -q` (VOID and twins run on every bill publish, photographed included; review pass 1, m5) |
| SL-08 | FR-131 (page), FR-110 (page), FR-111 (page); SC-129 step 2 and 6 (browser), SC-110 step 7, SC-111 step 3 | SL-07 | `app/static/document_v2.js` (P10); `tests/test_bill_engine_browser.py`; `docs/ui.md` (split panel for bills) | `RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_bill_engine_browser.py tests/test_document_v2_browser.py -q`; `.venv/bin/python -m pytest tests/test_bill_engine_record.py -k sc110 -q` |
| SL-09 | FR-123, FR-127; SC-123, SC-125 | SL-07 | `evals/bill_layouts.py`; `tests/bill_engine_generator.py`; `tests/test_bill_engine_generator.py` (≥ 100 files through the real reader and Record with stubs from inputs; each variation, rate kind and holder form at least once, asserted from the cases' choices; misses print seed, index and choices; byte-identical PDFs on regeneration; `-k diagnose` runs the probe as a subprocess with `-I`); `scripts/statement_diagnose.py` (P11) | `.venv/bin/python -m pytest tests/test_bill_engine_generator.py -q` |
| SL-10 | FR-124, FR-126; SC-124 | SL-09 | `evals/synthetic.py`, `evals/run.py`, `evals/graders.py`, `evals/report.py` (P12); `evals/README.md`; `tests/test_evals.py` (53 → 58 in the four named tests only, `BEFORE_BILLS` pin, `-k bill` tests); docs: `docs/documents.md` ("Bill lines from the printed columns", "Several bills in one file", the anchor and key word lists), `docs/money.md` ("Bills and their lines", "Reading a statement or receipt again"), `docs/evals.md` ("The two table readers"), `docs/open-work.md` (FR-41 built; D5, D12, D16, D18, D19, D20, consolidated bills, donating split bills, real-bill accuracy unmeasured, G14's narrowing and the 80-character holder limit if H1/H2 stand) | `.venv/bin/python -m pytest tests/test_evals.py -q`; `.venv/bin/python -m evals.synthetic "$(mktemp -d)"` writes 58 cases |

## Final verification
After SL-10, once, on the final tree:
```
.venv/bin/python -m pytest -q
RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_bill_engine_browser.py tests/test_paystub_engine_browser.py \
  tests/test_table_engine_browser.py tests/test_document_v2_browser.py -q
```
Before SL-01, the implement orchestrator runs the same two commands on the committed base (no tracked change) and records the failing
test ids in `progress.yaml` (`baseline_failures`). Those are the only accepted failures. Any other failure outside the
contract's "Tests this change edits" list (SC-120) is a defect to fix, not an expected value to edit.

## Requirements & scenarios coverage matrix
| Requirement | Slice | Scenarios |
|---|---|---|
| FR-100 | SL-01, SL-03 | SC-100 |
| FR-101 | SL-01, SL-03 | SC-101 |
| FR-102 | SL-01 (titles, phone form), SL-03 (holders, name titles) | SC-102, SC-123 |
| FR-103 | SL-01, SL-03 | SC-103 |
| FR-104 | SL-01, SL-03 | SC-104 |
| FR-105 | SL-02, SL-03 | SC-105 |
| FR-106 | SL-02, SL-03 | SC-106 |
| FR-110 | SL-02 (rate rule), SL-03, SL-08 (page) | SC-110, SC-102, SC-112, SC-119 A, SC-123 |
| FR-111 | SL-03 (single values), SL-04 (repeats), SL-08 (page) | SC-111 |
| FR-112 | SL-03 | SC-112 |
| FR-113 | SL-03, SL-04 | SC-113, SC-110 step 5 |
| FR-114 | SL-03 | SC-114 |
| FR-115 | SL-03 (a), SL-06 (b, in `tests/test_bill_split.py`) | SC-115 |
| FR-116 | SL-03 | SC-116 |
| FR-117 | SL-04 | SC-117 |
| FR-118 | SL-04 | SC-118 |
| FR-119 | SL-05 | SC-119 |
| FR-120, FR-125 | every slice's regression files; final | SC-120 |
| FR-121 | SL-03 (version), SL-04 (SC-121 1–3 for (1), (2)), SL-05, SL-06 (SC-121 (3)) | SC-121, SC-119 |
| FR-122 | SL-03, SL-04, SL-05, SL-06 (SC-122 BL-MULTI) | SC-122, SC-119 step 5, SC-130 |
| FR-123 | SL-09 | SC-123 |
| FR-124 | SL-02 (kinds), SL-04, SL-06 (`split_changed`), SL-10 | SC-124, SC-105, SC-117, SC-129 |
| FR-126 | SL-10 (SL-08 for docs/ui.md) | doc diff; SC-103 step 4 (documented list) |
| FR-127 | SL-09 | SC-125 |
| FR-128 | SL-06 | SC-126 |
| FR-129 | SL-06 | SC-127 |
| FR-130 | SL-06 | SC-128 |
| FR-131 | SL-06 (API), SL-08 (page) | SC-129 |
| FR-132 | SL-06 | SC-130 |
| FR-133, FR-134 | SL-07 | SC-131 |
| FR-135 | SL-06 | SC-128 |

## Test environments, data, stubs for nondeterministic components, final-state oracle
- **Isolation.** `tmp_path` libraries only. Every new module imports `no_network` (autouse) from
  `tests/test_paystub_engine_record.py`. P:\Finances, %LOCALAPPDATA%\HomeManager and P:\EvalCorpus are never read.
- **Levels.**
  - Engine and role tests (`tests/test_bill_engine.py`) are integration tests on real readings of synthetic PDFs, with no
    store or model. Each is independent.
  - Record tests go through `ReceiptService` and `ExtractionService.enqueue` + `run` with
    `ReasoningConfig(base_url=local_model…, model="synthetic-reasoning")` and `HouseholdConfig(home_currency="USD")`, as
    the contract's conventions say. They reuse `pdf_store`, `started` and `Run`.
  - SC-119 A, SC-129 and SC-130 are single tests with ordered checkpoints.
  - API steps use `create_app` and `TestClient`. Browser tests are opt-in (`RUN_BROWSER_TESTS=1`, `served()`).
- **Where the split-dependent record cases live (review pass 2, m1).** The contract puts SC-110 – SC-118, SC-121 and
  SC-122 in `tests/test_bill_engine_record.py` and lets the plan move them. Three cases need SL-06's split, so they live
  in `tests/test_bill_split.py` and run in SL-06: SC-115 (b) (`test_sc115_b_…`), SC-121 (3) (`test_sc121_3_…`) and SC-122's
  BL-MULTI case (`test_sc122_multi_…`). Everything else of SC-110 – SC-122 stays in `tests/test_bill_engine_record.py`, so
  SL-03's and SL-04's commands never select a test that needs the split. The coverage matrix and the contract's
  traceability move with them (FR-115, FR-121, FR-122: also `tests/test_bill_split.py`).
- **Stubs.** `local_model` by schema, as in the contract's doubles table (one answer per part for split files). The
  engine fault is a `monkeypatch` of `finance.bill_tables.read`. The split fault is a `monkeypatch` of
  `documents.bill_split.bill_parts`, raising `RuntimeError("injected split fault")` or returning 201 parts. The previous
  version is a `monkeypatch` of `EXTRACTION_VERSION` to v39, with v39 DB state seeded by SQL (SC-119, SC-121). SC-114
  step 3's "without layout" reading is built by saving the reading's pages with `layout=None` (the same `PDFResult` with
  each page's layout cleared before `ExtractionService.run`).
- **Oracle.** Expected values are the contract's hand-written literals in `tests/bill_engine_fixtures.py` and the
  generator's inputs, never the code under test. Final state is read back through:
  - `Ledger.record("receipt", id)` and `run["publication"]["segments"]`;
  - `GET /api/records/receipt/{id}`, `GET /api/documents/{id}`, `GET /api/documents/{id}/segments`;
  - `provenance_for`, `FinanceTools` spending, `Reconciler(store).run()`;
  - SQL snapshots of `receipts`, `receipt_items`, `record_corrections`, `financial_evidence_links` and
    `document_segments`.

  Shared checks C-money, C-docs, C-lines, C-rate, C-note (`details_json[bill_kind]["notes"]`), C-reason, C-auto,
  C-no-feature-review, C-no-grid, C-model-calls, C-segments and C-ledger are helpers in `tests/bill_engine_fixtures.py`.
  SC-113 step 3's "no anchoring note on any engine page" helper runs in every record test.

## Risks, unresolved decisions, alternatives
- **R-A: real bills unlike the fixtures (U2, U3).** The `bill` probe (FR-127) and the corpus eval (FR-124) are how the
  user measures them. Accuracy on real bills stays unmeasured until they run them (open-work).
- **R-A2: keys printed side by side** (`Account Number … Due Date …` on one visual line). Only the key that starts the
  line counts (FR-128: "a line whose text starts with a key label"), so the second key is not compared. The `bill` probe
  reports which keys each page prints (U3). Widening the rule would be a spec change, recorded in open-work if the probe
  shows it matters.
- **R-B: a sentence or footer with an amount becoming a charge row.** It is bounded by FR-104's accounting and the anchor
  rule (G7), and by columns needing two rows or a heading. The generator prints sentences with key and anchor words.
- **R-C: line-id mapping.** Engine rows must map to the ids the model saw (`PageMap`, as phase 2). A miss leaves rows
  unclassified, so they are guessed with a note, not lost. SC-102 and SC-112 assert classes and evidence.
- **R-D: the reserved `line_corrections` key in `receipts.details_json`.** It is a new top-level key in an existing
  JSON column. The risk is code that iterates every key as a kind. The verified readers (`merged_details`,
  `current_details`, `record`, `document_traces.current`, `apply_details`, `_undo_kind`) key by kind. SL-05 greps every
  `details_json` reader of `receipts` at its base and names any that iterates. The alternative, a new table, needs a
  migration, which SC-121 step 3 forbids.
- **R-E: the extra summary question for text-PDF invoices** (P7.9). It is accepted: invoices are few, and today's path is
  then byte-for-byte today's.
- **R-F: a bill file you decided as one bill before this change** that the rule now splits. `_upsert` keeps your
  decided segment 0 (holding every bill's lines) and adds the other bills as new records, so their charges count twice.
  FR-121 covers only an undecided file. See H3.
- **R-G: the 80-character holder cut** (FR-102, today's `line_holder` format). A title longer than 80 characters loses
  any phone number printed after character 80, and routing then finds no member. If the cut falls inside the number, the
  remaining digits' last four could match another member's line, which would route the line to the wrong person. Titles
  that long are rare: FR-102's examples are under 25 characters. See H2.
- **Alternative rejected: extending `pay_tables.read` with a bill mode.** It would put pay stub row finding at risk
  (FR-120). The new module imports the pay engine's helpers instead.
- **Alternative rejected: a new line-classification schema for engine rows** (phase 2's `PayRowClasses`). The existing
  `BillLines` / `RentBillLines` already carry description, kind, holder and evidence, and the stubs answer them. Copying
  ignores the model's numbers, and FR-112's non-row lines still need them.
- **Alternative considered: a separate feature for M4 (the split).** It was not taken. The bundle is approved as one, and
  M4 is three slices with their own checks.

### Human decisions needed before plan approval
- **H1 (G14): confirm that year ranges and account numbers are not phone numbers.** The plan's `PHONE` (i) needs a
  3-digit group before the last four. That matches every form FR-102 (a) and SC-102 lists, and excludes `Charges
  2025-2026` and `Account 1234-5678-9012`. It is narrower than FR-102 (a)'s literal "groups ending in four, at least 7
  digits": an international number grouped as `20 7946 0958` would not count either. I recommend confirming. If you read
  FR-102 (a) literally instead, year ranges and account numbers become holder titles, and the spec needs an amendment to
  exclude them.
- **H2: the 80-character cut can drop or cut the phone number (R-G).** FR-102 fixes the holder as "cut to 80 characters",
  so the plan implements that. A safer rule would be to keep the phone number: cut the text before the number so the
  whole number fits. That changes FR-102 and FR-110's wording, so it needs a spec amendment. I recommend accepting the cut
  for this phase and recording it in open-work. Today's model-given `line_holder` has the same cut.
- **H3: a file decided as one bill before this change (R-F).** The plan follows the spec literally: the file is split,
  your decided segment 0 is kept, and the other bills are added. A narrow guard would avoid the double count: don't split
  a file whose segment-0 bill you decided while it had no saved split, and give it reason (a)-style review instead. That
  would be a spec amendment to FR-121/FR-128. Decide whether to accept the literal behavior (recommended only if you have
  decided no multi-bill file as one bill) or amend the spec first.
- **H4 (before implementation, not a spec question): commit or stash the in-flight work.** The working tree holds tracked
  changes this workflow didn't make (`finance/ledger.py`, `app/static/document_v2.js`, `finance/pdf_import.py`, three docs,
  four tests) and an untracked migration `078_account_type_words.sql`. SL-01 can't start until `git status` shows no
  tracked change (the precondition under "Base"); the orchestrator then re-checks the citations against that commit.

**Answered by the user (2026-11-10).** H1 confirmed: `PHONE` (i) needs a 3-digit group before the last four, so year
ranges and account numbers are not holder titles. H2 confirmed: the 80-character cut stays as FR-102 says, recorded in
open-work by SL-10. H3: the literal behavior stands (no spec amendment); the user has decided no multi-bill file as one
bill. H4: the user's in-flight work stays uncommitted in the main checkout; implementation runs in a separate Git
worktree on branch `pdf-table-engine-bills`, created from the commit that adds this feature's spec, plan and approvals,
so the SL-01 precondition (no tracked change, no untracked file under `src/` or `tests/`) holds in that checkout. The
in-flight work touches files this plan edits (`finance/ledger.py`, `app/static/document_v2.js`, `docs/documents.md`,
`docs/money.md`), so integrating the two later may need conflict resolution by the user.
