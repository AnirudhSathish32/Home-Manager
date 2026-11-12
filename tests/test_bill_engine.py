"""The charge table engine, engine level (specs/pdf-table-engine-bills/test-contract.md), slice SL-01: P-checks, then charge rows (SC-100), headings never
required (SC-101), sections, holder titles, totals and wrapped labels (SC-102 steps 1 and 9), summary anchors and late lines (SC-103), nothing dropped
silently (SC-104), a page with no charge table (SC-114 step 1), and the plan's own G7 and G14 decisions.

Slice SL-02 (the last sections, `bill_tables`): which column is the charge (SC-105), money off (SC-106), the rate-to-cents rule (SC-110 step 6's unit list),
the guesses and the adapter Record reads (ids, line ids, wrapped label lines, title line ids) with `for_lines`.

`pcheck_*` say each synthetic fixture has the shape the contract intends when the real reader reads it; the others compare the engine's tables with the facts
written out by hand in tests/bill_engine_fixtures.py. A failed P-check is a fixture or reader problem, never a reason to change an expected value. No store
and no model: every test reads a saved reading of a synthetic PDF.
"""

from dataclasses import asdict
from decimal import Decimal
import json
import random
import re
import socket
from statistics import median

import pytest

import bill_engine_fixtures as bf
from home_manager.documents import charge_tables
from home_manager.documents.table_engine import PageView
from home_manager.finance import bill_tables
from home_manager.finance.paystub_tables import PageMap
import pdf_import_fixtures as fx


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """C-net: nothing connects to a non-loopback address."""
    def loopback(address):
        host = address[0] if isinstance(address, tuple) else address
        return not isinstance(host, str) or host in ("localhost", "::1") or host.startswith("127.") or host.startswith("/")

    def guard(original):
        def connect(self, address, *args):
            if not loopback(address):
                raise OSError(f"C-net: a connection to {address} was blocked")
            return original(self, address, *args)
        return connect

    real_create = socket.create_connection

    def create(address, *args, **kwargs):
        if not loopback(address):
            raise OSError(f"C-net: a connection to {address} was blocked")
        return real_create(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guard(socket.socket.connect))
    monkeypatch.setattr(socket.socket, "connect_ex", guard(socket.socket.connect_ex))
    monkeypatch.setattr(socket, "create_connection", create)


@pytest.fixture(scope="module")
def reader(tmp_path_factory):
    """`reader(name_or_pages)`: the fixture read by the real reader with no model (every page is native text), once per name."""
    cache = {}

    def read(source, **options):
        key = source if isinstance(source, str) else json.dumps(source, sort_keys=True, default=str)
        if key not in cache:
            pages = bf.FIXTURES[source]() if isinstance(source, str) else source
            result = fx.read_pdf(tmp_path_factory.mktemp("bill"), pages, **options)
            assert [page.method for page in result.pages] == ["embedded_text"] * len(pages)
            cache[key] = result
        return cache[key]

    return read


def engine_of(reader, name):
    return charge_tables.read(reader(name))


def facts(table):
    """A table's rows as the contract writes them: (label, section, the printed text in each column left to right, "" where the row prints none)."""
    columns = [column.id for column in table.columns]

    def cell(row, column):
        if column in row.usage:
            return row.usage[column][0]
        return row.amounts[column].text if column in row.amounts else ""

    return [(row.label, row.section, *[cell(row, column) for column in columns]) for row in table.rows]


def anchors_of(reading):
    return [(anchor.kind, anchor.token.text) for anchor in reading.anchors]


def right_edges(result, table, number=1):
    """Each column's right edge in page points (its extent's right end)."""
    scale = fx.scale(fx.layout(result, number))
    return [column.extent[1] / scale for column in table.columns]


def serialized(value):
    return json.dumps(asdict(value), sort_keys=True, default=str)  # Decimal is the only value json can't write.


# === P-checks: the shape of each fixture ====================================================================================

NATIVE = [name for name in bf.FIXTURES if name not in bf.NOT_NATIVE]


@pytest.mark.parametrize("name", NATIVE)
def test_pcheck_every_page_is_native_text_and_the_reader_states_only_the_expected_layout_issues(reader, name):
    result = reader(name)
    for number, page in enumerate(result.pages, 1):
        assert fx.nonspace(page.layout.raw_text) >= fx.MINIMUM_FOOTER
        assert set(page.layout.issues) <= {"unresolved_columns"}, f"page {number}: {page.layout.issues}"


def assert_edge(result, number, edge, texts, slack=0.5):
    """The saved word boxes of the texts printed near `edge` agree on their right edge within 0.5 pt, and it is the edge the contract states. The reader's word
    boxes are glyph boxes: a letter ends up to `slack` short of its advance, and a word ending in the digit 1 ends about 1.6 pt short, so those agree within 2 pt."""
    layout = fx.layout(result, number)
    scale = fx.scale(layout)
    words = [word for word in layout.words if word.text in texts and abs(fx.word_box(layout, word)[2] / scale - edge) <= 3]
    assert {word.text for word in words} == set(texts), (edge, texts)
    rights = [fx.word_box(layout, word)[2] / scale for word in words if not word.text.endswith("1")]
    assert max(rights) - min(rights) <= 0.5
    assert abs(median(rights) - edge) <= slack
    assert all(abs(fx.word_box(layout, word)[2] / scale - edge) <= 2 for word in words)


def test_pcheck_bl_util_amount_columns_agree_on_their_right_edge(reader):
    result = reader("BL-UTIL")
    assert_edge(result, 1, bf.USAGE, {"kWh"}, slack=1.0)
    assert_edge(result, 1, bf.RATE, {"0.1200", "0.1430"})
    assert_edge(result, 1, bf.CHARGE, {"60.00", "20.02", "12.00", "5.53", "82.10", "-82.10", "97.55"})


def test_pcheck_bl_phone_and_bl_rent_amounts_agree_on_their_right_edge(reader):
    assert_edge(reader("BL-PHONE"), 1, bf.CHARGE, {"55.00", "24.99", "79.99", "35.00", "8.51", "43.51", "-5.00", "120.00", "-120.00", "118.50"})
    assert_edge(reader("BL-RENT"), 1, bf.CHARGE, {"$1,450.00", "$38.42", "$1,488.42"})


def test_pcheck_the_rent_bill_keeps_its_amounts_in_runs_of_their_own_and_its_dot_leaders_in_the_labels(reader):
    layout = fx.layout(reader("BL-RENT"), 1)
    view = PageView(layout)
    runs = [[" ".join(word.text for word in run) for run in view.runs(index)] for index in range(len(view.rows))]
    assert ["Rent 10/01/2026 - 10/31/2026", "$1,450.00"] in runs
    assert ["Water Usage 08/15/2026 - 09/14/2026 3,200 GAL", "$38.42"] in runs
    assert any(len(row) == 2 and row[0].startswith("Amount Due....") and row[1] == "$1,488.42" for row in runs)


# === SC-100: charge rows, dates and usage are label text ====================================================================

def test_sc100_rent_gives_one_table_two_rows_dates_and_usage_in_the_labels(reader):
    result = reader("BL-RENT")
    reading = charge_tables.read(result)
    assert len(reading.tables) == 1 and reading.other_tables == []
    table = reading.tables[0]
    assert facts(table) == [(label, "Rent and Leasing Charges Due 10/01/2026", amount) for label, amount in bf.RENT_ENGINE_ROWS]
    assert [column.kind for column in table.columns] == ["amount"]
    assert [row.amounts[table.columns[0].id].value[0] for row in table.rows] == [Decimal("1450.00"), Decimal("38.42")]
    # 3,200 is no amount and no column, and no row has a stray amount.
    assert all("3,200" not in token.text for row in table.rows for token in [*row.amounts.values(), *row.stray]) and not any(row.stray for row in table.rows)
    assert table.totals == [] and reading.unplaced == [] and reading.late_lines == [] and reading.pages_without_tables == []
    # Due Date and Amount Due are key and summary lines, not rows: Amount Due is an amount-due anchor, 1,488.42.
    assert [(anchor.kind, anchor.token.value[0]) for anchor in reading.anchors] == [("amount_due", Decimal("1488.42"))]
    assert not any(row.label.startswith(("Due Date", "Amount Due")) for row in table.rows)


def test_sc100_a_payment_received_line_with_a_date_is_an_anchor_whose_only_amount_is_the_printed_one(reader):
    reading = charge_tables.read(reader("PAYMENT-RECEIVED"))
    assert [(anchor.kind, anchor.token.text, anchor.token.value) for anchor in reading.anchors] == [("payments", "-100.00", (Decimal("100.00"), "minus", None))]
    assert reading.tables == [] and reading.other_tables == [] and reading.unplaced == []


# === SC-101: headings are never required ====================================================================================

UTIL_COLUMN_KINDS = ["usage", "amount", "amount"]


@pytest.mark.parametrize("name", ["BL-UTIL", "UTIL-2L", "UTIL-ODD", "UTIL-NOHEAD"])
def test_sc101_headed_two_line_odd_and_headless_give_the_same_three_columns(reader, name):
    result = reader(name)
    table = charge_tables.read(result).tables[0]
    assert [round(edge) for edge in right_edges(result, table)] == [bf.USAGE, bf.RATE, bf.CHARGE] or all(
        abs(edge - wanted) <= 1 for edge, wanted in zip(right_edges(result, table), [bf.USAGE, bf.RATE, bf.CHARGE]))  # A letter ends short of its advance.
    assert [column.kind for column in table.columns] == UTIL_COLUMN_KINDS
    assert [(label, section, usage, rate, charge) for label, section, usage, rate, charge in facts(table)] == bf.UTIL_ENGINE_ROWS


