"""Synthetic PDF fixtures for the account-import-pdf contract (specs/account-import-pdf/test-contract.md "Fixtures").

Builders return `make_pdf` pages (positioned-item dicts). Expected values are the contract's tables, written out by hand
below, never computed from the code under test. The P-check helpers describe what the real reader made of a fixture, so
a test can assert that the fixture has the shape it is meant to have before any scenario step (contract "Fixture
preconditions"). A failed P-check is a fixture or reader problem, never a reason to change an expected value.
"""

import json
from pathlib import Path
import re
from statistics import median

from home_manager.documents.pdf_layout import point
from home_manager.documents.pdf_reader import complete_pdf, read_result, worker
from home_manager.library.storage import digest_file
from test_pdf import make_pdf

# --- Layout conventions --------------------------------------------------------------------------------------------

COLUMNS = (40, 110, 300, 390, 480)  # Native table x-positions (contract "Fixtures"); 3-column tables use the first three.
MINIMUM_FOOTER = 40  # Non-space characters a native page needs, or the reader sends it to the vision model.
HEADING5 = ("Date", "Description", "Withdrawals", "Deposits", "Balance")
HEADING3 = ("Date", "Description", "Amount")
DATE_NAMES = ("date", "posted date", "transaction date", "post date", "posting date")
AMOUNT_NAMES = ("amount", "debit", "credit", "withdrawals", "deposits")
# V: its 480-character description is about 3,500 pt wide at 10 pt. The column spans of the import run to the midpoint
# between two headings, so the next heading sits at least as far past the description's right edge as the edge is past
# the Description heading (3,600 + (3,600 - 162) = 7,040 pt).
WIDE_COLUMNS = (40, 110, 7200, 7300, 7400)
V_PAGE_WIDTH = 7600
# SC-16 step 4: a 2,001-character description is about 4,450 pt wide, so its amount heading is at least 9,000 pt across.
LONG_CELL_COLUMNS = (40, 110, 9500)
LONG_CELL_PAGE_WIDTH = 10000  # Within the PDF maximum of 14,400 pt, which the plan allows.
LONG_CELL_CHARACTERS = 2001
LONG_WORD = 1000  # PDFWord.character_indexes holds at most 1,000 characters, so a long cell is built from words.

# --- Expected values, hand-written from the contract --------------------------------------------------------------

# K (3-page checking statement): (id, page, date, description, withdrawal, deposit, balance, signed amount_minor).
K_ROWS = [
    ("k1", 1, "08/03/2026", "COFFEE SHOP", "4.50", "", "995.50", -450),
    ("k2", 1, "08/03/2026", "COFFEE SHOP", "4.50", "", "991.00", -450),
    ("k3", 1, "08/05/2026", "GROCERY MART", "45.10", "", "945.90", -4510),
    ("k4", 2, "08/15/2026", "PAYROLL ACME", "", "2,000.00", "2,945.90", 200000),
    ("k5", 2, "08/20/2026", "TRANSFER TO SAVINGS", "500.00", "", "2,445.90", -50000),
    ("k6", 2, "08/21/2026", "MONTHLY SERVICE FEE", "5.00", "", "2,440.90", -500),
    ("k7", 3, "08/25/2026", "REFUND BOOKSTORE", "", "19.99", "2,460.89", 1999),
    ("k8", 3, "08/28/2026", "UTILITY CO", "82.40", "", "2,378.49", -8240),
    ("k9", 3, "08/30/2026", "INTEREST PAID", "", "0.12", "2,378.61", 12),
]
K_POSTED = ["2026-08-03", "2026-08-03", "2026-08-05", "2026-08-15", "2026-08-20", "2026-08-21", "2026-08-25",
            "2026-08-28", "2026-08-30"]
K_OUT_MINOR, K_IN_MINOR = 64150, 202011  # Out 641.50 and in 2,020.11: 1,000.00 - 641.50 + 2,020.11 = 2,378.61.
K_OPENING_MINOR, K_CLOSING_MINOR = 100000, 237861
K_TEXT = ("FIRST LOCAL BANK", "Account ending in 4821", "Account number 000123454821",
          "Statement period 08/01/2026 to 08/31/2026")
