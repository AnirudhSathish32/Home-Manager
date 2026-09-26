"""Read-only product lookup connectors: Brave web search, Open Food Facts barcodes, result pages.

The only network access item resolution has. Callers pass a validated query or barcode, never a
URL: pages are fetched only from URLs a search returned. Every request is HTTPS to a public
address (checked after DNS resolution and again on each redirect, and connected to that exact
address), bounded in time and size, and paced. Nothing the model writes reaches a request
except the query text, which the item tools check for receipt amounts, dates and places first.
"""

from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import http.client
import ipaddress
import json
import os
import socket
import ssl
import threading
import time
from urllib.parse import quote, urlencode, urljoin, urlsplit

from .storage import now

BRAVE_SEARCH = "https://api.search.brave.com/res/v1/web/search"
OPEN_FOOD_FACTS = "https://world.openfoodfacts.org/api/v2/product/{code}.json?fields=product_name,brands,quantity,categories_tags"
# The key lives in the environment (or Windows credential storage later), never in settings files, prompts or logs.
BRAVE_KEY_VARIABLE = "HOME_MANAGER_BRAVE_API_KEY"
USER_AGENT = "HomeManager/0.1 (personal household records; read-only)"
MAX_REDIRECTS, TIMEOUT_SECONDS, MAX_RESPONSE_BYTES = 5, 10, 1_000_000
MAX_PAGE_CHARS, RESULTS_PER_SEARCH = 200_000, 5
CACHE_DAYS, MIN_REQUEST_GAP = 30, 1.0


class LookupFailed(ValueError):
    """A lookup that failed for a reason the model and the user may see."""


def public_address(host):
    """Resolve and return one public IP for host, refusing loopback, private, link-local and reserved ranges."""
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise LookupFailed("The address could not be resolved.") from exc
    addresses = [ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos]
    if not addresses or not all(address.is_global for address in addresses):
        raise LookupFailed("Refused: the page is not on a public address.")
    return str(addresses[0])


