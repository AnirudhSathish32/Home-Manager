"""Synthetic PDF fixtures for the pdf-table-engine contract (specs/pdf-table-engine/test-contract.md "Fixtures").

Builders return `make_pdf` pages (positioned-item dicts, 10 pt Helvetica). Expected values are the contract's tables, written out
by hand below, never computed from the code under test. Every native page prints a words-only footer (`words_footer`), so the
reader never sends it to the vision model. A right-aligned amount's left x is its right edge minus its Helvetica width (digits
5.56 pt, `,` and `.` 2.78 pt, `-` `(` `)` 3.33 pt, space 2.78 pt; letters from the standard Helvetica widths); a "left x"
amount starts at its column's x, as in the existing statement-accounts and account-import-pdf fixtures.

Printed texts keep the contract's spelling. `*_ENGINE` lists are the engine-level rows the contract gives (SL-01): per row the
printed date texts, the description, and the printed amount text in each amount column, left to right ("" where none is printed).
"""

from pdf_import_fixtures import k_pages, k_rows
from pdf_import_fixtures import page as k_page
from statement_account_fixtures import COLUMNS4, COLUMNS5, flag_items, lines_above, words_footer

HELVETICA = {" ": 278, "!": 278, '"': 355, "#": 556, "$": 556, "%": 889, "&": 667, "'": 191, "(": 333, ")": 333, "*": 389, "+": 584, ",": 278,
             "-": 333, ".": 278, "/": 278, ":": 278, ";": 278, "<": 584, "=": 584, ">": 584, "?": 556, "@": 1015, "[": 278, "\\": 278, "]": 278,
             "^": 469, "_": 556, "`": 333, "{": 334, "|": 260, "}": 334, "~": 584}
HELVETICA.update({digit: 556 for digit in "0123456789"})
HELVETICA.update(dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", (667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611,
                                                          722, 667, 944, 667, 667, 611))))
HELVETICA.update(dict(zip("abcdefghijklmnopqrstuvwxyz", (556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500,
                                                          278, 556, 500, 722, 500, 500, 500))))


def width(text):
    return sum(HELVETICA[char] for char in text) * 10 / 1000


def put(x, y, text, right=False):
    """An item at x (its left), or ending at x when `right`."""
    return (round(x - width(text), 3) if right else x, y, text)


def row_items(y, cells):
    """Items for one printed line: cells are (x, text) for left x, or (x, text, True) for right edge x; blank texts print nothing."""
    return [put(cell[0], y, cell[1], len(cell) > 2 and cell[2]) for cell in cells if cell[1]]


def shift(pages, dx):
    return [{**page, "items": [(x + dx, y, text, *rest) for x, y, text, *rest in page["items"]]} for page in pages]


def native(name, items, foot_y):
    return {"items": [*items, words_footer(name, foot_y)]}


# --- WF, WF-bare, WF-flag (SC-01, SC-05) -----------------------------------------------------------------------------------

WF_ABOVE = ("SYNTH WF STYLE BANK", "Everyday Checking", "Account number 0000009988", "Beginning balance on 10/1 1,000.00",
            "Ending balance on 10/31 2,113.45", "Statement period 10/01/2026 - 10/31/2026")
# (date, check, description, deposits, withdrawals, balance, expected posted date, expected amount_minor)
WF_ROWS = [
    ("10/2", "", "PAYROLL SYNTH CO", "2,000.00", "", "3,000.00", "2026-10-02", 200000),
    ("10/3", "1201", "CHECK", "", "150.00", "", "2026-10-03", -15000),
    ("10/3", "", "GROCERY SYNTH", "", "84.55", "2,765.45", "2026-10-03", -8455),
    ("10/9", "", "RENT SYNTH PROPERTIES", "", "1,200.00", "1,565.45", "2026-10-09", -120000),
    ("10/15", "", "REFUND SYNTH SHOP", "48.00", "", "", "2026-10-15", 4800),
    ("10/15", "1202", "CHECK", "", "500.00", "1,113.45", "2026-10-15", -50000),
    ("10/28", "", "PAYROLL SYNTH CO", "1,000.00", "", "2,113.45", "2026-10-28", 100000),
]
WF_ENGINE = [([row[0]], row[2], [row[3], row[4], row[5]]) for row in WF_ROWS]  # Amount columns left to right: Deposits, Withdrawals, Balance.
WF_CHECKS = [row[1] for row in WF_ROWS]
WF_BARE_ENGINE = [([row[0]], row[2], [row[5], row[4], row[3]]) for row in WF_ROWS]  # Left to right: Balance, Withdrawals, Deposits.
WF_EDGES = (390, 470, 560)  # Right edges of Deposits, Withdrawals and Ending daily balance.
WF_BARE_EDGES = (330, 410, 490)  # Balance, Withdrawals, Deposits.
WF_HEADING = (("Check", "Deposits/", "Withdrawals/", "Ending daily"), ("Date", "Number", "Description", "Additions", "Subtractions", "balance"))
WF_LABELS = [["Deposits/", "Additions"], ["Withdrawals/", "Subtractions"], ["Ending daily", "balance"]]


