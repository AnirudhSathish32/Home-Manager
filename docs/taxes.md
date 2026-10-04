# Taxes

The Taxes page (`static/taxes.js`) is where the year's taxes come together. It has these parts:

1. **Tax tags** (built 2026-09-30): ledger items marked as write-offs, business income, spending for a credit, or tax
   paid ahead.
2. **The year's return, estimated** (built 2026-09-30): every income source, deductions, credits and taxes, in 1040
   order.
3. **Tax Zen** (built 2026-09-30): the W-4 entries (or quarterly estimated payments) that bring the year to a $0 refund,
   per tax return. It also appears for each What If plan and in the paycheck planner.

The design is the approved plan of 2026-09-30.
- A **tax return is the unit that reaches $0**: a single filer, or a married couple filing jointly.
- The federal return's law comes from Engine 1, which cites the rule for every line (since 2026-10-04). The tax tables
  for pay stub withholding come from a quoted lookup confirmed in Review.
- Figures fixed in law that the app itself uses are constants citing the statute.
- Nothing is guessed.

## Tax tags

`finance/tax_tags.py`, `finance/tax_lines.py`, migration `045_tax_tags.sql` (`businesses`, `tax_rules`, `tax_tags`).

**What a tag says.** One tag per item: a bank line, a receipt, or one line of a receipt. Its kind and line:

| Kind | Lines | Goes to |
|---|---|---|
| Business income | gross receipts (1099-NEC, 1099-K, clients), other | Schedule C lines 1, 6 |
| Business expense | advertising, car and truck, commissions, contract labor, insurance, interest, legal and professional, office and software, rent or lease, repairs, supplies, taxes and licenses, travel, meals (50% counts, IRC §274(n)), utilities and phone, wages, other | Schedule C lines 8–27a |
| Itemized deduction | medical and dental, state and local income tax, property tax, mortgage interest, charity (cash), charity (goods), other | Schedule A |
| Adjustment to income | educator expenses, HSA contribution not through payroll, self-employed health insurance, traditional IRA, student-loan interest | Schedule 1 |
| Spending for a credit | child and dependent care, tuition, energy-efficient home improvement, clean vehicle | Forms 2441, 8863, 5695, 8936 |
| Tax paid ahead | federal estimated tax (1040-ES), state estimated tax | Form 1040 line 26; state return |

- **Businesses:** business kinds name a business. Contract (1099) work is a business to the IRS even without a
  company, and each business gets its own Schedule C.
- **Amount:** a tag counts the whole item unless you enter the part that counts. Limits that depend on the whole return
  (medical above 7.5% of AGI, the SALT cap, the student-loan cap) are applied by the return estimate, not per item.
- **Direction:** business income is money coming in; every other kind is money going out.

**Three ways to tag:**
- **By hand**, in the transaction drawer (Taxes section) or on a receipt (the whole receipt or one of its lines). It
  counts at once, and no rule changes it.
- **Tax rules:** "every bank line containing ADOBE CREATIVE is an office expense of Contract work".
  - Matched like category rules: every word of the pattern in the line's description and merchant name. The most
    words wins, then the newest. A rule can be limited to one account.
  - A rule for money out never tags money in.
  - Rules run when lines are imported or added, after reconciling, and whenever a rule changes.
  - Deleting a rule removes its tags; those lines can then be suggested.
  - Rule tags count at once.
- **Suggestions** (pattern recognition), made when lines arrive or are reconciled:
  - A bank line from a payee (its first three normalized words, as recurring-bill detection uses) whose line you
    tagged before gets the same kind, line and business.
  - A payment that looks like tax paid ahead: IRS Direct Pay ("IRS USATAXPYMT") or EFTPS as federal estimated tax,
    and a state department of revenue or taxation as state estimated tax.
  - Each suggestion waits in Review under **Possible write-offs and tax payments**, with the reason. The choices are
    **Tag it** (optionally "Also tag every bank line containing…", which makes a rule) and **Not a write-off**.
  - A "not a write-off" is kept, so that payee isn't suggested again. Decisions are audited in `review_events`.

**Each item counted once in a year** (`TaxTags.year`, the Taxes page):
- Only confirmed tags count, and only on items that count: not a rejected bank line, a verified receipt.
- Tags on a receipt's lines replace a tag on the receipt, and a receipt's tags replace a tag on the bank line it's
  matched to. The page notes each case.
