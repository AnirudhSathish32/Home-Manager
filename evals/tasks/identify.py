"""Identify (eval_plan.md task 5): who sold a purchase and where, read from a receipt's lines.

The location is the street name only ('1450 Oak Ridge Rd, Springfield' gives 'Oak Ridge Rd'), Online for an order
shipped or delivered, and missing when no street is printed. A seller printed only in a footer or web address counts.
"""

from home_manager.documents.extraction import EXTRACTION_VERSION, ExtractionService

from .common import make_case, names_match, normal, result, text_lines

NAME, ROLE, VERSION, PROMPT_VERSION = "identify", "reasoning", "identify-v1", EXTRACTION_VERSION
STORES = [("HILLSIDE HARDWARE", "Hillside Hardware", "1450 Oak Ridge Rd", "Oak Ridge Rd", "Springfield, IL 62704"),
          ("GREEN LEAF GROCERY", "Green Leaf Grocery", "22 Maple Ave", "Maple Ave", "Portland, OR 97205"),
          ("CORNER COFFEE", "Corner Coffee", "310 Harbor Blvd", "Harbor Blvd", "Tacoma, WA 98402"),
          ("NORTHSIDE PHARMACY", "Northside Pharmacy", "7 Elm St", "Elm St", "Dayton, OH 45402"),
          ("METRO ELECTRONICS", "Metro Electronics", "900 Commerce Pkwy", "Commerce Pkwy", "Plano, TX 75024"),
          ("PAGE TURNER BOOKS", "Page Turner Books", "41 College St", "College St", "Burlington, VT 05401"),
          ("BLUE PLATE DINER", "Blue Plate Diner", "1200 Route 9 N", "Route 9 N", "Albany, NY 12205"),
          ("SUNRISE BAKERY", "Sunrise Bakery", "88 King St W", "King St W", "Toronto, ON M5H 1J9")]
ITEMS = ["ITEM A 4.99", "ITEM B 12.50", "Subtotal 17.49", "Tax 1.40", "Total 18.89", "VISA ****4242"]


def receipt(header, footer=()):
    return [*header, "2026-08-14", *ITEMS, *footer]


def cases():
    out = []
    for printed, name, street, street_name, city in STORES:  # Name and street address printed at the top.
        out.append(make_case(NAME, {"lines": receipt([printed, f"{street}, {city}"])}, {"seller": name, "location": street_name}, ["printed"]))
    for _, name, _, _, city in STORES[:4]:  # Only the city at the top; the name is in the survey web address.
        domain = name.lower().replace(" ", "")
        out.append(make_case(NAME, {"lines": receipt([f"STORE #0{len(name)}", city.split(",")[0].upper()],
                                                     [f"Tell us how we did at survey.{domain}.com"])},
                             {"seller": name, "location": None}, ["footer_name", "no_street"]))
    for printed, name, _, _, _ in STORES[4:]:  # Online orders: the address printed is the customer's, not the store's.
        out.append(make_case(NAME, {"lines": receipt([printed, "Order #W58213", "Estimated delivery 2026-08-18"],
                                                     ["Ship to: 12 Willow Ln, Dayton, OH 45402"])},
                             {"seller": name, "location": "Online"}, ["online"]))
    for printed, name, _, _, city in STORES[:4]:  # Name but no street: the city is never a location.
        out.append(make_case(NAME, {"lines": receipt([printed, city])}, {"seller": name, "location": None}, ["no_street"]))
    return out


def run(case, config, work):
    found = ExtractionService.identify(config, work, text_lines(case["input"]["lines"]))
    return {"seller": found["seller"].value if found["seller"] else None, "inferred": found["inferred_from"] is not None, "location": found["location"]}


def grade(case, output):
    expected = case["expected"]
    checks = {"seller": names_match(expected["seller"], output["seller"]),
              "location": normal(expected["location"]) == normal(output["location"]) if expected["location"] or output["location"] else True}
    return result(checks, ["seller", "location"])
