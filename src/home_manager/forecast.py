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

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .finance import COUNTABLE
from .finance_tools import AccountInput, FinanceTools, PeriodInput, scope_of
from .money import currency_code, money, to_minor
from .storage import now

ASSET_KINDS = ("investment", "retirement", "bond", "real_estate", "vehicle", "other_asset", "loan")
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


class ForecastInput(StrictInput):
    years: int = Field(default=10, ge=1, le=MAX_YEARS)
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
    held = [asset for asset in assets.list() if asset["review_status"] == "verified"]
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
    for account in accounts:
        if account["currency"] != chosen:
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
    refunds = sum(bucket["refunds"] for (_, code), bucket in tools._totals(scope, params).items() if code == chosen)
    if refunds:
        categories["refunds"] = -refunds
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
    pending = [asset["name"] for asset in assets.list() if asset["review_status"] == "proposed"]
    if pending:
        notes.append(f"Waiting for review, so not included: {', '.join(pending)}.")
    return {"currency": chosen, "history": {"start": period.start, "end": period.end, "months": history_months, "months_with_data": months_seen},
            "cash": cash, "balances": balances,
            "monthly_income": Decimal(income) / history_months,
            "monthly_spending": {category: Decimal(total) / history_months for category, total in sorted(categories.items())},
            "assets": [asset for asset in held if asset["currency"] == chosen], "notes": notes}


def project(base, value: ForecastInput, today=None):
    """Month-by-month projection from a baseline. Pure: the same inputs give the same output."""
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
        unknown = sorted(set(changes) - set(base["monthly_spending"]))
        spending = {category: amount * changes.get(category, one) for category, amount in base["monthly_spending"].items()}
        income_steps = sorted((change.month, Decimal(to_minor(change.monthly_amount, currency))) for change in value.income_changes)
        one_offs = {}
        for item in value.one_offs:
            one_offs.setdefault(item.month, []).append((to_minor(item.amount, currency), item.label))
        holdings = [{"name": asset["name"], "kind": asset["kind"], "balance": Decimal(asset["value_minor"]),
                     "rate": (one + Decimal(asset["annual_rate_bp"]) / 10000) ** (one / 12) if asset["kind"] != "loan" else Decimal(asset["annual_rate_bp"]) / 10000 / 12,
                     "payment": Decimal(asset["monthly_payment_minor"] or 0)} for asset in base["assets"]]
        cash, price, pay_level = Decimal(base["cash"]), one, one
        rows, notes = [], list(base["notes"])
        if unknown:
            notes.append(f"No recent spending in {', '.join(unknown)}; those changes have no effect.")
        for step in range(months):
            month = month_add(start, step)
            price *= inflation
            pay_level *= income_growth
            base_income = base["monthly_income"] + sum(amount for since, amount in income_steps if since <= month)
            income = minor(base_income * pay_level)
            spent = {category: minor(amount * price) for category, amount in spending.items()}
            outgoing = sum(spent.values())
            extra = sum(amount for amount, _ in one_offs.get(month, []))
            loan_paid = 0
            for holding in holdings:
                if holding["kind"] == "loan":
                    if holding["balance"] <= 0:
                        continue
                    owed = holding["balance"] + (holding["balance"] * holding["rate"]).quantize(one, ROUND_HALF_EVEN)
                    paid = min(holding["payment"], owed)
                    holding["balance"] = owed - paid
                    loan_paid += int(paid)
                else:
                    holding["balance"] *= holding["rate"]
            cash += income - outgoing - loan_paid + extra
            asset_total = sum(minor(h["balance"]) for h in holdings if h["kind"] != "loan")
            loan_total = sum(minor(h["balance"]) for h in holdings if h["kind"] == "loan")
            worth = minor(cash) + asset_total - loan_total
            rows.append({"month": month, "income": income, "spending": outgoing, "loan_payments": loan_paid, "one_offs": extra,
                         "net_cash_flow": income - outgoing - loan_paid + extra, "cash": minor(cash),
                         "assets": asset_total, "loans": loan_total, "net_worth": worth,
                         "net_worth_today": minor(Decimal(worth) / price), "price_level": str(price.quantize(Decimal("0.000001")))})
        for holding in holdings:
            if holding["kind"] == "loan" and holding["balance"] > 0 and holding["payment"] <= holding["balance"] * holding["rate"]:
                notes.append(f"{holding['name']}: the monthly payment does not cover the interest, so this loan never shrinks.")
    years = []
    for index in range(value.years):
        chunk = rows[index * 12:(index + 1) * 12]
        years.append({"year": chunk[0]["month"][:4] if chunk[0]["month"].endswith("-01") else f"{chunk[0]['month']} to {chunk[-1]['month']}",
                      "income": sum(row["income"] for row in chunk), "spending": sum(row["spending"] for row in chunk),
                      "loan_payments": sum(row["loan_payments"] for row in chunk), "one_offs": sum(row["one_offs"] for row in chunk),
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
                            "one_offs": [item.model_dump() for item in value.one_offs]},
            "starting_point": {"cash": money(base["cash"], currency), "balances": base["balances"],
                               "monthly_income": money(minor(base["monthly_income"]), currency),
                               "monthly_spending": [{"category": category, "amount": money(minor(amount), currency)}
                                                    for category, amount in base["monthly_spending"].items()],
                               "assets": [{"name": asset["name"], "kind": asset["kind"], "value": asset["value"], "annual_rate_percent": asset["annual_rate_percent"],
                                           "monthly_payment": asset["monthly_payment"]} for asset in base["assets"]]}}


def forecast(store, value: ForecastInput, today=None):
    base = baseline(FinanceTools(store), Assets(store), value.history_months, value.currency, today)
    return project(base, value, today)
