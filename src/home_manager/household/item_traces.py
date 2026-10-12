"""Item insights' traces (docs/household.md "Item analysis"; docs/ui.md "Trace contract"), and the Inventory page's
Item insights view (`GET /api/inventory/insights`).

Each builder re-runs the item-analysis tool behind the figure (household/analysis.py) with a live Recorder: one step per
product, plus, for the rates, each product's cost, days and lots as inputs and the half-even rounding.
"""

from datetime import date

from ..core.money import currency_code
from ..core.trace import Recorder, build, figure, ref
from ..finance.dashboard import choose_currency
from ..finance.tools import FinanceTools
from .analysis import ItemPeriod, MonthInput, OptionalItemQuery


def _day(params, key):
    try:
        return date.fromisoformat(params.get(key, "")).isoformat()
    except ValueError:
        raise ValueError(f"The trace needs {key} as a date (YYYY-MM-DD).") from None


def _currency(params):
    if not params.get("currency"):
        raise ValueError("The trace needs a currency.")
    return currency_code(params["currency"])


def _month(params):
    text = params.get("month", "")
    try:
        date.fromisoformat(text + "-01")
    except ValueError:
        raise ValueError("The trace needs month as YYYY-MM.") from None
    return text


def _total(rows, key, currency):
    return next((row[key]["minor"] for row in rows if row["currency"] == currency), 0)


def items_spending(store, ref_text, params):
    start, end, currency = _day(params, "start"), _day(params, "end"), _currency(params)
    recorder = Recorder()
    found = FinanceTools(store).get_item_spending(ItemPeriod(start=start, end=end), recorder)
    return build(ref_text, f"Spent on items, {start} to {end}", _total(found["by_currency"], "spent", currency), currency,
                 "What approved receipt items cost in the period: each product's lines added up, as printed, before separate discounts.",
                 recorder.only(currency))


def items_waste(store, ref_text, params):
    start, end, currency = _day(params, "start"), _day(params, "end"), _currency(params)
    recorder = Recorder()
    found = FinanceTools(store).get_waste(ItemPeriod(start=start, end=end), recorder)
    return build(ref_text, f"Thrown out, {start} to {end}", _total(found["by_currency"], "wasted", currency), currency,
                 "Items you marked thrown out in the period, at what they cost.", recorder.only(currency))


def items_per_30_days(store, ref_text, params):
    currency = _currency(params)
    recorder = Recorder()
    found = FinanceTools(store).get_consumption_cost(OptionalItemQuery(), recorder)
    return build(ref_text, "Cost per 30 days", _total(found["per_30_days_by_currency"], "amount", currency), currency,
                 "Each finished product's cost divided by the days it lasted, times 30, added up.", recorder.only(currency))


def items_forecast(store, ref_text, params):
    month, currency = _month(params), _currency(params)
    recorder = Recorder()
    found = FinanceTools(store).forecast_consumables_spend(MonthInput(month=month), recorder)
    return build(ref_text, f"Consumables, {month}", _total(found["by_currency"], "projected", currency), currency,
                 "Each product's rate times the month's days; products with under two finished lots are left out.", recorder.only(currency))


TRACES = {"items.spending": items_spending, "items.waste": items_waste, "items.per_30_days": items_per_30_days, "items.forecast": items_forecast}


def next_month(today):
    return f"{today.year + today.month // 12}-{today.month % 12 + 1:02d}"


def insights(store, start, end, currency, today, home_currency=None):
    """The Item insights tab: four traced figures for one currency, and the rows behind them. Figures are shown through
    finance/traces.py shown(), which the caller runs. Without a currency: the home currency if items cost in it, as Home
    chooses (finance/dashboard.py choose_currency)."""
    tools, period = FinanceTools(store), ItemPeriod(start=start, end=end)
    spending, waste = tools.get_item_spending(period), tools.get_waste(period)
    consumption, month = tools.get_consumption_cost(OptionalItemQuery()), next_month(today)
    currencies = sorted({row["currency"] for row in spending["by_currency"] + consumption["per_30_days_by_currency"]})
    currency = choose_currency(currencies, currency, home_currency)
    forecast = tools.forecast_consumables_spend(MonthInput(month=month))
    changes = tools.get_price_changes(period)
    mine = [row for row in consumption["products"] if row["currency"] == currency]
    figures = {
        "spending": figure(_total(spending["by_currency"], "spent", currency), currency, ref("items.spending", start=start, end=end, currency=currency)),
        "waste": figure(_total(waste["by_currency"], "wasted", currency), currency, ref("items.waste", start=start, end=end, currency=currency)),
        "per_30_days": figure(_total(consumption["per_30_days_by_currency"], "amount", currency), currency, ref("items.per_30_days", currency=currency)),
        "forecast": figure(_total(forecast["by_currency"], "projected", currency), currency, ref("items.forecast", month=month, currency=currency)),
    }
    # The tools' notes for people, not the ones that explain a field to the assistant (approximate, package_size_changed).
    notes = [spending["notes"][0], consumption["notes"][0], *forecast["notes"], changes["notes"][0]]
    if any(row["approximate"] for row in mine):
        notes.append("~ approximate: fewer than three finished items back that product's cost per day.")
    return {"period": {"start": start, "end": end}, "currency": currency, "month": month, "figures": figures,
            "counts": {"purchases": next((row["purchases"] for row in spending["by_currency"] if row["currency"] == currency), 0),
                       "thrown_out": sum(1 for row in waste["items"] if row["cost"]["currency"] == currency),
                       "finished_products": len(mine)},
            "top_products": [{"product": row["product"], "spent": row["spent"], "purchases": row["purchases"]}
                             for row in spending["top_products"] if row["currency"] == currency],
            "increases": [{**row, "change_percent": f"{row['percent_change']}%" if row["percent_change"] is not None else None}
                          for row in changes["increases"] if row["currency"] == currency],
            "waste_items": [row for row in waste["items"] if row["cost"]["currency"] == currency],
            "consumption": [{"product": row["product"], "per_30_days": row["per_30_days"], "approximate": row["approximate"]} for row in mine],
            "notes": notes}
