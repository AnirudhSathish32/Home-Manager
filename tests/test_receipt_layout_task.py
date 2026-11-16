"""The receipt_layout task and its grader (specs/receipt-layout-eval FR-10, FR-12 – FR-20; SC-01 – SC-07, SC-14 on the eval side).

Drawn synthetic receipts and the fake model server only; every count is checked, never a wall time."""

import copy
import random

import pytest

from evals.layout_grading import Aligner, grade_reading, normalize, parse_amounts, split_cells
from evals.tasks import TASKS
from evals.tasks.runner import run_one
from home_manager.documents.vision_layout import build_rows
from home_manager.models.vision import reading_format
from model_server import layout_text_answer, spans_answer, v6_answer, vision_answer
from test_eval_tasks import oracle

MODULE = TASKS["receipt_layout"]
FORMATS = ["v7-lines", "v6-text", "layout-text", "spans"]
CASES = MODULE.cases()


def case_of(family, condition, index=0):
    return next(case for case in CASES if case["input"] == {"family": family, "condition": condition, "index": index})


DINING = case_of("dining", "clean")
ROWS = DINING["expected"]["rows"]


def texts(rows):
    return [" ".join(cell["text"] for cell in row["cells"]) for row in rows]


def v7(rows=ROWS, lines=None, indents=None):
    """A v7-shaped reading of the rows, with its lines (and indents) replaced when given."""
    lines = texts(rows) if lines is None else lines
    indents = [row["indent"] for row in rows] if indents is None else indents
    return {"format": "v7-lines", "lines": [[text, indent] for text, indent in zip(lines, indents)], "rows": [], "spans": []}


def grade(output, case=DINING):
    return grade_reading(case["expected"], output)


def index_of(text):
    return texts(ROWS).index(text)


def exact(case, name):
    """The fake server's answer for a case's exact rows, in each format's shape."""
    rows = case["expected"]["rows"]
    if name == "v7-lines":
        return vision_answer(texts(rows), [row["indent"] for row in rows])
    if name == "v6-text":
        return v6_answer(texts(rows))
    if name == "layout-text":
        return layout_text_answer([(row["indent"], [cell["text"] for cell in row["cells"]]) for row in rows])
    return spans_answer([(cell["text"], cell["box"], cell["handwritten"]) for row in rows for cell in row["cells"]])


# Grader units ---------------------------------------------------------------------------------------------------------------------

def test_a_perfect_reading_has_every_count_perfect():
    counts = grade(oracle("receipt_layout", DINING))
    assert (counts["rows"], counts["whole"]) == (28, 28)
    assert counts["split"] == counts["merged"] == counts["missing"] == counts["extra"] == counts["out_of_order"] == 0
    assert (counts["amounts"], counts["amounts_read"], counts["amounts_on_row"]) == (18, 18, 18)
    assert counts["amounts_wrong"] == counts["amounts_missing"] == 0 and counts["cer"] == 0 and counts["evaluations"] == 0
    assert (counts["cell_rows_match"], counts["align_right"], counts["handwritten_correct"]) == (28, 28, 2)
    assert (counts["usable_share"], counts["overlap"]) == (1.0, 1.0)


def test_a_price_on_its_own_line_is_one_split_row_with_the_amount_read_but_not_on_its_row():
    """SC-02."""
    at = index_of("Bottled Water $3.95")
    lines = texts(ROWS)
    lines[at:at + 1] = ["Bottled Water", "$3.95"]
    indents = [row["indent"] for row in ROWS]
    indents[at:at + 1] = [0, 0]
    counts = grade(v7(lines=lines, indents=indents))
    assert (counts["split"], counts["merged"], counts["missing"], counts["extra"]) == (1, 0, 0, 0)
    assert counts["whole"] == 27 and counts["amounts_read"] == 18 and counts["amounts_on_row"] == 17 and counts["amounts_wrong"] == 0
    graded = MODULE.grade(DINING, v7(lines=lines, indents=indents))
    assert not graded["passed"] and not graded["checks"]["no_split_rows"] and not graded["checks"]["amounts_on_their_rows"]
    assert graded["checks"]["no_merged_rows"] and graded["checks"]["no_missing_rows"] and graded["checks"]["indents_right"]


def test_a_price_after_a_side_line_is_one_split_row_and_no_extra_line():
    at = index_of("Georgia Peach Stack $18.70")
    lines = texts(ROWS)
    lines[at:at + 2] = ["Georgia Peach Stack", "No Allergies", "$18.70"]
    indents = [row["indent"] for row in ROWS]
    indents[at:at + 2] = [0, 1, 0]
    counts = grade(v7(lines=lines, indents=indents))
    assert (counts["split"], counts["merged"], counts["missing"], counts["extra"]) == (1, 0, 0, 0)
    assert counts["amounts_read"] == 18 and counts["amounts_on_row"] == 17 and counts["rows"] == 28
    assert counts["indented_right"] == counts["indented_rows"] - 0 and counts["indented_wrong"] == 0  # The side line itself is still right.


def test_two_rows_on_one_line_are_one_merged_row():
    """SC-03."""
    at = index_of("Subtotal: $48.85")
    lines = texts(ROWS)
    lines[at:at + 2] = [lines[at] + " " + lines[at + 1]]
    indents = [row["indent"] for row in ROWS]
    indents[at:at + 2] = [0]
    counts = grade(v7(lines=lines, indents=indents))
    assert (counts["merged"], counts["split"], counts["missing"], counts["extra"]) == (1, 0, 0, 0)
    assert (counts["whole"], counts["rows"]) == (26, 28)  # Rows alone on a line of their own: the two that share a line are not whole.
    assert not MODULE.grade(DINING, v7(lines=lines, indents=indents))["passed"]


