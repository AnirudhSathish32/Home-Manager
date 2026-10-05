"""Wealth figures' traces (docs/ui.md "Trace contract"; finance/traces.py has the ledger's): investment values, holdings
worked out from their terms (CDs, Treasuries, I bonds), gains by tax lot, required minimum distributions and the
forecast's months. Each builder re-runs the calculation behind the figure with a live Recorder.
"""

from datetime import date

from ..core.money import format_minor
from ..core.trace import Recorder, build, ref
from . import rules
from .forecast import ForecastInput, forecast
from .investments import Investments, accrued, ibond_value
from .provenance import light
from .retirement import divisor, required
from .tax_lots import account_lots


def _id(params, key):
    try:
        return int(params[key])
    except (KeyError, ValueError):
        raise ValueError(f"The trace needs {key} as a number.") from None


def _account(investments, db, account_id):
    found = investments.rows(db, True, account_id)
    if not found:
        raise ValueError("Investment account not found.")
    return found[0]


def record_value(investments, db, account, recorder):
    """An account's current value: a statement's or a value you typed as it is, a market-price value as its holdings' units
    times their prices, or an estimate as each CD, Treasury or I bond's value from its terms."""
    current, currency = account["current"], account["currency"]
    if current["source"] == "estimated":
        for holding in investments.term_holdings(db, account["id"]):
            if holding["counts"] and not holding["matured"]:
                recorder.add(holding["name"], holding["value_on"](investments.today), currency, trace=ref("investments.holding", holding_id=holding["id"]))
        return "Worked out for today from each CD, Treasury or I bond's terms: what it was worth, plus what it has earned since."
    if current["source"] == "quote":
        for row in db.execute("SELECT v.*,h.name FROM investment_valuations v JOIN holdings h ON h.id=v.holding_id WHERE v.account_id=? AND v.as_of=? "
                              "AND v.source='quote' ORDER BY h.name", (account["id"], current["as_of"])):
            price = f" × {format_minor(row['price_minor'], currency)}" if row["price_minor"] is not None else " (its statement value)"
            recorder.add(f"{row['name']}: {row['quantity'] or ''}{price}", row["value_minor"], currency)
            recorder.input(f"investment_valuation:{row['id']}", f"{row['name']} on {row['as_of']}", row["value_minor"], currency,
                           light("investment_valuation", row["id"], kind="rate" if row["price_minor"] is not None else "extracted"))
        return "Each holding's units now times the day's market price; cash and money market funds at their statement value."
    record_type, record_id = ("statement", current["statement_id"]) if current["source"] == "ledger_statement" else ("investment_valuation", current["id"])
    label = {"manual": "The value you entered", "ledger_statement": "The linked savings account's statement balance"}.get(current["source"], "The statement's value")
    recorder.add(f"{label}, as of {current['as_of']}", current["value_minor"], currency)
    recorder.input(f"{record_type}:{record_id}", f"{label} · {current['as_of']}", current["value_minor"], currency,
                   light(record_type, record_id, kind="manual" if current["source"] == "manual" else "extracted"),
                   "confirmed" if current["source"] == "manual" or current.get("review_source") != "automatic" else "checked_automatically")
    return "The newest confirmed value, as of its date."


def investment_value(store, ref_text, params):
    investments = Investments(store)
    with store.connection() as db:
        account = _account(investments, db, _id(params, "account_id"))
        if account["current"] is None:
            raise ValueError("This account has no confirmed value yet.")
        recorder = Recorder()
        formula = record_value(investments, db, account, recorder)
    return build(ref_text, f"{account['name']}, as of {account['current']['as_of']}", account["current"]["value_minor"], account["currency"], formula, recorder)


def investment_total(store, ref_text, params):
    """The investments' total in one currency (Investments.summary): every open account's current value; pensions pay an
    income instead and aren't counted."""
    currency, investments = params.get("currency", ""), Investments(store)
    recorder, total = Recorder(), 0
    with store.connection() as db:
        for account in investments.rows(db):
            if account["current"] is None or account["is_income"] or account["currency"] != currency:
                continue
            recorder.add(account["name"], account["current"]["value_minor"], currency, trace=ref("investments.value", account_id=account["id"]))
            total += account["current"]["value_minor"]
    return build(ref_text, f"Investments in {currency}", total, currency,
                 "Every open account's newest confirmed value, added up. A pension pays an income, so it isn't a balance here.", recorder)


