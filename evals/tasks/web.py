"""Recorded web for the web-agent evals (docs/evals.md): the agents' real tool loops against fixed pages, offline.

A case's web is a list of search results and the HTML of each result's page. Every search answers with the case's
results, ranked by how many of the query's words they share, so an agent's own wording of a query never changes what
exists to be found. Pages not recorded answer 404. There is no pacing delay and no network: the fetch never leaves
this process. The pages are synthetic; tax figures in them are made up, not any year's real ones.
"""

from contextlib import contextmanager
import json
from pathlib import Path
import re
import tempfile
from urllib.parse import parse_qs, urlsplit

from home_manager.finance.ledger import Ledger
from home_manager.household.items import ItemLedger, ResolutionFields
from home_manager.library.scanner import ScanLimits, Scanner
from home_manager.library.storage import Store
from home_manager.models.web_lookup import BRAVE_SEARCH, WebLookup

WORD = re.compile(r"[a-z0-9]+")


def html(title, *paragraphs):
    return f"<html><head><title>{title}</title></head><body>" + "".join(f"<p>{text}</p>" for text in paragraphs) + "</body></html>"


class Replay:
    """A fetch for WebLookup that serves one case's recorded results and pages."""

    def __init__(self, results, pages):
        self.results, self.pages, self.requests = results, pages, []

    def __call__(self, url, headers=None):
        self.requests.append(url)
        if url.startswith(BRAVE_SEARCH):
            words = set(WORD.findall(parse_qs(urlsplit(url).query).get("q", [""])[0].lower()))
            ranked = sorted(self.results, key=lambda item: -len(words & set(WORD.findall((item["title"] + " " + item["description"]).lower()))))
            return 200, "application/json", json.dumps({"web": {"results": ranked}}).encode(), url
        if url in self.pages:
            return 200, "text/html; charset=utf-8", self.pages[url].encode(), url
        return 404, "text/html", b"", url


class ReplayLookup(WebLookup):
    def _paced(self, url, headers=None):
        return self.fetch(url, headers)  # Recorded pages: no rate limit to respect.


def lookup(store, web):
    """A WebLookup over a case's recorded web: {"results": [{title, url, description}], "pages": {url: html}}."""
    return ReplayLookup(store, Replay(web["results"], web["pages"]), key="replay")


@contextmanager
def scratch_store():
    """A throwaway library, deleted afterwards."""
    with tempfile.TemporaryDirectory(prefix="hm-eval-web-") as folder:
        store = Store(Path(folder) / "managed")
        try:
            yield store
        finally:
            store.close()


def bought(store, merchant, description, cost, day="2026-03-14", location="Springfield"):
    """A confirmed one-line receipt. Returns the receipt line's ID."""
    (store.library.inbox / "receipt.png").write_bytes(f"synthetic receipt {merchant} {description}".encode())
    Scanner(store, ScanLimits(stability_seconds=0)).run(store.create_job())
    document = store.documents()["items"][0]
    record = {"merchant": merchant, "purchase_date": day, "subtotal_minor": None, "tax_minor": None, "tip_minor": None, "total_minor": cost,
              "currency": "USD", "issues": [], "location": location,
              "items": [{"description": description, "product_code": None, "quantity": "1", "unit_price_minor": cost, "line_total_minor": cost,
                         "discount_minor": None, "locator": {"line_ids": ["line-2"]}}], "locator": {"line_ids": ["line-1"]}}
    receipt_id = Ledger(store).publish_receipt(record, {"document_id": document["id"], "blob_hash": document["current_hash"],
                                                        "source_key": "eval", "run_id": "eval"}, "verified")["id"]
    return ItemLedger(store).lines(receipt_id)[0]["id"]


def owned(store, merchant, description, cost, fields, day="2026-03-14"):
    """An identified, confirmed item the household owns. Returns its inventory lot ID."""
    items = ItemLedger(store)
    line_id = bought(store, merchant, description, cost, day)
    items.review(items.propose(line_id, ResolutionFields(**fields), "search", "high")["id"], "verified")
    return next(lot["id"] for lot in items.inventory(include_closed=True) if lot["receipt_id"] == items.line(line_id)["receipt_id"])