def test_a_misread_amount_keeps_its_row_whole_and_counts_one_wrong_amount():
    """SC-04: 49.85 for 48.85."""
    lines = [line.replace("48.85", "49.85") for line in texts(ROWS)]
    counts = grade(v7(lines=lines))
    assert (counts["whole"], counts["split"], counts["merged"], counts["missing"], counts["extra"]) == (28, 0, 0, 0, 0)
    assert (counts["amounts_wrong"], counts["amounts_missing"], counts["amounts_read"], counts["amounts_on_row"]) == (1, 0, 17, 17)
    assert counts["cer"] > 0
    graded = MODULE.grade(DINING, v7(lines=lines))
    assert not graded["passed"] and graded["checks"]["no_split_rows"] and not graded["checks"]["amounts_on_their_rows"]


def test_a_side_line_read_at_indent_zero_is_one_wrong_indented_row():
    """SC-05."""
    indents = [row["indent"] for row in ROWS]
    indents[index_of("No Allergies")] = 0
    counts = grade(v7(indents=indents))
    assert (counts["indented_rows"], counts["indented_right"], counts["indented_wrong"], counts["indented_unknown"]) == (5, 4, 1, 0)
    assert (counts["edge_rows"], counts["edge_right"], counts["edge_wrong"]) == (23, 23, 0)
    graded = MODULE.grade(DINING, v7(indents=indents))
    assert not graded["passed"] and not graded["checks"]["indents_right"] and graded["checks"]["no_split_rows"]


def test_a_format_that_reports_no_indent_shows_not_reported():
    counts = grade({**v7(indents=[None] * len(ROWS)), "format": "v6-text"})
    assert counts["indent_reported"] is False and counts["indented_rows"] == counts["edge_rows"] == 0 and counts["whole"] == 28
    graded = MODULE.grade(DINING, {**v7(indents=[None] * len(ROWS)), "format": "v6-text"})
    assert graded["passed"] and graded["checks"]["indent_share"] is None and graded["score"] == 1.0


def test_an_unknown_indent_is_reported_apart_and_fails_the_case():
    indents = [row["indent"] for row in ROWS]
    indents[index_of("No Allergies")] = None
    counts = grade(v7(indents=indents))
    assert counts["indented_unknown"] == 1 and counts["indented_wrong"] == 0
    assert not MODULE.grade(DINING, v7(indents=indents))["passed"]


def test_rows_out_of_order_are_counted_and_not_missing():
    lines, indents = texts(ROWS), [row["indent"] for row in ROWS]
    lines[2], lines[20] = lines[20], lines[2]
    indents[2], indents[20] = indents[20], indents[2]
    counts = grade(v7(lines=lines, indents=indents))
    assert counts["out_of_order"] >= 1 and counts["missing"] == 0 and counts["extra"] == 0 and counts["split"] == counts["merged"] == 0
    assert counts["amounts_on_row"] == counts["amounts"]


def test_extra_lines_and_missing_rows_are_counted():
    lines, indents = texts(ROWS), [row["indent"] for row in ROWS]
    del lines[7], indents[7]
    lines += ["THANK YOU", "Visit us at the cafe"]
    indents += [0, 0]
    counts = grade(v7(lines=lines, indents=indents))
    assert (counts["missing"], counts["extra"], counts["split"], counts["merged"]) == (1, 2, 0, 0)
    assert (counts["amounts"], counts["amounts_read"], counts["amounts_missing"], counts["amounts_wrong"]) == (18, 17, 1, 0)  # 3.95 is printed twice; one copy is read.


def table(*prices):
    """A tiny expected case: one row per (name, price), each alone on its line."""
    rows = [{"cells": [{"text": f"{name} ${price}", "handwritten": False}], "indent": 0, "align": "left"} for name, price in prices]
    return {"rows": rows}


def test_an_amount_read_exactly_on_another_rows_line_is_not_taken_as_that_rows_wrong_digits():
    """Apple $1.00 and Coffee $2.00 read as $2.00 and $3.00: the $2.00 is Coffee's, read exactly elsewhere, so Apple's line has no spare to call wrong."""
    expected = table(("Apple", "1.00"), ("Coffee", "2.00"))
    counts = grade_reading(expected, {"format": "v7-lines", "lines": [["Apple $2.00", 0], ["Coffee $3.00", 0]]})
    assert (counts["amounts"], counts["amounts_read"], counts["amounts_on_row"], counts["amounts_wrong"], counts["amounts_missing"]) == (2, 1, 0, 0, 1)
    # A wrong digit still counts as wrong when nothing else reads the row's price exactly.
    counts = grade_reading(expected, {"format": "v7-lines", "lines": [["Apple $1.50", 0], ["Coffee $2.00", 0]]})
    assert (counts["amounts_read"], counts["amounts_on_row"], counts["amounts_wrong"], counts["amounts_missing"]) == (1, 1, 1, 0)


