# Taxes

The Taxes page (`static/taxes.js`) is where the year's taxes come together:
- **Tax tags:** ledger items marked as write-offs, business income, spending for a credit, or tax paid ahead.
- **The year's return:** every income source, deduction, credit and tax, in Form 1040 order, worked out by the tax
  engines.
- **Tax Zen:** the W-4 entries (or quarterly estimated payments) that bring the year to the aim (a $0 refund by
  default), per tax return. It also appears for each What If plan and in the paycheck planner
  ([planning](planning.md#what-if)).
- **The CPA pack:** one Excel workbook for the year, to hand to an accountant.

Pay stubs, the Jobs folders and the paycheck tax tables are in [Jobs and pay stubs](#jobs-and-pay-stubs). Investment
tax forms and lots are in [planning](planning.md#tax-lots-gains-and-tax-forms).

**Principles**
- **A tax return is the unit that reaches the aim:** a single filer, or a married couple filing jointly.
- **The federal return's law comes from the engines.** Engine 1 cites the rule for every line, and Engine 2 checks it.
  The tax tables for pay stub withholding come from a quoted lookup that you confirm in Review.
- **Figures fixed in law** that the app itself uses are constants citing the statute.
- **Nothing is guessed.** An engine that needs a fact no record gives asks for it.

## Design

Tax Zen and the engines follow a design written before they were built (2026-10-03). The parts that shaped the code:

- **Separate responsibilities.** No single "tax service". The pieces are:
  - the **tax engine** (liability: `finance/tax_engine.py` and its adapters);
  - the **safe harbor** (penalty rules: `finance/safe_harbor.py`);
  - the **withholding engine** (payroll: `finance/withholding.py`, Pub 15-T);
  - the **W-4 search** and the **Tax Zen** controller that coordinates them (`finance/tax_zen.py`).

  The UI and the assistant consume Tax Zen's result object and never reconstruct its calculations.
- **Engines are replaceable dependencies.**
  - The app owns the interface and the schemas, and the adapter owns everything engine-specific.
  - Each engine declares its capabilities (years, filing statuses, features), which are checked before it runs. An
    unsupported return fails explicitly rather than being approximated.
  - Changing engines must not change the page, the database, the assistant, Tax Zen or past records.
  - The withholding engine follows the same rule. The IRS Withholding Estimator could be added later behind the same
    shape.
- **Several objectives, not just $0.** The aim is a policy: $0, a small refund, keep cash (owe up to a limit less a
  buffer), or owe what the safe harbor allows.
- **The $1,000 rule is not the whole safe harbor.** The safe harbor is worked out on its own, from this year's tax,
  last year's tax and AGI, the high-income rule and payment timing. Withholding and estimated payments are timed
  differently.
- **A control system with damping.** Tax Zen is re-evaluated whenever its inputs change (a new stub, a tax form, a
  tag, a typed value), but it interrupts rarely:
  - a status band that takes 1.5 times its width to leave;
  - a W-4 answer that changes only for $25 or more a paycheck, a worse status or a material change;
  - Home is told only when the status gets worse.
- **Uncertainty, not a point estimate.** The likely range is worked out, and a result whose low end owes $1,000 or more
  is AT_RISK even when the middle is fine. A buffer steers toward owing $599 rather than $999.
- **The simplest valid W-4.** The first answer is one box (Step 4(c) extra a paycheck, then 4(a)), and the fewest boxes
  changed wins. Every answer is checked by working the return out again with that withholding (the round trip), and
  recommendations account for when a new W-4 takes effect.
- **The model explains; it never computes.**
  - The assistant's `get_tax_zen_status` returns the deterministic result, and the model only explains it. So a ~20B
    local model needs good tool choice and explanation, not tax expertise.
  - "Why did Tax Zen change?" is answered from recorded differences, never from a chain the model invents.
- **Facts, projections and entries are labelled.** Each value says whether it is from records, worked out from
  records, projected to Dec 31, waiting for you to enter it, or typed by you.
- **Reproducible.** Every distinct calculation is kept with its engine version and inputs, and evaluations are kept as
  history. A new engine version adds rows; it never rewrites old ones.
- **No network for calculations.** Engines run as local processes. Engine 1's telemetry is switched off by
  environment variables, and updates are separate from calculations.
- **Dependencies are pinned and audited.** Each is pinned with its hash, its outbound calls are reviewed, it is
  sandboxed where possible, and its version is kept with each calculation. Licenses are checked before anything ships
  (see [The tax engines](#the-tax-engines)).
- **Recommend, don't submit.** The app recommends W-4 changes; you hand the W-4 to payroll.

## Tax tags

Code: `finance/tax_tags.py`, `finance/tax_lines.py`, migration 045 (`businesses`, `tax_rules`, `tax_tags`).

**What a tag says.** There is one tag per item: a bank line, a receipt, or one line of a receipt. Each tag has a kind
and a line:

| Kind | Lines | Goes to |
|---|---|---|
| Business income | gross receipts (1099-NEC, 1099-K, clients), other | Schedule C lines 1, 6 |
| Business expense | advertising, car and truck, commissions, contract labor, insurance, interest, legal and professional, office and software, rent or lease, repairs, supplies, taxes and licenses, travel, meals (50% counts, IRC §274(n)), utilities and phone, wages, other | Schedule C lines 8–27a |
| Itemized deduction | medical and dental, state and local income tax, property tax, mortgage interest, charity (cash), charity (goods), other | Schedule A |
| Adjustment to income | educator expenses, HSA contribution not through payroll, self-employed health insurance, traditional IRA, student-loan interest | Schedule 1 |
| Spending for a credit | child and dependent care, tuition, energy-efficient home improvement, clean vehicle | Forms 2441, 8863, 5695, 8936 |
| Tax paid ahead | federal estimated tax (1040-ES), state estimated tax | Form 1040 line 26; state return |

- **Businesses.** Business kinds name a business. Contract (1099) work is a business to the IRS even without a company,
  and each business gets its own Schedule C.
- **Amount.** A tag counts the whole item unless you enter the part that counts. Limits that depend on the whole return
  (medical above 7.5% of AGI, the SALT cap, the student-loan cap) are applied by the engines, not per item.
- **Direction.** Business income is money coming in; every other kind is money going out.

**Three ways to tag**
- **By hand**, in the transaction drawer (Taxes section) or on a receipt (the whole receipt or one of its lines). It
  counts at once, and no rule changes it.
- **Tax rules**, such as "every bank line containing ADOBE CREATIVE is an office expense of Contract work".
  - Rules are matched like category rules: every word of the pattern must appear in the line's description and
    merchant name. The rule with the most words wins, then the newest. A rule can be limited to one account.
  - A rule for money out never tags money in.
  - Rules run when lines are imported or added, after reconciling, and whenever a rule changes.
  - Deleting a rule removes its tags, and those lines can then be suggested.
  - Rule tags count at once.
- **Suggestions**, made when lines arrive or are reconciled:
  - A bank line from a payee whose line you tagged before gets the same kind, line and business. The payee is the
    line's first three normalized words, as recurring-bill detection uses.
  - A payment that looks like tax paid ahead is suggested: IRS Direct Pay ("IRS USATAXPYMT") or EFTPS as federal
    estimated tax, and a state department of revenue or taxation as state estimated tax.
  - Each suggestion waits in Review under **Possible write-offs and tax payments**, with the reason. The choices are
    **Tag it** (optionally "Also tag every bank line containing…", which makes a rule) and **Not a write-off**.
  - A "not a write-off" answer is kept, so that payee isn't suggested again. Decisions are audited in `review_events`.

**Each item counted once in a year** (`TaxTags.year`)
- Only confirmed tags count, and only on items that count: not on a rejected bank line, and only on a verified
  receipt.
- Tags on a receipt's lines replace a tag on the receipt, and a receipt's tags replace a tag on the bank line it's
  matched to. The page notes each case.
- The page lists the year by kind, line and business (amount and the part that counts), every tagged item, the tax
  rules, and the businesses.
- Schedule C has no line yet for cost of goods sold, depreciation (line 13), home office (line 30) or vehicle mileage.

**API:** `GET /api/tax/setup` · `POST /api/tax/businesses`, `PUT|DELETE /api/tax/businesses/{id}` (delete archives: its tags keep counting and the
items and rules that have it keep it, but no new tag or rule can use it) ·
`GET /api/tax-tags?status=&year=&kind=&receipt_id=`, `GET /api/tax-tags/on/{type}/{id}`, `POST /api/tax-tags` ·
`POST /api/tax-tags/{id}/not-a-write-off`, `POST /api/tax-tags/{id}/review` · `GET|POST /api/tax/rules`,
`PUT|DELETE /api/tax/rules/{id}` · `GET /api/tax/write-offs/{year}`.

## The year's return

Code: `finance/tax_year.py` (gathers and merges the facts), `finance/tax_engine.py` (the engine interface),
`finance/tax_return.py` (the profile and the simplified state return). Migration 046 created `tax_years`. Its
`tax_figure_sets` table belonged to the retired figures lookup and is no longer used. This is the Taxes page's first
panel.

- **Engine 1** works out the federal return on this computer. **Engine 2** (optional) checks it line by line. The page
  names the engines by number, never by product name (see [The tax engines](#the-tax-engines)).
- **Coverage.** Both engines cover 2025 and 2026 returns.
  - Engine 2 works out a return that Engine 1 doesn't cover (both spouses self-employed, more than three AOTC students,
    other credits typed in), and the page says so.
  - A year or a case that neither engine covers gives no estimate, and the page names the reason.
- **Each distinct result** is kept in `tax_calculations`.
- **The federal tax table** (Review → "Tax tables to confirm") is still used for pay stub withholding (Pub 15-T),
  Tax Zen's W-4 answers, and the marginal rate shown on the page.

**Gathered from records** (each field names its source on the page):
- **Jobs:** one per employer, from this year's confirmed pay stubs.
  - Year-to-date figures come from the latest stub's printed figures when every line has one. Otherwise the year's
    stubs are added up.
  - The latest stub's paycheck is then added for each payday left this year, counted from the pay frequency and the
    last pay date.
  - The gathered figures are: wages (gross less pre-tax deductions); Social Security and Medicare wages (gross less
    health, dental, vision, HSA and FSA); federal, state and Medicare tax withheld; and HSA money through payroll (yours
    and the employer's).
- **Interest:** bank interest lines plus interest in taxable investment accounts. I bond and Treasury interest is
  reported separately as `us_obligation_interest`.
- **Dividends:** dividends in taxable accounts.
  - Interest and dividends are counted so far and projected to Dec 31 at the same pace.
  - Confirmed 1099-INT and 1099-DIV forms replace them.
  - Qualified dividends come from 1099-DIV box 1b; until it arrives, you type them.
- **Capital gains:** realized short- and long-term gains in taxable accounts (tax lots), including 1099-B and 1099-DA.
- **Retirement distributions:** withdrawals from tax-deferred accounts, or 1099-R box 2a. They count as early before
  59½, judged from your birth year.
- **529 plans:** non-qualified withdrawals' taxable earnings go to other income.
- **1099 withholding:** box 4 of 1099-INT and 1099-DIV. 1099-R box 4 isn't gathered yet; type it.
- **From tax tags:** each business's income and expenses (Schedule C), adjustments, itemized deductions, credit
  spending (dependent care, tuition, energy), and estimated tax paid (federal and state).
- **Work state:** from the latest stub.

**Engine facts filled from records** (so the engine doesn't have to ask):
- **Form 1098** (migration 059): box 1 gives the mortgage interest and box 10 the property tax, when no tag already
  counts them.
- **The mortgage's average balance** (Pub 936; it limits interest above $750,000), worked out by the first method that
  has what it needs:
  1. the average of 1098 box 2 (principal on Jan 1) and the mortgage's balance on Dec 31;
  2. 1098 box 2 alone, as an upper bound;
  3. the year's interest divided by the mortgage's yearly rate.

  "The mortgage" is a confirmed loan whose name says mortgage, home loan, home equity or HELOC. Its Dec 31 balance is
  projected from its recorded balance, rate and monthly payment, as the forecast does.
- **HSA coverage.** The year's HSA contributions are compared with the self-only limit (IRC §223(b), $1,000 more from
  age 55).
  - The contributions are 5498-SA box 2 once it arrives. Until then, they are payroll HSA lines projected to Dec 31
    plus your own tagged contributions.
  - At or under the limit, coverage is taken as self-only, since the coverage doesn't change the deduction at that
    amount. Over it, family.
- **Ages:** your birth year (Settings). In the family view, each member's birth year comes from their own Settings
  (sent with their published copy) for the two people on a joint return.
- **Last year's tax and AGI** (for the estimated-tax safe harbor): last year's return as worked out here, until you
  type the filed return's figures.

**Typed over the records** (saved per year):
- any field, any job's figures, and jobs not in your pay stubs (a spouse's);
- your spouse's birth year, children and dependents;
- itemizing anyway;
- qualified tips (with the tipped occupation from the Treasury list) and the overtime premium.

**Still asked for, because no record says it:** qualifying children and other dependents, the qualified part of
dividends before the 1099-DIV arrives, and which tuition is for whom.

**The estimate, in Form 1040 order:** income, adjustments, the deduction (standard, with the 2026 charitable deduction
for non-itemizers, or itemized), the senior, tips and overtime deductions, QBI, tax, credits, other taxes
(self-employment, Additional Medicare, net investment income tax and the rest), then payments.
- Each line says how it was worked out and cites the rule it follows.
- **Payments** are added up by the app: withholding (every job, plus box 4 of each 1099-INT, 1099-DIV and 1099-R),
  Additional Medicare withheld above
  1.45% (§3101(b)(1)), estimated tax paid, and refundable credits. The result is the refund, or the amount owed.
- **State (simplified):** federal AGI less the state's deduction (or yours), taxed on the state's brackets, less state
  credits, then compared with state withholding and estimated payments.
  - It is labelled simplified, because no full state return is wired up. Engine 1 has full returns for only IL, VA,
    CA, NY and PA.
  - It has no state additions or subtractions (beyond leaving out US-obligation interest), no personal exemptions
    unless typed as credits, no multi-state or part-year returns, no reciprocity, and no local income tax.
  - States with no wage income tax: AK, FL, NV, NH, SD, TN, TX, WA, WY.

**Not covered by Engine 1** (named on the page; Engine 2 works out some of these):
- both spouses self-employed;
- educator expenses on a joint return;
- forcing the standard deduction;
- the energy credit;
- other credits typed in;
- more than three AOTC students.

## The tax engines

The year's return is worked out by a **tax engine** behind one interface, so an engine can be added or replaced
without changing the Taxes page, Tax Zen, What If or the CPA pack.

**Numbered slots.** The app shows engines as numbered slots, never by name: **Engine 1** and **Engine 2**
(`tax_engine.ENGINES`, in order). A new engine would become Engine 3. The implementation behind a slot (its name,
version and pinned SHA-256) is recorded only in `tax_calculations`, this document, `vendor/NOTICES.md` and the adapter.
- **Engine 1 = Invaro OpenTax**, run as a separate, sandboxed Node process. It carries its own yearly law (2025 and
  2026).
- **Engine 2 = PSLmodels Tax-Calculator**, public domain (CC0). It is a Python model of federal income and payroll tax
  maintained by tax economists. It checks every return Engine 1 works out, and works out the returns Engine 1 doesn't
  cover. It is optional: `pip install "home-manager[engine2]"`.
- **Pay stub withholding** (Pub 15-T) is not an engine's job. It stays in the app (`finance/withholding.py`).
- **Retired 2026-10-04:** the hand-written federal return (`builtin`) and its model-driven yearly-figures lookup
  (`household/tax_figures.py`, deleted). You chose to rely on maintained open-source engines alone.
  - Saved settings naming `builtin` or `opentax` load as `engine_1`.
  - Old `tax_calculations` rows keep their engine name.
- **Adding to it later.** Code may be copied in from MIT, Apache or CC0 engines (TelosTax, the IRS Withholding
  Estimator), with their notices. Code copied from an AGPL engine (OpenTax, PolicyEngine) would make Home Manager AGPL
  once distributed. Re-implementing the law from the statute is always fine.

### Engine 1: OpenTax

**Pinned.** `@invaro/opentax` 0.4.0, unmodified from npm, is in `src/home_manager/vendor/opentax/` (`main.js`, the
licenses, and `PIN.json` with the SHA-256 of every file and the npm integrity). The engine is `@invaro/opentax-core`
0.1.0, with corpus `@invaro/opentax-corpus-us-federal` 0.37.0. Never edit these files.

**License.** AGPL-3.0-only (versions ≤ 0.2.1 were Apache-2.0); Invaro Inc. sells a commercial license.
- Personal and family use as an unmodified separate process is fine.
- **Before distributing Home Manager,** do one of these: offer the engine's source with it (AGPL §6), buy the
  commercial license, or replace the `opentax` adapter with an MIT/CC0 engine. Nothing outside the adapter depends on
  OpenTax.

**Audit of `main.js`**
- It makes one outbound call: an anonymous usage ping (event name, version, platform) to `opentax.invaro.ai/api/t`. It
  is off when `OPENTAX_TELEMETRY=0` or `DO_NOT_TRACK=1`, and the adapter always sets both.
- A `signup` command posts an email address; the adapter never runs it.
- `child_process` appears only inside the bundled `commander` library.

**How it runs**
- **The process.** `node --permission --allow-fs-read=<vendor dir> --allow-fs-read=<facts dir>`, with no write
  permission. Node's permission model doesn't block the network, so the opt-out variables are what stop the ping.
- **Requirements.** Node.js 20 or later. `HOME_MANAGER_NODE` can point to a specific `node` executable
  ([operations](operations.md#environment-variables)).
- **The command.** `eval --facts <file> --as-of <year>-12-31 --json`. The tax year comes from `--as-of`. Money goes in as
  dollar strings and comes out in cents.
- **Exit codes:** 0 is an answer; 2 means more facts are needed (named); 3 means not covered by the corpus; 1 is any
  other error.
- **Output.** A proof tree. Each node is a rule (`ruleId`, title, citation with statute and URL, value) or a fact or
  assumption.
  - Every Form 1040 line is a rule: `us.federal.agi`, `.taxable_income`, `.deduction_election`, `.qbi_deduction`,
    `.income_tax_before_credits`, `.ctc`, `.other_taxes`, `.se_tax`, `.niit`, `.additional_medicare_tax`,
    `.refundable_credits`, `.net_tax`, `.amt`, `.eitc`, …
  - The output also lists the `assumptions` (defaults it relied on), the `corpusMerkleRoot` and an `artifactHash`.
- **Payments.** `balance_due` subtracts `federalTaxWithheld` only, not `federalEstimatedPayments`. So the adapter takes
  tax and credits from the engine and adds up payments itself.
- **Adapter** (`finance/engines/opentax.py`):
  - It reads the proof tree into the app's line keys. Lines the tree doesn't name separately go to "other" lines, so
    totals always reconcile. The tips, overtime and car-loan line is what's left of AGI less taxable income before the
    QBI deduction after the deductions above, never below zero. When the deductions are larger than AGI, the taxable
    income line shows the floor as the engine applies it (fixed 2026-10-05: the line used to come out positive).
  - Answers are cached in memory by facts (32 of them). One run takes about 0.3 s.
  - The bundle's hash is checked once, and again whenever its file time or size changes.
- **Rounding.** Engine 1 works Schedule SE in whole dollars, so a hand-worked line, or a second engine's, agrees within
  a dollar (`AGREE_WITHIN`).

**`ReturnInput` → OpenTax facts**

| ReturnInput | Fact(s) | Note |
|---|---|---|
| filing_status | filingStatus (`single`, `mfj`, `hoh`) | The engine also has `mfs` and `qss`; the app doesn't yet |
| jobs[].wages | wages (sum) | |
| jobs[].medicare_wages | medicareWages (sum) | |
| jobs[].ss_wages | socialSecurityWages | **Per person:** only the self-employed person's own box 3 |
| jobs[].federal_withheld, other_federal_withholding | none (payments added by the app) | |
| interest | taxableInterest | |
| tax_exempt_interest | taxExemptInterest | |
| us_obligation_interest | none (state only) | |
| ordinary_dividends, qualified_dividends | ordinaryDividends = 1a − 1b; qualifiedDividends = 1b | The engine's `ordinaryDividends` excludes qualified ones |
| short_term_gain, long_term_gain, capital_loss_carryover | shortTermCapitalGains / shortTermCapitalLoss, longTermCapitalGains / longTermCapitalLoss, or netCapitalLoss | Carryover isn't split ST/LT in the app: it comes off short-term first (Schedule D order), noted |
| retirement_distributions | taxableIraDistributions | Or taxablePensionsAndAnnuities once the app tells them apart |
| early_distributions | earlyDistributionSubjectToPenalty | |
| hsa_nonqualified | hsaDistributions, hsaQualifiedMedicalExpenses = 0 | |
| social_security_benefits | socialSecurityBenefits | |
| unemployment | unemploymentCompensation | |
| other_income | otherOrdinaryIncome | |
| businesses[] (one self-employed person) | selfEmploymentNetProfit or scheduleCNetLoss | **Gap:** two self-employed spouses (Schedule SE is per person; the engine takes one) |
| educator_expenses | educatorExpenses | **Gap:** on a joint return the app doesn't split the two spouses' expenses |
| hsa_contributions, hsa_coverage | hsaContribution, hsaCoverage (self or family, required) | Filled from records, or typed: Adjustments → HSA coverage |
| se_health_insurance | selfEmployedHealthPremiums | The engine applies the earned-income limit |
| ira_deduction | iraContribution, isActivePlanParticipant = false | The field is the deductible part as entered, so the §219(g) phase-out isn't applied again (noted on the page) |
| student_loan_interest | studentLoanInterest | |
| other_adjustments | otherAdjustments | |
| medical | medicalExpenses | |
| state_local_tax + property_tax | stateAndLocalTaxesPaid | |
| mortgage_interest, mortgage_average_balance | mortgageInterestPaid, mortgageAverageBalance (required) | Filled from Form 1098 and the recorded mortgage, or typed: Deductions → Mortgage's average balance |
| charity, charity_noncash | charitableCashContributions, noncashCharitableContributions | From the cash and goods tags |
| other_itemized | otherItemizedDeductions | |
| itemize | forceItemized | **Gap:** forcing the standard deduction when itemizing is larger isn't an input |
| qualified_tips, tipped_occupation, qualified_overtime | qualifiedTips, occupation, qualifiedOvertimePremium | Typed: Deductions. The occupation is a slug from the Treasury Tipped Occupation list (`tax_return.TIPPED_OCCUPATIONS`), required with tips |
| qualifying_children, other_dependents | qualifyingChildren, otherDependents | |
| dependent_care_expenses, dependent_care_people | dependentCareExpenses, careQualifyingIndividuals, secondaryEarnedIncome | The lower earner's earned income comes from jobs by owner |
| students[] | aotcExpensesStudent1–3, llcQualifiedExpenses | At most 3 AOTC students |
| energy_home_expenses | none | **Gap:** OBBBA ended §25C for property placed in service after 2025, so it's 0 for 2026 on |
| other_credits, other_refundable_credits | none | **Gap:** not supported unless 0 |
| federal_estimated_paid | none (payments added by the app) | |
| people[].birth_year | isAge65OrOlder, spouseIsAge65OrOlder, isAge50OrOlder, isAge55OrOlder | |
| prior-year tax and AGI (Tax Zen) | priorYearTax, priorYearAGI | The engine has §6654 too; Tax Zen keeps its own safe-harbor engine |
| state, state_deduction, state_credits | none (separate `state` composer, 5 states) | |

A **gap** makes the result incomplete, with the gap named (`unsupported`). It is never dropped silently.

### Engine 2: Tax-Calculator

**Why this one.** You asked for a reputable, up-to-date second engine. TelosTax (MIT) covered 2025 only and was a young
one-person project. Tax-Calculator (github.com/PSLmodels/Tax-Calculator) is maintained by tax economists:
- release 6.8.4 came out on 2026-10-01;
- it has treated the OBBBA as current law since 5.2.0, and its law runs to 2026 (`Policy.LAST_KNOWN_YEAR`);
- it is public domain (CC0), so it can be used, or copied from, freely.

PolicyEngine-US was the alternative: also reputable, but AGPL and a heavier install.

**How it runs** (`finance/engines/taxcalc.py`, `finance/engines/taxcalc_run.py`)
- **Pinned** to 6.8.4 as the optional `engine2` extra. Readiness says when it is missing or a different version.
- **One record per return.** Each return is run in a child Python process (`python -I taxcalc_run.py`, JSON in and out)
  with `exact_calculations` on, so pandas and numba stay out of the app's process.
  - The first run on a computer compiles the model (about 12 s); after that a run takes about 1.7 s.
  - Answers are cached by record (32 of them).
- **What is recorded.** The calculation records keep the record sent, the model's outputs, the year's law parameters
  read, and the SHA-256 of its `policy_current_law.json`.

**Mapping** (`record_for`)

| Return | Tax-Calculator |
|---|---|
| filing status | `MARS` (1, 2, 4) |
| ages (year less birth year) | `age_head`, `age_spouse` |
| each person's wages (W-2 box 1) | `e00200p`/`s` |
| Medicare wages above box 1 (401(k)-type deferrals) | `pencon_p`/`s` |
| Schedule C profit per owner | `e00900p`/`s` |
| interest, tax-exempt interest | `e00300`, `e00400` |
| dividends, qualified | `e00600`, `e00650` |
| short (less the carryover) and long gains | `p22250`, `p23250` |
| taxable distributions | `e01500`, `e01700` |
| Social Security, unemployment | `e02400`, `e02300` |
| other income and HSA money not spent on care | `e00700` (ordinary income) |
| 10% early-distribution and 20% HSA additional taxes | `e09900` |
| educator, HSA, SE health, IRA, student loan | `e03220`, `e03290`, `e03270`, `e03150`, `e03210` |
| other adjustments | `e03400` |
| medical, state and local tax, property tax | `e17500`, `e18400`, `e18500` |
| mortgage interest | `e19200` |
| charity, cash and goods | `e19800`, `e20100` |
| dependent care and people | `e32800`, `f2441` |
| children and other dependents | `n24`, `nu18`, `EIC` (at most 3), `XTOT` |
| AOTC tentative credit, lifetime learning expenses | `e87521`, `e87530` |
| other credits | `p08000` |
| tips, overtime premium | `tip_income`, `overtime_income` |

**What it takes as given, worked out here from the law**
- **The Tax Table** below $100,000 of taxable income is the rate schedule applied to the middle of the income's row,
  rounded to the dollar, using Tax-Calculator's own rate schedule for the year (`table_tax`). With qualified dividends
  or long-term gains, the worksheet's Tax Table steps aren't redone, so that tax carries a `within` leeway of 22% of $25
  plus a dollar.
- **The mortgage limit** (Pub 936): interest × $750,000 ÷ the average balance.
- **The HSA deduction:** contributions up to the §223(b) limit for the coverage (`tax_year.HSA_LIMITS`), $1,000 more
  from age 55.
- **The AOTC's tentative amount** per student: 100% of the first $2,000 and 25% of the next.
- **The non-itemizer's charitable deduction** is inside its standard deduction. It is shown on its own line, as Engine
  1 shows it.

**It asks rather than guesses** (`needed`), using the same fact ids as Engine 1: the mortgage's average balance, the
HSA coverage, and the tipped occupation. With no birth year, it takes Engine 1's documented default (25 to 64, not 65 or
older) and says so. It asks for the birth year when the earned income credit depends on it.

- **Not covered:** other itemized deductions typed in, and forcing itemizing when the standard deduction is larger.
- **Lines it doesn't work out separately** (left out of comparisons): the SEP deduction, the saver's credit and the
  premium tax credit.

### The engines' worksheets

Every line of the return can show how its engine worked it out, step by step, down to the facts sent and the law. The
`tax.node` trace reads one engine-neutral graph ([ui](ui.md#trace-contract)), and each engine's adapter produces it.

**The graph** (`finance/worksheet.py`). A node is `{id, label, amount_minor, op, inputs, cite, source, when, detail}`,
plus `count`/`value` on a node that isn't money.
- **Ops.** `sum` (signed by `detail.signs`), `difference`, `min`, `max`, `multiply` (`a × b ÷ c` with `detail.divide`),
  `rate`, `round`, `steps` (whole steps of a unit), `lookup` (a rate table, each slice rounded half-up), and the leaves
  `fact`, `law`, `constant` and `opaque`.
- **No `if` nodes.** An `if` or `match` is never a node: the node takes the branch that applied, and `when` says why
  ("Filing status is head of household"). The branch not taken is never shown.
- **Sources.** A `fact` names the `ReturnInput` fields it came from (`[field, sign]`; `jobs.wages` adds up every job's,
  `jobs.0.wages` is one job's), or `{"assumed": …}` for the engine's documented default. A `law` names its parameter,
  year and filing status.
- **One evaluator** runs a rule written in OpenTax's expression language over known values. It uses exact integer cents
  and OpenTax's rounding modes, and stops an `and`/`or` where the engine stops. Both adapters use it.
- **Ids.** OpenTax rule ids, `<rule>~<path>` for a rule's inner steps, `fact:<id>`, `law:<rule>:<param>`,
  `const:money:<cents>`, Tax-Calculator output names, and `line:<key>` for what an adapter or `tax_engine.completed`
  works out itself (residual lines, the deduction less the charitable part, payments: withholding from each job and
  1099, Additional Medicare paid job by job).
- **Lines.** Each line carries `node` beside its `how` (`how` is still shown by the Taxes page and the CPA pack).
- **When it's built.** `tax_engine.worksheet(slot, profile)` builds the graph only when a trace asks. It works the return
  out again, which is a hit in the engine's answer cache: tables only feed the state return and the marginal rate, which
  have no nodes. It keeps the last 8 graphs, keyed by slot, the engine's pin and the profile. A Taxes page load costs
  nothing new.

**Engine 1.** The proof records each rule's value and the values it read (`inputs`), but not its arithmetic. A memoized
rule appears once in full and elsewhere as a stub without children. So the adapter re-runs each applied rule from its
formula and parameters in the pinned corpus.
- **The corpus.** `main.js corpus export` (24 MB of JSON) is read once per run of the app under the same sandbox, and
  only the federal rules are kept.
- **Labels.** Rule titles and fact descriptions without their asides.
- **Facts.** `facts_for` records each fact's fields as it builds the fact, so the mapping and its sources can't drift.
- **Overriders.** A rule that overrode another (the Tax Table over the general tax rule) is reached through the
  general rule's id, with `when` naming the override.
- **Opaque.** A rule that can't be re-run, or comes out at another value, is `opaque` with the reason. On the synthetic
  returns none is.

**Engine 2.** Tax-Calculator reports named outputs with no graph. Its functions also overwrite their own intermediate
values: a credit is limited to the tax in place, and the standard deduction becomes 0 once it itemizes (and the itemized
parts 0 when it doesn't).
- **The map.** `finance/engines/taxcalc_map.json` writes a formula for every output, from other final values, record
  inputs and the law:
  - income: AGI and the income before it, the Social Security worksheet, capital gains, self-employment tax and its
    deductible half, adjustments, earned income;
  - deductions: the standard deduction, each itemized part (the SALT cap and its phase-down, the charity floor and
    ceilings) and the 2026 2/37 reduction, the Schedule 1-A deductions (tips, overtime, car-loan interest, seniors),
    personal exemptions and the QBI deduction (Form 8995 and 8995-A's phase-in and income cap);
  - tax: the rate schedule, the Schedule D / qualified dividends worksheet (`dwks*`), and the AMT (Form 6251 Parts I–III);
  - credits: each nonrefundable credit in Schedule 3's order, each up to the tax still left (the outputs Tax-Calculator
    limits in place are written as the amount before the limit, then the smaller of it and what's left); the care
    credit's stepped rate; the AOTC and lifetime learning credit with their phase-out shares; the child and
    other-dependent credits; the EITC (parameters read by the number of children); the ACTC (Part II-A and II-B); the
    refundable AOTC; and the reform-only refundable credits as zero.
- **Formulas.** They're written as readable text (`max(0 - Capital_loss_limitation, p22250 + p23250)`) and compiled to
  the shared expression language. A name is an output, a record input, a part, or a law parameter.
  - `param_types` calls a parameter a rate (`x * SeniorDed_prt` is a rate step, the rate kept in the step's detail), a
    count, or a rate in basis points (for the care credit's rate arithmetic). Other parameters are dollars.
  - `param_index` reads a parameter by a record field instead of filing status (the EITC's by children).
  - `muldiv(a, b, c)` is a × b ÷ c rounded half-even (money × count ÷ money is a count: a share in thousandths);
    `steps_floor` and `steps_ceil` count whole steps of a parameter's size; `schedule(x)` is the year's rate schedule,
    rounded once as Tax-Calculator works it in floats; `usd(n)` is dollars inside a product.
  - Formulas cover current law. Terms inert under it (a haircut of 0, a cap of 9e99, a reform-only switch) are left out:
    if a law change activates one, the run check below turns the output opaque and the conformance test fails.
- **Extra values.** `taxcalc_run.py` reads back the extra outputs and parameters the map names. They're part of the
  answer cache's key.
- **Checked every run.** Each formula is re-run over the engine's own values and must give its value within 2 cents
  (float dollars rounded to cents). One that doesn't is `opaque` with the reason.
- **Pinned.** The map is pinned to the release and the SHA-256 of its law file. A different one isn't used: every
  output is then `opaque`.
- **Credits are claimed.** Tax-Calculator models how many people across a population claim the EITC and the additional
  child tax credit (`eitc_claim_prob_scale`, `actc_claim_prob_scale`). A one-household run always gets the same random
  draw (0.76), so it dropped any EITC below about 74% of its maximum and any ACTC below about 69%. The runner sets both
  scales so a return claims what it qualifies for (fixed 2026-10-05). Engine 2 estimates saved in the tax history
  before then may be missing one of these credits.
- **What stays opaque** (`TaxCalculatorEngine.opaque_lines`): nothing, under current law (since 2026-10-05).
  - The Tax Table's tax, which the adapter works out itself, is shown as nodes: the row's middle, the year's rate
    schedule on it, rounded to the dollar.
  - So are the HSA limit and the non-itemizer's charitable limit.
  - The choice to itemize is the engine's (it works the tax both ways and keeps the lower); it's said in the itemized
    deductions' note, not a node.
  - No profile reaches the AMT, so it's checked on a record with AMT preferences added (`tests/test_engine_worksheets.py`).
- **Upkeep.** When the pinned release or its law file changes:
  1. Run `python scripts/taxcalc_map_skeleton.py <output>` for each output's inputs and parameters (read from
     `calcfunctions.py`, never run). It doesn't say which parameters are rates or read by children: check
     `param_types` and `param_index` against the code.
  2. Check each formula against the new code, and that the terms left out are still inert.
  3. Update `law_sha256`.

**Conformance** (`tests/test_engine_worksheets.py`) runs every registered engine on the synthetic returns in
`tests/tax_returns.py`. Every non-total line's node must exist and match the line. Every node must reconcile under its op
within the engine's `tolerance_minor`. Every fact must name `ReturnInput` fields or a declared default, and every law
leaf must have a citation. No line may be `opaque` unless the engine declares it in `opaque_lines`. An engine counts as
traced once this passes, so the test is what adding an engine costs.

### Comparing, records and tests

- **The interface** (`finance/tax_engine.py`):
  - `calculate(slot, profile, tables)` checks capabilities (years, filing status, `FEATURES`) before the engine runs.
    Anything not covered gives no estimate, and `unsupported` and the notes name it, with the slot's label ("Engine 1
    doesn't cover …").
  - Every engine returns one shape: lines in Form 1040 order, the result, `missing`, `needs` (facts to enter) and
    `notes`.
  - The result also carries `engine` (`{slot, label, version}`, which the page and the assistant see) and `raw` (never
    sent to the page; the implementation is in `raw["engine"]` for the records).
  - `readiness(slot)` says whether the slot's engine can run here (bundle hash and Node, or the pinned package).
    Settings and the health check (`/api/finance/health`, `home-manager check-ledger`) show it.
- **Settings.** `tax_engine` holds the chosen slot (`engine_1`; there's no choice on the page).
  `tax_engine_compare` is on by default; its checkbox ("Check every return with a second engine") appears once Engine 2
  can run. With it on, the return is worked out with the other slot as well.
  - Every line more than a dollar apart is shown under "The engines disagree".
  - Tax Zen then becomes REVIEW_REQUIRED ("Check the return first").
- **Comparing** (`tax_engine.compare`): only lines both engines work out are compared. An engine's result lists its
  lines in `reports`; none listed means every line. A line an engine works approximately carries its own `within`
  leeway.
- **Records.** `tax_calculations` (migration 058) keeps each distinct return per year, filing unit, engine
  implementation, version and profile.
  - It keeps the profile, the result, the facts, the assumptions, the corpus Merkle root and the artifact hash. The
    proof tree and the lines' own worksheet nodes are left out, since re-running rebuilds them.
  - Rows are never rewritten. A new engine version adds a row beside the old one.
  - `TaxCalculations.prior(year)` is the newest row for a year, for next year's safe harbor.
- **Licenses.** `vendor/NOTICES.md` lists what ships, and Settings points to it.
- **Tests.** `tests/test_tax_engines.py` covers the slots and legacy settings, the capability check and the mapping. It
  also covers missing facts (the mortgage balance, the tipped occupation), a tampered bundle, and no Node. The synthetic
  returns live in `tests/tax_returns.py`, shared with the worksheet conformance test.
  - **Hand-worked 2026 returns:** W-2 only; joint with children, gains and contract work; high wages with Additional
    Medicare and NIIT; and the OBBBA charity, tips and overtime deductions. They run against both engines and match
    line by line within a dollar (`test_the_second_engine_checks_the_first_line_by_line`).
  - **Skips.** Tests that need Node skip without it. Engine 2's tests skip when it isn't installed.
  - `tests/test_tax_year.py` covers the record fills.

## Tax Zen

Code: `finance/tax_zen.py`, `finance/safe_harbor.py`, `finance/withholding.py`. Tax Zen is the top of the return panel
on the Taxes page. It means the return comes out within a dollar of $0 (or of the aim you chose), since withholding is
in cents and the W-4 is in whole dollars.

**Aim and status**
- **The aim** ("Aim for", saved with the year as `zen_policy`):
  - $0 (the default);
  - a small refund (default $200);
  - keep cash: owe at most a limit (default $999) less a $400 buffer, so the aim is owing $599;
  - owe what the safe harbor allows, less the buffer.
- **The status** is a badge:
  - **Tax Zen** (ZEN): at the aim (within a dollar for $0, otherwise within $100) with the safe harbor met.
  - **Close · watch it** (WATCH): within $500 and safe, so no change is asked for.
  - **On track · could turn** (AT_RISK): at the aim or close to it, but the low end of the likely range owes $1,000 or
    more. The page gives a cushion: the extra 4(c) withholding a paycheck that keeps even the low end under $1,000.
  - **Change recommended** (ACTION_RECOMMENDED).
  - **Check the return first** (REVIEW_REQUIRED): the two engines disagree.
  - **Not enough to go on** (INSUFFICIENT_DATA).
  - **Not covered** (ENGINE_UNSUPPORTED).
- **The safe harbor** (`finance/safe_harbor.py`) is worked out apart from the return.
  - Rules: under $1,000 owed, or payments reaching the smaller of 90% of this year's tax and 100% (110% above $150,000
    of AGI) of last year's.
  - Timing: withholding counts evenly through the year, estimated payments by their dates, and short quarters are
    named. Annualized income isn't worked out.
- **Why.** The page says where the year ends, the aim and the paychecks left.
  - When short of the aim, the first answer is one box, Step 4(c) extra a paycheck, with 4(a) as the alternative.
  - Each answer is **checked**: the engine works the return out again with that withholding.
- **The assistant** has `get_tax_zen_status`, which returns the status, aim, year end, likely range, what changed, safe
  harbor and W-4 answer as worked out here. It explains them and never recomputes.

**The likely range.** The return is worked out twice more with only the projected parts moved, then shown as "Likely
between X and Y" with a confidence.
- **What moves:** pay still to come moves by how much this year's paychecks varied (at least 5%), along with its
  withholding. Interest and dividends still to come move by 25%. Recorded and typed values don't move.
- **Confidence:** high when under 10% of income is projected, medium under 30%, otherwise low.

**Each value says what kind it is**, beside its field on the page:
- "From records";
- "Worked out from records" (the mortgage's average balance, HSA coverage, early distributions);
- "Projected to Dec 31";
- "Enter it" (the qualified part of dividends before the 1099-DIV);
- "You typed".

Each job says whether it is projected. `gather` returns these labels as `kinds`.

**Steady advice** (migration 060, `tax_zen_evaluations`)
- **History.** Each evaluation is kept: status, range, W-4 answer, aim, the figures it rested on, and what changed. A
  row is added only when the status, the answer or the inputs changed.
- **Staying Tax Zen.** Once Tax Zen, it takes 1.5 times the band to leave it.
- **Keeping the W-4 answer.** A new answer replaces the last one only when:
  - it moves withholding by $25 or more a paycheck;
  - the status got worse; or
  - something material changed: a new or dropped job, pay per paycheck moving by more than 10%, or a tax form arriving.

  Otherwise the page says the advice from that date still stands, worked out again for today.
- **What changed** since Tax Zen last looked is listed in words: new stubs, withholding per paycheck, new forms, and
  amounts that moved $100 or more.
- **On Home.** When the status gets worse than when the Taxes page last showed it (to On track · could turn, Change
  recommended, or Check the return first), Home's "Needs attention" lists it with what changed, until Taxes is opened.
  Home works this year's return out again in the background whenever a confirmed pay stub, tax form, tag or typed value
  is newer than the last evaluation.

**Paychecks ahead**
- **Paydays.** Jobs come from pay stubs. Every payday after the latest stub counts in the year's totals, paid like that
  stub, whether or not its stub is here yet. Only paydays after today can change with a new W-4.
- **Withholding.** Each paycheck's federal withholding is worked out as payroll does it, by the withholding engine:
  IRS Publication 15-T's annual percentage method for a 2020+ W-4. That covers Step 2's half-size schedule, Step 3
  credits a year, 4(a) other income, 4(b) deductions and 4(c) extra per paycheck.
- **When a new W-4 counts.** Payroll puts it in by the first payroll period ending 30 days after it's handed in (Pub 15,
  section 9). So by default the next paycheck passes first, and the answer is spread over the paychecks after it
  (`w4_delay_checks` in the aim).
  - The page names the next payday. When no payday is left after that, it says so.
- **Matching payroll.** The result is matched to what the latest stub actually withholds. The difference is kept, so a
  W-4 you haven't entered, or a payroll quirk, carries into the answer.
- **Your current W-4.** Enter the W-4 on file ("Your W-4 there now"), and the answer is the new total for the box.

**The answer, for one job.** By default this is the job with the most paychecks left, then the larger paycheck; you can
choose another.
- **Which box.** When owing, raise Step 4(a) other income. When getting a refund, raise Step 4(b) deductions, or Step 3
  credits when the W-4 already claims dependents.
- **Every answer is listed** (`recommendations`), simplest first: fewest boxes changed, then the smallest change in
  withholding.
- **Checked against the return.** When the engine's year-end with an answer differs by more than a cent a paycheck, the
  answer is aimed at the gap it reports and checked again, up to three times.
- **The search** is over whole dollars and keeps the entry that lands nearest the aim. It is exact because withholding
  only rises as 4(a) rises and only falls as 4(b) rises. The page shows the new withholding per paycheck and where the
  year ends.
- **When owing,** the same catch-up is also shown as a 4(c) extra amount per paycheck.
- **When no entry can close a refund** with the paychecks left (withholding can't go below zero), the page says so.
- **Two answers:**
  - **For the rest of this year:** larger, since only the paychecks left catch up.
  - **From January:** a full year at the same pay, using this year's tables. Check again once next year's tables are
    confirmed.

**Advance tax (1040-ES)**
- **Due dates:** Apr 15, Jun 15, Sep 15 and Jan 15, moved to the next day that isn't a weekend or a legal holiday in
  the District of Columbia (IRC §7503; `safe_harbor.legal_holidays`): DC Emancipation Day can move April's (Apr 18 in
  2023 and 2028) and Martin Luther King Jr. Day January's (Jan 16, 2024 and 2029).
- **What's needed:** the total tax less withholding and refundable credits.
- **Paid so far:** tagged federal estimated payments dated Feb 1 to Jan 31. Each counts for the first quarter due on or
  after its date.
- **What to pay:** what's left is split over the quarters still ahead.
- **Safe harbor** (§6654(d)): 90% of this year's tax, or 100% of last year's (110% above $150,000 of AGI), whichever is
  less. The floor by each date is the estimated-tax safe harbor's own (`safe_harbor.evaluate`): that date's share of
  it less withholding's share, since withholding counts evenly through the year. The underpaid quarters come from it
  too, so Tax Zen and the safe harbor never disagree. A missed quarter below it with $1,000 or more owed is noted
  (Form 2210).
- **When it shows:** it is the answer when there's no paycheck to change (1099 work). Otherwise it is the folded-away
  alternative.

**State.** Tax Zen shows the extra state withholding per paycheck that closes the simplified state return. When the
state return is on track to refund, it shows a reduction instead. When there's no job, it shows state estimated tax.

**The family** (`finance/tax_family.py`, migration 047)
- The family decides who files together (Taxes → Add a return). A married couple filing jointly is one return; everyone
  else files their own.
- A return's records come from its members' shared copies and are added together, with each job and business listed as
  whose it is. Its typed values are saved in the family's library. Self-employment tax and earned income stay per
  person.
- Each return has its own estimate and Tax Zen. The family is Tax Zen when every return is.
- Write-offs and tax rules stay in each person's own profile.

**What If**
- Each compared plan gets "Tax Zen in <year>": a full year at the pay the plan ends with (its paychecks with no last
  month), in place of your jobs when one replaces pay, plus this year's other income and deductions. It shows the
  year-end result with the W-4 in the plan, and the entry that brings it to $0.
- "Now" is this year's return.
- The paycheck planner shows "At tax time" for its paycheck alone.

**API**
- `GET /api/tax/year/{year}` returns:
  - the gathered, typed and merged values, the tables, and the estimate (`engine` is the slot: `{slot, label,
    version}`);
  - `prior_year` (typed, or last year's return as worked out here) and `tipped_occupations`;
  - Tax Zen. `w4`, `prior_year_tax`, `zen_job` and `zen_policy` are saved with the typed values.
- `PUT /api/tax/year/{year}` saves your typed values.
- `GET /api/tax/family/{year}`, `PUT /api/tax/family/{year}/{unit}`, `POST /api/tax/units`, `DELETE /api/tax/units/{id}`.
- Getting or saving the year marks the year's Tax Zen as seen. Tax Zen in the response carries `range`, `changed`,
  `cushion` (AT_RISK) and, per job, `payroll`, `recommendations` and `steady`.
- `GET /api/dashboard`: `attention.tax` is this year's Tax Zen when it got worse since last seen, otherwise null.
- `GET /api/finance/health`: `tax_engines` says whether each engine can run here.

## CPA pack

Code: `finance/cpa_pack.py`; tests: `tests/test_cpa_pack.py`. Taxes → **For your accountant** → **Build the YYYY CPA
pack** makes one Excel workbook for the year to hand to an accountant. Only your button makes one; the assistant has
no tool that writes files.

**Sheets**
- **Summary:** the estimate, income, gains, write-offs, and household spending in USD (complete or partial).
- **Return:** each line of the estimate.
- **Income:** jobs and every gathered field, with its source.
- Wages, income and the job rows are the values the return used (`tax_year.merge`: typed values over the gathered ones,
  and jobs typed in), never the records alone, so the pack and the return agree. A typed value says so as its source.
- **Write-offs:** counted totals by line. **Write-off items:** every tag, its USD value, and whether the estimate counts
  it.
- **Investments:** the year's confirmed activity and realized gains per taxable account.
- **Tax forms:** confirmed and proposed 1099 and 5498 boxes.
- **Transactions:** every counted line and stand-alone receipt, with its USD amount, the basis and the rate id.
- **Exchange rates:** each rate used, with its download's SHA-256.
- **Needs review** and **Manifest.**

**Rules**
- **No tax math of its own.** It shows what the Taxes page and the finance tools compute, read from one database
  snapshot. Before saving, the Transactions sheet's Spent (USD) column must add up to household spending, and the
  reopened workbook must match what was written.
- **Needs review** lists what's unfinished:
  - receipts and statement lines not yet counted, and open matching questions;
  - unconfirmed tags, tax forms and tax tables;
  - shares sold with no purchase lot;
  - amounts with no exchange rate, and write-offs in another currency (the estimate counts USD tags only).
- **Values only.** Python computes every number. Document text is always written as text, never as a formula: a
  description starting with `=` stays text, with a quote prefix.
- **Where it goes.** Packs are kept under `<library root>/Reports/<year>/`, outside `Library/`, so a pack is never read
  back in as evidence.
- **Never overwritten.** Building again from unchanged data returns the same file; changed data makes a new file beside
  the old one. Downloads check the file against the SHA-256 recorded when it was made.
- **Failures.** A full disk or a locked file (open in Excel) fails with a clear message and leaves nothing behind.

## Jobs and pay stubs

Code: `library/managed_library.py`, `documents/extraction.py`, `finance/paystub.py`, `household/tax_tables.py`,
`finance/charts.py`; pages `receipt.js`, `library.js`, `review.js`. Tests: `tests/test_employers.py`,
`tests/test_withholding.py`.

### Folders

Everything about work lives in **Jobs**, with one folder per employer, on disk too:

```
Library/Jobs/Google/Paystubs/2026/09/2026-09-15__Paystub__Google__<hash>__d<id>.pdf
Library/Jobs/Google/Documents/2026/08/2026-08-01__Offer_Letter__Google__<hash>__d<id>.pdf
```

- **Which employer.** The local model reads the employer from the document, never the payroll provider (such as ADP,
  Paychex or Gusto) or a bank.
  - It is given the employers that already have folders. If the document's employer is one of them, even printed
    differently, it answers with that name.
  - The app then drops a trailing legal form (LLC, Inc, Corp …) and keeps letters only, so "Google LLC" files under
    `Google`.
  - A new employer gets its folder, with `Paystubs` and `Documents`, at once (`employers` table;
    `ManagedLibrary.employer`).
- **Which section.** A pay stub (type `paystub`) goes to Paystubs. Employment documents go to Documents (type
  `employment_document`: offer letters, employment agreements, benefits enrollment, separation letters and employer
  W-2s). They are read only to be filed, and never reach the ledger. Tax returns and other tax forms stay in Taxes.
- **Titles.** A pay stub is titled "Paystub MM/DD/YYYY" from its pay date. An employment document is titled by its
  printed name ("Offer Letter", "W-2"). Your own description, if you add one, follows the title.
- **File names never contain digits,** so no account number can reach one. A one- or two-digit number in a document's
  name is spelled out instead (`2027-01-31__W-Two__Google__…`), and longer numbers are left out.
- **Sidebar.** Documents › Jobs › employer › All / Paystubs / Documents (`/api/documents?employer=&section=`).
- **Older libraries.** Files in the retired `Library/Income` folder move into Jobs on startup. A pay stub goes into its
  payer's Paystubs folder with the new name; anything else goes into `Jobs/YYYY/MM`. A document moved into Jobs by hand
  has no employer, and stays in `Jobs/YYYY/MM`.

### Gross to net

A pay stub's printed lines are recorded in `income_lines` (migration 031). Each line has this period's and the
year-to-date amount and a group:
- earnings;
- pre-tax deductions (401(k), health, dental, vision, HSA, FSA);
- taxes (federal, state and local income tax, Social Security, Medicare, state disability);
- post-tax deductions (Roth 401(k) …);
- amounts paid by the employer (a 401(k) match), which are shown but never taken from pay.

The page shows the lines grouped from gross pay down to net pay, with subtotals, and FICA as Social Security plus
Medicare.

Two checks run on each column: earnings add up to gross pay, and gross pay less pre-tax deductions, taxes and post-tax
deductions equals net pay. A stub that fails either check waits in Review with the difference named. One that passes
counts on its own (exception-based review, as for receipts).

### How the taxes were figured

The page explains the stub's withholding (`finance/paystub.py`) as an estimate beside what was actually withheld:
- **Wages.** Income-tax wages are gross pay less the pre-tax deductions. FICA wages are gross pay less the cafeteria-plan
  deductions (health, dental, vision, HSA, FSA). So a 401(k) lowers income tax, not FICA.
- **Buckets.** For federal and state income tax:
  - a paycheck's wages are multiplied by the paychecks in a year (from the printed pay frequency, otherwise the pay
    period's length);
  - the standard deduction is the 0% bucket, with its share of each paycheck;
  - each bracket taxes only its own slice (`tax_return.bracket_slices`, the one bracket function: the paycheck
    planner, the simplified state return and Engine 2's rate schedule use it too);
  - the year's tax, spread over the paychecks, is the estimate;
  - the top bucket is the rate on the next dollar of wages: 0% while still inside the deductions, else
    `tax_return.marginal`, the same rate the return shows as its top bracket.

  A bar chart splits the year's wages into the buckets, with a table of each bucket's wages and tax per year and per
  paycheck.
- **FICA.** Social Security is charged at its rate up to the year's wage base; year-to-date wages decide how much of
  this paycheck is still under it. Medicare is charged at its rate, plus the additional rate on wages above $200,000
  for the year: payroll withholds it there whatever the filing status (IRC §3102(f)(1); rule
  `additional_medicare_withholding`). The table's filing-status threshold ($250,000 joint) is the return's.
- **Why they differ.** Payroll uses IRS Publication 15-T and your W-4 (extra withholding, credits, other income). Tax
  Zen's withholding engine works the same paychecks the way payroll does.
- **Filing status** is a household setting (Settings › Financial preferences), Single by default.
- **The state** is the one whose income tax line is on the stub (`work_state`). States without a wage income tax need no
  table.
- **Plan a paycheck from this stub** opens the What If paycheck planner with the stub's lines filled in
  ([planning](planning.md#paycheck-planner)). For example, you can drop a new job's one-time onboarding lines to see the
  steady paycheck.

### Tax tables

A table is one jurisdiction's (federal or a state's) standard deduction and brackets for a tax year and filing status.
For federal, it also holds the Social Security and Medicare rates, the wage base and the threshold (`tax_tables`).
- **Lookup.** When a pay stub from a year without tables is recorded, the local model looks them up on the web (Brave
  Search key needed), in the same model job. The pay stub page and the paycheck planner also have a "Look up" button.
  The planner looks up the table for the filing status being planned, which can differ from the household's.
- **Checks.** Every number must be printed in a passage the model quotes from a page it opened, and the brackets must
  start at 0 and rise. Anything else is refused and sent back to the model.
- **Review.** A table is a proposal until you confirm it in Review (**Tax tables to confirm**, with its quoted
  sources). Until then, the page says it is waiting. A rejected table can be looked up again.

## For CPA review

The federal return comes from the engines (above), each line citing its rule. The items below are what the app computes
itself, where it may differ from the law. They are worth an accountant's look.

**Withholding and payroll** (`paystub.py`, `paycheck.py`, `withholding.py`)
- **The method.** Income tax per paycheck mirrors Pub 15-T's annual percentage method for 2020+ W-4s: annualize (wages ×
  pay periods + 4(a)); subtract the standard deduction and 4(b); apply the brackets; subtract Step 3; divide by
  periods; add 4(c). Step 2 halves the standard deduction and every bracket start.
- **Not done:** whole-dollar rounding between steps, and the pre-2020 W-4 (allowances).
- **Additional Medicare.** The pay stub and the planner withhold it on wages above **$200,000 regardless of filing
  status**, as payroll must. The return then reconciles it against the filing-status threshold (Form 8959).
- **Supplemental wages:** 22% flat, and 37% above $1M of the year's supplemental wages. The state supplemental rate is
  typed.
- **Pre-tax treatment.** A 401(k) lowers income-tax wages only. Health, dental, vision, HSA and FSA also lower FICA
  wages. An unnamed "other" pre-tax line lowers income-tax wages only. Roth 401(k) is post-tax.

**Estimated tax and the safe harbor** (`tax_zen.py`, `safe_harbor.py`)
- Due dates move past weekends and DC legal holidays (federal holidays and Emancipation Day), each with its observed day.
- No annualized-income installment method (Form 2210 Schedule AI).
- Withholding is treated as paid evenly through the year.

**The simplified state return.** No state additions or subtractions beyond US-obligation interest, no personal
exemptions unless typed as credits, no multi-state or part-year returns, no reciprocity, and no local income tax.

**Gathering**
- Federal tax withheld (box 4) is gathered from each confirmed 1099-INT, 1099-DIV and 1099-R.
- Retirement distributions aren't split into IRA and pension.
- The capital loss carryover isn't split short/long-term, and the excess isn't carried to next year automatically.

**Tax lots and investments** (`tax_lots.py`)
- FIFO only: no specific identification, and no average cost for mutual funds.
- No wash-sale disallowance, no 1099-B adjustments (box 1g), no inherited or gifted basis rules.
- Return-of-capital distributions don't reduce basis.
- No Education Savings Bond exclusion. The 10% additional tax on non-qualified 529 earnings isn't computed.

**RMDs** (`retirement.py`): no April 1 first-year deferral in the forecast, no still-working exception, no inherited
IRAs (10-year rule), no joint-life table for a spouse more than 10 years younger, and no QCDs.

**The forecast** (`forecast.py`): a single flat percentage you enter applies to tax-deferred withdrawals and pensions.
There is no tax on taxable-account gains or dividends, no Social Security taxation, no brackets, no IRMAA, no Roth
conversions and no state tax.

**Filing status:** the app supports single, married filing jointly and head of household. MFS and QSS aren't offered
(the engine supports them).

**Questions for the CPA** (highest impact first)
1. MFS/QSS: a gap that affects common returns.
2. Tax lots: wash-sale and specific-identification needs for the taxpayer's situation.
3. The simplified state return against the state's real rules for the taxpayer.
4. A check of the confirmed yearly withholding tables against the Revenue Procedure.
