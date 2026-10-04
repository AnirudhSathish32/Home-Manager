"""Item lookup (docs/evals.md, task 14, household/resolver.py): the full product behind an abbreviated receipt line,
found with web search over recorded pages.

Graded on the proposal the agent sends for review: the product's name words, brand, category and whether it runs out.
For a line no page explains, the right outcome is no proposal: a wrong name is worse than none.
"""

from home_manager.household.items import ItemLedger
from home_manager.household.resolver import RESOLVER_VERSION, ItemResolver

from .common import make_case, names_match, normal, result
from .web import bought, html, lookup, scratch_store

NAME, ROLE, VERSION, PROMPT_VERSION, MULTI_STEP = "item_lookup", "reasoning", "item-lookup-v1", RESOLVER_VERSION, True
# (merchant, printed line, [(result title, url, snippet, page paragraphs)], expected or None)
LINES = [
    ("Walmart", "GV WHL MLK 1GL",
     [("Great Value Whole Milk, 1 Gallon - Walmart.com", "https://www.walmart.example/ip/gv-whole-milk-1gal", "Great Value Whole Vitamin D Milk, 1 gal",
       ["Great Value Whole Vitamin D Milk, 1 Gallon", "Brand: Great Value", "Grade A pasteurized whole milk."]),
      ("Great Value 2% Reduced Fat Milk, Half Gallon", "https://www.walmart.example/ip/gv-2pct-milk-hg", "Great Value 2% milk, 64 fl oz",
       ["Great Value 2% Reduced Fat Milk, Half Gallon", "Brand: Great Value"])],
     {"words": ["great value", "whole", "milk"], "brand": "Great Value", "category": ["dairy & eggs", "beverages"], "consumable": True}),
    ("Target", "UP&UP PPR TWL 6RL",
     [("up & up Paper Towels, 6 Double Rolls - Target", "https://www.target.example/p/up-up-paper-towels-6", "Paper towels from up & up, 6 rolls",
       ["up & up Make-A-Size Paper Towels, 6 Double Rolls", "Brand: up & up"])],
     {"words": ["paper towels"], "brand": "up & up", "category": ["paper & disposables", "household cleaning"], "consumable": True}),
    ("Costco", "KS BATH TISSUE 30",
     [("Kirkland Signature Bath Tissue, 30 Rolls | Costco", "https://www.costco.example/kirkland-bath-tissue-30", "2-ply bath tissue, 30 rolls",
       ["Kirkland Signature 2-Ply Bath Tissue, 30 Rolls", "Brand: Kirkland Signature"])],
     {"words": ["bath tissue"], "brand": "Kirkland Signature", "category": ["paper & disposables"], "consumable": True}),
    ("The Home Depot", "HDX 33GAL TRSH BG",
     [("HDX 33 Gallon Black Trash Bags (40-Count) - The Home Depot", "https://www.homedepot.example/p/hdx-33-gal-trash-bags", "HDX contractor bags",
       ["HDX 33 Gal. Black Trash Bags (40-Count)", "Brand: HDX"])],
     {"words": ["trash bags"], "brand": "HDX", "category": ["paper & disposables", "household cleaning"], "consumable": True}),
    ("Walmart", "GV LG EGGS 18CT",
     [("Great Value Large White Eggs, 18 Count", "https://www.walmart.example/ip/gv-large-eggs-18", "Grade A large eggs",
       ["Great Value Large White Eggs, 18 Count", "Brand: Great Value"])],
     {"words": ["eggs"], "brand": "Great Value", "category": ["dairy & eggs"], "consumable": True}),
    ("Target", "GG ORG BNNA",
     [("Organic Bananas - 2lb - Good & Gather - Target", "https://www.target.example/p/gg-organic-bananas", "Good & Gather organic bananas",
       ["Organic Bananas, about 2 lb", "Brand: Good & Gather"])],
     {"words": ["banana"], "brand": "Good & Gather", "category": ["produce"], "consumable": True}),
    ("Best Buy", "INS 55IN 4K TV",
     [("Insignia 55\" Class F30 Series LED 4K UHD Fire TV - Best Buy", "https://www.bestbuy.example/site/insignia-55-4k", "Insignia 55-inch 4K TV",
       ["Insignia 55-inch Class F30 Series LED 4K UHD Smart Fire TV", "Brand: Insignia"])],
     {"words": ["55", "tv"], "brand": "Insignia", "category": ["other", "home maintenance"], "consumable": False}),
    ("Kroger", "KRO 2% MLK HG",
     [("Kroger 2% Reduced Fat Milk, Half Gallon", "https://www.kroger.example/p/kroger-2-milk-hg", "Kroger brand 2% milk",
       ["Kroger 2% Reduced Fat Milk, 64 fl oz", "Brand: Kroger"])],
     {"words": ["2", "milk"], "brand": "Kroger", "category": ["dairy & eggs", "beverages"], "consumable": True}),
    ("CVS", "CVS IBU 200MG 100CT",
     [("CVS Health Ibuprofen 200mg Tablets, 100 CT", "https://www.cvs.example/shop/cvs-ibuprofen-200mg-100", "Pain reliever / fever reducer",
       ["CVS Health Ibuprofen Tablets 200 mg, 100 count", "Brand: CVS Health"])],
     {"words": ["ibuprofen"], "brand": "CVS Health", "category": ["health"], "consumable": True}),
    ("Lowe's", "VALS ULTRA INT EGSH GL",
     [("Valspar Ultra Interior Paint, Eggshell, 1 Gallon - Lowe's", "https://www.lowes.example/pd/valspar-ultra-eggshell-1gal", "Valspar interior paint",
       ["Valspar Ultra Interior Paint + Primer, Eggshell, 1 Gallon", "Brand: Valspar"])],
     {"words": ["paint"], "brand": "Valspar", "category": ["home maintenance"], "consumable": None}),
    ("Walmart", "XQ MISC 7",
     [("Walmart Weekly Ad", "https://www.walmart.example/weekly-ad", "This week's savings", ["Save on groceries this week."])], None),
    ("Target", "MKT ITEM 22",
     [("Market Pantry Tomato Soup", "https://www.target.example/p/mp-tomato-soup", "Canned soup", ["Market Pantry Tomato Soup, 10.75 oz"]),
      ("Market Pantry Pasta Sauce", "https://www.target.example/p/mp-pasta-sauce", "Jarred sauce", ["Market Pantry Pasta Sauce, 24 oz"])], None),
]


