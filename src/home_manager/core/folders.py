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
# Two stores over one library. Money: proof of what was spent, which the ledger counts and reconciles.
# Documents: papers kept because they matter (leases, policies, pay stubs, tax forms).
MONEY_FOLDERS = ["Receipts", "Bank_Statements", "Credit_Card_Statements"]
DOCUMENT_FOLDERS = ["Housing", "Insurance", "Investments", "Jobs", "Loans", "Taxes"]
FOLDERS = [*MONEY_FOLDERS, *DOCUMENT_FOLDERS]
FILING_FOLDERS = ["Unfiled", *FOLDERS]
LIBRARY_FOLDERS = ["Inbox", *FILING_FOLDERS]
# Folders no longer filed into, and where startup moves their files. They stay readable until then.
RETIRED_FOLDERS = {"Bills": "Unfiled", "Income": "Jobs"}
# Jobs holds one folder per employer, each with these sections (docs/taxes.md "Jobs and pay stubs").
JOB_SECTIONS = ("Paystubs", "Documents")
DocumentFolder = Enum("DocumentFolder", {f"folder_{i}": value for i, value in enumerate(FILING_FOLDERS)}, type=str)  # type: ignore[misc]
HistoricalFolder = Enum("HistoricalFolder", {f"folder_{i}": value for i, value in enumerate(  # type: ignore[misc]
    [*FILING_FOLDERS, *RETIRED_FOLDERS, *[f"{parent}/{child}" for parent, children in LEGACY_HIERARCHY.items() for child in children]])}, type=str)


def validate_folder(value):
    if value not in FILING_FOLDERS:
        raise ValueError("Choose one of the supported document folders.")
    return value
