"""Charge tables from a saved PDF reading's positioned words (specs/pdf-table-engine-bills, plan P1 - P3).

`read` takes one saved reading and returns a `BillReading`. It is pure and deterministic like `table_engine` and `pay_tables`: no store, model, network, clock or
randomness, and it never opens the PDF. It imports the engine's primitives and the pay engine's helpers and nothing from `finance/`. Neither of those modules
is changed, so statements and pay stubs can't move (FR-120).

What it finds. A charge row starts at a visual line whose first run is text (the label) and that holds an amount in a later run (FR-100). Dates and numbers
joined to a unit word (`500 kWh`, `3,200 GAL`) are label text or usage, never money. Columns come from alignment alone, headings only label them (FR-101).
Sections, holder titles, totals, indented wrapped labels and tables that continue over pages are told from rows (FR-102). A line that names a summary amount
is an anchor wherever it is printed, a line that applies only after a date is a late line and nothing else (FR-103). A table of whole numbers (a usage
history) is another table, and every label-and-amount line that is none of these is listed as unplaced (FR-104).

Not here (SL-02): which column of a charge table is the charge, the quantity or the rate (FR-105), money off (FR-106) and the guesses. `BillReading.tables`
holds every table with an amount column, `other_tables` the tables whose columns are all whole numbers or usage; the role pass may move more of them.
"""

from dataclasses import dataclass, field
from decimal import Decimal
import re
from statistics import median

from .pay_tables import (
    MAX_OFFSET,
    column_sets,
    group_of,
    heading_runs,
    heads_above,
    is_title_like,
    key_of,
    line_text,
    readable,
    run_pieces,
    split_tails,
    text_only,
    words_of,
)
from .table_engine import (
    ALIGN,
    ALIGNMENTS,
    CODES,
    LONE_REACH,
    MONTH,
    Line,
    PageView,
    Token,
    amount_of,
    choose_alignments,
    edge_of,
    in_zone,
    tokenize_page,
    union,
    zones_between,
)

# --- The fixed word lists (plan P1; documented in docs/documents.md, SL-10) ----------------------------------------------

# FR-103. Each anchor kind is a set of whole-label phrases: lower case, dates, dot leaders, `$`, `:` and separating dashes removed (`clean_label`).
ANCHOR_WORDS = {
    "previous_balance": ("previous balance", "balance forward", "last bill", "previous bill amount"),
    "payments": ("payment", "payments", "payment received", "payments received", "payment thank you", "payments thank you"),
    "new_charges": ("new charges", "current charges", "total current charges", "total new charges"),
    "amount_due": ("amount due", "total amount due", "total due", "balance due", "amount to pay", "total amount to pay", "payment due"),
}
ANCHOR_KIND = {phrase: kind for kind, phrases in ANCHOR_WORDS.items() for phrase in phrases}
SENTENCE_EXTRA = 3  # A label holding a multi-word anchor phrase plus at least this many other words is a sentence (G7).

DATE = (r"(?:\d{1,2}/\d{1,2}(?:/\d{2,4})?|\d{4}-\d{2}-\d{2}|\d{1,2}[.-]\d{1,2}[.-]\d{2,4}"
        rf"|(?:{MONTH})\b\.? \d{{1,2}}(?:,? \d{{4}})?|\d{{1,2}} (?:{MONTH})\b\.?(?: \d{{4}})?)")
_WHEN = rf"(?:by|on or before|as of|on)\s+{DATE}"

# FR-103 / bill-kinds FR-58: an amount that applies only later. A condition with a date, then one without (review pass 2, m3).
LATE_WORDS = re.compile("|".join((
    rf"\bif\s+(?:paid|received)\s+after\s+{DATE}", rf"\bif\s+not\s+paid\s+by\s+{DATE}", rf"\bafter\s+{DATE}\s*,?\s*(?:pay|a\s+late)",
    rf"\blate\s+(?:fee|charge|payment\s+charge)\s+(?:after|if\s+not\s+paid\s+by|applies\s+after)\s+{DATE}",
    r"\bif\s+paid\s+late\b", r"\bif\s+(?:payment\s+is|paid)\s+(?:late|after\s+the\s+due\s+date)", r"\bif\s+not\s+paid\s+on\s+time",
    r"\bif\s+not\s+paid\s+by\s+the\s+due\s+date")), re.IGNORECASE)
