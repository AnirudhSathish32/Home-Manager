"""Settings in the browser (restyled in place; design-system/home-manager/pages/system.md): the ?tab= URL, the
Independent checks reviewer and the Donate tab. Synthetic data only."""
import os

import pytest

from test_taxes_v2_browser import served

browser_test = pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
NO_OVERFLOW = "document.documentElement.scrollWidth <= window.innerWidth"
TABS = {"library": "directories-tab", "profiles": "profiles-tab", "preferences": "preferences-tab", "appearance": "appearance-tab",
        "models": "model-tab", "checks": "checks-tab", "backup": "backup-tab", "sharing": "sharing-tab", "privacy": "privacy-tab",
        "donate": "donate-tab"}


@browser_test
def test_settings_tabs_reviewer_and_donate(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "settings-test"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(f"{base}/#token={token}")
        page.locator("#nav-settings").click()
        expect(page.locator("#directories-panel")).to_be_visible()
        expect(page).to_have_url(f"{base}/#/settings")

        # A tab is in the URL, and reload opens it again.
        page.get_by_role("tab", name="Independent checks").click()
        expect(page).to_have_url(f"{base}/#/settings?tab=checks")
        page.reload()
        expect(page.locator("#checks-tab")).to_have_attribute("aria-selected", "true")
        expect(page.locator("#checks-panel")).to_be_visible()
        expect(page.locator("#decision-status")).to_contain_text("No decision model is chosen")
        expect(page.locator(".settings-nav")).to_have_attribute("aria-orientation", "vertical")

        # The reviewer: Off hides the server fields; a second chat model shows them.
        expect(page.locator("#reviewer-kind")).to_have_value("off")
        expect(page.locator("#reviewer-url")).to_be_hidden()
        page.locator("#reviewer-kind").select_option("chat")
        expect(page.locator("#reviewer-url")).to_be_visible()
        expect(page.locator("#test-reviewer")).to_be_visible()

        # A remote URL is refused, and the error shows under the URL field.
        page.locator("#reviewer-url").fill("http://192.168.1.20:1234/v1")
        page.locator("#reviewer-model").fill("second-model")
        page.locator("#save-reviewer").click()
        expect(page.locator("#reviewer-form [data-error-for='url']")).to_contain_text("127.0.0.1")
        expect(page.locator("#reviewer-form .save-result")).to_be_hidden()
        assert page.request.get(f"{base}/api/settings", headers={"Authorization": f"Bearer {token}"}).json()["reviewer"]["provider"] == "off"

        # Saving round-trips through /api/settings, with a result line under Save; focus stays on the button.
        page.locator("#reviewer-url").fill("http://127.0.0.1:1234/v1")
        page.locator("#save-reviewer").click()
        expect(page.locator("#reviewer-form .save-result")).to_have_text("Saved.")
        expect(page.locator("#reviewer-form [data-error-for='url']")).to_be_empty()
        expect(page.locator(".toast", has_text="Reviewer saved.")).to_be_visible()
        expect(page.locator("#save-reviewer")).to_be_focused()
        saved = page.request.get(f"{base}/api/settings", headers={"Authorization": f"Bearer {token}"}).json()["reviewer"]
        assert (saved["provider"], saved["base_url"], saved["model"]) == ("chat", "http://127.0.0.1:1234/v1", "second-model")
        page.reload()
        expect(page.locator("#reviewer-kind")).to_have_value("chat")
        expect(page.locator("#reviewer-model")).to_have_value("second-model")

        # The decision model as reviewer hides URL and model and keeps them as saved.
        page.locator("#reviewer-kind").select_option("decision")
        expect(page.locator("#reviewer-url")).to_be_hidden()
        page.locator("#save-reviewer").click()
        expect(page.locator("#reviewer-form .save-result")).to_have_text("Saved.")
        saved = page.request.get(f"{base}/api/settings", headers={"Authorization": f"Bearer {token}"}).json()["reviewer"]
        assert (saved["provider"], saved["model"]) == ("decision", "second-model")

        # The link to the decision model opens Local models.
        page.locator("#checks-decision-link").click()
        expect(page.locator("#model-tab")).to_have_attribute("aria-selected", "true")
        expect(page).to_have_url(f"{base}/#/settings?tab=models")

        # Donate: a count, and a link to the Donate page.
        page.goto(f"{base}/#/settings?tab=donate")
        expect(page.locator("#donate-settings-panel")).to_be_visible()
        expect(page.locator("#donate-settings-count")).to_have_text("0 documents checked, ready to donate.")
        page.locator("#donate-settings-open").click()
        expect(page).to_have_url(f"{base}/#/donate")
        expect(page.locator("#donate-panel")).to_be_visible()

        # The collapsed sidebar's profile icon links to Profiles & family.
        expect(page.locator("#nav-profile")).to_have_attribute("href", "#/settings?tab=profiles")
        page.goto(f"{base}/#/settings?tab=profiles")
        expect(page.locator("#profiles-panel")).to_be_visible()

        # No horizontal scroll on any tab at any width; the tablist is a row below 800px.
        for width in (390, 768, 1440):
            page.set_viewport_size({"width": width, "height": 900})
            for tab, tab_id in TABS.items():
                page.goto(f"{base}/#/settings{'' if tab == 'library' else f'?tab={tab}'}")
                expect(page.locator(f"#{tab_id}")).to_have_attribute("aria-selected", "true")
                assert page.evaluate(NO_OVERFLOW), (width, tab)
        expect(page.locator(".settings-nav")).to_have_attribute("aria-orientation", "vertical")
        page.set_viewport_size({"width": 390, "height": 900})
        expect(page.locator(".settings-nav")).to_have_attribute("aria-orientation", "horizontal")
        browser.close()
        assert failures == []