def test_spaces_tabs_and_pipes_count_as_one_space():
    assert normalize("Coffee\t |  $14.95 ") == normalize("coffee $14.95") == "coffee $14.95"
    assert split_cells("Qty | Item\tPrice") == ["qty", "item", "price"]
    lines = [text.replace(" $", "\t$").replace("  ", " ") for text in texts(ROWS)]
    assert grade(v7(lines=lines))["whole"] == 28


def test_one_missed_handwritten_flag_lowers_recall_only():
    """FR-16."""
    output = oracle("receipt_layout", DINING)
    output["rows"][-6]["cells"][1] = {**output["rows"][-6]["cells"][1], "handwritten": False}
    counts = grade(output)
    assert (counts["handwritten_expected"], counts["handwritten_reported"], counts["handwritten_correct"]) == (2, 1, 1)
    assert counts["whole"] == 28 and counts["cell_rows_match"] == 28 and counts["align_right"] == 28
    graded = MODULE.grade(DINING, output)
    assert graded["passed"] and graded["checks"]["handwritten_correct"] == 1


def test_exact_boxes_scaled_per_axis_overlap_fully_and_shifted_boxes_overlap_less():
    """FR-17, SC-07."""
    output = oracle("receipt_layout", DINING)
    width, height = DINING["expected"]["size"]
    scaled = copy.deepcopy(output)
    for entry in (*scaled["spans"], *(cell for row in scaled["rows"] for cell in row["cells"])):
        left, top, right, bottom = entry["box"]
        entry["box"] = [left * 1000 / width, top * 1000 / height, right * 1000 / width, bottom * 1000 / height]
    assert grade(scaled)["overlap"] == 1.0
    shifted = copy.deepcopy(output)
    for entry in (*shifted["spans"], *(cell for row in shifted["rows"] for cell in row["cells"])):
        entry["box"] = [entry["box"][0] + 25, entry["box"][1] + 9, entry["box"][2] + 25, entry["box"][3] + 9]
    assert grade(shifted)["overlap"] < 0.9
    unusable = copy.deepcopy(output)
    for entry in unusable["spans"][:4]:
        entry["box"] = [5, 5, 5, 9]
    assert grade(unusable)["usable_share"] == round(1 - 4 / len(unusable["spans"]), 4)


def test_a_layout_text_table_row_written_with_pipes_grades_its_cells_right():
    case = case_of("itemized", "clean")
    rows = case["expected"]["rows"]
    row = next(row for row in rows if len(row["cells"]) >= 3)
    piped = [{"cells": [{"text": " | ".join(cell["text"] for cell in other["cells"]), "box": None, "handwritten": False}], "align": None}
             if other is row else {"cells": [{"text": cell["text"], "box": None, "handwritten": False} for cell in other["cells"]], "align": None}
             for other in rows]
    output = {"format": "layout-text", "lines": [[" ".join(cell["text"] for cell in other["cells"]), other["indent"]] for other in rows],
              "rows": piped, "spans": []}
    counts = grade(output, case)
    assert counts["cells_reported"] and counts["cell_rows_match"] == counts["cell_rows"] == len(rows)


def test_a_format_that_reports_indents_but_lost_them_all_does_not_pass():
    """Spans with every box unusable: no row has an indent, which is unknown (never "not reported") and fails the case."""
    rows = ROWS
    pieces = [(cell["text"], [0, 0, 0, 0], cell["handwritten"]) for row in rows for cell in row["cells"]]
    built, _ = build_rows(pieces)
    output = {"format": "spans", "lines": [[row.text, row.indent] for row in built],
              "rows": [{"cells": [{"text": cell.text, "box": cell.box, "handwritten": cell.handwritten} for cell in row.cells], "align": row.align} for row in built],
              "spans": [{"text": text, "box": box, "handwritten": hw} for text, box, hw in pieces]}
    assert all(row.indent is None for row in built)
    counts = grade(output)
    assert counts["indent_reported"] is True and counts["indented_unknown"] + counts["edge_unknown"] == counts["whole"] > 0
    graded = MODULE.grade(DINING, output)
    assert not graded["passed"] and not graded["checks"]["indents_right"]
    assert grade(v7(indents=[None] * len(ROWS)))["indent_reported"] is True
    assert grade({**v7(indents=[None] * len(ROWS)), "format": "v6-text"})["indent_reported"] is False


def deleting(case, at):
    rows = case["expected"]["rows"]
    lines = [[text, row["indent"]] for k, (text, row) in enumerate(zip(texts(rows), rows)) if k != at]
    return grade_reading(case["expected"], {"format": "v7-lines", "lines": lines})


def test_a_deleted_short_row_is_missing_and_never_merged_into_its_neighbour():
    counts = deleting(DINING, index_of("14 Orchard Row"))
    assert (counts["missing"], counts["merged"], counts["split"], counts["extra"]) == (1, 0, 0, 0)


@pytest.mark.parametrize("case", CASES, ids=lambda case: "/".join(map(str, case["input"].values())))
def test_deleting_any_one_row_counts_one_missing_row_and_nothing_else(case):
    for at in range(len(case["expected"]["rows"])):
        counts = deleting(case, at)
        assert (counts["missing"], counts["merged"], counts["split"], counts["extra"]) == (1, 0, 0, 0), (case["input"], at)


