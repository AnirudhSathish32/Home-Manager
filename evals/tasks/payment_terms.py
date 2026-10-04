"""Payment terms (eval_plan.md task 8): scheduled payments stated in a lease, insurance policy or loan document.

Each printed scheduled payment must be found once with its payee, exact amount and frequency. Deposits, late fees,
coverage limits, deductibles and totals for the whole term are not payment terms, and a section with none must give none.
"""

from decimal import Decimal, InvalidOperation
import re

from home_manager.documents.extraction import EXTRACTION_VERSION, ExtractionService

from .common import make_case, names_match, result, text_lines

NAME, ROLE, VERSION, PROMPT_VERSION = "payment_terms", "reasoning", "payment-terms-v1", EXTRACTION_VERSION
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
# (document kind, lines, [(payee, amount, frequency)], tags)
DOCUMENTS = [
    ("housing_document", ["RESIDENTIAL LEASE AGREEMENT", "Landlord: Maple Court Apartments LLC", "Tenant: J. Rivera",
                          "Rent: Tenant shall pay monthly rent of $1,850.00 due on the 1st day of each month beginning 2026-09-01.",
                          "Security deposit: $1,850.00, due at signing.", "Late fee: $75.00 if rent is received after the 5th."],
     [("Maple Court Apartments", "1850.00", "monthly")], ["lease"]),
    ("housing_document", ["LEASE", "Lessor: Harbor View Properties", "Monthly rent: $2,200.00, payable on the first of each month.",
                          "Pet rent: $35.00 per month for one cat.", "Key replacement fee: $50.00."],
     [("Harbor View Properties", "2200.00", "monthly"), ("Harbor View Properties", "35.00", "monthly")], ["lease", "two_terms"]),
    ("housing_document", ["OAKWOOD HOMEOWNERS ASSOCIATION", "Assessment notice", "Quarterly dues of $360.00 are payable to Oakwood HOA",
                          "on January 1, April 1, July 1 and October 1.", "Special assessment for roof repair: $1,200.00 (one time)."],
     [("Oakwood HOA", "360.00", "quarterly")], ["hoa"]),
    ("housing_document", ["MORTGAGE STATEMENT SUMMARY", "Lender: First Example Mortgage Co.", "Monthly payment (includes escrow): $1,800.76",
                          "Next payment due 2026-10-01", "Unpaid principal balance: $248,113.20"],
     [("First Example Mortgage", "1800.76", "monthly")], ["mortgage"]),
    ("housing_document", ["LEASE ADDENDUM", "Parking: Tenant rents space 14 from Riverside Lofts for $90.00 per month.",
                          "All other terms of the lease remain in effect."],
     [("Riverside Lofts", "90.00", "monthly")], ["lease"]),
    ("housing_document", ["RESIDENTIAL LEASE AGREEMENT", "Landlord: Cedar Grove Rentals", "Section 3. Rent is $1,475.00 per month.",
                          "Section 9. Rent of $1,475.00 per month is payable to Cedar Grove Rentals by the 1st.", "Section 12. Smoking is not permitted."],
     [("Cedar Grove Rentals", "1475.00", "monthly")], ["lease", "repeated"]),
    ("housing_document", ["SECTION 14. MAINTENANCE", "Tenant shall keep the premises clean and report damage promptly.",
                          "Landlord will repair appliances within a reasonable time."], [], ["none"]),
    ("insurance_document", ["SAFEGUARD AUTO INSURANCE", "Policy declarations", "Policy period: 2026-09-01 to 2027-03-01",
                            "Six-month premium: $642.00", "Bodily injury liability limit: $100,000 per person", "Collision deductible: $500"],
     [("Safeguard Auto Insurance", "642.00", "semiannual")], ["insurance"]),
    ("insurance_document", ["HOMEGUARD MUTUAL", "Homeowners policy HG-55120", "Annual premium: $1,284.00", "Dwelling coverage: $350,000",
                            "All other perils deductible: $1,000"],
     [("HomeGuard Mutual", "1284.00", "annual")], ["insurance"]),
    ("insurance_document", ["LIFEPATH INSURANCE COMPANY", "Term life policy", "Monthly premium: $38.50, drafted on the 15th of each month.",
                            "Death benefit: $500,000"],
     [("LifePath Insurance", "38.50", "monthly")], ["insurance"]),
    ("insurance_document", ["SAFEGUARD AUTO INSURANCE", "Payment plan", "You chose monthly installments: 6 payments of $107.00",
                            "Installment fee: $3.00 per installment is included."],
     [("Safeguard Auto Insurance", "107.00", "monthly")], ["insurance"]),
    ("insurance_document", ["RENTERS POLICY", "Insurer: Keystone Renters Insurance", "Annual premium $156.00, paid in full.",
                            "Personal property limit: $30,000", "Deductible: $250"],
     [("Keystone Renters Insurance", "156.00", "annual")], ["insurance"]),
    ("insurance_document", ["COVERAGE SUMMARY", "Medical payments: $5,000 per person", "Uninsured motorist: $50,000 per accident",
                            "Comprehensive deductible: $250"], [], ["none"]),
    ("insurance_document", ["WELLCARE HEALTH PLAN", "Member premium: $412.00 per month", "Annual out-of-pocket maximum: $7,500",
                            "Primary care copay: $25"],
     [("WellCare Health Plan", "412.00", "monthly")], ["insurance"]),
    ("loan_document", ["RETAIL INSTALLMENT CONTRACT", "Creditor: Lakeside Auto Finance", "Amount financed: $22,500.00",
                       "Your payment schedule: 60 monthly payments of $412.37 beginning 2026-10-15", "Total of payments: $24,742.20",
                       "Late charge: 5% of the payment"],
     [("Lakeside Auto Finance", "412.37", "monthly")], ["loan"]),
    ("loan_document", ["STUDENT LOAN DISCLOSURE", "Servicer: BrightPath Loan Servicing", "Repayment: 120 monthly payments of $287.14",
                       "First payment due 2026-11-01", "Origination fee: $210.00"],
     [("BrightPath Loan Servicing", "287.14", "monthly")], ["loan"]),
    ("loan_document", ["PERSONAL LOAN AGREEMENT", "Lender: Summit Credit Union", "Borrower agrees to repay in 24 monthly installments of $230.00.",
                       "Prepayment penalty: none"],
     [("Summit Credit Union", "230.00", "monthly")], ["loan"]),
    ("loan_document", ["HOME EQUITY LINE", "Lender: First Example Bank", "Draw period interest-only payment: $145.00 monthly",
                       "Credit limit: $50,000.00", "Annual fee: $75.00"],
     [("First Example Bank", "145.00", "monthly"), ("First Example Bank", "75.00", "annual")], ["loan", "two_terms"]),
    ("loan_document", ["TRUTH IN LENDING DISCLOSURE", "Annual percentage rate: 6.9%", "Finance charge: $2,242.20", "Amount financed: $22,500.00"],
     [], ["none"]),
    ("loan_document", ["AGRICULTURAL EQUIPMENT NOTE", "Payee: Prairie Farm Credit", "Payable in semiannual installments of $3,150.00",
                       "due each March 1 and September 1."],
     [("Prairie Farm Credit", "3150.00", "semiannual")], ["loan"]),
    ("housing_document", ["STORAGE UNIT RENTAL", "Facility: SecureSpace Storage", "Unit B-12 rent: $129.00 every month", "Admin fee: $25.00 one time"],
     [("SecureSpace Storage", "129.00", "monthly")], ["lease"]),
    ("insurance_document", ["PET INSURANCE", "Insurer: Happy Tails Pet Insurance", "Premium: $49.99 billed every month", "Annual deductible: $250"],
     [("Happy Tails Pet Insurance", "49.99", "monthly")], ["insurance"]),
]