- The page lists the year by kind, line and business (amount and the part that counts), every tagged item, the tax
  rules, and the businesses.

**API:**
- `GET /api/tax/setup`
- `POST /api/tax/businesses`, `PUT` and `DELETE /api/tax/businesses/{id}` (delete archives)
- `GET /api/tax-tags?status=&year=&kind=&receipt_id=`, `GET /api/tax-tags/on/{type}/{id}`, `POST /api/tax-tags`
- `POST /api/tax-tags/{id}/not-a-write-off`, `POST /api/tax-tags/{id}/review`
- `GET` and `POST /api/tax/rules`, `PUT` and `DELETE /api/tax/rules/{id}`
- `GET /api/tax/write-offs/{year}`

## The year's return, estimated

`finance/tax_year.py` (gather and merge), `finance/tax_engine.py` (the engine), `finance/tax_return.py` (the profile and
the simplified state return), migration `046_tax_figures.sql` (`tax_years`). This is the Taxes page's first panel.

**Engines 1 and 2** (docs/tax-engines.md, 2026-10-04):
- The federal return is worked out by **Engine 1**, which runs on this computer. The app shows numbered engines and
  never an engine's own name. Settings and the health check say whether each can run here.
- **Engine 2** (optional: `pip install "home-manager[engine2]"`) checks every return line by line. It's on by default
  once installed (Settings → "Check every return with a second engine"). Where they differ, the page lists the lines
  and Tax Zen asks you to check the return first.
- Both cover 2025 and 2026 returns. A return Engine 1 doesn't cover (both spouses self-employed, more than three AOTC
  students, other credits typed in) is worked out by Engine 2 instead, and the page says so. A year or a case neither
  covers gives no estimate, and the page names the reason.
- Engines ask rather than guess. When one needs a fact that no record gives, the page says what to enter.
- Each distinct result is kept in `tax_calculations`.
- The hand-written federal return and its yearly-figures lookup were retired on 2026-10-04. Engine 1 carries its own
  yearly law. The federal tax table (Review → "Tax tables to confirm") is still used for pay stub withholding
  (Pub 15-T) and Tax Zen's W-4 answers, and for the marginal rate shown on the page.

**Gathered from records** (each field names its source on the page):
- **Jobs:** one per employer, from this year's confirmed pay stubs.
  - Year to date comes from the latest stub's printed figures when every line has one; otherwise the year's stubs are
    added up.
  - The latest stub's paycheck is then added for each payday left this year, counted from the pay frequency and the
    last pay date.
  - From these: wages (gross less pre-tax deductions), Social Security and Medicare wages (gross less health, dental,
    vision, HSA and FSA), federal, state and Medicare withheld, and HSA money through payroll (yours and the
    employer's).
- **Interest:** bank interest lines plus interest in taxable investment accounts.
- **Dividends:** dividends in taxable accounts.
- Interest and dividends are counted so far and projected to Dec 31 at the same pace. Confirmed 1099-INT and
  1099-DIV forms replace them. Qualified dividends come from 1099-DIV box 1b, else you type them.
- **Capital gains:** realized short- and long-term gains in taxable accounts (tax lots).
- **Retirement distributions:** withdrawals from tax-deferred accounts, or 1099-R box 2a. They count as early before
  59½, from your birth year.
- **1099 withholding:** box 4.
- **From tax tags:** each business's income and expenses (Schedule C), adjustments, itemized deductions, credit
  spending (dependent care, tuition, energy), and estimated tax paid (federal and state).
- **Work state:** from the latest stub.

**Engine facts filled from records** (so the engine doesn't have to ask):
- **Form 1098:** box 1 gives the mortgage interest and box 10 the property tax, when no tag already counts them.
- **The mortgage's average balance** (Pub 936; it limits interest above $750,000), worked out by the first method
  that has what it needs:
  1. the average of 1098 box 2 (principal on Jan 1) and the mortgage's balance on Dec 31;
  2. 1098 box 2 alone, as an upper bound;
  3. the year's interest divided by the mortgage's yearly rate.

  "The mortgage" is a confirmed loan whose name says mortgage, home loan, home equity or HELOC. Its Dec 31 balance is
  projected from its recorded balance, rate and monthly payment, as the forecast does.
- **HSA coverage:** the year's HSA contributions are compared with the self-only limit (IRC §223(b), $1,000 more from
  55).
  - The contributions are 5498-SA box 2 once it arrives. Until then, payroll HSA lines projected to Dec 31 plus your
    own tagged contributions.
  - At or under the limit: self-only, since the coverage doesn't change the deduction at that amount.
  - Over it: family.
- **Ages:** your birth year (Settings). In the family view, each member's birth year comes from their own Settings
  (sent with their published copy) for the two people on a joint return.
- **Last year's tax and AGI** (the estimated-tax safe harbor): last year's return as worked out here, until you type
  the filed return's figures.

**Typed over the records** (saved per year):
- any field, any job's figures, and jobs not in your pay stubs (a spouse's);
- your spouse's birth year, children and dependents;
- itemizing anyway;
- qualified tips (with the tipped occupation from the Treasury list) and the overtime premium.

