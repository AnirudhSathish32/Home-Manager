"""The receipt item table's server half (specs/receipt-item-table FR-02, FR-03, FR-05; plans/receipt-item-table/plan.md
"Architecture, contracts, data flow and decisions"): item_table's qty, unit_price and tax_included for every rule branch,
splits.tax_basis, and the same values through Ledger.record. Expected values are the plan's and the contract's hand-worked
ones (tests/receipt_item_fixtures.py), not read back from the code."""

import pytest

from home_manager.finance.ledger import item_table
from home_manager.finance.splits import allocate, tax_basis
from receipt_item_fixtures import (
    D_AMOUNTS,
    D_LINES,
    D_SHARES,
    G_AMOUNTS,
    G_LINES,
    N_AMOUNTS,
    N_LINES,
    N_SHARES,
    R_AMOUNTS,
    R_LINES,
    R_SHARES,
    d_replies,
    g_replies,
    na_replies,
    ra_replies,
)
from test_bills_ledger import open_books, rent_and_water
from test_receipt_kinds import read_receipt


def row(position, line_total, share=None, **fields):
    """A receipt item as Ledger.record has it when item_table runs: id, stored columns, shown details and the stored share."""
    return {"id": position, "quantity": None, "unit_price_minor": None, "line_total_minor": line_total, "details": None, "share_minor": share, **fields}


def table(item, tax=0, basis=None):
    return item_table(item, {"tax_minor": tax}, basis or {}, "USD")


def weighed(price=None, unit="lb", price_unit=None, weight="2.31"):
    """Bananas' details as shown_details makes them: the weight's text with its unit, and the price per weight as printed."""
    details = {"weight": {"text": weight, "unit": unit, "display": f"{weight} {unit}" if unit else weight}}
    if price is not None:
        details["price_per_weight"] = {"text": price, "unit": price_unit or unit, "display": f"{price} {price_unit or unit}"}
    return details


# Qty and Unit price (FR-02, FR-03) ------------------------------------------------------------------------------

def test_r_items_show_one_the_printed_count_and_the_filter_price():
    ruffles = table(row(1, 429))
    veg = table(row(2, 4190, quantity="10", unit_price_minor=419))
    filter_ = table(row(3, 1299))
    assert (ruffles["qty"], ruffles["unit_price"]) == ("1", {"display": "4.29 USD", "per": None})
    assert (veg["qty"], veg["unit_price"]) == ("10", {"display": "4.19 USD", "per": None})
    assert (filter_["qty"], filter_["unit_price"]) == ("1", {"display": "12.99 USD", "per": None})


def test_g_items_show_a_weight_a_count_and_a_plain_line():
    bananas = table(row(1, 136, details=weighed("0.59")))
    yogurt = table(row(2, 450, quantity="3"))
    milk = table(row(3, 349))
    assert (bananas["qty"], bananas["unit_price"]) == ("2.31 lb", {"display": "0.59 USD", "per": "lb"})
    assert (yogurt["qty"], yogurt["unit_price"]) == ("3", None)  # Above one with no unit price: nothing is calculated.
    assert (milk["qty"], milk["unit_price"]) == ("1", {"display": "3.49 USD", "per": None})


def test_a_weight_without_a_printed_price_per_weight_has_no_unit_price():
    bananas = table(row(1, 136, details=weighed()))
    assert (bananas["qty"], bananas["unit_price"]) == ("2.31 lb", None)


def test_a_weight_with_a_unit_price_stored_still_takes_its_price_per_weight():
    bananas = table(row(1, 136, details=weighed("0.59"), unit_price_minor=136))
    assert bananas["unit_price"] == {"display": "0.59 USD", "per": "lb"}


@pytest.mark.parametrize("printed, shown", [("$0.59", "0.59 USD"), ("0.59", "0.59 USD"), ("1,000.5", "1000.5 USD"), ("€2", "2 USD")])
def test_a_price_per_weight_loses_one_leading_symbol_and_commas(printed, shown):
    assert table(row(1, 136, details=weighed(printed)))["unit_price"] == {"display": shown, "per": "lb"}


