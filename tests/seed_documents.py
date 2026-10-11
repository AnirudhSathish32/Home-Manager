"""Synthetic documents that are read and recorded, for the document page and To check (browser tests and
.claude/skills/ui-redesign/scripts/ui_shots.py). Each is a drawn image read by the fake vision model and recorded by the
fake reasoning model (tests/model_server.py), the way test_extraction.py does it, on the app's own manager."""

from contextlib import contextmanager
from datetime import date, timedelta
import socket
import threading
import time

import uvicorn

from conftest import inbox_scan
from home_manager.app.api import create_app
from home_manager.documents.grouping import Groups
from home_manager.documents.reasoning import ReasoningConfig
from home_manager.household.items import ItemLedger, ResolutionFields
from home_manager.household.tax_tables import TaxTables
from home_manager.household.warranty import Warranties
from home_manager.library.scanner import ScanLimits
from model_server import start_model_server
from test_extraction import MISSING, cite, value
from test_receipts import make_receipt


def _read_and_record(manager, model, name, lines, outputs):
    """Draw lines into Library/Inbox/name, then capture it: the fake vision model reads it and, with a reasoning model
    set, it is recorded from outputs. Returns the document's id."""
    make_receipt(manager.store.library.inbox / name, lines)
    model["outputs"] = [{"full_text": "\n".join(lines)}, *outputs]
    manager.start_inbox()
    manager.future.result(timeout=60)
    return next(doc["id"] for doc in manager.store.documents()["items"] if doc["relative_path"].replace("\\", "/").rsplit("/", 1)[-1] == name)


def _models(manager, model):
    """The fake models, and the household's settings kept (model_copy keeps ui_v2_screens) with item lookups off."""
    manager.configure_vision(model["config"])
    manager.configure_reasoning(ReasoningConfig(base_url=model["config"].base_url, model="synthetic-reasoning"))
    manager.configure_household(manager.household.model_copy(update={"auto_identify_items": False}))


def _record_id(manager, table, doc_id):
    with manager.store.connection() as db:
        row = db.execute(f"SELECT id FROM {table} WHERE document_id=? ORDER BY id DESC LIMIT 1", (doc_id,)).fetchone()
    assert row, f"the {table[:-1]} wasn't recorded"
    return row[0]


def seed_read_receipt(manager, model, needs_review=False):
    """A grocery receipt read and recorded; with needs_review its printed total isn't its subtotal plus tax, so the
    arithmetic check sends it to review. Returns {doc_id, record_id}."""
    _models(manager, model)
    day = (date.today() - timedelta(days=2)).isoformat()
    if needs_review:
        name, merchant, total = "hardware-depot.png", "HARDWARE DEPOT", "63.42"
        items = [("HAMMER", "30.00", "home improvement"), ("NAILS", "20.00", "home improvement")]
    else:
        name, merchant, total = "fresh-market.png", "FRESH MARKET", "52.00"
        items = [("EGGS", "18.00", "groceries"), ("BREAD", "12.00", "groceries"), ("SOAP", "20.00", "household supplies")]
    lines = [merchant, day, "USD", "Subtotal 50.00", "Tax 2.00", f"Total {total}", *[f"{item} 1 @ {price} {price}" for item, price, _ in items]]
    shown = merchant.title()
    summary = {"merchant": value(shown, 1, merchant), "purchase_date": value(day, 2), "currency": value("USD", 3),
               "subtotal": value("50.00", 4, lines[3]), "tax": value("2.00", 5, lines[4]), "tip": MISSING, "total": value(total, 6, lines[5])}
    outputs = [{"document_type": "receipt", "evidence": cite(1, merchant), "issuer": value(shown, 1, merchant), "document_date": value(day, 2)},
               summary, {"seller": value(shown, 1, merchant), "seller_basis": "printed", "location": MISSING},
               {"items": [{"description": item, "product_code": None, "quantity": "1", "unit_price": price, "line_total": price, "discount": None,
                           "taxed": None, "evidence": cite(number, lines[number - 1])} for number, (item, price, _) in enumerate(items, 7)]},
               {"description": "groceries" if not needs_review else "tools", "category": items[0][2], "recurrence": None,
                "item_categories": [category for _, _, category in items]},
               {"rewards": []}]
    doc_id = _read_and_record(manager, model, name, lines, outputs)
    return {"doc_id": doc_id, "record_id": _record_id(manager, "receipts", doc_id)}


