"""Synthetic PDF fixtures, stubs and expected values for the pdf-table-engine-bills contract (specs/pdf-table-engine-bills/test-contract.md "Fixtures").

Builders return `make_pdf` pages (positioned-item dicts, 10 pt Helvetica, page 612 x 792). Expected values are the contract's tables written out by hand
below, never computed from the code under test. Every page ends with the words-only footer `FOOTER` at (40, 40), so the reader never sends it to the vision
model and no amount is in it. A right-aligned amount's left x is its right edge minus its Helvetica width (digits 5.56 pt, `,` and `.` 2.78 pt, `-` `(` `)`
3.33 pt, `$` 5.56 pt, letters by the Helvetica AFM widths: `table_engine_fixtures.width`), as in the other table-engine fixtures, whose helpers are reused.

Printed texts keep the contract's spelling. Three kinds of names:
- `FIXTURES` maps a contract fixture name (BL-UTIL, UTIL-2L, BL-PHONE, MINI-BILL(k) ...) to a builder of its pages.
- `*_ENGINE` values are the engine-level facts the contract states (SL-01), as printed text: per fixture its charge rows, totals, anchors, other tables and
  unplaced lines. `EXP_*` values are the Record expectations (minor units), written here so later slices share them.
- `STUB_*` values are the reasoning model's answers as plain data (the contract's "Doubles" table): per charge row the description, the line kind, the category,
  the holder and the amounts the stub gives, keyed by the row's printed label. The record test turns them into `BillLines` / `BillSummary` replies once it
  has read the evidence line ids (tests/test_paystub_engine_record.py `Run.stub` is the pattern); nothing here needs a store.
"""

from pdf_import_fixtures import footer
from table_engine_fixtures import row_items

FOOTER = "This bill is for your records. Amounts are in US dollars."
USAGE, RATE, CHARGE = 330, 420, 520  # The right edges of BL-UTIL's three amount columns.


def page_of(items, extra=None):
    """A page: the items and the footer at (40, 40)."""
    return {"items": [*items, footer(FOOTER, 40)], **(extra or {})}


def left(y, text, x=40):
    return [(x, y, text)]


def amounts_at(y, label, *cells, x=40):
    """A printed line: the label at x and each (right edge, text) right-aligned (a blank text prints nothing)."""
    return row_items(y, [(x, label), *[(edge, text, True) for edge, text in cells]])


def heading(y, *cells):
    """A heading line: (right edge, text) cells, right-aligned over their columns."""
    return row_items(y, [(edge, text, True) for edge, text in cells])


# --- BL-UTIL: the utility bill (one page) ---------------------------------------------------------------------------------------

UTIL_HEADER = ("CITY POWER & WATER", "Account Number 1234-5678-9012", "Statement Date 09/20/2026", "Billing Period 08/15/2026 - 09/14/2026", "Due Date 10/15/2026")
UTIL_SUMMARY = [("Previous Balance", "82.10"), ("Payment Received 09/20/2026", "-82.10"), ("New Charges", "97.55"), ("Total Amount Due", "97.55")]
UTIL_ENERGY = [("Energy Tier 1", "500 kWh", "0.1200", "60.00"), ("Energy Tier 2", "140 kWh", "0.1430", "20.02")]
UTIL_HISTORY = [("Sep 2025", "590", "30"), ("Oct 2025", "610", "31"), ("Nov 2025", "540", "30"), ("Dec 2025", "600", "31"), ("Jan 2026", "680", "31"),
                ("Feb 2026", "720", "28"), ("Mar 2026", "650", "31"), ("Apr 2026", "560", "30"), ("May 2026", "500", "31"), ("Jun 2026", "520", "30"),
                ("Jul 2026", "610", "31"), ("Aug 2026", "640", "31")]
UTIL_STUB = (("Account Number 1234-5678-9012"), ("Due Date 10/15/2026"))


