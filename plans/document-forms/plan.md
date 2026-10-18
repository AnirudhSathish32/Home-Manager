# Document forms: receipt kinds, pay stubs and statements — implementation plan
Spec: specs/document-forms/spec.md (with specs/document-forms/test-contract.md)
Spec sha256: 7cf26b4ec7e952e54373b9e82e516eba61be79bf3420bdee61164bacddddfcbd

<!-- Approval lives in approvals/document-forms.json, bound to this file's hash. No Status line.
     Execution progress goes in plans/document-forms/progress.yaml, never in this file. -->

Planned as one feature in ordered phases (user decision 2026-10-18, instead of splitting the 30 FRs into separate
features): pay stub guards first (the reported defect), then statements, receipt kinds, gift cards, traces, kind
changes, the page, and evals with docs.

## Verified repository integration points

All paths are under `src/home_manager/` unless they start with `tests/`, `evals/` or `docs/`. Line numbers are from
commit 3c80ec5 plus the uncommitted tree at planning time.

| Area | Where | What this plan uses |
|---|---|---|
| Version | `documents/extraction.py:42` `EXTRACTION_VERSION` | Bumped once, in SL-02 (FR-16). It's part of the reuse key in `enqueue` (`:1442`) |
| Summary forms | `HEADERS` `:53`, `OPTIONAL_FIELDS` `:337`, `HEADER_MODELS` `:339`, `AMOUNTS` `:74` | Kind forms are new `HEADER_MODELS` keys. New pay stub and statement fields are optional, so existing stubs still validate |
| Classification | `Classification` `:174`, `CLASSIFY` `:431` | Gains `receipt_kind` and `receipt_kind_evidence` (D2: no extra call) |
| Rows | `Item` `:218`, `PayLine` `:254`, `ROWS` `:354` | `GroceryItem` (weight fields) and `PayLine` hours, rate and labels, all with defaults |
| Validation | `problems_in` `:795`, `ask` `:854` (one correction, then the DROPPABLE path `:884`) | `ask` gains a details fallback (FR-14) |
| Pay stub cells | `anchor_paystub` `:569`, `paystub_columns` `:467` | Sources the row label (cell 0) and column heading (header cell) on the table paths |
| Arithmetic | `normalize` `:955` (receipt `:996–1018`, statement `:1019–1046`), `paystub_lines` `:1308`, `review_reasons` `:1355` | New checks and the FR-22 guards run in `normalize`, so every path (vision table, native PDF, flat text) goes through them |
| Run flow | `run` `:1783`, `read` `:1849`, `record` `:1922`, `publish` `:1705`, `segments` `:1954` | The requested kind travels in the run's options. `record` scrubs `result_json` |
| Ledger writes | `finance/ledger.py` `_upsert` `:460` (a user-reviewed record is never rewritten), `publish_receipt` `:480`, `_replace_items` `:540`, `refresh_splits` `:643`, `publish_statement` `:739`, `publish_income` `:830` | Details are written in the same transaction as each record |
| Corrections | `CORRECTABLE` `:136`, `correct` `:1325`, `_apply_correction` `:1348`, `history` `:1420`, `undo_corrections` `:1477`, `apply_corrections` `:1535`, the `income_line:` prefix pattern `:1591–1630` | Detail corrections use a `detail:` prefix built on the `income_line:` pattern |
| Counting | `STANDALONE_RECEIPT` `:45`, `split_inputs` `:661` (target `receipts.total_minor`), `finance/reconcile.py:392` (match on `-total_minor`), `finance/health.py:106–176` | Every one reads `receipts.total_minor`, which is why D15 is stored as described below |
| Traces | `core/trace.py` `Recorder` `:50`, `build` `:129`. `finance/traces.py` `TRACES` `:294`, `split` `:187` (record-scoped ref pattern) | A new module `finance/document_traces.py` is merged into `TRACES` |
| API | `app/api.py` `ValueError`→400 `:644`, `RuntimeError`→409 `:648`, receipt routes `:980–1008`, `PATCH /api/finance/records/{type}/{id}` `:1309`, undo `:1329` | New routes are listed under "API contracts" |
| Manager | `app/manager.py` `submit` `:171`, `require` `:216`, `start_extraction` `:1479`, `set_split` `:1501` (a user choice followed by a forced re-read) | `change_receipt_kind` follows `set_split` but doesn't wait for an idle queue (SC-18 18a) |
| Migrations | `library/migrations/069_invoice_details.sql` (latest, `user_version=69`), `tests/test_migrations.py` (`test_064…` pattern) | Migration 070 |
| Model double | `tests/model_server.py:96` (`outputs` popped in order) | Gains `by_schema` (reply chosen by `json_schema.name`), as the test contract requires |
| Test helpers | `tests/test_extraction.py:130` `transcribe(tmp_path, local_model, lines, tables=None)`, `:148` `extract`, `tests/seed_documents.py`, `tests/test_document_v2_browser.py` | Reused |
| Evals | `evals/tasks/identify.py` (`cases`/`run`/`grade`), `evals/tasks/runner.py`, `tests/test_eval_tasks.py` | New task modules |
| Page | `app/static/document_v2.js` (646 lines; `RECORD_FIELDS` `:425`, kind label `:377`) | Details panel, kind control, check figures |
| Categories | `core/categories.py:5` includes `transportation` | Category for the fuel item (FR-06) |

**Verified facts that shaped the design:**
- `_upsert` returns `written=False` for a user-verified or rejected record (`ledger.py:466`). FR-12's pending proposal
  therefore needs its own column. It can't come through the normal publish.
- Every counting path (standalone receipts, splits, reconciliation, the health check, the CPA pack, the assistant tools:
  70 `total_minor` reads in 9 files) reads `receipts.total_minor` as the counted amount. See D15 storage below.
- `ask` already falls back to "drop and note" after the second failure, for identifying fields. FR-14 adds a second
  fallback of the same shape.
- `Recorder.input` only takes money (`core/trace.py:68`). Volume, price per unit, hours and rate need a decimal-text
  input.
- `start_extraction` refuses while any model work runs (`require("inference")`). SC-18 18a needs a kind change to queue
  behind another document's reading instead.

**Assumptions** (checked during the slice that relies on each):
- `splits.allocate(..., target)` spreads a target below the item sum proportionally ("any difference from what was
  charged shared the same way", `traces.py:210`). SL-06 asserts the categories keep their proportions. If they don't,
  SL-06 calls `splits.scale` explicitly, as FR-09 names.
- No existing pay stub fixture has a this-period value equal to year to date mid-year, or a row labelled "salary". SL-02
  runs the existing pay stub suites to confirm. Any fixture that trips a guard is reported, not silently re-stubbed.

## Architecture, contracts, data flow and decisions

### Data flow (unchanged shape, new steps marked ★)
1. `run` → classify the summary (★ the answer also carries `receipt_kind` and its evidence) → split into segments for
   receipts (★ each part's classification carries its own kind, FR-15).
2. `read` per segment → `extract`:
   - ★ **Choose the kind** (receipts only), first rule that applies: (a) the kind requested by this run's options (a
     kind change); (b) the latest `receipt_kind` correction on the receipt at (blob_hash, segment), so the user's
     choice persists; (c) the model's proposal, if it's in the list and every citation is an exact quote; (d) otherwise
     `general`, with the FR-02 note. A null or absent proposal means `general` with no note (D-P3).
   - Summary request with the kind's form: `HEADER_MODELS["receipt"]` for general (unchanged, schema name
     `ReceiptSummary`), or `"receipt:fuel"`, `"receipt:dining"`, `"receipt:grocery"` (schema names
     `ReceiptFuelSummary`, `ReceiptDiningSummary`, `ReceiptGrocerySummary`). Pay stubs and statements keep their
     schema names and gain optional fields.
   - Rows: grocery uses `GroceryItems` (`Item` plus `weight`, `weight_unit`, `price_per_weight`). The other kinds use
     `Items`. Pay stub rows gain optional fields.
   - ★ **Details fallback (FR-14):** if the final attempt fails, and validating the same JSON with only the new
     fields removed would pass, that base answer is used, `details_failed` is set, and nothing new is kept for the
     record. Problems in shared fields still fail the document, as today (variant 8a).
