"""Pay tables from a saved PDF reading's positioned words (specs/pdf-table-engine-paystubs, plan P3).

`read` takes one saved reading and returns a `PayReading`. It is pure and deterministic like `table_engine`: no store, model, network, clock or
randomness, and it never opens the PDF. It reuses the engine's primitives (tokens, visual rows, alignment groups, zones) and imports nothing
from `finance/`. `table_engine.read`, `build_layout`, `scan`, `cuts` and `continuation` are not changed, so statements can't move (FR-67).

What it finds. A pay row starts at a visual line whose first run is text (the label) and that holds an amount in a run not led by text; no date
or heading is needed (FR-50). Integers and numbers joined to letters stay label text (FR-51). A page whose lines carry a second label-and-amounts
group is split into two blocks, each read on its own (FR-53). Columns come from alignment alone, headings only label them (FR-52). Section titles
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
MAX_OFFSET = 8  # A later page's table sits at most this many font sizes from where the first page's did.


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
        cut = next((i for i in range(1, len(found)) if found[i - 1].kind == "amount" and found[i].kind in ("text", "integer")), None)
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
    return [index for index in range(1, len(line.runs)) if line.led_by_text[index] and any(j < index for j in amounts) and any(j > index for j in amounts)]


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


def heading_runs(view, lines, zones=()):
    """The heading lines' runs as (text, box, word ids). A run is split where its words are further apart than a space and lie in the zones of
    different columns (two headings printed close enough to read as one phrase: `This Period` `Year to Date`)."""
    made = []
    for line in lines:
        for run in line.runs:
            pieces, last = [], None
            for word in run:
                box = view.box[word.id]
                zone = next((number for number, found in enumerate(zones) if in_zone(box, found)), None)
                if pieces and not (zone is not None and last is not None and zone != last[0] and box[0] - last[1] > view.size / 2):
                    pieces[-1].append(word)
                else:
                    pieces.append([word])
                last = (zone, box[2])
            made += [(run_text(piece), union(view.box[word.id] for word in piece), [word.id for word in piece]) for piece in pieces]
    return made


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


def heads_above(bl, consumed, index):
    """The heading lines directly above a line, top to bottom: up to two, with at most one title line between them and the row."""
    found, skipped, above = [], False, index - 1
    while above >= 0 and len(found) < 2 and above not in consumed:
        line = bl[above]
        if is_heading_like(line):
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


def read_block(number, view, bl, name, previous, made, boxes, serial, taken=frozenset(), stub=None, starts=None, whole=None):
    """One block of a page: its summary boxes, then its tables and unplaced lines. `taken` is the lines of a summary box found across the whole page
    (before the page was split into blocks); `stub` is the dates printed on the start lines of the stub being read, kept across pages: a start line
    that prints only dates already in it repeats the stub's heading (a later page), so it doesn't end the open table. `starts`: the page's stub start
    lines (line index to its dates), found on the whole line, so that a block the start line leaves empty ends its table too. Returns (tables still
    open, unplaced lines)."""
    stub = set() if stub is None else stub
    starts, whole = starts or {}, whole or {}
    tolerance = view.size * ALIGN
    consumed = find_boxes(number, view, bl, tolerance, boxes, taken)
    pay = [line for line in bl if line.index not in consumed and is_pay(line)]
    pay_index = {line.index for line in pay}
    attached = {index for line in pay for index in heads_above(bl, consumed, line.index)}
    entries = [(token, line.index) for line in pay for token in amounts_of(line)]

    def supported(rows, alignment, centre):
        first = min(rows)
        return 1 if any(index < first and any(abs(edge_of(union(view.box[word.id] for word in run), alignment) - centre) <= tolerance
                                              for run in bl[index].runs) for index in attached) else 0

    found = choose_alignments(entries, tolerance, supported)
    groups = {gid: Group(alignment, median(edge_of(entries[position][0].box, alignment) for position in positions),
                         span([entries[position][0] for position in positions]), [entries[position][0].box for position in positions])
              for gid, (alignment, positions) in enumerate(found)}
    slots = {}
    place(slots, [(line.index, amounts_of(line)) for line in pay], found)
    sets = column_sets(slots)
    zones = []
    if groups:
        extents = sorted((group.extent for group in groups.values()), key=sum)
        centres = [sum(extent) / 2 for extent in extents]
        gaps = [right - left for left, right in zip(centres, centres[1:])]
        zones = zones_between(extents, median(gaps) / 2 if gaps else view.size * LONE_REACH)

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
        if index in attached and any(in_zone(union(view.box[word.id] for word in run), zone) for run in line.runs for zone in zones):
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
                cur = Builder(f"page-{number}-pay-{serial[0]}", name, view.size, heading_runs(view, heads, zones), [line_text(item) for item in heads],
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
        starts = {line.index: stub_dates(line) for line in lines if starts_stub(line)}
        whole = {line.index: len(line.runs) for line in lines}  # How many runs each line has across the whole page (blocks cut it).
        serial, still, extra = [0], [], []
        before = len(made)
        for name, bl in zip(names, blocks):
            kept, lost = read_block(number, view, bl, name, previous, made, boxes, serial, taken, stub.setdefault(name, set()), starts, whole)
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
