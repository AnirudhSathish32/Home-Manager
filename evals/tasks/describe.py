"""Describe purchase (eval_plan.md task 6): a receipt's category, how often it recurs, and a category per item.

Categories are graded against the set a careful person would accept (toothpaste at a pharmacy is personal care,
allergy tablets are health). The one-or-two-word description is checked only for shape here; whether it is useful
is the judge's rubric (evals/rubrics/describe.md).
"""

from types import SimpleNamespace

from home_manager.documents.extraction import EXTRACTION_VERSION, ExtractionService

from .common import make_case, result, text_lines

NAME, ROLE, VERSION, PROMPT_VERSION, RUBRIC = "describe", "reasoning", "describe-v1", EXTRACTION_VERSION, "describe"
FOOD = {"groceries", "dining"}
# (seller, category choices, recurrence, [(item, price, item category choices)], extra lines)
RECEIPTS = [
    ("GREEN LEAF GROCERY", {"groceries"}, None, [("BANANAS", "1.29", {"groceries"}), ("WHOLE MILK 1GAL", "3.89", {"groceries"}),
                                                 ("SOURDOUGH LOAF", "5.49", {"groceries"})], ()),
    ("FRESH MART", {"groceries"}, None, [("EGGS DOZEN", "4.59", {"groceries"}), ("CHEDDAR 8OZ", "4.79", {"groceries"}),
                                         ("APPLES 3LB", "5.99", {"groceries"}), ("PASTA", "1.99", {"groceries"})], ()),
    ("VALLEY FOODS", {"groceries"}, None, [("CHICKEN BREAST", "9.87", {"groceries"}), ("RICE 2LB", "3.49", {"groceries"})], ()),
    ("SAVE MORE SUPERMARKET", {"groceries", "household supplies"}, None,
     [("TOMATO SAUCE", "2.89", {"groceries"}), ("PAPER TOWELS 6PK", "8.99", {"household supplies"}), ("ORANGE JUICE", "4.29", {"groceries"})], ()),
    ("CORNER COFFEE", {"dining"}, None, [("LATTE", "4.50", {"dining"}), ("MUFFIN", "3.25", FOOD)], ()),
    ("SUNRISE CAFE", {"dining"}, None, [("CAPPUCCINO", "4.25", {"dining"}), ("CROISSANT", "3.75", FOOD), ("ICED TEA", "3.00", FOOD)], ()),
    ("BLUE PLATE DINER", {"dining"}, None, [("PANCAKES", "11.50", {"dining"}), ("COFFEE", "2.95", {"dining"})], ("Tip 2.90",)),
    ("HILLSIDE HARDWARE", {"home improvement"}, None, [("WOOD SCREWS 100PK", "8.99", {"home improvement"}),
                                                        ("PAINT ROLLER", "11.95", {"home improvement"}), ("DUCT TAPE", "6.49", {"home improvement", "household supplies"})], ()),
    ("BUILDRIGHT SUPPLY", {"home improvement"}, None, [("2X4 STUD 8FT", "4.28", {"home improvement"}), ("DRILL BIT SET", "24.00", {"home improvement"})], ()),
    ("NORTHSIDE PHARMACY", {"health", "personal care"}, None, [("ALLERGY TABLETS", "12.99", {"health"}), ("VITAMIN D", "8.99", {"health"})], ()),
    ("CITY DRUG", {"health", "personal care"}, None, [("TOOTHPASTE", "4.49", {"personal care"}), ("SHAMPOO", "6.99", {"personal care"}),
                                                      ("BANDAGES", "5.49", {"health"})], ()),
    ("METRO ELECTRONICS", {"electronics"}, None, [("USB-C CABLE", "14.99", {"electronics"}), ("WIRELESS MOUSE", "29.99", {"electronics"})], ()),
    ("GADGET HUB", {"electronics"}, None, [("HDMI ADAPTER", "19.99", {"electronics"}), ("PHONE CASE", "24.99", {"electronics"})], ()),
    ("QUICKFUEL STATION 112", {"transportation"}, None, [("UNLEADED 11.2 GAL", "40.21", {"transportation"})], ()),
    ("CITY PARKING GARAGE", {"transportation"}, None, [("PARKING 2 HR", "12.00", {"transportation"})], ()),
    ("PAGE TURNER BOOKS", {"entertainment"}, None, [("NOVEL PAPERBACK", "17.99", {"entertainment"}), ("COOKBOOK", "32.50", {"entertainment"})], ()),
    ("WAREHOUSE CLUB", {"groceries", "furniture & decor", "household supplies", "other", None}, None,
     [("HOT DOG COMBO", "1.50", {"dining"}), ("QUEEN MATTRESS", "499.99", {"furniture & decor"}), ("EGGS 24CT", "6.49", {"groceries"}),
      ("PAPER TOWELS 12PK", "21.99", {"household supplies"})], ()),
    ("HAPPY PAWS PET SUPPLY", {"pets"}, None, [("DOG FOOD 30LB", "54.99", {"pets"}), ("CHEW TOY", "8.99", {"pets"})], ()),
    ("DENIM & CO", {"clothing"}, None, [("JEANS", "49.00", {"clothing"}), ("T-SHIRT", "18.00", {"clothing"})], ()),
    ("STREAMFLIX", {"subscriptions", "entertainment"}, "monthly", [("PREMIUM PLAN", "15.49", {"subscriptions", "entertainment"})],
     ("Billing period 2026-08-05 to 2026-09-04", "Your plan renews monthly")),
    ("CITY POWER & LIGHT", {"housing"}, "monthly", [("ELECTRIC SERVICE", "88.40", {"housing"})],
     ("Account 4410-22", "Billing period 2026-08-01 to 2026-08-31", "Payment received - thank you")),
    ("SAFEGUARD AUTO INSURANCE", {"insurance"}, "semiannual", [("6-MONTH AUTO PREMIUM", "642.00", {"insurance"})],
     ("Policy period 2026-09-01 to 2027-03-01", "Payment received")),
    ("IRONWORKS GYM", {"subscriptions"}, "annual", [("ANNUAL MEMBERSHIP", "480.00", {"subscriptions"})], ("Membership renews every year",)),
    ("NORTHWEST FIBER", {"housing"}, "monthly", [("INTERNET 500 MBPS", "65.00", {"housing"})],
     ("Service period 2026-09-01 to 2026-09-30", "Autopay - thank you")),
]


