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
- Every yearly figure comes from a quoted lookup confirmed in Review.
- Figures fixed in law are constants citing the statute.
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

`finance/tax_year.py` (gather and merge), `finance/tax_return.py` (the estimate), `household/tax_figures.py` (the year's
figures), migration `046_tax_figures.sql` (`tax_figure_sets`, `tax_years`). This is the Taxes page's first panel.

**Gathered from records** (each field names its source on the page):
- **Jobs:** one per employer, from this year's confirmed pay stubs.
  - Year to date comes from the latest stub's printed figures when every line has one; otherwise the year's stubs are
    added up.
  - The latest stub's paycheck is then added for each payday left this year, counted from the pay frequency and the
    last pay date.
  - From these: wages (gross less pre-tax deductions), Social Security and Medicare wages (gross less health, dental,
    vision, HSA and FSA), and federal, state and Medicare withheld.
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

**Typed over the records** (saved per year): any field, any job's figures, jobs not in your pay stubs (a spouse's),
your spouse's birth year, children and dependents, and the deduction choice.

**Yearly figures:**
- The figures the brackets don't hold: capital-gains 0% and 15% thresholds, child tax credit and its refundable limit,
  credit for other dependents, additional standard deduction at 65, senior deduction, student-loan phase-out, SALT
  limit and phase-down start, QBI threshold, educator limit, IRA and HSA limits, dependent care limits and rates, and
  energy credit rate and limit.
- **Look up:** the local model searches irs.gov, quotes every number from a page it opened, and proposes the set. It
  waits in Review as "Tax figures to confirm".
- **Type in:** a figure you type counts at once and replaces the looked-up one.
- A figure that's missing is named, and the line that needs it says what was left out. Nothing is assumed.

**The estimate, in Form 1040 order:**
1. **Income:** wages, interest, dividends, capital gain or loss (a net loss counts up to $3,000; the rest carries
   over), taxable retirement distributions, Schedule C profit or loss, unemployment, HSA money not spent on medical
   care, other income, and taxable Social Security (the §86 worksheet: 50%/85% above $25,000/$34,000, or
   $32,000/$44,000 married filing jointly).
2. **Adjustments:** educator expenses (capped), HSA, half of self-employment tax, self-employed health insurance, IRA,
   student-loan interest (at most $2,500, phased out by the year's figures), and others.
3. **Deduction:** the standard deduction from the tax table (plus the 65+ amount), or itemized, whichever is larger
   unless you choose.
   - Itemized: medical above 7.5% of AGI; state and local taxes up to the SALT limit (shrinking 30% of MAGI above its
     start, not below $10,000); mortgage interest; charity; other.
   - The senior deduction (with its 6% phase-out) and other deductions you type come off too.
4. **QBI deduction:** 20% of business profit less half of SE tax and SE health insurance, limited to 20% of taxable
   income less gains. Above the threshold it isn't modelled, and the page says so.
5. **Tax:** the Tax Table below $100,000 of taxable income (the tax at the middle of each $50 row, rounded to the
   dollar) and the Tax Computation Worksheet above. Qualified dividends and long-term gains use the Qualified Dividends
   and Capital Gain Tax Worksheet at 0/15/20%.
6. **Credits:**
   - Dependent care: the rate falls 1 point per $2,000 of AGI above $15,000, from the year's high rate to its low.
   - Education: AOTC 100% of $2,000 plus 25% of the next $2,000, 40% refundable; lifetime learning 20% of up to
     $10,000; both phased out at $80,000–$90,000, or $160,000–$180,000 married filing jointly.
   - Energy, and other credits.
   - Then the child tax credit and credit for other dependents: $50 less per $1,000 of AGI above $200,000, or
     $400,000 married filing jointly. Its refundable part is up to the year's limit per child, and 15% of earned
     income above $2,500.
7. **Other taxes:**
   - Self-employment tax: 92.35% of profit; 12.4% up to the wage base less that person's W-2 Social Security wages,
     plus 2.9%; none under $400.
   - Additional Medicare: the table's rate above its threshold, on wages plus self-employment earnings.
   - Net investment income tax: 3.8% above $200,000, or $250,000 married filing jointly.
   - 10% on early distributions, and 20% on HSA money not spent on medical care.
8. **Payments:** withholding (every job, and 1099 box 4), additional Medicare withheld, estimated tax paid, and
   refundable credits. The result is the refund, or the amount owed.
9. **State (simplified):** federal AGI less the state's deduction (or yours), the state's brackets, less state credits,
   against state withholding and estimated payments.

**Not modelled** (said on the page):
- the alternative minimum tax;
- the QBI deduction above its threshold;
- IRA deductibility limits (enter the deductible part);
- charity and mortgage-interest limits;
- 28% and unrecaptured §1250 gains;
- credits not listed.

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
  unconfirmed tags and tax forms, missing figures or unconfirmed tax tables, shares sold with no purchase lot, amounts
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

**Paychecks ahead:**
- Jobs come from pay stubs. Every payday after the latest stub counts in the year's totals (paid like that stub, whether
  or not its stub is here yet). Only paydays after today can change with a new W-4.
- Each paycheck's federal withholding is worked out as payroll does: IRS Publication 15-T's annual percentage method for
  a 2020+ W-4 (Step 2's half-size schedule, Step 3 credits a year, 4(a) other income, 4(b) deductions, 4(c) extra per
  paycheck).
- That result is matched to what the latest stub actually withholds. The difference is kept, so a W-4 you haven't
  entered, or a payroll quirk, carries into the answer.
- Enter the W-4 on file ("Your W-4 there now") and the answer is the new total for the box.

**The answer, for one job** (the largest paycheck by default; you can choose another):
- **Owing:** raise Step 4(a) other income. **Getting a refund:** raise Step 4(b) deductions.
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
  month), in place of your jobs when one replaces pay, with this year's other income, deductions and figures. It shows
  the year-end result with the W-4 in the plan, and the entry that brings it to $0.
- "Now" is this year's return.
- The paycheck planner shows "At tax time" for its paycheck alone.

**API:**
- `GET /api/tax/year/{year}`: gathered, typed, merged, figures, tables, the estimate and Tax Zen (`w4`,
  `prior_year_tax` and `zen_job` are saved with the typed values).
- `GET /api/tax/family/{year}`, `PUT /api/tax/family/{year}/{unit}`, `POST /api/tax/units`, `DELETE /api/tax/units/{id}`
- `PUT /api/tax/year/{year}`: your typed values.
- `PUT /api/tax/figures/{year}`: typed figures.
- `POST /api/tax/figures/{year}/lookup`
- `GET /api/tax/figure-sets?status=`, `POST /api/tax/figure-sets/{id}/review`
