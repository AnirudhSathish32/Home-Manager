"""A seeded generator of text-PDF bill files (specs/pdf-table-engine-bills FR-123, SC-123; plan P12).

  layout = make(seed, index)       # the same two numbers always give the same Layout

`Layout.pages` are positioned items in the form `tests/test_pdf.py make_pdf` takes: {"items": [(x, y, text), ...]}, 10 pt Helvetica, in points, each
right-aligned amount placed from the Helvetica widths of `statement_layouts`. The generator writes no PDF. `Layout.bills` is one dict per bill of the file,
in file order, and comes only from the generator's inputs, never from a reader: the provider, dates and account, every charge line (the description the model
would give, its signed amount in minor units, kind, printed quantity and rate, the holder the print gives it and the holder a model would give), the amounts
the bill prints (previous balance, payments, new charges, each amount due), the amounts the reading should settle on (new charges worked out or printed, the
amount due chosen by FR-117), the notes it should carry and the pages it takes. `Layout.choices` names what was drawn, for failure messages and for the
coverage count (`variations`).

Every dimension FR-123 names is varied, each by a balanced draw (`pick`): over any run of consecutive indices every value of a dimension comes up equally
often. The rules that keep each bill decidable under the spec are in `settle`. A bill's printed money is integer minor units, so every sum holds exactly:
new charges are the lines' signed sum, the amount due is previous balance − payments + new charges (the new charges alone when the bill prints no
previous balance), and a charge that is a quantity × a rate is the product rounded half up (`document_checks.product`'s rule).
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
import random

from .statement_layouts import money, pick, put, width

FOOTER = "This bill is for your records. Amounts are in US dollars."
LABEL_X = 40
USAGE, RATE, CHARGE = 330, 420, 520  # The right edges of the amount columns.
TOP = 780
FLOOR = 76  # No printed line starts below this y (the footer is at 40).
WRAP_X = 52
PITCHES = (16, 14, 12)

KINDS = ("utility", "utility", "phone", "rent")
HEADINGS = ("known1", "known2", "unknown1", "unknown2", "none")
COLUMNS = ("plain", "qr", "lastyear")
CREDITS = ("minus", "paren", "cr", "section")
SUMMARIES = ("above", "below", "both", "none")
CUTS = ("none", "none", "tail", "mid")
STUBS = ("none", "on_page", "own_page", "on_page")
LATES = ("none", "none", "run", "col", "dateless", "fee_after")
SENTENCES = ("none", "none", "due_prose", "late_prose", "statement_prose", "anchor_prose")
RATE_KINDS = ("whole_2dp", "whole_4dp", "frac_3dp", "frac_4dp")
PHONE_FORMS = ("full", "paren", "seven", "masked", "ending", "ending_in", "ends_in", "name_only")
HOLDER_MODES = ("first_row", "none", "disagree")  # SC-123's (i), (ii) and (iii)
STUB_LINES = ("amount_due", "payment_due")
DUE_LABELS = ("Total Amount Due", "Amount Due", "Total Due", "Balance Due", "Amount Due by {due}", "Amount Due on or before {due}")
PREVIOUS_LABELS = ("Previous Balance", "Balance Forward", "Last Bill")
PAYMENT_LABELS = ("Payment Received {paid}", "Payments Received", "Payment - Thank You")
NEW_LABELS = ("New Charges", "Total Current Charges", "Current Charges")

PROVIDERS = {"utility": ("CITY POWER & WATER", "SYNTH ENERGY CO", "NORTHWIND UTILITIES"), "phone": ("METRO WIRELESS", "SYNTH MOBILE"),
             "rent": ("SYNTH PROPERTY MANAGEMENT", "NORTHWIND APARTMENTS")}
HOLDERS = (("Alex", "Blair"), ("Casey", "Drew"), ("Emery", "Finley"))
LAST_FOURS = (("1111", "2222"), ("3333", "4444"), ("5678", "8765"))
HISTORY = (("Sep 2025", "590", "30"), ("Oct 2025", "610", "31"), ("Nov 2025", "540", "30"), ("Dec 2025", "600", "31"), ("Jan 2026", "680", "31"),
           ("Feb 2026", "720", "28"), ("Mar 2026", "650", "31"), ("Apr 2026", "560", "30"), ("May 2026", "500", "31"))
KNOWN = {"plain": (("Charge",), ("Amount",), ("Current Charges",)), "qr": (("Usage", "Rate", "Charge"), ("Consumed", "Price", "Amount"))}


@dataclass
class Layout:
    pages: list = field(default_factory=list)  # [{"items": [(x, y, text), ...]}, ...], as tests/test_pdf.py make_pdf takes them.
    bills: list = field(default_factory=list)  # One dict per bill of the file, in file order.
    choices: dict = field(default_factory=dict)


# --- Small helpers ------------------------------------------------------------------------------------------------------------

def collapse(text):
    return " ".join(text.split())


def iso(day):
    return day.isoformat()


def us(day):
    return f"{day.month:02d}/{day.day:02d}/{day.year}"


def minor_text(minor, style="plain", dollar=False):
    """A signed amount as printed: `style` is how money off is shown (minus, paren, cr; `section` and anything else print it unsigned)."""
    sign = "$" if dollar else ""
    if minor >= 0:
        return f"{sign}{money(minor)}"
    if style == "minus":
        return f"-{sign}{money(-minor)}"
    if style == "paren":
        return f"({sign}{money(-minor)})"
    if style == "cr":
        return f"{sign}{money(-minor)} CR"
    return f"{sign}{money(-minor)}"


def product(quantity, rate):
    """quantity × rate (in ten-thousandths of a dollar) in minor units, rounded half up."""
    return (quantity * rate + 50) // 100


def rate_text(rate, kind):
    whole, tail = divmod(rate, 10000)
    return {"whole_2dp": f"{whole}.{tail // 100:02d}", "whole_4dp": f"{whole}.{tail:04d}", "frac_3dp": f"{whole}.{tail // 10:03d}", "frac_4dp": f"{whole}.{tail:04d}"}[kind]


def rate_for(rng, kind):
    """A rate in ten-thousandths of a dollar: whole cents for the two `whole` kinds, a rate half a cent past (or not on a cent) for the others."""
    if kind.startswith("whole"):
        return rng.choice((1000, 1200, 1500, 1800, 900)) + 0
    if kind == "frac_3dp":
        return rng.choice((1250, 1350, 1450, 1230, 1170))  # Three decimals: 0.125 is exactly half a cent past 0.12.
    return rng.choice((1450, 1430, 1275, 1530, 1250))  # Four decimals: 0.1450 is exactly half a cent past 0.14; 0.1275 and 0.1250 are not whole cents either.


# --- Choices --------------------------------------------------------------------------------------------------------------------

def settle(choices):
    """The dependent choices, after the independent draws (and any overrides)."""
    c = dict(choices)
    if c["kind"] == "rent":
        c["columns"] = "plain"
        c["history"] = False
    if c["kind"] == "phone" and c["columns"] == "qr":
        c["columns"] = "plain"
    if c["kind"] != "utility":
        c["history"] = False
    if c["summary"] == "none":
        c["prev_printed"] = False
    if c["columns"] == "lastyear":
        c["new_printed"] = True  # Two amount columns that both could be the charge are told apart by which sums to the new charges (FR-105 b).
    if c["bills"] == 1:
        c["acct_same_dates"] = False
    if c["stub"] == "own_page":
        c["cut"] = "none"
    if c["cut"] != "none" or c["stub"] == "own_page":
        c["pages"] = 2
    else:
        c["pages"] = 1
    c["repeat"] = c["repeat"] and c["pages"] == 2
    if c["kind"] != "phone":
        c["holder_forms"], c["holder_modes"] = (), ()
    else:  # A name-only title is a holder title only through a model holder on some row of its section (FR-102 b), so it never uses (ii).
        c["holder_modes"] = tuple("first_row" if form == "name_only" and mode == "none" else mode for form, mode in zip(c["holder_forms"], c["holder_modes"]))
    return c


def draw(seed, index):
    """The choices of one case (balanced per dimension)."""
    ordinal = index // 4  # KINDS holds one phone and one rent per block of four: this counts phone files, so every form of PHONE_FORMS comes up.
    forms = (PHONE_FORMS[(ordinal * 2) % len(PHONE_FORMS)], PHONE_FORMS[(ordinal * 2 + 1 + ordinal // len(PHONE_FORMS)) % len(PHONE_FORMS)])
    modes = (HOLDER_MODES[ordinal % 3], HOLDER_MODES[(ordinal + 1 + ordinal // 3) % 3])
    return settle({
        "kind": pick(seed, "kind", index, KINDS), "bills": pick(seed, "bills", index, (1, 2, 3, 4, 1, 2)),         "sections": pick(seed, "sections", index, ("sections", "one")), "heading": pick(seed, "heading", index, HEADINGS),
        "columns": pick(seed, "columns", index, COLUMNS), "credit": pick(seed, "credit", index, CREDITS), "summary": pick(seed, "summary", index, SUMMARIES),
        "prev_printed": pick(seed, "prev", index, (True, False)), "new_printed": pick(seed, "new", index, (True, False)),
        "due_diff": pick(seed, "duediff", index, (False, True, False)), "stub": pick(seed, "stub", index, STUBS), "stub_line": pick(seed, "stubline", index, STUB_LINES),
        "cut": pick(seed, "cut", index, CUTS), "repeat": pick(seed, "repeat", index, (True, False)), "late": pick(seed, "late", index, LATES),
        "late_row": pick(seed, "laterow", index, (False, True, False)), "sentence": pick(seed, "sentence", index, SENTENCES),
        "wrapped": pick(seed, "wrapped", index, (False, True)), "history": pick(seed, "history", index, (True, False)), "dots": pick(seed, "dots", index, (False, True)),
        "acct_same_dates": pick(seed, "acctdates", index, (False, True)), "rate_kind": pick(seed, "ratekind", index, RATE_KINDS),
        "due_label": pick(seed, "duelabel", index, tuple(range(len(DUE_LABELS)))), "swap": pick(seed, "swap", index, (False, True)),
        "holder_forms": forms, "holder_modes": modes,
    })


def make(seed, index, **overrides) -> Layout:
    """The `index`th case of `seed`. `overrides` replace drawn choices (for a fixed layout in the eval corpus); the rules still apply."""
    choices = settle({**draw(seed, index), **overrides})
    return Case(random.Random(f"{seed}:{index}"), choices).build()


# --- Building one bill -----------------------------------------------------------------------------------------------------------

class Case:
    def __init__(self, rng, choices):
        self.rng = rng
        self.c = choices
        kind = choices["kind"]
        self.provider = rng.choice(PROVIDERS[kind])
        self.names = rng.choice(HOLDERS)
        self.fours = rng.choice(LAST_FOURS)
        self.account_stem = {"utility": "1234-5678-", "phone": "555-0100-", "rent": "****"}[kind]
        self.statement_label = rng.choice(("Statement Date", "Bill Date"))
        self.due_label = rng.choice(("Due Date", "Payment Due Date"))
        self.account_label = rng.choice(("Account Number", "Account No."))
        self.current_label = rng.choice(KNOWN["plain"][0])
        self.dollar = kind == "rent"

    # --- The money of one bill -----------------------------------------------------------------------------------------------

    def line(self, label, minor, kind, *, section=None, category="utilities", **more):
        return {"label": label, "description": collapse(label), "minor": minor, "kind": kind, "category": category, "section": section, "quantity": None,
                "rate": None, "unit_minor": None, "unit_text": None, "wrap": None, "holder": None, "model_holder": None, "period": None, "usage": None, **more}

    def utility_lines(self, first):
        c, rng = self.c, self.rng
        lines = []
        if c["columns"] == "qr":
            kinds = [c["rate_kind"], RATE_KINDS[(RATE_KINDS.index(c["rate_kind"]) + 2) % 4]]
            if not first:
                kinds.reverse()
            for number, (kind, quantity) in enumerate(zip(kinds, (rng.choice((500, 300, 250, 400)), rng.choice((140, 120, 90, 60))))):
                rate = rate_for(rng, kind)
                text = rate_text(rate, kind)
                lines.append(self.line(f"Energy Tier {number + 1}", product(quantity, rate), "usage", section="Electric Charges", quantity=f"{quantity} kWh",
                                       rate=text, quantity_value=quantity, unit_minor=(rate + 50) // 100, unit_text=None if rate % 100 == 0 else text, rate_kind=kind))
        else:
            lines.append(self.line("Energy Charge", rng.randint(4000, 9000), "usage", section="Electric Charges"))
        lines.append(self.line("Customer Charge", rng.choice((1200, 1000, 1500)), "service", section="Electric Charges"))
        lines.append(self.line("State Tax", rng.randint(300, 900), "tax_fee", section="Taxes and Fees"))
        lines.append(self.line("Franchise Fee", rng.randint(100, 400), "tax_fee", section="Taxes and Fees"))
        if c["wrapped"]:
            lines[-1].update(wrap="(City surcharge)", description=collapse(f"{lines[-1]['label']} (City surcharge)"))
        return lines

    def phone_lines(self, first):
        c, rng = self.c, self.rng
        lines = []
        for number, name in enumerate(self.names):
            title = self.holder_title(number)
            holders = {"holder": title, "section": title, "owner": number}
            lines.append(self.line("Unlimited Plan" if number == 0 else "Basic Plan", rng.choice((5500, 3500, 4500)), "service", **holders))
            lines.append(self.line("Device Payment" if number == 0 else "International Pack", rng.choice((2499, 851, 1250)), "device" if number == 0 else "service", **holders))
            if number == 1 and c["wrapped"]:
                lines[-1].update(wrap="(Canada and Mexico)", description="International Pack (Canada and Mexico)")
        lines.append(self.line("Regulatory Fee", rng.randint(150, 500), "tax_fee", section="Taxes and Fees"))
        return lines

    def rent_lines(self, first, bill):
        rng = self.rng
        start = date(2026, 6 + bill % 4, 1)  # A whole calendar month, so no proration is noted.
        end = date(2026, 6 + bill % 4 + 1, 1) - timedelta(days=1)
        water = (start - timedelta(days=46), start - timedelta(days=16))
        lines = [self.line(f"Rent {us(start)} - {us(end)}", rng.choice((145000, 120000, 98000)), "rent", section="Rent and Leasing Charges", description="Rent",
                           period=(iso(start), iso(end)), category="housing"),
                 self.line(f"Water Usage {us(water[0])} - {us(water[1])} 3,200 GAL", rng.randint(2500, 6000), "utility", section="Rent and Leasing Charges",
                           description="Water Usage", period=(iso(water[0]), iso(water[1])), usage="3,200 GAL"),
                 self.line(f"Parking {us(start)} - {us(end)}", rng.choice((7500, 5000)), "parking", section="Rent and Leasing Charges", description="Parking",
                           period=(iso(start), iso(end)), category="housing")]
        if self.c["wrapped"]:
            lines[2].update(wrap="(Covered spot)", description="Parking (Covered spot)")
        return lines

    def holder_title(self, number):
        """The title line of a holder section (the text a title prints, whitespace as printed)."""
        form = self.c["holder_forms"][number]
        name, four = self.names[number], self.fours[number]
        area = "201" if number == 0 else "202"
        return {"full": f"{name} 555-{area}-{four}", "paren": f"{name} (555) {area}-{four}", "seven": f"{name} {area}-{four}", "masked": f"{name} xxx-xxx-{four}",
                "ending": f"Line ending {four}", "ending_in": f"Line ending in {four}", "ends_in": f"Line ends in {four}", "name_only": name}[form]

    def full_holder(self, number):
        """What a model would call the holder: the name and the whole number, whose last four digits match the title's."""
        return f"{self.names[number]} 555-{'201' if number == 0 else '202'}-{self.fours[number]}"

    def credit_line(self):
        rng, c = self.rng, self.c
        label = {"utility": "Paperless Credit", "phone": "Autopay Discount", "rent": "Rent Concession"}[c["kind"]]
        minor = -rng.choice((500, 250, 1000))
        kind = "credit"
        return self.line(label, minor, kind, section="Account Credits", category="housing" if c["kind"] == "rent" else "utilities", credit=True)

    def bill_lines(self, bill):
        c = self.c
        lines = {"utility": self.utility_lines, "phone": self.phone_lines, "rent": lambda first: self.rent_lines(first, bill)}[c["kind"]](bill == 0)
        if c["late_row"]:
            lines.append(self.line("Late Fee", 500, "tax_fee" if c["kind"] != "rent" else "fee", section=lines[-1]["section"] if c["kind"] != "phone" else "Taxes and Fees",
                                   description="Late Fee"))
        lines.append(self.credit_line())
        return lines

    def build(self):
        c, rng = self.c, self.rng
        first = date(2026, 3, 1) + timedelta(days=30 * rng.randint(0, 3))
        bills = []
        for number in range(c["bills"]):
            statement = first + timedelta(days=30 * number)
            if c["acct_same_dates"] and number == 1:
                statement = first
            due = statement + timedelta(days=25)
            period_end = statement - timedelta(days=6)
            account = f"{self.account_stem}{rng.randint(1000, 9999)}" if number == 0 or not c["acct_same_dates"] else f"{self.account_stem}{rng.randint(1000, 9999)}"
            if number and not c["acct_same_dates"]:
                account = bills[0]["account"]
            bills.append(self.bill(number, statement, due, period_end, account))
        return self.print_file(bills)

    def bill(self, number, statement, due, period_end, account):
        c, rng = self.c, self.rng
        lines = self.bill_lines(number)
        new = sum(line["minor"] for line in lines)
        prev = rng.randint(5000, 15000) if c["prev_printed"] else None
        paid = None if prev is None else rng.choice((prev, prev, prev - 1500))
        amount_due = new if prev is None else prev - paid + new
        wrong = amount_due + rng.choice((1234, 3377, 5000)) if c["due_diff"] else None
        carried = prev is not None and c["new_printed"]
        # FR-117: the carried check picks the amount due when previous balance, payments and new charges all print; the lines check when no new charges are
        # printed or worked out; else the first value on the first page, with a guess note. The right value is printed after the wrong one only when a guess
        # decides, so the guess is a right one.
        decision = "check" if carried else "lines" if not c["new_printed"] and prev is None else "guess"
        if c["columns"] == "lastyear":  # A last-year column is told from the charge column by the numbers: its sum is neither the new charges nor the amount due.
            for line in lines:
                if not line.get("credit"):
                    line["last"] = max(100, int(line["minor"] * rng.uniform(0.7, 1.3)))
            if sum(line.get("last", 0) for line in lines) + sum(line["minor"] for line in lines if line.get("credit")) in (new, amount_due):
                lines[0]["last"] += 111
        notes = self.holders(lines) if c["kind"] == "phone" else []
        if c["kind"] != "phone":
            for place, line in enumerate(lines, 1):
                line["position"] = place
        bill = {"provider": self.provider, "account": account, "last_four": account[-4:], "kind": c["kind"], "number": number,
                "issue_date": iso(statement), "due_date": iso(due), "statement": iso(statement), "due": iso(due),
                "period": (iso(period_end - timedelta(days=29)), iso(period_end)),
                "lines": lines, "previous": prev, "payments": paid, "new_printed": c["new_printed"], "new_charges": new, "worked_out": prev is not None and not c["new_printed"],
                "amount_due": amount_due, "wrong_due": wrong, "decision": decision if wrong is not None else None, "due_guess": wrong is not None and decision == "guess",
                "notes": notes, "pages": 1, "labels": {"account": self.account_label, "statement": self.statement_label, "due": self.due_label}}
        if c["kind"] == "rent":
            periods = [line["period"] for line in lines if line["kind"] == "rent"]
            bill["period"] = (min(p[0] for p in periods), max(p[1] for p in periods))
        return bill

    # --- Holders (FR-102, FR-110, D22, D24) ----------------------------------------------------------------------------------

    def holders(self, lines):
        """Each holder section's model holders per the case's mode, the holder the print gives its rows, and the notes a disagreeing model holder earns."""
        found = []
        for number in range(len(self.names)):
            rows = [line for line in lines if line.get("owner") == number]
            title = collapse(self.holder_title(number))[:80]
            mode = self.c["holder_modes"][number]
            for line in rows:
                line["holder"] = title
            if mode == "first_row":
                rows[0]["model_holder"] = self.full_holder(number)
            elif mode == "disagree":
                rows[0]["model_holder"] = self.full_holder(number)
                rows[1]["model_holder"] = self.full_holder(1 - number)
                found.append((rows[1], title))
        for place, line in enumerate(lines, 1):
            line["position"] = place
        return [f"Line {line['position']}: the holder {line['model_holder']} differs from its section title; the title's holder {title} was used." for line, title in found]

    # --- Printing --------------------------------------------------------------------------------------------------------------

    def print_file(self, bills):
        pages, first = [], 0
        for bill in bills:
            printed = Printer(self, bill).render()
            bill["pages"], bill["first_page"] = len(printed), first
            pages += printed
            first += len(printed)
        return Layout(pages=[{"items": [*items, (LABEL_X, 40, FOOTER)]} for items in pages], bills=bills, choices={**self.c, "bill_pages": [bill["pages"] for bill in bills]})


