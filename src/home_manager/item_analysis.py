"""Item-level analysis tools for the assistant (docs/items-assets-search.md §4, household-items H4).

Read-only, over inventory lots the user approved, plus counted transactions for anomalies. Exact
Decimal arithmetic; amounts are rounded half-even to the minor unit only for display. Every result
is per currency and says what it could not include. The assistant restates these figures.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
import re

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .finance import COUNTABLE, SPENDING, normalize_name
from .items import normalize_text
from .money import EXPONENTS, money

SPENDING_TYPES = ",".join(f"'{kind}'" for kind in SPENDING)
# Unit -> (dimension, base units per unit). Bare "oz" is weight; "fl oz" is volume.
UNITS = {"fl oz": ("volume", Decimal("29.5735295625")), "floz": ("volume", Decimal("29.5735295625")), "oz": ("mass", Decimal("28.349523125")),
         "lb": ("mass", Decimal("453.59237")), "lbs": ("mass", Decimal("453.59237")), "g": ("mass", Decimal(1)), "kg": ("mass", Decimal(1000)),
         "ml": ("volume", Decimal(1)), "l": ("volume", Decimal(1000)), "ltr": ("volume", Decimal(1000)), "qt": ("volume", Decimal("946.352946")),
         "pt": ("volume", Decimal("473.176473")), "gal": ("volume", Decimal("3785.411784")), "gallon": ("volume", Decimal("3785.411784")),
         "ct": ("count", Decimal(1)), "count": ("count", Decimal(1)), "pk": ("count", Decimal(1)), "pack": ("count", Decimal(1))}
STANDARD = {"mass": (Decimal(100), "per 100 g"), "volume": (Decimal(100), "per 100 ml"), "count": (Decimal(1), "per item")}
UNIT = r"(fl\.?\s*oz|floz|oz|lbs?|kg|g|ml|ltr|l|qt|pt|gallon|gal|count|ct|pk|pack)\b"
MULTIPACK = re.compile(r"(\d+)\s*(?:x|pk|pack|ct|count)\s*(?:x\s*)?(\d+(?:\.\d+)?)\s*" + UNIT, re.IGNORECASE)
SIZE = re.compile(r"(\d+(?:\.\d+)?)\s*" + UNIT, re.IGNORECASE)
ANOMALY_FACTOR = Decimal("1.5")
ANOMALY_MINIMUM = 20  # Major units: smaller rises are not worth mentioning.


def parse_size(text):
    """(dimension, base quantity) for a package size such as "19 oz", "1 gal" or "12 x 12 fl oz"; None if unreadable."""
    text = (text or "").lower()
    multi = MULTIPACK.search(text)
    if multi:
        count, amount, unit = Decimal(multi.group(1)), Decimal(multi.group(2)), multi.group(3)
    else:
        single = SIZE.search(text)
        if not single:
            return None
        count, amount, unit = Decimal(1), Decimal(single.group(1)), single.group(2)
    dimension, factor = UNITS[re.sub(r"[\s.]", "", unit) if unit.startswith("fl") else unit]
    if dimension == "count" and multi:
        return "count", count * amount
    quantity = count * amount * factor
    return (dimension, quantity) if quantity > 0 else None


def quantity_of(units):
    """(Decimal quantity, assumed) from the printed quantity; a missing or unreadable one counts as one unit."""
    try:
        value = Decimal((units or "").strip())
        if value > 0:
            return value, False
    except InvalidOperation:
        pass
    return Decimal(1), True


def rounded(value):
    return int(value.quantize(Decimal(1), ROUND_HALF_EVEN))


def percent(before, after):
    return None if before == 0 else str(((after - before) * 100 / before).quantize(Decimal("0.1"), ROUND_HALF_EVEN))


def product_name(row):
    return " ".join(filter(None, [row["brand"], row["name"], row["size_text"]]))


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ItemQuery(ToolInput):
    query: str = Field(min_length=1, max_length=100, description="Product name, brand or category words, e.g. 'milk' or 'household cleaning'.")


class Span(ToolInput):
    start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")

    @model_validator(mode="after")
    def ordered(self):
        first, last = date.fromisoformat(self.start), date.fromisoformat(self.end)
        if first > last:
            raise ValueError("The period start must not be after its end.")
        if (last - first).days > 731:
            raise ValueError("Choose a period of at most two years.")
        return self


class ItemPeriod(Span):
    query: str | None = Field(default=None, max_length=100, description="Optional product, brand or category words.")


class OptionalItemQuery(ToolInput):
    query: str | None = Field(default=None, max_length=100, description="Optional product, brand or category words; omit for everything.")


class MonthInput(ToolInput):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")


class ItemAnalysisTools:
    """Mixed into FinanceTools; uses its query() and connection()."""

    def _lots(self, query=None, start=None, end=None, date_column="l.bought_on", status=None):
        clauses, params = ["l.cost_minor IS NOT NULL", "l.currency IS NOT NULL"], []
        for word in normalize_text(query).split()[:8]:
            clauses.append("(p.normalized_name LIKE ? OR upper(coalesce(p.brand,'')) LIKE ? OR upper(p.category) LIKE ?)")
            params += [f"%{word}%"] * 3
        for bound, operator in ((start, ">="), (end, "<=")):
            if bound:
                clauses.append(f"{date_column}{operator}?")
                params.append(bound)
        if status:
            clauses.append("l.status=?")
            params.append(status)
        return self.query("SELECT l.*,p.name,p.brand,p.size_text,p.category,p.normalized_name,m.canonical_name AS merchant FROM inventory_lots l "
                          "JOIN products p ON p.id=l.product_id LEFT JOIN receipts r ON r.id=l.receipt_id LEFT JOIN merchants m ON m.id=r.merchant_id "
                          "WHERE " + " AND ".join(clauses) + " ORDER BY l.bought_on,l.id LIMIT 5000", params)

    @staticmethod
    def _unit_price(lot):
        """(dimension, exact price in minor units per standard unit, label, quantity assumed) or None without a readable size."""
        size = parse_size(lot["size_text"])
        if size is None:
            return None
        dimension, base = size
        quantity, assumed = quantity_of(lot["units"])
        standard, label = STANDARD[dimension]
        return dimension, Decimal(lot["cost_minor"]) * standard / (quantity * base), label, assumed

    def get_item_spending(self, value):
        """What approved receipt items cost in a period, per currency, with the products that cost most."""
        lots = self._lots(value.query, value.start, value.end)
        totals, products = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
        for lot in lots:
            totals[lot["currency"]][0] += lot["cost_minor"]
            totals[lot["currency"]][1] += 1
            products[(lot["currency"], product_name(lot))][0] += lot["cost_minor"]
            products[(lot["currency"], product_name(lot))][1] += 1
        top = sorted(products.items(), key=lambda item: -item[1][0])[:15]
        return {"period": {"start": value.start, "end": value.end}, "query": value.query,
                "by_currency": [{"currency": currency, "spent": money(total, currency), "purchases": count} for currency, (total, count) in sorted(totals.items())],
                "top_products": [{"product": name, "currency": currency, "spent": money(total, currency), "purchases": count} for (currency, name), (total, count) in top],
                "notes": ["Only receipt lines whose product you approved are included; line totals are as printed, before any separate discounts."]}

    def item_price_history(self, value):
        """Every approved purchase of matching products, oldest first, with the price per standard unit where the size is readable."""
        rows, assumed = [], False
        for lot in self._lots(value.query)[-100:]:
            unit = self._unit_price(lot)
            quantity, guess = quantity_of(lot["units"])
            assumed |= guess
            rows.append({"bought_on": lot["bought_on"], "merchant": lot["merchant"], "product": product_name(lot), "quantity": str(quantity),
                         "cost": money(lot["cost_minor"], lot["currency"]),
                         "unit_price": {"amount": money(rounded(unit[1]), lot["currency"]), "per": unit[2]} if unit else None})
        notes = ["A price per unit is shown only where the package size is readable."]
        if assumed:
            notes.append("Some receipt lines don't print a quantity; those were treated as one unit.")
        return {"query": value.query, "purchases": rows, "notes": notes}

    def get_price_changes(self, value):
        """Largest rises in price per standard unit between each product's first and last purchase in the period.
        Products are grouped by name and brand across package sizes, so a smaller package at the same price shows."""
        groups = defaultdict(list)
        for lot in self._lots(value.query, value.start, value.end):
            unit = self._unit_price(lot)
            if unit:
                groups[(normalize_text(lot["name"]), lot["brand"], lot["currency"], unit[0])].append((lot, unit))
        changes = []
        for (_, _, currency, _), purchases in groups.items():
            if len(purchases) < 2:
                continue
            (first, first_unit), (last, last_unit) = purchases[0], purchases[-1]
            if last_unit[1] <= first_unit[1]:
                continue
            changes.append({"product": " ".join(filter(None, [first["brand"], first["name"]])), "currency": currency, "per": first_unit[2],
                            "first": {"bought_on": first["bought_on"], "size": first["size_text"], "merchant": first["merchant"], "cost": money(first["cost_minor"], currency),
                                      "unit_price": money(rounded(first_unit[1]), currency)},
                            "last": {"bought_on": last["bought_on"], "size": last["size_text"], "merchant": last["merchant"], "cost": money(last["cost_minor"], currency),
                                     "unit_price": money(rounded(last_unit[1]), currency)},
                            "percent_change": percent(first_unit[1], last_unit[1]),
                            "package_size_changed": normalize_text(first["size_text"]) != normalize_text(last["size_text"]), "_sort": (last_unit[1] - first_unit[1]) / first_unit[1]})
        changes.sort(key=lambda row: -row["_sort"])
        for row in changes:
            del row["_sort"]
        return {"period": {"start": value.start, "end": value.end}, "increases": changes[:20],
                "notes": ["Compares the first and last purchase of each product in the period, per 100 g, 100 ml or item.",
                          "package_size_changed marks a different package size, which is how a smaller pack at the same price (shrinkflation) shows."]}

    def compare_merchant_prices(self, value):
        """Each merchant's latest price per standard unit for matching products, cheapest first."""
        latest = {}
        for lot in self._lots(value.query):
            unit = self._unit_price(lot)
            if unit:
                latest[(lot["merchant"] or "Unknown merchant", lot["currency"], unit[0])] = (lot, unit)
        rows = sorted(latest.items(), key=lambda item: (item[0][1], item[0][2], item[1][1][1]))
        return {"query": value.query, "merchants": [{"merchant": merchant, "currency": currency, "per": unit[2], "unit_price": money(rounded(unit[1]), currency),
                                                     "product": product_name(lot), "bought_on": lot["bought_on"], "cost": money(lot["cost_minor"], currency)}
                                                    for (merchant, currency, _), (lot, unit) in rows],
                "notes": ["Latest purchase at each merchant; only products with a readable package size are compared."]}

    def _rates(self, query=None):
        """Per product: (currency, total cost, total days, lots) over finished lots with both dates."""
        rates = {}
        for lot in self._lots(query, status="finished"):
            if not lot["closed_on"] or not lot["bought_on"]:
                continue
            days = max(1, (date.fromisoformat(lot["closed_on"]) - date.fromisoformat(lot["bought_on"])).days)
            key = (lot["product_id"], lot["currency"])
            entry = rates.setdefault(key, {"product": product_name(lot), "currency": lot["currency"], "cost": 0, "days": 0, "lots": 0})
            entry["cost"] += lot["cost_minor"]
            entry["days"] += days
            entry["lots"] += 1
        return list(rates.values())

    def get_consumption_cost(self, value):
        """Cost per day and per 30 days from finished lots: total cost divided by total days each lasted."""
        rows, totals = [], defaultdict(Decimal)
        for entry in sorted(self._rates(value.query), key=lambda item: -item["cost"] / item["days"]):
            per_day = Decimal(entry["cost"]) / entry["days"]
            totals[entry["currency"]] += per_day * 30
            rows.append({"product": entry["product"], "currency": entry["currency"], "per_day": money(rounded(per_day), entry["currency"]),
                         "per_30_days": money(rounded(per_day * 30), entry["currency"]), "finished_lots": entry["lots"], "approximate": entry["lots"] < 3})
        return {"query": value.query, "products": rows[:50],
                "per_30_days_by_currency": [{"currency": currency, "amount": money(rounded(total), currency)} for currency, total in sorted(totals.items())],
                "notes": ["Only items you marked finished count; thrown-out ones are waste, not consumption.",
                          "approximate is true while fewer than three finished lots back a figure."]}

    def get_waste(self, value):
        """Thrown-out items closed in the period and what they cost."""
        lots = self._lots(value.query, value.start, value.end, date_column="l.closed_on", status="thrown_out")
        totals = defaultdict(lambda: [0, 0])
        for lot in lots:
            totals[lot["currency"]][0] += lot["cost_minor"]
            totals[lot["currency"]][1] += 1
        return {"period": {"start": value.start, "end": value.end},
                "by_currency": [{"currency": currency, "wasted": money(total, currency), "items": count} for currency, (total, count) in sorted(totals.items())],
                "items": [{"product": product_name(lot), "thrown_out_on": lot["closed_on"], "cost": money(lot["cost_minor"], lot["currency"])} for lot in lots[:50]]}

    def forecast_consumables_spend(self, value):
        """Projected cost of consumables in a month: each product's consumption rate times the month's days."""
        year, month = map(int, value.month.split("-"))
        days = ((date(year + month // 12, month % 12 + 1, 1)) - date(year, month, 1)).days
        rows, totals, skipped = [], defaultdict(Decimal), 0
        for entry in self._rates():
            if entry["lots"] < 2:
                skipped += 1
                continue
            projected = Decimal(entry["cost"]) * days / entry["days"]
            totals[entry["currency"]] += projected
            rows.append({"product": entry["product"], "currency": entry["currency"], "projected": money(rounded(projected), entry["currency"]), "finished_lots": entry["lots"]})
        rows.sort(key=lambda row: -row["projected"]["minor"])
        return {"month": value.month, "days": days, "products": rows[:50],
                "by_currency": [{"currency": currency, "projected": money(rounded(total), currency)} for currency, total in sorted(totals.items())],
                "notes": [f"Projected from how long finished items lasted; {skipped} product(s) with fewer than two finished lots are not included.",
                          "A projection, not a record: actual spending depends on what you buy."]}

    def detect_spending_anomalies(self, value):
        """Categories and merchants whose counted spending in the period is well above their average over the
        three preceding periods of the same length."""
        start, end = date.fromisoformat(value.start), date.fromisoformat(value.end)
        length = (end - start).days + 1
        periods = [(start - timedelta(days=length * n), end - timedelta(days=length * n)) for n in range(4)]

        def spent(first, last):
            by = defaultdict(int)
            for row in self.query(f"SELECT t.currency,coalesce(t.category,'uncategorized') AS category,coalesce(m.canonical_name,t.description_raw) AS merchant,"
                                  f"t.amount_minor FROM transactions t LEFT JOIN merchants m ON m.id=t.merchant_id WHERE {COUNTABLE} "
                                  f"AND t.transaction_type IN ({SPENDING_TYPES}) AND t.posted_date BETWEEN ? AND ?", (first.isoformat(), last.isoformat())):
                by[("category", row["currency"], row["category"])] -= row["amount_minor"]
                by[("merchant", row["currency"], " ".join(normalize_name(row["merchant"]).split()[:3]) or "UNKNOWN")] -= row["amount_minor"]
            return by

        current, history = spent(*periods[0]), [spent(*period) for period in periods[1:]]
        flagged = []
        for key, amount in current.items():
            kind, currency, name = key
            baseline = sum(Decimal(past.get(key, 0)) for past in history) / 3
            minimum = ANOMALY_MINIMUM * 10 ** EXPONENTS[currency]
            if amount - baseline >= minimum and (baseline == 0 or amount > baseline * ANOMALY_FACTOR):
                flagged.append({"kind": kind, "name": name, "currency": currency, "spent": money(amount, currency),
                                "usual": money(rounded(baseline), currency), "percent_above_usual": percent(baseline, Decimal(amount)), "new": baseline == 0,
                                "_sort": amount - baseline})
        flagged.sort(key=lambda row: -row["_sort"])
        for row in flagged:
            del row["_sort"]
        return {"period": {"start": value.start, "end": value.end},
                "compared_with": [{"start": first.isoformat(), "end": last.isoformat()} for first, last in periods[1:]],
                "anomalies": flagged[:20],
                "notes": [f"Flagged when spending is at least {ANOMALY_FACTOR}× the average of the three earlier periods and at least {ANOMALY_MINIMUM} "
                          "(in the currency's main unit) above it. new marks spending with no history in those periods.",
                          "Only imported or verified transactions count; each currency is separate."]}


ITEM_TOOLS = {"get_item_spending": (ItemPeriod, "get_item_spending"), "item_price_history": (ItemQuery, "item_price_history"),
              "get_price_changes": (ItemPeriod, "get_price_changes"), "compare_merchant_prices": (ItemQuery, "compare_merchant_prices"),
              "get_consumption_cost": (OptionalItemQuery, "get_consumption_cost"), "get_waste": (ItemPeriod, "get_waste"),
              "forecast_consumables_spend": (MonthInput, "forecast_consumables_spend")}
ANOMALY_TOOLS = {"detect_spending_anomalies": (Span, "detect_spending_anomalies")}
