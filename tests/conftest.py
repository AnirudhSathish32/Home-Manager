"""Synthetic local model server; never sends documents outside the test process."""

import os

import pytest

from home_manager.library.scanner import ScanLimits, Scanner
from model_server import start_model_server


def pytest_addoption(parser):
    parser.addoption("--browser", action="store_true", help="Also run the opt-in local browser tests (same as RUN_BROWSER_TESTS=1).")


def pytest_configure(config):
    # Set before collection: the browser tests' skip conditions read the variable when their modules are imported.
    if config.getoption("--browser"):
        os.environ["RUN_BROWSER_TESTS"] = "1"


def inbox_scan(store, files=None, **limits):
    """Put files directly in Library/Inbox, the only way documents enter a library, and capture them."""
    for name, data in (files or {}).items():
        (store.library.inbox / name).write_bytes(data)
    job = store.create_job()
    Scanner(store, ScanLimits(stability_seconds=0, **limits)).run(job)
    return job


def documents_by_name(store):
    return {doc["relative_path"]: doc for doc in store.documents()["items"]}


def assert_ledger_healthy(store):
    """No ledger rule at error level is broken (finance/health.py). Warnings and info may be expected mid-scenario."""
    from home_manager.finance.health import check_ledger
    with store.connection() as db:
        errors = [item for item in check_ledger(db) if item.severity == "error"]
    assert errors == []


# Every tile's figure, badge and plain amount stays inside its tile (style.css "Observability": figure tile).
TILES_FIT = """() => [...document.querySelectorAll('#today-tiles > .figure-tile')].every(tile => {
  const t = tile.getBoundingClientRect();
  return [...tile.querySelectorAll('.figure-button[data-size="lg"], .figure-flag, :scope > .amount')]
    .every(el => { const r = el.getBoundingClientRect(); return r.left >= t.left - 0.5 && r.right <= t.right + 0.5; });
})"""

# For each row: fit it (trace.js fitFigures), then list every figure, badge or plain amount outside its cell, any amount
# whose digits split across lines, and any row whose figures differ in size.
_FIGURES_MISFIT = """selector => {
  const problems = [];
  for (const row of document.querySelectorAll(selector)) {
    fitFigures(row);
    const sizes = [];  // Tiles a subpixel apart in width get sizes a subpixel apart.
    for (const cell of row.querySelectorAll('.figure-tile, .plan-figure')) {
      const box = cell.getBoundingClientRect();
      for (const el of cell.querySelectorAll('.figure-button[data-size="lg"], .figure-flag, :scope > .amount')) {
        const r = el.getBoundingClientRect();
        if (r.left < box.left - 0.5 || r.right > box.right + 0.5) problems.push(`${el.textContent} spills ${Math.round(r.left)}–${Math.round(r.right)} past ${Math.round(box.left)}–${Math.round(box.right)}`);
        if (!el.classList.contains('figure-flag')) sizes.push(parseFloat(getComputedStyle(el).fontSize));
      }
      for (const amount of cell.querySelectorAll('.figure-button[data-size="lg"] > .amount, :scope > .amount')) {
        const text = [...amount.childNodes].filter(node => node.nodeType === Node.TEXT_NODE).pop();
        if (!text) continue;
        const range = document.createRange(), space = text.data.lastIndexOf(' ');
        range.setStart(text, 0); range.setEnd(text, space > 0 ? space : text.data.length);
        if (new Set([...range.getClientRects()].filter(r => r.width).map(r => Math.round(r.top))).size > 1) problems.push(`${text.data} splits its digits`);
      }
    }
    if (sizes.length && Math.max(...sizes) - Math.min(...sizes) > 0.5) problems.push(`${selector} mixes sizes ${sizes}`);
  }
  return problems;
}"""
_LENGTHEN = """([selector, text]) => {
  for (const row of document.querySelectorAll(selector)) {
    const amount = row.querySelector('.figure-tile > .figure-button[data-size="lg"] > .amount, .figure-tile > .amount, '
      + '.plan-figure > .figure-button > .amount, .plan-figure > .amount');
    if (!amount) continue;
    for (const node of [...amount.childNodes]) if (!node.classList?.contains('visually-hidden')) node.remove();
    amount.append(text);
  }
}"""


def assert_tiles_fit(page, row_selector, long_text="+1,155,707.53 USD"):
    """Every row of figure tiles (or plan headline) matching `row_selector` fits its figures as shown, and again with its
    first figure's amount replaced by `long_text`. The page is left with the long amounts; reload it to undo."""
    assert page.locator(row_selector).count(), row_selector
    assert page.evaluate(_FIGURES_MISFIT, row_selector) == []
    page.evaluate(_LENGTHEN, [row_selector, long_text])
    assert page.evaluate(_FIGURES_MISFIT, row_selector) == []


def assert_tiles_fit_beside_ask(page, row_selector, widths=(1180, 1440)):
    """assert_tiles_fit at each width, with Ask's column open (Control+J) and then closed."""
    from playwright.sync_api import expect
    for width in widths:
        page.set_viewport_size({"width": width, "height": 900})
        page.keyboard.press("Control+j")
        expect(page.locator("#assistant-panel")).to_be_visible()
        assert_tiles_fit(page, row_selector)
        page.keyboard.press("Control+j")
        expect(page.locator("#assistant-panel")).to_be_hidden()
        assert_tiles_fit(page, row_selector)


@pytest.fixture(autouse=True)
def no_tailnet(monkeypatch):
    """Tests never listen on this computer's real Tailscale address: the family hub stays off unless a test builds a
    Manager with hub_loopback=True (tests/test_family_hub.py)."""
    from home_manager.app import family_hub
    monkeypatch.setattr(family_hub, "tailnet_address", lambda: None)


@pytest.fixture
def local_model():
    state, stop = start_model_server()
    try:
        yield state
    finally:
        stop()
