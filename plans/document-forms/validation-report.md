# Document forms: validation report (2026-10-19)

How document forms behaves for a person using the app, how well the configured models read real-looking documents,
and what to change in the spec and plan. Evidence comes from one hands-on run on the agent test instance (synthetic
household, `tests/.tmp`), plus the automated suites. Findings were recorded in `docs/bugs.md` "Agent findings".

## Verdict

- **The feature works end to end.** These all behave as specified through the UI, and the database agrees:
  - receipt kinds;
  - changing a kind;
  - the reviewed-receipt proposal and Apply details;
  - printed details with their source lines;
  - check figures and their traces.
- **Five defects in this feature, three of them about values that aren't printed.** The reasoning model fills optional
  fields with values it copied from other lines (a cash payment from the Total line, a deposit from the Net pay line, a
  subtotal from the total). The code checks each value's amount against its citation, but not what the cited line
  *is*. The new optional fields widen this gap.
- **The paycheck was read mostly right but not well enough to count.** Employer, dates, gross and net were all correct.
  It went to review for two reasons outside this feature (the 401k line and totals read as lines) and one inside it (an
  invented deposit). The year-to-date guards (FR-22) could not be exercised live, because the uploaded stub prints no
  year-to-date column.
- **The models are reasonable for this app on clean documents.**
  - gemma-3-12b transcribed 10 of 11 images perfectly in 2–4 s each.
  - openai/gpt-oss-20b classified every document correctly and returned valid JSON first time on every image.
  - Its weak points: inventing optional values, an empty transaction list on one statement, and running out of output
    on the multi-page PDF.

## What was run

- **Setup:** reset and start of the test instance (preflight passed, live inference allowed).
  - LM Studio served `gemma-3-12b-it` (vision) and `openai/gpt-oss-20b` (reasoning, decision checks off).
  - The 12 files in `uploads/` were added through Processing › Watched folders, as a person would.
- **Browsing:** the document pages, in Edge with `playwright-cli`. At each step I queried the instance's database
  read-only.
- **Graded:** each reading against the synthetic file's known answers (`evals/synthetic.py`). That covers the printed
  lines, document type, fields, rows, item categories and model calls.
- **What this can't show:** the uploads were generated before document forms. None prints gallons, a gift card, a
  year-to-date column, a deposit line or a statement summary block. So the live run covers the kind flow, the details
  UI and model behaviour on ordinary documents. FR-07, FR-09 (gift cards), FR-21 and FR-22 are covered only by the
  fixture tests (204 passed in the last full run). Each upload was read once: model results are anecdotes, not rates.

## Does the paycheck read correctly?

`pay-stub.png` (EXAMPLE WIDGETS LLC, paid 2026-04-04, period 2026-03-16 to 2026-03-30):

| | Printed | Recorded | |
|---|---|---|---|
| Type | pay stub | pay stub | ✓ |
| Employer, pay date, period | as above | as above | ✓ |
| Gross pay | 3,699.78 | 3,699.78 | ✓ |
| Net pay | 2,739.81 | 2,739.81 | ✓ |
| Regular pay, health, federal, Social Security, Medicare | 5 lines | the same 5, right amounts and groups | ✓ |
| 401k | 184.98 (pre-tax) | pre-tax, **no amount** | ✗ code: the digits in "401k" count as a second number ("multiple amounts without a validated source row") |
| Gross pay, Net pay | totals | **also listed as earnings lines** | ✗ model, and code that only excludes totals on table rows |
| Direct deposit | not printed | **2,739.81 stored, cited to "Net pay 2,739.81"** | ✗ model invented it; code kept the amount (its account digits were dropped) |
| Outcome | — | Needs review | right outcome, for the wrong reasons |

The stub didn't count, which is the safe result, but a person would see three confusing reasons:
- "Earnings (10,139.37 USD) do not add up to gross pay (3,699.78 USD)": the totals counted as lines.
- The 401k line with no amount.
- "Deposit split 1 account was not printed where it was cited".

