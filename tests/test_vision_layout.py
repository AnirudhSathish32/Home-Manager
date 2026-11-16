"""The row builder of specs/receipt-layout-eval (plans/receipt-layout-eval P6): rows, cells, indents and alignment from the
boxes of text pieces alone (FR-10, FR-11; SC-06, SC-07, SC-08 on hand-built pieces). Pure code, synthetic pieces."""

from math import cos, radians, sin

import pytest

from home_manager.documents.vision_layout import NO_POSITION, build_rows

CHAR = 15.6     # a character's advance, in pixels
PITCH = 34      # row spacing
MARGIN = 52     # the main left edge
RIGHT = 708     # where right cells end
MIDDLE = 380
INDENT_STEP = 2 * CHAR
CAPS_HEIGHT, MIXED_HEIGHT = 19, 25  # all-caps text has no descenders: a shorter box


class Spec:
    """One cell of the hand-built receipt: text, its kind of position and the row's indent."""

    def __init__(self, text, where="left", indent=0, handwritten=False, gap=0):
        self.text, self.where, self.indent, self.handwritten, self.gap = text, where, indent, handwritten, gap


def receipt(rows, caps=False, size=(760, 0)):
    """(pieces, expected) of a flush receipt: rows is a list of lists of Spec. Pieces are (text, [l, t, r, b], handwritten) in
    reading order; expected is [(row text, indent, align)] per row."""
    pieces, expected = [], []
    for number, specs in enumerate(rows):
        top = 60 + number * PITCH
        texts = []
        for spec in specs:
            width = len(spec.text) * CHAR
            if spec.where == "left":
                left = MARGIN + spec.indent * INDENT_STEP + spec.gap
            elif spec.where == "right":
                left = RIGHT - width
            else:
                left = MIDDLE - width / 2
            height = CAPS_HEIGHT if caps or spec.text.upper() == spec.text else MIXED_HEIGHT
            pieces.append((spec.text, [left, top, left + width, top + height], spec.handwritten))
            texts.append(spec.text)
        first = specs[0]
        align = first.where if len(specs) == 1 else "left"
        indent = first.indent if align == "left" else 0
        expected.append((" ".join(texts), indent, align))
    return pieces, expected


def two(name, amount, indent=0):
    return [Spec(name, indent=indent), Spec(amount, "right")]


def padded(rows):
    """rows between two ordinary item rows above and two below, as a real receipt has width and a margin to measure."""
    above = [two("Bottled Water", "3.95"), two("Coffee", "14.95"), two("Toast", "4.25")]
    below = [two("Subtotal", "48.85"), two("Tax", "3.91"), two("Total", "52.76")]
    return above + rows + below, len(above), len(below)


def breakfast(caps=False):
    names = ["Bottled Water", "Coffee", "Georgia Peach Stack", "No Allergies", "Extra Syrup", "Better Than No Y'all Biscuits (3)", "Gravy"]
    amounts = ["3.95", "14.95", "18.70", "", "", "7.30", ""]
    indents = [0, 0, 0, 1, 2, 0, 1]
    rows = [[Spec("CRESCENT DINER" if caps else "Crescent Diner", "center")], [Spec("12 Main Street", "center")],
            [Spec("Server: Alex")], [Spec("Table 5")]]
    for name, amount, indent in zip(names, amounts, indents):
        rows.append(two(name, amount, indent) if amount else [Spec(name, indent=indent)])
    rows += [two("Subtotal", "48.85"), two("Tax", "3.91"), two("Bill", "52.76"), [Spec("Thank you", "center")]]
    pieces, expected = receipt(rows, caps)
    return pieces, expected


def rows_of(pieces):
    rows, notes = build_rows(pieces)
    return [(row.text, row.indent, row.align) for row in rows], notes


def transform(pieces, move):
    """The same pieces with each box's four corners moved by move(x, y) and the axis-aligned bounds taken."""
    moved = []
    for text, (left, top, right, bottom), handwritten in pieces:
        corners = [move(x, y) for x, y in ((left, top), (right, top), (right, bottom), (left, bottom))]
        xs, ys = [x for x, _ in corners], [y for _, y in corners]
        moved.append((text, [min(xs), min(ys), max(xs), max(ys)], handwritten))
    return moved


