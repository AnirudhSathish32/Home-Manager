"""Warranty lookup (eval_plan.md task 14, household/warranty.py): the manufacturer's stated warranty for an owned item,
found with web search over recorded pages and quoted exactly.

Graded on the proposal: its length in months (or lifetime) and kind. Pages hold traps: another model's warranty, an
accessory's shorter cover, an extended plan for sale. When no page states the warranty, the right outcome is none.
"""

from home_manager.household.warranty import WARRANTY_VERSION, Warranties, WarrantyService

from .common import make_case, result
from .web import html, lookup, owned, scratch_store

NAME, ROLE, VERSION, PROMPT_VERSION, MULTI_STEP = "warranty", "reasoning", "warranty-v1", WARRANTY_VERSION, True
# (product name, brand, printed line, [(title, url, snippet, paragraphs)], (months, lifetime) or None)
ITEMS = [
    ("Acme Book 14", "Acme", "ACME BK14",
     [("Acme Book 14 warranty | Acme Support", "https://support.acme.example/book-14/warranty", "Warranty for Acme Book 14",
       ["Every Acme Book 14 includes a one-year limited warranty covering parts and labor.", "Extended plans are sold separately."])], (12, False)),
    ("Brightline 55 inch TV", "Brightline", "BRTLN 55 TV",
     [("Brightline TV warranty", "https://www.brightline.example/support/warranty", "TV warranty terms",
       ["Brightline televisions carry a 2-year limited warranty from the date of purchase."])], (24, False)),
    ("Northwind Pro Blender", "Northwind", "NW PRO BLNDR",
     [("Northwind Pro Blender - Warranty", "https://www.northwind.example/pro-blender/warranty", "Blender warranty",
       ["The Northwind Pro Blender is backed by a 7-year limited warranty on the motor base and container."]),
      ("Northwind Toaster - Warranty", "https://www.northwind.example/toaster/warranty", "Toaster warranty",
       ["The Northwind Toaster has a 1-year limited warranty."])], (84, False)),
    ("Summit Cast Iron Skillet", "Summit", "SUMMIT CI SKLT",
     [("Summit Cookware guarantee", "https://www.summitcookware.example/guarantee", "Our guarantee",
       ["Summit cast iron is covered by a limited lifetime warranty against defects in material and workmanship."])], (None, True)),
    ("Volt 20V Drill", "Volt", "VOLT 20V DRL",
     [("Volt Tools warranty", "https://www.volttools.example/warranty", "Tool and battery warranty",
       ["Volt 20V power tools carry a 3-year limited tool warranty.", "Batteries and chargers are covered by a 90-day warranty."])], (36, False)),
    ("Cascade Electric Kettle", "Cascade", "CASCADE KETTLE",
     [("Cascade Kettle support", "https://www.cascade.example/kettle", "Kettle care and warranty",
       ["Warranty: Cascade kettles are guaranteed for 90 days from purchase."])], (3, False)),
    ("Echo Wireless Headphones", "Echo Audio", "ECHO WL HDPHN",
     [("Echo Audio warranty", "https://www.echoaudio.example/warranty", "Product warranty",
       ["This product comes with a 1 year limited warranty."]),
      ("ProtectPlus for headphones", "https://www.protectplus.example/headphones", "Buy extended protection",
       ["Get 3 years of protection with a ProtectPlus extended warranty plan, sold separately."])], (12, False)),
    ("Restwell Hybrid Mattress", "Restwell", "RESTWELL HYB QN",
     [("Restwell mattress warranty", "https://www.restwell.example/warranty", "Mattress warranty",
       ["Every Restwell mattress includes a 10-year limited warranty."])], (120, False)),
    ("Brewmaster Coffee Maker", "Brewmaster", "BREWMSTR CM12",
     [("Brewmaster CM12 product page", "https://www.brewmaster.example/cm12", "12-cup coffee maker",
       ["The CM12 brews 12 cups with a programmable timer.", "Dishwasher-safe carafe."])], None),
    ("Ergo Task Chair", "Ergo", "ERGO TASK CHR",
     [("Ergo chair warranty", "https://www.ergoseating.example/warranty", "Seating warranty",
       ["Ergo task chairs are covered by a 12-year warranty for everyday use."])], (144, False)),
    ("Linkway AX3000 Router", "Linkway", "LNKWY AX3000",
     [("Linkway AX3000 support", "https://www.linkway.example/ax3000/support", "Router support",
       ["Linkway AX3000 routers include a two-year limited warranty."])], (24, False)),
    ("Lumen Z5 Camera", "Lumen", "LUMEN Z5 CAM",
     [("Lumen Z7 camera warranty", "https://www.lumen.example/z7/warranty", "Z7 warranty",
       ["The Lumen Z7 is covered by a 2-year limited warranty."]),
      ("Lumen Z5 camera warranty", "https://www.lumen.example/z5/warranty", "Z5 warranty",
       ["The Lumen Z5 is covered by a one-year limited warranty."])], (12, False)),
]


def cases():
    out = []
    for name, brand, printed, results, expected in ITEMS:
        web = {"results": [{"title": title, "url": url, "description": snippet} for title, url, snippet, _ in results],
               "pages": {url: html(title, *paragraphs) for title, url, _, paragraphs in results}}
        out.append(make_case(NAME, {"name": name, "brand": brand, "printed": printed, "web": web},
                             {"months": expected[0] if expected else None, "lifetime": expected[1] if expected else None, "none": expected is None},
                             ["none_stated"] if expected is None else []))
    return out


def run(case, config, work):
    given = case["input"]
    with scratch_store() as store:
        lot_id = owned(store, "Best Buy", given["printed"], 49999,
                       {"name": given["name"], "brand": given["brand"], "category": "other", "consumable": False})
        outcome = WarrantyService(store, lookup(store, given["web"])).agent(lot_id, config, work, "eval")
        warranty = Warranties(store).get(outcome["warranty_id"]) if outcome.get("warranty_id") else None
    return {"warranty": {key: warranty[key] for key in ("kind", "months", "lifetime", "quote", "source_url")} if warranty else None,
            "note": outcome.get("note"), "tool_calls": outcome.get("tool_calls")}


def grade(case, output):
    want, got = case["expected"], output["warranty"]
    if want["none"]:
        return result({"no_proposal": got is None}, ["no_proposal"])
    if got is None:
        return result({"proposed": False}, ["proposed"])
    checks = {"proposed": True, "length": got["lifetime"] == want["lifetime"] and got["months"] == want["months"],
              "manufacturer": got["kind"] == "manufacturer"}
    return result(checks, ["length", "manufacturer"])
