"""Synthetic fixtures for specs/dining-receipt-indent: the breakfast receipt, its vision answer, the reasoning stubs B0 – B11
and the paths of the baseline captures.

Lines are exactly as specs/dining-receipt-indent/test-contract.md prints them ("The breakfast receipt", "Stubs").
Line numbers are 1-based, as the transcription's line ids are (line-1, line-2, …). Stubs answer by json_schema name through
local_model["by_schema"] (tests/model_server.py), so a test never depends on the order of model calls.

Baseline captures (test contract, "Baseline captures"; D28): tests/dining_receipt_data/ holds what today's application
code produced for the breakfast receipt with stub B0, before any application change of this feature:

  r6_result.json, p3_result.json, g2_result.json   the stored result_json of the image (R6, receipt-vision-v6-tables),
                                                  one-page scanned PDF (P3, pdf-pages-v3-layout) and two-image combined
                                                  document (G2, receipt-images-v2-tables) parse runs, byte for byte
  q56_r6.json, q56_p3.json, q56_g2.json            every reasoning request body of the extraction run (typed-extraction-
                                                  v56-money-sign-rule) that local_model["requests"] recorded, in order
  row_instruction_v56.txt                          today's receipt row instruction (extraction.py, the `direction` text of
                                                  a dining receipt)

They were written by `CAPTURE_DINING_BASELINE=1 .venv/bin/python -m pytest tests/test_dining_baseline_capture.py -q`
at commit 7980943 (src/ identical to 2676e51 and a8542d8). Never regenerate them with changed code: a later test compares
the new code's output with these files.
"""

import json
from pathlib import Path

from home_manager.finance.ledger import normalize_name

DATA = Path(__file__).parent / "dining_receipt_data"
CAPTURES = {
    "result": {"R6": DATA / "r6_result.json", "P3": DATA / "p3_result.json", "G2": DATA / "g2_result.json"},
    "requests": {"R6": DATA / "q56_r6.json", "P3": DATA / "q56_p3.json", "G2": DATA / "q56_g2.json"},
    "row_instruction": DATA / "row_instruction_v56.txt",
}

# The breakfast receipt: (text, indent) per line.
BREAKFAST = [
    ("Gacha's Breakfast Bar", 0), ("12 Peach St", 0), ("Order #: 179580", 0), ("Server: Crimson H", 0),
    ("Date: 11/12/26, 10:31 AM", 0), ("Amount: $52.76", 0), ("Bottled Water $3.95", 0), ("Bottled Water $3.95", 0),
    ("Coffee $14.95", 0), ("Georgia Peach Stack $18.70", 0), ("No Allergies", 1), ("Fresh Berry Pancakes", 1),
    ("Veggie Sausage", 1), ("Jalapeno Cheese Grits", 1), ("Better Than No Y'all Biscuits (3) $7.30", 0),
    ("No Allergies", 1), ("Total Item Count: 6", 0), ("Subtotal: $48.85", 0), ("Total Tax: $3.91", 0),
    ("Total: $52.76", 0), ("Paid With: VISA CARDHOLDER", 0), ("Bill: $52.76", 0), ("Total: $61.55", 0),
    ("Tip: $", 0), ("Suggested Tip", 0), ("18.00% of sale: $8.79 Total $61.55", 0),
    ("20.00% of sale: $9.77 Total $62.53", 0), ("22.00% of sale: $10.75 Total $63.51", 0),
]
BREAKFAST_TEXTS = [text for text, _ in BREAKFAST]
BREAKFAST_INDENTS = [indent for _, indent in BREAKFAST]


def vision_lines(texts, indents=None, tables=None):
    """A v7 vision answer: {"lines": [{"text", "indent"}], "tables"?}. indents: one per line (default 0 on every line); an
    entry of None leaves the key out, the way a model that gave no indent does (D25)."""
    indents = [0] * len(texts) if indents is None else indents
    lines = [{"text": text} if indent is None else {"text": text, "indent": indent} for text, indent in zip(texts, indents)]
    return {"lines": lines, **({"tables": tables} if tables is not None else {})}


