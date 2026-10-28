"""The table engine: tables, columns and rows from a saved PDF reading's positioned words (specs/pdf-table-engine).

`read` takes one saved reading and returns an `EngineReading`. It is pure and deterministic: it touches no store, makes no model
or network call, uses no clock or randomness, and never opens the PDF. It imports nothing from `finance/`, so any consumer can
use it. It reads the saved layout's words of `embedded_text` pages only.

What it finds: tokens (dates, amounts, integers, text), columns by alignment with their zones, headings that label columns, tables
(a page's tables, and a table continued over later pages with or without a repeated heading, at a page offset), and rows (wrapped
descriptions, descriptions printed above their amounts, dateless rows, a date line over its amount line). Lines that are no rows are
classed: balance lines inside a table are candidates (the statement layer decides by the balance column), totals, summary anchors
outside every table, and unplaced lines (a date and an amount that sit in no column). It never converts money: amounts are exact
`Decimal` tokens, and which column is money in or out is decided by the statement layer. Not here (later slices): statement roles,
signs, the period and the date order, schedules and the rejections that need a role ("both a debit and a credit"). `read` takes the
statement's currency only to reject an amount printed in another one (FR-16); the code stays on the amount token either way.

Zones: columns come from alignment alone, but when a heading is printed the outermost amount zones are bounded by the heading labels
beside them (`bound_by_headings`; handoff SL-02 explains why the extent-and-reach zones of the plan are not enough for statement-accounts
X and T).
"""

from dataclasses import dataclass, field, replace
from decimal import Decimal
import math
import re
from statistics import median

from ..core.money import EXPONENTS
from .pdf_layout import point, visual_box

ALIGN = 0.75  # OD-4: amounts line up when their edges are within this many font sizes of the group's median.
RUN_GAP = 1.5  # A run is words closer than this many font sizes (the reader's own rule).
FIT = 0.2  # A token fits a zone when it crosses the zone's edges by no more than this share of its width.
LONE_REACH = 4  # A lone amount column's zone reaches this many font sizes past its extent (there is no gap between columns to halve).

NO_AMOUNT = "No amount is printed."
JOINED_AMOUNT = "The amount is printed against the description, so it can't be told apart from it."
NO_DATE = "No date is printed."
MORE_THAN_ONE = "More than one amount sits in the {name} column."
TEXT_IN_AMOUNT = "Text that is not an amount sits in the {name} column."
BAD_DATE = 'The date "{text}" is not a real date.'
CANT_READ = 'The amount "{text}" can\'t be read.'
NOT_IN_CURRENCY = 'The amount "{text}" is not in {currency}.'
BLANK_DESCRIPTION = "The description is blank."

INFINITY = math.inf


# --- Visual rows ---------------------------------------------------------------------------------------------------------

class PageView:
    """A native page's saved words grouped into visual rows (plan "Visual rows"): a word's baseline is its first character's
    origin through page_to_preview, else the bottom of its box; a new row starts when a baseline differs by more than a quarter
    of the font size from the first word of the row. This re-implements the reader's rule, which is a closure (pdf_layout.py)."""

    def __init__(self, layout):
        self.layout = layout
        matrix = layout.page_to_preview
        glyphs = [char for char in layout.characters if char.bbox and not char.generated and char.text and not char.text.isspace()]
        self.size = max(1, median(char.font_size for char in glyphs) * math.hypot(matrix[0], matrix[1])) if glyphs else 1
        self.box = {word.id: visual_box(matrix, word.bbox) for word in layout.words}
        self.baseline = {}
        for word in layout.words:
            origin = layout.characters[word.character_indexes[0]].origin
            self.baseline[word.id] = point(matrix, *origin)[1] if origin else self.box[word.id][3]
        groups = []
        for word in sorted(layout.words, key=lambda word: (self.baseline[word.id], self.box[word.id][0])):
            if not groups or abs(self.baseline[word.id] - self.baseline[groups[-1][0].id]) > self.size * 0.25:
                groups.append([])
            groups[-1].append(word)
        self.row_baseline = [self.baseline[group[0].id] for group in groups]
        self.rows = [sorted(group, key=lambda word: self.box[word.id][0]) for group in groups]
        self.row_of = {word.id: index for index, row in enumerate(self.rows) for word in row}
        self.line_of = {word_id: line.id for line in layout.lines for word_id in line.word_ids}

    def runs(self, index):
        """A visual row's runs of words: a word closer than 1.5 font sizes to the one before it joins its run (plan "Heading texts")."""
        groups = []
        for word in self.rows[index]:
            if not groups or self.box[word.id][0] - self.box[groups[-1][-1].id][2] > self.size * RUN_GAP:
                groups.append([])
            groups[-1].append(word)
        return groups

    def texts(self, index):
        """A visual row's texts, as (text, left, right): the text of each run and where it starts and ends."""
        return [(" ".join(word.text for word in run), self.box[run[0].id][0], self.box[run[-1].id][2]) for run in self.runs(index)]

    def lines(self, word_ids):
        return list(dict.fromkeys(self.line_of[word_id] for word_id in word_ids if word_id in self.line_of))


# --- Contracts (plan P2) -------------------------------------------------------------------------------------------------

@dataclass
class Token:
    """kind: date, amount, integer or text. `value` by kind:
    date: (first, second, year, form). form is slash (first and second are the two numbers as printed, their order is decided
        later), iso or month_name (first is the day, second the month); year is as printed (26 or 2026) or None.
    amount: (magnitude, marker, code). The magnitude is an exact Decimal, None when the word is unreadable (`1.2.3`, `1.234,56`).
        marker is minus, plus, credit, debit or None; code is the ISO code printed (a symbol gives its usual code) or None.
    integer: the int. text: None."""
    kind: str
    word_ids: list[str]
    box: tuple[float, float, float, float]
    text: str
    value: object = None


@dataclass
class Column:
    id: str
    kind: str  # date, amount or text (the description)
    align: str  # right, left or centre
    edge: float  # The group's median edge (the description's median left edge).
    extent: tuple[float, float]  # The members' leftmost left and rightmost right.
    zone: tuple[float, float]  # Where a token of the column may sit; open ends are infinite.
    labels: list[str] = field(default_factory=list)  # Heading words over it, top to bottom.


