"""Native PDF evidence and conservative, document-independent layout reconstruction.

All boxes use unrotated PDF canvas units (left, bottom, right, top). The affine
page_to_preview transform maps these to top-left preview pixels: (a*x+c*y+e,
b*x+d*y+f). Visual order is separate from PDFium's character-stream indexes.
No geometry or recognition confidence is attributed to model transcriptions.
"""

from collections import Counter
import ctypes
import math
import re
from statistics import median
from typing import Literal

from pydantic import Field, model_validator

from .receipt_schema import StrictModel

MAX_CHARACTERS = 100_000
MAX_DOCUMENT_CHARACTERS = 250_000
PDF_EVIDENCE_BYTES = 24 * 1024**2
PDF_PREVIEW_BYTES = 64 * 1024**2
PDF_RUN_RESERVATION = 128 * 1024**2
Box = tuple[float, float, float, float]


class PDFCharacter(StrictModel):
    index: int = Field(ge=0)
    unicode_value: int = Field(ge=0)
    text: str = Field(max_length=1)
    continuation_of: int | None = None
    bbox: Box | None = None
    origin: tuple[float, float] | None = None
    font_size: float = Field(ge=0)
    angle: float
    generated: bool = False
    unicode_error: bool = False


class PDFWord(StrictModel):
    id: str
    text: str
    character_indexes: list[int] = Field(min_length=1, max_length=1000)
    bbox: Box


class PDFLayoutLine(StrictModel):
    id: str
    word_ids: list[str] = Field(min_length=1)
    text: str
    bbox: Box


class PDFCell(StrictModel):
    id: str
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1, le=500)
    column_span: int = Field(default=1, ge=1, le=40)
    word_ids: list[str]
    line_ids: list[str]
    text: str  # A blank cell is empty, never zero or a guessed value.


class PDFTable(StrictModel):
    id: str
    rows: int = Field(ge=2, le=500)
    columns: int = Field(ge=2, le=40)
    header_rows: list[int] = Field(min_length=1)
    cells: list[PDFCell] = Field(max_length=20_000)


class PDFLayoutBlock(StrictModel):
    id: str
    source: Literal["pdf_text"] = "pdf_text"
    kind: Literal["heading", "paragraph", "list", "key_value", "table"]
    status: Literal["reconstructed", "needs_review"] = "reconstructed"
    line_ids: list[str] = Field(min_length=1)
    table_id: str | None = None


def union(boxes):
    boxes = list(boxes)
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def point(matrix, x, y):
    a, b, c, d, e, f = matrix
    return a*x + c*y + e, b*x + d*y + f


def visual_box(matrix, box):
    x0, y0, x1, y1 = box
    points = [point(matrix, x, y) for x, y in ((x0, y0), (x0, y1), (x1, y0), (x1, y1))]
    return min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)