@pytest.mark.parametrize("case", CASES, ids=lambda case: "/".join(map(str, case["input"].values())))
def test_splitting_any_multi_cell_row_into_its_cells_counts_one_split_row_and_nothing_else(case):
    """Dining's suggested-tip rows have four cells: splits go up to the most cells a row has (MOST_PIECES is 4 at least)."""
    rows = case["expected"]["rows"]
    for at, row in enumerate(rows):
        if len(row["cells"]) < 2:
            continue
        lines = [[text, other["indent"]] for text, other in zip(texts(rows), rows)]
        lines[at:at + 1] = [[cell["text"], row["indent"]] for cell in row["cells"]]
        counts = grade_reading(case["expected"], {"format": "v7-lines", "lines": lines})
        assert (counts["split"], counts["missing"], counts["extra"], counts["merged"]) == (1, 0, 0, 0), (case["input"], at)


def miswritten(text):
    """text with one character substituted: the first that is neither a digit nor a space, else the last digit; one or two characters stay as they are."""
    if len(text) <= 2:
        return text
    at = next((k for k, char in enumerate(text) if not char.isdigit() and char != " "), len(text) - 1)
    other = str((int(text[at]) + 1) % 10) if text[at].isdigit() else "z" if text[at] != "z" else "y"
    return text[:at] + other + text[at + 1:]


def row_of(*cells):
    return {"cells": [{"text": cell, "box": None, "handwritten": False} for cell in cells], "indent": 0, "align": "left", "amounts": []}


def graded_lines(rows, lines):
    counts = grade_reading({"rows": rows}, {"format": "v6-text", "lines": [[line, None] for line in lines]})
    return counts["whole"], counts["split"], counts["merged"], counts["missing"], counts["extra"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: "/".join(map(str, case["input"].values())))
def test_splitting_any_multi_cell_row_into_misread_cells_is_still_one_split_row(case):
    """Each piece of a split row gets one substituted character (not a digit where it can be avoided): the pieces are still found in order."""
    rows = case["expected"]["rows"]
    for at, row in enumerate(rows):
        if len(row["cells"]) < 2:
            continue
        lines = [[text, other["indent"]] for text, other in zip(texts(rows), rows)]
        lines[at:at + 1] = [[miswritten(cell["text"]), row["indent"]] for cell in row["cells"]]
        counts = grade_reading(case["expected"], {"format": "v7-lines", "lines": lines})
        assert (counts["split"], counts["missing"], counts["extra"], counts["merged"]) == (1, 0, 0, 0), (case["input"], at, lines[at:at + len(row["cells"])])


@pytest.mark.parametrize("case", CASES, ids=lambda case: "/".join(map(str, case["input"].values())))
def test_deleting_a_row_whose_text_is_inside_another_row_counts_it_missing_and_never_merged(case):
    """Repeated words: a heading "Tea" and a row "Green Tea $3.95" on one line must not make the heading merged."""
    rows = case["expected"]["rows"]
    inside = [at for at, text in enumerate(texts(rows)) if any(normalize(text) in normalize(other) for k, other in enumerate(texts(rows)) if k != at)]
    for at in inside:
        counts = deleting(case, at)
        assert (counts["missing"], counts["merged"], counts["split"], counts["extra"]) == (1, 0, 0, 0), (case["input"], at)


def test_a_misread_split_row_is_still_one_split_row_and_not_two_whole_ones():
    """Reviewer's examples: a three-character piece with one wrong character, a price with one wrong digit-like character."""
    rows = [row_of("Tea", "$3.95"), row_of("Coffee", "$2.50")]
    assert graded_lines(rows, ["Tee", "$3.95", "Coffee $2.50"]) == (1, 1, 0, 0, 0)
    assert graded_lines(rows, ["Tee", "$3.9S", "Coffee $2.50"]) == (1, 1, 0, 0, 0)
    assert graded_lines(rows, ["Tea", "$3.9S", "Coffee $2.50"]) == (1, 1, 0, 0, 0)


def test_a_heading_deleted_before_a_row_that_repeats_it_is_missing_and_never_merged():
    rows = [row_of("Tea"), row_of("Green Tea", "$3.95")]
    assert graded_lines(rows, ["Green Tea $3.95"]) == (1, 0, 0, 1, 0)
    assert graded_lines(rows, ["Tea", "Green Tea $3.95"]) == (2, 0, 0, 0, 0)
    assert graded_lines(rows, ["Tea Green Tea $3.95"]) == (0, 0, 1, 0, 0)   # both really on one line, in order: merged


def later_twin(pieces, at):
    """Piece at, misread by one substitution so that it reads exactly like the start of a later piece, when some later piece allows that."""
    text = normalize(pieces[at])
    for later in pieces[at + 1:]:
        for start in range(len(normalize(later)) - len(text) + 1):
            window = normalize(later)[start:start + len(text)]
            if len(text) > 2 and sum(a != b for a, b in zip(window, text)) == 1:
                return window
    return None


@pytest.mark.parametrize("case", CASES, ids=lambda case: "/".join(map(str, case["input"].values())))
def test_a_split_row_whose_misread_piece_reads_like_a_later_piece_is_still_one_split_row(case):
    """Adversarial duplicates: the misread piece also occurs exactly later in the row, where a first match would take it and strand the rest."""
    rows = case["expected"]["rows"]
    for at, row in enumerate(rows):
        cells = [cell["text"] for cell in row["cells"]]
        for piece in range(len(cells) - 1):
            twin = later_twin(cells, piece)
            if twin is None:
                continue
            lines = [[text, other["indent"]] for text, other in zip(texts(rows), rows)]
            lines[at:at + 1] = [[twin if k == piece else cell, row["indent"]] for k, cell in enumerate(cells)]
            counts = grade_reading(case["expected"], {"format": "v7-lines", "lines": lines})
            assert (counts["split"], counts["missing"], counts["extra"], counts["merged"]) == (1, 0, 0, 0), (case["input"], at, piece)


