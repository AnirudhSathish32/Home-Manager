"""Synthetic PDF fixtures for the pdf-table-engine-paystubs contract (specs/pdf-table-engine-paystubs/test-contract.md "Fixtures").

Builders return `make_pdf` pages (positioned-item dicts, 10 pt Helvetica). Expected values are the contract's tables written out by hand
below, never computed from the code under test. Every page ends with the words-only footer `FOOTER` at (40, 60), so the reader never sends it to
the vision model and no amount is in it. A right-aligned amount's left x is its right edge minus its Helvetica width (digits 5.56 pt, `,` and `.`
2.78 pt, `-` `(` `)` 3.33 pt), as in tests/table_engine_fixtures.py, whose helpers are reused.

Printed texts keep the contract's spelling. The `*_ENGINE` values are the engine-level facts the contract gives (SL-01 of the plan): per table the
heading text over each amount column (left to right), its rows `(label, section, printed amount text per column)` and its totals
`(label, kind, printed amount text per column)`, with "" where a column prints nothing. The `EXP_*` values are the contract's Record expectations
(minor units), written here so later slices share them. `*_CONT*`, `*_STUBCUT` and `*_TALL` are SL-01's own fixtures for the engine steps the contract
names without a fixture (continuation across pages, a stub start line ending a table, a page with no table beside a page with one).
"""

from pdf_import_fixtures import footer
from statement_account_fixtures import lines_above
from table_engine_fixtures import row_items

FOOTER = "This pay statement is for your records. Amounts are in US dollars ($)."
ABOVE = ("SYNTH PAYROLL CO", "Earnings Statement", "Pay date 2026-07-03", "Pay period 2026-06-15 to 2026-06-28", "Currency USD")

HOURS, RATE, CURRENT, YTD = 260, 330, 430, 520
PS_EDGES = (HOURS, RATE, CURRENT, YTD)
PS_HEADING = ("Description", "Hours", "Rate", "Current", "YTD")

# (label, hours, rate, current, ytd, kind): kind is "row" or the total's kind.
PS_ROWS = [
    ("Regular", "80.00", "31.25", "2,500.00", "32,500.00", "row"),
    ("Overtime", "4.00", "46.8750", "187.50", "1,125.00", "row"),
    ("Gross Pay", "", "", "2,687.50", "33,625.00", "gross"),
    ("Federal Income Tax", "", "", "295.63", "3,698.75", "row"),
    ("Social Security", "", "", "166.63", "2,084.75", "row"),
    ("Medicare", "", "", "38.97", "487.56", "row"),
    ("Total Taxes", "", "", "501.23", "6,271.06", "taxes"),
    ("401K", "", "", "134.38", "1,681.25", "row"),
    ("Total Pre-Tax Deductions", "", "", "134.38", "1,681.25", "deductions"),
    ("Net Pay", "", "", "2,051.89", "25,672.69", "net"),
]


def page_of(items, above=ABOVE):
    """A page: the lines above from y 780, the items, and the footer."""
    return {"items": [*lines_above(above), *items, footer(FOOTER, 60)]}


def lay(top, specs, edges, step=16, label_x=40):
    """Items for printed lines from y = top downward. A spec is ("row", label, texts per edge), ("title", text), ("wrap", text, x) (8 pt under
    the row before it, and the next line 16 pt under the wrap) or ("head", [(x, text, right)...])."""
    items, y = [], top
    for spec in specs:
        if spec[0] == "row":
            items += row_items(y, [(label_x, spec[1]), *[(edge, text, True) for edge, text in zip(edges, spec[2])]])
        elif spec[0] == "title":
            items.append((label_x, y, spec[1]))
        elif spec[0] == "wrap":
            y += 8  # 8 pt under the row before it; the next line is 16 pt under this one.
            items.append((spec[2], y, spec[1]))
        elif spec[0] == "head":
            items += row_items(y, spec[1])
        y -= step
    return items