def wf_pages(heading=True, edges=WF_EDGES, order=(3, 4, 5), flagged=False):
    """WF: two-line heading at y 712 and 700, rows from y 680. `order` picks the cells (deposits, withdrawals, balance) printed at `edges`."""
    items = lines_above(WF_ABOVE)
    if heading:
        items += row_items(712, [(80, "Check"), (edges[0], "Deposits/", True), (edges[1], "Withdrawals/", True), (edges[2], "Ending daily", True)])
        items += row_items(700, [(40, "Date"), (80, "Number"), (130, "Description"), (edges[0], "Additions", True), (edges[1], "Subtractions", True),
                                 (edges[2], "balance", True)])
    y = 680
    for row in WF_ROWS:
        items += row_items(y, [(40, row[0]), (80, row[1]), (130, row[2]), *((edge, row[index], True) for edge, index in zip(edges, order))])
        y -= 20
    items.append(words_footer("SYNTH WF STYLE BANK", y))
    return [{"items": items + (flag_items() if flagged else [])}]


def wf_bare_pages():
    """WF-bare: no heading; Balance right edge 330, Withdrawals 410, Deposits 490 (cells in the order balance, withdrawals, deposits)."""
    return wf_pages(heading=False, edges=WF_BARE_EDGES, order=(5, 4, 3))


def wf_flag_pages():
    return wf_pages(flagged=True)


# --- DM, BRK (SC-02, SC-06 a) ----------------------------------------------------------------------------------------------

DM_ABOVE = ("SYNTH DAYFIRST BANK", "Savings Account", "Account No 000000004417", "Opening Balance 10,000.00", "Closing Balance 33,754.10",
            "Statement From 01/10/2026 To 31/10/2026")
# (date, narration, withdrawal, deposit, balance, expected posted date, expected amount_minor)
DM_ROWS = [
    ("01/10/2026", "UPI SYNTH GROCER", "250.00", "", "9,750.00", "2026-10-01", -25000),
    ("02/10/2026", "SALARY SYNTH LTD", "", "45,000.00", "54,750.00", "2026-10-02", 4500000),
    ("03/10/2026", "ATM WDL SYNTH", "2,000.00", "", "52,750.00", "2026-10-03", -200000),
    ("05/10/2026", "RENT TRANSFER", "15,000.00", "", "37,750.00", "2026-10-05", -1500000),
    ("06/10/2026", "UPI SYNTH CAFE", "180.50", "", "37,569.50", "2026-10-06", -18050),
    ("08/10/2026", "ELECTRICITY SYNTH", "1,240.00", "", "36,329.50", "2026-10-08", -124000),
    ("10/10/2026", "INTEREST CREDIT", "", "12.35", "36,341.85", "2026-10-10", 1235),
    ("12/10/2026", "UPI SYNTH PHARMACY", "455.00", "", "35,886.85", "2026-10-12", -45500),
    ("13/10/2026", "NEFT SYNTH FRIEND", "", "3,000.00", "38,886.85", "2026-10-13", 300000),
    ("14/10/2026", "CARD SYNTH FUEL", "2,100.00", "", "36,786.85", "2026-10-14", -210000),
    ("16/10/2026", "UPI SYNTH GROCER", "1,325.75", "", "35,461.10", "2026-10-16", -132575),
    ("18/10/2026", "MUTUAL FUND SIP", "5,000.00", "", "30,461.10", "2026-10-18", -500000),
    ("19/10/2026", "UPI SYNTH CAFE", "95.00", "", "30,366.10", "2026-10-19", -9500),
    ("21/10/2026", "REFUND SYNTH STORE", "", "799.00", "31,165.10", "2026-10-21", 79900),
    ("22/10/2026", "MOBILE RECHARGE", "399.00", "", "30,766.10", "2026-10-22", -39900),
    ("24/10/2026", "UPI SYNTH TAXI", "342.60", "", "30,423.50", "2026-10-24", -34260),
    ("26/10/2026", "INSURANCE PREMIUM", "8,500.00", "", "21,923.50", "2026-10-26", -850000),
    ("28/10/2026", "NEFT SYNTH CLIENT", "", "12,500.00", "34,423.50", "2026-10-28", 1250000),
    ("30/10/2026", "UPI SYNTH GROCER", "610.40", "", "33,813.10", "2026-10-30", -61040),
    ("31/10/2026", "BANK CHARGES", "59.00", "", "33,754.10", "2026-10-31", -5900),
]
DM_ENGINE = [([row[0]], row[1], [row[2], row[3], row[4]]) for row in DM_ROWS]  # Left to right: Withdrawal, Deposit, Balance.
DM_EDGES = (380, 460, 560)
BRK_ROW = 13  # Index of row 14, whose deposit is printed 797.00 (expected 79700) with its balance unchanged.
BRK_EXPECTED = ("2026-10-21", 79700)


