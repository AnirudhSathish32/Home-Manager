# Receipt items: tax shared by its printed tax code — implementation plan
Spec: specs/receipt-tax-codes/spec.md (+ specs/receipt-tax-codes/test-contract.md)
Spec sha256: cb0c4c79db2067d9261f2cda498281ca7c8ac70c10f1a926b3eefabdf2b5dcb6
Review-Risk: HIGH
Review-Risk-Rationale: It changes how a receipt's tax is divided into stored category shares (financial correctness), adds a
migration, changes the reading schema and prompt, and must leave every existing receipt's shares exactly as they are.

<!-- Approval lives in approvals/receipt-tax-codes.json, bound to this file's hash. No Status line.
     Execution progress goes in plans/receipt-tax-codes/progress.yaml, never in this file. -->

Size note: the spec has 21 FRs, past plan-feature's ~10. The user split the joint spec once (D2) and chose to plan this
half whole (2026-11-01). Reading and sharing depend on each other, so a further split would leave stored fields nothing
uses. The plan keeps 5 slices.

## Verified repository integration points
All read at HEAD `3f3225b` on `reorganize-packages` (`receipt-item-table` built and reviewed), 2026-11-01. The spec's
line numbers predate that work. The ones below are current.

| Where | What it does today | Used for |
|---|---|---|
| `documents/extraction.py:45` `EXTRACTION_VERSION = "typed-extraction-v32-table-engine"` | Run reuse key. | bumped to v33 (SL-03) |
| `extraction.py:56` `HEADERS["receipt"]` (`merchant … tax … return_marker`); `:463-484` `DETAIL_FIELDS`, `HEADER_MODELS` built with `create_model`; `:487-490` `KIND_FIELDS`, `RECEIPT_FORMS` (each kind's form subclasses `HEADER_MODELS["receipt"]`) | Receipt summary forms. A field added to `DETAIL_FIELDS["receipt"]` reaches every receipt form, but not bills (`HEADERS["bill"]`). | `tax_lines`, `tax_legend` |
| `extraction.py:291-301` `Item` (`taxed: bool \| None`), `:303` `GroceryItem(Item)`; `:542` `Items`; `:491` `GroceryItems` | Item rows. | `tax_code` |
| `extraction.py:314-320` `Tender` | A cited list entry in a receipt summary. | the model for `TaxLine`/`TaxCodeMeaning` |
| `extraction.py:527-533` `NEW_FIELDS`, `:1569` `base_answer`, `:1600` `plain` | When only fields that document forms added fail validation twice, they are dropped and the rest is kept. `details=False` then reaches `normalize` (`:3221`). | the new fields join `NEW_FIELDS` |
| `extraction.py:554` `SCHEMA_FIELDS` | Every schema model's field names. | new models added |
| `extraction.py:127` `LABELS["receipt"]` | Summary instructions. | `tax_lines`/`tax_legend` instructions |
| `extraction.py:2978-2986` item row instructions (the `taxed:` sentence at `:2982-2984`) | Prompts F/E-style marks as untaxed today. | FR-24 rewording; `tax_code` instruction |
| `extraction.py:1677` `normalize`; receipt branch `:1724-1760` (items `:1729-1742`, `sign_return` `:1743`, `receipt_details` `:1744`) | Items are built with `taxed` straight from the model. `sign_return` negates every receipt amount on a whole return (`:1650-1657`). | tax-code checks and flag derivation (SL-03) |
| `finance/ledger.py:704-751` `publish_receipt` | Writes the receipt. When `written`: evidence, `_replace_items`, corrections, `refresh_paid`, delete+insert of `receipt_rewards` with `locator_json` (`:747-750`), `refresh_splits`. When not written (reviewed), nothing changes. | `tax_source`, `receipt_tax_lines` (SL-01) |
| `ledger.py:951-1017` `_replace_items` | UPDATE/INSERT column lists for `receipt_items` (`taxed` at `:990`). Kept (worked-on) items keep their old columns. | `tax_code` column |
| `ledger.py:1055-1103` `refresh_splits`, `split_inputs` (items `SELECT id,description,line_total_minor,discount_minor,taxed,category,member_id`), `shares` (calls `splits.allocate` three ways, then `scale`/`by_line`) | The only path that writes `category_splits`. | the per-code rule (SL-02) |
| `finance/reconcile.py:214` `self.ledger.refresh_splits(db)` | **Every reconciliation run rebuilds every receipt's splits.** | why FR-13 needs `tax_source` (Decisions) |
| `finance/splits.py:50-55` `tax_basis(items)`, `:91-92` `allocate` spreads `tax` over it | Today's taxed-items rule, shared with the item table's "with tax" note. | generalized to `tax_parts` (SL-02) |
| `ledger.py:255-291` `item_table` (`tax_included` from `basis_by_id`); `:1808-1813` in `record()` | The "with tax" note. | per-code note (FR-26) |
| `ledger.py:1781-1930` `Ledger.record` | Receipt items, shares, `receipt_rewards` (`:1842`, line ids from `locator_json`), and the final display loop over `value`, items, transactions, lines, splits (`:1878-1880`). | `tax_lines`, `tax_issues`, `tax_code` in the API |
| `ledger.py:166-169` `CORRECTABLE["receipt"]["tax"] = ("tax_minor","receipt_money","Tax")`; `:2300-2325` `correct` | A Tax correction updates only `tax_minor` (sign by direction), then `refresh_splits`. Total, subtotal and tip are untouched. | FR-17, FR-28 hold through `refresh_splits` |
| `finance/traces.py:190-212` split trace | `ledger.split_inputs` then `ledger.shares` with a recorder. Its description says "the tax shared by amount". | description names "by tax code" when used |
| `app/static/receipt.js:294-310` `RECEIPT_COLUMNS`, `receiptCell` (Paid note from `row.table.tax_included`); `:366-386` footer rows | The `receipt-item-table` FR-01 – FR-07 table. | FR-19, FR-26 (SL-04) |
| `app/static/document_v2.js:436,824` `doc2Why(record.issues)` (shown only while undecided) | Reasons a record needs review. | tax issues are shown under the table instead (Decisions) |
| `library/migrations/074_account_type_names.sql` (`PRAGMA user_version=74`); `050_strict_tables.sql:976-987` `receipt_rewards` (STRICT, `locator_json`) | Migration conventions. | `075_receipt_tax_codes.sql` |
| `tests/receipt_item_fixtures.py` (R, RA, D, G, N, `item`, `amount_on`, `receipt_replies` from `document_forms_fixtures`); `tests/test_receipt_items_browser.py`; `tests/test_receipt_kinds.py:52` `read_receipt`; `tests/test_spending_splits.py:60-80` `source_of`, `statement`, `:88` charge matching via `Reconciler.reconcile_statement`; `tests/test_migrations.py:261` per-migration test | Test helpers. | all slices |
| `evals/tasks/receipt_kinds.py` (`make_case`, `reader`), registered in `evals/tasks/__init__.py:25,34`; `tests/test_eval_tasks.py` | Eval task pattern. | the FR-24 eval cases |

## Architecture, contracts, data flow and decisions

### Stored data (SL-01, migration `075_receipt_tax_codes.sql`)
```
ALTER TABLE receipt_items ADD COLUMN tax_code TEXT;   -- as printed beside the price ("BF"), NULL when none
ALTER TABLE receipts ADD COLUMN tax_source TEXT CHECK (tax_source IS NULL OR tax_source IN ('tax_lines','legend','printed'));
CREATE TABLE receipt_tax_lines (
    id INTEGER PRIMARY KEY,
    receipt_id INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,                 -- printed order
    code TEXT NOT NULL,                        -- normalized: upper case, no spaces ("B")
    rate_text TEXT,                            -- as printed ("7.75000"), NULL when none
    taxable_minor INTEGER CHECK (taxable_minor IS NULL OR typeof(taxable_minor)='integer'),   -- magnitude
    amount_minor INTEGER CHECK (amount_minor IS NULL OR typeof(amount_minor)='integer'),      -- magnitude; NULL = unreadable
    locator_json TEXT NOT NULL,
    created_at TEXT, updated_at TEXT,
    UNIQUE(receipt_id, position)
) STRICT;
PRAGMA user_version=75;
```
- **`tax_source`** records which rule a reading set up:
  - `tax_lines`: per-code tax lines are stored.
  - `legend`: the receipt printed a code legend and no per-code amounts.
  - `printed`: read by this version with neither.
  - `NULL`: every receipt recorded before this change, every bill, and any record published without a reading
    (family deliveries, tests).
- **Why it's needed (FR-13):** `Reconciler.run` rebuilds every receipt's splits (`reconcile.py:214`). A rule change
  that applied to old receipts would rewrite their shares on the next reconciliation. Old receipts and bills get
  `NULL`, which keeps today's rule exactly, so their `category_splits` can't change.
- **Tax-line amounts are stored as magnitudes.** The receipt's own tax carries the sign. A whole return
  (`sign_return`) or a sale/return correction (`set_receipt_direction`) flips `tax_minor` and the item lines but never
  touches tax lines. The rule and the API apply `sign(tax_minor)`.
- **Writes:** `publish_receipt` writes `tax_source` with the receipt. When `written`, it deletes and re-inserts
  `receipt_tax_lines` exactly like `receipt_rewards`, so the same reading twice gives no duplicates (FR-12).
  `_replace_items` writes `tax_code`. A reviewed record (not `written`) changes nothing, as today. A failed reading
  publishes nothing, so earlier codes, lines and splits stay.

### Reading (SL-03)
New schema, all optional, all in `NEW_FIELDS` so a reading whose only failures are these fields drops them (FR-14 of
document forms):
```
Item.tax_code: str | None = Field(default=None, max_length=10,
    description="The tax code printed beside the item's price exactly as printed (BF, T, A, N), or null.")
class TaxLine(StrictModel):          # one printed per-code tax line
    code: str | None = Field(max_length=10)       # the code the line is for ("T" in "T = GA TAX ..."), null when none is printed
    rate: str | None = Field(max_length=20)       # as printed ("7.75000")
    taxable_amount: str | None = Field(max_length=50)
    amount: str | None = Field(max_length=50)
    evidence: list[EvidenceQuote] = Field(min_length=1, max_length=5)
class TaxCodeMeaning(StrictModel):   # a printed legend entry
    code: str = Field(min_length=1, max_length=10); taxed: bool; evidence: list[EvidenceQuote] = Field(min_length=1, max_length=5)
DETAIL_FIELDS["receipt"] = {"tax_lines": (list[TaxLine], Field(default_factory=list, max_length=20)),
                            "tax_legend": (list[TaxCodeMeaning], Field(default_factory=list, max_length=20))}
NEW_FIELDS gains: "ReceiptSummary" (the general receipt's form, which isn't in RECEIPT_FORMS) -> {"tax_lines", "tax_legend"};
    each Receipt<Kind>Summary's set -> + {"tax_lines", "tax_legend"}; "Items" -> {"tax_code"}; "GroceryItems" -> + {"tax_code"}
```
Every new field has a default (`StrictModel` forbids extras and makes a field without a default required,
`receipt_schema.py:14-15`). Existing stubs and earlier answers, which carry none of these fields, therefore still
validate.
- **Instructions.** `LABELS["receipt"]` explains `tax_lines` (only lines that print tax for one code, never a single
  TAX line or a total) and `tax_legend` (only printed tax meanings such as "T = TAXABLE" or "N = NON-TAXABLE"; a
  food-stamp, EBT or SNAP meaning such as "F = FOOD STAMP" is never an entry).
- **FR-24 rewording.** The item `taxed:` sentence becomes: "taxed: true or false only when the receipt says what the item's
  code means (a legend such as T = TAXABLE, or a tax line printed for its code); a food-stamp or EBT mark such as F or E
  never means untaxed on its own; otherwise null." Plus a `tax_code:` sentence. `Item.taxed`'s own Field description
  (`extraction.py:298`, sent with the schema) is reworded to the same rule.

`normalize` receipt branch, after items and before `sign_return`, a new `tax_codes(record, header, rows, line_text,
issues, currency, details)`:

1. **Codes:** each item's `tax_code` (whitespace collapsed, upper case) is kept only when it is printed in one of the
   item's citations, else dropped with the issue "Item n tax code was not printed where it was cited and was left
   out." (FR-08).
2. **Tax lines:** each needs a code printed in its citation. Amount, rate and taxable amount are each kept only when
   printed in a citation. An amount that can't be read is kept as `None` (spec Errors). **If any line has no code**,
   no tax lines are kept and the receipt is read as having one tax total (FR-21; also a single TAX line, FR-09).
3. **Legend entries** need their code printed in their citation.
4. **Flags and `tax_source`:**
   - With kept tax lines → `tax_source='tax_lines'`, and each item's `taxed` is derived (FR-11, FR-27):
     - `1` when it belongs to exactly one line code (FR-10: the line code is a substring of the item's code, and no
       other line code is) whose summed amount is > 0, or whose amount couldn't be read (P7);
     - `0` when it belongs to none (an empty code, or a code like "BT" that contains two), or only to a line whose
       amount is 0.00 (FR-11's "above zero");
     - the model's `taxed` is ignored.
   - Else with legend entries → `tax_source='legend'`. `taxed` = the meaning of the one legend code the item's code
     contains (several codes that all mean the same also count), else `None` (FR-22). A legend entry whose code isn't
     contained in any item code is ignored.
   - Else → `tax_source='printed'`. The model's `taxed` stays (FR-24).
5. With `details=False` (new fields failed), `tax_source='printed'` and none of the above is kept.

`EXTRACTION_VERSION` → `"typed-extraction-v33-tax-codes"`.

### The rule (SL-02, `finance/splits.py`)
```
def tax_parts(items, tax, tax_lines, source) -> TaxPlan
    TaxPlan = namedtuple(parts=[(amount, weights, code | None)], by_code: bool, issues: [str], codes: {item index: code})
```
`items` carry `tax_code`, `taxed` and amounts. `tax_lines` are `[(code, amount_minor | None)]` and `source` is the
receipt's `tax_source`.

- **No tax** (`tax` 0 or `None`) → no parts.
- **`source == 'tax_lines'` with lines:**
  - Lines are grouped by code and their amounts added (FR-23).
  - Membership follows FR-10 on non-empty item codes.
  - Every item with two line codes is named: "RUFFLES carries more than one tax line's code (B, T), so it got no share
    of either." Every non-empty code that matches no line is named: "… tax code N matches no tax line, so it got no
    tax line's share." (FR-18)
  - **Consistent** when every group amount is readable, `sum(groups) == abs(tax)`, every group has at least one member
    item (FR-16 "every tax line with an amount", read literally to include 0.00: P9), and every group with an amount
    > 0 has members whose `item_amount` weights sum ≠ 0.
  - Consistent → one part per group: `(sign(tax) × amount, [item_amount if member else 0], code)`, with `by_code=True`
    (FR-14).
  - Otherwise → fallback: one part `(tax, tax_basis(items), None)` using the stored, derived flags (FR-16, FR-27), plus
    the reason:
    - "The tax lines (X) don't add up to the tax (Y), so tax was shared across the taxed items."
    - "The T tax line has no items carrying its code, so tax was shared across the taxed items."
    - "The B tax line's amount couldn't be read, so tax was shared across the taxed items."
- **`source == 'printed'` and any item's `taxed` is `None`** → one part over every item's amount (FR-29).
- **Else** (`NULL`, `legend`, `printed` with every flag answered) → `(tax, tax_basis(items), None)`. This is exactly
  today's rule.

`allocate(..., tax_parts=None)` spreads each part with the existing `spread` (exact fractions, a zero weight sum goes
to an extra row as today). When `tax_parts` is `None` it keeps today's single `spread(tax, tax_basis(items))`. Discounts,
tip, charge difference and rounding are untouched (FR-15). Tax keeps today's weights (`item_amount`, line less its
own discount). The spec's "after any order-wide discount, as tax is today" is read as "as today". See Risks R-c.

`Ledger.split_inputs` adds `tax_code` to the items query and returns `receipt` as a dict with `tax_lines`
(`[(code, amount_minor)]` by position) and `tax_source`. `Ledger.shares` computes `tax_parts` once and passes it to every
`allocate` call. Charges, gift cards, other currencies, `scale` and `by_line` therefore follow unchanged (FR-15).
`traces.py` adds ", by tax code" to its description when `by_code`.

### API (SL-02, `Ledger.record`, receipts that are not bills)
- `record["tax_lines"]`: by printed position, each `{position, code, rate_display ("7.75%" from `format(Decimal(rate_text).normalize(), "f")`
  so "10.000" gives "10%", not "1E+1%"; `None` when it doesn't parse), taxable_minor, amount_minor (both signed like `tax_minor`), line_ids}`, with `display` from
  the final display loop (added to its row list).
- `record["tax_lines_used"]`: the plan's `by_code`.
- `record["tax_issues"]`: the plan's issues. They are also appended to `record["issues"]` (not stored), so the contract's
  C-issue holds. (The correction preview compares stored `validation_json` (`correction_preview.py:37`), so it doesn't
  list them. The spec doesn't ask it to.)
- **Items:** `tax_code` is the stored column. `item["table"]["tax_included"]` is true when some part with a non-zero
  amount gives the item a non-zero weight within a non-zero weight sum. That is the same condition as today's when
  there is one part. `item["table"]["tax_note"]` is `"with B tax"` when `by_code` and the item belongs to code B, else
  `"with tax"` when `tax_included`, else `None`.

### Page (SL-04)
- **Paid** shows `row.table.tax_note` in place of the fixed "with tax" (FR-26). A row with `tax_code` gets
  `tr.title = "Tax code BF"` (text, not money).
- **Footer (FR-19).** When `tax_lines_used`, the Tax row is followed by one row per tax line, sorted by code then
  position:
  - the label cell reads `"B · 7.75% on "` followed by `amount(taxable)` (parts left out when not printed);
  - the amount cell (`data-col="line_total"`) holds `amount(amount)`;
  - the actions cell holds `sourceButton(line_ids, find)`, with aria-label "Find B tax line".
  - The Tax row keeps its Correct button.
  - When lines are stored but not used, only the one Tax row shows, as today.
- **Issues.** `record.tax_issues` render under the table as `.item-warning` paragraphs, beside the existing "Doesn't add
  up" note, whatever the review status. At both `doc2Why` call sites (`document_v2.js:436,824`), the issues are filtered
  to those not in `tax_issues` before the length check, so a receipt whose only issues are tax issues shows no empty
  "why" block, and nothing shows twice.

### Decisions taken in the plan (each consistent with the spec; flagged for review)
- P1. Any uncoded tax line means the receipt has no per-code tax lines (FR-21 is silent on a mix).
- P2. An empty item code is untaxed on a receipt with tax lines but isn't named in an issue. FR-18 names codes that
  match no line, and an empty code isn't a printed code.
- P3. Issue amounts use the server's money text ("2.74 USD", `format_minor`), as every other issue does. The contract
  prints "$2.74". Tests assert the spec's sentence with the server's money text.
- P4. Tax issues are worked out on each read and never stored, so a Tax correction adds or clears them (FR-17). They
  don't send a receipt to review.
- P5. Footer tax lines are sorted by code, which matches FR-19's "B … T …" against the printed T-then-B order.
- P6. Family copies share tax as the sender's record does. `family_routing.record_payload` (`family_routing.py:254-266`)
  adds each item's `tax_code`, plus the receipt's `tax_source` and its tax lines in `publish_receipt`'s record shape
  (`{code, rate_text, taxable_minor, amount_minor, locator: {"family": True}}`). The member's copy is then published with
  the same rule. Spec Users name "family shares".
- P7. A tax line whose amount can't be read still marks its items taxed. The line is printed with their code, so tax
  was charged on them. The receipt then falls back (FR-16, unreadable amount counts as not adding up) and tax goes over
  every taxed item. Taking FR-11's "above zero" literally would leave the BF items untaxed and put all the tax on the
  filter, which is the reported bug. Flagged for the user.
- P9. A readable 0.00 tax line still needs an item carrying its code (FR-16 read literally). Otherwise the receipt falls
  back with "The N tax line has no items carrying its code…". Its members are untaxed (FR-11).
- P8. A worked-on item that a new reading no longer finds is kept with its earlier columns (`ledger.py:970`), including
  its old `tax_code` and `taxed`. On a `tax_lines` receipt that old code still takes part in membership. This is
  documented in `docs/money.md`, not changed.

## Error handling, idempotency and recovery
- A failed reading publishes nothing. Codes, lines, `tax_source` and splits stay (SC-08 b).
- The same reading twice: tax lines are deleted and re-inserted and items are matched by key, so there are no
  duplicates (SC-01 variant, SC-08 c).
- The migration only adds a column, a NULL column and an empty table. `apply_migrations` keeps its pre-upgrade copy
  and its rollback (`test_migrations.py:45-160`).
- Bad stored data never raises in `record()`. An unparseable `rate_text` shows as printed with "%" left out
  (`rate_display` `None`, and the page shows `rate_text`). An unreadable amount falls back with its issue.
- A restart changes nothing. Splits are rebuilt from stored values only.

## Privacy/security and migration impact
- One forward migration, 075, adding nullable columns and a STRICT table. Existing rows keep every value (SC-09).
- The extraction version bumps, so later readings don't reuse v32 runs. Old runs stay readable.
- Readings use the configured local model, as today. `scrubbed` masks every `NEW_FIELDS` name in saved run results
  (`extraction.py:1585-1586`), so the new fields are masked there too. That's harmless; no code change.
- No new dependencies. CSP: DOM nodes only.
- Tests use synthetic fixtures under `tmp_path`. The live-model eval is user-run. Nothing under P:\Finances,
  %LOCALAPPDATA%\HomeManager or P:\EvalCorpus is read.

## Vertical slices
| ID | FR/SC covered | Dependencies | Files/changes | Verification command / evidence |
|---|---|---|---|---|
| SL-01 | FR-12 (storage), FR-13; SC-09 | none | `library/migrations/075_receipt_tax_codes.sql`. `ledger.py`: `publish_receipt` writes `tax_source` and `receipt_tax_lines` (delete + insert when `written`); `_replace_items` writes `tax_code`; `record()` returns `tax_code`, `tax_lines` (signed, `rate_display`, `line_ids`) and `tax_source`. No producer yet. `finance/family_routing.py` `record_payload` carries `tax_code`, `tax_source` and the tax lines (P6); `tests/test_family_inbox.py` gains a delivery test: a receipt with two tax lines and codes delivered to a member's copy stores the same codes, lines, `tax_source` and (after SL-02) the same shares. `tests/test_migrations.py`: `test_075_…` (v74 rows by SQL: receipt + items + splits; after 075 every old column equal, `tax_code`/`tax_source` NULL, table empty). New `tests/test_receipt_tax_codes.py`: publish with tax lines through `Ledger.publish_receipt`, publish again (no duplicates), reopen the store (unchanged), a reviewed record isn't rewritten, and **SC-09**. | `.venv/bin/python -m pytest tests/test_migrations.py -k 075 -q`; `.venv/bin/python -m pytest tests/test_receipt_tax_codes.py -q`; `.venv/bin/python -m pytest tests/test_spending_splits.py tests/test_receipt_item_table.py tests/test_reextraction.py tests/test_bills_ledger.py tests/test_migrations.py tests/test_family_inbox.py tests/test_family_routing.py -q` |
| SL-02 | FR-14 – FR-18, FR-23, FR-27, FR-28, FR-29; SC-04 – SC-07, SC-10, SC-18 (rule and ledger level) | SL-01 | `finance/splits.py` `tax_parts`, `TaxPlan`, `allocate(tax_parts=)`. `ledger.py`: `split_inputs`, `shares`, `item_table` (`tax_note`), `record()` (`tax_lines_used`, `tax_issues`, issues appended). `traces.py` description. New `tests/test_splits_by_code.py`, no database, each case independent: R0's 445/4347/1400; SC-04's 450/4391/1361; SC-05's 454/4439/1299; SC-06's 429/4363/1400; SC-07's 449/4384/1359; SC-15's same-code sum; SC-18 and its all-answered variant; R0 with B's amount unreadable (flags 1, 1, 1 per P7 → fallback, 274 over 5918 → 449/4384/1359, issue "The B tax line's amount couldn't be read…"); a zero-weight line; a 0.00 line with no members (fallback, P9) and with a member (by code, member untaxed); `rate_display` for "7.75000", "10.000" and "abc"; a negative (return) tax; `source=None` equals today's `tax_basis` on the D, R and RA inputs. `tests/test_receipt_tax_codes.py` gains SC-07 through the public correction path (`manager.correct_record("receipt", id, {"tax": "3.00"})` (`app/manager.py:2189`), which also runs `reconciler.run("correction")` and so the full split rebuild; then `PATCH /api/finance/records/receipt/{id}` back to 2.74 through `TestClient`; total, subtotal and tip unchanged; issue added then cleared) and SC-10 (charge −61.92 matched via `statement` + `Reconciler.reconcile_statement` → 445/4347/1400; 50/50 share via a `record_shares` row and `refresh_splits` as `tests/test_family_inbox.py:64` does → 3096; a −57.00 EUR charge → sums 5700, each within 1 cent). The SL-01 family delivery test asserts the member's copy has 445/4347/1400. | `.venv/bin/python -m pytest tests/test_splits_by_code.py tests/test_receipt_tax_codes.py -q`; `.venv/bin/python -m pytest tests/test_spending_splits.py tests/test_receipt_item_table.py tests/test_traces.py tests/test_family_routing.py tests/test_family_inbox.py tests/test_health.py tests/test_returns.py tests/test_bills_ledger.py -q` (unchanged shares; shared receipts, returns and the ledger health check) |
| SL-03 | FR-08 – FR-11, FR-12 (reading), FR-21, FR-22, FR-24, FR-27 (flags); SC-01, SC-03 – SC-06, SC-08, SC-13 – SC-16, SC-18 end to end | SL-02 | `extraction.py`: `Item.tax_code`, `TaxLine`, `TaxCodeMeaning`, `DETAIL_FIELDS["receipt"]`, `NEW_FIELDS` (every receipt form, `Items`, `GroceryItems`), `SCHEMA_FIELDS`, `LABELS["receipt"]`, the item instructions (FR-24 sentence, `tax_code`), `tax_codes()` in `normalize`, `record["tax_source"]`, `record["tax_lines"]`, `EXTRACTION_VERSION` v33 (and `tests/test_table_engine_record.py:214-215`, which pins v32, becomes a `!=` check like `tests/test_receipt_kinds.py:328`). `ledger.publish_receipt` already stores them (SL-01). `tests/receipt_item_fixtures.py`: R0 (RA plus tax codes and the two tax lines) and the contract's variants as reply builders. `tests/test_receipt_tax_codes.py` gains `sc01` (with restart and second Record), `sc03`, `sc04`, `sc05`, `sc06`, `sc08` (+ b, c), `sc13`, `sc14`, `sc15`, `sc16` (prompt text asserted on `local_model["requests"]`), `sc18` (+ variant), and a `version` test, all through `read_receipt`. Two plan-level cases: (1) `new_fields_fail`: a general receipt (D's lines) and a grocery receipt (R0) whose summary answer carries an invalid `tax_lines` entry (no evidence) on both tries. The reading is kept with today's fields, `DETAILS_FAILED` in its notes, `tax_source='printed'`, no tax lines, and the shares of today's rule. (2) `legend_food_stamp`: SC-14's lines plus `F = FOOD STAMP`, with a stub legend holding only T and N. An item coded TF takes T's meaning (taxed). | `.venv/bin/python -m pytest tests/test_receipt_tax_codes.py tests/test_splits_by_code.py -q`; `.venv/bin/python -m pytest tests/test_receipt_kinds.py tests/test_table_engine_record.py tests/test_receipt_segments.py tests/test_extraction.py tests/test_reextraction.py tests/test_receipt_item_table.py tests/test_eval_tasks.py -q` (the schema and prompt change touches every receipt reading) |
| SL-04 | FR-19, FR-26; SC-19, SC-15 step 3 | SL-03 | `app/static/receipt.js` (`tax_note`, row `title`, footer tax-line rows with Find, `tax_issues` warnings), `app/static/document_v2.js` (at both `doc2Why` call sites, issues are filtered to those not in `tax_issues` before the length check). ui-ux-pro-max consulted before any CSS; no new tokens. `tests/test_receipt_items_browser.py` gains `sc19` (+ the SC-04 variant, which also asserts the issue shows once under the table as `.item-warning` and no `#doc2-why` block holds it) and `sc15_footer`, seeded with R0 and its variants through `record_document`, `home_currency` USD as the file's other seeds do. Each P-checks stored totals and shares by SQL first, checks footer geometry as SC-02 does, and asserts `NO_OVERFLOW` at 390/768/1440 px. | `RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_receipt_items_browser.py -q`; `RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_planned_bugfixes_browser.py tests/test_document_v2_browser.py -q`; synthetic before/after screenshots with `.claude/skills/ui-redesign/scripts/ui_shots.py` at desktop and phone widths |
| SL-05 | FR-20, FR-24 (eval) | SL-04 | `docs/money.md` "Item categories and splits" (tax codes, tax lines, FR-10 rule, fallback and reasons, a worked example on R as synthetic, `tax_source` and old receipts); `docs/documents.md` (the new reading fields); `docs/open-work.md` (OD-4 tax-line correction; P6 family copies); `docs/evals.md` (task row and run command). New `evals/tasks/receipt_tax_codes.py` (cases R and the SC-16 lines; graded on codes, line amounts within 0.01, and no BF item read as untaxed), registered in `evals/tasks/__init__.py`; `tests/test_eval_tasks.py` gains its case-shape and grading tests with a stub model. | `.venv/bin/python -m pytest tests/test_eval_tasks.py -k tax_codes -q`; FR-20 by review of the doc diff; headings unchanged except new subheadings |

## Requirements & scenarios coverage matrix
| FR | Slice | Tests |
|---|---|---|
| FR-08 | SL-03 | sc01 step 2 (codes BF, BF, T; cited) |
| FR-09 | SL-03 (read), SL-01 (store) | sc01 step 3; sc15 |
| FR-10 | SL-02, SL-03 | test_splits_by_code membership cases; sc01; sc06 |
| FR-11 | SL-03 | sc01 step 2 (flags 1 despite false); sc03; sc05 |
| FR-12 | SL-01, SL-03 | SL-01 republish/reopen; sc01 step 5 and second Record; sc08 (+ b, c) |
| FR-13 | SL-01 | test_075; sc09 (rebuild + `Reconciler.run` + reopen leave splits and flags identical) |
| FR-14 | SL-02 | test_splits_by_code R0; sc01 step 4 |
| FR-15 | SL-02 | sc10; existing split suites unchanged |
| FR-16 | SL-02 | sc04; sc05; unreadable-amount unit case |
| FR-17 | SL-02 | sc07 |
| FR-18 | SL-02 | sc05; sc06 |
| FR-19 | SL-04 | sc19; sc15_footer |
| FR-20 | SL-05 | review |
| FR-21 | SL-03 | sc13 |
| FR-22 | SL-03 | sc14 |
| FR-23 | SL-02, SL-03 | same-code unit case; sc15 |
| FR-24 | SL-03, SL-05 | sc16 (prompt + shares); eval |
| FR-26 | SL-02 (note), SL-04 | sc19 steps 1–2 |
| FR-27 | SL-03 (flags), SL-02 | sc04; sc07 |
| FR-28 | SL-02 | sc07 step 1 |
| FR-29 | SL-02, SL-03 | sc18 (+ variant); unit case |

| SC | Slice | Test |
|---|---|---|
| SC-01 | SL-03 | `test_receipt_tax_codes.py::test_sc01_records_codes_lines_and_shares_by_code` |
| SC-03 | SL-03 | `::test_sc03_one_tax_line_shares_as_today` |
| SC-04, SC-05, SC-06 | SL-03 (end to end), SL-02 (rule) | `::test_sc04…`, `::test_sc05…`, `::test_sc06…`; unit cases |
| SC-07 | SL-02 | `::test_sc07_correcting_tax_falls_back_and_back` |
| SC-08 | SL-03 | `::test_sc08_extract_again…` (+ b, c) |
| SC-09 | SL-01 | `::test_sc09_upgrade_keeps_existing_receipts`; `test_migrations.py::test_075…` |
| SC-10 | SL-02 | `::test_sc10_charges_shares_and_currencies_stay_exact` |
| SC-13 – SC-16, SC-18 | SL-03 | `::test_sc13…` – `::test_sc18…` |
| SC-15 step 3, SC-19 | SL-04 | `test_receipt_items_browser.py::test_sc15_footer_three_tax_lines`, `::test_sc19_tax_lines_and_codes` |

## Test environments, data, stubs for nondeterministic components, final-state oracle
- **Fixtures.** `tests/receipt_item_fixtures.py` gains:
  - `r0_replies(**changes)`: R0 per the contract, with RA's summary and items plus `tax_code` per item and `tax_lines`
    citing `T = GA TAX…` and `B = GA TAX…`;
  - keyword variants for SC-04 (tax 2.84, total 62.02), SC-05 (filter code empty), SC-06 (Ruffles BT) and SC-15 (B
    split into two cited lines; the fixture prints two B lines);
  - R1 for SC-08;
  - SC-13's, SC-14's and SC-16/SC-18's line lists and replies;
  - SC-08 b's invalid answer (an item with no evidence).
  Every code, line and legend entry cites its fixture line with `document_forms_fixtures.cite`.
- **Stubs.** `local_model` by schema name (`read_receipt`); `document_server(seed=)` with the fake model server for
  browser tests. No live model in pytest.
- **Oracles** are independent of the code under test:
  - **P-checks** by SQL first: subtotal, tax and total.
  - **Shares:** `category_splits` with `transaction_id IS NULL`, per item by position, asserted against the contract's
    hand-worked numbers, with C-sum.
  - **Final state:** row counts of `receipt_tax_lines`, `receipt_items.tax_code`/`taxed` and `receipts.tax_source` by
    SQL.
  - **C-cited:** every stored tax line's `locator_json` line ids, and each coded item's evidence-link line ids, equal
    the fixture line ids. In the browser, Find highlights `#doc2-viewer .sv-line.selected` with that text.
  - **C-issue:** asserted on `ledger.record("receipt", id)["issues"]` and `["tax_issues"]`.
- **SC-09 oracle.** The contract asks for a library at the pre-feature migration filled through Ledger paths, which
  today's code can't write once 075 exists. Two independent checks cover it:
  - `test_075` builds a v74 database by SQL, applies 075, and compares every pre-existing column of `receipts`,
    `receipt_items` and `category_splits`.
  - `sc09` publishes D and R the old way (`tax_source NULL`, no codes, R's flags filter 1, BF 0) through
    `Ledger.publish_receipt`. These are exactly the rows 075 leaves. It snapshots the splits and flags, runs
    `refresh_splits(db)`, `Reconciler.run`, a store reopen and `check_ledger`, then asserts everything identical
    (R stays 429/4190/1573).

## Risks, unresolved decisions, alternatives
- **R-a Old receipts' shares** (FR-13). `Reconciler.run` rebuilds all splits. Mitigation: the `tax_source NULL` path is
  today's expression, unit-tested against `tax_basis`, plus `sc09`'s full rebuild check and the unchanged existing
  split suites.
- **R-b The reading schema grows** for every receipt kind. A model failing on the new fields could lose the reading.
  Mitigation: `NEW_FIELDS` drops them on their own (FR-14 of document forms), and the receipt-kind and document-form
  suites run in SL-03.
- **R-c Tax weights.** Today's code weighs tax by `item_amount` (`splits.py:89-92`). The order-wide discount is spread
  in proportion to those same amounts, so within any group the weights before and after it are proportional. Both
  readings of FR-15 therefore give identical shares (except when the items add up to zero, where `share` is `None`
  either way). The plan keeps today's weights.
- **R-d Issue money text** (P3) and **footer order** (P5) read the contract's illustrations as illustrations.
- **R-e Live-model behavior** of the new fields and the reworded `taxed` sentence is only measured by the user-run eval.
- **Alternative rejected:** storing tax lines in `details_json`. That is per receipt kind (`merged_details`), so a kind
  change would hide them. Rewards' own table is the precedent.
- **Alternative rejected:** deriving flags at split time from codes. Stored flags keep FR-27's fallback and the
  existing `taxed` readers (item table, traces) unchanged.

## Final verification
After SL-05, once:
- `.venv/bin/python -m pytest -q`, compared test by test against the pre-feature baseline recorded at SL-01's start
  (`receipt-item-table`'s last run: 54 failed, 20 errors, all pre-existing).
- `RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_receipt_items_browser.py tests/test_planned_bugfixes_browser.py tests/test_document_v2_browser.py -q`.
- `.venv/bin/ruff check src tests`.
