"""A consistent, read-only household dashboard snapshot. All money math stays here."""
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_EVEN

from .finance import COUNTABLE
from .finance_tools import FinanceTools, PeriodInput, CompareInput, AsOfInput, month_index, month_label, last_day, scope_of, totals_view
from .money import money, currency_code
from .paths import path_key
from .storage import now, WORK_FILTERS


class SnapshotStore:
    def __init__(self, store, db):
        self.store, self.db = store, db

    @contextmanager
    def connection(self):
        yield self.db

    def __getattr__(self, name):
        return getattr(self.store, name)


def dashboard(store, source, month, months=6, currency=None, home_currency=None, today=None):
    today = today or date.today()
    if months not in (6, 12):
        raise ValueError("Choose a six- or twelve-month trend.")
    current = today.isoformat()[:7]
    index = month_index(month)
    if month > current or index < months - 1:
        raise ValueError("Choose a month no later than the current month.")
    end = min(last_day(index), today.isoformat())
    period = PeriodInput(start=month + "-01", end=end)
    previous = month_label(index - 1)
    previous_end = last_day(index - 1)
    if month == current:
        previous_end = previous + f'-{min(today.day, int(previous_end[-2:])):02d}'
    before = PeriodInput(start=previous + "-01", end=previous_end)
    with store.connection() as db:
        db.execute("BEGIN")
        tools = FinanceTools(SnapshotStore(store, db))
        currencies = sorted({row[0] for row in db.execute("SELECT currency FROM transactions UNION SELECT currency FROM receipts UNION SELECT currency FROM bills")})
        chosen = currency_code(currency) if currency else home_currency if home_currency in currencies else "USD" if "USD" in currencies or not currencies else currencies[0]
        currencies = sorted(set(currencies) | {chosen})
        pick = lambda rows: next((row for row in rows if row["currency"] == chosen), None)
        spending = tools.get_spending(period)
        totals = pick(spending["by_currency"])
        flow = pick(tools.calculate_cashflow(period)["by_currency"])
        comparison = pick(tools.compare_periods(CompareInput(first=before, second=period))["by_currency"])
        series = []
        trend_scope, trend_params = scope_of(month_label(index - months + 1) + "-01", end, None)
        trend_totals = tools._totals(trend_scope, trend_params, by_month=True)
        for item in range(index - months + 1, index + 1):
            label = month_label(item)
            stop = min(last_day(item), today.isoformat())
            bucket = totals_view(chosen, trend_totals[(label, chosen)]) if (label, chosen) in trend_totals else None
            series.append({"month": label, "start": label + "-01", "end": stop,
                           "partial": label == current and stop != last_day(item), "totals": bucket})
        categories = [row for row in tools.get_spending_by_category(period)["categories"] if row["currency"] == chosen]
        named = [row for row in categories if row["category"] != "uncategorized"]
        groups = [{**row, "members": [row["category"]]} for row in named[:5]]
        if len(named) > 5:
            rest = named[5:]
            groups.append({"category": "Other", "spending": money(sum(row["spending"]["minor"] for row in rest), chosen),
                           "transactions": sum(row["transactions"] for row in rest), "members": [row["category"] for row in rest]})
        groups += [{**row, "members": ["uncategorized"]} for row in categories if row["category"] == "uncategorized"]
        gross = sum(row["spending"]["minor"] for row in categories)
        for row in groups:
            row["share"] = str((Decimal(row["spending"]["minor"]) * 100 / gross).quantize(Decimal("0.1"), ROUND_HALF_EVEN)) if gross > 0 else "0.0"
        unmatched = tools.get_unmatched_receipts(period)
        unmatched_total = pick(unmatched["by_currency"])
        queue = tools.review_queue()
        ready = db.execute(store.library_query() + "SELECT count(*) FROM library WHERE source_root IN (?,?) AND deleted_at IS NULL "
                           f"AND {WORK_FILTERS['ready_for_ledger']}",
                           (path_key(source), path_key(store.library.inbox))).fetchone()[0]
        bill_result = tools.get_upcoming_bills(AsOfInput(as_of=today.isoformat(), days=30))
        bills = [row for row in bill_result["bills"] if row["currency"] == chosen and row["payment_state"] not in ("paid", "payment_found")]
        coverage = [dict(row) for row in db.execute(f"SELECT a.display_name,min(t.posted_date) AS first,max(t.posted_date) AS last,count(*) AS transactions "
                     f"FROM transactions t JOIN accounts a ON a.id=t.account_id WHERE {COUNTABLE} AND t.currency=? AND t.posted_date BETWEEN ? AND ? GROUP BY a.id",
                     (chosen, period.start, period.end))]
        return {"loaded_at": now(), "month": month, "period": period.model_dump(), "previous_period": before.model_dump(),
                "currency": chosen, "currencies": currencies, "totals": totals, "cashflow": flow, "comparison": comparison,
                "series": series, "categories": groups, "gross": money(gross, chosen), "coverage": coverage,
                "pending": pick(spending["pending_review"]), "excluded": spending["excluded_transfers_and_card_payments"],
                "attention": {"unmatched": unmatched_total, "undated": sum(row["currency"] == chosen for row in unmatched["undated"]),
                              "records": len(queue["records"]), "links": len(queue["links"]), "issues": len(queue["issues"]), "ready": ready},
                "bills": {"as_of": today.isoformat(), "until": (today + timedelta(days=30)).isoformat(),
                          "upcoming": [row for row in bills if row["due_date"] >= today.isoformat()][:3],
                          "overdue": [row for row in bills if row["due_date"] < today.isoformat()][:3], "total": len(bills)}}
