# What If

Try money plans before they are real: a new job whose first paychecks aren't representative, a move to another city or
state, or your forecast on someone else's salary. Planned 2026-09-29 in three phases; all three are built.

1. **Paycheck planner** (built): a paycheck worked out forward from gross pay, every line shown.
2. **Saved plans** (built): named plans based on a profile, the family or a blank slate. A plan's paychecks replace
   or add to pay, set category amounts replace spending (rent in the new city), and one-offs cover the move. Plans
   run through the forecast ([forecast.md](forecast.md)) side by side with "Now".
3. **Follow a plan** (built): turn a plan's set spending into budgets, then compare the plan with actual pay stubs
   (line by line) and actual spending.

## Paycheck planner

`finance/paycheck.py` (calculation), `POST /api/paycheck`, `GET /api/paycheck/from-stub/{id}`, `static/whatif.js`
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
  - The standard deduction comes from the year's confirmed table; a number you type replaces it, and the table's shows
    as the hint.
  - W-4 adjustments: step 3 credits (off the year's tax), step 4(a) other income (added to the year's wages), step 4(b)
    deductions (a second 0% bucket after the standard deduction) and step 4(c) extra withholding per paycheck.
  - **Step 2 checked** (more than one job, or a spouse who works): Publication 15-T's checkbox schedule. Every
    threshold is halved and rounded to whole dollars, so half the standard deduction is untaxed and each bracket starts
    at half its usual wage level.
  - Without the box, Pub 15-T's standard schedule (2020+ W-4, annual percentage method) is the tax brackets shifted by
    the standard deduction less the Step 1(g) amount ($8,600, or $12,900 married filing jointly), after that amount is
    taken off wages. That is the same as taxing wages less the standard deduction on the brackets, which is what the
    planner does, so it matches payroll's method.
- **State:**
  - The state's deduction or exemption comes from its confirmed table. Type one to replace it, for example where the
    state gives a personal exemption instead.
  - Instead of the table, a flat rate you type works the tax out now; use it for a flat-tax state not looked up yet.
  - **State credits** a year come off the state's year of tax, for states whose withholding uses credits (for example
    an exemption credit).
  - Also extra withholding, and state disability insurance (a percent, optionally up to a yearly wage limit).
- **Local tax:** a percent of income-tax wages or of gross pay, or an amount per paycheck.
- **Bonuses** (supplemental wages): each has a name, an amount and the month it is paid, with that month's first
  paycheck.
  - Percent-of-pay deductions and contributions (a 401(k) %, the match) take their share of it.
  - Federal withholding is the flat supplemental rate: 22%, and 37% on the year's supplemental wages above $1
    million (26 CFR 31.3402(g)-1).
  - The state's withholding is the "state rate on bonuses" you enter; left blank, a note says it is left out.
  - Social Security, Medicare and disability insurance count the bonus in its paycheck, so the wage base can be
    reached there.
  - The bonus appears in the year's column and in **Paychecks through the year**. The first regular paycheck stays
    the one shown.

**How it is worked out** (per paycheck and per year)
- **Wages:**
  - Income-tax wages are gross pay less every pre-tax deduction.
  - Social Security and Medicare wages are gross pay less the cafeteria-plan ones (health, dental, vision, HSA and FSA);
    a 401(k) doesn't lower them.
  - State wages are taken to be the federal ones.
- **Income taxes:** the same method as `paystub.income_tax`. A paycheck's wages times the paychecks in a year, less
  the deduction; each bracket taxes only its own slice; the year's tax is spread over the paychecks. Each tax has its
  bucket chart and table.
- **Social Security, Medicare and state disability** run paycheck by paycheck through the year. The paycheck where
  Social Security reaches its wage base (or disability insurance its limit), and where additional Medicare starts, is
  visible in **Paychecks through the year**. The first paycheck is shown in the table; the year's column adds up every
  paycheck.