@dataclass
class EngineRow:
    page: int
    table_id: str
    row: int  # 1-based among the table's rows on its page, rejected rows included.
    line_ids: list[str]
    word_ids: list[str]
    cell_ids: list[str]
    dates: list[Token]  # As printed, one per date column the row has a date in (column order).
    description: str
    amounts: dict[str, Token]  # Column id to the amount printed there.
    carried_from: tuple[int, int] | None = None  # (page, row) whose date a dateless row takes (OD-1).
    section: str | None = None
    reject: str | None = None
    candidate: str | None = None  # opening or closing: a balance line inside the table; the statement layer decides if it is an anchor.


@dataclass
class Anchor:
    page: int
    line_id: str
    kind: str  # opening or closing
    value: Decimal  # Signed: a minus sign or parentheses make it negative.
    inside_table: bool  # A candidate: the row with the same line stays in the table's rows, flagged, until the statement layer decides.
    dated: bool = False  # The line also prints a date.


@dataclass
class Total:
    page: int
    line_id: str
    column_id: str
    value: Decimal


@dataclass
class Unplaced:
    page: int
    line_id: str
    text: str
    reason: str  # no_column here; the statement layer adds pending


@dataclass
class EngineTable:
    id: str  # page-<p>-table-<n>
    pages: list[int]
    columns: list[Column]
    rows: list[EngineRow]
    kind: str  # transactions, balance, schedule or other
    continues: str | None = None
    headings: list[str] = field(default_factory=list)  # The text of the heading lines, top to bottom.
    anchors: list[Anchor] = field(default_factory=list)
    totals: list[Total] = field(default_factory=list)


@dataclass
class EngineReading:
    tables: list[EngineTable]
    unplaced: list[Unplaced] = field(default_factory=list)
    summary_anchors: list[Anchor] = field(default_factory=list)
    period_lines: list[tuple] = field(default_factory=list)
    other_native_tables: list[str] = field(default_factory=list)
    pages_without_tables: list[int] = field(default_factory=list)  # Native pages with a layout where no table was found.


# --- Tokens (plan P3; FR-02) ---------------------------------------------------------------------------------------------

MONTHS = {name: number for number, names in enumerate(
    (("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"), ("jul", "july"),
     ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"), ("dec", "december")), 1) for name in names}
MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))
SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}
NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
AMOUNT = re.compile(rf"(?P<open>\()?(?P<sign>[-+])?(?P<symbol>[$€£¥])?(?P<number>{NUMBER})(?P<close>\))?(?P<tail>-|CR|DR)?")
SHAPED = re.compile(r"[-+(]?[$€£¥]?\d[\d,.]*\)?(?:-|CR|DR)?")  # Digit-led digits, commas and periods: whether it reads is decided here.
INTEGER = re.compile(r"\d+")
SLASH_DATE = re.compile(r"(\d{1,2})/(\d{1,2})(?:/(\d{4}|\d{2}))?")
DOTTED_DATE = re.compile(r"(\d{1,2})([.-])(\d{1,2})\2(\d{4}|\d{2})")  # Dots and dashes need a year: `10.25` is an amount.
DASHED_DATE = re.compile(r"(\d{1,2})-(\d{1,2})")
ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
NAMED_DATE = re.compile(rf"(\d{{1,2}})-({MONTH})-(\d{{4}}|\d{{2}})", re.IGNORECASE)
CODES = frozenset(EXPONENTS)
UNREADABLE = (None, None, None)


def real_day(day, month):
    return 1 <= month <= 12 and 1 <= day <= (29 if month == 2 else 30 if month in (4, 6, 9, 11) else 31)


def date_of(text):
    """A single printed word as a date value, or None. A numeric date that is no real date in either order is not one."""
    match = ISO_DATE.fullmatch(text)
    if match:
        year, month, day = (int(part) for part in match.groups())
        return (day, month, year, "iso") if real_day(day, month) else None
    match = NAMED_DATE.fullmatch(text)
    if match:
        return int(match.group(1)), MONTHS[match.group(2).lower()], int(match.group(3)), "month_name"
    for pattern, groups in ((SLASH_DATE, (1, 2, 3)), (DOTTED_DATE, (1, 3, 4)), (DASHED_DATE, (1, 2, None))):
        match = pattern.fullmatch(text)
        if match:
            first, second = int(match.group(groups[0])), int(match.group(groups[1]))
            if not (real_day(first, second) or real_day(second, first)):
                return None
            year = match.group(groups[2]) if groups[2] else None
            return first, second, int(year) if year else None, "slash"
    return None


def amount_of(text):
    """A single printed word as an amount value (magnitude, marker, code); UNREADABLE for a digit-led word with separators that
    is not a number (`1.2.3`, `1.234,56`; OD-3); None when it is no amount."""
    match = AMOUNT.fullmatch(text)
    if match:
        marks = [mark for mark in ("minus" if match["sign"] == "-" else "plus" if match["sign"] else None, "minus" if match["open"] else None,
                                   {"-": "minus", "CR": "credit", "DR": "debit"}.get(match["tail"])) if mark]
        if bool(match["open"]) != bool(match["close"]) or len(marks) > 1:
            return UNREADABLE
        return Decimal(match["number"].replace(",", "")), marks[0] if marks else None, SYMBOLS.get(match["symbol"])
    return UNREADABLE if SHAPED.fullmatch(text) and re.search(r"[,.]", text) else None


def union(boxes):
    boxes = list(boxes)
    return min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)


def single(text, box, word_id):
    date = date_of(text)
    if date:
        return Token("date", [word_id], box, text, date)
    if INTEGER.fullmatch(text):
        return Token("integer", [word_id], box, text, int(text))
    value = amount_of(text)
    return Token("amount", [word_id], box, text, value) if value is not None else Token("text", [word_id], box, text)