**Still asked for, because no record says it:** qualifying children and other dependents, the qualified part of
dividends before the 1099-DIV, and which tuition is for whom.

**The estimate, in Form 1040 order:** income, adjustments, the deduction (standard with the 2026 charitable deduction
for non-itemizers, or itemized), the senior, tips and overtime deductions, QBI, tax, credits, other taxes
(self-employment, Additional Medicare, net investment income tax and the rest), then payments.
- Each line says how it was worked out and cites the rule it follows.
- **Payments** are added up by the app: withholding (every job, and 1099 box 4), Additional Medicare withheld,
  estimated tax paid, and refundable credits. The result is the refund, or the amount owed.
- **State (simplified):** federal AGI less the state's deduction (or yours), the state's brackets, less state credits,
  against state withholding and estimated payments. It's labeled simplified, since Engine 1 has no full return for
  most states.

**Not covered by Engine 1** (named on the page, and no estimate is given):
- both spouses self-employed;
- educator expenses on a joint return;
- forcing the standard deduction;
- the energy credit;
- other credits typed in;
- more than three AOTC students.

## CPA pack

Built 2026-09-30 (milestone M4b, reshaped from a general Excel report). Code: `finance/cpa_pack.py`; tests:
`tests/test_cpa_pack.py`. Taxes → **For your accountant** → **Build the YYYY CPA pack** makes one Excel workbook for the
year to hand an accountant. Only the user's button makes one; the assistant has no tool for it.

