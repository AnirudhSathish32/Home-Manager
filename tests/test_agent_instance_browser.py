"""The agent test instance in the browser (docs/development.md "Agent test instance"): the "Test data" marker, seeded
screens on every route, the LM Studio address in Settings, and the test-mode refusals and offline states as screens.

The seeded instance runs through scripts/test_instance.py at a tmp_path root on a free port (never tests/.tmp:8775);
the in-process apps run on tmp_path with the sandbox on (or off, for SC-11). Synthetic data only.
"""

from contextlib import contextmanager
import itertools
import logging
import os

import httpx
import pytest

from home_manager.core import sandbox
from seed_household import seed
from test_agent_guards import REFUSED_LOG, counts, make_decoy, no_egress, real_path_spies, sc05_setup  # noqa: F401  (fixtures)
from test_agent_instance import Harness, lmstudio, raw_counts, restore, template  # noqa: F401  (fixtures)
from test_taxes_v2_browser import served

browser_test = pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
MARKER = "#test-instance-marker"
NO_OVERFLOW = "document.documentElement.scrollWidth <= window.innerWidth"
# SC-02 step 3: a seeded row or figure on each screen, not its empty state.
SEEDED = {"home": "#today-tiles > .figure-tile", "transactions": "#tx2-table tbody tr", "documents": "#rc2-table tbody tr",
          "review": "#review2-queue > *", "investments": "#inv2-accounts tbody tr:not(.group-row)",
          "whatif": "#wi2-scenario-select option[value]:not([value=''])", "inventory": "#it2-items tbody tr:not(.group-row)",
          "taxes": "#taxes2-body:not([hidden]) .figure-tile"}


@pytest.fixture(scope="module")
def running(tmp_path_factory, template):  # noqa: F811
    """One restored copy of the template, started, shared by the read-only tests in this module."""
    base = tmp_path_factory.getbasetemp() / "browser-run"
    harness = Harness(base / "instance", base / "fake-localappdata", template.lmstudio)
    restore(template.root, harness.root)
    harness.run("start", check=0)
    try:
        yield harness
    finally:
        harness.stop()


@contextmanager
def browser(playwright, width=1440, height=900, color_scheme="light"):
    with playwright.sync_playwright() as driver:
        launched = driver.chromium.launch(channel="msedge", headless=True)
        page = launched.new_page(viewport={"width": width, "height": height}, color_scheme=color_scheme)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            yield page, errors
        finally:
            launched.close()


def settle(page, url):
    page.goto(url)
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("[aria-busy='true']", state="detached", timeout=120000)


