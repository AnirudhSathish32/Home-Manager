"""Screenshot app pages on a synthetic household, for before/after comparisons in the UI redesign.

Never touches the live library or %LOCALAPPDATA%\\HomeManager: the control dir and library are temporary folders.
Run from the project root with the venv:
    .venv/Scripts/python.exe .claude/skills/ui-redesign/scripts/ui_shots.py --routes home,review --out DIR
"""
import argparse
from datetime import date, datetime, timedelta
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from conftest import inbox_scan  # noqa: E402
from home_manager.app.api import create_app  # noqa: E402
from home_manager.finance.forecast import AssetInput, Assets  # noqa: E402
from home_manager.finance.reconcile import Reconciler  # noqa: E402
from home_manager.finance.tools import FinanceTools  # noqa: E402
from home_manager.library.scanner import ScanLimits  # noqa: E402
from test_reconcile_tools import add, receipt  # noqa: E402
from test_taxes_browser import seed_tax_year  # noqa: E402

TOKEN = "ui-shots"


def seed(manager, root):
    """A small household: two accounts, a month of spending across categories, a budget, and items left to review."""
    manager.configure(str(root / "managed"))
    inbox_scan(manager.store, {"checking-statement.csv": b"Date,Description,Amount\n",
                               "card-statement.csv": b"Date,Description,Amount\n"})
    docs = manager.store.documents()["items"]
    checking = manager.ledger.create_account("Household checking", "checking", "USD")
    card = manager.ledger.create_account("Everyday card", "credit_card", "USD")
    # Every date falls in this month, on or before today, so the Home period counts it.
    first = date.today().replace(day=1)
    day = lambda n: first.replace(day=min(n, date.today().day)).isoformat()  # noqa: E731
    verified = add(manager.store, manager.ledger, checking, docs[0], [
        (day(1), "PAYROLL ACME CORP", 412500), (day(1), "CITY UTILITIES", -8950),
        (day(1), "Rent - Maple Street", -165000), (day(2), "Fresh Market", -12480),
        (day(3), "Corner Cafe", -1860), (day(4), "Metro Transit", -4500)], status="verified")
    proposed = add(manager.store, manager.ledger, card, docs[-1], [
        (day(2), "Hardware Depot", -6342), (day(3), "Streaming Plus", -1599),
        (day(4), "Fresh Market", -9875)])
    receipt(manager.ledger, docs[0], "Fresh Market", day(4), 9875)
    categories = ["income", "utilities", "housing", "groceries", "dining", "transport"]
    with manager.store.connection() as db:
        for txn_id, category in zip(verified, categories):
            db.execute("UPDATE transactions SET category=?,category_source='user' WHERE id=?", (category, txn_id))
        db.execute("UPDATE transactions SET category='groceries',category_source='user' WHERE id=?", (proposed[-1],))
    manager.ledger.set_budget("groceries", "USD", "250.00")
    manager.ledger.set_budget("dining", "USD", "120.00")
    seed_today(manager, checking, card)
    # This year's taxes (a pay stub, interest, the federal table), when the tax engine covers this year.
    seed_tax_year(manager, manager.store, manager.ledger)


