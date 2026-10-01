"""Separate pieces of paper in one scan or photo: several receipts on a flatbed, or laid side by side on a table.

Deterministic and conservative, on a coarse grid of the image (numpy only, no model). A split is made only where it is
plain in the pixels; anything else is one region, and the text segmentation step (extraction) handles receipts that
touch or sit one under another with ordinary gaps. Two cases:

- Contrasting background (scanner lid open, a dark table): paper is the bright area that differs from the image border.
  Each separate bright area large enough to be a receipt is a region.
- Background as light as the paper (lid closed, white table): only ink is visible, so only side-by-side receipts with a
  clear full-height gap between them are separated. A gap inside one receipt is usually a full-width band (between its
  header and items), which is why light backgrounds are never cut horizontally here.
"""

import numpy as np

GRID = 256  # Cells along the image's longer side.
MIN_AREA = 0.02  # A region must cover this share of the image...
MIN_SIDE = 0.08  # ...and this share of each dimension.
MAX_REGIONS = 12
GAP = 0.04  # A side-by-side gap on a light background: this share of the width, free of ink over the full height.


def grid(image):
    """(grayscale cell means, cell size) of a PIL image."""
    gray = np.asarray(image.convert("L"), dtype=np.float32)
    height, width = gray.shape
    cell = max(1, int(np.ceil(max(width, height) / GRID)))
    rows, columns = height // cell, width // cell
    if rows < 8 or columns < 8:
        return None, cell
    trimmed = gray[:rows * cell, :columns * cell].reshape(rows, cell, columns, cell)
    return trimmed.mean(axis=(1, 3)), cell


def components(mask):
    """Bounding boxes (row0, col0, row1, col1, cells) of 4-connected True areas."""
    seen = np.zeros(mask.shape, dtype=bool)
    rows, columns = mask.shape
    found = []
    for start_row, start_column in zip(*np.nonzero(mask)):
        if seen[start_row, start_column]:
            continue
        stack, seen[start_row, start_column] = [(start_row, start_column)], True
        top, left, bottom, right, count = start_row, start_column, start_row, start_column, 0
        while stack:
            row, column = stack.pop()
            count += 1
            top, left, bottom, right = min(top, row), min(left, column), max(bottom, row), max(right, column)
            for r, c in ((row - 1, column), (row + 1, column), (row, column - 1), (row, column + 1)):
                if 0 <= r < rows and 0 <= c < columns and mask[r, c] and not seen[r, c]:
                    seen[r, c] = True
                    stack.append((r, c))
        found.append((int(top), int(left), int(bottom) + 1, int(right) + 1, count))
    return found


def dilate(mask, steps):
    for _ in range(steps):
        grown = mask.copy()
        grown[1:] |= mask[:-1]
        grown[:-1] |= mask[1:]
        grown[:, 1:] |= mask[:, :-1]
        grown[:, :-1] |= mask[:, 1:]
        mask = grown
    return mask


def merge_overlapping(boxes):
    """Boxes that overlap are one piece of paper (a fold or shadow split it)."""
    boxes = list(boxes)
    changed = True
    while changed:
        changed = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                    boxes[i] = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
                    del boxes[j]
                    changed = True
                    break
            if changed:
                break
    return boxes


def paper_regions(cells):
    """Bright areas unlike the border, on a contrasting background. None when the background is not contrasting."""
    border = np.concatenate([cells[0], cells[-1], cells[:, 0], cells[:, -1]])
    background = float(np.median(border))
    bright = cells > background + 60
    if background > 150 or bright.mean() < 0.1:
        return None
    rows, columns = cells.shape
    boxes = [(top, left, bottom, right) for top, left, bottom, right, count in components(dilate(bright, 1))
             if count >= MIN_AREA * rows * columns and bottom - top >= MIN_SIDE * rows and right - left >= MIN_SIDE * columns]
    return merge_overlapping(boxes)


def side_by_side(cells):
    """Full-height bands without ink on a light background, wide enough to separate two receipts."""
    rows, columns = cells.shape
    ink = cells < float(np.median(cells)) - 50
    used = ink.any(axis=0)
    if not used.any():
        return []
    first, last = int(np.argmax(used)), columns - int(np.argmax(used[::-1]))
    boxes, start, gap = [], first, 0
    for column in range(first, last):
        if used[column]:
            if gap >= GAP * columns:
                boxes.append((0, start, rows, column - gap))
                start = column
            gap = 0
        else:
            gap += 1
    boxes.append((0, start, rows, last))
    # Each side must hold a receipt's worth of ink; trim every box to the rows that have ink.
    kept = []
    for _, left, _, right in boxes:
        band = ink[:, left:right]
        lines = np.nonzero(band.any(axis=1))[0]
        if right - left >= MIN_SIDE * columns and len(lines) and lines[-1] - lines[0] >= MIN_SIDE * rows:
            kept.append((int(lines[0]), left, int(lines[-1]) + 1, right))
    return kept if len(kept) == len(boxes) else []


def reading_order(boxes):
    """Top to bottom by rows of regions that share height, then left to right within a row."""
    rows = []
    for box in sorted(boxes):
        if rows and box[0] < min(other[2] for other in rows[-1]):
            rows[-1].append(box)
        else:
            rows.append([box])
    return [box for row in rows for box in sorted(row, key=lambda item: item[1])]


def find_regions(image):
    """[(left, top, right, bottom)] in image pixels, in reading order, or [] when the image is one piece of paper
    (or the split is not plain). A small margin is kept around each region."""
    cells, cell = grid(image)
    if cells is None:
        return []
    boxes = paper_regions(cells)
    if boxes is None:
        boxes = side_by_side(cells)
    if not 2 <= len(boxes) <= MAX_REGIONS:
        return []
    rows, columns = cells.shape
    regions = []
    for top, left, bottom, right in reading_order(boxes):
        top, left, bottom, right = max(0, top - 1), max(0, left - 1), min(rows, bottom + 1), min(columns, right + 1)
        regions.append((left * cell, top * cell, min(image.width, right * cell), min(image.height, bottom * cell)))
    return regions