K_ACCOUNT_NUMBER = "000123454821"  # C-ids: no stored column outside the reading holds more than its last four digits.
K_CSV_ROWS = [("08/03/2026", "COFFEE SHOP", "-4.50"), ("08/03/2026", "COFFEE SHOP", "-4.50"),
              ("08/05/2026", "GROCERY MART", "-45.10"), ("08/15/2026", "PAYROLL ACME", "2,000.00"),
              ("08/20/2026", "TRANSFER TO SAVINGS", "-500.00"), ("08/21/2026", "MONTHLY SERVICE FEE", "-5.00"),
              ("08/25/2026", "REFUND BOOKSTORE", "19.99"), ("08/28/2026", "UTILITY CO", "-82.40"),
              ("08/30/2026", "INTEREST PAID", "0.12")]

# R (2-page card statement): (id, page, date, description, amount, into C, into A).
R_ROWS = [
    ("r1", 1, "08/03", "BOOKSTORE", "19.99", -1999, 1999),
    ("r2", 1, "08/05", "PAYMENT THANK YOU", "-250.00", 25000, -25000),
    ("r3", 1, "08/09", "GAS STATION", "38.20", -3820, 3820),
    ("r4", 2, "08/14", "RESTAURANT", "54.75", -5475, 5475),
    ("r5", 2, "08/20", "RETURN BOOKSTORE", "-19.99", 1999, -1999),
]
R_POSTED_2025 = ["2025-08-03", "2025-08-05", "2025-08-09", "2025-08-14", "2025-08-20"]
R_TOTALS_C = (-11294, 26999)  # Ticked New rows into C (credit card): out -112.94 and in 269.99.
R_TOTALS_A = (-26999, 11294)  # Into A (checking): out -269.99 and in 112.94.

# X (cross-page linking): (id, page, date, description, withdrawal, deposit, balance, signed amount_minor).
X_ROWS = [("A1", 1, "09/01/2026", "A1", "10.00", "", "990.00", -1000),
          ("A2", 1, "09/02/2026", "A2", "", "20.00", "1,010.00", 2000),
          ("B1", 2, "09/03/2026", "B1", "1.00", "", "1,009.00", -100),
          ("B2", 2, "09/04/2026", "B2", "", "2.00", "1,011.00", 200)]
X_TOTALS = (-1100, 2200)  # Out 11.00 and in 22.00 USD.
X_7C_TOTALS = (-3100, 200)  # 7-c: page 1 prints only withdrawals (A1 10.00, A2 20.00); out 31.00 and in 2.00.
X_SUMMARY = (("Summary", "Amount"), ("Purchases", "100.00"), ("Payments", "50.00"))
X_FEES = (("Fee summary", "Count", "Total"), ("Monthly fee", "1", "5.00"), ("Wire fee", "2", "30.00"))
X_SCHEDULE_ROWS = (("10/01/2026", "Scheduled payment", "25.00", "", "975.00"),
                   ("11/01/2026", "Scheduled payment", "25.00", "", "950.00"))  # 7-a: rows of the Payment schedule page.
X_7B_ROWS = (("09/05/2026", "C1", "3.00", "", "1,008.00"), ("09/06/2026", "C2", "", "4.00", "1,012.00"))

# F (flagged page): (id, page, date, description, amount).
F_ROWS = [("F1", 1, "07/01/2026", "F1", "10.00"), ("F2", 1, "07/02/2026", "F2", "20.00"),
          ("F3", 2, "07/03/2026", "F3", "1.00"), ("F4", 2, "07/04/2026", "F4", "2.00"),
          ("F5", 2, "07/05/2026", "F5", "3.00"), ("F6", 2, "07/06/2026", "F6", "4.00")]

