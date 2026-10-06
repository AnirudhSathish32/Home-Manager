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
from .ledger import normalize_name
from .tools import AsOfInput, FinanceTools, percent_change


class MemberStore:
    """A member's imported copy, opened read-only. Enough of Store for the finance read paths."""
    library_query = Store.library_query
    document_version = Store.document_version  # The family view opens members' originals (Manager.family_original).

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


# The family ledger (docs/family.md "Family ledger"): finance tools run on every member's view copy and merged. -----------

def _tag(rows, member):
    return [{**row, "member_id": member["member_id"], "owner": member["name"]} for row in rows]


def _keyed(rows, key):
    """Rows from several members with the same key added together (money exactly, counts as integers), first-seen order."""
    merged: dict = {}
    for row in rows:
        merged[key(row)] = add(merged.get(key(row)), row)
    return list(merged.values())


def _page(results, rows_key, args, sort):
    """One page of rows merged from members who were each asked for the first offset+limit rows."""
    rows = sorted((row for result in results for row in result[rows_key]), key=sort)
    offset, limit = args.get("offset", 0), args.get("limit", 200)
    return {rows_key: rows[offset:offset + limit], "total_matching": sum(result["total_matching"] for result in results), "offset": offset,
            "limit": limit}


def _transaction_sort(sort, order):
    keys = {"date_desc": lambda row: (_desc(row["posted_date"]), order[row["member_id"]], -row["id"]),
            "date_asc": lambda row: (row["posted_date"], order[row["member_id"]], row["id"]),
            "amount_desc": lambda row: (-row["amount_minor"], order[row["member_id"]], -row["id"]),
            "amount_asc": lambda row: (row["amount_minor"], order[row["member_id"]], row["id"]),
            "description": lambda row: (normalize_name(row["description_raw"] or ""), order[row["member_id"]], row["id"])}
    return keys.get(sort, keys["date_desc"])


def _desc(text):
    """A sort key that orders ISO dates newest first."""
    return tuple(-ord(ch) for ch in text or "")


def _merge_spending(results):
    total = dict(results[0])
    total["by_currency"] = _keyed([row for result in results for row in result["by_currency"]], lambda row: row["currency"])
    for row in total["by_currency"]:
        row["net_spending"] = money(row["net_spending"]["minor"], row["currency"])  # Members' traces don't add up to one.
    total["pending_review"] = _keyed([row for result in results for row in result["pending_review"]], lambda row: row["currency"])
    total["excluded_transfers_and_card_payments"] = sum(result["excluded_transfers_and_card_payments"] for result in results)
    total["coverage"] = [row for result in results for row in result["coverage"]]
    total["usd_total"] = None  # Each member's conversion uses their own rates; the family view shows each currency.
    return total


def _merge_compare(results):
    rows = _keyed([row for result in results for row in result["categories"]], lambda row: (row["currency"], row["category"]))
    for row in rows:
        row["percent_change"] = percent_change(row["first"]["minor"], row["second"]["minor"])
    rows.sort(key=lambda row: (row["currency"], -row["second"]["minor"], row["category"]))
    return {**results[0], "categories": rows}


def _merge_by_category(results):
    categories = _keyed([row for result in results for row in result["categories"]], lambda row: (row["currency"], row["category"]))
    for row in categories:
        row["spending"] = money(row["spending"]["minor"], row["currency"])
    merchants = _keyed([row for result in results for row in result["top_merchants"]], lambda row: (row["currency"], row["merchant"]))
    return {**results[0], "categories": sorted(categories, key=lambda row: (row["currency"], -row["spending"]["minor"])),
            "top_merchants": sorted(merchants, key=lambda row: -row["spending"]["minor"])[:20]}


def _merge_recurring(results):
    totals = _keyed([row for result in results for row in result["totals"]], lambda row: (row["currency"], row["kind"]))
    for row in totals:
        for key in ("monthly", "yearly"):
            row[key] = money(row[key]["minor"], row["currency"])
    obligations = sorted((row for result in results for row in result["obligations"]), key=lambda row: (row["next_due_date"] or "9999", row["merchant"]))
    return {**results[0], "obligations": obligations, "totals": sorted(totals, key=lambda row: (row["currency"], row["kind"]))}