def named_date(texts):
    """`01 Oct 2026`, `01 Oct`, `Oct 1`, `Oct 01, 2026` or `Oct 1 2026` at the start of the texts: (value, words used) or None."""
    lowered = [text.lower().rstrip(",") for text in texts]
    if len(texts) < 2:
        return None
    for day, name in ((0, 1), (1, 0)):
        if lowered[name] in MONTHS and re.fullmatch(r"\d{1,2}", lowered[day]) and real_day(int(lowered[day]), MONTHS[lowered[name]]):
            year = int(texts[2]) if len(texts) >= 3 and re.fullmatch(r"\d{4}", texts[2]) else None
            return (int(lowered[day]), MONTHS[lowered[name]], year, "month_name"), 3 if year else 2
    return None


def joined_amount(first, second):
    """Two words that are one amount: an ISO code before or after it, or CR/DR after it. The amount value, else None."""
    if first.kind == "amount" and second.kind == "text" and first.value[0] is not None:
        if first.value[2] is None and second.text in CODES:
            return first.value[0], first.value[1], second.text
        if first.value[1] is None and second.text in ("CR", "DR"):
            return first.value[0], "credit" if second.text == "CR" else "debit", first.value[2]
    if second.kind == "amount" and first.kind == "text" and first.text in CODES and second.value[2] is None and second.value[0] is not None:
        return second.value[0], second.value[1], first.text
    return None


def tokenize(words):
    """The tokens of one run of words, [(text, box, word_id)]: multi-word tokens first, left to right (month-name dates, an amount
    with its ISO code before or after it, an amount followed by CR or DR), then single words."""
    tokens, index = [], 0
    while index < len(words):
        found = named_date([word[0] for word in words[index:index + 3]])
        if found:
            used = words[index:index + found[1]]
            tokens.append(Token("date", [word[2] for word in used], union(word[1] for word in used), " ".join(word[0] for word in used), found[0]))
            index += len(used)
            continue
        token = single(*words[index])
        if index + 1 < len(words):
            value = joined_amount(token, single(*words[index + 1]))
            if value:
                used = words[index:index + 2]
                tokens.append(Token("amount", [word[2] for word in used], union(word[1] for word in used), " ".join(word[0] for word in used), value))
                index += 2
                continue
        tokens.append(token)
        index += 1
    return tokens


def read_tokens(texts):
    """The tokens of one run of printed words with no page (each word gets a box 10 units to the right of the one before)."""
    return tokenize([(text, (index * 10.0, 0.0, index * 10.0 + 9.0, 10.0), f"word-{index}") for index, text in enumerate(texts)])


# --- Geometry ------------------------------------------------------------------------------------------------------------

ALIGNMENTS = ("right", "left", "centre")


def middle(box):
    return (box[0] + box[2]) / 2


def edge_of(box, alignment):
    return {"right": box[2], "left": box[0], "centre": middle(box)}[alignment]


def in_zone(box, zone):
    return zone[0] <= middle(box) < zone[1]


def fits(box, zone):
    """The token's centre is in the zone and its box crosses the zone's edges by no more than 20% of its width."""
    allowance = (box[2] - box[0]) * FIT
    return in_zone(box, zone) and zone[0] - allowance <= box[0] and box[2] <= zone[1] + allowance


def whole_inside(box, zone):
    return zone[0] <= box[0] and box[2] <= zone[1]


def cluster(items, tolerance):
    """Groups of (value, key) within `tolerance` of the group's median, in value order; a member farther than that from the final
    median leaves its group."""
    groups = []
    for item in sorted(items):
        if groups and item[0] - median(member[0] for member in groups[-1]) <= tolerance:
            groups[-1].append(item)
        else:
            groups.append([item])
    settled = []
    for group in groups:
        while len(group) > 1:
            centre = median(member[0] for member in group)
            far = max(group, key=lambda member: (abs(member[0] - centre), member))
            if abs(far[0] - centre) <= tolerance:
                break
            group.remove(far)
            settled.append([far])
        settled.append(group)
    return settled


# --- A page: tokens, columns, zones (plan P4) ----------------------------------------------------------------------------

@dataclass
class Line:
    """One visual row of a page, tokenized."""
    index: int
    words: list
    runs: list[list]
    tokens: list[list[Token]]  # Per run.
    led_by_text: list[bool]  # Per run: its first token is text or an integer.

    def all_tokens(self):
        return [token for tokens in self.tokens for token in tokens]

    def free_tokens(self, kind):
        """Tokens of a kind that are not in a run led by text."""
        return [token for tokens, led in zip(self.tokens, self.led_by_text) for token in tokens if token.kind == kind and not led]


def tokenize_page(view):
    lines = []
    for index in range(len(view.rows)):
        runs = view.runs(index)
        tokens = [tokenize([(word.text, view.box[word.id], word.id) for word in run]) for run in runs]
        lines.append(Line(index, view.rows[index], runs, tokens, [run_tokens[0].kind in ("text", "integer") for run_tokens in tokens]))
    return lines


@dataclass
class Layout:
    """A page's columns and zones."""
    dates: list[Column]
    description: Column
    amounts: list[Column]

    @property
    def columns(self):
        return [*self.dates, self.description, *self.amounts]

    def zone_of(self, box):
        return next((column for column in self.columns if in_zone(box, column.zone)), None)


def label_support(lines, lo, first_row, view_box, alignment, centre, tolerance):
    """Whether a multi-run text line within three visual rows above the table's first row (and not above the segment's first line `lo`)
    prints a label aligned with the group (the heading, with room for one title line between it and the row)."""
    for index in range(first_row - 1, max(first_row - 4, lo - 1), -1):
        line = lines[index]
        if len(line.runs) >= 2 and all(token.kind == "text" for token in line.all_tokens()):
            for run in line.runs:
                if abs(edge_of(union(view_box[word.id] for word in run), alignment) - centre) <= tolerance:
                    return True
    return False