def old_vision_text(texts, tables=None):
    """Today's (v6) vision answer, {"full_text": …}: what the baseline captures were read from."""
    return {"full_text": "\n".join(texts), **({"tables": tables} if tables is not None else {})}


def dump_requests(requests):
    """The bytes a q56_*.json capture holds for a list of request bodies; the one way to write or compare them."""
    return json.dumps(requests, indent=2, ensure_ascii=False) + "\n"


# Line ids ---------------------------------------------------------------------------------------------------

def image_id(number):
    """The id of line number in an image reading (R6)."""
    return f"line-{number}"


def pdf_id(number):
    """The id of line number in a one-page PDF reading (P3)."""
    return f"page-1-line-{number}"


# G2 reads breakfast lines 1 – GROUP_SPLIT on page 1 and the rest on page 2.
GROUP_SPLIT = 20


def group_id(number):
    """The id of line number in a two-image combined reading (G2)."""
    return f"page-1-line-{number}" if number <= GROUP_SPLIT else f"page-2-line-{number - GROUP_SPLIT}"


# Stub building ------------------------------------------------------------------------------------------------

MISSING = {"value": None, "status": "missing", "evidence": []}


def find(texts, text, nth=0):
    """The 1-based number of the nth line (from 0) that is exactly text."""
    found = [number for number, line in enumerate(texts, 1) if line == text]
    assert len(found) > nth, f"{text!r} is on {len(found)} lines"
    return found[nth]


def cites(texts, number, id_of, quote=None):
    return [{"line_id": id_of(number), "quote": texts[number - 1] if quote is None else quote}]


def proposed(texts, number, id_of, text, quote=None):
    return {"value": text, "status": "proposed", "evidence": cites(texts, number, id_of, text if quote is None else quote)}


def row(texts, number, id_of, description, line_total):
    return {"description": description, "product_code": None, "quantity": None, "unit_price": None, "line_total": line_total,
            "discount": None, "taxed": None, "evidence": cites(texts, number, id_of)}


def stub_replies(texts, id_of, *, summary, rows, categories, kind="dining", merchant_line=1, date_line=5, kind_line=4,
                 merchant="Gacha's Breakfast Bar", date="2026-11-12", date_quote="11/12/26", form=None, rows_schema="Items",
                 starts=1):
    """Every reply a receipt reading asks for, keyed by schema name. summary: the form's fields beyond merchant and date
    (each a Value); rows: the item rows; categories: the receipt's category and one per row."""
    form = form or {"dining": "ReceiptDiningSummary", "grocery": "ReceiptGrocerySummary"}[kind]
    head = {"merchant": proposed(texts, merchant_line, id_of, merchant, texts[merchant_line - 1]),
            "purchase_date": proposed(texts, date_line, id_of, date, date_quote),
            "currency": MISSING, "subtotal": MISSING, "tax": MISSING, "tip": MISSING, "total": MISSING}
    classified = {"document_type": "receipt", "evidence": cites(texts, merchant_line, id_of),
                  "issuer": proposed(texts, merchant_line, id_of, merchant, texts[merchant_line - 1]),
                  "document_date": proposed(texts, date_line, id_of, date, date_quote),
                  "receipt_kind": kind, "receipt_kind_evidence": cites(texts, kind_line, id_of)}
    if form == "ReceiptGrocerySummary":
        head = {**head, "savings_total": MISSING, "tenders": []}  # The grocery form asks for both.
    return {"Classification": [classified], form: [{**head, **summary}],
            "ReceiptIdentity": [{"seller": proposed(texts, merchant_line, id_of, merchant, texts[merchant_line - 1]),
                                 "seller_basis": "printed", "location": MISSING}],
            rows_schema: [{"items": rows}],
            "PurchaseDescription": [{"description": None, "category": categories[0], "recurrence": None, "item_categories": categories[1:]}],
            "Rewards": [{"rewards": []}], "ReceiptStarts": [{"starts": cites(texts, starts, id_of)}]}