def dm_pages(deposit_14="799.00"):
    items = lines_above(DM_ABOVE)
    items += row_items(700, [(40, "Date"), (110, "Narration"), (DM_EDGES[0], "Withdrawal Amt.", True), (DM_EDGES[1], "Deposit Amt.", True),
                             (DM_EDGES[2], "Closing Balance", True)])
    y = 680
    for number, row in enumerate(DM_ROWS):
        deposit = deposit_14 if number == BRK_ROW else row[3]
        items += row_items(y, [(40, row[0]), (110, row[1]), (DM_EDGES[0], row[2], True), (DM_EDGES[1], deposit, True), (DM_EDGES[2], row[4], True)])
        y -= 20
    items.append(words_footer("SYNTH DAYFIRST BANK", y))
    return [{"items": items}]


def brk_pages():
    return dm_pages(deposit_14="797.00")


# --- WR, WR-split, WR-above (SC-03) ----------------------------------------------------------------------------------------

WR_ABOVE = ("SYNTH WRAP BANK", "Account number 0000002208", "Beginning balance 500.00", "Ending balance 2,007.66",
            "Statement period 11/01/2026 to 11/30/2026")
HEADING5 = ("Date", "Description", "Withdrawals", "Deposits", "Balance")
# (date line, description, continuation lines, withdrawal, deposit, balance, expected description, expected amount_minor, expected posted date)
WR_ROWS = [
    ("11/02/2026", "COFFEE SYNTH", (), "4.25", "", "495.75", "COFFEE SYNTH", -425, "2026-11-02"),
    ("11/04/2026", "PAYROLL SYNTH", (), "", "1,800.00", "2,295.75", "PAYROLL SYNTH", 180000, "2026-11-04"),
    ("11/07/2026", "GROCERY SYNTH", (), "63.10", "", "2,232.65", "GROCERY SYNTH", -6310, "2026-11-07"),
    ("11/10/2026", "PHONE SYNTH", (), "45.00", "", "2,187.65", "PHONE SYNTH", -4500, "2026-11-10"),
    ("11/14/2026", "ONLINE TRANSFER TO SYNTH", ("SAVINGS ACCOUNT ENDING ALPHA",), "300.00", "", "1,887.65",
     "ONLINE TRANSFER TO SYNTH SAVINGS ACCOUNT ENDING ALPHA", -30000, "2026-11-14"),
    ("11/20/2026", "CARD PURCHASE SYNTH", ("HARDWARE SUPPLY STORE", "SPRINGFIELD US"), "129.99", "", "1,757.66",
     "CARD PURCHASE SYNTH HARDWARE SUPPLY STORE SPRINGFIELD US", -12999, "2026-11-20"),
    ("11/25/2026", "DEPOSIT SYNTH", ("MOBILE CHECK",), "", "250.00", "2,007.66", "DEPOSIT SYNTH MOBILE CHECK", 25000, "2026-11-25"),
]
WR_ENGINE = [([row[0]], row[6], [row[3], row[4], row[5]]) for row in WR_ROWS]  # Left to right: Withdrawals, Deposits, Balance.
WR_LINES = [1 + len(row[2]) for row in WR_ROWS]  # Printed lines per row.
WR_MEMO = "11/27/2026 SYNTH MEMO NOTICE"  # WR-split: a dated line with no amount and no amount line below it.


