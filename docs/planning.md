# Planning: forecast, What If and investments

The long-range forecast, What If plans and paycheck planning, and investment accounts. Taxes, Tax Zen and pay stubs
are in [taxes](taxes.md). How spending and recurring bills are counted is in [money](money.md).

## Forecast

The forecast is a deterministic projection of income, spending, cash, assets, loans and net worth, month by month, for
1 to 100 years. Code: `finance/forecast.py` (calculation), `finance/charts.py` (SVG charts), `static/forecast.js` (page),
migration 022 (`assets`). No model is involved: the same records and assumptions always give the same numbers and
byte-identical charts.

### Starting point
- **Cash** is each account's latest statement balance (credit card balances count as owed).
  - Accounts without a statement balance start at zero and are listed in the notes.
  - A savings account linked to an investment account (a HYSA) is counted there instead, not as cash.
- **Income** is the average monthly counted income (deposits, interest) over the last *N* full months (default 6).
- **Spending** is the average monthly counted spending per category over the same months. Refunds appear as a negative
  line. Transfers and card payments are excluded, as everywhere else.
- **Recurring bills.** Each confirmed recurring bill is projected at its expected amount in the months it falls due,
  counting on from its next due date.
  - Weekly bills are spread evenly (52/12 a month).
  - Bills grow with inflation and follow their category's spending change.
  - Past payments to a bill are taken out of the category averages ([money](money.md#recurring-bills)).
- **Assets and loans** come from the `assets` table (homes, cars, other assets, loans; see
  [Assets and loans](#assets-and-loans)).
- **Investments.** Each investment account starts at its newest confirmed value, growing at the account's yearly rate or
  its kind's default, plus its monthly contributions (see [Investments](#investments)):
  - **From pay:** the linked employer's confirmed pay stub 401(k), HSA and match lines, averaged over the history
    window. Cash is untouched.
  - **From you:** the amount set on the account, otherwise your recent payments in from the ledger. This comes out of
    cash.
  - **CDs and Treasuries** grow at their own terms to their maturity value, and are paid to cash in the maturity month
    unless they renew.
  - Accounts with a statement value waiting for review are named in the notes.
- **One currency per forecast.** Amounts in other currencies are left out and named in the notes.

### Assumptions

| Assumption | Default | Effect |
|---|---|---|
| Inflation | 2% a year | Spending grows with it, compounded monthly; "today's dollars" divide it back out |
| Income growth | 0% | Income stays flat unless changed |
| Asset growth | per asset; car −15%, others 0% until set | Compounded monthly |
| Loans | rate and payment per loan | Monthly interest (rounded to the cent), then the payment, until repaid; a payment below the interest is flagged |
| Spending changes | none | A category's average times (1 + percent) |
| Income changes | none | Added to monthly income from a month on |
| One-off amounts | none | Added to cash in their month (expenses negative) |
| Planned paychecks (`pay_plans`) | none | What If: take-home pay a month from a month on (to a last month, or until retirement). *Replace* takes the place of confirmed pay stubs' take-home pay and payroll contributions; *add* is another earner. Contributions go to a linked investment account or a new planned one. Yearly bonuses are paid (after withholding) in their calendar month |
| Set spending (`category_amounts`) | none | What If: a category's monthly amount from a month on, in today's money (grown with inflation); replaces its average and its recurring bills |
| Cancel subscriptions (`cut_subscriptions_from`) | none | What If: every confirmed subscription stops from a month on; bills stay |
| Pensions, education costs | none | See [Retirement and required distributions](#retirement-and-required-distributions) |

Cash each month = previous cash + income − spending − loan payments − contributions from you + maturities paid out +
withdrawals from investments + pension income + one-offs.

Net worth = cash + investments + assets − loans. All arithmetic is exact decimal, and each monthly amount is rounded
half-even to the cent.

### Retirement and required distributions

`ForecastInput.retirement` (`RetirementPlan`) is one self-contained input. It is never stored, so What If can run
several side by side.

- **From the start month:**
  - Take-home pay stops. This is the average net pay of confirmed pay stubs in the history window, grown with income.
    Income after that never goes below zero.
  - Contributions from pay stop, and so do your own.
- **Withdrawals** come from taxable accounts first, then tax-deferred, then tax-free, then HSAs. Each takes from the
  account's balance before its CDs.
  - **Fixed:** a monthly amount in today's dollars, grown with inflation.
  - **Cover the shortfall:** whatever keeps cash at a floor, also in today's dollars.
  - **Tax:** a withdrawal from a tax-deferred account is grossed up at the flat tax rate you set, so the planned amount
    reaches cash. The tax is shown per year.
  - **Running out:** when the accounts can't meet a withdrawal, a note says when investments run out.
- **RMDs.** With a birth year set in Settings, every December from the start year each tax-deferred account pays out at
  least its end-of-last-year balance divided by the Uniform Lifetime divisor, after tax, into cash (see
  [Required minimum distributions](#required-minimum-distributions)). This happens with or without a retirement plan.
  The year table shows "From investments", "Tax withheld" and "Required (RMD)" (the part taken only because it was
  required).
- **Pensions.** A pension is income, not an asset. It pays its monthly benefit from its start month, raised by its COLA
  each January. A tax-deferred pension is taxed at the retirement plan's flat rate (untaxed when no plan sets one). A
  What If can add pensions (`pensions`), and the family forecast adds every member's. Survivor benefits aren't
  projected.
- **529 plans.** A 529 is never drawn on by retirement withdrawals. Planned education costs (`education_withdrawals`: a
  month, an amount, and optionally a 529's account id) are paid from the 529, and from cash once it runs short.
- The year table adds "Pension", "Pension tax", "Education" and "Paid by the 529" columns when there are any.

### Output

- **`POST /api/forecast`** returns:
  - every month, and a per-year summary with exact display text;
  - the starting point and the notes (missing balances, thin history, other currencies, pending statement values,
    unknown categories);
  - the first month cash falls below zero;
  - three SVG charts: net worth (nominal and in today's dollars), income and spending per year, and
    cash/assets/loans.
- **Tables.** Each chart has a per-year table view.
- **Colors.** Charts use the validated categorical order blue `#2a78d6`, orange `#eb6834`, aqua `#1baf7a` on white
  (chart rules: the `forecast-charts` skill).
- **Family.** The family view's net worth comes from `/api/family/net-worth` ([family](family.md#families)).

### Assets and loans

- **Endpoints.** `GET/POST /api/assets`, `PUT/DELETE /api/assets/{id}` (delete archives the asset).
- **Values you type** count at once.
- **Loan statements** are read as `loan_document`: lender, account reference, statement date, principal balance,
  interest rate, regular monthly payment and currency. The rate must be printed as a percentage in its citation.
- **One asset row per loan account** (institution + last four digits + kind). A newer statement updates the value and
  date and returns the row to *proposed*; an older one is ignored.
- **Review.** Every statement value waits in Review under "Investment and loan documents to confirm", and counts in the
  forecast once confirmed. Until then it is listed in the notes.
- **Investments** used to be `assets` rows too. Since migration 036 they have their own tables (see
  [Investments](#investments)).

### Not modelled

- Taxes other than the flat rate on tax-deferred withdrawals and pensions.
- Investment income modelled separately from growth. This is planned: see
  [Planned: investment income](#planned-investment-income). Until then, set an account's yearly rate to include it.

## What If

What If lets you try money plans before they are real: a new job whose first paychecks aren't representative, a move to
another city or state, or your forecast on someone else's salary. It has three parts:
- the **paycheck planner** works out a paycheck forward from gross pay, showing every line;
- **saved plans** run through the forecast side by side with "Now";
- **following a plan** turns its spending into budgets and compares it with actual pay stubs and spending.

### Paycheck planner

Code: `finance/paycheck.py` (calculation), `POST /api/paycheck`, `GET /api/paycheck/from-stub/{id}`, `static/whatif.js`
(the What If page). Nothing is stored. `paystub.py` explains a real stub backward; the planner uses the same tax math
forward, so a plan built from a stub gives the same estimates as the stub's explanation.

**Inputs**
- **Paycheck:** tax year, filing status, work state, and how often you're paid (12, 24, 26 or 52 times a year).
- **Pay:** a yearly salary (split evenly over the paychecks, each rounded to the cent) or the gross pay per paycheck.
  Other earnings are amounts per paycheck.
- **Deductions:** pre-tax (401(k), HSA, FSA, health, dental, vision, other) and post-tax (Roth 401(k), life insurance,
  other), each an amount per paycheck or a percent of gross pay.
- **Paid by the employer:** a 401(k) match ("X% of what you put in, up to Y% of gross pay", counting pre-tax and Roth
  contributions) and other employer contributions, such as an HSA. These are shown but never taken from pay.
- **Federal:**
  - The standard deduction comes from the year's confirmed federal tax table; a number you type replaces it, and the
    table's figure is shown as the hint.
  - W-4 adjustments: step 3 credits (off the year's tax), step 4(a) other income (added to the year's wages), step 4(b)
    deductions (a second 0% bucket after the standard deduction) and step 4(c) extra withholding per paycheck.
  - **Step 2 checked** (more than one job, or a spouse who works) uses Publication 15-T's checkbox schedule. Every
    threshold is halved and rounded to whole dollars, so half the standard deduction is untaxed and each bracket starts
    at half its usual wage level.
  - Without the box, Pub 15-T's standard schedule (2020+ W-4, annual percentage method) is used. That schedule takes the
    Step 1(g) amount ($8,600, or $12,900 married filing jointly) off wages, then applies the tax brackets shifted by the
    standard deduction less that amount. This works out the same as taxing wages less the standard deduction on the
    brackets, which is what the planner does, so it matches payroll's method.
- **State:**
  - The state's deduction or exemption comes from its confirmed table. Type one to replace it, for example where the
    state gives a personal exemption instead.
  - Instead of the table, a flat rate you type works the tax out now. Use it for a flat-tax state not looked up yet.
  - **State credits** a year come off the state's tax for the year, for states whose withholding uses credits (for
    example an exemption credit).
  - You can also enter extra withholding, and state disability insurance (a percent, optionally up to a yearly wage
    limit).
- **Local tax:** a percent of income-tax wages or of gross pay, or an amount per paycheck.
- **Bonuses** (supplemental wages): each has a name, an amount and the month it is paid, with that month's first
  paycheck.
  - Percent-of-pay deductions and contributions (a 401(k) %, the match) take their share of it.
  - Federal withholding is the flat supplemental rate: 22%, and 37% on the year's supplemental wages above $1 million
    (26 CFR 31.3402(g)-1).
  - The state's withholding is the "state rate on bonuses" you enter. If it is left blank, a note says it is left out.
  - Social Security, Medicare and disability insurance count the bonus in its paycheck, so the wage base can be reached
    there.

**How it is worked out** (per paycheck and per year)
- **Wages:**
  - Income-tax wages are gross pay less every pre-tax deduction.
  - Social Security and Medicare wages are gross pay less the cafeteria-plan deductions (health, dental, vision, HSA and
    FSA). A 401(k) doesn't lower them.
  - State wages are taken to be the federal ones.
- **Income taxes** use the same method as `paystub.income_tax`:
  - a paycheck's wages are multiplied by the paychecks in a year, and the deduction is taken off;
  - each bracket taxes only its own slice;
  - the year's tax is spread over the paychecks.
  Each tax has its bucket chart and table.
- **Social Security, Medicare and state disability** run paycheck by paycheck through the year. **Paychecks through the
  year** shows where Social Security reaches its wage base (or disability insurance its limit), and where additional
  Medicare starts.
- **Net pay** is gross pay less pre-tax deductions, taxes and post-tax deductions. It is shown per paycheck, per year,
  and as a monthly average (the year's net pay over 12). The monthly average is what a plan feeds the forecast.
- **Contributions:** the retirement and HSA amounts per paycheck (yours plus your employer's) are returned for the
  plan's forecast.
- **Missing tables.** A missing or unconfirmed table is named, with a Look up button. Those taxes are left out, and the
  page warns that take-home pay is too high until the table is confirmed. The planner never guesses a rate.
- **At tax time.** The planner shows where this year's return would end at this paycheck, through Tax Zen
  ([taxes](taxes.md#tax-zen)).

**Start from a stub:** "Plan a paycheck from this stub" on a pay stub opens the planner (`#/whatif?stub=<id>`) with that
stub's earnings, pre-tax, post-tax and employer lines as amounts per paycheck.

### Saved plans

Code: `finance/scenarios.py`, migration 043 (`scenarios`: name, basis, `inputs_json`). API: `GET/POST /api/scenarios`,
`PUT/DELETE /api/scenarios/{id}`, `POST /api/scenarios/{id}/duplicate`, `POST /api/scenarios/compare`. The page has Plans
and Compare panels, and the URL keeps the open plan (`#/whatif?plan=<id>`).

- **Stored.** A plan keeps its inputs only. Every comparison works every paycheck out again from today's tax tables and
  runs the forecast from today's records.
  - The inputs are: the plan's name and what it starts from; its paychecks; its set spending, spending changes and
    one-offs; and the forecast's assumptions.
  - Each paycheck is a planner input with a name, a first and optional last month, *replaces pay* or *adds to income*,
    and where its 401(k) and HSA contributions go.
  - Plans live in the open library; in the family view, in the family's own library.
- **Starts from:**
  - **My records:** this profile's forecast baseline.
  - **The family's records** (family view only): every member's baseline added together, exactly. Cash, take-home pay,
    income and each category's spending are summed. Balances, bills and assets are listed with the member's name.
    Contributions can't be linked to one member's account from the family, so they go to new planned accounts.
  - **A blank slate:** only the cash you type (in the home currency, otherwise USD). The plan's paychecks, spending and
    one-offs are everything. Use it for someone else's life or a household that doesn't exist yet.
- **Paycheck to forecast:**
  - Take-home pay a month is the year's regular net pay over 12. Each bonus is paid after its withholding in its
    calendar month, every year the paycheck runs, and its 401(k)/HSA share goes into the account that month.
  - Contributions a month are each paycheck's retirement amount (pre-tax and Roth 401(k), plus the match and employer
    retirement lines) and its HSA amount (yours and the employer's), times the paychecks in a year, over 12.
  - These become the forecast's `pay_plans`. A paycheck that replaces pay takes the place of the confirmed pay stubs'
    take-home pay and payroll contributions while it runs.
  - Without confirmed pay stubs there is nothing to replace, so the recorded income keeps whatever pay it includes, and
    a note says so.
  - Retirement stops planned pay like any pay.
  - A paycheck whose tax tables are missing is still used; the notes say its take-home pay is too high.
- **Compare.** Compares Now (this profile's or the family's forecast with the Forecast page's defaults) with saved
  plans, at most three lines together (the chart's three validated colors), all over the same years.
  - "Compare with now" runs the plan on screen, saved or not.
  - The result is a net-worth line chart with a table view, and a warning for any plan whose cash falls below zero.
  - For each plan it also shows the paychecks as worked out; each year's income, spending, one-offs, contributions,
    cash and net worth; and the plan's notes.
- **Retirement.** A plan can plan withdrawals with the same fields as the Forecast page (retire in, fixed amount or
  cover the shortfall, cash floor, tax on tax-deferred withdrawals). Its paychecks stop at retirement.
- **Cancel subscriptions.** A plan can cancel every confirmed subscription from a month on. The notes say how many were
  cancelled and roughly what that saves a month. Which recurring payments are subscriptions is your choice
  ([money](money.md#recurring-bills)).
- **Moving.** A move is modelled as:
  - a second paycheck from the move month, with the new work state (the first paycheck gets a last month);
  - set spending for rent and the like from that month;
  - one-offs for movers and deposits.
- **Tax Zen.** Each compared plan shows where this year's return would end at the plan's pay for a full year, and the
  W-4 entry that brings it to $0 ([taxes](taxes.md#tax-zen)).

### Following a plan

Code: `finance/plan_tracking.py`, migration 044 (`scenarios.adopted_month`). API:
`GET /api/scenarios/{id}/budgets?month=`, `POST /api/scenarios/{id}/adopt`, `POST /api/scenarios/{id}/stop`,
`GET /api/scenarios/{id}/actual`. The **Follow this plan** panel is shown for a saved plan in a person's profile.
Budgets and pay stubs belong to each person, so the family view doesn't follow plans.

- **Use as budgets.** Choose the month the budgets start. The page lists each category the plan sets for that month:
  - the budget now and the plan's amount;
  - whether it is new, changes or is already set;
  - the budgets the plan doesn't name, which are left alone.

  Nothing changes until you choose **Set N budgets and follow this plan**. That sets the budgets (`ledger.set_budget`)
  and marks the plan as followed from that month.
  - Category names are compared the way budgets compare them: lower case, single spaces.
  - Set spending is in today's dollars, so each budget is the amount as entered.
  - A zero amount can't be a budget, and is named instead.
- **Stop following.** The plan and the budgets it set both stay; only the follow mark is cleared.
- **Plan and actual.** Works for any saved plan. Before a plan is followed, it runs from the plan's first set-spending
  month.
  - **Pay:** each paycheck that replaces pay is compared line by line with this profile's confirmed pay stubs paid in
    its months.
    - The lines are gross pay, each pre-tax deduction, each tax, each post-tax deduction, and net pay.
    - The columns are planned, the latest stub, the average of up to six stubs, and the difference (average less
      planned).
    - A line a stub doesn't print counts as zero on it, so a planned deduction that never started shows up.
    - Paychecks that add another earner aren't compared, since their stubs are in that person's profile.
  - **Spending:** each set-spending amount against the category's counted spending (the budgets' figure). This runs
    month by month, newest first, for up to six months from the month the plan is followed. The current month is "so
    far". Each row is marked Over plan or Within plan.

**Not modelled** (the notes under the breakdown say so where it matters):
- the pre-2020 W-4 (withholding allowances);
- payroll systems that round withholding to whole dollars;
- state withholding formulas beyond the state's brackets, its deduction or exemption, and the credits you enter;
- state rules that treat some pre-tax deductions differently from federal.

## Investments

Investments covers retirement accounts (401(k), 403(b), IRAs), pensions, HSAs, high-yield savings, CDs, Treasuries, I
bonds, brokerage accounts, crypto and 529 plans. They have their own page: Money → Investments. Values come from
documents and what you type. The one exception is crypto market prices, fetched only when you turn them on (see
[Crypto](#crypto)). Investments are not spending.

Code: `finance/investments.py`, `finance/tax_lots.py`, `finance/retirement.py`, `finance/prices.py`; page
`static/investments.js`.

### One model for every kind

Each account is described by four independent things. The page, the forecast and extraction branch on the **section**,
**tax treatment** and **value model**, never on the kind itself. So a new kind is a row in `investment_kinds`, not new
code or a schema change.

| Dimension | Values | Used for |
|---|---|---|
| **Kind** (`investment_kinds` row) | `401k` `403b` `457b` `ira` `roth_ira` `pension` `retirement` `hsa` `hysa` `money_market` `cd` `treasury` `i_bond` `bonds` `brokerage` `crypto` `education_529` `other` | Label, defaults |
| **Section** | Retirement · Health savings · Cash and savings · CDs, bonds and Treasuries · Stocks and funds · Education · Other | Page groups, the share of each |
| **Tax treatment** | taxable · tax-deferred · tax-free · HSA | Share by tax treatment; withdrawal order in the forecast's retirement plan. Each account can override its kind's |
| **Value model** | `market`: the last reported value. `accrual`: principal plus a rate to maturity (CD, Treasury bill or note); I bonds use the published I bond rates. `cash`: a balance earning a yearly rate (HYSA, money market). `income`: a monthly benefit from a start date (pension), never a balance | How the value is estimated and projected |

The kind comes only from printed words in the account name or institution (`printed_kind`). A statement whose kind
isn't recognized becomes `other` (or a brokerage account), and you can rename or reclassify it on the page.

### Tables

- **`investment_kinds`:** key, label, section, tax treatment, value model, has_maturity, default yearly rate.
- **`investment_accounts`:** kind, name, institution, currency, and `account_key` (institution | last four, or name |
  currency, for statements). Optional overrides for tax treatment and yearly rate. `ledger_account_id` links a HYSA to
  its ledger savings account.
- **`holdings`:** positions in an account (fund, stock, CD, Treasury bill), with nullable terms: rate, issue and
  maturity dates, principal. The ticker or CUSIP is in `identifier`.
- **`investment_valuations`:** **append-only values over time**. A row with no holding is the whole account. There is
  one row per account, holding and date. Each row records its source (manual, statement or quote), its document, and
  its review status.
- **`investment_events`:** append-only activity: contributions (employee, employer or personal), withdrawals,
  dividends, interest, fees, buys, sells, maturities and rollovers. Each can link to the bank transaction or pay stub
  line it came from.
- **History.** Migration 036 moved the old `assets` rows of kind investment, retirement and bond into these tables.
  They kept their ids, values, review status and source documents. `legacy_asset_id` lets older extraction results
  still open on the document page.

### Reading statements

An `investment_statement` is read in three questions: its classification, its summary, and then its rows
(`InvestmentLine` in `documents/extraction.py`), chunk by chunk. Each row is either a **holding** or an **activity**
entry:
- **Holding:** printed name, ticker or CUSIP, instrument class (fund, stock, ETF, CD, Treasury, cash sweep, …),
  quantity, price, market value, cost basis, and, for CDs, bonds and Treasuries, the rate and maturity date.
- **Activity:** date, type (contribution, withdrawal, dividend, interest, fee, buy, sell, maturity, rollover,
  transfer), amount, and, for a contribution, whether it came from pay, the employer or you.

What is kept, and how it's checked:
- Money is checked against its citation, like every other amount.
- A quantity, rate or ticker is kept only when it is printed on its cited line. Otherwise it is dropped, with a note
  for quantities.
- An activity row without a clear date and amount is not recorded.
- When every holding has a value, the holdings must add up to the ending value. This is the statement's cross-check,
  and any difference is listed on the value in Review.

On publishing:
- Holdings are matched from one statement to the next by ticker or CUSIP, otherwise by name.
- Each holding gets a value for the statement date.
- Activity entries become events. An entry that another statement already recorded (overlapping periods) is not added
  twice.
- Reading the same statement again replaces what the earlier reading listed, unless you already decided on it.
- Confirming or rejecting the statement's value in Review applies the same decision to its holdings and activity.

The account shows the holdings on its newest statement date, with the gain where a cost basis is printed, and the
activity from newest to oldest.

### Savings accounts kept as investments

A HYSA's statements are bank statements, already read into Accounts. On the Investments page, an investment account can
be linked to one savings, checking or brokerage account in the same currency. Each ledger account can be linked only
once (migration 037). The link then does three things:
- **Values.** The linked account's statement closing balances become the investment account's values.
  - They are read when the page loads, never copied, so they follow the statements exactly.
  - They are reviewed as statements in Review.
  - A value you type for a date still takes precedence over the statement for that date.
- **Interest.** Interest transactions from that account appear as interest activity.
- **Counted once.** The forecast and net worth leave the linked account out of cash and count it once, as an
  investment.

### Purchase confirmations, estimates and maturities

An `investment_confirmation` is its own document type, filed under Investments. It covers a trade, a CD opened, a
Treasury bill, note or bond bought, or an I bond bought. It is read as a summary (institution, account, trade date) and
its trades (`TradeLine`):
- Each trade has an action (buy, sell, reinvest, redeem, deposit), the security, the quantity, the price, the net
  amount, the principal, the face value, fees, rate, issue date and maturity date.
- Money is checked against its citation. A quantity or rate is kept only when it is printed where it is cited.
- For shares, quantity × price plus fees (on a buy) or less fees (on a sale) must give the amount.
- An I bond can first be cashed 12 months after it is issued. That date is computed in code.

Publishing (migration 038):
- The confirmation is recorded in `investment_confirmations` and waits in Review.
- Each trade becomes a buy, sell or contribution event.
- Buying a CD, Treasury or bond sets that holding's terms: principal, rate, face value, issue, maturity and redeemable
  dates, and whether it renews.
- Confirming the confirmation confirms its trades. Re-reading one you've decided on changes nothing.
- You can also add a CD or Treasury with its terms by hand ("Add a CD or Treasury" on an account). It counts at once.

**Estimated values.** An account valued by accrual that has no value newer than today gets an estimate for today. The
estimate is the sum of its open holdings, each carried forward from its terms:
- A holding with a face value rises in a straight line from its price to the face value at maturity.
- An I bond follows its published rates (see [I bonds](#i-bonds)).
- Any other holding compounds at its yearly rate: principal × (1 + rate)^(days/365), exact and rounded half-even.
- A holding on the newest statement starts from its statement value.
- Holdings that matured, that wait for review, or that come from a rejected confirmation are left out. An account whose
  CDs all matured is estimated at zero.
- The estimate is worked out when read, never stored. A statement or a value you type for a date always takes
  precedence. Totals count the estimate, and the page labels it "Estimated".

**Maturities**
- **Coming due.** "Coming due" on the page, and Home's bills panel (three soonest), list:
  - CDs, Treasuries and bonds maturing within 90 days;
  - I bonds whose lock ends;
  - holdings that matured with no answer yet.
- **Answering.** A matured holding is answered with "Paid out" or "Renewed". Either records a maturity event at the
  amount its terms pay, and closes the holding. A renewal is then added as a new holding.
- **Statements.** A statement dated after a holding's maturity already answers it.

### Contributions and payments in

**From pay (migration 039).** Pay stub lines are read into the account at read time, never copied:
- A retirement account takes the employer's `retirement_pretax` and `retirement_roth` lines. An HSA takes its `hsa`
  lines.
- Lines in the `employer_paid` group are the employer's (the match). The rest come from your pay.
- They follow the pay stub's review.
- A statement contribution with the same payer and amount within 7 days is the same money. It is shown once, as the pay
  stub's ("also on a statement").

**Which account an employer's lines go to** is decided from the documents, after each pay stub or statement is
published and when the page loads:
1. The only account whose name or institution shares a word with the employer (an "Acme Corp 401(k) Plan").
2. Otherwise, the only account whose statement lists those contributions: one paycheck's amount within a week, or a
   quarter's lines added up, all together or one kind of line.
3. Otherwise, the only account of that kind.

When it stays ambiguous, the page asks which account. If there is no such account, it asks you to add one. Your choice
in the account's settings, or "No employer", is kept and never changed automatically. A choice replaces an automatic
match on another account.

**Payments in are transfers, not spending.**
- **Matching.** `Reconciler.investment_transfers` matches a bank or card outflow of exactly the amount, within 5 days,
  to a contribution or deposit you made, or to a confirmed CD or Treasury bought.
- **Candidates.** A purchase line is a candidate only when it names the institution. Lines already in a ledger transfer
  are skipped.
- **Linking.** If there is one candidate, it is linked, and the line becomes a transfer unless you verified it. Several
  candidates become a question in Review. "Leave unmatched" is respected by later passes.
- **Display.** The activity shows "Paid from <account>".
- **"Not this payment"** undoes a match, automatic or yours (migration 041, `Reconciler.unlink_investment`):
  1. The line goes back to its type before the match, unless you verified it.
  2. The pair is recorded in `investment_payment_rejections` and never proposed again.
  3. If other lines could have paid it, Review asks which one, even when there's only one. Otherwise the contribution is
     left unmatched for good.

### Required minimum distributions

- **Birth year.** It is set in Settings and kept per profile (`HouseholdConfig.birth_year`).
- **The table.** `finance/retirement.py` holds the Uniform Lifetime Table: 26 CFR 1.401(a)(9)-9(c), Table 2, the same as
  Pub. 590-B Table III. It was checked against the regulation on 2026-09-28.
- **Start age.** Distributions begin in the year you reach 72 (born 1950 or earlier), 73 (born 1951–1959) or 75 (born
  1960 or later).
- **Which accounts.** Only tax-deferred accounts have them, decided by tax treatment. Pensions don't.
- **The amount.** Each account's amount is its confirmed balance at the end of the previous year, divided by the divisor
  for the age reached that year and rounded half-even. The balance is the newest value on or before Dec 31, flagged when
  older than a month.
- **On the page.** The Investments page shows this year's amount per account, what confirmed withdrawals already took,
  what's left, and the deadline. The first year's deadline is April 1 of the next year.
- **Not modelled:** the still-working exception for a current employer's plan, inherited accounts, and the joint table
  for a spouse more than ten years younger.

### Tax lots, gains and tax forms

**Lots** (`finance/tax_lots.py`, taxable accounts only) are worked out when read:
- Each confirmed buy with a printed quantity is a lot. A statement listing a confirmed trade again adds nothing.
- So is each lot you enter for shares bought before the documents here begin (`tax_lots`, migration 040).
- Confirmed sales close lots first in, first out:
  - the cost is taken in proportion to shares;
  - the proceeds are split in proportion to shares, and the last piece takes the rounding remainder;
  - a lot held more than a year (sold after its first anniversary) gives a long-term gain.
- Shares sold with no lot are reported and give no gain.
- The account view lists lots under "Tax lots", with unrealized gain by lot cost when the lots hold exactly the
  statement's shares.
- Wash sales, specific identification and basis adjustments are not handled ([taxes](taxes.md#for-cpa-review)).

**1099 and 5498 forms.** `investment_tax_form` is a document type filed under Taxes. It covers 1099-INT, -DIV, -B, -R,
-SA, -Q, -DA, 5498 and 5498-SA, including a consolidated 1099.
- Its summary has the payer, account, tax year and date. Its rows are boxes (`TaxBox`: form, box, label, amount), each
  checked against its citation.
- The form is linked to an account by institution and last four digits, otherwise to the only account at that
  institution. If neither works, it is kept unlinked. It waits for review.

**Taxes on the page** (year in the URL, `#/investments?year=2026`) compares each confirmed or waiting form with the
account's confirmed records for the year:

| Box | Compared with |
|---|---|
| INT 1 and 3 | interest |
| DIV 1a | dividends |
| B 1d / 1e, DA 1f / 1g | lot proceeds and cost |
| R 1, SA 1 and Q 1 | withdrawals |
| 5498 1 and 10, and 5498-SA 2 | contributions, including pay stub lines |

It also shows realized short- and long-term gains in taxable accounts. How these feed the year's return is in
[taxes](taxes.md#the-years-return).

### Kinds made specific

Migration 056 rebuilt `investment_kinds` with the `income` value model and added `pension_terms`, `price_quotes`,
`ibond_rates` and the `quote` valuation source.

#### I bonds
- **Valuation.** An I bond holding (`instrument_class='i_bond'`, with its principal and issue date) is valued by
  `ibond_value()` from the published rates in `ibond_rates`. Migration 056 seeds every rate from May 2015 to May 2026.
  Add each new rate (every May 1 and November 1) under "I bond rates" on the account, or with
  `PUT /api/investments/ibond-rates`.
- **The method follows TreasuryDirect:**
  - The composite rate is fixed + 2 × semiannual inflation + fixed × semiannual inflation, never below zero.
  - The fixed rate is the one for the issue month. The inflation rate resets every six months from the issue month, to
    the one in force at the start of each period.
  - The value is worked out for a $25 bond, rounded to the cent at each six-month step and at the month reached, then
    scaled to the principal. Interest is added on the first of each month and stops after 30 years.
  - A period that starts after the newest rate uses that newest rate until you add the next one.
- **Maturity and lock.** The maturity defaults to 30 years. The 12-month lock stays (the "redeemable" date).
- **If cashed today** shows the value three months earlier while the bond is under five years old, and nothing in its
  first year. No value at maturity is shown, since it depends on rates not yet published.
- **Purchase limit.** Purchases over $10,000 in a calendar year get a warning on the page and on the account. A profile
  is one person, and purchases waiting for review count too. Paper bonds bought with a tax refund aren't separated out.
- **Tax.** I bond and Treasury interest (accounts of kind `i_bond` or `treasury`, or 1099-INT box 3) is federal-taxable
  and state-exempt. `tax_year.gather()` reports it as `us_obligation_interest`, and the simplified state return leaves
  it out. The Education Savings Bond exclusion isn't worked out; type it over the records.

#### 529 plans
- **Settings.** The account settings add a **beneficiary** (a profile's name or anyone's) and the **plan state**.
- **Withdrawals** are `qualified_withdrawal` (tuition, books, room and board) or `nonqualified_withdrawal`. A
  statement's plain `withdrawal` is listed as "Not marked", with buttons to mark it. You can also record a withdrawal
  yourself; it counts at once.
- **Tax.** The Taxes panel shows each 529's non-qualified withdrawals for the year. Their taxable earnings are the
  withdrawal times the confirmed 1099-Q's box 2 (earnings) over box 1 (gross distribution). `tax_year.gather()` adds
  them to other income. The 10% additional tax usually applies too, and isn't computed.
- **Forecast.** A 529 (section `education`) is never drawn on by retirement withdrawals, and pays planned education
  costs.

#### Pensions
- **An income stream.** A pension has value model `income`, not a balance. Its account has `pension_terms`: the monthly
  benefit, start date, yearly raise (COLA, each January), survivor share, and a lump sum offered instead. The lump sum
  is shown for comparison and never counted.
- **Left out** of totals and shares, required minimum distributions, and the forecast's balances and withdrawals.
- **Forecast.** `Investments.forecast_pensions()` feeds `PensionIncome` streams into `project()`.
- **1099-R import** is unchanged.

#### Crypto
- **Prices** (`finance/prices.py`, modelled on `finance/fx.py`) come from CoinGecko's public simple-price endpoint.
  - They are fetched only when **Settings → Fetch crypto market prices** (`fetch_crypto_prices`, off by default) is on.
  - Requests go out at most once a day at startup, plus whenever you press **Refresh prices** on the account. A request
    names only coin ids and currencies, never amounts.
  - Prices are cached in `price_quotes` as exact decimal text, so coins worth less than a cent still value correctly.
  - Coins are matched by ticker (`COINGECKO_IDS`: BTC, ETH, SOL…). A coin not listed there isn't priced.
- **A price adds a `quote` value for today** (labelled "Market price"): each coin's units × price, plus cash carried
  from the statement.
  - Units are the newest confirmed statement's quantities, adjusted by confirmed buys, sells, transfers and rewards
    since.
  - An account holding anything without a price (a fund, an unknown coin) gets no quote at all, never a partial one.
  - Valuations stay append-only, and a document always takes precedence. An account with a statement or typed value
    dated today or later gets no quote, and a statement for the same date later replaces the quote.
- **Coinbase export.** "Import a Coinbase export" reads the transaction-history CSV (or XLSX) from the library
  (`parse_crypto_export`, preset `coinbase`).
  - Buys, sells, sends, receives and rewards become the account's activity; a conversion is a sale and a purchase.
  - Holdings are created by symbol. Fiat deposits and withdrawals are skipped, and unknown types are reported.
  - Importing the same file again adds nothing twice. The rows count at once, like a transaction import.
- **Tax.** Crypto is taxable, so confirmed buys open FIFO lots and sales give realized gains.

### Rules

- **Typed values** count at once. If you type a value for a date that already has one, yours replaces it, and later
  statements for that date don't change it.
- **Statement values** wait in Review under "Investment and loan documents to confirm", along with purchase
  confirmations and tax forms.
  - A newer statement adds a value. An older one is kept as history and doesn't change today's value.
  - Re-extracting a statement you already decided on changes nothing.
- **Current value.** An account's current value is its newest confirmed value. The change shown is the difference from
  the confirmed value before it.
- **Totals,** section shares and tax shares use confirmed values only, per currency. They are computed on the server,
  and the page only shows the text it receives.

### API

`GET /api/investment-kinds` · `GET /api/investments` (accounts, totals, shares) · `POST /api/investments` ·
`GET|PUT|DELETE /api/investments/{id}` (delete archives) · `POST /api/investments/{id}/values` ·
`GET /api/investments/review` · `POST /api/investments/valuations/{id}/review` ·
`GET /api/investments/valuations/{id}` and `…/valuations/by-asset/{asset_id}` (document page) ·
`GET /api/investments/confirmations/{id}`, `POST …/confirmations/{id}/review` ·
`POST /api/investments/{id}/holdings`, `PUT|DELETE /api/investments/holdings/{id}`, `POST …/holdings/{id}/matured` ·
`POST /api/investments/{id}/payroll` (answer the payroll question) · `POST /api/investments/events/{id}/unlink` ·
`GET /api/investments/rmd?year=` · `POST /api/investments/holdings/{id}/lots`, `DELETE /api/investments/lots/{id}` ·
`GET /api/investments/tax-forms/{id}`, `POST …/tax-forms/{id}/review`, `GET /api/investments/tax-years/{year}` ·
`PUT /api/investments/{id}/pension` · `POST /api/investments/{id}/events` · `POST /api/investments/events/{id}/qualified` ·
`GET|PUT /api/investments/ibond-rates` · `POST /api/investments/{id}/crypto-import` · `GET /api/prices`,
`POST /api/prices/refresh`.

### Planned: investment income

Not started. Migration 056 already added the `yield_bp` and `reinvest` columns, but nothing in `src/` uses them yet.
- **Yield.** Each investment account gets `yield_bp`: the part of the yearly return paid as dividends or interest. The
  rest is growth.
- **Paid or reinvested.** In `project()`, each month's yield on **taxable** accounts goes to cash, or is reinvested when
  the account's `reinvest` flag is set (on by default). It is reported as "investment income".
- **Tax.** That income is taxed at a new `investment_tax_percent` in `RetirementPlan` / `ForecastInput`.
- **Tax-advantaged accounts** keep compounding inside the balance, as now.
- **No change by default.** The default `yield_bp=0` keeps today's results, so existing forecasts and
  `tests/test_forecast.py` stay unchanged.
- **Tests:** a zero yield matches the old output, while a set yield moves cash and is taxed (`tests/test_forecast.py`).
  Also What If with yields (`tests/test_scenarios.py`).