def tilt(degrees, centre=(380, 300)):
    angle = radians(degrees)
    return lambda x, y: (centre[0] + (x - centre[0]) * cos(angle) - (y - centre[1]) * sin(angle),
                         centre[1] + (x - centre[0]) * sin(angle) + (y - centre[1]) * cos(angle))


def keystone(inset=0.05, width=760, height=700):
    """A perspective warp that keeps horizontal lines level: the top edge is inset on both sides (x' = c + (x - c) / (1 + k y))."""
    k = -inset / height
    return lambda x, y: (width / 2 + (x - width / 2) / (1 + k * y), y / (1 + k * y))


def scale(pieces, sx, sy):
    return [(text, [left * sx, top * sy, right * sx, bottom * sy], handwritten) for text, (left, top, right, bottom), handwritten in pieces]


# Rows, cells, indents ----------------------------------------------------------------------------------------------

def test_a_name_and_its_amount_are_two_cells_of_one_row():
    rows, notes = build_rows(receipt([two("Coffee", "14.95"), two("Bottled Water", "3.95"), two("Tax", "3.91")])[0])
    assert [[cell.text for cell in row.cells] for row in rows] == [["Coffee", "14.95"], ["Bottled Water", "3.95"], ["Tax", "3.91"]]
    assert [row.text for row in rows] == ["Coffee 14.95", "Bottled Water 3.95", "Tax 3.91"] and notes == []


def test_pieces_in_any_order_make_the_same_rows():
    pieces, expected = breakfast()
    assert rows_of(list(reversed(pieces)))[0] == expected


def test_a_cell_box_is_the_union_of_its_pieces_boxes():
    pieces = [("Georgia", [52, 60, 160, 79], False), ("Peach", [168, 61, 250, 80], False), ("18.70", [620, 60, 708, 79], False),
              ("Stack", [52, 94, 140, 113], False)]
    pieces += [("Coffee", [52, 128 + 34 * n, 148, 147 + 34 * n], False) for n in range(6)]
    first = build_rows(pieces)[0][0]
    assert [cell.text for cell in first.cells] == ["Georgia Peach", "18.70"]
    assert first.cells[0].box == (52, 60, 250, 80)


@pytest.mark.parametrize("caps", [False, True])
def test_indent_zero_one_two_and_centre_and_right_rows(caps):
    pieces, expected = breakfast(caps)
    got, notes = rows_of(pieces)
    assert got == expected and notes == []
    assert {indent for _, indent, _ in got} == {0, 1, 2}
    assert [align for _, _, align in got].count("center") == 3


def test_a_row_printed_deeper_than_two_steps_is_indent_two():
    rows, above, below = padded([[Spec("Item A")], [Spec("Side", indent=1)], [Spec("Deeper", indent=2)], [Spec("Deepest", indent=3)],
                                 [Spec("Item B")]])
    pieces, _ = receipt(rows)
    got = rows_of(pieces)[0][above:-below]
    assert [indent for _, indent, _ in got] == [0, 1, 2, 2, 0]


def test_a_right_row_has_no_indent_and_a_one_cell_left_row_stays_left():
    rows, above, below = padded([[Spec("Coffee")], [Spec("Visit us again", "right")], [Spec("Open daily", "center")], [Spec("Tomorrow")],
                                 [Spec("Closed Sunday")]])
    got = rows_of(receipt(rows)[0])[0][above:-below]
    assert got == [("Coffee", 0, "left"), ("Visit us again", 0, "right"), ("Open daily", 0, "center"), ("Tomorrow", 0, "left"),
                   ("Closed Sunday", 0, "left")]


def written(rows_below):
    """A padded receipt whose last printed rows carry handwritten cells; (pieces, number of rows above them)."""
    rows, above, _ = padded([])
    rows = rows[:above] + rows_below
    return receipt(rows)[0], above


def cells_of(rows):
    return [[(cell.text, cell.handwritten) for cell in row.cells] for row in rows]


