"""Grading of one reading against a drawn receipt's printed rows (specs/receipt-layout-eval FR-13 – FR-17; plan P8). Pure: no model, file or clock.

The case's rows are aligned, in order, to the reading's lines, tolerant of misread characters, so a misread digit keeps a row whole and a price
on a line of its own is a split. Then rows, money, indent, cells, alignment, handwriting and (for `spans`) box diagnostics are counted. Counts only;
the task turns them into a pass and a score, and the report adds the denominators.
"""

from collections import Counter
from difflib import SequenceMatcher
from math import ceil, floor
import re
from statistics import median

from home_manager.documents.vision_layout import usable
from home_manager.models.vision import READING_FORMATS

# The money rule, one definition for the generator (its answers) and the grader: a number with exactly two decimals, an optional `$`,
# thousands commas, a leading or trailing minus or parentheses, not followed by `%` or a digit.
MONEY = re.compile(r"(?<![\d.,])(\()?(-)?\$?(-)?(\d{1,3}(?:,\d{3})+|\d+)\.(\d{2})(?![\d%])(-)?(\))?")

CELL_FORMATS = ("layout-text", "spans")  # The formats that report where a row's parts split.
POSITION_FORMATS = ("spans",)            # The formats that report alignment, handwriting and boxes.
PAIRABLE = 0.5       # Rows and lines further apart than this share of their length are never paired.
HELD = 0.3           # A cell is held by a line when it sits in it within this share of its length.
BAND = 15            # Lines either side of the proportional diagonal the alignment looks at.
SHORT_PIECE = 2      # A split or merged piece this short must be there exactly; longer ones may differ by at least one edit.
EXTRA_PIECE = 0.05   # What a split or a merge costs for each piece beyond the first.
NEAR_LINES = 3       # A missing cell is looked for on unpaired lines this close to its row's line.
ANCHOR_RUN = 2      # Equal rows and lines in runs this long are paired before the alignment looks at the rest.
MOST_PIECES = 4      # A row is split over, or merged into, at least this many lines at most (more when a row has more cells; dining's tip rows have four).
INDENT_FORMATS = ("v7-lines", "layout-text", "spans")  # The formats that report an indent for every line; v6-text reports none.


def parse_amounts(text):
    """The money amounts of a text in minor units, signed."""
    found = []
    for opened, lead, lead_after_dollar, whole, cents, trail, closed in MONEY.findall(text):
        value = int(whole.replace(",", "")) * 100 + int(cents)
        found.append(-value if (lead or lead_after_dollar or trail or (opened and closed)) else value)
    return found


def normalize(text):
    """Tabs, " | " and runs of spaces become one space; case folded; stripped."""
    return " ".join(re.sub(r"(?:^|\s)\|(?:\s|$)", " ", str(text or "")).split()).casefold()


def split_cells(text):
    """A reported cell's normalized parts: " | " and tabs inside it are boundaries too."""
    return [part for part in (normalize(piece) for piece in re.split(r"\t|\s\|\s", str(text or ""))) if part]


