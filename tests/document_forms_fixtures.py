"""Synthetic transcriptions and stub replies for the document-forms scenarios (specs/document-forms/test-contract.md).

Lines are exactly as the contract prints them. Stubs answer by json_schema name through local_model["by_schema"]
(tests/model_server.py), so a test never depends on the order of model calls. Line numbers are 1-based, as the
transcription's line ids are (line-1, line-2, …).
"""

MISSING = {"value": None, "status": "missing", "evidence": []}
AMBIGUOUS = {"value": None, "status": "ambiguous", "evidence": []}

# The identifiers the fixtures print (C-ids): none may be stored outside the saved transcription.
IDENTIFIERS = ("445566", "021000021", "000123456789", "6006491234565555", "XXX-XX-1234")


def number_of(lines, text):
    """The 1-based line number of the line that is exactly text, or that contains it when no line is exactly it."""
    for index, line in enumerate(lines, 1):
        if line == text:
            return index
    matches = [index for index, line in enumerate(lines, 1) if text in line]
    assert len(matches) == 1, f"{text!r} is on {len(matches)} lines"
    return matches[0]


def cite(lines, text, quote=None):
    """Evidence for the line holding text, quoting quote (default: the whole line)."""
    number = number_of(lines, text)
    return [{"line_id": f"line-{number}", "quote": quote if quote is not None else lines[number - 1]}]


def value(lines, text, line, quote=None):
    """A proposed value citing the line that holds line."""
    return {"value": text, "status": "proposed", "evidence": cite(lines, line, quote)}


def replies(**by_schema):
    """{schema name: [replies]} for local_model["by_schema"]; a single reply may be given without a list."""
    return {name: list(reply) if isinstance(reply, list) else [reply] for name, reply in by_schema.items()}


def classification(lines, kind, issuer, issuer_line, date, date_line, **extra):
    return {"document_type": kind, "evidence": cite(lines, issuer_line), "issuer": value(lines, issuer, issuer_line),
            "document_date": value(lines, date, date_line), **extra}


def description(category=None, items=0):
    return {"description": None, "category": category, "recurrence": None, "item_categories": [category] * items}


NO_REWARDS = {"rewards": []}


# Receipts ------------------------------------------------------------------------------------------------------

FUEL = ["SYNTH FUEL #12", "2026-10-01", "PUMP 17", "REG UNL 10.312 GAL @ 3.459", "FUEL SALE 35.67", "COFFEE 2.19", "TOTAL 37.86",
        "VISA ****4242"]
DINING = ["SYNTH BISTRO", "2026-10-02", "SERVER: SAM TABLE 9 GUESTS 4", "PASTA 30.00", "SALAD 20.00", "SUBTOTAL 50.00", "TAX 4.00",
          "GRATUITY 18% INCLUDED 9.00", "TIP ______", "TOTAL 63.00"]
GROCERY = ["SYNTH MARKET", "2026-10-03", "MILK 3.49", "BANANAS 2.31 lb @ 0.59/lb 1.36", "2x CHIPS @ 2.00 4.00", "BOTTLE DEPOSIT 0.10",
           "BAG FEE 0.10", "MEMBER SAVINGS -0.50", "SUBTOTAL 8.55", "TAX 0.00", "TOTAL 8.55", "GIFT CARD 6006491234565555 -5.00",
           "EBT SNAP 3.55"]
GIFT_RECEIPT = ["SYNTH MARKET", "2026-10-03", "GROCERIES 8.55", "SUBTOTAL 8.55", "TAX 0.00", "TOTAL 8.55", "GIFT CARD ****5555 -5.00",
                "VISA ****4242 3.55"]


def fuel(sale="35.67", total="37.86", volume="10.312 GAL"):
    """SC-01 (SC-02: sale 36.67, total 38.86; 1b: volume 10.312 L)."""
    return [*FUEL[:3], f"REG UNL {volume} @ 3.459", f"FUEL SALE {sale}", FUEL[5], f"TOTAL {total}", FUEL[7]]


