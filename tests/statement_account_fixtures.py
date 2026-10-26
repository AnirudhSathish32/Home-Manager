"""Synthetic PDF fixtures and stubs for the statement-accounts contract (specs/statement-accounts/test-contract.md "Fixtures").

Builders return `make_pdf` pages (positioned-item dicts). Expected values are the contract's tables, written out by hand
below, never computed from the code under test. Every native page prints a words-only footer of at least 40 characters, so the
reader never sends it to the vision model.

The lines the contract lists above a table are printed in an order whose last line names no balance (plan P17), because FR-27
reads the visual row directly above a heading as its title, and a title that names a balance makes a balance table. No line is
added or removed. Only D's `DAILY ENDING BALANCE` stays directly above its table.

The stubs (`Transactions` and the summaries) take the reading's lines as `(line id, text)` pairs from `reading_lines`, and cite
them as the Record path does.
"""

from home_manager.documents.layout_context import evidence_lines
from pdf_import_fixtures import HEADING3, footer, table_items

# --- Layout conventions --------------------------------------------------------------------------------------------

COLUMNS4 = (40, 110, 380, 470)  # Date | Description | Amount | Balance
COLUMNS5 = (40, 110, 330, 400, 470)  # Date | Description | Withdrawals | Deposits | Balance
COLUMNS3 = (40, 110, 380)  # Date | Description | Amount
HEADING4 = ("Date", "Description", "Amount", "Balance")
HEADING5 = ("Date", "Description", "Withdrawals", "Deposits", "Balance")
TOP = 700  # The heading is on row 0 at y = 700; each later row is 20 pt lower.
MISSING = {"value": None, "status": "missing", "evidence": []}

# --- Expected values, hand-written from the contract ---------------------------------------------------------------

# S: (id, date, description, amount, balance, expected amount_minor). All dates are 2026-09-xx.
S_ROWS = [
    ("s1", "09/18", "SYNTH ACCTVERIFY PPD ID 1234567890", "0.36", "", 36),
    ("s2", "09/18", "SYNTH ACCTVERIFY PPD ID 1234567890", "0.02", "0.38", 2),
    ("s3", "09/18", "SYNTH ACCTVERIFY WEB ID 1234567890", "-0.38", "0.00", -38),
    ("s4", "09/20", "PAYROLL SYNTH WORKS", "1,500.00", "1,500.00", 150000),
    ("s5", "09/25", "TRANSFER TO CHECKING", "-500.00", "1,000.00", -50000),
]
S_AMOUNTS = [row[5] for row in S_ROWS]
S_POSTED = ["2026-09-18", "2026-09-18", "2026-09-18", "2026-09-20", "2026-09-25"]
S_DESCRIPTIONS = [row[2] for row in S_ROWS]
S_ABOVE = ("SYNTH BANK", "SYNTH SAVINGS", "Account Number 000009000123456", "Beginning Balance 0.00", "Ending Balance 1,000.00",
           "Statement period 09/01/2026 through 09/30/2026")  # The contract's lines, with the period last (P17).
S2_ABOVE = (*S_ABOVE[:2], "Account Number 000009000127890", *S_ABOVE[3:])
T1 = ("t1", "09/22", "SYNTH LONG DESCRIPTION", "12.34", "", 1234)  # T: the row below s5; recorded as 2026-09-22.
T1_POSTED = "2026-09-22"
DAILY = (("09/18", "0.00"), ("09/20", "1,500.00"), ("09/25", "1,000.00"))

# W: (id, date, description, withdrawal, deposit, balance, expected amount_minor), 08/2026; opening 1,000.00, closing 2,450.00.
W_ROWS = [
    ("w1", "08/03/2026", "RENT", "1,200.00", "", "-200.00", -120000),
    ("w2", "08/15/2026", "PAYROLL", "", "2,500.00", "2,300.00", 250000),
    ("w3", "08/20/2026", "REFUND SHOP", "", "150.00", "2,450.00", 15000),
]
W_AMOUNTS = [row[6] for row in W_ROWS]
W_ABOVE = ("SYNTH BANK", "SYNTH CHECKING", "Account Number 000000004821", "Beginning Balance 1,000.00", "Ending Balance 2,450.00",
           "Statement period {start} through {end}")

