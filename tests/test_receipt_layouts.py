"""The receipt generator of specs/receipt-layout-eval (plans/receipt-layout-eval P7): FR-01 – FR-06, SC-13. Invented, synthetic receipts only."""

from collections import Counter
import hashlib
import re

import numpy as np
import PIL
from PIL import features
import pytest

from dining_receipt_fixtures import BREAKFAST
from evals import receipt_layouts as rl
from evals.receipt_layouts import CASES, FAMILIES, FONT_DIR, FONTS, answers, draw, make, parse_amounts, png_bytes
from evals.tasks.common import make_case

DINING_CLEAN_SHA256 = "7fbfc8c6f0cf659296df76864ff388da20ac884f17ec190b776189eeb7f56b49"
PINNED_IMAGING = {"pillow": "12.3.0", "freetype2": "2.14.3", "zlib_ng": "2.3.3"}


def drawn(case):
    receipt = make(*case)
    image, boxes = draw(receipt)
    return receipt, image, boxes, answers(receipt, boxes, image.size)


def row_boxes(receipt, boxes, text):
    """The boxes of the first row whose first cell reads `text`."""
    for row, row_box in zip(receipt.rows, boxes):
        if row.cells and row.cells[0].text == text:
            return row, row_box
    raise AssertionError(text)


# --- FR-03: fonts, licences, identical bytes --------------------------------------------------------------------------------------

def test_the_fonts_are_the_ones_the_generator_was_written_for():
    assert set(FONTS) == {"LiberationMono-Regular.ttf", "LiberationSans-Regular.ttf", "Caveat-VariableFont_wght.ttf"}
    for name, expected in FONTS.items():
        assert hashlib.sha256((FONT_DIR / name).read_bytes()).hexdigest() == expected, name


def test_the_licences_sit_beside_the_fonts():
    for name in ("OFL-Caveat.txt", "LICENSE-Liberation.txt"):
        text = (FONT_DIR / name).read_text(encoding="utf-8")
        assert "SIL OPEN FONT LICENSE" in text.upper(), name
    assert "Copyright" in (FONT_DIR / "LICENSE-Liberation.txt").read_text(encoding="utf-8")
    assert "Caveat" in (FONT_DIR / "OFL-Caveat.txt").read_text(encoding="utf-8")


def test_a_font_file_that_changed_is_refused(monkeypatch):
    monkeypatch.setitem(FONTS, "LiberationMono-Regular.ttf", "0" * 64)
    rl.font.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="not the font"):
            rl.font("LiberationMono-Regular.ttf", 26)
    finally:
        monkeypatch.undo()
        rl.font.cache_clear()


@pytest.mark.parametrize("case", [("dining", "clean", 0), ("dining", "tilted", 2), ("grocery", "faded", 1), ("itemized", "angled", 1),
                                  ("ereceipt", "background", 1), ("return", "blurred", 1), ("long", "small_text", 1)])
def test_drawing_a_case_twice_gives_identical_png_bytes(case):
    first = png_bytes(draw(make(*case))[0])
    assert first == png_bytes(draw(make(*case))[0])
    assert first.startswith(b"\x89PNG")


def pinned_imaging():
    found = {"pillow": PIL.__version__, "freetype2": features.version("freetype2"), "zlib_ng": features.version("zlib_ng")}
    return found == PINNED_IMAGING, found


def test_the_recorded_png_hash_of_the_dining_fixture_case():
    same, found = pinned_imaging()
    if not same:
        pytest.skip(f"the recorded hash was made with {PINNED_IMAGING}; this computer has {found}")
    assert hashlib.sha256(png_bytes(draw(make("dining", "clean", 0))[0])).hexdigest() == DINING_CLEAN_SHA256