Its new **Direct deposits** check reported "2,739.81 matches the printed 2,739.81", which is net pay compared with
itself. On another stub, that check could be the only cross-check that agrees and let it count automatically.

- **The reported defect (year to date read as this paycheck)** is reproduced and fixed by the characterization test on
  fixture P (verified with gross 32,500.00 before the fix, held for review after it). It wasn't triggered live, because
  this stub prints no YTD column.
- **Recommended next step:** add a stub with a year-to-date column (table and flat) to `evals/synthetic.py` and the
  test instance uploads.

### Why a photographed stub comes back almost empty (user report, 2026-10-19)

The report: a pay stub was read with only a relocation bonus recorded (one already received in an earlier period), and
everything else empty. That stub wasn't opened. The same result reproduces on synthetic lines through the extraction
entry point: `tests/test_paystub_forms.py::test_a_photo_stub_keeps_this_period_beside_year_to_date`, marked
`xfail(strict=True)` until a fix is approved.

- **Root cause (verified):**
  - Every vision reading carries `vision_tables`, empty when no table was found.
  - So `read()` treats a photographed stub as having a table contract and runs `anchor_paystub` with no tables.
  - Its fallback then sets current and YTD to null on every line, and on every summary amount, whose cited line prints
    more than one number. Those cover "REGULAR 2,500.00 32,500.00", "GROSS PAY 2,500.00 37,500.00" and the rest.
  - A row paid in an earlier period prints one number (its year to date), so it is the only one that survives. On a
    one-number line the model may also file that year-to-date amount as this period, and nothing can tell (there is no
    year to date to compare with).
