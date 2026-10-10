"""trace.js in the real app (docs/ui.md "Observability components"): figure(), the breakdown panel, provenanceBadge()
and ruleCard(), mounted into a test container with the synthetic dashboard's figures."""
import pytest

from test_ui_parity import browser_test, mount_dashboard_figures, seeded_server

NO_OVERFLOW = "document.documentElement.scrollWidth <= window.innerWidth"


@browser_test
def test_figure_opens_its_breakdown_drills_and_returns(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    with seeded_server(tmp_path, "trace-test") as base, playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(f"{base}/#token=trace-test")
        expect(page.locator("#home-panel")).to_be_visible()
        mount_dashboard_figures(page)
        panel = page.locator("#breakdown")
        expect(panel).to_be_hidden()

        # Gross spending adds up each category, and each category is a breakdown of its own.
        gross = page.locator('#parity-fixture [data-figure-ref^="spending.gross"]')
        expect(gross).to_have_attribute("aria-controls", "breakdown")
        expect(gross).to_have_attribute("aria-expanded", "false")
        gross.click()
        expect(panel).to_be_visible()
        expect(gross).to_have_attribute("aria-expanded", "true")
        expect(page.locator("#breakdown-title")).to_be_focused()
        expect(panel.locator(".breakdown-kicker")).to_have_text("How it's worked out")
        expect(panel.locator(".breakdown-answer")).to_contain_text("149.00")
        expect(panel.locator(".breakdown-steps tbody tr")).to_have_count(2)
        expect(panel.locator(".breakdown-steps tfoot")).to_contain_text("Sums to")
        expect(panel.locator(".breakdown-meta")).to_contain_text("Calculated")
        # Its tile shows which figure is open: the accent border plus a 1px ring.
        ring = page.evaluate("getComputedStyle(document.querySelector('#parity-fixture .figure-tile:has([aria-expanded=\"true\"])')).boxShadow")
        assert "1px" in ring, ring

        # At 1440 the panel is a column beside the page.
        main = page.locator("main").bounding_box()
        box = panel.bounding_box()
        assert box["x"] >= main["x"] + main["width"] - 1, (box, main)
        assert page.evaluate(NO_OVERFLOW)

        # Drill into a category: the breadcrumb shows the path, Esc goes back, then closes and returns focus.
        panel.locator(".breakdown-steps tbody button.link-button").first.click()
        crumbs = panel.get_by_role("navigation", name="Breakdown path")
        expect(crumbs).to_be_visible()
        expect(crumbs.locator('[aria-current="page"]')).to_have_count(1)
        expect(page.locator("#breakdown-title")).to_be_focused()
        page.keyboard.press("Escape")
        expect(crumbs).to_have_count(0)
        expect(panel).to_be_visible()
        page.keyboard.press("Escape")
        expect(panel).to_be_hidden()
        expect(gross).to_be_focused()
        expect(gross).to_have_attribute("aria-expanded", "false")

        # Opening again starts from the figure, not where the last visit ended.
        gross.click()
        panel.locator(".breakdown-steps tbody button.link-button").first.click()
        expect(crumbs).to_be_visible()
        gross.click()
        expect(crumbs).to_have_count(0)
        expect(page.locator("#breakdown-title")).to_be_focused()

        # 1000: floating over the right edge. 390: a bottom sheet. No sideways scroll at either.
        page.set_viewport_size({"width": 1000, "height": 800})
        assert page.evaluate("getComputedStyle(document.getElementById('breakdown')).position") == "fixed"
        box = panel.bounding_box()
        assert abs(box["x"] + box["width"] - 1000) <= 1 and box["width"] == 360, box
        assert page.evaluate(NO_OVERFLOW)
        page.set_viewport_size({"width": 390, "height": 844})
        box = panel.bounding_box()
        assert box["x"] == 0 and abs(box["width"] - 390) <= 1 and abs(box["y"] + box["height"] - 844) <= 1, box
        assert box["height"] <= 844 * .7 + 1, box
        assert page.evaluate(NO_OVERFLOW)
        page.locator("#breakdown").get_by_role("button", name="Close").click()
        expect(panel).to_be_hidden()
        page.set_viewport_size({"width": 1440, "height": 1000})

        # A breakdown that fails to load says so in the panel, with Retry and a way to close.
        page.route("**/api/traces/**", lambda route: route.abort())
        gross.click()
        expect(panel.locator("#breakdown-state").get_by_role("alert")).to_contain_text("Couldn't load this breakdown.")
        page.unroute("**/api/traces/**")
        panel.get_by_role("button", name="Retry").click()
        expect(panel.locator(".breakdown-steps")).to_be_visible()
        expect(panel.locator("#breakdown-state")).to_be_empty()
        expect(page.locator("#breakdown-title")).to_be_focused()
        page.keyboard.press("Escape")
        expect(panel).to_be_hidden()
        assert not failures, failures
        browser.close()


@browser_test
def test_breakdown_edge_cases_provenance_and_rule_card(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    with seeded_server(tmp_path, "trace-test") as base, playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(f"{base}/#token=trace-test")
        expect(page.locator("#home-panel")).to_be_visible()

        # Provenance: icon + the server's own words.
        badges = page.evaluate("""() => [
          {kind: "manual", actor: {person: "Alex", at: "2026-09-03T10:00:00"}},
          {kind: "manual"},
          {kind: "extracted", model: {id: "qwen-vl"}, document: {id: 5, page: 2}, confidence: {level: "doubted", by: "independent check"}},
          {kind: "imported", import: {file: "export.csv", row: 14}},
          {kind: "computed"}, {kind: "override", actor: {person: "Sam"}, reason: "typo"}, {kind: "rule"}, {kind: "rate"}, {kind: "mystery_kind"},
        ].map(prov => { const badge = provenanceBadge(prov); return [badge.textContent, badge.dataset.tone, badge.querySelectorAll("svg").length]; })""")
        assert [text for text, _, _ in badges] == [
            "Entered by Alex · Sep 3, 2026", "Entered", "Read by model qwen-vl · page 2 · doubted by independent check",
            "Imported · export.csv row 14", "Worked out", "Changed by Sam · typo", "Rule", "Exchange rate", "Mystery kind"]
        assert all(icons == 1 for _, _, icons in badges[:8])

        card = page.evaluate("""() => { const card = ruleCard({name: "Federal brackets", source: "IRS Rev. Proc. 2025-32", version: "2026.1",
                                                               tax_year: 2026, checked_on: "2026-01-15", cpa_reviewed_on: null});
                                        return [card.textContent, card.querySelector("code").textContent, card.querySelectorAll("a").length]; }""")
        assert "Federal brackets" in card[0] and "IRS Rev. Proc. 2025-32" in card[0] and "Jan 15, 2026" in card[0]
        assert "Not CPA-reviewed" in card[0] and card[1] == "2026.1" and card[2] == 0
        assert "No check recorded" in page.evaluate("() => ruleCard({name: 'x', source: 's', version: 'v', checked_on: null}).textContent")

        # A figure without a trace is a plain amount; a flagged one says so in words.
        plain = page.evaluate("() => figure({display: '12.00 USD'}).tagName")
        assert plain == "SPAN"
        flags = page.evaluate("""() => [...figure({display: "1.00 USD", trace: "spending.net?x=1", verification: {state: "partial"}, stale: true})
                                         .querySelectorAll(".figure-flag")].map(flag => flag.textContent)""")
        assert flags == ["Unconfirmed", "Changed"]

        # The panel's edge cases, from a served trace: a long label, 200+ inputs, no rule, steps that don't add up, stale.
        long_label = "A very long input label " * 12
        trace = {
            "ref": "fixture", "label": "Fixture breakdown " + "with a long title " * 6, "formula": "Synthetic.",
            "result": {"display": "10.00 USD"}, "reconciles": False, "stale": True, "computed_at": "2026-10-10T12:00:00+00:00",
            "steps": [{"n": 1, "label": "Only step", "op": "+", "value": {"display": "9.99 USD"}, "running": {"display": "9.99 USD"}, "trace": None, "count": 3}],
            "rounding": {"adjustment": {"display": "0.01 USD"}, "note": "half-even cents"},
            "inputs": [{"key": "a", "label": long_label, "value": {"display": "-1.00 USD"}, "verification": "needs_review",
                        "provenance": {"kind": "extracted", "document": {"id": 7, "lines": ["page-1-line-2"], "page": 1}}, "trace": None},
                       {"key": "b", "label": "Checked", "value": {"display": "2.00 USD"}, "verification": "checked_automatically",
                        "provenance": {"kind": "imported"}, "trace": None}],
            "inputs_page": {"total": 240, "shown": 200}, "rule": None,
        }
        page.route("**/api/traces/fixture", lambda route: route.fulfill(status=200, content_type="application/json", json=trace))
        page.evaluate("""() => { const host = element("div"); host.id = "parity-fixture"; document.querySelector("main").append(host);
                                 host.append(figure({display: "10.00 USD", trace: "fixture"})); }""")
        page.locator('#parity-fixture [data-figure-ref="fixture"]').click()
        panel = page.locator("#breakdown")
        expect(panel.locator(".breakdown-steps")).to_contain_text("Rounding")
        expect(panel.locator(".breakdown-steps")).to_contain_text("· 3 lines")
        expect(panel.locator(".breakdown-steps tfoot")).to_contain_text("These steps don't add up to the figure.")
        expect(panel).to_contain_text("Showing 200 of 240.")
        expect(panel.locator(".rule-card")).to_have_count(0)
        expect(panel.locator(".breakdown-meta")).to_contain_text("inputs changed since this was last shown")
        expect(panel.locator(".breakdown-meta .status-badge")).to_have_text("Changed")
        row = panel.locator('.input-row[data-verification="needs_review"]')
        expect(row).to_contain_text("Unconfirmed")
        expect(row.get_by_role("link", name="Open source")).to_have_attribute("href", "#/documents/7?lines=page-1-line-2")
        expect(panel.locator('.input-row[data-verification="checked_automatically"]')).to_contain_text("Checked automatically")
        assert page.evaluate("(() => { const panel = document.getElementById('breakdown'); return panel.scrollWidth <= panel.clientWidth; })()")
        for width in (390, 1000, 1440):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate(NO_OVERFLOW), width
        assert not failures, failures
        browser.close()
