"""Rewards (eval_plan.md task 7): points, savings, coupons and survey offers printed on a receipt.

Graded as sets: every printed reward amount and link is found, and nothing else is listed (the purchased items,
subtotal, tax and total are never rewards). A receipt without rewards must give an empty list.
"""

import random
import re

from home_manager.documents.extraction import EXTRACTION_VERSION, ExtractionService

from .common import make_case, result, text_lines

NAME, ROLE, VERSION, PROMPT_VERSION = "rewards", "reasoning", "rewards-v1", EXTRACTION_VERSION
# (printed line, kind, amount as compared, link)
OFFERS = [
    ("You earned 45 points today", "earned", "45", None),
    ("Points earned this visit: 120", "earned", "120", None),
    ("Rewards balance 1,230 points", "balance", "1230", None),
    ("Your points balance: 860", "balance", "860", None),
    ("Member savings 3.50", "membership", "3.50", None),
    ("Club card savings $6.25", "membership", "6.25", None),
    ("Redeemed 500 points", "redeemed", "500", None),
    ("Take our survey at survey.greenleaf.com for 10% off your next visit", "survey", "10%", "survey.greenleaf.com"),
    ("Tell us how we did: www.cornercoffee.com/feedback - get a free pastry", "survey", None, "www.cornercoffee.com/feedback"),
    ("COUPON: $5 off your next $50 purchase, expires 2026-10-31", "offer", "5", None),
    ("Save 15% on your next order with code SAVE15", "offer", "15%", "SAVE15"),
    ("2% cash back earned on this purchase", "earned", "2%", None),
]
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?%?")
STORES = [("GREEN LEAF GROCERY", "BANANAS", "1.29"), ("CORNER COFFEE", "LATTE", "4.50"), ("NORTHSIDE PHARMACY", "VITAMIN D", "8.99"),
          ("HILLSIDE HARDWARE", "DUCT TAPE", "6.49"), ("PAGE TURNER BOOKS", "NOTEBOOK", "8.99"), ("QUICKFUEL STATION 112", "SNACK BAR", "2.49"),
          ("METRO ELECTRONICS", "USB-C CABLE", "14.99")]


def cases():
    rng = random.Random(20261003)
    out = []
    for index in range(24):
        count = 0 if index % 6 == 0 else rng.randint(1, 3)  # Every sixth receipt has no rewards at all.
        offers = rng.sample(OFFERS, count)
        store, item, price = STORES[index % len(STORES)]
        lines = [store, f"2026-08-{index + 1:02d}", f"{item} {price}", f"Subtotal {price}", "Tax 0.00", f"Total {price}",
                 "VISA ****4242", *[line for line, *_ in offers], "Thank you for shopping"]
        out.append(make_case(NAME, {"lines": lines}, {"rewards": [{"kind": kind, "amount": amount, "link": link} for _, kind, amount, link in offers]},
                             ["none"] if not offers else []))
    return out


def run(case, config, work):
    found = ExtractionService.rewards(config, work, text_lines(case["input"]["lines"]))
    if found is None:
        raise ValueError("Extraction output failed validation: no rewards answer passed its checks.")
    return {"rewards": [{"kind": reward["kind"], "amount": reward["amount"], "link": reward["link"]} for reward in found]}


def amount_key(text):
    if text is None:
        return None
    match = NUMBER.search(text)
    return match.group().replace(",", "") if match else text.strip().lower()


def grade(case, output):
    want = {("amount", amount_key(item["amount"])) for item in case["expected"]["rewards"] if item["amount"]}
    want |= {("link", item["link"].lower()) for item in case["expected"]["rewards"] if item["link"]}
    got = {("amount", amount_key(item["amount"])) for item in output["rewards"] if item["amount"]}
    got |= {("link", item["link"].strip().lower()) for item in output["rewards"] if item["link"]}
    found = len(want & got)
    precision = found / len(got) if got else 1.0
    recall = found / len(want) if want else 1.0
    kinds = sorted(item["kind"] for item in case["expected"]["rewards"]) == sorted(item["kind"] for item in output["rewards"])
    checks = {"recall": round(recall, 4), "precision": round(precision, 4), "exact": want == got,
              "count": len(output["rewards"]) == len(case["expected"]["rewards"]), "kinds": kinds,
              "money_errors": sum(kind == "amount" for kind, _ in got - want)}  # A listed amount that was not a printed reward.
    return result(checks, ["exact", "count"], ["recall", "precision"])