def test_the_dining_fixture_case_is_the_fixture_with_its_numbers_replaced():
    receipt = make("dining", "clean", 0)
    texts = [cell.text for row in receipt.rows for cell in row.cells]
    # Every item line of the fixture is here with its price, and the four indented side lines sit at indent 1.
    fixture_prices = [parse_amounts(text) for text, _ in BREAKFAST if text.startswith(("Bottled", "Coffee", "Georgia", "Better"))]
    assert Counter(amount for amounts in fixture_prices for amount in amounts) == Counter(
        amount for row in receipt.rows if row.kind == "item" for amount in parse_amounts(" ".join(c.text for c in row.cells)))
    assert [row.cells[0].text for row in receipt.rows if row.indent == 1] == ["No Allergies", "Fresh Berry Pancakes", "Veggie Sausage", "Jalapeno Cheese Grits",
                                                                              "No Allergies"]
    assert {"Subtotal:", "Total Tax:", "Bill:"} <= {text for text in texts}
    assert [cell.text for row in receipt.rows if row.kind in ("written_tip", "written_total") for cell in row.cells if cell.handwritten] == ["61.55", "8.79"]
    suggested = [[cell.text for cell in row.cells] for row in receipt.rows if row.kind == "suggested"]
    assert suggested == [["18.00% of sale:", "$8.79", "Total", "$61.55"], ["20.00% of sale:", "$9.77", "Total", "$62.53"],
                         ["22.00% of sale:", "$10.75", "Total", "$63.51"]]


# --- FR-01: geometry, on the drawn boxes ------------------------------------------------------------------------------------------

def test_a_two_cell_rows_amount_ends_at_the_right_margin():
    receipt, _, boxes, _ = drawn(("dining", "clean", 0))
    row, row_box = row_boxes(receipt, boxes, "Coffee")
    assert len(row.cells) == 2
    assert row_box[1][2] == pytest.approx(rl.STYLES["thermal"].right, abs=2)
    assert row_box[0][0] == pytest.approx(rl.STYLES["thermal"].margin, abs=2)


def test_indent_one_starts_one_step_right_of_indent_zero():
    receipt, _, boxes, _ = drawn(("dining", "clean", 0))
    _, plain = row_boxes(receipt, boxes, "Georgia Peach Stack")
    _, side = row_boxes(receipt, boxes, "No Allergies")
    step = rl.indent_step("thermal")
    assert step == 2 * rl.advance("thermal")
    assert side[0][0] - plain[0][0] == pytest.approx(step, abs=2)


def test_a_centred_rows_middle_is_the_canvas_middle():
    receipt, image, boxes, _ = drawn(("dining", "clean", 0))
    _, row_box = row_boxes(receipt, boxes, "Magnolia Breakfast Bar")
    assert (row_box[0][0] + row_box[0][2]) / 2 == pytest.approx(rl.STYLES["thermal"].center, abs=2)
    assert image.width == rl.STYLES["thermal"].width
    # The proportional style has its own margins: a right cell ends at 840, a centred one is on 450.
    receipt, image, boxes, _ = drawn(("ereceipt", "clean", 0))
    _, row_box = row_boxes(receipt, boxes, "Order confirmation")
    assert (row_box[0][0] + row_box[0][2]) / 2 == pytest.approx(450, abs=2)
    _, total = row_boxes(receipt, boxes, "Total")
    assert total[1][2] == pytest.approx(840, abs=2)
    assert image.width == 900


def test_every_case_keeps_its_cells_in_order_and_apart():
    """Rows run top to bottom, a row's cells left to right, and no two cells of a row touch (so a reading can tell them apart)."""
    for case in CASES:
        receipt, image, boxes, _ = drawn(case)
        flat = [box for row in boxes for box in row]
        assert all(0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height for box in flat), case
        for row_box in boxes:
            assert [box[0] for box in row_box] == sorted(box[0] for box in row_box), case
        assert all(row.indent in (0, 1, 2) for row in receipt.rows), case
        assert all(row.indent == 0 for row in receipt.rows if row.cells and row.cells[0].align != "left"), case


def test_a_handwritten_cell_is_a_flagged_cell_of_a_printed_row():
    _, _, _, answer = drawn(("dining", "clean", 0))
    flagged = [(row["cells"][0]["text"], [cell["text"] for cell in row["cells"] if cell["handwritten"]]) for row in answer["rows"]
               if any(cell["handwritten"] for cell in row["cells"])]
    assert flagged == [("Total: $", ["61.55"]), ("Tip: $", ["8.79"])]
    assert any(row["amounts"] == [6155] and row["cells"][0]["text"] == "Total: $" for row in answer["rows"])


# --- FR-02: families --------------------------------------------------------------------------------------------------------------