def wr_pages(split=False, above_descriptions=False):
    """WR: heading at y 700, every printed line 14 pt below the one above. `split` is WR-split (r7's date line has no amount and the
    line below it, `MOBILE CHECK`, holds 250.00 and 2,007.66; then the memo line). `above_descriptions` is WR-above: every row's description
    lines are printed directly above its date line (the date line holds the date and the amounts)."""
    items = lines_above(WR_ABOVE) + row_items(700, list(zip((40, 110, 330, 400, 470), HEADING5)))
    y = 700 - 14
    for number, row in enumerate(WR_ROWS):
        last = split and number == len(WR_ROWS) - 1
        amounts = [(330, row[3]), (400, row[4]), (470, row[5])]
        if above_descriptions:
            for text in (row[1], *row[2]):
                items += row_items(y, [(110, text)])
                y -= 14
            items += row_items(y, [(40, row[0]), *amounts])
            y -= 14
        elif last:
            items += row_items(y, [(40, row[0]), (110, row[1])])
            items += row_items(y - 14, [(110, row[2][0]), *amounts])
            y -= 28
        else:
            items += row_items(y, [(40, row[0]), (110, row[1]), *amounts])
            for text in row[2]:
                y -= 14
                items += row_items(y, [(110, text)])
            y -= 14
    if split:
        items += row_items(y, [(40, WR_MEMO.split(" ", 1)[0]), (110, WR_MEMO.split(" ", 1)[1])])
        y -= 14
    items.append(words_footer("SYNTH WRAP BANK", y))
    return [{"items": items}]


def wr_split_pages():
    return wr_pages(split=True)


def wr_above_pages():
    return wr_pages(above_descriptions=True)


# --- OD (SC-04) ------------------------------------------------------------------------------------------------------------

OD_ABOVE = ("SYNTH DAILY BANK", "Account number 0000006630", "Beginning balance 200.00", "Ending balance 437.85", "Statement period 12/01/2026 to 12/31/2026")
# (date, description, withdrawal, deposit, balance, expected posted date, expected amount_minor, carried from the row above)
OD_ROWS = [
    ("12/03", "COFFEE SYNTH", "3.50", "", "", "2026-12-03", -350, False),
    ("", "BAKERY SYNTH", "6.25", "", "190.25", "2026-12-03", -625, True),
    ("12/05", "PAYROLL SYNTH", "", "900.00", "1,090.25", "2026-12-05", 90000, False),
    ("", "GROCERY SYNTH", "40.00", "", "", "2026-12-05", -4000, True),
    ("", "PHARMACY SYNTH", "12.40", "", "1,037.85", "2026-12-05", -1240, True),
    ("12/09", "RENT SYNTH", "600.00", "", "437.85", "2026-12-09", -60000, False),
]
OD_ENGINE = [([row[0]] if row[0] else [], row[1], [row[2], row[3], row[4]]) for row in OD_ROWS]  # Withdrawals, Deposits, Balance.


def od_pages():
    items = lines_above(OD_ABOVE) + row_items(700, list(zip((40, 110, 330, 400, 470), HEADING5)))
    y = 680
    for row in OD_ROWS:
        items += row_items(y, [(40, row[0]), (110, row[1]), (330, row[2]), (400, row[3]), (470, row[4])])
        y -= 20
    items.append(words_footer("SYNTH DAILY BANK", y))
    return [{"items": items}]


# --- ONE (SC-06 b) ---------------------------------------------------------------------------------------------------------

ONE_ABOVE = ("SYNTH ONE BANK", "Account number 0000006611", "Statement period 09/01/2026 to 09/30/2026")
ONE_ROW = ("09/15/2026", "SYNTH SERVICE FEE", "25.00", "2026-09-15", -2500)
ONE_ENGINE = [([ONE_ROW[0]], ONE_ROW[1], [ONE_ROW[2]])]


def one_pages():
    items = lines_above(ONE_ABOVE) + row_items(700, [(40, "Date"), (110, "Description"), (380, "Withdrawals")])
    items += row_items(680, [(40, ONE_ROW[0]), (110, ONE_ROW[1]), (380, ONE_ROW[2])])
    return [native("SYNTH ONE BANK", items, 660)]