class PDFLayout(StrictModel):
    version: Literal[1] = 1
    source: Literal["pdf_text"] = "pdf_text"
    source_hash: str
    page_number: int = Field(ge=1, le=200)
    bounds: Box
    rotation: Literal[0, 90, 180, 270]
    coordinate_system: Literal["pdf_canvas"] = "pdf_canvas"
    preview_width: int = Field(ge=1, le=2400)
    preview_height: int = Field(ge=1, le=2400)
    page_to_preview: tuple[float, float, float, float, float, float]
    raw_text: str = Field(max_length=200_000)
    characters: list[PDFCharacter] = Field(max_length=MAX_CHARACTERS)
    words: list[PDFWord] = Field(max_length=30_000)
    lines: list[PDFLayoutLine] = Field(max_length=5000)
    blocks: list[PDFLayoutBlock] = Field(max_length=5000)
    tables: list[PDFTable] = Field(max_length=100)
    coverage: Literal["native_text", "needs_review"]
    issues: list[str] = Field(max_length=100)

    @model_validator(mode="after")
    def validate_evidence(self):
        prefix = f"page-{self.page_number}-"
        if self.bounds[0] >= self.bounds[2] or self.bounds[1] >= self.bounds[3]:
            raise ValueError("Invalid PDF layout bounds.")
        a, b, c, d, _, _ = self.page_to_preview
        if abs(a*d - b*c) < 1e-12:
            raise ValueError("Invalid PDF preview transform.")
        if self.coverage == "native_text" and self.issues:
            raise ValueError("PDF layout issues require review coverage.")
        chars = {char.index: char for char in self.characters}
        if list(chars) != list(range(len(self.characters))):
            raise ValueError("PDF character indexes must preserve the engine array.")
        codes = [char.unicode_value for char in self.characters]
        for char in self.characters:
            expected_text, continuation, invalid = decode_character(codes, char.index)
            if char.text != expected_text or char.continuation_of != continuation or (invalid and not char.unicode_error):
                raise ValueError("Invalid PDF Unicode character/continuation.")
            if char.unicode_error and "unicode_mapping" not in self.issues:
                raise ValueError("PDF Unicode errors require a coverage issue.")
            if char.generated and char.bbox is not None:
                raise ValueError("Generated PDF characters cannot have glyph geometry.")
            if char.bbox is not None:
                l, b, r, t = char.bbox
                if l >= r or b >= t:
                    raise ValueError("Invalid PDF glyph bounds.")
                if (l < self.bounds[0]-1 or b < self.bounds[1]-1 or r > self.bounds[2]+1 or t > self.bounds[3]+1) and "glyph_outside_page" not in self.issues:
                    raise ValueError("Out-of-page PDF glyph requires a coverage issue.")
            elif not char.generated and not char.text.isspace() and "degenerate_glyph" not in self.issues:
                raise ValueError("Missing PDF glyph requires a coverage issue.")
        words = {word.id: word for word in self.words}
        lines = {line.id: line for line in self.lines}
        tables = {table.id: table for table in self.tables}
        ids = [item.id for items in (self.words, self.lines, self.blocks, self.tables) for item in items]
        ids += [cell.id for table in self.tables for cell in table.cells]
        if len(ids) != len(set(ids)) or any(not id.startswith(prefix) for id in ids):
            raise ValueError("Duplicate or foreign PDF layout IDs.")
        used_chars = []
        for word in self.words:
            selected = [chars.get(i) for i in word.character_indexes]
            if any(char is None or char.bbox is None or char.generated or char.text.isspace() for char in selected):
                raise ValueError("PDF word cites unavailable characters.")
            if word.text != "".join(char.text for char in selected) or word.bbox != union(char.bbox for char in selected):
                raise ValueError("PDF word does not copy source characters/geometry.")
            used_chars.extend(word.character_indexes)
        if len(used_chars) != len(set(used_chars)):
            raise ValueError("PDF characters assigned to multiple words.")
        eligible = {char.index for char in self.characters if char.bbox and not char.generated and not char.text.isspace()}
        if set(used_chars) != eligible:
            raise ValueError("PDF layout omitted source characters.")
        used_words = []
        for line in self.lines:
            if any(id not in words for id in line.word_ids):
                raise ValueError("PDF line cites an unknown word.")
            if line.text != " ".join(words[id].text for id in line.word_ids) or line.bbox != union(words[id].bbox for id in line.word_ids):
                raise ValueError("PDF line does not copy its words.")
            used_words.extend(line.word_ids)
        if Counter(used_words) != Counter(words.keys()):
            raise ValueError("PDF line coverage must include each word once.")
        used_lines, used_tables = [], []
        for block in self.blocks:
            if any(id not in lines for id in block.line_ids):
                raise ValueError("PDF block cites an unknown line.")
            used_lines.extend(block.line_ids)
            if block.kind == "table":
                if block.table_id not in tables:
                    raise ValueError("PDF block cites an unknown table.")
                used_tables.append(block.table_id)
                table_lines = {id for cell in tables[block.table_id].cells for id in cell.line_ids}
                if table_lines != set(block.line_ids):
                    raise ValueError("PDF table and block coverage disagree.")
            elif block.table_id is not None:
                raise ValueError("Only a table block may cite a table.")
        if Counter(used_lines) != Counter(lines.keys()) or Counter(used_tables) != Counter(tables.keys()):
            raise ValueError("PDF block coverage is incomplete or duplicated.")
        cell_words = []
        for table in self.tables:
            occupied = set()
            row_positions = []
            if len(set(table.header_rows)) != len(table.header_rows) or any(not 0 <= row < table.rows for row in table.header_rows):
                raise ValueError("Invalid PDF table header rows.")
            for cell in table.cells:
                slots = {(r, c) for r in range(cell.row, cell.row + cell.row_span) for c in range(cell.column, cell.column + cell.column_span)}
                if any(r >= table.rows or c >= table.columns for r, c in slots) or occupied & slots:
                    raise ValueError("Overlapping or out-of-bounds PDF cells.")
                occupied |= slots
                if any(id not in words for id in cell.word_ids) or any(id not in lines for id in cell.line_ids):
                    raise ValueError("PDF cell cites unknown evidence.")
                if cell.text != " ".join(words[id].text for id in cell.word_ids):
                    raise ValueError("PDF cell does not copy its words.")
                members = {id for line_id in cell.line_ids for id in lines[line_id].word_ids}
                if not set(cell.word_ids) <= members:
                    raise ValueError("PDF cell words are not on its cited lines.")
                cell_words.extend(cell.word_ids)
            # Check the visual order as well as text membership. A saved cell
            # cannot move an otherwise valid amount into the column to its left.
            for row in range(table.rows):
                populated = sorted((cell for cell in table.cells if cell.row == row and cell.word_ids), key=lambda cell: cell.column)
                boxes = [visual_box(self.page_to_preview, union(words[id].bbox for id in cell.word_ids)) for cell in populated]
                if any(left[2] > right[0]+1 for left, right in zip(boxes, boxes[1:])):
                    raise ValueError("PDF cells disagree with visual column order.")
                if boxes:
                    row_positions.append(min(box[1] for box in boxes))
            if any(top > bottom+1 for top, bottom in zip(row_positions, row_positions[1:])):
                raise ValueError("PDF cells disagree with visual row order.")
            if len(occupied) != table.rows * table.columns:
                raise ValueError("PDF table must preserve blank cells.")
            block = next(block for block in self.blocks if block.table_id == table.id)
            if Counter(id for cell in table.cells for id in cell.word_ids) != Counter(id for line_id in block.line_ids for id in lines[line_id].word_ids):
                raise ValueError("PDF table omits or duplicates words.")
        if len(cell_words) != len(set(cell_words)):
            raise ValueError("PDF words assigned to multiple cells.")
        return self

    @property
    def reading_text(self):
        """Deterministic projection; does not replace historical flat-text citations."""
        lines = {line.id: line for line in self.lines}
        tables = {table.id: table for table in self.tables}
        parts = []
        for block in self.blocks:
            if block.table_id:
                table = tables[block.table_id]
                for row in range(table.rows):
                    parts.append(" | ".join(cell.text for cell in sorted(table.cells, key=lambda cell: cell.column) if cell.row == row))
            else:
                parts.extend(lines[id].text for id in block.line_ids)
        return "\n".join(parts)