def head(y, words, edges, label_x=40):
    """A heading line: the first word at label_x, the others right-aligned at the edges (a blank prints nothing)."""
    return row_items(y, [(label_x, words[0]), *[(edge, text, True) for edge, text in zip(edges, words[1:])]])


def ps_specs(rows=PS_ROWS):
    return [("row", row[0], row[1:5]) for row in rows]


def ps_page(rows=PS_ROWS, heading=PS_HEADING, edges=PS_EDGES, above=ABOVE, extra=()):
    return page_of([*head(700, heading, edges), *lay(680, ps_specs(rows), edges), *extra], above)


def ps_pages():
    return [ps_page()]


# --- Variants of PS -------------------------------------------------------------------------------------------------------

def ps_2l_pages():
    """PS-2L (SC-51): a two-line heading."""
    items = [*row_items(712, [(CURRENT, "This", True), (YTD, "Year to", True)]), *head(700, ("Description", "Hours", "Rate", "Period", "Date"), PS_EDGES),
             *lay(680, ps_specs(), PS_EDGES)]
    return [page_of(items)]


def ps_nh_pages():
    """PS-NH (SC-55): no heading; Current printed at right edge 520 and YTD at 430."""
    rows = [(label, hours, rate, ytd, current, kind) for label, hours, rate, current, ytd, kind in PS_ROWS]
    return [page_of(lay(680, ps_specs(rows), PS_EDGES))]


def ps_wrap_pages():
    """PS-WRAP (SC-54): row 4 prints `Federal Income` with its amounts and `Tax Withholding` (x 52) on the line under it; rows 5 - 10 move down 8."""
    specs = ps_specs()
    specs.insert(4, ("wrap", "Tax Withholding", 52))
    specs[3] = ("row", "Federal Income", PS_ROWS[3][1:5])
    return [page_of([*head(700, PS_HEADING, PS_EDGES), *lay(680, specs, PS_EDGES)])]


def ps_sec_pages(memo=False):
    """PS-SEC (SC-60): text-only section titles `Earnings`, `Taxes` and `Pre-tax`, each above its rows; with `memo`, SC-60's line outside every column."""
    specs = ps_specs()
    specs[7:7] = [("title", "Pre-tax")]
    specs[3:3] = [("title", "Taxes")]
    specs[0:0] = [("title", "Earnings")]
    items = [*head(700, PS_HEADING, PS_EDGES), *lay(680, specs, PS_EDGES)]
    if memo:
        items += row_items(680 - 16 * len(specs), [(40, "Bonus advance memo"), (600, "75.00", True)])
    return [page_of(items)]


DEPOSIT_ROWS = [("Checking 1234", "1,551.89"), ("Savings 5678", "500.00")]
LEAVE_ROWS = [("Vacation", "40.00", "8.00", "32.00"), ("Sick", "24.00", "0.00", "24.00")]


def ps_other_pages():
    """PS-OTHER (SC-56): PS, a Direct Deposit table from y 440 and a Leave table from y 360 (their columns line up with PS's)."""
    items = [(40, 440, "Direct Deposit"), *row_items(424, [(40, "Account"), (CURRENT, "Amount", True)])]
    for number, (label, amount) in enumerate(DEPOSIT_ROWS):
        items += row_items(408 - 16 * number, [(40, label), (CURRENT, amount, True)])
    items += head(360, ("Leave", "Accrued", "Used", "Balance"), (HOURS, RATE, CURRENT))
    for number, row in enumerate(LEAVE_ROWS):
        items += row_items(344 - 16 * number, [(40, row[0]), (HOURS, row[1], True), (RATE, row[2], True), (CURRENT, row[3], True)])
    return [ps_page(extra=items)]


YTDH_EDGES = (220, 290, 370, 450, 530)


def ps_ytdh_pages():
    """PS-YTDH (SC-57 a): Hours, Rate, Current, YTD Hours, YTD."""
    hours = {"Regular": "1,040.00", "Overtime": "24.00"}
    specs = [("row", row[0], (row[1], row[2], row[3], hours.get(row[0], ""), row[4])) for row in PS_ROWS]
    return [page_of([*head(700, ("Description", "Hours", "Rate", "Current", "YTD Hours", "YTD"), YTDH_EDGES), *lay(680, specs, YTDH_EDGES)])]