def util_items(summary=None, heading_lines="std", energy=None, total_current="97.55", stub_amount="97.55", history=True, stub=True, extra=(), above=()):
    """BL-UTIL's items. `summary` replaces the four box lines (None keeps them; a line is (label, amount) from y 692 down, 16 apart); `heading_lines` is
    "std", "2l", "odd", None (no heading) or a list of ready items; `total_current` None leaves the `Total Current Charges` line out; `history` and `stub`
    leave the usage history and the remittance stub out when False."""
    items = [(40, 780 - 12 * number, text) for number, text in enumerate(UTIL_HEADER)]
    items += left(708, "Account Summary")
    for number, (label, amount) in enumerate(UTIL_SUMMARY if summary is None else summary):
        items += amounts_at(692 - 16 * number, label, (CHARGE, amount))
    items += left(620, "Electric Charges")
    heads = {"std": heading(604, (USAGE, "Usage"), (RATE, "Rate"), (CHARGE, "Charge")),
             "2l": [*heading(616, (USAGE, "Usage"), (RATE, "Rate per"), (CHARGE, "This")), *heading(604, (USAGE, "(kWh)"), (RATE, "kWh"), (CHARGE, "Charge"))],
             "odd": heading(604, (USAGE, "Consumed"), (RATE, "Price"), (CHARGE, "Amount Billed")), None: []}
    items += heads[heading_lines] if heading_lines in heads else heading_lines
    for number, (label, usage, rate, charge) in enumerate(energy or UTIL_ENERGY):
        items += amounts_at(588 - 16 * number, label, (USAGE, usage), (RATE, rate), (CHARGE, charge))
    items += amounts_at(556, "Customer Charge", (CHARGE, "12.00"))
    items += left(532, "Taxes and Fees")
    items += amounts_at(516, "State Tax", (CHARGE, "5.53"))
    if total_current:
        items += amounts_at(492, "Total Current Charges", (CHARGE, total_current))
    if history:
        items += left(468, "Usage History")
        items += heading(452, (USAGE, "kWh"), (RATE, "Days")) + left(452, "Month")
        for number, (month, kwh, days) in enumerate(UTIL_HISTORY):
            items += amounts_at(440 - 12 * number, month, (USAGE, kwh), (RATE, days))
    if stub:
        items += left(280, "Return this portion with your payment") + left(264, UTIL_STUB[0]) + left(248, UTIL_STUB[1])
        items += amounts_at(232, "Amount Due", (CHARGE, stub_amount))
    return [*above, *items, *extra]


def util_pages(**changes):
    return [page_of(util_items(**changes))]


UTIL_SHUF_HEAD = heading(604, (USAGE, "Charge"), (RATE, "Usage"), (CHARGE, "Rate"))


def util_shuf_items(head=True):
    """UTIL-SHUF (SC-105 a): Charge r330, Usage r420, Rate r520, each row's values moved with its column; Customer Charge and State Tax at r330. With
    `head` False the heading line is gone: BL-HEADLESS (SC-105 b)."""
    items = [(40, 780 - 12 * number, text) for number, text in enumerate(UTIL_HEADER)] + left(708, "Account Summary")
    for number, (label, amount) in enumerate(UTIL_SUMMARY):
        items += amounts_at(692 - 16 * number, label, (CHARGE, amount))
    items += left(620, "Electric Charges") + (UTIL_SHUF_HEAD if head else [])
    for number, (label, usage, rate, charge) in enumerate(UTIL_ENERGY):
        items += amounts_at(588 - 16 * number, label, (USAGE, charge), (RATE, usage), (CHARGE, rate))
    items += amounts_at(556, "Customer Charge", (USAGE, "12.00")) + left(532, "Taxes and Fees") + amounts_at(516, "State Tax", (USAGE, "5.53"))
    items += amounts_at(492, "Total Current Charges", (CHARGE, "97.55")) + left(280, "Return this portion with your payment")
    items += left(264, UTIL_STUB[0]) + left(248, UTIL_STUB[1]) + amounts_at(232, "Amount Due", (CHARGE, "97.55"))
    return items


def util_lastyear_items(head=True):
    """UTIL-LASTYEAR (SC-105 c, c2 with `head` False): `This Bill` r420 and `Last Year` r520 over three rows."""
    items = [(40, 780 - 12 * number, text) for number, text in enumerate(UTIL_HEADER)] + left(708, "Account Summary")
    for number, (label, amount) in enumerate(UTIL_SUMMARY):
        items += amounts_at(692 - 16 * number, label, (CHARGE, amount))
    items += left(620, "Electric Charges") + (heading(604, (RATE, "This Bill"), (CHARGE, "Last Year")) if head else [])
    for number, (label, this, last) in enumerate((("Energy Charge", "80.02", "72.15"), ("Customer Charge", "12.00", "12.00"), ("State Tax", "5.53", "4.98"))):
        items += amounts_at(588 - 16 * number, label, (RATE, this), (CHARGE, last))
    items += amounts_at(492, "Total Current Charges", (CHARGE, "97.55")) + left(280, "Return this portion with your payment")
    items += left(264, UTIL_STUB[0]) + left(248, UTIL_STUB[1]) + amounts_at(232, "Amount Due", (CHARGE, "97.55"))
    return items


LATE_TEXT = "If paid after 10/15/2026, pay $102.55"


