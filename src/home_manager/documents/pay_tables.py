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


def words_of(lines):
    return {token.text.lower() for line in lines for token in line.all_tokens()}


# --- Blocks (FR-53) ------------------------------------------------------------------------------------------------------

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


@dataclass
class Builder:
    """A table being read: it may take rows from later pages."""
    id: str
    block: str | None
    size: float
    head_runs: list  # (text, box) of the heading lines' runs, top to bottom.
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
    frame: dict = field(default_factory=dict)  # column key -> (alignment, edge) in the first page's frame, while the table is open.


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
        label = [text for text, box in builder.head_runs if in_zone(box, zone)]
        columns.append(PayColumn(f"{builder.id}-column-{len(columns) + 1}", align, edge, extent, zone, label))
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


def heading_runs(view, lines):
    return [(run_text(run), union(view.box[word.id] for word in run)) for line in lines for run in line.runs]


def find_boxes(number, view, bl, tolerance, found_boxes):
    """Summary boxes of a block (FR-75): the lines they use, including a heading printed directly above, are returned as consumed."""
    consumed = set()
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
    position = 0
    for index, tokens in entries:
        placed, stray = {}, []
        for token in tokens:
            gid = gid_of.get(position)
            position += 1
            if gid is None or gid in placed:
                stray.append(token)
            else:
                placed[gid] = token
        slots[index] = (placed, stray)


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
    """(offset, group id to column key) when the page's first row fits the open table's columns at a page offset, else None."""
    best = None
    tolerance = size * ALIGN
    for gid in first:
        for _, (align, edge) in builder.frame.items():
            if groups[gid].align != align:
                continue
            offset = groups[gid].edge - edge
            if abs(offset) > size * MAX_OFFSET:
                continue
            mapping = {}
            for other, info in groups.items():
                near = [(abs(info.edge - (edge2 + offset)), key2) for key2, (align2, edge2) in builder.frame.items()
                        if align2 == info.align and abs(info.edge - (edge2 + offset)) <= tolerance]
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


def read_block(number, view, bl, name, previous, made, boxes, serial):
    """One block of a page: its summary boxes, then its tables and unplaced lines. Returns (tables still open, unplaced lines)."""
    tolerance = view.size * ALIGN
    consumed = find_boxes(number, view, bl, tolerance, boxes)
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
                         span([entries[position][0] for position in positions])) for gid, (alignment, positions) in enumerate(found)}
    slots = {}
    place(slots, [(line.index, amounts_of(line)) for line in pay], found)
    sets = column_sets(slots)
    zones = []
    if groups:
        extents = sorted((group.extent for group in groups.values()), key=sum)
        centres = [sum(extent) / 2 for extent in extents]
        gaps = [right - left for left, right in zip(centres, centres[1:])]
        zones = zones_between(extents, median(gaps) / 2 if gaps else view.size * LONE_REACH)

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
        if index in consumed or not line.runs:
            last = title = None
            continue
        if starts_stub(line):
            close()
            pending = []
            continue
        if index in attached and any(in_zone(union(view.box[word.id] for word in run), zone) for run in line.runs for zone in zones):
            if cur is not None and words_of([line]) <= cur.heading_words:
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
                cur = Builder(f"page-{number}-pay-{serial[0]}", name, view.size, heading_runs(view, heads), [line_text(item) for item in heads],
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
                     "section": section, "stray": stray}
            cur.entries.append(entry)
            cur.label_lefts.append(view.box[line.runs[0][0].id][0] - offset)
            last = (entry, index) if kind is None else None
            if kind == "net":
                close()  # A table ends after its net pay (P3.6).
            continue
        if not text_only(line):
            last = title = None
            continue
        left = view.box[line.runs[0][0].id][0]
        if last is not None and index == last[1] + 1 and cur is not None and left - (median(cur.label_lefts) + offset) > tolerance:
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
        cur.frame = {key: (cur.aligns[key], median(edge_of(token.box, cur.aligns[key]) - shift for token, shift in members))
                     for key, members in cur.members.items()}
    return opened, unplaced


def read(result):
    """Read a saved reading (`PDFResult`) into its pay tables. Only `embedded_text` pages with a saved layout are read."""
    views, made, boxes, unplaced, without, previous = {}, [], [], [], [], []
    for page in result.pages:
        if page.method != "embedded_text" or page.layout is None:
            previous = []
            continue
        number = page.number
        view = views[number] = PageView(page.layout)
        lines = tokenize_page(view)
        blocks = blocks_of(view, lines, view.size * ALIGN)
        names = ("left", "right") if len(blocks) == 2 else (None,)
        serial, still, extra = [0], [], []
        before = len(made)
        for name, bl in zip(names, blocks):
            kept, lost = read_block(number, view, bl, name, previous, made, boxes, serial)
            still += kept
            extra += lost
        created = made[before:]
        if len(created) == 2 and created[0].block == "left" and created[1].block == "right":
            created[0].partner, created[1].partner = created[1].id, created[0].id
        if any(number in builder.pages for builder in made):
            unplaced += extra
        else:
            without.append(number)
        previous = still
    return PayReading([finish(builder, views) for builder in made],
                      [finish_box(box, views[box.entries[0]["page"]].lines(words), views[box.entries[0]["page"]]) for box, words in boxes], [], unplaced, without)
