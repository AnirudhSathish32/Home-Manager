"""Where each bill of a file starts (specs/pdf-table-engine-bills FR-128, FR-129 a - c; plan P8.1). Pure and lines only: it reads the transcribed lines' ids and
text, so it works on text PDFs, scanned PDFs and combined images, and asks no model. A single image has no page in its line ids and is one page, never split.

A key line starts with a key label directly followed by its value (`Due Date 07/20/2026`, `Account #: ****9012`): a due date, a statement date or an account
(its last four digits). Pages are walked in order and page 1 opens bill 1. A later page whose key line prints a value that differs from the value the open bill
printed for that key starts a new bill at the page's first line; otherwise it continues the open bill. The rule splits only between pages. Each part must hold an
amount-due line, else it joins the part before it (the first joins the next). On a text PDF the bill engine's anchors count too (`anchors`): a heading over the
amount column sets the amounts in layout lines of their own, so the line `Amount Due ....` holds no amount, but the engine pairs it with the amount printed
beside it (charge_tables.read). The labels are `charge_tables.KEY_LABELS` (SL-01 put them beside the anchor
words, because the charge reader needs `key_kind` too and this module imports `anchor_kind` from there).
"""

from dataclasses import dataclass, field
import re

from .charge_tables import KEY_LABELS, LATE_WORDS, anchor_kind
from .table_engine import read_tokens

PAGE = re.compile(r"page-(\d+)-")
KEYS = ("due_date", "statement_date", "account")  # The order in which a differing key is named (G5).
NAMES = {"due_date": "due date", "statement_date": "statement date", "account": "account"}
LABEL = re.compile(r"^(?:" + "|".join(re.escape(label) for label in sorted((label for labels in KEY_LABELS.values() for label in labels), key=len, reverse=True))
                   + r")(?![A-Za-z])", re.IGNORECASE)
LABEL_KIND = {label: kind for kind, labels in KEY_LABELS.items() for label in labels}
GAP = re.compile(r"^[\s.:#…]+")  # Dot leaders, a colon or a number sign between a label and its value.
ACCOUNT_GROUP = re.compile(r"^[\dxX*•-]+$")  # A following group of an account: digits, hyphens and the masking characters.
ACCOUNT_START = re.compile(r"^(?:[\dxX*•-]+|(?=[A-Za-z0-9*•-]*\d)[A-Za-z0-9*•-]+)$")  # The first group: that, or letters with digits (`AB1234-5678-9012`).

# The review reasons of FR-129 (a), (b) and (c), as they read with their printed values taken out; `reason_of` tells whether an issue is one of them.
REASONS = (re.compile(r"Page \d+ prints more than one .+, so it may hold more than one bill; check it and split it on the document's page\."),
           re.compile(r"Page \d+ prints (?:its own .+ but )?no amount due.*, so it was read with the bill (?:before|after) it; check how the file was split\."),
           re.compile(r"This bill prints new charges of .+ on different pages, so the file may hold more than one bill; check it and split it on the document's "
                      r"page\."))
OFFERED = (REASONS[0], REASONS[2])  # (a) and (c) leave the file as one bill that the user may still want to split (FR-131); (d) is the caller's.


@dataclass
class BillSplit:
    parts: list[tuple[int, int]]  # (first, last) index ranges of the lines, one per bill, in order; last is exclusive.
    reasons: dict[int, list[str]] = field(default_factory=dict)  # Part index to the FR-129 review reasons that part carries.


@dataclass
class Key:
    kind: str  # due_date, statement_date or account
    value: object  # What is compared: a date as (month, day, year), an account as its last four digits.
    printed: str  # The value as printed (an account: its last four digits).


def page_of(line):
    """The page a line is on; a line that names none (a single image) is on page 1."""
    found = PAGE.match(line.id or "")
    return int(found.group(1)) if found else 1


def text_of(line):
    """The line's text with its cell separators ("Due Date | 07/20/2026") taken out."""
    return " ".join(word for word in line.text.split() if word != "|")