def test_a_split_row_with_a_misread_piece_that_reads_exactly_later_is_one_split_row():
    """Reviewer's example: "Tea" misread "Sea" is also the start of the next cell."""
    assert graded_lines([row_of("Tea", "Sea $3.95")], ["Sea", "Sea $3.95"]) == (0, 1, 0, 0, 0)
    assert graded_lines([row_of("Tea", "Sea $3.95")], ["Tea", "Sea $3.95"]) == (0, 1, 0, 0, 0)
    assert graded_lines([row_of("Sea", "Sea", "$3.95")], ["Tea", "Sea", "$3.95"]) == (0, 1, 0, 0, 0)
    assert graded_lines([row_of("Tea", "Tea", "Sea $3.95")], ["Sea", "Sea", "Sea $3.95"]) == (0, 1, 0, 0, 0)


def test_a_merged_row_with_a_truncated_piece_is_one_merged_row_and_not_a_missing_one():
    """Reviewer's example: "Baguette" read "Baguet" before the next row's "X" on the same line."""
    assert graded_lines([row_of("Baguette"), row_of("X")], ["Baguet X"]) == (0, 0, 1, 0, 0)
    assert graded_lines([row_of("Baguette"), row_of("X")], ["Baguette X"]) == (0, 0, 1, 0, 0)
    assert graded_lines([row_of("Baguette"), row_of("X")], ["Baguet"]) == (1, 0, 0, 1, 0)   # no "X" anywhere: it is missing


def test_a_misread_split_piece_that_reads_exactly_inside_a_later_one_takes_its_own_place():
    """Reviewer's example, itemized/angled row 10: "9", "Duct Tape", "5.75", "51.75" with the price misread "1.75", which is inside the total."""
    row = row_of("9", "Duct Tape", "5.75", "51.75")
    assert graded_lines([row], ["9", "Duct Tape", "1.75", "51.75"]) == (0, 1, 0, 0, 0)
    assert graded_lines([row], ["9", "Duct Tape", "5.75", "5.75"]) == (0, 1, 0, 0, 0)
    assert graded_lines([row], ["9", "Duct Tape", "5.75", "51.7"]) == (0, 1, 0, 0, 0)
    case = case_of("itemized", "angled", 1)
    rows = case["expected"]["rows"]
    at = texts(rows).index("9 Duct Tape 5.75 51.75")
    lines = [[text, other["indent"]] for text, other in zip(texts(rows), rows)]
    lines[at:at + 1] = [[text, rows[at]["indent"]] for text in ("9", "duct tape", "1.75", "51.75")]
    counts = grade_reading(case["expected"], {"format": "v7-lines", "lines": lines})
    assert (counts["split"], counts["missing"], counts["extra"], counts["merged"]) == (1, 0, 0, 0)


def test_random_misread_splits_and_merges_of_repeated_words_are_never_mistaken_for_missing_or_extra():
    """Seeded fuzz over a small vocabulary full of repeats: every piece of three or more characters has one substitution."""
    rng = random.Random(8)
    words = ["Tea", "Sea", "Tee", "Iced Tea", "Tea with lemon", "Green Tea", "$3.95", "3.95", "Latte", "Late", "Total", "Tota"]
    for _ in range(400):
        cells = [rng.choice(words) for _ in range(rng.randint(2, 4))]
        # Pieces that read like another piece's misreading are ambiguous by construction: only those apart by more than one edit are asked about.
        if any(normalize(a) != normalize(b) and Aligner().lev(normalize(a), normalize(b)) <= 1 for a in cells for b in cells):
            continue
        lines = [miswritten(cell) if rng.random() < 0.7 else cell for cell in cells]
        assert graded_lines([row_of(*cells)], lines) == (0, 1, 0, 0, 0), (cells, lines)
        assert graded_lines([row_of(cells[0]), row_of(*cells[1:])], [" ".join([lines[0], *lines[1:]])]) == (0, 0, 1, 0, 0), (cells, lines)


def test_a_row_deleted_before_a_row_that_repeats_it_is_missing_in_every_position_of_the_repeat():
    """Reviewer's example and its prefix, suffix and middle variants: the deleted row's text is in the next row, which takes the whole line."""
    heading = row_of("Tea")
    for second in (("Tea with lemon", "$3.95"), ("Iced Tea", "$3.95"), ("Green Tea Large", "$3.95"), ("Tea", "$3.95"), ("Sweet Tea",), ("Tea Tea", "$1.00")):
        line = " ".join(second)
        assert graded_lines([heading, row_of(*second)], [line]) == (1, 0, 0, 1, 0), second
        assert graded_lines([heading, row_of(*second)], ["Tea", line]) == (2, 0, 0, 0, 0), second
        assert graded_lines([heading, row_of(*second)], [f"Tea {line}"]) == (0, 0, 1, 0, 0), second   # both really there on one line: merged