def util_late_pages(column=False):
    """UTIL-LATE: the late line in one run. UTIL-LATE-COL (`column`): the same with `102.55` alone at r520."""
    if column:
        return [page_of(util_items(extra=[*left(216, "If paid after 10/15/2026, pay"), *heading(216, (CHARGE, "102.55"))]))]
    return [page_of(util_items(extra=left(216, LATE_TEXT)))]


def util_half_pages(rate="0.1450", charge="20.30", total="97.83"):
    """UTIL-HALF (SC-110 step 6): Energy Tier 2's rate 0.1450 and its charge 20.30; every new-charges and amount-due line 97.83."""
    energy = [UTIL_ENERGY[0], ("Energy Tier 2", "140 kWh", rate, charge)]
    summary = [*UTIL_SUMMARY[:2], ("New Charges", total), ("Total Amount Due", total)]
    return [page_of(util_items(summary=summary, energy=energy, total_current=total, stub_amount=total))]


def util_15_pages():
    """UTIL-15 (D25): Energy Tier 2's rate printed 0.1500 and its charge 21.00; 98.53 everywhere."""
    return util_half_pages("0.1500", "21.00", "98.53")


def util_125_pages():
    """UTIL-125 (D25): Energy Tier 2's rate printed 0.125 and its charge 17.50; 95.03 everywhere."""
    return util_half_pages("0.125", "17.50", "95.03")


def util_stray_pages():
    """UTIL-STRAY (SC-104): a line of text with 2.00 at r590, outside every column."""
    return [page_of(util_items(extra=[*left(196, "Paperless billing saves paper"), *heading(196, (590, "2.00"))]))]


def util_sentence_pages():
    """G7: BL-UTIL plus a sentence that holds an anchor phrase, with an amount in its own run at r520."""
    return [page_of(util_items(extra=amounts_at(196, "Your previous balance was paid in full", (CHARGE, "82.10"))))]


def util_misnc_pages():
    """UTIL-MISNC (SC-113 b): `New Charges` and `Total Current Charges` both printed 99.55."""
    return [page_of(util_items(summary=[*UTIL_SUMMARY[:2], ("New Charges", "99.55"), UTIL_SUMMARY[3]], total_current="99.55"))]


def util_2p_pages():
    """UTIL-2P (SC-114): page 1 = BL-UTIL with 99.55 in the box and no `Total Current Charges`, no stub; page 2 = prose and the remittance stub."""
    first = util_items(summary=[*UTIL_SUMMARY[:2], ("New Charges", "99.55"), ("Total Amount Due", "99.55")], total_current=None, stub=False)
    second = [*left(780, "A message from City Power & Water"), *left(768, "Your paper bill fee this month was 2.00."), *left(700, "Return this portion with your payment"),
              *left(684, UTIL_STUB[0]), *left(668, UTIL_STUB[1]), *amounts_at(652, "Amount Due", (CHARGE, "99.55"))]
    return [page_of(first), page_of(second)]


def util_r1_pages(variant="a"):
    """BL-UTIL-R1 (SC-117). (a) `Balance Due` 50.00 first on page 1, Previous Balance 132.10, 147.55 for the box total and the stub. (b) no
    Previous Balance, Payment Received, New Charges nor Total Current Charges, Balance Due 50.00, 97.55. (c) no Previous Balance nor Payment Received,
    Balance Due 50.00, 147.55 in the box and stub, new charges 97.55 twice."""
    first = amounts_at(720, "Balance Due", (CHARGE, "50.00"))
    if variant == "a":
        return [page_of(util_items(summary=[("Previous Balance", "132.10"), UTIL_SUMMARY[1], UTIL_SUMMARY[2], ("Total Amount Due", "147.55")], stub_amount="147.55",
                                   above=first))]
    if variant == "b":
        return [page_of(util_items(summary=[("Total Amount Due", "97.55")], total_current=None, above=first))]
    return [page_of(util_items(summary=[UTIL_SUMMARY[2], ("Total Amount Due", "147.55")], stub_amount="147.55", above=first))]


def util_r2_pages(variant="r2"):
    """BL-UTIL-R2 (SC-118): no New Charges nor Total Current Charges, Previous Balance 150.00, Payment Received -100.00, 147.55 in the box and stub.
    R2-BAD: 150.55. R2-NOPREV: no Previous Balance nor Payment Received."""
    total = "150.55" if variant == "bad" else "147.55"
    summary = [("Total Amount Due", total)] if variant == "noprev" else [("Previous Balance", "150.00"), ("Payment Received 09/20/2026", "-100.00"), ("Total Amount Due", total)]
    return [page_of(util_items(summary=summary, total_current=None, stub_amount=total))]


