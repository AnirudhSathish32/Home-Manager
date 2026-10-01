# Home Manager: tax rules as implemented (for CPA review)

*Prepared 2026-09-30 from the source code, not just the design docs.*

## About this document
Home Manager is a personal finance app. It estimates a household's federal return (and a simplified state return)
during the year and suggests W-4 changes or estimated payments so the return comes out near $0. This document lists,
rule by rule, what the code actually calculates, so it can be compared with current tax law.

Items marked **⚠** are places where the implementation may differ from the law, or where the law changed recently
(the One Big Beautiful Bill Act, July 2025). These are the developer's reading and need a CPA to confirm them.

Abbreviations:
- **MFJ:** married filing jointly
- **MFS:** married filing separately
- **HOH:** head of household
- **SE:** self-employment
- **OBBBA:** the One Big Beautiful Bill Act

Source files (under `src/home_manager/`): `finance/tax_return.py` (1040 estimate), `finance/tax_year.py` (gathering), `household/tax_figures.py`,
`household/tax_tables.py` (yearly figures), `finance/tax_zen.py` (W-4 and estimated tax), `finance/paystub.py`,
`finance/paycheck.py` (withholding and FICA), `finance/tax_lots.py`, `finance/tax_lines.py`, `finance/tax_tags.py`,
`finance/tax_family.py`, `finance/retirement.py`, `finance/forecast.py`.

---

## 1. Where the numbers come from
- **Yearly figures are never hard-coded.** Brackets, standard deduction, Social Security rate and wage base, Medicare
  rate, and the Additional Medicare rate and threshold come from a tax-table lookup per year and filing status
  (`tax_tables.py`). Other indexed figures come from a figures lookup (`tax_figures.py`).
  - In both lookups, the local model searches irs.gov or ssa.gov, and every number must appear in an exact quote from a
    page it opened. The set stays proposed until the taxpayer confirms it in Review. Typed figures override.
  - Looked-up figures: 0% and 15% capital-gain thresholds, CTC per child and refundable max, ODC, additional standard
    deduction for 65+, senior deduction, student-loan phase-out start and end, SALT cap and phase-down start, QBI
    threshold, educator max, IRA limit and catch-up, HSA self/family limits and catch-up, dependent-care expense limits
    (one, two or more) and high/low rates, energy home-improvement rate and cap.
  - A missing figure is named on the page, and the line that needs it is left out, never guessed.
- **Statutory constants** (`tax_return.py:21-43`): SE 92.35%, $400 SE floor; NIIT 3.8% above $200k/$250k; medical
  floor 7.5%; $3,000 capital-loss limit; 10% early-distribution and 20% HSA penalties; §86 bases $25k/$34k
  ($32k/$44k MFJ); QBI 20%; CTC phase-out $200k/$400k at $50 per $1,000; ACTC 15% above $2,500; dependent-care rate
  steps from $15,000 in $2,000 steps; AOTC $2,000 + 25% of $2,000, 40% refundable; LLC 20% of $10,000;
  education phase-out $80–90k ($160–180k MFJ); student-loan max $2,500; SALT phase-down 30%, floor $10,000;
  senior phase-out $75k/$150k at 6%; supplemental withholding 22%, and 37% over $1M.
- Arithmetic: exact integer cents, rounded half-even. The Tax Table method applies below $100k of taxable income.
- **Filing statuses supported:** Single, Married Filing Jointly, Head of Household.
  - **⚠ Not supported:** Married Filing Separately and Qualifying Surviving Spouse. HOH uses the single amounts for
    NIIT, CTC, §86 and the education phase-outs (which is correct law for those items).

## 2. Federal return estimate — Form 1040 order (`tax_return.estimate`)
### Income
| Line | Implemented | ⚠ Notes for CPA |
|---|---|---|
| Wages | Sum of W-2 box 1 per job (from pay stubs: gross less pre-tax deductions, projected to Dec 31) | Projection assumes every remaining paycheck equals the latest stub |
| Taxable interest | Bank interest + taxable-account interest, projected to Dec 31 at year-to-date pace; 1099-INT box 1 replaces it | 1099-INT box 3 (Treasury interest) is not separated for state purposes |
| Ordinary / qualified dividends | 1099-DIV 1a / 1b, else projected dividends; qualified = 0 unless typed | |
| Capital gain/loss | ST + LT − prior carryover; net loss limited to $3,000; excess noted | **⚠** Carryover is not split ST/LT, and the excess isn't carried to next year automatically. No 28% collectibles or unrecaptured §1250 gain |
| Retirement distributions | 1099-R box 2a, else withdrawals from tax-deferred accounts | Roth / basis / rollover handling isn't modelled (the taxpayer types the taxable part) |
| Schedule C | Per business: tagged income − tagged expenses (meals at 50%) | No home office, depreciation/§179, vehicle mileage method, inventory/COGS |
| Unemployment, other income | Typed | |
| HSA non-qualified distributions | Typed, added to income | |
| Taxable Social Security | §86 worksheet, 50%/85% tiers; provisional income excludes the student-loan adjustment | |
| **Not modelled** | Schedule E (rentals, K-1), alimony, gambling, foreign income/exclusion, kiddie tax, cancellation of debt | |

