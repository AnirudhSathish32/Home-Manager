"""Deterministic income, spending and net-worth forecast (docs/forecast.md).

Starting figures come from the ledger: each account's latest statement balance, average monthly
income and per-category spending over recent full months, and reviewed assets and loans. The
projection then runs month by month in exact decimal arithmetic, rounding every monthly amount
to the currency's minor unit (half-even). The same inputs always give the same numbers; no model
is involved and nothing is written.

Assumptions (all adjustable): prices rise with inflation (2% a year by default), so spending
grows with it; income stays flat unless an income growth rate or changes are set; each asset grows
at its own yearly rate; each loan accrues its yearly interest monthly and is paid down by its
monthly payment until repaid. Account balances are cash: income adds to it, spending, loan
payments and one-off expenses take from it.
"""

from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..core.categories import FREQUENCY_MONTHS
from ..core.money import currency_code, money, to_minor
from ..library.storage import now
from .investments import Investments
from .ledger import COUNTABLE
from .reconcile import Reconciler, bill_payments
from .retirement import HAS_RMD, divisor, rmd_start_age
from .tools import AccountInput, FinanceTools, PeriodInput, scope_of

# Investment accounts live in finance/investments.py and join the forecast from there.
ASSET_KINDS = ("real_estate", "vehicle", "other_asset", "loan")
# Retirement withdrawals come from taxable money first, then tax-deferred, then tax-free, and an HSA last (it is tax-free
# for medical costs, so it is kept for them).
WITHDRAWAL_ORDER = {"taxable": 0, "tax_deferred": 1, "tax_free": 2, "hsa": 3}
# Starting yearly growth when an asset is added without one: cars lose value; other assets are
# left flat until the user chooses a rate. Loans have no default interest rate.
DEFAULT_RATE_BP = {"vehicle": -1500}
MAX_YEARS = 100
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
PERCENT = r"^-?\d{1,3}(\.\d{1,2})?$"


def minor(value):
    """Round a Decimal amount in minor units to a whole minor unit, half-even."""
    return int(value.to_integral_value(ROUND_HALF_EVEN))


def month_add(month, count):
    year, number = int(month[:4]), int(month[5:7]) - 1 + count
    return f"{year + number // 12:04d}-{number % 12 + 1:02d}"


def month_steps(first, second):
    """Months from one YYYY-MM to another; negative when the second is earlier."""
    return (int(second[:4]) - int(first[:4])) * 12 + int(second[5:7]) - int(first[5:7])


def month_end(month):
    following = date.fromisoformat(month_add(month, 1) + "-01")
    return date.fromordinal(following.toordinal() - 1).isoformat()


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AssetInput(StrictInput):
    name: str = Field(min_length=1, max_length=80)
    kind: str = Field(json_schema_extra={"enum": list(ASSET_KINDS)})
    value: str = Field(min_length=1, max_length=30, description="Current value, or the amount still owed on a loan.")
    currency: str = Field(pattern=r"^[A-Za-z]{3}$")
    as_of: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    annual_rate_percent: str | None = Field(default=None, pattern=PERCENT, description="Yearly growth, or a loan's yearly interest rate.")
    monthly_payment: str | None = Field(default=None, max_length=30, description="Loans only.")

    @field_validator("kind")
    @classmethod
    def known_kind(cls, value):
        if value not in ASSET_KINDS:
            raise ValueError(f"Choose one of: {', '.join(ASSET_KINDS)}.")
        return value

    @model_validator(mode="after")
    def consistent(self):
        date.fromisoformat(self.as_of)
        if self.monthly_payment and self.kind != "loan":
            raise ValueError("Only loans have a monthly payment.")
        return self


class SpendingChange(StrictInput):
    category: str = Field(min_length=1, max_length=60)
    percent: str = Field(pattern=PERCENT)


class OneOff(StrictInput):
    month: str = Field(pattern=MONTH.pattern)
    amount: str = Field(min_length=1, max_length=30, description="Money in is positive, an expense negative.")
    label: str = Field(default="", max_length=80)


class IncomeChange(StrictInput):
    month: str = Field(pattern=MONTH.pattern)
    monthly_amount: str = Field(min_length=1, max_length=30, description="Added to monthly income from this month on; negative lowers it.")