def https_get(url, headers=None):
    """GET one URL: HTTPS, public address, pinned to the checked IP, bounded, following at most five redirects."""
    for _ in range(MAX_REDIRECTS + 1):
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise LookupFailed("Refused: only plain https:// addresses are fetched.")
        address = public_address(parts.hostname)
        port = parts.port or 443
        context = ssl.create_default_context()  # Windows certificate store, so TLS inspection by local antivirus still verifies.
        connection = http.client.HTTPSConnection(parts.hostname, port, timeout=TIMEOUT_SECONDS, context=context)
        try:
            # Connect to the address that was checked, not a second resolution of the name.
            raw = socket.create_connection((address, port), timeout=TIMEOUT_SECONDS)
            connection.sock = context.wrap_socket(raw, server_hostname=parts.hostname)
            path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
            connection.request("GET", path, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity", **(headers or {})})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308) and response.getheader("Location"):
                url = urljoin(url, response.getheader("Location"))
                continue
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise LookupFailed("Refused: the response is larger than 1 MB.")
            return response.status, response.getheader("Content-Type") or "", body, url
        except (OSError, http.client.HTTPException) as exc:
            raise LookupFailed(f"The request failed ({type(exc).__name__}).") from exc
        finally:
            connection.close()
    raise LookupFailed("Refused: too many redirects.")


class TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "svg", "head"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.depth, self.title, self._in_title = [], 0, "", False

    def handle_starttag(self, tag, attrs):
        self.depth += tag in self.SKIP
        self._in_title = tag == "title"

    def handle_endtag(self, tag):
        self.depth -= tag in self.SKIP and self.depth > 0
        self._in_title = False
        if tag in ("p", "div", "li", "tr", "h1", "h2", "h3", "h4", "br", "section", "article"):
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.depth:
            self.parts.append(data)


def page_text(body: bytes, content_type: str):
    charset = content_type.split("charset=")[-1].split(";")[0].strip() if "charset=" in content_type else "utf-8"
    try:
        text = body.decode(charset, errors="replace")
    except LookupError:
        text = body.decode("utf-8", errors="replace")
    if "html" not in content_type.lower():
        return "", text[:MAX_PAGE_CHARS]
    parser = TextExtractor()
    parser.feed(text)
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return " ".join(parser.title.split())[:200], "\n".join(line for line in lines if line)[:MAX_PAGE_CHARS]


class WebLookup:
    def __init__(self, store, fetch=https_get, key=None):
        self.store, self.fetch = store, fetch
        self._key = key
        self._lock, self._last = threading.Lock(), 0.0

    def key(self):
        return self._key if self._key is not None else os.environ.get(BRAVE_KEY_VARIABLE, "")

    def _paced(self, url, headers=None):
        with self._lock:
            wait = self._last + MIN_REQUEST_GAP - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                return self.fetch(url, headers)
            finally:
                self._last = time.monotonic()

    def search(self, query):
        """Titles, URLs and snippets for a query. Cached by exact query for 30 days."""
        key = " ".join(query.split()).lower()
        with self.store.connection() as db:
            row = db.execute("SELECT results_json,fetched_at FROM web_search_cache WHERE query=?", (key,)).fetchone()
        if row and datetime.fromisoformat(row["fetched_at"]) > datetime.now(timezone.utc) - timedelta(days=CACHE_DAYS):
            return json.loads(row["results_json"])
        if not self.key():
            raise LookupFailed(f"Web search is not configured. Set {BRAVE_KEY_VARIABLE} to a Brave Search API key.")
        status, _, body, _ = self._paced(f"{BRAVE_SEARCH}?{urlencode({'q': query, 'count': RESULTS_PER_SEARCH, 'safesearch': 'strict'})}",
                                         {"Accept": "application/json", "X-Subscription-Token": self.key()})
        if status == 429:
            raise LookupFailed("The search quota or rate limit was reached. Try again later.")
        if status != 200:
            raise LookupFailed(f"Search failed with HTTP {status}.")
        try:
            items = json.loads(body).get("web", {}).get("results", [])
            results = [{"title": str(item.get("title", ""))[:200], "url": str(item["url"]), "snippet": str(item.get("description", ""))[:500]}
                       for item in items[:RESULTS_PER_SEARCH] if str(item.get("url", "")).startswith("https://")]
        except (ValueError, AttributeError, KeyError, TypeError) as exc:
            raise LookupFailed("The search response was not in the expected format.") from exc
        with self.store.connection() as db:
            db.execute("INSERT OR REPLACE INTO web_search_cache(query,results_json,fetched_at) VALUES(?,?,?)", (key, json.dumps(results), now()))
        return results

    def barcode(self, code):
        """Open Food Facts product for a validated GTIN, or None when it is not listed."""
        status, _, body, _ = self._paced(OPEN_FOOD_FACTS.format(code=quote(code)), {"Accept": "application/json"})
        if status == 404:
            return None
        if status != 200:
            raise LookupFailed(f"Barcode lookup failed with HTTP {status}.")
        try:
            value = json.loads(body)
            product = value.get("product") if value.get("status") == 1 else None
        except (ValueError, AttributeError) as exc:
            raise LookupFailed("The barcode response was not in the expected format.") from exc
        if not product or not product.get("product_name"):
            return None
        return {"name": str(product["product_name"])[:160], "brand": str(product.get("brands") or "").split(",")[0].strip()[:80] or None,
                "size_text": str(product.get("quantity") or "")[:40] or None,
                "categories": [str(tag).split(":")[-1] for tag in (product.get("categories_tags") or [])[:8]], "source": "openfoodfacts.org"}

    def page(self, url):
        status, content_type, body, final_url = self._paced(url)
        if status != 200:
            raise LookupFailed(f"The page returned HTTP {status}.")
        title, text = page_text(body, content_type)
        return {"url": final_url, "title": title, "text": text}