def seed_statement(manager, model):
    """Last month's bank statement with three rows, read and recorded; its balances reconcile. Returns {doc_id, record_id}."""
    _models(manager, model)
    end = date.today().replace(day=1) - timedelta(days=1)
    start = end.replace(day=1)
    rows = [(start + timedelta(days=4), "CORNER BOOKS", "25.00", True), (start + timedelta(days=9), "PAYROLL ACME", "500.00", False),
            (start + timedelta(days=14), "CITY WATER", "45.00", True)]
    lines = ["FIRST LOCAL BANK", "Checking account 000123454821", f"Statement period {start} to {end}", "Currency USD", "Opening balance 1,000.00",
             *[f"{day} {text} {'-' if debit else '+'}{amount}" for day, text, amount, debit in rows], "Closing balance 1,430.00"]
    summary = {"institution": value("First Local Bank", 1, "FIRST LOCAL BANK"), "account_reference": value("4821", 2, "000123454821"),
               "period_start": value(start.isoformat(), 3), "period_end": value(end.isoformat(), 3), "currency": value("USD", 4, "Currency USD"),
               "opening_balance": value("1,000.00", 5, lines[4]), "closing_balance": value("1,430.00", 9, lines[8])}
    outputs = [{"document_type": "bank_statement", "evidence": cite(1, "FIRST LOCAL BANK"), "issuer": value("First Local Bank", 1, "FIRST LOCAL BANK"),
                "document_date": value(end.isoformat(), 3)},
               summary,
               {"transactions": [{"posted_date": day.isoformat(), "transaction_date": None, "description": text, "amount": amount,
                                  "direction": "debit" if debit else "credit", "evidence": cite(number, lines[number - 1])}
                                 for number, (day, text, amount, debit) in enumerate(rows, 6)]}]
    doc_id = _read_and_record(manager, model, "bank-statement.png", lines, outputs)
    return {"doc_id": doc_id, "record_id": _record_id(manager, "statements", doc_id)}


def seed_documents(manager, model):
    """The three documents the document page's states need: a recorded receipt, one that needs review, and a statement.
    Returns the ids ui_shots.py's --routes placeholders name."""
    receipt = seed_read_receipt(manager, model)
    review = seed_read_receipt(manager, model, needs_review=True)
    statement = seed_statement(manager, model)
    return {"receipt_doc": receipt["doc_id"], "receipt_record": receipt["record_id"], "review_doc": review["doc_id"],
            "review_record": review["record_id"], "statement_doc": statement["doc_id"], "statement_record": statement["record_id"]}


def seed_review_items(manager, ids):
    """One of each To check kind the documents don't make (review_v2.js): a product to identify on the recorded
    receipt's soap line, a warranty found online for its bread line approved as a toaster, a tax table, and two images
    that look like one document. Returns their ids."""
    items = ItemLedger(manager.store)
    lines = {line["description"]: line for line in items.lines(ids["receipt_record"])}
    item = items.propose(lines["SOAP"]["id"], ResolutionFields(name="Dish Soap", category="household cleaning", consumable=True), "search", "medium")
    toaster = items.propose(lines["BREAD"]["id"], ResolutionFields(name="Toaster", brand="Acme", category="other", consumable=False), "search", "high")
    items.review(toaster["id"], "verified")
    lot = next(lot for lot in items.inventory(include_closed=True) if lot["receipt_id"] == ids["receipt_record"])
    warranty = Warranties(manager.store).propose(lot["id"], "manufacturer", 12, False, "Support | Acme Home", "https://acme.example/warranty",
                                                 "Every Acme toaster includes a one-year limited warranty")
    # Head of household, so it never meets the single table other seeding confirms (test_taxes_browser.seed_tax_year).
    table = TaxTables(manager.store).propose("US", date.today().year, "head_of_household",
                                             {"standard_deduction_minor": 1500000, "brackets": [{"from_minor": 0, "rate_bp": 1000}, {"from_minor": 1192500, "rate_bp": 1200}]},
                                             [{"url": "https://irs.example/brackets", "quote": "10% on taxable income up to $11,925"}])
    for name, text in (("porch-left.png", "PORCH PART A"), ("porch-right.png", "PORCH PART B")):
        make_receipt(manager.store.library.inbox / name, [text])
    inbox_scan(manager.store)
    pages = [next(doc["id"] for doc in manager.store.documents()["items"] if doc["relative_path"].endswith(name)) for name in ("porch-left.png", "porch-right.png")]
    group = Groups(manager.store).create(pages, status="proposed", reason="Saved together and numbered in one series.")
    return {"item_resolution": item["id"], "warranty": warranty["id"], "tax_table": table["id"], "group": group}


@contextmanager
def document_server(tmp_path, token, routes=(), review_items=False):
    """The app on a free port with seed_documents' documents (and seed_review_items' when asked) and the redesigned
    routes turned on. Yields (base, ids, manager)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = create_app(tmp_path / "control", token, port, ScanLimits(stability_seconds=0))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    model, stop = start_model_server()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        assert server.started
        manager = app.state.manager
        manager.configure(str(tmp_path / "managed"))
        # Captured before any model is set, so it stays unread.
        make_receipt(tmp_path / "unread.png", ["CORNER CAFE", "Total 4.50"])
        inbox_scan(manager.store, {"unread.png": (tmp_path / "unread.png").read_bytes()})
        unread = next(doc["id"] for doc in manager.store.documents()["items"] if doc["relative_path"].endswith("unread.png"))
        ids = {**seed_documents(manager, model), "unread_doc": unread}
        if review_items:
            ids.update(seed_review_items(manager, ids))
        if routes:
            manager.configure_household(manager.household.model_copy(update={"ui_v2_screens": list(routes)}))
        yield f"http://127.0.0.1:{port}", ids, manager
    finally:
        stop()
        server.should_exit = True
        thread.join(timeout=10)
