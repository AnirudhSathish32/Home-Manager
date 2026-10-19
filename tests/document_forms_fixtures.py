"""Synthetic transcriptions and stub replies for the document-forms scenarios (specs/document-forms/test-contract.md).

Lines are exactly as the contract prints them. Stubs answer by json_schema name through local_model["by_schema"]
(tests/model_server.py), so a test never depends on the order of model calls. Line numbers are 1-based, as the
transcription's line ids are (line-1, line-2, …).
"""

from home_manager.core.identifiers import mask

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
# P-flat prints one amount per line, so the 401(k) line's own digits are left out of its printed label.
FLAT_LABELS = {"401(k)": "PRE-TAX RETIREMENT"}
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
        lines.append(f"{flat_label(name)} {current}")
    lines += [f"GROSS PAY {P_GROSS[0]}", f"NET PAY {P_NET[0]}", "YEAR TO DATE"]
    for name, _, _, current, ytd in P_LINES[(1 if regular_unlabelled else 0):]:
        lines.append(f"{flat_label(name)} {current if ytd_equal else ytd}")
    lines += [f"GROSS PAY {P_GROSS[0] if ytd_equal else P_GROSS[1]}", f"NET PAY {P_NET[0] if ytd_equal else P_NET[1]}"]
    return lines + list(extra) + P_EXTRAS


def flat_label(name):
    """How P-flat prints a fixture P line's description."""
    return FLAT_LABELS.get(name, name.upper())


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


def p_table(period=("2026-06-15", "2026-06-28"), pay_date="2026-07-03", frequency="BIWEEKLY", regular="Regular 80.00 h @ 31.25", extras=None):
    """P-table: (lines, tables) with a validated vision table headed Description | This period | Year to date. The
    Regular row prints its hours and rate in its description cell (regular: that cell's text)."""
    lines = p_header(period, pay_date, frequency)
    first = len(lines)
    rows = [(regular if name == "Regular" else name, current, ytd) for name, _, _, current, ytd in P_LINES]
    rows += [("Gross pay", *P_GROSS), ("Net pay", *P_NET)]
    lines.append(P_TABLE_HEADING)
    lines += [" | ".join(cells) for cells in rows]
    tables = [{"header_rows": [{"line_index": first, "cells": ["Description", "This period", "Year to date"]}],
               "rows": [{"line_index": first + 1 + index, "cells": list(cells)} for index, cells in enumerate(rows)]}]
    return lines + list(P_EXTRAS if extras is None else extras), tables


# Final-state oracles ----------------------------------------------------------------------------------------------

# The saved transcription keeps the document as printed (FR-30, docs/documents.md): the only tables C-ids skips.
TRANSCRIPTION_STORES = ("parse_runs", "document_passages")


def stored_identifiers(db, identifiers=IDENTIFIERS):
    """(table, column, identifier) for every fixture identifier stored outside the saved transcription (C-ids)."""
    found = []
    tables = [row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")
              if row[0] not in TRANSCRIPTION_STORES and not row[0].startswith("document_passages_fts")]
    for table in tables:
        for column in [row[1] for row in db.execute(f'PRAGMA table_info("{table}")') if row[2].upper() in ("TEXT", "", "ANY", "BLOB")]:
            for identifier in identifiers:
                if db.execute(f'SELECT 1 FROM "{table}" WHERE instr(CAST("{column}" AS TEXT), ?) LIMIT 1', (identifier,)).fetchone():
                    found.append((table, column, identifier))
    return found


def uncited(detail, lines):
    """C-cite: the quotes of a stored detail that aren't in any of its cited lines (compared masked, as stored)."""
    texts = [mask(lines[int(line_id.split("-")[1]) - 1]) for line_id in detail["locator"]["line_ids"]]
    return [quote for quote in detail["locator"]["quotes"] if not any(mask(quote) in text for text in texts)]


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

