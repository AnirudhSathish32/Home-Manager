"""Pay tables from a saved PDF reading's positioned words (specs/pdf-table-engine-paystubs, plan P3).

`read` takes one saved reading and returns a `PayReading`. It is pure and deterministic like `table_engine`: no store, model, network, clock or
randomness, and it never opens the PDF. It reuses the engine's primitives (tokens, visual rows, alignment groups, zones) and imports nothing
from `finance/`. `table_engine.read`, `build_layout`, `scan`, `cuts` and `continuation` are not changed, so statements can't move (FR-67).

What it finds. A pay row starts at a visual line whose first run is text (the label) and that holds an amount in a run not led by text; no date
or heading is needed (FR-50). Numbers joined to letters stay label text (FR-51), and so do integers, except whole numbers that line up in a column
of their own (`80` hours: FR-90). A page whose lines carry a second label-and-amounts group is split into two blocks, each read on its own (FR-53). Columns come from alignment alone, headings only label them (FR-52). Section titles
at the label column's left edge, indented wrapped labels, and totals lines are told from rows (FR-54, FR-55). A table ends after its net pay
total, at a heading line of other words, at a stub start line (a pay date or pay period line), and where a row's amounts share no column with it;
a later page whose rows fit the columns at a page offset continues it. Two rows of four or more amounts whose largest is the sum of three others
are a summary box, not a table (FR-75). A line with a label and an amount that is no row, total, heading or box line is an unplaced line (FR-56).

Not here (SL-02): which table is a pay table and which is another (deposit, leave), the column roles, and the guesses. `PayReading.tables` holds
every table found; `other_tables` stays empty until the role pass fills it.
"""

from dataclasses import dataclass, field
from itertools import combinations
import re
from statistics import median

from .table_engine import (
    ALIGN,
    ALIGNMENTS,
    LONE_REACH,
    Line,
    PageView,
    Token,
    amount_of,
    choose_alignments,
    cluster,
    edge_of,
    in_zone,
    span,
    tokenize_page,
    union,
    value_of,
    zones_between,
)

LETTERED = r"(?:\s*\([A-Z](?:\s*-\s*[A-Z])?\))?"
TOTAL_LABEL = re.compile(r"(?:gross pay|net pay(?:ment)?|total (?:earnings|gross(?: pay)?|pay|tax(?:es)?|(?:(?:pre|post)[ -]?tax |employee |employer )?"
                         r"(?:deductions|contributions)))" + LETTERED, re.IGNORECASE)
STUB_START = re.compile(r"\b(?:pay date|check date|payment date|pay period|period ending)\b", re.IGNORECASE)
BOX_ROWS = 4  # A summary box row prints at least this many amounts (FR-75).
LEAVE_HEADING_WORDS = frozenset({"accrued", "accrual", "accruals", "balance", "balances", "used", "available", "remaining", "carryover", "deposit", "deposits",
                                 "account", "routing"})  # A one-run line cuts a table only if it holds one (FR-92 f); lower-cased whole words, punctuation stripped.
MAX_OFFSET = ALIGN  # A later page's table sits at most this many font sizes from where the first page's did (FR-92 b).


# --- Contracts (plan P2) -------------------------------------------------------------------------------------------------

@dataclass
class PayColumn:
    id: str
    align: str  # right, left or centre
    edge: float  # The group's median edge, in the table's first page.
    extent: tuple[float, float]
    zone: tuple[float, float]
    labels: list[str] = field(default_factory=list)  # Heading words over it, top to bottom.
    label_words: list[list[str]] = field(default_factory=list)  # The word ids of each label, so Record can cite the heading.


@dataclass
class PayRow:
    page: int
    table_id: str
    row: int  # 1-based among the table's rows and totals in printed order (the adapter's `<table>-row-<r>`).
    line_ids: list[str]
    word_ids: list[str]
    label: str
    amounts: dict[str, Token]  # Column id to the amount printed there.
    section: str | None = None
    stray: list[Token] = field(default_factory=list)  # Amounts of the line that sit in no column of the table.


@dataclass
class PayTotal:
    page: int
    line_id: str
    word_ids: list[str]
    label: str
    kind: str  # gross, earnings, taxes, deductions, net (or employer: a total of the employer's contributions)
    values: dict[str, Token]
    row: int = 0
    table_id: str = ""


@dataclass
class PayTable:
    id: str  # page-<p>-pay-<n>
    pages: list[int]
    label_column: tuple[float, float]
    columns: list[PayColumn]
    rows: list[PayRow]
    totals: list[PayTotal]
    headings: list[str]  # The text of the heading lines, top to bottom.
    block: str | None = None  # left or right on a page with side-by-side blocks.
    partner: str | None = None
    lead: str | None = None  # The title line directly above the heading (`Direct Deposit`).


@dataclass
class SummaryBox:
    page: int
    line_ids: list[str]
    columns: list[PayColumn]
    rows: list[PayRow]
    id: str = ""


@dataclass
class Unplaced:
    page: int
    line_id: str
    text: str


@dataclass
class PayReading:
    tables: list[PayTable]
    boxes: list[SummaryBox] = field(default_factory=list)
    other_tables: list[PayTable] = field(default_factory=list)  # Filled by the role pass (SL-02).
    unplaced: list[Unplaced] = field(default_factory=list)
    pages_without_tables: list[int] = field(default_factory=list)


# --- Lines ---------------------------------------------------------------------------------------------------------------

