"""The table engine: tables, columns and rows from a saved PDF reading's positioned words (specs/pdf-table-engine).

`read` takes one saved reading and returns an `EngineReading`. It is pure and deterministic: it touches no store, makes no model
or network call, uses no clock or randomness, and never opens the PDF. It imports nothing from `finance/`, so any consumer can
use it. It reads the saved layout's words of `embedded_text` pages only.

What it finds: tokens (dates, amounts, integers, text), columns by alignment with their zones, headings that label columns, and
rows (wrapped descriptions, dateless rows, a date line over its amount line). It never converts money: amounts are exact `Decimal`
tokens, and which column is money in or out is decided by the statement layer. Not here yet (the plan's later slices): a table's
extent across a page and its pages, balance and total lines, unplaced lines, rejections beyond those named below, statement roles,
signs and the period. One table is read per page.
"""

from dataclasses import dataclass, field
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


@dataclass
class Anchor:
    page: int
    line_id: str
    kind: str  # opening or closing
    value: Decimal
    inside_table: bool


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
    reason: str  # no_column or pending


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


def label_support(lines, first_row, view_box, alignment, centre, tolerance):
    """Whether a multi-run text line within three visual rows above the table's first row prints a label aligned with the group (the
    heading, with room for one title line between it and the row)."""
    for index in range(first_row - 1, max(first_row - 4, -1), -1):
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


def build_layout(view, lines, page, table_id):
    """The page's date, description and amount columns with their zones, or None when it holds no table (plan P4)."""
    tolerance = view.size * ALIGN
    dated = {line.index for line in lines if line.free_tokens("date")}
    date_entries = [(token, line.index) for line in lines for token in line.free_tokens("date")]
    amount_entries = [(token, line.index) for line in lines if line.index in dated for token in line.free_tokens("amount")]
    if not date_entries or not amount_entries:
        return None
    first_row = min(row for _, row in amount_entries)

    def supported(rows, alignment, centre):
        return 1 if label_support(lines, first_row, view.box, alignment, centre, tolerance) else 0

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


# --- Rows (plan P5, rules 1 to 4) ----------------------------------------------------------------------------------------

@dataclass
class Reading:
    """What one visual row holds, against a page's zones."""
    dates: list[Token] = field(default_factory=list)
    amounts: dict[str, Token] = field(default_factory=dict)
    extra: list[tuple[Token, Column]] = field(default_factory=list)  # A second amount fitting an already filled zone.
    joined: bool = False  # An amount is printed against the description text.
    stray: bool = False  # An amount that fits no amount zone.
    used: set = field(default_factory=set)  # Word ids that are a date or an amount.


def read_line(line, layout, view):
    """What a visual row holds against the page's zones (plan P3, P5): the date tokens in a date zone, and the amounts. An amount
    or integer inside a run whose first word sits in the description zone is text, unless its whole box lies in one amount zone and
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


def is_heading(line, layout):
    """A text-only line with at least two runs in different zones, at least one of them an amount column's (plan P4)."""
    if len(line.runs) < 2 or any(token.kind != "text" for token in line.all_tokens()):
        return False
    zones = [layout.zone_of(union(token.box for token in tokens)) for tokens in line.tokens]
    ids = {column.id for column in zones if column}
    return len(ids) >= 2 and any(column.kind == "amount" for column in zones if column)


def heading_start(lines, first_row, layout):
    """The heading lines directly above the table's first row, nearest first: one or two heading lines, with at most one title
    line between them and the row (`Payments and Credits`)."""
    found, index, skipped = [], first_row - 1, False
    while index >= 0 and len(found) < 2:
        line = lines[index]
        if is_heading(line, layout):
            found.append(index)
        elif not found and not skipped and len(line.runs) == 1 and all(token.kind == "text" for token in line.all_tokens()):
            skipped = True
        else:
            break
        index -= 1
    return found


def words_text(words, used):
    return " ".join(word.text for word in words if word.id not in used)