# C: (id, date, description, amount, expected posted date, expected amount_minor). Charges are positive.
C_ROWS = [
    ("c1", "12/20", "BOOKSTORE", "19.99", "2025-12-20", -1999),
    ("c2", "01/03", "PAYMENT THANK YOU", "-250.00", "2026-01-03", 25000),
    ("c3", "01/05", "GAS STATION", "38.20", "2026-01-05", -3820),
]
C_ABOVE = ("SYNTH CARD", "Card number XXXX7700", "Previous Balance 300.00", "New Balance 108.19", "Statement period 12/15/2025 to 01/14/2026")
C0_ABOVE = ("SYNTH CARD", "Previous Balance 300.00", "New Balance 108.19", "Card number XXXX7700")

# X: the rejection rows. (id, date, description, amount word, x of the amount word, what the contract expects.)
X_ABOVE = ("SYNTH BANK", "SYNTH CHECKING", "All amounts in USD", "Statement period 09/01/2026 through 09/30/2026")  # USD: x6's EUR blocks the home currency
X_REJECTED = {"x2": "The amount doesn't fit a column.",
              "x3": "More than one amount sits in the Amount column.",
              "x4": 'The date "02/30/2026" is not a real date.',
              "x5": None,  # The reader's own wording for an unparseable amount; asserted by the test against analyze.
              "x6": None}  # Currency mismatch: likewise.

# Q: the same line in a CHECKS PAID table (page 1) and the main table (page 2).
Q_CHECK = ("09/10/2026", "CHECK 1001", "-75.00")
Q_MAIN = (("09/05/2026", "COFFEE SHOP", "-4.50"), Q_CHECK, ("09/15/2026", "PAYROLL SYNTH WORKS", "1,500.00"))

# T-edge: t1's `12.34` moved left so that its box starts left of the Description/Amount midpoint by less than 20% of its width.
T_AMOUNT_X = 272
T_EDGE_X = 268


# --- Page builders -------------------------------------------------------------------------------------------------

def lines_above(lines, top=780, step=12):
    """The lines above a table, from y = 780, 12 pt apart (the heading is at 700, so the last of six is at 720)."""
    return [(40, top - step * index, text) for index, text in enumerate(lines)]


def words_footer(name, y):
    # The "$" lets Record read the amounts as the home currency (ExtractionService.currency_for), as the summary stubs leave the currency missing.
    return footer(f"{name} statement page one of one, amounts shown in $, kept for your records", y)


def page(above, rows, columns, heading, name, top=TOP, extra=(), foot=True, **settings):
    """One page: lines above, the heading and rows from y = top, any extra items, and the words-only footer below the rows."""
    items = lines_above(above) + table_items([heading, *rows], top, columns) + list(extra)
    if foot:
        items.append(words_footer(name, top - 20 * (len(rows) + 1)))
    return {"items": items, **settings}


def s_cells(rows=S_ROWS):
    return [(row[1], row[2], row[3], row[4]) for row in rows]


def flag_items():
    """S-flag: two different words drawn at one position (`overlapping_text`) and a title word drawn rotated through the text
    matrix (`unsupported_text_rotation`), below the footer so no visual row of the table is touched."""
    return [(300, 400, "STAMPED"), (300, 400, "OVERLAID"), (590, 300, "ROTATED", 10, (0, 1, -1, 0))]


def s_pages(above=S_ABOVE, flagged=False, extra_rows=(), extra=(), daily=False):
    """S: the user's 1-page savings statement. `flagged` makes S-flag; `extra_rows` are printed as given cells (date, description,
    amount, balance) below s5; `daily` adds D's DAILY ENDING BALANCE table below the footer."""
    rows = s_cells() + list(extra_rows)
    items = list(extra) + (flag_items() if flagged else [])
    if daily:
        items += table_items([HEADING4[:1] + ("Amount",), *DAILY], 480, (40, 380))
        items.append((40, 520, "DAILY ENDING BALANCE"))
        items.append(words_footer("SYNTH BANK daily", 400))
    return [page(above, rows, COLUMNS4, HEADING4, "SYNTH BANK", extra=items)]


def s_flag_pages():
    return s_pages(flagged=True)


def s2_pages():
    """S2: S printing account number 000009000127890, so the last four is 7890."""
    return s_pages(above=S2_ABOVE)


def d_pages(flagged=False):
    return s_pages(flagged=flagged, daily=True)


def t_items(amount_x=T_AMOUNT_X):
    """t1's words placed one by one at 10 pt: `SYNTH` at 110, `LONG` at 155, `DESCRIPTION` at 194 and `12.34` at `amount_x`."""
    y = TOP - 20 * 6
    return [(40, y, T1[1]), (110, y, "SYNTH"), (155, y, "LONG"), (194, y, "DESCRIPTION"), (amount_x, y, T1[3])]