def readable(token):
    return token.kind == "amount" and token.value[0] is not None


def amounts_of(line):
    """The readable amounts of a line's runs that are not led by text (the label run is not one)."""
    return [token for tokens, led in zip(line.tokens, line.led_by_text) for token in tokens if readable(token) and not led]


def amount_runs(line):
    return [index for index, (tokens, led) in enumerate(zip(line.tokens, line.led_by_text)) if not led and any(readable(token) for token in tokens)]


def is_pay(line):
    """FR-50: the first run is text (the label) and an amount follows in a run not led by text."""
    return bool(line.runs) and line.led_by_text[0] and bool(amount_runs(line))


def text_only(line):
    return bool(line.runs) and not any(readable(token) for token in line.all_tokens())


def is_heading_like(line):
    """Two or more runs, all words (the engine's heading shape)."""
    return len(line.runs) >= 2 and all(token.kind == "text" for token in line.all_tokens())


def is_title_like(line):
    return len(line.runs) == 1 and text_only(line)


def lone_integer(tokens):
    """Whether a run is one integer and nothing else (`80` under a Hours heading): never the start of a second label (FR-90)."""
    return len(tokens) == 1 and tokens[0].kind == "integer"


def integer_only(line):
    """A line of a text label and then only runs of one whole number each, no decimal amount: a row printed in whole numbers (FR-90, plan P1
    step 7). It is no pay line until its numbers are read as amounts."""
    return (len(line.runs) >= 2 and line.led_by_text[0] and any(token.kind == "text" for token in line.tokens[0])
            and not any(readable(token) for token in line.tokens[0]) and all(lone_integer(tokens) for tokens in line.tokens[1:]))


def run_text(run):
    return " ".join(word.text for word in run)


def line_text(line):
    return " ".join(word.text for word in line.words)


def label_of(line):
    first = amount_runs(line)[0]
    return " ".join(run_text(run) for run in line.runs[:first])


def total_kind(label):
    """gross, earnings, taxes, deductions, net or employer when the label is a printed totals line (FR-55), else None."""
    text = re.sub(r"\s+", " ", label.strip().rstrip(":"))
    if not TOTAL_LABEL.fullmatch(text):
        return None
    words = text.lower()
    if "net" in words:
        return "net"
    if "contribution" in words or "employer" in words:
        return "employer"
    if "deduction" in words:
        return "deductions"
    if "tax" in words:
        return "taxes"
    return "gross" if "gross" in words else "earnings"


def starts_stub(line):
    """A stub start line (P8): a pay date label and a date."""
    return text_only(line) and bool(STUB_START.search(line_text(line))) and any(token.kind == "date" for token in line.all_tokens())


def stub_dates(line):
    """The dates a stub start line prints."""
    return {token.text for token in line.all_tokens() if token.kind == "date"}


def words_of(lines):
    return {token.text.lower() for line in lines for token in line.all_tokens()}


# --- Blocks (FR-53) ------------------------------------------------------------------------------------------------------

def split_tails(line):
    """A second label printed less than 1.5 font sizes after the first group's last amount joins that amount's run ("52,000.00 Federal Income Tax"
    in a tightly padded payslip). When amounts follow it, the label starts a run of its own, so the line reads as two label-and-amounts groups."""
    runs, tokens = [], []
    for run, found in zip(line.runs, line.tokens):
        # A lone integer after an amount (`80` in an hours column) is no second label (FR-90).
        cut = next((i for i in range(1, len(found)) if found[i - 1].kind == "amount" and (found[i].kind == "text" or found[i].kind == "integer" and i < len(found) - 1)),
                   None)
        first_word = found[cut].word_ids[0] if cut is not None else None
        position = next((i for i, word in enumerate(run) if word.id == first_word), None)
        if position is None:
            runs.append(run)
            tokens.append(found)
        else:
            runs += [run[:position], run[position:]]
            tokens += [found[:cut], found[cut:]]
    led = [group[0].kind in ("text", "integer") for group in tokens]
    split = Line(line.index, line.words, runs, tokens, led)
    return split if any(led[i] and any(j > i and not led[j] and any(t.kind == "amount" for t in tokens[j]) for j in range(len(runs))) and i > 0
                        and tokens[i - 1][-1].kind == "amount" for i in range(1, len(runs))) else line


def group_starts(line):
    """Runs that start a second label-and-amounts group: text after an amount run, with an amount run after it."""
    if not line.runs or not line.led_by_text[0]:
        return []
    amounts = amount_runs(line)
    return [index for index in range(1, len(line.runs)) if line.led_by_text[index] and not lone_integer(line.tokens[index])
            and any(j < index for j in amounts) and any(j > index for j in amounts)]


def block_split(view, lines, tolerance):
    """Where the page splits into two blocks: the median left edge of the second groups' labels, when at least two lines carry one and they
    line up by left edge; else None."""
    edges = [(view.box[line.runs[index][0].id][0], line.index) for line in lines for index in group_starts(line)]
    if not edges:
        return None
    best = max(cluster(edges, tolerance), key=lambda group: len({index for _, index in group}))
    if len({index for _, index in best}) < 2:
        return None
    return median(value for value, _ in best)