def test_there_are_24_cases_and_every_family_has_at_least_two_tagged_cases():
    assert len(CASES) == 24 == len(set(CASES))
    for family in FAMILIES:
        cases = [case for case in CASES if case[0] == family]
        assert len(cases) >= 2, family
        for case in cases:
            assert family in make(*case).tags
            assert case[1] in make(*case).tags
    assert [case[1] for case in CASES if case[0] == "long"] == ["clean", "small_text", "small_text", "faded"]
    assert {case[1] for case in CASES} == set(rl.CONDITIONS)
    assert ("dining", "clean", 0) in CASES


def test_each_family_has_the_rows_its_name_promises():
    def texts(case):
        return [" ".join(cell.text for cell in row.cells) for row in make(*case).rows]

    grocery = make("grocery", "clean", 0)
    assert any(row.indent == 1 and len(row.cells) == 2 for row in grocery.rows)           # a quantity or savings line with its own price
    assert any(re.search(r"\d\.\d\d [TF]$", " ".join(c.text for c in row.cells)) for row in grocery.rows)  # a tax letter after a price
    assert any(row.kind == "written_tip" for row in make("dining", "faded", 1).rows)
    assert any(row.cells and row.cells[0].text == "Gallons" for row in make("fuel", "clean", 0).rows)
    assert any(row.cells and row.cells[0].text == "Merchant ID" for row in make("terminal", "clean", 0).rows)
    table = [row for row in make("itemized", "clean", 0).rows if row.kind == "header"]
    assert [cell.text for cell in table[0].cells] == ["Qty", "Item", "Price", "Total"]
    assert make("ereceipt", "clean", 0).style == "proportional" and all(make(*c).style == "thermal" for c in CASES if c[0] != "ereceipt")
    assert any(text.startswith("RETURN ") for text in texts(("return", "clean", 0)))
    # The two return cases print their negative money differently.
    assert any(text.endswith("-") for text in texts(("return", "clean", 0)))
    assert any(text.endswith(")") for text in texts(("return", "blurred", 1)))


def test_every_long_case_has_at_least_80_rows():
    for case in [case for case in CASES if case[0] == "long"]:
        assert len(drawn(case)[3]["rows"]) >= 80, case


# --- FR-05: answers and case ids --------------------------------------------------------------------------------------------------

def test_making_a_case_twice_gives_equal_answers_and_case_ids():
    for case in CASES:
        _, _, _, first = drawn(case)
        _, _, _, second = drawn(case)
        assert first == second, case
        family, condition, index = case
        make_first = make_case("receipt_layout", {"family": family, "condition": condition, "index": index}, first, [family, condition])
        make_second = make_case("receipt_layout", {"family": family, "condition": condition, "index": index}, second, [family, condition])
        assert make_first["id"] == make_second["id"]
    ids = {make_case("receipt_layout", {"case": list(case)}, drawn(case)[3])["id"] for case in CASES}
    assert len(ids) == len(CASES)


def test_the_answers_hold_rows_cells_indent_alignment_handwriting_amounts_and_boxes():
    _, image, _, answer = drawn(("dining", "clean", 0))
    assert answer["size"] == list(image.size)
    row = next(row for row in answer["rows"] if row["cells"][0]["text"] == "Georgia Peach Stack")
    assert row["indent"] == 0 and row["align"] == "left" and row["amounts"] == [1870]
    assert [cell["text"] for cell in row["cells"]] == ["Georgia Peach Stack", "$18.70"]
    assert all(len(cell["box"]) == 4 and not cell["handwritten"] for cell in row["cells"])
    assert next(row for row in answer["rows"] if row["cells"][0]["text"] == "Magnolia Breakfast Bar")["align"] == "center"
    assert next(row for row in answer["rows"] if row["cells"][0]["text"] == "Veggie Sausage")["indent"] == 1
    assert all(len(row["cells"]) >= 1 for row in answer["rows"])  # blank lines are not rows
    # Boxes are rounded to 0.1 px.
    assert all(round(value, 1) == value for row in answer["rows"] for cell in row["cells"] for value in cell["box"])


def test_amounts_follow_the_money_rule():
    assert parse_amounts("$3.95") == [395]
    assert parse_amounts("1,234.50 T") == [123450]
    assert parse_amounts("0.40-") == [-40] and parse_amounts("(24.99)") == [-2499] and parse_amounts("-1.20") == [-120]
    assert parse_amounts("18.00% of sale: $8.79 Total $61.55") == [879, 6155]
    assert parse_amounts("Price/Gal $3.459") == [] and parse_amounts("Gallons 10.234") == [] and parse_amounts("TAX 8.000%") == []
    assert parse_amounts("Tip: $ 8.79") == [879] and parse_amounts("3 @ 0.85 2.55 F") == [85, 255]


