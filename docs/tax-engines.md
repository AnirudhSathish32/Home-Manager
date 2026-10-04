# Tax engines

The year's return (docs/taxes.md) is worked out by a **tax engine** behind one interface, so an engine can be added or
replaced without changing the Taxes page, Tax Zen, What If or the CPA pack. The design follows
docs/tax_intelligence_architecture.md §6–10; the plan was phased (0 spike → 1 seam → 2 adapter → 3 shadow comparison
and calculation records → 4 Tax Zen core).

**Numbered slots (2026-10-04).** The app shows engines as numbered slots, never by name: **Engine 1** and **Engine 2**
(`tax_engine.ENGINES`, in order); a new engine becomes Engine 3. The implementation behind a slot (its name, version
and pinned SHA-256) is kept only in `tax_calculations`, this document, `vendor/NOTICES.md` and the adapter.
- **Engine 1 = Invaro OpenTax**, run as a separate, sandboxed Node process. It carries its own yearly law (2025 and
  2026). Pay stub withholding (Pub 15-T) is not an engine's job and stays in the app (`finance/withholding.py`).
- **Engine 2 = PSLmodels Tax-Calculator** (added 2026-10-04; see "Engine 2" below), public domain (CC0), a Python
  model of federal income and payroll tax that tax economists maintain. It checks every return Engine 1 works out, and
  works out the returns Engine 1 doesn't cover. Optional: `pip install "home-manager[engine2]"`.
- **Retired 2026-10-04:** the hand-written federal return (`builtin`) and its LLM yearly-figures lookup
  (`household/tax_figures.py`).
  - The user chose to rely on maintained open-source engines alone.
  - Saved settings naming `builtin` or `opentax` load as `engine_1`.
  - Old `tax_calculations` rows keep their engine name.
- **Adding to it later:** code may be copied in from MIT, Apache or CC0 engines (TelosTax, the IRS Withholding
  Estimator), with their notices. Code copied from an AGPL engine (OpenTax, PolicyEngine) would make Home Manager AGPL
  once distributed. Re-implementing the law from the statute is always fine.

## Phase 0 findings (2026-10-03)

**Pinned:** `@invaro/opentax` 0.4.0, unmodified from npm, in `src/home_manager/vendor/opentax/` (`main.js`, licenses,
`PIN.json` with SHA-256 of every file and the npm integrity). Engine `@invaro/opentax-core` 0.1.0, corpus
`@invaro/opentax-corpus-us-federal` 0.37.0.

**License:** AGPL-3.0-only (versions ≤ 0.2.1 were Apache-2.0); a commercial license is sold by Invaro Inc.
- Fine for personal and family use as an unmodified separate process.
- **Before distributing Home Manager:** offer the engine's source with it (AGPL §6), or buy the commercial license, or
  switch the `opentax` adapter for an MIT/CC0 engine. Nothing outside the adapter depends on OpenTax.

**Audit of `main.js`:**
- One outbound call: an anonymous usage ping (event name, version, platform) to `opentax.invaro.ai/api/t`. It is off
  when `OPENTAX_TELEMETRY=0` or `DO_NOT_TRACK=1`, and the adapter always sets both.
- A `signup` command posts an email address; the adapter never runs it.
- `child_process` appears only inside the bundled `commander` library.
- **How it runs:** `node --permission --allow-fs-read=<vendor dir> --allow-fs-read=<facts dir>`, with no write
  permission. Node 24's permission model doesn't block the network, so the opt-out variables are what stop the ping.

**Runs:**
- **Command:** `eval --facts <file> --as-of <year>-12-31 --json`. The tax year comes from `--as-of`. Money goes in as
  dollar strings and comes out in cents.
- **Exit codes:**
  - 0: answer;
  - 2: needs more facts (named);
  - 3: not covered by the corpus;
  - 1: other error.
- **Output:** a proof tree. Each node is a rule (`ruleId`, title, citation with statute and URL, value) or a fact or
  assumption. Every Form 1040 line is a rule: `us.federal.agi`, `.taxable_income`, `.deduction_election`,
  `.qbi_deduction`, `.income_tax_before_credits`, `.ctc`, `.other_taxes`, `.se_tax`, `.niit`,
  `.additional_medicare_tax`, `.refundable_credits`, `.net_tax`, `.amt`, `.eitc`, … The output also lists the
  `assumptions` (defaults it relied on), the `corpusMerkleRoot` and an `artifactHash`.
