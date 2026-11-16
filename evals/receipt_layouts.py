"""A seeded generator of drawn receipts with known layouts (specs/receipt-layout-eval FR-01 – FR-06, SC-13; plan P7).

  receipt = make(family, condition, index)       # the same three values always give the same Receipt
  image, boxes = draw(receipt)                   # a PIL image and, per row, each cell's box in that image
  answer = answers(receipt, boxes, image.size)   # rows, cells, indent, alignment, handwriting, amounts, boxes

A `Receipt` is printed rows: each `Row` has cells (text, where it sits: left, center or right, and a handwritten flag) and an indent of 0, 1 or 2.
Everything the answers say comes from these inputs and from the drawing's own transform, never from a reader. Contents are invented: every
merchant, address, phone (the fictional 555-01xx range) and name; every number of six digits or more starts with `0000` (FR-06). The `dining`
case 0 keeps the items, amounts and layout of the fixture in tests/dining_receipt_fixtures.py, with its order number and server replaced.

Fonts are committed under evals/fonts and checked against `FONTS` before use; every font is loaded with the basic layout engine, so a computer
with or without libraqm lays text out the same way (plan P7, "Cross-computer drawing").
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
import functools
import hashlib
import io
from pathlib import Path
import random
import re

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_DIR = Path(__file__).with_name("fonts")
FONTS = {
    "LiberationMono-Regular.ttf": "395fa5ab8d40c8eba390ced528744ea75a7f69aabf3e68b6f925ca0e39a27370",
    "LiberationSans-Regular.ttf": "4659bc0c58c5028dd488ec928d41d9265db43d9b669fc14ca8b0832daca7b144",
    "Caveat-VariableFont_wght.ttf": "0bdb6b660482d31531b3945849fba5916b3ef8695da7024a9e6b9ee3c4157988",
}
HAND_FONT, HAND_SIZE, HAND_INK = "Caveat-VariableFont_wght.ttf", 34, (20, 30, 120)

FAMILIES = ("grocery", "dining", "fuel", "terminal", "itemized", "long", "ereceipt", "return")
CONDITIONS = ("clean", "faded", "tilted", "angled", "blurred", "small_text", "background")
CASES = (
    *[("grocery", condition, index) for index, condition in enumerate(("clean", "faded", "tilted", "angled"))],
    *[("dining", condition, index) for index, condition in enumerate(("clean", "faded", "tilted", "angled", "blurred", "background"))],
    *[("fuel", condition, index) for index, condition in enumerate(("clean", "blurred"))],
    *[("terminal", condition, index) for index, condition in enumerate(("clean", "tilted"))],
    *[("itemized", condition, index) for index, condition in enumerate(("clean", "angled"))],
    *[("long", condition, index) for index, condition in enumerate(("clean", "small_text", "small_text", "faded"))],
    *[("ereceipt", condition, index) for index, condition in enumerate(("clean", "background"))],
    *[("return", condition, index) for index, condition in enumerate(("clean", "blurred"))],
)

TILT, SMALL, BLUR, BACKGROUND_PAD, BACKGROUND_INK, INSET = 2.5, 0.45, 1.2, 60, (70, 70, 76), 0.05
REFERENCE = "Hgjpqy|"  # Every cell of a font gets at least this box height, so boxes of one row line up.
GAP = 1.5  # Neighbouring printed cells are at least this many character widths apart (the row builder joins closer ones).


@dataclass
class Cell:
    text: str
    align: str = "left"        # left, center or right
    anchor: float | None = None  # x of a column: a left cell starts there, a right cell ends there, a center cell is centred on it
    handwritten: bool = False
    money: bool = False        # the cell prints one transaction amount (not a unit price or a rate)


@dataclass
class Row:
    cells: list = field(default_factory=list)  # no cells: a blank line
    indent: int = 0
    kind: str = ""


@dataclass
class Receipt:
    family: str
    condition: str
    index: int
    style: str                 # thermal or proportional
    rows: list
    checks: list = field(default_factory=list)  # ("sum", parts, total) or ("product", a, b, total, divisor), in minor units

    @property
    def key(self):
        return f"{self.family}:{self.condition}:{self.index}"

    @property
    def tags(self):
        return [self.family, self.condition]


@dataclass(frozen=True)
class Style:
    width: int
    font: str
    size: int
    pitch: int
    margin: int
    right: int
    center: int
    top: int


STYLES = {"thermal": Style(760, "LiberationMono-Regular.ttf", 26, 34, 52, 708, 380, 52),
          "proportional": Style(900, "LiberationSans-Regular.ttf", 24, 38, 60, 840, 450, 60)}


# --- Fonts ----------------------------------------------------------------------------------------------------------------------

@functools.cache
def font(name, size):
    """The committed font file, checked against FONTS, laid out by the basic engine."""
    path = FONT_DIR / name
    found = hashlib.sha256(path.read_bytes()).hexdigest()
    if found != FONTS[name]:
        raise RuntimeError(f"{name} is not the font this generator was written for (sha256 {found})")
    return ImageFont.truetype(str(path), size, layout_engine=ImageFont.Layout.BASIC)


def text_font(receipt):
    style = STYLES[receipt.style]
    return font(style.font, style.size)


def hand_font():
    return font(HAND_FONT, HAND_SIZE)


def advance(style_name):
    """One character's width: the thermal font is monospaced, the proportional one is measured on a digit."""
    style = STYLES[style_name]
    return font(style.font, style.size).getlength("0")