def t_pages(edge=False):
    """T: S-flag plus t1 below s5. `edge` is T-edge (beyond the contract, plan G5): t1's amount starts left of the midpoint."""
    rows = s_cells()
    items = table_items([HEADING4, *rows], TOP, COLUMNS4) + t_items(T_EDGE_X if edge else T_AMOUNT_X)
    items = lines_above(S_ABOVE) + items + flag_items() + [words_footer("SYNTH BANK", TOP - 20 * 8)]
    return [{"items": items}]


def w_pages(shift=0, above=W_ABOVE):
    """W: a bank statement with Withdrawals | Deposits | Balance. W′ is W with its dates moved one month, and W″ two (SC-10)."""
    month = 8 + shift
    cells = [(row[1].replace("08/", f"{month:02d}/"), row[2], row[3], row[4], row[5]) for row in W_ROWS]
    period = dict(start=f"{month:02d}/01/2026", end=f"{month:02d}/{31 if month in (8, 10) else 30}/2026")
    lines = [text.format(**period) for text in above]
    return [page(lines, cells, COLUMNS5, HEADING5, "SYNTH BANK")]


def c_pages(above=C_ABOVE):
    return [page(above, [(row[1], row[2], row[3]) for row in C_ROWS], COLUMNS3, HEADING3, "SYNTH CARD")]


def c0_pages():
    """C0: C with no statement period printed."""
    return c_pages(C0_ABOVE)


X_DATA = (("09/02/2026", "GOOD", "10.00"), ("09/03/2026", "STRADDLE", ""), ("09/04/2026", "X3", "5.00"), ("02/30/2026", "BADDATE", "1.00"),
          ("09/05/2026", "BADAMT", "1.2.3"), ("09/06/2026", "EURO", "4.00 EUR"))


def x_pages():
    """X: five rejections after a good row, on a Date | Description | Amount | Balance page. x2's amount straddles the
    Amount/Balance midpoint, and x3 prints `REF 55.55` in the Amount span beside `5.00`."""
    rows = [(date, description, amount, "") for date, description, amount in X_DATA]
    extra = [(425, TOP - 20 * 2, "100.00"), (330, TOP - 20 * 3, "REF"), (358, TOP - 20 * 3, "55.55")]
    rows[2] = (rows[2][0], rows[2][1], "", "")
    extra.append((405, TOP - 20 * 3, "5.00"))
    return [page(X_ABOVE, rows, COLUMNS4, HEADING4, "SYNTH BANK", extra=extra)]


def q_pages():
    """Q: page 1 is a CHECKS PAID table, page 2 the main transactions table, which holds the same line."""
    checks = lines_above(("SYNTH BANK", "Statement period 09/01/2026 through 09/30/2026", "CHECKS PAID"), step=12)
    checks = [(x, y - 24, text) for x, y, text in checks]  # So CHECKS PAID is directly above the heading, as a table's title.
    first = {"items": checks + table_items([HEADING3, Q_CHECK], TOP, COLUMNS3) + [words_footer("SYNTH BANK checks", TOP - 60)]}
    second = page(("SYNTH BANK", "Statement period 09/01/2026 through 09/30/2026"), [(*row, "") for row in Q_MAIN], COLUMNS4, HEADING4, "SYNTH BANK")
    return [first, second]


def daily_page():
    """A page holding only D's DAILY ENDING BALANCE table (Date | Amount) under its title (SC-21's second variant)."""
    items = [(40, 724, "DAILY ENDING BALANCE"), *table_items([HEADING4[:1] + ("Amount",), *DAILY], TOP, (40, 380))]
    return {"items": items + [words_footer("SYNTH BANK daily", TOP - 20 * 4)]}


def d2_pages():
    """S's page, then the daily balance table by itself on page 2."""
    return [s_pages()[0], daily_page()]


def m_pages():
    """M: S's page, then a scanned page (read once with the vision stub)."""
    return [s_pages()[0], None]


# --- Stubs ---------------------------------------------------------------------------------------------------------

def reading_lines(result):
    """The lines Record's model is shown for the reading, as (line id, text) pairs: a native page's rows (cells joined by ` | `), else
    the page's lines (`documents.layout_context.evidence_lines`). The stubs cite these."""
    return [(line.id, line.text) for line in evidence_lines(result)]


def spaced(text):
    return " ".join(text.replace("|", " ").split())


def find(lines, text):
    """The (line id, text) of the line that is exactly text, else the one line that contains it (cell separators ignored)."""
    exact = [pair for pair in lines if spaced(pair[1]) == text]
    found = exact or [pair for pair in lines if text in spaced(pair[1])]
    assert len(found) == 1, f"{text!r} is on {len(found)} lines"
    return found[0]