class RetirementPlan(StrictInput):
    """Withdrawals from investments once retired. A self-contained input like the rest of ForecastInput (never stored), so
    what-if scenarios can vary it and run side by side."""
    start_month: str = Field(pattern=MONTH.pattern, description="Take-home pay and payroll contributions stop; withdrawals begin.")
    mode: Literal["fixed", "shortfall"] = Field(description="fixed: a monthly amount; shortfall: whatever keeps cash at the floor.")
    monthly_amount: str | None = Field(default=None, max_length=30, description="Fixed mode: reaching cash after tax, in today's money; grows with inflation.")
    cash_floor: str = Field(default="0", max_length=30, description="Shortfall mode: the least cash to keep, in today's money.")
    tax_percent: str = Field(default="0", pattern=r"^\d{1,2}(\.\d{1,2})?$", description="Flat tax on withdrawals from tax-deferred accounts.")

    @model_validator(mode="after")
    def consistent(self):
        if self.mode == "fixed" and not self.monthly_amount:
            raise ValueError("Enter the monthly amount to withdraw.")
        return self


class ForecastInput(StrictInput):
    years: int = Field(default=10, ge=1, le=MAX_YEARS)
    retirement: RetirementPlan | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    inflation_percent: str = Field(default="2", pattern=PERCENT)
    income_growth_percent: str = Field(default="0", pattern=PERCENT)
    history_months: int = Field(default=6, ge=1, le=24)
    spending_changes: list[SpendingChange] = Field(default_factory=list, max_length=50)
    one_offs: list[OneOff] = Field(default_factory=list, max_length=200)
    income_changes: list[IncomeChange] = Field(default_factory=list, max_length=50)


class Assets:
    def __init__(self, store):
        self.store = store

    def list(self, include_archived=False):
        with self.store.connection() as db:
            rows = db.execute("SELECT * FROM assets" + ("" if include_archived else " WHERE archived_at IS NULL") + " ORDER BY kind='loan',name,id")
            return [self.view(dict(row)) for row in rows]

    @staticmethod
    def view(row):
        rate = Decimal(row["annual_rate_bp"]) / 100
        row["issues"] = json.loads(row.pop("validation_json", None) or "[]")
        return {**row, "value": money(row["value_minor"], row["currency"]), "annual_rate_percent": f"{rate.normalize():f}",
                "monthly_payment": money(row["monthly_payment_minor"], row["currency"]) if row["monthly_payment_minor"] is not None else None}

    @staticmethod
    def columns(value: AssetInput):
        currency = currency_code(value.currency)
        amount = to_minor(value.value, currency)
        if amount < 0:
            raise ValueError("Enter a value of zero or more; a loan's value is the amount still owed.")
        payment = to_minor(value.monthly_payment, currency) if value.monthly_payment else None
        if payment is not None and payment < 0:
            raise ValueError("A monthly payment cannot be negative.")
        rate = (Decimal(value.annual_rate_percent) * 100 if value.annual_rate_percent is not None
                else Decimal(DEFAULT_RATE_BP.get(value.kind, 0)))
        if rate != rate.to_integral_value() or not -10000 <= rate <= 10000:
            raise ValueError("Use a yearly rate between -100% and 100% with at most two decimals.")
        return {"name": " ".join(value.name.split()), "kind": value.kind, "value_minor": amount, "currency": currency, "as_of": value.as_of,
                "annual_rate_bp": int(rate), "monthly_payment_minor": payment}

    def add(self, value: AssetInput):
        """A value the user enters is their own input: it counts at once."""
        columns = {**self.columns(value), "source": "manual", "review_status": "verified", "created_at": now(), "updated_at": now()}
        with self.store.connection() as db:
            asset_id = db.execute(f"INSERT INTO assets({','.join(columns)}) VALUES({','.join('?' * len(columns))})", tuple(columns.values())).lastrowid
        return self.get(asset_id)

    def update(self, asset_id, value: AssetInput):
        self.get(asset_id)
        columns = {**self.columns(value), "updated_at": now()}
        with self.store.connection() as db:
            db.execute(f"UPDATE assets SET {','.join(f'{key}=?' for key in columns)} WHERE id=?", (*columns.values(), asset_id))
        return self.get(asset_id)

    def archive(self, asset_id):
        self.get(asset_id)
        with self.store.connection() as db:
            db.execute("UPDATE assets SET archived_at=?,updated_at=? WHERE id=?", (now(), now(), asset_id))
        return {"id": asset_id, "archived": True}

    def get(self, asset_id):
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
        if row is None:
            raise ValueError("Asset not found.")
        return self.view(dict(row))

    def review(self, asset_id, status):
        """Confirm or reject a value read from a statement; confirmed values count in the forecast. Audited like other reviews."""
        if status not in ("verified", "rejected", "proposed"):
            raise ValueError("Choose confirm, reject or undo.")
        asset = self.get(asset_id)
        if asset["source"] != "statement":
            raise ValueError("Only values read from statements are reviewed; values you enter count at once.")
        with self.store.connection() as db:
            db.execute("UPDATE assets SET review_status=?,updated_at=? WHERE id=?", (status, now(), asset_id))
            db.execute("INSERT INTO review_events(record_type,record_id,previous_status,new_status,note,created_at) VALUES('asset',?,?,?,'',?)",
                       (asset_id, asset["review_status"], status, now()))
        return self.get(asset_id)


