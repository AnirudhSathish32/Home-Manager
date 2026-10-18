"""Screenshot app pages on a synthetic household, for before/after comparisons in the UI redesign.

Never touches the live library or %LOCALAPPDATA%\\HomeManager: the control dir and library are temporary folders.
Run from the project root with the venv:
    .venv/Scripts/python.exe .claude/skills/ui-redesign/scripts/ui_shots.py --routes home,review --out DIR
"""
import argparse
from datetime import datetime
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

from home_manager.app.api import create_app  # noqa: E402
from home_manager.library.scanner import ScanLimits  # noqa: E402
from model_server import start_model_server  # noqa: E402
from seed_household import seed  # noqa: E402

TOKEN = "ui-shots"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--routes", default="home,review,transactions,spending,documents",
                        help="comma-separated; {receipt_doc}, {review_doc}, {statement_doc} and {review_record} name the seeded documents and records; "
                             "{work_account}, {cd_account}, {ira_account}, {ibonds_account}, {pension_account}, {education_account} and {brokerage_account} the investment accounts")
    parser.add_argument("--widths", default="390,768,1440")
    parser.add_argument("--themes", default="light,dark")
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--full-page", action="store_true", help="capture the whole scroll height, not just the viewport")
    parser.add_argument("--open-ask", action="store_true", help="open the Ask panel (Control+J) on each route before capturing")
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
        model, stop_model = start_model_server()
        try:
            app.state.manager.configure(str(root / "managed"))
            ids, _ = seed(app.state.manager, root, model)
            routes = args.routes.format(**ids).split(",")
            with sync_playwright() as driver:
                browser = driver.chromium.launch(channel="msedge", headless=True)
                for theme in args.themes.split(","):
                    for width in map(int, args.widths.split(",")):
                        page = browser.new_page(viewport={"width": width, "height": args.height}, color_scheme=theme)
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.goto(f"http://127.0.0.1:{port}/#token={TOKEN}")
                        page.wait_for_load_state("networkidle")
                        for route in routes:
                            page.goto(f"http://127.0.0.1:{port}/#/{route}")
                            page.wait_for_load_state("networkidle")
                            # Slow pages (the tax engine) stay aria-busy until loaded; a selector wait, as the CSP blocks string wait_for_function.
                            page.wait_for_selector("[aria-busy='true']", state="detached", timeout=120000)
                            page.wait_for_timeout(300)
                            if args.open_ask:
                                if page.locator("#assistant-panel").is_hidden():
                                    page.keyboard.press("Control+j")
                                page.wait_for_timeout(300)
                            name = f"{route.replace('/', '_').replace('?', '_')}{'-ask' if args.open_ask else ''}-{width}-{theme}.png"
                            page.screenshot(path=str(args.out / name), full_page=args.full_page)
                            overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
                            print(f"{name}{'  HORIZONTAL OVERFLOW' if overflow else ''}")
                        for error in errors:
                            print(f"page error ({width}, {theme}): {error}")
                        page.close()
                browser.close()
        finally:
            stop_model()
            server.should_exit = True
    print(f"saved to {args.out}")


if __name__ == "__main__":
    main()
