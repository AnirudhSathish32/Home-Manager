"""Receipt kinds (docs/evals.md; specs/document-forms SC-17): the kind a receipt is read as, and its kind's printed fields.

Each case is a made-up receipt of one kind (fuel, dining, grocery or general). The app reads it as it records any
receipt (ExtractionService.extract: classify, choose the kind, its form, its rows) and checks it in code (normalize).
Graded on the kind chosen and on each of the kind's printed fields: present, and equal to what is printed.
"""

from types import SimpleNamespace

from home_manager.core.money import as_decimal_text
from home_manager.documents.extraction import EXTRACTION_VERSION, ExtractionService, normalize

from .common import make_case, result, text_lines

NAME, ROLE, VERSION, PROMPT_VERSION = "receipt_kinds", "reasoning", "receipt-kinds-v1", EXTRACTION_VERSION
KINDS = ("fuel", "dining", "grocery", "general")

# The first receipt of each kind is the spec's own fixture (tests/document_forms_fixtures.py prints the same lines).
FUEL = ["SYNTH FUEL #12", "2026-10-01", "PUMP 17", "REG UNL 10.312 GAL @ 3.459", "FUEL SALE 35.67", "COFFEE 2.19", "TOTAL 37.86", "VISA ****4242"]
DINING = ["SYNTH BISTRO", "2026-10-02", "SERVER: SAM TABLE 9 GUESTS 4", "PASTA 30.00", "SALAD 20.00", "SUBTOTAL 50.00", "TAX 4.00",
          "GRATUITY 18% INCLUDED 9.00", "TIP ______", "TOTAL 63.00"]
GROCERY = ["SYNTH MARKET", "2026-10-03", "MILK 3.49", "BANANAS 2.31 lb @ 0.59/lb 1.36", "2x CHIPS @ 2.00 4.00", "BOTTLE DEPOSIT 0.10",
           "BAG FEE 0.10", "MEMBER SAVINGS -0.50", "SUBTOTAL 8.55", "TAX 0.00", "TOTAL 8.55", "GIFT CARD 6006491234565555 -5.00",
           "EBT SNAP 3.55"]
GENERAL = ["SYNTH HARDWARE", "2026-10-04", "HAMMER 12.00", "NAILS 3.00", "SUBTOTAL 15.00", "TAX 1.20", "TOTAL 16.20", "VISA ****4242"]

# More of each kind: (station, pump, grade, gallons, price, fuel amount); (restaurant, guests, subtotal, tax, gratuity, total).
STATIONS = [("NORTHGATE GAS", "4", "PREMIUM", "8.500", "4.199", "35.69"), ("HILLTOP FUEL", "9", "DIESEL", "15.020", "3.899", "58.56"),
            ("RIVER ROAD GAS", "2", "REG UNL", "11.111", "3.299", "36.65"), ("MESA STATION", "11", "MIDGRADE", "6.250", "3.789", "23.68")]
DINERS = [("THE CORNER TABLE", "2", "40.00", "3.20", "7.20", "50.40"), ("HARBOR GRILL", "6", "120.00", "9.60", "21.60", "151.20"),
          ("BLUE PLATE DINER", "3", "33.00", "2.64", "5.94", "41.58"), ("NOODLE HOUSE", "5", "75.00", "6.00", "13.50", "94.50")]
MARKETS = [("GREEN LEAF GROCERY", "-1.25"), ("VALLEY MARKET", "-0.75"), ("FRESH FIELDS", "-2.00"), ("CITY FOODS", "-0.40")]
SHOPS = [("PAGE TURNER BOOKS", "NOTEBOOK", "8.99"), ("METRO ELECTRONICS", "USB-C CABLE", "14.99"), ("NORTHSIDE PHARMACY", "VITAMIN D", "8.99"),
         ("HOME GOODS PLUS", "TOWELS", "19.99")]


def fuel_case(station, pump, grade, gallons, price, amount):
    lines = [station, "2026-09-12", f"PUMP {pump}", f"{grade} {gallons} GAL @ {price}", f"FUEL SALE {amount}", f"TOTAL {amount}", "VISA ****4242"]
    return lines, {"kind": "fuel", "fields": {"volume": gallons, "price_per_unit": price, "fuel_amount": amount, "pump_number": pump, "fuel_grade": grade}}


def dining_case(name, guests, subtotal, tax, gratuity, total):
    lines = [name, "2026-09-14", f"TABLE 12 GUESTS {guests}", f"FOOD {subtotal}", f"SUBTOTAL {subtotal}", f"TAX {tax}",
             f"SERVICE CHARGE 18% INCLUDED {gratuity}", "TIP ______", f"TOTAL {total}"]
    return lines, {"kind": "dining", "fields": {"gratuity": gratuity, "party_size": guests, "tip": None}}