# --- BL-PHONE: the phone bill (one page, no column heading) -----------------------------------------------------------------------

PHONE_HEADER = ("METRO WIRELESS", "Account Number 555-0100-7788", "Due Date 10/12/2026")


def phone_pages(discount="-5.00", credits="Account Credits"):
    """BL-PHONE. SC-106's variants print the discount differently (`(5.00)`, `5.00 CR`, unsigned `5.00`) or under another section title."""
    items = [(40, 780 - 12 * number, text) for number, text in enumerate(PHONE_HEADER)]
    for y, label, amount in ((732, "Previous Balance", "120.00"), (716, "Payments", "-120.00"), (700, "New Charges", "118.50"), (684, "Amount Due", "118.50")):
        items += amounts_at(y, label, (CHARGE, amount))
    items += left(660, "Alex 555-201-1111")
    for y, label, amount in ((644, "Unlimited Plan", "55.00"), (628, "Device Payment", "24.99"), (612, "Total for Alex", "79.99")):
        items += amounts_at(y, label, (CHARGE, amount))
    items += left(588, "Blair (555) 202-2222") + amounts_at(572, "Basic Plan", (CHARGE, "35.00")) + amounts_at(556, "International Pack", (CHARGE, "8.51"))
    items += left(546, "(Canada and Mexico)", 52) + amounts_at(530, "Total for Blair", (CHARGE, "43.51")) + left(506, credits)
    items += amounts_at(490, "Autopay Discount", (CHARGE, discount))
    return [page_of(items)]


def role_pages(heads=(), rows=(), summary=(), extra=()):
    """A hand-built page for SC-105's role tests: `summary` (label, amount) anchor lines from y 700 down; `heads` (right edge, text) cells; `rows` (label,
    (right edge, text) ...) from y 600 down, 16 apart, each given as `(label, *cells)`; `extra` ready items below the rows."""
    items = []
    for number, (label, amount) in enumerate(summary):
        items += amounts_at(700 - 16 * number, label, (CHARGE, amount))
    items += heading(620, *heads) if heads else []
    for number, (label, *cells) in enumerate(rows):
        items += amounts_at(600 - 16 * number, label, *cells)
    return [page_of([*items, *extra])]


# --- BL-RENT: the rent bill as a text PDF -----------------------------------------------------------------------------------------

RENT_LABELS = ["SYNTH PROPERTY MANAGEMENT", "Resident Account ****4821", "Rent and Leasing Charges Due 10/01/2026", "Rent 10/01/2026 - 10/31/2026",
               "Water Usage 08/15/2026 - 09/14/2026 3,200 GAL", "Due Date " + "." * 59 + " 10/01/2026", "Amount Due" + "." * 57]
RENT_AMOUNTS = {3: "$1,450.00", 4: "$38.42", 6: "$1,488.42"}


def rent_pages():
    """tests/bill_kinds_fixtures.py RENT's seven lines at x 40 from y 780, 16 apart, each trailing `$` amount split off into its own run at r520."""
    items = []
    for number, label in enumerate(RENT_LABELS):
        items += amounts_at(780 - 16 * number, label, *([(CHARGE, RENT_AMOUNTS[number])] if number in RENT_AMOUNTS else []))
    return [page_of(items)]


def payment_received_page():
    """SC-100 step 3: a hand-built page of the single line `Payment Received 09/03/2026` with -100.00 at r520."""
    return [page_of(amounts_at(700, "Payment Received 09/03/2026", (CHARGE, "-100.00")))]


# --- MINI-BILL(k) and the multi-bill files ----------------------------------------------------------------------------------------

# k: (S statement date, B period, D due date, P previous, R payments, E energy, T tax, N new charges, A amount due)
MINI = {1: ("07/02/2026", "06/01/2026 - 06/30/2026", "07/20/2026", "80.00", "-80.00", "64.80", "4.62", "81.42", "81.42"),
        2: ("08/03/2026", "07/01/2026 - 07/31/2026", "08/20/2026", "81.42", "-81.42", "70.20", "5.06", "87.26", "87.26"),
        3: ("09/02/2026", "08/01/2026 - 08/31/2026", "09/20/2026", "87.26", "-50.00", "58.50", "4.22", "74.72", "111.98")}