def choose_alignments(entries, tolerance, supported):
    """Each token goes to the alignment whose group has the most support: its distinct rows, plus one when a heading label is
    printed over the group. A tie goes to the group whose edges agree most closely, then to right, left, centre. A group with
    fewer than two supporting rows is no column (FR-04). Returns [(alignment, [entry index])] in order of first member."""
    found, standing = {}, {}
    for alignment in ALIGNMENTS:
        for number, group in enumerate(cluster([(edge_of(entry[0].box, alignment), position) for position, entry in enumerate(entries)], tolerance)):
            values = [value for value, _ in group]
            rows = {entries[position][1] for _, position in group}
            standing[(alignment, number)] = (len(rows) + supported(rows, alignment, median(values)), max(values) - min(values))
            for _, position in group:
                found[(alignment, position)] = number
    chosen = {}
    for position in range(len(entries)):
        best = min(ALIGNMENTS, key=lambda alignment: (-standing[(alignment, found[(alignment, position)])][0],
                                                       standing[(alignment, found[(alignment, position)])][1], ALIGNMENTS.index(alignment)))
        chosen.setdefault((best, found[(best, position)]), []).append(position)
    columns = []
    for (alignment, _), positions in chosen.items():
        rows = {entries[position][1] for position in positions}
        if len(rows) + supported(rows, alignment, median(edge_of(entries[position][0].box, alignment) for position in positions)) >= 2:
            columns.append((alignment, positions))
    return columns


def span(tokens):
    """The leftmost left and rightmost right of the tokens' boxes."""
    return min(token.box[0] for token in tokens), max(token.box[2] for token in tokens)


def zones_between(extents, reach):
    """Zones for columns ordered left to right: each runs from the midpoint between its extent and the previous column's to the
    midpoint with the next; the outer ones reach past their extent by `reach`."""
    bounds = [(left_extent[1] + right_extent[0]) / 2 if left_extent[1] <= right_extent[0] else
              ((left_extent[0] + left_extent[1]) / 2 + (right_extent[0] + right_extent[1]) / 2) / 2
              for left_extent, right_extent in zip(extents, extents[1:])]
    lefts = [extents[0][0] - reach, *bounds]
    rights = [*bounds, extents[-1][1] + reach]
    return list(zip(lefts, rights))


def build_layout(view, lines, lo, hi, table_id):
    """The date, description and amount columns with their zones of the page's lines `lo` to `hi`, or None when they hold no table
    (plan P4)."""
    tolerance = view.size * ALIGN
    segment = lines[lo:hi]
    dated = {line.index for line in segment if line.free_tokens("date")}
    date_entries = [(token, line.index) for line in segment for token in line.free_tokens("date")]
    amount_entries = [(token, line.index) for line in segment if line.index in dated for token in line.free_tokens("amount")]
    if not date_entries or not amount_entries:
        return None
    first_row = min(row for _, row in amount_entries)

    def supported(rows, alignment, centre):
        return 1 if label_support(lines, lo, first_row, view.box, alignment, centre, tolerance) else 0

    amounts = [(alignment, [amount_entries[position][0] for position in positions]) for alignment, positions in choose_alignments(amount_entries, tolerance, supported)]
    if not amounts:
        return None
    amounts.sort(key=lambda item: sum(span(item[1])) / 2)
    extents = [span(tokens) for _, tokens in amounts]
    date_groups = []
    for group in cluster([(entry[0].box[0], position) for position, entry in enumerate(date_entries)], tolerance):
        rows = {date_entries[position][1] for _, position in group}
        if len(rows) + supported(rows, "left", median(value for value, _ in group)) >= 2:
            date_groups.append([date_entries[position][0] for _, position in group])
    date_groups = [tokens for tokens in sorted(date_groups, key=lambda tokens: median(token.box[0] for token in tokens))
                   if span(tokens)[1] < extents[0][0]]
    if not date_groups:
        return None
    date_extents = [span(tokens) for tokens in date_groups]

    centres = [sum(extent) / 2 for extent in extents]
    gaps = [right - left for left, right in zip(centres, centres[1:])]
    reach = median(gaps) / 2 if gaps else view.size * LONE_REACH
    amount_zones = zones_between(extents, reach)
    date_zones = zones_between(date_extents, tolerance)
    date_zones[0] = (-INFINITY, date_zones[0][1])
    description_zone = (date_zones[-1][1], max(amount_zones[0][0], date_zones[-1][1]))
    amount_zones[0] = (description_zone[1], amount_zones[0][1])
    ids = iter(range(1, 100))
    name = lambda: f"{table_id}-column-{next(ids)}"  # noqa: E731
    date_columns = [Column(name(), "date", "left", median(token.box[0] for token in tokens), extent, zone)
                    for tokens, extent, zone in zip(date_groups, date_extents, date_zones)]
    description = Column(name(), "text", "left", description_zone[0], (description_zone[0], description_zone[0]), description_zone)
    amount_columns = [Column(name(), "amount", alignment, median(edge_of(token.box, alignment) for token in tokens), extent, zone)
                      for (alignment, tokens), extent, zone in zip(amounts, extents, amount_zones)]
    return Layout(date_columns, description, amount_columns)




# --- Rows (plan P5) and line classes (plan P6) ---------------------------------------------------------------------------

DATE_SHAPE = re.compile(rf"\d{{1,2}}/\d{{1,2}}(?:/\d{{2,4}})?|\d{{1,2}}([.-])\d{{1,2}}\1\d{{2,4}}|\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}-(?:{MONTH})-\d{{2,4}}",
                        re.IGNORECASE)  # What a printed date looks like, whether or not it is a real one.
OPENING = frozenset(("opening", "beginning", "previous", "starting"))
CLOSING = frozenset(("closing", "ending", "new"))
TOTAL = re.compile(r"(?:sub)?totals?")
SECTION_WORDS = frozenset(("balance", "balances", "total", "totals", "subtotal", "summary"))
UNIT_CODES = frozenset(("CR", "DR"))


@dataclass
class Reading:
    """What one visual row holds, against a page's zones."""
    dates: list[Token] = field(default_factory=list)
    amounts: dict[str, Token] = field(default_factory=dict)
    extra: list[tuple[Token, Column]] = field(default_factory=list)  # A second amount fitting an already filled zone.
    joined: bool = False  # An amount is printed against the description text.
    stray: bool = False  # An amount that fits no amount zone.
    used: set = field(default_factory=set)  # Word ids that are a date or an amount.
    bad_date: str | None = None  # A date-shaped word in the date zone that is no real date.
    text_in: list[Token] = field(default_factory=list)  # Text that is not an amount, wholly inside an amount zone.


