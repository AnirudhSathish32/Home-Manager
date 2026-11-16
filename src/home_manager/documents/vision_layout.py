"""Rows from positioned text pieces (specs/receipt-layout-eval, the `spans` reading format).

A vision model that answers with pieces of text and their boxes gives no lines of its own. build_rows turns the pieces into
rows (cells left to right, an indent of 0, 1 or 2, an alignment) from the boxes alone: no wording of any piece, and no
assumption that the image is level, upright, in pixels or in any particular frame. Pure; no model, file or clock.
"""

from dataclasses import dataclass, field
from math import isfinite

# Thresholds, in text heights (rows) or character widths (columns). Tune only on synthetic cases and the corpus dev split.
USABLE_SHARE = 0.5          # fewer usable boxes than this share of the pieces: the model's order is kept
SLOPE_LIMIT, SLOPE_STEP = 0.15, 0.0025
SLOPE_ROW = 0.25            # tighter row tolerance while searching for the slope
LEVEL_SLOPE, SLANT_MIN = 0.005, 0.01
MIN_TO_MEASURE = 6          # fewer usable pieces than this search only the small slopes below
FEW_TO_MEASURE, FEW_SLOPE_LIMIT = 4, 0.06  # a few pieces (a two-row receipt) may be tilted up to about 3.4 degrees; fewer are read level
SAME_ROW = 0.5              # a piece joins the open row within this many text heights of the row's centre
HANDWRITING_ROW = 1.0       # a handwritten piece joins the nearest printed row within this many text heights
SAME_CELL = 1.5             # neighbours closer than this many character widths are one cell
MARGIN_BAND = 3.0           # text heights per band when measuring the margin's slant
MARGIN_OUTLIER = 4.0        # a band's left edge this many character widths right of the typical one is not the margin
CENTER_TOLERANCE, EDGE_CLEARANCE = 2.0, 3.0
RIGHT_TOLERANCE = 1.5
INDENT_GROUP_GAP = 1.0      # indent values closer than this are one indent level; also the largest "not indented" offset

NO_POSITION = "Most text pieces had no usable position; rows follow the model's order."
UNPLACED = "{count} text pieces had no usable position; each was kept after the piece before it."


@dataclass
class Cell:
    text: str
    box: tuple | None
    handwritten: bool = False


@dataclass(eq=False)
class Row:
    cells: list = field(default_factory=list)
    indent: int | None = None
    align: str | None = None

    @property
    def text(self):
        return " ".join(cell.text for cell in self.cells)


def usable(box):
    """Four finite numbers (not booleans) with right > left and bottom > top."""
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return False
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) for value in box):
        return False
    return box[2] > box[0] and box[3] > box[1]


