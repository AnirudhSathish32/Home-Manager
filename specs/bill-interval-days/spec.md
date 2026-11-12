# Recurring bills every N days
Feature: bill-interval-days

<!-- Approval state lives in approvals/<slug>.json and is bound to this file's content hash.
     Do not add a Status line: changing it would change the hash. Check with gate.py. -->

Amends: `docs/money.md` "Recurring bills" (how often a recurring payment repeats); `specs/bill-kinds/spec.md` as built,
for the `recurrence` a bill is read with. Every other rule of recurring bills stands: sources, bill or subscription, one
bill per payee, later payments keeping it current, the forecast, upcoming bills.

## Decisions already made (not to be re-asked)
- **D1 The wanted behavior** (user, 2026-11-09): "it does not support the amount of days the payment is recurring. This
  should be a text box that is editable by the human but the system should make a guess by having that text box filled
  in with a number. The model should make this guess by analyzing the picture I give it. In this picture it literally
  says every 45 days."
- **D2 The model's guess comes from what is printed.** It reads the transcription of the bill (the picture's text, as
  every image is read today: vision transcription, then the reasoning model). A day count is kept only when it is
  printed in the line it cites. The picture itself is not attached to this spec; the test fixtures are synthetic.

## Goal / users / scope / non-goals
**Goal.** A recurring payment can repeat every N days. When a bill or receipt prints its schedule in days ("every 45
days", "billed every 60 days"), the proposal already holds that number. The user can change the number when confirming
the bill and at any time after. Due dates, the monthly cost, the forecast and upcoming bills follow it.

**Users.** The household user confirming recurring bills in Review and keeping them on the Bills page.

**In scope.** The schedule and its stored form (FR-01, FR-02); the model's reading (FR-03, FR-04); editing (FR-05,
FR-06); arithmetic: due dates, monthly cost, forecast, matching (FR-07 – FR-09); every screen and tool that shows how
often (FR-10); existing data (FR-11); docs (FR-12).

**Non-goals.**
- Finding an N-day cadence from three or more payments (`CADENCES`, `finance/reconcile.py:38`). OD-3 default: out of
  scope, recorded in `docs/open-work.md`.
- The statement payee scan (`finance/recurring_scan.py`) answering in days. It guesses from charges, not from a printed
  schedule, so it keeps the named choices.
- Schedules that aren't a fixed number of days or months ("the 2nd Tuesday", "twice a month"), and seasonal bills.
- Any change to how a bill counts or is matched, apart from its due dates.

## Existing behavior (verified paths, assumptions, unknowns)
Paths under `src/home_manager/` unless noted. Read at HEAD `06cbb9b`.

- How often is one of `weekly, monthly, quarterly, semiannual, annual` (`core/categories.py:24 – :25` `FREQUENCY_MONTHS`,
  `FREQUENCIES`). It is enforced by checks on `recurring_obligations.frequency` (`library/migrations/050_strict_tables.sql:1090`)
  and `receipts.recurrence` (`054_receipt_segments.sql:29`). `recurring_obligations` is
  `UNIQUE(merchant_id, account_id, currency, frequency)` (`:1099`).
- The model gives `recurrence` with a receipt or bill's description (`documents/extraction.py:276` `PurchaseDescription`,
  instruction `:670 – :672`), restricted to those five words, with no citation. Contract terms give `frequency` the same
  way (`:484`, `TERMS` `:680`).
- `propose_bills` (`finance/reconcile.py:653`) proposes a bill from a verified receipt or bill with its `recurrence`, or
  `monthly` (`:693`). A single card charge is always proposed as monthly (`:705`).
- Arithmetic: `due_after` (`finance/reconcile.py:80`) adds 7 days or N calendar months; `monthly_equivalent`
  (`core/categories.py:44`) is weekly × 52/12, else amount ÷ months; the forecast places a bill in its due months
  (`finance/forecast.py:375` `bill_amount`), weekly spread evenly. Totals on the Bills page use `monthly_equivalent`
  (`finance/tools.py:1003`, `:1034`).
- Editing: Review's Confirm sends a chosen frequency from a select of the five (`app/static/review_v2.js:362 – :366`;
  `Reconciler.review_obligation` `:818`, API `ObligationReviewInput.frequency`, `app/api.py:353`). After confirming,
  only the kind can be changed (`/api/finance/recurring/{id}/kind`); the frequency cannot.