def test_sc101_headings_only_label_their_columns(reader):
    labels = lambda name: [column.labels for column in charge_tables.read(reader(name)).tables[0].columns]  # noqa: E731
    assert labels("BL-UTIL") == [["Usage"], ["Rate"], ["Charge"]]
    assert labels("UTIL-2L") == [["Usage", "(kWh)"], ["Rate per", "kWh"], ["This", "Charge"]]
    assert labels("UTIL-ODD") == [["Consumed"], ["Price"], ["Amount Billed"]]
    assert labels("UTIL-NOHEAD") == [[], [], []]


def test_sc101_a_usage_column_keeps_the_unit_as_printed_and_is_never_money(reader):
    table = charge_tables.read(reader("BL-UTIL")).tables[0]
    usage = table.columns[0]
    assert [row.usage[usage.id][0] for row in table.rows[:2]] == ["500 kWh", "140 kWh"] and all(row.usage == {} for row in table.rows[2:])
    assert all(usage.id not in row.amounts for row in table.rows)
    assert charge_tables.usage_value("500 kWh") == Decimal(500) and charge_tables.usage_value("1,234 kWh") == Decimal(1234)


def test_sc101_columns_are_found_by_alignment_wherever_they_sit(reader):
    shuffled = charge_tables.read(reader("UTIL-SHUF")).tables[0]
    assert [column.kind for column in shuffled.columns] == ["amount", "usage", "amount"]
    assert facts(shuffled) == [("Energy Tier 1", "Electric Charges", "60.00", "500 kWh", "0.1200"), ("Energy Tier 2", "Electric Charges", "20.02", "140 kWh", "0.1430"),
                               ("Customer Charge", "Electric Charges", "12.00", "", ""), ("State Tax", "Taxes and Fees", "5.53", "", "")]
    headless = charge_tables.read(reader("BL-HEADLESS")).tables[0]
    assert [column.kind for column in headless.columns] == ["amount", "usage", "amount"] and [column.labels for column in headless.columns] == [[], [], []]
    assert facts(headless) == facts(shuffled)
    last_year = charge_tables.read(reader("UTIL-LASTYEAR")).tables[0]
    assert [column.labels for column in last_year.columns] == [["This Bill"], ["Last Year"]]
    assert facts(last_year) == [("Energy Charge", "Electric Charges", "80.02", "72.15"), ("Customer Charge", "Electric Charges", "12.00", "12.00"),
                                ("State Tax", "Electric Charges", "5.53", "4.98")]
    assert facts(charge_tables.read(reader("UTIL-LASTYEAR-C2")).tables[0]) == facts(last_year)


# === SC-102 steps 1 and 9: sections, holder titles, totals, a wrapped label =================================================

def line_with(result, text, number=1):
    """The id of the saved layout line that holds the one word printed as `text`."""
    layout = fx.layout(result, number)
    ids = [word.id for word in layout.words if word.text == text]
    assert len(ids) == 1, (text, ids)
    return next(line.id for line in layout.lines if ids[0] in line.word_ids)


def test_sc102_step1_phone_bill_gives_five_rows_two_totals_four_anchors_and_holder_titles(reader):
    result = reader("BL-PHONE")
    reading = charge_tables.read(result)
    assert len(reading.tables) == 1 and reading.other_tables == []
    table = reading.tables[0]
    assert facts(table) == bf.PHONE_ENGINE_ROWS
    assert [(total.label, total.values[table.columns[0].id].text) for total in table.totals] == bf.PHONE_ENGINE_TOTALS
    assert anchors_of(reading) == bf.PHONE_ENGINE_ANCHORS
    assert reading.unplaced == [] and reading.late_lines == []
    # Each of the four rows under a holder title is cited to the title line as well as its own lines; the credits title is no holder title.
    alex, blair, credits = (line_with(result, word) for word in ("555-201-1111", "555-202-2222", "Credits"))
    assert [(row.title.line_id, row.title.phone) for row in table.rows] == [(alex, True), (alex, True), (blair, True), (blair, True), (credits, False)]
    assert [title.text for title in table.titles] == ["Alex 555-201-1111", "Blair 555-202-2222", "Account Credits"]
    assert [title.line_id for title in table.titles] == [alex, blair, credits]
    assert all(title.line_id not in row.line_ids for row in table.rows for title in [row.title])  # The title line is its own line, cited by the title.


def test_sc102_step1_the_wrapped_label_joins_its_row_and_spans_both_lines(reader):
    result = reader("BL-PHONE")
    table = charge_tables.read(result).tables[0]
    row = next(row for row in table.rows if row.label.startswith("International Pack"))
    assert row.label == "International Pack (Canada and Mexico)"
    first, second = line_with(result, "International"), line_with(result, "(Canada")
    assert [line for line in row.line_ids if line in (first, second)] == [first, second]
    printed = {word.id: word.text for word in fx.layout(result, 1).words}
    assert sorted(printed[word_id] for word_id in row.word_ids) == sorted(["International", "Pack", "8.51", "(Canada", "and", "Mexico)"])
    # The wrapped line is no unplaced line and no row of its own.
    assert len(table.rows) == 5


def test_sc102_totals_are_totals_not_rows_and_a_section_ends_with_its_total(reader):
    table = charge_tables.read(reader("BL-PHONE")).tables[0]
    assert [row.row for row in table.rows] == [1, 2, 4, 5, 7] and [total.row for total in table.totals] == [3, 6]
    assert not any(row.label.startswith("Total") for row in table.rows)


@pytest.mark.parametrize(("title", "holder", "text"), bf.PHONE_TITLES)
def test_sc102_step9_phone_number_titles_are_decided_at_engine_level_with_no_model(reader, title, holder, text):
    pages = bf.title_page(title, encoding="cp1252" if "•" in title else None)
    reading = charge_tables.read(reader(pages))
    assert len(reading.tables) == 1 and len(reading.tables[0].rows) == 2
    table = reading.tables[0]
    assert [t.text for t in table.titles] == [text] and table.titles[0].phone is holder
    assert [(row.section, row.title.phone) for row in table.rows] == [(text, holder)] * 2


def test_sc102_step9_a_title_longer_than_eighty_characters_is_read_whole_and_recognised_by_its_number(reader):
    pages = bf.title_page(bf.LONG_TITLE, size=7)
    result = reader(pages)
    assert abs(PageView(fx.layout(result, 1)).size / fx.scale(fx.layout(result, 1)) - 10) < 0.5  # The small title leaves the page's font size at 10.
    table = charge_tables.read(result).tables[0]
    assert table.titles[0].text == bf.LONG_TITLE and table.titles[0].phone is True
    assert len(bf.LONG_TITLE[:80]) == 80 and bf.LONG_TITLE[:80] == "555-201-1111 " + "Z" * 67


# === G14 and the phone form =================================================================================================

PHONE_YES = ["Alex 555-201-1111", "Blair (555) 202-2222", "Alex 555.201.1111", "Line 201-1111", "+1 555-201-1111", "1-555-201-1111", "Alex xxx-xxx-1111",
             "Alex ***-1111", "Alex •••• 1111", "Line ending 1111", "Line ending in 1111", "Phone ends in 1111", "Account ****9012"]
PHONE_NO = ["Charges 2025-2026", "2025 - 2026", "Account 1234-5678-9012", "555-0100-7788", "Charges 2026", "Card 4111 1111 1111 1111", "Quantity 1,234.5678",
            "Electric Charges", "Charges 2025 2026"]


@pytest.mark.parametrize("text", PHONE_YES)
def test_g14_every_phone_form_the_spec_lists_matches(text):
    assert charge_tables.PHONE.search(text)


@pytest.mark.parametrize("text", PHONE_NO)
def test_g14_year_ranges_account_numbers_years_and_quantities_are_no_phone_numbers(text):
    assert charge_tables.PHONE.search(text) is None


def test_g14_a_bare_four_digit_number_is_never_a_phone():
    for text in ("2026", "Year 2026", "Ref 1111", "Line 1111"):
        assert charge_tables.PHONE.search(text) is None


def test_g14_a_year_range_and_an_account_number_are_no_holder_titles_and_a_masked_number_is(reader):
    year = charge_tables.read(reader(bf.title_page("Charges 2025-2026"))).tables[0].titles[0]
    account = charge_tables.read(reader(bf.title_page("Account 1234-5678-9012"))).tables[0].titles[0]
    masked = charge_tables.read(reader(bf.title_page("Account ****9012"))).tables[0].titles[0]
    assert (year.phone, account.phone, masked.phone) == (False, False, True)


# === SC-103: summary anchors wherever printed; late amounts are nothing ======================================================

def test_sc103_step1_util_gives_six_anchors_none_a_row_or_a_total_and_four_rows(reader):
    reading = engine_of(reader, "BL-UTIL")
    assert anchors_of(reading) == bf.UTIL_ENGINE_ANCHORS and [anchor.order for anchor in reading.anchors] == list(range(6))
    assert len(reading.tables) == 1 and len(reading.tables[0].rows) == 4 and reading.tables[0].totals == []
    assert facts(reading.tables[0]) == bf.UTIL_ENGINE_ROWS
    labels = {row.label for table in [*reading.tables, *reading.other_tables] for row in table.rows}
    assert not labels & {"Previous Balance", "Total Amount Due", "New Charges", "Total Current Charges", "Amount Due"}


