"""Sharing a receipt's tax by its printed tax codes (specs/receipt-tax-codes FR-14 – FR-18, FR-23, FR-27, FR-29; plan "The rule"). The
rule only, with no database; each case builds its own items. Expected shares are the test contract's hand-worked numbers, and the
cases the contract doesn't print are worked out by hand in the comment beside them."""

import pytest

from home_manager.finance.splits import allocate, by_category, tax_basis, tax_parts

SUBTOTAL, TAX, TOTAL = 5918, 274, 6192
LINES = [("T", 101), ("B", 173)]


def thing(description, total, taxed, category, code=None):
    return {"description": description, "line_total_minor": total, "discount_minor": None, "taxed": taxed, "category": category, "tax_code": code}


def r0(ruffles="BF", veg="BF", filter_="T", flags=(True, True, True)):
    """R as SC-01 reads it: the stored flags FR-11 derives (all taxed), the codes as printed."""
    return [thing("RUFFLES", 429, flags[0], "groceries", ruffles), thing("LITLE VEGET", 4190, flags[1], "groceries", veg),
            thing("WATER FILTER", 1299, flags[2], "household supplies", filter_)]


def shared(items, lines, source="tax_lines", tax=TAX, total=TOTAL, subtotal=SUBTOTAL, fallback="groceries"):
    """(per-item shares, the plan) of a receipt the way Ledger.shares spreads it."""
    plan = tax_parts(items, tax, lines, source, "USD")
    rows = allocate(items, subtotal, tax, None, total, fallback, tax_parts=plan.parts)
    assert sum(amount for _, _, amount in rows) == total
    return [amount for _, _, amount in rows], plan


def test_r0_shares_each_tax_line_over_its_own_items():
    amounts, plan = shared(r0(), LINES)
    assert amounts == [445, 4347, 1400]
    assert (plan.by_code, plan.issues, plan.codes) == (True, [], {0: "B", 1: "B", 2: "T"})
    assert [(part[0], part[2]) for part in plan.parts] == [(101, "T"), (173, "B")]


def test_lines_that_dont_add_up_to_the_tax_fall_back_to_the_taxed_flags_sc04():
    amounts, plan = shared(r0(), LINES, tax=284, total=6202)
    assert amounts == [450, 4391, 1361]
    assert plan.by_code is False
    assert plan.issues == ["The tax lines (2.74 USD) don't add up to the tax (2.84 USD), so tax was shared across the taxed items."]


def test_a_tax_line_with_no_items_falls_back_sc05():
    amounts, plan = shared(r0(filter_="", flags=(True, True, False)), LINES)
    assert amounts == [454, 4439, 1299]
    assert plan.by_code is False
    assert plan.issues == ["The T tax line has no items carrying its code, so tax was shared across the taxed items."]


def test_an_item_carrying_two_codes_gets_no_tax_line_sc06():
    amounts, plan = shared(r0(ruffles="BT", flags=(False, True, True)), LINES)
    assert amounts == [429, 4363, 1400]
    assert plan.by_code is True
    assert plan.issues == ["RUFFLES carries more than one tax line's code (B, T), so it got no share of either."]
    assert plan.codes == {1: "B", 2: "T"}


def test_a_code_matching_no_tax_line_is_named_and_an_empty_code_is_not():
    amounts, plan = shared(r0(ruffles="N", veg="", flags=(False, False, True)), [("T", 274)])
    assert amounts == [429, 4190, 1573]
    assert plan.by_code is True
    assert plan.issues == ["RUFFLES's tax code N matches no tax line, so it got no tax line's share."]
    assert plan.codes == {2: "T"}


def test_correcting_the_tax_falls_back_by_amount_sc07():
    # 300 over all three items (flags 1, 1, 1), then the -26 charge difference by amount: each item's amount x 6192 / 5918.
    amounts, plan = shared(r0(), LINES, tax=300)
    assert amounts == [449, 4384, 1359]
    assert plan.issues == ["The tax lines (2.74 USD) don't add up to the tax (3.00 USD), so tax was shared across the taxed items."]
    amounts, plan = shared(r0(), LINES, tax=274)
    assert (amounts, plan.issues) == ([445, 4347, 1400], [])


def test_two_lines_with_the_same_code_are_added_for_that_code_sc15():
    amounts, plan = shared(r0(), [("T", 101), ("B", 100), ("B", 73)])
    assert amounts == [445, 4347, 1400]
    assert (plan.by_code, plan.issues) == (True, [])
    assert [(part[0], part[2]) for part in plan.parts] == [(101, "T"), (173, "B")]


def test_codes_are_compared_without_spaces_or_case():
    assert shared(r0(ruffles=" b f", veg="bf"), [("t", 101), (" b ", 173)])[0] == [445, 4347, 1400]


def test_a_tax_line_whose_amount_cant_be_read_falls_back_over_the_taxed_flags():
    # R0 with B unreadable: the flags are 1, 1, 1 (P7), so 274 over 5918 as in SC-07's arithmetic.
    amounts, plan = shared(r0(), [("T", 101), ("B", None)])
    assert amounts == [449, 4384, 1359]
    assert plan.by_code is False
    assert plan.issues == ["The B tax line's amount couldn't be read, so tax was shared across the taxed items."]
    # The same code printed twice with one amount unreadable is unreadable for the code.
    assert shared(r0(), [("T", 101), ("B", 100), ("B", None)])[1].issues == plan.issues