def date_of(token):
    """A date token as something comparable: (month, day, year). A slash date with a first number over 12 is day first."""
    first, second, year, form = token.value
    year += 2000 if year < 100 else 0
    if form == "slash":
        return (second, first, year) if first > 12 else (first, second, year)
    return (second, first, year)  # iso and month_name hold (day, month, year).


def key_of(line):
    """The key a line prints (FR-128), else None: its text starts with a key label directly followed by its value. A due or statement date is the first date
    (the value must start with it); an account is the last four digits of its whole printed value: its first word (digits, hyphens, masking characters, or
    letters mixed with digits, `AB1234-5678-9012`) and the groups of digits, hyphens and masking characters after it (`1234 5678 9012`, `****9012`), up to
    the first word that is none of those (a following field). The value must hold at least four digits."""
    text = text_of(line)
    found = LABEL.match(text)
    if not found:
        return None
    kind = LABEL_KIND[found.group(0).lower()]
    rest = GAP.sub("", text[found.end():])
    if not rest:
        return None
    words = rest.split()
    if kind == "account":
        value = []
        for word in words:
            if not (ACCOUNT_GROUP if value else ACCOUNT_START).match(word):
                break
            value.append(word)
        digits = re.sub(r"\D", "", "".join(value))
        return Key(kind, digits[-4:], digits[-4:]) if len(digits) >= 4 else None
    first = read_tokens(words)[0]
    return Key(kind, date_of(first), first.text) if first.kind == "date" else None


def amount_tokens(line):
    return [token for token in read_tokens(text_of(line).split()) if token.kind == "amount" and token.value[0] is not None]


def anchor_of(line):
    """(kind, value) when the line is a summary anchor (FR-103): its label, the text before its last amount, fully matches an anchor phrase, and it is no
    late-payment line; else None."""
    text = text_of(line)
    amounts = amount_tokens(line)
    if not amounts or LATE_WORDS.search(text):
        return None
    words = text.split()
    last = amounts[-1]
    kind = anchor_kind(" ".join(words[:int(last.word_ids[0].removeprefix("word-"))]))
    return (kind, last.value[0]) if kind else None


def plain(value):
    return format(value, "f")


def reason_of(text):
    """Whether an issue is one of FR-129's a - c (a split you confirm drops them)."""
    return any(pattern.fullmatch(text) for pattern in REASONS)


def offers_split(issues):
    """Whether a bill's issues hold FR-129 (a) or (c): the bill is one that may hold more, so the document page offers Split here (FR-131)."""
    return any(pattern.fullmatch(issue) for issue in issues for pattern in OFFERED)


def pages_of(lines):
    """[(page, first index, last index + 1)] runs of lines on one page, in order."""
    runs = []
    for index, line in enumerate(lines):
        page = page_of(line)
        if runs and runs[-1][0] == page:
            runs[-1][2] = index + 1
        else:
            runs.append([page, index, index + 1])
    return [tuple(run) for run in runs]


def many(kind, printed):
    """FR-129 (a)'s wording of a key printed with two values: `more than one due date (A, B)`, an account as `(ending A, ending B)` (G5)."""
    shown = ", ".join(f"ending {value}" if kind == "account" else value for value in printed[:2])
    return f"more than one {NAMES[kind]} ({shown})"


def own(kind, printed):
    return f"its own {NAMES[kind]} ({'ending ' + printed if kind == 'account' else printed})"