def amount(texts, number, id_of, text=None):
    """A proposed amount: text (default: the amount after the last $ on the line), cited by itself."""
    return proposed(texts, number, id_of, text or texts[number - 1].rsplit("$", 1)[1].strip())


# (description, the line's text, which line of that text, line_total)
BREAKFAST_ROWS = [("Bottled Water", "Bottled Water $3.95", 0, "3.95"), ("Bottled Water", "Bottled Water $3.95", 1, "3.95"),
                  ("Coffee", "Coffee $14.95", 0, "14.95"), ("Georgia Peach Stack", "Georgia Peach Stack $18.70", 0, "18.70"),
                  ("Better Than No Y'all Biscuits", "Better Than No Y'all Biscuits (3) $7.30", 0, "7.30")]
BREAKFAST_CATEGORIES = ["dining", "groceries", "groceries", "dining", "dining", "dining"]
SIDE_LINES = [("No Allergies", 11), ("Fresh Berry Pancakes", 12), ("Veggie Sausage", 13), ("Jalapeno Cheese Grits", 14)]


def breakfast_stub(name="B0", id_of=image_id):
    """(texts, indents, replies) for stub B0 – B10 of the contract. The texts change for B4, B4e, B5, B5n, B5a, B9 and B10
    (the contract's line changes); the replies answer by line text, so their citations follow."""
    texts, indents = list(BREAKFAST_TEXTS), list(BREAKFAST_INDENTS)

    def drop(*numbers):
        nonlocal texts, indents
        keep = [index for index in range(len(texts)) if index + 1 not in numbers]
        texts, indents = [texts[index] for index in keep], [indents[index] for index in keep]

    if name in ("B4", "B4e"):
        texts, indents = texts[:22] + ["Tip: $", "Total: $52.76" if name == "B4e" else "Total: $"], indents[:22] + [0, 0]
    elif name == "B5":
        drop(23)
    elif name == "B5n":
        drop(6, 20, 22, 23)
    elif name == "B5a":
        drop(20, 22, 23)
    elif name == "B9":
        texts[21] = "Bill: $50.00"
    elif name == "B10":
        drop(24)
    summary = {"subtotal": amount(texts, find(texts, "Subtotal: $48.85"), id_of), "tax": amount(texts, find(texts, "Total Tax: $3.91"), id_of),
               "server": proposed(texts, find(texts, "Server: Crimson H"), id_of, "Crimson H")}
    if name in ("B5", "B5n", "B5a"):
        table = find(texts, "18.00% of sale: $8.79 Total $61.55")
        summary["total"] = proposed(texts, table, id_of, "61.55", "$61.55")
    elif name == "B1":
        summary["total"] = amount(texts, find(texts, "Total: $61.55"), id_of)
    else:
        summary["total"] = amount(texts, find(texts, "Total: $52.76"), id_of)
    if name == "B2":
        texts[23] = "Tip: $8.79"
        summary["tip"] = amount(texts, 24, id_of)
    elif name == "B3":
        texts[23] = "Tip: $5.00"
        summary["tip"] = amount(texts, 24, id_of)
    rows = [row(texts, find(texts, text, nth), id_of, description, total) for description, text, nth, total in BREAKFAST_ROWS]
    replies = stub_replies(texts, id_of, summary=summary, rows=rows, categories=BREAKFAST_CATEGORIES)
    return texts, indents, replies


def side_line_stub(zero=False, id_of=image_id):
    """B6 (B6z with zero): B0 with the four side lines published as items, each citing its own line."""
    texts, indents, replies = breakfast_stub("B0", id_of)
    extra = [row(texts, number, id_of, description, "0.00" if zero else None) for description, number in SIDE_LINES]
    replies["Items"][0]["items"][4:4] = extra  # The side lines follow Georgia Peach Stack, as printed.
    replies["PurchaseDescription"][0]["item_categories"][4:4] = ["groceries"] * 4  # Beside their rows, so the categories stay aligned.
    return texts, indents, replies


