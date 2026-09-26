"""Phase 5: classifier, type-specific extraction, deterministic validation and publication."""

from decimal import Decimal
import json
import threading
import time

import pytest

from home_manager.finance import HouseholdConfig
from home_manager.manager import Manager
from home_manager.reasoning import ReasoningConfig
from home_manager.scanner import ScanLimits
from test_receipts import make_receipt

RECEIPT = ["LOCAL TEST CAFE", "2026-09-22", "USD", "Subtotal 20.00", "Tax 2.00", "Tip 3.00", "Total 25.00",
           "Returns within 14 days", "LATTE 1 @ 5.00 5.00", "LATTE 1 @ 5.00 5.00", "SANDWICH 1 @ 10.00 10.00"]


def cite(number, quote):
    return [{"line_id": f"line-{number}", "quote": quote}]


def value(text, number, quote=None):
    return {"value": text, "status": "proposed", "evidence": cite(number, quote or text)}


MISSING = {"value": None, "status": "missing", "evidence": []}


def classification(kind="receipt"):
    if kind == "receipt":
        return {"document_type": kind, "evidence": cite(1, RECEIPT[0]), "issuer": value("LOCAL TEST CAFE", 1), "document_date": value("2026-09-22", 2)}
    return {"document_type": kind, "evidence": cite(1, "FIRST LOCAL BANK"), "issuer": value("First Local Bank", 1, "FIRST LOCAL BANK"),
            "document_date": value("2026-08-31", 3)}


def receipt_summary(**changes):
    summary = {"merchant": value("Local Test Cafe", 1, "LOCAL TEST CAFE"), "purchase_date": value("2026-09-22", 2),
               "currency": value("USD", 3), "subtotal": value("20.00", 4, "Subtotal 20.00"), "tax": value("2.00", 5, "Tax 2.00"),
               "tip": value("3.00", 6, "Tip 3.00"), "total": value("25.00", 7, "Total 25.00")}
    return {**summary, **changes}


def identity(seller=None, basis="printed", location=None):
    """The seller-and-location answer; defaults to the printed merchant and no location."""
    return {"seller": seller or value("Local Test Cafe", 1, "LOCAL TEST CAFE"), "seller_basis": basis, "location": location or MISSING}


def receipt_items():
    return {"items": [{"description": name, "product_code": None, "quantity": "1", "unit_price": price, "line_total": price,
                       "discount": None, "evidence": cite(number, RECEIPT[number - 1])}
                      for number, name, price in [(9, "LATTE", "5.00"), (10, "LATTE", "5.00"), (11, "SANDWICH", "10.00")]]}