def mini_items(k, top=780, account="1234-5678-9012", omit=(), compact=False, dates_of=None):
    """MINI-BILL(k)'s fifteen lines. `top` moves the first line (compact: 12 pt apart from `top`, BL-TWOONPAGE); `omit` leaves out the lines whose label starts with
    one of its prefixes (BL-NOKEY: no Account Number, Statement Date or Due Date line, the stub's included; BL-JOIN: no Total Amount Due nor stub Amount Due);
    `dates_of` prints another bill's statement date, period and due date (BL-ACCT)."""
    s, b, d, p, r, e, t, n, a = MINI[k]
    s, b, d = MINI[dates_of or k][:3]
    spec = [("CITY POWER & WATER", None), (f"Account Number {account}", None), (f"Statement Date {s}", None), (f"Billing Period {b}", None), (f"Due Date {d}", None),
            ("Previous Balance", p), ("Payment Received", r), ("New Charges", n), ("Total Amount Due", a), ("Customer Charge", "12.00"), ("Energy Charge", e),
            ("State Tax", t), ("Total Current Charges", n), (f"Due Date {d}", None), ("Amount Due", a)]
    if compact:
        ys = [top - 12 * number for number in range(len(spec))]
    else:
        ys = [top - drop for drop in (0, 12, 24, 36, 48, 80, 96, 112, 128, 160, 176, 192, 216, 480, 496)]
    items = []
    for (label, amount), y in zip(spec, ys):
        if not label.startswith(omit or ("\0",)):
            items += amounts_at(y, label, *([(CHARGE, amount)] if amount else []))
    return items


def mini_pages(*numbers):
    return [page_of(mini_items(k)) for k in numbers]


def remit_pages():
    """BL-REMIT: page 1 = BL-UTIL down to `Total Current Charges`; page 2 = a repeated header, the usage table, a sentence and the stub."""
    first = util_items(history=False, stub=False)
    second = [*left(780, "CITY POWER & WATER"), *left(768, UTIL_HEADER[1]), *left(756, UTIL_HEADER[2]), *left(720, "Usage History"),
              *heading(704, (USAGE, "kWh"), (RATE, "Days")), *left(704, "Month")]
    for number, (month, kwh, days) in enumerate(UTIL_HISTORY):
        second += amounts_at(692 - 12 * number, month, (USAGE, kwh), (RATE, days))
    second += left(520, "Your previous bill, due 09/15/2026, is past due.") + left(480, "Due Date 10/15/2026") + amounts_at(464, "Amount Due", (CHARGE, "97.55"))
    return [page_of(first), page_of(second)]


def acct_pages():
    """BL-ACCT: page 1 = MINI-BILL(1); page 2 = MINI-BILL(1)'s S, B, D with account 1234-5678-3456 and MINI-BILL(2)'s P, R, E, T, N, A."""
    return [page_of(mini_items(1)), page_of(mini_items(2, account="1234-5678-3456", dates_of=1))]


def join_pages():
    """BL-JOIN: BL-MULTI with page 2's `Total Amount Due` and stub `Amount Due` lines removed."""
    return [page_of(mini_items(1)), page_of(mini_items(2, omit=("Total Amount Due", "Amount Due"))), page_of(mini_items(3))]


def two_on_page_pages():
    """BL-TWOONPAGE: MINI-BILL(1)'s lines from y 780, 12 pt apart, then MINI-BILL(2)'s from y 560, 12 pt apart."""
    return [page_of([*mini_items(1, 780, compact=True), *mini_items(2, 560, compact=True)])]


def nokey_pages():
    """BL-NOKEY: page 1 = MINI-BILL(1); page 2 = MINI-BILL(2) with no Account Number, Statement Date or Due Date line anywhere."""
    return [page_of(mini_items(1)), page_of(mini_items(2, omit=("Account Number", "Statement Date", "Due Date")))]


def multi_void_pages(word=False):
    """BL-MULTI-VOID: BL-MULTI with `VOID` at x 260, y 720 on page 2. BL-MULTI-VOIDWORD: `Checks are void after 90 days` in the same place."""
    pages = mini_pages(1, 2, 3)
    pages[1]["items"] += [(260, 720, "Checks are void after 90 days" if word else "VOID")]
    return pages


def multi_inv_pages():
    """BL-MULTI-INV: BL-MULTI with `Invoice Number INV-2002` at x 40, y 720 on page 2."""
    pages = mini_pages(1, 2, 3)
    pages[1]["items"] += left(720, "Invoice Number INV-2002")
    return pages


def mini_transcription(k):
    """The vision stub's transcription of MINI-BILL(k): one line per printed line, label and amounts joined by a space (MULTI-SCAN, MULTI-IMAGES, MINI-PNG).
    The scanned PDF is `[None, None, None]` pages of `make_pdf`; the PNG files are written with tests/test_receipts.py's `make_receipt`."""
    s, b, d, p, r, e, t, n, a = MINI[k]
    return ["CITY POWER & WATER", "Account Number 1234-5678-9012", f"Statement Date {s}", f"Billing Period {b}", f"Due Date {d}", f"Previous Balance {p}",
            f"Payment Received {r}", f"New Charges {n}", f"Total Amount Due {a}", "Customer Charge 12.00", f"Energy Charge {e}", f"State Tax {t}",
            f"Total Current Charges {n}", f"Due Date {d}", f"Amount Due {a}"]