def test_handwriting_joins_the_row_it_is_written_on_as_its_own_cell():
    pieces, above = written([two("Bill", "52.76"), [Spec("Tip"), Spec("8.79", "right", handwritten=True)],
                             [Spec("Total"), Spec("61.55", "right", handwritten=True)]])
    built, _ = build_rows(pieces)
    assert cells_of(built)[above + 1:] == [[("Tip", False), ("8.79", True)], [("Total", False), ("61.55", True)]]
    # Written a little higher than the printed row: still on it.
    raised = [(text, [left, top - 6, right, bottom - 6] if hand else [left, top, right, bottom], hand) for text, (left, top, right, bottom), hand in pieces]
    assert cells_of(build_rows(raised)[0])[above + 1:] == [[("Tip", False), ("8.79", True)], [("Total", False), ("61.55", True)]]


def test_handwriting_touching_a_printed_word_is_still_its_own_cell():
    pieces, above = written([two("Bill", "52.76"), [Spec("Tip"), Spec("8.79", gap=3.5 * CHAR, handwritten=True)]])
    built, _ = build_rows(pieces)
    assert cells_of(built)[-1] == [("Tip", False), ("8.79", True)]


def test_handwriting_at_a_height_of_its_own_is_a_row_of_its_own():
    pieces, above = written([two("Bill", "52.76"), [Spec("Total", handwritten=True)]])
    pieces[-1] = (pieces[-1][0], [pieces[-1][1][0], pieces[-1][1][1] + 40, pieces[-1][1][2], pieces[-1][1][3] + 40], True)
    rows, _ = build_rows(pieces)
    assert cells_of(rows)[-2:] == [[("Bill", False), ("52.76", False)], [("Total", True)]]


def test_whole_row_pieces_still_form_the_right_rows():
    # A model that answers a whole row as one piece: nothing to split, and the 25th percentile still sets a sane unit.
    rows = [[Spec("Coffee 14.95")], [Spec("Bottled Water 3.95")], [Spec("Georgia Peach Stack 18.70")], [Spec("No Allergies", indent=1)], [Spec("Tax 3.91")],
            [Spec("Total 52.76")]]
    got, _ = rows_of(receipt(rows)[0])
    assert got == [("Coffee 14.95", 0, "left"), ("Bottled Water 3.95", 0, "left"), ("Georgia Peach Stack 18.70", 0, "left"),
                   ("No Allergies", 1, "left"), ("Tax 3.91", 0, "left"), ("Total 52.76", 0, "left")]


# Tilted and angled pages -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("caps", [False, True])
@pytest.mark.parametrize("degrees", [2.5, -2.5, 3, -3])
def test_a_tilted_receipt_gives_the_untilted_rows(degrees, caps):
    pieces, expected = breakfast(caps)
    assert rows_of(transform(pieces, tilt(degrees)))[0] == expected


@pytest.mark.parametrize("caps", [False, True])
def test_a_perspective_warp_keeps_its_rows_level(caps):
    pieces, expected = breakfast(caps)
    assert rows_of(transform(pieces, keystone()))[0] == expected


def test_a_tilted_receipt_with_handwriting_and_a_second_warp():
    rows, _, _ = padded([[Spec("Tip"), Spec("8.79", "right", handwritten=True)], [Spec("Total"), Spec("61.55", "right", handwritten=True)],
                         [Spec("Thank you", "center")], [Spec("Come again", "center")], [Spec("Server: Alex")]])
    pieces, expected = receipt(rows)
    for move in (tilt(2.5), tilt(-3), keystone()):
        assert rows_of(transform(pieces, move))[0] == expected


# Units ------------------------------------------------------------------------------------------------------------

def test_scaling_either_axis_or_a_0_to_1000_frame_gives_identical_rows():
    pieces, expected = breakfast()
    for sx, sy in ((1, 1), (2.0, 0.5), (0.3, 1.7), (1000 / 760, 1000 / 640)):
        assert rows_of(scale(pieces, sx, sy))[0] == expected, (sx, sy)
    tilted = transform(pieces, tilt(2.5))
    assert rows_of(scale(tilted, 1000 / 760, 1000 / 640))[0] == rows_of(tilted)[0] == expected


# No usable positions (SC-08) --------------------------------------------------------------------------------------