def wide_heading(view, bl, position):
    """Whether a one-run all-text line is a heading printed over the columns of the pay rows that follow (FR-89), judged before zones exist: it holds a
    word of `LEAVE_HEADING_WORDS` (a section title such as "Health Insurance Premiums" or "Reimbursements" never cuts, however it is placed), the pay
    line comes next, the line does not start in its label column, and each amount of that line has a unit of the heading of its own: a piece over it
    (the line splits where its words lie further apart than a space, as `heading_runs` does) or a word aligned with it by an edge within `ALIGN` font
    sizes (a heading phrase printed at one pitch, "Accrued Vacation Used Leave Balance"; the same edge for every word); no word serves two amounts.
    A section title holding one of the words that lines up with the amounts still cuts (docs/documents.md "Known limits")."""
    line = bl[position]
    if not is_title_like(line) or not LEAVE_HEADING_WORDS & {re.sub(r"^\W+|\W+$", "", word.text.lower()) for word in line.runs[0]}:
        return False
    following = next((other for other in bl[position + 1:] if other.runs), None)
    if following is None or not is_pay(following):
        return False
    tolerance = view.size * ALIGN
    if view.box[line.words[0].id][0] <= view.box[following.runs[0][0].id][0] + tolerance:
        return False
    # Units: a piece over an amount (it takes all its words) or one word aligned with it, all words by the same edge. No word serves two amounts.
    units = [(box, {word.id for word in piece}, True) for piece in run_pieces(view, line.runs[0]) for box in [union(view.box[word.id] for word in piece)]]
    units += [(view.box[word.id], {word.id}, False) for word in line.runs[0]]

    def seat(amounts, used, alignment):
        if not amounts:
            return True
        amount, rest = amounts[0], amounts[1:]
        for box, ids, piece in units:
            fits = (box[0] <= amount.box[2] and box[2] >= amount.box[0]) if piece else abs(edge_of(box, alignment) - edge_of(amount.box, alignment)) <= tolerance
            if fits and not ids & used and seat(rest, used | ids, alignment):
                return True
        return False

    return any(seat(amounts_of(following), set(), alignment) for alignment in ALIGNMENTS)


def tables_cut(view, bl, starts):
    """A block's lines as one (lines, indexes) pair per table (FR-92 f): the lines from the first line after a totals line, when a heading line follows
    before the next pay line (two or more runs, or one run of leave or deposit heading words over the amounts of the pay row below it), and those from a stub
    start line that follows pay lines, start a new table's list, so each table's amounts are clustered on their own and a leave or deposit table
    whose columns line up with a pay table's doesn't merge with it. Each list is the block's length with the lines outside its indexes emptied, so
    line indexes stay the page's."""
    cuts, total, start, seen = [], False, None, False
    for position, line in enumerate(bl):
        if line.index in starts and seen:
            cuts.append(position)
            total, start, seen = False, None, False
        if not line.runs:
            continue
        if is_pay(line):
            total, start, seen = total_kind(label_of(line)) is not None, None, True
        elif total:
            start = position if start is None else start
            if is_heading_like(line) or wide_heading(view, bl, position):
                cuts.append(start)
                total, start = False, None
    edges = [0, *cuts, len(bl)]
    return [([line if low <= position < high else subline(line, []) for position, line in enumerate(bl)], range(low, high))
            for low, high in zip(edges, edges[1:])]


def subline(line, picks):
    return Line(line.index, [word for index in picks for word in line.runs[index]], [line.runs[index] for index in picks],
                [line.tokens[index] for index in picks], [line.led_by_text[index] for index in picks])


def blocks_of(view, lines, tolerance):
    """The page as one block, or as a left and a right block: per page line, the line's runs that lie in the block."""
    split = block_split(view, lines, tolerance)
    if split is None:
        return [lines]
    edge = split - tolerance
    left = [subline(line, [i for i in range(len(line.runs)) if view.box[line.runs[i][0].id][0] < edge]) for line in lines]
    right = [subline(line, [i for i in range(len(line.runs)) if view.box[line.runs[i][0].id][0] >= edge]) for line in lines]
    return [left, right]


# --- Summary box (FR-75) -------------------------------------------------------------------------------------------------

def aligned_columns(first, second, tolerance):
    """The alignment at which two lines' amounts line up one for one, else None."""
    if len(first) != len(second):
        return None
    return next((alignment for alignment in ALIGNMENTS if all(abs(edge_of(a.box, alignment) - edge_of(b.box, alignment)) <= tolerance
                                                           for a, b in zip(first, second))), None)


def is_box(first, second):
    """Two rows of at least four amounts whose largest, on both, is the sum of three others."""
    one, two = [value_of(token) for token in first], [value_of(token) for token in second]
    gross = max(range(len(one)), key=lambda index: one[index])
    if two[gross] != max(two):
        return False
    others = [index for index in range(len(one)) if index != gross]
    return any(sum(one[i] for i in trio) == one[gross] and sum(two[i] for i in trio) == two[gross] for trio in combinations(others, 3))


# --- Blocks, tables and the walk -----------------------------------------------------------------------------------------

@dataclass
class Group:
    align: str
    edge: float
    extent: tuple[float, float]
    boxes: list = field(default_factory=list)  # The boxes of its tokens, so its edge can be read at another alignment.

    def edge_at(self, align):
        return self.edge if align == self.align else median(edge_of(box, align) for box in self.boxes)