def baseline(tools: FinanceTools, assets: Assets, history_months, currency=None, today=None):
    """Starting figures for one currency: balances, recent monthly income and spending, assets, loans."""
    today = today or date.today()
    first = month_add(today.isoformat()[:7], -history_months)
    last = month_add(today.isoformat()[:7], -1)
    period = PeriodInput(start=first + "-01", end=month_end(last))
    accounts = tools.get_accounts()["accounts"]
    investments = Investments(assets.store, today)
    held = [asset for asset in assets.list() if asset["review_status"] == "verified"] + investments.forecast_assets(period.start, period.end, history_months)
    currencies = {account["currency"] for account in accounts} | {asset["currency"] for asset in held}
    flow = {row["currency"]: row for row in tools.calculate_cashflow(period)["by_currency"]}
    currencies |= set(flow)
    if currency:
        chosen = currency_code(currency)
    elif len(currencies) == 1:
        chosen = next(iter(currencies))
    elif currencies:
        chosen = max(sorted(currencies), key=lambda code: sum(1 for account in accounts if account["currency"] == code))
    else:
        chosen = "USD"
    notes = []
    cash, balances = 0, []
    linked = investments.linked_ledger_accounts()  # A savings account kept as an investment (a HYSA) counts there, not as cash.
    for account in accounts:
        if account["currency"] != chosen or account["id"] in linked:
            continue
        balance = tools.get_account_balance(AccountInput(account_id=account["id"]))["balance"]
        if balance is None:
            notes.append(f"{account['display_name']} has no statement balance, so it starts at zero.")
            continue
        signed = -balance["minor"] if account["account_type"] == "credit_card" else balance["minor"]
        cash += signed
        balances.append({"account": account["display_name"], "type": account["account_type"], "amount": money(signed, chosen), "as_of": balance["as_of"]})
    categories = {category: total for (code, category), (total, _) in tools._category_totals(period.start, period.end, None).items() if code == chosen}
    scope, params = scope_of(period.start, period.end, None)
    refunds = sum(bucket["refunds"] for (_, code), bucket in tools._totals(period.start, period.end, None).items() if code == chosen)
    if refunds:
        categories["refunds"] = -refunds
    # Confirmed recurring bills are projected on their own schedule, so their past payments leave the category averages.
    bills = []
    with tools.connection() as db:
        for bill in Reconciler.bills(db):
            if bill["status"] != "verified" or bill["currency"] != chosen:
                continue
            for payment in bill_payments(db, bill, period.start, period.end):
                if payment["category"] in categories:
                    categories[payment["category"]] -= payment["amount"]
            bills.append({"name": bill["merchant"], "category": bill["category"] or "bills", "amount_minor": bill["expected_amount_minor"],
                          "frequency": bill["frequency"], "next_due": bill["next_due_date"]})
    categories = {category: total for category, total in categories.items() if total}
    if bills:
        notes.append(f"{len(bills)} confirmed recurring {'bill is' if len(bills) == 1 else 'bills are'} placed on {'its' if len(bills) == 1 else 'their'} "
                     "due months; past payments to them are left out of the spending averages.")
    income = flow.get(chosen, {}).get("inflow", {}).get("minor", 0)
    months_seen = tools.query(f"SELECT count(DISTINCT substr(t.posted_date,1,7)) AS months FROM transactions t WHERE {COUNTABLE} AND {scope} AND t.currency=?",
                              (*params, chosen))[0]["months"]
    if categories and months_seen < history_months:
        notes.append(f"Only {months_seen} of the last {history_months} months have transactions, so monthly averages may be too low.")
    if not categories and not income:
        notes.append(f"No counted income or spending between {period.start} and {period.end}; the forecast has only balances and assets.")
    other = sorted(currencies - {chosen})
    if other:
        notes.append(f"Amounts in {', '.join(other)} are left out; forecasts are in one currency ({chosen}).")
    pending = [asset["name"] for asset in assets.list() if asset["review_status"] == "proposed"] + investments.waiting_names()
    if pending:
        notes.append(f"Waiting for review, so not included: {', '.join(pending)}.")
    # Take-home pay from confirmed pay stubs: what stops when retirement begins.
    with tools.connection() as db:
        pay = db.execute("SELECT coalesce(sum(net_pay_minor),0) FROM income_records WHERE review_status='verified' AND currency=? AND pay_date BETWEEN ? AND ?",
                         (chosen, period.start, period.end)).fetchone()[0]
    return {"currency": chosen, "history": {"start": period.start, "end": period.end, "months": history_months, "months_with_data": months_seen},
            "cash": cash, "balances": balances, "monthly_pay": Decimal(pay) / history_months,
            "monthly_income": Decimal(income) / history_months,
            "monthly_spending": {category: Decimal(total) / history_months for category, total in sorted(categories.items())},
            "bills": bills, "assets": [asset for asset in held if asset["currency"] == chosen], "notes": notes}