# V (rejected rows): (id, date, description, withdrawal, deposit, balance, signed amount_minor, or None when rejected).
# v5's description is exactly 480 characters ("D" words), and is stored exactly as printed.
V_LONG_DESCRIPTION = ("D" * 7 + " ") * 59 + "D" * 8
V_ROWS = [
    ("v1", "08/01/2026", "GOOD", "10.00", "", "990.00", -1000),
    ("v2", "08/02/2026", "BOTH", "5.00", "5.00", "990.00", None),
    ("v3", "08/03/2026", "", "1.00", "", "989.00", None),
    ("v4", "08/04/2026", "BAD AMOUNT", "1.2.3", "", "989.00", None),
    ("v5", "08/05/2026", V_LONG_DESCRIPTION, "2.00", "", "987.00", -200),
]

# SC-05 pattern table: lines that preselect A (...4821), and lines that preselect nothing.
PATTERN_MATCHES = ("ending in 4821", "ending 4821", "XXXX4821", "xxxxxxxx4821", "****4821",
                   "••••4821", "*4821", "…4821")
PATTERN_MISSES = ("Ref 4821", "4821")

# SC-24 exact dates: rows of (date, description, amount).
D_NY = (("08/03", "X", "1.00"), ("12/30", "Y", "2.00"), ("01/02", "Z", "3.00"))
D_BAD = (("02/27/2026", "P", "1.00"), ("02/30/2026", "Q", "2.00"))
D_FULL = (("08/03/2026", "W", "1.00"), ("08/04/2026", "V", "2.00"))
D_AMB = (("03/08/2026", "G", "1.00"), ("04/09/2026", "H", "2.00"))
D_2Y = (("08/03/26", "T", "1.00"), ("08/04/26", "U", "2.00"))

# S-K, the statement double for K: what Record's extraction returns (the dates and amounts of table K).
S_K = {"statement_type": "bank", "institution": "FIRST LOCAL BANK", "last_four": "4821", "currency": "USD",
       "period_start": "2026-08-01", "period_end": "2026-08-31", "opening_balance_minor": K_OPENING_MINOR,
       "closing_balance_minor": K_CLOSING_MINOR,
       "transactions": [(posted, row[7], row[3]) for posted, row in zip(K_POSTED, K_ROWS)]}


# --- Page builders -------------------------------------------------------------------------------------------------

def footer(text, y, check=True):
    """A words-only footer line of at least MINIMUM_FOOTER non-space characters, so the page reads as native text. A
    digit followed by a word would make the reader raise unresolved_columns even under a complete table (so check
    refuses one) unless a fixture wants exactly that (Fn)."""
    if check:
        assert len("".join(text.split())) >= MINIMUM_FOOTER, text
        assert not re.search(r"\d\s+[A-Za-z]", text), text
    return (40, y, text)


def table_items(rows, top=700, columns=COLUMNS):
    """Items for a table: rows[0] is at y = top and each later row is 20 pt lower. A blank cell prints nothing."""
    return [(columns[column], top - 20 * row, text) for row, cells in enumerate(rows) for column, text in enumerate(cells) if text]


def page(rows, above=(), name="FIRST LOCAL BANK", number=1, total=1, top=700, columns=COLUMNS, **settings):
    """One page: lines above (from y = 780, 15 pt apart), the rows from y = top, and a words-only footer below them."""
    words = ("zero", "one", "two", "three", "four")
    items = [(40, 780 - 15 * index, text) for index, text in enumerate(above)]
    items += table_items(rows, top, columns)
    items.append(footer(f"{name} statement page {words[number]} of {words[total]}, kept for your records",
                        top - 20 * len(rows)))
    return {"items": items, **settings}


def amount(text, currency=None):
    return f"{text} {currency}" if text and currency else text


def k_rows(number, currency=None, only=None):
    """K's data cells (date, description, withdrawal, deposit, balance) for a page, in print order. `currency` prints a
    code after every amount (Keur), or only after row `only` (18-a)."""
    show = lambda row: currency if only in (None, row[0]) else None
    return [(row[2], row[3], amount(row[4], show(row)), amount(row[5], show(row)), amount(row[6], show(row)))
            for row in K_ROWS if row[1] == number]