EMP_EDGES = (HOURS, RATE, CURRENT, YTD, 600)


def ps_emp_pages():
    """PS-EMP (SC-57 b): an `Employer` column at right edge 600 that prints only on row 8."""
    specs = [("row", row[0], (*row[1:5], "80.63" if row[0] == "401K" else "")) for row in PS_ROWS]
    return [page_of([*head(700, (*PS_HEADING, "Employer"), EMP_EDGES), *lay(680, specs, EMP_EDGES)])]


def ps_digits_pages():
    """PS-DIGITS (SC-58): `PRE-TAX 401K` and `SECTION 125` as rows."""
    rows = list(PS_ROWS)
    rows[7:9] = [("PRE-TAX 401K", "", "", "134.38", "1,681.25", "row"), ("SECTION 125", "", "", "85.00", "1,105.00", "row"),
                 ("Total Pre-Tax Deductions", "", "", "219.38", "2,786.25", "deductions")]
    rows[-1] = ("Net Pay", "", "", "1,966.89", "24,567.69", "net")
    return [ps_page(rows)]


def ps_bonus_pages():
    """PS-BONUS (SC-69): `Relocation Bonus` after Overtime, Current blank, YTD 5,000.00."""
    rows = list(PS_ROWS)
    rows.insert(2, ("Relocation Bonus", "", "", "", "5,000.00", "row"))
    rows[3] = ("Gross Pay", "", "", "2,687.50", "38,625.00", "gross")
    rows[-1] = ("Net Pay", "", "", "2,051.89", "30,672.69", "net")
    return [ps_page(rows)]


def ps_swaphead_pages():
    """PS-SWAPHEAD (SC-61 a): the heading words YTD and Current exchanged."""
    return [ps_page(heading=("Description", "Hours", "Rate", "YTD", "Current"))]


def ps_badtotal_pages():
    """PS-BADTOTAL (SC-62 a): Total Taxes Current printed 510.23."""
    rows = list(PS_ROWS)
    rows[6] = ("Total Taxes", "", "", "510.23", "6,271.06", "taxes")
    return [ps_page(rows)]


def ps_badnet_pages():
    """PS-BADNET (SC-62 b): Net Pay Current printed 2,061.89."""
    rows = list(PS_ROWS)
    rows[-1] = ("Net Pay", "", "", "2,061.89", "25,672.69", "net")
    return [ps_page(rows)]


# --- SBS: side-by-side blocks (SC-52) -------------------------------------------------------------------------------------

SBS_ROWS = [  # left label, current, ytd, right label, current, ytd
    ("Regular", "2,500.00", "32,500.00", "Federal Income Tax", "295.63", "3,698.75"),
    ("Overtime", "187.50", "1,125.00", "Social Security", "166.63", "2,084.75"),
    ("Gross Pay", "2,687.50", "33,625.00", "Medicare", "38.97", "487.56"),
    ("", "", "", "Total Taxes", "501.23", "6,271.06"),
    ("Net Pay", "2,051.89", "25,672.69", "401K", "134.38", "1,681.25"),
    ("", "", "", "Total Pre-Tax Deductions", "134.38", "1,681.25"),
]


def sbs_pages():
    items = row_items(700, [(40, "Earnings"), (200, "Current", True), (270, "YTD", True), (300, "Deductions"), (460, "Current", True), (530, "YTD", True)])
    for number, (left, lc, ly, right, rc, ry) in enumerate(SBS_ROWS):
        items += row_items(680 - 16 * number, [(40, left), (200, lc, True), (270, ly, True), (300, right), (460, rc, True), (530, ry, True)])
    return [page_of(items)]


# --- STK: stacked tables (SC-53) ------------------------------------------------------------------------------------------