def cases():
    out = []
    for merchant, printed, results, expected in LINES:
        web = {"results": [{"title": title, "url": url, "description": snippet} for title, url, snippet, _ in results],
               "pages": {url: html(title, *paragraphs) for title, url, _, paragraphs in results}}
        out.append(make_case(NAME, {"merchant": merchant, "printed": printed, "web": web}, {"product": expected},
                             ["unknown"] if expected is None else []))
    return out


def run(case, config, work):
    given = case["input"]
    with scratch_store() as store:
        line_id = bought(store, given["merchant"], given["printed"], 1999)
        resolver = ItemResolver(store, lookup(store, given["web"]))
        outcome = resolver.agent(ItemLedger(store).line(line_id), config, work, "eval")
        proposal = ItemLedger(store).resolution(outcome["proposal_id"]) if outcome.get("proposal_id") else None
    return {"proposal": {key: proposal[key] for key in ("name", "brand", "size_text", "category", "consumable", "confidence")} if proposal else None,
            "note": outcome.get("note"), "tool_calls": outcome.get("tool_calls")}


def grade(case, output):
    want, got = case["expected"]["product"], output["proposal"]
    if want is None:
        return result({"no_proposal": got is None}, ["no_proposal"])
    if got is None:
        return result({"proposed": False}, ["proposed"])
    name = normal(got["name"])
    checks = {"proposed": True, "name": all(normal(word) in name for word in want["words"]), "brand": names_match(want["brand"], got["brand"] or ""),
              "category": got["category"] in want["category"], "consumable": want["consumable"] is None or got["consumable"] == want["consumable"]}
    return result(checks, ["name", "category", "consumable"], ["name", "brand", "category", "consumable"])
