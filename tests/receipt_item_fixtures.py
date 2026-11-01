"""Synthetic receipts and stub replies for the receipt item table (specs/receipt-item-table/test-contract.md "Fixtures").

R (answered by RA), D, G and N (answered by NA) are exactly as the contract prints them; the hand-worked amounts are in
the constants beside each. Replies are keyed by schema name for local_model["by_schema"] (tests/model_server.py), built
from tests/document_forms_fixtures.py. specs/receipt-tax-codes extends this file later.
"""

from document_forms_fixtures import amount_on, cite, item, receipt_replies, value

# R: the user's receipt. Only the filter is taxed, so all of the 274 tax goes to it.
R_LINES = ["SYNTH MART", "2026-10-20", "GROCERY", "071057174 RUFFLES BF $4.29", "211180042 LITLE VEGET BF $41.90", "10 @ $4.19 ea",
           "KITCHEN", "07200120 WATER FILTER T $12.99", "Regular Price $15.99", "SUBTOTAL $59.18",
           "T = GA TAX 7.75000 on $12.99 $1.01", "B = GA TAX 7.75000 on $46.19 $1.73", "TOTAL $61.92"]
R_AMOUNTS = (5918, 274, 6192)  # subtotal, tax, total
R_SHARES = [429, 4190, 1573]

# D: the docs' Costco example (docs/money.md "Item categories and splits"): one TAX line, no codes printed.
D_LINES = ["SYNTH WHOLESALE", "2026-10-05", "HOT DOG 1.50", "MATTRESS 499.99", "GROCERIES 80.00", "SUBTOTAL 581.49", "TAX 40.12", "TOTAL 621.61"]
D_AMOUNTS = (58149, 4012, 62161)
D_SHARES = [162, 53999, 8000]

# G: a weighed item, a counted item and a plain one, with no tax.
G_LINES = ["SYNTH MARKET", "2026-10-03", "BANANAS 2.31 lb @ 0.59/lb 1.36", "3 @ YOGURT 4.50", "MILK 3.49", "SUBTOTAL 9.35", "TAX 0.00", "TOTAL 9.35"]
G_AMOUNTS = (935, 0, 935)

# N: a whole return of the filter. Only returned lines, so every amount is money back (sign_return's whole-return branch).
N_LINES = ["SYNTH MART", "2026-10-20", "RETURN", "KITCHEN", "07200120 WATER FILTER T $12.99", "SUBTOTAL $12.99",
           "T = GA TAX 7.75000 on $12.99 $1.01", "TOTAL $14.00"]
N_AMOUNTS = (-1299, -101, -1400)
N_SHARES = [-1400]


def categories(*names):
    """PurchaseDescription's reply for a receipt whose items are in these categories (None: not categorized)."""
    return {"description": None, "category": None, "recurrence": None, "item_categories": list(names)}


def with_categories(replies, *names):
    return {**replies, "PurchaseDescription": [categories(*names)]}


def ra_replies():
    """RA: R read as a grocery receipt with today's fields. Ruffles and the filter print no quantity; Little Veg prints 10 @ 4.19."""
    lines = R_LINES
    tax = {"value": "2.74", "status": "proposed", "evidence": cite(lines, "T = GA TAX") + cite(lines, "B = GA TAX")}
    summary = {"subtotal": amount_on(lines, "SUBTOTAL"), "tax": tax, "total": amount_on(lines, "TOTAL ")}
    items = [item(lines, "RUFFLES", "071057174 RUFFLES", "4.29", product_code="071057174", taxed=False),
             item(lines, "LITLE VEGET", "211180042 LITLE VEGET", "41.90", product_code="211180042", quantity="10", unit_price="4.19",
                  taxed=False, also=["10 @ $4.19 ea"]),
             item(lines, "WATER FILTER", "07200120 WATER FILTER", "12.99", product_code="07200120", taxed=True)]
    return with_categories(receipt_replies(lines, "grocery", "Synth Mart", "SYNTH MART", "2026-10-20", summary, items,
                                           kind_evidence=cite(lines, "GROCERY")), "groceries", "groceries", "household supplies")


def d_replies():
    """D read as a general receipt: hot dog and mattress taxed, groceries not."""
    lines = D_LINES
    summary = {"subtotal": amount_on(lines, "SUBTOTAL"), "tax": amount_on(lines, "TAX "), "total": amount_on(lines, "TOTAL ")}
    items = [item(lines, "HOT DOG", "HOT DOG 1.50", "1.50", taxed=True), item(lines, "MATTRESS", "MATTRESS 499.99", "499.99", taxed=True),
             item(lines, "GROCERIES", "GROCERIES 80.00", "80.00", taxed=False)]
    return with_categories(receipt_replies(lines, "general", "Synth Wholesale", "SYNTH WHOLESALE", "2026-10-05", summary, items),
                           "dining", "furniture & decor", "groceries")


def g_replies():
    """G read as a grocery receipt: bananas with a weight and a price per weight, yogurt with a count, milk with neither."""
    lines = G_LINES
    summary = {"subtotal": amount_on(lines, "SUBTOTAL"), "tax": amount_on(lines, "TAX "), "total": amount_on(lines, "TOTAL ")}
    items = [item(lines, "BANANAS", "BANANAS", "1.36", weight="2.31", weight_unit="lb", price_per_weight="0.59"),
             item(lines, "YOGURT", "3 @ YOGURT 4.50", "4.50", quantity="3"),
             item(lines, "MILK", "MILK 3.49", "3.49")]
    return with_categories(receipt_replies(lines, "grocery", "Synth Market", "SYNTH MARKET", "2026-10-03", summary, items,
                                           kind_evidence=cite(lines, "MILK")), "groceries", "groceries", "groceries")


def na_replies():
    """NA: N read with an unsigned summary (12.99, 1.01, 14.00) and the cited RETURN marker; the filter's line is -12.99."""
    lines = N_LINES
    summary = {"subtotal": amount_on(lines, "SUBTOTAL"), "tax": amount_on(lines, "T = GA TAX"), "total": amount_on(lines, "TOTAL "),
               "return_marker": value(lines, "RETURN", "RETURN")}
    items = [item(lines, "WATER FILTER", "07200120 WATER FILTER", "-12.99", product_code="07200120", taxed=True, returned=True)]
    return with_categories(receipt_replies(lines, "grocery", "Synth Mart", "SYNTH MART", "2026-10-20", summary, items,
                                           kind_evidence=cite(lines, "KITCHEN")), "household supplies")