def read_line(line, layout, view):
    """What a visual row holds against the page's zones (plan P3, P5): the date tokens in a date zone, and the amounts. An amount
    or integer inside a run whose first word sits in the description zone is text, unless its whole box lies inside one amount zone and
    it is the row's only amount-shaped word centred in an amount zone (statement-accounts FR-30). An integer is an amount only
    where it fits an amount zone."""
    reading = Reading()
    candidates = []  # (token, joined to the description text)
    for run, tokens, led in zip(line.runs, line.tokens, line.led_by_text):
        in_text = in_zone(view.box[run[0].id], layout.description.zone)
        taken = set()
        for position, token in enumerate(tokens):
            if token.kind == "date" and not led:
                column = next((column for column in layout.dates if column.id not in taken and fits(token.box, column.zone)), None)
                if column:
                    taken.add(column.id)
                    reading.dates.append(token)
                    reading.used.update(token.word_ids)
            elif token.kind == "text" and position == 0 and DATE_SHAPE.fullmatch(token.text) and any(in_zone(token.box, column.zone) for column in layout.dates):
                reading.bad_date = token.text
                reading.used.update(token.word_ids)
            elif token.kind == "text" and not in_text and token.text not in CODES and token.text not in UNIT_CODES \
                    and any(whole_inside(token.box, column.zone) for column in layout.amounts):
                reading.text_in.append(token)
            elif token.kind in ("amount", "integer"):
                candidates.append((token, in_text and position > 0))
    centred = [token for token, _ in candidates if any(in_zone(token.box, column.zone) for column in layout.amounts)]
    for token, joined in candidates:
        if joined and not (len(centred) == 1 and any(whole_inside(token.box, column.zone) for column in layout.amounts)):
            reading.joined = reading.joined or token.kind == "amount"
            continue
        column = next((column for column in layout.amounts if fits(token.box, column.zone)), None)
        if column is None:
            reading.stray = reading.stray or token.kind == "amount"
            continue
        if token.kind == "integer":
            token = Token("amount", token.word_ids, token.box, token.text, (Decimal(token.value), None, None))
        if column.id in reading.amounts:
            reading.extra.append((token, column))
        else:
            reading.amounts[column.id] = token
        reading.used.update(token.word_ids)
    return reading


def label_of(column):
    return " ".join(column.labels) if column and column.labels else "unlabelled"


def reject_of(reading, layout):
    """The reason a row that has its date and amounts is rejected, in today's words (FR-16), in today's order: the amount column
    rules, then the date."""
    if reading.extra:
        return MORE_THAN_ONE.format(name=label_of(reading.extra[0][1]))
    if reading.text_in:
        return TEXT_IN_AMOUNT.format(name=label_of(layout.zone_of(reading.text_in[0].box)))
    if reading.bad_date:
        return BAD_DATE.format(text=reading.bad_date)
    return None


def is_heading(line, layout):
    """A text-only line with at least two runs in different zones, at least one of them an amount column's (plan P4)."""
    if len(line.runs) < 2 or any(token.kind != "text" for token in line.all_tokens()):
        return False
    zones = [layout.zone_of(union(token.box for token in tokens)) for tokens in line.tokens]
    ids = {column.id for column in zones if column}
    return len(ids) >= 2 and any(column.kind == "amount" for column in zones if column)


def heading_start(lines, lo, first_row, layout):
    """The heading lines directly above the table's first row, nearest first: one or two heading lines, with at most one title
    line between them and the row (`Payments and Credits`)."""
    found, index, skipped = [], first_row - 1, False
    while index >= lo and len(found) < 2:
        line = lines[index]
        if is_heading(line, layout):
            found.append(index)
        elif not found and not skipped and len(line.runs) == 1 and all(token.kind == "text" for token in line.all_tokens()):
            skipped = True
        else:
            break
        index -= 1
    return found


def bound_by_headings(layout, heading_lines, view):
    """Bound the outermost amount zones by the heading labels beside them, as the old reader's spans were (statement-accounts X and
    T; escalated in handoff SL-02, the plan's extent-and-reach zones can't give their results): the first amount zone starts no
    later than the midpoint between the label before its own label and its own label, and the last zone ends no later than the
    midpoint between its own label and the label after it. Returns whether a zone moved."""
    boxes = [union(view.box[word.id] for word in run) for line in heading_lines for run in line.runs]
    owner = [layout.zone_of(box) for box in boxes]
    first, last = layout.amounts[0], layout.amounts[-1]
    moved = False
    over = [box for box, column in zip(boxes, owner) if column is first]
    if over:
        label_left = min(box[0] for box in over)
        before = [box[2] for box, column in zip(boxes, owner) if column is not first and box[2] <= label_left]
        bound = (max(before) + label_left) / 2 if before else INFINITY
        if layout.description.zone[0] < bound < first.zone[0]:
            first.zone, layout.description.zone, moved = (bound, first.zone[1]), (layout.description.zone[0], bound), True
    over = [box for box, column in zip(boxes, owner) if column is last]
    if over:
        label_right = max(box[2] for box in over)
        after = [box[0] for box, column in zip(boxes, owner) if column is not last and box[0] >= label_right]
        bound = (label_right + min(after)) / 2 if after else INFINITY
        if last.zone[0] < bound < last.zone[1]:
            last.zone, moved = (last.zone[0], bound), True
    return moved


def in_description(view, layout, words):
    """Whether printed words are description text: the first starts in the description zone and none reaches the first amount
    column's extent (a wrapped line may run past the zone's edge, which the headings can pull in, but not into an amount column)."""
    return bool(words) and in_zone(view.box[words[0].id], layout.description.zone) and all(view.box[word.id][2] <= layout.amounts[0].extent[0] for word in words)


def words_text(words, used):
    return " ".join(word.text for word in words if word.id not in used)


def words_of(line):
    """The lower-case letters of each text word of a line: what a balance, total or section name is read from."""
    return [re.sub(r"[^a-z]", "", token.text.lower()) for token in line.all_tokens() if token.kind == "text"]


def balance_kind(words):
    """opening or closing when the words name a balance (`Beginning Balance`, `New Balance`), else None (plan P6)."""
    if "balance" not in words:
        return None
    return next(("opening" if word in OPENING else "closing" for word in words if word in OPENING or word in CLOSING), None)