TOTAL_WORDS = (re.compile(r"^(?:sub)?total\b"), re.compile(r"^total for\b"), re.compile(r"\btotal$"))  # FR-102
CREDIT_SECTION = re.compile(r"\b(?:credits?|discounts?|adjustments?)\b", re.IGNORECASE)  # FR-106 (used by the role pass)

# FR-128's key labels. They live here, not in documents/bill_split.py (SL-06), because the key line is a class of line the charge reader needs and
# bill_split imports `anchor_kind` from this module: one module can't import the other both ways. SL-06 may move the list and import it here lazily.
KEY_LABELS = {
    "due_date": ("due date", "payment due date", "payment due"),
    "statement_date": ("statement date", "bill date", "billing date"),
    "account": ("account number", "account no.", "account no", "account #", "account"),
}

# FR-102 (a): a phone number in a section title. (i) grouped digits ending in a 4-digit group directly after a 3-digit group (G14: a year range or an
# account number is none), (ii) masked, (iii) after `ending`, `ending in` or `ends in`.
PHONE = re.compile("|".join((
    r"(?<![\d,])(?<!\d[\s.,-])(?:\+?1[\s.-])?(?:\(\d{3}\)\s?|\d{3}[\s.-])?\d{3}[\s.-]\d{4}(?![\s.-]?\d)",
    r"(?<![A-Za-z0-9])(?:[xX*•]+[\s.-]?)+\d{4}(?!\d)",
    r"\b(?:ending(?:\s+in)?|ends\s+in)\s+\d{4}\b")), re.IGNORECASE)

UNITS = frozenset(("CR", "DR")) | CODES


# --- Contracts (plan P2) -------------------------------------------------------------------------------------------------

@dataclass
class ChargeColumn:
    id: str
    align: str  # right, left or centre
    edge: float  # The group's median edge, in the table's first page.
    extent: tuple[float, float]
    zone: tuple[float, float]
    labels: list[str] = field(default_factory=list)  # Heading words over it, top to bottom.
    label_words: list[list[str]] = field(default_factory=list)  # The word ids of each label.
    kind: str = "amount"  # amount, usage (numbers printed with a unit word, kept as printed text) or integer (whole numbers: never money)


@dataclass
class SectionTitle:
    page: int
    line_id: str
    word_ids: list[str]
    text: str
    phone: bool  # FR-102 (a) holds on the title's text alone.


@dataclass
class ChargeRow:
    page: int
    table_id: str
    row: int  # 1-based among the table's rows and totals in printed order.
    line_ids: list[str]
    word_ids: list[str]
    label: str
    amounts: dict[str, Token]  # Column id to the amount (or whole number) printed there.
    usage: dict[str, tuple[str, list[str]]] = field(default_factory=dict)  # Column id to (the printed text `500 kWh`, its word ids).
    section: str | None = None
    title: SectionTitle | None = None
    stray: list[Token] = field(default_factory=list)  # Amounts of the line that sit in no column of the table.


@dataclass
class ChargeTotal:
    page: int
    table_id: str
    row: int
    line_id: str
    word_ids: list[str]
    label: str
    values: dict[str, Token]


@dataclass
class Anchor:
    page: int
    line_id: str
    word_ids: list[str]
    kind: str  # previous_balance, payments, new_charges or amount_due
    token: Token
    order: int  # Reading order over the whole reading: 0, 1, 2 ... (FR-117 takes the first amount-due anchor on the first page).


@dataclass
class Unplaced:
    page: int
    line_id: str
    text: str


@dataclass
class ChargeTable:
    id: str  # page-<p>-charges-<n>
    pages: list[int]
    label_column: tuple[float, float]
    columns: list[ChargeColumn]
    rows: list[ChargeRow]
    totals: list[ChargeTotal]
    titles: list[SectionTitle]
    headings: list[str]  # The text of the heading lines, top to bottom.