# --- Hand-built pages for the section title table (SC-102 step 9) ------------------------------------------------------------------

TITLE_ABOVE = ("SYNTH TITLE CO", "Account Number 1234-5678-9012", "Due Date 10/15/2026", "Statement Date 09/20/2026", "Billing Period 08/15/2026 - 09/14/2026",
               "Thank you for being a customer of this synthetic provider", "Questions about your bill? Visit the synthetic website")


def title_page(title, size=None, rows=(("Plan", "10.00"), ("Device", "5.00")), encoding=None):
    """A one-section page: a header, the title at x 40 and the rows after it (two rows: one row alone forms no column). `size` prints the title smaller, so a
    90 character title fits the page; the header keeps the page's median font size at 10."""
    items = [(40, 780 - 12 * number, text) for number, text in enumerate(TITLE_ABOVE)]
    items += [(40, 680, title, size)] if size else [(40, 680, title)]
    for number, (label, amount) in enumerate(rows):
        items += amounts_at(664 - 16 * number, label, (CHARGE, amount))
    return [page_of(items, {"encoding": encoding} if encoding else None)]


# Title as printed -> (holder title?, the title's text as read). SC-102 step 9's table; the 80-character cut is Record's (SL-03).
PHONE_TITLES = [
    ("Alex 555-201-1111", True, "Alex 555-201-1111"), ("Blair (555) 202-2222", True, "Blair (555) 202-2222"), ("Alex 555.201.1111", True, "Alex 555.201.1111"),
    ("Line 201-1111", True, "Line 201-1111"), ("Alex xxx-xxx-1111", True, "Alex xxx-xxx-1111"), ("Alex ***-1111", True, "Alex ***-1111"),
    ("Alex •••• 1111", True, "Alex •••• 1111"), ("Line ending 1111", True, "Line ending 1111"), ("Line ending in 1111", True, "Line ending in 1111"),
    ("Phone ends in 1111", True, "Phone ends in 1111"), ("Alex   555-201-1111", True, "Alex 555-201-1111"),
    ("Charges 2026", False, "Charges 2026"), ("Electric Charges", False, "Electric Charges"),
    # G14: not phone numbers; and a masked number does count.
    ("Charges 2025-2026", False, "Charges 2025-2026"), ("Charges 2025 - 2026", False, "Charges 2025 - 2026"),
    ("Account 1234-5678-9012", False, "Account 1234-5678-9012"), ("Account ****9012", True, "Account ****9012"),
]
LONG_TITLE = "555-201-1111 " + "Z" * 90  # Phone number first; Record cuts it to 80 characters (FR-102), the engine reads it whole.

# --- Fixture registry -------------------------------------------------------------------------------------------------------------

FIXTURES = {
    "BL-UTIL": util_pages, "UTIL-2L": lambda: util_pages(heading_lines="2l"), "UTIL-ODD": lambda: util_pages(heading_lines="odd"),
    "UTIL-NOHEAD": lambda: util_pages(heading_lines=None), "UTIL-SHUF": lambda: [page_of(util_shuf_items())], "BL-HEADLESS": lambda: [page_of(util_shuf_items(False))],
    "UTIL-LASTYEAR": lambda: [page_of(util_lastyear_items())], "UTIL-LASTYEAR-C2": lambda: [page_of(util_lastyear_items(False))],
    "UTIL-LATE": util_late_pages, "UTIL-LATE-COL": lambda: util_late_pages(True), "UTIL-HALF": util_half_pages, "UTIL-15": util_15_pages, "UTIL-125": util_125_pages,
    "UTIL-STRAY": util_stray_pages, "UTIL-SENTENCE": util_sentence_pages, "UTIL-MISNC": util_misnc_pages, "UTIL-2P": util_2p_pages,
    "UTIL-R1-A": util_r1_pages, "UTIL-R1-B": lambda: util_r1_pages("b"), "UTIL-R1-C": lambda: util_r1_pages("c"),
    "UTIL-R2": util_r2_pages, "UTIL-R2-BAD": lambda: util_r2_pages("bad"), "UTIL-R2-NOPREV": lambda: util_r2_pages("noprev"),
    "BL-PHONE": phone_pages, "BL-RENT": rent_pages, "PAYMENT-RECEIVED": payment_received_page,
    "MINI-1": lambda: mini_pages(1), "MINI-2-ALONE": lambda: mini_pages(2), "BL-MULTI": lambda: mini_pages(1, 2, 3), "BL-REMIT": remit_pages, "BL-ACCT": acct_pages,
    "BL-JOIN": join_pages, "BL-TWOONPAGE": two_on_page_pages, "BL-NOKEY": nokey_pages, "BL-MULTI-VOID": multi_void_pages,
    "BL-MULTI-VOIDWORD": lambda: multi_void_pages(True), "BL-MULTI-INV": multi_inv_pages,
    "MULTI-SCAN": lambda: [None, None, None],
}
# The fixtures SC-126 reads as scanned or as images (no embedded text) are not native pages; the others are.
NOT_NATIVE = frozenset(("MULTI-SCAN",))

