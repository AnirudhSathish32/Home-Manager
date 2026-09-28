"""Receipt spending categories: one fixed, flat list, used for receipt items, the Receipts folder's subfolders and spending totals."""

RECEIPT_CATEGORIES = ("groceries", "dining", "furniture & decor", "household supplies", "home improvement", "clothing", "electronics",
                      "personal care", "transportation", "travel", "health", "entertainment", "subscriptions", "housing", "insurance",
                      "pets", "kids & baby", "gifts & donations", "other")
# Retired names still found in stored data until it is re-sorted (finance/item_categories.py); never offered as a choice.
# "shopping" covered all general retail until 2026-09-28.
LEGACY_CATEGORIES = ("shopping",)
# What each category covers, for the model's suggestion.
CATEGORY_GUIDE = ("groceries (food and drink to take home and cook), dining (restaurants, cafes, takeout, food courts, bars), "
                  "furniture & decor (furniture, mattresses, bedding, rugs, decor, kitchenware, appliances), "
                  "household supplies (cleaning products, paper goods, laundry, storage, batteries, light bulbs), "
                  "home improvement (hardware, tools, paint, garden, repair parts), clothing (clothing, shoes, accessories), "
                  "electronics (phones, computers, TVs, games consoles, cables, gadgets), personal care (toiletries, cosmetics, haircuts, grooming), "
                  "transportation (fuel, parking, tolls, car maintenance, transit, rideshare), travel (hotels, flights, car rental, trips), "
                  "health (pharmacy, medical, dental, vision), entertainment (movies, events, books, games, hobbies), "
                  "subscriptions (streaming, software, memberships), housing (rent, mortgage, HOA dues, utilities: power, water, gas, "
                  "internet, phone), insurance (home, renters, auto, health or life premiums), pets (pet food, supplies, vet), "
                  "kids & baby (diapers, baby gear, toys, school supplies, childcare), gifts & donations (gifts for others, charity), other")
# How often a bill recurs, and how many months apart its payments are. Weekly is handled as 12/52 of a month.
FREQUENCY_MONTHS = {"monthly": 1, "quarterly": 3, "semiannual": 6, "annual": 12}
FREQUENCIES = ("weekly", *FREQUENCY_MONTHS)


def receipt_category(value, legacy=False):
    """A category from the fixed list, compared in lower case; None clears it. legacy accepts retired names,
    for re-applying data stored before the list changed."""
    if value is None or not str(value).strip():
        return None
    name = " ".join(str(value).split()).lower()
    if name not in RECEIPT_CATEGORIES and not (legacy and name in LEGACY_CATEGORIES):
        raise ValueError("Choose one of the listed categories.")
    return name