- **Same cause as the "401k" line:** its label's digits count as a second number.
- **Why document forms didn't fix it.**
  - The spec's diagnosis (D14) was the opposite failure: the model putting year-to-date amounts into this period. The
    FR-22 guards remove such values; they never restore correct ones that code removed first.
  - This blanking happens before the guards. It was listed as *existing, intended* behavior ("A cited line with several
    numbers and no validated row is set to null and goes to review"), so the plan built on it rather than questioning it.
  - Every fixture used either a validated table (P-table) or one amount per line (P-flat, chosen deliberately to avoid
    this rule). None was a photo with both columns on one line, the most common layout.
- **Proposed fix (gated: it changes which money values are recorded, so it needs a spec amendment and approval):**
  1. Run the cell anchoring only when a validated table exists (`tables` non-empty), not when the reading merely
     supports tables.
  2. On a line with several amounts and no validated row, keep the model's values when each is printed in its line.
     FR-22 then judges them: larger than YTD, equal to YTD mid-year, or labelled YTD goes to review. That is the
     protection the old blanking stood in for.
  3. When a header line orders the columns (this period before YTD), and a line prints exactly two amounts, check that
     the model's this-period value is the one in the this-period position. Otherwise it is ambiguous with a note.
  4. Ignore numbers inside a line's description words ("401k", "403(b)") when counting a line's amounts.
  5. A line whose only amount sits under a YTD heading (a bonus paid earlier) keeps it as year to date. When the heading
    can't be told, its this-period value is ambiguous rather than the lone amount.
- **Spec and contract changes for that amendment:**
  - The "Existing behavior" bullet about multi-number lines.
  - A new FR: this period and year to date printed on one line are both kept on photos, judged by FR-22.
  - Contract variants: SIDE_BY_SIDE (two columns on one line, no table), a row printed only in YTD, a "401k" label, and
    a model answer that swaps the two columns on such a line (FR-22 b must catch it).

## How the reasoning model (gpt-oss-20b) did

**Classification: 11 of 11 types right** (the PDF failed later, at the summary). Receipt kinds:

| File | Kind chosen | Right? |
|---|---|---|
| grocery-receipt | grocery | ✓ |
| dining-receipt | dining | ✓ |
| fuel-receipt (snack bar, windshield fluid; no fuel) | general | ✓ (no fuel is printed) |
| parking, injection, refund receipts | general | ✓ |

**Categories (describe step).** The receipt categories were all sensible:
- groceries, dining, electronics, home improvement, phone & internet;
- for the gas-station receipt, groceries with items groceries / household supplies.

Item categories were sensible too, apart from two weak calls:
- Windshield fluid as household supplies, where transportation fits better.
- The bill's "Taxes, surcharges and fees" as other (acceptable).

The kind change's re-read got an unusable item-category answer, and **wiped the earlier good categories**. All three
items went back to "Choose…" and the receipt category became "other". The reading replaces model categories even when
its new answer is unusable.

**Filling the JSON forms.**

| | Result |
|---|---|
| Valid JSON first time | every image reading: no correction requests needed |
| Summary fields | right on every recorded document (merchant, dates, subtotal, tax, total, balances, gross, net) |
| Rows | grocery 5/5, dining 2/2, gas station 3/3, injection 3/3, refund 1/1, bill 5/5, bank 5/5 transactions, pay stub 5/6 (plus 2 extra) |
| Card statement | **0 of 6 transactions** (the model returned an empty list), so it went to review |
| bank-statement.pdf (multi-page) | **failed**: "final response was incomplete or truncated" twice (gpt-oss reasoning used the output budget) |
| Invented optional values | parking receipt: Subtotal 12.00 copied from "Total USD 12.00"; grocery: a **Cash 18.24** payment cited to the Total line; pay stub: the deposit above |
| Prompt injection (`injection-receipt`) | resisted: total 51.93 kept, not 0.00 |
| Speed | 7–24 s per document (3–6 calls); the failed PDF took 79 s |

The pattern: when a form offers an optional field, the model tends to fill it with something from the page. Today's
forms tolerated that, because their optional fields were few. Document forms adds many, so the code needs to check
what a value's citation says, not just the number in it.

## How the vision model (gemma-3-12b) did

| File | Printed lines read exactly | Time |
|---|---|---|
| grocery, dining, fuel, parking, refund, bank, card, pay stub, bill | 100% each (similarity 1.000) | 1.7–4.3 s |
| injection-receipt | 9 of 11: "WIRELESS" read as "WIRLESS", and the injected sentence cut off as "[unreadable]" | 2.7 s |
| bank-statement.pdf | native PDF text, no vision call | — |

On these clean synthetic images gemma is fast and nearly perfect. It reported no tables for the pipe-free layouts,
which is correct. Faded, skewed or photographed paper isn't covered by this run.

**Do the models work reasonably well?**
- **Yes, as a pair, on clean documents.** Vision is not the bottleneck. Reasoning gets structure and kinds right and
  returns valid JSON reliably.
- **Its failures are the kind the app's checks must catch:** invented optional values, missed rows, truncation on long
  inputs. The checks caught the missed rows and the truncation, but not the invented values that copy a printed amount.
- **Before trusting it for pay stubs**, run the `document_forms` and `receipt_kinds` eval tasks against these models,
  and against the donated corpus in your own terminal, with a year-to-date stub included.
- **For long PDFs**, a reasoning model with shorter reasoning, or a larger output budget for statement summaries.

## UX and UI: where a person gets annoyed

**Things that break trust:**
1. **Kind change and Apply details can't be undone from the page.** Their toasts ("Read as fuel.", "Details applied.")
   have no Undo, and History shows the change with no Undo either. A field correction's toast does have Undo, but it
   was already gone when I went back to it about a minute later, and History never offers one. A person who misses the toast has no way back.
   *(finding)*
2. **A failing check's breakdown says "These steps don't add up to the figure. This is a bug; please report it."** It
   also never shows the printed amount the figure is compared with. A real mismatch reads as an app crash, and the
   person can't see what disagreed. *(finding)*
3. **Invented values show up as "Printed details"**: "Cash 18.24 USD", "Direct deposit 2,739.81 USD". Each has a Find
   button that lights the Total or Net pay line, so a careful person sees the citation doesn't fit. *(findings)*
4. **A correction can break a check without review.** After I corrected the dining tip to 1.00, the check said "9.06
   doesn't match the printed 8.06", yet the receipt stayed "Checked automatically" and counted. Corrections don't
   re-run the arithmetic.
5. **History names "Home Manager"**, not the person, for a kind change. *(finding)*

**Unintuitive:**
6. **No way to add a file from the browser.** Documents arrive only through the Inbox folder or a watched folder. A
   first-time user looks for an upload button and finds none.
7. **Scan now right after Watch a folder** shows "Wait for the current scan before scanning a watched folder.", and the
   error stays on screen across every page for the rest of the session. *(finding)*
8. **The Receipt kind row shows the kind twice** ("Grocery" beside a select reading "Grocery"). Changing it takes
   choosing a kind, pressing Change kind…, then confirming. The preview text is clear, but the doubled label looks like
   two settings.
9. **A printed merchant is reported as inferred**: "Merchant QUICKFUEL STATION 112 was inferred from “QUICKFUEL
   STATION 112”, not printed". That line is printed; the model marked its own reading as inferred, and the note
   contradicts itself.
10. **"Counts in Household supplies, March 2026 0.00 USD"** on a receipt waiting in review reads as "this counts zero"
    rather than "doesn't count yet".
11. **The pay stub page repeats itself.** Gross and net appear in the field list, in "From gross pay to net pay" twice
    (as lines and as totals), and in the checks. With totals read as lines, the breakdown is hard to follow.
12. **Package sizes look like weights.** "RICE 2 lb", "WHOLE MILK 1 gal" appear under Printed details, read from item
    names like "RICE 2LB", and imply sold-by-weight pricing that isn't there.
13. **Correct opens the whole form.** "Correct tip" opens every field (date, merchant, subtotal…), focused on Tip. Fine
    for keyboard users, heavy for a one-field fix.

**What felt good:**
- The kind change's preview says exactly what happens: no image re-read, corrections stay, reviewed amounts stay.
- The reviewed-receipt banner explains why Apply details is offered and what it won't change.
- Find on a detail lights its line in the source.
- Breakdowns list each input with "Read by model" and Open source.

## What to change in the spec and plan

Each item names the requirement to amend and the slice it falls to. Items marked *pre-existing* belong to
`docs/open-work.md` rather than this spec, but they decide whether pay stubs count, so they are listed here.

**Values the document doesn't print (spec FR-04, FR-20, FR-30 invariants "Nothing is invented"; plan SL-03, SL-05)**
1. **Tenders.** FR-04 gains: "A tender is kept only when its type is printed in its citation (gift card, EBT, SNAP,
   VISA/card, cash), as an account type is (FR-25), and it never cites the line its total is read from." Plan SL-05:
   check type words in `receipt_details`. Contract SC-04 gains a variant where the stub returns a cash tender citing
   TOTAL, which must not be stored. This matters most for gift cards: an invented gift card of the full total makes the
   receipt count 0.00 through `refresh_paid`.
