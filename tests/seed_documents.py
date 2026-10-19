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
    """The fake models, and the household's settings kept with item lookups off."""
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


def seed_bill(manager, model):
    """A phone bill due three days ago, read by line and recorded (docs/money.md "Bills and their lines"): a line for one
    person, an Apple TV+ add-on and the taxes, with a past-due balance in the amount due. Returns {doc_id, record_id}."""
    _models(manager, model)
    due = date.today() - timedelta(days=3)
    issued = due - timedelta(days=21)
    lines = ["ACME WIRELESS", "Account 0000 4821", f"Bill date {issued}", f"Due {due}", "Alex 555-201-1111 Unlimited 40.00", "Apple TV+ 9.99",
             "Taxes and fees 18.00", "Past due 12.00", "New charges 67.99", "Amount due USD 79.99"]
    header = {"provider": value("ACME WIRELESS", 1), "account_reference": value("4821", 2, lines[1]), "issue_date": value(issued.isoformat(), 3),
              "due_date": value(due.isoformat(), 4), "period_start": MISSING, "period_end": MISSING, "amount_due": value("79.99", 10, lines[9]),
              "new_charges": value("67.99", 9, lines[8]), "currency": value("USD", 10, "USD")}
    rows = [{"description": "Unlimited", "amount": "40.00", "category": "phone & internet", "line_kind": "service", "line_holder": "Alex 555-201-1111",
             "evidence": cite(5, lines[4])},
            {"description": "Apple TV+", "amount": "9.99", "category": "subscriptions", "line_kind": "subscription", "line_holder": None, "evidence": cite(6, lines[5])},
            {"description": "Taxes and fees", "amount": "18.00", "category": None, "line_kind": "tax_fee", "line_holder": None, "evidence": cite(7, lines[6])}]
    outputs = [{"document_type": "bill", "evidence": cite(1, "ACME WIRELESS"), "issuer": value("ACME WIRELESS", 1), "document_date": MISSING},
               header, {"line_items": rows}]
    doc_id = _read_and_record(manager, model, "acme-wireless.png", lines, outputs)
    return {"doc_id": doc_id, "record_id": _record_id(manager, "receipts", doc_id)}


def seed_paystub(manager, model):
    """A pay stub whose current and year-to-date amounts were confused, for correcting on the document page."""
    _models(manager, model)
    lines = ["ACME PAY", "Pay date 2026-09-15", "USD", "Description | This period | Year to date",
             "Regular pay | 52000.00 | 52000.00", "Gross pay | 52000.00 | 52000.00", "Net pay | 40000.00 | 40000.00"]
    summary = {"payer_or_employer": value("Acme", 1, lines[0]), "pay_date": value("2026-09-15", 2, lines[1]),
               "period_start": MISSING, "period_end": MISSING, "pay_frequency": MISSING, "work_state": MISSING,
               "gross_pay": value("52000.00", 6, lines[5]), "gross_pay_ytd": value("52000.00", 6, lines[5]),
               "net_pay": value("40000.00", 7, lines[6]), "net_pay_ytd": value("40000.00", 7, lines[6]),
               "taxes": MISSING, "deductions": MISSING, "currency": value("USD", 3)}
    outputs = [{"document_type": "paystub", "evidence": cite(1, lines[0]), "issuer": value("Acme", 1, lines[0]),
                "document_date": value("2026-09-15", 2, lines[1])}, summary, {"lines": []},
               {"lines": [{"description": "Regular pay", "group": "earnings", "category": "regular_pay",
                           "evidence": cite(5, lines[4])}]}]
    doc_id = _read_and_record(manager, model, "editable-stub.png", lines, outputs)
    return {"doc_id": doc_id, "record_id": _record_id(manager, "income_records", doc_id)}


def seed_document_forms(manager, model):
    """The document-forms records (specs/document-forms SC-14): SC-01's fuel receipt, SC-04's grocery receipt, SC-21's
    pay stub (fixture P-table) and the SC-22 and SC-23 statements, each read and recorded. The fake model is left ready
    to read the fuel receipt as dining, for a kind change. Returns their document and record ids."""
    from document_forms_fixtures import BANK, CARD, GROCERY, bank_replies, card_replies, fuel, fuel_replies, grocery_replies, p_table, record_document
    from test_paystub_forms import p_details, p_table_replies
    from test_receipt_kinds import read_as
    _models(manager, model)
    stub, tables = p_table()
    found = {}
    for name, lines, replies, extra in (("fuel", fuel(), fuel_replies(fuel()), None), ("grocery", GROCERY, grocery_replies(), None),
                                        ("paystub", stub, p_table_replies(stub, hours="80.00", rate="31.25", **p_details(stub)), tables),
                                        ("bank", BANK, bank_replies(BANK), None), ("card", CARD, card_replies(CARD), None)):
        doc, _, run = record_document(manager, model, f"forms-{name}.png", lines, replies, extra)
        found[f"{name}_doc"], found[f"{name}_record"] = doc["id"], run["publication"]["id"]
    model["by_schema"] = read_as(fuel(), "dining")
    return found


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
    # Head of household, so it never meets the single table other seeding confirms (seed_taxes.seed_tax_year).
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
def document_server(tmp_path, token, review_items=False, paystub=False, forms=False):
    """The app on a free port with seed_documents' documents (and seed_review_items', seed_paystub's or
    seed_document_forms' when asked). Yields (base, ids, manager)."""
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
        if paystub:
            stub = seed_paystub(manager, model)
            ids.update(paystub_doc=stub["doc_id"], paystub_record=stub["record_id"])
        if forms:
            ids.update({f"forms_{key}": value for key, value in seed_document_forms(manager, model).items()})
        yield f"http://127.0.0.1:{port}", ids, manager
    finally:
        stop()
        server.should_exit = True
        thread.join(timeout=10)
