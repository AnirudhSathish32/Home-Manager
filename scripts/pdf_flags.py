"""Which glyphs give a PDF page its layout flags, and whether they touch the rows that look like transactions.

Usage:  python scripts/pdf_flags.py "<path to a PDF>"

Reads the PDF with the reader's own glyph capture (documents/pdf_layout.py `capture_layout`) and repeats the checks
that set `unsupported_text_rotation` and `overlapping_text` glyph by glyph. Nothing is written anywhere.
Prints only flags, counts, angles, glyph kinds (letters, digits, other) and positions as a percentage of the page
(0,0 is the top left). It prints no text from the document: words are read only to find the rows' positions.
"""
from collections import Counter
import math
from pathlib import Path
import re
from statistics import median
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pypdfium2 as pdfium  # noqa: E402
import pypdfium2.raw as raw  # noqa: E402

from home_manager.documents import pdf_layout  # noqa: E402
from home_manager.documents.pdf_layout import capture_layout, point, visual_box  # noqa: E402

DATE = re.compile(r"\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?")
AMOUNT = re.compile(r"[-+(]?[$€£]?\d{1,3}(,\d{3})*\.\d{2}\)?-?")
HEADING = {"date", "description", "amount", "balance", "withdrawals", "deposits", "debit", "credit", "debits", "credits"}
LIMIT = 15


def kinds(chars):
    count = Counter("letter" if c.text.isalpha() else "digit" if c.text.isdigit() else "other" for c in chars)
    return ", ".join(f"{n} {kind}" for kind, n in sorted(count.items()))