def percentile(values, share):
    """Linear interpolation between order statistics (share 0 – 1)."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * share
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def group(centres, tolerance=SAME_ROW):
    """Group indexes into rows by centre: sorted by centre, a piece joins the open row when within tolerance of its mean."""
    rows = []  # [indexes, sum of centres]
    for index in sorted(centres, key=centres.get):
        if rows and abs(centres[index] - rows[-1][1] / len(rows[-1][0])) <= tolerance:
            rows[-1][0].append(index)
            rows[-1][1] += centres[index]
        else:
            rows.append([[index], centres[index]])
    return [members for members, _ in rows]


def row_slope(printed, slant=None, limit=SLOPE_LIMIT):
    """The slope (Y units per X unit) that groups the pieces into the fewest rows. printed maps an index to its centre (X, Y).

    slant is the margin's slope (None when unknown). A page turned in its own plane slants its rows and its margin the same
    way; a page seen at an angle keeps level rows with a slanted margin. So a slope is allowed when it is nearly level, or
    when it has the margin's sign (a margin that is itself level allows only the nearly level ones). That rules out the slope
    that pairs each row's left end with the next row's right end on a page that is level, or tilted the other way.

    The search groups more tightly than the rows do (SLOPE_ROW), so a slope cannot make fewer rows by crowding two real rows
    together. Slopes with the fewest rows tie; the tightest rows (mean distance from the row's centre line) come first, then
    the smallest |slope|."""
    steps = round(limit / SLOPE_STEP)
    results = []
    for step in range(-steps, steps + 1):
        slope = step * SLOPE_STEP
        if slant is not None and abs(slope) > LEVEL_SLOPE and not (abs(slant) >= SLANT_MIN and slope * slant > 0):
            continue
        centres = {index: cy + slope * cx for index, (cx, cy) in printed.items()}
        rows = group(centres, SLOPE_ROW)
        spread = sum(abs(centres[index] - sum(centres[i] for i in members) / len(members)) for members in rows for index in members)
        results.append((len(rows), round(spread / len(centres), 6), abs(slope), slope))
    return min(results)[3]


def margin_slope(boxes):
    """Theil–Sen slope of the left edge's X against Y, over the smallest left edge in each band (None with fewer than 3 bands)."""
    bands = {}
    for left, centre in boxes:
        band = int(centre // MARGIN_BAND)
        if band not in bands or left < bands[band][0]:
            bands[band] = (left, centre)
    points = sorted(bands.values(), key=lambda point: point[1])
    # Bands holding only centred or indented rows start far right of the margin: leave them out.
    middle = percentile([left for left, _ in points], 0.5)
    points = [point for point in points if point[0] - middle <= MARGIN_OUTLIER]
    if len(points) < 3:
        return None
    slopes = [(b[0] - a[0]) / (b[1] - a[1]) for i, a in enumerate(points) for b in points[i + 1:] if b[1] > a[1]]
    return percentile(slopes, 0.5) if slopes else None


def build_rows(pieces):
    """(rows, notes) for pieces given as (text, box, handwritten) in the model's order; box is [left, top, right, bottom].

    Rows run top to bottom, cells left to right. Indent is 0, 1 or 2 for rows with a position (None without one); align is
    "left", "center" or "right". A piece whose box is unusable is kept as a row of its own after the piece before it."""
    pieces = [(text, tuple(box) if usable(box) else None, bool(handwritten)) for text, box, handwritten in pieces]
    if not pieces:
        return [], []
    placed = [index for index, (_, box, _) in enumerate(pieces) if box]
    if len(placed) < len(pieces) * USABLE_SHARE or not placed:
        return [Row([Cell(text, box, handwritten)]) for text, box, handwritten in pieces], [NO_POSITION]
    # Units: w = a character's width, h = a text's height, both from the pieces (so any pixel or 0–1000 frame gives the same rows).
    w = percentile([(box[2] - box[0]) / max(1, len(text)) for text, box, _ in (pieces[i] for i in placed)], 0.25)
    h = percentile([box[3] - box[1] for _, box, _ in (pieces[i] for i in placed)], 0.5)
    left = {i: pieces[i][1][0] / w for i in placed}
    right = {i: pieces[i][1][2] / w for i in placed}
    cx = {i: (left[i] + right[i]) / 2 for i in placed}
    cy = {i: (pieces[i][1][1] + pieces[i][1][3]) / 2 / h for i in placed}
    printed = [i for i in placed if not pieces[i][2]] or placed
    # A few pieces cannot tell a large tilt from a pairing of rows (a title and a price far below it): they search only the small slopes,
    # and fewer than FEW_TO_MEASURE are read level.
    measured = len(placed) >= MIN_TO_MEASURE
    slant = margin_slope([(left[i], cy[i]) for i in placed]) if len(placed) >= FEW_TO_MEASURE else None
    slope = row_slope({i: (cx[i], cy[i]) for i in placed}, slant, SLOPE_LIMIT if measured else FEW_SLOPE_LIMIT) if len(placed) >= FEW_TO_MEASURE else 0.0
    row_y = {i: cy[i] + slope * cx[i] for i in placed}
    # Row membership: printed pieces by row_y, then each handwritten piece to the nearest printed row, else rows of their own.
    groups = group({i: row_y[i] for i in printed}) if printed else []
    centre_of = lambda members: sum(row_y[i] for i in members) / len(members)
    loose = [i for i in placed if i not in printed]
    for index in sorted(loose, key=row_y.get):
        near = min(groups, key=lambda members: abs(centre_of(members) - row_y[index]), default=None)
        if near is not None and abs(centre_of(near) - row_y[index]) <= HANDWRITING_ROW:
            near.append(index)
        else:
            groups.append([index])  # Handwriting alone (or at a new height) starts a row; the next one joins it by the same rule.
    groups.sort(key=centre_of)
    shear = slant or 0.0
    shifted_left = {i: left[i] - shear * cy[i] for i in placed}
    shifted_right = {i: right[i] - shear * cy[i] for i in placed}
    rows, extents, owner = [], [], {}
    for members in groups:
        cells = []  # [texts, boxes, handwritten, left, right]
        for index in sorted(members, key=shifted_left.get):
            text, box, handwritten = pieces[index]
            if cells and cells[-1][2] == handwritten and shifted_left[index] - cells[-1][4] < SAME_CELL:
                cell = cells[-1]
                cell[0].append(text), cell[1].append(box)
                cell[4] = max(cell[4], shifted_right[index])
            else:
                cells.append([[text], [box], handwritten, shifted_left[index], shifted_right[index]])
        row = Row([Cell(" ".join(texts), (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)), hw)
                   for texts, boxes, hw, _, _ in cells])
        rows.append(row)
        extents.append((cells[0][3], cells[-1][4]))
        for index in members:
            owner[index] = row
    # Extent, alignment and indent, in character widths.
    edge_left = min(start for start, _ in extents)  # The leftmost row sets the margin, however few rows sit on it: a margin of 10% of the rows would call a lone main row's followers unindented.
    edge_right = percentile([end for _, end in extents], 0.9)
    middle = (edge_left + edge_right) / 2
    offsets = []
    for row, (start, end) in zip(rows, extents):
        row.align = "left"
        if len(row.cells) == 1:
            if abs((start + end) / 2 - middle) <= CENTER_TOLERANCE and start - edge_left >= EDGE_CLEARANCE and edge_right - end >= EDGE_CLEARANCE:
                row.align = "center"
            elif abs(edge_right - end) <= RIGHT_TOLERANCE and start > edge_left + (edge_right - edge_left) / 3:
                row.align = "right"
        if row.align == "left":
            offsets.append((start - edge_left, row))
        else:
            row.indent = 0
    level, previous = 0, None
    for offset, row in sorted(offsets, key=lambda pair: pair[0]):
        if offset < INDENT_GROUP_GAP:
            row.indent = 0
            continue
        if previous is None or offset - previous >= INDENT_GROUP_GAP:
            level += 1
        previous = offset
        row.indent = min(level, 2)
    notes = []
    unplaced, tail = [i for i in range(len(pieces)) if i not in owner], {}
    for index in unplaced:
        text, _, handwritten = pieces[index]
        row = Row([Cell(text, None, handwritten)])
        after = owner.get(index - 1) if index else None
        # Right after the row of the piece before it, and after any unplaced rows already put there, so the answer's order holds.
        anchor = after
        while anchor in tail:
            anchor = tail[anchor]
        rows.insert(rows.index(anchor) + 1 if anchor is not None else 0, row)
        owner[index] = row
        if after is not None:
            tail[anchor] = row
    if unplaced:
        notes.append(UNPLACED.format(count=len(unplaced)))
    return rows, notes