def grocery_re_read_stub(id_of=image_id):
    """B7: B0's reading answered with the grocery form and the groceries category (SC-08)."""
    texts, indents, replies = breakfast_stub("B0", id_of)
    summary = replies.pop("ReceiptDiningSummary")[0]
    replies["ReceiptGrocerySummary"] = [{**{key: summary[key] for key in ("merchant", "purchase_date", "currency", "subtotal", "tax", "tip", "total")},
                                         "savings_total": MISSING, "tenders": []}]
    replies["GroceryItems"] = replies.pop("Items")
    replies["Classification"][0]["receipt_kind"] = "grocery"
    replies["PurchaseDescription"][0]["category"] = "groceries"
    return texts, indents, replies


# B8: a printed tip with $2.00 left over; B11: a grocery receipt for the link scenarios.
B8_TEXTS = ["SYNTH DINER", "2026-11-10", "SERVER: JO", "BURGER 20.00", "SUBTOTAL 20.00", "TAX 1.00", "TIP 3.00", "TOTAL 26.00"]
B11_TEXTS = ["SYNTH MART", "2026-11-12", "MILK 4.00", "BREAD 5.00", "SUBTOTAL 9.00", "TAX 1.00", "TOTAL 10.00", "CHANGE 7.00", "SAVED 7.70",
             "SAVED 7.69"]


def b8_stub(id_of=image_id):
    texts = B8_TEXTS
    summary = {"subtotal": proposed(texts, 5, id_of, "20.00"), "tax": proposed(texts, 6, id_of, "1.00"),
               "tip": proposed(texts, 7, id_of, "3.00"), "total": proposed(texts, 8, id_of, "26.00")}
    return texts, [0] * len(texts), stub_replies(texts, id_of, summary=summary, rows=[row(texts, 4, id_of, "Burger", "20.00")],
                                                  categories=["dining", "dining"], merchant="SYNTH DINER", merchant_line=1, date="2026-11-10",
                                                  date_line=2, date_quote="2026-11-10", kind_line=3)


def b11_stub(variant="B11", id_of=image_id):
    """B11 and its variants b, c, d, e (the summary's total and its citation) and n (total missing); g and g' add a gift card."""
    texts = list(B11_TEXTS)
    total = {"B11": (7, "10.00"), "B11b": (5, "9.00"), "B11c": (8, "7.00"), "B11d": (9, "7.70"), "B11e": (10, "7.69"),
             "B11g": (7, "10.00"), "B11g'": (5, "9.00")}.get(variant)
    summary = {"subtotal": proposed(texts, 5, id_of, "9.00"), "tax": proposed(texts, 6, id_of, "1.00"),
               "total": proposed(texts, total[0], id_of, total[1]) if total else MISSING}
    rows = [row(texts, 3, id_of, "Milk", "4.00"), row(texts, 4, id_of, "Bread", "5.00")]
    if variant in ("B11g", "B11g'"):
        texts.append("GIFT CARD -1.00")
        summary["tenders"] = [{"tender_type": "gift_card", "amount": "1.00", "last_four": None, "evidence": cites(texts, 11, id_of)}]
    replies = stub_replies(texts, id_of, kind="grocery", summary=summary, rows=rows, categories=["groceries", "groceries", "groceries"],
                           merchant="SYNTH MART", date="2026-11-12", date_quote="2026-11-12", date_line=2, kind_line=3, rows_schema="GroceryItems")
    replies.pop("ReceiptStarts")  # Nothing asks where a receipt starts in ten lines with one total.
    return texts, [0] * len(texts), replies


