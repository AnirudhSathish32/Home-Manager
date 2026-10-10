"""The shell's look (phase 1a): the theme switch, the self-hosted fonts and the top bar under 820px. Synthetic data only."""
import os
import socket
import threading
import time

import pytest
import uvicorn

from home_manager.app.api import create_app
from home_manager.library.scanner import ScanLimits

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' blob:; frame-src 'self' blob:; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
NO_OVERFLOW = "document.documentElement.scrollWidth <= window.innerWidth"
CANVAS = "getComputedStyle(document.documentElement).getPropertyValue('--canvas').trim()"


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
def test_theme_fonts_and_narrow_menu(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = create_app(tmp_path / "control", "shell-test", port, ScanLimits(stability_seconds=0))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        assert server.started
        app.state.manager.configure(str(tmp_path / "managed"))
        base = f"http://127.0.0.1:{port}"
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(channel="msedge", headless=True)
            failures = []

            # Theme: the radio sets data-theme, the tokens change, and the choice survives a reload.
            context = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light")
            page = context.new_page()
            page.on("pageerror", lambda error: failures.append(str(error)))
            response = page.goto(f"{base}/#token=shell-test")
            assert response.headers["content-security-policy"] == CSP
            playwright.expect(page.locator("#home-panel")).to_be_visible()
            assert page.evaluate(CANVAS).upper() == "#F7F6F3"
            page.evaluate("document.fonts.ready")
            assert page.evaluate("document.fonts.check('14px \"Plus Jakarta Sans\"')")
            fonts = page.request.get(f"{base}/fonts/PlusJakartaSans-Variable.woff2")
            assert fonts.ok and fonts.headers["content-type"] == "font/woff2"
            page.goto(f"{base}/#/settings")
            page.locator("#appearance-tab").click()
            playwright.expect(page.locator("#theme-system")).to_be_checked()
            # New screens: one checkbox per registered screen (app.js V2_SCREENS), off until chosen.
            playwright.expect(page.locator("#ui-v2-taxes")).not_to_be_checked()
            playwright.expect(page.locator("#ui-v2-list")).to_contain_text("Taxes")
            playwright.expect(page.locator("#ui-v2-choice")).to_be_enabled()
            page.locator("#theme-dark").check()
            playwright.expect(page.locator("html")).to_have_attribute("data-theme", "dark")
            assert page.evaluate(CANVAS).upper() == "#12141A"
            page.reload()
            playwright.expect(page.locator("html")).to_have_attribute("data-theme", "dark")
            page.locator("#appearance-tab").click()
            playwright.expect(page.locator("#theme-dark")).to_be_checked()
            # System follows the OS again: no attribute, and the light OS gives the light canvas.
            page.locator("#theme-system").check()
            assert page.evaluate("document.documentElement.dataset.theme") is None
            assert page.evaluate(CANVAS).upper() == "#F7F6F3"
            # Light chosen on a dark OS stays light.
            page.locator("#theme-light").check()
            page.emulate_media(color_scheme="dark")
            assert page.evaluate(CANVAS).upper() == "#F7F6F3"
            page.locator("#theme-system").check()
            assert page.evaluate(CANVAS).upper() == "#12141A"
            context.close()

            # Storage blocked: the page falls back to System without errors.
            context = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")
            context.add_init_script("Object.defineProperty(window, 'localStorage', {get() { throw new Error('blocked'); }});")
            page = context.new_page()
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(f"{base}/#token=shell-test")
            playwright.expect(page.locator("#home-panel")).to_be_visible()
            assert page.evaluate(CANVAS).upper() == "#12141A"
            context.close()

            # Narrow: a top bar with a menu; the sheet opens, navigates and closes; Esc returns focus.
            context = browser.new_context(viewport={"width": 390, "height": 844})
            page = context.new_page()
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(f"{base}/#token=shell-test")
            playwright.expect(page.locator("#home-panel")).to_be_visible()
            toggle = page.locator("#nav-toggle")
            playwright.expect(toggle).to_be_visible()
            playwright.expect(page.locator("#nav-review")).to_be_hidden()
            assert page.locator(".sidebar").bounding_box()["height"] <= 56
            toggle.click()
            playwright.expect(toggle).to_have_attribute("aria-expanded", "true")
            playwright.expect(page.locator("#nav-review")).to_be_visible()
            page.locator("#nav-review").click()
            playwright.expect(page.locator("#review-panel")).to_be_visible()
            playwright.expect(page.locator("#nav-review")).to_be_hidden()
            playwright.expect(toggle).to_have_attribute("aria-expanded", "false")
            toggle.click()
            playwright.expect(page.locator("#nav-home")).to_be_focused()
            page.keyboard.press("Escape")
            playwright.expect(toggle).to_have_attribute("aria-expanded", "false")
            playwright.expect(toggle).to_be_focused()
            toggle.click()
            playwright.expect(toggle).to_have_attribute("aria-expanded", "true")
            page.locator("main").dispatch_event("click")  # The open sheet covers the page at this height.
            playwright.expect(toggle).to_have_attribute("aria-expanded", "false")
            context.close()

            # No sideways scroll at any width, in either theme.
            for scheme in ("light", "dark"):
                for width in (390, 768, 1440):
                    context = browser.new_context(viewport={"width": width, "height": 900}, color_scheme=scheme)
                    page = context.new_page()
                    page.on("pageerror", lambda error: failures.append(str(error)))
                    page.goto(f"{base}/#token=shell-test")
                    playwright.expect(page.locator("#home-panel")).to_be_visible()
                    assert page.evaluate(NO_OVERFLOW), (scheme, width)
                    context.close()
            browser.close()
            assert failures == []
    finally:
        server.should_exit = True
        thread.join(timeout=5)