def test_one_zero_width_box_keeps_the_piece_after_the_one_before_it():
    pieces, expected = breakfast()
    broken = list(pieces)
    text, (left, top, _right, bottom), hand = broken[5]
    broken[5] = (text, [left, top, left, bottom], hand)
    rows, notes = build_rows(broken)
    assert notes == ["1 text pieces had no usable position; each was kept after the piece before it."]
    placed = [row for row in rows if row.cells[0].text == text]
    assert len(placed) == 1 and placed[0].indent is None and placed[0].align is None and placed[0].cells[0].box is None
    texts = [cell.text for row in rows for cell in row.cells]
    assert texts[texts.index(broken[4][0]) + 1] == text   # right after the piece answered before it
    assert sorted(texts) == sorted(piece[0] for piece in pieces)


def test_several_unusable_pieces_keep_the_answers_order():
    pieces, _ = breakfast()
    broken = list(pieces)
    for number in (5, 6, 9):   # two in a row, and one more later
        broken[number] = (pieces[number][0], None, False)
    rows, notes = build_rows(broken)
    texts = [cell.text for row in rows for cell in row.cells]
    assert notes == ["3 text pieces had no usable position; each was kept after the piece before it."]
    for number in (5, 6, 9):
        assert texts[texts.index(pieces[number - 1][0]) + 1] == pieces[number][0]


def test_unusable_pieces_after_pieces_of_one_row_keep_the_answers_order():
    pieces = [("A", [10, 10, 30, 30], False), ("x", None, False), ("B", [100, 10, 120, 30], False), ("y", None, False)]
    pieces += [(f"row {n}", [10, 10 + 40 * n, 70, 30 + 40 * n], False) for n in range(1, 8)]
    rows, _ = build_rows(pieces)
    assert [row.text for row in rows][:4] == ["A B", "x", "y", "row 1"]


def test_a_few_pieces_are_read_level():
    rows, _ = build_rows([("LOCAL TEST CAFE", [300, 30, 520, 54], False), ("14.95", [600, 90, 680, 114], False)])
    assert [row.text for row in rows] == ["LOCAL TEST CAFE", "14.95"]


@pytest.mark.parametrize("degrees", [0, 2.5, -2.5, 3, -3])
def test_a_two_row_receipt_tilted_a_little_is_still_two_rows(degrees):
    pieces, expected = receipt([two("Coffee", "$3.50"), two("Total", "$3.50")])
    assert len(pieces) == 4
    assert rows_of(transform(pieces, tilt(degrees, centre=(380, 90))))[0] == expected


def piece(text, left, top, right, bottom):
    return (text, [left, top, right, bottom], False)


def test_a_title_and_a_price_four_text_heights_below_are_not_one_tilted_row():
    """Four pieces: the title row has two, so one row could pair its price with almost any slope; no tilt is searched out of that."""
    pieces = [piece("CAFE", 40, 40, 72, 60), piece("MENU", 80, 40, 112, 60), piece("12.00", 680, 120, 720, 140), piece("THANKS", 350, 200, 398, 220)]
    assert [row.text for row in build_rows(pieces)[0]] == ["CAFE MENU", "12.00", "THANKS"]


def test_a_title_and_a_price_four_text_heights_above_are_not_one_tilted_row():
    pieces = [piece("12.00", 680, 40, 720, 60), piece("CAFE", 40, 120, 72, 140), piece("MENU", 80, 120, 112, 140), piece("THANKS", 350, 200, 398, 220)]
    assert [row.text for row in build_rows(pieces)[0]] == ["12.00", "CAFE MENU", "THANKS"]


def test_five_pieces_in_one_row_of_two_are_read_level():
    pieces = [piece("CAFE", 40, 40, 72, 60), piece("MENU", 80, 40, 112, 60), piece("12.00", 680, 120, 720, 140),
              piece("THANKS", 350, 200, 398, 220), piece("AGAIN", 410, 200, 450, 220)]
    assert [row.text for row in build_rows(pieces)[0]] == ["CAFE MENU", "12.00", "THANKS AGAIN"]


def test_one_main_row_followed_by_side_rows_leaves_the_side_rows_indented():
    """One row on the margin and ten on the first indent: the margin is the leftmost row's, however few rows sit on it."""
    got = rows_of(receipt([[Spec("Coffee")]] + [[Spec(f"Side {number}", indent=1)] for number in range(10)])[0])[0]
    assert [indent for _, indent, _ in got] == [0] + [1] * 10