def holding_value(store, ref_text, params):
    """A CD, Treasury or I bond's value today, from its terms (accrued, ibond_value)."""
    investments, holding_id = Investments(store), _id(params, "holding_id")
    with store.connection() as db:
        account_id = investments.holding(db, holding_id)["account_id"]
        currency = _account(investments, db, account_id)["currency"]
        holding = next((item for item in investments.term_holdings(db, account_id) if item["id"] == holding_id), None)
        rates = investments.ibond_rates(db)
    if holding is None:
        raise ValueError("This holding isn't worked out from its terms.")
    recorder, today = Recorder(), investments.today
    if investments.ibond_terms(holding, rates):
        value = ibond_value(holding["principal_minor"], holding["issue_date"], today, rates, recorder=recorder, currency=currency)
        formula = ("An I bond earns the published composite rate (its fixed rate plus inflation), a month at a time, resetting every six months "
                   "from its issue month; worked out as TreasuryDirect does.")
    else:
        value = accrued(holding["base_minor"], holding["since"], today, holding["rate_bp"], holding["face_minor"], holding["maturity_date"], recorder, currency)
        formula = "Its value then, plus what it has earned since: at its yearly rate, or rising evenly to its face value at maturity."
    return build(ref_text, f"{holding['name']}, today", value, currency, formula, recorder)


def lot_gain(store, ref_text, params):
    """A holding's gain by its open tax lots: its statement value less what the lots cost (Investments.with_lots)."""
    investments, holding_id = Investments(store), _id(params, "holding_id")
    with store.connection() as db:
        holding = investments.holding(db, holding_id)
        found = account_lots(db, holding["account_id"]).get(holding_id)
        account = _account(investments, db, holding["account_id"])
        holdings, _ = investments.holdings(db, holding["account_id"], account["currency"])
    view = next((item for item in holdings if item["id"] == holding_id), None)
    if not found or view is None:
        raise ValueError("This holding has no open tax lots.")
    currency, recorder = account["currency"], Recorder()
    recorder.add(f"Its value on the statement of {account['current']['as_of'] if account['current'] else 'its date'}", view["value_minor"], currency)
    for number, lot in enumerate(found["lots"], 1):
        recorder.add(f"Lot bought {lot['acquired_date']}: {lot['shares']} shares (what they cost)", -lot["cost_minor"], currency)
        recorder.input(f"tax_lot:{lot['id']}" if lot["id"] else f"lot:{number}", f"Lot bought {lot['acquired_date']}", lot["cost_minor"], currency,
                       {"kind": "manual" if lot["source"] == "manual" else "extracted", "record": {"type": "tax_lot", "id": lot["id"]} if lot["id"] else None})
    return build(ref_text, f"{holding['name']}: gain on open lots", view["value_minor"] - found["open_cost_minor"], currency,
                 "The holding's value less what its open lots cost.", recorder)


def rmd(store, ref_text, params, context, which):
    """A year's required minimum distribution from one account, or what's left of it (Investments.required_distributions)."""
    investments, account_id, year = Investments(store), _id(params, "account_id"), _id(params, "year")
    birth_year = context.household.birth_year
    if birth_year is None:
        raise ValueError("Add the year you were born in Settings.")
    with store.connection() as db:
        account = _account(investments, db, account_id)
        balance, taken = investments.rmd_basis(db, account, year)
    if balance is None:
        raise ValueError("There's no confirmed balance for the end of last year.")
    currency, recorder = account["currency"], Recorder()
    amount = required(balance["value_minor"], birth_year, year)
    if which == "left":
        recorder.add("Required this year", amount, currency, trace=ref("investments.rmd", account_id=account_id, year=year))
        recorder.add("Taken so far this year", -taken, currency)
        if taken > amount:
            recorder.add("Nothing more once it's all taken", taken - amount, currency)
        return build(ref_text, f"{account['name']}: still to take in {year}", max(amount - taken, 0), currency,
                     "The year's required distribution less the confirmed withdrawals already taken this year.", recorder)
    age = year - birth_year
    recorder.add(f"The {balance['as_of']} balance, {format_minor(balance['value_minor'], currency)}, ÷ {divisor(age)} (age {age})", amount, currency)
    recorder.input(f"investment_valuation:{balance['id']}" if balance.get("id") else f"statement:{balance.get('statement_id')}",
                   f"Balance on {balance['as_of']}", balance["value_minor"], currency,
                   light("investment_valuation", balance["id"]) if balance.get("id") else light("statement", balance.get("statement_id")))
    recorder.rule(rules.rule("rmd_uniform_lifetime"))
    return build(ref_text, f"{account['name']}: required in {year}", amount, currency,
                 "The balance at the end of last year divided by the Uniform Lifetime Table's period for the age reached this year, rounded half to even.",
                 recorder)