def read_page(number, layout_page):
    """The tables of one native page (one per page for now), or []."""
    view = PageView(layout_page)
    lines = tokenize_page(view)
    table_id = f"page-{number}-table-1"
    layout = build_layout(view, lines, number, table_id)
    if layout is None:
        return []
    readings = [read_line(line, layout, view) for line in lines]
    first = next((line.index for line in lines if readings[line.index].dates and readings[line.index].amounts), None)
    if first is None:
        return []
    headings = heading_start(lines, first, layout)
    start = min(headings) if headings else first
    cells = {word_id: cell.id for table in layout_page.tables for cell in table.cells for word_id in cell.word_ids}
    rows: list[EngineRow] = []
    state = {"last_line": None, "section": None, "title": None}
    starts = []  # The description words on each row's first line.
    consumed = set()

    def make(indexes, reject=None):
        words = [word for index in indexes for word in lines[index].words]
        used = set().union(*(readings[index].used for index in indexes))
        amounts = {}
        for index in indexes:
            amounts.update(readings[index].amounts)
        word_ids = [word.id for word in words]
        if state["title"] is not None:
            state["section"], state["title"] = state["title"], None
        row = EngineRow(number, table_id, len(rows) + 1, view.lines(word_ids), word_ids, list(dict.fromkeys(cells[w] for w in word_ids if w in cells)),
                        [token for index in indexes for token in readings[index].dates], words_text(words, used), amounts, section=state["section"],
                        reject=reject)
        rows.append(row)
        starts.append([word for word in lines[indexes[0]].words if word.id not in used])
        state["last_line"] = indexes[-1]
        return row

    for line in lines[start:]:
        index = line.index
        if index in consumed or index in headings:
            continue
        reading = readings[index]
        if reading.dates and reading.amounts:
            row = make([index])
            if reading.extra:
                row.reject = MORE_THAN_ONE.format(name=" ".join(reading.extra[0][1].labels) or "unlabelled")
        elif reading.dates:
            if reading.stray:
                continue  # An amount that fits no column: an unplaced line (a later slice).
            below = readings[index + 1] if index + 1 < len(lines) else None
            if below and below.amounts and not below.dates and not below.stray:
                make([index, index + 1])
                consumed.add(index + 1)
            else:
                make([index], JOINED_AMOUNT if reading.joined else NO_AMOUNT)
        elif reading.amounts:
            source = next((row for row in reversed(rows) if row.dates), None)
            row = make([index], None if source else NO_DATE)
            row.carried_from = (source.page, source.row) if source else None
        elif rows and state["last_line"] == index - 1 and all(in_zone(view.box[word.id], layout.description.zone) for word in line.words):
            row = rows[-1]
            row.word_ids += [word.id for word in line.words]
            row.line_ids = view.lines(row.word_ids)
            row.description = " ".join(part for part in (row.description, words_text(line.words, ())) if part)
            row.cell_ids = list(dict.fromkeys(cells[w] for w in row.word_ids if w in cells))
            state["last_line"] = index
        elif len(line.runs) == 1 and all(token.kind == "text" for token in line.all_tokens()):
            state["title"] = " ".join(word.text for word in line.words)  # A section title labels the rows below it; a footer has none.
    if not rows:
        return []
    described = [word for words in starts for word in words]
    if described:
        boxes = [view.box[word.id] for word in described]
        layout.description.extent = (min(box[0] for box in boxes), max(box[2] for box in boxes))
        layout.description.edge = median(min(view.box[word.id][0] for word in words) for words in starts if words)
    for index in sorted(headings):
        for tokens in lines[index].tokens:
            column = layout.zone_of(union(token.box for token in tokens))
            if column:
                column.labels.append(" ".join(token.text for token in tokens))
    kind = "transactions" if sum(1 for row in rows if row.description) * 2 >= len(rows) else "balance" if len(layout.amounts) == 1 else "other"
    return [EngineTable(table_id, [number], layout.columns, rows, kind, None, [" ".join(word.text for word in lines[index].words) for index in sorted(headings)])]


# --- Entry point (FR-01) ---------------------------------------------------------------------------------------------------

def read(result):
    """Read a saved reading (`PDFResult`) into its tables. Only `embedded_text` pages with a saved layout are read."""
    tables, without = [], []
    for page in result.pages:
        if page.method != "embedded_text" or page.layout is None:
            continue
        found = read_page(page.number, page.layout)
        tables += found
        if not found:
            without.append(page.number)
    return EngineReading(tables, pages_without_tables=without)