def margin_rows(stray, handwritten=False):
    """Twelve item rows (name at x 52, amount at x 600), 30 apart, plus one stray piece."""
    pieces = []
    for number in range(12):
        top = 30 + 30 * number
        pieces += [(f"Item{number}", [52, top, 120, top + 20], False), (f"{number}.00", [600, top, 640, top + 20], False)]
    return pieces + [(stray, [12, 520, 12 + 15.6 * len(stray), 539], handwritten)]


@pytest.mark.parametrize("handwritten", [False, True])
def test_one_stray_short_box_left_of_the_margin_does_not_indent_every_main_row(handwritten):
    """A lone "x" in the margin, printed or handwritten, sets no margin: the twelve main rows stay at indent 0."""
    rows, _ = build_rows(margin_rows("x", handwritten))
    main = [row for row in rows if row.text.startswith("Item")]
    assert len(main) == 12 and [row.indent for row in main] == [0] * 12


def test_a_stray_handwritten_word_left_of_the_margin_does_not_set_it_however_long():
    rows, _ = build_rows(margin_rows("scribble", handwritten=True))
    assert [row.indent for row in rows if row.text.startswith("Item")] == [0] * 12


@pytest.mark.parametrize("note", ["a", "ok", "scribble", "see manager about this", "a note long enough to be a whole sentence of its own"])
@pytest.mark.parametrize("stray", ["x", "x2", "-"])
def test_a_handwritten_note_beside_a_short_stray_does_not_make_the_stray_a_margin(stray, note):
    """The stray's length is its printed cells', like its extent: a note on its row, of any length, changes no main row's indent."""
    pieces = margin_rows(stray) + [(note, [100, 520, 100 + 15.6 * len(note), 539], True)]
    rows, _ = build_rows(pieces)
    assert [row.indent for row in rows if row.text.startswith("Item")] == [0] * 12


def test_a_stray_row_that_is_not_short_still_sets_the_margin():
    """The remaining ambiguity: a printed word left of the margin cannot be told from a main row followed by deeper ones."""
    rows, _ = build_rows(margin_rows("Notes"))
    assert [row.indent for row in rows if row.text.startswith("Item")] == [1] * 12


def test_short_rows_starting_together_in_the_margin_still_set_it():
    pieces = [(f"{number}", [12, 520 + 30 * number, 20, 540 + 30 * number], False) for number in range(3)]
    rows, _ = build_rows(margin_rows("x")[:-1] + pieces)
    assert [row.indent for row in rows if row.text.startswith("Item")] == [1] * 12


def test_an_unusable_first_piece_comes_first():
    pieces, _ = breakfast()
    broken = [(pieces[0][0], None, False), *pieces[1:]]
    rows, notes = build_rows(broken)
    assert rows[0].text == pieces[0][0] and rows[0].indent is None and len(notes) == 1


@pytest.mark.parametrize("bad", [None, [1, 2, 3], [1, 2, 3, "x"], [0, 0, float("nan"), 5], [5, 5, 4, 9], [True, 0, 9, 9], "box", {"a": 1}, [0, 9, 9, 3]])
def test_every_kind_of_bad_box_is_unusable(bad):
    pieces = [("A", [0, 0, 10, 10], False), ("B", [0, 20, 10, 30], False), ("C", bad, False)]
    rows, notes = build_rows(pieces)
    assert [row.text for row in rows] == ["A", "B", "C"] and rows[2].indent is None and len(notes) == 1


def test_most_boxes_invalid_keeps_the_models_order_without_indent_or_align():
    pieces, _ = breakfast()
    broken = [(text, box if number % 3 == 0 else None, hand) for number, (text, box, hand) in enumerate(pieces)]
    rows, notes = build_rows(broken)
    assert notes == [NO_POSITION]
    assert [row.text for row in rows] == [piece[0] for piece in pieces]
    assert all(row.indent is None and row.align is None and len(row.cells) == 1 for row in rows)


def test_no_pieces_no_rows():
    assert build_rows([]) == ([], [])