def preview_transform(bitmap, page):
    """Invert PDFium's double-precision device-to-page transform, including crop/rotation."""
    conv = bitmap.get_posconv(page)
    x0, y0 = conv.to_page(0, 0)
    xx, yx = conv.to_page(bitmap.width, 0)
    xy, yy = conv.to_page(0, bitmap.height)
    a, b = (xx-x0)/bitmap.width, (yx-y0)/bitmap.width
    c, d = (xy-x0)/bitmap.height, (yy-y0)/bitmap.height
    det = a*d-b*c
    if not math.isfinite(det) or abs(det) < 1e-12:
        raise ValueError("Invalid PDF page transform.")
    return d/det, -b/det, -c/det, a/det, (c*y0-d*x0)/det, (b*x0-a*y0)/det


def decode_character(codes, index):
    """PDFium can expose UTF-16 pairs as two engine indexes, despite its uint API.
    Keep both indexes; the first carries the decoded scalar and the second is
    an explicit continuation. Isolated surrogates are retained as flagged U+FFFD.
    """
    code = codes[index]
    if 0xd800 <= code <= 0xdbff and index+1 < len(codes) and 0xdc00 <= codes[index+1] <= 0xdfff:
        return chr(0x10000 + ((code-0xd800) << 10) + codes[index+1]-0xdc00), None, False
    if 0xdc00 <= code <= 0xdfff and index and 0xd800 <= codes[index-1] <= 0xdbff:
        return "", index-1, False
    invalid = code == 0 or code > 0x10ffff or 0xd800 <= code <= 0xdfff
    return "\ufffd" if invalid else chr(code), None, invalid


