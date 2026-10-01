"""What If scenarios (docs/what-if.md): named plans run through the forecast beside "Now".

A scenario stores its inputs only: planned paychecks (finance/paycheck.py inputs, each with the months it is paid and whether
it replaces pay or adds to it), set category amounts, one-offs and the forecast's assumptions. Running it works every
paycheck out again from the tax tables, turns it into the forecast's pure PayPlan input, and projects it from one of three
bases:
- profile: this person's records (forecast.baseline);
- family: every member's baseline added together, exactly, the same way the family view adds its figures;
- blank: nothing but a starting cash amount; the plan supplies everything.
Nothing about a run is stored, so a scenario always reflects today's records and tables.
"""

from datetime import date
from decimal import Decimal
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..core.money import as_decimal_text, currency_code, money, to_minor
from ..library.storage import now
from .charts import line_chart
from .forecast import MONTH, PERCENT, Assets, ForecastInput, PayPlan, YearlyBonus, baseline, month_add, month_end, project
from .paycheck import CURRENCY, PaycheckInput, calculate
from .paystub import rounded
from .tools import FinanceTools

BASES = {"profile": "Your records", "family": "The family's records", "blank": "A blank slate"}
MAX_COMPARED = 3  # The validated chart palette has three colors: "Now" and two plans, or three plans.


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PaycheckPlan(StrictInput):
    label: str = Field(min_length=1, max_length=60)
    paycheck: PaycheckInput
    from_month: str = Field(pattern=MONTH.pattern)
    to_month: str | None = Field(default=None, pattern=MONTH.pattern)
    mode: Literal["replace_pay", "add"] = "replace_pay"
    retirement_account_id: int | None = None
    hsa_account_id: int | None = None
    contribution_growth_percent: str = Field(default="0", pattern=PERCENT)

    @model_validator(mode="after")
    def ordered(self):
        if self.to_month and self.to_month < self.from_month:
            raise ValueError(f"{self.label}: the last month can't be before the first.")
        return self


class ScenarioInput(StrictInput):
    name: str = Field(min_length=1, max_length=60)
    basis: Literal["profile", "family", "blank"] = "profile"
    starting_cash: str = Field(default="0", max_length=30, description="A blank slate's cash to start with.")
    paychecks: list[PaycheckPlan] = Field(default_factory=list, max_length=10)
    forecast: ForecastInput = Field(default_factory=ForecastInput)

    @model_validator(mode="after")
    def planned_here(self):
        if self.forecast.pay_plans:
            raise ValueError("Add paychecks to a scenario as paychecks, not as worked-out pay plans.")
        return self