def stk_pages():
    """Heading and rows 1 - 3 as PS; `Statutory` at y 620 and rows 4 - 7 at edges 400 and 500 from y 604; `Voluntary` at y 524 and rows 8 - 9 from
    y 508; Net Pay at y 460; no heading over the second table."""
    second = (400, 500)
    items = [*head(700, PS_HEADING, PS_EDGES), *lay(680, ps_specs(PS_ROWS[:3]), PS_EDGES), (40, 620, "Statutory"),
             *lay(604, [("row", row[0], row[3:5]) for row in PS_ROWS[3:7]], second), (40, 524, "Voluntary"),
             *lay(508, [("row", row[0], row[3:5]) for row in PS_ROWS[7:9]], second), *lay(460, [("row", "Net Pay", PS_ROWS[9][3:5])], second)]
    return [page_of(items)]


# --- B1 and B2: columns the numbers don't settle (SC-61 b) ----------------------------------------------------------------

def b_pages(rows):
    return [page_of(lay(680, [("row", label, (current, ytd)) for label, current, ytd in rows], (CURRENT, YTD)))]


B1_ROWS = [("Regular", "2,500.00", ""), ("Relocation Bonus", "", "5,000.00"), ("Gross Pay", "2,500.00", "5,000.00"), ("Net Pay", "2,500.00", "5,000.00")]
B2_ROWS = [("Regular", "1,000.00", "2,000.00"), ("Shift Premium", "300.00", "150.00"), ("Bonus", "50.00", "400.00"),
           ("Gross Pay", "1,350.00", "2,550.00"), ("Net Pay", "1,350.00", "2,550.00")]


def b1_pages():
    return b_pages(B1_ROWS)


def b2_pages():
    return b_pages(B2_ROWS)


# --- SB: summary box (SC-70) ----------------------------------------------------------------------------------------------

BOX_EDGES = (200, 280, 370, 460)
BOX_HEADING = ("Gross Pay", "Taxes", "Deductions", "Net Pay")
BOX_CURRENT = ("2,687.50", "501.23", "134.38", "2,051.89")
BOX_YTD = ("33,625.00", "6,271.06", "1,681.25", "25,672.69")
SB_TABLE_ROWS = [PS_ROWS[i] for i in (0, 1, 3, 4, 5, 7)]  # PS rows 1, 2, 4, 5, 6, 8: no totals.


def sb_pages(order=(0, 1, 2, 3), heading=True):
    """SB: the box (heading at y 712, Current at 696, YTD at 680), PS's heading at y 650 and PS rows 1, 2, 4, 5, 6, 8 from y 630. `order` picks
    the box columns printed left to right (SB-SHUF); `heading` False leaves the box's heading out (SB-NOHEAD)."""
    items = []
    if heading:
        items += row_items(712, [(edge, BOX_HEADING[column], True) for edge, column in zip(BOX_EDGES, order)])
    for y, label, values in ((696, "Current", BOX_CURRENT), (680, "YTD", BOX_YTD)):
        items += row_items(y, [(40, label), *[(edge, values[column], True) for edge, column in zip(BOX_EDGES, order)]])
    items += [*head(650, PS_HEADING, PS_EDGES), *lay(630, ps_specs(SB_TABLE_ROWS), PS_EDGES)]
    return [page_of(items, ABOVE)]


def sb_shuf_pages():
    return sb_pages(order=(3, 1, 0, 2))  # Net Pay, Taxes, Gross Pay, Deductions


def sb_nohead_pages():
    return sb_pages(heading=False)


# --- MINI: the stub used in files of several (SC-72 - SC-76) --------------------------------------------------------------

