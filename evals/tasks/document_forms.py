"""Document forms (docs/evals.md; specs/document-forms SC-17, FR-24): a pay stub's, bank statement's and card statement's
printed fields, and for pay stubs the values read from the wrong column that would count without the user.

Each case is a made-up document of a known type, read with the app's own form and rows (ExtractionService.extract) and
checked in code (normalize and the review rules), as the app records it. A pay stub's "wrong column" value is a
this-period amount (gross, net or a line's) equal to its year-to-date amount on a stub that would count automatically:
the target is zero (text_extraction_plan.md).
"""

from home_manager.core.money import as_decimal_text
from home_manager.documents.extraction import EXTRACTION_VERSION, MISSING_VALUE, Classification, normalize, review_reasons

from .common import make_case, result, text_lines
from .receipt_kinds import reader, shown

NAME, ROLE, VERSION, PROMPT_VERSION = "document_forms", "reasoning", "document-forms-v1", EXTRACTION_VERSION
TYPES = ("paystub", "bank_statement", "credit_card_statement")

# Fixture P (specs/document-forms test contract): this period and year to date per line.
P_LINES = [("Regular 80.00 h @ 31.25", "2,500.00", "32,500.00"), ("Federal income tax", "250.00", "3,250.00"), ("Social Security", "155.00", "2,015.00"),
           ("Medicare", "36.25", "471.25"), ("GA state tax", "96.41", "1,253.33"), ("401(k)", "50.00", "650.00")]
P_HEADER = ["SYNTH WORKS", "EARNINGS STATEMENT", "PAY DATE 2026-07-03", "PAY PERIOD 2026-06-15 TO 2026-06-28", "PAY FREQUENCY BIWEEKLY", "CURRENCY USD"]
P_EXTRAS = ["PTO BALANCE 56.00 HRS", "DIRECT DEPOSIT CHECKING ****1234 1,500.00", "SAVINGS ****9876 412.34"]
P_TABLE = [*P_HEADER, "Description | This period | Year to date", *[" | ".join(row) for row in P_LINES], "Gross pay | 2,500.00 | 32,500.00",
           "Net pay | 1,912.34 | 24,860.42", *P_EXTRAS]
P_FLAT = [*P_HEADER, "THIS PERIOD", "REGULAR 2,500.00", "FEDERAL INCOME TAX 250.00", "SOCIAL SECURITY 155.00", "MEDICARE 36.25", "GA STATE TAX 96.41",
          "PRE-TAX RETIREMENT 50.00", "GROSS PAY 2,500.00", "NET PAY 1,912.34", "YEAR TO DATE", "REGULAR 32,500.00", "FEDERAL INCOME TAX 3,250.00",
          "SOCIAL SECURITY 2,015.00", "MEDICARE 471.25", "GA STATE TAX 1,253.33", "PRE-TAX RETIREMENT 650.00", "GROSS PAY 32,500.00",
          "NET PAY 24,860.42", *P_EXTRAS]
BANK = ["SYNTH BANK", "EVERYDAY CHECKING ACCOUNT 000123456789", "STATEMENT PERIOD 2026-09-01 TO 2026-09-30", "STATEMENT CURRENCY USD",
        "OPENING BALANCE 1,000.00", "DEPOSITS 2,500.00", "WITHDRAWALS 1,200.50", "CLOSING BALANCE 2,299.50", "INTEREST EARNED 0.42", "APY 0.50%",
        "FEES 0.00", "09/03 PAYROLL SYNTH WORKS +2,500.00", "09/05 RENT -1,200.50"]
CARD = ["SYNTH CARD", "ACCOUNT ENDING 4242", "STATEMENT PERIOD 2026-09-01 TO 2026-09-30", "STATEMENT CURRENCY USD", "PREVIOUS BALANCE 500.00",
        "PAYMENTS -500.00", "CREDITS -20.00", "PURCHASES 812.45", "FEES CHARGED 0.00", "INTEREST CHARGED 0.00", "NEW BALANCE 792.45",
        "PURCHASE APR 24.99%", "CASH ADVANCE APR 29.99%", "CREDIT LIMIT 5,000.00", "AVAILABLE CREDIT 4,207.55", "POINTS EARNED 812",
        "09/10 PAYMENT THANK YOU +500.00", "09/12 SYNTH SHOP REFUND +20.00", "09/15 SYNTH SHOP -812.45"]
PAY_FIELDS = {"gross_pay": "2500.00", "net_pay": "1912.34", "hours": "80.00", "rate": "31.25", "pto_balance": "56.00", "deposits": "2"}
BANK_FIELDS = {"account_type": "checking", "deposits_total": "2500.00", "withdrawals_total": "1200.50", "interest_earned": "0.42", "apy": "0.50%"}
CARD_FIELDS = {"purchase_apr": "24.99%", "cash_advance_apr": "29.99%", "credit_limit": "5000.00", "available_credit": "4207.55", "rewards_earned": "812"}