# The old library (contract "Old library (v56 / v6)"): receipts as the code before this feature stored them. Plain SQL on a database at the
# last schema version before the feature's migration, so nothing in it is produced by the changed code.
OLD_ITEMS = [("Bottled Water", 395), ("Bottled Water", 395), ("Coffee", 1495), ("Georgia Peach Stack", 1870), ("Better Than No Y'all Biscuits", 730)]
OLD_RECEIPTS = {
    # name: (review_source, item categories as (category, category_source) in order, total, subtotal, tax, tip, receipt category, kind)
    "A": ("automatic", [("groceries", "model"), ("groceries", "model"), ("dining", "model"), ("dining", "model"), ("dining", "model")], 5276, 4885, None, None, "dining"),
    "B": ("user", [("groceries", "model"), ("groceries", "model"), ("dining", "model"), ("dining", "model"), ("dining", "model")], 5276, 4885, None, None, "dining"),
    "C": (None, [("groceries", "user"), ("groceries", "model"), ("dining", "model"), ("dining", "model"), ("dining", "model")], 5276, 4885, None, None, "dining"),
    "D": ("user", [("groceries", "user"), ("dining", "model"), ("dining", "model"), ("dining", "model"), ("dining", "model")], 5276, 4885, None, None, "dining"),
    "E": (None, [(None, None)] * 5, 5276, 4885, None, None, "dining"),
}


def insert_old_receipts(db, names=tuple(OLD_RECEIPTS) + ("G", "H"), memory=True):
    """Insert the old receipts called names (A – E, G, H of the contract) with their items, receipt splits, a v6 parse run holding the R6 capture and a
    v56 extraction run each, and (memory) one item category memory row. Returns {name: receipt id}. Money is in minor units; every statement is plain SQL."""
    result = CAPTURES["result"]["R6"].read_text()
    ids = {}
    for number, name in enumerate(names, 1):
        digest = f"{number:x}" * 64
        db.execute("INSERT INTO blobs(hash,size,created_at) VALUES(?,1,'t')", (digest,))
        db.execute("INSERT OR IGNORE INTO jobs(id,source_root,status,created_at,updated_at) VALUES('job','root','completed','t','t')")
        document = db.execute("INSERT INTO occurrences(source_root,path_key,relative_path,current_hash,first_seen,last_seen,last_job) "
                              "VALUES('root',?,?,?,'t','t','job')", (f"{name}.png", f"{name}.png", digest)).lastrowid
        db.execute("INSERT INTO versions(occurrence_id,hash,captured_at,source_mtime_ns) VALUES(?,?,'t',0)", (document, digest))
        parse = f"parse-{name}"
        db.execute("INSERT INTO parse_runs(id,blob_hash,parser_version,options_json,status,created_at,updated_at,result_json) "
                   "VALUES(?,?,'receipt-vision-v6-tables','{}','succeeded','t','t',?)", (parse, digest, result))
        db.execute("INSERT INTO extraction_runs(id,document_id,parse_run_id,config_json,prompt_version,status,created_at,updated_at) "
                   "VALUES(?,?,?,'{}','typed-extraction-v56-money-sign-rule','succeeded','t','t')", (f"extraction-{name}", document, parse))
        if name == "G":  # A small grocery receipt: the regression control.
            receipt = db.execute("INSERT INTO receipts(document_id,blob_hash,extraction_run_id,purchase_date,subtotal_minor,tax_minor,total_minor,currency,"
                                 "review_status,review_source,category,receipt_kind,created_at,updated_at) VALUES(?,?,?,'2026-11-01',900,100,1000,'USD',"
                                 "'verified','user','groceries','grocery','t','t')", (document, digest, f"extraction-{name}")).lastrowid
            items = [("Milk", 400, "groceries", 444), ("Soap", 500, "household supplies", 556)]  # 900 + 100 tax shared by amount (allocate)
            tail = []
        elif name == "H":  # Dining, category travel before the upgrade: tip dining, the difference spread (rules 4 and 5).
            receipt = db.execute("INSERT INTO receipts(document_id,blob_hash,extraction_run_id,purchase_date,subtotal_minor,tax_minor,tip_minor,total_minor,"
                                 "currency,review_status,category,receipt_kind,created_at,updated_at) VALUES(?,?,?,'2026-11-10',2000,100,300,2600,'USD',"
                                 "'needs_review','travel','dining','t','t')", (document, digest, f"extraction-{name}")).lastrowid
            items = [("Burger", 2000, "travel", 2300)]
            tail = [("dining", 300)]
        else:
            source, categories, total, subtotal, tax, tip, category = OLD_RECEIPTS[name]
            receipt = db.execute("INSERT INTO receipts(document_id,blob_hash,extraction_run_id,purchase_date,subtotal_minor,tax_minor,tip_minor,total_minor,"
                                 "currency,review_status,review_source,category,receipt_kind,created_at,updated_at) VALUES(?,?,?,'2026-11-12',?,?,?,?,'USD',"
                                 "?,?,?,'dining','t','t')", (document, digest, f"extraction-{name}", subtotal, tax, tip, total,
                                                             "verified" if source else "needs_review", source, category)).lastrowid
            items = [(description, amount, kind[0], amount) for (description, amount), kind in zip(OLD_ITEMS, categories)]
            tail = [("dining", 391)]  # The tax today's rule 5 leaves as a no-item row when the dining receipt printed none.
        for position, (description, amount, category, share) in enumerate(items, 1):
            source = (OLD_RECEIPTS[name][1][position - 1][1] if name in OLD_RECEIPTS else "receipt" if name == "H" else "model")
            item = db.execute("INSERT INTO receipt_items(receipt_id,position,description,line_total_minor,category,category_source,review_status) "
                              "VALUES(?,?,?,?,?,?,'proposed')", (receipt, position, description, amount, category, source)).lastrowid
            db.execute("INSERT INTO category_splits(receipt_id,receipt_item_id,category,amount_minor) VALUES(?,?,?,?)", (receipt, item, category or "dining", share))
        for category, amount in tail:
            db.execute("INSERT INTO category_splits(receipt_id,category,amount_minor) VALUES(?,?,?)", (receipt, category, amount))
        ids[name] = receipt
    if memory:
        db.execute("INSERT INTO item_category_memory(merchant_key,item_key,category,updated_at) VALUES(?,?,'groceries','t')",
                   (normalize_name("Gacha's Breakfast Bar"), normalize_name("Coffee")))  # The keys as the ledger writes them.
    return ids