@pytest.mark.parametrize("name", ["UTIL-LATE", "UTIL-LATE-COL"])
def test_sc103_step2_the_late_line_is_no_anchor_no_row_and_no_unplaced_line(reader, name):
    reading = engine_of(reader, name)
    assert anchors_of(reading) == bf.UTIL_ENGINE_ANCHORS
    assert facts(reading.tables[0]) == bf.UTIL_ENGINE_ROWS and reading.tables[0].totals == []
    assert reading.unplaced == [] and len(reading.late_lines) >= 1
    assert all(token.text != "102.55" and token.text != "$102.55" for anchor in reading.anchors for token in [anchor.token])
    assert not any("102.55" in token.text for table in reading.tables for row in table.rows for token in [*row.amounts.values(), *row.stray])


ANCHOR_CASES = {
    "previous_balance": ["Previous Balance", "Balance Forward", "Last Bill", "Previous Bill Amount"],
    "payments": ["Payment", "Payments", "Payment Received", "Payments Received", "Payment - Thank You", "Payments - Thank You", "Payment Thank You"],
    "new_charges": ["New Charges", "Current Charges", "Total Current Charges", "Total New Charges"],
    "amount_due": ["Amount Due", "Total Amount Due", "Total Due", "Balance Due", "Amount to Pay", "Total Amount to Pay", "Payment Due"],
}


@pytest.mark.parametrize(("kind", "phrase"), [(kind, phrase) for kind, phrases in ANCHOR_CASES.items() for phrase in phrases])
def test_sc103_step4_each_listed_phrase_is_an_anchor_of_its_kind_in_any_case(kind, phrase):
    for text in (phrase, phrase.upper(), phrase.lower(), phrase.title()):
        assert charge_tables.anchor_kind(text) == kind


def test_sc103_step4_dates_leaders_dollar_signs_and_colons_are_not_part_of_the_label():
    for text, kind in (("Amount Due by 10/15/2026", "amount_due"), ("Payment Received 09/20/2026", "payments"), ("Payment Due 10/15/2026", "amount_due"),
                       ("Amount Due.........", "amount_due"), ("Total Amount Due:", "amount_due"), ("$ Balance Forward", "previous_balance"),
                       ("Payment as of 09/20/2026", "payments"), ("New Charges | ", "new_charges")):
        assert charge_tables.anchor_kind(text) == kind, text
    # Whole words and whole labels only.
    for text in ("Previous Balances Report", "Minimum Payment Due", "Late Payment Charge", "Device Payment", "Your previous balance was paid in full", "Amount Due Now Today"):
        assert charge_tables.anchor_kind(text) is None, text


def test_sc103_step4_the_word_list_is_one_module_constant():
    assert {phrase.lower() for phrases in ANCHOR_CASES.values() for phrase in phrases} <= {phrase for phrases in charge_tables.ANCHOR_WORDS.values() for phrase in phrases} | {
        "payment - thank you", "payments - thank you"}
    assert set(charge_tables.ANCHOR_WORDS) == set(ANCHOR_CASES)


def test_sc103_a_payment_due_line_with_an_amount_is_an_anchor_and_without_one_a_key_line():
    assert charge_tables.key_kind("Payment Due 10/15/2026") == "due_date"
    assert charge_tables.anchor_kind("Payment Due 10/15/2026") == "amount_due"


# === FR-128's key lines (the engine classes them, the split rule is SL-06) ==================================================

@pytest.mark.parametrize(("text", "kind"), [("Due Date 10/15/2026", "due_date"), ("Payment Due Date: 10/15/2026", "due_date"), ("Due Date ........ 10/01/2026", "due_date"),
                                           ("Statement Date 09/20/2026", "statement_date"), ("Bill Date 09/20/2026", "statement_date"),
                                           ("Account Number 1234-5678-9012", "account"), ("Account # 1234", "account"), ("Account ****9012", "account"),
                                           ("Account No. 555-0100-7788", "account")])
def test_a_line_that_starts_with_a_key_label_and_prints_its_value_is_a_key_line(text, kind):
    assert charge_tables.key_kind(text) == kind


@pytest.mark.parametrize("text", ["Your previous bill, due 09/15/2026, is past due.", "Late fee if not paid by 10/15/2026", "Previous Statement Date 09/01/2026",
                                  "Rent and Leasing Charges Due 10/01/2026", "Account Summary", "Billing Period 08/15/2026 - 09/14/2026", "Minimum Payment Due 25.00"])
def test_a_key_word_inside_a_sentence_or_after_other_words_is_no_key_line(text):
    assert charge_tables.key_kind(text) is None


# === SC-104: nothing dropped silently =========================================================================================

LABEL_AND_AMOUNT = re.compile(r"-?\(?\$?[\d,]+(?:\.\d+)?\)?")


def label_and_amount_lines(pages):
    """The lines of a page that print a label at x 40 and an amount in an item of their own, counted from the fixture's item list."""
    count = 0
    for page in pages:
        rows = {}
        for x, y, text, *_ in page["items"]:
            rows.setdefault(y, []).append((x, text))
        count += sum(1 for items in rows.values() if any(x <= 52 for x, _ in items) and any(x > 52 and LABEL_AND_AMOUNT.fullmatch(text) for x, text in items))
    return count


def test_sc104_step1_a_stray_amount_is_one_unplaced_line_and_the_usage_history_gives_nothing(reader):
    result = reader("UTIL-STRAY")
    reading = charge_tables.read(result)
    assert [(item.page, "Paperless billing saves paper" in item.text and "2.00" in item.text) for item in reading.unplaced] == [(1, True)]
    assert len(reading.tables) == 1 and facts(reading.tables[0]) == bf.UTIL_ENGINE_ROWS
    assert len(reading.other_tables) == 1 and reading.other_tables[0].totals == []
    history = reading.other_tables[0]
    assert [column.kind for column in history.columns] == ["integer", "integer"]
    assert [(row.label, *[row.amounts[column.id].text for column in history.columns]) for row in history.rows] == bf.UTIL_ENGINE_HISTORY
    assert all(row.usage == {} and row.stray == [] for row in history.rows)
    # Accounting: 4 rows + 0 totals + 6 anchors + 12 other-table rows + 1 unplaced = 23 = every label-and-amount line of the page.
    counted = (sum(len(table.rows) + len(table.totals) for table in reading.tables) + len(reading.anchors) + sum(len(table.rows) for table in reading.other_tables)
               + len(reading.unplaced))
    assert counted == 4 + 0 + 6 + 12 + 1 == 23 == label_and_amount_lines(bf.FIXTURES["UTIL-STRAY"]())


@pytest.mark.parametrize("name", ["BL-UTIL", "BL-PHONE", "BL-RENT", "UTIL-LASTYEAR", "UTIL-SHUF"])
def test_sc104_every_label_and_amount_line_is_accounted_for_in_the_other_fixtures(reader, name):
    reading = engine_of(reader, name)
    counted = (sum(len(table.rows) + len(table.totals) for table in reading.tables) + len(reading.anchors)
               + sum(len(table.rows) for table in reading.other_tables) + len(reading.unplaced))
    assert counted == label_and_amount_lines(bf.FIXTURES[name]()) - sum(1 for _ in reading.late_lines)


# === G7: anchor words inside a sentence =====================================================================================

def test_g7_a_sentence_holding_an_anchor_phrase_is_no_anchor_and_no_row_but_an_unplaced_line(reader):
    reading = engine_of(reader, "UTIL-SENTENCE")
    assert anchors_of(reading) == bf.UTIL_ENGINE_ANCHORS
    assert facts(reading.tables[0]) == bf.UTIL_ENGINE_ROWS and reading.tables[0].totals == []
    assert [(item.page, "Your previous balance was paid in full" in item.text and "82.10" in item.text) for item in reading.unplaced] == [(1, True)]


def test_g7_a_charge_row_whose_label_has_a_short_anchor_word_stays_a_row(reader):
    # BL-PHONE's Device Payment holds the word of the payments anchors and is a row (EXP-PHONE).
    table = engine_of(reader, "BL-PHONE").tables[0]
    assert "Device Payment" in [row.label for row in table.rows]


# === SC-114 step 1: a page with no charge table ==============================================================================

def test_sc114_step1_page_two_has_no_charge_table_but_its_stub_is_still_an_amount_due_anchor(reader):
    reading = engine_of(reader, "UTIL-2P")
    assert [table.pages for table in reading.tables] == [[1]] and reading.pages_without_tables == [2]
    assert facts(reading.tables[0]) == bf.UTIL_ENGINE_ROWS
    assert [(anchor.page, anchor.kind, anchor.token.text) for anchor in reading.anchors][-1] == (2, "amount_due", "99.55")
    assert reading.unplaced == []  # The prose sentence on page 2 is no label-and-amount line.


# === Pages: a table continues over pages; layout-free pages are not read =====================================================

def test_a_table_whose_rows_fit_the_same_columns_on_the_next_pages_continues(reader):
    reading = engine_of(reader, "BL-MULTI")
    assert len(reading.tables) == 1 and reading.tables[0].pages == [1, 2, 3]
    assert [row.page for row in reading.tables[0].rows] == [1, 1, 1, 2, 2, 2, 3, 3, 3]
    assert [row.label for row in reading.tables[0].rows[:3]] == ["Customer Charge", "Energy Charge", "State Tax"]
    assert len(reading.anchors) == 18 and reading.pages_without_tables == []


def test_a_usage_history_table_under_the_charge_table_columns_of_the_page_before_is_a_table_of_its_own(reader):
    reading = engine_of(reader, "BL-REMIT")
    assert [table.pages for table in reading.tables] == [[1]] and [table.pages for table in reading.other_tables] == [[2]]
    assert reading.pages_without_tables == [2]
    assert len(reading.other_tables[0].rows) == 12


def test_two_bills_printed_on_one_page_stay_one_reading_with_every_line_accounted_for(reader):
    reading = engine_of(reader, "BL-TWOONPAGE")
    assert len(reading.tables) == 1 and len(reading.tables[0].rows) == 6 and len(reading.anchors) == 12