class Aligner:
    """Edit distances with a count of how many were worked out, so the cost can be tested without a clock."""

    def __init__(self):
        self.evaluations = 0
        self.cells = 0  # Table cells filled by the search for a piece in order, the part of the cost that grows with the text.
        self.cache = {}

    def lev(self, a, b, limit=None):
        """The edit distance of a and b, or limit + 1 when it is more than limit."""
        if a == b:
            return 0
        limit = max(len(a), len(b)) if limit is None else limit
        key = (a, b, limit)
        if key in self.cache:
            return self.cache[key]
        self.evaluations += 1
        if abs(len(a) - len(b)) > limit:
            value = limit + 1
        else:
            common = sum((Counter(a) & Counter(b)).values())
            if max(len(a), len(b)) - common > limit:  # Too many characters that no edit could pair up.
                value = limit + 1
            else:
                value = self._distance(a, b, limit)
        self.cache[key] = value
        return value

    @staticmethod
    def _distance(a, b, limit):
        if len(a) < len(b):
            a, b = b, a
        previous = list(range(len(b) + 1))
        for i, x in enumerate(a, 1):
            current = [i]
            for j, y in enumerate(b, 1):
                current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
            if min(current) > limit:
                return limit + 1
            previous = current
        return previous[-1]

    def near(self, a, b):
        """The share of the longer text that differs, when that is at most PAIRABLE; else 1.0."""
        size = max(len(a), len(b), 1)
        distance = self.lev(a, b, floor(PAIRABLE * size))
        return distance / size if distance <= PAIRABLE * size else 1.0

    def holds(self, cell, line):
        """Whether the line holds the cell: exactly, or as its closest stretch within HELD of the cell's length."""
        if not cell or cell in line:
            return True
        limit = floor(HELD * len(cell))
        if not limit:
            return False
        key = ("holds", cell, line)
        if key not in self.cache:
            self.evaluations += 1
            previous = [0] * (len(line) + 1)
            for i, x in enumerate(cell, 1):
                current = [i]
                for j, y in enumerate(line, 1):
                    current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
                previous = current
            self.cache[key] = min(previous) <= limit
        return self.cache[key]

    @staticmethod
    def budget(part):
        """The edits a split or merged piece may differ by: none for one or two characters, at least one from three on."""
        return 0 if len(part) <= SHORT_PIECE else max(1, floor(HELD * len(part)))

    def earliest_end(self, part, text, start):
        """The smallest end of any stretch of text that begins at or after start and is within the part's budget, or None. One semi-global
        edit distance: the stretch may begin at any column from start (a free start), and the last row says which columns it can end at."""
        key = ("earliest", part, text, start)
        if key not in self.cache:
            self.evaluations += 1
            allowed = self.budget(part)
            self.cells += len(part) * (len(text) - start)
            previous = [0] * (len(text) - start + 1)  # Column c is the text from start to start + c; a stretch may begin at any of them.
            for i, x in enumerate(part, 1):
                current = [i]
                for c in range(1, len(previous)):
                    current.append(min(previous[c] + 1, current[c - 1] + 1, previous[c - 1] + (x != text[start + c - 1])))
                previous = current
                if min(previous) > allowed:
                    previous = None
                    break
            self.cache[key] = None if previous is None else next((start + c for c, distance in enumerate(previous) if distance <= allowed and c), None)
        return self.cache[key]

    def in_order(self, parts, text):
        """Whether the parts can be found in the text one after the other, each after the end of the one before: a character is evidence once.
        A search, not a first match: any stretch within a part's budget is a candidate, and as only the end of the one before matters to the
        next, the earliest end of each leaves the most room for the rest. So a repeated word, or a misread piece that also reads exactly
        further on, cannot make a row's parts look out of order."""
        end = 0
        for part in parts:
            if not part:
                continue
            end = self.earliest_end(part, text, end)
            if end is None:
                return False
        return True

    def supported(self, whole, parts, tie=False):
        """Whether pieces and whole explain each other better than pairing the whole with any one piece alone, as the grader's own distance
        would charge that: the other pieces left missing (or extra) cost their length. A merge or a split must rest on characters the
        1:1 pairing cannot explain, so a row deleted before one that repeats its words is missing, not merged. Spaces do not count, so a
        lost separator is no evidence.
        A tie is ambiguous, and an ambiguous reading must never pass: it is resolved toward the reading that fails the case. A case needs no
        split, merged or missing row, but not "no extra line", so for a split (tie=True) the tie is a split, and the alternative, one whole
        row beside an extra line, could pass; for a merge a tie is a missing row (the 1:1 pairing), which fails as a merge would."""
        whole = whole.replace(" ", "")
        parts = [part.replace(" ", "") for part in parts]
        together = self.lev(whole, "".join(parts))
        alone = min(self.lev(whole, part) + sum(map(len, parts)) - len(part) for part in parts)
        return together <= alone if tie else together < alone

    def align(self, rows, lines, most=MOST_PIECES):
        """Groups (row indexes, line indexes) in order: 1:1, 1:k (split) or k:1 (merged), k up to most. Anything unpaired is missing or extra.
        A split or a merge needs ordered evidence: the row holds its lines one after the other without sharing a character (or the line
        its rows), so a deleted row is missing rather than merged into a neighbour, and a split cannot take an unrelated line."""
        matcher = SequenceMatcher(None, rows, lines, autojunk=False)
        # Only runs of at least two equal rows are anchors: a lone equal row may be the left half of a split row that repeats an item's name.
        anchors = [(a + k, b + k) for a, b, size in matcher.get_matching_blocks() if size >= ANCHOR_RUN for k in range(size)]
        groups, row_start, line_start = [], 0, 0
        for i, j in anchors:
            groups += self.gap(rows, lines, row_start, i, line_start, j, most)
            groups.append(((i,), (j,)))
            row_start, line_start = i + 1, j + 1
        return groups + self.gap(rows, lines, row_start, len(rows), line_start, len(lines), most)

    def gap(self, rows, lines, row0, row1, line0, line1, most=MOST_PIECES):
        n, m = row1 - row0, line1 - line0
        if not n or not m:
            return []
        slope = m / n

        def window(i):
            return max(0, ceil(i * slope - BAND)), min(m, floor(i * slope + BAND))

        cost, back = {(0, 0): 0.0}, {}
        for i in range(n + 1):
            for j in range(window(i)[0], window(i)[1] + 1):
                if (i, j) == (0, 0):
                    continue
                best = (float("inf"), None)
                if (i - 1, j - 1) in cost:
                    step = self.near(rows[row0 + i - 1], lines[line0 + j - 1])
                    if step <= PAIRABLE:
                        best = min(best, (cost[(i - 1, j - 1)] + step, (i - 1, j - 1)), key=lambda option: option[0])
                for k in range(2, most + 1):
                    if j - k >= 0 and (i - 1, j - k) in cost:
                        row, pieces = rows[row0 + i - 1], lines[line0 + j - k:line0 + j]
                        step = self.near(row, " ".join(pieces))
                        if step <= HELD and cost[(i - 1, j - k)] + step + EXTRA_PIECE * (k - 1) < best[0] and self.in_order(pieces, row) and self.supported(row, pieces, tie=True):
                            best = (cost[(i - 1, j - k)] + step + EXTRA_PIECE * (k - 1), (i - 1, j - k))
                    if i - k >= 0 and (i - k, j - 1) in cost:
                        parts, line = rows[row0 + i - k:row0 + i], lines[line0 + j - 1]
                        step = self.near(" ".join(parts), line)
                        if step <= HELD and cost[(i - k, j - 1)] + step + EXTRA_PIECE * (k - 1) < best[0] and self.in_order(parts, line) and self.supported(line, parts):
                            best = (cost[(i - k, j - 1)] + step + EXTRA_PIECE * (k - 1), (i - k, j - 1))
                for previous in ((i - 1, j), (i, j - 1)):  # Skip a row, or skip a line: 1.0 each.
                    if previous in cost and cost[previous] + 1.0 < best[0]:
                        best = (cost[previous] + 1.0, previous)
                if best[1] is not None:
                    cost[(i, j)], back[(i, j)] = best
        groups, here = [], (n, m)
        while here in back:
            before = back[here]
            if before[0] < here[0] and before[1] < here[1]:
                groups.append((tuple(range(row0 + before[0], row0 + here[0])), tuple(range(line0 + before[1], line0 + here[1]))))
            here = before
        return groups[::-1]