@pytest.mark.parametrize("printed", ["0.59-ish", "$$5", "5.", ".5", "1.2.3"])
def test_a_price_per_weight_that_is_not_a_plain_number_is_shown_as_text(printed):
    assert table(row(1, 136, details=weighed(printed)))["unit_price"] == {"display": f"{printed}/lb", "per": None}


def test_the_price_per_weight_unit_is_its_own_else_the_weights():
    assert table(row(1, 136, details=weighed("0.59", unit="lb", price_unit="oz")))["unit_price"]["per"] == "oz"
    assert table(row(1, 136, details={"weight": {"text": "2", "unit": "kg", "display": "2 kg"},
                                      "price_per_weight": {"text": "3", "unit": None, "display": "3"}}))["unit_price"] == {"display": "3 USD", "per": "kg"}


def test_a_stored_unit_price_wins_over_the_line_total_whatever_the_quantity():
    assert table(row(1, 4190, quantity="10", unit_price_minor=419))["unit_price"] == {"display": "4.19 USD", "per": None}
    assert table(row(1, 4190, quantity="2x", unit_price_minor=419))["unit_price"] == {"display": "4.19 USD", "per": None}


@pytest.mark.parametrize("quantity", ["1", "1.0", "-1", " 1 ", "-1.00"])
def test_a_quantity_of_one_or_minus_one_shows_the_line_total_as_the_price_of_one(quantity):
    assert table(row(1, 429, quantity=quantity))["unit_price"] == {"display": "4.29 USD", "per": None}


@pytest.mark.parametrize("quantity", ["0.5", "2x", "NaN", "sNaN", "Infinity", "10", "0", "−1", "1/2", "abc"])
def test_any_other_quantity_without_a_unit_price_shows_a_dash(quantity):
    assert table(row(1, 429, quantity=quantity))["unit_price"] is None


def test_qty_is_the_printed_quantity_collapsed_else_one_and_is_never_empty():
    assert table(row(1, 429, quantity="  10 "))["qty"] == "10"
    assert table(row(1, 429, quantity="2   x"))["qty"] == "2 x"
    assert table(row(1, 429, quantity="0.5"))["qty"] == "0.5"
    assert table(row(1, 429, quantity="   "))["qty"] == "1"
    assert table(row(1, 429, quantity=""))["qty"] == "1"
    assert table(row(1, 429, quantity=None))["qty"] == "1"


def test_a_weight_wins_over_a_stored_quantity_for_qty():
    assert table(row(1, 136, quantity="3", details=weighed("0.59")))["qty"] == "2.31 lb"


def test_an_item_with_no_line_total_and_no_unit_price_has_no_unit_price():
    assert table(row(1, None))["unit_price"] is None
    assert table(row(1, None, quantity="1"))["unit_price"] is None


def test_a_returned_item_shows_its_stored_negative_line_total_as_the_price():
    assert table(row(1, -1299))["unit_price"] == {"display": "-12.99 USD", "per": None}
    assert table(row(1, -1299, quantity="-1"))["unit_price"] == {"display": "-12.99 USD", "per": None}


def test_details_that_are_not_weight_details_change_nothing():
    other = table(row(1, 429, details={"pump": {"text": "3", "unit": None, "display": "3"}}))
    assert (other["qty"], other["unit_price"]) == ("1", {"display": "4.29 USD", "per": None})


# With tax (FR-05) -----------------------------------------------------------------------------------------------

def test_tax_is_in_only_the_taxed_filters_share_on_r():
    items = [{"line_total_minor": 429, "taxed": False}, {"line_total_minor": 4190, "taxed": False}, {"line_total_minor": 1299, "taxed": True}]
    basis = dict(zip((1, 2, 3), tax_basis(items)))
    shown = [table(row(index, amount, share), tax=274, basis=basis)["tax_included"] for index, amount, share in ((1, 429, 429), (2, 4190, 4190), (3, 1299, 1573))]
    assert shown == [False, False, True]


def test_tax_is_in_the_taxed_items_of_d_and_not_in_the_groceries():
    items = [{"line_total_minor": 150, "taxed": True}, {"line_total_minor": 49999, "taxed": True}, {"line_total_minor": 8000, "taxed": False}]
    basis = dict(zip((1, 2, 3), tax_basis(items)))
    shown = [table(row(index, amount, share), tax=4012, basis=basis)["tax_included"] for index, amount, share in zip((1, 2, 3), (150, 49999, 8000), D_SHARES)]
    assert shown == [True, True, False]