def capture_layout(page, textpage, bitmap, number, digest, raw_text):
    """Called only inside the bounded PDF worker while engine handles remain alive."""
    import pypdfium2.raw as raw

    count = textpage.count_chars()
    if count > MAX_CHARACTERS:
        raise ValueError("PDF page exceeds the text limit.")
    matrix, bounds = preview_transform(bitmap, page), page.get_bbox()
    issues, characters = set(), []
    codes = [raw.FPDFText_GetUnicode(textpage, index) for index in range(count)]
    for index in range(count):
        text, continuation, invalid = decode_character(codes, index)
        generated = raw.FPDFText_IsGenerated(textpage, index) == 1
        error = invalid or raw.FPDFText_HasUnicodeMapError(textpage, index) != 0
        if error:
            issues.add("unicode_mapping")
        size = raw.FPDFText_GetFontSize(textpage, index)
        angle = raw.FPDFText_GetCharAngle(textpage, index)
        box = origin = None
        if not generated and not text.isspace():
            box = tuple(round(v, 5) for v in textpage.get_charbox(index))
            x, y = ctypes.c_double(), ctypes.c_double()
            if raw.FPDFText_GetCharOrigin(textpage, index, x, y):
                origin = x.value, y.value
            if not all(math.isfinite(v) for v in box) or box[0] >= box[2] or box[1] >= box[3]:
                box = None
                issues.add("degenerate_glyph")
            elif box[0] < bounds[0] - 1 or box[1] < bounds[1] - 1 or box[2] > bounds[2] + 1 or box[3] > bounds[3] + 1:
                issues.add("glyph_outside_page")
            dx, dy = point(matrix, math.cos(angle), math.sin(angle))
            ox, oy = point(matrix, 0, 0)
            if dx-ox <= 0 or abs(dy-oy) > abs(dx-ox)*0.05:
                issues.add("unsupported_text_rotation")
        characters.append(PDFCharacter(index=index, unicode_value=codes[index], text=text, continuation_of=continuation,
                                       bbox=box, origin=origin, font_size=max(0, size),
                                       angle=angle, generated=generated, unicode_error=error))
    # Even a small image can contain amounts. Keep native evidence but require review;
    # automatic native/vision region merging is intentionally not claimed here.
    if any(True for _ in page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE])):
        issues.add("possible_image_content")
    if len("".join(raw_text.split())) < 40:
        issues.add("insufficient_native_text")
    words, lines, blocks, tables = reconstruct(characters, matrix, number, issues)
    return PDFLayout(source_hash=digest, page_number=number, bounds=bounds, rotation=page.get_rotation(),
                     preview_width=bitmap.width, preview_height=bitmap.height, page_to_preview=matrix,
                     raw_text=raw_text, characters=characters, words=words, lines=lines, blocks=blocks, tables=tables,
                     coverage="needs_review" if issues else "native_text", issues=sorted(issues))