# === Determinism =============================================================================================================

def test_the_same_reading_gives_the_same_tables_every_time(reader):
    result = reader("BL-UTIL")
    assert serialized(charge_tables.read(result)) == serialized(charge_tables.read(result))


def test_the_order_the_pdf_prints_its_items_in_does_not_change_the_tables(tmp_path):
    pages = bf.FIXTURES["BL-PHONE"]()
    items = list(pages[0]["items"])
    random.Random(7).shuffle(items)
    (tmp_path / "shuffled").mkdir()
    (tmp_path / "plain").mkdir()
    shuffled = fx.read_pdf(tmp_path / "shuffled", [{**pages[0], "items": items}])
    plain = fx.read_pdf(tmp_path / "plain", pages)
    one, two = charge_tables.read(shuffled), charge_tables.read(plain)
    assert [facts(table) for table in one.tables] == [facts(table) for table in two.tables] == [bf.PHONE_ENGINE_ROWS]
    assert anchors_of(one) == anchors_of(two) == bf.PHONE_ENGINE_ANCHORS


def test_a_page_read_without_its_layout_is_not_read(reader):
    bare = reader("BL-UTIL").model_copy(deep=True)
    for page in bare.pages:
        page.layout = None
    reading = charge_tables.read(bare)
    assert (reading.tables, reading.other_tables, reading.anchors, reading.unplaced, reading.pages_without_tables) == ([], [], [], [], [])


# === SL-02: roles, money off, the rate rule, the guesses and the adapter ====================================================

def bills_of(reader, source):
    return bill_tables.read(reader(source))


def roles_by_edge(reader, source, table=0):
    """({the contract's column edge (r330, r420 or r520): its role}, how the roles were decided). A column's extent ends up to 1.6 pt short of its edge (a
    word ending in a letter or a `1`: SL-01 note 10), so each is matched to the nearest edge within 3 pt."""
    result = reader(source)
    bills = bill_tables.read(result)
    edges = {}
    for edge, role in zip(right_edges(result, bills.reading.tables[table]), bills.roles[table].roles.values()):
        near = min((bf.USAGE, bf.RATE, bf.CHARGE), key=lambda contract: abs(contract - edge))
        assert abs(near - edge) <= 3, edge
        edges[near] = role
    return edges, bills.roles[table].decided_by


def cell_texts(row):
    return [cell.quote for cell in row.cells]


def evidence_texts(result, number=1):
    return PageMap(result.pages[number - 1]).text


def kinds_of(bills):
    return [guess.kind for guess in bills.guesses]


# --- The rate rule (SC-110 step 6's unit list; FR-110, D21, D25) -------------------------------------------------------------------

@pytest.mark.parametrize("text, minor, kept", [
    ("0.1430", 14, True), ("0.1450", 15, True), ("0.1449", 14, True), ("0.1451", 15, True), ("0.0050", 1, True), ("0.125", 13, True),
    ("0.1200", 12, False), ("0.1500", 15, False), ("0.12", 12, False), ("13.00", 1300, False), ("0.0049", 0, True), ("1,234.5678", 123457, True)])
def test_sc110_step6_the_rate_rule_judges_the_value_not_the_printed_digits(text, minor, kept):
    rate = bill_tables.printed_rate(text, "USD")
    assert (rate.minor, rate.text) == (minor, text if kept else None)


def test_the_rate_rule_keeps_the_text_exactly_as_printed_and_follows_the_currency():
    assert bill_tables.printed_rate("$0.1430", "USD") == bill_tables.PrintedRate(14, "$0.1430")
    assert bill_tables.printed_rate("150", "JPY") == bill_tables.PrintedRate(150, None)  # Yen has no minor unit: a whole number is exact.
    assert bill_tables.printed_rate("0.5", "JPY") == bill_tables.PrintedRate(1, "0.5")  # Half up, not half even (which would give 0).
    assert bill_tables.printed_rate("1.2345", "KWD") == bill_tables.PrintedRate(1235, "1.2345")  # Three minor digits.
    assert bill_tables.printed_rate("1.234", "KWD") == bill_tables.PrintedRate(1234, None)


def test_the_rate_rule_never_raises_a_precision_issue_and_refuses_only_what_is_no_number():
    for text in ("0.1430", "0.123456789", "3.14159"):
        bill_tables.printed_rate(text, "USD")
    with pytest.raises(ValueError):
        bill_tables.printed_rate("kWh", "USD")


@pytest.mark.parametrize("name, minor, kept", [("BL-UTIL", 14, "0.1430"), ("UTIL-HALF", 15, "0.1450"), ("UTIL-15", 15, None), ("UTIL-125", 13, "0.125")])
def test_sc110_step6_the_rate_the_engine_reads_from_the_page_gives_the_contracts_minor_units(reader, name, minor, kept):
    bills = bills_of(reader, name)
    assert bills.roles[0].decided_by == "product"  # Judged on the printed rate: 140 x 0.1430 = 20.02, 140 x 0.1450 = 20.30, 140 x 0.125 = 17.50.
    rate = bill_tables.printed_rate(cell_texts(bills.adapted[0].rows[1])[2], "USD")
    assert (rate.minor, rate.text) == (minor, kept)


# --- SC-105: which column is the charge ----------------------------------------------------------------------------------------

def test_sc105_a_columns_shuffled_the_product_rule_finds_charge_quantity_and_rate_wherever_they_sit(reader):
    roles, decided_by = roles_by_edge(reader, "UTIL-SHUF")
    assert roles == {bf.USAGE: "charge", bf.RATE: "quantity", bf.CHARGE: "unit_price"} and decided_by == "product"
    bills = bills_of(reader, "UTIL-SHUF")
    assert bills.guesses == [] and bills.notes == []
    # The quantity keeps its unit as printed; the cells are in column order, the charge first.
    assert [cell_texts(row)[1:] for row in bills.adapted[0].rows] == [["60.00", "500 kWh", "0.1200"], ["20.02", "140 kWh", "0.1430"], ["12.00", "", ""], ["5.53", "", ""]]
    assert bills.adapted[0].roles == {1: "charge", 2: "quantity", 3: "unit_price"}


def test_sc105_b_without_headings_the_roles_and_the_cells_are_the_same_and_no_guess_is_made(reader):
    shuffled, headless = bills_of(reader, "UTIL-SHUF"), bills_of(reader, "BL-HEADLESS")
    assert [role.roles for role in shuffled.roles] == [role.roles for role in headless.roles]
    assert headless.roles[0].decided_by == "product" and headless.guesses == [] and headless.notes == []
    assert [cell_texts(row)[1:] for row in headless.adapted[0].rows] == [cell_texts(row)[1:] for row in shuffled.adapted[0].rows]


@pytest.mark.parametrize("name", ["BL-UTIL", "UTIL-2L", "UTIL-ODD", "UTIL-NOHEAD"])
def test_sc105_the_heading_wording_never_changes_the_roles(reader, name):
    roles, decided_by = roles_by_edge(reader, name)
    assert roles == {bf.USAGE: "quantity", bf.RATE: "unit_price", bf.CHARGE: "charge"} and decided_by == "product"


@pytest.mark.parametrize("name", ["UTIL-LASTYEAR", "UTIL-LASTYEAR-C2"])
def test_sc105_c_a_this_bill_and_last_year_pair_the_sums_choose_this_bill_with_or_without_headings(reader, name):
    roles, decided_by = roles_by_edge(reader, name)
    assert roles == {bf.RATE: "charge", bf.CHARGE: "other"} and decided_by == "sum"  # Last Year (r520) is the right-most: the sums, not the position, decide.
    bills = bills_of(reader, name)
    assert bills.guesses == [] and bills.notes == []
    assert [(row.label, cell_texts(row)[1:]) for row in bills.adapted[0].rows][0] == ("Energy Charge", ["80.02", "72.15"])


def test_sc105_step4_two_columns_that_both_add_up_and_no_heading_the_right_most_is_the_charge_and_a_guess_says_so(reader):
    pages = bf.role_pages(rows=[("Service", (420, "10.00"), (520, "10.00")), ("Fee", (420, "5.00"), (520, "5.00"))], summary=[("New Charges", "15.00"), ("Amount Due", "15.00")])
    bills = bill_tables.read(reader(pages))
    assert [role.decided_by for role in bills.roles] == ["guess"]
    assert list(bills.roles[0].roles.values()) == ["other", "charge"]
    [guess] = bills.guesses
    assert (guess.kind, guess.page, guess.table_id) == ("charge_column", 1, bills.reading.tables[0].id)
    assert "right-most" in guess.text and guess.text.startswith("Page 1:") and bills.notes == [guess.text]


def test_sc105_step4_with_headings_previous_and_current_the_heading_decides_and_there_is_no_guess(reader):
    pages = bf.role_pages(heads=[(420, "Previous"), (520, "Current")], rows=[("Service", (420, "10.00"), (520, "10.00")), ("Fee", (420, "5.00"), (520, "5.00"))],
                          summary=[("New Charges", "15.00"), ("Amount Due", "15.00")])
    bills = bill_tables.read(reader(pages))
    assert list(bills.roles[0].roles.values()) == ["other", "charge"] and bills.roles[0].decided_by == "heading" and bills.guesses == []
    flipped = bf.role_pages(heads=[(420, "This Bill"), (520, "Last Year")], rows=[("Service", (420, "10.00"), (520, "10.00")), ("Fee", (420, "5.00"), (520, "5.00"))],
                            summary=[("New Charges", "15.00"), ("Amount Due", "15.00")])
    bills = bill_tables.read(reader(flipped))
    assert list(bills.roles[0].roles.values()) == ["charge", "other"] and bills.roles[0].decided_by == "heading" and bills.guesses == []  # Not the right-most.


