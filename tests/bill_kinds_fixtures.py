"""Synthetic rent bills and stub replies for the bill-kinds scenarios (specs/bill-kinds/test-contract.md "Fixtures").

Lines are exactly as the contract prints them; line numbers are 1-based, as the transcription's line ids are (line-1, …).
Replies are keyed by json_schema name (local_model["by_schema"], tests/model_server.py), so no test fixes the call order.
"""

from test_extraction import MISSING, cite, value

RENT = ["SYNTH PROPERTY MANAGEMENT",
        "Resident Account ****4821",
        "Rent and Leasing Charges Due 10/01/2026",
        "Rent 10/01/2026 - 10/31/2026 $1,450.00",
        "Water Usage 08/15/2026 - 09/14/2026 3,200 GAL $38.42",
        "Due Date ........................................................... 10/01/2026",
        "Amount Due......................................................... $1,488.42"]
RENT_LINE, WATER_LINE, DUE_LINE, AMOUNT_LINE = 4, 5, 6, 7


def rent_plain():
    """RENT-PLAIN: line 5 is a bare water line."""
    return [*RENT[:4], "Water $38.42", *RENT[5:]]


def rent_month():
    """RENT-MONTH: the rent line prints only its month."""
    return with_line(RENT, RENT_LINE, "Rent for October 2026 $1,450.00")


def rent_noyear():
    """RENT-NOYEAR: the rent and water lines print their periods without a year."""
    return with_line(with_line(RENT, RENT_LINE, "Rent 10/1 - 10/31 $1,450.00"), WATER_LINE, "Water Usage 5/15 - 6/14 3,200 GAL $38.42")


def rent_carried():
    """RENT-CARRIED (a): a previous balance, a payment and the new charges printed before the due date line."""
    return [*RENT[:5], "Previous Balance $100.00", "Payment Received 09/03/2026 -$100.00", "New Charges $1,488.42", *RENT[5:]]


def with_line(lines, number, text):
    """lines with line number replaced by text."""
    return [*lines[:number - 1], text, *lines[number:]]


def rent_row(description="Rent", amount="1,450.00", line=RENT_LINE, lines=RENT, rent_type="rent", category="housing",
             period=("2026-10-01", "2026-10-31"), usage=None, evidence=None):
    return {"description": description, "amount": amount, "quantity": None, "unit_price": None, "category": category,
            "rent_type": rent_type, "line_holder": None, "period_start": period[0] if period else None,
            "period_end": period[1] if period else None, "usage": usage,
            "evidence": evidence if evidence is not None else cite(line, lines[line - 1])}


def water_row(lines=RENT, **changes):
    fields = {"description": "Water Usage", "amount": "38.42", "line": WATER_LINE, "lines": lines, "rent_type": "utility",
              "category": "utilities", "period": ("2026-08-15", "2026-09-14"), "usage": "3,200 GAL"}
    return rent_row(**{**fields, **changes})


def general_rows(lines=RENT):
    """The same two charges read with the general form (BillLines)."""
    return [{"description": "Rent", "amount": "1,450.00", "quantity": None, "unit_price": None, "category": "housing", "line_kind": "service",
             "line_holder": None, "evidence": cite(RENT_LINE, lines[RENT_LINE - 1])},
            {"description": "Water Usage", "amount": "38.42", "quantity": None, "unit_price": None, "category": "utilities", "line_kind": "usage",
             "line_holder": None, "evidence": cite(WATER_LINE, lines[WATER_LINE - 1])}]


def bill_header(lines=RENT, **changes):
    """Every BillSummary field (the general form), answered correctly for RENT: Issued missing, the period the rent line's."""
    header = {"provider": value("SYNTH PROPERTY MANAGEMENT", 1), "account_reference": value("4821", 2, "4821"), "issue_date": MISSING,
              "due_date": value("2026-10-01", DUE_LINE, lines[DUE_LINE - 1]),
              "period_start": value("2026-10-01", RENT_LINE, "10/01/2026"), "period_end": value("2026-10-31", RENT_LINE, "10/31/2026"),
              "amount_due": value("1,488.42", AMOUNT_LINE, lines[AMOUNT_LINE - 1]), "new_charges": MISSING, "currency": MISSING}
    return {**header, **changes}


def classified(lines=RENT, kind="rent", kind_evidence=None):
    """The sorting step's answer: a bill, its kind citing line 3 (the Rent and Leasing Charges heading) unless given."""
    answer = {"document_type": "bill", "evidence": cite(1, lines[0]), "issuer": value(lines[0], 1), "document_date": MISSING}
    if kind is not None:
        answer.update(bill_kind=kind, bill_kind_evidence=kind_evidence if kind_evidence is not None else cite(3, lines[2]))
    return answer


def rent_replies(lines=RENT, rows=None, kind="rent", kind_evidence=None, **changes):
    """Every reply a rent reading asks for, keyed by schema name; changes replace summary fields."""
    return {"Classification": [classified(lines, kind, kind_evidence)], "BillRentSummary": [bill_header(lines, **changes)],
            "RentBillLines": [{"line_items": rows if rows is not None else [rent_row(lines=lines), water_row(lines)]}]}


def general_replies(lines=RENT, rows=None, kind="general", kind_evidence=None, **changes):
    """Every reply a general bill reading asks for (today's form)."""
    return {"Classification": [classified(lines, kind, kind_evidence)], "BillSummary": [bill_header(lines, **changes)],
            "BillLines": [{"line_items": rows if rows is not None else general_rows(lines)}]}
