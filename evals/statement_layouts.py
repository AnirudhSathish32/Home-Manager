"""A seeded generator of aligned-column text-PDF bank and card statements (specs/pdf-table-engine FR-33, SC-18; plan P12).

  layout = make(seed, index)       # the same two numbers always give the same Layout

`Layout.pages` are positioned items in the form `tests/test_pdf.py make_pdf` takes: {"items": [(x, y, text), ...]}, 10 pt Helvetica, in
points, with each right-aligned amount placed from the Helvetica widths below. The generator writes no PDF. `Layout.answers` come only from
the generator's own inputs, never from a reader: the rows as (ISO date, signed amount in minor units, description) in print order, the
printed period as ISO dates (or None), the printed opening and closing balances in minor units (or None) and the kind (`bank` or `card`).
`Layout.choices` names what was drawn, for failure messages and for the coverage count.

Every dimension FR-33 names is varied, each by a balanced draw (`pick`): over any run of consecutive indices every value of a dimension comes
up equally often, so the coverage holds for any seed. Rules that keep each case decidable under the spec (SC-18): a case prints a running
balance or a summary (or both); a year-less date comes with a printed period; a case whose numeric dates are all ≤ 12 prints a period that
decides the order; every amount column has at least two rows on a page of two or more rows (one with a heading printed on that page), because
a column needs two supporting rows (FR-04).
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
import random

SIZE = 10
LINE = 14  # Between the printed lines of one row, and between rows with no gap.
BOTTOM = 100  # No row starts below this y.
WIDTH_UNITS = {" ": 278, "!": 278, '"': 355, "#": 556, "$": 556, "%": 889, "&": 667, "'": 191, "(": 333, ")": 333, "*": 389, "+": 584, ",": 278,
               "-": 333, ".": 278, "/": 278, ":": 278, ";": 278, "<": 584, "=": 584, ">": 584, "?": 556, "@": 1015, "[": 278, "\\": 278, "]": 278}
WIDTH_UNITS.update({digit: 556 for digit in "0123456789"})
WIDTH_UNITS.update(dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", (667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667,
                                                           611, 722, 667, 944, 667, 667, 611))))
WIDTH_UNITS.update(dict(zip("abcdefghijklmnopqrstuvwxyz", (556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500,
                                                           278, 556, 500, 722, 500, 500, 500))))
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
PAGE_WORDS = ("zero", "one", "two", "three", "four", "five", "six")

DATE_STYLES = ("mdy4", "mdy2", "mdy_short", "mdy_dash", "dmy4", "dmy_short", "dmy_dot", "iso", "mon_d_short", "mon_d_year", "d_mon_year", "d_mon_short")
NUMERIC = frozenset(("mdy4", "mdy2", "mdy_short", "mdy_dash", "dmy4", "dmy_short", "dmy_dot"))
NO_YEAR = frozenset(("mdy_short", "dmy_short", "mon_d_short", "d_mon_short"))
NEEDS_PERIOD = NO_YEAR | {"mdy2"}  # A two-digit year is placed against the printed period (FR-14).
DAY_FIRST = frozenset(("dmy4", "dmy_short", "dmy_dot", "d_mon_year", "d_mon_short"))
SIGNS = ("signed", "inout", "crdr", "parens", "sectioned")
HEADINGS = ("none", "known1", "known2", "unknown1", "unknown2")
EXTRAS = ((), (), (), (), ("daily",), ("fees",), ("schedule",), ("daily", "fees"))
ROW_COUNTS = (6, 8, 11, 15, 21, 29, 40, 55, 70)

# What a column's heading says. Known wording is what the engine reads as a role; unknown wording says nothing.
KNOWN = {"in": ((("Deposits",), ("Credits",), ("Paid in",), ("Money in",)), (("Deposits/", "Additions"), ("Money", "in"), ("Paid", "in"), ("Credit", "amount"))),
         "out": ((("Withdrawals",), ("Debits",), ("Paid out",), ("Money out",)), (("Withdrawals/", "Subtractions"), ("Money", "out"), ("Paid", "out"), ("Debit", "amount"))),
         "balance": ((("Balance",), ("Running balance",), ("Account balance",)), (("Ending daily", "balance"), ("Running", "balance"), ("Account", "balance"))),
         "signed": ((("Amount",), ("Transaction amount",), ("Amount",)), (("Transaction", "amount"), ("Posted", "amount"), ("Net", "amount")))}
UNKNOWN = {role: ((("Alpha",), ("Beta",), ("Gamma",), ("Delta",)), (("Column", "one"), ("Column", "two"), ("Column", "three"), ("Column", "four")))
           for role in KNOWN}
DATE_HEADS = ("Date", "Posted", "Date")
DESCRIPTION_HEADS = ("Description", "Details", "Transaction")
WORDS = ("SYNTH", "MARKET", "GROCER", "CAFE", "FUEL", "RENT", "PAYROLL", "TRANSFER", "REFUND", "PHARMACY", "BOOKSTORE", "STREAMING", "ELECTRIC", "WATER",
         "INSURANCE", "TAXI", "HARDWARE", "FOODS", "OUTLET", "CLINIC", "MOBILE", "INTEREST", "SERVICE", "ONLINE", "STORE", "SUPPLY", "CARD", "PURCHASE",
         "DEPOSIT", "MEMBERSHIP", "GARAGE", "BAKERY", "TICKETS", "TRAVEL", "HOTEL", "CINEMA", "SPRINGFIELD", "WHOLESALE", "PARKING", "GIFTS")
IN_SECTIONS = ("Payments and Credits", "Payments", "Credits and Refunds")
OUT_SECTIONS = ("Purchases", "Purchases and Fees", "Charges and Interest")
BANKS = ("SYNTH FIRST BANK", "SYNTH LOCAL BANK", "SYNTH SAVINGS BANK", "SYNTH TRUST BANK")
CARDS = ("SYNTH REWARDS CARD", "SYNTH TRAVEL CARD", "SYNTH EVERYDAY CARD")


@dataclass
class Layout:
    pages: list = field(default_factory=list)  # [{"items": [(x, y, text), ...]}, ...], as tests/test_pdf.py make_pdf takes them.
    answers: dict = field(default_factory=dict)  # rows [(ISO date, signed minor, description)], period, opening, closing, kind.
    choices: dict = field(default_factory=dict)


# --- Small helpers -----------------------------------------------------------------------------------------------------------

def width(text):
    return sum(WIDTH_UNITS[char] for char in text) * SIZE / 1000


def put(x, y, text, right=False):
    """An item at x (its left), or ending at x when `right`."""
    return (round(x - width(text), 3) if right else x, y, text)


def money(minor):
    return f"{minor // 100:,}.{minor % 100:02d}"


def pick(seed, name, index, values):
    """A balanced draw: every block of len(values) consecutive indices holds each value once, in an order drawn from the seed and the block."""
    block, spot = divmod(index, len(values))
    return random.Random(f"{seed}:{name}:{block}").sample(list(values), len(values))[spot]


def when(day, style, full_year=False):
    """A date as printed in this style. `full_year` forces a four-digit year (the printed period)."""
    if style in NO_YEAR and not full_year:
        style = {"mdy_short": "mdy4", "dmy_short": "dmy4", "mon_d_short": "mon_d_year", "d_mon_short": "d_mon_year"}[style]
        year = False
    else:
        year = True
    month = MONTHS[day.month - 1]
    if style in ("mdy4", "mdy_short"):
        return f"{day.month:02d}/{day.day:02d}/{day.year}" if year else f"{day.month:02d}/{day.day:02d}"
    if style == "mdy2":
        return f"{day.month:02d}/{day.day:02d}/{day.year % 100:02d}"
    if style == "mdy_dash":
        return f"{day.month:02d}-{day.day:02d}-{day.year}"
    if style in ("dmy4", "dmy_short"):
        return f"{day.day:02d}/{day.month:02d}/{day.year}" if year else f"{day.day:02d}/{day.month:02d}"
    if style == "dmy_dot":
        return f"{day.day:02d}.{day.month:02d}.{day.year}"
    if style == "iso":
        return day.isoformat()
    if style == "mon_d_year" or style == "mon_d_short":
        return f"{month} {day.day:02d}, {day.year}" if year else f"{month} {day.day}"
    return f"{day.day:02d} {month} {day.year}" if year else f"{day.day} {month}"


def other_way(day, style, start, end):
    """The date a reader would get by taking the printed day and month the other way round, or None when that is no date or lies outside the
    printed period by more than a week."""
    if day.day > 12:
        return None
    for year in (day.year, day.year - 1, day.year + 1):
        try:
            swapped = date(year, day.day, day.month)
        except ValueError:
            continue
        if start - timedelta(days=7) <= swapped <= end + timedelta(days=7):
            return swapped
    return None


def decides_order(days, style, start, end):
    """Whether the printed period settles the order of numeric dates: the other reading would put some row outside the period, or break the
    rows' order (the spec's rule, written out independently of the engine)."""
    swapped = [other_way(day, style, start, end) for day in days]
    if any(day is None for day in swapped):
        return True
    return any(second < first for first, second in zip(swapped, swapped[1:]))


# --- The case ----------------------------------------------------------------------------------------------------------------

def draw(seed, index):
    """The choices of one case (balanced per dimension). Dependent ones are settled after the independent draws."""
    kind = pick(seed, "kind", index, ("bank", "bank", "bank", "card"))
    signs = pick(seed, "signs", index, SIGNS)
    if signs == "sectioned" and kind == "bank":
        signs = "signed"
    heading = pick(seed, "heading", index, HEADINGS)
    if signs == "sectioned" and heading == "none":
        heading = "known1"  # A section title directly above a headless table's first row is not read as the title of its rows (docs: handoff SL-04).
    balance = pick(seed, "balance", index, (True, False, True, False, False))
    summary = pick(seed, "summary", index, (True, True, False))
    if kind == "card":
        balance = balance and signs != "sectioned" and pick(seed, "cardbalance", index, (True, False, False, False))
        summary = True
    elif not balance:
        summary = True
    if signs == "sectioned":
        balance = False
    small_days = pick(seed, "small", index, (False, False, True)) and signs != "sectioned"
    return {
        "kind": kind, "signs": signs, "heading": heading, "balance": balance, "summary": summary,
        "dates": pick(seed, "dates", index, DATE_STYLES), "date_once": pick(seed, "once", index, (False, False, True)),
        "wrap": pick(seed, "wrap", index, (1, 1, 2, 3)), "rows": pick(seed, "rows", index, ROW_COUNTS),
        "continuation_heading": pick(seed, "continuation", index, (True, False)),
        "extras": pick(seed, "extras", index, EXTRAS), "columns": pick(seed, "columns", index, (0, 1, 2, 3, 4, 5)),
        "small_days": small_days, "cross_year": pick(seed, "cross", index, (False, False, False, True)),
        "period_wanted": pick(seed, "period", index, (True, False)), "balances": pick(seed, "balances", index, ("all", "end_of_day", "some")),
        "row_gap": pick(seed, "gap", index, (0, 6)), "summary_dated": pick(seed, "dated", index, (False, False, False, True)),
        "summary_words": pick(seed, "words", index, (0, 1)), "separator": pick(seed, "separator", index, (" - ", " to ", " through ")),
    }


def make(seed, index, **overrides) -> Layout:
    """The `index`th case of `seed`. `overrides` replace drawn choices (for a fixed layout in the eval corpus); every rule still applies."""
    choices = {**draw(seed, index), **overrides}
    if choices["dates"] == "mdy2":
        # A two-digit year is placed only in the period's own years, so a schedule dated after the period would have no year at all.
        choices["extras"] = tuple(extra for extra in choices["extras"] if extra != "schedule")
    rng = random.Random(f"{seed}:{index}")
    return Case(rng, choices).build()


class Case:
    def __init__(self, rng, choices):
        self.rng = rng
        self.c = choices
        self.card = choices["kind"] == "card"
        self.style = choices["dates"]
        self.numeric = self.style in NUMERIC
        self.sectioned = choices["signs"] == "sectioned"

    # --- Dates, period -------------------------------------------------------------------------------------------------------

    def period_and_days(self):
        """The statement period and the row dates (sorted), redrawn until the dates are decidable under the spec's rules."""
        rng, c = self.rng, self.c
        count = c["rows"]
        for _ in range(60):
            year = rng.randint(2024, 2027)
            if c["cross_year"]:
                start = date(year, 12, rng.randint(14, 20))
            elif self.card or self.numeric:
                start = date(year, rng.randint(1, 12), rng.choice((1, 1, rng.randint(14, 27)))) if not self.card else date(year, rng.randint(1, 12), rng.randint(14, 27))
            else:
                start = date(year, rng.randint(1, 12), rng.choice((1, rng.randint(1, 27))))
            end = (start + timedelta(days=32)).replace(day=start.day) - timedelta(days=1) if start.day > 1 else (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            days = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
            if c["small_days"] and self.numeric:
                days = [day for day in days if day.day <= 12]
            if not days:
                continue
            if c["date_once"]:
                pool = rng.sample(days, min(len(days), max(2, count // 2)))
                chosen = sorted(pool)
                rows = list(chosen)
                while len(rows) < count:
                    rows.append(rng.choice(chosen))
                rows.sort()
            else:
                rows = sorted(rng.choice(days) for _ in range(count))
            rows = rows[:count]
            if self.sectioned:
                # Two sections restart the dates, so the rows are not in one run of increasing dates: a day over 12 must decide the order.
                if self.numeric and all(day.day <= 12 for day in rows):
                    continue
            if not self.numeric:
                return start, end, rows
            if any(day.day > 12 for day in rows):
                return start, end, rows
            if decides_order(rows, self.style, start, end) and (start.day > 12 or end.day > 12) and any(day.month != day.day for day in rows):
                return start, end, rows
        raise RuntimeError("no decidable dates drawn")

    def period_text(self, start, end):
        style = self.style if self.style not in NO_YEAR else {"mdy_short": "mdy4", "dmy_short": "dmy4", "mon_d_short": "mon_d_year", "d_mon_short": "d_mon_year"}[self.style]
        if style == "mdy2":
            style = "mdy4"
        prefix = self.rng.choice(("Statement period ", "Statement Period: ", "For the period ", "Billing cycle "))
        return f"{prefix}{when(start, style, True)}{self.c['separator']}{when(end, style, True)}"

    # --- Rows ----------------------------------------------------------------------------------------------------------------

    def describe(self, limit):
        """One description of 1 to `wrap` printed lines, each at most `limit` points wide."""
        rng = self.rng
        lines = rng.choice(range(1, self.c["wrap"] + 1)) if rng.random() < 0.6 else 1
        out = []
        for number in range(lines):
            line = []
            for _ in range(rng.randint(1, 3) if number == 0 else rng.randint(1, 2)):
                word = rng.choice(WORDS)
                if width(" ".join([*line, word])) > limit:
                    break
                line.append(word)
            if not line:
                line = [rng.choice(("CAFE", "FUEL", "RENT", "TAXI"))]
            out.append(" ".join(line))
        if rng.random() < 0.15:
            out[-1] = f"{out[-1]} {rng.randint(1000, 9999)}"
        return out

    def amounts(self, count, directions):
        rng = self.rng
        out = []
        for direction in directions:
            if self.card:
                size = rng.choice((rng.randint(100, 9999), rng.randint(1000, 30000))) if direction < 0 else rng.randint(1000, 40000)
            else:
                size = rng.choice((rng.randint(100, 9999), rng.randint(1000, 60000), rng.randint(10000, 150000))) if direction < 0 else rng.choice((rng.randint(5000, 50000), rng.randint(50000, 400000)))
            out.append(direction * size)
        return out

    # --- The whole case -------------------------------------------------------------------------------------------------------

    def build(self) -> Layout:
        rng, c = self.rng, self.c
        start, end, days = self.period_and_days()
        count = len(days)
        in_first = rng.random() < 0.7
        section_at = 0
        if self.sectioned:
            # Two sections, each in date order, so the dates restart at the second one.
            inward = rng.randint(1, max(1, min(count - 1, count // 3)))
            chosen = set(rng.sample(range(count), inward))
            money_in = [day for number, day in enumerate(days) if number in chosen]
            money_out = [day for number, day in enumerate(days) if number not in chosen]
            days = money_in + money_out if in_first else money_out + money_in
            section_at = inward if in_first else count - inward
        # Geometry: columns are listed left to right.
        roles = {"signed": ["signed"], "crdr": ["signed"], "parens": ["signed"], "sectioned": ["signed"], "inout": ["in", "out"]}[c["signs"]]
        if c["balance"]:
            roles = [*roles, "balance"]
        orders = [list(roles)]
        for role in roles:
            rest = [other for other in roles if other != role]
            orders.append([role, *rest])
            orders.append([*rest, role])
        unique = []
        for order in orders:
            if order not in unique:
                unique.append(order)
        roles = unique[c["columns"] % len(unique)]
        edge = rng.randint(540, 570)
        gap = self.gap = rng.randint(90, 100)
        edges = {role: edge - gap * (len(roles) - 1 - spot) for spot, role in enumerate(roles)}
        c["column_order"] = ",".join(roles)
        heading = c["heading"] != "none"
        two_lines = c["heading"].endswith("2")
        # Dates and descriptions.
        printed = [when(day, self.style) for day in days]
        date_x = 40
        description_x = date_x + int(max(width(text) for text in printed) // 5 + 1) * 5 + 22
        first_edge = edges[roles[0]]
        limit = first_edge - 66 - 24 - description_x
        descriptions = [self.describe(limit) for _ in range(count)]
        # Pages: the rows are broken by height. The first page holds the header block, so it starts lower.
        pages_rows, page = [], []
        y = 780 - 12 * 5 - 36 - 20 - (24 if self.sectioned else 0)
        for number in range(count):
            height = len(descriptions[number]) * LINE
            extra_title = LINE + 6 if self.sectioned and number in (0, section_at) else 0
            if page and y - extra_title - (len(descriptions[number]) - 1) * LINE < BOTTOM:
                pages_rows.append(page)
                page, y = [], 744 - (24 if heading and c["continuation_heading"] else 0) - (12 if two_lines and heading and c["continuation_heading"] else 0)
            page.append(number)
            y -= extra_title + height + c["row_gap"]
        pages_rows.append(page)
        # A last page of 2 or 3 rows would leave an amount column with one row; take rows from the page before.
        if len(pages_rows) > 1 and len(pages_rows[-1]) in (2, 3):
            need = 4 - len(pages_rows[-1])
            moved = pages_rows[-2][-need:]
            pages_rows[-2] = pages_rows[-2][:-need]
            pages_rows[-1] = moved + pages_rows[-1]
        dated = [not (c["date_once"] and number and days[number] == days[number - 1]) for number in range(count)]
        for position, numbers in enumerate(pages_rows):
            # Columns are found from dated lines (FR-04 builds them from the rows that print a date), so a page needs dated rows to carry them.
            headed = heading and (position == 0 or c["continuation_heading"])
            least = 1 if headed else 2
            if sum(dated[number] for number in numbers) < (2 * least if c["signs"] == "inout" else least) or len(numbers) == 1:
                for number in numbers:
                    dated[number] = True
        directions = self.directions(pages_rows, dated, heading, c)
        if self.sectioned:
            directions = [(1 if in_first else -1) if number < section_at else (-1 if in_first else 1) for number in range(count)]
        amounts = self.amounts(count, directions)
        opening = closing = None
        balances = [None] * count
        total = sum(amounts)
        if self.card:
            level, peak = 0, 0
            for amount in amounts:
                level += amount
                peak = max(peak, level)
            owed = peak + rng.randint(0, 200000)  # What is owed never goes below zero along the way.
            balance = owed
            for number in range(count):
                balance -= amounts[number]
                balances[number] = balance
            opening, closing = owed, owed - total
        else:
            running = rng.randint(10000, 2000000)
            low = 0
            level = 0
            for amount in amounts:
                level += amount
                low = min(low, level)
            opening = running - low
            balance = opening
            for number in range(count):
                balance += amounts[number]
                balances[number] = balance
            closing = balance
        shown = self.shown_balances(pages_rows, days, dated, heading, c)
        if not c["balance"]:
            shown = [False] * count
        period_printed = c["period_wanted"] or self.style in NEEDS_PERIOD
        ambiguous = self.numeric and not any(day.day > 12 for day in days)
        if ambiguous or c["extras"] and "schedule" in c["extras"]:
            period_printed = True
        c["period"] = period_printed
        c["year"] = self.style not in NO_YEAR
        rows = []
        for number in range(count):
            rows.append((days[number].isoformat(), amounts[number], " ".join(descriptions[number])))
        layout = Layout(answers={"rows": rows, "period": (start.isoformat(), end.isoformat()) if period_printed else None,
                                 "opening": opening if c["summary"] else None, "closing": closing if c["summary"] else None,
                                 "kind": c["kind"]}, choices=c)
        # Render.
        header = self.header(start, end, opening, closing, period_printed)
        pages = []
        pages_total = len(pages_rows) + (1 if "schedule" in c["extras"] else 0)
        wrapped = [len(description) for description in descriptions]
        c["pages"] = len(pages_rows)
        c["wrapped"] = sorted(set(wrapped))
        section_titles = (rng.choice(IN_SECTIONS), rng.choice(OUT_SECTIONS)) if self.sectioned else None
        printed_extras = []
        for position, numbers in enumerate(pages_rows):
            items = []
            if position == 0:
                items += [(40, 780 - 12 * spot, text) for spot, text in enumerate(header)]
                y = 780 - 12 * (len(header) - 1) - 36
            else:
                if not self.sectioned:  # A running header is a one-run line: it would be read as the title of the rows below and end a carried section.
                    items.append((40, 780, f"{self.name} statement continued"))
                y = 744
            show_heading = heading and (position == 0 or c["continuation_heading"])
            if show_heading:
                items += self.heading_items(y, roles, edges, description_x, two_lines)
                y -= 20
            else:
                y -= 8 if position == 0 else 0
            if position == 0 and not show_heading:
                y = 780 - 12 * (len(header) - 1) - 36
            for number in numbers:
                if self.sectioned and number in (0, section_at):
                    title = section_titles[0] if (number == 0) == in_first else section_titles[1]
                    items += [(40, y, title)]
                    y -= LINE + 6
                text = printed[number]
                cells = [(date_x, text)] if dated[number] else []
                first, *rest = descriptions[number]
                cells.append((description_x, first))
                items += [put(x, y, label) for x, label in cells]
                items += self.amount_items(y, roles, edges, amounts[number], balances[number] if shown[number] else None)
                for line in rest:
                    y -= LINE
                    items.append((description_x, y, line))
                y -= LINE + c["row_gap"]
            if position == len(pages_rows) - 1:
                printed_extras = self.extras(items, y, roles, edges, days, opening, amounts, c)
            items.append((40, 50, f"{self.name} statement page {PAGE_WORDS[position + 1]} of {PAGE_WORDS[pages_total]}, kept for your records"))
            pages.append({"items": items})
        if "schedule" in c["extras"]:
            pages.append({"items": self.schedule_page(edges, description_x, end, pages_total, c)})
            printed_extras.append("schedule")
        c["extras"] = tuple(printed_extras)
        c["dateless"] = dated.count(False)
        layout.pages = pages
        return layout

    # --- Directions, balances ----------------------------------------------------------------------------------------------------

    def directions(self, pages_rows, dated, heading, c):
        """+1 money in, -1 money out, per row in print order. In/out columns need two dated rows each on a page (one with a heading printed)."""
        rng = self.rng
        count = len(dated)
        out = [0] * count
        if self.sectioned:
            return out
        if c["signs"] == "inout":
            for position, numbers in enumerate(pages_rows):
                headed = heading and (position == 0 or c["continuation_heading"])
                least = 1 if headed else 2
                firsts = [number for number in numbers if dated[number]]
                if len(numbers) == 1:
                    kinds = [rng.choice((1, -1))]
                else:
                    inward = rng.randint(least, len(firsts) - least)
                    kinds = [1] * inward + [-1] * (len(firsts) - inward)
                    rng.shuffle(kinds)
                for number, kind in zip(firsts, kinds):
                    out[number] = kind
                for number in numbers:
                    if not dated[number]:
                        out[number] = rng.choice((1, -1))
            return out
        share = 0.4 if self.card else 0.3
        return [1 if rng.random() < share else -1 for _ in range(count)]

    def shown_balances(self, pages_rows, days, dated, heading, c):
        """Which rows print a balance. Every page prints it on at least two dated rows (one with a heading), and a table prints at least three
        when there is no summary to fall back on."""
        count = len(days)
        mode = c["balances"] if c["summary"] else "all"
        if mode == "all":
            shown = [True] * count
        elif mode == "end_of_day":
            shown = [number == count - 1 or days[number] != days[number + 1] for number in range(count)]
        else:
            shown = [self.rng.random() < 0.5 for _ in range(count)]
        for position, numbers in enumerate(pages_rows):
            headed = heading and (position == 0 or c["continuation_heading"])
            least = 1 if headed else 2
            have = [number for number in numbers if shown[number] and dated[number]]
            for number in numbers:
                if len(have) >= min(least, len(numbers)):
                    break
                if dated[number] and not shown[number]:
                    shown[number] = True
                    have.append(number)
        if sum(shown) < 3:
            shown = [True] * count
        return shown

    # --- Printed parts --------------------------------------------------------------------------------------------------------

    @property
    def name(self):
        if not hasattr(self, "_name"):
            self._name = self.rng.choice(CARDS if self.card else BANKS)
        return self._name

    def header(self, start, end, opening, closing, period_printed):
        rng, c = self.rng, self.c
        words = (("Previous balance", "New balance") if self.card else (("Beginning balance", "Ending balance"), ("Opening balance", "Closing balance"))[c["summary_words"]])
        summary = []
        if c["summary"]:
            if c["summary_dated"] and not self.card:
                summary = [f"{words[0]} on {when(start, self.style)} {money(opening)}", f"{words[1]} on {when(end, self.style)} {money(closing)}"]
            else:
                summary = [f"{words[0]} {money(opening)}", f"{words[1]} {money(closing)}"]
        account = (f"Card number XXXX{rng.randint(1000, 9999)}" if self.card else f"Account number 00000{rng.randint(10000, 99999)}")
        period = [self.period_text(start, end)] if period_printed else []
        if period or not summary:
            lines = [self.name, account, *summary, *period] if rng.random() < 0.5 or not summary else [self.name, *summary, *period, account]
        else:
            lines = [self.name, *summary, account]
        return lines

    def heading_items(self, y, roles, edges, description_x, two_lines):
        rng = self.rng
        table = UNKNOWN if self.c["heading"].startswith("unknown") else KNOWN
        labels = {}
        for role in roles:
            options = table[role][1 if two_lines else 0]
            fitting = [label for label in options if max(width(part) for part in label) <= self.gap - 20]  # Labels stay a run apart.
            labels[role] = rng.choice(fitting or options[:1])
        date_head, description_head = rng.choice(DATE_HEADS), rng.choice(DESCRIPTION_HEADS)
        items = [(40, y, date_head), (description_x, y, description_head)]
        for role in roles:
            if two_lines:
                top, bottom = labels[role]
                items.append(put(edges[role], y + 12, top, True))
                items.append(put(edges[role], y, bottom, True))
            else:
                items.append(put(edges[role], y, labels[role][0], True))
        return items

    def amount_items(self, y, roles, edges, amount, balance):
        """The cells of one row. The amount goes where its sign style puts it; the balance, when printed, in its column."""
        signs, magnitude = self.c["signs"], money(abs(amount))
        out = amount < 0
        items = []
        for role in roles:
            if role == "balance":
                if balance is not None:
                    items.append(put(edges[role], y, money(balance), True))
                continue
            if role == "in" and not out:
                items.append(put(edges[role], y, magnitude, True))
            elif role == "out" and out:
                items.append(put(edges[role], y, magnitude, True))
            elif role == "signed":
                if signs == "sectioned":
                    text = magnitude
                elif signs == "crdr":
                    text = f"{magnitude} {'DR' if out else 'CR'}" if not self.card else (magnitude if out else f"{magnitude} CR")
                elif signs == "parens":
                    text = (f"({magnitude})" if out else magnitude) if not self.card else (magnitude if out else f"({magnitude})")
                else:
                    text = (f"-{magnitude}" if out else magnitude) if not self.card else (magnitude if out else f"-{magnitude}")
                items.append(put(edges[role], y, text, True))
        return items

    def extras(self, items, y, roles, edges, days, opening, amounts, c):
        """Non-transaction tables under the last page's rows: a daily balance table and a fee summary (their titles end the table, so their lines
        are not rows). Returns which were printed; one that would not fit is left out."""
        rng = self.rng
        y -= 6
        column = edges[roles[-1]]
        printed = []
        if "daily" in c["extras"] and not self.card and y - 14 * 5 > BOTTOM:
            printed.append("daily")
            items.append((40, y, "Daily ending balance"))
            y -= 20
            chosen = sorted(rng.sample(sorted(set(days)), min(3, len(set(days)))))
            for day in chosen:
                level = opening + sum(amount for amount, other in zip(amounts, days) if other <= day)
                items.append((40, y, when(day, self.style)))
                items.append(put(column, y, money(level), True))
                y -= 20
            y -= 6
        if "fees" in c["extras"] and y - 14 * 4 > BOTTOM:
            printed.append("fees")
            items.append((40, y, "Fee summary"))
            y -= 20
            for label in rng.sample(("Monthly service fee", "Overdraft fees", "Interest charged"), 2):
                items.append((40, y, label))
                items.append(put(column, y, money(rng.choice((0, 0, 500, 1200))), True))
                y -= 20
        return printed

    def schedule_page(self, edges, description_x, end, total, c):
        """A last page of upcoming payments dated after the period: rows outside the period, so not recorded."""
        rng = self.rng
        column = edges["out"] if "out" in edges else edges["signed"]
        items = [(40, 744, "Payment schedule")]
        count = rng.randint(2, 4)
        if c["small_days"] and self.numeric:
            # Days of 12 or less, two months on: far outside the period whichever way round the date is read.
            month = (end.replace(day=1) + timedelta(days=65)).replace(day=1)
            dates = [month.replace(day=day) for day in sorted(rng.sample(range(1, 13), count))]
        else:
            later = end + timedelta(days=rng.randint(20, 40))
            dates = [later + timedelta(days=number * 7) for number in range(count)]
        y = 700
        for day in dates:
            items.append((40, y, when(day, self.style)))
            items.append((description_x, y, "SCHEDULED SYNTH PAYMENT"))
            items.append(put(column, y, money(rng.randint(1000, 30000)), True))
            y -= 20
        items.append((40, 50, f"{self.name} statement page {PAGE_WORDS[total]} of {PAGE_WORDS[total]}, kept for your records"))
        return items


# --- What a case shows -------------------------------------------------------------------------------------------------------

REQUIRED = (
    "columns:balance_first", "columns:balance_middle", "columns:balance_last", "columns:in_before_out", "columns:out_before_in",
    "columns:signed_before_balance", "columns:signed_after_balance",
    "heading:known", "heading:unknown", "heading:none", "heading:one_line", "heading:two_lines",
    "dates:month_first", "dates:day_first", "dates:iso", "dates:month_names", "dates:with_year", "dates:without_year",
    "wrap:1", "wrap:2", "wrap:3", "one_date_per_day",
    "signs:signed", "signs:inout", "signs:crdr", "signs:parens",
    "balance:with", "balance:without", "summary:with", "summary:without",
    "continuation:with_heading", "continuation:without_heading", "extra_tables",
)


def variations(layout) -> set[str]:
    """The FR-33 variations a case actually shows, from what was printed (SC-18 counts each of `REQUIRED` in at least five cases)."""
    c = layout.choices
    roles = c["column_order"].split(",")
    found = {f"signs:{c['signs']}", f"balance:{'with' if c['balance'] else 'without'}", f"summary:{'with' if c['summary'] else 'without'}"}
    found |= {f"wrap:{lines}" for lines in c["wrapped"]}
    if "balance" in roles:
        spot = roles.index("balance")
        found.add("columns:balance_first" if spot == 0 else "columns:balance_last" if spot == len(roles) - 1 else "columns:balance_middle")
        if "signed" in roles:
            found.add("columns:signed_before_balance" if roles.index("signed") < spot else "columns:signed_after_balance")
    if "in" in roles:
        found.add("columns:in_before_out" if roles.index("in") < roles.index("out") else "columns:out_before_in")
    found.add("heading:none" if c["heading"] == "none" else "heading:unknown" if c["heading"].startswith("unknown") else "heading:known")
    if c["heading"] != "none":
        found.add("heading:two_lines" if c["heading"].endswith("2") else "heading:one_line")
    style = c["dates"]
    found.add("dates:month_first" if style in NUMERIC and style not in DAY_FIRST else "dates:day_first" if style in NUMERIC else
              "dates:iso" if style == "iso" else "dates:month_names")
    found.add("dates:without_year" if style in NO_YEAR else "dates:with_year")
    if c["dateless"]:
        found.add("one_date_per_day")
    if c["pages"] > 1:
        found.add("continuation:with_heading" if c["heading"] != "none" and c["continuation_heading"] else "continuation:without_heading")
    if c["extras"]:
        found.add("extra_tables")
    return found