def test_sc105_headings_are_the_only_guide_when_the_numbers_decide_nothing(reader):
    rows = [("Service", (420, "12.00"), (520, "10.00")), ("Fee", (420, "6.00"), (520, "5.00"))]  # Neither column adds up to anything printed.
    one = bill_tables.read(reader(bf.role_pages(heads=[(420, "Last Year"), (520, "This Bill")], rows=rows)))
    two = bill_tables.read(reader(bf.role_pages(heads=[(420, "Amount"), (520, "Previous")], rows=rows)))
    assert (list(one.roles[0].roles.values()), one.roles[0].decided_by, one.guesses) == (["other", "charge"], "heading", [])
    assert (list(two.roles[0].roles.values()), two.roles[0].decided_by, two.guesses) == (["charge", "other"], "heading", [])


def test_sc105_with_nothing_to_decide_the_right_most_is_taken_and_a_guess_of_the_column_kind_is_made(reader):
    bills = bill_tables.read(reader(bf.role_pages(rows=[("Service", (420, "12.00"), (520, "10.00")), ("Fee", (420, "6.00"), (520, "5.00"))])))
    assert list(bills.roles[0].roles.values()) == ["other", "charge"] and bills.roles[0].decided_by == "guess"
    assert kinds_of(bills) == ["charge_column"] and "right-most" in bills.notes[0]


def test_sc105_printed_subtotals_that_each_equal_the_rows_they_cover_decide_when_no_summary_amount_does(reader):
    rows = [("Service", (420, "10.00"), (520, "20.00")), ("Fee", (420, "5.00"), (520, "7.00")), ("Total", (420, "15.00"), (520, "99.00"))]
    bills = bill_tables.read(reader(bf.role_pages(rows=rows)))
    assert list(bills.roles[0].roles.values()) == ["charge", "other"] and bills.roles[0].decided_by == "subtotals" and bills.guesses == []


def test_sc105_a_credits_row_counts_negative_in_the_sums_so_only_the_right_column_adds_up(reader):
    rows = [("Service", (420, "10.00"), (520, "10.00")), ("Fee", (420, "5.00"), (520, "5.00")), ("Account Credits",), ("Autopay Discount", (420, "4.00"), (520, "5.00"))]
    pages = bf.role_pages(rows=rows, summary=[("New Charges", "10.00")])  # `Account Credits` prints no amount: a section title. 10 + 5 - 5 = 10, but 10 + 5 - 4 = 11.
    bills = bill_tables.read(reader(pages))
    assert list(bills.roles[0].roles.values()) == ["other", "charge"] and bills.roles[0].decided_by == "sum" and bills.guesses == []
    assert [row.money_off for row in bills.adapted[0].rows] == [False, False, True]


def test_sc105_the_sum_target_is_the_new_charges_else_the_worked_out_value_else_the_amount_due(reader):
    rows = [("Service", (420, "10.00"), (520, "11.00")), ("Fee", (420, "5.00"), (520, "7.00"))]  # r420 adds up to 15.00, r520 to 18.00.
    worked_out = bf.role_pages(rows=rows, summary=[("Previous Balance", "100.00"), ("Payments", "-100.00"), ("Total Amount Due", "18.00")])
    amount_due = bf.role_pages(rows=rows, summary=[("Total Amount Due", "15.00")])
    new_charges = bf.role_pages(rows=rows, summary=[("Previous Balance", "100.00"), ("New Charges", "15.00"), ("Total Amount Due", "115.00")])
    for pages, expected in ((worked_out, ["other", "charge"]), (amount_due, ["charge", "other"]), (new_charges, ["charge", "other"])):
        bills = bill_tables.read(reader(pages))
        assert (list(bills.roles[0].roles.values()), bills.roles[0].decided_by, bills.guesses) == (expected, "sum", [])


def test_sc105_a_late_amount_is_never_a_sum_target(reader):
    rows = [("Service", (420, "10.00"), (520, "11.00")), ("Fee", (420, "5.00"), (520, "7.00"))]  # r420 adds up to 15.00 (the new charges), r520 to 18.00.
    late = bf.left(560, "If paid after 10/15/2026, pay") + bf.heading(560, (520, "18.00"))  # Were it a target both columns would add up and the right-most win.
    bills = bill_tables.read(reader(bf.role_pages(rows=rows, summary=[("New Charges", "15.00")], extra=late)))
    assert list(bills.roles[0].roles.values()) == ["charge", "other"] and bills.roles[0].decided_by == "sum" and bills.guesses == []


def test_sc105_summary_amounts_on_another_page_of_the_same_bill_are_sum_targets(reader):
    """FR-103 lets a summary be printed on another page, and FR-105 b judges the bill's new charges: page 2 (no key line of its own) continues the bill, so its
    figure that r420 adds up to decides the column. (SL-11: this test pinned the plan's earlier restriction to the table's own pages; plan.md is not edited.)"""
    rows = [("Service", (420, "10.00"), (520, "11.00")), ("Fee", (420, "5.00"), (520, "7.00"))]
    pages = [*bf.role_pages(rows=rows), bf.page_of(bf.amounts_at(700, "New Charges", (bf.CHARGE, "15.00")))]
    bills = bill_tables.read(reader(pages))
    assert bills.reading.tables[0].pages == [1] and bills.roles[0].decided_by == "sum" and list(bills.roles[0].roles.values()) == ["charge", "other"]
    assert bills.guesses == []


def test_sc105_a_quantity_column_of_whole_numbers_and_a_rate_with_the_charge_are_found_by_the_product(reader):
    rows = [("Widget", (330, "3"), (420, "2.50"), (520, "7.50")), ("Gadget", (330, "2"), (420, "10.00"), (520, "20.00")), ("Fee", (520, "5.00"))]
    bills = bill_tables.read(reader(bf.role_pages(rows=rows)))
    assert list(bills.roles[0].roles.values()) == ["quantity", "unit_price", "charge"] and bills.roles[0].decided_by == "product"
    assert [row.kind for row in bills.reading.tables[0].columns] == ["integer", "amount", "amount"]


def test_sc105_of_two_amount_columns_the_one_printing_fewer_decimals_is_the_quantity(reader):
    rows = [("Bulk", (330, "12.5"), (420, "0.2400"), (520, "3.00")), ("Pack", (330, "10.0"), (420, "0.2500"), (520, "2.50"))]
    bills = bill_tables.read(reader(bf.role_pages(rows=rows)))
    assert list(bills.roles[0].roles.values()) == ["quantity", "unit_price", "charge"]


def test_sc105_one_row_that_breaks_the_product_means_no_product_roles(reader):
    rows = [("Widget", (330, "3"), (420, "2.50"), (520, "7.50")), ("Gadget", (330, "2"), (420, "10.00"), (520, "21.00"))]
    bills = bill_tables.read(reader(bf.role_pages(rows=rows)))
    assert bills.roles[0].decided_by != "product" and "quantity" not in bills.roles[0].roles.values()
    assert list(bills.roles[0].roles.values()).count("charge") == 1


def test_sc105_one_amount_column_is_the_charge(reader):
    """FR-105 (d) on a table whose sums decide nothing. BL-MULTI's one column over three bills adds up to each bill's own new charges, so the sum rule,
    judged per bill, decides it first (FR-105 b before d; it read `single` while the sum was judged over the whole table)."""
    pages = bf.role_pages(rows=[("Service", (520, "10.00")), ("Fee", (520, "5.00"))], summary=[("New Charges", "99.00"), ("Amount Due", "99.00")])
    one = bill_tables.read(reader(pages))
    assert [role.decided_by for role in one.roles] == ["single"] and list(one.roles[0].roles.values()) == ["charge"] and one.guesses == []
    bills = bills_of(reader, "BL-MULTI")
    assert [role.decided_by for role in bills.roles] == ["sum"] and list(bills.roles[0].roles.values()) == ["charge"] and bills.reading.tables[0].pages == [1, 2, 3]


def test_sc105_a_table_whose_headings_name_every_column_as_something_else_is_another_table(reader):
    rows = [("Jan", (420, "12.00"), (520, "10.00")), ("Feb", (420, "6.00"), (520, "5.00"))]
    bills = bill_tables.read(reader(bf.role_pages(heads=[(420, "Last Year"), (520, "Prior")], rows=rows)))
    assert bills.reading.tables == [] and len(bills.reading.other_tables) == 1 and bills.roles == [] and bills.adapted == [] and bills.guesses == []
    assert bills.reading.pages_without_tables == [1] and bills.reading.unplaced == []


def test_sc105_every_charge_table_of_every_contract_fixture_has_exactly_one_charge_column_and_no_guess(reader):
    for name in NATIVE:
        bills = bills_of(reader, name)
        assert bills.guesses == [] and bills.notes == [], name
        assert len(bills.roles) == len(bills.reading.tables), name
        for table, roles in zip(bills.reading.tables, bills.roles):
            assert roles.table_id == table.id and set(roles.roles) == {column.id for column in table.columns}, name
            assert list(roles.roles.values()).count("charge") == 1 and set(roles.roles.values()) <= set(bill_tables.ROLES), name
            assert all(column.kind == "amount" for column in table.columns if roles.roles[column.id] == "charge"), name
        assert bills.pages == {page for table in bills.reading.tables for page in table.pages}, name


# --- SC-106: money off -----------------------------------------------------------------------------------------------------

def phone_row(reader, **variant):
    """BL-PHONE with the Autopay Discount printed as `variant` says: (the bills, its row)."""
    bills = bill_tables.read(reader(bf.phone_pages(**variant)))
    return bills, next(row for row in bills.reading.tables[0].rows if row.label == "Autopay Discount")


