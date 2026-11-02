"""Receipt tax codes (docs/evals.md; specs/receipt-tax-codes FR-08, FR-09, FR-24): the code printed beside each item, and the
per-code tax lines.

Two kinds of made-up grocery receipt, each read as the app reads any receipt (ExtractionService.extract, then normalize):
- tax_lines: two items coded BF-ish and one coded T, with a printed tax line for each code (R, the user's receipt).
  Graded on both tax lines read with their codes and amounts within a cent, and on each item's code holding its tax line's code.
- one_tax_line: the same items with a single TAX line (SC-16). Graded on no BF item read as taxed false: with no legend and
  no per-code lines, the F of BF (food stamp) is not a reason to call an item untaxed.
"""

from decimal import ROUND_HALF_UP, Decimal

from home_manager.core.money import as_decimal_text
from home_manager.documents.extraction import EXTRACTION_VERSION, normalize

from .common import make_case, result, text_lines
from .receipt_kinds import reader

NAME, ROLE, VERSION, PROMPT_VERSION = "receipt_tax_codes", "reasoning", "receipt-tax-codes-v1", EXTRACTION_VERSION
MODES = ("tax_lines", "one_tax_line")

# R: the user's receipt, as tests/receipt_item_fixtures.py prints it (the first case of each kind).
R = ["SYNTH MART", "2026-10-20", "GROCERY", "071057174 RUFFLES BF $4.29", "211180042 LITLE VEGET BF $41.90", "10 @ $4.19 ea",
     "KITCHEN", "07200120 WATER FILTER T $12.99", "Regular Price $15.99", "SUBTOTAL $59.18",
     "T = GA TAX 7.75000 on $12.99 $1.01", "B = GA TAX 7.75000 on $46.19 $1.73", "TOTAL $61.92"]
R_ITEMS = [("071057174", "B"), ("211180042", "B"), ("07200120", "T")]  # Product code, the tax line's code its item's printed code holds.
R_TAX_LINES = {"T": "1.01", "B": "1.73"}
R_ONE_TAX_LINE = [*R[:10], "TAX $2.74", R[12]]

# More receipts: (merchant, rate, [grocery item name, product code, price in cents] twice, grocery code, filter-like item, its code).
SHOPS = [("GREEN LEAF GROCERY", "6.00000", (("BANANA CHIPS", "041220576", 329), ("RICE 5 LB", "068100123", 1249)), "BF", ("DISH SOAP", "035000987", 449), "T"),
         ("VALLEY MARKET", "7.00000", (("PASTA SAUCE", "072940001", 289), ("OATMEAL", "030000566", 519)), "FB", ("LIGHT BULBS", "046135200", 899), "T"),
         ("FRESH FIELDS", "8.25000", (("GREEK YOGURT", "070470003", 599), ("GRANOLA", "021130044", 799)), "B", ("PAPER TOWELS", "037000211", 1099), "T"),
         ("CITY FOODS", "4.00000", (("SALSA", "073416000", 349), ("TORTILLAS", "049000555", 299)), "BF", ("TRASH BAGS", "011111065", 799), "T"),
         ("RIVERSIDE MARKET", "7.75000", (("CEREAL", "016000275", 479), ("PEANUT BUTTER", "051500255", 559)), "BF", ("SPONGES", "026200081", 349), "T"),
         ("MAPLE STREET GROCER", "6.50000", (("EGGS 12", "070330001", 389), ("BUTTER", "034500332", 599)), "FB", ("SHOWER CURTAIN", "083100044", 1599), "T"),
         ("HILLTOP FOODS", "5.00000", (("TOMATO SOUP", "051000012", 189), ("CRACKERS", "044000032", 429)), "B", ("BATTERIES", "041333420", 1299), "T"),
         ("NORTHGATE MARKET", "7.25000", (("COFFEE", "072250001", 899), ("TEA BAGS", "041570054", 479)), "BF", ("CANDLES", "075190007", 699), "T"),
         ("LAKESIDE GROCERY", "8.00000", (("FROZEN PEAS", "014100085", 249), ("WAFFLES", "038000221", 449)), "BF", ("MOP HEAD", "046500702", 1199), "T"),
         ("ORCHARD MARKET", "6.25000", (("APPLE JUICE", "074890001", 519), ("PRETZELS", "028400090", 369)), "FB", ("LAUNDRY BAG", "081200330", 849), "T")]


def dollars(cents):
    return as_decimal_text(cents, "USD")


