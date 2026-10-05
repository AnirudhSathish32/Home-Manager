"""The family view: each member's dashboard and net worth, added up exactly in minor units per currency.

Members' copies are opened read-only (app/family_sync.py keeps them). Every figure comes from the same
functions an individual profile uses (dashboard.py, tools.py, forecast.py), run once per member; this
module only adds them together, so the family total always equals the sum of its members.
"""

from contextlib import contextmanager
import copy
from datetime import date
import sqlite3

from ..core.money import money
from ..core.trace import figure, ref
from ..library.storage import Store, now
from .dashboard import CURRENCIES_SQL, choose_currency, dashboard, group_categories, periods
from .forecast import Assets, baseline
from .tools import AsOfInput, FinanceTools, percent_change


class MemberStore:
    """A member's imported copy, opened read-only. Enough of Store for the finance read paths."""
    library_query = Store.library_query

    def __init__(self, path):
        self.db_path = path

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.db_path.as_uri() + "?mode=ro", uri=True, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()


def _is_money(value):
    return isinstance(value, dict) and "minor" in value and "currency" in value and "display" in value


def add(first, second):
    """Add two values of the same shape: money exactly, counts as integers, nested objects key by key."""
    if first is None:
        return second
    if second is None:
        return first
    if _is_money(first):
        return money(first["minor"] + second["minor"], first["currency"])
    if isinstance(first, bool):
        return first
    if isinstance(first, int) and isinstance(second, int):
        return first + second
    if isinstance(first, dict):
        return {key: add(first.get(key), second.get(key)) for key in {**first, **second}}
    return first


def member_currencies(stores):
    found = set()
    for store in stores:
        with store.connection() as db:
            found |= {row[0] for row in db.execute(CURRENCIES_SQL)}
    return sorted(found)