def only_amount(line):
    """The line's only amount token, when it holds exactly one that can be read."""
    amounts = [token for token in line.all_tokens() if token.kind == "amount"]
    return amounts[0] if len(amounts) == 1 and amounts[0].value[0] is not None else None


def value_of(token):
    magnitude, marker, _ = token.value
    return -magnitude if marker == "minus" else magnitude


def title_line(line):
    """A single run of text on its own line (a section title, when rows follow it)."""
    return len(line.runs) == 1 and all(token.kind == "text" for token in line.all_tokens())


def heading_like(line):
    return len(line.runs) >= 2 and all(token.kind == "text" for token in line.all_tokens())


def cuts(view, lines):
    """The lines where a new table starts (plan P6): a section title that names a balance, totals or summary section, at or left of
    the date column, directly above a line that holds a date or an amount (heading lines in between do not count)."""
    rows = [line for line in lines if line.free_tokens("date") and line.free_tokens("amount")]
    if not rows:
        return []
    left = median(min(token.box[0] for token in line.free_tokens("date")) for line in rows)
    found = []
    for line in lines[rows[0].index + 1:]:
        if not title_line(line) or not SECTION_WORDS & set(words_of(line)) or view.box[line.words[0].id][0] > left + view.size * ALIGN:
            continue
        ahead = next((other for other in lines[line.index + 1:] if not heading_like(other)), None)
        if ahead is not None and any(token.kind in ("date", "amount") for token in ahead.all_tokens()):
            found.append(line.index)
    return found


@dataclass
class Page:
    number: int
    view: PageView
    lines: list[Line]
    cells: dict[str, str]  # Word id to the native reader cell that holds it.
    used: set = field(default_factory=set)  # Visual rows cited by a row, an anchor or a total.
    cited: set = field(default_factory=set)  # Their word ids.

    def mark(self, indexes):
        for index in indexes:
            self.used.add(index)
            self.cited.update(word.id for word in self.lines[index].words)

    def line_id(self, index):
        ids = self.view.lines([word.id for word in self.lines[index].words])
        return ids[0] if ids else ""


@dataclass
class Open:
    """A table that may continue on the next page."""
    table: EngineTable
    layout: Layout
    section: str | None = None
    labels: list = field(default_factory=list)  # The heading's runs, top to bottom, as (text, box): what the columns' labels are read from.

    def relabel(self):
        for column in self.layout.columns:
            column.labels[:] = [text for text, box in self.labels if self.layout.zone_of(box) is column]


def shifted(layout, offset):
    move = lambda pair: (pair[0] + offset, pair[1] + offset)  # noqa: E731
    return Layout([replace(column, edge=column.edge + offset, extent=move(column.extent), zone=move(column.zone)) for column in layout.dates],
                  replace(layout.description, edge=layout.description.edge + offset, extent=move(layout.description.extent), zone=move(layout.description.zone)),
                  [replace(column, edge=column.edge + offset, extent=move(column.extent), zone=move(column.zone)) for column in layout.amounts])


def aligned(token, column, offset, tolerance):
    """Whether an amount sits at the column's edge plus the page offset in any alignment: a column whose first rows were all the
    same width could have been taken for right-aligned when it is left-aligned (K's balances)."""
    box = token.box
    return any(abs(value - (edge + offset)) <= tolerance for value, edge in
               ((edge_of(box, column.align), column.edge), (box[0], column.extent[0]), (box[2], column.extent[1]), (middle(box), sum(column.extent) / 2)))


def extended(layout, added, size):
    """The layout with extra amount columns (found on a later page, in the table's own frame): zones are cut again between the
    extents, the outer ends stay where they were unless a new column is outermost."""
    amounts = sorted([*layout.amounts, *added], key=lambda column: sum(column.extent) / 2)
    centres = [sum(column.extent) / 2 for column in amounts]
    gaps = [right - left for left, right in zip(centres, centres[1:])]
    zones = zones_between([column.extent for column in amounts], median(gaps) / 2 if gaps else size * LONE_REACH)
    if amounts[0] is layout.amounts[0]:
        zones[0] = (layout.amounts[0].zone[0], zones[0][1])
    if amounts[-1] is layout.amounts[-1]:
        zones[-1] = (zones[-1][0], layout.amounts[-1].zone[1])
    amounts = [replace(column, zone=zone) for column, zone in zip(amounts, zones)]
    description = replace(layout.description, zone=(layout.description.zone[0], amounts[0].zone[0]))
    return Layout(layout.dates, description, amounts)


def continuation(view, lines, lo, hi, candidates):
    """The previous page's table, latest first, that the segment's rows continue, with the page offset (the median difference of
    the date column's left edge) and the columns they add (plan P4; FR-06). Most rows must have their dates and at least one
    amount at a column's edge plus the offset, within the tolerance. An amount that fits no column makes a new column of the table
    only when the page repeats the table's own heading (so the heading proves the same column set) and at least two rows (or one
    row and its heading label) support it. Returns (open, offset, new columns) or None."""
    rows = [line for line in lines[lo:hi] if line.free_tokens("date") and line.free_tokens("amount")]
    if not rows:
        return None
    tolerance = view.size * ALIGN
    first = rows[0].index
    for opened in reversed(candidates):
        layout = opened.layout
        offset = median(min(token.box[0] for token in line.free_tokens("date")) - layout.dates[0].edge for line in rows)
        fitting, leftover = 0, []
        for line in rows:
            dates = all(any(abs(token.box[0] - (column.edge + offset)) <= tolerance for column in layout.dates) for token in line.free_tokens("date"))
            unmatched = [(token, line.index) for token in line.free_tokens("amount") if not any(aligned(token, column, offset, tolerance) for column in layout.amounts)]
            fitting += dates and len(unmatched) < len(line.free_tokens("amount"))
            leftover += unmatched
        if fitting * 2 <= len(rows):
            continue
        if not leftover:
            return opened, offset, []
        drawn = [index for index in range(first - 1, max(first - 3, lo - 1), -1) if is_heading(lines[index], shifted(layout, offset))]
        if not opened.table.headings or [" ".join(word.text for word in lines[index].words) for index in sorted(drawn)] != opened.table.headings:
            continue
        found = choose_alignments(leftover, tolerance, lambda rows_, alignment, centre: 1 if label_support(lines, lo, first, view.box, alignment, centre, tolerance) else 0)
        if {position for _, positions in found for position in positions} != set(range(len(leftover))):
            continue
        added = []
        for alignment, positions in found:
            tokens = [leftover[position][0] for position in positions]
            left, right = span(tokens)
            added.append(Column(f"{opened.table.id}-column-{len(opened.layout.columns) + len(added) + 1}", "amount", alignment,
                                median(edge_of(token.box, alignment) for token in tokens) - offset, (left - offset, right - offset), (0.0, 0.0)))
        return opened, offset, added
    return None