# --- CS (SC-07) ------------------------------------------------------------------------------------------------------------

CS_ABOVE = ("SYNTH REWARDS CARD", "Card number XXXX5512", "Previous Balance 1,250.00", "New Balance 481.62", "Statement period 10/05/2026 to 11/04/2026")
# (section, date, description, amount, expected posted date, expected amount_minor)
CS_ROWS = [
    ("Payments and Credits", "10/12", "PAYMENT THANK YOU", "1,000.00", "2026-10-12", 100000),
    ("Payments and Credits", "10/20", "RETURN SYNTH SHOP", "45.00", "2026-10-20", 4500),
    ("Purchases", "10/07", "SYNTH GROCERY", "120.40", "2026-10-07", -12040),
    ("Purchases", "10/15", "SYNTH FUEL", "52.18", "2026-10-15", -5218),
    ("Purchases", "10/22", "SYNTH STREAMING", "15.99", "2026-10-22", -1599),
    ("Purchases", "11/01", "SYNTH RESTAURANT", "88.05", "2026-11-01", -8805),
]
CS_ENGINE = [([row[1]], row[2], [row[3]]) for row in CS_ROWS]
CS_SECTIONS = [row[0] for row in CS_ROWS]


def cs_pages():
    items = lines_above(CS_ABOVE) + row_items(700, [(40, "Date"), (110, "Description"), (420, "Amount", True)])
    y, section = 680, None
    for row in CS_ROWS:
        if row[0] != section:
            section = row[0]
            items += row_items(y, [(40, section)])
            y -= 20
        items += row_items(y, [(40, row[1]), (110, row[2]), (420, row[3], True)])
        y -= 20
    items.append(words_footer("SYNTH REWARDS CARD", y))
    return [{"items": items}]


# --- NB (SC-07 variant) ----------------------------------------------------------------------------------------------------

NB_ABOVE = ("SYNTH PLAIN BANK", "Account number 0000004040", "Beginning balance 100.00", "Ending balance 624.80", "Statement period 11/01/2026 to 11/30/2026")
# (date, description, A, B, expected posted date, expected amount_minor)
NB_ROWS = [
    ("11/03/2026", "SYNTH PAYROLL", "", "1,500.00", "2026-11-03", 150000),
    ("11/05/2026", "SYNTH RENT", "900.00", "", "2026-11-05", -90000),
    ("11/18/2026", "SYNTH UTILITY", "75.20", "", "2026-11-18", -7520),
]
NB_ENGINE = [([row[0]], row[1], [row[2], row[3]]) for row in NB_ROWS]  # Columns A (right edge 380) and B (460).


def nb_pages(summary=True):
    """NB: no heading; `summary=False` removes the two summary lines (the engine-level variant of SC-07)."""
    above = NB_ABOVE if summary else (NB_ABOVE[0], NB_ABOVE[1], NB_ABOVE[4])
    items = lines_above(above)
    y = 700
    for row in NB_ROWS:
        items += row_items(y, [(40, row[0]), (110, row[1]), (380, row[2], True), (460, row[3], True)])
        y -= 20
    items.append(words_footer("SYNTH PLAIN BANK", y))
    return [{"items": items}]


# --- K3 (SC-08) ------------------------------------------------------------------------------------------------------------

K3_PAGES_OF_ROWS = (3, 3, 3)  # Rows k1-k3, k4-k6, k7-k9; the amounts and dates are account-import-pdf's K table (pdf_import_fixtures.K_ROWS).


def k3_pages():
    """K with page 2's heading repeated at its top, and every item on page 3 drawn 6 pt to the right."""
    first, _, third = k_pages()
    second = k_page([("Date", "Description", "Withdrawals", "Deposits", "Balance"), *k_rows(2)], number=2, total=3)
    return [first, second, *shift([third], 6)]


# --- B, BL, UP, PR (SC-09 - SC-11) -----------------------------------------------------------------------------------------