def k_pages(above=K_TEXT, currency=None, only=None):
    """K: page 1 has the heading and k1-k3, pages 2 and 3 have only rows (no headings) at the same positions."""
    return [page([HEADING5, *k_rows(1, currency, only)], above=above, number=1, total=3),
            page(k_rows(2, currency, only), number=2, total=3),
            page(k_rows(3, currency, only), number=3, total=3)]


def k2_pages():
    """K2: K's page 1 with an added line, so the text prints both 4821 and 7700."""
    return k_pages(above=(*K_TEXT, "Payment to card XXXX7700"))


def k0_pages():
    """K0: K with no last four and no account number line printed."""
    return k_pages(above=(K_TEXT[0], K_TEXT[3]))


def keur_pages():
    """Keur: every amount printed with EUR, and `Currency: EUR` on page 1."""
    return k_pages(above=(*K_TEXT, "Currency: EUR"), currency="EUR")


def k18a_pages():
    """18-a: only k3 printed `45.10 EUR`, and no document-level currency."""
    return k_pages(currency="EUR", only="k3")


def kc_csv():
    """Kc: K's rows as a CSV, with signed amounts and 4-digit years. Used only for fingerprint duplicates."""
    return "".join(["Date,Description,Amount\n"] + [f'{date},{description},"{value}"\n' for date, description, value in K_CSV_ROWS]).encode()


def r_pages():
    """R: card statement. Page 1 has the heading and r1-r3; page 2 has r4-r5 without headings."""
    cells = lambda number: [(row[2], row[3], row[4]) for row in R_ROWS if row[1] == number]
    return [page([HEADING3, *cells(1)], above=("SYNTH CARD SERVICES", "Card number XXXX7700"), name="SYNTH CARD SERVICES",
                 number=1, total=2),
            page(cells(2), name="SYNTH CARD SERVICES", number=2, total=2)]


def x_cells(*ids, only_withdrawals=False):
    """X's data cells (date, description, withdrawal, deposit, balance). `only_withdrawals` (7-c) prints every amount in the
    Withdrawals column and leaves Deposits blank on every row, so A2's 20.00 is a withdrawal, as the contract says."""
    rows = [row for row in X_ROWS if row[0] in ids]
    if only_withdrawals:
        return [(row[2], row[3], row[4] or row[5], "", row[6]) for row in rows]
    return [(row[2], row[3], row[4], row[5], row[6]) for row in rows]


def x_pages(variant=None, b2_x=None):
    """X: page 1 holds a summary table and a transactions table (A1, A2), page 2 headerless rows B1 and B2, and page 3
    the fee summary. Variants: 7a (page 3 is a payment schedule with two headerless rows), 7b (page 2 has its own
    headings, page 3 has headerless rows), 7c (page 1 prints only withdrawals, so it has no native table), 7d (B2's
    amount sits across the Withdrawals/Deposits boundary, at b2_x), 7e (B1's description is `B1 REF 12345`, with the
    `12345` placed in the Withdrawals span)."""
    first = table_items(X_SUMMARY, 700, COLUMNS[:2]) + table_items([HEADING5, *x_cells("A1", "A2", only_withdrawals=variant == "7c")], 560)
    first.append(footer("FIRST LOCAL BANK statement page one of three, kept for your records", 500))
    second = x_cells("B1", "B2")
    items2 = table_items(second, 700)
    if variant == "7d":
        items2 = [item for item in items2 if item[2] != "2.00"] + [(b2_x if b2_x is not None else 362.5, 680, "2.00")]
    if variant == "7e":
        items2 = [item for item in items2 if item[2] != "B1"] + [(110, 700, "B1 REF"), (240, 700, "12345")]
    items2.append(footer("FIRST LOCAL BANK statement page two of three, kept for your records", 640))
    if variant == "7b":
        items2 = table_items([HEADING5, *x_cells("B1", "B2")], 700) + [footer("FIRST LOCAL BANK statement page two of three, kept for your records", 640)]
    if variant == "7a":
        third = [(40, 740, "Payment schedule")] + table_items(X_SCHEDULE_ROWS, 700)
        third.append(footer("FIRST LOCAL BANK statement page three of three, kept for your records", 660))
    elif variant == "7b":
        third = table_items(X_7B_ROWS, 700) + [footer("FIRST LOCAL BANK statement page three of three, kept for your records", 660)]
    else:
        third = table_items(X_FEES, 700) + [footer("FIRST LOCAL BANK statement page three of three, kept for your records", 640)]
    return [{"items": first}, {"items": items2}, {"items": third}]