def reconstruct(characters, matrix, number, issues):
    prefix = f"page-{number}-layout-"
    glyphs = [char for char in characters if char.bbox and not char.generated and char.text and not char.text.isspace()]
    if not glyphs:
        return [], [], [], []
    scale = math.hypot(matrix[0], matrix[1])
    size = max(1, median(char.font_size for char in glyphs)*scale)
    boxes = {char.index: visual_box(matrix, char.bbox) for char in glyphs}
    baseline = {char.index: point(matrix, *char.origin)[1] if char.origin else boxes[char.index][3] for char in glyphs}
    rows = []
    for char in sorted(glyphs, key=lambda char: (baseline[char.index], boxes[char.index][0], char.index)):
        if not rows or abs(baseline[char.index] - baseline[rows[-1][0].index]) > size*0.25:
            rows.append([])
        rows[-1].append(char)
    words, visual_rows = [], []
    seen = set()
    for row in rows:
        row.sort(key=lambda char: (boxes[char.index][0], char.index))
        groups = []
        for char in row:
            key = (char.text, tuple(round(v, 1) for v in char.bbox))
            if key in seen:
                issues.add("overlapping_text")
            seen.add(key)
            previous = groups[-1][-1] if groups else None
            gap = boxes[char.index][0] - boxes[previous.index][2] if previous else 0
            explicit_space = previous and 0 < char.index - previous.index < 20 and any(
                item.text.isspace() for item in characters[previous.index+1:char.index])
            if previous and gap < -size*0.15:
                issues.add("overlapping_text")
            if previous is None or gap > size*0.4 or explicit_space:
                groups.append([])
            groups[-1].append(char)
        row_words = []
        for group in groups:
            group = [part for char in group for part in
                     ([char, characters[char.index+1]] if char.index+1 < len(characters) and characters[char.index+1].continuation_of == char.index else [char])]
            word = PDFWord(id=f"{prefix}word-{len(words)+1}", text="".join(char.text for char in group),
                           character_indexes=[char.index for char in group], bbox=union(char.bbox for char in group))
            words.append(word)
            row_words.append(word)
        visual_rows.append(row_words)
    lines, blocks, tables = [], [], []
    word_boxes = {word.id: visual_box(matrix, word.bbox) for word in words}

    def segments(row):
        groups = []
        for word in row:
            if not groups or word_boxes[word.id][0] - word_boxes[groups[-1][-1].id][2] > size*1.5:
                groups.append([])
            groups[-1].append(word)
        return groups

    def table_grid(region):
        """Require a printed textual header and repeated numeric body alignment.
        Headerless, spanning and wrapped candidates stay text with a review issue.
        """
        groups = [segments(row) for row in region]
        header = groups[0]
        if len(region) < 3 or not 2 <= len(header) <= 40:
            return None
        numeric = lambda group: bool(re.fullmatch(r"[\s\d.,+\-()%$€£/]+", " ".join(w.text for w in group)))
        if any(numeric(group) for group in header) or any(
            not any(numeric(group) for group in row) or not any(any(char.isalpha() for word in group for char in word.text) for group in row)
            for row in groups[1:]
        ):
            return None
        starts = [word_boxes[group[0].id][0] for group in header]
        ends = [word_boxes[group[-1].id][2] for group in header]
        bands = [-math.inf] + [(ends[i]+starts[i+1])/2 for i in range(len(header)-1)] + [math.inf]
        grid = []
        for groups_row in groups:
            cells = [[] for _ in header]
            for group in groups_row:
                left, right = word_boxes[group[0].id][0], word_boxes[group[-1].id][2]
                candidates = [i for i in range(len(header)) if left >= bands[i]-size*0.2 and right <= bands[i+1]+size*0.2]
                if len(candidates) != 1 or cells[candidates[0]]:
                    return None
                cells[candidates[0]] = group
            grid.append(cells)
        # Every inferred column needs body support; do not invent empty columns from headings alone.
        if any(sum(bool(row[c]) for row in grid[1:]) < 1 for c in range(len(header))):
            return None
        return grid

    def add_line(row):
        line = PDFLayoutLine(id=f"{prefix}line-{len(lines)+1}", word_ids=[w.id for w in row],
                             text=" ".join(w.text for w in row), bbox=union(w.bbox for w in row))
        lines.append(line)
        return line

    def emit(region, depth=0):
        if not region:
            return
        # Persistent whitespace separates columns/side-by-side tables. Only cut
        # a table when both sides are independently supported tables.
        grid = table_grid(region)
        # Isolate a supported table before a page-wide gutter can split its
        # title and footnote from the numeric columns.
        if grid is None and depth < 12 and len(region) > 3:
            for start in range(len(region)-2):
                stop = start+3
                if table_grid(region[start:stop]) is not None:
                    while stop < len(region) and stop-start < 500 and table_grid(region[start:stop+1]) is not None:
                        stop += 1
                    if start or stop < len(region):
                        emit(region[:start], depth+1)
                        emit(region[start:stop], depth+1)
                        emit(region[stop:], depth+1)
                        return
        intervals = sorted((word_boxes[w.id][0], word_boxes[w.id][2]) for row in region for w in row)
        gaps, end = [], intervals[0][1]
        for start, right in intervals[1:]:
            if start-end > size*2.5:
                gaps.append((start-end, (start+end)/2))
            end = max(end, right)
        for _, cut in sorted(gaps, reverse=True) if depth < 12 else []:
            left = [[w for w in row if word_boxes[w.id][2] < cut] for row in region]
            right = [[w for w in row if word_boxes[w.id][0] > cut] for row in region]
            left, right = [row for row in left if row], [row for row in right if row]
            if len(left) >= 2 and len(right) >= 2 and (grid is None or (table_grid(left) and table_grid(right))):
                if grid is None and any(re.fullmatch(r"[\d.,+\-()%$€£]+", word.text) for row in region for word in row):
                    issues.add("unresolved_columns")
                emit(left, depth+1)
                emit(right, depth+1)
                return
        if grid and not issues & {"overlapping_text", "unsupported_text_rotation", "glyph_outside_page", "unicode_mapping"}:
            table_id = f"{prefix}table-{len(tables)+1}"
            row_lines = [add_line(row) for row in region]
            cells = [PDFCell(id=f"{table_id}-row-{r+1}-cell-{c+1}", row=r, column=c, word_ids=[w.id for w in group],
                             line_ids=[row_lines[r].id], text=" ".join(w.text for w in group))
                     for r, row in enumerate(grid) for c, group in enumerate(row)]
            tables.append(PDFTable(id=table_id, rows=len(grid), columns=len(grid[0]), header_rows=[0], cells=cells))
            blocks.append(PDFLayoutBlock(id=f"{prefix}block-{len(blocks)+1}", kind="table", line_ids=[line.id for line in row_lines], table_id=table_id))
            return
        ambiguous = any(len(segments(row)) >= 2 for row in region)
        if ambiguous:
            issues.add("unresolved_columns")
        for row in region:
            line = add_line(row)
            kind = "list" if re.match(r"^(?:[•*\-]|\d+[.)])\s", line.text) else "key_value" if ":" in line.text else "paragraph"
            if len(row) <= 10 and median(characters[i].font_size for w in row for i in w.character_indexes)*scale > size*1.25:
                kind = "heading"
            blocks.append(PDFLayoutBlock(id=f"{prefix}block-{len(blocks)+1}", kind=kind, line_ids=[line.id],
                                         status="needs_review" if ambiguous else "reconstructed"))

    # Split at vertical whitespace before considering columns, retaining section order.
    regions = []
    for row in visual_rows:
        if not regions or min(word_boxes[w.id][1] for w in row) - max(word_boxes[w.id][3] for w in regions[-1][-1]) > size*1.8:
            regions.append([])
        regions[-1].append(row)
    for region in regions:
        emit(region)
    return words, lines, blocks, tables
