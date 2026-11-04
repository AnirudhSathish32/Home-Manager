"""Where each pay stub of a file starts (specs/pdf-table-engine-paystubs FR-80; plan P8). Pure and lines only: it reads the transcribed
lines' ids and text, so it works on text PDFs, scans and photos, and asks no model.

A stub starts at a line holding a pay date label (pay date, check date, payment date, pay period, period ending) and a date. A start opens a
new stub only after the open stub has printed its net pay line: a stub prints both a pay date and a pay period, and a later page repeats its
heading, so those are continuations. A part left without a net pay line joins the part before it (the first joins the next). Then each
stub's first line moves up over its employer heading lines, but only on the same page and never past the previous stub's last net pay line."""

import re

from .pay_tables import STUB_START
from .table_engine import read_tokens

NET_PAY = re.compile(r"net pay(?:ment)?(?:\s*\([A-Z](?:\s*-\s*[A-Z])?\))?\s*:?", re.IGNORECASE)  # extraction.TOTAL_ROWS["net_pay"], and a colon.
PAGE = re.compile(r"page-(\d+)-")
HEADING_LINES = 4  # How far above its pay date line a stub's employer heading can reach.


def tokens_of(line):
    """The line's tokens; the cell separator of a projected table row ("Net Pay | 1,800.00") is not a word."""
    return read_tokens([word for word in line.text.split() if word != "|"])


def starts_stub(line):
    return bool(STUB_START.search(line.text)) and any(token.kind == "date" for token in tokens_of(line))


def prints_net_pay(line):
    """A net pay label followed by an amount."""
    tokens = tokens_of(line)
    amount = next((index for index, token in enumerate(tokens) if token.kind == "amount"), None)
    return amount is not None and bool(NET_PAY.fullmatch(" ".join(token.text for token in tokens[:amount]).strip()))


def page_of(line):
    found = PAGE.match(line.id or "")
    return int(found.group(1)) if found else None


def has_amount(line):
    return any(token.kind == "amount" for token in tokens_of(line))


def stub_parts(lines):
    """[(first, last)] index ranges of the lines, one per pay stub, in order; [(0, len(lines))] for one stub."""
    everything = [(0, len(lines))]
    nets = [index for index, line in enumerate(lines) if prints_net_pay(line)]
    starts, printed = [], False
    for index, line in enumerate(lines):
        if starts_stub(line) and (not starts or printed):
            starts.append(index)
            printed = False
        if index in nets and starts:
            printed = True
    if len(starts) < 2:
        return everything
    bounds = [0, *starts[1:], len(lines)]
    parts = list(zip(bounds, bounds[1:]))
    joined = []  # A part with no net pay line of its own joins the part before it; the first joins the next.
    for first, last in parts:
        if joined and not any(first <= net < last for net in nets):
            joined[-1] = (joined[-1][0], last)
        else:
            joined.append((first, last))
    if len(joined) > 1 and not any(joined[0][0] <= net < joined[0][1] for net in nets):
        joined[1] = (joined[0][0], joined[1][1])
        del joined[0]
    if len(joined) < 2:
        return everything
    moved = [joined[0][0]]
    for _, (first, _) in zip(joined, joined[1:]):
        floor = max((net for net in nets if net < first), default=-1) + 1  # After the previous stub's last net pay line.
        top = first
        while (top > floor and first - top < HEADING_LINES and page_of(lines[top - 1]) == page_of(lines[first])
               and not has_amount(lines[top - 1])):
            top -= 1
        moved.append(top)
    ends = [*moved[1:], len(lines)]
    return list(zip(moved, ends))