@pytest.mark.parametrize("variant, text, section", [
    ({}, "-5.00", "Account Credits"), ({"discount": "(5.00)"}, "(5.00)", "Account Credits"), ({"discount": "5.00-"}, "5.00-", "Account Credits"),
    ({"discount": "5.00 CR"}, "5.00 CR", "Account Credits"), ({"discount": "5.00"}, "5.00", "Account Credits")])
def test_sc106_step4_a_minus_parentheses_a_trailing_minus_cr_or_an_unsigned_amount_under_credits_is_money_off_of_five(reader, variant, text, section):
    bills, row = phone_row(reader, **variant)
    [token] = row.amounts.values()
    assert token.text == text and row.section == section
    assert bill_tables.signed(token, row.section) == Decimal("-5.00")
    assert bill_tables.money_off(row, bills.roles[0]) is True
    assert [entry.money_off for entry in bills.adapted[0].rows if not entry.total] == [False, False, False, False, True]
    assert bills.roles[0].decided_by == "sum" and bills.guesses == []  # The signed rows add up to 118.50, the new charges.


def test_sc106_the_other_rows_of_the_phone_bill_are_charges(reader):
    bills, _ = phone_row(reader)
    assert [bill_tables.money_off(row, bills.roles[0]) for row in bills.reading.tables[0].rows] == [False, False, False, False, True]


@pytest.mark.parametrize("title", ["Account Credits", "Discounts", "Adjustment", "Credit", "Your discounts"])
def test_sc106_an_unsigned_row_under_a_credits_discounts_or_adjustments_section_is_money_off(reader, title):
    bills, row = phone_row(reader, discount="5.00", credits=title)
    assert row.section == title and bill_tables.money_off(row, bills.roles[0]) is True


@pytest.mark.parametrize("title", ["Account Charges", "Discounted Items", "Creditworthy Services", "Accredited"])
def test_sc106_other_section_titles_make_an_unsigned_row_a_charge(reader, title):
    bills, row = phone_row(reader, discount="5.00", credits=title)
    assert row.section == title and bill_tables.money_off(row, bills.roles[0]) is False


def test_sc106_a_signed_row_in_a_credits_section_is_negative_once(reader):
    bills, row = phone_row(reader, discount="-5.00")
    assert bill_tables.signed(next(iter(row.amounts.values())), "Credits") == Decimal("-5.00")
    assert bill_tables.signed(next(iter(row.amounts.values())), None) == Decimal("-5.00")


def test_sc106_a_debit_marker_is_a_charge_even_under_credits(reader):
    token = charge_tables.Token("amount", ["w"], (0, 0, 0, 0), "5.00 DR", (Decimal("5.00"), "debit", None))
    assert bill_tables.signed(token, "Account Credits") == Decimal("5.00")


@pytest.mark.parametrize("title", ["Account Credits", "Discounts", "Adjustments"])
def test_sl11_f2_an_explicit_plus_under_a_money_off_section_is_a_charge_in_the_row_the_sums_and_the_adapter(reader, title):
    bills, row = phone_row(reader, discount="+5.00", credits=title)
    [token] = row.amounts.values()
    assert token.text == "+5.00" and token.value[1] == "plus" and row.section == title
    assert bill_tables.signed(token, row.section) == Decimal("5.00")
    assert bill_tables.money_off(row, bills.roles[0]) is False
    assert [entry.money_off for entry in bills.adapted[0].rows if not entry.total] == [False] * 5


@pytest.mark.parametrize("title", ["Account Credits", "Discounts", "Adjustments"])
def test_sl11_f2_a_plus_row_under_a_money_off_section_counts_positive_so_the_sum_decides_the_column(reader, title):
    rows = [("Service", (420, "10.00"), (520, "10.00")), ("Fee", (420, "5.00"), (520, "5.00")), (title,), ("Reversal", (420, "+4.00"), (520, "+5.00"))]
    bills = bill_tables.read(reader(bf.role_pages(rows=rows, summary=[("New Charges", "20.00")])))  # 10 + 5 + 5 = 20, but 10 + 5 + 4 = 19.
    assert list(bills.roles[0].roles.values()) == ["other", "charge"] and bills.roles[0].decided_by == "sum" and bills.guesses == []
    assert [row.money_off for row in bills.adapted[0].rows] == [False, False, False]


def other_page_summary_pages():
    """One bill of two pages: page 1 holds a headless table with a charge column (r420: 10.00, 20.00) and a comparison column (r520: 100.00, 200.00); the
    bill's New Charges and Amount Due are printed only on page 2 (FR-103 allows a summary on another page of the bill)."""
    first = [*bf.left(780, "CITY POWER & WATER"), *bf.left(768, "Account Number 1234-5678-9012"), *bf.left(756, "Due Date 07/20/2026"),
             *bf.amounts_at(600, "Service", (420, "10.00"), (520, "100.00")), *bf.amounts_at(584, "Fee", (420, "20.00"), (520, "200.00"))]
    second = [*bf.left(780, "Summary of your bill"), *bf.amounts_at(700, "New Charges", (520, "30.00")), *bf.amounts_at(684, "Amount Due", (520, "30.00"))]
    return [bf.page_of(first), bf.page_of(second)]


def test_sl11_f5_a_bills_summary_on_another_page_decides_the_column_with_no_guess(reader):
    bills = bill_tables.read(reader(other_page_summary_pages()))
    [table] = bills.reading.tables
    assert table.pages == [1] and {anchor.page for anchor in bills.reading.anchors} == {2}
    assert list(bills.roles[0].roles.values()) == ["charge", "other"] and bills.roles[0].decided_by == "sum" and bills.guesses == []
    assert [cell_texts(row)[1:] for row in bills.adapted[0].rows] == [["10.00", "100.00"], ["20.00", "200.00"]]


def test_sl11_f5_a_summary_on_the_next_bills_page_does_not_decide_this_bills_column(reader):
    """The other side: page 2 is another bill (another due date), so its New Charges are not the first bill's target and the columns stay a guess."""
    pages = other_page_summary_pages()
    pages[0]["items"] = [*pages[0]["items"], *bf.amounts_at(500, "Amount Due", (520, "7.00"))]  # Page 1 prints its own amount due, so it is a bill of its own.
    pages[1]["items"] = [*bf.left(790, "Due Date 08/20/2026"), *pages[1]["items"]]
    bills = bill_tables.read(reader(pages))
    assert bills.roles[0].decided_by == "guess" and kinds_of(bills) == ["charge_column"]


# --- The adapter (plan P4): ids, line ids, wrapped label lines, title line ids ------------------------------------------------------

def test_p4_the_adapter_makes_one_table_in_the_shape_record_reads_with_a_header_row_and_a_cell_per_column(reader):
    bills = bills_of(reader, "BL-UTIL")
    [table] = bills.adapted
    assert (table.id, table.page, table.pages, table.source) == (bills.reading.tables[0].id, 1, [1], "bill_engine")
    assert table.roles == {1: "quantity", 2: "unit_price", 3: "charge"}
    [header] = table.header_rows
    assert header.id == f"{table.id}-row-0" and [cell.quote for cell in header.cells] == ["", "Usage", "Rate", "Charge"]
    assert [row.id for row in table.rows] == [f"{table.id}-row-{number}" for number in (1, 2, 3, 4)]
    assert [cell_texts(row) for row in table.rows] == [["Energy Tier 1", "500 kWh", "0.1200", "60.00"], ["Energy Tier 2", "140 kWh", "0.1430", "20.02"],
                                                       ["Customer Charge", "", "", "12.00"], ["State Tax", "", "", "5.53"]]
    for row in table.rows:
        assert len(row.cells) == 4 and row.total is False and row.page == 1 and row.money_off is False
        assert [cell.id for cell in row.cells] == [f"{row.id}-cell-{number}" for number in range(4)]
    assert [(row.section, row.label) for row in table.rows][2:] == [("Electric Charges", "Customer Charge"), ("Taxes and Fees", "State Tax")]


def test_p4_every_cell_quotes_the_words_it_cites_and_a_blank_cell_cites_nothing(reader):
    result = reader("BL-UTIL")
    bills = bill_tables.read(result)
    words = PageMap(result.pages[0]).words
    for row in bills.adapted[0].rows:
        for cell in row.cells:
            assert " ".join(words[word_id] for word_id in cell.word_ids) == cell.quote
            assert (cell.word_ids == []) == (cell.quote == "")


def test_p4_a_rows_line_ids_are_evidence_lines_holding_its_words_with_the_label_line_first(reader):
    result = reader("BL-UTIL")
    texts = evidence_texts(result)
    row = bill_tables.read(result).adapted[0].rows[1]
    assert row.line_id == row.line_ids[0] and set(row.line_ids) <= set(texts)
    assert texts[row.line_ids[0]].startswith("Energy Tier 2")
    held = " ".join(texts[line_id] for line_id in row.line_ids)
    assert all(text in held for text in ("140 kWh", "0.1430", "20.02"))
    assert not any("Energy Tier 1" in texts[line_id] for line_id in row.line_ids)
    for cell in row.cells:
        assert cell.line_id in row.line_ids
        assert cell.source_line_ids and set(cell.source_line_ids) <= {line.id for line in result.pages[0].layout.lines}


def test_p4_a_wrapped_label_lists_both_lines_label_first_and_the_cell_cites_both(reader):
    result = reader("BL-PHONE")
    texts = evidence_texts(result)
    bills = bill_tables.read(result)
    row = next(row for row in bills.adapted[0].rows if row.label.startswith("International Pack"))
    assert row.label == "International Pack (Canada and Mexico)"
    assert len(row.line_ids) == 2 and texts[row.line_ids[0]].startswith("International Pack") and texts[row.line_ids[1]] == "(Canada and Mexico)"
    assert row.line_id == row.line_ids[0] and cell_texts(row)[0] == row.label and cell_texts(row)[1] == "8.51"
    assert [text for _, text in row.cells[0].cites] == ["International Pack", "(Canada and Mexico)"]
    assert [line for line, _ in row.cells[0].cites] == row.line_ids