def bill_parts(lines, anchors=None):
    """The bills of a file as a BillSplit (FR-128, FR-129 a - c); one part for a file with one bill. `anchors` is {line id: [(kind, value), ...]}, the bill
    engine's summary anchors by the evidence line holding their label (bill_tables.split_anchors); a line is an anchor when its own text is one, or the
    engine found one there."""
    anchors = anchors or {}

    def anchors_of(line):
        own = anchor_of(line)
        return [own] if own else anchors.get(line.id, [])
    if not lines:
        return BillSplit([(0, 0)])
    pages = pages_of(lines)
    keys = []  # Per page: {kind: [Key, ...]} in printed order.
    for _, first, last in pages:
        found = {}
        for line in lines[first:last]:
            key = key_of(line)
            if key:
                found.setdefault(key.kind, []).append(key)
        keys.append(found)
    # Walk the pages: a page whose first value of a key differs from the open bill's starts a new bill at its first line (the first such key in KEYS' order).
    starts, open_values, trigger, twice = [0], {}, {}, {}
    for number, ((page, first, _), found) in enumerate(zip(pages, keys)):
        for kind in KEYS:  # Two values for one key on one page: never split there, and one reason for the page (a, G5).
            printed = list(dict.fromkeys(key.printed for key in found.get(kind, [])))
            if len({key.value for key in found.get(kind, [])}) > 1:
                twice[page] = f"Page {page} prints {many(kind, printed)}, so it may hold more than one bill; check it and split it on the document's page."
                break
        differing = next((kind for kind in KEYS if kind in found and kind in open_values and found[kind][0].value != open_values[kind].value), None)
        if number and differing:
            starts.append(first)
            trigger[first] = (differing, found[differing][0].printed)
            open_values = {}
        for kind, listed in found.items():
            open_values.setdefault(kind, listed[0])
    bounds = [*starts, len(lines)]
    parts = list(zip(bounds, bounds[1:]))

    def has_due(first, last):
        return any(kind == "amount_due" for line in lines[first:last] for kind, _ in anchors_of(line))

    # (b) Each bill prints an amount due of its own: a part without one joins the part before it; the first, without one, joins the next.
    groups = []  # [first, last, [(start of a part joined in, the direction)]]
    for first, last in parts:
        if groups and not has_due(first, last):
            groups[-1][1] = last
            groups[-1][2].append((first, "before"))
        else:
            groups.append([first, last, []])
    if len(groups) > 1 and not has_due(groups[0][0], groups[0][1]):
        zero = groups.pop(0)
        groups[0] = [zero[0], groups[0][1], [(zero[0], "after"), *zero[2], *groups[0][2]]]
    keyed_at = {first: keyed for (_, first, _), keyed in zip(pages, keys)}  # A part always starts at the first line of a page.

    result, reasons = [], {}
    for number, (first, last, joined) in enumerate(groups):
        found = []
        found += [twice[page] for page, start, _ in pages if first <= start < last and page in twice]
        for start, direction in joined:
            if start in trigger:
                kind, printed = trigger[start]
            else:  # The part has no differing key (the first part, or an unkeyed page): name the first key it prints, if any.
                kind = next((kind for kind in KEYS if kind in keyed_at[start]), None)
                printed = keyed_at[start][kind][0].printed if kind else None
            who = f"prints {own(kind, printed)} but no amount due" if kind else "prints no amount due"
            found.append(f"Page {page_of(lines[start])} {who}, so it was read with the bill {direction} it; check how the file was split.")
        # (c) New charges printed with different values on different pages of one bill, with no key line telling those pages apart.
        charges = {}
        for position, (_, start, stop) in enumerate(pages):
            if not first <= start < last:
                continue
            values = [value for line in lines[start:stop] for kind, value in anchors_of(line) if kind == "new_charges"]
            if values:
                charges[position] = values
        different = None
        ordered = sorted(charges)
        for index, early in enumerate(ordered):
            for late in ordered[index + 1:]:
                alike = all(keys[early][kind][0].value == keys[late][kind][0].value for kind in KEYS if kind in keys[early] and kind in keys[late])
                other = next((value for value in charges[late] if value != charges[early][0]), None)
                if alike and other is not None and different is None:
                    different = (charges[early][0], other)
        if different:
            found.append(f"This bill prints new charges of {plain(different[0])} and {plain(different[1])} on different pages, so the file may hold more than one bill; "
                         "check it and split it on the document's page.")
        if found:
            reasons[number] = found
        result.append((first, last))
    return BillSplit(result, reasons)
