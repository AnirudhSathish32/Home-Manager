"""This year's synthetic taxes for the browser tests and ui_shots.py (docs/taxes.md), with synthetic bank lines only."""
from datetime import date

import pytest

from conftest import documents_by_name, inbox_scan
from home_manager.finance.engines.opentax import YEARS
from home_manager.household.tax_tables import TaxTables
from test_plan_tracking import stub
from test_withholding import FEDERAL, confirmed

# The page works out this year's return, and Engine 1 covers only the years it's pinned for: past them, re-pin the
# engine (docs/taxes.md "The tax engines") rather than let these tests fail as if the page were broken.
this_year_covered = pytest.mark.skipif(date.today().year not in YEARS, reason=f"Engine 1 covers {sorted(YEARS)} only; re-pin it for this year")


def seed_tax_year(manager, store, ledger):
    """This year's synthetic taxes: a 1985 birth year, the confirmed federal table, one biweekly pay stub and 20,000 of
    interest nobody withholds on, so Tax Zen recommends a W-4 change. False (and nothing seeded) when Engine 1 doesn't
    cover this year."""
    today = date.today()
    if today.year not in YEARS:
        return False
    manager.configure_household(manager.household.model_copy(update={"birth_year": 1985}))  # The tax engine's age facts.
    confirmed(TaxTables(store), "US", FEDERAL)
    inbox_scan(store, {"stub.png": b"stub", "tax-export.csv": b"date,amount\n"})
    docs = documents_by_name(store)
    stub(store, docs["stub.png"], f"{today.year}-01-02", 47936, 270671)
    with store.connection() as db:
        db.execute("UPDATE income_records SET pay_frequency=26")
    account = ledger.create_account("Savings", "savings", "USD")
    with store.connection() as db:  # 20,000 of interest nobody withholds on.
        ledger.insert_transactions(db, account, [{"posted_date": f"{today.year}-01-05", "description": "INTEREST PAID", "amount_minor": 2000000, "currency": "USD",
                                                  "locator": {"rows": [1]}}], "import",
                                   {"document_id": docs["tax-export.csv"]["id"], "blob_hash": docs["tax-export.csv"]["current_hash"], "source_key": "import:test"})
    return True