def descriptions_above(page, layout, begin, hi, readings, headings):
    """Plan P5.7: the table prints its descriptions above their amounts when every row's date line has a text-only line (inside the
    description zone) directly above it, the first one included, and the last row's date line has none directly below. At least two
    rows. (The plan also asks that no date line has one below; the next row's description is always directly below the row before, so
    only the last row can show it.)"""
    view = page.view

    def text_only(index):
        if index < begin or index >= hi or index in headings:
            return False
        line = page.lines[index]
        return bool(line.tokens) and not readings[index].dates and not readings[index].amounts \
            and all(token.kind == "text" for token in line.all_tokens()) and in_description(view, layout, line.words)

    row_lines = [index for index in range(begin, hi) if readings[index].dates and readings[index].amounts]
    return len(row_lines) >= 2 and all(text_only(index - 1) for index in row_lines) and not text_only(row_lines[-1] + 1)


def scan(page, table, state, layout, begin, hi, readings, headings):
    """Plan P5 and P6 over lines `begin` to `hi` against `layout`, appending rows (and a table's balance candidates and totals) to
    `table`. Returns this segment's description words on each row's first line."""
    view, lines = page.view, page.lines
    rows, starts, consumed, waiting = [], [], set(), []
    last = None
    above = descriptions_above(page, layout, begin, hi, readings, headings)

    def make(indexes, reject=None):
        nonlocal last
        indexes = sorted(indexes)
        words = [word for index in indexes for word in lines[index].words]
        used = set().union(*(readings[index].used for index in indexes))
        amounts = {}
        for index in indexes:
            amounts.update(readings[index].amounts)
        word_ids = [word.id for word in words]
        if state["title"] is not None:
            state["section"], state["title"] = state["title"], None
        row = EngineRow(page.number, table.id, 1 + sum(1 for other in table.rows if other.page == page.number), view.lines(word_ids), word_ids,
                        list(dict.fromkeys(page.cells[word_id] for word_id in word_ids if word_id in page.cells)),
                        [token for index in indexes for token in readings[index].dates], words_text(words, used), amounts, section=state["section"],
                        reject=reject)
        table.rows.append(row)
        rows.append(row)
        starts.append([word for word in lines[indexes[0]].words if word.id not in used])
        page.mark(indexes)
        last = indexes[-1]
        return row

    def with_waiting(index):
        """The line, with the description lines printed directly above it when the table prints descriptions above its amounts."""
        if above and waiting and waiting[-1] == index - 1:
            return [*waiting, index]
        return [index]

    def candidate(row, line, kind, dated):
        row.candidate, row.reject = kind, None
        table.anchors.append(Anchor(page.number, row.line_ids[0] if row.line_ids else "", kind, value_of(only_amount(line)), True, dated))

    def source():
        return next((other for other in reversed(table.rows) if other.dates and not other.candidate), None)

    for line in lines[begin:hi]:
        index = line.index
        if index in consumed or index in headings:
            continue
        reading = readings[index]
        words = words_of(line)
        kind = balance_kind(words) if len(reading.amounts) == 1 and not reading.extra and only_amount(line) is not None else None
        if (reading.dates or reading.bad_date) and reading.amounts:
            row = make(with_waiting(index), reject_of(reading, layout))
            if kind and not reading.bad_date:
                candidate(row, line, kind, bool(reading.dates))
        elif reading.dates:
            if reading.stray:
                continue  # An amount that fits no column: an unplaced line, listed once the page is read.
            below = readings.get(index + 1) if index + 1 < hi else None
            if below and below.amounts and not below.dates and not below.stray and not any(TOTAL.fullmatch(word) for word in words_of(lines[index + 1])):
                make([*with_waiting(index), index + 1])
                consumed.add(index + 1)
            else:
                make(with_waiting(index), JOINED_AMOUNT if reading.joined else NO_AMOUNT)
        elif reading.amounts:
            if any(TOTAL.fullmatch(word) for word in words):
                for column_id, token in reading.amounts.items():
                    if token.value[0] is not None:
                        table.totals.append(Total(page.number, page.line_id(index), column_id, value_of(token)))
                page.mark([index])
                last = None
                continue
            earlier = source()
            row = make(with_waiting(index), reject_of(reading, layout) or (None if earlier else NO_DATE))
            row.carried_from = (earlier.page, earlier.row) if earlier else None
            if kind:
                candidate(row, line, kind, False)
        elif rows and not above and last == index - 1 and in_description(view, layout, line.words):
            row = rows[-1]
            row.word_ids += [word.id for word in line.words]
            row.line_ids = view.lines(row.word_ids)
            row.description = " ".join(part for part in (row.description, words_text(line.words, ())) if part)
            row.cell_ids = list(dict.fromkeys(page.cells[word_id] for word_id in row.word_ids if word_id in page.cells))
            page.mark([index])
            last = index
        elif above and line.tokens and all(token.kind == "text" for token in line.all_tokens()) and in_description(view, layout, line.words):
            waiting[:] = [*waiting, index] if waiting and waiting[-1] == index - 1 else [index]
        elif title_line(line):
            state["title"] = " ".join(word.text for word in line.words)  # A section title labels the rows below it; a footer has none.
    return starts


@dataclass
class PageReading:
    opens: list[Open] = field(default_factory=list)  # The tables with rows on this page, in order.
    created: list[EngineTable] = field(default_factory=list)  # The ones that start here.
    anchors: list[Anchor] = field(default_factory=list)  # Summary anchors: balance lines outside every table.
    unplaced: list[Unplaced] = field(default_factory=list)
    periods: list[tuple] = field(default_factory=list)  # (page, line id, first date token, second date token), plan P8.
    others: list[str] = field(default_factory=list)  # Native reader tables no engine row, anchor or total cites.