def indent_step(style_name):
    return 2 * advance(style_name)


def end_of(text, indent=0, style="thermal"):
    """Where a thermal left cell of this text, at this indent, ends."""
    return STYLES[style].margin + indent * indent_step(style) + font(STYLES[style].font, STYLES[style].size).getlength(text)


# --- Money ----------------------------------------------------------------------------------------------------------------------

MONEY = re.compile(r"(?<![\d.,])(\()?(-)?\$?(-)?(\d{1,3}(?:,\d{3})+|\d+)\.(\d{2})(?![\d%])(-)?(\))?")


def parse_amounts(text):
    """The money amounts of a text in minor units: a number with exactly two decimals, an optional `$`, thousands commas, a leading or trailing
    minus or parentheses, not followed by `%` or a digit (plan P8)."""
    found = []
    for opened, lead, lead_after_dollar, whole, cents, trail, closed in MONEY.findall(text):
        value = int(whole.replace(",", "")) * 100 + int(cents)
        found.append(-value if (lead or lead_after_dollar or trail or (opened and closed)) else value)
    return found


def fmt(minor, dollar=False, negative="trail"):
    """An amount as printed. A negative one is `1.20-` (trail), `(1.20)` (paren) or `-1.20` (lead)."""
    text = f"{abs(minor) // 100:,}.{abs(minor) % 100:02d}"
    if dollar:
        text = "$" + text
    if minor < 0:
        return {"trail": text + "-", "paren": f"({text})", "lead": "-" + text}[negative]
    return text


# --- Rows -----------------------------------------------------------------------------------------------------------------------

def one(text, align="left", indent=0, kind=""):
    return Row([Cell(text, align)], indent, kind)


def pair(label, value, indent=0, kind="", money=False):
    return Row([Cell(label), Cell(value, "right", money=money)], indent, kind)


def gap():
    return Row()


def day_text(rng, short=True):
    day = date(2026, 1, 3) + timedelta(days=rng.randint(0, 300))
    hour, minute = rng.randint(1, 12), rng.randint(0, 59)
    return f"{day.month:02d}/{day.day:02d}/{day.year % 100:02d}, {hour}:{minute:02d} {rng.choice(('AM', 'PM'))}"


def reference(rng):
    return f"0000{rng.randint(1000, 9999)}"


def card(rng):
    return f"VISA ****{rng.choice(('1111', '2222', '4444', '7777'))}"


def header(rng, names, street_pool=("Orchard Row", "Mill Road", "Harbor Way", "Elm Court", "Cedar Lane", "Lantern St")):
    return [one(rng.choice(names), "center"), one(f"{rng.randint(10, 98)} {rng.choice(street_pool)}", "center"),
            one(f"Tel 555-01{rng.randint(10, 99)}", "center")]


def tax_of(minor, percent=8):
    return (minor * percent + 50) // 100


# --- Families -------------------------------------------------------------------------------------------------------------------

