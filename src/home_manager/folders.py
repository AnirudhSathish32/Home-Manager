"""Application folder identifiers, never paths supplied to the operating system."""

from enum import Enum

LEGACY_HIERARCHY = {
    "01_Banking": ["Bank_Statements", "Credit_Card_Statements"],
    "02_Income": ["Pay_Stubs", "Tax_Documents"],
    "03_Purchases": ["Receipts", "Invoices", "Refunds_Returns"],
    "04_Bills": ["Utilities", "Subscriptions", "Other_Bills"],
    "05_Investments": ["Brokerage", "Retirement"],
    "06_Obligations": ["Housing", "Loans", "Insurance"],
}
FOLDERS = ["Bank_Statements", "Credit_Card_Statements", "Receipts", "Income", "Bills", "Taxes",
           "Investments", "Loans", "Insurance", "Housing"]
FILING_FOLDERS = ["Unfiled", *FOLDERS]
LIBRARY_FOLDERS = ["Inbox", *FILING_FOLDERS]
DocumentFolder = Enum("DocumentFolder", {f"folder_{i}": value for i, value in enumerate(FILING_FOLDERS)}, type=str)
HistoricalFolder = Enum("HistoricalFolder", {f"folder_{i}": value for i, value in enumerate(
    [*FILING_FOLDERS, *[f"{parent}/{child}" for parent, children in LEGACY_HIERARCHY.items() for child in children]])}, type=str)


def validate_folder(value):
    if value not in FILING_FOLDERS:
        raise ValueError("Choose one of the supported document folders.")
    return value