Sheets: Summary (the estimate, income, gains, write-offs, household spending in USD, complete or partial), Return (each
line of the estimate), Income (jobs and every gathered field with its source), Write-offs (counted totals by line),
Write-off items (every tag, its USD value and whether the estimate counts it), Investments (the year's confirmed
activity and realized gains per taxable account), Tax forms (confirmed and proposed 1099 and 5498 boxes), Transactions
(every counted line and stand-alone receipt, with its USD amount, the basis and the rate id), Exchange rates (each rate
used, with its download's SHA-256), Needs review, and Manifest.

- It does no tax math of its own: it shows what the Taxes page and the finance tools compute, read from one database
  snapshot. Before saving, the Transactions sheet's Spent (USD) column must add up to household spending, and the
  reopened workbook must match what was written.
- **Needs review** lists what's unfinished: receipts and statement lines not yet counted, open matching questions,
  unconfirmed tags and tax forms, unconfirmed tax tables, shares sold with no purchase lot, amounts
  with no exchange rate, and write-offs in another currency (the estimate counts USD tags only).
- Values only: Python computes every number. Document text is always written as text, never a formula (a description
  starting with `=` stays text, quote-prefixed).
- Kept under `<library root>/Reports/<year>/`, outside `Library/`, so a pack is never read back in as evidence. A pack is
  never overwritten: building again from unchanged data returns the same file; changed data makes a new file beside the
  old one. Downloads check the file against the SHA-256 recorded when it was made.
- A full disk or a locked file (open in Excel) fails with a clear message and leaves nothing behind.

## Tax Zen

`finance/tax_zen.py`. It is the top of the return panel on the Taxes page. Tax Zen means the return comes out within a
dollar of $0, since withholding is in cents and the W-4 is in whole dollars.

**Aim and status** (built 2026-10-03, docs/tax_intelligence_architecture.md §12–26):
- **The aim** ("Aim for", saved with the year as `zen_policy`):
  - $0 (the default);
  - a small refund (default $200);
  - keep cash: owe at most a limit (default $999) less a $400 buffer, so the aim is owing $599;
  - owe what the safe harbor allows, less the buffer.
- **The status** is a badge:
  - **Tax Zen:** at the aim (within a dollar for $0, otherwise within $100) with the safe harbor met;
  - **Close · watch it:** within $500 and safe, so no change is asked;
  - **On track · could turn** (AT_RISK): at the aim or close to it, but the low end of the likely range owes $1,000 or
    more. The page gives a cushion: the extra 4(c) withholding a paycheck that keeps even the low end under $1,000;
  - **Change recommended;**
  - **Check the return first:** the two engines disagree;
  - **Not enough to go on;**
  - **Not covered.**
- **The safe harbor** is `finance/safe_harbor.py`, apart from the return.
  - Rules: under $1,000 owed, or payments reaching the smaller of 90% of this year's tax and 100% (110%) of last
    year's.
  - Timing: withholding counts evenly through the year, estimated payments by date, and short quarters are named.
    Annualized income isn't worked out.
- **Why:** the page says where the year ends, the aim and the paychecks left.
  - When short of the aim, the first answer is one box, Step 4(c) extra a paycheck (§20), with 4(a) as the
    alternative.
  - Each answer is **checked**: the return is worked out again by the engine with that withholding (§46).
- **The assistant** has `get_tax_zen_status`: the status, aim, year end, likely range, what changed, safe harbor and W-4
  answer as worked out here. It explains them and never recomputes.

**The likely range** (built 2026-10-04, §23, §36): the return is worked out twice more with only the projected parts
moved, then shown as "Likely between X and Y" with a confidence.
- **What moves:** pay still to come moves by how much this year's paychecks varied (at least 5%), with its withholding.
  Interest and dividends still to come move by 25%. Recorded and typed values don't move.
- **Confidence:** high when under 10% of income is projected, medium under 30%, else low.

**Each value says what kind it is** (§35), beside its field on the page: "From records", "Worked out from records" (the
mortgage's average balance, HSA coverage, early distributions), "Projected to Dec 31", "Enter it" (the qualified part of
dividends before the 1099-DIV) or "You typed". Each job says whether it's projected. `gather` returns them as `kinds`.

**Steady advice** (built 2026-10-04, §25, §37, §42, §43; migration `060_tax_zen_evaluations.sql`):
- **History:** each evaluation is kept: status, range, W-4 answer, aim, the figures it rested on, and what changed. A
  row is added only when the status, the answer or the inputs changed.
- **Staying Tax Zen:** once Tax Zen, it takes 1.5 times the band to leave it.
- **Keeping the W-4 answer:** a new answer replaces the last one only when it moves withholding by $25 or more a
  paycheck, the status got worse, or something material changed:
  - a new or dropped job;
  - pay per paycheck moving by more than 10%;
  - a tax form arriving.

  Otherwise the page says the advice from that date still stands, worked out again for today.
- **What changed** since Tax Zen last looked is listed in words (new stubs, withholding per paycheck, new forms, amounts
  that moved $100 or more).
- **On Home:** when the status got worse than when the Taxes page last showed it (to On track · could turn, Change
  recommended, or Check the return first), Home's "Needs attention" lists it with what changed, until Taxes is opened.
  - Home works this year's return out again in the background whenever a confirmed pay stub, tax form, tag or typed
    value is newer than the last evaluation.

**Paychecks ahead:**
- Jobs come from pay stubs. Every payday after the latest stub counts in the year's totals (paid like that stub, whether
  or not its stub is here yet). Only paydays after today can change with a new W-4.
- Each paycheck's federal withholding is worked out as payroll does, by the withholding engine (`finance/withholding.py`,
  §30): IRS Publication 15-T's annual percentage method for a 2020+ W-4 (Step 2's half-size schedule, Step 3 credits a
  year, 4(a) other income, 4(b) deductions, 4(c) extra per paycheck).