3. `read` → `anchor_paystub` (★ also records each value's row label and column heading from the validated table).
4. `publish` → `normalize`:
   - ★ Parse and validate details: exact-decimal texts, money to minor units, last four digits only.
   - ★ The kind's checks (fuel, dining gratuity, multi-unit lines), the gift card amount paid, the pay stub checks
     (hours × rate, deposit splits), the FR-22 guards, and the statement summary checks.
   - ★ FR-30 masking (below).
5. Ledger publish (★ writes the details, the kind, `printed_total_minor` and the kind correction in the same
   transaction) → `refresh_splits` → reconciliation.

### Storage (migration `070_document_forms.sql`, every column nullable, no backfill: FR-13 / D8)
```sql
ALTER TABLE receipts ADD COLUMN receipt_kind TEXT CHECK (receipt_kind IN ('fuel','dining','grocery','general'));
ALTER TABLE receipts ADD COLUMN details_json TEXT;          -- {"<kind>": {details}} : details per kind read
ALTER TABLE receipts ADD COLUMN pending_details_json TEXT;  -- {"kind","details","run_id","proposed_at"} (FR-12)
ALTER TABLE receipts ADD COLUMN printed_total_minor INTEGER; -- set only when a gift card lowers what counts (D15)
ALTER TABLE receipt_items ADD COLUMN details_json TEXT;     -- grocery: weight, unit, price per weight
ALTER TABLE income_records ADD COLUMN details_json TEXT;    -- balances, deposit splits, summary labels, guard results
ALTER TABLE income_lines ADD COLUMN details_json TEXT;      -- hours, rate, current/ytd labels
ALTER TABLE statements ADD COLUMN details_json TEXT;        -- bank or card summary fields
PRAGMA user_version=70;
```
Every table has been STRICT since migration 050. `ADD COLUMN` with a declared type works on STRICT tables, and the CHECK
on a new column is allowed because the column is nullable. The `test_migrations` refusal and rollback checks cover the
step.

- **Details per kind** (`receipts.details_json` keyed by kind). The current details are
  `details_json[receipt_kind]`. Undoing a kind change makes the earlier kind's details current again, and "fuel details
  are not current" after an undo to `general` falls out with no copying (journey step 5). A re-read replaces only the
  entry for the kind it read.
- **Detail value shape** (all types): `{"status": "proposed"|"ambiguous"|"missing", "text": str|null, "minor":
  int|null, "unit": str|null, "locator": {"line_ids": [...], "quotes": [...]}}`. Money uses `minor` (a JSON integer, so
  `json_type()='integer'` meets C-money). Decimals that aren't money use `text` exactly as printed (A2, FR-05). No
  floats are written anywhere.
- **D15, the gift card, stored as the counted amount (D-P1).** When a receipt has at least one gift-card tender and the
  deductions don't exceed the printed total, `total_minor` holds the **amount paid**, and the new
  `printed_total_minor` holds the printed total as a **magnitude** (never negative). With no gift card,
  `printed_total_minor` stays NULL and nothing changes. This keeps every one of the 70 counting reads unchanged and
  correct: standalone counting, splits, the reconciliation match (`reconcile.py:392`) and the health check all already
  target what counts. The display shows Total as `sign × coalesce(printed_total_minor, abs(total_minor))`.
- **`Ledger.refresh_paid(db, receipt_id)`** owns the derivation. It's idempotent. This area drew a MAJOR in passes 1, 2
  and 3, so each time the simplest alternative was adopted; it's now kept deliberately small.
  - **Bills:** a receipt corrected to "Record as: bill" applies rule 4 once: `total_minor = sign × coalesce(printed,
    abs(total))`, `printed_total_minor = NULL`. After that it returns early, so a later "New charges" correction
    writes `total_minor` as today.
  - **NULL total:** when `coalesce(printed_total_minor, total_minor)` IS NULL (a missing, ambiguous or cleared total),
    it strips its own issues and returns early. It also does nothing when the
    receipt has no gift-card tender and `printed_total_minor` is NULL. That covers every receipt today, so the existing
    paths can't be affected.
  - `sign = −1 if effective_receipt_direction(db, row) == 'return' else 1`. This is the rule the direction correction
    already uses (`ledger.py:1669`). Exchanges (mixed-sign lines, `sign_return` `extraction.py:929–945`, SC-04's
    savings row included) have a positive total, so they're sales here.
  - `printed = coalesce(printed_total_minor, abs(total_minor))` and `gift` = the sum of the current gift-card tenders'
    magnitudes, corrections applied.
  - Rules apply **first match, in this order**:
    1. `gift > 0` and `sign == −1` → `total_minor = −printed`, `printed_total_minor = NULL`, issue "Gift card on a
       return isn't handled; check the amount."
    2. `gift > printed` → `total_minor = printed`, `printed_total_minor = NULL`, issue "Gift card deductions exceed the
       total" (FR-09).
    3. `gift > 0` → `printed_total_minor = printed`, `total_minor = printed − gift`.
    4. Otherwise (the gift card was corrected away) → `total_minor = sign × printed`, `printed_total_minor = NULL`.
  - **It owns its issues, by fixed prefix.** The prefixes are "Gift card on a return", "Gift card deductions exceed"
    and "Amount paid (" (the linked-charge mismatch carries amounts, so it's matched by prefix, not exact text). Each
    run removes every issue with those prefixes and adds back only the current ones.
    - These texts never start with a correction label: the tender's correction label is "Gift card amount", which none
      of them begins with. They're never stored in `resolved_issues_json`, so an undo can't bring back a stale one.
    - When it adds one to a receipt the user hasn't reviewed (`review_source` isn't `user`), the receipt goes to
      `needs_review` with `review_source = NULL`, as the kept-items path does (`ledger.py:501`).
    - **It never moves a receipt to verified.** Pass 4 found that a restore conflicts with `undo_corrections`' own
      revert (`ledger.py:1523–1532`), and this area had then drawn a MAJOR in four passes, so the simplest alternative
      was adopted. After an issue clears, the existing paths decide the review state: `correct()`'s auto-verify check
      for a correction, and the user for an undo. SC-27 step 6 asserts only what the contract requires: the note
      clears.
  - **Where it's called, as the last write:**
    - `publish_receipt`: after `apply_corrections`, before `refresh_splits`;
    - `correct()`: after `_apply_correction` has written `validation_json` (`ledger.py:1373`), before the auto-verify
      check (`:1341`). It's never called inside `_apply_correction`'s loop;
    - `undo_corrections`: once at the very end, after the re-add (`:1519–1522`) and the revert (`:1523–1532`), when
      any undone field is in the trigger list;
    - `apply_corrections` (on a re-read): no call, because `publish_receipt` calls it right after.
  - `set_receipt_direction` (`ledger.py:1700`) leaves `printed_total_minor` alone, because it's a magnitude. Every
    direction change is followed by `refresh_paid`.
- **Family copies.** A receipt published from a family delivery (`finance/family_routing.py:261` `record_payload`
  carries `total_minor` only, which is already the amount paid) has no tenders. Its publish writes `receipt_kind`,
  `details_json` and `printed_total_minor` as NULL, so `refresh_paid` returns early and can't subtract the gift card a
  second time. Showing the printed total on a family member's copy is listed under Risks.
- **What triggers it**, always in the same transaction and at the call points above:
  - every publish;
  - a correction to `total`, `direction` or `document_kind`, or to any `detail:*` field;
  - an undo of any of those, or of `receipt_kind`.
  It doesn't run on apply (D-P4) or on unrelated corrections such as category. Whenever it changes `total_minor`, it
  calls `refresh_splits`.
- **Publish write and order.**
  - `publish_receipt`'s `_upsert` writes `receipt_kind`, `details_json`, `printed_total_minor = NULL` and `total_minor`
    = the reading's signed printed total, all as columns of the one upsert.
  - `details_json` is **merged**, not replaced. Before `_upsert` (which writes whole columns, `ledger.py:468–471`),
    publish reads the existing value and sets only `details_json[kind]` for the kind it read. That keeps the "a re-read
    replaces only its own kind's entry" rule, and lets an undo restore the earlier kind's details. A journey assertion
    checks it: after step 4's re-read, the general details entry still exists beside the fuel one.
  - Then, in order: items, `apply_corrections` (which sees the `detail:*` fields because the details are already in the
    row, `ledger.py:1549`/`:1562`), `refresh_paid`, and `refresh_splits`. A re-read whose printed
  total changed therefore never keeps a stale printed total.
- **Total corrections.** A `total` correction on a receipt whose `printed_total_minor` is set writes
  `printed_total_minor = abs(value)`, then calls `refresh_paid`. A blank (None) total writes both columns NULL, and
  `refresh_paid` then returns early. This is special-cased in `_apply_correction` and
  `apply_corrections`. `_field_text` shows Total as the printed magnitude, so Edit details and the page agree (8.55),
  and a user's total is never mistaken for the amount paid.
- **Splits.** When `printed_total_minor` is set, `Ledger.shares` divides the printed total with `splits.allocate`
  (recorder `NULL`), then resizes to the target with `splits.scale`, as FR-09 names. The live recorder goes through
  the existing `last(not shared)` rule (`ledger.py:680–689`), as the foreign-currency path does, so a shared receipt
  still records one live pass. The `split`
  trace then reconciles to the counted amount. `allocate` alone spreads a negative difference only over positive
  amounts (`splits.py:92`).

### Detail contracts per type (each field optional, cited)
| Type / kind | Summary fields (form) | Row fields | Checks (pass → `cross_checks += 1`, fail → issue) |
|---|---|---|---|
| fuel | `volume`, `volume_unit` (gallon\|litre, from printed words), `price_per_unit`, `fuel_grade`, `pump_number`, `fuel_amount` (money) | Items as today | FR-07: `Decimal(volume)×Decimal(price)` ROUND_HALF_UP to the minor unit, within 1 of the fuel amount. Skipped if any input isn't proposed (2a) |
| dining | `gratuity_included` (the printed words), `gratuity` (money), `party_size`, `server`, `table` | Items | FR-08: `subtotal + tax + (tip or 0) + (gratuity or 0) = total`, replacing today's check on dining receipts only |
| grocery | `savings_total` (money), `tenders: list[Tender]` (`tender_type` gift_card\|ebt\|card\|cash\|other, `amount`, `last_four`, evidence) | `GroceryItem`: `weight`, `weight_unit`, `price_per_weight`; the existing `quantity`/`unit_price` | FR-09 multi-unit line: count × unit price, half-up, within 1, only when a count is printed. The item-sum check is today's, and tenders never join it |
| general | none (today's form, D1) | Items | today's |
| pay stub | each money summary field is a `PayValue` (Value + `row_label: PayLabel \| None`, `column_heading: PayLabel \| None`, where `PayLabel = {text, evidence: list[EvidenceQuote] (min 1)}`); `pto_balance`, `sick_balance` (text + label); `deposit_splits: list[Split]` (`last_four`, `amount`, evidence) | `PayLine` + `hours`, `rate`, `current_row_label`, `current_column_heading`, `ytd_row_label`, `ytd_column_heading` (each a `PayLabel \| None`) | FR-21 hours × rate per earning line; split sum = net pay when every split has an amount. FR-22 guards (below) |
| bank statement | `account_type` (checking\|savings\|money_market\|other), `deposits_total`, `withdrawals_total`, `interest_earned`, `fees_total`, `apy` (percent text) | Transactions as today | FR-26: opening + |deposits| − |withdrawals| = closing, only when all four are printed |
| card statement | `purchase_apr`, `cash_advance_apr` (percent text), `credit_limit`, `available_credit` (money), `rewards_earned`, `rewards_balance` (text, plus minor when the printed text is money) | Transactions as today | FR-28: previous − |payments| − |credits| + purchases + fees + interest = statement balance, only when all are printed (a printed 0.00 counts) |

Labels and printed text are checked in code, outside the generic amount check:
- **Labels are cited on their own (FR-20).** A row label or column heading carries its own evidence, and its text must
  be an exact substring of its own cited quote. That quote must in turn be an exact substring of its cited line, under
  `mask` (`problems_in` doesn't reach nested evidence, `extraction.py:812–834`, so `normalize` checks it). The heading
  can sit on another line: P-flat's `YEAR TO DATE` section line, or a table's header row.
- **On the table paths**, `anchor_paystub` builds the labels from validated cells: row label = `cells[0]` with that
  row's line id and quote; column heading = the header cell of the chosen column with the header row's line id and
  quote. The model's labels are then ignored.
- **A label that fails its check** is dropped (null), with the note "<field> label was not printed where it was
  cited." It never fails the document. The same holds for any detail that fails a check in `normalize`, after `ask`:
  it's dropped with a note naming the field, so nothing invented is stored, and FR-14's fallback isn't needed.
- An `account_type` other than `other` needs its word in the citation. Anything else becomes `other` (FR-25).
- Points stay text (FR-27).

`account_type` is stored in the statement's details only. `accounts.account_type` is not changed (FR-29: what counts and
how accounts are matched stays the same).

### FR-22 guards (`extraction.py`, `this_period_guards(record, labels, issues)`, called from `paystub_lines`)
For gross pay, net pay, taxes, deductions and each line's current amount:
- **(a)** The row label, the column heading (each after its own citation check) or any cited quote of the value matches
  `\b(ytd|year[\s-]*to[\s-]*date|annual(?:ly)?|yearly|salary|per\s+year)\b`.
- **(b)** `abs(this period) > abs(its year to date)`. Gross is compared with gross YTD, net with net YTD, and a line
  with its own YTD. Taxes and deductions have no YTD field, so (b) and (c) skip them.
- **(c)** The value equals its year to date, and the pay period doesn't start in the first pay period of the year. That
  year is the pay date's year (the period's year if no pay date is printed). The first period means `period_start ≤
  Jan 1 + days_per_period − 1`, where `days_per_period` is 7, 14, 15 or 31 from `pay_frequency`. A period that starts in
  December counts as first, which the later rule then catches.
- **Result:** (a), (b), or (c) with a known period → the value becomes null and `ambiguous`, with an issue starting
  with the field's correction label (`Gross pay`, `Net pay`, `Taxes this period`, `Deductions this period`, or
  `This period: <line description>`). The issue names both values and the cited line ids. (c) with an unknown period or
  frequency → the value is kept and the equality issue is added (20-h).