# Each statement also prints its currency (STATEMENT CURRENCY USD): without one, and with no $ printed, a statement's
# amounts can't be read as any currency and nothing is published (ExtractionService.currency_for).
BANK = ["SYNTH BANK", "EVERYDAY CHECKING ACCOUNT 000123456789", "ROUTING 021000021", "STATEMENT PERIOD 2026-09-01 TO 2026-09-30",
        "STATEMENT CURRENCY USD", "OPENING BALANCE 1,000.00", "DEPOSITS 2,500.00", "WITHDRAWALS 1,200.50", "CLOSING BALANCE 2,299.50",
        "INTEREST EARNED 0.42", "APY 0.50%", "FEES 0.00", "09/03 PAYROLL SYNTH WORKS +2,500.00", "09/05 RENT -1,200.50"]
CARD = ["SYNTH CARD", "ACCOUNT ENDING 4242", "STATEMENT PERIOD 2026-09-01 TO 2026-09-30", "STATEMENT CURRENCY USD", "PREVIOUS BALANCE 500.00",
        "PAYMENTS -500.00", "CREDITS -20.00", "PURCHASES 812.45", "FEES CHARGED 0.00", "INTEREST CHARGED 0.00", "NEW BALANCE 792.45",
        "PURCHASE APR 24.99%", "CASH ADVANCE APR 29.99%", "CREDIT LIMIT 5,000.00", "AVAILABLE CREDIT 4,207.55", "POINTS EARNED 812",
        "09/10 PAYMENT THANK YOU +500.00", "09/12 SYNTH SHOP REFUND +20.00", "09/15 SYNTH SHOP -812.45"]
# SC-27's card statement: the receipt's charge, and another purchase at the same merchant with no receipt.
GIFT_CARD_STATEMENT = ["SYNTH CARD", "ACCOUNT ENDING 4242", "STATEMENT PERIOD 2026-10-01 TO 2026-10-31", "STATEMENT CURRENCY USD",
                       "PREVIOUS BALANCE 0.00", "NEW BALANCE 12.10", "10/05 SYNTH MARKET -3.55", "10/06 SYNTH MARKET -8.55"]


def amount_of(lines, text):
    """The last amount printed on the line holding text, as printed (without its sign)."""
    return lines[number_of(lines, text) - 1].split()[-1].lstrip("+-")


def amount_value(lines, text):
    line = lines[number_of(lines, text) - 1]
    return value(lines, line.split()[-1], line, line.split()[-1])


def statement_rows(lines, year="2026"):
    """Transactions for every 'MM/DD TEXT ±AMOUNT' line: credits are printed with +, debits with -."""
    rows = []
    for number, line in enumerate(lines, 1):
        words = line.split()
        if len(words) >= 3 and len(words[0]) == 5 and words[0][2] == "/" and words[-1][0] in "+-":
            rows.append({"posted_date": f"{year}-{words[0][:2]}-{words[0][3:]}", "transaction_date": None, "description": " ".join(words[1:-1]),
                         "amount": words[-1].lstrip("+-"), "direction": "credit" if words[-1][0] == "+" else "debit", "evidence": at(lines, number)})
    return rows


def statement_period(lines):
    line = next(line for line in lines if line.startswith("STATEMENT PERIOD "))
    start, end = line.split()[2], line.split()[4]
    return value(lines, start, line, start), value(lines, end, line, end)


def bank_replies(lines, **changes):
    """A bank statement read correctly, with every printed detail; changes replace summary fields."""
    start, end = statement_period(lines)
    account = next(line for line in lines if "ACCOUNT" in line)
    summary = {"institution": value(lines, "SYNTH BANK", "SYNTH BANK"), "account_reference": value(lines, "6789", account, account.split()[-1]),
               "period_start": start, "period_end": end, "currency": value(lines, "USD", "STATEMENT CURRENCY USD", "USD"),
               "opening_balance": amount_value(lines, "OPENING BALANCE"), "closing_balance": amount_value(lines, "CLOSING BALANCE"),
               "account_type": value(lines, "checking", account, "EVERYDAY CHECKING") if "CHECKING" in account else MISSING}
    for name, text in (("deposits_total", "DEPOSITS "), ("withdrawals_total", "WITHDRAWALS "), ("interest_earned", "INTEREST EARNED"),
                       ("fees_total", "FEES "), ("apy", "APY ")):
        summary[name] = amount_value(lines, text) if any(line.startswith(text) for line in lines) else MISSING
    classified = {"document_type": "bank_statement", "evidence": cite(lines, "SYNTH BANK"), "issuer": value(lines, "SYNTH BANK", "SYNTH BANK"),
                  "document_date": end}
    return {"Classification": [classified], "BankStatementSummary": [{**summary, **changes}], "Transactions": [{"transactions": statement_rows(lines)}]}


