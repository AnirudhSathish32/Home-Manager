"""What a tagged ledger item can be for taxes (docs/taxes.md): kinds and their lines, with the return line each feeds.

A line's `share_bp` is the part of the amount the return counts: business meals count at 50% (IRC §274(n)). Everything
else counts in full here; limits that depend on the whole return (medical above 7.5% of AGI, the SALT cap, the
student-loan interest cap) are applied by the return estimate (finance/tax_return.py), not per item.
"""

KINDS = {"business_income": "Business income", "business_expense": "Business expense", "itemized": "Itemized deduction",
         "adjustment": "Adjustment to income", "credit_spending": "Spending for a credit", "tax_payment": "Tax paid ahead"}
# (key, label, where it goes on the return)
LINES = {
    "business_income": (("gross_receipts", "Gross receipts (1099-NEC, 1099-K, clients)", "Schedule C line 1"),
                        ("other_income", "Other business income", "Schedule C line 6")),
    "business_expense": (("advertising", "Advertising", "Schedule C line 8"), ("car_truck", "Car and truck", "Schedule C line 9"),
                         ("commissions", "Commissions and fees", "Schedule C line 10"), ("contract_labor", "Contract labor", "Schedule C line 11"),
                         ("insurance", "Insurance (not health)", "Schedule C line 15"), ("interest", "Interest", "Schedule C line 16"),
                         ("legal_professional", "Legal and professional", "Schedule C line 17"), ("office", "Office expense and software", "Schedule C line 18"),
                         ("rent_lease", "Rent or lease", "Schedule C line 20"), ("repairs", "Repairs and maintenance", "Schedule C line 21"),
                         ("supplies", "Supplies", "Schedule C line 22"), ("taxes_licenses", "Taxes and licenses", "Schedule C line 23"),
                         ("travel", "Travel", "Schedule C line 24a"), ("meals", "Meals (50% counts)", "Schedule C line 24b"),
                         ("utilities", "Utilities and phone", "Schedule C line 25"), ("wages", "Wages you paid", "Schedule C line 26"),
                         ("other", "Other expenses", "Schedule C line 27a")),
    "itemized": (("medical", "Medical and dental", "Schedule A line 1"), ("state_local_tax", "State and local income tax", "Schedule A line 5a"),
                 ("property_tax", "Property tax", "Schedule A line 5b"), ("mortgage_interest", "Mortgage interest", "Schedule A line 8a"),
                 ("charity_cash", "Charity (cash)", "Schedule A line 11"), ("charity_noncash", "Charity (goods)", "Schedule A line 12"),
                 ("other", "Other itemized", "Schedule A line 16")),
    "adjustment": (("educator", "Educator expenses", "Schedule 1 line 11"), ("hsa", "HSA contribution (not through payroll)", "Schedule 1 line 13"),
                   ("se_health_insurance", "Self-employed health insurance", "Schedule 1 line 17"),
                   ("ira", "Traditional IRA contribution", "Schedule 1 line 20"), ("student_loan_interest", "Student-loan interest", "Schedule 1 line 21")),
    "credit_spending": (("dependent_care", "Child and dependent care", "Form 2441"), ("education", "Tuition and course materials", "Form 8863"),
                        ("energy_home", "Energy-efficient home improvement", "Form 5695"), ("clean_vehicle", "Clean vehicle", "Form 8936")),
    "tax_payment": (("federal_estimated", "Federal estimated tax (1040-ES)", "Form 1040 line 26"),
                    ("state_estimated", "State estimated tax", "State return")),
}
SHARE_BP = {("business_expense", "meals"): 5000}
BUSINESS_KINDS = ("business_income", "business_expense")
INCOME_KINDS = ("business_income",)  # Money in; every other kind is money out.


def labels():
    return {kind: {key: label for key, label, _ in lines} for kind, lines in LINES.items()}


def check(kind, line, business_id):
    if kind not in LINES:
        raise ValueError(f"Choose one of: {', '.join(KINDS.values())}.")
    if line not in {key for key, _, _ in LINES[kind]}:
        raise ValueError(f"{line} isn't a {KINDS[kind].lower()} line.")
    if (kind in BUSINESS_KINDS) != (business_id is not None):
        raise ValueError("Choose the business for business income and expenses (and only for them).")