@dataclass
class Builder:
    """A table being read: it may take rows from later pages."""
    id: str
    block: str | None
    size: float
    head_runs: list  # (text, box, word ids) of the heading lines' runs, top to bottom.
    headings: list[str]
    heading_words: set
    lead: str | None
    entries: list = field(default_factory=list)
    members: dict = field(default_factory=dict)  # column key -> [(token, page offset)]
    comps: set = field(default_factory=set)  # The column sets of the page being read that its rows use (see `column_sets`).
    aligns: dict = field(default_factory=dict)
    label_lefts: list = field(default_factory=list)
    pages: list = field(default_factory=list)
    section: str | None = None
    partner: str | None = None
    frame: dict = field(default_factory=dict)  # column key -> {alignment: edge} in the first page's frame, while the table is open.


def finish_columns(builder, ids):
    """The builder's columns left to right with zones and heading labels, in the first page's frame."""
    keys = sorted(builder.members, key=lambda key: sum(extent_of(builder, key)) / 2)
    extents = [extent_of(builder, key) for key in keys]
    centres = [sum(extent) / 2 for extent in extents]
    gaps = [right - left for left, right in zip(centres, centres[1:])]
    zones = zones_between(extents, median(gaps) / 2 if gaps else builder.size * LONE_REACH)
    columns = []
    for key, extent, zone in zip(keys, extents, zones):
        align = builder.aligns[key]
        edge = median(edge_of(token.box, align) - offset for token, offset in builder.members[key])
        named = [(text, words) for text, box, words in builder.head_runs if in_zone(box, zone)]
        columns.append(PayColumn(f"{builder.id}-column-{len(columns) + 1}", align, edge, extent, zone, [text for text, _ in named], [words for _, words in named]))
        ids[key] = columns[-1].id
    return columns


def extent_of(builder, key):
    boxes = [(token.box[0] - offset, token.box[2] - offset) for token, offset in builder.members[key]]
    return min(box[0] for box in boxes), max(box[1] for box in boxes)


def finish(builder, view_of):
    """A builder's PayTable (plan P2)."""
    ids = {}
    columns = finish_columns(builder, ids)
    rows, totals = [], []
    for number, entry in enumerate(builder.entries, 1):
        view = view_of[entry["page"]]
        line_ids = view.lines(entry["word_ids"])
        amounts = {ids[key]: token for key, token in entry["keys"].items()}
        if entry["kind"]:
            totals.append(PayTotal(entry["page"], line_ids[0] if line_ids else "", entry["word_ids"], entry["label"], entry["kind"], amounts, number, builder.id))
        else:
            rows.append(PayRow(entry["page"], builder.id, number, line_ids, entry["word_ids"], entry["label"], amounts, entry["section"], entry["stray"]))
    lefts = [left for left in builder.label_lefts]
    return PayTable(builder.id, builder.pages, (min(lefts) if lefts else columns[0].zone[0], columns[0].zone[0]), columns, rows, totals, builder.headings,
                    builder.block, builder.partner, builder.lead)


def finish_box(builder, ids_line, view):
    ids = {}
    columns = finish_columns(builder, ids)
    rows = []
    for number, entry in enumerate(builder.entries, 1):
        rows.append(PayRow(entry["page"], builder.id, number, view.lines(entry["word_ids"]), entry["word_ids"], entry["label"],
                           {ids[key]: token for key, token in entry["keys"].items()}))
    return SummaryBox(builder.entries[0]["page"], ids_line, columns, rows, builder.id)


def run_pieces(view, run, zones=None, edge=None):
    """A run's words as pieces, each a list of words. A run is split where its words are further apart than a space and, when `zones` is given,
    lie in the zones of different columns; without `zones` it splits on the gap alone. Words that start at or past `edge` belong to the next
    block and are cut off."""
    pieces, last = [], None
    for word in run:
        if edge is not None and view.box[word.id][0] >= edge:
            break
        box = view.box[word.id]
        zone = None if zones is None else next((number for number, found in enumerate(zones) if in_zone(box, found)), None)
        far = box[0] - last[1] > view.size / 2 if last is not None else False
        if pieces and not (far and (zones is None or zone is not None and zone != last[0])):
            pieces[-1].append(word)
        else:
            pieces.append([word])
        last = (zone, box[2])
    return pieces


def heading_runs(view, lines, zones=(), edge=None):
    """The heading lines' runs as (text, box, word ids). A run is split where its words are further apart than a space and lie in the zones of
    different columns (two headings printed close enough to read as one phrase: `This Period` `Year to Date`: FR-89). Words that start at or past
    `edge` belong to the next block and are cut off (the right block's label printed in the left block's run)."""
    return [(run_text(piece), union(view.box[word.id] for word in piece), [word.id for word in piece])
            for line in lines for run in line.runs for piece in run_pieces(view, run, zones, edge)]


def find_boxes(number, view, bl, tolerance, found_boxes, taken=frozenset()):
    """Summary boxes of a block (FR-75): the lines they use, including a heading printed directly above, are returned as consumed (with `taken`)."""
    consumed = set(taken)
    index = 0
    while index + 1 < len(bl):
        first, second = bl[index], bl[index + 1]
        if index in consumed or not (is_pay(first) and is_pay(second)):
            index += 1
            continue
        one, two = amounts_of(first), amounts_of(second)
        alignment = aligned_columns(one, two, tolerance)
        if len(one) < BOX_ROWS or alignment is None or not is_box(one, two):
            index += 1
            continue
        heads, above = [], index - 1
        while above >= 0 and len(heads) < 2 and is_heading_like(bl[above]) and above not in consumed:
            heads.append(above)
            above -= 1
        heads.reverse()
        box = Builder(f"page-{number}-box-{sum(1 for other, _ in found_boxes if other.entries[0]['page'] == number) + 1}", None, view.size, heading_runs(view, [bl[i] for i in heads]),
                      [line_text(bl[i]) for i in heads], set(), None)
        for line in (first, second):
            keys = {("box", position): token for position, token in enumerate(amounts_of(line))}
            for key, token in keys.items():
                box.members.setdefault(key, []).append((token, 0.0))
                box.aligns[key] = alignment
            box.entries.append({"page": number, "kind": None, "word_ids": [word.id for word in line.words], "label": label_of(line), "keys": keys,
                                "section": None, "stray": []})
        found_boxes.append((box, [word.id for i in (*heads, index, index + 1) for word in bl[i].words]))
        consumed.update((*heads, index, index + 1))
        index += 2
    return consumed