GROCERY_STORES = ("Maple Grove Market", "Corner Basket Foods", "Blue Heron Grocery", "Harvest Lane Market")
GROCERY_ITEMS = (("ORGANIC BANANAS", 199, False), ("WHOLE MILK 1 GAL", 389, False), ("SOURDOUGH LOAF", 449, False), ("EGGS LARGE 12CT", 429, False),
                 ("ROMA TOMATOES", 279, False), ("DISH SOAP", 349, True), ("PAPER TOWELS 6PK", 899, True), ("CHEDDAR BLOCK", 599, False),
                 ("GREEN APPLES", 85, False), ("BASMATI RICE 2LB", 479, False), ("OLIVE OIL 500ML", 1099, False), ("AA BATTERIES 8CT", 1049, True),
                 ("SPARKLING WATER", 129, False), ("GREEK YOGURT", 119, False), ("FROZEN PEAS", 199, False), ("TOOTHPASTE", 379, True),
                 ("PASTA SAUCE", 249, False), ("BLACK BEANS CAN", 109, False), ("CHICKEN BREAST LB", 689, False), ("BUTTER UNSALTED", 459, False),
                 ("LAUNDRY PODS", 1299, True), ("RED ONIONS", 149, False), ("CEREAL OATS", 399, False), ("COFFEE BEANS 12OZ", 1149, False),
                 ("TRASH BAGS 30CT", 849, True), ("SALMON FILLET", 1299, False), ("BABY SPINACH", 349, False), ("PEANUT BUTTER", 379, False))
SAVINGS = (("Member Savings", 40), ("Coupon", 100), ("Store Sale", 30), ("Loyalty Discount", 25))


def grocery(rng, count=None, floor=0):
    """Quantity and savings lines indented with their own prices, a tax letter after each price."""
    rows = header(rng, GROCERY_STORES)
    rows += [pair(day_text(rng), f"Lane {rng.randint(1, 8)}"), pair(f"Cashier: {rng.choice(('Sam', 'Jo', 'Pat', 'Lee'))}", f"Reg {rng.randint(1, 9)}"), gap()]
    parts, taxable, checks, count = [], 0, [], count or rng.randint(8, 13)
    while count > 0 or sum(1 for row in rows if row.cells) < floor:
        count -= 1
        name, price, tax = rng.choice(GROCERY_ITEMS)
        letter = "T" if tax else "F"
        if rng.random() < 0.3:
            qty, unit = rng.randint(2, 4), price // 2 or price
            total = qty * unit
            rows += [one(name), Row([Cell(f"{qty} @ {fmt(unit)}"), Cell(f"{fmt(total)} {letter}", "right", money=True)], 1, "item")]
            checks.append(("product", qty, unit, total, 1))
        else:
            total = price
            rows.append(pair(name, f"{fmt(total)} {letter}", kind="item", money=True))
        parts.append(total)
        taxable += total if tax else 0
        if rng.random() < 0.18:
            label, saving = rng.choice(SAVINGS)
            rows.append(Row([Cell(label), Cell(fmt(-saving), "right", money=True)], 1, "item"))
            parts.append(-saving)
    subtotal = sum(parts)
    tax = tax_of(taxable)
    total = subtotal + tax
    rows += [gap(), pair("SUBTOTAL", fmt(subtotal), kind="subtotal", money=True), pair("TAX 8.000%", fmt(tax), kind="tax", money=True),
             pair("TOTAL", fmt(total), kind="total", money=True), gap(), pair(card(rng).replace("VISA", "VISA CREDIT"), fmt(total), money=True),
             pair("Ref", reference(rng)), gap(), one("THANK YOU FOR SHOPPING", "center"), one("T = Taxable  F = Food", "center")]
    return rows, [("sum", parts, subtotal), ("sum", [subtotal, tax], total), *checks]


DINING_NAMES = ("Magnolia Breakfast Bar", "Copper Kettle Diner", "The Salted Fig", "Juniper Table", "Blue Door Brunch")
DINING_ITEMS = (("Bottled Water", 395), ("Coffee", 1495), ("Orange Juice", 450), ("Buttermilk Pancakes", 1275), ("Veggie Omelette", 1490),
                ("Avocado Toast", 1325), ("Chicken Waffles", 1795), ("Fruit Bowl", 825), ("Hash Browns", 595), ("Breakfast Burrito", 1380), ("Chai Latte", 575))