def test_every_money_cell_prints_one_amount_and_the_answers_agree_with_the_cells():
    for case in CASES:
        receipt, _, _, answer = drawn(case)
        assert all(len(parse_amounts(cell.text)) == 1 for row in receipt.rows for cell in row.cells if cell.money), case
        printed = Counter(amount for row in answer["rows"] for amount in row["amounts"])
        assert not (rl.printed_amounts(receipt) - printed), case


# --- FR-06: invented data ---------------------------------------------------------------------------------------------------------

def test_no_real_numbers_or_names_are_drawn():
    for case in CASES:
        texts = [cell.text for row in make(*case).rows for cell in row.cells]
        everything = "\n".join(texts)
        for number in re.findall(r"\d{6,}", everything):
            assert number.startswith("0000"), (case, number)
        assert "179580" not in everything and "Crimson" not in everything, case
        assert "Gacha" not in everything, case
        for phone in re.findall(r"555-\d+", everything):
            assert re.fullmatch(r"555-01\d\d", phone), (case, phone)


def test_the_fixtures_real_order_number_and_server_are_not_in_any_case():
    real = {text for text, _ in BREAKFAST if text.startswith(("Order #", "Server"))}
    assert real and not real & {cell.text for case in CASES for row in make(*case).rows for cell in row.cells}


# --- Arithmetic -------------------------------------------------------------------------------------------------------------------

def test_every_receipts_arithmetic_holds_and_is_printed():
    for case in CASES:
        receipt = make(*case)
        assert receipt.checks, case
        printed = rl.printed_amounts(receipt)
        for check in receipt.checks:
            if check[0] == "sum":
                _, parts, total = check
                assert sum(parts) == total, (case, check)
                assert not (Counter(parts + [total]) - printed), (case, check)
            else:
                _, a, b, total, divisor = check
                assert (a * b + divisor // 2) // divisor == total, (case, check)
                assert printed[total] >= 1, (case, check)
        totals = [amount for row in receipt.rows if row.kind == "total" for cell in row.cells if cell.money for amount in parse_amounts(cell.text)]
        assert totals, case


# --- SC-13: the recorded boxes enclose the drawn text -----------------------------------------------------------------------------

@pytest.mark.parametrize("case", [("dining", "tilted", 2), ("dining", "angled", 3), ("grocery", "tilted", 2), ("itemized", "angled", 1)])
def test_every_cells_ink_is_inside_its_recorded_box(case):
    receipt = make(*case)
    _, boxes = draw(receipt)
    checked = 0
    for number, row in enumerate(receipt.rows):
        for position, cell in enumerate(row.cells):
            image, again = draw(receipt, only=(number, position))
            assert again == boxes
            pixels = np.asarray(image.convert("RGB")).min(axis=2) < 160
            assert pixels.any(), (case, cell.text)
            ys, xs = np.nonzero(pixels)
            left, top, right, bottom = boxes[number][position]
            assert (xs.min() >= left - 2 and xs.max() + 1 <= right + 2 and ys.min() >= top - 2 and ys.max() + 1 <= bottom + 2), (
                case, cell.text, (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1), (left, top, right, bottom))
            checked += 1
    assert checked >= 14


def test_a_tilted_and_an_angled_case_really_are_transformed():
    flat = draw(make("dining", "clean", 0))[0]
    tilted, angled = draw(make("dining", "tilted", 2))[0], draw(make("dining", "angled", 3))[0]
    assert tilted.width > flat.width                       # rotated and expanded onto white
    assert np.asarray(angled)[0, :20].min() == 255          # the top edge is inset: the corners are paper-white fill
    assert (np.asarray(angled)[0, :20] == 255).all()
    assert angled.size == (760, angled.height)
    background = draw(make("dining", "background", 5))[0]
    assert background.size == (flat.width + 120, background.height) and background.getpixel((5, 5)) == rl.BACKGROUND_INK
    small = draw(make("long", "small_text", 1))[0]
    assert small.width == round(760 * rl.SMALL)