def card_replies(lines, **changes):
    """A card statement read correctly, with every printed detail; changes replace summary fields."""
    start, end = statement_period(lines)
    printed = {name: amount_value(lines, text) if any(line.startswith(text) for line in lines) else MISSING
               for name, text in (("previous_balance", "PREVIOUS BALANCE"), ("payments", "PAYMENTS "), ("credits", "CREDITS "),
                                  ("purchases", "PURCHASES "), ("fees", "FEES CHARGED"), ("interest", "INTEREST CHARGED"),
                                  ("statement_balance", "NEW BALANCE"), ("purchase_apr", "PURCHASE APR"), ("cash_advance_apr", "CASH ADVANCE APR"),
                                  ("credit_limit", "CREDIT LIMIT"), ("available_credit", "AVAILABLE CREDIT"), ("rewards_earned", "POINTS EARNED"))}
    summary = {"issuer": value(lines, "SYNTH CARD", "SYNTH CARD"), "account_reference": value(lines, "4242", "ACCOUNT ENDING 4242", "4242"),
               "period_start": start, "period_end": end, "minimum_payment": MISSING, "due_date": MISSING,
               "currency": value(lines, "USD", "STATEMENT CURRENCY USD", "USD"), **printed}
    classified = {"document_type": "credit_card_statement", "evidence": cite(lines, "SYNTH CARD"), "issuer": value(lines, "SYNTH CARD", "SYNTH CARD"),
                  "document_date": end}
    return {"Classification": [classified], "CreditCardStatementSummary": [{**summary, **changes}], "Transactions": [{"transactions": statement_rows(lines)}]}


# Several documents in one library ------------------------------------------------------------------------------

def library(tmp_path, model):
    """A Manager on tmp_path with the fake vision and reasoning models: each document captured is also recorded."""
    from home_manager.app.manager import Manager
    from home_manager.documents.reasoning import ReasoningConfig
    from home_manager.library.scanner import ScanLimits
    manager = Manager(tmp_path / "control", ScanLimits(stability_seconds=0))
    manager.configure(str(tmp_path / "managed"))
    manager.configure_vision(model["config"])
    manager.configure_reasoning(ReasoningConfig(base_url=model["config"].base_url, model="synthetic-reasoning"))
    manager.configure_household(manager.household.model_copy(update={"auto_identify_items": False}))
    return manager


def record_document(manager, model, name, lines, replies, tables=None):
    """Draw lines into the Inbox as name, capture it (the fake vision model reads lines) and record it with replies
    keyed by schema name. Returns (document, parse run id, extraction run)."""
    from test_receipts import make_receipt
    make_receipt(manager.store.library.inbox / name, lines)
    model["outputs"] = [{"full_text": "\n".join(lines), **({"tables": tables} if tables is not None else {})}]
    model["by_schema"] = replies
    manager.start_inbox()
    manager.future.result(timeout=60)
    doc = next(doc for doc in manager.store.documents()["items"] if doc["relative_path"].replace("\\", "/").rsplit("/", 1)[-1] == name)
    parse_id = manager.receipts.history(doc["id"])[0]["id"]
    run = manager.extractions.get(manager.extractions.history(parse_id)[0]["id"])
    assert run["status"] == "succeeded", run["error"]
    return doc, parse_id, run