2. **Deposit splits.** FR-20 gains: "A split cites a deposit line (an account mask or deposit words), never the line its
   net pay is read from; a split equal to net pay that cites the net pay line is dropped." FR-21: "The splits check
   never compares a value with itself; it runs only when at least one split cites a line other than net pay's." Plan
   SL-03, plus contract SC-21 variant 21d (the stub returns a split citing NET PAY).
3. **A money field copied from another field's line.** Add a cross-field rule to "Deterministic checks" (it touches
   today's receipt form, so either a spec amendment or a follow-up spec): "A summary amount whose only citation is
   another summary field's line and quote (subtotal citing the total's line) is dropped with a note." Example: the
   parking receipt.

**Undo, history and review (spec FR-11, FR-12, FR-19; plan SL-08, SL-09)**
4. **FR-11/FR-12 acceptance gains the UI path**: "The kind change and Apply details each show an Undo in their
   confirmation and in History, and Undo restores the earlier kind or the waiting details." Plan SL-09: Undo on both
   toasts, and an Undo control on History rows the API marks `undoable`. SC-14 gains steps for both, and the browser
   test asserts them. The journey test checked only the API.
5. **Who made a kind change.** FR-12 gains: "The kind correction names the person who asked for it." Plan SL-08: carry
   the actor from the PATCH into the enqueued run's options and write it on the correction.