def splits_by_column(line, view, zones, edge, least=2):
    """Whether an all-text line of one run prints words over `least` or more columns, so it is a heading line though it is one run (FR-89)."""
    if not zones or not is_title_like(line):
        return False
    return sum(any(in_zone(box, zone) for zone in zones) for _, box, _ in heading_runs(view, [line], zones, edge)) >= least


def heads_above(bl, consumed, index, wide=None):
    """The heading lines directly above a line, top to bottom: up to two, with at most one title line between them and the row. `wide` is
    (view, zones, edge) when a one-run line printed over two columns counts as a heading line too."""
    found, skipped, above = [], False, index - 1
    while above >= 0 and len(found) < 2 and above not in consumed:
        line = bl[above]
        # Above a heading line, a line of one run over a column is its first line, though only one column lies under it (FR-92 d).
        if is_heading_like(line) or (wide is not None and splits_by_column(line, *wide, least=1 if found else 2)):
            found.append(above)
        elif not found and not skipped and is_title_like(line):
            skipped = True
        else:
            break
        above -= 1
    return found[::-1]


def place(slots, entries, found):
    """Per pay line, the amounts that sit in a column (group id to token) and those that don't."""
    gid_of = {}
    for gid, (_, positions) in enumerate(found):
        for position in positions:
            gid_of[position] = gid
    extents = {}
    for position, token in enumerate(token for _, tokens in entries for token in tokens):
        if position in gid_of:
            left, right = extents.get(gid_of[position], (token.box[0], token.box[2]))
            extents[gid_of[position]] = (min(left, token.box[0]), max(right, token.box[2]))
    position = 0
    for index, tokens in entries:
        placed, stray = {}, []
        for token in tokens:
            gid = gid_of.get(position)
            position += 1
            if gid is None or gid in placed:
                gid = under(token, extents) if gid is None else None
            if gid is None or gid in placed:
                stray.append(token)
            else:
                placed[gid] = token
        slots[index] = (placed, stray)


def under(token, extents):
    """The one column a token printed mostly inside is under, though its edge did not line up with that column's (a right-aligned column whose
    first amount chose another alignment); None when it lies under no column or under several."""
    width = max(token.box[2] - token.box[0], 1e-9)
    inside = [gid for gid, (left, right) in extents.items() if (min(token.box[2], right) - max(token.box[0], left)) / width >= 0.5]
    return inside[0] if len(inside) == 1 else None


def column_sets(slots):
    """Group id to a column set: groups that print on one line are one set (a table's columns), so a row printing only some of them still
    continues the table; groups no line prints together belong to different tables (STK)."""
    parent = {}

    def root(gid):
        while parent.setdefault(gid, gid) != gid:
            parent[gid] = parent[parent[gid]]
            gid = parent[gid]
        return gid

    for placed, _ in slots.values():
        for gid in placed:
            parent[root(gid)] = root(next(iter(placed)))
    return {gid: root(gid) for gid in list(parent)}


def offset_of(builder, groups, first, size):
    """(offset, group id to column key) when the page's first row fits the open table's columns at a page offset, else None. A group is compared
    with a column at every alignment: the same column can be right-aligned on one page and, where its amounts happen to be of equal width, left- or
    centre-aligned on another."""
    best = None
    tolerance = size * ALIGN

    def apart(info, edges, offset):
        return min(abs(info.edge_at(align) - (edge + offset)) for align, edge in edges.items())

    for gid in first:
        for edges in builder.frame.values():
            for align, edge in edges.items():
                offset = groups[gid].edge_at(align) - edge
                if abs(offset) > size * MAX_OFFSET:
                    continue
                mapping = {}
                for other, info in groups.items():
                    near = [(apart(info, edges2, offset), key2) for key2, edges2 in builder.frame.items() if apart(info, edges2, offset) <= tolerance]
                    if near:
                        mapping[other] = min(near)[1]
                if all(g in mapping for g in first):
                    rank = (-abs(offset), len(mapping))
                    if best is None or rank > best[0]:
                        best = (rank, offset, mapping)
    return (best[1], best[2]) if best else None


def key_of(gid, mapping, number):
    """A group's column key in the table: through the page offset's mapping when the table continues from an earlier page."""
    return mapping.get(gid, (number, gid)) if mapping else (number, gid)


def group_of(entries, positions, alignment):
    return Group(alignment, median(edge_of(entries[position][0].box, alignment) for position in positions),
                 span([entries[position][0] for position in positions]), [entries[position][0].box for position in positions])


