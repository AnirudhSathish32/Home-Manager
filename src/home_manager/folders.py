"""Application folder identifiers, never paths supplied to the operating system."""

from enum import Enum

HIERARCHY = {
    "01_Banking": ["Bank_Statements", "Credit_Card_Statements"],
    "02_Income": ["Pay_Stubs", "Tax_Documents"],
    "03_Purchases": ["Receipts", "Invoices", "Refunds_Returns"],
    "04_Bills": ["Utilities", "Subscriptions", "Other_Bills"],
    "05_Investments": ["Brokerage", "Retirement"],
    "06_Obligations": ["Housing", "Loans", "Insurance"],
}
FOLDERS = [f"{parent}/{child}" for parent, children in HIERARCHY.items() for child in children]
DocumentFolder = Enum("DocumentFolder", {f"folder_{i}": value for i, value in enumerate(["Unfiled", *FOLDERS])}, type=str)


def validate_folder(value):
    if value not in ["Unfiled", *FOLDERS]:
        raise ValueError("Choose one of the supported document folders.")
    return value