# --- Engine-level facts (SL-01), as printed -------------------------------------------------------------------------------------------

# BL-UTIL: the charge table's rows (label, section, usage, rate, charge) and the sections in order, the six anchors, the twelve other-table rows.
UTIL_ENGINE_ROWS = [("Energy Tier 1", "Electric Charges", "500 kWh", "0.1200", "60.00"), ("Energy Tier 2", "Electric Charges", "140 kWh", "0.1430", "20.02"),
                    ("Customer Charge", "Electric Charges", "", "", "12.00"), ("State Tax", "Taxes and Fees", "", "", "5.53")]
UTIL_ENGINE_ANCHORS = [("previous_balance", "82.10"), ("payments", "-82.10"), ("new_charges", "97.55"), ("amount_due", "97.55"), ("new_charges", "97.55"),
                       ("amount_due", "97.55")]
UTIL_ENGINE_HISTORY = UTIL_HISTORY  # (label, kWh, Days)

# BL-PHONE: (label, section, charge), the totals, the anchors.
PHONE_ENGINE_ROWS = [("Unlimited Plan", "Alex 555-201-1111", "55.00"), ("Device Payment", "Alex 555-201-1111", "24.99"), ("Basic Plan", "Blair (555) 202-2222", "35.00"),
                     ("International Pack (Canada and Mexico)", "Blair (555) 202-2222", "8.51"), ("Autopay Discount", "Account Credits", "-5.00")]
PHONE_ENGINE_TOTALS = [("Total for Alex", "79.99"), ("Total for Blair", "43.51")]
PHONE_ENGINE_ANCHORS = [("previous_balance", "120.00"), ("payments", "-120.00"), ("new_charges", "118.50"), ("amount_due", "118.50")]

# BL-RENT: (label, charge).
RENT_ENGINE_ROWS = [("Rent 10/01/2026 - 10/31/2026", "$1,450.00"), ("Water Usage 08/15/2026 - 09/14/2026 3,200 GAL", "$38.42")]

# --- Record expectations (minor units; the contract's EXP-* values) ---------------------------------------------------------------

# C-lines: (description, line_total_minor, line_kind), then quantity text and unit_price_minor and the printed rate where listed.
EXP_UTIL_LINES = [("Energy Tier 1", 6000, "usage"), ("Energy Tier 2", 2002, "usage"), ("Customer Charge", 1200, "service"), ("State Tax", 553, "tax_fee")]
EXP_UTIL_QUANTITY = {"Energy Tier 1": "500 kWh", "Energy Tier 2": "140 kWh"}
EXP_UTIL_RATE = {"Energy Tier 1": (12, None), "Energy Tier 2": (14, "0.1430")}  # (unit_price_minor, printed text kept in details when not whole cents)
EXP_UTIL = {"total_minor": 9755, "amount_due_minor": 9755, "due_date": "2026-10-15", "issue_date": "2026-09-20", "period": ("2026-08-15", "2026-09-14"),
            "previous_balance": 8210, "payments_received": 8210, "new_charges": 9755}

# K is the LINE_KINDS value STUB-PHONE gives Device Payment (named once).
PHONE_DEVICE_KIND = "device"
EXP_PHONE_LINES = [("Unlimited Plan", 5500, "service"), ("Device Payment", 2499, PHONE_DEVICE_KIND), ("Basic Plan", 3500, "service"),
                   ("International Pack (Canada and Mexico)", 851, "service"), ("Autopay Discount", -500, "credit")]
EXP_PHONE = {"total_minor": 11850, "amount_due_minor": 11850, "previous_balance": 12000, "payments_received": 12000}
EXP_PHONE_HOLDERS = ["Alex 555-201-1111", "Alex 555-201-1111", "Blair 555-202-2222", "Blair 555-202-2222", None]
PHONE_TITLE_LINES = {"Alex": 660, "Blair": 588}  # The y of each holder title: the rows' evidence includes it.