def cited(lines, text, quote=None):
    line_id, printed = find(lines, text)
    return [{"line_id": line_id, "quote": quote if quote is not None else printed}]


def proposed(lines, text, line, quote=None):
    return {"value": text, "status": "proposed", "evidence": cited(lines, line, quote or text)}


def stub_row(lines, date, description, amount, direction, line):
    return {"posted_date": date, "transaction_date": None, "description": description, "amount": amount, "direction": direction,
            "evidence": cited(lines, line)}


def s_bad_rows(lines, only=None):
    """S-bad, the wrong `Transactions` stub used wherever S is recorded: s1 as 0.36 credit; s2 as `0.38` credit (its balance); s3
    as 0.38 debit; s4; s5; and an extra row `09/18 SYNTH ACCTVERIFY 0.38 credit` citing s2's line. `only` drops rows by id (the
    stub with s4 removed is `only=("s1", "s2", "s3", "s5", "extra")`). T's t1 is never listed."""
    s2_line = "SYNTH ACCTVERIFY PPD ID 1234567890 0.02"
    rows = {
        "s1": stub_row(lines, "2026-09-18", S_DESCRIPTIONS[0], "0.36", "credit", "SYNTH ACCTVERIFY PPD ID 1234567890 0.36"),
        "s2": stub_row(lines, "2026-09-18", S_DESCRIPTIONS[1], "0.38", "credit", s2_line),
        "s3": stub_row(lines, "2026-09-18", S_DESCRIPTIONS[2], "0.38", "debit", "SYNTH ACCTVERIFY WEB ID 1234567890 -0.38"),
        "s4": stub_row(lines, "2026-09-20", S_DESCRIPTIONS[3], "1,500.00", "credit", "PAYROLL SYNTH WORKS"),
        "s5": stub_row(lines, "2026-09-25", S_DESCRIPTIONS[4], "500.00", "debit", "TRANSFER TO CHECKING"),
        "extra": stub_row(lines, "2026-09-18", "SYNTH ACCTVERIFY", "0.38", "credit", s2_line),
    }
    return [row for key, row in rows.items() if only is None or key in only]


def printed(iso):
    """An ISO date as the statements print it (MM/DD/YYYY), which is what the model's citation quotes."""
    year, month, day = iso.split("-")
    return f"{month}/{day}/{year}"


def line_with(lines, text):
    """The first line that contains text (a statement printing its period on several pages has more than one)."""
    return next(pair for pair in lines if text in spaced(pair[1]))


def first_proposed(lines, value, line, quote=None):
    line_id, printed_text = line_with(lines, line)
    return {"value": value, "status": "proposed", "evidence": [{"line_id": line_id, "quote": quote or value}]}


def fill(kind, summary):
    """Every field of the summary schema: the given ones, the rest missing."""
    from home_manager.documents.extraction import HEADER_MODELS
    return {name: summary.get(name, MISSING) for name in HEADER_MODELS[kind].model_fields}


def bank_summary(lines, reference, account_line, start, end, opening, closing, account_type=("savings", "SYNTH SAVINGS")):
    """S's `BankStatementSummary` reply: institution SYNTH BANK, account_type `savings` citing SYNTH SAVINGS, the account
    reference, the period, opening and closing. The currency is missing (USD from the setting, as today); the rest is missing.
    A reference, opening or closing of None is not printed on the statement (X), and so missing."""
    found = {"institution": first_proposed(lines, "SYNTH BANK", "SYNTH BANK"),
             "period_start": first_proposed(lines, start, "Statement period", printed(start)), "period_end": first_proposed(lines, end, "Statement period", printed(end))}
    if account_type:
        found["account_type"] = proposed(lines, account_type[0], account_type[1], account_type[1])
    if reference:
        found["account_reference"] = proposed(lines, reference, account_line)
    if opening:
        found["opening_balance"], found["closing_balance"] = proposed(lines, opening, "Beginning Balance"), proposed(lines, closing, "Ending Balance")
    return fill("bank_statement", found)


def s_summary(lines):
    """S's stub: account_reference 3456, the period 2026-09-01 to 2026-09-30, opening 0.00 and closing 1,000.00."""
    return bank_summary(lines, "3456", "Account Number 000009000123456", "2026-09-01", "2026-09-30", "0.00", "1,000.00")


def s2_summary(lines):
    """S2's stub: S's with account_reference 7890, cited from S2's account number line."""
    return bank_summary(lines, "7890", "Account Number 000009000127890", "2026-09-01", "2026-09-30", "0.00", "1,000.00")