def amounts_of(lines):
    return Counter(amount for text in lines for amount in parse_amounts(text))


def intersection_over_union(a, b):
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    both = width * height
    return both / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - both)


def box_overlap(pairs):
    """The median intersection over union of (reported box, drawn box) pairs after one scale per axis, each fitted by least squares
    through the origin. None without pairs. Reported positions are the model's own report, never a measurement."""
    if not pairs:
        return None
    scales = []
    for axis in ((0, 2), (1, 3)):
        top = sum(reported[k] * drawn[k] for reported, drawn in pairs for k in axis)
        bottom = sum(reported[k] ** 2 for reported, _ in pairs for k in axis)
        scales.append(top / bottom if bottom else 1.0)
    scale = (scales[0], scales[1], scales[0], scales[1])
    return round(median(intersection_over_union([value * factor for value, factor in zip(reported, scale)], drawn)
                        for reported, drawn in pairs), 4)


def grade_reading(expected, output):
    """The counts for one reading. expected is a case's answers ({"rows": [{"cells", "indent", "align", "amounts"}]}); output holds the
    reading's "format", "lines" ([[text, indent]]), "rows" (per line: {"cells": [{"text", "box", "handwritten"}], "align"}) and "spans"."""
    output = output or {}
    format_name = output.get("format")
    rows = expected["rows"]
    row_text = [normalize(" ".join(cell["text"] for cell in row["cells"])) for row in rows]
    row_cells = [[normalize(cell["text"]) for cell in row["cells"]] for row in rows]
    reading = [(position, str(entry[0] or ""), entry[1] if len(entry) > 1 else None) for position, entry in enumerate(output.get("lines") or [])]
    reading = [(position, text, indent) for position, text, indent in reading if normalize(text)]
    line_text = [normalize(text) for _, text, _ in reading]
    aligner = Aligner()
    groups = aligner.align(row_text, line_text, max([MOST_PIECES, *(len(cells) for cells in row_cells)]))
    paired_rows = {i for group in groups for i in group[0]}
    paired_lines = {j for group in groups for j in group[1]}
    # A price printed after a side line: the row's line lacks a cell that an unpaired line near it holds, so the row is split over both.
    for index, (group_rows, group_lines) in enumerate(groups):
        if len(group_rows) == 1 and len(group_lines) == 1 and len(row_cells[group_rows[0]]) > 1:
            line = group_lines[0]
            lacking = [cell for cell in row_cells[group_rows[0]] if not aligner.holds(cell, line_text[line])]
            found = []
            for cell in lacking:
                for other in range(max(0, line - NEAR_LINES), min(len(line_text), line + NEAR_LINES + 1)):
                    if other not in paired_lines and other not in found and aligner.holds(cell, line_text[other]):
                        found.append(other)
                        break
            if found:
                paired_lines.update(found)
                groups[index] = (group_rows, tuple(sorted((line, *found))))
    missing_rows = [i for i in range(len(rows)) if i not in paired_rows]
    extra_lines = [j for j in range(len(reading)) if j not in paired_lines]
    # Out of order: a row the in-order alignment could not place, but that sits on an unpaired line.
    out_of_order = 0
    candidates = sorted((aligner.near(row_text[i], line_text[j]), i, j) for i in missing_rows for j in extra_lines)
    taken_rows, taken_lines = set(), set()
    for distance, i, j in candidates:
        if distance <= HELD and i not in taken_rows and j not in taken_lines:
            taken_rows.add(i), taken_lines.add(j)
            groups.append(((i,), (j,)))
    out_of_order = len(taken_rows)
    missing_rows = [i for i in missing_rows if i not in taken_rows]
    extra_lines = [j for j in extra_lines if j not in taken_lines]

    lines_of = {}   # row -> its lines
    sole = set()    # rows alone on a line of their own
    merged = split = 0
    for group_rows, group_lines in groups:
        for i in group_rows:
            lines_of[i] = list(group_lines)
        if len(group_rows) == 1 and len(group_lines) == 1:
            sole.add(group_rows[0])
        elif len(group_rows) == 1:
            split += 1
        else:
            merged += len(group_rows) - 1

    # Characters: how far the readings are from the printed text, by the aligned rows.
    distance = sum(aligner.lev(" ".join(row_text[i] for i in group_rows), " ".join(line_text[j] for j in group_lines))
                   for group_rows, group_lines in groups)
    distance += sum(len(row_text[i]) for i in missing_rows) + sum(len(line_text[j]) for j in extra_lines)
    characters = sum(len(text) for text in row_text)

    # Money (FR-14): read anywhere, read on the row's own line, wrong digits apart from missing.
    remaining = [amounts_of([text]) for _, text, _ in reading]
    wanted = [Counter(row.get("amounts") or parse_amounts(" ".join(cell["text"] for cell in row["cells"]))) for row in rows]
    own = {}
    for i in range(len(rows)):
        found = Counter()
        for amount, count in wanted[i].items():
            for line in lines_of.get(i, []):
                take = min(count, remaining[line][amount])
                if take:
                    remaining[line][amount] -= take
                    count -= take
                    found[amount] += take
        own[i] = found
    placed = {line for lines in lines_of.values() for line in lines}
    elsewhere = wrong = absent = 0
    unmatched = []
    for i in range(len(rows)):  # Every exact match anywhere is reserved before any wrong digit is allotted, so a spare is never one that another row reads exactly.
        for amount, count in (wanted[i] - own[i]).items():
            for _ in range(count):
                holders = [line for line, counter in enumerate(remaining) if counter[amount] > 0]
                if holders:
                    remaining[min(holders, key=lambda line: (line in placed, line))][amount] -= 1  # A line that no row owns first.
                    elsewhere += 1
                else:
                    unmatched.append(i)
    for i in unmatched:
        spare = next(((line, other) for line in lines_of.get(i, []) for other, left in remaining[line].items() if left > 0), None)
        if spare:
            remaining[spare[0]][spare[1]] -= 1
            wrong += 1
        else:
            absent += 1
    amounts = sum(sum(counter.values()) for counter in wanted)
    on_row = sum(sum(own[i].values()) for i in sole)

    # Indent (FR-15), cells and alignment and handwriting (FR-16), for rows alone on their line.
    # The format decides whether an indent is reported: one that should report it and has lost it is "unknown", never "not reported".
    indent_reported = format_name in INDENT_FORMATS if format_name in READING_FORMATS else any(indent is not None for _, _, indent in reading)
    cells_reported = format_name in CELL_FORMATS and len(output.get("rows") or []) == len(output.get("lines") or [])
    position_reported = cells_reported and format_name in POSITION_FORMATS
    counts = {"indented_rows": 0, "indented_right": 0, "indented_wrong": 0, "indented_unknown": 0,
              "edge_rows": 0, "edge_right": 0, "edge_wrong": 0, "edge_unknown": 0,
              "cell_rows": 0, "cell_rows_match": 0, "align_rows": 0, "align_right": 0,
              "handwritten_expected": 0, "handwritten_reported": 0, "handwritten_correct": 0}
    pairs = []
    for i in sorted(sole):
        position, _, indent = reading[lines_of[i][0]]
        kind = "indented" if rows[i]["indent"] else "edge"
        if indent_reported:
            counts[f"{kind}_rows"] += 1
            counts[f"{kind}_unknown" if indent is None else f"{kind}_right" if indent == rows[i]["indent"] else f"{kind}_wrong"] += 1
        if not cells_reported:
            continue
        reported = output["rows"][position]
        got = [part for cell in reported.get("cells") or [] for part in split_cells(cell.get("text"))]
        counts["cell_rows"] += 1
        same = len(got) == len(row_cells[i]) and all(a == b or aligner.near(a, b) <= HELD for a, b in zip(got, row_cells[i]))
        counts["cell_rows_match"] += same
        if not position_reported:
            continue
        counts["align_rows"] += 1
        counts["align_right"] += reported.get("align") == rows[i]["align"]
        if same and len(reported.get("cells") or []) == len(rows[i]["cells"]):
            for want, have in zip(rows[i]["cells"], reported["cells"]):
                counts["handwritten_expected"] += bool(want["handwritten"])
                counts["handwritten_reported"] += bool(have.get("handwritten"))
                counts["handwritten_correct"] += bool(want["handwritten"]) and bool(have.get("handwritten"))
                if want.get("box") and usable(have.get("box")):
                    pairs.append((list(have["box"]), list(want["box"])))
    pieces = output.get("spans") or []
    return {"rows": len(rows), "lines": len(reading), "whole": len(sole), "split": split, "merged": merged,
            "missing": len(missing_rows), "extra": len(extra_lines), "out_of_order": out_of_order,
            "amounts": amounts, "amounts_read": sum(sum(counter.values()) for counter in own.values()) + elsewhere,
            "amounts_on_row": on_row, "amounts_wrong": wrong, "amounts_missing": absent,
            "indent_reported": indent_reported, **counts, "cells_reported": cells_reported, "position_reported": position_reported,
            "distance": distance, "characters": characters, "cer": round(distance / max(1, characters), 4),
            "usable_share": round(sum(usable(piece.get("box")) for piece in pieces) / len(pieces), 4) if position_reported and pieces else None,
            "overlap": box_overlap(pairs) if position_reported else None, "evaluations": aligner.evaluations}