- **Net pay:** gross pay less pre-tax deductions, taxes and post-tax deductions. It is shown per paycheck, per year,
  and as a monthly average (the year's net pay over 12), which is what a scenario will feed the forecast.
- **Contributions:** the retirement and HSA amounts per paycheck (yours plus your employer's) are returned for the
  scenario forecast.
- **Missing tables:** a missing or unconfirmed table is named, with a Look up button that uses the planned filing
  status. Those taxes are left out, and the page warns that take-home pay is too high until the table is confirmed. The
  planner never guesses a rate.
- Exact integer and Decimal arithmetic, rounded half-even to the cent; the browser shows the server's text.

**Start from a stub:** "Plan a paycheck from this stub" on a pay stub opens the planner (`#/whatif?stub=<id>`) with that
stub's earnings, pre-tax, post-tax and employer lines as amounts per paycheck.

## Saved plans

`finance/scenarios.py`, migration `043_scenarios.sql` (`scenarios`: name, basis, `inputs_json`, `adopted_at` for phase
3), `GET/POST /api/scenarios`, `PUT/DELETE /api/scenarios/{id}`, `POST /api/scenarios/{id}/duplicate`,
`POST /api/scenarios/compare`. The Plans and Compare panels on the What If page.

- **Stored:** a plan keeps its inputs only. Every comparison works every paycheck out again from today's tax tables
  and runs the forecast from today's records.
  - Inputs: its name, what it starts from, its paychecks (each a planner input with a name, first and optional last
    month, *replaces pay* or *adds to income*, and where its 401(k) and HSA contributions go), set spending,
    spending changes, one-offs and the forecast's assumptions.
  - Plans live in the open library; in the family view, in the family's own library.
- **Starts from:**
  - **My records:** this profile's forecast baseline.
  - **The family's records** (family view only): every member's baseline added together, exactly. Cash, take-home
    pay, income and each category's spending are summed; balances, bills and assets are listed with the member's
    name. Contributions can't be linked to one member's account from the family, so they go to new planned accounts.
  - **A blank slate:** only the cash you type (in the home currency, else USD). The plan's paychecks, spending and
    one-offs are everything. Use it for someone else's life or a household that doesn't exist yet.
- **Paycheck to forecast:**
  - Take-home pay a month is the year's regular net pay over 12. Each bonus is paid after its withholding in its
    calendar month every year the paycheck runs, and its 401(k)/HSA share goes into the account that month.
  - Contributions a month are each paycheck's retirement amount (pre-tax and Roth 401(k) plus the match and employer
    retirement lines) and its HSA amount (yours and the employer's), times the paychecks in a year, over 12.
  - These become the forecast's `pay_plans` ([forecast.md](forecast.md)): a replacing paycheck takes the place of the
    confirmed pay stubs' take-home pay and payroll contributions while it runs.
  - Without confirmed pay stubs there is nothing to replace, so the recorded income keeps whatever pay it includes; a
    note says so.
  - Retirement stops planned pay like any pay.
  - A paycheck whose tax tables are missing is still used; the notes say its take-home pay is too high.
- **Compare:** Now (this profile's or the family's forecast with the Forecast page's defaults) and saved plans, at most
  three lines together (the chart's three validated colors), all over the same years.
  - "Compare with now" runs the plan on screen, saved or not.
  - The result is a net-worth line chart with a table view, a warning for any plan whose cash falls below zero, and
    for each plan its paychecks as worked out, each year's income, spending, one-offs, contributions, cash and net
    worth, and its notes.
- **Retirement:** a plan can plan withdrawals with the same fields as the Forecast page (retire in, fixed amount or
  cover the shortfall, cash floor, tax on tax-deferred withdrawals). Its paychecks stop at retirement. The comparison
  details show "From investments", "Tax withheld" and "Required (RMD)" for years with withdrawals.
- **Cancel subscriptions:** a plan can cancel every confirmed subscription from a month on (the forecast's
  `cut_subscriptions_from`). Bills stay. The notes say how many were cancelled and roughly what that saves a month.
  Which recurring payments are subscriptions is the user's choice ([receipts-and-statements.md](receipts-and-statements.md#recurring-bills)).
- **Moving:** a move is a second paycheck from the move month with the new work state (the first gets a last month),
  set spending for rent and the like from that month, and one-offs for movers and deposits.
- The URL keeps the open plan (`#/whatif?plan=<id>`).
- **Tax Zen in <year>:** each compared plan shows where this year's return would end at the plan's pay for a full year,
  and the W-4 entry that brings it to $0. The planner shows the same "At tax time" for its paycheck alone. See
  [taxes.md](taxes.md#tax-zen).

## Following a plan

`finance/plan_tracking.py`, migration `044_scenario_adoption.sql` (`scenarios.adopted_month`),
`GET /api/scenarios/{id}/budgets?month=`, `POST /api/scenarios/{id}/adopt`, `POST /api/scenarios/{id}/stop`,
`GET /api/scenarios/{id}/actual`. The **Follow this plan** panel, shown for a saved plan in a person's profile. Budgets
and pay stubs belong to each person, so the family view doesn't follow plans.

- **Use as budgets:** choose the month the budgets start. The page lists each category the plan sets for that month:
  - the budget now and the plan's amount;
  - whether it is new, changes or is already set;
  - the budgets the plan doesn't name, which are left alone.
  Nothing changes until **Set N budgets and follow this plan**, which sets them (`ledger.set_budget`) and marks the
  plan followed from that month. Categories compare as budgets do: lower case, single spaces. Set spending is in
  today's dollars, so each budget is the amount as entered. A zero amount can't be a budget and is named instead.
- **Stop following:** the plan and the budgets it set both stay; only the follow mark is cleared.
- **Plan and actual** (any saved plan; before it is followed, from its first set spending month):
  - **Pay:** each paycheck that replaces pay, line by line, against this profile's confirmed pay stubs paid in its
    months. Lines: gross, each pre-tax deduction, each tax, each post-tax deduction, net. The columns are planned, the
    latest stub, the average of up to six stubs, and the difference (average less planned). A line a stub doesn't
    print counts as zero on it, so a planned deduction that never started shows up. Paychecks that add another earner
    aren't compared, since their stubs are in that person's profile.
  - **Spending:** each set spending amount against the category's counted spending (the budgets' figure). This runs
    month by month, newest first, for up to six months from the month the plan is followed; the current month is "so
    far". Each row is marked Over plan or Within plan.

**Not modelled:**
- the pre-2020 W-4 (withholding allowances);
- payroll systems that round withholding to whole dollars;
- state withholding formulas beyond the state's brackets, its deduction or exemption and the credits you enter;
- state rules that treat some pre-tax deductions differently from federal.

The notes under the breakdown say so where it matters.