# Tool -> (list keys whose rows are tagged with their owner, merge of the tagged results). Paged tools are asked for
# offset+limit rows each, then sorted and cut together.
FAMILY_TOOLS = {
    "get_accounts": (("accounts",), lambda results, args, order: {"accounts": [row for result in results for row in result["accounts"]]}),
    "get_categories": ((), lambda results, args, order: {"categories": sorted(
        _keyed([row for result in results for row in result["categories"]], lambda row: row["category"]), key=lambda row: row["category"])}),
    "get_transactions": (("transactions",), lambda results, args, order: _page(results, "transactions", args, _transaction_sort(args.get("sort"), order))),
    "get_spending_items": (("items",), lambda results, args, order: {**_page(results, "items", args, lambda row: (
        _desc(row["date"]), order[row["member_id"]], row["source"], -(row["transaction_id"] or 0), -(row["receipt_id"] or 0),
        row["position"] is None, row["position"] or 0)), "notes": results[0]["notes"]}),
    "get_spending": ((), lambda results, args, order: _merge_spending(results)),
    "compare_categories": ((), lambda results, args, order: _merge_compare(results)),
    "get_spending_by_category": ((), lambda results, args, order: _merge_by_category(results)),
    "get_refunds": (("posted_credits", "refund_evidence"), lambda results, args, order: {
        **results[0], **{key: [row for result in results for row in result[key]] for key in ("posted_credits", "refund_evidence")}}),
    "get_upcoming_bills": (("bills",), lambda results, args, order: {
        **results[0], "bills": sorted((row for result in results for row in result["bills"]), key=lambda row: (row["due_date"], row["provider"]))}),
    "get_recurring_obligations": (("obligations",), lambda results, args, order: _merge_recurring(results)),
}


def _waiting(pending):
    """(member id, record type, record id) -> the fields a sent correction is still waiting on (docs/family.md
    "Family corrections"): the view copies already show the new value."""
    found: dict = {}
    for row in pending or []:
        found.setdefault((row["member_id"], row["record_type"], row["record_id"]), []).append(row["field"])
    return found


def family_tool(members, name, arguments=None, pending=None):
    """A finance tool across the family: run on each member's view copy (where a joint account already counts once and
    transfers between members aren't spending), with list rows tagged member_id and owner and totals added exactly.
    arguments may name one member ("member"): then only their copy is asked, as when a member's account is chosen.
    pending: the family's unanswered corrections; transaction rows carry pending_fields for them."""
    result = _family_tool(members, name, arguments)
    waiting = _waiting(pending)
    for row in result.get("transactions", []) + result.get("items", []):
        transaction = row["id"] if name == "get_transactions" else row.get("transaction_id")
        row["pending_fields"] = waiting.get((row["member_id"], "transaction", transaction), []) if transaction else []
    return result


def _family_tool(members, name, arguments=None):
    from .tools import TOOLS
    if name not in FAMILY_TOOLS:
        raise ValueError("This isn't available in the family view. Open the person's own profile.")
    arguments = dict(arguments or {})
    only = arguments.pop("member", None)
    paged = name in ("get_transactions", "get_spending_items")
    model = TOOLS[name][0]
    value = model.model_validate(arguments)
    asked = value.model_copy(update={"offset": 0, "limit": value.offset + value.limit}) if paged else value
    tagged_keys, merge = FAMILY_TOOLS[name]
    chosen = [(member, store) for member, store in members if only in (None, member["member_id"])]
    results, order = [], {member["member_id"]: index for index, (member, _) in enumerate(members)}
    for member, store in chosen:
        result = getattr(FinanceTools(store), TOOLS[name][1])(asked)
        for key in tagged_keys:
            result[key] = _tag(result[key], member)
        if name in ("get_spending", "get_accounts"):
            for row in result.get("coverage", []):
                row["display_name"] = f"{member['name']} · {row['display_name']}"
        results.append(result)
    if not results:
        raise ValueError("Family member not found.")
    return merge(results, value.model_dump(), order)


def family_record(members, member_id, record_type, record_id, pending=None):
    """One record from a member's view copy, for the family ledger's drawer, tagged with its owner and the fields a
    correction is still waiting on."""
    from .ledger import Ledger
    for member, store in members:
        if member["member_id"] == member_id:
            return {**Ledger(store).record(record_type, record_id), "member_id": member_id, "owner": member["name"],
                    "pending_fields": _waiting(pending).get((member_id, record_type, record_id), [])}
    raise ValueError("Family member not found.")


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