def zones_of(groups, size):
    """The zones of a block's columns, left to right: each runs to the midpoint with its neighbour, the outer ones past their extent."""
    extents = sorted((group.extent for group in groups), key=sum)
    if not extents:
        return []
    centres = [sum(extent) / 2 for extent in extents]
    gaps = [right - left for left, right in zip(centres, centres[1:])]
    return zones_between(extents, median(gaps) / 2 if gaps else size * LONE_REACH)


def whole_columns(pay, groups, tolerance):
    """Tentative columns of whole numbers (FR-90, plan P1 step 2): the pay lines' runs (not the label's) holding one integer whose edge, at every
    alignment, is further than `tolerance` from every decimal column's, grouped by alignment like amounts. Each is (alignment, [(token, line index)]).
    A column of one row is allowed here: a heading over it decides whether it stays."""
    entries = [(token, line.index) for line in pay for tokens, led in zip(line.tokens[1:], line.led_by_text[1:]) if led and lone_integer(tokens)
               for token in tokens if all(abs(edge_of(token.box, align) - group.edge_at(align)) > tolerance for group in groups for align in ALIGNMENTS)]
    return [(alignment, [entries[position] for position in positions]) for alignment, positions in choose_alignments(entries, tolerance, lambda *_: 1)]


def with_whole_numbers(bl, kept):
    """(`bl` with the integers of the kept columns made amounts, old token id to new token). An amount token as phase 1's `read_line` makes one, and the
    run is no longer led by text, so the rest of the reader sees it (`table_engine` is not changed: FR-67)."""
    swap = {id(token): Token("amount", token.word_ids, token.box, token.text, amount_of(token.text)) for _, column in kept for token, _ in column}
    lines = []
    for line in bl:
        if any(id(token) in swap for run in line.tokens for token in run):
            tokens = [[swap.get(id(token), token) for token in run] for run in line.tokens]
            led = [flag and not any(id(token) in swap for token in run) for flag, run in zip(line.led_by_text, line.tokens)]
            line = Line(line.index, line.words, line.runs, tokens, led)
        lines.append(line)
    return lines, swap


def nearest_column(token, groups, tolerance):
    """The id of the decimal column whose edge, at some alignment, lies within `tolerance` of the token's (step 2's test reversed), the closest one; else None."""
    best = min(((abs(edge_of(token.box, align) - group.edge_at(align)), gid) for gid, group in groups.items() for align in ALIGNMENTS), default=None)
    return best[1] if best is not None and best[0] <= tolerance else None


def whole_numbers(view, bl, consumed, pay, extras, groups, edge):
    """The whole numbers of a block that are amounts (FR-90, plan P1 steps 2, 5 and 7): (kept columns, {decimal column id: tokens}). Kept columns are
    (alignment, [(token, line index)]) of whole numbers; the other is the integers of integer-only lines (`extras`) that print in a decimal column. An
    integer-only line counts only with a heading line above it (walking up over rows and section titles), so a details box above the first heading
    stays text, and only when every integer of it is read as an amount. A column of integer-only lines alone needs a heading piece over it and two
    rows; a column that pay lines share follows step 5 (a heading piece or two rows)."""
    tolerance = view.size * ALIGN
    pay_index = {line.index for line in pay}
    while True:
        lines = sorted([*pay, *extras], key=lambda line: line.index)
        tentative = whole_columns(lines, groups.values(), tolerance)
        if not tentative and not extras:
            return [], {}
        extra = [Group(alignment, median(edge_of(token.box, alignment) for token, _ in column), span([token for token, _ in column]),
                       [token.box for token, _ in column]) for alignment, column in tentative]
        every = [*groups.values(), *extra]
        zones = zones_of(every, view.size)
        zone_of = {id(group): zone for group, zone in zip(sorted(every, key=lambda group: sum(group.extent)), zones)}
        heads = {index for line in lines for index in heads_above(bl, consumed, line.index, (view, zones, edge))}
        if extras:
            walkable = heads | pay_index | {line.index for line in extras} | {line.index for line in bl if is_title_like(line)}
            headed = []
            for line in extras:
                above = line.index - 1
                while above >= 0 and above not in consumed and above not in heads and above in walkable:
                    above -= 1
                if above >= 0 and above in heads:
                    headed.append(line)
            if len(headed) < len(extras):
                extras = headed
                continue
        pieces = [box for index in heads for _, box, _ in heading_runs(view, [bl[index]], zones, edge)]
        alone = {line.index for line in extras}
        kept = []
        for column, group in zip(tentative, extra):
            rows = {index for _, index in column[1]}
            over = any(in_zone(box, zone_of[id(group)]) for box in pieces)
            if (over and len(rows) >= 2) if rows <= alone else (over or len(rows) >= 2):
                kept.append(column)
        near = {}
        for line in extras:
            for tokens in line.tokens[1:]:
                gid = nearest_column(tokens[0], groups, tolerance)
                if gid is not None:
                    near.setdefault(gid, []).append(tokens[0])
        read = {id(token) for _, column in kept for token, _ in column} | {id(token) for tokens in near.values() for token in tokens}
        bad = {line.index for line in extras if any(id(tokens[0]) not in read for tokens in line.tokens[1:])}
        if not bad:
            return kept, near
        extras = [line for line in extras if line.index not in bad]