def report(page_number, layout, textpage):
    width, height = layout.preview_width, layout.preview_height
    matrix = layout.page_to_preview

    def where(box):
        return f"x {100*box[0]/width:5.1f}–{100*box[2]/width:5.1f}%  y {100*box[1]/height:5.1f}–{100*box[3]/height:5.1f}%"

    print(f"\n=== Page {page_number} ===")
    print("flags:", ", ".join(layout.issues) or "none")
    glyphs = [c for c in layout.characters if c.bbox and not c.generated and c.text and not c.text.isspace()]
    if not glyphs:
        print("no positioned glyphs")
        return
    scale = math.hypot(matrix[0], matrix[1])
    size = max(1, median(c.font_size for c in glyphs)*scale)
    boxes = {c.index: visual_box(matrix, c.bbox) for c in glyphs}
    print(f"glyphs: {len(glyphs)}   median font size: {size:.1f} px   page: {width}×{height} px")
    sizes = Counter(round(c.font_size, 2) for c in glyphs).most_common(5)
    print("reported font sizes (pt, glyphs):", ", ".join(f"{s} ×{n}" for s, n in sizes),
          f"  median glyph height: {median(boxes[c.index][3] - boxes[c.index][1] for c in glyphs):.1f} px")

    # Rows that look like a transactions heading, or like a transaction (a date first and an amount somewhere).
    words = {w.id: w for w in layout.words}
    band, headings = [], []
    for line in layout.lines:
        texts = [words[id].text for id in line.word_ids]
        box = visual_box(matrix, line.bbox)
        if len(HEADING.intersection(t.lower() for t in texts)) >= 3:
            headings.append(box)
        elif texts and DATE.fullmatch(texts[0]) and any(AMOUNT.fullmatch(t) for t in texts[1:]):
            band.append(box)
    for box in headings:
        print(f"heading-like row:       {where(box)}")
    if band:
        top, bottom = min(b[1] for b in band), max(b[3] for b in band)
        print(f"transaction-like rows:  {len(band)}, y {100*top/height:.1f}–{100*bottom/height:.1f}%")
    else:
        top = bottom = None
        print("transaction-like rows:  none found")

    def in_band(box):
        return top is not None and box[1] < bottom and box[3] > top

    # unsupported_text_rotation: the glyph's direction, mapped to the preview, isn't left to right within 5%.
    rotated = []
    for c in layout.characters:
        if c.generated or not c.text or c.text.isspace() or not c.bbox:
            continue
        dx, dy = point(matrix, math.cos(c.angle), math.sin(c.angle))
        ox, oy = point(matrix, 0, 0)
        if dx-ox <= 0 or abs(dy-oy) > abs(dx-ox)*0.05:
            rotated.append(c)
    runs = []
    for c in rotated:
        if runs and c.index - runs[-1][-1].index <= 2 and abs(c.angle - runs[-1][-1].angle) < 1e-3:
            runs[-1].append(c)
        else:
            runs.append([c])
    print(f"\nrotated glyphs: {len(rotated)} in {len(runs)} run(s)")
    for run in runs[:LIMIT]:
        box = visual_box(matrix, (min(c.bbox[0] for c in run), min(c.bbox[1] for c in run),
                                  max(c.bbox[2] for c in run), max(c.bbox[3] for c in run)))
        print(f"  {len(run):3} glyphs ({kinds(run)}), angle {math.degrees(run[0].angle):6.1f}°, {where(box)}"
              f"{'   INSIDE transaction rows' if in_band(box) else ''}")

    # overlapping_text, two ways: the same glyph drawn twice in the same box, or a glyph starting well inside the one before.
    seen = Counter((c.text, tuple(round(v, 1) for v in c.bbox)) for c in glyphs)
    doubled = [c for c in glyphs if seen[(c.text, tuple(round(v, 1) for v in c.bbox))] > 1]
    baseline = {c.index: point(matrix, *c.origin)[1] if c.origin else boxes[c.index][3] for c in glyphs}
    rows = []
    for c in sorted(glyphs, key=lambda c: (baseline[c.index], boxes[c.index][0], c.index)):
        if not rows or abs(baseline[c.index] - baseline[rows[-1][0].index]) > size*0.25:
            rows.append([])
        rows[-1].append(c)
    squeezed = []
    for row in rows:
        row.sort(key=lambda c: (boxes[c.index][0], c.index))
        for previous, c in zip(row, row[1:]):
            gap = boxes[c.index][0] - boxes[previous.index][2]
            if gap < -size*0.15:
                squeezed.append((row, previous, c, gap))

    def by_row(chars):
        groups = {}
        for c in chars:
            groups.setdefault(round(baseline[c.index]), []).append(c)
        return list(groups.values())

    print(f"\nglyphs drawn twice in the same box: {len(doubled)}")
    for group in by_row(doubled)[:LIMIT]:
        box = (min(boxes[c.index][0] for c in group), min(boxes[c.index][1] for c in group),
               max(boxes[c.index][2] for c in group), max(boxes[c.index][3] for c in group))
        print(f"  {len(group):3} glyphs ({kinds(group)}), {where(box)}{'   INSIDE transaction rows' if in_band(box) else ''}")

    print(f"\nglyph pairs overlapping by more than 15% of the font size: {len(squeezed)}")
    for _, previous, c, gap in squeezed[:LIMIT]:
        box = (boxes[previous.index][0], min(boxes[previous.index][1], boxes[c.index][1]),
               boxes[c.index][2], max(boxes[previous.index][3], boxes[c.index][3]))
        print(f"  overlap {-gap/size:4.2f}× font size ({kinds([previous, c])}), {where(box)}"
              f"{'   INSIDE transaction rows' if in_band(box) else ''}")
    if len(squeezed) > LIMIT:
        print(f"  … and {len(squeezed) - LIMIT} more")

    others = {
        "glyphs outside the page": sum(1 for c in glyphs if c.bbox[0] < layout.bounds[0]-1 or c.bbox[1] < layout.bounds[1]-1
                                       or c.bbox[2] > layout.bounds[2]+1 or c.bbox[3] > layout.bounds[3]+1),
        "glyphs with unicode errors": sum(1 for c in layout.characters if c.unicode_error),
    }
    print("\n" + "   ".join(f"{name}: {n}" for name, n in others.items()))

    # How each glyph is drawn: PDFium's font size, the scale of its matrix, and its box height, all in PDF points.
    drawn = Counter()
    for c in glyphs:
        matrix_ = raw.FS_MATRIX()
        ok = raw.FPDFText_GetMatrix(textpage, c.index, matrix_)
        reported = raw.FPDFText_GetFontSize(textpage, c.index)
        scale_ = math.hypot(matrix_.c, matrix_.d) if ok else None
        loose = raw.FS_RECTF()
        raw.FPDFText_GetLooseCharBox(textpage, c.index, loose)
        drawn[(round(reported, 2), ok, round(scale_, 3) if scale_ is not None else None,
               round(c.bbox[3] - c.bbox[1], 1), round(abs(loose.top - loose.bottom), 1))] += 1
    print("\nreported size, matrix found, matrix scale, glyph height, loose box height (pt) × glyphs:")
    for key, n in drawn.most_common(8):
        print(f"  {key} ×{n}")


path = Path(sys.argv[1]).resolve()
with pdfium.PdfDocument(str(path)) as pdf:
    print(f"pages: {len(pdf)}   this checkout has the size fix: {hasattr(pdf_layout, 'upright')}   pypdfium2 {pdfium.PYPDFIUM_INFO}, pdfium {pdfium.PDFIUM_INFO}")
    for index in range(len(pdf)):
        page = pdf[index]
        textpage = page.get_textpage()
        try:
            width, height = page.get_size()
            bitmap = page.render(scale=min(2, 2400 / max(width, height)))
            try:
                report(index+1, capture_layout(page, textpage, bitmap, index+1, "0"*64, textpage.get_text_bounded()), textpage)
            finally:
                bitmap.close()
        finally:
            textpage.close()
            page.close()