def forecast_month(store, ref_text, params, context, figure):
    """One projected month's cash or net worth (forecast.project), from the forecast's own input as it was run: the
    Forecast page's (input) or a What If plan's (scenario, scenarios.run)."""
    from .scenarios import ScenarioInput, run
    month, recorder = params.get("month", ""), Recorder()
    try:
        today = date.fromisoformat(params["today"])
        if params.get("scenario"):
            plan = ScenarioInput.model_validate_json(params["scenario"])
        else:
            value = ForecastInput.model_validate_json(params.get("input") or "{}")
    except (KeyError, ValueError):
        raise ValueError("The trace needs the forecast's input and the day it was worked out.") from None
    if params.get("scenario"):
        cash_ref = lambda shown: ref("forecast.cash", scenario=params["scenario"], today=params["today"], month=shown)
        if context.family:
            with context.family.mutex:
                base, tables_for = context.scenario_base(plan), context.scenario_tables()
        else:
            base, tables_for = context.scenario_base(plan), context.scenario_tables()
        result = run(plan, base, tables_for, today, context.household.birth_year, recorder, (figure, month, cash_ref))
    else:
        result = forecast(store, value, today, context.household.birth_year, recorder,
                          (figure, month, lambda shown: ref("forecast.cash", input=params.get("input"), today=params["today"], month=shown)))
    row = next((item for item in result["months"] if item["month"] == month), None)
    if row is None:
        raise ValueError("That month isn't in this forecast.")
    if figure == "cash":
        return build(ref_text, f"Cash at the end of {month}", row["cash"], result["currency"],
                     "The month before's cash, plus the month's income, less its spending (recent averages and bills, grown with prices), loan "
                     "payments and savings, with one-offs, maturities, withdrawals, pensions and education costs.", recorder)
    return build(ref_text, f"Net worth at the end of {month}", row["net_worth"], result["currency"],
                 "Cash, plus every account and asset as projected, less what's owed on loans.", recorder)


def worth_today(store, ref_text, params):
    """Today's cash, assets, loans or net worth in one currency (forecast.baseline, as the family net worth adds it up):
    cash is each account's latest statement balance (a card's counts as owed), assets and loans the verified ones."""
    from .forecast import Assets, baseline
    from .tools import FinanceTools
    which, currency = params.get("figure", "net_worth"), params.get("currency") or None
    try:
        history = int(params.get("history_months", 3))
    except ValueError:
        raise ValueError("The trace needs history_months as a number.") from None
    base = baseline(FinanceTools(store), Assets(store), history, currency)
    currency, recorder = base["currency"], Recorder()
    figure_ref = lambda name: ref("worth.today", figure=name, currency=currency, history_months=history, member=params.get("member"))
    cash = sum(row["amount"]["minor"] for row in base["balances"])
    assets = [asset for asset in base["assets"] if asset["kind"] != "loan"]
    loans = [asset for asset in base["assets"] if asset["kind"] == "loan"]
    totals = {"cash": cash, "assets": sum(asset["value_minor"] for asset in assets), "loans": sum(asset["value_minor"] for asset in loans)}
    totals["net_worth"] = totals["cash"] + totals["assets"] - totals["loans"]
    if which not in totals:
        raise ValueError("Choose cash, assets, loans or net_worth.")
    if which == "cash":
        for row in base["balances"]:
            recorder.add(f"{row['account']} · {row['as_of']}", row["amount"]["minor"], currency,
                         trace=ref("account.balance", account_id=row["account_id"], member=params.get("member")))
    elif which in ("assets", "loans"):
        for asset in assets if which == "assets" else loans:
            shown = ref("investments.value", account_id=asset["account_id"], member=params.get("member")) if asset.get("source") == "investment" and asset.get("account_id") else None
            recorder.add(asset["name"], asset["value_minor"], currency, trace=shown)
    else:
        recorder.add("Cash", totals["cash"], currency, trace=figure_ref("cash"))
        recorder.add("Assets", totals["assets"], currency, trace=figure_ref("assets"))
        recorder.add("Loans", -totals["loans"], currency, trace=figure_ref("loans"))
    labels = {"cash": "Cash", "assets": "Assets", "loans": "Loans", "net_worth": "Net worth"}
    return build(ref_text, f"{labels[which]} today", totals[which], currency,
                 "Cash is each account's latest statement balance (a card's balance counts as owed); assets and loans are the confirmed ones."
                 if which != "net_worth" else "Cash plus assets, less loans.", recorder)


TRACES = {"worth.today": worth_today, "investments.value": investment_value, "investments.total": investment_total, "investments.holding": holding_value,
          "investments.lot_gain": lot_gain}
CONTEXT_TRACES = {
    "investments.rmd": lambda store, text, params, context: rmd(store, text, params, context, "required"),
    "investments.rmd_left": lambda store, text, params, context: rmd(store, text, params, context, "left"),
    "forecast.cash": lambda store, text, params, context: forecast_month(store, text, params, context, "cash"),
    "forecast.net_worth": lambda store, text, params, context: forecast_month(store, text, params, context, "net_worth"),
}