def test_a_line_deleted_after_a_split_pieces_that_repeats_it_is_extra_not_a_split():
    """The mirror: a row of two cells, and a line that repeats its first cell with nothing of the second."""
    assert graded_lines([row_of("Tea with lemon $3.95")], ["Tea with lemon $3.95", "Tea"]) == (1, 0, 0, 0, 1)
    assert graded_lines([row_of("Tea with lemon $3.95")], ["Tea", "Tea with lemon $3.95"]) == (1, 0, 0, 0, 1)


def prefix_pairs(case):
    """Each adjacent pair of rows made synthetic: the first row's text is a prefix of the second's."""
    rows = case["expected"]["rows"]
    for first, second in zip(rows, rows[1:]):
        head = " ".join(cell["text"] for cell in first["cells"])
        yield row_of(head), row_of(f"{head} {second['cells'][0]['text']}", *[cell["text"] for cell in second["cells"][1:]])


@pytest.mark.parametrize("case", CASES, ids=lambda case: "/".join(map(str, case["input"].values())))
def test_deleting_a_row_that_is_a_prefix_of_the_next_is_missing_and_never_merged_but_really_sharing_a_line_is_merged(case):
    for first, second in prefix_pairs(case):
        line = " ".join(cell["text"] for cell in second["cells"])
        head = first["cells"][0]["text"]
        assert graded_lines([first, second], [line]) == (1, 0, 0, 1, 0), (head, line)
        assert graded_lines([first, second], [f"{head} {line}"]) == (0, 0, 1, 0, 0), (head, line)


def test_split_pieces_and_merged_rows_may_not_share_characters():
    rows = [row_of("Tea", "Tea")]
    assert graded_lines(rows, ["Tea", "Tea"]) == (0, 1, 0, 0, 0)
    assert graded_lines([row_of("Tea", "Tea", "$3.95")], ["Tea", "Tea", "$3.95"]) == (0, 1, 0, 0, 0)
    assert graded_lines([row_of("Tea", "$3.95")], ["Tea", "Tea"]) == (0, 0, 0, 1, 2)   # the second line holds none of the price
    assert graded_lines([row_of("Tea"), row_of("Tea")], ["Tea"]) == (1, 0, 0, 1, 0)    # one printed "Tea" cannot be two rows


def test_a_row_of_four_cells_split_into_its_four_cells_is_one_split_row():
    at = index_of("18.00% of sale: $8.79 Total $61.55")
    cells = [cell["text"] for cell in ROWS[at]["cells"]]
    assert len(cells) == 4
    counts = grade(v7(lines=texts(ROWS)[:at] + cells + texts(ROWS)[at + 1:], indents=[row["indent"] for row in ROWS[:at]] + [0] * 4 + [row["indent"] for row in ROWS[at + 1:]]))
    assert (counts["split"], counts["missing"], counts["extra"], counts["merged"]) == (1, 0, 0, 0)


def test_the_amount_rule_is_one_definition():
    from evals import receipt_layouts
    assert receipt_layouts.parse_amounts is parse_amounts
    assert parse_amounts("18.00% of sale: $8.79 Total $61.55") == [879, 6155] and parse_amounts("0.40-") == [-40]


def test_the_alignment_cost_is_bounded_by_the_count_not_the_clock():
    """P8: a 90-row case needs at most 1,000 edit-distance evaluations on a perfect answer and 60,000 on a fully split one."""
    case = next(case for case in CASES if case["input"]["family"] == "long")
    rows = case["expected"]["rows"]
    assert len(rows) >= 90
    perfect = grade_reading(case["expected"], {"format": "v7-lines", "lines": [[text, row["indent"]] for text, row in zip(texts(rows), rows)]})
    assert perfect["whole"] == len(rows) and perfect["evaluations"] <= 1000
    halves = []
    for row in rows:
        text = " ".join(cell["text"] for cell in row["cells"])
        cut = len(row["cells"][0]["text"]) if len(row["cells"]) > 1 else len(text) // 2
        halves += [[text[:cut].strip() or text, row["indent"]], [text[cut:].strip() or text, row["indent"]]]
    split = grade_reading(case["expected"], {"format": "v7-lines", "lines": halves})
    assert split["evaluations"] <= 60000 and split["split"] >= len(rows) * 0.8


# The row builder on the drawn boxes (FR-10, SC-06, SC-07) ------------------------------------------------------------------------------

def pieces_of(case, shuffle=None, scale=(1, 1)):
    pieces = [(cell["text"], [cell["box"][0] * scale[0], cell["box"][1] * scale[1], cell["box"][2] * scale[0], cell["box"][3] * scale[1]],
               cell["handwritten"]) for row in case["expected"]["rows"] for cell in row["cells"]]
    if shuffle is not None:
        random.Random(shuffle).shuffle(pieces)
    return pieces


def built_matches(rows, case):
    expected = case["expected"]["rows"]
    assert [[cell.text for cell in row.cells] for row in rows] == [[cell["text"] for cell in row["cells"]] for row in expected], case["input"]
    assert [row.indent for row in rows] == [row["indent"] for row in expected], case["input"]
    assert [row.align for row in rows] == [row["align"] for row in expected], case["input"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: "/".join(map(str, case["input"].values())))
def test_the_row_builder_reproduces_every_drawn_case_from_its_exact_boxes(case):
    rows, notes = build_rows(pieces_of(case, shuffle=case["id"]))
    assert notes == []
    built_matches(rows, case)
    width, height = case["expected"]["size"]  # Any frame, each axis scaled differently, builds the same rows.
    scaled_rows, scaled_notes = build_rows(pieces_of(case, shuffle=case["id"], scale=(1000 / width, 1000 / height)))
    assert scaled_notes == []
    built_matches(scaled_rows, case)


