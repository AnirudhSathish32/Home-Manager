"""A seeded generator of text-PDF pay stub files (specs/pdf-table-engine-paystubs FR-70, SC-67; plan P10).

  layout = make(seed, index)       # the same two numbers always give the same Layout

`Layout.pages` are positioned items in the form `tests/test_pdf.py make_pdf` takes: {"items": [(x, y, text), ...]}, 10 pt Helvetica, in points,
each right-aligned amount placed from the Helvetica widths of `statement_layouts`. The generator writes no PDF. `Layout.answers` is one dict per
stub of the file, in file order, and comes only from the generator's inputs, never from a reader: the employer and pay date, every pay line (its
full description, group, category, this-period and year-to-date amounts in minor units or None for a blank cell, and the hours and rate as printed),
gross, net, taxes and deductions where the stub prints them, the printed text that cites each value, and how the file splits (`start`, the text of
the line a stub starts at, and `above`, how many heading lines print above it). `Layout.choices` names what was drawn, for failure messages and for
the coverage count.

Every dimension FR-70 names is varied, each by a balanced draw (`pick`): over any run of consecutive indices every value of a dimension comes up
equally often. Rules that keep each stub decidable under the spec (plan P10): a stub prints either section totals or headings naming the columns
(so its pay table is found); its this-period amounts are at most the year to date, except on a negative row; it prints its gross pay (a totals
line, or the summary box) so its arithmetic can be checked; money is integer minor units, so every sum holds exactly; a file of several stubs prints
a net pay line in each, so each can be told from the next; pay dates are before 2026-11-04.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
import random
import re

from .statement_layouts import money, pick, put, width

FOOTER = "This pay statement is for your records. Amounts are in US dollars ($)."
TOP = 780
ROW = 16
SPACING = 72  # Between the right edges of neighbouring amount columns.
LABEL_X = 40
SIDE = ((200, 270), (480, 550))  # The right edges of the current and year-to-date columns of the left and right blocks.
SIDE_ONE = (240, 540)
LEAVE_EDGES = (260, 330, 430)
AMOUNT = re.compile(r"[(-]?[\d,]+\.\d+\)?")
RIGHT_X = 290  # Where the right block's labels start
FLOOR = 100  # No line is printed below this y.

LAYOUTS = ("one", "one", "stacked", "side")
ORDERS = ("hr_cy", "hr_yc", "cy_hr", "yc_hr")
HEADINGS = ("known1", "known2", "unknown1", "unknown2", "none")
SIGNS = ("plain", "paren", "minus")
TOTALS = ("all", "all", "gross_net", "none", "all", "none")
EMPLOYERS = ("SYNTH PAYROLL CO", "NORTHWIND SYNTH LLC", "SYNTH HEALTH GROUP", "ACME SYNTH INC")
TITLES = ("Earnings Statement", "Pay Statement", "Pay Advice")
DATE_LABELS = ("Pay date", "Check date", "Payment date")
GROSS_LABELS = ("Gross Pay", "Total Earnings")
NET_LABELS = ("Net Pay", "Net Payment")
STACK_TITLES = (("Taxes", "Deductions"), ("Statutory", "Voluntary"))
CURRENT_YTD = (("Current", "YTD"), ("This Period", "Year to Date"), ("Current", "Year to Date"))
BOX_NAMES = ("Gross Pay", "Taxes", "Deductions", "Net Pay")
BOX_LABELS = (("Current", "YTD"), ("This Period", "Year to Date"))
BOX_EDGES = (200, 280, 370, 460)

SALARIED = ("Salary", "Regular Salary", "Base Pay")
# (label, category, wrapped label): a stub always prints the federal tax first; with `wrap` its label is printed over two lines.
TAXES = (("Social Security", "social_security", None), ("Medicare", "medicare", None), ("State Income Tax", "state_income_tax", None),
         ("State Disability", "state_disability", None))
FEDERAL = ("Federal Income Tax", "federal_income_tax", ("Federal Income", "Tax Withholding"))
SHARES = {"federal_income_tax": 11, "social_security": 6, "medicare": 1, "state_income_tax": 4, "state_disability": 1}
PRE_TAX_DIGITS = (("SECTION 125", "health"), ("403(b)", "retirement_pretax"))
PRE_TAX_PLAIN = (("Retirement Plan", "retirement_pretax"), ("Medical", "health"), ("Dental", "dental"), ("Vision", "vision"))


@dataclass
class Layout:
    pages: list = field(default_factory=list)  # [{"items": [(x, y, text), ...]}, ...], as tests/test_pdf.py make_pdf takes them.
    answers: list = field(default_factory=list)  # One dict per stub of the file, in file order.
    choices: dict = field(default_factory=dict)


# --- Small helpers -----------------------------------------------------------------------------------------------------------

def times(hundredths, ten_thousandths):
    """Hours (in hundredths) times a rate (in ten-thousandths of a dollar), in minor units, rounded half up."""
    return (hundredths * ten_thousandths + 5000) // 10000


def hours_text(hundredths):
    return f"{hundredths // 100}.{hundredths % 100:02d}"


def rate_text(ten_thousandths, four):
    whole, tail = divmod(ten_thousandths, 10000)
    return f"{whole}.{tail:04d}" if four else f"{whole}.{tail // 100:02d}"


def amount(minor, style, group="earnings"):
    """An amount as printed. Taxes and deductions are kept as magnitudes in the answers and printed plain, in parentheses or with a minus sign; an
    earning below zero (a correction) is printed with a minus sign, or in parentheses when the stub's style is parentheses."""
    if minor is None:
        return ""
    if group == "earnings":
        return money(minor) if minor >= 0 else (f"({money(-minor)})" if style == "paren" else f"-{money(-minor)}")
    return {"plain": money(minor), "paren": f"({money(minor)})", "minus": f"-{money(minor)}"}[style]