# Pay stubs (fixture P) -----------------------------------------------------------------------------------------

# Fixture P: (description, group, category, this period, year to date). Its year to date is exactly 13 periods.
P_LINES = [("Regular", "earnings", "regular_pay", "2,500.00", "32,500.00"),
           ("Federal income tax", "tax", "federal_income_tax", "250.00", "3,250.00"),
           ("Social Security", "tax", "social_security", "155.00", "2,015.00"),
           ("Medicare", "tax", "medicare", "36.25", "471.25"),
           ("GA state tax", "tax", "state_income_tax", "96.41", "1,253.33"),
           ("401(k)", "pre_tax", "retirement_pretax", "50.00", "650.00")]
P_GROSS, P_NET = ("2,500.00", "32,500.00"), ("1,912.34", "24,860.42")
P_TAXES, P_DEDUCTIONS = "537.66", "50.00"
P_EXTRAS = ["PTO BALANCE 56.00 HRS", "DIRECT DEPOSIT CHECKING ****1234 1,500.00", "SAVINGS ****9876 412.34", "SSN XXX-XX-1234",
            "EMPLOYEE ID 445566"]


def p_header(period=("2026-06-15", "2026-06-28"), pay_date="2026-07-03", frequency="BIWEEKLY"):
    lines = ["SYNTH WORKS", "EARNINGS STATEMENT"]
    if pay_date:
        lines.append(f"PAY DATE {pay_date}")
    if period:
        lines.append(f"PAY PERIOD {period[0]} TO {period[1]}")
    if frequency:
        lines.append(f"PAY FREQUENCY {frequency}")
    return lines + ["CURRENCY USD"]


def p_flat(period=("2026-06-15", "2026-06-28"), pay_date="2026-07-03", frequency="BIWEEKLY", ytd_equal=False,
           regular_unlabelled=False, extra=()):
    """P-flat: a THIS PERIOD section, then a YEAR TO DATE section, one amount per line. ytd_equal: every year-to-date
    amount equals this period's (a first paycheck of the year). regular_unlabelled (20-b): the Regular line's two
    amounts on their own unlabelled lines, before the sections."""
    lines = p_header(period, pay_date, frequency)
    if regular_unlabelled:
        lines += ["REGULAR", P_LINES[0][3], P_LINES[0][4]]
    lines.append("THIS PERIOD")
    for name, _, _, current, _ in P_LINES[(1 if regular_unlabelled else 0):]:
        lines.append(f"{name.upper()} {current}")
    lines += [f"GROSS PAY {P_GROSS[0]}", f"NET PAY {P_NET[0]}", "YEAR TO DATE"]
    for name, _, _, current, ytd in P_LINES[(1 if regular_unlabelled else 0):]:
        lines.append(f"{name.upper()} {current if ytd_equal else ytd}")
    lines += [f"GROSS PAY {P_GROSS[0] if ytd_equal else P_GROSS[1]}", f"NET PAY {P_NET[0] if ytd_equal else P_NET[1]}"]
    return lines + list(extra) + P_EXTRAS


def section_line(lines, section, text):
    """The 1-based number of the first line starting with text after the section heading line (THIS PERIOD or YEAR TO DATE)."""
    start = lines.index(section)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith(text):
            return index + 1
    raise AssertionError(f"{text!r} not under {section}")


def at(lines, number, quote=None):
    """Evidence for line number (1-based)."""
    return [{"line_id": f"line-{number}", "quote": quote if quote is not None else lines[number - 1]}]


P_TABLE_HEADING = "Description | This period | Year to date"