def mini_items(top, date, n=1, ytd=True):
    """One MINI stub from top y `top`, dated `date`, with YTD multiplied by n (MINI-C with `ytd` False)."""
    edges = (CURRENT, YTD) if ytd else (CURRENT,)
    items = [(40, top, "SYNTH PAYROLL CO"), (40, top - 12, f"Pay date {date}"), (40, top - 24, "Currency USD"),
             *head(top - 48, ("Description", "Current", "YTD")[:len(edges) + 1], edges)]
    rows = [("Regular", 2000), ("Gross Pay", 2000), ("Federal Income Tax", 200), ("Total Taxes", 200), ("Net Pay", 1800)]
    for number, (label, amount) in enumerate(rows):
        texts = (f"{amount:,}.00", f"{amount * n:,}.00")[:len(edges)]
        items += row_items(top - 64 - 16 * number, [(40, label), *[(edge, text, True) for edge, text in zip(edges, texts)]])
    return items


def mini_pages(*stubs, ytd=True):
    """One page per stub: each stub is (date, n). MINI-C (`ytd` False) prints no YTD column."""
    return [{"items": [*mini_items(780, date, n, ytd), footer(FOOTER, 60)]} for date, n in stubs]


# --- SL-01's own fixtures -------------------------------------------------------------------------------------------------

def ps_cont_pages(heading=True, shift=0):
    """PS-CONT: PS split after Medicare over two pages. Page 2 repeats the heading (or not) and is drawn `shift` pt to the right."""
    first = {"items": [*lines_above(ABOVE), *head(700, PS_HEADING, PS_EDGES), *lay(680, ps_specs(PS_ROWS[:6]), PS_EDGES), footer(FOOTER, 60)]}
    items = head(780, PS_HEADING, PS_EDGES) if heading else []
    items += lay(760 if heading else 780, ps_specs(PS_ROWS[6:]), PS_EDGES)
    second = {"items": [(x + shift, y, text) for x, y, text in items] + [footer(FOOTER, 60)]}
    return [first, second]


def stubcut_pages():
    """STUBCUT: two stubs on one page with no net pay line, dated differently, whose rows share their columns: the second stub's pay date line
    ends the first stub's table."""
    items = []
    for top, date, amount in ((780, "2026-06-05", "2,000.00"), (600, "2026-06-19", "2,100.00")):
        items += [(40, top, "SYNTH PAYROLL CO"), (40, top - 12, f"Pay date {date}"), *head(top - 36, ("Description", "Current", "YTD"), (CURRENT, YTD)),
                  *lay(top - 52, [("row", "Regular", (amount, amount)), ("row", "Federal Income Tax", ("200.00", "200.00"))], (CURRENT, YTD))]
    return [{"items": [*items, footer(FOOTER, 60)]}]


def ps_stray_pages():
    """PS-STRAY: row 8 (401K) prints a fifth amount, 9.99, at right edge 600, where no other row prints and no heading is: it fits no column."""
    specs = [("row", row[0], (*row[1:5], "9.99" if row[0] == "401K" else "")) for row in PS_ROWS]
    return [page_of([*head(700, PS_HEADING, PS_EDGES), *lay(680, specs, EMP_EDGES)])]


def prose_pages():
    """SC-59's two pages: page 1 is PS; page 2 holds only prose (an amount inside a sentence) and the footer."""
    second = {"items": [(40, 780, "Message from payroll"),
                        (40, 768, "Your employer HSA contribution this period was 50.00 and is not part of your net pay."), footer(FOOTER, 60)]}
    return [ps_page(), second]


FIXTURES = {
    "PS": ps_pages, "PS-2L": ps_2l_pages, "PS-NH": ps_nh_pages, "PS-WRAP": ps_wrap_pages, "PS-SEC": ps_sec_pages,
    "PS-SEC-MEMO": lambda: ps_sec_pages(memo=True), "PS-OTHER": ps_other_pages, "PS-YTDH": ps_ytdh_pages, "PS-EMP": ps_emp_pages,
    "PS-DIGITS": ps_digits_pages, "PS-BONUS": ps_bonus_pages, "PS-SWAPHEAD": ps_swaphead_pages, "PS-BADTOTAL": ps_badtotal_pages,
    "PS-BADNET": ps_badnet_pages, "SBS": sbs_pages, "STK": stk_pages, "B1": b1_pages, "B2": b2_pages, "SB": sb_pages,
    "SB-SHUF": sb_shuf_pages, "SB-NOHEAD": sb_nohead_pages,
    "MINI-3": lambda: mini_pages(("2026-06-05", 11), ("2026-06-19", 12), ("2026-07-03", 13)),
    "MINI-C": lambda: mini_pages(("2025-11-07", 1), ytd=False),
    "PS-CONT": ps_cont_pages, "PS-CONT-NH": lambda: ps_cont_pages(heading=False, shift=6), "STUBCUT": stubcut_pages, "PS-PROSE": prose_pages, "PS-STRAY": ps_stray_pages,
}