@dataclass
class BillReading:
    tables: list[ChargeTable]
    other_tables: list[ChargeTable] = field(default_factory=list)
    anchors: list[Anchor] = field(default_factory=list)
    late_lines: list[str] = field(default_factory=list)
    unplaced: list[Unplaced] = field(default_factory=list)
    pages_without_tables: list[int] = field(default_factory=list)
    line_pages: dict[str, int] = field(default_factory=dict)  # Every saved line id of a page that was read, to its page.


@dataclass
class Cell:
    """An amount, a number with its unit word, or a whole number printed in a column position of a row."""
    kind: str  # amount, usage or integer
    token: Token  # A usage cell's token has kind "usage": its value is the number and its text the number and unit as printed.
    text: str
    word_ids: list[str]


# --- Words ---------------------------------------------------------------------------------------------------------------

def clean_label(text):
    """A label for the anchor list (P3.2): lower case, dates removed with a directly preceding `by`, `on or before`, `as of` or `on`, dot leaders, `$`, `:`,
    `|` and separating dashes removed, whitespace collapsed."""
    text = re.sub(rf"\b{_WHEN}|{DATE}", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\.{2,}|…+|[$|:]", " ", text)
    text = re.sub(r"(?:^|\s)[–—-]+(?=\s|$)", " ", text)
    return " ".join(text.lower().split())


def anchor_kind(label):
    """The kind of summary anchor a line's label is (whole label, whole words, case-insensitive), else None (FR-103)."""
    return ANCHOR_KIND.get(clean_label(label))


def is_sentence(label):
    """A label holding a multi-word anchor phrase among at least `SENTENCE_EXTRA` other words (`Your previous balance was paid in full`): no anchor and no
    charge row, an unplaced line (G7)."""
    text = clean_label(label)
    words = len(text.split())
    return any(" " in phrase and re.search(rf"\b{re.escape(phrase)}\b", text) and words - len(phrase.split()) >= SENTENCE_EXTRA for phrase in ANCHOR_KIND)


def key_kind(text):
    """The key a line prints (FR-128): `due_date`, `statement_date` or `account` when the text starts with a key label directly followed by its value (dot
    leaders and a colon allowed), else None. A date key needs a date, the account a word holding a digit."""
    text = " ".join(text.lower().split())
    for kind, labels in KEY_LABELS.items():
        for label in sorted(labels, key=len, reverse=True):
            if not text.startswith(label):
                continue
            rest = text[len(label):]
            if rest[:1].isalpha():
                continue
            rest = re.sub(r"^[\s.:#…]+", "", rest)
            if (re.match(DATE, rest, re.IGNORECASE) if kind != "account" else re.match(r"\S*\d", rest)):
                return kind
    return None


def is_total(label):
    text = " ".join(label.lower().split()).rstrip(":").strip()
    return any(pattern.search(text) for pattern in TOTAL_WORDS)


def usage_value(text):
    """The number of a usage cell's printed text (`1,234 kWh` is 1234)."""
    return Decimal(text.split()[0].replace(",", ""))


def label_text(words):
    """Printed label words as a label: dot leaders dropped, whitespace collapsed."""
    return " ".join(re.sub(r"\.{2,}|…+", " ", " ".join(words)).split())


# --- Lines ---------------------------------------------------------------------------------------------------------------

def number_of(token):
    if token.kind == "integer":
        return Decimal(token.value)
    return token.value[0] if token.kind == "amount" and token.value[0] is not None else None


def merge_usage(line):
    """A number directly followed in its run by a word with a letter in it, other than `CR`, `DR` or an ISO code, is usage (FR-100): one token of kind
    `usage` over both words, label text or the value of a usage column, never money."""
    changed, runs = False, []
    for found in line.tokens:
        merged, index = [], 0
        while index < len(found):
            token, after = found[index], found[index + 1] if index + 1 < len(found) else None
            if number_of(token) is not None and after is not None and after.kind == "text" and after.text not in UNITS and re.search(r"[A-Za-z]", after.text):
                merged.append(Token("usage", [*token.word_ids, *after.word_ids], union((token.box, after.box)), f"{token.text} {after.text}", number_of(token)))
                index, changed = index + 2, True
            else:
                merged.append(token)
                index += 1
        runs.append(merged)
    return rebuilt(line, runs) if changed else line


def rebuilt(line, tokens):
    return Line(line.index, line.words, line.runs, tokens, [found[0].kind in ("text", "integer") for found in tokens])


def without_phones(line):
    """The tokens a `PHONE` match covers become text tokens (review pass 1, M3): the tokenizer reads `(555)` as an amount, which would keep
    `Blair (555) 202-2222` from being text only. A match that is one plain decimal word (`123.4567`) is a number, not a phone."""
    text, spans = "", []
    for word in line.words:
        text += (" " if text else "") + word.text
        spans.append((len(text) - len(word.text), len(text), word))
    covered = set()
    for match in PHONE.finditer(text):
        words = [word for start, end, word in spans if start < match.end() and end > match.start()]
        if len(words) == 1 and (amount_of(words[0].text) or (None,))[0] is not None and not words[0].text.startswith("("):
            continue
        covered.update(word.id for word in words)
    if not covered:
        return line
    return rebuilt(line, [[Token("text", token.word_ids, token.box, token.text) if token.kind in ("amount", "usage") and covered & set(token.word_ids) else token
                           for token in found] for found in line.tokens])


def cells_of(tokens, led):
    """The cells one run after the label holds (P3 step 5). A run led by text or a number holds at most a lone whole number; any other run holds its
    amounts, usage and its lone whole number (an amount is not read in a run led by text: the label's)."""
    if led:
        return [Cell("integer", tokens[0], tokens[0].text, tokens[0].word_ids)] if len(tokens) == 1 and tokens[0].kind == "integer" else []
    found = []
    for token in tokens:
        if token.kind == "usage":
            found.append(Cell("usage", token, token.text, token.word_ids))
        elif readable(token):
            found.append(Cell("amount", token, token.text, token.word_ids))
        elif token.kind == "integer" and len(tokens) == 1:
            found.append(Cell("integer", token, token.text, token.word_ids))
    return found


def shape(line):
    """(label, label word ids, cells) of a line that has the shape of a row: its first run holds the label (text first, and a word of text in it), the runs
    up to the first run with a cell are label too, and at least one cell follows. Else None."""
    if not line.runs or line.tokens[0][0].kind not in ("text", "integer") or not any(token.kind == "text" for token in line.tokens[0]):
        return None
    cells, label_words, seen = [], list(line.runs[0]), False
    for run, tokens, led in zip(line.runs[1:], line.tokens[1:], line.led_by_text[1:]):
        found = cells_of(tokens, led)
        if found:
            seen = True
            cells.extend(found)
        elif not seen:
            label_words.extend(run)
    if not cells:
        return None
    return label_text(word.text for word in label_words), [word.id for word in label_words], cells


def late(line, text):
    return LATE_WORDS.search(text) is not None and any(readable(token) for token in line.all_tokens())


def classify(line):
    """(class, data) of a line, first match wins (P3 steps 1 - 6): late, anchor (kind, token), key, sentence, total, row (label, word ids, cells) or text."""
    text = line_text(line)
    amounts = [token for token in line.all_tokens() if readable(token)]
    if amounts and LATE_WORDS.search(text):
        return "late", None
    if amounts:
        before = []
        for word in line.words:
            if word.id == amounts[-1].word_ids[0]:
                break
            before.append(word.text)
        kind = anchor_kind(" ".join(before))
        if kind:
            return "anchor", (kind, amounts[-1])
    if not amounts and key_kind(text):
        return "key", None
    found = shape(line)
    if found and any(cell.kind == "amount" for cell in found[2]):
        if is_sentence(found[0]):
            return "sentence", None
        if is_total(found[0]):
            return "total", found
    return ("row", found) if found else ("text", None)


# --- Tables --------------------------------------------------------------------------------------------------------------

@dataclass
class Builder:
    """A table being read: it may take rows from later pages."""
    id: str
    size: float
    head_runs: list  # (text, box, word ids) of the heading lines' runs, top to bottom.
    headings: list[str]
    heading_words: set
    entries: list = field(default_factory=list)
    members: dict = field(default_factory=dict)  # column key -> [(token, page offset)]
    kinds: dict = field(default_factory=dict)  # column key -> amount, usage or integer
    aligns: dict = field(default_factory=dict)
    comps: set = field(default_factory=set)  # The column sets of the page being read that its rows use.
    label_lefts: list = field(default_factory=list)
    pages: list = field(default_factory=list)
    titles: list = field(default_factory=list)
    section: SectionTitle | None = None
    frame: dict = field(default_factory=dict)  # column key -> {alignment: edge} in the first page's frame, while the table is open.


def extent_of(builder, key):
    boxes = [(token.box[0] - offset, token.box[2] - offset) for token, offset in builder.members[key]]
    return min(box[0] for box in boxes), max(box[1] for box in boxes)


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
        columns.append(ChargeColumn(f"{builder.id}-column-{len(columns) + 1}", align, edge, extent, zone, [text for text, _ in named],
                                    [words for _, words in named], builder.kinds[key]))
        ids[key] = columns[-1].id
    return columns


def finish(builder, view_of):
    """A builder's ChargeTable (plan P2)."""
    ids = {}
    columns = finish_columns(builder, ids)
    kind_of = {column.id: column.kind for column in columns}
    rows, totals = [], []
    for number, entry in enumerate(builder.entries, 1):
        view = view_of[entry["page"]]
        line_ids = view.lines(entry["word_ids"])
        cells = {ids[key]: cell for key, cell in entry["keys"].items()}
        if entry["kind"] == "total":
            totals.append(ChargeTotal(entry["page"], builder.id, number, line_ids[0] if line_ids else "", entry["word_ids"], entry["label"],
                                      {column: cell.token for column, cell in cells.items() if cell.kind != "usage"}))
        else:
            rows.append(ChargeRow(entry["page"], builder.id, number, line_ids, entry["word_ids"], entry["label"],
                                  {column: cell.token for column, cell in cells.items() if kind_of[column] != "usage"},
                                  {column: (cell.text, cell.word_ids) for column, cell in cells.items() if kind_of[column] == "usage"},
                                  entry["section"], entry["title"], entry["stray"]))
    lefts = builder.label_lefts
    return ChargeTable(builder.id, builder.pages, (min(lefts) if lefts else columns[0].zone[0], columns[0].zone[0]), columns, rows, totals,
                       builder.titles, builder.headings)


def offset_of(builder, groups, kinds, first, size):
    """(offset, group id to column key) when the page's first row fits the open table's columns at a page offset, else None. Like `pay_tables.offset_of`,
    but a group fits only a column of its own kind (a table of whole numbers under a charge table's columns is a table of its own)."""
    best, tolerance = None, size * ALIGN

    def apart(info, edges, offset):
        return min(abs(info.edge_at(align) - (edge + offset)) for align, edge in edges.items())

    for gid in first:
        for key, edges in builder.frame.items():
            if builder.kinds[key] != kinds[gid]:
                continue
            for align, edge in edges.items():
                offset = groups[gid].edge_at(align) - edge
                if abs(offset) > size * MAX_OFFSET:
                    continue
                mapping = {}
                for other, info in groups.items():
                    near = [(apart(info, edges2, offset), key2) for key2, edges2 in builder.frame.items()
                            if builder.kinds[key2] == kinds[other] and apart(info, edges2, offset) <= tolerance]
                    if near:
                        mapping[other] = min(near)[1]
                if all(g in mapping for g in first):
                    rank = (-abs(offset), len(mapping))
                    if best is None or rank > best[0]:
                        best = (rank, offset, mapping)
    return (best[1], best[2]) if best else None


def under(cell, groups, kinds):
    """The one group of the cell's kind that the cell printed mostly inside (its edge did not line up with the group's), else None."""
    token = cell.token
    width = max(token.box[2] - token.box[0], 1e-9)
    inside = [gid for gid, group in groups.items() if kinds[gid] == cell.kind
              and (min(token.box[2], group.extent[1]) - max(token.box[0], group.extent[0])) / width >= 0.5]
    return inside[0] if len(inside) == 1 else None


def read_page(number, view, lines, previous, made, serial):
    """One page: its anchors, late lines, tables and unplaced lines. Returns (tables still open, anchors, late line ids, unplaced lines)."""
    tolerance = view.size * ALIGN
    klass = {line.index: classify(line) for line in lines}
    consumed = {index for index, (name, _) in klass.items() if name in ("late", "anchor", "key", "sentence")}
    rows = [line for line in lines if klass[line.index][0] in ("row", "total")]
    attached = {index for line in rows for index in heads_above(lines, consumed, line.index)}
    anchors = [(klass[line.index][1], line) for line in lines if klass[line.index][0] == "anchor"]
    late_ids = [line_id for line in lines if klass[line.index][0] == "late" for line_id in view.lines([word.id for word in line.words])]

    def supported(members, alignment, centre):
        first = min(members)
        return 1 if any(index < first and any(abs(edge_of(union(view.box[word.id] for word in piece), alignment) - centre) <= tolerance
                                              for run in lines[index].runs for piece in [run, *run_pieces(view, run)]) for index in attached) else 0

    flat = [(line.index, cell) for line in rows for cell in klass[line.index][1][2]]
    groups, kinds, group_of_cell = {}, {}, {}
    for kind in ("amount", "usage", "integer"):
        positions = [position for position, (_, cell) in enumerate(flat) if cell.kind == kind]
        entries = [(flat[position][1].token, flat[position][0]) for position in positions]
        for alignment, local in choose_alignments(entries, tolerance, supported):
            gid = len(groups)
            groups[gid], kinds[gid] = group_of(entries, local, alignment), kind
            group_of_cell.update({positions[item]: gid for item in local})
    slots, position = {}, 0
    for line in rows:
        placed, stray, loose = {}, [], []
        for cell in klass[line.index][1][2]:
            gid = group_of_cell.get(position)
            position += 1
            if gid is None:
                gid = under(cell, groups, kinds)
            if gid is None or gid in placed:
                if cell.kind == "amount":
                    stray.append(cell.token)
                elif cell.kind == "usage":
                    loose.append(cell)
            else:
                placed[gid] = cell
        slots[line.index] = (placed, stray, loose)
    sets = column_sets({index: (placed, stray) for index, (placed, stray, _) in slots.items()})

    def repeats(line, builder):
        """Whether a heading line only repeats the open table's own: its words are the table's, and the row after it prints in the table's columns."""
        if not words_of([line]) <= builder.heading_words:
            return False
        after = next((item.index for item in rows if item.index > line.index), None)
        return after is None or not slots[after][0] or bool({sets[gid] for gid in slots[after][0]} & builder.comps)

    cur, mapping, offset = None, None, 0.0
    section, title, last = None, None, None  # `last` is (entry, line index): the row a wrapped label may join.
    pending, unplaced = [], []
    first = next((line.index for line in rows if slots[line.index][0]), None)
    if first is not None:
        for builder in reversed(previous):
            matched = offset_of(builder, groups, kinds, list(slots[first][0]), view.size)
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

    def line_id_of(line):
        return (view.lines([line.words[0].id]) or [""])[0]

    for line in lines:
        index = line.index
        name, data = klass[index]
        if name in ("late", "anchor") or name == "key" and not is_title_like(line):
            last = title = None
            continue
        if name == "sentence":
            unplaced.append(Unplaced(number, line_id_of(line), line_text(line)))
            last = None
            continue
        if index in attached:
            if cur is not None and repeats(line, cur):
                last = None  # The table's own heading, repeated.
                continue
            carried = title
            close()
            title = carried  # A section title directly above a heading belongs to the table below it.
            pending = [*pending, index] if pending and pending[-1] == index - 1 else [index]
            continue
        if name in ("row", "total"):
            placed, stray, loose = slots[index]
            label, label_ids, cells = data
            if not placed:
                if any(cell.kind == "amount" for cell in cells):
                    unplaced.append(Unplaced(number, line_id_of(line), line_text(line)))
                last = title = None
                continue
            if cur is not None and not {sets[gid] for gid in placed} & cur.comps:
                carried = title
                close()
                title = carried
                pending = []
            if cur is None:
                heads = [lines[item] for item in pending]
                serial[0] += 1
                cur = Builder(f"page-{number}-charges-{serial[0]}", view.size, heading_runs(view, heads, None), [line_text(item) for item in heads],
                              words_of(heads))
                made.append(cur)
                pending, mapping, offset, section = [], None, 0.0, None
            cur.comps |= {sets[gid] for gid in placed}
            if title is not None:
                section = title
                cur.titles.append(title)
                title = None
            keys = {}
            for gid, cell in placed.items():
                key = key_of(gid, mapping, number)
                keys[key] = cell
                cur.members.setdefault(key, []).append((cell.token, offset))
                cur.aligns.setdefault(key, groups[gid].align)
                cur.kinds.setdefault(key, kinds[gid])
            if number not in cur.pages:
                cur.pages.append(number)
            word_ids = [word.id for word in line.words]
            for cell in loose:  # A number with its unit that no column holds is label text.
                label = f"{label} {cell.text}"
            entry = {"page": number, "kind": name, "word_ids": word_ids, "label": label, "keys": keys, "stray": stray, "line": index,
                     "section": section.text if section is not None else None, "title": section}
            cur.entries.append(entry)
            cur.label_lefts.append(view.box[line.runs[0][0].id][0] - offset)
            last = (entry, index) if name == "row" else None
            if name == "total":
                section = None  # A section ends with its total.
            continue
        # A line of text: a wrapped label, a section title, or nothing.
        last_entry = last
        last = None
        if not text_only(line):
            title = None
            continue
        left = view.box[line.runs[0][0].id][0]
        if (last_entry is not None and index == last_entry[1] + 1 and cur is not None and len(line.runs) == 1
                and left - (median(cur.label_lefts) + offset) > tolerance):
            entry = last_entry[0]  # Indented under a row: the rest of its label (FR-102).
            entry["word_ids"] += [word.id for word in line.words]
            entry["label"] = f"{entry['label']} {line_text(line)}"
            last = (entry, index)
            title = None
            continue
        ahead = index + 1
        while ahead in attached and ahead < index + 3:
            ahead += 1  # A title may sit above its table's heading (one or two lines).
        target = lines[ahead] if ahead < len(lines) else None
        if (is_title_like(line) and target is not None and klass[target.index][0] in ("row", "total")
                and abs(left - view.box[target.runs[0][0].id][0]) <= tolerance):
            text = line_text(line)
            title = SectionTitle(number, line_id_of(line), [word.id for word in line.words], text, PHONE.search(text) is not None)
        else:
            title = None
    if cur is not None:
        cur.section = section
        cur.frame = {key: {align: median(edge_of(token.box, align) - shift for token, shift in members) for align in ALIGNMENTS}
                     for key, members in cur.members.items()}
    ordered = [Anchor(number, line_id_of(line), [word.id for word in line.words], found[0], found[1], 0) for found, line in anchors]
    return ([cur] if cur is not None else []), ordered, late_ids, unplaced


def read(result):
    """Read a saved reading (`PDFResult`) into its charge tables. Only `embedded_text` pages with a saved layout are read."""
    views, made, previous, anchors, late_ids, held, line_pages = {}, [], [], [], [], {}, {}
    for page in result.pages:
        if page.method != "embedded_text" or page.layout is None:
            previous = []
            continue
        number = page.number
        view = views[number] = PageView(page.layout)
        lines = [split_tails(without_phones(merge_usage(line))) for line in tokenize_page(view)]
        still, found, late_here, lost = read_page(number, view, lines, previous, made, [0])
        previous = still
        anchors += found
        late_ids += late_here
        held[number] = lost
        line_pages.update({line.id: number for line in page.layout.lines})
    for order, anchor in enumerate(anchors):
        anchor.order = order
    tables = [finish(builder, views) for builder in made]
    charge = [table for table in tables if any(column.kind == "amount" for column in table.columns)]
    other = [table for table in tables if table not in charge]
    unplaced, without = [], []
    for number, lost in held.items():
        if any(number in table.pages for table in charge):
            unplaced += lost
        else:
            without.append(number)
    return BillReading(charge, other, anchors, late_ids, unplaced, without, line_pages)