B_ABOVE = ("SYNTH CHECKING BANK", "Account number 0000005521", "Beginning balance 1,000.00", "Ending balance 2,950.00", "Statement period 08/01/2026 to 08/31/2026")
# (date, description, withdrawal, deposit, balance, expected amount_minor)
B_ROWS = [
    ("08/03/2026", "RENT SYNTH", "700.00", "", "300.00", -70000),
    ("08/15/2026", "PAYROLL SYNTH", "", "2,500.00", "2,800.00", 250000),
    ("08/20/2026", "REFUND SYNTH SHOP", "", "150.00", "2,950.00", 15000),
]
BL_DAILY = (("08/03/2026", "300.00"), ("08/15/2026", "2,800.00"), ("08/20/2026", "2,950.00"))
BL_SCHEDULE = (("09/15/2026", "SCHEDULED PAYMENT", "125.00"), ("10/15/2026", "SCHEDULED PAYMENT", "125.00"))
UP_LINE = ("08/12/2026", "SYNTH COURTESY CREDIT", "35.00")  # The amount's left x is 545, right of every column.
UP_X = 545
PR_PROSE = ("Important information about your account. Paper statement fees apply from this month.",
            "A paper statement fee of 2.50 was charged on 08/28/2026 to this account.",
            "Interest of 0.42 was paid on 08/31/2026 and will show on next month's statement.")


def b_rows(y, rows=B_ROWS, step=20):
    items = []
    for row in rows:
        items += row_items(y, [(40, row[0]), (110, row[1]), (330, row[2]), (400, row[3]), (470, row[4])])
        y -= step
    return items, y


def b_pages(above=B_ABOVE, extra=()):
    items = lines_above(above) + row_items(700, list(zip((40, 110, 330, 400, 470), HEADING5)))
    rows, y = b_rows(680)
    items += rows
    for line in extra:
        items += row_items(y, line)
        y -= 20
    return [native("SYNTH CHECKING BANK", items, y)]


def up_pages():
    return b_pages(extra=[[(40, UP_LINE[0]), (110, UP_LINE[1]), (UP_X, UP_LINE[2])]])


def pr_pages():
    first = b_pages(above=(*B_ABOVE[:3], "Ending balance 2,947.50", B_ABOVE[4]))[0]
    second = native("SYNTH CHECKING BANK", [(40, 700 - 14 * index, text) for index, text in enumerate(PR_PROSE)], 700 - 14 * len(PR_PROSE))
    return [first, second]


def bl_pages():
    """BL: B without its two balance lines above, the balance, total and daily lines described in the contract, and a schedule on page 2."""
    items = lines_above((B_ABOVE[0], B_ABOVE[1], B_ABOVE[4])) + row_items(700, list(zip((40, 110, 330, 400, 470), HEADING5)))
    items += row_items(680, [(40, "08/01/2026"), (110, "Beginning Balance"), (470, "1,000.00")])
    rows, y = b_rows(660)
    items += rows
    items += row_items(y, [(110, "Total withdrawals"), (330, "700.00")])
    items += row_items(y - 20, [(110, "Total deposits"), (400, "2,650.00")])
    items += row_items(y - 40, [(40, "08/31/2026"), (110, "Ending Balance"), (470, "2,950.00")])
    y -= 70
    items += row_items(y, [(40, "Daily ending balance")])
    y -= 20
    for date, balance in BL_DAILY:
        items += row_items(y, [(40, date), (470, balance)])
        y -= 20
    y -= 10
    items += row_items(y, [(40, "Fee summary")])
    items += row_items(y - 20, [(40, "Monthly service fee"), (470, "0.00")])
    items += row_items(y - 40, [(40, "Overdraft fees"), (470, "0.00")])
    first = native("SYNTH CHECKING BANK", items, y - 60)
    schedule = [(40, 740, "Payment schedule")]
    for number, (date, text, amount) in enumerate(BL_SCHEDULE):
        schedule += row_items(700 - 20 * number, [(40, date), (110, text), (330, amount)])
    return [first, native("SYNTH CHECKING BANK schedule", schedule, 640)]


# --- CC (SC-17) ------------------------------------------------------------------------------------------------------------

CC_ROWS = [  # (page, date, description, amount, balance, expected posted date, expected amount_minor)
    (1, "09/02/2026", "SYNTH RENT", "100.00", "400.00", "2026-09-02", -10000),
    (1, "09/10/2026", "SYNTH PAYROLL", "250.00", "650.00", "2026-09-10", 25000),
    (1, "09/20/2026", "SYNTH GAS", "50.00", "600.00", "2026-09-20", -5000),
    (2, "09/05/2026", "TRANSFER FROM CHECKING", "1,000.00", "6,000.00", "2026-09-05", 100000),
    (2, "09/25/2026", "SYNTH WITHDRAWAL", "-200.00", "5,800.00", "2026-09-25", -20000),
    (2, "09/30/2026", "INTEREST", "2.15", "5,802.15", "2026-09-30", 215),
]