def cases():
    out = [make_case(NAME, {"type": "paystub", "lines": P_TABLE}, {"fields": PAY_FIELDS}, ["paystub", "p_table"]),
           make_case(NAME, {"type": "paystub", "lines": P_FLAT}, {"fields": {key: value for key, value in PAY_FIELDS.items() if key not in ("hours", "rate")}},
                     ["paystub", "p_flat"]),
           make_case(NAME, {"type": "bank_statement", "lines": BANK}, {"fields": BANK_FIELDS}, ["bank_statement"]),
           make_case(NAME, {"type": "credit_card_statement", "lines": CARD}, {"fields": CARD_FIELDS}, ["credit_card_statement"])]
    # Variants: the same documents without one printed detail each, which must then stay out (never filled in).
    for left_out, changes in ((("PTO BALANCE",), {"pto_balance": None}), (("SAVINGS ****9876",), {"deposits": "1"}),
                              (("DIRECT DEPOSIT", "SAVINGS ****9876"), {"deposits": None})):
        for index, (layout, lines) in enumerate((("p_table", P_TABLE), ("p_flat", P_FLAT))):
            fields = {**out[index]["expected"]["fields"], **changes}
            out.append(make_case(NAME, {"type": "paystub", "lines": [line for line in lines if not line.startswith(left_out)]}, {"fields": fields},
                                 ["paystub", layout, "unprinted"]))
    for name, field in (("DEPOSITS", "deposits_total"), ("WITHDRAWALS", "withdrawals_total"), ("INTEREST EARNED", "interest_earned"), ("APY", "apy")):
        out.append(make_case(NAME, {"type": "bank_statement", "lines": [line for line in BANK if not line.startswith(name + " ")]},
                             {"fields": {**BANK_FIELDS, field: None}}, ["bank_statement", "unprinted"]))
    # No account type word printed: it is other, never guessed from the transactions.
    out.append(make_case(NAME, {"type": "bank_statement", "lines": [line.replace("EVERYDAY CHECKING ", "") for line in BANK]},
                         {"fields": {**BANK_FIELDS, "account_type": "other"}}, ["bank_statement", "unprinted"]))
    for name, field in (("PURCHASE APR", "purchase_apr"), ("CASH ADVANCE APR", "cash_advance_apr"), ("CREDIT LIMIT", "credit_limit"),
                        ("AVAILABLE CREDIT", "available_credit"), ("POINTS EARNED", "rewards_earned")):
        out.append(make_case(NAME, {"type": "credit_card_statement", "lines": [line for line in CARD if not line.startswith(name)]},
                             {"fields": {**CARD_FIELDS, field: None}}, ["credit_card_statement", "unprinted"]))
    return out


def run(case, config, work):
    kind, lines, notes = case["input"]["type"], text_lines(case["input"]["lines"]), []
    known = Classification(document_type=kind, evidence=[], issuer=MISSING_VALUE, document_date=MISSING_VALUE)
    _, header, rows, _, _ = reader().extract(config, work, lines, notes, known)
    record, issues = normalize(kind, header, rows, "USD", lines)
    issues = [*issues, *notes]
    issues += review_reasons(kind, record, None, issues)
    details = record.get("details") or {}
    if kind == "paystub":
        regular = next((line for line in record["lines"] if line["line_group"] == "earnings"), None) or {"details": {}, "current_minor": None, "ytd_minor": None}
        fields = {"gross_pay": money(record.get("gross_pay_minor")), "net_pay": money(record.get("net_pay_minor")),
                  "hours": shown(regular["details"].get("hours")), "rate": shown(regular["details"].get("rate")), "pto_balance": shown(details.get("pto_balance")),
                  "deposits": str(len(details.get("deposit_splits", []))) if details.get("deposit_splits") else None}
        counted = not issues
        wrong = [value for value, ytd in ((record.get("gross_pay_minor"), record.get("gross_pay_ytd_minor")),
                                          (record.get("net_pay_minor"), record.get("net_pay_ytd_minor")),
                                          *((line["current_minor"], line["ytd_minor"]) for line in record["lines"]))
                 if value is not None and ytd is not None and value and value == ytd]
        return {"fields": fields, "counted": counted, "wrong_column_counted": len(wrong) if counted else 0}
    return {"fields": {name: shown(detail) for name, detail in details.items() if isinstance(detail, dict)}, "counted": not issues, "wrong_column_counted": 0}


def money(minor):
    return as_decimal_text(minor, "USD") if minor is not None else None


def grade(case, output):
    expected = case["expected"]["fields"]
    printed = {name: want for name, want in expected.items() if want is not None}
    checks = {"fields_present": sum(1 for name in printed if output["fields"].get(name) is not None),
              "fields_correct": sum(1 for name, want in printed.items() if output["fields"].get(name) == want),
              "fields_printed": len(printed),
              "invented": sum(1 for name, want in expected.items() if want is None and output["fields"].get(name) is not None),
              "wrong_column_counted": output["wrong_column_counted"]}
    checks["all_fields"] = checks["fields_correct"] == len(printed) and not checks["invented"]
    checks["no_wrong_column"] = checks["wrong_column_counted"] == 0
    checks["field_share"] = round(checks["fields_correct"] / len(printed), 4) if printed else 1.0
    return result(checks, ["all_fields", "no_wrong_column"], ["field_share", "no_wrong_column"])


def report_lines(rows_by_candidate):
    """Printed fields present and correct per document type, and per pay stub fixture the wrong-column values that would
    have counted without the user (target 0)."""
    lines = ["", "| Candidate | Type | Fields present | Fields right | Invented | Wrong column, counted |", "|---|---|---|---|---|---|"]
    for candidate, rows in rows_by_candidate.items():
        for kind in TYPES:
            for layout in (("p_table", "p_flat") if kind == "paystub" else (None,)):
                mine = [row for row in rows if kind in row["tags"] and (layout is None or layout in row["tags"]) and row["status"] == "ok"]
                if not mine:
                    continue
                checks = [row["grades"]["checks"] for row in mine]
                printed = sum(check["fields_printed"] for check in checks)
                lines.append(f"| {candidate} | {kind}{f' ({layout})' if layout else ''} | {sum(check['fields_present'] for check in checks)} of {printed} | "
                             f"{sum(check['fields_correct'] for check in checks)} of {printed} | {sum(check['invented'] for check in checks)} | "
                             f"{sum(check['wrong_column_counted'] for check in checks)} |")
    return lines