def seed_today(manager, checking, card):
    """What Today shows beyond one month: statement balances (the card's over 35 days old), a car and its loan, a
    confirmed monthly rent due in about ten days, and spending in the two months before, so the trend has bars."""
    store, ledger = manager.store, manager.ledger
    inbox_scan(store, {"checking-statement.pdf": b"synthetic checking statement", "card-statement.pdf": b"synthetic card statement",
                       "rent-receipt.png": b"synthetic rent receipt", "history.csv": b"Date,Description,Amount\n"})
    docs = {doc["relative_path"].rsplit("/", 1)[-1]: doc for doc in store.documents()["items"]}
    today = date.today()
    with store.connection() as db:
        for account, name, back, closing, kind in ((checking, "checking-statement.pdf", 5, 841230, "bank"), (card, "card-statement.pdf", 60, 31245, "credit_card")):
            doc = docs[name]
            db.execute("INSERT INTO statements(account_id,document_id,blob_hash,statement_type,period_end,closing_balance_minor,currency,review_status,"
                       "created_at,updated_at) VALUES(?,?,?,?,?,?,'USD','verified','t','t')",
                       (account["id"], doc["id"], doc["current_hash"], kind, (today - timedelta(days=back)).isoformat(), closing))
    assets = Assets(store)
    assets.add(AssetInput(name="Family car", kind="vehicle", value="18000", currency="USD", as_of=today.isoformat()))
    assets.add(AssetInput(name="Car loan", kind="loan", value="6000", currency="USD", as_of=today.isoformat()))
    # A confirmed monthly rent paid 20 days ago, so it is next due in about ten.
    rent = docs["rent-receipt.png"]
    ledger.publish_receipt({"merchant": "Maple Street Rentals", "purchase_date": (today - timedelta(days=20)).isoformat(), "subtotal_minor": None,
                            "tax_minor": None, "tip_minor": None, "total_minor": 165000, "currency": "USD", "issues": [], "items": [],
                            "category": "housing", "recurrence": "monthly", "locator": {"line_ids": ["line-1"]}},
                           {"document_id": rent["id"], "blob_hash": rent["current_hash"], "source_key": "extraction:rent", "run_id": "extraction:rent"}, "verified")
    reconciler = Reconciler(store)
    reconciler.run()
    bill = next(row for row in FinanceTools(store).get_recurring_obligations()["obligations"] if row["merchant"] == "Maple Street Rentals")
    reconciler.review_obligation(bill["id"], "verified")
    earlier = lambda months: (today.replace(day=1) - timedelta(days=1 + 31 * (months - 1))).replace(day=12).isoformat()  # noqa: E731
    add(store, ledger, checking, docs["history.csv"], [(earlier(1), "Fresh Market", -21040), (earlier(1), "Corner Cafe", -4210),
                                                        (earlier(2), "Fresh Market", -18825), (earlier(2), "Metro Transit", -4500)], status="verified")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--routes", default="home,review,transactions,spending,documents")
    parser.add_argument("--widths", default="390,768,1440")
    parser.add_argument("--themes", default="light,dark")
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--full-page", action="store_true", help="capture the whole scroll height, not just the viewport")
    parser.add_argument("--v2", default="", help="comma-separated routes to show redesigned (the ui_v2_screens flag)")
    parser.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "ui-shots" / datetime.now().strftime("%Y%m%d-%H%M%S"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="hm-ui-shots-", ignore_cleanup_errors=True) as tmp, socket.socket() as sock:
        root = Path(tmp)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        app = create_app(root / "control", TOKEN, port, ScanLimits(stability_seconds=0))
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False))
        threading.Thread(target=server.run, daemon=True).start()
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        if not server.started:
            sys.exit("server did not start")
        try:
            seed(app.state.manager, root)
            with sync_playwright() as driver:
                browser = driver.chromium.launch(channel="msedge", headless=True)
                if args.v2:
                    request = driver.request.new_context()
                    response = request.put(f"http://127.0.0.1:{port}/api/ui-screens", data={"routes": args.v2.split(",")},
                                           headers={"Authorization": f"Bearer {TOKEN}"})
                    if not response.ok:
                        sys.exit(f"could not turn on {args.v2}: {response.status}")
                    request.dispose()
                for theme in args.themes.split(","):
                    for width in map(int, args.widths.split(",")):
                        page = browser.new_page(viewport={"width": width, "height": args.height}, color_scheme=theme)
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.goto(f"http://127.0.0.1:{port}/#token={TOKEN}")
                        page.wait_for_load_state("networkidle")
                        for route in args.routes.split(","):
                            page.goto(f"http://127.0.0.1:{port}/#/{route}")
                            page.wait_for_load_state("networkidle")
                            # Slow pages (the tax engine) stay aria-busy until loaded; a selector wait, as the CSP blocks string wait_for_function.
                            page.wait_for_selector("[aria-busy='true']", state="detached", timeout=120000)
                            page.wait_for_timeout(300)
                            name = f"{route.replace('/', '_').replace('?', '_')}-{width}-{theme}.png"
                            page.screenshot(path=str(args.out / name), full_page=args.full_page)
                            overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
                            print(f"{name}{'  HORIZONTAL OVERFLOW' if overflow else ''}")
                        for error in errors:
                            print(f"page error ({width}, {theme}): {error}")
                        page.close()
                browser.close()
        finally:
            server.should_exit = True
    print(f"saved to {args.out}")


if __name__ == "__main__":
    main()