### Adjustments (Schedule 1 Part II)
- Educator expenses, capped at the figure (×2 for MFJ). **⚠** Doubling assumes both spouses are eligible educators.
- HSA contributions (not through payroll). **⚠** The HSA limits are looked up but **not applied**.
- Half of SE tax.
- Self-employed health insurance. **⚠** Not limited to Schedule C profit.
- Traditional IRA. **⚠** The IRA limit is looked up but not applied, and there's no deductibility phase-out (the taxpayer
  enters the deductible part).
- Student-loan interest: $2,500 max, phased out on MAGI (total income − other adjustments) by the year's figures.
- Other adjustments: typed.
- **Not modelled:** SEP/SIMPLE/solo-401(k) deduction, early-withdrawal penalty, alimony, moving (military).

### Deduction
- Standard deduction from the tax table, plus the 65+ amount per person aged 65+ (calendar-year approximation).
  - **⚠** No blindness addition.
  - **⚠** No dependent's limited standard deduction.
- Itemized deductions, whichever is larger unless the taxpayer chooses:
  - Medical above 7.5% of AGI.
  - SALT: income + property tax capped at the figure. The cap shrinks by 30% of AGI above the phase-down start, with a
    $10,000 floor. **⚠** Uses AGI as MAGI. No sales-tax election.
  - Mortgage interest, in full. **⚠** No $750k / $1M acquisition-debt limit.
  - Charity (cash + goods), in full. **⚠** No 60/30/20% AGI limits and no carryover.
  - Other itemized.
- Senior deduction (OBBBA §151(f)): figure × each person 65+, less 6% of AGI above $75k/$150k per person.
  - **⚠** The SSN requirement isn't checked.
  - **⚠** The 2025–2028 window is enforced only by whether the figure exists for the year.
- Other below-the-line deductions (tips, overtime, etc.): typed only.
  - **⚠** No computed no-tax-on-tips or overtime caps.
  - **⚠** No car-loan interest deduction.
- **⚠ OBBBA 2026+ items not modelled:**
  - non-itemizer charitable deduction ($1,000 / $2,000)
  - 0.5%-of-AGI floor on itemized charity
  - 2/37 limit on itemized deductions for the 37% bracket

### QBI (§199A)
- 20% × (Schedule C profit − ½ SE tax − SE health insurance), limited to 20% × (taxable income before QBI − net
  capital gain − qualified dividends).
- Only at or below the threshold. Above it, the deduction is **left out entirely**.
  - **⚠** No phase-in range, W-2 wage/UBIA limits, SSTB rules, QBI loss carryforward, or OBBBA's $400 minimum.
- **⚠** Doesn't reduce QBI by self-employed retirement contributions.

### Tax
- Tax Table (midpoint of $50 rows, $25 rows below $3,000) under $100k; exact Tax Computation Worksheet above.
- Qualified Dividends and Capital Gain Tax Worksheet at 0/15/20% using the looked-up thresholds; the result is the
  lesser of the worksheet and the regular tax.
- **⚠ Not modelled:**
  - AMT
  - Schedule D Tax Worksheet (28% and §1250)
  - Form 8615 kiddie tax
  - Form 4972 lump-sum

