"""Receipt spending categories: one fixed list, used as the Receipts folder's subfolders and in spending totals."""

RECEIPT_CATEGORIES = ("dining", "groceries", "shopping", "travel", "health", "entertainment", "insurance", "housing", "other")
# What each category covers, for the model's suggestion.
CATEGORY_GUIDE = ("dining (restaurants, cafes, takeout, bars), groceries (supermarkets, food to cook), "
                  "shopping (clothing, electronics, furniture, hardware, household supplies, general retail), "
                  "travel (hotels, flights, car rental, fuel, parking, transit, rideshare), health (pharmacy, medical, dental), "
                  "entertainment (movies, events, games, hobbies, streaming), "
                  "insurance (home, renters, auto, health or life premiums), "
                  "housing (rent, mortgage, HOA dues, repairs to the home, and utilities: power, water, gas, internet, phone), other")
# How often a bill recurs, and how many months apart its payments are. Weekly is handled as 12/52 of a month.
FREQUENCY_MONTHS = {"monthly": 1, "quarterly": 3, "semiannual": 6, "annual": 12}
FREQUENCIES = ("weekly", *FREQUENCY_MONTHS)


def receipt_category(value):
    """A category from the fixed list, compared in lower case; None clears it."""
    if value is None or not str(value).strip():
        return None
    name = " ".join(str(value).split()).lower()
    if name not in RECEIPT_CATEGORIES:
        raise ValueError("Choose one of the listed categories.")
    return name
