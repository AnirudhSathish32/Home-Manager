"""The charge table engine, engine level (specs/pdf-table-engine-bills/test-contract.md), slice SL-01: P-checks, then charge rows (SC-100), headings never
required (SC-101), sections, holder titles, totals and wrapped labels (SC-102 steps 1 and 9), summary anchors and late lines (SC-103), nothing dropped
silently (SC-104), a page with no charge table (SC-114 step 1), and the plan's own G7 and G14 decisions.

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
    alex, blair, credits = (line_with(result, word) for word in ("555-201-1111", "202-2222", "Credits"))
    assert [(row.title.line_id, row.title.phone) for row in table.rows] == [(alex, True), (alex, True), (blair, True), (blair, True), (credits, False)]
    assert [title.text for title in table.titles] == ["Alex 555-201-1111", "Blair (555) 202-2222", "Account Credits"]
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