def p_table(period=("2026-06-15", "2026-06-28"), pay_date="2026-07-03", frequency="BIWEEKLY"):
    """P-table: (lines, tables) with a validated vision table headed Description | This period | Year to date. The
    Regular row prints its hours and rate in its description cell."""
    lines = p_header(period, pay_date, frequency)
    first = len(lines)
    rows = [("Regular 80.00 h @ 31.25" if name == "Regular" else name, current, ytd) for name, _, _, current, ytd in P_LINES]
    rows += [("Gross pay", *P_GROSS), ("Net pay", *P_NET)]
    lines.append(P_TABLE_HEADING)
    lines += [" | ".join(cells) for cells in rows]
    tables = [{"header_rows": [{"line_index": first, "cells": ["Description", "This period", "Year to date"]}],
               "rows": [{"line_index": first + 1 + index, "cells": list(cells)} for index, cells in enumerate(rows)]}]
    return lines + P_EXTRAS, tables


def paystub_summary(lines, **changes):
    """Today's PaystubSummary fields, every one missing unless changed; employer, pay date and currency cited when printed."""
    summary = {name: MISSING for name in ("payer_or_employer", "pay_date", "period_start", "period_end", "pay_frequency", "work_state",
                                          "gross_pay", "gross_pay_ytd", "net_pay", "net_pay_ytd", "taxes", "deductions", "currency")}
    summary["payer_or_employer"] = value(lines, "SYNTH WORKS", "SYNTH WORKS")
    summary["currency"] = value(lines, "USD", "CURRENCY USD", "USD")
    for line in lines:
        if line.startswith("PAY DATE "):
            summary["pay_date"] = value(lines, line.split()[-1], line, line.split()[-1])
        elif line.startswith("PAY PERIOD "):
            words = line.split()
            summary["period_start"] = value(lines, words[2], line, words[2])
            summary["period_end"] = value(lines, words[4], line, words[4])
        elif line.startswith("PAY FREQUENCY "):
            summary["pay_frequency"] = value(lines, line.split()[-1], line, line.split()[-1])
    return {**summary, **changes}


def paystub_classification(lines):
    dated = next((line for line in lines if line.startswith("PAY DATE ")), None)
    return {"document_type": "paystub", "evidence": cite(lines, "EARNINGS STATEMENT"), "issuer": value(lines, "SYNTH WORKS", "SYNTH WORKS"),
            "document_date": value(lines, dated.split()[-1], dated, dated.split()[-1]) if dated else MISSING}


# Statements ----------------------------------------------------------------------------------------------------

BANK = ["SYNTH BANK", "EVERYDAY CHECKING ACCOUNT 000123456789", "ROUTING 021000021", "STATEMENT PERIOD 2026-09-01 TO 2026-09-30",
        "OPENING BALANCE 1,000.00", "DEPOSITS 2,500.00", "WITHDRAWALS 1,200.50", "CLOSING BALANCE 2,299.50", "INTEREST EARNED 0.42",
        "APY 0.50%", "FEES 0.00", "09/03 PAYROLL SYNTH WORKS +2,500.00", "09/05 RENT -1,200.50"]
CARD = ["SYNTH CARD", "ACCOUNT ENDING 4242", "STATEMENT PERIOD 2026-09-01 TO 2026-09-30", "PREVIOUS BALANCE 500.00", "PAYMENTS -500.00",
        "CREDITS -20.00", "PURCHASES 812.45", "FEES CHARGED 0.00", "INTEREST CHARGED 0.00", "NEW BALANCE 792.45", "PURCHASE APR 24.99%",
        "CASH ADVANCE APR 29.99%", "CREDIT LIMIT 5,000.00", "AVAILABLE CREDIT 4,207.55", "POINTS EARNED 812",
        "09/10 PAYMENT THANK YOU +500.00", "09/12 SYNTH SHOP REFUND +20.00", "09/15 SYNTH SHOP -812.45"]
# SC-27's card statement: the receipt's charge, and another purchase at the same merchant with no receipt.
GIFT_CARD_STATEMENT = ["SYNTH CARD", "ACCOUNT ENDING 4242", "STATEMENT PERIOD 2026-10-01 TO 2026-10-31", "PREVIOUS BALANCE 0.00",
                       "NEW BALANCE 12.10", "10/05 SYNTH MARKET -3.55", "10/06 SYNTH MARKET -8.55"]