def family_dashboard(members, month, months=6, currency=None, home_currency=None, today=None):
    """members: [(member dict, MemberStore)]. The Home dashboard's shape for the whole family, plus a per-member breakdown."""
    today = today or date.today()
    period, before, _ = periods(month, months, today)
    currencies = member_currencies([store for _, store in members])
    chosen = choose_currency(currencies, currency, home_currency)
    total, breakdown, raw_categories, bills, maturities, maturity_count = None, [], {}, [], [], 0
    for member, store in members:
        data = dashboard(store, month, months, chosen, home_currency, today)
        tools = FinanceTools(store)
        for row in tools.get_spending_by_category(period)["categories"]:
            if row["currency"] == chosen:
                item = raw_categories.setdefault(row["category"], {"category": row["category"], "spending": money(0, chosen), "transactions": 0})
                item["spending"] = add(item["spending"], row["spending"])
                item["transactions"] += row["transactions"]
        for bill in tools.get_upcoming_bills(AsOfInput(as_of=today.isoformat(), days=30))["bills"]:
            if bill["currency"] == chosen:
                bills.append({**bill, "member": member["name"]})
        # Each member's three soonest include the family's three soonest.
        maturities += [{**row, "member": member["name"]} for row in data["maturities"]]
        maturity_count += data["maturities_total"]
        mine = {"start": period.start, "end": period.end, "currency": chosen, "member": member["member_id"]}
        own = copy.deepcopy({"totals": data["totals"], "cashflow": data["cashflow"]})  # Their own figures, traced on their copy.
        if own["totals"]:
            own["totals"]["net_spending"]["trace"] = ref("spending.net", **mine)
        if own["cashflow"]:
            own["cashflow"]["net"]["trace"], own["cashflow"]["outflow"]["trace"] = ref("cashflow.net", **mine), ref("spending.net", **mine)
        breakdown.append({"member_id": member["member_id"], "name": member["name"], "as_of": member.get("as_of"), **own, "series": data["series"]})
        for row in data["coverage"]:
            row["display_name"] = f"{member['name']} · {row['display_name']}"
        if total is None:
            total = data
            continue
        for key in ("totals", "cashflow", "pending", "attention"):
            total[key] = add(total[key], data[key])
        total["excluded"] += data["excluded"]
        total["coverage"] += data["coverage"]
        total["series"] = [{**mine, "totals": add(mine["totals"], theirs["totals"])} for mine, theirs in zip(total["series"], data["series"])]
        if total["comparison"] or data["comparison"]:
            combined = add(total["comparison"], data["comparison"])
            combined["percent_change"] = percent_change(combined["first"]["minor"], combined["second"]["minor"])
            total["comparison"] = combined
    if total is None:
        return None
    # Each family figure traces to its members' (finance/traces.py family_sum).
    shown = {"start": period.start, "end": period.end, "currency": chosen}
    for row in raw_categories.values():
        row["spending"] = figure(row["spending"]["minor"], chosen, ref("family.spending.category", category=row["category"], **shown))
    ordered = sorted(raw_categories.values(), key=lambda row: -row["spending"]["minor"])
    total["categories"], gross, total["categories_chartable"] = group_categories(ordered, chosen)
    for row in total["categories"]:
        if row["category"] == "Other":
            row["spending"]["trace"] = ref("family.spending.other", **shown)
    total["gross"] = figure(gross, chosen, ref("family.spending.gross", **shown))
    if total["totals"]:
        total["totals"]["net_spending"] = figure(total["totals"]["net_spending"]["minor"], chosen, ref("family.spending.net", **shown))
    if total["cashflow"]:
        total["cashflow"]["net"] = figure(total["cashflow"]["net"]["minor"], chosen, ref("family.cashflow.net", **shown))
        total["cashflow"]["outflow"] = figure(total["cashflow"]["outflow"]["minor"], chosen, ref("family.spending.net", **shown))
    bills.sort(key=lambda bill: (bill["due_date"], bill["provider"]))
    as_of = today.isoformat()
    total["bills"].update(upcoming=[bill for bill in bills if bill["due_date"] >= as_of][:3],
                          overdue=[bill for bill in bills if bill["due_date"] < as_of][:3], total=len(bills))
    maturities.sort(key=lambda row: (row["date"], row["name"]))
    total.update(loaded_at=now(), currency=chosen, currencies=sorted(set(currencies) | {chosen}), members=breakdown,
                 maturities=maturities[:3], maturities_total=maturity_count)
    return total


def family_net_worth(members, currency=None, history_months=3, today=None):
    """Today's cash, assets, loans and net worth per member in one currency, and their sum."""
    rows, chosen = [], currency
    if not chosen:
        chosen = choose_currency(member_currencies([store for _, store in members]))
    for member, store in members:
        base = baseline(FinanceTools(store), Assets(store), history_months, chosen, today)
        assets = sum(asset["value_minor"] for asset in base["assets"] if asset["kind"] != "loan")
        loans = sum(asset["value_minor"] for asset in base["assets"] if asset["kind"] == "loan")
        rows.append({"member_id": member["member_id"], "name": member["name"], "cash": base["cash"], "assets": assets, "loans": loans,
                     "net_worth": base["cash"] + assets - loans, "notes": base["notes"]})
    # Each member's figure traces on their copy (worth.today with member); the family's adds them up.
    worth = lambda key, **more: ref("worth.today", figure=key, currency=chosen, history_months=history_months, **more)
    view = lambda row: {**row, **{key: figure(row[key], chosen, worth(key, member=row["member_id"])) for key in ("cash", "assets", "loans", "net_worth")}}
    total = {key: sum(row[key] for row in rows) for key in ("cash", "assets", "loans", "net_worth")}
    return {"currency": chosen, "members": [view(row) for row in rows],
            "total": {key: figure(value, chosen, "family." + worth(key)) for key, value in total.items()},
            "notes": ["Cash is each account's latest statement balance (card balances count as owed). Assets and loans are the ones "
                      "each member verified. A joint account is counted once."]}