SIDES = ("No Onions", "Extra Crispy", "Add Bacon", "Gluten Free", "Dressing On Side", "Sub Fruit", "No Allergies")
SERVERS = ("Avery T", "Morgan P", "Riley K", "Quinn D")
FIXTURE_ITEMS = (("Bottled Water", 395, ()), ("Bottled Water", 395, ()), ("Coffee", 1495, ()),
                 ("Georgia Peach Stack", 1870, ("No Allergies", "Fresh Berry Pancakes", "Veggie Sausage", "Jalapeno Cheese Grits")),
                 ("Better Than No Y'all Biscuits (3)", 730, ("No Allergies",)))


def dining(rng, index):
    """The breakfast fixture's layout: unpriced side lines at indent 1, a Bill, a handwritten Tip and Total, a suggested-tip block."""
    if index == 0:
        name, street, order, server, when = "Magnolia Breakfast Bar", "14 Orchard Row", "00004217", "Avery T", "11/12/26, 10:31 AM"
        items = FIXTURE_ITEMS
    else:
        name, street, order, server, when = rng.choice(DINING_NAMES), f"{rng.randint(10, 98)} {rng.choice(('Mill Road', 'Harbor Way', 'Elm Court'))}", \
            reference(rng), rng.choice(SERVERS), day_text(rng)
        items = tuple((label, price, tuple(rng.sample(SIDES, rng.choice((0, 0, 1, 2))))) for label, price in rng.sample(DINING_ITEMS, rng.randint(4, 6)))
    subtotal = sum(price for _, price, _ in items)
    tax = tax_of(subtotal)
    bill = subtotal + tax
    tip = tax_of(subtotal, rng.choice((18, 20, 22))) if index else 879
    rows = [one(name, "center"), one(street, "center"), one(f"Order #: {order}"), one(f"Server: {server}"), one(f"Date: {when}"),
            pair("Amount:", fmt(bill, True), money=True)]
    count = 6 if index == 0 else len(items)  # the fixture prints 6 for its 5 lines
    for label, price, sides in items:
        rows.append(pair(label, fmt(price, True), kind="item", money=True))
        rows += [one(side, indent=1) for side in sides]
    rows += [one(f"Total Item Count: {count}"), pair("Subtotal:", fmt(subtotal, True), kind="subtotal", money=True),
             pair("Total Tax:", fmt(tax, True), kind="tax", money=True), pair("Total:", fmt(bill, True), kind="total", money=True),
             one("Paid With: VISA CARDHOLDER"), pair("Bill:", fmt(bill, True), kind="bill", money=True),
             Row([Cell("Total: $"), Cell(fmt(bill + tip), anchor=end_of("Total: $") + 14, handwritten=True, money=True)], kind="written_total"),
             Row([Cell("Tip: $"), Cell(fmt(tip), anchor=end_of("Tip: $") + 14, handwritten=True, money=True)], kind="written_tip"), one("Suggested Tip")]
    checks = [("sum", [price for _, price, _ in items], subtotal), ("sum", [subtotal, tax], bill), ("sum", [bill, tip], bill + tip)]
    for percent in (18, 20, 22):
        suggested = tax_of(subtotal, percent)
        rows.append(Row([Cell(f"{percent}.00% of sale:"), Cell(fmt(suggested, True), "right", anchor=420, money=True), Cell("Total", anchor=470),
                         Cell(fmt(bill + suggested, True), "right", money=True)], kind="suggested"))
        checks.append(("sum", [bill, suggested], bill + suggested))
    return rows, checks


FUEL_NAMES = ("Northway Fuel", "Redline Gas & Go", "Summit Petroleum", "Prairie Pump")