class Scenarios:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def view(row):
        inputs = json.loads(row["inputs_json"])
        return {"id": row["id"], "name": row["name"], "basis": row["basis"], "basis_name": BASES[row["basis"]], "inputs": inputs,
                "adopted_at": row["adopted_at"], "adopted_month": row["adopted_month"], "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def list(self):
        with self.store.connection() as db:
            return [self.view(row) for row in db.execute("SELECT * FROM scenarios ORDER BY name COLLATE NOCASE, id")]

    def get(self, scenario_id):
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM scenarios WHERE id=?", (scenario_id,)).fetchone()
        if row is None:
            raise ValueError("Scenario not found.")
        return self.view(row)

    def create(self, value: ScenarioInput):
        with self.store.connection() as db:
            scenario_id = db.execute("INSERT INTO scenarios(name,basis,inputs_json,created_at,updated_at) VALUES(?,?,?,?,?)",
                                     (value.name.strip(), value.basis, value.model_dump_json(), now(), now())).lastrowid
        return self.get(scenario_id)

    def update(self, scenario_id, value: ScenarioInput):
        self.get(scenario_id)
        with self.store.connection() as db:
            db.execute("UPDATE scenarios SET name=?,basis=?,inputs_json=?,updated_at=? WHERE id=?",
                       (value.name.strip(), value.basis, value.model_dump_json(), now(), scenario_id))
        return self.get(scenario_id)

    def duplicate(self, scenario_id):
        original = self.get(scenario_id)
        value = ScenarioInput.model_validate({**original["inputs"], "name": f"{original['name']} (copy)"[:60]})
        return self.create(value)

    def delete(self, scenario_id):
        self.get(scenario_id)
        with self.store.connection() as db:
            db.execute("DELETE FROM scenarios WHERE id=?", (scenario_id,))
        return {"id": scenario_id, "deleted": True}

    def input(self, scenario_id):
        return ScenarioInput.model_validate(self.get(scenario_id)["inputs"])


def empty_baseline(currency, history_months, cash=0, today=None):
    """A blank slate: nothing recorded, only the cash to start with."""
    today = today or date.today()
    first = month_add(today.isoformat()[:7], -history_months)
    last = month_add(today.isoformat()[:7], -1)
    return {"currency": currency, "history": {"start": first + "-01", "end": month_end(last), "months": history_months, "months_with_data": 0},
            "cash": cash, "balances": [], "monthly_pay": Decimal(0), "monthly_income": Decimal(0), "monthly_spending": {}, "bills": [], "assets": [], "pensions": [],
            "notes": ["A blank slate: no records are used; the plan's paychecks, spending and one-offs are everything."]}


def family_baseline(members, history_months, currency=None, today=None):
    """Every member's baseline added together: cash, pay, income and each category's spending summed; balances, bills and
    assets listed with the member's name. Accounts can't be linked across members, so planned contributions go to new
    planned accounts."""
    from .dashboard import choose_currency
    from .family import member_currencies
    chosen = currency_code(currency) if currency else choose_currency(member_currencies([store for _, store in members]))
    combined = empty_baseline(chosen, history_months, today=today)
    combined["notes"] = []
    months_with_data = 0
    for member, store in members:
        base = baseline(FinanceTools(store), Assets(store), history_months, chosen, today)
        name = member["name"]
        combined["history"] = base["history"]
        months_with_data = max(months_with_data, base["history"]["months_with_data"])
        combined["cash"] += base["cash"]
        combined["monthly_pay"] += base["monthly_pay"]
        combined["monthly_income"] += base["monthly_income"]
        for category, amount in base["monthly_spending"].items():
            combined["monthly_spending"][category] = combined["monthly_spending"].get(category, Decimal(0)) + amount
        combined["balances"] += [{**row, "account": f"{name} · {row['account']}"} for row in base["balances"]]
        combined["bills"] += [{**bill, "name": f"{name} · {bill['name']}"} for bill in base["bills"]]
        combined["assets"] += [{**asset, "name": f"{name} · {asset['name']}", "account_id": None} for asset in base["assets"]]
        combined["pensions"] += [{**pension, "label": f"{name} · {pension['label']}"} for pension in base.get("pensions", [])]
        combined["notes"] += [f"{name}: {note}" for note in base["notes"]]
    combined["history"] = {**combined["history"], "months_with_data": months_with_data}
    combined["monthly_spending"] = dict(sorted(combined["monthly_spending"].items()))
    if not members:
        combined["notes"].append("No family member has shared records yet.")
    return combined


def paycheck_plans(value: ScenarioInput, tables_for):
    """Each planned paycheck worked out (tables_for(year, jurisdictions, status) gives the tax tables), and the forecast's
    PayPlan for it: take-home pay a month, and contributions a month (paycheck amount × paychecks a year ÷ 12)."""
    plans, summaries = [], []
    for plan in value.paychecks:
        paycheck = plan.paycheck
        result = calculate(paycheck, tables_for(paycheck.year, ["US", *([paycheck.work_state] if paycheck.work_state else [])], paycheck.filing_status))
        checks = result["paychecks"]
        retirement, hsa = (rounded(Decimal(result["contributions"][key] * checks) / 12) for key in ("retirement_per_check_minor", "hsa_per_check_minor"))
        # Bonuses are paid in their month each year; the monthly take-home pay is the regular paychecks' only.
        bonuses = [YearlyBonus(month_of_year=bonus["month"], net=as_decimal_text(bonus["net_minor"], CURRENCY),
                               retirement=as_decimal_text(bonus["retirement_minor"], CURRENCY), hsa=as_decimal_text(bonus["hsa_minor"], CURRENCY))
                   for bonus in result["bonuses"]]
        plans.append(PayPlan(label=plan.label, from_month=plan.from_month, to_month=plan.to_month, mode=plan.mode, yearly_bonuses=bonuses,
                             monthly_net=as_decimal_text(result["net"]["regular_monthly_minor"], CURRENCY),
                             monthly_retirement=as_decimal_text(retirement, CURRENCY), monthly_hsa=as_decimal_text(hsa, CURRENCY),
                             retirement_account_id=plan.retirement_account_id, hsa_account_id=plan.hsa_account_id,
                             contribution_growth_percent=plan.contribution_growth_percent))
        summaries.append({"label": plan.label, "from_month": plan.from_month, "to_month": plan.to_month, "mode": plan.mode, "complete": result["complete"],
                          "state": result["state"], "state_name": result["state_name"], "frequency_name": result["frequency_name"],
                          "net_per_check": money(result["net"]["per_check_minor"], CURRENCY), "net_monthly": money(result["net"]["monthly_minor"], CURRENCY),
                          "gross_per_check": money(result["groups"][0]["per_check_minor"], CURRENCY),
                          "retirement_monthly": money(retirement, CURRENCY), "hsa_monthly": money(hsa, CURRENCY),
                          "bonuses": [{"label": bonus["label"], "month": bonus["month"], "net": money(bonus["net_minor"], CURRENCY)} for bonus in result["bonuses"]]})
    return plans, summaries


def run(value: ScenarioInput, base, tables_for, today=None, birth_year=None):
    """One scenario's forecast from its base."""
    plans, summaries = paycheck_plans(value, tables_for)
    if plans and base["currency"] != CURRENCY:
        raise ValueError(f"Planned paychecks are in {CURRENCY}; this forecast is in {base['currency']}.")
    result = project(base, value.forecast.model_copy(update={"pay_plans": plans}), today, birth_year)
    for summary in summaries:
        if not summary["complete"]:
            result["notes"].append(f"{summary['label']}: some tax tables are missing, so its take-home pay leaves out those taxes and is too high.")
    return {**result, "paychecks": summaries}


def compare_chart(runs, currency):
    """Net worth at the end of each year, one line per run (at most three, in the validated order)."""
    labels = [row["year"][:4] if len(row["year"]) == 4 else row["year"][-7:-3] for row in runs[0]["result"]["years"]]
    span = f"{labels[0]}–{labels[-1]}" if labels[0] != labels[-1] else labels[0]
    series = [{"name": item["name"][:28], "short": item["name"][:14], "values": [row["end_net_worth"] for row in item["result"]["years"]]} for item in runs]
    return line_chart("Net worth by plan", f"{currency}, end of each year, {span}", labels, series, currency)


def compare(runs):
    """runs: [(name, result)], "Now" first when included. The chart, and each run's years, notes and paychecks."""
    if not runs:
        raise ValueError("Choose at least one plan to compare.")
    if len(runs) > MAX_COMPARED:
        raise ValueError(f"Compare at most {MAX_COMPARED} at a time, counting Now.")
    currencies = {result["currency"] for _, result in runs}
    if len(currencies) > 1:
        raise ValueError(f"These plans are in different currencies ({', '.join(sorted(currencies))}); compare plans in one currency.")
    shaped = [{"name": name, "result": result} for name, result in runs]
    currency = next(iter(currencies))
    return {"currency": currency, "chart": compare_chart(shaped, currency),
            "runs": [{"name": item["name"], "currency": currency, "years": item["result"]["years"], "notes": item["result"]["notes"],
                      "paychecks": item["result"].get("paychecks", []), "first_month_cash_below_zero": item["result"]["first_month_cash_below_zero"],
                      "start_month": item["result"]["start_month"], "starting_cash": item["result"]["starting_point"]["cash"],
                      "tax_zen": item["result"].get("tax_zen")} for item in shaped]}


def starting_cash(value: ScenarioInput, currency):
    return to_minor(value.starting_cash, currency) if value.basis == "blank" else 0