def cc_pages():
    """CC: a checking table (Withdrawals | Deposits | Balance; c1 and c3 print their amount under Withdrawals, c2 under Deposits) on page 1 and a savings table
    (Amount | Balance) on page 2."""
    first = lines_above(("SYNTH COMBINED BANK", "Statement period 09/01/2026 to 09/30/2026", "CHECKING ACCOUNT 0000003311"))
    first += row_items(700, list(zip(COLUMNS5, HEADING5)))
    for number, row in enumerate(row for row in CC_ROWS if row[0] == 1):
        column = COLUMNS5[3] if number == 1 else COLUMNS5[2]
        first += row_items(680 - 20 * number, [(40, row[1]), (110, row[2]), (column, row[3]), (COLUMNS5[4], row[4])])
    second = [(40, 780, "SAVINGS ACCOUNT 0000003322")] + row_items(700, list(zip(COLUMNS4, ("Date", "Description", "Amount", "Balance"))))
    for number, row in enumerate(row for row in CC_ROWS if row[0] == 2):
        second += row_items(680 - 20 * number, [(40, row[1]), (110, row[2]), (COLUMNS4[2], row[3]), (COLUMNS4[3], row[4])])
    return [native("SYNTH COMBINED BANK", first, 600), native("SYNTH COMBINED BANK savings", second, 600)]


# --- ND, ND-prior (SC-16) --------------------------------------------------------------------------------------------------

ND_ABOVE = ("SYNTH NODATE BANK", "Account number 0000007788")
ND_ROWS = [  # (page, date, description, amount, balance)
    (1, "03/04/2026", "ALPHA", "10.00", "110.00"), (1, "03/05/2026", "BRAVO", "-5.00", "105.00"),
    (2, "04/06/2026", "CHARLIE", "1.00", "106.00"), (2, "04/07/2026", "DELTA", "2.00", "108.00"),
]
ND_EXPECTED_DAY_FIRST = [("2026-04-03", 1000), ("2026-05-03", -500), ("2026-06-04", 100), ("2026-07-04", 200)]  # SC-16 b, ND read day-first.
ND_PRIOR_ABOVE = (*ND_ABOVE, "Beginning balance 100.00", "Ending balance 104.00", "Statement period 02/01/2026 to 02/28/2026")
ND_PRIOR_ROWS = [(1, "15/02/2026", "ECHO", "3.00", "103.00"), (1, "16/02/2026", "FOXTROT", "1.00", "104.00")]


def nd_pages(prior=False):
    """ND: two pages, the heading on page 1 only; ND-prior (`prior`) is one page of day-first rows. ND-prior also prints its own
    balance and period lines above (the summary stub for it cites them; the contract lists them in its stub table)."""
    rows = ND_PRIOR_ROWS if prior else ND_ROWS
    pages = []
    for number in sorted({row[0] for row in rows}):
        items = lines_above(ND_PRIOR_ABOVE if prior else ND_ABOVE) if number == 1 else []
        y = 700
        if number == 1:
            items += row_items(y, list(zip(COLUMNS4, ("Date", "Description", "Amount", "Balance"))))
            y -= 20
        for row in (row for row in rows if row[0] == number):
            items += row_items(y, [(40, row[1]), (110, row[2]), (COLUMNS4[2], row[3]), (COLUMNS4[3], row[4])])
            y -= 20
        pages.append(native("SYNTH NODATE BANK", items, y))
    return pages


def nd_prior_pages():
    return nd_pages(prior=True)


# --- FX, PD, TD (SC-23 - SC-25) --------------------------------------------------------------------------------------------