EXP_RENT_LINES = [("Rent", 145000, "rent"), ("Water Usage", 3842, "utility")]
EXP_RENT = {"amount_due_minor": 148842, "total_minor": 148842, "periods": (("2026-10-01", "2026-10-31"), ("2026-08-15", "2026-09-14")), "usage": "3,200 GAL"}


def exp_mini(k):
    """EXP-MINI(k): the lines and the bill's amounts, minor units, from MINI's table."""
    s, b, d, p, r, e, t, n, a = MINI[k]
    minor = lambda text: round(abs(float(text.replace(",", ""))) * 100)  # noqa: E731
    month, day, year = d.split("/")
    return {"lines": [("Customer Charge", 1200, "service"), ("Energy Charge", minor(e), "usage"), ("State Tax", minor(t), "tax_fee")],
            "total_minor": minor(n), "amount_due_minor": minor(a), "due_date": f"{year}-{month}-{day}", "previous_balance": minor(p), "payments_received": minor(r)}


# --- Stubs: the model's answers as data (the contract's "Doubles") ----------------------------------------------------------------------

# One entry per charge row of the fixture, keyed by its printed label: description, line_kind, category, line_holder, amount, quantity, unit_price.
STUB_UTIL = {"Energy Tier 1": ("Energy Tier 1", "usage", "utilities", None, "60.00", "500 kWh", "0.1200"),
             "Energy Tier 2": ("Energy Tier 2", "usage", "utilities", None, "20.02", "140 kWh", "0.1430"),
             "Customer Charge": ("Customer Charge", "service", "utilities", None, "12.00", None, None),
             "State Tax": ("State Tax", "tax_fee", "utilities", None, "5.53", None, None)}
# STUB-UTIL-WRONG: every amount 1.00 too high, quantities 600 kWh / 150 kWh, rates 0.1300 / 0.1500, Customer Charge given quantity 1 and unit price 13.00.
STUB_UTIL_WRONG = {"Energy Tier 1": ("Energy Tier 1", "usage", "utilities", None, "61.00", "600 kWh", "0.1300"),
                   "Energy Tier 2": ("Energy Tier 2", "usage", "utilities", None, "21.02", "150 kWh", "0.1500"),
                   "Customer Charge": ("Customer Charge", "service", "utilities", None, "13.00", "1", "13.00"),
                   "State Tax": ("State Tax", "tax_fee", "utilities", None, "6.53", None, None)}
STUB_UTIL_SUMMARY = {"previous_balance": "82.10", "payments_received": "-82.10", "new_charges": "97.55", "amount_due": "97.55"}
STUB_UTIL_WRONG_SUMMARY = {"previous_balance": "83.10", "payments_received": "-83.10", "new_charges": "98.55", "amount_due": "98.55"}

STUB_PHONE = {"Unlimited Plan": ("Unlimited Plan", "service", "utilities", "Alex 555-201-1111", "55.00", None, None),
              "Device Payment": ("Device Payment", PHONE_DEVICE_KIND, "utilities", None, "24.99", None, None),
              "Basic Plan": ("Basic Plan", "service", "utilities", "Blair 555-202-2222", "35.00", None, None),
              "International Pack (Canada and Mexico)": ("International Pack (Canada and Mexico)", "service", "utilities", None, "8.51", None, None),
              "Autopay Discount": ("Autopay Discount", "credit", "utilities", None, "5.00", None, None)}


def stub_phone(**holders):
    """STUB-PHONE with some holders replaced, keyed by label (None gives the row no holder): STUB-PHONE-NOHOLD, -DISAGREE, -AGREE and -CREDITHOLD."""
    return {label: (*row[:3], holders.get(label, row[3]), *row[4:]) for label, row in STUB_PHONE.items()}


STUB_PHONE_NOHOLD = stub_phone(**{"Unlimited Plan": None, "Basic Plan": None})
STUB_PHONE_DISAGREE = stub_phone(**{"Basic Plan": "Alex 555-201-1111"})
STUB_PHONE_AGREE = stub_phone(**{"Unlimited Plan": "Alex (555) 201-1111", "Basic Plan": "Blair"})
STUB_PHONE_CREDITHOLD = stub_phone(**{"Autopay Discount": "Alex 555-201-1111"})

# BL-RENT: rent_replies() with every amount answered wrong.
STUB_RENT_WRONG = {"amounts": {"Rent": "1,540.00", "Water Usage": "83.42"}, "amount_due": "1,623.42"}