# A document_server seed (the browser tests): the breakfast receipt and B8, each read with its indents and recorded with its stub.
def record_dining(manager, model, name, texts, indents, replies):
    """Draw texts into the Inbox as name, read it with the fake vision model (answering lines with indents) and record it with replies:
    (document id, record id)."""
    from test_receipts import make_receipt
    make_receipt(manager.store.library.inbox / name, texts)
    model["outputs"] = [vision_lines(texts, indents)]
    model["by_schema"] = {key: list(reply) for key, reply in replies.items()}
    manager.start_inbox()
    manager.future.result(timeout=60)
    doc = next(doc for doc in manager.store.documents()["items"] if doc["relative_path"].replace("\\", "/").rsplit("/", 1)[-1] == name)
    run = manager.extractions.get(manager.extractions.history(manager.receipts.history(doc["id"])[0]["id"])[0]["id"])
    assert run["status"] == "succeeded", run["error"]
    return doc["id"], run["publication"]["id"]


def dining_seed(manager, model):
    """Household currency USD; the breakfast receipt (SC-01: Tip worked out, no left-over) and B8 (a printed tip with $2.00 left over).
    Returns {"b0_doc", "b0_record", "b8_doc", "b8_record"}."""
    from home_manager.documents.extraction import looks_like_several
    from home_manager.documents.receipt_schema import TextLine
    manager.configure_household(manager.household.model_copy(update={"home_currency": "USD", "auto_identify_items": False}))
    found = {}
    for key, stub in (("b0", breakfast_stub), ("b8", b8_stub)):
        texts, indents, replies = stub()
        if not looks_like_several([TextLine(id=f"line-{number}", text=text, block_ids=[]) for number, text in enumerate(texts, 1)]):
            replies.pop("ReceiptStarts", None)
        found[f"{key}_doc"], found[f"{key}_record"] = record_dining(manager, model, f"{key}-dining.png", texts, indents, replies)
    return found