def fuel(rng):
    """Label and value pairs."""
    gallons, price = rng.randint(6000, 16000), rng.choice((3299, 3459, 3519, 3689))  # thousandths of a gallon and of a dollar
    amount = (gallons * price + 5000) // 10000
    rows = header(rng, FUEL_NAMES) + [gap(), pair("Date", day_text(rng)), pair("Pump", f"{rng.randint(1, 12):02d}"),
                                     pair("Product", rng.choice(("REGULAR 87", "PLUS 89", "PREMIUM 93"))), pair("Gallons", f"{gallons / 1000:.3f}"),
                                     pair("Price/Gal", f"${price / 1000:.3f}"), pair("Fuel Total", fmt(amount, True), kind="item", money=True)]
    checks, parts = [("product", gallons, price, amount, 10000)], [amount]
    if rng.random() < 0.5:
        wash = rng.choice((800, 1000, 1200))
        rows.append(pair("Car Wash", fmt(wash, True), kind="item", money=True))
        parts.append(wash)
    total = sum(parts)
    rows += [pair("TOTAL", fmt(total, True), kind="total", money=True), gap(), pair("Card", card(rng).split()[1]), pair("Auth", reference(rng)),
             pair("Receipt", reference(rng)), gap(), one("THANK YOU - DRIVE SAFE", "center")]
    return rows, [*checks, ("sum", parts, total)]


TERMINAL_NAMES = ("Willow Hardware", "Lantern Books", "Cedar Cafe", "Brightside Pharmacy")


def terminal(rng):
    """A card-terminal block: label at the left, value at the right."""
    sale = rng.randint(1200, 9800)
    tip = rng.choice((0, 200, 400, 500))
    rows = [one(rng.choice(TERMINAL_NAMES), "center"), one(f"{rng.randint(10, 98)} Mill Road", "center"), one("CUSTOMER COPY", "center"), gap(),
            pair("Merchant ID", reference(rng)), pair("Terminal", f"T{reference(rng)}"), pair("Date/Time", day_text(rng)), pair("Card Type", "VISA CREDIT"),
            pair("Card", card(rng).split()[1]), pair("Entry", rng.choice(("CHIP", "TAP", "SWIPE"))), pair("Auth Code", reference(rng)),
            pair("Reference", reference(rng)), gap(), pair("Sale", fmt(sale, True), kind="item", money=True)]
    parts = [sale]
    if tip:
        rows.append(pair("Tip", fmt(tip, True), kind="item", money=True))
        parts.append(tip)
    total = sum(parts)
    rows += [pair("Total", fmt(total, True), kind="total", money=True), gap(), one("APPROVED", "center"), one("Thank You", "center")]
    return rows, [("sum", parts, total)]


ITEMIZED_NAMES = ("Ironbridge Supply Co", "Harbor Tool & Parts")
ITEMIZED_ITEMS = (("Hex Bolts M8", 85), ("Wood Screws Box", 640), ("Work Gloves", 1250), ("Safety Glasses", 780), ("Paint Roller Kit", 1895),
                  ("Duct Tape", 575), ("Drill Bit Set", 2450), ("Extension Cord", 1695), ("Masking Tape", 325), ("Utility Knife", 899))


def itemized(rng):
    """A table with a Qty / Item / Price / Total header."""
    def line(qty, item, price, total, kind):
        money = kind == "item"
        return Row([Cell(qty, anchor=52), Cell(item, anchor=134), Cell(price, "right", anchor=548, money=money), Cell(total, "right", money=money)], kind=kind)
    rows = header(rng, ITEMIZED_NAMES) + [one(f"Order: {reference(rng)}"), pair("Date", day_text(rng)), gap(), line("Qty", "Item", "Price", "Total", "header")]
    parts, checks = [], []
    for item, price in rng.sample(ITEMIZED_ITEMS, rng.randint(5, 8)):
        qty = rng.randint(1, 12)
        total = qty * price
        rows.append(line(str(qty), item, fmt(price), fmt(total), "item"))
        parts.append(total)
        checks.append(("product", qty, price, total, 1))
    subtotal = sum(parts)
    tax = tax_of(subtotal)
    total = subtotal + tax
    rows += [gap(), pair("Subtotal", fmt(subtotal), kind="subtotal", money=True), pair("Tax 8%", fmt(tax), kind="tax", money=True),
             pair("Total", fmt(total), kind="total", money=True), gap(), one("Net 30 - thank you", "center")]
    return rows, [("sum", parts, subtotal), ("sum", [subtotal, tax], total), *checks]


