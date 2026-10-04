"""Payee scan (docs/evals.md, task 11): which statement payees are ongoing services billed on a schedule.

Each case is a batch of payees with their recent charges, as finance/recurring_scan.py sends them. A recurring payee
needs its frequency (judged from the service and the charge dates) and a category; a shop, restaurant or fuel stop
needs null, however often it was visited.
"""

from datetime import date, timedelta
import random

from home_manager.finance.recurring_scan import SCAN_VERSION, RecurringScan

from .common import make_case, result

NAME, ROLE, VERSION, PROMPT_VERSION = "payees", "reasoning", "payees-v1", SCAN_VERSION
START, LAST = date(2026, 3, 1), date(2026, 9, 5)
# (statement text, recurrence or None, months between charges, amount in cents (None: varies), category choices)
PAYEES = [
    ("NETFLIX.COM 866-579", "monthly", 1, 1549, {"subscriptions", "entertainment"}),
    ("SPOTIFY USA", "monthly", 1, 1199, {"subscriptions", "entertainment"}),
    ("CITY POWER & LIGHT", "monthly", 1, None, {"housing"}),
    ("COMCAST XFINITY", "monthly", 1, 8999, {"housing"}),
    ("VERIZON WIRELESS", "monthly", 1, 7250, {"housing"}),
    ("PLANET FITNESS CLUB", "monthly", 1, 2499, {"subscriptions"}),
    ("MAPLE COURT APTS RENT", "monthly", 1, 185000, {"housing"}),
    ("GEICO AUTO PAYMENT", "monthly", 1, 10700, {"insurance"}),
    ("CITY WATER UTILITY", "quarterly", 3, None, {"housing"}),
    ("STATE FARM INSURANCE", "semiannual", 6, 64200, {"insurance"}),
    ("AMAZON PRIME ANNUAL", "annual", 12, 13900, {"subscriptions"}),
    ("LAKESIDE AUTO FINANCE", "monthly", 1, 41237, {"transportation", "other"}),
    ("SHELL OIL 57441", None, 0, None, set()),
    ("STARBUCKS STORE 1123", None, 0, None, set()),
    ("WHOLE FOODS MARKET", None, 0, None, set()),
    ("TARGET T-1427", None, 0, None, set()),
    ("UBER TRIP", None, 0, None, set()),
    ("THE HOME DEPOT #4410", None, 0, None, set()),
    ("CHIPOTLE 2231", None, 0, None, set()),
    ("DELTA AIR LINES", None, 0, None, set()),
    ("CVS PHARMACY 8821", None, 0, None, set()),
    ("BEST BUY 00123", None, 0, None, set()),
]


def months_before(day, months):
    total = day.year * 12 + day.month - 1 - months
    return day.replace(year=total // 12, month=total % 12 + 1)


def charges(rng, recurrence, months, cents):
    """Newest first, as the scan shows them: a scheduled payee's charges on the same day of the month, counting back from
    LAST; any other payee's on irregular days with varying amounts, sometimes several a month."""
    if recurrence is None:
        days = sorted({START + timedelta(days=rng.randrange(180)) for _ in range(rng.randint(2, 6))}, reverse=True)
        return [f"{day.isoformat()} {rng.randrange(400, 15000) / 100:.2f} USD" for day in days]
    days = [months_before(LAST, months * index) for index in range(3 if months < 12 else 2)]
    return [f"{day.isoformat()} {(cents or rng.randrange(6000, 14000)) / 100:.2f} USD" for day in days]


def cases():
    rng = random.Random(20261003)
    out = []
    for _ in range(20):
        chosen = rng.sample(PAYEES, 5)
        batch = [{"name": name, "charges": charges(rng, recurrence, months, cents)} for name, recurrence, months, cents, _ in chosen]
        expected = [{"recurrence": recurrence, "category": sorted(categories)} for _, recurrence, _, _, categories in chosen]
        out.append(make_case(NAME, {"payees": batch}, {"payees": expected}))
    return out


def run(case, config, work):
    answers = RecurringScan.ask(config, case["input"]["payees"], work)
    if not answers:
        raise ValueError("Extraction output failed validation: the answer did not follow the payee format.")
    return {"payees": [{"payee_id": answer.payee_id, "recurrence": answer.recurrence, "category": answer.category} for answer in answers]}


def grade(case, output):
    expected = case["expected"]["payees"]
    got = {}
    for answer in output["payees"]:
        got.setdefault(answer["payee_id"], answer)  # The scan keeps the first answer for a payee.
    right_frequency = right_category = 0
    true_positive = false_positive = false_negative = 0
    for index, want in enumerate(expected):
        answer = got.get(index, {"recurrence": "missing", "category": None})
        right_frequency += answer["recurrence"] == want["recurrence"]
        is_recurring, said_recurring = want["recurrence"] is not None, answer["recurrence"] not in (None, "missing")
        true_positive += is_recurring and said_recurring
        false_positive += said_recurring and not is_recurring
        false_negative += is_recurring and not said_recurring
        right_category += (not is_recurring) or answer["category"] in want["category"]
    f1 = 2 * true_positive / (2 * true_positive + false_positive + false_negative) if true_positive + false_positive + false_negative else 1.0
    checks = {"frequency": round(right_frequency / len(expected), 4), "category": round(right_category / len(expected), 4),
              "recurring_f1": round(f1, 4), "answered_all": set(range(len(expected))) <= set(got)}
    checks["all_right"] = checks["frequency"] == checks["category"] == 1.0
    return result(checks, ["all_right", "answered_all"], ["frequency", "category", "recurring_f1"])