- Guarded values are never filled in with a calculated value.
- The stub then fails `REQUIRED`/`CROSS_CHECKED` or carries an issue, so it can't count automatically (FR-23).
- Correcting the field clears its issue through the existing `startswith(label)` rule.
- Line corrections get the same treatment, for `This period: <description>` (FR-23 "as for other fields"):
  - `_correct_income_line` clears the line's issue and stores it in `resolved_issues_json` (today it stores `'[]'`,
    `ledger.py:1606`), so undo restores it;
  - `apply_income_line_corrections` (`:1619`) clears it on every re-read, so a corrected line doesn't come back to
    review.
- Each issue says which rule fired ("reads as year to date or annual", "is larger than its year to date", "equals its
  year to date mid-year"). SC-20 asserts the rule, not only that the value is null (20-a must fire on (a)).
- On the table paths, `anchor_paystub` already copies from the Current column. The guards still run on the copied
  values, and 20-f expects no reason.

### Receipt kind on Classification (FR-01, FR-02)
`receipt_kind: str | None` with `json_schema_extra={"enum": [...]}`, so the schema sent constrains the model, but an
out-of-list stub answer (7a `pharmacy`) is caught in code instead of failing classification. `receipt_kind_evidence:
list[EvidenceQuote]` defaults to `[]`. These fields are excluded from `problems_in`, so a bad kind citation can never
fail the document. The kind-choice step validates them (rule (c) above).

### Kind change (FR-11, FR-12, FR-18; decision D-P2)
- `PATCH /api/receipts/{receipt_id}/kind` with body `{"kind": "fuel"|"dining"|"grocery"|"general"}` (Pydantic
  Literal, so `pharmacy` gets a 4xx and nothing changes, J-d) → `Manager.change_receipt_kind`:
  1. `require(False)`. 404/400 if the receipt is unknown or is a bill.
  2. If the receipt's `blob_hash` has a `queued` or `running` run, in `extraction_runs` (joined through `parse_runs`)
     or in `parse_runs` itself (a transcription in progress, FR-18's "reading or extraction"), for any occurrence →
     `RuntimeError("A reading is in progress; try again when it finishes")` → 409. Nothing is written.
  3. If the kind equals the current kind → `{"run_id": null, "unchanged": true}`. No request and no correction (J-a).
  4. Find the latest succeeded parse run for the current hash (as `set_split` does). `enqueue(document_id,
     parse_run_id, self.reasoning_config, force=True, home_currency=self.household.home_currency,
     decision=self.decision_config, receipt_kind={"segment": s, "first_line_id": f, "kind": k})`, the same arguments
     `start_extraction` passes (`manager.py:1483–1484`). The segment is matched by its first line id when the run splits
     the file again (`segments()` re-asks the model for unconfirmed splits, `extraction.py:1969`). If no segment starts
     at that line, the run publishes nothing for the kind: it's reported as failed with "The file's split changed;
     confirm the split, then change the kind again." Nothing is written. The options are in `config_json`, so the run is never reused. `run()`
     pops `receipt_kind` from the settings before `ReasoningConfig.model_validate` (`extraction.py:1788–1792`;
     `ReasoningConfig` forbids extra keys), as it already does for `home_currency` and `decision`.
     `first_line_id` comes from the receipt's `document_segments` row. The fallback, the first non-blank line of the
     latest parse, applies only when the hash has no segment rows at all (a single-receipt file, `save_segments`
     `extraction.py:2067`). A receipt with no row in a file that is split is a retired segment
     (`ledger.py:512–529`), and its kind change is refused with 400 "This receipt is no longer in the file's split."
     The match runs in `run()` after the per-part classification loop (`:1810–1818`, which can collapse the parts) and
     before `read` (`:1819`). A mismatch fails the whole run: no segment publishes, and `save_segments` and
     `retire_segments` don't run.
  5. `submit(..., self.extract_and_file, document_id, run_id)` on the inference queue with no busy check
     (`manager.py:1508`), so reconciliation, filing and item identification run as for any reading. The executor runs
     it after other work (18a).
  6. Returns 202 `{"run_id"}`.
- Steps 2–5 run under `Manager.mutex`, which every API mutation already takes. Two simultaneous PATCHes are
  therefore serialized, and the second one sees the first one's queued run and gets 409.
- The kind correction row (`record_type='receipt'`, `field='receipt_kind'`, previous = the old kind, which may be
  null) is inserted **inside `publish_receipt`'s transaction**, together with that record's details. So each record
  either has its kind, details and correction, or none of them.
  - A run cancelled or interrupted before publication leaves the state exactly as before (J-b).
  - A run interrupted after a segment's commit, but before the run's status is written, leaves that segment's record
    whole and consistent, and the run `interrupted`. J-c asserts "no partial details on any record", not "nothing
    changed".
- The journey reads the correction id from `history` after the run (D-P2).
- **Kind choice rule (b)** treats a latest `receipt_kind` correction whose value is null as "no user choice". That's
  what undoing the first kind change on a pre-upgrade receipt leaves.
- **A plain re-read** (no requested kind) of a verified or rejected receipt changes nothing on it: no kind, no details,
  no pending proposal. Only a requested kind writes to a user-reviewed receipt.
- **Unreviewed receipt:** normal publish. The new kind, details, items and amounts are written. Your corrections are
  re-applied (`apply_corrections`).
- **Verified or rejected receipt (`_upsert` returns not written):** `publish_receipt` still writes the kind
  correction, sets `receipt_kind`, and stores the reading's details in `pending_details_json`, replacing any earlier
  proposal (J-e). Amounts, items and review state are untouched (FR-12).
- `POST /api/receipts/{receipt_id}/details/apply`:
  - With nothing pending → 400 "There are no details waiting to be applied." (J-f).
  - Otherwise it moves the pending details into `details_json[kind]` and writes a correction `field='receipt_details'`
    (value = the kind, previous = the earlier details for that kind as JSON). Amounts and review state are unchanged:
    no `refresh_paid` on apply (D-P4).
  - Undoing it puts the details back into pending (journey step 10).
  - Pending and apply cover the **summary details** only (the kind's form fields and tenders). Item rows on a reviewed
    receipt are never rewritten, so grocery item details (weights) on such a receipt stay as they were. This is listed
    under Risks.
- `undo_corrections` gets explicit branches before the generic `_apply_correction` call (`ledger.py:1518`, which would
  raise KeyError because neither field is in `fields_for`):
  - `receipt_kind`: insert a new `receipt_kind` correction row whose value is `previous` (reason `UNDO_REASON`, as the
    `income_line:` undo does, `ledger.py:1503`). Rule (b) then sees the undone choice. Set the column, then
    `refresh_paid`. Any pending proposal is cleared, because it belonged to the kind being undone;
  - `receipt_details`: move `details_json[kind]` back into `pending_details_json` and restore `previous`.
- `receipt_kind` is not accepted by the generic `PATCH /api/finance/records/...`, because it must re-read. It does
  appear in `history` (label "Receipt kind") and can be undone through `undo_corrections`.

### Detail corrections and override provenance (needed by FR-19 and SC-27)
- Fields are named `detail:<path>`, for example `detail:fuel.volume`, `detail:tenders.1.amount`,
  `detail:lines.<line key>.hours` and `detail:summary.deposits_total`.
- They go through the existing `PATCH /api/finance/records/{type}/{id}` and appear in `correctable` with their kind
  (`decimal_text` or `money`).
- `_apply_correction`, `apply_corrections` and `undo_corrections` handle the prefix the way `income_line:` is handled
  today. Each stores previous and value as text in `record_corrections`.
- An undo of a `detail:*` correction whose field the current details no longer have (for example, the kind changed
  since) raises `ValueError("This detail is no longer in the reading.")` → 400, never a KeyError. `apply_corrections`
  skips such fields, as it does today (`ledger.py:1562`). A journey assertion checks this after step 5.
- A correction on a receipt detail or on `total` calls `refresh_paid`. When the new amount paid no longer equals a
  non-rejected linked charge, it adds the issue "Amount paid (4.55) no longer equals the linked charge (3.55)" and sets
  `needs_review`. When they match again (a correction or an undo), `refresh_paid` removes the issue (SC-27 step 6:
  "the note clears"). It never sets verified. After a correction, `correct()`'s existing auto-verify check runs after
  it, as for any field.

### Check figures and traces (FR-19)
- One pure module, `finance/document_checks.py`, holds every new check as a function of printed values with a
  `recorder=NULL` argument: `fuel(volume_text, price_text, amount_minor, currency, recorder)`, `dining`, `unit_line`,
  `amount_paid`, `hours_rate`, `deposit_splits`, `bank_summary` and `card_summary`. Each returns `(computed_minor,
  compared_minor, passes)`.
- `normalize` calls them with `NULL`. `finance/document_traces.py` calls them with a live recorder on the stored record,
  corrections applied. This is the contract's "no parallel explainer" rule.
- Refs: `receipt.fuel?receipt_id=`, `receipt.dining?receipt_id=`, `receipt.unit_line?receipt_id=&position=`,
  `receipt.paid?receipt_id=`, `paystub.hours?income_id=&position=`, `paystub.deposits?income_id=` and
  `statement.summary?statement_id=` (bank or card, by the statement's type). They're merged into `TRACES`.
- **Trace shape.** It uses `build()` plus a wrapper, `check_trace`, which:
  - adds `compared_with` (the printed amount as `money()`);
  - sets `reconciles` to the check's outcome (FR-19 defines it so for these figures; module docstring and docs/ui.md
    record the exception);
  - records the rounding as `{"method": "half_up_minor", "note": "10.312 × 3.459 = 35.669208"}` for the products.
- Additive checks (dining, amount paid, splits, summaries) record signed steps. Products record one step at the
  rounded value.
- **Unprinted input** (SC-19 step 4, the dining tip): `Recorder.step(..., missing=True)` adds 0 to the running total,
  and `build` emits that step with `"value": null` and the label "Tip (not printed)".
- **Amount paid with no other printed tender:** `compared_with` is null, and `reconciles` is true exactly when the
  deductions don't exceed the printed total. With another tender printed, it's compared with that tender's amount.
- `Recorder.input_text(key, label, text, unit, provenance, verification)` is new. It stores `value = {"text", "unit",
  "display", "minor": None, "currency": None}`. `verification_of` skips a `None` minor when summing. `inputs_hash`
  hashes `text` and `unit` for these inputs, so a corrected volume or rate marks the figure stale even when the rounded
  result doesn't change. Provenance is
  `extracted` (document id, line ids, quote) or `override` (original, reason, actor) from the detail correction.
- A ref for something the record doesn't have → `ValueError("This isn't worked out for this record.")` → 400.
- `Ledger.record` returns `checks: [{"name", "label", "figure": figure(computed, currency, trace=ref), "compared_with":
  money(...), "passes"}]`, worked out with the same functions, so the page does no math and `trace.result` equals the
  figure.

### FR-30: identifiers (decision D-P5, user-approved reading of FR-30 against C-cite)
- `core/identifiers.py`:
  - `IDENTIFIER` matches either an unbroken run of 5 or more digits that isn't part of a decimal or thousands-separated
    amount (`(?<![\d.,])\d{5,}(?![\d]|[.,]\d)`), or a card-style group of three or more four-digit blocks
    (`\d{4}(?:[ -]\d{4}){2,}`).
  - It deliberately doesn't match ISO dates (`2026-10-03`), phone numbers (`555-123-4567`) or amounts (`32,500.00`,
    `12500.00`).
  - `mask(text)` keeps the last four digits of each match and replaces the rest with `*`.
  - `scrub(record_dict, keys)` masks the strings under the named keys only.
  - Unit tests show dates, phones and amounts pass through `mask` unchanged, and the identifiers in the fixtures are
    masked.
- Applied to:
  1. every `last_four` value (digits only, the last four. Under four digits → dropped, with the note "<field> was not
     an account number and was dropped.");
  2. every new free-text detail (labels, server, table, grade, rewards text). If masking changed it, the note "Digits
     of an identifier were dropped from <field>." is added;
  3. the cited quotes of the identifier fields (`account_reference`, `card_last_four`, splits, tenders) and of every
     new detail, before they go into a locator;
  4. in `extraction_runs.result_json`, via `scrub` in `record()`: the values and quotes of the same identifier fields
     and new details, under `header`, `rows[].` new fields and `normalized`. Dates, merchant names and item rows are
     untouched, so `filing_identity` (`extraction.py:2073`) keeps working.
- Item quotes (product codes) and other non-identifier quotes aren't masked, in the locators or in `result_json`, so
  today's source highlighting is unaffected.
- `parse_runs`, `document_passages` (the rebuildable copy of transcription text, `migrations/042_document_text.sql:1–11`),
  `document_passages_fts` and its FTS5 shadow tables (`document_passages_fts_*`) are "the saved transcription" and are
  exempt.
- Item rows stay unmasked, because product codes (12-digit UPCs) match the pattern. SC-04 variant 4d's stub returns
  the gift card as an item with description `GIFT CARD` and quote `-5.00` (an exact substring of line 12), so C-ids
  holds there. A real model quoting a card number inside an item row is listed under Risks.
- C-cite compares `mask(quote)` with `mask(line)`.

### API contracts (new or changed)
| Route | Body | Success | Errors |
|---|---|---|---|
| `PATCH /api/receipts/{id}/kind` | `{"kind": Literal[...]}` | 202 `{"run_id": str}` or 200 `{"run_id": null, "unchanged": true}` | 409 reading in progress; 4xx unknown kind; 400 bill or unknown receipt |
| `POST /api/receipts/{id}/details/apply` | none | 200 the record (`correction_ids`) | 400 nothing pending |
| `PATCH /api/finance/records/{type}/{id}` | `changes` may name `detail:*` | as today | 400 for a field the record doesn't have |
| `GET /api/finance/records/receipt/{id}` (and income and statement) | — | adds `receipt_kind`, `details` (current), `pending_details`, `printed_total`, `amount_paid`, `tenders`, `checks`; items and lines add `details` | — |
| `GET /api/traces/{ref}` | — | the new refs above | 400 "This isn't worked out for this record." |

### Decisions taken in this plan
- **D-P1** (spec open item: storage shape). JSON details per record and per row, beside the record, as with
  `invoice_json`. The gift card is stored as described under D15 above. Alternative rejected: a new `paid_minor`
  column, which would mean changing 70 counting reads across 9 files and risks FR-29.
- **D-P2** (user, 2026-10-18). A kind change is an asynchronous run. Its correction is written atomically with
  publication.
- **D-P3.** A null or absent kind proposal is `general` with no note. `general` needs no citation, because it's the
  fallback and keeps today's form. Existing receipt stubs stay valid and SC-05 holds. FR-02's note fires only for a
  proposed non-general kind that fails its checks, or for an out-of-list value.
- **D-P4** (user, 2026-10-18). Apply details never changes amounts or review state, even when the details include a
  gift card. The page then shows "Paid 3.55 isn't counted: this receipt was reviewed before its gift card was read.
  Correcting the gift card, the total or sale/return with Edit details counts it." Any of those corrections runs
  `refresh_paid`, which then counts the amount paid.
- **D-P5** (user, 2026-10-18). FR-30 is met by masking, as described above. The transcription stores are exempt, and
  C-cite holds under the mask.
- **D-P6** (user, 2026-10-18). The spec's domain risk candidates 1–7 are not built. They're listed under Risks, and
  SL-10 adds them to `docs/open-work.md`.
- **D-P7.** The eval thresholds stay report-only (the spec's open default). The only target is the pay stub wrong-column
  count of 0 on the synthetic fixtures.

## Error handling, idempotency and recovery
- **Kind proposal invalid** → `general`, the note "Receipt kind: <value> was not used: <why>.", and `needs_review`. No
  request goes out for that kind's form (FR-02, SC-07).
- **New fields invalid twice** → the base answer is published. `details_failed` drops every new field for that record
  (summary and rows alike, none partial) and adds "Document details could not be read; the record was saved with its
  usual fields." (FR-14, SC-08, SC-26). A shared-field failure still fails the run with nothing published (8a).
- **Atomicity, per record:**
  - Each record's kind, details, items or lines, `printed_total_minor`, splits and kind correction are written in the
    one `store.connection()` transaction that `publish_*` already opens.
  - Segments of a split file are separate transactions, as today (`run` `:1825–1839`).
  - Cancellation is checked before any publish (`:1823`, unchanged). `recover()` marks queued and running runs
    `interrupted`, unchanged.
- **Duplicate PATCH** → no-op when the kind is already current. During a running reading → 409.
- **Reading again:** items match by (description, line total) as today. A `PUMP 17` item nobody worked on is removed
  with its split rows (`_replace_items`). One you worked on is kept with today's note. Pay stub corrections re-apply,
  and guards fire again on the model's values, then your corrections clear their issues (SC-20 follow-on).
- **Retries:** no path retries a run by its id; "retry" means a new reading (`extraction.py:1423`). A cancelled or
  interrupted kind change is retried by sending the same `PATCH` again. The kind isn't current yet, so it isn't a
  no-op. J-b and J-c do exactly that and assert the requested kind afterwards.
- **FR-18 window:** a document in a running batch whose extraction row isn't created yet (`manager.py:1357–1364`) isn't
  refused. The outcome is safe: the plain reading runs first, then the kind run, and rule (b) keeps the kind. It's
  listed under Risks.
- **Restart with a pending proposal:** it's a column, so it survives a restart (journey step 8).

## Privacy/security and migration impact
- Only synthetic fixtures in Git are used. Nothing reads `P:\Finances`, `%LOCALAPPDATA%\HomeManager` or `P:\EvalCorpus`.
  The user runs the eval and the redacted paystub reproduction in their own terminal and shares only `summary.json`
  (FR-24, `docs/evals.md`).
- No new external service. All calls go through `request_completion` under the existing endpoint validation. `RULES`
  is prepended to every new form, unchanged.
- FR-30 masking is described above. It reduces what's stored compared with today, for identifier fields.
- **Migration 070** is additive and nullable, with no backfill and nothing queued (FR-13). It goes through the existing
  runner's pre-upgrade copy and rollback. `docs/documents.md` "Schema upgrades…" needs no change.
- **Gated work:** this touches persisted schemas and money (what counts after a gift card), so it stays behind the gate.
  Plan approval is `gate.py approve --feature document-forms --stage plan --by "<name>"`, run by the user.

## Vertical slices
Each slice is independently verifiable and leaves the suite green. Lint every slice with
`python -m ruff check <touched files>`, plus `python -m mypy src/home_manager` when the project's mypy config covers the
touched modules (`docs/development.md`).

| ID | FR/SC covered | Dependencies | Files/changes | Verification command / evidence |
|---|---|---|---|---|
| SL-01 Storage and stub harness | FR-13; SC-11 | none | `library/migrations/070_document_forms.sql`. `tests/model_server.py`: `state["by_schema"] = {name: [outputs]}`, popped by `body["response_format"]["json_schema"]["name"]` before `outputs`. `tests/document_forms_fixtures.py`: synthetic lines for SC-01…SC-27, fixture P (P-flat, P-table builders) and stub builders keyed by schema name. `tests/test_migrations.py::test_070_document_forms_*` | `python -m pytest tests/test_migrations.py -k "document_forms or 070" -q`. Also `python -m pytest tests/test_extraction.py -q` (the harness change leaves the old `outputs` order intact) |
| SL-02 Pay stub guards and labels (the reported defect) | FR-22, FR-23, FR-24 (test part), FR-20 (row label and column heading only), FR-16; SC-20, SC-15 | SL-01 | **First**, write `tests/test_paystub_forms.py::test_sc20_e_*`. Its stubs use **only pre-change fields**: no `row_label`, `column_heading` or `receipt_kind` keys. `StrictModel` forbids extra keys (`receipt_schema.py:15`), and an extra key would fail the old code for the wrong reason. The new fields then take their defaults after the change. The test asserts `status == "needs_review"` and `gross_pay_minor is None`, and it prints the record's status and `gross_pay_minor`. Run it on the unchanged code: it must fail, and the printed output must show `verified` and `3250000`. Save that output as evidence in `progress.yaml`. The pre-change run is on the tree after SL-01 (it needs the `by_schema` harness and fixtures), with none of SL-02's non-test changes applied. P-flat prints one amount per line (the Regular line's amounts too), so `anchor_paystub`'s multi-number nulling (`extraction.py:608`) can't be why it fails. Then: `PayValue` and the `PayLine` label fields. Labels from `anchor_paystub` on the table paths. Label substring and line checks. `this_period_guards` called from `paystub_lines`. Issue clearing in `_correct_income_line` and `apply_income_line_corrections`. `ledger.publish_income` writes `income_records.details_json` and `income_lines.details_json` (labels and guard results; SL-03 adds its fields to the same write). `EXTRACTION_VERSION = "typed-extraction-v23-document-forms"` | Pre-change run: `python -m pytest tests/test_paystub_forms.py -k sc20_e -q` (expected FAIL, recorded). After: `python -m pytest tests/test_paystub_forms.py -k "sc20 or version" -q`. Regression: `python -m pytest tests/test_vision_tables.py tests/test_pdf.py tests/test_layout_consumers.py tests/test_extraction.py -q` |
| SL-03 Pay stub fields, checks, details fallback, identifiers | FR-20 (hours, rate, balances, splits), FR-21, FR-14 (mechanism + pay stub), FR-30; SC-21 (checkpoints 1–3, 5), SC-25 (pay stub) | SL-02 | `extraction.py`: pay stub optional fields, the `Split` row model, the `ask` details fallback (`base_schema`, `new_fields`), `details_failed` handling. `finance/document_checks.py` (`hours_rate`, `deposit_splits`). `core/identifiers.py` (`mask`, `scrub`) with unit tests, applied in `normalize` and `record()`. `ledger.publish_income` adds the new fields to SL-02's details write | 1. `python -m pytest tests/test_paystub_forms.py -k "sc21 or sc25 or fallback" -q` 2. `python -m pytest tests/test_identifiers.py -q`. SC-25's SQL scan covers every table except the transcription stores (`parse_runs`, `document_passages`, `document_passages_fts`, `document_passages_fts_*`) |
| SL-04 Statement fields and summary checks | FR-25, FR-26, FR-27, FR-28, FR-14 (statement), FR-29, FR-30 (statement); SC-22, SC-23, SC-24, SC-25 (statement), SC-26 | SL-03 | `extraction.py`: optional bank and card fields, account-type wording, percent text. `document_checks.bank_summary`, `card_summary`. `ledger.publish_statement` writes `details_json`. `tests/test_statement_forms.py` | `python -m pytest tests/test_statement_forms.py -q`. SC-24 uses fixture P-sept (spec D16). It asserts the hard-coded figures worked out from the fixtures, and also compares them with the new-field writes switched off (monkeypatched to null) |
| SL-05 Receipt kinds: classification, forms, kind checks | FR-01–FR-08, FR-09 (weights, multi-unit lines, deposits and bag fees, savings; not gift-card counting), FR-14 (receipt), FR-15, FR-30 (tender last four); SC-01, SC-02, SC-03, SC-04 (non-gift checkpoints, 4a–4c), SC-05, SC-06, SC-07, SC-08, SC-12 | SL-03 | `Classification` kind fields and `CLASSIFY` text, the kind-choice step, the `receipt:*` header models, `GroceryItem`/`GroceryItems`, `Tender`, row directions per kind. Fuel: one fuel item, category `transportation`, pump, volume and price lines never items (code guard drops a row citing only a `PUMP\s*#?\s*\d+` line, with a note). The dining check. `document_checks.fuel`, `dining`, `unit_line`. `publish_receipt` writes `receipt_kind`, details, item details. `tests/test_receipt_kinds.py`. `tests/test_receipt_segments.py::test_*kind*` | 1. `python -m pytest tests/test_receipt_kinds.py -k "sc01 or sc02 or sc03 or sc04 or sc05 or sc07 or sc08 or version" -q` 2. `python -m pytest tests/test_receipt_segments.py -q` (includes the new `kind` tests) 3. `python -m pytest tests/test_invoice_ingestion.py tests/test_extraction.py tests/test_receipts.py -q` (no `-k`) |
| SL-06 Gift cards and amount paid | FR-09 (D15), FR-29 (gift-card exception); SC-04 (gift checkpoints, 4d–4f), SC-27 (checkpoints 1–3, 5 without trace, 6, 27a, 27b) | SL-05 | `ledger.refresh_paid`, `printed_total_minor` write, the `detail:` correction prefix (`_apply_correction`, `apply_corrections`, `undo_corrections`, `correctable`, `history` labels), the linked-charge mismatch issue. The record view gains `printed_total`, `amount_paid` and `tenders`. Health check unchanged, asserted. SC-04 adds a variant (plan-level, not in the contract): correct the direction to `return` → `total_minor == -855` with the "Gift card on a return" issue, and undo → 355 again | 1. `python -m pytest tests/test_receipt_kinds.py -k "sc04 or sc27" -q` 2. `python -m pytest tests/test_health.py tests/test_reconcile_tools.py tests/test_spending_splits.py tests/test_returns.py -q` 3. `python -m pytest tests/test_extraction.py tests/test_receipts.py tests/test_invoice_ingestion.py tests/test_bills_ledger.py tests/test_family_routing.py tests/test_family_inbox.py -q` (no `-k`; SL-06 changes `publish_receipt`). The SC-04 direction variant also asserts that the return issue clears after the undo. A receipt with a missing total and a bill each publish unchanged |
| SL-07 Check figures and traces | FR-19; SC-19 (API checkpoints 1–7), trace checkpoints of SC-21 (4, 21a), SC-22, SC-23, SC-27 (4, 5 provenance) | SL-04, SL-06 | `core/trace.py` `input_text` with None-safe roll-ups, `inputs_hash` over `text` and `unit`, and `step(missing=True)`. `finance/document_traces.py` (`check_trace` and the seven refs) merged into `TRACES`. `Ledger.record` `checks`. `Ledger.shares` recorder routing (`allocate` gets NULL, `scale` gets the live recorder). Extends `tests/test_migrations.py::test_070_document_forms_*` with SC-11's last checkpoint: the record view of a pre-upgrade receipt, pay stub and statement shows no kind, no details and no `checks` | 0. `python -m pytest tests/test_migrations.py -k "document_forms or 070" -q` 1. `python -m pytest tests/test_receipt_kinds.py -k "sc19 or sc27" -q` 2. `python -m pytest tests/test_paystub_forms.py -k sc21 -q` 3. `python -m pytest tests/test_statement_forms.py -k "sc22 or sc23" -q` 4. `python -m pytest tests/test_traces.py tests/test_ui_parity.py -q` (no `-k`) |
| SL-08 Kind change, re-read, pending details | FR-11, FR-12, FR-18, FR-06 (re-read), FR-16 (journey 1); journey (SC-09, SC-10, SC-13, J-a…J-f), SC-18 | SL-06 | `ExtractionService.enqueue(receipt_kind=)` and kind choice (a)/(b). `publish_receipt` writes the kind correction and the pending proposal. `Ledger.apply_details`. `Manager.change_receipt_kind`, `apply_receipt_details`. API routes. `correct()` refuses `receipt_kind` | `python -m pytest tests/test_receipt_kinds.py -k "journey or sc18" -q`. SC-18 setup: see "SC-18 setup" under Test environments |
| SL-09 Document page | FR-10, FR-11 (UI path), FR-19 (page links); SC-14, SC-19 step 8 | SL-07, SL-08 | Load `ui-ux-pro-max` and `ui-redesign` first (project CLAUDE.md). `app/static/document_v2.js`: a Details section per type, item and line details, tenders, the money summary line "Total · Gift card · Paid", check figures through `trace.js` `figure`, a Kind row with a change control (preview, save, poll the run, reload), and the pending details banner with **Apply details**. `style.css` tokens only, CSP strict, no math in the browser. `tests/seed_documents.py` `seed_document_forms`. `tests/test_document_v2_browser.py` | `python -m pytest tests/test_document_v2_browser.py -k "kind or forms or kind_trace" -q`. Synthetic before/after screenshots with `python .claude/skills/ui-redesign/scripts/ui_shots.py` (per the `ui-redesign` skill). (`RECORD_FIELDS` is defined in `receipt.js:34` and used at `document_v2.js:425`) |
| SL-10 Evals and docs | SC-17, FR-24 (eval part), FR-17; SC-16 | SL-05, SL-03, SL-04 | `evals/tasks/receipt_kinds.py` (kind accuracy per kind; fields present and correct per form), `evals/tasks/document_forms.py` (pay stub, bank, card fields; wrong-column values that would count automatically, per pay stub fixture) and their synthetic fixtures, registered with the runner. `tests/test_eval_tasks.py`. Docs: `docs/documents.md` "Typed extraction" (new subsections "Receipt kinds" and "Pay stub and statement fields", existing headings unchanged); pay stub guards in `docs/money.md` under its pay stub heading; the new refs and the `reconciles` exception in `docs/ui.md` "What's built"; `docs/open-work.md` (remove the gas-station and receipt-kind items, add D4 analytics, the pay stub alternatives and domain risks 1–7); `text_extraction_plan.md` (which open pay stub items this closes) | `python -m pytest tests/test_eval_tasks.py -k "receipt_kind or document_forms" -q`. SC-16 review of `git diff docs/ text_extraction_plan.md` against FR-17 |

**Release unit:** the slices land on one branch and none ships on its own. `EXTRACTION_VERSION` is bumped once, in
SL-02, while SL-03 to SL-05 keep extending the output under that version. That's safe only because nothing is merged
before SL-10.

The full targeted run after SL-10 is the contract's command, plus `tests/test_vision_tables.py tests/test_pdf.py
tests/test_layout_consumers.py tests/test_traces.py`.

## Requirements & scenarios coverage matrix
| FR | Slice(s) | Scenarios | Test file |
|---|---|---|---|
| FR-01 | SL-05 | SC-01, SC-05 | `test_receipt_kinds.py`, `test_extraction.py` |
| FR-02 | SL-05 | SC-07 (7a, 7b) | `test_receipt_kinds.py -k sc07` |
| FR-03 | SL-05 | SC-01 (captured schema) | `-k sc01` |
| FR-04 | SL-05 (grocery tenders SL-05, counting SL-06) | SC-01, SC-03, SC-04 | `test_receipt_kinds.py` |
| FR-05 | SL-05 | SC-01, SC-04 (C-money) | `test_receipt_kinds.py` |
| FR-06 | SL-05, SL-08 | SC-01, journey 1 (SC-13) | `-k "sc01 or journey"` |
| FR-07 | SL-05 | SC-01, SC-02 | `-k "sc01 or sc02"` |
| FR-08 | SL-05 | SC-03 | `-k sc03` |
| FR-09 | SL-05 (rows, lines), SL-06 (gift cards) | SC-04, SC-19 5–6, SC-27 | `-k "sc04 or sc19 or sc27"` |
| FR-10 | SL-09 | SC-14 | `test_document_v2_browser.py -k "kind or forms"` |
| FR-11 | SL-08, SL-09 | journey 2–5, SC-14 step 6 | `-k journey`, browser |
| FR-12 | SL-08 | journey 6–10, J-e, J-f | `-k journey` |
| FR-13 | SL-01, SL-05 | SC-11, SC-05 | `test_migrations.py -k document_forms` |
| FR-14 | SL-03 (mechanism), SL-04, SL-05 | SC-08, SC-26 | `-k sc08`, `test_statement_forms.py -k sc26` |
| FR-15 | SL-05 | SC-12 | `test_receipt_segments.py -k kind` |
| FR-16 | SL-02 | SC-15, journey 1 | `test_paystub_forms.py -k version`. SL-05 adds `test_receipt_kinds.py -k version` |
| FR-17 | SL-10 | SC-16 | review |
| FR-18 | SL-08 | SC-18 (18a) | `-k sc18` |
| FR-19 | SL-07, SL-09 | SC-19, SC-21, SC-22, SC-23, SC-27 | as listed |
| FR-20 | SL-02 (labels), SL-03 (rest), SL-09 (shown) | SC-21, SC-14 | `test_paystub_forms.py -k sc21` |
| FR-21 | SL-03, SL-07 (traces) | SC-21 (21a–21c) | `-k sc21` |
| FR-22 | SL-02 | SC-20 a–h | `-k sc20` |
| FR-23 | SL-02 | SC-20 e and follow-on | `-k sc20` |
| FR-24 | SL-02 (characterization), SL-10 (eval) | SC-20 characterization, SC-17 | `-k sc20_e` before and after, `test_eval_tasks.py` |
| FR-25 | SL-04 | SC-22 (22b) | `test_statement_forms.py -k sc22` |
| FR-26 | SL-04, SL-07 | SC-22 (22a, 22c) | `-k sc22` |
| FR-27 | SL-04 | SC-23 | `-k sc23` |
| FR-28 | SL-04, SL-07 | SC-23 (23a, 23b) | `-k sc23` |
| FR-29 | SL-04, SL-06 | SC-24, SC-27 | `-k sc24`, `-k sc27` |
| FR-30 | SL-03, SL-04, SL-05 | SC-04, SC-21, SC-22, SC-25 | `-k sc25` in both files |

| SC | Slice | SC | Slice | SC | Slice |
|---|---|---|---|---|---|
| SC-01 | SL-05 | SC-10 | SL-08 | SC-19 | SL-07 (+ step 8 SL-09) |
| SC-02 | SL-05 | SC-11 | SL-01 | SC-20 | SL-02 |
| SC-03 | SL-05 | SC-12 | SL-05 | SC-21 | SL-03, SL-07 |
| SC-04 | SL-05, SL-06 | SC-13 | SL-08 | SC-22 | SL-04, SL-07 |
| SC-05 | SL-05 | SC-14 | SL-09 | SC-23 | SL-04, SL-07 |
| SC-06 | SL-05 | SC-15 | SL-02 | SC-24 | SL-04 |
| SC-07 | SL-05 | SC-16 | SL-10 | SC-25 | SL-03, SL-04 |
| SC-08 | SL-05 | SC-17 | SL-10 | SC-26 | SL-04 |
| SC-09 | SL-08 | SC-18 | SL-08 | SC-27 | SL-06, SL-07 |

## Test environments, data, stubs for nondeterministic components, final-state oracle
- **Environment:** a `tmp_path` library per test, built with `transcribe` and `extract` from `tests/test_extraction.py`
  and a `Manager` with `local_model`. The journey (SL-08) and SC-27 (SL-06/07) are each **one** stateful test function
  on one library, as the contract requires. The SC-20 variants are independent tests.
- **Data:** synthetic lines only, in `tests/document_forms_fixtures.py`, exactly as the contract prints them (fixture P,
  SC-01…SC-27). P-table uses the existing validated-table helper path. SC-12's two-page PDF is built with the pattern
  `tests/test_receipt_segments.py` already uses.
- **Model stub:**
  - Replies are keyed by schema name through `state["by_schema"]`, so tests don't depend on call order.
  - Request assertions read `local_model["requests"]`, filtering on `response_format.json_schema.name`.
  - Hold and release for SC-18 uses the existing `response_gate` (`model_server.py:88`).
  - The decision model isn't configured in SC-20 (`state` has no `decide`).
- **Final-state oracle** (asserted directly in SQLite, not through mocked functions):
  - The record row's columns. `json_extract`/`json_type` on the new `details_json` columns (C-money: `typeof`/`json_type`
    is `integer` for minor units, `text` for decimals).
  - Item, line and transaction rows.
  - `record_corrections`, `review_events` and `pending_details_json`.
  - `category_splits` sums and the health check report (`finance/health.py`).
  - `extraction_runs` status and count, and `parse_runs` count (C-noimg, unchanged).
  - C-cite: every stored new value's quote satisfies `mask(quote) in mask(line)`.
  - C-ids: a scan over every table except the transcription stores (`parse_runs`, `document_passages`,
    `document_passages_fts` and `document_passages_fts_*`), and every TEXT column, for the
    fixture identifiers (`445566`, `021000021`, `000123456789`, `6006491234565555`, `XXX-XX-1234`).
  - Spending, money in and balances through `FinanceTools`, the same functions the API uses.
- **Traces:** `GET /api/traces/{ref}` through the app's test client. Assertions cover `result`, `compared_with`,
  `reconciles` and input provenance, and that `trace.result` equals the record's `checks[].figure`.
- **Browser (SL-09):** the `test_document_v2_browser.py` fixture with seeded synthetic records. It checks for no console
  errors and no CSP violations. Screenshots use synthetic data only.
- **SC-18 setup (SL-08):**
  - The first reading is started through `Manager` and held by `response_gate`.
  - The second reading of the same document needs different options, or `enqueue` hands back the held run
    (`extraction.py:1442–1445` returns any queued or running row with the same options, whatever `force` says).
  - So the manager runs with `home_currency="USD"`, and the second reading is enqueued with `home_currency=None`. On
    SC-01's lines both resolve USD through the receipt fallback (`extraction.py:1701–1702`), so the published currency
    doesn't change.
  - It's then `submit`ted on the inference queue behind the held run, so its row is honestly `queued`. After step 3 the
    test asserts that the currency is still USD.
  - Release the gate, wait for both runs to succeed, then PATCH (expect one dining-form request).
  - 18a uses a second document's held reading.
- **Characterization (FR-24):** SL-02 runs `-k sc20_e` on the tree after SL-01, with none of SL-02's non-test changes
  applied (write the test first, run it, then implement), and records the failing output in `progress.yaml`.
- **Unit vs integration vs UI:**
  - Unit: `document_checks` functions, `this_period_guards`, `mask` and `scrub`, the kind-choice step.
  - Integration: extraction through the publish and ledger, corrections and undo, traces through the API.
  - UI: the browser tests.

## Escalations to the spec (resolved)
- **E-1 → spec D16.** SC-24 uses fixture P-sept (paid 2026-09-19). The paycheck counts on its own at net 1,912.34 in
  September, beside the bank's 2,500.00 payroll line.
- **E-2 → spec D17.** SC-27 keeps the unrelated −8.55 line, and October groceries are 12.10. The spec now agrees with
  the contract.
Both were amended and re-approved on 2026-10-18 (spec `7cf26b4ec7e9`).

## Risks, unresolved decisions, alternatives
- **Spec domain risks 1–7 (D-P6), not built:**
  - mixed-purpose receipts (the kind may flip between readings);
  - pump prepay or holds (a prepay could be read as the total);
  - two copies of one dining receipt (left to the existing duplicate handling);
  - prices with a 9/10 cent, litres, or no unit (FR-07 is skipped when the unit is ambiguous);
  - EBT/SNAP sensitivity in family routing and donations (only the tender type is stored, and no routing note is
    added);
  - combined statements (the summary check may compare different accounts' totals);
  - negative pay lines. FR-22(b) compares magnitudes, so retro pay can't trip it wrongly. A negative current line has
    no special rule.
  SL-10 lists each one in `docs/open-work.md`.
- **False positives in FR-22(a):** an earnings line labelled "Salary", or a single line printing "GROSS 2,500.00 YTD
  32,500.00", is rejected and goes to review. This errs toward review, matching the spec's invariant, and SL-10
  documents it.
- **Masking scope (D-P5):** only identifier fields, new details and their parts of `result_json` are masked. A full
  account or card number that a model quotes inside an item row's citation would stay (product codes look the same).
  No spec scenario covers it, so it's noted rather than built.
- **Gift card on a return:** a receipt whose `effective_receipt_direction` is `return` gets the issue "Gift card on a
  return isn't handled; check the amount." and counts its signed printed total. Exchanges (mixed-sign lines, which
  include any receipt with a savings row) have a positive total, so they're sales. SC-04 asserts that its
  exchange-labelled receipt counts 355 with no such issue, and SL-06's direction variant asserts −855.
- **Existing tests that may move:**
  - pay stub suites (FR-22 guards on their fixtures, per the assumption above);
  - the page-parity loop in `tests/test_ui_parity.py:114`, which asserts `reconciles` for every figure on a page. It
    doesn't cover the document page today. If it's extended to the document page, the check refs must be excluded,
    because they can fail by design.
- **FR-18 batch window** (see "Error handling"): a document in a running batch, before its extraction row exists, isn't
  refused. The result is safe.
- **Family copies** show the amount paid only, not the printed total or the gift card (`record_payload` doesn't carry
  details). What counts is correct.
- **Grocery item details on a reviewed receipt** aren't proposed or applied (pending covers summary details only, see
  "Kind change").
  Anything else that changes is reported in `progress.yaml`, not silently re-stubbed.
- **`reconciles` meaning:** for the seven check refs it's the check's outcome (FR-19), not the steps' sum.
  `docs/ui.md` records the exception.
- **Untested here:** live-model accuracy (U1, evals only), and the user's own failing paystub (G6/U2, the user runs it
  and shares only `summary.json`). SC-16 is by review.
- **New dependencies:** none.
- **Alternatives considered:**
  - one extra "details" call per document instead of folding fields into the kind's form (rejected by A1 and D2's
    no-extra-call intent);
  - storing details in typed columns (rejected: about 40 nullable columns across four tables, and FR-14's "none
    partially stored" is simpler as one JSON write);
  - a `paid_minor` column (rejected, see D-P1).