ERECEIPT_NAMES = ("Parcelwise Online", "Northlight Goods", "Tidepool Store")
ERECEIPT_ITEMS = (("Canvas Tote Bag", 2400, ("Color: Navy",)), ("Ceramic Mug", 1600, ("Size: 12 oz", "Color: White")), ("Linen Napkins", 3200, ("Set of 4",)),
                  ("Desk Lamp", 5400, ("Finish: Brass",)), ("Wool Socks", 1800, ("Size: M", "Color: Grey")), ("Notebook Set", 1450, ()),
                  ("Glass Carafe", 2850, ("Capacity: 1 L",)))


def ereceipt(rng):
    """A proportional font, an online order: indented option lines, a shipping address block."""
    rows = [one(rng.choice(ERECEIPT_NAMES), "center"), one("Order confirmation", "center"), gap(), one(f"Order #: {reference(rng)}"),
            one(f"Placed on {day_text(rng).split(',')[0]}"), gap()]
    parts = []
    for item, price, options in rng.sample(ERECEIPT_ITEMS, rng.randint(3, 5)):
        rows.append(pair(item, fmt(price, True), kind="item", money=True))
        rows += [one(option, indent=1) for option in options]
        parts.append(price)
    subtotal, shipping = sum(parts), rng.choice((0, 495, 695))
    tax = tax_of(subtotal)
    total = subtotal + shipping + tax
    rows += [gap(), pair("Subtotal", fmt(subtotal, True), kind="subtotal", money=True), pair("Shipping", fmt(shipping, True), kind="shipping", money=True),
             pair("Tax", fmt(tax, True), kind="tax", money=True), pair("Total", fmt(total, True), kind="total", money=True), gap(), one("Ship to"),
             one(rng.choice(("Alex Rivera", "Sam Okafor", "Jordan Lee")), indent=1), one(f"{rng.randint(100, 980)} Maple Terrace", indent=1),
             one("Fairview, ST 55501", indent=1), gap(), one(f"Payment: {card(rng)}"), gap(), one("Questions? help@example.test", "center")]
    return rows, [("sum", parts, subtotal), ("sum", [subtotal, shipping, tax], total)]


RETURN_ITEMS = (("Coffee Maker", 4999), ("Wool Throw", 3500), ("Table Lamp", 2899), ("Kettle", 3250), ("Picture Frame", 1499), ("Bath Towels", 2400))


def return_slip(rng, index):
    """RETURN rows: the money given back is printed with a minus (trailing for index 0, in parentheses for the next)."""
    negative = ("trail", "paren")[index % 2]
    rows = header(rng, GROCERY_STORES) + [pair(day_text(rng), "RETURN"), one(f"Orig receipt {reference(rng)}"), gap()]
    parts = []
    for item, price in rng.sample(RETURN_ITEMS, rng.randint(2, 4)):
        rows.append(pair(f"RETURN {item}", fmt(-price, negative=negative), kind="item", money=True))
        parts.append(-price)
    subtotal = sum(parts)
    tax = -tax_of(-subtotal)
    total = subtotal + tax
    rows += [gap(), pair("SUBTOTAL", fmt(subtotal, negative=negative), kind="subtotal", money=True), pair("TAX", fmt(tax, negative=negative), kind="tax", money=True),
             pair("REFUND TOTAL", fmt(total, negative=negative), kind="total", money=True), gap(), one(f"Refund to {card(rng)}"),
             one("RETURNS ACCEPTED WITHIN 30 DAYS", "center")]
    return rows, [("sum", parts, subtotal), ("sum", [subtotal, tax], total)]


def make(family, condition, index) -> Receipt:
    """The receipt of one case: seeded by its three values (a string seed is stable across processes)."""
    if family not in FAMILIES or condition not in CONDITIONS:
        raise ValueError(f"unknown case {family}/{condition}/{index}")
    rng = random.Random(f"{family}:{condition}:{index}")
    style = "proportional" if family == "ereceipt" else "thermal"
    if family == "grocery":
        rows, checks = grocery(rng)
    elif family == "long":
        rows, checks = grocery(rng, count=rng.randint(60, 70), floor=84)
    elif family == "dining":
        rows, checks = dining(rng, index)
    elif family == "fuel":
        rows, checks = fuel(rng)
    elif family == "terminal":
        rows, checks = terminal(rng)
    elif family == "itemized":
        rows, checks = itemized(rng)
    elif family == "ereceipt":
        rows, checks = ereceipt(rng)
    else:
        rows, checks = return_slip(rng, index)
    return Receipt(family, condition, index, style, rows, checks)