def test_p4_a_label_on_one_line_has_no_separate_cites(reader):
    row = bills_of(reader, "BL-PHONE").adapted[0].rows[0]
    assert row.cells[0].cites is None


def test_p4_title_line_ids_and_phone_flags_for_the_holder_titles(reader):
    result = reader("BL-PHONE")
    texts = evidence_texts(result)
    rows = bill_tables.read(result).adapted[0].rows
    assert [(row.label, texts[row.title_line_id] if row.title_line_id else None, row.title_phone) for row in rows] == [
        ("Unlimited Plan", "Alex 555-201-1111", True), ("Device Payment", "Alex 555-201-1111", True), ("Total for Alex", None, False),
        ("Basic Plan", "Blair 555-202-2222", True), ("International Pack (Canada and Mexico)", "Blair 555-202-2222", True), ("Total for Blair", None, False),
        ("Autopay Discount", "Account Credits", False)]
    assert rows[0].title_line_id == rows[1].title_line_id != rows[3].title_line_id
    assert rows[0].title_line_id not in rows[0].line_ids  # The title line is Record's to add to the evidence (P5), not a line of the row.


def test_p4_totals_are_rows_flagged_total_with_their_cell_and_no_money_off(reader):
    rows = bills_of(reader, "BL-PHONE").adapted[0].rows
    totals = [row for row in rows if row.total]
    assert [(row.label, cell_texts(row)[1], row.id.rpartition("-")[2]) for row in totals] == [("Total for Alex", "79.99", "3"), ("Total for Blair", "43.51", "6")]
    assert not any(row.money_off for row in totals) and all(row.title_line_id is None for row in totals)


def test_p4_the_money_off_flag_is_on_the_credit_row_only(reader):
    assert [row.money_off for row in bills_of(reader, "BL-PHONE").adapted[0].rows] == [False, False, False, False, False, False, True]


def test_p4_a_usage_cell_that_forms_no_column_stays_in_the_label_and_the_row_has_one_amount_cell(reader):
    [table] = bills_of(reader, "BL-RENT").adapted
    assert [cell_texts(row) for row in table.rows] == [["Rent 10/01/2026 - 10/31/2026", "$1,450.00"], ["Water Usage 08/15/2026 - 09/14/2026 3,200 GAL", "$38.42"]]


def test_p4_a_table_over_several_pages_is_one_adapted_table_whose_rows_keep_their_pages(reader):
    [table] = bills_of(reader, "BL-MULTI").adapted
    assert table.pages == [1, 2, 3] and [row.page for row in table.rows] == [1, 1, 1, 2, 2, 2, 3, 3, 3]
    assert [row.id.rpartition("-")[2] for row in table.rows] == [str(number) for number in range(1, 10)]
    assert all(row.line_id.startswith(f"page-{row.page}-") for row in table.rows)


def test_p4_the_header_row_names_the_columns_by_their_heading_words(reader):
    [table] = bills_of(reader, "UTIL-2L").adapted
    assert [cell.quote for cell in table.header_rows[0].cells] == ["", "Usage (kWh)", "Rate per kWh", "This Charge"]


def test_p4_a_page_with_no_layout_gives_no_adapted_table(reader):
    bare = reader("BL-UTIL").model_copy(deep=True)
    for page in bare.pages:
        page.layout = None
    bills = bill_tables.read(bare)
    assert (bills.reading.tables, bills.roles, bills.adapted, bills.guesses, bills.engine_pages, bills.pages) == ([], [], [], [], set(), set())


def test_p4_engine_pages_lines_of_and_line_pages_describe_the_evidence(reader):
    bills = bills_of(reader, "UTIL-2P")
    assert bills.engine_pages == {1} and bills.pages == {1} and bills.line_pages == {1, 2}
    assert bills.reading.pages_without_tables == [2]
    result = reader("UTIL-2P")
    assert set(bills.lines_of) == {line.id for page in result.pages for line in page.layout.lines}
    assert set(bills.lines_of.values()) == set(evidence_texts(result, 1)) | set(evidence_texts(result, 2))


# --- for_lines: what lies in one part ------------------------------------------------------------------------------------------

def part_ids(result, number, first=None, last=None):
    """The evidence line ids of one page, optionally from the line that starts with `first` to the one that starts with `last`."""
    texts = evidence_texts(result, number)
    ids = list(texts)
    start = next((position for position, line in enumerate(ids) if first and texts[line].startswith(first)), 0)
    stop = next((position for position, line in enumerate(ids) if last and texts[line].startswith(last)), len(ids) - 1)
    return ids[start:stop + 1]


def test_sc128_step8_a_table_cut_between_pages_gives_each_part_its_own_rows_anchors_and_pages(reader):
    result = reader("BL-MULTI")
    bills = bill_tables.read(result)
    for number in (1, 2, 3):
        part = bill_tables.for_lines(bills, part_ids(result, number))
        [table] = part.adapted
        assert [row.page for row in table.rows] == [number] * 3 and [row.id for row in table.rows] == [f"{bills.adapted[0].id}-row-{n}" for n in range(3 * number - 2, 3 * number + 1)]
        assert [row.page for row in part.reading.tables[0].rows] == [number] * 3 and [row.row for row in part.reading.tables[0].rows] == list(range(3 * number - 2, 3 * number + 1))
        assert {anchor.page for anchor in part.reading.anchors} == {number} and len(part.reading.anchors) == 6
        assert part.engine_pages == {number} and part.pages == {number}
        assert part.roles == bills.roles and part.reading.pages_without_tables == []


def test_for_lines_cuts_inside_a_page_at_the_row_the_part_ends_with(reader):
    result = reader("BL-UTIL")
    bills = bill_tables.read(result)
    part = bill_tables.for_lines(bills, part_ids(result, 1, last="Customer Charge"))
    assert [row.label for row in part.adapted[0].rows] == ["Energy Tier 1", "Energy Tier 2", "Customer Charge"]
    assert [row.label for row in part.reading.tables[0].rows] == ["Energy Tier 1", "Energy Tier 2", "Customer Charge"]
    assert [anchor.kind for anchor in part.reading.anchors] == ["previous_balance", "payments", "new_charges", "amount_due"]  # Not the late total or the stub.
    rest = bill_tables.for_lines(bills, part_ids(result, 1, first="Taxes and Fees"))
    assert [row.label for row in rest.adapted[0].rows] == ["State Tax"]
    assert [anchor.kind for anchor in rest.reading.anchors] == ["new_charges", "amount_due"] and len(rest.reading.other_tables) == 1
    assert part.reading.other_tables == []  # The usage history lies in the other part.


def test_for_lines_keeps_the_totals_of_the_part_and_drops_the_tables_of_other_parts(reader):
    result = reader("BL-PHONE")
    bills = bill_tables.read(result)
    part = bill_tables.for_lines(bills, part_ids(result, 1, last="Total for Alex"))
    assert [(row.label, row.total) for row in part.adapted[0].rows] == [("Unlimited Plan", False), ("Device Payment", False), ("Total for Alex", True)]
    assert [total.label for total in part.reading.tables[0].totals] == ["Total for Alex"]
    nothing = bill_tables.for_lines(bills, [])
    assert (nothing.adapted, nothing.reading.tables, nothing.roles, nothing.reading.anchors, nothing.engine_pages, nothing.notes) == ([], [], [], [], set(), [])


def test_for_lines_keeps_the_guesses_and_notes_of_the_tables_in_the_part_and_the_pages_without_tables(reader):
    pages = bf.role_pages(rows=[("Service", (420, "12.00"), (520, "10.00")), ("Fee", (420, "6.00"), (520, "5.00"))])
    result = reader(pages)
    bills = bill_tables.read(result)
    assert len(bills.guesses) == 1
    whole = bill_tables.for_lines(bills, part_ids(result, 1))
    assert whole.guesses == bills.guesses and whole.notes == bills.notes
    assert bill_tables.for_lines(bills, []).guesses == []
    plain = reader("UTIL-2P")
    both = bill_tables.read(plain)
    assert bill_tables.for_lines(both, part_ids(plain, 1) + part_ids(plain, 2)).reading.pages_without_tables == [2]
    assert bill_tables.for_lines(both, part_ids(plain, 1)).reading.pages_without_tables == []


def test_for_lines_does_not_change_what_it_was_given(reader):
    result = reader("BL-MULTI")
    bills = bill_tables.read(result)
    before = serialized(bills.reading), [serialized(role) for role in bills.roles], len(bills.adapted[0].rows)
    bill_tables.for_lines(bills, part_ids(result, 2))
    assert (serialized(bills.reading), [serialized(role) for role in bills.roles], len(bills.adapted[0].rows)) == before


# --- Determinism and the unchanged modules ---------------------------------------------------------------------------------------

def adapted_facts(bills):
    """The adapted tables as plain data (the adapter's rows are namespaces), for comparing two readings."""
    def plain(value):
        if hasattr(value, "__dict__"):
            return {key: plain(item) for key, item in vars(value).items()}
        if isinstance(value, (list, tuple)):
            return [plain(item) for item in value]
        if isinstance(value, set):
            return sorted(value)
        return value
    return json.dumps(plain(bills.adapted), sort_keys=True, default=str)