def read_block(number, view, bl, name, previous, made, boxes, serial, taken=frozenset(), stub=None, starts=None, whole=None, edge=None):
    """One block of a page: its summary boxes, then its tables and unplaced lines. `taken` is the lines of a summary box found across the whole page
    (before the page was split into blocks); `stub` is the dates printed on the start lines of the stub being read, kept across pages: a start line
    that prints only dates already in it repeats the stub's heading (a later page), so it doesn't end the open table. `starts`: the page's stub start
    lines (line index to its dates), found on the whole line, so that a block the start line leaves empty ends its table too. `edge`: for the left block
    of a page, where the right block starts (heading words from there on are not this block's). Returns (tables still open, unplaced lines)."""
    stub = set() if stub is None else stub
    starts, whole = starts or {}, whole or {}
    tolerance = view.size * ALIGN
    consumed = find_boxes(number, view, bl, tolerance, boxes, taken)
    pay = [line for line in bl if line.index not in consumed and is_pay(line)]
    attached = {index for line in pay for index in heads_above(bl, consumed, line.index)}
    entries = [(token, line.index) for line in pay for token in amounts_of(line)]

    def supported(rows, alignment, centre):
        first = min(rows)
        # A run joining two close headings (`This Period Year to Date`) supports a one-row column by a piece's edge too: docs/documents.md "Pay stub rows from the printed columns".
        return 1 if any(index < first and any(abs(edge_of(union(view.box[word.id] for word in piece), alignment) - centre) <= tolerance
                                              for run in bl[index].runs for piece in [run, *run_pieces(view, run, edge=edge)]) for index in attached) else 0

    found = choose_alignments(entries, tolerance, supported)
    groups = {gid: group_of(entries, positions, alignment) for gid, (alignment, positions) in enumerate(found)}
    # Whole-number amounts (FR-90): columns of integers under a heading or on two rows, and the integers of rows printed in whole numbers only.
    kept, near = whole_numbers(view, bl, consumed, pay, [line for line in bl if line.index not in consumed and integer_only(line)], groups, edge)
    if kept or near:
        old = [token for token, _ in entries]
        bl, swap = with_whole_numbers(bl, [*kept, (None, [(token, None) for tokens in near.values() for token in tokens])])
        pay = [line for line in bl if line.index not in consumed and is_pay(line)]
        entries = [(token, line.index) for line in pay for token in amounts_of(line)]
        at = {id(token): position for position, (token, _) in enumerate(entries)}
        decimal = [(alignment, [*(at[id(swap.get(id(old[position]), old[position]))] for position in positions), *(at[id(swap[id(token)])] for token in near.get(gid, []))])
                   for gid, (alignment, positions) in enumerate(found)]
        whole_found = [(alignment, [at[id(swap[id(token)])] for token, _ in column]) for alignment, column in kept]
        found = sorted([*decimal, *whole_found], key=lambda item: min(item[1]))
        groups = {gid: group_of(entries, positions, alignment) for gid, (alignment, positions) in enumerate(found)}
    zones = zones_of(groups.values(), view.size)
    pay_index = {line.index for line in pay}
    attached = {index for line in pay for index in heads_above(bl, consumed, line.index, (view, zones, edge))}
    slots = {}
    place(slots, [(line.index, amounts_of(line)) for line in pay], found)
    sets = column_sets(slots)

    def repeats(line, builder):
        """Whether a heading line only repeats the open table's own: its words are the table's, and the row after it prints in the table's columns
        (a second table with the same wording over other columns has a heading of its own)."""
        if not words_of([line]) <= builder.heading_words:
            return False
        after = next((item.index for item in bl if item.index > line.index and item.index in pay_index), None)
        return after is None or not slots[after][0] or bool({sets[gid] for gid in slots[after][0]} & builder.comps)

    before = len(made)
    cur, mapping, offset = None, None, 0.0
    section, title, last = None, None, None  # `last` is (entry, line index): the row a wrapped label may join.
    pending = []  # Heading line indexes waiting for their table.
    unplaced = []
    first = next((line.index for line in pay if slots[line.index][0]), None)
    if first is not None:
        for builder in reversed(previous):
            matched = offset_of(builder, groups, list(slots[first][0]), view.size)
            if matched:
                cur, (offset, mapping) = builder, matched
                cur.comps = {sets[gid] for gid in mapping if gid in sets}
                section = builder.section
                previous.remove(builder)
                break

    def close():
        nonlocal cur, mapping, offset, section, title, last
        if cur is not None:
            cur.section = section
        cur, mapping, offset, section, title, last = None, None, 0.0, None, None, None

    for line in bl:
        index = line.index
        if index in starts and index not in consumed:
            dates = starts[index]
            if cur is not None and dates <= stub:
                continue  # The stub's heading repeated on a later page (FR-55, FR-80).
            if cur is not None:
                stub.clear()
            close()
            pending = []
            stub |= dates
            continue
        if index in consumed or not line.runs:
            last = title = None
            continue
        if index in attached and any(in_zone(box, zone) for box in (*(union(view.box[word.id] for word in run) for run in line.runs),
                                                                     *(box for _, box, _ in heading_runs(view, [line], zones, edge))) for zone in zones):
            if cur is not None and repeats(line, cur):
                last = title = None  # The table's own heading, repeated: ignored (FR-55).
                continue
            close()
            pending = [*pending, index] if pending and pending[-1] == index - 1 else [index]
            continue
        if index in pay_index:
            placed, stray = slots[index]
            if not placed:
                unplaced.append(Unplaced(number, (view.lines([line.words[0].id]) or [""])[0], line_text(line)))
                last = title = None
                continue
            if cur is not None and not {sets[gid] for gid in placed} & cur.comps:
                carried = title
                close()
                title = carried  # A section title directly above a new table's first row belongs to it.
                pending = []
            if cur is None:
                heads = [bl[item] for item in pending]
                above = bl[pending[0] - 1] if pending and pending[0] > 0 and pending[0] - 1 not in consumed else None
                serial[0] += 1
                cur = Builder(f"page-{number}-pay-{serial[0]}", name, view.size, heading_runs(view, heads, zones, edge), [line_text(item) for item in heads],
                              words_of(heads), line_text(above) if above is not None and is_title_like(above) else None)
                made.append(cur)
                pending, mapping, offset, section = [], None, 0.0, None
            cur.comps |= {sets[gid] for gid in placed}
            if title is not None:
                section = title
            title = None
            keys = {}
            for gid, token in placed.items():
                key = key_of(gid, mapping, number)
                keys[key] = token
                cur.members.setdefault(key, []).append((token, offset))
                cur.aligns.setdefault(key, groups[gid].align)
            if number not in cur.pages:
                cur.pages.append(number)
            label = label_of(line)
            kind = total_kind(label)
            entry = {"page": number, "kind": kind, "word_ids": [word.id for word in line.words], "label": label, "keys": keys,
                     "section": section, "stray": stray, "line": index}
            cur.entries.append(entry)
            cur.label_lefts.append(view.box[line.runs[0][0].id][0] - offset)
            last = (entry, index) if kind is None else None
            if kind == "net":
                close()  # A table ends after its net pay (P3.6).
                stub.clear()
            continue
        if not text_only(line):
            last = title = None
            continue
        left = view.box[line.runs[0][0].id][0]
        if (last is not None and index == last[1] + 1 and cur is not None and whole.get(index, len(line.runs)) == 1
                and left - (median(cur.label_lefts) + offset) > tolerance):
            entry = last[0]  # Indented under a row: the rest of its label (FR-54).
            entry["word_ids"] += [word.id for word in line.words]
            entry["label"] = f"{entry['label']} {line_text(line)}"
            last, title = (entry, index), None
            continue
        after = bl[index + 1] if index + 1 < len(bl) else None
        # A title over a page's first headerless table is no section: only a title in an open table, over a heading, or after another table is.
        opens = cur is not None or bool(pending) or len(made) > before
        title = line_text(line) if opens and is_title_like(line) and after is not None and after.index in pay_index \
            and abs(left - view.box[after.runs[0][0].id][0]) <= tolerance else None
        last = None
    opened = [cur] if cur is not None else []
    if cur is not None:
        cur.section = section
        cur.frame = {key: {align: median(edge_of(token.box, align) - shift for token, shift in members) for align in ALIGNMENTS}
                     for key, members in cur.members.items()}
    return opened, unplaced