# --- Expected engine-level facts (hand-written from the tables above) ---------------------------------------------------

# A table is (headings text, labels per amount column, rows [(label, section, texts)], totals [(label, kind, texts)]).
PS_ROWS_ENGINE = [
    ("Regular", None, ["80.00", "31.25", "2,500.00", "32,500.00"]),
    ("Overtime", None, ["4.00", "46.8750", "187.50", "1,125.00"]),
    ("Federal Income Tax", None, ["", "", "295.63", "3,698.75"]),
    ("Social Security", None, ["", "", "166.63", "2,084.75"]),
    ("Medicare", None, ["", "", "38.97", "487.56"]),
    ("401K", None, ["", "", "134.38", "1,681.25"]),
]
PS_TOTALS_ENGINE = [
    ("Gross Pay", "gross", ["", "", "2,687.50", "33,625.00"]),
    ("Total Taxes", "taxes", ["", "", "501.23", "6,271.06"]),
    ("Total Pre-Tax Deductions", "deductions", ["", "", "134.38", "1,681.25"]),
    ("Net Pay", "net", ["", "", "2,051.89", "25,672.69"]),
]
PS_ENGINE = (["Description Hours Rate Current YTD"], [["Hours"], ["Rate"], ["Current"], ["YTD"]], PS_ROWS_ENGINE, PS_TOTALS_ENGINE)
PS_2L_ENGINE = (["This Year to", "Description Hours Rate Period Date"], [["Hours"], ["Rate"], ["This", "Period"], ["Year to", "Date"]],
                PS_ROWS_ENGINE, PS_TOTALS_ENGINE)
PS_NH_ENGINE = ([], [[], [], [], []], [(label, section, [texts[0], texts[1], texts[3], texts[2]]) for label, section, texts in PS_ROWS_ENGINE],
                [(label, kind, [texts[0], texts[1], texts[3], texts[2]]) for label, kind, texts in PS_TOTALS_ENGINE])
PS_WRAP_ROWS = [("Federal Income Tax Withholding" if label == "Federal Income Tax" else label, section, texts) for label, section, texts in PS_ROWS_ENGINE]
PS_SEC_SECTIONS = {"Regular": "Earnings", "Overtime": "Earnings", "Federal Income Tax": "Taxes", "Social Security": "Taxes", "Medicare": "Taxes",
                   "401K": "Pre-tax"}
PS_SEC_ROWS = [(label, PS_SEC_SECTIONS[label], texts) for label, _, texts in PS_ROWS_ENGINE]

SBS_LEFT = (["Earnings Current YTD"], [["Current"], ["YTD"]],
            [("Regular", None, ["2,500.00", "32,500.00"]), ("Overtime", None, ["187.50", "1,125.00"])],
            [("Gross Pay", "gross", ["2,687.50", "33,625.00"]), ("Net Pay", "net", ["2,051.89", "25,672.69"])])
SBS_RIGHT = (["Deductions Current YTD"], [["Current"], ["YTD"]],
             [("Federal Income Tax", None, ["295.63", "3,698.75"]), ("Social Security", None, ["166.63", "2,084.75"]),
              ("Medicare", None, ["38.97", "487.56"]), ("401K", None, ["134.38", "1,681.25"])],
             [("Total Taxes", "taxes", ["501.23", "6,271.06"]), ("Total Pre-Tax Deductions", "deductions", ["134.38", "1,681.25"])])