6. **Corrections re-run the document's checks.** A new FR: "A correction to an amount or detail re-runs the record's
   arithmetic checks; one that now fails adds its note and sends a receipt not reviewed by the user to review." Plan
   SL-06 already re-runs the gift-card rule (`refresh_paid`); generalize it to every check in `document_checks`.

**Traces (spec FR-19; plan SL-07, SL-09)**
7. **FR-19 acceptance gains the page**: "The breakdown shows the printed amount it is compared with, and whether the
   check passes; a failing check is never presented as a calculation error." Plan SL-09: `trace.js` renders
   `compared_with` and a pass or fail line for traces that carry it, and keeps the "don't add up" warning for the rest.
   Browser test: open a failing check's breakdown.

**Reading again (spec "Reading again" in Errors; FR-11; plan SL-08)**
8. **Keep categories when the new answer is unusable.** Add to Errors: "A re-read whose category answer is unusable
   keeps the receipt's and items' earlier model categories, rather than clearing them." Plan SL-08 and the journey gain
   that step.

**Pay stubs (pre-existing, but block FR-23's goal)**
9. **Digits inside a line's label aren't an amount** ("401k", "403(b)", "Section 125"). Fix `anchor_paystub`'s
   multi-number rule to ignore numbers inside the description words. Contract: a stub with "401k 184.98" keeps 18498.
10. **Totals are never pay lines on any path.** Extend the table-only exclusion of Gross pay / Net pay / Total … rows to
    flat text. Contract: a flat stub whose PayLines answer includes "Gross pay" keeps earnings equal to gross.
11. **A year-to-date stub in the live test data.** Add a pay stub with This period and YTD columns (image and flat text)
    to `evals/synthetic.py`, so the test instance and `document_forms` exercise FR-22 with the real models.

**Models and limits (spec "Nondeterministic outputs"; plan SL-10)**
12. **Eval thresholds.** Promote "zero invented optional values" to a reported count in `receipt_kinds` and
    `document_forms` (invented tenders, deposits, copied subtotals), beside the wrong-column count. The thresholds are
    still to be decided.
13. **Long statements.** A recorded known limit plus open work: gpt-oss-20b ran out of output on the multi-page bank
    PDF. Either a larger summary output budget for statements, or the eval should prefer a reasoning model with shorter
    reasoning.

**Page polish (plan SL-09, UI)**
14. **Show the kind once**: the select alone, labelled "Receipt kind".
15. **Mark a weight only when a price per weight is printed.** Otherwise show nothing under Printed details (FR-09 asks
    for weight with price per weight).
16. **Say "Doesn't count yet"** instead of 0.00 in "Counts in" while a record waits in review.
17. **On the pay stub page,** fold "As printed on the stub" and the checks under "From gross pay to net pay", so gross
    and net appear once.

**Outside this feature, noted for open work**
- An upload button or drop target on Documents.
- "Scan now" during a folder's first scan should say it is already scanning, not leave an error on screen.
- "Merchant was inferred" shouldn't appear when the seller's line is printed (the identify step's `seller_basis`).

**Process notes for the next iteration**
- The approval-guard hook blocks `environment.py` (any command naming `.agent-harness`), so the preflight needs the
  user to run it. Allowlist it, or document that in the validate-feature skill.
- Git Bash rewrites `--route "#/…"` arguments into Windows paths. The first finding was recorded with a mangled route
  (`#P:/Dev Environment/Git/documents/ID`) and needs correcting by hand. The agent-testing skill should say to run
  `finding` from PowerShell, or with `MSYS_NO_PATHCONV=1`.
- The fixture-only scenarios passed while the live run found invented values. Contract variants with plausible wrong
  answers (items 1–3 above) would have caught them. Each new optional field should get one "the model fills it from
  the wrong line" variant.