def read(result):
    """Read a saved reading (`PDFResult`) into its pay tables. Only `embedded_text` pages with a saved layout are read."""
    views, made, boxes, unplaced, without, previous, stub = {}, [], [], [], [], [], {}
    for page in result.pages:
        if page.method != "embedded_text" or page.layout is None:
            previous = []
            continue
        number = page.number
        view = views[number] = PageView(page.layout)
        lines = [split_tails(line) for line in tokenize_page(view)]
        taken = find_boxes(number, view, lines, view.size * ALIGN, boxes)  # A summary box above side-by-side blocks spans both (FR-53, FR-75).
        blocks = blocks_of(view, lines, view.size * ALIGN)
        names = ("left", "right") if len(blocks) == 2 else (None,)
        split = block_split(view, lines, view.size * ALIGN)
        edges = (split - view.size * ALIGN, None) if len(blocks) == 2 else (None,)
        starts = {line.index: stub_dates(line) for line in lines if starts_stub(line)}
        whole = {line.index: len(line.runs) for line in lines}  # How many runs each line has across the whole page (blocks cut it).
        serial, still, extra = [0], [], []
        before = len(made)
        for name, block, edge in zip(names, blocks, edges):
            tables = tables_cut(view, block, starts)
            for position, (bl, indexes) in enumerate(tables):
                kept, lost = read_block(number, view, bl, name, previous if position == 0 else [], made, boxes, serial, taken, stub.setdefault(name, set()),
                                        {index: dates for index, dates in starts.items() if index in indexes}, whole, edge)
                if position == len(tables) - 1:
                    still += kept
                extra += lost
        created = made[before:]
        if len(created) == 2 and created[0].block == "left" and created[1].block == "right":
            created[0].partner, created[1].partner = created[1].id, created[0].id
        else:  # More tables on the page (a deposit or leave table under the left block): a right table sits beside the left one it shares lines with.
            lefts = [builder for builder in created if builder.block == "left"]
            for right in (builder for builder in created if builder.block == "right"):
                shared = {entry["line"] for entry in right.entries if entry["page"] == number}
                best = max(lefts, key=lambda left: len(shared & {entry["line"] for entry in left.entries if entry["page"] == number}), default=None)
                if best is not None and best.partner is None and shared & {entry["line"] for entry in best.entries if entry["page"] == number}:
                    best.partner, right.partner = right.id, best.id
        if any(number in builder.pages for builder in made):
            unplaced += extra
        else:
            without.append(number)
        previous = still
    return PayReading([finish(builder, views) for builder in made],
                      [finish_box(box, views[box.entries[0]["page"]].lines(words), views[box.entries[0]["page"]]) for box, words in boxes], [], unplaced, without)