def f_pages():
    """F: page 1 is a clean headed table. Page 2 is headerless and carries a small image, a real reader trigger for
    `possible_image_content` (plan "Verified facts": a glyph outside the CropBox suppresses the table, so it can't be
    the trigger)."""
    cells = lambda number: [(row[2], row[3], row[4]) for row in F_ROWS if row[1] == number]
    return [page([HEADING3, *cells(1)], number=1, total=2), page(cells(2), number=2, total=2, images=1)]


def fn_pages():
    """Fn (8-a): a one-page native transactions table with `FIRST LOCAL BANK - Page 1 of 3` as its footer."""
    items = table_items([HEADING5, *x_cells("A1", "A2")], 700) + [footer("FIRST LOCAL BANK - Page 1 of 3", 640, check=False)]
    return [{"items": items}]


def m_pages():
    """M: K's page 1, then a scanned page."""
    return [k_pages()[0], None]


def one_page(rows, above=(), heading=HEADING3, **settings):
    """A one-page `Date | Description | Amount` table (SC-24, SC-16 step 3 and the SC-05 patterns)."""
    return [page([heading, *rows], above=above, **settings)]


def pattern_page(line):
    """SC-05 step 5: a 2-row table and one line. The bullet and ellipsis need WinAnsi."""
    return one_page([("08/03/2026", "ALPHA", "1.00"), ("08/04/2026", "BETA", "2.00")], above=(line,), encoding="cp1252")


def v_pages(wide=True):
    """V: SC-25's table. v5's 480-character description is long, so the page is wide and the other columns follow it."""
    rows = [HEADING5, *[(row[1], row[2], row[3], row[4], row[5]) for row in V_ROWS]]
    return [page(rows, columns=WIDE_COLUMNS, media=(V_PAGE_WIDTH, 792))]


def long_cell_text():
    """2,001 characters, as two 1,000-character words and the space between them (PDFWord is capped at 1,000)."""
    text = "i" * LONG_WORD + " " + "l" * LONG_WORD
    assert len(text) == LONG_CELL_CHARACTERS
    return text


def long_cell_pages():
    """SC-16 step 4: a `Date | Description | Amount` table, with a 2,001-character description in its first row."""
    rows = [HEADING3, ("08/01/2026", long_cell_text(), "1.00"), ("08/02/2026", "SHORT", "2.00")]
    return [page(rows, columns=LONG_CELL_COLUMNS, media=(LONG_CELL_PAGE_WIDTH, 792))]


# --- P-check helpers: what the real reader made of a fixture ------------------------------------------------------

def read_pdf(directory, pages, name="fixture.pdf", **options):
    """Write the fixture and read it with the real reader and no model: a page that would need the vision model fails
    (complete_pdf has no configuration). Returns the PDFResult, as `read_result` makes it."""
    directory = Path(directory)
    source = directory / name
    make_pdf(source, pages, **options)
    worker(str(source), directory)
    complete_pdf(directory, config=None, digest=digest_file(source))
    return read_result(json.loads((directory / "result.json").read_text(encoding="utf-8")))


def layout(result, number):
    return result.pages[number - 1].layout


def page_issue_codes(result, number):
    """The reader's page-level issues for one page, from PDFResult.issues (pdf_layout_review, pdf_table_ambiguous)."""
    return [issue.code for issue in result.issues if issue.message.startswith(f"Page {number} ")]