def settle(choices):
    """The dependent choices, after the independent draws (and any overrides)."""
    c = dict(choices)
    if c["layout"] == "side":
        c["hours"] = c["wrap"] = False
        c["pages"] = 1
    if not c["hours"]:
        c["ytd_hours"] = c["rate4"] = False
    if not c["ytd"]:
        c["box"] = c["ytd_hours"] = c["ytd_only"] = False
    if c["layout"] != "one":
        c["ytd_hours"] = c["employer_col"] = False
    if c["totals"] == "none" and not c["box"]:
        c["totals"] = "gross_net"  # Without a gross total or a summary box a stub can't be cross-checked.
    if c["totals"] != "all" and c["heading"] in ("unknown1", "unknown2", "none"):
        c["heading"] = "known1" if c["heading"] != "unknown2" else "known2"  # Without section totals the headings are what name the pay columns.
    if c["layout"] == "stacked" and (c["totals"] != "all" or c["heading"] == "none"):
        c["stack_heads"] = c["totals"] != "all"  # A table with no section total needs a heading of its own.
    if c["layout"] != "stacked":
        c["stack_heads"] = False
    if not (c["hours"] and c["ytd"]):
        c["hours_multiple"] = False
    if c["hours_multiple"]:
        c["ytd_hours"] = False  # A year-to-date hours column would make a third product (hours × rate); the rule needs two.
    if c["layout"] != "stacked" or c["pages"] != 2:
        c["break_table"] = 3
    if c["heading"] == "none":
        c["box_shuffled"] = c["box_shuffled"] and c["box_heads"] != "none"
    if c["box_heads"] == "none":
        c["box_shuffled"] = False
    if not c["box"]:
        c["box_heads"] = "known"
        c["box_shuffled"] = False
    c["net_row"] = c["net_row"] or not (c["box"] and c["totals"] == "none" and c["stubs"] == 1)
    if c["stubs"] == 1:
        c["per_page"] = 1
    return c


def draw(seed, index):
    """The choices of one case (balanced per dimension)."""
    return settle({
        "layout": pick(seed, "layout", index, LAYOUTS), "box": pick(seed, "box", index, (True, False)),
        "hours": pick(seed, "hours", index, (True, True, False)), "ytd_hours": pick(seed, "ytdhours", index, (False, True)),
        "rate4": pick(seed, "rate4", index, (False, True)), "order": pick(seed, "order", index, ORDERS),
        "heading": pick(seed, "heading", index, HEADINGS), "ytd": pick(seed, "ytd", index, (True, True, False)),
        "ytd_only": pick(seed, "ytdonly", index, (False, False, True)), "retro": pick(seed, "retro", index, (False, True)),
        "negative": pick(seed, "negative", index, (False, False, True)), "digits": pick(seed, "digits", index, (False, True)),
        "sign": pick(seed, "sign", index, SIGNS), "totals": pick(seed, "totals", index, TOTALS),
        "employer_col": pick(seed, "employer", index, (False, False, True)), "wrap": pick(seed, "wrap", index, (False, True)),
        "pages": pick(seed, "pages", index, (1, 1, 2)), "deposit": pick(seed, "deposit", index, (False, True)),
        "leave": pick(seed, "leave", index, (False, True)), "stubs": pick(seed, "stubs", index, (1, 2, 3, 4, 1, 2)),
        "per_page": pick(seed, "perpage", index, (1, 2)), "head_order": pick(seed, "headorder", index, ("above", "below")),
        "dates": pick(seed, "dates", index, ("date", "date", "both_date", "both_period")),
        "box_heads": pick(seed, "boxheads", index, ("known", "known", "none")), "box_shuffled": pick(seed, "boxshuffle", index, (False, True)),
        "stack_heads": pick(seed, "stackheads", index, (False, True)), "net_row": pick(seed, "netrow", index, (True, True, False)),
        "hours_multiple": pick(seed, "hoursmultiple", index, (False, False, True)), "break_table": pick(seed, "breaktable", index, (3, 2)),
        "lined_up": pick(seed, "linedup", index, (False, True)),
    })


def make(seed, index, **overrides) -> Layout:
    """The `index`th case of `seed`. `overrides` replace drawn choices (for a fixed layout in the eval corpus); the rules still apply."""
    choices = settle({**draw(seed, index), **overrides})
    return Case(random.Random(f"{seed}:{index}"), choices).build()