def width_of(text):
    return width(text)


SECTION_TOTALS = {"Electric Charges": "Total Electric Charges", "Taxes and Fees": "Total Taxes and Fees", "Rent and Leasing Charges": "Total Rent and Leasing Charges"}


class Printer:
    """The pages of one bill: items placed from the top down by a cursor, a page break where the page is full or where the case forces one. It draws nothing
    from the random generator, so printing again at a smaller pitch changes only the spacing."""

    def __init__(self, case, bill):
        self.case, self.bill, self.c = case, bill, case.c
        self.statement, self.due = date.fromisoformat(bill["statement"]), date.fromisoformat(bill["due"])
        self.pitch = self.base = PITCHES[0]

    def render(self):
        for pitch in PITCHES:
            self.pitch = self.base = pitch
            self.pages, self.y = [[]], TOP
            self.draw()
            if len(self.pages) == self.c["pages"]:
                return self.pages
        raise ValueError(f"a bill of {self.c} does not fit {self.c['pages']} page(s) at any pitch: {len(self.pages)}")

    # -- The cursor --

    def put_line(self, text, x=LABEL_X, step=None):
        self.room(1)
        self.pages[-1].append((x, self.y, text))
        self.y -= self.pitch if step is None else step

    def amounts(self, label, *cells, wrap=None, dots=False, step=None):
        """A printed line: the label at x 40 (with leaders when asked) and the (right edge, text) cells right-aligned."""
        self.room(2 if wrap else 1)
        if dots:
            label = f"{label} {'.' * max(int((230 - width_of(label)) / 2.78), 3)}"
        if label:
            self.pages[-1].append((LABEL_X, self.y, label))
        self.pages[-1].extend(put(edge, self.y, text, True) for edge, text in cells if text)
        self.y -= self.pitch if step is None else step
        if wrap:
            self.pages[-1].append((WRAP_X, self.y + self.pitch - 10, wrap))
            self.y -= 10

    def room(self, lines):
        if self.y - self.pitch * (lines - 1) < FLOOR:
            self.new_page()

    def new_page(self):
        """A new page; a bill that repeats its header on a continuation page prints it again here."""
        self.pages.append([])
        self.y = TOP
        if self.c["repeat"]:
            self.header(short=True)

    def header(self, short=False):
        bill, case = self.bill, self.case
        lines = [bill["provider"], f"{case.account_label} {bill['account']}", f"{case.statement_label} {us(self.statement)}"]
        if bill["kind"] != "rent":
            lines.append(f"Billing Period {us(date.fromisoformat(bill['period'][0]))} - {us(date.fromisoformat(bill['period'][1]))}")
        lines.append(f"{case.due_label} {us(self.due)}")
        if short:
            lines = [lines[0], lines[1], lines[-1]]
        if self.c["swap"]:
            lines[1:3] = lines[2:3] + lines[1:2] if not short else lines[1:2]
        for text in lines:
            self.pages[-1].append((LABEL_X, self.y, text))
            self.y -= 12
        self.y -= 12

    # -- Money --

    def money(self, minor):
        return minor_text(minor, "plain", self.case.dollar)

    def cell(self, minor):
        """A charge cell: money off as the case's credit style prints it."""
        return minor_text(minor, self.c["credit"], self.case.dollar)

    def due_label(self):
        return DUE_LABELS[self.c["due_label"]].format(due=us(self.due))

    def summary_lines(self, box):
        """The bill's summary anchors (previous balance, payments, new charges, amount due) as (label, minor) in print order."""
        bill = self.bill
        paid = us(self.statement - timedelta(days=4))
        lines = []
        if bill["previous"] is not None:
            lines.append((PREVIOUS_LABELS[bill["number"] % 3], bill["previous"]))
            lines.append((PAYMENT_LABELS[(bill["number"] + self.c["due_label"]) % 3].format(paid=paid), -bill["payments"]))
        if bill["new_printed"]:
            lines.append((NEW_LABELS[0] if box else NEW_LABELS[1 + bill["number"] % 2], bill["new_charges"]))
        lines.append((self.due_label(), bill["amount_due"]))
        return lines

    # -- The bill --

    def draw(self):
        c, bill = self.c, self.bill
        self.header()
        if bill["decision"] in ("check", "lines"):  # The other value first on the page (SC-117).
            self.amounts("Balance Due", (CHARGE, self.money(bill["wrong_due"])))
        if c["summary"] in ("above", "both"):
            self.room(6)
            self.put_line("Account Summary")
            for label, minor in self.summary_lines(True):
                self.amounts(label, (CHARGE, self.money(minor)), dots=c["dots"])
        self.y -= 8
        self.charges()
        if c["cut"] == "tail":
            self.new_page()
        self.y -= 6
        if c["summary"] in ("below", "both"):
            for label, minor in self.summary_lines(False):
                self.amounts(label, (CHARGE, self.money(minor)), dots=c["dots"])
        elif c["summary"] == "none":
            if bill["new_printed"]:
                self.amounts(NEW_LABELS[1], (CHARGE, self.money(bill["new_charges"])), dots=c["dots"])
            self.amounts(self.due_label(), (CHARGE, self.money(bill["amount_due"])), dots=c["dots"])
        self.late()
        self.sentence()
        if c["history"]:
            self.history()
        if c["stub"] != "none":
            self.stub()
        if bill["decision"] == "guess":  # After the right value, wherever that was printed.
            self.amounts("Balance Due", (CHARGE, self.money(bill["wrong_due"])))

    def stub(self):
        bill, case = self.bill, self.case
        if self.c["stub"] == "own_page":
            self.new_page()
        else:
            self.y -= 8
            self.room(5)
        self.put_line("Return this portion with your payment")
        self.put_line(f"{case.account_label} {bill['account']}")
        if self.c["stub_line"] == "payment_due":
            self.amounts(f"Payment Due {us(self.due)}", (CHARGE, self.money(bill["amount_due"])))
        else:
            self.put_line(f"{case.due_label} {us(self.due)}")
            self.amounts("Amount Due", (CHARGE, self.money(bill["amount_due"])))

    def late(self):
        late = self.bill["amount_due"] + 500
        form = self.c["late"]
        if form == "run":
            self.put_line(f"If paid after {us(self.due)}, pay ${money(late)}")
        elif form == "col":
            self.amounts(f"If paid after {us(self.due)}, pay", (CHARGE, money(late)))
        elif form == "dateless":
            self.put_line(f"If paid late, pay ${money(late)}")
        elif form == "fee_after":
            self.amounts(f"Late fee after {us(self.due)}", (CHARGE, "5.00"))

    def sentence(self):
        form = self.c["sentence"]
        if form == "due_prose":
            self.put_line(f"Your previous bill, due {us(self.due - timedelta(days=30))}, is past due.")
        elif form == "late_prose":
            self.put_line(f"Late fee if not paid by {us(self.due)}")
        elif form == "statement_prose":
            self.put_line(f"Previous Statement Date {us(self.statement - timedelta(days=30))}")
        elif form == "anchor_prose":
            self.amounts("Your previous balance was paid in full", (CHARGE, "4.00"))

    def history(self):
        self.room(len(HISTORY) + 3)
        self.put_line("Usage History", step=12)
        self.amounts("Month", (USAGE, "kWh"), (RATE, "Days"), step=12)
        for month, kwh, days in HISTORY:
            self.amounts(month, (USAGE, kwh), (RATE, days), step=12)

    # -- Charges --

    def columns(self):
        if self.c["columns"] == "plain":
            return {"charge": CHARGE}
        if self.c["columns"] == "qr":
            return {"usage": USAGE, "rate": RATE, "charge": CHARGE}
        return {"last": RATE, "charge": CHARGE} if self.c["swap"] else {"charge": RATE, "last": CHARGE}

    def heading_lines(self):
        """The heading line(s) of the first table: a list of lines, each [(right edge, text) ...], from the case's style."""
        c, style = self.c, self.c["heading"]
        edges = self.columns()
        names = list(edges)
        flipped = c["columns"] == "lastyear" and c["swap"]
        if style == "none":
            return []
        if style == "known1":
            words = {"plain": (self.case.current_label,), "qr": ("Usage", "Rate", "Charge"), "lastyear": ("Last Year", "This Bill") if flipped else ("This Bill", "Last Year")}
            lines = [words[c["columns"]]]
        elif style == "known2":
            top, low = {"plain": (("This",), ("Charge",)), "qr": (("Usage", "Rate per", "This"), ("(kWh)", "kWh", "Charge")),
                        "lastyear": (("Last", "This"), ("Year", "Bill")) if flipped else (("This", "Last"), ("Bill", "Year"))}[c["columns"]]
            lines = [top, low]
        elif style == "unknown1":
            lines = [("Alpha", "Beta", "Gamma")]
        else:
            lines = [("Column", "Column", "Column"), ("A", "B", "C")]
        return [[(edges[name], word) for name, word in zip(names, line)] for line in lines]

    def sections(self):
        """[(title or None, rows, total label or None)] of the table, in print order."""
        c, bill = self.c, self.bill
        groups = []
        for line in bill["lines"]:
            if groups and groups[-1][0] == line["section"] and groups[-1][1][-1].get("owner") == line.get("owner"):
                groups[-1][1].append(line)
            else:
                groups.append((line["section"], [line]))
        sections = []
        for title, rows in groups:
            credit = bool(rows[0].get("credit"))
            shown = title if (c["kind"] != "utility" or c["sections"] == "sections" or credit and c["credit"] == "section") else None
            total = None
            if c["sections"] == "sections" and not credit:
                owner = rows[0].get("owner")
                total = f"Total for {self.case.names[owner]}" if owner is not None else SECTION_TOTALS[title]
            sections.append((shown, rows, total))
        return sections

    def charges(self):
        c = self.c
        edges = self.columns()
        sections = self.sections()
        count = sum(len(rows) for _, rows, _ in sections)
        cut = next((at for at in range(2, count - 1)), None) if c["cut"] == "mid" else None
        placed, headed = 0, False
        for title, rows, total in sections:
            if cut is not None and placed == cut:
                self.new_page()
                cut = None
            if title:
                self.room(4)
                self.put_line(title)
            if not headed:
                headed = True
                heads = self.heading_lines()
                for number, cells in enumerate(heads):
                    self.amounts("", *cells, step=12 if number < len(heads) - 1 else None)
            for row in rows:
                if cut is not None and placed == cut:
                    self.new_page()
                    cut = None
                self.row(row, edges)
                placed += 1
            if total:
                self.amounts(total, (edges["charge"], self.money(sum(row["minor"] for row in rows))))

    def row(self, row, edges):
        cells = [(edges["charge"], self.cell(row["minor"]))]
        if row["quantity"]:
            cells = [(edges["usage"], row["quantity"]), (edges["rate"], row["rate"]), *cells]
        if "last" in row:
            cells.append((edges["last"], self.money(row["last"])))
        flat = not row["quantity"] and "last" not in edges
        self.amounts(row["label"], *cells, wrap=row["wrap"], dots=self.c["dots"] and flat and not row["wrap"])