def test_a_tax_line_whose_items_add_up_to_nothing_falls_back():
    # B's only item prices at 0.00, so 1.73 has nowhere to go: 274 over the taxed items (Ruffles 429, filter 1299).
    items = [thing("RUFFLES", 429, True, "groceries", "T"), thing("FREE GIFT", 0, True, "groceries", "B"), thing("WATER FILTER", 1299, True, "household supplies", "T")]
    amounts, plan = shared(items, [("T", 101), ("B", 173)], subtotal=1728, total=2002)
    assert plan.by_code is False
    assert plan.issues == ["The B tax line's items add up to nothing, so tax was shared across the taxed items."]
    assert sum(amounts) == 2002 and amounts[1] == 0


def test_a_zero_tax_line_with_no_items_falls_back_but_with_an_item_it_shares_by_code():
    # 274 on B, a printed 0.00 on N. No item carries N: the receipt falls back (P9), flags 0, 1, 1 (Ruffles has no tax line).
    lines = [("B", 274), ("N", 0)]
    amounts, plan = shared(r0(ruffles="", flags=(False, True, True), filter_="BF"), lines)
    assert plan.by_code is False
    assert plan.issues == ["The N tax line has no items carrying its code, so tax was shared across the taxed items."]
    # With Ruffles carrying N, B's 274 goes over Little Veg and the filter: 274 x 4190 / 5489 = 209.156, 274 x 1299 / 5489 = 64.844.
    amounts, plan = shared(r0(ruffles="N", filter_="BF", flags=(False, True, True)), lines)
    assert amounts == [429, 4399, 1364]
    assert (plan.by_code, plan.issues, plan.codes) == (True, [], {0: "N", 1: "B", 2: "B"})
    assert plan.included(0) is False and plan.included(1) is True and plan.included(2) is True


def test_a_returns_tax_lines_carry_the_receipts_sign():
    items = [{**row, "line_total_minor": -row["line_total_minor"]} for row in r0()]
    amounts, plan = shared(items, LINES, tax=-TAX, total=-TOTAL, subtotal=-SUBTOTAL)
    assert amounts == [-445, -4347, -1400]
    assert plan.by_code is True and [part[0] for part in plan.parts] == [-101, -173]


def test_no_tax_means_no_parts_and_no_issues():
    for tax in (0, None):
        plan = tax_parts(r0(ruffles="BT"), tax, LINES, "tax_lines", "USD")
        assert (plan.parts, plan.by_code, plan.issues, plan.codes) == ([], False, [], {})
    assert shared(r0(), LINES, tax=0, total=5918)[0] == [429, 4190, 1299]


def test_one_tax_line_receipt_with_partly_answered_flags_shares_over_every_item_sc18():
    # Read with neither tax lines nor a legend: the filter answered taxed, the BF items left empty. 274 over 5918 (SC-07's arithmetic).
    amounts, plan = shared(r0(flags=(None, None, True)), [], source="printed")
    assert amounts == [449, 4384, 1359]
    assert (plan.by_code, plan.issues) == (False, [])
    assert [part[2] for part in plan.parts] == [None]
    # Every flag answered: today's rule, the filter alone (429 / 4190 / 1573).
    assert shared(r0(flags=(False, False, True)), [], source="printed")[0] == [429, 4190, 1573]


def test_a_receipt_read_with_every_flag_empty_shares_over_every_item_sc16():
    assert shared(r0(flags=(None, None, None)), [], source="printed")[0] == [449, 4384, 1359]


def test_a_legend_receipt_with_an_unanswered_flag_keeps_todays_rule():
    # The legend sets what it can; an item it doesn't name stays empty and is untaxed in the basis, as today (plan "The rule").
    items = r0(flags=(None, False, True))
    plan = tax_parts(items, TAX, [], "legend", "USD")
    assert plan.parts == [(TAX, tax_basis(items), None)]


def costco():
    return [thing("HOT DOG", 150, True, "dining"), thing("MATTRESS", 49999, True, "furniture & decor"), thing("GROCERIES", 8000, False, "groceries")]


def ra():
    return [thing("RUFFLES", 429, False, "groceries"), thing("LITLE VEG", 4190, False, "groceries"), thing("WATER FILTER", 1299, True, "household supplies")]


@pytest.mark.parametrize("items, subtotal, tax, total, expected", [
    (costco(), 58149, 4012, 62161, [162, 53999, 8000]),  # D: docs/money.md's Costco example.
    (ra(), SUBTOTAL, TAX, TOTAL, [429, 4190, 1573]),  # R / RA as recorded before this change.
    ([{**row, "taxed": None} for row in costco()], 58149, 4012, 62161, [160, 53449, 8552]),  # No flags at all.
])
@pytest.mark.parametrize("source", [None, "legend"])
def test_without_tax_lines_the_rule_is_todays_tax_basis(items, subtotal, tax, total, expected, source):
    plan = tax_parts(items, tax, [], source, "USD")
    assert plan.parts == [(tax, tax_basis(items), None)] and plan.by_code is False
    with_plan = allocate(items, subtotal, tax, None, total, "groceries", tax_parts=plan.parts)
    assert with_plan == allocate(items, subtotal, tax, None, total, "groceries")
    assert [amount for _, _, amount in with_plan] == expected


def test_a_source_of_none_ignores_tax_lines_that_are_there():
    # Receipts recorded before this change have no tax_source; Reconciler.run rebuilds their splits and they must not move.
    assert shared(ra(), LINES, source=None)[0] == [429, 4190, 1573]


def test_categories_add_up_to_the_target_with_a_discount_and_a_tip():
    items = r0()
    items[1]["discount_minor"] = 190
    plan = tax_parts(items, TAX, LINES, "tax_lines", "USD")
    rows = allocate(items, 5918 - 190 - 100, TAX, 150, 5918 - 190 - 100 + TAX + 150, "groceries", tax_parts=plan.parts)
    assert sum(by_category(rows).values()) == 5918 - 190 - 100 + TAX + 150