def test_the_same_reading_gives_the_same_roles_guesses_and_adapted_tables_every_time(reader):
    for source in ("BL-UTIL", "BL-PHONE", "BL-MULTI", bf.role_pages(rows=[("Service", (420, "12.00"), (520, "10.00")), ("Fee", (420, "6.00"), (520, "5.00"))])):
        result = reader(source)
        one, two = bill_tables.read(result), bill_tables.read(result)
        assert (serialized(one.reading), [serialized(role) for role in one.roles], [serialized(guess) for guess in one.guesses], adapted_facts(one)) == (
            serialized(two.reading), [serialized(role) for role in two.roles], [serialized(guess) for guess in two.guesses], adapted_facts(two))


def test_the_order_the_pdf_prints_its_items_in_does_not_change_the_roles_or_the_adapted_cells(tmp_path):
    pages = bf.FIXTURES["BL-UTIL"]()
    items = list(pages[0]["items"])
    random.Random(11).shuffle(items)
    (tmp_path / "shuffled").mkdir()
    (tmp_path / "plain").mkdir()
    one = bill_tables.read(fx.read_pdf(tmp_path / "shuffled", [{**pages[0], "items": items}]))
    two = bill_tables.read(fx.read_pdf(tmp_path / "plain", pages))
    assert [role.roles for role in one.roles] == [role.roles for role in two.roles] and [role.decided_by for role in one.roles] == ["product"]
    assert [cell_texts(row) for row in one.adapted[0].rows] == [cell_texts(row) for row in two.adapted[0].rows]


def test_reading_the_bill_does_not_change_what_the_pay_and_statement_engines_get(reader):
    """The statement and pay stub engines are not changed (FR-120): the new modules only read the saved reading, never write to it."""
    result = reader("BL-UTIL")
    before = result.model_dump_json()
    bill_tables.read(result)
    assert result.model_dump_json() == before


def test_the_guess_kinds_are_the_four_the_eval_counts():
    assert bill_tables.GUESS_KINDS == ("charge_column", "unclassified_row", "amount_due", "split_changed")


# --- A table that runs on over the pages of several bills (FR-128 with FR-102, FR-105 b, FR-106) ----------------------------------------------

def two_bills(first, second, extra=()):
    """Two one-page bills (MINI-BILL(1) and (2)) whose charge rows print in the same column, so the engine reads one table over both pages; `extra` (items)
    are added below page 1's charges."""
    return [bf.page_of([*bf.mini_items(first), *extra]), bf.page_of(bf.mini_items(second))]


def test_a_section_title_of_one_bill_does_not_reach_the_rows_of_the_next_bill(reader):
    """Generator case 56's defect, by hand: page 1 ends with `Account Credits`; page 2 is another bill (another due date) whose rows print no title, so none
    of them is money off."""
    pages = two_bills(1, 2, [*bf.left(548, "Account Credits"), *bf.amounts_at(532, "Paperless Credit", (bf.CHARGE, "2.50"))])
    bills = bill_tables.read(reader(pages))
    [table] = bills.reading.tables
    assert table.pages == [1, 2]  # One table over both bills: the case under test.
    rows = {(row.page, row.label): row for row in table.rows}
    assert rows[1, "Paperless Credit"].section == "Account Credits" and bill_tables.money_off(rows[1, "Paperless Credit"], bills.roles[0])
    second = [row for row in table.rows if row.page == 2]
    assert [row.label for row in second] == ["Customer Charge", "Energy Charge", "State Tax"]
    assert [(row.section, row.title) for row in second] == [(None, None)] * 3
    assert not [row for row in second if bill_tables.money_off(row, bills.roles[0])]
    assert not [row for adapted in bills.adapted for row in adapted.rows if row.page == 2 and row.money_off]


def test_a_section_title_carries_onto_the_next_page_of_the_same_bill(reader):
    """The other side of the rule: page 2 repeats bill 1's keys, so it is the same bill and its rows stay in the `Account Credits` section."""
    first = [*bf.mini_items(1, omit=("Total Current Charges", "Due Date", "Amount Due")), *bf.left(548, "Account Credits"),
             *bf.amounts_at(532, "Paperless Credit", (bf.CHARGE, "2.50"))]
    second = [*bf.left(780, "CITY POWER & WATER"), *bf.left(768, "Account Number 1234-5678-9012"), *bf.left(756, "Due Date 07/20/2026"),
              *bf.amounts_at(700, "Total Amount Due", (bf.CHARGE, "81.42")),  # An anchor between the keys and the rows: a key line is no title here (G14).
              *bf.amounts_at(620, "Loyalty Credit", (bf.CHARGE, "1.00")), *bf.amounts_at(604, "Referral Credit", (bf.CHARGE, "3.00"))]
    bills = bill_tables.read(reader([bf.page_of(first), bf.page_of(second)]))
    [table] = bills.reading.tables
    second = [row for row in table.rows if row.page == 2]
    assert table.pages == [1, 2] and [row.label for row in second] == ["Loyalty Credit", "Referral Credit"]
    assert [row.section for row in second] == ["Account Credits"] * 2 and all(bill_tables.money_off(row, bills.roles[0]) for row in second)


def test_sl11_f4_a_users_cut_inside_a_page_ends_the_credits_section_for_the_bill_after_it(reader):
    """Review round 1, finding 4, engine side: the user's boundary may be inside a page. Rows printed after it belong to the next bill, so the section title
    above the cut does not make them money off, and the bill after the cut is judged by its own rows and anchors."""
    items = [*bf.left(780, "CITY POWER & WATER"), *bf.left(768, "Account Number 1234-5678-9012"), *bf.left(756, "Due Date 07/20/2026"),
             *bf.amounts_at(700, "Amount Due", (bf.CHARGE, "10.00")), *bf.amounts_at(620, "Service", (bf.CHARGE, "10.00")), *bf.left(604, "Account Credits"),
             *bf.amounts_at(588, "Paperless Credit", (bf.CHARGE, "2.50")), *bf.left(540, "Due Date 08/20/2026"), *bf.amounts_at(524, "New Charges", (bf.CHARGE, "30.00")),
             *bf.amounts_at(508, "Amount Due", (bf.CHARGE, "30.00")), *bf.amounts_at(492, "Extra Service", (bf.CHARGE, "30.00"))]
    result = reader([bf.page_of(items)])
    texts = evidence_texts(result)
    cut = next(line for line, text in texts.items() if text.startswith("Due Date 08/20/2026"))
    whole = bill_tables.read(result)
    assert [(row.label, row.money_off) for row in whole.adapted[0].rows] == [("Service", False), ("Paperless Credit", True), ("Extra Service", True)]
    split = bill_tables.read(result, [next(iter(texts)), cut])
    assert [(row.label, row.money_off) for row in split.adapted[0].rows] == [("Service", False), ("Paperless Credit", True), ("Extra Service", False)]
    assert [row.section for row in split.reading.tables[0].rows][-1] is None


def lastyear_bill(due, rows, new_charges):
    """A one-page bill with a `This Bill` (r420) and a `Last Year` (r520, the right-most) column and no heading over them (UTIL-LASTYEAR-C2's shape)."""
    items = [*bf.left(780, "CITY POWER & WATER"), *bf.left(768, "Account Number 1234-5678-9012"), *bf.left(756, f"Due Date {due}")]
    items += bf.amounts_at(700, "New Charges", (bf.CHARGE, new_charges)) + bf.amounts_at(684, "Total Amount Due", (bf.CHARGE, new_charges))
    items += bf.left(620, "Electric Charges")
    for number, (label, this, last) in enumerate(rows):
        items += bf.amounts_at(588 - 16 * number, label, (bf.RATE, this), (bf.CHARGE, last))
    return bf.page_of(items)


def test_sc105_c_a_last_year_column_over_two_bills_is_other_the_sums_judged_per_bill(reader):
    """Generator cases 29, 33, 64 and 67's defect, by hand: one table over two bills; neither column's whole sum (97.55 + 86.00) is a bill's new charges, but
    `This Bill` adds up to each bill's own, so it is the charge although `Last Year` is right-most, and no guess is made."""
    pages = [lastyear_bill("07/20/2026", (("Energy Charge", "80.02", "72.15"), ("Customer Charge", "12.00", "12.00"), ("State Tax", "5.53", "4.98")), "97.55"),
             lastyear_bill("08/20/2026", (("Energy Charge", "70.00", "60.00"), ("Customer Charge", "12.00", "12.00"), ("State Tax", "4.00", "4.00")), "86.00")]
    result = reader(pages)
    bills = bill_tables.read(result)
    [table] = bills.reading.tables
    assert table.pages == [1, 2]  # One table over both bills: the case under test.
    edges = [min((bf.RATE, bf.CHARGE), key=lambda contract: abs(contract - edge)) for edge in right_edges(result, table)]
    assert dict(zip(edges, bills.roles[0].roles.values())) == {bf.RATE: "charge", bf.CHARGE: "other"} and bills.roles[0].decided_by == "sum"
    assert bills.guesses == []


def test_sc105_the_sum_rule_still_needs_every_bill_to_add_up(reader):
    """Per bill means every bill: when the second bill's `This Bill` column does not add up to its new charges, the sums decide nothing and the right-most
    is taken with the guess note, as for one bill (FR-105, FR-124)."""
    pages = [lastyear_bill("07/20/2026", (("Energy Charge", "80.02", "72.15"), ("Customer Charge", "12.00", "12.00"), ("State Tax", "5.53", "4.98")), "97.55"),
             lastyear_bill("08/20/2026", (("Energy Charge", "70.00", "60.00"), ("Customer Charge", "12.00", "12.00"), ("State Tax", "4.00", "4.00")), "99.00")]
    bills = bill_tables.read(reader(pages))
    assert [role.decided_by for role in bills.roles] == ["guess"] and kinds_of(bills) == [bill_tables.CHARGE_COLUMN]