FX_ABOVE = ("SYNTH TRAVEL CARD", "Card number XXXX7001", "Previous Balance 0.00", "New Balance 210.00", "Statement period 10/01/2026 to 10/31/2026")
# (date, description, foreign amount, rate, amount, expected posted date, expected amount_minor)
FX_ROWS = [
    ("10/03", "SYNTH HOTEL PARIS", "92.17", "1.0850", "100.00", "2026-10-03", -10000),
    ("10/09", "SYNTH CAFE LONDON", "38.50", "1.2987", "50.00", "2026-10-09", -5000),
    ("10/15", "SYNTH BOOKS", "", "", "60.00", "2026-10-15", -6000),
]
FX_ENGINE = [([row[0]], row[1], [row[2], row[3], row[4]]) for row in FX_ROWS]


def fx_pages():
    items = lines_above(FX_ABOVE) + row_items(700, [(40, "Date"), (110, "Description"), (330, "Foreign amount", True), (400, "Rate", True), (480, "Amount", True)])
    y = 680
    for row in FX_ROWS:
        items += row_items(y, [(40, row[0]), (110, row[1]), (330, row[2], True), (400, row[3], True), (480, row[4], True)])
        y -= 20
    items.append(words_footer("SYNTH TRAVEL CARD", y))
    return [{"items": items}]


PD_ABOVE = ("SYNTH PENDING CARD", "Card number XXXX7002", "Previous Balance 100.00", "New Balance 145.00", "Statement period 10/01/2026 to 10/31/2026")
PD_ROWS = [  # (section, date, description, amount, expected posted date, expected amount_minor or None when pending)
    ("Purchases", "10/05", "SYNTH GROCERY", "30.00", "2026-10-05", -3000),
    ("Purchases", "10/18", "SYNTH FUEL", "15.00", "2026-10-18", -1500),
    ("Pending transactions", "10/30", "SYNTH HOTEL", "200.00", None, None),
    ("Pending transactions", "10/31", "SYNTH TAXI", "12.50", None, None),
]


def pd_pages():
    items = lines_above(PD_ABOVE) + row_items(700, [(40, "Date"), (110, "Description"), (420, "Amount", True)])
    y, section = 680, None
    for row in PD_ROWS:
        if row[0] != section:
            section = row[0]
            items += row_items(y, [(40, section)])
            y -= 20
        items += row_items(y, [(40, row[1]), (110, row[2]), (420, row[3], True)])
        y -= 20
    items.append(words_footer("SYNTH PENDING CARD", y))
    return [{"items": items}]


TD_ABOVE = ("SYNTH POSTING CARD", "Card number XXXX7003", "Previous Balance 0.00", "New Balance 439.25", "Statement period 09/20/2026 to 10/19/2026")
# (transaction date, posted date, description, amount, expected transaction_date, expected posted_date, expected amount_minor)
TD_ROWS = [
    ("09/28", "10/01", "SYNTH AIRLINE", "412.00", "2026-09-28", "2026-10-01", -41200),
    ("10/02", "10/03", "SYNTH CAFE", "7.25", "2026-10-02", "2026-10-03", -725),
    ("10/14", "10/15", "SYNTH BOOKS", "20.00", "2026-10-14", "2026-10-15", -2000),
]
TD_ENGINE = [([row[0], row[1]], row[2], [row[3]]) for row in TD_ROWS]


def td_pages(heading=True):
    items = lines_above(TD_ABOVE)
    y = 700
    if heading:
        items += row_items(y, [(40, "Trans Date"), (90, "Post Date"), (150, "Description"), (420, "Amount", True)])
        y -= 20
    for row in TD_ROWS:
        items += row_items(y, [(40, row[0]), (90, row[1]), (150, row[2]), (420, row[3], True)])
        y -= 20
    items.append(words_footer("SYNTH POSTING CARD", y))
    return [{"items": items}]


def td_bare_pages():
    return td_pages(heading=False)


# --- All of them -----------------------------------------------------------------------------------------------------------

FIXTURES = {
    "WF": wf_pages, "WF-bare": wf_bare_pages, "WF-flag": wf_flag_pages, "DM": dm_pages, "BRK": brk_pages, "WR": wr_pages, "WR-split": wr_split_pages,
    "WR-above": wr_above_pages, "OD": od_pages, "ONE": one_pages, "CS": cs_pages, "NB": nb_pages, "K3": k3_pages, "B": b_pages, "BL": bl_pages,
    "UP": up_pages, "PR": pr_pages, "CC": cc_pages, "ND": nd_pages, "ND-prior": nd_prior_pages, "FX": fx_pages, "PD": pd_pages, "TD": td_pages,
    "TD-bare": td_bare_pages,
}
