"""Tools for the item-resolution agent (docs/household-items.md).

One ItemTools instance serves one receipt line. The shape mirrors gpt-oss's trained browsing
tool (search, open, find). Its only write is a proposal, which the user reviews. Search queries
may name the merchant and the printed item text or code; any amount, date, long number or place
from the receipt is refused before a request is made. Pages open only by result ID.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .items import CATEGORIES, ItemLedger, ResolutionFields, normalize_text, valid_gtin
from .web_lookup import LookupFailed, WebLookup

MAX_SEARCHES, MAX_OPENS, MAX_QUERY_CHARS = 3, 3, 120
MAX_FIND_MATCHES, FIND_CONTEXT_CHARS = 5, 300
PRICE = re.compile(r"\d+[.,]\d{2}\b|[$€£¥₹]")
DATE = re.compile(r"\b\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}\b")
# Standalone numbers of four or more digits (card digits, years, store numbers); sizes such as 1000ML are fine.
LONG_NUMBER = re.compile(r"(?<![A-Za-z0-9])\d{4,}(?![A-Za-z0-9])")


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EmptyInput(ToolInput):
    pass


class CodeInput(ToolInput):
    code: str = Field(pattern=r"^\d{8,14}$")


class SearchInput(ToolInput):
    query: str = Field(min_length=2, max_length=MAX_QUERY_CHARS, description="Merchant name plus the printed item text or code. No prices, dates or places.")


class OpenInput(ToolInput):
    result_id: str = Field(pattern=r"^r\d{1,3}$")


class FindInput(ToolInput):
    result_id: str = Field(pattern=r"^r\d{1,3}$")
    pattern: str = Field(min_length=2, max_length=80, description="Plain words to look for in the opened page; not a regular expression.")


class ProposeInput(ResolutionFields):
    model_config = ConfigDict(extra="forbid", strict=True)
    confidence: Literal["low", "medium", "high"]
    source_ids: list[str] = Field(max_length=5, description="Result IDs (r1, r2...) or 'barcode' that support the name. Empty if none.")


class ItemTools:
    def __init__(self, ledger: ItemLedger, web: WebLookup, line_id, run_id=None):
        self.ledger, self.web, self.line_id, self.run_id = ledger, web, line_id, run_id
        self.results, self.pages, self.searches, self.opens = {}, {}, 0, 0
        self.proposal = None
        line = ledger.line(line_id)
        self.merchant, self.code = line["merchant"], line["product_code"]
        self._private = self._private_text(line["receipt_id"])

    def _private_text(self, receipt_id):
        """Words from the receipt that must never leave the device: its location."""
        with self.ledger.store.connection() as db:
            row = db.execute("SELECT location FROM receipts WHERE id=?", (receipt_id,)).fetchone()
        location = normalize_text(row["location"] if row else "")
        return {location} if location and location != "ONLINE" else set()

    def get_receipt_line(self, _=None):
        line = self.ledger.line(self.line_id)
        with self.ledger.store.connection() as db:
            neighbours = [row[0] for row in db.execute("SELECT description FROM receipt_items WHERE receipt_id=? AND position BETWEEN ? AND ? AND id<>? "
                                                       "ORDER BY position", (line["receipt_id"], line["position"] - 2, line["position"] + 2, line["id"]))]
        return {"printed_text": line["description"], "product_code": line["product_code"], "quantity": line["quantity"],
                "merchant": line["merchant"], "neighbouring_lines": neighbours}

    def find_similar_lines(self, _=None):
        return {"approved_products": self.ledger.similar(self.line_id)}

    def lookup_barcode(self, value: CodeInput):
        if not valid_gtin(value.code):
            raise ValueError("The check digit does not validate; this is not a UPC/EAN barcode.")
        product = self.web.barcode(value.code)
        return {"product": product} if product else {"product": None, "note": "Not listed in Open Food Facts."}

    def check_query(self, query):
        text = normalize_text(query)
        if PRICE.search(query) or DATE.search(query):
            raise ValueError("Queries may not contain prices or dates.")
        allowed = {self.code} if self.code else set()
        if any(number not in allowed for number in LONG_NUMBER.findall(query)):
            raise ValueError("Queries may contain only the printed product code as a long number.")
        if any(place and place in text for place in self._private):
            raise ValueError("Queries may not contain the store location.")

    def web_search(self, value: SearchInput):
        if self.searches >= MAX_SEARCHES:
            raise ValueError(f"The search limit for this line ({MAX_SEARCHES}) is reached. Propose from what you have, or finish.")
        self.check_query(value.query)
        self.searches += 1
        results = []
        for item in self.web.search(value.query):
            result_id = f"r{len(self.results) + 1}"
            self.results[result_id] = item
            results.append({"result_id": result_id, "title": item["title"], "snippet": item["snippet"], "site": item["url"].split("/")[2]})
        return {"results": results}

    def open_result(self, value: OpenInput):
        if value.result_id not in self.results:
            raise ValueError("Unknown result ID. Use an ID from a web_search result.")
        if value.result_id not in self.pages:
            if self.opens >= MAX_OPENS:
                raise ValueError(f"The page limit for this line ({MAX_OPENS}) is reached.")
            self.opens += 1
            self.pages[value.result_id] = self.web.page(self.results[value.result_id]["url"])
        page = self.pages[value.result_id]
        return {"result_id": value.result_id, "title": page["title"], "text_start": page["text"][:1500], "length": len(page["text"])}

    def find_in_page(self, value: FindInput):
        if value.result_id not in self.pages:
            raise ValueError("Open the result with open_result first.")
        text, words = self.pages[value.result_id]["text"], value.pattern.lower().split()
        lower, matches, start = text.lower(), [], 0
        while len(matches) < MAX_FIND_MATCHES:
            index = lower.find(words[0], start)
            if index < 0:
                break
            passage = text[max(0, index - FIND_CONTEXT_CHARS // 2): index + FIND_CONTEXT_CHARS // 2]
            if all(word in passage.lower() for word in words):
                matches.append(" ".join(passage.split()))
            start = index + len(words[0])
        return {"matches": matches}

    def propose_item_resolution(self, value: ProposeInput):
        unknown = [source for source in value.source_ids if source != "barcode" and source not in self.results]
        if unknown:
            raise ValueError(f"Unknown sources: {', '.join(unknown)}. Cite result IDs from this line's searches.")
        sources = [{"id": source, **({"title": self.results[source]["title"], "url": self.results[source]["url"]} if source in self.results else {})}
                   for source in value.source_ids]
        fields = ResolutionFields(**value.model_dump(exclude={"confidence", "source_ids"}))
        self.proposal = self.ledger.propose(self.line_id, fields, "search", value.confidence, sources, self.run_id)
        return {"proposal_id": self.proposal["id"], "status": "sent to the user for review"}


# name -> (input model, method, description shown to the model)
TOOLS = {
    "get_receipt_line": (EmptyInput, "get_receipt_line", "The printed line, its product code and quantity, the merchant, and nearby lines."),
    "find_similar_lines": (EmptyInput, "find_similar_lines", "Products the user already approved whose printed text shares words with this line."),
    "lookup_barcode": (CodeInput, "lookup_barcode", "Look up a printed UPC/EAN in Open Food Facts."),
    "web_search": (SearchInput, "web_search", f"Search the web. At most {MAX_SEARCHES} per line."),
    "open_result": (OpenInput, "open_result", f"Open a search result by its ID. At most {MAX_OPENS} per line."),
    "find_in_page": (FindInput, "find_in_page", "Find passages containing all of these words in an opened result."),
    "propose_item_resolution": (ProposeInput, "propose_item_resolution", "Send your answer to the user for review. Ends the work on this line."),
}
ItemToolName = Literal[*TOOLS]
CATEGORY_LIST = ", ".join(CATEGORIES)


def call_item_tool(tools, name, arguments):
    model, method, _ = TOOLS[name]
    try:
        return getattr(tools, method)(model.model_validate(arguments or {}))
    except LookupFailed as exc:
        raise ValueError(str(exc)) from exc