def bill_amount(bill, month, start):
    """What a recurring bill costs in one projected month, before inflation: weekly bills spread evenly; others fall
    in their due months, counted on from the next due date (a date already past moves forward to the first projected month)."""
    if bill["frequency"] == "weekly":
        return Decimal(bill["amount_minor"]) * 52 / 12
    every = FREQUENCY_MONTHS[bill["frequency"]]
    due = (bill["next_due"] or start + "-01")[:7]
    while due < start:
        due = month_add(due, every)
    steps = (int(month[:4]) - int(due[:4])) * 12 + int(month[5:7]) - int(due[5:7])
    return Decimal(bill["amount_minor"]) if steps >= 0 and steps % every == 0 else Decimal(0)


def available(holding):
    """What an asset holds now: its balance and its CDs or Treasuries not yet matured."""
    return holding["balance"] + sum(piece["balance"] for piece in holding["pieces"] if not piece["done"])


def take(holding, amount):
    """Take from an account's balance first, then from its CDs or Treasuries, soonest maturing first."""
    used = min(amount, holding["balance"])
    holding["balance"] -= used
    amount -= used
    for piece in sorted((piece for piece in holding["pieces"] if not piece["done"]), key=lambda piece: piece["month"]):
        used = min(amount, piece["balance"])
        piece["balance"] -= used
        piece["target"] = piece["target"] * (piece["balance"] / (piece["balance"] + used)) if piece["balance"] + used > 0 else Decimal(0)
        amount -= used