def native_grids(result, number):
    """The page's native tables as grids of cell text (a blank cell is the empty string)."""
    page_layout = layout(result, number)
    return [[[next(cell.text for cell in table.cells if cell.row == r and cell.column == c) for c in range(table.columns)]
             for r in range(table.rows)] for table in page_layout.tables]


def is_transactions_heading(texts):
    """A heading row has a date name and an amount, debit or credit name (matched stripped and lower-cased)."""
    names = [text.strip().lower() for text in texts]
    return any(name in DATE_NAMES for name in names) and any(name in AMOUNT_NAMES for name in names)


def native_transactions_tables(result, number):
    return [grid for grid in native_grids(result, number) if is_transactions_heading(grid[0])]


def scale(page_layout):
    a, b = page_layout.page_to_preview[:2]
    return (a * a + b * b) ** 0.5


def font_size(page_layout):
    """The page's median glyph font size, in preview units (the reader's own `size`, pdf_layout.py:332)."""
    glyphs = [char for char in page_layout.characters if char.bbox and not char.generated and char.text and not char.text.isspace()]
    return max(1, median(char.font_size for char in glyphs) * scale(page_layout))


def word_box(page_layout, word):
    x0, y0, x1, y1 = word.bbox
    points = [point(page_layout.page_to_preview, x, y) for x, y in ((x0, y0), (x0, y1), (x1, y0), (x1, y1))]
    return min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)


def baseline(page_layout, word):
    """A word's baseline is its first character's saved origin through page_to_preview, else the bottom of its box."""
    origin = page_layout.characters[word.character_indexes[0]].origin
    return point(page_layout.page_to_preview, *origin)[1] if origin else word_box(page_layout, word)[3]


def visual_rows(result, number):
    """The page's saved words grouped into visual rows (plan "Visual rows"): a new row starts when a baseline differs by
    more than 0.25 font sizes from the first word of the current row. Words in a row are ordered by left x."""
    page_layout = layout(result, number)
    size = font_size(page_layout)
    rows = []
    for word in sorted(page_layout.words, key=lambda word: (baseline(page_layout, word), word_box(page_layout, word)[0])):
        if not rows or abs(baseline(page_layout, word) - baseline(page_layout, rows[-1][0])) > size * 0.25:
            rows.append([])
        rows[-1].append(word)
    return [sorted(row, key=lambda word: word_box(page_layout, word)[0]) for row in rows]


def texts(result, number, row):
    """A visual row's texts: words closer than 1.5 font sizes form one text (plan "Heading texts"). Returns the text
    and its words' left and right x, for each."""
    page_layout = layout(result, number)
    size = font_size(page_layout)
    groups = []
    for word in row:
        box = word_box(page_layout, word)
        if not groups or box[0] - groups[-1][2] > size * 1.5:
            groups.append([[word.text], box[0], box[2]])
        else:
            groups[-1][0].append(word.text)
            groups[-1][2] = box[2]
    return [(" ".join(words), left, right) for words, left, right in groups]


def row_texts(result, number):
    return [[text for text, _, _ in texts(result, number, row)] for row in visual_rows(result, number)]


def heading_rows(result, number):
    """The visual rows whose texts are a transactions heading."""
    return [row for row in visual_rows(result, number) if is_transactions_heading([text for text, _, _ in texts(result, number, row)])]


def spans(heading):
    """Column spans from a heading row's texts (plan "Column positions"): each runs from the midpoint after the previous
    heading to the midpoint before the next, and the first and last are open to the page edges."""
    inf = float("inf")
    cuts = [(heading[i][2] + heading[i + 1][1]) / 2 for i in range(len(heading) - 1)]
    return [(left, right) for left, right in zip([-inf] + cuts, cuts + [inf])]


def column_of(spans_, box):
    """The span holding a word's horizontal centre, and whether the word fits it: it straddles when its box crosses a
    midpoint by more than 20% of its own width (plan "Column positions")."""
    centre = (box[0] + box[2]) / 2
    index = next(i for i, (left, right) in enumerate(spans_) if left <= centre < right)
    allowance = (box[2] - box[0]) * 0.2
    return index, spans_[index][0] - allowance <= box[0] and box[2] <= spans_[index][1] + allowance