@browser_test
def test_sc02_every_route_has_the_marker_and_seeded_content(running, tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    session, before = running.session(), raw_counts(running.root / "library")
    base, shots = session["base_url"], tmp_path / "shots"
    shots.mkdir()
    for scheme in ("light", "dark"):
        for width in (390, 768, 1440):
            with browser(playwright, width, 900, scheme) as (page, errors):
                page.goto(session["link"])  # Step 1: authenticated from the link, no token prompt.
                page.wait_for_load_state("networkidle")
                expect(page.get_by_role("heading", name="Today", level=1)).to_be_visible()
                expect(page.locator(MARKER)).to_be_visible()
                routes = list(dict.fromkeys(page.eval_on_selector_all(".nav-link[href^='#/']", "links => links.map(link => link.getAttribute('href'))")))
                assert "#/home" in routes and "#/settings" in routes, routes
                for route in routes:  # Step 2.
                    settle(page, base + "/" + route)
                    expect(page.locator(MARKER)).to_be_visible()
                    assert page.evaluate(NO_OVERFLOW), (route, width, scheme)
                    name = route[2:].split("?")[0]
                    page.screenshot(path=str(shots / f"{name}-{width}-{scheme}.png"))
                    if width == 1440 and scheme == "light" and name in SEEDED:  # Step 3.
                        if name == "taxes" and not running.seeded()["manifest"]["taxes_seeded"]:
                            continue  # Engine 1 doesn't cover this year (seed_taxes.this_year_covered).
                        assert page.locator(SEEDED[name]).count() > 0, name
                page.reload()  # A reload keeps the marker.
                page.wait_for_load_state("networkidle")
                expect(page.locator(MARKER)).to_be_visible()
                assert errors == [], (width, scheme, errors)
    seeded = {name for name in SEEDED if name != "taxes" or running.seeded()["manifest"]["taxes_seeded"]}
    assert seeded - {path.name.split("-")[0] for path in shots.iterdir()} == set()
    assert raw_counts(running.root / "library") == before


@browser_test
def test_marker_visible_everywhere(running, tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    # 390 and 768: the top bar with the menu closed; 1024: the 64 px rail without labels; 1440: the full sidebar.
    for scheme, (width, label) in itertools.product(("light", "dark"), ((390, "Test data"), (768, "Test data"), (1024, "Test"), (1440, "Test data"))):
        with browser(playwright, width, 900, scheme) as (page, errors):
            page.goto(running.session()["link"])
            page.wait_for_load_state("networkidle")
            marker = page.locator(MARKER)
            expect(page.locator("#nav-toggle")).to_have_attribute("aria-expanded", "false")
            expect(marker).to_be_visible()
            assert page.locator(".brand-name").is_visible() == (width != 1024)
            assert [span.inner_text() for span in marker.locator(".test-instance-long, .test-instance-short").all() if span.is_visible()] == [label], width
            assert marker.text_content().startswith("Test instance: synthetic ")  # Read in full by assistive technology.
            box = marker.bounding_box()
            assert box["width"] > 0 and box["x"] >= 0 and box["x"] + box["width"] <= (64 if width == 1024 else width), (width, box)
            page.screenshot(path=str(tmp_path / f"marker-{width}-{scheme}.png"))
            assert errors == []


@browser_test
def test_models_show_lmstudio_address(running):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    with browser(playwright) as (page, errors):
        page.goto(running.session()["link"])
        settle(page, running.session()["base_url"] + "/#/settings?tab=models")
        expect(page.locator("#model-panel")).to_be_visible()
        expect(page.locator("#vision-url")).to_have_value(running.lmstudio)
        expect(page.locator("#reasoning-url")).to_have_value(running.lmstudio)
        expect(page.locator("#vision-model")).to_have_value("synthetic-vision")
        expect(page.locator("#reasoning-model")).to_have_value("synthetic-reasoning")
        assert errors == []


# In-process apps -----------------------------------------------------------------------------------------------------

@contextmanager
def sandboxed_served(tmp_path, token, protected=()):
    root = tmp_path / "instance"
    root.mkdir()
    sandbox.activate(root, protected=list(protected))
    try:
        with served(tmp_path, token) as (manager, base):
            manager.configure(str(root / "library"))
            yield manager, base, root
    finally:
        sandbox.deactivate()


@browser_test
def test_sc11_no_marker_without_test_mode(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    assert not sandbox.active()
    with served(tmp_path, "plain") as (manager, base), browser(playwright) as (page, errors):
        manager.configure(str(tmp_path / "library"))
        page.goto(f"{base}/#token=plain")
        page.wait_for_load_state("networkidle")
        expect(page.locator("#nav-home")).to_be_visible()
        expect(page.locator(MARKER)).to_be_hidden()
        assert not page.evaluate("document.body.classList.contains('test-instance')")
        assert errors == []


@browser_test
def test_sc14_profile_and_restore_folders_refused_on_screen(tmp_path, real_path_spies):  # noqa: F811
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    decoy = make_decoy(tmp_path / "decoy-protected-folder")
    (tmp_path / "elsewhere").mkdir()
    with sandboxed_served(tmp_path, "sc14", [decoy]) as (manager, base, root), browser(playwright) as (page, errors):
        profiles_file = tmp_path / "control" / "profiles.json"
        before = profiles_file.read_bytes() if profiles_file.exists() else None
        page.goto(f"{base}/#token=sc14")
        settle(page, f"{base}/#/settings?tab=profiles")
        rows = page.locator("#profile-rows tr").count()
        for folder, message in ((r"P:\Finances\y", "holds real data"), (str(tmp_path / "elsewhere" / "y"), "only folders inside")):
            page.locator("#profile-name").fill("Agent")
            page.locator("#profile-folder").fill(folder)
            page.locator("#profile-add").click()
            toast = page.locator(".toast[data-tone='error']").last
            expect(toast).to_contain_text("Test instance:")
            expect(toast).to_contain_text(message)
            page.screenshot(path=str(tmp_path / f"sc14-profile-{message.split()[0]}.png"))
            toast.get_by_role("button", name="Dismiss").click()
            expect(page.locator("#profile-rows tr")).to_have_count(rows)
        settle(page, f"{base}/#/settings?tab=backup")
        page.locator("#restore-backup").fill(str(root / "backups"))
        page.locator("#restore-target").fill(r"P:\Finances\y")
        page.locator("#restore-start").click()
        page.get_by_role("dialog").get_by_role("button", name="Verify and restore").click()
        expect(page.locator("#restore-status")).to_contain_text("holds real data")
        page.screenshot(path=str(tmp_path / "sc14-restore.png"))
        after = profiles_file.read_bytes() if profiles_file.exists() else None
        assert after == before
        assert real_path_spies == []
        assert errors == []


@browser_test
def test_sc05_offline_screens(tmp_path, local_model, no_egress, caplog):  # noqa: F811
    """SC-05 step 5: with the internet refused, Money, Investments and Inventory show their existing states."""
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    caplog.set_level(logging.WARNING, logger="home_manager.sandbox")
    with sandboxed_served(tmp_path, "sc05") as (manager, base, root):
        seed(manager, root, local_model)
        with httpx.Client(base_url=base, headers={"Authorization": "Bearer sc05"}) as client:
            wallet_id, _ = sc05_setup(client, manager)
        before = counts(manager.store)
        with browser(playwright) as (page, errors):
            page.goto(f"{base}/#token=sc05")
            page.wait_for_load_state("networkidle")
            for route in ("spending", "transactions", "accounts"):  # Money: rates are refused before any page asks.
                settle(page, f"{base}/#/{route}")
            settle(page, f"{base}/#/investments?account={wallet_id}")
            page.get_by_role("button", name="Refresh prices").click()
            expect(page.locator(".toast[data-tone='error']").last).to_be_visible()
            page.screenshot(path=str(tmp_path / "sc05-investments.png"))
            settle(page, f"{base}/#/inventory")
            page.get_by_role("button", name="Identify items on the Corner Shop receipt").click()
            expect(page.locator(".toast").last).to_contain_text("Identifying items")
            manager.future.result(timeout=60)
            settle(page, f"{base}/#/inventory")
            page.screenshot(path=str(tmp_path / "sc05-inventory.png"))
            assert errors == []
        assert counts(manager.store) == before
    hosts = set(no_egress.hosts())
    assert {"api.coingecko.com", "world.openfoodfacts.org"} <= hosts, hosts
    assert no_egress.hosts("double") == []
    assert {REFUSED_LOG + "api.coingecko.com", REFUSED_LOG + "world.openfoodfacts.org"} <= {
        record.getMessage() for record in caplog.records}
