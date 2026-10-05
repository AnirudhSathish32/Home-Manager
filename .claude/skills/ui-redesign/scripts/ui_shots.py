"""Screenshot app pages on a synthetic household, for before/after comparisons in the UI redesign.

Never touches the live library or %LOCALAPPDATA%\\HomeManager: the control dir and library are temporary folders.
Run from the project root with the venv:
    .venv/Scripts/python.exe .claude/skills/ui-redesign/scripts/ui_shots.py --routes home,review --out DIR
"""
import argparse
from datetime import date, datetime
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
from home_manager.library.scanner import ScanLimits  # noqa: E402
from test_reconcile_tools import add, receipt  # noqa: E402

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
            db.execute("UPDATE transactions SET category=? WHERE id=?", (category, txn_id))
        db.execute("UPDATE transactions SET category='groceries' WHERE id=?", (proposed[-1],))
    manager.ledger.set_budget("groceries", "USD", "250.00")
    manager.ledger.set_budget("dining", "USD", "120.00")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--routes", default="home,review,transactions,spending,documents")
    parser.add_argument("--widths", default="390,768,1440")
    parser.add_argument("--themes", default="light,dark")
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--full-page", action="store_true", help="capture the whole scroll height, not just the viewport")
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