# --- What was drawn --------------------------------------------------------------------------------------------------------------

def variations(layout):
    """The tags of what a case prints, for the coverage count (every FR-123 variation, SC-123's rate kinds and holder forms and stubs)."""
    c = layout.choices
    tags = {f"kind:{c['kind']}", f"sections:{c['sections']}", f"heading:{c['heading']}", f"columns:{c['columns']}", f"credit:{c['credit']}", f"summary:{c['summary']}",
            f"prev:{'printed' if c['prev_printed'] else 'not'}", f"new:{'printed' if c['new_printed'] else 'not'}", f"stub:{c['stub']}", f"bills:{c['bills']}",
            f"pages_per_bill:{max(c['bill_pages'])}", f"late:{c['late']}", f"sentence:{c['sentence']}", f"cut:{c['cut']}"}
    if c["due_diff"]:
        tags.add("due:different")
    elif sum(1 for bill in layout.bills if bill["amount_due"] is not None) and (c["summary"] in ("above", "below") and c["stub"] != "none" or c["summary"] == "both"):
        tags.add("due:alike")
    for tag, on in (("wrapped", c["wrapped"]), ("history", c["history"]), ("dots", c["dots"]), ("late_row", c["late_row"]),
                    ("repeat", c["repeat"] and layout.choices["pages"] == 2), ("acct_same_dates", c["acct_same_dates"])):
        if on:
            tags.add(tag)
    for bill in layout.bills:
        if bill["decision"]:
            tags.add(f"decision:{bill['decision']}")
        tags.add("worked_out" if bill["worked_out"] else "new_charges:summed")
        for line in bill["lines"]:
            if line.get("rate_kind"):
                tags.add(f"rate:{line['rate_kind']}")
    for form, mode in zip(c["holder_forms"], c["holder_modes"]):
        tags.update((f"holder_form:{form}", f"holder_mode:{mode}"))
    return tags