def transcribe(tmp_path, local_model, lines):
    manager = Manager(tmp_path / "control", ScanLimits(stability_seconds=0))
    manager.configure(str(tmp_path / "managed"))
    month = manager.store.library.inbox
    make_receipt(month / "document.png")
    local_model["output"] = {"full_text": "\n".join(lines)}
    manager.configure_vision(local_model["config"])
    manager.start_inbox()
    manager.future.result(timeout=30)
    # Set after capture, so Inbox's automatic ledger extraction does not run and each step is tested on its own.
    manager.configure_reasoning(ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning"))
    manager.configure_household(HouseholdConfig(auto_identify_items=False))  # Item identification is tested in test_warranties.
    doc = manager.store.documents()["items"][0]
    parse_id = manager.receipts.history(doc["id"])[0]["id"]
    assert manager.receipts.get(parse_id)["status"] == "succeeded"
    return manager, doc, parse_id


def extract(manager, doc, parse_id, force=False):
    run_id = manager.start_extraction(doc["id"], parse_id, force)["run_id"]
    manager.future.result(timeout=30)
    return manager.extractions.get(run_id)


@pytest.fixture
def receipt(tmp_path, local_model):
    manager, doc, parse_id = transcribe(tmp_path, local_model, RECEIPT)
    try:
        yield manager, doc, parse_id
    finally:
        manager.close()


def test_receipt_extraction_publishes_exact_evidence_linked_records_and_files(receipt, local_model):
    manager, doc, parse_id = receipt
    local_model["outputs"] = [classification(), receipt_summary(), identity(), receipt_items(), {"description": "coffee & lunch"}]
    run = extract(manager, doc, parse_id)
    assert run["status"] == "succeeded", run["error"]
    # Every automatic check passes (arithmetic, cited amounts, merchant and date), so the record counts without review.
    assert run["publication"]["status"] == "published" and run["publication"]["review_status"] == "verified"
    record = manager.ledger.record("receipt", run["publication"]["id"])
    assert (record["subtotal_minor"], record["tax_minor"], record["tip_minor"], record["total_minor"]) == (2000, 200, 300, 2500)
    assert record["currency"] == "USD" and record["merchant"] == "Local Test Cafe" and record["issues"] == []
    assert [(item["description"], item["line_total_minor"]) for item in record["items"]] == [("LATTE", 500), ("LATTE", 500), ("SANDWICH", 1000)]
    assert record["evidence"][0]["parse_run_id"] == parse_id and "line-7" in record["evidence"][0]["locator"]["line_ids"]
    # Smallest schemas, separate bounded calls; no image ever reaches the text model.
    requests = local_model["requests"][1:]
    assert [request["response_format"]["json_schema"]["name"] for request in requests] == ["Classification", "ReceiptSummary", "ReceiptIdentity", "Items", "PurchaseDescription"]
    assert [request["max_tokens"] for request in requests] == [1024, 2048, 1024, 8192, 512]
    assert "image_url" not in json.dumps(requests)
    assert [row["task"] for row in manager.store.model_runs(run["id"])] == ["extraction"] * 5
    filed = manager.store.documents()["items"][0]
    assert filed["folder"] == "Receipts" and "2026-09-22__Local_Test_Cafe__Receipts" in filed["managed_path"]
    # The title is Merchant - Location - Description; date, amount and type have their own columns.
    assert (filed["title"], filed["description_source"], filed["merchant"], filed["document_date"]) == ("Local Test Cafe - Coffee & lunch", "model", "Local Test Cafe", "2026-09-22")
    assert filed["ledger_amount"] == "25.00 USD" and filed["ledger_status"] == "verified"
    assert (record["review_source"], manager.store.folders()["work"]["needs_review"]) == ("automatic", 0)
    store = manager.store
    assert [len(store.documents(status=name)["items"]) for name in ("needs_text", "ready_for_ledger", "needs_review", "failed")] == [0, 0, 0, 0]
    assert store.documents(query="cafe")["total"] == 1 and store.documents(query="100%_x")["total"] == 0
    assert store.folders()["work"] == {"needs_text": 0, "ready_for_ledger": 0, "needs_review": 0, "failed": 0}


def test_missing_summary_merchant_falls_back_to_the_cited_classifier_issuer(receipt, local_model):
    manager, doc, parse_id = receipt
    local_model["outputs"] = [classification(), receipt_summary(merchant=MISSING), identity(seller=MISSING), receipt_items()]
    run = extract(manager, doc, parse_id)
    record = manager.ledger.record("receipt", run["publication"]["id"])
    assert record["merchant"] == "LOCAL TEST CAFE" and record["review_status"] == "verified"
    assert run["result"]["normalized"]["notes"] == ["The merchant or issuer was taken from the document classification."]
    assert manager.start_extraction(doc["id"], parse_id) == {"run_id": run["id"], "reused": True}
    manager.future.result(timeout=10)


def test_arithmetic_mismatch_needs_review_and_reviewed_records_are_never_overwritten(receipt, local_model):
    manager, doc, parse_id = receipt
    local_model["outputs"] = [classification(), receipt_summary(tip=MISSING), identity(), receipt_items()]
    run = extract(manager, doc, parse_id)
    receipt_id = run["publication"]["id"]
    record = manager.ledger.record("receipt", receipt_id)
    assert record["review_status"] == "needs_review"
    assert record["issues"] == ["Subtotal, tax and tip (22.00 USD) do not equal the total (25.00 USD)."]
    manager.ledger.review("receipt", receipt_id, "verified", "Tip was cash.")
    local_model["outputs"] = [classification(), receipt_summary(), identity(), receipt_items()]
    again = extract(manager, doc, parse_id, force=True)
    assert again["publication"]["status"] == "kept_reviewed"
    record = manager.ledger.record("receipt", receipt_id)
    assert record["review_status"] == "verified" and record["tip_minor"] is None
    assert all(item["review_status"] == "verified" for item in record["items"])


def test_hallucinated_amount_is_rejected_after_one_correction_and_nothing_is_published(receipt, local_model):
    manager, doc, parse_id = receipt
    invented = receipt_summary(total=value("26.00", 7, "Total 25.00"))  # Not printed in its citation.
    local_model["outputs"] = [classification(), invented, invented]
    run = extract(manager, doc, parse_id)
    assert run["status"] == "failed" and run["publication"] is None
    assert "total: the amount is not printed in its cited evidence" in run["error"]
    assert "26.00" not in run["error"]
    with manager.store.connection() as db:
        assert db.execute("SELECT count(*) FROM receipts").fetchone()[0] == 0
    correction = local_model["requests"][-1]["messages"][-1]["content"]
    assert "total: the amount is not printed" in correction and "Total 25.00" not in correction


@pytest.mark.parametrize("currency_text,expected", [("", "USD"), ("$", "USD"), ("EUR", None), ("£", None)])
def test_receipt_defaults_to_usd_without_currency_but_respects_foreign_evidence(tmp_path, local_model, currency_text, expected):
    lines = [*RECEIPT]
    lines[2] = currency_text or "Thank you"
    manager, doc, parse_id = transcribe(tmp_path, local_model, lines)
    try:
        local_model["outputs"] = [classification(), receipt_summary(currency=MISSING), identity(), receipt_items(), {"description": "Lunch"}]
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded", run["error"]
        if expected:
            record = manager.ledger.record("receipt", run["publication"]["id"])
            assert (record["currency"], record["total_minor"], record["review_status"]) == ("USD", 2500, "verified")
            assert "assumed to be USD" in run["result"]["normalized"]["notes"][0]
        else:
            assert run["publication"]["status"] == "blocked"
    finally:
        manager.close()


def test_unknown_or_uncited_classifications_never_publish_or_choose_folders(receipt, local_model):
    manager, doc, parse_id = receipt
    unknown = {"document_type": "unknown", "evidence": [], "issuer": MISSING, "document_date": MISSING}
    local_model["outputs"] = [unknown]
    run = extract(manager, doc, parse_id)
    assert run["status"] == "succeeded" and run["publication"] is None and len(local_model["requests"]) == 2
    assert manager.store.documents()["items"][0]["folder"] == "Unfiled"
    # A merchant the cited line does not mention (e.g. injected path text) is never used: after one
    # correction it is dropped, the record needs review, and no folder or filename is derived from it.
    hostile = receipt_summary(merchant=value(r"..\..\Windows System32", 1, "LOCAL TEST CAFE"))
    local_model["outputs"] = [classification(), hostile, hostile, identity(seller=MISSING), receipt_items()]
    run = extract(manager, doc, parse_id, force=True)
    assert run["status"] == "succeeded" and run["publication"]["review_status"] == "needs_review"
    record = manager.ledger.record("receipt", run["publication"]["id"])
    assert record["merchant"] == "LOCAL TEST CAFE" and record["total_minor"] == 2500  # Cited classifier issuer, never the injected text.
    assert record["issues"] == ["Merchant was not used: the name does not appear in its cited evidence. Check it against the document."]
    assert "Windows" not in local_model["requests"][-2]["messages"][-1]["content"]  # Correction feedback never echoes values.
    filed = manager.store.documents()["items"][0]  # Filed by the classifier's cited issuer instead.
    assert filed["folder"] == "Receipts" and "LOCAL_TEST_CAFE" in filed["managed_path"] and "Windows" not in filed["managed_path"]


def test_real_model_quirks_quotes_split_taxes_brand_footer_and_home_currency(tmp_path, local_model):
    """Patterns seen with a real local model on store receipts that print only $ and a city header."""
    lines = ["Milton - 770-225-1780", "09/19/2026 04:54 PM", "GROCERY BF $8.99", "211010107 Bitchin'",
             "STATIONERY & OFFICE SUPPLIES T $3.89", "085035655 Command", "SUBTOTAL $12.88", "T = GA TAX 3.75000 on $8.99 $0.34",
             "B = GA TAX 7.75000 on $3.89 $0.30", "TOTAL $13.52", "Help make your Target Run better.", "informtarget.com"]
    manager, doc, parse_id = transcribe(tmp_path, local_model, lines)
    try:
        quoted = lambda text, number, quote: {"value": text, "status": "proposed", "evidence": cite(number, f'"{quote}"')}
        summary = {"merchant": quoted("Target", 12, "informtarget.com"), "purchase_date": quoted("2026-09-19", 2, lines[1]),
                   "currency": MISSING, "subtotal": quoted("12.88", 7, lines[6]), "tip": MISSING, "total": quoted("13.52", 10, lines[9]),
                   "tax": {"value": "0.64", "status": "proposed", "evidence": cite(8, lines[7]) + cite(9, lines[8])}}  # Exact sum of two lines.
        items = {"items": [{"description": name, "product_code": code, "quantity": None, "unit_price": None, "line_total": price, "discount": None,
                            "evidence": cite(first, lines[first - 1]) + cite(first + 1, lines[first])}
                           for first, name, code, price in [(3, "Bitchin'", "211010107", "8.99"), (5, "Command", "085035655", "3.89")]]}
        target = {"document_type": "receipt", "evidence": cite(11, lines[10]), "issuer": quoted("Target", 11, lines[10]),
                  "document_date": quoted("2026-09-19", 2, lines[1])}
        # The seller is printed only in the footer; the city in the header is the store's location, not the merchant.
        where = {"seller": quoted("Target", 12, "informtarget.com"), "seller_basis": "printed", "location": quoted("Milton", 1, lines[0])}
        local_model["outputs"] = [target, summary, where, items, {"description": "Snacks/Office"}]
        defaulted = extract(manager, doc, parse_id)
        assert defaulted["status"] == "succeeded", defaulted["error"]
        assert defaulted["publication"]["status"] == "published"
        manager.configure_household(manager.household.model_copy(update={"home_currency": "USD"}))
        local_model["outputs"] = [target, summary, where, items, {"description": "Snacks/Office"}]
        run = extract(manager, doc, parse_id)
        assert run["id"] != defaulted["id"]  # The home currency is part of the reuse key.
        record = manager.ledger.record("receipt", run["publication"]["id"])
        assert (record["merchant"], record["purchase_date"], record["review_status"], record["issues"]) == ("Target", "2026-09-19", "verified", [])
        assert (record["subtotal_minor"], record["tax_minor"], record["total_minor"]) == (1288, 64, 1352)
        assert [(item["description"], item["line_total_minor"]) for item in record["items"]] == [("Bitchin'", 899), ("Command", 389)]
        assert record["evidence"][0]["locator"]["quotes"][0] == "informtarget.com"  # Wrapping quote marks removed.
        assert run["result"]["normalized"]["notes"] == ["No currency code is printed; the $ amounts were read as your home currency (USD)."]
        assert manager.store.documents()["items"][0]["folder"] == "Receipts"
        assert manager.store.documents()["items"][0]["title"] == "Target - Milton - Snacks/Office"
        with pytest.raises(ValueError):
            manager.configure_household(manager.household.model_validate({"home_currency": "XYZ"}))
    finally:
        manager.close()


def test_cancelled_extraction_publishes_nothing(receipt, local_model):
    manager, doc, parse_id = receipt
    local_model["outputs"] = [classification(), receipt_summary(), identity(), receipt_items()]
    local_model["response_gate"] = threading.Event()
    run_id = manager.start_extraction(doc["id"], parse_id)["run_id"]
    for _ in range(100):
        if len(local_model["requests"]) == 2:
            break
        time.sleep(.05)
    manager.cancel()
    manager.future.result(timeout=10)
    local_model["response_gate"].set()
    assert manager.extractions.get(run_id)["status"] == "cancelled"
    with manager.store.connection() as db:
        assert db.execute("SELECT count(*) FROM receipts").fetchone()[0] == 0


def statement_lines(missing=None):
    rows, balance = [], Decimal("1000.00")
    for index in range(1, 101):
        amount = Decimal(index) + Decimal("0.25")
        debit = index % 5 != 0
        balance += -amount if debit else amount
        rows.append((index, f"2026-08-{index % 28 + 1:02d} MERCHANT {index:03d} {'-' if debit else '+'}{amount}", f"{amount}", debit))
    header = ["FIRST LOCAL BANK", "Checking account 000123454821", "Statement period 2026-08-01 to 2026-08-31", "Currency USD", "Opening balance 1,000.00"]
    lines = header + [row[1] for row in rows] + [f"Closing balance {balance:,.2f}"]
    summary = {"institution": value("First Local Bank", 1, "FIRST LOCAL BANK"), "account_reference": value("4821", 2, "000123454821"),
               "period_start": value("2026-08-01", 3), "period_end": value("2026-08-31", 3), "currency": value("USD", 4, "Currency USD"),
               "opening_balance": value("1,000.00", 5, "Opening balance 1,000.00"),
               "closing_balance": value(f"{balance:,.2f}", 106, lines[-1])}

    def transactions(start, stop):
        return {"transactions": [{"posted_date": text.split()[0], "transaction_date": None, "description": f"MERCHANT {index:03d}",
                                  "amount": amount, "direction": "debit" if debit else "credit", "evidence": cite(index + 5, text)}
                                 for index, text, amount, debit in rows[start:stop] if index != missing]}
    return lines, summary, transactions


def test_long_statement_is_chunked_reconciled_and_only_failed_chunks_retry(tmp_path, local_model):
    lines, summary, transactions = statement_lines()
    manager, doc, parse_id = transcribe(tmp_path, local_model, lines)
    try:
        broken = transactions(75, 100)
        broken["transactions"][0]["evidence"] = cite(999, "invented")
        local_model["outputs"] = [classification("bank_statement"), summary, transactions(0, 75), broken, transactions(75, 100)]
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded", run["error"]
        requests = local_model["requests"][1:]
        sent = [len(json.loads(request["messages"][1]["content"])["lines"]) for request in requests]
        assert sent == [80, 66, 80, 26, 26]  # Summary: first/last lines; rows: two chunks; only chunk 2 retried.
        publication = run["publication"]
        assert publication["status"] == "published" and publication["review_status"] == "verified"  # Balances reconcile.
        assert (publication["inserted"], publication["duplicates"]) == (100, 0)
        statement = manager.ledger.record("statement", publication["id"])
        assert statement["issues"] == [] and len(statement["transactions"]) == 100
        account = manager.ledger.account(statement["account_id"])
        assert (account["institution"], account["account_last_four"], account["account_type"]) == ("First Local Bank", "4821", "checking")
        assert "000123454821" not in json.dumps(manager.ledger.accounts())
        assert sum(row["amount_minor"] for row in statement["transactions"]) == statement["closing_balance_minor"] - statement["opening_balance_minor"]
        # A re-extraction that drops a row fails the deterministic arithmetic check and replaces stale unreviewed rows.
        _, summary, transactions = statement_lines(missing=42)
        local_model["outputs"] = [classification("bank_statement"), summary, transactions(0, 75), transactions(75, 100)]
        run = extract(manager, doc, parse_id, force=True)
        statement = manager.ledger.record("statement", run["publication"]["id"])
        assert statement["review_status"] == "needs_review" and len(statement["transactions"]) == 99
        assert "Statement arithmetic does not reconcile" in statement["issues"][0]
    finally:
        manager.close()


@pytest.mark.parametrize("address,street", [
    ("123 Main St W, Milton, ON L9T 2M3", "Main St W"),
    ("Milton, ON L9T 2M3", None),
])
def test_receipt_street_location_reaches_document_title(tmp_path, local_model, address, street):
    manager, doc, parse_id = transcribe(tmp_path, local_model, [*RECEIPT, address])
    try:
        local_model["outputs"] = [classification(), receipt_summary(),
                                  identity(location=value(street, 12, address) if street else MISSING),
                                  receipt_items(), {"description": "Lunch"}]
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded", run["error"]
        record = manager.ledger.record("receipt", run["publication"]["id"])
        assert record["location"] == street
        expected = "Local Test Cafe - Main St W - Lunch" if street else "Local Test Cafe - Lunch"
        assert manager.store.document(doc["id"])["title"] == expected
        prompt = local_model["requests"][3]["messages"][0]["content"]
        assert "only the street name" in prompt
        assert "Never substitute a city or postal code" in prompt
    finally:
        manager.close()


def test_the_seller_and_location_question_names_the_store_and_online_orders(receipt, local_model):
    manager, doc, parse_id = receipt
    # A printed seller replaces a header that took a place for the merchant.
    local_model["outputs"] = [classification(), receipt_summary(merchant=value("Returns within 14 days", 8)),
                              identity(location=value("Test Cafe", 1, "LOCAL TEST CAFE")), receipt_items(), {"description": "Snacks/Office"}]
    run = extract(manager, doc, parse_id)
    record = manager.ledger.record("receipt", run["publication"]["id"])
    assert (record["merchant"], record["location"], record["review_status"]) == ("Local Test Cafe", "Test Cafe", "verified")
    assert manager.store.document(doc["id"])["title"] == "Local Test Cafe - Test Cafe - Snacks/Office"
    names = [request["response_format"]["json_schema"]["name"] for request in local_model["requests"][1:]]
    assert names == ["Classification", "ReceiptSummary", "ReceiptIdentity", "Items", "PurchaseDescription"]
    assert "never the store's location" in local_model["requests"][3]["messages"][0]["content"]


def test_an_inferred_seller_is_used_and_flagged_and_online_needs_delivery_evidence(receipt, local_model):
    manager, doc, parse_id = receipt
    # Online must cite a delivery or order line; "Tip 3.00" is neither, so the location is dropped without failing anything.
    local_model["outputs"] = [classification(), receipt_summary(), identity(seller=value("The Home Depot", 8, "Returns within 14 days"), basis="inferred",
                                                                           location=value("Online", 6, "Tip 3.00")), receipt_items(), {"description": "Bed frame"}]
    run = extract(manager, doc, parse_id)
    receipt_id = run["publication"]["id"]
    record = manager.ledger.record("receipt", receipt_id)
    assert (record["merchant"], record["location"], record["review_status"]) == ("The Home Depot", None, "needs_review")
    assert record["issues"] == ["Merchant The Home Depot was inferred from “Returns within 14 days”, not printed; confirm it with Edit details."]
    assert manager.store.document(doc["id"])["title"] == "The Home Depot - Bed frame"
    # Confirming the merchant clears the flag; a location the user enters becomes part of the title.
    record = manager.ledger.correct("receipt", receipt_id, {"merchant": "The Home Depot", "location": "Online"})
    assert (record["review_status"], record["issues"]) == ("verified", [])
    assert manager.store.document(doc["id"])["title"] == "The Home Depot - Online - Bed frame"
    # An inferred seller that does not look like a business name is never used.
    local_model["outputs"] = [classification(), receipt_summary(), identity(seller=value(r"..\Windows", 8, "Returns within 14 days"), basis="inferred",
                                                                           location=value("Online", 8, "Returns within 14 days")), receipt_items(), {"description": "Bed frame"}]
    run = extract(manager, doc, parse_id, force=True)
    assert run["result"]["identity"] == {"location": None, "seller_inferred_from": None}


def test_descriptions_are_short_plain_labels_and_the_users_own_wins(receipt, local_model):
    from home_manager.extraction import clean_description
    assert [clean_description(text, "Local Test Cafe") for text in ("Snacks & toiletries.", "bed frame", "Take-out")] == ["Snacks & toiletries", "Bed frame", "Take-out"]
    # Amounts, dates, the merchant, the document type and long phrases are never titles.
    assert [clean_description(text, "Local Test Cafe") for text in ("$30 snacks", "09/21 run", "Local Test Cafe lunch", "Grocery receipt",
                                                                     "Snacks, toiletries, office supplies", "")] == [None] * 6
    manager, doc, parse_id = receipt
    local_model["outputs"] = [classification(), receipt_summary(), identity(), receipt_items(), {"description": "Receipt from Local Test Cafe 2026"}]
    run = extract(manager, doc, parse_id)
    assert run["result"]["description"] is None
    store = manager.store
    assert (store.document(doc["id"])["title"], store.document(doc["id"])["description_source"]) == ("Local Test Cafe", None)
    named = store.set_description(doc["id"], "  Weekend   treats ")
    assert (named["title"], named["description_source"]) == ("Local Test Cafe - Weekend treats", "user")
    assert store.documents(query="weekend")["total"] == 1 and store.documents(query="test cafe")["total"] == 1
    with pytest.raises(ValueError, match="60 characters"):
        store.set_description(doc["id"], "x" * 61)
    assert store.set_description(doc["id"], None)["description_source"] is None
    with pytest.raises(ValueError, match="not found"):
        store.set_description(9999, "Anything")


def test_user_corrections_fill_unprinted_dates_survive_re_extraction_and_are_audited(receipt, local_model):
    manager, doc, parse_id = receipt
    unclear_date = {"value": None, "status": "ambiguous", "evidence": []}
    local_model["outputs"] = [classification(), receipt_summary(purchase_date=unclear_date), identity(), receipt_items(), {"description": "Coffee"}]
    run = extract(manager, doc, parse_id)
    receipt_id = run["publication"]["id"]
    assert manager.ledger.record("receipt", receipt_id)["issues"] == ["Purchase date is ambiguous in the document."]
    for changes, message in (({"purchase_date": "Sep 24"}, "full date"), ({"purchase_date": "2026-02-30"}, "full date"),
                             ({"total": "1.00"}, "fields this record allows"), ({}, "fields this record allows")):
        with pytest.raises(ValueError, match=message):
            manager.ledger.correct("receipt", receipt_id, changes)
    result = manager.correct_record("receipt", receipt_id, {"purchase_date": "2026-09-24", "merchant": "Local Test Café"})
    record = result["record"]
    assert (record["purchase_date"], record["merchant"], record["issues"], record["review_status"]) == ("2026-09-24", "Local Test Café", [], "verified")
    assert [(item["field"], item["previous"], item["value"]) for item in record["corrections"]] == [
        ("purchase_date", None, "2026-09-24"), ("merchant", "Local Test Cafe", "Local Test Café")]
    assert any(item["source_key"].startswith("user:correction:") and item["locator"] == {"entered_by_user": ["merchant", "purchase_date"]} for item in record["evidence"])
    assert manager.reconciler.history()[0]["trigger"] == "correction"
    assert manager.store.document(doc["id"])["document_date"] == "2026-09-24"
    # A later extraction rewrites the model's values; the user's corrections are applied again on top.
    local_model["outputs"] = [classification(), receipt_summary(purchase_date=unclear_date), identity(), receipt_items(), {"description": "Coffee"}]
    again = extract(manager, doc, parse_id, force=True)
    assert again["publication"]["status"] == "published"
    record = manager.ledger.record("receipt", receipt_id)
    assert (record["purchase_date"], record["merchant"], record["issues"]) == ("2026-09-24", "Local Test Café", [])


def test_counting_a_flagged_record_anyway_records_the_warnings_and_undo_restores_them(receipt, local_model):
    manager, doc, parse_id = receipt
    local_model["outputs"] = [classification(), receipt_summary(tip=MISSING), identity(), receipt_items()]
    receipt_id = extract(manager, doc, parse_id)["publication"]["id"]
    warning = "Subtotal, tax and tip (22.00 USD) do not equal the total (25.00 USD)."
    manager.ledger.review("receipt", receipt_id, "verified")
    record = manager.ledger.record("receipt", receipt_id)
    assert (record["review_status"], record["review_source"]) == ("verified", "user")
    assert record["review_history"][-1]["note"] == f"Counted despite: {warning}"
    manager.ledger.review("receipt", receipt_id, "needs_review")  # Undo: the warnings are still there to act on.
    assert manager.ledger.record("receipt", receipt_id)["issues"] == [warning]


def test_descriptions_never_repeat_the_merchant_or_location_already_in_the_title(receipt, local_model):
    from home_manager.extraction import clean_description
    assert [clean_description(text, "The Home Depot", "Online") for text in ("Home Depot", "Online order", "Bed frame", "Home goods")] == [
        None, None, "Bed frame", "Home goods"]
    assert [clean_description(text, "Target", "Milton") for text in ("Target run", "Milton", "Snacks/Office")] == [None, None, "Snacks/Office"]
    manager, doc, parse_id = receipt
    local_model["outputs"] = [classification(), receipt_summary(), identity(location=value("Test Cafe", 1, "LOCAL TEST CAFE")), receipt_items(),
                              {"description": "Local Test Cafe"}]
    run = extract(manager, doc, parse_id)
    assert run["result"]["description"] is None
    # The model is told the seller and location so it does not echo them.
    asked = json.loads(local_model["requests"][-1]["messages"][1]["content"])
    assert (asked["seller"], asked["location"]) == ("Local Test Cafe", "Test Cafe")
    store = manager.store
    assert store.document(doc["id"])["title"] == "Local Test Cafe - Test Cafe"
    # A duplicate saved before this check existed is left out of the title; the user's own words are kept as written.
    with store.connection() as db:
        db.execute("UPDATE receipts SET description='Local Test Cafe' WHERE id=?", (run["publication"]["id"],))
    assert store.document(doc["id"])["title"] == "Local Test Cafe - Test Cafe"
    assert store.set_description(doc["id"], "Test Cafe treats")["title"] == "Local Test Cafe - Test Cafe - Test Cafe treats"
