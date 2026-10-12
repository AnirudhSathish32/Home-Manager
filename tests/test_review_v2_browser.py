"""To check, redesigned (review_v2.js; design-system/home-manager/pages/review.md), on synthetic read and recorded
documents plus one of each other kind (tests/seed_documents.py): the decision in view, J/K and the URL, V with Undo,
the source beside each kind, Correct with its preview, combining images, correcting an unmatched receipt, the family's
"Who is it for?", every width, and v1's keys staying quiet."""
from datetime import date, timedelta
import socket
import threading
import time

import pytest
import uvicorn

from conftest import inbox_scan
from home_manager.app.api import create_app
from home_manager.library.scanner import ScanLimits
from seed_documents import document_server
from test_family_browser import spend
from test_ui_parity import browser_test

TOKEN = "review-v2-test"
NO_OVERFLOW = "document.documentElement.scrollWidth <= window.innerWidth"


def open_review(page, base, query=""):
    page.goto(f"{base}/#/review{query}")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("#review2-panel:not([hidden]) #review2-bar button")


def bottom(locator):
    box = locator.bounding_box()
    return box["y"] + box["height"]


@browser_test
def test_to_check_decides_each_kind_with_its_source_in_view(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    with document_server(tmp_path, TOKEN, review_items=True) as (base, ids, _), playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1366, "height": 768})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(f"{base}/#token={TOKEN}")
        page.wait_for_load_state("networkidle")
        open_review(page, base)
        expect(page.locator("[data-page='review']")).to_have_count(1)  # One section per page.
        expect(page.locator("#nav-review .nav-label")).to_have_text("To check")
        queue = page.locator("#review2-queue")
        for group in ("Records to verify", "Warranties to confirm", "Tax tables to confirm", "Receipt items to identify",
                      "Images that look like one document", "Receipts with no matching charge"):
            expect(queue.locator(".review2-group-title", has_text=group)).to_have_count(1)

        # The first item, its source beside it with the evidence lit, and the decision in view (Layout rule 1).
        assert f"item=record%3Areceipt-{ids['review_record']}" in page.evaluate("location.hash")
        expect(page.locator("#review2-what")).to_have_text("Receipt: Hardware Depot")
        expect(page.locator("#review2-why .needs-row")).to_contain_text("do not equal the total")
        expect(page.locator("#review2-source .sv-line.selected").first).to_be_visible()
        expect(queue.locator('.review2-entry[aria-current="true"]')).to_have_text("Receipt: Hardware Depot")
        assert bottom(page.locator("#review2-confirm")) <= 768
        page.set_viewport_size({"width": 1440, "height": 900})
        assert bottom(page.locator("#review2-confirm")) <= 900
        page.set_viewport_size({"width": 1366, "height": 768})

        # J and K move through the queue and keep the item in the URL; a reload stays on it.
        page.keyboard.press("j")
        expect(page.locator("#review2-what")).to_have_text("Warranty: Acme Toaster")
        assert f"item=warranty%3A{ids['warranty']}" in page.evaluate("location.hash")
        page.reload()
        page.wait_for_selector("#review2-bar button")
        expect(page.locator("#review2-what")).to_have_text("Warranty: Acme Toaster")
        # Found online: the quote and its address as text, never a link.
        card = page.locator("#review2-source .source-card")
        expect(card).to_contain_text("Found online")
        expect(card).to_contain_text("one-year limited warranty")
        expect(card.locator("a")).to_have_count(0)
        page.keyboard.press("j")
        expect(page.locator("#review2-what")).to_contain_text("Federal income tax table")
        expect(page.locator("#review2-source .source-card")).to_contain_text("Quoted sources")
        expect(page.locator("#review2-source .source-table tbody tr")).to_have_count(2)
        page.keyboard.press("j")
        expect(page.locator("#review2-what")).to_have_text("SOAP")
        expect(page.locator("#review2-source .sv-line.selected")).to_have_text("SOAP 1 @ 20.00 20.00")
        for _ in range(3):
            page.keyboard.press("k")
        expect(page.locator("#review2-what")).to_have_text("Receipt: Hardware Depot")

        # Correct opens in the item's column with a preview of what saving would change; Esc closes it.
        page.locator("#review2-correct").click()
        form = page.locator("#review2-form .cc-form")
        date_field = form.get_by_label("Purchase date")
        expect(date_field).to_be_focused()
        page.keyboard.press("v")  # Typing in the form never decides the item.
        date_field.fill((date.today().replace(day=1) - timedelta(days=20)).isoformat())
        # It needs review, so it isn't counted yet: the preview says no total moves, and why it still needs you.
        expect(form.locator(".cc-preview")).to_contain_text("No totals change.", timeout=10000)
        expect(form.locator(".cc-preview")).to_contain_text("Still needs you")
        save = form.get_by_role("button", name="Save")
        assert 0 <= save.bounding_box()["y"] and bottom(save) <= 768
        page.keyboard.press("Escape")
        expect(form).to_be_hidden()
        expect(page.locator("#review2-correct")).to_be_focused()

        # V confirms; the next item takes its place, and Undo puts it back.
        with page.expect_request(lambda request: request.method == "POST" and request.url.endswith(f"/receipt/{ids['review_record']}/review")):
            page.keyboard.press("v")
        toast = page.locator(".toast", has_text="Confirmed.")
        expect(toast).to_be_visible()
        expect(page.locator("#review2-what")).to_have_text("Warranty: Acme Toaster")
        expect(queue.locator(".review2-group-title", has_text="Records to verify")).to_have_count(0)
        toast.get_by_role("button", name="Undo").click()
        expect(queue.locator(".review2-group-title", has_text="Records to verify")).to_have_count(1)
        expect(page.locator("#review2-what")).to_have_text("Warranty: Acme Toaster")

        # An unmatched receipt offers Correct for its purchase date only, and Open document.
        queue.locator(".review2-entry", has_text="Fresh Market").click()
        expect(page.locator("#review2-what")).to_have_text("Receipt from Fresh Market")
        expect(page.locator("#review2-open")).to_have_attribute("href", f"#/documents/{ids['receipt_doc']}")
        expect(page.locator("#review2-confirm")).to_have_count(0)
        page.locator("#review2-correct").click()
        expect(form.locator(".field")).to_have_count(2)  # Purchase date, and why.
        form.get_by_label("Purchase date").fill((date.today() - timedelta(days=3)).isoformat())
        form.get_by_role("button", name="Save").click()
        expect(page.locator(".toast", has_text="Saved.")).to_be_visible()

        # Two images that look like one document: their pages as chips, combined with V's button.
        queue.locator(".review2-entry", has_text="porch-left.png").click()
        expect(page.locator("#review2-source .review2-chips .filter-chip")).to_have_count(2)
        page.locator("#review2-confirm").click()
        expect(page.locator(".toast", has_text="Combined.")).to_be_visible()
        expect(queue.locator(".review2-group-title", has_text="Images that look like one document")).to_have_count(0)

        # Under 1180px the queue is a select; under 900px the bar is fixed to the bottom; nothing scrolls sideways.
        page.set_viewport_size({"width": 1024, "height": 768})
        expect(page.locator("#review2-picker")).to_be_visible()
        expect(queue).to_be_hidden()
        page.locator("#review2-next").click()
        assert "item=" in page.evaluate("location.hash")
        for width in (768, 390):
            page.set_viewport_size({"width": width, "height": 800})
            expect(page.locator("#review2-bar")).to_be_visible()
            assert page.locator("#review2-bar").evaluate("bar => getComputedStyle(bar).position") == "fixed"
            assert bottom(page.locator("#review2-bar")) <= 800
            assert page.evaluate(NO_OVERFLOW), width
        page.set_viewport_size({"width": 1440, "height": 900})
        assert page.evaluate(NO_OVERFLOW)
        assert failures == [], failures
        browser.close()


