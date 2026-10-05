"""A consistent, read-only household dashboard snapshot. All money math stays here."""
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from ..core.money import currency_code
from ..core.trace import NULL, figure, ref
from ..library.storage import WORK_FILTERS, now
from .investments import Investments
from .ledger import COUNTABLE
from .splits import rounded, share
from .tools import AsOfInput, CompareInput, FinanceTools, PeriodInput, last_day, month_index, month_label, totals_view


class SnapshotStore:
    def __init__(self, store, db):
        self.store, self.db = store, db

    @contextmanager
    def connection(self):
        yield self.db

    def __getattr__(self, name):
        return getattr(self.store, name)


CURRENCIES_SQL = "SELECT currency FROM transactions UNION SELECT currency FROM receipts UNION SELECT currency FROM recurring_obligations WHERE status='verified'"


def choose_currency(currencies, currency=None, home_currency=None):
    return currency_code(currency) if currency else home_currency if home_currency in currencies else "USD" if "USD" in currencies or not currencies else currencies[0]


def periods(month, months, today):
    """The selected month (to today when it is the current month), the same span of the month before, and its index."""
    if months not in (6, 12):
        raise ValueError("Choose a six- or twelve-month trend.")
    current = today.isoformat()[:7]
    index = month_index(month)
    if month > current or index < months - 1:
        raise ValueError("Choose a month no later than the current month.")
    end = min(last_day(index), today.isoformat())
    previous = month_label(index - 1)
    previous_end = last_day(index - 1)
    if month == current:
        previous_end = previous + f'-{min(today.day, int(previous_end[-2:])):02d}'
    return PeriodInput(start=month + "-01", end=end), PeriodInput(start=previous + "-01", end=previous_end), index


def group_categories(categories, chosen, period=None, recorder=NULL, only=None):
    """The five largest named categories, the rest as Other, then uncategorized; each with its share of gross spending:
    `share_bp` (whole basis points summing to exactly 10,000, largest remainders first, so the donut closes) and `share`
    (its percent text, which labels the same slice). The donut is drawn only when every group is spending (chartable).
    period: the PeriodInput the categories are for, which gives Other its trace; a live recorder gets the categories
    in Other (only="other") or in gross spending (only="gross"), each with its own trace (finance/traces.py)."""
    named = [row for row in categories if row["category"] != "uncategorized"]
    groups = [{**row, "members": [row["category"]]} for row in named[:5]]
    shown = {"start": period.start, "end": period.end, "currency": chosen} if period else None
    if len(named) > 5:
        rest = named[5:]
        groups.append({"category": "Other", "transactions": sum(row["transactions"] for row in rest), "members": [row["category"] for row in rest],
                       "spending": figure(sum(row["spending"]["minor"] for row in rest), chosen, ref("spending.other", **shown) if shown else None)})
    groups += [{**row, "members": ["uncategorized"]} for row in categories if row["category"] == "uncategorized"]
    gross = sum(row["spending"]["minor"] for row in categories)
    for row in named[5:] if only == "other" else categories if only == "gross" else []:
        recorder.add(row["category"].capitalize(), row["spending"]["minor"], chosen, trace=row["spending"].get("trace"), count=row["transactions"])
    chartable = gross > 0 and all(row["spending"]["minor"] >= 0 for row in groups)
    points = rounded(share(10000, [row["spending"]["minor"] for row in groups]), 10000) if chartable else [0] * len(groups)
    for row, bp in zip(groups, points):
        row["share_bp"] = bp
        row["share"] = str((Decimal(bp) / 100).quantize(Decimal("0.1"), ROUND_HALF_EVEN))
    return groups, gross, chartable


def dashboard(store, month, months=6, currency=None, home_currency=None, today=None):
    today = today or date.today()
    current = today.isoformat()[:7]
    period, before, index = periods(month, months, today)
    end = period.end
    with store.connection() as db:
        db.execute("BEGIN")
        tools = FinanceTools(SnapshotStore(store, db))
        currencies = sorted({row[0] for row in db.execute(CURRENCIES_SQL)})
        chosen = choose_currency(currencies, currency, home_currency)
        currencies = sorted(set(currencies) | {chosen})
        pick = lambda rows: next((row for row in rows if row["currency"] == chosen), None)
        spending = tools.get_spending(period)
        totals = pick(spending["by_currency"])
        flow = pick(tools.calculate_cashflow(period)["by_currency"])
        comparison = pick(tools.compare_periods(CompareInput(first=before, second=period))["by_currency"])
        series = []
        trend_totals = tools._totals(month_label(index - months + 1) + "-01", end, None, by_month=True)
        for item in range(index - months + 1, index + 1):
            label = month_label(item)
            stop = min(last_day(item), today.isoformat())
            bucket = totals_view(chosen, trend_totals[(label, chosen)]) if (label, chosen) in trend_totals else None
            series.append({"month": label, "start": label + "-01", "end": stop,
                           "partial": label == current and stop != last_day(item), "totals": bucket})
        groups, gross, chartable = group_categories([row for row in tools.get_spending_by_category(period)["categories"] if row["currency"] == chosen], chosen, period)
        unmatched = tools.get_unmatched_receipts(period)
        unmatched_total = pick(unmatched["by_currency"])
        queue = tools.review_queue()
        ready = db.execute(store.library_query() + f"SELECT count(*) FROM library WHERE deleted_at IS NULL AND {WORK_FILTERS['ready_for_ledger']}").fetchone()[0]
        bill_result = tools.get_upcoming_bills(AsOfInput(as_of=today.isoformat(), days=30))
        bills = [row for row in bill_result["bills"] if row["currency"] == chosen]
        # CDs and Treasuries coming due, or matured and waiting for an answer (docs/planning.md "Purchase confirmations, estimates and maturities").
        maturities = Investments(SnapshotStore(store, db), today).maturities(currency=chosen)
        coverage = [dict(row) for row in db.execute(f"SELECT a.display_name,min(t.posted_date) AS first,max(t.posted_date) AS last,count(*) AS transactions "
                     f"FROM transactions t JOIN accounts a ON a.id=t.account_id WHERE {COUNTABLE} AND t.currency=? AND t.posted_date BETWEEN ? AND ? GROUP BY a.id",
                     (chosen, period.start, period.end))]
        found = {"loaded_at": now(), "month": month, "period": period.model_dump(), "previous_period": before.model_dump(),
                "currency": chosen, "currencies": currencies, "totals": totals, "cashflow": flow, "comparison": comparison,
                "series": series, "categories": groups, "categories_chartable": chartable, "coverage": coverage,
                "gross": figure(gross, chosen, ref("spending.gross", start=period.start, end=period.end, currency=chosen)),
                "pending": pick(spending["pending_review"]), "excluded": spending["excluded_transfers_and_card_payments"],
                "attention": {"unmatched": unmatched_total, "undated": sum(row["currency"] == chosen for row in unmatched["undated"]),
                              "records": len(queue["records"]), "links": len(queue["links"]), "issues": len(queue["issues"]), "ready": ready},
                "bills": {"as_of": today.isoformat(), "until": (today + timedelta(days=30)).isoformat(),
                          "upcoming": [row for row in bills if row["due_date"] >= today.isoformat()][:3],
                          "overdue": [row for row in bills if row["due_date"] < today.isoformat()][:3], "total": len(bills)},
                "maturities": maturities[:3], "maturities_total": len(maturities)}
    return found


def figures(found):
    """The traceable figures Home shows (finance/traces.py shown)."""
    return ([found["totals"]["net_spending"]] if found.get("totals") else []) + ([found["cashflow"]["net"]] if found.get("cashflow") else [])