def test_scaled_pieces_diagnose_with_full_overlap():
    """SC-07: the SC-06 pieces in a 0-1000 frame, run through the grader."""
    case = case_of("dining", "tilted", 2)
    width, height = case["expected"]["size"]
    rows, _ = build_rows(pieces_of(case, scale=(1000 / width, 1000 / height)))
    output = {"format": "spans", "lines": [[row.text, row.indent] for row in rows],
              "rows": [{"cells": [{"text": cell.text, "box": list(cell.box), "handwritten": cell.handwritten} for cell in row.cells], "align": row.align}
                       for row in rows],
              "spans": [{"text": text, "box": box, "handwritten": hw} for text, box, hw in pieces_of(case, scale=(1000 / width, 1000 / height))]}
    counts = grade(output, case)
    assert counts["whole"] == counts["rows"] and counts["overlap"] == 1.0 and counts["usable_share"] == 1.0


# The task through the fake model server (SC-01, SC-14, FR-12, FR-18) ------------------------------------------------------------------

@pytest.mark.parametrize("name", FORMATS)
def test_the_exact_rows_in_each_formats_shape_pass_with_every_count_perfect(local_model, name):
    """SC-01."""
    local_model["output"] = exact(DINING, name)
    with reading_format(name):
        line = run_one(MODULE, DINING, local_model["config"])
    checks = line["grades"]["checks"]
    assert line["status"] == "ok" and line["grades"]["passed"] and line["grades"]["score"] == 1.0, checks
    assert line["output"]["format"] == name and line["first_try_valid"] is True
    assert (checks["whole"], checks["split"], checks["merged"], checks["missing"], checks["extra"], checks["out_of_order"]) == (28, 0, 0, 0, 0, 0)
    assert checks["amounts_on_row"] == checks["amounts_read"] == checks["amounts"] == 18 and checks["amounts_wrong"] == checks["amounts_missing"] == 0
    assert checks["cer"] == 0
    assert checks["output_characters"] == len(line["output"]["text"]) > 0  # FR-18: as the transcription task counts it.
    assert checks["indent_reported"] is (name != "v6-text")
    assert (checks["indented_right"], checks["edge_right"]) == ((5, 23) if name != "v6-text" else (0, 0))
    assert checks["cells_reported"] is (name in ("layout-text", "spans")) and checks["position_reported"] is (name == "spans")
    if name in ("layout-text", "spans"):
        assert checks["cell_rows_match"] == checks["cell_rows"] == 28
    if name == "spans":
        assert (checks["align_right"], checks["handwritten_correct"], checks["usable_share"], checks["overlap"]) == (28, 2, 1.0, 1.0)


def test_v7_shaped_wrong_answers_through_the_task_count_exactly_what_is_wrong(local_model):
    """SC-02 – SC-05 end to end on the v7 format."""
    lines, indents = texts(ROWS), [row["indent"] for row in ROWS]
    at = index_of("Bottled Water $3.95")
    split_lines, split_indents = lines[:at] + ["Bottled Water", "$3.95"] + lines[at + 1:], indents[:at] + [0, 0] + indents[at + 1:]
    local_model["output"] = vision_answer(split_lines, split_indents)
    line = run_one(MODULE, DINING, local_model["config"])
    assert (line["grades"]["checks"]["split"], line["grades"]["passed"]) == (1, False)
    local_model["output"] = vision_answer([text.replace("48.85", "49.85") for text in lines], indents)
    checks = run_one(MODULE, DINING, local_model["config"])["grades"]["checks"]
    assert (checks["whole"], checks["amounts_wrong"]) == (28, 1) and checks["cer"] > 0


@pytest.mark.parametrize("name", FORMATS)
def test_a_truncated_main_call_is_the_failure_kind_truncated(local_model, name):
    """FR-12, FR-18: out of tokens at 8,192 and again at 16,384."""
    local_model["output"] = exact(DINING, name)
    local_model["finish_reasons"] = ["length", "length"]
    with reading_format(name):
        line = run_one(MODULE, DINING, local_model["config"])
    assert (line["status"], line["failure"], line["attempts"]["calls"], line["attempts"]["failed"]) == ("failed", "truncated", 2, 2)
    assert line["grades"]["passed"] is False


@pytest.mark.parametrize("name", FORMATS)
def test_a_rescue_that_runs_out_is_truncated_too(local_model, name):
    local_model["outputs"] = [{"nope": 1}]
    local_model["output"] = exact(DINING, name)
    local_model["finish_reasons"] = ["stop", "length", "length"]
    with reading_format(name):
        line = run_one(MODULE, DINING, local_model["config"])
    assert (line["status"], line["failure"], line["attempts"]["calls"]) == ("failed", "truncated", 3)
    assert "after a text-only retry" in line["error"]


@pytest.mark.parametrize("name", FORMATS)
def test_a_budget_retry_that_succeeds_is_a_read_case_not_a_truncation(local_model, name):
    local_model["output"] = exact(DINING, name)
    local_model["finish_reasons"] = ["length", "stop"]
    with reading_format(name):
        line = run_one(MODULE, DINING, local_model["config"])
    assert line["status"] == "ok" and line["failure"] is None and (line["attempts"]["calls"], line["attempts"]["failed"]) == (2, 1)