STK_FIRST = (["Description Hours Rate Current YTD"], [["Hours"], ["Rate"], ["Current"], ["YTD"]], PS_ROWS_ENGINE[:2],
             [("Gross Pay", "gross", ["", "", "2,687.50", "33,625.00"])])
STK_SECOND = ([], [[], []],
              [("Federal Income Tax", "Statutory", ["295.63", "3,698.75"]), ("Social Security", "Statutory", ["166.63", "2,084.75"]),
               ("Medicare", "Statutory", ["38.97", "487.56"]), ("401K", "Voluntary", ["134.38", "1,681.25"])],
              [("Total Taxes", "taxes", ["501.23", "6,271.06"]), ("Total Pre-Tax Deductions", "deductions", ["134.38", "1,681.25"]),
               ("Net Pay", "net", ["2,051.89", "25,672.69"])])

DEPOSIT_ENGINE = (["Account Amount"], [["Amount"]], [("Checking 1234", None, ["1,551.89"]), ("Savings 5678", None, ["500.00"])], [])
LEAVE_ENGINE = (["Leave Accrued Used Balance"], [["Accrued"], ["Used"], ["Balance"]],
                [("Vacation", None, ["40.00", "8.00", "32.00"]), ("Sick", None, ["24.00", "0.00", "24.00"])], [])

PS_YTDH_ENGINE = (["Description Hours Rate Current YTD Hours YTD"], [["Hours"], ["Rate"], ["Current"], ["YTD Hours"], ["YTD"]],
                  [(label, section, [texts[0], texts[1], texts[2], {"Regular": "1,040.00", "Overtime": "24.00"}.get(label, ""), texts[3]])
                   for label, section, texts in PS_ROWS_ENGINE],
                  [(label, kind, [texts[0], texts[1], texts[2], "", texts[3]]) for label, kind, texts in PS_TOTALS_ENGINE])
PS_EMP_ENGINE = (["Description Hours Rate Current YTD Employer"], [["Hours"], ["Rate"], ["Current"], ["YTD"], ["Employer"]],
                 [(label, section, [*texts, "80.63" if label == "401K" else ""]) for label, section, texts in PS_ROWS_ENGINE],
                 [(label, kind, [*texts, ""]) for label, kind, texts in PS_TOTALS_ENGINE])

PS_DIGITS_ROWS = [*PS_ROWS_ENGINE[:5], ("PRE-TAX 401K", None, ["", "", "134.38", "1,681.25"]), ("SECTION 125", None, ["", "", "85.00", "1,105.00"])]
PS_DIGITS_TOTALS = [PS_TOTALS_ENGINE[0], PS_TOTALS_ENGINE[1], ("Total Pre-Tax Deductions", "deductions", ["", "", "219.38", "2,786.25"]),
                    ("Net Pay", "net", ["", "", "1,966.89", "24,567.69"])]

# SB: the box columns left to right with their heading, and its two rows; the table under it is PS's heading with rows 1, 2, 4, 5, 6, 8.
SB_BOX = ([["Gross Pay"], ["Taxes"], ["Deductions"], ["Net Pay"]],
          [("Current", ["2,687.50", "501.23", "134.38", "2,051.89"]), ("YTD", ["33,625.00", "6,271.06", "1,681.25", "25,672.69"])])
SB_SHUF_BOX = ([["Net Pay"], ["Taxes"], ["Gross Pay"], ["Deductions"]],
               [("Current", ["2,051.89", "501.23", "2,687.50", "134.38"]), ("YTD", ["25,672.69", "6,271.06", "33,625.00", "1,681.25"])])
SB_NOHEAD_BOX = ([[], [], [], []], SB_BOX[1])
SB_TABLE = (["Description Hours Rate Current YTD"], [["Hours"], ["Rate"], ["Current"], ["YTD"]], PS_ROWS_ENGINE, [])