def cases():
    out = []
    for seller, categories, recurrence, items, extra in RECEIPTS:
        lines = [seller, "2026-08-14", *[f"{name} {price}" for name, price, _ in items], *extra,
                 f"Total {sum(float(price) for _, price, _ in items):.2f}"]
        out.append(make_case(NAME, {"seller": seller.title(), "lines": lines, "items": [name for name, _, _ in items]},
                             {"category": sorted(categories, key=str), "recurrence": recurrence, "items": [sorted(choices) for _, _, choices in items]},
                             ["recurring"] if recurrence else []))
    return out


def run(case, config, work):
    rows = [SimpleNamespace(description=name) for name in case["input"]["items"]]
    description, category, recurrence, items = ExtractionService.describe_purchase(config, work, text_lines(case["input"]["lines"]), rows,
                                                                                    case["input"]["seller"], None)
    return {"description": description, "category": category, "recurrence": recurrence, "item_categories": items}


def grade(case, output):
    expected = case["expected"]
    items = output["item_categories"]
    right = sum(got in choices for got, choices in zip(items, expected["items"])) if items else 0
    checks = {"category": output["category"] in expected["category"], "recurrence": output["recurrence"] == expected["recurrence"],
              "item_categories": round(right / len(expected["items"]), 4), "item_list_complete": items is not None,
              "described": bool(output["description"])}
    checks["items_mostly_right"] = checks["item_categories"] >= 0.8
    return result(checks, ["category", "recurrence", "items_mostly_right", "described"], ["category", "recurrence", "item_categories"])