# --- Drawing --------------------------------------------------------------------------------------------------------------------

def cell_font(cell, receipt):
    return hand_font() if cell.handwritten else text_font(receipt)


def reference_span(face):
    box = face.getbbox(REFERENCE, anchor="la")
    return box[1], box[3]


def place(receipt, row, cell, face):
    """The x where a cell's text starts."""
    style = STYLES[receipt.style]
    width = face.getlength(cell.text)
    if cell.anchor is not None:
        return {"left": cell.anchor, "right": cell.anchor - width, "center": cell.anchor - width / 2}[cell.align]
    return {"left": style.margin + row.indent * indent_step(receipt.style), "right": style.right - width, "center": style.center - width / 2}[cell.align]


def layout(receipt):
    """Per row, per cell: (x, y, font, box) on the flat canvas before any photo condition. The first row's top is the style's top margin."""
    style, printed = STYLES[receipt.style], text_font(receipt)
    top, bottom = reference_span(printed)
    centre = (top + bottom) / 2
    step = advance(receipt.style)
    rows = []
    for number, row in enumerate(receipt.rows):
        y = style.top + number * style.pitch
        placed = []
        for cell in row.cells:
            face = cell_font(cell, receipt)
            x = place(receipt, row, cell, face)
            ref_top, ref_bottom = reference_span(face)
            ink = face.getbbox(cell.text, anchor="la")
            line_y = y + centre - (ref_top + ref_bottom) / 2 - 2 if cell.handwritten else y  # handwriting sits on the printed row's middle
            box = (x + ink[0], line_y + min(ink[1], ref_top), x + max(ink[2], face.getlength(cell.text)), line_y + max(ink[3], ref_bottom))
            placed.append((x, line_y, face, box))
        rows.append(placed)
        check_row(receipt, row, placed, style, step)
    return rows


def check_row(receipt, row, placed, style, step):
    """A row's cells stay inside the margins and keep clear of one another (the row builder joins cells closer than 1.5 characters)."""
    previous = None
    for cell, (_, _, _, box) in zip(row.cells, placed):
        assert style.margin - 1 <= box[0] and box[2] <= style.right + 1, (receipt.key, cell.text, box)
        if previous is not None:
            needed = 8 if cell.handwritten or previous[0].handwritten else GAP * step
            assert box[0] - previous[1] >= needed, (receipt.key, previous[0].text, cell.text, box[0] - previous[1])
        previous = (cell, box[2])
    for cell in row.cells:
        if cell.money:
            assert parse_amounts(cell.text) and len(parse_amounts(cell.text)) == 1, (receipt.key, cell.text)