def cases():
    return [make_case(NAME, {"kind": kind, "lines": lines, "currency": "USD"},
                      {"terms": [{"payee": payee, "amount": amount, "frequency": frequency} for payee, amount, frequency in terms]}, tags)
            for kind, lines, terms, tags in DOCUMENTS]


def run(case, config, work):
    notes = []
    terms = ExtractionService.payment_terms(config, work, case["input"]["kind"], text_lines(case["input"]["lines"]), notes)
    if notes and not terms:
        raise ValueError("Extraction failed validation: " + notes[0])
    return {"terms": [{"payee": term.payee.value, "amount": term.amount.value, "frequency": term.frequency,
                       "currency": term.currency.value} for term in terms], "notes": notes}


def money(text):
    match = NUMBER.search(text or "")
    try:
        return Decimal(match.group().replace(",", "")) if match else None
    except InvalidOperation:
        return None


def grade(case, output):
    expected, got = case["expected"]["terms"], list(output["terms"])
    unused, matched, wrong_amount = list(range(len(got))), 0, 0
    for term in expected:
        same = [index for index in unused if got[index]["frequency"] == term["frequency"] and names_match(term["payee"], got[index]["payee"] or "")]
        exact = [index for index in same if money(got[index]["amount"]) == Decimal(term["amount"])]
        if exact:
            unused.remove(exact[0])
            matched += 1
        elif same:
            wrong_amount += 1
    keys = [(money(term["amount"]), term["frequency"]) for term in got]
    duplicates = len(keys) - len(set(keys))
    checks = {"recall": round(matched / len(expected), 4) if expected else 1.0, "precision": round(matched / len(got), 4) if got else 1.0,
              "all_found": matched == len(expected), "nothing_extra": len(got) == matched, "no_duplicates": duplicates == 0,
              "money_errors": wrong_amount}
    return result(checks, ["all_found", "nothing_extra"], ["recall", "precision"])