class Case:
    def __init__(self, rng, choices):
        self.rng = rng
        self.c = choices
        self.ytd = choices["ytd"]
        self.sign = choices["sign"]
        self.last = 500 + rng.choice((0, 10, 20))  # The rightmost money column's right edge.
        self.employer = rng.choice(EMPLOYERS)
        self.title = rng.choice(TITLES)
        self.date_label = rng.choice(DATE_LABELS)
        self.gross_label = rng.choice(GROSS_LABELS)
        self.net_label = rng.choice(NET_LABELS)
        self.cur_word, self.ytd_word = rng.choice(CURRENT_YTD)
        if choices["heading"] == "known2":
            self.cur_word, self.ytd_word = "This Period", "Year to Date"  # Headings of two lines print words that need two.
        self.stack_titles = rng.choice(STACK_TITLES)
        self.box_labels = rng.choice(BOX_LABELS)
        order = list(range(4))
        if choices["box_shuffled"]:
            while order == list(range(4)):
                rng.shuffle(order)
        self.box_order = order
        self.drawn = {"deposit": True, "leave": True}

    # --- The money of one stub ----------------------------------------------------------------------------------------------

    def row(self, label, group, category, current, ytd, **more):
        return {"label": label, "description": label, "group": group, "category": category, "current": current, "ytd": ytd, "hours": None, "rate": None,
                "yhours": None, "wrap": None, "employer": None, **more}

    def hourly(self, label, category, first):
        rng, c = self.rng, self.c
        # Hours that equal the year-to-date multiple make hours × current the year to date as well as hours × rate the current (`hours_multiple`, FR-92 e).
        hundredths = rng.choice([hours for hours in (800, 1250, 1600, 2400, 3200, 4000, 1000, 2050) if hours != self.multiple * 100])
        if c["hours_multiple"]:
            hundredths = self.multiple * 100  # After the draw, so the rest of the stub's numbers are the ones the draw gave.
        four = c["rate4"] and first
        rate = rng.randrange(1500, 9500) * 100 + (rng.choice((25, 50, 75)) if four else 0)
        multiple = self.multiple
        row = self.row(label, "earnings", category, times(hundredths, rate), times(hundredths * multiple, rate))
        row.update(hours=hours_text(hundredths), rate=rate_text(rate, four), yhours=hours_text(hundredths * multiple))
        return row

    def stub_rows(self):
        """The pay lines of one stub (earnings, taxes, pre-tax deductions) with their this-period and year-to-date minor units."""
        rng, c = self.rng, self.c
        self.multiple = rng.randint(2, 24)  # How many pay periods the year to date holds: every line's year to date is about this many times its amount.
        earnings = []
        if c["hours"]:
            earnings.append(self.hourly("Regular", "regular_pay", True))
            if rng.random() < 0.7 or c["heading"] == "none":  # A column needs two rows to be found without a heading (FR-04).
                earnings.append(self.hourly("Overtime", "overtime", False))
            if rng.random() < 0.3:
                earnings.append(self.hourly("Holiday Pay", "other_earnings", False))
            if rng.random() < 0.4:
                earnings.append(self.row("Shift Premium", "earnings", "other_earnings", rng.randint(5000, 30000), None))
        else:
            earnings.append(self.row(rng.choice(SALARIED), "earnings", "regular_pay", rng.randint(150000, 450000), None))
            if rng.random() < 0.5:
                earnings.append(self.row("Commission", "earnings", "commission", rng.randint(10000, 90000), None))
        if c["retro"]:
            earnings.append(self.row("Retro Pay", "earnings", "other_earnings", rng.randint(5000, 40000), None))
        if c["negative"]:
            earnings.append(self.row("Prior Period Adjustment", "earnings", "other_earnings", -rng.randint(1500, 4000), rng.randint(30000, 90000)))
        if c["ytd_only"]:
            earnings.append(self.row("Relocation Bonus", "earnings", "bonus", None, rng.randint(100000, 800000)))
        for item in earnings:
            if item["ytd"] is None:
                item["ytd"] = item["current"] * self.multiple
        gross = sum(item["current"] or 0 for item in earnings)
        taxes = []
        for label, category, _ in [FEDERAL, *rng.sample(TAXES, rng.randint(1, 3))]:
            current = max(500, gross * SHARES[category] // 100 + rng.randint(0, 99))
            taxes.append(self.row(label, "tax", category, current, current * self.multiple))
        if c["wrap"]:
            taxes[0].update(wrap="Tax Withholding", label="Federal Income", description="Federal Income Tax Withholding")
        pre = []
        if c["digits"]:
            names = [(rng.choice(("401K", "PRE-TAX 401K")), "retirement_pretax"), *rng.sample(PRE_TAX_DIGITS, rng.randint(0, 2))]
        else:
            names = rng.sample(PRE_TAX_PLAIN, rng.randint(1, 3))
        for label, category in names:
            current = max(500, gross * rng.randint(2, 5) // 100 + rng.randint(0, 99))
            pre.append(self.row(label, "pre_tax", category, current, current * self.multiple))
        if c["employer_col"]:
            pre[0]["employer"] = max(100, pre[0]["current"] * rng.randint(30, 80) // 100)
        return earnings, taxes, pre

    # --- Columns and headings -----------------------------------------------------------------------------------------------

    def columns(self):
        """The money columns of the first (or only) table, left to right: [(key, right edge)]; keys are h, r, c, y and yh (year-to-date hours)."""
        c = self.c
        money_keys = (["c", "yh", "y"] if c["ytd_hours"] else ["c", "y"]) if self.ytd else ["c"]
        if c["order"] in ("hr_yc", "yc_hr"):
            money_keys.reverse()
        hours = ["h", "r"] if c["hours"] else []
        keys = hours + money_keys if c["order"].startswith("hr") else money_keys + hours
        return [(key, self.last - SPACING * (len(keys) - 1 - spot)) for spot, key in enumerate(keys)]

    def words(self):
        """The heading wording of every column key as (upper line, lower line)."""
        style = self.c["heading"]
        if style == "known1":
            return {"h": ("", "Hours"), "r": ("", "Rate"), "c": ("", self.cur_word), "y": ("", self.ytd_word), "yh": ("", "YTD Hours"), "e": ("", "Employer")}
        if style == "known2":
            split = {"Current": ("Current", ""), "YTD": ("YTD", ""), "This Period": ("This", "Period"), "Year to Date": ("Year to", "Date")}
            return {"h": ("", "Hours"), "r": ("", "Rate"), "c": split[self.cur_word], "y": split[self.ytd_word], "yh": ("YTD", "Hours"), "e": ("", "Employer")}
        if style == "unknown1":
            return {"h": ("", "Delta"), "r": ("", "Omega"), "c": ("", "Alpha"), "y": ("", "Beta"), "yh": ("", "Gamma"), "e": ("", "Sigma")}
        return {"h": ("Column", "C"), "r": ("Column", "D"), "c": ("Column", "A"), "y": ("Column", "B"), "yh": ("Column", "E"), "e": ("Column", "F")}

    def cells(self, source, group):
        """The printed text of every column key of a row (or total) with these amounts."""
        cells = {"c": amount(source["current"], self.sign, group)}
        if self.ytd:
            cells["y"] = amount(source["ytd"], self.sign, group)
        for key, name in (("h", "hours"), ("r", "rate"), ("yh", "yhours")):
            if source.get(name):
                cells[key] = source[name]
        if source.get("employer"):
            cells["e"] = money(source["employer"])
        return cells

    # --- Printing -----------------------------------------------------------------------------------------------------------

    def top_lines(self, stub):
        """The lines at the top of a stub, in print order."""
        dates = [f"{self.date_label} {stub['pay_date']}", f"Pay period {stub['period']}"]
        if self.c["dates"] == "date":
            dates = dates[:1]
        elif self.c["dates"] == "both_period":
            dates.reverse()
        head = [self.employer, self.title]
        lines = [*head, *dates, "Currency USD"] if self.c["head_order"] == "above" else [*dates, *head, "Currency USD"]
        return lines, dates[0]

    def build(self):
        c, rng = self.c, self.rng
        first = date(2026, 1, 2) + timedelta(days=14 * rng.randint(0, 12))
        stubs = []
        for number in range(c["stubs"]):
            pay = first + timedelta(days=14 * number)
            period = f"{pay - timedelta(days=18)} to {pay - timedelta(days=5)}"
            stub = {"pay_date": pay.isoformat(), "period": period}
            stub["rows"] = self.stub_rows()
            stubs.append(stub)
        printed = [self.print_stub(stub) for stub in stubs]
        pages, answers = self.pack(printed, stubs)
        choices = {**c, "pages": max(len(p["pages"]) for p in printed), "deposit": self.drawn["deposit"] and c["deposit"],
                   "leave": self.drawn["leave"] and c["leave"], "per_page": 2 if any(p.get("shared") for p in printed) else 1}
        return Layout(pages=pages, answers=answers, choices=choices)

    def print_stub(self, stub):
        """One stub's pages (item lists from y 780) and its answer. Pairing on a page is done by `pack`."""
        c = self.c
        earnings, taxes, pre = stub["rows"]
        gross = {"current": sum(item["current"] or 0 for item in earnings), "ytd": sum(item["ytd"] or 0 for item in earnings)}
        tax = {"current": sum(item["current"] for item in taxes), "ytd": sum(item["ytd"] for item in taxes)}
        ded = {"current": sum(item["current"] for item in pre), "ytd": sum(item["ytd"] for item in pre)}
        net = {key: gross[key] - tax[key] - ded[key] for key in ("current", "ytd")}
        totals = {"gross": {"label": self.gross_label, **gross, "group": "earnings"}, "taxes": {"label": "Total Taxes", **tax, "group": "tax"},
                  "deductions": {"label": "Total Pre-Tax Deductions", **ded, "group": "pre_tax"}, "net": {"label": self.net_label, **net, "group": "earnings"}}
        lines, start = self.top_lines(stub)
        base = TOP - 12 * (len(lines) - 1)
        state = {"pages": [], "items": [], "needles": {}, "lowest": TOP, "lines": lines, "base": base, "net": net, "totals": totals}
        self.page_header(state, lines)
        y = self.box(state, stub, totals, base)
        if c["layout"] == "side":
            y = self.side(state, y, earnings, taxes, pre, totals)
        else:
            y = self.stacked(state, y, earnings, taxes, pre, totals)
        y = self.extras(state, y, net)
        state["pages"].append(state["items"])
        printed = self.answer(stub, state, start, earnings, taxes, pre, gross, tax, ded, net)
        return {"pages": state["pages"], "answer": printed, "lowest": state["lowest"]}

    def page_header(self, state, lines):
        for number, text in enumerate(lines):
            state["items"].append((LABEL_X, TOP - 12 * number, text))

    def emit(self, state, x, y, text, right=False):
        state["items"].append(put(x, y, text, right))
        state["lowest"] = min(state["lowest"], y)

    def print_row(self, state, y, label, cells, columns, x=LABEL_X, needle=None, wrap=None):
        """A pay row: the label at x and the cells right-aligned at their columns' edges. Returns the printed needle of the row (label and its first
        amount), which cites the row."""
        self.emit(state, x, y, label)
        first = None
        for key, edge in sorted(columns, key=lambda pair: pair[1]):
            if cells.get(key):
                self.emit(state, edge, y, cells[key], right=True)
                first = first or cells[key]
        if "e" in cells:
            self.emit(state, self.last + 80, y, cells["e"], right=True)
        if wrap:
            self.emit(state, x + 12, y - 8, wrap)
        return f"{label} {first}" if first else None

    def heading(self, state, y, columns, label, x=LABEL_X, employer=False):
        """The heading lines of a table whose first line is at y; returns the y of the first row."""
        style = self.c["heading"]
        if style == "none":
            return y - 20
        words = self.words()
        two = style.endswith("2")
        pairs = [(key, edge) for key, edge in columns] + ([("e", self.last + 80)] if employer else [])
        if two:
            for key, edge in pairs:
                if words[key][0]:
                    self.emit(state, edge, y, words[key][0], right=True)
            y -= 12
        self.emit(state, x, y, label)
        for key, edge in pairs:
            if words[key][1]:
                self.emit(state, edge, y, words[key][1], right=True)
        return y - 20

    # --- Summary box ----------------------------------------------------------------------------------------------------------

    def box(self, state, stub, totals, base):
        """The summary box under the lines at the top (page 1): returns the y of the table's first heading line."""
        y = base - 24
        if not self.c["box"]:
            return y
        order = self.box_order
        values = {"current": [totals["gross"]["current"], totals["taxes"]["current"], totals["deductions"]["current"], totals["net"]["current"]],
                  "ytd": [totals["gross"]["ytd"], totals["taxes"]["ytd"], totals["deductions"]["ytd"], totals["net"]["ytd"]]}
        edges = [BOX_EDGES[spot] for spot in range(4)]
        if self.c["box_heads"] == "known":
            for spot, which in enumerate(order):
                self.emit(state, edges[spot], y, BOX_NAMES[which], right=True)
            y -= 16
        state["box"] = {}
        for name, label in zip(("current", "ytd"), self.box_labels):
            self.emit(state, LABEL_X, y, label)
            texts = [money(values[name][which]) for which in order]
            for edge, text in zip(edges, texts):
                self.emit(state, edge, y, text, right=True)
            state["box"][name] = (f"{label} {texts[0]}", dict(zip(BOX_NAMES, (money(values[name][which]) for which in range(4)))))
            y -= 16
        return y - 12

    # --- Tables ---------------------------------------------------------------------------------------------------------------

    def total_cells(self, kind, totals, keys):
        total = totals[kind]
        text = lambda minor: amount(minor, self.sign, "earnings" if kind in ("gross", "net") else total["group"])  # noqa: E731
        return {key: text(total["current" if key == "c" else "ytd"]) for key in keys}

    def record(self, state, name, needle, cells):
        state["needles"][name] = (needle, cells)

    def elements(self, earnings, taxes, pre, totals, stacked):
        """The printed order of rows and totals: ("row", row) or ("total", kind). A stacked layout's tables start at ("table", n)."""
        c = self.c
        order = [("row", item) for item in earnings]
        if c["totals"] != "none":
            order.append(("total", "gross"))
        order.append(("table", 2)) if stacked else None
        order += [("row", item) for item in taxes]
        if c["totals"] == "all":
            order.append(("total", "taxes"))
        order.append(("table", 3)) if stacked else None
        order += [("row", item) for item in pre]
        if c["totals"] == "all":
            order.append(("total", "deductions"))
        if c["net_row"]:
            order.append(("total", "net"))
        return order

    def stacked(self, state, y, earnings, taxes, pre, totals):
        """One table (layout `one`) or three stacked tables (layout `stacked`), over one or two pages."""
        c = self.c
        stacked = c["layout"] == "stacked"
        columns = self.columns()
        keys = [key for key, _ in columns]
        second = self.second_columns(keys)
        order = self.elements(earnings, taxes, pre, totals, stacked)
        flat_break = None
        if c["pages"] == 2:
            if stacked:
                flat_break = next(index for index, item in enumerate(order) if item == ("table", c["break_table"]))
            else:
                spot = max(index for index, item in enumerate(order) if item[0] == "row" and item[1]["group"] == "earnings")
                flat_break = spot + 1 + (1 if c["totals"] != "none" else 0)
        cols, table = columns, 1
        row_y = self.heading(state, y, columns, "Description" if c["heading"].startswith("known") else "Item", employer=c["employer_col"])
        for index, element in enumerate(order):
            if index == flat_break:
                state["pages"].append(state["items"])
                state["items"] = []
                self.page_header(state, state["lines"])
                row_y = state["base"] - 24
                if stacked and c["break_table"] == 2:
                    pass  # The second table's own heading or title opens the page (FR-92 b).
                elif (not stacked or c["stack_heads"]) and c["heading"] != "none":
                    row_y = self.heading(state, row_y, cols, "Description" if c["heading"].startswith("known") else "Item", employer=c["employer_col"] and not stacked)
                else:
                    row_y = state["base"] - 44
            if element[0] == "table":
                table = element[1]
                cols = second
                row_y -= ROW
                if c["stack_heads"]:
                    row_y = self.heading(state, row_y, cols, "Description" if c["heading"].startswith("known") else "Item")
                else:
                    self.emit(state, LABEL_X, row_y, self.stack_titles[table - 2])
                    row_y -= ROW
                continue
            if element[0] == "row":
                item = element[1]
                needle = self.print_row(state, row_y, item["label"], self.cells(item, item["group"]), cols, wrap=item["wrap"])
                state["needles"][id(item)] = needle
                row_y -= ROW + (8 if item["wrap"] else 0)
            else:
                kind = element[1]
                label = totals[kind]["label"]
                cells = self.total_cells(kind, totals, [key for key, _ in cols if key in ("c", "y")])
                needle = self.print_row(state, row_y, label, cells, cols)
                state["needles"][kind] = (needle, cells)
                row_y -= ROW
        return row_y

    def second_columns(self, keys):
        """The columns of a stacked layout's second and third tables: the current and year-to-date columns, 33 points left of the first table's last two."""
        wanted = [key for key in keys if key in ("c", "y")]
        edges = [self.last - 33 - SPACING * (len(wanted) - 1 - spot) for spot in range(len(wanted))]
        return list(zip(wanted, edges))

    def side(self, state, y, earnings, taxes, pre, totals):
        """Two blocks on shared lines: earnings (and the gross and net lines) on the left, taxes and deductions on the right."""
        c = self.c
        pairs = SIDE if self.ytd else ((SIDE_ONE[0],), (SIDE_ONE[1],))
        keys = ["c", "y"] if self.ytd else ["c"]
        if c["order"] in ("hr_yc", "yc_hr"):
            keys.reverse()
        left_columns = list(zip(keys, sorted(pairs[0])))
        right_columns = list(zip(keys, sorted(pairs[1])))
        left = [("row", item) for item in earnings] + ([("total", "gross")] if c["totals"] != "none" else [])
        right = [("row", item) for item in taxes] + ([("total", "taxes")] if c["totals"] == "all" else []) + [("row", item) for item in pre]
        right += [("total", "deductions")] if c["totals"] == "all" else []
        if c["net_row"]:
            spot = max(len(left), len(right) - 1)
            left += [None] * (spot - len(left)) + [("total", "net")]
        count = max(len(left), len(right))
        words = self.words()
        style = c["heading"]
        head_y = y
        if style != "none":
            if style.endswith("2"):
                for columns in (left_columns, right_columns):
                    for key, edge in columns:
                        if words[key][0]:
                            self.emit(state, edge, head_y, words[key][0], right=True)
                head_y -= 12
            for label, x, columns in (("Earnings", LABEL_X, left_columns), ("Deductions", RIGHT_X, right_columns)):
                self.emit(state, x, head_y, label)
                for key, edge in columns:
                    if words[key][1]:
                        self.emit(state, edge, head_y, words[key][1], right=True)
            row_y = head_y - 20
        else:
            row_y = y - 20
        for number in range(count):
            for block, x, columns in ((left, LABEL_X, left_columns), (right, RIGHT_X, right_columns)):
                element = block[number] if number < len(block) else None
                if element is None:
                    continue
                if element[0] == "row":
                    item = element[1]
                    state["needles"][id(item)] = self.print_row(state, row_y, item["label"], self.cells(item, item["group"]), columns, x=x)
                else:
                    kind = element[1]
                    cells = self.total_cells(kind, totals, [key for key, _ in columns])
                    state["needles"][kind] = (self.print_row(state, row_y, totals[kind]["label"], cells, columns, x=x), cells)
            row_y -= ROW
        state["side_edge"] = left_columns[0][1]
        return row_y

    def leave_edges(self, state, lined=False):
        """The right edges of the leave table's three columns: the contract's (which line up with the pay columns of a plain stub) unless one of its
        amounts would line up by its left, centre or right edge, within the engine's tolerance, with an amount already printed; then the first set
        that doesn't. With `lined` (FR-92 f), the first set (the contract's, then the same scan) that does line up, by its left or centre edge, with
        an amount already printed. None when there is none."""
        amounts = [(x, x + width(text)) for x, _, text in state["items"] if AMOUNT.fullmatch(text)]
        pairs = lambda one, two: ((one[0], two[0]), (sum(one) / 2, sum(two) / 2)) if lined else ((one[0], two[0]), (one[1], two[1]), (sum(one) / 2, sum(two) / 2))  # noqa: E731
        aligned = lambda one, two: any(abs(a - b) <= 20 for a, b in pairs(one, two))  # noqa: E731
        for first in (None, *range(60, 400, 10)):
            option = LEAVE_EDGES if first is None else (first + 90, first + 160, first + 230)
            leave = [(edge - width(text), edge) for edge, texts in zip(option, (("40.00", "24.00", "8.00"), ("8.00", "0.00", "24.00"), ("32.00", "24.00", "0.00")))
                     for text in texts]
            if any(aligned(one, two) for one in leave for two in amounts) == lined:
                return option
        return None

    def extras(self, state, y, net):
        """The deposit and leave tables under the pay table, when the page has room."""
        c = self.c
        edge = state.get("side_edge") if c["layout"] == "side" else dict(self.columns()).get("c")
        edge = edge or self.columns()[0][1]
        if c["deposit"]:
            lines = 4
            if y - 24 - ROW * lines < FLOOR:
                self.drawn["deposit"] = False
            else:
                y -= 24
                self.emit(state, LABEL_X, y, "Direct Deposit")
                self.emit(state, LABEL_X, y - ROW, "Account")
                self.emit(state, edge, y - ROW, "Amount", right=True)
                remainder = net["current"] // 4
                for number, (label, minor) in enumerate((("Checking 1234", net["current"] - remainder), ("Savings 5678", remainder))):
                    self.emit(state, LABEL_X, y - ROW * (2 + number), label)
                    self.emit(state, edge, y - ROW * (2 + number), money(minor), right=True)
                y -= ROW * 4
        if c["leave"]:
            leave = self.leave_edges(state, c["lined_up"])
            if y - 24 - ROW * 3 < FLOOR or leave is None:
                self.drawn["leave"] = False
            else:
                y -= 24
                self.emit(state, LABEL_X, y, "Leave")
                for edge_x, text in zip(leave, ("Accrued", "Used", "Balance")):
                    self.emit(state, edge_x, y, text, right=True)
                for number, values in enumerate((("Vacation", "40.00", "8.00", "32.00"), ("Sick", "24.00", "0.00", "24.00"))):
                    self.emit(state, LABEL_X, y - ROW * (1 + number), values[0])
                    for edge_x, text in zip(leave, values[1:]):
                        self.emit(state, edge_x, y - ROW * (1 + number), text, right=True)
                y -= ROW * 3
        return y

    # --- What the stub means --------------------------------------------------------------------------------------------------

    def answer(self, stub, state, start, earnings, taxes, pre, gross, tax, ded, net):
        c = self.c
        needles = state["needles"]
        lines = []
        for item in [*earnings, *taxes, *pre]:
            lines.append({"description": item["description"], "label": item["label"], "group": item["group"], "category": item["category"], "current": item["current"],
                          "ytd": item["ytd"] if self.ytd else None, "hours": item["hours"] if c["hours"] else None,
                          "rate": item["rate"] if c["hours"] else None, "cite": needles[id(item)]})
        printed, box = {}, state.get("box")
        for kind, name, values in (("gross", "gross", gross), ("taxes", "taxes", tax), ("deductions", "deductions", ded), ("net", "net", net)):
            entry = {}
            if kind in needles and kind in needles:
                needle, cells = needles[kind]
                entry = {"current": (needle, cells["c"]), "ytd": (needle, cells["y"]) if self.ytd else None}
            elif box:
                entry = {"current": (box["current"][0], box["current"][1][BOX_NAMES[("gross", "taxes", "deductions", "net").index(kind)]]),
                         "ytd": (box["ytd"][0], box["ytd"][1][BOX_NAMES[("gross", "taxes", "deductions", "net").index(kind)]])}
            if entry:
                printed[name] = {"values": values, "current": entry["current"], "ytd": entry["ytd"]}
        out = {"employer": self.employer, "pay_date": stub["pay_date"], "date_line": f"{self.date_label} {stub['pay_date']}", "currency_line": "Currency USD",
               "title_line": self.title, "start": start, "above": 2 if c["head_order"] == "above" else 0, "lines": lines, "printed": printed,
               "box_guess": bool(c["box"]) and c["box_heads"] == "none"}
        out["gross"] = {"current": gross["current"] if "gross" in printed else None, "ytd": gross["ytd"] if "gross" in printed and self.ytd else None}
        out["net"] = {"current": net["current"] if "net" in printed else None, "ytd": net["ytd"] if "net" in printed and self.ytd else None}
        out["taxes"] = tax["current"] if "taxes" in printed else None
        out["deductions"] = ded["current"] if "deductions" in printed else None
        return out

    # --- Pages ---------------------------------------------------------------------------------------------------------------

    def pack(self, printed, stubs):
        """The file's pages: each stub on its own page(s), or two single-page stubs on one page when `per_page` is 2 and both fit."""
        pages, answers, spot = [], [], 0
        while spot < len(printed):
            one = printed[spot]
            two = printed[spot + 1] if spot + 1 < len(printed) else None
            answers.append(one["answer"])
            if (self.c["per_page"] == 2 and two and len(one["pages"]) == 1 and len(two["pages"]) == 1
                    and one["lowest"] - 36 - (TOP - two["lowest"]) >= FLOOR):
                shift = TOP - (one["lowest"] - 36)
                moved = [(x, round(y - shift, 3), text) for x, y, text in two["pages"][0]]
                pages.append({"items": [*one["pages"][0], *moved, (LABEL_X, 60, FOOTER)]})
                answers.append(two["answer"])
                one["shared"] = True
                spot += 2
                continue
            for items in one["pages"]:
                pages.append({"items": [*items, (LABEL_X, 60, FOOTER)]})
            spot += 1
        return pages, answers


# --- What a case shows -------------------------------------------------------------------------------------------------------

REQUIRED = (
    "layout:one", "layout:stacked", "layout:side", "summary:with", "summary:without", "hours:with", "hours:without", "ytd_hours", "rate:4_decimals",
    "columns:current_first", "columns:ytd_first", "columns:hours_first", "columns:hours_last",
    "heading:known", "heading:unknown", "heading:none", "heading:one_line", "heading:two_lines", "ytd:with", "ytd:without", "ytd_only_row",
    "retro", "negative", "label_digits", "deductions:parens", "deductions:minus", "totals:all", "totals:some", "totals:none", "employer_column",
    "wrapped_label", "pages:2", "deposit_table", "leave_table", "stubs:1", "stubs:2", "stubs:3", "stubs:4", "employer:above", "employer:below",
    "date_and_period", "two_on_a_page", "summary_box:no_headings", "summary_box:shuffled",
    "negative_rows:ytd_first_unheaded", "stacked:second_table_starts_page", "one_column:two_line_heading", "hours:ytd_multiple", "leave:lined_up",
)


def variations(layout) -> set[str]:
    """The FR-70 variations a case actually shows, from what was printed (the generator test counts each of `REQUIRED` in at least three cases)."""
    c = layout.choices
    found = {f"layout:{c['layout']}", f"summary:{'with' if c['box'] else 'without'}", f"hours:{'with' if c['hours'] else 'without'}",
             f"ytd:{'with' if c['ytd'] else 'without'}", f"stubs:{c['stubs']}", f"employer:{c['head_order']}",
             f"totals:{'all' if c['totals'] == 'all' else 'none' if c['totals'] == 'none' else 'some'}"}
    if c["ytd_hours"]:
        found.add("ytd_hours")
    if c["rate4"]:
        found.add("rate:4_decimals")
    found.add("columns:ytd_first" if c["order"] in ("hr_yc", "yc_hr") and c["ytd"] else "columns:current_first")
    found.add("columns:hours_first" if c["order"].startswith("hr") and c["hours"] else "columns:hours_last")
    if c["hours"] is False:
        found -= {"columns:hours_first", "columns:hours_last"}
    found.add("heading:none" if c["heading"] == "none" else "heading:unknown" if c["heading"].startswith("unknown") else "heading:known")
    if c["heading"] != "none":
        found.add("heading:two_lines" if c["heading"].endswith("2") else "heading:one_line")
    for tag, key in (("ytd_only_row", "ytd_only"), ("retro", "retro"), ("negative", "negative"), ("label_digits", "digits"), ("employer_column", "employer_col"),
                     ("wrapped_label", "wrap"), ("deposit_table", "deposit"), ("leave_table", "leave")):
        if c[key]:
            found.add(tag)
    if c["sign"] != "plain":
        found.add(f"deductions:{'parens' if c['sign'] == 'paren' else 'minus'}")
    if c["pages"] > 1:
        found.add("pages:2")
    if c["dates"] != "date":
        found.add("date_and_period")
    if c["per_page"] == 2:
        found.add("two_on_a_page")
    if c["box"] and c["box_heads"] == "none":
        found.add("summary_box:no_headings")
    if c["box"] and c["box_shuffled"]:
        found.add("summary_box:shuffled")
    if (c["sign"] != "plain" and c["ytd"] and c["order"] in ("hr_yc", "yc_hr")
            and ((c["layout"] == "stacked" and not c["stack_heads"]) or (c["layout"] == "side" and c["heading"] not in ("known1", "known2"))
                 or (c["layout"] == "stacked" and c["heading"] not in ("known1", "known2")))):
        found.add("negative_rows:ytd_first_unheaded")  # Taxes and deductions printed negative, year to date on the left, nothing naming the columns.
    if c["layout"] == "stacked" and c["pages"] > 1 and c["break_table"] == 2:
        found.add("stacked:second_table_starts_page")
    if not c["ytd"] and c["heading"] == "known2":
        found.add("one_column:two_line_heading")
    if c["hours_multiple"]:
        found.add("hours:ytd_multiple")
    if c["leave"] and c["lined_up"]:
        found.add("leave:lined_up")
    return found