- **Checked by hand:**
  - 2026 single: $16,100 standard deduction and Tax Table method.
  - 2026 MFJ: $32,200 standard deduction, SE tax with half deducted, QBI, CTC $2,200 per child, and the OBBBA $2,000
    charitable deduction for non-itemizers (the builtin engine doesn't have it).
- **Payments:** `balance_due` subtracts `federalTaxWithheld` only, not `federalEstimatedPayments`. The adapter takes tax
  and credits from the engine and adds up payments itself, as the builtin engine does.

**States:** only IL, VA, CA, NY and PA have state composers (`state` command, a separate facts shape). The website's
"29 states" isn't in this package. Other states keep the simplified state return (`tax_return.state_return`), labeled as such.

**Gate:** passed for federal. Every core `ReturnInput` field maps (below). The gaps are named, and the engine refuses
rather than guesses.

## `ReturnInput` → OpenTax facts

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
| businesses[] (one self-employed person) | selfEmploymentNetProfit or scheduleCNetLoss | **Gap:** two self-employed spouses (Schedule SE is per person; the engine takes one) → not supported |
| educator_expenses | educatorExpenses | **Gap:** on a joint return the app doesn't split the two spouses' expenses |
| hsa_contributions, hsa_coverage | hsaContribution, hsaCoverage (self or family, required) | Filled from records (the year's HSA contributions against the self-only limit), or typed: Adjustments → HSA coverage |
| se_health_insurance | selfEmployedHealthPremiums | The engine applies the earned-income limit the builtin doesn't |
| ira_deduction | iraContribution, isActivePlanParticipant = false | The field is the deductible part as entered, so the §219(g) phase-out isn't applied again (noted on the page) |
| student_loan_interest | studentLoanInterest | |
| other_adjustments | otherAdjustments | |
| medical | medicalExpenses | |
| state_local_tax + property_tax | stateAndLocalTaxesPaid | |
| mortgage_interest, mortgage_average_balance | mortgageInterestPaid, mortgageAverageBalance (required) | Filled from Form 1098 and the recorded mortgage (Pub 936 methods), or typed: Deductions → Mortgage's average balance |
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

A **gap** makes the result incomplete with the gap named (`unsupported`). It is never dropped silently.

## How it runs in the app (built 2026-10-03; Engine 2 added 2026-10-04)

- **Interface:** `finance/tax_engine.py`.
  - `calculate(slot, profile, tables)` checks capabilities (years, filing status, FEATURES) before the engine runs.
    Anything not covered gives no estimate; `unsupported` and the notes name it, with the slot's label ("Engine 1
    doesn't cover …").
  - Every engine returns one shape:
    - lines in Form 1040 order, the result, `missing`, `needs` (facts to enter) and `notes`;
    - `engine`, `{slot, label, version}`, which is what the page and the assistant see;
    - `raw`, never sent to the page, with the implementation as `raw["engine"]` (name, version, pin) for the records.
  - `readiness(slot)` says whether the slot's engine can run here (bundle hash and Node). Settings shows it.
- **Adapter:** `finance/engines/opentax.py`.
  - Maps the facts as in the table above, then runs the pinned bundle as described.
  - Reads the proof tree into the app's line keys. Lines it doesn't name separately go to "other" lines, so totals
    always reconcile.
  - Answers are cached in memory by facts (32 of them). One run takes about 0.3 s.
  - The bundle's hash is checked once and again whenever its file time or size changes.
- **User-facing text** names only the slot: "Engine 1 needs Node.js 20 or later", "Worked out by Engine 1: every line
  follows a cited rule".
- **Facts filled from records** (`finance/tax_year.gather`; docs/taxes.md lists them):
  - Form 1098, and the mortgage's average balance from 1098 box 2 and the recorded mortgage, or interest ÷ rate;
  - HSA coverage from the year's HSA contributions;
  - each family member's birth year;
  - last year's tax and AGI from last year's calculation.
- **Payments:** the app adds them up. The Additional Medicare withheld above 1.45% (§3101(b)(1)) counts as paid.
- **Rounding:** Engine 1 works Schedule SE in whole dollars, so a hand-worked line, or a second engine's, agrees
  within a dollar (`AGREE_WITHIN`).
- **Settings:** `tax_engine` holds the chosen slot (`engine_1`; there's no choice on the page).
  - `tax_engine_compare` (on by default; the checkbox shows once Engine 2 can run) works the return out with the other
    slot as well: every line more than a dollar apart shows under "The engines disagree", and Tax Zen becomes
    REVIEW_REQUIRED.
  - Settings and the health check (`/api/finance/health`, `home-manager check-ledger`) say whether each slot can run.
- **Comparing** (`tax_engine.compare`): only lines both engines work out are compared (an engine's result lists its
  lines in `reports`; none means every line). A line an engine works approximately carries its own `within` leeway.
- **When Engine 1 doesn't cover a return** (both spouses self-employed, more than three AOTC students, other credits
  typed in), the Taxes page has Engine 2 work it out instead and says so.
- **Records:** `tax_calculations` (migration 058) keeps each distinct return per year, filing unit, engine
  implementation, version and profile.
  - What's kept: the profile, the result, the facts, assumptions, corpus Merkle root and artifact hash. The proof tree
    is left out, since re-running rebuilds it.
  - Rows are never rewritten. A new engine version adds a row beside the old one.
  - `TaxCalculations.prior(year)` is the newest row for a year, for next year's safe harbor.
- **Licenses:** `vendor/NOTICES.md` lists what ships, and Settings points to it.
- **Tests:**
  - `tests/test_tax_engines.py`:
    - the slots and legacy settings, the capability check and the mapping;
    - missing facts (the mortgage balance, the tipped occupation), a tampered bundle, and no Node;
    - hand-worked 2026 returns: W-2 only; joint with children, gains and contract work; high wages with Additional
      Medicare and NIIT; and the OBBBA charity, tips and overtime deductions.
  - `tests/test_tax_year.py`: the record fills.
  - Tests that run Node skip without it.
  - The hand-worked returns run against both engines (Engine 2's skip when it isn't installed).

## Engine 2: Tax-Calculator (built 2026-10-04)

**Why this one.** The user asked for a reputable, up-to-date second engine. TelosTax (MIT) covered 2025 only and was a
young one-person project. Tax-Calculator (github.com/PSLmodels/Tax-Calculator) is maintained by tax economists:
- release 6.8.4 came out on 2026-10-01;
- it has treated the OBBBA as current law since 5.2.0, and its law runs to 2026 (`Policy.LAST_KNOWN_YEAR`);
- it is public domain (CC0), so it can be used, or copied from, freely.

PolicyEngine-US was the alternative: also reputable, but AGPL and a heavier install.

**How it runs** (`finance/engines/taxcalc.py`, `finance/engines/taxcalc_run.py`):
- **Pinned** to 6.8.4 as the optional `engine2` extra. Readiness says when it's missing or a different version.
- **One record per return**, run in a child Python process (`python -I taxcalc_run.py`; JSON in and out) with
  `exact_calculations` on, so pandas and numba stay out of the app's process.
  - The first run on a computer compiles the model (about 12 s); after that a run takes about 1.7 s.
  - Answers are cached by record (32 of them).
- **Records:** the calculation records keep the record sent, the model's outputs, the year's law parameters read, and
  the SHA-256 of its `policy_current_law.json`.

**Mapping** (`record_for`):

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

**What it takes as given, worked here from the law:**
- **The Tax Table** below $100,000 of taxable income: the rate schedule on the middle of the income's row, rounded to
  the dollar, from Tax-Calculator's own rate schedule for the year (`table_tax`). With qualified dividends or long-term
  gains the worksheet's Tax Table steps aren't redone, so that tax carries a `within` leeway of 22% of $25 plus a dollar.
- **The mortgage limit** (Pub 936): interest × $750,000 ÷ the average balance.
- **The HSA deduction**: contributions up to the §223(b) limit for the coverage (`tax_year.HSA_LIMITS`), $1,000 more
  from 55.
- **The AOTC's tentative amount** per student: 100% of the first $2,000 and 25% of the next.
- **The non-itemizer's charitable deduction** is inside its standard deduction; it's shown on its own line, as Engine 1
  shows it.

**It asks rather than guesses** (`needed`), by the same fact ids as Engine 1: the mortgage's average balance, the HSA
coverage, the tipped occupation. With no birth year it takes Engine 1's documented default (25 to 64, not 65 or older)
and says so, and asks for the birth year when the earned income credit turns on it.

**Not covered:** other itemized deductions typed in; forcing itemizing when the standard deduction is larger.

**Lines it doesn't work out separately** (left out of comparisons): the SEP deduction, the saver's credit and the
premium tax credit.

**Checked:** the hand-worked 2026 returns in `tests/test_tax_engines.py` match it line by line within a dollar:
- W-2 only;
- joint with children, gains and contract work;
- high wages with Additional Medicare and NIIT;
- the charity, tips and overtime deductions.

It agrees with Engine 1 on each (`test_the_second_engine_checks_the_first_line_by_line`).