def grocery_case(name, savings):
    lines = [name, "2026-09-15", "APPLES 3.00 lb @ 1.50/lb 4.50", "BREAD 3.50", f"MEMBER SAVINGS {savings}", "SUBTOTAL "
             + as_decimal_text(450 + 350 + int(round(float(savings) * 100)), "USD"), "TAX 0.00",
             "TOTAL " + as_decimal_text(450 + 350 + int(round(float(savings) * 100)), "USD"), "VISA ****4242"]
    return lines, {"kind": "grocery", "fields": {"savings_total": savings}}


def cases():
    out = [make_case(NAME, {"lines": FUEL}, {"kind": "fuel", "fields": {"volume": "10.312", "price_per_unit": "3.459", "fuel_amount": "35.67",
                                                                        "pump_number": "17", "fuel_grade": "REG UNL"}}, ["fuel", "fixture"]),
           make_case(NAME, {"lines": DINING}, {"kind": "dining", "fields": {"gratuity": "9.00", "party_size": "4", "tip": None}}, ["dining", "fixture"]),
           make_case(NAME, {"lines": GROCERY}, {"kind": "grocery", "fields": {"savings_total": "-0.50", "gift_card": "5.00"}}, ["grocery", "fixture"]),
           make_case(NAME, {"lines": GENERAL}, {"kind": "general", "fields": {}}, ["general", "fixture"])]
    for builder, rows, kind in ((fuel_case, STATIONS, "fuel"), (dining_case, DINERS, "dining"), (grocery_case, MARKETS, "grocery")):
        for row in rows:
            lines, expected = builder(*row)
            out.append(make_case(NAME, {"lines": lines}, expected, [kind]))
    for name, item, price in SHOPS:
        out.append(make_case(NAME, {"lines": [name, "2026-09-16", f"{item} {price}", f"SUBTOTAL {price}", "TAX 0.00", f"TOTAL {price}", "VISA ****4242"]},
                             {"kind": "general", "fields": {}}, ["general"]))
    return out


def reader():
    """The app's extraction service without a library: reading a receipt asks nothing of the store."""
    service = ExtractionService.__new__(ExtractionService)
    service.store = SimpleNamespace(library=SimpleNamespace(employers=list))
    return service


def shown(detail):
    """A stored detail as compared: its printed text, or its amount as decimal text."""
    if not detail:
        return None
    return detail["text"] if detail.get("minor") is None else as_decimal_text(detail["minor"], "USD")


def run(case, config, work):
    lines, notes = text_lines(case["input"]["lines"]), []
    classification, header, rows, _, kind = reader().extract(config, work, lines, notes)
    if classification.document_type != "receipt" or header is None:
        return {"kind": None, "fields": {}}
    record, _ = normalize("receipt", header, rows, "USD", lines, receipt_kind=kind)
    details = record.get("details") or {}
    fields = {name: shown(detail) for name, detail in details.items() if isinstance(detail, dict)}
    fields["tip"] = as_decimal_text(record["tip_minor"], "USD") if record.get("tip_minor") is not None else None
    gifts = [tender for tender in details.get("tenders", []) if tender["tender_type"] == "gift_card" and tender["minor"] is not None]
    if gifts:
        fields["gift_card"] = as_decimal_text(gifts[0]["minor"], "USD")
    return {"kind": kind, "fields": fields}


def grade(case, output):
    expected = case["expected"]
    checks = {"kind": output["kind"] == expected["kind"]}
    printed = {name: want for name, want in expected["fields"].items() if want is not None}
    checks["fields_present"] = sum(1 for name in printed if output["fields"].get(name) is not None)
    checks["fields_correct"] = sum(1 for name, want in printed.items() if output["fields"].get(name) == want)
    checks["fields_printed"] = len(printed)
    checks["invented"] = sum(1 for name, want in expected["fields"].items() if want is None and output["fields"].get(name) is not None)
    checks["all_fields"] = checks["fields_correct"] == len(printed) and not checks["invented"]
    checks["field_share"] = round(checks["fields_correct"] / len(printed), 4) if printed else 1.0
    return result(checks, ["kind", "all_fields"], ["kind", "field_share"])


def report_lines(rows_by_candidate):
    """Kind accuracy per receipt kind, and printed fields present and correct, per candidate."""
    lines = ["", "| Candidate | Kind | Kind right | Fields present | Fields right | Invented |", "|---|---|---|---|---|---|"]
    for candidate, rows in rows_by_candidate.items():
        for kind in KINDS:
            mine = [row for row in rows if kind in row["tags"] and row["status"] == "ok"]
            if not mine:
                continue
            checks = [row["grades"]["checks"] for row in mine]
            lines.append(f"| {candidate} | {kind} | {sum(bool(check['kind']) for check in checks)} of {len(checks)} | "
                         f"{sum(check['fields_present'] for check in checks)} of {sum(check['fields_printed'] for check in checks)} | "
                         f"{sum(check['fields_correct'] for check in checks)} of {sum(check['fields_printed'] for check in checks)} | "
                         f"{sum(check['invented'] for check in checks)} |")
    return lines