def tax_on(cents, rate):
    """A tax line's amount: the rate on the taxable amount, rounded half up to the cent."""
    return int((Decimal(cents) * Decimal(rate) / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def shop(merchant, rate, groceries, code, other, other_code):
    """(lines with a tax line per code, lines with one TAX line, the amounts by tax line code, the items' product codes and line codes)."""
    first, second = groceries
    on_b, on_t = first[2] + second[2], other[2]
    tax_b, tax_t = tax_on(on_b, rate), tax_on(on_t, rate)
    head = [merchant, "2026-09-20", "GROCERY", f"{first[1]} {first[0]} {code} ${dollars(first[2])}", f"{second[1]} {second[0]} {code} ${dollars(second[2])}",
            "HOUSEHOLD", f"{other[1]} {other[0]} {other_code} ${dollars(other[2])}", f"SUBTOTAL ${dollars(on_b + on_t)}"]
    total = f"TOTAL ${dollars(on_b + on_t + tax_b + tax_t)}"
    lines = [*head, f"T = GA TAX {rate} on ${dollars(on_t)} ${dollars(tax_t)}", f"B = GA TAX {rate} on ${dollars(on_b)} ${dollars(tax_b)}", total]
    one = [*head, f"TAX ${dollars(tax_b + tax_t)}", total]
    items = [(first[1], "B"), (second[1], "B"), (other[1], "T")]
    return lines, one, {"T": dollars(tax_t), "B": dollars(tax_b)}, items


def cases():
    out = [make_case(NAME, {"lines": R}, {"mode": "tax_lines", "tax_lines": R_TAX_LINES, "items": R_ITEMS}, ["tax_lines", "fixture"]),
           make_case(NAME, {"lines": R_ONE_TAX_LINE}, {"mode": "one_tax_line", "items": R_ITEMS}, ["one_tax_line", "fixture"])]
    for row in SHOPS:
        lines, one, amounts, items = shop(*row)
        out.append(make_case(NAME, {"lines": lines}, {"mode": "tax_lines", "tax_lines": amounts, "items": items}, ["tax_lines"]))
        out.append(make_case(NAME, {"lines": one}, {"mode": "one_tax_line", "items": items}, ["one_tax_line"]))
    return out


def run(case, config, work):
    lines, notes = text_lines(case["input"]["lines"]), []
    classification, header, rows, _, kind = reader().extract(config, work, lines, notes)
    if classification.document_type != "receipt" or header is None:
        return {"tax_lines": [], "items": []}
    record, _ = normalize("receipt", header, rows, "USD", lines, receipt_kind=kind)
    return {"tax_lines": [{"code": line["code"], "amount": dollars(line["amount_minor"]) if line["amount_minor"] is not None else None}
                          for line in record.get("tax_lines", [])],
            "items": [{"product_code": item["product_code"], "tax_code": item["tax_code"], "taxed": item["taxed"]} for item in record["items"]]}


def within_a_cent(amount, want):
    return amount is not None and abs(Decimal(amount) - Decimal(want)) <= Decimal("0.01")


def grade(case, output):
    expected = case["expected"]
    read = {item["product_code"]: item for item in output["items"]}
    checks = {"items_expected": len(expected["items"])}
    checks["items_read"] = sum(1 for product, _ in expected["items"] if product in read)
    if expected["mode"] == "tax_lines":
        printed = expected["tax_lines"]
        checks["lines_expected"] = len(printed)
        checks["lines_right"] = sum(1 for code, want in printed.items()
                                    if any(line["code"] == code and within_a_cent(line["amount"], want) for line in output["tax_lines"]))
        checks["codes_right"] = sum(1 for product, code in expected["items"] if code in (read.get(product, {}).get("tax_code") or ""))
        checks["all_lines"] = checks["lines_right"] == len(printed)
        checks["all_codes"] = checks["codes_right"] == len(expected["items"])
        total = len(printed) + len(expected["items"])
        checks["share"] = round((checks["lines_right"] + checks["codes_right"]) / total, 4)
        return result(checks, ["all_lines", "all_codes"], ["share"])
    # One TAX line: the BF items are the ones whose line code is B. Reading one as taxed false is the bug (FR-24).
    checks["bf_expected"] = sum(1 for _, code in expected["items"] if code == "B")
    checks["bf_untaxed"] = sum(1 for product, code in expected["items"] if code == "B" and read.get(product, {}).get("taxed") is False)
    checks["all_read"] = checks["items_read"] == len(expected["items"])
    checks["none_untaxed"] = checks["bf_untaxed"] == 0
    checks["share"] = round(1 - checks["bf_untaxed"] / checks["bf_expected"], 4)
    return result(checks, ["all_read", "none_untaxed"], ["share"])


def report_lines(rows_by_candidate):
    """Per candidate: the tax lines and item codes right on receipts with a tax line per code, and the BF items read as taxed false
    on receipts with one TAX line (the target is 0)."""
    lines = ["", "| Candidate | Receipts with tax lines | Tax lines right | Item codes right | One TAX line | BF items read untaxed |",
             "|---|---|---|---|---|---|"]
    for candidate, rows in rows_by_candidate.items():
        ok = [row for row in rows if row["status"] == "ok"]
        coded = [row["grades"]["checks"] for row in ok if "tax_lines" in row["tags"]]
        single = [row["grades"]["checks"] for row in ok if "one_tax_line" in row["tags"]]
        if not coded and not single:
            continue
        lines.append(f"| {candidate} | {len(coded)} | {sum(check['lines_right'] for check in coded)} of {sum(check['lines_expected'] for check in coded)} | "
                     f"{sum(check['codes_right'] for check in coded)} of {sum(check['items_expected'] for check in coded)} | {len(single)} | "
                     f"{sum(check['bf_untaxed'] for check in single)} of {sum(check['bf_expected'] for check in single)} |")
    return lines