def test_with_no_item_marked_taxed_tax_is_in_every_share():
    items = [{"line_total_minor": 1000}, {"line_total_minor": 2000}]
    basis = dict(zip((1, 2), tax_basis(items)))
    assert [table(row(index, amount, amount + 100), tax=200, basis=basis)["tax_included"] for index, amount in ((1, 1000), (2, 2000))] == [True, True]


def test_a_receipt_with_no_tax_has_no_with_tax_flag():
    items = [{"line_total_minor": 1000, "taxed": True}]
    assert table(row(1, 1000, 1000), tax=0, basis=dict(zip((1,), tax_basis(items))))["tax_included"] is False
    assert item_table(row(1, 1000, 1000), {"tax_minor": None}, {1: 1000}, "USD")["tax_included"] is False


def test_an_item_without_a_stored_share_is_not_with_tax():
    assert table(row(1, 1000, None), tax=100, basis={1: 1000})["tax_included"] is False


def test_an_item_the_tax_is_not_shared_over_is_not_with_tax():
    assert table(row(2, 1000, 1000), tax=100, basis={1: 1000})["tax_included"] is False  # Rejected items aren't in the basis.
    assert table(row(1, 1000, 1000), tax=100, basis={})["tax_included"] is False  # No items to share over at all.


def test_a_basis_that_sums_to_nothing_puts_the_tax_where_no_item_carries_it():
    items = [{"line_total_minor": 1000}, {"line_total_minor": -1000}]
    basis = dict(zip((1, 2), tax_basis(items)))
    rows = allocate(items, None, 100, None, 100, "groceries")
    assert [index for index, _, _ in rows if index is None] == [None]  # allocate has no row for the tax on an item.
    assert [table(row(index, amount, amount), tax=100, basis=basis)["tax_included"] for index, amount in ((1, 1000), (2, -1000))] == [False, False]


def test_tax_on_a_returned_item_is_in_its_negative_share():
    # N: the filter's line is -1299 and the receipt's tax -101; its one share is -1400.
    result = table(row(1, -1299, -1400), tax=-101, basis={1: -1299})
    assert (result["qty"], result["unit_price"], result["tax_included"]) == ("1", {"display": "-12.99 USD", "per": None}, True)


# splits.tax_basis -----------------------------------------------------------------------------------------------

def test_tax_basis_is_the_amount_of_each_taxed_item():
    items = [{"line_total_minor": 150, "taxed": True}, {"line_total_minor": 49999, "taxed": True}, {"line_total_minor": 8000, "taxed": False}]
    assert tax_basis(items) == [150, 49999, 0]


def test_tax_basis_takes_an_items_discount_off():
    assert tax_basis([{"line_total_minor": 1000, "discount_minor": 100, "taxed": True}, {"line_total_minor": 500, "taxed": False}]) == [900, 0]


def test_tax_basis_is_every_amount_when_no_taxed_item_has_one():
    assert tax_basis([{"line_total_minor": 100}, {"line_total_minor": 200, "taxed": False}]) == [100, 200]
    assert tax_basis([{"line_total_minor": None, "taxed": True}, {"line_total_minor": 200}]) == [0, 200]


def test_tax_basis_of_no_items_is_empty():
    assert tax_basis([]) == []


def test_allocate_still_shares_the_tax_over_the_taxed_items_only():
    items = [{"line_total_minor": 150, "taxed": True, "category": "dining"}, {"line_total_minor": 49999, "taxed": True, "category": "furniture & decor"},
             {"line_total_minor": 8000, "taxed": False, "category": "groceries"}]
    rows = allocate(items, 58149, 4012, None, 62161, "groceries")
    assert [amount for _, _, amount in rows] == D_SHARES


# Through Ledger.record ------------------------------------------------------------------------------------------