@pytest.mark.parametrize("name", FORMATS)
def test_a_blank_answer_fails_as_blank(local_model, name):
    """SC-14, the blank half."""
    local_model["output"] = {"v7-lines": vision_answer([""]), "v6-text": v6_answer(""), "layout-text": v6_answer(""), "spans": spans_answer([])}[name]
    with reading_format(name):
        line = run_one(MODULE, DINING, local_model["config"])
    assert line["status"] == "failed" and "Model response was blank." in line["error"] and line["failure"] == "other"


def test_a_failed_case_grades_as_nothing_and_the_run_goes_on(local_model):
    local_model["output"] = {"nope": 1}
    local_model["outputs"] = [{"nope": 1}, {"nope": 1}]
    line = run_one(MODULE, DINING, local_model["config"])
    assert line["status"] == "failed" and line["grades"] == {"passed": False, "score": 0.0, "checks": {}}


# The cases and the report -------------------------------------------------------------------------------------------------------------

def test_the_cases_are_the_24_drawn_receipts_with_family_and_condition_tags():
    assert len(CASES) == 24 and len({case["id"] for case in CASES}) == 24 and CASES == MODULE.cases()
    assert all(case["tags"][:2] == [case["input"]["family"], case["input"]["condition"]] for case in CASES)
    assert (MODULE.NAME, MODULE.ROLE, MODULE.MEASURED_ONLY) == ("receipt_layout", "vision", True) and list(TASKS)[-1] == "receipt_layout"


def result_line(candidate, case, output, status="ok"):
    graded = MODULE.grade(case, output) if status == "ok" else {"passed": False, "score": 0.0, "checks": {}}
    return {"candidate": candidate, "task": "receipt_layout", "case_id": case["id"], "tags": case["tags"], "status": status, "output": output,
            "failure": None if status == "ok" else "truncated", "grades": graded, "run_index": 0}


def test_the_report_has_a_reading_formats_section_with_denominators_per_format_family_and_condition():
    wrong_at = index_of("Bottled Water $3.95")
    lines = texts(ROWS)
    lines[wrong_at:wrong_at + 1] = ["Bottled Water", "$3.95"]
    split = v7(lines=lines, indents=[0] * len(lines))
    grouped = {
        "model@spans": [result_line("model@spans", case, oracle("receipt_layout", case)) for case in CASES[:5]]
        + [result_line("model@spans", CASES[5], None, status="failed")],
        "model@v7-lines": [result_line("model@v7-lines", DINING, split), result_line("model@v7-lines", CASES[1], {**v7(CASES[1]["expected"]["rows"]),
                                                                                                          "format": "v7-lines"})],
    }
    text = "\n".join(MODULE.report_lines(grouped))
    assert "### Reading formats" in text and "Measured only" in text
    assert "#### spans (receipt-vision-spans-1)" in text and "#### v7-lines (receipt-vision-v7-indent)" in text
    assert text.index("#### v7-lines") < text.index("#### spans")  # Formats in their fixed order.
    # Every count is against its total: rows read whole and the split row (28 + 28 rows), amounts on their row (18 + 20 amounts).
    assert "| model@v7-lines | 1 of 2 | 55 of 56 (" in text and "| 1 of 56 | 0 of 56 | 0 of 56 | 0 |" in text and "| 37 of 38 (" in text
    assert "| model@spans | 5 of 6 | 129 of 129 (" in text and "| model@spans | not reported" not in text
    assert "| model@spans | 19 of 19 (wrong 0, unknown 0) | 110 of 110 (wrong 0, unknown 0) | 129 of 129 | 129 of 129 | 100% / 100% (2 of 2" in text
    assert "| model@v7-lines | not reported" not in text and "not reported | not reported | not reported | not reported |" in text
    assert "| model@v7-lines | dining | 1 of 1 read (few) | 27 of 28 | 17 of 18 |" in text
    assert "| model@spans | grocery | 4 of 4 read | 101 of 101 | 69 of 69 |" in text and "| model@spans | dining | 1 of 2 read (few) | 28 of 28 |" in text
    assert "By family (spans)" in text and "By photo condition (spans)" in text and "(few)" in text


def test_a_run_reports_reading_formats_and_ranks_the_candidate_without_the_measured_only_task(tmp_path, local_model):
    from evals.tasks.runner import run_tasks
    from test_eval_tasks import config_for, task_lines
    local_model["output"] = exact(CASES[0], "v7-lines")
    folder = run_tasks(config_for(local_model), ["transcription", "receipt_layout"], out=tmp_path, network_guard=False, echo=lambda _: None, case_limit=2)
    lines = task_lines(folder)
    layout = [line for line in lines if line["task"] == "receipt_layout"]
    assert len(layout) == 2 and layout[0]["grades"]["passed"] and layout[0]["output"]["format"] == "v7-lines"
    report = (folder / "report.md").read_text(encoding="utf-8")
    assert "### Reading formats" in report and "#### v7-lines (receipt-vision-v7-indent)" in report and "| synthetic | 1 of 2 |" in report
    only = run_tasks(config_for(local_model), ["receipt_layout"], out=tmp_path, network_guard=False, echo=lambda _: None, case_limit=1)
    assert "### Reading formats" in (only / "report.md").read_text(encoding="utf-8")