def w_summary(lines, month=8):
    """W's stub: account 4821, checking, the period of the month, opening 1,000.00 and closing 2,450.00."""
    last = 31 if month in (8, 10) else 30
    return bank_summary(lines, "4821", "Account Number 000000004821", f"2026-{month:02d}-01", f"2026-{month:02d}-{last}", "1,000.00", "2,450.00",
                        account_type=("checking", "SYNTH CHECKING"))


def c_summary(lines, period=True):
    """C's `CreditCardStatementSummary` reply (C0 with `period=False`): SYNTH CARD …7700, previous 300.00 and new balance 108.19."""
    found = {"issuer": proposed(lines, "SYNTH CARD", "SYNTH CARD"), "account_reference": proposed(lines, "7700", "Card number XXXX7700"),
             "previous_balance": proposed(lines, "300.00", "Previous Balance"), "statement_balance": proposed(lines, "108.19", "New Balance")}
    if period:
        found["period_start"] = first_proposed(lines, "2025-12-15", "Statement period", "12/15/2025")
        found["period_end"] = first_proposed(lines, "2026-01-14", "Statement period", "01/14/2026")
    return fill("credit_card_statement", found)


def classified(lines, kind, end=None):
    """The `Classification` reply for a statement: SYNTH BANK (or SYNTH CARD) as the issuer, the period's end as the document date."""
    issuer = "SYNTH CARD" if kind == "credit_card_statement" else "SYNTH BANK"
    return {"document_type": kind, "evidence": first_proposed(lines, issuer, issuer)["evidence"], "issuer": first_proposed(lines, issuer, issuer),
            "document_date": first_proposed(lines, end, "Statement period", printed(end)) if end else MISSING}


def w_rows(lines):
    """W's `Transactions` stub: every amount is its Balance cell (SC-14), with the direction the columns give."""
    found = []
    for row in W_ROWS:
        line = f"{row[1]} {row[2]}"
        found.append(stub_row(lines, printed_to_iso(row[1]), row[2], row[5].lstrip("-"), "debit" if row[3] else "credit", line))
    return found


def printed_to_iso(text):
    month, day, year = text.split("/")
    return f"{year}-{month}-{day}"


def x_summary(lines):
    """X's stub: SYNTH BANK checking, the period 09/2026, the currency from its printed line, no account number or balances."""
    return {**bank_summary(lines, None, None, "2026-09-01", "2026-09-30", None, None, account_type=("checking", "SYNTH CHECKING")),
            "currency": first_proposed(lines, "USD", "All amounts in USD")}


def q_summary(lines):
    """Q's stub: SYNTH BANK, the period 09/2026, and nothing else printed."""
    return bank_summary(lines, None, None, "2026-09-01", "2026-09-30", None, None, account_type=None)


# --- Shared checks ---------------------------------------------------------------------------------------------------------

def orphans(db, account_id, statements=(), transactions=()):
    """C-orphans(account, statements, transactions): the rows still holding the account or an id in either set. Every table with a
    column that refers to accounts, statements or transactions is read from sqlite_schema and its foreign keys at call time, so a new table
    can't be missed. `transactions.replaced_by` is checked too (it names a transaction)."""
    found = []
    typed = {"statement": list(statements), "transaction": list(transactions)}
    for (table,) in db.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall():
        columns = {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}
        wanted = [("account_id", [account_id]), ("ledger_account_id", [account_id]), ("statement_id", typed["statement"]),
                  ("transaction_id", typed["transaction"]), ("from_transaction_id", typed["transaction"]), ("to_transaction_id", typed["transaction"]),
                  ("replaced_by", typed["transaction"])]
        if table == "accounts":
            wanted.append(("id", [account_id]))
        # An `account_id` counts only where its foreign key targets accounts: holdings, investment_events and others name an
        # investment account by the same column name, and their ids are not this account's.
        targets_accounts = {row[3] for row in db.execute(f'PRAGMA foreign_key_list("{table}")') if row[2] == "accounts"}
        for column, ids in wanted:
            if column in ("account_id", "ledger_account_id") and column not in targets_accounts:
                continue
            if column in columns and ids:
                marks = ",".join("?" * len(ids))
                found += [(table, column, row[0]) for row in db.execute(f'SELECT rowid FROM "{table}" WHERE "{column}" IN ({marks})', ids)]
        if {"record_type", "record_id"} <= columns:
            for kind in ("statement", "transaction"):
                if typed[kind]:
                    marks = ",".join("?" * len(typed[kind]))
                    found += [(table, f"{kind} record_id", row[0]) for row in db.execute(
                        f'SELECT rowid FROM "{table}" WHERE record_type=? AND record_id IN ({marks})', [kind, *typed[kind]])]
    return found