def shares_of(manager, receipt_id):
    """The receipt's own category_splits per item in position order (transaction_id IS NULL), and the sum of every split row."""
    with manager.store.connection() as db:
        found = [row[0] for row in db.execute(
            "SELECT s.amount_minor FROM category_splits s JOIN receipt_items i ON i.id=s.receipt_item_id "
            "WHERE s.receipt_id=? AND s.transaction_id IS NULL ORDER BY i.position", (receipt_id,))]
        total = db.execute("SELECT sum(amount_minor) FROM category_splits WHERE receipt_id=? AND transaction_id IS NULL", (receipt_id,)).fetchone()[0]
    return found, total


def test_ra_through_record_shows_the_three_items_as_the_contract_says(tmp_path, local_model):
    with read_receipt(tmp_path, local_model, R_LINES, ra_replies()) as (manager, _run, record, row_):
        # P-checks: the stored receipt and its shares are the hand-worked ones.
        assert (row_["subtotal_minor"], row_["tax_minor"], row_["total_minor"]) == R_AMOUNTS
        assert shares_of(manager, row_["id"]) == (R_SHARES, R_AMOUNTS[2])
        assert [entry["share_minor"] for entry in record["items"]] == R_SHARES
        ruffles, veg, filter_ = [entry["table"] for entry in record["items"]]
        assert ruffles == {"qty": "1", "unit_price": {"display": "4.29 USD", "per": None}, "tax_included": False}
        assert veg == {"qty": "10", "unit_price": {"display": "4.19 USD", "per": None}, "tax_included": False}
        assert filter_ == {"qty": "1", "unit_price": {"display": "12.99 USD", "per": None}, "tax_included": True}
        # Display only: Ruffles' stored quantity stays empty.
        with manager.store.connection() as db:
            assert db.execute("SELECT quantity FROM receipt_items WHERE receipt_id=? ORDER BY position", (row_["id"],)).fetchall()[0][0] is None


def test_d_through_record_puts_the_tax_in_the_taxed_items_only(tmp_path, local_model):
    with read_receipt(tmp_path, local_model, D_LINES, d_replies()) as (manager, _run, record, row_):
        assert (row_["subtotal_minor"], row_["tax_minor"], row_["total_minor"]) == D_AMOUNTS
        assert shares_of(manager, row_["id"]) == (D_SHARES, D_AMOUNTS[2])
        assert [entry["table"]["tax_included"] for entry in record["items"]] == [True, True, False]
        assert [entry["table"]["qty"] for entry in record["items"]] == ["1", "1", "1"]
        assert [entry["table"]["unit_price"]["display"] for entry in record["items"]] == ["1.50 USD", "499.99 USD", "80.00 USD"]


def test_g_through_record_shows_the_weight_the_count_and_the_plain_line(tmp_path, local_model):
    with read_receipt(tmp_path, local_model, G_LINES, g_replies()) as (_manager, _run, record, row_):
        assert (row_["subtotal_minor"], row_["tax_minor"], row_["total_minor"]) == G_AMOUNTS
        bananas, yogurt, milk = [entry["table"] for entry in record["items"]]
        assert bananas == {"qty": "2.31 lb", "unit_price": {"display": "0.59 USD", "per": "lb"}, "tax_included": False}
        assert yogurt == {"qty": "3", "unit_price": None, "tax_included": False}
        assert milk == {"qty": "1", "unit_price": {"display": "3.49 USD", "per": None}, "tax_included": False}


def test_na_through_record_is_a_whole_return_and_the_filter_is_with_tax(tmp_path, local_model):
    with read_receipt(tmp_path, local_model, N_LINES, na_replies()) as (manager, _run, record, row_):
        assert record["direction"] == "return"
        assert (row_["subtotal_minor"], row_["tax_minor"], row_["total_minor"]) == N_AMOUNTS
        assert shares_of(manager, row_["id"]) == (N_SHARES, N_AMOUNTS[2])
        [entry] = record["items"]
        assert (entry["line_total_minor"], entry["share_minor"]) == (-1299, -1400)
        assert entry["table"] == {"qty": "1", "unit_price": {"display": "-12.99 USD", "per": None}, "tax_included": True}


def test_a_bill_gets_no_table(tmp_path):
    store, ledger, docs = open_books(tmp_path / "managed")
    try:
        bill_id = rent_and_water(ledger, docs["rent.png"])
        record = ledger.record("receipt", bill_id)
        assert record["items"] and all("table" not in entry for entry in record["items"])
    finally:
        store.close()