- Labels: `FREQUENCY_LABELS` (`app/static/ui.js:153`), `BILLS2_EVERY` (`app/static/bills_v2.js:6`), and the forecast,
  Today and Review lines that print them. The family view, the dashboard, Tax Zen and the traces also read `frequency`
  (`finance/family.py`, `finance/dashboard.py`, `finance/tax_zen.py`, `finance/traces.py`).

## Functional requirements
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-01 | A recurring payment repeats on a **named schedule** (weekly, monthly, quarterly, every 6 months, yearly, as today) **or every N days**, N a whole number from 1 to 730. | A bill can be saved as every 45 days; N = 0, 731, 4.5 or text is refused with "Enter a whole number of days from 1 to 730." and changes nothing. |
| FR-02 | **One bill per payee and schedule**, as today: the uniqueness that holds per named frequency holds per day count too. | A payee with a bill every 45 days can't get a second one every 45 days; changing a bill to a schedule another of the payee's bills has is refused with today's message. |
| FR-03 | **The model reads a printed day count.** When a bill or receipt for an ongoing service prints its schedule in days, the reading gives the day count with a citation. It is kept only when that number is printed in the cited line, beside a day word ("day", "days"). | Stub reply `recurrence_days: 45` citing "Billed every 45 days" → kept. The same citing a line without 45 → dropped with a record note, and the named `recurrence` (if any) is used. |
| FR-04 | **The guess fills the box.** A bill proposed from such a reading is proposed as every N days. Without a printed day count, it is proposed as today (the model's named `recurrence`, else monthly). | The SC-01 fixture proposes "every 45 days"; a bill printing "monthly" still proposes monthly. |
| FR-05 | **Confirming in Review** shows the schedule as a choice of the named schedules plus "Every [N] days", where N is a number box. A day-count proposal opens on "Every" with N filled in. The user can change either before confirming. | Review shows "Every 45 days" with 45 in the box; typing 40 and confirming saves every 40 days, with a `review_events` note "How often: every 40 days". |
| FR-06 | **Editing later.** A confirmed bill's schedule can be changed on the Bills page with the same control. Each change is audited, and a later reading never overwrites the user's choice. | Change 45 → 50 on the Bills page: saved, audited; recording the same bill again leaves 50. |
| FR-07 | **Due dates.** Every N days: next due = last paid (or first due) + N days. Named schedules keep their calendar arithmetic. | Last paid 2026-10-01, every 45 days → next due 2026-11-15; a matched payment on 2026-11-14 → next due 2026-12-29. |
| FR-08 | **Monthly cost.** Every N days costs amount × 365 ÷ (12 × N) a month, exact in the arithmetic, rounded only for display as today. Named schedules unchanged. | $90 every 45 days shows $60.83 a month and $730.00 a year; a monthly $90 still shows $90.00. |
| FR-09 | **Forecast and upcoming bills.** An every-N-days bill falls in each projected month that holds one of its due dates (twice in a month when two fall in it). It is upcoming and overdue by its next due date, as today. | Every 20 days from 2027-01-05: January holds 2 payments (01-05, 01-25), February 1 (02-14); the 120-day upcoming list shows each due date. |
| FR-10 | **Everywhere it is shown** (Bills page, Review, Today, Home, forecast, family view, assistant tools, traces), an every-N-days schedule reads "Every N days" (or "every N days" mid-sentence). | Each screen and tool output, for the fixture bill, shows "Every 45 days"; no screen shows a raw key or `undefined`. |
| FR-11 | **Existing bills** keep their named schedules and dates exactly; no reading is repeated for this change except through the extraction version (FR-12). | After upgrade, every existing row's schedule, next due date and expected amount are unchanged. |
| FR-12 | **Version and docs.** The extraction version moves on so bills read before are read again when next recorded. `docs/money.md` "Recurring bills" describes FR-01 – FR-10, and the open-work item is removed. | `EXTRACTION_VERSION` differs from before; doc text present; open-work entry gone. |

## Invariants, privacy, security and data retention
- Nothing leaves the machine; the day count comes from the same local reasoning call that reads the bill today (no new
  call). Its citation is checked like every other cited value.
- Money from the server: monthly and yearly costs are computed and formatted by the server (`docs/ui.md` "Screen
  rules"); the browser never multiplies.
- A user's schedule choice is never replaced by a machine reading (FR-06).
- Strict CSP, no framework: the control is a native `<select>` plus `<input type="number">`.

## Errors, recovery, duplicates, restart behavior
- An invalid day count from the model (0, over 730, not a whole number) is dropped with a record note; the bill is
  proposed as FR-04's fallback says.
- An invalid day count from the user is refused (FR-01) and the form keeps what was typed so it can be fixed.
- The schema upgrade keeps every existing value (FR-11); a failed upgrade leaves the library as before, with today's
  recovery.

## Nondeterministic outputs and how they are verified
The model's day count is verified with fixed stub replies (the `local_model` stub of the existing extraction tests): a
supported citation, an unsupported one, an out-of-range number and none. The bill eval (`evals/`) gains a synthetic bill
that prints "every 45 days", scored as exact match on N; the user runs it on the private corpus themselves
(`docs/evals.md`).

## Scenarios
| ID | FR IDs | Initial state | User/API actions | Expected final DB/files/UI state |
|---|---|---|---|---|
| SC-01 | FR-03, FR-04, FR-05 | Synthetic bill image printing "Billed every 45 days", read | Record (stub gives 45 with a supported citation); confirm the bill; open Review | Proposed bill every 45 days; Review shows "Every" with 45 filled in |
| SC-02 | FR-03 | Same bill | Record with a stub citing a line without 45 | Day count dropped with a note; proposed as the named recurrence or monthly |
| SC-03 | FR-05 | SC-01 in Review | Change 45 to 40, Confirm | Saved every 40 days; audited note |
| SC-04 | FR-01 | SC-01 in Review | Enter 0, then 731, then 4.5 | Each refused with the FR-01 message; nothing saved |
| SC-05 | FR-06 | Confirmed bill every 45 days | Change to 50 on the Bills page; record the bill again | 50 kept; audited |
| SC-06 | FR-07 | Confirmed every 45 days, last paid 2026-10-01 | A matching payment posts 2026-11-14 | Last paid 2026-11-14; next due 2026-12-29 |
| SC-07 | FR-08 | $90 every 45 days | Open Bills | $60.83 a month, $730.00 a year (server values) |
| SC-08 | FR-09 | Every 20 days from 2027-01-05 | Forecast for 2027 | January 2 payments, February 1 |
| SC-09 | FR-02 | Payee with a bill every 45 days | Change another of the payee's bills to every 45 days | Refused with today's message |
| SC-10 | FR-11 | Library at the previous schema with five bills, one per named schedule | Upgrade | All five unchanged |
| SC-11 | FR-10 | SC-01 confirmed | Open Today, Home, forecast, family view; call the recurring tool | "Every 45 days" in each |

## Out of scope / product decisions requiring approval
- **OD-1 Named schedules or days only.** Default: keep the named schedules and add "Every N days". Monthly and yearly
  stay calendar-exact (a monthly bill due on the 1st stays on the 1st), which 30 or 365 days would drift from.
  Alternative: days only, with monthly shown as 30.
- **OD-2 Monthly cost formula.** Default: 365 ÷ (12 × N) months per payment (FR-08). Alternative: 365.25. The difference
  is under 0.1%.
- **OD-3 Detecting an N-day cadence from payments.** Default: out of scope, open-work item. Alternative: in scope, with
  a tolerance of ±3 days over three or more payments.
- **OD-4 Contract terms in days.** Default: in scope. A lease or policy that prints "every 45 days" gives the day count
  the same way (FR-03). Alternative: bills and receipts only.
- **OD-5 Range.** Default: 1 – 730 days. Alternative: up to 1,095 (three-year licenses).

**Domain risk candidates (accept or reject each):**
- **R1 A printed day count that is not the schedule** ("payment due in 30 days", "late after 15 days"). Unhandled: a
  bill proposed every 30 days that is really monthly. Default: the instruction asks only for a billing cycle ("every",
  "billed every", "each N-day period"); a due-in phrase is not a schedule; the eval fixture includes a bill with both.
- **R2 Billing period printed as dates** (Service 10/01 – 11/14, 45 days). Default: not inferred; only a printed day
  count is read. The user fills the box.
- **R3 Budgets and What If.** Default: they use the monthly cost (FR-08), so an every-N-days bill budgets and cancels
  like any other.
- **R4 A family's copy on an older version** receiving an every-N-days bill. Default: the plan checks the family share
  format; an older peer shows "Every N days" from a fallback label or refuses the share with a clear message.