### Nonrefundable credits (taken in this order)
1. **Child and dependent care (Form 2441):** expenses ≤ the limit (one, or two or more) and ≤ earned income (the lower
   earner's when MFJ). The rate starts at the high figure and drops 1 point per $2,000 over $15,000, down to the low
   figure.
   - **⚠** Employer dependent-care FSA benefits aren't subtracted from the limit.
   - **⚠** OBBBA's 2026 two-tier phase-down (50% → 35% → 20%) can't be represented: there is one step-down only.
2. **Education (Form 8863):** AOTC per student (max $2,500), LLC 20% of up to $10,000 per return; both phased out
   linearly over the fixed ranges. 40% of the AOTC is moved to refundable.
   - **⚠** No check of student age or support rules for refundability.
   - **⚠** Scholarships and 529 coordination are not modelled.
3. **Energy-efficient home improvement (Form 5695, §25C):** rate × expenses, capped at one yearly cap.
   - **⚠** No per-item sub-caps (windows, doors, heat pumps, audits).
   - **⚠** Per OBBBA, this credit ends for property placed in service after 2025. The code relies on the figure lookup
     finding nothing for 2026.
4. **Other credits:** typed.
5. **CTC/ODC:** per child or dependent, reduced $50 per $1,000 (or part) of AGI over $200k/$400k, limited by the tax
   left.
   - **⚠** No SSN or age checks; the taxpayer enters counts.

### Other taxes (Schedule 2)
- **SE tax per person:** 92.35% of combined profit. Social Security part at 2× the employee rate, up to the wage base
  less that person's W-2 SS wages. Medicare part at 2× the rate. Nothing if net earnings are under $400.
  - **⚠** No farm or optional methods, no church-employee income.
- **Additional Medicare (Form 8959):** rate × (Medicare wages + SE earnings − the threshold from the table).
- **NIIT (Form 8960):** 3.8% × min(interest + ordinary dividends + positive net gain, AGI − threshold).
  - **⚠** Excludes rents, royalties, passive K-1 and annuities. Uses AGI as MAGI. No investment-expense deduction.
- **10% early distribution (§72(t)):** applied to all distributions when (year − birth year) < 59, with no exceptions
  unless the taxpayer types 0.
  - **⚠** 59½ is approximated by birth year.
  - **⚠** No 25% SIMPLE-IRA rule.
- **20% HSA penalty:** **⚠** No exception at 65+ or for disability.
- **⚠ Not modelled:**
  - household employment tax (Schedule H)
  - uncollected FICA on tips
  - first-time homebuyer credit repayment
  - excess advance premium tax credit repayment

### Payments and refundable credits
- Federal withholding from every job, plus 1099-INT/DIV box 4.
  - **⚠ 1099-R box 4 withholding is not gathered** (`tax_year.py:172`); it has to be typed.
- Additional Medicare withheld = Medicare withheld − 1.45% × Medicare wages.
- Estimated payments: tagged federal payments dated Feb 1 – Jan 31.
- ACTC: min(the child credit not used, per-child refundable max, 15% × (earned income − $2,500)).
  - **⚠** The alternative 3+ children Social Security method is not modelled.
- Refundable AOTC (40%) and other refundable credits (typed).
- **⚠ Not modelled:**
  - **Excess Social Security withheld** (two or more employers over the wage base)
  - **EITC**
  - Premium tax credit
  - Saver's credit
  - Foreign tax credit (1099-DIV box 7 ignored)
  - Adoption credit
  - Residential clean energy (§25D)
  - Clean vehicle credit: the `clean_vehicle` tag exists, but it isn't wired into the return. OBBBA ended §30D for
    vehicles acquired after Sep 30, 2025.
  - Credit for the elderly

### State return (simplified)
- Federal AGI − state standard deduction (from the state table, or typed) → state brackets − typed state credits,
  compared with state withholding + state estimated payments.
- **⚠** No state additions or subtractions (e.g. Treasury interest, state treatment of 401(k)/HSA), no personal
  exemptions unless typed as credits, no multi-state or part-year, no reciprocity, no local income tax on the return.
- No-wage-tax states: AK, FL, NV, NH, SD, TN, TX, WA, WY.

## 3. Withholding and payroll (`paystub.py`, `paycheck.py`)
- **Income tax per paycheck:**
  - Annualize (wages × pay periods + W-4 4(a)).
  - Subtract the standard deduction and 4(b).
  - Apply the brackets, subtract Step 3 credits, divide by periods, add 4(c).
  - The Step 2 checkbox halves the standard deduction and all bracket starts.
  - This mirrors Pub 15-T's annual percentage method for 2020+ W-4s, using the return's tax brackets instead of Pub
    15-T's own tables. **⚠** No whole-dollar rounding between steps. No pre-2020 W-4 (allowances).
- **Supplemental wages (bonuses):** 22% flat; 37% above $1M of the year's supplemental wages. The state supplemental
  rate is typed.
- **FICA:**
  - Social Security at the rate up to the wage base, tracked check by check.
  - Medicare 1.45%, plus Additional Medicare above the threshold.
  - **⚠** Payroll must start Additional Medicare withholding at **$200,000 regardless of filing status**. The code uses
    the threshold from the filing-status table, so an MFJ table would give $250,000.
- **Pre-tax treatment:**
  - 401(k) lowers income-tax wages only.
  - Health, dental, vision, HSA and FSA also lower FICA wages.
  - An unnamed "other" pre-tax line lowers income-tax wages only.
  - Roth 401(k) is post-tax.
- **State withholding:** the state table, or a flat rate; the state deduction, credits and extra withholding are
  typed. Local tax is a % of taxable or gross wages, or a fixed amount. State disability insurance is supported.

## 4. Tax Zen and estimated tax (`tax_zen.py`)
- **W-4 search:** for one job, a whole-dollar search on 4(a) (owing) or 4(b) (refund) that lands the return within $1
  of $0, plus a 4(c) per-check alternative.
  - Two answers: the rest of this year, and from January (a full year at the same pay).
  - The model's withholding is calibrated to the actual stub; the difference carries over.
- **1040-ES:**
  - Due Apr 15, Jun 15, Sep 15, Jan 15, shifted for weekends. **⚠** Not shifted for holidays (e.g. DC Emancipation
    Day).
  - What's left is split evenly over the quarters ahead.
  - **Safe harbor §6654(d):** the lesser of 90% of this year's tax or 100% of last year's (110% if last year's AGI was
    over $150k), less withholding. The penalty note applies only when $1,000+ is owed.
  - **⚠** No annualized-income installment method (Form 2210 Schedule AI).
  - **⚠** The MFS $75k threshold isn't relevant (MFS isn't supported).
  - Withholding is treated as paid evenly; the code doesn't model it that way explicitly.