def project(base, value: ForecastInput, today=None, birth_year=None):
    """Month-by-month projection from a baseline. Pure: the same inputs give the same output. With a birth year, tax-deferred
    accounts pay out their required minimum distributions each December (finance/retirement.py); with a retirement plan,
    pay and payroll contributions stop and withdrawals begin."""
    today = today or date.today()
    currency = base["currency"]
    start = month_add(today.isoformat()[:7], 1)
    months = value.years * 12
    with localcontext() as context:
        context.prec = 34
        one = Decimal(1)
        inflation = (one + Decimal(value.inflation_percent) / 100) ** (one / 12)
        income_growth = (one + Decimal(value.income_growth_percent) / 100) ** (one / 12)
        changes = {change.category: one + Decimal(change.percent) / 100 for change in value.spending_changes}
        unknown = sorted(set(changes) - set(base["monthly_spending"]) - {bill["category"] for bill in base.get("bills", [])})
        spending = {category: amount * changes.get(category, one) for category, amount in base["monthly_spending"].items()}
        income_steps = sorted((change.month, Decimal(to_minor(change.monthly_amount, currency))) for change in value.income_changes)
        one_offs: dict[str, list[tuple[int, str]]] = {}
        for item in value.one_offs:
            one_offs.setdefault(item.month, []).append((to_minor(item.amount, currency), item.label))
        holdings = []
        for asset in base["assets"]:
            # A CD or Treasury grows at its own pace to its value at maturity, then leaves the account (to cash unless it renews).
            pieces = []
            for term in asset.get("terms", []):
                steps = max(month_steps(start, term["maturity_month"]), 0)
                worth_now, target = Decimal(term["value_minor"]), Decimal(term["maturity_value_minor"])
                pieces.append({"name": term["name"], "balance": worth_now, "target": target, "month": month_add(start, steps), "to_cash": term["to_cash"],
                               "rate": (target / worth_now) ** (one / (steps + 1)) if worth_now > 0 else one, "done": False})
            rest = Decimal(asset["value_minor"]) - sum(piece["balance"] for piece in pieces)
            holdings.append({"name": asset["name"], "kind": asset["kind"], "balance": max(rest, Decimal(0)), "pieces": pieces,
                             "rate": (one + Decimal(asset["annual_rate_bp"]) / 10000) ** (one / 12) if asset["kind"] != "loan" else Decimal(asset["annual_rate_bp"]) / 10000 / 12,
                             "payment": Decimal(asset["monthly_payment_minor"] or 0),
                             # Paid in from pay (already outside take-home pay, so cash is untouched) and from you (out of cash).
                             "payroll": Decimal(asset.get("payroll_monthly_minor") or 0), "personal": Decimal(asset.get("personal_monthly_minor") or 0),
                             # Investment accounts can be drawn on in retirement; tax-deferred ones also have required distributions.
                             "investment": asset.get("source") == "investment", "tax": asset.get("tax_treatment"), "withdrawn": Decimal(0)})
        for holding in holdings:
            holding["year_start"] = available(holding)  # Its balance at the end of the year before, for required distributions.
        drawable = sorted((holding for holding in holdings if holding["investment"]), key=lambda holding: WITHDRAWAL_ORDER.get(holding["tax"], len(WITHDRAWAL_ORDER)))
        plan = value.retirement
        tax = Decimal(plan.tax_percent) / 100 if plan else Decimal(0)
        fixed = Decimal(to_minor(plan.monthly_amount, currency)) if plan and plan.mode == "fixed" else None
        floor = Decimal(to_minor(plan.cash_floor, currency)) if plan and plan.mode == "shortfall" else None
        pay = base.get("monthly_pay", Decimal(0))
        cash, price, pay_level = Decimal(base["cash"]), one, one
        rows, notes = [], list(base["notes"])
        if unknown:
            notes.append(f"No recent spending in {', '.join(unknown)}; those changes have no effect.")
        if plan and pay:
            notes.append(f"Take-home pay of {money(minor(pay), currency)['display']} a month (confirmed pay stubs) stops in {plan.start_month}, "
                         "and so do contributions from pay.")
        first_rmd = birth_year + rmd_start_age(birth_year) if birth_year else None
        if first_rmd and any(holding["tax"] in HAS_RMD for holding in drawable) and first_rmd <= int(month_add(start, months - 1)[:4]):
            notes.append(f"Required minimum distributions from tax-deferred accounts begin in {first_rmd} (age {rmd_start_age(birth_year)}); each December "
                         "takes out at least the year's required amount.")
        if not birth_year and any(holding["tax"] in HAS_RMD for holding in drawable):
            notes.append("Add the year you were born in Settings to include required minimum distributions.")
        ran_out = None

        def draw(needed, only=None):
            """Withdraw so `needed` reaches cash after tax, in order (taxable, tax-deferred, tax-free, HSA), or only from one
            account. A tax-deferred withdrawal is grossed up at the flat rate. Returns (reaching cash, tax, still missing)."""
            delivered = taxed = Decimal(0)
            for holding in [only] if only else drawable:
                if needed <= 0:
                    break
                rate = tax if holding["tax"] in HAS_RMD else Decimal(0)
                gross = min(needed / (one - rate), available(holding))
                if gross <= 0:
                    continue
                take(holding, gross)
                holding["withdrawn"] += gross
                delivered += gross * (one - rate)
                taxed += gross * rate
                needed -= gross * (one - rate)
            return delivered, taxed, max(needed, Decimal(0))
        for step in range(months):
            month = month_add(start, step)
            price *= inflation
            pay_level *= income_growth
            retired = plan is not None and month >= plan.start_month
            base_income = base["monthly_income"] + sum(amount for since, amount in income_steps if since <= month)
            income = minor(max(base_income - pay, Decimal(0)) * pay_level if retired else base_income * pay_level)
            spent = {category: minor(amount * price) for category, amount in spending.items()}
            for bill in base.get("bills", []):
                due = bill_amount(bill, month, start) * changes.get(bill["category"], one)
                if due:
                    spent[bill["category"]] = spent.get(bill["category"], 0) + minor(due * price)
            outgoing = sum(spent.values())
            extra = sum(amount for amount, _ in one_offs.get(month, []))
            loan_paid = contributed = saved = matured = 0
            for holding in holdings:
                if holding["kind"] == "loan":
                    if holding["balance"] <= 0:
                        continue
                    owed = holding["balance"] + (holding["balance"] * holding["rate"]).quantize(one, ROUND_HALF_EVEN)
                    paid = min(holding["payment"], owed)
                    holding["balance"] = owed - paid
                    loan_paid += int(paid)
                    continue
                # Nothing is paid in once retired: no pay, and money now flows out.
                paid_in = Decimal(0) if retired else holding["payroll"] + holding["personal"]
                holding["balance"] = holding["balance"] * holding["rate"] + paid_in
                contributed += minor(paid_in)
                saved += 0 if retired else minor(holding["personal"])
                for piece in holding["pieces"]:
                    if piece["done"]:
                        continue
                    piece["balance"] *= piece["rate"]
                    if month >= piece["month"]:
                        piece["done"] = True
                        if piece["to_cash"]:
                            matured += minor(piece["target"])
                        else:
                            holding["balance"] += piece["target"]
            cash += income - outgoing - loan_paid - saved + extra + matured
            withdrawn = withdrawal_tax = forced = Decimal(0)
            if retired:
                # A fixed amount grown with prices, or whatever keeps cash at the floor (also grown with prices).
                # A plan sets exactly one of fixed and floor, so floor is set whenever fixed is not.
                needed = fixed * price if fixed is not None else max(floor * price - cash, Decimal(0))  # type: ignore[operator]
                withdrawn, withdrawal_tax, missing = draw(needed)
                if missing > 0 and ran_out is None:
                    ran_out = month
            if first_rmd and month.endswith("-12") and int(month[:4]) >= first_rmd:
                # Each tax-deferred account must have paid out its balance at the end of last year over the divisor for this age.
                period = divisor(int(month[:4]) - birth_year)
                for holding in drawable:
                    owed = holding["year_start"] / period - holding["withdrawn"] if holding["tax"] in HAS_RMD else Decimal(0)
                    if owed > 0:
                        got, taxed, _ = draw(owed * (one - tax), only=holding)
                        forced += got
                        withdrawn += got
                        withdrawal_tax += taxed
            cash += withdrawn
            if month.endswith("-12"):
                for holding in holdings:
                    holding["year_start"], holding["withdrawn"] = available(holding), Decimal(0)
            asset_total = sum(minor(h["balance"]) + sum(minor(p["balance"]) for p in h["pieces"] if not p["done"]) for h in holdings if h["kind"] != "loan")
            loan_total = sum(minor(h["balance"]) for h in holdings if h["kind"] == "loan")
            worth = minor(cash) + asset_total - loan_total
            rows.append({"month": month, "income": income, "spending": outgoing, "loan_payments": loan_paid, "one_offs": extra,
                         "contributions": contributed, "invested_from_cash": saved, "matured": matured,
                         "withdrawals": minor(withdrawn), "withdrawal_tax": minor(withdrawal_tax), "rmd": minor(forced),
                         "net_cash_flow": income - outgoing - loan_paid - saved + extra + matured + minor(withdrawn), "cash": minor(cash),
                         "assets": asset_total, "loans": loan_total, "net_worth": worth,
                         "net_worth_today": minor(Decimal(worth) / price), "price_level": str(price.quantize(Decimal("0.000001")))})
        for holding in holdings:
            if holding["kind"] == "loan" and holding["balance"] > 0 and holding["payment"] <= holding["balance"] * holding["rate"]:
                notes.append(f"{holding['name']}: the monthly payment does not cover the interest, so this loan never shrinks.")
        if ran_out:
            notes.append(f"Investments run out in {ran_out}: from then on the planned withdrawals can't be met.")
        if plan and pay and pay > base["monthly_income"]:
            notes.append("Take-home pay on pay stubs is more than the recorded monthly income, so income after retirement is taken as zero.")
    years = []
    for index in range(value.years):
        chunk = rows[index * 12:(index + 1) * 12]
        years.append({"year": chunk[0]["month"][:4] if chunk[0]["month"].endswith("-01") else f"{chunk[0]['month']} to {chunk[-1]['month']}",
                      "income": sum(row["income"] for row in chunk), "spending": sum(row["spending"] for row in chunk),
                      "loan_payments": sum(row["loan_payments"] for row in chunk), "one_offs": sum(row["one_offs"] for row in chunk),
                      "contributions": sum(row["contributions"] for row in chunk), "matured": sum(row["matured"] for row in chunk),
                      "withdrawals": sum(row["withdrawals"] for row in chunk), "withdrawal_tax": sum(row["withdrawal_tax"] for row in chunk),
                      "rmd": sum(row["rmd"] for row in chunk),
                      "end_cash": chunk[-1]["cash"], "end_assets": chunk[-1]["assets"], "end_loans": chunk[-1]["loans"],
                      "end_net_worth": chunk[-1]["net_worth"], "end_net_worth_today": chunk[-1]["net_worth_today"]})
    for year in years:
        year["display"] = {key: money(amount, currency)["display"] for key, amount in year.items() if isinstance(amount, int)}
    short = next((row["month"] for row in rows if row["cash"] < 0), None)
    return {"currency": currency, "start_month": start, "months": rows, "years": years, "notes": notes,
            "first_month_cash_below_zero": short,
            "assumptions": {"inflation_percent": value.inflation_percent, "income_growth_percent": value.income_growth_percent,
                            "history": base["history"], "spending_changes": [change.model_dump() for change in value.spending_changes],
                            "income_changes": [change.model_dump() for change in value.income_changes],
                            "one_offs": [item.model_dump() for item in value.one_offs],
                            "retirement": plan.model_dump() if plan else None, "birth_year": birth_year,
                            "rmd_start": {"year": first_rmd, "age": rmd_start_age(birth_year)} if birth_year else None},
            "starting_point": {"cash": money(base["cash"], currency), "balances": base["balances"],
                               "monthly_income": money(minor(base["monthly_income"]), currency),
                               "monthly_pay": money(minor(pay), currency),
                               "monthly_spending": [{"category": category, "amount": money(minor(amount), currency)}
                                                    for category, amount in base["monthly_spending"].items()],
                               "recurring_bills": [{"name": bill["name"], "category": bill["category"], "frequency": bill["frequency"],
                                                    "next_due": bill["next_due"], "amount": money(bill["amount_minor"], currency)}
                                                   for bill in base.get("bills", [])],
                               "assets": [{"name": asset["name"], "kind": asset["kind"], "kind_label": asset.get("kind_label"), "investment": asset.get("source") == "investment",
                                           "value": asset["value"], "annual_rate_percent": asset["annual_rate_percent"],
                                           "monthly_payment": asset["monthly_payment"],
                                           "monthly_from_pay": money(asset["payroll_monthly_minor"], currency) if asset.get("payroll_monthly_minor") else None,
                                           "monthly_from_you": money(asset["personal_monthly_minor"], currency) if asset.get("personal_monthly_minor") else None,
                                           "maturing": [{"name": term["name"], "month": term["maturity_month"], "to_cash": term["to_cash"],
                                                         "amount": money(term["maturity_value_minor"], currency)} for term in asset.get("terms", [])]}
                                          for asset in base["assets"]]}}


def forecast(store, value: ForecastInput, today=None, birth_year=None):
    base = baseline(FinanceTools(store), Assets(store), value.history_months, value.currency, today)
    return project(base, value, today, birth_year)