def read_page(number, layout_page, previous):
    """The tables of one native page, with the previous page's open tables it may continue (plan P4, P6)."""
    view = PageView(layout_page)
    lines = tokenize_page(view)
    page = Page(number, view, lines, {word_id: cell.id for table in layout_page.tables for cell in table.cells for word_id in cell.word_ids})
    found = PageReading()
    bounds = [0, *cuts(view, lines), len(lines)]
    for lo, hi in zip(bounds, bounds[1:]):
        free = [opened for opened in previous if all(opened is not other for other in found.opens)]
        matched = continuation(view, lines, lo, hi, free)
        if matched:
            opened, offset, added = matched
            if added:
                opened.layout = extended(opened.layout, added, view.size)
                opened.table.columns = opened.layout.columns
                opened.relabel()
            layout = shifted(opened.layout, offset)
        else:
            table_id = f"page-{number}-table-{len(found.created) + 1}"
            layout = build_layout(view, lines, lo, hi, table_id)
            if layout is None:
                continue
            opened = Open(EngineTable(table_id, [number], layout.columns, [], "other"), layout)
        readings = {line.index: read_line(line, layout, view) for line in lines[lo:hi]}
        if matched:
            begin, headings = lo, ()
        else:
            first = next((index for index in range(lo, hi) if readings[index].dates and readings[index].amounts), None)
            if first is None:
                continue
            headings = heading_start(lines, lo, first, layout)
            begin = min(headings) if headings else first
            opened.labels = [(" ".join(token.text for token in tokens), union(token.box for token in tokens)) for index in sorted(headings) for tokens in lines[index].tokens]
            opened.table.headings = [" ".join(word.text for word in lines[index].words) for index in sorted(headings)]
            if headings and bound_by_headings(layout, [lines[index] for index in sorted(headings)], view):
                readings = {line.index: read_line(line, layout, view) for line in lines[lo:hi]}
            opened.relabel()
        state = {"section": opened.section, "title": None}
        starts = scan(page, opened.table, state, layout, begin, hi, readings, headings)
        opened.section = state["section"]
        if not any(row.page == number for row in opened.table.rows):
            continue
        if matched:
            if number not in opened.table.pages:
                opened.table.pages.append(number)
        else:
            described = [word for words in starts for word in words]
            if described:
                boxes = [view.box[word.id] for word in described]
                layout.description.extent = (min(box[0] for box in boxes), max(box[2] for box in boxes))
                layout.description.edge = median(min(view.box[word.id][0] for word in words) for words in starts if words)
            found.created.append(opened.table)
        found.opens.append(opened)
    for line in lines:
        if line.index in page.used:
            continue
        kind, amount = balance_kind(words_of(line)), only_amount(line)
        if kind and amount is not None:
            found.anchors.append(Anchor(number, page.line_id(line.index), kind, value_of(amount), False, any(token.kind == "date" for token in line.all_tokens())))
            page.mark([line.index])
    for line in lines:
        tokens = line.all_tokens()
        dates = [token for token in tokens if token.kind == "date"]
        if line.index not in page.used and len(dates) == 2 and all(token.value[2] is not None and token.value[2] > 999 for token in dates) \
                and not any(token.kind == "amount" for token in tokens):
            found.periods.append((number, page.line_id(line.index), dates[0], dates[1]))  # A candidate period line: outside every table, two dated, no amount.
    if found.opens:
        for line in lines:
            tokens = line.all_tokens()
            if line.index not in page.used and any(token.kind == "date" for token in tokens) and any(token.kind == "amount" for token in tokens):
                found.unplaced.append(Unplaced(number, page.line_id(line.index), " ".join(word.text for word in line.words), "no_column"))
    found.others = [table.id for table in layout_page.tables if not any(word_id in page.cited for cell in table.cells for word_id in cell.word_ids)]
    return found


def finish(table, currency, amounts=True):
    """A table's kind from all its rows, then the rejections that need the whole table (a blank description) or the statement's
    currency (plan P5.5, P6). With `amounts` False the amount rejections (unreadable, another currency) are left to the statement
    layer, which knows which columns hold money."""
    rows = [row for row in table.rows if not row.candidate]
    described = sum(1 for row in rows if row.description)
    amounts = [column for column in table.columns if column.kind == "amount"]
    table.kind = "transactions" if rows and described * 2 >= len(rows) else "balance" if rows and len(amounts) == 1 else "other"
    for row in rows:
        if row.reject:
            continue
        if table.kind == "transactions" and not row.description.strip():
            row.reject = BLANK_DESCRIPTION
            continue
        for token in row.amounts.values() if amounts else ():
            magnitude, _, code = token.value
            if magnitude is None:
                row.reject = CANT_READ.format(text=token.text)
            elif currency and code and code != currency:
                row.reject = NOT_IN_CURRENCY.format(text=token.text, currency=currency)
            if row.reject:
                break


# --- Entry point (FR-01) ---------------------------------------------------------------------------------------------------

def read(result, currency=None, amounts=True):
    """Read a saved reading (`PDFResult`) into its tables. Only `embedded_text` pages with a saved layout are read. With the
    statement's `currency` (an ISO code), a row whose printed amount carries another code is rejected (FR-16); without it the code
    stays on the amount token for the statement layer. With `amounts` False no row is rejected for its amounts (unreadable, another
    currency): the statement layer does that, per column, once it knows which columns are money."""
    reading = EngineReading([])
    previous = []
    for page in result.pages:
        if page.method != "embedded_text" or page.layout is None:
            previous = []
            continue
        found = read_page(page.number, page.layout, previous)
        reading.tables += found.created
        reading.summary_anchors += found.anchors
        reading.unplaced += found.unplaced
        reading.period_lines += found.periods
        reading.other_native_tables += found.others
        if not found.opens:
            reading.pages_without_tables.append(page.number)
        previous = found.opens
    for table in reading.tables:
        finish(table, currency, amounts)
    return reading