def base_image(receipt, only=None):
    """The flat drawing (white paper, black or grey ink). `only` = (row, cell) draws that cell alone, for the box-encloses-ink check."""
    style = STYLES[receipt.style]
    rows = layout(receipt)
    height = 2 * style.top + len(receipt.rows) * style.pitch
    image = Image.new("RGB", (style.width, height), "white")
    pen = ImageDraw.Draw(image)
    ink = (150, 150, 150) if receipt.condition == "faded" else (0, 0, 0)
    for number, (row, placed) in enumerate(zip(receipt.rows, rows)):
        for position, (cell, (x, y, face, _)) in enumerate(zip(row.cells, placed)):
            if only is None or only == (number, position):
                pen.text((x, y), cell.text, fill=HAND_INK if cell.handwritten else ink, font=face, anchor="la")
    if receipt.condition == "faded" and only is None:  # Thermal paper that has faded: grey print and specks.
        specks = random.Random(f"{receipt.key}:specks")
        for _ in range(image.width * image.height // 400):
            pen.point((specks.randrange(image.width), specks.randrange(image.height)), fill=(200, 200, 200))
    return image, [[box for *_, box in placed] for placed in rows]


def homography(source, target):
    """The 8 coefficients (a..h) of the perspective map taking each source point to its target."""
    matrix, values = [], []
    for (x, y), (u, v) in zip(source, target):
        matrix += [[x, y, 1, 0, 0, 0, -u * x, -u * y], [0, 0, 0, x, y, 1, -v * x, -v * y]]
        values += [u, v]
    return [float(value) for value in np.linalg.solve(np.array(matrix, float), np.array(values, float))]


def project(coefficients, point):
    a, b, c, d, e, f, g, h = coefficients
    x, y = point
    scale = g * x + h * y + 1
    return (a * x + b * y + c) / scale, (d * x + e * y + f) / scale


def photograph(receipt, image):
    """Apply the case's photo condition: (image, a function mapping a point of the flat canvas to the final image)."""
    condition, width, height = receipt.condition, *image.size
    if condition == "tilted":
        angle = np.radians(random.Random(f"{receipt.key}:tilt").choice((-TILT, TILT)))
        cos, sin = float(np.cos(angle)), float(np.sin(angle))
        new_w, new_h = int(np.ceil(width * abs(cos) + height * abs(sin))), int(np.ceil(width * abs(sin) + height * abs(cos)))
        cx, cy, nx, ny = width / 2, height / 2, new_w / 2, new_h / 2
        inverse = (cos, -sin, cx - nx * cos + ny * sin, sin, cos, cy - nx * sin - ny * cos)
        out = image.transform((new_w, new_h), Image.Transform.AFFINE, inverse, resample=Image.Resampling.BICUBIC, fillcolor=(255, 255, 255))
        return out, lambda p: (nx + (p[0] - cx) * cos + (p[1] - cy) * sin, ny - (p[0] - cx) * sin + (p[1] - cy) * cos)
    if condition == "angled":
        corners = [(0, 0), (width, 0), (width, height), (0, height)]
        warped = [(width * INSET, 0), (width * (1 - INSET), 0), (width, height), (0, height)]
        out = image.transform((width, height), Image.Transform.PERSPECTIVE, homography(warped, corners), resample=Image.Resampling.BICUBIC,
                              fillcolor=(255, 255, 255))
        forward = homography(corners, warped)
        return out, lambda p: project(forward, p)
    if condition == "blurred":
        return image.filter(ImageFilter.GaussianBlur(BLUR)), lambda p: p
    if condition == "small_text":
        size = (round(width * SMALL), round(height * SMALL))
        return image.resize(size, Image.Resampling.LANCZOS), lambda p: (p[0] * size[0] / width, p[1] * size[1] / height)
    if condition == "background":
        out = Image.new("RGB", (width + 2 * BACKGROUND_PAD, height + 2 * BACKGROUND_PAD), BACKGROUND_INK)
        out.paste(image, (BACKGROUND_PAD, BACKGROUND_PAD))
        return out, lambda p: (p[0] + BACKGROUND_PAD, p[1] + BACKGROUND_PAD)
    return image, lambda p: p


def draw(receipt, only=None):
    """(image, boxes): boxes[row][cell] = [left, top, right, bottom] in the final image, rounded to 0.1 px (so a floating-point difference between
    computers can't change a case id)."""
    flat, flat_boxes = base_image(receipt, only)
    image, mapper = photograph(receipt, flat)
    boxes = []
    for row in flat_boxes:
        mapped = []
        for left, top, right, bottom in row:
            points = [mapper(point) for point in ((left, top), (right, top), (right, bottom), (left, bottom))]
            xs, ys = [p[0] for p in points], [p[1] for p in points]
            mapped.append([round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)])
        boxes.append(mapped)
    return image, boxes


def png_bytes(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", compress_level=6)
    return buffer.getvalue()


# --- Answers --------------------------------------------------------------------------------------------------------------------

def answers(receipt, boxes, size):
    """What a perfect reading says: the rows in printed order (blank lines are not rows) with cells, indent, alignment, handwriting and amounts."""
    rows = []
    for row, row_boxes in zip(receipt.rows, boxes):
        if not row.cells:
            continue
        rows.append({"cells": [{"text": cell.text, "handwritten": cell.handwritten, "box": box} for cell, box in zip(row.cells, row_boxes)],
                     "indent": row.indent, "align": row.cells[0].align if len(row.cells) == 1 else "left",
                     "amounts": parse_amounts(" ".join(cell.text for cell in row.cells))})
    return {"size": list(size), "rows": rows}


def printed_amounts(receipt):
    """Every amount the receipt prints on its money cells, as a multiset."""
    return Counter(amount for row in receipt.rows for cell in row.cells if cell.money for amount in parse_amounts(cell.text))