- **State:** extra withholding per paycheck, or state estimated tax (federal due dates assumed).

## 5. Investments, gains and retirement
- **Tax lots:** FIFO only (no specific identification or average cost for mutual funds). Holding period over one year
  is long-term (Feb 29 handled). Only taxable accounts. Sales not covered by a lot are reported, not guessed.
  - **⚠** No wash-sale disallowance.
  - **⚠** No 1099-B adjustments (box 1g).
  - **⚠** No inherited or gifted basis rules.
  - **⚠** Return-of-capital distributions don't reduce basis.
- **Forms read:** 1099-INT, 1099-DIV, 1099-B, 1099-R, 1099-SA, 5498, 5498-SA. These are used for cross-checks and some
  return lines.
- **Tax treatments:** taxable, tax-deferred, tax-free (Roth), HSA.
- **RMDs (`retirement.py`):** Uniform Lifetime Table (2022+). Start age 72 (born ≤1950), 73 (1951–1959),
  75 (1960+); based on the prior year-end balance.
  - **⚠ Not modelled:** the April 1 first-year deferral, the still-working exception, inherited IRAs (10-year rule),
    the joint-life table for a spouse more than 10 years younger, and QCDs.
- **Forecast (`forecast.py`):** retirement withdrawals come from taxable → tax-deferred → tax-free → HSA. **A single
  flat, taxpayer-entered % applies only to tax-deferred withdrawals.**
  - **⚠** No tax on taxable-account gains or dividends, Social Security taxation, brackets, IRMAA, Roth conversions or
    state tax in the forecast.

## 6. Data entry and tags (`tax_lines.py`, `tax_tags.py`)
Ledger items can be tagged to these return lines:
- Schedule C lines 1, 6, 8–27a (meals at 50%).
- Schedule A lines 1, 5a, 5b, 8a, 11, 12, 16.
- Schedule 1 lines 11, 13, 17, 20, 21.
- Credit spending: Forms 2441, 8863, 5695, 8936.
- Federal and state estimated tax.

Tags can be set by hand, by rules or by suggestion; only confirmed tags count. **⚠** Schedule C has no line for COGS,
depreciation (line 13), home office (line 30) or vehicle mileage.

## 7. Family
- A tax unit is one person, or two people for MFJ. Members' records are summed; SE tax and earned income stay per
  person. Write-offs stay per profile.

## 8. Not modelled (as stated in the docs)
- AMT
- QBI above its threshold
- IRA deductibility limits
- Charity and mortgage-interest limits
- 28% and §1250 gains
- Unlisted credits
- 529 plans, crypto, pensions, I bonds
- Forecast taxes beyond the flat rate

There is no further roadmap for tax law in the docs.

## Suggested questions for the CPA (highest impact first)
1. Excess Social Security credit, EITC, MFS/QSS, and 1099-R withholding: these are gaps that affect common returns.
2. 2026 OBBBA changes: charity floor and non-itemizer deduction, the 37% itemized limit, the dependent-care rate
   tiers, the end of §25C/§30D, tips/overtime/car-loan interest computations, and the QBI $400 minimum.
3. Additional Medicare withholding threshold ($200k payroll vs the filing-status threshold).
4. Limits not enforced: HSA/IRA contributions, mortgage debt, charity AGI %, SE health insurance ≤ profit.
5. Above-threshold QBI, AMT exposure, and the wash-sale / specific-ID needs for the taxpayer's situation.

## Notes for the reviewer
- Every ⚠ item points to the source file where the rule lives. Constants are in `finance/tax_return.py`.
- Yearly figures (brackets, limits and thresholds) are confirmed by the taxpayer from quoted IRS pages. Checking the
  confirmed 2026 figures against the Revenue Procedure is a separate task.