@browser_test
def test_v_on_a_warranty_decides_only_the_warranty(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    with document_server(tmp_path, TOKEN, review_items=True) as (base, ids, _), playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1366, "height": 768})
        posts = []
        page.on("request", lambda request: posts.append(request.url) if request.method == "POST" else None)
        page.goto(f"{base}/#token={TOKEN}")
        page.wait_for_load_state("networkidle")
        open_review(page, base, f"?item=warranty:{ids['warranty']}")
        expect(page.locator("#review2-what")).to_have_text("Warranty: Acme Toaster")
        posts.clear()
        page.keyboard.press("v")
        expect(page.locator(".toast", has_text="Warranty confirmed.")).to_be_visible()
        assert any(url.endswith(f"/api/warranties/{ids['warranty']}/review") for url in posts), posts
        assert not any("/api/finance/records/" in url for url in posts), posts
        browser.close()


@browser_test
def test_the_familys_to_check_asks_who_each_upload_is_for(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = create_app(tmp_path / "control", TOKEN, port, ScanLimits(stability_seconds=0))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        assert server.started
        manager = app.state.manager
        month = date.today().isoformat()[:7]
        # The family setup from test_family_browser.py: Alex and Sam, and Jo set up as Sam's profile.
        manager.configure(str(tmp_path / "alex"))
        manager.rename_profile(manager.profile["id"], "Alex")
        spend(manager, "alex", [(month + "-01", "Groceries", -12500)])
        alex = manager.profile["id"]
        sam = manager.create_profile("Sam", str(tmp_path / "sam"))
        manager.switch_profile(alex)
        family = manager.create_family("The Parks", str(tmp_path / "family"), ["Jo"], my_profile=alex)
        from home_manager.app.family_sync import FamilyFolder
        folder = FamilyFolder(tmp_path / "family")
        jo = folder.data["members"][0]["member_id"]
        folder.close()
        manager.set_up_local_member(family["id"], jo, profile_id=sam["id"])
        manager.switch_profile(family["id"])
        manager.future.result(timeout=30)
        inbox_scan(manager.store, {"market.png": b"family market receipt"})
        doc = manager.store.documents()["items"][0]
        manager.ledger.publish_receipt({"merchant": "Corner Market", "purchase_date": month + "-02", "subtotal_minor": None, "tax_minor": None,
                                        "tip_minor": None, "total_minor": 5001, "currency": "USD", "issues": [], "items": [], "locator": {}},
                                       {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": "test", "run_id": None}, "verified")
        manager.switch_profile(alex)
        base = f"http://127.0.0.1:{port}"
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            failures = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(f"{base}/#token={TOKEN}")
            page.wait_for_load_state("networkidle")
            page.locator("#profile-select").select_option(family["id"])
            expect(page.locator("#today-family-members")).to_contain_text("Jo", timeout=15000)
            open_review(page, base)
            queue = page.locator("#review2-queue")
            expect(queue.locator(".review2-group-title", has_text="Who is it for?")).to_have_count(1)
            expect(queue.locator(".review2-group-title", has_text="Receipts with no matching charge")).to_have_count(0)
            expect(page.locator("#review2-what")).to_have_text("Who is Corner Market for?")
            bar = page.locator("#review2-bar")
            send = bar.get_by_role("button", name="Send")
            assert bottom(send) <= 768
            bar.get_by_label("For").select_option("shared")
            expect(bar.locator(".routing-people")).to_be_visible()
            send.click()
            expect(page.locator("#toasts")).to_contain_text("Shared:")
            expect(queue.locator(".review2-group-title", has_text="Who is it for?")).to_have_count(0)
            assert failures == [], failures
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