B1_ENGINE = ([], [[], []], [("Regular", None, ["2,500.00", ""]), ("Relocation Bonus", None, ["", "5,000.00"])],
             [("Gross Pay", "gross", ["2,500.00", "5,000.00"]), ("Net Pay", "net", ["2,500.00", "5,000.00"])])
B2_ENGINE = ([], [[], []], [("Regular", None, ["1,000.00", "2,000.00"]), ("Shift Premium", None, ["300.00", "150.00"]), ("Bonus", None, ["50.00", "400.00"])],
             [("Gross Pay", "gross", ["1,350.00", "2,550.00"]), ("Net Pay", "net", ["1,350.00", "2,550.00"])])

MINI_ENGINE = lambda n: (["Description Current YTD"], [["Current"], ["YTD"]],  # noqa: E731
                         [("Regular", None, ["2,000.00", f"{2000 * n:,}.00"]), ("Federal Income Tax", None, ["200.00", f"{200 * n:,}.00"])],
                         [("Gross Pay", "gross", ["2,000.00", f"{2000 * n:,}.00"]), ("Total Taxes", "taxes", ["200.00", f"{200 * n:,}.00"]),
                          ("Net Pay", "net", ["1,800.00", f"{1800 * n:,}.00"])])

MINI_C_ENGINE = (["Description Current"], [["Current"]], [("Regular", None, ["2,000.00"]), ("Federal Income Tax", None, ["200.00"])],
                 [("Gross Pay", "gross", ["2,000.00"]), ("Total Taxes", "taxes", ["200.00"]), ("Net Pay", "net", ["1,800.00"])])

# PS-CONT: one table over two pages, 10 rows and totals in printed order, the second page's rows in the first page's columns.
PS_CONT_ENGINE = PS_ENGINE
# STUBCUT: two tables, one per stub, each with its two rows and no totals.
STUBCUT_TABLES = [
    (["Description Current YTD"], [["Current"], ["YTD"]], [("Regular", None, ["2,000.00", "2,000.00"]), ("Federal Income Tax", None, ["200.00", "200.00"])], []),
    (["Description Current YTD"], [["Current"], ["YTD"]], [("Regular", None, ["2,100.00", "2,100.00"]), ("Federal Income Tax", None, ["200.00", "200.00"])], []),
]

# --- Record expectations (EXP-PS and the others; minor units), shared with later slices -----------------------------------

EXP_PS_LINES = [  # (description, line_group, current_minor, ytd_minor, hours, rate)
    ("Regular", "earnings", 250000, 3250000, "80.00", "31.25"),
    ("Overtime", "earnings", 18750, 112500, "4.00", "46.8750"),
    ("Federal Income Tax", "tax", 29563, 369875, None, None),
    ("Social Security", "tax", 16663, 208475, None, None),
    ("Medicare", "tax", 3897, 48756, None, None),
    ("401K", "pre_tax", 13438, 168125, None, None),
]
EXP_PS = {"gross_pay_minor": 268750, "gross_pay_ytd_minor": 3362500, "net_pay_minor": 205189, "net_pay_ytd_minor": 2567269, "taxes_minor": 50123,
          "deductions_minor": 13438}
EXP_B1_LINES = [("Regular", "earnings", 250000, None), ("Relocation Bonus", "earnings", None, 500000)]
EXP_B2_LINES = [("Regular", "earnings", 100000, 200000), ("Shift Premium", "earnings", 30000, 15000), ("Bonus", "earnings", 5000, 40000)]
EXP_DIGITS_LINES = [*[line[:4] for line in EXP_PS_LINES[:5]], ("PRE-TAX 401K", "pre_tax", 13438, 168125), ("SECTION 125", "pre_tax", 8500, 110500)]
EXP_DIGITS = {"deductions_minor": 21938, "net_pay_minor": 196689, "net_pay_ytd_minor": 2456769}


def mini_expected(n):
    return {"lines": [("Regular", "earnings", 200000, 200000 * n), ("Federal Income Tax", "tax", 20000, 20000 * n)],
            "gross": (200000, 200000 * n), "net": (180000, 180000 * n)}