- **When a new W-4 counts** (§21): payroll puts it in by the first payroll period ending 30 days after it's handed in
  (Pub 15, section 9). So by default the next paycheck passes first, and the answer is spread over the paychecks after
  it (`w4_delay_checks` in the aim). The page names the next payday. When none is left after that, it says so.
- That result is matched to what the latest stub actually withholds. The difference is kept, so a W-4 you haven't
  entered, or a payroll quirk, carries into the answer.
- Enter the W-4 on file ("Your W-4 there now") and the answer is the new total for the box.

**The answer, for one job** (by default the job with the most paychecks left, then the larger paycheck; you can choose
another):
- **Owing:** raise Step 4(a) other income. **Getting a refund:** raise Step 4(b) deductions, or Step 3 credits when the
  W-4 already claims dependents.
- Every answer is listed (`recommendations`), simplest first: fewest boxes changed, then the smallest change in
  withholding.
- **Checked against the return** (§46): when the engine's year-end with an answer differs by more than a cent a paycheck,
  the answer is aimed at the gap it reports and checked again, up to three times.
- The search is over whole dollars and keeps the entry that lands nearest $0. It is exact because withholding only rises
  as 4(a) rises and only falls as 4(b) rises. The page shows the new withholding per paycheck and where the year ends.
- When owing, the same catch-up is also shown as a 4(c) extra amount per paycheck.
- When no entry can close a refund with the paychecks left (withholding can't go below zero), the page says so.
- **For the rest of this year:** larger, since only the paychecks left catch up.
- **From January:** a full year at the same pay, using this year's tables. Check again once next year's are
  confirmed.

**Advance tax** (1040-ES):
- **Due dates:** Apr 15, Jun 15, Sep 15 and Jan 15, moved to the next weekday when they fall on a weekend.
- **What's needed:** the total tax less withholding and refundable credits.
- **Paid so far:** tagged federal estimated payments dated Feb 1 to Jan 31. Each counts for the first quarter due on or
  after it.
- **What to pay:** what's left is split over the quarters still ahead.
- **Safe harbor** (§6654(d)): 90% of this year's tax, or 100% of last year's (110% above $150,000 of AGI), whichever
  is less, less withholding. It's shown as the floor by each date. A missed quarter below it with $1,000 or more owed
  is noted (Form 2210).
- **When it shows:** it is the answer when there's no paycheck to change (1099 work). Otherwise it's the folded-away
  alternative.

**State:** the extra state withholding per paycheck that closes the simplified state return, a reduction when it's on
track to refund, or state estimated tax when there's no job.

**The family** (`finance/tax_family.py`, migration `047_tax_units.sql`):
- The family decides who files together (Taxes → Add a return). A married couple filing jointly is one return; everyone
  else files their own.
- A return's records come from its members' shared copies and are added together, with each job and business listed as
  whose it is. Its typed values are saved in the family's library.
- Each return has its own estimate and Tax Zen. The family is Tax Zen when every return is.
- Write-offs and tax rules stay in each person's own profile.

**What If:**
- Each compared plan gets "Tax Zen in <year>": a full year at the pay the plan ends with (its paychecks with no last
  month), in place of your jobs when one replaces pay, with this year's other income and deductions. It shows
  the year-end result with the W-4 in the plan, and the entry that brings it to $0.
- "Now" is this year's return.
- The paycheck planner shows "At tax time" for its paycheck alone.

**API:**
- `GET /api/tax/year/{year}`: gathered, typed, merged, tables, the estimate (`engine` is the slot: `{slot, label,
  version}`), `prior_year` (typed, or last year's return as worked out here), `tipped_occupations` and Tax Zen
  (`w4`, `prior_year_tax`, `zen_job` and `zen_policy` are saved with the typed values).
- `GET /api/tax/family/{year}`, `PUT /api/tax/family/{year}/{unit}`, `POST /api/tax/units`, `DELETE /api/tax/units/{id}`
- `PUT /api/tax/year/{year}`: your typed values.
- Both mark the year's Tax Zen as seen. Tax Zen in the response carries `range`, `changed`, `cushion` (AT_RISK) and,
  per job, `payroll`, `recommendations` and `steady`.
- `GET /api/dashboard`: `attention.tax` is this year's Tax Zen when it got worse since last seen, else null.
- `GET /api/finance/health`: `tax_engines` says whether each engine can run here.