def cells_by_column(result, number, row, heading):
    """A visual row's words as text per heading column: {column index: text}, and the columns whose word straddles."""
    page_layout = layout(result, number)
    columns = spans(heading)
    found, straddling = {}, []
    for word in row:
        index, inside = column_of(columns, word_box(page_layout, word))
        found.setdefault(index, []).append(word.text)
        if not inside:
            straddling.append(word.text)
    return {index: " ".join(words) for index, words in found.items()}, straddling


# The plan's shapes ("Rows"): a date-like word fully matches one of FR-06's printed dates, an amount-like word is a digit-led
# run of digits, commas and periods (so `1.2.3` and `12345` are amount-like) with an optional sign, currency symbol and suffix.
DATE_WORD = re.compile(r"\d{1,2}/\d{1,2}(?:/\d{2}|/\d{4})?|\d{4}-\d{2}-\d{2}")
AMOUNT_WORD = re.compile(r"[-+(]?[$\u20ac\u00a3\u00a5]?\d[\d,.]*(?:\)|-|CR|DR|[A-Za-z]{3})?")


def data_rows(result, number):
    """The visual rows holding a date-like word and an amount-like word anywhere: the shape-only candidates of a page. A
    title such as the statement period has dates but no amount. `candidate_rows` applies the plan's column rule."""
    return [row for row in visual_rows(result, number)
            if any(DATE_WORD.fullmatch(word.text) for word in row) and any(AMOUNT_WORD.fullmatch(word.text) for word in row)]


def candidate_rows(result, number, heading, rows=None):
    """The plan's candidate rule (FR-08 "Rows"): a date-like word in, or straddling, the Date span and an amount-like word
    in, or straddling, an Amount, Debit, Credit, Withdrawals or Deposits span. A Balance-only amount makes no candidate."""
    page_layout = layout(result, number)
    columns = spans(heading)
    names = [text.strip().lower() for text, _, _ in heading]
    date_columns = {index for index, name in enumerate(names) if name in DATE_NAMES}
    amount_columns = {index for index, name in enumerate(names) if name in AMOUNT_NAMES}
    candidates = []
    for row in visual_rows(result, number) if rows is None else rows:
        placed = [(word, column_of(columns, word_box(page_layout, word))[0]) for word in row]
        if (any(DATE_WORD.fullmatch(word.text) and index in date_columns for word, index in placed)
                and any(AMOUNT_WORD.fullmatch(word.text) and index in amount_columns for word, index in placed)):
            candidates.append(row)
    return candidates


def below_table_rows(result, number):
    """The visual rows whose baseline is below the last row of the page's native transactions table (plan "Rows below a
    native table"): its below-table region, up to the page end."""
    page_layout = layout(result, number)
    [grid] = [table for table in page_layout.tables if is_transactions_heading(
        [next(cell.text for cell in table.cells if cell.row == 0 and cell.column == c) for c in range(table.columns)])]
    words = {word.id: word for word in page_layout.words}
    last = max(baseline(page_layout, words[word_id]) for cell in grid.cells if cell.row == grid.rows - 1 for word_id in cell.word_ids)
    size = font_size(page_layout)
    return [row for row in visual_rows(result, number) if baseline(page_layout, row[0]) - last > size * 0.25]


def heading_of(result, number):
    """The page's single transactions heading as (text, left x, right x) per heading text, from its one visual row."""
    [row] = heading_rows(result, number)
    return texts(result, number, row)


def printed_cells(result, number, heading, row):
    """A candidate row as {heading column index: printed text}, and any words that straddle a column boundary."""
    return cells_by_column(result, number, row, heading)


def footer_text(result, number):
    """The page's last visual row, which every fixture makes its footer line."""
    return " ".join(word.text for word in visual_rows(result, number)[-1])


def nonspace(text):
    return len("".join(text.split()))
